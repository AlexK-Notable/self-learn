"""T17 — `route <id> --dest hook` end-to-end (08 §8.1 pins: Hook compiler
output, Hook apply convention M3-2, Guard test replay M3-12, Hook approval
flow M3-11, Hook correction/rollback M3-4; doc 13 §4 two-phase shape).

Sandbox ledger + host repos with bare remotes; generated guards are
EXECUTED (replay + post-route behavioral probes). The three real M3
worklist records (lrn-98d42215 chezmoi-cd, lrn-6883f824 sudo-npm,
lrn-25968266 uv-venv-copy) are replicated here as fixtures so the seed
worklist's guards are proven routable before the user drains the list.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from self_learn import verbs
from self_learn.hook_compiler import script_name
from self_learn.ledger_ops import create_record, stamp_proposal, write_proposal
from self_learn.records import Record
from support import git, make_behavior, make_env, proposal_dict

RID = "lrn-0000aaaa"


class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir
        self.bucket = self.home / "skills" / "s"
        self.bare = tmp_path / "ledger-remote.git"
        self.host_bare = tmp_path / "host-remote.git"
        for repo, bare in ((self.home, self.bare), (self.host, self.host_bare)):
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
            )
            git(repo, "remote", "add", "origin", str(bare))
            git(repo, "push", "-q", "-u", "origin", "main")

    def host_subject(self):
        return git(self.host, "log", "-1", "--format=%s").stdout.strip()

    def host_body(self):
        return git(self.host, "log", "-1", "--format=%B").stdout

    def host_remote_files(self):
        return git(self.host_bare, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()

    def ledger_subject(self):
        return git(self.home, "log", "-1", "--format=%s").stdout.strip()

    def pending(self, rid=RID):
        return self.bucket / "pending" / f"{rid}.md"

    def resolved(self, rid=RID):
        return self.bucket / "resolved" / f"{rid}.md"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


TRIGGER = "About to edit `.storage/*.json` while HA is running."


def hook_proposal(**overrides) -> dict:
    data = proposal_dict(
        destination="hook",
        alternates=["skill-md"],
        hook={
            "tools": ["Edit", "Write"],
            "path_regex": r"\.storage/",
            "deny_message": "stop the HA container first — .storage is rewritten on shutdown",
        },
        examples={
            "allow": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/configuration.yaml"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
            ],
            "deny": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/core.config"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/auth"}},
            ],
        },
    )
    data.update(overrides)
    return data


def seed_hook(env, rid=RID, scope="skill:s", stamp=True, **proposal_overrides):
    record = make_behavior(scope=scope, record_id=rid, trigger=TRIGGER)
    create_record(env.home, record)
    write_proposal(env.home, rid, hook_proposal(**proposal_overrides))
    if stamp:
        stamp_proposal(env.home, rid)  # CLI-generates the script bytes
    return record


def run_guard(script, payload) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(script)], input=json.dumps(payload), capture_output=True, text=True
    )


NAME = script_name(RID, TRIGGER)  # self-learn-0000aaaa-about-to-edit.sh


class TestRouteHook:
    def test_two_phase_route_lands_a_working_guard(self, env):
        seed_hook(env)
        result = verbs.route(env.home, RID)  # proposal carries the destination

        # ledger phase: pinned subject, record resolved, proposal swept
        assert result.commit_message == f"self-learn: route {RID} → hook"
        assert env.resolved().is_file() and not env.pending().exists()
        assert not (env.bucket / "proposals" / f"{RID}.yaml").exists()

        # host phase: script committed at the M3-7 skill-scoped path,
        # executable, pushed; apply subject pinned
        script = env.host / "plugins" / "s-plugin" / "hooks" / NAME
        assert script.is_file()
        assert script.stat().st_mode & stat.S_IXUSR
        rel = f"plugins/s-plugin/hooks/{NAME}"
        assert env.host_subject() == f"self-learn: apply {RID} → {rel} (hook)"
        assert rel in env.host_remote_files()

        # M3-11: snippet logged in the host commit body
        assert '"PreToolUse"' in env.host_body()
        assert f"$HOME/.claude/hooks/{NAME}" in env.host_body()

        # the approval flow surfaces: entire script as the diff + the
        # manual steps (install.sh + settings.json) as post notes
        assert result.diff is not None and result.diff.startswith("#!/usr/bin/env bash")
        notes = "\n".join(result.post_notes)
        assert "./install.sh" in notes
        assert "settings.json" in notes
        assert '"matcher": "Edit|Write"' in notes

        # M3-2 verbatim: the committed bytes ARE the approved proposal bytes
        assert script.read_text(encoding="utf-8") == result.diff

        # routing.hook carries the approved compile artifacts (recompile's
        # input — H-2 must hold for hooks too)
        routed = Record.from_path(env.resolved())
        meta = routed.routing["hook"]
        assert meta["script_path"] == rel
        assert meta["script"] == result.diff
        assert meta["tools"] == ["Edit", "Write"]

        # and the guard actually guards
        deny = run_guard(script, {"tool_name": "Edit", "tool_input": {"file_path": "/.storage/x"}})
        assert deny.returncode == 2 and RID in deny.stderr
        allow = run_guard(script, {"tool_name": "Edit", "tool_input": {"file_path": "/ok.yaml"}})
        assert allow.returncode == 0

    def test_project_scope_lands_under_self_learn_plugin(self, env):
        # M3-7: project/user-scoped records → plugins/self-learn/hooks/.
        rid = "lrn-0000cccc"
        record = make_behavior(scope="project", record_id=rid, trigger=TRIGGER)
        create_record(env.home, record, project_path=env.host)
        write_proposal(env.home, rid, hook_proposal())
        stamp_proposal(env.home, rid)
        verbs.route(env.home, rid)
        rel = f"plugins/self-learn/hooks/{script_name(rid, TRIGGER)}"
        assert (env.host / rel).is_file()
        assert env.host_subject() == f"self-learn: apply {rid} → {rel} (hook)"

    def test_replay_mismatch_aborts_before_any_commit(self, env):
        # M3-12: an allow example the guard denies aborts the route.
        seed_hook(
            env,
            examples={
                "allow": [
                    # WRONG on purpose: matches the deny regex
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/ok.yaml"}},
                ],
                "deny": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/y/.storage/b"}},
                    {"tool_name": "Write", "tool_input": {"file_path": "/z/.storage/c"}},
                ],
            },
        )
        before = env.ledger_subject()
        with pytest.raises(verbs.VerbError, match="replay"):
            verbs.route(env.home, RID)
        assert env.pending().is_file()  # record untouched
        assert env.ledger_subject() == before  # nothing committed
        assert not list((env.host / "plugins").rglob("self-learn-*.sh"))

    def test_stale_record_sha_aborts_and_names_reanalysis(self, env):
        # M3-2: hash mismatch at apply time forces re-analysis + fresh
        # approval — never silent regeneration.
        record = seed_hook(env)
        path = env.pending()
        fresh = Record.from_path(path)
        fresh.set_body(fresh.body + "\n\nEdited after analysis.\n")
        fresh.write(path)
        with pytest.raises(verbs.VerbError, match="re-analys"):
            verbs.route(env.home, RID)
        assert env.pending().is_file()

    def test_unstamped_proposal_refused(self, env):
        seed_hook(env, stamp=False)  # no script, no fresh sha
        with pytest.raises(verbs.VerbError, match="proposal validate"):
            verbs.route(env.home, RID)

    def test_dest_hook_without_hook_proposal_refused(self, env):
        record = make_behavior(scope="skill:s", record_id=RID, trigger=TRIGGER)
        create_record(env.home, record)
        write_proposal(env.home, RID, proposal_dict())  # skill-md proposal
        stamp_proposal(env.home, RID)
        with pytest.raises(verbs.VerbError, match="hook"):
            verbs.route(env.home, RID, dest="hook")
        assert env.pending().is_file()

    def test_existing_script_path_collision_refused(self, env):
        seed_hook(env)
        hooks_dir = env.host / "plugins" / "s-plugin" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / NAME).write_text("#!/bin/sh\n", encoding="utf-8")
        with pytest.raises(verbs.VerbError, match="exists"):
            verbs.route(env.home, RID)
        assert env.pending().is_file()

    def test_route_direct_refuses_hook(self, env):
        # teach --route has no proposal to carry the approved bytes; the
        # hook flow is capture → analyze → approve (P9).
        record = make_behavior(scope="skill:s", trigger=TRIGGER)
        with pytest.raises(verbs.VerbError, match="hook"):
            verbs.route_direct(env.home, record, dest="hook")


class TestHookRollback:
    def seed_routed(self, env):
        seed_hook(env)
        result = verbs.route(env.home, RID)
        rel = f"plugins/s-plugin/hooks/{NAME}"
        return env.host / rel, rel

    def test_supersede_git_rms_script_and_reminds(self, env):
        # M3-4: durable correction — script removed in the host phase,
        # un-registration reminder printed.
        script, rel = self.seed_routed(env)
        new = make_behavior(scope="skill:s", record_id="lrn-0000bbbb")
        create_record(env.home, new)
        result = verbs.supersede(env.home, RID, "lrn-0000bbbb")
        assert not script.exists()
        assert env.host_subject() == f"self-learn: apply {RID} → {rel} (hook removed)"
        assert rel not in env.host_remote_files()
        text = "\n".join(result.warnings) + "\n".join(result.post_notes)
        assert "settings.json" in text and NAME in text

    def test_graduate_also_removes_the_script(self, env):
        # M3-4 names graduation too — there is no section to regenerate,
        # so removal cannot wait for a recompile that never comes.
        script, rel = self.seed_routed(env)
        result = verbs.graduate(env.home, RID)
        assert not script.exists()
        assert env.host_subject() == f"self-learn: apply {RID} → {rel} (hook removed)"


class TestHookRecompile:
    def test_recompile_restores_deleted_script_byte_identical(self, env):
        # H-2: a two-phase interruption (script vanished after the ledger
        # committed) is repaired by recompile — re-applying the APPROVED
        # bytes from routing.hook, never a regeneration from new inputs.
        seed_hook(env)
        result = verbs.route(env.home, RID)
        rel = f"plugins/s-plugin/hooks/{NAME}"
        script = env.host / rel
        approved = script.read_text(encoding="utf-8")
        git(env.host, "rm", "-q", str(script))
        git(env.host, "commit", "-q", "-m", "simulate lost host phase")

        rres = verbs.recompile(env.home)
        assert script.is_file()
        assert script.read_text(encoding="utf-8") == approved
        assert script.stat().st_mode & stat.S_IXUSR
        assert env.host_subject() == f"self-learn: recompile {rel}"

    def test_recompile_is_idempotent_for_hooks(self, env):
        seed_hook(env)
        verbs.route(env.home, RID)
        subject_before = env.host_subject()
        rres = verbs.recompile(env.home)
        assert env.host_subject() == subject_before  # no new commit
        assert all(e.commit_sha is None for e in rres.entries)


class TestWorklistGuards:
    """The three real open-follow-up records, replicated: each routes to a
    guard that denies its incident command and allows the near-miss."""

    def route_one(self, env, rid, trigger, hook, examples):
        record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
        create_record(env.home, record)
        write_proposal(
            env.home, rid, hook_proposal(hook=hook, examples=examples)
        )
        stamp_proposal(env.home, rid)
        verbs.route(env.home, rid)
        return env.host / "plugins" / "s-plugin" / "hooks" / script_name(rid, trigger)

    def test_chezmoi_cd_guard(self, env):
        # lrn-98d42215: chezmoi cd blocks forever in a non-interactive shell
        script = self.route_one(
            env,
            "lrn-98d42215",
            "About to run `chezmoi cd` in a non-interactive shell",
            {
                "tools": ["Bash"],
                "path_regex": r"(^|[;&|[:space:]])chezmoi[[:space:]]+cd([[:space:]]|$)",
                "deny_message": "chezmoi cd spawns an interactive child shell and blocks — use git -C \"$(chezmoi source-path)\" instead",
            },
            {
                "allow": [
                    {"tool_name": "Bash", "tool_input": {"command": "chezmoi diff"}},
                    {"tool_name": "Bash", "tool_input": {"command": 'git -C "$(chezmoi source-path)" status'}},
                ],
                "deny": [
                    {"tool_name": "Bash", "tool_input": {"command": "chezmoi cd"}},
                    {"tool_name": "Bash", "tool_input": {"command": "cd /tmp && chezmoi cd"}},
                ],
            },
        )
        assert run_guard(script, {"tool_name": "Bash", "tool_input": {"command": "chezmoi cd"}}).returncode == 2
        assert run_guard(script, {"tool_name": "Bash", "tool_input": {"command": "chezmoi cd-what a-weird-arg"}}).returncode == 0

    def test_sudo_npm_global_guard(self, env):
        # lrn-6883f824: sudo npm install -g writes into pacman territory
        script = self.route_one(
            env,
            "lrn-6883f824",
            "About to run sudo npm install -g on this Arch system",
            {
                "tools": ["Bash"],
                "path_regex": r"sudo([[:space:]]+[^[:space:]]+)*[[:space:]]+npm[[:space:]]+(install|i|add)([[:space:]]+[^[:space:]]+)*[[:space:]]+(-g|--global)",
                "deny_message": "never sudo npm install -g here — it splits pacman's npm ownership; use pacman/paru or a user prefix",
            },
            {
                "allow": [
                    {"tool_name": "Bash", "tool_input": {"command": "npm install -g yarn --prefix ~/.local"}},
                    {"tool_name": "Bash", "tool_input": {"command": "sudo npm --version"}},
                ],
                "deny": [
                    {"tool_name": "Bash", "tool_input": {"command": "sudo npm install -g corepack"}},
                    {"tool_name": "Bash", "tool_input": {"command": "sudo npm install --global npm@latest"}},
                ],
            },
        )
        assert run_guard(script, {"tool_name": "Bash", "tool_input": {"command": "sudo npm install -g npm"}}).returncode == 2
        assert run_guard(script, {"tool_name": "Bash", "tool_input": {"command": "npm install left-pad"}}).returncode == 0

    def test_uv_venv_copy_guard(self, env):
        # lrn-25968266: cp -r/rsync of a uv project carries a poisoned .venv
        script = self.route_one(
            env,
            "lrn-25968266",
            "About to sandbox-copy a uv Python project",
            {
                "tools": ["Bash"],
                "path_regex": r"(cp[[:space:]]+-[a-zA-Z]*r|rsync[[:space:]])(.*[[:space:]])?[^[:space:]]*\.venv",
                "deny_message": "a copied .venv still points at the ORIGINAL tree — rm -rf <copy>/.venv and re-sync in the copy first",
            },
            {
                "allow": [
                    {"tool_name": "Bash", "tool_input": {"command": "cp -r src/ /tmp/scratch/"}},
                    {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/copy/.venv"}},
                ],
                "deny": [
                    {"tool_name": "Bash", "tool_input": {"command": "cp -r project/.venv /tmp/copy/.venv"}},
                    {"tool_name": "Bash", "tool_input": {"command": "rsync -a proj/.venv/ /tmp/copy/.venv/"}},
                ],
            },
        )
        assert run_guard(script, {"tool_name": "Bash", "tool_input": {"command": "cp -r p/.venv /tmp/c/.venv"}}).returncode == 2
        assert run_guard(script, {"tool_name": "Bash", "tool_input": {"command": "uv sync"}}).returncode == 0
