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
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import sentinel, telemetry, worker
from .import_common import existing_origins
from .ledger import discover_buckets
from .ledger_ops import LedgerOpsError, create_record, record_title
from .records import GENERALITIES, KINDS, RECORD_ID_RE, Record, RecordError
from .scan import scan as secret_scan

__all__ = [
    "DEFAULT_CAP_MAX",
    "DEFAULT_CAP_PER_SESSION",
    "DEFAULT_PENDING_GATE",
    "MineResult",
    "build_reader_argv",
    "cap_for",
    "digest_transcript",
    "journal_path",
    "last_run_iso",
    "maybe_kick",
    "miner_dir",
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
STALE_AFTER_SECS = 36 * 60 * 60  # R1 layer 3: SessionStart alarm
INVOKE_TIMEOUT_SECS = 15 * 60
JOURNAL_CAP_BYTES = 2_000_000
DEFAULT_MINER_MODEL = "claude-sonnet-5"

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


def walk(since: str | None = None) -> list[SessionSlice]:
    """Every transcript with unread lines. ``since`` (YYYY-MM-DD) is the
    deliberate-backfill override: files modified on/after that date are
    re-read from line 0 (origin dedup makes replays safe)."""
    root = transcripts_root()
    if not root.is_dir():
        return []
    since_ts = None
    if since:
        since_ts = (
            datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp()
        )
    cursors = _load_cursors()
    slices: list[SessionSlice] = []
    for path in sorted(root.glob("*/*.jsonl")):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if since_ts is not None:
            if mtime < since_ts:
                continue
            start = 0
        else:
            start = int(cursors.get(str(path), {}).get("lines", 0))
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        if len(lines) <= start:
            continue
        slices.append(
            SessionSlice(
                path=path,
                session_id=path.stem,
                project=path.parent.name,
                start_line=start,
                lines=lines[start:],
            )
        )
    return slices


def _advance_cursors(slices: list[SessionSlice]) -> None:
    cursors = _load_cursors()
    for s in slices:
        cursors[str(s.path)] = {"lines": s.start_line + len(s.lines)}
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


def digest_transcript(s: SessionSlice) -> str | None:
    """One session's structural digest — or None when the whole session is
    excluded (self-prompt header, M-5) or contributes nothing minable.

    Kept: user text turns (verbatim, clipped), assistant text turns,
    tool-use name + command shape, tool-result status + first/last lines.
    Dropped: tool-result bodies, tool-use payloads, self-learn command
    spans. Annotated: errors, retry clusters.
    """
    out: list[str] = []
    first_user_seen = False
    in_selflearn_span = False
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
                        return None  # the system's own machinery (M-5)
                if _COMMAND_SPAN_RE.search(user_text):
                    in_selflearn_span = True
                    continue
                # A genuine user text turn ends a self-learn command span.
                in_selflearn_span = False
                out.append(f"[user L{lineno}] {_clip(user_text)}")
            for block in results:
                if in_selflearn_span:
                    continue
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
            if in_selflearn_span:
                continue
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
        return None

    clusters = [
        f"[retry-cluster {shape} ×{uses}, {errs} error(s)]"
        for shape, (uses, errs) in sorted(command_counts.items())
        if uses >= 3 and errs >= 1
    ]
    header = f"=== session {s.session_id} project {s.project} ==="
    body = "\n".join(clusters + out)
    if len(body) > MAX_DIGEST_CHARS:
        body = body[:MAX_DIGEST_CHARS] + "\n…[session digest clipped]"
    return f"{header}\n{body}"


# ----------------------------------------------- Phase 2: the reader pass


def spool_dir() -> Path:
    d = miner_dir() / "spool"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_reader_settings() -> Path:
    """Write scope = the CACHE spool only (Edit rule family — the
    live-verified syntax; the repo is entirely out of reach)."""
    path = miner_dir() / "miner.settings.json"
    path.write_text(
        json.dumps(
            {"permissions": {"allow": [f"Edit(/{spool_dir()}/**)"]}}, indent=2
        ),
        encoding="utf-8",
    )
    return path


def build_reader_argv(prompt: str, settings_path: Path) -> list[str]:
    return [
        "claude",
        "-p",
        prompt,
        "--model",
        miner_model(),
        "--allowedTools",
        worker.ALLOWED_TOOLS,
        "--disallowedTools",
        worker.DISALLOWED_TOOLS,
        "--settings",
        str(settings_path),
    ]


def _rubric(home: Path) -> tuple[str, str]:
    """(text, version). Version comes from a `rubric-version:` marker."""
    path = (
        home
        / "plugins/self-learn/skills/self-learn/references/mining-rubric.md"
    )
    if not path.is_file():
        return ("(rubric missing — mine conservatively: corrections, "
                "verified gotchas, stated standing preferences only)"), "none"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"rubric-version:\s*(\S+)", text)
    return text, (m.group(1) if m else "unversioned")


def _ledger_index(home: Path) -> str:
    """Compact all-status index the reader reconciles against (doc 12 §5:
    in-context comparison beats a vector index at this ledger size)."""
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
                rows.append(
                    f"- {r.id} [{r.status}] ({r.scope}): {record_title(r)}"
                )
    return "\n".join(rows) if rows else "(ledger is empty)"


def _canon_index(home: Path) -> str:
    """Routed rules for fire observation: id + title."""
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
correct and common answer.

=== MINING RUBRIC ===
{rubric}

=== LEDGER INDEX (reconcile against this) ===
{ledger}

=== ROUTED RULES (observe fires against these) ===
{canon}

=== SESSION DIGESTS ===
{digests}
"""


def _compose_prompt(home: Path, digests: list[str], output_path: Path) -> str:
    return _PROMPT_TEMPLATE.format(
        output_path=output_path,
        rubric=_rubric(home)[0],
        ledger=_ledger_index(home),
        canon=_canon_index(home),
        digests="\n\n".join(digests),
    )


def _invoke_reader(home: Path, prompt: str) -> Path | None:
    """Run the contained reader; return the output file path if it exists.
    Split out so tests shim the model with a fake writer."""
    out_path = spool_dir() / OUTPUT_BASENAME
    out_path.unlink(missing_ok=True)
    argv = build_reader_argv(prompt, write_reader_settings())
    try:
        proc = subprocess.run(
            argv,
            cwd=str(home),
            capture_output=True,
            text=True,
            timeout=INVOKE_TIMEOUT_SECS,
        )
        if proc.returncode != 0:
            log(
                f"run: claude exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout)[:400]}"
            )
    except FileNotFoundError:
        log("run: claude CLI not found on PATH")
        return None
    except subprocess.TimeoutExpired:
        log(f"run: claude timed out after {INVOKE_TIMEOUT_SECS}s")
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
    status: str  # ok | idle | held-gate | failed | disabled | busy
    run_id: str = ""
    sessions_scanned: int = 0
    landed: list[str] = field(default_factory=list)
    folded: list[str] = field(default_factory=list)
    recurrences: list[str] = field(default_factory=list)
    fires: int = 0
    dropped: int = 0
    outcomes: list[dict] = field(default_factory=list)


def _outcome(result: MineResult, origin: str, outcome: str, **extra) -> None:
    result.outcomes.append({"origin": origin, "outcome": outcome, **extra})


def _find_record(home: Path, rid: str) -> tuple[Record, str] | None:
    """(record, status-dir) across all buckets, or None."""
    if not rid or not RECORD_ID_RE.match(rid):
        return None
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            path = bucket.path / sub / f"{rid}.md"
            if path.is_file():
                try:
                    return Record.from_path(path), sub
                except RecordError:
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
    """The SKILL directory must exist — not the bucket (which only exists
    after a first capture; create_record creates it on demand)."""
    name = scope.partition(":")[2]
    if not name or "/" in name or name.startswith("."):
        return False
    return any(p.is_dir() for p in home.glob(f"plugins/*/skills/{name}"))


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
            kind = "surface-rule"
        record = Record.create(
            type="behavior",
            scope=scope,
            source="session",
            kind=kind,
            trigger=str(cand.get("trigger") or "").strip(),
            instruction=str(cand.get("instruction") or "").strip(),
        )
    elif rtype == "knowledge":
        record = Record.create(
            type="knowledge",
            scope=scope,
            source="session",
            fact=str(cand.get("fact") or "").strip(),
            context=(str(cand.get("context")).strip() or None)
            if cand.get("context")
            else None,
        )
    else:
        raise RecordError(f"bad type {rtype!r}")
    if cand.get("verified"):
        record.set_verified(True, how=(cand.get("verified_how") or None))
    if cand.get("incident_cost"):
        record.set_incident_cost(str(cand["incident_cost"]))
    generality = cand.get("generality")
    if generality in GENERALITIES:
        record.set_generality(generality)
    return record


def _scan_candidate(record: Record, cand: dict) -> list:
    texts = [record.body]
    for key in ("quote", "verified_how", "incident_cost", "why_durable"):
        if cand.get(key):
            texts.append(str(cand[key]))
    return [h for t in texts for h in secret_scan(t)]


def _reconcile_and_land(
    home: Path, parsed: dict, result: MineResult, cap: int
) -> None:
    origins = existing_origins(home)
    candidates = parsed.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        session_id = str(cand.get("session") or "unknown")
        line = cand.get("line")
        origin = f"transcript:{session_id}#L{line if line else '?'}"
        if origin in origins:
            _outcome(result, origin, "skipped-known-origin")
            continue

        # --- match-claim verification (never trust the model's claim raw)
        match = cand.get("match") or {}
        claimed_id = match.get("record") if isinstance(match, dict) else None
        target = _find_record(home, str(claimed_id)) if claimed_id else None
        if claimed_id and target is None:
            _outcome(
                result, origin, "match-claim-invalid", claimed=str(claimed_id)
            )
            # demote to no-match; fall through to landing
        if target is not None:
            record, sub = target
            if sub == "pending":
                entry = {"session": session_id, "ts": _now_iso(), "origin": origin}
                if cand.get("quote") and not secret_scan(str(cand["quote"])):
                    entry["quote"] = str(cand["quote"])
                record.append_evidence(entry)
                pending_path = None
                for bucket in discover_buckets(home):
                    p = bucket.path / "pending" / f"{record.id}.md"
                    if p.is_file():
                        pending_path = p
                        break
                if pending_path is not None:
                    record.write(pending_path)
                    result.folded.append(record.id)
                    _outcome(result, origin, "folded", record=record.id)
                    origins.add(origin)
                    continue
            elif record.status == "routed":
                telemetry.spool_quiet(
                    "recurrence-suspect",
                    record=record.id,
                    origin=origin,
                    basis="miner-match",
                )
                result.recurrences.append(record.id)
                _outcome(result, origin, "recurrence", record=record.id)
                continue
            elif record.status == "rejected":
                n = _rejected_counter_bump(record.id, origin)
                if n < 0 or n < REJECTED_RESURFACE_SIGHTINGS:
                    _outcome(
                        result,
                        origin,
                        "dropped-rejected",
                        record=record.id,
                        sightings=max(n, 0),
                    )
                    continue
                cand = dict(cand)
                cand["why_durable"] = (
                    f"previously rejected as {record.id}; sighted "
                    f"{n}× since — resurfaced per doc 12 §8 Q4. "
                    + str(cand.get("why_durable") or "")
                ).strip()
                _rejected_mark_landed(record.id)
                # falls through to landing
            else:
                _outcome(result, origin, "skipped-resolved", record=record.id)
                continue

        # --- landing (cap-checked, scan-gated)
        if len(result.landed) >= cap:
            result.dropped += 1
            _outcome(result, origin, "dropped-cap")
            continue
        try:
            record = _build_record(home, cand)
        except RecordError as exc:
            _outcome(result, origin, "dropped-invalid", reason=str(exc)[:200])
            continue
        hits = _scan_candidate(record, cand)
        if hits:
            _outcome(result, origin, "scan-refused", rule=hits[0].rule)
            log(f"run: candidate {origin} refused by secret scan ({hits[0].rule})")
            continue
        entry = {"session": session_id, "ts": _now_iso(), "origin": origin}
        if cand.get("quote"):
            entry["quote"] = str(cand["quote"])
        record.append_evidence(entry)
        try:
            path = create_record(home, record)
        except LedgerOpsError as exc:
            _outcome(result, origin, "dropped-land-failed", reason=str(exc)[:200])
            continue
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

    fires = parsed.get("fires") or []
    if isinstance(fires, list):
        for fire in fires:
            if not isinstance(fire, dict):
                continue
            rid = str(fire.get("record") or "")
            outcome = str(fire.get("outcome") or "")
            if not RECORD_ID_RE.match(rid) or outcome not in (
                "complied",
                "violated",
            ):
                continue
            if _find_record(home, rid) is None:
                continue
            telemetry.spool_quiet(
                "fire",
                record=rid,
                origin=f"transcript:{fire.get('session')}#L{fire.get('line')}",
                outcome=outcome,
            )
            result.fires += 1


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


# ------------------------------------------------------- watchdog (R1 L2)


def _spawn_run(home: Path) -> int:
    with open(miner_dir() / "miner.log", "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "self_learn.cli", "mine", "run",
             "--trigger", "kick"],
            cwd=str(home),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def maybe_kick(home: Path | str) -> str:
    """Verb-invocation watchdog: spawn a detached run when the last one is
    >24 h old. Returns disabled | fresh | busy | spawned."""
    if (
        os.environ.get("SELF_LEARN_MINER") == "0"
        or os.environ.get("SELF_LEARN_MINER_AUTOKICK") == "0"
    ):
        return "disabled"
    if _last_run_age_secs() <= KICK_AFTER_SECS:
        return "fresh"
    with open(miner_dir() / "miner.spawn.lock", "w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "busy"
        try:
            pid = _spawn_run(Path(home))
            log(f"watchdog: last run >24h — spawned run (pid {pid})")
            return "spawned"
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ------------------------------------------------------------------ run


def run(home: Path | str, *, trigger: str = "manual", since: str | None = None) -> MineResult:
    home = Path(home)
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

        rubric_version = _rubric(home)[1]
        base = {
            "ts": _now_iso(),
            "run_id": run_id,
            "trigger": trigger,
            "rubric_version": rubric_version,
            "model": miner_model(),
        }

        slices = walk(since)
        digests: list[str] = []
        digested: list[SessionSlice] = []
        excluded = 0
        total_chars = 0
        deferred_files = 0
        for s in slices:
            digest = digest_transcript(s)
            if digest is None:
                excluded += 1
                digested.append(s)  # nothing minable — cursor still advances
                continue
            if total_chars + len(digest) > MAX_PROMPT_DIGESTS_CHARS:
                deferred_files += 1  # stays behind the cursor for next run
                continue
            total_chars += len(digest)
            digests.append(digest)
            digested.append(s)

        result = MineResult(
            status="idle", run_id=run_id, sessions_scanned=len(digests)
        )

        if not digests:
            _advance_cursors(digested)
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
        prompt = _compose_prompt(home, digests, out_path)
        artifact = _invoke_reader(home, prompt)
        if artifact is None:
            result.status = "failed"
            _journal({**base, "status": "failed",
                      "reason": "reader produced no output",
                      "sessions_scanned": len(digests),
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
                      "duration_secs": round(time.time() - t0, 1)})
            return result

        cap = cap_for(len(digests))
        hold = sentinel.hold()
        try:
            _reconcile_and_land(home, parsed, result, cap)
        finally:
            hold.release()

        _advance_cursors(digested)
        (miner_dir() / "miner.last-run").touch()
        result.status = "ok"
        _journal({**base, "status": "ok",
                  "sessions_scanned": len(digests),
                  "excluded": excluded,
                  "deferred_files": deferred_files,
                  "cap": cap,
                  "landed": len(result.landed),
                  "folded": len(result.folded),
                  "recurrences": len(result.recurrences),
                  "fires": result.fires,
                  "outcomes": result.outcomes,
                  "duration_secs": round(time.time() - t0, 1)})
        log(
            f"run {run_id}: ok — {len(result.landed)} landed, "
            f"{len(result.folded)} folded, {len(result.recurrences)} "
            f"recurrence(s), {result.fires} fire(s)"
        )

        try:
            telemetry.flush(home)
        except telemetry.TelemetryError as exc:
            log(f"run {run_id}: telemetry flush refused ({exc})")

        if result.landed:
            worker.kick(home)  # analyzed before any human sees the card
        return result
    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fh.close()
