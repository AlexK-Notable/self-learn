"""U-sdk §3.7 `Life-1` — the kill ladder (`K-1`/`K-1a`/`K-1b`), the
guarded child kill (`K-2`), the defensive child-pid resolver (`K-3`), the
pid sidecar (`K-4`) and the start-of-run orphan sweep (`K-5`).

The ONLY module in this unit that sends a signal (§ files-this-unit-may-
touch table). Import-bounded to stdlib plus `.. import worker` (the
module object, `I-d`) -- every `worker` use is `worker.cache_dir()` /
`worker._pid_alive(...)` at CALL time, so a test's
`monkeypatch.setattr(worker, ...)` is observed.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import worker

__all__ = [
    "INTERRUPT_GRACE_SECS",
    "KILL_SECS",
    "child_pid_of",
    "clear_sidecar",
    "kill_child",
    "read_sidecar",
    "run_kill_ladder",
    "sweep_orphans",
    "write_sidecar",
]

#: `K-1` -- `sdk.py`'s tuned 2026-07-18 defaults, ported verbatim.
INTERRUPT_GRACE_SECS = 1.0
KILL_SECS = 2.5

#: `K-1` step 2 -- strong references to abandoned `disconnect()` tasks;
#: asyncio's own registry holds tasks weakly, so this is what keeps a
#: background escalation alive until it finishes (ported verbatim from
#: `sdk.py`'s `_ABANDONED_DISCONNECTS`).
_ABANDONED_DISCONNECTS: set[asyncio.Task[Any]] = set()


def _log_abandoned_disconnect(task: asyncio.Task[Any], log: Callable[[str], None]) -> None:
    """Ported verbatim from `sdk.py`'s `_log_abandoned_disconnect` --
    retrieves the abandoned disconnect()'s outcome (never let it die as
    an un-retrieved exception) and logs the completion."""
    if task.cancelled():
        log("run: sdk backend: abandoned disconnect() was cancelled")
        return
    exc = task.exception()
    if exc is not None:
        log(f"run: sdk backend: abandoned disconnect() finished with: {exc}")
    else:
        log("run: sdk backend: abandoned disconnect() completed")


def child_pid_of(client: Any) -> int | None:
    """`K-3` -- DEFENSIVE: walks private attributes and returns `None` on
    ANY failure, never raising. An SDK-internal rename must degrade to
    "pid unknown", not a total outage of the backend. `client` is typed
    `Any` deliberately -- this module may not import `claude_agent_sdk`
    (§3.1's table)."""
    try:
        return client._transport._process.pid  # noqa: SLF001 - deliberate, defensive
    except (AttributeError, TypeError):
        return None


def _sidecar_path(surface: str) -> Path:
    return worker.cache_dir() / f"{surface}.sdk-child.pid"


def write_sidecar(surface: str, pid: int, cli: str) -> None:
    """`K-4` -- written as soon as the child pid is known. Carries more
    than a bare pid: a bare pid is a pid-reuse foot-gun -- a sweep that
    trusts one can SIGKILL an unrelated process that inherited the
    number."""
    path = _sidecar_path(surface)
    path.write_text(
        json.dumps({"pid": pid, "started_at": time.time(), "cli": cli}),
        encoding="utf-8",
    )


def read_sidecar(surface: str) -> dict[str, Any] | None:
    path = _sidecar_path(surface)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_sidecar(surface: str) -> None:
    """`K-4`/`K-5` -- unlinked whether the session succeeded, failed, or
    timed out; also the ONE call site the orphan sweep uses once it is
    done with a sidecar it read (`PL3` pins the exact write/unlink count
    across this package)."""
    _sidecar_path(surface).unlink(missing_ok=True)


def kill_child(pid: int | None, log: Callable[[str], None]) -> None:
    """`K-2` -- the `getpgid` guard, MEASURED and load-bearing: the SDK's
    child shares the caller's process group (no `start_new_session`, no
    `preexec_fn` -- `anyio.open_process` is called plain), so an
    unguarded `killpg` would kill the worker/miner/analyst itself. Tested
    through RECORDERS (`K-2a`), never real signals, for exactly this
    reason."""
    del log
    if pid is None or not worker._pid_alive(pid):
        return
    try:
        if os.getpgid(pid) != os.getpgid(0):
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def run_kill_ladder(
    client: Any, child_pid: int | None, log: Callable[[str], None]
) -> None:
    """`K-1` -- three rungs, run on timeout AND unconditionally in
    `finally`.

    Step 3 is what makes the ladder terminate in a SYNC frame
    (`K-1a`/`K-1b`): `run_sync` drives this coroutine via `asyncio.run`,
    which closes the event loop on return -- any background task (the
    abandoned `disconnect()` of step 2) dies unfinished, and the SDK's
    own SIGTERM/SIGKILL escalation inside it never completes. On the
    timeout path, `close()`'s own teardown spends its first 5s window
    waiting gracefully with NO signal sent at all -- `KILL_SECS` (2.5s)
    expires inside that window, so step 3 is, in practice, the only
    thing that signals the child before the loop closes."""
    # Step 1 -- bounded interrupt(); ANY failure, including the timeout,
    # is swallowed and escalates to step 2. Cancel-on-timeout is safe
    # here: the abandoned control request is moot once step 2
    # disconnects the transport.
    try:
        await asyncio.wait_for(client.interrupt(), timeout=INTERRUPT_GRACE_SECS)
    except Exception:  # noqa: BLE001 - any transport failure escalates
        pass

    # Step 2 -- SHIELDED disconnect(): never cancelled -- a raw cancel
    # pierces the SDK transport's own shielded SIGTERM/SIGKILL escalation
    # (its own docstring carries the caveat). On expiry the task is
    # abandoned, never cancelled, held by a strong module-level reference
    # with both done-callbacks (discard + log).
    task: asyncio.Task[Any] = asyncio.ensure_future(client.disconnect())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=KILL_SECS)
    except TimeoutError:
        # `MAJOR-1` -- ported verbatim from `sdk.py:300-313`'s TWO
        # branches: this one fires ONLY when the shielded wait itself
        # expired (`O-quiet` line 4), never for a `disconnect()` that
        # raised something else -- collapsing the two into one `except
        # Exception` would report an immediately-raising disconnect() as
        # "still running... escalation continues in the background",
        # which is false, and would track its (already-finished) task in
        # `_ABANDONED_DISCONNECTS` for no reason.
        log(
            "run: sdk backend: disconnect() still running at the kill "
            "bound — caller released; SDK subprocess escalation "
            "continues in the background"
        )
        _ABANDONED_DISCONNECTS.add(task)
        task.add_done_callback(_ABANDONED_DISCONNECTS.discard)
        task.add_done_callback(lambda t: _log_abandoned_disconnect(t, log))
    except Exception as exc:  # noqa: BLE001 - disconnect() must never raise uncaught
        # `MAJOR-1` -- the port source's second branch: `disconnect()`
        # itself raised (not a timeout) -- reported by its own line, and
        # NOT tracked in `_ABANDONED_DISCONNECTS` (the task is already
        # done; there is nothing left to escalate in the background).
        log(f"run: sdk backend: disconnect() raised: {exc}")

    # Step 3 -- explicit child kill, BEFORE this coroutine returns.
    kill_child(child_pid, log)


def sweep_orphans(surface: str, log: Callable[[str], None]) -> None:
    """`K-5` -- before connecting, kill a sidecar-recorded pid for this
    surface ONLY when all three corroborating checks hold. Any check that
    cannot be performed means DO NOT kill -- unlink the sidecar and log
    one line. Silent when there is nothing to sweep at all (no sidecar
    present -- `O-quiet`)."""
    record = read_sidecar(surface)
    if record is None:
        return
    pid = record.get("pid")
    started_at = record.get("started_at")
    cli = record.get("cli")
    if not isinstance(pid, int) or not isinstance(started_at, (int, float)):
        clear_sidecar(surface)
        log(f"run: sdk backend: orphan sweep for {surface} declined (malformed sidecar)")
        return
    if not worker._pid_alive(pid):
        clear_sidecar(surface)
        log(f"run: sdk backend: orphan sweep for {surface} found no live process at pid {pid}")
        return
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        clear_sidecar(surface)
        log(f"run: sdk backend: orphan sweep for {surface} could not corroborate pid {pid}")
        return
    first = raw.split(b"\x00")[0].decode("utf-8", "replace")
    basename = os.path.basename(first)
    cli_basename = os.path.basename(cli) if isinstance(cli, str) else None
    matches = basename == "claude" or (cli_basename is not None and basename == cli_basename)
    if not matches:
        clear_sidecar(surface)
        log(f"run: sdk backend: orphan sweep for {surface} declined (pid {pid} cmdline mismatch)")
        return
    if not (started_at < _process_start()):
        clear_sidecar(surface)
        log(f"run: sdk backend: orphan sweep for {surface} declined (pid {pid} not stale)")
        return
    kill_child(pid, log)
    clear_sidecar(surface)
    log(f"run: sdk backend: orphan sweep for {surface} killed stale pid {pid}")


#: `K-5` -- "older than the current process's start", approximated as
#: this module's first-import time (close enough for a pid-reuse guard,
#: which is inherently a heuristic rather than a hard security boundary).
_PROCESS_START = time.time()


def _process_start() -> float:
    return _PROCESS_START
