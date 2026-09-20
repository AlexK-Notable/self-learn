"""U10 -- crash-safe steward runner and its CLI/scheduler surfaces."""

from __future__ import annotations

import fcntl
import io
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from ruamel.yaml import YAML
import pytest

from self_learn import cli as cli_mod
from self_learn import (
    cases,
    gitops,
    intents,
    ledger_ops,
    provider,
    serve,
    settings,
    statements,
    steward,
    user_model,
    verbs,
)
from self_learn.ledger_ops import create_record
from self_learn.invocation.contract import Outcome
# the shipped notification helper, patched HERE rather than through
# `steward.overseer_notify`, so these tests reach their behavioural
# assertions on a build that has not wired the steward to it yet
from self_learn.overseer import notify as overseer_notify
from self_learn.invocation_sdk.backend import SdkOutcome
from self_learn.records import Record
from test_recover_or_refuse import _plant_stop
from support import commit_all, git, make_behavior, make_home, proposal_dict


def _seed_fresh_proposals(home: Path, count: int, offset: int = 0) -> list[str]:
    ids = []
    for n in range(count):
        rid = f"lrn-{n + 1 + offset:08x}"
        create_record(home, make_behavior(record_id=rid))
        ledger_ops.write_proposal(home, rid, proposal_dict())
        ledger_ops.stamp_proposal(home, rid)
        ids.append(rid)
    commit_all(home, "seed steward queue")
    return ids


def _enable_steward(home: Path) -> None:
    (home / "config.yaml").write_text("steward:\n  enabled: true\n", encoding="utf-8")
    commit_all(home, "enable steward")


def _configure_steward(home: Path, *, packet_size: int = 10) -> None:
    (home / "config.yaml").write_text(
        f"steward:\n  enabled: true\n  packet_size: {packet_size}\n",
        encoding="utf-8",
    )
    commit_all(home, "configure steward")


def _dump_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    buf = io.StringIO()
    yaml.dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


def _write_decision_stage(spec, *, turns: int | None = None):
    match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
    assert match is not None
    stage = Path(match.group(1))
    ids = re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M)
    for rid in ids:
        _dump_yaml(
            stage / "cases" / f"{rid}.yaml",
            {
                "kind": "resolution",
                "trigger": "nightly",
                "outcome": "reject",
                "records": [rid],
                "scope": "skill:s",
                "question": "should this pending lesson become standing guidance?",
                "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
                "decision": {
                    "verb": "reject",
                    "because": "the evidence does not support a standing rule",
                    "confidence": "settled",
                },
                "dependencies": {
                    "statements": [],
                    "user_model": [],
                    "conditions": [],
                    "capabilities": [],
                },
            },
        )
        _dump_yaml(
            stage / "sheets" / f"{rid}.yaml",
            {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]},
        )
    if turns is None:
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)
    return SdkOutcome(ok=True, rc=0, stdout="", detail="", failure=None, turns=turns)


def _write_hook_stage(spec):
    outcome = _write_decision_stage(spec)
    match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
    assert match is not None
    stage = Path(match.group(1))
    sheet = next((stage / "sheets").glob("*.yaml"))
    data = YAML(typ="safe").load(sheet.read_text(encoding="utf-8"))
    data["items"][0] = {"id": data["items"][0]["id"], "verb": "route", "dest": "hook"}
    _dump_yaml(sheet, data)
    case = next((stage / "cases").glob("*.yaml"))
    case_data = YAML(typ="safe").load(case.read_text(encoding="utf-8"))
    case_data["outcome"] = "route"
    case_data["decision"]["verb"] = "route"
    _dump_yaml(case, case_data)
    return outcome


# ------------------------------------------------ S-68 shared helpers


def _head_manifest(home: Path, run_id: str) -> dict:
    """The run record from COMMITTED truth, never the cache projection."""
    return json.loads(git(home, "show", f"HEAD:cases/runs/{run_id}.json").stdout)


def _stage_dir(spec) -> Path:
    match = re.search(
        r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M
    )
    assert match is not None
    return Path(match.group(1))


def _transport_failure(spec):
    """The 2026-09-14 shape: the transport returned a message, the run
    committed only its kind (`exit`)."""
    return Outcome(
        ok=False,
        rc=1,
        stdout="",
        detail="API Error: 400 this build does not support the selected model",
        failure="exit",
    )


def _invalid_schema_stage(spec):
    outcome = _write_decision_stage(spec)
    sheet = next((_stage_dir(spec) / "sheets").glob("*.yaml"))
    _dump_yaml(sheet, {"version": 1, "unexpected": []})
    return outcome


def _failing_receipt(*args, **kwargs):
    """`batch.write_receipt` NEVER raises; it reports a failed write by
    returning this (A20). That is what used to mark the CASE unfinished
    while the PACKET was stamped complete over it.

    Paired with `_write_hook_stage`: a hook route is parked, so its
    receipt is written DIRECTLY by the runner and never through
    `batch.run`'s ordered checkpoint (which halts loudly on a non-ok
    return and is therefore not this defect)."""
    return {"state": "failed", "pushed": None}


def _iso_epoch(stamp: str) -> float:
    return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()


def test_steward_settings_are_registered_with_safe_defaults():
    assert settings.by_name("steward.packet_size").default == 10
    cooldown = settings.by_name("steward.cooldown_secs")
    assert cooldown.default == 72000
    assert cooldown.validate_hint == "must be >= 0"
    enabled = settings.by_name("steward.enabled")
    assert enabled.default is False
    assert enabled.env_var is None


def test_disabled_runner_recovers_first_then_writes_one_status_line(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    order = []
    monkeypatch.setattr(
        steward.intents,
        "recover",
        lambda actual: order.append("recover") or intents.RecoverResult(),
    )
    monkeypatch.setattr(
        steward.invocation,
        "write_session",
        lambda spec: (_ for _ in ()).throw(AssertionError("disabled runner invoked a session")),
    )

    result = steward.run(home)

    assert result.status == "disabled" and order == ["recover"]
    lines = steward.journal_path(home).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["status"] == "disabled"


def test_held_steward_lock_is_idle_without_a_session(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    lock_path = steward.cache_dir(home) / "steward.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        steward.invocation,
        "write_session",
        lambda spec: (_ for _ in ()).throw(AssertionError("held lock invoked a session")),
    )
    with open(lock_path, "w", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = steward.run(home, dry_run=True)

    assert result.status == "idle"
    assert '"reason":"already running"' in steward.journal_path(home).read_text(
        encoding="utf-8"
    )


def test_stop_recovery_ends_before_a_session_or_stage_directory(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    stopped = intents.RecoverResult(stopped=["intent-deadbeef: cannot restore record"])
    calls = []

    monkeypatch.setattr(steward.intents, "recover", lambda actual: stopped)
    monkeypatch.setattr(
        steward.invocation,
        "write_session",
        lambda spec: calls.append(spec),
    )

    result = steward.run(home, dry_run=True)

    assert result.status == "stopped"
    assert result.stopped == stopped.stopped
    assert calls == []
    assert list((steward.cache_dir(home) / "steward" / "runs").glob("*")) == []
    journal = steward.journal_path(home).read_text(encoding="utf-8")
    assert '"status":"stopped"' in journal
    assert "intent-deadbeef" in journal


def test_twenty_five_records_are_decided_across_three_packets(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 25)
    _enable_steward(home)
    calls = []

    def fake_session(spec):
        calls.append(spec)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", fake_session)
    result = steward.run(home, dry_run=False)

    assert result.status == "applied"
    assert result.calls == 3
    assert result.decided == ids
    assert ledger_ops.list_items(home) == []
    assert git(home, "log", "--format=%B").stdout.count("By: steward") >= 25
    recorded = cases.list_cases(home, only_ok=True)
    assert len(recorded) == 25
    assert {row["actor"] for row in recorded} == {"steward"}
    assert steward.cases_since_overseer(home) == 25


def test_cross_bucket_queue_is_globally_oldest_first(tmp_path):
    home = make_home(tmp_path, skills=("a", "b"))
    plan = [
        ("skill:a", "2026-01-01T00:00:00Z", "lrn-aaaa0001"),
        ("skill:b", "2026-01-02T00:00:00Z", "lrn-bbbb0001"),
        ("skill:a", "2026-01-03T00:00:00Z", "lrn-aaaa0002"),
        ("skill:b", "2026-01-04T00:00:00Z", "lrn-bbbb0002"),
    ]
    for scope, created_at, rid in plan:
        create_record(
            home,
            make_behavior(record_id=rid, scope=scope, created_at=created_at),
        )
        ledger_ops.write_proposal(home, rid, proposal_dict(scope=scope))
        ledger_ops.stamp_proposal(home, rid)
    commit_all(home, "seed interleaved steward queue")

    assert [entry.record.id for entry, _ in steward._eligible_proposals(home)] == [
        "lrn-aaaa0001",
        "lrn-bbbb0001",
        "lrn-aaaa0002",
        "lrn-bbbb0002",
    ]


def test_runner_forces_steward_attribution_on_every_status_changing_sheet_item(tmp_path):
    sheet = tmp_path / "sheet.yaml"
    verbs_and_fields = [
        ("route", {"dest": "skill-md"}),
        ("reject", {}),
        ("defer", {}),
        ("undefer", {}),
        ("reopen", {}),
        ("retire", {"covered_by": "skill-md:x"}),
        ("supersede", {"new_id": "lrn-feedface"}),
        ("rehome", {"to": "skill:x"}),
        ("rescope", {"to": "user"}),
        ("revise", {"section": "Lesson", "text": "new", "because": "clearer"}),
    ]
    _dump_yaml(
        sheet,
        {
            "version": 1,
            "case": "$CASE_ID",
            "items": [
                {"id": f"lrn-{index:08x}", "verb": verb, **fields}
                for index, (verb, fields) in enumerate(verbs_and_fields, start=1)
            ],
        },
    )

    parsed = steward._prepare_sheet(sheet, "case-deadbeef")

    assert all(item.fields.get("by") == "steward" for item in parsed)


def test_runner_attributes_every_batch_preview_and_apply_to_steward(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    real_dry_run = steward.batch.dry_run
    real_run = steward.batch.run
    actors: list[tuple[str, object]] = []

    def attributed_dry_run(*args, **kwargs):
        actors.append(("dry-run", kwargs.get("actor")))
        return real_dry_run(*args, **kwargs)

    def attributed_run(*args, **kwargs):
        actors.append(("run", kwargs.get("actor")))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    monkeypatch.setattr(steward.batch, "dry_run", attributed_dry_run)
    monkeypatch.setattr(steward.batch, "run", attributed_run)

    assert steward.run(home).status == "applied"
    assert actors
    assert {kind for kind, _actor in actors} == {"dry-run", "run"}
    assert {actor for _kind, actor in actors} == {"steward"}


def test_session_spec_and_doctor_share_the_required_steward_containment(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    captured = []

    def capture(spec):
        captured.append(spec)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", capture)
    assert steward.run(home).status == "applied"

    spec = captured[0]
    run_record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    assert spec.cwd == run_record.parent
    assert spec.containment.write_globs == (f"{spec.cwd}/steward/**",)
    assert spec.containment.write_exact == ()
    assert spec.containment.strict_mcp is True
    assert spec.containment.allowed_tools == "Read,Grep,Glob,Write,Edit"
    assert spec.containment.disallowed_tools == "Bash,NotebookEdit,Task,WebFetch,WebSearch"

    row = provider._steward_containment_row(home)
    assert row.verdict == "PASS"
    assert "writes confined to the run directory" in row.detail

    monkeypatch.setattr(steward, "_DISALLOWED_TOOLS", None)
    refused_row = provider._steward_containment_row(home)
    assert refused_row.verdict == "FAIL"
    assert "disallowed_tools=None" in refused_row.detail


def test_dry_run_writes_stage_files_without_a_ledger_commit(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    before = git(home, "rev-list", "--count", "HEAD").stdout.strip()
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)

    result = steward.run(home, dry_run=True)

    after = git(home, "rev-list", "--count", "HEAD").stdout.strip()
    assert result.status == "dry-run"
    assert before == after
    assert list((steward.cache_dir(home) / "steward" / "runs").glob("*/steward/packet-*/sheets/*.yaml"))
    assert len(ledger_ops.list_items(home)) == 1
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    assert json.loads(record.read_text(encoding="utf-8"))["NOT_REPO_TRUTH"]["value"] is True
    assert steward.last_run_iso(home) is None
    assert not (home / "cases" / "runs").exists()


def test_turn_bound_leaves_that_packet_queued_and_records_the_bound(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)
    monkeypatch.setattr(
        steward.invocation,
        "write_session",
        lambda spec: _write_decision_stage(spec, turns=80),
    )

    result = steward.run(home, dry_run=False)

    assert result.status == "partial"
    assert result.decided == []
    assert [row["id"] for row in ledger_ops.list_items(home)] == ids
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    assert json.loads(record.read_text(encoding="utf-8"))["packets"][0]["bound"] == "turns"


def test_bound_ends_only_its_packet_and_later_packet_still_applies(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _configure_steward(home, packet_size=1)
    calls = 0

    def invoke(spec):
        nonlocal calls
        calls += 1
        return _write_decision_stage(spec, turns=80 if calls == 1 else 1)

    monkeypatch.setattr(steward.invocation, "write_session", invoke)

    result = steward.run(home)

    assert calls == 2
    assert result.status == "partial"
    assert result.decided == [ids[1]]
    assert [row["id"] for row in ledger_ops.list_items(home)] == [ids[0]]
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    packets = json.loads(record.read_text(encoding="utf-8"))["packets"]
    assert [packet["bound"] for packet in packets] == ["turns", None]


@pytest.mark.parametrize("code", [5, 6, 7, 8])
def test_sheet_stop_or_aggregate_halts_later_packets_and_maintenance(
    code, tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _configure_steward(home, packet_size=1)
    calls = 0

    def write_stage(spec):
        nonlocal calls
        calls += 1
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        assert match is not None
        _dump_yaml(Path(match.group(1)) / "statements.yaml", {"items": [{
            "verbatim": "Must never land after a halted sheet.",
            "source": {"message_ref": "transcript:halt#L1"},
        }]})
        return outcome

    def halt_batch(actual_home, items, **kwargs):
        item = items[0]
        return steward.batch.BatchResult(
            items=[steward.batch.ItemResult(
                n=item.n, id=item.id, verb=item.verb, rc=code,
                state="stopped" if code in {5, 6, 7} else "refused",
            )], process_code=code, stopped_at=item.n if code in {5, 6, 7} else None,
            case=items.case, sheet_sha=items.sheet_sha, actor="steward",
        )

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)
    monkeypatch.setattr(steward.batch, "run", halt_batch)

    result = steward.run(home)

    assert calls == 1
    assert result.status == ("stopped" if code == 6 else "partial")
    assert result.unfinished == ids
    assert not any(
        row["verbatim"] == "Must never land after a halted sheet."
        for row in statements.list_statements(home)
    )


def test_mixed_refused_and_applied_packets_report_partial(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _configure_steward(home, packet_size=1)
    calls = 0

    def invoke(spec):
        nonlocal calls
        calls += 1
        outcome = _write_decision_stage(spec)
        if calls == 1:
            match = re.search(
                r"^stage directory \(the only place you may write\): (.+)$",
                spec.prompt,
                re.M,
            )
            assert match is not None
            case = next((Path(match.group(1)) / "cases").glob("*.yaml"))
            data = YAML(typ="safe").load(case.read_text(encoding="utf-8"))
            data["decision"]["because"] = "token ghp_" + "Ab1" * 12
            _dump_yaml(case, data)
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", invoke)

    result = steward.run(home)

    assert result.status == "partial"
    assert result.decided == [ids[1]]
    assert result.refused == 1
    assert [row["id"] for row in ledger_ops.list_items(home)] == [ids[0]]


def test_run_manifest_is_committed_truth_and_cache_lies_do_not_drive_recovery(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)

    result = steward.run(home)

    assert result.status == "applied" and result.run_id is not None
    manifest_rel = f"cases/runs/{result.run_id}.json"
    committed = json.loads(git(home, "show", f"HEAD:{manifest_rel}").stdout)
    assert committed["run_id"] == result.run_id
    assert committed["status"] == "complete"
    assert committed["cases"]
    recipe = next(iter(committed["cases"].values()))
    assert recipe["sheet"]
    assert recipe["sheet_digest"] and recipe["items"]

    run_json = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    run_json.write_text('{"status":"case-recorded","active_case":"case-deadbeef"}\n')
    for result_json in run_json.parent.glob("batch-result-*.json"):
        result_json.write_text("not json\n", encoding="utf-8")

    again = steward.run(home)

    assert again.status == "idle"
    assert len(cases.list_cases(home, only_ok=True)) == 1


def test_unexplained_dirty_truth_path_refuses_before_batch_dispatch(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    real_preview = steward.batch.dry_run
    previews = 0

    def dirty_after_case(*args, **kwargs):
        nonlocal previews
        previews += 1
        result = real_preview(*args, **kwargs)
        if previews == 2:
            (home / "unexplained.txt").write_text("foreign write\n", encoding="utf-8")
        return result

    monkeypatch.setattr(steward.batch, "dry_run", dirty_after_case)
    monkeypatch.setattr(
        steward.batch, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dirty state reached dispatch")),
    )

    result = steward.run(home)

    assert result.status == "partial" and result.unfinished == [rid]
    journal = steward.journal_path(home).read_text(encoding="utf-8")
    assert "dirty-refused" in journal and "unexplained.txt" in journal
    assert Record.from_path(ledger_ops.find_record_path(home, rid)).status == "pending"


def test_run_record_has_call_durations_and_all_twenty_seven_coverage_cells(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)

    result = steward.run(home)

    assert len(result.coverage) == 27
    assert result.coverage["reject:skill"] == 1
    assert result.coverage["route:user"] == 0
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    data = json.loads(record.read_text(encoding="utf-8"))
    assert isinstance(data["packets"][0]["duration_secs"], float)
    assert data["coverage"] == result.coverage


class SimulatedKill(BaseException):
    pass


def _case_path(home: Path, case_id: str) -> Path:
    return next((home / "cases").glob(f"*/{case_id}.md"))


def test_crash_after_mutation_before_receipt_recovers_from_commit_evidence(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    real_receipt = steward.batch.write_receipt
    first = True

    def kill_before_receipt(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            raise SimulatedKill()
        return real_receipt(*args, **kwargs)

    monkeypatch.setattr(steward.batch, "write_receipt", kill_before_receipt)
    with pytest.raises(SimulatedKill):
        steward.run(home)

    manifest_rel = next(
        line for line in git(home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs").stdout.splitlines()
        if line.endswith(".json")
    )
    crashed = json.loads(git(home, "show", f"HEAD:{manifest_rel}").stdout)
    case_id = next(iter(crashed["cases"]))
    assert "sheet=" not in _case_path(home, case_id).read_text(encoding="utf-8")
    shutil.rmtree(steward.cache_dir(home))

    steward.run(home)
    steward.run(home)

    lines = [
        line
        for line in _case_path(home, case_id).read_text(encoding="utf-8").splitlines()
        if "sheet=" in line
    ]
    assert len(lines) == 1
    assert "item=1" in lines[0] and "reject" in lines[0]


def test_crash_after_case_before_batch_resumes_same_reserved_case_and_sheet(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    real_run = steward.batch.run
    first = True

    def kill_before_batch(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            raise SimulatedKill()
        return real_run(*args, **kwargs)

    monkeypatch.setattr(steward.batch, "run", kill_before_batch)
    with pytest.raises(SimulatedKill):
        steward.run(home)

    manifest_rel = next(
        line for line in git(home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs").stdout.splitlines()
        if line.endswith(".json")
    )
    crashed = json.loads(git(home, "show", f"HEAD:{manifest_rel}").stdout)
    case_id = next(iter(crashed["cases"]))
    original_sheet = crashed["cases"][case_id]["sheet"]
    shutil.rmtree(steward.cache_dir(home))

    result = steward.run(home)

    assert result.status == "applied"
    recorded = steward.cases.list_cases(home, record_id=rid)
    assert [row["case"] for row in recorded] == [case_id]
    finished = json.loads(git(home, "show", f"HEAD:{manifest_rel}").stdout)
    assert finished["cases"][case_id]["sheet"] == original_sheet
    assert "steward abandoned" not in _case_path(home, case_id).read_text(encoding="utf-8")


def test_crash_after_final_manifest_rebuilds_cache_projection_on_next_start(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    real_project = steward._project_manifest
    killed = False

    def kill_before_final_projection(actual_home, data):
        nonlocal killed
        if not killed and data.get("status") == "complete":
            killed = True
            raise SimulatedKill()
        return real_project(actual_home, data)

    monkeypatch.setattr(steward, "_project_manifest", kill_before_final_projection)
    with pytest.raises(SimulatedKill):
        steward.run(home)

    shutil.rmtree(steward.cache_dir(home))

    result = steward.run(home)

    assert result.status == "idle"
    record_path = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    recovered = json.loads(record_path.read_text(encoding="utf-8"))
    assert recovered["status"] == "complete"
    assert recovered["outcome"] == "applied"
    assert recovered["decided"]


def test_one_schema_repair_turn_gets_the_error_and_then_applies(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    prompts = []

    def fake_session(spec):
        prompts.append(spec.prompt)
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        assert match is not None
        sheet = next((Path(match.group(1)) / "sheets").glob("*.yaml"))
        if len(prompts) == 1:
            _dump_yaml(sheet, {"version": 1, "unexpected": []})
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", fake_session)
    result = steward.run(home)

    assert result.status == "applied"
    assert result.calls == 2
    assert "unexpected" in prompts[1]
    assert "Repair them in place" in prompts[1]


def test_second_schema_failure_stops_after_the_one_repair_turn(tmp_path, monkeypatch):
    """REWRITTEN for S-68 (`03-decisions.md`), which names this test by
    name: it used to pin "no new call ever again, `repair_remaining == 0`
    and the packet left unfinished forever" — the behaviour that caused
    the 2026-09-14 outage. The name still holds, with the unit corrected:
    the ATTEMPT stops after its one repair turn, and ruling 1 gives the
    PACKET a later attempt with a fresh repair turn of its own."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    prompts = []

    def always_invalid(spec):
        prompts.append(spec.prompt)
        return _invalid_schema_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", always_invalid)
    result = steward.run(home)

    assert result.status == "partial" and result.calls == 2
    assert [row["id"] for row in ledger_ops.list_items(home)] == ids
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    packet = json.loads(record.read_text(encoding="utf-8"))["packets"][0]
    assert packet["bound"] == "schema-repair" and "unexpected" in packet["error"]
    assert result.run_id is not None
    committed = _head_manifest(home, result.run_id)["packets"][0]
    assert committed["attempt_count"] == 1
    assert committed["failure"] == "schema-repair"
    assert "unexpected" in (committed["failure_detail"] or "")
    assert committed["repair_remaining"] == 0

    shutil.rmtree(steward.cache_dir(home))
    calls_before = len(prompts)
    again = steward.run(home)

    # The attempt is fresh, and so is its single repair turn: one decision
    # call plus one repair call, never a second repair inside one attempt.
    assert again.status == "partial" and again.calls == 2
    assert len(prompts) == calls_before + 2
    committed = _head_manifest(home, result.run_id)["packets"][0]
    assert committed["attempt_count"] == 2
    assert committed["repair_remaining"] == 0
    assert _head_manifest(home, result.run_id)["completed_at"] is None


def test_hook_route_is_parked_for_overseer_and_never_dispatched(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_hook_stage)
    monkeypatch.setattr(
        steward.batch,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("parked route reached batch.run")),
    )

    result = steward.run(home)

    assert result.status == "applied"
    rows = steward.cases.list_cases(home, parked_for="overseer", parked_reason="hook")
    assert len(rows) == 1 and rows[0]["records"] == [rid]
    assert ledger_ops.list_items(home)[0]["id"] == rid
    text = _case_path(home, rows[0]["case"]).read_text(encoding="utf-8")
    assert "→ parked (exit 0)" in text


def test_plain_host_route_to_a_committed_file_is_parked(monkeypatch, tmp_path):
    home = tmp_path / "home"
    host = tmp_path / "host"
    host.mkdir()
    target = host / "CLAUDE.md"
    target.write_text("standing\n", encoding="utf-8")
    git(host, "init", "-q")
    git(host, "add", "CLAUDE.md")
    git(host, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed")
    sheet = tmp_path / "stage" / "sheets" / "one.yaml"
    _dump_yaml(
        sheet,
        {"version": 1, "case": "$CASE_ID", "items": [{"id": "lrn-deadbeef", "verb": "route", "dest": "claude-md"}]},
    )
    preview = steward.batch.DryRunResult(
        items=[
            steward.batch.DryRunItem(
                n=1,
                id="lrn-deadbeef",
                verb="route",
                state="would-apply",
                route_preview={"mode": "plain", "host": str(host), "target": str(target)},
            )
        ]
    )
    monkeypatch.setattr(steward.batch, "dry_run", lambda *a, **k: preview)

    assert steward._forced_parking_reason(home, sheet) == "plain-host-committed-file"

    git(host, "rm", "--cached", "-q", "CLAUDE.md")
    assert steward._forced_parking_reason(home, sheet) is None


def test_parked_proposal_version_is_terminal_and_not_decided_again(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    _enable_steward(home)
    calls = 0

    def invoke(spec):
        nonlocal calls
        calls += 1
        return _write_hook_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", invoke)

    first = steward.run(home)
    second = steward.run(home)
    third = steward.run(home)

    assert first.status == "applied"
    assert first.decided == []
    assert second.status == third.status == "idle"
    assert calls == 1
    parked = cases.list_cases(home, record_id=rid, parked_for="overseer")
    assert len(parked) == 1


def test_secret_scan_hit_is_refused_never_parked(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    _enable_steward(home)

    def write_secret_stage(spec):
        outcome = _write_hook_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        case = next((Path(match.group(1)) / "cases").glob("*.yaml"))
        data = YAML(typ="safe").load(case.read_text(encoding="utf-8"))
        data["decision"]["because"] = "token ghp_" + "Ab1" * 12
        _dump_yaml(case, data)
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", write_secret_stage)
    result = steward.run(home)

    assert result.status == "refused"
    assert result.decided == [] and result.refused == 1
    assert ledger_ops.list_items(home)[0]["id"] == rid
    assert steward.cases.list_cases(home, parked_for="overseer") == []
    assert "secret scan:" in steward.journal_path(home).read_text(encoding="utf-8")


def test_statement_maintenance_requires_a_transcript_reference_and_is_journaled(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)

    def write_stage(spec):
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        stage = Path(match.group(1))
        _dump_yaml(
            stage / "statements.yaml",
            {
                "items": [
                    {
                        "verbatim": "I prefer the narrow surface.",
                        "source": {"message_ref": "transcript:session#L9"},
                    },
                    {"verbatim": "invented", "source": {"message_ref": "inline:none"}},
                ]
            },
        )
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)
    result = steward.run(home)

    assert result.status == "partial" and result.refused == 1
    rows = statements.list_statements(home)
    assert len(rows) == 1
    assert rows[0]["recorded_by"] == "steward"
    assert rows[0]["source"]["message_ref"] == "transcript:session#L9"
    assert "statement-refused" in steward.journal_path(home).read_text(encoding="utf-8")


def test_malformed_maintenance_entries_are_refused_and_later_entries_apply(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)

    def write_stage(spec):
        outcome = _write_decision_stage(spec)
        match = re.search(
            r"^stage directory \(the only place you may write\): (.+)$",
            spec.prompt,
            re.M,
        )
        assert match is not None
        stage = Path(match.group(1))
        _dump_yaml(
            stage / "statements.yaml",
            {
                "items": [
                    {
                        "verbatim": "bad type",
                        "source": {"message_ref": "transcript:session#L1"},
                        "answers": 1,
                    },
                    {
                        "verbatim": "bad value",
                        "source": {"message_ref": "transcript:session#L2"},
                        "answers": [["kind"]],
                    },
                    {
                        "verbatim": "The narrow surface is preferred.",
                        "source": {"message_ref": "transcript:session#L3"},
                    },
                ]
            },
        )
        _dump_yaml(
            stage / "model-updates.yaml",
            {
                "items": [
                    {
                        "action": "add",
                        "container": "C",
                        "title": "malformed",
                        "because": "a stray key must be refused",
                        "source": "system-reading",
                        "ref": "transcript:session#L4",
                        "not_a_real_key": 1,
                    },
                    {
                        "action": "add",
                        "container": "C",
                        "title": "valid reading",
                        "because": "later entries still apply",
                        "source": "system-reading",
                        "ref": "transcript:session#L5",
                        "statements": ["stmt-deadbeef"],
                    },
                ]
            },
        )
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)

    result = steward.run(home)

    assert result.status == "partial"
    assert result.refused == 3
    assert [row["verbatim"] for row in statements.list_statements(home)] == [
        "The narrow surface is preferred."
    ]
    model = user_model.show(home)
    assert [row["title"] for row in model["containers"]["C"]] == ["valid reading"]
    journal = steward.journal_path(home).read_text(encoding="utf-8")
    assert journal.count('"status":"statement-refused"') == 2
    assert journal.count('"status":"model-update-refused"') == 1


@pytest.mark.parametrize("owner", ["statement", "model-add", "model-lapse"])
def test_kill_after_maintenance_owner_commit_recovers_without_duplicate(
    owner, tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    statement_id = statements.add(
        home, verbatim="Evidence for model maintenance.",
        source={"message_ref": "transcript:seed#L1"}, recorded_by="human",
    )
    lapse_id = user_model.add_entry(
        home, container="C", title="old reading", because="the old condition held",
        source="system-reading", statements=[statement_id], ref="transcript:seed#L1",
        by="steward",
    )

    def write_stage(spec):
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        assert match is not None
        stage = Path(match.group(1))
        if owner == "statement":
            _dump_yaml(stage / "statements.yaml", {"items": [{
                "verbatim": "A recovered statement.",
                "source": {"message_ref": "transcript:run#L2"},
            }]})
        elif owner == "model-add":
            _dump_yaml(stage / "model-updates.yaml", {"items": [{
                "action": "add", "container": "C", "title": "new reading",
                "because": "the new condition was observed", "source": "system-reading",
                "statements": [statement_id], "ref": "transcript:run#L3",
            }]})
        else:
            _dump_yaml(stage / "model-updates.yaml", {"items": [{
                "action": "lapse", "id": lapse_id,
                "changed_condition": "the old condition no longer holds",
            }]})
        return outcome

    real_update = steward._update_manifest
    killed = False

    def kill_after_owner(actual_home, run_id, *, reason, update):
        nonlocal killed
        if not killed and reason.startswith("maintenance result"):
            killed = True
            raise SimulatedKill()
        return real_update(actual_home, run_id, reason=reason, update=update)

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)
    monkeypatch.setattr(steward, "_update_manifest", kill_after_owner)
    with pytest.raises(SimulatedKill):
        steward.run(home)
    shutil.rmtree(steward.cache_dir(home))

    assert steward.run(home).status == "applied"
    if owner == "statement":
        assert sum(row["verbatim"] == "A recovered statement." for row in statements.list_statements(home)) == 1
    elif owner == "model-add":
        assert sum(row["title"] == "new reading" for row in steward._model_entries(home)) == 1
    else:
        assert next(row for row in steward._model_entries(home) if row["id"] == lapse_id)["status"] == "LAPSED"


def test_dependency_observation_is_mechanically_reconsidered(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    statement_id = statements.add(
        home,
        verbatim="Use the revised condition.",
        source={"message_ref": "transcript:session#L7"},
        recorded_by="human",
    )
    original_stage = tmp_path / "original-case.yaml"
    _dump_yaml(
        original_stage,
        {
            "kind": "resolution",
            "trigger": "human",
            "outcome": "reject",
            "records": [rid],
            "scope": "skill:s",
            "question": "should this be retained?",
            "evidence": [{"ref": "transcript:session#L1", "quote": "old evidence"}],
            "decision": {"verb": "reject", "because": "old condition", "confidence": "settled"},
            "dependencies": {"statements": [statement_id], "user_model": [], "conditions": [], "capabilities": []},
        },
    )
    original_case = cases.record(home, original_stage, actor="human")
    verbs.reject(home, rid, by="human", no_push=True)
    cases.observe(
        home,
        original_case,
        "statement",
        text="the answer changed",
        ref=statement_id,
        by="steward",
    )
    _enable_steward(home)

    def write_reconsider_stage(spec):
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        stage = Path(match.group(1))
        _dump_yaml(
            stage / "cases" / f"{rid}.yaml",
            {
                "kind": "reconsider",
                "trigger": "reconsider",
                "outcome": "defer",
                "records": [rid],
                "scope": "skill:s",
                "question": "does the changed statement alter the decision?",
                "evidence": [{"ref": statement_id, "quote": "the answer changed"}],
                "decision": {"verb": "defer", "because": "the new condition needs time", "confidence": "settled"},
                "dependencies": {"statements": [statement_id], "user_model": [], "conditions": [], "capabilities": []},
            },
        )
        _dump_yaml(
            stage / "sheets" / f"{rid}.yaml",
            {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reopen"}, {"id": rid, "verb": "defer"}]},
        )
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", write_reconsider_stage)
    result = steward.run(home)

    assert result.status == "applied" and result.decided == [rid]
    successor = next(row for row in cases.list_cases(home, record_id=rid) if row["kind"] == "reconsider")
    assert successor["supersedes"] == original_case
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert record.status == "deferred"
    assert any(event.get("event") == "reconsidered" for event in record.history)


def test_kill_after_reconsider_marker_reuses_successor_and_marker(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    statement_id = statements.add(home, verbatim="Changed dependency.",
        source={"message_ref": "transcript:reconsider#L1"}, recorded_by="human")
    original_stage = tmp_path / "original.yaml"
    _dump_yaml(original_stage, {
        "kind": "resolution", "trigger": "human", "outcome": "reject", "records": [rid],
        "scope": "skill:s", "question": "retain?",
        "evidence": [{"ref": "transcript:reconsider#L1", "quote": "old"}],
        "decision": {"verb": "reject", "because": "old condition", "confidence": "settled"},
        "dependencies": {"statements": [statement_id], "user_model": [], "conditions": [], "capabilities": []},
    })
    predecessor = cases.record(home, original_stage, actor="human")
    verbs.reject(home, rid, by="human", no_push=True)
    cases.observe(home, predecessor, "statement", text="changed", ref=statement_id, by="steward")
    _enable_steward(home)

    def write_stage(spec):
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        assert match is not None
        stage = Path(match.group(1))
        _dump_yaml(stage / "cases" / f"{rid}.yaml", {
            "kind": "reconsider", "trigger": "reconsider", "outcome": "defer", "records": [rid],
            "scope": "skill:s", "question": "does the dependency change the decision?",
            "evidence": [{"ref": statement_id, "quote": "changed"}],
            "decision": {"verb": "defer", "because": "re-evaluate later", "confidence": "settled"},
            "dependencies": {"statements": [statement_id], "user_model": [], "conditions": [], "capabilities": []},
        })
        _dump_yaml(stage / "sheets" / f"{rid}.yaml", {"version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "reopen"}, {"id": rid, "verb": "defer"}]})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    real_reconsider = steward.verbs.reconsider
    killed = False

    def kill_after_marker(*args, **kwargs):
        nonlocal killed
        outcome = real_reconsider(*args, **kwargs)
        if not killed:
            killed = True
            raise SimulatedKill()
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)
    monkeypatch.setattr(steward.verbs, "reconsider", kill_after_marker)
    with pytest.raises(SimulatedKill):
        steward.run(home)
    shutil.rmtree(steward.cache_dir(home))

    assert steward.run(home).status == "applied"
    successors = [row for row in cases.list_cases(home, record_id=rid) if row["kind"] == "reconsider"]
    assert len(successors) == 1
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert sum(event.get("event") == "reconsidered" for event in record.history) == 1


def test_cli_steward_run_exit_codes_and_json(monkeypatch, capsys, tmp_path):
    """REWRITTEN for S-68: the envelope and the text line both carry
    `abandoned`, so a run that closed lessons out can never again read
    "0 decided, 0 refused, 0 unfinished" beside a non-zero exit code."""
    home = make_home(tmp_path)
    monkeypatch.setattr(cli_mod, "resolve_home", lambda: home)
    monkeypatch.setattr(
        cli_mod.steward,
        "run",
        lambda actual, dry_run=False: steward.RunResult(
            "partial", run_id="run-abc", decided=["lrn-deadbeef"], calls=2, refused=1
        ),
    )

    rc = cli_mod.main(["steward", "run", "--json"])

    assert rc == cli_mod.EXIT_BATCH_PARTIAL
    assert json.loads(capsys.readouterr().out) == {
        "command": "steward run",
        "outcome": "partial",
        "ok": False,
        "run_id": "run-abc",
        "decided": ["lrn-deadbeef"],
        "calls": 2,
        "refused": 1,
        "unfinished": [],
        "abandoned": [],
        "coverage": {},
        "stopped": [],
    }

    monkeypatch.setattr(
        cli_mod.steward,
        "run",
        lambda actual, dry_run=False: steward.RunResult(
            "refused", run_id="run-abc", calls=0, abandoned=["lrn-deadbeef"]
        ),
    )

    assert cli_mod.main(["steward", "run", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "command": "steward run",
        "outcome": "refused",
        "ok": False,
        "run_id": "run-abc",
        "decided": [],
        "calls": 0,
        "refused": 0,
        "unfinished": [],
        "abandoned": ["lrn-deadbeef"],
        "coverage": {},
        "stopped": [],
    }

    assert cli_mod.main(["steward", "run"]) == 1
    text = capsys.readouterr().out
    assert "0 decided, 0 refused, 0 unfinished, 1 abandoned" in text


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("idle", cli_mod.EXIT_HELD),
        ("disabled", cli_mod.EXIT_HELD),
        ("dry-run", cli_mod.EXIT_OK),
        ("applied", cli_mod.EXIT_OK),
        ("partial", cli_mod.EXIT_BATCH_PARTIAL),
        ("refused", 1),
        ("stopped", gitops.EXIT_GIT_FAILED),
    ],
)
def test_cli_steward_run_maps_every_status_to_fw85(
    status, expected, monkeypatch, capsys, tmp_path
):
    home = make_home(tmp_path)
    monkeypatch.setattr(cli_mod, "resolve_home", lambda: home)
    monkeypatch.setattr(
        cli_mod.steward,
        "run",
        lambda actual, dry_run=False: steward.RunResult(
            status,
            stopped=["intent-deadbeef: path hosts.yaml changed twice"]
            if status == "stopped"
            else [],
        ),
    )

    assert cli_mod.main(["steward", "run", "--json"]) == expected
    assert json.loads(capsys.readouterr().out)["outcome"] == status


def test_cli_steward_stop_names_the_planted_intent_and_clear_command(
    tmp_path, monkeypatch, capsys
):
    home = make_home(tmp_path)
    target = home / "hosts.yaml"
    intent = _plant_stop(home, target, op="steward-stop")
    monkeypatch.setattr(cli_mod, "resolve_home", lambda: home)

    assert cli_mod.main(["steward", "run"]) == gitops.EXIT_GIT_FAILED
    err = capsys.readouterr().err
    assert intent.id in err
    assert target.name in err
    assert "reconcile --clear-intent" in err


def test_status_json_has_steward_fields_and_doctor_names_containment(
    monkeypatch, capsys, tmp_path
):
    home = make_home(tmp_path)
    monkeypatch.setattr(cli_mod, "resolve_home", lambda: home)
    monkeypatch.setattr(cli_mod.steward, "last_run_iso", lambda actual: "2026-09-14T12:00:00Z")
    monkeypatch.setattr(cli_mod.steward, "cases_since_overseer", lambda actual: 7)

    assert cli_mod.main(["status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["steward_last_run_at"] == "2026-09-14T12:00:00Z"
    assert status["steward_cases_since_overseer"] == 7

    cli_mod.main(["doctor", "invocation"])
    doctor = capsys.readouterr().out
    assert "models — steward:" in doctor
    assert "containment — steward:" in doctor
    assert "writes confined to the run directory" in doctor


def test_doctor_serve_reads_the_threaded_homes_cached_steward_marker(
    monkeypatch, tmp_path
):
    home = make_home(tmp_path)
    marker = steward.cache_dir(home) / "steward" / "steward.last-run"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("2026-09-14T12:34:56Z\n", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "different-home"))

    row = provider._serve_row(home)

    assert "steward_last_run_at=2026-09-14T12:34:56Z" in row.detail


# ==================================================================
# S-68 — liveness of delegated runs (U2: the steward)
#
# Every test below fails on the parent commit 155df84: there, a packet
# marked `unfinished` was in the resume skip set, so no later run ever
# touched it again, and `complete` was stamped over cases that had not
# finished.
# ==================================================================


def test_transport_failure_is_reattempted_by_the_next_run_and_completes(tmp_path, monkeypatch):
    """S-68 ruling 1: a model call that failed is not a judgment on the
    merits, so a LATER run re-attempts it as a fresh attempt. A2: the
    failure path must not rewind the committed `last_attempt_at`."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _transport_failure)

    first = steward.run(home)

    assert first.status == "partial" and first.calls == 1 and first.decided == []
    assert first.run_id is not None
    manifest = _head_manifest(home, first.run_id)
    packet = manifest["packets"][0]
    assert manifest["status"] == "unfinished"
    assert packet["phase"] == "unfinished" and packet["bound"] == "exit"
    assert packet["attempt_count"] == 1
    # the scheduler's committed cooldown reads these two; the failure
    # path used to publish a pre-invocation copy that erased both
    assert isinstance(manifest["last_attempt_at"], str)
    assert isinstance(packet["last_attempt_at"], str)

    calls = []

    def decide(spec):
        calls.append(spec)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", decide)
    second = steward.run(home)

    assert second.run_id == first.run_id
    assert len(calls) == 1 and second.calls == 1
    assert second.status == "applied" and second.decided == ids
    manifest = _head_manifest(home, first.run_id)
    packet = manifest["packets"][0]
    assert manifest["status"] == "complete" and manifest["completed_at"]
    assert packet["phase"] == "complete" and packet["bound"] is None
    assert packet["attempt_count"] == 2 and packet["progress_at"]
    assert ledger_ops.list_items(home) == []


def test_schema_failure_is_reattempted_with_its_own_fresh_repair_turn(tmp_path, monkeypatch):
    """S-68 ruling 1's other half: "a FRESH attempt with its OWN single
    repair turn" — the re-attempt's `repair_remaining` is 1 again."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _invalid_schema_stage)

    first = steward.run(home)

    assert first.status == "partial" and first.calls == 2
    assert first.run_id is not None
    packet = _head_manifest(home, first.run_id)["packets"][0]
    assert packet["repair_remaining"] == 0 and packet["attempt_count"] == 1

    prompts = []

    def repair_once(spec):
        prompts.append(spec.prompt)
        if len(prompts) == 1:
            return _invalid_schema_stage(spec)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", repair_once)
    second = steward.run(home)

    assert second.calls == 2 and "Repair them in place" in prompts[1]
    assert second.status == "applied" and second.decided == ids
    manifest = _head_manifest(home, first.run_id)
    assert manifest["status"] == "complete"
    assert manifest["packets"][0]["attempt_count"] == 2


def test_three_failed_attempts_close_the_run_out_and_a_fourth_run_starts_a_new_one(
    tmp_path, monkeypatch
):
    """S-68 ruling 2: "after 3 failed attempts the run is closed so new
    runs can start". Nothing before this test ran a third time, so
    nothing detected the loop."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _transport_failure)
    notifications = []
    monkeypatch.setattr(
        overseer_notify, "send",
        lambda home_, cue, summary, sent_ids: notifications.append((cue, summary, sent_ids)),
    )

    cap, _source = settings.resolve_setting(home, settings.by_name("runs.attempt_cap"))
    assert cap == 3
    results = [steward.run(home) for _ in range(3)]

    assert len({result.run_id for result in results}) == 1
    stuck_run = results[0].run_id
    assert stuck_run is not None
    assert [result.calls for result in results] == [1, 1, 1]
    manifest = _head_manifest(home, stuck_run)
    packet = manifest["packets"][0]
    assert packet["attempt_count"] == 3 and packet["phase"] == "abandoned"
    assert manifest["status"] == "complete" and manifest["completed_at"]
    assert results[-1].abandoned == ids and results[-1].status == "refused"
    assert len(notifications) == 1

    # the fourth run is a NEW run, because the stuck one is closed
    fresh = _seed_fresh_proposals(home, 1, offset=len(ids))
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    fourth = steward.run(home)

    assert fourth.run_id != stuck_run
    assert fourth.status == "applied" and fourth.decided == fresh


def test_failed_receipt_write_leaves_the_packet_open_and_the_case_is_redriven(
    tmp_path, monkeypatch
):
    """A20: `batch.write_receipt` reports a failed write by RETURNING
    `{"state": "failed"}` — it never raises. The case was marked
    `unfinished`, the packet was then stamped `complete` over it, later
    runs skipped it, and the run stayed unfinished forever."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_hook_stage)
    real_receipt = steward.batch.write_receipt
    monkeypatch.setattr(steward.batch, "write_receipt", _failing_receipt)

    first = steward.run(home)

    # the run reports success — every disposition reached `parked` — and
    # the CASE is still unfinished underneath it. That gap is the trap:
    # the packet used to be stamped `complete` over it.
    assert first.status == "applied" and first.run_id is not None
    manifest = _head_manifest(home, first.run_id)
    packet = manifest["packets"][0]
    # positive control: the packet DID reach the apply phase and made a case
    assert packet["case_ids"] and packet["phase"] != "pending"
    assert manifest["cases"][packet["case_ids"][0]]["phase"] == "unfinished"
    assert packet["phase"] not in {"complete", "refused", "abandoned"}
    assert manifest["status"] == "unfinished" and manifest["completed_at"] is None

    calls = []

    def never_called(spec):
        calls.append(spec)
        return _write_hook_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", never_called)
    monkeypatch.setattr(steward.batch, "write_receipt", real_receipt)
    second = steward.run(home)

    # the receipt write is idempotent by (sheet_sha, item); re-driving it
    # needs no model call at all
    assert calls == [] and second.calls == 0
    assert second.run_id == first.run_id and second.status == "applied"
    manifest = _head_manifest(home, first.run_id)
    assert manifest["status"] == "complete"
    assert manifest["packets"][0]["phase"] == "complete"
    assert manifest["packets"][0]["attempt_count"] == 2
    assert manifest["packets"][0]["dispositions"][ids[0]]["state"] == "parked"
    assert len(cases.list_cases(home, parked_for="overseer", parked_reason="hook")) == 1


def test_an_input_left_with_no_disposition_is_never_stuck(tmp_path, monkeypatch):
    """A20's second half (`steward.py`'s `cases.record` refusal path,
    where `case_data["records"]` is absent): the input ends the run with
    NO disposition at all. It must be re-driven or closed out, never
    silently carried by a packet stamped `complete`."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    real_stage = steward._write_recipe_stage

    def recipe_without_records(run_dir, packet_index, case_id, recipe):
        case_path, sheet_path = real_stage(run_dir, packet_index, case_id, recipe)
        data = YAML(typ="safe").load(case_path.read_text(encoding="utf-8"))
        data.pop("records", None)
        _dump_yaml(case_path, data)
        return case_path, sheet_path

    monkeypatch.setattr(steward, "_write_recipe_stage", recipe_without_records)
    notifications = []
    monkeypatch.setattr(
        overseer_notify, "send",
        lambda home_, cue, summary, sent_ids: notifications.append(summary),
    )

    first = steward.run(home)
    assert first.run_id is not None
    packet = _head_manifest(home, first.run_id)["packets"][0]
    # positive control: this really is the no-disposition shape
    assert packet["dispositions"] == {}
    assert packet["phase"] not in {"complete", "refused", "abandoned"}

    steward.run(home)
    third = steward.run(home)

    manifest = _head_manifest(home, first.run_id)
    packet = manifest["packets"][0]
    assert packet["phase"] == "abandoned"
    assert packet["dispositions"][ids[0]]["state"] == "abandoned"
    assert packet["dispositions"][ids[0]]["successor_case"]
    assert manifest["status"] == "complete"
    assert third.abandoned == ids and len(notifications) == 1


def test_an_attempt_that_moves_nothing_is_recorded_and_reaches_the_cap(
    tmp_path, monkeypatch
):
    """S-68's PROGRESS definition and the generic guard behind it: an
    attempt that ran and moved no unit toward a terminal value counts
    exactly like one that failed, so a trap nobody thought of still
    closes out instead of spinning."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_hook_stage)
    monkeypatch.setattr(steward.batch, "write_receipt", _failing_receipt)
    monkeypatch.setattr(overseer_notify, "send", lambda *a, **k: None)

    first = steward.run(home)
    assert first.run_id is not None
    # positive control: the first attempt DID make progress (a case appeared)
    packet = _head_manifest(home, first.run_id)["packets"][0]
    assert packet["progress_at"] and packet.get("failure") != "no-progress"

    second = steward.run(home)

    assert second.calls == 0
    manifest = _head_manifest(home, first.run_id)
    packet = manifest["packets"][0]
    assert packet["failure"] == "no-progress"
    assert packet["failure_detail"] and "toward a terminal value" in packet["failure_detail"]
    assert packet["attempt_count"] == 2
    assert manifest["status"] == "unfinished"

    third = steward.run(home)

    manifest = _head_manifest(home, first.run_id)
    assert manifest["packets"][0]["phase"] == "abandoned"
    assert manifest["status"] == "complete" and manifest["completed_at"]
    # nothing to park: this record's own disposition already reached
    # `parked`, and its parked case is committed — only the receipt for it
    # never landed, so no lesson was lost and none is parked a second time
    assert third.abandoned == []
    assert len(cases.list_cases(home, parked_for="overseer", parked_reason="hook")) == 1
    assert cases.list_cases(home, parked_reason="attempts-exhausted") == []


def test_stage_leftovers_from_a_failed_attempt_are_cleared_first(tmp_path, monkeypatch):
    """A24: the packet stage was never cleared between attempts, so a
    re-attempt validated the new session's files BESIDE the failed
    session's. This test must NOT delete the cache — that is exactly
    what hid the defect from the old schema-failure test."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    leftover_name = "lrn-ffffffff.yaml"
    seen_after = []

    def first_session_leaves_litter(spec):
        stage = _stage_dir(spec)
        _write_decision_stage(spec)
        # a case for a record this packet does not own: if it survives,
        # the next attempt's coverage check refuses the whole stage
        litter = YAML(typ="safe").load(
            next((stage / "cases").glob("*.yaml")).read_text(encoding="utf-8")
        )
        litter["records"] = ["lrn-ffffffff"]
        _dump_yaml(stage / "cases" / leftover_name, litter)
        return _transport_failure(spec)

    monkeypatch.setattr(steward.invocation, "write_session", first_session_leaves_litter)
    first = steward.run(home)
    assert first.run_id is not None
    stage = steward.steward_dir(home) / "runs" / first.run_id / "steward" / "packet-0001"
    # positive control: the litter really was written and really survived
    assert (stage / "cases" / leftover_name).is_file()

    def second_session(spec):
        second_stage = _stage_dir(spec)
        seen_after.append(sorted(p.name for p in (second_stage / "cases").glob("*.yaml")))
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", second_session)
    second = steward.run(home)

    assert seen_after == [[]]
    assert not (stage / "cases" / leftover_name).is_file()
    assert second.status == "applied" and second.decided == ids


def test_the_live_stuck_run_shape_is_reattempted_and_completes(tmp_path, monkeypatch):
    """02-schema §3a's legacy rule, against the exact shape left stuck on
    2026-09-14: three packets, `phase: unfinished`, `bound: exit`,
    `repair_remaining: 1`, one `decision` attempt each, NO
    `attempt_count`, run-level `last_attempt_at: null`. Its count is
    DERIVED from the attempts list, never invented, and the product —
    not a hand edit of committed JSON — carries it forward."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 3)
    _configure_steward(home, packet_size=1)
    run_id = "run-0123456789ab"
    packets = []
    for index, (entry, proposal) in enumerate(steward._eligible_proposals(home), start=1):
        identity = steward._input_identity(
            home, entry.proposal_path, entry.record.id, proposal
        )
        packets.append({
            "index": index,
            "inputs": [identity],
            "records": [entry.record.id],
            "predecessors": {},
            "phase": "unfinished",
            "attempts": [
                {"kind": "decision", "turns": None, "failure": "exit", "duration_secs": 1.0}
            ],
            "repair_remaining": 1,
            "case_ids": [],
            "maintenance": [],
            "dispositions": {
                entry.record.id: {
                    "state": "unfinished",
                    "input_version": identity["version"],
                    "reason": "exit",
                }
            },
            "bound": "exit",
            "failure": "exit",
        })
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": run_id,
        "started_at": steward.chrono.now_iso(), "last_attempt_at": None,
        "completed_at": None, "status": "unfinished", "outcome": "partial",
        "start_head": steward.gitops.head_sha(home), "cases": {},
        "packets": packets,
        "inputs": [row for packet in packets for row in packet["inputs"]],
        "reconsider_observations": [], "coverage": steward._coverage_empty(),
        "ledger_effects": [],
    }, reason="the 2026-09-14 stuck shape")

    # positive control: the fixture really carries no explicit count, and
    # exactly the one `decision` row a derived count has to read
    stuck = _head_manifest(home, run_id)
    assert all("attempt_count" not in packet for packet in stuck["packets"])
    assert stuck["last_attempt_at"] is None
    assert all(
        sum(1 for row in packet["attempts"] if row["kind"] == "decision") == 1
        for packet in stuck["packets"]
    )

    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    result = steward.run(home)

    assert result.run_id == run_id and result.calls == 3
    assert result.status == "applied" and sorted(result.decided) == sorted(ids)
    manifest = _head_manifest(home, run_id)
    assert manifest["status"] == "complete"
    assert [packet["attempt_count"] for packet in manifest["packets"]] == [2, 2, 2]
    assert ledger_ops.list_items(home) == []


def test_close_out_parks_every_record_for_the_overseer_and_duplicates_nothing(
    tmp_path, monkeypatch
):
    """Ruling 2 and 02-schema §3a's `abandoned` shape: a parked case per
    record (`parked_for: overseer`, `parked_reason: attempts-exhausted`),
    a committed evidence reference into the run record, a non-null
    `successor_case`, one notification, and nothing duplicated."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    # one record per packet, so the evidence reference has to name the
    # RIGHT packet's line span and not simply the whole file
    _configure_steward(home, packet_size=1)
    monkeypatch.setattr(steward.invocation, "write_session", _transport_failure)
    notifications = []
    monkeypatch.setattr(
        overseer_notify, "send",
        lambda home_, cue, summary, sent_ids: notifications.append((cue, summary, sent_ids)),
    )

    results = [steward.run(home) for _ in range(3)]
    run_id = results[0].run_id
    assert run_id is not None

    rows = cases.list_cases(home, parked_for="overseer", parked_reason="attempts-exhausted")
    assert sorted(row["records"][0] for row in rows) == sorted(ids)
    assert all(row["actor"] == "steward" and row["outcome"] == "parked" for row in rows)

    manifest = _head_manifest(home, run_id)
    assert len(manifest["packets"]) == 2
    for packet in manifest["packets"]:
        index = packet["index"]
        other = 2 if index == 1 else 1
        assert len(packet["records"]) == 1
        record_id = packet["records"][0]
        disposition = packet["dispositions"][record_id]
        assert disposition["state"] == "abandoned"
        assert disposition["attempts"] == 3
        assert "does not support the selected model" in disposition["reason"]
        successor = disposition["successor_case"]
        assert successor and successor in {row["case"] for row in rows}
        view = cases.show(home, successor, evidence_only=False)
        # positive control: the evidence section rendered at all
        evidence = view.sections["Evidence"]
        assert evidence.strip()
        assert "decide this lesson itself" in view.sections["Identity and scope"]
        reference = re.search(
            r"ledger@([0-9a-f]{40}):(cases/runs/\S+\.json)#L(\d+)-(\d+)", evidence
        )
        assert reference is not None
        sha, path, first, last = reference.groups()
        quoted = git(home, "show", f"{sha}:{path}").stdout.splitlines()[
            int(first) - 1 : int(last)
        ]
        assert any(f'"index": {index}' in line for line in quoted)
        # the span is THIS packet's, not the whole packets array
        assert not any(f'"index": {other}' in line for line in quoted)
        assert any("does not support the selected model" in line for line in quoted)

    assert len(notifications) == 1
    cue, summary, sent = notifications[0]
    assert cue == "routine" and sorted(sent) == sorted(ids)
    assert "2 lesson(s) parked for the overseer" in summary

    # the records leave the steward's eligibility with their successors
    assert steward.run(home).status == "idle"
    assert len(cases.list_cases(home, parked_reason="attempts-exhausted")) == 2
    assert len(notifications) == 1


def test_a_close_out_whose_ledger_write_fails_is_retried_without_a_new_count(
    tmp_path, monkeypatch
):
    """02-schema §3a: "a close-out that fails ... is retried by the next
    run, is idempotent ... and increments no count of its own"."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _transport_failure)
    monkeypatch.setattr(overseer_notify, "send", lambda *a, **k: None)
    real_update = steward._update_manifest
    refusals = []

    def refuse_the_first_close_out(actual_home, run_id, *, reason, update):
        """The parked cases land, and THEN the manifest write fails — the
        shape that would duplicate successors on the retry if the
        close-out looked them up by content instead of by record."""
        if reason.startswith("packet 1 abandoned") and not refusals:
            refusals.append(reason)
            raise steward.gitops.GitOpsError("simulated manifest write failure")
        return real_update(actual_home, run_id, reason=reason, update=update)

    monkeypatch.setattr(steward, "_update_manifest", refuse_the_first_close_out)

    third = None
    for _ in range(3):
        third = steward.run(home)
    assert third is not None and third.run_id is not None
    run_id = third.run_id

    manifest = _head_manifest(home, run_id)
    packet = manifest["packets"][0]
    assert len(refusals) == 1
    # positive control: the successor cases really were committed before
    # the manifest write failed, so the retry has something to reuse
    assert len(cases.list_cases(home, parked_reason="attempts-exhausted")) == 2
    assert packet["phase"] != "abandoned" and manifest["status"] == "unfinished"
    assert packet["attempt_count"] == 3
    assert "close-out-failed" in steward.journal_path(home).read_text(encoding="utf-8")

    fourth = steward.run(home)

    assert fourth.calls == 0 and sorted(fourth.abandoned) == sorted(ids)
    manifest = _head_manifest(home, run_id)
    assert manifest["packets"][0]["phase"] == "abandoned"
    # the retry counted nothing of its own, and reused both successors
    assert manifest["packets"][0]["attempt_count"] == 3
    assert manifest["status"] == "complete"
    rows = cases.list_cases(home, parked_reason="attempts-exhausted")
    assert len(rows) == 2
    assert sorted(row["case"] for row in rows) == sorted(
        manifest["packets"][0]["dispositions"][rid]["successor_case"] for rid in ids
    )


def test_the_abandoned_observation_is_written_once_however_often_it_is_retried(
    tmp_path, monkeypatch
):
    """A close-out is retried until it lands, so the `abandoned` later
    observation it appends to an item's existing case (02-schema §3a.2,
    section 6) has to be idempotent. A reserved-id collision here would
    be raised, swallowed as `close-out-failed`, and retried forever."""
    home = make_home(tmp_path)
    rid = _seed_fresh_proposals(home, 1)[0]
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_hook_stage)
    assert steward.run(home).status == "applied"
    case_id = cases.list_cases(home, parked_for="overseer")[0]["case"]
    # positive control: the case starts with no later observations at all
    before = cases.show(home, case_id, evidence_only=False).sections["Later observations"]
    assert before.strip() == "(none)"

    steward._observe_abandonment(home, case_id, rid, "case-0000dead")
    steward._observe_abandonment(home, case_id, rid, "case-0000dead")

    after = cases.show(home, case_id, evidence_only=False).sections["Later observations"]
    assert after.count("steward abandoned:") == 1
    assert "case-0000dead" in after and rid in after


def test_failure_detail_is_committed_bounded_and_secret_scanned(tmp_path, monkeypatch):
    """A23 and 02-schema §3a: the real message, at most 2,000 characters
    with a trailing ellipsis, and a scan hit REDACTS the detail while the
    attempt record still commits with its kind and counts."""
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    long_detail = "API Error: 400 " + ("verbose " * 600)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        lambda spec: Outcome(ok=False, rc=1, stdout="", detail=long_detail, failure="exit"),
    )

    first = steward.run(home)
    assert first.run_id is not None
    packet = _head_manifest(home, first.run_id)["packets"][0]
    detail = packet["failure_detail"]
    assert detail.startswith("API Error: 400 verbose")
    assert len(detail) == 2000 and detail.endswith("…")
    assert packet["failure"] == "exit"

    secret_home = make_home(tmp_path / "secret-ledger")
    _seed_fresh_proposals(secret_home, 1)
    _enable_steward(secret_home)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        lambda spec: Outcome(
            ok=False, rc=1, stdout="",
            detail="transport refused with AKIAIOSFODNN7EXAMPLE in the header",
            failure="exit",
        ),
    )

    second = steward.run(secret_home)
    assert second.run_id is not None
    packet = _head_manifest(secret_home, second.run_id)["packets"][0]
    assert packet["failure_detail"] == "<redacted: secret-scan>"
    # a trace is never suppressed by its own content
    assert packet["failure"] == "exit" and packet["attempt_count"] == 1


def test_a_zero_call_attempt_arms_the_committed_cooldown_without_the_cache(
    tmp_path, monkeypatch
):
    """A19/A22 and S-68: "every attempt arms the cooldown, including an
    attempt that makes zero model calls". The cache is a projection any
    restart can lose; the committed `last_attempt_at` is what survives."""
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_hook_stage)
    monkeypatch.setattr(steward.batch, "write_receipt", _failing_receipt)
    # a controlled clock, because `chrono.now_iso` has one-second
    # resolution and both runs finish inside the same second
    clock = ["2026-09-01T04:15:00Z"]
    monkeypatch.setattr(steward.chrono, "now_iso", lambda: clock[0])

    first = steward.run(home)
    assert first.run_id is not None
    first_stamp = _head_manifest(home, first.run_id)["last_attempt_at"]
    assert first_stamp == clock[0]

    clock[0] = "2026-09-02T04:15:00Z"
    second = steward.run(home)
    assert second.calls == 0
    second_stamp = _head_manifest(home, first.run_id)["last_attempt_at"]
    assert second_stamp == clock[0] > first_stamp

    cache = steward.cache_dir(home)
    shutil.rmtree(cache)
    cooldown, _source = settings.resolve_setting(
        home, settings.by_name("steward.cooldown_secs")
    )
    assert cooldown == 72000

    # the first attempt's cooldown has expired, the zero-call one's has not
    assert serve._steward_is_due(home, cache, _iso_epoch(first_stamp) + cooldown + 1) is False
    # positive control: past the zero-call attempt's own cooldown it IS due
    shutil.rmtree(cache, ignore_errors=True)
    assert serve._steward_is_due(home, cache, _iso_epoch(second_stamp) + cooldown + 1) is True


def test_dry_run_reattempts_a_stuck_packet_and_writes_nothing(tmp_path, monkeypatch):
    """`steward run --dry-run` is a rehearsal: it re-drives the stuck
    packets with real model calls and touches neither the ledger nor the
    attempt counts, so it can never suppress the real run behind it."""
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _transport_failure)

    first = steward.run(home)
    assert first.run_id is not None
    before_head = git(home, "rev-parse", "HEAD").stdout.strip()
    before_manifest = _head_manifest(home, first.run_id)

    calls = []

    def rehearse(spec):
        calls.append(spec)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", rehearse)
    rehearsal = steward.run(home, dry_run=True)

    assert rehearsal.status == "dry-run" and len(calls) == 1
    assert git(home, "rev-parse", "HEAD").stdout.strip() == before_head
    assert _head_manifest(home, first.run_id) == before_manifest
    assert before_manifest["packets"][0]["attempt_count"] == 1
    journal = steward.journal_path(home).read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in journal if '"status":"attempt-start"' in line) == 1
