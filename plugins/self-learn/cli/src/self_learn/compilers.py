"""Compilers (T6): managed sections (SKILL.md / CLAUDE.md) + references append.

Pure compilation: (records routed to a target) -> target-file content. No git,
no verb wiring (T7 owns those). Contracts implemented here:

Managed sections (02 §4, 01 §3.5, 08 §1 bootstrap pin)
------------------------------------------------------
- The compiler owns EXACTLY the region between :data:`BEGIN_MARKER` and
  :data:`END_MARKER`; text outside the markers is preserved byte-exact.
- The whole section is regenerated idempotently from the given records —
  the routed-to-this-target set of resolved/ records. Defensively, only
  ``status: routed`` records with ``superseded_by: null`` compile in:
  graduation (``superseded_by: canon``) and corrective supersession drop an
  entry by contract (02 §4), so the filter lives in the compiler.
- Entry format is trigger-first, one tight line each, id always present:
  behavior  -> ``- **When <trigger>:** <instruction> *(lrn-xxxxxxxx)*``
  knowledge -> ``- <fact one-liner> *(lrn-xxxxxxxx)*``
  One-liners are mechanical tightenings of the record's body sections:
  first non-empty line, cut at the first ``". "`` sentence boundary. The
  trigger's trailing period is trimmed (a colon follows); the instruction
  keeps its sentence period. Trigger and instruction have their first
  letter lowercased when the second letter is lowercase (reads as prose
  after "When …:" / the colon; acronyms and code spans are left alone).
- Deterministic ordering (structural decision, recorded here): entries sort
  by ``(routing.routed_at, id)`` — routing order, id as tiebreak — so
  reruns are byte-stable.
- Bootstrap (08 §1 pin): a target with no markers gets the marker pair
  appended at EOF, preceded by exactly one blank line (an empty target gets
  the bare section). This necessarily normalizes the file's trailing
  newlines; byte-exact preservation applies to regeneration, where the
  markers already delimit ownership.
- Overflow (02 §4, mechanical): cap = 10 entries or ~150 words inside the
  section (per-target override via ``max_entries`` / ``max_words``). At the
  cap the compiler STILL applies the new entry and returns a flagged
  result (:attr:`SectionResult.over_cap` + :attr:`SectionResult.cap_reason`)
  — callers surface it; nothing is dropped silently.
- A half-markered or multi-markered target is corrupt: :class:`CompileError`,
  never a guess.
- A missing managed target file is refused (:class:`CompileError`) — the
  compiler never creates SKILL.md/CLAUDE.md files, only sections inside
  existing ones.

References compiler (01 §3.5, 08 §1 References-compiler pin)
------------------------------------------------------------
- Append-style, ha-note-like. Default target: the skill's
  ``references/LEARNINGS.md``, created (with a small header) if absent.
- An explicitly named dest must be an EXISTING references file — a
  non-existent named target is refused (never create arbitrary files) —
  and ``GOTCHAS.journal.md`` is refused by name (ha-note's surface, O-7).
- Entries are dated blocks carrying the record id + the full section text
  (references are the bulk/progressive-disclosure surface; no tightening).
- Idempotent per record: the file is scanned for the record id and an
  already-present id makes the append a no-op.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from .records import Record

__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_WORDS",
    "DEFAULT_REFERENCE_BASENAME",
    "FORBIDDEN_REFERENCE_BASENAME",
    "CompileError",
    "SectionResult",
    "ReferenceResult",
    "entry_line",
    "compile_managed_text",
    "compile_managed_file",
    "compile_reference",
]

#: Marker pair, exactly per 02 §4.
BEGIN_MARKER = "<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->"
END_MARKER = "<!-- self-learn:end -->"

#: Overflow caps (02 §4); per-target overrides via function parameters.
DEFAULT_MAX_ENTRIES = 10
DEFAULT_MAX_WORDS = 150

#: References compiler pins (08 §1).
DEFAULT_REFERENCE_BASENAME = "LEARNINGS.md"
FORBIDDEN_REFERENCE_BASENAME = "GOTCHAS.journal.md"

_LEARNINGS_HEADER = (
    "# Learnings\n"
    "\n"
    "Reference-routed lessons, appended by self-learn (newest last). Each\n"
    "entry carries its record id for provenance; regenerate nothing here —\n"
    "this file is append-only.\n"
)

_HEADING_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


class CompileError(Exception):
    """A compile target violates the managed-section / references contract."""


# --------------------------------------------------------------------- results


@dataclass(frozen=True)
class SectionResult:
    """Outcome of one managed-section compilation."""

    text: str  # the full new target-file content
    changed: bool  # text differs from the input target
    bootstrapped: bool  # markers were absent and got appended at EOF
    entry_count: int
    word_count: int  # words inside the section (entry lines only)
    over_cap: bool  # section exceeds the cap — surface a graduation card
    cap_reason: str | None  # "entries" | "words" | None


@dataclass(frozen=True)
class ReferenceResult:
    """Outcome of one references append."""

    path: Path
    applied: bool  # False = record id already present (no-op)
    created: bool  # LEARNINGS.md was created fresh
    entry: str | None  # the appended block (None on no-op)


# ---------------------------------------------------------------- record view


def _body_sections(record: Record) -> dict[str, str]:
    """Map section heading -> section text from the record body.

    Section *extraction* is new here (records.py validates headings but does
    not expose their text); the parsing of the record itself stays T2's.
    """
    body = record.body
    sections: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(body))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[m.group(1)] = body[start:end].strip()
    return sections


def _one_liner(text: str) -> str:
    """Mechanical tightening: first non-empty line, cut at the first
    ``". "`` sentence boundary (period kept)."""
    line = next((ln.strip() for ln in text.strip().splitlines() if ln.strip()), "")
    m = re.search(r"\. ", line)
    if m:
        line = line[: m.start() + 1]
    return line


def _lower_first(text: str) -> str:
    """Lowercase the leading letter only when the second char is lowercase —
    'About to…' reads on after "When", while 'HA caches…' and code spans
    keep their casing."""
    if len(text) >= 2 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def entry_line(record: Record) -> str:
    """One tight managed-section line for a record (02 §4, trigger-first)."""
    sections = _body_sections(record)
    if record.type == "behavior":
        trigger = _one_liner(sections.get("Trigger", ""))
        trigger = trigger[:-1].rstrip() if trigger.endswith(".") else trigger
        instruction = _lower_first(_one_liner(sections.get("Instruction", "")))
        return f"- **When {_lower_first(trigger)}:** {instruction} *({record.id})*"
    fact = _one_liner(sections.get("Fact", ""))
    return f"- {fact} *({record.id})*"


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _eligible(records: Iterable[Record]) -> list[Record]:
    """Filter to compiling records and apply the pinned deterministic order:
    (routing.routed_at, id)."""
    kept = [r for r in records if r.status == "routed" and r.superseded_by is None]
    kept.sort(key=lambda r: (_iso((r.routing or {}).get("routed_at") or ""), r.id))
    return kept


# ------------------------------------------------------- managed-section core


def compile_managed_text(
    target_text: str,
    records: Sequence[Record],
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_words: int = DEFAULT_MAX_WORDS,
) -> SectionResult:
    """Regenerate the managed section inside ``target_text`` from ``records``.

    Returns the full new file content plus cap/bootstrap flags; performs no
    I/O. See the module docstring for the contract.
    """
    entries = [entry_line(r) for r in _eligible(records)]
    section = "\n".join([BEGIN_MARKER, *entries, END_MARKER])

    word_count = sum(len(e.split()) for e in entries)
    if len(entries) > max_entries:
        over_cap, cap_reason = True, "entries"
    elif word_count > max_words:
        over_cap, cap_reason = True, "words"
    else:
        over_cap, cap_reason = False, None

    begins = target_text.count(BEGIN_MARKER)
    ends = target_text.count(END_MARKER)

    if begins == 0 and ends == 0:
        # Bootstrap (08 §1 pin): marker pair at EOF, exactly one blank line
        # before it; an empty target gets the bare section.
        stripped = target_text.rstrip("\n")
        new_text = f"{section}\n" if stripped == "" else f"{stripped}\n\n{section}\n"
        bootstrapped = True
    elif begins == 1 and ends == 1:
        begin_at = target_text.index(BEGIN_MARKER)
        end_at = target_text.index(END_MARKER)
        if end_at < begin_at:
            raise CompileError(
                "broken managed-section markers: end marker precedes begin marker"
            )
        pre = target_text[:begin_at]
        post = target_text[end_at + len(END_MARKER) :]
        new_text = pre + section + post
        bootstrapped = False
    else:
        raise CompileError(
            "broken managed-section markers: expected exactly one begin/end pair, "
            f"found {begins} begin / {ends} end"
        )

    return SectionResult(
        text=new_text,
        changed=new_text != target_text,
        bootstrapped=bootstrapped,
        entry_count=len(entries),
        word_count=word_count,
        over_cap=over_cap,
        cap_reason=cap_reason,
    )


def compile_managed_file(
    path: Path | str,
    records: Sequence[Record],
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_words: int = DEFAULT_MAX_WORDS,
) -> SectionResult:
    """File wrapper for :func:`compile_managed_text`: read the target,
    regenerate its section, write back only when changed.

    A missing target is refused — the compiler owns a section, never the
    file's existence.
    """
    path = Path(path)
    if not path.is_file():
        raise CompileError(
            f"managed target does not exist: {path} — the compiler never creates "
            "target files, only the section inside an existing one"
        )
    result = compile_managed_text(
        path.read_text(encoding="utf-8"),
        records,
        max_entries=max_entries,
        max_words=max_words,
    )
    if result.changed:
        path.write_text(result.text, encoding="utf-8")
    return result


# ----------------------------------------------------------------- references


def _reference_block(record: Record, *, on: date | None = None) -> str:
    """A dated entry block: id + full trigger/fact + instruction/context."""
    routed_at = (record.routing or {}).get("routed_at")
    day = _iso(routed_at)[:10] if routed_at else (on or date.today()).isoformat()
    sections = _body_sections(record)
    lines = [f"## {day} — {record.id}", ""]
    if record.type == "behavior":
        lines.append(f"**Trigger:** {sections.get('Trigger', '').strip()}")
        lines.append("")
        lines.append(f"**Instruction:** {sections.get('Instruction', '').strip()}")
    else:
        lines.append(f"**Fact:** {sections.get('Fact', '').strip()}")
        context = sections.get("Context", "").strip()
        if context:
            lines.append("")
            lines.append(f"**Context:** {context}")
    return "\n".join(lines)


def compile_reference(
    references_dir: Path | str,
    record: Record,
    *,
    dest: str | None = None,
    on: date | None = None,
) -> ReferenceResult:
    """Append one record to a references file (08 §1 References-compiler pin).

    ``dest`` names an EXISTING references file (basename or path, resolved
    against ``references_dir``); omitted, the default ``LEARNINGS.md`` is
    used and created with a small header if absent. ``GOTCHAS.journal.md``
    is refused by name. Re-appending an already-present record id is a
    no-op (the file is scanned for the id).
    """
    references_dir = Path(references_dir)

    if dest is not None:
        dest_path = Path(dest)
        if not dest_path.is_absolute():
            dest_path = references_dir / dest_path
        if dest_path.name == FORBIDDEN_REFERENCE_BASENAME:
            raise CompileError(
                f"refusing {FORBIDDEN_REFERENCE_BASENAME}: that is ha-note's surface "
                "(O-7); route to LEARNINGS.md or another references file"
            )
        if not dest_path.is_file():
            raise CompileError(
                f"named references target does not exist: {dest_path} — an explicit "
                "--dest must name an existing references file (never created)"
            )
        path, created = dest_path, False
        text = path.read_text(encoding="utf-8")
    else:
        path = references_dir / DEFAULT_REFERENCE_BASENAME
        if path.is_file():
            created = False
            text = path.read_text(encoding="utf-8")
        else:
            created = True
            text = _LEARNINGS_HEADER
            references_dir.mkdir(parents=True, exist_ok=True)

    if record.id in text:
        # Idempotency scan: this record is already in the file.
        if created:  # never happens with a fresh header, but stay honest
            path.write_text(text, encoding="utf-8")
        return ReferenceResult(path=path, applied=False, created=created, entry=None)

    block = _reference_block(record, on=on)
    new_text = text.rstrip("\n") + "\n\n" + block + "\n"
    path.write_text(new_text, encoding="utf-8")
    return ReferenceResult(path=path, applied=True, created=created, entry=block)
