"""The offline comparison of a session-miner shadow run with the old miner
(U4-harness; U4 spec section 7; docs/specs/self-learn/02-schema.md, "Session
miner output").

Run as ``python -m self_learn.mining.compare``:

``inventory --testset DIR --out DIR [--home LEDGER]``
    The zero-call inventory of a frozen test set: sessions with and without
    Claude Code's typed-turn marker, typed turns per session, the known
    moments per bucket (and how many sit in marker-less sessions), the role
    of each moment's line, sessions with subagent logs.

``report --run RUN_DIR [--testset DIR] [--home LEDGER] [--journal FILE]
[--marks FILE] [--shared-sample N] [--nights N] [--transcript-root DIR]``
    Compare one shadow run with what the old miner found. Writes only under
    ``<run>/compare/``: ``report.json`` (``miner-compare/1``), ``report.md``,
    ``spot-check.md`` and ``spot-marks.template.json``.

Everything it reads is read-only and it never calls a model. What it prints,
and what ``report.json`` and ``report.md`` hold, is counts and keys: session
ids and ``<session>#L<line>`` moment keys, never transcript text. The one
file with excerpts, ``spot-check.md``, is private (mode 0600). Exit codes: 0
done, 2 bad arguments or an input that fails its contract (the message names
the path of the first error and never echoes a value).

Vocabulary used throughout:

- A *moment* (frozen set) is one ``(session, line)`` the manifest lists; an
  *old find* (a night) is one origin of the old miner's journal row. Both are
  *targets*. A *fire* is a telemetry ``fire`` event.
- Bucket A: cited by a mined record (``source: session``) that was not
  rejected. B: cited only by rejected mined records (reported on its own
  line, never as a miss). C: cited only by ``teach`` records. ``other``:
  cited by none of those (a synthetic set can produce it; the real set
  cannot).
- A target is *found* when an item of the new miner hits it: **strict** (the
  same entry uuid; the same session and line when either uuid is missing) or
  **loose** (strict, or the same session, or a file holding the uuid, within
  one typed turn). Every count is given both ways; ``missed`` is the loose
  view and ``missed_strict`` the strict one.
- *Not judged is not missed*: a target in a session the new miner did not
  judge (skipped, not run, call failed, bad output, outside the judged line
  range, or absent from the run) is counted under its reason. A session with
  no typed turns is shelved by design: its reason is ``out-of-scope`` and the
  count field is ``out_of_scope`` (every reason value is hyphenated; the JSON
  field names stay snake_case).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .. import refs, telemetry
from ..index import fts5
from ..index.store import LessonIndex, lesson_text
from ..ledger import discover_buckets, resolve_home
from ..primitives import chrono, fsops
from ..records import Record
from ..scan import redact
from . import contract

__all__ = ["COMPARE_CONTRACT", "InputError", "main"]

COMPARE_CONTRACT = "miner-compare/1"

#: Slack after an old-miner run ends in which its fires and cost log fall.
WINDOW_SLACK_SECS = 300
#: Old-miner journal outcomes that count as "the old miner found this".
FOUND_OUTCOMES = frozenset({"landed", "folded", "recurrence", "recurrence-from-fire", "dropped-cap"})
#: ... and the night version of bucket B.
REJECTED_OUTCOME = "dropped-rejected"

#: The marks a person may give a new item or a missed moment.
ITEM_MARKS: tuple[str, ...] = ("real", "junk", "duplicate", "not-a-lesson")
#: The marks for a shared-but-maybe-different lesson.
SHARED_MARKS: tuple[str, ...] = ("same", "new-better", "old-better", "both-off")
DEFAULT_SHARED_SAMPLE = 8
#: Lines of context either side of a cited line in the spot sheet.
EXCERPT_BEFORE = 2
EXCERPT_AFTER = 2
EXCERPT_CHARS = 4000
NEIGHBOURS = 3

BUCKETS: tuple[str, ...] = ("A", "B", "C", "other")
_ORIGIN_RE = re.compile(r"^transcript:([^#\s]+)#L(\d+)$")
_RUN_ID_TS_RE = re.compile(r"^(\d{8}T\d{6}Z)-")


class InputError(ValueError):
    """An input that is missing, malformed or inconsistent. Exit code 2."""

    def __init__(self, errors: str | Sequence[str]) -> None:
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors[:5]))


# ------------------------------------------------------------ transcripts


@dataclass
class FileInfo:
    """What the comparison needs of one transcript file; the parsed entries
    themselves are dropped as soon as the file is scanned."""

    n_lines: int
    typed_lines: list[int]
    has_marker: bool
    uuids: frozenset[str]
    #: ``line -> (uuid, role)`` for the lines asked for; ``(None, None)`` when
    #: the line is past the end or is not a JSON object.
    at: dict[int, tuple[str | None, str | None]]


def scan_file(path: Path, wanted: Iterable[int] = ()) -> FileInfo:
    """One pass over a transcript, one slot per physical line (the same line
    splitting ``refs`` uses, so line numbers agree)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: list[dict[str, Any] | None] = []
    for raw in text.splitlines():
        try:
            e = json.loads(raw)
        except (ValueError, RecursionError):
            e = None
        entries.append(e if isinstance(e, dict) else None)
    uuids = frozenset(e["uuid"] for e in entries if e is not None and isinstance(e.get("uuid"), str))
    at: dict[int, tuple[str | None, str | None]] = {}
    for ln in wanted:
        e = entries[ln - 1] if 1 <= ln <= len(entries) else None
        if e is None:
            at[ln] = (None, None)
        else:
            uid = e.get("uuid")
            at[ln] = (uid if isinstance(uid, str) else None, refs.role_of(e))
    return FileInfo(
        n_lines=len(entries),
        typed_lines=contract.typed_turn_lines(entries),
        has_marker=contract.has_typed_turn_marker(entries),
        uuids=uuids,
        at=at,
    )


# ------------------------------------------------------------- the ledger


@dataclass(frozen=True)
class CitingRecord:
    id: str
    source: str
    status: str
    bucket: str
    text: str


def _cited(evidence: Iterable[Any]) -> set[tuple[str, int]]:
    """The ``(session, line)`` pairs a record's evidence cites, by ``origin``
    string or by a ``ref`` mapping."""
    out: set[tuple[str, int]] = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        origin = item.get("origin")
        if isinstance(origin, str):
            m = _ORIGIN_RE.match(origin.strip())
            if m:
                out.add((m.group(1), int(m.group(2))))
        ref = item.get("ref")
        if isinstance(ref, dict):
            session, line = ref.get("session"), ref.get("line")
            if isinstance(session, str) and isinstance(line, int) and not isinstance(line, bool):
                out.add((session, line))
    return out


@dataclass
class Ledger:
    by_moment: dict[tuple[str, int], list[CitingRecord]]
    by_id: dict[str, CitingRecord]
    unreadable: int


def load_ledger(home: Path) -> Ledger:
    """Every record under every bucket, read-only, enumerated the way
    ``index.store.collect`` does (``discover_buckets`` + ``Record.from_path``)."""
    if not home.is_dir():
        raise InputError("ledger home: not a directory")
    by_moment: dict[tuple[str, int], list[CitingRecord]] = {}
    by_id: dict[str, CitingRecord] = {}
    unreadable = 0
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            folder = bucket.path / sub
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                    cr = CitingRecord(
                        id=record.id,
                        source=record.source,
                        status=record.status,
                        bucket=f"{bucket.scope}/{bucket.name}",
                        text=lesson_text(record),
                    )
                    cites = _cited(record.evidence)
                except Exception:  # noqa: BLE001 -- one broken file costs that file
                    unreadable += 1
                    continue
                by_id[cr.id] = cr
                for pair in cites:
                    by_moment.setdefault(pair, []).append(cr)
    for lst in by_moment.values():
        lst.sort(key=lambda r: r.id)
    return Ledger(by_moment, by_id, unreadable)


def bucket_of(citing: Sequence[CitingRecord]) -> str:
    """A, B, C or ``other`` (module docstring)."""
    mined = [r for r in citing if r.source == "session"]
    if any(r.status != "rejected" for r in mined):
        return "A"
    if mined:
        return "B"
    if any(r.source == "teach" for r in citing):
        return "C"
    return "other"


# -------------------------------------------------------------- targets


@dataclass
class Target:
    """A moment, an old find or a fire: one entry of one transcript."""

    key: str
    session: str
    line: int
    uuid: str | None
    turn: int | None
    role: str | None
    holders: frozenset[str]
    ref: refs.Ref | None = None
    bucket: str | None = None
    citing: tuple[CitingRecord, ...] = ()
    outcome: str | None = None
    record: str | None = None
    unresolved: bool = False


def _moment_key(session: str, line: int) -> str:
    return f"{session}#L{line}"


@dataclass
class ManifestSession:
    session: str
    project: str
    file: str
    path: Path
    known_lines: list[int]
    subagent_logs: int = 0


@dataclass
class Testset:
    root: Path
    roots: list[Path]
    manifest_sha256: str
    sessions: dict[str, ManifestSession]


def load_testset(root: Path) -> Testset:
    """A frozen set's manifest and where its transcripts are. Main sessions
    are the manifest entries whose path has no ``subagents`` folder."""
    manifest_path = root / "MANIFEST.json"
    try:
        raw = manifest_path.read_bytes()
    except OSError:
        raise InputError("MANIFEST.json: missing or unreadable") from None
    try:
        manifest = json.loads(raw)
    except (ValueError, RecursionError):
        raise InputError("MANIFEST.json: not valid JSON") from None
    if not isinstance(manifest, list):
        raise InputError("MANIFEST.json: not an array")
    sessions: dict[str, ManifestSession] = {}
    subagent_logs: dict[str, int] = {}
    for i, m in enumerate(manifest):
        p = f"MANIFEST.json[{i}]"
        if not isinstance(m, dict):
            raise InputError(f"{p}: not an object")
        sid, rel = m.get("session"), m.get("file")
        if not isinstance(sid, str) or not sid or not isinstance(rel, str) or not rel:
            raise InputError(f"{p}: needs a session and a file")
        if "subagents" in Path(rel).parts:
            subagent_logs[sid] = subagent_logs.get(sid, 0) + 1
            continue
        lines = m.get("known_moment_lines", [])
        if not isinstance(lines, list) or any(
            not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in lines
        ):
            raise InputError(f"{p}.known_moment_lines: not a list of line numbers")
        if sid in sessions:
            raise InputError(f"{p}.session: listed twice")
        project = m.get("project")
        sessions[sid] = ManifestSession(
            session=sid,
            project=project if isinstance(project, str) else "",
            file=rel,
            path=root / "sessions" / rel,
            known_lines=sorted(set(lines)),
        )
    for sid, n in subagent_logs.items():
        if sid in sessions:
            sessions[sid].subagent_logs = n
    return Testset(
        root=root,
        roots=[root / "sessions", root / "sessions" / "from-archive"],
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        sessions=sessions,
    )


def _scan_testset(ts: Testset, extra_wanted: dict[str, set[int]] | None = None) -> dict[str, FileInfo]:
    infos: dict[str, FileInfo] = {}
    for sid in sorted(ts.sessions):
        ms = ts.sessions[sid]
        if not ms.path.is_file():
            raise InputError(f"manifest session {sid}: transcript file missing")
        wanted = set(ms.known_lines) | (extra_wanted or {}).get(sid, set())
        infos[sid] = scan_file(ms.path, wanted)
    return infos


def _resolve_ref(session: str, line: int, uuid: str | None, roots: Sequence[Path]) -> refs.Ref | None:
    try:
        return refs.resolve(session, line, uuid=uuid, roots=roots)
    except (refs.RefError, OSError):
        return None


def build_moments(
    ts: Testset, infos: dict[str, FileInfo], ledger: Ledger
) -> dict[str, Target]:
    """Every known moment of the set, keyed ``<session>#L<line>``."""
    holders_of: dict[str, set[str]] = {}
    for sid, info in infos.items():
        for line in ts.sessions[sid].known_lines:
            uid = info.at[line][0]
            if uid is not None:
                holders_of.setdefault(uid, set())
    for sid, info in infos.items():
        for uid in holders_of:
            if uid in info.uuids:
                holders_of[uid].add(sid)
    moments: dict[str, Target] = {}
    for sid in sorted(ts.sessions):
        info = infos[sid]
        for line in ts.sessions[sid].known_lines:
            uid, role = info.at[line]
            citing = tuple(ledger.by_moment.get((sid, line), ()))
            moments[_moment_key(sid, line)] = Target(
                key=_moment_key(sid, line),
                session=sid,
                line=line,
                uuid=uid,
                turn=contract.turn_of(info.typed_lines, line),
                role=role,
                holders=frozenset({sid} | holders_of.get(uid or "", set())),
                ref=_resolve_ref(sid, line, uid, ts.roots) if role is not None else None,
                bucket=bucket_of(citing),
                citing=citing,
                unresolved=role is None,
            )
    return moments


# ----------------------------------------------------------------- the run


class RunView:
    """What the run says about each session: judged, not judged and why, or
    shelved by design."""

    def __init__(self, run: contract.Run, outs: dict[str, contract.Checked]) -> None:
        self.run = run
        self.outs = outs
        self.by_session = {s["session"]: s for s in run["sessions"]}

    def state(self, session: str, line: int) -> tuple[str, str | None]:
        """``(state, reason)``; state is ``judged``, ``not-judged`` or
        ``out-of-scope``."""
        entry = self.by_session.get(session)
        if entry is None:
            return "not-judged", "not-in-run"
        if entry["status"] == "called":
            out = self.outs[session]
            if out["status"] != "ok":
                return "not-judged", out["status"]
            j = out["session"]["judged"]
            if not j["first_line"] <= line <= j["last_line"]:
                return "not-judged", "out-of-range"
            return "judged", None
        if entry["status"] == "skipped":
            if entry["reason"] == "no-typed-turns":
                return "out-of-scope", "out-of-scope"
            return "not-judged", entry["reason"]
        return "not-judged", entry["reason"]


@dataclass(frozen=True)
class Pt:
    ref: dict[str, Any]
    turn: int | None


@dataclass
class Item:
    key: str
    kind: str  # "lesson" | "sighting" | "rule_check"
    session: str
    data: dict[str, Any]
    points: list[Pt]
    record: str | None = None


def collect_items(run_id: str, outs: dict[str, contract.Checked]) -> list[Item]:
    """Every item of every session whose output is ``ok``."""
    items: list[Item] = []
    for sid in sorted(outs):
        out = outs[sid]
        if out["status"] != "ok":
            continue
        for lesson in out["lessons"]:
            items.append(
                Item(
                    f"{run_id}/{sid}/{lesson['id']}",
                    "lesson",
                    sid,
                    lesson,
                    [Pt(e["ref"], e["turn"]) for e in lesson["evidence"]],
                )
            )
        for i, s in enumerate(out["sightings"]):
            items.append(
                Item(
                    f"{run_id}/{sid}/sightings[{i}]",
                    "sighting",
                    sid,
                    s,
                    [Pt(e["ref"], e["turn"]) for e in s["evidence"]],
                    s["record"],
                )
            )
        for i, c in enumerate(out["rule_checks"]):
            items.append(
                Item(
                    f"{run_id}/{sid}/rule_checks[{i}]",
                    "rule_check",
                    sid,
                    c,
                    [Pt(c["situation"]["ref"], c["situation"]["turn"])],
                    c["record"],
                )
            )
    return items


# ---------------------------------------------------------------- matching


def hits_strict(pt: Pt, t: Target) -> bool:
    """The same entry: equal uuids (both present), else the same session and
    line. A subagent file's lines are not the main session's, so a subagent
    pointer hits only by uuid."""
    pu = pt.ref.get("uuid")
    if pu is not None and t.uuid is not None:
        return pu == t.uuid
    if pt.ref.get("subagent_file"):
        return False
    return pt.ref.get("session") == t.session and pt.ref.get("line") == t.line


def hits_loose(pt: Pt, t: Target) -> bool:
    """Strict, or the same exchange: the same session (or a file holding the
    target's uuid) and a typed turn at most one away. A subagent pointer never
    hits loosely."""
    if hits_strict(pt, t):
        return True
    if pt.ref.get("subagent_file"):
        return False
    if pt.ref.get("session") not in t.holders:
        return False
    if pt.turn is None or t.turn is None:
        return False
    return abs(pt.turn - t.turn) <= 1


@dataclass
class Match:
    strict: list[Item] = field(default_factory=list)
    loose: list[Item] = field(default_factory=list)


def match_targets(targets: Iterable[Target], items: Sequence[Item]) -> dict[str, Match]:
    """For each target the items that hit it. Lessons and sightings only: a
    rule check is matched against fires, not against lessons."""
    out: dict[str, Match] = {}
    for t in targets:
        m = Match()
        for it in items:
            if it.kind == "rule_check":
                continue
            if any(hits_strict(p, t) for p in it.points):
                m.strict.append(it)
                m.loose.append(it)
            elif any(hits_loose(p, t) for p in it.points):
                m.loose.append(it)
        out[t.key] = m
    return out


@dataclass
class Classified:
    target: Target
    match: Match
    kind: str | None  # "lesson" | "sighting" | None (not found, loose view)
    names_citing_record: bool
    state: str
    reason: str | None


def classify(targets: Iterable[Target], items: Sequence[Item], view: RunView) -> list[Classified]:
    targets = list(targets)
    matches = match_targets(targets, items)
    out: list[Classified] = []
    for t in targets:
        m = matches[t.key]
        kind = None
        if any(i.kind == "lesson" for i in m.loose):
            kind = "lesson"
        elif m.loose:
            kind = "sighting"
        cites = {r.id for r in t.citing}
        names = any(i.kind == "sighting" and i.record in cites for i in m.loose)
        state, reason = view.state(t.session, t.line)
        out.append(Classified(t, m, kind, names, state, reason))
    return out


def _count(into: dict[str, int], key: str) -> None:
    into[key] = into.get(key, 0) + 1


def _tally(rows: Iterable[Classified], *, counts_as_miss: bool | None = None) -> dict[str, Any]:
    """The per-line counts of one group of targets."""
    total = found_strict = found_loose = as_lesson = as_sighting = names = missed = missed_strict = oos = 0
    not_judged: dict[str, int] = {}
    for r in rows:
        total += 1
        strict = bool(r.match.strict)
        found_strict += strict
        if r.match.loose:
            found_loose += 1
            if r.kind == "lesson":
                as_lesson += 1
            else:
                as_sighting += 1
                names += r.names_citing_record
        if r.state == "judged":
            missed_strict += not strict
            missed += not r.match.loose
        elif not r.match.loose:
            if r.state == "out-of-scope":
                oos += 1
            else:
                _count(not_judged, r.reason or "unknown")
    d: dict[str, Any] = {
        "total": total,
        "found_strict": found_strict,
        "found_loose": found_loose,
        "found_as_lesson": as_lesson,
        "found_as_sighting": as_sighting,
        "found_as_sighting_naming_citing_record": names,
        "missed": missed,
        "missed_strict": missed_strict,
        "not_judged": dict(sorted(not_judged.items())),
        "out_of_scope": oos,
    }
    if counts_as_miss is not None:
        d["counts_as_miss"] = counts_as_miss
    return d


def _skipped(rows: Iterable[Classified]) -> dict[str, str]:
    """Every target the new miner did not judge and no item found, by key."""
    return {
        r.target.key: (r.reason or "unknown")
        for r in sorted(rows, key=lambda r: r.target.key)
        if r.state != "judged" and not r.match.loose
    }


# ---------------------------------------------------------- night inputs


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _dt(value: object) -> datetime | None:
    return chrono.to_dt(value)


def _cache_dir(home: Path) -> Path:
    from ..serve import cache_dir_readonly  # late: serve imports far more than the harness needs

    return cache_dir_readonly(home)


def default_journal_path(home: Path) -> Path:
    """The old miner's journal, without ``miner.journal_path()``'s mkdir."""
    return _cache_dir(home) / "miner" / "journal.jsonl"


@dataclass
class Night:
    rows: list[dict[str, Any]]
    found: dict[str, tuple[str, int, str]]  # key -> (session, line, outcome)
    rejected: dict[str, tuple[str, int]]
    by_outcome: dict[str, int]
    windows: list[tuple[datetime, datetime]]


def select_night(journal: Path, run: contract.Run, nights: int) -> Night:
    """The old miner's journal rows for the run's night(s): the latest
    ``nights`` rows with ``outcomes`` whose ``ts`` is not after the run's
    start, and every origin of theirs by outcome kind."""
    started = _dt(run["started_at"])
    rows = [
        r
        for r in _read_jsonl(journal)
        if isinstance(r.get("outcomes"), list) and _dt(r.get("ts")) is not None
    ]
    if started is not None:
        rows = [r for r in rows if (_dt(r["ts"]) or started) <= started]
    rows.sort(key=lambda r: _dt(r["ts"]) or datetime.min.replace(tzinfo=timezone.utc))
    rows = rows[-nights:] if nights > 0 else []
    if not rows:
        raise InputError("journal: no row with outcomes at or before the run's start")
    found: dict[str, tuple[str, int, str]] = {}
    rejected: dict[str, tuple[str, int]] = {}
    by_outcome: dict[str, int] = {}
    windows: list[tuple[datetime, datetime]] = []
    for r in rows:
        start = _dt(r["ts"])
        assert start is not None
        dur = r.get("duration_secs")
        dur_s = float(dur) if isinstance(dur, (int, float)) and not isinstance(dur, bool) else 0.0
        windows.append((start, start + timedelta(seconds=dur_s + WINDOW_SLACK_SECS)))
        for o in r["outcomes"]:
            if not isinstance(o, dict):
                continue
            kind, origin = o.get("outcome"), o.get("origin")
            if not isinstance(kind, str):
                continue
            _count(by_outcome, kind)
            m = _ORIGIN_RE.match(origin.strip()) if isinstance(origin, str) else None
            if m is None:
                continue
            session, line = m.group(1), int(m.group(2))
            key = _moment_key(session, line)
            if kind in FOUND_OUTCOMES:
                found.setdefault(key, (session, line, kind))
            elif kind == REJECTED_OUTCOME:
                rejected.setdefault(key, (session, line))
    for key in found:
        rejected.pop(key, None)
    return Night(rows, found, rejected, dict(sorted(by_outcome.items())), windows)


def _locate_scan(
    pairs: Iterable[tuple[str, int]], roots: Sequence[Path]
) -> dict[tuple[str, int], tuple[FileInfo, refs.Ref] | None]:
    """Resolve each ``(session, line)`` in the roots, scan each file once."""
    resolved: dict[tuple[str, int], refs.Ref | None] = {}
    paths: dict[tuple[str, int], Path | None] = {}
    wanted: dict[Path, set[int]] = {}
    for session, line in sorted(set(pairs)):
        ref = _resolve_ref(session, line, None, roots)
        resolved[(session, line)] = ref
        path: Path | None = None
        if ref is not None:
            try:
                path = refs.locate(ref, roots=roots)
            except (refs.RefError, OSError):
                path = None
        paths[(session, line)] = path
        if path is not None:
            wanted.setdefault(path, set()).add(line)
    infos = {p: scan_file(p, lines) for p, lines in wanted.items()}
    out: dict[tuple[str, int], tuple[FileInfo, refs.Ref] | None] = {}
    for pair, ref in resolved.items():
        path = paths[pair]
        out[pair] = (infos[path], ref) if ref is not None and path is not None else None
    return out


def _target_from(
    key: str,
    session: str,
    line: int,
    found: tuple[FileInfo, refs.Ref] | None,
    ledger: Ledger,
    **extra: Any,
) -> Target:
    citing = tuple(ledger.by_moment.get((session, line), ()))
    if found is None:
        return Target(key, session, line, None, None, None, frozenset({session}), unresolved=True, citing=citing, **extra)
    info, ref = found
    uid, role = info.at.get(line, (None, None))
    return Target(
        key=key,
        session=session,
        line=line,
        uuid=uid,
        turn=contract.turn_of(info.typed_lines, line),
        role=role,
        holders=frozenset({session}),
        ref=ref,
        citing=citing,
        unresolved=role is None,
        **extra,
    )


@dataclass(frozen=True)
class Fire:
    record: str
    outcome: str
    ts: str | None
    session: str
    line: int


def _fires(home: Path) -> list[Fire]:
    """Every telemetry ``fire`` event with a usable origin, read-only."""
    out: list[Fire] = []
    for e in telemetry.read_events(home):
        origin = e.get("origin")
        m = _ORIGIN_RE.match(origin.strip()) if isinstance(origin, str) else None
        if e.get("kind") != "fire" or m is None or not isinstance(e.get("record"), str):
            continue
        ts = e.get("ts")
        out.append(Fire(e["record"], str(e.get("outcome")), ts if isinstance(ts, str) else None, m.group(1), int(m.group(2))))
    return out


def _old_cost(home: Path, windows: Sequence[tuple[datetime, datetime]]) -> float | None:
    """The old miner's own cost for the night(s): the first line of each
    ``miner-reader.tool-events.<seam run id>.jsonl`` whose run id's timestamp
    falls in a row's window, while those logs are retained."""
    cache = _cache_dir(home)
    total = 0.0
    seen = False
    if not cache.is_dir():
        return None
    for p in sorted(cache.glob("miner-reader.tool-events.*.jsonl")):
        run_id = p.name[len("miner-reader.tool-events.") : -len(".jsonl")]
        m = _RUN_ID_TS_RE.match(run_id)
        if m is None:
            continue
        try:
            at = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if not any(a <= at <= b for a, b in windows):
            continue
        first = _read_jsonl_first(p)
        cost = first.get("cost_usd") if first else None
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            total += float(cost)
            seen = True
    return round(total, 6) if seen else None


def _read_jsonl_first(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            line = fh.readline()
    except OSError:
        return None
    try:
        e = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return e if isinstance(e, dict) else None


# ------------------------------------------------------------------- marks


def read_marks(path: Path | None, valid_keys: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """``{key: mark}`` from a marks file, ``valid_keys`` mapping each key the
    run offers to the marks it accepts. An unknown key or mark is an input
    error naming the key, never the value."""
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise InputError("marks: missing or unreadable") from None
    except (ValueError, RecursionError):
        raise InputError("marks: not valid JSON") from None
    if not isinstance(raw, dict):
        raise InputError("marks: not an object")
    marks: dict[str, str] = {}
    for key, entry in raw.items():
        if key not in valid_keys:
            raise InputError(f"marks[{key}]: not a key of this run's spot check")
        if not isinstance(entry, dict) or not isinstance(entry.get("mark", ""), str):
            raise InputError(f"marks[{key}].mark: not a string")
        mark = entry.get("mark", "")
        if mark == "":
            continue
        if mark not in valid_keys[key]:
            raise InputError(f"marks[{key}].mark: not one of the allowed marks")
        marks[key] = mark
    return marks


def _marks_summary(keys: Iterable[str], marks: dict[str, str], allowed: tuple[str, ...]) -> dict[str, int]:
    counts = {m: 0 for m in allowed}
    counts["unmarked"] = 0
    for k in keys:
        counts[marks.get(k, "unmarked")] += 1
    return counts


def sample_shared(run_id: str, candidates: Sequence[str], n: int) -> list[str]:
    """A deterministic sample, seeded by the run id: the keys ordered by the
    SHA-256 of ``<run id>:<key>``, the first ``n``. Independent of the Python
    version and of the order the candidates came in."""
    ordered = sorted(candidates, key=lambda k: hashlib.sha256(f"{run_id}:{k}".encode()).hexdigest())
    return sorted(ordered[: max(n, 0)])


# ------------------------------------------------------------- the report


def _median(values: Sequence[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _session_counts(view: RunView) -> dict[str, Any]:
    run = view.run
    called = [s for s in run["sessions"] if s["status"] == "called"]
    skipped: dict[str, int] = {}
    for s in run["sessions"]:
        if s["status"] == "skipped":
            _count(skipped, s["reason"])
    return {
        "called": len(called),
        "ok": sum(1 for s in called if s["out_status"] == "ok"),
        "bad_output": sum(1 for s in called if s["out_status"] == "bad-output"),
        "failed": sum(1 for s in called if s["out_status"] == "failed"),
        "skipped": dict(sorted(skipped.items())),
        "not_run": sum(1 for s in run["sessions"] if s["status"] == "not-run"),
    }


def _accuracy(outs: dict[str, contract.Checked]) -> dict[str, Any]:
    drops: dict[str, int] = {}
    verdicts: dict[str, int] = {}
    corrected = 0

    def see(e: dict[str, Any]) -> None:
        nonlocal corrected
        _count(verdicts, e["verdict"])
        corrected += e["corrected_from"] is not None

    for out in outs.values():
        for d in out["drops"]:
            _count(drops, d["reason"])
        for lesson in out["lessons"]:
            for e in lesson["evidence"]:
                see(e)
            if lesson["verification"] is not None:
                see(lesson["verification"])
        for s in out["sightings"]:
            for e in s["evidence"]:
                see(e)
    return {
        "drops": dict(sorted(drops.items())),
        "verdicts": dict(sorted(verdicts.items())),
        "corrected": corrected,
    }


def _rule_checks(
    items: Sequence[Item], fires: Sequence[Target], view: RunView
) -> tuple[dict[str, Any], set[str]]:
    """Rule checks against old fires: by record id plus the situation ref."""
    checks = [i for i in items if i.kind == "rule_check"]

    def hit(c: Item, f: Target, loose: bool) -> bool:
        if c.record != f.record:
            return False
        fn = hits_loose if loose else hits_strict
        return any(fn(p, f) for p in c.points)

    matched = matched_strict = missed = missed_strict = not_judged = same = different = 0
    hit_checks: set[str] = set()
    hit_checks_strict: set[str] = set()
    for f in fires:
        state, _reason = view.state(f.session, f.line)
        loose_hits = [c for c in checks if hit(c, f, True)]
        strict_hits = [c for c in checks if hit(c, f, False)]
        hit_checks.update(c.key for c in loose_hits)
        hit_checks_strict.update(c.key for c in strict_hits)
        matched_strict += bool(strict_hits)
        if loose_hits:
            matched += 1
            if any(c.data["outcome"] == f.outcome for c in loose_hits):
                same += 1
            else:
                different += 1
        elif state == "judged":
            missed += 1
        else:
            not_judged += 1
        if state == "judged" and not strict_hits:
            missed_strict += 1
    new_keys = {c.key for c in checks} - hit_checks
    d = {
        "old_fires": len(fires),
        "matched": matched,
        "matched_strict": matched_strict,
        "missed": missed,
        "missed_strict": missed_strict,
        "not_judged": not_judged,
        "new": len(new_keys),
        "new_strict": len({c.key for c in checks} - hit_checks_strict),
        "outcome_same": same,
        "outcome_different": different,
    }
    return d, new_keys


@dataclass
class Analysis:
    report: dict[str, Any]
    items: list[Item]
    rows: list[Classified]
    new_keys: list[str]
    new_rule_check_keys: set[str]
    missed_spot: list[Classified]
    shared: dict[str, list[Classified]]
    valid_marks: dict[str, tuple[str, ...]]
    roots: list[Path]


def analyse(
    run: contract.Run,
    outs: dict[str, contract.Checked],
    targets: dict[str, Target],
    fires: Sequence[Target],
    *,
    night: Night | None,
    shared_n: int,
    roots: list[Path],
    old_usd: float | None,
    marks: dict[str, str],
    ledger: Ledger,
    marks_path: Path | None,
) -> Analysis:
    run_id = run["run_id"]
    view = RunView(run, outs)
    items = collect_items(run_id, outs)
    rows = classify(list(targets.values()), items, view)

    # --- items: matched or new
    hit_loose: set[str] = set()
    hit_strict: set[str] = set()
    for r in rows:
        hit_loose.update(i.key for i in r.match.loose)
        hit_strict.update(i.key for i in r.match.strict)
    rc_stats, new_rc = _rule_checks(items, fires, view)
    non_rc = [i for i in items if i.kind != "rule_check"]
    new_keys = sorted([i.key for i in non_rc if i.key not in hit_loose] + sorted(new_rc))
    new_strict = [i.key for i in non_rc if i.key not in hit_strict]
    n_new_strict = len(new_strict) + rc_stats["new_strict"]
    matched_loose = len(items) - len(new_keys)
    matched_strict = len(items) - n_new_strict

    # --- the spot check's missed list: bucket A (a frozen set) or the old finds (a night)
    testset = run["mode"] == "testset"
    spot_rows = [
        r
        for r in rows
        if r.state == "judged" and not r.match.loose and (r.target.bucket == "A" if testset else True)
    ]
    missed_spot = sorted(spot_rows, key=lambda r: r.target.key)

    # --- the shared sample: found-as-lesson items that hit a target the old miner's records cite
    cands: dict[str, list[Classified]] = {}
    for r in rows:
        if not any(c.source == "session" for c in r.target.citing):
            continue
        for it in r.match.loose:
            if it.kind == "lesson":
                cands.setdefault(it.key, []).append(r)
    shared_keys = sample_shared(run_id, sorted(cands), shared_n)
    shared = {k: cands[k] for k in shared_keys}

    valid_marks: dict[str, tuple[str, ...]] = {}
    for k in new_keys:
        valid_marks[k] = ITEM_MARKS
    for r in missed_spot:
        valid_marks[r.target.key] = ITEM_MARKS
    for k in shared:
        valid_marks[k] = SHARED_MARKS
    if marks_path is not None:
        marks = read_marks(marks_path, valid_marks)

    # --- sections
    report: dict[str, Any] = {
        "contract": COMPARE_CONTRACT,
        "run_id": run_id,
        "mode": run["mode"],
        "generated_at": chrono.now_iso(),
        "sessions": _session_counts(view),
        "moments": None,
        "old_finds": None,
        "items": {
            "lessons": sum(1 for i in items if i.kind == "lesson"),
            "sightings": sum(1 for i in items if i.kind == "sighting"),
            "rule_checks": sum(1 for i in items if i.kind == "rule_check"),
            "matched": matched_loose,
            "matched_strict": matched_strict,
            "new": len(new_keys),
            "new_strict": n_new_strict,
            "marks": _marks_summary(new_keys, marks, ITEM_MARKS),
        },
        "accuracy": _accuracy(outs),
        "rule_checks": rc_stats,
        "cost": _cost(run, old_usd),
        "missed_moments": sorted(r.target.key for r in rows if r.state == "judged" and not r.match.loose),
        "new_items": new_keys,
        "missed_a_marks": {r.target.key: marks.get(r.target.key, "unmarked") for r in missed_spot},
        "skipped_moments": _skipped(rows),
        "shared_sample": {k: marks.get(k, "unmarked") for k in shared_keys},
        "shared_sample_marks": _marks_summary(shared_keys, marks, SHARED_MARKS),
        "ledger": {"records": len(ledger.by_id), "unreadable": ledger.unreadable},
    }
    if testset:
        by_bucket: dict[str, Any] = {}
        for b in BUCKETS:
            group = [r for r in rows if r.target.bucket == b]
            if group or b != "other":
                by_bucket[b] = _tally(group, counts_as_miss=(b == "A"))
        report["moments"] = {
            "total": len(rows),
            "by_bucket": by_bucket,
            "unresolved": sum(1 for r in rows if r.target.unresolved),
        }
    else:
        assert night is not None
        old = _tally(rows)
        rejected = sorted(_moment_key(s, n) for s, n in night.rejected.values())
        old["rejected_match"] = len(rejected)
        old["rejected_match_keys"] = rejected
        old["by_outcome"] = night.by_outcome
        old["unresolved"] = sum(1 for r in rows if r.target.unresolved)
        report["old_finds"] = old
    return Analysis(report, items, rows, new_keys, new_rc, missed_spot, shared, valid_marks, roots)


def _cost(run: contract.Run, old_usd: float | None) -> dict[str, Any]:
    called = [s["cost_usd"] for s in run["sessions"] if s["status"] == "called" and s["cost_usd"] is not None]
    return {
        "shadow_usd": round(sum(s["cost_usd"] for s in run["sessions"] if s["cost_usd"] is not None), 6),
        "per_called_session_usd": {
            "median": round(_median(called), 6),
            "max": round(float(max(called)), 6) if called else 0.0,
        },
        "old_usd": old_usd,
    }


# -------------------------------------------------------------- the sheets


def _fmt_pointer(ref: dict[str, Any], turn: int | None) -> str:
    where = f"{ref.get('session')}#L{ref.get('line')}"
    if ref.get("subagent_file"):
        where += f" ({ref['subagent_file']})"
    t = f" T{turn}" if turn is not None else ""
    return f"{where}{t} [{ref.get('role')}]"


def _excerpt_block(ref_dict: dict[str, Any], roots: Sequence[Path]) -> str:
    try:
        ref = refs.Ref.from_dict(ref_dict)
        rows = refs.excerpt(ref, before=EXCERPT_BEFORE, after=EXCERPT_AFTER, total_chars=EXCERPT_CHARS, roots=roots)
    except (refs.RefError, OSError, KeyError, ValueError, TypeError):
        return "    [excerpt unavailable]\n"
    lines: list[str] = []
    for r, text in rows:
        mark = ">>" if r.line == ref.line else "  "
        body = text.replace("\n", "\n        ")
        lines.append(f"    {mark} L{r.line} [{r.role}] {body}")
    return "\n".join(lines) + "\n"


def _record_block(r: CitingRecord, limit: int = 1200) -> str:
    text = r.text if len(r.text) <= limit else r.text[:limit] + " ...[clipped]"
    return f"  - {r.id} [{r.status}] source={r.source} ({r.bucket})\n    {text.replace(chr(10), chr(10) + '    ')}\n"


def _lesson_block(item: Item) -> str:
    L = item.data
    out = [f"- shape: {L['shape']} · scope: {L['scope']} · type: {L['type']} · kind: {L['kind']} · generality: {L['generality']}\n"]
    if L["type"] == "behavior":
        out.append(f"- Trigger: {L['trigger']}\n- Instruction: {L['instruction']}\n")
    else:
        out.append(f"- Fact: {L['fact']}\n")
        if L["context"]:
            out.append(f"- Context: {L['context']}\n")
    out.append(f"- why durable: {L['why_durable']}\n")
    if L["subagent_cause"]:
        out.append(f"- subagent cause: {L['subagent_cause']}\n")
    for i, e in enumerate(L["evidence"]):
        out.append(f"- evidence[{i}] {_fmt_pointer(e['ref'], e['turn'])} {e['verdict']}")
        if e["corrected_from"] is not None:
            out.append(f" (cited L{e['corrected_from']})")
        out.append(f"\n  > {e['quote']}\n")
    if L["verification"] is not None:
        v = L["verification"]
        out.append(f"- verification {_fmt_pointer(v['ref'], v['turn'])}: {v['how']}\n  > {v['quote']}\n")
    for i, s in enumerate(L["steps"]):
        out.append(f"- step {i + 1} {_fmt_pointer(s['ref'], s['turn'])}: {s['what']}\n")
    if L["incident_cost"] is not None:
        c = L["incident_cost"]
        out.append(f"- incident cost {_fmt_pointer(c['ref'], c['turn'])}: {c['text']}\n")
    return "".join(out)


def _neighbours(home: Path, item: Item) -> str:
    L = item.data
    query = " ".join(
        str(x) for x in (L["trigger"], L["instruction"], L["fact"], L["context"]) if x
    )
    try:
        index = LessonIndex.open_existing(home)
    except Exception:  # noqa: BLE001 -- a hint, never fatal
        index = None
    if index is None:
        return "- lexical neighbours: none (no lesson index built)\n"
    try:
        hits = fts5.search(index.conn, query, limit=NEIGHBOURS)
        docs = index.docs()
    except Exception:  # noqa: BLE001
        return "- lexical neighbours: unavailable\n"
    finally:
        index.close()
    if not hits:
        return "- lexical neighbours: none\n"
    out = ["- lexical neighbours (a hint for duplicates):\n"]
    for rid, _score in hits:
        doc = docs.get(rid)
        status = doc.status if doc else "?"
        text = (doc.text if doc else "")[:300].replace("\n", " ")
        out.append(f"  - {rid} [{status}] {text}\n")
    return "".join(out)


def build_sheet(a: Analysis, home: Path, ledger: Ledger, run: contract.Run) -> str:
    rep = a.report
    out: list[str] = [
        f"# Spot check for run {rep['run_id']}\n\n",
        f"mode {rep['mode']} · {len(a.shared)} shared-sample · {len(a.new_keys)} new item(s) · "
        f"{len(a.missed_spot)} missed\n\n",
        "Mark each entry in `spot-marks.template.json` (key, then `mark`). New items and missed moments: "
        f"{', '.join(ITEM_MARKS)}. Shared sample: {', '.join(SHARED_MARKS)}. "
        "Leave `mark` empty to leave an entry unmarked.\n\n",
    ]
    by_key = {i.key: i for i in a.items}
    if a.shared:
        out.append("## Shared sample: the same lesson, or a different one?\n\n")
        out.append(
            "Each is a new lesson that hit a moment the old miner's records also cite. "
            "Judge whether the two miners drew the same lesson.\n\n"
        )
        for key, hit_rows in a.shared.items():
            item = by_key[key]
            out.append(f"### {key}\n\nNEW LESSON\n{_lesson_block(item)}\n")
            for r in hit_rows:
                basis = "strict" if any(i.key == item.key for i in r.match.strict) else "loose"
                out.append(f"hit {r.target.key} (bucket {r.target.bucket}, {basis}); the old miner's record(s) citing it:\n")
                out.extend(_record_block(c) for c in r.target.citing if c.source == "session")
                if r.target.ref is not None:
                    out.append(_excerpt_block(r.target.ref.to_dict(), a.roots))
            out.append("\n")
    new_lessons = [k for k in a.new_keys if by_key[k].kind == "lesson"]
    new_sightings = [k for k in a.new_keys if by_key[k].kind == "sighting"]
    new_checks = [k for k in a.new_keys if by_key[k].kind == "rule_check"]
    if new_lessons:
        out.append("## New lessons (no old find hits them)\n\n")
        for k in new_lessons:
            item = by_key[k]
            out.append(f"### {k}\n\n{_lesson_block(item)}")
            out.append(_neighbours(home, item))
            for e in item.data["evidence"]:
                out.append(f"- context of evidence {_fmt_pointer(e['ref'], e['turn'])}:\n{_excerpt_block(e['ref'], a.roots)}")
            out.append("\n")
    if new_sightings:
        out.append("## New sightings\n\n")
        for k in new_sightings:
            item = by_key[k]
            rec = ledger.by_id.get(item.record or "")
            out.append(f"### {k}\n\nsighting of {item.record}\n")
            if rec is not None:
                out.append(_record_block(rec))
            for e in item.data["evidence"]:
                out.append(f"- evidence {_fmt_pointer(e['ref'], e['turn'])} {e['verdict']}\n  > {e['quote']}\n")
                out.append(_excerpt_block(e["ref"], a.roots))
            out.append("\n")
    if new_checks:
        out.append("## New rule checks (no old fire hits them)\n\n")
        for k in new_checks:
            item = by_key[k]
            c = item.data
            out.append(f"### {k}\n\nrule {c['record']} · outcome {c['outcome']}\n")
            rec = ledger.by_id.get(c["record"])
            if rec is not None:
                out.append(_record_block(rec))
            out.append(f"- situation {_fmt_pointer(c['situation']['ref'], c['situation']['turn'])}\n")
            out.append(_excerpt_block(c["situation"]["ref"], a.roots))
            if c["action"] is not None:
                out.append(f"- action {_fmt_pointer(c['action']['ref'], c['action']['turn'])}\n")
                out.append(_excerpt_block(c["action"]["ref"], a.roots))
            out.append("\n")
    if a.missed_spot:
        label = "bucket-A moments" if run["mode"] == "testset" else "old finds"
        out.append(f"## Missed {label} (the new miner judged the session and found nothing)\n\n")
        for r in a.missed_spot:
            t = r.target
            out.append(f"### {t.key}\n\nbucket {t.bucket or '-'} · role {t.role} · turn {t.turn}\n")
            if t.citing:
                out.append("records citing it:\n")
                out.extend(_record_block(c) for c in t.citing)
            if t.ref is not None:
                out.append(_excerpt_block(t.ref.to_dict(), a.roots))
            else:
                out.append("    [excerpt unavailable]\n")
            out.append("\n")
    text = "".join(out)
    # every text of the sheet passes the secret scan once more (the ledger
    # records and the model's own fields are not covered by refs.excerpt)
    return redact(text)[0]


def build_markdown(rep: dict[str, Any]) -> str:
    """The same counts as ``report.json``, as tables (counts and keys only)."""

    def row(*cells: object) -> str:
        return "| " + " | ".join(str(c) for c in cells) + " |\n"

    def keys(title: str, ks: Sequence[str]) -> str:
        if not ks:
            return f"**{title}:** none\n\n"
        shown = ", ".join(f"`{k}`" for k in ks[:50])
        more = f" (+{len(ks) - 50} more in report.json)" if len(ks) > 50 else ""
        return f"**{title}** ({len(ks)}): {shown}{more}\n\n"

    s = rep["sessions"]
    out = [
        f"# Comparison for run {rep['run_id']} ({rep['mode']})\n\n",
        "## Sessions\n\n| called | ok | bad-output | failed | not run | skipped |\n|---|---|---|---|---|---|\n",
        row(s["called"], s["ok"], s["bad_output"], s["failed"], s["not_run"], json.dumps(s["skipped"], sort_keys=True)),
        "\n",
    ]
    head = "| line | total | found strict | found loose | as lesson | as sighting | missed | missed strict | not judged | out of scope |\n|---|---|---|---|---|---|---|---|---|---|\n"
    if rep["moments"] is not None:
        out.append("## Known moments\n\n" + head)
        for b, d in rep["moments"]["by_bucket"].items():
            name = {"A": "A (mined, kept)", "B": "B (rejected only: never a miss)", "C": "C (taught only)", "other": "other (no mined or taught citer)"}[b]
            out.append(row(name, d["total"], d["found_strict"], d["found_loose"], d["found_as_lesson"], d["found_as_sighting"], d["missed"], d["missed_strict"], json.dumps(d["not_judged"], sort_keys=True), d["out_of_scope"]))
        out.append(f"\n{rep['moments']['unresolved']} moment(s) did not resolve to a transcript entry.\n\n")
    if rep["old_finds"] is not None:
        d = rep["old_finds"]
        out.append("## The old miner's finds for the night\n\n" + head)
        out.append(row("old finds", d["total"], d["found_strict"], d["found_loose"], d["found_as_lesson"], d["found_as_sighting"], d["missed"], d["missed_strict"], json.dumps(d["not_judged"], sort_keys=True), d["out_of_scope"]))
        out.append(f"\nMatched a rejected record (not a miss): {d['rejected_match']}. By outcome: {json.dumps(d['by_outcome'], sort_keys=True)}.\n\n")
    it = rep["items"]
    out.append("## The new miner's items\n\n| lessons | sightings | rule checks | matched | new | matched strict | new strict |\n|---|---|---|---|---|---|---|\n")
    out.append(row(it["lessons"], it["sightings"], it["rule_checks"], it["matched"], it["new"], it["matched_strict"], it["new_strict"]))
    out.append(f"\nMarks on new items: {json.dumps(it['marks'], sort_keys=True)}\n\n")
    out.append(f"Shared sample ({len(rep['shared_sample'])} sampled): {json.dumps(rep['shared_sample_marks'], sort_keys=True)}\n\n")
    rc = rep["rule_checks"]
    out.append("## Rule checks against the old miner's fires\n\n| old fires | matched | missed | not judged | new | outcome same | outcome different |\n|---|---|---|---|---|---|---|\n")
    out.append(row(rc["old_fires"], rc["matched"], rc["missed"], rc["not_judged"], rc["new"], rc["outcome_same"], rc["outcome_different"]))
    out.append("\n## Accuracy of the checks\n\n")
    out.append(f"Drops: {json.dumps(rep['accuracy']['drops'], sort_keys=True)}. Verdicts: {json.dumps(rep['accuracy']['verdicts'], sort_keys=True)}. Corrected pointers: {rep['accuracy']['corrected']}.\n\n")
    c = rep["cost"]
    old = "not measured" if c["old_usd"] is None else f"${c['old_usd']:.2f}"
    out.append(f"## Cost\n\nShadow ${c['shadow_usd']:.2f} (median per called session ${c['per_called_session_usd']['median']:.2f}, max ${c['per_called_session_usd']['max']:.2f}); old miner {old}.\n\n")
    out.append("## Keys\n\n")
    a_missed = [k for k, _ in rep["missed_a_marks"].items()]
    out.append(keys("Missed, to spot-check", a_missed))
    out.append(keys("Missed, all buckets", rep["missed_moments"]))
    out.append(keys("New items", rep["new_items"]))
    out.append(keys("Shared sample", list(rep["shared_sample"])))
    out.append(keys("Skipped (not judged, not found), with reasons in report.json", list(rep["skipped_moments"])))
    return "".join(out)


# ------------------------------------------------------------ the commands


def _write_outputs(
    out_dir: Path, rep: dict[str, Any], sheet: str, template_keys: Iterable[str]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(out_dir / "report.json", json.dumps(rep, indent=1, sort_keys=True) + "\n")
    fsops.atomic_write(out_dir / "report.md", build_markdown(rep))
    fsops.private_write(out_dir / "spot-check.md", sheet)
    # the template keeps any mark already entered for a key that remains
    tpl_path = out_dir / "spot-marks.template.json"
    existing: dict[str, Any] = {}
    try:
        loaded = json.loads(tpl_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, ValueError):
        pass
    tpl: dict[str, Any] = {}
    for k in sorted(template_keys):
        prev = existing.get(k)
        keep = isinstance(prev, dict) and isinstance(prev.get("mark"), str) and isinstance(prev.get("note"), str)
        tpl[k] = prev if keep else {"mark": "", "note": ""}
    fsops.private_write(tpl_path, json.dumps(tpl, indent=1, sort_keys=True) + "\n")


def _summary(rep: dict[str, Any]) -> str:
    s = rep["sessions"]
    lines = [
        f"run {rep['run_id']} ({rep['mode']}): sessions called {s['called']} (ok {s['ok']}, bad-output {s['bad_output']}, "
        f"failed {s['failed']}), skipped {json.dumps(s['skipped'], sort_keys=True)}, not run {s['not_run']}",
    ]
    if rep["moments"] is not None:
        for b, d in rep["moments"]["by_bucket"].items():
            lines.append(
                f"moments {b}: {d['total']} (found strict {d['found_strict']} / loose {d['found_loose']}, "
                f"missed {d['missed']}, not judged {sum(d['not_judged'].values())}, out of scope {d['out_of_scope']})"
            )
    if rep["old_finds"] is not None:
        d = rep["old_finds"]
        lines.append(
            f"old finds: {d['total']} (found strict {d['found_strict']} / loose {d['found_loose']}, missed {d['missed']}, "
            f"not judged {sum(d['not_judged'].values())}, out of scope {d['out_of_scope']}, rejected match {d['rejected_match']})"
        )
    it = rep["items"]
    lines.append(
        f"items: lessons {it['lessons']}, sightings {it['sightings']}, rule checks {it['rule_checks']}; "
        f"matched {it['matched']}, new {it['new']}; shared sample {len(rep['shared_sample'])}"
    )
    rc = rep["rule_checks"]
    lines.append(f"rule checks: old fires {rc['old_fires']}, matched {rc['matched']}, missed {rc['missed']}, new {rc['new']}")
    return "\n".join(lines)


def _testset_dir(arg: str | None, run: contract.Run) -> Path:
    if arg is not None:
        return Path(arg).expanduser()
    recorded = run.get("testset")
    if recorded is None:
        raise InputError("--testset is required for a testset run without a recorded set")
    return Path(recorded["dir"]).expanduser()


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run).expanduser()
    run, outs = contract.load_run(run_dir)
    home = Path(args.home).expanduser() if args.home else resolve_home()
    ledger = load_ledger(home)
    marks_path = Path(args.marks).expanduser() if args.marks else None
    night: Night | None = None
    fires: list[Target] = []
    old_usd: float | None = None
    if run["mode"] == "testset":
        ts = load_testset(_testset_dir(args.testset, run))
        recorded = run["testset"]
        if recorded is not None and recorded["manifest_sha256"] != ts.manifest_sha256:
            raise InputError("MANIFEST.json: differs from the manifest the run recorded")
        in_set = [f for f in _fires(home) if f.session in ts.sessions]
        extra_wanted: dict[str, set[int]] = {}
        for f in in_set:
            extra_wanted.setdefault(f.session, set()).add(f.line)
        infos = _scan_testset(ts, extra_wanted)
        targets = build_moments(ts, infos, ledger)
        for f in in_set:
            uid, role = infos[f.session].at[f.line]
            fires.append(
                Target(
                    key=_moment_key(f.session, f.line), session=f.session, line=f.line, uuid=uid,
                    turn=contract.turn_of(infos[f.session].typed_lines, f.line), role=role,
                    holders=frozenset({f.session}), outcome=f.outcome, record=f.record,
                )
            )
        roots = ts.roots
    else:
        roots = [Path(p).expanduser() for p in args.transcript_root] or refs.transcript_roots(home)
        journal = Path(args.journal).expanduser() if args.journal else default_journal_path(home)
        night = select_night(journal, run, args.nights)
        in_window = [
            f for f in _fires(home)
            if (at := _dt(f.ts)) is not None and any(a <= at <= b for a, b in night.windows)
        ]
        pairs = {(s, n) for s, n, _ in night.found.values()} | set(night.rejected.values())
        located = _locate_scan(pairs | {(f.session, f.line) for f in in_window}, roots)
        targets = {
            key: _target_from(key, s, n, located.get((s, n)), ledger, outcome=outcome)
            for key, (s, n, outcome) in sorted(night.found.items())
        }
        for f in in_window:
            fires.append(
                _target_from(
                    _moment_key(f.session, f.line), f.session, f.line, located.get((f.session, f.line)),
                    ledger, outcome=f.outcome, record=f.record,
                )
            )
        old_usd = _old_cost(home, night.windows)
    analysis = analyse(
        run, outs, targets, fires, night=night, shared_n=args.shared_sample, roots=roots,
        old_usd=old_usd, marks={}, ledger=ledger, marks_path=marks_path,
    )
    rep = analysis.report
    sheet = build_sheet(analysis, home, ledger, run)
    _write_outputs(run_dir / "compare", rep, sheet, analysis.valid_marks)
    print(_summary(rep))
    print(f"wrote {run_dir / 'compare'}")
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    ts = load_testset(Path(args.testset).expanduser())
    home = Path(args.home).expanduser() if args.home else resolve_home()
    ledger = load_ledger(home)
    infos = _scan_testset(ts)
    moments = build_moments(ts, infos, ledger)
    no_marker = sorted(s for s, i in infos.items() if not i.has_marker)
    no_typed = sorted(s for s, i in infos.items() if i.has_marker and not i.typed_lines)
    typed_counts = [len(i.typed_lines) for i in infos.values()]
    by_bucket: dict[str, int] = {}
    in_markerless: dict[str, int] = {}
    roles: dict[str, int] = {}
    for m in moments.values():
        _count(by_bucket, m.bucket or "other")
        if m.session in no_marker:
            _count(in_markerless, m.bucket or "other")
        _count(roles, m.role or "unresolved")
    inv = {
        "contract": "miner-inventory/1",
        "sessions": {
            "total": len(infos),
            "with_marker": len(infos) - len(no_marker),
            "without_marker": len(no_marker),
            "without_typed_turns": len(no_typed),
            "with_subagent_logs": sum(1 for s in ts.sessions.values() if s.subagent_logs),
        },
        "without_marker_ids": no_marker,
        "without_typed_turns_ids": no_typed,
        "with_subagent_logs_ids": sorted(s.session for s in ts.sessions.values() if s.subagent_logs),
        "typed_turns": {
            "median": _median(typed_counts),
            "max": max(typed_counts) if typed_counts else 0,
        },
        "moments": {
            "total": len(moments),
            "by_bucket": dict(sorted(by_bucket.items())),
            "in_sessions_without_marker": dict(sorted(in_markerless.items())),
            "roles": dict(sorted(roles.items())),
        },
        "manifest_sha256": ts.manifest_sha256,
    }
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(out_dir / "inventory.json", json.dumps(inv, indent=1, sort_keys=True) + "\n")
    s = inv["sessions"]
    print(
        f"sessions {s['total']}: with marker {s['with_marker']}, without {s['without_marker']}, "
        f"no typed turns {s['without_typed_turns']}, with subagent logs {s['with_subagent_logs']}"
    )
    print(f"typed turns per session: median {inv['typed_turns']['median']:g}, max {inv['typed_turns']['max']}")
    print(
        f"moments {inv['moments']['total']}: by bucket {json.dumps(inv['moments']['by_bucket'], sort_keys=True)}; "
        f"in sessions without the marker {json.dumps(inv['moments']['in_sessions_without_marker'], sort_keys=True)}"
    )
    print(f"moment line roles: {json.dumps(inv['moments']['roles'], sort_keys=True)}")
    if no_marker:
        print("sessions without the marker: " + ", ".join(no_marker))
    print(f"wrote {out_dir / 'inventory.json'}")
    return 0


# --------------------------------------------------------------------- CLI


def _nonneg(text: str) -> int:
    n = int(text)
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return n


def _positive(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m self_learn.mining.compare",
        description="Compare a session-miner shadow run with the old miner (counts and keys only).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("inventory", help="the zero-call inventory of a frozen test set")
    inv.add_argument("--testset", required=True, metavar="DIR")
    inv.add_argument("--home", metavar="LEDGER")
    inv.add_argument("--out", required=True, metavar="DIR", help="where inventory.json goes (required: nothing is written to the working directory)")
    rep = sub.add_parser("report", help="compare one shadow run with the old miner")
    rep.add_argument("--run", required=True, metavar="RUN_DIR")
    rep.add_argument("--testset", metavar="DIR", help="default: the set the run recorded")
    rep.add_argument("--home", metavar="LEDGER")
    rep.add_argument("--journal", metavar="FILE", help="night runs: the old miner's journal")
    rep.add_argument("--marks", metavar="FILE", help="a filled-in spot-marks file")
    rep.add_argument("--shared-sample", type=_nonneg, default=DEFAULT_SHARED_SAMPLE, metavar="N")
    rep.add_argument("--nights", type=_positive, default=1, metavar="N", help="night runs: how many journal rows (default 1)")
    rep.add_argument("--transcript-root", action="append", default=[], metavar="DIR", help="night runs: where transcripts live (repeatable)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "inventory":
            return cmd_inventory(args)
        return cmd_report(args)
    except (InputError, contract.ContractError) as exc:
        print(f"error: {exc.errors[0] if exc.errors else exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
