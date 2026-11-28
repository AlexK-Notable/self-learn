"""``self-learn-supervise``: keeps one command running on Windows, as
systemd keeps the host unit running on Linux.

Task Scheduler starts this launcher at logon (``primitives.supervisor``
registers it). The launcher first puts itself in a kill-on-close job
(``procs.contain_self``), so whatever kills it also ends the host. It
starts the command suspended, inside a further kill-on-close job that
allows explicit breakaway (detached work the host starts still escapes),
resumes it, waits, and then:

- exit 0 or 143 (the unit's ``SuccessExitStatus``), or a stop request
  (``supervisor.stop`` signals the launcher's event): no relaunch; the
  launcher exits 0;
- ``supervisor.RESTART_REQUESTED_EXIT``: relaunch at once (``serve``'s
  replacement for the Linux re-exec, which systemd does not count as a
  start); more than ``START_LIMIT_BURST`` of them within the interval are
  treated as failures;
- any other exit: wait ``RESTART_DELAY_SECS``, then start again unless
  ``START_LIMIT_BURST`` starts already happened within
  ``START_LIMIT_INTERVAL_SECS`` (systemd's rule: the first start counts,
  and the check is made at the start); it then exits
  ``LAUNCHER_GAVE_UP_EXIT``, which Task Scheduler records as the task's
  last result.

One launcher per name: a second exits ``LAUNCHER_ALREADY_RUNNING_EXIT``
without starting anything. The launcher writes no console output (it is a
windowless program). It logs, and copies the command's output (read from a
pipe by a thread, so the command never waits on the disk), to
``<state dir>/<name>.log``, moved to ``<name>.log.1`` whenever it would grow
past ``LOG_ROTATE_BYTES``.

    self-learn-supervise --name NAME --state-dir DIR [--home HOME] -- COMMAND...
"""

from __future__ import annotations

import argparse
import codecs
import math
import os
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from .primitives import fsops, procs, supervisor

#: The log is moved to ``<name>.log.1`` before it would pass this size.
LOG_ROTATE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Policy:
    restart_delay: float = supervisor.RESTART_DELAY_SECS
    burst: int = supervisor.START_LIMIT_BURST
    window: float = supervisor.START_LIMIT_INTERVAL_SECS

    def __post_init__(self) -> None:
        for label, value in (("restart delay", self.restart_delay), ("window", self.window)):
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"the {label} must be a positive number of seconds, not {value!r}")
        if self.burst < 1:
            raise ValueError(f"the start limit must be at least 1, not {self.burst!r}")


def _prune(times: deque[float], since: float) -> None:
    while times and times[0] <= since:
        times.popleft()


def supervise(launch: Callable[[], Callable[[], int | None]], policy: Policy, *,
              pause: Callable[[float], bool], log: Callable[[str], None],
              clock: Callable[[], float] = time.monotonic) -> int:
    """The relaunch loop, free of operating-system calls. *launch* starts
    the command and returns its waiter (exit code, or ``None`` after a stop
    request); it raises ``OSError`` when the command cannot start, which
    counts as a failure. *pause* sleeps and answers whether a stop was
    requested; ``pause(0)`` is asked before every start."""
    starts: deque[float] = deque()
    restarts: deque[float] = deque()
    immediate = False
    while True:
        if pause(0):
            log("stop requested; not starting the command")
            return 0
        now = clock()
        if not immediate:
            _prune(starts, now - policy.window)
            if len(starts) >= policy.burst:
                log(f"{len(starts)} starts within {policy.window:g} s; giving up")
                return supervisor.LAUNCHER_GAVE_UP_EXIT
            starts.append(now)
        try:
            wait = launch()
        except OSError as exc:
            log(f"could not start the command: {exc}")
            code: int | None = -1
        else:
            code = wait()
        if code is None:
            log("stop requested; not relaunching")
            return 0
        if code in supervisor.CLEAN_EXITS:
            log(f"the command exited {code}; not relaunching")
            return 0
        immediate = False
        if code == supervisor.RESTART_REQUESTED_EXIT:
            now = clock()
            _prune(restarts, now - policy.window)
            if len(restarts) < policy.burst:
                restarts.append(now)
                immediate = True
                log("the command asked to be restarted; relaunching now")
                continue
            log(f"more than {policy.burst} restart requests in {policy.window:g} s; counting a failure")
        log(f"the command exited {code}; relaunching in {policy.restart_delay:g} s")
        if pause(policy.restart_delay):
            log("stop requested; not relaunching")
            return 0


class _Log:
    """One writer for the launcher's lines and the command's output. Each
    write that would take the file past *cap* first moves it to ``.1``; a
    rotation that fails (the file is open elsewhere) is logged and retried
    after another *cap* bytes, and writing goes on."""

    def __init__(self, path: Path, cap: int = LOG_ROTATE_BYTES) -> None:
        self.path = path
        self._cap = cap
        self._lock = threading.Lock()
        self._stream: IO[Any] | None = None
        self._size = 0
        self._limit = cap

    def _open(self) -> IO[Any]:
        fh = fsops.open_for_mode(self.path, "a")
        try:
            self._size = self.path.stat().st_size
        except OSError:
            self._size = 0
        self._stream = fh
        return fh

    def _rotate(self) -> str | None:
        fh, self._stream = self._stream, None
        if fh is not None:
            fh.close()
        try:
            os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._limit = self._size + self._cap
            return f"could not rotate the log: {exc}"
        self._limit = self._cap
        return None

    def append(self, text: str) -> None:
        data = len(text.encode("utf-8"))
        with self._lock:
            try:
                fh = self._stream or self._open()
                note = None
                if self._size + data > self._limit:
                    note = self._rotate()
                    fh = self._open()
                if note:
                    fh.write(note + "\n")
                fh.write(text)
                fh.flush()
                self._size += 0
            except OSError:
                pass  # A log that cannot be written must not stop the host.

    def __call__(self, message: str) -> None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.append(f"{stamp} self-learn-supervise[{os.getpid()}]: {message}\n")

    def sink(self) -> Callable[[bytes], None]:
        """A writer for one command's output, decoding UTF-8 across chunks."""
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        return lambda data: self.append(decoder.decode(data))

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None


def _note_refused(state_dir: Path, name: str) -> None:
    """A second launcher writes one line of its own, never into the log the
    first one is writing."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        fsops.atomic_write(state_dir / f"{name}.refused",
                           f"{stamp} pid {os.getpid()}: another launcher of this name is running\n",
                           fsync=False)
    except OSError:
        pass


def _seconds(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"not a finite number: {text}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="self-learn-supervise", add_help=False)
    parser.add_argument("--name", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--restart-delay", type=_seconds, default=supervisor.RESTART_DELAY_SECS)
    parser.add_argument("--burst", type=int, default=supervisor.START_LIMIT_BURST)
    parser.add_argument("--window", type=_seconds, default=supervisor.START_LIMIT_INTERVAL_SECS)
    parser.add_argument("--stop-grace", type=_seconds, default=supervisor.STOP_GRACE_SECS)
    parser.add_argument("--log-bytes", type=int, default=LOG_ROTATE_BYTES)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def parse(argv: list[str]) -> tuple[argparse.Namespace, list[str], Policy] | None:
    """The arguments, the command and the policy; ``None`` when they are
    not usable (the launcher then exits ``LAUNCHER_USAGE_EXIT``)."""
    try:
        args = _parser().parse_args(argv)
        policy = Policy(args.restart_delay, args.burst, args.window)
    except (SystemExit, ValueError):
        return None
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if (not command or not (0 <= args.stop_grace <= supervisor.MAX_STOP_GRACE_SECS)
            or args.log_bytes < 4096):
        return None
    return args, command, policy


def main(argv: list[str] | None = None) -> int:
    if os.name != "nt":
        if sys.stderr is not None:
            print("self-learn-supervise runs on Windows; on Linux systemd keeps the host running",
                  file=sys.stderr)
        return supervisor.LAUNCHER_USAGE_EXIT
    parsed = parse(sys.argv[1:] if argv is None else argv)
    if parsed is None:
        return supervisor.LAUNCHER_USAGE_EXIT
    args, command, policy = parsed
    from .primitives import _supervisor_tasks, locks

    try:
        name = _supervisor_tasks.check_leaf(args.name)
    except ValueError:
        return supervisor.LAUNCHER_USAGE_EXIT
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = args.state_dir / f"{name}.lock"
    with locks.open_lock(lock_path, purpose="private") as holder:
        try:
            lease = locks.acquire(holder.fileno(), path=lock_path, wait=0)
        except BlockingIOError:
            _note_refused(args.state_dir, name)
            return supervisor.LAUNCHER_ALREADY_RUNNING_EXIT
        with lease:
            log = _Log(args.state_dir / f"{name}.log", args.log_bytes)
            try:
                # Before anything is started: whatever kills this process
                # now also ends every host it starts (their jobs nest here).
                try:
                    procs.contain_self()
                except OSError as exc:
                    log(f"could not put the launcher in its own job: {exc}")
                    return supervisor.LAUNCHER_GAVE_UP_EXIT
                return _run(args, name, command, policy, log, _supervisor_tasks)
            finally:
                log.close()


def _run(args: argparse.Namespace, name: str, command: list[str], policy: Policy, log: _Log,
         tasks) -> int:
    try:
        runtime = tasks.LauncherRuntime(name, grace=args.stop_grace)
    except OSError as exc:
        log(f"could not create the launcher's events: {exc}")
        return supervisor.LAUNCHER_GAVE_UP_EXIT
    extra = {} if args.home is None else {"SELF_LEARN_HOME": str(args.home)}
    env = runtime.child_environment(os.environ, extra)
    log(f"supervising {command!r}")
    try:
        return supervise(lambda: runtime.launch(command, env=env, sink=log.sink()), policy,
                         pause=runtime.pause, log=log)
    except BaseException:
        log("launcher failed:\n" + traceback.format_exc())
        return supervisor.LAUNCHER_GAVE_UP_EXIT
    finally:
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
