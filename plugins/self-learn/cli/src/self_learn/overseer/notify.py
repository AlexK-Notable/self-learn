"""Code-owned notification cue selection for overseer runs (O-6)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from .. import worker

_REMOVAL_VERBS = frozenset({"reject", "retire", "replace", "supersede"})


def classify(
    outcomes: Iterable[Mapping[str, Any]], *, broad_removal_threshold: int
) -> str:
    """Choose exactly one cue from applied result facts, in priority order."""
    rows = list(outcomes)
    if any(bool(row.get("hook_activated")) for row in rows):
        return "hook-activated"
    if any(bool(row.get("always_loaded_user_scope")) for row in rows):
        return "always-loaded-user-scope"
    removals = sum(1 for row in rows if row.get("verb") in _REMOVAL_VERBS)
    if removals > broad_removal_threshold:
        return "broad-removal"
    if any(bool(row.get("close_call")) for row in rows):
        return "close-call"
    return "routine"


def _line(cue: str, summary: str, ids: list[str]) -> str:
    if cue == "hook-activated":
        record = ids[0] if ids else "unknown record"
        return (
            f"CRITICAL — {summary}; hook activated for {record}. "
            f"Deactivate with: self-learn hook deactivate {record}"
        )
    if cue == "always-loaded-user-scope":
        return f"ATTENTION — user-scope always-loaded surface changed; {summary}"
    if cue == "broad-removal":
        return f"ATTENTION — broad catalogue removal; {summary}"
    if cue == "close-call":
        return f"ATTENTION — close call flagged for review; {summary}"
    return summary


def send(home: Path, cue: str, summary: str, ids: list[str]) -> None:
    """Detach one bounded companion-script notification, best effort."""
    if worker._notifications_suppressed(home):
        return
    helper = shutil.which("self-learn-notify")
    line = _line(cue, summary, ids)
    if not helper:
        worker.log("notify: self-learn-notify not on PATH — notification skipped")
        return
    # The detached helper owns the action wait.  Its two notify-send legs are
    # both wrapped by ``timeout --kill-after=5 40`` and branch on action output.
    try:
        subprocess.Popen(
            [helper, "--line", line, "--ids", ",".join(ids)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        worker.log("notify: failed to spawn self-learn-notify")
