"""Auto-memory importer + S-13 prune sweep (T9).

Import (01 §3.2 / S-14; doc 13 §3): drain the native memory directory
(``~/.claude/projects/<proj>/memory/``) into the per-project bucket
(project-typed memories) / the user bucket as pending records, origin
preserved. Shape studied against the real dir:
``MEMORY.md`` is an index of ``- [Title](file.md) — hook`` lines; each
topic file is YAML frontmatter (``name`` / ``description`` /
``metadata.type`` / ``originSessionId``) + markdown body.

Contract choices (documented judgment calls):

- **One file = one memory = one record** — matching the memory system's own
  contract; never per-bullet splitting.
- Every ``*.md`` topic file in the directory imports (``MEMORY.md``
  excluded): an unindexed topic file still holds a memory; the index line,
  when present, is pruned alongside the file.
- All memory records are ``type: knowledge`` (``Fact`` = the frontmatter
  description, else the first body line; ``Context`` = the body). Memories
  are the platform's observations, not do/don't rules; triage re-classifies
  freely (02 §2).
- Scope: ``user`` when ``metadata.type`` is ``user`` or ``feedback`` (those
  are about how to work with the user, not about this project), ``project``
  otherwise (including files with no frontmatter).
- ``evidence.origin`` = ``memory/<file>.md#sha256:<12hex>`` of the
  normalized FULL file text (the shared normalization fn) — recomputable
  from the file alone, which is what lets the prune sweep detect drift.
  A memory file edited after import hashes differently, so re-import treats
  it as a new memory (the platform rewrote it) and the old record's file
  reference reports as drifted at prune time.

Dedupe: same all-statuses ``evidence.origin`` index as the backlog importer
(a rejected memory never resurrects). Every record body is secret-scanned
before write; hits skip that file (reported), never abort the run.

Prune (S-13): a POST-PROCESSING sweep over imported (``source:
auto-memory``) records in TERMINAL status only — routed / rejected /
superseded — never pending/deferred, never inline with adjudication.
It removes the topic file AND its ``MEMORY.md`` index line, refuses
in-flight records, leaves drifted files alone (origin hash no longer
matches the file — the memory changed since import), and reports exactly
what it did; ``dry_run`` lists without touching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import gitops
from . import scan as scan_mod
from .import_common import ImporterError, ImportReport, commit_import, existing_origins
from .ledger import discover_buckets
from .ledger_ops import create_record
from .normalize import sha_anchor
from .records import Record, RecordError

__all__ = ["PruneReport", "import_memory", "prune_memory"]

INDEX_BASENAME = "MEMORY.md"

#: metadata.type values that map to the user scope (about the user, not the
#: project); everything else — project, absent, unknown — stays project.
_USER_SCOPED_TYPES = frozenset({"user", "feedback"})

_ORIGIN_FORM = re.compile(r"^memory/(?P<file>[^#/]+\.md)#(?P<sha>sha256:[0-9a-f]{12})$")
_TERMINAL_STATUSES = frozenset({"routed", "rejected", "superseded"})


# ---------------------------------------------------------------- parsing


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Lenient frontmatter split: (mapping, body). Files without a
    parseable frontmatter block yield ({}, whole text)."""
    if not text.startswith("---\n"):
        return {}, text
    closing = text.find("\n---\n", len("---\n") - 1)
    if closing == -1:
        return {}, text
    fm_text = text[len("---\n") : closing + 1]
    body = text[closing + len("\n---\n") :]
    try:
        data = YAML(typ="safe").load(fm_text)
    except YAMLError:
        return {}, text
    return (data, body) if isinstance(data, dict) else ({}, text)


def _memory_scope(frontmatter: dict) -> str:
    metadata = frontmatter.get("metadata")
    mtype = metadata.get("type") if isinstance(metadata, dict) else None
    return "user" if mtype in _USER_SCOPED_TYPES else "project"


def _first_line(text: str) -> str:
    for line in text.split("\n"):
        if line.strip():
            return line.strip()
    return ""


# ----------------------------------------------------------------- import


def import_memory(
    home: Path, memory_dir: Path, *, project_path: Path | None = None
) -> ImportReport:
    """Import every topic file under *memory_dir* (one file = one record)
    into the per-project bucket (project-typed memories) or the user
    bucket. ``project_path`` binds the project records (doc 13 §3:
    import_memory imports THIS project's memory — default: the git
    toplevel of cwd, else cwd). Idempotent via the all-statuses origin
    index; scan-then-write; ONE ledger commit per run (H-5)."""
    memory_dir = Path(memory_dir)
    if not memory_dir.is_dir():
        raise ImporterError(f"no memory directory at {memory_dir}")
    if project_path is None:
        project_path = gitops.toplevel(Path.cwd()) or Path.cwd()

    known = existing_origins(home)
    report = ImportReport(source="auto-memory")

    # ONE lock across [first write → commit] (audit 2026-07-16 round 7 —
    # the invariant). `commit_import` takes it again re-entrantly and
    # pushes outside it. Refusing here costs nothing: the import is
    # idempotent by origin and re-runs.
    with gitops.commit_lock(home):
        _import_topics(home, memory_dir, project_path, known, report)
        report.committed = commit_import(home, report)  # H-5: one commit/run
    return report


def _import_topics(
    home: Path,
    memory_dir: Path,
    project_path: Path,
    known: set[str],
    report: ImportReport,
) -> None:
    """The write loop. **The caller holds the ledger lock.**"""
    for path in sorted(memory_dir.glob("*.md")):
        if path.name == INDEX_BASENAME:
            continue
        text = path.read_text(encoding="utf-8")
        origin = f"memory/{path.name}#{sha_anchor(text)}"
        if origin in known:
            report.skipped_dup.append(origin)
            continue
        known.add(origin)

        frontmatter, body = _parse_frontmatter(text)
        description = frontmatter.get("description")
        fact = (
            description
            if isinstance(description, str) and description.strip()
            else _first_line(body) or path.stem
        )
        context = body.strip() or None
        record = Record.create(
            type="knowledge",
            scope=_memory_scope(frontmatter),
            source="auto-memory",
            fact=fact,
            context=context,
        )
        if scan_mod.scan(record.to_text()):
            report.scan_refused.append(origin)
            continue
        record.append_evidence({"origin": origin})
        created = create_record(
            home,
            record,
            project_path=project_path if record.scope == "project" else None,
        )
        report.touched.append(created)
        meta = created.parent.parent / "meta.yaml"
        if meta.is_file() and meta not in report.touched:
            report.touched.append(meta)
        report.created.append(record.id)
        report.origins[record.id] = origin

    return None


# ------------------------------------------------------------------ prune


@dataclass
class PruneReport:
    """Outcome of one S-13 sweep. Each list holds ``(record_id, filename,
    status)`` tuples; ``pruned`` means removed (or would-remove when
    ``dry_run``)."""

    dry_run: bool = False
    pruned: list[tuple[str, str, str]] = field(default_factory=list)
    refused_in_flight: list[tuple[str, str, str]] = field(default_factory=list)
    drifted: list[tuple[str, str, str]] = field(default_factory=list)
    missing: list[tuple[str, str, str]] = field(default_factory=list)

    def summary(self) -> str:
        verb = "would prune" if self.dry_run else "pruned"
        lines = [
            f"memory prune sweep ({'dry run' if self.dry_run else 'live'}): "
            f"{len(self.pruned)} {verb}, {len(self.refused_in_flight)} in-flight "
            f"refused, {len(self.drifted)} drifted (left alone), "
            f"{len(self.missing)} already gone"
        ]
        for rid, fname, status in self.pruned:
            lines.append(f"  - {verb} {fname} + its index line  ({rid}, {status})")
        for rid, fname, status in self.refused_in_flight:
            lines.append(f"  ! refused {fname}: {rid} is {status} (in flight)")
        for rid, fname, status in self.drifted:
            lines.append(
                f"  ! left {fname}: content changed since import ({rid}, {status})"
            )
        for rid, fname, status in self.missing:
            lines.append(f"  = {fname} already absent ({rid}, {status})")
        return "\n".join(lines)


def _memory_origin(record: Record) -> tuple[str, str] | None:
    """First ``memory/<file>.md#sha256:...`` evidence origin → (file, sha)."""
    for entry in record.evidence:
        origin = entry.get("origin")
        if isinstance(origin, str):
            m = _ORIGIN_FORM.match(origin)
            if m:
                return m.group("file"), m.group("sha")
    return None


def _drop_index_line(memory_dir: Path, filename: str) -> bool:
    """Remove the MEMORY.md index line(s) linking *filename*. True iff the
    index changed."""
    index = memory_dir / INDEX_BASENAME
    if not index.is_file():
        return False
    lines = index.read_text(encoding="utf-8").split("\n")
    link = re.compile(r"\(" + re.escape(filename) + r"\)")
    kept = [line for line in lines if not link.search(line)]
    if kept == lines:
        return False
    index.write_text("\n".join(kept), encoding="utf-8")
    return True


def prune_memory(home: Path, memory_dir: Path, dry_run: bool = False) -> PruneReport:
    """S-13 sweep: for every ``source: auto-memory`` record under *home*,
    prune its memory file + index line iff the record is TERMINAL and the
    file still hashes to the imported origin. See the module docstring."""
    memory_dir = Path(memory_dir)
    report = PruneReport(dry_run=dry_run)

    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            directory = bucket.path / sub
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                try:
                    record = Record.from_path(path)
                except RecordError:
                    continue  # unparseable records never drive deletions
                if record.source != "auto-memory":
                    continue
                ref = _memory_origin(record)
                if ref is None:
                    continue
                filename, sha = ref
                item = (record.id, filename, record.status)

                target = memory_dir / filename
                if record.status not in _TERMINAL_STATUSES:
                    report.refused_in_flight.append(item)
                    continue
                if not target.is_file():
                    report.missing.append(item)
                    continue
                if sha_anchor(target.read_text(encoding="utf-8")) != sha:
                    report.drifted.append(item)  # changed since import
                    continue
                if not dry_run:
                    target.unlink()
                    _drop_index_line(memory_dir, filename)
                report.pruned.append(item)

    return report
