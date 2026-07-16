"""Backlog importer (T9): mine ``references/GOTCHAS.journal.md`` into
pending records — journal ONLY, per the 08 §1 Backlog-import-sources pin
(gate-check F3): ``GOTCHAS.md`` is authored canon and the revisions file is
history; importing either would double the card set with cross-file
duplicates origin-dedupe cannot catch.

Journal shape (studied against the real ~58-entry corpus): entries are
``### YYYY-MM-DD — Title`` headings followed by ``- **Field:** value``
bullets (Status / HA version / Cause / Fix / Repro / Tags); an entry runs
to the next ``### `` heading or EOF.

Origin anchors (08 §1 Dedupe-key pin — never line numbers):

- The FIRST entry carrying a given date gets the date anchor
  (``GOTCHAS.journal.md#2026-06-08`` — the 02 §1 example's form).
- Every LATER entry sharing that date, and any entry whose heading has no
  parseable date, gets ``GOTCHAS.journal.md#sha256:<12hex>`` of its
  normalized entry text (the shared normalization fn).

Why first-of-date rather than unique-date: the journal is append-only, so
"first entry of a date" is stable under future appends — a unique-date rule
would silently re-anchor an already-imported entry the day a second entry
lands on its date, resurrecting it as a duplicate. Order within the file is
part of the append-only contract; hand-reordering the journal voids the
date anchors (the sha fallback and the dedupe index still hold the line).

Type-inference heuristic (documented, biased to under-classify as the
journal is mostly knowledge; triage re-classifies freely — 02 §2):

- ``behavior`` iff the title OPENS with an imperative directive —
  ``Never`` / ``Don't`` / ``Do not`` / ``Avoid`` (kind: anti-pattern) or
  ``Always`` / ``Must`` (kind: surface-rule). A sentence-initial imperative
  is a rule addressed to the operator.
- Mid-sentence negations/modals stay ``knowledge`` ("entities don't hit the
  registry immediately", "the key must contain a hyphen" are facts).
- behavior: Trigger = the title (it names the situation), Instruction = the
  Fix field (title again when Fix is absent). Deriving a sharper trigger
  from a knowledge fact is inference and gets human eyes at triage
  (01 §3.2, gen-1 review finding).

Already-canon flagging (08 §1 pin: ``type: knowledge`` AND present in
canon; behavioral entries NEVER bulk-flagged). Canon-presence heuristic,
honestly stated: the entry's title, normalized to lowercase alphanumeric
words, must appear as a CONTIGUOUS substring of the normalized text of the
sibling ``GOTCHAS.md``, and must be >= 24 normalized chars long. Shorter or
looser resemblance is borderline and stays UNFLAGGED — a wrong flag is one
mis-grouped card the human de-selects; a missed flag is one extra card
(08 §4: bias to under-flag). The flag lives in the PROPOSAL SIBLING
(``already_canon`` + reason + destination suggestion, record_sha stamped by
the CLI) — the record itself stays clean (02 §1).

Every composed record body is secret-scanned before write; a hit skips
that entry (reported), never aborts the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import scan as scan_mod
from .import_common import ImporterError, ImportReport, commit_import, existing_origins
from .ledger_ops import bucket_dir_for_scope, create_record, stamp_proposal, write_proposal
from .normalize import sha_anchor
from .records import Record

__all__ = ["JournalEntry", "import_backlog", "parse_journal"]

JOURNAL_BASENAME = "GOTCHAS.journal.md"
CANON_BASENAME = "GOTCHAS.md"

_DATED_TITLE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[—–-]\s*(.*)$")
_FIELD_RE = re.compile(r"^- \*\*(.+?):\*\*\s*(.*)$")
_NEG_DIRECTIVE_RE = re.compile(r"^(?:never|don'?t|do not|avoid)\b", re.IGNORECASE)
_POS_DIRECTIVE_RE = re.compile(r"^(?:always|must)\b", re.IGNORECASE)

#: Minimum normalized-title length for a canon match to count; anything
#: shorter is borderline and stays unflagged (bias to under-flag, 08 §4).
MIN_CANON_MATCH_LEN = 24


@dataclass(frozen=True)
class JournalEntry:
    """One journal entry: heading date (None when unparseable), title text,
    the full entry block (heading included), and the bullet fields."""

    date: str | None
    title: str
    text: str
    fields: dict[str, str] = field(default_factory=dict)


def parse_journal(text: str) -> list[JournalEntry]:
    """Split the journal into entries at ``### `` headings. Preamble before
    the first heading is not an entry. Trailing blank lines are trimmed from
    each block so inter-entry reflow never changes an entry's text."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("### ")]
    entries: list[JournalEntry] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        while block and block[-1].strip() == "":
            block.pop()
        heading = block[0][len("### ") :].strip()
        m = _DATED_TITLE_RE.match(heading)
        date, title = (m.group(1), m.group(2).strip()) if m else (None, heading)
        fields: dict[str, str] = {}
        for line in block[1:]:
            fm = _FIELD_RE.match(line.strip())
            if fm:
                fields.setdefault(fm.group(1).strip(), fm.group(2).strip())
        entries.append(
            JournalEntry(date=date, title=title, text="\n".join(block), fields=fields)
        )
    return entries


def _entry_origins(entries: list[JournalEntry]) -> list[str]:
    """Anchor per entry: date for the first entry of each date, sha of the
    normalized entry text otherwise (dupes and dateless entries)."""
    seen_dates: set[str] = set()
    origins: list[str] = []
    for entry in entries:
        if entry.date is not None and entry.date not in seen_dates:
            seen_dates.add(entry.date)
            origins.append(f"{JOURNAL_BASENAME}#{entry.date}")
        else:
            origins.append(f"{JOURNAL_BASENAME}#{sha_anchor(entry.text)}")
    return origins


def _infer_type(title: str) -> tuple[str, str | None]:
    """(type, kind) from the title — see the module docstring's heuristic."""
    if _NEG_DIRECTIVE_RE.match(title):
        return "behavior", "anti-pattern"
    if _POS_DIRECTIVE_RE.match(title):
        return "behavior", "surface-rule"
    return "knowledge", None


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _canon_match(title: str, canon_norm: str | None) -> bool:
    if canon_norm is None:
        return False
    title_norm = _normalize_for_match(title)
    if len(title_norm) < MIN_CANON_MATCH_LEN:
        return False  # borderline: too short to trust — stays unflagged
    return title_norm in canon_norm


def _compose_record(entry: JournalEntry, scope: str) -> Record:
    rtype, kind = _infer_type(entry.title)
    context_lines = [
        line for line in entry.text.split("\n")[1:] if line.strip() != ""
    ]
    context = "\n".join(context_lines) if context_lines else None
    if rtype == "behavior":
        return Record.create(
            type="behavior",
            scope=scope,
            source="backlog",
            kind=kind,
            trigger=entry.title,
            instruction=entry.fields.get("Fix") or entry.title,
        )
    return Record.create(
        type="knowledge",
        scope=scope,
        source="backlog",
        fact=entry.title,
        context=context,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def import_backlog(
    home: Path, skill_name: str, journal_path: Path | None = None
) -> ImportReport:
    """One-shot ETL of the skill's GOTCHAS journal into its pending bucket.

    Resolves ``references/GOTCHAS.journal.md`` from the skill bucket's
    plugin; *journal_path* overrides for tests. The canon file used for
    already-canon flagging is the journal's sibling ``GOTCHAS.md``.
    Idempotent: origins already present anywhere in the ledger are skipped.
    """
    scope = f"skill:{skill_name}"
    bucket_dir_for_scope(home, scope)  # validates the skill via the registry
    if journal_path is None:
        # The journal lives in the HOST skill dir now (doc 13 §2): the
        # ledger bucket holds records only, never source material.
        from .hosts import HostsError, load_hosts, skill_dir_for

        try:
            skill_dir = skill_dir_for(load_hosts(home), skill_name)
        except HostsError as exc:
            raise ImporterError(str(exc)) from exc
        journal_path = skill_dir / "references" / JOURNAL_BASENAME
    journal_path = Path(journal_path)
    if not journal_path.is_file():
        raise ImporterError(f"no journal at {journal_path}")

    canon_path = journal_path.parent / CANON_BASENAME
    canon_norm = (
        _normalize_for_match(canon_path.read_text(encoding="utf-8"))
        if canon_path.is_file()
        else None
    )

    entries = parse_journal(journal_path.read_text(encoding="utf-8"))
    origins = _entry_origins(entries)
    known = existing_origins(home)
    report = ImportReport(source="backlog")

    for entry, origin in zip(entries, origins):
        if origin in known:
            report.skipped_dup.append(origin)
            continue
        known.add(origin)  # run-local: a pathological double entry imports once

        record = _compose_record(entry, scope)
        hits = scan_mod.scan(record.to_text())
        if hits:
            report.scan_refused.append(origin)
            continue

        evidence: dict = {"origin": origin}
        if entry.date is not None and not origin.endswith(entry.date):
            evidence["note"] = f"journal entry dated {entry.date}"
        record.append_evidence(evidence)
        report.touched.append(create_record(home, record))
        report.created.append(record.id)
        report.origins[record.id] = origin

        if record.type == "knowledge" and _canon_match(entry.title, canon_norm):
            # Flag lives in the proposal sibling; the record stays clean.
            proposal_path = write_proposal(
                home,
                record.id,
                {
                    "destination": "reference",
                    "alternates": [],
                    "rationale": (
                        "backlog import: knowledge entry whose substance already "
                        f"lives in curated {CANON_BASENAME} — bulk-acknowledge "
                        "candidate (graduation, superseded_by: canon)"
                    ),
                    "already_canon": True,
                    "already_canon_reason": (
                        f"normalized title matches {CANON_BASENAME} content"
                    ),
                    "model": "import-backlog/pinned-criterion",
                    "analyzed_at": _now_iso(),
                },
            )
            stamp_proposal(home, record.id)  # CLI stamps record_sha (08 §7.1)
            report.touched.append(proposal_path)
            report.flagged_canon.append(record.id)
        else:
            # Card-set data for exit (b): behavior-type + unflagged knowledge.
            report.behavioral_minority.append(record.id)

    commit_import(home, report)  # H-5: one ledger commit per run
    return report
