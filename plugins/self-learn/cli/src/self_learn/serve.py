"""``self-learn serve`` — the long-lived host process (U-engine Phase 2,
spec ``docs/specs/self-learn/drafts/u-engine-shared-sdk-core-spec.md``
§5). A SCHEDULER of producers, never a watcher (H-5, doc 13 §5): it
starts :func:`miner.run` and :func:`worker.run` as JOBS; each job still
takes its own ``commit_lock`` and commits its own paths under its own
pinned subject, exactly as when a verb or the nightly timer started it.
``serve`` itself never stages, never commits, never pushes, and writes
into ``cache_dir()`` only — three files, corrected 2026-08-27 (gate r2
D-2): ``serve.heartbeat`` (the heartbeat itself), ``serve.poke`` (a
verb's watchdog handoff, a separate file so a write never races the
heartbeat), and ``serve.schedule`` (today's jittered mine target). All
three are ``NOT_REPO_TRUTH``, mirroring ``worker.log``/``miner.spool_dir``.

Jobs run SERIALLY (orchestrator ruling, spec §5.2a): the producers this
unit schedules are already serialised by their own locks
(``worker.lock``, ``miner.spawn.lock``), so a daemon that runs one job at
a time changes nothing about producer semantics — it inherits the
concurrency the locks already impose instead of inventing a second,
weaker one on top of them. Concurrent jobs are OUT (spec §11 row 14).

Portable (§5.7): ``run_forever`` is a plain synchronous loop — it opens
no event loop of its own and calls neither ``run_sync`` nor
``asyncio.run`` (``HP2`` — those stay exactly where the seam already had
them, one level below anything this module calls), so it runs the same
way under systemd, launchd, or a bare terminal, and exits cleanly on
SIGINT/SIGTERM with no job left mid-flight (``HP1``): a job, once
started, always runs to completion before the next tick's stop check.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import signal
import threading
import time
from dataclasses import dataclass, replace as _dataclass_replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

from . import miner, settings, worker
from .ledger import resolve_home

__all__ = [
    "DEFAULT_TICK_SECS",
    "HEARTBEAT_FILENAME",
    "Job",
    "JobRecord",
    "cache_dir_readonly",
    "heartbeat_age_secs",
    "heartbeat_is_fresh",
    "heartbeat_path",
    "is_configured",
    "is_enabled",
    "read_heartbeat",
    "request_poke",
    "run_forever",
    "run_one_job",
    "tick_secs_from_env",
    "unit_dir",
    "write_heartbeat",
]

# --------------------------------------------------------------- schedule

#: Q.14 (builder's call, spec): a one-minute tick is frequent enough
#: that the `doctor` staleness alarm (`SUP2`: "older than one tick
#: interval") fires within a human-noticeable bound, and cheap enough
#: that a daemon idling between the nightly mine pass costs nothing
#: measurable. Env-overridable (`SELF_LEARN_SERVE_TICK_SECS`) the same
#: way every other interval in this codebase is (`worker._timeout_secs`'s
#: convention) — the ACTUAL value used is carried inside the heartbeat
#: itself (`tick_secs`), so `doctor` and `maybe_kick` compare against
#: what THIS daemon is really doing, never a second hardcoded guess that
#: could drift out of sync with an operator's override.
DEFAULT_TICK_SECS = 60.0

#: Mirrors `systemd/self-learn-miner.timer`'s `OnCalendar=*-*-* 03:30` +
#: `RandomizedDelaySec=15m` (both measured, spec §5.2/§8.1).
MINE_HOUR, MINE_MINUTE = 3, 30
MINE_JITTER_SECS = 15 * 60

HEARTBEAT_FILENAME = "serve.heartbeat"
_SCHEDULE_STATE_FILENAME = "serve.schedule"
_POKE_FILENAME = "serve.poke"


@dataclass(frozen=True)
class Job:
    """One schedulable unit. `run` is a zero-argument callable — `serve`
    does not know or care what it does, only that it runs to completion
    (or raises) before the next job starts (§5.2a: SERIAL). `surface`
    is carried through only for logging/heartbeat labelling."""

    name: str
    surface: str
    run: Callable[[], Any]


@dataclass
class JobRecord:
    name: str
    surface: str
    ok: bool
    started_at: float
    finished_at: float
    result: Any = None
    error: str | None = None


def tick_secs_from_env(default: float = DEFAULT_TICK_SECS, *, home: Path | str | None = None) -> float:
    """U-settings Phase 1: resolves through the registry's `serve.
    tick_secs` entry (config.yaml `serve.tick_secs` > env
    `SELF_LEARN_SERVE_TICK_SECS` > `default` -- U-flip 2026-09-01, S-58:
    config wins). `default` overrides the registry
    entry's own built-in default (`dataclasses.replace`) rather than
    being a second, parallel fallback — the one real call site
    (:func:`run_forever`) never passes a non-default value, but the
    parameter stays honoured for any caller that does. `home` defaults
    to :func:`resolve_home`."""
    setting = settings.by_name("serve.tick_secs")
    if default != setting.default:
        setting = _dataclass_replace(setting, default=default)
    value, _source = settings.resolve_setting(home if home is not None else resolve_home(), setting)
    return cast(float, value)


# ----------------------------------------------------------------- heartbeat


def heartbeat_path(cache_dir: Path) -> Path:
    return cache_dir / HEARTBEAT_FILENAME


def write_heartbeat(cache_dir: Path, *, pid: int, next_job: str | None, tick_secs: float | None = None) -> None:
    """`SUP1` — written on every scheduler tick, carrying the tick time,
    the pid and the next scheduled job. Lands in `cache_dir()`, which is
    `NOT_REPO_TRUTH` by the same rule as every other cache write
    (`worker.log`, `miner.spool_dir`, ...) — never inside a git repo, so
    H-5 (doc 13 §5) is untouched by this write.

    Gate r1 N-3: `mkdir(parents=True)` first — a caller must not depend
    on `cache_dir()`'s own `mkdir`/migration side effect having already
    run (`cache_dir_readonly()` deliberately has none). Gate r1 N-2:
    written via a tmp file + `os.replace` — atomic on the same
    filesystem, so a `doctor` read racing a write observes either the
    OLD complete body or the NEW one, never a truncated one that would
    make a live, healthy daemon read as `FAIL`."""
    path = heartbeat_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "ts": time.time(),
            "pid": pid,
            "next_job": next_job,
            "tick_secs": tick_secs if tick_secs is not None else DEFAULT_TICK_SECS,
        }
    )
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def read_heartbeat(cache_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(heartbeat_path(cache_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def heartbeat_age_secs(cache_dir: Path, *, now: float | None = None) -> float | None:
    """`None` iff no heartbeat file exists at all — `SUP2`'s "absent"
    legs; distinguished from a merely STALE one, which returns a real
    (large) number instead."""
    record = read_heartbeat(cache_dir)
    if record is None or not isinstance(record.get("ts"), (int, float)):
        return None
    return (now if now is not None else time.time()) - record["ts"]


def heartbeat_is_fresh(cache_dir: Path, *, now: float | None = None) -> bool:
    """`SUP2`'s "fresh" leg, stated once and shared by `doctor`'s `serve`
    row AND `miner.maybe_kick`'s poke leg (§5.3) — one definition, so the
    two can never silently disagree about what "serve is running" means.
    Fresh iff a heartbeat exists and its age is within ONE tick interval
    of the value THAT heartbeat itself recorded."""
    record = read_heartbeat(cache_dir)
    if record is None:
        return False
    age = heartbeat_age_secs(cache_dir, now=now)
    if age is None:
        return False
    tick = record.get("tick_secs")
    tick = tick if isinstance(tick, (int, float)) and tick > 0 else DEFAULT_TICK_SECS
    return age <= tick


# ------------------------------------------------------------------- poke


def _poke_path(cache_dir: Path) -> Path:
    return cache_dir / _POKE_FILENAME


def request_poke(cache_dir: Path) -> None:
    """§5.3 leg 1 — a verb's watchdog asks the running daemon to mine
    soon instead of spawning its own detached run. No daemon state
    beyond a file (§5.4): the NEXT tick notices it and clears it."""
    _poke_path(cache_dir).write_text(str(time.time()), encoding="utf-8")


def _consume_poke(cache_dir: Path) -> bool:
    path = _poke_path(cache_dir)
    if not path.is_file():
        return False
    path.unlink(missing_ok=True)
    return True


# --------------------------------------------------------- systemd surface


def cache_dir_readonly() -> Path:
    """The SAME path `worker.cache_dir()` resolves, WITHOUT its
    `mkdir`/migration side effects -- so a read-only check (`doctor`'s
    `serve` row, `Doc-0`'s own "computes no verdict, PRINTS NOTHING but
    also WRITES nothing" contract, pinned by `test_ns5_doctor_writes_
    nothing`) never creates the cache directory as a side effect of
    merely asking whether a heartbeat exists. Mirrors `worker.cache_dir`'s
    path formula exactly; if the directory does not exist yet, callers
    read that as "no heartbeat" (`read_heartbeat` already treats a
    missing file as `None`), which is the correct answer regardless.
    (U-settings Phase 1: `resolve_home` moved to a module-level import --
    `tick_secs_from_env` below needs it too.)"""
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    digest = hashlib.sha256(str(resolve_home()).encode("utf-8")).hexdigest()[:8]
    return base / "self-learn" / f"home-{digest}"


def unit_dir() -> Path:
    """Where the reference unit(s) get linked (`install.sh`, `PORT2`).
    Resolved the way systemd itself resolves the user unit search path
    (AMENDED 2026-08-27, U-servehermetic): `SELF_LEARN_SERVE_UNIT_DIR`
    (explicit override, kept) -> else `$XDG_CONFIG_HOME/systemd/user` if
    `XDG_CONFIG_HOME` is set -> else the real `~/.config/systemd/user`
    (HOST SAFETY: this module must never read or write the real one
    during a test run, and never shells out to `systemctl` at all — a
    pure filesystem check costs nothing under `PORT1`, where `systemctl`
    is absent from `PATH` entirely). The docstring used to call
    `SELF_LEARN_SERVE_UNIT_DIR` "the ONE override — the ONLY way" this
    resolves away from the real host; that claim was false the moment a
    test's hermetic `XDG_CACHE_HOME` redirect stopped being mirrored by
    an equivalent `XDG_CONFIG_HOME` redirect here, and a live host unit
    (linked 2026-08-27) turned the gap into 18 failing tests that had
    never been exercised against a linked unit before."""
    override = os.environ.get("SELF_LEARN_SERVE_UNIT_DIR")
    if override:
        return Path(override)
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "systemd" / "user"
    return Path.home() / ".config" / "systemd" / "user"


def is_configured() -> bool:
    """`SUP2`'s "configured" bit: has this machine opted into `serve` by
    linking the reference unit? A machine running `serve` ad hoc from a
    terminal (no unit ever linked) reads as unconfigured — correct,
    because nothing here claims a persistent intent to keep it running,
    so a doctor check catching it momentarily down is a `SKIP`, not an
    alarm."""
    return (unit_dir() / "self-learn-host.service").is_file()


def is_enabled(unit_name: str, wanted_by: str) -> bool:
    """Whether `systemctl --user enable` has been run for `unit_name` —
    detected the same way systemd itself materialises it: a symlink
    under `<wanted_by>.wants/`. Never a `systemctl` subprocess call (same
    portability reasoning as :func:`is_configured`)."""
    return (unit_dir() / f"{wanted_by}.wants" / unit_name).exists()


# --------------------------------------------------------------- scheduling


def _schedule_state_path(cache_dir: Path) -> Path:
    return cache_dir / _SCHEDULE_STATE_FILENAME


def _target_for(now: float) -> float:
    """Pure: the jittered mine-pass target for whatever calendar day
    `now` falls in -- `MINE_HOUR:MINE_MINUTE` local, plus 0..
    `MINE_JITTER_SECS`, deterministic per day (seeded by the day's date
    string, so calling this twice for the same day always agrees). No
    file I/O. `_today_mine_target` below wraps this with the
    schedule-state cache (`Persistent=true` parity); gate r2 N-7's
    `_describe_next` calls it directly to preview TOMORROW's target
    without ever writing today's cache entry early."""
    local = time.localtime(now)
    day_key = time.strftime("%Y-%m-%d", local)
    base = time.mktime(
        (local.tm_year, local.tm_mon, local.tm_mday, MINE_HOUR, MINE_MINUTE, 0, 0, 0, -1)
    )
    jitter = random.Random(day_key).uniform(0, MINE_JITTER_SECS)
    return base + jitter


def _today_mine_target(cache_dir: Path, now: float) -> float:
    """Deterministic per-day jitter, cached so a restart mid-day (or a
    daemon that ticks every minute) does not recompute a different
    target — `Persistent=true` parity with `self-learn-miner.timer`
    (§5.2/§8.1): a target already crossed while the daemon was down (or
    never running) fires at the very next tick instead of waiting for
    tomorrow."""
    local = time.localtime(now)
    day_key = time.strftime("%Y-%m-%d", local)
    path = _schedule_state_path(cache_dir)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = None
    if isinstance(state, dict) and state.get("day") == day_key and isinstance(state.get("target"), (int, float)):
        return state["target"]
    target = _target_for(now)
    path.write_text(json.dumps({"day": day_key, "target": target}), encoding="utf-8")
    return target


def _recently_attempted(now: float) -> bool:
    """Gate r2 N-3': extracted out of `_mine_is_due` so a positive
    control can SPY on this exact call (`monkeypatch.setattr(serve,
    "_recently_attempted", spy)`) rather than replace the whole
    predicate with a hand-written stub -- the r1 shipped control did the
    latter and was proven insensitive: it stayed green under a real
    inverse edit that deleted this very leg, because it never called the
    real function at all. Reads the SAME file `maybe_kick`'s watchdog
    reads (`miner.py:1717`) and `miner.run` touches on every attempt,
    success or failure (`miner.py:1759`)."""
    attempt_iso = miner.last_attempt_iso()
    if not attempt_iso:
        return False
    try:
        attempt_epoch = datetime.fromisoformat(attempt_iso).timestamp()
    except ValueError:
        return False
    return now - attempt_epoch < miner.ATTEMPT_COOLDOWN_SECS


def _mine_is_due(cache_dir: Path, now: float, *, ignore_schedule: bool = False) -> bool:
    """Due iff (a) the SCHEDULE leg says so and (b) the last COMPLETED
    run predates it and (c, gate r1 B-1, spec r6 HP8) no ATTEMPT is
    still inside its own cooldown window -- the SAME guard `maybe_kick`'s
    watchdog already applies (miner.py:1717) against the SAME file
    `miner.run` touches on every attempt, success or failure (:1759).
    Without leg (c), a persistently failing mine never touches
    `miner.last-run` (only `initialized`/`idle`/`held-gate`/the ok path
    do), so it stayed "due" forever and every tick re-ran the full pass.

    `ignore_schedule` (gate r2 B-1'): a poke is a HINT to evaluate NOW,
    never a command to mine -- it bypasses ONLY the daily SCHEDULE leg
    (today's jittered target), never staleness or cooldown. With it
    True, staleness is judged the way `maybe_kick`'s own watchdog
    already judged it BEFORE writing the poke in the first place
    (`_last_run_age_secs() > miner.KICK_AFTER_SECS`) -- so a poke
    consumed later, once conditions may have changed, is re-checked
    against the same rule, not merely trusted from the moment it was
    written. The r1 shape short-circuited `_consume_poke(...) or
    _mine_is_due(...)`, so a poke bypassed staleness AND cooldown both
    -- measured: a ledger mined 0.0s ago still triggered a full mine
    attempt on the very next poke."""
    last_iso = miner.last_run_iso()
    last_epoch = 0.0
    if last_iso:
        try:
            last_epoch = datetime.fromisoformat(last_iso).timestamp()
        except ValueError:
            last_epoch = 0.0

    if ignore_schedule:
        if now - last_epoch <= miner.KICK_AFTER_SECS:
            return False
    else:
        target = _today_mine_target(cache_dir, now)
        if now < target:
            return False
        if last_epoch >= target:
            return False

    if _recently_attempted(now):
        return False
    return True


def _describe_next(cache_dir: Path, now: float) -> str:
    """Gate r2 N-7': once today's target has passed, "next" must mean
    TOMORROW's occurrence, not restate a target that is now in the past
    for the rest of the day (measured: `next: mine at
    2026-08-27T03:39:54` still printed at 05:57 -- true two hours
    earlier, misleading after). Tomorrow's preview uses the pure
    `_target_for` (no file I/O -- a preview, not a commitment; the
    schedule file is only ever written for TODAY, by
    `_today_mine_target` itself, when today's tick actually runs)."""
    target = _today_mine_target(cache_dir, now)
    if now >= target:
        target = _target_for(now + 24 * 60 * 60)
    when = datetime.fromtimestamp(target).isoformat(timespec="seconds")
    return f"mine at {when}"


# ------------------------------------------------------------------- jobs


def run_one_job(cache_dir: Path, job: Job, *, pid: int | None = None, tick_secs: float | None = None) -> JobRecord:
    """Executes `job.run()` to completion — never interrupted mid-flight
    (§5.2a: SERIAL) — then advances the heartbeat (`SUP1`) naming this
    job as the one just run. This is THE scheduler primitive: both
    `run_forever`'s real tick loop and `MS1-seq`'s test drive jobs
    through this exact function, so "a real serve scheduler loop" means
    the same code path in both places."""
    started = time.time()
    try:
        result = job.run()
        record = JobRecord(job.name, job.surface, True, started, time.time(), result=result)
    except Exception as exc:  # noqa: BLE001 — a crashed job must not crash the daemon
        record = JobRecord(job.name, job.surface, False, started, time.time(), error=f"{exc}")
    write_heartbeat(
        cache_dir,
        pid=pid if pid is not None else os.getpid(),
        next_job=job.name,
        tick_secs=tick_secs,
    )
    return record


@contextlib.contextmanager
def _worker_autokick_disabled():
    """Gate r1 M-2: neutralises the `worker.autokick` setting — the SAME
    kill switch a human already has — for the whole span this wraps,
    restored to whatever it held when the span STARTED. TWO producers
    each have a tail that can spawn a detached follow-on behind this
    switch: `miner.run`'s own `worker.kick(home)` call (`N-1`'s shape)
    and `worker.run`'s OWN run-end follow-on window (`_open_window` ->
    `_spawn_window` -> a setsid `Popen`, gate r1 M-2's shape,
    worker.py:3550-3558). `serve` IS the follow-on for both (`HP4`:
    register item #11, closed by construction), so neither producer may
    launch a second one for as long as `serve` itself is already
    driving the next job in-process. `_run_tick` holds this open across
    BOTH the mine job and the worker job that may follow it in the same
    tick — restoring it between them (as the pre-fix code did) reopened
    exactly the window M-2 measured.

    Review Blocker (2026-09-01): under S-58's config-wins flip, a plain
    `os.environ["SELF_LEARN_WORKER_AUTOKICK"] = "0"` write (this
    function's ORIGINAL shape) is silently DEFEATED whenever
    `config.yaml` names `worker.autokick` -- config now outranks that
    env var, so the neutralisation would stop working the moment a
    Phase-2 settings UI ever saved the (defaulted-`True`) key. Routes
    through :func:`settings.override` instead: a rung ABOVE config.yaml
    (not just above env), and -- because it is a real, namespaced env
    var under the hood, not an in-process dict -- one that also reaches
    any DETACHED CHILD this span spawns (`worker.py:1103-1115`'s own
    documented convention: a `start_new_session=True` child inherits a
    flag only via environment; the 2026-08-09 incident this switch
    guards against was itself a self-respawning detached chain, where
    containment has to hold for the whole process tree, not just this
    one process). `settings.override`'s own restore-on-exit contract is
    byte-for-byte what this function relied on before this fix."""
    with settings.override("worker.autokick", False):
        yield


def _run_mine_job(home: Path) -> "miner.MineResult":
    """`N-1`'s negative space: a plain in-process call to `miner.run` —
    never `worker.kick`'s setsid `Popen`. `miner.run` is UNCHANGED
    (files-may-touch §9.3) and, when it lands candidates, still calls
    `worker.kick(home)` at its own tail — neutralised by
    `_worker_autokick_disabled()`, which `_run_tick` holds open across
    THIS call and the worker job that may follow it (gate r1 M-2: the
    window BETWEEN the two must stay closed too, not just this one
    call, so the neutralisation lives one level up now)."""
    return miner.run(home, trigger="serve")


def _run_worker_job(home: Path) -> "worker.RunResult":
    """Gate r1 M-2: `worker.run`'s OWN run-end follow-on is gated only
    by `worker._autokick_disabled()` — reading the SAME
    `SELF_LEARN_WORKER_AUTOKICK` switch `_run_mine_job` neutralises,
    held disabled through THIS call by `_run_tick`'s
    `_worker_autokick_disabled()` span (never restored in between).
    Without that, `serve` scheduling this job is exactly the setsid
    `Popen` `HP4` exists to replace — just launched by the producer it
    called instead of by `serve` itself."""
    return worker.run(home, coalesce=True, no_push=False)


def _run_tick(home: Path, cache_dir: Path, *, now: float, pid: int, tick_secs: float) -> list[JobRecord]:
    """One scheduler tick: at most ONE mine pass, immediately followed
    in-process by the worker follow-on iff it landed candidates
    (`HP4`) — jobs never overlap (§5.2a). Always leaves a fresh
    heartbeat behind, whether or not a job ran (`SUP1`). The whole span
    runs under `_worker_autokick_disabled()` (gate r1 M-2) — set before
    the mine job starts, held through the worker job, restored once
    after both are done (or after just the mine job, if nothing
    landed) — so neither producer's own follow-on tail can spawn a
    detached child while `serve` is already driving the next job.

    Gate r2 B-1': a poke is a HINT to evaluate NOW, never a command to
    mine — consuming it (`_consume_poke`, always called, always clears
    the flag) bypasses ONLY the daily schedule leg (`_mine_is_due(...,
    ignore_schedule=True)`), never staleness or cooldown. The r1 shape
    (`_consume_poke(cache_dir) or _mine_is_due(cache_dir, now)`)
    short-circuited past `_mine_is_due` entirely on a poke, so the
    cooldown added for HP8 was never consulted on that path — measured:
    a ledger mined 0.0s ago still produced a full mine attempt on the
    very next poke, five verb invocations producing five full mine
    passes with `serve` alive."""
    ran: list[JobRecord] = []
    poked = _consume_poke(cache_dir)
    if (poked and _mine_is_due(cache_dir, now, ignore_schedule=True)) or _mine_is_due(cache_dir, now):
        with _worker_autokick_disabled():
            mine_record = run_one_job(
                cache_dir, Job("mine", "miner-reader", lambda: _run_mine_job(home)), pid=pid, tick_secs=tick_secs
            )
            ran.append(mine_record)
            landed = getattr(mine_record.result, "landed", None)
            if landed:
                ran.append(
                    run_one_job(
                        cache_dir, Job("worker", "worker", lambda: _run_worker_job(home)), pid=pid, tick_secs=tick_secs
                    )
                )
    # Gate r1 N-1: `run_one_job`'s own heartbeat write (inside the `with`
    # block above, when a job ran) records the job it just RAN as
    # `next_job` -- correct the instant that job finishes, but stale
    # operator text a moment later ("next: mine" printed by `doctor`
    # right after mine already ran). Overwrite once more, unconditionally,
    # with what `SUP1` actually promises -- "the next scheduled job" --
    # now that this tick's due-check has already run and can describe it.
    write_heartbeat(cache_dir, pid=pid, next_job=_describe_next(cache_dir, now), tick_secs=tick_secs)
    return ran


# --------------------------------------------------------------- the loop


def run_forever(
    home: Path | str,
    *,
    tick_secs: float | None = None,
    cache_dir: Path | None = None,
    max_ticks: int | None = None,
) -> int:
    """`HP1`/`PORT1` — runs in the foreground, exits `0` on SIGTERM and
    on SIGINT with no job left mid-flight: a job always runs to
    completion inside `_run_tick` before the stop flag is next checked.
    `max_ticks` is test-only (bounds an otherwise-infinite loop without
    needing a signal at all).

    Opens no event loop of its own and calls neither `run_sync` nor
    `asyncio.run` anywhere in this module (`HP2`) — `_run_tick` calls
    `miner.run`/`worker.run` as ordinary blocking Python calls, exactly
    the way `cli._cmd_mine`/`cli._cmd_worker` already do today; the
    seam's own `run_sync`/`asyncio.run` (one level below, inside
    `invocation_sdk/backend.py`) sees no ambient loop here to nest
    inside, so `run_sync`'s thread-blocking branch (§4.6 R-2's actual
    hazard) never triggers.

    M-P (sprint 1 audit A14/A13): the `cache_dir=None` fallback now
    resolves `worker.cache_dir(home)` -- namespaced to THIS call's own
    `home` -- instead of the bare, ambient `worker.cache_dir()`; this
    daemon's own housekeeping files (`serve.heartbeat`/`serve.poke`/
    `serve.schedule`) must land under the home it is actually serving,
    not whatever `SELF_LEARN_HOME` happens to be set to in this
    process's environment when the two disagree.

    M-P fold r1: `miner.maybe_kick`'s two heartbeat reads
    (`heartbeat_is_fresh`/`request_poke`) were the same defect on the
    READ side and now thread THEIR OWN `home` too (`maybe_kick` already
    holds one).

    M-P fold r2 (M2): two ambient readers remain, both deliberately,
    neither touched by this move:
    (1) `provider.preflight`'s `serve` doctor row (`_serve_row`) calls
    `cache_dir_readonly()` bare -- `_serve_row` takes no `home` param,
    and adding one would change `preflight`'s signature in
    `provider.py`, another lane's file.
    (2) THIS function's own daemon tick jobs -- `_run_mine_job(home)` ->
    `miner.run(home, ...)` and `_run_worker_job(home)` -> `worker.run(
    home, ...)` -- DO thread `home` into `miner.run`/`worker.run`
    themselves, but those two functions' OWN internal housekeeping
    (`miner.miner_dir()`, `worker._p()`) stays bare by the SAME rule
    this module's `cache_dir` docstring states: `miner_dir`/`_p` are
    themselves confirmed bare writers, so reads paired to them stay
    bare too, not threaded.
    So a `run_forever(A)`/`maybe_kick(A)` pair with `SELF_LEARN_HOME=B`
    writes and reads its OWN `serve.heartbeat`/`serve.poke` consistently
    under A, but `self-learn doctor`'s serve row still reads B's
    `cache_dir_readonly()`/`read_heartbeat()`, and this same daemon's own
    tick-driven `miner.run`/`worker.run` calls still lock/log under B's
    `miner_dir()`/`_p()` -- two documented, accepted residuals, not
    regressions."""
    home = Path(home)
    cd = cache_dir if cache_dir is not None else worker.cache_dir(home)
    secs = tick_secs if tick_secs is not None else tick_secs_from_env(home=home)
    pid = os.getpid()
    stop = threading.Event()

    def _handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        stop.set()

    prev_term = signal.signal(signal.SIGTERM, _handler)
    prev_int = signal.signal(signal.SIGINT, _handler)
    try:
        ticks = 0
        while not stop.is_set():
            _run_tick(home, cd, now=time.time(), pid=pid, tick_secs=secs)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            stop.wait(secs)
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)
    return 0
