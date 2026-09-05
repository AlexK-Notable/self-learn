"""U-sdk §3.8 `Ev-1` — capture: `EventLog`, the JSONL sink, retention.

The ONLY other module in this unit that writes a file (`lifecycle.py`'s
pid sidecar is the other -- `E-6`). Import-bounded to stdlib plus
`.. import worker` (the module object, `I-d`) -- `worker.cache_dir()` at
call time -- plus, as of U-settings Phase 1, `.. import settings` and
`..ledger.resolve_home` for :func:`prune_event_logs`'s config.yaml rung
(`settings.py` itself imports only `config.py`, which imports only
`ruamel.yaml` -- no new heavy dependency enters this module's graph).

**U-engine (§4.2/§4.6 `F-1`):** `EventLog` and `new_run_id` delegate to
`self_learn.sdksession.events` verbatim.

**Sprint 2 M-V (2026-09-04, sdk-lifecycle):** `write_event_log` and
`prune_event_logs` used to keep their OWN fully self-contained file I/O
-- a carve-out `test_invocation_sdk.py::test_pl3_filesystem_writes_are_
enumerated_with_an_exact_count` pinned at an exact total of 5, naming
`(events.py, write_text)`/`(events.py, unlink)`/`(events.py, mkdir)`
among the allowed call sites, because `test_worker_contract.py::
test_ev4_tool_events_string_confined_to_events_module` (see that test's
own docstring -- it is NOT armor-pinned, unlike an earlier draft of this
docstring claimed) requires the `"tool-events"` filename literal to stay
confined to this module, and the library's generalised
`sdksession.events` functions take that literal as a caller-supplied
`log_kind` instead of hardcoding it. Both reasons still hold `log_kind`
here, but the WRITE/UNLINK ITSELF no longer needs to be this module's
own: `write_event_log` and `prune_event_logs` are now thin adapters over
`sdksession.events.write_event_log`/`prune_event_logs`, called with
`cache_dir=worker.cache_dir()` and `log_kind="tool-events"` -- and
`test_pl3` is retargeted to assert ZERO filesystem-mutating calls
anywhere in this six-file package. `prune_event_logs` keeps ONE local
`cache.glob(...)` read (no mutation) as a cheap short-circuit -- skip
the delegate call entirely when there is nothing to prune -- kept
deliberately so `test_ev4`'s `.glob(`-present assertion is satisfied by
REAL code rather than by this docstring's own prose, which would
satisfy it vacuously (gate M-V r1, minor 3: the prose alone already
contains the literal `.glob(` four times over, so deleting the code
would NOT redden that check -- the short-circuit is kept for honesty,
not because the assertion requires it). `_event_log_path` stays a pure path computation
with no I/O of its own -- kept because `test_serve.py` still calls it
directly to locate the file the delegate wrote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .. import settings, worker
from ..ledger import resolve_home
from ..sdksession import events as sdk_events
from ..sdksession.events import EventLog, new_run_id

__all__ = ["EventLog", "new_run_id", "prune_event_logs", "write_event_log"]

#: `E-5` -- default retention when `SELF_LEARN_SDK_EVENT_LOGS` is unset.
_DEFAULT_EVENT_LOGS = 20


def _event_log_path(surface: str, run_id: str) -> Path:
    return worker.cache_dir() / f"{surface}.tool-events.{run_id}.jsonl"


def write_event_log(surface: str, run_id: str, *, meta: dict[str, Any], events: EventLog) -> None:
    """`E-3` -- one JSON object per line: a `meta` line first (surface,
    run_id, session_id, cost_usd, turns, failure), then one line per tool
    event, then one per denial. Written ONCE, at the end of the session,
    inside the SAME `finally` that clears the pid sidecar -- so a
    timed-out session still leaves its file. Delegates to
    `sdksession.events.write_event_log` -- see the module docstring's
    Sprint 2 M-V note; `log_kind="tool-events"` reproduces
    `_event_log_path`'s filename byte-for-byte."""
    sdk_events.write_event_log(
        worker.cache_dir(), surface, run_id, log_kind="tool-events", meta=meta, events=events
    )


def prune_event_logs(surface: str) -> None:
    """`E-5` -- keeps the newest `SELF_LEARN_SDK_EVENT_LOGS` (default 20)
    files matching EXACTLY `f"{surface}.tool-events.*.jsonl"` in
    `cache_dir()`, by mtime; unlinks the rest. Matches nothing else --
    not another surface's files, not `worker.log`, not `worker.window`
    (`EV6`'s negative control).

    U-settings Phase 1: resolves through the registry's `sdk.event_logs`
    entry (config.yaml `sdk.event_logs` > env `SELF_LEARN_SDK_EVENT_LOGS`
    > `_DEFAULT_EVENT_LOGS` -- U-flip 2026-09-01, S-58: config wins) --
    signature UNCHANGED (this function's one
    real call site, `invocation_sdk/backend.py`'s `_run_session`, is spy-
    wrapped by `test_ms4_production_retention_runs_exactly_once_and_
    after_the_log_write` with a fixed `(surface)` shim; a new parameter
    there would break that pinned call). `settings` is imported directly
    (module docstring's stdlib-plus-`worker` note updated) rather than
    threading a resolved value through the call site; `resolve_home()`
    supplies the home this function has never taken.

    Sprint 2 M-V: the actual retention walk (sort by mtime, unlink past
    `keep`) delegates to `sdksession.events.prune_event_logs` --
    `log_kind="tool-events"` reproduces the exact same glob pattern and
    therefore the exact same matches, order, and count. The one local
    `cache.glob(pattern)` read below is a short-circuit only (no
    mutation): when there is nothing past `keep` there is nothing to
    unlink, so the delegate call is skipped entirely; behaviourally a
    no-op either way, kept deliberately so `test_ev4_nothing_in_the_
    package_reads_a_tool_events_file` (`test_invocation_sdk.py`)'s
    pinned `.glob(`-present check is satisfied by REAL code here rather
    than by this docstring's own prose -- which, gate M-V r1's minor 3
    mutation (deleting this whole short-circuit) showed, would satisfy
    that check vacuously on its own, since the literal `.glob(` already
    appears four times across this module's docstrings alone."""
    cache = worker.cache_dir()
    keep, _source = settings.resolve_setting(resolve_home(), settings.by_name("sdk.event_logs"))
    keep = cast(int, keep)
    pattern = f"{surface}.tool-events.*.jsonl"
    if len(list(cache.glob(pattern))) <= keep:
        return
    sdk_events.prune_event_logs(cache, surface, log_kind="tool-events", keep=keep)
