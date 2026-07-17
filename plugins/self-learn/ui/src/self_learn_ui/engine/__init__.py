"""The adjudication pane engine (10 §1's "Engine event protocol" +
"Pane sdk engine construction" rows; 09 §4). Public surface:

- :mod:`.base` — the ``PaneEngine`` seam, ``PaneEvent`` vocabulary,
  ``PaneContext``, and ``FakeEngine`` for downstream UI tests.
- :mod:`.sdk` — ``SdkPaneEngine``, the default (and only built) engine.
- :mod:`.charter` — the ``can_use_tool`` permission-surface builder.

Downstream code should import from this package's re-exports, not reach
into the submodules directly, so the seam stays the only contract UI code
depends on (09 §4.1: "the UI renders events; it never reaches around the
engine to the transport").
"""

from __future__ import annotations

from .base import (
    BlockStart,
    FakeEngine,
    FileChanged,
    PaneContext,
    PaneEngine,
    PaneEvent,
    Result,
    TextDelta,
    ToolUse,
)
from .charter import CanonReadRootsUnavailable, build_can_use_tool
from .sdk import SdkPaneEngine

__all__ = [
    "BlockStart",
    "CanonReadRootsUnavailable",
    "FakeEngine",
    "FileChanged",
    "PaneContext",
    "PaneEngine",
    "PaneEvent",
    "Result",
    "SdkPaneEngine",
    "TextDelta",
    "ToolUse",
    "build_can_use_tool",
]
