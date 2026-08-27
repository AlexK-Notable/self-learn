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
    verbatim -- the original never logged from this function either)."""
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
