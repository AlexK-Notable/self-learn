"""Keymap single-source tests (10 §1 Keymap row; task U1 test bullet 1)."""

from __future__ import annotations

import json

from self_learn_ui.keymap import KEYMAP, keymap_as_dicts, keymap_json

# The pinned action set (10 §1), one per key row named in the row's prose.
EXPECTED_ACTIONS = {
    "move_down",
    "move_up",
    "drill_in",
    "up",
    "route",
    "reject",
    "defer",
    "graduate",
    "iterate",
    "cycle_destination",
    "note",
    "tolerate",
    # F6 fix (2026-07-24, human-ratified): renamed from "confirm" — see
    # keymap.py's KEYMAP entry comment for why.
    "confirm_recurrence",
    "retry",
    "close_pane",
    "bucket_pane",
    "arm_proposal",
    "help",
    "toggle_brief",
    # Resolution-evidence unit (§3.4/§3.6): the success leg's three
    # navigation links.
    "success_next",
    "success_bucket",
    "success_view",
}


def test_keymap_json_is_the_table_serialized() -> None:
    """The JSON blob app.js consumes must BE the table — never a second
    hand-authored list that could drift from it (single-source rule)."""
    assert json.loads(keymap_json()) == keymap_as_dicts()


def test_keymap_covers_every_pinned_action() -> None:
    actions = {entry.action for entry in KEYMAP}
    assert actions == EXPECTED_ACTIONS


def test_every_entry_has_context_and_label() -> None:
    for entry in KEYMAP:
        assert entry.keys, f"{entry.action} has no keys"
        assert entry.label.strip(), f"{entry.action} has an empty label"
        assert entry.context.strip(), f"{entry.action} has an empty context"


def test_no_ctrl_alt_chords() -> None:
    """09 §1: no Ctrl/Alt chords, ever — the browser owns them."""
    for entry in KEYMAP:
        for key in entry.keys:
            assert "ctrl" not in key.lower()
            assert "alt" not in key.lower()
            assert "+" not in key


def test_pinned_key_bindings() -> None:
    """Gaming-centric layout (user-directed remap 2026-07-17; dated
    09 §1/§2 amendment): WASD + arrows navigate; approve/deny moved to
    e/x because navigation evicted a/d."""
    by_action = {entry.action: entry.keys for entry in KEYMAP}
    assert by_action["move_down"] == ("s", "ArrowDown")
    assert by_action["move_up"] == ("w", "ArrowUp")
    assert by_action["drill_in"] == ("Enter", "d", "ArrowRight")
    assert by_action["up"] == ("Escape", "a", "ArrowLeft")
    assert by_action["route"] == ("e",)
    assert by_action["reject"] == ("x",)
    assert by_action["defer"] == ("f",)
    assert by_action["graduate"] == ("g",)
    assert by_action["iterate"] == ("i",)
    assert by_action["cycle_destination"] == ("o",)
    assert by_action["note"] == ("n",)
    assert by_action["tolerate"] == ("t",)
    # F6 fix (2026-07-24, human-ratified): "confirm" -> "confirm_recurrence".
    assert by_action["confirm_recurrence"] == ("c",)
    assert by_action["retry"] == ("r",)
    assert by_action["close_pane"] == ("q",)
    # Y-13 (dated 09 §1 amendment 2026-07-17): both previously unbound.
    # `p` opens the bucket chat pane; `y` arms a WAITING proposal bar
    # (Enter never acts on a waiting bar — y-then-Enter is the pinned
    # two-keystroke consent path).
    assert by_action["bucket_pane"] == ("p",)
    assert by_action["arm_proposal"] == ("y",)
    assert by_action["help"] == ("?",)
    # Y-21 (09 §2.3/§11, 2026-07-18): the episode-brief disclosure toggle.
    assert by_action["toggle_brief"] == ("b",)
    # Resolution-evidence unit (§3.4/§3.6): picked from the spec's own
    # free-key set (h j k l m u v z) — `h` deliberately excluded (see
    # test_success_row_never_claims_h below).
    assert by_action["success_next"] == ("j",)
    assert by_action["success_bucket"] == ("u",)
    assert by_action["success_view"] == ("v",)


def test_success_row_never_claims_h() -> None:
    """§3.6: "`h` is currently printed on the header back-link and bound
    to nothing … Do not claim `h` without fixing that first, or the
    uniqueness test will encode the existing bug." Fixing the header
    back-link is out of scope for this unit (§2.4) — so `h` must stay
    absent from the table entirely, not merely unused by the success
    row specifically."""
    all_keys = {key for entry in KEYMAP for key in entry.keys}
    assert "h" not in all_keys


def test_every_key_is_globally_unique() -> None:
    """app.js dispatches on the FIRST entry whose keys contain the
    pressed key, with no context filter — a duplicate key across any
    two entries would silently shadow the later one."""
    seen: dict[str, str] = {}
    for entry in KEYMAP:
        for key in entry.keys:
            assert key not in seen, (
                f"key {key!r} bound to both {seen[key]} and {entry.action}"
            )
            seen[key] = entry.action


def test_holding_row_keys_are_t_and_c() -> None:
    """t/c live on the 'is it holding?' row context (09 §11 Y-4).
    F6 fix (2026-07-24, human-ratified): the `c` action is now named
    "confirm_recurrence", not "confirm" — same key, corrected name."""
    holding = {entry.action for entry in KEYMAP if entry.context == "holding"}
    assert holding == {"tolerate", "confirm_recurrence"}


def test_success_row_actions() -> None:
    """The resolution-evidence unit's success leg row (§3.4/§3.6)."""
    success = {entry.action for entry in KEYMAP if entry.context == "success"}
    assert success == {"success_next", "success_bucket", "success_view"}
