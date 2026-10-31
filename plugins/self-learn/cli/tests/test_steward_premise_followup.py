"""S-NEXT-u3-followup (premise-check design, unit U3): a closed follow-up puts the
placed lesson in front of the steward.

The case that prompted it (read from the live ledger, 2026-10-30): a routed
lesson said "nothing binds this daemon to the bus", its follow-up was met and
closed on 2026-10-29 with the proof in `follow_up_done.done_note`, and nothing
connected the two, so the always-loaded line stayed false. The user, 2026-10-30:
"What use is a self learning system if it can't keep its lessons up to date."

What this file pins, each of it failing on master (the kind, the selection and
the brief do not exist there):

* a routed lesson whose follow-up was closed after it was last decided is a
  `premise-moved` input, and an OPEN follow-up is not (the positive control for
  every "nothing is offered" assertion below);
* the one predicate is both the live trigger and the one-time pass: a follow-up
  closed before the last decision is left alone, one closed on the same day or
  later is offered, and the last decision is the premise spec's own rule (02
  section 3a.10.4): the `opened_at` of the newest case that names the lesson, or
  `routed_at` when none does -- never a history entry or `last_confirmed`;
* a case opened after the closing takes the lesson out of the list only because
  every brief of a routed lesson shows its closed follow-up (the review's first
  finding: otherwise a reconsider input decided first loses the lesson without
  the case ever seeing what moved);
* a run that decided an input never sees it again; its version is
  `follow_up:<done_at>`, so a follow-up closed on another day is a new input;
* the switch (`premises.enabled`, tier C, default ON in code), the overseer's
  hold, another input of the run and the per-run cap of ten each hold an input
  back;
* the steward's due check sees the input;
* the brief carries what moved with the record's own lines to cite, the deciding
  case's own "what would change this decision" bullets and nothing else of its
  decision, and no transcript evidence pack;
* end to end, a fake steward decides it, the run record carries the kind, and
  it is never offered again.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real `~/.self-learn`). No model call; ids and texts are
synthetic.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import (
    cases,
    gitops,
    ledger_ops,
    serve,
    settings,
    steward,
    steward_inputs,
    verbs,
)
from self_learn.invocation.contract import Outcome
from self_learn.records import Record
from support import commit_all, make_behavior, make_env, proposal_dict
from test_steward import _configure_steward, _dump_yaml, _stage_dir
from test_steward_inputs import _publish_disposition

A = "lrn-f5a00001"
B = "lrn-f5a00002"
C = "lrn-f5a00003"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")


def _day(offset: int = 0) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()


def _routed(env, rid: str, *, action: str = "bind the unit to the bus") -> str:
    """A routed lesson with an OPEN follow-up, as `route --follow-up` makes it."""
    ledger = env.ledger
    ledger_ops.create_record(ledger, make_behavior(record_id=rid, scope="skill:s"))
    ledger_ops.write_proposal(ledger, rid, proposal_dict(scope="skill:s"))
    commit_all(ledger, f"seed {rid}")
    verbs.route(
        ledger, rid, dest="skill-md", no_push=True,
        follow_up={"action": action, "unblocks_on": "the unit is bound"},
    )
    return rid


def _close(home: Path, rid: str, *, done_at: str, note: str = "the condition is met") -> None:
    """Close the follow-up with a chosen DATE (the verb always writes today's)."""
    path = ledger_ops.find_record_path(home, rid)
    record = Record.from_path(path)
    record.complete_follow_up(done_at=done_at, done_note=note)
    record.write(path)
    commit_all(home, f"close the follow-up on {rid}")


def _moved(home: Path) -> list[str]:
    return [row["record"] for row in steward._premise_moved_inputs(home)]


def _case_index(rows: list[dict]):
    """A stand-in for `cases.list_cases` over *rows* that answers only the
    queries the code under test makes about ONE lesson: the overseer's holds
    (`parked_for=`) are asked of the real index's shape and found empty, so a
    row the test makes up never holds the lesson by accident."""

    def list_cases(home_, *, parked_for=None, **kwargs):
        return [] if parked_for is not None else [dict(row) for row in rows]

    return list_cases


# ------------------------------------------------------------- the kind


def test_a_closed_follow_up_is_a_premise_moved_input_and_an_open_one_is_not(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    # control: the follow-up is open, so nothing has moved
    assert steward._premise_moved_inputs(home) == []

    verbs.followup_done(home, A, note="the condition is met", no_push=True)
    (row,) = steward._premise_moved_inputs(home)

    assert steward_inputs.INPUT_PREMISE_MOVED == "premise-moved"
    assert steward_inputs.INPUT_PREMISE_MOVED in steward_inputs.INPUT_KINDS
    assert row["kind"] == "premise-moved" and row["record"] == A
    assert row["record_status"] == "routed" and row["version"] == row["blob"]
    assert row["version"] == f"follow_up:{_day()}"
    assert row["moved"] == [{
        "source": "follow-up-done", "done_at": _day(),
        "action": "bind the unit to the bus", "unblocks_on": "the unit is bound",
        "done_note": "the condition is met",
    }]
    # a lesson routed by hand has no covering case to supersede
    assert "predecessor" not in row
    # the row reaches the brief with the facts it carries
    brief_input = steward._brief_input(row)
    assert brief_input["kind"] == "premise-moved" and brief_input["moved"] == row["moved"]
    assert brief_input["reason"] == row["reason"]


def test_closed_followups_are_routed_records_that_carry_the_block(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    _routed(env, C)
    verbs.followup_done(home, A, no_push=True)
    verbs.followup_done(home, C, no_push=True)
    # positive control: B's follow-up is open, so it is not "closed"
    assert [r.id for r in ledger_ops.closed_followups(home)] == [A, C]
    # a record that left `routed` keeps the block but its lifecycle ended
    verbs.retire(home, C, covered_by="skill-md:s", no_push=True)
    assert [r.id for r in ledger_ops.closed_followups(home)] == [A]
    assert _moved(home) == [A]


# --------------------------------------- the one predicate, by day


def test_a_follow_up_closed_before_the_last_decision_is_left_alone(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    for rid in (A, B, C):
        _routed(env, rid)
    _close(home, A, done_at=_day(-30))
    _close(home, B, done_at=_day(0))
    _close(home, C, done_at=_day(-1))

    # control: A and C have a dated decision (the routing), so they are left
    # alone by the comparison, not because nothing about them is dated
    record = Record.from_path(ledger_ops.find_record_path(home, A))
    decided_at, by = steward_inputs.last_decision(home, record)
    assert decided_at is not None and by == "routed_at"
    # B closed the day it was routed counts as after (one look, never a miss)
    assert _moved(home) == [B]


@pytest.mark.parametrize(
    "kind, outcome",
    [
        ("resolution", "route"),
        ("reconsider", "replaced"),
        ("resolution", "retire"),
        # the premise spec counts the newest case that names the lesson, whatever
        # it decided: it froze its facts when it opened, and its brief showed
        # the closed follow-up
        ("resolution", "no-action"),
        ("resolution", "defer"),
        ("parked", "parked"),
    ],
)
def test_the_last_decision_is_the_newest_case_that_names_the_lesson(tmp_path, monkeypatch, kind, outcome):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    verbs.followup_done(home, A, no_push=True)
    row = {"case": "case-0000beef", "kind": kind, "outcome": outcome, "records": [A]}
    # control: a case opened BEFORE the closing leaves the lesson offered, so the
    # case index is read (not nothing at all) when the next line drops it
    monkeypatch.setattr(cases, "list_cases", _case_index([dict(row, opened_at=f"{_day(-1)}T00:00:00Z")]))
    assert _moved(home) == [A]
    monkeypatch.setattr(cases, "list_cases", _case_index([dict(row, opened_at=f"{_day(1)}T00:00:00Z")]))
    assert _moved(home) == []
    decided_at, by = steward_inputs.last_decision(home, Record.from_path(ledger_ops.find_record_path(home, A)))
    assert by == "case:case-0000beef" and decided_at.date().isoformat() == _day(1)


def test_a_history_entry_or_a_confirmation_is_not_a_decision(tmp_path):
    """A `reconsidered` entry is dated when the case APPLIED (weeks after it froze
    its facts) and `last_confirmed` says a person saw the rule work: neither says
    the closed follow-up was looked at, so neither takes the lesson out."""
    env = make_env(tmp_path)
    home = env.ledger
    for rid in (A, B, C):
        _routed(env, rid)
        verbs.followup_done(home, rid, no_push=True)
    assert _moved(home) == [A, B, C]  # control: all three are offered before

    later = f"{_day(1)}T00:00:00Z"
    path = ledger_ops.find_record_path(home, A)
    record = Record.from_path(path)
    record.append_history("reconsidered", {"at": later, "case": "case-0000beef"})
    record.write(path)
    path = ledger_ops.find_record_path(home, B)
    record = Record.from_path(path)
    record.set_last_confirmed(_day(1))
    record.write(path)
    path = ledger_ops.find_record_path(home, C)
    record = Record.from_path(path)
    record.append_history("moved", {"at": later, "by": "steward"})
    record.write(path)
    commit_all(home, "later facts")

    assert _moved(home) == [A, B, C]
    decided_at, by = steward_inputs.last_decision(home, Record.from_path(ledger_ops.find_record_path(home, A)))
    assert by == "routed_at" and decided_at is not None and decided_at.date().isoformat() == _day()


# --------------------------------------------------- identity


def test_a_decided_input_is_not_offered_again_and_a_returned_one_is(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    verbs.followup_done(home, A, no_push=True)
    (row,) = steward._premise_moved_inputs(home)

    # sent back is not decided: the next run offers it again
    _publish_disposition(home, A, row["version"], "returned", "run-f5a000000001")
    assert _moved(home) == [A]
    _publish_disposition(home, A, row["version"], "applied", "run-f5a000000002")
    assert _moved(home) == []
    # an applied row under another version decides nothing about this one
    _publish_disposition(home, A, "follow_up:2000-01-01", "applied", "run-f5a000000003")
    assert _moved(home) == []


def test_the_version_is_the_closing_day_and_the_premises_that_moved():
    done = {"action": "bind it", "unblocks_on": "bound", "done_at": "2026-10-29", "done_note": "met"}
    version = steward_inputs.premise_moved_version(followup_done=done)
    # 02 section 3a.10.7: `follow_up:<done_at>` for a closed follow-up alone
    assert version == "follow_up:2026-10-29"
    assert version == steward_inputs.premise_moved_version(followup_done=dict(done))
    # a follow-up closed on another day is a new input; other words the same day are not
    assert version != steward_inputs.premise_moved_version(followup_done={**done, "done_at": "2026-10-30"})
    assert version == steward_inputs.premise_moved_version(followup_done={**done, "done_note": "met again"})
    # a premise that moved is part of it, whatever order the pairs arrive in
    pairs = [("p2", "bbb"), ("p1", "aaa")]
    both = steward_inputs.premise_moved_version(followup_done=done, moved=pairs)
    assert both == "premises:p1=aaa,p2=bbb;follow_up:2026-10-29"
    assert both == steward_inputs.premise_moved_version(followup_done=done, moved=reversed(pairs))
    assert both != steward_inputs.premise_moved_version(followup_done=done, moved=[("p1", "ccc"), ("p2", "bbb")])
    assert steward_inputs.premise_moved_version(moved=pairs) == "premises:p1=aaa,p2=bbb"
    # a date that is a value, not text (hand-edited YAML), or a timestamp, names the same day
    assert version == steward_inputs.premise_moved_version(
        followup_done={**done, "done_at": datetime(2026, 10, 29).date()}
    )
    assert version == steward_inputs.premise_moved_version(
        followup_done={**done, "done_at": "2026-10-29T10:30:00Z"}
    )
    # an input that names nothing that moved has no identity
    with pytest.raises(ValueError):
        steward_inputs.premise_moved_version()


# ------------------------------------- what holds an input back


def test_the_switch_the_hold_another_input_and_the_cap_hold_an_input_back(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    for rid, day in ((C, 0), (B, 1), (A, 2)):
        _routed(env, rid)
        _close(home, rid, done_at=_day(day))
    # control: all three are offered, oldest closing first (not by id)
    assert _moved(home) == [C, B, A]

    # the cap: the rest wait for the next run
    with monkeypatch.context() as patch:
        patch.setattr(steward_inputs, "PREMISE_MOVED_PER_RUN", 2)
        assert _moved(home) == [C, B]

    # another input of the run already names the lesson
    assert [r["record"] for r in steward._premise_moved_inputs(home, exclude={C})] == [B, A]

    # the overseer holds a lesson: the steward is offered nothing about it
    with monkeypatch.context() as patch:
        patch.setattr(cases, "held_lessons", lambda home_: {B: [{"case": "case-0000beef"}]})
        assert _moved(home) == [C, A]

    # the switch is on in code until it is set false
    assert steward_inputs.premises_enabled(home) is True
    real_by_name, real_resolve = settings.by_name, settings.resolve_setting
    stand_in = SimpleNamespace(name="premises.enabled")

    def by_name(name):
        return stand_in if name == "premises.enabled" else real_by_name(name)

    def resolving(value):
        return lambda home_, s: (value, "config") if s is stand_in else real_resolve(home_, s)

    with monkeypatch.context() as patch:
        patch.setattr(settings, "by_name", by_name)
        patch.setattr(settings, "resolve_setting", resolving(False))
        assert steward_inputs.premises_enabled(home) is False
        assert steward._premise_moved_inputs(home) == []
        # control: the stand-in is read, and true gives every input back
        patch.setattr(settings, "resolve_setting", resolving(True))
        assert steward_inputs.premises_enabled(home) is True
        assert _moved(home) == [C, B, A]


# --------------------------------------------------- the due check


def test_the_steward_due_check_sees_a_premise_moved_input(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _configure_steward(home)
    cache = tmp_path / "cache"
    now = time.time()
    # control: the steward is on, a follow-up is open, nothing is due
    assert serve._steward_is_due(home, cache, now) is False

    verbs.followup_done(home, A, no_push=True)
    assert steward._premise_moved_inputs(home)
    assert serve._steward_is_due(home, cache, now) is True


def test_the_due_check_hands_the_manifests_it_read_to_the_terminal_check(tmp_path, monkeypatch):
    """`serve._steward_is_due` reads the committed manifests once a tick; the
    premise check must not read every one of them from git a second time (the
    review's cost finding)."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    verbs.followup_done(home, A, no_push=True)
    (row,) = steward._premise_moved_inputs(home)
    manifests = [{"packets": [{"dispositions": {
        A: {"state": "applied", "input_version": row["version"]},
    }}]}]

    def refuse(home_):
        raise AssertionError("the committed manifests were read again")

    monkeypatch.setattr(steward, "committed_manifests", refuse)
    # the manifests handed in decide it; nothing is read from git
    assert steward._premise_moved_inputs(home, manifests=manifests) == []
    # positive control: without them the (refusing) read is made
    with pytest.raises(AssertionError, match="read again"):
        steward._premise_moved_inputs(home)
    # and a manifest that decided another version of it decides nothing here
    other = [{"packets": [{"dispositions": {A: {"state": "applied", "input_version": "follow_up:2000-01-01"}}}]}]
    assert [r["record"] for r in steward._premise_moved_inputs(home, manifests=other)] == [A]


# ------------------------------------------------------- the brief


def _brief(home: Path, row: dict) -> str:
    briefs = steward_inputs.build_briefs(
        home, [steward._brief_input(row)],
        find_record_path=ledger_ops.find_record_path, head=gitops.head_sha(home), roots=[],
    )
    return briefs[row["record"]].body


def test_the_brief_shows_what_moved_with_the_record_lines_to_cite(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    verbs.followup_done(home, A, note="the condition is met", no_push=True)
    (row,) = steward._premise_moved_inputs(home)
    body = _brief(home, row)

    assert body.startswith("[input] premise-moved\n[why it is back] ")
    assert "Decide whether the lesson is still true as written" in body
    assert "Stop the container first" in body  # the lesson itself, as for any brief
    assert "[what moved]" in body
    assert f"the follow-up on this lesson was closed on {_day()}" in body
    assert "what the follow-up asked for: bind the unit to the bus" in body
    assert "it was to be closed when: the unit is bound" in body
    assert "the note it was closed with: the condition is met" in body

    # the cited span is the block's real place in the record file
    path = ledger_ops.find_record_path(home, A)
    lines = path.read_text(encoding="utf-8").splitlines()
    first = lines.index("follow_up_done:") + 1
    last = first
    while last < len(lines) and lines[last].startswith(" "):
        last += 1
    rel = path.relative_to(home).as_posix()
    assert f":{rel}#L{first}-{last})" in body
    assert f"L{first}: follow_up_done:" in body
    # indentation kept: the block's structure reads as the record holds it
    assert f"L{last}:   done_note: the condition is met" in body

    # no case covers it: the brief says how that is decided, and quotes no case
    assert "[how to decide it] no case covers this lesson" in body
    assert "[what the deciding case" not in body
    # the lesson's transcript evidence is not what moved: no pack. The same
    # lesson as an ordinary input has one (positive control).
    assert "[evidence pack]" not in body
    assert "[evidence pack]" in _brief(home, {"record": A, "kind": "lesson"})


@pytest.mark.parametrize("kind", ["lesson", "reconsider", "suspected-violation"])
def test_every_brief_of_a_lesson_with_a_closed_follow_up_shows_it(tmp_path, kind):
    """The guard behind `last_decision`: a case opened after the closing takes the
    lesson out of the premise check (a reconsider input decided first, a suspected
    violation, a plain queued lesson), so each of those briefs must carry the
    closed follow-up -- or the lesson would lose it without the case ever seeing
    what moved (the review's first finding, the oo7 failure over again)."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    # control: while the follow-up is OPEN the brief has no such block
    assert "[closed follow-up]" not in _brief(home, {"record": A, "kind": kind})

    verbs.followup_done(home, A, note="the condition is met", no_push=True)
    body = _brief(home, {"record": A, "kind": kind})

    assert "[closed follow-up]" in body
    assert f"the follow-up on this lesson was closed on {_day()}" in body
    assert "what the follow-up asked for: bind the unit to the bus" in body
    assert "the note it was closed with: the condition is met" in body
    path = ledger_ops.find_record_path(home, A)
    lines = path.read_text(encoding="utf-8").splitlines()
    first = lines.index("follow_up_done:") + 1
    assert f":{path.relative_to(home).as_posix()}#L{first}-" in body
    assert f"L{first}: follow_up_done:" in body
    # a premise-moved input is not one of these: it carries the facts in its own
    # block, once
    (row,) = steward._premise_moved_inputs(home)
    moved_body = _brief(home, row)
    assert "[closed follow-up]" not in moved_body
    assert moved_body.count("the follow-up on this lesson was closed on") == 1
    assert moved_body.count("L%d: follow_up_done:" % first) == 1


def test_a_covering_case_is_the_predecessor_and_only_its_what_would_change_is_shown(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    verbs.followup_done(home, A, no_push=True)

    rows = [
        {"case": "case-1a2b3c4d", "opened_at": "2026-09-22T06:34:15Z", "records": [A]},
        {"case": "case-2b3c4d5e", "opened_at": "2026-09-23T06:34:15Z", "records": [A]},
        {"case": "case-3c4d5e6f", "opened_at": "2026-09-24T06:34:15Z", "records": [A],
         "superseded_by": "case-4d5e6f7a"},
        {"case": "case-5e6f7a8b", "opened_at": "2026-09-25T06:34:15Z", "records": [A]},
    ]
    monkeypatch.setattr(cases, "list_cases", _case_index(rows))
    # the apply-time test: the newest still-open case that passes it wins; a
    # superseded case and one that fails it do not
    monkeypatch.setattr(
        steward, "_reconsider_predecessor_problem",
        lambda home_, case_id, rid: "refused" if case_id == "case-5e6f7a8b" else None,
    )
    (row,) = steward._premise_moved_inputs(home)
    assert row["predecessor"] == "case-2b3c4d5e"
    assert steward._brief_input(row)["predecessor"] == "case-2b3c4d5e"

    decision = (
        "- verb: route\n- because: the host had nothing then\n- confidence: settled\n\n"
        "What would change this decision:\n- a drop-in binds the unit to the bus\n"
        "- the guard re-checks after a restart\n\nsecond paragraph"
    )
    monkeypatch.setattr(
        cases, "show", lambda home_, case_id, evidence_only=True: SimpleNamespace(sections={"Decision": decision})
    )
    body = _brief(home, row)
    assert "[what the deciding case (case-2b3c4d5e) said would change it]" in body
    assert "  - a drop-in binds the unit to the bus" in body
    assert "  - the guard re-checks after a restart" in body
    # only that list: the rest of the decision stays out of the brief
    assert "the host had nothing then" not in body and "second paragraph" not in body
    assert "`supersedes: case-2b3c4d5e`" in body
    assert "no case covers this lesson" not in body
    assert "method section 17" in body


def test_a_case_without_a_what_would_change_list_shows_none(monkeypatch):
    monkeypatch.setattr(
        cases, "show",
        lambda home_, case_id, evidence_only=True: SimpleNamespace(sections={"Decision": "- verb: route\n"}),
    )
    assert steward_inputs._would_change_lines(Path("."), "case-1a2b3c4d") == []

    def refuse(home_, case_id, evidence_only=True):
        raise cases.CaseError("failed its freeze-hash check")

    monkeypatch.setattr(cases, "show", refuse)
    assert steward_inputs._would_change_lines(Path("."), "case-1a2b3c4d") == []


def test_a_mover_another_unit_adds_is_shown_as_recorded(tmp_path):
    """U4 (the premise sweep) and U8 (placement premises) raise this kind with
    their own `moved` items; until they render their own lines the brief shows
    what the row carries, so a mover is never silently dropped."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    row = {
        "record": A, "kind": "premise-moved", "reason": "a premise moved",
        "moved": [{"source": "probe", "claim": "the unit is not bound", "now": "bound"}],
    }
    body = _brief(home, row)
    assert "moved (probe): claim: the unit is not bound, now: bound" in body
    assert "closed follow-up as the record holds it" not in body


# --------------------------------------------------- through a run


def test_a_run_decides_a_premise_moved_input_once(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    verbs.followup_done(home, A, note="the condition is met", no_push=True)
    _configure_steward(home)
    seen: list[str] = []

    def fake(spec):
        seen.append(spec.prompt)
        stage = _stage_dir(spec)
        for rid in re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M):
            _dump_yaml(stage / "cases" / f"{rid}.yaml", {
                "kind": "resolution", "trigger": "nightly", "outcome": "no-action",
                "records": [rid], "scope": "skill:s",
                "question": "is the lesson still true now that its follow-up is closed?",
                "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
                "decision": {"verb": "note", "because": "the closing note leaves it true",
                             "confidence": "settled"},
                "dependencies": {"statements": [], "user_model": [], "conditions": [],
                                 "capabilities": []},
            })
            _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
                "version": 1, "case": "$CASE_ID",
                "items": [{"id": rid, "verb": "note",
                           "append": "checked against the closed follow-up: still true"}],
            })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", fake)
    result = steward.run(home)
    assert result.status == "applied", result
    assert len(seen) == 1
    assert "[input] premise-moved" in seen[0] and f"### brief: {A}" in seen[0]
    assert "the note it was closed with: the condition is met" in seen[0]

    manifest = steward.committed_manifests(home)[-1]
    assert [(row["record"], row["kind"]) for row in manifest["inputs"]] == [(A, "premise-moved")]
    # decided: not offered again, the due check is quiet, the next run is idle
    assert steward._premise_moved_inputs(home) == []
    assert steward.run(home).status == "idle"
    assert len(seen) == 1


# ------------------------------- through a run: a lesson a case placed (lrn-9b4250f5's shape)


def _placed_by_a_case(home: Path, setup: Path, rid: str) -> str:
    """The lesson is routed to its skill's SKILL.md by a steward case with a
    follow-up, the way the pipeline places lessons (the live acceptance case:
    routed by case-333cc8dc, follow-up closed a month later); returns the case."""
    from self_learn import batch
    from test_steward_refusals import _case
    from test_u3b_steward_authority import HOOK_TRIGGER, _record_case

    setup.mkdir(parents=True, exist_ok=True)
    ledger_ops.create_record(home, make_behavior(record_id=rid, trigger=HOOK_TRIGGER))
    ledger_ops.write_proposal(home, rid, proposal_dict())
    ledger_ops.stamp_proposal(home, rid)
    commit_all(home, f"seed {rid}")
    case_id = _record_case(home, setup, _case([rid], "route", "route"))
    sheet = setup / "route.yaml"
    _dump_yaml(sheet, {"version": 1, "case": case_id, "items": [{
        "id": rid, "verb": "route", "dest": "skill-md",
        "follow_up": "bind the unit to the bus", "unblocks_on": "the unit is bound",
    }]})
    result = batch.run(home, batch.load_sheet(sheet, home=home), no_push=True, actor="steward")
    assert result.items[0].state == "applied", result.items[0].detail
    return case_id


def test_a_lesson_a_case_placed_is_decided_through_a_reconsider_case_and_not_offered_again(tmp_path, monkeypatch):
    """The covering-case path end to end, with nothing about the case index or the
    predecessor test stubbed: the real `cases.require_reconsider_predecessor`
    accepts the route case, the runner fills in `supersedes`, `verbs.reconsider`
    applies and writes `history: reconsidered`, and the input is not offered
    again (the review's first MINOR: the live acceptance case lrn-9b4250f5 takes
    this path and nothing ran it)."""
    from test_steward_refusals import _case

    env = make_env(tmp_path)
    home = env.ledger
    rid = "lrn-f5a00004"
    prior = _placed_by_a_case(home, tmp_path / "setup", rid)
    # control: the follow-up is open, so nothing has moved
    assert steward._premise_moved_inputs(home) == []
    verbs.followup_done(home, rid, note="the condition is met", no_push=True)

    (row,) = steward._premise_moved_inputs(home)
    assert row["predecessor"] == prior
    decided_at, by = steward_inputs.last_decision(home, Record.from_path(ledger_ops.find_record_path(home, rid)))
    assert decided_at is not None and by == f"case:{prior}"

    _configure_steward(home)
    seen: list[str] = []

    def fake(spec):
        seen.append(spec.prompt)
        stage = _stage_dir(spec)
        case = _case([rid], "no-action", "note")
        # no `supersedes`: the runner fills it in from the input's predecessor
        case.update(kind="reconsider", trigger="reconsider",
                    question="is the lesson still true now that its follow-up is closed?")
        _dump_yaml(stage / "cases" / f"{rid}.yaml", case)
        _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "note",
                       "append": "checked against the closed follow-up: still true"}],
        })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", fake)
    result = steward.run(home)

    assert result.status == "applied", result
    assert len(seen) == 1 and "[input] premise-moved" in seen[0] and f"### brief: {rid}" in seen[0]
    assert f"`supersedes: {prior}`" in seen[0]
    by_id = {c["case"]: c for c in cases.list_cases(home, record_id=rid)}
    (successor,) = [c for c in by_id.values() if c["case"] != prior]
    assert successor["kind"] == "reconsider" and successor["supersedes"] == prior
    assert by_id[prior]["superseded_by"] == successor["case"]
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert any(
        h.get("event") == "reconsidered" and h.get("case") == successor["case"] for h in record.history
    )
    manifest = steward.committed_manifests(home)[-1]
    assert [(r["record"], r["kind"]) for r in manifest["inputs"]] == [(rid, "premise-moved")]
    # decided: not offered again, the next run is idle
    assert steward._premise_moved_inputs(home) == []
    assert steward.run(home).status == "idle"
    assert len(seen) == 1
