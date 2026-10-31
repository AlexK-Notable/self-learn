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
    "last_refusals",
    "read_state",
    "run",
    "state_path",
]

#: Once a day, like the premise sweep.
INTERVAL_SECS = 24 * 3600
CACHE_SUBDIR = "maintenance"
STATE_FILENAME = "recompile.json"
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
    if not found:
        _store_state(cache_dir, {
            "last_attempt_at": stamp, "status": "idle", "targets": [],
            "recorded": [], "refused": {},
        })
        return MaintenanceResult("idle")
    ids = list(dict.fromkeys(rid for rids in found.values() for rid in rids))
    head_before = verbs.ledger_head(home)
    try:
        result = verbs.recompile(home, no_push=True, only_records=ids)
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
    _store_state(cache_dir, {
        "last_attempt_at": stamp, "status": "ran", "targets": targets,
        "recorded": recorded, "refused": refused,
    })
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
        "ran", targets=targets, recorded=recorded, refused=refused, recompile=result
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
