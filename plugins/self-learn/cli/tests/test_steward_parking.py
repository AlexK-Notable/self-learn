"""A lesson the steward's MODEL parks, and a lesson a case forgets.

Both found 2026-09-20 while writing down, for the steward's brief, how
its files work -- and both by running the real runner, not by reading.

1. Parking. `steward-method.md` section 12 tells the model to park a
   lesson it cannot decide alone: a case whose `kind` is `parked`, with
   the reason that stopped it. Until this fix the runner took a parking
   reason only from its own two checks (a route to a hook; a route into a
   plain-mode host's committed file), so a case the model parked was
   recorded as a question for the overseer AND had its sheet applied in
   the same run: the lesson was deferred, and reported as decided. One
   existing test did stage a model-chosen park, as a side control
   (`test_steward.py::test_a_model_written_runner_only_parked_reason_is_a_
   schema_failure`), and it had pinned the defect: it asserted the parked
   lesson came out `decided`. (The real run of 2026-09-19 parked none of
   its 29 lessons, which is the only reason it had not happened live.)

2. A forgotten lesson. The runner dispositions every lesson of a finished
   case `applied`. A lesson listed in a case's `records` with no item on
   the sheet was therefore recorded as handled with nothing done to it --
   seen once in that same real run (a two-lesson case, one item).

The user chose both fixes on 2026-09-20.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ruamel.yaml import YAML

from self_learn import cases, ledger_ops, steward
from self_learn.ledger_ops import find_record_path
from self_learn.records import Record

from support import make_home
from test_steward import _dump_yaml, _enable_steward, _seed_fresh_proposals, _write_decision_stage


def _stage_of(spec) -> Path:
    match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
    assert match is not None
    return Path(match.group(1))


def _edit_yaml(path: Path, **changes) -> None:
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    data.update(changes)
    _dump_yaml(path, data)


def _packet(home) -> dict:
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    return json.loads(record.read_text(encoding="utf-8"))["packets"][0]


def _status(home, rid: str) -> str:
    return Record.from_path(find_record_path(home, rid)).status


def _run_with(home, monkeypatch, rewrite) -> tuple[object, list]:
    """Stub the model: the ordinary two-reject stage, then `rewrite(stage)`
    changes what this test is about. Returns the run result and every
    session the runner asked for (a repair turn is a second one)."""
    calls: list = []

    def invoke(spec):
        calls.append(spec)
        outcome = _write_decision_stage(spec)
        rewrite(_stage_of(spec))
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", invoke)
    return steward.run(home, dry_run=False), calls


# ----------------------------------------------------------------- parking


def test_a_lesson_the_model_parks_is_handed_to_the_overseer_and_nothing_is_done_to_it(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)

    def park_the_second(stage: Path) -> None:
        _edit_yaml(stage / "cases" / f"{ids[1]}.yaml", kind="parked", outcome="parked",
                   parked_for="overseer", parked_reason="authority-unclear")
        # its sheet keeps the `reject` item: the model's tentative answer

    result, calls = _run_with(home, monkeypatch, park_the_second)

    assert len(calls) == 1  # valid as staged: no repair turn
    # The control: the OTHER lesson in the same batch really was applied,
    # so "still pending" below is not just a run that did nothing.
    assert _status(home, ids[0]) == "rejected"
    # The parked lesson: nothing done to it ...
    assert _status(home, ids[1]) == "pending"
    assert [row["id"] for row in ledger_ops.list_items(home)] == [ids[1]]
    # ... a question for the overseer, with the model's own reason ...
    (parked,) = cases.list_cases(home, parked_for="overseer")
    assert parked["parked_reason"] == "authority-unclear"
    assert cases.show(home, parked["case"], evidence_only=False).frontmatter["records"] == [ids[1]]
    # ... its tentative answer on record as parked, not applied ...
    application = cases.show(home, parked["case"], evidence_only=False).sections["Application"]
    assert "parked" in application and "reject" in application
    # ... and the batch is finished, not left open for a retry.
    packet = _packet(home)
    assert packet["phase"] == "complete"
    assert packet["dispositions"][ids[1]]["state"] == "parked"
    assert packet["dispositions"][ids[0]]["state"] == "applied"
    assert ids[1] not in result.decided


def test_a_parked_case_without_a_reason_the_model_may_choose_gets_the_repair_turn(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)

    def park_with_no_reason(stage: Path) -> None:
        _edit_yaml(stage / "cases" / f"{ids[1]}.yaml", kind="parked", outcome="parked", parked_for="overseer")

    _result, calls = _run_with(home, monkeypatch, park_with_no_reason)

    assert len(calls) == 2  # the one repair turn was spent on it
    packet = _packet(home)
    assert packet["failure"] == "schema-repair"
    assert "a parked case needs parked_reason" in packet["failure_detail"]
    assert "authority-unclear" in packet["failure_detail"]  # the error names what it may be
    assert [_status(home, rid) for rid in ids] == ["pending", "pending"]  # nothing half-applied
    assert cases.list_cases(home, parked_for="overseer") == []


def test_parking_fields_on_a_case_that_is_not_parked_get_the_repair_turn(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)

    def reason_without_parking(stage: Path) -> None:
        _edit_yaml(stage / "cases" / f"{ids[1]}.yaml", parked_reason="authority-unclear")

    _result, calls = _run_with(home, monkeypatch, reason_without_parking)

    assert len(calls) == 2
    assert "only for a case whose kind is parked" in _packet(home)["failure_detail"]
    assert [_status(home, rid) for rid in ids] == ["pending", "pending"]


# ------------------------------------------------- a lesson with no sheet item


def _merge_into_one_case(stage: Path, ids: list[str], *, items: list[str]) -> None:
    """Both lessons under the first lesson's case; its sheet carries an
    item for each id in `items`."""
    (stage / "cases" / f"{ids[1]}.yaml").unlink()
    (stage / "sheets" / f"{ids[1]}.yaml").unlink()
    _edit_yaml(stage / "cases" / f"{ids[0]}.yaml", records=list(ids))
    _edit_yaml(stage / "sheets" / f"{ids[0]}.yaml", items=[{"id": rid, "verb": "reject"} for rid in items])


def test_a_lesson_a_case_covers_but_its_sheet_forgets_gets_the_repair_turn(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)

    _result, calls = _run_with(
        home, monkeypatch, lambda stage: _merge_into_one_case(stage, ids, items=[ids[0]])
    )

    assert len(calls) == 2
    packet = _packet(home)
    assert packet["failure"] == "schema-repair"
    assert "every lesson in a case needs its own item" in packet["failure_detail"]
    assert ids[1] in packet["failure_detail"] and f"'{ids[0]}'" not in packet["failure_detail"]
    # Before the fix this read ['rejected', 'pending'] with BOTH lessons
    # dispositioned `applied`.
    assert [_status(home, rid) for rid in ids] == ["pending", "pending"]
    assert {row["state"] for row in packet["dispositions"].values()} == {"unfinished"}


def test_a_case_that_gives_each_of_its_lessons_an_item_is_applied(tmp_path, monkeypatch):
    """The control for the test above: two lessons in one case is fine."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)

    result, calls = _run_with(
        home, monkeypatch, lambda stage: _merge_into_one_case(stage, ids, items=list(ids))
    )

    assert len(calls) == 1
    assert [_status(home, rid) for rid in ids] == ["rejected", "rejected"]
    assert sorted(result.decided) == sorted(ids)
