"""S-NEXT-hookmatch, the orchestrator's decision: a placed WARNING hook
whose stored bytes the current compiler no longer produces is regenerated
by self-learn itself -- by ``recompile`` and by the daily ``maintenance``
job -- never a deny guard, never a file a person edited, and a second run
changes nothing.

An "outdated" hook is made the way a compiler change makes one: the lesson
is routed while the compiler is patched to write different bytes (the
stored script, the placed file and the host commit all agree with that
older compiler), then the patch is lifted. Sandbox ledger and host
(`support.make_env`), a scratch Claude directory, no model call.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from self_learn import hook_compiler, maintenance, verbs
from self_learn.hook_compiler import script_for_hook, script_name
from self_learn.records import Record
from self_learn.selfcheck import Verdict, _check_hooks
from test_hook_activation import _real_claude_dir_never_touched  # noqa: F401 -- the real-~/.claude control
from test_route_hook import RID, TRIGGER, Env, seed_hook

NAME = script_name(RID, TRIGGER)
BAD = "python3 - <<EOF </dev/null"
BASH_WARN = {
    "mode": "warn",
    "event": "PreToolUse",
    "tools": ["Bash"],
    "path_regex": r"<<-?[[:space:]]*[^[:space:]<|;&]+([^|;&]|&[0-9])*<[[:space:]]*/dev/null",
    "warn_message": "a heredoc and </dev/null on one command: the script never arrives",
}
BASH_EXAMPLES = {
    "allow": [
        {"tool_name": "Bash", "tool_input": {"command": "python3 - <<'EOF'\nprint(1)\nEOF"}},
        {"tool_name": "Bash", "tool_input": {"command": "tool --dir x </dev/null"}},
    ],
    "warn": [
        {"tool_name": "Bash", "tool_input": {"command": f"{BAD}\nprint(1)\nEOF"}},
        {"tool_name": "Bash", "tool_input": {"command": "uv run python - <<PY 2>&1 </dev/null\nPY"}},
    ],
}
FILE_WARN = {
    "mode": "warn",
    "event": "PostToolUse",
    "tools": ["Edit", "Write"],
    "path_regex": r"\.storage/",
    "warn_message": "HA rewrites .storage on shutdown",
}
FILE_EXAMPLES = {
    "allow": [{"tool_name": "Edit", "tool_input": {"file_path": "/x/configuration.yaml"}},
              {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}}],
    "warn": [{"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/core.config"}},
             {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/auth"}}],
}


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return tmp_path / "xdg-cache"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def claude_dir(tmp_path, monkeypatch):
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    return claude


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def _older_compiler(m: pytest.MonkeyPatch) -> None:
    """A compiler that writes different bytes for every mode: the message
    prefix every script embeds (the S-127 shape of change)."""
    real = hook_compiler.prefixed_message
    m.setattr(hook_compiler, "prefixed_message",
              lambda rid, msg: real(rid, msg).replace("self-learn ", "self-learn (old) ", 1))


def _route(env, monkeypatch, hook: dict | None, examples: dict | None, *, old: bool) -> Path:
    overrides = {} if hook is None else {"hook": hook, "examples": examples}
    with monkeypatch.context() as m:
        if old:
            _older_compiler(m)
        seed_hook(env, **overrides)
        verbs.route(env.home, RID)
    return env.host / "plugins" / "s-plugin" / "hooks" / NAME


def _meta(env) -> dict:
    return Record.from_path(env.resolved()).routing["hook"]


def _current(env) -> str:
    return script_for_hook(RID, TRIGGER, _meta(env))


def _run(script: Path, command: str) -> str:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run([str(script)], input=payload, capture_output=True, text=True).stdout


# -------------------------------------------------------- it regenerates


@pytest.mark.parametrize("block,examples", [(BASH_WARN, BASH_EXAMPLES), (FILE_WARN, FILE_EXAMPLES)],
                         ids=["bash", "edit-write"])
def test_an_outdated_warn_hook_regenerates_and_a_second_run_changes_nothing(
        env, monkeypatch, claude_dir, block, examples):
    script = _route(env, monkeypatch, block, examples, old=True)
    old = _meta(env)["script"]
    assert script.read_text(encoding="utf-8") == old  # placed by the older compiler
    assert _current(env) != old  # control: the current compiler disagrees
    head_before = _git(env.home, "rev-parse", "HEAD")

    result = verbs.recompile(env.home, no_push=True)

    new = _current(env)
    assert result.hooks_regenerated == [RID]
    assert _meta(env)["script"] == new  # the record carries the new bytes
    assert script.read_text(encoding="utf-8") == new  # and so does the host
    subjects = _git(env.home, "log", "--format=%s", f"{head_before}..HEAD").splitlines()
    assert "self-learn: regenerate warning hook(s) (1)" in subjects
    body = _git(env.home, "log", "-1", "--format=%B", "--grep=regenerate warning hook")
    assert f"{RID}: plugins/s-plugin/hooks/{NAME}" in body
    assert _git(env.host, "log", "-1", "--format=%s").startswith("self-learn: recompile")
    assert _check_hooks(env.home, claude_dir)[0] is Verdict.PASS  # record, file, examples agree
    if block is BASH_WARN:  # the regenerated hook has the command view
        assert _run(script, f"{BAD}\nEOF") != ""
        assert _run(script, f'git commit -m "{BAD}"') == ""

    ledger_head, host_head = _git(env.home, "rev-parse", "HEAD"), _git(env.host, "rev-parse", "HEAD")
    again = verbs.recompile(env.home, no_push=True)
    assert again.hooks_regenerated == []
    assert (_git(env.home, "rev-parse", "HEAD"), _git(env.host, "rev-parse", "HEAD")) == (
        ledger_head, host_head)
    assert script.read_text(encoding="utf-8") == new


def test_an_up_to_date_warn_hook_is_untouched(env, monkeypatch):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=False)
    assert _meta(env)["script"] == _current(env)  # control: current
    heads = (_git(env.home, "rev-parse", "HEAD"), _git(env.host, "rev-parse", "HEAD"))
    result = verbs.recompile(env.home, no_push=True)
    assert result.hooks_regenerated == []
    assert not [w for w in result.warnings if "warning hook not regenerated" in w]
    assert (_git(env.home, "rev-parse", "HEAD"), _git(env.host, "rev-parse", "HEAD")) == heads
    assert verbs.stale_warn_hooks(env.home) == ([], {})
    assert script.read_text(encoding="utf-8") == _meta(env)["script"]


# ------------------------------------------------ what it never touches


def test_a_deny_guard_is_never_regenerated(env, monkeypatch, claude_dir):
    script = _route(env, monkeypatch, None, None, old=True)  # the default deny block
    meta = _meta(env)
    assert hook_compiler.hook_mode(meta) == "deny"
    old = meta["script"]
    assert _current(env) != old  # control: the deny compiler changed too
    assert verbs.stale_warn_hooks(env.home) == ([], {})
    refresh = verbs.refresh_warn_hooks(env.home)
    assert (refresh.regenerated, refresh.refused, refresh.commit_subject) == ([], {}, None)
    result = verbs.recompile(env.home, no_push=True)
    assert result.hooks_regenerated == []
    assert _meta(env)["script"] == old and script.read_text(encoding="utf-8") == old
    assert "regenerate warning hook" not in _git(env.home, "log", "--format=%s")


def test_a_deny_guard_whose_block_claims_warn_is_still_never_regenerated(env, monkeypatch):
    """The stored bytes decide too: a deny guard's script under a block that
    reads ``mode: warn`` (a hand-edited record) is refused, never rewritten."""
    _route(env, monkeypatch, None, None, old=True)
    record = Record.from_path(env.resolved())
    routing = dict(record.routing)
    hook = dict(routing["hook"])
    hook["mode"] = "warn"
    hook["warn_message"] = hook.pop("deny_message")
    hook["examples"] = {"allow": hook["examples"]["allow"], "warn": hook["examples"]["deny"]}
    routing["hook"] = hook
    record.set_routing(routing)
    record.write(env.resolved())
    old = hook["script"]
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and "not a warning hook" in refused[RID]
    assert verbs.refresh_warn_hooks(env.home).regenerated == []
    assert _meta(env)["script"] == old


def test_a_hand_edited_hook_file_is_left_and_reported(env, monkeypatch, claude_dir, cache_dir):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    old = _meta(env)["script"]
    edited = old + "# a person's own line\n"
    script.write_text(edited, encoding="utf-8")
    _git(env.host, "commit", "-qam", "hand edit")  # committed: not the dirty gate
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and refused[RID].startswith("hand-edited")

    result = verbs.recompile(env.home, no_push=True)
    assert result.hooks_regenerated == []
    assert any(w.startswith(f"{RID}: warning hook not regenerated — hand-edited")
               for w in result.warnings)
    assert script.read_text(encoding="utf-8") == edited  # left as the person wrote it
    assert _meta(env)["script"] == old

    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.hooks_regenerated == [] and job.hooks_refused[RID].startswith("hand-edited")
    assert maintenance.read_state(cache_dir)["hooks_refused"][RID].startswith("hand-edited")
    assert script.read_text(encoding="utf-8") == edited

    script.unlink()  # the way out the refusal names
    assert verbs.recompile(env.home, no_push=True).hooks_regenerated == [RID]
    assert script.read_text(encoding="utf-8") == _current(env)


def test_a_hook_whose_examples_fail_against_the_new_bytes_is_left(env, monkeypatch):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    record = Record.from_path(env.resolved())
    routing = dict(record.routing)
    hook = dict(routing["hook"])
    # a warn example only the raw matcher warns on: the view keeps it quiet
    hook["examples"] = {**hook["examples"], "warn": [
        {"tool_name": "Bash", "tool_input": {"command": f'echo "{BAD}"'}}]}
    routing["hook"] = hook
    record.set_routing(routing)
    record.write(env.resolved())
    _git(env.home, "commit", "-qam", "test: an example the new script fails")
    old = hook["script"]
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and "do not replay" in refused[RID]
    verbs.recompile(env.home, no_push=True)
    assert _meta(env)["script"] == old and script.read_text(encoding="utf-8") == old


# ----------------------------------------------------- the maintenance job


def test_the_maintenance_job_regenerates_as_the_maintenance_actor(
        env, monkeypatch, cache_dir, capsys):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    head_before = _git(env.home, "rev-parse", "HEAD")
    capsys.readouterr()
    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.status == "ran" and job.hooks_regenerated == [RID]
    assert f"maintenance regenerated 1 warning hook(s) from the current compiler — {RID}" in (
        capsys.readouterr().err)  # the log names the hooks that moved
    assert maintenance.read_state(cache_dir)["hooks_regenerated"] == [RID]
    assert _meta(env)["script"] == _current(env) == script.read_text(encoding="utf-8")
    log = _git(env.home, "log", "--format=%s%n%b%n--", f"{head_before}..HEAD")
    regen = [c for c in log.split("\n--\n") if "regenerate warning hook(s) (1)" in c]
    assert len(regen) == 1 and "By: maintenance" in regen[0] and "By: human" not in regen[0]

    head = _git(env.home, "rev-parse", "HEAD")
    again = maintenance.run(env.home, cache_dir, now=time.time())
    assert again.status == "idle" and again.hooks_regenerated == []
    assert _git(env.home, "rev-parse", "HEAD") == head
