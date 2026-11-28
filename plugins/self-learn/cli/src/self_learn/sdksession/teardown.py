"""U-engine sdksession — `teardown.py` (spec §4.2): the kill ladder --
bounded `interrupt()`, SHIELDED `disconnect()` never cancelled, the
abandoned-task registry with both done-callbacks, and the guarded child
kill.

`ABANDONED_DISCONNECTS` is THE module-level registry object (`LAD2`):
`invocation_sdk/lifecycle.py` and `ui engine/sdk.py` both bind their own
name to THIS set, by identity, not a copy.

`R-1` (§4.6): `run_kill_ladder`'s step 3 (the explicit child kill) is
CONDITIONAL on `loop_closing`. The seam passes `True` (today's CLI
behaviour, unconditional, byte-identical); the pane passes `False` and
lets the SDK's own shielded escalation finish on its own -- which is
already exactly what `SdkPaneEngine.close()` does today (it never had a
step 3), so `loop_closing=False` reproduces the UI's existing behaviour
by construction, not by a new branch. `interrupt_grace_secs=None` skips
step 1 entirely -- the UI's `close()` never ran a bounded `interrupt()`
of its own (that lives in its OWN `interrupt()` method); only the CLI's
ladder runs all three steps every time (`finally`, unconditional).

Import-bounded: stdlib only.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .policy import ShutdownMessages

__all__ = ["ABANDONED_DISCONNECTS", "kill_child", "run_kill_ladder"]
#: `bounded_interrupt` is deliberately NOT exported (gate r1 N-1/M-1):
#: it has zero importers anywhere outside this module's own
#: `shielded_disconnect` -- Sec 9.2's row for `sdk.py` names it as the
#: intended `interrupt()` delegate, but adopting it now would be a
#: real UI production-behaviour change this fold round does not make
#: (Sec C's byte-identical-messages proof would need re-verifying).
#: Kept as a private module function, callable via `teardown.
#: bounded_interrupt` for a future consumer, but no longer claimed as
#: part of the library's public surface.

#: `K-1` step 2 -- strong references to abandoned `disconnect()` tasks;
#: asyncio's own registry holds tasks weakly, so this is what keeps a
#: background escalation alive until it finishes. THE shared registry
#: object both engines bind by identity (`LAD2`/`LAD3`).
ABANDONED_DISCONNECTS: "set[asyncio.Task[Any]]" = set()


async def bounded_interrupt(client: Any, grace_secs: float) -> None:
    """Step 1 -- bounded `interrupt()`; ANY failure, including the
    timeout, is swallowed and escalates to step 2."""
    try:
        await asyncio.wait_for(client.interrupt(), timeout=grace_secs)
    except Exception:  # noqa: BLE001 - any transport failure escalates
        pass


def _log_abandoned_disconnect(
    task: "asyncio.Task[Any]", log: Callable[[str], None], messages: ShutdownMessages
) -> None:
    """Retrieves the abandoned disconnect()'s outcome (never let it die
    as an un-retrieved exception) and logs the completion."""
    if task.cancelled():
        log(messages.abandoned_cancelled)
        return
    exc = task.exception()
    if exc is not None:
        log(messages.abandoned_finished.format(exc=exc))
    else:
        log(messages.abandoned_completed)


async def shielded_disconnect(
    client: Any, kill_secs: float, log: Callable[[str], None], messages: ShutdownMessages
) -> None:
    """Step 2 -- SHIELDED `disconnect()`: never cancelled -- a raw
    cancel pierces the SDK transport's own shielded SIGTERM/SIGKILL
    escalation (its own docstring carries the caveat). On expiry the
    task is abandoned, never cancelled, held by a strong module-level
    reference with both done-callbacks (discard + log)."""
    task: "asyncio.Task[Any]" = asyncio.ensure_future(client.disconnect())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=kill_secs)
    except TimeoutError:
        # `MAJOR-1` -- fires ONLY when the shielded wait itself expired,
        # never for a `disconnect()` that raised something else.
        log(messages.disconnect_timeout)
        ABANDONED_DISCONNECTS.add(task)
        task.add_done_callback(ABANDONED_DISCONNECTS.discard)
        task.add_done_callback(lambda t: _log_abandoned_disconnect(t, log, messages))
    except Exception as exc:  # noqa: BLE001 - disconnect() must never raise uncaught
        # the port source's second branch: disconnect() itself raised
        # (not a timeout) -- NOT tracked in ABANDONED_DISCONNECTS (the
        # task is already done; there is nothing left to escalate).
        log(messages.disconnect_raised.format(exc=exc))


def kill_child(pid: int | None, log: Callable[[str], None], pid_alive: Callable[[int], bool]) -> None:
    """`K-2` -- the `getpgid` guard, MEASURED and load-bearing: the
    SDK's child shares the caller's process group (no
    `start_new_session`, no `preexec_fn`), so an unguarded `killpg`
    would kill the caller itself. `log` is accepted, unused (ported
    verbatim -- the original never logged from this function either).

    S-NEXT-w6-sdk, Windows only: ends the job :func:`contain_session_child`
    put the child in (its descendants with it), never a bare PID, and logs
    a failure instead of raising; see :func:`_kill_contained`."""
    if os.name == "nt":
        if pid is not None and pid_alive(pid):
            _kill_contained(pid, log)
        return
    del log
    if pid is None or not pid_alive(pid):
        return
    try:
        if os.getpgid(pid) != os.getpgid(0):
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def run_kill_ladder(
    client: Any,
    child_pid: int | None,
    log: Callable[[str], None],
    *,
    kill_secs: float,
    interrupt_grace_secs: float | None,
    loop_closing: bool,
    pid_alive: Callable[[int], bool],
    messages: ShutdownMessages,
) -> None:
    """The CLI-shaped three-rung composition (`K-1`), run on timeout AND
    unconditionally in `finally`.

    `interrupt_grace_secs=None` skips step 1 entirely (the UI's own
    ladder shape: its `close()` never ran a bounded `interrupt()` --
    that lives in its separate `interrupt()` method). `loop_closing`
    gates step 3 (`R-1`): `True` reproduces the CLI's existing
    unconditional child kill; `False` reproduces the UI's existing
    absence of one.
    """
    if interrupt_grace_secs is not None:
        await bounded_interrupt(client, interrupt_grace_secs)

    await shielded_disconnect(client, kill_secs, log, messages)

    if loop_closing:
        kill_child(child_pid, log, pid_alive)


# --------------------------------------------------------------------------
# S-NEXT-w6-sdk: Windows containment of the SDK's Claude Code child.
#
# On Windows the child is put in a kill-on-close job object right after its
# PID is known, and the ladder's last rung ends that job (the child and every
# descendant in it) instead of signalling a process group. Nothing below runs
# on Linux: every entry point is reached only under `os.name == "nt"`.
#
# `LIB1` keeps this package stdlib-only, so it never imports the process
# calls itself: a client registers them with :func:`use_containment` (the CLI
# registers `self_learn.primitives.procs` when `invocation_sdk.backend` is
# imported on Windows). Its operator-visible lines come from the client too
# (`POL2`), in a :class:`ContainmentMessages`.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContainmentMessages:
    """The client's lines for containment trouble. Each is a
    ``str.format`` template; ``{pid}`` and ``{exc}`` are filled where named.
    A containment problem is only ever logged: it never fails a session."""

    #: `contain_self()` refused (``{exc}``).
    self_failed: str
    #: `contain_child(pid)` failed (``{pid}``, ``{exc}``).
    contain_failed: str
    #: The child was contained but its adoption sweep was incomplete or could
    #: not reach every descendant (``{pid}``, ``{exc}``: what was reported).
    contain_incomplete: str
    #: Ending the contained child at the last rung failed or timed out
    #: (``{pid}``, ``{exc}``).
    terminate_failed: str


class _Contained:
    """One SDK child this process contained: the job handle (``None`` when
    containment failed) and the identity read when it was contained (``None``
    when it could not be read)."""

    def __init__(self, handle: Any, identity: Any) -> None:
        self.handle = handle
        self.identity = identity


#: The registered process calls and messages (`use_containment`); empty until
#: a client registers them.
_CONTAINMENT: list[tuple[Any, ContainmentMessages]] = []

#: Each SDK child this process contained, by PID, held for the whole session.
#: Holding the job handle keeps the job open: dropping it, or this process
#: ending, closes the job and kills the child and its descendants. A held
#: handle also pins the PID, so the key cannot pass to another process while
#: the entry lives. The last rung (`kill_child`) removes the entry.
CONTAINED: dict[int, _Contained] = {}

#: Set once `contain_self` has been tried in this process.
_SELF_TRIED: list[bool] = []


def use_containment(facade: Any, messages: ContainmentMessages) -> None:
    """Register the process calls (``contain_child``, ``terminate_contained``,
    ``process_identity``, ``identity_predates_boot``, ``contain_self`` and the
    ``ProcessIdentity`` class, as in `self_learn.primitives.procs`) and the
    lines to log. Windows only; a later call replaces the earlier one."""
    _CONTAINMENT[:] = [(facade, messages)]


def containment() -> tuple[Any, ContainmentMessages] | None:
    """The registered ``(facade, messages)``, or ``None``."""
    return _CONTAINMENT[0] if _CONTAINMENT else None


def contain_self(log: Callable[[str], None]) -> None:
    """Windows: put this process in its own kill-on-close job before the first
    Claude Code child is spawned, so that child is born inside it and dies with
    this process however it ends. Tried once per process; a refusal is logged
    once and never raised (`KeyboardInterrupt` and the like still propagate)."""
    registered = containment()
    if registered is None or _SELF_TRIED:
        return
    facade, messages = registered
    pass
    try:
        facade.contain_self()
    except Exception as exc:  # noqa: BLE001 - containment never fails a session
        log(messages.self_failed.format(exc=exc))


def contain_session_child(pid: int, log: Callable[[str], None]) -> None:
    """Windows: put the SDK's Claude Code child *pid* (and the descendants it
    already has) in a fresh kill-on-close job, and keep the handle in
    :data:`CONTAINED` for the session, together with the identity
    `children.write_sidecar` records. A failure is logged, never raised: the
    session goes on uncontained, ended by the SDK's own teardown. A handle
    that the failing call carried as ``contained_child`` (containment was
    interrupted after the child joined the job) is kept like any other, so
    the last rung still ends it; a non-``Exception`` interruption is
    re-raised after that."""
    registered = containment()
    if registered is None:
        return
    facade, messages = registered
    try:
        handle = facade.contain_child(pid)
    except BaseException as exc:
        handle = None
        identity = handle.identity if handle is not None else _identity_or_none(facade, pid)
        CONTAINED[pid] = _Contained(handle, identity)
        if not isinstance(exc, Exception):
            raise
        log(messages.contain_failed.format(pid=pid, exc=exc))
        return
    if handle is None:
        # Already gone (or never existed): nothing to contain, and the
        # session fails on its own when the SDK reads from the child.
        CONTAINED[pid] = _Contained(None, None)
        return
    CONTAINED[pid] = _Contained(handle, handle.identity)
    uncovered = tuple(getattr(handle, "uncovered", ()) or ())
    if uncovered or getattr(handle, "complete", True) is False:
        log(messages.contain_incomplete.format(
            pid=pid, exc=f"uncovered {list(uncovered)}, sweep complete: {getattr(handle, 'complete', None)}"
        ))


def _identity_or_none(facade: Any, pid: int) -> Any:
    try:
        return facade.process_identity(pid)
    except Exception:  # noqa: BLE001 - an unreadable identity is recorded as none
        return None


def session_identity(pid: int) -> Any:
    """The identity recorded for the contained child *pid*, or ``None``."""
    entry = CONTAINED.get(pid)
    return entry.identity if entry is not None else None


def _kill_contained(pid: int | None, log: Callable[[str], None]) -> None:
    """The Windows body of :func:`kill_child`. Ends the job held for *pid*
    whether or not the child itself is still alive (the SDK's own teardown
    ends only the child; its descendants are still in the job). With no
    handle but an identity recorded at spawn, the PID is contained again only
    if it is still that identity (``expect``), so a reused PID is never
    touched; with neither, nothing is killed. Failures, timeouts included,
    are logged and never raised."""
    if pid is None:
        return
    entry = CONTAINED.pop(pid, None)
    registered = containment()
    if entry is None or registered is None:
        return
    facade, messages = registered
    handle = entry.handle
    try:
        if handle is None and entry.identity is not None and not facade.identity_predates_boot(entry.identity):
            handle = facade.contain_child(pid, expect=entry.identity)
        facade.terminate_contained(handle)
    except Exception as exc:  # noqa: BLE001 - the last rung never raises
        carried = getattr(exc, "contained_child", None)
        if carried is not None:
            try:
                facade.terminate_contained(carried)
            except Exception:  # noqa: BLE001 - already reporting the first failure
                pass
        log(messages.terminate_failed.format(pid=pid, exc=exc))


def hold_contained(pid: int, handle: Any, identity: Any) -> None:
    """Keep *handle* (a contained process *pid* with *identity*) in
    :data:`CONTAINED` until :func:`kill_child` ends it. Windows only; used by
    the orphan sweep, which contains a leftover child before killing it."""
    CONTAINED[pid] = _Contained(handle, identity)
