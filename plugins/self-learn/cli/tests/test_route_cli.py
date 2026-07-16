"""T8: `teach --route` (deterministic --dest path + one-shot analyst) and
the CLI verb wiring (route/reject/defer/graduate/supersede/push/sentinel).

All CLI-level via cli.main (the console entry's target). Sandbox git repos
with bare remotes under tmpdirs; the sentinel is XDG-redirected; the
analyst's `claude` is a PATH shim that records its argv.
"""

import os
import stat
import subprocess
import time

import pytest

from self_learn import analyst, cli, sentinel
from self_learn.analyst import ANALYST_ALLOWED_TOOLS, DEFAULT_ANALYST_MODEL
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import (
    SKILL_MD_SEED,
    commit_all,
    git,
    last_verb_sha,
    make_behavior,
    make_env,
    proposal_dict,
    verb_files,
    verb_subject,
)

SKILL_MD = SKILL_MD_SEED.format(name="s")

# doc 13 T-H3: the routing doctrine now ships with the CLI PACKAGE (one
# file, package-relative) — it is ALWAYS present, no longer installed into
# any home. Tests read the shipped text rather than seeding their own.
DOCTRINE_TEXT = analyst.doctrine_path().read_text(encoding="utf-8")

# argv NUL-separated: args (the doctrine text, the prompt) are multi-line.
CLAUDE_SHIM = """#!/usr/bin/env bash
printf '%s\\0' "$@" > "$CLAUDE_SHIM_LOG"
cat "$CLAUDE_SHIM_OUT"
exit "${CLAUDE_SHIM_EXIT-0}"
"""

TEACH_ARGS = [
    "teach",
    "--skill",
    "s",
    "--type",
    "behavior",
    "--kind",
    "anti-pattern",
    "--trigger",
    "About to edit .storage while HA is running.",
    "--instruction",
    "Stop the container first.",
]


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel goes to a per-test XDG cache, never the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


class Env:
    """The doc-13 sandbox pair: an independent LEDGER home (skill `s`
    bucket, hosts.yaml registering the host) with a bare remote, plus the
    HOST repo (plugins/s-plugin/skills/s/SKILL.md) with its own bare remote
    so the two-phase canon push is clean. Records live in the ledger; canon
    compiles into the host."""

    def __init__(self, tmp_path):
        e = make_env(tmp_path)
        self.home = e.ledger
        self.host = e.host
        self.skill_dir = e.skill_dir  # host-side plugins/s-plugin/skills/s
        self.skill_md = e.skill_md  # host-side SKILL.md (seeded by make_env)
        self.bare = tmp_path / "remote.git"
        self.host_bare = tmp_path / "host-remote.git"
        for bare, repo in ((self.bare, self.home), (self.host_bare, self.host)):
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
            )
            git(repo, "remote", "add", "origin", str(bare))
            git(repo, "push", "-q", "-u", "origin", "main")
        # the ledger's seed subject, for "commit stayed local" assertions
        self.seed_subject = self.local_subject()

    # -- ledger (home) side
    #
    # doc 13 H-5 (audit 2026-07-16 MAJOR 3): telemetry commits ITSELF now,
    # on top of the verb's commit — so "the verb's commit" is the newest
    # NON-flush commit, not HEAD. The assertions keep their strength: the
    # verb commit must still be the newest thing besides the flush, with
    # its exact pinned subject and its exact file list.
    def local_subject(self):
        return verb_subject(self.home)

    def local_body(self):
        return git(
            self.home, "log", "-1", "--format=%B", last_verb_sha(self.home)
        ).stdout

    def remote_subject(self):
        return verb_subject(self.bare)

    def remote_files(self):
        return git(self.bare, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()

    def committed_files(self):
        return verb_files(self.home)

    # -- host side (compiled canon)
    def host_subject(self):
        return git(self.host, "log", "-1", "--format=%s").stdout.strip()

    def host_committed_files(self):
        return git(
            self.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()

    # -- ledger bucket paths (skills/s/{pending,resolved})
    def pending_files(self):
        pending = self.home / "skills" / "s" / "pending"
        return sorted(pending.glob("lrn-*.md")) if pending.is_dir() else []

    def resolved_files(self):
        resolved = self.home / "skills" / "s" / "resolved"
        return sorted(resolved.glob("lrn-*.md")) if resolved.is_dir() else []

    def pending(self, rid):
        return self.home / "skills" / "s" / "pending" / f"{rid}.md"

    def resolved(self, rid):
        return self.home / "skills" / "s" / "resolved" / f"{rid}.md"


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


@pytest.fixture
def claude_shim(tmp_path, monkeypatch):
    """PATH-shimmed fake `claude`: records argv (one arg per line) to
    CLAUDE_SHIM_LOG, emits CLAUDE_SHIM_OUT on stdout."""
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    shim = shim_dir / "claude"
    shim.write_text(CLAUDE_SHIM, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "claude-shim-argv.log"
    out = tmp_path / "claude-shim-stdout.txt"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLAUDE_SHIM_LOG", str(log))
    monkeypatch.setenv("CLAUDE_SHIM_OUT", str(out))
    return {"log": log, "out": out}


def seed_pending(env, rid="lrn-0000aaaa", **kwargs):
    record = make_behavior(record_id=rid, **kwargs)
    create_record(env.home, record)
    commit_all(env.home, "seed record")
    git(env.home, "push", "-q")
    return record


def sole(paths):
    (path,) = paths
    return path


# ------------------------------------------------- teach --route --dest


def test_teach_route_dest_end_to_end(env, capsys):
    rc = cli.main(TEACH_ARGS + ["--route", "--dest", "skill-md"])
    out = capsys.readouterr().out
    assert rc == 0

    # Record landed in resolved/ as status: routed — never in pending/.
    assert env.pending_files() == []
    resolved_path = sole(env.resolved_files())
    record = Record.from_path(resolved_path)
    assert record.status == "routed"
    assert record.routing["destination"] == "skill-md"
    assert record.routing["by"] == "human"

    # Compiled section carries the record's line — in the HOST's SKILL.md.
    assert record.id in env.skill_md.read_text(encoding="utf-8")

    # Two-phase (doc 13 §4): LEDGER commit moves the record to resolved/;
    # HOST commit applies the compiled SKILL.md. Each repo touched exactly
    # its own path, and both were pushed.
    assert env.local_subject() == f"self-learn: route {record.id} → skill-md"
    assert env.committed_files() == [f"skills/s/resolved/{record.id}.md"]
    assert env.remote_subject() == f"self-learn: route {record.id} → skill-md"
    assert f"skills/s/resolved/{record.id}.md" in "\n".join(env.remote_files())

    assert env.host_subject() == (
        f"self-learn: apply {record.id} → "
        "plugins/s-plugin/skills/s/SKILL.md (skill-md)"
    )
    assert env.host_committed_files() == ["plugins/s-plugin/skills/s/SKILL.md"]

    # The applied diff was printed (no confirmation prompt anywhere).
    assert "diff --git" in out
    assert "SKILL.md" in out
    assert f"routed {record.id} → skill-md @" in out
    assert "(pushed)" in out


def test_teach_route_dest_note_rides_record_and_commit_body(env, capsys):
    rc = cli.main(
        TEACH_ARGS + ["--route", "--dest", "skill-md", "--note", "hard-won lesson"]
    )
    assert rc == 0
    record = Record.from_path(sole(env.resolved_files()))
    assert record.resolution_note == "hard-won lesson"
    assert "hard-won lesson" in env.local_body()


def test_teach_route_dest_supersedes_same_commit(env, capsys):
    old = seed_pending(env)
    rc = cli.main(
        TEACH_ARGS + ["--route", "--dest", "skill-md", "--supersedes", old.id]
    )
    assert rc == 0
    new_record = Record.from_path(
        sole([p for p in env.resolved_files() if p.stem != old.id])
    )

    # Old record superseded in the SAME commit, pinned suffix on the subject.
    old_after = Record.from_path(env.resolved(old.id))
    assert old_after.status == "superseded"
    assert old_after.superseded_by == new_record.id
    assert (
        env.local_subject()
        == f"self-learn: route {new_record.id} → skill-md (supersedes {old.id})"
    )
    committed = env.committed_files()
    assert f"resolved/{old.id}.md" in "\n".join(committed)
    assert f"resolved/{new_record.id}.md" in "\n".join(committed)
    # Superseded records never compile (the old line is absent from the HOST).
    assert old.id not in env.skill_md.read_text(encoding="utf-8")


def test_teach_route_no_push_then_push(env, capsys):
    rc = cli.main(TEACH_ARGS + ["--route", "--dest", "skill-md", "--no-push"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "not pushed — --no-push" in out
    assert env.remote_subject() == env.seed_subject  # commit stayed local

    assert cli.main(["push"]) == 0
    assert env.remote_subject().startswith("self-learn: route lrn-")


# --------------------------------------------- teach --route (analyst path)


def test_teach_route_analyst_routes_to_shim_destination(env, claude_shim, capsys):
    claude_shim["out"].write_text(
        "```yaml\n"
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n"
        "```\n",
        encoding="utf-8",
    )
    rc = cli.main(TEACH_ARGS + ["--route"])
    out = capsys.readouterr().out
    assert rc == 0

    # Routed to the fake analyst's destination, never via pending/.
    assert env.pending_files() == []
    record = Record.from_path(sole(env.resolved_files()))
    assert record.routing["destination"] == "skill-md"
    assert env.remote_subject() == f"self-learn: route {record.id} → skill-md"
    assert "analyst: destination skill-md" in out

    # The recorded invocation: doctrine as system prompt, restricted tools,
    # pinned default model, record content riding the prompt.
    argv = claude_shim["log"].read_text(encoding="utf-8").split("\0")[:-1]
    assert "-p" in argv
    assert argv[argv.index("--append-system-prompt") + 1] == DOCTRINE_TEXT
    assert argv[argv.index("--model") + 1] == DEFAULT_ANALYST_MODEL
    allowed = argv[argv.index("--allowedTools") + 1]
    # The exact-string equality IS the no-write-tools assertion — a
    # separate "Bash not in allowed" check could never fail (audit
    # 2026-07-15: removed as a can't-fail assertion).
    assert allowed == ANALYST_ALLOWED_TOOLS == "Read,Grep,Glob"
    prompt = argv[argv.index("-p") + 1]
    assert "About to edit .storage while HA is running." in prompt


@pytest.mark.parametrize(
    "sabotage",
    [
        {"stdout": "::: not yaml {{{\n"},  # unparseable
        {"stdout": "just a string\n"},  # parses, not a mapping
        {"stdout": "destination: bogus\nrationale: r\n"},  # bad enum
        {"stdout": "destination: skill-md\n", "exit": "1"},  # non-zero exit
    ],
)
def test_teach_route_analyst_failure_captures_to_pending(
    env, claude_shim, capsys, monkeypatch, sabotage
):
    claude_shim["out"].write_text(sabotage["stdout"], encoding="utf-8")
    if "exit" in sabotage:
        monkeypatch.setenv("CLAUDE_SHIM_EXIT", sabotage["exit"])
    rc = cli.main(TEACH_ARGS + ["--route"])
    captured = capsys.readouterr()
    assert rc == 4

    # Never lost: the record sits in pending/ as a NORMAL teach.
    assert env.resolved_files() == []
    record = Record.from_path(sole(env.pending_files()))
    assert record.status == "pending"
    assert record.routing is None
    assert "analysis failed" in captured.err
    assert "captured to pending" in captured.err


def test_teach_route_missing_doctrine_exits_2_pre_spawn(
    env, claude_shim, capsys, monkeypatch, tmp_path
):
    # doc 13 T-H3: the doctrine ships package-relative and is normally
    # always present. Force the "not installed" branch by pointing the
    # package-refs resolver at an empty dir — the shim must never spawn.
    empty_refs = tmp_path / "empty-refs"
    empty_refs.mkdir()
    monkeypatch.setattr(
        "self_learn.worker.package_skill_refs", lambda: empty_refs
    )
    rc = cli.main(TEACH_ARGS + ["--route"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "routing doctrine not installed — T10" in err
    assert not claude_shim["log"].exists()  # pre-spawn
    assert env.pending_files() == [] and env.resolved_files() == []


# ----------------------------------------------------------- verb wiring


def test_route_cli_with_proposal_sibling(env, capsys):
    record = seed_pending(env)
    write_proposal(env.home, record.id, proposal_dict())
    commit_all(env.home, "proposal")

    rc = cli.main(["route", record.id])
    out = capsys.readouterr().out
    assert rc == 0
    assert env.resolved(record.id).is_file()
    assert env.local_subject() == f"self-learn: route {record.id} → skill-md"
    assert env.remote_subject() == f"self-learn: route {record.id} → skill-md"
    assert record.id in env.skill_md.read_text(encoding="utf-8")
    sha7 = git(
        env.home, "rev-parse", "--short=7", last_verb_sha(env.home)
    ).stdout.strip()
    assert f"route {record.id} → skill-md @ {sha7} (pushed)" in out


def test_route_cli_no_proposal_no_dest_exits_1(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["route", record.id])
    assert rc == 1
    assert "no proposal" in capsys.readouterr().err


def test_route_cli_bare_new_skill_exits_1_naming_the_recipe(env, capsys):
    # supersedes the M1-era exit-2 "not built until M3" check: the
    # compiler exists (T18), but the name slot is the human's call.
    record = seed_pending(env)
    rc = cli.main(["route", record.id, "--dest", "new-skill"])
    assert rc == 1
    assert "new-skill:<name>" in capsys.readouterr().err
    assert env.pending(record.id).is_file()  # untouched


def test_reject_cli_note_in_commit_body(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["reject", record.id, "--note", "duplicate of canon"])
    out = capsys.readouterr().out
    assert rc == 0
    assert env.local_subject() == f"self-learn: reject {record.id}"
    assert "duplicate of canon" in env.local_body()
    assert Record.from_path(env.resolved(record.id)).status == "rejected"
    assert f"reject {record.id} → rejected @" in out


def test_defer_cli_until_date(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["defer", record.id, "--until", "2027-01-01"])
    out = capsys.readouterr().out
    assert rc == 0
    after = Record.from_path(env.pending(record.id))  # defer stays pending
    assert str(after.deferred_until) == "2027-01-01"
    assert env.local_subject() == f"self-learn: defer {record.id} until 2027-01-01"
    assert f"defer {record.id} → deferred until 2027-01-01 @" in out


def test_defer_cli_bad_date_is_usage_error(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["defer", record.id, "--until", "next tuesday"])
    assert rc == 64
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_graduate_cli(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["graduate", record.id])
    assert rc == 0
    after = Record.from_path(env.resolved(record.id))
    assert after.status == "superseded"
    assert after.superseded_by == "canon"
    assert env.local_subject() == f"self-learn: graduate {record.id}"


def test_supersede_cli(env, capsys):
    old = seed_pending(env, rid="lrn-0000aaaa")
    new = seed_pending(env, rid="lrn-0000bbbb")
    rc = cli.main(["supersede", old.id, new.id])
    assert rc == 0
    after = Record.from_path(env.resolved(old.id))
    assert after.superseded_by == new.id
    assert env.local_subject() == f"self-learn: supersede {old.id} → {new.id}"


def test_verb_no_push_then_bare_push(env, capsys):
    record = seed_pending(env)
    rc = cli.main(["reject", record.id, "--no-push"])
    assert rc == 0
    assert "not pushed — --no-push" in capsys.readouterr().out
    assert env.remote_subject() == "seed record"

    rc = cli.main(["push"])
    assert rc == 0
    assert env.remote_subject() == f"self-learn: reject {record.id}"


def test_unknown_record_id_is_usage_error(env, capsys):
    rc = cli.main(["reject", "lrn-deadbeef"])
    assert rc == 64
    assert "not found" in capsys.readouterr().err


def test_malformed_record_id_is_usage_error(env, capsys):
    rc = cli.main(["route", "not-an-id"])
    assert rc == 64
    assert "not a record id" in capsys.readouterr().err


# --------------------------------------------------------------- sentinel


def test_sentinel_hold_heartbeat_release_cycle(env, capsys):
    path = sentinel.sentinel_path()

    assert cli.main(["sentinel", "hold"]) == 0
    assert path.is_file()
    assert "sentinel held" in capsys.readouterr().out

    # heartbeat re-touches a live sentinel's mtime.
    old = time.time() - 600
    os.utime(path, (old, old))
    assert cli.main(["sentinel", "heartbeat"]) == 0
    assert path.stat().st_mtime > old + 1
    assert "sentinel heartbeat" in capsys.readouterr().out

    assert cli.main(["sentinel", "release"]) == 0
    assert not path.exists()
    assert "sentinel released" in capsys.readouterr().out


def test_sentinel_heartbeat_without_hold_is_noop(env, capsys):
    assert cli.main(["sentinel", "heartbeat"]) == 0
    assert "no live sentinel" in capsys.readouterr().out
    assert not sentinel.sentinel_path().exists()


def test_sentinel_release_without_hold(env, capsys):
    assert cli.main(["sentinel", "release"]) == 0
    assert "none held" in capsys.readouterr().out


def test_verbs_self_hold_releases_only_own_sentinel(env, capsys):
    # A pre-existing LIVE hold (the slash review's batch hold) survives a verb.
    assert cli.main(["sentinel", "hold"]) == 0
    record = seed_pending(env)
    assert cli.main(["reject", record.id]) == 0
    assert sentinel.sentinel_path().is_file()  # not released by the verb
    assert cli.main(["sentinel", "release"]) == 0
    assert not sentinel.sentinel_path().exists()
