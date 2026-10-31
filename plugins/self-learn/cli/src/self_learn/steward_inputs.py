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
   later through the same kind (:func:`premise_moved_version`). The fifth,
   ``premise-extract`` (S-NEXT-u6-backfill, unit U6), is a ROUTED lesson
   with no ``premises`` field at all, offered so its premises get written
   (:func:`routed_without_premises`, :func:`extract_rank`): the backfill of
   the lessons placed before premises existed, and the safety net for a
   route that wrote none.
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
from typing import Any, Iterable, Mapping, Sequence, cast

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
    "INPUT_PREMISE_EXTRACT",
    "INPUT_KINDS",
    "PREMISE_EXTRACT_PER_RUN",
    "covering_cases",
    "extract_rank",
    "premise_backfill_per_night",
    "render_premise_extract",
    "routed_without_premises",
    "LessonBrief",
    "MovedFollowup",
    "PREMISE_MOVED_PER_RUN",
    "PacketPlan",
    "build_briefs",
    "fires_version",
    "last_decision",
    "moved_followups",
    "packet_stats",
    "plan_packets",
    "premise_moved_version",
    "premise_moves",
    "premises_enabled",
    "PremiseMoves",
    "confirmed_move",
    "moved_premises",
    "observations_path",
    "probe_words",
    "read_observations",
    "routed_with_premises",
    "refresh_index",
    "suspected_violations",
    "tool_reads",
]

INPUT_LESSON = "lesson"
INPUT_RECONSIDER = "reconsider"
INPUT_SUSPECTED_VIOLATION = "suspected-violation"
#: S-NEXT-u3-followup (premise-check design D6): a routed lesson a premise of
#: its own moved for. The one constant every producer of this kind and the
#: premise units that build on it (U4's brief, U8's placement premises) name.
INPUT_PREMISE_MOVED = "premise-moved"
#: S-NEXT-u6-backfill (premise-check design D10): a routed lesson with no
#: ``premises`` field, offered for its premises to be written (the backfill).
INPUT_PREMISE_EXTRACT = "premise-extract"
INPUT_KINDS = (
    INPUT_LESSON, INPUT_RECONSIDER, INPUT_SUSPECTED_VIOLATION, INPUT_PREMISE_MOVED,
    INPUT_PREMISE_EXTRACT,
)

#: Design D7.5: at most this many ``premise-moved`` inputs in one run, oldest
#: first; the rest wait for the next run (the backlog carries over).
PREMISE_MOVED_PER_RUN = 10
#: Design D10: the backfill offers at most this many lessons a night by
#: default; ``premises.backfill_per_night`` (tier C) is what a run reads
#: (:func:`premise_backfill_per_night`).
PREMISE_EXTRACT_PER_RUN = 10

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


def premise_moved_version(
    *,
    followup_done: Mapping[str, Any] | None = None,
    moved: Iterable[tuple[str, str]] = (),
) -> str:
    """The identity of a ``premise-moved`` input: a hash of what moved. The
    closed follow-up (its action, gate, notes and ``done_at``) and, when the
    premise sweep adds them, the ``(premise id, new value hash)`` pairs.
    A run that decided this identity (applied, parked, refused, abandoned)
    is never offered it again; a follow-up closed again, or a premise that
    moves again, is a new version. The same pattern as :func:`fires_version`."""
    block = None
    if followup_done is not None:
        block = {
            key: str(followup_done.get(key) or "")
            for key in ("action", "unblocks_on", "note", "done_at", "done_note")
        }
    pairs = sorted([str(pid), str(value)] for pid, value in moved)
    blob = json.dumps({"followup": block, "moved": pairs}, sort_keys=True)
    return "premise:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


#: The case outcomes that placed, moved, rewrote or retired a lesson: what
#: counts as "decided" when asking whether a follow-up closed AFTER the last
#: decision. A case that deferred, parked or only recorded a recurrence
#: (`no-action`) did not look at the lesson's premises.
_DECIDING_OUTCOMES = frozenset({"route", "reject", "retire", "replaced", "rehome", "revise"})
#: ... and the history entries a verb writes when a lesson's placement was
#: displaced or the overseer reconsidered it.
_DECIDING_HISTORY = frozenset({"routing", "reconsidered"})


def last_decision(home: Path, record: Record) -> tuple[datetime | None, str]:
    """When a ROUTED lesson was last decided, and by what evidence, from the
    ledger alone: ``(time, label)`` with the newest of its ``routed_at``, a
    ``routing`` or ``reconsidered`` history entry, a ``last_confirmed`` date
    (a person observed the rule working), and the ``opened_at`` of a case
    that placed, moved, rewrote or retired it (:data:`_DECIDING_OUTCOMES`).
    ``(None, "")`` when nothing is dated. A case index that cannot be read
    contributes nothing: the answer then errs toward OFFERING the lesson."""
    from . import cases  # late: cases pulls the cache and the worker

    found: list[tuple[datetime, str]] = []

    def add(value: object, label: str) -> None:
        when = chrono.to_dt(value)
        if when is not None:
            found.append((when, label))

    routing = record.routing if isinstance(record.routing, dict) else {}
    add(routing.get("routed_at"), "routed_at")
    for entry in record.history:
        if isinstance(entry, dict) and entry.get("event") in _DECIDING_HISTORY:
            add(entry.get("at"), f"history:{entry.get('event')}")
    add(record.last_confirmed, "last_confirmed")
    try:
        rows = cases.list_cases(home, record_id=record.id)
    except (cases.CaseError, OSError, ValueError):
        rows = []
    for row in rows:
        if row.get("kind") != "parked" and row.get("outcome") in _DECIDING_OUTCOMES:
            add(row.get("opened_at"), f"case:{row.get('case')}")
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
    (:func:`premise_moved_version`) keeps it from being offered twice."""
    from . import ledger_ops  # late: ledger_ops imports far more

    out: list[MovedFollowup] = []
    for record in ledger_ops.closed_followups(home):
        done = record.follow_up_done or {}
        done_when = chrono.to_dt(done.get("done_at"))
        if done_when is None:
            continue
        decided_at, decided_by = last_decision(home, record)
        if decided_at is not None and decided_at.date() > done_when.date():
            continue
        out.append(MovedFollowup(record.id, done, done_when.date(), decided_at, decided_by))
    out.sort(key=lambda item: (item.done_on, item.record_id))
    return out


# --------------------------------- moved premises (U4, S-NEXT-u4-steward)
#
# 02 §3a.10.4 events 1 and 3: a WRITTEN premise of a placed lesson moved.
# Three ways, each read here from the record and the cache, never by a model:
#
# * a probe premise the daily sweep (U2) saw fail its `holds_if` against the
#   recorded baseline on its last two observations, both made after that
#   baseline was recorded and agreeing on the value (two sweeps in a row);
# * a premise recorded as `contradicts-claim` (its first value already said
#   the claim was false), from the night after it was recorded;
# * a `ledger` premise, checked here and now (a ledger read, no command):
#   a lesson it names was retired or replaced, a statement it names was
#   corrected, a follow-up it names was closed. These wait for no sweep.
#
# `unavailable` never makes a move (`premises.verdict` reads it as neither
# holds nor moved); three in a row is a broken probe the brief shows.

#: Where the premise sweep (U2) keeps its observations, under the cache
#: (02 §3a.10.6; ``NOT_REPO_TRUTH``): JSON lines, oldest first, each
#: ``{"record": "lrn-…", "premise": "p1", "observation": {…}}`` with the
#: observation as :meth:`premises.Observation.as_dict` writes it (its keys
#: may also sit at the top level of the line). A missing or unreadable
#: file is "no observations": a probe premise then waits, and nothing else.
OBSERVATIONS_FILE = Path("premises") / "observations.jsonl"
#: Design D7.5: a re-decision a probe triggers waits until the premise was
#: decided (written or re-baselined) at least this many days ago. Follow-up,
#: ledger and `contradicts-claim` events do not wait.
PROBE_REDECIDE_DAYS = 7
#: Design D7.3: this many `unavailable` observations in a row is a broken
#: probe, shown in the lesson's brief for the steward to fix or drop.
BROKEN_PROBE_SWEEPS = 3


def observations_path(home: Path) -> Path:
    """The sweep's observation file for *home*'s cache namespace (the path
    `worker.cache_dir` resolves, computed without creating anything)."""
    from .serve import cache_dir_readonly  # late: serve imports the steward

    return cache_dir_readonly(home) / OBSERVATIONS_FILE


def _as_observation(row: Mapping[str, Any]) -> Any:
    """One stored observation as a :class:`premises.Observation`, or
    ``None`` when the row is not one."""
    from . import premises

    state = row.get("state")
    if state not in (premises.OBS_OK, premises.OBS_UNAVAILABLE):
        return None
    sha = row.get("value_sha")
    return premises.Observation(
        state=str(state),
        value_sha=str(sha) if isinstance(sha, str) and sha else None,
        shown=str(row.get("shown") or ""),
        claim=str(row.get("claim") or premises.CLAIM_UNJUDGED),
        reason=str(row.get("reason") or ""),
        observed_at=str(row.get("observed_at") or ""),
    )


def read_observations(home: Path) -> dict[tuple[str, str], list[Any]]:
    """``(record id, premise id) -> [Observation, ...]``, oldest first, from
    the sweep's cache file (:data:`OBSERVATIONS_FILE`)."""
    try:
        text = observations_path(home).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out: dict[tuple[str, str], list[Any]] = {}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        rid, pid = row.get("record"), row.get("premise")
        if not isinstance(rid, str) or not isinstance(pid, str):
            continue
        body = row.get("observation")
        observation = _as_observation(body if isinstance(body, dict) else row)
        if observation is not None:
            out.setdefault((rid, pid), []).append(observation)
    for rows in out.values():
        # stable: equal or unreadable times keep the file's order
        rows.sort(key=lambda o: chrono.to_dt(o.observed_at) or datetime.min.replace(tzinfo=timezone.utc))
    return out


def confirmed_move(premise: Mapping[str, Any], observations: Sequence[Any]) -> tuple[Any, Any] | None:
    """The two observations that confirm *premise* moved, or ``None``: the
    last two made after its baseline was recorded both judge it ``moved``
    (`premises.verdict`) and agree on the value. Older observations, made
    before a decision re-recorded the baseline, never count: a decided
    change does not come back from a stale cache line."""
    from . import premises

    baseline = premise.get("baseline")
    if not isinstance(baseline, Mapping):
        return None
    since = chrono.to_dt(baseline.get("observed_at"))
    after = []
    for observation in observations:
        when = chrono.to_dt(observation.observed_at)
        if when is not None and (since is None or when > since):
            after.append(observation)
    if len(after) < 2:
        return None
    first, last = after[-2], after[-1]
    if any(premises.verdict(premise, o) != premises.VERDICT_MOVED for o in (first, last)):
        return None
    if first.value_sha != last.value_sha:
        return None
    return first, last


def _broken_reason(observations: Sequence[Any]) -> str | None:
    """Why a probe is broken -- its last :data:`BROKEN_PROBE_SWEEPS`
    observations all `unavailable` -- or ``None``."""
    from . import premises

    last = list(observations)[-BROKEN_PROBE_SWEEPS:]
    if len(last) < BROKEN_PROBE_SWEEPS or any(o.state != premises.OBS_UNAVAILABLE for o in last):
        return None
    return last[-1].reason or "unavailable"


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
    brief's ``moved`` entries, ``source: premise``), ``broken`` (probes
    `unavailable` three sweeps running), and ``since`` (when the oldest
    move was first seen, for the oldest-first order)."""

    record_id: str
    items: list[dict]
    broken: list[dict]
    since: str


def _premise_item(
    premise: Mapping[str, Any], how: str, now: Any | None, since: str
) -> dict:
    """One ``moved`` entry (``source: premise``) as the brief and the run
    record carry it: claim, probe, recorded value and today's, all short
    and scan-clean (`premises` stores nothing else)."""
    baseline = premise.get("baseline") if isinstance(premise.get("baseline"), Mapping) else {}
    assert isinstance(baseline, Mapping)
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
        "since": since,
    }
    if premise.get("match") is not None:
        item["match"] = _one_line(premise.get("match"))
    if now is not None:
        item["now"] = now.shown
        item["now_at"] = now.observed_at
        item["value_sha"] = now.value_sha or ""
    else:
        item["now"] = item["recorded"]
        item["now_at"] = item["recorded_at"]
        item["value_sha"] = str(baseline.get("value_sha") or "")
    return item


def premise_moves(
    home: Path,
    record: Record,
    *,
    observations: Mapping[tuple[str, str], Sequence[Any]] | None = None,
    today: date | None = None,
) -> PremiseMoves | None:
    """The moves of *record*'s written premises (see the block comment
    above), or ``None`` when nothing moved and no probe is broken. A
    premise with ``on_change: refresh`` is never a move: code re-records
    it (the sweep's refresh) without asking the steward."""
    from . import premises

    observations = observations if observations is not None else {}
    today = today or datetime.now(timezone.utc).date()
    env = premises.ProbeEnv(ledger_home=home)
    items: list[dict] = []
    broken: list[dict] = []
    for premise in record.premises or []:
        probe = premise.get("probe")
        baseline = premise.get("baseline")
        if not isinstance(probe, Mapping) or not isinstance(baseline, Mapping):
            continue
        pid = str(premise.get("id"))
        rows = list(observations.get((record.id, pid), ()))
        reason = _broken_reason(rows)
        if reason is not None:
            broken.append({"premise": pid, "probe": probe_words(probe), "reason": _one_line(reason)})
        if premise.get("on_change") == "refresh":
            continue
        recorded_at = chrono.to_dt(baseline.get("observed_at"))
        if baseline.get("state") == "contradicts-claim":
            # Counts from the night after it was recorded (02 §3a.10.4 (1)).
            if recorded_at is not None and recorded_at.date() < today:
                later = [o for o in rows if o.state == premises.OBS_OK and o.value_sha]
                items.append(_premise_item(
                    premise, "contradicts-claim", later[-1] if later else None,
                    str(baseline.get("observed_at")),
                ))
            continue
        if probe.get("kind") == "ledger":
            observation = premises.observe(premise, env)
            if premises.verdict(premise, observation) == premises.VERDICT_MOVED:
                assert observation is not None
                items.append(_premise_item(premise, "ledger", observation, observation.observed_at))
            continue
        pair = confirmed_move(premise, rows)
        if pair is None:
            continue
        decided = chrono.to_dt(premise.get("decided_at"))
        if decided is not None and (today - decided.date()).days < PROBE_REDECIDE_DAYS:
            continue  # D7.5: it was decided less than a week ago; it waits
        items.append(_premise_item(premise, "probe", pair[1], pair[0].observed_at))
    if not items and not broken:
        return None
    since = min((item["since"] for item in items), default="")
    return PremiseMoves(record.id, items, broken, since)


def routed_with_premises(home: Path) -> list[Record]:
    """Every ROUTED record that carries a written ``premises`` list, in
    bucket and file order. Like `ledger_ops.closed_followups` it reads the
    file text first and parses only a file that names the field, because
    the steward's due check calls this on every scheduler tick."""
    from .ledger import discover_buckets
    from .records import RecordError

    out: list[Record] = []
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
            if record.status == "routed" and record.premises:
                out.append(record)
    return out


def moved_premises(home: Path, *, today: date | None = None) -> dict[str, PremiseMoves]:
    """``record id -> PremiseMoves`` for every placed lesson whose written
    premises moved or whose probe is broken (:func:`premise_moves`)."""
    records = routed_with_premises(home)
    if not records:
        return {}
    observations = read_observations(home)
    out: dict[str, PremiseMoves] = {}
    for record in records:
        found = premise_moves(home, record, observations=observations, today=today)
        if found is not None:
            out[record.id] = found
    return out


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
    predecessor: object, moved_ids: list[str], followup_only: bool
) -> list[str]:
    """The brief's [how to decide it] block: which case kind, which
    outcomes, and the rebaseline a decision that keeps the lesson owes."""
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
        ids = ", ".join(moved_ids)
        out.append(
            "  - every sentence still true: outcome `no-action` with a `premises` line "
            f"`action: rebaseline`, `ids: [{ids}]` (every moved premise the lesson keeps; the "
            "runner refuses a `no-action` case that leaves one out, because the same change "
            "would come back every night);"
        )
    out.append(
        "  - a sentence now false but the lesson's point stands: a `replace` line that narrows "
        "or corrects the words, every idea of the old text in `decision.rewrite`"
        + (
            "" if followup_only else
            ", and the `premises` rebaseline (or a `set`) on this lesson BEFORE the `replace` "
            "line, so the new lesson starts from today's values"
        )
        + ";"
    )
    out.append(
        "  - all of it false, or loaded text now covers it: `retire` with `covered_by`"
        + (
            "; what it asked for is now done by the system itself: `reject` with a `note`;"
            if predecessor else ";"
        )
    )
    if not followup_only:
        out.append(
            "  - the probe is wrong, not the lesson: fix or drop it with a `premises` line "
            "`action: set` (the whole list), and decide the lesson on what you find;"
        )
    if predecessor:
        out.append("  - you cannot tell: park it.")
    else:
        out.append(
            "  - it must move to another destination, or you cannot tell: park it "
            "(`authority-unclear`) with your tentative answer; with no case to supersede, a "
            "placed lesson cannot be moved or rejected here."
        )
    out.append(
        "  Narrowing, rewriting or retiring this placed lesson is yours here without the "
        "overseer (method section 17); merging it with another placed lesson is not."
    )
    return out


def render_premise_moved(
    home: Path, record: Record, row: Mapping[str, Any], *, path: str | None, head: str | None
) -> tuple[str, dict]:
    """The part of a ``premise-moved`` brief that is not the lesson itself:
    what moved -- a closed follow-up (U3), a written premise (U4: its claim,
    probe, recorded value and today's), or a mover another unit adds (U8's
    placement premises), each with the record lines to cite -- the lesson's
    premises, its `env` pins, broken probes, what the cases that cover it
    said would change them, and how to decide. Code never judges whether
    the lesson is still true: the brief gives the steward the facts and the
    deciding case's own prediction."""
    lines = [
        "[what moved] something this lesson rested on has changed since it was last "
        "decided; the facts below are recorded, not guessed"
    ]
    items = [m for m in row.get("moved") or [] if isinstance(m, dict)]
    followups = [m for m in items if m.get("source") == "follow-up-done"]
    written = [m for m in items if m.get("source") == "premise"]
    for item in followups:
        lines.append(f"  the follow-up on this lesson was closed on {item.get('done_at')}")
        for key, label in _FOLLOWUP_LABELS:
            if item.get(key):
                lines.append(f"    {label}: {_clip(item[key])}")
    for item in written:
        lines += _premise_item_lines(item)
    for item in items:
        if item.get("source") in ("follow-up-done", "premise"):
            continue
        # A mover another unit adds (the placement premises of U8): shown as
        # recorded until that unit gives it its own lines.
        detail = ", ".join(
            f"{key}: {_clip(value, 400)}" for key, value in sorted(item.items()) if key != "source"
        )
        lines.append(f"  moved ({item.get('source') or 'unknown source'}): {detail}")
    if followups:
        lines += _cited_block(
            record, "follow_up_done", "the closed follow-up as the record holds it",
            path=path, head=head,
        )
    if record.premises:
        # each premise is listed with the lesson itself (`render_record`)
        lines += _cited_block(
            record, "premises", "the premises as the record holds them", path=path, head=head,
        )
    broken = [b for b in row.get("broken") or [] if isinstance(b, dict)]
    if broken:
        lines.append(
            f"[broken probes] could not observe on {BROKEN_PROBE_SWEEPS} checks running: fix "
            "or drop each with `premises` `action: set`"
        )
        lines += [
            f"  {b.get('premise')}: {_clip(b.get('probe'), 300)} ({_clip(b.get('reason'), 200)})"
            for b in broken
        ]
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
    moved_ids = [str(m.get("premise")) for m in written]
    lines += _decide_lines(predecessor, moved_ids, followup_only=not written)
    stats = {"items": 0, "excerpted": 0, "excerpt_chars": 0, "verdicts": {}, "moved": len(items)}
    return "\n".join(lines), stats


# ------------------------------ premise-extract (U6, S-NEXT-u6-backfill)
#
# 02 §3a.10.7, "Writing premises": a PLACED lesson with no `premises` field
# is offered to the steward so that its premises get written -- the lessons
# placed before premises existed (149 on 2026-10-30), and any lesson a later
# route placed without them. The test is ABSENT, never empty: `premises: []`
# is a decision ("it rests on no fact about the machine") and is not offered
# again. Order (design D10): `environment-specific` lessons first, then those
# whose covering case says what would change it, then the rest; at most
# `premises.backfill_per_night` a night. The case such an input gets records
# what the lesson rests on and changes nothing else (`steward.
# _premise_extract_problem`): a lesson found false here is written with a
# premise whose first value contradicts its claim, and comes back the next
# night as a `premise-moved` input, where the authority to change it is.


def premise_backfill_per_night(home: Path) -> int:
    """How many ``premise-extract`` inputs one run may take: the tier C
    setting ``premises.backfill_per_night`` (default
    :data:`PREMISE_EXTRACT_PER_RUN`; 0 pauses the backfill)."""
    from . import settings  # late: settings is a registry module, not an input

    try:
        setting = settings.by_name("premises.backfill_per_night")
    except KeyError:
        return PREMISE_EXTRACT_PER_RUN
    value, _source = settings.resolve_setting(home, setting)
    try:
        return max(int(cast(int | str, value)), 0)
    except (TypeError, ValueError):
        return PREMISE_EXTRACT_PER_RUN


#: A frontmatter line that says the record is placed, and one that names
#: the field -- the cheap test before a parse (:func:`routed_without_premises`).
_ROUTED_LINE = re.compile(r"""^status:[ \t]*['"]?routed['"]?[ \t]*$""", re.M)
_PREMISES_KEY = re.compile(r"^premises[ \t]*:", re.M)


def _frontmatter(text: str) -> str | None:
    """A record file's frontmatter (between its first two ``---`` lines,
    as `Record.from_text` splits it), or ``None`` when it has none."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return None
    try:
        close = lines[1:].index("---") + 1
    except ValueError:
        return None
    return "\n".join(lines[1:close])


def routed_without_premises(home: Path) -> list[tuple[Path, Record]]:
    """Every ROUTED record whose frontmatter has no ``premises`` key, with
    its file path, in bucket and file order. ``premises: []`` is a key: a
    decision, never a candidate. Like :func:`routed_with_premises` it reads
    the file text first and parses only a file whose frontmatter says
    ``status: routed`` and names no ``premises`` key, because the
    steward's due check calls this on every scheduler tick; the parse then
    decides. An unreadable file is skipped."""
    from .ledger import discover_buckets
    from .records import RecordError

    out: list[tuple[Path, Record]] = []
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                front = _frontmatter(path.read_text(encoding="utf-8"))
                if front is None or not _ROUTED_LINE.search(front) or _PREMISES_KEY.search(front):
                    continue
                record = Record.from_path(path)
            except (RecordError, OSError, UnicodeDecodeError):
                continue
            if record.status == "routed" and record.premises is None:
                out.append((path, record))
    return out


def covering_cases(home: Path, record_ids: Iterable[str]) -> dict[str, list[str]]:
    """``record id -> [case id, ...]``: the cases that name each record, are
    intact and are not superseded, newest first, from ONE read of the case
    index (the backfill ranks every candidate at once). A record no such
    case names is absent. An index that cannot be read gives ``{}``: every
    lesson then ranks as one no case covers, and is still offered."""
    from . import cases

    wanted = {str(rid) for rid in record_ids}
    try:
        rows = cases.list_cases(home, only_ok=True)
    except (cases.CaseError, OSError, ValueError):
        return {}
    found: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        case_id = row.get("case")
        if not isinstance(case_id, str) or row.get("superseded_by"):
            continue
        for rid in row.get("records") or []:
            if str(rid) in wanted:
                found.setdefault(str(rid), []).append((str(row.get("opened_at") or ""), case_id))
    return {
        rid: [case_id for _opened, case_id in sorted(pairs, reverse=True)]
        for rid, pairs in found.items()
    }


def _would_change_by_case(home: Path, case_ids: Sequence[str]) -> list[tuple[str, list[str]]]:
    """``[(case id, its "what would change" bullets), ...]`` for the newest
    :data:`_OTHER_COVERING_CASES` of *case_ids* that have any."""
    out: list[tuple[str, list[str]]] = []
    for case_id in list(case_ids)[:_OTHER_COVERING_CASES]:
        bullets = _would_change_lines(home, case_id)
        if bullets:
            out.append((case_id, bullets))
    return out


#: The backfill's three ranks, in the order they are offered (design D10).
EXTRACT_RANK_ENVIRONMENT = 0
EXTRACT_RANK_WOULD_CHANGE = 1
EXTRACT_RANK_REST = 2


def extract_rank(home: Path, record: Record, case_ids: Sequence[str]) -> int:
    """Where *record* falls in the backfill's order (design D10): a lesson
    marked ``environment-specific`` first (it is the most likely to rest on
    a fact that can change), then one whose covering case (*case_ids*,
    newest first) wrote "What would change this decision" lines (an
    expiry condition already in prose, waiting to become a probe), then
    the rest. The case files are read only for a lesson that is not
    environment-specific."""
    if record.generality == "environment-specific":
        return EXTRACT_RANK_ENVIRONMENT
    if _would_change_by_case(home, case_ids):
        return EXTRACT_RANK_WOULD_CHANGE
    return EXTRACT_RANK_REST


#: The open follow-up's fields as the extract brief labels them.
_OPEN_FOLLOWUP_LABELS = (
    ("action", "what it asks for"),
    ("unblocks_on", "it is to be closed when"),
    ("note", "its note"),
)


def _extract_decide_lines() -> list[str]:
    """The extract brief's [how to decide it] block."""
    return [
        "[how to decide it] one `kind: resolution` case with `outcome: no-action` and no "
        "`supersedes` (the placement stands; this case only records what the lesson rests "
        "on), holding exactly ONE line for this lesson: `premises` with `action: set`:",
        "  - it rests on facts about this machine: write them, at most "
        f"{_premise_limits()} -- a one-line claim each, a probe where the catalog can check "
        "one (try it first with the `premise_probe` tool; keep it narrow: the line that "
        "matters, not a whole file), `probe: null` for a behaviour no check can see, and "
        "`source: <case id>#what_would_change[<n>]` on a premise taken from a line numbered "
        "above;",
        "  - it rests on no fact about the machine (a general practice): `premises: []`, with "
        "the reason in `decision.because`; it is then never offered again;",
        "  - a premise you would write is ALREADY false: do not change the lesson in this case "
        "(no replace, retire, route, reject or note line; the runner refuses them here). "
        "Write that premise with the probe that shows it is false: the runner records the "
        "first value as contradicting the claim, and the lesson comes back to you the next "
        "night as a `premise-moved` input, where correcting, narrowing or retiring it is "
        "yours;",
        "  - no probe can show what you found, or you cannot tell what it rests on: park the "
        "case (`authority-unclear`) with what you found.",
        "  (method section 17)",
    ]


def _premise_limits() -> str:
    from . import premises

    return f"{premises.MAX_PREMISES} premises, {premises.MAX_PROBED} of them with a probe"


def render_premise_extract(
    home: Path, record: Record, row: Mapping[str, Any], *, path: str | None, head: str | None
) -> tuple[str, dict]:
    """The part of a ``premise-extract`` brief that is not the lesson itself
    (S-NEXT-u6-backfill): what the steward needs to write the lesson's
    premises -- its recorded generality, its open follow-up (a condition
    the placement waits on is usually a premise), its ``env`` pins, and the
    numbered "What would change this decision" bullets of the cases that
    cover it, so a premise can name the bullet it came from -- then how to
    decide. No transcript evidence pack: what the lesson rests on is in its
    words and its cases, not in the session it was taught from."""
    lines = [
        "[what to write] this placed lesson has no premises recorded: write what it rests "
        "on. Nothing has been observed to change; the placement decision stands"
    ]
    if record.generality:
        lines.append(f"  generality as recorded: {record.generality}")
    follow = record.follow_up
    if follow:
        lines.append(
            "  its follow-up is still open (a condition the placement waits on is usually a "
            "premise):"
        )
        for key, label in _OPEN_FOLLOWUP_LABELS:
            if follow.get(key):
                lines.append(f"    {label}: {_clip(follow[key])}")
    if record.env:
        pins = ", ".join(f"{key} {value}" for key, value in sorted(record.env.items()))
        lines.append(
            f"[tool versions when it was taught] {_clip(pins, 600)} (a premise that really "
            "depends on a version says so with a `package` probe and `holds_if: version`)"
        )
    case_ids = covering_cases(home, [record.id]).get(record.id, [])
    shown = _would_change_by_case(home, case_ids)
    for case_id, bullets in shown:
        lines.append(f"[what the case that covers it ({case_id}) said would change it]")
        lines += [f"  [{n}] {_clip(bullet, 600)}" for n, bullet in enumerate(bullets, start=1)]
    if not case_ids:
        lines.append(
            "[covering case] none: no case names this lesson (placed before cases existed)"
        )
    lines += _extract_decide_lines()
    stats = {
        "items": 0, "excerpted": 0, "excerpt_chars": 0, "verdicts": {},
        "would_change_cases": len(shown),
    }
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
    # S-NEXT-u4-steward (02 §3a.10.2): what the lesson rests on, whatever
    # brought it here -- a premise with no probe (a behaviour) is read
    # nowhere else.
    if record.premises == []:
        lines.append("  premises: none (decided: it rests on no fact about the machine)")
    elif record.premises:
        lines.append("  premises (what it rests on):")
        lines += [f"  {line}" for line in _lesson_premise_lines(record)]
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
        elif kind == INPUT_PREMISE_EXTRACT and row.get("reason"):
            # S-NEXT-u6-backfill: nothing brought it BACK; it is here to be
            # completed.
            parts.append(f"[why it is here] {_one_line(row['reason'])}")
        parts.append(render_record(record, path=rel, head=head, bucket=_bucket_of(home, path)))
        if kind == INPUT_SUSPECTED_VIOLATION:
            events = [e for e in row.get("events") or [] if isinstance(e, dict)]
            text, pack_stats = fire_pack(events, roots=resolved_roots, budget=share)
            parts.append(text)
        elif kind == INPUT_PREMISE_MOVED:
            # What moved is the evidence: the lesson's own transcript pack
            # says what it was taught from, not what has changed since.
            text, pack_stats = render_premise_moved(home, record, row, path=rel, head=head)
            parts.append(text)
        elif kind == INPUT_PREMISE_EXTRACT:
            # S-NEXT-u6-backfill: what the lesson rests on is in its words and
            # its cases, not in the session it was taught from.
            text, pack_stats = render_premise_extract(home, record, row, path=rel, head=head)
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
