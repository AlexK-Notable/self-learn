"""Batch 2026-09-28, unit E: a refused commit of a retired hook script's
removal leaves no staged deletion in the user's repo.

The user's words (2026-09-28 11:54 PDT): "fix the rest of 3". Retiring a
hook-routed lesson in a git-mode host runs ``git rm`` on its guard script
and commits. When a pre-commit hook refuses that commit (the machine-wide
gitleaks guard runs in block mode on every git-mode host), the script was
left deleted AND staged in the user's repo: the user's next commit would
carry our deletion, and ``recompile`` never retried it because the script
was already gone from disk. Sweep 2 R3's rule for a refused host write now
covers the removal: the script is put back and unstaged, and the removal
stays owed -- the next ``recompile`` removes it once the commit can land.

Sandbox ledger and host repos under pytest's tmpdir; the refusing hook is
a repo-local ``core.hooksPath``.
"""

from __future__ import annotations

import os

import pytest

from self_learn import verbs
from self_learn.ledger_ops import create_record
from support import git, make_behavior
from test_route_hook import NAME, RID, Env, seed_hook


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")


def _refuse_every_commit(tmp_path, host):
    hooks = tmp_path / "refusing-hooks"
    hooks.mkdir(exist_ok=True)
    script = hooks / "pre-commit"
    script.write_text(
        "#!/usr/bin/env bash\necho 'test-hook: REFUSED the staged changes' >&2\nexit 1\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    git(host, "config", "core.hooksPath", str(hooks))


def _status(host) -> str:
    return git(host, "status", "--porcelain", "-uall").stdout.strip()


def _head(host) -> str:
    return git(host, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.parametrize("hooked", [False, True])
def test_a_refused_removal_leaves_the_script_in_place_and_nothing_staged(
    tmp_path, hooked
):
    env = Env(tmp_path)
    seed_hook(env)
    verbs.route(env.home, RID)
    rel = f"plugins/s-plugin/hooks/{NAME}"
    script = env.host / rel
    assert script.is_file()  # positive control: the guard was routed
    before = script.read_bytes()
    mode = script.stat().st_mode & 0o7777
    if hooked:
        _refuse_every_commit(tmp_path, env.host)
    host_head = _head(env.host)
    create_record(env.home, make_behavior(scope="skill:s", record_id="lrn-0000bbbb"))

    result = verbs.supersede(env.home, RID, "lrn-0000bbbb")

    if not hooked:
        # control: the removal commits and the script is gone
        assert not script.exists()
        assert env.host_subject() == f"self-learn: apply {RID} → {rel} (hook removed)"
        assert _status(env.host) == ""
        return
    warning = next(w for w in result.warnings if "HOOK REMOVAL REFUSED" in w)
    assert "test-hook: REFUSED the staged changes" in warning
    assert "put back as it was and unstaged" in warning
    assert "owed" in warning and "self-learn recompile" in warning
    # the user's repo is as it was: no staged deletion, same bytes and mode
    assert _status(env.host) == ""
    assert _head(env.host) == host_head
    assert script.read_bytes() == before
    assert script.stat().st_mode & 0o7777 == mode

    # a recompile while the hook still refuses reports the skip, still clean
    again = verbs.recompile(env.home, no_push=True)
    entry = next(e for e in again.entries if e.target == script)
    assert entry.skipped and "owed" in entry.skipped
    assert script.is_file() and _status(env.host) == ""

    # once the hook stops refusing, the owed removal lands
    git(env.host, "config", "--unset", "core.hooksPath")
    done = verbs.recompile(env.home, no_push=True)
    entry = next(e for e in done.entries if e.target == script)
    assert entry.commit_sha and not entry.skipped
    assert not script.exists()
    assert env.host_subject() == f"self-learn: apply {RID} → {rel} (hook removed)"
    assert _status(env.host) == ""
