"""Shared importer plumbing (T9): report shape + the all-statuses origin index.

Both importers dedupe by ``evidence.origin`` against EVERY record in EVERY
status (01 §3.2 / S-14): a rejected entry must not resurrect on the next
run, and because the dedupe ledger *is* the records, it syncs across
machines for free. :func:`existing_origins` therefore sweeps ``pending/``
AND ``resolved/`` of every bucket under the home — never just the target
bucket — which is a superset of the per-bucket requirement and can never
wrongly re-import (origins embed their source path, so two buckets cannot
legitimately share one).

Defensive detail: a record file that fails schema parsing still contributes
its origins via a raw-text regex fallback. Losing dedupe silently on a
corrupt record is the exact failure the key exists to prevent, so the index
degrades soft, never blind.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops
from .ledger import discover_buckets
from .records import Record, RecordError

__all__ = ["ImportReport", "ImporterError", "commit_import", "existing_origins"]


class ImporterError(Exception):
    """An import source is missing or unreadable."""


@dataclass
class ImportReport:
    """Outcome of one import run. ``created``/``flagged_canon``/
    ``behavioral_minority`` carry record ids; ``skipped_dup`` and
    ``scan_refused`` carry origins (the entry never became a record, so the
    origin is its only stable name). ``origins`` maps created id → origin."""

    source: str
    created: list[str] = field(default_factory=list)
    origins: dict[str, str] = field(default_factory=dict)
    skipped_dup: list[str] = field(default_factory=list)
    flagged_canon: list[str] = field(default_factory=list)
    behavioral_minority: list[str] = field(default_factory=list)
    scan_refused: list[str] = field(default_factory=list)
    touched: list[Path] = field(default_factory=list)  # ledger paths (H-5 commit)
    #: False iff the records were written but their commit FAILED — the
    #: CLI turns this into a non-zero exit (BLOCKER B: 'wrote something,
    #: then reported success' is the class of bug being closed).
    committed: bool = True

    def summary(self) -> str:
        """Human-readable run summary (visible confirmation; CLI prints it)."""
        lines = [
            f"import --{self.source}: {len(self.created)} created, "
            f"{len(self.skipped_dup)} skipped (already imported), "
            f"{len(self.scan_refused)} refused by secret scan"
        ]
        for rid in self.created:
            lines.append(f"  + {rid}  ({self.origins.get(rid, '?')})")
        if self.flagged_canon:
            lines.append(
                f"  already-canon flagged ({len(self.flagged_canon)}): "
                + ", ".join(self.flagged_canon)
            )
        if self.behavioral_minority:
            lines.append(
                f"  card set — behavioral minority + unflagged knowledge "
                f"({len(self.behavioral_minority)}): "
                + ", ".join(self.behavioral_minority)
            )
        for origin in self.skipped_dup:
            lines.append(f"  = skipped dup  {origin}")
        for origin in self.scan_refused:
            lines.append(f"  ! scan-refused {origin}")
        return "\n".join(lines)


def commit_import(home: Path, report: ImportReport) -> bool:
    """H-5 (doc 13 §5): importers are producers — ONE ledger commit per
    run (pinned subject ``self-learn: import <n> record(s) --<source>``)
    + best-effort push. No-op when nothing was created.

    Returns True iff the records are COMMITTED (or there was nothing to
    commit). Same rule as ``teach``: with no watcher (H-5) nobody else
    ever commits them, so an uncommitted import is a failure the caller
    must surface, not a warning (audit 2026-07-16 BLOCKER B).

    The commit is locked + pathspec-scoped, so a racing background
    worker/miner can neither steal this import's files nor have its own
    swept in here; the push sits OUTSIDE the lock (it touches no index).

    **The importers hold the lock across their whole write loop** (audit
    2026-07-16 round 7 — the invariant: no ledger mutation may precede its
    lock), so ``commit_lock`` here is re-entrant and this function keeps
    working standalone. That matters most for ``--memory``, whose loop
    rewrites the TRACKED MEMORY.md index as it goes.

    No ``--no-push`` guard here: ``import`` HAS no such flag. It used to
    call ``worker.no_push_requested()``, which reads an env var that only
    ever exists in a worker/miner CHILD — `import` runs in the parent, so
    the guard could not fire, and the comment above it described a flag
    that does not exist (audit 2026-07-16 MAJOR F). Deleted rather than
    invented: nothing in the product asks for `import --no-push` today."""
    if not report.created or not report.touched:
        return True
    n = len(report.created)
    try:
        with gitops.commit_lock(home):
            gitops.stage(home, report.touched)
            gitops.commit(
                home,
                f"self-learn: import {n} record(s) --{report.source}",
                paths=report.touched,
            )
    except gitops.GitOpsError as exc:
        print(
            f"self-learn: IMPORT NOT COMMITTED ({exc})\n"
            f"  The {n} record(s) ARE written under {home}, but nothing else "
            "will ever commit them (doc 13 H-5: no watcher on the ledger).\n"
            f"  Repair: self-learn reconcile   (or, by hand: git -C {home} "
            f"add -A && git -C {home} commit -m 'self-learn: import {n} "
            f"record(s) --{report.source}')",
            file=sys.stderr,
        )
        return False
    try:
        gitops.push_if_remote(home)
    except gitops.GitOpsError as exc:
        print(
            f"self-learn: import committed but NOT pushed ({exc}) — run "
            "`self-learn push` to publish it",
            file=sys.stderr,
        )
    return True


# Fallback extraction from unparseable record files: both the flow style the
# schema example uses (- {origin: "...", note: ...}) and block style.
_ORIGIN_RE = re.compile(r"""origin:\s*(?:"([^"]+)"|'([^']+)'|([^,}\s][^,}\n]*))""")


def existing_origins(home: Path) -> set[str]:
    """Every ``evidence.origin`` present in any record, any status, any
    bucket under *home* — THE dedupe index (01 §3.2)."""
    origins: set[str] = set()
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            directory = bucket.path / sub
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                try:
                    record = Record.from_path(path)
                except RecordError:
                    try:
                        text = path.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    for m in _ORIGIN_RE.finditer(text):
                        value = next(g for g in m.groups() if g is not None)
                        origins.add(value.strip())
                    continue
                for entry in record.evidence:
                    value = entry.get("origin")
                    if isinstance(value, str) and value:
                        origins.add(value)
    return origins
