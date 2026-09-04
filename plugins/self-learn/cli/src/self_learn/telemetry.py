"""Observation-plane telemetry: cache spool + verb flush (11 §4, v2).

Two-plane mechanism, pinned by the 2026-07-14 audit (11 §4.2):

- **Any process may append events to the SPOOL** — ``<home-namespaced
  cache>/spool/<month>.<actor>.jsonl`` (doc 13 §6 / H-4: under
  ``${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<hash>/``) — untracked
  transient state (S-7's ``~/.cache`` class). Single-line JSON, ``flock``
  on append (same-machine concurrent sessions are the common case).
- **Only human-triggered CLI verbs flush** the spool into the tracked
  plane — ``<home>/telemetry/<month>.<actor>.jsonl`` (doc 13 §3 layout;
  NEVER staged by a resolution verb's surgical commit). At flush the §1
  secret scan runs over every flushed line; a hit refuses the whole
  flush and leaves the spool intact.

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
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from . import settings
from .ledger import resolve_home
from .primitives import chrono
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
    "spool_quiet",
    "telemetry_dir",
]

#: Extending the closed event-kind set is a schema version bump (11 §4.3).
#: v1 → v2 (U-reach §2.2): `route` joins the set. v2 → v3 (U-readref §5.1):
#: `reference-read` joins the set. No consumer filters on this number
#: (`read_events`, `report.gather`, `worker._recurrence_suspects` all key
#: on `kind` alone — verified), so the bump is honest bookkeeping, not a
#: migration.
SCHEMA_VERSION = 3

#: The v3 closed set (11 §4.3) — `route` and `reference-read` are
#: code-emitted only (never via `telemetry note`; see NOTE_KINDS below).
#: `reference-read` (U-readref §5.1) is the observation half of S-23's
#: reopening condition — ids-only (§5.2/§5.3), never model-emittable.
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
        "route",
        "reference-read",
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
    """The home-namespaced worker cache (doc 13 §6, H-4). Deferred import:
    worker imports this module at load time, so the top level must not
    import worker back."""
    from .worker import cache_dir

    return cache_dir()


def spool_dir() -> Path:
    """The spool directory, XDG-resolved at call time (tests redirect it)."""
    return _cache_base() / "spool"


def telemetry_dir(home: Path | str) -> Path:
    """The tracked plane: ``<home>/telemetry/`` (doc 13 §3 layout — a
    top-level dir of the independent ledger home). Bucket discovery and
    ``--selftest`` skip this directory — its files are observation lines,
    not records (11 §4.2)."""
    return Path(home) / "telemetry"


def actor() -> str:
    """Machine name — the single-writer filename component (11 §4.2).
    ``SELF_LEARN_ACTOR`` overrides (tests; team-scale ``machine.user``).

    U-settings Phase 1: resolves through the registry's ``ledger.actor``
    entry (config.yaml ``ledger.actor`` > env ``SELF_LEARN_ACTOR`` >
    ``socket.gethostname()``, called lazily -- U-flip 2026-09-01, S-58:
    config wins; MINOR-2 review r2 fold, this file was the ninth of nine
    stale docstrings and was missed in the first review pass). Neither
    caller in this
    module (:func:`spool_event`) threads a ``home`` — telemetry spooling
    is home-independent (XDG cache, not the ledger) — so this falls back
    to :func:`resolve_home` for the config.yaml rung only."""
    value, _source = settings.resolve_setting(resolve_home(), settings.by_name("ledger.actor"))
    return str(value)


def _month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _now_iso(now: datetime | None = None) -> str:
    """Thin wrapper kept for its ``now:`` parameter (a test-injected clock
    that must not be re-sampled) -- the format itself lives once, in
    :func:`self_learn.primitives.chrono.now_iso`."""
    return chrono.now_iso(now)


def spool_event(kind: str, *, now: datetime | None = None, **payload) -> Path:
    """Append one event line to this actor's current spool file.

    Cache-only — no repo write, no commit, safe from any process
    (11 §2.5's ``telemetry note`` row). Returns the spool path written.
    """
    if kind not in EVENT_KINDS:
        raise TelemetryError(
            f"unknown event kind {kind!r} — v2 kinds: {sorted(EVENT_KINDS)}"
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
        # Uniqueness nonce: two DISTINCT events can otherwise be
        # byte-identical (same second, same payload — e.g. two declined
        # offers in one burst), and read_events' crash-reflush dedupe
        # would wrongly collapse them. With the nonce, identical lines
        # can only be re-flushes. (Caught by the regime-audit tests.)
        "nonce": secrets.token_hex(4),
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


def spool_quiet(kind: str, **payload) -> Path | None:
    """Best-effort :func:`spool_event` for code-emitted events inside verb
    flows (capture, surface-budget): telemetry must never break the verb —
    a spool failure is a loud stderr warning, nothing more."""
    try:
        return spool_event(kind, **payload)
    except (TelemetryError, OSError) as exc:
        print(f"self-learn: telemetry spool failed: {exc}", file=sys.stderr)
        return None


@dataclass
class FlushReport:
    """What one flush moved: event count per tracked file touched.

    ``deferred_reason`` (M-M fold r1, gate MAJOR M-1) is set iff this
    flush could not even START moving events — ``commit_lock`` could not
    be taken (busy, or the repo itself is unavailable) — in which case
    every spooled line is STILL spooled (``deferred_events`` says how
    many) and ``events``/``files`` stay at their zero defaults. Without
    this field a deferral and an empty spool were indistinguishable to
    every caller: :meth:`summary` printed "spool empty",
    ``_flush_spool_best_effort`` returned ``"ok"``, and
    ``report.gather``'s ``counts_are_lower_bound`` read ``False`` while
    unflushed events sat invisibly in the spool."""

    events: int = 0
    files: list[Path] = field(default_factory=list)
    deferred_reason: str | None = None
    deferred_events: int = 0

    def summary(self) -> str:
        if self.deferred_reason is not None:
            plural = "s" if self.deferred_events != 1 else ""
            return (
                f"telemetry flush deferred: {self.deferred_events} "
                f"event{plural} remain spooled — {self.deferred_reason}"
            )
        if not self.events:
            return "telemetry flush: spool empty"
        names = ", ".join(p.name for p in self.files)
        plural = "s" if self.events != 1 else ""
        return f"telemetry flush: {self.events} event{plural} → {names}"


def flush(home: Path | str, *, push: bool = True) -> FlushReport:
    """Move every spooled event into the tracked plane (11 §4.2).

    ALL-OR-NOTHING (audit 2026-07-15): every spool file is locked and
    every line scanned BEFORE anything moves — a single scan hit raises
    :class:`ScanRefusal` and no file is flushed, so "spool intact" is
    true even across a month-rollover multi-file spool. Locks are taken
    in sorted-name order; appenders only ever hold one lock at a time,
    so ordering cannot deadlock.

    Crash windows (documented, not fully closed): dying between the
    tracked append and the spool truncate re-flushes those lines next
    time — :func:`read_events` dedupes identical lines, so downstream
    counts stay honest. A torn trailing tracked line (crash mid-append)
    is healed by prefixing a newline before the next append.

    The flushed files are staged (surgically — only the files this flush
    touched) and committed in the LEDGER repo with the pinned subject
    ``self-learn: telemetry flush <n> event(s)``, then best-effort pushed
    behind the :func:`gitops.has_remote` guard. ``push=False`` commits but
    publishes nothing — a verb invoked with ``--no-push`` said "keep this
    local", and a flush that pushed anyway would publish that verb's
    commit out from under it.

    M-M fold r1 (gate MINOR m-1): the tracked-plane append and its stage+
    commit are ONE continuous ``commit_lock`` hold, not two separate
    acquisitions — the lock opens before the first append and is still
    held when :func:`_commit_flush` stages and commits, closing the
    window a second producer could otherwise slip into between "append
    done" and "committed". Push stays OUTSIDE that hold (a push touches
    no index).

    That commit is this function's job because nothing else does it any
    more (audit 2026-07-16 MAJOR 3): the old docstring justified appending
    without committing by "autosync commits them on its normal cycle", but
    doc 13 H-5 removed the watcher from the ledger and no producer
    replaced it — so the tracked plane was never committed, never pushed,
    invisible on machine B, and destroyed by a re-clone. H-5's rule is
    that producers commit their own writes; telemetry is a producer. (A
    resolution verb's surgical commit still must never sweep these in —
    hence a commit of their own, not a shared one.)

    Git trouble is loud but never fatal: the events are already in the
    tracked file, and the next flush's commit sweeps them in.
    """
    home = Path(home)
    sdir = spool_dir()
    report = FlushReport()
    if not sdir.is_dir():
        return report

    opened: list[tuple[Path, BinaryIO, list[str]]] = []
    try:
        # Phase 1: lock every spool file and scan every line. Nothing is
        # written until every line of every file has passed.
        for spool_path in sorted(sdir.glob("*.jsonl")):
            try:
                fh = open(spool_path, "r+b")
            except (FileNotFoundError, OSError):
                continue  # vanished between glob and open (cache cleaner)
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            # FW-53: opened and decoded per LINE (binary read + per-line
            # decode), matching read_events' own fix — a spool file is
            # THIS-machine cache state (module docstring: "Losing spool
            # contents... degrades analytics, never the ledger"), so one
            # torn/corrupt line is dropped, never propagated into the
            # tracked plane, and never allowed to crash the flush of
            # every OTHER spool file's good events (the previous
            # ``open(..., encoding="utf-8")`` + ``fh.read()`` shape raised
            # UnicodeDecodeError on the FIRST bad byte, uncaught by the
            # `except telemetry.TelemetryError` guard around this call in
            # miner.py — turning even a run that landed candidates into
            # `status: failed`).
            lines: list[str] = []
            for raw_line in fh.read().split(b"\n"):
                try:
                    ln = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if ln.strip():
                    lines.append(ln)
            opened.append((spool_path, fh, lines))
        for spool_path, _fh, lines in opened:
            for i, line in enumerate(lines, 1):
                hits = secret_scan(line)
                if hits:
                    raise ScanRefusal(
                        "secret scan hit at flush — refusing the WHOLE "
                        f"flush; spool intact ({spool_path}:{i}):\n"
                        + format_refusal(hits)
                    )

        # Phase 2: everything scanned clean — move file by file, then
        # stage+commit, all under ONE commit_lock hold (M-M / P7 lock-
        # start gate, plan v2 §2/§5; M-M fold r1 MINOR m-1): a tracked-
        # plane append is a mutation of the ledger exactly like
        # `resolve_record`'s git mv, so the lock must open BEFORE it —
        # the same round-7 rule (module docstring above) applied to the
        # one producer round 7 never looked at — and stay held through
        # :func:`_commit_flush`'s stage+commit, not released and
        # reacquired, or a second producer could slip into the gap
        # between "appended" and "committed". Push stays OUTSIDE this
        # hold (see :func:`_commit_flush`'s docstring).
        #
        # If the lock cannot be taken at all (another producer wedged
        # mid-commit, or the repo itself is unavailable), NOTHING below
        # has run yet: the whole flush defers loud-but-not-fatal and the
        # spool is untouched (fold r1 MAJOR M-1 — `report.files` is still
        # empty in that case, which is exactly how the `except` below
        # tells "never appended" apart from "appended, commit failed").
        from . import gitops  # deferred: gitops is imported by every verb path

        # Fold r2 MINOR m-1: nothing to flush (every spool file was
        # empty) is NOT a deferral, even if commit_lock happens to be
        # busy right now — there is nothing pending for a busy lock to
        # defer. Return before the lock is even attempted, so an empty
        # spool never blocks on, or reports about, a lock it has no
        # need of. `finally` below still releases every spool handle.
        if not any(lines for _, _, lines in opened):
            return report

        try:
            with gitops.commit_lock(home):
                for spool_path, fh, lines in opened:
                    if not lines:
                        continue
                    target = telemetry_dir(home) / spool_path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "a+", encoding="utf-8") as out:
                        fcntl.flock(out.fileno(), fcntl.LOCK_EX)
                        try:
                            # Heal a torn trailing line from a previous
                            # crashed append: never concatenate onto it.
                            out.seek(0)
                            existing = out.read()
                            if existing and not existing.endswith("\n"):
                                out.write("\n")
                            out.write("\n".join(lines) + "\n")
                            out.flush()
                        finally:
                            fcntl.flock(out.fileno(), fcntl.LOCK_UN)
                    # Truncate in place: the inode stays stable, so a
                    # writer blocked on our flock appends to THIS file,
                    # never a deleted one.
                    fh.seek(0)
                    fh.truncate()
                    # Fold r2 n-2/n-3: release THIS spool file's flock
                    # (and close it) the instant its own read-and-
                    # truncate cycle is done, rather than holding it
                    # through the git stage+commit that follows. The
                    # spool flock's only job is to stop a concurrent
                    # producer's write from being lost between the read
                    # (phase 1) and this truncate — it has nothing to
                    # do with the git index, which commit_lock already
                    # guards on its own. Holding it further was scope
                    # creep from the single-hold restructure (fold r1
                    # MINOR m-1), not a deliberate widening.
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    fh.close()
                    report.events += len(lines)
                    report.files.append(target)
                # Still inside the SAME hold (m-1): stage+commit, never a
                # second acquisition.
                _commit_flush(home, report)
        except gitops.GitOpsError as exc:
            if not report.files:
                # Fold r1 MAJOR M-1: the lock itself could not be taken
                # (or the repo is unavailable) — nothing was appended,
                # every spooled line is still on disk. The reason comes
                # straight from the exception text (fold r1 NIT n-1: a
                # `GitOpsError` here is not always "lock busy" — it can
                # also be "not a git repository" — so it is never
                # hardcoded).
                report.deferred_reason = str(exc)
                report.deferred_events = sum(len(lines) for _, _, lines in opened)
                print(
                    f"self-learn: telemetry flush deferred — {exc}; spool "
                    "intact, the next flush retries",
                    file=sys.stderr,
                )
            else:
                # The append already happened (still holding the lock);
                # `_commit_flush`'s stage/commit is what failed. Genuinely
                # benign (unchanged from pre-fold): the events are on disk
                # and the NEXT flush's commit sweeps them in.
                print(
                    f"self-learn: telemetry flush commit failed ({exc}) — "
                    "the events are flushed but uncommitted; the next "
                    "flush commits them",
                    file=sys.stderr,
                )
            return report
    finally:
        # Fold r2 n-2/n-3: a spool file whose truncate already ran (and
        # already released/closed its own handle, above) must not be
        # touched again here — `fh.fileno()` on an already-closed file
        # object raises `ValueError` before `flock` ever runs, and a
        # double-close is itself a bug even where it wouldn't. Every
        # OTHER handle (skipped as empty, or never reached because the
        # scan/lock/commit raised first) is still open and still needs
        # this cleanup.
        for _path, fh, _lines in opened:
            if fh.closed:
                continue
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    if report.files and push:
        try:
            gitops.push_if_remote(home)
        except gitops.GitOpsError as exc:
            print(
                f"self-learn: telemetry flush committed but not pushed ({exc})",
                file=sys.stderr,
            )
    return report


def _commit_flush(home: Path, report: FlushReport) -> None:
    """H-5 (doc 13 §5): the producer commits its own writes. Surgical
    staging (only the flushed files), pinned subject. Raises
    :class:`gitops.GitOpsError` on failure — the caller (:func:`flush`)
    is the one that knows whether anything was appended yet, and prints
    accordingly.

    M-M fold r1 (MINOR m-1): this function no longer opens its own
    ``commit_lock`` or pushes — the CALLER must already hold the lock
    (opened before the first append, per :func:`flush`'s docstring), so
    append and commit are one continuous critical section rather than two
    separate hand-offs a racing writer could slip between. The push half
    lives in :func:`flush`, after that hold is released (a push touches
    no index — see the :mod:`self_learn.gitops` docstring for the scope
    and the probe behind it)."""
    if not report.files:
        return
    from . import gitops  # deferred: gitops is imported by every verb path

    # This flush was the reported thief: it runs from the DETACHED
    # worker (run end) as well as from foreground verbs, and its bare
    # index-wide commit swept a racing verb's git mv-ed rename into
    # "self-learn: telemetry flush N events" — the verb's pinned
    # subject then never entered history (H-6). Scope the commit to the
    # flushed files (the lock itself is the CALLER's, already held).
    gitops.stage(home, report.files)
    plural = "s" if report.events != 1 else ""
    gitops.commit(
        home,
        f"self-learn: telemetry flush {report.events} event{plural}",
        paths=report.files,
    )


def read_events(home: Path | str) -> list[dict]:
    """Every event in the tracked plane, ts-ordered (11 §5: ts is the
    order; cross-machine order is partial and callers must say so).

    Lenient by design — telemetry is cheap truth, never fatal: non-JSON
    lines, non-mapping lines, and lines without a string ``kind`` are
    skipped; byte-identical duplicate lines (the crash-between-append-
    and-truncate re-flush window) are counted once.

    FW-53: decoded per LINE, not per file — a single line that is not
    valid UTF-8 (a torn write, a corrupted byte) is skipped exactly like
    a non-JSON line already was, and never takes its file's other,
    perfectly good lines down with it. Reading the whole file as one
    ``str`` first (the previous shape) meant one bad byte ANYWHERE raised
    before the per-line loop even started — for a caller on the miner's
    path (`_event_seen`, called at the top of every `_reconcile_and_land`)
    that was `run()`'s outer handler turning the whole nightly run into
    `status: failed` over one torn telemetry line."""
    tdir = telemetry_dir(home)
    events: list[dict] = []
    seen: set[str] = set()
    if not tdir.is_dir():
        return events
    for path in sorted(tdir.glob("*.jsonl")):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        for raw_line in raw.split(b"\n"):
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not line or line in seen:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and isinstance(event.get("kind"), str):
                seen.add(line)
                events.append(event)
    events.sort(key=lambda e: str(e.get("ts", "")))
    return events
