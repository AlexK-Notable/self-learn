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
Once a day (S-99) it also asks ``cache_gc.prune`` to delete, from
the cache ROOT, per-home cache directories whose ledger home no longer
exists and host lock files nobody holds -- cache only, never the home it
serves.

A daily PREMISES job (S-104, `premise_sweep.py`) also runs, before
the steward: it re-reads what placed lessons rest on, writes only its own cache
folder (`<cache>/premises/`) and, for a premise marked `on_change: refresh`, one
ledger commit under the commit lock (the job commits its own writes, as the
others do); it never calls a model.

Self-maintenance (L6, 2026-10-31; 13 §5). Between ticks, never during a
job, ``serve`` compares a hash of the package's source files with the one
it started on; once a changed hash has read the same on two ticks and the
new code imports, it re-executes itself with the same command line, so a
landing needs no hand restart (``serve.restart_on_new_code``, default on,
is the rollback switch). The hash covers the uv project's ``pyproject.toml``
and ``uv.lock`` too: when they changed, ``serve`` runs ``uv sync`` first,
the step the unit's ``uv run`` takes and a re-exec skips. New code it
cannot run is retried hourly and leaves a project notice saying why. A host unit file that changed after the process
started cannot be picked up that way; it gets a project notice naming the
``daemon-reload`` and restart. A daily ``maintenance`` job recompiles the
targets that carry markers with no compile record (``maintenance.py``).

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
import traceback
from dataclasses import dataclass, replace as _dataclass_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

from . import (
    attribution, cache_gc, cases, gitops, intents, maintenance, miner, notices, overseer,
    premise_sweep, settings, steward, steward_inputs, worker,
)
from . import hosts as hosts_mod
from .overseer import notify as overseer_notify
from .overseer import run as overseer_run
from .primitives import chrono, fsops, procs
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


def write_heartbeat(
    cache_dir: Path,
    *,
    pid: int,
    next_job: str | None,
    tick_secs: float | None = None,
    running: str | None = None,
    running_since: float | None = None,
) -> None:
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
    body: dict[str, Any] = {
        "ts": time.time(),
        "pid": pid,
        "next_job": next_job,
        "tick_secs": tick_secs if tick_secs is not None else DEFAULT_TICK_SECS,
    }
    if running is not None:
        # 2026-09-26: the job running right now and since when (epoch
        # seconds). Absent between jobs; every existing key is unchanged.
        body["running"] = running
        body["running_since"] = running_since
    fsops.atomic_write(path, json.dumps(body), fsync=False, preserve_mode=False)


class _RunningHeartbeat:
    """Keeps the heartbeat fresh while one job runs (2026-09-26). Before,
    it was written only between jobs, so it read stale during every run
    for as long as the run lasted. A helper thread rewrites it every half
    tick -- so its age stays inside the one tick `heartbeat_is_fresh`
    allows -- naming the running job and carrying the last `next_job`
    unchanged. It only ever writes the cache heartbeat file."""

    def __init__(
        self, cache_dir: Path, *, pid: int, job: str, tick_secs: float | None
    ) -> None:
        self._cache_dir = cache_dir
        self._pid = pid
        self._job = job
        self._tick_secs = tick_secs
        tick = tick_secs if tick_secs is not None and tick_secs > 0 else DEFAULT_TICK_SECS
        self._interval = tick / 2
        self._since = time.time()
        self._next_job = (read_heartbeat(cache_dir) or {}).get("next_job")
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name=f"serve-heartbeat-{job}", daemon=True
        )

    def _beat(self) -> None:
        try:
            write_heartbeat(
                self._cache_dir, pid=self._pid, next_job=self._next_job,
                tick_secs=self._tick_secs, running=self._job, running_since=self._since,
            )
        except OSError:
            pass  # a missed beat is only a stale reading, never a failed job

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._beat()

    def __enter__(self) -> "_RunningHeartbeat":
        self._beat()
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join()


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
        for job in ("mine", "hosts", "premises", "maintenance", "steward", "overseer")
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
    (`_HOLD_STATUSES`) and that a dry run did not write (`"dry_run":
    true`). `None` when the journal holds no attempt at all."""
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
        # 2026-09-26 (agenda item 25): a row a `--dry-run` wrote (its
        # `model-log` lines included) is a rehearsal, never an attempt.
        if row.get("dry_run") is True:
            continue
        stamp = row.get("at") or row.get("ts")
        if not isinstance(stamp, str):
            continue
        return _attempt_epoch(stamp, now)
    return None


def _steward_journal(cache_dir: Path) -> Path:
    return cache_dir / "steward" / "journal.jsonl"


def _steward_recently_attempted(cache_dir: Path, now: float) -> bool:
    """S-68's ordering rule: the steward's cooldown test reads the cache
    attempt journal ONLY, so it can be evaluated before any git read.
    S-115: the interval is `steward.RETRY_SECS` (2 h, the same as
    `miner.ATTEMPT_COOLDOWN_SECS`), and it is the whole retry rule for an
    unfinished run."""
    epoch = _journal_attempt_epoch(_steward_journal(cache_dir), now)
    return epoch is not None and now - epoch < steward.RETRY_SECS


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
        # S-115: cache-only, like the overseer's preview -- the
        # attempt journal and the last-run marker, never the case store -- and
        # through the same rules the predicate uses, so the instant it prints
        # is the instant the steward becomes due.
        steward_epoch, steward_why = _steward_next(home, cache_dir, now)
        steward_when = (
            datetime.fromtimestamp(steward_epoch).isoformat(timespec="seconds")
            + f" {steward_why}"
        )
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
        f"mine at {when}; steward at {steward_when}; "
        f"overseer at {overseer_when}" + _holds_text(cache_dir, now)
    )


#: S-115: the steward's nightly slot opens when the night's mine
#: pass has finished, or this long after the mine target when it has not
#: (the mine failed, is off, or is still running), so a broken mine never
#: costs the steward its night.
STEWARD_MINE_GRACE_SECS = 3 * 60 * 60


def _mine_finished_epoch() -> float | None:
    """When the last mine pass finished (`miner.last-run`), or ``None``."""
    iso = miner.last_run_iso()
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _day_target(now: float, days: int) -> float:
    """The jittered mine target *days* calendar days from *now*'s date
    (noon of that day picks the date, so a 23- or 25-hour day cannot pick
    the wrong one). Pure, like :func:`_target_for`."""
    local = time.localtime(now)
    noon = time.mktime(
        (local.tm_year, local.tm_mon, local.tm_mday + days, 12, 0, 0, 0, 0, -1)
    )
    return _target_for(noon)


def _mine_target_today(cache_dir: Path, now: float) -> float:
    """Today's mine target as the mine itself reads it (the schedule state),
    or computed when the cache cannot be written: the steward's due check
    must not fail on a cache the mine's own check would have created."""
    try:
        return _today_mine_target(cache_dir, now)
    except OSError:
        return _target_for(now)


def _steward_slot(cache_dir: Path, now: float) -> float:
    """S-115: the START of the newest nightly steward slot that is
    open at *now* -- the mine target that begins it. Today's slot opens
    once today's mine pass has finished after its target (`miner.last-run`
    newer than the target), or at the target plus
    :data:`STEWARD_MINE_GRACE_SECS` whatever the mine did; until then the
    newest open slot is yesterday's (always open by now). A run that started
    at or after the returned instant has taken that slot."""
    today = _mine_target_today(cache_dir, now)
    if now >= today:
        finished = _mine_finished_epoch()
        if (finished is not None and finished >= today) or now >= today + STEWARD_MINE_GRACE_SECS:
            return today
    return _day_target(now, -1)


def _next_slot_open(cache_dir: Path, now: float, taken_from: float | None) -> float:
    """The preview's half of :func:`_steward_slot`: the earliest instant at
    or after *now* at which a slot not yet taken by a start at
    *taken_from* is open. Today's slot, before the mine has finished, is
    shown at the mine target: the slot opens between it and the grace."""
    today = _mine_target_today(cache_dir, now)
    if taken_from is None or taken_from < _steward_slot(cache_dir, now):
        return now
    if taken_from >= today:
        return _day_target(now, 1)
    return max(now, today)


def _journal_run_starts(path: Path, now: float) -> tuple[float | None, float | None]:
    """The steward cache journal's `attempt-start` rows, read newest first:
    ``(first, newest)`` -- the FIRST `attempt-start` of the newest run (the
    cache's view of when that run selected its inputs) and the NEWEST
    `attempt-start` of all (when the latest attempt began). ``(None, None)``
    when the journal holds none. Dry-run rows are never attempts."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    newest_run: str | None = None
    newest: float | None = None
    first: float | None = None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("status") != "attempt-start":
            continue
        if row.get("dry_run") is True:
            continue
        run_id = row.get("run_id")
        stamp = row.get("at") or row.get("ts")
        if not isinstance(stamp, str):
            continue
        epoch = _attempt_epoch(stamp, now)
        if newest_run is None:
            newest_run = run_id if isinstance(run_id, str) else ""
            newest = epoch
        elif run_id != newest_run:
            break
        first = epoch
    return first, newest


def _journal_run_start_epoch(path: Path, now: float) -> float | None:
    """The first `attempt-start` of the newest run in the steward's cache
    journal (:func:`_journal_run_starts`), or ``None``."""
    return _journal_run_starts(path, now)[0]


def _steward_next(home: Path, cache_dir: Path, now: float) -> tuple[float, str]:
    """When the steward is next due, from the cache alone (the heartbeat
    preview, S-115), and why.

    A run is unfinished when the journal's newest `attempt-start` is newer
    than the last COMPLETED run (`steward.last-run`): a completed run writes
    its last-run stamp when it ends, after every `attempt-start` it made, so
    only an attempt that has not completed since can be newer. (Gate r1
    MAJOR 1: the first cut compared the newest attempt row of ANY status, and
    a completed run's `recompile` and `push` rows come after its last-run
    stamp, so after almost every completed run the preview said "retry its
    unfinished run".) An unfinished run retries :data:`steward.RETRY_SECS`
    after the journal's newest attempt row, exactly where
    `_steward_recently_attempted` stops holding it. Otherwise the next run is
    the next nightly slot not yet taken, no sooner than `steward.cooldown_secs`
    after the last run's start nor inside the cache retry interval the
    predicate tests first, and only if there is work then."""
    journal = _steward_journal(cache_dir)
    attempt = _journal_attempt_epoch(journal, now)
    start, newest_start = _journal_run_starts(journal, now)
    last_iso = steward.last_run_iso(home)
    last = _attempt_epoch(last_iso, now) if last_iso is not None else None
    if newest_start is not None and (last is None or last < newest_start):
        retry_from = newest_start if attempt is None else max(attempt, newest_start)
        return max(now, retry_from + steward.RETRY_SECS), "to retry its unfinished run"
    if start is None:
        start = last
    when = _next_slot_open(cache_dir, now, start)
    if start is not None:
        cooldown_value, _source = settings.resolve_setting(
            home, settings.by_name("steward.cooldown_secs")
        )
        when = max(when, start + float(cast(int | float | str, cooldown_value)))
    if attempt is not None:
        # `_steward_recently_attempted` holds every run for RETRY_SECS after
        # the newest attempt row (a completed run's push row included).
        when = max(when, attempt + steward.RETRY_SECS)
    return when, "after the night's mine, when there is work"


def _deferral_due_epochs(paths: list[Path], now: float) -> dict[str, float]:
    """S-115: lesson id -> when its deferral came due, for each
    eligible lesson whose `deferred_until` has passed. A record that cannot
    be read is left out (it is then no newer than before)."""
    from .records import Record  # late: a record parse is only needed here

    due: dict[str, float] = {}
    for path in paths:
        try:
            until = chrono.to_dt(getattr(Record.from_path(path), "deferred_until", None))
        except Exception:  # noqa: BLE001 -- a hint for the due check, never a raise
            continue
        if until is None:
            continue
        epoch = until.timestamp()
        if epoch <= now:
            due[path.stem] = epoch
    return due


def _eligible_input_paths(home: Path) -> list[Path]:
    """U3a (2026-09-27): the record files of the lessons the steward would
    select -- a lesson no longer needs a proposal file to be selected."""
    return [entry.path for entry, _row in steward._eligible_lessons(home)]


def _input_commit_epoch(home: Path, path: Path) -> float:
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


def _premise_extract_waiting(home: Path) -> bool:
    """S-104: whether the steward's next run would take at
    least one `premise-extract` input (a placed lesson with no premises,
    not held, its version undecided, the backfill not paused). Unordered
    and stopped at one row: the ordering reads case files, and this runs
    on every scheduler tick."""
    return bool(steward._premise_extract_inputs(home, limit=1, ordered=False))


def _rotation_on(home: Path) -> bool:
    """S-114: whether the rotation could offer anything at all
    (`premises.enabled` and a `premises.rotation_days` above 0): two
    settings reads, cheap enough for every tick."""
    return steward_inputs.premises_enabled(home) and steward_inputs.premise_rotation_days(home) > 0


def _premise_review_overdue(home: Path, manifests: list[dict]) -> bool:
    """S-114 (premises design P1): reviews ride along with a run
    something else starts, sharing its packet; by themselves they make the
    steward due only once the oldest due one is
    `steward_inputs.ROTATION_GRACE_DAYS` days past due
    (:func:`steward._premise_review_overdue`, one case-index read for every
    lesson)."""
    if not _rotation_on(home):
        return False
    return steward._premise_review_overdue(home, manifests=manifests)


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
    if unfinished:
        # S-115: committed unfinished work -- a failed attempt, an
        # environment hold, a partial run -- is retried `steward.RETRY_SECS`
        # (2 h) after its last attempt, the overseer's rule (13 §5), never
        # after the 20 hours a new run waited: a login the user restored
        # cost them a day. The cache attempt journal (tested above too) and
        # the committed `last_attempt_at` both count; the committed stamp
        # stands alone when the cache was lost. The attempt cap still bounds a
        # run that keeps failing on its content; a hold counts nothing and
        # makes one fast failing call per 2 h.
        # The clock is the LATER of the two: an attempt's journal rows (its
        # end and push rows) are written after its committed stamp, so the
        # journal is normally the later one and the cache-only preview names
        # this same instant; a lost or foreign cache can never make a retry
        # come sooner than two hours after the committed attempt.
        epochs = [
            _attempt_epoch(str(row.get("last_attempt_at")), now)
            for row in unfinished if row.get("last_attempt_at")
        ]
        journal = _journal_attempt_epoch(_steward_journal(cache_dir), now)
        if journal is not None:
            epochs.append(journal)
        if not epochs:
            return True
        return now - max(epochs) >= steward.RETRY_SECS
    reconsider, _predecessors = steward._reconsider_proposals(home)
    input_paths = _eligible_input_paths(home)
    # U3a: an unhandled suspected rule violation is an input too; like a
    # reconsider input it is due once the cooldown has passed.
    violations = steward._suspected_violation_inputs(home)
    # S-104: a placed lesson whose follow-up closed after it was
    # last decided is an input too, due like a reconsider input once the
    # cooldown has passed (the premise-check design, U3).
    premise_moved = steward._premise_moved_inputs(home, manifests=manifests)
    # S-104: a placed lesson with no premises is an input too
    # (the backfill), due like a reconsider input once the cooldown has
    # passed. Asked only when it can change the answer, and unordered (the
    # ordering reads case files; this runs on every tick).
    premise_extract: bool | None = None
    only_review = False
    if not reconsider and not input_paths and not violations and not premise_moved:
        premise_extract = _premise_extract_waiting(home)
        if not premise_extract:
            # S-114: a review can still make it due by itself, but
            # that is asked only after the cooldown (below), and only when
            # the rotation is on at all -- a settings read, nothing more, here.
            if not _rotation_on(home):
                return False
            only_review = True
    # S-115: new work. The steward runs once a night, after the
    # mine (`_steward_slot`), and never twice within `steward.cooldown_secs`
    # of a start. Before, the 20-hour cooldown rolled from the last run, so
    # the run drifted about 4 hours earlier every day.
    starts = [str(row.get("started_at")) for row in manifests if row.get("started_at")]
    if starts:
        selected_epoch = _attempt_epoch(max(starts), now)
    else:
        last_iso = steward.last_run_iso(home)
        if last_iso is None:
            # never run: the first run takes the queue now (S-114:
            # with only reviews waiting, when one is overdue)
            return _premise_review_overdue(home, manifests) if only_review else True
        selected_epoch = _attempt_epoch(last_iso, now)
    cooldown_value, _source = settings.resolve_setting(
        home, settings.by_name("steward.cooldown_secs")
    )
    cooldown = cast(int | float | str, cooldown_value)
    if now - selected_epoch < float(cooldown):
        return False  # the minimum gap between two starts
    if selected_epoch >= _steward_slot(cache_dir, now):
        return False  # tonight's run has already selected
    if reconsider or violations or premise_moved:
        return True
    if premise_extract is None:
        premise_extract = _premise_extract_waiting(home)
    if premise_extract:
        return True
    if not input_paths:
        # S-114: nothing else is waiting; only an overdue review
        # can make the steward due now.
        return _premise_review_overdue(home, manifests)
    # S-81 (gate S1d R2): an input is new work when no run has SELECTED
    # inputs since its record -- or the overseer's release of it -- was
    # committed. A run selects its inputs when it starts (`started_at`); a
    # run resumed later selects none, so measuring from the last run's END
    # left a lesson committed or released while an earlier run was
    # unfinished behind that end, waiting for an unrelated input.
    # S-115: and a lesson whose deferral came due since then is new
    # work too -- its record is older than that selection, so before, a due
    # deferral waited for an unrelated input to make the steward due.
    released = _release_epochs(home, {path.stem for path in input_paths})
    came_due = _deferral_due_epochs(input_paths, now)
    if any(
        _input_commit_epoch(home, path) > selected_epoch
        # Not before the last selection: both clocks count whole seconds,
        # and an eligible lesson the overseer let go no earlier than that
        # selection is one no run has had the chance to select.
        or released.get(path.stem, -1.0) >= selected_epoch
        or came_due.get(path.stem, -1.0) >= selected_epoch
        for path in input_paths
    ):
        return True
    # S-114: asked last, and only now -- after the cooldown and
    # every cheaper reason -- because it reads every placed lesson.
    return _premise_review_overdue(home, manifests)

def _release_epochs(home: Path, lessons: set[str]) -> dict[str, float]:
    """S-81 (gate S1c R3): lesson id -> when the overseer last let it go --
    the commit of its decision that superseded a parked case naming the
    lesson (the same commit rewrites that parked case's `superseded_by`,
    so the parked case file's last commit is the release). An undecided
    lesson released after the steward's last selection is new work for
    the steward: before, its record file was older than that run, so
    nothing made the steward due for it until some unrelated input
    arrived. Gate S1d N5: only for *lessons* (the eligible inputs), so a
    tick reads no case file that cannot change the answer."""
    released: dict[str, float] = {}
    if not lessons:
        return released
    for row in cases.list_cases(home, parked_for="overseer"):
        if not row.get("superseded_by"):
            continue
        if not {str(rid) for rid in row.get("records") or []} & lessons:
            continue
        case_path = next((home / "cases").glob(f"*/{row.get('case')}.md"), None)
        if case_path is None:
            continue
        epoch = _input_commit_epoch(home, case_path)
        for record_id in row.get("records") or []:
            released[str(record_id)] = max(released.get(str(record_id), 0.0), epoch)
    return released


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


#: 2026-09-27 (fail-state audit finding 6): where a crashed job is recorded
#: when it has no journal of its own (the mine and worker jobs, or a caller
#: that passed no ledger home). Cache only, never ledger truth.
SERVE_JOURNAL_FILENAME = "serve.journal.jsonl"


def _log_job_crash(home: Path | None, cache_dir: Path, job: str, exc: BaseException) -> None:
    """A job that raised is never swallowed silently (2026-09-27, fail-state
    audit finding 6): its error and traceback go to stderr (journald, under
    the service), and one `crashed` row goes to the job's own journal -- the
    steward's or the overseer's, where the same reader finds its attempts --
    or else to serve's own journal in the cache. Nothing here may raise."""
    error = f"{type(exc).__name__}: {exc}"[:500]
    try:
        print(f"self-learn serve: the {job} job crashed: {error}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 -- logging a crash must never widen it
        pass
    entry = {"status": "crashed", "job": job, "error": error}
    try:
        if home is not None and job == "steward":
            steward._journal(home, {"ts": chrono.now_iso(), **entry})
        elif home is not None and job == "overseer":
            overseer_run._journal(Path(home), {"at": chrono.now_iso(), **entry})
        else:
            cache_dir.mkdir(parents=True, exist_ok=True)
            with open(cache_dir / SERVE_JOURNAL_FILENAME, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": chrono.now_iso(), **entry}, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 -- logging a crash must never widen it
        pass


#: S-109: the actor each scheduled job's ledger commits carry
#: (``By:``). The entry points stamp themselves too; this keeps a job that
#: reaches the ledger some other way attributed.
_JOB_ACTORS = {
    "mine": "miner",
    "worker": "worker",
    "hosts": hosts_mod.POLICY_ACTOR,
    "premises": "sweep",
    "steward": "steward",
    "overseer": "overseer",
    # S-119: the daily maintenance recompile.
    "maintenance": "maintenance",
}


def run_one_job(
    cache_dir: Path, job: Job, *, pid: int | None = None, tick_secs: float | None = None,
    home: Path | None = None,
) -> JobRecord:
    """Executes `job.run()` to completion — never interrupted mid-flight
    (§5.2a: SERIAL) — then advances the heartbeat (`SUP1`) naming this
    job as the one just run. This is THE scheduler primitive: both
    `run_forever`'s real tick loop and `MS1-seq`'s test drive jobs
    through this exact function, so "a real serve scheduler loop" means
    the same code path in both places."""
    global _jobs_in_flight
    started = time.time()
    beat_pid = pid if pid is not None else os.getpid()
    actor = _JOB_ACTORS.get(job.name)
    with _RunningHeartbeat(cache_dir, pid=beat_pid, job=job.name, tick_secs=tick_secs), (
        attribution.job(actor) if actor is not None else contextlib.nullcontext()
    ):
        # L6: counted while it runs, so the re-exec on new code can never
        # replace this process in the middle of a job.
        _jobs_in_flight += 1
        try:
            result = job.run()
            record = JobRecord(job.name, job.surface, True, started, time.time(), result=result)
        except Exception as exc:  # noqa: BLE001 — a crashed job must not crash the daemon
            record = JobRecord(job.name, job.surface, False, started, time.time(), error=f"{exc}")
            _log_job_crash(home, cache_dir, job.name, exc)
        finally:
            _jobs_in_flight -= 1
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


#: S-112: the host policy's attempt marker in the cache, and how
#: often the policy is applied (once a day, like the premise sweep).
HOSTS_POLICY_FILENAME = "hosts-policy.json"
HOSTS_POLICY_INTERVAL_SECS = 24 * 3600


def _hosts_policy_is_due(home: Path, cache_dir: Path, now: float) -> bool:
    """The host policy (S-112) is due when the registry has a
    registration the policy would change (:func:`hosts.policy_changes`, a
    read of ``hosts.yaml``) and its attempt marker is absent, unreadable,
    future-dated or at least a day old: checked every tick, acted on at
    most once a day. It needs no switch: it applies a rule the user typed.
    A registry that cannot be read is not due (the doctor's ``hosts`` row
    FAILs on it); a registry that follows the policy costs no job at all."""
    try:
        if not hosts_mod.policy_changes(hosts_mod.load_hosts(home)):
            return False
    except hosts_mod.HostsError:
        return False
    try:
        data = json.loads((cache_dir / HOSTS_POLICY_FILENAME).read_text(encoding="utf-8"))
        stamp = data["attempted_at"]
        last = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except FileNotFoundError:
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return True  # a marker that cannot be read is rewritten by the next attempt
    if last > now:
        return True
    return now - last >= HOSTS_POLICY_INTERVAL_SECS


def _write_hosts_policy_marker(cache_dir: Path, now: float) -> None:
    """The host policy's attempt marker: cache only, never ledger truth."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(
        cache_dir / HOSTS_POLICY_FILENAME,
        json.dumps({"attempted_at": chrono.now_iso(datetime.fromtimestamp(now, timezone.utc))}) + "\n",
        fsync=False,
    )


def _run_hosts_policy_job(home: Path, cache_dir: Path, now: float) -> "hosts_mod.PolicyResult":
    """Apply the host policy (:func:`hosts.apply_policy`): a project
    registration of the skills root's path takes the skills root's mode.
    The attempt marker is written FIRST, so a pass that crashes waits a day
    instead of running every tick. Each change, and each change it could
    not make, is one line on serve's stderr (the journal the operator
    reads); the doctor's ``hosts`` row names a change still owed."""
    _write_hosts_policy_marker(cache_dir, now)
    result = hosts_mod.apply_policy(home)
    for change in result.changed:
        print(f"serve: host policy: {change.text()} ({hosts_mod.POLICY_RULE})", file=sys.stderr)
    for line in result.failed:
        print(f"serve: host policy: {line}", file=sys.stderr)
    return result


def _premises_is_due(home: Path, cache_dir: Path, now: float) -> bool:
    """S-104 (premise-check design D5): the daily premise sweep is
    due when ``premises.enabled`` is on, it was last attempted at least a day
    ago, and the ledger has a resolved lesson to look at. Reads the cache and
    directory names only, so it is cheap every tick."""
    return premise_sweep.is_due(home, cache_dir, now)


def _run_premises_job(home: Path, cache_dir: Path, now: float) -> "premise_sweep.SweepResult":
    """The sweep itself: code only, never a model call. It writes the cache
    (``<cache>/premises/``) and, for a premise marked ``on_change: refresh``,
    one ledger commit under the commit lock. The cache directory and the clock
    are the ones the due check read, so the attempt marker it leaves is the one
    that stops the job being due again the same day."""
    return premise_sweep.run(home, cache_dir, now=now)


def _maintenance_is_due(home: Path, cache_dir: Path, now: float) -> bool:
    """L6: the daily maintenance recompile is due once a day (marker in the
    cache, written when an attempt starts) when the ledger registers any
    host. Reads the cache and one file's presence only."""
    return maintenance.is_due(home, cache_dir, now)


def _run_maintenance_job(home: Path, cache_dir: Path, now: float) -> "maintenance.MaintenanceResult":
    """L6: recompiles the targets `--selftest` reports as carrying markers
    with no compile record (never `--adopt`), and logs any it refuses."""
    return maintenance.run(home, cache_dir, now=now)


def _run_steward_job(home: Path) -> "steward.RunResult":
    return steward.run(home)


def _run_overseer_job(home: Path) -> "overseer_run.RunResult":
    return overseer_run.run(home)


# ------------------------------------------- the stranded-lesson census

#: S-115: where the last census of stranded queued lessons is kept,
#: under ``<cache>/steward/`` (`NOT_REPO_TRUTH`): the session-start status
#: reads its count without walking the ledger.
STRANDED_FILENAME = "stranded.json"
#: The key of the census's `health` notice (one per checkout).
STRANDED_NOTICE_KEY = "steward-stranded-lessons"


def stranded_path(cache_dir: Path) -> Path:
    return cache_dir / "steward" / STRANDED_FILENAME


def read_stranded(cache_dir: Path) -> dict[str, Any] | None:
    """The last census as written (``{"at", "count", "lessons"}``), or
    ``None`` when there is none or it cannot be read. Never raises."""
    try:
        data = json.loads(stranded_path(cache_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("count"), int) else None


def _write_stranded(cache_dir: Path, rows: list["steward.Stranded"], at: str) -> None:
    """THE census writer (`NOT_REPO_TRUTH`: one cache file, atomic)."""
    path = stranded_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(
        path,
        json.dumps(
            {"at": at, "count": len(rows), "lessons": [row.as_dict() for row in rows]},
            sort_keys=True,
        ) + "\n",
        fsync=False,
        preserve_mode=False,
    )


def _installed_checkout(home: Path) -> Path | None:
    """The self-learn checkout this process runs -- the git work tree of
    the real path of this module -- when it is a registered project host,
    else ``None``: a health notice is shown in sessions inside it, where the
    people who can change self-learn's code work."""
    root = gitops.work_tree_of(Path(__file__))
    if root is None:
        return None
    from .hosts import load_hosts  # late: hosts is only needed here

    registered = {os.path.realpath(path) for path in load_hosts(home).projects}
    return root if os.path.realpath(root) in registered else None


def stranded_notice_text(rows: list["steward.Stranded"]) -> str:
    """The `health` notice's words: the count, the oldest lesson and what
    makes it terminal, and where the full list is."""
    oldest = rows[0]
    if oldest.run:
        why = f"terminal by {oldest.run}"
    elif oldest.reason.startswith("identity unreadable"):
        why = "identity unreadable"
    else:
        why = "no deciding run found"
    text = (
        f"{len(rows)} queued lesson(s) the steward never selects (oldest {oldest.record}, "
        f"{why}); see `self-learn --selftest`"
    )
    return text if len(text) <= notices.MAX_TEXT else text[: notices.MAX_TEXT - 3] + "..."


def census_stranded(
    home: Path, cache_dir: Path, *, now: float | None = None
) -> list["steward.Stranded"] | None:
    """S-115: take the stranded-lesson census
    (`steward.stranded_lessons`), keep it in the cache, and keep the
    `health` notice for the installed self-learn checkout in step with it:
    written (or its words updated) while the census finds a lesson, removed
    when it finds none. Run after every steward job and once a day after the
    premises job. Answers the rows, or ``None`` when the census could not be
    taken -- then the cache file and the notice are left as they were (an
    unreadable ledger is not a clean census). Never raises."""
    moment = time.time() if now is None else now
    try:
        rows = steward.stranded_lessons(home)
    except Exception as exc:  # noqa: BLE001 -- a census must never end a tick
        print(f"serve: the stranded-lesson census failed — {_short_cause(exc)}", file=sys.stderr)
        return None
    at = datetime.fromtimestamp(moment).astimezone().isoformat(timespec="seconds")
    try:
        _write_stranded(cache_dir, rows, at)
    except OSError as exc:
        print(f"serve: the stranded-lesson census was not kept — {_short_cause(exc)}", file=sys.stderr)
    try:
        checkout = _installed_checkout(home)
    except Exception:  # noqa: BLE001 -- the notice is a hint
        checkout = None
    if checkout is not None:
        if rows:
            notices.set_health(
                home, project=checkout, key=STRANDED_NOTICE_KEY, text=stranded_notice_text(rows)
            )
        else:
            notices.clear_health(home, project=checkout, key=STRANDED_NOTICE_KEY)
    if rows:
        print(
            f"serve: {len(rows)} queued lesson(s) the steward never selects: "
            + ", ".join(f"{row.record} ({row.reason})" for row in rows[:5]),
            file=sys.stderr,
        )
    return rows


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
                cache_dir, Job("mine", "miner-reader", lambda: _run_mine_job(home)), pid=pid, tick_secs=tick_secs, home=home
            )
            ran.append(mine_record)
            _log_stopped_refusal("mine", getattr(mine_record.result, "stopped", None) or [])
            landed = getattr(mine_record.result, "landed", None)
            if landed:
                worker_record = run_one_job(
                    cache_dir, Job("worker", "worker", lambda: _run_worker_job(home)), pid=pid, tick_secs=tick_secs, home=home
                )
                ran.append(worker_record)
                _log_stopped_refusal("worker", getattr(worker_record.result, "stopped", None) or [])
        # S-112: the host policy, at most once a day and only when
        # a registration does not follow it, before the premise sweep, so a
        # registration it changes is probed in its new mode the same night.
        # Code only; no switch (it applies a rule the user typed).
        if _due_or_hold("hosts", home, cache_dir, now, lambda: _hosts_policy_is_due(home, cache_dir, now)):
            ran.append(
                run_one_job(
                    cache_dir,
                    Job("hosts", "hosts", lambda: _run_hosts_policy_job(home, cache_dir, now)),
                    pid=pid,
                    tick_secs=tick_secs,
                    home=home,
                )
            )
        # S-104: the premise sweep runs BEFORE the steward, so a
        # change it confirms is decided the same night (design D5). It is a
        # job like the others (serial, one at a time) and calls no model.
        if _due_or_hold(
            "premises", home, cache_dir, now, lambda: _premises_is_due(home, cache_dir, now)
        ):
            premises_record = run_one_job(
                cache_dir,
                Job("premises", "premises", lambda: _run_premises_job(home, cache_dir, now)),
                pid=pid,
                tick_secs=tick_secs,
                home=home,
            )
            ran.append(premises_record)
            _log_stopped_refusal(
                "premises", getattr(premises_record.result, "stopped", None) or []
            )
            # S-115: the daily census, whether or not a steward
            # job follows (with the steward off, or nothing due, this is
            # the only one that day).
            census_stranded(home, cache_dir, now=now)
        # L6: the daily maintenance recompile, at the premises job's hook
        # point and before the steward: targets whose self-learn markers have
        # no compile record get one, so nobody has to run `recompile` for it.
        if _due_or_hold(
            "maintenance", home, cache_dir, now,
            lambda: _maintenance_is_due(home, cache_dir, now),
        ):
            ran.append(
                run_one_job(
                    cache_dir,
                    Job("maintenance", "maintenance",
                        lambda: _run_maintenance_job(home, cache_dir, now)),
                    pid=pid,
                    tick_secs=tick_secs,
                    home=home,
                )
            )
        if _due_or_hold(
            "steward", home, cache_dir, now, lambda: _steward_is_due(home, cache_dir, now)
        ):
            steward_record = run_one_job(
                cache_dir,
                Job("steward", "steward", lambda: _run_steward_job(home)),
                pid=pid,
                tick_secs=tick_secs,
                home=home,
            )
            ran.append(steward_record)
            _log_stopped_refusal(
                "steward", getattr(steward_record.result, "stopped", None) or []
            )
            # S-115: and after every steward job, which is when
            # the selection changes.
            census_stranded(home, cache_dir, now=now)
        if _due_or_hold(
            "overseer", home, cache_dir, now, lambda: _overseer_is_due(home, cache_dir, now)
        ):
            overseer_record = run_one_job(
                cache_dir,
                Job("overseer", "overseer", lambda: _run_overseer_job(home)),
                pid=pid,
                tick_secs=tick_secs,
                home=home,
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


# ------------------------------------------------- re-exec on new code (L6)

#: L6 (2026-10-31): jobs running right now in this process. `run_one_job`
#: counts each job while it runs; the re-exec below never fires while this
#: is above zero, so a landing can never cut a job off (the 10-31 03:45 hand
#: restart killed the nightly mine 9 s in).
_jobs_in_flight = 0

#: A changed code fingerprint must read the same on this many consecutive
#: checks (one per tick) before `serve` re-executes onto it, so a merge or a
#: checkout that is still writing files is not caught half-way.
REEXEC_STABLE_TICKS = 2

#: Carried across the re-exec in the new image's environment (never written
#: into this process's own `os.environ`): when the process that systemd
#: started first began, so the unit-file check below still compares against
#: the real start after any number of re-execs.
_STARTED_AT_ENV = "SELF_LEARN_SERVE_STARTED_AT"

HOST_UNIT_NAME = "self-learn-host.service"

#: Fix r1 (gate finding 1): a refused fingerprint is tried again after this
#: long even though the code has not changed, because what failed may have
#: been the environment (a venv synced since, by hand or by any `uv run`).
REEXEC_RETRY_SECS = 3600

#: The files of the uv project that decide what the venv holds. A change to
#: either means the venv must be synced before the new code can run: the
#: re-exec runs the interpreter directly, never `uv run`, so nothing else
#: would sync it.
_ENV_FILES = ("pyproject.toml", "uv.lock")

#: The key of the one project notice that says the host process is held on
#: its old code (fix r1, gate finding 1).
_REFUSED_NOTICE_KEY = "host-code-refused"


def _code_root() -> Path:
    """The `self_learn` package directory this process imported (symlinks
    resolved): the code a re-exec would load again."""
    return Path(__file__).resolve().parent


def _project_root() -> Path | None:
    """The uv project the package belongs to (`plugins/self-learn/cli`: the
    directory above `src/` that holds `pyproject.toml`), or `None` when the
    package does not sit in one (an installed wheel, a test's copy)."""
    root = _code_root().parent.parent
    return root if (root / "pyproject.toml").is_file() else None


def env_fingerprint(project: Path | None = None) -> str | None:
    """A hash of the uv project's `pyproject.toml` and `uv.lock` (fix r1,
    gate finding 1): what the venv must hold. `None` when there is no
    project or it cannot be read."""
    base = project if project is not None else _project_root()
    if base is None:
        return None
    digest = hashlib.sha256()
    try:
        for name in _ENV_FILES:
            path = base / name
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"-")
    except OSError:
        return None
    return digest.hexdigest()[:16]


def _fingerprint(code: str | None, env: str | None) -> str | None:
    """The one fingerprint the stability count runs on: the code's, joined
    with the project files' when there are any."""
    if code is None:
        return None
    return code if env is None else f"{code}.{env}"


def code_fingerprint(root: Path | None = None) -> str | None:
    """A hash of every Python source file under the package *root* (default:
    the one this process runs), by relative path and CONTENT. A landing
    (a new `HEAD`) and an uncommitted edit both change it; a commit that
    changes no file, or a touch, does not. `None` when the tree cannot be
    read, which never triggers a re-exec. About 4 MB of source; a few
    milliseconds once a tick."""
    base = root if root is not None else _code_root()
    digest = hashlib.sha256()
    try:
        files = sorted(
            p for p in base.rglob("*.py") if "__pycache__" not in p.relative_to(base).parts
        )
        for path in files:
            digest.update(path.relative_to(base).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    except OSError:
        return None
    return digest.hexdigest()[:16] if files else None


@dataclass
class _CodeWatch:
    """What the re-exec check remembers between ticks."""

    running: str | None
    started_at: float
    candidate: str | None = None
    seen: int = 0
    #: A fingerprint the re-exec was refused for (it did not import, or the
    #: venv could not be synced): not tried again until the code changes
    #: once more or `REEXEC_RETRY_SECS` have passed (fix r1).
    refused: str | None = None
    refused_at: float = 0.0
    #: The unit file mtime a notice was last written (or cleared) for.
    unit_mtime_seen: int | None = None
    #: The project files' fingerprint (`env_fingerprint`) this process
    #: started on; a different one means the venv needs a sync (fix r1).
    running_env: str | None = None


def _start_time_from_env(now: float) -> float:
    raw = os.environ.get(_STARTED_AT_ENV)
    try:
        value = float(raw) if raw is not None else None
    except ValueError:
        value = None
    return value if value is not None and 0 < value <= now else now


def _append_serve_journal(cache_dir: Path, entry: dict[str, Any]) -> None:
    """One row in `serve.journal.jsonl` (the cache, `NOT_REPO_TRUTH`), the
    same file `_log_job_crash` writes for a job with no journal of its own.
    Never raises."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with open(cache_dir / SERVE_JOURNAL_FILENAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": chrono.now_iso(), **entry}, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 -- a journal row never widens anything
        pass


def _restart_on_new_code(home: Path) -> bool:
    """`serve.restart_on_new_code` (default on); a read that fails reads as
    off for this tick, never as a crash."""
    try:
        value, _source = settings.resolve_setting(
            home, settings.by_name("serve.restart_on_new_code")
        )
    except Exception:  # noqa: BLE001
        return False
    return value is True


def _new_code_imports(timeout: float = 120.0) -> tuple[bool, str]:
    """Whether the code on disk imports in a fresh interpreter, the same
    interpreter and environment the re-exec would use (`-P`: the working
    directory is not put on the path). A half-written or broken tree must
    not replace a running daemon with one that dies on start."""
    import subprocess

    try:
        proc = procs.run_bounded(
            [sys.executable, "-P", "-c", "import self_learn.cli, self_learn.serve"],
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, _short_cause(exc)
    if proc.returncode == 0:
        return True, ""
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, (tail[-1] if tail else f"exit {proc.returncode}")[:300]


def _is_import_failure(why: str) -> bool:
    """Whether the import check failed on a missing or broken dependency
    (the last traceback line names `ModuleNotFoundError`/`ImportError`),
    which a venv sync may cure, rather than on the code itself."""
    return why.startswith(("ModuleNotFoundError", "ImportError"))


def _sync_venv(project: Path, timeout: float = 600.0) -> tuple[bool, str]:
    """Fix r1 (gate finding 1): bring the venv up to the project's lock, the
    step the unit's `uv run` takes on every start and the re-exec skips.
    Runs `uv sync --project <project> --inexact` (`--inexact`: like `uv
    run`, it never removes packages). The `uv` is the one that started this
    process (`uv run` puts its own path in `UV`), else the one on `PATH`.
    Called between jobs only, before the import check, so a failed or
    partial sync is followed by that check and never by a blind re-exec."""
    import shutil
    import subprocess

    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        return False, "no `uv` to sync the venv with (`UV` is unset and none is on PATH)"
    try:
        proc = procs.run_bounded(
            [uv, "sync", "--project", str(project), "--inexact"], timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, _short_cause(exc)
    if proc.returncode == 0:
        return True, ""
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, (tail[-1] if tail else f"uv sync exit {proc.returncode}")[:300]


def _checkout_of_code() -> Path:
    """The checkout the running code lives in (its git work tree), for the
    project notice; the package directory itself when it is in none."""
    root = _code_root()
    return gitops.work_tree_of(root) or root


def _refused_notice_id() -> str:
    return notices.notice_id(
        os.path.realpath(_checkout_of_code()), notices.SOURCE_CODE, _REFUSED_NOTICE_KEY
    )


def _refuse_reexec(
    home: Path, cache_dir: Path, watch: _CodeWatch, current: str, why: str, now: float
) -> None:
    """The new code is not run (fix r1): remembered with its time, so it is
    tried again after `REEXEC_RETRY_SECS` or on the next change; one journal
    row and one stderr line per attempt; and one project notice for the
    checkout (S-106), so a session working there sees that the host process
    is held on its old code and why. The notice is marked done when the next
    image starts (`_clear_refused_notice`: a fresh start runs what is on
    disk) or the code on disk is back to what this one runs. Never raises."""
    watch.refused, watch.refused_at = current, now
    _append_serve_journal(cache_dir, {
        "status": "reexec-refused", "from": watch.running, "to": current, "error": why,
    })
    print(
        f"serve: the self-learn code on disk changed but cannot be run ({why}); "
        "staying on the running code; retrying when it changes again or in "
        f"{REEXEC_RETRY_SECS // 60} minutes.",
        file=sys.stderr,
    )
    _hold_notice(home, why)


def _hold_notice(home: Path, why: str) -> None:
    """The one project notice saying the host process is held on its old
    code, with the current reason. A live notice with another reason is
    replaced (fix r2, gate NIT 5): the notice names why the process is held
    now, not why it was first held. Never raises."""
    short = " ".join(why.split())
    short = "".join(ch for ch in short if ch.isprintable())[:90]
    text = (
        "the self-learn host process is held on its old code: the new code "
        f"cannot run ({short}); it retries hourly"
    )
    try:
        project = _checkout_of_code()
        held = notices.add(
            home, project=project, text=text, source=notices.SOURCE_CODE,
            key=_REFUSED_NOTICE_KEY, renew=True,
        )
        if held is not None and held.text != text and held.done_at is None:
            # `add` leaves a live notice as it is; once done, `renew`
            # replaces it with the words of this refusal.
            notices.mark_done(home, held.id)
            notices.add(
                home, project=project, text=text, source=notices.SOURCE_CODE,
                key=_REFUSED_NOTICE_KEY, renew=True,
            )
    except Exception:  # noqa: BLE001 -- a hint never widens anything
        pass


def _clear_refused_notice(home: Path) -> None:
    """Fix r2 (gate finding 2): the hold has ended -- this process has just
    started on the code on disk, or the code on disk is again the code it
    runs -- so the "held on its old code" notice is marked done. Never
    raises."""
    try:
        notices.mark_done(home, _refused_notice_id())
    except Exception:  # noqa: BLE001 -- a hint never widens anything
        pass


def _exec_argv() -> list[str]:
    """The command line this process was started with, interpreter first,
    so the re-exec runs exactly the same command."""
    argv = list(getattr(sys, "orig_argv", None) or [])
    return argv if argv else [sys.executable, "-m", "self_learn.cli", *sys.argv[1:]]


def _reexec(argv: list[str], env: dict[str, str]) -> None:
    """Replace this process with *argv*. The one call the tests stub."""
    os.execve(sys.executable, argv, env)


def _check_unit_file(home: Path, watch: _CodeWatch) -> None:
    """A host unit file changed after this process started: the code is
    picked up by the re-exec, but a unit file change needs systemd to
    reload it and restart the service, which a process cannot do for
    itself. Writes one project notice for the checkout the unit file lives
    in (S-106; shown in a session working there), and clears it once the
    service has been restarted onto that file. Only under systemd
    (`INVOCATION_ID` set) and only when the unit is linked. Never raises."""
    try:
        if not os.environ.get("INVOCATION_ID") or not is_configured(HOST_UNIT_NAME):
            return
        unit = unit_dir() / HOST_UNIT_NAME
        mtime_ns = unit.stat().st_mtime_ns
        if watch.unit_mtime_seen == mtime_ns:
            return
        real = Path(os.path.realpath(unit))
        project = gitops.work_tree_of(real) or real.parent
        key = f"host-unit:{real}:{mtime_ns}"
        if mtime_ns / 1e9 <= watch.started_at:
            # Started after the file last changed: any notice for this exact
            # file version is dealt with.
            notices.mark_done(home, notices.notice_id(os.path.realpath(project), notices.SOURCE_CODE, key))
        else:
            notices.add(
                home,
                project=project,
                # Fix r1 (gate NIT 4): the restart waits for a moment with no
                # job running -- a restart mid-job kills the job, as the
                # 10-31 03:45 one killed the mine.
                text=(
                    "the host unit file changed after the host process started: run "
                    f"`systemctl --user daemon-reload`, then restart {HOST_UNIT_NAME} "
                    f"while no job runs ({HEARTBEAT_FILENAME} has no `running` key)"
                ),
                source=notices.SOURCE_CODE,
                key=key,
            )
            print(
                f"serve: {real} changed after this process started; it needs "
                "`systemctl --user daemon-reload` and a restart of "
                f"{HOST_UNIT_NAME} while no job runs (code changes need neither).",
                file=sys.stderr,
            )
        watch.unit_mtime_seen = mtime_ns
    except Exception:  # noqa: BLE001 -- a hint never widens anything
        pass


def _consider_reexec(
    home: Path, cache_dir: Path, watch: _CodeWatch, *, pid: int, tick_secs: float,
    now: float | None = None,
) -> None:
    """L6, one check per tick, called between ticks only. When the code on
    disk (its `*.py` files, and the uv project's `pyproject.toml` and
    `uv.lock`) has changed from what this process runs, has read the same on
    `REEXEC_STABLE_TICKS` consecutive checks, no job is running, and
    `serve.restart_on_new_code` is on:

    - when the project files changed, sync the venv first (`_sync_venv`;
      the re-exec skips the unit's `uv run`, which is what synced it);
    - check the new code imports; when it fails on a missing or broken
      dependency and the venv was not synced yet, sync it and check again;
    - then write a heartbeat and a journal row saying so, and replace this
      process with the same command (`os.execve`), which loads the new code.

    A refusal (no sync, no import, a failed exec) leaves a project notice and
    is tried again on the next change or after `REEXEC_RETRY_SECS`; the
    notice is done once the code on disk is back to the running code or the
    next image starts. Returns only when it does not re-exec."""
    moment = now if now is not None else time.time()
    _check_unit_file(home, watch)
    env_now = env_fingerprint()
    current = _fingerprint(code_fingerprint(), env_now)
    if current is None or current == watch.running:
        watch.candidate, watch.seen = None, 0
        if current is not None and watch.refused is not None:
            # Fix r2 (gate finding 2): the code on disk is back to what this
            # process runs (a revert), so nothing is held any more.
            watch.refused, watch.refused_at = None, 0.0
            _clear_refused_notice(home)
        return
    if current != watch.candidate:
        watch.candidate, watch.seen = current, 1
    else:
        watch.seen += 1
    if watch.seen < REEXEC_STABLE_TICKS:
        return
    if current == watch.refused and moment - watch.refused_at < REEXEC_RETRY_SECS:
        return
    if _jobs_in_flight > 0:
        return  # never mid-job; the next check between jobs takes it
    if not _restart_on_new_code(home):
        return
    project = _project_root()
    synced = False
    if env_now != watch.running_env and project is not None:
        ok, why = _sync_venv(project)
        if not ok:
            _refuse_reexec(home, cache_dir, watch, current, f"uv sync failed: {why}", moment)
            return
        synced = True
    ok, why = _new_code_imports()
    if not ok and not synced and project is not None and _is_import_failure(why):
        synced_ok, sync_why = _sync_venv(project)
        if synced_ok:
            ok, why = _new_code_imports()
        else:
            why = f"{why}; uv sync failed: {sync_why}"
    if not ok:
        _refuse_reexec(home, cache_dir, watch, current, why, moment)
        return
    # Fix r2 (gate NIT 5): the hold notice is not marked done here; the new
    # image marks it done as it starts (`run_forever`), so a failed exec
    # below leaves it live.
    _append_serve_journal(cache_dir, {"status": "reexec", "from": watch.running, "to": current})
    try:
        write_heartbeat(
            cache_dir, pid=pid, next_job=f"restarting on new code ({current})",
            tick_secs=tick_secs,
        )
    except OSError:
        pass
    print(
        f"serve: the self-learn code changed ({watch.running} -> {current}); "
        "restarting the host process between jobs.",
        file=sys.stderr,
    )
    sys.stdout.flush()
    sys.stderr.flush()
    env = dict(os.environ)
    env[_STARTED_AT_ENV] = repr(watch.started_at)
    try:
        _reexec(_exec_argv(), env)
    except OSError as exc:
        watch.refused, watch.refused_at = current, moment
        _append_serve_journal(cache_dir, {
            "status": "reexec-failed", "from": watch.running, "to": current,
            "error": _short_cause(exc),
        })
        print(f"serve: the restart failed ({_short_cause(exc)}); staying on the running code.",
              file=sys.stderr)
        _hold_notice(home, f"the restart failed: {_short_cause(exc)}")


# --------------------------------------------------------------- the loop


#: S-99: how often the serving daemon sweeps the cache root for
#: orphaned per-home directories and idle host lock files.
CACHE_GC_INTERVAL_SECS = 24 * 3600


def _sweep_cache(home: Path) -> None:
    """One `cache_gc.prune` pass, keeping the cache of the home this daemon
    serves. Never raises (`prune` contains its own failures); says what it
    removed on stderr so the journal shows it."""
    result = cache_gc.prune(keep_homes=[home])
    if result.removed_homes or result.removed_locks:
        print(
            f"serve: cache sweep removed {len(result.removed_homes)} orphaned "
            f"home cache dir(s) and {len(result.removed_locks)} idle host lock "
            "file(s).",
            file=sys.stderr,
        )


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
    # L6: the code this process runs, read once at start; checked between
    # ticks for a landing (`_consider_reexec`).
    running_env = env_fingerprint()
    watch = _CodeWatch(
        running=_fingerprint(code_fingerprint(), running_env),
        started_at=_start_time_from_env(time.time()),
        running_env=running_env,
    )
    # Fix r2 (gate finding 2): whatever held an earlier image on its old
    # code, this one runs the code on disk (a re-exec, a reboot, a restart
    # of the unit), so the hold notice is done.
    _clear_refused_notice(home)

    def _handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        stop.set()

    prev_term = signal.signal(signal.SIGTERM, _handler)
    prev_int = signal.signal(signal.SIGINT, _handler)
    # S-109: outside a job the daemon is `serve`, never the
    # `human` its command line would otherwise stamp.
    actor = attribution.process("serve")
    actor.__enter__()
    try:
        ticks = 0
        next_sweep = 0.0
        while not stop.is_set():
            if time.time() >= next_sweep:
                next_sweep = time.time() + CACHE_GC_INTERVAL_SECS
                _sweep_cache(home)
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
            # L6: between ticks no job is running (every job ran to its end
            # inside `_run_tick`), so this is where new code is picked up.
            if not stop.is_set():
                try:
                    _consider_reexec(home, cd, watch, pid=pid, tick_secs=secs)
                except Exception as exc:  # noqa: BLE001 — never ends the daemon
                    print(f"serve: the code-change check failed — {_short_cause(exc)}",
                          file=sys.stderr)
            stop.wait(secs)
    finally:
        actor.__exit__(None, None, None)
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)
    return 0
