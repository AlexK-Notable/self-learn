"""Ledger-home resolution and bucket discovery.

Pins (docs/specs/self-learn/08-build-plan.md §1):
- Ledger home: ``SELF_LEARN_HOME`` env var, default ``~/repos/claude-skills``,
  expanduser'd. All bucket paths resolve against it.
- Bucket discovery: skill buckets = glob ``plugins/*/skills/*/.self-learn/``
  under home; the project+user bucket = ``<home>/.self-learn/``.

Queue semantics (deferred_until hiding, eligibility) live in
:mod:`self_learn.ledger_ops` — :func:`Bucket.pending_files` is the raw
directory listing that feeds them, never a queue definition of its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOME = "~/repos/claude-skills"


def resolve_home() -> Path:
    """Resolve the ledger home: $SELF_LEARN_HOME, else the default, expanded."""
    raw = os.environ.get("SELF_LEARN_HOME") or DEFAULT_HOME
    return Path(raw).expanduser()


@dataclass(frozen=True)
class Bucket:
    """One .self-learn bucket: its directory, scope, and display name."""

    path: Path
    scope: str  # "skill" | "project+user"
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

    Skill buckets are named after their skill directory; the repo-root
    project+user bucket is named "project".
    """
    if home is None:
        home = resolve_home()
    buckets: list[Bucket] = []
    for p in sorted(home.glob("plugins/*/skills/*/.self-learn")):
        if p.is_dir():
            buckets.append(Bucket(path=p, scope="skill", name=p.parent.name))
    root = home / ".self-learn"
    if root.is_dir():
        buckets.append(Bucket(path=root, scope="project+user", name="project"))
    return buckets
