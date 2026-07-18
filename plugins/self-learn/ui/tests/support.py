"""Shared test helpers for the U2 ledger/model suite.

Mirrors the CLI package's own ``tests/support.py`` fixture shape (doc 13
sandbox: an independent ledger home + one paired host repo) — deliberately
NOT imported cross-package (ui tests never reach into the cli package's
tests/ dir); this is a small, self-contained port of just what U2 needs.

10 §0 rules 7/8: every helper here builds THROWAWAY repos under pytest
tmpdirs and returns an explicit env mapping tests thread through
``self_learn_ui.ledger``'s ``env=`` parameter — nothing here ever touches
the real ``~/.self-learn``, ``~/.claude``, or the real XDG dirs.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record

# ------------------------------------------------------------------ git


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
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

SKILL_MD_SEED = "# {name} skill\n\nAuthored prose stays put.\n"
CLAUDE_MD_SEED = "# host project\n\nAuthored context stays put.\n"


@dataclass
class SandboxEnv:
    ledger: Path
    host: Path
    skill_dir: Path
    skill_md: Path
    env: dict[str, str]


def make_env(tmp_path: Path, *, skills: tuple[str, ...] = ("s",)) -> SandboxEnv:
    """Build a ledger home + paired host repo (registered as BOTH skills
    root and project host), and an explicit env mapping
    (``XDG_CACHE_HOME``/``XDG_RUNTIME_DIR``/``SELF_LEARN_HOME`` redirected
    under *tmp_path*) ready to pass as ``env=`` to any ``ledger.py`` call
    — never mutates ``os.environ``."""
    host = tmp_path / "host-repo"
    init_repo(host)
    first = skills[0] if skills else "s"
    skill_dir = host / "plugins" / f"{first}-plugin" / "skills" / first
    for name in skills:
        d = host / "plugins" / f"{name}-plugin" / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(SKILL_MD_SEED.format(name=name), encoding="utf-8")
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

    cache_home = tmp_path / "cache"
    runtime_dir = tmp_path / "runtime"
    cache_home.mkdir()
    runtime_dir.mkdir()

    env = dict(os.environ)
    env["XDG_CACHE_HOME"] = str(cache_home)
    env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    env["SELF_LEARN_HOME"] = str(ledger)

    return SandboxEnv(
        ledger=ledger,
        host=host,
        skill_dir=skill_dir,
        skill_md=skill_dir / "SKILL.md",
        env=env,
    )


def bare_ledger(tmp_path: Path) -> Path:
    """A ledger home with the layout dirs but NO hosts.yaml — the
    'nothing registered' state (matches a foreign/unregistered bucket)."""
    home = tmp_path / "bare-ledger"
    init_repo(home)
    for sub in ("skills", "projects", "user", "telemetry"):
        (home / sub).mkdir()
    return home


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
    source: str = "teach",
) -> Record:
    return Record.create(
        type="behavior",
        scope=scope,
        source=source,
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
    source: str = "teach",
) -> Record:
    return Record.create(
        type="knowledge",
        scope=scope,
        source=source,
        fact=fact,
        record_id=record_id,
        created_at=created_at,
    )


def seed_record(ledger: Path, record: Record, *, project_path: Path | None = None) -> Path:
    return create_record(ledger, record, project_path=project_path)


def resolve_record_directly(
    ledger: Path,
    bucket_dir: Path,
    record: Record,
    *,
    destination: str = "skill-md",
    status: str = "routed",
) -> None:
    """Move a pending record's file straight to resolved/, bypassing the
    real verb (no git commit needed) — enough to exercise the
    resolved-elsewhere READ path (09 §11 P1-9c), which only cares that
    the record's status is no longer pending/deferred, AND the U9
    bulk-loop-resume idempotency check (10 §5 playbook: "re-running the
    bulk row is idempotent — already-resolved ids vanish from the
    group")."""
    record.set_status(status)
    if status == "routed":
        record.set_routing(
            {"routed_at": "2026-07-01T00:00:00Z", "destination": destination, "by": "human"}
        )
    dest_path = bucket_dir / "resolved" / f"{record.id}.md"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    record.write(dest_path)
    pending_path = bucket_dir / "pending" / f"{record.id}.md"
    pending_path.unlink(missing_ok=True)


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


def hook_proposal_fields() -> dict:
    return {
        "hook": {
            "tools": ["Edit", "Write"],
            "path_regex": r"\.storage/",
            "deny_message": "stop the HA container first",
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


def seed_proposal(ledger: Path, record_id: str, **overrides) -> Path:
    return write_proposal(ledger, record_id, proposal_dict(**overrides))


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


# ---------------------------------------------------- Y-15 client context
#
# The non-blocking pane start (09 §4.2 Y-15) drains the first turn as a
# background task on the APP's event loop. A bare TestClient runs every
# request on a throwaway per-request loop, which would destroy that task
# mid-flight — so route tests that touch panes enter the client's
# lifespan context (ONE persistent portal/loop per test) via the autouse
# stack conftest.py arms, and join turns deterministically through that
# same portal.

CLIENT_STACK = None  # armed per-test by conftest._client_contexts


def enter_client(client):
    """Enter *client*'s lifespan/portal context for the current test —
    required for any client whose requests spawn pane drains (Y-15)."""
    if CLIENT_STACK is None:
        raise RuntimeError("enter_client() used outside a test")
    return CLIENT_STACK.enter_context(client)


def join_pane_turn(client, manager) -> None:
    """Deterministic join on the background first turn
    (:meth:`PaneManager.wait_for_turn`) on the client's own loop."""
    assert client.portal is not None, "join_pane_turn needs an entered client"
    client.portal.call(manager.wait_for_turn)
