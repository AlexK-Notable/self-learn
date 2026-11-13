"""S-148 (2026-11-12): what the user writes by hand, read against placed lessons.

The overseer's census of 2026-11-08 traced five hand edits of lessons in one
week to one gap: the user adds a rule to their own instruction file and
nothing re-reads the placed lessons it now covers. Pinned here:

* `canon_watch.hand_text` leaves out what self-learn manages;
* `observe`: the first look only takes snapshots; later, lines a file gained
  are one change (kept in the cache, deduplicated, forgotten after its
  window); a moved line is not a change; a new rules file is;
* `similar`: a lesson that shares its uncommon words with a change is
  named, an unrelated one is not;
* the sweep derives a failing `@canon` for a resembling placed lesson, with
  the change's hash as its value, and none on the first look;
* the steward's brief shows what the user wrote and how to decide;
* the trailing colon a lesson's trigger may carry is not rendered twice.

Synthetic ids and texts; no model call; no real `~/.claude`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import canon_watch, compilers, premise_sweep, premises, steward_inputs
from self_learn.ledger import Bucket
from self_learn.records import Record

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
RULE = (
    "Before adding any review, second opinion, mutation run or extra test layer, weigh what "
    "it costs in agent-hours against what it would catch, and default to no extra layer."
)
LESSON = (
    "## Trigger\nAbout to add a review, a second opinion or a mutation run to finished work.\n\n"
    "## Instruction\nWeigh what the extra layer costs in agent-hours against what it would "
    "catch, and default to no extra layer unless it is cheap.\n"
)
OTHER = (
    "## Fact\nThe printer firmware caps process names at fifteen visible characters, so an "
    "exact match on a longer name never succeeds.\n"
)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")


def _claude(tmp_path: Path, body: str) -> Path:
    claude = tmp_path / "claude"
    claude.mkdir(exist_ok=True)
    (claude / "CLAUDE.md").write_text(
        "# Mine\n\n" + body + "\n\n" + compilers.BEGIN_MARKER + "\n- a managed line that says "
        "review and mutation and agent-hours *(lrn-c0000009)*\n" + compilers.END_MARKER + "\n",
        encoding="utf-8",
    )
    return claude


def test_hand_text_leaves_out_what_self_learn_manages(tmp_path):
    claude = _claude(tmp_path, "My own rule about proportion and effort.")
    hand = canon_watch.hand_text((claude / "CLAUDE.md").read_text())
    assert "My own rule" in hand and "lrn-c0000009" not in hand and "self-learn:begin" not in hand
    # an unclosed block hides the rest: a damaged file is never the user's words
    assert "after" not in canon_watch.hand_text(compilers.BEGIN_MARKER + "\nx\nafter\n")


def test_the_first_look_takes_snapshots_and_a_later_gain_is_one_change(tmp_path):
    cache = tmp_path / "cache"
    claude = _claude(tmp_path, "An older line of mine that stays where it is today.")
    assert canon_watch.observe(cache, claude, now=NOW) == []
    assert canon_watch.observe(cache, claude, now=NOW) == []  # nothing changed
    _claude(tmp_path, "An older line of mine that stays where it is today.\n\n" + RULE)
    (change,) = canon_watch.observe(cache, claude, now=NOW + timedelta(days=1))
    assert change.text == RULE and change.path.endswith("CLAUDE.md")
    assert canon_watch.change_by_sha(cache, change.sha) == change
    # seen again the next day: the same one change, not a second
    assert canon_watch.observe(cache, claude, now=NOW + timedelta(days=2)) == [change]
    # moving the old line is not a change; nor is a short heading
    _claude(tmp_path, RULE + "\n\n## A heading\n\nAn older line of mine that stays where it is today.")
    assert canon_watch.observe(cache, claude, now=NOW + timedelta(days=3)) == [change]
    # forgotten after its window
    late = NOW + timedelta(days=2 + canon_watch.ACTIVE_DAYS)
    assert canon_watch.observe(cache, claude, now=late) == []


def test_a_new_rules_file_after_the_first_look_is_a_change(tmp_path):
    cache = tmp_path / "cache"
    claude = _claude(tmp_path, "An older line of mine that stays where it is today.")
    canon_watch.observe(cache, claude, now=NOW)
    (claude / "rules").mkdir()
    (claude / "rules" / "proportion.md").write_text(RULE + "\n", encoding="utf-8")
    (change,) = canon_watch.observe(cache, claude, now=NOW + timedelta(days=1))
    assert change.path.endswith("proportion.md")


def test_similar_names_the_lesson_that_shares_its_words_and_not_the_other():
    lessons = {"lrn-c0000001": LESSON, "lrn-c0000002": OTHER}
    rows = canon_watch.similar(RULE, lessons)
    assert [rid for rid, _score, _shared in rows] == ["lrn-c0000001"]
    assert rows[0][1] >= canon_watch.MIN_SCORE and rows[0][2] >= canon_watch.MIN_SHARED
    assert canon_watch.similar("Something about keyboards and firmware flashing only.", lessons) == []


def _placed(tmp_path: Path, rid: str, body: str):
    return Bucket(tmp_path / "user", "user", "user"), SimpleNamespace(id=rid, body=body)


def test_the_sweep_fails_canon_for_a_resembling_placed_lesson(tmp_path):
    cache = tmp_path / "cache"
    placed = [_placed(tmp_path, "lrn-c0000001", LESSON), _placed(tmp_path, "lrn-c0000002", OTHER)]
    claude = _claude(tmp_path, "An older line of mine that stays where it is today.")
    assert premise_sweep._canon_facts(tmp_path / "ledger", placed, claude, cache, NOW) == []
    _claude(tmp_path, "An older line of mine that stays where it is today.\n\n" + RULE)
    (fact,) = premise_sweep._canon_facts(
        tmp_path / "ledger", placed, claude, cache, NOW + timedelta(days=1)
    )
    (change,) = canon_watch._load_changes(canon_watch.watch_dir(cache))
    assert (fact.record_id, fact.premise_id, fact.state) == ("lrn-c0000001", "@canon", "failing")
    assert fact.value == f"canon:{change.sha}" and f"change:{change.sha}" in fact.shown
    assert RULE not in fact.shown and RULE not in fact.detail  # only the hash travels
    # the same value on the next sweep, so two sweeps confirm it
    (again,) = premise_sweep._canon_facts(
        tmp_path / "ledger", placed, claude, cache, NOW + timedelta(days=2)
    )
    assert again.value == fact.value
    rows = [premise_sweep._fact_row(f, at) for f, at in
            ((fact, "2026-11-13T12:00:00Z"), (again, "2026-11-14T12:00:00Z"))]
    assert premise_sweep.judge_placement(rows).confirmed
    assert "@canon" in premises.PLACEMENT_PREMISE_IDS


def test_the_brief_shows_what_the_user_wrote_and_how_to_decide(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    claude = _claude(tmp_path, "An older line of mine that stays where it is today.")
    canon_watch.observe(cache, claude, now=NOW)
    _claude(tmp_path, "An older line of mine that stays where it is today.\n\n" + RULE)
    (change,) = canon_watch.observe(cache, claude, now=NOW + timedelta(days=1))
    monkeypatch.setattr(premise_sweep, "default_cache_dir", lambda home: cache)
    item = {"premise": "@canon", "now": f"CLAUDE.md change:{change.sha} first seen 2026-11-13",
            "claim": "c", "since": "s", "now_at": "n"}
    record = SimpleNamespace(id="lrn-c0000001")
    lines = "\n".join(steward_inputs._placement_item_lines(tmp_path, record, item))
    assert "wrote by hand" in lines and RULE in lines
    gone = {**item, "now": "CLAUDE.md change:000000000000 first seen 2026-11-13"}
    assert "no longer kept" in "\n".join(
        steward_inputs._placement_item_lines(tmp_path, record, gone)
    )
    decide = "\n".join(steward_inputs._placement_decide_lines(None, ["@canon"]))
    assert "outrank a lesson" in decide and "covered_by" in decide
    assert "outrank a lesson" not in "\n".join(
        steward_inputs._placement_decide_lines(None, ["@reach"])
    )


def test_a_trigger_that_ends_in_a_colon_is_not_rendered_with_two():
    record = Record.create(
        type="behavior", scope="user", source="teach", kind="anti-pattern",
        trigger="About to push a branch nobody reviewed:", instruction="Stop and read it.",
        record_id="lrn-c0000003",
    )
    line = compilers.entry_line(record)
    assert "reviewed:** stop" in line and "::" not in line
    plain = Record.create(
        type="behavior", scope="user", source="teach", kind="anti-pattern",
        trigger="About to push a branch nobody reviewed.", instruction="Stop and read it.",
        record_id="lrn-c0000004",
    )
    assert "reviewed:** stop" in compilers.entry_line(plain)  # the full stop, as before
