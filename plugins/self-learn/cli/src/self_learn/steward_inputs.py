"""What the steward reads (U3a of the pipeline redesign, 2026-09-27; spec
02-schema.md §3a.8).

The user, 2026-09-26: the pipeline is "a series of builders ... miner finds
lesson material > steward builds lessons > overseer builds a coherent
system out of those lessons", and on retiring the analyst "basically, i
think i agree with you". So the steward no longer reads the analyst's card:
it reads the lesson itself and what CODE can check about it.

This module builds, for one run:

1. **The inputs.** Three kinds (:data:`INPUT_KINDS`): a pending ``lesson``
   (selected by :mod:`steward`, identity = the record's committed blob), a
   ``reconsider`` input (unchanged, :func:`steward._reconsider_proposals`),
   and a ``suspected-violation``: every ``fire`` telemetry event with
   outcome ``suspected-violation`` (the legacy ``violated`` reads as it)
   that names a ROUTED record and that no record entry has handled yet,
   collected per record (:func:`suspected_violations`). The user's words
   (2026-09-26 19:32, of the audit's two options): "do both a and b" --
   (b) being that suspected rule violations the miner records go to the
   steward.
2. **The batches.** U2's :func:`index.related.group_for_steward` over the
   run's input ids: at most 10 per packet, at most 5 unrelated
   (:func:`plan_packets`). The lesson index is brought up to date
   incrementally at run start (:func:`refresh_index`); with no embedding
   key it is word search only and the run record says so. With no index at
   all the batches are 5 at a time (nothing is known to be related).
3. **The brief per lesson** (:func:`build_briefs`): the record (its lesson
   sections with their file line numbers, so a case can cite
   ``ledger@<commit>:<path>#L<a>-<b>`` without opening the file), an
   **evidence pack** built by code with U1 (:mod:`refs`) -- each evidence
   item's resolved ref, the quote check's verdict with the corrected ref
   where the text was found somewhere else, and a bounded, redacted excerpt
   of the entries around it with who spoke on each line -- the closest
   existing lessons (U2 ``nearest``), and the links that put the lesson in
   this batch.
4. **The data points** a future dashboard reads (the user, 2026-09-26
   21:58: "make gathering data points for the future screen easy"): per
   packet, the group's basis counts, pack sizes and verdict counts
   (:func:`packet_stats`), and how many transcript and ledger reads the
   steward still made (:func:`tool_reads`).

Nothing here writes the ledger. The index lives in the cache. Transcript
text reaches the brief only through :func:`refs.excerpt`, which redacts it;
a verdict's detail never carries transcript or quote text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import refs, telemetry
from .index import hybrid
from .index.related import MAX_GROUP, MAX_UNRELATED, Relatedness, group_for_steward
from .index.store import LessonIndex
from .records import Record

__all__ = [
    "INPUT_LESSON",
    "INPUT_RECONSIDER",
    "INPUT_SUSPECTED_VIOLATION",
    "INPUT_KINDS",
    "LessonBrief",
    "PacketPlan",
    "build_briefs",
    "fires_version",
    "packet_stats",
    "plan_packets",
    "refresh_index",
    "suspected_violations",
    "tool_reads",
]

INPUT_LESSON = "lesson"
INPUT_RECONSIDER = "reconsider"
INPUT_SUSPECTED_VIOLATION = "suspected-violation"
INPUT_KINDS = (INPUT_LESSON, INPUT_RECONSIDER, INPUT_SUSPECTED_VIOLATION)

# ------------------------------------------------------------ the budgets
#
# MEASURED 2026-09-27 on the live pending queue (read-only, word search
# only, no embedding call; misc/pipeline-design-2026-09-26/u3a-measure/):
# see 02-schema.md §3a.8 for the numbers these were chosen against.

#: Entries either side of an evidence item's line in its excerpt.
EXCERPT_BEFORE = 2
EXCERPT_AFTER = 2
#: One entry's text in an excerpt is clipped to this (head and tail kept).
EXCERPT_ENTRY_CHARS = 700
#: One evidence item's excerpt, all its entries together.
EXCERPT_ITEM_CHARS = 2_800
#: One lesson's whole pack (every excerpt of its evidence items).
LESSON_PACK_CHARS = 9_000
#: One packet's packs together; each lesson gets an equal share of this
#: when the share is smaller than :data:`LESSON_PACK_CHARS`.
PACKET_PACK_CHARS = 60_000
#: Below this many characters left, an item gets its ref and verdict only.
MIN_EXCERPT_CHARS = 400
#: The quote check's ``other_session`` search, capped lower than the
#: audit's 200 files: this runs for every item of every packet.
PACK_OTHER_SESSION_CAP = 60
#: The closest existing lessons shown per lesson.
NEAREST_LIMIT = 5
#: Fire events shown per suspected-violation input (newest last).
FIRE_EVENTS_SHOWN = 5

#: Extra verdicts beyond :data:`refs.VERDICTS` the pack can report.
NO_QUOTE = "no_quote"
UNRESOLVABLE = "unresolvable"
NOT_A_TRANSCRIPT = "not_a_transcript"

_ORIGIN_RE = re.compile(r"^transcript:([^#\s]+)#L(\d+)$")
_CORRECTED = frozenset({"nearby", "elsewhere_in_file", "other_session"})

#: What each verdict means, in the words the steward reads.
VERDICT_MEANING: dict[str, str] = {
    "exact": "the quote is verbatim in the cited entry",
    "normalised": "the quote is in the cited entry once quotes, dashes and spaces are normalised",
    "nearby": "NOT in the cited entry; found in a nearby entry of the same file -- use the corrected ref",
    "elsewhere_in_file": "NOT near the cited line; found elsewhere in the same file -- use the corrected ref",
    "stitched": "NOT one passage: pieces joined with an ellipsis, each found separately -- no entry says this",
    "other_session": "NOT in the cited session; found in ANOTHER session -- the record's pointer is wrong",
    "not_found": "NOT FOUND anywhere the checker looked -- this evidence does not check out",
    NO_QUOTE: "the item carries no quote to check; the excerpt is what the cited line says",
    UNRESOLVABLE: "the cited transcript could not be found or read -- nothing about this item is checked",
    NOT_A_TRANSCRIPT: "not a transcript pointer; nothing here checks it",
}

#: Verdicts under which the record's evidence item checks out as cited.
CHECKS_OUT = frozenset({"exact", "normalised"})


# --------------------------------------------------------------- the index


def refresh_index(home: Path) -> tuple[LessonIndex | None, dict]:
    """Bring the lesson index up to date (incremental) and return it open,
    with what the run record says about it. Never raises: an index that
    cannot be built is ``None`` and ``mode: unavailable`` says why. With no
    embedding key the build is word search only (``mode: lexical-only``)."""
    try:
        index = LessonIndex.open(home)
    except Exception as exc:  # noqa: BLE001 -- the run goes on without it
        return None, {"mode": "unavailable", "mode_reason": _short(exc)}
    try:
        report = index.build()
    except Exception as exc:  # noqa: BLE001
        index.close()
        return None, {"mode": "unavailable", "mode_reason": _short(exc)}
    info = {
        "mode": report.mode,
        "mode_reason": report.mode_reason,
        "model": report.model,
        "added": len(report.added),
        "changed": len(report.changed),
        "removed": len(report.removed),
        "embedded": len(report.embedded),
        "embed_error": report.embed_error or None,
    }
    return index, info


def _short(exc: BaseException) -> str:
    return f"the lesson index could not be built: {type(exc).__name__}: {exc}"[:300]


def open_index(home: Path) -> LessonIndex | None:
    """The existing index, or ``None`` (never built, or unreadable)."""
    try:
        return LessonIndex.open_existing(home)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------- the batches


@dataclass
class PacketPlan:
    """One packet: its record ids in reading order, and why they are together."""

    members: list[str]
    unrelated: list[str]
    links: list[dict]
    basis_counts: dict[str, int]

    def to_json(self) -> dict:
        return {
            "members": list(self.members),
            "unrelated": list(self.unrelated),
            "links": [dict(link) for link in self.links],
            "basis_counts": dict(self.basis_counts),
        }


def packet_limits(packet_size: int) -> tuple[int, int]:
    """``(max per packet, max unrelated)``. The user's rule (2026-09-20):
    at most 10, at most 5 unrelated. ``steward.packet_size`` can only
    lower the first (a value above 10 conflicts with the rule and is
    capped); the second never exceeds the first."""
    size = max(1, min(MAX_GROUP, int(packet_size)))
    return size, min(MAX_UNRELATED, size)


def plan_packets(
    ids: Sequence[str], index: LessonIndex | None, packet_size: int
) -> tuple[list[PacketPlan], dict]:
    """Batch ``ids`` (in the caller's order: oldest first) into packets.

    With an index: :func:`group_for_steward`, each group's members kept in
    the caller's order. Without one: chunks of the unrelated cap, since
    nothing is known to be related. Returns the plans and the run-level
    facts the run record keeps (``basis``, ``basis_reason``, thresholds)."""
    order = {rid: n for n, rid in enumerate(ids)}
    size, unrelated_cap = packet_limits(packet_size)
    if index is None:
        plans = [
            PacketPlan(
                members=list(ids[start:start + unrelated_cap]),
                unrelated=list(ids[start:start + unrelated_cap]),
                links=[],
                basis_counts={"cosine": 0, "lexical": 0, "none": 0},
            )
            for start in range(0, len(ids), unrelated_cap)
        ]
        return plans, {
            "basis": "none",
            "basis_reason": "no lesson index: batched without relatedness, "
            f"{unrelated_cap} at a time",
            "max_size": size,
            "max_unrelated": unrelated_cap,
            "thresholds": {"cosine": None, "lexical": None},
            "not_indexed": list(ids),
        }
    grouping = group_for_steward(ids, index=index, max_size=size, max_unrelated=unrelated_cap)
    rel = Relatedness(index)
    plans: list[PacketPlan] = []
    for group in grouping.groups:
        members = sorted(group.members, key=lambda rid: (order.get(rid, len(order)), rid))
        counts = {"cosine": 0, "lexical": 0, "none": 0}
        for x, a in enumerate(members):
            for b in members[x + 1:]:
                basis = rel.relation(a, b).basis
                counts[basis if basis in ("cosine", "lexical") else "none"] += 1
        plans.append(PacketPlan(
            members=members,
            unrelated=sorted(group.unrelated, key=lambda rid: order.get(rid, len(order))),
            links=[link.to_json() for link in group.links],
            basis_counts=counts,
        ))
    # Packets in the order of their oldest member, so the oldest lesson is
    # decided first, as it was before batches followed relatedness.
    plans.sort(key=lambda plan: min(order.get(rid, len(order)) for rid in plan.members))
    return plans, {
        "basis": grouping.basis,
        "basis_reason": grouping.basis_reason,
        "max_size": size,
        "max_unrelated": unrelated_cap,
        "thresholds": dict(grouping.thresholds),
        "not_indexed": list(grouping.not_indexed),
    }


# ------------------------------------------------ suspected rule violations


def _handled_refs(record: Record) -> set[str]:
    refs_seen = {str(r.get("ref")) for r in record.recurrences if isinstance(r, dict) and r.get("ref")}
    refs_seen |= {
        str(d.get("ref")) for d in record.dismissed_suspects if isinstance(d, dict) and d.get("ref")
    }
    return refs_seen


#: The ``basis`` the miner's legacy backfill gives the ``recurrence-suspect``
#: it spooled for a pre-U6 ``violated`` fire (``miner._FIRE_VIOLATED_BASIS``,
#: and the older spelling ``fire-violated``).
FIRE_SUSPECT_BASES = frozenset({"fire-suspected-violation", "fire-violated"})


def suspected_violations(
    home: Path, find_record: Any
) -> dict[str, list[dict]]:
    """Every unhandled ``suspected-violation`` fire, by the ROUTED record it
    names, oldest first. ``find_record(home, rid)`` returns the record or
    ``None``. Handled means: the record's ``recurrences`` or
    ``dismissed_suspects`` names the event's nonce (what ``confirm-
    recurrence`` and ``dismiss-suspect`` write); a record no longer routed
    has nothing a fire can be against. Whether a run already decided an
    event is the caller's check (the committed run records).

    **One observation, one nonce.** The miner's legacy backfill spooled a
    ``recurrence-suspect`` (its own nonce, basis ``fire-violated``) for each
    pre-U6 ``violated`` fire, and those suspects are the review's "not
    holding" cards -- measured 2026-09-27: 6 of the live queue's 9 fire
    events had one, 4 of them already confirmed or dismissed by the user. A
    fire whose same-``(record, origin)`` fire-basis suspect is handled is
    handled; one whose suspect is not yet handled is offered under the
    SUSPECT's nonce (``fire_nonce`` keeps the fire's), so deciding it clears
    the review card too."""
    all_events = telemetry.read_events(home)
    siblings: dict[tuple[str, str], list[dict]] = {}
    for event in all_events:
        if event.get("kind") == "recurrence-suspect" and event.get("basis") in FIRE_SUSPECT_BASES:
            key = (str(event.get("record")), str(event.get("origin")))
            if isinstance(event.get("nonce"), str):
                siblings.setdefault(key, []).append(event)
    events: dict[str, list[dict]] = {}
    for event in all_events:
        if event.get("kind") != "fire" or event.get("outcome") != "suspected-violation":
            continue
        rid, nonce = event.get("record"), event.get("nonce")
        if not isinstance(rid, str) or not isinstance(nonce, str):
            continue
        events.setdefault(rid, []).append(event)
    out: dict[str, list[dict]] = {}
    for rid in sorted(events):
        record = find_record(home, rid)
        if record is None or record.status != "routed":
            continue
        handled = _handled_refs(record)
        fresh: list[dict] = []
        for event in events[rid]:
            if str(event.get("nonce")) in handled:
                continue
            twins = siblings.get((rid, str(event.get("origin"))), [])
            if any(str(t.get("nonce")) in handled for t in twins):
                continue
            if twins:
                twin = min(twins, key=lambda t: (str(t.get("ts") or ""), str(t.get("nonce"))))
                event = {**event, "nonce": twin["nonce"], "fire_nonce": event.get("nonce"),
                         "kind": "recurrence-suspect"}
            fresh.append(event)
        # one event per nonce, oldest first
        seen: set[str] = set()
        unique = []
        for event in sorted(fresh, key=lambda e: (str(e.get("ts") or ""), str(e.get("nonce")))):
            if event["nonce"] in seen:
                continue
            seen.add(event["nonce"])
            unique.append(event)
        if unique:
            out[rid] = unique
    return out


def fires_version(events: Iterable[dict]) -> str:
    """The input identity of a suspected-violation input: its events' nonces,
    sorted. A new fire about the same record is a new version."""
    return "fires:" + ",".join(sorted(str(e.get("nonce")) for e in events))


# -------------------------------------------------------------- the record


_HEADING = re.compile(r"^## (.+?)\s*$")
_LESSON_SECTIONS = {
    "behavior": ("Trigger", "Instruction"),
    "knowledge": ("Fact", "Context"),
}


def _section_lines(text: str) -> dict[str, tuple[int, int, list[str]]]:
    """``{heading: (first body line, last body line, body lines)}`` over the
    whole record file, 1-based file line numbers, blank edges trimmed."""
    lines = text.splitlines()
    heads = [(n + 1, m.group(1)) for n, line in enumerate(lines) if (m := _HEADING.match(line))]
    out: dict[str, tuple[int, int, list[str]]] = {}
    for i, (at, name) in enumerate(heads):
        end = heads[i + 1][0] - 1 if i + 1 < len(heads) else len(lines)
        body = list(range(at + 1, end + 1))
        while body and not lines[body[0] - 1].strip():
            body.pop(0)
        while body and not lines[body[-1] - 1].strip():
            body.pop()
        if body and name not in out:
            out[name] = (body[0], body[-1], [lines[n - 1] for n in body])
    return out


def _one_line(text: object) -> str:
    return " ".join(str(text).split())


def render_record(record: Record, *, path: str | None, head: str | None, bucket: str) -> str:
    """The lesson as the steward reads it: its facts on one line, then its
    lesson sections with their file lines (citable as
    ``ledger@<commit>:<path>#L<a>-<b>``)."""
    lines = [
        f"[lesson] {record.type}, scope {record.scope}, bucket {bucket}, "
        f"status {record.status}, sightings {record.sightings}, created {record.created_at}"
    ]
    if isinstance(record.routing, dict) and record.routing.get("destination"):
        lines.append(
            f"[routed] to {record.routing.get('destination')}"
            + (f" ({record.routing.get('variant')})" if record.routing.get("variant") else "")
            + f" at {record.routing.get('routed_at')}"
        )
    if path:
        lines.append(f"[record] ledger@{(head or 'HEAD')[:12]}:{path}")
    sections = _section_lines(record.to_text())
    for name in _LESSON_SECTIONS.get(record.type, ()):
        found = sections.get(name)
        if found is None:
            continue
        first, last, body = found
        span = f"L{first}" if first == last else f"L{first}-{last}"
        lines.append(f"  {name} ({span}):")
        lines += [f"    {line}" for line in body]
    if record.verified_how:
        lines.append(
            "  verification as the miner wrote it (no ref; not checked by code): "
            + _one_line(record.verified_how)
        )
    return "\n".join(lines)


# ----------------------------------------------------------- evidence pack


#: Relayed rows that say nothing (an empty attachment rendered as ``{}``,
#: the harness's token-count notice). Measured 2026-09-27 on the live
#: queue: they took one or two of the four context slots of most excerpts.
_NOISE_PREFIXES = ("<total_tokens>",)
_NOISE_TEXTS = frozenset({"", "{}", "[]"})


def _is_noise(ref: refs.Ref, text: str) -> bool:
    stripped = text.strip()
    return ref.role == "relay" and (
        stripped in _NOISE_TEXTS or stripped.startswith(_NOISE_PREFIXES)
    )


def _excerpt(anchor: refs.Ref, left: int, roots: Sequence[Path]) -> list[tuple[refs.Ref, str]]:
    """:func:`refs.excerpt` around ``anchor`` with contentless relayed rows
    dropped: :data:`EXCERPT_BEFORE` / :data:`EXCERPT_AFTER` entries that
    say something, either side, within ``min(EXCERPT_ITEM_CHARS, left)``."""
    rows = refs.excerpt(
        anchor, EXCERPT_BEFORE + 4, EXCERPT_AFTER + 4,
        entry_chars=EXCERPT_ENTRY_CHARS,
        total_chars=min(EXCERPT_ITEM_CHARS, left), roots=roots,
    )
    kept = [(r, t) for r, t in rows if r.line == anchor.line or not _is_noise(r, t)]
    before = [row for row in kept if row[0].line < anchor.line][-EXCERPT_BEFORE:]
    after = [row for row in kept if row[0].line > anchor.line][:EXCERPT_AFTER]
    return before + [row for row in kept if row[0].line == anchor.line] + after


@dataclass
class _Item:
    n: int
    cited: str
    verdict: str
    ref: refs.Ref | None = None
    found: refs.Ref | None = None
    detail: str = ""
    quote: str | None = None
    same_as: int | None = None
    excerpt: list[tuple[refs.Ref, str]] = field(default_factory=list)
    omitted: str = ""


def _cited_ref(item: dict, roots: Sequence[Path]) -> tuple[str, refs.Ref | None, str]:
    """``(what the record cites, the resolved ref or None, verdict if not resolvable)``."""
    raw = item.get("ref")
    if isinstance(raw, dict):
        try:
            given = refs.Ref.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            given = None
        if given is not None:
            try:
                return given.origin, refs.resolve(
                    given.session, given.line, given.uuid,
                    subagent_file=given.subagent_file, roots=roots,
                ), ""
            except (refs.RefError, OSError) as exc:
                return given.origin, None, f"{UNRESOLVABLE}:{exc}"
    origin = item.get("origin")
    m = _ORIGIN_RE.match(str(origin or "").strip())
    if not m:
        return str(origin or "(no pointer)"), None, NOT_A_TRANSCRIPT
    try:
        return m.group(0), refs.resolve(m.group(1), int(m.group(2)), roots=roots), ""
    except (refs.RefError, OSError, ValueError) as exc:
        return m.group(0), None, f"{UNRESOLVABLE}:{exc}"


def _check(item: dict, ref: refs.Ref, roots: Sequence[Path]) -> tuple[str, refs.Ref, str]:
    quote = item.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return NO_QUOTE, ref, ""
    try:
        verdict = refs.check_quote(
            ref, quote, roots=roots, other_session_cap=PACK_OTHER_SESSION_CAP
        )
    except (refs.RefError, OSError) as exc:
        return UNRESOLVABLE, ref, str(exc)
    found = verdict.ref if verdict.outcome in _CORRECTED else ref
    return verdict.outcome, found, verdict.detail


def evidence_pack(
    record: Record, *, roots: Sequence[Path], budget: int
) -> tuple[list[_Item], dict]:
    """Check every evidence item of ``record`` and excerpt around it, within
    ``budget`` characters of excerpt text. Items the budget cannot reach
    keep their ref and verdict. A second item at the same transcript
    moment (same entry uuid: a resumed or forked copy) is marked, not
    excerpted again."""
    items: list[_Item] = []
    moments: dict[str, int] = {}
    left = budget
    for n, raw in enumerate((e for e in record.evidence if isinstance(e, dict)), start=1):
        cited, ref, failed = _cited_ref(raw, roots)
        quote = raw.get("quote") if isinstance(raw.get("quote"), str) else None
        if ref is None:
            verdict = failed.split(":", 1)[0]
            detail = failed.split(":", 1)[1] if ":" in failed else ""
            items.append(_Item(n, cited, verdict, detail=detail, quote=quote))
            continue
        outcome, found, detail = _check(raw, ref, roots)
        item = _Item(n, cited, outcome, ref=ref, found=found, detail=detail, quote=quote)
        items.append(item)
        anchor = found if outcome in _CORRECTED else ref
        if anchor.uuid and anchor.uuid in moments:
            item.same_as = moments[anchor.uuid]
            continue
        if anchor.uuid:
            moments[anchor.uuid] = n
        if left < MIN_EXCERPT_CHARS:
            item.omitted = "excerpt left out: this lesson's pack budget is spent"
            continue
        try:
            item.excerpt = _excerpt(anchor, left, roots)
        except (refs.RefError, OSError) as exc:
            item.omitted = f"excerpt unavailable: {exc}"
            continue
        left -= sum(len(text) for _ref, text in item.excerpt)
    stats = _item_stats(items)
    stats["budget_chars"] = budget
    return items, stats


def _item_stats(items: list[_Item]) -> dict:
    verdicts: dict[str, int] = {}
    for item in items:
        verdicts[item.verdict] = verdicts.get(item.verdict, 0) + 1
    return {
        "items": len(items),
        "excerpted": sum(1 for i in items if i.excerpt),
        "same_moment": sum(1 for i in items if i.same_as is not None),
        "excerpt_chars": sum(len(t) for i in items for _r, t in i.excerpt),
        "verdicts": dict(sorted(verdicts.items())),
    }


def _ref_line(ref: refs.Ref) -> str:
    parts = [
        f"session {ref.session}",
        f"folder {ref.project_dir}",
        f"line {ref.line}",
        f"uuid {ref.uuid or '-'}",
        f"at {ref.entry_ts or '-'}",
        f"spoke: {ref.role}",
    ]
    if ref.subagent_file:
        parts.insert(2, f"file {ref.subagent_file}")
    return " | ".join(parts)


def _render_excerpt(rows: list[tuple[refs.Ref, str]], anchor_line: int, indent: str) -> list[str]:
    out = []
    for ref, text in rows:
        mark = "  <- this line" if ref.line == anchor_line else ""
        body = text.splitlines() or [""]
        out.append(f"{indent}L{ref.line} {ref.role}:{mark} {body[0]}")
        out += [f"{indent}    {line}" for line in body[1:]]
    return out


def render_pack(items: list[_Item]) -> str:
    if not items:
        return "[evidence pack] the record carries no evidence items"
    counts = _item_stats(items)["verdicts"]
    summary = ", ".join(f"{k} {v}" for k, v in counts.items())
    lines = [f"[evidence pack] {len(items)} item(s), checked by code: {summary}"]
    for item in items:
        lines.append(f"  item {item.n}: the record cites {item.cited}")
        if item.ref is not None:
            lines.append(f"    cited ref: {_ref_line(item.ref)}")
        if item.quote is not None:
            lines.append(f"    quote: {json.dumps(_one_line(item.quote), ensure_ascii=False)}")
        meaning = VERDICT_MEANING.get(item.verdict, "")
        lines.append(f"    verdict: {item.verdict} -- {meaning}")
        if item.found is not None and item.verdict in _CORRECTED:
            lines.append(f"    corrected ref: {_ref_line(item.found)} (cite transcript:{item.found.session}#L{item.found.line})")
        if item.detail:
            lines.append(f"    check detail: {_one_line(item.detail)}")
        if item.same_as is not None:
            lines.append(
                f"    same transcript moment as item {item.same_as} (same entry uuid: a "
                "resumed or forked copy of one conversation) -- one sighting, not two"
            )
        if item.excerpt:
            anchor = item.found if item.verdict in _CORRECTED else item.ref
            lines.append("    excerpt (who spoke on each line; redacted, clipped):")
            lines += _render_excerpt(item.excerpt, anchor.line if anchor else 0, "      ")
        elif item.omitted:
            lines.append(f"    {item.omitted}")
    return "\n".join(lines)


# ------------------------------------------------------------- fire packs


def fire_pack(events: list[dict], *, roots: Sequence[Path], budget: int) -> tuple[str, dict]:
    """The suspected-violation events of one routed record: each event's
    nonce (what a sheet item names as ``event``), its pointer resolved, and
    an excerpt around it."""
    shown = events[-FIRE_EVENTS_SHOWN:]
    lines = [
        f"[suspected violations] {len(events)} unhandled miner fire(s) with outcome "
        "suspected-violation name this routed lesson"
        + (f"; the newest {len(shown)} are shown" if len(shown) < len(events) else "")
    ]
    left = budget
    stats = {"items": len(events), "excerpted": 0, "excerpt_chars": 0, "verdicts": {}}
    for event in shown:
        nonce = str(event.get("nonce"))
        origin = str(event.get("origin") or "")
        lines.append(
            f"  event {nonce}: at {event.get('ts')}, outcome {event.get('outcome')}, "
            f"pointer {origin or '(none)'}"
        )
        if event.get("fire_nonce"):
            lines.append(
                f"    (the recurrence-suspect the miner raised for fire {event['fire_nonce']}; "
                "deciding it also clears the review's card)"
            )
        m = _ORIGIN_RE.match(origin.strip())
        if not m:
            lines.append("    the pointer is not a transcript line; nothing here checks it")
            continue
        try:
            ref = refs.resolve(m.group(1), int(m.group(2)), roots=roots)
        except (refs.RefError, OSError, ValueError) as exc:
            lines.append(f"    the cited transcript could not be read: {_one_line(exc)}")
            continue
        lines.append(f"    ref: {_ref_line(ref)}")
        if left < MIN_EXCERPT_CHARS:
            lines.append("    excerpt left out: this lesson's pack budget is spent")
            continue
        try:
            rows = _excerpt(ref, left, roots)
        except (refs.RefError, OSError) as exc:
            lines.append(f"    excerpt unavailable: {_one_line(exc)}")
            continue
        used = sum(len(t) for _r, t in rows)
        left -= used
        stats["excerpted"] += 1
        stats["excerpt_chars"] += used
        lines.append("    excerpt (who spoke on each line; redacted, clipped):")
        lines += _render_excerpt(rows, ref.line, "      ")
    return "\n".join(lines), stats


# ---------------------------------------------------------- nearest lessons


def render_nearest(index: LessonIndex | None, record_id: str, home: Path, find_record: Any) -> tuple[str, dict]:
    """The closest existing lessons of any status (U2 ``nearest``), with
    status, bucket and, for a routed one, where it went."""
    if index is None:
        return "[closest existing lessons] unavailable: no lesson index", {"nearest": 0, "mode": "none"}
    try:
        docs = index.docs()
        if record_id not in docs:
            return (
                f"[closest existing lessons] {record_id} is not in the lesson index yet",
                {"nearest": 0, "mode": "none"},
            )
        near = hybrid.nearest(index, record_id, limit=NEAREST_LIMIT)
    except Exception as exc:  # noqa: BLE001 -- a broken index never costs the brief
        return f"[closest existing lessons] unavailable: {_one_line(exc)[:200]}", {"nearest": 0, "mode": "none"}
    how = "words and meaning" if near.mode == "hybrid" else "word search only"
    lines = [f"[closest existing lessons] {how}, any status, closest first"]
    for hit in near.hits:
        doc = docs.get(hit.id)
        if doc is None:
            continue
        where = ""
        title = ""
        other = find_record(home, hit.id)
        if other is not None:
            from .ledger_ops import record_title  # late: ledger_ops imports far more

            title = record_title(other)
            routing = other.routing if isinstance(other.routing, dict) else {}
            if routing.get("destination"):
                where = f" -> {routing.get('destination')}"
        score = []
        if hit.lexical is not None:
            score.append(f"words {hit.lexical:.2f}")
        if hit.cosine is not None:
            score.append(f"meaning {hit.cosine:.2f}")
        lines.append(
            f"  {hit.id} {doc.status}{where} | {doc.bucket_scope}:{doc.bucket_name} | "
            f"{json.dumps(title[:160], ensure_ascii=False)}"
            + (f" ({', '.join(score)})" if score else "")
        )
    if len(lines) == 1:
        lines.append("  (none)")
    return "\n".join(lines), {"nearest": len(lines) - 1, "mode": near.mode}


def render_links(record_id: str, links: list[dict]) -> str:
    mine = [link for link in links if record_id in (link.get("a"), link.get("b"))]
    if not mine:
        return "[batched with] no lesson in this packet is related to this one"
    lines = ["[batched with] why these lessons share a packet"]
    for link in mine:
        other = link["b"] if link.get("a") == record_id else link["a"]
        why = []
        if link.get("shared_sessions"):
            why.append("same session " + ", ".join(link["shared_sessions"]))
        if link.get("shared_uuids") and not link.get("shared_sessions"):
            why.append("same transcript moment (entry uuid)")
        if "bucket+similar" in (link.get("reasons") or []):
            sim = link.get("similarity")
            why.append(
                f"same bucket, close in meaning ({link.get('basis')} {sim})"
            )
        lines.append(f"  {other}: {'; '.join(why) or 'related'}")
    return "\n".join(lines)


# ------------------------------------------------------------- the briefs


@dataclass
class LessonBrief:
    record_id: str
    kind: str
    body: str
    stats: dict


def _bucket_of(home: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(Path(home).resolve()).parts
    except ValueError:
        return "?"
    if rel[:1] == ("user",):
        return "user:user"
    if len(rel) >= 2 and rel[0] in ("skills", "projects"):
        return f"{'skill' if rel[0] == 'skills' else 'project'}:{rel[1]}"
    return "?"


def build_briefs(
    home: Path,
    inputs: list[dict],
    *,
    find_record_path: Any,
    index: LessonIndex | None = None,
    links: list[dict] | None = None,
    head: str | None = None,
    roots: Sequence[Path] | None = None,
    packet_budget: int = PACKET_PACK_CHARS,
) -> dict[str, LessonBrief]:
    """One brief per input (``{"id", "kind", ...}``), keyed by record id.

    ``find_record_path(home, rid)`` locates the record file (raises when
    there is none). ``links``: the packet's relatedness links
    (:class:`PacketPlan`). Each lesson's pack gets
    ``min(LESSON_PACK_CHARS, packet_budget // len(inputs))`` characters of
    excerpt."""
    home = Path(home)
    resolved_roots = list(roots) if roots is not None else refs.transcript_roots(home)
    share = min(LESSON_PACK_CHARS, packet_budget // max(1, len(inputs)))

    def find(h: Path, rid: str) -> Record | None:
        try:
            return Record.from_path(find_record_path(h, rid))
        except Exception:  # noqa: BLE001 -- a missing record is shown as missing
            return None

    out: dict[str, LessonBrief] = {}
    for row in inputs:
        rid = str(row.get("id"))
        kind = str(row.get("kind") or INPUT_LESSON)
        parts: list[str] = [f"[input] {kind}"]
        stats: dict = {"kind": kind}
        try:
            path = Path(find_record_path(home, rid))
            record = Record.from_path(path)
        except Exception as exc:  # noqa: BLE001
            parts.append(f"[lesson] not found in the ledger: {_one_line(exc)[:200]}")
            out[rid] = LessonBrief(rid, kind, "\n".join(parts), {**stats, "pack_chars": 0})
            continue
        try:
            rel = path.resolve().relative_to(home.resolve()).as_posix()
        except ValueError:
            rel = None
        if kind == INPUT_RECONSIDER and row.get("reason"):
            parts.append(f"[why it is back] {_one_line(row['reason'])}")
        parts.append(render_record(record, path=rel, head=head, bucket=_bucket_of(home, path)))
        if kind == INPUT_SUSPECTED_VIOLATION:
            events = [e for e in row.get("events") or [] if isinstance(e, dict)]
            text, pack_stats = fire_pack(events, roots=resolved_roots, budget=share)
            parts.append(text)
        else:
            items, pack_stats = evidence_pack(record, roots=resolved_roots, budget=share)
            parts.append(render_pack(items))
        near_text, near_stats = render_nearest(index, rid, home, find)
        parts.append(near_text)
        parts.append(render_links(rid, links or []))
        body = "\n".join(parts)
        stats.update(pack_stats)
        stats.update(near_stats)
        stats["brief_chars"] = len(body)
        out[rid] = LessonBrief(rid, kind, body, stats)
    return out


def packet_stats(briefs: Iterable[LessonBrief], plan: dict | None = None) -> dict:
    """What the run record keeps about one packet's brief: dashboard data,
    and the check that packs work."""
    rows = list(briefs)
    verdicts: dict[str, int] = {}
    for brief in rows:
        for key, value in (brief.stats.get("verdicts") or {}).items():
            verdicts[key] = verdicts.get(key, 0) + int(value)
    kinds: dict[str, int] = {}
    for brief in rows:
        kinds[brief.kind] = kinds.get(brief.kind, 0) + 1
    out = {
        "lessons": len(rows),
        "kinds": dict(sorted(kinds.items())),
        "brief_chars": sum(int(b.stats.get("brief_chars") or 0) for b in rows),
        "pack_chars": sum(int(b.stats.get("excerpt_chars") or 0) for b in rows),
        "pack_chars_max": max((int(b.stats.get("excerpt_chars") or 0) for b in rows), default=0),
        "evidence_items": sum(int(b.stats.get("items") or 0) for b in rows),
        "excerpted": sum(int(b.stats.get("excerpted") or 0) for b in rows),
        "verdicts": dict(sorted(verdicts.items())),
        "nearest_mode": sorted({str(b.stats.get("mode")) for b in rows if b.stats.get("mode")}),
    }
    if plan is not None:
        out["basis_counts"] = dict(plan.get("basis_counts") or {})
    return out


# ------------------------------------------------------ what the steward read


#: A tool call whose input names one of these touches a session transcript
#: (the 2026-09-26 audit's rule, `steward_transcript_calls.py`).
TRANSCRIPT_MARKS = (".claude/projects", "archive/sessions", ".jsonl")


def tool_reads(outcome: object, home: Path) -> dict | None:
    """How many tool calls the steward's session made, and how many of them
    reached a transcript or a ledger record file -- the check that the pack
    made going to the transcript rare. ``None`` when the backend reported
    no tool events (a fake, or a CLI transport)."""
    events = getattr(outcome, "tool_events", None)
    if events is None:
        return None
    home_text = str(Path(home))
    uses = [e for e in events if isinstance(e, dict) and e.get("kind") == "tool_use"]
    transcript = ledger = 0
    by_name: dict[str, int] = {}
    for use in uses:
        name = str(use.get("name"))
        by_name[name] = by_name.get(name, 0) + 1
        text = json.dumps(use.get("input"), default=str)
        if any(mark in text for mark in TRANSCRIPT_MARKS) and "telemetry" not in text:
            transcript += 1
        elif home_text in text and "lrn-" in text:
            ledger += 1
    return {
        "tool_uses": len(uses),
        "transcript_reads": transcript,
        "ledger_record_reads": ledger,
        "by_tool": dict(sorted(by_name.items())),
    }
