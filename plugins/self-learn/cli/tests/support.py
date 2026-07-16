"""Shared test helpers: sandbox git repos, record/proposal factories.

Tests create throwaway git repos under pytest tmpdirs and run git freely
inside them — never against the worktree repo itself.
"""

from __future__ import annotations

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
