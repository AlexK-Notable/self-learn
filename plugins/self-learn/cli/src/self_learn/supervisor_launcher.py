"""``self-learn-supervise``: keeps one command running on Windows, as
systemd keeps the host unit running on Linux.

Task Scheduler starts this launcher at logon (``primitives.supervisor``
registers it). The launcher starts the command inside a kill-on-close job,
waits, and then:

- exit 0, or a stop request (``supervisor.stop`` signals the launcher's
  event): no relaunch; the launcher exits 0;
- ``supervisor.RESTART_REQUESTED_EXIT``: relaunch at once (``serve``'s
  replacement for the Linux re-exec);
- any other exit: relaunch after ``RESTART_DELAY_SECS`` and give up after
  ``START_LIMIT_BURST`` failures within ``START_LIMIT_INTERVAL_SECS``, the
  Linux unit's ``RestartSec`` and start limit; it then exits
  ``LAUNCHER_GAVE_UP_EXIT``, which Task Scheduler records as the task's last
  result.

One launcher per name: a second exits ``LAUNCHER_ALREADY_RUNNING_EXIT``
without starting anything. The launcher writes no console output (it is a
windowless program); it logs to ``<state dir>/<name>.log``, where the
command's own output also goes.

    self-learn-supervise --name NAME --state-dir DIR [--home HOME] -- COMMAND...
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .primitives import fsops, supervisor

#: A log larger than this at launcher start is moved to ``<name>.log.1``.
LOG_ROTATE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Policy:
    restart_delay: float = supervisor.RESTART_DELAY_SECS
    burst: int = supervisor.START_LIMIT_BURST
    window: float = supervisor.START_LIMIT_INTERVAL_SECS


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
    requested meanwhile. Restart requests are not failures, but more than
    ``burst`` of them within ``window`` count as one, so a command that
    always asks to restart cannot spin."""
    failures: deque[float] = deque()
    restarts: deque[float] = deque()
    while True:
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
        if code == 0:
            log("the command exited 0; not relaunching")
            return 0
        now = clock()
        if code == supervisor.RESTART_REQUESTED_EXIT:
            _prune(restarts, now - policy.window)
            if len(restarts) < 0:
                restarts.append(now)
                log("the command asked to be restarted; relaunching now")
                continue
            log(f"more than {policy.burst} restart requests in {policy.window:g} s; counting a failure")
        _prune(failures, now - policy.window)
        failures.append(now)
        if len(failures) >= policy.burst:
            log(f"the command failed {len(failures)} times in {policy.window:g} s (last exit {code}); "
                "giving up")
            return supervisor.LAUNCHER_GAVE_UP_EXIT
        log(f"the command exited {code}; relaunching in {policy.restart_delay:g} s")
        if pause(policy.restart_delay):
            log("stop requested; not relaunching")
            return 0


class _Log:
    def __init__(self, path: Path) -> None:
        self.path = path

    def rotate(self) -> None:
        try:
            if self.path.stat().st_size > LOG_ROTATE_BYTES:
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        except FileNotFoundError:
            pass

    def __call__(self, message: str) -> None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        try:
            with fsops.open_for_mode(self.path, "a") as fh:
                fh.write(f"{stamp} self-learn-supervise[{os.getpid()}]: {message}\n")
        except OSError:
            pass  # A log that cannot be written must not stop the host.


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="self-learn-supervise", add_help=False)
    parser.add_argument("--name", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--restart-delay", type=float, default=supervisor.RESTART_DELAY_SECS)
    parser.add_argument("--burst", type=int, default=supervisor.START_LIMIT_BURST)
    parser.add_argument("--window", type=float, default=supervisor.START_LIMIT_INTERVAL_SECS)
    parser.add_argument("--stop-grace", type=float, default=supervisor.STOP_GRACE_SECS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    if os.name != "nt":
        if sys.stderr is not None:
            print("self-learn-supervise runs on Windows; on Linux systemd keeps the host running",
                  file=sys.stderr)
        return supervisor.LAUNCHER_USAGE_EXIT
    try:
        args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return supervisor.LAUNCHER_USAGE_EXIT
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.burst < 1:
        return supervisor.LAUNCHER_USAGE_EXIT
    from .primitives import _supervisor_tasks, locks

    try:
        name = _supervisor_tasks.check_name(args.name)
    except ValueError:
        return supervisor.LAUNCHER_USAGE_EXIT
    args.state_dir.mkdir(parents=True, exist_ok=True)
    log = _Log(args.state_dir / f"{name}.log")
    lock_path = args.state_dir / f"{name}.lock"
    with locks.open_lock(lock_path, purpose="private") as holder:
        try:
            lease = locks.acquire(holder.fileno(), path=lock_path, wait=0)
        except BlockingIOError:
            log("another launcher of this name is running; exiting")
            return supervisor.LAUNCHER_ALREADY_RUNNING_EXIT
        with lease:
            log.rotate()
            return _run(args, name, command, log, _supervisor_tasks)


def _run(args: argparse.Namespace, name: str, command: list[str], log: _Log, tasks) -> int:
    try:
        runtime = tasks.LauncherRuntime(name, grace=args.stop_grace)
    except OSError as exc:
        log(f"could not create the stop event: {exc}")
        return supervisor.LAUNCHER_GAVE_UP_EXIT
    extra = {} if args.home is None else {"SELF_LEARN_HOME": str(args.home)}
    env = runtime.child_environment(os.environ, extra)
    log(f"supervising {command!r}")
    try:
        return supervise(
            lambda: runtime.launch(command, env=env, output=log.path),
            Policy(args.restart_delay, args.burst, args.window),
            pause=runtime.pause, log=log,
        )
    except BaseException:
        log("launcher failed:\n" + traceback.format_exc())
        return supervisor.LAUNCHER_GAVE_UP_EXIT
    finally:
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
