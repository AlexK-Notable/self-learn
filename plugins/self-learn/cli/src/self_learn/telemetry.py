"""Observation-plane telemetry: cache spool + verb flush (11 §4, v2).

Two-plane mechanism, pinned by the 2026-07-14 audit (11 §4.2):

- **Any process may append events to the SPOOL** —
  ``${XDG_CACHE_HOME:-~/.cache}/claude-skills/self-learn/spool/
  <month>.<actor>.jsonl`` — untracked transient state (S-7's ``~/.cache``
  class). Single-line JSON, ``flock`` on append (same-machine concurrent
  sessions are the common case).
- **Only human-triggered CLI verbs flush** the spool into the tracked
  plane — ``<home>/.self-learn/telemetry/<month>.<actor>.jsonl`` (root
  bucket, committed by autosync, NEVER staged by a resolution verb's
  surgical commit). At flush the §1 secret scan runs over every flushed
  line; a hit refuses the whole flush and leaves the spool intact.

Content discipline (11 §4.4): events carry ids, enums, versions, hashes,
counts — never lesson body text, quotes, transcript spans, or free text.
The one free-ish field, the offer decline reason, is a closed enum.

Flush truncates the spool file in place rather than unlinking it (the
inode stays stable, so a concurrent appender blocked on the flock can
never write into a deleted file — no reopen/retry dance). Empty spool
files from past months linger in the cache; that is deliberate and
harmless (~12 files/year).

Losing spool contents (cache wipe, crash before flush) degrades
analytics, never the ledger.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .scan import format_refusal
from .scan import scan as secret_scan

__all__ = [
    "DECLINE_REASONS",
    "EVENT_KINDS",
    "FlushReport",
    "NOTE_KINDS",
    "SCHEMA_VERSION",
    "ScanRefusal",
    "TelemetryError",
    "actor",
    "flush",
    "read_events",
    "spool_dir",
    "spool_event",
    "telemetry_dir",
]

#: Extending the closed event-kind set is a schema version bump (11 §4.3).
SCHEMA_VERSION = 1

#: The v1 closed set (11 §4.3).
EVENT_KINDS = frozenset(
    {
        "offer-made",
        "offer-declined",
        "capture",
        "card-shown",
        "card-decided",
        "fire",
        "recurrence-suspect",
        "staleness-flag",
        "surface-budget",
    }
)

#: Kinds the model may emit via ``telemetry note`` (the offer ledger).
#: Everything else is code-emitted inside CLI paths (11 §4.3 table).
NOTE_KINDS = frozenset({"offer-made", "offer-declined"})

#: Closed decline-reason enum — no free text (11 §4.3, audit v2).
DECLINE_REASONS = ("not-durable", "wrong", "duplicate", "private", "later", "other")


class TelemetryError(Exception):
    """A telemetry operation refused or failed."""

    exit_code = 1


class ScanRefusal(TelemetryError):
    """Scan-at-flush hit: the whole flush is refused, the spool is intact."""


def _cache_base() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    return base / "claude-skills" / "self-learn"


def spool_dir() -> Path:
    """The spool directory, XDG-resolved at call time (tests redirect it)."""
    return _cache_base() / "spool"


def telemetry_dir(home: Path | str) -> Path:
    """The tracked plane: ``<home>/.self-learn/telemetry/`` (root bucket).
    Bucket discovery and ``--selftest`` skip this directory — its files
    are observation lines, not records (11 §4.2)."""
    return Path(home) / ".self-learn" / "telemetry"


def actor() -> str:
    """Machine name — the single-writer filename component (11 §4.2).
    ``SELF_LEARN_ACTOR`` overrides (tests; team-scale ``machine.user``)."""
    return os.environ.get("SELF_LEARN_ACTOR") or socket.gethostname()


def _month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def spool_event(kind: str, *, now: datetime | None = None, **payload) -> Path:
    """Append one event line to this actor's current spool file.

    Cache-only — no repo write, no commit, safe from any process
    (11 §2.5's ``telemetry note`` row). Returns the spool path written.
    """
    if kind not in EVENT_KINDS:
        raise TelemetryError(
            f"unknown event kind {kind!r} — v1 kinds: {sorted(EVENT_KINDS)}"
        )
    reason = payload.get("reason")
    if reason is not None:
        if kind != "offer-declined":
            raise TelemetryError("--reason applies to offer-declined only")
        if reason not in DECLINE_REASONS:
            raise TelemetryError(
                f"decline reason must be one of {list(DECLINE_REASONS)}, "
                f"got {reason!r} (closed enum — no free text, 11 §4.3)"
            )
    event = {
        "ts": _now_iso(now),
        "kind": kind,
        "actor": actor(),
        "schema_version": SCHEMA_VERSION,
    }
    for key, value in payload.items():
        if value is None:
            continue
        if not isinstance(value, (str, int, float, bool)):
            raise TelemetryError(
                f"event field {key!r} must be a scalar (ids/enums/counts — "
                f"11 §4.4), got {type(value).__name__}"
            )
        event[key] = value
    line = json.dumps(event, separators=(",", ":"), sort_keys=True)

    path = spool_dir() / f"{_month(now)}.{actor()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(line + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return path


@dataclass
class FlushReport:
    """What one flush moved: event count per tracked file touched."""

    events: int = 0
    files: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        if not self.events:
            return "telemetry flush: spool empty"
        names = ", ".join(p.name for p in self.files)
        plural = "s" if self.events != 1 else ""
        return f"telemetry flush: {self.events} event{plural} → {names}"


def flush(home: Path | str) -> FlushReport:
    """Move every spooled event into the tracked plane (11 §4.2).

    Scan-at-flush: every line is secret-scanned first; a hit raises
    :class:`ScanRefusal` with the file, line number, and span — nothing
    is moved, the spool is intact (belt-and-suspenders; payloads are
    ids/enums by schema).

    The tracked files are appended, never staged or committed here —
    autosync commits them on its normal cycle; a resolution verb's
    surgical commit must never sweep them in.
    """
    home = Path(home)
    sdir = spool_dir()
    report = FlushReport()
    if not sdir.is_dir():
        return report

    for spool_path in sorted(sdir.glob("*.jsonl")):
        with open(spool_path, "r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
                if not lines:
                    continue
                for i, line in enumerate(lines, 1):
                    hits = secret_scan(line)
                    if hits:
                        raise ScanRefusal(
                            "secret scan hit at flush — refusing the flush; "
                            f"spool intact ({spool_path}:{i}):\n"
                            + format_refusal(hits)
                        )
                target = telemetry_dir(home) / spool_path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "a", encoding="utf-8") as out:
                    fcntl.flock(out.fileno(), fcntl.LOCK_EX)
                    try:
                        out.write("\n".join(lines) + "\n")
                        out.flush()
                    finally:
                        fcntl.flock(out.fileno(), fcntl.LOCK_UN)
                # Truncate in place: the inode stays stable, so a writer
                # blocked on our flock appends to THIS file, never a
                # deleted one.
                fh.seek(0)
                fh.truncate()
                report.events += len(lines)
                report.files.append(target)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return report


def read_events(home: Path | str) -> list[dict]:
    """Every event in the tracked plane, ts-ordered (11 §5: ts is the
    order; cross-machine order is partial and callers must say so).
    Malformed lines are skipped, never fatal — telemetry is cheap truth."""
    tdir = telemetry_dir(home)
    events: list[dict] = []
    if not tdir.is_dir():
        return events
    for path in sorted(tdir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    events.sort(key=lambda e: str(e.get("ts", "")))
    return events
