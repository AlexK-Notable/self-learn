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
- Counting, no threshold (U-cap): the compiler counts entries and words
  inside the section (:attr:`SectionResult.entry_count` /
  :attr:`SectionResult.word_count`) and applies every entry unconditionally
  — nothing here is capped, so nothing is ever exceeded. The counts feed
  the report-only context budget (``report --json .context_budget``,
  U-cap); nothing is ever dropped, refused, or flagged by the compiler
  itself.
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

Pointer emission (U-pointer, the ALWAYS-surface write)
--------------------------------------------------------
- A `reference` route's canon lands in a references file nothing loaded
  reads (02 §4's managed sections cover skill-md/claude-md, never
  references). :func:`apply_pointer` closes that: it writes a small,
  dedicated, cap-exempt block -- its own marker pair, distinct from
  :data:`BEGIN_MARKER`/:data:`END_MARKER` -- into the surface a session
  DOES load (SKILL.md / CLAUDE.md), naming the references file with a
  path token.
- The contract is behavioural, not textual: :func:`surface_names_target`
  (moved here from `selfcheck.py`, the shipped u-reach detector) is BOTH
  the idempotence check (a surface that already names the target is left
  untouched -- a hand-written mention counts) and the mandatory post-
  condition (`apply_pointer` re-reads the file it just wrote and raises
  :class:`CompileError` if the detector still cannot find the target;
  the pre-write text is restored first, so a failed write never wedges
  the surface against a later route or repair).
- Structurally cap-exempt: the pointer line lives outside
  :data:`BEGIN_MARKER`/:data:`END_MARKER` entirely, so it never enters
  :func:`compile_managed_text`'s entry/word counts and a managed-section
  regeneration on the SAME surface leaves it untouched.
- Insert-only: a new line is appended as the LAST line inside the
  pointer block (reference targets are append-only), never sorted,
  never re-derived from scratch on every call the way the managed
  section is.

Paths frontmatter (U-pathed, `paths:` emission for rules targets)
-------------------------------------------------------------------
- The ONE normative register for what a rules target's `paths:` key should
  say lives here, not at any call site: :func:`expected_paths` — `U(T)`,
  the spec's §2 union — derives ENTIRELY from the routed records
  (``_eligible`` filtered, same as the managed section), never from a
  value threaded in by a caller. Two call sites (`recompile`'s
  `_resolve_target`, retirement's own resolve) deliberately withhold a
  `rules_paths` value for correct, stated reasons — an emitter keyed on
  that value would silently strip pathed frontmatter back to
  always-loaded on the very first repair run.
- The compiler owns EXACTLY the `paths:` key of the leading
  ``---``/``---`` (or ``...``) frontmatter block — never the rest of it.
  Foreign keys, their order, and comments round-trip byte-for-byte via
  ruamel (the same `typ="rt"` discipline `records.py` already uses for
  record frontmatter). A block reduced to comments-and-nothing-else is
  KEPT, never collapsed to ruamel's bare `{}` empty-mapping form; a block
  reduced to nothing at all (no keys, no comments) is removed, plus one
  immediately following blank line.
- :func:`apply_paths_frontmatter` writes only when
  :func:`paths_frontmatter_drift` — the one *agreement* predicate, defined
  on the RAW loaded YAML value, never through the lossy
  :func:`read_paths_frontmatter` reader — says the file disagrees.
- A missing target, an unterminated leading block, or a leading block that
  does not load as a YAML mapping all refuse via :class:`CompileError`
  (already caught by the host-phase drift-warning path, same as a
  half-markered managed section).
"""

from __future__ import annotations

import io
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .records import Record

__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "DEFAULT_REFERENCE_BASENAME",
    "FORBIDDEN_REFERENCE_BASENAME",
    "POINTER_BEGIN_MARKER",
    "POINTER_END_MARKER",
    "CompileError",
    "SectionResult",
    "ReferenceResult",
    "PathsResult",
    "PointerResult",
    "entry_line",
    "compile_managed_text",
    "compile_managed_file",
    "compile_reference",
    "reference_target_path",
    "retire_reference",
    "expected_paths",
    "read_paths_frontmatter",
    "has_paths_key",
    "paths_frontmatter_drift",
    "apply_paths_frontmatter",
    "surface_names_target",
    "pointer_token",
    "pointer_line",
    "compile_pointer_text",
    "apply_pointer",
]

#: Marker pair, exactly per 02 §4.
BEGIN_MARKER = "<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->"
END_MARKER = "<!-- self-learn:end -->"

#: Pointer-block marker pair (U-pointer §3.1) -- distinct from
#: BEGIN_MARKER/END_MARKER above so a surface can carry a managed section
#: AND a pointer block without either arithmetic touching the other.
POINTER_BEGIN_MARKER = (
    "<!-- self-learn:pointers:begin (do not hand-edit inside; managed by self-learn) -->"
)
POINTER_END_MARKER = "<!-- self-learn:pointers:end -->"

#: References compiler pins (08 §1).
DEFAULT_REFERENCE_BASENAME = "LEARNINGS.md"
FORBIDDEN_REFERENCE_BASENAME = "GOTCHAS.journal.md"

_LEARNINGS_HEADER = (
    "# Learnings\n"
    "\n"
    "Reference-routed lessons, appended and retired by self-learn (newest\n"
    "last). Each entry carries its record id for provenance; regenerate\n"
    "nothing here — entries are added or removed only by self-learn's own\n"
    "verbs (U-verbs S-54), never hand-edited in place.\n"
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


@dataclass(frozen=True)
class ReferenceResult:
    """Outcome of one references append."""

    path: Path
    applied: bool  # False = record id already present (no-op)
    created: bool  # LEARNINGS.md was created fresh
    entry: str | None  # the appended block (None on no-op)
    #: U-pointer §3.6: True iff this route ALSO wrote a pointer block into
    #: the ALWAYS-loaded surface (SKILL.md/CLAUDE.md). Defaulted so the two
    #: existing construction sites below never change; read by the commit
    #: gate (verbs.py's `_host_phase`) so a no-op reference append with a
    #: freshly-written pointer still commits.
    pointer_changed: bool = False


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
    """Mechanical tightening: the whole first non-empty LINE. No sentence
    cut (audit 2026-07-14): doctrine §6's Instruction carries the what AND
    the why in one or two sentences on a single line, and cutting at the
    first period silently dropped the why; the §4 word cap polices bloat."""
    return next((ln.strip() for ln in text.strip().splitlines() if ln.strip()), "")


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
) -> SectionResult:
    """Regenerate the managed section inside ``target_text`` from ``records``.

    Returns the full new file content plus entry/word counts and the
    bootstrap flag; performs no I/O. See the module docstring for the
    contract.
    """
    entries = [entry_line(r) for r in _eligible(records)]
    section = "\n".join([BEGIN_MARKER, *entries, END_MARKER])

    word_count = sum(len(e.split()) for e in entries)

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
    )


def compile_managed_file(
    path: Path | str,
    records: Sequence[Record],
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
    )
    if result.changed:
        path.write_text(result.text, encoding="utf-8")
    return result


# ----------------------------------------------------- paths frontmatter (U-pathed)


@dataclass(frozen=True)
class PathsResult:
    """Outcome of one `paths:` frontmatter compile (§3.2)."""

    path: Path
    paths: tuple[str, ...]  # U(T); () = unpathed (no `paths:` key)
    changed: bool  # the frontmatter region was rewritten
    unpathed_by: tuple[str, ...]  # §2 derived value
    widened: bool  # §2 derived value
    drift: str | None  # the disagreement this rewrite replaced
    notes: tuple[str, ...]  # human-readable, for the verb warnings channel


#: Sentinel distinguishing "no `paths:` key present" from any other raw
#: loaded value (including a legitimate ``None``/``null``) — §2's
#: agreement predicate needs this distinction, `dict.get` alone conflates
#: "absent" with "present and null".
_MISSING = object()


def _paths_yaml() -> YAML:
    """Round-trip YAML for the rules-file frontmatter block — the SAME
    pinned config `records.py`'s own `_make_yaml()` uses (`typ="rt"`,
    preserve_quotes, width=4096, `indent(mapping=2, sequence=4, offset=2)`)
    so both frontmatter surfaces this codebase owns emit identically."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _dump_mapping(mapping: object) -> str:
    buf = io.StringIO()
    _paths_yaml().dump(mapping, buf)
    return buf.getvalue()


def _standalone_comments(text: str) -> list[str]:
    """Whole-line YAML comments, verbatim (indentation included), in source
    order. An INLINE trailer (``- a/** # why``) is deliberately not one:
    it annotates the item it rides on, so it lives and dies with it.

    This is a LINE SCAN, not a YAML parse, and the boundary is worth
    naming: a line beginning with ``#`` *inside a block scalar* is data,
    not a comment, and this reads it as one. Reaching that needs a
    hand-written ``paths: |`` block scalar — already malformed for this
    compiler, which reads a non-sequence ``paths:`` as ``()`` — and the
    residue is cosmetic (the key was being deleted anyway, nothing is
    lost, and the result still parses). A YAML-aware scan would cost a
    second round-trip to fix a shape the compiler already rejects."""
    return [ln for ln in text.splitlines() if ln.strip().startswith("#")]


def _readd_dropped_comments(inner: str, dumped: str) -> str:
    """Re-emit standalone comments that the round-trip discarded (F5).

    §3.2 promises the compiler owns ``paths:`` and nothing else in the
    block — but a comment's survival through ruamel depends on which node
    it happens to be keyed to. One ABOVE ``paths:`` attaches to the mapping
    and survives; one below the list, between its globs, or keyed to a glob
    that a NARROW pops attaches to the ``CommentedSeq`` and is discarded
    with it. That made the compiler destroy human text it does not own.

    Comparison is on the STRIPPED line and is multiplicity-aware, so a file
    that legitimately repeats a comment keeps both copies. On the stripping:
    it is defensive, not a fix for an observed bug — against the pinned
    ruamel config a surviving comment is re-indented in 0 of 48 measured
    configurations, so the hazard it guards (a dumper that re-indents,
    making a survivor look like a loss and get appended a second time) is
    NOT reproducible here. It is kept because it is strictly safer and
    cannot wrongly suppress a genuine loss — the Counter handles
    same-text-different-indent correctly either way. Recovered lines are
    appended at the end of the block: their anchor is gone, so there is no
    non-arbitrary place to restore them to, and preserving the text where a
    human can see it beats preserving nothing. Idempotent — on the next
    compile the recovered line is itself a standalone comment in the
    source, so it matches and is not appended twice."""
    have = Counter(ln.strip() for ln in _standalone_comments(dumped))
    missing: list[str] = []
    for line in _standalone_comments(inner):
        key = line.strip()
        if have[key]:
            have[key] -= 1
        else:
            missing.append(line)
    if not missing:
        return dumped
    return dumped + "".join(f"{ln}\n" for ln in missing)


def _find_leading_block(text: str) -> tuple[str, int] | None:
    """Locate the file's leading ``---``-delimited block. Returns
    ``(inner_text, end)`` where ``end`` is the character offset of the
    first byte after the closing delimiter line (so ``text[end:]`` is
    everything that follows the block) — ``None`` when the file's first
    line is not exactly ``---`` (no leading block at all).

    Raises :class:`CompileError` when the first line IS ``---`` but no
    ``---``/``...`` line ever closes it (A8's corrupt-block refusal) —
    the ONE place that detection lives; :func:`read_paths_frontmatter`
    (which must never raise) catches it and reads as absent.

    Fence lines are matched with ``rstrip()`` (trailing whitespace only —
    a fence with a trailing space is still a fence), never ``strip()``
    (leading whitespace must still DISQUALIFY a fence: an indented
    ``  ---`` is not a document delimiter). ``rstrip("\\r\\n")`` alone was
    the F2 bug: it left a trailing space on the OPENING line unstripped,
    so ``"--- \\n"`` was read as "no leading block", and the emitter then
    PREPENDED a fresh one on top of the real block — two ``paths:``
    blocks on disk, route reported success."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return None
    consumed = len(lines[0])
    inner_lines: list[str] = []
    for line in lines[1:]:
        consumed += len(line)
        if line.rstrip() in ("---", "..."):
            return "".join(inner_lines), consumed
        inner_lines.append(line)
    raise CompileError(
        "leading frontmatter block starts with '---' but has no "
        "terminating '---' or '...' line"
    )


def _eligible_globsets(records: Sequence[Record]) -> list[tuple[str, ...]]:
    return [
        tuple((r.routing or {}).get("rules_paths") or ()) for r in _eligible(records)
    ]


def expected_paths(records: Sequence[Record]) -> tuple[str, ...]:
    """``U(T)`` — the emitted paths (§2), pure. Applies the compiler's own
    :func:`_eligible` filter to ``records`` FIRST, so the frontmatter and
    the managed section are always computed from the same C(T) — never a
    second query a future caller could let drift apart.

    1. ``C(T)`` empty -> ``()``.
    2. ANY record in ``C(T)`` with no ``rules_paths`` -> ``()`` — the
       absorbing rule: union with "always" is "always" (§2.2).
    3. Otherwise -> the deduped, sorted union of every record's globs —
       deduped/sorted so re-runs are byte-stable (§2 rule 3).
    """
    globsets = _eligible_globsets(records)
    if not globsets:
        return ()
    if any(g == () for g in globsets):
        return ()
    return tuple(sorted({glob for g in globsets for glob in g}))


def _unpathed_by(records: Sequence[Record]) -> tuple[str, ...]:
    """``unpathed_by(T)`` (§2): sorted ids of records in ``C(T)`` with no
    ``rules_paths``, when ``C(T)`` is non-empty."""
    eligible = _eligible(records)
    if not eligible:
        return ()
    return tuple(
        sorted(r.id for r in eligible if not (r.routing or {}).get("rules_paths"))
    )


def _widened(records: Sequence[Record], u: tuple[str, ...]) -> bool:
    """``widened(T)`` (§2): ``U(T) != ()`` and some record's own globs
    differ from the emitted union — its rule now also fires on files it
    did not name.

    F4: compared as SETS, not as the raw stored tuples. §2's letter reads
    ``G(r) != U(T)`` as a tuple inequality, but a single record whose own
    proposal lists its globs unsorted (nobody hand-sorts a proposal) is
    NOT widened — its rule fires on exactly the files it named, in a
    different order. A tuple comparison called that "the union of 1
    routed lesson... fires on files it did not name" — both halves false,
    and it degrades the channel that carries A4's absorption alarm on a
    large share of first routes at S-23's primary tier. Order-only
    differences are unpinned by any criterion; §2's own gloss and §3.3's
    note text are set-based, which is what a human reads."""
    if not u:
        return False
    u_set = set(u)
    return any(set(g) != u_set for g in _eligible_globsets(records))


def _safe_load_leading_mapping(text: str) -> dict | None:
    """Lenient, never-raising: the leading block's ``typ="safe"``-loaded
    mapping, or ``None`` for absent / unterminated / unparseable / non-
    mapping — the shared basis for :func:`read_paths_frontmatter` and
    :func:`has_paths_key`, so the two never disagree about whether a
    block is even readable."""
    try:
        block = _find_leading_block(text)
    except CompileError:
        return None
    if block is None:
        return None
    inner, _end = block
    try:
        loaded = YAML(typ="safe").load(inner)
    except Exception:
        return None
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return None
    return loaded


def read_paths_frontmatter(text: str) -> tuple[str, ...]:
    """The file's ``paths:`` frontmatter as a tuple of strings — a reader,
    pure, and NEVER raises (drift detection is a separate, stricter path;
    this is the lenient, broadly-reusable primitive). ``()`` for: no
    leading frontmatter block, an unterminated/unparseable block, no
    ``paths:`` key, or a ``paths:`` value that is not a list of non-empty
    strings — a scalar and ``[]`` both collapse to ``()`` here, which is
    exactly why §2's agreement predicate (:func:`paths_frontmatter_drift`)
    is defined on the RAW value instead (M15's target), and exactly why a
    "does it carry a paths: key AT ALL" question must use
    :func:`has_paths_key` instead, never this reader (F1)."""
    loaded = _safe_load_leading_mapping(text)
    if loaded is None:
        return ()
    value = loaded.get("paths")
    if not isinstance(value, list) or not value:
        return ()
    if not all(isinstance(v, str) and v for v in value):
        return ()
    return tuple(value)


def has_paths_key(text: str) -> bool:
    """Lenient, never-raising: ``True`` iff the leading block loads as a
    YAML mapping containing a ``paths`` key AT ALL — regardless of
    whether its value is well-formed. This is the narrower question
    §3.4(2)'s chezmoi-MANAGED refusal needs, and it is NOT the same
    question :func:`read_paths_frontmatter` answers: the reader
    normalizes a scalar / ``[]`` / ``null`` / a list of non-strings all
    down to the SAME falsy ``()`` as "no key at all", but
    :func:`paths_frontmatter_drift` (the agreement predicate, defined on
    the RAW value) treats every one of those as disagreement — a rewrite
    the pre-pass WILL perform. A refusal keyed on the reader therefore
    misses exactly the values the pre-pass is about to touch (found live,
    F1): a target with ``paths: []`` slips past the MANAGED refusal, the
    pre-pass then writes it, and chezmoi's own drift check reads that
    write as pre-existing drift — an unrecoverable post-ledger abort,
    with the record already sitting in ``resolved/``."""
    loaded = _safe_load_leading_mapping(text)
    return loaded is not None and "paths" in loaded


def paths_frontmatter_drift(text: str, records: Sequence[Record]) -> str | None:
    """§2's *agreement* predicate: ``None`` when the file's RAW ``paths:``
    value already equals ``list(U(T))`` (a missing key counting as
    agreement iff ``U(T) == ()``); otherwise a one-line message naming
    what was found and what is expected. Compares the raw loaded value —
    never through :func:`read_paths_frontmatter`, whose normalization of a
    scalar / ``[]`` / absent key down to a uniform ``()`` is exactly what
    would call a stale scalar "clean" (M15).

    Unlike the reader, this DOES raise :class:`CompileError` on an
    unterminated or non-mapping leading block — propagated from
    :func:`_find_leading_block` / this function's own mapping check, and
    the one detection point :func:`apply_paths_frontmatter` relies on for
    A8's refusal."""
    expected = list(expected_paths(records))
    block = _find_leading_block(text)
    if block is None:
        raw: object = _MISSING
    else:
        inner, _end = block
        try:
            loaded = YAML(typ="safe").load(inner)
        except Exception as exc:
            raise CompileError(
                f"leading frontmatter block does not load as YAML: {exc}"
            ) from exc
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise CompileError(
                "leading frontmatter block does not load as a YAML mapping"
            )
        raw = loaded.get("paths", _MISSING)
    if raw is _MISSING:
        return None if not expected else f"no `paths:` key present; expected {expected!r}"
    if isinstance(raw, list) and not raw:
        # §2: an explicit `paths: []` is NEVER agreement, even when
        # `U(T) == ()` — only a MISSING key represents "unpathed"; the
        # compiler itself never writes an empty list (it deletes the key
        # instead), so a `[]` on disk is always a hand edit to normalize.
        return f"`paths:` is []; expected {expected!r}"
    if raw == expected:
        return None
    return f"`paths:` is {raw!r}; expected {expected!r}"


def _rewrite_paths_block(
    text: str, existing_block: tuple[str, int] | None, u: tuple[str, ...]
) -> str:
    """The write side of §3.2's ownership rule: rewrite the LOADED leading
    block in place (never prepend a fresh one — M20/A7), touching only the
    ``paths:`` key. ``existing_block`` is ``None`` only when there was no
    leading block at all (a brand-new one is created; ``u`` is guaranteed
    non-empty here, since an empty union with no pre-existing block is
    *agreement* — :func:`apply_paths_frontmatter` never reaches this
    function for that case)."""
    if existing_block is None:
        mapping = CommentedMap()
        mapping["paths"] = list(u)
        return f"---\n{_dump_mapping(mapping)}---\n{text}"

    inner, end = existing_block
    post = text[end:]
    mapping = _paths_yaml().load(inner)
    if mapping is None:
        mapping = CommentedMap()

    if u:
        # F3: update an EXISTING CommentedSeq in place (pop to shrink,
        # index-assign up to its old length, append past it) rather than
        # replacing it with a plain list. `mapping["paths"] = list(u)`
        # measurably drops comments attached to the sequence itself — a
        # comment below the last list item (whether or not a key
        # follows), or an inline comment on a list item — because the
        # comment lives on the CommentedSeq node this would discard, not
        # on the mapping. Measured against the pinned ruamel config: this
        # form preserves all three placements IN PLACE whenever the list
        # widens or stays the same size (21 of 21 configurations), where a
        # plain reassignment preserves none of them.
        #
        # It is not sufficient on its own for a NARROW: a comment keyed to
        # one of the popped items goes with it (4 of 8 measured
        # configurations). `_readd_dropped_comments` below is what closes
        # that — the text survives, appended to the block, since its anchor
        # no longer exists. In-place mutation is still what keeps the other
        # 4 exactly where the human put them, so both halves are load-bearing.
        old = mapping.get("paths")
        if isinstance(old, CommentedSeq):
            while len(old) > len(u):
                old.pop()
            for i, glob in enumerate(u):
                if i < len(old):
                    old[i] = glob
                else:
                    old.append(glob)
        else:
            mapping["paths"] = list(u)
        body = _readd_dropped_comments(inner, _dump_mapping(mapping))
        return f"---\n{body}---\n{post}"

    if "paths" in mapping:
        del mapping["paths"]
    if len(mapping) > 0:
        body = _readd_dropped_comments(inner, _dump_mapping(mapping))
        return f"---\n{body}---\n{post}"

    # No keys left. §3.2's removal rule is "no keys AND no comments left",
    # so the surviving comments are recovered from the SOURCE block, not
    # from ruamel's dump of the now-empty mapping.
    #
    # F5: the dump cannot be trusted here. What it retains depends on where
    # the comment sat — one ABOVE `paths:` attaches to the mapping and
    # survives the `del`, but one below the list or between its items
    # attaches to the CommentedSeq that `del` just discarded, so it is gone.
    # Trusting the dump therefore made the rule that exists to preserve
    # comments the rule that DELETED them: a block holding `paths:` plus a
    # comment below it was removed entirely, comment included. Reading the
    # source keeps every standalone comment line byte-for-byte, whatever
    # its placement, and makes ruamel's `{}` form (which §3.2 prohibits)
    # unreachable rather than string-surgeried away after the fact.
    #
    # Comment text that is NOT a standalone line — an inline trailer on
    # `paths:` or on one of its globs — is deliberately not recovered: it
    # annotates the key being deleted, so it leaves with it (§3.2).
    survivors = _standalone_comments(inner)
    if not survivors:
        if post.startswith("\n"):
            post = post[1:]
        return post
    return "---\n" + "".join(f"{ln}\n" for ln in survivors) + f"---\n{post}"


def apply_paths_frontmatter(path: Path | str, records: Sequence[Record]) -> PathsResult:
    """Read ``path``, write back ONLY when :func:`paths_frontmatter_drift`
    says the leading block disagrees with ``U(T)`` (§2), and report the
    §3.3 notes (absorption / widening / drift-repaired) either way — they
    are re-derived from ``records`` on every call, not gated on a write
    happening this specific time (there is no standing report yet; §7.3).

    Refusals (:class:`CompileError`, never a guess): a missing ``path``;
    an unterminated leading block; a leading block that does not load as
    a YAML mapping — both propagated from :func:`paths_frontmatter_drift`.
    """
    path = Path(path)
    if not path.is_file():
        raise CompileError(
            f"rules target does not exist: {path} — the frontmatter compiler "
            "never creates target files, only rewrites the leading block of "
            "an existing one"
        )
    text = path.read_text(encoding="utf-8")
    u = expected_paths(records)
    drift = paths_frontmatter_drift(text, records)
    unpathed = _unpathed_by(records)
    wide = _widened(records, u)
    eligible = _eligible(records)

    notes: list[str] = []
    if unpathed and any((r.routing or {}).get("rules_paths") for r in eligible):
        notes.append(
            f"{path}: rules file is UNPATHED (loads at launch) because "
            f"{', '.join(unpathed)} carry no rules_paths — the pathed "
            "lessons in this topic now cost full always-loaded attention; "
            "route a globless lesson to its own topic"
        )
    if wide:
        notes.append(
            f"{path}: paths: is the union of {len(eligible)} routed lessons "
            "— each lesson's rule now also fires on files it did not name"
        )

    if drift is None:
        return PathsResult(
            path=path, paths=u, changed=False, unpathed_by=unpathed,
            widened=wide, drift=None, notes=tuple(notes),
        )

    existing_block = _find_leading_block(text)
    if existing_block is not None:
        notes.append(
            f"{path}: rewrote the compiler-owned paths: frontmatter ({drift}) "
            "— it regenerates from the routed records' rules_paths; hand "
            "edits do not survive a route or a recompile"
        )

    new_text = _rewrite_paths_block(text, existing_block, u)
    changed = new_text != text
    if changed:
        path.write_text(new_text, encoding="utf-8")
    return PathsResult(
        path=path, paths=u, changed=changed, unpathed_by=unpathed,
        widened=wide, drift=drift, notes=tuple(notes),
    )


# ------------------------------------------------------------- pointer emission


@dataclass(frozen=True)
class PointerResult:
    """Outcome of one pointer-block apply (U-pointer §3.3)."""

    surface: Path
    target: Path
    token: str  # the token written, or the one already present
    changed: bool  # the surface file was rewritten
    created: bool  # the surface file did not exist and was created
    bootstrapped: bool  # the pointer block was absent and got appended


#: §2.1 step 2: a token is delimited by whitespace or by any of these
#: bracket/quote characters -- never consumed into the match.
_TOKEN_DELIMS = r"\s()\[\]<>\"'`"


def surface_names_target(surface: Path, target: Path) -> bool:
    """The reachability predicate (§2.1): does ``surface`` contain a path
    TOKEN that RESOLVES to ``target``? Pure text + path arithmetic, no
    globbing -- the whole file is searched, not just a managed section (the
    home-assistant ``SKILL.md`` this unit exists for has no managed
    section at all).

    Step 2 is LEFT-MAXIMAL and anchored on the basename: for every
    occurrence of ``target.name`` in the text, the token extends
    LEFTWARD ONLY over non-delimiter characters and ENDS at the basename --
    nothing to its right is ever consumed. This is normative, and the two
    readings differ: a both-directions-maximal tokenizer rejects
    ``see references/LEARNINGS.md.`` (a sentence-final period, the
    commonest hand-written pointer shape); the anchored reading here
    accepts it, and adds no false positives (``myLEARNINGS.md`` still
    yields a token that fails the resolve-and-compare below).

    Steps 3-4 are the half that matters: a bare basename match would pass
    on some OTHER same-named file. Each candidate token is expanduser'd;
    an absolute token is used as-is, else resolved against
    ``surface.parent`` (the token is read as the AUTHOR meant it -- a
    relative pointer written in the surface file, relative to that file);
    a match requires the resolved candidate to equal ``target.resolve()``
    exactly (criterion 8b: comparing against an UNRESOLVED target breaks
    the moment the registered skills root is reached through a symlink)."""
    if not surface.is_file():
        return False
    text = surface.read_text(encoding="utf-8")
    pattern = re.compile(f"[^{_TOKEN_DELIMS}]*" + re.escape(target.name))
    resolved_target = target.resolve()
    for match in pattern.finditer(text):
        token = Path(match.group(0)).expanduser()
        candidate = token if token.is_absolute() else surface.parent / token
        if candidate.resolve() == resolved_target:
            return True
    return False


def pointer_token(surface: Path, target: Path) -> str:
    """T-TOKEN (§3.2): the path token written into a pointer line.

    Relative against ``surface.parent`` whenever that stays lexically
    forward (no ``..``) -- the form the detector resolves against
    (`surface_names_target`), and the only form that survives the surface
    being committed, shared, and cloned onto another machine. A relative
    form that would escape upward falls back to a ``~``-relative token
    when the target is under ``$HOME`` (still no absolute personal-path
    leak), else the bare absolute path."""
    rel = os.path.relpath(target, surface.parent)
    if not rel.startswith(".."):
        return Path(rel).as_posix()
    try:
        return "~/" + Path(target).relative_to(Path.home()).as_posix()
    except ValueError:  # target is not under $HOME
        return str(target)


def pointer_line(token: str, label: str) -> str:
    """One pointer-block line (§3.1 grammar): ``- `<token>` -- <label>``.
    Backticked deliberately -- `` ` `` is in the detector's
    ``_TOKEN_DELIMS``, so it terminates the leftward token scan cleanly.
    The em dash and the label are free text and are never parsed back."""
    return f"- `{token}` — {label}"


_POINTER_HEADING = "## Reference material (self-learn)"
_POINTER_PREAMBLE = (
    f"{_POINTER_HEADING}\n"
    "\n"
    "Captured lessons that are NOT loaded into this context. Read the file whose\n"
    "subject matches what you are about to do, before you start.\n"
    "\n"
)

#: U-ancestry ANC8/§6.4 -- the verbatim disambiguating sentence, pinned
#: word for word (a builder may not reword it). All three live pointer
#: blocks are byte-identical today (Finding C-3), so a host with a
#: registered ancestor OR a registered descendant is the one
#: configuration where TWO of these blocks can load in one session, each
#: saying "this project" about a different project. The base is
#: deliberately NOT an absolute path (Q2): a CLAUDE.md is a tracked file
#: and one registered host has a public remote, so an absolute token
#: would commit a real home path into it. The pointer TOKEN itself is
#: unchanged -- this sentence lives in the surrounding prose only, never
#: in a `- \`token\` -- label` line, so `surface_names_target`/
#: `pointer_token`/every `test_pointer.py` contract keeps its meaning.
_POINTER_BASE_SENTENCE = (
    "paths are relative to the directory containing this file, not your "
    "working directory.\n"
)


def _pointer_preamble(*, names_base: bool) -> str:
    """The bootstrap preamble for a FRESH pointer block. `names_base`
    (ANC8) appends the verbatim disambiguating sentence when the host
    this block is being written into has a registered ancestor or a
    registered descendant -- the only configurations where two
    self-learn pointer blocks can load in one live session.

    Code gate r1 N8: the `names_base=True` branch is DERIVED from
    `_POINTER_PREAMBLE` rather than hand-copying its text a second time
    -- `_POINTER_PREAMBLE` ends in "...before you start.\\n\\n" (the body
    line, then the block's trailing blank line); stripping exactly the
    last character removes that trailing blank line's newline, leaving
    the body ending in a single "\\n", after which the base sentence and
    a fresh blank line are appended. A single source of truth for the
    fixed preamble text means the two branches can never drift apart."""
    if not names_base:
        return _POINTER_PREAMBLE
    return _POINTER_PREAMBLE[:-1] + _POINTER_BASE_SENTENCE + "\n"


def compile_pointer_text(
    surface_text: str, line: str, *, names_base: bool = False
) -> tuple[str, bool]:
    """Pure block arithmetic (no I/O), like :func:`compile_managed_text`:
    insert ``line`` into the pointer block, bootstrapping the block at EOF
    -- exactly one blank line before it, a trailing newline -- when the
    markers are absent (0/0). When present (1/1), ``line`` is inserted as
    the LAST line inside the block, immediately before
    :data:`POINTER_END_MARKER`, preserving whatever is already there
    untouched -- never re-derived from scratch. Anything else (or an end
    marker preceding a begin marker) raises :class:`CompileError` naming
    the counts, mirroring `compile_managed_text`'s own refusal exactly.

    Returns ``(new_text, bootstrapped)`` -- ``bootstrapped`` reports
    whether the block was ABSENT and had to be appended at EOF (the same
    thing :attr:`SectionResult.bootstrapped` reports). This is deliberately
    NOT a ``changed`` flag: this function is only ever called when the
    caller has already decided a write is owed, so ``changed`` would be a
    constant ``True`` and therefore worthless."""
    begins = surface_text.count(POINTER_BEGIN_MARKER)
    ends = surface_text.count(POINTER_END_MARKER)

    if begins == 0 and ends == 0:
        block = (
            f"{POINTER_BEGIN_MARKER}\n"
            f"{_pointer_preamble(names_base=names_base)}"
            f"{line}\n"
            f"{POINTER_END_MARKER}"
        )
        stripped = surface_text.rstrip("\n")
        new_text = f"{block}\n" if stripped == "" else f"{stripped}\n\n{block}\n"
        return new_text, True

    if begins == 1 and ends == 1:
        begin_at = surface_text.index(POINTER_BEGIN_MARKER)
        end_at = surface_text.index(POINTER_END_MARKER)
        if end_at < begin_at:
            raise CompileError(
                "broken pointer-block markers: end marker precedes begin marker"
            )
        pre = surface_text[:end_at]
        if not pre.endswith("\n"):
            pre += "\n"
        post = surface_text[end_at:]
        return pre + line + "\n" + post, False

    raise CompileError(
        "broken pointer-block markers: expected exactly one begin/end pair, "
        f"found {begins} begin / {ends} end"
    )


def apply_pointer(
    surface: Path | str,
    target: Path | str,
    *,
    label: str,
    create: bool = False,
    names_base: bool = False,
) -> PointerResult:
    """Write (or confirm) a pointer from ``surface`` to ``target`` (§3.3).

    ``names_base`` (U-ancestry ANC8): when this pointer block is
    BOOTSTRAPPED fresh, append the verbatim disambiguating sentence to
    its preamble -- the caller's signal that ``surface``'s host has a
    registered ancestor or descendant. Has no effect when the block
    already exists (only a NEW line is inserted then, the preamble is
    untouched) or when no write happens at all (leg 2 below).

    In order:

    1. ``surface`` is not a file: ``create=True`` makes it (empty,
       parents created); ``create=False`` raises :class:`CompileError`
       naming the surface, mirroring `compile_managed_file`'s refusal.
    2. `surface_names_target` already ``True`` (a hand-written mention
       counts): return ``changed=False`` with the resolvable token --
       NO write at all. This is the idempotence leg (K2).
    3. Otherwise compute the token, build the line, `compile_pointer_text`,
       write it, ``changed=True``.
    4. MANDATORY post-condition: re-read the file through
       `surface_names_target`. If it is still ``False``, the pre-write
       text is restored (never leave a wedged surface behind -- a dirty
       surface would trip the L4 refusal on every later route to this
       skill and be skipped by the recompile repair too) and
       :class:`CompileError` is raised naming the surface, target and
       token. This is the one place "we wrote something" is converted
       into "the contract holds"."""
    surface = Path(surface)
    target = Path(target)
    created = False

    if not surface.is_file():
        if not create:
            raise CompileError(
                f"pointer surface does not exist: {surface} — the pointer "
                "compiler never creates target files, only appends the "
                "block to an existing one"
            )
        surface.parent.mkdir(parents=True, exist_ok=True)
        surface.write_text("", encoding="utf-8")
        created = True

    if surface_names_target(surface, target):
        return PointerResult(
            surface=surface,
            target=target,
            token=pointer_token(surface, target),
            changed=False,
            created=created,
            bootstrapped=False,
        )

    token = pointer_token(surface, target)
    line = pointer_line(token, label)
    original_text = surface.read_text(encoding="utf-8")
    new_text, bootstrapped = compile_pointer_text(original_text, line, names_base=names_base)
    surface.write_text(new_text, encoding="utf-8")

    if not surface_names_target(surface, target):
        # r3 (NOTE 4): restore before raising -- the raise is still loud,
        # and the pointer's absence is still caught by the `reach`
        # selftest, but the surface itself must never be left dirty by a
        # failed write (that would block the very repair the error
        # recommends). Must not swallow the original error, and a failure
        # to restore must not mask it either.
        # FOLD MAJOR 1: a restore failure of its own (OSError/ENOSPC, a
        # permissions flip mid-run, ...) must not escape and MASK the
        # CompileError below -- an escaped OSError would leave the wedged
        # surface on disk, which is itself refused by later routes/
        # recompiles, blocking its own repair.
        # FOLD NOTE 1: the message must tell the truth about which of
        # these happened -- a "reverted" claim on a surface that is
        # actually still dirty sends a human/repair straight past it.
        restored = True
        try:
            surface.write_text(original_text, encoding="utf-8")
        except Exception:
            restored = False  # the CompileError below must still surface, not this
        outcome = (
            "the write was reverted" if restored
            else "the write could NOT be reverted — the surface is left "
            "dirty; restore it by hand"
        )
        raise CompileError(
            f"pointer post-condition failed: after writing token {token!r} "
            f"into {surface}, it still does not resolve to {target} — "
            f"{outcome}"
        )

    return PointerResult(
        surface=surface,
        target=target,
        token=token,
        changed=True,
        created=created,
        bootstrapped=bootstrapped,
    )


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


def reference_target_path(
    references_dir: Path | str, dest: str | None = None
) -> Path:
    """WHERE a reference route lands: ``dest`` (basename or path, resolved
    against ``references_dir``) else the default ``LEARNINGS.md``. The one
    place that mapping lives — :func:`compile_reference` writes here, and
    recompile / the drift check READ here (audit 2026-07-16 BLOCKER 2:
    both were blind to reference destinations entirely)."""
    if dest is None:
        return Path(references_dir) / DEFAULT_REFERENCE_BASENAME
    path = Path(dest)
    return path if path.is_absolute() else Path(references_dir) / path


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


def _retire_reference_text(text: str, record_id: str) -> tuple[str, str | None]:
    """Pure text transform (REC7's own discipline, applied to a removal
    instead of an append): remove *record_id*'s entry block -- the
    heading matching ``^## \\S+ — <record_id>\\s*$`` through the line
    BEFORE the next ``^## `` (or EOF) -- from *text*. Heading-bounded,
    never blank-line-bounded (the plausible wrong implementation, M45):
    a multi-paragraph entry's own blank lines never truncate the
    removal. Returns ``(new_text, removed)`` -- ``removed`` is ``None``
    (``new_text == text``) when no matching block is present.

    THE ONE PLACE this algorithm lives: :func:`retire_reference` (the
    real write) and verbs.py's same-commit prediction
    (``_expected_retired_reference_region``) both call this, so
    prediction and the write cannot drift."""
    heading_re = re.compile(
        rf"^## \S+ — {re.escape(record_id)}\s*$", re.MULTILINE
    )
    match = heading_re.search(text)
    if match is None:
        return text, None
    start = match.start()
    next_heading = re.compile(r"^## ", re.MULTILINE).search(text, match.end())
    end = next_heading.start() if next_heading is not None else len(text)
    removed = text[start:end]
    new_text = text[:start] + text[end:]
    # M-2 (U-verbs Phase 2 code gate r1): a `re.sub(r"\n{3,}", ...)`
    # USED to sit here, meant to collapse a blank-line run left behind
    # at the removal seam -- but the seam is PROVABLY always exactly
    # `\n\n` already (compile_reference's own writer, just above,
    # always separates entries with exactly one blank line and ends
    # the file with exactly one trailing newline; text[:start] and
    # text[end:] concatenate back to that same one blank line, or to
    # nothing when the removed entry was last). The regex therefore
    # never had a seam to collapse -- being GLOBAL, its only observed
    # effect was collapsing a human's OWN 3+-blank-line run anywhere
    # else in the file, reachable end-to-end through shipped verbs with
    # no hand edit (`route` into a pre-existing hand-written references
    # file, then `graduate` collapses the human's blank line). Deleted
    # outright, not narrowed: code that cannot do its stated job and
    # can still damage a human's file has no defensible narrowed form.
    # The trailing-newline normalisation below is NOT the same class of
    # bug: it matches compile_reference's own write-leg convention
    # (every append already rstrips trailing newlines before writing),
    # so a file that has been through compile_reference even once
    # already carries this same normalisation -- retirement staying
    # consistent with it is not a new overreach.
    new_text = new_text.rstrip("\n") + "\n"
    return new_text, removed


def retire_reference(
    references_dir: Path | str,
    record_id: str,
    *,
    dest: str | None = None,
) -> ReferenceResult:
    """Remove one record's entry block from a references file (U-verbs
    S-54 / 3.5, RER5-RER7) via :func:`_retire_reference_text`.

    Idempotent -- a record with no block present in the FILE (its own
    truth, never a compile prediction) returns ``applied=False`` and
    writes nothing.

    ``dest`` resolves through the SAME :func:`reference_target_path`
    mapping the write leg, ``recompile`` and the drift check all share
    (audit 2026-07-16 BLOCKER 2) -- never a second lookup."""
    path = reference_target_path(references_dir, dest)
    if not path.is_file():
        return ReferenceResult(path=path, applied=False, created=False, entry=None)
    text = path.read_text(encoding="utf-8")
    new_text, removed = _retire_reference_text(text, record_id)
    if removed is None:
        return ReferenceResult(path=path, applied=False, created=False, entry=None)
    path.write_text(new_text, encoding="utf-8")
    return ReferenceResult(path=path, applied=True, created=False, entry=removed)
