"""S-144 (2026-11-12): what the steward's crashes of 2026-11-07 showed.

Live: one `replace` line turned a pending FACT into a behavior lesson and
named no `kind`. `Record.create` refused it with a bare
`records.ValidationError`, which no layer read as the line's mistake: it
escaped the ledger preview, ended the steward job on three attempts in a row,
and the attempt cap parked the packet's five lessons as `no-progress` with no
cause on record. The weekly overseer then answered the fact's parked case with
a `route` to a hook, which the ledger refused (a hook needs a behavior
lesson); the parked case was superseded, so the hold lifted, and the lesson
sat queued at a version the steward's `abandoned` row called decided: no run
would ever take it again.

Pinned here:

* a `replace` or `restate` line whose words make an invalid lesson is a
  refused LINE (`SheetLineError`, kind `bad-line`), in the preview too;
* a failure inside the ledger preview becomes a repair message and a noted
  crash cause, not the end of the job;
* a noted crash cause reaches the parked case's detail;
* a lesson a `parked` or `abandoned` row handed to the overseer, queued and
  no longer held, is selectable again, with a card line saying where it was;
  an `applied` row at the same version still decides it.

Synthetic ids and texts; sandbox ledgers; no model call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import batch, ledger_ops, steward, verbs
from self_learn.records import Record
from support import commit_all, git, make_env


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")


def _fact(home: Path, rid: str) -> str:
    """A pending fact, committed; answers its record blob."""
    ledger_ops.create_record(home, Record.create(
        type="knowledge", scope="user", source="teach",
        fact=f"The watch command exits at once before a run exists ({rid}).",
        context="An invented example.", record_id=rid,
    ))
    commit_all(home, f"fact {rid}")
    path = ledger_ops.find_record_path(home, rid)
    return git(home, "rev-parse", f"HEAD:{path.relative_to(home).as_posix()}").stdout.strip()


def _handed_over(home: Path, rid: str, version: str, state: str, run_id: str) -> None:
    disposition = {"input_version": version, "state": state}
    if state == "abandoned":
        disposition.update(successor_case="case-0000feed", reason="no-progress", attempts=3)
    else:
        disposition["case"] = "case-0000feed"
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": run_id,
        "started_at": "2026-11-07T11:00:00Z", "completed_at": "2026-11-07T18:00:00Z",
        "status": "complete", "cases": {},
        "packets": [{
            "index": 1, "inputs": [{"record": rid, "version": version}], "records": [rid],
            "dispositions": {rid: disposition},
        }],
    }, reason=f"a {state} row")


# ------------------------------------------------- 1. the line's own mistake


def test_a_replace_that_makes_a_fact_a_behavior_lesson_with_no_kind_is_a_refused_line(tmp_path):
    home = make_env(tmp_path).ledger
    rid = "lrn-5144a001"
    _fact(home, rid)
    with pytest.raises(verbs.SheetLineError) as refused:
        verbs._preflight_replace(
            home, rid, also=None, trigger="About to watch a run that may not exist yet.",
            instruction="List the runs first.", fact=None, context=None, text_from=None,
            type="behavior", kind=None, to=None, dest=None, rules_paths=None,
            because="it is a rule about one call", note=None, by="steward", actor="steward",
        )
    assert "kind" in str(refused.value)
    assert batch.refusal_kind(refused.value, rc=1, state="refused") == "bad-line"
    # control: the same line with a kind passes the same checks
    verbs._preflight_replace(
        home, rid, also=None, trigger="About to watch a run that may not exist yet.",
        instruction="List the runs first.", fact=None, context=None, text_from=None,
        type="behavior", kind="anti-pattern", to=None, dest=None, rules_paths=None,
        because="it is a rule about one call", note=None, by="steward", actor="steward",
    )


def test_the_batch_preview_reports_that_line_instead_of_raising(tmp_path):
    home = make_env(tmp_path).ledger
    rid = "lrn-5144a002"
    _fact(home, rid)
    sheet = tmp_path / "sheet.yaml"
    sheet.write_text(
        "version: 1\n"
        "items:\n"
        f"  - id: {rid}\n"
        "    verb: replace\n"
        "    type: behavior\n"
        "    trigger: About to watch a run that may not exist yet.\n"
        "    instruction: List the runs first.\n"
        "    because: it is a rule about one call\n",
        encoding="utf-8",
    )
    preview = batch.dry_run(home, batch.load_sheet(sheet), actor="steward")
    (item,) = preview.items
    assert item.state == "would-refuse" and item.kind == "bad-line"
    assert "kind" in (item.detail or "")


# ------------------------------------------ 2. a preview that fails inside


def test_a_failing_ledger_preview_is_a_repair_message_and_a_noted_cause(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    stage = tmp_path / "stage"
    (stage / "cases").mkdir(parents=True)

    def boom(*_args, **_kwargs):
        raise RuntimeError("an invented failure inside the preview")

    monkeypatch.setattr(steward, "_ledger_repair_message", boom)
    monkeypatch.setattr(steward, "_pair_message", lambda check: None)
    monkeypatch.setattr(steward, "_case_rule_message", lambda stage: None)
    # `_StageCheck` needs only `.problems` here.
    check = type("Check", (), {"problems": {}})()
    message = steward._stage_repair_message(home, stage, check, {}, predecessors={})
    assert message is not None and "an invented failure inside the preview" in message
    causes = steward._crashes_since(home, None)
    assert len(causes) == 1 and "an invented failure inside the preview" in causes[0]


def test_a_noted_crash_reaches_the_parked_case_detail_only_for_its_own_run(tmp_path):
    home = make_env(tmp_path).ledger
    steward._note_crash(home, "ValidationError: an invented cause")
    line = json.loads(steward.crash_log_path(home).read_text().splitlines()[0])
    after = {"started_at": "2000-01-01T00:00:00Z"}
    later = {"started_at": "2999-01-01T00:00:00Z"}
    detail = steward._with_crash_causes(home, after, "no-progress")
    assert detail.startswith("no-progress; ") and "an invented cause" in detail
    assert "not a judgment on the lesson" in detail
    assert steward._with_crash_causes(home, later, "no-progress") == "no-progress"
    assert line["cause"] == "ValidationError: an invented cause"


def test_run_notes_the_cause_and_still_raises(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger

    def boom(_home, *, dry_run):
        raise RuntimeError("an invented job failure")

    monkeypatch.setattr(steward, "_run", boom)
    monkeypatch.setattr(steward, "_publish", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        steward.run(home)
    assert any("an invented job failure" in c for c in steward._crashes_since(home, None))


# --------------------------------------- 3. back from the overseer, queued


@pytest.mark.parametrize("state", ["abandoned", "parked"])
def test_a_lesson_the_overseer_left_queued_is_the_stewards_again(tmp_path, state):
    home = make_env(tmp_path).ledger
    rid = "lrn-5144b001"
    version = _fact(home, rid)
    _handed_over(home, rid, version, state, "run-5144000000b1")
    # No parked case holds it (the overseer's decision superseded that case)
    # and it is still queued at the same version.
    eligible = steward._eligible_lessons(home)
    assert [entry.record.id for entry, _row in eligible] == [rid]
    reason = eligible[0][1]["reason"]
    assert "run-5144000000b1" in reason and state in reason and "yours again" in reason
    assert steward.stranded_lessons(home) == []


def test_an_applied_row_at_the_same_version_still_decides_it(tmp_path):
    """The control for the test above: only a hand-over is undone."""
    home = make_env(tmp_path).ledger
    rid = "lrn-5144b002"
    version = _fact(home, rid)
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": "run-5144000000b2",
        "started_at": "2026-11-07T11:00:00Z", "completed_at": "2026-11-07T18:00:00Z",
        "status": "complete",
        "cases": {"case-0000cade": {"items": [{"id": rid, "n": 1, "verb": "reject"}]}},
        "packets": [{
            "index": 1, "inputs": [{"record": rid, "version": version}], "records": [rid],
            "dispositions": {rid: {"case": "case-0000cade", "input_version": version,
                                   "state": "applied"}},
        }],
    }, reason="an applied row")
    assert steward._eligible_lessons(home) == []
    assert [row.record for row in steward.stranded_lessons(home)] == [rid]


def test_a_lesson_the_overseer_still_holds_is_not_selected(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    rid = "lrn-5144b003"
    version = _fact(home, rid)
    _handed_over(home, rid, version, "abandoned", "run-5144000000b3")
    monkeypatch.setattr(
        steward.cases, "held_lessons",
        lambda h: {rid: [{"case": "case-0000feed", "parked_reason": "attempts-exhausted"}]},
    )
    assert steward._eligible_lessons(home) == []
