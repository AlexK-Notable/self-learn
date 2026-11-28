"""Platform interface for the service manager that keeps the background
host running: the systemd user manager on Linux, Task Scheduler plus a
small self-learn launcher (``self-learn-supervise``) on Windows.

Operations: :func:`register`, :func:`unregister`, :func:`start`,
:func:`stop`, :func:`restart`, :func:`status` (one of ``running``,
``stopped``, ``failed``, ``missing``) and :func:`last_result`.

On Linux every ``systemctl --user`` argument list here is a copy of a call
that already existed in ``attention.py`` and ``attention_answers.py``
(``_supervisor_systemd`` quotes each original beside its copy). On Windows
Task Scheduler only starts the launcher at logon: measured on GitHub's
Windows runner (``w3-taskspike-findings.md`` section 4), Task Scheduler
never relaunches a task whose process exits nonzero, so the launcher does
the relaunching, inside a kill-on-close job so that ending the task also
ends the host and everything it started.

Importing this module loads no backend; the first operation selects one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from . import names

State = Literal["running", "stopped", "failed", "missing"]

#: ``serve`` exits with this code to ask the launcher for an immediate
#: relaunch (the Windows replacement for the Linux re-exec, which keeps
#: the PID; parity plan section 1.7). 75 is ``EX_TEMPFAIL``.
RESTART_REQUESTED_EXIT = 75
#: The launcher's own exit codes. Task Scheduler records them as the
#: task's last result, which :func:`status` reads back.
LAUNCHER_USAGE_EXIT = 64
LAUNCHER_GAVE_UP_EXIT = 70
LAUNCHER_ALREADY_RUNNING_EXIT = 73

#: The Linux host unit's restart policy (``systemd/self-learn-host.service``:
#: ``RestartSec=5``, ``StartLimitBurst=5``, ``StartLimitIntervalSec=300``);
#: ``tests/test_platform_supervisor.py`` reads the unit file and fails if
#: these drift from it.
RESTART_DELAY_SECS = 5.0
START_LIMIT_BURST = 5
START_LIMIT_INTERVAL_SECS = 300.0
#: How long the launcher lets the host finish after a stop request before
#: it ends the host's job.
STOP_GRACE_SECS = 5.0

#: The environment variable carrying the name of the launcher's stop event
#: to the host, so a later ``serve`` can wait on the same request.
STOP_EVENT_ENV = "SELF_LEARN_SUPERVISOR_STOP_EVENT"

DEFAULT_TIMEOUT_SECS = 10.0
#: How long :func:`stop` waits for the launcher to finish on its own before
#: it ends the task.
STOP_WAIT_SECS = STOP_GRACE_SECS + 10.0


class SupervisorError(RuntimeError):
    """An operation did not complete. ``verb`` names the operation as the
    service manager knows it (``is-active``, ``restart``, ``/Run``),
    ``name`` the unit or task, ``detail`` what the manager said (at most
    400 characters), ``returncode`` its exit status when it ran."""

    def __init__(self, message: str, *, verb: str, name: str, detail: str = "",
                 returncode: int | None = None) -> None:
        super().__init__(message)
        self.verb = verb
        self.name = name
        self.detail = detail
        self.returncode = returncode


class SupervisorUnavailable(SupervisorError):
    """The service manager could not be asked: its program is missing,
    could not be started, or did not answer in time."""


class SupervisorRefused(SupervisorError):
    """The service manager answered and refused (a nonzero exit, or a task
    that does not exist)."""


@dataclass(frozen=True)
class ServiceStatus:
    """``state`` is the portable answer. ``raw`` is the manager's own word
    (systemd: what ``is-active`` printed; Windows: the task state, such as
    ``Running`` or ``Ready``; ``missing`` when there is no such task), so a
    caller that relied on one exact word keeps relying on it.
    ``last_result`` is the last exit status the manager recorded, ``None``
    when it has none."""

    state: State
    raw: str
    last_result: int | None


def _backend():
    if os.name == "nt":
        from . import _supervisor_tasks

        return _supervisor_tasks
    from . import _supervisor_systemd

    return _supervisor_systemd


def host_name() -> str:
    """The background host's unit or task name on this platform."""
    return _backend().HOST_NAME


def state_dir(home: Path | str | None = None) -> Path:
    """Where the launcher keeps its log and its single-instance lock:
    ``supervisor/`` in the ledger's cache folder (``names.home_cache``)."""
    return names.home_cache(home) / "supervisor"


def register(name: str, command: Sequence[str], *, description: str,
             home: Path | str | None = None, timeout: float = DEFAULT_TIMEOUT_SECS) -> None:
    """Make *name* start at logon. Windows: a per-user Task Scheduler task
    whose action is the launcher running *command* (``command[0]`` must be
    an absolute path) with the ledger at *home* (default: the resolved
    ledger home). Linux: ``systemctl --user enable`` of the unit
    ``install.sh`` linked; the unit file, not *command*, says what runs."""
    _backend().register(name, list(command), description=description,
                        home=names.ledger_home() if home is None else Path(home), timeout=timeout)


def unregister(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> None:
    """Stop *name* if it runs and remove its registration. Windows: a task
    that does not exist is already unregistered."""
    _backend().unregister(name, timeout=timeout)


def start(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> None:
    """Start *name* now. Starting a running service changes nothing."""
    _backend().start(name, timeout=timeout)


def stop(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> None:
    """Stop *name*. Windows: asks the launcher first (it lets the host
    finish for :data:`STOP_GRACE_SECS`, then ends it, and exits 0); ends
    the task if the launcher has not finished within :data:`STOP_WAIT_SECS`."""
    _backend().stop(name, timeout=timeout)


def restart(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> None:
    """Start *name* again, also after its manager gave up on it. Linux:
    ``reset-failed`` then ``restart``, the inbox's fix. Windows: stop, then
    start."""
    _backend().restart(name, timeout=timeout)


def status(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> ServiceStatus:
    return _backend().status(name, timeout=timeout)


def last_result(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> int | None:
    return _backend().last_result(name, timeout=timeout)
