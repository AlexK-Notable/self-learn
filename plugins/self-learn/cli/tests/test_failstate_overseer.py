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


# ------------------------------------------------------------ unit 5


def _week():
    return overseer_run.week_key(overseer_run.week_boundary(time.time()))


def test_an_orphan_sheet_is_dropped_and_its_sibling_applies(tmp_path, monkeypatch):
    """Audit finding 5 (`test_O1_…`): `sheet-x.yaml` with no `case-x.yaml`
    raised after phase A, outside every handler: uncounted, repeated every
    two hours. Now that sheet is dropped with a trace and the valid pair
    beside it applies."""
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
            (stage / "case-a.yaml").unlink()  # sheet-a.yaml is now an orphan
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)
    assert _status(home, rid_b) != "pending"  # the sibling applied
    assert _status(home, rid_a) == "pending"
    assert not overseer_run.has_unfinished_work(home)
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "sheet-a.yaml: dropped — no case-a.yaml beside it" in report
    assert result.status in {"applied", "partial"}


def test_a_stage_holding_only_an_orphan_sheet_is_a_counted_refusal(tmp_path, monkeypatch):
    """The probe's exact shape: the only sheet is an orphan. The run is
    refused through the ordinary failure path -- a committed note that
    counts -- instead of raising uncounted."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "sheet-x.yaml", {"version": 1, "items": []})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    before = overseer_run.week_attempts(home, _week())
    result = overseer_run.run(home, no_push=True)
    assert result.status == "refused"
    assert overseer_run.week_attempts(home, _week()) == before + 1


def test_a_case_that_cannot_be_classified_is_left_out_of_coverage(tmp_path, monkeypatch):
    """Audit finding 5 (`test_O3_…`): a case in the window whose first
    cited record is gone has no usable scope_kind; `coverage_update`
    raised for it after phase A, uncounted. Now that one row is left out of
    coverage with a trace and the run completes."""
    import glob
    import os
    import subprocess

    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid = "lrn-0c000003"
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, "seed")
    path = tmp_path / "decided.yaml"
    _dump(path, {
        "kind": "resolution", "trigger": "nightly", "outcome": "reject",
        "records": [rid], "scope": "skill:s", "question": "keep?",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "reject", "because": "narrow", "confidence": "settled"},
    })
    orphaned = cases.record(home, path, actor="steward")
    subprocess.run(["git", "-C", str(home), "rm", "-q", str(find_record_path(home, rid))], check=True)
    commit_all(home, "record gone")
    for idx in glob.glob(os.path.join(os.environ["XDG_CACHE_HOME"], "**", "index.json"), recursive=True):
        os.unlink(idx)
    calls = []

    def invoke(spec):
        calls.append(spec.label)
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "sheet.yaml", {"version": 1, "items": []})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)
    assert calls == ["phase-a", "phase-b"]
    assert result.status == "applied"
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert f"case {orphaned}: left out of coverage" in report


@pytest.mark.parametrize("step", ["_full_inputs", "_prepare_manifest"])
def test_a_step_after_phase_a_that_raises_is_a_counted_refusal(tmp_path, monkeypatch, step):
    """`_full_inputs` and `_prepare_manifest` sat outside every handler: a
    raise escaped the run with no note and no count. Now it commits a
    failure note that counts, and coverage is put back."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "sheet.yaml", {"version": 1, "items": []})
        return _ok()

    def broken(*args, **kwargs):
        raise overseer_run.OverseerError("synthetic failure")

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    monkeypatch.setattr(overseer_run, step, broken)
    before = overseer_run.week_attempts(home, _week())
    result = overseer_run.run(home, no_push=True)
    assert result.status == "refused"
    assert overseer_run.week_attempts(home, _week()) == before + 1
    assert not (home / "overseer" / "coverage.yaml").exists()
    (note,) = overseer_run._committed_failure_notes(home, _week())
    assert "synthetic failure" in (home / note).read_text(encoding="utf-8")


# ------------------------------------------------------------ unit 7


def _timed_out():
    from self_learn.invocation.contract import Outcome
    return Outcome(ok=False, rc=None, stdout="", detail="", failure="timeout")


def test_the_phase_time_limit_grows_with_the_population():
    """`max(overseer.timeout_secs, 30 s x cases)`: the floor for a small
    week; for the 57 cases of 2026-09-27 (810 s against a flat 900 s)
    1710 s."""
    assert overseer_run.phase_timeout(900.0, 0) == 900.0
    assert overseer_run.phase_timeout(900.0, 30) == 900.0
    assert overseer_run.phase_timeout(900.0, 57) == 1710.0


def test_each_phase_is_given_the_scaled_limit(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)
    monkeypatch.setattr(overseer_run, "TIMEOUT_PER_CASE_SECS", 1000.0)
    timeouts = {}

    def invoke(spec):
        timeouts[spec.label] = spec.timeout
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "sheet.yaml", {"version": 1, "items": []})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    overseer_run.run(home, no_push=True)
    # The week holds the two parked cases (phase A reads 2); phase B reads
    # them again as the parked queue (4).
    assert timeouts == {"phase-a": 2000.0, "phase-b": 4000.0}


def test_a_timed_out_phase_b_that_wrote_its_files_is_applied(tmp_path, monkeypatch):
    """Audit finding 7: a phase B that timed out kept nothing, however much
    it had written. Now a phase B that wrote every file a run needs is
    checked like a finished one, and what passes applies."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
            return _ok()
        _stage_two_successors(
            spec.cwd, rid_a, _successor(rid_a, parked_a), rid_b, _successor(rid_b, parked_b),
        )
        return _timed_out()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)
    assert _status(home, rid_a) != "pending" and _status(home, rid_b) != "pending"
    assert not overseer_run.has_unfinished_work(home)
    assert result.status in {"applied", "partial"}
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "phase B timed-out (timeout); what it had written was checked" in report


def test_a_validated_phase_a_is_kept_for_the_weeks_next_attempt(tmp_path, monkeypatch):
    """Phase B times out having written nothing usable: that attempt is a
    counted refusal as before, but its validated phase A is kept, and the
    week's next attempt -- the population unchanged -- goes straight to
    phase B."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)
    labels = []

    def invoke(spec):
        labels.append(spec.label)
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
            return _ok()
        if labels.count("phase-b") == 1:
            return _timed_out()
        _stage_two_successors(
            spec.cwd, rid_a, _successor(rid_a, parked_a), rid_b, _successor(rid_b, parked_b),
        )
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    first = overseer_run.run(home, no_push=True)
    assert first.status == "timed-out"
    assert overseer_run.week_attempts(home, _week()) == 1
    second = overseer_run.run(home, no_push=True)
    assert labels == ["phase-a", "phase-b", "phase-b"]
    assert second.status in {"applied", "partial"}
    assert _status(home, rid_b) != "pending"


def test_a_kept_phase_a_is_not_used_for_a_changed_population(tmp_path, monkeypatch):
    """Control: a case opened between the attempts changes the population,
    so phase A is made again."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    labels = []

    def invoke(spec):
        labels.append(spec.label)
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
            return _ok()
        return _timed_out()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    overseer_run.run(home, no_push=True)
    _seed_parked(home, tmp_path, "lrn-0d000004", "pd")  # a new case in the window
    overseer_run.run(home, no_push=True)
    assert labels == ["phase-a", "phase-b", "phase-a", "phase-b"]


# ------------------------------------------------ unparseable stage files
# 2026-09-27, run c2b9192b: findings.yaml held a plain `text:` value with
# ": " in it, did not parse, and the whole run was refused with its three
# decided cases unapplied. A file that does not parse now costs only what
# it carries. The marker sits on the offending line itself, so the
# parser's own message (which quotes the source around the error) would
# carry it: its absence below is not vacuous.

MARKER = "MARKER-7Q"
UNPARSEABLE_FINDINGS = (
    "findings:\n"
    "  - case: case-00000000\n"
    "    kind: examined\n"
    f"    text: {MARKER} held: the decision stands\n"
)
UNPARSEABLE_CASE = (
    "kind: resolution\n"
    f"question: {MARKER} keep it: yes or no\n"
)


def test_a_findings_file_that_does_not_parse_costs_only_the_findings(tmp_path, monkeypatch):
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
            (stage / "findings.yaml").write_text(UNPARSEABLE_FINDINGS, encoding="utf-8")
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)

    # Both decided sheets applied: the run was not refused.
    assert result.status == "applied", result
    assert _status(home, rid_a) != "pending" and _status(home, rid_b) != "pending"
    assert not overseer_run.has_unfinished_work(home)
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.split("## Refused / could not do", 1)[1]
    line = (
        "findings.yaml: cannot parse — mapping values are not allowed here "
        "at line 4, column 25: every finding dropped"
    )
    assert line in refused
    manifest = execution_evidence.read_manifest(home, result.run, at="HEAD")
    assert line in manifest["runner_notes"]
    assert MARKER not in report
    assert MARKER not in str(manifest)


def test_a_case_file_that_does_not_parse_costs_only_its_pair(tmp_path, monkeypatch):
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
            (stage / "case-a.yaml").write_text(UNPARSEABLE_CASE, encoding="utf-8")
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)

    # Positive control: the other pair applied and the run finished.
    assert _status(home, rid_b) != "pending"
    assert result.status in {"applied", "partial"}, result
    assert not overseer_run.has_unfinished_work(home)
    # The unparseable pair cost itself: lesson untouched, parked case open.
    assert _status(home, rid_a) == "pending"
    parked_rows = {row["case"]: row for row in cases.list_cases(home, parked_for="overseer")}
    assert not parked_rows[parked_a].get("superseded_by")
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.split("## Refused / could not do", 1)[1]
    assert (
        "case-a.yaml: cannot parse — mapping values are not allowed here "
        "at line 2, column 28: dropped with sheet-a.yaml"
    ) in refused
    assert MARKER not in report


def test_a_user_model_delta_that_does_not_parse_costs_only_the_updates(tmp_path, monkeypatch):
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
            (stage / "user-model-delta.yaml").write_text(
                f"updates:\n  - action: add\n    because: {MARKER} said: so\n", encoding="utf-8",
            )
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)

    assert result.status == "applied", result
    assert _status(home, rid_a) != "pending" and _status(home, rid_b) != "pending"
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.split("## Refused / could not do", 1)[1]
    assert "user-model-delta.yaml: cannot parse — mapping values are not allowed here" in refused
    assert ": no user-model updates this run" in refused
    assert MARKER not in report
