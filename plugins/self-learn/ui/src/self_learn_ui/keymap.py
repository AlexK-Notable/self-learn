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
  stream first (09 §2.4); otherwise it is "up a level" like ``a``.
- **Layout is gaming-centric, not vim-centric** (user-directed remap,
  2026-07-17, dated 09 §1/§2 amendment): WASD + arrows navigate
  (``w``/``s`` move, ``d``/``ArrowRight`` open, ``a``/``ArrowLeft``
  back), which evicted the old ``a`` approve / ``d`` deny — now ``e``
  (the games' "use/interact" key) and ``x``. app.js dispatches on the
  FIRST key match with no context filter, so every key must be unique
  across the whole table (tested).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

#: Contexts a key's binding applies in. ``global`` fires everywhere keys
#: are live; the others gate on where focus/attention currently is.
#: Context gates DISPLAY only (footer filtering, style.css) — dispatch is
#: first-match with no context filter, which is why every key is unique.
Context = str  # "global" | "list" | "detail" | "holding" | "pane" | "bucket" | "proposal"


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
    KeymapEntry(("s", "ArrowDown"), "move_down", "Move down", "list"),
    KeymapEntry(("w", "ArrowUp"), "move_up", "Move up", "list"),
    KeymapEntry(("Enter", "d", "ArrowRight"), "drill_in", "Open", "list"),
    KeymapEntry(
        ("Escape", "a", "ArrowLeft"),
        "up",
        "Back / up a level (interrupts the pane first, if focused)",
        "global",
    ),
    KeymapEntry(("e",), "route", "Approve", "detail"),
    KeymapEntry(("x",), "reject", "Deny", "detail"),
    KeymapEntry(("f",), "defer", "Defer", "detail"),
    KeymapEntry(("g",), "graduate", "Graduate", "detail"),
    KeymapEntry(("i",), "iterate", "Iterate (open agent pane)", "detail"),
    KeymapEntry(("o",), "cycle_destination", "Cycle destination", "detail"),
    KeymapEntry(("n",), "note", "Attach / edit note", "detail"),
    # Y-21 (09 §2.3/§11, 2026-07-18): click-or-key disclosure for the
    # miner's episode brief — a native <details>/<summary> element, so the
    # default dispatch (clickAction) needs no app.js special case: a
    # synthesized click on <summary> toggles its <details> natively.
    # `b` was unbound — the global-uniqueness invariant holds (tested).
    # Only renders where a '## Episode brief' section exists (detail-only,
    # and only when the record actually carries one).
    KeymapEntry(("b",), "toggle_brief", "Toggle episode brief", "detail"),
    KeymapEntry(
        ("t",),
        "tolerate",
        "Tolerate (confirm-recurrence --tolerate)",
        "holding",
    ),
    KeymapEntry(("c",), "confirm", "Confirm recurrence", "holding"),
    KeymapEntry(("r",), "retry", "Retry pane", "pane"),
    KeymapEntry(("q",), "close_pane", "Close split (ends the session)", "pane"),
    # Y-13 (09 §1/§2.2/§4.5, 2026-07-17): both keys were unbound — the
    # global-uniqueness invariant holds (tested). `p` only does anything
    # where its button exists (the Bucket page); `y` only where a WAITING
    # proposal bar is rendered — the footer shows each only in context
    # (style.css). Enter NEVER acts on a waiting proposal bar: `y` arms
    # it through the standard armed contract first (two keystrokes, the
    # same consent path as every human-initiated action).
    KeymapEntry(("p",), "bucket_pane", "Open bucket chat pane", "bucket"),
    KeymapEntry(("y",), "arm_proposal", "Review agent proposal (arm)", "proposal"),
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
