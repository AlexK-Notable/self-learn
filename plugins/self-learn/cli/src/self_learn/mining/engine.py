"""The session engine: one model call per session (new-miner plan §1, §3;
unit R2).

``miner.run`` owns the run: its lock, the cursors, the sweeps, the ledger
lock and the landing commit. When ``miner.engine`` is ``session`` it hands
each slice ``walk()`` returned to this module, which

1. **plans** it (:func:`plan_session`): the judged range (the slice cut at
   its halt point), the session filters, the rule-situation flags, the
   spine and the session's three tools;
2. **calls** every planned session (:func:`call_sessions`): the first alone
   (it sweeps orphans once and writes the shared prefix to the prompt
   cache), the rest ``parallel`` at once, a ``transient`` failure retried
   once, and no call started once the runaway guard trips;
3. **checks** each final message (:func:`check_session`) into
   ``miner-output/1``.

``miner._land_checked`` lands the checked output; this module never writes
the ledger. The one seam call is ``miner.py``'s (the census of
``tests/test_invocation.py``), passed in as ``call``.

Everything a run writes here is in the cache, under
``<cache>/miner/runs/<run_id>/`` (:class:`RunFolder`), mode 0600: it holds
redacted transcript text. The newest :data:`KEEP_RUNS` run folders are kept,
and as many of the seam's transcript copies of the ``miner-session``
surface (``<cache>/sessions/miner-session/<run_id>/``), which the seam
itself never prunes.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Container, Mapping, Sequence

from .. import invocation, lesson_writing, provenance, settings, worker
from ..invocation import failure_class
from ..primitives import fsops
from ..records import Record
from . import check as check_mod
from . import contract, flags as flags_mod, spine as spine_mod, tools as tools_mod
from .spine import Session, Spine, SpineFlag

__all__ = [
    "HEAVY_CALL_USD",
    "KEEP_RUNS",
    "SURFACE",
    "CallRecord",
    "EngineError",
    "EngineSettings",
    "Plan",
    "RunFolder",
    "SessionResult",
    "call_sessions",
    "check_session",
    "flag_body",
    "plan_session",
    "prune_runs",
    "prune_session_copies",
    "run_record",
    "save_plan",
    "save_result",
    "session_spec",
    "shared_instructions",
    "spine_flags",
]

SURFACE = "miner-session"
#: What one call is assumed to cost while it runs (old spec §8.2's heavy
#: call, rounded up), and what a call that reports no cost counts as.
HEAVY_CALL_USD = 0.60
#: Run folders, and transcript-copy groups of the surface, kept.
KEEP_RUNS = 30
#: ``miner.parallel`` is used within these bounds, ``miner.spine_tokens``
#: from this floor (the registry refuses only values <= 0).
PARALLEL_MAX = 8
SPINE_TOKENS_MIN = 2_000

_METHOD = "miner-method.md"
_VERSION_RE = re.compile(r"<!--\s*method-version:\s*(\S+?)\s*-->")
_SCHEMA_LINE = f"=== OUTPUT SCHEMA ({contract.MODEL_CONTRACT}) ==="


class EngineError(RuntimeError):
    """The engine cannot run at all (its method file is missing)."""


# ---------------------------------------------------------------- settings


@dataclass(frozen=True)
class EngineSettings:
    parallel: int = 4
    spine_tokens: int = spine_mod.DEFAULT_SPINE_TOKENS
    max_sessions: int = 30
    max_usd: float = 8.0

    @classmethod
    def resolve(cls, home: Path | str) -> "EngineSettings":
        """The run's settings, read once (``miner.parallel`` clamped to
        1..8, ``miner.spine_tokens`` to at least 2,000)."""
        return cls(
            parallel=min(PARALLEL_MAX, max(1, settings.resolve_int(home, "miner.parallel"))),
            spine_tokens=max(SPINE_TOKENS_MIN, settings.resolve_int(home, "miner.spine_tokens")),
            max_sessions=max(1, settings.resolve_int(home, "miner.max_sessions_per_run")),
            max_usd=settings.resolve_float(home, "miner.max_run_usd"),
        )


# ---------------------------------------------------- shared instructions


def shared_instructions() -> tuple[str, str]:
    """``(text, method version)``: the part of every call's system prompt
    that is the same bytes for the whole run (plan §3.4) -- the method, the
    lesson-writing passage inlined between its markers (S-84), and the
    output schema. Read from the files each run, so it cannot drift."""
    path = worker.package_skill_refs() / _METHOD
    if not path.is_file():
        raise EngineError(f"the session miner's method is missing ({_METHOD})")
    method = path.read_text(encoding="utf-8")
    m = _VERSION_RE.search(method)
    version = m.group(1) if m else "unversioned"
    schema = json.dumps(contract.model_output_json_schema(), indent=1, sort_keys=True)
    text = (
        method.rstrip("\n")
        + "\n\n"
        + lesson_writing.inlined()
        + "\n\n"
        + _SCHEMA_LINE
        + "\n"
        + schema
        + "\n"
    )
    return text, version


# --------------------------------------------------------------- run folder


class RunFolder:
    """``<miner dir>/runs/<run_id>/``: the run record, the shared
    instructions, and per session its plan, raw final message, checked
    output and call record. Every file mode 0600 (redacted transcript
    text), written whole (``fsops.private_write``)."""

    def __init__(self, miner_dir: Path, run_id: str) -> None:
        self.path = Path(miner_dir) / "runs" / run_id

    def put(self, rel: str, data: str) -> Path:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        fsops.private_write(target, data)
        return target

    def put_json(self, rel: str, obj: Any) -> Path:
        return self.put(rel, json.dumps(obj, indent=1, sort_keys=True) + "\n")


def _prune_dirs(parent: Path, keep: int, *, spare: str | None = None) -> int:
    """Remove all but the ``keep`` newest folders under ``parent`` (by
    modification time, then name); ``spare`` is never removed."""
    if not parent.is_dir():
        return 0
    dirs = [d for d in parent.iterdir() if d.is_dir() and not d.is_symlink()]
    dirs.sort(key=lambda d: (d.stat().st_mtime, d.name), reverse=True)
    gone = 0
    for d in dirs[keep:]:
        if d.name == spare:
            continue
        shutil.rmtree(d, ignore_errors=True)
        gone += 1
    return gone


def prune_runs(miner_dir: Path, *, keep: int = KEEP_RUNS, current: str | None = None) -> int:
    """Keep the ``keep`` newest run folders, ``current`` always."""
    return _prune_dirs(Path(miner_dir) / "runs", keep, spare=current)


def prune_session_copies(sessions_dir: Path, *, keep: int = KEEP_RUNS) -> int:
    """Keep the ``keep`` newest groups of the surface's transcript copies
    (``<cache>/sessions/miner-session/<run_id>/``): the seam never prunes
    them, and a night makes one group of up to 30 sessions."""
    return _prune_dirs(Path(sessions_dir) / SURFACE, keep)


# -------------------------------------------------------------------- plans


def flag_body(record: Record) -> str:
    """A flagged rule as the spine shows it: ``Trigger: … — Instruction:
    …`` for a behavior record, ``Fact: …`` (and ``— Context: …``) for a
    knowledge one."""
    from ..index.store import _sections  # pyright: ignore[reportPrivateUsage]

    sections = _sections(record.body)
    names = ("Trigger", "Instruction") if record.type == "behavior" else ("Fact", "Context")
    return " — ".join(f"{n}: {sections[n]}" for n in names if sections.get(n))


def spine_flags(result: flags_mod.FlagResult, records: Mapping[str, tuple[Any, Record]]) -> tuple[SpineFlag, ...]:
    """R1b's :class:`flags.FlagResult` as R1a's :class:`SpineFlag`: the
    record's scope, the stretch it matched (``after_turn``), how it matched
    (``lexical+meaning`` when a cosine was computed, else ``lexical``) and
    the rule's text. A flag whose record is gone is left out."""
    out: list[SpineFlag] = []
    for f in result.flags:
        found = records.get(f.record)
        if found is None:
            continue
        record = found[1]
        out.append(
            SpineFlag(
                record=f.record,
                scope=record.scope,
                turn=f.after_turn,
                basis="lexical+meaning" if f.cosine is not None else "lexical",
                body=flag_body(record),
            )
        )
    return tuple(out)


@dataclass
class Plan:
    """One slice, planned. ``skip`` is set for a session that is not
    called (one of ``contract.SKIP_REASONS``); otherwise ``spine`` and
    ``toolset`` are."""

    session_id: str
    path: Path
    file: str
    skip: str | None = None
    spine: Spine | None = None
    toolset: invocation.McpToolset | None = None
    flag_mode: str | None = None
    flag_note: str | None = None


def _first_cwd(entries: Sequence[dict[str, Any] | None]) -> str | None:
    for e in entries:
        if e is not None and isinstance(e.get("cwd"), str) and e["cwd"]:
            return e["cwd"]
    return None


def plan_session(
    path: Path,
    start_line: int,
    n_lines: int,
    end: int | None,
    *,
    home: Path,
    sent: provenance.SentIndex,
    judged_uuids: Container[str],
    spine_tokens: int,
    index: Any,
    records: Mapping[str, tuple[Any, Record]],
    provider: Any = None,
) -> Plan:
    """Plan one ``miner.SessionSlice`` (``start_line``, ``len(lines)``),
    cut at ``end`` = ``miner.halt_point(s).end`` (relative to the slice's
    lines; None when not cut). ``index`` is the run's open lesson index
    (None when it could not be built: no flags), ``records`` the ledger's
    records (``tools.load_records``)."""
    session = spine_mod.read_session(path)
    plan = Plan(session_id=session.session_id, path=path, file=session.file)
    judged = spine_mod.judged_range(start_line, n_lines, end)
    if judged is None:
        plan.skip = "halted"
        return plan
    first, last = judged
    last = min(last, len(session.lines))
    if first > last:
        plan.skip = "nothing-new"
        return plan
    reason = spine_mod.skip_reason(session, first, last, judged_uuids=judged_uuids, sent=sent)
    if reason is not None:
        plan.skip = reason
        return plan
    flags, plan.flag_mode, plan.flag_note = _flags(session, first, last, home, sent, index, records, provider)
    plan.spine = spine_mod.build_spine(
        session, first, last, sent=sent, judged_uuids=judged_uuids, spine_tokens=spine_tokens, flags=flags
    )
    subagents = {sid: session.subagent_dir / f"agent-{sid}.jsonl" for sid in plan.spine.subagents}
    plan.toolset = tools_mod.build_toolset(
        session.path, subagents, last, home, sent=sent, end_ts=plan.spine.end_ts,
        **({} if provider is None else {"provider": provider}),
    )
    return plan


def _flags(
    session: Session,
    first: int,
    last: int,
    home: Path,
    sent: provenance.SentIndex,
    index: Any,
    records: Mapping[str, tuple[Any, Record]],
    provider: Any,
) -> tuple[tuple[SpineFlag, ...], str, str]:
    if index is None:
        return (), "unavailable", "the lesson index could not be built"
    entries = list(session.entries[:last])
    # only the stretches the judged lines reach: a flag on an already-mined
    # stretch could never carry a rule check (its situation must be judged)
    work = [s for s in tools_mod.stretches(entries, sent) if s.end_line >= first]
    cwd = _first_cwd(entries)
    kwargs: dict[str, Any] = {} if provider is None else {"provider": provider}
    result = flags_mod.flag_rules(
        index, work, cwd=Path(cwd) if cwd else Path("/nonexistent"), entries=entries, **kwargs
    )
    return spine_flags(result, records), result.mode, result.note


def session_spec(
    plan: Plan,
    k: int,
    *,
    home: Path,
    run_id: str,
    stage: Path,
    shared: Path,
    timeout: float,
    disallowed_tools: str,
    log: Callable[[str], None],
) -> invocation.SessionSpec:
    """The ``SessionSpec`` of call ``k`` of a run (plan §3.4)."""
    assert plan.spine is not None and plan.toolset is not None
    return invocation.SessionSpec(
        surface=SURFACE,
        prompt=plan.spine.text,
        cwd=stage,
        timeout=timeout,
        containment=invocation.containment_for(
            SURFACE,
            allowed_tools=",".join(plan.toolset.qualified_names),
            disallowed_tools=disallowed_tools,
        ),
        log=log,
        label=f"session {plan.session_id[:8]}",
        ledger_home=home,
        extra_env=invocation.NO_AUTO_MEMORY_ENV,
        append_system_prompt_file=shared,
        exclude_dynamic_sections=True,
        transcript_group=run_id,
        mcp_toolset=plan.toolset,
        sidecar_key=f"{run_id}-{k}",
        skip_orphan_sweep=k != 0,
    )


# -------------------------------------------------------------------- calls


@dataclass
class CallRecord:
    """What one session's call did, attempts included (the run folder's
    ``calls/<session>.json``; the seam's event logs rotate within a night,
    so this is the durable copy). ``stdout`` -- the final message -- is
    written to ``raw/``, never here."""

    session_id: str
    k: int
    started: bool = False
    ok: bool = False
    stdout: str = ""
    attempts: int = 0
    failure: str | None = None
    failure_class: str | None = None
    cost_usd: float | None = None
    turns: int | None = None
    claude_session_id: str | None = None
    usage_first_response: dict | None = None
    usage_session: dict | None = None
    charter_denials: int = 0
    duration_secs: float = 0.0
    transcript: dict | None = None
    attempt_log: list[dict] = field(default_factory=list)

    @property
    def counted_usd(self) -> float:
        """Cost for the runaway guard: an unreported cost counts as a heavy
        call."""
        return HEAVY_CALL_USD * max(1, self.attempts) if self.cost_usd is None else self.cost_usd

    def to_json(self) -> dict:
        return {
            "session": self.session_id,
            "k": self.k,
            "started": self.started,
            "ok": self.ok,
            "attempts": self.attempts,
            "failure": self.failure,
            "failure_class": self.failure_class,
            "cost_usd": self.cost_usd,
            "turns": self.turns,
            "claude_session_id": self.claude_session_id,
            "usage_first_response": self.usage_first_response,
            "usage_session": self.usage_session,
            "charter_denials": self.charter_denials,
            "duration_secs": self.duration_secs,
            "transcript": self.transcript,
            "attempt_log": self.attempt_log,
        }


def _attempt(outcome: Any) -> dict:
    denials = getattr(outcome, "denials", ()) or ()
    cost = getattr(outcome, "cost_usd", None)
    return {
        "ok": bool(getattr(outcome, "ok", False)),
        "failure": getattr(outcome, "failure", None),
        "failure_class": failure_class.outcome_class(outcome),
        "cost_usd": cost if isinstance(cost, (int, float)) else None,
        "turns": getattr(outcome, "turns", None),
        "session_id": getattr(outcome, "session_id", None),
        "charter_denials": sum(1 for d in denials if isinstance(d, dict) and d.get("source") == "charter"),
    }


def _one_call(
    plan: Plan, k: int, make_spec: Callable[[Plan, int], invocation.SessionSpec], call: Callable[[Any], Any]
) -> CallRecord:
    """One session's call, a ``transient`` failure retried once (it skips
    the orphan sweep: a sibling may be running by then)."""
    rec = CallRecord(session_id=plan.session_id, k=k, started=True)
    t0 = time.monotonic()
    spec = make_spec(plan, k)
    costs: list[float] = []
    outcome: Any = None
    for attempt in (1, 2):
        outcome = call(spec)
        rec.attempts = attempt
        info = _attempt(outcome)
        rec.attempt_log.append(info)
        if info["cost_usd"] is not None:
            costs.append(float(info["cost_usd"]))
        if info["ok"] or info["failure_class"] != "transient" or attempt == 2:
            break
        spec = dataclasses.replace(spec, skip_orphan_sweep=True)
    rec.ok = bool(getattr(outcome, "ok", False))
    rec.stdout = str(getattr(outcome, "stdout", "") or "") if rec.ok else ""
    rec.failure = getattr(outcome, "failure", None)
    rec.failure_class = failure_class.outcome_class(outcome)
    rec.cost_usd = round(sum(costs), 6) if costs else None
    rec.turns = getattr(outcome, "turns", None)
    rec.claude_session_id = getattr(outcome, "session_id", None)
    rec.usage_first_response = getattr(outcome, "usage_first_response", None)
    rec.usage_session = getattr(outcome, "usage_session", None)
    rec.charter_denials = sum(a["charter_denials"] for a in rec.attempt_log)
    transcript = getattr(outcome, "transcript", None)
    rec.transcript = transcript if isinstance(transcript, dict) else None
    rec.duration_secs = round(time.monotonic() - t0, 3)
    return rec


def call_sessions(
    plans: Sequence[Plan],
    *,
    make_spec: Callable[[Plan, int], invocation.SessionSpec],
    call: Callable[[Any], Any],
    parallel: int,
    max_usd: float,
) -> tuple[dict[str, CallRecord], bool]:
    """Call every plan (plan §3.5): the first alone, the rest through a pool
    of ``parallel``. Before each call starts, the runaway guard: no call
    starts once ``spent + in_flight × 0.60 >= max_usd``. Returns
    ``({session id: record}, stopped)``; a session not started has a record
    with ``started`` False and keeps its cursor."""
    out: dict[str, CallRecord] = {}
    queue = list(plans)
    spent = 0.0
    lock = threading.Lock()
    stopped = False

    def tripped(in_flight: int) -> bool:
        return spent + in_flight * HEAVY_CALL_USD >= max_usd

    k = 0
    if queue:
        first = queue.pop(0)
        if tripped(0):
            stopped = True
            out[first.session_id] = CallRecord(session_id=first.session_id, k=-1)
        else:
            rec = _one_call(first, k, make_spec, call)
            out[first.session_id] = rec
            spent += rec.counted_usd
        k += 1
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        running: dict[Future[CallRecord], Plan] = {}
        while queue or running:
            while queue and not stopped and len(running) < parallel:
                with lock:
                    if tripped(len(running)):
                        stopped = True
                        break
                plan = queue.pop(0)
                running[pool.submit(_one_call, plan, k, make_spec, call)] = plan
                k += 1
            if stopped:
                for plan in queue:
                    out[plan.session_id] = CallRecord(session_id=plan.session_id, k=-1)
                queue = []
            if not running:
                break
            done, _pending = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                plan = running.pop(fut)
                rec = fut.result()
                out[plan.session_id] = rec
                with lock:
                    spent += rec.counted_usd
    return out, stopped


# ------------------------------------------------------------------- checks


@dataclass
class SessionResult:
    """A called session after its check: ``status`` is the checked
    document's (``ok``, ``bad-output`` or ``failed``); ``error`` says why a
    ``failed`` one failed (``call`` or ``checker-error``)."""

    plan: Plan
    call: CallRecord
    status: str
    checked: dict
    quote_redacted: int = 0
    cut_to_limit: int = 0
    error: str | None = None


def check_session(
    plan: Plan,
    rec: CallRecord,
    *,
    run_id: str,
    model: str,
    method_version: str,
    roots: Sequence[Path],
    judged_uuids: Container[str],
    known_records: Container[str],
    search_mode: str,
    sent: provenance.SentIndex,
) -> SessionResult:
    """The checked output of one called session. A failed call is a
    ``failed`` document; so is a :class:`check.CheckerError` (a defect in
    the checker, never the model's): that one session fails, the run goes
    on."""
    spine = plan.spine
    assert spine is not None

    def failed(error: str) -> SessionResult:
        doc = check_mod.empty_output(
            spine, "failed", run_id=run_id, model=model, method_version=method_version, search_mode=search_mode
        )
        return SessionResult(plan, rec, "failed", doc, error=error)

    if not rec.ok:
        return failed("call")
    try:
        res = check_mod.check_output(
            rec.stdout,
            spine,
            run_id=run_id,
            model=model,
            method_version=method_version,
            roots=roots,
            judged_uuids=judged_uuids,
            known_records=known_records,
            search_mode=search_mode,
            sent=sent,
        )
    except check_mod.CheckerError:
        return failed("checker-error")
    return SessionResult(
        plan, rec, res.checked["status"], res.checked, quote_redacted=res.quote_redacted, cut_to_limit=res.cut_to_limit
    )


def save_plan(folder: RunFolder, plan: Plan) -> None:
    """``plans/<session>.json``: what the call is sent -- the spine, its
    flags, the judged range and the subagent logs."""
    assert plan.spine is not None
    sp = plan.spine
    folder.put_json(
        f"plans/{plan.session_id}.json",
        {
            "session": plan.session_id,
            "file": plan.file,
            "judged": {"first_line": sp.first_line, "last_line": sp.last_line,
                       "first_turn": sp.first_turn, "last_turn": sp.last_turn},
            "typed_turns": len(sp.typed_lines),
            "subagents": dict(sp.subagents),
            "flags": [dataclasses.asdict(f) for f in sp.flags],
            "flag_mode": plan.flag_mode,
            "flag_note": plan.flag_note,
            "spine_tokens_est": sp.tokens_est,
            "over_budget": sp.over_budget,
            "redactions": sp.redactions,
            "spine": sp.text,
        },
    )


def save_result(folder: RunFolder, res: SessionResult) -> None:
    """``raw/<session>.txt`` (the final message, unparsed), ``out/<session>.json``
    (the checked output) and ``calls/<session>.json`` (the call record)."""
    sid = res.plan.session_id
    if res.call.ok:
        folder.put(f"raw/{sid}.txt", res.call.stdout)
    folder.put_json(f"out/{sid}.json", res.checked)
    folder.put_json(f"calls/{sid}.json", {**res.call.to_json(), "out_status": res.status, "error": res.error})


# --------------------------------------------------------------- run record


def run_record(
    *,
    run_id: str,
    started_at: str,
    finished_at: str | None,
    model: str,
    method_version: str,
    engine: EngineSettings,
    search_mode: str,
    status: str,
    plans: Sequence[Plan],
    results: Mapping[str, SessionResult],
    calls: Mapping[str, CallRecord],
    extra: Mapping[str, Any],
) -> dict:
    """``miner-shadow-run/1`` (the name is kept until R4) for one run:
    one row per planned session, in plan order; ``extra`` carries the
    optional ``preview``, ``counts`` and ``judged_uuids`` keys."""
    rows: list[dict] = []
    skipped: dict[str, int] = {}
    totals = {"lessons": 0, "sightings": 0, "rule_checks": 0}
    drops: dict[str, int] = {}
    cost = 0.0
    called = not_run = 0
    for plan in plans:
        row: dict[str, Any] = {
            "session": plan.session_id,
            "file": plan.file,
            "status": "skipped",
            "reason": plan.skip,
            "out_status": None,
            "attempts": 0,
            "failure_class": None,
            "cost_usd": None,
            "turns": None,
            "claude_session_id": None,
            "usage_first_response": None,
            "usage_session": None,
            "charter_denials": 0,
            "duration_secs": 0.0,
        }
        if plan.skip is not None:
            skipped[plan.skip] = skipped.get(plan.skip, 0) + 1
        else:
            row["flag_mode"] = plan.flag_mode
            row["flag_note"] = (plan.flag_note or "")[:200] or None
            row["flags"] = len(plan.spine.flags) if plan.spine else 0
            row["spine_tokens_est"] = plan.spine.tokens_est if plan.spine else 0
            row["over_budget"] = bool(plan.spine and plan.spine.over_budget)
            rec = calls.get(plan.session_id)
            res = results.get(plan.session_id)
            if rec is None or not rec.started:
                row.update(status="not-run", reason="spend-ceiling")
                not_run += 1
            else:
                called += 1
                row.update(
                    status="called",
                    reason=None,
                    out_status=res.status if res else "failed",
                    attempts=rec.attempts,
                    failure_class=rec.failure_class,
                    cost_usd=rec.cost_usd,
                    turns=rec.turns,
                    claude_session_id=rec.claude_session_id,
                    usage_first_response=rec.usage_first_response,
                    usage_session=rec.usage_session,
                    charter_denials=rec.charter_denials,
                    duration_secs=float(rec.duration_secs),
                )
                cost += rec.cost_usd or 0.0
                if res is not None:
                    row["quote_redacted"] = res.quote_redacted
                    row["cut_to_limit"] = res.cut_to_limit
                    row["error"] = res.error
                    for k in totals:
                        totals[k] += len(res.checked[k])
                    for d in res.checked["drops"]:
                        drops[d["reason"]] = drops.get(d["reason"], 0) + 1
        rows.append(row)
    run = {
        "contract": contract.RUN_CONTRACT,
        "run_id": run_id,
        "mode": "night",
        "started_at": started_at,
        "finished_at": finished_at,
        "model": model,
        "method_version": method_version,
        "settings": {"parallel": engine.parallel, "spine_tokens": engine.spine_tokens, "max_usd": engine.max_usd},
        "testset": None,
        "status": status,
        "search_mode": search_mode,
        "sessions": rows,
        "totals": {
            "called": called,
            "skipped": skipped,
            "not_run": not_run,
            "cost_usd": round(cost, 6),
            **totals,
            "drops": drops,
        },
    }
    run.update(extra)
    return run
