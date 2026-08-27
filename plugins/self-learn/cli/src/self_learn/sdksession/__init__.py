"""`sdksession` — the shared SDK session library (spec §4). Owns one SDK
session end to end: connect, drive, tear down, capture, and the
mechanics of multi-session hygiene. Policy (both charters, both message
tables, both option assemblies beyond the floor) stays with its client
-- this package takes policy as an object (`policy.SessionPolicy`) and
never contains any (§4.3).

**Portable, by the four things that word is allowed to mean here
(§4.5):** stdlib plus `claude_agent_sdk` only (this package itself
imports neither `claude_agent_sdk` nor any `self_learn.*`/
`self_learn_ui.*` module -- `LIB1`); no dependency beyond
`claude-agent-sdk`; a fake (`fake.FakeSdkClient`) ships so the whole
package is testable with the real SDK absent (`LIB3`); and an API sized
for exactly three consumers (the pane, the seam, the host process) --
no sweep-all, no kill-all, no generic middleware (`MS7`, `HOST3`).

Re-exports only -- this module is the package's public surface.
"""

from __future__ import annotations

from .children import child_pid_of, sweep_orphans, write_sidecar
from .events import EventLog, new_run_id, prune_event_logs, write_event_log
from .fake import FakeSdkClient
from .ladder import INTERRUPT_GRACE_SECS, KILL_SECS
from .policy import ShutdownMessages, SessionPolicy, wrap_can_use_tool
from .result import reduce_result_error
from .session import SdkSession
from .teardown import ABANDONED_DISCONNECTS, run_kill_ladder
from .toolpaths import TARGET_PATH_KEYS, extract_target_path

__all__ = [
    "ABANDONED_DISCONNECTS",
    "EventLog",
    "FakeSdkClient",
    "INTERRUPT_GRACE_SECS",
    "KILL_SECS",
    "SdkSession",
    "SessionPolicy",
    "ShutdownMessages",
    "TARGET_PATH_KEYS",
    "child_pid_of",
    "extract_target_path",
    "new_run_id",
    "prune_event_logs",
    "reduce_result_error",
    "run_kill_ladder",
    "sweep_orphans",
    "wrap_can_use_tool",
    "write_event_log",
    "write_sidecar",
]
