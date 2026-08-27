"""U-engine sdksession -- events.py (spec section 4.2): EventLog, run ids,
the JSONL sink, retention.

F-1 (section 4.6, MS2): new_run_id() stays a zero-argument function --
its collision-free component is a per-process MONOTONIC COUNTER, folded
into the SAME digit run the pid already occupies (pid * 10**9 + seq)
rather than appended as a second dash-separated segment, because
test_ev3_... (armor-pinned test_invocation_sdk.py) asserts the id's
shape with a regex requiring 8 digits, "T", 6 digits, "Z", "-", then
ONLY digits to the end of the string. A monotonic counter is chosen
over a uuid4().hex[:8] suffix for exactly this reason: a hex suffix can
contain a-f, which is not a digit, and would have forced test_ev3 into
the seven-file re-pin the design (C-1's spirit) otherwise avoids
entirely. The counter alone (ignoring the pid and timestamp components)
already proves MS2: it strictly increases on every call in this
process, regardless of surface.

F-3 (section 4.6, MS4): retention is prune_event_logs, generalised to
take live_run_ids -- a file whose run id is in that set is never
unlinked, however it ranks by mtime. The CALLER decides what "live"
means (the CLI's own invocation_sdk/events.py wrapper tracks its own
single in-flight run id; a future multi-session caller tracks more).

Every path-touching function takes `cache_dir: Path` AND `log_kind: str`
as PARAMETERS -- never `worker.cache_dir()` (LIB1/section 4.3), and
never the CLI's own event-log filename middle segment as a literal.
The latter is a DELIBERATE, armor-driven choice, not a style
preference: `test_worker_contract.py::
test_ev4_tool_events_string_confined_to_events_module` (armor-pinned,
whole-file sha-checked) recursively scans EVERY `.py` file under
`src/self_learn/` and asserts that literal substring appears ONLY in
`invocation_sdk/events.py` (unrestricted) and exactly once in
`worker.py` (the pinned FW-107 log line) -- this package is outside
both exemptions, so its own source may never spell that literal out.
`invocation_sdk/events.py` keeps its own, fully self-contained
`write_event_log`/`prune_event_logs` for exactly this reason too (see
that module's docstring); this module's generalised versions exist for
the OTHER two consumers and for direct library-level testing
(`MS2`/`MS4`), with the caller supplying its own filename convention.

Import-bounded: stdlib only.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_EVENT_LOGS",
    "EventLog",
    "event_log_path",
    "new_run_id",
    "prune_event_logs",
    "write_event_log",
]

#: `E-5` -- default retention when the caller has no override.
DEFAULT_EVENT_LOGS = 20


@dataclass
class EventLog:
    """Mutable per-session accumulator (`E-2`) -- appended to live by
    the message drain (tool events) and by the containment-callback
    adapter (denials, `C-9`)."""

    tool_events: list[dict[str, Any]] = field(default_factory=list)
    denials: list[dict[str, Any]] = field(default_factory=list)

    def add_denial(self, tool_name: str, reason: str) -> None:
        self.denials.append({"source": "charter", "tool": tool_name, "reason": reason})

    def add_sdk_permission_denial(self, denial: Any) -> None:
        """Kept SEPARATE from `add_denial`'s charter-sourced entries: a
        denial the SDK recorded but the charter callback never saw
        appears only here."""
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


_run_id_lock = threading.Lock()
_run_id_counter = itertools.count()


def new_run_id() -> str:
    """`E-3`/`F-1`/`MS2` -- assigned at session START. Collision-free
    regardless of surface: `seq` strictly increases on every call in
    this process."""
    with _run_id_lock:
        seq = next(_run_id_counter)
    combined = os.getpid() * 1_000_000_000 + seq
    return f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{combined}"


def event_log_path(cache_dir: Path, surface: str, run_id: str, *, log_kind: str) -> Path:
    """`log_kind` is the filename's middle segment (the CLI's own
    caller supplies its own convention -- see the module docstring)."""
    return cache_dir / f"{surface}.{log_kind}.{run_id}.jsonl"


def write_event_log(
    cache_dir: Path,
    surface: str,
    run_id: str,
    *,
    log_kind: str,
    meta: dict[str, Any],
    events: EventLog,
) -> None:
    """`E-3` -- one JSON object per line: a `meta` line first, then one
    line per tool event, then one per denial. Written ONCE, at the end
    of the session, inside the SAME `finally` that clears the pid
    sidecar -- so a timed-out session still leaves its file."""
    path = event_log_path(cache_dir, surface, run_id, log_kind=log_kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "meta", **meta}, default=str)]
    for event in events.tool_events:
        lines.append(json.dumps({"type": "tool_event", **event}, default=str))
    for denial in events.denials:
        lines.append(json.dumps({"type": "denial", **denial}, default=str))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_id_of(path: Path, surface: str, log_kind: str) -> str:
    prefix = f"{surface}.{log_kind}."
    return path.name[len(prefix) : -len(".jsonl")]


def prune_event_logs(
    cache_dir: Path,
    surface: str,
    *,
    log_kind: str,
    keep: int = DEFAULT_EVENT_LOGS,
    live_run_ids: frozenset[str] = frozenset(),
) -> None:
    """`E-5`/`F-3` -- keeps the newest `keep` files matching EXACTLY
    `f"{surface}.{log_kind}.*.jsonl"` in `cache_dir`, by mtime; unlinks
    the rest. Matches nothing else -- not another surface's files, not
    an unrelated log.

    `F-3`/`MS4`: a file whose run id is in `live_run_ids` is NEVER
    unlinked, regardless of its mtime rank -- a starting session must
    not unlink another session's in-flight log."""
    keep = max(keep, 0)
    pattern = f"{surface}.{log_kind}.*.jsonl"
    matches = sorted(cache_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    kept = 0
    for path in matches:
        if _run_id_of(path, surface, log_kind) in live_run_ids:
            continue
        if kept < keep:
            kept += 1
            continue
        path.unlink(missing_ok=True)
