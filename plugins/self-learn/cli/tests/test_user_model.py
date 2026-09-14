"""U2 · The model of the user (`02-schema.md` §3a.4, S-65).

Mutation checks pinned here (each recorded red-then-green in the U2
report): (g) `mark_seen` flips the stored flag and nothing else, and a
`presented` observation with `entries: []` flips nothing; (h)
`lapse_entry` refuses without a named changed condition, and no code
path here lapses on age.
"""

from __future__ import annotations

import inspect
import re

import pytest

from self_learn import user_model
from support import make_home


def test_add_entry_creates_container_a_own_words(tmp_path):
    home = make_home(tmp_path)
    entry_id = user_model.add_entry(
        home, container="A", title="cost-sensitivity was a symptom",
        because='(the user\'s words) "cost-sensitivity was a symptom"',
        source="own-words", by="steward", ref="stmt-2b7e91c0",
        recorded_by="steward",
    )
    assert user_model.UM_ID_RE.match(entry_id)
    doc = user_model.show(home)
    entry = next(e for e in doc["containers"]["A"] if e["id"] == entry_id)
    assert entry["status"] == "CURRENT"
    assert entry["r"] == 1
    assert "provisional" not in entry
    assert doc["frontmatter"]["revision"] == 1


def test_add_entry_container_b_refuses_direct_add(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="B", title="x", because="y",
            source="system-reading", by="steward", ref="case-x",
            statements=["stmt-11112222"],
        )


def test_add_entry_container_d_only_overseer(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="D", title="x", because="y",
            source="system-reading", by="steward", ref="telemetry:e1",
        )
    entry_id = user_model.add_entry(
        home, container="D", title="x", because="y",
        source="system-reading", by="overseer", ref="telemetry:e1",
    )
    assert user_model.UM_ID_RE.match(entry_id)


def test_add_entry_container_c_needs_a_statement_id(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="C", title="x", because="y",
            source="system-reading", by="steward", ref="case-x",
            statements=[],
        )


def test_add_entry_refuses_forbidden_vocabulary(tmp_path):
    home = make_home(tmp_path)
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="A", title="the user ratified this",
            because="because text", source="own-words", by="human",
            ref="stmt-11112222",
        )
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="A", title="ok title",
            because="the user stated this in passing",
            source="own-words", by="human", ref="stmt-11112222",
        )


def test_add_entry_secret_scan_refuses(tmp_path):
    home = make_home(tmp_path)
    token = "ghp_" + "Ab1" * 12
    with pytest.raises(user_model.UserModelError):
        user_model.add_entry(
            home, container="A", title="ok",
            because=f"the token is {token}",
            source="own-words", by="human", ref="stmt-11112222",
        )


# ------------------------------------------------------------- (g) mark_seen


def _seed_provisional_entry(home, *, container="C") -> str:
    return user_model.add_entry(
        home, container=container, title="load cost dominates",
        because="the pipeline was misrouting lessons",
        source="system-reading", by="steward",
        conditions=["report.destinations"], ref="case-00000000",
        statements=["stmt-11112222"],
    )


def test_g_mark_seen_flips_only_provisional_and_moves_c_to_b(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    before = next(
        e for e in user_model.show(home)["containers"]["C"] if e["id"] == entry_id
    )

    user_model.mark_seen(home, entry_id)

    doc = user_model.show(home)
    assert not any(e["id"] == entry_id for e in doc["containers"]["C"])
    after = next(e for e in doc["containers"]["B"] if e["id"] == entry_id)
    assert after["provisional"] is False
    assert after["r"] == before["r"], "mark_seen must never bump r (it is not a dependency move)"
    for key in ("held_since", "because", "conditions", "status", "source", "ref", "statements"):
        assert after[key] == before[key], f"mark_seen changed {key!r} — it must change nothing but provisional"


def test_g_mark_seen_is_idempotent_on_an_already_seen_entry(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    user_model.mark_seen(home, entry_id)
    rev_after_first = user_model.show(home)["frontmatter"]["revision"]
    user_model.mark_seen(home, entry_id)  # no-op, must not error
    doc = user_model.show(home)
    after = next(e for e in doc["containers"]["B"] if e["id"] == entry_id)
    assert after["provisional"] is False
    assert doc["frontmatter"]["revision"] >= rev_after_first


def test_g_mark_seen_refuses_an_own_words_entry(tmp_path):
    home = make_home(tmp_path)
    entry_id = user_model.add_entry(
        home, container="A", title="own words entry", because="because text",
        source="own-words", by="human", ref="stmt-11112222",
    )
    with pytest.raises(user_model.UserModelError):
        user_model.mark_seen(home, entry_id)


def test_g_presented_observation_with_no_entries_flips_nothing(tmp_path):
    """The `cases.observe(kind="presented", entries=[])` half of check
    (g) is exercised end to end in `test_cases.py`
    (`test_observe_presented_with_no_entries_flips_nothing`) — this file
    only owns `user_model.mark_seen` itself, called directly, never with
    an empty list (there is nothing to call it WITH when entries is
    empty; `cases.observe`'s loop over `entries` simply does not run)."""
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    # No call to mark_seen at all — the entry must be exactly as seeded.
    doc = user_model.show(home)
    still_there = next(e for e in doc["containers"]["C"] if e["id"] == entry_id)
    assert still_there["provisional"] is True


# ----------------------------------------------------------- (h) lapse_entry


def test_h_lapse_entry_refuses_without_a_named_cause(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    with pytest.raises(user_model.UserModelUsageError):
        user_model.lapse_entry(home, entry_id, by="steward")


def test_h_lapse_entry_with_changed_condition_succeeds(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    before = next(
        e for e in user_model.show(home)["containers"]["C"] if e["id"] == entry_id
    )
    user_model.lapse_entry(
        home, entry_id, changed_condition="report.destinations", by="steward",
        at="2026-09-20",
    )
    doc = user_model.show(home)
    after = next(e for e in doc["containers"]["C"] if e["id"] == entry_id)
    assert after["status"] == "LAPSED"
    assert after["lapsed_at"] == "2026-09-20"
    assert after["changed_condition"] == "report.destinations"
    assert after["r"] == before["r"] + 1, "lapse IS a substantive status change — it bumps r, unlike mark_seen"

    with pytest.raises(user_model.UserModelError):
        user_model.lapse_entry(home, entry_id, changed_condition="x", by="steward")


def test_h_lapse_entry_accepts_exactly_one_of_the_three_causes(tmp_path):
    home = make_home(tmp_path)
    entry_id = _seed_provisional_entry(home)
    with pytest.raises(user_model.UserModelUsageError):
        user_model.lapse_entry(
            home, entry_id, changed_condition="a", contrary="b", by="steward",
        )


def test_h_no_time_based_lapse_anywhere_in_this_module():
    """D6 / seam-reconciliation addendum: "nothing lapses for silence"
    — grep proof, quoted in the U2 report: this module imports and uses
    neither `days` nor `timedelta`."""
    src = inspect.getsource(user_model)
    assert not re.search(r"\bdays\b", src), src
    assert not re.search(r"\btimedelta\b", src), src
