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

from .procs import BoundedTimeout, OutputLimitExceeded

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
        raise OSError(0, exc.strerror, getattr(exc, "filename", None) or filename, code) from exc


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


def _launch(handles, argv, cwd, env, input_data, inherit):
    program = os.path.join(cwd, argv[0]) if cwd and os.path.dirname(argv[0]) else argv[0]
    executable = shutil.which(program, path=os.pathsep.join(os.get_exec_path(env)))
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
        try:
            if thread is not None:
                win32api.CloseHandle(thread)
        finally:
            if process is not None:
                win32api.CloseHandle(process)

    # Install the cleanup before CreateProcess can return a suspended child.
    handles.callback(close_process_handles)
    pipe_owners = [handles.enter_context(ExitStack()) for _ in range(3)]
    stdin_writer = None
    with _launch_lock, ExitStack() as children:
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
                win32process.TerminateProcess(process, 1)
                _reap_after_failed_launch(process, failure)
            raise
        try:
            win32process.ResumeThread(thread)
        except BaseException as failure:
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
                try:
                    if not _cancel_io(int(handle)):
                        code = ctypes.get_last_error()
                        if code != winerror.ERROR_NOT_FOUND:
                            raise ctypes.WinError(code)
                finally:
                    win32api.CloseHandle(handle)
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

    with ExitStack() as handles:
        job, process, stdout, stderr, writer, owners = _launch(handles, argv, cwd, env, data, inherit)
        deadline = time.monotonic() + timeout
        tasks: list[tuple[str, Callable, tuple]] = [
            ("stdout", read, (stdout, buffers[0])), ("stderr", read, (stderr, buffers[1])),
        ]
        if writer is not None:
            tasks.append(("stdin", write, (writer,)))
        exited = False
        try:
            for owner, (name, fn, args) in zip(owners, tasks):
                thread = threading.Thread(target=worker, args=(owner, fn, args),
                                          name=f"bounded-{name}", daemon=True)
                threads.append(thread)
                thread.start()
            with changed:
                completed = changed.wait_for(lambda: bool(failures) or finished == len(tasks),
                                             max(0, deadline - time.monotonic()))
                io_ok = completed and not failures
            exited = io_ok and _wait_until(process, deadline)
        finally:
            cleanup = time.monotonic() + _CLEANUP_SECONDS
            try:
                if not exited:
                    win32job.TerminateJobObject(job, 1)
                reaped = exited or _wait_until(process, cleanup)
            finally:
                # Keep a native terminate/wait error if cancellation was also
                # necessary. The caller needs its Win32 code to choose a fallback.
                joined = _join_pipes(threads, active, changed, stopping, cleanup)

        if failures:
            raise failures[0]
        if not reaped:
            raise RuntimeError("terminated Windows child did not exit")
        if not joined:
            raise RuntimeError("Windows pipe worker exceeded its cleanup deadline")
        if not exited:
            if inherit:
                raise subprocess.TimeoutExpired(argv, timeout, buffers[0].getvalue() or None,
                                                 buffers[1].getvalue() or None)
            raise BoundedTimeout(argv, timeout) from None
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
    try:
        return win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_TIMEOUT
    finally:
        win32api.CloseHandle(handle)
