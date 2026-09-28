"""Batch 2026-09-28, part 4: follow-ups the user delegated.

The user, 2026-09-28 15:17 PDT: "i trust you to deal with the questions."
The questions were raised by the builders of batch-0928 (merge 9940b03);
the orchestrator decided them under that delegation. One test group per
follow-up:

1. A moved lesson updates both files.
2. A host that keeps refusing tells the user once.
3. A secret hit outside the overseer's pairs costs that file's contents.
4. An all-dropped run says so.
5. The steward cannot read the transcript copies.

Sandbox ledger and host repos under pytest's tmpdir; fake model sessions.
"""

from __future__ import annotations

import json

import pytest

from self_learn import ledger_ops, steward, verbs
from support import commit_all, git, make_env
from test_batch0928_post_run_recompile import _journal_rows, _refusing_hook
from test_steward import _enable_steward
from test_steward_refusals import _dispositions, _notifications, _seed, _writer


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")


# ------------------------------------------------ 1. a moved lesson's old file


def _stale_line_in_s(tmp_path, rid):
    """A lesson routed into skill s, then reopened with its host write
    left undone (a refused host commit, R3): it is pending again, keeps its
    routing block, and s's SKILL.md still carries its line."""
    env = make_env(tmp_path, skills=("s", "t"))
    home = env.ledger
    _seed(home, rid)
    verbs.route(home, rid, dest="skill-md", no_push=True)
    ledger_ops.reopen_record(home, rid)
    commit_all(home, f"reopen {rid}, host write left undone")
    return env, home


def test_a_rehomed_lesson_leaves_the_file_it_moved_out_of(tmp_path, monkeypatch):
    rid = "lrn-f1000001"
    env, home = _stale_line_in_s(tmp_path, rid)
    s_md = env.host / "plugins/s-plugin/skills/s/SKILL.md"
    assert rid in s_md.read_text()  # positive control: the stale line is there
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            (rid, [rid], [{"id": rid, "verb": "rehome", "to": "skill:t"}], "rehome", "rehome"),
        ]),
    )

    result = steward.run(home)

    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"
    assert (home / "skills/t/pending" / f"{rid}.md").is_file()
    assert rid not in s_md.read_text()
    assert git(env.host, "status", "--porcelain", "-uall").stdout.strip() == ""
    (row,) = _journal_rows(home, "recompile")
    assert row["changed"] == [str(s_md)]
    assert result.recompile_skipped == []


def test_move_origins_names_the_bucket_before_the_move(tmp_path):
    rid = "lrn-f1000002"
    env, home = _stale_line_in_s(tmp_path, rid)

    class Item:
        def __init__(self, verb):
            self.id, self.verb = rid, verb

    assert verbs.move_origins(home, [Item("rehome"), Item("rescope"), Item("reject")]) == [
        (rid, home / "skills" / "s"), (rid, home / "skills" / "s"),
    ]


def test_the_overseer_also_clears_the_file_a_rehomed_lesson_left(tmp_path, monkeypatch):
    from self_learn import cases
    from self_learn.overseer import run as overseer_run
    from test_failstate_overseer import _ok, _phase_a, _phase_b_common
    from test_overseer_run import _dump, _enabled

    rid = "lrn-f1000003"
    env, home = _stale_line_in_s(tmp_path, rid)
    s_md = env.host / "plugins/s-plugin/skills/s/SKILL.md"
    assert rid in s_md.read_text()  # positive control
    _enabled(monkeypatch)
    parked_path = tmp_path / "parked.yaml"
    _dump(parked_path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "where does this belong?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_path, actor="steward")

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _phase_b_common(stage)
            _dump(stage / "case-r.yaml", {
                "kind": "resolution", "trigger": "weekly", "outcome": "rehome",
                "records": [rid], "scope": "skill:s", "question": "where?",
                "supersedes": parked,
                "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
                "decision": {"verb": "rehome", "because": "it is about t", "confidence": "settled"},
            })
            _dump(stage / "sheet-r.yaml", {
                "version": 1, "items": [{"id": rid, "verb": "rehome", "to": "skill:t"}],
            })
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)

    result = overseer_run.run(home, no_push=True)

    assert (home / "skills/t/pending" / f"{rid}.md").is_file()
    assert rid not in s_md.read_text()
    assert result.recompile_skipped == ()


# ------------------------------------------- 2. a refusing host tells once


def _told(sent):
    return [summary for _cue, summary, _ids in sent if "refused self-learn's commit" in summary]


def test_a_host_that_keeps_refusing_tells_the_user_once_per_cause(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    _refusing_hook(tmp_path, env.host, times=None)
    skill_md = env.skill_dir / "SKILL.md"

    def one_run(rid):
        _seed(home, rid)
        monkeypatch.setattr(
            steward.invocation, "write_session",
            _writer(lambda ids: [
                (rid, [rid], [{"id": rid, "verb": "route", "dest": "skill-md"}], "route", "route"),
            ]),
        )
        return steward.run(home)

    first = one_run("lrn-f2000001")
    assert len(first.recompile_skipped) == 1  # positive control: the pass was refused
    (told,) = _told(sent)
    assert str(skill_md) in told and "test-hook: REFUSED the staged changes" in told

    second = one_run("lrn-f2000002")
    assert len(second.recompile_skipped) == 1  # refused again, same cause
    assert len(_told(sent)) == 1  # not told again

    hook = tmp_path / "refusing-hooks" / "pre-commit"
    hook.write_text(hook.read_text().replace("REFUSED the staged changes", "REFUSED: signing key missing"))
    third = one_run("lrn-f2000003")
    assert len(third.recompile_skipped) == 1
    assert len(_told(sent)) == 2 and "signing key missing" in _told(sent)[1]
    rows = _journal_rows(home, steward.HOST_REFUSED_TOLD)
    assert [row["run_id"] for row in rows] == [first.run_id, third.run_id]


def test_host_refusal_causes_keep_only_hook_refusals_and_strip_ids():
    skipped = [
        "/h/SKILL.md: host commit refused: git commit -m x -- /h/SKILL.md failed: "
        "hook said no; request id: req_abc123 — put back",
        "/h/SKILL.md: host commit refused: git commit -m y -- /h/SKILL.md failed: "
        "hook said no; request id: req_zzz999 — put back",
        "/h/CLAUDE.md: dirty",
    ]
    assert verbs.host_refusal_causes(skipped) == ["/h/SKILL.md: hook said no;"]


def test_the_overseer_tells_a_host_refusal_once_too(tmp_path, monkeypatch):
    from self_learn import cases
    from self_learn.overseer import run as overseer_run
    from test_failstate_overseer import _ok, _phase_a, _phase_b_common
    from test_overseer_run import _dump, _enabled

    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    sent = _notifications(monkeypatch)
    rid = _seed(home, "lrn-f2000004")
    parked_path = tmp_path / "parked.yaml"
    _dump(parked_path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "route this?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_path, actor="steward")

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _phase_b_common(stage)
            _dump(stage / "case-r.yaml", {
                "kind": "resolution", "trigger": "weekly", "outcome": "route",
                "records": [rid], "scope": "skill:s", "question": "route?",
                "supersedes": parked,
                "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
                "decision": {"verb": "route", "because": "it holds", "confidence": "settled"},
            })
            _dump(stage / "sheet-r.yaml", {
                "version": 1, "items": [{"id": rid, "verb": "route", "dest": "skill-md"}],
            })
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    _refusing_hook(tmp_path, env.host, times=None)

    result = overseer_run.run(home, no_push=True)

    assert len(result.recompile_skipped) == 1  # positive control
    (told,) = _told(sent)
    assert "test-hook: REFUSED the staged changes" in told
    rows = [
        json.loads(line)
        for line in overseer_run.journal_path(home).read_text().splitlines()
        if overseer_run.HOST_REFUSED_TOLD in line
    ]
    assert [row["run"] for row in rows] == [result.run]


# ------------------------- 3. a secret outside the pairs costs that file only


def _files_under(root, text):
    out = []
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            try:
                if text in path.read_text(encoding="utf-8", errors="replace"):
                    out.append(str(path))
            except OSError:
                pass
    return out


@pytest.mark.parametrize("where", ["findings.yaml", "user-model-delta.yaml", "report.md"])
def test_a_secret_in_an_output_file_costs_that_file_not_the_run(tmp_path, monkeypatch, where):
    from self_learn import cases
    from self_learn.overseer import run as overseer_run
    from test_heading_evidence import _ledger_files_with
    from test_overseer_run import _enabled, _refused_section, _seed_parked_reject, _silence_notifications
    from test_secret_evidence import _fake_github_token, _overseer_phases

    token = _fake_github_token(31)
    home = make_env(tmp_path).ledger
    rid, parked = _seed_parked_reject(home, tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _overseer_phases(
        monkeypatch, rid, parked, [{"ref": f"record:{rid}", "quote": "status: pending"}],
        report_extra=" model-prose-marker",
    )
    phases = overseer_run.invocation.write_session

    def leaky(spec):
        outcome = phases(spec)
        if spec.label != "phase-a":
            path = spec.cwd / where
            path.write_text(path.read_text(encoding="utf-8") + f"# {token}\n", encoding="utf-8")
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", leaky)

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.applied) == ("applied", 1), result
    assert [r for r in cases.list_cases(home, record_id=rid) if r["case"] != parked]
    refused = _refused_section(home)
    assert refused.strip(), "positive control: the section rendered"
    assert f"{where}: withheld — the secret scan matched github-token" in refused
    assert _ledger_files_with(home, "status: pending")  # positive control for the grep
    assert _ledger_files_with(home, token) == []
    assert _files_under(tmp_path, token) == []
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    if where == "report.md":
        assert "model-prose-marker" not in report  # the model's text is withheld
    else:
        assert "model-prose-marker" in report  # the model's report is kept whole


# ------------------------------------------------- 4. an all-dropped run


@pytest.mark.parametrize("leak", [False, True, "invalid"])
def test_an_overseer_run_whose_decisions_were_all_dropped_says_so(tmp_path, monkeypatch, leak):
    import argparse
    import contextlib
    import io

    from self_learn.overseer import cli as overseer_cli
    from test_overseer_run import _enabled, _seed_parked_reject, _silence_notifications
    from test_secret_evidence import _fake_github_token, _overseer_phases

    token = _fake_github_token(41)
    home = make_env(tmp_path).ledger
    rid, parked = _seed_parked_reject(home, tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    # leak: the one decided case carries a secret in `because` (dropped by
    # the secret scan) or lacks its required fields ("invalid", dropped by
    # the pair's own validation); otherwise (the control) it applies.
    _overseer_phases(
        monkeypatch, rid, parked, [{"ref": f"record:{rid}", "quote": "status: pending"}],
        because=f"it leaked {token}" if leak is True else "too narrow",
        raw_case="kind: resolution\ntrigger: nightly\n" if leak == "invalid" else None,
    )

    def cli_run(as_json):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = overseer_cli.dispatch(argparse.Namespace(
                overseer_command="run", dry_run=False, json=as_json,
            ))
        return code, out.getvalue()

    code, text = cli_run(True)
    data = json.loads(text)
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    decided = report.split("## Decided in the user's stead\n", 1)[1].split("\n## ", 1)[0]
    assert data["status"] == "applied" and code == 0  # the machine value is unchanged
    if leak:
        assert data["applied"] == 0
        assert (data["decisions_staged"], data["decisions_dropped"]) == (1, 1)
        assert data["status_text"] == "applied (0 of 1; 1 dropped)"
        assert "- decisions: 0 of 1 reached the ledger; 1 dropped" in decided
    else:
        assert data["applied"] == 1  # positive control: the decision landed
        assert (data["decisions_staged"], data["decisions_dropped"]) == (1, 0)
        assert data["status_text"] == "applied"
        assert "decisions:" not in decided


def test_the_cli_text_line_carries_the_counts(capsys, monkeypatch):
    import argparse

    from self_learn.overseer import cli as overseer_cli
    from self_learn.overseer import run as overseer_run

    result = overseer_run.RunResult(
        "applied", 0, "r1", decisions_staged=3, decisions_dropped=3,
    )
    monkeypatch.setattr(overseer_run, "run", lambda *a, **kw: result)
    overseer_cli.dispatch(argparse.Namespace(overseer_command="run", dry_run=False, json=False))
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith("self-learn overseer: applied (0 of 3; 3 dropped); examined=0")
    assert overseer_run.RunResult("applied", 0, "r").status_text == "applied"


# ------------------------------- 5. the steward cannot read the kept copies


def _verdict(decide, tool, tool_input) -> str:
    import asyncio

    return type(asyncio.run(decide(tool, tool_input, None))).__name__


def test_the_steward_may_not_read_the_kept_session_copies(tmp_path, monkeypatch):
    from self_learn import session_copies
    from self_learn.invocation_sdk import charter

    home = make_env(tmp_path).ledger
    sessions = session_copies.sessions_dir(home)
    copy = sessions / "steward" / "run-1" / "abc.jsonl"
    copy.parent.mkdir(parents=True)
    copy.write_text("{}", encoding="utf-8")
    projects = tmp_path / "claude" / "projects" / "-home-x" / "abc.jsonl"
    projects.parent.mkdir(parents=True)
    projects.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run"
    (run_dir / "steward").mkdir(parents=True)
    (run_dir / "steward" / "link.jsonl").symlink_to(copy)

    spec = steward._session_spec(home, run_dir, "prompt", label="decision")
    assert spec.containment.read_denied == (str(sessions),)
    decide = charter.build_can_use_tool(spec.containment, cwd=run_dir)
    allow, deny = "PermissionResultAllow", "PermissionResultDeny"
    # Positive controls: its evidence reads, and its own stage, stay open.
    assert _verdict(decide, "Read", {"file_path": str(projects)}) == allow
    assert _verdict(decide, "Grep", {"pattern": "x", "path": str(projects.parent)}) == allow
    assert _verdict(decide, "Grep", {"pattern": "x"}) == allow
    assert _verdict(decide, "Read", {"file_path": str(run_dir / "steward" / "brief.md")}) == allow
    # The kept copies: refused, by path, by search, by glob and through a link.
    assert _verdict(decide, "Read", {"file_path": str(copy)}) == deny
    assert _verdict(decide, "Grep", {"pattern": "x", "path": str(sessions)}) == deny
    assert _verdict(decide, "Grep", {"pattern": "x", "path": str(sessions.parent)}) == deny
    assert _verdict(decide, "Glob", {"pattern": f"{sessions}/**/*.jsonl"}) == deny
    assert _verdict(decide, "Read", {"file_path": str(run_dir / "steward" / "link.jsonl")}) == deny
