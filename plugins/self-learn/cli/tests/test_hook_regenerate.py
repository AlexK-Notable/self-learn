"""S-133, the orchestrator's decision: a placed WARNING hook
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
        {"tool_name": "Bash", "tool_input": {"command": f'git commit -m "{BAD}"'}}]}
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


# ------------------------------------------- gate r1 (2026-11-01) folds

RID2 = "lrn-0000bbbb"


def _route_id(env, monkeypatch, rid: str, *, old: bool) -> Path:
    with monkeypatch.context() as m:
        if old:
            _older_compiler(m)
        seed_hook(env, rid=rid, hook=BASH_WARN, examples=BASH_EXAMPLES)
        verbs.route(env.home, rid)
    return env.host / "plugins" / "s-plugin" / "hooks" / script_name(rid, TRIGGER)


def _record_path(env, rid: str = RID) -> Path:
    from self_learn import ledger_ops

    return ledger_ops.find_record_path(env.home, rid)


def _set_meta(env, rid: str = RID, **changes) -> None:
    path = _record_path(env, rid)
    record = Record.from_path(path)
    routing = dict(record.routing)
    routing["hook"] = {**routing["hook"], **changes}
    record.set_routing(routing)
    record.write(path)
    _git(env.home, "commit", "-qam", "test: edit the stored hook block")


def _retire(env, rid: str = RID) -> None:
    path = _record_path(env, rid)
    record = Record.from_path(path)
    record._fm["superseded_by"] = "lrn-0000cccc"  # test-only: is_canon_live reads it
    record.write(path)
    _git(env.home, "commit", "-qam", "test: retire the lesson")


def compiled_sha(text: str) -> str:
    from self_learn import compiled

    return compiled.sha256_hex(text.encode("utf-8"))


def _fail_host_commits(env) -> Path:
    hook = env.host / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    return hook


def _pending(env) -> dict:
    from self_learn import hook_pending

    return hook_pending.read(env.home)


def _commit_host(env, message: str) -> None:
    _git(env.host, "add", "-A")
    _git(env.host, "commit", "-qm", message)


def test_f2_a_failed_host_write_is_recorded_pending_and_the_next_maintenance_run_places_it(
        env, monkeypatch, cache_dir):
    """The gate's r1 reproduction, under r2's rule: the regeneration's
    ledger commit lands, the host commit is refused (the file is put back);
    the job reports the hook pending and RECORDS it, and the next run places
    exactly that record, then forgets it."""
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    old = _meta(env)["script"]
    blocker = _fail_host_commits(env)
    first = maintenance.run(env.home, cache_dir, now=time.time())
    new = _current(env)
    assert _meta(env)["script"] == new  # the ledger moved
    assert script.read_bytes() == old.encode("utf-8")  # the host write did not land
    assert first.hooks_regenerated == [] and RID in first.hooks_pending
    state = maintenance.read_state(cache_dir)
    assert RID in state["hooks_pending"] and "hooks_regenerated" not in state
    entry = _pending(env)[RID]
    assert entry["placed_sha256"] == compiled_sha(old) and entry["missing"] is False

    blocker.unlink()
    assert verbs.pending_warn_hook_placements(env.home) == ([RID], {})  # work, not idle
    second = maintenance.run(env.home, cache_dir, now=time.time() + 2 * 86400)
    assert second.status == "ran" and second.hooks_placed == [RID]
    assert script.read_bytes() == new.encode("utf-8")
    assert maintenance.read_state(cache_dir)["hooks_placed"] == [RID]
    assert _pending(env) == {}  # placed, so forgotten
    assert maintenance.run(env.home, cache_dir, now=time.time() + 4 * 86400).status == "idle"


def test_f2_recompile_records_the_pending_write_and_a_later_recompile_places_it(env, monkeypatch):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    blocker = _fail_host_commits(env)
    first = verbs.recompile(env.home, no_push=True)
    assert first.hooks_regenerated == [] and RID in first.hooks_pending
    assert any(w.startswith(f"{RID}: warning hook regenerated in the ledger, host write pending")
               for w in first.warnings)
    assert RID in _pending(env)
    blocker.unlink()
    second = verbs.recompile(env.home, no_push=True)
    assert second.hooks_placed == [RID] and second.hooks_pending == {}
    assert script.read_bytes() == _current(env).encode("utf-8")
    assert _pending(env) == {}


def test_g2_a_person_edit_after_a_failed_write_is_left_and_reported(env, monkeypatch, cache_dir):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    blocker = _fail_host_commits(env)
    maintenance.run(env.home, cache_dir, now=time.time())
    assert RID in _pending(env)  # control: recorded
    blocker.unlink()
    edited = script.read_text(encoding="utf-8") + "# mine\n"
    script.write_text(edited, encoding="utf-8")
    _commit_host(env, "hand edit")
    place, left = verbs.pending_warn_hook_placements(env.home)
    assert place == [] and "was changed after" in left[RID]
    job = maintenance.run(env.home, cache_dir, now=time.time() + 2 * 86400)
    assert job.status == "idle" and "was changed after" in job.hooks_refused[RID]
    assert script.read_text(encoding="utf-8") == edited
    # a recompile by hand leaves it too, and says so
    by_hand = verbs.recompile(env.home, no_push=True)
    assert any(w.startswith(f"{RID}: pending warning hook not placed") for w in by_hand.warnings)
    assert script.read_text(encoding="utf-8") == edited


def test_g2_a_person_deletion_after_a_failed_write_is_left_and_reported(
        env, monkeypatch, cache_dir):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    blocker = _fail_host_commits(env)
    maintenance.run(env.home, cache_dir, now=time.time())
    assert _pending(env)[RID]["missing"] is False  # control: the file was put back
    blocker.unlink()
    script.unlink()
    _commit_host(env, "hand delete")
    job = maintenance.run(env.home, cache_dir, now=time.time() + 2 * 86400)
    assert job.status == "idle" and "was deleted after" in job.hooks_refused[RID]
    assert not script.exists()


def test_h6_the_pending_cache_is_written_under_the_commit_lock(env, monkeypatch):
    """Gate r3 H6 (V20): every write of the pending-placement cache, by
    ``record`` and by ``drop``, happens while the ledger's commit lock is
    held (``test_lock_invariant`` exempts the writer as NOT_REPO_TRUTH, so
    nothing else pins this)."""
    from contextlib import contextmanager

    from self_learn import gitops, hook_pending

    depth = [0]
    real_lock = gitops.commit_lock

    @contextmanager
    def spy(repo, **kwargs):
        with real_lock(repo, **kwargs):
            depth[0] += 1
            try:
                yield
            finally:
                depth[0] -= 1

    writes: list[bool] = []
    real_store = hook_pending._store

    def store(home, data):
        writes.append(depth[0] > 0)
        real_store(home, data)

    monkeypatch.setattr(gitops, "commit_lock", spy)
    monkeypatch.setattr(hook_pending, "_store", store)
    hook_pending.record(env.home, RID, placed_sha256="0" * 64, missing=False,
                        script_path="x.sh", why="test")
    assert RID in hook_pending.read(env.home)  # control: it was written
    hook_pending.drop(env.home, [RID])
    assert hook_pending.read(env.home) == {}
    assert writes == [True, True]


def test_g2_a_pending_entry_for_a_retired_lesson_is_forgotten(env, monkeypatch, cache_dir):
    _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    blocker = _fail_host_commits(env)
    maintenance.run(env.home, cache_dir, now=time.time())
    assert RID in _pending(env)  # control: recorded
    blocker.unlink()
    _retire(env)
    verbs.recompile(env.home, no_push=True)
    assert _pending(env) == {}


def test_g2_a_symlink_after_a_failed_write_is_left(env, monkeypatch, cache_dir, tmp_path):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    blocker = _fail_host_commits(env)
    maintenance.run(env.home, cache_dir, now=time.time())
    assert RID in _pending(env)  # control: recorded
    blocker.unlink()
    elsewhere = tmp_path / "mine.sh"
    elsewhere.write_bytes(script.read_bytes())  # the very bytes self-learn had placed
    script.unlink()
    script.symlink_to(elsewhere)
    place, left = verbs.pending_warn_hook_placements(env.home)
    assert place == [] and "became a symlink" in left[RID]


def test_g2_a_file_missing_after_the_failed_write_is_placed(env, monkeypatch, cache_dir):
    """A person removes an outdated hook's file and runs recompile by hand,
    which regenerates it; its host write fails, leaving the file missing.
    That is recorded (``missing``), and the next run places it."""
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    script.unlink()
    _commit_host(env, "remove it so recompile writes the regenerated hook")
    blocker = _fail_host_commits(env)
    first = verbs.recompile(env.home, no_push=True)
    assert RID in first.hooks_pending and not script.exists()
    assert _pending(env)[RID]["missing"] is True
    blocker.unlink()
    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.status == "ran" and job.hooks_placed == [RID]
    assert script.read_bytes() == _current(env).encode("utf-8")


def test_g2_a_restored_edit_after_a_hand_recompile_is_left(env, monkeypatch, cache_dir):
    """The gate's P1: a person edits an up-to-date hook, a hand recompile
    re-applies the stored bytes, and the person puts their edit back. With
    nothing recorded pending, the daily job leaves it."""
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=False)
    stored = _meta(env)["script"]
    edited = stored + "# mine\n"
    script.write_text(edited, encoding="utf-8")
    _commit_host(env, "hand edit")
    verbs.recompile(env.home, no_push=True)
    assert script.read_text(encoding="utf-8") == stored  # control: re-applied
    script.write_text(edited, encoding="utf-8")
    _commit_host(env, "put my edit back")
    assert verbs.pending_warn_hook_placements(env.home) == ([], {})
    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.status == "idle" and job.hooks_refused == {}
    assert script.read_text(encoding="utf-8") == edited


def test_g4_a_deleted_up_to_date_hook_is_not_recreated(env, monkeypatch, cache_dir):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=False)
    assert script.exists()  # control
    script.unlink()
    _commit_host(env, "hand delete")
    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.status == "idle" and job.hooks_placed == []
    assert not script.exists()


def test_g4_a_deleted_outdated_hook_is_left_by_maintenance(env, monkeypatch, cache_dir):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    old = _meta(env)["script"]
    script.unlink()
    _commit_host(env, "hand delete")
    stale, left = verbs.stale_warn_hooks(env.home)
    assert stale == [] and "is missing" in left[RID]
    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.status == "idle" and "is missing" in job.hooks_refused[RID]
    assert not script.exists() and _meta(env)["script"] == old  # nothing moved


def test_f2_a_person_edit_of_an_up_to_date_hook_is_not_placed_by_maintenance(
        env, monkeypatch, cache_dir):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=False)
    edited = _meta(env)["script"] + "# mine\n"
    script.write_text(edited, encoding="utf-8")
    _git(env.host, "commit", "-qam", "hand edit")
    assert verbs.pending_warn_hook_placements(env.home) == ([], {})
    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.status == "idle"
    assert script.read_text(encoding="utf-8") == edited


def test_f5_the_planner_skips_a_retired_lesson(env, monkeypatch):
    _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    assert verbs.stale_warn_hooks(env.home) == ([RID], {})  # control: outdated and live
    _retire(env)
    assert verbs.stale_warn_hooks(env.home) == ([], {})


def test_f5_the_commit_rechecks_under_the_lock(env, monkeypatch):
    """A lesson retired between the plan and the commit is left alone."""
    _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    old = _meta(env)["script"]
    real = verbs._plan_warn_hook_refresh

    def plan_then_retire(home, only_records=None):
        planned = real(home, only_records)
        assert [r.id for _, r, _ in planned[0]] == [RID]  # control: planned
        _retire(env)
        return planned

    monkeypatch.setattr(verbs, "_plan_warn_hook_refresh", plan_then_retire)
    refresh = verbs.refresh_warn_hooks(env.home)
    assert refresh.regenerated == [] and refresh.commit_subject is None
    assert Record.from_path(_record_path(env)).routing["hook"]["script"] == old


def test_f5_a_symlinked_hook_file_is_refused(env, monkeypatch, tmp_path):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    copy = tmp_path / "elsewhere.sh"
    copy.write_bytes(script.read_bytes())
    script.unlink()
    script.symlink_to(copy)
    _git(env.host, "add", "-A")
    _git(env.host, "commit", "-qm", "symlink")
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and "is a symlink" in refused[RID]


def test_f5_a_trigger_that_names_another_file_is_refused(env, monkeypatch):
    _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    _set_meta(env, script_path="plugins/s-plugin/hooks/self-learn-0000aaaa-other-name.sh")
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and "now names the file" in refused[RID]


def test_f5_a_secret_scan_hit_is_refused(env, monkeypatch):
    _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    assert verbs.stale_warn_hooks(env.home) == ([RID], {})  # control
    monkeypatch.setattr(verbs, "secret_scan", lambda text: ["a hit"])
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and "secret scan" in refused[RID]


def test_f5_a_hook_with_no_warn_examples_is_refused(env, monkeypatch):
    _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    _set_meta(env, examples={"allow": BASH_EXAMPLES["allow"], "warn": []})
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and "no warn examples" in refused[RID]


def test_f5_a_run_that_did_work_still_records_what_it_left(env, monkeypatch, cache_dir):
    _route_id(env, monkeypatch, RID, old=True)
    other = _route_id(env, monkeypatch, RID2, old=True)
    other.write_text(other.read_text(encoding="utf-8") + "# mine\n", encoding="utf-8")
    _git(env.host, "commit", "-qam", "hand edit")
    job = maintenance.run(env.home, cache_dir, now=time.time())
    assert job.status == "ran" and job.hooks_regenerated == [RID]
    state = maintenance.read_state(cache_dir)
    assert state["status"] == "ran" and state["hooks_refused"][RID2].startswith("hand-edited")


def test_f8_a_crlf_only_edit_is_a_hand_edit(env, monkeypatch):
    script = _route(env, monkeypatch, BASH_WARN, BASH_EXAMPLES, old=True)
    old = _meta(env)["script"]
    assert verbs.stale_warn_hooks(env.home) == ([RID], {})  # control
    script.write_bytes(old.replace("\n", "\r\n").encode("utf-8"))
    _git(env.host, "commit", "-qam", "crlf")
    todo, refused = verbs.stale_warn_hooks(env.home)
    assert todo == [] and refused[RID].startswith("hand-edited")
