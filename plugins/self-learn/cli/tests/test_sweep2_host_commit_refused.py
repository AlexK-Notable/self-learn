"""Sweep 2, R3 (2026-09-27): a host repo's commit hook refusing ONE
self-learn commit costs that one host write -- never the user's repo state,
never every later lesson routed to the same file, never the rest of a
`recompile`.

On the maintainer's machine a machine-wide gitleaks pre-commit hook runs in
block mode on every git-mode host. Here a repo-local ``core.hooksPath``
stands in for it: its pre-commit refuses any staged diff that contains a
marker string (built at runtime). Every test has a no-hook or unmarked
control showing the same flow commits normally.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from self_learn import verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env, make_knowledge, proposal_dict

MARK = "BLOCK" + "ME-" + "FLAGGED"


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")


def _install_refusing_hook(tmp_path, host, marker=MARK):
    hooks = tmp_path / "refusing-hooks"
    hooks.mkdir(exist_ok=True)
    script = hooks / "pre-commit"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"if git diff --cached | grep -q '{marker}'; then\n"
        "  echo 'test-hook: REFUSED the staged changes' >&2; exit 1\nfi\nexit 0\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    git(host, "config", "core.hooksPath", str(hooks))


def _remove_hook(host):
    git(host, "config", "--unset", "core.hooksPath")


def _status(host) -> str:
    return git(host, "status", "--porcelain", "-uall").stdout.strip()


def _seed(home, rid, skill="s", instruction="Stop the container first."):
    create_record(
        home, make_behavior(record_id=rid, scope=f"skill:{skill}", instruction=instruction)
    )
    write_proposal(home, rid, proposal_dict(scope=f"skill:{skill}"))
    commit_all(home, f"seed {rid}")


def _env(tmp_path, monkeypatch, skills=("s",)):
    env = make_env(tmp_path, skills=skills)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    return env


def _skill_md(env, skill="s"):
    return env.host / "plugins" / f"{skill}-plugin" / "skills" / skill / "SKILL.md"


# ------------------------------------------------------------------ route


@pytest.mark.parametrize("hooked", [False, True])
def test_a_refused_route_commit_leaves_the_host_as_it_was(tmp_path, monkeypatch, hooked):
    env = _env(tmp_path, monkeypatch)
    home = env.ledger
    if hooked:
        _install_refusing_hook(tmp_path, env.host)
    _seed(home, "lrn-9c000001", instruction=f"Rotate the {MARK} value first.")
    _seed(home, "lrn-9c000002")
    before = _skill_md(env).read_bytes()
    host_head = git(env.host, "rev-parse", "HEAD").stdout.strip()

    first = verbs.route(home, "lrn-9c000001", dest="skill-md", no_push=True)

    # the ledger commit stands either way (H-2)
    routed = Record.from_path(home / "skills/s/resolved/lrn-9c000001.md")
    assert routed.status == "routed"
    if not hooked:
        # control: the host commit lands
        assert not first.warnings
        assert git(env.host, "rev-parse", "HEAD").stdout.strip() != host_head
        assert "lrn-9c000001" in _skill_md(env).read_text()
        return
    warning = next(w for w in first.warnings if "HOST PHASE FAILED" in w)
    assert "test-hook: REFUSED the staged changes" in warning
    assert "put back as it was and unstaged" in warning
    # nothing staged, nothing modified, no new host commit, same bytes
    assert _status(env.host) == ""
    assert git(env.host, "rev-parse", "HEAD").stdout.strip() == host_head
    assert _skill_md(env).read_bytes() == before
    # a later lesson to the same file is not refused as "dirty"
    verbs.route(home, "lrn-9c000002", dest="skill-md", no_push=True)
    assert Record.from_path(home / "skills/s/resolved/lrn-9c000002.md").status == "routed"
    assert _status(env.host) == ""
    # once the hook stops refusing, the next recompile writes the owed canon
    _remove_hook(env.host)
    result = verbs.recompile(home, no_push=True)
    text = _skill_md(env).read_text()
    assert "lrn-9c000001" in text and "lrn-9c000002" in text
    assert any(e.commit_sha for e in result.entries)
    assert _status(env.host) == ""


# ------------------------------------------------------------------ recompile


def _drift(env, *paths):
    for p in paths:
        text = p.read_text()
        p.write_text(text[: text.index(BEGIN_MARKER)] + BEGIN_MARKER + "\n" + END_MARKER + "\n")
    commit_all(env.host, "drift")


@pytest.mark.parametrize("hooked", [False, True])
def test_a_refused_recompile_commit_costs_only_that_target(tmp_path, monkeypatch, hooked):
    env = _env(tmp_path, monkeypatch, skills=("s", "t"))
    home = env.ledger
    _seed(home, "lrn-9d000001", "s", instruction=f"Rotate the {MARK} value first.")
    _seed(home, "lrn-9d000002", "t")
    verbs.route(home, "lrn-9d000001", dest="skill-md", no_push=True)
    verbs.route(home, "lrn-9d000002", dest="skill-md", no_push=True)
    s_md, t_md = _skill_md(env, "s"), _skill_md(env, "t")
    _drift(env, s_md, t_md)
    if hooked:
        _install_refusing_hook(tmp_path, env.host)
    s_before = s_md.read_bytes()

    result = verbs.recompile(home, no_push=True)

    # every target after the refused one is still repaired and committed
    assert "lrn-9d000002" in t_md.read_text()
    t_entry = next(e for e in result.entries if e.target == t_md)
    assert t_entry.changed and t_entry.commit_sha
    s_entry = next(e for e in result.entries if e.target == s_md)
    if not hooked:
        assert s_entry.changed and s_entry.commit_sha
        return
    assert s_entry.skipped and "host commit refused" in s_entry.skipped
    assert "test-hook: REFUSED the staged changes" in s_entry.skipped
    assert s_md.read_bytes() == s_before
    assert _status(env.host) == ""
    # the owed write is retried by the next recompile
    _remove_hook(env.host)
    verbs.recompile(home, no_push=True)
    assert "lrn-9d000001" in s_md.read_text()
    assert _status(env.host) == ""


@pytest.mark.parametrize("hooked", [False, True])
def test_a_refused_reference_commit_costs_only_that_file(tmp_path, monkeypatch, hooked):
    env = _env(tmp_path, monkeypatch, skills=("s", "t"))
    home = env.ledger
    clean = make_knowledge(scope="skill:s")
    create_record(home, clean)
    verbs.route(home, clean.id, dest="reference", no_push=True)
    refs = sorted((_skill_md(env).parent).rglob("*.md"))
    refs_file = next(p for p in refs if p.name != "SKILL.md")
    assert clean.id in refs_file.read_text()
    # a second, flagged fact: its route's host write is refused
    _install_refusing_hook(tmp_path, env.host)
    flagged = make_knowledge(scope="skill:s", fact=f"The {MARK} value rotates weekly.")
    create_record(home, flagged)
    before_route = refs_file.read_bytes()
    out = verbs.route(home, flagged.id, dest="reference", no_push=True)
    assert any("HOST PHASE FAILED" in w for w in out.warnings)
    assert refs_file.read_bytes() == before_route
    assert _status(env.host) == ""
    # a managed target elsewhere drifts too (the positive control for "the rest")
    _seed(home, "lrn-9d000003", "t")
    verbs.route(home, "lrn-9d000003", dest="skill-md", no_push=True)
    t_md = _skill_md(env, "t")
    _drift(env, t_md)
    if not hooked:
        _remove_hook(env.host)

    result = verbs.recompile(home, no_push=True)

    assert "lrn-9d000003" in t_md.read_text()
    ref_entry = next(e for e in result.entries if e.target == refs_file)
    if not hooked:
        assert ref_entry.commit_sha and flagged.id in refs_file.read_text()
        return
    assert ref_entry.skipped and "host commit refused" in ref_entry.skipped
    assert refs_file.read_bytes() == before_route
    assert _status(env.host) == ""


def _hook_input(deny_message):
    return {
        "rationale": "deterministic guard; over-block: denies stopped-container edits too",
        "alternates": ["skill-md"],
        "hook": {
            "tools": ["Edit", "Write"],
            "path_regex": r"\.storage/",
            "deny_message": deny_message,
        },
        "examples": {
            "allow": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/config.yaml"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
            ],
            "deny": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/b"}},
            ],
        },
    }


@pytest.mark.parametrize("hooked", [False, True])
def test_a_refused_hook_script_commit_costs_only_that_script(tmp_path, monkeypatch, hooked):
    env = _env(tmp_path, monkeypatch, skills=("s", "t"))
    home = env.ledger
    (home / "config.yaml").write_text("one_motion_route:\n  hook: true\n", encoding="utf-8")
    commit_all(home, "enable one-motion hook routes")
    record = make_behavior(scope="skill:s", trigger="About to edit `.storage/*.json` while HA is running.")
    verbs.route_direct(
        home, record, dest="hook", hook_input=_hook_input(f"stop first {MARK}")
    )
    routed = Record.from_path(home / "skills/s/resolved" / f"{record.id}.md")
    script = env.host / routed.routing["hook"]["script_path"]
    assert script.is_file()
    # the script goes missing (an interrupted apply), committed
    git(env.host, "rm", "-q", "--", str(script))
    subprocess.run(["git", "-C", str(env.host), "commit", "-q", "-m", "lose it"], check=True)
    _seed(home, "lrn-9d000004", "t")
    verbs.route(home, "lrn-9d000004", dest="skill-md", no_push=True)
    t_md = _skill_md(env, "t")
    _drift(env, t_md)
    if hooked:
        _install_refusing_hook(tmp_path, env.host)

    result = verbs.recompile(home, no_push=True)

    assert "lrn-9d000004" in t_md.read_text()
    entry = next(e for e in result.entries if e.target == script)
    if not hooked:
        assert entry.commit_sha and script.is_file()
        return
    assert entry.skipped and "host commit refused" in entry.skipped
    assert not script.exists()  # put back: it did not exist before
    assert _status(env.host) == ""


# ------------------------------------------------------------------ the undo


def test_undo_puts_back_the_bytes_seen_before_not_head(tmp_path):
    """A new skill's marketplace.json can carry the user's own uncommitted
    edit (only the target is dirty-checked); the undo must restore THOSE
    bytes, not HEAD's, and drop a file the compile created."""
    env = make_env(tmp_path)
    host = env.host
    user_file = host / "CLAUDE.md"
    user_file.write_text(user_file.read_text() + "\nthe user's own edit\n")
    users_bytes = user_file.read_bytes()
    created = host / "plugins" / "new-one.json"
    snapshot = verbs._snapshot_host_files([user_file, created])
    user_file.write_text("compiled over\n")
    created.write_text("{}\n")
    git(host, "add", "--", str(user_file), str(created))
    assert git(host, "diff", "--cached", "--name-only").stdout.strip()

    note = verbs._undo_host_write(host, snapshot, [user_file, created])

    assert note == "the host file was put back as it was and unstaged"
    assert user_file.read_bytes() == users_bytes
    assert not created.exists()
    assert git(host, "diff", "--cached", "--name-only").stdout.strip() == ""
    # the user's edit is still theirs, unstaged
    assert _status(host) == "M CLAUDE.md"
