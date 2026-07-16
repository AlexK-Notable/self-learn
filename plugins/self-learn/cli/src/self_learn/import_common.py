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


def commit_import(home: Path, report: ImportReport) -> None:
    """H-5 (doc 13 §5): importers are producers — ONE ledger commit per
    run (pinned subject ``self-learn: import <n> record(s) --<source>``)
    + best-effort push. No-op when nothing was created; a git failure is
    loud but never un-imports the records."""
    if not report.created or not report.touched:
        return
    n = len(report.created)
    try:
        gitops.stage(home, report.touched)
        gitops.commit(
            home, f"self-learn: import {n} record(s) --{report.source}"
        )
    except gitops.GitOpsError as exc:
        print(
            f"self-learn: import commit failed ({exc}) — records written "
            "but uncommitted",
            file=sys.stderr,
        )
        return
    if gitops.has_remote(home):
        gitops.push_with_retry(home)


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
