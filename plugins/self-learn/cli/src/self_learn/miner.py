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
test suite sets it globally in conftest).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import gitops, sentinel, telemetry, worker
from . import reconcile as reconcile_mod
from .hosts import load_hosts
from .import_common import existing_origins
from .ledger import discover_buckets, home_state, home_state_message
from .ledger_ops import LedgerOpsError, create_record, record_title
from .records import GENERALITIES, KINDS, RECORD_ID_RE, Record, RecordError
from .scan import scan as secret_scan

__all__ = [
    "CanaryError",
    "DEFAULT_CAP_MAX",
    "DEFAULT_CAP_PER_SESSION",
    "DEFAULT_PENDING_GATE",
    "MAX_NEARMISS_SNIPPET_CHARS",
    "MineResult",
    "build_reader_argv",
    "canaries_path",
    "cap_for",
    "digest_transcript",
    "journal_path",
    "last_run_iso",
    "maybe_kick",
    "miner_dir",
    "plant_canary",
    "read_canaries_summary",
    "read_journal",
    "run",
    "walk",
    "write_reader_settings",
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
INVOKE_TIMEOUT_SECS = 15 * 60
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
MAX_TEXT_CHARS = 2_000  # per kept turn
MAX_DIGEST_CHARS = 60_000  # per session digest
MAX_PROMPT_DIGESTS_CHARS = 400_000  # per run; overflow waits for next run

#: Sessions whose FIRST user turn opens with one of these are the
#: system's own machinery — never mined (M-5).
SELF_PROMPT_HEADERS = (
    "You are the self-learn routing analyst worker.",
    "You are the self-learn transcript miner.",
)
#: Self-learn command spans inside otherwise-minable sessions (M-5).
_COMMAND_SPAN_RE = re.compile(r"<command-name>/?self-learn:")

OUTPUT_BASENAME = "mine-output.json"


def miner_dir() -> Path:
    d = worker.cache_dir() / "miner"
    d.mkdir(parents=True, exist_ok=True)
    return d


def journal_path() -> Path:
    return miner_dir() / "journal.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    path = miner_dir() / "miner.log"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{_now_iso()} {message}\n")
    worker._truncate_oldest(path, worker.LOG_CAP_BYTES)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def cap_for(sessions_scanned: int) -> int:
    """Use-scaled landing cap (§8 Q3): min(per-session × scanned, max)."""
    per = _int_env("SELF_LEARN_MINE_CAP_PER_SESSION", DEFAULT_CAP_PER_SESSION)
    cap_max = _int_env("SELF_LEARN_MINE_CAP_MAX", DEFAULT_CAP_MAX)
    return min(per * max(sessions_scanned, 1), cap_max)


def pending_gate() -> int:
    return _int_env("SELF_LEARN_MINE_PENDING_GATE", DEFAULT_PENDING_GATE)


def miner_model() -> str:
    return os.environ.get("SELF_LEARN_MINER_MODEL") or DEFAULT_MINER_MODEL


def transcripts_root() -> Path:
    raw = os.environ.get("SELF_LEARN_TRANSCRIPTS_DIR")
    return Path(raw).expanduser() if raw else Path("~/.claude/projects").expanduser()


def last_run_iso() -> str | None:
    try:
        mtime = (miner_dir() / "miner.last-run").stat().st_mtime
    except FileNotFoundError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _last_run_age_secs() -> float:
    try:
        return time.time() - (miner_dir() / "miner.last-run").stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def stale() -> bool:
    """SessionStart alarm predicate (R1 layer 3): no completed run in 36 h.
    A missing marker counts as infinitely old — self-healing, because the
    verb watchdog spawns a run on the next CLI use, which touches the
    marker even when idle. A deliberately disabled miner never alarms."""
    if os.environ.get("SELF_LEARN_MINER") == "0":
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


def initialized() -> bool:
    return bool(_load_cursors().get("__initialized__"))


def initialize_cursors() -> int:
    """First-activation forward-only pin (doc 12 §8 R2, audit B2): seed
    every EXISTING transcript's cursor at its current end so night one
    mines nothing — history is reachable only through the deliberate
    ``--since`` backfill. Files containing self-learn machinery markers
    anywhere in their existing history are halted outright (M-5: an
    in-flight review/worker session's tail must not become minable just
    because the cursor was seeded past its header). Returns the number of
    files seeded."""
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
            if _contains_self_learn("\n".join(lines)):
                entry["halt"] = True
            cursors[str(path)] = entry
            seeded += 1
    cursors["__initialized__"] = _now_iso()
    _save_cursors(cursors)
    return seeded


def walk(since: str | None = None) -> list[SessionSlice]:
    """Every transcript with unread COMPLETE lines, oldest-modified first.
    ``since`` (YYYY-MM-DD) is the deliberate-backfill override: files
    modified on/after that date are re-read from line 0 (origin dedup
    makes landing replays safe). Halted files (self-learn machinery,
    M-5) are skipped without reading."""
    root = transcripts_root()
    if not root.is_dir():
        return []
    since_ts = None
    if since:
        since_ts = (
            datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp()
        )
    cursors = _load_cursors()
    candidates: list[tuple[float, Path, int, int]] = []
    for path in sorted(root.glob("*/*.jsonl")):
        entry = cursors.get(str(path), {})
        try:
            st = path.stat()
        except OSError:
            continue
        if since_ts is not None:
            if st.st_mtime < since_ts:
                continue
            start = 0
        else:
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


def _blocks(message: dict) -> list[dict]:
    content = (message or {}).get("content")
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


def digest_transcript(s: SessionSlice) -> tuple[str | None, bool]:
    """(digest-or-None, halt) for one session slice.

    Kept: user text turns (verbatim, clipped), assistant text turns,
    tool-use name + command shape, tool-result status + first/last lines.
    Dropped: tool-result bodies and tool-use payloads.

    halt=True means the REST of this session — including future appends —
    must never be mined; the caller persists it into the cursor. Two
    halters (M-5, tightened by audit 2026-07-15): a self-prompt header
    (the system's own claude -p machinery), and ANY self-learn command
    tag — the old "span ends at the next genuine user turn" rule
    collapsed on the first review reply, feeding every card's lesson text
    (which the reader would dutifully match against the ledger) back into
    the miner as fake sightings. Recall loss from over-exclusion is cheap;
    evidence corruption is not.
    """
    out: list[str] = []
    halt = False
    first_user_seen = False
    command_counts: dict[str, list[int]] = {}  # norm shape -> [uses, errors]
    last_tool_shape: dict[str, str] = {}  # tool_use id -> display shape
    last_tool_norm: dict[str, str] = {}  # tool_use id -> norm shape

    for offset, raw in enumerate(s.lines):
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
            texts: list[str] = []
            results: list[dict] = []
            for block in _blocks(message):
                btype = block.get("type")
                if btype == "text":
                    texts.append(str(block.get("text", "")))
                elif btype == "tool_result":
                    results.append(block)
            user_text = "\n".join(t for t in texts if t.strip())
            if user_text.strip():
                if not first_user_seen:
                    first_user_seen = True
                    if any(
                        user_text.strip().startswith(h)
                        for h in SELF_PROMPT_HEADERS
                    ):
                        return None, True  # own machinery: halt forever
                if _COMMAND_SPAN_RE.search(user_text):
                    halt = True
                    break  # everything after the tag is off-limits
                out.append(f"[user L{lineno}] {_clip(user_text)}")
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
                        out.append(f"[assistant L{lineno}] {_clip(text)}")
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
    if len(body) > MAX_DIGEST_CHARS:
        body = body[:MAX_DIGEST_CHARS] + "\n…[session digest clipped]"
    return f"{header}\n{body}", halt


# ----------------------------------------------- Phase 2: the reader pass


def spool_dir() -> Path:
    d = miner_dir() / "spool"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_reader_settings() -> Path:
    """Write scope = the CACHE spool only (Edit rule family — the
    live-verified syntax; the repo is entirely out of reach). Pins
    ``defaultMode: "default"`` — without it, the session inherits the
    host's global ``permissions.defaultMode`` (which may be
    ``bypassPermissions``), voiding the scope above."""
    path = miner_dir() / "miner.settings.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [f"Edit(/{spool_dir()}/**)"],
                    "defaultMode": "default",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


#: The miner's reader gets NO filesystem tools (audit 2026-07-15,
#: injection hardening): unlike the worker — which must open record
#: files — the reader's entire evidence base rides in the prompt, and
#: transcript digests are attacker-influenceable text. Write stays
#: available only through the settings-file Edit rule family, scoped to
#: the cache spool.
READER_DISALLOWED_TOOLS = worker.DISALLOWED_TOOLS + ",Read,Grep,Glob"


def build_reader_argv(settings_path: Path) -> list[str]:
    """The prompt is deliberately NOT in argv: Linux caps one argv element
    at 128 KiB and a busy night's digests exceed it (audit B1, verified
    E2BIG live) — the prompt goes to the reader on stdin."""
    return [
        "claude",
        "-p",
        "--model",
        miner_model(),
        "--disallowedTools",
        READER_DISALLOWED_TOOLS,
        "--settings",
        str(settings_path),
    ]


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
                except RecordError:
                    continue
                except UnicodeDecodeError:
                    if corrupt is not None:
                        corrupt.append(path)
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
            except RecordError:
                continue
            except UnicodeDecodeError:
                if corrupt is not None:
                    corrupt.append(path)
                continue
            if r.status == "routed":
                rows.append(f"- {r.id} ({r.scope}): {record_title(r)}")
    return "\n".join(rows) if rows else "(no routed rules yet)"


_PROMPT_TEMPLATE = """You are the self-learn transcript miner. Below are structural digests of
recent Claude Code sessions (tool-result bodies removed; [user]/
[assistant] turns and error/retry annotations kept, each tagged with its
transcript line). Your job: find DURABLE lessons — user corrections,
verified gotchas, stated standing preferences, repeated friction — and
observations of routed rules firing. Apply the mining rubric strictly;
when in doubt, do not emit. A one-off task instruction is never a lesson.

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
      "outcome": "complied" | "violated"}}
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
    (a hung node child must not outlive the 15-minute budget)."""
    out_path = spool_dir() / OUTPUT_BASENAME
    out_path.unlink(missing_ok=True)
    argv = build_reader_argv(write_reader_settings())
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(home),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            output, _ = proc.communicate(prompt, timeout=INVOKE_TIMEOUT_SECS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
            log(f"run: claude timed out after {INVOKE_TIMEOUT_SECS}s")
            return None
        if proc.returncode != 0:
            log(f"run: claude exited {proc.returncode}: {(output or '')[:400]}")
    except FileNotFoundError:
        log("run: claude CLI not found on PATH")
        return None
    except OSError as exc:  # audit B1: E2BIG-class failures must journal,
        log(f"run: reader invocation failed ({exc})")  # never crash the run
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
    #: failed, cursors advanced anyway — never re-mined, never published)
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
    path.write_text(json.dumps(data, indent=0, sort_keys=True), encoding="utf-8")
    return len(sightings)


def _rejected_mark_landed(rid: str) -> None:
    path = miner_dir() / "rejected-sightings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[rid] = "landed"
    path.write_text(json.dumps(data, indent=0, sort_keys=True), encoding="utf-8")


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
#: suspicion, not a similarity metric. One constant, not a literal typed
#: twice: THE CROSSOVER and THE BACKFILL share it, so they can never
#: drift apart on the label.
_FIRE_VIOLATED_BASIS = "fire-violated"


def _event_seen(
    home: Path,
) -> tuple[set[tuple[str, str, str]], list[tuple[str, str]]]:
    """(kind, record, origin) for fire/recurrence-suspect events —
    replay dedup (audit: crash-replay and the DOCUMENTED --since replay
    duplicated both classes; nonces make byte-dedup useless).

    Also returns ``violated_fires`` — ``(record, origin)`` pairs drawn
    from tracked ``fire`` events with ``outcome == "violated"``, in
    ``read_events`` (ts-ordered) order. This is THE BACKFILL's source
    list (U-recur spec §4 decision 4): one ``read_events`` pass serves
    both purposes, no second read. Telemetry lines are untrusted input
    (11 §4.2): a row whose ``record``/``origin`` is not a string is
    skipped, and ``record`` is re-validated against :data:`RECORD_ID_RE`
    — never a crash, never a guessed id."""
    seen: set[tuple[str, str, str]] = set()
    violated_fires: list[tuple[str, str]] = []
    for e in telemetry.read_events(home):
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
    ``recurrence-from-fire`` journal row. THE CROSSOVER (in the fires
    loop) and THE BACKFILL (below) both call this — two copies of this
    dedupe logic is how the two rules drift apart. A no-op when the key
    is already present; that is the whole dedupe contract, live or
    backfilled."""
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
            project_path = Path(cwd)
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
                or outcome not in ("complied", "violated")
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
            # THE CROSSOVER (U-recur spec §2 / §4 decision 9): placement
            # is load-bearing — AFTER the fire's own dedupe key is added
            # and the counter incremented, never before the dedupe
            # `continue` above. That placement is exactly what makes THE
            # BACKFILL below structurally necessary (spec §2.2): a fire
            # already in the tracked plane never reaches this line again.
            if outcome == "violated":
                _raise_recurrence_suspect(
                    result, seen_events, rid, origin, _FIRE_VIOLATED_BASIS
                )

    # THE BACKFILL (U-recur spec §2.2): structurally forced, not a
    # nicety. THE CROSSOVER above can only ever reach a `violated` fire
    # reported by THIS run's reader — a fire already sitting in the
    # tracked plane is deduped out by the `key in seen_events` check
    # before reaching the crossover, so a forward-only build ships
    # green and leaves `recurrence-suspect` at zero on the real ledger
    # forever. This mirrors the live crossover's `routed` guard EXACTLY,
    # including its `found is None` half (AC7): an unbounded pass over
    # an append-only telemetry plane must never raise on one
    # unresolvable row — run()'s outer handler would turn that into
    # `status: failed` and the offending row would never go away,
    # wedging every future nightly run.
    for rid, origin in violated_fires:
        found = _find_record(home, rid)
        if found is None or found[0].status != "routed":
            continue
        _raise_recurrence_suspect(result, seen_events, rid, origin, _FIRE_VIOLATED_BASIS)


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
    Returns disabled | fresh | cooling | busy | spawned.

    ``no_push`` is the INVOKING verb's flag, passed explicitly (BLOCKER
    D). This watchdog ticks before every command except `mine`, so any
    ``--no-push`` verb can spawn a miner; the spawned run must inherit the
    policy or the flag is a lie the moment the watchdog fires."""
    if (
        os.environ.get("SELF_LEARN_MINER") == "0"
        or os.environ.get("SELF_LEARN_MINER_AUTOKICK") == "0"
    ):
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
) -> MineResult:
    """``no_push=None`` reads the process boundary once
    (:func:`worker.no_push_requested`) and threads the answer as a
    parameter from there (BLOCKER D)."""
    home = Path(home)
    if no_push is None:
        no_push = worker.no_push_requested()
    if os.environ.get("SELF_LEARN_MINER") == "0":
        return MineResult(status="disabled")
    t0 = time.time()
    run_id = uuid.uuid4().hex[:8]

    lock_fh = open(miner_dir() / "miner.lock", "w", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return MineResult(status="busy")
        (miner_dir() / "miner.last-attempt").touch()  # watchdog cool-down

        base = {
            "ts": _now_iso(),
            "run_id": run_id,
            "trigger": trigger,
            "rubric_version": _rubric()[1],
            "model": miner_model(),
        }

        # BLOCKER 11 (audit 2026-07-16): the nightly miner resolves the
        # home too — and a unit resolving a DIFFERENT home than the shell
        # is the live failure mode. Mining into the void would land
        # candidates nobody ever sees; fail loudly in the log AND the
        # journal (`mine status` is the surface that notices).
        state = home_state(home)
        if state in ("missing", "not-a-repo"):
            reason = home_state_message(state, home)
            log(f"run {run_id}: REFUSED — {reason}")
            _journal({**base, "status": "failed", "reason": reason[:300],
                      "duration_secs": round(time.time() - t0, 1)})
            return MineResult(status="failed", run_id=run_id)

        try:
            return _run_locked(home, since, t0, run_id, base, no_push=no_push)
        except Exception as exc:  # noqa: BLE001 — A1: EVERY run journals,
            # even a crashed one (audit B1: an uncaught error previously
            # left no journal entry at all — invisible to mine status).
            log(f"run {run_id}: CRASHED — {exc}\n{traceback.format_exc()}")
            _journal({**base, "status": "failed",
                      "reason": f"crashed: {exc}"[:300],
                      "duration_secs": round(time.time() - t0, 1)})
            return MineResult(status="failed", run_id=run_id)
    finally:
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
        if healed.healed:
            log(
                f"run {run_id}: reconciled {len(healed.committed)} orphaned "
                f"path(s) from an earlier run @ {healed.sha[:7]}"
            )
        for line in healed.blocked:
            log(f"run {run_id}: reconcile left a half-committed change: {line}")
    except gitops.GitOpsError as exc:
        log(f"run {run_id}: reconcile step skipped ({exc})")

    # First-activation forward-only pin (§8 R2, audit B2): seed cursors at
    # the current end of every existing transcript and stop — history is
    # reachable only through the deliberate --since backfill.
    if not initialized():
        seeded = initialize_cursors()
        (miner_dir() / "miner.last-run").touch()
        _journal({**base, "status": "initialized", "files_seeded": seeded,
                  "duration_secs": round(time.time() - t0, 1)})
        log(f"run {run_id}: initialized forward-only ({seeded} files seeded)")
        return MineResult(status="initialized", run_id=run_id)

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
    for s in slices:
        digest, halt = digest_transcript(s)
        if digest is None:
            excluded += 1
            processed.append((s, halt))  # nothing minable — cursor advances
            continue
        if total_chars + len(digest) > MAX_PROMPT_DIGESTS_CHARS:
            deferred_files += 1  # stays behind the cursor for next run
            continue
        total_chars += len(digest)
        digests.append(digest)
        processed.append((s, halt))
        digested[s.session_id] = halt
        cwd = _slice_cwd(s)
        if cwd:
            cwds[s.session_id] = cwd

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
    gate = pending_gate()
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
            log(f"run {run_id}: ledger record {p} not readable as UTF-8 — "
                "excluded from the reconciliation index")
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

    cap = cap_for(len(digests))
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
        with gitops.commit_lock(home):
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
            telemetry.flush(home)
        except telemetry.TelemetryError as exc:
            log(f"run {run_id}: telemetry flush refused ({exc})")

    if result.landed:
        worker.kick(home)  # analyzed before any human sees the card
    return result


def _commit_landing(
    home: Path, result: MineResult, run_id: str, *, no_push: bool
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
    nothing ever re-mined them."""
    if not (result.landed and result.touched):
        return
    try:
        gitops.stage(home, result.touched)
        gitops.commit(
            home,
            f"self-learn: mine {len(result.landed)} candidate(s) ({run_id})",
            paths=result.touched,
        )
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
        gitops.push_if_remote(home)
    except gitops.GitOpsError as exc:
        log(f"run {run_id}: push errored ({exc}) — commit kept")
