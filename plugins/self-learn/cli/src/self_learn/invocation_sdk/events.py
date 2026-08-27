"""U-sdk §3.8 `Ev-1` — capture: `EventLog`, the JSONL sink, retention.

The ONLY other module in this unit that writes a file (`lifecycle.py`'s
pid sidecar is the other -- `E-6`). Import-bounded to stdlib plus
`.. import worker` (the module object, `I-d`) -- `worker.cache_dir()` at
call time.

**U-engine (§4.2/§4.6 `F-1`):** `EventLog` and `new_run_id` now delegate
to `self_learn.sdksession.events` verbatim -- neither has any file I/O
of its own, so delegating them does not touch
`test_pl3_filesystem_writes_are_enumerated_with_an_exact_count`'s
armor-pinned count (it counts `write_text`/`unlink`/`mkdir` call SITES,
and this module's own `write_event_log`/`prune_event_logs` keep theirs,
unchanged, for the same reason `lifecycle.py`'s sidecar functions do --
see that module's docstring). `new_run_id()`'s collision-free component
(`MS2`) is therefore live on THIS production path, not just proven in
the library.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import worker
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
    timed-out session still leaves its file."""
    path = _event_log_path(surface, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "meta", **meta}, default=str)]
    for event in events.tool_events:
        lines.append(json.dumps({"type": "tool_event", **event}, default=str))
    for denial in events.denials:
        lines.append(json.dumps({"type": "denial", **denial}, default=str))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prune_event_logs(surface: str) -> None:
    """`E-5` -- keeps the newest `SELF_LEARN_SDK_EVENT_LOGS` (default 20)
    files matching EXACTLY `f"{surface}.tool-events.*.jsonl"` in
    `cache_dir()`, by mtime; unlinks the rest. Matches nothing else --
    not another surface's files, not `worker.log`, not `worker.window`
    (`EV6`'s negative control)."""
    cache = worker.cache_dir()
    keep_raw = os.environ.get("SELF_LEARN_SDK_EVENT_LOGS")
    try:
        keep = int(keep_raw) if keep_raw else _DEFAULT_EVENT_LOGS
    except ValueError:
        keep = _DEFAULT_EVENT_LOGS
    keep = max(keep, 0)
    pattern = f"{surface}.tool-events.*.jsonl"
    matches = sorted(cache.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in matches[keep:]:
        stale.unlink(missing_ok=True)
