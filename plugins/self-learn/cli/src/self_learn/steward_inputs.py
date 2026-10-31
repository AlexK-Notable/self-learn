"""What the steward reads (U3a of the pipeline redesign, 2026-09-27; spec
02-schema.md §3a.8).

The user, 2026-09-26: the pipeline is "a series of builders ... miner finds
lesson material > steward builds lessons > overseer builds a coherent
system out of those lessons", and on retiring the analyst "basically, i
think i agree with you". So the steward no longer reads the analyst's card:
it reads the lesson itself and what CODE can check about it.

This module builds, for one run:

1. **The inputs.** Four kinds (:data:`INPUT_KINDS`): a pending ``lesson``
   (selected by :mod:`steward`, identity = the record's committed blob), a
   ``reconsider`` input (unchanged, :func:`steward._reconsider_proposals`),
   and a ``suspected-violation``: every ``fire`` telemetry event with
   outcome ``suspected-violation`` (the legacy ``violated`` reads as it)
   that names a ROUTED record and that no record entry has handled yet,
   collected per record (:func:`suspected_violations`). The user's words
   (2026-09-26 19:32, of the audit's two options): "do both a and b" --
   (b) being that suspected rule violations the miner records go to the
   steward. The fourth, ``premise-moved`` (S-NEXT-u3-followup, the premise
   check's unit U3), is a ROUTED lesson something the lesson rested on has
   moved for; today the one thing that moves it is a closed follow-up
   (:func:`moved_followups`), and the premise sweep adds its own movers
   later through the same kind (:func:`premise_moved_version`).
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

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import refs, telemetry
from .index import hybrid
from .index.related import MAX_GROUP, MAX_UNRELATED, Relatedness, group_for_steward
from .index.store import LessonIndex
from .primitives import chrono
from .records import Record

__all__ = [
    "INPUT_LESSON",
    "INPUT_RECONSIDER",
    "INPUT_SUSPECTED_VIOLATION",
    "INPUT_PREMISE_MOVED",
    "INPUT_KINDS",
    "LessonBrief",
    "MovedFollowup",
    "PREMISE_MOVED_PER_RUN",
    "PacketPlan",
    "build_briefs",
    "fires_version",
    "last_decision",
    "moved_followups",
    "open_followup_ids",
    "packet_stats",
    "plan_packets",
    "premise_moved_version",
    "premises_enabled",
    "PremiseMoves",
    "broken_probes",
    "moved_premises",
    "placed_with_premises",
    "probe_words",
    "refresh_index",
    "suspected_violations",
    "tool_reads",
    # S-NEXT-u8-placement
    "PlacementMoves",
    "intact_group",
    "intact_groups",
    "keep_groups_together",
    "placement_moves",
    "quotable_line",
    "scan_hit",
]

INPUT_LESSON = "lesson"
INPUT_RECONSIDER = "reconsider"
INPUT_SUSPECTED_VIOLATION = "suspected-violation"
#: S-NEXT-u3-followup (premise-check design D6): a routed lesson a premise of
#: its own moved for. The one constant every producer of this kind and the
#: premise units that build on it (U4's brief, U8's placement premises) name.
INPUT_PREMISE_MOVED = "premise-moved"
INPUT_KINDS = (INPUT_LESSON, INPUT_RECONSIDER, INPUT_SUSPECTED_VIOLATION, INPUT_PREMISE_MOVED)

#: Design D7.5: at most this many ``premise-moved`` inputs in one run, oldest
#: first; the rest wait for the next run (the backlog carries over).
PREMISE_MOVED_PER_RUN = 10

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
#: The ``<where>`` of a subagent line's origin, as the session miner writes
#: it: ``<session>/subagents/agent-<id>.jsonl`` (its line numbers are that
#: log's own).
_SUBAGENT_WHERE_RE = re.compile(r"^([^/\s]+)/(subagents/agent-[^/\s]+\.jsonl)$")


def _resolve_origin(where: str, line: int, roots: Sequence[Path], *, quote: str | None = None,
                    uuid: str | None = None) -> refs.Ref:
    """``refs.resolve`` for an origin's ``<where>`` and line: a session id,
    or a session's subagent log (:data:`_SUBAGENT_WHERE_RE`)."""
    sub = _SUBAGENT_WHERE_RE.match(where)
    if sub:
        return refs.resolve(sub.group(1), line, uuid, quote=quote, subagent_file=sub.group(2), roots=roots)
    return refs.resolve(where, line, uuid, quote=quote, roots=roots)
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


def refresh_index(home: Path, *, copy_to: Path | None = None) -> tuple[LessonIndex | None, dict]:
    """Bring the lesson index up to date (incremental) and return it open,
    with what the run record says about it. Never raises: an index that
    cannot be built is ``None`` and ``mode: unavailable`` says why. With no
    embedding key the build is word search only (``mode: lexical-only``).

    ``copy_to`` (the miner's preview): copy the index into that folder
    first and refresh the copy, so the live index is never written; with
    no live index, the copy is built there from scratch."""
    try:
        if copy_to is not None:
            from .index.store import index_path
            from .mining.engine import copy_sqlite

            index = LessonIndex.open_at(copy_sqlite(index_path(home), copy_to), home)
        else:
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


# ----------------------------------------------- premise-moved (U3, S-NEXT-u3-followup)


def premises_enabled(home: Path) -> bool:
    """Whether the premise check is on (design D12, as the user changed it on
    2026-10-30: ``premises.enabled`` is TRUE unless set false). The setting
    belongs to the sweep's unit (U2), which registers it as a tier C switch
    (agents never set it); until it is registered this reads the code default,
    on, so the one thing U3 does -- offer a lesson whose follow-up closed
    after its last decision -- works from landing with no human step."""
    from . import settings  # late: settings is a registry module, not an input

    try:
        setting = settings.by_name("premises.enabled")
    except KeyError:
        return True
    value, _source = settings.resolve_setting(home, setting)
    return bool(value)


def _done_day(value: object) -> str:
    """A follow-up's ``done_at`` as the day it names (``YYYY-MM-DD``): a date
    value from hand-edited YAML and its text give the same day."""
    when = chrono.to_dt(value)
    return when.date().isoformat() if when is not None else str(value or "")


def premise_moved_version(
    *,
    followup_done: Mapping[str, Any] | None = None,
    moved: Iterable[Sequence[str]] = (),
) -> str:
    """The identity of a ``premise-moved`` input (02 section 3a.10.7): a hash
    of what moved, ``premise:<12 hex>``. The closed follow-up (its action,
    gate, notes and ``done_at``) and, when the premise sweep adds them, the
    sorted moved-premise tuples. A run that decided this identity (applied,
    parked, refused, abandoned) is never offered it again; a follow-up
    closed again with other words, or a premise that moves again, is a new
    version. The same pattern as :func:`fires_version`. U3 passes
    ``followup_done=``.

    S-NEXT-u4-steward passes ``(premise id, current value hash, baseline
    observed_at)`` for each written premise (gate round 1 on c82e783,
    MINOR): with the value alone, a value that went A to B (decided, the
    baseline re-recorded as B), then back to A (decided), then to B again
    made the first input's version once more, already decided, and the
    third move was never offered. Every decision that keeps a premise
    re-records its baseline at a new time, so the third move is a new
    version; a park or a refusal leaves the baseline, and so the version,
    as it was. A two-element pair hashes exactly as before.

    S-NEXT-u8-placement passes ``(premise id, failing value hash, basis)``
    for each placement premise (fix round 2): the basis names what the
    failure is a failure of, so a reroute or a restore makes the same
    failing value, seen again, a new version
    (:func:`placement_moves`)."""
    block = None
    if followup_done is not None:
        block = {
            key: str(followup_done.get(key) or "")
            for key in ("action", "unblocks_on", "note", "done_at", "done_note")
        }
    pairs = sorted([str(part) for part in entry] for entry in moved)
    blob = json.dumps({"followup": block, "moved": pairs}, sort_keys=True)
    return "premise:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


#: The case outcomes that placed, moved, rewrote or retired a lesson: what
#: counts as a decision of it when asking whether a follow-up closed AFTER
#: the last one (02 section 3a.10.4, event 2). A case that deferred, parked
#: or only recorded a recurrence or dismissed a suspect (`no-action`) did
#: not look at what the lesson rests on.
_DECIDING_OUTCOMES = frozenset({"route", "reject", "retire", "replaced", "rehome", "revise"})


def last_decision(home: Path, record: Record) -> tuple[datetime | None, str]:
    """When a ROUTED lesson was last decided, from the ledger alone: ``(time,
    label)``, the newest of its ``routing.routed_at`` and the ``opened_at``
    of a case that is not parked, whose ``records`` name the lesson, and
    whose outcome placed, moved, rewrote or retired it
    (:data:`_DECIDING_OUTCOMES`). ``(None, "")`` when nothing is dated.

    Not counted, on purpose: a parked case, a ``no-action`` case (a dismissed
    suspect, a recorded recurrence) and a deferring case: none of them
    decided what the lesson rests on, and a closed follow-up must stay in
    front of the steward until one does. Neither a ``routing`` or
    ``reconsidered`` history entry (the case that wrote it is counted, at the
    time it froze its facts; the entry is dated when it APPLIED, which can be
    weeks later) nor ``last_confirmed`` (a person saw the rule working; that
    says nothing about the facts a follow-up closed on). A case whose file
    fails its freeze-hash check, or an index that cannot be read, contributes
    nothing: the answer then errs toward OFFERING the lesson."""
    from . import cases  # late: cases pulls the cache and the worker

    found: list[tuple[datetime, str]] = []
    routing = record.routing if isinstance(record.routing, dict) else {}
    routed = chrono.to_dt(routing.get("routed_at"))
    if routed is not None:
        found.append((routed, "routed_at"))
    try:
        rows = cases.list_cases(home, record_id=record.id, only_ok=True)
    except (cases.CaseError, OSError, ValueError):
        rows = []
    for row in rows:
        if row.get("kind") == "parked" or row.get("outcome") not in _DECIDING_OUTCOMES:
            continue
        when = chrono.to_dt(row.get("opened_at"))
        if when is not None:
            found.append((when, f"case:{row.get('case')}"))
    if not found:
        return None, ""
    return max(found, key=lambda item: item[0])


@dataclass(frozen=True)
class MovedFollowup:
    """One routed lesson whose follow-up was closed after it was last decided."""

    record_id: str
    done: dict
    done_on: date
    decided_at: datetime | None
    decided_by: str


def _followup_is_open(home: Path, record: Record) -> MovedFollowup | None:
    """The lesson as a :class:`MovedFollowup` when its closed follow-up is
    not earlier than the day of its last decision, else ``None``. The one
    test :func:`moved_followups` and :func:`open_followup_ids` share."""
    done = record.follow_up_done or {}
    done_when = chrono.to_dt(done.get("done_at"))
    if done_when is None:
        return None
    decided_at, decided_by = last_decision(home, record)
    if decided_at is not None and decided_at.date() > done_when.date():
        return None
    return MovedFollowup(record.id, done, done_when.date(), decided_at, decided_by)


def moved_followups(home: Path) -> list[MovedFollowup]:
    """Every ROUTED lesson whose ``follow_up_done.done_at`` is not earlier
    than the day it was last decided (:func:`last_decision`), oldest closing
    first. This ONE predicate is both the live trigger (``followup-done`` on
    a lesson) and the one-time pass for follow-ups closed before the check
    existed: today it names `lrn-9b4250f5` (closed 2026-10-29, last decided
    2026-09-22) and not `lrn-25968266` (closed 2026-07-17, a case decided
    it later).

    ``done_at`` is a DATE (the verb writes the day), so the comparison is by
    day, and the same day counts as after: a lesson decided and closed on one
    day is offered once rather than missed. The input's own version
    (:func:`premise_moved_version`) keeps it from being offered twice.

    Only a case that decided what the lesson says takes the lesson out of
    this list (:func:`last_decision`): a suspected-violation case that
    dismissed its events, a recurrence case and a parked case leave it
    offered, because the method gives them no authority to narrow or retire a
    placed lesson. A brief that reaches the lesson while the follow-up is
    undecided still shows it (:func:`open_followup_ids`), as context."""
    from . import ledger_ops  # late: ledger_ops imports far more

    out = [
        item for item in
        (_followup_is_open(home, record) for record in ledger_ops.closed_followups(home))
        if item is not None
    ]
    out.sort(key=lambda item: (item.done_on, item.record_id))
    return out


# --------------------------------- moved premises (U4, S-NEXT-u4-steward)
#
# 02 §3a.10.4 events 1 and 3: a WRITTEN premise of a placed lesson moved.
# The daily sweep (U2, `premise_sweep`) is the one judge of that: it keeps
# the observations and its :func:`premise_sweep.confirmed_moves` says which
# moves count -- a probe premise that fails its `holds_if` against the
# recorded baseline on two sweeps in a row made after that baseline, the
# two agreeing on the value; a `contradicts-claim` baseline from the first
# sweep after it was written; a `ledger` premise on first sight. This
# module reads that answer and never re-judges the cache: one debounce,
# one reader (gate round 1 on c82e783, BLOCKER).
#
# What it adds on top is the steward's own rate rule (design D7.5, 02
# §3a.10.5 (5)): a move a probe triggers waits until the premise was
# decided at least seven days ago. A `ledger` or `contradicts-claim` move
# does not wait. The placement premises (`@reach`, `@writable`, `@intact`)
# the sweep also confirms are U8's steward half and are left out here.
#
# `unavailable` never makes a move (`premises.verdict`); three in a row is a
# broken probe (:func:`broken_probes`), which every brief of the lesson
# shows and which is never an input by itself.

#: Design D7.5: a re-decision a probe triggers waits until the premise was
#: decided (written or re-baselined) at least this many days ago. Follow-up,
#: ledger and `contradicts-claim` events do not wait.
PROBE_REDECIDE_DAYS = 7


def probe_words(probe: object) -> str:
    """A probe as one short line for a brief: its kind and its fields."""
    if not isinstance(probe, Mapping):
        return "no probe"
    fields = " ".join(
        f"{key}={_one_line(value)}" for key, value in probe.items() if key != "kind"
    )
    return f"{probe.get('kind')} {fields}".strip()


@dataclass(frozen=True)
class PremiseMoves:
    """What moved for one placed lesson's written premises: ``items`` (the
    input's ``moved`` entries, ``source: premise``) and ``since`` (when the
    oldest move was first seen, for the oldest-first order)."""

    record_id: str
    items: list[dict]
    since: str


def _premise_item(premise: Mapping[str, Any], move: Any) -> dict:
    """One ``moved`` entry (``source: premise``) from a confirmed
    :class:`premise_sweep.Movement`, as the brief and the run record carry
    it: claim, probe, recorded value and today's, all short and scan-clean
    (the sweep stores nothing else)."""
    baseline = premise.get("baseline") if isinstance(premise.get("baseline"), Mapping) else {}
    assert isinstance(baseline, Mapping)
    if move.kind == "ledger":
        how = "ledger"
    elif baseline.get("state") == "contradicts-claim":
        how = "contradicts-claim"
    else:
        how = "probe"
    item: dict = {
        "source": "premise",
        "premise": str(premise.get("id")),
        "how": how,
        "claim": _one_line(premise.get("claim")),
        "probe": probe_words(premise.get("probe")),
        "holds_if": str(premise.get("holds_if") or "changed"),
        "recorded": str(baseline.get("shown", "")),
        "recorded_state": str(baseline.get("state") or ""),
        "recorded_at": str(baseline.get("observed_at") or ""),
        "now": str(move.shown),
        "now_at": str(move.observed_at),
        "since": str(move.since),
        "value_sha": str(move.value_sha),
    }
    if premise.get("match") is not None:
        item["match"] = _one_line(premise.get("match"))
    return item


def _waits_a_week(premise: Mapping[str, Any], how: str, today: date) -> bool:
    """D7.5: a probe-triggered move of a premise decided less than
    :data:`PROBE_REDECIDE_DAYS` ago waits. A `ledger` move (an act by a
    person or a ledger verb) and a `contradicts-claim` baseline (the
    decision that wrote it asked for exactly this look) do not."""
    if how != "probe":
        return False
    decided = chrono.to_dt(premise.get("decided_at"))
    return decided is not None and (today - decided.date()).days < PROBE_REDECIDE_DAYS


def placed_with_premises(home: Path) -> list[tuple[Any, Record]]:
    """Every live placed lesson (`domain.is_canon_live`: routed, not
    superseded) that carries a non-empty ``premises`` list, with its bucket,
    in bucket and file order. It reads the file text first and parses only a
    file that names the field, because the steward's due check calls this
    on every scheduler tick (`premise_sweep.routed_lessons` parses every
    placed lesson)."""
    from . import domain
    from .ledger import discover_buckets
    from .records import RecordError

    out: list[tuple[Any, Record]] = []
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                if "\npremises:" not in path.read_text(encoding="utf-8"):
                    continue
                record = Record.from_path(path)
            except (RecordError, OSError, UnicodeDecodeError):
                continue
            if domain.is_canon_live(record) and record.premises:
                out.append((bucket, record))
    return out


def moved_premises(
    home: Path,
    *,
    today: date | None = None,
    placed: list[tuple[Any, Record]] | None = None,
    history: dict | None = None,
) -> dict[str, PremiseMoves]:
    """``record id -> PremiseMoves`` for every placed lesson one of whose
    written premises the sweep confirms moved
    (:func:`premise_sweep.confirmed_moves`), less the moves that wait a week
    (:func:`_waits_a_week`). Placement premises are not here (U8). Reads
    only; an empty or missing cache gives ``{}``. *placed* and *history*
    are for a caller that already read them."""
    from . import premise_sweep  # late: the sweep imports serve, serve the steward

    placed = placed if placed is not None else placed_with_premises(home)
    if not placed:
        return {}
    today = today or datetime.now(timezone.utc).date()
    moves = premise_sweep.confirmed_moves(home, placed=placed, history=history)
    by_record = {record.id: record for _bucket, record in placed}
    found: dict[str, list[dict]] = {}
    for move in moves:
        if move.kind not in (premise_sweep.KIND_PROBE, premise_sweep.KIND_LEDGER):
            continue  # a placement premise: U8's steward half
        record = by_record.get(move.record_id)
        premise = next(
            (p for p in (record.premises or []) if str(p.get("id")) == move.premise_id), None
        ) if record is not None else None
        if premise is None:
            continue
        item = _premise_item(premise, move)
        if _waits_a_week(premise, str(item["how"]), today):
            continue
        found.setdefault(move.record_id, []).append(item)
    return {
        rid: PremiseMoves(rid, items, min(str(item["since"]) for item in items))
        for rid, items in found.items()
    }


def broken_probes(
    home: Path,
    *,
    placed: list[tuple[Any, Record]] | None = None,
    history: dict | None = None,
) -> dict[str, list[dict]]:
    """``record id -> [{premise, probe, reason}, ...]``: the written probes
    the sweep saw `unavailable` on its last
    :data:`premise_sweep.BROKEN_PROBE_SWEEPS` sweeps in a row, under the
    premise's current question (02 §3a.10.5 (3); the same rule as
    :func:`premise_sweep.doctor_rows`). Every brief of the lesson shows
    them, whatever brought it to the steward, so the steward can fix or drop
    the probe with ``premises set``. Never an input by itself. Placement
    premises are never "broken" (02 §3a.10.3)."""
    from . import premise_sweep, premises

    placed = placed if placed is not None else placed_with_premises(home)
    if not placed:
        return {}
    if history is None:
        history = premise_sweep.read_history(premise_sweep.default_cache_dir(home))
    out: dict[str, list[dict]] = {}
    for _bucket, record in placed:
        for premise in record.premises or []:
            if premise.get("probe") is None:
                continue
            pid = str(premise.get("id"))
            sig = premise_sweep._premise_sig(premise)
            tail = [r for r in history.get((record.id, pid), []) if r.get("psha") == sig]
            tail = tail[-premise_sweep.BROKEN_PROBE_SWEEPS:]
            if len(tail) == premise_sweep.BROKEN_PROBE_SWEEPS and all(
                r.get("state") == premises.OBS_UNAVAILABLE for r in tail
            ):
                out.setdefault(record.id, []).append({
                    "premise": pid,
                    "probe": probe_words(premise.get("probe")),
                    "reason": _one_line(tail[-1].get("reason") or "unavailable"),
                })
    return out


def open_followup_ids(home: Path) -> set[str]:
    """The ids of the routed lessons whose closed follow-up is still
    undecided: :func:`moved_followups`, minus a lesson whose ``premise-moved``
    input for the follow-up as it stands was already decided by a committed
    steward run (applied, parked, refused or abandoned). Only these show the
    ``[closed follow-up]`` block in their other briefs: once the question
    was settled it is not put back in front of the steward on an unrelated
    input. Empty, and cheap, when no routed lesson has a closed follow-up."""
    found = moved_followups(home)
    if not found:
        return set()
    from . import steward  # late: steward imports this module

    terminal = steward._terminal_versions(home)
    return {
        item.record_id for item in found
        if (item.record_id, premise_moved_version(followup_done=item.done)) not in terminal
    }


# --------------------------- placement premises (U8, S-NEXT-u8-placement)
#
# 02 §3a.10.3: every placed lesson has up to three placement premises that
# code derives on each daily sweep and nobody writes -- `@reach` (does a
# session load the file it sits in), `@writable` (may self-learn still write
# there: not a file git tracks in a plain host) and `@intact` (is its managed
# block as self-learn left it). The sweep (`premise_sweep`) confirms one as
# moved when it failed on two sweeps running with the same failing value;
# this reads those confirmations and turns them into `premise-moved` movers
# (`source: placement`). Judged by their current state, so nothing is
# re-recorded when they are decided: the input's version (the failing
# state, and what it is a failure OF -- `basis`) is what keeps a decided
# failure from being offered again.

#: The placement premises the 7-day rule holds (02 §3a.10.5 (5)): they
#: follow values that can drift back and forth. `@intact` is a person's act,
#: and an edited block refuses every write to its file until decided.
_PLACEMENT_WAITS = frozenset({"@reach", "@writable"})


@dataclass(frozen=True)
class PlacementMoves:
    """The confirmed placement moves of one placed lesson: ``items`` (the
    brief's ``moved`` entries, ``source: placement``) and ``since`` (the
    oldest first-seen failure, for the oldest-first order)."""

    record_id: str
    items: list[dict]
    since: str


def _placement_item(move: Any, basis: str) -> dict:
    """One confirmed placement move as the input row and the brief carry
    it: the premise, the failing state's short words and value hash, what
    the failure is a failure of (`basis`, :func:`placement_moves`), when it
    was first and last seen failing, the sweep's note, and for `@intact` the
    managed target (`group`). Never the block's text: input rows are kept
    in the committed run record."""
    item: dict = {
        "source": "placement",
        "premise": move.premise_id,
        "claim": _one_line(move.claim),
        "now": _one_line(move.shown),
        "value_sha": move.value_sha,
        "basis": basis,
        "since": move.since,
        "now_at": move.observed_at,
    }
    if move.detail:
        item["detail"] = _one_line(move.detail)
    if move.group:
        item["group"] = str(move.group)
    return item


def _placed_record(home: Path, record_id: str) -> Record | None:
    """The lesson when it is still placed (routed, not superseded), else
    ``None``: the sweep's rows outlive a lesson retired since."""
    from .ledger_ops import find_record_path

    try:
        record = Record.from_path(find_record_path(home, record_id))
    except Exception:  # noqa: BLE001 -- missing, unreadable: not offered
        return None
    if record.status != "routed" or record.superseded_by:
        return None
    return record


def _intact_basis(home: Path, record_id: str, value_sha: str) -> str | None:
    """The `basis` of an `@intact` move (:func:`placement_moves`) while the
    lesson's managed block still fails `@intact` with the value the sweep
    confirmed, else ``None``. A block edited again since (a new input after
    two more sweeps) or put right by hand is not offered on the old evidence:
    the fold or restore would refuse it anyway (`verbs._require_confirmed_block`).
    Reads the block's bytes and its compile-record entry only (no rendering).

    Fix round 2 (gate MAJOR): the basis is the block's compile-record entry
    -- its write time, its writer and both hashes, hashed short (a full digest in the
    committed run record would trip the secret scan's hex rule). Every
    write of the block changes it, a restore (`no-action`, so
    :func:`last_decision` does not move) included; while the block stays
    edited nothing writes it (an edited block refuses every write), so an
    undecided or parked failure keeps its version. Without it a block put
    back by a restore and then removed again, or returned to an earlier
    edited state after a later write, had the very version the earlier
    decision closed, and was never offered again."""
    from . import compiled, premises, verbs  # late: verbs imports far more

    try:
        region = verbs.lesson_region(home, record_id, render=False)
        if premises.intact_value_sha(region.verdict, region.observed_sha) != value_sha:
            return None
        entry = compiled.entry_for(
            compiled.load_record(home, region.slug), region.key, region="managed"
        ) or {}
    except Exception:  # noqa: BLE001 -- unreadable now: not offered this run
        return None
    written = json.dumps(
        [str(entry.get(key) or "") for key in ("at", "by", "sha256", "based_on_sha256")]
    )
    return "entry:" + hashlib.sha256(written.encode("utf-8")).hexdigest()[:12]


def _routed_basis(record: Record) -> str:
    """The `basis` of an `@reach` or `@writable` move (:func:`placement_moves`):
    the placement the failure is about, named by ``routing.routed_at``.
    A route or reroute that lands rewrites it (`ledger_ops.reroute_record`), a
    park, a refusal or a `no-action` decision does not -- so a lesson moved
    to a place that fails in the same way is a new input (after the 7-day
    wait), and a failure decided where it is stays decided. Fix round 2
    (gate MAJOR): not :func:`last_decision`, which also counts the
    ``opened_at`` of a case whose line the ledger refused (the case stays
    in the index, superseded by its `ledger-refused` successor), so a
    refusal would have made a new version every night."""
    routing = record.routing if isinstance(record.routing, dict) else {}
    return f"routed:{routing.get('routed_at') or ''}"


def placement_moves(home: Path, *, today: date | None = None) -> dict[str, PlacementMoves]:
    """``record id -> PlacementMoves`` for every placed lesson whose
    placement premise the daily sweep confirmed as moved (02 §3a.10.3,
    §3a.10.4 (1)). Reads the sweep's cache first and parses only the lessons
    it names, so the steward's due check can ask on every scheduler tick.

    Left out: a lesson no longer placed; an `@reach` or `@writable` move on
    a lesson decided less than :data:`PROBE_REDECIDE_DAYS` days ago
    (:func:`last_decision`; 02 §3a.10.5 (5)); an `@intact` move whose block
    is no longer the one the sweep confirmed (:func:`_intact_basis`).

    Each item carries a `basis` (fix round 2): what the failure is a
    failure OF -- the placement (:func:`_routed_basis`) or the block's last
    write (:func:`_intact_basis`). It joins the input's version, so a
    decision that changed the placement or rewrote the block makes the same
    failing value, seen again, a new input."""
    from . import premise_sweep  # late: premise_sweep imports verbs

    try:
        moves = premise_sweep.confirmed_placement_moves(home)
    except Exception:  # noqa: BLE001 -- an unreadable cache is "nothing confirmed"
        return {}
    if not moves:
        return {}
    today = today or datetime.now(timezone.utc).date()
    by_record: dict[str, list[Any]] = {}
    for move in moves:
        by_record.setdefault(move.record_id, []).append(move)
    out: dict[str, PlacementMoves] = {}
    for record_id, found in sorted(by_record.items()):
        record = _placed_record(home, record_id)
        if record is None:
            continue
        decided: datetime | None = None
        if any(move.premise_id in _PLACEMENT_WAITS for move in found):
            decided, _label = last_decision(home, record)
        items: list[dict] = []
        for move in found:
            if move.premise_id in _PLACEMENT_WAITS and decided is not None and (
                today - decided.date()
            ).days < PROBE_REDECIDE_DAYS:
                continue  # D7.5: decided less than a week ago; it waits
            if move.premise_id == "@intact":
                basis = _intact_basis(home, record_id, move.value_sha)
                if basis is None:
                    continue
            else:
                basis = _routed_basis(record)
            items.append(_placement_item(move, basis))
        if items:
            out[record_id] = PlacementMoves(
                record_id, items, min(str(item["since"]) for item in items)
            )
    return out


def intact_group(row: Mapping[str, Any] | None) -> str | None:
    """The managed target of a `premise-moved` input's `@intact` mover, or
    ``None`` when the input carries none (02 §3a.10.3: the lessons of one
    block whose hand edits are decided together)."""
    if not row:
        return None
    for item in row.get("moved") or []:
        if (
            isinstance(item, Mapping) and item.get("source") == "placement"
            and item.get("premise") == "@intact" and item.get("group")
        ):
            return str(item["group"])
    return None


def intact_groups(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """``managed target -> [record ids]`` over a run's input rows, in row
    order: every `@intact` group the run offers."""
    out: dict[str, list[str]] = {}
    for row in rows:
        group = intact_group(row)
        if group is not None:
            out.setdefault(group, []).append(str(row.get("record")))
    return out


def keep_groups_together(
    plans: list["PacketPlan"], groups: Mapping[str, Sequence[str]]
) -> list["PacketPlan"]:
    """S-NEXT-u8-placement (02 §3a.10.3, "one region, one decision"): the
    lessons of one `@intact` group are decided in ONE case, so they must sit
    in one packet. Each group's members are moved into the packet that holds
    its first member, as unrelated members (relatedness did not put them
    there); a packet left empty is dropped. A packet may then exceed the
    size cap by the group's size -- deciding a block's edits apart would
    erase one with the other's re-render, which is worse."""
    plans = [
        PacketPlan(list(p.members), list(p.unrelated), list(p.links), dict(p.basis_counts))
        for p in plans
    ]
    for members in groups.values():
        if len(members) < 2:
            continue
        home_plan = next((p for p in plans if members[0] in p.members), None)
        if home_plan is None:
            continue
        for rid in members[1:]:
            if rid in home_plan.members:
                continue
            for plan in plans:
                if rid in plan.members:
                    plan.members.remove(rid)
                    if rid in plan.unrelated:
                        plan.unrelated.remove(rid)
                    plan.links = [
                        link for link in plan.links
                        if rid not in (link.get("a"), link.get("b"))
                    ]
            home_plan.members.append(rid)
            home_plan.unrelated.append(rid)
    return [plan for plan in plans if plan.members]


#: A closed follow-up's fields as the brief labels them, in reading order.
_FOLLOWUP_LABELS = (
    ("action", "what the follow-up asked for"),
    ("unblocks_on", "it was to be closed when"),
    ("note", "its note"),
    ("done_note", "the note it was closed with"),
)
_MOVED_FIELD_CHARS = 1_500
_WOULD_CHANGE_HEADING = "What would change this decision:"


def _cut(text: str, limit: int) -> str:
    """*text* cut to *limit* characters, whitespace untouched."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clip(text: object, limit: int = _MOVED_FIELD_CHARS) -> str:
    return _cut(_one_line(text), limit)


def _block_lines(record: Record, key: str) -> tuple[int, list[tuple[int, str]]] | None:
    """The record file's top-level ``<key>:`` block as ``(first line,
    [(file line, text), ...])`` so a case can cite it as a ledger ref with a
    line span, or ``None`` when the text has none."""
    lines = record.to_text().splitlines()
    for at, line in enumerate(lines):
        if line.rstrip() != f"{key}:":
            continue
        end = at + 1
        while end < len(lines) and lines[end][:1] in (" ", "\t"):
            end += 1
        return at + 1, [(n + 1, lines[n]) for n in range(at, end)]
    return None


def _done_block_lines(record: Record) -> tuple[int, list[tuple[int, str]]] | None:
    """The record file's ``follow_up_done:`` block (:func:`_block_lines`)."""
    return _block_lines(record, "follow_up_done")


def _cited_block(
    record: Record, key: str, label: str, *, path: str | None, head: str | None
) -> list[str]:
    """A record block with its file lines and the ledger ref to cite it by,
    as brief lines, or ``[]`` when the record has no such block."""
    block = _block_lines(record, key)
    if block is None:
        return []
    first, body = block
    span = f"L{first}-{body[-1][0]}" if len(body) > 1 else f"L{first}"
    cite = f"ledger@{(head or 'HEAD')[:12]}:{path}#{span}" if path else f"the record's {span}"
    out = [f"  {label} ({cite}):"]
    # indentation kept: it is the block's structure; only a very long line is cut
    out += [f"    L{n}: {_cut(text, 400)}" for n, text in body]
    return out


def _followup_fact_lines(item: Mapping[str, Any]) -> list[str]:
    """The closed follow-up's facts, one labelled line each."""
    lines = [f"  the follow-up on this lesson was closed on {item.get('done_at')}"]
    for key, label in _FOLLOWUP_LABELS:
        if item.get(key):
            lines.append(f"    {label}: {_clip(item[key])}")
    return lines


def _followup_cite_lines(record: Record, *, path: str | None, head: str | None) -> list[str]:
    """The closed follow-up as the record file holds it, line by line, with
    the ledger ref a case cites (empty when the file has no such block)."""
    block = _done_block_lines(record)
    if block is None:
        return []
    first, body = block
    span = f"L{first}-{body[-1][0]}" if len(body) > 1 else f"L{first}"
    cite = f"ledger@{(head or 'HEAD')[:12]}:{path}#{span}" if path else f"the record's {span}"
    return [
        f"  the closed follow-up as the record holds it ({cite}):",
        # indentation kept: it is the block's structure; only a very long line is cut
        *(f"    L{n}: {_cut(text, 400)}" for n, text in body),
    ]


def render_closed_followup(record: Record, *, path: str | None, head: str | None) -> str:
    """What a brief of a ROUTED lesson shows while its closed follow-up is
    undecided (:func:`open_followup_ids`): the facts and the record's own
    lines to cite, or ``""`` when the lesson has no closed follow-up. The
    ``premise-moved`` brief carries the same facts in its own block
    (:func:`render_premise_moved`) and does not use this. It is context for
    a decision about something else (a dismissed suspect, a recurrence): it
    is not what keeps the lesson in front of the steward, and it gives that
    decision no new authority over the lesson (:func:`last_decision`)."""
    done = record.follow_up_done
    if not isinstance(done, Mapping) or not done:
        return ""
    lines = [
        "[closed follow-up] this lesson was placed while it waited on a condition, and "
        "its follow-up has since been closed; what it waited on has happened. This is "
        "context for this decision; the lesson itself comes to you again on its own "
        "`premise-moved` input, which is where a sentence that rested on that wait is "
        "checked."
    ]
    lines += _followup_fact_lines({**done, "done_at": _done_day(done.get("done_at"))})
    lines += _followup_cite_lines(record, path=path, head=head)
    return "\n".join(lines)


def _would_change_lines(home: Path, case_id: str) -> list[str]:
    """The bullets under "What would change this decision:" in a case's
    Decision section (the one place a case says what its own facts would
    have to do for it to be wrong), or ``[]``. Only that list is shown, never
    the rest of the decision."""
    from . import cases

    try:
        view = cases.show(home, case_id, evidence_only=False)
    except (cases.CaseError, OSError):
        return []
    lines = view.sections.get("Decision", "").splitlines()
    if _WOULD_CHANGE_HEADING not in lines:
        return []
    out: list[str] = []
    for line in lines[lines.index(_WOULD_CHANGE_HEADING) + 1:]:
        if not line.startswith("- "):
            break
        out.append(line[2:].strip())
    return out


#: At most this many covering cases besides the predecessor have their
#: "what would change" lines shown (newest first).
_OTHER_COVERING_CASES = 3


def _other_covering_cases(home: Path, record_id: str, predecessor: object) -> list[str]:
    """The cases that cover *record_id*, are not superseded and are not
    *predecessor*, newest first (02 §3a.10.7: the brief shows the "what
    would change" lines of every covering case still standing, so a case
    that only recorded something never hides the placing case's
    prediction)."""
    from . import cases

    try:
        rows = cases.list_cases(home, record_id=record_id, only_ok=True)
    except (cases.CaseError, OSError, ValueError):
        return []
    found = sorted(
        (
            (str(row.get("opened_at") or ""), str(row.get("case")))
            for row in rows
            if isinstance(row.get("case"), str) and not row.get("superseded_by")
            and row.get("case") != predecessor
        ),
        reverse=True,
    )
    return [case_id for _opened, case_id in found[:_OTHER_COVERING_CASES]]


#: How each way a written premise moves reads in the brief.
_PREMISE_HOW = {
    "probe": "the daily check saw it change on two checks in a row",
    "ledger": "the ledger entry it rests on changed",
    "contradicts-claim": "its first recorded value already said the claim was false",
}


def _premise_item_lines(item: Mapping[str, Any]) -> list[str]:
    """A ``source: premise`` mover as brief lines."""
    how = _PREMISE_HOW.get(str(item.get("how")), str(item.get("how")))
    holds = str(item.get("holds_if") or "changed")
    judged = f"holds_if {holds}" + (f", match {_clip(item.get('match'), 200)!r}" if item.get("match") else "")
    return [
        f"  premise {item.get('premise')} moved: {how}",
        f"    claim: {_clip(item.get('claim'), 300)}",
        f"    probe: {_clip(item.get('probe'), 300)} ({judged})",
        f"    recorded value: {item.get('recorded')!r} ({item.get('recorded_state') or 'holds'}, "
        f"seen {item.get('recorded_at')})",
        f"    value now: {item.get('now')!r} (seen {item.get('now_at')}; first seen changed "
        f"{item.get('since')})",
    ]


def _lesson_premise_lines(record: Record) -> list[str]:
    """Every premise the lesson records, as one line each -- a premise with
    no probe (a behaviour) included, since this is where it is read."""
    out: list[str] = []
    for premise in record.premises or []:
        probe = premise.get("probe")
        what = "no probe (a behaviour, written down)" if probe is None else probe_words(probe)
        out.append(f"  {premise.get('id')}: {_clip(premise.get('claim'), 300)} [{what}]")
    return out


def _decide_lines(
    predecessor: object, moved: Sequence[Mapping[str, Any]], followup_only: bool
) -> list[str]:
    """The brief's [how to decide it] block: which case kind, the outcomes
    02 section 3a.10.7 and method section 17 give this input (`no-action`,
    `replace`, `retire`, `route`, park; never `reject`), and what a
    decision that keeps the lesson owes each moved premise."""
    if predecessor:
        kind = (
            "a `kind: reconsider` case (the runner fills in `supersedes: "
            f"{predecessor}`)"
        )
    else:
        kind = (
            "no case covers this lesson, so decide it in a `kind: resolution` case that "
            "supersedes nothing"
        )
    out = [f"[how to decide it] {kind}, with the lesson's lines on its sheet:"]
    if followup_only:
        out.append(
            "  - every sentence still true: outcome `no-action` with one `note` item saying "
            "which sentence you checked against which cited line;"
        )
    else:
        # A premise judged by its claim (`holds_if` other than `changed`)
        # that moved has a claim that is false now: re-recording it would
        # record a false claim, so the runner refuses that rebaseline and the
        # premise is rewritten or dropped with `set` instead.
        changed = [str(m.get("premise")) for m in moved if m.get("holds_if") in (None, "", "changed")]
        claimed = [str(m.get("premise")) for m in moved if str(m.get("premise")) not in changed]
        owed = []
        if changed:
            owed.append(f"`action: rebaseline`, `ids: [{', '.join(changed)}]`")
        if claimed:
            owed.append(
                f"`action: set` with a list in which {', '.join(claimed)} says what is true now, "
                "or is dropped (its claim is false now, and the runner refuses to rebaseline a "
                "false claim)"
            )
        out.append(
            "  - every sentence still true: outcome `no-action` with a `premises` line "
            + " and ".join(owed)
            + " (every moved premise the lesson keeps; the runner refuses a `no-action` case "
            "that leaves one out, because the same change would come back every night);"
        )
    out.append(
        "  - a sentence now false but the lesson's point stands: a `replace` line that narrows "
        "or corrects the words, every idea of the old text in `decision.rewrite`"
        + (
            "" if followup_only else
            "; the new lesson carries this lesson's premises, so when they change too, put a "
            "`premises` line on this lesson BEFORE the `replace` line (a moved premise left as "
            "it is brings the new lesson back to you)"
        )
        + ";"
    )
    out.append(
        "  - all of it false now, or something else now covers it: `retire` with `covered_by`;"
    )
    out.append(
        "  - it no longer belongs where it sits: `route` with an explicit `dest` (applied as a "
        "reroute: the old placement leaves, the new one is written);"
    )
    if not followup_only:
        out.append(
            "  - the probe is wrong, not the lesson: fix or drop it with a `premises` line "
            "`action: set` (the whole list), and decide the lesson on what you find;"
        )
    out.append(
        "  - you cannot tell: park it (`authority-unclear`) with your tentative answer."
    )
    out.append(
        "  Narrowing, rewriting, moving or retiring this placed lesson is yours here without "
        "the overseer (method section 17); merging it with another placed lesson is not."
    )
    return out


#: S-NEXT-u8-placement: what each placement premise says when it fails, in
#: the brief.
_PLACEMENT_WORDS = {
    "@reach": "no session loads the file this lesson sits in any more",
    "@writable": "self-learn may no longer write where this lesson sits",
    "@intact": "a person edited this lesson's managed block by hand",
}
#: A managed block longer than this is shown as its diff only.
_REGION_SHOWN_CHARS = 6_000
#: At most this many diff lines in a brief.
_REGION_DIFF_LINES = 150
#: What stands in for a line the secret scan matched (never shown, and the
#: case need not quote it: its evidence is scanned too).
WITHHELD_LINE = "[withheld: the line matched the secret scan]"


def quotable_line(line: str) -> str:
    """S-NEXT-u8-placement, fix round 1: the words of a hand-written line a
    case's evidence must quote. A line that starts with `## ` cannot start a
    quoted line (`cases.split_runner_evidence` drops that evidence item
    before the case is recorded), so for it the words after `## ` are asked
    for; every other line is asked for as it stands."""
    return line[3:] if line.startswith("## ") else line


def scan_hit(line: str) -> bool:
    from .scan import scan

    return bool(scan(line))


#: The most of one block line a brief shows.
_SHOWN_LINE_CHARS = 400


def _shown_line(line: str) -> str:
    return WITHHELD_LINE if scan_hit(line) else _cut(line, _SHOWN_LINE_CHARS)


def _quoted_line(line: str, target: object) -> str:
    """A line a person wrote, as the brief lists it for the case to quote.
    Fix round 2 (gate NIT): a line longer than the brief shows is cut, and
    the case must still quote it whole, so the brief says it was cut and
    where to Read it."""
    shown = _shown_line(line)
    if shown == WITHHELD_LINE or len(line) <= _SHOWN_LINE_CHARS:
        return shown
    return (
        f"{shown}  [cut: this line has {len(line)} characters; Read it whole in {target} "
        "and quote it whole]"
    )


def _intact_region_lines(home: Path, record_id: str) -> list[str]:
    """The `@intact` part of the brief (02 §3a.10.7): the lines a person
    wrote that the case must quote, the diff from the ledger's text to the
    block on disk, and both blocks in full when they are short. Read now,
    from disk; never kept in the input row."""
    from . import verbs  # late: verbs imports far more

    try:
        region = verbs.lesson_region(home, record_id)
    except Exception as exc:  # noqa: BLE001 -- the brief says so and goes on
        return [f"    the block cannot be read now ({_clip(exc, 300)})"]
    out = [f"    the block: {region.key} (the compile record says it is {region.verdict})"]
    edited = verbs.edited_region_lines(region)
    if region.observed is None:
        out.append("    the block is gone from the file: nothing a person wrote is left in it")
    elif edited:
        out.append(
            "    the lines a person wrote there, which the case's `evidence` must quote word for "
            f"word (one item, ref `{region.target}#managed`), so they survive whatever you decide:"
        )
        out += [f"      | {_quoted_line(line, region.target)}" for line in edited]
        if any(quotable_line(line) != line for line in edited):
            out.append(
                "    (a line that starts with `## ` is quoted by its words after the `## `: a "
                "quoted line that starts with `## ` is dropped from the case's evidence)"
            )
    else:
        out.append("    no line was added or changed: the edit only removed or reordered lines")
    diff = verbs.region_diff(region)
    if diff:
        out.append("    the diff (- the ledger's text, + the block on disk):")
        shown = diff[:_REGION_DIFF_LINES]
        out += [f"      {_shown_line(line)}" for line in shown]
        if len(diff) > len(shown):
            out.append(f"      … {len(diff) - len(shown)} more diff lines")
    shown_blocks = (
        ("the block on disk", region.observed),
        ("the block the ledger renders now", region.expected),
    )
    for label, data in shown_blocks:
        if data is None:
            continue
        text = data.decode("utf-8", errors="replace")
        if len(text) > _REGION_SHOWN_CHARS:
            out.append(f"    {label}: {len(text)} characters, shown by its diff only")
            continue
        out.append(f"    {label}:")
        out += [f"      {_shown_line(line)}" for line in text.splitlines()]
    return out


def _placement_item_lines(home: Path, record: Record, item: Mapping[str, Any]) -> list[str]:
    """A ``source: placement`` mover as brief lines (S-NEXT-u8-placement)."""
    pid = str(item.get("premise"))
    lines = [
        f"  placement {pid} moved: {_PLACEMENT_WORDS.get(pid, 'its placement failed')} "
        f"(failing on two daily checks running; first seen {item.get('since')}, last "
        f"{item.get('now_at')})",
        f"    claim: {_clip(item.get('claim'), 300)}",
        f"    what the check saw: {_clip(item.get('now'), 300) or '(not shown)'}",
    ]
    if item.get("detail"):
        lines.append(f"    detail: {_clip(item.get('detail'), 400)}")
    if pid == "@intact":
        members = [str(m) for m in item.get("members") or [] if str(m) != record.id]
        if members:
            lines.append(
                f"    other lessons of this block with a hand edit, decided in the SAME case: "
                f"{', '.join(members)}"
            )
        lines += _intact_region_lines(home, record.id)
    return lines


def _placement_decide_lines(
    predecessor: object, placement_ids: list[str], *, cases_differ: bool = False
) -> list[str]:
    """The [how to decide it] lines for a placement mover (02 §3a.10.7).
    *cases_differ*: the lessons of this block's `@intact` group are not all
    covered by one case, so their one case is a `kind: resolution` case
    (fix round 1, gate MAJOR 1; `steward._split_intact_members`)."""
    case = (
        f"a `kind: reconsider` case (the runner fills in `supersedes: {predecessor}`)"
        if predecessor else
        "a `kind: resolution` case that supersedes nothing (no case covers this lesson)"
    )
    out: list[str] = []
    if "@intact" in placement_ids:
        # Fix round 2 (gate MINOR): a mixed group (one lesson covered, one
        # not) records with `supersedes` filled in by the runner
        # (`steward._predecessor_fill`: one earlier case among its records),
        # so the words say "write none yourself", not "it has none".
        edit_case = (
            "ONE `kind: resolution` case (write no `supersedes` yourself: the lessons of this "
            "block were not all placed by one case, and a reconsider case supersedes only one; "
            "the runner fills one in only when exactly one earlier case covers any of them)"
            if cases_differ else case
        )
        out += [
            f"[how to decide the hand edit] in {edit_case} naming every lesson of the block listed "
            "above in `records`, each with its own line; a case that leaves the block as it is "
            "(no fold or restore line for a lesson of it) is not an answer, because an edited "
            "block refuses every later write to its file:",
            "  - the edit is consistent with the lesson (usually a correction): fold it into "
            "the lesson -- a `replace` line with `adopt_region: true` whose new text says what "
            "the edit says, every idea of the old text in `decision.rewrite` (outcome "
            "`replaced`);",
            "  - the edit contradicts the lesson, or is not a change to a lesson: put the "
            "ledger's text back -- a `premises` line `action: restore-region` (the lesson's "
            "text stands, so the case's outcome is `no-action`; the restore line is the "
            "answer);",
            "  - fold one lesson and restore another of the same block in the one case if they "
            "differ; quote every line a person wrote (listed above) in the case's `evidence`, "
            "whichever you choose: the block is rewritten from the ledger either way;",
            "  - you cannot tell: park it.",
        ]
    if {"@reach", "@writable"} & set(placement_ids):
        # S-NEXT-u4-steward's fix round 1 lets a resolution case move a
        # placed lesson no case covers (`batch._resolution_reroute_for`), so
        # both shapes move it with a `route` line.
        move = "a `route` line with the `dest` it should have (applied as a reroute)"
        out += [
            f"[how to decide where it sits] in {case}:",
            f"  - the lesson should live where a session loads it, or where self-learn may "
            f"write (for a file git tracks in a plain host, usually `claude-md:local`): {move};"
            " taking it out of a file git tracks leaves an uncommitted change there for a "
            "person, which is expected;",
            "  - nothing needs the lesson any more: `retire` with `covered_by`;",
            "  - you cannot tell, or a person placed it (the runner refuses moving a person's "
            "lesson): park it with your tentative answer.",
        ]
    out.append(
        "  Moving, narrowing, rewriting or retiring this placed lesson is yours here without "
        "the overseer (method section 17); merging it with another placed lesson is not."
    )
    return out


def render_premise_moved(
    home: Path, record: Record, row: Mapping[str, Any], *, path: str | None, head: str | None
) -> tuple[str, dict]:
    """The part of a ``premise-moved`` brief that is not the lesson itself:
    what moved -- a closed follow-up (U3), a written premise (U4: its claim,
    probe, recorded value and today's), or a mover another unit adds (U8's
    placement premises), each with the record lines to cite -- its `env`
    pins, what the cases that cover it said would change it, and how to
    decide. The lesson's premises and any broken probe are in the lesson
    block (:func:`render_record`), as on every brief. Code never judges
    whether the lesson is still true: the brief gives the steward the facts
    and the deciding case's own prediction. The decision rules are those of
    02 section 3a.10.7 and steward-method section 17."""
    lines = [
        "[what moved] something this lesson rested on has changed since it was last "
        "decided; the facts below are recorded, not guessed"
    ]
    items = [m for m in row.get("moved") or [] if isinstance(m, dict)]
    followups = [m for m in items if m.get("source") == "follow-up-done"]
    written = [m for m in items if m.get("source") == "premise"]
    for item in followups:
        lines += _followup_fact_lines(item)
    for item in written:
        lines += _premise_item_lines(item)
    placed = [m for m in items if m.get("source") == "placement"]
    for item in placed:
        lines += _placement_item_lines(home, record, item)
    for item in items:
        if item.get("source") in ("follow-up-done", "premise", "placement"):
            continue
        # A mover no unit has given its own lines: shown as recorded.
        detail = ", ".join(
            f"{key}: {_clip(value, 400)}" for key, value in sorted(item.items()) if key != "source"
        )
        lines.append(f"  moved ({item.get('source') or 'unknown source'}): {detail}")
    if followups:
        lines += _followup_cite_lines(record, path=path, head=head)
    if record.premises:
        # each premise is listed with the lesson itself (`render_record`)
        lines += _cited_block(
            record, "premises", "the premises as the record holds them", path=path, head=head,
        )
    if record.env:
        pins = ", ".join(f"{key} {value}" for key, value in sorted(record.env.items()))
        lines.append(
            f"[tool versions when it was taught] {_clip(pins, 600)} (context only: a changed "
            "version is not itself a reason to change the lesson)"
        )
    predecessor = row.get("predecessor")
    wanted = _would_change_lines(home, str(predecessor)) if predecessor else []
    if wanted:
        lines.append(f"[what the deciding case ({predecessor}) said would change it]")
        lines += [f"  - {_clip(w, 600)}" for w in wanted]
    for case_id in _other_covering_cases(home, record.id, predecessor):
        others = _would_change_lines(home, case_id)
        if others:
            lines.append(f"[what another case that covers it ({case_id}) said would change it]")
            lines += [f"  - {_clip(w, 600)}" for w in others]
    if written or followups or not placed:
        lines += _decide_lines(predecessor, written, followup_only=not written)
    if placed:
        lines += _placement_decide_lines(
            predecessor, [str(m.get("premise")) for m in placed],
            cases_differ=any(m.get("cases_differ") for m in placed),
        )
    stats = {"items": 0, "excerpted": 0, "excerpt_chars": 0, "verdicts": {}, "moved": len(items)}
    return "\n".join(lines), stats


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


def render_record(
    record: Record, *, path: str | None, head: str | None, bucket: str,
    closed_followup: bool = False, broken: Sequence[Mapping[str, Any]] = (),
) -> str:
    """The lesson as the steward reads it: its facts on one line, then its
    lesson sections with their file lines (citable as
    ``ledger@<commit>:<path>#L<a>-<b>``), then, when its follow-up was
    closed and not yet decided, what that says
    (:func:`render_closed_followup`; ``closed_followup`` is off by default and
    for a ``premise-moved`` brief, which carries the same facts in its own
    block; :func:`build_briefs` turns it on for a lesson in
    :func:`open_followup_ids`).

    S-NEXT-u4-steward (02 section 3a.10.2 and 3a.10.5 (3)): every brief, of
    any input kind, lists the lesson's premises (a premise with no probe, a
    behaviour, is read nowhere else) and *broken*, the probes the sweep saw
    `unavailable` three times running (:func:`broken_probes`), so the
    steward fixes or drops them whenever the lesson comes up."""
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
    # S-NEXT-u4-steward (02 §3a.10.2): what the lesson rests on, whatever
    # brought it here -- a premise with no probe (a behaviour) is read
    # nowhere else.
    if record.premises == []:
        lines.append("  premises: none (decided: it rests on no fact about the machine)")
    elif record.premises:
        lines.append("  premises (what it rests on):")
        lines += [f"  {line}" for line in _lesson_premise_lines(record)]
    shown_broken = [b for b in broken if isinstance(b, Mapping)]
    if shown_broken:
        lines.append(
            "  [broken probes] the daily check could not observe these on its last three "
            "checks: fix or drop each with a `premises` line `action: set` (the whole list) "
            "in this decision's sheet"
        )
        lines += [
            f"    {b.get('premise')}: {_clip(b.get('probe'), 300)} ({_clip(b.get('reason'), 200)})"
            for b in shown_broken
        ]
    if closed_followup:
        shown = render_closed_followup(record, path=path, head=head)
        if shown:
            lines.append(shown)
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


def _stored_quote(item: dict) -> str | None:
    quote = item.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        quote = item.get("verbatim")
    return quote if isinstance(quote, str) else None


def _cited_ref(item: dict, roots: Sequence[Path]) -> tuple[str, refs.Ref | None, str]:
    """``(what the record cites, the resolved ref or None, verdict if not resolvable)``."""
    quote = _stored_quote(item)
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
                    subagent_file=given.subagent_file, roots=roots, quote=quote,
                ), ""
            except (refs.RefError, OSError) as exc:
                return given.origin, None, f"{UNRESOLVABLE}:{exc}"
    source = item.get("source")
    origin = (item.get("origin") or (raw if isinstance(raw, str) else None)
              or (source.get("message_ref") if isinstance(source, dict) else None))
    m = _ORIGIN_RE.match(str(origin or "").strip())
    if not m:
        return str(origin or "(no pointer)"), None, NOT_A_TRANSCRIPT
    try:
        uuid = item.get("uuid")
        return m.group(0), _resolve_origin(m.group(1), int(m.group(2)), roots, quote=quote,
                                         uuid=uuid if isinstance(uuid, str) else None), ""
    except (refs.RefError, OSError, ValueError) as exc:
        return m.group(0), None, f"{UNRESOLVABLE}:{exc}"


def _check(item: dict, ref: refs.Ref, roots: Sequence[Path]) -> tuple[str, refs.Ref, str]:
    quote = _stored_quote(item)
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
        quote = _stored_quote(raw)
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
    from .miner import _OriginIndex

    origin_index = _OriginIndex(roots=roots)
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
        m = _ORIGIN_RE.match(origin_index.event(event, legacy_only=True).strip())
        if not m:
            lines.append("    the pointer is not a transcript line; nothing here checks it")
            continue
        try:
            moment = event.get("moment")
            ref = _resolve_origin(m.group(1), int(m.group(2)), roots,
                                  uuid=moment if isinstance(moment, str) else None)
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

    # The routed lessons whose closed follow-up is still undecided: their
    # briefs of any kind but `premise-moved` show it as context.
    undecided = open_followup_ids(home)
    # S-NEXT-u4-steward: probes broken three sweeps running, shown on every
    # brief of their lesson whatever its input kind (02 section 3a.10.5 (3)).
    broken = broken_probes(home)
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
        # S-88: a lesson input carries a reason only when it is a deferred
        # lesson no case covers (`steward._deferred_unresolved`): its
        # deferral came due, and the card says how it is decided.
        if kind in (INPUT_RECONSIDER, INPUT_LESSON, INPUT_PREMISE_MOVED) and row.get("reason"):
            parts.append(f"[why it is back] {_one_line(row['reason'])}")
        parts.append(render_record(
            record, path=rel, head=head, bucket=_bucket_of(home, path),
            closed_followup=kind != INPUT_PREMISE_MOVED and rid in undecided,
            broken=broken.get(rid, ()),
        ))
        if kind == INPUT_SUSPECTED_VIOLATION:
            events = [e for e in row.get("events") or [] if isinstance(e, dict)]
            text, pack_stats = fire_pack(events, roots=resolved_roots, budget=share)
            parts.append(text)
        elif kind == INPUT_PREMISE_MOVED:
            # What moved is the evidence: the lesson's own transcript pack
            # says what it was taught from, not what has changed since.
            text, pack_stats = render_premise_moved(home, record, row, path=rel, head=head)
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
