"""O-3: two-phase overseer runner, parser, report, and journal guards."""

from __future__ import annotations

import argparse
import hashlib
import json
import io
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import batch, cases, execution_evidence, gitops, intents, settings, verbs, worker
from self_learn import overseer as overseer_package
from self_learn.invocation import Outcome
from self_learn.ledger_ops import create_record, find_record_path, stamp_proposal, write_proposal
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
                ("user-model-delta.yaml", {"updates": []}),
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


def _fake_hook_phases(
    monkeypatch, rid, parked, *, extra_refusal=False, close_call=False
):
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
            _dump(stage / "user-model-delta.yaml", {"updates": []})
            _dump(stage / "case-hook.yaml", {
                "kind": "resolution", "trigger": "nightly", "outcome": "route",
                "records": [rid], "scope": "skill:s", "question": "activate this hook?",
                "supersedes": parked,
                "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
                "decision": {"verb": "route", "because": "guard is specific", "confidence": "settled"},
            })
            items = [
                {
                    "id": rid,
                    "verb": "route",
                    "dest": "hook",
                    **({"close_call": True} if close_call else {}),
                }
            ]
            if extra_refusal:
                items.append({"id": rid, "verb": "undefer"})
            _dump(stage / "sheet-hook.yaml", {"version": 1, "items": items})
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
            _dump(stage / "user-model-delta.yaml", {"updates": []})
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def _fake_reference_reconsider_phases(monkeypatch, rid, parked):
    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
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
            _dump(stage / "user-model-delta.yaml", {"updates": []})
            _dump(stage / "case-reconsider.yaml", {
                "kind": "reconsider", "trigger": "reconsider", "outcome": "reject",
                "records": [rid], "scope": "skill:s", "question": "correct reference route?",
                "supersedes": parked,
                "evidence": [{"ref": f"record:{rid}", "quote": "status: routed"}],
                "decision": {"verb": "reject", "because": "route was wrong", "confidence": "settled"},
            })
            _dump(stage / "sheet-reconsider.yaml", {
                "version": 1, "items": [{"id": rid, "verb": "reject"}],
            })
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
    _rid, case_id = _seed_decided_case(home, tmp_path)
    _fake_selected_phases(monkeypatch, case_id)
    calls: list[object] = []
    real_invoke = overseer_run.invocation.write_session

    def capture(spec):
        calls.append(spec)
        return real_invoke(spec)

    monkeypatch.setattr(overseer_run.invocation, "write_session", capture)
    result = overseer_run.run(home, dry_run=True, no_push=True)
    assert result.status == "dry-run"
    assert len(calls) == 2
    assert "steward rationale" not in calls[0].prompt.lower()
    assert "steward rationale" in calls[1].prompt.lower()
    assert calls[0].surface == calls[1].surface == "overseer"
    assert calls[0].cwd.name == "overseer"
    assert calls[0].containment.allowed_tools == "Read,Grep,Glob,Write"
    assert calls[0].containment.disallowed_tools == "Bash"
    blind_view = calls[0].cwd / "blind" / f"{case_id}.md"
    assert "## Decision" not in blind_view.read_text(encoding="utf-8")


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
    assert not (home / "overseer").exists()


def test_coverage_precedes_uncapped_parked_intake(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _fake_two_phase(monkeypatch)
    _enabled(monkeypatch)
    parked = [{"case": f"case-{n:08x}", "superseded_by": None} for n in range(75)]
    captured = []
    real_list = overseer_run.cases.list_cases

    def listed(given_home, **kwargs):
        if kwargs.get("parked_for") == "overseer":
            assert (overseer_run.worker.stage_dir() / "overseer" / "coverage.yaml").is_file()
            assert (home / "overseer" / "coverage.yaml").is_file()
            assert kwargs.get("only_ok") is True
            return parked
        return real_list(given_home, **kwargs)

    monkeypatch.setattr(overseer_run.cases, "list_cases", listed)
    monkeypatch.setattr(
        overseer_run,
        "_full_inputs",
        lambda home, stage, selected, parked_rows: captured.extend(parked_rows),
    )
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "applied"
    assert captured == parked


def test_failed_activation_hook_line_names_the_record_once(tmp_path, monkeypatch):
    """Observed by hand 2026-09-14: O-2b's failure text already leads with the record id,
    and the runner prefixed it again ("lrn-…: lrn-…: routed … but activation failed").
    A foreign file at the hook's symlink path makes activation refuse."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
    (claude_dir / "hooks").mkdir(parents=True)
    (claude_dir / "settings.json").write_bytes(b'{"existing": true}\n')
    foreign = claude_dir / "hooks" / f"self-learn-{rid.removeprefix('lrn-')}-about-to-edit-storage.sh"
    foreign.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    monkeypatch.setattr(overseer_run.notify, "send", lambda *args: None)
    (home / "config.yaml").write_text("overseer:\n  hook_activation: true\n", encoding="utf-8")
    commit_all(home, "enable hook activation")

    overseer_run.run(home, dry_run=False, no_push=True)

    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    hooks = report.split("## Hooks\n", 1)[1].split("\n## User model", 1)[0]
    assert "activation failed" in hooks, "positive control: the failure line is present"
    assert hooks.startswith(f"- {rid}: routed"), hooks
    assert f"{rid}: {rid}:" not in hooks


def test_phase_b_runaway_applies_nothing(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _fake_two_phase(monkeypatch, a_turns=2, b_turns=48)
    applied = []
    monkeypatch.setattr(overseer_run.batch, "run", lambda *a, **kw: applied.append((a, kw)))
    _enabled(monkeypatch)
    result = overseer_run.run(home, dry_run=False, no_push=True)
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
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.json"
    original_settings = b'{"existing": true}\n'
    settings_path.write_bytes(original_settings)
    notices = []
    monkeypatch.setattr(
        overseer_run.notify,
        "send",
        lambda actual_home, cue, summary, ids: notices.append(
            (actual_home, cue, summary, ids)
        ),
    )
    if gate:
        (home / "config.yaml").write_text("overseer:\n  hook_activation: true\n", encoding="utf-8")
        commit_all(home, "enable hook activation")

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied"
    assert result.applied == 1
    assert len(notices) == 1
    assert notices[0][1] == ("hook-activated" if gate else "routine")
    assert notices[0][3][0] == rid
    if not gate:
        assert settings_path.read_bytes() == original_settings
    else:
        links = list((claude_dir / "hooks").iterdir())
        assert len(links) == 1
        assert links[0].is_symlink()
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
    record_path = next(home.glob(f"skills/*/resolved/{rid}.md"))
    assert "By: overseer" in __import__("subprocess").run(
        ["git", "-C", str(home), "log", "--format=%B", "--", str(record_path.relative_to(home))],
        check=True, capture_output=True, text=True,
    ).stdout


def test_close_call_sheet_metadata_raises_the_coalesced_cue(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, close_call=True)
    notices = []
    monkeypatch.setattr(
        overseer_run.notify,
        "send",
        lambda actual_home, cue, summary, ids: notices.append((cue, ids)),
    )
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "applied"
    assert notices == [("close-call", [rid])]


def test_dry_run_preview_reports_sheet_apply_and_refusal_counts(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _fake_hook_phases(monkeypatch, rid, parked, extra_refusal=True)
    result = overseer_run.run(home, dry_run=True, no_push=True)
    text = Path(result.report).read_text(encoding="utf-8")
    assert result.status == "dry-run"
    assert "- Dry-run preview: 1 sheet(s); 1 would apply; 1 would refuse" in text


def test_secret_scan_names_files_and_applies_nothing(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch, secret=True)
    applied = []
    notices = []
    notice_lock_states = []
    monkeypatch.setattr(overseer_run.batch, "run", lambda *a, **kw: applied.append((a, kw)))

    def notified(actual_home, cue, summary, ids):
        notices.append((actual_home, cue, summary, ids))
        notice_lock_states.append(str(gitops.commit_lock_path(home)) in gitops._held_locks)

    monkeypatch.setattr(overseer_run.notify, "send", notified)
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "refused"
    assert result.code == 1
    assert applied == []
    assert not (home / "overseer" / "latest-report.md").exists()
    report = Path(result.report).read_text(encoding="utf-8")
    assert "report.md" in report
    assert "ghp_" not in report
    assert notices == [
        (home, "routine", "overseer refused: secret-hit report.md", [result.run])
    ]
    assert notice_lock_states == [False]
    assert overseer_run.read_journal(home)[-1]["reason"] == "secret-hit report.md"


def test_report_is_written_before_notification(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch)
    observed = []

    def send(actual_home, cue, summary, ids):
        observed.append(
            (
                actual_home == home,
                cue,
                (home / "overseer" / "latest-report.md").is_file(),
                str(gitops.commit_lock_path(home)) in gitops._held_locks,
            )
        )

    monkeypatch.setattr(overseer_run.notify, "send", send)
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "applied"
    assert observed == [(True, "routine", True, False)]
    assert not os.path.islink(home / "overseer" / "latest-report.md")
    cached = overseer_run.last_run_iso_from_cache(worker.cache_dir(home))
    assert cached == overseer_run.status(home)["last_run_at"]


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
    assert "the user-model delta leg lands in a later unit" not in text


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


def test_o4_text_status_falls_back_to_committed_coverage_last_run(
    tmp_path, monkeypatch, capsys
):
    home = make_home(tmp_path)
    coverage = home / "overseer" / "coverage.yaml"
    coverage.parent.mkdir(parents=True, exist_ok=True)
    _dump(coverage, {"version": 1, "last_run_at": "2026-09-14T16:00:00Z"})
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="verb", required=True)
    overseer_cli.add_parser(sub)
    args = parser.parse_args(["overseer", "status"])
    monkeypatch.setattr(overseer_cli, "resolve_home", lambda: home)
    assert overseer_cli.dispatch(args) == 0
    assert "last run 2026-09-14T16:00:00Z" in capsys.readouterr().out


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


def test_write_stage_refuses_outside_stage_before_mkdir(tmp_path):
    stage = tmp_path / "stage"
    outside = tmp_path / "ledger" / "outside.md"
    with pytest.raises(overseer_run.OverseerError, match="outside overseer stage"):
        overseer_run._write_stage(stage, outside, "nope\n")
    assert not outside.exists()
    assert not outside.parent.exists()
    inside = stage / "inside.md"
    overseer_run._write_stage(stage, inside, "yes\n")
    assert inside.read_text(encoding="utf-8") == "yes\n"


def test_reference_reconsider_refusal_is_committed_and_not_retried(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = "lrn-0f0e0d0c"
    create_record(home, make_behavior(record_id=rid))
    write_proposal(home, rid, proposal_dict(destination="reference"))
    stamp_proposal(home, rid)
    commit_all(home, "reference seed")
    verbs.route(home, rid, dest="reference", no_push=True)
    record_path = find_record_path(home, rid)
    before = record_path.read_bytes()
    parked_stage = tmp_path / "parked-reference.yaml"
    _dump(parked_stage, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "correct reference route?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: routed"}],
        "decision": {"verb": "parked", "because": "needs review", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_stage, actor="steward")
    _enabled(monkeypatch)
    _fake_reference_reconsider_phases(monkeypatch, rid, parked)
    calls = []
    real_run = overseer_run.batch.run

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(overseer_run.batch, "run", counted)
    result = overseer_run.run(home, dry_run=False, no_push=True)
    message = (
        f"reject {rid}: a reconsider correction of a routed 'reference'-destination "
        "record is not supported here"
    )
    text = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert result.status == "partial"
    assert message in text.partition("## Refused / could not do")[2]
    assert len(calls) == 1
    assert record_path.read_bytes() == before
    assert not __import__("subprocess").run(
        ["git", "-C", str(home), "status", "--porcelain"], check=True,
        capture_output=True, text=True,
    ).stdout
    assert __import__("subprocess").run(
        ["git", "-C", str(home), "log", "-1", "--format=%B", "--", "overseer/latest-report.md"],
        check=True, capture_output=True, text=True,
    ).stdout
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("refusal recovery must not invoke the model"),
    )
    recovered = overseer_run.run(home, dry_run=False, no_push=True)
    assert recovered.status == "refused"
    assert len(calls) == 1
    assert execution_evidence.read_manifest(home, result.run)["status"] == "complete"


def test_run_exit_8_when_a_sheet_applies_and_refuses(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_refusal=True)
    fake = batch.BatchResult(
        items=[
            batch.ItemResult(n=1, id=rid, verb="route", rc=0, state="applied"),
            batch.ItemResult(n=2, id=rid, verb="reject", rc=1, state="refused", detail="refused"),
        ],
        process_code=1, sheet_sha="01234567", actor="overseer",
    )
    monkeypatch.setattr(overseer_run.batch, "run", lambda *args, **kwargs: fake)
    monkeypatch.setattr(overseer_run.batch, "write_receipt", lambda *args, **kwargs: {})
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert (result.code, result.status, result.applied, result.refused) == (8, "partial", 1, 1)


def test_failed_boundary_push_keeps_applied_status_and_records_failure(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    fake = batch.BatchResult(
        items=[batch.ItemResult(n=1, id=rid, verb="route", rc=0, state="applied")],
        process_code=0, sheet_sha="01234567", actor="overseer",
    )
    monkeypatch.setattr(overseer_run.batch, "run", lambda *args, **kwargs: fake)
    monkeypatch.setattr(overseer_run.batch, "write_receipt", lambda *args, **kwargs: {})
    push = verbs.PushReport(entries=[(home, gitops.PushResult(ok=False, detail="offline"))])
    monkeypatch.setattr(overseer_run.verbs, "push_pending", lambda given_home: push)
    result = overseer_run.run(home, dry_run=False, no_push=False)
    text = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert (result.code, result.status) == (3, "applied")
    assert "push: failed (3)" in text
    assert overseer_run.read_journal(home)[-1]["push"] == "push: failed (3)"


def test_model_report_owned_facts_truncate_model_prose_not_the_run(tmp_path):
    path = tmp_path / "report.md"
    headings = [
        "Examined", "Decided in the user's stead", "Hooks", "User model",
        "Catalogue health", "Questions for you", "Refused / could not do",
    ]
    lines = ["# draft"]
    for heading in headings:
        lines.extend([f"## {heading}", "- model prose"])
    lines.extend("- more model prose" for _ in range(57 - len(lines)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    text = overseer_run._finalize_model_report(
        path, date="2026-09-14", run_id="12345678", model="m", selected=(),
        population_count=0, excluded=0, model_calls=2, guard=50,
        refusals=["first refusal", "second refusal"],
    )
    assert len(text.splitlines()) <= 60
    assert "- model report truncated:" in text


def test_runner_added_lines_remove_bare_none_placeholders(tmp_path):
    path = tmp_path / "report.md"
    headings = [
        "Examined", "Decided in the user's stead", "Hooks", "User model",
        "Catalogue health", "Questions for you", "Refused / could not do",
    ]
    path.write_text(
        "# draft\n" + "\n".join(f"## {heading}\n- none" for heading in headings) + "\n",
        encoding="utf-8",
    )
    text = overseer_run._finalize_model_report(
        path, date="2026-09-14", run_id="12345678", model="m", selected=(),
        population_count=0, excluded=0, model_calls=2, guard=50,
        refusals=[], hooks=["lrn-0123abcd: route applied"],
        user_model_lines=["um-abcd: add applied"],
    )
    hooks = text.split("## Hooks\n", 1)[1].split("\n## User model", 1)[0]
    model = text.split("## User model\n", 1)[1].split("\n## Catalogue health", 1)[0]
    assert hooks == "- lrn-0123abcd: route applied"
    assert model == "- um-abcd: add applied"


def test_runner_template_refused_section_has_no_placeholder_beside_a_reason():
    """The runner-owned template (refused runs, partial runs) must not print the
    run-level reason and then a '- none'.  Positive control: no reason, no refusals
    keeps the placeholder."""
    kwargs = dict(date="2026-09-14", run_id="12345678", model="m", selected=(),
                  population_count=0, excluded=0, model_calls=2, guard=50)
    quiet = overseer_run._report_text(**kwargs)
    assert quiet.split("## Refused / could not do\n", 1)[1].strip() == "- none"
    refused = overseer_run._report_text(**kwargs, reason="sheet-1.yaml: item 1 close_call must be boolean")
    section = refused.split("## Refused / could not do\n", 1)[1].strip()
    assert section == "- sheet-1.yaml: item 1 close_call must be boolean"
    both = overseer_run._report_text(**kwargs, reason="run ended early", refused=["item 2 refused"])
    assert both.split("## Refused / could not do\n", 1)[1].strip() == "- run ended early\n- item 2 refused"


def test_examined_and_refused_sections_lose_the_placeholder_too(tmp_path):
    """Observed by hand 2026-09-14: the runner's facts and refusals were followed by the
    model's own "- none".  Positive control first: the runner-written lines are present."""
    path = tmp_path / "report.md"
    headings = [
        "Examined", "Decided in the user's stead", "Hooks", "User model",
        "Catalogue health", "Questions for you", "Refused / could not do",
    ]
    path.write_text(
        "# draft\n" + "\n".join(f"## {heading}\n- none" for heading in headings) + "\n",
        encoding="utf-8",
    )
    text = overseer_run._finalize_model_report(
        path, date="2026-09-14", run_id="12345678", model="m", selected=("case-1",),
        population_count=1, excluded=0, model_calls=2, guard=50,
        refusals=["sheet-1.yaml: item 1 close_call must be boolean"], hooks=[],
        user_model_lines=[],
    )
    examined = text.split("## Examined\n", 1)[1].split("\n## Decided", 1)[0]
    refused = text.split("## Refused / could not do\n", 1)[1].strip()
    assert "- Model calls this run: 2 of the runaway guard 50" in examined
    assert "- none" not in examined
    assert refused == "- sheet-1.yaml: item 1 close_call must be boolean"
    decided = text.split("## Decided in the user's stead\n", 1)[1].split("\n## Hooks", 1)[0]
    assert decided == "- none", "a section the runner leaves alone keeps its placeholder"


def test_late_finalize_failure_after_apply_is_partial_and_finishes_intent(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    monkeypatch.setattr(
        overseer_run, "_finalize_model_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            overseer_run.OverseerError("report.md: code-owned facts make the report exceed 60 lines")
        ),
    )
    result = overseer_run.run(home, dry_run=False, no_push=True)
    report = home / "overseer" / "latest-report.md"
    dated_reports = list((home / "overseer").glob("????-??-??-report.md"))
    assert (result.status, result.code, result.applied) == ("partial", 8, 1)
    assert report.is_file()
    assert len(dated_reports) == 1
    assert "run ended early: report.md: code-owned facts make the report exceed 60 lines" in report.read_text(encoding="utf-8")
    recovered = intents.recover(home)
    assert not recovered.stopped
    assert recovered.restored == []
    assert overseer_run.status(home)["last_run_at"] is not None


def test_receipt_failure_after_applied_sheet_retries_and_stays_partial(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    real_receipt = overseer_run.batch.write_receipt
    calls = []

    def write_then_raise(*args, **kwargs):
        calls.append(True)
        receipt = real_receipt(*args, **kwargs)
        if len(calls) == 1:
            raise RuntimeError("receipt postcondition failed")
        return receipt

    monkeypatch.setattr(overseer_run.batch, "write_receipt", write_then_raise)
    result = overseer_run.run(home, dry_run=False, no_push=True)
    successor = next(row["case"] for row in cases.list_cases(home, only_ok=True) if row.get("supersedes") == parked)
    application = cases.show(home, successor, evidence_only=False).sections["Application"]
    assert (result.status, result.code, result.applied) == ("partial", 8, 1)
    assert len(calls) == 2
    assert "sheet-hook.yaml" in application


def test_invalid_raw_report_refuses_before_any_decision_and_leaves_a_trace(
    tmp_path, monkeypatch
):
    """Rewritten for S-68 A15 (2026-09-19).  It used to assert that NOTHING
    under `overseer/` existed after an invalid raw report.  A staged-output
    schema failure is a retryable failed attempt under ruling 1, and A15
    requires every failed attempt to leave a COMMITTED trace with its real
    reason — a week lost to a validator was previously invisible in the
    ledger.  Everything the test actually guarded is kept and named: no
    decision applied, no coverage advance, no published report, clean tree."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch)
    real_invoke = overseer_run.invocation.write_session

    def oversized(spec):
        outcome = real_invoke(spec)
        if spec.label == "phase-b":
            with (spec.cwd / "report.md").open("a", encoding="utf-8") as fh:
                fh.write("- excess model prose\n" * 50)
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", oversized)
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert (result.status, result.code) == ("refused", 1)
    # The trace A15 asks for, committed, naming the real reason.
    week = overseer_run.week_key(overseer_run.week_boundary(__import__("time").time()))
    notes = overseer_run._committed_failure_notes(home, week)
    assert len(notes) == 1, notes
    note = __import__("subprocess").run(
        ["git", "-C", str(home), "show", f"HEAD:{notes[0]}"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "- failure: schema-repair" in note
    assert "60-line limit" in note
    # What the old assertion was really protecting: nothing was decided,
    # coverage did not advance (A5), no report was published, tree clean.
    assert not (home / "overseer" / "coverage.yaml").exists()
    assert not (home / "overseer" / "latest-report.md").exists()
    assert not (home / "overseer" / "open-questions.yaml").exists()
    assert [row for row in cases.list_cases(home, only_ok=True) if row.get("actor") == "overseer"] == []
    assert not __import__("subprocess").run(
        ["git", "-C", str(home), "status", "--porcelain"], check=True,
        capture_output=True, text=True,
    ).stdout


def test_committed_recipe_precedes_reserved_successor_and_binds_exact_sheet(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    real_record = overseer_run.cases.record
    observed = []

    def record(given_home, stage_file, *, actor, reserved_id=None):
        data = YAML(typ="safe").load(Path(stage_file).read_text(encoding="utf-8"))
        run_id = data.get("run_id")
        if actor == "overseer":
            assert reserved_id is not None
            manifest = execution_evidence.read_manifest(given_home, run_id)
            recipe = manifest["cases"][reserved_id]
            digest = hashlib.sha256(recipe["sheet"].encode("utf-8")).hexdigest()
            assert recipe["sheet_sha"] == digest[:8]
            assert recipe["sheet_digest"] == digest
            assert recipe["items"] == [
                {"n": 1, "id": rid, "verb": "route", "close_call": False}
            ]
            observed.append((run_id, reserved_id))
        return real_record(
            given_home, stage_file, actor=actor, reserved_id=reserved_id
        )

    monkeypatch.setattr(overseer_run.cases, "record", record)
    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied"
    assert observed == [(result.run, observed[0][1])]
    manifest = execution_evidence.read_manifest(home, result.run)
    assert manifest["actor"] == "overseer"
    assert manifest["status"] == "complete"
    successor = cases.show(home, observed[0][1], evidence_only=False)
    assert successor.frontmatter["run_id"] == result.run


def test_whole_sheet_stop_with_no_items_halts_without_zip_and_stays_unfinished(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    stopped = batch.BatchResult(
        items=[], process_code=6, sheet_sha="01234567", actor="overseer",
        stop_message="ledger STOP before sheet",
    )
    monkeypatch.setattr(overseer_run.batch, "run", lambda *args, **kwargs: stopped)
    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code, result.applied) == ("partial", 8, 0)
    assert "ledger STOP before sheet" in Path(result.report).read_text(encoding="utf-8")
    assert execution_evidence.read_manifest(home, result.run)["status"] == "unfinished"


def test_restart_discovers_committed_work_after_cache_deletion_without_model_call(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    calls = []

    def halt_after_checkpoint(*args, continuation, checkpoint, **kwargs):
        calls.append(("first", continuation.case_id, dict(continuation.completed)))
        partial = batch.BatchResult(
            items=[batch.ItemResult(n=1, id=rid, verb="route", rc=0, state="applied")],
            process_code=0, case=continuation.case_id,
            sheet_sha=args[1].sheet_sha, actor="overseer",
        )
        assert checkpoint(partial)["state"] == "ok"
        raise batch.BookkeepingHalt("killed after apply", partial, [])

    monkeypatch.setattr(overseer_run.batch, "run", halt_after_checkpoint)
    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert first.status == "partial"
    assert overseer_run.has_unfinished_work(home)

    cache = overseer_run.worker.cache_dir(home)
    __import__("shutil").rmtree(cache, ignore_errors=True)
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("recovery must not invoke the model"),
    )

    def resume(*args, continuation, checkpoint, **kwargs):
        calls.append(("resume", continuation.case_id, dict(continuation.completed)))
        assert set(continuation.completed) == {1}
        return batch.BatchResult(
            items=list(continuation.completed.values()), process_code=0,
            case=continuation.case_id, sheet_sha=args[1].sheet_sha, actor="overseer",
        )

    monkeypatch.setattr(overseer_run.batch, "run", resume)
    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert (second.run, second.status) == (first.run, "applied")
    assert calls[0][1] == calls[1][1]
    assert not overseer_run.has_unfinished_work(home)
    assert len(list((home / "overseer").glob("????-??-??-report.md"))) == 1


def test_unfinished_manifest_is_due_from_git_not_the_worktree_or_cache(tmp_path):
    home = make_home(tmp_path)
    path = execution_evidence.manifest_path(home, "due-r2")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "run_id": "due-r2", "actor": "overseer", "status": "unfinished"}) + "\n",
        encoding="utf-8",
    )
    commit_all(home, "prepared overseer recipe")
    path.write_text("{}\n", encoding="utf-8")
    assert overseer_run.has_unfinished_work(home)
    assert overseer_package.has_unfinished_work(home)


def test_failed_ordered_checkpoint_halts_finalization(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    receipts = []

    def failed(*args, **kwargs):
        receipts.append(kwargs.get("prefix"))
        return {"state": "failed", "reason": "case receipt commit failed"}

    monkeypatch.setattr(overseer_run.batch, "write_receipt", failed)
    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code) == ("partial", 8)
    assert receipts and all(value is True for value in receipts)
    assert execution_evidence.read_manifest(home, result.run)["status"] == "unfinished"
    assert "case receipt" in Path(result.report).read_text(encoding="utf-8")


def test_matching_trailer_without_the_sheet_effect_is_not_proof(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-0badc0de"
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, "seed proof record")
    case_id = "case-0badc0de"
    case_stage = tmp_path / "proof-case.yaml"
    _dump(case_stage, {
        "kind": "resolution", "trigger": "weekly", "outcome": "reject",
        "records": [rid], "scope": "skill:s", "question": "reject it?",
        "evidence": [{"ref": f"record:{rid}", "quote": "pending"}],
        "decision": {"verb": "reject", "because": "evidence", "confidence": "settled"},
        "run_id": "proof-r2",
    })
    cases.record(home, case_stage, actor="overseer", reserved_id=case_id)
    sheet_path = tmp_path / "proof-sheet.yaml"
    _dump(sheet_path, {"version": 1, "case": case_id, "items": [{"id": rid, "verb": "reject"}]})
    sheet = batch.load_sheet(sheet_path, home=home)
    manifest = {
        "version": 1, "run_id": "proof-r2", "actor": "overseer",
        "status": "unfinished", "cases": {case_id: {
            "sheet": sheet_path.read_text(encoding="utf-8"),
            "sheet_sha": sheet.sheet_sha, "sheet_digest": sheet.sheet_digest,
            "items": [{"n": 1, "id": rid, "verb": "reject"}],
            "maintenance": [], "dispositions": [],
        }}, "ledger_effects": [],
    }
    manifest_path = execution_evidence.manifest_path(home, "proof-r2")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    commit_all(home, "prepare proof recipe")
    ref = execution_evidence.ExecutionRef(
        run_id="proof-r2", case_id=case_id, sheet_sha=sheet.sheet_sha,
        sheet_digest=sheet.sheet_digest, item=1, record_id=rid,
        verb="reject", actor="overseer",
    )
    record_path = find_record_path(home, rid)
    record_path.write_text(
        record_path.read_text(encoding="utf-8") + "\nUnrelated text.\n",
        encoding="utf-8",
    )
    gitops.stage_and_commit(
        home, [record_path], f"self-learn: reject {rid}",
        execution_evidence.render_trailers(ref),
    )

    with pytest.raises(overseer_run.OverseerError, match="does not establish"):
        overseer_run._mutation_proven_completed(
            home, manifest, case_id, manifest["cases"][case_id], {}
        )


def test_committed_effective_sheet_freezes_defer_default(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-00defe12"
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, "seed deferred recipe")
    parked_stage = tmp_path / "parked-defer.yaml"
    _dump(parked_stage, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "defer it?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "pending"}],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_stage, actor="steward")
    case_stage = tmp_path / "case-defer.yaml"
    _dump(case_stage, {
        "kind": "resolution", "trigger": "weekly", "outcome": "defer",
        "records": [rid], "scope": "skill:s", "question": "defer it?",
        "supersedes": parked,
        "evidence": [{"ref": f"record:{rid}", "quote": "pending"}],
        "decision": {"verb": "defer", "because": "wait", "confidence": "settled"},
    })
    sheet_path = tmp_path / "sheet-defer.yaml"
    _dump(sheet_path, {"version": 1, "items": [{"id": rid, "verb": "defer"}]})
    stage = tmp_path / "overseer-stage"
    stage.mkdir()
    (stage / "report.md").write_text("# report\n", encoding="utf-8")
    before = datetime.now(timezone.utc).date() + timedelta(days=30)
    manifest = overseer_run._prepare_manifest(
        home, stage, run_id="defer-r2", started="2026-09-15T00:00:00Z",
        model="m", selected=(), population_count=0, excluded=0,
        model_calls=2, guard=50, coverage_text="strata: {}\n",
        questions={"questions": []}, findings=[],
        prepared=[(case_stage, sheet_path, batch.load_sheet(sheet_path, home=home))],
    )
    frozen = YAML(typ="safe").load(
        next(iter(manifest["cases"].values()))["sheet"]
    )
    assert frozen["items"][0]["until"] == before.isoformat()


# ---------------------------------------------------------------- S-68 (U3)
#
# Liveness of a delegated run: a run left unfinished either makes progress on
# its next attempt or is closed out after `runs.attempt_cap` attempts, and no
# state is ever both "never retried" and "keeps the run open".


def _this_week():
    return overseer_run.week_key(overseer_run.week_boundary(time.time()))


def _git(home, *args):
    return subprocess.run(
        ["git", "-C", str(home), *args], check=True, capture_output=True, text=True,
    ).stdout


def _silence_notifications(monkeypatch):
    notices = []
    monkeypatch.setattr(
        overseer_run.notify, "send",
        lambda home, cue, summary, ids: notices.append((cue, summary, list(ids))),
    )
    return notices


def _fake_phases_by_label(monkeypatch, *, a_turns=2, b_turns=3):
    """`_fake_two_phase` keyed on `spec.label` instead of a call counter, so
    a test can drive the overseer more than once in one process."""
    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "empty"})
            _dump(stage / "initial-views.yaml", {"cases": []})
            turns = a_turns
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
            _dump(stage / "findings.yaml", {"findings": []})
            _dump(stage / "questions.yaml", {"questions": []})
            _dump(stage / "user-model-delta.yaml", {"updates": []})
            turns = b_turns
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": turns,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def _dispatch_returning(monkeypatch, rc, *, only_first=False, item_n=None):
    """Replace one ledger operation's outcome, counting every dispatch."""
    real_dispatch = batch._dispatch
    dispatched = []

    def patched(given_home, item, **kwargs):
        dispatched.append(item.n)
        spent = only_first and len(dispatched) > 1
        wrong_item = item_n is not None and item.n != item_n
        if spent or wrong_item:
            return real_dispatch(given_home, item, **kwargs)
        return batch.ItemResult(
            n=item.n, id=item.id, verb=item.verb, rc=rc, state="refused",
            detail="simulated one-off git failure",
        )

    monkeypatch.setattr(batch, "_dispatch", patched)
    return dispatched


def test_one_transient_exit_6_is_retried_and_the_next_run_completes(tmp_path, monkeypatch):
    """The 2026-09-19 reproduction, committed (A4).

    One ledger operation exits 6 -- which `batch.py` itself calls "a
    pre-mutation ledger-level failure -- nothing written, safe to retry".
    Run 1 stalls the item and the run stays unfinished.  Run 2 is healthy and
    re-dispatches the SAME item, and the run completes.  Run 3 finds the week
    done and holds.

    Before A4 a receipted `stopped` item sat beside a committed refusal in
    the never-retry set, so run 2 -- and every two-hourly run after it, for
    ever -- returned the same preserved partial result, made no model call,
    dispatched nothing, and committed a rewritten report each time.
    """
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    _silence_notifications(monkeypatch)
    dispatched = _dispatch_returning(monkeypatch, 6, only_first=True)

    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert first.status == "partial", "positive control: run 1 really did stall"
    assert dispatched == [1]
    assert overseer_run.has_unfinished_work(home)

    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a resume must not invoke the model"),
    )
    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 1], "the stopped item is re-dispatched, not frozen"
    assert (second.run, second.status) == (first.run, "applied")
    assert not overseer_run.has_unfinished_work(home)
    assert execution_evidence.read_manifest(home, first.run)["status"] == "complete"

    before_third = _git(home, "rev-parse", "HEAD").strip()
    third = overseer_run.run(home, dry_run=False, no_push=True)
    assert third.status == "held-week-done"
    assert dispatched == [1, 1], "a held run dispatches nothing"
    assert _git(home, "rev-parse", "HEAD").strip() == before_third


def test_a_permanent_failure_reaches_the_cap_and_closes_the_week(tmp_path, monkeypatch):
    """S-68 ruling 2, for the overseer: after `runs.attempt_cap` failed
    attempts the run CLOSES so a new run can start, the decision it could not
    settle becomes a question put to the user in its report, and one
    notification fires.  Before this the run stayed unfinished for ever."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    notices = _silence_notifications(monkeypatch)
    dispatched = _dispatch_returning(monkeypatch, 6)

    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert first.status == "partial"
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a resume must not invoke the model"),
    )
    second = overseer_run.run(home, dry_run=False, no_push=True)
    assert second.status == "partial", "positive control: attempt 2 ran and failed"
    assert execution_evidence.read_manifest(home, first.run)["status"] == "unfinished"

    notices.clear()
    overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 1, 1], "every attempt really re-drove the item"
    record = execution_evidence.read_manifest(home, first.run)
    assert record["status"] == "closed"
    assert record["outcome"] == "attempts-exhausted"
    assert record["attempt_count"] == 3
    # The question, in the report, where `overseer open` prints it.
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    block = report.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert "was closed after 3 failed attempts" in block, block
    assert "- none" not in block
    # The committed close-out note, and the notification.
    week = _this_week()
    assert f"overseer/failures/{week}/closed.md" in _git(
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "overseer/failures"
    )
    assert any("was closed after 3 failed attempts" in summary for _cue, summary, _ids in notices), notices
    # A NEW run can start: nothing committed is unfinished any more, and the
    # next week is not done.
    assert overseer_run._unfinished_manifest(home) is None
    next_boundary = overseer_run.week_boundary(time.time()) + 7 * 86400
    assert not overseer_run.week_done(home, next_boundary)


def test_a_sheets_tail_behind_a_refused_host_verb_is_never_lost(tmp_path, monkeypatch):
    """A12.  A refused host verb raises `BookkeepingHalt` with no receipt for
    the later items.  On resume the committed refusal is final -- it is never
    dispatched again -- but the items it left undispatched are reported as
    "not attempted" and the run stays UNFINISHED, instead of being stamped
    `complete` over a tail nobody will ever apply and nobody was ever told
    about (02-schema.md: "Completion is checked against every expected
    original `(sheet_sha, item)` key")."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_refusal=True)
    _silence_notifications(monkeypatch)
    dispatched = _dispatch_returning(monkeypatch, 1, item_n=1)

    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert first.status == "partial"
    assert dispatched == [1], "positive control: item 2 was never dispatched"

    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a resume must not invoke the model"),
    )
    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1], "a committed refusal is never dispatched again"
    assert second.status == "partial"
    assert execution_evidence.read_manifest(home, first.run)["status"] == "unfinished"
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    refused = report.split("## Refused / could not do\n", 1)[1]
    assert "item(s) 2 not attempted" in refused, refused


def test_a_failed_attempt_never_blanks_last_weeks_open_questions(tmp_path, monkeypatch):
    """A14.  Three failure paths wrote `questions={"questions": []}` over the
    committed index, so one failed week erased the questions the user had not
    answered yet.  No failure path writes that file at all now."""
    home = make_home(tmp_path)
    questions = home / "overseer" / "open-questions.yaml"
    questions.parent.mkdir(parents=True, exist_ok=True)
    _dump(questions, {"questions": [{"id": "um-1a2b@r1", "cases": ["case-00000001"]}]})
    commit_all(home, "seed last week's open questions")
    before = questions.read_bytes()
    assert b"um-1a2b@r1" in before, "positive control: the index is there to lose"

    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch, a_turns=2, b_turns=48)  # runaway after phase B
    _silence_notifications(monkeypatch)

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "runaway", "positive control: the attempt really failed"
    assert questions.read_bytes() == before
    assert _git(home, "status", "--porcelain") == ""


def test_coverage_does_not_advance_when_the_second_call_fails(tmp_path, monkeypatch):
    """A5.  Coverage, `last_run_at` included, was written and committed
    BEFORE the second model call; a failed call left the week counted as run
    and its cases counted as covered although nothing was examined."""
    home = make_home(tmp_path)
    coverage = home / "overseer" / "coverage.yaml"
    coverage.parent.mkdir(parents=True, exist_ok=True)
    _dump(coverage, {"version": 1, "last_run_at": "2026-09-01T04:15:00Z", "strata": {}})
    commit_all(home, "seed last run's coverage")
    before = coverage.read_bytes()
    assert b"2026-09-01T04:15:00Z" in before, "positive control: coverage is there to move"

    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch, a_turns=2, b_turns=48)
    _silence_notifications(monkeypatch)

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "runaway", "positive control: the second call really failed"
    assert coverage.read_bytes() == before
    assert _git(home, "status", "--porcelain") == ""


def test_a_second_report_on_the_same_day_does_not_overwrite_the_first(tmp_path, monkeypatch):
    """B4.  Two overseer runs on one UTC day published to the same
    `<date>-report.md`, so the second silently replaced the first."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    # Keyed on the phase LABEL, not on a call counter: this test runs the
    # overseer twice, so the second run's phase A is the third call.
    _fake_phases_by_label(monkeypatch, a_turns=2, b_turns=48)
    _silence_notifications(monkeypatch)

    first = overseer_run.run(home, dry_run=False, no_push=True)
    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert first.run != second.run
    assert (first.status, second.status) == ("runaway", "runaway")
    dated = sorted(
        p.name for p in (home / "overseer").glob("*-report*.md")
        if p.name != "latest-report.md"
    )
    assert len(dated) == 2, dated
    plain = next(name for name in dated if not name.endswith("-report-2.md"))
    numbered = next(name for name in dated if name.endswith("-report-2.md"))
    first_text = (home / "overseer" / plain).read_text(encoding="utf-8")
    assert f"run {first.run}" in first_text, f"the first report survived: {dated}"
    second_text = (home / "overseer" / numbered).read_text(encoding="utf-8")
    assert f"run {second.run}" in second_text
    latest = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert f"run {second.run}" in latest


def test_an_unreported_turn_count_fails_the_runaway_guard_closed(tmp_path, monkeypatch):
    """A10.  `int(getattr(outcome, "turns", 0) or 0)` read a missing turn
    count as ZERO -- the one value that can never trip the guard.
    `invocation.Outcome` carries no `turns` attribute at all and
    `invocation_sdk.SdkOutcome.turns` is `int | None`, so this is the shape a
    real session presents when it reports no count."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_two_phase(monkeypatch)
    _silence_notifications(monkeypatch)
    real_invoke = overseer_run.invocation.write_session

    def countless(spec):
        outcome = real_invoke(spec)
        if spec.label == "phase-a":
            return type("SdkLike", (), {
                "ok": True, "rc": 0, "stdout": "", "detail": "",
                "failure": None, "turns": None,
            })()
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", countless)
    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "runaway"
    text = Path(result.report).read_text(encoding="utf-8")
    assert "reported no turn count" in text, text
    assert len(overseer_run._committed_failure_notes(home, _this_week())) == 1


def _fake_caseless_phases(monkeypatch, rid, *, case_kind):
    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "none", "why_stopped": "none"})
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
            _dump(stage / "user-model-delta.yaml", {"updates": []})
            _dump(stage / "sheet.yaml", {
                "version": 1,
                "items": [{"id": rid, "verb": "note", "append": "catalogue change", "key": "u3-note"}],
            })
            if case_kind is not None:
                _dump(stage / "case.yaml", {
                    "kind": case_kind, "trigger": "weekly", "outcome": "no-action",
                    "records": [rid], "scope": "skill:s",
                    "question": "record the catalogue change?",
                    "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
                    "decision": {"verb": "note", "because": "catalogue upkeep", "confidence": "settled"},
                })
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


@pytest.mark.parametrize("case_kind", ["resolution", "reconsider"])
def test_a_caseless_sheets_paired_case_must_be_maintenance(tmp_path, monkeypatch, case_kind):
    """A9 / O-7.3.  `build-lane-b.md:24-31` recorded this half as not built:
    the runner refused a caseless sheet outright, so the rule that its paired
    case must be `kind: maintenance` had nothing to attach to."""
    home = make_home(tmp_path)
    rid = "lrn-0a0b0c0d"
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, "catalogue seed")
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_caseless_phases(monkeypatch, rid, case_kind=case_kind)
    monkeypatch.setattr(
        overseer_run.batch, "run",
        lambda *a, **kw: pytest.fail("a non-maintenance caseless pair reached batch.run"),
    )

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "refused"
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert f"kind: maintenance, not '{case_kind}'" in report, report


def test_a_maintenance_case_lets_a_caseless_sheet_through(tmp_path, monkeypatch):
    """The positive control for A9: the pairing the rule permits is accepted
    and applied, so the refusal above is a real classification and not a
    blanket "a caseless sheet is always refused"."""
    home = make_home(tmp_path)
    rid = "lrn-0a0b0c0d"
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, "catalogue seed")
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_caseless_phases(monkeypatch, rid, case_kind="maintenance")

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied", result.status
    assert result.applied == 1
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "kind: maintenance, not" not in report


def test_three_failed_phase_b_attempts_close_the_week_with_a_published_question(
    tmp_path, monkeypatch
):
    """The cap reached by attempts that never got as far as a run record.

    A failure before `_prepare_manifest` has no record to count on, so its
    committed failure note IS the count (S-68: "attempts are counted from
    committed evidence ... never from the cache alone").  The attempt that
    reaches the cap publishes its report, because the close-out's question
    has to land in `latest-report.md` -- the only file `overseer open` reads
    it from -- and the user is notified once."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_phases_by_label(monkeypatch, a_turns=2, b_turns=48)
    notices = _silence_notifications(monkeypatch)
    week = _this_week()

    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert first.status == "runaway"
    assert len(overseer_run._committed_failure_notes(home, week)) == 1
    assert not overseer_run.week_closed(home, week), "positive control: not yet at the cap"

    second = overseer_run.run(home, dry_run=False, no_push=True)
    assert second.status == "runaway"
    assert overseer_run.week_attempts(home, week) == 2
    notices.clear()

    third = overseer_run.run(home, dry_run=False, no_push=True)

    assert third.status == "runaway"
    assert overseer_run.week_closed(home, week)
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    block = report.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert "was closed after 3 failed attempts" in block, block
    assert f"overseer/failures/{week}/closed.md" in _git(
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "overseer/failures"
    )
    assert any("was closed after 3 failed attempts" in summary for _c, summary, _i in notices), notices

    # The week is now DONE, so the next tick holds instead of attempting --
    # and it does not close the week a second time.
    notices.clear()
    fourth = overseer_run.run(home, dry_run=False, no_push=True)
    assert fourth.status == "held-week-done"
    assert notices == []
    assert overseer_run.week_attempts(home, week) == 3


def test_a_close_out_the_cap_earned_but_no_run_wrote_is_written_before_the_hold(
    tmp_path, monkeypatch
):
    """The close-out is checked BEFORE the same-week hold.

    A week at the cap makes `week_done` true, so if the run that reached the
    cap could not write its close-out -- or was killed between the two --
    every later run would answer `held-week-done` and the question would
    never be written, for ever.  That is the S-68 shape one level up.  The
    close-out is retried, counts nothing of its own, and is idempotent."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _fake_phases_by_label(monkeypatch, a_turns=2, b_turns=48)
    notices = _silence_notifications(monkeypatch)
    week = _this_week()
    real_close_out = overseer_run._close_out_if_exhausted
    monkeypatch.setattr(
        overseer_run, "_close_out_if_exhausted",
        lambda *a, **kw: (None, []),  # the cap is reached; nothing is written
    )

    for _ in range(3):
        overseer_run.run(home, dry_run=False, no_push=True)

    # positive control: the cap IS reached and the close-out is NOT written
    assert overseer_run.week_attempts(home, week) == 3
    assert not overseer_run.week_closed(home, week)
    assert overseer_run.week_done(home, overseer_run.week_boundary(time.time()))
    monkeypatch.setattr(overseer_run, "_close_out_if_exhausted", real_close_out)
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a pending close-out makes no model call"),
    )
    notices.clear()

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "closed", result.status
    assert overseer_run.week_closed(home, week)
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    block = report.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert "was closed after 3 failed attempts" in block, block
    assert any("was closed after 3 failed attempts" in summary for _c, summary, _i in notices), notices
    # It counted nothing of its own, and the next tick simply holds.
    assert overseer_run.week_attempts(home, week) == 3
    assert overseer_run.run(home, dry_run=False, no_push=True).status == "held-week-done"
