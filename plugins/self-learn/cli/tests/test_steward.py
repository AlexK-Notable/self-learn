"""U10 -- crash-safe steward runner and its CLI/scheduler surfaces."""

from __future__ import annotations

import fcntl
import io
import json
import re
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
    settings,
    statements,
    steward,
    user_model,
    verbs,
)
from self_learn.ledger_ops import create_record
from self_learn.invocation.contract import Outcome
from self_learn.invocation_sdk.backend import SdkOutcome
from self_learn.records import Record
from test_recover_or_refuse import _plant_stop
from support import commit_all, git, make_behavior, make_home, proposal_dict


def _seed_fresh_proposals(home: Path, count: int) -> list[str]:
    ids = []
    for n in range(count):
        rid = f"lrn-{n + 1:08x}"
        create_record(home, make_behavior(record_id=rid))
        ledger_ops.write_proposal(home, rid, proposal_dict())
        ledger_ops.stamp_proposal(home, rid)
        ids.append(rid)
    commit_all(home, "seed steward queue")
    return ids


def _enable_steward(home: Path) -> None:
    (home / "config.yaml").write_text("steward:\n  enabled: true\n", encoding="utf-8")
    commit_all(home, "enable steward")


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


class SimulatedKill(BaseException):
    pass


def _case_path(home: Path, case_id: str) -> Path:
    return next((home / "cases").glob(f"*/{case_id}.md"))


def test_crash_after_batch_before_receipt_replays_once_on_next_run(tmp_path, monkeypatch):
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

    run_record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    crashed = json.loads(run_record.read_text(encoding="utf-8"))
    case_id = next(iter(crashed["case_ids"].values()))
    assert "sheet=" not in _case_path(home, case_id).read_text(encoding="utf-8")

    steward.run(home)
    steward.run(home)

    lines = [
        line
        for line in _case_path(home, case_id).read_text(encoding="utf-8").splitlines()
        if "sheet=" in line
    ]
    assert len(lines) == 1
    assert "item=1" in lines[0] and "reject" in lines[0]


def test_crash_after_case_before_batch_records_abandonment_and_successor(tmp_path, monkeypatch):
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

    crashed_record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    crashed = json.loads(crashed_record.read_text(encoding="utf-8"))
    abandoned_id = next(iter(crashed["case_ids"].values()))

    result = steward.run(home)

    assert result.status == "applied"
    successor = [row for row in steward.cases.list_cases(home, record_id=rid) if row["case"] != abandoned_id]
    assert len(successor) == 1
    assert successor[0]["supersedes"] == abandoned_id
    abandoned_text = _case_path(home, abandoned_id).read_text(encoding="utf-8")
    assert f"steward abandoned: run {crashed['run_id']} crashed before apply" in abandoned_text


def test_crash_after_maintenance_rewrites_the_run_record_on_next_start(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    real_write = steward._write_json
    killed = False

    def kill_before_final_record(path, data):
        nonlocal killed
        if not killed and data.get("finished_at") and data.get("status") == "applied":
            killed = True
            raise SimulatedKill()
        return real_write(path, data)

    monkeypatch.setattr(steward, "_write_json", kill_before_final_record)
    with pytest.raises(SimulatedKill):
        steward.run(home)

    record_path = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    assert json.loads(record_path.read_text(encoding="utf-8"))["status"] == "maintenance-complete"

    result = steward.run(home)

    assert result.status == "idle"
    recovered = json.loads(record_path.read_text(encoding="utf-8"))
    assert recovered["status"] == "applied"
    assert recovered["last_run_outcome"] == "applied"
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
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    prompts = []

    def always_invalid(spec):
        prompts.append(spec.prompt)
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        sheet = next((Path(match.group(1)) / "sheets").glob("*.yaml"))
        _dump_yaml(sheet, {"version": 1, "unexpected": []})
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", always_invalid)
    result = steward.run(home)

    assert result.status == "partial" and result.calls == 2
    assert [row["id"] for row in ledger_ops.list_items(home)] == ids
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    packet = json.loads(record.read_text(encoding="utf-8"))["packets"][0]
    assert packet["bound"] == "schema-repair" and "unexpected" in packet["error"]


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

    assert steward._forced_parking_reason(home, sheet) == "always-loaded-user-scope"

    git(host, "rm", "--cached", "-q", "CLAUDE.md")
    assert steward._forced_parking_reason(home, sheet) is None


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


def test_cli_steward_run_exit_codes_and_json(monkeypatch, capsys, tmp_path):
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
        "stopped": [],
    }


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
