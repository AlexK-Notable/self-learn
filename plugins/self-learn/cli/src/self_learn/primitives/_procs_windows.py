"""Windows synchronous children. Each launch owns one kill-on-close job."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from io import BytesIO
from typing import Any, Mapping, Sequence, cast
from uuid import uuid4

from .procs import BoundedTimeout, OutputLimitExceeded, ProcessIdentity

if sys.platform == "win32":
    import _winapi
    import ctypes
    from ctypes import wintypes
    import pywintypes
    import win32api
    import win32con
    import win32event
    import win32file
    import win32job
    import win32pipe
    import win32process
    import winerror
else:
    raise NotImplementedError("native Windows process operations require Windows")


_launch_lock = threading.Lock()
_CLEANUP_SECONDS = 5
_CHUNK = 65536


@contextmanager
def _os_errors(filename=None):
    """Present Win32 diagnostics through the subprocess OSError interface."""
    try:
        yield
    except (pywintypes.error, OSError) as exc:
        code = getattr(exc, "winerror", None)
        if code is None:
            raise
        error = OSError(0, exc.strerror, getattr(exc, "filename", None) or filename, code)
        for note in getattr(exc, "__notes__", ()):
            error.add_note(note)
        raise error from exc


@contextmanager
def _cleanup_after(primary):
    try:
        yield
    except BaseException as error:
        if primary is None:
            raise
        primary.add_note(f"Windows process cleanup: {error!r}")


class _Handles(ExitStack):
    """Close every registered handle, keeping a pending caller error primary."""

    def __exit__(self, exc_type, exc, tb):
        with _cleanup_after(exc):
            return super().__exit__(exc_type, exc, tb)
        return False


def _wait_until(process, deadline):
    millis = math.ceil(max(0, deadline - time.monotonic()) * 1000)
    return win32event.WaitForSingleObject(process, millis) == win32event.WAIT_OBJECT_0


def _reap_after_failed_launch(process, failure):
    if not _wait_until(process, time.monotonic() + _CLEANUP_SECONDS):
        failure.add_note("terminated Windows child did not exit within the cleanup budget")


def _pipe(parents, children, *, child_reads=False):
    security = pywintypes.SECURITY_ATTRIBUTES()
    security.bInheritHandle = False
    reader, writer = win32pipe.CreatePipe(security, 0)
    child, parent = (reader, writer) if child_reads else (writer, reader)
    children.callback(win32api.CloseHandle, child)
    parents.callback(win32api.CloseHandle, parent)
    os.set_handle_inheritable(int(child), True)
    return child, parent


def _stdin(children, inherit):
    source = _winapi.GetStdHandle(win32api.STD_INPUT_HANDLE) if inherit else None
    if not source or source == -1:
        security = pywintypes.SECURITY_ATTRIBUTES()
        security.bInheritHandle = True
        handle = win32file.CreateFile(os.devnull, win32con.GENERIC_READ,
                                      win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                      security, win32con.OPEN_EXISTING, 0, None)
        children.callback(win32api.CloseHandle, handle)
        return int(cast(Any, handle))
    current = win32api.GetCurrentProcess()
    handle = win32api.DuplicateHandle(current, source, current, 0, True, win32con.DUPLICATE_SAME_ACCESS)
    children.callback(win32api.CloseHandle, handle)
    return handle


def _executable(program, cwd, env):
    if os.path.dirname(program):
        return shutil.which(os.path.join(cwd, program) if cwd else program)

    # which(bare_name) on Windows may prepend "." even with an explicit PATH.
    # Compare directory identities so spelling or junctions cannot reintroduce cwd.
    excluded = {os.path.normcase(os.path.realpath(path)) for path in (os.curdir, cwd or os.curdir)}
    environment = env if env is not None else os.environ
    extensions = environment.get("PATHEXT") or os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    suffixes = [ext for ext in extensions.split(os.pathsep) if ext]
    names = [program + ext for ext in suffixes]
    if program.lower().endswith(tuple(ext.lower() for ext in suffixes)):
        names.insert(0, program)
    for entry in environment.get("PATH", "").split(os.pathsep):
        if not entry or entry == os.curdir:
            continue
        directory = os.path.realpath(entry)
        if os.path.normcase(directory) in excluded:
            continue
        for name in names:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def _launch(handles, argv, cwd, env, input_data, inherit):
    executable = _executable(argv[0], cwd, env)
    if executable is None:
        raise ctypes.WinError(winerror.ERROR_FILE_NOT_FOUND)
    # CreateProcess can hand batch files to cmd.exe even with shell=False.
    if executable.lower().endswith((".bat", ".cmd")):
        raise ctypes.WinError(winerror.ERROR_BAD_EXE_FORMAT,
                              f"Cannot launch batch shim without a shell: {executable}")

    # pywin32 312 requires a string name and returns a PyHANDLE.
    job = cast(Any, win32job.CreateJobObject(None, uuid4().hex))
    handles.callback(win32api.CloseHandle, job)
    info_class = win32job.JobObjectExtendedLimitInformation
    info = win32job.QueryInformationJobObject(job, info_class)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, info_class, info)

    process = thread = None

    def close_process_handles():
        with _Handles() as closing:
            if process is not None:
                closing.callback(win32api.CloseHandle, process)
            if thread is not None:
                win32api.CloseHandle(thread)

    # Install the cleanup before CreateProcess can return a suspended child.
    handles.callback(close_process_handles)
    pipe_owners = [handles.enter_context(_Handles()) for _ in range(3)]
    stdin_writer = None
    with _launch_lock, _Handles() as children:
        startup = win32process.STARTUPINFO()
        startup.dwFlags = win32process.STARTF_USESTDHANDLES
        startup.hStdOutput, stdout = _pipe(pipe_owners[0], children)
        startup.hStdError, stderr = _pipe(pipe_owners[1], children)
        if input_data is None:
            startup.hStdInput = _stdin(children, inherit)
        else:
            startup.hStdInput, stdin_writer = _pipe(pipe_owners[2], children, child_reads=True)
        try:
            process, thread, _, _ = win32process.CreateProcess(
                executable, subprocess.list2cmdline(argv), None, None, True,
                win32process.CREATE_SUSPENDED | win32process.CREATE_UNICODE_ENVIRONMENT,
                env, cwd, startup,
            )
            win32job.AssignProcessToJobObject(job, process)
        except BaseException as failure:
            if process is not None:
                with _cleanup_after(failure):
                    win32process.TerminateProcess(process, 1)
                    _reap_after_failed_launch(process, failure)
            raise
        try:
            win32process.ResumeThread(thread)
        except BaseException as failure:
            with _cleanup_after(failure):
                win32job.TerminateJobObject(job, 1)
                _reap_after_failed_launch(process, failure)
            raise
    return job, process, stdout, stderr, stdin_writer, pipe_owners


# pywin32 has OpenThread but no CancelSynchronousIo binding.
_cancel_io = ctypes.WinDLL("kernel32", use_last_error=True).CancelSynchronousIo
_cancel_io.argtypes = [wintypes.HANDLE]
_cancel_io.restype = wintypes.BOOL


def _join_pipes(threads, active, changed, stopping, deadline) -> bool:
    # Reserve time for cancellation of a read/write held open outside the job.
    grace = (time.monotonic() + deadline) / 2
    for thread in threads:
        if thread.ident is not None:
            thread.join(max(0, grace - time.monotonic()))
    if not any(thread.is_alive() for thread in threads):
        return True
    stopping.set()
    # A worker removes its ID under this lock before exiting, preventing reuse.
    # ERROR_NOT_FOUND can also mean we raced between its stop check and ReadFile.
    # Retry pending workers until the same cleanup deadline.
    with changed:
        interrupted = bool(active)
        while active:
            for tid in active:
                handle = win32api.OpenThread(win32con.THREAD_TERMINATE, False, tid)
                with _Handles() as opened:
                    opened.callback(win32api.CloseHandle, handle)
                    if not _cancel_io(int(handle)):
                        code = ctypes.get_last_error()
                        if code != winerror.ERROR_NOT_FOUND:
                            raise ctypes.WinError(code)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            changed.wait(min(.025, remaining))
    for thread in threads:
        if thread.ident is not None:
            thread.join(max(0, deadline - time.monotonic()))
    return not interrupted and not any(thread.is_alive() for thread in threads)


def _capture(argv, timeout, cwd, env, data, inherit, limit):
    buffers = [BytesIO(), BytesIO()]
    changed = threading.Condition()
    active: set[int] = set()
    stopping = threading.Event()
    failures: list[BaseException] = []
    threads: list[threading.Thread] = []
    finished = 0
    total = 0

    def read(handle, buffer):
        nonlocal total
        while True:
            with changed:
                if failures or stopping.is_set():
                    return
                # Both in-flight reads together fit in one 64 KiB chunk,
                # including while their bytes are copied to the capture buffers.
                size = _CHUNK if limit is None else min(_CHUNK // 2, limit - total + 1)
            # A synchronous anonymous-pipe read returns available bytes immediately.
            _, chunk = win32file.ReadFile(handle, size)
            if not chunk:
                return
            with changed:
                if failures or stopping.is_set():
                    return
                if limit is not None:
                    if total + len(chunk) > limit:
                        failures.append(OutputLimitExceeded(f"child output exceeded {limit} bytes"))
                        changed.notify()
                        return
                    total += len(chunk)
                buffer.write(chunk)
                del chunk

    def write(handle):
        for pos in range(0, len(data), _CHUNK):
            if stopping.is_set():
                return
            win32file.WriteFile(handle, data[pos:pos + _CHUNK])

    def worker(owners, fn, args):
        nonlocal finished
        tid = threading.get_native_id()
        try:
            # Only this worker can close a handle with synchronous I/O pending.
            # Unstarted workers leave their endpoints on the supervisor's stack.
            with owners.pop_all():
                with changed:
                    active.add(tid)
                try:
                    fn(*args)
                except pywintypes.error as exc:
                    eof = exc.winerror in (winerror.ERROR_BROKEN_PIPE, winerror.ERROR_NO_DATA)
                    cancelled = stopping.is_set() and exc.winerror == winerror.ERROR_OPERATION_ABORTED
                    if not eof and not cancelled:
                        raise
        except BaseException as exc:
            with changed:
                failures.append(exc)
        finally:
            with changed:
                active.discard(tid)
                finished += 1
                changed.notify()

    with _Handles() as handles:
        job, process, stdout, stderr, writer, owners = _launch(handles, argv, cwd, env, data, inherit)
        deadline = time.monotonic() + timeout
        tasks: list[tuple[str, Callable, tuple]] = [
            ("stdout", read, (stdout, buffers[0])), ("stderr", read, (stderr, buffers[1])),
        ]
        if writer is not None:
            tasks.append(("stdin", write, (writer,)))
        primary = None
        try:
            for owner, (name, fn, args) in zip(owners, tasks):
                thread = threading.Thread(target=worker, args=(owner, fn, args),
                                          name=f"bounded-{name}", daemon=True)
                threads.append(thread)
                thread.start()
            with changed:
                completed = changed.wait_for(lambda: bool(failures) or finished == len(tasks),
                                             max(0, deadline - time.monotonic()))
                if failures:
                    raise failures[0]
            if not completed or not _wait_until(process, deadline):
                if inherit:
                    raise subprocess.TimeoutExpired(argv, timeout)
                raise BoundedTimeout(argv, timeout) from None
        except BaseException as error:
            primary = error
            raise
        finally:
            cleanup = time.monotonic() + _CLEANUP_SECONDS
            if primary is not None:
                with _cleanup_after(primary):
                    win32job.TerminateJobObject(job, 1)
                    if not _wait_until(process, cleanup):
                        raise RuntimeError("terminated Windows child did not exit")
            with _cleanup_after(primary):
                if not _join_pipes(threads, active, changed, stopping, cleanup):
                    raise RuntimeError("Windows pipe worker exceeded its cleanup deadline")
            if inherit and isinstance(primary, subprocess.TimeoutExpired):
                primary.output = buffers[0].getvalue() or None
                primary.stderr = buffers[1].getvalue() or None

        return win32process.GetExitCodeProcess(process), buffers[0].getvalue(), buffers[1].getvalue()


def _text(data: bytes, program: str) -> str:
    errors = "replace" if os.path.basename(program).lower() in ("git", "git.exe") else "strict"
    return data.decode("utf-8", errors).replace("\r\n", "\n").replace("\r", "\n")


def run_bounded(
    argv: Sequence[str], *, timeout: float, cwd: str | None = None,
    env: Mapping[str, str] | None = None, input: str | bytes | None = None,
    check: bool = False, binary: bool = False, max_output_bytes: int | None = None,
) -> subprocess.CompletedProcess:
    if binary and isinstance(input, str):
        raise ValueError("run_bounded: binary=True requires input to be bytes or None, not str")
    if max_output_bytes is not None and (
        max_output_bytes <= 0 or not binary or input is not None
    ):
        raise ValueError("run_bounded: output limit requires a positive budget, binary=True and no input")
    argv = list(argv)
    data = input.encode("utf-8") if isinstance(input, str) else input
    environment = {k.upper(): v for k, v in env.items()} if env is not None else None
    with _os_errors(argv[0]):
        code, out, err = _capture(argv, timeout, cwd, environment, data, False, max_output_bytes)
    if not binary and not isinstance(input, (bytes, bytearray)):
        out, err = _text(out, argv[0]), _text(err, argv[0])
    result = subprocess.CompletedProcess(argv, code, out, err)
    if check:
        result.check_returncode()
    return result


def run_command(argv: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    with _os_errors(argv[0]):
        code, out, err = _capture(argv, timeout, None, None, None, True, None)
    return subprocess.CompletedProcess(argv, code, _text(out, argv[0]), _text(err, argv[0]))


@_os_errors()
def pid_alive(pid: int) -> bool:
    if pid <= 0 or pid > 0xffffffff:
        return False
    try:
        handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
    except pywintypes.error as exc:
        if exc.winerror == winerror.ERROR_INVALID_PARAMETER:
            return False
        if exc.winerror == winerror.ERROR_ACCESS_DENIED:
            return True
        raise
    with _Handles() as handles:
        handles.callback(win32api.CloseHandle, handle)
        return win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_TIMEOUT


# S-174: identify and contain a child that someone else spawned
# (the Agent SDK's Claude Code child), and make this process's own
# descendants die with it.

# SYNCHRONIZE tells an exited process apart: its image can no longer be read
# (QueryFullProcessImageNameW fails with ERROR_GEN_FAILURE, measured on the
# runner) even while another handle keeps the process object.
_PROCESS_QUERY = win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE
# AssignProcessToJobObject needs PROCESS_SET_QUOTA and PROCESS_TERMINATE;
# SYNCHRONIZE lets terminate_contained wait for the process itself to exit.
_PROCESS_CONTAIN = (win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE
                    | win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE)
_JOB_FLAGS = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
_TERMINATE_SECONDS = 5.0
#: A pass adopts every descendant whose parent was adopted in an earlier
#: pass; a chain deeper than this many generations is left uncovered.
_ADOPTION_PASSES = 16

# pywin32 312 has neither QueryFullProcessImageNameW nor the Toolhelp32
# snapshot calls (checked in the 312 wheel), and its GetProcessTimes rounds the
# creation time to the millisecond (measured on the runner), so these few come
# from kernel32 and ntdll.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_query_image = _kernel32.QueryFullProcessImageNameW
_query_image.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_query_image.restype = wintypes.BOOL
_get_process_times = _kernel32.GetProcessTimes
_get_process_times.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
_get_process_times.restype = wintypes.BOOL
_tick_count = _kernel32.GetTickCount64
_tick_count.argtypes = []
_tick_count.restype = ctypes.c_uint64
_precise_now = _kernel32.GetSystemTimePreciseAsFileTime
_precise_now.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
_precise_now.restype = None
_snapshot = _kernel32.CreateToolhelp32Snapshot
_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_snapshot.restype = wintypes.HANDLE
_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_ntdll = ctypes.WinDLL("ntdll")


class _BasicInformation(ctypes.Structure):
    _fields_ = [("ExitStatus", ctypes.c_long), ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_size_t), ("BasePriority", ctypes.c_long),
                ("UniqueProcessId", ctypes.c_size_t), ("InheritedFromUniqueProcessId", ctypes.c_size_t)]


_query_process = _ntdll.NtQueryInformationProcess
_query_process.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                           ctypes.POINTER(wintypes.ULONG)]
_query_process.restype = ctypes.c_long
_status_to_error = _ntdll.RtlNtStatusToDosError
_status_to_error.argtypes = [ctypes.c_long]
_status_to_error.restype = wintypes.ULONG


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


_first_entry = _kernel32.Process32FirstW
_next_entry = _kernel32.Process32NextW
for _walk in (_first_entry, _next_entry):
    _walk.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    _walk.restype = wintypes.BOOL
_close_handle = _kernel32.CloseHandle
_close_handle.argtypes = [wintypes.HANDLE]
_close_handle.restype = wintypes.BOOL


def _filetime(value: wintypes.FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _now() -> int:
    """The precise system time as FILETIME ticks: the clock that stamps a
    process's creation time (measured on the runner: every creation time fell
    strictly between a reading taken before the spawn and one taken after)."""
    now = wintypes.FILETIME()
    _precise_now(ctypes.byref(now))
    return _filetime(now)


def _open_process(pid, rights):
    """An open process handle, or ``None`` when *pid* names no process."""
    if pid <= 0 or pid > 0xffffffff:
        return None
    try:
        return win32api.OpenProcess(rights, False, pid)
    except pywintypes.error as exc:
        if exc.winerror == winerror.ERROR_INVALID_PARAMETER:
            return None
        raise


def _image_of(process) -> str:
    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not _query_image(int(process), 0, buffer, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def _created_of(process) -> int:
    created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if not _get_process_times(int(process), ctypes.byref(created), ctypes.byref(exited),
                              ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    return _filetime(created)


def _parent_of(process) -> int:
    """The parent PID recorded in the process object behind *process* (not a
    snapshot row, which may describe an earlier owner of the same number)."""
    info = _BasicInformation()
    status = _query_process(int(process), 0, ctypes.byref(info), ctypes.sizeof(info), None)
    if status < 0:  # NT_SUCCESS is status >= 0
        raise ctypes.WinError(_status_to_error(status))
    return info.InheritedFromUniqueProcessId


def _identity_of(process) -> ProcessIdentity:
    return ProcessIdentity(image=_image_of(process), created=_created_of(process))


def _exited(process) -> bool:
    return win32event.WaitForSingleObject(process, 0) == win32event.WAIT_OBJECT_0


def _live_identity(process) -> ProcessIdentity | None:
    """The identity of a running process; ``None`` once it has exited."""
    if _exited(process):
        return None
    try:
        return _identity_of(process)
    except OSError:
        if _exited(process):  # it exited while we read it
            return None
        raise


@_os_errors()
def process_identity(pid: int) -> ProcessIdentity | None:
    try:
        process = _open_process(pid, _PROCESS_QUERY)
    except pywintypes.error as exc:
        if exc.winerror == winerror.ERROR_ACCESS_DENIED:
            return None
        raise
    if process is None:
        return None
    with _Handles() as handles:
        handles.callback(win32api.CloseHandle, process)
        return _live_identity(process)


def _new_job():
    # pywin32 312 requires a string name and returns a PyHANDLE.
    job = cast(Any, win32job.CreateJobObject(None, uuid4().hex))
    try:
        info_class = win32job.JobObjectExtendedLimitInformation
        info = win32job.QueryInformationJobObject(job, info_class)
        info["BasicLimitInformation"]["LimitFlags"] |= _JOB_FLAGS
        win32job.SetInformationJobObject(job, info_class, info)
    except BaseException as failure:
        with _cleanup_after(failure):
            win32api.CloseHandle(job)
        raise
    return job


def _process_parents() -> list[tuple[int, int]]:
    """(pid, parent pid) for every process, from one Toolhelp32 snapshot.
    The parent column is only a hint: a row can describe a process that has
    since exited and whose number now belongs to another."""
    snapshot = _snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot is None or snapshot == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    pairs = []
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        more = _first_entry(snapshot, ctypes.byref(entry))
        while more:
            pairs.append((entry.th32ProcessID, entry.th32ParentProcessID))
            more = _next_entry(snapshot, ctypes.byref(entry))
        code = ctypes.get_last_error()
        if code != winerror.ERROR_NO_MORE_FILES:
            raise ctypes.WinError(code)
    except BaseException as failure:
        if not _close_handle(snapshot):
            secondary = ctypes.WinError(ctypes.get_last_error())
            failure.add_note(f"Windows snapshot cleanup: {secondary!r}")
            setattr(failure, "secondary_winerror", secondary.winerror)
        raise
    if not _close_handle(snapshot):
        raise ctypes.WinError(ctypes.get_last_error())
    return pairs


class _Member:
    """A process known to be in the child's tree, pinned by an open handle so
    its number cannot pass to another process while we rely on it."""

    def __init__(self, process, created, cutoff, in_any_job, in_self_job):
        self.process = process
        self.created = created
        #: A child of this member that is outside the job counts as missed
        #: (spawned before the member joined) only if created before this.
        self.cutoff = cutoff
        self.in_any_job = in_any_job
        self.in_self_job = in_self_job


def _job_states(process):
    in_any = win32job.IsProcessInJob(process, cast(Any, None))  # None: any job
    in_self = bool(_self_job) and win32job.IsProcessInJob(process, _self_job[0])
    return in_any, in_self


def _judge(job, tree, pid, owner):
    """Open *pid*, decide on that handle whether it is ours, and adopt it.
    Every member and result is published into *owner* as soon as it exists,
    so an interrupted sweep leaves the owner complete up to that point.
    Returns True when the tree grew."""
    process = _open_process(pid, _PROCESS_CONTAIN)
    if process is None:  # already gone
        return False
    with _Handles() as handles:
        handles.callback(win32api.CloseHandle, process)
        if _exited(process):
            return False
        created = _created_of(process)
        if win32job.IsProcessInJob(process, job):
            # Born in the job: ours by construction. Anything it spawned
            # outside the job broke away, so its cutoff is its own birth.
            handles.pop_all()
            owner._processes.append(process)
            tree[pid] = _Member(process, created, created, *_job_states(process))
            return True
        parent = tree.get(_parent_of(process))
        if parent is None:
            return False  # the snapshot row was stale; this is someone else
        # The parent is pinned, so from its creation until now no other process
        # held its number: a later-created process naming it is its child.
        if created <= parent.created:
            owner.left_out += ((pid, "not-younger-than-parent"),)
            return False
        if created >= parent.cutoff:
            owner.left_out += ((pid, "spawned-after-parent-joined"),)
            return False
        in_any, in_self = _job_states(process)
        if (parent.in_self_job and not in_self) or (parent.in_any_job and not in_any):
            owner.left_out += ((pid, "outside-its-parents-job"),)
            return False
        # Published before the call, so an interruption during or right after
        # it leaves the owner holding this member (perhaps not yet assigned:
        # terminate_contained waits only on members that are in the job).
        handles.pop_all()
        owner._processes.append(process)
        owner.adopted += (pid,)
        try:
            win32job.AssignProcessToJobObject(job, process)
        except pywintypes.error as exc:
            owner._processes.remove(process)
            owner.adopted = tuple(p for p in owner.adopted if p != pid)
            owner.uncovered += ((pid, exc.winerror),)
            win32api.CloseHandle(process)
            return False
        # Sampled after the assignment returns: a normal child it spawned while
        # the call ran did not inherit the job and is still taken as early.
        tree[pid] = _Member(process, created, _now(), in_any, in_self)
        return True


def _adopt_descendants(job, root_pid, root, owner):
    """Assign to *job* the descendants of *root_pid* that were spawned before it
    joined (they did not inherit the job), publishing into *owner*: its
    ``adopted``, ``uncovered`` (``(pid, winerror)``; pid 0: the snapshot failed,
    and a second pid-0 entry for a failed snapshot close) and ``left_out``
    (``(pid, reason)``: not provably ours). Returns whether the sweep finished.

    A candidate is judged on its own open handle: its parent is read from the
    process object, that parent must be a pinned member of the tree, the
    candidate must be strictly younger than the parent and created before the
    moment just after the parent's assignment returned, and it must not have
    left a job its parent was in (a deliberate breakaway). A child the parent
    starts with breakaway while its own assignment call is running is taken
    too: that instant cannot be told apart from a normal early child.
    Per-candidate failures are reported, never raised: the child is already
    in the job, and a failed sweep must not cost it its life. The sweep sees
    what one snapshot per pass sees; an empty report is not proof that every
    descendant was found."""
    tree = {root_pid: root}
    judged = {root_pid}
    for _ in range(_ADOPTION_PASSES):
        grew = False
        try:
            rows = _process_parents()
        except OSError as exc:
            owner.uncovered += ((0, getattr(exc, "winerror", None) or 0),)
            secondary = getattr(exc, "secondary_winerror", None)
            if secondary:
                owner.uncovered += ((0, secondary),)
            return False
        for pid, parent in rows:
            if parent not in tree or pid in judged:
                continue
            judged.add(pid)
            try:
                grew = _judge(job, tree, pid, owner) or grew
            except (pywintypes.error, OSError) as exc:
                owner.uncovered += ((pid, getattr(exc, "winerror", None) or 0),)
        if not grew:
            return True
    return False


class ContainedChild:
    """A kill-on-close job holding a child and its adopted descendants.

    Keep this object for as long as the child should live: when it is
    released (garbage-collected, or this process dies), Windows closes the
    job and kills everything in it. Every member it relies on is pinned by an
    open handle, so their numbers cannot pass to other processes meanwhile."""

    def __init__(self, pid, identity, job, process):
        self.pid = pid
        self.identity = identity
        self.adopted: tuple[int, ...] = ()
        self.uncovered: tuple[tuple[int, int], ...] = ()
        self.left_out: tuple[tuple[int, str], ...] = ()
        #: False when the adoption sweep did not run to a pass with no growth.
        self.complete = False
        self._job = job
        #: The child's handle first, then every other pinned member's.
        self._processes = [process]

    @property
    def released(self) -> bool:
        return self._job is None


#: Handles whose contain_child call was interrupted after the child was in the
#: job: kept here so the job (and the child) survive until the caller recovers
#: them from the exception's ``contained_child`` or terminates them.
unclaimed: list[ContainedChild] = []


def contain_child(pid: int, *, expect: ProcessIdentity | None = None) -> ContainedChild | None:
    # The one place any exception leaves this call: whatever it has become by
    # now (a native error is re-raised as a new OSError), it carries the owner
    # of a job that already holds the child.
    owners: list[ContainedChild] = []
    try:
        return _contain_child(pid, expect, owners)
    except BaseException as failure:
        if owners:
            setattr(failure, "contained_child", owners[0])
        raise


@_os_errors()
def _contain_child(pid, expect, owners):
    process = _open_process(pid, _PROCESS_CONTAIN)
    if process is None:
        return None
    with _Handles() as handles:
        handles.callback(win32api.CloseHandle, process)
        identity = _live_identity(process)
        if identity is None or (expect is not None and identity != expect):
            return None
        in_any, in_self = _job_states(process)
        # Still empty if assignment fails, so closing it kills nothing.
        job = _new_job()
        handles.callback(win32api.CloseHandle, job)
        handle = ContainedChild(pid, identity, job, process)
        handles.pop_all()
    try:
        win32job.AssignProcessToJobObject(job, process)
        # Sampled after the assignment returns: see _adopt_descendants.
        root = _Member(process, identity.created, _now(), in_any, in_self)
        handle.complete = _adopt_descendants(job, pid, root, handle)
    except BaseException as failure:
        _hand_over_or_release(handle, failure, owners)
        raise
    return handle


def _hand_over_or_release(handle, failure, owners):
    try:
        contained = win32job.IsProcessInJob(handle._processes[0], handle._job)
    except BaseException as error:
        failure.add_note(f"Windows job membership check: {error!r}")
        contained = True  # unsure: keep the child alive
    if contained:
        # The child may be in the job: closing it now would kill the child.
        unclaimed.append(handle)
        owners.append(handle)
        failure.add_note(f"PID {handle.pid} stays contained; recover it from "
                         "the exception's contained_child or terminate it")
        return
    _release(handle, failure)


def _release(handle, failure=None):
    processes, job = handle._processes, handle._job
    handle._job, handle._processes = None, []
    with _cleanup_after(failure), _Handles() as handles:
        for process in processes:
            handles.callback(win32api.CloseHandle, process)
        if job is not None:
            handles.callback(win32api.CloseHandle, job)


def _member_of(process, job) -> bool:
    try:
        return win32job.IsProcessInJob(process, job)
    except pywintypes.error:
        return True  # unsure: wait for it rather than return early


def _active_processes(job) -> int:
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)
    return info["ActiveProcesses"]


@_os_errors()
def terminate_contained(handle: ContainedChild | None, *, timeout: float = _TERMINATE_SECONDS) -> None:
    if handle is None:
        return
    job, processes = handle._job, handle._processes
    if job is None:
        return
    handle._job, handle._processes = None, []
    if handle in unclaimed:
        unclaimed.remove(handle)
    with _Handles() as handles:
        for process in processes:
            handles.callback(win32api.CloseHandle, process)
        handles.callback(win32api.CloseHandle, job)
        # A handed-over owner can hold a process whose assignment never took
        # effect; it is not ours to wait for (or to kill).
        processes = [process for process in processes if _member_of(process, job)]
        win32job.TerminateJobObject(job, 1)
        deadline = time.monotonic() + timeout
        # The job's count can reach zero a moment before a process object is
        # signalled; wait for both, on handles, never on a PID.
        for process in processes:
            if not _wait_until(process, deadline):
                break
        while _active_processes(job):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"contained job for PID {handle.pid} still has processes after {timeout} s")
            time.sleep(.01)
        if not all(_wait_until(process, time.monotonic()) for process in processes):
            raise TimeoutError(f"contained job for PID {handle.pid} still has processes after {timeout} s")


#: The raw self-job handle. Detached from its PyHANDLE so that Python never
#: closes it, not even while finalizing: the kernel closes it when the process
#: has ended (exit status already set) and the job then kills the descendants.
_self_job: list[int] = []
_self_lock = threading.Lock()


@_os_errors()
def contain_self() -> bool:
    with _self_lock:
        if _self_job:
            return True
        # Detached before this process joins, so no Python object ever owns a
        # handle to a job that holds this process: an interruption anywhere
        # below cannot close it through a finalizer.
        job = _new_job().Detach()
        current = win32api.GetCurrentProcess()
        try:
            win32job.AssignProcessToJobObject(job, current)
            _self_job.append(job)
        except BaseException as failure:
            try:
                joined = win32job.IsProcessInJob(current, job)
            except BaseException as error:
                failure.add_note(f"Windows job membership check: {error!r}")
                joined = True  # unsure: closing it could kill this process
            if joined:
                if job not in _self_job:
                    _self_job.append(job)
                failure.add_note("this process is in its self job; contain_self will not make another")
            else:
                with _cleanup_after(failure):
                    win32api.CloseHandle(job)
            raise
        return True


#: Tolerance for comparing a creation time with the boot time, which is
#: derived from the uptime counter (a timer of about 16 ms resolution).
_BOOT_MARGIN = 10_000_000  # one second, in FILETIME ticks


def identity_predates_boot(identity: ProcessIdentity) -> bool:
    if identity.created is None:
        return False
    boot = _now() - _tick_count() * 10_000
    return identity.created <= boot + _BOOT_MARGIN


# S-NEXT-w7-procs: detached background runs (the worker, the miner, the
# notifier) and asyncio children whose whole tree the caller owns (the web UI).
# Self-contained: it adds names and changes none above.

import msvcrt  # noqa: E402 - Windows-only, and this module is Windows-only
import signal  # noqa: E402
import weakref  # noqa: E402

from .procs import STOP_EVENT_ENV, DetachedChild  # noqa: E402

#: The child gets a console of its own without a window. Not DETACHED_PROCESS:
#: Windows ignores CREATE_NO_WINDOW next to it, and a child with no console
#: makes every console program it starts (git, python) open a new console,
#: which on a desktop is a window (measured on the runner: such a grandchild
#: shares no console with its parent).
_DETACHED_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
#: Write access that only appends: every write lands at the end of the file,
#: whatever any writer's file pointer says, so concurrent runs never overwrite
#: each other's lines.
_FILE_APPEND_DATA = 0x0004


def _program(argv, cwd, env):
    """The checked image for *argv*: the same rules as ``_launch`` (a bare
    name is looked up on PATH only, never the current folder; ``.bat`` and
    ``.cmd`` are refused), raised as OSErrors that carry ``winerror``."""
    executable = _executable(argv[0], cwd, env)
    if executable is None:
        raise ctypes.WinError(winerror.ERROR_FILE_NOT_FOUND)
    if executable.lower().endswith((".bat", ".cmd")):
        raise ctypes.WinError(winerror.ERROR_BAD_EXE_FORMAT,
                              f"Cannot launch batch shim without a shell: {executable}")
    return executable


def _popen(argv, executable, cwd, env, flags, stdin, stdout, stderr):
    """The one ``subprocess.Popen`` of this module. With all three standard
    handles given and ``close_fds=True``, CPython passes exactly those three
    in ``PROC_THREAD_ATTRIBUTE_HANDLE_LIST``: the child inherits nothing else,
    whatever else in this process is inheritable."""
    return subprocess.Popen(argv, executable=executable, cwd=cwd, env=env, stdin=stdin,
                            stdout=stdout, stderr=stderr, creationflags=flags, close_fds=True)


def _open_log(path) -> int:
    """A C descriptor for *path* opened for appending only (created when
    missing), shareable for reading, writing and deletion."""
    handle = win32file.CreateFile(
        os.fspath(path), _FILE_APPEND_DATA,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None, win32con.OPEN_ALWAYS, win32con.FILE_ATTRIBUTE_NORMAL, None)
    try:
        descriptor = msvcrt.open_osfhandle(int(cast(Any, handle)), os.O_WRONLY)
    except BaseException:
        win32api.CloseHandle(cast(Any, handle))
        raise
    cast(Any, handle).Detach()  # the descriptor owns the handle now
    return descriptor


def _in_a_job() -> bool:
    return bool(win32job.IsProcessInJob(win32api.GetCurrentProcess(), cast(Any, None)))


def _child_in_a_job(pid) -> bool:
    """Whether our just-started child is in any job. Its Popen object holds
    the process open, so the PID still names it."""
    process = _open_process(pid, win32con.PROCESS_QUERY_LIMITED_INFORMATION)
    if process is None:
        raise ctypes.WinError(winerror.ERROR_INVALID_PARAMETER, f"PID {pid} vanished")
    with _Handles() as handles:
        handles.callback(win32api.CloseHandle, process)
        return bool(win32job.IsProcessInJob(process, cast(Any, None)))


def _started(proc, broke_away) -> DetachedChild:
    return DetachedChild(proc.pid, broke_away, _child_in_a_job(proc.pid))


@_os_errors()
def spawn_detached(argv, *, cwd=None, env=None, log_path=None) -> DetachedChild:
    argv = list(argv)
    environment = {k.upper(): v for k, v in env.items()} if env is not None else None
    executable = _program(argv, cwd, environment)
    with ExitStack() as stack:
        if log_path is None:
            stdout: Any = subprocess.DEVNULL
            stderr: Any = subprocess.DEVNULL
        else:
            stdout = _open_log(log_path)
            stack.callback(os.close, stdout)
            stderr = subprocess.STDOUT

        def launch(flags):
            return _popen(argv, executable, cwd, environment, flags, subprocess.DEVNULL, stdout, stderr)

        if not _in_a_job():
            return _started(launch(_DETACHED_FLAGS), None)
        try:
            proc = launch(_DETACHED_FLAGS | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError as exc:
            if getattr(exc, "winerror", None) != winerror.ERROR_ACCESS_DENIED:
                raise
        else:
            # Out of this process's job; a job that one is nested in may still
            # hold it. DetachedChild.in_job says which.
            return _started(proc, True)
        # The job forbids breakaway: the child starts inside it and lives only
        # as long as the job does. DetachedChild says so.
        return _started(launch(_DETACHED_FLAGS), False)


def breakaway_allowed() -> bool | None:
    try:
        if not _in_a_job():
            return True
        # A job this one is nested in can forbid what this one allows, and
        # only some of them can be queried; a trial child answers for all.
        # It is created suspended, with no console, and killed before it runs.
        probe = _popen([sys.executable], sys.executable, None, None,
                       win32process.CREATE_SUSPENDED | subprocess.DETACHED_PROCESS
                       | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                       subprocess.DEVNULL, subprocess.DEVNULL, subprocess.DEVNULL)
    except OSError as exc:
        return False if getattr(exc, "winerror", None) == winerror.ERROR_ACCESS_DENIED else None
    except pywintypes.error:
        return None
    try:
        contained = _child_in_a_job(probe.pid)
    except (OSError, pywintypes.error):
        contained = None
    finally:
        try:
            probe.kill()
            probe.wait(_CLEANUP_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None if contained is None else not contained


# --------------------------------------------------- owned asyncio children

_TH32CS_SNAPTHREAD = 0x4


class _ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wintypes.DWORD)]


_first_thread = _kernel32.Thread32First
_next_thread = _kernel32.Thread32Next
for _walk in (_first_thread, _next_thread):
    _walk.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
    _walk.restype = wintypes.BOOL
_console_processes = _kernel32.GetConsoleProcessList
_console_processes.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
_console_processes.restype = wintypes.DWORD


def _has_console() -> bool:
    """Whether this process is attached to a console (the call fails, and
    returns 0, when it is not)."""
    buffer = (wintypes.DWORD * 1)()
    return _console_processes(buffer, 1) != 0


def _threads_of(pid) -> list[int]:
    """The thread IDs of *pid*, from one Toolhelp32 snapshot."""
    snapshot = _snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot is None or snapshot == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    threads = []
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(_ThreadEntry)
        more = _first_thread(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                threads.append(entry.th32ThreadID)
            more = _next_thread(snapshot, ctypes.byref(entry))
        code = ctypes.get_last_error()
        if code != winerror.ERROR_NO_MORE_FILES:
            raise ctypes.WinError(code)
    finally:
        _close_handle(snapshot)
    return threads


def _resume(pid) -> None:
    """Resume the suspended first thread of a process we created suspended
    and still hold open (so neither its PID nor its thread can be reused)."""
    threads = _threads_of(pid)
    if not threads:
        raise ctypes.WinError(winerror.ERROR_INVALID_PARAMETER, f"no thread to resume in PID {pid}")
    for tid in threads:
        thread = win32api.OpenThread(win32con.THREAD_SUSPEND_RESUME, False, tid)
        try:
            win32process.ResumeThread(thread)
        finally:
            win32api.CloseHandle(thread)


class _Owned:
    """The job, stop event and pinned process handle behind one owned child.
    Released when the asyncio process object goes (the registry holds it
    weakly), which closes the job and so kills whatever is left in it."""

    def __init__(self, job, process, event, shares_console):
        self.job: Any = job
        self.process: Any = process
        self.event: Any = event
        self.shares_console = shares_console

    def release(self):
        handles, self.job, self.process, self.event = (self.job, self.process, self.event), None, None, None
        with _Handles() as closing:
            for handle in handles:
                if handle is not None:
                    closing.callback(win32api.CloseHandle, handle)


#: asyncio process object -> what owns its tree.
_owned: weakref.WeakKeyDictionary[Any, _Owned] = weakref.WeakKeyDictionary()


async def async_owned_child(*argv, env=None, stdin=None, stdout=None, stderr=None):
    # A decorator would cover only the creation of the coroutine, not its run.
    with _os_errors():
        return await _start_owned(list(argv), env, stdin, stdout, stderr)


async def _start_owned(argv, env, stdin, stdout, stderr):
    import asyncio

    environment = {k.upper(): v for k, v in (env if env is not None else os.environ).items()}
    executable = _program(argv, None, environment)
    shares_console = _has_console()
    flags = win32process.CREATE_SUSPENDED | subprocess.CREATE_NEW_PROCESS_GROUP
    if not shares_console:
        flags |= subprocess.CREATE_NO_WINDOW
    name = f"Local\\self-learn-stop-{uuid4().hex}"
    environment[STOP_EVENT_ENV] = name
    with _Handles() as handles:
        job = _new_job()
        handles.callback(win32api.CloseHandle, job)
        event = win32event.CreateEvent(None, True, False, name)
        handles.callback(win32api.CloseHandle, event)
        # Cancelled during this await, asyncio itself kills the (suspended) child.
        proc = await asyncio.create_subprocess_exec(
            *argv, executable=executable, env=environment, stdin=stdin, stdout=stdout,
            stderr=stderr, creationflags=flags)
        try:
            # asyncio holds the process open, so this PID still names our child.
            process = _open_process(proc.pid, _PROCESS_CONTAIN)
            if process is None:
                raise ctypes.WinError(winerror.ERROR_INVALID_PARAMETER, f"PID {proc.pid} vanished")
            handles.callback(win32api.CloseHandle, process)
            win32job.AssignProcessToJobObject(job, process)
            _resume(proc.pid)
        except BaseException as failure:
            with _cleanup_after(failure):
                proc.kill()  # still suspended (or in the job): it never ran our payload
            raise
        handles.pop_all()
    _owned[proc] = _Owned(job, process, event, shares_console)
    return proc


def _job_of(proc):
    owner = _owned.get(proc)
    return owner if owner is not None and owner.job is not None else None


@_os_errors()
def stop_owned(proc, *, hard: bool) -> bool:
    owner = _job_of(proc)
    if owner is None:
        # Not started by async_owned_child (or released): one process, and no
        # soft channel to it.
        if proc.returncode is not None:
            return False
        try:
            proc.kill()
        except ProcessLookupError:
            return False
        return True
    if not _active_processes(owner.job):
        return False
    if hard:
        win32job.TerminateJobObject(owner.job, 1)
        return True
    win32event.SetEvent(owner.event)
    # Only while the leader runs is its PID certainly a live group on our
    # console; a group ID that names no group must never reach this call.
    if owner.shares_console and not _exited(owner.process):
        win32api.GenerateConsoleCtrlEvent(signal.CTRL_BREAK_EVENT, proc.pid)
    return True


async def _empty_the_job(proc, grace: float) -> None:
    import asyncio

    owner = _job_of(proc)
    if owner is None or not _active_processes(owner.job):
        return
    win32job.TerminateJobObject(owner.job, 1)
    deadline = time.monotonic() + grace
    while _active_processes(owner.job) and time.monotonic() < deadline:
        await asyncio.sleep(.01)


async def terminate_owned(proc, *, kill_grace: float, wait_after_lost_kill: bool = False) -> None:
    import asyncio

    if proc.returncode is None and stop_owned(proc, hard=False):
        try:
            await asyncio.wait_for(proc.wait(), timeout=kill_grace)
        except TimeoutError:
            if stop_owned(proc, hard=True) or wait_after_lost_kill:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=kill_grace)
                except TimeoutError:
                    pass
    # The child is gone (or never will be); what it left in the job goes too.
    with _os_errors():
        await _empty_the_job(proc, kill_grace)


def release_owned(proc) -> None:
    owner = _owned.pop(proc, None)
    if owner is not None:
        with _os_errors():
            owner.release()
