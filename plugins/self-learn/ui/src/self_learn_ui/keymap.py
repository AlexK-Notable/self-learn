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
Context = str  # "global" | "list" | "detail" | "holding" | "pane" | "bucket" | "proposal" | "success"


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
    # F6 fix (2026-07-24, human-ratified R-6/§5.5): renamed from
    # "confirm" — that name collided with the GENERIC arm-then-confirm
    # `data-key-action="confirm"` button rendered at THREE other sites
    # (action_bar.html's armed block, proposal_bar.html, host_add_bar.html)
    # — host_add_bar.html is included by BOTH bucket.html and
    # detail.html, so a holding Detail page with an unregistered host
    # could co-render two identical targets, and clickAction's
    # querySelector would resolve by document order (ambiguous). The `c`
    # key was consequently dead against its own button
    # (action_bar.html's holding block already carries
    # data-key-action="confirm_recurrence" — the template side was never
    # the bug). Renaming the KEYMAP action leaves every existing target
    # unambiguous. Three tests in test_keymap.py pinned the old name and
    # were updated under this same authority — see 03-decisions.md's
    # S-row.
    KeymapEntry(("c",), "confirm_recurrence", "Confirm recurrence", "holding"),
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
    # Resolution-evidence unit (§3.4/§3.6, spec §4 "Success-leg
    # bindings"): the three navigation links on the success leg
    # (evidence.html) — genuinely new actions, genuinely new keys,
    # never reusing `confirm`/`disarm` (keymap.py:88-102 above records
    # exactly that reuse-a-generic-action class of defect: the `c`
    # failure was a DUPLICATE `data-key-action`, not a missing entry).
    # Picked from the free-key set named in the spec (`h j k l m u v
    # z`) — `h` deliberately excluded: it is already printed on the
    # header back-link and bound to nothing (ui-walks.md W2-F1), and
    # claiming it here would encode that pre-existing defect into a
    # uniqueness test rather than fixing it (out of scope for this
    # unit — §2.4). The success leg is DOM-presence-scoped like every
    # other leg here — no context filter (§3.6): it only exists in the
    # document while a `[data-verb-success]` element is rendered.
    KeymapEntry(("j",), "success_next", "Next pending record", "success"),
    KeymapEntry(("u",), "success_bucket", "Back to the bucket", "success"),
    KeymapEntry(("v",), "success_view", "View the record", "success"),
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
