"""Self-healing for orphaned ledger writes (audit 2026-07-16 round 7 MAJOR 4).

The ledger has **no watcher** (doc 13 H-5: every producer commits its own
writes), and every producer pathspec-commits ONLY its own paths (doc 08 §1
Resolution-verbs pin, BLOCKER 4 layer b). Those two rules compose into a
hole: a record whose producer wrote it and then failed to commit it is
committed by *nobody, ever*. It sits untracked until a ``git clone``
deletes it — and the miner's cursors have already advanced past its
origin, so it is never re-mined either (origin dedup reads landed records
off disk, and a file nobody committed still answers "already mined" to the
one process that could re-create it).

Probed shapes of the hole:

- ``mine``'s landing commit fails → ``_advance_cursors`` runs anyway. The
  ``landed-uncommitted`` status and the non-zero exit are HONEST, but
  honesty is not recovery: the records are lost on the next clone (MAJOR
  4).
- ``teach``'s capture commit fails → the record is on disk, and the CLI
  prints a repair command for a human to paste (BLOCKER B).

Reporting a data-loss window is not closing it. This module closes it: one
capability that finds orphaned ledger writes and commits them, under the
lock, by pathspec, with the pinned subject :data:`RECONCILE_SUBJECT`. It
is wired at three surfaces so the system heals without being asked:

1. ``self-learn reconcile`` — the human/agent-facing verb, and the command
   ``teach``'s capture-failure message now names as the repair.
2. ``miner.run`` calls it at run START — so a failed landing is committed
   by the NEXT nightly run, before it mines anything new. That is what
   turns "the records are lost on the next clone" into "the records are
   committed within a day, automatically".
3. ``self-learn push`` calls it first — publishing a ledger whose records
   are not even committed is the one moment the gap is most visible.

**Safety against a concurrent producer.** The scan runs INSIDE the commit
lock, not before it. That is load-bearing and only became true this round:
now that every producer takes the lock BEFORE its first mutation (the
round-7 invariant), a producer is never mid-write while we hold the lock,
so anything the scan sees uncommitted under the lock is orphaned BY
DEFINITION rather than merely in-flight. The commit is then pathspec-scoped
to exactly the paths the scan found (:func:`gitops.commit` with ``paths``),
so even a producer that starts the instant we release cannot have its work
absorbed into our commit.

**What it will NOT do.** It commits only files that EXIST and are
untracked-or-modified. It never commits a deletion and never touches a
staged rename: a half-committed ``git mv`` (the shape a resolution verb
leaves when its commit fails) must not be committed one half at a time —
that is the exact corruption :func:`gitops.known_paths` exists to prevent,
"the record in BOTH pending/ and resolved/, git status clean, exit 0".
Those entries are REPORTED as blocked, naming the verb's own printed
repair. Reconcile heals the shape it understands and refuses to guess at
the one it does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import gitops

__all__ = [
    "RECONCILE_SUBJECT",
    "ReconcileResult",
    "find_orphans",
    "reconcile",
]

#: The pinned commit subject. ``{n}`` is the record count.
RECONCILE_SUBJECT = "self-learn: reconcile {n} uncommitted record(s)"

#: Bucket-relative shapes reconcile owns: the ledger's actual data. A
#: file under a bucket that is none of these (a stray note, an editor
#: swapfile) is NOT the ledger's truth and is left alone — reconcile
#: commits records, it does not sweep directories.
_RECONCILABLE = (
    "pending/lrn-*.md",
    "resolved/lrn-*.md",
    "proposals/*.yaml",
    "meta.yaml",
)

#: Porcelain XY codes that mean "this path has a staged deletion or
#: rename" — the half-committed-``git mv`` shape reconcile must not touch.
_BLOCKING_CODES = ("R", "D")


@dataclass(frozen=True)
class ReconcileResult:
    """``committed`` — what landed (empty = nothing to do, the normal
    case). ``blocked`` — porcelain entries reconcile refused to guess at,
    verbatim, for a human. ``push`` — None when nothing was committed or
    ``no_push``."""

    committed: list[Path] = field(default_factory=list)
    sha: str | None = None
    blocked: list[str] = field(default_factory=list)
    push: gitops.PushResult | None = None

    @property
    def healed(self) -> bool:
        return bool(self.committed)


def _porcelain(home: Path) -> list[tuple[str, Path]]:
    """``git status --porcelain -uall`` → [(XY, path)]. ``-uall`` so a
    wholly-untracked BUCKET reports its files rather than the directory
    (the miner's very first landing into a new project bucket is exactly
    that case, and a directory pathspec would over-commit)."""
    proc = gitops._git(  # noqa: SLF001 — same module family
        home, "status", "--porcelain", "-uall"
    )
    if proc.returncode != 0:
        raise gitops.GitOpsError(
            f"git status in {home} failed: {(proc.stderr or proc.stdout).strip()}"
        )
    out: list[tuple[str, Path]] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        xy, rest = line[:2], line[3:]
        if " -> " in rest:  # rename: both halves, kept whole for the report
            rest = rest.split(" -> ", 1)[1]
        out.append((xy, home / rest.strip('"')))
    return out


def _is_reconcilable(home: Path, path: Path) -> bool:
    """True iff *path* is a ledger record/proposal/meta inside a bucket."""
    from .ledger import discover_buckets

    for bucket in discover_buckets(home):
        for pattern in _RECONCILABLE:
            if path.parent == (bucket.path / pattern).parent and path.match(pattern):
                return True
    return False


def find_orphans(home: Path) -> tuple[list[Path], list[str]]:
    """(paths to commit, blocked porcelain lines). Callers that intend to
    COMMIT the result must already hold :func:`gitops.commit_lock` — see
    the module docstring for why the scan belongs inside the lock."""
    orphans: list[Path] = []
    blocked: list[str] = []
    for xy, path in _porcelain(home):
        if not _is_reconcilable(home, path):
            continue
        if any(c in _BLOCKING_CODES for c in xy):
            blocked.append(f"{xy} {path}")
            continue
        if path.exists():
            orphans.append(path)
    return sorted(set(orphans)), blocked


def reconcile(home: Path, *, no_push: bool = False) -> ReconcileResult:
    """Commit every orphaned ledger write, under the lock, by pathspec.

    Idempotent and cheap: on a clean ledger it takes the lock, runs one
    ``git status``, and returns an empty result — which is why the miner
    and ``push`` can call it unconditionally."""
    home = Path(home)
    with gitops.commit_lock(home):
        orphans, blocked = find_orphans(home)
        if not orphans:
            return ReconcileResult(blocked=blocked)
        message = RECONCILE_SUBJECT.format(n=len(orphans))
        try:
            gitops.stage(home, orphans)
            sha = gitops.commit(home, message, paths=orphans)
        except gitops.GitOpsError as exc:
            # Post-mutation by construction (the paths are staged now).
            raise gitops.HalfWrittenError.for_commit(
                home, message, orphans, exc
            ) from exc
    # The push is OUTSIDE the lock (it touches no index — see the gitops
    # module docstring for the re-scope).
    push = None if no_push else gitops.push_if_remote(home)
    return ReconcileResult(committed=orphans, sha=sha, blocked=blocked, push=push)
