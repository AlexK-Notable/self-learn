"""Ledger-home resolution and bucket discovery (doc 13 §3 layout).

Pins (doc 13 §1 Q1 / §3; H-1):
- Ledger home: ``SELF_LEARN_HOME`` env var, default ``~/.self-learn``,
  expanduser'd — explicit, never inferred from cwd. All bucket paths
  resolve against it.
- Bucket discovery on the independent-home layout:
  ``skills/<name>/`` → one skill bucket each (name = the dir name);
  ``projects/<slug>/`` → one project bucket each (name = the slug dir,
  path recorded in the sibling ``meta.yaml`` — the slug alone is lossy);
  ``user/`` → the single user bucket. Only dirs that exist.

Queue semantics (deferred_until hiding, eligibility) live in
:mod:`self_learn.ledger_ops` — :func:`Bucket.pending_files` is the raw
directory listing that feeds them, never a queue definition of its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOME = "~/.self-learn"


def resolve_home() -> Path:
    """Resolve the ledger home: $SELF_LEARN_HOME, else the default, expanded."""
    raw = os.environ.get("SELF_LEARN_HOME") or DEFAULT_HOME
    return Path(raw).expanduser()


@dataclass(frozen=True)
class Bucket:
    """One ledger bucket: its directory, scope, and display name."""

    path: Path
    scope: str  # "skill" | "project" | "user"
    name: str

    def pending_files(self) -> list[Path]:
        """Raw listing: every pending/*.md file, sorted by name. Queue
        membership (deferral hiding) is computed in ledger_ops.queue()."""
        pending_dir = self.path / "pending"
        if not pending_dir.is_dir():
            return []
        return sorted(p for p in pending_dir.glob("*.md") if p.is_file())


def discover_buckets(home: Path | None = None) -> list[Bucket]:
    """Return every existing bucket under the ledger home (may be empty).

    Skill buckets under ``skills/``, per-project buckets under
    ``projects/`` (named by slug), and the single ``user/`` bucket.
    """
    if home is None:
        home = resolve_home()
    buckets: list[Bucket] = []
    for p in sorted(home.glob("skills/*")):
        if p.is_dir():
            buckets.append(Bucket(path=p, scope="skill", name=p.name))
    for p in sorted(home.glob("projects/*")):
        if p.is_dir():
            buckets.append(Bucket(path=p, scope="project", name=p.name))
    user = home / "user"
    if user.is_dir():
        buckets.append(Bucket(path=user, scope="user", name="user"))
    return buckets
