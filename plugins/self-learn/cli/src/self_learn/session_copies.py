"""Copies of the model sessions self-learn runs (2026-09-28).

The user's words: "go ahead and just capture everything." Every model
session self-learn starts through the invocation seam (the miner's
reader, the worker and its repair round, the analyst, the steward and its
repair turns, the overseer's phases) is a Claude Code session, and Claude
Code writes its own transcript of it to
``<claude dir>/projects/<project dir>/<session id>.jsonl`` (plus
``<session id>/subagents/agent-*.jsonl`` beside it when the session ran
subagents). Claude Code deletes those files after its cleanup period.
After each session ends -- finished or failed -- :func:`capture` copies
them into self-learn's CACHE::

    <cache>/sessions/<surface>/<group>/<session id>.jsonl
    <cache>/sessions/<surface>/<group>/<session id>/subagents/agent-*.jsonl

``<group>`` is the producer's run id when it names one
(`SessionSpec.transcript_group`: the steward and the overseer), else the
seam's own per-session run id (the one in the name of that session's
event log).

Never the ledger: a transcript holds raw tool output. What the ledger and
the journals get is :func:`capture`'s small record -- the session id, the
copy's path RELATIVE to the cache directory (an absolute path trips the
secret scan's high-entropy rule on the ``home-<hash>`` segment, measured),
its size, and counts: transcript entries by ``type`` and assistant content
blocks by block ``type``. Counts only, never text.

Nothing self-learn builds for a model -- a prompt, a brief, a blind view,
an evidence pack -- reads this directory
(`tests/test_session_copies.py`).

A copy that fails is a record with an ``error``, never an exception: it
never fails the session or the run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from . import settings, worker

__all__ = [
    "SETTING",
    "SUMMARIZED_THINKING",
    "capture",
    "claude_projects_dir",
    "enabled",
    "sessions_dir",
]

#: The one registry switch for both halves of this feature.
SETTING = "sdk.capture_sessions"

#: The SDK option every self-learn session gets while :data:`SETTING` is on
#: (claude-agent-sdk 0.2.134's ``ClaudeAgentOptions.thinking``).
SUMMARIZED_THINKING: dict[str, str] = {"type": "adaptive", "display": "summarized"}

#: A session id or group name is used as a path component: letters,
#: digits, dot, underscore and dash only, and never a bare dot or two.
_SAFE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")


def enabled(home: Path | str) -> bool:
    """:data:`SETTING`, resolved against the ledger *home*. A setting that
    cannot be read counts as on -- the registry default."""
    try:
        value, _source = settings.resolve_setting(home, settings.by_name(SETTING))
    except Exception:  # noqa: BLE001 -- a settings problem never fails a session
        return True
    return bool(value)


def sessions_dir(home: Path | str) -> Path:
    """Where the copies live: the ledger home's cache namespace, never the
    ledger itself."""
    return worker.cache_dir(home) / "sessions"


def claude_projects_dir() -> Path:
    """Where Claude Code writes its transcripts: ``SELF_LEARN_CLAUDE_DIR``
    (tests), else ``CLAUDE_CONFIG_DIR``, else ``~/.claude`` -- then
    ``projects``."""
    base = os.environ.get("SELF_LEARN_CLAUDE_DIR") or os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(base) if base else Path("~/.claude").expanduser()
    return root / "projects"


def _group_name(*candidates: str | None) -> str:
    for candidate in candidates:
        text = (candidate or "").strip()
        if not text:
            continue
        text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")
        if text and _SAFE.match(text):
            return text
    return "unlabelled"


def _find(projects: Path, session_id: str, cwd: Path | str | None) -> Path | None:
    """The top-level ``<session id>.jsonl``: first in the directory Claude
    Code names after *cwd* (every character that is not a letter or digit
    becomes ``-``), then in every project directory."""
    name = f"{session_id}.jsonl"
    if cwd is not None:
        try:
            guess = projects / re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))
        except OSError:
            guess = None
        if guess is not None and (guess / name).is_file():
            return guess / name
    if not projects.is_dir():
        return None
    for project in sorted(projects.iterdir()):
        candidate = project / name
        if candidate.is_file():
            return candidate
    return None


def _counts(path: Path) -> tuple[dict[str, int], dict[str, int]]:
    """Transcript entries by ``type`` and assistant content blocks by block
    ``type``. A line that does not parse counts under ``unparsed``."""
    entries: Counter[str] = Counter()
    blocks: Counter[str] = Counter()
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                entries["unparsed"] += 1
                continue
            if not isinstance(entry, dict):
                entries["unparsed"] += 1
                continue
            kind = entry.get("type")
            entries[kind if isinstance(kind, str) else "untyped"] += 1
            if kind != "assistant":
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                for block in content:
                    block_type = block.get("type") if isinstance(block, dict) else None
                    blocks[block_type if isinstance(block_type, str) else "untyped"] += 1
    return dict(sorted(entries.items())), dict(sorted(blocks.items()))


def capture(
    *,
    home: Path | str,
    surface: str,
    session_id: str | None,
    group: str | None,
    fallback_group: str,
    cwd: Path | str | None,
) -> dict[str, Any] | None:
    """Copy one ended session's transcript into the cache and describe the
    copy. ``None`` when :data:`SETTING` is off (nothing is copied). Never
    raises: a failure is a record whose ``error`` says what went wrong."""
    try:
        if not enabled(home):
            return None
        return _capture(
            home=home, surface=surface, session_id=session_id,
            group=_group_name(group, fallback_group), cwd=cwd,
        )
    except Exception as exc:  # noqa: BLE001 -- a copy never fails the session
        return {"session_id": session_id, "error": f"copy failed: {type(exc).__name__}: {exc}"[:300]}


def _capture(
    *, home: Path | str, surface: str, session_id: str | None, group: str, cwd: Path | str | None
) -> dict[str, Any]:
    if not session_id:
        return {"session_id": None, "error": "the session reported no session id"}
    if not _SAFE.match(session_id):
        return {"session_id": session_id[:80], "error": "the session id is not a safe file name"}
    projects = claude_projects_dir()
    source = _find(projects, session_id, cwd)
    if source is None:
        return {"session_id": session_id, "error": "no transcript file found for this session"}

    cache = worker.cache_dir(home)
    dest_dir = sessions_dir(home) / _group_name(surface) / group
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    shutil.copyfile(source, dest)

    subagent_files = 0
    subagent_bytes = 0
    sub_source = source.parent / session_id / "subagents"
    if sub_source.is_dir():
        sub_dest = dest_dir / session_id / "subagents"
        for sub in sorted(sub_source.glob("agent-*.jsonl")):
            if not sub.is_file():
                continue
            sub_dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sub, sub_dest / sub.name)
            subagent_files += 1
            subagent_bytes += (sub_dest / sub.name).stat().st_size

    entries, blocks = _counts(dest)
    record: dict[str, Any] = {
        "session_id": session_id,
        "path": dest.relative_to(cache).as_posix(),
        "bytes": dest.stat().st_size,
        "entries": entries,
        "assistant_blocks": blocks,
    }
    if subagent_files:
        record["subagent_files"] = subagent_files
        record["subagent_bytes"] = subagent_bytes
    return record
