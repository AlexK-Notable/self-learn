"""maintenance.py -- the host process's daily maintenance recompile (L6 of
the 2026-10-31 interventions survey; 13 §5).

The problem. ``self-learn --selftest``'s drift row names targets that carry
self-learn's managed-section markers but have no compile record (verdict
``unknown``: the region was written before compile records existed, or a
record was lost), and tells whoever reads it to run ``self-learn
recompile``. Nobody does, so the row repeats every day. A plain
``recompile`` is exactly the repair: when the region on disk is what the
ledger would render, it writes the missing record (S-102 M2.4); when it is
not, it refuses the target as hand-edited and names ``--adopt``.

What this job does. Once a day ``serve`` runs it beside the premise sweep,
before the steward. It asks :func:`selfcheck.unrecorded_targets` which
targets have markers and no record, and runs one ``recompile`` narrowed to
the lessons on those targets (``only_records``; never ``--adopt``, which
only a person's or the steward's judgement may use). The ledger commit the
recompile makes (``self-learn: recompile resync record(s)``) is pushed once,
the way a steward run publishes. A target the recompile refuses -- a plain
host's file git tracks (S-80), a hand edit, a host whose two registrations
disagree (S-82) -- is left alone and logged once (the job runs once a day),
for the host policy or the steward's ``@writable`` input to settle.

Outdated warning hooks (S-133, the orchestrator's decision). A
placed warning hook whose stored script the current hook compiler no longer
produces (:func:`verbs.stale_warn_hooks`) joins the same narrowed recompile,
which regenerates it (:func:`verbs.refresh_warn_hooks`: one ledger commit
stamped ``By: maintenance``, then the host write). Never a deny guard; an
outdated hook whose file a person edited is left and named in the log and
the cache file (``hooks_refused``); the hooks that moved are named too
(``hooks_regenerated``). A hook regenerated in the ledger whose host write
failed is named ``hooks_pending`` and RECORDED pending (:mod:`hook_pending`,
gate r2); the next run places exactly the recorded hooks whose placed file
is still as the failed write left it (:func:`verbs.pending_warn_hook_placements`)
-- that is work, never idle (``hooks_placed``) -- and leaves and names one a
person changed or deleted since. Nothing is placed because of a file's
state alone.

What it writes. The ledger only through ``recompile`` (which takes its own
locks), and one cache file, ``<cache>/maintenance/recompile.json``: when the
last attempt began, the targets it found, the ones it recorded and the ones
it could not, with why. ``--selftest`` reads that file to say what is left,
and stops telling a person to run ``recompile`` while the host process runs
(:func:`job_on`). The cache file is ``NOT_REPO_TRUTH``.

It never calls a model, never decides anything a person or the steward
decides, and never raises into ``serve`` (a raise becomes the job's crash
row, like every job's)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .hosts import hosts_path
from .primitives import chrono, fsops

__all__ = [
    "INTERVAL_SECS",
    "MaintenanceResult",
    "is_due",
    "job_on",
    "last_failure",
    "last_refusals",
    "read_state",
    "run",
    "state_path",
]

#: Once a day, like the premise sweep.
INTERVAL_SECS = 24 * 3600
CACHE_SUBDIR = "maintenance"
STATE_FILENAME = "recompile.json"
#: The trailer this job's recompile commit carries, so the overseer's
#: hand-step census (`report.hand_steps`, S-105) reads it as a job's act,
#: not a shell's (`report._JOB_ACTORS` names `maintenance`).
COMMIT_NOTE = "By: maintenance"
#: A refusal's reason is cut to this many characters in the cache file and
#: in the drift row.
_REASON_LIMIT = 240


@dataclass
class MaintenanceResult:
    """One run's outcome. ``status`` is ``idle`` (nothing to record),
    ``ran`` (a recompile ran) or ``failed`` (the recompile raised; the error
    is in ``error`` and the cache file)."""

    status: str
    targets: list[str] = field(default_factory=list)
    recorded: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    #: The recompile's own result, for a caller that wants its entries.
    recompile: Any = None
    #: Never set: this job takes no intent of its own. Present so `serve`'s
    #: `_log_stopped_refusal` reads it like the other jobs' results.
    stopped: list[str] = field(default_factory=list)
    #: S-133: the placed warning hooks this run regenerated (record
    #: ids), and the outdated ones it left, with why (a hand edit, a replay
    #: that fails, a Trigger that now names another file).
    hooks_regenerated: list[str] = field(default_factory=list)
    hooks_refused: dict[str, str] = field(default_factory=dict)
    #: Gate r1 F2 / r2 G2: regenerated in the ledger but not placed this run
    #: (id -> why, recorded pending), and the recorded pending ones this run
    #: placed.
    hooks_pending: dict[str, str] = field(default_factory=dict)
    hooks_placed: list[str] = field(default_factory=list)


def state_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / CACHE_SUBDIR / STATE_FILENAME


def read_state(cache_dir: Path) -> dict:
    """The last run's record, or ``{}``. Never raises."""
    try:
        data = json.loads(state_path(cache_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _store_state(cache_dir: Path, state: Mapping[str, Any]) -> None:
    """THE cache writer of this module (``NOT_REPO_TRUTH``: a file under the
    XDG cache, never a repo's truth). Atomic."""
    path = state_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(
        path, json.dumps(dict(state), sort_keys=True) + "\n", fsync=False, preserve_mode=False
    )


def _last_attempt(state: Mapping[str, Any], now: float) -> float | None:
    """When the last attempt began, or ``None``. A future-dated stamp is read
    as no marker, so the job is due and writes a good one (the premise
    sweep's rule, `premise_sweep._last_attempt`)."""
    when = chrono.to_dt(state.get("last_attempt_at"))
    if when is None:
        return None
    last = when.timestamp()
    return None if last > now else last


def is_due(home: Path | str, cache_dir: Path, now: float) -> bool:
    """Due when the ledger registers any host (no ``hosts.yaml``, nothing is
    compiled anywhere) and the last attempt began at least a day ago. Reads
    one file's presence and the cache only."""
    if not hosts_path(Path(home)).is_file():
        return False
    last = _last_attempt(read_state(cache_dir), now)
    return last is None or now - last >= INTERVAL_SECS


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= _REASON_LIMIT else text[: _REASON_LIMIT - 3] + "..."


def run(home: Path | str, cache_dir: Path, *, now: float | None = None) -> MaintenanceResult:
    """One maintenance recompile. The marker is written when the attempt
    starts, so a run that crashes waits a day instead of looping every tick."""
    from . import selfcheck, verbs  # late: both are heavy, and serve imports this module

    home = Path(home)
    stamp = chrono.now_iso(
        datetime.fromtimestamp(now, timezone.utc) if now is not None else None
    )
    _store_state(cache_dir, {"last_attempt_at": stamp, "status": "started"})
    found = selfcheck.unrecorded_targets(home)
    targets = [str(t) for t in found]
    # S-133: placed warning hooks the current compiler would
    # write differently ride the same recompile, which regenerates them
    # (never a deny guard; an outdated hook a person edited is left).
    # Gate r2 G2: so do the hooks an earlier failed host write RECORDED
    # pending, while their placed file is as that write left it; placing
    # them is work, never idle. One a person changed since is left.
    try:
        stale, hooks_left = verbs.stale_warn_hooks(home)
        unplaced, unplaced_left = verbs.pending_warn_hook_placements(home)
    except Exception as exc:  # noqa: BLE001 -- the managed-target repair still runs
        stale, hooks_left, unplaced, unplaced_left = [], {}, [], {}
        print(f"serve: maintenance could not check warning hooks — {_clip(str(exc))}",
              file=sys.stderr)
    hooks_left = {rid: _clip(why) for rid, why in {**hooks_left, **unplaced_left}.items()}
    if hooks_left:
        print(
            f"serve: maintenance left {len(hooks_left)} warning hook(s) — "
            + "; ".join(f"{rid}: {why}" for rid, why in sorted(hooks_left.items())),
            file=sys.stderr,
        )
    if not found and not stale and not unplaced:
        state: dict[str, Any] = {
            "last_attempt_at": stamp, "status": "idle", "targets": [],
            "recorded": [], "refused": {},
        }
        if hooks_left:
            state["hooks_refused"] = hooks_left
        _store_state(cache_dir, state)
        return MaintenanceResult("idle", hooks_refused=hooks_left)
    ids = list(dict.fromkeys(
        [*(rid for rids in found.values() for rid in rids), *stale, *unplaced]
    ))
    head_before = verbs.ledger_head(home)
    try:
        result = verbs.recompile(
            home, no_push=True, only_records=ids, commit_note=COMMIT_NOTE
        )
    except Exception as exc:  # noqa: BLE001 -- recorded; serve's crash row is for the unexpected
        error = _clip(f"{type(exc).__name__}: {exc}")
        _store_state(cache_dir, {
            "last_attempt_at": stamp, "status": "failed", "targets": targets,
            "recorded": [], "refused": {}, "error": error,
        })
        print(f"serve: maintenance recompile failed — {error}", file=sys.stderr)
        return MaintenanceResult("failed", targets=targets, error=error)
    try:
        verbs.publish_after_run(home, head_before)
    except Exception as exc:  # noqa: BLE001 -- the next push publishes it
        print(f"serve: maintenance recompile could not push — {_clip(str(exc))}", file=sys.stderr)
    skipped = {str(e.target): _clip(e.skipped) for e in result.entries if e.skipped}
    # What is still unrecorded after the run decides "recorded": a target the
    # recompile skipped, or one whose record it could not write, stays.
    left = {str(t) for t in selfcheck.unrecorded_targets(home)}
    recorded = [t for t in targets if t not in left]
    refused: dict[str, str] = {}
    for target in targets:
        if target not in left:
            continue
        reason = skipped.get(target)
        if reason is None:
            named = [w for w in result.warnings if str(w).startswith(f"{target}:")]
            reason = _clip(named[0][len(target) + 1:]) if named else "not recorded (no reason given)"
        refused[target] = reason
    state = {
        "last_attempt_at": stamp, "status": "ran", "targets": targets,
        "recorded": recorded, "refused": refused,
    }
    regenerated = list(result.hooks_regenerated)
    if regenerated:
        state["hooks_regenerated"] = regenerated
        # S-133: which placed warning hooks moved, once a day.
        print(
            f"serve: maintenance regenerated {len(regenerated)} warning hook(s) "
            "from the current compiler — " + ", ".join(regenerated),
            file=sys.stderr,
        )
    pending = {rid: _clip(why) for rid, why in result.hooks_pending.items()}
    if pending:
        state["hooks_pending"] = pending
        print(
            f"serve: maintenance regenerated {len(pending)} warning hook(s) in the ledger "
            "but could not place them — "
            + "; ".join(f"{rid}: {why}" for rid, why in sorted(pending.items())),
            file=sys.stderr,
        )
    placed = list(result.hooks_placed)
    if placed:
        state["hooks_placed"] = placed
        print(
            f"serve: maintenance placed {len(placed)} warning hook(s) an earlier failed "
            "write left pending — " + ", ".join(placed),
            file=sys.stderr,
        )
    if hooks_left:
        state["hooks_refused"] = hooks_left
    _store_state(cache_dir, state)
    if refused:
        # Once a day, because the job runs once a day: left for the host
        # policy (L5) or the steward's `@writable` input, never retried here.
        print(
            "serve: maintenance recompile left "
            f"{len(refused)} target(s) unrecorded — "
            + "; ".join(f"{t}: {r}" for t, r in refused.items()),
            file=sys.stderr,
        )
    return MaintenanceResult(
        "ran", targets=targets, recorded=recorded, refused=refused, recompile=result,
        hooks_regenerated=regenerated, hooks_refused=hooks_left,
        hooks_pending=pending, hooks_placed=placed,
    )


def job_on(home: Path | str) -> bool:
    """Whether the daily maintenance recompile is running for *home*: the
    host process that schedules it is alive (its heartbeat is fresh)."""
    from .serve import cache_dir_readonly, heartbeat_is_fresh  # late: serve imports this module

    try:
        return heartbeat_is_fresh(cache_dir_readonly(Path(home)))
    except Exception:  # noqa: BLE001 -- a read for advice text never raises
        return False


def last_refusals(home: Path | str) -> dict[str, str]:
    """The targets the last maintenance recompile could not record, with
    why (``{}`` when there were none or no run is on file)."""
    from .serve import cache_dir_readonly  # late: serve imports this module

    try:
        refused = read_state(cache_dir_readonly(Path(home))).get("refused")
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(refused, dict):
        return {}
    return {str(k): str(v) for k, v in refused.items()}


def last_failure(home: Path | str) -> str | None:
    """The error of the last maintenance recompile when it FAILED (the
    recompile raised), else ``None`` (fix r1, gate NIT 5): the drift row
    must not say the job records targets while its last run failed."""
    from .serve import cache_dir_readonly  # late: serve imports this module

    try:
        state = read_state(cache_dir_readonly(Path(home)))
    except Exception:  # noqa: BLE001
        return None
    if state.get("status") != "failed":
        return None
    return str(state.get("error") or "no error recorded")
