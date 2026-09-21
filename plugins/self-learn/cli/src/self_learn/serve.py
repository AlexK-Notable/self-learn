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
import sys
import threading
import time
from dataclasses import dataclass, replace as _dataclass_replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

from . import gitops, intents, miner, overseer, settings, steward, worker
from .overseer import notify as overseer_notify
from .overseer import run as overseer_run
from .primitives import chrono, fsops
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
#: way every other interval in this codebase is (a value that does not
#: parse, or is not above zero, falls back to the default) — the ACTUAL value used is carried inside the heartbeat
#: itself (`tick_secs`), so `doctor` and `maybe_kick` compare against
#: what THIS daemon is really doing, never a second hardcoded guess that
#: could drift out of sync with an operator's override.
DEFAULT_TICK_SECS = 60.0

#: Mirrors `systemd/self-learn-miner.timer`'s `OnCalendar=*-*-* 03:30` +
#: `RandomizedDelaySec=15m` (both measured, spec §5.2/§8.1).
MINE_HOUR, MINE_MINUTE = 3, 30
MINE_JITTER_SECS = 15 * 60
# Shipped timer parity: Sunday at 04:15 local time. ONE definition now
# (U1, S-68): `overseer_run` owns the week boundary the catch-up rule and
# the runner's own same-week guard both read, so a second copy here could
# not drift away from it.
OVERSEER_WEEKDAY = overseer_run.WEEK_WEEKDAY
OVERSEER_HOUR = overseer_run.WEEK_HOUR
OVERSEER_MINUTE = overseer_run.WEEK_MINUTE

HEARTBEAT_FILENAME = "serve.heartbeat"
_SCHEDULE_STATE_FILENAME = "serve.schedule"
_POKE_FILENAME = "serve.poke"
#: U1/A13: one cache-only file recording, per job, the due-check failure
#: that is currently holding it — read by the heartbeat preview (and so by
#: `doctor`'s serve row) and by the once-per-cause notification. Cache, so
#: `NOT_REPO_TRUTH` by the same rule as every other write this module makes.
_HOLDS_FILENAME = "serve.holds.json"

#: S-68: a journal status that means the run HELD before it took ownership
#: of any unit of work. A hold is not an attempt, so it must not arm an
#: attempt cooldown. Deliberately a DENY list: an unrecognised status errs
#: toward "an attempt happened" (at worst one cooldown of extra delay)
#: rather than toward the hot loop an allow-list would produce the day a
#: runner gains a status nobody remembered to add here.
_HOLD_STATUSES = frozenset(
    {"disabled", "idle", "stopped", "dry-run", "held-gate", "held-week-done"}
)


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
    make a live, healthy daemon read as `FAIL`.

    Sprint 2 M-I: now `fsops.atomic_write` (same atomicity gate r1 N-2
    already established, from the shared primitive instead of this
    function's own copy). `fsync=False`: unchanged durability, this
    write never fsync'd before this move either — a heartbeat is
    superseded every tick, so surviving a kernel-level crash was never
    this write's job (contrast `worker._write_window_durable`, fsync'd
    because ITS whole job is to survive a crash). `preserve_mode=False`:
    the ORIGINAL code always opened a brand-new temp file (no chmod), so
    the mode already reset to the process umask default on every tick
    regardless of the previous file's mode."""
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
    fsops.atomic_write(path, payload, fsync=False, preserve_mode=False)


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


def cache_dir_readonly(home: Path | str | None = None) -> Path:
    """The SAME path `worker.cache_dir()` resolves, WITHOUT its
    `mkdir`/migration side effects -- so a read-only check (`doctor`'s
    `serve` row, `Doc-0`'s own "computes no verdict, PRINTS NOTHING but
    also WRITES nothing" contract, pinned by `test_ns5_doctor_writes_
    nothing`) never creates the cache directory as a side effect of
    merely asking whether a heartbeat exists. Mirrors `worker.cache_dir`'s
    path formula exactly; if the directory does not exist yet, callers
    read that as "no heartbeat" (`read_heartbeat` already treats a
    missing file as `None`), which is the correct answer regardless.
    An explicit `home` selects that ledger's namespace; without one the
    ambient resolved home is preserved for existing callers."""
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    resolved_home = Path(home).expanduser() if home is not None else resolve_home()
    digest = hashlib.sha256(str(resolved_home).encode("utf-8")).hexdigest()[:8]
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


def is_configured(unit_name: str = "self-learn-host.service") -> bool:
    """`SUP2`'s "configured" bit: has this machine opted into `unit_name`
    by linking the reference unit? A machine running the unit's command
    ad hoc from a terminal (no unit ever linked) reads as unconfigured —
    correct, because nothing here claims a persistent intent to keep it
    running, so a doctor check catching it momentarily down is a
    `SKIP`, not an alarm.

    M-N: generalized to take a unit name (was hardcoded to the host
    unit) so the `ui` doctor row can ask the same question about
    `self-learn-ui.service`; the default preserves every existing
    caller's behaviour unchanged."""
    return (unit_dir() / unit_name).is_file()


def is_enabled(unit_name: str, wanted_by: str) -> bool:
    """Whether `systemctl --user enable` has been run for `unit_name` —
    detected the same way systemd itself materialises it: a symlink
    under `<wanted_by>.wants/`. Never a `systemctl` subprocess call (same
    portability reasoning as :func:`is_configured`)."""
    return (unit_dir() / f"{wanted_by}.wants" / unit_name).exists()


# --------------------------------------------------------------- scheduling


def _schedule_state_path(cache_dir: Path) -> Path:
    return cache_dir / _SCHEDULE_STATE_FILENAME


# ------------------------------------------- due-check holds (A13, S-68)


def _short_cause(exc: BaseException) -> str:
    """One line, bounded: `doctor`'s serve row and a notification both
    carry this, and a traceback's worth of text in either is unreadable."""
    return " ".join(f"{type(exc).__name__}: {exc}".split())[:200]


def _holds_path(cache_dir: Path) -> Path:
    return cache_dir / _HOLDS_FILENAME


def _read_holds(cache_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads(_holds_path(cache_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_holds(cache_dir: Path, holds: dict[str, Any]) -> None:
    path = _holds_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(
        path, json.dumps(holds, sort_keys=True), fsync=False, preserve_mode=False
    )


def _held_cause(cache_dir: Path, job: str, now: float) -> str | None:
    """The cause currently holding `job`, or `None` — a hold expires with
    its cooldown, so a stale entry never keeps naming a job as held."""
    row = _read_holds(cache_dir).get(job)
    if not isinstance(row, dict):
        return None
    at = row.get("at")
    if not isinstance(at, (int, float)):
        return None
    if now - float(at) >= miner.ATTEMPT_COOLDOWN_SECS:
        return None
    cause = row.get("cause")
    return cause if isinstance(cause, str) else "unknown cause"


def _journal_due_check_error(home: Path, job: str, cause: str) -> None:
    """Record the HOLD in that job's OWN cache journal, in that journal's
    own timestamp key (`ts` for the steward, `at` for the overseer), so
    the same reader that finds its attempts finds this too. The mine job
    has no JSON journal of this shape; the holds file above is its
    record."""
    entry = {"status": "due-check-error", "job": job, "reason": cause}
    try:
        if job == "steward":
            steward._journal(home, {"ts": chrono.now_iso(), **entry})
        elif job == "overseer":
            overseer_run._journal(Path(home), {"at": chrono.now_iso(), **entry})
    except Exception:  # noqa: BLE001 — a journal write must never widen the failure
        pass


def _notify_due_hold(home: Path, job: str, cause: str) -> None:
    """Once per DISTINCT cause, never once per tick. Goes through the
    shipped notification path unchanged (its detached helper owns the
    action wait and its own `timeout(1)` bound); this module never calls
    `notify-send` itself."""
    try:
        overseer_notify.send(
            Path(home),
            "routine",
            f"self-learn serve: the {job} job is not running — its due check "
            f"failed: {cause}",
            [],
        )
    except Exception:  # noqa: BLE001 — a notification must never widen the failure
        pass


def _hold_due_check(
    home: Path, cache_dir: Path, job: str, now: float, cause: str
) -> None:
    holds = _read_holds(cache_dir)
    previous = holds.get(job)
    notified = previous.get("notified_cause") if isinstance(previous, dict) else None
    holds[job] = {"at": now, "cause": cause, "notified_cause": notified}
    _write_holds(cache_dir, holds)
    _journal_due_check_error(home, job, cause)
    print(
        f"serve: {job} due check failed — {cause}; holding that job for "
        f"{int(miner.ATTEMPT_COOLDOWN_SECS)}s. Every other job is unaffected.",
        file=sys.stderr,
    )
    if notified != cause:
        _notify_due_hold(home, job, cause)
        holds[job]["notified_cause"] = cause
        _write_holds(cache_dir, holds)


def _due_or_hold(
    job: str, home: Path, cache_dir: Path, now: float, predicate: Callable[[], bool]
) -> bool:
    """A13: the ONE seam every due check in `_run_tick` is evaluated
    through. A raise is logged, recorded as a HOLD, and read as "not due
    this tick" — it never escapes into the tick loop, where one exception
    ends the whole daemon and ends it again on every restart while the
    cause persists (and, S-68, it is never counted as an attempt: a check
    that could not read the state took ownership of nothing).

    While a hold is inside its cooldown the predicate is not called at
    ALL, so a wedged git read is retried once every
    `miner.ATTEMPT_COOLDOWN_SECS`, not once every tick. A predicate that
    succeeds clears its job's hold."""
    if _held_cause(cache_dir, job, now) is not None:
        return False
    try:
        due = bool(predicate())
    except Exception as exc:  # noqa: BLE001 — that is this function's whole job
        # U2 nit on U1: recording the hold is itself I/O (a cache write, a
        # journal append, a notification) and can raise. If it did, the
        # raise escaped this seam and skipped every REMAINING job of the
        # tick — the exact whole-daemon blast radius A13 exists to stop,
        # one level in. A failure to RECORD a hold still means "not due".
        try:
            _hold_due_check(home, cache_dir, job, now, _short_cause(exc))
        except Exception as record_exc:  # noqa: BLE001 — never widen a hold
            print(
                f"serve: {job} due check failed and its hold could not be "
                f"recorded — {_short_cause(record_exc)}; treating that job as "
                "not due this tick. Every other job is unaffected.",
                file=sys.stderr,
            )
        return False
    holds = _read_holds(cache_dir)
    if job in holds:
        holds.pop(job, None)
        _write_holds(cache_dir, holds)
    return due


def _holds_text(cache_dir: Path, now: float) -> str:
    """The heartbeat's (and so `doctor`'s serve row's) rendering of every
    job currently held by a failing due check."""
    held = [
        f"{job} ({_held_cause(cache_dir, job, now)})"
        for job in ("mine", "steward", "overseer")
        if _held_cause(cache_dir, job, now) is not None
    ]
    return f"; holding: {', '.join(held)}" if held else ""


# ------------------------------------------ attempt journals (A19, A22)


def _attempt_epoch(stamp: str, now: float) -> float:
    """S-68: an unparseable or future-dated attempt timestamp reads as
    "attempted NOW". The two failure modes it replaces are the ones
    measured on this scheduler: a bad value parsed to epoch 0 made the
    job due on every single tick, and a future value made it due never."""
    try:
        epoch = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return now
    return now if epoch > now else epoch


def _journal_attempt_epoch(path: Path, now: float) -> float | None:
    """The time of the most recent line in a runner's cache journal that
    records an ATTEMPT — the newest line whose status is not a hold
    (`_HOLD_STATUSES`). `None` when the journal holds no attempt at all."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if isinstance(status, str) and status in _HOLD_STATUSES:
            continue
        stamp = row.get("at") or row.get("ts")
        if not isinstance(stamp, str):
            continue
        return _attempt_epoch(stamp, now)
    return None


def _steward_recently_attempted(cache_dir: Path, now: float) -> bool:
    """S-68's ordering rule: the steward's cooldown test reads the cache
    attempt journal ONLY, so it can be evaluated before any git read."""
    epoch = _journal_attempt_epoch(cache_dir / "steward" / "journal.jsonl", now)
    return epoch is not None and now - epoch < miner.ATTEMPT_COOLDOWN_SECS


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


def _describe_next(home: Path, cache_dir: Path, now: float) -> str:
    """Gate r2 N-7': once today's target has passed, "next" must mean
    TOMORROW's occurrence, not restate a target that is now in the past
    for the rest of the day (measured: `next: mine at
    2026-08-27T03:39:54` still printed at 05:57 -- true two hours
    earlier, misleading after). Tomorrow's preview uses the pure
    `_target_for` (no file I/O -- a preview, not a commitment; the
    schedule file is only ever written for TODAY, by
    `_today_mine_target` itself, when today's tick actually runs).

    A13/U1: this text is the heartbeat's `next_job`, which is also what
    `doctor`'s serve row prints, so it must never raise and it must name
    a job that a failing due check is currently holding — otherwise the
    only operator-visible surface says "next: steward at ..." about a job
    that has not been evaluated for hours. Each leg is guarded
    separately: one broken preview never blanks the other two."""
    try:
        target = _today_mine_target(cache_dir, now)
        if now >= target:
            target = _target_for(now + 24 * 60 * 60)
        when = datetime.fromtimestamp(target).isoformat(timespec="seconds")
    except Exception as exc:  # noqa: BLE001 — a preview must never raise
        when = f"held: {_short_cause(exc)}"
    try:
        # This heartbeat preview reads one small cached marker, never the case store.
        last_iso = steward.last_run_iso(home)
        # S-68: the preview reads its timestamp through the SAME rule the
        # real predicate uses, so "steward at ..." cannot disagree with it.
        last_epoch = _attempt_epoch(last_iso, now) if last_iso is not None else 0.0
        cooldown_value, _source = settings.resolve_setting(
            home, settings.by_name("steward.cooldown_secs")
        )
        cooldown = cast(int | float | str, cooldown_value)
        steward_when = datetime.fromtimestamp(
            max(now, last_epoch + float(cooldown))
        ).isoformat(timespec="seconds")
    except Exception as exc:  # noqa: BLE001 — a preview must never raise
        steward_when = f"held: {_short_cause(exc)}"
    try:
        # Heartbeats stay cache-only and never walk committed case manifests.
        overseer_when = datetime.fromtimestamp(
            _overseer_target_for(now)
        ).isoformat(timespec="seconds")
    except Exception as exc:  # noqa: BLE001 — a preview must never raise
        overseer_when = f"held: {_short_cause(exc)}"
    return (
        f"mine at {when}; steward at {steward_when} when committed obligations exist; "
        f"overseer at {overseer_when}" + _holds_text(cache_dir, now)
    )


def _eligible_proposal_paths(home: Path) -> list[Path]:
    return [entry.proposal_path for entry, _proposal in steward._eligible_proposals(home)]


def _proposal_commit_epoch(home: Path, path: Path) -> float:
    try:
        rel = path.resolve().relative_to(home.resolve())
    except ValueError:
        return 0.0
    proc = gitops._git(home, "log", "-1", "--format=%ct", "--", str(rel))
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _steward_is_due(home: Path, cache_dir: Path, now: float) -> bool:
    """Apply the committed-obligation OR predicate outside cooldown and STOP.

    S-68 ordering (U1): the CACHE attempt-journal cooldown is evaluated
    first, before anything that reads git. Before this, the first thing
    this predicate did was walk committed manifests, so a wedged git read
    was re-entered on every 60-second tick with no cooldown able to stop
    it. The committed `last_attempt_at` / last-run-marker test below is
    kept as the SECOND check, because the cache is not durable and the
    committed timestamp is."""
    enabled, _source = settings.resolve_setting(home, settings.by_name("steward.enabled"))
    if not enabled:
        return False
    if _steward_recently_attempted(cache_dir, now):
        return False
    if intents.classify_status(home).stopped:
        return False
    manifests = steward.committed_manifests(home)
    unfinished = [row for row in manifests if row.get("status") != "complete"]
    reconsider, _predecessors = steward._reconsider_proposals(home)
    proposal_paths = _eligible_proposal_paths(home)
    if not unfinished and not reconsider and not proposal_paths:
        return False
    attempts = [str(row.get("last_attempt_at")) for row in unfinished if row.get("last_attempt_at")]
    last_iso = max(attempts) if attempts else steward.last_run_iso(home)
    if last_iso is None:
        return True
    last_epoch = _attempt_epoch(last_iso, now)
    cooldown_value, _source = settings.resolve_setting(
        home, settings.by_name("steward.cooldown_secs")
    )
    cooldown = cast(int | float | str, cooldown_value)
    if now - last_epoch < float(cooldown):
        return False
    if unfinished or reconsider:
        return True
    return any(_proposal_commit_epoch(home, path) > last_epoch for path in proposal_paths)


def _overseer_target_for(now: float) -> float:
    """Return the next Sunday 04:15 local target at or after ``now``."""
    local = time.localtime(now)
    days = (OVERSEER_WEEKDAY - local.tm_wday) % 7
    target = time.mktime(
        (
            local.tm_year,
            local.tm_mon,
            local.tm_mday + days,
            OVERSEER_HOUR,
            OVERSEER_MINUTE,
            0,
            0,
            0,
            -1,
        )
    )
    if target < now:
        target += 7 * 24 * 60 * 60
    return target


def overseer_next_iso(home: Path | str, *, now: float | None = None) -> str:
    """The next calendar target; committed unfinished work is reported as
    now. A13: this reads git, so it must not raise either — a failure is
    reported as a held job naming its cause, never propagated into the
    caller (`status --json`, the heartbeat preview)."""
    resolved = Path(home)
    current = time.time() if now is None else now
    try:
        unfinished = overseer.has_unfinished_work(resolved)
    except Exception as exc:  # noqa: BLE001 — a preview must never raise
        return f"held: {_short_cause(exc)}"
    target = current if unfinished else _overseer_target_for(current)
    return datetime.fromtimestamp(target).isoformat(timespec="seconds")


def _overseer_recently_attempted(cache_dir: Path, now: float) -> bool:
    """Apply the miner's bounded retry interval to every overseer attempt.

    U1: reads the newest line that records an ATTEMPT, skipping holds —
    before this, a `disabled` or `stopped` line (a run that did nothing at
    all) armed the cooldown exactly like a real attempt."""
    epoch = _journal_attempt_epoch(cache_dir / "overseer.journal", now)
    return epoch is not None and now - epoch < miner.ATTEMPT_COOLDOWN_SECS


def _overseer_is_due(home: Path, cache_dir: Path, now: float) -> bool:
    """Weekly opt-in predicate, with committed unfinished work taking
    priority, and the A16 catch-up rule (S-68,
    `13-hosting-and-separation.md` §5): due on the first tick at or after
    the most recent Sunday 04:15 local for which that week is not done,
    whatever the weekday, so a machine that was off all Sunday runs the
    missed week on Monday instead of skipping it in silence.

    The catch-up applies only once a previous run exists (coverage's
    `last_run_at` is not null; orchestrator ruling 2026-09-19). An
    overseer that has NEVER run stays on the calendar rule — due at the
    next Sunday 04:15 — so flipping `overseer.enabled` on a Wednesday
    cannot trigger an immediate unattended first run; `self-learn overseer
    run` remains the way to start it by hand.

    S-68 ordering: the cache attempt-journal cooldown is evaluated before
    any git read."""
    enabled, _source = settings.resolve_setting(home, settings.by_name("overseer.enabled"))
    if not enabled:
        return False
    if _overseer_recently_attempted(cache_dir, now):
        return False
    if intents.classify_status(home).stopped:
        return False
    if overseer.has_unfinished_work(home):
        return True
    if overseer_run.previous_run_exists(home):
        return not overseer_run.week_done(home, overseer_run.week_boundary(now))
    local = time.localtime(now)
    if local.tm_wday != OVERSEER_WEEKDAY:
        return False
    target = time.mktime(
        (
            local.tm_year, local.tm_mon, local.tm_mday,
            OVERSEER_HOUR, OVERSEER_MINUTE, 0, 0, 0, -1,
        )
    )
    if now < target:
        return False
    # S-68: a week that is DONE is never due, on the calendar branch too.
    # Without this, an overseer that has never completed a run and whose
    # week was closed at `runs.attempt_cap` answered "due" for the rest of
    # Sunday: `run` replies `held-week-done`, which is a HOLD and therefore
    # arms no cooldown, so the job was re-entered on every 60-second tick.
    # `previous_run_exists` is false in exactly that state, so the branch
    # above never got the chance to say so.
    if overseer_run.week_done(home, overseer_run.week_boundary(now)):
        return False
    last_iso = overseer_run.last_run_iso(home)
    if last_iso is None:
        return True
    return _attempt_epoch(last_iso, now) < target


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


def _run_steward_job(home: Path) -> "steward.RunResult":
    return steward.run(home)


def _run_overseer_job(home: Path) -> "overseer_run.RunResult":
    return overseer_run.run(home)


def _log_stopped_refusal(job_name: str, stopped: list[str]) -> None:
    """§7.2a.7 (REQUIRED): "a job refused by the guard logs the refusal
    on its own line naming the intent id ... a refusal that reaches
    only the job record and the journal does not satisfy this
    section." `miner.run`/`worker.run` already log a STOP to their OWN
    per-surface log file internally (`miner.log`/`worker.log`) -- gate
    r1 ruled that insufficient on its own, since nothing tails those
    files live. This is `serve`'s OWN line, on `run_forever`'s own
    stderr (the daemon's foreground output stream), naming the real id
    -- MINOR-2's own id-interpolation fix applies here too, since
    every entry in `stopped` is already `"<id>: <reason>"`."""
    for line in stopped:
        intent_id = line.split(":", 1)[0]
        print(
            f"serve: {job_name} job refused — {line}; every ledger write "
            "refuses until it is cleared. Run 'self-learn reconcile "
            f"--clear-intent {intent_id}' after inspecting the offender.",
            file=sys.stderr,
        )


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
    with _worker_autokick_disabled():
        if _due_or_hold(
            "mine",
            home,
            cache_dir,
            now,
            lambda: (poked and _mine_is_due(cache_dir, now, ignore_schedule=True))
            or _mine_is_due(cache_dir, now),
        ):
            mine_record = run_one_job(
                cache_dir, Job("mine", "miner-reader", lambda: _run_mine_job(home)), pid=pid, tick_secs=tick_secs
            )
            ran.append(mine_record)
            _log_stopped_refusal("mine", getattr(mine_record.result, "stopped", None) or [])
            landed = getattr(mine_record.result, "landed", None)
            if landed:
                worker_record = run_one_job(
                    cache_dir, Job("worker", "worker", lambda: _run_worker_job(home)), pid=pid, tick_secs=tick_secs
                )
                ran.append(worker_record)
                _log_stopped_refusal("worker", getattr(worker_record.result, "stopped", None) or [])
        if _due_or_hold(
            "steward", home, cache_dir, now, lambda: _steward_is_due(home, cache_dir, now)
        ):
            steward_record = run_one_job(
                cache_dir,
                Job("steward", "steward", lambda: _run_steward_job(home)),
                pid=pid,
                tick_secs=tick_secs,
            )
            ran.append(steward_record)
            _log_stopped_refusal(
                "steward", getattr(steward_record.result, "stopped", None) or []
            )
        if _due_or_hold(
            "overseer", home, cache_dir, now, lambda: _overseer_is_due(home, cache_dir, now)
        ):
            overseer_record = run_one_job(
                cache_dir,
                Job("overseer", "overseer", lambda: _run_overseer_job(home)),
                pid=pid,
                tick_secs=tick_secs,
            )
            ran.append(overseer_record)
            _log_stopped_refusal(
                "overseer", getattr(overseer_record.result, "stopped", None) or []
            )
    # Gate r1 N-1: `run_one_job`'s own heartbeat write (inside the `with`
    # block above, when a job ran) records the job it just RAN as
    # `next_job` -- correct the instant that job finishes, but stale
    # operator text a moment later ("next: mine" printed by `doctor`
    # right after mine already ran). Overwrite once more, unconditionally,
    # with what `SUP1` actually promises -- "the next scheduled job" --
    # now that this tick's due-check has already run and can describe it.
    write_heartbeat(
        cache_dir,
        pid=pid,
        next_job=_describe_next(home, cache_dir, now),
        tick_secs=tick_secs,
    )
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

    M-P fold r2 (M2): one ambient reader remains deliberately: THIS
    function's own daemon tick jobs -- `_run_mine_job(home)` ->
    `miner.run(home, ...)` and `_run_worker_job(home)` -> `worker.run(
    home, ...)` -- DO thread `home` into `miner.run`/`worker.run`
    themselves, but those two functions' OWN internal housekeeping
    (`miner.miner_dir()`, `worker._p()`) stays bare by the SAME rule
    `worker.cache_dir`'s docstring states: `miner_dir`/`_p` are
    themselves confirmed bare writers, so reads paired to them stay
    bare too, not threaded.
    So a `run_forever(A)`/`maybe_kick(A)` pair with `SELF_LEARN_HOME=B`
    writes and reads its OWN `serve.heartbeat`/`serve.poke` consistently
    under A, and `self-learn doctor` reads A when passed A; this daemon's
    tick-driven `miner.run`/`worker.run` calls still lock/log under B's
    `miner_dir()`/`_p()` -- the one documented, accepted residual."""
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
            # A13 backstop: `_due_or_hold` already contains every due
            # check, and `run_one_job` already contains every job, so
            # nothing is EXPECTED to reach here -- but an exception that
            # does must cost one tick, not the daemon. Before this, a
            # raise here ended the whole process (miner, worker, steward
            # and overseer together) and ended it again on every restart
            # while its cause persisted. SIGTERM/SIGINT and `max_ticks`
            # are untouched: the counter below advances either way.
            try:
                _run_tick(home, cd, now=time.time(), pid=pid, tick_secs=secs)
            except Exception as exc:  # noqa: BLE001 — a tick must never end the daemon
                print(
                    f"serve: tick failed — {_short_cause(exc)}; continuing "
                    "with the next tick.",
                    file=sys.stderr,
                )
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            stop.wait(secs)
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)
    return 0
