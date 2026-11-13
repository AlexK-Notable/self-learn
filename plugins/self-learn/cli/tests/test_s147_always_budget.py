"""S-147 (2026-11-12): the word budget of the user's always-loaded lessons.

The user's rule of 2026-08-19 is that user scope holds only high-value lessons
that recur across many sessions and projects. Nothing kept the file to it: a
report-only signal flagged the growth and the file reached 47 lesson lines.

Pinned here:

* the ranking and the budget arithmetic (`always_budget.standings`): the
  best-ranked lines fill the budget, the rest are over, a line in its first
  days is charged and never over, and no budget means nothing is over;
* the sweep derives `@budget` only for lessons in the user's always-loaded
  file, failing for the lines past the budget, with a value that is stable
  across nights so two sweeps confirm it;
* a confirmed `@budget` failure is a placement move the steward is offered;
* the steward's runner refuses a case that would enter a line past the
  budget, and one that keeps a line over the budget without the three tests;
* the brief says how to decide such an input.

Synthetic ids and texts; no model call; no real `~/.claude`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import always_budget, ledger_ops, premise_sweep, premises, steward, steward_inputs
from self_learn.always_budget import Line
from self_learn.ledger import Bucket
from self_learn.records import Record
from support import commit_all, make_env

TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=60)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")


def _entry(rid: str, words: int) -> str:
    return "- " + " ".join(["word"] * (words - 2)) + f" *({rid})*"


# ------------------------------------------------------------ 1. the ranking


def test_the_best_ranked_lines_fill_the_budget_and_the_rest_are_over():
    lines = [
        Line("lrn-b0000001", 100, fires=9, sessions=5, placed_at=OLD),
        Line("lrn-b0000002", 100, fires=3, sessions=2, placed_at=OLD),
        Line("lrn-b0000003", 100, fires=0, sessions=0, placed_at=OLD),
        Line("lrn-b0000004", 100, fires=1, sessions=1, placed_at=OLD),
    ]
    got = always_budget.standings(lines, 250, TODAY)
    assert [rid for rid, row in got.items() if row.over] == ["lrn-b0000004", "lrn-b0000003"]
    assert got["lrn-b0000001"].rank == 1 and got["lrn-b0000003"].rank == 4
    assert got["lrn-b0000003"].total_words == 400 and got["lrn-b0000003"].budget == 250
    # once one line does not fit, no worse-ranked line is kept in its place
    lines.append(Line("lrn-b0000005", 10, fires=0, sessions=0, placed_at=OLD))
    assert always_budget.standings(lines, 250, TODAY)["lrn-b0000005"].over


def test_no_budget_means_nothing_is_over():
    lines = [Line("lrn-b0000001", 5000, placed_at=OLD)]
    assert not always_budget.standings(lines, 0, TODAY)["lrn-b0000001"].over
    assert always_budget.standings(lines, 100, TODAY)["lrn-b0000001"].over  # control


def test_a_line_in_its_first_days_is_charged_and_never_over():
    fresh = Line("lrn-b0000001", 200, placed_at=NOW - timedelta(days=3))
    seen = Line("lrn-b0000002", 100, fires=5, sessions=5, placed_at=OLD)
    got = always_budget.standings([fresh, seen], 250, TODAY)
    assert got["lrn-b0000001"].grace and not got["lrn-b0000001"].over
    assert got["lrn-b0000002"].over  # the fresh line's 200 words are spent first
    aged = Line("lrn-b0000001", 200, placed_at=NOW - timedelta(days=always_budget.GRACE_DAYS))
    assert always_budget.standings([aged, seen], 250, TODAY)["lrn-b0000001"].over


def test_entry_words_and_fire_stats():
    text = "### Lessons\n" + _entry("lrn-b0000001", 12) + "\n" + _entry("lrn-b0000002", 30) + "\n"
    assert always_budget.entry_words(text) == {"lrn-b0000001": 12, "lrn-b0000002": 30}
    events = [
        {"kind": "fire", "record": "lrn-b0000001", "ts": "2026-11-10T00:00:00Z",
         "action": "transcript:aaaa#L1", "origin": "transcript:aaaa#L9"},
        {"kind": "fire", "record": "lrn-b0000001", "ts": "2026-11-11T00:00:00Z",
         "action": "transcript:bbbb#L1"},
        {"kind": "fire", "record": "lrn-b0000001", "ts": "2026-01-01T00:00:00Z",
         "action": "transcript:cccc#L1"},  # outside the window
        {"kind": "capture", "record": "lrn-b0000001", "ts": "2026-11-11T00:00:00Z"},
    ]
    assert always_budget.fire_stats(events, now=NOW) == {"lrn-b0000001": (2, 2)}


def test_user_lines_reads_the_block_the_records_and_the_fires(tmp_path):
    home = make_env(tmp_path).ledger
    record = SimpleNamespace(
        recurrences=[{"ts": "2026-11-01T00:00:00Z"}],
        routing={"destination": "claude-md", "variant": None,
                 "routed_at": "2026-09-01T00:00:00Z"},
    )
    events = [{"kind": "fire", "record": "lrn-b0000001", "ts": "2026-11-10T00:00:00Z",
               "action": "transcript:aaaa#L1"}]
    text = _entry("lrn-b0000001", 12) + "\n" + _entry("lrn-b0000002", 20) + "\n"
    lines = {
        line.record_id: line
        for line in always_budget.user_lines(
            home, text, {"lrn-b0000001": record}, now=NOW, events=events
        )
    }
    one = lines["lrn-b0000001"]
    assert (one.words, one.fires, one.sessions, one.recurrences) == (12, 1, 1, 1)
    assert one.placed_at == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert lines["lrn-b0000002"] == Line("lrn-b0000002", 20)  # an entry with no record
    # the real telemetry reader is used when no events are given (an empty ledger: none)
    assert {line.fires for line in always_budget.user_lines(home, text, {}, now=NOW)} == {0}


def test_the_failing_value_is_the_same_all_month_and_new_next_month():
    assert always_budget.failing_value(1500, date(2026, 11, 2)) == always_budget.failing_value(
        1500, date(2026, 11, 29)
    )
    assert always_budget.failing_value(1500, date(2026, 12, 1)) != always_budget.failing_value(
        1500, date(2026, 11, 29)
    )
    assert always_budget.failing_value(1000, TODAY) != always_budget.failing_value(1500, TODAY)


# ---------------------------------------------------------- 2. the sweep


def _placed(tmp_path: Path, rid: str, *, scope: str = "user", destination: str = "claude-md",
            variant=None):
    record = SimpleNamespace(
        id=rid, recurrences=[],
        routing={"destination": destination, "variant": variant,
                 "routed_at": "2026-09-01T00:00:00Z"},
    )
    return Bucket(tmp_path / scope, scope, scope), record


def _budget_facts(tmp_path, monkeypatch, placed, region_text: str, budget: int):
    claude = tmp_path / "claude"
    monkeypatch.setattr(always_budget, "budget_words", lambda home: budget)
    monkeypatch.setattr(
        always_budget, "user_lines",
        lambda home, text, records, now=None, events=None: [
            Line(rid, words, placed_at=OLD)
            for rid, words in always_budget.entry_words(text).items()
        ],
    )
    regions = [premise_sweep._Region(
        placed[0][1], claude / "CLAUDE.md", "clean", region_text.encode(), None
    )]
    return premise_sweep._budget_facts(
        tmp_path / "ledger", placed, regions, claude, "2026-11-12T12:00:00Z"
    )


def test_the_sweep_fails_budget_only_for_user_lines_past_the_budget(tmp_path, monkeypatch):
    a, b, c = "lrn-b1000001", "lrn-b1000002", "lrn-b1000003"
    placed = [
        _placed(tmp_path, a), _placed(tmp_path, b),
        _placed(tmp_path, c, scope="project"),                  # a project's own file
        _placed(tmp_path, "lrn-b1000004", destination="hook"),  # not a line of the file
    ]
    text = _entry(a, 100) + "\n" + _entry(b, 100) + "\n"
    facts = {f.record_id: f for f in _budget_facts(tmp_path, monkeypatch, placed, text, 150)}
    assert set(facts) == {a, b}
    assert all(f.premise_id == "@budget" for f in facts.values())
    assert facts[a].state == "holds" and facts[b].state == "failing"
    assert facts[b].value == always_budget.failing_value(150, TODAY)
    assert "200 of 150 words" in facts[b].shown
    # control: with room for both, both hold; with the budget off, no fact
    roomy = _budget_facts(tmp_path, monkeypatch, placed, text, 500)
    assert {f.state for f in roomy} == {"holds"}
    assert _budget_facts(tmp_path, monkeypatch, placed, text, 0) == []


def test_two_sweeps_confirm_a_budget_failure_and_the_steward_is_offered_it(tmp_path):
    cache = tmp_path / "cache"
    rid = "lrn-b1000005"
    fact = premise_sweep._Fact(
        rid, "@budget", "failing", always_budget.failing_value(1500, TODAY),
        "4000 of 1500 words", "detail",
    )
    rows = [
        premise_sweep._fact_row(fact, "2026-11-11T10:00:00Z"),
        premise_sweep._fact_row(fact, "2026-11-12T10:00:00Z"),
    ]
    one = premise_sweep.judge_placement(rows[:1])
    two = premise_sweep.judge_placement(rows)
    assert one.verdict == premises.VERDICT_MOVED and not one.confirmed
    assert two.confirmed
    moves = premise_sweep.confirmed_placement_moves(
        tmp_path, cache, history={(rid, "@budget"): rows}
    )
    assert [(m.record_id, m.premise_id) for m in moves] == [(rid, "@budget")]
    assert "@budget" not in steward_inputs._PLACEMENT_WAITS  # it does not wait a week
    assert "@budget" in premises.PLACEMENT_PREMISE_IDS
    assert "@budget" not in premise_sweep.placement_ids("claude-md")  # derived apart


# ------------------------------------------------- 3. the steward's runner


def _user_fact(home: Path, rid: str, words: int = 40) -> None:
    ledger_ops.create_record(home, Record.create(
        type="knowledge", scope="user", source="teach",
        fact=" ".join(["fact"] * words), context="An invented example.", record_id=rid,
    ))
    commit_all(home, f"fact {rid}")


def test_a_case_that_would_enter_a_line_past_the_budget_is_refused(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    rid = "lrn-b2000001"
    _user_fact(home, rid)
    monkeypatch.setattr(always_budget, "budget_words", lambda h: 100)
    monkeypatch.setattr(always_budget, "_user_region_text", lambda d: _entry("lrn-b2000009", 90))
    case = {"kind": "resolution", "records": [rid]}
    line = {"id": rid, "verb": "route", "dest": "claude-md"}
    problem = always_budget.route_problem(home, case, [line], label="c.yaml")
    assert problem is not None and "budget of 100" in problem and rid in problem
    # controls: a cheaper destination, a parked case, room, and no budget all pass
    assert always_budget.route_problem(
        home, case, [{**line, "dest": "claude-md:rules:topic"}]) is None
    assert always_budget.route_problem(home, {**case, "kind": "parked"}, [line]) is None
    monkeypatch.setattr(always_budget, "budget_words", lambda h: 1000)
    assert always_budget.route_problem(home, case, [line]) is None
    monkeypatch.setattr(always_budget, "budget_words", lambda h: 0)
    assert always_budget.route_problem(home, case, [line]) is None


def _budget_input(rid: str) -> dict:
    return {rid: {
        "kind": steward_inputs.INPUT_PREMISE_MOVED,
        "moved": [{"source": "placement", "premise": "@budget"}],
    }}


def test_keeping_a_line_over_the_budget_needs_the_three_tests(tmp_path):
    rid = "lrn-b2000002"
    case = {"kind": "resolution", "outcome": "no-action", "records": [rid],
            "evidence": [{"ref": f"record:{rid}", "quote": "an invented quote"}]}
    problem = steward._budget_keep_problem(case, _budget_input(rid), label="c.yaml")
    assert problem is not None and "all three tests" in problem
    evidenced = {**case, "decision": {"always_loaded": {
        key: {"because": "an invented reason", "refs": [f"record:{rid}"]}
        for key in ("always_applies", "missing_costs_more", "cheaper_fixes_fail")
    }}}
    assert steward._budget_keep_problem(evidenced, _budget_input(rid), label="c.yaml") is None
    # controls: a move owes nothing; nor does a keep on another kind of input
    assert steward._budget_keep_problem(
        {**case, "outcome": "route"}, _budget_input(rid), label="c.yaml") is None
    other = {rid: {"kind": steward_inputs.INPUT_PREMISE_MOVED,
                   "moved": [{"source": "placement", "premise": "@reach"}]}}
    assert steward._budget_keep_problem(case, other, label="c.yaml") is None


def test_the_brief_says_how_to_decide_a_budget_input():
    lines = "\n".join(steward_inputs._placement_decide_lines(None, ["@budget"]))
    assert "over its budget" in lines and "warning hook" in lines and "ALL THREE" in lines
    assert "over its budget" not in "\n".join(
        steward_inputs._placement_decide_lines(None, ["@reach"])
    )
    assert "@budget" in steward_inputs._PLACEMENT_WORDS
