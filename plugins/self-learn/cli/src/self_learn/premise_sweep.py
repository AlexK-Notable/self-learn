"""premise_sweep.py -- the daily premise sweep (premise-check design, unit
U2, plus the sweep half of unit U8; decision row S-NEXT-u2-sweep, assigned
at landing).

:mod:`premises` is the field, the closed catalog of read-only probes and
the single comparison. This module is what runs them on a schedule and
remembers what they said, so that a change is noticed only when it is real:

- **The sweep** (:func:`run`) is one job of the ``serve`` process, due once
  a day and run before the steward. It walks every live routed lesson, runs
  every written probe, derives the three placement premises of each lesson
  (``@reach``, ``@writable``, ``@intact``; U8), and appends what it saw to
  the cache. It calls no model. Its only ledger writes are the ``refresh``
  re-baselines (:func:`_refresh_record`), under the commit lock.
- **The cache** is ``<cache>/premises/observations.jsonl`` (the last
  :data:`HISTORY_KEEP` observations per probe and per placement premise)
  and ``<cache>/premises/sweep.json`` (when the sweep last ran). Losing
  both delays a trigger by a day and loses nothing: a written premise's
  baseline lives on its record, and a placement premise has no baseline.
- **Change detection** (:func:`judge_probe`, :func:`judge_placement`): a
  value that differs from the baseline counts only when it stays different
  on :data:`STABLE_SWEEPS` sweeps in a row and the two observations agree
  (a service restarting or a file half-edited does not trigger). Three
  exceptions, each from the design: a ``ledger`` probe counts on first
  sight (a person or a ledger verb made the change); a baseline recorded
  as ``contradicts-claim`` counts from the sweep after it was written; and
  ``unavailable`` NEVER counts, in either direction (fail-closed; lrn-6d21607e).
  Three ``unavailable`` sweeps in a row make a written probe "broken"
  (:func:`doctor_rows`), which is a report, not an input.
- **Refresh** (``on_change: refresh``): a stably moved premise whose
  author chose ``refresh`` is re-baselined by code with no model call. That
  is the only thing the sweep writes to the ledger; the commit subject is
  ``self-learn: premises refresh lrn-<id> <premise ids>``.
- **Placement premises** (U8) are derived, never written, and judged by
  their current state rather than a stored baseline: ``@reach`` from
  :func:`reachability.reachability_rows`, ``@writable`` from the S-80 check
  (:func:`verbs._plain_write_check`, read-only), ``@intact`` from the compile
  record's verdict for the lesson's managed region. A failing ``@intact`` is
  put on the lessons whose entry line differs or is gone (the region is
  rendered from the ledger again and compared line by line); when the edit
  touches no entry, or the region cannot be matched to the ledger, it goes on
  the region's first lesson in file order and says so.
- **The read verb** (:func:`check`, ``self-learn premises check``) runs the
  same probes now and prints premise, baseline, current value and verdict.
  It writes NOTHING (not even the cache): a person running it twice must not
  make a flapping value look stable.
- **What this module does not do:** it does not decide anything, put a lesson
  in front of the steward, or write the ``premises`` field of a lesson
  (apart from the refresh above). The steward's input (U3/U4) reads
  :func:`confirmed_moves`; nothing else is its interface.

The switch is ``premises.enabled`` (tier C, default TRUE; agents never set
it). With it false the job is never due and :func:`run` does nothing unless
forced; :func:`check` works either way.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import (
    compiled,
    compilers,
    config,
    domain,
    intents,
    premises,
    reachability,
    sentinel,
    settings,
    verbs,
)
from .hosts import HostsError, host_mode, host_slug, load_hosts
from .ledger import Bucket, discover_buckets
from .ledger_ops import find_record_path
from .primitives import chrono, fsops
from .records import Record, RecordError

__all__ = [
    "BROKEN_PROBE_SWEEPS",
    "CheckRow",
    "DoctorRow",
    "HISTORY_KEEP",
    "MIN_SWEEP_GAP_SECS",
    "Movement",
    "STABLE_SWEEPS",
    "SWEEP_INTERVAL_SECS",
    "SweepResult",
    "check",
    "confirmed_moves",
    "default_cache_dir",
    "doctor_rows",
    "enabled",
    "is_due",
    "judge_placement",
    "judge_probe",
    "observations_path",
    "read_history",
    "read_state",
    "render_check",
    "routed_lessons",
    "run",
    "state_path",
]

# ------------------------------------------------------------- vocabulary

#: Due once a day (design D5).
SWEEP_INTERVAL_SECS = 24 * 3600
#: A second :func:`run` this soon after the last attempt is not a new
#: sweep: it would let two observations minutes apart read as "stable on
#: two sweeps" (a restart of the host process, a cache that was lost).
MIN_SWEEP_GAP_SECS = 6 * 3600
#: Observations kept per probe and per placement premise (design D5).
HISTORY_KEEP = 3
#: Design D7.2: a change counts after it holds on this many sweeps in a row.
STABLE_SWEEPS = 2
#: Design D7.3: a written probe `unavailable` on this many sweeps in a row
#: is "broken" in doctor and selftest. Equal to :data:`HISTORY_KEEP`: the
#: history cannot show a longer run.
BROKEN_PROBE_SWEEPS = 3

CACHE_SUBDIR = "premises"
OBSERVATIONS_FILENAME = "observations.jsonl"
STATE_FILENAME = "sweep.json"

#: Row ``kind``: a written probe, a written ``ledger`` probe (counts on
#: first sight), a derived placement premise.
KIND_PROBE = "probe"
KIND_LEDGER = "ledger"
KIND_PLACEMENT = "placement"

REACH, WRITABLE, INTACT = premises.PLACEMENT_PREMISE_IDS

_PLACEMENT_CLAIMS = {
    REACH: "a session loads the file this lesson was placed in",
    WRITABLE: "self-learn may still write to the place this lesson was routed to",
    INTACT: "the managed block holding this lesson is as self-learn left it",
}
#: The destinations whose lessons have ``@reach`` and ``@writable``
#: (02 §3a.10.3); ``@intact`` only for the two that have a managed region
#: the compile record tracks.
_PLACED_DESTINATIONS = ("claude-md", "skill-md", "new-skill", "hook")
_REGION_DESTINATIONS = ("claude-md", "skill-md")
#: What a managed target file's compile set is made of (the destinations
#: that write a managed region into one physical file).
_MANAGED_DESTINATIONS = ("claude-md", "skill-md", "new-skill")

_ID_RE = re.compile(r"\((lrn-[0-9a-f]{8})\)")
_SHOWN_LIMIT = 120

Key = tuple[str, str]
History = dict[Key, list[dict]]


def enabled(home: Path | str) -> bool:
    """Whether the premise check is on: ``premises.enabled``, a tier C
    switch whose DEFAULT is true (the user's 2026-10-30 change to design
    D12). Agents never set it (S-92 refuses a tier-C ``config set`` from an
    agent's shell). A registry that does not know the name reads as on, the
    code default."""
    try:
        setting = settings.by_name("premises.enabled")
    except KeyError:
        return True
    value, _source = settings.resolve_setting(Path(home), setting)
    return bool(value)


def default_cache_dir(home: Path | str) -> Path:
    """The per-home cache namespace ``serve`` and the steward use, WITHOUT
    creating it. ``serve`` imports this module, so the import is late."""
    from .serve import cache_dir_readonly

    return cache_dir_readonly(Path(home))


def observations_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / CACHE_SUBDIR / OBSERVATIONS_FILENAME


def state_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / CACHE_SUBDIR / STATE_FILENAME


# ---------------------------------------------------------------- the cache


def _write_cache_file(path: Path, text: str) -> None:
    """THE cache writer of this module (``NOT_REPO_TRUTH`` in the lock
    invariant: a file under the XDG cache, never a repo's truth). Atomic, so
    a reader never sees half a history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, text, fsync=False, preserve_mode=False)


def read_history(cache_dir: Path) -> History:
    """The observation rows, per ``(lesson id, premise id)``, oldest first.
    A malformed or foreign line is skipped, never an error: the cache is
    disposable and the next sweep rewrites it."""
    out: History = {}
    try:
        text = observations_path(cache_dir).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        rid, pid = row.get("id"), row.get("premise")
        if not isinstance(rid, str) or not isinstance(pid, str):
            continue
        if not isinstance(row.get("sweep"), str) or row.get("state") not in (
            premises.OBS_OK, premises.OBS_UNAVAILABLE
        ):
            continue
        out.setdefault((rid, pid), []).append(row)
    return out


def _store_history(cache_dir: Path, history: History) -> None:
    rows = [row for key in sorted(history) for row in history[key]]
    rows.sort(key=lambda row: (str(row.get("sweep")), str(row.get("id")), str(row.get("premise"))))
    text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    _write_cache_file(observations_path(cache_dir), text)


def read_state(cache_dir: Path) -> dict:
    """The last sweep's marker, or ``{}``."""
    try:
        data = json.loads(state_path(cache_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _store_state(cache_dir: Path, state: Mapping[str, Any]) -> None:
    _write_cache_file(state_path(cache_dir), json.dumps(dict(state), sort_keys=True) + "\n")


def _epoch(value: object) -> float | None:
    when = chrono.to_dt(value)
    return when.timestamp() if when is not None else None


# ------------------------------------------------------------ the lessons


def routed_lessons(home: Path | str) -> tuple[list[tuple[Bucket, Record]], int]:
    """Every live routed lesson (``domain.is_canon_live``: routed and not
    superseded), with its bucket, in a stable order, plus how many record
    files would not parse. The same walk :func:`reachability.reachability_rows`
    makes, so a lesson the sweep sees is a lesson that predicate sees."""
    home = Path(home)
    out: list[tuple[Bucket, Record]] = []
    unparseable = 0
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, UnicodeDecodeError, OSError):
                unparseable += 1
                continue
            if domain.is_canon_live(record):
                out.append((bucket, record))
    return out, unparseable


def _has_resolved(home: Path) -> bool:
    """Cheap: is there any resolved lesson file at all (the due check runs
    every tick, so it must not parse records)."""
    try:
        for bucket in discover_buckets(home):
            resolved = bucket.path / "resolved"
            if resolved.is_dir() and next(resolved.glob("lrn-*.md"), None) is not None:
                return True
    except OSError:
        return False
    return False


# ----------------------------------------------------------------- the rows


def _premise_sig(premise: Mapping) -> str:
    """A short hash of what a probe observes and how it is judged. Rows made
    under another signature are ignored once the steward rewrites a probe, a
    ``holds_if`` or a ``match``: they describe a different question."""
    blob = json.dumps(
        {
            "probe": premise.get("probe"),
            "holds_if": premise.get("holds_if"),
            "match": premise.get("match"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _row(
    sweep: str,
    record_id: str,
    premise_id: str,
    kind: str,
    obs: premises.Observation,
    *,
    sig: str = "",
    failing: bool | None = None,
    detail: str = "",
    group: str | None = None,
) -> dict:
    return {
        "sweep": sweep,
        "id": record_id,
        "premise": premise_id,
        "kind": kind,
        "psha": sig,
        "state": obs.state,
        "value_sha": obs.value_sha,
        "shown": obs.shown,
        "claim": obs.claim,
        "reason": obs.reason,
        "at": obs.observed_at,
        "failing": failing,
        "detail": detail,
        "group": group,
    }


def _obs(row: Mapping) -> premises.Observation:
    return premises.Observation(
        state=str(row.get("state")),
        value_sha=row.get("value_sha"),
        shown=str(row.get("shown") or ""),
        claim=str(row.get("claim") or premises.CLAIM_UNJUDGED),
        reason=str(row.get("reason") or ""),
        observed_at=str(row.get("at") or row.get("sweep")),
    )


def _written_rows(record: Record, env: premises.ProbeEnv, sweep: str) -> list[dict]:
    """One row per written premise that has a probe. Behavioural premises
    (``probe: null``) are never observed (design D8)."""
    rows: list[dict] = []
    for premise in record.premises or []:
        probe = premise.get("probe")
        if probe is None:
            continue
        obs = premises.observe(premise, env)
        if obs is None:  # defensive: observe() is None only without a probe
            continue
        kind = KIND_LEDGER if probe.get("kind") == "ledger" else KIND_PROBE
        rows.append(
            _row(sweep, record.id, str(premise.get("id")), kind, obs, sig=_premise_sig(premise))
        )
    return rows


# -------------------------------------------------- placement premises (U8)


@dataclass(frozen=True)
class _Fact:
    """One placement premise of one lesson, as derived now. ``state`` is
    ``holds``, ``failing`` or ``unavailable``; ``value`` is what the version
    of the failing state is made from (hashed, never stored as text)."""

    record_id: str
    premise_id: str
    state: str
    value: str = ""
    shown: str = ""
    detail: str = ""
    group: str | None = None


def _clip(text: str, limit: int = _SHOWN_LIMIT) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def _fact_row(fact: _Fact, sweep: str) -> dict:
    if fact.state == "unavailable":
        obs = premises.unavailable_observation(_clip(fact.detail or "unavailable"), observed_at=sweep)
        return _row(
            sweep, fact.record_id, fact.premise_id, KIND_PLACEMENT, obs,
            failing=None, detail=_clip(fact.detail, 200), group=fact.group,
        )
    obs = premises.observation_from_value(fact.value, observed_at=sweep)
    obs = dataclasses.replace(obs, shown=_clip(fact.shown) if fact.shown else obs.shown)
    return _row(
        sweep, fact.record_id, fact.premise_id, KIND_PLACEMENT, obs,
        failing=fact.state == "failing", detail=_clip(fact.detail, 200), group=fact.group,
    )


def _reach_fact(verdict: reachability.Verdict, hook_gate: bool) -> _Fact:
    rid = verdict.record_id
    if verdict.state == "reachable":
        return _Fact(rid, REACH, "holds", f"reachable:{verdict.reason}", "reachable")
    if verdict.state == "unreachable":
        if (
            verdict.destination == "hook"
            and verdict.reason in ("not-registered", "no-registrations")
            and not hook_gate
        ):
            # 02 §3a.10.3: waiting for the person's switch is not a broken
            # placement.
            return _Fact(rid, REACH, "holds", "hook-awaiting-switch", "hook awaits overseer.hook_activation")
        return _Fact(
            rid, REACH, "failing", f"unreachable:{verdict.reason}",
            f"unreachable: {verdict.reason}", verdict.detail,
        )
    return _Fact(rid, REACH, "unavailable", detail=f"unmeasurable: {verdict.reason}")


def _host_for(home: Path, bucket: Bucket, record: Record, verdict: reachability.Verdict):
    """``(host path, mode)`` for the host a write of this lesson goes
    through, or ``None``. User scope is a plain host by design (§4.8, the
    same literal ``verbs._resolve_target`` uses); a skill-bucket lesson and a
    hook go through the skills root, a project lesson through its project
    host. Raises :class:`HostsError` for a registry that cannot be read."""
    from .selfcheck import _managed_host_for

    if record.scope == "user" and verdict.destination != "hook":
        host = _managed_host_for(home, bucket, record)
        return (host, "plain") if host is not None else None
    if verdict.destination == "hook" or bucket.scope == "skill":
        root = load_hosts(home).skills_root
        host = Path(root) if root is not None else None
        registration = "skills-root"
    else:
        host = _managed_host_for(home, bucket, record)
        registration = "project"
    if host is None:
        return None
    return host, host_mode(home, host, registration=registration)


def _writable_fact(
    home: Path, bucket: Bucket, record: Record, verdict: reachability.Verdict
) -> _Fact:
    rid = record.id
    if not verdict.target:
        return _Fact(rid, WRITABLE, "unavailable", detail="the lesson's target cannot be resolved")
    try:
        placed = _host_for(home, bucket, record, verdict)
    except HostsError as exc:
        return _Fact(rid, WRITABLE, "unavailable", detail=f"hosts.yaml cannot be read ({type(exc).__name__})")
    if placed is None:
        return _Fact(rid, WRITABLE, "unavailable", detail="the lesson's host is not registered")
    _host, mode = placed
    if mode != "plain":
        # S-80's refusal is a plain-host rule; a git host commits its writes.
        return _Fact(rid, WRITABLE, "holds", "git-host", "git-mode host")
    try:
        _repo, _line, problem = verbs._plain_write_check(Path(verdict.target))
    except Exception as exc:  # noqa: BLE001 -- a placement check never takes a sweep down
        return _Fact(rid, WRITABLE, "unavailable", detail=f"the write check failed ({type(exc).__name__})")
    if problem is not None:
        return _Fact(rid, WRITABLE, "failing", f"refused:{problem}", problem, problem)
    return _Fact(rid, WRITABLE, "holds", "writable", "writable")


@dataclass(frozen=True)
class _Region:
    """What one lesson's managed region looked like when observed."""

    record: Record
    target: Path
    verdict: str  # clean | stale | edited | missing | unknown | fresh | ""
    observed: bytes | None
    entry: dict | None
    problem: str = ""


def _region_for(
    home: Path, bucket: Bucket, record: Record, verdict: reachability.Verdict
) -> _Region | None:
    """The compile record's verdict for this lesson's managed region, the
    way ``selfcheck._check_drift`` reads it. ``None``: no region applies
    (the target is unresolved)."""
    from .selfcheck import _managed_host_for

    if not verdict.target:
        return None
    target = Path(verdict.target)
    host = _managed_host_for(home, bucket, record)
    if host is None:
        return _Region(record, target, "", None, None, "the lesson's host cannot be resolved")
    scope_kind = "user" if bucket.scope == "user" else ("skill" if bucket.scope == "skill" else "project")
    try:
        slug = host_slug(home, host, scope_kind=scope_kind)
        entry = compiled.entry_for(
            compiled.load_record(home, slug),
            compiled.region_key(host, target, "managed"),
            region="managed",
        )
        observed: bytes | None = None
        if target.is_file():
            observed = compiled.region_bytes(target.read_text(encoding="utf-8"), "managed")
    except (compiled.CompiledRecordError, OSError, UnicodeDecodeError, ValueError) as exc:
        return _Region(record, target, "", None, None, f"cannot read the region ({type(exc).__name__})")
    state = compiled.verdict_for(entry, compiled.sha256_hex(observed) if observed is not None else None)
    return _Region(record, target, state, observed, entry)


def _entry_lines(region: bytes) -> dict[str, list[str]]:
    """Lines of a managed region by the lesson id each carries (the last
    ``(lrn-…)`` on a line is its own: an entry line ends with it)."""
    out: dict[str, list[str]] = {}
    for line in region.decode("utf-8", errors="replace").splitlines():
        ids = _ID_RE.findall(line)
        if ids:
            out.setdefault(ids[-1], []).append(line)
    return out


def _first_in_file_order(region: bytes | None, members: Iterable[Record]) -> str:
    ids = sorted(m.id for m in members)
    if region is not None:
        for line in region.decode("utf-8", errors="replace").splitlines():
            found = _ID_RE.findall(line)
            if found and found[-1] in ids:
                return found[-1]
    return ids[0]


def _edit_carriers(members: list[Record], observed: bytes, entry: dict | None) -> tuple[set[str], str]:
    """Which lessons of an edited region carry the edit (02 §3a.10.3): those
    whose entry line differs from what the compiler renders from the ledger
    now, or is gone. Only trusted when the rendering reproduces the very
    region the compile record last wrote (same sha256): otherwise the ledger
    has moved since and a line comparison would blame lessons for a change
    that is not a hand edit. Then, and when no entry line differs (a line added
    between entries, a heading touched), the edit goes on the region's first
    lesson in file order."""
    fallback = _first_in_file_order(observed, members)
    try:
        rendered = compilers.compile_managed_text("", members).text
        expected = compiled.region_bytes(rendered, "managed")
    except (compilers.CompileError, compiled.CompiledRecordError):
        expected = None
    if expected is None or entry is None or compiled.sha256_hex(expected) != entry.get("sha256"):
        return {fallback}, "the edit could not be matched to entries (region-level)"
    exp, obs = _entry_lines(expected), _entry_lines(observed)
    differing = {m.id for m in members if exp.get(m.id) != obs.get(m.id)}
    if differing:
        return differing, "this lesson's entry line differs from the ledger's or is gone"
    return {fallback}, "the edit touches no lesson's entry line"


def _intact_facts(
    regions: list[_Region], members_by_target: Mapping[Path, list[Record]]
) -> list[_Fact]:
    """``@intact`` for every lesson with a managed region, judged once per
    region and attributed to lessons (see :func:`_edit_carriers`)."""
    facts: list[_Fact] = []
    by_target: dict[Path, list[_Region]] = {}
    for region in regions:
        by_target.setdefault(region.target, []).append(region)
    for target, group in by_target.items():
        group_key = str(target)
        carriers: set[str] = set()
        note = ""
        failing = next((r for r in group if r.verdict == "edited"), None)
        if failing is not None and failing.observed is not None:
            carriers, note = _edit_carriers(
                members_by_target.get(target) or [r.record for r in group],
                failing.observed,
                failing.entry,
            )
        for region in group:
            rid = region.record.id
            if region.problem or region.verdict in ("", "unknown", "fresh"):
                reason = region.problem or f"no compile record entry for this region ({region.verdict or 'unknown'})"
                facts.append(_Fact(rid, INTACT, "unavailable", detail=reason, group=group_key))
            elif region.verdict in ("clean", "stale"):
                facts.append(_Fact(rid, INTACT, "holds", region.verdict, region.verdict, group=group_key))
            elif region.verdict == "missing":
                facts.append(
                    _Fact(rid, INTACT, "failing", "region-missing", "the managed block is gone",
                          "the managed block is gone from the target", group_key)
                )
            elif rid in carriers:  # edited
                sha = compiled.sha256_hex(region.observed or b"")
                facts.append(_Fact(rid, INTACT, "failing", f"edited:{sha}", "hand-edited", note, group_key))
            else:
                facts.append(_Fact(rid, INTACT, "holds", "entry-unedited", "entry unedited", group=group_key))
    return facts


def _placement_rows(
    home: Path, placed: list[tuple[Bucket, Record]], claude_dir: Path, sweep: str
) -> list[dict]:
    """The derived rows of every placement premise (``@reach``,
    ``@writable``, ``@intact``) of every placed lesson."""
    try:
        verdicts = {v.record_id: v for v in reachability.reachability_rows(home, claude_dir)}
    except Exception as exc:  # noqa: BLE001 -- the instrument failing is "unavailable", not a crash
        verdicts = {}
        reason = f"reachability could not be measured ({type(exc).__name__})"
        return [
            _fact_row(_Fact(rec.id, premise_id, "unavailable", detail=reason), sweep)
            for _b, rec in placed
            if (rec.routing or {}).get("destination") in _PLACED_DESTINATIONS
            for premise_id in (REACH, WRITABLE)
        ]
    hook_gate = config.hook_activation_enabled(home)
    facts: list[_Fact] = []
    regions: list[_Region] = []
    members_by_target: dict[Path, list[Record]] = {}
    for bucket, record in placed:
        verdict = verdicts.get(record.id)
        if verdict is None:  # not in the reachability domain (e.g. `reference`)
            continue
        facts.append(_reach_fact(verdict, hook_gate))
        facts.append(_writable_fact(home, bucket, record, verdict))
        if verdict.destination in _MANAGED_DESTINATIONS and verdict.target:
            members_by_target.setdefault(Path(verdict.target), []).append(record)
        if verdict.destination in _REGION_DESTINATIONS:
            region = _region_for(home, bucket, record, verdict)
            if region is None:
                facts.append(
                    _Fact(record.id, INTACT, "unavailable", detail="the lesson's target cannot be resolved")
                )
            else:
                regions.append(region)
    facts.extend(_intact_facts(regions, members_by_target))
    return [_fact_row(fact, sweep) for fact in facts]


# ------------------------------------------------------ judging a history


@dataclass(frozen=True)
class Judgement:
    """What the history says about one premise now. ``verdict`` is
    :data:`premises.VERDICT_*` vocabulary (``holds``, ``moved``,
    ``unavailable``, ``no-baseline``) or ``no-history``; ``confirmed`` is
    true when a ``moved`` has held long enough to count; ``since`` is the
    first observation of the value it moved to."""

    verdict: str
    confirmed: bool = False
    row: dict | None = None
    since: str | None = None


def _later_than(row_at: object, baseline_at: object) -> bool:
    a, b = chrono.to_dt(row_at), chrono.to_dt(baseline_at)
    return a is not None and b is not None and a > b


def judge_probe(premise: Mapping, rows: list[dict]) -> Judgement:
    """Judge one written premise from its observation rows (oldest first).
    Rows made under another probe or judgment are ignored. See the module
    docstring for what counts as a confirmed move."""
    sig = _premise_sig(premise)
    mine = [r for r in rows if r.get("psha") == sig]
    if not mine:
        return Judgement("no-history")
    latest = mine[-1]
    verdict = premises.verdict(premise, _obs(latest))
    if verdict != premises.VERDICT_MOVED:
        return Judgement(verdict, False, latest)
    baseline = premise.get("baseline") if isinstance(premise.get("baseline"), Mapping) else {}
    if latest.get("kind") == KIND_LEDGER:
        need = 1
    elif baseline.get("state") == "contradicts-claim" and _later_than(
        latest.get("at"), baseline.get("observed_at")
    ):
        need = 1  # the observation that wrote it was the first sighting
    else:
        need = STABLE_SWEEPS
    run_rows: list[dict] = []
    for row in reversed(mine):
        if (
            premises.verdict(premise, _obs(row)) == premises.VERDICT_MOVED
            and row.get("value_sha") == latest.get("value_sha")
        ):
            run_rows.append(row)
        else:
            break
    run_rows.reverse()
    confirmed = len(run_rows) >= need
    since = str(run_rows[0].get("at") or run_rows[0].get("sweep")) if run_rows else None
    return Judgement(premises.VERDICT_MOVED, confirmed, latest, since)


def judge_placement(rows: list[dict]) -> Judgement:
    """Judge one placement premise: by its current state, never a baseline.
    ``moved`` means failing; it counts after :data:`STABLE_SWEEPS` sweeps in a
    row with the same failing value."""
    if not rows:
        return Judgement("no-history")
    latest = rows[-1]
    if latest.get("state") != premises.OBS_OK or not latest.get("value_sha"):
        return Judgement(premises.VERDICT_UNAVAILABLE, False, latest)
    if not latest.get("failing"):
        return Judgement(premises.VERDICT_HOLDS, False, latest)
    run_rows: list[dict] = []
    for row in reversed(rows):
        if row.get("failing") and row.get("value_sha") == latest.get("value_sha"):
            run_rows.append(row)
        else:
            break
    run_rows.reverse()
    since = str(run_rows[0].get("at") or run_rows[0].get("sweep"))
    return Judgement(premises.VERDICT_MOVED, len(run_rows) >= STABLE_SWEEPS, latest, since)


@dataclass(frozen=True)
class Movement:
    """One confirmed move of one premise: what the steward's ``premise-moved``
    input is made from (U3/U4). ``kind`` is ``probe``, ``ledger`` or
    ``placement``; ``premise_id`` is ``p1``..``p4`` or ``@reach``,
    ``@writable``, ``@intact``; ``group`` is the managed target of an
    ``@intact`` move (lessons of one region are decided together)."""

    record_id: str
    premise_id: str
    kind: str
    claim: str
    value_sha: str
    shown: str
    baseline_shown: str
    since: str
    observed_at: str
    detail: str = ""
    group: str | None = None
    on_change: str = "re-decide"


def _premise_by_id(record: Record) -> dict[str, dict]:
    return {str(p.get("id")): p for p in (record.premises or [])}


def confirmed_moves(
    home: Path | str,
    cache_dir: Path | None = None,
    *,
    placed: list[tuple[Bucket, Record]] | None = None,
    history: History | None = None,
) -> list[Movement]:
    """Every premise whose move is confirmed by the cache, longest-moved
    first. ``on_change: refresh`` premises are not here (the sweep
    re-baselines them without a model). Reads only; an empty or missing
    cache gives ``[]``, so nothing triggers on a cold start."""
    home = Path(home)
    cache_dir = cache_dir if cache_dir is not None else default_cache_dir(home)
    placed = placed if placed is not None else routed_lessons(home)[0]
    history = history if history is not None else read_history(cache_dir)
    out: list[Movement] = []
    for _bucket, record in placed:
        for pid, premise in _premise_by_id(record).items():
            if premise.get("probe") is None or premise.get("on_change") == "refresh":
                continue
            judged = judge_probe(premise, history.get((record.id, pid), []))
            if judged.verdict != premises.VERDICT_MOVED or not judged.confirmed or judged.row is None:
                continue
            baseline = premise.get("baseline") or {}
            out.append(
                Movement(
                    record_id=record.id, premise_id=pid, kind=str(judged.row.get("kind")),
                    claim=str(premise.get("claim")), value_sha=str(judged.row.get("value_sha")),
                    shown=str(judged.row.get("shown") or ""),
                    baseline_shown=str(baseline.get("shown") or ""),
                    since=str(judged.since), observed_at=str(judged.row.get("at")),
                    on_change="re-decide",
                )
            )
        for pid in premises.PLACEMENT_PREMISE_IDS:
            rows = history.get((record.id, pid), [])
            judged = judge_placement(rows)
            if judged.verdict != premises.VERDICT_MOVED or not judged.confirmed or judged.row is None:
                continue
            out.append(
                Movement(
                    record_id=record.id, premise_id=pid, kind=KIND_PLACEMENT,
                    claim=_PLACEMENT_CLAIMS[pid], value_sha=str(judged.row.get("value_sha")),
                    shown=str(judged.row.get("shown") or ""), baseline_shown="",
                    since=str(judged.since), observed_at=str(judged.row.get("at")),
                    detail=str(judged.row.get("detail") or ""), group=judged.row.get("group"),
                )
            )
    out.sort(key=lambda m: (m.since, m.record_id, m.premise_id))
    return out


# ------------------------------------------------------------------ refresh


def _refresh_record(home: Path, record_id: str, updates: list[dict]) -> str | None:
    """Re-baseline the named ``on_change: refresh`` premises of one lesson,
    in ONE ledger commit under the commit lock. *updates* are observation
    rows that were stably moved. The record is read again INSIDE the lock and
    each update is applied only if the premise is still ``refresh``, still
    asks the same question (same signature) and still sits on a different
    baseline; a lesson that changed meanwhile is left for the next sweep.
    Returns the premise ids refreshed (``"p1 p2"``) or ``None`` when nothing
    was written. Raises on a git failure; :func:`run` records it."""
    path = find_record_path(home, record_id)
    changed: list[str] = []
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            record = Record.from_path(path)
            current = record.premises or []
            notes: list[str] = []
            rebuilt: list[dict] = []
            by_row = {str(row["premise"]): row for row in updates}
            for premise in current:
                pid = str(premise.get("id"))
                row = by_row.get(pid)
                keep = dict(premise)
                if (
                    row is not None
                    and premise.get("on_change") == "refresh"
                    and premise.get("probe") is not None
                    and _premise_sig(premise) == row.get("psha")
                    and isinstance(row.get("value_sha"), str)
                ):
                    old = premise.get("baseline") or {}
                    if old.get("value_sha") != row["value_sha"]:
                        keep["baseline"] = premises.make_baseline(_obs(row))
                        changed.append(pid)
                        before = str(old.get("shown") or "")[:80] or f"hash {str(old.get('value_sha'))[:8]}"
                        after = str(row.get("shown") or "")[:80] or f"hash {str(row['value_sha'])[:8]}"
                        notes.append(f"{pid}: {before} -> {after}")
                rebuilt.append(keep)
            if not changed:
                return None
            record.set_premises(rebuilt)
            record.write(path)
            body = (
                "Re-baselined by the premise sweep (code only, no model call): "
                "these premises are marked on_change: refresh.\n" + "\n".join(notes)
            )
            message = f"self-learn: premises refresh {record_id} {' '.join(changed)}"
            verbs._stage_and_commit(home, [path], message, body)
    finally:
        hold.release()
    return " ".join(changed)


# --------------------------------------------------------------- the sweep


@dataclass
class SweepResult:
    """What one :func:`run` did. ``status``: ``ok``, ``disabled``,
    ``too-soon`` (the last attempt was under :data:`MIN_SWEEP_GAP_SECS` ago)
    or ``idle`` (nothing routed). ``moved`` counts premises whose move is
    confirmed after this sweep; ``refreshed`` names ``lrn-…/p1`` entries."""

    status: str
    at: str = ""
    lessons: int = 0
    probes: int = 0
    placement: int = 0
    unavailable: int = 0
    moved: int = 0
    refreshed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_due(home: Path | str, cache_dir: Path, now: float) -> bool:
    """The serve due check: the switch is on, the last attempt was at least a
    day ago (the marker is written when an attempt STARTS, so a sweep that
    crashes waits a day instead of looping every tick), and the ledger has
    any resolved lesson to look at. Reads cache and directory names only."""
    home = Path(home)
    if not enabled(home):
        return False
    last = _epoch(read_state(cache_dir).get("last_attempt_at"))
    if last is not None and now - last < SWEEP_INTERVAL_SECS:
        return False
    return _has_resolved(home)


def _claude_dir(claude_dir: Path | None) -> Path:
    if claude_dir is not None:
        return Path(claude_dir)
    from .selfcheck import claude_runtime_dir

    return claude_runtime_dir()


def run(
    home: Path | str,
    cache_dir: Path | None = None,
    *,
    now: float | None = None,
    env: premises.ProbeEnv | None = None,
    claude_dir: Path | None = None,
    force: bool = False,
) -> SweepResult:
    """One sweep. See the module docstring. Never calls a model; writes the
    cache, and the ledger only for a ``refresh`` re-baseline. A failure in
    one lesson, or one refresh, is recorded in ``errors`` and the sweep
    carries on."""
    home = Path(home)
    cache_dir = cache_dir if cache_dir is not None else default_cache_dir(home)
    now_epoch = time.time() if now is None else float(now)
    sweep_at = chrono.now_iso(datetime.fromtimestamp(now_epoch, timezone.utc))
    if not force and not enabled(home):
        return SweepResult("disabled", sweep_at)
    state = read_state(cache_dir)
    last = _epoch(state.get("last_attempt_at"))
    if not force and last is not None and now_epoch - last < MIN_SWEEP_GAP_SECS:
        return SweepResult("too-soon", sweep_at)
    # The attempt marker first: a sweep that dies waits for the next day.
    _store_state(cache_dir, {**state, "last_attempt_at": sweep_at, "last_status": "running"})

    result = SweepResult("ok", sweep_at)
    placed, unparseable = routed_lessons(home)
    result.lessons = len(placed)
    if not placed:
        result.status = "idle"
    if unparseable:
        result.errors.append(f"{unparseable} record file(s) did not parse and were skipped")
    probe_env = dataclasses.replace(
        env if env is not None else premises.ProbeEnv(),
        ledger_home=(env.ledger_home if env is not None and env.ledger_home else home),
        now=lambda: sweep_at,
    )

    rows: list[dict] = []
    for _bucket, record in placed:
        try:
            rows.extend(_written_rows(record, probe_env, sweep_at))
        except Exception as exc:  # noqa: BLE001 -- one lesson never takes the sweep down
            result.errors.append(f"{record.id}: probes failed ({type(exc).__name__})")
    result.probes = len(rows)
    if placed:
        try:
            placement = _placement_rows(home, placed, _claude_dir(claude_dir), sweep_at)
        except Exception as exc:  # noqa: BLE001
            placement = []
            result.errors.append(f"placement premises failed ({type(exc).__name__})")
        rows.extend(placement)
        result.placement = len(placement)
    result.unavailable = sum(1 for row in rows if row["state"] == premises.OBS_UNAVAILABLE)

    history = read_history(cache_dir)
    fresh: History = {}
    for row in rows:
        key = (str(row["id"]), str(row["premise"]))
        fresh[key] = [*history.get(key, []), row][-HISTORY_KEEP:]
    _store_history(cache_dir, fresh)

    result.moved = len(confirmed_moves(home, cache_dir, placed=placed, history=fresh))
    refreshes: dict[str, list[dict]] = {}
    for _bucket, record in placed:
        for pid, premise in _premise_by_id(record).items():
            if premise.get("on_change") != "refresh" or premise.get("probe") is None:
                continue
            judged = judge_probe(premise, fresh.get((record.id, pid), []))
            if judged.verdict == premises.VERDICT_MOVED and judged.confirmed and judged.row:
                refreshes.setdefault(record.id, []).append(judged.row)
    for record_id, updates in sorted(refreshes.items()):
        try:
            done = _refresh_record(home, record_id, updates)
        except intents.LedgerStoppedError as exc:
            result.errors.append(f"{record_id}: refresh refused, the ledger is stopped ({exc})")
            break
        except Exception as exc:  # noqa: BLE001 -- the next sweep retries it
            result.errors.append(f"{record_id}: refresh failed ({type(exc).__name__}: {exc})")
            continue
        if done:
            result.refreshed.extend(f"{record_id}/{pid}" for pid in done.split())
            try:
                verbs._push_ledger(home, False)
            except Exception as exc:  # noqa: BLE001 -- the commit landed; a push can wait
                result.errors.append(f"{record_id}: refresh committed, push failed ({type(exc).__name__})")

    _store_state(
        cache_dir,
        {
            "last_attempt_at": sweep_at,
            "last_finished_at": sweep_at,
            "last_status": result.status,
            "lessons": result.lessons,
            "probes": result.probes,
            "placement": result.placement,
            "unavailable": result.unavailable,
            "moved": result.moved,
            "refreshed": result.refreshed,
            "errors": result.errors[:10],
        },
    )
    return result


# ------------------------------------------------------------ the read verb


@dataclass(frozen=True)
class CheckRow:
    """One line of ``self-learn premises check``. ``verdict``: ``holds``,
    ``moved``, ``unavailable``, ``no-probe``, ``no-baseline``. ``confirmed``
    is only meaningful for ``moved``: ``yes`` (a sweep would count it),
    ``first-sight`` (a second sweep confirms it) or ``refresh`` (code
    re-baselines it, no model)."""

    record_id: str
    premise_id: str
    kind: str
    claim: str
    verdict: str
    confirmed: str
    baseline_shown: str
    baseline_at: str
    current_shown: str
    observed_at: str
    reason: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _confirmed_label(judged: Judgement, premise: Mapping | None) -> str:
    if judged.verdict != premises.VERDICT_MOVED:
        return ""
    if premise is not None and premise.get("on_change") == "refresh":
        return "refresh"
    return "yes" if judged.confirmed else "first-sight"


def check(
    home: Path | str,
    *,
    record_id: str | None = None,
    cache_dir: Path | None = None,
    env: premises.ProbeEnv | None = None,
    claude_dir: Path | None = None,
    now: float | None = None,
) -> list[CheckRow]:
    """Run every probe and placement check NOW and return one row per
    premise, judged against the baseline on the record. Writes nothing at
    all. A row's ``confirmed`` says whether the cache's last observation plus
    this one would count as a stable move (what the next sweep will do).
    With *record_id*, only that lesson's rows (and a row saying so when it has
    no premises); the placement checks still read the whole ledger, because
    one managed block holds several lessons."""
    home = Path(home)
    cache_dir = cache_dir if cache_dir is not None else default_cache_dir(home)
    now_epoch = time.time() if now is None else float(now)
    at = chrono.now_iso(datetime.fromtimestamp(now_epoch, timezone.utc))
    placed, _unparseable = routed_lessons(home)
    if record_id is not None and not any(rec.id == record_id for _b, rec in placed):
        raise LookupError(f"{record_id} is not a live routed lesson in this ledger")
    probe_env = dataclasses.replace(
        env if env is not None else premises.ProbeEnv(),
        ledger_home=(env.ledger_home if env is not None and env.ledger_home else home),
        now=lambda: at,
    )
    history = read_history(cache_dir)
    out: list[CheckRow] = []
    wanted = [(b, r) for b, r in placed if record_id is None or r.id == record_id]
    for _bucket, record in wanted:
        for premise in record.premises or []:
            pid = str(premise.get("id"))
            baseline = premise.get("baseline") if isinstance(premise.get("baseline"), Mapping) else {}
            if premise.get("probe") is None:
                out.append(
                    CheckRow(record.id, pid, "behaviour", str(premise.get("claim")), premises.VERDICT_NO_PROBE,
                             "", "", "", "", "")
                )
                continue
            obs = premises.observe(premise, probe_env)
            assert obs is not None
            verdict = premises.verdict(premise, obs)
            kind = KIND_LEDGER if premise["probe"].get("kind") == "ledger" else KIND_PROBE
            judged = Judgement("no-history")
            if verdict == premises.VERDICT_MOVED:
                row = _row(at, record.id, pid, kind, obs, sig=_premise_sig(premise))
                judged = judge_probe(premise, [*history.get((record.id, pid), []), row])
            out.append(
                CheckRow(
                    record.id, pid, kind, str(premise.get("claim")), verdict,
                    _confirmed_label(judged, premise),
                    str(baseline.get("shown") or ""), str(baseline.get("observed_at") or ""),
                    obs.shown, obs.observed_at, obs.reason,
                )
            )
    if placed:
        for row in _placement_rows(home, placed, _claude_dir(claude_dir), at):
            if record_id is not None and row["id"] != record_id:
                continue
            prior = history.get((row["id"], row["premise"]), [])
            judged = judge_placement([*prior, row])
            verdict = judged.verdict if judged.verdict != "no-history" else premises.VERDICT_UNAVAILABLE
            out.append(
                CheckRow(
                    row["id"], row["premise"], KIND_PLACEMENT, _PLACEMENT_CLAIMS[row["premise"]], verdict,
                    _confirmed_label(judged, None), "", "", str(row.get("shown") or ""), str(row.get("at")),
                    str(row.get("reason") or row.get("detail") or ""),
                )
            )
    if record_id is not None and not out:
        out.append(
            CheckRow(record_id, "-", "none", "this lesson records no premises", premises.VERDICT_NO_PROBE,
                     "", "", "", "", "")
        )
    out.sort(key=lambda r: (r.record_id, r.premise_id.startswith("@"), r.premise_id))
    return out


def render_check(rows: list[CheckRow]) -> str:
    """The plain-text form of :func:`check`."""
    lines: list[str] = []
    last = None
    for row in rows:
        if row.record_id != last:
            lines.append(row.record_id)
            last = row.record_id
        tag = row.verdict if not row.confirmed else f"{row.verdict} ({_CONFIRMED_WORDS[row.confirmed]})"
        lines.append(f"  {row.premise_id:<10} {tag}")
        lines.append(f"      {row.claim}")
        if row.verdict in (premises.VERDICT_NO_PROBE,):
            lines.append("      (nothing to probe; written down only)")
            continue
        if row.baseline_shown or row.baseline_at:
            lines.append(f"      baseline: {row.baseline_shown or '(hash only)'}  [{row.baseline_at}]")
        if row.verdict == premises.VERDICT_UNAVAILABLE:
            lines.append(f"      now: could not be observed ({row.reason or 'unknown'})")
        else:
            lines.append(f"      now:      {row.current_shown or '(hash only)'}  [{row.observed_at}]")
    return "\n".join(lines)


_CONFIRMED_WORDS = {
    "yes": "stable: the sweep counts it",
    "first-sight": "first sight: a second sweep confirms it",
    "refresh": "code will re-baseline it",
}


# -------------------------------------------------------- doctor / selftest


@dataclass(frozen=True)
class DoctorRow:
    verdict: str  # OK | WARN | INFO
    name: str
    detail: str


def _ago(epoch: float | None, now: float) -> str:
    if epoch is None:
        return "never"
    hours = max(0, int((now - epoch) // 3600))
    return f"{hours} hour(s) ago" if hours < 48 else f"{hours // 24} day(s) ago"


def doctor_rows(
    home: Path | str, cache_dir: Path | None = None, *, now: float | None = None
) -> list[DoctorRow]:
    """The premise check's health, for ``doctor premises`` and the selftest
    row (02 §3a.10.6): written probes `unavailable` on three sweeps in a row
    (WARN, each named), placement premises failing and how many are
    `unavailable` (information, 02 §3a.10.3), how many placed lessons record
    no premises yet, and when the sweep last ran. Reads only."""
    home = Path(home)
    now_epoch = time.time() if now is None else float(now)
    if not enabled(home):
        return [DoctorRow("INFO", "premises", "off (premises.enabled is false)")]
    cache_dir = cache_dir if cache_dir is not None else default_cache_dir(home)
    placed, _unparseable = routed_lessons(home)
    history = read_history(cache_dir)
    rows: list[DoctorRow] = []

    broken: list[str] = []
    for _bucket, record in placed:
        for pid, premise in _premise_by_id(record).items():
            if premise.get("probe") is None:
                continue
            tail = [r for r in history.get((record.id, pid), []) if r.get("psha") == _premise_sig(premise)]
            tail = tail[-BROKEN_PROBE_SWEEPS:]
            if len(tail) == BROKEN_PROBE_SWEEPS and all(
                r.get("state") == premises.OBS_UNAVAILABLE for r in tail
            ):
                broken.append(f"{record.id}/{pid} ({_clip(str(tail[-1].get('reason') or ''), 60)})")
    if broken:
        rows.append(
            DoctorRow("WARN", "broken-probes",
                      f"{len(broken)} probe(s) unavailable on {BROKEN_PROBE_SWEEPS} sweeps in a row: "
                      + "; ".join(broken))
        )

    failing: list[str] = []
    unavailable = 0
    for _bucket, record in placed:
        for pid in premises.PLACEMENT_PREMISE_IDS:
            prior = history.get((record.id, pid), [])
            if not prior:
                continue
            judged = judge_placement(prior)
            if judged.verdict == premises.VERDICT_UNAVAILABLE:
                unavailable += 1
            elif judged.verdict == premises.VERDICT_MOVED and judged.confirmed:
                failing.append(f"{record.id}{pid}")
    if failing:
        rows.append(
            DoctorRow("INFO", "placement-failing",
                      f"{len(failing)} placement premise(s) failing on {STABLE_SWEEPS} sweeps: "
                      + ", ".join(failing))
        )
    if unavailable:
        rows.append(
            DoctorRow("INFO", "placement-unavailable",
                      f"{unavailable} placement premise(s) could not be measured (not an error)")
        )

    without = sum(1 for _b, rec in placed if rec.premises is None)
    rows.append(
        DoctorRow("INFO", "coverage", f"{without} of {len(placed)} placed lesson(s) record no premises yet")
    )
    state = read_state(cache_dir)
    last = _epoch(state.get("last_finished_at") or state.get("last_attempt_at"))
    detail = "the sweep has not run yet" if last is None else f"the sweep last ran {_ago(last, now_epoch)}"
    if state.get("last_status") == "running":
        detail += " and did not finish (it retries in a day)"
    errors = state.get("errors")
    if isinstance(errors, list) and errors:
        detail += f"; {len(errors)} problem(s) last time (first: {_clip(str(errors[0]), 100)})"
    rows.append(DoctorRow("INFO", "sweep", detail))
    if not rows or all(r.verdict == "INFO" for r in rows):
        rows.insert(0, DoctorRow("OK", "premises", "no probe is broken"))
    return rows
