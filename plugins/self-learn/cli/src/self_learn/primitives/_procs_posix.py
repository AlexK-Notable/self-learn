"""POSIX child-process execution and PID probing."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from typing import Mapping, Sequence

from .procs import BoundedTimeout, OutputLimitExceeded


def _limited_output(proc, argv, timeout: float, limit: int) -> tuple[bytes, bytes]:
    """Drain both pipes without letting a fast producer outrun the byte cap."""
    deadline = time.monotonic() + timeout
    buffers = [bytearray(), bytearray()]
    size = 0
    with selectors.DefaultSelector() as selector:
        for index, stream in enumerate((proc.stdout, proc.stderr)):
            selector.register(stream, selectors.EVENT_READ, index)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fd, min(65536, limit - size + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                size += len(chunk)
                if size > limit:
                    raise OutputLimitExceeded(f"child output exceeded {limit} bytes")
                buffers[key.data].extend(chunk)
    proc.wait(timeout=max(0, deadline - time.monotonic()))
    proc.stdout.close()
    proc.stderr.close()
    return bytes(buffers[0]), bytes(buffers[1])


def run_bounded(
    argv: Sequence[str],
    *,
    timeout: float,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    input: str | bytes | None = None,
    check: bool = False,
    binary: bool = False,
    max_output_bytes: int | None = None,
) -> subprocess.CompletedProcess:
    if binary and isinstance(input, str):
        raise ValueError("run_bounded: binary=True requires input to be bytes or None, not str")
    if max_output_bytes is not None and (
        max_output_bytes <= 0 or not binary or input is not None
    ):
        raise ValueError("run_bounded: output limit requires a positive budget, binary=True and no input")
    argv = list(argv)
    text_mode = not binary and not isinstance(input, (bytes, bytearray))
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text_mode,
        start_new_session=True,
    )
    try:
        if max_output_bytes is None:
            stdout, stderr = proc.communicate(input=input, timeout=timeout)
        else:
            stdout, stderr = _limited_output(proc, argv, timeout, max_output_bytes)
    except (subprocess.TimeoutExpired, OutputLimitExceeded) as exc:
        # start_new_session makes pid the group id. The leader may have
        # already exited while a descendant still owns a pipe: getpgid(pid)
        # would lose that group precisely when we still need to kill it.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            # the group kill above should make this unreachable in
            # practice; a last-resort direct kill + one more bounded
            # drain rather than a bare (unbounded) communicate().
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if isinstance(exc, subprocess.TimeoutExpired):
            raise BoundedTimeout(argv, timeout) from None
        raise

    result = subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, argv, output=stdout, stderr=stderr
        )
    return result


def run_command(argv: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True
