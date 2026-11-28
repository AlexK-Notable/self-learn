"""Windows synchronous children. Each launch owns one kill-on-close job."""

from __future__ import annotations

from collections.abc import Callable
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from typing import Any, Mapping, Sequence, cast
from uuid import uuid4

from .procs import BoundedTimeout, OutputLimitExceeded

if sys.platform == "win32":
    import _winapi
    import msvcrt
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


def _wait_until(process, deadline):
    millis = math.ceil(max(0, deadline - time.monotonic()) * 1000)
    return win32event.WaitForSingleObject(process, millis) == win32event.WAIT_OBJECT_0


def _reap(process):
    if not _wait_until(process, time.monotonic() + _CLEANUP_SECONDS):
        raise RuntimeError("terminated Windows child did not exit")


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
    if source is None or source == -1:
        devnull = children.enter_context(open(os.devnull, "rb"))
        source = msvcrt.get_osfhandle(devnull.fileno())
    current = win32api.GetCurrentProcess()
    handle = win32api.DuplicateHandle(current, source, current, 0, True, win32con.DUPLICATE_SAME_ACCESS)
    children.callback(win32api.CloseHandle, handle)
    return handle


def _launch(handles, argv, cwd, env, input_data, inherit):
    program = os.path.join(cwd, argv[0]) if cwd and os.path.dirname(argv[0]) else argv[0]
    executable = shutil.which(program, path=os.pathsep.join(os.get_exec_path(env)))
    if executable is None:
        raise FileNotFoundError(argv[0])
    # CreateProcess can hand batch files to cmd.exe even with shell=False.
    if executable.lower().endswith((".bat", ".cmd")):
        raise ValueError("a native executable is required")

    # pywin32 312 requires a string name and returns a PyHANDLE.
    job = cast(Any, win32job.CreateJobObject(None, uuid4().hex))
    handles.callback(win32api.CloseHandle, job)
    info_class = win32job.JobObjectExtendedLimitInformation
    info = win32job.QueryInformationJobObject(job, info_class)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, info_class, info)

    stdin_handles = handles.enter_context(ExitStack())
    stdin_writer = None
    with _launch_lock, ExitStack() as children:
        startup = win32process.STARTUPINFO()
        startup.dwFlags = win32process.STARTF_USESTDHANDLES
        startup.hStdOutput, stdout = _pipe(handles, children)
        startup.hStdError, stderr = _pipe(handles, children)
        if input_data is None:
            startup.hStdInput = _stdin(children, inherit)
        else:
            startup.hStdInput, stdin_writer = _pipe(stdin_handles, children, child_reads=True)
        process, thread, _, _ = win32process.CreateProcess(
            executable, subprocess.list2cmdline(argv), None, None, True,
            win32process.CREATE_SUSPENDED | win32process.CREATE_UNICODE_ENVIRONMENT,
            env, cwd, startup,
        )
        handles.callback(win32api.CloseHandle, process)
        handles.callback(win32api.CloseHandle, thread)
        try:
            win32job.AssignProcessToJobObject(job, process)
        except BaseException:
            win32process.TerminateProcess(process, 1)
            _reap(process)
            raise
        try:
            win32process.ResumeThread(thread)
        except BaseException:
            win32job.TerminateJobObject(job, 1)
            _reap(process)
            raise
    return job, process, stdout, stderr, stdin_writer, stdin_handles


def _capture(argv, timeout, cwd, env, data, inherit, limit):
    buffers = [bytearray(), bytearray()]
    changed = threading.Condition()
    failures: list[BaseException] = []
    threads: list[threading.Thread] = []
    finished = 0
    total = 0

    def read(handle, buffer):
        nonlocal total
        while True:
            with changed:
                if failures:
                    return
                # The other reader can hold one older request. Leave one byte
                # for this reader's N+1 probe: at most limit + _CHUNK in flight
                # and retained together, even when both pipes complete at once.
                size = _CHUNK if limit is None else min(_CHUNK - 1, limit - total + 1)
            # A synchronous anonymous-pipe read returns available bytes immediately.
            _, chunk = win32file.ReadFile(handle, size)
            if not chunk:
                return
            with changed:
                if failures:
                    return
                if limit is not None:
                    if total + len(chunk) > limit:
                        failures.append(OutputLimitExceeded(f"child output exceeded {limit} bytes"))
                        changed.notify()
                        return
                    total += len(chunk)
                buffer.extend(chunk)
                del chunk

    def write(handle, owners):
        try:
            for pos in range(0, len(data), _CHUNK):
                win32file.WriteFile(handle, data[pos:pos + _CHUNK])
        finally:
            owners.close()  # Deliver EOF even when the child waits for it before writing.

    def worker(fn, args):
        nonlocal finished
        try:
            fn(*args)
        except BaseException as exc:
            if not (isinstance(exc, pywintypes.error) and
                    exc.winerror in (winerror.ERROR_BROKEN_PIPE, winerror.ERROR_NO_DATA)):
                with changed:
                    failures.append(exc)
        finally:
            with changed:
                finished += 1
                changed.notify()

    with ExitStack() as handles:
        job, process, stdout, stderr, writer, owners = _launch(handles, argv, cwd, env, data, inherit)
        deadline = time.monotonic() + timeout
        tasks: list[tuple[str, Callable, tuple]] = [
            ("stdout", read, (stdout, buffers[0])), ("stderr", read, (stderr, buffers[1])),
        ]
        if writer is not None:
            tasks.append(("stdin", write, (writer, owners)))
        expired = False
        try:
            for name, fn, args in tasks:
                thread = threading.Thread(target=worker, args=(fn, args), name=f"bounded-{name}")
                thread.start()
                threads.append(thread)
            with changed:
                completed = changed.wait_for(lambda: failures or finished == len(tasks),
                                             max(0, deadline - time.monotonic()))
                if failures:
                    raise failures[0]
            if not completed or not _wait_until(process, deadline):
                expired = True
                raise subprocess.TimeoutExpired(argv, timeout)
        except BaseException:
            win32job.TerminateJobObject(job, 1)
            _reap(process)
            if not expired:
                raise
        finally:
            cleanup = time.monotonic() + _CLEANUP_SECONDS
            for thread in threads:
                thread.join(max(0, cleanup - time.monotonic()))
                if thread.is_alive():
                    raise RuntimeError(f"Windows pipe thread did not exit: {thread.name}")

        if expired:
            if inherit:
                raise subprocess.TimeoutExpired(argv, timeout, bytes(buffers[0]) or None,
                                                 bytes(buffers[1]) or None)
            raise BoundedTimeout(argv, timeout) from None
        return win32process.GetExitCodeProcess(process), bytes(buffers[0]), bytes(buffers[1])


def _text(data: bytes, errors: str) -> str:
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
    code, out, err = _capture(argv, timeout, cwd, dict(env) if env is not None else None,
                              data, False, max_output_bytes)
    if not binary and not isinstance(input, (bytes, bytearray)):
        out, err = _text(out, "strict"), _text(err, "strict")
    result = subprocess.CompletedProcess(argv, code, out, err)
    if check:
        result.check_returncode()
    return result


def run_command(argv: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    code, out, err = _capture(argv, timeout, None, None, None, True, None)
    return subprocess.CompletedProcess(argv, code, _text(out, "replace"), _text(err, "replace"))


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
