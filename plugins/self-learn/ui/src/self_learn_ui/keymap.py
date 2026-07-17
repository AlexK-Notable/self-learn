"""The single-source keymap table (10 §1's "Keymap (single source)" row).

Rendered from this ONE table into three places — never duplicated: the
footer partial, the ``?`` help overlay, and the JSON blob ``app.js``
consumes for its keydown handler (both template wiring landing at U3; this
module is the source of truth + the JSON renderer).

Mechanics pinned alongside the table (09 §1, not per-key data, so recorded
here as documentation rather than a field):

- **Arm-then-confirm**: a resolution key ARMS the action bar; ``Enter``
  EXECUTES the armed action; any other key DISARMS. No modal confirm.
- Keys are inert while focus is in a text input (09 §1).
- **No Ctrl/Alt chords, ever** — the browser owns them.
- ``Esc`` is context-sensitive: with the pane focused it interrupts the
  stream first (09 §2.4); otherwise it is "up a level" like ``h``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

#: Contexts a key's binding applies in. ``global`` fires everywhere keys
#: are live; the others gate on where focus/attention currently is.
Context = str  # "global" | "list" | "detail" | "holding" | "pane"


@dataclass(frozen=True)
class KeymapEntry:
    """One row of the keymap table.

    ``keys`` — the literal key(s) that trigger ``action`` (e.g. both
    ``j`` and ``ArrowDown`` map to the same ``move_down`` action).
    ``action`` — a stable machine name app.js switches on.
    ``label`` — the human-readable string rendered in the footer/overlay.
    ``context`` — where this binding is live (see :data:`Context`).
    """

    keys: tuple[str, ...]
    action: str
    label: str
    context: Context


#: The one source of truth (10 §1). Order is display order in the footer
#: and help overlay.
KEYMAP: tuple[KeymapEntry, ...] = (
    KeymapEntry(("j", "ArrowDown"), "move_down", "Move down", "list"),
    KeymapEntry(("k", "ArrowUp"), "move_up", "Move up", "list"),
    KeymapEntry(("Enter", "l"), "drill_in", "Open", "list"),
    KeymapEntry(
        ("Escape", "h"),
        "up",
        "Back / up a level (interrupts the pane first, if focused)",
        "global",
    ),
    KeymapEntry(("a",), "route", "Approve", "detail"),
    KeymapEntry(("d",), "reject", "Deny", "detail"),
    KeymapEntry(("f",), "defer", "Defer", "detail"),
    KeymapEntry(("g",), "graduate", "Graduate", "detail"),
    KeymapEntry(("i",), "iterate", "Iterate (open agent pane)", "detail"),
    KeymapEntry(("o",), "cycle_destination", "Cycle destination", "detail"),
    KeymapEntry(("n",), "note", "Attach / edit note", "detail"),
    KeymapEntry(
        ("t",),
        "tolerate",
        "Tolerate (confirm-recurrence --tolerate)",
        "holding",
    ),
    KeymapEntry(("c",), "confirm", "Confirm recurrence", "holding"),
    KeymapEntry(("r",), "retry", "Retry pane", "pane"),
    KeymapEntry(("q",), "close_pane", "Close split (ends the session)", "pane"),
    KeymapEntry(("?",), "help", "Help overlay", "global"),
)


def keymap_as_dicts() -> list[dict]:
    """The table as plain dicts (JSON-serializable), display order preserved."""
    return [
        {**asdict(entry), "keys": list(entry.keys)} for entry in KEYMAP
    ]


def keymap_json() -> str:
    """The table rendered as a JSON blob — what ``app.js`` consumes.

    One source of truth: this is a pure function of :data:`KEYMAP`, never
    a second hand-authored list.
    """
    return json.dumps(keymap_as_dicts())
