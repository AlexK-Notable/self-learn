"""Shared test helpers: sandbox git repos, record/proposal factories.

Tests create throwaway git repos under pytest tmpdirs and run git freely
inside them — never against the worktree repo itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from self_learn.records import Record

# ------------------------------------------------------------------ git


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")


def commit_all(repo: Path, message: str = "seed") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


_GIT_SHIM = '''#!/usr/bin/env python3
"""A REAL git that fails one subcommand while a flag file exists."""
import os, subprocess, sys

args = sys.argv[1:]
i, sub = 0, None
while i < len(args):
    a = args[i]
    if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
        i += 2
        continue
    if a.startswith("-"):
        i += 1
        continue
    sub = a
    break
if sub == {sub!r} and os.path.exists({flag!r}):
    sys.stderr.write("fatal: simulated git " + {sub!r} + " failure\\n")
    sys.exit(1)
sys.exit(subprocess.run([{real!r}, *args]).returncode)
'''


def failing_git_shim(tmp_path: Path, monkeypatch, *, sub: str = "commit") -> Path:
    """Put a REAL git shim on PATH that passes everything through to the
    real git except ``sub``, which fails while the returned FLAG file
    exists (audit 2026-07-16 round 7 BLOCKER 2's probe shape, made a
    fixture).

    A held lock is no longer a way to make a commit fail — the round-7
    invariant takes the lock BEFORE the first mutation, so a lock timeout
    is now a clean refusal that wrote nothing (which is the point). The
    ONLY way left to reach the half-written state is a git that fails at
    the commit itself, which is exactly what this produces — a real
    process failing a real exec, no mocks, and no monkeypatching of the
    code under test.

    Flag-gated rather than always-on so the surrounding test harness
    (:func:`commit_all` and friends) can still use git normally: create
    the flag immediately before the call under test, remove it after."""
    real = shutil.which("git")
    assert real, "no git on PATH"
    d = tmp_path / f"git-shim-{sub}"
    d.mkdir(parents=True, exist_ok=True)
    flag = tmp_path / f"fail-git-{sub}"
    shim = d / "git"
    shim.write_text(_GIT_SHIM.format(sub=sub, flag=str(flag), real=real))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    return flag


#: The producer commit telemetry makes for itself (doc 13 H-5; audit
#: 2026-07-16 MAJOR 3). It rides on TOP of a verb's own commit, so "the
#: verb's commit" is no longer a synonym for HEAD.
TELEMETRY_SUBJECT = "self-learn: telemetry flush"


def last_verb_sha(repo: Path) -> str:
    """The newest commit that is NOT a telemetry-flush commit — i.e. the
    verb's own commit. Assertions keep their full strength: the verb
    commit must still be the newest thing besides the flush, with its
    exact pinned subject and its exact file list."""
    for line in git(repo, "log", "--format=%H %s").stdout.splitlines():
        sha, _, subject = line.partition(" ")
        if not subject.startswith(TELEMETRY_SUBJECT):
            return sha
    raise AssertionError(f"no non-telemetry commit in {repo}")


def verb_subject(repo: Path) -> str:
    return git(
        repo, "log", "-1", "--format=%s", last_verb_sha(repo)
    ).stdout.strip()


def verb_files(repo: Path) -> list[str]:
    return git(
        repo,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        last_verb_sha(repo),
    ).stdout.split()


# ------------------------------------------------- ledger home + host repo


class SandboxEnv:
    """The doc-13 fixture surface: an independent LEDGER home plus one
    sandbox HOST repo (skills root + registered project host in one)."""

    def __init__(self, ledger: Path, host: Path, skills: tuple[str, ...]):
        self.ledger = ledger
        self.host = host
        first = skills[0] if skills else "s"
        self.skill_dir = host / "plugins" / f"{first}-plugin" / "skills" / first
        self.skill_md = self.skill_dir / "SKILL.md"


SKILL_MD_SEED = "# {name} skill\n\nAuthored prose stays put.\n"
CLAUDE_MD_SEED = "# host project\n\nAuthored context stays put.\n"


def make_env(tmp_path: Path, skills: tuple[str, ...] = ("s",)) -> SandboxEnv:
    """Build the NEW (doc 13 §3) sandbox pair:

    - HOST repo at ``tmp_path/host-repo``: ``plugins/<n>-plugin/skills/<n>/
      SKILL.md`` per skill + a root ``CLAUDE.md``, git init + seed commit.
    - LEDGER home at ``tmp_path/ledger-home``: git repo with the layout
      dirs (``skills/ projects/ user/ telemetry/``) and a ``hosts.yaml``
      registering the host repo as BOTH skills root and project host.
    """
    host = tmp_path / "host-repo"
    init_repo(host)
    for name in skills:
        skill_dir = host / "plugins" / f"{name}-plugin" / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            SKILL_MD_SEED.format(name=name), encoding="utf-8"
        )
    (host / "CLAUDE.md").write_text(CLAUDE_MD_SEED, encoding="utf-8")
    commit_all(host, "host seed")

    ledger = tmp_path / "ledger-home"
    init_repo(ledger)
    for sub in ("skills", "projects", "user", "telemetry"):
        (ledger / sub).mkdir()
    (ledger / "hosts.yaml").write_text(
        f"skills_root: {host}\nprojects:\n  - path: {host}\n", encoding="utf-8"
    )
    commit_all(ledger, "ledger seed")
    return SandboxEnv(ledger, host, skills)


def make_home(tmp_path: Path, skills: tuple[str, ...] = ("s",)) -> Path:
    """A sandbox ledger home on the doc-13 layout (see :func:`make_env`);
    returns the LEDGER path — the paired host repo sits at
    ``tmp_path/host-repo``."""
    return make_env(tmp_path, skills).ledger


# --------------------------------------------------------------- records


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_ago(n: int) -> str:
    return iso(datetime.now(timezone.utc) - timedelta(days=n))


def make_behavior(
    scope: str = "skill:s",
    record_id: str | None = None,
    created_at: str | None = None,
    trigger: str = "About to edit .storage while HA is running.",
    instruction: str = "Stop the container first.",
) -> Record:
    return Record.create(
        type="behavior",
        scope=scope,
        source="teach",
        kind="anti-pattern",
        trigger=trigger,
        instruction=instruction,
        record_id=record_id,
        created_at=created_at,
    )


def make_knowledge(
    scope: str = "project",
    record_id: str | None = None,
    created_at: str | None = None,
    fact: str = "The router reserves 192.168.1.232 for the Nova.",
) -> Record:
    return Record.create(
        type="knowledge",
        scope=scope,
        source="teach",
        fact=fact,
        record_id=record_id,
        created_at=created_at,
    )


# -------------------------------------------------------------- proposals


def proposal_dict(**overrides) -> dict:
    base = {
        "destination": "skill-md",
        "alternates": ["claude-md"],
        "rationale": "deterministic guard beats advisory text",
        "already_canon": False,
        "already_canon_reason": "",
        "record_sha": "sha256:000000000000",
        "model": "claude-opus-4-8",
        "analyzed_at": "2026-07-13T00:00:00Z",
    }
    base.update(overrides)
    return base


def merge_proposal_text(cluster_id: str, records: list[str], survivor: str) -> str:
    shas = "\n".join(f"  {r}: sha256:000000000000" for r in records)
    ids = ", ".join(records)
    return (
        f"cluster_id: {cluster_id}\n"
        f"records: [{ids}]\n"
        f"suggested_survivor: {survivor}\n"
        f"rationale: same lesson twice\n"
        f"record_shas:\n{shas}\n"
        f"model: claude-sonnet-5\n"
        f"analyzed_at: 2026-07-13T02:10:00Z\n"
    )
