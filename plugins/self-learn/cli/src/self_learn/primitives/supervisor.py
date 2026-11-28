"""Platform interface for the service manager that keeps the background
host running: the systemd user manager on Linux, Task Scheduler plus a
small self-learn launcher (``self-learn-supervise``) on Windows.

Operations: :func:`register`, :func:`unregister`, :func:`start`,
:func:`stop`, :func:`restart`, :func:`status` (one of ``running``,
``stopped``, ``failed``, ``missing`` or ``unknown``) and
:func:`last_result`. Each operation has one deadline, its ``timeout``.

Linux makes only the ``systemctl --user`` calls the product already makes
(``_supervisor_systemd`` quotes each original beside its copy): ``is-active``,
``reset-failed`` then ``restart``, ``stop``, and the tray's ``start``.
Registration on Linux is ``install.sh`` linking the unit and the person
enabling it, so :func:`register` and :func:`unregister` raise
``NotImplementedError`` there, and :func:`status` cannot tell ``missing``
from ``stopped`` (``is-active`` says ``inactive`` for both).

On Windows Task Scheduler only starts the launcher at logon: measured on
GitHub's Windows runner (``w3-taskspike-findings.md`` section 4), Task
Scheduler never relaunches a task whose process exits nonzero, so the
launcher does the relaunching, with the host in a kill-on-close job so
that ending the task also ends the host.

Importing this module loads no backend; the first operation selects one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from . import names

State = Literal["running", "stopped", "failed", "missing", "unknown"]

#: ``serve`` exits with this code to ask the launcher for an immediate
#: relaunch (the Windows replacement for the Linux re-exec, which keeps
#: the PID; parity plan section 1.7). 75 is ``EX_TEMPFAIL``.
RESTART_REQUESTED_EXIT = 75
#: Exit statuses that end supervision cleanly: 0 and the unit's
#: ``SuccessExitStatus=143``.
CLEAN_EXITS = frozenset({0, 143})
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
#: The longest grace the launcher accepts (a finite Win32 wait).
MAX_STOP_GRACE_SECS = 3600.0

#: The environment variable carrying the name of the launcher's stop event
#: to the host, so a later ``serve`` can wait on the same request.
STOP_EVENT_ENV = "SELF_LEARN_SUPERVISOR_STOP_EVENT"

DEFAULT_TIMEOUT_SECS = 10.0
#: How long :func:`stop` waits for the launcher to finish on its own before
#: it ends the task.
STOP_WAIT_SECS = STOP_GRACE_SECS + 10.0
#: Default deadlines of the operations that wait for the service.
START_TIMEOUT_SECS = 30.0
STOP_TIMEOUT_SECS = STOP_WAIT_SECS + 15.0
RESTART_TIMEOUT_SECS = STOP_TIMEOUT_SECS + START_TIMEOUT_SECS


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
    """The service manager could not be asked or did not confirm in time:
    its program is missing or could not be started, it did not answer, or
    the outcome was not observed before the deadline."""


class SupervisorRefused(SupervisorError):
    """The service manager answered and refused (a nonzero exit, a task
    that does not exist, or a launcher that ended before a host started)."""


@dataclass(frozen=True)
class ServiceStatus:
    """``state`` is the portable answer; ``unknown`` means the manager could
    not be asked or did not answer in time (Windows; Linux raises
    :class:`SupervisorUnavailable` instead, as its callers expect). ``raw``
    is the manager's own word (systemd: what ``is-active`` printed;
    Windows: the task state, such as ``Running`` or ``Ready``, ``missing``,
    or why the query failed). ``last_result`` is the last exit status the
    manager recorded, ``None`` when it has none or was not asked (Linux)."""

    state: State
    raw: str
    last_result: int | None


def _backend():
    if os.name == "nt":
        from . import _supervisor_tasks

        return _supervisor_tasks
    from . import _supervisor_systemd

    return _supervisor_systemd


def host_name(home: Path | str | None = None) -> str:
    """The background host's unit or task for the ledger at *home*
    (default: the resolved ledger home). Linux: the one host unit, whatever
    the ledger. Windows: one task per user and ledger."""
    return _backend().host_name(names.ledger_home() if home is None else Path(home))


def state_dir(home: Path | str | None = None) -> Path:
    """Where the launcher keeps its log and its single-instance lock:
    ``supervisor/`` in the ledger's cache folder (``names.home_cache``)."""
    return names.home_cache(home) / "supervisor"


def register(name: str, command: Sequence[str], *, description: str,
             home: Path | str | None = None, timeout: float = DEFAULT_TIMEOUT_SECS) -> None:
    """Windows: make *name* (from :func:`host_name` for the same *home*)
    a per-user Task Scheduler task whose action is the launcher running
    *command* with the ledger at *home*. ``command[0]`` must be a fully
    qualified path, and no part of the action may contain ``%`` (Task
    Scheduler would expand it): :class:`ValueError` otherwise. Linux:
    ``NotImplementedError``."""
    _backend().register(name, list(command), description=description,
                        home=names.ledger_home() if home is None else Path(home), timeout=timeout)


def unregister(name: str, *, timeout: float = STOP_TIMEOUT_SECS) -> None:
    """Windows: stop *name* if it runs and remove that task only; a task
    that does not exist is already unregistered. Linux: ``NotImplementedError``."""
    _backend().unregister(name, timeout=timeout)


def start(name: str, *, timeout: float = START_TIMEOUT_SECS) -> None:
    """Start *name*. Windows: returns once a host is seen running under the
    launcher, else raises; starting a running service changes nothing."""
    _backend().start(name, timeout=timeout)


def stop(name: str, *, timeout: float = STOP_TIMEOUT_SECS) -> None:
    """Stop *name*. Windows: asks the launcher first (it lets the host
    finish for :data:`STOP_GRACE_SECS`, then ends it, and exits 0); ends
    the task if the launcher has not finished within :data:`STOP_WAIT_SECS`;
    raises unless the task is seen stopped by the deadline. Linux: the
    existing ``stop``, whose exit status is not checked (ask :func:`status`)."""
    _backend().stop(name, timeout=timeout)


def restart(name: str, *, timeout: float = RESTART_TIMEOUT_SECS) -> None:
    """Start *name* again, also after its manager gave up on it. Linux:
    ``reset-failed`` then ``restart``, the inbox's fix. Windows: stop, then
    start, under one deadline; returns once the new host is seen running."""
    _backend().restart(name, timeout=timeout)


def status(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> ServiceStatus:
    return _backend().status(name, timeout=timeout)


def last_result(name: str, *, timeout: float = DEFAULT_TIMEOUT_SECS) -> int | None:
    return _backend().last_result(name, timeout=timeout)
