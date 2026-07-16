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
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOME = "~/.self-learn"

#: The layout dirs + registry that a bootstrapped home has (doc 13 §3).
_LAYOUT = ("skills", "projects", "user", "telemetry")

HOME_STATES = ("ok", "missing", "not-a-repo", "uninitialized")

#: A surface asked about a home that is missing / not a git repo. Distinct
#: from "empty ledger" (0) and from a refusal (1): the question could not be
#: answered at all. It lives HERE, beside :func:`home_state`, because it is
#: a home fact — `cli` and `teach` both import it rather than each pinning
#: their own integer (audit 2026-07-16 MINOR G: they had drifted, `teach`
#: returning 2 for a bad home where all eight other surfaces returned 5).
EXIT_NO_HOME = 5


def resolve_home() -> Path:
    """Resolve the ledger home: $SELF_LEARN_HOME, else the default, expanded."""
    raw = os.environ.get("SELF_LEARN_HOME") or DEFAULT_HOME
    return Path(raw).expanduser()


def home_state(home: Path | str | None = None) -> str:
    """Classify the resolved home — the silent-failure gate (audit
    2026-07-16 BLOCKER 11).

    ``discover_buckets`` globs; a home that does not exist simply globs to
    ``[]``, so every read surface rendered a confident all-clear ("0
    pending", exit 0) for a home that was never there — a wrong or unset
    ``SELF_LEARN_HOME`` (a systemd unit resolving a different home than
    the shell is the live case) made the whole ledger invisible with no
    error anywhere. Zero pending and no ledger at all are opposite facts
    and must never render the same.

    States: ``missing`` (no such dir) · ``not-a-repo`` (a dir, but not a
    git work tree — the ledger IS a git repo, doc 13 §2) ·
    ``uninitialized`` (a git repo with no layout dirs and no hosts.yaml —
    never bootstrapped) · ``ok``. An initialized home with zero records is
    ``ok``: an empty ledger is a legitimate, and quiet, state."""
    home = Path(home) if home is not None else resolve_home()
    if not home.is_dir():
        return "missing"
    proc = subprocess.run(
        ["git", "-C", str(home), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return "not-a-repo"
    if any((home / d).is_dir() for d in _LAYOUT) or (home / "hosts.yaml").is_file():
        return "ok"
    return "uninitialized"


def home_state_message(state: str, home: Path | str) -> str:
    """The loud, actionable line every read surface prints for a bad home
    (and every write surface refuses with)."""
    if state == "missing":
        return (
            f"ledger home {home} does not exist — self-learn cannot see any "
            "records (this is NOT an empty ledger). Check $SELF_LEARN_HOME, "
            "or clone/bootstrap the ledger repo there."
        )
    if state == "not-a-repo":
        return (
            f"ledger home {home} is not a git repo — the ledger is a git "
            "repo (doc 13 §2) and every producer commits its own writes "
            "(H-5). Check $SELF_LEARN_HOME, or clone the ledger repo there."
        )
    if state == "uninitialized":
        return (
            f"ledger home {home} has no layout dirs and no hosts.yaml — it "
            "was never bootstrapped (doc 13 §3). Clone the ledger repo, or "
            "create skills/ projects/ user/ telemetry/ + register a host "
            "(`self-learn host add <path>`)."
        )
    return f"ledger home {home} ok"


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
