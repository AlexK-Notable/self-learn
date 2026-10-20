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

Senders are read from Claude Code, Codex, Hermes, agy and pi. JSONL
files are cached by path, mtime and size, including the stat fingerprints of
referenced brief files. Hermes reads are cached against both the database
and its WAL, since WAL changes need not change the database file.

Literal file substitutions in a herdr text argument are read only when the
file has neither an mtime nor a ctime later than the send. No shell is executed or variables expanded.
"""

from __future__ import annotations

import bisect
import json
import re
import math
import os
import shlex
import sqlite3
import stat
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
    cwd: str | None = None
    file_text: bool = False
    command: str | None = None


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
            if send.file_text and folded != send.folded:
                continue
            if short and not send.file_text and not any(q + body + q in send.raw for q in _QUOTES):
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
    """Transcript roots and the other harness stores beside .claude/projects.
    An arbitrary transcripts folder never causes a scan of the user's home.
    """
    out: list[Path] = []
    for root in transcript_roots:
        out.append(root)
        if root.name == "projects" and root.parent.name == ".claude":
            home = root.parent.parent
            out.extend([home / ".codex" / "sessions", home / ".hermes",
                        home / ".gemini" / "antigravity-cli" / "brain",
                        home / ".pi" / "agent" / "sessions"])
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
            out.append(Send(at, session, cmd, fold(cmd), _cwd(_object(inp).get("cwd") or raw.get("cwd"))))
    return out


def _codex_sends(raw: dict, session: str, cwd: str | None = None) -> list[Send]:
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
    # Preserve the original text for the established inline rule. Decode the
    # command separately for file substitutions; JSON escaping is not shell syntax.
    args = _object(body)
    call_cwd = _cwd(args.get("workdir") or args.get("cwd")) or cwd
    cmd = args.get("cmd") or args.get("command")
    if isinstance(cmd, list) and len(cmd) == 3 and cmd[1] in ("-c", "-lc"):
        cmd = cmd[2]
    command = cmd if isinstance(cmd, str) else text
    return [Send(at, session, text, fold(text), call_cwd, command=command)]


# A bad stored row/store must not interrupt unrelated provenance lookups.
_ROW_ERRORS = (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError)


def _path_text_ok(value: str) -> bool:
    return "\0" not in value and not any(0xD800 <= ord(c) <= 0xDFFF for c in value)


def _cwd(value: object) -> str | None:
    if isinstance(value, str) and not _path_text_ok(value):
        raise ValueError("invalid stored directory")
    return value if isinstance(value, str) and Path(value).is_absolute() else None


def _checked_sends(sends: list[Send]) -> list[Send]:
    for send in sends:
        if not _path_text_ok(send.raw) or not _path_text_ok(send.command or ""):
            raise ValueError("invalid stored command")
        _cwd(send.cwd)
    return sends


def _object(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return {}
    return value if isinstance(value, dict) else {}


def _pi_sends(raw: dict, session: str, cwd: str | None) -> list[Send]:
    message = _object(raw.get("message"))
    at = _epoch(raw.get("timestamp"))
    if raw.get("type") != "message" or message.get("role") != "assistant" or at is None:
        return []
    out = []
    content = message.get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "toolCall" or block.get("name") != "bash":
            continue
        args = _object(block.get("arguments"))
        cmd = args.get("command")
        if isinstance(cmd, str) and "herdr" in cmd:
            out.append(Send(at, session, cmd, fold(cmd), _cwd(args.get("cwd")) or cwd))
    return out


def _agy_sends(raw: dict, session: str) -> list[Send]:
    at = _epoch(raw.get("created_at"))
    if raw.get("type") != "PLANNER_RESPONSE" or at is None:
        return []
    out = []
    calls = raw.get("tool_calls")
    for call in calls if isinstance(calls, list) else []:
        if not isinstance(call, dict) or call.get("name") != "run_command":
            continue
        args = _object(call.get("args"))
        cmd = args.get("CommandLine")
        if isinstance(cmd, str) and "herdr" in cmd:
            out.append(Send(at, session, cmd, fold(cmd), _cwd(args.get("Cwd"))))
    return out


def _read_hermes_sends(path: Path) -> list[Send]:
    """Read only assistant terminal calls; no inferred session directory."""
    out = []
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            rows = db.execute("SELECT session_id, timestamp, tool_calls FROM messages "
                              "WHERE role='assistant' AND tool_calls LIKE '%herdr%'")
            for session, at, encoded in rows:
                try:
                    if not isinstance(at, (int, float)) or not math.isfinite(at):
                        continue
                    calls = json.loads(encoded)
                    row_sends = []
                    for call in calls if isinstance(calls, list) else []:
                        fn = _object(_object(call).get("function"))
                        args = _object(fn.get("arguments"))
                        cmd = args.get("command")
                        if fn.get("name") == "terminal" and isinstance(cmd, str) and "herdr" in cmd:
                            row_sends.append(Send(at, "hermes:" + str(session), cmd, fold(cmd),
                                                  _cwd(args.get("workdir"))))
                    out.extend(_checked_sends(row_sends))
                except _ROW_ERRORS:
                    continue
        finally:
            db.close()
    except (sqlite3.Error, *_ROW_ERRORS):
        return []
    return out


DbStamp = tuple[int, int, int] | None
_HERMES_CACHE: dict[str, tuple[tuple[DbStamp, DbStamp], tuple[Send, ...]]] = {}


def _db_stamp(path: Path) -> DbStamp:
    fp = _fingerprint(path)
    return (fp[0], fp[1], fp[3]) if fp is not None else None


def _hermes_sends(path: Path) -> list[Send]:
    """Reuse raw sends only while both the main DB and WAL are unchanged.

    File-content expansions are deliberately outside this cache: their own
    dependencies must still be checked on every sweep.
    """
    wal = path.with_name(path.name + "-wal")
    stamp = (_db_stamp(path), _db_stamp(wal))
    key = str(path)
    hit = _HERMES_CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return list(hit[1])
    found = _read_hermes_sends(path)
    if stamp == (_db_stamp(path), _db_stamp(wal)):
        _HERMES_CACHE[key] = (stamp, tuple(found))
    return found


# Only a whole double-quoted substitution in the TEXT argument is eligible.
# Parsing tokens keeps quoted prose, file reads elsewhere in the command, and
# pane IDs from becoming sends. Deliberately not a shell interpreter.
_FILE_ARG = re.compile(r'"\$\((?:cat\s+(?:--\s+)?|<\s*)([^()\n]+)\)"')


def _brief_paths(send: Send) -> list[Path]:
    candidates: dict[str, str] = {}

    source = send.command or send.raw

    def substitute(match: re.Match) -> str:
        quote = None
        escaped = False
        for char in source[:match.start()]:
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif char == quote:
                quote = None
            elif char in ("'", '"') and quote is None:
                quote = char
        if quote is not None or escaped:
            return match.group(0)
        marker = f"__self_learn_file_{len(candidates)}__"
        candidates[marker] = match.group(1)
        return marker

    command = _FILE_ARG.sub(substitute, source)
    if not candidates or "<<" in command or "`" in command:
        return []
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    out = []
    segment: list[str] = []
    # Any possible cwd mutation makes relative resolution uncertain, even
    # inside a compound command (e.g. `then cd ...`). False negatives are safe.
    changed_dir = any(t in ("cd", "pushd", "popd", "eval", "source", ".") for t in tokens)
    for token in [*tokens, ";"]:
        if token not in (";", "&&", "||", "|", "&", "\n"):
            segment.append(token)
            continue
        args = segment
        segment = []
        if not args or args[0] != "herdr":
            continue
        args = args[1:]
        if args[:1] == ["--session"]:
            args = args[2:]
        if len(args) < 4 or args[:2] not in (["agent", "prompt"], ["pane", "send-text"]):
            continue
        literal = candidates.get(args[3])
        if literal is None:
            continue
        try:
            names = shlex.split(literal)
        except ValueError:
            continue
        if len(names) != 1 or any(c in names[0] for c in "$`*?[]~\n;<>&|") or names[0].startswith("-"):
            continue
        if not _path_text_ok(names[0]):
            raise ValueError("invalid stored filename")
        path = Path(names[0])
        if not path.is_absolute():
            if send.cwd is None or changed_dir:
                continue
            cwd = _cwd(send.cwd)
            if cwd is None:
                continue
            path = Path(cwd) / path
        out.append(path)
    return out


Fingerprint = tuple[int, int, int, int, int]


def _fingerprint(path: Path) -> Fingerprint | None:
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size, st.st_ctime_ns, st.st_ino, st.st_mode
    except (OSError, ValueError):
        return None


def _expand_files(sends: Iterable[Send], deps: dict[Path, Fingerprint | None]) -> list[Send]:
    out = []
    for send in sends:
        try:
            paths = _brief_paths(send)
        except _ROW_ERRORS:
            continue
        for path in paths:
            before = _fingerprint(path)
            if path in deps and deps[path] != before:
                # Never retain an earlier payload under a later fingerprint.
                # Keep the old dependency so the next cache hit re-reads too.
                return []
            deps[path] = before  # Missing files are dependencies too.
            if before is None or not stat.S_ISREG(before[4]) or before[0] / 1e9 > send.at or before[2] / 1e9 > send.at:
                continue
            # Bound reads and avoid blocking if a regular file becomes a FIFO.
            if before[1] > 1024 * 1024:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as fh:
                    if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                        continue
                    body = fh.read(1024 * 1024 + 1).decode("utf-8").rstrip("\n")
            except (OSError, ValueError):
                continue
            if _fingerprint(path) != before or len(body.encode("utf-8")) > 1024 * 1024:
                continue
            if body.strip():
                out.append(Send(send.at, send.session, body, fold(body), file_text=True))
    return out


_CACHE: dict[str, tuple[int, int, tuple[Send, ...], dict[Path, Fingerprint | None]]] = {}


def _file_sends(path: Path) -> tuple[Send, ...]:
    try:
        st = path.stat()
    except (OSError, ValueError):
        return ()
    key = str(path)
    hit = _CACHE.get(key)
    if (hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size
            and all(_fingerprint(p) == fp for p, fp in hit[3].items())):
        return hit[2]
    codex = path.name.startswith("rollout-")
    agy = path.name == "transcript_full.jsonl"
    pi = ".pi" in path.parts
    session = ("codex:" if codex else "pi:" if pi else "") + path.stem
    if agy:
        session = "agy:" + path.parents[2].name
    cwd = None
    sends: list[Send] = []
    try:
        with path.open("rb") as fh:
            for line in fh:
                # Header/context rows carry cwd, even without a herdr mention.
                if _HERDR not in line and not ((codex or pi) and b'"cwd"' in line):
                    continue
                try:
                    raw = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if not isinstance(raw, dict):
                    continue
                try:
                    if codex:
                        if raw.get("type") in ("session_meta", "turn_context"):
                            cwd = None
                            cwd = _cwd(_object(raw.get("payload")).get("cwd"))
                        row_sends = _codex_sends(raw, session, cwd)
                    elif agy:
                        row_sends = _agy_sends(raw, session)
                    elif pi:
                        if raw.get("type") == "session":
                            cwd = None
                            cwd = _cwd(raw.get("cwd"))
                        row_sends = _pi_sends(raw, session, cwd)
                    else:
                        row_sends = _claude_sends(raw, session)
                    sends.extend(_checked_sends(row_sends))
                except _ROW_ERRORS:
                    continue
    except (OSError, ValueError):
        return ()
    deps: dict[Path, Fingerprint | None] = {}
    sends += _expand_files(sends, deps)
    found = tuple(sends)
    _CACHE[key] = (st.st_mtime_ns, st.st_size, found, deps)
    return found


def sweep(dirs: Iterable[Path]) -> SentIndex:
    """Read sends from harness stores; absent or malformed stores add nothing."""
    sends: list[Send] = []
    for d in dict.fromkeys(dirs):
        try:
            if not d.is_dir():
                continue
            if d.name == ".hermes":
                db_sends = _hermes_sends(d / "state.db")
                sends += db_sends + _expand_files(db_sends, {})
                continue
            pattern = "*/.system_generated/logs/transcript_full.jsonl" if d.name == "brain" else "**/*.jsonl"
            for path in sorted(d.glob(pattern)):
                try:
                    sends += _file_sends(path)
                except _ROW_ERRORS:
                    continue
        except _ROW_ERRORS:
            continue
    return SentIndex(sends)
