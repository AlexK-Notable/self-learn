"""U-sdk §3.8 `Ev-1` — capture: `EventLog`, the JSONL sink, retention.

The ONLY other module in this unit that writes a file (`lifecycle.py`'s
pid sidecar is the other -- `E-6`). Import-bounded to stdlib plus
`.. import worker` (the module object, `I-d`) -- `worker.cache_dir()` at
call time.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import worker

__all__ = ["EventLog", "new_run_id", "prune_event_logs", "write_event_log"]

#: `E-5` -- default retention when `SELF_LEARN_SDK_EVENT_LOGS` is unset.
_DEFAULT_EVENT_LOGS = 20


@dataclass
class EventLog:
    """Mutable per-session accumulator (`E-2`) -- appended to live by the
    message drain (tool events) and by `backend.py`'s wrapper around the
    charter callback (denials, `C-9`)."""

    tool_events: list[dict[str, Any]] = field(default_factory=list)
    denials: list[dict[str, Any]] = field(default_factory=list)

    def add_denial(self, tool_name: str, reason: str) -> None:
        self.denials.append({"source": "charter", "tool": tool_name, "reason": reason})

    def add_sdk_permission_denial(self, denial: Any) -> None:
        """`E-2` -- kept SEPARATE from `add_denial`'s charter-sourced
        entries: a denial the SDK recorded but the charter callback never
        saw (e.g. a structurally-disallowed tool) appears only here."""
        self.denials.append({"source": "sdk-result", "value": denial})

    def add_tool_use(self, block_id: str, name: str, tool_input: dict[str, Any]) -> None:
        self.tool_events.append(
            {"kind": "tool_use", "id": block_id, "name": name, "input": tool_input}
        )

    def add_tool_result(self, tool_use_id: str, is_error: bool, content: Any) -> None:
        self.tool_events.append(
            {
                "kind": "tool_result",
                "tool_use_id": tool_use_id,
                "is_error": is_error,
                "content": content,
            }
        )


def new_run_id() -> str:
    """`E-3` -- assigned at session START (never the session id, which
    arrives only with `ResultMessage` and a timed-out/crashed session
    never produces one)."""
    return f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"


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
