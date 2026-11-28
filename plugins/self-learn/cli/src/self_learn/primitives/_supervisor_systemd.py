"""The systemd user manager behind ``primitives.supervisor``.

Only calls the product already makes, each argument list a copy with the
original quoted beside it, every one through ``procs.run_bounded``:
``is-active`` (``attention.py``, ``attention_answers.py``), ``reset-failed``
then ``restart`` (``attention_answers.fix``), ``stop``
(``attention_answers.stop``) and ``start`` (the tray's ``START_HOST_ARGV``).
Nothing here enables, disables or inspects a unit file: ``install.sh``
links the unit and the person enables it, so ``register`` and
``unregister`` are not provided, ``missing`` cannot be told from
``inactive``, and no last result is read. A caller that needs those adds
its own call (for example ``systemctl --user show``) with its own review.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from . import procs
from .supervisor import ServiceStatus, State, SupervisorRefused, SupervisorUnavailable

HOST_NAME = "self-learn-host.service"

#: attention_answers.py:1517 `_STILL_RUNNING = frozenset({"active",
#: "activating", "deactivating", "reloading", "refreshing"})`.
_STILL_RUNNING = frozenset({"active", "activating", "deactivating", "reloading", "refreshing"})


def host_name(home: Path) -> str:
    del home  # One host unit; it pins its own ledger (Environment=SELF_LEARN_HOME).
    return HOST_NAME


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


def _state(word: str) -> State:
    if word in _STILL_RUNNING:
        return "running"
    if word == "failed":
        return "failed"
    return "stopped" if word == "inactive" else "unknown"


def status(name: str, *, timeout: float) -> ServiceStatus:
    """One ``is-active`` call, as before."""
    word = active_word(name, timeout=timeout)
    return ServiceStatus(_state(word), word, None)


def last_result(name: str, *, timeout: float) -> int | None:
    del name, timeout  # No existing call reads it (see the module docstring).
    return None


def start(name: str, *, timeout: float) -> None:
    # plugins/self-learn/scripts/self-learn-tray:54:
    #     START_HOST_ARGV = ["systemctl", "--user", "start", "self-learn-host.service"]
    _checked("start", name, timeout)


def stop(name: str, *, timeout: float) -> None:
    binary = _systemctl("stop", name)
    # attention_answers.py:1625-1628 (`stop`, which does not check the exit
    # status and asks `is-active` afterwards):
    #     subprocess.run(
    #         [binary, "--user", "stop", unit], capture_output=True, text=True,
    #         timeout=STOP_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL,
    #     )
    _call("stop", name, [binary, "--user", "stop", name], timeout)


def restart(name: str, *, timeout: float) -> None:
    # attention_answers.py:1490: `for verb in ("reset-failed", "restart"):`
    for verb in ("reset-failed", "restart"):
        _checked(verb, name, timeout)


def register(name: str, command: list[str], *, description: str, home: Path,
             timeout: float) -> None:
    raise NotImplementedError("on Linux install.sh links the unit and the person enables it")


def unregister(name: str, *, timeout: float) -> None:
    raise NotImplementedError("on Linux install.sh links the unit and the person enables it")
