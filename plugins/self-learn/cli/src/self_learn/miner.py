"""Transcript miner — autonomous capture (doc 12, ratified 2026-07-15).

The third producer beside teach and import ("continuous import"): a
nightly systemd timer — plus a 24 h verb autokick watchdog and manual
``self-learn mine run`` — walks Claude Code session transcripts, reduces
them to a deterministic structural digest (Phase 1: no model, no
embeddings — doc 12 §5), hands the digest to ONE contained ``claude -p``
reader driven by the versioned mining rubric (Phase 2), reconciles every
candidate against the ledger (Phase 3), and lands survivors in
``pending/`` as ``source: session`` records through the same scan-gated
writer path import uses (Phase 4). Mined records NEVER route (M-1); the
human gate is review.

Containment mirrors the M2 worker verbatim: allowed tools Read/Grep/Glob,
no Bash/Edit, and the write scope rides the settings-file ``Edit(//…)``
rule FAMILY (live-verified 2026-07-15) — pointed at the miner's CACHE
spool, so the model cannot touch the repo at all; only the CLI lands
records, behind the secret scan (refuse default, unattended policy:
drop + journal, never publish).

Observability contract (doc 12 §8 A1): every run appends one JSONL entry
to the run journal — trigger, sessions scanned, rubric version, and a
per-candidate outcome for everything that was seen and everything that
was clipped. ``self-learn mine status`` renders it; the future G-3 miner
pane reads the same file.

Kill switches: ``SELF_LEARN_MINER=0`` disables runs entirely;
``SELF_LEARN_MINER_AUTOKICK=0`` disables only the verb watchdog (the
test suite sets it globally in conftest). U-settings Phase 1: both now
also resolve a ``config.yaml`` rung (``miner.enabled``, ``miner.
autokick`` — see ``settings.py``'s registry); config.yaml wins over the
env var (U-flip 2026-09-01, S-58) — a saved ``miner.enabled: false``
overrides a machine-local env var, and a local exception must be
expressed in config or by unsetting the key.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, cast

from . import gitops, intents, invocation, provenance, provider, refs, sentinel, settings, steward_prompt, telemetry, worker
from .primitives import chrono, fsops
from . import reconcile as reconcile_mod
from .corroborate import MISMATCH, NO_EVIDENCE, RunEvidence
from .hosts import HostsError, capture_host_path, load_hosts
from .import_common import existing_origins
from .ledger import discover_buckets, home_state, home_state_message, resolve_home
from .ledger_ops import LedgerOpsError, create_record, record_title
from .mining import check as check_mod
from .mining import engine as engine_mod
from .mining import tools as mining_tools
from .mining import uuids as mining_uuids
from .mining import waiting as mining_waiting
from .overseer import run as overseer_run
from .records import (
    GENERALITIES,
    KINDS,
    RECORD_ID_RE,
    FrontmatterLoadError,
    Record,
    RecordError,
)
from .scan import scan as secret_scan

__all__ = [
    "CanaryError",
    "DEFAULT_CAP_MAX",
    "DEFAULT_CAP_PER_SESSION",
    "DEFAULT_PENDING_GATE",
    "MAX_NEARMISS_SNIPPET_CHARS",
    "MineResult",
    "canaries_path",
    "cap_for",
    "digest_transcript",
    "journal_path",
    "last_attempt_iso",
    "last_run_iso",
    "maybe_kick",
    "miner_dir",
    "plant_canary",
    "read_canaries_summary",
    "read_journal",
    "reader_timeout_secs",
    "run",
    "walk",
]

# ---- tunables (doc 12 §8 Q3: values scale/tune; enforcement is hard)
DEFAULT_CAP_PER_SESSION = 2
DEFAULT_CAP_MAX = 15
DEFAULT_PENDING_GATE = 25
REJECTED_RESURFACE_SIGHTINGS = 3  # §8 Q4
KICK_AFTER_SECS = 24 * 60 * 60  # R1 layer 2: verb autokick
ATTEMPT_COOLDOWN_SECS = 2 * 60 * 60  # audit 2026-07-15: failure backoff —
# without it a persistently failing reader converts every CLI invocation
# into a full walk+digest+15-min model attempt
STALE_AFTER_SECS = 36 * 60 * 60  # R1 layer 3: SessionStart alarm
#: The reader session's timeout: the default of the registry's
#: `miner.reader_timeout_secs` (:func:`reader_timeout_secs` returns the
#: operative value; env name SELF_LEARN_READER_TIMEOUT_SECS, FW-100).
INVOKE_TIMEOUT_SECS = float(cast(float, settings.by_name("miner.reader_timeout_secs").default))
JOURNAL_CAP_BYTES = 2_000_000
DEFAULT_MINER_MODEL = "claude-sonnet-5"

#: Injection-bandwidth caps (audit 2026-07-15: transcript text is
#: attacker-influenceable and landed fields autosync to the remote —
#: oversize model output is refused, never clipped into canon).
MAX_QUOTE_CHARS = 400
MAX_FIELD_CHARS = 1_000

#: 12 §11 / 02 §1 (U18): the episode brief's dedicated cap, one-sided by
#: design — ≈ the 200-word bound. The 100-word floor is rubric guidance
#: only (never enforced). Over the ceiling refuses the WHOLE candidate,
#: same refuse-not-clip posture as MAX_FIELD_CHARS above — never a
#: truncated brief on a landed record.
MAX_EPISODE_BRIEF_CHARS = 1_200

#: FW-34 §1.2: the near-miss snippet's own cap — smaller than the episode
#: brief because a snippet is a draft stub (trigger/instruction or
#: fact/context + why_durable), not a story. Refuse-not-clip: over the
#: cap the near-miss records counts only, never a truncated draft.
MAX_NEARMISS_SNIPPET_CHARS = 600

#: Model-authored reference validation (audit: session/line build the
#: evidence origin, which lands in tracked files and telemetry — free
#: text there is both a scan bypass and a flush-wedge risk).
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{3,63}$")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

#: Digest limits — a runaway session must not blow the reader's context.
#: Each is the DEFAULT of a registry setting (the number lives there);
#: a run reads the operative values once, into a :class:`DigestLimits`.
MAX_TEXT_CHARS = cast(int, settings.by_name("miner.message_chars").default)  # per kept turn
MAX_DIGEST_CHARS = cast(int, settings.by_name("miner.session_chars").default)  # per session digest
#: per run; overflow waits for the next run
MAX_PROMPT_DIGESTS_CHARS = cast(int, settings.by_name("miner.run_chars").default)


@dataclass(frozen=True)
class DigestLimits:
    """How much of the scanned sessions one mining run hands its reader.

    Every field is the registry setting ``miner.<field name>``;
    :func:`digest_limits` resolves them by walking the fields, so a new
    limit is one field here plus one ``settings.sizing_knob`` line and
    nothing else. All three are character counts today. This object is
    the one thing :func:`digest_transcript` and :func:`run` size
    against, so a different measure would be introduced here."""

    message_chars: int = MAX_TEXT_CHARS
    session_chars: int = MAX_DIGEST_CHARS
    run_chars: int = MAX_PROMPT_DIGESTS_CHARS


def digest_limits(home: Path | str | None = None) -> DigestLimits:
    """The operative :class:`DigestLimits` (config.yaml > env > default)."""
    root = home if home is not None else resolve_home()
    return DigestLimits(**{f.name: settings.resolve_int(root, f"miner.{f.name}") for f in fields(DigestLimits)})

#: Sessions whose FIRST user turn opens with one of these are the
#: system's own machinery — never mined (M-5). The worker's, the steward's and
#: the overseer's openings are not typed here: each is defined beside the
#: prompt that makes it (`worker.SESSION_OPENINGS`,
#: `steward_prompt.SESSION_OPENINGS`, `overseer.run.SESSION_OPENINGS`) and
#: `tests/test_miner_self_sessions.py` builds the real prompts and checks they
#: begin with them, so an edit to any of those prompts cannot quietly start
#: the miner reading that agent's sessions again (it did, until 2026-10-06).
#: Changing this list changes its fingerprint, and
#: :func:`halt_tracked_self_sessions` then checks the tracked files once more.
SELF_PROMPT_HEADERS = (
    "You are the self-learn transcript miner.",
    *worker.SESSION_OPENINGS,
    *steward_prompt.SESSION_OPENINGS,
    *overseer_run.SESSION_OPENINGS,
)
#: Self-learn command spans inside otherwise-minable sessions (M-5).
_COMMAND_SPAN_RE = re.compile(r"<command-name>/?self-learn:")

#: Sessions a scheduler started are not mined unless the user names the job
#: (M-5; the user, 2026-10-07: "scheduled jobs maybe not unless i explicitly
#: ask for coverage. background jobs yes."). Claude Desktop's scheduled tasks
#: open the session's first user turn with this tag, which names the task:
#: ``<scheduled-task name="<task>" file="…/scheduled-tasks/<task>/SKILL.md">``
#: (measured 2026-10-07: 38 of 38 such sessions, and no session of any other
#: kind). Claude Code's background sessions carry no such tag and are mined
#: as before. A ``claude -p`` that a systemd timer starts has no marker in its
#: transcript at all, so this rule cannot see it. Changing this opening changes
#: the scheduled-job fingerprint, and :func:`halt_tracked_scheduled_sessions`
#: then checks the tracked files once more.
SCHEDULED_JOB_OPENING = "<scheduled-task"
_SCHEDULED_TAG_RE = re.compile(re.escape(SCHEDULED_JOB_OPENING) + r"(?=[\s/>])[^>]*")
_TAG_NAME_RE = re.compile(r'\sname="([^"]*)"')
#: Reasons a session is halted, as the run's log names them.
HALT_SELF_PROMPT = "self-learn prompt"
HALT_SELF_COMMAND = "self-learn command"
HALT_SCHEDULED_JOB = "scheduled job"

OUTPUT_BASENAME = "mine-output.json"


def miner_dir() -> Path:
    d = worker.cache_dir() / "miner"
    d.mkdir(parents=True, exist_ok=True)
    return d


def journal_path() -> Path:
    return miner_dir() / "journal.jsonl"


def _now_iso() -> str:
    return chrono.now_iso()


#: Where :func:`log` writes while a preview runs: that run's own folder
#: (a preview changes nothing outside it); None for every other run.
_LOG_TO: Path | None = None


def log(message: str) -> None:
    path = _LOG_TO if _LOG_TO is not None else miner_dir() / "miner.log"
    if _LOG_TO is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{_now_iso()} {message}\n")
    worker._truncate_oldest(path, worker.LOG_CAP_BYTES)


def cap_for(sessions_scanned: int, *, home: Path | str | None = None) -> int:
    """Use-scaled landing cap (§8 Q3): min(per-session × scanned, max).

    U-settings Phase 1: both caps resolve through the registry
    (config.yaml `miner.cap_per_session`/`miner.cap_max` > env > their
    module defaults -- U-flip 2026-09-01, S-58: config wins) rather
    than a bare env read; `home` defaults to
    :func:`resolve_home` so the existing single-arg call shape is
    unaffected."""
    resolved_home = home if home is not None else resolve_home()
    per, _per_source = settings.resolve_setting(resolved_home, settings.by_name("miner.cap_per_session"))
    cap_max, _max_source = settings.resolve_setting(resolved_home, settings.by_name("miner.cap_max"))
    return min(cast(int, per) * max(sessions_scanned, 1), cast(int, cap_max))


def pending_gate(*, home: Path | str | None = None) -> int:
    """U-settings Phase 1: resolves through the registry's `miner.
    pending_gate` entry (config.yaml `miner.pending_gate` > env >
    :data:`DEFAULT_PENDING_GATE` -- U-flip 2026-09-01, S-58: config wins)."""
    value, _source = settings.resolve_setting(
        home if home is not None else resolve_home(), settings.by_name("miner.pending_gate")
    )
    return cast(int, value)


def miner_model() -> str:
    return os.environ.get("SELF_LEARN_MINER_MODEL") or DEFAULT_MINER_MODEL


def reader_timeout_secs(home: Path | str | None = None) -> float:
    """The reader session's timeout (doc 12 §2 Phase 2): the registry's
    ``miner.reader_timeout_secs`` (config.yaml > env
    ``SELF_LEARN_READER_TIMEOUT_SECS`` > :data:`INVOKE_TIMEOUT_SECS`).
    It resolves exactly as :func:`worker.invoke_timeout_secs` and
    :func:`worker.repair_timeout_secs` do — one resolver, the same
    parsing, validation, and fallback (FW-100's point; until 2026-09-20
    this was an env-only reader with no config.yaml rung)."""
    return settings.resolve_float(home if home is not None else resolve_home(), "miner.reader_timeout_secs")


def transcripts_root(home: Path | str | None = None) -> Path:
    """U-settings Phase 1: resolves through the registry's `miner.
    transcripts_dir` entry (config.yaml `miner.transcripts_dir` > env >
    `"~/.claude/projects"` -- U-flip 2026-09-01, S-58: config wins).
    Neither existing caller (:func:`initialize_cursors`, :func:`walk`)
    threads a `home`, so this still falls back to :func:`resolve_home`
    when `home` is omitted, the same way :func:`telemetry.actor` does
    (M-P, sprint 1 audit A14/A13 -- the optional `home` closes the gap
    for a future caller that DOES hold one).

    M-P fold r1 (F3): an explicit `home` is `.expanduser()`'d before use,
    matching :func:`resolve_home`'s own normalization -- `config_path`
    never expands `~` on its own, so an unexpanded `home` would silently
    miss `config.yaml` entirely."""
    resolved_home = Path(home).expanduser() if home is not None else resolve_home()
    raw, _source = settings.resolve_setting(resolved_home, settings.by_name("miner.transcripts_dir"))
    return Path(cast(str, raw)).expanduser()


def mined_scheduled_jobs(home: Path | str | None = None) -> frozenset[str]:
    """The scheduled jobs whose sessions are mined anyway: the registry's
    ``miner.mined_scheduled_jobs`` (config.yaml > env > none), comma-separated
    job names. A job is named as its scheduler names it, the ``name`` in the
    session's opening ``<scheduled-task name="...">`` tag (for Claude Desktop,
    the task's folder under ``~/.claude/scheduled-tasks/``). Blank entries are
    ignored; every other scheduled job's session is halted (M-5)."""
    raw, _source = settings.resolve_setting(
        home if home is not None else resolve_home(), settings.by_name("miner.mined_scheduled_jobs")
    )
    return frozenset(name.strip() for name in str(raw or "").split(",") if name.strip())


def skip_sessions(home: Path | str | None = None) -> frozenset[str]:
    """The sessions the miner never reads: the registry's
    ``miner.skip_sessions`` (config.yaml > env > none), comma-separated
    session ids, each a transcript's file stem (``<project>/<id>.jsonl``).
    Blank entries are ignored. :func:`walk` skips a listed file before
    reading it, on every walk, and persists nothing (2026-10-11)."""
    raw, _source = settings.resolve_setting(
        home if home is not None else resolve_home(), settings.by_name("miner.skip_sessions")
    )
    return frozenset(sid.strip() for sid in str(raw or "").split(",") if sid.strip())


def last_run_iso() -> str | None:
    try:
        mtime = (miner_dir() / "miner.last-run").stat().st_mtime
    except FileNotFoundError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
        chrono.ISO_FORMAT
    )


def last_attempt_iso() -> str | None:
    """Gate r1 B-1 -- `serve._mine_is_due` reads this the same way
    `maybe_kick`'s watchdog reads `_last_attempt_age_secs()` below: the
    SAME file (`miner.last-attempt`), touched on EVERY attempt (:1759),
    success OR failure -- so a mine that keeps failing (a refused home,
    a crash, or the reader/model call coming back empty, none of which
    touch `miner.last-run`) backs off for `ATTEMPT_COOLDOWN_SECS`
    instead of being retried on the very next tick."""
    try:
        mtime = (miner_dir() / "miner.last-attempt").stat().st_mtime
    except FileNotFoundError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
        chrono.ISO_FORMAT
    )


def _last_run_age_secs() -> float:
    try:
        return time.time() - (miner_dir() / "miner.last-run").stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def miner_enabled(home: Path | str | None = None) -> bool:
    """U-settings Phase 1: resolves through the registry's `miner.
    enabled` entry (config.yaml `miner.enabled` > env `SELF_LEARN_MINER`
    > `True` -- U-flip 2026-09-01, S-58: config wins). Extracted from
    :func:`stale` (M-P, sprint 1 audit A14/A13 -- the inline check there
    had no standalone name, so nothing could ever thread an explicit
    `home` through it); `home` defaults to :func:`resolve_home` when
    omitted, so :func:`stale`'s existing bare call is unchanged.

    M-P fold r1 (F3): an explicit `home` is `.expanduser()`'d before use,
    matching :func:`resolve_home`'s own normalization -- `config_path`
    never expands `~` on its own, so an unexpanded `home` would silently
    miss `config.yaml` entirely."""
    resolved_home = Path(home).expanduser() if home is not None else resolve_home()
    enabled, _source = settings.resolve_setting(resolved_home, settings.by_name("miner.enabled"))
    return bool(enabled)


def stale() -> bool:
    """SessionStart alarm predicate (R1 layer 3): no completed run in 36 h.
    A missing marker counts as infinitely old — self-healing, because the
    verb watchdog spawns a run on the next CLI use, which touches the
    marker even when idle. A deliberately disabled miner never alarms.

    Delegates the enabled check to :func:`miner_enabled` (M-P, sprint 1
    audit A14/A13); called bare here, unchanged from before the
    extraction -- no `home` is threaded at this call site."""
    if not miner_enabled():
        return False
    return _last_run_age_secs() > STALE_AFTER_SECS


# ------------------------------------------------------- Phase 0: the walk


@dataclass
class SessionSlice:
    """New lines of one transcript since the cursor."""

    path: Path
    session_id: str
    project: str
    start_line: int  # 0-based index of the first NEW line
    lines: list[str]
    stat_size: int = 0  # file size observed BEFORE the read (skip basis;
    # taken pre-read so an append racing the read forces a re-read next run)
    #: Why :func:`digest_transcript` halted this session (one of the
    #: ``HALT_*`` reasons), for the run's log; None while it is not halted.
    halt_reason: str | None = None


def _cursors_path() -> Path:
    return miner_dir() / "cursors.json"


def _load_cursors() -> dict:
    try:
        data = json.loads(_cursors_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cursors(cursors: dict) -> None:
    _cursors_path().write_text(
        json.dumps(cursors, indent=0, sort_keys=True), encoding="utf-8"
    )


def _complete_lines(path: Path) -> list[str] | None:
    """The file's newline-TERMINATED lines (audit 2026-07-15: a transcript
    mid-append at walk time must not have its torn tail consumed by the
    cursor — the partial line is left for the next run)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text:
        return []
    if not text.endswith("\n"):
        cut = text.rfind("\n")
        text = text[: cut + 1] if cut >= 0 else ""
    return text.splitlines()


def _contains_self_learn(text: str) -> bool:
    return _COMMAND_SPAN_RE.search(text) is not None or any(
        h in text for h in SELF_PROMPT_HEADERS
    )


def _user_turn_text(message: object) -> str:
    """The text blocks of one user entry's message, joined; blank blocks
    dropped. A tool-result-only entry has none, and neither has a message that
    is not a dict."""
    if not isinstance(message, dict):
        return ""
    texts = [str(b.get("text", "")) for b in _blocks(message) if b.get("type") == "text"]
    return "\n".join(t for t in texts if t.strip())


def _is_self_prompt(user_text: str) -> bool:
    """True when a session whose first user turn is `user_text` is one of
    self-learn's own agents (M-5): the text BEGINS with a header. A person
    who pastes a header into the middle of their own message does not match."""
    return user_text.strip().startswith(SELF_PROMPT_HEADERS)


def _scheduled_job_name(user_text: str) -> str | None:
    """The job a session belongs to when its first user turn `user_text` is a
    scheduler's: the text BEGINS with the ``<scheduled-task`` tag (as
    :func:`_is_self_prompt` requires of a header, so a person who pastes the tag
    into their own message is not a job). The name is the tag's ``name``
    attribute, '' when it has none. None for any other session."""
    tag = _SCHEDULED_TAG_RE.match(user_text.strip())
    if tag is None:
        return None
    name = _TAG_NAME_RE.search(tag.group(0))
    return name.group(1).strip() if name else ""


def _is_skipped_scheduled_job(user_text: str, mined: frozenset[str]) -> bool:
    """True when a session whose first user turn is `user_text` is a scheduled
    job's and the job is not one of `mined` (M-5)."""
    name = _scheduled_job_name(user_text)
    return name is not None and name not in mined


def _first_user_text_of(rows: Iterable[str]) -> str:
    """The first user turn that carries text among transcript `rows`, or ''.
    Stops there. A row of any odd shape (not JSON, JSON too deep to parse, a
    user row whose message is not a dict) is "no text here" and is skipped,
    never an exception."""
    for raw in rows:
        try:
            entry = json.loads(raw)
            if not isinstance(entry, dict) or entry.get("type") != "user":
                continue
            text = _user_turn_text(entry.get("message"))
        except Exception:  # noqa: BLE001 -- a row of any shape is only "no text here"
            continue
        if text.strip():
            return text
    return ""


def _first_user_text(path: Path) -> str:
    """The transcript's first user turn that carries text, or '' when the
    file has none. Streams the file and stops there: the prompt is among its
    first lines, and a transcript can be tens of MiB. A row of any odd shape
    is skipped (:func:`_first_user_text_of`). A file that cannot be
    opened or read raises :class:`OSError`; what that means is the caller's to
    say (bytes that are not UTF-8 are read as replacement characters instead)."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        return _first_user_text_of(fh)


#: The cursor file's record of which header list its tracked sessions were
#: last checked against: a fingerprint of :data:`SELF_PROMPT_HEADERS`.
_HEADERS_CHECKED_KEY = "__self_prompt_headers__"


def _headers_fingerprint() -> str:
    return hashlib.sha256("\n".join(SELF_PROMPT_HEADERS).encode("utf-8")).hexdigest()[:16]


#: The cursor file's record of which scheduled-job rule its tracked sessions
#: were last checked against: a fingerprint of the opening and of the jobs
#: named in ``miner.mined_scheduled_jobs``.
_SCHEDULED_CHECKED_KEY = "__scheduled_jobs__"


def _scheduled_fingerprint(mined: frozenset[str]) -> str:
    """Changes when the opening changes or when a job is named or unnamed in
    the opt-in, so that an unnamed job's tracked sessions are checked again."""
    rule = "\n".join((SCHEDULED_JOB_OPENING, *sorted(mined)))
    return hashlib.sha256(rule.encode("utf-8")).hexdigest()[:16]


class SweepResult(NamedTuple):
    """What a pass over the tracked sessions (:func:`halt_tracked_self_sessions`,
    :func:`halt_tracked_scheduled_sessions`) did: how many sessions it halted,
    and how many it could not check this time."""

    halted: int
    unchecked: int


def _halt_tracked(checked_key: str, fingerprint: str, halts: Callable[[str], bool]) -> SweepResult:
    """Halt every tracked, unhalted session whose first user turn `halts`, once
    per `fingerprint`, recorded in the cursor file under `checked_key`. The
    rules of the pass are :func:`halt_tracked_self_sessions`'s."""
    cursors = _load_cursors()
    if cursors.get(checked_key) == fingerprint:
        return SweepResult(0, 0)
    halted = unchecked = 0
    for key, entry in cursors.items():
        if not isinstance(entry, dict) or entry.get("halt"):
            continue
        try:
            text = _first_user_text(Path(key))
        except FileNotFoundError:
            continue
        except Exception:  # noqa: BLE001 -- one file never stops the pass
            unchecked += 1
            continue
        if halts(text):
            entry["halt"] = True
            halted += 1
    if not unchecked:
        cursors[checked_key] = fingerprint
    _save_cursors(cursors)
    return SweepResult(halted, unchecked)


def halt_tracked_scheduled_sessions(mined: frozenset[str]) -> SweepResult:
    """Halt every tracked session of a scheduled job that is not one of
    `mined`, once per rule (:func:`_scheduled_fingerprint`): the same pass as
    :func:`halt_tracked_self_sessions`, for the scheduled-job opening. It
    catches the sessions tracked before this rule existed, and those of a job
    removed from ``miner.mined_scheduled_jobs``. A job added there later is not
    un-halted: its earlier sessions are reachable through ``--since``."""
    return _halt_tracked(
        _SCHEDULED_CHECKED_KEY, _scheduled_fingerprint(mined), lambda text: _is_skipped_scheduled_job(text, mined)
    )


def halt_tracked_self_sessions() -> SweepResult:
    """Halt every tracked session whose first user turn is a self-learn
    prompt, once per header list.

    A header added to :data:`SELF_PROMPT_HEADERS` reaches only the sessions
    :func:`digest_transcript` sees from their first line. A file the cursor
    file already tracks is never shown to it again: an unchanged file is
    skipped without a read, and a grown one is read from its cursor onward,
    where the first prompt is not. So a session tracked before its header
    existed (the steward's and the overseer's, until 2026-10-06) stays
    unhalted, and mined as soon as it grows. This reads the head of each
    tracked, unhalted file once and halts the ones that open with a header,
    then records the header list's fingerprint in the cursor file; a later
    run with the same list reads nothing, and a changed list does it again.

    One file never stops the pass. A file that is gone (Claude Code deletes old
    transcripts) is left as it is, with nothing to check later. Any other
    failure on a file (a permission error, a failure of the check itself) leaves
    that file unhalted this time and counted in ``unchecked``; the fingerprint
    is then NOT recorded, so the next run checks the tracked files again, until
    a pass finishes with nothing unchecked. That costs one more read of each
    tracked file's first lines per run while a file stays unreadable."""
    return _halt_tracked(_HEADERS_CHECKED_KEY, _headers_fingerprint(), _is_self_prompt)


def initialized() -> bool:
    return bool(_load_cursors().get("__initialized__"))


def initialize_cursors(mined_scheduled: frozenset[str] = frozenset()) -> int:
    """First-activation forward-only pin (doc 12 §8 R2, audit B2): seed
    every EXISTING transcript's cursor at its current end so night one
    mines nothing — history is reachable only through the deliberate
    ``--since`` backfill. Files containing self-learn machinery markers
    anywhere in their existing history are halted outright (M-5: an
    in-flight review/worker session's tail must not become minable just
    because the cursor was seeded past its header), and so are the
    sessions of a scheduled job not in `mined_scheduled`, judged by their
    first user turn only. Returns the number of files seeded."""
    root = transcripts_root()
    cursors = _load_cursors()
    seeded = 0
    if root.is_dir():
        for path in sorted(root.glob("*/*.jsonl")):
            try:
                size = path.stat().st_size  # pre-read (same race rule as walk)
            except OSError:
                continue
            lines = _complete_lines(path)
            if lines is None:
                continue
            entry: dict = {"lines": len(lines), "size": size}
            if _contains_self_learn("\n".join(lines)) or _is_skipped_scheduled_job(
                _first_user_text_of(lines), mined_scheduled
            ):
                entry["halt"] = True
            cursors[str(path)] = entry
            seeded += 1
    cursors["__initialized__"] = _now_iso()
    # The seeding above halted by the same headers and the same scheduled-job
    # rule: nothing for the passes over tracked sessions to catch up on.
    cursors[_HEADERS_CHECKED_KEY] = _headers_fingerprint()
    cursors[_SCHEDULED_CHECKED_KEY] = _scheduled_fingerprint(mined_scheduled)
    _save_cursors(cursors)
    return seeded


def walk(since: str | None = None) -> list[SessionSlice]:
    """Every transcript with unread COMPLETE lines, oldest-modified first.
    ``since`` (YYYY-MM-DD) is the deliberate-backfill override: files
    modified on/after that date are re-read from line 0 (origin dedup
    makes landing replays safe). Halted files (self-learn machinery,
    M-5) are skipped without reading, and so are the sessions listed in
    ``miner.skip_sessions`` (:func:`skip_sessions`), in both branches."""
    root = transcripts_root()
    if not root.is_dir():
        return []
    since_ts = None
    if since:
        since_ts = (
            datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp()
        )
    cursors = _load_cursors()
    # Read on every walk and never written to the cursor file: taking an id
    # off the list makes its file minable again from its cursor, or from
    # line 0 if it never had one (2026-10-11).
    skipped = skip_sessions()
    candidates: list[tuple[float, Path, int, int]] = []
    for path in sorted(root.glob("*/*.jsonl")):
        entry = cursors.get(str(path), {})
        try:
            st = path.stat()
        except OSError:
            continue
        if since_ts is not None:
            # Unlike `halt`, which this backfill ignores, a listed session
            # is skipped here too: the list exists to keep copies of a
            # session from being read at all.
            if path.stem in skipped:
                continue
            if st.st_mtime < since_ts:
                continue
            start = 0
        else:
            if path.stem in skipped:
                continue
            if entry.get("halt"):
                continue
            if st.st_size == entry.get("size"):
                continue  # unchanged since last read — skip the I/O
            start = int(entry.get("lines", 0))
        candidates.append((st.st_mtime, path, start, st.st_size))
    slices: list[SessionSlice] = []
    for _mtime, path, start, size in sorted(candidates, key=lambda t: t[0]):
        lines = _complete_lines(path)
        if lines is None or len(lines) <= start:
            continue
        slices.append(
            SessionSlice(
                path=path,
                session_id=path.stem,
                project=path.parent.name,
                start_line=start,
                lines=lines[start:],
                stat_size=size,
            )
        )
    return slices


def _settle_waiting_cursors(answers: Iterable["mining_waiting.Answer"]) -> int:
    """Each waiting answer's cursor entry, applied again, forward only (fix
    round 4): the cursor a session took when its answer was saved. A file
    now shorter than it was then is left to the walk. Returns how many
    cursors moved."""
    cursors = _load_cursors()
    moved = 0
    for answer in answers:
        path, entry = answer.doc.get("transcript"), answer.doc.get("cursor")
        if not isinstance(path, str) or not isinstance(entry, dict):
            continue
        lines, size = entry.get("lines"), entry.get("size")
        if not isinstance(lines, int) or not isinstance(size, int):
            continue
        current = cursors.get(path, {})
        have = current.get("lines") if isinstance(current, dict) else None
        if isinstance(have, int) and have >= lines:
            continue
        try:
            if Path(path).stat().st_size < size:
                continue
        except OSError:
            continue
        new: dict = {"lines": lines, "size": size}
        if entry.get("halt") or (isinstance(current, dict) and current.get("halt")):
            new["halt"] = True
        cursors[path] = new
        moved += 1
    if moved:
        _save_cursors(cursors)
    return moved


def _advance_cursors(processed: list[tuple[SessionSlice, bool]]) -> None:
    """Advance past each slice's complete lines; a True halt flag is
    persisted so the REST of that session (including future appends) is
    never mined (audit 2026-07-15: exclusion state must survive cursor
    splits — it was slice-local before)."""
    cursors = _load_cursors()
    for s, halt in processed:
        entry: dict = {"lines": s.start_line + len(s.lines), "size": s.stat_size}
        if halt or cursors.get(str(s.path), {}).get("halt"):
            entry["halt"] = True
        cursors[str(s.path)] = entry
    _save_cursors(cursors)


# --------------------------------------- Phase 1: the structural digest


def _clip(text: str, cap: int = MAX_TEXT_CHARS) -> str:
    text = text.strip()
    if len(text) <= cap:
        return text
    return text[: cap // 2] + " …[clipped]… " + text[-cap // 2 :]


def _edges(text: str) -> str:
    """First + last line of a dropped tool-result body."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return _clip(lines[0], 200)
    return f"{_clip(lines[0], 200)} ⋯ {_clip(lines[-1], 200)}"


def _blocks(message: object) -> list[dict]:
    # A message that is not a dict (a malformed row) has no blocks: the
    # nightly loop calls `digest_transcript` with no error handling, so one
    # such row must never raise (2026-10-06).
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _norm_command(cmd: str) -> str:
    """Normalized command shape for retry-cluster detection: first two
    whitespace tokens."""
    return " ".join(str(cmd).split()[:2])


def _slice_cwd(s: SessionSlice) -> str | None:
    """The session's working directory — the FIRST ``cwd`` field seen in
    the slice (transcript lines carry one per entry). Binds a
    project-scoped candidate to ITS project (doc 13 §0 point 2: the
    miner reads every project's transcripts, so the project path must
    come from the transcript, never from any global default)."""
    for raw in s.lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if isinstance(entry, dict):
            cwd = entry.get("cwd")
            if isinstance(cwd, str) and cwd:
                return cwd
    return None


class HaltPoint(NamedTuple):
    """Where :func:`halt_point` stops a session slice.

    ``end`` is how many of the slice's ``lines`` are judged when the slice
    is cut (``lines[:end]``), None when it is not: 0 for a whole-session
    halt (nothing of the slice is read, not even lines before the halting
    turn), the halting line's index for a command tag. ``halt`` is True
    exactly when ``end`` is not None, and ``reason`` is then one of the
    ``HALT_*`` constants."""

    end: int | None
    halt: bool
    reason: str | None


def halt_point(s: SessionSlice, *, mined_scheduled: frozenset[str] = frozenset()) -> HaltPoint:
    """The halt decision for one session slice (M-5), without a digest:
    the one predicate both miners read (new-miner plan §3.1).

    The slice's first typed turn is its first ``user`` row that carries
    text (:func:`_user_turn_text`), whoever wrote it: ``refs.role_of`` is
    not read, so a relay or agent-written turn counts as it always has
    (S-90 left halts unchanged). It is counted within ``s.lines``, as
    :func:`digest_transcript` always counted it. Three halters:

    - that turn begins with a self-prompt header: :data:`HALT_SELF_PROMPT`,
      the whole session (``end`` 0);
    - that turn is a scheduled job's opening and the job is not one of
      `mined_scheduled`: :data:`HALT_SCHEDULED_JOB`, the whole session;
    - any user text turn holds a self-learn command tag
      (:data:`_COMMAND_SPAN_RE`): :data:`HALT_SELF_COMMAND`, the slice ends
      before that line.

    Reads ``s.lines`` only and changes nothing on ``s``. A line that is not
    JSON, or not a JSON object, is skipped, as the digest skips it."""
    first_user_seen = False
    for offset, raw in enumerate(s.lines):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "user":
            continue
        if refs.is_compact_provenance_note(entry):
            continue  # a mod's note is never the opening and never a command (refs rule 7a)
        user_text = _user_turn_text(entry.get("message") or {})
        if not user_text.strip():
            continue
        if not first_user_seen:
            first_user_seen = True
            if _is_self_prompt(user_text):
                return HaltPoint(0, True, HALT_SELF_PROMPT)  # own machinery: halt forever
            if _is_skipped_scheduled_job(user_text, mined_scheduled):
                return HaltPoint(0, True, HALT_SCHEDULED_JOB)  # a scheduler's session: halt forever
        if _COMMAND_SPAN_RE.search(user_text):
            return HaltPoint(offset, True, HALT_SELF_COMMAND)  # everything from the tag on is off-limits
    return HaltPoint(None, False, None)


def digest_transcript(
    s: SessionSlice,
    limits: DigestLimits | None = None,
    *,
    mined_scheduled: frozenset[str] = frozenset(),
    sent: provenance.SentIndex | None = None,
) -> tuple[str | None, bool]:
    """(digest-or-None, halt) for one session slice, sized against
    `limits` (the built-in defaults when omitted).

    Kept: user text turns (verbatim, clipped), assistant text turns,
    tool-use name + command shape, tool-result status + first/last lines.
    Dropped: tool-result bodies and tool-use payloads.

    Who wrote a user text turn is ``refs.role_of``'s answer (2026-10-19,
    with ``sent`` for its rule 10): ``[user L<n>]`` for the person,
    ``[agent L<n>]`` for text an agent wrote and typed into the session
    (a brief sent through herdr, an accepted suggestion), ``[relay L<n>]``
    for text the harness or a program put there (a headless prompt, a task
    notification, skill text, a compaction summary), ``[subagent L<n>]``
    for a sidechain row. A row that also carries a tool result keeps
    ``[user …]``. The halts read every user text turn, whoever wrote it,
    except a compact-provenance note (refs rule 7a), which they skip.

    halt=True means the REST of this session — including future appends —
    must never be mined; the caller persists it into the cursor. The
    decision is :func:`halt_point`'s, and only the lines before its
    ``end`` are digested. Three halters (M-5, tightened by audit
    2026-07-15): a self-prompt header (the system's own claude -p
    machinery); a scheduled job's opening (:data:`SCHEDULED_JOB_OPENING`,
    2026-10-07) unless the job is one of `mined_scheduled` (none when
    omitted); and ANY self-learn command tag — the old "span ends at the
    next genuine user turn" rule collapsed on the first review reply,
    feeding every card's lesson text (which the reader would dutifully
    match against the ledger) back into the miner as fake sightings.
    Recall loss from over-exclusion is cheap; evidence corruption is not.
    The reason is left on ``s.halt_reason`` for the run's log.
    """
    limits = limits if limits is not None else DigestLimits()
    out: list[str] = []
    stop = halt_point(s, mined_scheduled=mined_scheduled)
    halt = stop.halt
    if stop.halt:
        s.halt_reason = stop.reason
    command_counts: dict[str, list[int]] = {}  # norm shape -> [uses, errors]
    last_tool_shape: dict[str, str] = {}  # tool_use id -> display shape
    last_tool_norm: dict[str, str] = {}  # tool_use id -> norm shape

    for offset, raw in enumerate(s.lines[: stop.end]):
        lineno = s.start_line + offset + 1  # 1-based, for origins
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        etype = entry.get("type")
        message = entry.get("message") or {}
        if etype == "user":
            results = [b for b in _blocks(message) if b.get("type") == "tool_result"]
            user_text = _user_turn_text(message)
            if refs.is_compact_provenance_note(entry):
                continue
            if user_text.strip():
                role = refs.role_of(entry, sent=sent)
                label = role if role in ("agent", "relay", "subagent") else "user"
                out.append(f"[{label} L{lineno}] {_clip(user_text, limits.message_chars)}")
            for block in results:
                is_err = bool(block.get("is_error"))
                tid = str(block.get("tool_use_id"))
                shape = last_tool_shape.get(tid, "?")
                norm = last_tool_norm.get(tid)
                if norm in command_counts:
                    command_counts[norm][1] += 1 if is_err else 0
                status = "ERROR" if is_err else "ok"
                out.append(
                    f"[result L{lineno} {shape} {status}] "
                    f"{_edges(_result_text(block))}"
                )
        elif etype == "assistant":
            for block in _blocks(message):
                btype = block.get("type")
                if btype == "text":
                    text = str(block.get("text", ""))
                    if text.strip():
                        out.append(f"[assistant L{lineno}] {_clip(text, limits.message_chars)}")
                elif btype == "tool_use":
                    name = str(block.get("name", "?"))
                    inputs = block.get("input") or {}
                    shape = name
                    if name == "Bash" and isinstance(inputs, dict):
                        command = str(inputs.get("command", ""))
                        shape = f"Bash:{_clip(command, 80)}"
                        norm = f"Bash:{_norm_command(command)}"
                        command_counts.setdefault(norm, [0, 0])[0] += 1
                        last_tool_norm[str(block.get("id"))] = norm
                    last_tool_shape[str(block.get("id"))] = shape
    if not out:
        return None, halt

    clusters = [
        f"[retry-cluster {shape} ×{uses}, {errs} error(s)]"
        for shape, (uses, errs) in sorted(command_counts.items())
        if uses >= 3 and errs >= 1
    ]
    header = f"=== session {s.session_id} project {s.project} ==="
    body = "\n".join(clusters + out)
    if len(body) > limits.session_chars:
        body = body[: limits.session_chars] + "\n…[session digest clipped]"
    return f"{header}\n{body}", halt


# ----------------------------------------------- Phase 2: the reader pass


def spool_dir() -> Path:
    d = miner_dir() / "spool"
    d.mkdir(parents=True, exist_ok=True)
    return d


#: The miner's reader gets NO filesystem tools (audit 2026-07-15,
#: injection hardening): unlike the worker — which must open record
#: files — the reader's entire evidence base rides in the prompt, and
#: transcript digests are attacker-influenceable text. Write stays
#: available only through the settings-file Edit rule family, scoped to
#: the cache spool.
READER_DISALLOWED_TOOLS = worker.DISALLOWED_TOOLS + ",Read,Grep,Glob"


def _rubric() -> tuple[str, str]:
    """(text, version). Version comes from a `rubric-version:` marker.
    PACKAGE-relative (doc 13 T-H3): the rubric ships with the product
    beside the skill — never resolved through any home."""
    path = worker.package_skill_refs() / "mining-rubric.md"
    if not path.is_file():
        return ("(rubric missing — mine conservatively: corrections, "
                "verified gotchas, stated standing preferences only)"), "none"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"rubric-version:\s*(\S+)", text)
    return text, (m.group(1) if m else "unversioned")


def _ledger_index(home: Path, corrupt: list[Path] | None = None) -> str:
    """Compact all-status index the reader reconciles against (doc 12 §5:
    in-context comparison beats a vector index at this ledger size).

    FW-53: a ledger file that fails to even decode as UTF-8 is skipped
    exactly like a ``RecordError`` (malformed frontmatter) already was —
    its status/scope can't be read either way, so this sweep cannot place
    it, and this is the FIRST thing every productive run does (`run()`'s
    outer handler previously turned one bad byte anywhere in the ledger
    into `status: failed` for the whole run, before the reader ever saw a
    prompt). Unlike the pre-existing RecordError skip, the caller wants to
    know about THIS failure mode — appended to `corrupt` when given, so
    `_compose_prompt`/`_run_locked` can surface a non-silent count in the
    run journal (skip-and-report, not skip-and-forget)."""
    rows: list[str] = []
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            d = bucket.path / sub
            if not d.is_dir():
                continue
            for path in sorted(d.glob("lrn-*.md")):
                try:
                    r = Record.from_path(path)
                except (FrontmatterLoadError, UnicodeDecodeError):
                    # R4 (sweep 2, 2026-09-27): a header that does not
                    # load is reported exactly like FW-53's bad bytes.
                    if corrupt is not None:
                        corrupt.append(path)
                    continue
                except RecordError:
                    continue
                rows.append(
                    f"- {r.id} [{r.status}] ({r.scope}): {record_title(r)}"
                )
    return "\n".join(rows) if rows else "(ledger is empty)"


def _canon_index(home: Path, corrupt: list[Path] | None = None) -> str:
    """Routed rules for fire observation: id + title.

    FW-53: same decode-safety treatment as :func:`_ledger_index` (same
    sweep, same crash-before-the-reader risk, same skip-and-report
    contract)."""
    rows: list[str] = []
    for bucket in discover_buckets(home):
        d = bucket.path / "resolved"
        if not d.is_dir():
            continue
        for path in sorted(d.glob("lrn-*.md")):
            try:
                r = Record.from_path(path)
            except (FrontmatterLoadError, UnicodeDecodeError):
                if corrupt is not None:
                    corrupt.append(path)
                continue
            except RecordError:
                continue
            if r.status == "routed":
                rows.append(f"- {r.id} ({r.scope}): {record_title(r)}")
    return "\n".join(rows) if rows else "(no routed rules yet)"


_PROMPT_TEMPLATE = """You are the self-learn transcript miner. Below are structural digests of
recent Claude Code sessions (tool-result bodies removed; [user],
[agent], [relay], [subagent] and [assistant] turns and error/retry
annotations kept, each tagged with its transcript line). Your job: find
DURABLE lessons — user corrections, verified gotchas, stated standing
preferences, repeated friction — and
observations of routed rules firing. Apply the mining rubric strictly;
when in doubt, do not emit. A one-off task instruction is never a lesson.

Only a [user] line is the user's own words. An [agent] line is text
another agent wrote and typed into the session as if the user typed it
(a brief handed over by an orchestrating session, an accepted suggested
prompt); a [relay] line is text the harness or a program put there (a
headless prompt, a task notification, skill text, a compaction summary);
a [subagent] line is a subagent's. Read them as context around a moment,
never as a correction, ruling, or preference of the user's, and never
quote one as the user's words.

Write EXACTLY ONE file: {output_path}
JSON, this shape:
{{
  "candidates": [
    {{
      "scope": "skill:<name>" | "project" | "user",
      "type": "behavior" | "knowledge",
      "kind": "anti-pattern" | "surface-rule" | "reasoning-pattern",
      "trigger": "<firing condition — concrete paths/commands/situations>",
      "instruction": "<what to do, carrying the why, one line>",
      "fact": "<knowledge records only>", "context": "<optional>",
      "quote": "<SHORTEST transcript span proving the sighting>",
      "session": "<session id>", "line": <transcript line number>,
      "verified": true|false, "verified_how": "<if verified>",
      "incident_cost": "<human terms, if visible>",
      "generality": "environment-specific" | "general-practice" | "uncertain",
      "confidence": "high" | "medium" | "low",
      "why_durable": "<one line: why this will recur>",
      "episode_brief": "<OPTIONAL, 100-200 words: the attempt -> failure -> correction -> resolution arc, told in the plain, domestic terms the human lived it in — no record ids, no destination names (skill-md/hook/etc.), no unexpanded acronyms. RETELL, never quote: no verbatim transcript spans beyond the shortest-span quote above. Omit the field entirely when there is nothing worth reconstructing.>",
      "match": {{"record": "lrn-…" | null, "status": "pending" | "routed" | "rejected" | null}}
    }}
  ],
  "fires": [
    {{"record": "lrn-…", "session": "<id>", "line": <n>,
      "outcome": "suspected-compliance" | "suspected-violation" | "cannot-tell"}}
  ]
}}

Rules: behavior records need trigger+instruction; knowledge records need
fact. `match` reconciles against the LEDGER INDEX below — if a candidate
is the same lesson as an existing record, name it (the CLI verifies your
claim; a wrong id demotes the candidate). Never emit secrets, tokens, or
credentials in any field — shorten quotes around them. Emit nothing for
sessions that contain no durable lesson: an empty candidates list is a
correct and common answer. `episode_brief` is optional narrative prose
(100-200 words) reconstructing the episode so a human can recognize it
again after the transcript is gone — plain words, no jargon, a retelling
never a quotation; leave it out rather than pad it to reach the floor.
A fire is a suspicion, never a verdict: `suspected-compliance` — the
session's own text reads as following the rule; `suspected-violation` —
it reads as breaking it; `cannot-tell` — the digest does not show enough
to say either way, so emit this rather than guessing. The steward, not
you, decides whether a `suspected-violation` is a real recurrence.

=== MINING RUBRIC ===
{rubric}

=== LEDGER INDEX (reconcile against this) ===
{ledger}

=== ROUTED RULES (observe fires against these) ===
{canon}

=== SESSION DIGESTS ===
{digests}
"""


def _compose_prompt(
    home: Path, digests: list[str], output_path: Path
) -> tuple[str, list[Path]]:
    """Returns ``(prompt, corrupt)`` — ``corrupt`` is every ledger file the
    index sweeps (:func:`_ledger_index`, :func:`_canon_index`) skipped for
    failing to decode as UTF-8 (FW-53), so the caller can journal it
    instead of losing the fact silently."""
    corrupt: list[Path] = []
    ledger = _ledger_index(home, corrupt)
    canon = _canon_index(home, corrupt)
    prompt = _PROMPT_TEMPLATE.format(
        output_path=output_path,
        rubric=_rubric()[0],
        ledger=ledger,
        canon=canon,
        digests="\n\n".join(digests),
    )
    return prompt, corrupt


def _invoke_reader(home: Path, prompt: str) -> Path | None:
    """Run the contained reader (prompt on STDIN — audit B1); return the
    output file path if it exists. Split out so tests shim the model with
    a fake writer. On timeout the reader's whole process group is killed
    (a hung node child must not outlive the 15-minute budget).

    U-seam §3.9.2: the transport lives behind the invocation seam
    (``invocation.write_session``). U-cleanup §7: the reader carries no
    doctrine (``doctrine=None``) — closing this unit also closes the
    live residual §2.3 found (a settings JSON written to disk that
    nothing under the SDK backend ever reads); the writer that produced
    it is deleted, not merely unwired."""
    out_path = spool_dir() / OUTPUT_BASENAME
    out_path.unlink(missing_ok=True)
    # U-corrob (`COR7`/`COR9`/`COR10`): the reader's filesystem census is
    # `len(after - before)` over two RECURSIVE snapshots of `spool_dir()`
    # -- `before` taken here, immediately after the unlink above, so
    # pre-existing residue (a stray planted before this run, or a stale
    # `mine-output.json` an earlier early-return run left behind) cancels
    # rather than being counted as this run's write.
    before = {p for p in spool_dir().rglob("*") if p.is_file()}
    # N-2a (U-fw100 gate r1): bind once -- enforced and displayed must be
    # the SAME env read, not two independent calls straddling
    # containment_for(), so they cannot diverge by construction.
    timeout_secs = reader_timeout_secs(home)
    spec = invocation.SessionSpec(
        surface="miner-reader",
        prompt=prompt,
        cwd=home,
        timeout=timeout_secs,
        containment=invocation.containment_for(
            "miner-reader",
            disallowed_tools=READER_DISALLOWED_TOOLS,
            spool_dir=spool_dir(),
        ),
        log=log,
        timeout_display=timeout_secs,
        doctrine=None,
    )
    outcome = invocation.write_session(spec)
    # U-corrob: `after` is taken here -- before the early return below
    # and before the stray sweep -- so a session that times out or fails
    # to spawn still gets an honest census, and the sweep (which only
    # ever touches strays, never `out_path`) cannot perturb the count.
    after = {p for p in spool_dir().rglob("*") if p.is_file()}
    fs_count = len(after - before)
    evidence = RunEvidence(spool_dir(), flat=False)
    evidence.observe(outcome)
    tag = evidence.verdict(fs_count)
    if tag == NO_EVIDENCE:
        log(
            "run: corroboration — no tool events recorded "
            f"({fs_count} artifact(s) in the spool)"
        )
    elif tag == MISMATCH:
        log(
            f"run: corroboration MISMATCH — spool has {fs_count} "
            f"artifact(s), model reported {len(evidence.inside)} accepted "
            "write(s) (filesystem is authority)"
        )
    outside = evidence.outside_paths()
    if outside:
        log(
            f"run: {len(outside)} accepted write(s) reported OUTSIDE the "
            f"spool (filesystem is authority; see the event log in {worker.cache_dir()})"
        )
    # U-corrob (`DEN1`/`DEN2`, the `FW-107` pattern extended): the
    # miner-reader has no FAILED line of its own, so a fully-denied
    # reader run used to be indistinguishable from one that wrote
    # nothing -- the identical defect `FW-107` fixed for the worker.
    # `source == "sdk-result"` denials never count (`DEN2`).
    charter_denials = [
        d for d in getattr(outcome, "denials", ()) if d.get("source") == "charter"
    ]
    if charter_denials:
        tools = sorted({d.get("tool") for d in charter_denials if d.get("tool")})
        log(
            f"run: {len(charter_denials)} charter denial(s) this run "
            f"({', '.join(tools)}) — see the event log in {worker.cache_dir()}"
        )
    if outcome.failure in {"timeout", "not-found", "os-error", "unavailable"}:
        return None
    # Artifact contract: exactly OUTPUT_BASENAME; strays are litter.
    for path in spool_dir().iterdir():
        if path.name != OUTPUT_BASENAME and path.is_file():
            log(f"run: stray spool artifact {path.name} deleted")
            path.unlink(missing_ok=True)
    return out_path if out_path.is_file() else None


# ------------------------------------- Phase 3+4: reconcile, cap, land


@dataclass
class MineResult:
    #: ok | idle | held-gate | failed | disabled | busy |
    #: landed-uncommitted (BLOCKER B (c): candidates written, commit
    #: failed, cursors advanced anyway — never re-mined, never published) |
    #: stopped (S-62 §7.2a.5(4): a live intent STOP froze this run at
    #: START, before enumeration or any model session)
    status: str
    run_id: str = ""
    sessions_scanned: int = 0
    landed: list[str] = field(default_factory=list)
    folded: list[str] = field(default_factory=list)
    recurrences: list[str] = field(default_factory=list)
    fires: int = 0
    dropped: int = 0
    outcomes: list[dict] = field(default_factory=list)
    touched: list[Path] = field(default_factory=list)  # ledger paths to commit (H-5)
    #: True iff the landing commit failed — the records are on disk and
    #: untracked. Drives ``status`` (and thus `mine status` + the CLI exit).
    landing_uncommitted: bool = False
    #: FW-53: ledger files skipped by the reconciliation index because
    #: they failed to decode as UTF-8 — degrade (skip, count, land the
    #: rest), never wedge the whole run, but never silently either;
    #: journaled every time it is non-empty.
    corrupt_records: list[str] = field(default_factory=list)
    #: U-cursorhold O-3: distinct session ids whose cursor this run HELD
    #: (withheld from the advance) because a cap drop cited them and they
    #: were not halted. Never serialised itself — the journal writes only
    #: its length, under `cursors_held` (BD3).
    held_sessions: set[str] = field(default_factory=set)
    #: S-62 (§7.2a.5(4)): populated only when `status == "stopped"` — the
    #: run-start reconcile found a live intent it could neither roll
    #: forward nor restore, and this run ended THERE, before enumeration
    #: and before any model session was spent. One `"{id}: {reason}"`
    #: string per offender, mirroring `ReconcileResult.stopped`.
    stopped: list[str] = field(default_factory=list)
    #: The session engine's counts for this run (R2): what `mine run
    #: --preview` prints -- sessions by filter reason, calls, drops by
    #: reason, spine token estimates, cost. Counts and ids only, never
    #: transcript text. Empty for the digest engine.
    engine: dict = field(default_factory=dict)


def _outcome(result: MineResult, origin: str, outcome: str, **extra) -> None:
    result.outcomes.append({"origin": origin, "outcome": outcome, **extra})


def _find_record(home: Path, rid: str) -> tuple[Record, str] | None:
    """(record, status-dir) across all buckets, or None.

    FW-53: a file that fails to decode as UTF-8 is treated the same as a
    `RecordError` (malformed frontmatter) already was — `None`, i.e. "not
    usable", not a crash. Every call site already treats a `None` return
    the same way it treats "no such record" (a demoted match-claim, a
    skipped fire/backfill row) — see the `_reconcile_and_land` backfill
    loop's own comment: an unbounded pass over telemetry must never raise
    on one unresolvable row, or `run()`'s outer handler wedges every
    future nightly run on that one row forever."""
    if not rid or not RECORD_ID_RE.match(rid):
        return None
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            path = bucket.path / sub / f"{rid}.md"
            if path.is_file():
                try:
                    return Record.from_path(path), sub
                except (RecordError, UnicodeDecodeError):
                    return None
    return None


def _rejected_counter_bump(rid: str, origin: str) -> int:
    """Q4 resurfacing counter (cache-side). Returns fresh-sighting count;
    -1 once the resurfaced candidate has already landed."""
    path = miner_dir() / "rejected-sightings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    entry = data.get(rid)
    if entry == "landed":
        return -1
    sightings = set(entry or [])
    sightings.add(origin)
    data[rid] = sorted(sightings)
    fsops.atomic_write(path, json.dumps(data, indent=0, sort_keys=True))  # whole or not at all
    return len(sightings)


def _rejected_mark_landed(rid: str) -> None:
    path = miner_dir() / "rejected-sightings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[rid] = "landed"
    # atomic (fix round 5): a resurface replayed after a stop marks it
    # again, and a torn file would forget every other record's count
    fsops.atomic_write(path, json.dumps(data, indent=0, sort_keys=True))


def _valid_skill_scope(home: Path, scope: str) -> bool:
    """The SKILL directory must exist in the registered skills-root HOST
    (doc 13 H-3) — not the bucket (which only exists after a first
    capture; create_record creates it on demand). The name is regex-gated
    BEFORE it reaches any glob (audit: `skill:s*` would otherwise
    validate against a real skill and land with a nonsense scope
    string). No skills root registered → no skill scope is valid."""
    name = scope.partition(":")[2]
    if not _SKILL_NAME_RE.match(name):
        return False
    root = load_hosts(home).skills_root
    if root is None:
        return False
    return any(p.is_dir() for p in root.glob(f"plugins/*/skills/{name}"))


def _build_record(home: Path, cand: dict) -> Record:
    """Compose a Record from a candidate dict; raises RecordError on any
    schema violation (the caller journals + drops)."""
    scope = str(cand.get("scope") or "project")
    if scope.startswith("skill:") and not _valid_skill_scope(home, scope):
        raise RecordError(f"unknown skill bucket for scope {scope!r}")
    if scope not in ("project", "user") and not scope.startswith("skill:"):
        raise RecordError(f"bad scope {scope!r}")
    rtype = str(cand.get("type") or "")
    if rtype == "behavior":
        kind = str(cand.get("kind") or "surface-rule")
        if kind not in KINDS:
            raise RecordError(f"bad kind {kind!r}")  # drop, never coerce
        trigger = str(cand.get("trigger") or "").strip()
        instruction = str(cand.get("instruction") or "").strip()
        if len(trigger) > MAX_FIELD_CHARS or len(instruction) > MAX_FIELD_CHARS:
            raise RecordError("field over injection-bandwidth cap")
        record = Record.create(
            type="behavior",
            scope=scope,
            source="session",
            kind=kind,
            trigger=trigger,
            instruction=instruction,
        )
    elif rtype == "knowledge":
        fact = str(cand.get("fact") or "").strip()
        context = (
            (str(cand.get("context")).strip() or None)
            if cand.get("context")
            else None
        )
        if len(fact) > MAX_FIELD_CHARS or len(context or "") > MAX_FIELD_CHARS:
            raise RecordError("field over injection-bandwidth cap")
        record = Record.create(
            type="knowledge",
            scope=scope,
            source="session",
            fact=fact,
            context=context,
        )
    else:
        raise RecordError(f"bad type {rtype!r}")
    # 12 §11 / 02 §1 (U18): the episode brief COMPOSES INTO record.body
    # HERE — before _scan_candidate runs (miner.py:1024) — never in
    # create_record (which runs after the scan). This ordering is the
    # whole compose-before-scan invariant: the brief is body bytes the
    # secret scan already walks (record.body is in _scan_candidate's
    # text list) ONLY because it landed in the body before the scan call.
    # Both record types register "Episode brief" as optional (records.py
    # OPTIONAL_SECTIONS), so record.set_body's re-validation accepts it.
    # Free prose, no structured refs — no _valid_ref gating applies here.
    episode_brief = str(cand.get("episode_brief") or "").strip()
    if episode_brief:
        if len(episode_brief) > MAX_EPISODE_BRIEF_CHARS:
            # Refuse-not-clip (§10-2 posture): over the ceiling drops the
            # WHOLE candidate, never a truncated brief on a landed record.
            raise RecordError(
                f"episode brief over cap ({MAX_EPISODE_BRIEF_CHARS} chars)"
            )
        record.set_body(
            record.body.rstrip("\n") + "\n\n## Episode brief\n" + episode_brief + "\n"
        )
    if cand.get("verified"):
        record.set_verified(True, how=(cand.get("verified_how") or None))
    if cand.get("incident_cost"):
        record.set_incident_cost(str(cand["incident_cost"]))
    generality = cand.get("generality")
    if generality in GENERALITIES:
        record.set_generality(generality)
    return record


def _scan_candidate(record: Record, cand: dict, quote: str) -> list:
    """Scan everything that will land or be journaled. ``quote`` is the
    EFFECTIVE quote (post length-cap), not the raw candidate field."""
    texts = [record.body, quote]
    for key in ("verified_how", "incident_cost", "why_durable"):
        if cand.get(key):
            texts.append(str(cand[key]))
    return [h for t in texts if t for h in secret_scan(t)]


def _valid_ref(cand: dict) -> tuple[str, int] | None:
    """Validate the model-authored (session, line) pair — these build the
    evidence origin, which lands in tracked files and telemetry events
    (all-or-nothing flush: one secret-shaped span there would wedge every
    future flush). Free text is refused, never passed through."""
    session_id = str(cand.get("session") or "")
    line = cand.get("line")
    if not _SESSION_ID_RE.match(session_id):
        return None
    if not isinstance(line, int) or isinstance(line, bool) or not (
        1 <= line <= 10_000_000
    ):
        return None
    return session_id, line


#: U-recur spec §4 decision 1: a literal distinct from the candidate
#: path's "miner-match" (:1183) and from the worker's origin-match /
#: title-token-overlap (worker.py:1001-1006) — it labels the SOURCE of
#: suspicion, not a similarity metric. *Amended 2026-09-13 (steward
#: build, U6):* THE CROSSOVER is removed — a miner-observed
#: `suspected-violation` is never auto-decided into a recurrence-suspect
#: (11 §4.3, `12-transcript-miner.md` §7 M-1). THE BACKFILL below is the
#: only remaining caller: a one-way migration net for rows already
#: sitting in the tracked plane with the pre-U6 raw `violated` value,
#: never for anything reported under the new vocabulary. The label moves
#: with the rename `commands/review.md` already applies on read (a basis
#: recorded before it still reads `fire-violated`; the CLI accepts both
#: spellings).
_FIRE_VIOLATED_BASIS = "fire-suspected-violation"


def _event_seen(
    home: Path,
) -> tuple[set[tuple[str, str, str]], list[tuple[str, str]]]:
    """(kind, record, origin) for fire/recurrence-suspect events —
    replay dedup (audit: crash-replay and the DOCUMENTED --since replay
    duplicated both classes; nonces make byte-dedup useless).

    Also returns ``violated_fires`` — ``(record, origin)`` pairs drawn
    from tracked ``fire`` events with the RAW (pre-mapping) outcome
    ``"violated"``, in ``read_events`` (ts-ordered) order. *Amended
    2026-09-13 (steward build, U6):* this is now a LEGACY-ONLY list —
    every `fire` event spooled going forward carries one of the three
    new outcome values (the acceptance check in `_reconcile_and_land`
    refuses the raw model output otherwise), so a row with the literal
    string `"violated"` can only be one written before this change
    shipped. ``read_events(..., map_legacy_outcome=False)`` is used
    deliberately here: the mapped view (every other caller's default)
    would show `"suspected-violation"` for these same rows and erase the
    one signal that proves a row is legacy rather than newly-reported —
    which is exactly what THE BACKFILL (the comment block below, grep `THE BACKFILL`) needs to stay a bounded
    migration net instead of reopening the crossover one run late. This
    is still THE BACKFILL's source list (U-recur spec §4 decision 4):
    one ``read_events`` pass serves both purposes, no second read.
    Telemetry lines are untrusted input (11 §4.2): a row whose
    ``record``/``origin`` is not a string is skipped, and ``record`` is
    re-validated against :data:`RECORD_ID_RE` — never a crash, never a
    guessed id."""
    seen: set[tuple[str, str, str]] = set()
    violated_fires: list[tuple[str, str]] = []
    for e in telemetry.read_events(home, map_legacy_outcome=False):
        kind = e.get("kind")
        if kind not in ("fire", "recurrence-suspect"):
            continue
        record = e.get("record")
        origin = e.get("origin")
        seen.add((kind, str(record), str(origin)))
        if (
            kind == "fire"
            and e.get("outcome") == "violated"
            and isinstance(record, str)
            and isinstance(origin, str)
            and RECORD_ID_RE.match(record)
        ):
            violated_fires.append((record, origin))
    return seen, violated_fires


def _raise_recurrence_suspect(
    result: MineResult,
    seen_events: set[tuple[str, str, str]],
    rid: str,
    origin: str,
    basis: str,
) -> None:
    """U-recur spec §4 decision 5's ONE emission point: spools the
    suspect, checks/updates THE SUSPECT KEY
    (``("recurrence-suspect", rid, origin)``) against ``seen_events``,
    appends to ``result.recurrences``, and writes the
    ``recurrence-from-fire`` journal row. *Amended 2026-09-13 (steward
    build, U6):* THE CROSSOVER is gone (11 §4.3, `12-transcript-miner.md`
    §7 M-1 — a fire is never auto-decided into a recurrence by the
    miner); THE BACKFILL (below) is now the only caller, kept as one
    emission point on principle even with a single call site. A no-op
    when the key is already present; that is the whole dedupe contract."""
    key = ("recurrence-suspect", rid, origin)
    if key in seen_events:
        return
    telemetry.spool_quiet(
        "recurrence-suspect", record=rid, origin=origin, basis=basis
    )
    seen_events.add(key)
    result.recurrences.append(rid)
    _outcome(result, origin, "recurrence-from-fire", record=rid)


# ---------------------------------------- FW-34 §1: near-miss visibility

#: §1.1's 5-way fold table: internal `outcome` → human-facing
#: `disposition`. This fold itself does not change the outcome vocabulary
#: (12 A1) — it is a read-time-independent, deterministic translation
#: applied once at journal-write (never re-derived in the UI, the
#: no-derivation rule). `landed`/`resurfaced`/`recurrence-from-fire` are
#: absent on purpose: they are not near-misses, so they carry no
#: disposition at all (12 §12.1, canon amended by U-recur).
_NEARMISS_DISPOSITION: dict[str, str] = {
    "dropped-cap": "cap-refused",
    "rubric-dropped": "rubric-dropped",
    "folded": "already-canon",
    "skipped-resolved": "already-canon",
    "recurrence": "already-canon",
    "recurrence-already-known": "already-canon",
    "skipped-known-origin": "already-canon",
    "dropped-rejected": "rejected",
    "scan-refused": "scan-blocked",
    "fold-quote-scan-refused": "scan-blocked",
    "dropped-invalid": "other",
    "dropped-land-failed": "other",
    "match-claim-invalid": "other",
    "quote-dropped-overlength": "other",
}

#: One plain-words (Y-9 register) line per disposition — no enums, no
#: ids, no unexpanded acronyms.
_NEARMISS_REASON: dict[str, str] = {
    "cap-refused": "a real lesson, but this run had already landed its cap",
    "rubric-dropped": "the reader saw a moment here but judged it below the durability bar",
    "already-canon": "this is already reflected in an existing lesson",
    "rejected": "a lesson like this was reviewed before and turned down",
    "scan-blocked": "this looked like it might contain a secret, so it was held back",
    "other": "this candidate could not be landed",
}

#: Dispositions a human can promote (§2.3, F5) — gated further by an
#: actually-clean snippet at enrichment time.
_PROMOTABLE_DISPOSITIONS = frozenset({"cap-refused", "rubric-dropped"})


def _snippet_fields(cand: dict) -> dict | None:
    """§1.2: ``{type, trigger, instruction}`` | ``{type, fact, context}``
    + ``why_durable``, drawn from a candidate/near-miss dict already in
    scope. ``None`` for an unrecognized ``type`` — never a guessed shape.
    No evidence quote is ever included (§1.2 / F3-(a)).

    Also carries ``scope``/``kind`` WHEN the source dict has them (a full
    reader ``candidates[]`` entry does; the leaner ``near_misses[]``
    schema, §1.3, does not) — §2.3's promote argv needs a scope to build
    ``teach --<scope>``, and these are cheap, short, enum-shaped strings
    already scanned/capped by the same snippet defenses. A rubric-dropped
    row with no source scope simply has none here; the promote route
    falls back to teach's own documented default (project, 01 §2)."""
    rtype = str(cand.get("type") or "")
    if rtype == "behavior":
        fields: dict = {
            "type": "behavior",
            "trigger": str(cand.get("trigger") or "").strip(),
            "instruction": str(cand.get("instruction") or "").strip(),
        }
        kind = str(cand.get("kind") or "").strip()
        if kind:
            fields["kind"] = kind
    elif rtype == "knowledge":
        fields = {"type": "knowledge", "fact": str(cand.get("fact") or "").strip()}
        context = str(cand.get("context") or "").strip()
        if context:
            fields["context"] = context
    else:
        return None
    scope = str(cand.get("scope") or "").strip()
    if scope:
        fields["scope"] = scope
    why_durable = str(cand.get("why_durable") or "").strip()
    if why_durable:
        fields["why_durable"] = why_durable
    return fields


def _nearmiss_snippet(fields: dict) -> dict:
    """§1.2 build-pin: field-by-field ``secret_scan``, evaluated BEFORE
    the caller's ``_outcome`` call — nothing near-miss enters the journal
    unscanned. Returns a clean dict, ``{scan_refused_rule}`` (rule name
    only, never the content), or ``{overlength: True}``
    (:data:`MAX_NEARMISS_SNIPPET_CHARS`, refuse-not-clip — checked
    first, so an oversize attacker-influenceable blob is never scanned
    for nothing)."""
    total = sum(len(v) for v in fields.values() if isinstance(v, str))
    if total > MAX_NEARMISS_SNIPPET_CHARS:
        return {"overlength": True}
    for value in fields.values():
        if isinstance(value, str) and value:
            hits = secret_scan(value)
            if hits:
                return {"scan_refused_rule": hits[0].rule}
    return fields


def _handle_near_misses(result: MineResult, parsed: dict) -> None:
    """§1.3: the one reader-output extension — an optional
    ``near_misses[]`` array beside ``candidates``/``fires``. Every field
    rides the identical injection-bandwidth defenses as candidate fields:
    :data:`MAX_FIELD_CHARS` refuse-not-clip (an over-length field drops
    the WHOLE near-miss, mirroring `_build_record`'s candidate cap), the
    §1.2 build-pin scan, and `_valid_ref` gating on the session/line ref
    (an invalid ref drops the whole near-miss too — never a guessed
    origin). The miner works completely without this array (M-3)."""
    near_misses = parsed.get("near_misses") or []
    if not isinstance(near_misses, list):
        return
    for nm in near_misses:
        if not isinstance(nm, dict):
            continue
        ref = _valid_ref(nm)
        if ref is None:
            continue  # invalid ref drops the whole near-miss (§1.3)
        session_id, line = ref
        origin = f"transcript:{session_id}#L{line}"
        fields = _snippet_fields(nm)
        if fields is None:
            continue  # unrecognized type — never a guessed shape
        text_values = [v for k, v in fields.items() if k != "type"]
        if any(len(v) > MAX_FIELD_CHARS for v in text_values):
            continue  # refuse-not-clip: over-length drops the WHOLE near-miss
        snippet = _nearmiss_snippet(fields)
        _outcome(result, origin, "rubric-dropped", snippet=snippet)


def _enrich_near_miss(outcome_entry: dict) -> dict:
    """§1.1/§4: fold the internal `outcome` to its human-facing
    `disposition` + one plain-words `reason`, and compute the ONE
    `promotable` rule (F5): true iff a real content snippet exists — a
    populated `{type,…}` dict, never `{scan_refused_rule}`/`{overlength}`/
    absent. Non-near-miss outcomes (`landed`, `resurfaced`,
    `recurrence-from-fire`) pass through unchanged — they gain no
    disposition at all."""
    outcome_name = outcome_entry.get("outcome")
    disposition = (
        _NEARMISS_DISPOSITION.get(outcome_name)
        if isinstance(outcome_name, str)
        else None
    )
    if disposition is None:
        return outcome_entry
    enriched = dict(outcome_entry)
    enriched["disposition"] = disposition
    enriched["reason"] = _NEARMISS_REASON[disposition]
    snippet = outcome_entry.get("snippet")
    enriched["promotable"] = bool(
        disposition in _PROMOTABLE_DISPOSITIONS
        and isinstance(snippet, dict)
        and "type" in snippet
        and "scan_refused_rule" not in snippet
        and "overlength" not in snippet
    )
    return enriched


def _reconcile_and_land(
    home: Path,
    parsed: dict,
    result: MineResult,
    cap: int,
    cwds: dict[str, str] | None = None,
    digested: dict[str, bool] | None = None,
) -> None:
    """``cwds`` maps session id → that session's transcript ``cwd``; a
    project-scoped candidate lands in the bucket for THAT path (doc 13
    §3) — no cwd on file → dropped-invalid, never a guessed bucket.

    ``digested`` (U-cursorhold H-1/H-2) maps session id → that slice's
    halt flag, for EVERY session this run's reader actually saw text
    from. It classifies a cap drop's cursor effect: ``None`` behaves as
    ``{}`` (every cap drop then classifies ``advanced-unmatched``), so
    the function stays callable from a test without it."""
    cwds = cwds or {}
    digested = digested or {}
    origins = existing_origins(home)
    seen_events, violated_fires = _event_seen(home)
    candidates = parsed.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        ref = _valid_ref(cand)
        if ref is None:
            _outcome(result, "(invalid-ref)", "dropped-invalid",
                     reason="bad session/line reference")
            continue
        session_id, line = ref
        origin = f"transcript:{session_id}#L{line}"
        if origin in origins:
            _outcome(result, origin, "skipped-known-origin")
            continue

        quote = str(cand.get("quote") or "")
        if len(quote) > MAX_QUOTE_CHARS:
            quote = ""  # injection-bandwidth cap: evidence rides the ref
            _outcome(result, origin, "quote-dropped-overlength")

        # --- match-claim verification (never trust the model's claim raw)
        match = cand.get("match") or {}
        claimed_id = match.get("record") if isinstance(match, dict) else None
        target = _find_record(home, str(claimed_id)) if claimed_id else None
        if claimed_id and target is None:
            _outcome(
                result, origin, "match-claim-invalid", claimed=str(claimed_id)[:40]
            )
            # demote to no-match; fall through to landing
        resurface_of: str | None = None
        resurface_n = 0
        if target is not None:
            record, sub = target
            if sub == "pending":
                entry = {"session": session_id, "ts": _now_iso(), "origin": origin}
                if quote:
                    if secret_scan(quote):
                        _outcome(result, origin, "fold-quote-scan-refused",
                                 record=record.id)
                    else:
                        entry["quote"] = quote
                record.append_evidence(entry)
                record.set_sightings(record.sightings + 1)  # spec Phase 3
                pending_path = None
                for bucket in discover_buckets(home):
                    p = bucket.path / "pending" / f"{record.id}.md"
                    if p.is_file():
                        pending_path = p
                        break
                if pending_path is not None:
                    record.write(pending_path)
                    result.folded.append(record.id)
                    result.touched.append(pending_path)
                    _outcome(result, origin, "folded", record=record.id)
                    origins.add(origin)
                    continue
            elif record.status == "routed":
                key = ("recurrence-suspect", record.id, origin)
                if key not in seen_events:
                    telemetry.spool_quiet(
                        "recurrence-suspect",
                        record=record.id,
                        origin=origin,
                        basis="miner-match",
                    )
                    seen_events.add(key)
                    result.recurrences.append(record.id)
                    _outcome(result, origin, "recurrence", record=record.id)
                else:
                    _outcome(result, origin, "recurrence-already-known",
                             record=record.id)
                continue
            elif record.status == "rejected":
                n = _rejected_counter_bump(record.id, origin)
                if n < 0 or n < REJECTED_RESURFACE_SIGHTINGS:
                    # FW-34 §1.1 double-absence pin: no `record=` kwarg —
                    # surfacing the rejected id would invite re-promoting
                    # a lesson the human said no to. Counts-only
                    # (`sightings` may stay); the resurfacing counter
                    # above stays the ONLY path a rejected class returns.
                    _outcome(
                        result,
                        origin,
                        "dropped-rejected",
                        sightings=max(n, 0),
                    )
                    continue
                cand = dict(cand)
                cand["why_durable"] = (
                    f"previously rejected as {record.id}; sighted "
                    f"{n}× since — resurfaced per doc 12 §8 Q4. "
                    + str(cand.get("why_durable") or "")
                ).strip()
                # marked landed only AFTER create_record succeeds (audit:
                # marking here + a cap/scan drop killed resurfacing forever)
                resurface_of, resurface_n = record.id, n
            else:
                _outcome(result, origin, "skipped-resolved", record=record.id)
                continue

        # --- landing (cap-checked, scan-gated)
        if len(result.landed) >= cap:
            result.dropped += 1
            # FW-34 §1.2 build-pin: scan BEFORE _outcome — this branch
            # used to fire before _build_record/_scan_candidate ever ran,
            # so cap-refused prose was never scanned at all. The near-miss
            # snippet closes that leak; the candidate is still dropped
            # unconditionally (the cap decision is unaffected by scan
            # outcome — even a scan-refused snippet stays cap-refused).
            snippet_fields = _snippet_fields(cand)
            extra: dict[str, object] = (
                {"snippet": _nearmiss_snippet(snippet_fields)}
                if snippet_fields is not None
                else {}
            )
            # U-cursorhold H-2: classify this drop's cursor effect. A
            # session absent from `digested` was never read by this run's
            # reader — nothing to hold (`advanced-unmatched`). A session
            # present and unhalted holds (`held`, and only then is it
            # added to `result.held_sessions`); a session present and
            # ALREADY halted advances with its halt persisted regardless —
            # M-5 wins, unconditionally (`advanced-halted`, §3.2).
            if session_id not in digested:
                cursor = "advanced-unmatched"
            elif digested[session_id]:
                cursor = "advanced-halted"
            else:
                cursor = "held"
                result.held_sessions.add(session_id)
            extra["cursor"] = cursor
            _outcome(result, origin, "dropped-cap", **extra)
            continue
        try:
            record = _build_record(home, cand)
        except RecordError as exc:
            _outcome(result, origin, "dropped-invalid", reason=str(exc)[:200])
            continue
        except HostsError as exc:
            # 2026-09-28 (fail-state audit finding 14): a hosts.yaml that
            # does not load made a skill-scoped candidate's check raise out
            # of the whole pass. Only this candidate is held: its session's
            # cursor is held exactly as the cap drop above holds it, so the
            # session is read again once hosts.yaml loads; every other
            # candidate goes on. Named by the error's type, never its text.
            if session_id not in digested:
                cursor = "advanced-unmatched"
            elif digested[session_id]:
                cursor = "advanced-halted"
            else:
                cursor = "held"
                result.held_sessions.add(session_id)
            _outcome(
                result, origin, "dropped-invalid", cursor=cursor,
                reason=f"hosts.yaml does not load ({type(exc).__name__}); "
                "the skill scope could not be checked",
            )
            log(f"run: candidate {origin} held — hosts.yaml does not load ({type(exc).__name__})")
            continue
        hits = _scan_candidate(record, cand, quote)
        if hits:
            _outcome(result, origin, "scan-refused", rule=hits[0].rule)
            log(f"run: candidate {origin} refused by secret scan ({hits[0].rule})")
            continue
        project_path = None
        if record.scope == "project":
            cwd = cwds.get(session_id)
            if not cwd:
                _outcome(
                    result,
                    origin,
                    "dropped-invalid",
                    reason="no cwd for project scope",
                )
                continue
            project_path = capture_host_path(home, Path(cwd))  # FW-162
        entry = {"session": session_id, "ts": _now_iso(), "origin": origin}
        if quote:
            entry["quote"] = quote
        record.append_evidence(entry)
        try:
            path = create_record(home, record, project_path=project_path)
        except LedgerOpsError as exc:
            _outcome(result, origin, "dropped-land-failed", reason=str(exc)[:200])
            continue
        result.touched.append(path)
        meta = path.parent.parent / "meta.yaml"
        if meta.is_file():
            result.touched.append(meta)
        if resurface_of is not None:
            _rejected_mark_landed(resurface_of)
            _outcome(result, origin, "resurfaced", record=resurface_of,
                     sightings=resurface_n)
        origins.add(origin)
        result.landed.append(record.id)
        _outcome(
            result,
            origin,
            "landed",
            record=record.id,
            confidence=str(cand.get("confidence") or "unstated"),
            why=str(cand.get("why_durable") or "")[:300],
        )
        telemetry.spool_quiet(
            "capture", source="session", scope=record.scope, record=record.id
        )
        log(f"run: landed {record.id} → {path}")

    # FW-34 §1.3: the one reader-output extension — near-misses the
    # rubric judged below the durability bar. Never affects landing.
    _handle_near_misses(result, parsed)

    fires = parsed.get("fires") or []
    if isinstance(fires, list):
        for fire in fires:
            if not isinstance(fire, dict):
                continue
            rid = str(fire.get("record") or "")
            outcome = str(fire.get("outcome") or "")
            ref = _valid_ref(fire)
            if (
                ref is None
                or not RECORD_ID_RE.match(rid)
                or outcome not in (
                    "suspected-compliance", "suspected-violation", "cannot-tell",
                )
            ):
                continue
            found = _find_record(home, rid)
            if found is None or found[0].status != "routed":
                continue  # fires only against live routed rules
            origin = f"transcript:{ref[0]}#L{ref[1]}"
            key = ("fire", rid, origin)
            if key in seen_events:
                continue
            telemetry.spool_quiet(
                "fire", record=rid, origin=origin, outcome=outcome
            )
            seen_events.add(key)
            result.fires += 1
            # *Amended 2026-09-13 (steward build, U6):* THE CROSSOVER that
            # used to sit here — an immediate `_raise_recurrence_suspect`
            # call when `outcome == "violated"` — is removed. A
            # `suspected-violation` fire is spooled above and nothing
            # else: the steward reads it as evidence against the
            # transcript line and decides recurrence itself (11 §4.3,
            # `12-transcript-miner.md` §7 M-1, mining-rubric.md "Fire
            # observations"). This loop no longer calls
            # `_raise_recurrence_suspect` at all.

    # THE BACKFILL (U-recur spec §2.2, scope narrowed 2026-09-13 steward
    # build U6): a one-way migration net, not a live decision path. It
    # exists only because rows already sitting in the tracked plane with
    # the pre-U6 raw `outcome: "violated"` predate both the vocabulary
    # change and the acceptance check that now refuses that value from
    # the model — those rows were captured back when the (now-removed)
    # crossover was the live mechanism meant to promote them, and this
    # is the only remaining path that finishes that promotion. It can
    # never fire for anything reported under the new vocabulary:
    # `violated_fires` (`_event_seen`, read with `map_legacy_outcome=
    # False`) only ever contains rows whose RAW on-disk outcome is the
    # literal string `"violated"`, which nothing written after this
    # build can produce. This mirrors the old crossover's `routed` guard
    # EXACTLY, including its `found is None` half (AC7): an unbounded
    # pass over an append-only telemetry plane must never raise on one
    # unresolvable row — run()'s outer handler would turn that into
    # `status: failed` and the offending row would never go away,
    # wedging every future nightly run.
    for rid, origin in violated_fires:
        found = _find_record(home, rid)
        if found is None or found[0].status != "routed":
            continue
        _raise_recurrence_suspect(result, seen_events, rid, origin, _FIRE_VIOLATED_BASIS)


# ------------------------------------- the session engine's landing (R2)
#
# New-miner plan §3.6. The checked output of the session engine
# (`miner-output/1`, every pointer a full ref, every quote checked) lands
# here, rule for rule as `_reconcile_and_land` lands the reader's
# candidates: a lesson becomes a pending record, a sighting folds into a
# pending record or spools a recurrence-suspect against a routed one, a
# rule check spools a `fire`. It lands from waiting answers
# (`mining.waiting`, fix round 4): `_drain_waiting` runs inside the run's
# `intents.ledger_write` block, so every write below is under the lock.

#: The ``basis`` of a recurrence-suspect the session engine spools for a
#: sighting of a routed record: the reader's own label (`_reconcile_and_land`).
_SIGHTING_BASIS = "miner-match"


def _ref_origin(ref: dict) -> str:
    """The legacy origin string of a checked ref: ``transcript:<session>#L<n>``,
    and for a line of a subagent's log ``transcript:<session>/subagents/
    agent-<id>.jsonl#L<n>`` (its line numbers are that file's)."""
    sub = ref.get("subagent_file")
    where = f"{ref['session']}/{sub}" if sub else str(ref["session"])
    return f"transcript:{where}#L{ref['line']}"


def _ref_moment(ref: dict) -> tuple:
    """One transcript moment: the entry's uuid (a fork copies it), else its
    place."""
    uid = ref.get("uuid")
    if isinstance(uid, str) and uid:
        return ("uuid", uid)
    return ("at", ref.get("session"), ref.get("subagent_file"), ref.get("line"))


def _evidence_entry(item: dict, *, why: str | None = None) -> dict:
    """A checked evidence item as a record's evidence entry (plan §3.6):
    ``{ref, quote?, session, ts, origin}``, ``ts`` the entry's own time. A
    quote the checker withheld (it held a redaction placeholder) is not
    stored, so the steward reads ``no_quote``, never a false ``not_found``."""
    ref = dict(item["ref"])
    entry: dict = {"ref": ref, "session": ref["session"], "origin": _ref_origin(ref)}
    if ref.get("entry_ts"):
        entry["ts"] = ref["entry_ts"]
    quote = item.get("quote")
    if isinstance(quote, str) and quote and not check_mod.quote_withheld(quote):
        entry["quote"] = quote
    if why is not None:
        entry["why"] = why
    return entry


def _step_line(step: dict) -> str:
    """One ``## Episode brief`` line: ``L<line> (<role>, T<turn>): <what>``;
    a step in a subagent's log names it (``agent-<id> L<line>``)."""
    ref = step["ref"]
    sub = ref.get("subagent_file")
    where = f"{Path(sub).stem} L{ref['line']}" if sub else f"L{ref['line']}"
    turn = step.get("turn")
    who = f"{ref['role']}, T{turn}" if turn is not None else str(ref["role"])
    return f"{where} ({who}): {' '.join(str(step['what']).split())}"


def _capped_brief(lines: list[str]) -> str:
    """The ``## Episode brief`` of a session lesson, at most
    :data:`MAX_EPISODE_BRIEF_CHARS` (the digest engine's ceiling): whole
    step lines in order, and a last line saying how many were left out."""
    whole = "\n".join(lines)
    if len(whole) <= MAX_EPISODE_BRIEF_CHARS:
        return whole

    def marker(n: int) -> str:
        return f"… {n} more step(s) left out at {MAX_EPISODE_BRIEF_CHARS:,} characters"

    room = MAX_EPISODE_BRIEF_CHARS - len(marker(len(lines))) - 1
    kept: list[str] = []
    for line in lines:
        if len("\n".join([*kept, line])) > room:
            break
        kept.append(line)
    return "\n".join([*kept, marker(len(lines) - len(kept))])


def _session_record(home: Path, lesson: dict) -> Record:
    """A pending record from a checked lesson (plan §3.6): its loaded text
    and ``## Context``, the steps as ``## Episode brief``, ``verified`` with
    ``verified_how``, ``incident_cost``, ``generality``. Raises RecordError
    for a scope or field the ledger refuses (the caller drops it)."""
    scope = str(lesson["scope"])
    if scope.startswith("skill:") and not _valid_skill_scope(home, scope):
        raise RecordError(f"unknown skill bucket for scope {scope!r}")
    if lesson["type"] == "behavior":
        record = Record.create(
            type="behavior", scope=scope, source="session", kind=lesson["kind"],
            trigger=str(lesson["trigger"]).strip(), instruction=str(lesson["instruction"]).strip(),
            context=(str(lesson["context"]).strip() or None) if lesson.get("context") else None,
        )
    else:
        record = Record.create(
            type="knowledge", scope=scope, source="session", fact=str(lesson["fact"]).strip(),
            context=(str(lesson["context"]).strip() or None) if lesson.get("context") else None,
        )
    if lesson["steps"]:
        brief = _capped_brief([_step_line(s) for s in lesson["steps"]])
        record.set_body(record.body.rstrip("\n") + "\n\n## Episode brief\n" + brief + "\n")
    verification = lesson.get("verification")
    if verification:
        record.set_verified(True, how=str(verification["how"]))
    cost = lesson.get("incident_cost")
    if cost:
        record.set_incident_cost(str(cost["text"]))
    if lesson.get("generality") in GENERALITIES:
        record.set_generality(lesson["generality"])
    return record


def _lesson_entries(lesson: dict) -> list[dict]:
    """The record's evidence: each evidence item, then the verification's
    and the incident cost's pointers (``why: verification`` /
    ``why: incident-cost``)."""
    entries = [_evidence_entry(item) for item in lesson["evidence"]]
    if lesson.get("verification"):
        entries.append(_evidence_entry(lesson["verification"], why="verification"))
    if lesson.get("incident_cost"):
        entries.append(_evidence_entry(lesson["incident_cost"], why="incident-cost"))
    return entries


@dataclass
class _Landing:
    """One drain's run-local state. ``origins`` suppress a new lesson at a
    known origin (every record's evidence, and what this run landed);
    ``seen_events`` are the fire and recurrence-suspect keys already
    tracked or still spooled; ``moments`` the ``(kind, record or "lesson",
    moment)`` keys this run has already landed, so a parent and its fork
    land one moment once."""

    home: Path
    result: MineResult
    cap: int
    origins: set[str]
    seen_events: set[tuple[str, str, str]]
    moments: set[tuple] = field(default_factory=set)
    #: records what an item is about to write before it writes (the
    #: drain sets it per item; None outside a drain)
    intend: Callable[[dict], None] | None = None
    #: the ledger files a replay found its output already in (the drain
    #: reads and clears it per item): its terminal mark waits until they
    #: are committed, like a file this run wrote (fix round 6)
    acknowledged: list[Path] = field(default_factory=list)


class _LandingHeld(Exception):
    """An item that cannot land on this run for a reason outside the item
    (``hosts.yaml`` does not load): it stays waiting, as a failed write
    does. The message is ours, never a file's text."""


#: What landing one item did: it landed (a record, a fold, a spooled
#: event), it was dropped on purpose (a duplicate, a stale target, a scan
#: refusal, ...), or the run's lesson cap held it (it stays waiting and
#: lands first next run). A write that fails raises instead.
LANDED, DROPPED, CAPPED = "landed", "dropped", "capped"


def _intend(st: _Landing, output: str, record: str | None, origin: str, **extra: object) -> None:
    """Record, on the item being landed, what this attempt is about to
    write (fix round 5): its output, target record and origin, and mark
    the item ``writing`` in one atomic rewrite of its waiting answer --
    before the write. A replay of a ``writing`` item finishes that output
    and never decides again (:func:`_finish_intent`)."""
    if st.intend is not None:
        st.intend({"output": output, "record": record, "origin": origin, **extra})


def _land_lesson(st: _Landing, lesson: dict, cwd: str | None) -> str:
    """Land one checked lesson as a pending record: :data:`LANDED`,
    :data:`DROPPED` or :data:`CAPPED`. A write that fails raises (the item
    stays waiting)."""
    result = st.result
    ev = lesson["evidence"]
    main = [e for e in ev if not e["ref"].get("subagent_file")]
    origin = _ref_origin((main or ev)[0]["ref"])
    if origin in st.origins:
        _outcome(result, origin, "skipped-known-origin", reason="a record already holds this origin")
        return DROPPED
    # a parent and its fork can both report one moment: one lesson lands
    cited = {("lesson", _ref_moment(e["ref"])) for e in ev}
    if cited and cited <= st.moments:
        _outcome(result, origin, "skipped-duplicate-moment", reason="this run already landed a lesson there")
        return DROPPED
    if len(result.landed) >= st.cap:
        # the cap counts every landing of the run, drained ones included;
        # the lesson stays waiting and lands first next run
        _outcome(result, origin, "waiting-cap", reason=f"the run's lesson cap ({st.cap}) was reached")
        return CAPPED
    return _write_lesson(st, lesson, cwd)


def _write_lesson(st: _Landing, lesson: dict, cwd: str | None, *, output: str = "lesson",
                  target: str | None = None, extra: dict | None = None) -> str:
    """The write half of a lesson's landing: the record, its scan and
    scope checks (each a property of the lesson itself), then the intent
    and ``create_record``. ``output``/``target``: ``resurface`` and the
    rejected record it resurfaces."""
    home, result = st.home, st.result
    ev = lesson["evidence"]
    main = [e for e in ev if not e["ref"].get("subagent_file")]
    primary = (main or ev)[0]
    origin = _ref_origin(primary["ref"])
    cited = {("lesson", _ref_moment(e["ref"])) for e in ev}
    try:
        record = _session_record(home, lesson)
    except RecordError as exc:
        _outcome(result, origin, "dropped-invalid", reason=str(exc)[:200])
        return DROPPED
    except HostsError as exc:
        # as `_reconcile_and_land`: named by the error's type, never its text
        raise _LandingHeld(
            f"hosts.yaml does not load ({type(exc).__name__}); the skill scope could not be checked"
        ) from None
    entries = _lesson_entries(lesson)
    texts = [record.body, str(lesson.get("why_durable") or "")]
    texts += [str(e["quote"]) for e in entries if e.get("quote")]
    if lesson.get("verification"):
        texts.append(str(lesson["verification"]["how"]))
    if lesson.get("incident_cost"):
        texts.append(str(lesson["incident_cost"]["text"]))
    hits = [h for t in texts if t for h in secret_scan(t)]
    if hits:
        _outcome(result, origin, "scan-refused", rule=hits[0].rule)
        log(f"run: lesson {origin} refused by secret scan ({hits[0].rule})")
        return DROPPED
    project_path = None
    if record.scope == "project":
        where = primary["ref"].get("cwd") or cwd
        if not where:
            _outcome(result, origin, "dropped-invalid", reason="no cwd for project scope")
            return DROPPED
        project_path = capture_host_path(home, Path(where))  # FW-162
    for entry in entries:
        record.append_evidence(entry)
    _intend(st, output, target, origin, **(extra or {}))
    path = create_record(home, record, project_path=project_path)  # LedgerOpsError: the item waits
    result.touched.append(path)
    meta = path.parent.parent / "meta.yaml"
    if meta.is_file():
        result.touched.append(meta)
    st.origins.update(e["origin"] for e in entries)
    st.moments.update(cited)
    result.landed.append(record.id)
    _outcome(result, origin, "landed", record=record.id, shape=lesson["shape"],
             why=str(lesson.get("why_durable") or "")[:300])
    telemetry.spool_quiet("capture", source="session", scope=record.scope, record=record.id)
    log(f"run: landed {record.id} → {path}")
    return LANDED


def _find_record_path(home: Path, rid: str) -> tuple[Record, Path] | None:
    """:func:`_find_record`, with the file it was read from."""
    if not rid or not RECORD_ID_RE.match(rid):
        return None
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            path = bucket.path / sub / f"{rid}.md"
            if path.is_file():
                try:
                    return Record.from_path(path), path
                except (RecordError, UnicodeDecodeError):
                    return None
    return None


def _live_record(home: Path, rid: str) -> tuple[Record, Path] | None:
    """The record ``rid`` names, ``superseded_by`` followed to its live
    successor (S-85); None for a missing record, a missing successor or a
    cycle."""
    seen: set[str] = set()
    while rid not in seen:
        seen.add(rid)
        found = _find_record_path(home, rid)
        if found is None:
            return None
        successor = found[0].superseded_by
        if not successor:
            return found
        rid = successor
    return None


def _resurfaced_lesson(rejected: Record, items: list[dict], n: int) -> dict:
    """Doc 12 §8 Q4: the lesson a rejected record resurfaces as -- its own
    text, the sighting's evidence."""
    from .index.store import _sections  # pyright: ignore[reportPrivateUsage]

    sections = _sections(rejected.body)
    return {
        "scope": rejected.scope, "type": rejected.type, "kind": rejected.kind,
        "trigger": sections.get("Trigger"), "instruction": sections.get("Instruction"),
        "fact": sections.get("Fact"), "context": sections.get("Context"),
        "steps": [], "verification": None, "incident_cost": None, "generality": None,
        "evidence": items, "shape": "repeated-friction",
        "why_durable": f"previously rejected as {rejected.id}; sighted {n}× since — resurfaced per doc 12 §8 Q4",
    }


def _origin_holders(home: Path, origin: str) -> list[tuple[Record, Path]]:
    """The records whose evidence holds ``origin``, with their files: the
    record a replay or a known-origin check finds an output already in."""
    out: list[tuple[Record, Path]] = []
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            directory = bucket.path / sub
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                try:
                    record = Record.from_path(path)
                except (RecordError, UnicodeDecodeError):
                    continue
                if any(isinstance(e, dict) and e.get("origin") == origin for e in record.evidence):
                    out.append((record, path))
    return out


def _is_resurface_of(record: Record, rejected: Record) -> bool:
    """``record`` is ``rejected``'s own resurfaced copy (:func:`_resurfaced_lesson`):
    another session record of the same type and scope carrying the
    rejected record's own loaded text."""
    from .index.store import _sections  # pyright: ignore[reportPrivateUsage]

    if record.id == rejected.id or record.source != "session":
        return False
    if record.type != rejected.type or record.scope != rejected.scope:
        return False
    mine, theirs = _sections(record.body), _sections(rejected.body)
    return all(mine.get(k) == theirs.get(k) for k in ("Trigger", "Instruction", "Fact"))


def _own_resurface_paths(home: Path, rejected: Record, origin: str) -> list[Path]:
    """The files of the records holding ``origin`` that are ``rejected``'s
    own resurfaced copy; empty when another record holds it (fix round 6)."""
    return [path for record, path in _origin_holders(home, origin) if _is_resurface_of(record, rejected)]


def _resurface(st: _Landing, rejected: Record, items: list[dict], n: int, cwd: str | None) -> str:
    """Doc 12 §8 Q4 for a sighting: a rejected lesson sighted
    :data:`REJECTED_RESURFACE_SIGHTINGS` times since is landed again as a
    new pending record, and the rejected record is marked resurfaced."""
    lesson = _resurfaced_lesson(rejected, items, n)
    origin = _ref_origin(items[0]["ref"])
    if origin in st.origins:
        # the rejected record is marked only when the record holding the
        # origin is its own resurfaced copy (a mark lost after the copy
        # landed); another record at this moment -- a lesson from the same
        # answer -- leaves it unmarked, so a later sighting resurfaces it
        # (fix round 6)
        if _own_resurface_paths(st.home, rejected, origin):
            _rejected_mark_landed(rejected.id)
        _outcome(st.result, origin, "skipped-known-origin", reason="a record already holds this origin")
        return DROPPED
    cited = {("lesson", _ref_moment(e["ref"])) for e in items}
    if cited and cited <= st.moments:
        _outcome(st.result, origin, "skipped-duplicate-moment", reason="this run already landed a lesson there")
        return DROPPED
    if len(st.result.landed) >= st.cap:
        _outcome(st.result, origin, "waiting-cap", reason=f"the run's lesson cap ({st.cap}) was reached")
        return CAPPED
    landed = _write_lesson(st, lesson, cwd, output="resurface", target=rejected.id, extra={"sightings": n})
    if landed != LANDED:
        return landed
    _rejected_mark_landed(rejected.id)
    _outcome(st.result, origin, "resurfaced", record=rejected.id, sightings=n)
    return LANDED


def _record_moments(record: Record) -> tuple[set[tuple], set[str]]:
    """The transcript moments and origins ``record``'s evidence already
    holds: a sighting replayed after a crash, or reported by a fork, is
    found here, per record."""
    moments: set[tuple] = set()
    origins: set[str] = set()
    for entry in record.evidence:
        ref = entry.get("ref")
        if isinstance(ref, dict) and (ref.get("uuid") or ref.get("session")):
            moments.add(_ref_moment(ref))
        if isinstance(entry.get("origin"), str):
            origins.add(entry["origin"])
    return moments, origins


def _spool_output(kind: str, **payload) -> None:
    """A fire or recurrence-suspect is the miner's output, not usage
    telemetry: a spool that fails raises (the item stays waiting and is
    landed again next run), where `telemetry.spool_quiet` would only warn.
    The spool file, and its folder, are fsynced before this returns, so
    the event is durable before its item is marked (fix round 5)."""
    path = telemetry.spool_event(kind, **payload)
    mining_waiting.fsync_file_and_folder(path)


def _sync_spool() -> None:
    """Fsync every spool file, then the spool folder: what a replay found
    already spooled is durable before its item is marked (fix round 6)."""
    files = sorted(telemetry.spool_dir().glob("*.jsonl"))
    for path in files:
        mining_waiting.fsync_file_and_folder(path)


def _write_fold(st: _Landing, record: Record, path: Path, fresh: list[dict], origin: str) -> str:
    """Fold ``fresh`` evidence into ``record``: the intent, then one write."""
    result = st.result
    for item in fresh:
        entry = _evidence_entry(item)
        if entry.get("quote") and secret_scan(entry["quote"]):
            del entry["quote"]
            _outcome(result, entry["origin"], "fold-quote-scan-refused", record=record.id)
        record.append_evidence(entry)
    record.set_sightings(record.sightings + 1)
    _intend(st, "fold", record.id, origin)
    record.write(path)
    st.origins.update(_ref_origin(e["ref"]) for e in fresh)
    result.folded.append(record.id)
    result.touched.append(path)
    _outcome(result, origin, "folded", record=record.id)
    return LANDED


def _write_event(st: _Landing, kind: str, rid: str, origin: str, **payload: object) -> None:
    """Spool a recurrence-suspect or a fire: the intent, then the spool."""
    _intend(st, kind, rid, origin)
    _spool_output(kind, record=rid, origin=origin, **payload)
    st.seen_events.add((kind, rid, origin))


def _land_sighting(st: _Landing, sighting: dict, cwd: str | None) -> str:
    """Land one checked sighting: :data:`LANDED` when it folded, spooled or
    resurfaced. Replay is keyed by (record, moment): the target record's
    own evidence, and what this run already landed for that record -- a
    sighting of one record never suppresses a sighting of another. A
    sighting whose record is gone, or is no longer pending, routed or
    rejected, is dropped with the reason."""
    home, result = st.home, st.result
    found = _live_record(home, str(sighting["record"]))
    first = _ref_origin(sighting["evidence"][0]["ref"])
    if found is None:
        _outcome(result, first, "dropped-invalid", reason="the sighted record has no live record in the ledger")
        return DROPPED
    record, path = found
    # a fork and its parent can both report one moment: it lands once per run
    items = [e for e in sighting["evidence"] if ("sighting", record.id, _ref_moment(e["ref"])) not in st.moments]
    if not items:
        _outcome(result, first, "skipped-duplicate-moment", record=record.id,
                 reason="this run already landed a sighting of this record there")
        return DROPPED
    st.moments.update(("sighting", record.id, _ref_moment(e["ref"])) for e in items)
    origin = _ref_origin(items[0]["ref"])
    if record.status == "pending":
        held_moments, held_origins = _record_moments(record)
        fresh = [e for e in items
                 if _ref_moment(e["ref"]) not in held_moments and _ref_origin(e["ref"]) not in held_origins]
        if not fresh:
            _outcome(result, origin, "skipped-known-origin", record=record.id,
                     reason="the record already holds this moment")
            return DROPPED
        return _write_fold(st, record, path, fresh, _ref_origin(fresh[0]["ref"]))
    if record.status == "routed":
        if ("recurrence-suspect", record.id, origin) in st.seen_events:
            _outcome(result, origin, "recurrence-already-known", record=record.id,
                     reason="this recurrence-suspect is already spooled or tracked")
            return DROPPED
        _write_event(st, "recurrence-suspect", record.id, origin, basis=_SIGHTING_BASIS)
        result.recurrences.append(record.id)
        _outcome(result, origin, "recurrence", record=record.id)
        return LANDED
    if record.status == "rejected":
        n = _rejected_counter_bump(record.id, origin)
        if n < 0 or n < REJECTED_RESURFACE_SIGHTINGS:
            # FW-34 §1.1: counts only, never the rejected record's id
            _outcome(result, origin, "dropped-rejected", sightings=max(n, 0))
            return DROPPED
        return _resurface(st, record, items, n, cwd)
    _outcome(result, origin, "skipped-resolved", record=record.id, reason=f"the sighted record is {record.status}")
    return DROPPED


def _land_rule_check(st: _Landing, check: dict) -> str:
    """A rule check spools a ``fire`` against a routed record only, once per
    ``(record, origin)`` (as `_reconcile_and_land`; spooled-not-flushed
    counts), and once per moment in a run: :data:`LANDED` when it spooled.
    ``action`` is the origin of the agent's action, when the model gave one
    (telemetry takes any scalar payload key)."""
    home, result = st.home, st.result
    rid = str(check["record"])
    situation = check["situation"]["ref"]
    origin = _ref_origin(situation)
    found = _find_record(home, rid)
    if found is None or found[0].status != "routed":
        _outcome(result, origin, "fire-skipped", record=rid,
                 reason="the record is gone" if found is None else f"the record is {found[0].status}, not routed")
        return DROPPED
    moment = ("fire", rid, _ref_moment(situation))
    if moment in st.moments:
        _outcome(result, origin, "skipped-duplicate-moment", record=rid,
                 reason="this run already spooled a fire of this record there")
        return DROPPED
    if ("fire", rid, origin) in st.seen_events:
        st.moments.add(moment)
        _outcome(result, origin, "fire-already-known", record=rid, reason="this fire is already spooled or tracked")
        return DROPPED
    _write_event(st, "fire", rid, origin, **_fire_payload(check))
    st.moments.add(moment)
    result.fires += 1
    _outcome(result, origin, "fire-spooled", record=rid, check=check["outcome"])
    return LANDED


def _fire_payload(check: dict) -> dict:
    action = check.get("action")
    return {"outcome": check["outcome"], "action": _ref_origin(action["ref"]) if action else None}


def _finish_intent(st: _Landing, intent: dict, kind: str, item: dict, cwd: str | None) -> str:
    """Finish an item a stop left ``writing`` (fix round 5): the output its
    intent recorded, against the target it recorded -- never decided
    again from that target's current status or successor. The output
    already exists (the record's evidence holds every moment of a fold,
    the spooled or tracked events hold a fire or recurrence-suspect, the
    known origin a lesson): :data:`LANDED`, and the files it was found in
    are ``acknowledged`` (their commit gates the mark). It does not: the
    same output is written, unless the recorded target is gone
    (:data:`DROPPED`, with the reason), or, for a new lesson or
    resurface, this run's lesson cap is reached (:data:`CAPPED`; it stays
    ``writing`` and lands on a later run, fix round 6)."""
    home, result = st.home, st.result
    output, rid, origin = intent["output"], intent.get("record"), intent["origin"]
    reason_done = "it was written before a stop that came before its mark"
    if output == "lesson":
        if origin in st.origins:
            st.acknowledged.extend(path for _r, path in _origin_holders(home, origin))
            _outcome(result, origin, "already-written", reason=reason_done)
            return LANDED
        if len(result.landed) >= st.cap:
            _outcome(result, origin, "waiting-cap", reason=f"the run's lesson cap ({st.cap}) was reached")
            return CAPPED
        return _write_lesson(st, item, cwd)
    found = _find_record_path(home, str(rid))
    if output == "resurface":
        if found is None:
            _outcome(result, origin, "dropped-invalid", record=rid,
                     reason="the rejected record it resurfaces is gone")
            return DROPPED
        rejected = found[0]
        if origin in st.origins:
            own = _own_resurface_paths(home, rejected, origin)
            if not own:
                _outcome(result, origin, "skipped-known-origin", record=rid,
                         reason="another record already holds this origin")
                return DROPPED
            _rejected_mark_landed(rejected.id)
            st.acknowledged.extend(own)
            _outcome(result, origin, "already-written", record=rid, reason=reason_done)
            return LANDED
        if len(result.landed) >= st.cap:
            _outcome(result, origin, "waiting-cap", reason=f"the run's lesson cap ({st.cap}) was reached")
            return CAPPED
        recorded = intent.get("sightings")
        n = recorded if isinstance(recorded, int) else REJECTED_RESURFACE_SIGHTINGS
        landed = _write_lesson(st, _resurfaced_lesson(rejected, item["evidence"], n), cwd,
                               output="resurface", target=rejected.id, extra={"sightings": n})
        if landed == LANDED:
            _rejected_mark_landed(rejected.id)
            _outcome(result, origin, "resurfaced", record=rejected.id, sightings=n)
        return landed
    if output == "fold":
        if found is None:
            _outcome(result, origin, "dropped-invalid", record=rid, reason="the record it folds into is gone")
            return DROPPED
        record, path = found
        held_moments, held_origins = _record_moments(record)
        # already written only when every one of its moments is there: one
        # matching origin is not the whole fold (fix round 6)
        fresh = [e for e in item["evidence"]
                 if _ref_moment(e["ref"]) not in held_moments and _ref_origin(e["ref"]) not in held_origins]
        if not fresh:
            st.acknowledged.append(path)
            _outcome(result, origin, "already-written", record=rid, reason=reason_done)
            return LANDED
        return _write_fold(st, record, path, fresh, origin)
    # a recurrence-suspect or a fire
    if (output, rid, origin) in st.seen_events:
        if (output, rid, origin) in _spooled_seen():
            # a readable append is not a durable one (its own fsync may
            # have failed): sync the spool before the mark (fix round 6)
            _sync_spool()
        _outcome(result, origin, "already-written", record=rid, reason=reason_done)
        return LANDED
    if found is None:
        _outcome(result, origin, "dropped-invalid", record=rid, reason=f"the record its {output} names is gone")
        return DROPPED
    if output == "fire":
        _write_event(st, "fire", str(rid), origin, **_fire_payload(item))
        result.fires += 1
        _outcome(result, origin, "fire-spooled", record=rid, check=item["outcome"])
    else:
        _write_event(st, "recurrence-suspect", str(rid), origin, basis=_SIGHTING_BASIS)
        result.recurrences.append(str(rid))
        _outcome(result, origin, "recurrence", record=rid)
    return LANDED


def _spooled_seen() -> set[tuple[str, str, str]]:
    """(kind, record, origin) of the fire and recurrence-suspect events
    still in the spool: written by a run that stopped before its flush.
    Replay dedupes against these as well as the tracked plane."""
    return {
        (str(e.get("kind")), str(e.get("record")), str(e.get("origin")))
        for e in telemetry.read_spooled(("fire", "recurrence-suspect"))
    }


@dataclass
class DrainReport:
    """What one run did with the waiting answers (``run.json``'s
    ``waiting``): the answers it found from earlier runs; items landed from
    earlier runs' answers and from this run's; items still waiting after
    it; the stuck ones; the files that do not read (``unreadable``); and
    whether it took the ledger lock to land them (``drained``, set the
    moment the lock is acquired). ``gate_held``: the flood gate kept it
    from landing any. ``terminal``: the items this run landed or dropped,
    whose mark waits for the landing commit (fix round 6), each with the
    ledger files it wrote or found its output in."""

    found: int = 0
    landed_earlier: int = 0
    landed_this_run: int = 0
    still_waiting: int = 0
    stuck: list[dict] = field(default_factory=list)
    drained: bool = False
    unreadable: list[str] = field(default_factory=list)
    gate_held: bool = False
    terminal: list = field(default_factory=list, repr=False)

    def as_dict(self) -> dict:
        return {"found": self.found, "landed_earlier": self.landed_earlier,
                "landed_this_run": self.landed_this_run, "still_waiting": self.still_waiting,
                "stuck": self.stuck, "drained": self.drained, "unreadable": list(self.unreadable)}


def _drain_waiting(
    home: Path, answers: list[mining_waiting.Answer], result: MineResult, cap: int, run_id: str
) -> DrainReport:
    """Land the waiting answers, oldest first, one item at a time. **The
    caller holds the ledger lock** (`intents.ledger_write`). Before an
    item's write, what it is about to write is recorded on it (state
    ``writing``, one atomic rewrite); a ``writing`` item left by a stop is
    finished, not decided again (:func:`_finish_intent`). An item that
    landed or was dropped gets that terminal mark only after a landing
    commit that succeeded (:func:`_finish_drain`, fix round 6). A write
    that fails, or an item held for a reason outside it, leaves the item
    unfinished with its failure counted (the model is never asked again);
    the cap holds an item without counting."""
    seen_events, _legacy = _event_seen(home)
    st = _Landing(home=home, result=result, cap=cap, origins=existing_origins(home),
                  seen_events=seen_events | _spooled_seen())
    report = DrainReport(drained=True)
    for answer in answers:
        earlier = answer.run_id != run_id
        for entry in answer.waiting():
            item = answer.item(entry)
            origin = mining_waiting.item_origin(item, entry["kind"])
            mark = len(result.outcomes)
            touched = len(result.touched)
            st.acknowledged = []

            def intend(intent: dict, entry: dict = entry, answer: mining_waiting.Answer = answer) -> None:
                entry["intent"] = intent
                entry["state"] = "writing"
                answer.mark()

            st.intend = intend
            try:
                # direct calls, never a table: the lock walker follows calls
                if entry["state"] == "writing":
                    state = _finish_intent(st, entry["intent"], entry["kind"], item, answer.cwd)
                elif entry["kind"] == "lessons":
                    state = _land_lesson(st, item, answer.cwd)
                elif entry["kind"] == "sightings":
                    state = _land_sighting(st, item, answer.cwd)
                else:
                    state = _land_rule_check(st, item)
            except Exception as exc:  # noqa: BLE001 -- one item's failed write leaves it unfinished, no more
                error = str(exc) if isinstance(exc, _LandingHeld) else f"{type(exc).__name__}: {exc}"
                entry["failures"] += 1
                entry["error"] = error[:200]
                _outcome(result, origin, "land-failed", reason=error[:200], failures=entry["failures"])
                log(f"run: an item of {answer.session} did not land ({type(exc).__name__}); it stays waiting")
                state = None
            finally:
                st.intend = None
            if earlier:
                for o in result.outcomes[mark:]:
                    o["waited_from"] = answer.run_id
            last = result.outcomes[-1] if len(result.outcomes) > mark else {}
            if state in (LANDED, DROPPED):
                # the terminal mark waits for a landing commit that
                # succeeded; until then the item keeps its state
                paths = [*result.touched[touched:], *st.acknowledged]
                report.terminal.append((answer, entry, state, last, paths))
                if state == LANDED:
                    if earlier:
                        report.landed_earlier += 1
                    else:
                        report.landed_this_run += 1
                continue
            try:
                answer.mark()
            except OSError as exc:
                # the item's state is lost with the file's rewrite: a later
                # run lands it again, and its own deduplication catches it
                log(f"run: the state of a waiting answer of {answer.session} was not saved ({exc})")
    return report


def _finish_drain(home: Path, answers: list[mining_waiting.Answer], report: DrainReport, *,
                  committed: bool) -> None:
    """After the landing commit: give each landed or dropped item its
    terminal mark, then remove each answer whose items have all landed or
    been dropped and whose ``learn`` set has reached the store (fix round
    5: until then the file is kept, so the next run can teach the store
    from it). A terminal mark needs a landing commit that succeeded
    (``committed``) and every ledger file the item wrote or found its
    output in committed (fix round 6): otherwise the item keeps its state
    (a written one stays ``writing``), the file stays, and the next run's
    replay finds the output and marks it."""
    marked: dict[int, mining_waiting.Answer] = {}
    for answer, entry, state, last, paths in report.terminal:
        if not committed or any(gitops.paths_dirty(home, p) for p in paths):
            continue
        entry["state"] = "landed" if state == LANDED else "dropped"
        if last.get("outcome"):
            entry["outcome"] = last["outcome"]
        if state == DROPPED and last.get("reason"):
            entry["reason"] = str(last["reason"])[:200]
        marked[id(answer)] = answer
    for answer in marked.values():
        try:
            answer.mark()
        except OSError as exc:
            log(f"run: the state of a waiting answer of {answer.session} was not saved ({exc})")
    for answer in answers:
        if answer.done() and answer.learned:
            try:
                answer.remove()
            except OSError as exc:
                log(f"run: a finished waiting answer of {answer.session} was not removed ({exc})")


# ------------------------------------------------------------ the journal


def _journal(entry: dict) -> None:
    path = journal_path()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
    worker._truncate_oldest(path, JOURNAL_CAP_BYTES)


def read_journal(limit: int = 20) -> list[dict]:
    try:
        lines = journal_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


# --------------------------------------------------- FW-34 §3: canaries


class CanaryError(Exception):
    """``canary plant`` refusal (the DP-2 guard) — nothing written."""


#: Case-insensitive: refuses "DP-2", "dp-2", embedded in longer text, etc.
#: The standing DP-2 window-placement experiment (supply-quality §5,
#: FW-4) must never be contaminated by an artificial plant.
_DP2_RE = re.compile(r"dp-2", re.IGNORECASE)


def canaries_path() -> Path:
    return miner_dir() / "canaries.json"


def _load_canaries() -> list[dict]:
    try:
        data = json.loads(canaries_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    canaries = data.get("canaries") if isinstance(data, dict) else None
    return canaries if isinstance(canaries, list) else []


def _save_canaries(canaries: list[dict]) -> None:
    canaries_path().write_text(
        json.dumps({"canaries": canaries}, indent=0, sort_keys=True),
        encoding="utf-8",
    )


def plant_canary(lesson: str, expect: str | None = None) -> str:
    """§3: a human act — the user states a genuine durable lesson
    in-session as normal speech *and* runs this. Writes ONE entry to
    :func:`canaries_path` (cache-local, like the cursors) and NOTHING
    else — never a transcript file, never a ledger mutation (t-h: plant
    creates/mutates no ``*.jsonl`` under any transcripts dir). Returns
    the new canary's id. Raises :class:`CanaryError` (nothing written)
    for an empty lesson or one naming DP-2 (guard, tested — the standing
    experiment is never planted artificially)."""
    lesson = (lesson or "").strip()
    if not lesson:
        raise CanaryError("--lesson needs a non-empty description")
    expect = (expect or "").strip() or None
    if _DP2_RE.search(lesson) or (expect and _DP2_RE.search(expect)):
        raise CanaryError(
            "refusing a lesson naming DP-2 — the standing window-placement "
            "experiment (forward/supply-quality.md §5) is never planted "
            "artificially; it is already live, adjudicated by human "
            "judgment at review"
        )
    canaries = _load_canaries()
    canary_id = uuid.uuid4().hex[:8]
    canaries.append(
        {
            "id": canary_id,
            "lesson": lesson,
            "expect": expect,
            "planted_at": _now_iso(),
            # Best-effort — no reliable current-session channel exists for
            # a bare CLI invocation; a canary with no session id can still
            # be CAUGHT, it just never scores `missed` (§3).
            "session": os.environ.get("CLAUDE_SESSION_ID") or None,
            "status": "open",
        }
    )
    _save_canaries(canaries)
    return canary_id


def _score_canaries(
    home: Path, record_ids: list[str], mined_session_ids: set[str]
) -> None:
    """§3: deterministic scoring, run after `_reconcile_and_land`. Reuses
    the WORKER's own recurrence-suspect similarity — `worker._tokens` +
    `worker.SUSPECT_JACCARD` — rather than reimplementing it (no new
    infrastructure, drift-free). An open canary is `caught` when its
    lesson/expect token-overlaps a record this run landed or folded at or
    above the Jaccard threshold; otherwise, once its own (best-effort)
    source session has itself been mined with no match, it is `missed`.
    A canary with no recorded session simply stays `open` until caught —
    never a false `missed`. Counts only; a mis-scored canary is cheap
    (unlike a missed dedup) and never enters `supply_mix` or the
    mined-accept-rate (worker-ecology §4-3) — this function touches
    nothing but ``canaries.json``."""
    canaries = _load_canaries()
    if not canaries:
        return
    title_tokens: list[set[str]] = []
    for rid in dict.fromkeys(record_ids):
        found = _find_record(home, rid)
        if found is not None:
            title_tokens.append(worker._tokens(record_title(found[0])))
    changed = False
    for c in canaries:
        if not isinstance(c, dict) or c.get("status") != "open":
            continue
        lesson_tokens = worker._tokens(
            f"{c.get('lesson') or ''} {c.get('expect') or ''}"
        )
        caught = False
        for tt in title_tokens:
            union = lesson_tokens | tt
            if union and len(lesson_tokens & tt) / len(union) >= worker.SUSPECT_JACCARD:
                caught = True
                break
        if caught:
            c["status"] = "caught"
            changed = True
        elif c.get("session") and c["session"] in mined_session_ids:
            c["status"] = "missed"
            changed = True
    if changed:
        _save_canaries(canaries)


def read_canaries_summary() -> dict | None:
    """§4: the `mine status --json` top-level `canaries` field — `None`
    (absent) when no canary has EVER been planted, so the one-liner adds
    "· canaries K/N caught" only when `planted > 0`. Degradation: an
    unreadable `canaries.json` (present but corrupt) reports the all-zero
    shape + a `log()` line, never a crash (E-11 spirit / M-3)."""
    path = canaries_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(f"canaries.json unreadable ({exc}) — reporting zero")
        return {"planted": 0, "caught": 0, "missed": 0, "open": []}
    canaries = data.get("canaries") if isinstance(data, dict) else None
    canaries = canaries if isinstance(canaries, list) else []
    if not canaries:
        return None
    return {
        "planted": len(canaries),
        "caught": sum(1 for c in canaries if c.get("status") == "caught"),
        "missed": sum(1 for c in canaries if c.get("status") == "missed"),
        "open": [
            {"lesson": c.get("lesson"), "planted_at": c.get("planted_at")}
            for c in canaries
            if c.get("status") == "open"
        ],
    }


# ------------------------------------------------------- watchdog (R1 L2)


def _spawn_run(home: Path, *, no_push: bool = False) -> int:
    """setsid-spawn a mining run; returns the child pid.

    ``no_push`` rides the child's ENV because a detached spawn gives no
    other channel — the SAME mechanism worker._spawn_window uses, and the
    only place an env var is legitimate (BLOCKER D). This Popen had no
    ``env=`` at all, and nothing ever set SELF_LEARN_NO_PUSH in the
    PARENT's environ (worker.py builds it into the worker child's env dict
    only), so the var the child looked for could not exist: probed —
    ``reject --no-push`` → watchdog spawns a miner → child sees no var →
    pushes the whole branch, publishing the very commit the flag was
    protecting."""
    env = dict(os.environ)
    env.pop(worker.NO_PUSH_ENV, None)
    if no_push:
        env[worker.NO_PUSH_ENV] = "1"
    with open(miner_dir() / "miner.log", "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "self_learn.cli", "mine", "run",
             "--trigger", "kick"],
            cwd=str(home),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    return proc.pid


def _last_attempt_age_secs() -> float:
    try:
        return time.time() - (miner_dir() / "miner.last-attempt").stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def maybe_kick(home: Path | str, *, no_push: bool = False) -> str:
    """Verb-invocation watchdog: spawn a detached run when the last
    COMPLETED run is >24 h old AND the last ATTEMPT is >2 h old (audit:
    without the attempt cool-down, a persistently failing reader turns
    every CLI invocation into a full walk + 15-minute model attempt).
    Returns disabled | poked | fresh | cooling | busy | spawned.

    ``no_push`` is the INVOKING verb's flag, passed explicitly (BLOCKER
    D). This watchdog ticks before every command except `mine`/`serve`,
    so any ``--no-push`` verb can spawn a miner; the spawned run must
    inherit the policy or the flag is a lie the moment the watchdog
    fires.

    U-engine Phase 2 (spec Sec 5.3) -- REDUCED, not retired: when a
    `self-learn serve` daemon is already running for this home (a fresh
    heartbeat), this watchdog pokes it instead of spawning -- "no spawn
    from a verb, ever" while a daemon already owns the schedule (the
    FW-116 hazard this closes). **Gate r2 B-1' fix**: the serve-alive
    check moved to EXACTLY the point the pre-U-engine watchdog would
    otherwise spawn -- after disabled/fresh/cooling/busy ALL pass, never
    before. The r1 shape checked it FIRST, so a live `serve` poked on
    EVERY verb invocation regardless of staleness (measured: a ledger
    mined 0.0s ago still got poked); this shape means a poke fires under
    the EXACT SAME condition a spawn would have, and nothing else. With
    no live daemon, every leg below is byte-identical to before this
    unit."""
    # U-settings Phase 1: both switches resolve through the registry
    # (`miner.enabled` / `miner.autokick`, config.yaml > env > `True` --
    # U-flip 2026-09-01, S-58: config wins).
    enabled, _e_source = settings.resolve_setting(home, settings.by_name("miner.enabled"))
    autokick, _a_source = settings.resolve_setting(home, settings.by_name("miner.autokick"))
    if not enabled or not autokick:
        return "disabled"
    if _last_run_age_secs() <= KICK_AFTER_SECS:
        return "fresh"
    if _last_attempt_age_secs() <= ATTEMPT_COOLDOWN_SECS:
        return "cooling"
    with open(miner_dir() / "miner.spawn.lock", "w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "busy"
        try:
            # Local import: `serve` imports THIS module (to schedule
            # mine passes as jobs), so a module-level import here would
            # be circular -- this one resolves at CALL time instead, the
            # same pattern `lifecycle.kill_child` already uses for an
            # analogous reason. Gate r2 B-1': THIS is the point the
            # pre-U-engine watchdog would spawn -- serve alive (fresh
            # heartbeat) pokes instead; no live serve spawns exactly as
            # before.
            from . import serve as serve_mod

            if serve_mod.heartbeat_is_fresh(worker.cache_dir(home)):
                serve_mod.request_poke(worker.cache_dir(home))
                return "poked"
            pid = _spawn_run(Path(home), no_push=no_push)
            log(f"watchdog: last run >24h — spawned run (pid {pid})")
            return "spawned"
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ------------------------------------------------------------------ run


def run(
    home: Path | str,
    *,
    trigger: str = "manual",
    since: str | None = None,
    no_push: bool | None = None,
    engine: str | None = None,
    preview: bool = False,
    sessions: Sequence[str] = (),
) -> MineResult:
    """One mining run. ``engine`` (``digest`` or ``session``) overrides the
    ``miner.engine`` setting for this run (new-miner plan §3.8);
    ``preview`` runs the session engine without landing anything, over
    the ``sessions`` named, or over what the walk would judge.

    ``no_push=None`` reads the process boundary once
    (:func:`worker.no_push_requested`) and threads the answer as a
    parameter from there (BLOCKER D).

    MINOR-1 (review r2 2026-09-01, `worker.run`'s own M-2 residual):
    :func:`pending_gate` and :func:`cap_for` below are now called with
    THIS run's own `home`, not bare -- measured before this fix: inside
    one `miner.run(A)`, `miner.enabled` (already threaded, above) read
    A's config.yaml while the gate and cap read `resolve_home()`'s
    config.yaml instead, disagreeing whenever the two differ. One run
    must read one policy file."""
    home = Path(home)
    if no_push is None:
        no_push = worker.no_push_requested()
    # U-settings Phase 1: resolves through the registry's `miner.enabled`
    # entry (config.yaml `miner.enabled` > env `SELF_LEARN_MINER` > `True`
    # -- U-flip 2026-09-01, S-58: config wins).
    chosen = engine if engine is not None else str(settings.resolve_setting(home, settings.by_name("miner.engine"))[0])
    if chosen not in settings.MINER_ENGINES:
        raise ValueError(f"miner.run: unknown engine {chosen!r}")
    if (preview or sessions) and chosen != "session":
        raise ValueError("miner.run: --preview and --session belong to the session engine")
    if sessions and not preview:
        raise ValueError("miner.run: --session needs --preview")
    enabled, _source = settings.resolve_setting(home, settings.by_name("miner.enabled"))
    if not enabled:
        return MineResult(status="disabled")
    t0 = time.time()
    run_id = uuid.uuid4().hex[:8]

    # a preview opens the lock without truncating it, and logs into its own
    # run folder: the lock file (created when absent) is all it writes
    # outside that folder (the seam's own copies and logs aside)
    if preview:
        lock_fh = open(miner_dir() / "miner.lock", "a", encoding="utf-8")
    else:
        lock_fh = open(miner_dir() / "miner.lock", "w", encoding="utf-8")
    global _LOG_TO
    if preview:
        _LOG_TO = miner_dir() / "runs" / run_id / "miner.log"
    try:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return MineResult(status="busy")
        if not preview:  # a preview is no attempt at the night's run
            (miner_dir() / "miner.last-attempt").touch()  # watchdog cool-down

        base = {
            "ts": _now_iso(),
            "run_id": run_id,
            "trigger": trigger,
            "rubric_version": _rubric()[1],
            # M-S (S-58 code-gate fold r1, minor-1): the STAMP records
            # the model that would actually run the "miner-reader"
            # surface -- `provider.model_for`'s full registry-backed
            # answer (`models.miner` / `provider.bedrock.models.miner`
            # under this run's OWN `home`), not `miner_model()`'s bare
            # env-or-default rung, which is invisible to a `models.
            # miner: X` config.yaml value entirely. `miner_model()`
            # itself is UNCHANGED (it stays a registry default rung --
            # `_default_miner_model` in settings.py calls it -- calling
            # `model_for` FROM it would recurse). Measured: `model_for`
            # never raises (no `model_for`/`resolve_setting` call site
            # in its graph raises; refusal is a separate mechanism in
            # `session_env`/`resolve()` this pure-heuristic `run()`
            # never touches), so this stamp adds no new raise where
            # today there is only a write.
            "model": provider.model_for("miner-reader", home=home),
        }
        if chosen == "session":
            base["model"] = provider.model_for(engine_mod.SURFACE, home=home)

        # BLOCKER 11 (audit 2026-07-16): the nightly miner resolves the
        # home too — and a unit resolving a DIFFERENT home than the shell
        # is the live failure mode. Mining into the void would land
        # candidates nobody ever sees; fail loudly in the log AND the
        # journal (`mine status` is the surface that notices).
        state = home_state(home)
        if state in ("missing", "not-a-repo"):
            reason = home_state_message(state, home)
            log(f"run {run_id}: REFUSED — {reason}")
            if not preview:
                _journal({**base, "status": "failed", "reason": reason[:300],
                          "duration_secs": round(time.time() - t0, 1)})
            return MineResult(status="failed", run_id=run_id)

        try:
            if preview:
                return _run_preview(home, since, t0, run_id, base, sessions)
            return _run_locked(home, since, t0, run_id, base, no_push=no_push, engine=chosen)
        except Exception as exc:  # noqa: BLE001 — A1: EVERY run journals,
            # even a crashed one (audit B1: an uncaught error previously
            # left no journal entry at all — invisible to mine status).
            log(f"run {run_id}: CRASHED — {exc}\n{traceback.format_exc()}")
            if not preview:
                _journal({**base, "status": "failed",
                          "reason": f"crashed: {exc}"[:300],
                          "duration_secs": round(time.time() - t0, 1)})
            return MineResult(status="failed", run_id=run_id)
    finally:
        _LOG_TO = None
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fh.close()


def _run_locked(
    home: Path,
    since: str | None,
    t0: float,
    run_id: str,
    base: dict,
    *,
    no_push: bool = False,
    engine: str = "digest",
) -> MineResult:
    # SELF-HEALING (audit 2026-07-16 round 7 MAJOR 4). Before mining
    # anything new, commit whatever a previous producer wrote and could
    # not commit — very much including THIS miner's own last run, whose
    # `landed-uncommitted` status meant "these records are untracked, the
    # cursors advanced past them, and a clone deletes them". Reporting
    # that honestly was not recovery; this is. It runs FIRST, so a nightly
    # timer is enough to close the window without a human ever being told.
    # Idempotent and cheap on a clean ledger; never fatal — a miner that
    # cannot heal must still mine.
    try:
        healed = reconcile_mod.reconcile(home, no_push=no_push)
        # Gate r1 BLOCKER-2: `healed.healed` is true whenever ANYTHING
        # happened (an ordinary commit, OR an intent recovery with
        # nothing committed at all), but `healed.sha` is set ONLY by the
        # ordinary orphan-commit path below — `if healed.healed:` here
        # crashed on `healed.sha[:7]` the first time a mine start
        # recovered an intent with no orphans alongside it. Guarded on
        # `healed.committed` instead, mirroring `cli.py`'s own
        # `_cmd_push` fix for the identical field.
        if healed.committed:
            log(
                f"run {run_id}: reconciled {len(healed.committed)} orphaned "
                f"path(s) from an earlier run @ {healed.sha[:7]}"
            )
        # M-W/D7, each on its OWN line (gate r1 BLOCKER-2), mirroring
        # `cli.py:2232-2235`'s per-intent-id loops — never folded into
        # one combined line naming all three lists at once.
        for intent_id in healed.rolled_forward:
            # Gate r1 MAJOR-2: roll-forward only ever replays the
            # LEDGER's own commit — it never re-runs `_host_phase` (that
            # step lives inside the interrupted `_execute_route` call,
            # which is gone). Silence here is the bug MAJOR-2 found: the
            # host target is left uncompiled and nothing said so. Name
            # the repair on every surface that reports a roll-forward.
            log(
                f"run {run_id}: recovered {intent_id} (rolled forward: its "
                "commit landed — the host phase did not run; run "
                "'self-learn recompile')"
            )
        for intent_id in healed.restored:
            log(f"run {run_id}: recovered {intent_id} (restored: its mutation was undone)")
        for line in healed.blocked:
            log(f"run {run_id}: reconcile left a half-committed change: {line}")
        # M-C: an invalid orphan refuses the whole reconcile batch the
        # same as a blocked rename does — logged the same way, never
        # fatal. A miner that cannot heal must still mine.
        for line in healed.invalid:
            log(f"run {run_id}: reconcile left an invalid orphan uncommitted: {line}")
        # Sweep 2, R1: what an invalid/blocked orphan holds back with it.
        for line in healed.held:
            log(f"run {run_id}: reconcile left an orphan uncommitted: {line}")
        # M-W/D7: an intent recovery that verified neither roll-forward
        # nor restore refuses the same way — logged the same way, never
        # fatal. The intent file itself is left in place for a human.
        for line in healed.stopped:
            log(f"run {run_id}: reconcile could not resolve an intent, left for a human: {line}")
        # S-62 (§7.2a.5(4)): unlike every OTHER line above, a STOP here
        # is the one exception to "never fatal — a miner that cannot
        # heal must still mine". A run that cannot land has nothing to
        # mine FOR, so it ends HERE — before `initialized()`/`walk()`
        # and before any model session is spent — rather than logging
        # and proceeding as it did before this sprint.
        if healed.stopped:
            _journal({**base, "status": "stopped", "reason": "; ".join(healed.stopped)[:300],
                      "duration_secs": round(time.time() - t0, 1)})
            return MineResult(status="stopped", run_id=run_id, stopped=healed.stopped)
    except gitops.GitOpsError as exc:
        log(f"run {run_id}: reconcile step skipped ({exc})")

    # Read once: one run, one opt-in (M-5, scheduled jobs).
    mined_scheduled = mined_scheduled_jobs(home)

    # First-activation forward-only pin (§8 R2, audit B2): seed cursors at
    # the current end of every existing transcript and stop — history is
    # reachable only through the deliberate --since backfill.
    if not initialized():
        seeded = initialize_cursors(mined_scheduled)
        (miner_dir() / "miner.last-run").touch()
        _journal({**base, "status": "initialized", "files_seeded": seeded,
                  "duration_secs": round(time.time() - t0, 1)})
        log(f"run {run_id}: initialized forward-only ({seeded} files seeded)")
        return MineResult(status="initialized", run_id=run_id)

    swept = halt_tracked_self_sessions()
    if swept.halted:
        log(
            f"run {run_id}: halted {swept.halted} tracked sessions that open with a "
            "self-learn prompt (the steward's, the overseer's, ...): never mined"
        )
    if swept.unchecked:
        # a count only: never a path, never anything a file or an exception said
        log(
            f"run {run_id}: {swept.unchecked} tracked sessions could not be checked "
            "against the self-learn prompts this time; they are checked again next run"
        )
    swept = halt_tracked_scheduled_sessions(mined_scheduled)
    if swept.halted:
        log(
            f"run {run_id}: halted {swept.halted} tracked sessions of scheduled jobs "
            "not named in miner.mined_scheduled_jobs: never mined"
        )
    if swept.unchecked:
        # a count only, as above
        log(
            f"run {run_id}: {swept.unchecked} tracked sessions were not checked for "
            "scheduled jobs this time; they are checked again next run"
        )

    if engine == "session":
        # a run that stopped between saving an answer and moving its
        # session's cursor moves it here, before the walk: a saved answer
        # is never asked for again
        waiting_now, _broken = mining_waiting.load_all(miner_dir())
        moved = _settle_waiting_cursors(waiting_now)
        if moved:
            log(f"run {run_id}: moved {moved} cursor(s) to their waiting answers")
    slices = walk(since)
    digests: list[str] = []
    processed: list[tuple[SessionSlice, bool]] = []
    cwds: dict[str, str] = {}  # session id → transcript cwd (doc 13 §3)
    #: U-cursorhold H-1: session id → that slice's halt flag, populated ONLY
    #: in the branch below that appends a digest — never for a slice
    #: excluded (nothing minable) or deferred (over budget). A session
    #: absent from this map is a session whose text this run's reader
    #: never saw, so a cap drop citing it cannot hold anything (H-2).
    digested: dict[str, bool] = {}
    excluded = 0
    total_chars = 0
    deferred_files = 0
    limits = digest_limits(home)  # read once: one run, one set of limits
    # refs rule 10 (2026-10-19): text other sessions handed to herdr, read
    # once per run from the transcripts and the sibling Codex, Hermes, agy and pi stores.
    sent = (
        provenance.sweep(provenance.sender_dirs([transcripts_root(home)]))
        if slices
        else provenance.SentIndex()
    )
    if engine == "session":
        # new-miner plan §1: the session engine replaces exactly the digest
        # step; everything above (lock, healing, seeding, sweeps, walk, the
        # sends) and the landing commit are shared
        return _run_session_engine(
            home, slices, sent, mined_scheduled, run_id, base, t0, preview=False, no_push=no_push
        )
    for s in slices:
        digest, halt = digest_transcript(s, limits, mined_scheduled=mined_scheduled, sent=sent)
        if digest is None:
            excluded += 1
            processed.append((s, halt))  # nothing minable — cursor advances
            continue
        if total_chars + len(digest) > limits.run_chars:
            deferred_files += 1  # stays behind the cursor for next run
            continue
        total_chars += len(digest)
        digests.append(digest)
        processed.append((s, halt))
        digested[s.session_id] = halt
        cwd = _slice_cwd(s)
        if cwd:
            cwds[s.session_id] = cwd
    halted_by_reason: Counter[str] = Counter()
    for s, halt in processed:
        if halt and s.halt_reason:
            halted_by_reason[s.halt_reason] += 1
    if halted_by_reason:
        # counts by reason only: never a path, a job's name, or a session's text
        log(
            f"run {run_id}: halted {sum(halted_by_reason.values())} sessions, the rest of each never mined ("
            + ", ".join(f"{reason}: {n}" for reason, n in sorted(halted_by_reason.items()))
            + ")"
        )

    result = MineResult(
        status="idle", run_id=run_id, sessions_scanned=len(digests)
    )

    if not digests:
        _advance_cursors(processed)
        (miner_dir() / "miner.last-run").touch()
        _journal({**base, "status": "idle", "sessions_scanned": 0,
                  "excluded": excluded,
                  "duration_secs": round(time.time() - t0, 1)})
        log(f"run {run_id}: idle (nothing new)")
        return result

    # Flood gate (§8 Q3): don't advance cursors — nothing is missed.
    total_pending = worker.fast_status(home)["total_pending"]
    gate = pending_gate(home=home)
    if total_pending >= gate:
        result.status = "held-gate"
        (miner_dir() / "miner.last-run").touch()
        _journal({**base, "status": "held-gate",
                  "pending": total_pending, "gate": gate,
                  "sessions_ready": len(digests),
                  "duration_secs": round(time.time() - t0, 1)})
        log(f"run {run_id}: held — {total_pending} pending ≥ gate {gate}")
        return result

    out_path = spool_dir() / OUTPUT_BASENAME
    prompt, corrupt = _compose_prompt(home, digests, out_path)
    if corrupt:
        # FW-53: degrade, don't wedge — the rest of the ledger still
        # reconciles and this run still lands candidates; the corruption
        # is reported (miner.log + every journal entry from here on),
        # never swallowed.
        result.corrupt_records = sorted({str(p) for p in corrupt})
        for p in result.corrupt_records:
            log(f"run {run_id}: ledger record {p} not readable (not UTF-8, "
                "or a frontmatter that does not load) — excluded from the "
                "reconciliation index")
    artifact = _invoke_reader(home, prompt)
    if artifact is None:
        result.status = "failed"
        _journal({**base, "status": "failed",
                  "reason": "reader produced no output",
                  "sessions_scanned": len(digests),
                  "corrupt_records": result.corrupt_records,
                  "duration_secs": round(time.time() - t0, 1)})
        return result
    try:
        parsed = json.loads(artifact.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("output is not a JSON object")
    except (OSError, ValueError) as exc:
        result.status = "failed"
        _journal({**base, "status": "failed",
                  "reason": f"unparseable reader output: {exc}",
                  "sessions_scanned": len(digests),
                  "corrupt_records": result.corrupt_records,
                  "duration_secs": round(time.time() - t0, 1)})
        return result

    cap = cap_for(len(digests), home=home)
    hold = sentinel.hold()
    try:
        # ONE lock spanning [first mutation → commit] (audit 2026-07-16
        # round 7): the lock used to open at the commit below, but
        # `_reconcile_and_land` mutates first — a FOLD rewrites an
        # existing pending record, and that file is TRACKED, so a racing
        # `pull --rebase --autostash` stashes the rewrite and restores it
        # into a conflict. Landing a NEW record is the benign half
        # (untracked files survive an autostash); folding is not, and both
        # live in the same call.
        with intents.ledger_write(home) as recovered:  # S-62: the landing lock's own backstop check
            # §7.2a.5(3): UNATTENDED — log each recovered id on its own
            # line, the same shape the run-start reconcile healing above
            # uses, never a bare stderr print (this lock is not the run's
            # first, so a STOP found HERE cannot be reported until after
            # this `with` raises; a clean recovery here is logged now).
            for intent_id in recovered.rolled_forward:
                log(
                    f"run {run_id}: recovered {intent_id} (rolled forward: its "
                    "commit landed — the host phase did not run; run "
                    "'self-learn recompile')"
                )
            for intent_id in recovered.restored:
                log(f"run {run_id}: recovered {intent_id} (restored: its mutation was undone)")
            _reconcile_and_land(home, parsed, result, cap, cwds, digested)
            _commit_landing(home, result, run_id, no_push=no_push)
    except gitops.GitOpsError as exc:
        # BLOCKER B: every GitOpsError is caught — including a lock
        # TIMEOUT, which is not an error but a busy neighbour. This is a
        # detached timer job; an escaping exception is a stack dump in
        # miner.log and a dead nightly run. A timeout HERE is now a clean
        # no-op: the lock is taken before the first mutation.
        result.landing_uncommitted = bool(result.landed)
        log(f"run {run_id}: could not take the ledger lock ({exc})")
    finally:
        hold.release()

    # FW-34 §3: deterministic canary scoring — after _reconcile_and_land,
    # reusing worker._tokens/SUSPECT_JACCARD (never reimplemented), no
    # reader change. Cache-local (canaries.json) and never fatal to the
    # run — a scoring failure is logged, not raised (M-3 spirit; counts
    # never enter supply_mix or the mined-accept-rate, worker-ecology §4-3).
    try:
        _score_canaries(
            home,
            result.landed + result.folded,
            {s.session_id for s, _halt in processed},
        )
    except Exception as exc:  # noqa: BLE001 — canary scoring never crashes a run
        log(f"run {run_id}: canary scoring skipped ({exc})")

    # U-cursorhold H-3: withhold an entry of `processed` iff its slice's
    # session id was HELD by this run's cap AND that slice's own halt
    # flag is False. `processed` itself is not mutated or reassigned —
    # this is a freshly built list at this one call site, and the halted
    # half of the guard is load-bearing, not belt-and-braces: a same-stem
    # unhalted twin can classify `held` (§3.1 H-5's aliasing), and
    # filtering on session id alone would then withhold a HALTED slice's
    # cursor too — the exact M-5 regression this unit refuses (§3.2).
    _advance_cursors(
        [
            (s, halt)
            for s, halt in processed
            if s.session_id not in result.held_sessions or halt
        ]
    )
    (miner_dir() / "miner.last-run").touch()
    # A run whose landings never committed is NOT "ok" (BLOCKER B (c)):
    # `mine status` would otherwise report a clean nightly run over records
    # that no clone will ever see. It is no longer DATA LOSS, though (round
    # 7 MAJOR 4): the next run's `reconcile` step commits them, and so does
    # `self-learn reconcile` / `self-learn push` on demand.
    result.status = "landed-uncommitted" if result.landing_uncommitted else "ok"
    # FW-34 §1.1/§4: fold each outcome's disposition/reason/promotable at
    # journal-write time (the no-derivation rule — the UI renders this
    # verbatim, never re-maps it) + the per-run near_miss_count.
    enriched_outcomes = [_enrich_near_miss(o) for o in result.outcomes]
    near_miss_count = sum(1 for o in enriched_outcomes if "disposition" in o)
    _journal({**base, "status": result.status,
              "landing_uncommitted": result.landing_uncommitted,
              "sessions_scanned": len(digests),
              "excluded": excluded,
              "deferred_files": deferred_files,
              "cap": cap,
              "landed": len(result.landed),
              "folded": len(result.folded),
              "recurrences": len(result.recurrences),
              "fires": result.fires,
              "outcomes": enriched_outcomes,
              "near_miss_count": near_miss_count,
              "corrupt_records": result.corrupt_records,
              # U-cursorhold O-2: distinct held sessions — covers `ok` and
              # `landed-uncommitted` ONLY, by construction (this is the one
              # journal write both statuses share). An absent key means
              # "not a landing run", never "no cursors were held" — a
              # `held-gate` run holds EVERY cursor and writes a different
              # entry entirely, with no key of this name.
              "cursors_held": len(result.held_sessions),
              "duration_secs": round(time.time() - t0, 1)})
    log(
        f"run {run_id}: {result.status} — {len(result.landed)} landed, "
        f"{len(result.folded)} folded, {len(result.recurrences)} "
        f"recurrence(s), {result.fires} fire(s)"
    )

    # Flush only when this run actually produced events — an empty nightly
    # flush would put a machine-triggered commit on the tracked telemetry
    # plane for nothing (audit m8).
    if result.landed or result.folded or result.recurrences or result.fires:
        try:
            flush_report = telemetry.flush(home)
        except telemetry.TelemetryError as exc:
            log(f"run {run_id}: telemetry flush refused ({exc})")
        else:
            # §7.2a.5(3): unattended — log, never print.
            for intent_id in flush_report.recovered_rolled_forward:
                log(
                    f"run {run_id}: recovered {intent_id} (rolled forward: its "
                    "commit landed — the host phase did not run; run "
                    "'self-learn recompile')"
                )
            for intent_id in flush_report.recovered_restored:
                log(f"run {run_id}: recovered {intent_id} (restored: its mutation was undone)")

    if result.landed:
        worker.kick(home)  # analyzed before any human sees the card
    return result


# ------------------------------------------------ the session engine's run


def _session_call(spec: invocation.SessionSpec) -> invocation.Outcome:
    """The session engine's one seam call (plan §3.5): one session, its
    final message back as ``stdout``."""
    return invocation.text_session(spec)


def _named_slices(home: Path, session_ids: Iterable[str]) -> tuple[list[SessionSlice], list[str]]:
    """``mine run --preview --session ID``: each named session's whole file
    (the larger, when two folders hold one id), and the ids not found. A
    session on ``miner.skip_sessions`` is never read, named or not."""
    root = transcripts_root(home)
    listed = skip_sessions(home)
    slices: list[SessionSlice] = []
    missing: list[str] = []
    for sid in dict.fromkeys(session_ids):
        if not _SESSION_ID_RE.match(sid) or sid in listed or not root.is_dir():
            missing.append(sid)
            continue
        files = sorted(root.glob(f"*/{sid}.jsonl"), key=lambda p: (p.stat().st_size, str(p)), reverse=True)
        lines = _complete_lines(files[0]) if files else None
        if not files or not lines:
            missing.append(sid)
            continue
        path = files[0]
        slices.append(SessionSlice(path=path, session_id=sid, project=path.parent.name, start_line=0,
                                   lines=lines, stat_size=path.stat().st_size))
    return slices, missing


def _judged_uuids(
    store: "mining_uuids.JudgedUuids", *, preview: bool, relearn: Sequence["mining_waiting.Answer"] = ()
) -> tuple[frozenset[str], dict]:
    """The judged-uuid store's snapshot for this run, read once before
    anything is judged, and what the run record says about the store. A
    damaged store is moved aside (never in a preview, never a locked one);
    rows past 120 days are pruned (never in a preview). ``relearn``: the
    waiting answers; what each teaches the store is added again (a row
    keeps its first date), so a run that stopped between a save and the
    store's write, or a store moved aside, still knows those moments. An
    answer whose write succeeds is ``learned`` (a finished one may then be
    removed); every answer's moments are in the snapshot either way, so a
    store that cannot be written never lets a saved moment be judged
    again (fix round 5)."""
    info: dict = {"state": "ok", "loaded": 0}
    if store.damaged:
        if preview:
            info["state"] = "damaged"
        else:
            try:
                aside = store.rebuild()
            except OSError:
                aside = None
            info["state"] = "rebuilt" if aside is not None else "damaged"
            info["aside"] = aside.name if aside is not None else None
            log(f"judged-uuid store damaged; {'moved aside to ' + aside.name if aside else 'could not move it'}")
    if not preview:
        try:
            mining_uuids.prune_damaged(store.path)
        except OSError:
            pass
    if not preview and not store.locked and not store.damaged:
        try:
            info["pruned"] = store.prune(datetime.now(timezone.utc).date())
        except Exception as exc:  # noqa: BLE001 -- sqlite3.Error; a prune never fails a run
            if mining_uuids.is_lock_timeout(exc):
                store.locked = True
    today = datetime.now(timezone.utc).date()
    for answer in relearn:
        if not answer.learn:
            answer.learned = True
            continue
        if preview or store.locked or store.damaged:
            continue
        try:
            info["relearned"] = info.get("relearned", 0) + store.add(answer.learn, today)
            answer.learned = True
        except Exception as exc:  # noqa: BLE001 -- sqlite3.Error; the answer is kept and tried again
            info["relearn_failed"] = info.get("relearn_failed", 0) + 1
            if mining_uuids.is_lock_timeout(exc):
                store.locked = True
    snapshot = frozenset() if store.locked or store.damaged else store.snapshot()
    if relearn:
        snapshot = snapshot.union(*(a.learn for a in relearn))
    if store.locked:
        info["state"] = "locked"
    info["loaded"] = len(snapshot)
    return snapshot, info


def _run_session_engine(
    home: Path,
    slices: list[SessionSlice],
    sent: provenance.SentIndex,
    mined_scheduled: frozenset[str],
    run_id: str,
    base: dict,
    t0: float,
    *,
    preview: bool,
    no_push: bool,
    missing: Sequence[str] = (),
) -> MineResult:
    """The session engine in place of the digest step (plan §1): plan each
    slice, call each session, check each answer, and -- unless ``preview``
    -- save each checked answer as a waiting answer (`mining.waiting`),
    move that session's cursor and teach the judged-uuid store from it,
    then land every waiting answer under the ledger lock, oldest first
    (fix round 4, the user's design). A landing that fails never asks the
    model again: the item stays waiting and lands on a later run. A preview
    writes its run folder only: no waiting answer, no landing, no cursor,
    no judged uuid, no journal row. One session's failed call, bad output
    or checker error never fails the others."""
    from . import session_copies, steward_inputs

    cfg = engine_mod.EngineSettings.resolve(home)
    mdir = miner_dir()
    started = _now_iso()
    jbase = {**base, "engine": "session"}
    result = MineResult(status="preview" if preview else "idle", run_id=run_id)
    summary: dict = {"run_id": run_id, "preview": preview, "missing": len(missing)}
    result.engine = summary
    # the waiting answers earlier runs saved; a preview never loads them
    # (`mining.waiting.load_all` is not called on a preview)
    earlier: list[mining_waiting.Answer] = []
    unreadable: list[str] = []
    if not preview:
        earlier, unreadable = mining_waiting.load_all(mdir)
        for name in unreadable:
            # its cursor and the store already moved: say so where a person looks
            _outcome(result, f"pending:{name}", "waiting-unreadable",
                     reason="this waiting answer does not read; its output waits on a manual repair")
        if unreadable:
            log(f"run {run_id}: {len(unreadable)} waiting answer file(s) do not read; they are left in "
                "place and their output waits on a manual repair (self-learn doctor miner)")

    gate_seen: dict = {}

    def gate_closed() -> bool:
        """The flood gate (§8 Q3), read once a run: closed when the
        pending queue is at the gate. It holds every call and every
        landing of a waiting answer."""
        if "closed" not in gate_seen:
            total = worker.fast_status(home)["total_pending"]
            limit = pending_gate(home=home)
            gate_seen.update(closed=total >= limit, pending=total, gate=limit)
            if gate_seen["closed"]:
                log(f"run {run_id}: held — {total} pending ≥ gate {limit}")
        return bool(gate_seen["closed"])

    def drain(new: list[mining_waiting.Answer], cap: int) -> DrainReport:
        """Land the waiting answers, earlier runs' first, under the lock.
        Every run that is not a preview drains, whether or not it called
        anyone; a lock it cannot take leaves every answer waiting. Every
        drain passes the flood gate here: a run the gate holds lands
        nothing (landing adds pending records to a review queue that is
        already full), and the answers wait for the first run after it
        opens."""
        answers = earlier + new
        report = DrainReport(found=len(earlier), unreadable=list(unreadable))
        if answers and gate_closed():
            report.gate_held = True
        elif answers:
            hold = sentinel.hold()
            try:
                with intents.ledger_write(home) as recovered:  # S-62: the landing lock's own backstop check
                    report.drained = True  # the lock is acquired: never read as the drain completing
                    for intent_id in recovered.rolled_forward:
                        log(
                            f"run {run_id}: recovered {intent_id} (rolled forward: its "
                            "commit landed — the host phase did not run; run "
                            "'self-learn recompile')"
                        )
                    for intent_id in recovered.restored:
                        log(f"run {run_id}: recovered {intent_id} (restored: its mutation was undone)")
                    landed = _drain_waiting(home, answers, result, cap, run_id)
                    report.landed_earlier, report.landed_this_run = landed.landed_earlier, landed.landed_this_run
                    report.terminal = landed.terminal
                    _commit_landing(home, result, run_id, no_push=no_push, folds_alone=True)
                    # the marks come after a commit that succeeded
                    _finish_drain(home, answers, report, committed=not result.landing_uncommitted)
            except gitops.GitOpsError as exc:
                # the lock was not taken, or the landing or its commit did
                # not complete: what was written is on disk with its item
                # still `writing` (the next run finds it and marks it; its
                # reconcile commits it); the rest waits
                result.landing_uncommitted = bool(result.landed or result.folded)
                log(f"run {run_id}: the waiting answers did not all land ({exc}); the rest wait")
            finally:
                hold.release()
        report.still_waiting = sum(len(a.waiting()) for a in answers)
        report.stuck = [s.as_dict() for s in mining_waiting.stuck_items(answers)]
        if report.stuck:
            log(f"run {run_id}: {len(report.stuck)} waiting item(s) failed to land on "
                f"{mining_waiting.STUCK_AFTER} or more runs (self-learn doctor miner)")
        return report

    def after_landing(report: DrainReport, saved_ids: set[str]) -> None:
        if result.landed or result.folded or saved_ids:
            try:
                _score_canaries(home, result.landed + result.folded, saved_ids)
            except Exception as exc:  # noqa: BLE001 — canary scoring never crashes a run
                log(f"run {run_id}: canary scoring skipped ({exc})")
        if report.drained or telemetry.read_spooled(("fire", "recurrence-suspect")):
            # a fire or recurrence-suspect spooled by a run that stopped
            # before its flush is flushed here, whatever this run spooled
            try:
                flush_report = telemetry.flush(home)
            except telemetry.TelemetryError as exc:
                log(f"run {run_id}: telemetry flush refused ({exc})")
            else:
                for intent_id in flush_report.recovered_rolled_forward:
                    log(
                        f"run {run_id}: recovered {intent_id} (rolled forward: its "
                        "commit landed — the host phase did not run; run "
                        "'self-learn recompile')"
                    )
                for intent_id in flush_report.recovered_restored:
                    log(f"run {run_id}: recovered {intent_id} (restored: its mutation was undone)")
        if result.landed:
            worker.kick(home)

    def stop(status: str, reason: str) -> MineResult:
        result.status = status
        summary["reason"] = reason
        if not preview:
            report = drain([], cap_for(0, home=home))
            summary["waiting"] = report.as_dict()
            _journal({**jbase, "status": status, "reason": reason[:300], "waiting": _waiting_counts(report),
                      "duration_secs": round(time.time() - t0, 1)})
            after_landing(report, set())
        log(f"run {run_id}: {status} — {reason}")
        return result

    try:
        shared_text, method_version = engine_mod.shared_instructions()
    except engine_mod.EngineError as exc:
        return stop("failed", str(exc))
    jbase["method_version"] = method_version
    summary["method_version"] = method_version

    # a preview reads copies inside its own run folder: SQLite rolls back a
    # crash's hot journal on open, and the index refresh writes -- neither
    # may touch the live files
    folder = engine_mod.RunFolder(mdir, run_id)
    live_store = mdir / mining_uuids.STORE_NAME
    store = mining_uuids.JudgedUuids.load(
        engine_mod.copy_sqlite(live_store, folder.path / "copies") if preview else live_store
    )
    snapshot, uuid_info = _judged_uuids(store, preview=preview, relearn=earlier)

    # ---- plan
    plans: list[engine_mod.Plan] = []
    processed: list[tuple[SessionSlice, bool]] = []  # skipped: their cursors advance
    to_call: list[tuple[SessionSlice, engine_mod.Plan, bool]] = []
    deferred = 0
    seen: set[str] = set()
    halted_by_reason: Counter[str] = Counter()
    claimed: frozenset[str] = frozenset()
    plan_judged: dict[str, frozenset[str]] = {}
    index, _index_info = steward_inputs.refresh_index(home, copy_to=folder.path / "copies" if preview else None)
    # a session that failed in earlier runs waits behind those that have not
    failing = engine_mod.Failures.load(mdir)
    try:
        search_mode = index.mode()[0] if index is not None else "lexical-only"
        records = mining_tools.load_records(home)
        for s in sorted(slices, key=lambda s: failing.count(str(s.path), s.start_line) > 0):
            if s.session_id in seen or len(to_call) >= cfg.max_sessions:
                # one file per session id a run (the other is judged next
                # run), and at most `max_sessions_per_run` calls: the rest
                # wait behind their cursors
                deferred += 1
                continue
            seen.add(s.session_id)
            hp = halt_point(s, mined_scheduled=mined_scheduled)
            if hp.halt:
                s.halt_reason = hp.reason
                halted_by_reason[str(hp.reason)] += 1
            # a fork copies its parent's entries: the moments of every
            # session already planned for a call this run read as judged,
            # so the fork's spine shows them as mined and one lands once
            judged = snapshot | claimed if claimed else snapshot
            plan = engine_mod.plan_session(
                s.path, s.start_line, len(s.lines), hp.end, home=home, sent=sent, judged_uuids=judged,
                spine_tokens=cfg.spine_tokens, index=index, records=records,
                # a preview's tools read its own copy of the index, never the live file
                index_file=(index.path if index is not None else folder.path / "copies" / "no-index")
                if preview else None,
            )
            plans.append(plan)
            if plan.skip is not None:
                processed.append((s, hp.halt))
            else:
                to_call.append((s, plan, hp.halt))
                plan_judged[plan.session_id] = judged
                if plan.spine is not None:
                    claimed |= plan.spine.moment_uuids
    finally:
        if index is not None:
            index.close()
    if halted_by_reason:
        log(
            f"run {run_id}: halted {sum(halted_by_reason.values())} sessions, the rest of each never mined ("
            + ", ".join(f"{reason}: {n}" for reason, n in sorted(halted_by_reason.items()))
            + ")"
        )
    skipped = Counter(p.skip for p in plans if p.skip)
    summary.update(sessions=len(plans), skipped=dict(sorted(skipped.items())), deferred=deferred,
                   to_call=len(to_call), judged_uuids=uuid_info)

    # Flood gate (§8 Q3): nothing is called and no cursor moves; no
    # waiting answer lands either (`drain` checks the gate for every run)
    gated = bool(to_call) and not preview and gate_closed()
    calling = bool(to_call) and not gated

    if not calling and preview:
        engine_mod.drop_copies(folder.path / "copies")
        log(f"run {run_id}: preview: idle (nothing new to call)")
        return result

    # ---- call
    calls: dict[str, engine_mod.CallRecord] = {}
    stopped = False
    results: dict[str, engine_mod.SessionResult] = {}
    model = provider.model_for(engine_mod.SURFACE, home=home)
    if calling:
        shared_path = folder.put("shared-instructions.md", shared_text)
        if not preview:  # a preview never prunes another run's folder or copies
            engine_mod.prune_runs(mdir, current=run_id)  # this run's folder is one of the 30
            engine_mod.prune_session_copies(session_copies.sessions_dir(home))
        for _s, plan, _halt in to_call:
            engine_mod.save_plan(folder, plan)
        stage = folder.path / "stage" if preview else mdir / "session-stage"
        stage.mkdir(parents=True, exist_ok=True)
        timeout = reader_timeout_secs(home)

        def make_spec(plan: engine_mod.Plan, k: int) -> invocation.SessionSpec:
            return engine_mod.session_spec(
                plan, k, home=home, run_id=run_id, stage=stage, shared=shared_path, timeout=timeout,
                disallowed_tools=READER_DISALLOWED_TOOLS, log=log, sweep=not preview,
            )

        calls, stopped = engine_mod.call_sessions(
            [plan for _s, plan, _h in to_call], make_spec=make_spec, call=_session_call,
            parallel=cfg.parallel, max_usd=cfg.max_usd,
        )

        # ---- check
        roots = list(dict.fromkeys([transcripts_root(home), *refs.transcript_roots(home)]))
        for _s, plan, _halt in to_call:
            rec = calls[plan.session_id]
            if not rec.started:
                continue
            res = engine_mod.check_session(
                plan, rec, run_id=run_id, model=model, method_version=method_version, roots=roots,
                judged_uuids=plan_judged.get(plan.session_id, snapshot), known_records=frozenset(records),
                search_mode=search_mode, sent=sent,
            )
            results[plan.session_id] = res
            engine_mod.save_result(folder, res)
    ok = [(s, results[p.session_id], halt) for s, p, halt in to_call
          if p.session_id in results and results[p.session_id].status == "ok"]

    # ---- save: each checked answer is written as a waiting answer before
    # anything of it lands. Once it is on disk, the judged-uuid store
    # learns from it and the session's cursor moves: the model is never
    # asked about those lines again. A failed call or check saves, moves
    # and teaches nothing; the session is called again later.
    saved: dict[str, mining_waiting.Answer] = {}
    uuid_info.setdefault("added", 0)
    if not preview:
        today = datetime.now(timezone.utc).date()
        for s, res, halt in ok:
            sid = s.session_id
            spine = res.plan.spine
            # the spine's moments, but not those it showed as judged: a
            # moment another session of this run claimed reaches the store
            # only through that claimer's own save (a cited one too)
            judged = plan_judged.get(sid, snapshot)
            others = judged - snapshot
            learn = ((spine.moment_uuids - judged) if spine is not None else frozenset()) | (
                check_mod.cited_uuids(res.checked) - others
            )
            try:
                saved[sid] = mining_waiting.save(
                    mdir, session=sid, transcript=str(s.path), run_id=run_id, method_version=method_version,
                    halted=halt, cwd=_slice_cwd(s),
                    cursor={"lines": s.start_line + len(s.lines), "size": s.stat_size, "halt": bool(halt)},
                    learn=learn, checked=res.checked,
                )
            except OSError as exc:
                log(f"run {run_id}: the answer of {sid} was not saved ({exc}); it is called again next run")
                continue
            try:
                uuid_info["added"] += store.add(learn, today)
                saved[sid].learned = True
            except Exception:  # noqa: BLE001 -- sqlite3.Error: the answer is kept and teaches it next run
                uuid_info["add_failed"] = uuid_info.get("add_failed", 0) + 1
            _advance_cursors([(s, halt)])
            for drop in res.checked["drops"]:
                _outcome(result, f"transcript:{sid}", "dropped-check", reason=drop["reason"], item=drop["item"])
        if not gated:
            _advance_cursors(processed)

        # ---- land: every waiting answer, earlier runs' first
        report = drain(list(saved.values()), cap_for(len(results), home=home))
        after_landing(report, set(saved))
    else:
        report = DrainReport()

    # ---- failing sessions: only a failed call or check counts. A run-wide
    # failure is no session's: when no call succeeded (logged out, the
    # service down), or the ledger lock was not taken, nothing is counted.
    if not preview and calling:
        any_call_ok = any(rec.ok for rec in calls.values())
        run_wide = not any_call_ok or (bool(earlier or saved) and not report.drained)
        for s, plan, _halt in to_call:
            res = results.get(plan.session_id)
            key = str(s.path)
            if res is None:
                continue  # not started (the runaway guard): no verdict
            if s.session_id in saved:
                failing.cleared(key)
            elif run_wide:
                continue
            elif res.status != "ok":
                failing.failed(key, s.start_line)
        try:
            failing.save()
        except OSError as exc:
            log(f"run {run_id}: failing-session counts not saved ({exc})")

    # ---- the run record (after the landing: it says what landed)
    failures = Counter(r.error for r in results.values() if r.error)
    counts = {
        "quote_redacted": sum(r.quote_redacted for r in results.values()),
        "cut_to_limit": sum(r.cut_to_limit for r in results.values()),
        "checker_errors": failures.get("checker-error", 0),
        "call_failures": failures.get("call", 0),
        "bad_output": sum(1 for r in results.values() if r.status == "bad-output"),
        "deferred": deferred,
        "flag_modes": dict(Counter(p.flag_mode for _s, p, _h in to_call if p.flag_mode)),
    }
    all_failed = bool(results) and (not ok if preview else not saved)
    run_status = "stopped-ceiling" if stopped else ("failed" if all_failed else "ok")
    run: dict | None = None
    if calling or report.found or report.unreadable:
        extra: dict = {"preview": preview, "counts": counts, "judged_uuids": uuid_info}
        if not preview:
            extra["landed"] = {"lessons": len(result.landed), "folded": len(result.folded),
                               "recurrences": len(result.recurrences), "fires": result.fires}
            extra["waiting"] = report.as_dict()
            if not calling:
                engine_mod.prune_runs(mdir, current=run_id)
        run = engine_mod.run_record(
            run_id=run_id, started_at=started, finished_at=_now_iso(), model=model, method_version=method_version,
            engine=cfg, search_mode=search_mode, status=run_status, plans=plans, results=results, calls=calls,
            extra=extra, saved=None if preview else set(saved), gated=gated,
        )
        folder.put_json("run.json", run)
        summary.update(
            called=run["totals"]["called"], not_run=run["totals"]["not_run"], cost_usd=run["totals"]["cost_usd"],
            lessons=run["totals"]["lessons"], sightings=run["totals"]["sightings"],
            rule_checks=run["totals"]["rule_checks"], drops=dict(run["totals"]["drops"]), counts=counts,
            status=run_status, spine_tokens=sorted(p.spine.tokens_est for _s, p, _h in to_call if p.spine),
            run_folder=f"runs/{run_id}",
        )
    if preview:
        engine_mod.drop_copies(folder.path / "copies")
        log(f"run {run_id}: preview — {summary.get('called', 0)} called, nothing saved or landed")
        return result
    summary["waiting"] = report.as_dict()

    # ---- journal
    (miner_dir() / "miner.last-run").touch()
    waiting = _waiting_counts(report)
    if gated or report.gate_held:
        result.status = "held-gate"
        _journal({**jbase, "status": "held-gate", "pending": gate_seen.get("pending"), "gate": gate_seen.get("gate"),
                  "sessions_ready": len(to_call), "waiting": waiting,
                  "duration_secs": round(time.time() - t0, 1)})
        return result
    if not calling and not report.found and not report.unreadable:
        _journal({**jbase, "status": "idle", "sessions_scanned": 0, "sessions_called": 0,
                  "excluded": len(processed), "deferred_files": deferred,
                  "duration_secs": round(time.time() - t0, 1)})
        log(f"run {run_id}: idle (nothing new to call)")
        return result
    if all_failed:
        result.status = "failed"
    else:
        result.status = "landed-uncommitted" if result.landing_uncommitted else "ok"
    result.sessions_scanned = len(results)
    enriched = [_enrich_near_miss(o) for o in result.outcomes]
    _journal({**jbase, "status": result.status,
              "landing_uncommitted": result.landing_uncommitted,
              "sessions_scanned": len(results),
              "sessions_called": len(results),
              "sessions_failed": sum(1 for r in results.values() if r.status != "ok"),
              "sessions_saved": len(saved),
              "not_run": run["totals"]["not_run"] if run else 0,
              "excluded": len(processed),
              "deferred_files": deferred,
              "cap": cap_for(len(results), home=home),
              "landed": len(result.landed),
              "folded": len(result.folded),
              "recurrences": len(result.recurrences),
              "fires": result.fires,
              "drops": dict(run["totals"]["drops"]) if run else {},
              "outcomes": enriched,
              "near_miss_count": sum(1 for o in enriched if "disposition" in o),
              "corrupt_records": result.corrupt_records,
              # called sessions whose cursor did not move (nothing saved)
              "cursors_held": len(to_call) - len(saved) if calling else 0,
              "waiting": waiting,
              "duration_secs": round(time.time() - t0, 1)})
    log(
        f"run {run_id}: {result.status} — {len(results)} sessions called, {len(saved)} saved, "
        f"{len(result.landed)} landed, {len(result.folded)} folded, {len(result.recurrences)} recurrence(s), "
        f"{result.fires} fire(s), {report.still_waiting} item(s) still waiting"
    )
    return result


def _waiting_counts(report: DrainReport) -> dict:
    """``run.json``'s ``waiting``, the stuck items counted: the journal's."""
    return {**report.as_dict(), "stuck": len(report.stuck)}


def _run_preview(
    home: Path,
    since: str | None,
    t0: float,
    run_id: str,
    base: dict,
    sessions: Sequence[str],
) -> MineResult:
    """``mine run --engine session --preview``: the session engine over the
    named sessions' whole files, or over what tonight's walk would judge.
    Nothing a night run writes is written: no reconcile, no cursor seeding
    or sweep, no landing, no cursor, no judged uuid, no journal row."""
    if sessions:
        slices, missing = _named_slices(home, sessions)
    else:
        if not initialized():
            result = MineResult(status="failed", run_id=run_id)
            result.engine = {"reason": "the miner has no cursors yet; name sessions with --session"}
            return result
        slices, missing = walk(since), []
    sent = (
        provenance.sweep(provenance.sender_dirs([transcripts_root(home)]))
        if slices
        else provenance.SentIndex()
    )
    return _run_session_engine(
        home, slices, sent, mined_scheduled_jobs(home), run_id, base, t0,
        preview=True, no_push=True, missing=missing,
    )


def _commit_landing(
    home: Path, result: MineResult, run_id: str, *, no_push: bool, folds_alone: bool = False
) -> None:
    """The landing commit. **The caller holds the lock** — everything here
    is post-mutation by construction (audit 2026-07-16 round 7).

    H-5 (doc 13 §5): the miner is a producer — it commits its own landings
    (pinned subject) + pushes best-effort. NOTE: this deliberately CHANGES
    the doc-12 §10 adjustment that landings ride autosync — doc 13 H-5
    supersedes it (the ledger home has no watcher, ever).

    BLOCKER 4 (2026-07-16): the miner is the OTHER background committer M3
    put in the ledger (a nightly timer), racing every foreground verb. The
    section is locked (by the caller now, so the FOLD is covered too) and
    the commit is pathspec-scoped.

    A commit failure here is not fatal and not silent: the run's status
    becomes ``landed-uncommitted`` and the NEXT run's reconcile step (or
    `self-learn reconcile`) commits the records (round 7 MAJOR 4). Before
    that they were simply lost — the cursors advance regardless, so
    nothing ever re-mined them.

    ``folds_alone`` (the session engine, R2): a run that only folded
    sightings into pending records commits those too. The digest engine
    keeps its old rule (no landing, no commit; the next run's reconcile
    commits a fold) unchanged."""
    if not result.touched or not (result.landed or (folds_alone and result.folded)):
        return
    subject = f"self-learn: mine {len(result.landed)} candidate(s) ({run_id})"
    if folds_alone and result.folded:
        subject = f"self-learn: mine {len(result.landed)} candidate(s), {len(result.folded)} fold(s) ({run_id})"
    try:
        gitops.stage(home, result.touched)
        gitops.commit(home, subject, paths=result.touched)
    except gitops.GitOpsError as exc:
        result.landing_uncommitted = True
        log(
            f"run {run_id}: LANDING NOT COMMITTED ({exc}) — "
            f"{len(result.landed)} candidate(s) are written but untracked, "
            "and the cursors still advance; the next run reconciles them "
            f"(or run `self-learn reconcile` now against {home})"
        )
        return
    # push OUTSIDE the lock would be better still, but this runs under the
    # caller's lock; push_with_retry is re-entrant, and the miner is a
    # detached timer job whose push blocking a foreground verb for a
    # network timeout is the lesser evil against splitting the section.
    if no_push:
        log(f"run {run_id}: push skipped — --no-push in effect")
        return
    try:
        gitops.push_pending(home)
    except gitops.GitOpsError as exc:
        log(f"run {run_id}: push errored ({exc}) — commit kept")
