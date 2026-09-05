"""U-sdk §3.7 `Life-1` -- the kill ladder (`K-1`/`K-1a`/`K-1b`), the
guarded child kill (`K-2`), the defensive child-pid resolver (`K-3`), the
pid sidecar (`K-4`) and the start-of-run orphan sweep (`K-5`).

**U-engine (spec `u-engine-shared-sdk-core-spec.md` §4, Phase 1A):** the
MECHANISM now lives in `self_learn.sdksession` -- `ladder.py`,
`teardown.py`, `children.py` -- shared with the UI pane engine. This
module is a THIN SURFACE over it.

**Sprint 2 M-V (2026-09-04, sdk-lifecycle):** `write_sidecar`/
`read_sidecar`/`clear_sidecar` used to keep their OWN direct file I/O --
a carve-out `test_invocation_sdk.py::test_pl3_filesystem_writes_are_
enumerated_with_an_exact_count` pinned at an exact total of 5, naming
`(lifecycle.py, write_text)`/`(lifecycle.py, unlink)` among the allowed
call sites, because at that point `sdksession.children` shipped an
equivalent, more general implementation for the OTHER two consumers
only. That reason is gone: all three are now thin adapters over
`sdksession.children.write_sidecar`/`read_sidecar`/`clear_sidecar`
(called with `session_key=None`, so the sidecar filename shape stays
byte-identical to before -- `F-2`), and `test_pl3` is retargeted to
assert ZERO filesystem-mutating calls anywhere in this six-file
package. `_sidecar_path` stays a pure path computation with no I/O of
its own -- kept because `test_invocation_sdk.py`,
`test_reader_contract.py` and `test_sdk_lifecycle_delegation.py` call
it directly today to locate the file the delegate wrote (gate M-V r1,
minor 4: an earlier draft of this sentence named `test_serve.py`, which
never calls it).

`INTERRUPT_GRACE_SECS`/`KILL_SECS` are bound to the library's `ladder.py`
objects BY IDENTITY (`LAD2`/`LAD3` carry the analogous UI-side proof).
`_ABANDONED_DISCONNECTS` is bound to the library's registry object, also
by identity. `run_kill_ladder` stays a NAME in this module, read at CALL
TIME by every caller (`lifecycle.run_kill_ladder(...)`) -- and its own
body reads `KILL_SECS`/`INTERRUPT_GRACE_SECS` from ITS OWN globals at
call time too (design constraint `C-1`), which is what keeps every
existing `monkeypatch.setattr(lifecycle_mod, "KILL_SECS", ...)` test
valid unedited.

Import-bounded to stdlib plus `.. import worker` (`worker.cache_dir()` /
`worker._pid_alive(...)` at CALL time) plus `..sdksession`.
"""

from __future__ import annotations

import os  # noqa: F401 - kept so `lifecycle_mod.os` exists for `monkeypatch.setattr(lifecycle_mod.os, ...)` (test_kl5/test_to6); the real calls run inside `sdksession.teardown`, same global `os` module
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import worker
from ..sdksession import children, ladder, teardown
from ..sdksession.policy import ShutdownMessages

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

#: `K-1` -- bound by identity to `sdksession.ladder`'s objects (`LAD2`).
INTERRUPT_GRACE_SECS = ladder.INTERRUPT_GRACE_SECS
KILL_SECS = ladder.KILL_SECS

#: `K-1` step 2 -- bound by identity to the library's shared registry.
_ABANDONED_DISCONNECTS = teardown.ABANDONED_DISCONNECTS

#: This surface's operator-visible message table (§2.8's CLI-owned
#: rows: the 5-line teardown ladder, the 6-line orphan sweep, and the
#: child-pid-unresolved line `_run_session` still emits directly).
#: Exposed publicly (no leading underscore) so `backend.py`'s
#: `CliSessionPolicy.messages()` returns THIS object -- one definition,
#: not two hand-kept copies.
CLI_SHUTDOWN_MESSAGES = ShutdownMessages(
    disconnect_timeout=(
        "run: sdk backend: disconnect() still running at the kill "
        "bound — caller released; SDK subprocess escalation "
        "continues in the background"
    ),
    disconnect_raised="run: sdk backend: disconnect() raised: {exc}",
    abandoned_cancelled="run: sdk backend: abandoned disconnect() was cancelled",
    abandoned_finished="run: sdk backend: abandoned disconnect() finished with: {exc}",
    abandoned_completed="run: sdk backend: abandoned disconnect() completed",
    child_pid_unresolved="run: sdk backend could not resolve the child pid",
    orphan_malformed=lambda surface: (
        f"run: sdk backend: orphan sweep for {surface} declined (malformed sidecar)"
    ),
    orphan_no_live_process=lambda surface, pid: (
        f"run: sdk backend: orphan sweep for {surface} found no live process at pid {pid}"
    ),
    orphan_uncorroborated=lambda surface, pid: (
        f"run: sdk backend: orphan sweep for {surface} could not corroborate pid {pid}"
    ),
    orphan_cmdline_mismatch=lambda surface, pid: (
        f"run: sdk backend: orphan sweep for {surface} declined (pid {pid} cmdline mismatch)"
    ),
    orphan_not_stale=lambda surface, pid: (
        f"run: sdk backend: orphan sweep for {surface} declined (pid {pid} not stale)"
    ),
    orphan_killed=lambda surface, pid: (
        f"run: sdk backend: orphan sweep for {surface} killed stale pid {pid}"
    ),
)


def child_pid_of(client: Any) -> int | None:
    """`K-3` -- delegates verbatim to the library's defensive walk."""
    return children.child_pid_of(client)


def _sidecar_path(surface: str) -> Path:
    return worker.cache_dir() / f"{surface}.sdk-child.pid"


def write_sidecar(surface: str, pid: int, cli: str) -> None:
    """`K-4` -- written as soon as the child pid is known. Delegates to
    `sdksession.children.write_sidecar` (see the module docstring's
    Sprint 2 M-V note) -- `session_key=None` reproduces `_sidecar_path`'s
    filename byte-for-byte."""
    children.write_sidecar(worker.cache_dir(), surface, pid, cli, session_key=None)


def read_sidecar(surface: str) -> dict[str, Any] | None:
    """Delegates to `sdksession.children.read_sidecar` -- see the module
    docstring's Sprint 2 M-V note."""
    return children.read_sidecar(worker.cache_dir(), surface, session_key=None)


def clear_sidecar(surface: str) -> None:
    """`K-4`/`K-5` -- unlinked whether the session succeeded, failed, or
    timed out. Delegates to `sdksession.children.clear_sidecar` -- see
    the module docstring's Sprint 2 M-V note."""
    children.clear_sidecar(worker.cache_dir(), surface, session_key=None)


def kill_child(pid: int | None, log: Callable[[str], None]) -> None:
    """`K-2` -- delegates to the library, passing `worker._pid_alive`
    looked up at CALL time (an attribute access on the `worker` module
    object performed inside this function body), so
    `monkeypatch.setattr(lifecycle_mod.worker, "_pid_alive", ...)`
    still takes effect."""
    teardown.kill_child(pid, log, worker._pid_alive)


async def run_kill_ladder(client: Any, child_pid: int | None, log: Callable[[str], None]) -> None:
    """`K-1` -- the CLI's three-rung ladder, run on timeout AND
    unconditionally in `finally`. Design constraint `C-1`: reads its OWN
    module-level `KILL_SECS`/`INTERRUPT_GRACE_SECS` at CALL time (bare
    names, resolved against THIS module's globals), so a test's
    `monkeypatch.setattr(lifecycle_mod, "KILL_SECS", ...)` is observed
    by this exact call. `loop_closing=True` (`R-1`): the CLI's
    `run_sync` bridge means the event loop closes when this coroutine's
    caller returns, so step 3 (the explicit child kill) always runs --
    today's exact, unconditional behaviour."""
    await teardown.run_kill_ladder(
        client,
        child_pid,
        log,
        kill_secs=KILL_SECS,
        interrupt_grace_secs=INTERRUPT_GRACE_SECS,
        loop_closing=True,
        pid_alive=worker._pid_alive,
        messages=CLI_SHUTDOWN_MESSAGES,
    )


def sweep_orphans(surface: str, log: Callable[[str], None]) -> None:
    """`K-5` -- before connecting, delegates to the library's scoped
    sweep over every sidecar recorded for `surface`. `worker.cache_dir()`
    and `worker._pid_alive` are both looked up at CALL time."""
    children.sweep_orphans(
        worker.cache_dir(),
        surface,
        log,
        pid_alive=worker._pid_alive,
        messages=CLI_SHUTDOWN_MESSAGES,
    )
