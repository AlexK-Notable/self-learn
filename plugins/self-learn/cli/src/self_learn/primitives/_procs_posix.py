"""POSIX child-process execution and PID probing."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .procs import BoundedTimeout, OutputLimitExceeded, ProcessIdentity


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


# S-174: the calls below are copies of what sdksession/children.py
# and sdksession/teardown.py do today, so a later lane can switch to them with
# no behaviour change. Each original statement is quoted beside its copy.


def process_identity(pid: int) -> ProcessIdentity | None:
    try:
        # children.py _sweep_one: `raw = Path(f"/proc/{pid}/cmdline").read_bytes()`
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    # children.py _sweep_one: `except OSError:`
    except OSError:
        return None
    # children.py _sweep_one: `first = raw.split(b"\x00")[0].decode("utf-8", "replace")`
    first = raw.split(b"\x00")[0].decode("utf-8", "replace")
    return ProcessIdentity(image=first, created=None, cmdline=raw)


@dataclass(frozen=True)
class ContainedChild:
    """The POSIX handle: the PID, from which the kill reads the process
    group with ``os.getpgid`` at kill time, as ``teardown.kill_child`` does."""

    pid: int


def _refused(pid) -> bool:
    """PIDs the copied kill body must never receive: zero and negative numbers
    address process groups (0 is our own; -1 is every process we may signal),
    and our own PID or our group leader's would kill this process or the
    leader of its group. ``teardown.kill_child`` never sees them today (the
    SDK supplies a positive child PID or ``None``)."""
    return not isinstance(pid, int) or pid <= 0 or pid == os.getpid() or pid == os.getpgrp()


def contain_child(pid: int, *, expect: ProcessIdentity | None = None) -> ContainedChild | None:
    if _refused(pid):
        return None
    if expect is not None and process_identity(pid) != expect:
        return None
    return ContainedChild(pid)


def terminate_contained(handle: ContainedChild | None) -> None:
    if handle is None or _refused(handle.pid):
        return
    pid = handle.pid
    # Copied from teardown.kill_child, statement for statement:
    #     try:
    #         if os.getpgid(pid) != os.getpgid(0):
    #             os.killpg(pid, signal.SIGKILL)
    #         else:
    #             os.kill(pid, signal.SIGKILL)
    #     except (ProcessLookupError, PermissionError):
    #         pass
    try:
        if os.getpgid(pid) != os.getpgid(0):
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def contain_self() -> bool:
    """POSIX does nothing here: process groups already carry descendants."""
    return False


def identity_predates_boot(identity: ProcessIdentity) -> bool:
    """POSIX identities carry no creation time, so there is nothing to compare;
    the orphan sweep's own checks (sidecar time, cmdline) stay in force."""
    return False


# S-NEXT-w7-procs: detached background runs and the web UI's owned asyncio
# children. Each body is a copy of the call it replaces; the original
# statements are quoted beside it, so a later lane can switch the callers with
# no change in behaviour.

from ._detached import DetachedChild  # noqa: E402


def spawn_detached(argv, *, cwd=None, env=None, log_path=None) -> DetachedChild:
    if log_path is not None:
        # worker._spawn_window (miner._spawn_run is the same call with its own
        # argv and log):
        #     with open(log_path, "a", encoding="utf-8") as out:
        #         proc = subprocess.Popen(
        #             [sys.executable, "-m", "self_learn.cli", "worker", "run", "--coalesce"],
        #             cwd=str(home),
        #             stdout=out,
        #             stderr=subprocess.STDOUT,
        #             start_new_session=True,
        #             env=env,
        #         )
        #     return proc.pid
        with open(log_path, "a", encoding="utf-8") as out:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
        return DetachedChild(proc.pid)
    # overseer.notify.send (no cwd= and no env=, which leaves both at
    # Popen's own default of None, as passing None here does):
    #     subprocess.Popen(
    #         [helper, "--line", line, "--page", POPUP_PAGE],
    #         stdin=subprocess.DEVNULL,
    #         stdout=subprocess.DEVNULL,
    #         stderr=subprocess.DEVNULL,
    #         start_new_session=True,
    #     )
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return DetachedChild(proc.pid)


def breakaway_allowed() -> bool | None:
    """POSIX has no jobs to break away from."""
    return None


async def async_owned_child(*argv, env=None, stdin=None, stdout=None, stderr=None):
    import asyncio

    # ui/runner.py RealRunner._spawn (no stdin=, so create_subprocess_exec's
    # default None):
    #     proc = await create_subprocess_exec(
    #         *cmd,
    #         env=full_env,
    #         stdout=asyncio_subprocess.PIPE,
    #         stderr=asyncio_subprocess.PIPE,
    #         start_new_session=True,
    #     )
    # ui/ask_runner.py RealAskRunner.start (start_summary and check_login pass
    # stdin=asyncio_subprocess.DEVNULL):
    #     proc = await asyncio.create_subprocess_exec(
    #         *self._argv_prefix, "ask", item_id, "--message-file", "-", "--stream",
    #         env=self._full_env(), stdin=asyncio_subprocess.PIPE,
    #         stdout=asyncio_subprocess.PIPE, stderr=asyncio_subprocess.PIPE,
    #         start_new_session=True,
    #     )
    return await asyncio.create_subprocess_exec(
        *argv, env=env, stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True,
    )


def stop_owned(proc, *, hard: bool, soft_request=None) -> bool:
    sig = signal.SIGKILL if hard else signal.SIGTERM
    # ui/runner.py _signal_group(proc, sig) (ask_runner's _signal_group(pid,
    # sig) is the same calls with proc.pid; killpg receives the same number,
    # since pgid == pid in that branch):
    #     try:
    #         pgid = os.getpgid(proc.pid)
    #         if pgid == proc.pid:
    #             os.killpg(pgid, sig)
    #         else:
    #             os.kill(proc.pid, sig)
    #     except ProcessLookupError:
    #         return False
    #     return True
    try:
        pgid = os.getpgid(proc.pid)
        if pgid == proc.pid:
            os.killpg(pgid, sig)
        else:
            os.kill(proc.pid, sig)
    except ProcessLookupError:
        return False
    return True


async def terminate_owned(proc, *, kill_grace: float, wait_after_lost_kill: bool = False,
                          soft_request=None) -> None:
    import asyncio

    # ui/runner.py _terminate_then_kill (wait_for is asyncio.wait_for):
    #     if proc.returncode is not None:
    #         return
    #     if not _signal_group(proc, signal.SIGTERM):
    #         return
    #     try:
    #         await wait_for(proc.wait(), timeout=kill_grace)
    #         return
    #     except TimeoutError:
    #         pass
    #     if not _signal_group(proc, signal.SIGKILL):
    #         return
    #     try:
    #         await wait_for(proc.wait(), timeout=kill_grace)
    #     except TimeoutError:
    #         pass
    # ui/ask_runner.py RealAskRunner._terminate is the same except that it
    # ignores the result of the SIGKILL and always waits again:
    #     _signal_group(proc.pid, signal.SIGKILL)
    #     try:
    #         await asyncio.wait_for(proc.wait(), timeout=self._kill_grace)
    #     except TimeoutError:
    #         pass
    if proc.returncode is not None:
        return
    if not stop_owned(proc, hard=False):
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=kill_grace)
        return
    except TimeoutError:
        pass
    if not stop_owned(proc, hard=True) and not wait_after_lost_kill:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=kill_grace)
    except TimeoutError:
        pass


def release_owned(proc) -> None:
    """POSIX holds nothing for an owned child: the process group is enough."""
