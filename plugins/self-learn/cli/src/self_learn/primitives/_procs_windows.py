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
from datetime import datetime, timedelta, timezone
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


# S-NEXT-w6-procs: identify and contain a child that someone else spawned
# (the Agent SDK's Claude Code child), and make this process's own
# descendants die with it.

_PROCESS_QUERY = win32con.PROCESS_QUERY_LIMITED_INFORMATION
# AssignProcessToJobObject needs PROCESS_SET_QUOTA and PROCESS_TERMINATE;
# SYNCHRONIZE lets terminate_contained wait for the process itself to exit.
_PROCESS_CONTAIN = (win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE
                    | win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE)
_JOB_FLAGS = win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)
_TERMINATE_SECONDS = 5.0
#: A pass adopts every descendant whose parent was adopted in an earlier
#: pass; a chain deeper than this many generations is left uncovered.
_ADOPTION_PASSES = 16

# pywin32 312 has neither QueryFullProcessImageNameW nor the Toolhelp32
# snapshot calls (checked in the 312 wheel), so these few come from kernel32.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_query_image = _kernel32.QueryFullProcessImageNameW
_query_image.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_query_image.restype = wintypes.BOOL
_snapshot = _kernel32.CreateToolhelp32Snapshot
_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_snapshot.restype = wintypes.HANDLE
_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE = wintypes.HANDLE(-1).value


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
    created = win32process.GetProcessTimes(process)["CreationTime"]
    return 0


def _identity_of(process) -> ProcessIdentity:
    return ProcessIdentity(image=_image_of(process), created=_created_of(process))


def process_identity(pid: int) -> ProcessIdentity | None:
    try:
        process = _open_process(pid, _PROCESS_QUERY)
    except pywintypes.error as exc:
        if exc.winerror == -1:
            return None
        raise
    if process is None:
        return None
    with _Handles() as handles:
        handles.callback(win32api.CloseHandle, process)
        return _identity_of(process)


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
    """(pid, parent pid) for every process, from one Toolhelp32 snapshot."""
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
    finally:
        _close_handle(snapshot)
    return pairs


def _adopt_descendants(job, root_pid, root_created, held):
    """Assign to *job* the descendants of *root_pid* that were spawned before
    it was assigned (they did not inherit the job). Each adopted process's
    open handle is appended to *held*. Returns the adopted PIDs,
    the ``(pid, winerror)`` pairs that could not be adopted (pid 0: the process
    snapshot itself failed), and whether the sweep finished.

    A process counts as a descendant only if its recorded parent is in the
    job's tree AND it was created no earlier than that parent: a process whose
    parent PID was reused by our child is older than our child, and is left
    alone. Nothing here raises: the child is already in the job, and a failed
    sweep must not cost it its life, so failures are reported instead."""
    tree = {root_pid: root_created}
    adopted: list[int] = []
    uncovered: list[tuple[int, int]] = []
    judged = {root_pid}
    for _ in range(_ADOPTION_PASSES):
        grew = False
        try:
            parents = _process_parents()
        except OSError as exc:
            uncovered.append((0, exc.winerror or 0))
            return adopted, uncovered, False
        for pid, parent in parents:
            if parent not in tree or pid in judged:
                continue
            judged.add(pid)
            try:
                process = _open_process(pid, _PROCESS_CONTAIN)
                if process is None:  # already gone
                    continue
                with _Handles() as handles:
                    handles.callback(win32api.CloseHandle, process)
                    created = _created_of(process)
                    if created < tree[parent]:
                        continue  # its parent PID was reused: not ours
                    tree[pid] = created
                    grew = True
                    if not win32job.IsProcessInJob(process, job):
                        win32job.AssignProcessToJobObject(job, process)
                        adopted.append(pid)
                        handles.pop_all()
                        held.append(process)
            except pywintypes.error as exc:
                uncovered.append((pid, exc.winerror))
        if not grew:
            return adopted, uncovered, True
    return adopted, uncovered, False


class ContainedChild:
    """A kill-on-close job holding a child and its adopted descendants.

    Keep this object for as long as the child should live: when it is
    released (garbage-collected, or this process dies), Windows closes the
    job and kills everything in it. The open process handle pins the PID, so
    it cannot be reused while this object holds it."""

    def __init__(self, pid, identity, job, processes, adopted, uncovered, complete):
        self.pid = pid
        self.identity = identity
        self.adopted = tuple(adopted)
        self.uncovered = tuple(uncovered)
        #: False when the adoption sweep stopped at its generation bound.
        self.complete = complete
        self._job = job
        #: The child's handle first, then each adopted descendant's.
        self._processes = processes

    @property
    def released(self) -> bool:
        return self._job is None


@_os_errors()
def contain_child(pid: int, *, expect: ProcessIdentity | None = None) -> ContainedChild | None:
    process = _open_process(pid, _PROCESS_CONTAIN)
    if process is None:
        return None
    with _Handles() as handles:
        handles.callback(win32api.CloseHandle, process)
        identity = _identity_of(process)
        if expect is not None and identity != expect:
            return None
        # Closed with the stack unless handed to the ContainedChild below; it
        # is still empty if assignment fails, so closing it kills nothing.
        job = _new_job()
        handles.callback(win32api.CloseHandle, job)
        win32job.AssignProcessToJobObject(job, process)
        held = [process]
        adopted, uncovered, complete = _adopt_descendants(job, pid, identity.created, held)
        handles.pop_all()
    return ContainedChild(pid, identity, job, held, adopted, uncovered, complete)


def _active_processes(job) -> int:
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)
    return info["ActiveProcesses"]


@_os_errors()
def terminate_contained(handle: ContainedChild, *, timeout: float = _TERMINATE_SECONDS) -> None:
    job, processes = handle._job, handle._processes
    if job is None:
        return
    handle._job, handle._processes = None, []
    with _Handles() as handles:
        for process in processes:
            handles.callback(win32api.CloseHandle, process)
        handles.callback(win32api.CloseHandle, job)
        win32job.TerminateJobObject(job, 1)
        deadline = time.monotonic() + timeout
        # The job's count can reach zero a moment before a process object is
        # signalled; wait for both, on handles, never on a PID.
        for process in processes:
            if not _wait_until(process, deadline):
                break
        while _active_processes(job):
            if time.monotonic() >= deadline:
                break
                raise TimeoutError(f"contained job for PID {handle.pid} still has processes after {timeout} s")
            time.sleep(.01)
        if not all(_wait_until(process, time.monotonic()) for process in processes):
            raise TimeoutError(f"contained job for PID {handle.pid} still has processes after {timeout} s")


_self_job: list[Any] = []
_self_lock = threading.Lock()


@_os_errors()
def contain_self() -> bool:
    with _self_lock:
        if _self_job:
            return True
        job = _new_job()
        try:
            win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
        except BaseException as failure:
            with _cleanup_after(failure):
                win32api.CloseHandle(job)
            raise
        # Never closed: the kernel closes it when this process ends, and the
        # job then kills every descendant that did not break away.
        _self_job.append(job)
        return True
