"""Fail-state batch 1, the overseer's units (2026-09-27).

The user's words, 06:58: "Make the fix. Look for any other similarly
outlandish fail states." The audit (findings 1, 5 and 7) found runs where
one bad item cost the whole run, or a run that crashed without counting.
The rule the user has now accepted three times: a bad item costs that item
(dropped or refused with a traced reason), not the unit around it.

Every scenario runs on a pytest sandbox ledger with fake model sessions;
the ids and texts are synthetic.
"""

from __future__ import annotations

import time

import pytest

from self_learn import cases, execution_evidence
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
from support import commit_all, make_behavior, make_home
from test_overseer_run import _dump, _enabled


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


HEADINGS = [
    "Examined", "Decided in the user's stead", "Hooks", "User model",
    "Catalogue health", "Questions for you", "Refused / could not do",
]


def _phase_b_common(stage):
    (stage / "report.md").write_text(
        "# draft\n" + "\n".join(f"## {h}\n- none" for h in HEADINGS) + "\n", encoding="utf-8"
    )
    _dump(stage / "findings.yaml", {"findings": []})
    _dump(stage / "questions.yaml", {"questions": []})
    _dump(stage / "user-model-delta.yaml", {"updates": []})


def _phase_a(stage):
    _dump(stage / "selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "empty"})
    _dump(stage / "initial-views.yaml", {"cases": []})


def _ok():
    return type("SdkLike", (), {
        "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
    })()


def _seed_parked(home, tmp_path, rid, name):
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, f"seed {rid}")
    path = tmp_path / f"{name}.yaml"
    _dump(path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "decide this?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    return cases.record(home, path, actor="steward")


def _successor(rid, parked, confidence="settled", because="narrow"):
    return {
        "kind": "resolution", "trigger": "weekly", "outcome": "reject",
        "records": [rid], "scope": "skill:s", "question": "keep?",
        "supersedes": parked,
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "reject", "because": because, "confidence": confidence},
    }


def _status(home, rid):
    return Record.from_path(find_record_path(home, rid)).status


def _two_parked(home, tmp_path):
    rid_a, rid_b = "lrn-0a000001", "lrn-0b000002"
    parked_a = _seed_parked(home, tmp_path, rid_a, "pa")
    parked_b = _seed_parked(home, tmp_path, rid_b, "pb")
    return rid_a, parked_a, rid_b, parked_b


def _stage_two_successors(stage, rid_a, case_a, rid_b, case_b):
    _phase_b_common(stage)
    _dump(stage / "case-a.yaml", case_a)
    _dump(stage / "sheet-a.yaml", {"version": 1, "items": [{"id": rid_a, "verb": "reject"}]})
    _dump(stage / "case-b.yaml", case_b)
    _dump(stage / "sheet-b.yaml", {"version": 1, "items": [{"id": rid_b, "verb": "reject"}]})


# ------------------------------------------------------------ unit 1


def test_a_successor_the_case_writer_refuses_is_dropped_at_phase_b_and_the_rest_applies(
    tmp_path, monkeypatch
):
    """Audit finding 1 (`test_O2_…`): `confidence: high` is outside the
    case writer's closed set. Before: the run halted at that case on every
    resume and case-b never applied. Now case-a is dropped at phase B with
    a traced line, and case-b applies in the same run."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _stage_two_successors(
                stage, rid_a, _successor(rid_a, parked_a, confidence="high"),
                rid_b, _successor(rid_b, parked_b),
            )
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)

    # Positive control first: the good case landed and the run finished.
    assert _status(home, rid_b) != "pending"
    assert not overseer_run.has_unfinished_work(home)
    assert result.status in {"applied", "partial"}
    # The bad case cost only itself: its lesson is untouched, its parked
    # case is still open, and the report names the file and the rule.
    assert _status(home, rid_a) == "pending"
    parked_rows = {row["case"]: row for row in cases.list_cases(home, parked_for="overseer")}
    assert not parked_rows[parked_a].get("superseded_by")
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.split("## Refused / could not do", 1)[1]
    assert f"case-a.yaml (successor for {parked_a}): dropped with sheet-a.yaml" in refused
    assert "decision.confidence must be one of" in refused
    # The model's own value never reaches the committed line.
    assert "'high'" not in refused


def test_a_case_the_writer_refuses_at_execute_time_is_refused_alone(tmp_path, monkeypatch):
    """A case that passes phase B but that `cases.record` still refuses at
    execute time (here: a reserved-id refusal the phase-B check cannot see)
    refuses that case and its sheet; the next case still applies, the run
    completes, and a resume has nothing left to do."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _stage_two_successors(
                stage, rid_a, _successor(rid_a, parked_a), rid_b, _successor(rid_b, parked_b),
            )
        return _ok()

    real_record = cases.record

    def record(home_arg, stage_file, *, actor, reserved_id=None):
        text = open(stage_file, encoding="utf-8").read()
        if actor == "overseer" and rid_a in text:
            raise cases.CaseError(f"case record: reserved id collision for {reserved_id}")
        return real_record(home_arg, stage_file, actor=actor, reserved_id=reserved_id)

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    monkeypatch.setattr(cases, "record", record)
    result = overseer_run.run(home, no_push=True)

    # Positive control: case-b (after case-a in the run's order) applied.
    assert _status(home, rid_b) != "pending"
    assert _status(home, rid_a) == "pending"
    assert result.status == "partial" and result.code == overseer_run.EXIT_PARTIAL
    # Not halted: the run record is complete, nothing is left to resume.
    assert not overseer_run.has_unfinished_work(home)
    manifest = execution_evidence.read_manifest(home, result.run, at="HEAD")
    assert manifest["status"] == "complete"
    rows = [
        row for recipe in manifest["cases"].values()
        if recipe["sheet_name"] == "sheet-a.yaml"
        for row in recipe["dispositions"]
    ]
    assert rows and all(row["state"] == "refused" for row in rows)
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "case-a.yaml (successor " in report and "refused by the case writer" in report
