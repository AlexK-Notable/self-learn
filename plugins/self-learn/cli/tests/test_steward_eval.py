"""U11: nine decision-shape fixtures exercised through steward dry-run."""

from __future__ import annotations

import copy
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from self_learn import batch, ledger_ops, steward
from self_learn.invocation.contract import Outcome
from self_learn.ledger_ops import create_record
from support import commit_all, make_behavior, make_home, proposal_dict


FIXTURES = Path(__file__).parent / "fixtures" / "steward-cases" / "cases.yaml"


def _load_fixtures() -> list[dict[str, Any]]:
    data = YAML(typ="safe").load(FIXTURES.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("fixtures"), list)
    return [dict(row) for row in data["fixtures"]]


FIXTURE_ROWS = _load_fixtures()


def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    YAML().dump(data, stream)
    path.write_text(stream.getvalue(), encoding="utf-8")


def _substitute(value: Any, ids: list[str]) -> Any:
    if isinstance(value, str):
        for index, record_id in enumerate(ids, start=1):
            value = value.replace(f"$RID{index}", record_id)
        return value
    if isinstance(value, list):
        return [_substitute(item, ids) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, ids) for key, item in value.items()}
    return value


def _seed(home: Path, fixture: dict[str, Any]) -> list[str]:
    ids = [f"lrn-{index:08x}" for index in range(1, int(fixture["inputs"]) + 1)]
    for record_id in ids:
        create_record(home, make_behavior(record_id=record_id))
        ledger_ops.write_proposal(home, record_id, proposal_dict())
        ledger_ops.stamp_proposal(home, record_id)
    commit_all(home, f"seed {fixture['id']}")
    return ids


def _case_document(fixture: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    case = {
        "kind": fixture["kind"],
        "trigger": fixture.get("trigger", "nightly"),
        "outcome": fixture["outcome"],
        "records": ids,
        "scope": "skill:s",
        "question": f"what should the steward do for {fixture['id']}?",
        "evidence": fixture["evidence"],
        "decision": {
            "verb": fixture["outcome"],
            "because": "the recorded fixture evidence determines this shape",
            "confidence": "provisional" if fixture["kind"] == "parked" else "settled",
        },
        "dependencies": fixture["dependencies"],
    }
    for key in ("supersedes", "parked_for", "parked_reason"):
        if key in fixture:
            case[key] = fixture[key]
    return _substitute(case, ids)


def _backend(fixture: dict[str, Any], ids: list[str], captured: dict[str, Path]):
    def write(spec):
        match = re.search(
            r"^stage directory \(the only place you may write\): (.+)$",
            spec.prompt,
            re.MULTILINE,
        )
        assert match is not None
        stage = Path(match.group(1))
        captured["stage"] = stage
        _dump(stage / "cases" / "decision.yaml", _case_document(fixture, ids))
        _dump(
            stage / "sheets" / "decision.yaml",
            {"version": 1, "case": "$CASE_ID", "items": _substitute(fixture["sheet"], ids)},
        )
        if fixture.get("model_updates"):
            _dump(
                stage / "model-updates.yaml",
                {"items": _substitute(fixture["model_updates"], ids)},
            )
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def _assert_shape(fixture: dict[str, Any], case: dict[str, Any], sheet: dict[str, Any], stage: Path) -> None:
    expected = fixture["expect"]
    items = sheet["items"]
    verbs = [item["verb"] for item in items]
    destinations = [item.get("dest") for item in items if "dest" in item]
    assert verbs == expected["verbs"]
    if "advised_verb" in expected:
        assert verbs[-1] == expected["advised_verb"]
    assert not set(expected.get("forbidden_verbs", [])) & set(verbs)
    if "destinations" in expected:
        assert destinations == expected["destinations"]
    assert not set(expected.get("forbidden_destinations", [])) & set(destinations)
    if "record_count" in expected:
        assert len(case["records"]) == expected["record_count"]
    if "evidence_count" in expected:
        assert len(case["evidence"]) == expected["evidence_count"]
    evidence_refs = {row["ref"] for row in case["evidence"]}
    assert set(expected.get("evidence_refs", [])) <= evidence_refs
    assert set(case["dependencies"]) == {
        "statements", "user_model", "conditions", "capabilities"
    }
    assert case["dependencies"] == fixture["dependencies"]
    conditions = case["dependencies"]["conditions"]
    assert conditions == expected.get("conditions", conditions)
    assert not set(expected.get("forbidden_conditions", [])) & set(conditions)
    if "supersedes" in expected:
        assert case.get("supersedes") == expected["supersedes"]
    if "model_source" in expected:
        updates = YAML(typ="safe").load(
            (stage / "model-updates.yaml").read_text(encoding="utf-8")
        )["items"]
        assert updates[0]["source"] == expected["model_source"]
        assert updates[0]["container"] == expected["model_container"]
        assert updates[0]["held_since"] == expected["model_held_since"]
        assert updates[0]["conditions"] == expected["model_conditions"]
    if expected.get("runner_recompile"):
        assert verbs[-1] in batch._HOST_OUTCOME_VERBS


def _mutate(fixture: dict[str, Any], case: dict[str, Any], sheet: dict[str, Any], stage: Path) -> None:
    mutation = fixture["mutation"]
    if mutation == "drop-first-sheet-item":
        sheet["items"].pop(0)
    elif mutation == "replace-declared-with-observed":
        case["dependencies"]["conditions"] = ["host.demo.claude-md"]
    elif mutation == "add-declared-condition":
        case["dependencies"]["conditions"].append("declared.host.demo.claude-md")
    elif mutation == "drop-host-condition":
        case["dependencies"]["conditions"] = []
    elif mutation == "drop-transcript-evidence":
        case["evidence"] = [row for row in case["evidence"] if not row["ref"].startswith("transcript:")]
    elif mutation == "add-recurrence":
        sheet["items"].append({"id": case["records"][0], "verb": "confirm-recurrence"})
    elif mutation == "force-skill-destination":
        sheet["items"][0]["dest"] = "new-skill"
    elif mutation == "make-own-words":
        updates_path = stage / "model-updates.yaml"
        updates = YAML(typ="safe").load(updates_path.read_text(encoding="utf-8"))
        updates["items"][0]["source"] = "own-words"
        _dump(updates_path, updates)
    elif mutation == "remove-supersedes":
        case.pop("supersedes")
    else:  # pragma: no cover - fixture registry is closed by this assertion
        raise AssertionError(f"unknown mutation {mutation}")


@pytest.mark.parametrize("fixture", FIXTURE_ROWS, ids=lambda row: row["id"])
def test_steward_decision_shape_and_named_mutation(fixture, tmp_path, monkeypatch) -> None:
    home = make_home(tmp_path)
    ids = _seed(home, fixture)
    captured: dict[str, Path] = {}
    monkeypatch.setattr(steward.invocation, "write_session", _backend(fixture, ids, captured))

    result = steward.run(home, dry_run=True)

    assert result.status == "dry-run"
    assert result.calls == 1
    stage = captured["stage"]
    run_dir = stage.parents[1]
    projected = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert projected["actor"] == "steward"
    assert projected["status"] == "dry-run"
    assert projected["packets"][0]["records"] == ids
    expected_stage_files = {"cases/decision.yaml", "sheets/decision.yaml"}
    if fixture.get("model_updates"):
        expected_stage_files.add("model-updates.yaml")
    assert {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file()
    } == expected_stage_files
    case = YAML(typ="safe").load((stage / "cases" / "decision.yaml").read_text(encoding="utf-8"))
    sheet = YAML(typ="safe").load((stage / "sheets" / "decision.yaml").read_text(encoding="utf-8"))
    _assert_shape(fixture, case, sheet, stage)

    mutated_case = copy.deepcopy(case)
    mutated_sheet = copy.deepcopy(sheet)
    _mutate(fixture, mutated_case, mutated_sheet, stage)
    with pytest.raises(AssertionError):
        _assert_shape(fixture, mutated_case, mutated_sheet, stage)
