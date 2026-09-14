"""O-3: two-phase overseer runner, parser, report, and journal guards."""

from __future__ import annotations

import argparse
import json
import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, intents, settings
from self_learn.invocation import Outcome
from self_learn.ledger_ops import create_record, stamp_proposal, write_proposal
from self_learn.overseer import cli as overseer_cli
from self_learn.overseer import run as overseer_run
from support import commit_all, make_behavior, make_home, proposal_dict


def _enabled(monkeypatch):
    real = settings.resolve_setting

    def resolve(home, setting):
        if setting.name == "overseer.enabled":
            return True, "test"
        return real(home, setting)

    monkeypatch.setattr(settings, "resolve_setting", resolve)


def _fake_two_phase(monkeypatch, *, a_turns=2, b_turns=3, secret=False):
    calls = []

    def invoke(spec):
        calls.append(spec)
        stage = spec.cwd
        yaml = YAML()
        if len(calls) == 1:
            with (stage / "selection.yaml").open("w", encoding="utf-8") as fh:
                yaml.dump({"cases": [], "why_these": "none", "why_stopped": "empty"}, fh)
            with (stage / "initial-views.yaml").open("w", encoding="utf-8") as fh:
                yaml.dump({"cases": []}, fh)
            turns = a_turns
        else:
            report_lines = ["# model draft"]
            for heading in (
                "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do",
            ):
                report_lines.extend([f"## {heading}", "- none"])
            if secret:
                report_lines.append("token = ghp_abcdefghijklmnopqrstuvwxyz123456")
            (stage / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
            for name, data in (
                ("sheet.yaml", {"version": 1, "items": []}),
                ("findings.yaml", {"findings": []}),
                ("questions.yaml", {"questions": []}),
            ):
                with (stage / name).open("w", encoding="utf-8") as fh:
                    yaml.dump(data, fh)
            turns = b_turns
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "",
            "failure": None, "turns": turns,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    return calls


def _dump(path, data):
    stream = io.StringIO()
    YAML().dump(data, stream)
    path.write_text(stream.getvalue(), encoding="utf-8")


def _seed_parked_hook(home, tmp_path):
    rid = "lrn-0a0b0c0d"
    create_record(home, make_behavior(record_id=rid))
    write_proposal(
        home,
        rid,
        proposal_dict(
            destination="hook",
            alternates=["skill-md"],
            hook={
                "tools": ["Edit"],
                "path_regex": r"\.storage/",
                "deny_message": "stop first",
            },
            examples={
                "allow": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/ok.yaml"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/notes.md"}},
                ],
                "deny": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/.storage/x"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/y"}},
                ],
            },
        ),
    )
    stamp_proposal(home, rid)
    commit_all(home, "hook seed")
    path = tmp_path / "parked.yaml"
    _dump(path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "activate this hook?",
        "parked_for": "overseer", "parked_reason": "hook",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "parked", "because": "delegated decision", "confidence": "provisional"},
    })
    return rid, cases.record(home, path, actor="steward")


def _fake_hook_phases(monkeypatch, rid, parked):
    calls = []

    def invoke(spec):
        calls.append(spec)
        stage = spec.cwd
        if len(calls) == 1:
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "parked intake", "why_stopped": "none blind"})
            _dump(stage / "initial-views.yaml", {"cases": []})
        else:
            headings = [
                "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do",
            ]
            (stage / "report.md").write_text(
                "# draft\n" + "\n".join(f"## {h}\n- none" for h in headings) + "\n",
                encoding="utf-8",
            )
            _dump(stage / "findings.yaml", {"findings": []})
            _dump(stage / "questions.yaml", {"questions": []})
            _dump(stage / "case-hook.yaml", {
                "kind": "resolution", "trigger": "nightly", "outcome": "route",
                "records": [rid], "scope": "skill:s", "question": "activate this hook?",
                "supersedes": parked,
                "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
                "decision": {"verb": "route", "because": "guard is specific", "confidence": "settled"},
            })
            _dump(stage / "sheet-hook.yaml", {"version": 1, "items": [{"id": rid, "verb": "route", "dest": "hook"}]})
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def _seed_decided_case(home, tmp_path):
    rid = "lrn-01020304"
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, "record seed")
    path = tmp_path / "decided.yaml"
    _dump(path, {
        "kind": "resolution", "trigger": "nightly", "outcome": "reject",
        "records": [rid], "scope": "skill:s", "question": "keep this lesson?",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "reject", "because": "too narrow", "confidence": "settled"},
    })
    return rid, cases.record(home, path, actor="steward")


def _fake_selected_phases(monkeypatch, case_id):
    calls = []

    def invoke(spec):
        calls.append(spec)
        stage = spec.cwd
        if len(calls) == 1:
            _dump(stage / "selection.yaml", {"cases": [{"id": case_id}], "why_these": "oldest", "why_stopped": "one was clear"})
            _dump(stage / "initial-views.yaml", {"cases": [{
                "id": case_id, "what_i_would_do": "reject", "why": "narrow",
                "what_evidence_decides_it": "record evidence", "confidence": "clear",
            }]})
        else:
            headings = [
                "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do",
            ]
            (stage / "report.md").write_text(
                "# draft\n" + "\n".join(f"## {h}\n- none" for h in headings) + "\n",
                encoding="utf-8",
            )
            _dump(stage / "sheet.yaml", {"version": 1, "items": []})
            _dump(stage / "findings.yaml", {"findings": [{"case": case_id, "kind": "examined", "text": "decision held"}]})
            _dump(stage / "questions.yaml", {"questions": []})
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def test_stop_precedes_invocation(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    stopped = intents.RecoverResult(stopped=["deadbeef: mismatch"])
    monkeypatch.setattr(overseer_run.intents, "recover", lambda home: stopped)
    called = []
    monkeypatch.setattr(overseer_run.invocation, "write_session", lambda spec: called.append(spec))
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "stopped"
    assert result.code == 6
    assert called == []


def test_two_invocations_are_blind_then_full(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    calls = _fake_two_phase(monkeypatch)
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "dry-run"
    assert len(calls) == 2
    assert "steward rationale" not in calls[0].prompt.lower()
    assert "steward rationale" in calls[1].prompt.lower()
    assert calls[0].surface == calls[1].surface == "overseer"
    assert calls[0].cwd.name == "overseer"
    assert calls[0].containment.allowed_tools == "Read,Grep,Glob,Write"
    assert calls[0].containment.disallowed_tools == "Bash"


def test_no_push_is_read_once_at_the_run_boundary(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _fake_two_phase(monkeypatch)
    reads = []

    def requested():
        reads.append(True)
        return True

    monkeypatch.setattr(overseer_run.worker, "no_push_requested", requested)
    result = overseer_run.run(home, dry_run=True, no_push=None)
    assert result.status == "dry-run"
    assert reads == [True]


def test_phase_a_timeout_never_starts_b(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    calls = []

    def timeout(spec):
        calls.append(spec)
        return Outcome(False, None, "", "deadline", "timeout")

    monkeypatch.setattr(overseer_run.invocation, "write_session", timeout)
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "timed-out"
    assert result.code == 1
    assert len(calls) == 1
    assert not (home / "overseer").exists()


def test_runaway_after_a_never_starts_b(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    calls = _fake_two_phase(monkeypatch, a_turns=50)
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "runaway"
    assert result.code == 1
    assert result.model_calls == 50
    assert len(calls) == 1
    assert "runaway" in Path(result.report).read_text(encoding="utf-8").lower()


def test_coverage_precedes_uncapped_parked_intake(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _fake_two_phase(monkeypatch)
    parked = [{"case": f"case-{n:08x}", "superseded_by": None} for n in range(75)]
    captured = []
    real_list = overseer_run.cases.list_cases

    def listed(given_home, **kwargs):
        if kwargs.get("parked_for") == "overseer":
            assert (overseer_run.worker.stage_dir() / "overseer" / "coverage.yaml").is_file()
            assert kwargs.get("only_ok") is True
            return parked
        return real_list(given_home, **kwargs)

    monkeypatch.setattr(overseer_run.cases, "list_cases", listed)
    monkeypatch.setattr(
        overseer_run,
        "_full_inputs",
        lambda home, stage, selected, parked_rows: captured.extend(parked_rows),
    )
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "dry-run"
    assert captured == parked


def test_phase_b_runaway_applies_nothing(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _fake_two_phase(monkeypatch, a_turns=2, b_turns=48)
    applied = []
    monkeypatch.setattr(overseer_run.batch, "run", lambda *a, **kw: applied.append((a, kw)))
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "runaway"
    assert result.model_calls == 50
    assert applied == []


@pytest.mark.parametrize("gate", [False, True])
def test_hook_route_obeys_current_gate_and_writes_case_receipt(tmp_path, monkeypatch, gate):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
    if gate:
        (home / "config.yaml").write_text("overseer:\n  hook_activation: true\n", encoding="utf-8")
        commit_all(home, "enable hook activation")

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied"
    assert result.applied == 1
    successors = [row for row in cases.list_cases(home, only_ok=True) if row.get("supersedes") == parked]
    assert len(successors) == 1
    view = cases.show(home, successors[0]["case"], evidence_only=False)
    assert "sheet-hook.yaml" in view.sections["Application"]
    final_report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    if not gate:
        assert "delegated" in final_report
        assert "switched off" in final_report
    sheet_rows = [row for row in overseer_run.read_journal(home) if row.get("status") == "sheet"]
    assert len(sheet_rows) == 1
    assert len(sheet_rows[0]["sheet_sha"]) == 8
    assert sheet_rows[0]["stopped"] == 0
    settings_path = claude_dir / "settings.json"
    assert settings_path.exists() is gate
    record_path = next(home.glob(f"skills/*/resolved/{rid}.md"))
    assert "By: overseer" in __import__("subprocess").run(
        ["git", "-C", str(home), "log", "--format=%B", "--", str(record_path.relative_to(home))],
        check=True, capture_output=True, text=True,
    ).stdout


def test_secret_scan_names_files_and_applies_nothing(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch, secret=True)
    applied = []
    notices = []
    monkeypatch.setattr(overseer_run.batch, "run", lambda *a, **kw: applied.append((a, kw)))
    monkeypatch.setattr(overseer_run.worker, "_notify_with_ids", lambda message, ids: notices.append((message, ids)))
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "refused"
    assert result.code == 1
    assert applied == []
    assert not (home / "overseer" / "latest-report.md").exists()
    report = Path(result.report).read_text(encoding="utf-8")
    assert "report.md" in report
    assert "ghp_" not in report
    assert notices == [("overseer refused: secret-hit report.md", [])]
    assert overseer_run.read_journal(home)[-1]["reason"] == "secret-hit report.md"


def test_report_is_written_before_notification(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch)
    observed = []

    def notify(message, ids):
        observed.append((home / "overseer" / "latest-report.md").is_file())

    monkeypatch.setattr(overseer_run.worker, "_notify_with_ids", notify)
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "applied"
    assert observed == [True]


def test_report_names_sample_and_examined_observation_lands(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _rid, case_id = _seed_decided_case(home, tmp_path)
    _enabled(monkeypatch)
    _fake_selected_phases(monkeypatch, case_id)
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "applied"
    text = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert case_id in text
    view = cases.show(home, case_id, evidence_only=False)
    assert "examined" in view.sections["Later observations"]


def test_disabled_is_success_without_invocation(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    called = []
    monkeypatch.setattr(overseer_run.invocation, "write_session", lambda spec: called.append(spec))
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert (result.status, result.code, called) == ("disabled", 0, [])


def test_enabled_setting_is_config_only_and_defaults_false(tmp_path):
    setting = settings.by_name("overseer.enabled")
    assert setting.env_var is None
    assert setting.kind == "bool"
    assert settings.resolve_setting(tmp_path, setting) == (False, "default")


def test_cli_parser_surface_and_disabled_line(tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="verb", required=True)
    overseer_cli.add_parser(sub)
    args = parser.parse_args(["overseer", "run"])
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    code = overseer_cli.dispatch(args)
    assert code == 0
    assert capsys.readouterr().out == "self-learn overseer: disabled\n"


def test_status_reads_jsonl_journal(tmp_path):
    home = make_home(tmp_path)
    path = overseer_run.journal_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "applied", "run": "12345678"}) + "\n")
    assert overseer_run.status(home)["last"]["run"] == "12345678"


def test_report_lookup_by_date(tmp_path):
    home = make_home(tmp_path)
    directory = home / "overseer"
    directory.mkdir()
    report = directory / "2026-09-14-report.md"
    report.write_text("hello\n", encoding="utf-8")
    assert overseer_run.report(home, date="2026-09-14") == "hello\n"


def test_exit_decision_keeps_refused_partial_and_stop_distinct():
    assert overseer_run._worst_code([1], any_applied=False) == 1
    assert overseer_run._worst_code([0, 1], any_applied=True) == 8
    assert overseer_run._worst_code([6], any_applied=False) == 6


def test_reference_reconsider_refusal_is_copied_verbatim_to_report(tmp_path):
    path = tmp_path / "report.md"
    headings = [
        "Examined", "Decided in the user's stead", "Hooks", "User model",
        "Catalogue health", "Questions for you", "Refused / could not do",
    ]
    path.write_text("# draft\n" + "\n".join(f"## {h}\n- none" for h in headings) + "\n")
    refusal = "reconsider: reference destination is not supported"
    text = overseer_run._finalize_model_report(
        path, date="2026-09-14", run_id="12345678", model="m", selected=(),
        population_count=0, excluded=0, model_calls=2, guard=50, refusals=[refusal],
    )
    assert f"- {refusal}" in text
