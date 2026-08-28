"""11 §3 adjudication-plane schema fields: capture-time grounding
(verified / incident_cost / generality / env), follow-ups, recurrences,
last_confirmed, contradiction edges.

All optional (existing records stay valid), all metadata class — mutable
in every status, substance freeze untouched (S-8/S-12).
"""

import pytest

from self_learn.records import (
    MutationError,
    Record,
    ValidationError,
)
from support import make_behavior


def routed(record: Record) -> Record:
    record.set_routing(
        {"routed_at": "2026-07-15T00:00:00Z", "destination": "skill-md", "by": "human"}
    )
    record.set_status("routed")
    return record


# ------------------------------------------------- capture-time grounding


def test_capture_time_fields_round_trip():
    r = make_behavior()
    r.set_verified(True, how="repro'd twice on this host")
    r.set_incident_cost("an evening")
    r.set_generality("environment-specific")
    r.set_env({"swaync": "0.10.2", "model": "claude-fable-5"})
    reparsed = Record.from_text(r.to_text())
    assert reparsed.verified is True
    assert reparsed.verified_how == "repro'd twice on this host"
    assert reparsed.incident_cost == "an evening"
    assert reparsed.generality == "environment-specific"
    assert reparsed.env == {"swaync": "0.10.2", "model": "claude-fable-5"}


def test_generality_enum_enforced():
    r = make_behavior()
    with pytest.raises(ValidationError, match="generality"):
        r.set_generality("sometimes")


def test_verified_how_needs_verified():
    r = make_behavior()
    with pytest.raises(ValidationError, match="verified"):
        r.set_verified(None, how="orphan how")
    text = r.to_text().replace("status: pending", "status: pending\nverified_how: x")
    with pytest.raises(ValidationError, match="verified_how needs a verified value"):
        Record.from_text(text)


def test_env_values_must_be_scalars():
    r = make_behavior()
    with pytest.raises(ValidationError, match="env values"):
        r.set_env({"swaync": {"version": "0.10.2"}})


def test_metadata_fields_mutable_after_routing():
    r = routed(make_behavior())
    r.set_verified(True)  # metadata class: no freeze
    r.set_generality("general-practice")
    assert r.verified is True


def test_existing_records_without_new_fields_stay_valid():
    r = make_behavior()
    assert r.verified is None
    assert r.follow_up is None
    assert r.recurrences == ()
    assert r.contradicts == ()
    Record.from_text(r.to_text())  # validates


# ------------------------------------------------------------- follow-ups


def test_follow_up_rides_routing_block():
    r = routed(make_behavior())
    r.set_follow_up("upgrade-to-hook", unblocks_on="M3", note="advisory is the weak form")
    reparsed = Record.from_text(r.to_text())
    assert reparsed.follow_up == {
        "action": "upgrade-to-hook",
        "unblocks_on": "M3",
        "note": "advisory is the weak form",
    }
    # status stays terminal — no new lifecycle status (11 §2.1)
    assert reparsed.status == "routed"


def test_follow_up_needs_routing():
    r = make_behavior()
    with pytest.raises(MutationError, match="route first"):
        r.set_follow_up("upgrade-to-hook")


def test_complete_follow_up_moves_to_dated_done_block():
    r = routed(make_behavior())
    r.set_follow_up("upgrade-to-hook", unblocks_on="M3")
    r.complete_follow_up(done_at="2026-08-01", done_note="hook landed")
    assert r.follow_up is None
    done = r.follow_up_done
    assert done["action"] == "upgrade-to-hook"
    assert done["done_at"] == "2026-08-01"
    assert done["done_note"] == "hook landed"
    Record.from_text(r.to_text())  # validates


def test_complete_follow_up_without_open_one_refuses():
    r = routed(make_behavior())
    with pytest.raises(MutationError, match="no open follow-up"):
        r.complete_follow_up()


def test_follow_up_needs_action():
    r = routed(make_behavior())
    with pytest.raises(ValidationError, match="action"):
        r.set_follow_up("   ")


def test_set_routing_validates_follow_up_shape():
    r = make_behavior()
    with pytest.raises(ValidationError, match="action"):
        r.set_routing(
            {
                "routed_at": "2026-07-15T00:00:00Z",
                "destination": "skill-md",
                "by": "human",
                "follow_up": {"unblocks_on": "M3"},
            }
        )


# ------------------------------------------- recurrences / last_confirmed


def test_recurrences_append_only_with_minimal_facts():
    r = routed(make_behavior())
    r.append_recurrence(
        {"ts": "2026-08-02T10:00:00Z", "origin": "lrn-0000cccc", "ref": "2026-08.host"}
    )
    assert len(r.recurrences) == 1
    with pytest.raises(ValidationError, match="origin"):
        r.append_recurrence({"ts": "2026-08-03T10:00:00Z"})
    Record.from_text(r.to_text())


def test_last_confirmed_round_trips():
    r = routed(make_behavior())
    r.set_last_confirmed("2026-08-02")
    assert str(Record.from_text(r.to_text()).last_confirmed) == "2026-08-02"


# ------------------------------------------------------------ contradicts


def test_contradicts_edges_append_and_dedupe():
    r = make_behavior()
    r.append_contradicts("lrn-889241d9")
    r.append_contradicts("dotfiles/SKILL.md#cd-rule")
    assert r.contradicts == ("lrn-889241d9", "dotfiles/SKILL.md#cd-rule")
    with pytest.raises(ValidationError, match="already contradicts"):
        r.append_contradicts("lrn-889241d9")
    Record.from_text(r.to_text())


def test_contradicts_rejects_empty_target():
    r = make_behavior()
    with pytest.raises(ValidationError, match="non-empty"):
        r.append_contradicts("  ")
