"""S-160: effect filters, held versions and provable reviews. No real model."""
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import test_skill_write as sk1
from self_learn import cli, skill_scripts as scripts, skill_writer, settings
from self_learn.script_screen import screen
from self_learn.invocation_sdk import backend as sdk
from self_learn.invocation.contract import Containment
from self_learn.overseer import skills
from support import git

PY = "#!/usr/bin/env python3\n"
SH = "#!/usr/bin/env bash\nset -o noclobber\n"
GOOD = PY + 'import sys\nprint(len(sys.argv))\n'


@pytest.mark.parametrize("code,rule", [
    ("from os import remove", "effects"), ("io.FileIO('x', 'w')", "effects"), ("import socket", "imports"), ("import ssl", "imports"), ("import http", "imports"),
    ("import urllib", "imports"), ("import ftplib", "imports"), ("import smtplib", "imports"),
    ("import imaplib", "imports"), ("import poplib", "imports"), ("import telnetlib", "imports"),
    ("import xmlrpc", "imports"), ("import asyncio", "imports"), ("import requests", "imports"),
    ("import subprocess", "imports"), ("import shutil", "imports"), ("import importlib", "imports"),
    ("import json as j", "indirection"), ("eval('1')", "indirection"),
    ("exec('1')", "indirection"), ("getattr(x, 'run')()", "indirection"),
    ("open('out', 'w')", "open-mode"), ("open('out', 'a')", "open-mode"),
    ("open('out', 'r+')", "open-mode"), ("open('out', mode)", "open-mode"),
    ("open('out', 'x')", "output-path"), ("open(sys.argv[1], 'x', opener=f)", "open-mode"),
    ("os.remove('x')", "effects"), ("os.unlink('x')", "effects"), ("os.rmdir('x')", "effects"),
    ("os.rename('x','y')", "effects"), ("os.replace('x','y')", "effects"),
    ("os.truncate('x',0)", "effects"), ("os.system('ls')", "effects"), ("os.fork()", "effects"),
    ("os.putenv('x','y')", "os-effects"), ("os.popen('ls')", "effects"), ("os.execv('x',[])", "effects"),
    ("p.write_text('x')", "effects"), ("p.write_bytes(b'x')", "effects"),
    ("p.unlink()", "effects"), ("p.rename('x')", "effects"), ("p.replace('x')", "effects"),
    ("while True: pass", "bounded"), ("while x: pass", "bounded"),
    ("import itertools\nitertools.count()", "bounded"),
    ("open('.ssh/id_rsa')", "credentials"), ("open('.env')", "credentials"),
    ("open('credentials')", "credentials"), ("open('token')", "credentials"),
    ("open('hosts.yml')", "credentials"), ("open('.aws/config')", "credentials"),
    ("open('.gnupg/x')", "credentials"), ("open('x.key')", "credentials"),
    ("base64.b64decode('x')", "payload"), ("x.__class__", "effects"),
])
def test_python_refusals(code, rule):
    checked = screen(PY + code + "\n")
    assert not checked.ok
    assert any(r.startswith(rule + ":") for r in checked.rules), checked


@pytest.mark.parametrize("code,rule", [
    *[(cmd, "command") for cmd in ["curl x", "wget x", "nc x", "ssh x", "scp x", "rsync x", "telnet x", "pip x", "npm x", "uv x", "pacman x", "paru x", "apt x", "rm x", "rmdir x", "shred x", "truncate x", "mv x y", "dd x", "nohup x", "setsid x", "disown", "systemctl x", "crontab x", "at x"]],
    ("git status", "git"), ("git fetch", "git"), ("git push", "git"), ("git clone x", "git"),
    ("git cat-file --filters x", "git"), ("date --set=today", "command-effects"), ("sort --compress-program=bad x", "command-effects"), ("git remote", "git"), ("git diff --output=x", "git"),
    ('echo hi >| "$1"', "shell-effects"), ('echo hi >> "$1"', "shell-effects"),
    ('echo hi > out', "output-path"), ('echo hi &', "shell-effects"),
    ('source "$1"', "shell-syntax"), ('eval "$1"', "shell-syntax"),
    ('exec cat "$1"', "shell-syntax"), ('while true; do echo x; done', "shell-syntax"),
    ('echo $(curl x)', "shell-syntax"), ("sed -i s/a/b/ x", "sed-effects"),
    ("find . -delete", "find-effects"), ("find . -exec rm {} ;", "find-effects"),
    ("awk 'system(x)'", "awk-effects"), ("sort -o x y", "command-output"),
    ("cat /dev/tcp/x/80", "payload"), ("tail -f x", "bounded"), ("sed 's/a/b/w out'", "sed-effects"), ("sed 's~a~b~wout'", "sed-effects"), ("sed -f x", "sed-effects"),
])
def test_bash_refusals(code, rule):
    checked = screen(SH + code + "\n")
    assert not checked.ok
    assert any(r.startswith(rule + ":") for r in checked.rules), checked


@pytest.mark.parametrize("code", [GOOD, PY + 'import json\nprint(json.loads("[]"))\n',
    PY + 'import sys\nwith open(sys.argv[1], "x") as f:\n    f.write("report")\n',
    PY + 'import sys\nfrom pathlib import Path\nout = Path(sys.argv[1]) / "report.txt"\nwith out.open("x") as f:\n    f.write("new")\n',
    SH + 'wc -l "$1"\n', SH + 'cat "$1" | sort | uniq\n',
    SH + 'printf report > "$1"\n', SH + 'git --no-pager --no-optional-locks -c core.fsmonitor=false -c log.showSignature=false log --no-ext-diff --no-textconv --oneline\n',
    SH + "sed 's/a/b/g' \"$1\"\n",
])
def test_allowed(code):
    assert screen(code).ok, screen(code).rules


def test_language_syntax_and_noclobber():
    for code, rule in [("print(1)", "language"), (PY + "(", "syntax"), (SH + 'echo "', "syntax"), ("#!/bin/bash\necho x", "noclobber"), (PY + "#" * 64001, "size")]:
        assert any(r.startswith(rule + ":") for r in screen(code).rules)


@pytest.fixture
def env(tmp_path, monkeypatch):
    env = sk1.Env(tmp_path, monkeypatch)
    result = skill_writer.write(env.home, sk1.NAME, sk1.draft(), case=None, by="human", no_push=True)
    assert result.ok, result
    return env


def held(env, name="count", text=GOOD, usage="Run with a local input path to count arguments."):
    return scripts.draft(env.home, sk1.NAME, name=name, text=text, usage=usage, note="repeatable count")


def fake(monkeypatch, *, verdict="approve", init=(scripts.MODEL,), assistants=(scripts.MODEL,), raw=None):
    calls = []
    def run(self, spec):
        calls.append(spec)
        return sdk.SdkOutcome(ok=True, rc=0, stdout=raw if raw is not None else json.dumps({"verdict": verdict, "reasons": ["inspected effects"], "changes": ["remove hazards"] if verdict == "reject" else []}), detail="", failure=None, session_id="fake-session", cost_usd=0.12, init_models=init, assistant_models=assistants)
    monkeypatch.setattr(sdk.SdkBackend, "text_session", run)
    return calls


def test_draft_permissions_version_and_storage(env):
    a = held(env)
    assert a["state"] == "drafted" and a["review"] is None and a["screen"]["ok"]
    path = scripts._held(env.home, a)
    assert path.read_text() == GOOD and path.stat().st_mode & 0o111 == 0
    assert not (env.skill_dir() / "scripts/count").exists()
    assert held(env)["id"] == a["id"]
    b = held(env, usage="A different usage.")
    assert a["version"] != b["version"]
    with pytest.raises(ValueError, match="owned or registered"):
        scripts.draft(env.home, "foreign", name="count", text=GOOD, usage="Use it.", note="reason")
    assert "script draft" in git(env.home, "log", "-1", "--format=%s").stdout


@pytest.mark.parametrize("scenario,expected", [("approve", "active"), ("reject", "drafted"), ("wrong", "drafted"), ("mixed", "drafted"), ("unproven", "drafted"), ("missing-assistant", "drafted"), ("bad-json", "drafted")])
def test_review_proof(env, monkeypatch, scenario, expected):
    options = {"verdict": "reject"} if scenario == "reject" else {}
    if scenario == "wrong": options["init"] = ("other",)
    if scenario == "mixed": options["assistants"] = (scripts.MODEL, "other")
    if scenario == "unproven": options["init"] = ()
    if scenario == "missing-assistant": options["assistants"] = (None,)
    if scenario == "bad-json": options["raw"] = "yes"
    calls = fake(monkeypatch, **options)
    row = scripts.review(env.home, held(env)["id"], note="review now")
    assert row["state"] == expected
    assert len(calls) == 1 and isinstance(calls[0], sdk.TextOnlySpec)
    assert calls[0].model == scripts.MODEL and calls[0].resume_session_id is None
    assert scripts.LIMITS in json.loads(calls[0].prompt)["user_words"]
    review = row["review"]
    assert review["version"] == row["version"] and review["screen"]["ok"]
    if scenario in {"approve", "reject"}:
        assert review["model"] == scripts.MODEL and review["session"] == "fake-session" and review["cost_usd"] == .12
    else:
        assert review["verdict"] == "no review"
    with pytest.raises(ValueError, match="one review"):
        scripts.review(env.home, row["id"], note="retry")
    assert len(calls) == 1


def test_activation_and_writer(env, monkeypatch):
    fake(monkeypatch)
    row = held(env)
    before = env.head(env.root)
    result = scripts.review(env.home, row["id"], note="approve test")
    assert result["state"] == "active", result
    target = env.skill_dir() / "scripts/count"
    assert target.read_text() == GOOD and target.stat().st_mode & 0o111 == 0o111
    assert result["active_version"] == row["version"] and env.head(env.root) != before
    assert scripts.BEGIN in env.skill_md().read_text() and row["usage"] in env.skill_md().read_text()
    rewrite = skill_writer.draft_view(skill_writer.deployed_files(env.home, sk1.NAME))
    assert scripts.BEGIN not in rewrite["SKILL.md"] and "scripts/count" not in rewrite
    rewrite["SKILL.md"] += "\nManual instructions stay complete.\n"
    written = skill_writer.write(env.home, sk1.NAME, rewrite, case=None, by="human", no_push=True)
    assert written.ok, written
    assert target.read_text() == GOOD and target.stat().st_mode & 0o111
    assert scripts.BEGIN in env.skill_md().read_text()
    for extra in [{"scripts/new": GOOD}, {"scripts/count": GOOD}]:
        assert not skill_writer.check(env.home, sk1.NAME, {**rewrite, **extra}).ok
    rewrite["SKILL.md"] += "\n" + scripts.BEGIN + "\n" + scripts.END
    assert not skill_writer.check(env.home, sk1.NAME, rewrite).ok


@pytest.mark.parametrize("change", ["edit", "delete", "pending", "symlink", "usage", "markers"])
def test_audit_quarantines_without_data_loss(env, monkeypatch, change):
    fake(monkeypatch)
    row = scripts.review(env.home, held(env)["id"], note="test")
    assert row["state"] == "active"
    target = env.skill_dir() / "scripts/count"
    if change == "usage": env.skill_md().write_text(env.skill_md().read_text().replace(row["usage"], "user changed usage"))
    if change == "markers": env.skill_md().write_text(env.skill_md().read_text().replace(scripts.END, "user removed marker"))
    original_md = env.skill_md().read_bytes()
    if change == "edit": target.write_text("user's changed bytes")
    if change == "delete": target.unlink()
    if change == "symlink":
        target.unlink(); target.symlink_to(env.skill_md())
    if change == "pending":
        from self_learn import intents
        with intents.ledger_write(env.home):
            records = scripts.rows(env.home); records[0]["activation_pending"] = True
            scripts._save(env.home, records, "test interrupted")
    before = env.head(env.root)
    notices = scripts.audit(env.home)
    assert len(notices) == 1 and "count" in notices[0]
    result = scripts.get(env.home, row["id"])
    assert result["state"] == "drafted" and not target.exists()
    assert scripts.BEGIN not in env.skill_md().read_text() and env.head(env.root) != before
    if change != "delete":
        q = Path(result["quarantine"])
        assert str(q) in notices[0]
        if change == "symlink": assert q.is_symlink()
        else: assert q.read_text() == ("user's changed bytes" if change == "edit" else GOOD)
    if change in {"usage", "markers"}:
        assert Path(result["usage_quarantine"]).read_bytes() == original_md
        assert result["usage_quarantine"] in notices[0]
    assert scripts.audit(env.home) == []


def test_caps_screen_and_new_versions(env, monkeypatch):
    calls = fake(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_SCRIPT_REVIEWS_PER_DAY", "1")
    a = held(env)
    scripts.review(env.home, a["id"], note="first")
    b = held(env, name="second")
    with pytest.raises(ValueError, match="cap"):
        scripts.review(env.home, b["id"], note="second")
    bad = held(env, name="bad", text=PY + "import socket\n")
    with pytest.raises(ValueError, match="screen refused"):
        scripts.review(env.home, bad["id"], note="bad")
    assert len(calls) == 1 and scripts.get(env.home, b["id"])["review"] is None
    monkeypatch.setenv("SELF_LEARN_OVERSEER_SCRIPT_REVIEWS_PER_RUN", "1")
    scripts.review(env.home, b["id"], note="run first", run="r1")
    c = held(env, name="third")
    with pytest.raises(ValueError, match="cap"):
        scripts.review(env.home, c["id"], note="run second", run="r1")
    assert any("cap" in line for line in scripts.review_pending(env.home, "r1"))
    newer = held(env, text=GOOD + 'print("new")\n')
    assert newer["state"] == "drafted" and scripts.get(env.home, a["id"])["state"] == "drafted"
    with pytest.raises(ValueError, match="superseded"):
        scripts.review(env.home, a["id"], note="old")


def test_tampering_and_collision(env, monkeypatch):
    fake(monkeypatch)
    row = held(env)
    scripts._held(env.home, row).write_text(GOOD + "print(1)\n")
    with pytest.raises(ValueError, match="changed"):
        scripts.review(env.home, row["id"], note="changed")
    row = held(env, name="other")
    target = env.skill_dir() / "scripts/other"
    target.parent.mkdir(); target.write_text("user script")
    result = scripts.review(env.home, row["id"], note="collision")
    assert result["state"] == "approved" and "existing" in result["activation_error"]
    assert target.read_text() == "user script"


def test_cli_lifecycle(env, monkeypatch, capsys):
    fake(monkeypatch)
    source = env.tmp / "count"; source.write_text(GOOD)
    assert cli.main(["skill", "script", "draft", sk1.NAME, "--file", str(source), "--name", "count", "--usage", "Count arguments.", "--note", "test"]) == 0
    row = json.loads(capsys.readouterr().out)
    for args in [["list"], ["show", row["id"]], ["review", row["id"], "--note", "test"]]:
        assert cli.main(["skill", "script", *args]) == 0
        assert row["id"] in capsys.readouterr().out
    assert cli.main(["skill", "script", "deactivate", row["id"], "--note", "safe"]) == 0
    assert "deactivated" in capsys.readouterr().out
    assert scripts.get(env.home, row["id"])["state"] == "drafted"


def test_overseer_extract_and_hold(env, monkeypatch):
    files = {**sk1.draft(), "scripts/count": GOOD, "scripts/count.usage.md": "Count arguments."}
    prose, extracted = skills.extract_scripts(files)
    assert prose == sk1.draft() and extracted == [{"name": "count", "text": GOOD, "usage": "Count arguments."}]
    step = skills.SkillStep(action="write", name=sk1.NAME, updating=True, files=prose, scripts=extracted)
    assert skills.SkillStep.from_json(step.to_json()).scripts == extracted
    stage = env.tmp / "stage"
    for key, text in files.items():
        path = stage / "skills" / sk1.NAME / key
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    parsed = skills.step_for_case(env.home, stage, {"outcome": "restate", "decision": {"skill": {"name": sk1.NAME}}}, staged=skills.StagedSkills(), deploy=True)
    assert parsed is not None and parsed.scripts == extracted and parsed.files == prose
    result = skills.apply_write(env.home, "case-1234abcd", parsed, case_name="example")
    assert result.state == "applied", result
    assert scripts.rows(env.home)[0]["state"] == "drafted"
    assert not (env.skill_dir() / "scripts/count").exists()
    with pytest.raises(ValueError, match="companion"):
        skills.extract_scripts({"scripts/count": GOOD})


def test_sdk_proof_capture_and_no_tools(env, monkeypatch):
    from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock, ClaudeAgentOptions
    from self_learn.invocation_sdk.events import EventLog
    messages = [SystemMessage(subtype="init", data={"model": scripts.MODEL, "session_id": "proof"}),
        AssistantMessage(content=[TextBlock(text="first")], model=scripts.MODEL),
        AssistantMessage(content=[TextBlock(text="second")], model="different")]
    class Client:
        async def connect(self): pass
        async def query(self, prompt): pass
        async def receive_response(self):
            for message in messages: yield message
    monkeypatch.setattr(sdk.lifecycle, "child_pid_of", lambda _: None)
    spec = sdk.TextOnlySpec(surface="analyst", prompt="review", cwd=env.home, timeout=2,
        containment=Containment("", "", (), (), True, "default"), log=lambda _: None, model=scripts.MODEL)
    observed, sessions = [], []
    result, text = asyncio.run(sdk._run_session(spec, Client(), ClaudeAgentOptions(), EventLog(), lambda _: None, sessions.append, observed))
    assert observed == [("init", scripts.MODEL), ("assistant", scripts.MODEL), ("assistant", "different")]
    assert sessions == ["proof"] and text == "second"
    options = sdk.options_kwargs(spec)
    assert options["tools"] == [] and options["mcp_servers"] == {} and options["model"] == scripts.MODEL
    with pytest.raises(ValueError, match="cannot resume"):
        sdk.options_kwargs(replace(spec, resume_session_id="old"))


@pytest.mark.parametrize("entry", ["doctor", "recompile", "overseer"])
def test_integrity_entrypoints(env, monkeypatch, entry, capsys):
    from self_learn import verbs
    from self_learn.overseer import run as overrun
    fake(monkeypatch)
    row = scripts.review(env.home, held(env)["id"], note="test")
    target = env.skill_dir() / "scripts/count"
    target.write_text("changed")
    if entry == "doctor":
        cli.main(["doctor", "settings"])
    elif entry == "recompile":
        verbs.recompile(env.home, no_push=True)
    else:
        monkeypatch.setattr(overrun, "_run", lambda *a, **k: overrun.RunResult("test", 0, "test", 0, (), ()))
        overrun.run(env.home, no_push=True)
    assert scripts.get(env.home, row["id"])["state"] == "drafted"
    assert "deactivated" in capsys.readouterr().out


def test_sdk_outcome_carries_observed_models(env, monkeypatch):
    from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock, ResultMessage, ClaudeAgentOptions
    messages = [SystemMessage(subtype="init", data={"model": scripts.MODEL, "session_id": "fresh"}),
        AssistantMessage(content=[TextBlock(text="approved")], model=scripts.MODEL),
        ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="fresh", result="approved", total_cost_usd=.03)]
    class Client:
        async def connect(self): pass
        async def query(self, prompt): pass
        async def receive_response(self):
            for message in messages: yield message
    async def stop(*args): pass
    monkeypatch.setattr(sdk, "ClaudeSDKClient", lambda **kwargs: Client())
    monkeypatch.setattr(sdk, "_build_options", lambda *args: ClaudeAgentOptions())
    monkeypatch.setattr(sdk.lifecycle, "child_pid_of", lambda _: None)
    monkeypatch.setattr(sdk.lifecycle, "run_kill_ladder", stop)
    monkeypatch.setattr(sdk.lifecycle, "clear_sidecar", lambda *a, **k: None)
    monkeypatch.setattr(sdk.session_copies, "capture", lambda **k: None)
    logs = []
    monkeypatch.setattr(sdk, "write_event_log", lambda *a, **k: logs.append(k["meta"]))
    monkeypatch.setattr(sdk, "prune_event_logs", lambda *a: None)
    spec = sdk.TextOnlySpec(surface="analyst", prompt="review", cwd=env.home, timeout=2,
        containment=Containment("", "", (), (), True, "default"), log=lambda _: None, model=scripts.MODEL, skip_orphan_sweep=True)
    outcome = asyncio.run(sdk._drive(spec))
    assert outcome.ok and outcome.init_models == (scripts.MODEL,) and outcome.assistant_models == (scripts.MODEL,)
    assert outcome.session_id == "fresh" and outcome.cost_usd == .03
    assert logs[0]["model_observations"] == [("init", scripts.MODEL), ("assistant", scripts.MODEL)]


def test_review_failure_reservation_and_wrong_setting(env, monkeypatch):
    fake(monkeypatch)
    row = held(env)
    monkeypatch.setenv("SELF_LEARN_SCRIPT_REVIEW_MODEL", "other")
    with pytest.raises(ValueError, match="requires claude-fable"):
        scripts.review(env.home, row["id"], note="test")
    assert scripts.get(env.home, row["id"])["review"] is None
    monkeypatch.delenv("SELF_LEARN_SCRIPT_REVIEW_MODEL")
    def broken(self, spec):
        reserved = scripts.get(env.home, row["id"])
        assert reserved["review"]["verdict"] == "no review"
        raise OSError("fake invocation failure")
    monkeypatch.setattr(sdk.SdkBackend, "text_session", broken)
    result = scripts.review(env.home, row["id"], note="test")
    assert result["state"] == "drafted" and result["review"]["verdict"] == "no review"
    with pytest.raises(ValueError, match="one review"):
        scripts.review(env.home, row["id"], note="test")


def test_activation_failure_and_recovery(env, monkeypatch):
    fake(monkeypatch)
    row = held(env)
    original = env.skill_md().read_bytes()
    commit = scripts.gitops.commit
    def fail(repo, *args, **kwargs):
        if repo == env.root: raise OSError("fake host commit failure")
        return commit(repo, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(scripts.gitops, "commit", fail)
        result = scripts.review(env.home, row["id"], note="test")
    assert result["state"] == "approved" and result["activation_error"]
    assert not (env.skill_dir() / "scripts/count").exists()
    assert env.skill_md().read_bytes() == original
    assert Path(result["quarantine"]).read_text() == GOOD
    assert git(env.root, "status", "--porcelain").stdout == ""
    assert scripts.audit(env.home)
    assert scripts.get(env.home, row["id"])["state"] == "drafted"


def test_external_files_and_lifecycle_boundaries(env, monkeypatch):
    from support import commit_all
    fake(monkeypatch)
    external = env.skill_dir() / "scripts/external"
    external.parent.mkdir(); external.write_text("external helper")
    commit_all(env.root, "external script")
    row = scripts.review(env.home, held(env)["id"], note="test")
    assert row["state"] == "active"
    assert not skill_writer.retire(env.home, sk1.NAME, case=None, by="human", no_push=True).ok
    from self_learn.skill_writer import rename as rename_skill
    assert not rename_skill(env.home, sk1.NAME, "new-name", case=None, by="human", no_push=True).ok
    assert scripts.deactivate(env.home, row["id"], note="safe")
    assert external.read_text() == "external helper"
    assert scripts.deactivate(env.home, row["id"], note="again") == "script already inactive"


def test_overseer_stages_rejection_and_retains_drafts(env, monkeypatch):
    fake(monkeypatch, verdict="reject")
    scripts.review(env.home, held(env)["id"], note="test")
    staged = {}
    stage = env.tmp / "input"
    def write(root, path, text): staged[path.relative_to(root).as_posix()] = text
    skills.stage_phase_b(env.home, stage, [], skills.WritingState("off", False), write)
    assert "script-reviews.yaml" in staged
    assert "reject" in staged["script-reviews.yaml"] and "remove hazards" in staged["script-reviews.yaml"]
    step = skills.SkillStep(action="write", name=sk1.NAME, files=sk1.draft(), scripts=[{"name": "next", "text": GOOD, "usage": "Use it."}], deploy=False)
    entry = skills.draft_entry(step, "case", [])
    files = skills.draft_files(env.home, "2026-W01", [entry])
    assert any(path.name == "next" and text == GOOD for path, text in files)
    for path, text in files:
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    assert skills.stale_draft_files(env.home, "2026-W01", [entry]) == []
    assert len(scripts.rows(env.home)) == 1  # no executable/review from draft retention


def test_credential_source_refused_before_read(env, monkeypatch, capsys):
    source = env.tmp / "credentials"
    source.write_text("placeholder")
    link = env.tmp / "innocent"; link.symlink_to(source)
    original = Path.read_bytes
    def read(path):
        if path in (source, link): raise AssertionError("credential bytes were read")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    for path in (source, link):
        assert cli.main(["skill", "script", "draft", sk1.NAME, "--file", str(path), "--name", "count", "--usage", "Use it.", "--note", "test"]) == 1
        assert "credentials" in capsys.readouterr().err
    assert scripts.rows(env.home) == []


def test_quarantine_cross_filesystem(env, monkeypatch):
    import errno
    fake(monkeypatch)
    row = scripts.review(env.home, held(env)["id"], note="test")
    target = env.skill_dir() / "scripts/count"
    target.write_text("user edit across filesystems")
    def cross_device(*args, **kwargs): raise OSError(errno.EXDEV, "cross-device")
    monkeypatch.setattr(scripts.os, "rename", cross_device)
    notices = scripts.audit(env.home)
    assert len(notices) == 1 and "deactivated" in notices[0]
    result = scripts.get(env.home, row["id"])
    assert not target.exists() and Path(result["quarantine"]).read_text() == "user edit across filesystems"


def test_allowed_git_commands_are_read_only(env):
    prefix = ["--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "log.showSignature=false"]
    index = env.root / ".git/index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    for args in [["log", "--no-ext-diff", "--no-textconv", "--oneline"], ["status", "--porcelain"]]:
        assert screen(SH + "git " + " ".join(prefix + args)).ok
        result = git(env.root, *prefix, *args)
        assert result.returncode == 0
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
