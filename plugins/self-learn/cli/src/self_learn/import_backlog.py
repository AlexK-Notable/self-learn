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
from pathlib import Path

from . import gitops
from . import scan as scan_mod
from .primitives import chrono
from .import_common import ImporterError, ImportReport, commit_import, existing_origins
from .ledger_ops import (
    ROSTER_UNAVAILABLE,
    bucket_dir_for_scope,
    create_record,
    stamp_proposal,
    write_proposal,
)
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
    return chrono.now_iso()


#: Every record this importer creates is freshly minted (`Record.create`,
#: above) and lands in `pending/` with `status: pending` in its frontmatter
#: (`records.py` stamps this unconditionally) — a genuine, always-present
#: RECORD-sourced quote, never a fabricated one, for the trace fields below
#: that require containment but have nothing real to point at (the gate
#: they document was never reached).
_RECORD_QUOTE = "status: pending"


def _graduate_gates(canon_evidence: str) -> dict:
    """A GRADUATE decision trace (u-schema-decision-trace §3, u-table's
    Table-1 G3 row) for this importer's pinned canon-match heuristic —
    S-26 (`ledger_ops.TRACE_REQUIRED`) made the trace mandatory on every
    proposal, and this bulk-acknowledge write is a real producer, not a
    test fixture, so it must state a trace that is both schema-valid and
    honest about what actually happened: ``g0.canon`` fires on the
    heuristic string match (never on Table-1 gate-by-gate reasoning), and
    every downstream gate answers the "not reached" skeleton — t1-tn all
    "no"/null, t4 present (required whenever t2 and t3 both answer "no"
    and tn does not answer "yes") and itself all "no", which is exactly
    the shape `gates.load_class` needs to fall through to `DEMAND` — so
    `_validate_derivation`'s destination check (`_RENDER_DESTINATIONS`)
    lands on "reference", matching what this importer has always written.
    `t3.roster_sha` is `ROSTER_UNAVAILABLE`: no roster was ever composed
    here, and claiming a fabricated sha would be exactly the dishonesty
    X3 exists to catch — the required 'evidence-gap' flag (set by the
    caller) admits the degradation instead of hiding it."""
    return {
        "g0": {
            "reject": {"answer": "no"},
            "defer": {"answer": "no"},
            "canon": {
                "answer": "yes",
                "evidence": canon_evidence,
                "target": CANON_BASENAME,
            },
        },
        "t1": {
            "attempted": False,
            "field_shaped": {"answer": "no", "evidence": _RECORD_QUOTE},
            "separable": {"answer": None},
            "cost_bearing": {"answer": None},
        },
        "t2": {"answer": "no", "evidence": _RECORD_QUOTE, "match_path": None},
        "t3": {
            "answer": "no",
            "owner": None,
            "scan_terms": ["backlog-import", "no-roster-composed"],
            "roster_sha": ROSTER_UNAVAILABLE,
        },
        "t3a": None,
        "tn": {"answer": "no", "terms": [], "members": [], "proposed_name": None},
        "t4": {
            "depth_behind_rule": {"answer": "no", "evidence": None},
            "conduct_mode": {"answer": "no", "evidence": None},
            "fs": {"verdict": "INDETERMINATE", "evidence": None},
        },
        "e1": {"sightings": 1, "post_demand_recurrence": False},
        "outcome": "GRADUATE",
    }


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

    # ONE lock across [first write → commit] (audit 2026-07-16 round 7 —
    # the invariant). The loop's writes are local file ops and its commit
    # is `commit_import`, which takes the lock again re-entrantly; the
    # push it does sits outside. Refusing here (a busy neighbour) costs
    # nothing: the import is idempotent by origin and simply re-runs.
    with gitops.commit_lock(home):
        _import_entries(home, entries, origins, known, scope, canon_norm, report)
        report.committed = commit_import(home, report)  # H-5: one commit/run
    return report


def _import_entries(
    home: Path,
    entries: list,
    origins: list[str],
    known: set[str],
    scope: str,
    canon_norm: str | None,
    report: ImportReport,
) -> None:
    """The write loop. **The caller holds the ledger lock.**"""
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
                    # U-composer's S-26 flip (ledger_ops.TRACE_REQUIRED) made
                    # the decision trace mandatory on EVERY proposal, this
                    # importer's bulk-acknowledge write included — a gap the
                    # composer spec didn't anticipate (its own producer is
                    # the worker/analyst, not this heuristic importer).
                    # `_graduate_gates` states plainly what actually
                    # happened: G3 (g0.canon) fired on a pinned string-match
                    # heuristic, never on Table-1 gate-by-gate reasoning —
                    # every downstream gate is the honest "not reached"
                    # skeleton, and t3's roster_sha is ROSTER_UNAVAILABLE
                    # (X3: no roster was ever composed here) with the
                    # required 'evidence-gap' flag admitting it, rather than
                    # a fabricated sha claiming a roster that was never
                    # loaded.
                    "gates": _graduate_gates(
                        f"normalized title matches {CANON_BASENAME} content"
                    ),
                    "flags": ["evidence-gap"],
                    "recommendation": "graduate",
                },
            )
            stamp_proposal(home, record.id)  # CLI stamps record_sha (08 §7.1)
            report.touched.append(proposal_path)
            report.flagged_canon.append(record.id)
        else:
            # Card-set data for exit (b): behavior-type + unflagged knowledge.
            report.behavioral_minority.append(record.id)

    return None
