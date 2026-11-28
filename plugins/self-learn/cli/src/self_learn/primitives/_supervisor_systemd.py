"""The systemd user manager behind ``primitives.supervisor``.

Each argument list is a copy of a ``systemctl --user`` call that existed
before this interface; the original statement is quoted beside each copy.
Every call goes through ``procs.run_bounded``. ``start``, ``enable``,
``disable`` and ``show`` had no caller in the Python tree; they are new
and marked so.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from . import procs
from .supervisor import ServiceStatus, SupervisorRefused, SupervisorUnavailable

HOST_NAME = "self-learn-host.service"

#: attention_answers.py:1517 `_STILL_RUNNING = frozenset({"active",
#: "activating", "deactivating", "reloading", "refreshing"})`.
_STILL_RUNNING = frozenset({"active", "activating", "deactivating", "reloading", "refreshing"})


def _systemctl(verb: str, unit: str) -> str:
    # attention_answers.py:1487-1489:
    #     binary = shutil.which("systemctl")
    #     if binary is None:
    #         raise AnswerError("systemctl is not on PATH", EXIT_REFUSED)
    binary = shutil.which("systemctl")
    if binary is None:
        raise SupervisorUnavailable("systemctl is not on PATH", verb=verb, name=unit)
    return binary


def _call(verb: str, unit: str, argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return procs.run_bounded(argv, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        # attention_answers.py:1496-1497:
        #     except (OSError, subprocess.TimeoutExpired) as exc:
        #         raise AnswerError(f"systemctl --user {verb} {HOST_UNIT} failed: {exc}", EXIT_REFUSED) from exc
        raise SupervisorUnavailable(f"systemctl --user {verb} {unit} failed: {exc}",
                                    verb=verb, name=unit, detail=str(exc)) from exc


def _checked(verb: str, unit: str, timeout: float) -> None:
    binary = _systemctl(verb, unit)
    # attention_answers.py:1492-1495 (verb in "reset-failed", "restart"):
    #     proc = subprocess.run(
    #         [binary, "--user", verb, HOST_UNIT], capture_output=True, text=True,
    #         timeout=FIX_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL,
    #     )
    proc = _call(verb, unit, [binary, "--user", verb, unit], timeout)
    if proc.returncode != 0:
        # attention_answers.py:1498-1502:
        #     if proc.returncode != 0:
        #         raise AnswerError(
        #             f"systemctl --user {verb} {HOST_UNIT} exited {proc.returncode}: "
        #             f"{str(proc.stderr or proc.stdout or '').strip()[:400]}", EXIT_REFUSED,
        #         )
        detail = str(proc.stderr or proc.stdout or "").strip()[:400]
        raise SupervisorRefused(f"systemctl --user {verb} {unit} exited {proc.returncode}: {detail}",
                                verb=verb, name=unit, detail=detail, returncode=proc.returncode)


def active_word(unit: str, *, timeout: float) -> str:
    """What ``systemctl --user is-active <unit>`` printed, ``unknown`` when
    it printed nothing. Its exit status is not an error: it is nonzero for
    every state but active."""
    binary = _systemctl("is-active", unit)
    # attention.py:1120-1123:
    #     proc = subprocess.run(
    #         ["systemctl", "--user", "is-active", unit], capture_output=True, text=True,
    #         timeout=SYSTEMCTL_TIMEOUT_SECS, check=False,
    #     )
    # attention_answers.py:1558-1561 (`_unit_state`):
    #     proc = subprocess.run(
    #         [binary, "--user", "is-active", unit], capture_output=True, text=True,
    #         timeout=STOP_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL,
    #     )
    proc = _call("is-active", unit, [binary, "--user", "is-active", unit], timeout)
    # attention_answers.py:1564: `return str(proc.stdout or "").strip() or "unknown"`
    return str(proc.stdout or "").strip() or "unknown"


def _show(unit: str, timeout: float) -> dict[str, str]:
    # New: no Python caller asked `show` before this interface.
    binary = _systemctl("show", unit)
    argv = [binary, "--user", "show", unit, "--property=LoadState,ActiveState,Result,ExecMainStatus"]
    proc = _call("show", unit, argv, timeout)
    if proc.returncode != 0:
        detail = str(proc.stderr or proc.stdout or "").strip()[:400]
        raise SupervisorRefused(f"systemctl --user show {unit} exited {proc.returncode}: {detail}",
                                verb="show", name=unit, detail=detail, returncode=proc.returncode)
    fields = {}
    for line in str(proc.stdout or "").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def _exit_status(fields: dict[str, str]) -> int | None:
    try:
        return int(fields.get("ExecMainStatus", ""))
    except ValueError:
        return None


def status(name: str, *, timeout: float) -> ServiceStatus:
    word = active_word(name, timeout=timeout)
    if word in _STILL_RUNNING:
        # One call, as before: a running unit's last result is not asked.
        return ServiceStatus("running", word, None)
    fields = _show(name, timeout)
    result = _exit_status(fields)
    if fields.get("LoadState") == "not-found":
        return ServiceStatus("missing", word, result)
    if word == "failed" or fields.get("Result", "success") != "success":
        return ServiceStatus("failed", word, result)
    return ServiceStatus("stopped", word, result)


def last_result(name: str, *, timeout: float) -> int | None:
    return _exit_status(_show(name, timeout))


def start(name: str, *, timeout: float) -> None:
    # New: the Python tree never started a unit (`self-learn-ui-open`, a
    # Bash script, runs `systemctl --user start`).
    _checked("start", name, timeout)


def stop(name: str, *, timeout: float) -> None:
    # attention_answers.py:1625-1628 (`stop`, which ignores the exit status
    # and asks `is-active` afterwards; a caller doing the same catches
    # SupervisorRefused):
    #     subprocess.run(
    #         [binary, "--user", "stop", unit], capture_output=True, text=True,
    #         timeout=STOP_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL,
    #     )
    _checked("stop", name, timeout)


def restart(name: str, *, timeout: float) -> None:
    # attention_answers.py:1490: `for verb in ("reset-failed", "restart"):`
    for verb in ("reset-failed", "restart"):
        _checked(verb, name, timeout)


def register(name: str, command: list[str], *, description: str, home: Path,
             timeout: float) -> None:
    # New. install.sh links the unit and never enables it; the unit file
    # says what runs and with which ledger, so `command`, `description`
    # and `home` have nothing to set here.
    del command, description, home
    _checked("enable", name, timeout)


def unregister(name: str, *, timeout: float) -> None:
    # New. `disable --now` would differ from the Windows order only in
    # wording; two calls keep each one a plain copy of the verb.
    _checked("stop", name, timeout)
    _checked("disable", name, timeout)
