"""Who wrote a turn recorded as typed (2026-10-19; spec 02-schema.md
§"Transcript refs", role rule 10).

Claude Code records text another program types into a session's terminal
exactly like text the person typed: ``origin.kind == "human"``,
``promptSource == "typed"``. Herdr types an orchestrating agent's brief into
a worker's pane that way (a long text arrives inside the
``<pasted_content …>`` wrapper of a bracketed paste, which the person's own
pastes carry too). Read as the person's words, such a brief becomes a lesson
or a "ruling" the person never made.

A turn :func:`refs.role_of` would call ``user`` is written by an agent when
one of three signs holds (:func:`agent_written`):

1. **Tagged.** Its whole text -- after at most one ``<pasted_content>``
   wrapper -- is one ``<agent-message>…</agent-message>`` element
   (:func:`is_tagged`). Agents tag what they send through herdr since
   2026-10-19. A person who pastes an agent's message and writes below it
   is not tagged: their own words are in the turn.
2. **An accepted suggestion.** ``promptSource == "suggestion_accepted"``:
   Claude Code's own suggested prompt, accepted with one keystroke.
3. **Sent.** Another session made a tool call whose text mentions herdr
   at most :data:`SEND_WINDOW_SECS` before the turn (and at most
   :data:`SEND_SKEW_SECS` after it), and that text holds the turn's whole
   text (:meth:`SentIndex.sender_of`). This covers untagged history. A
   turn shorter than :data:`SHORT_CHARS` after :func:`fold` must sit in
   the call as one quoted argument, so ``1`` or ``yes`` never matches a
   pane id or a stray word. Measured 2026-10-19 over every transcript on
   the maintainer's machine: 195 of 2,684 typed turns matched; a prototype
   found 178 of its matches within 30 seconds of the send and none later
   than 400 seconds, and a six-hour window found no more.

Senders are read from Claude Code transcripts (subagent files included)
and Codex rollouts (:func:`sender_dirs`), only from lines that mention
herdr; each file's sends are cached by (path, mtime, size), so a
long-running process re-reads only files that changed.

Known limits: a brief sent as ``"$(cat FILE)"`` matches only when the
command itself holds the text; senders other than Claude Code and Codex
(hermes, agy, pi) are not read.
"""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "AGENT_CLOSE",
    "AGENT_OPEN",
    "SEND_SKEW_SECS",
    "SEND_WINDOW_SECS",
    "SHORT_CHARS",
    "Send",
    "SentIndex",
    "agent_written",
    "fold",
    "is_tagged",
    "sender_dirs",
    "sweep",
    "unwrap_paste",
]

AGENT_OPEN = "<agent-message>"
AGENT_CLOSE = "</agent-message>"
#: How long before a turn a send may have been made (module docstring, sign 3).
SEND_WINDOW_SECS = 30 * 60
#: How long after a turn a send may be stamped: the sender's row and the
#: receiver's row are written by two processes on one machine.
SEND_SKEW_SECS = 5
#: Folded turns shorter than this must appear in the send as one quoted argument.
SHORT_CHARS = 40
#: Claude Code's ``promptSource`` for a suggested prompt the person accepted.
SUGGESTION_ACCEPTED = "suggestion_accepted"

_PASTE = re.compile(r"\A\s*<pasted_content\b[^>]*>\n?(.*?)\n?</pasted_content\b[^>]*>\s*\Z", re.S)
_ESCAPED_SPACE = re.compile(r"\\[nrt]")
_DROPPED = re.compile(r"[\\\"'`]")
_WS = re.compile(r"\s+")
_HERDR = b"herdr"
_CODEX_CALLS = ("function_call", "custom_tool_call", "local_shell_call")
#: How a short sent text is quoted: shell quotes, or a JSON-escaped double quote.
_QUOTES = ('"', "'", '\\"')


def unwrap_paste(text: str) -> str:
    """``text`` without one ``<pasted_content …>…</pasted_content …>``
    wrapper around all of it; ``text`` itself when it has none."""
    m = _PASTE.match(text)
    return m.group(1) if m else text


def is_tagged(text: str) -> bool:
    """Sign 1: the whole text, after at most one paste wrapper, is one
    ``<agent-message>`` element."""
    body = unwrap_paste(text).strip()
    return (
        body.startswith(AGENT_OPEN)
        and body.endswith(AGENT_CLOSE)
        and body.count(AGENT_OPEN) == 1
    )


def fold(text: str) -> str:
    """The text with what shell and JSON quoting change taken out: escaped
    newlines and tabs become spaces, backslashes, quotes and backticks are
    dropped, and whitespace runs become one space. A sent text and the turn
    it became fold to the same string."""
    return _WS.sub(" ", _DROPPED.sub("", _ESCAPED_SPACE.sub(" ", text))).strip()


def _epoch(ts: object) -> float | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass(frozen=True)
class Send:
    """One tool call that mentions herdr: when, from which session, its text."""

    at: float
    session: str
    raw: str
    folded: str


class SentIndex:
    """Sends in time order (sign 3)."""

    def __init__(self, sends: Iterable[Send] = ()) -> None:
        self._sends = sorted(sends, key=lambda s: s.at)
        self._times = [s.at for s in self._sends]

    def __len__(self) -> int:
        return len(self._sends)

    def sender_of(self, text: str, at: float | None, session: str | None) -> Send | None:
        """The latest send from a session other than ``session``, made at
        most :data:`SEND_WINDOW_SECS` before ``at``, that holds ``text``
        (module docstring, sign 3); None when there is none or ``at`` is
        unknown."""
        if at is None:
            return None
        body = unwrap_paste(text).strip()
        folded = fold(body)
        if not folded:
            return None
        short = len(folded) < SHORT_CHARS
        lo = bisect.bisect_left(self._times, at - SEND_WINDOW_SECS)
        hi = bisect.bisect_right(self._times, at + SEND_SKEW_SECS)
        for send in reversed(self._sends[lo:hi]):
            if send.session == session or folded not in send.folded:
                continue
            if short and not any(q + body + q in send.raw for q in _QUOTES):
                continue
            return send
        return None


def agent_written(entry: dict, text: str, sent: SentIndex | None = None) -> bool:
    """True when the typed turn ``entry``, whose text is ``text``, was
    written by an agent (module docstring: signs 1-3; sign 3 only when
    ``sent`` is given)."""
    if is_tagged(text) or entry.get("promptSource") == SUGGESTION_ACCEPTED:
        return True
    if sent is None or not len(sent):
        return False
    ts = entry.get("timestamp")
    att = entry.get("attachment")
    if ts is None and isinstance(att, dict):
        ts = att.get("timestamp")
    session = entry.get("sessionId")
    return sent.sender_of(text, _epoch(ts), session if isinstance(session, str) else None) is not None


# ------------------------------------------------------------ the sweep


def sender_dirs(transcript_roots: Sequence[Path]) -> list[Path]:
    """Where sends are read from: each transcript root, plus the Codex
    rollouts beside a root that is a ``.claude/projects`` folder
    (``<home>/.claude/projects`` -> ``<home>/.codex/sessions``)."""
    out: list[Path] = []
    for root in transcript_roots:
        out.append(root)
        if root.name == "projects" and root.parent.name == ".claude":
            out.append(root.parent.parent / ".codex" / "sessions")
    return out


def _claude_sends(raw: dict, fallback_session: str) -> list[Send]:
    if raw.get("type") != "assistant":
        return []
    at = _epoch(raw.get("timestamp"))
    message = raw.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if at is None or not isinstance(content, list):
        return []
    session = raw.get("sessionId")
    session = session if isinstance(session, str) else fallback_session
    out: list[Send] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        inp = block.get("input")
        cmd = inp.get("command") if isinstance(inp, dict) else None
        if isinstance(cmd, str) and "herdr" in cmd:
            out.append(Send(at, session, cmd, fold(cmd)))
    return out


def _codex_sends(raw: dict, session: str) -> list[Send]:
    payload = raw.get("payload")
    if raw.get("type") != "response_item" or not isinstance(payload, dict):
        return []
    if payload.get("type") not in _CODEX_CALLS:
        return []
    at = _epoch(raw.get("timestamp"))
    body = payload.get("arguments") or payload.get("input") or payload.get("action")
    text = body if isinstance(body, str) else json.dumps(body)
    if at is None or "herdr" not in text:
        return []
    return [Send(at, session, text, fold(text))]


_CACHE: dict[str, tuple[int, int, tuple[Send, ...]]] = {}


def _file_sends(path: Path) -> tuple[Send, ...]:
    try:
        st = path.stat()
    except OSError:
        return ()
    key = str(path)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    codex = path.name.startswith("rollout-")
    session = f"codex:{path.stem}" if codex else path.stem
    sends: list[Send] = []
    try:
        with path.open("rb") as fh:
            for line in fh:
                if _HERDR not in line:
                    continue
                try:
                    raw = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if isinstance(raw, dict):
                    sends += _codex_sends(raw, session) if codex else _claude_sends(raw, session)
    except OSError:
        return ()
    found = tuple(sends)
    _CACHE[key] = (st.st_mtime_ns, st.st_size, found)
    return found


def sweep(dirs: Iterable[Path]) -> SentIndex:
    """Every send in every ``*.jsonl`` under ``dirs`` (recursively); a
    directory that does not exist adds nothing."""
    sends: list[Send] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.jsonl")):
            sends += _file_sends(path)
    return SentIndex(sends)
