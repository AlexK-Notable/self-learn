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
   wrapper -- is one ``<agent-message>…</agent-message>`` element, or one
   element herdr-core's ``hc`` writes (:func:`is_tagged`,
   :func:`is_hc_delivered`). Agents tag what they send through herdr since
   2026-10-19. ``hc`` (2026-11-22, W-397) wraps a send whose sender is an
   agent's terminal in ``<hc from="t1 lead">…</hc>``, a template launch's
   first message in ``<hc from="…" reach="…">…</hc>``, and its own notes
   to a parent in ``<hc>…</hc>``. hc adds the element when the sending
   command runs inside a terminal whose program reported an agent status,
   a nested shell there included, so the person's own ``!hc send …`` from
   a Claude Code pane is wrapped too: when the caller passes the sends, an
   hc element whose inner text such a ``!`` command in another session sent
   (:meth:`SentIndex.person_sent`) stays the person's, unless that inner
   text is itself tagged (the person relayed an agent's message). A person who pastes
   an agent's message, or two hc deliveries, and writes beside it is not
   tagged: their own words are in the turn.
2. **An accepted suggestion.** ``promptSource == "suggestion_accepted"``:
   Claude Code's own suggested prompt, accepted with one keystroke.
3. **Sent.** Another session made a tool call whose text mentions herdr
   or runs ``hc send`` / ``hc run`` (:func:`is_send_call`) at most
   :data:`SEND_WINDOW_SECS` before the turn (and at most
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

Literal file substitutions in a herdr or hc text argument are read only when the
file has neither an mtime nor a ctime later than the send. No shell is executed or variables expanded.
"""

from __future__ import annotations

import bisect
import contextlib
import contextvars
import dataclasses
import hashlib
import json
import re
import math
import os
import shlex
import sqlite3
import stat
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Sequence

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
    "is_hc_delivered",
    "is_send_call",
    "is_tagged",
    "sender_dirs",
    "sweep",
    "unwrap_paste",
]

AGENT_OPEN = "<agent-message>"
AGENT_CLOSE = "</agent-message>"
HC_CLOSE = "</hc>"
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
#: The opening tag hc writes: ``<hc>``, or ``<hc`` with ``name="value"``
#: attributes only (0.1.22 writes ``from`` and ``reach``).
_HC_OPEN = r'<hc(?:\s+[A-Za-z_][\w.-]*="[^"\n]*")*\s*>'
_HC_OPEN_AT_START = re.compile(_HC_OPEN)
_HC_TAGS = re.compile(_HC_OPEN + "|" + re.escape(HC_CLOSE))
#: Backtick code (a fence, or a span on one line): a tag quoted there is prose.
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
#: A close followed later by an opening tag may be the boundary between two
#: elements with the person's words between them; when the inner text holds
#: one anywhere, no tag is treated as prose.
_CLOSE_THEN_OPEN = re.compile(re.escape(HC_CLOSE) + r".*?" + _HC_OPEN, re.S)
#: A call of herdr-core's CLI that hands text to a terminal: the word ``hc``
#: (not part of a longer word or file name; after an escaped newline or tab
#: when the call is stored JSON-escaped), optionally ``--json``, then
#: ``send`` or ``run``; or the same words as an argv list (``"hc", "send"``,
#: quotes JSON-escaped or not).
_HC_CALL_PAT = (r"(?:(?<![\w.-])|(?<=\\[nt]))hc(?:\s+--json)?\s+(?:send|run)\b"
                r'|\\?"(?:[^"\s\\]*/)?hc\\?"\s*,\s*\\?"(?:--json\\?"\s*,\s*\\?")?(?:send|run)\\?"')
_HC_CALL = re.compile(_HC_CALL_PAT)
_HC_CALL_BYTES = re.compile(_HC_CALL_PAT.encode())
#: What every match of :data:`_HC_CALL_PAT` holds: ``hc`` followed by
#: whitespace (the command form) or by a closing quote, JSON-escaped or not
#: (the argv form). The sweep tests each transcript line for this first:
#: it starts with a literal, so the search is a byte scan, while the full
#: pattern can begin at any quote and ran at 40 MB/s against 1 GB/s
#: (2026-11-23: a sweep of 9.35 GB took 233 s, not 9 s, and every inbox
#: packet timed out).
_HC_CALL_GATE = re.compile(rb'hc(?:\s|\\?"|\\[nrt])')
#: The command form as its bytes are stored when the whitespace after ``hc``
#: was a tab or a newline: JSON writes those as ``\t`` and ``\n``, which no
#: ``\s`` matches. The decoded text decides whether the row is a send; this
#: only keeps such a line from being dropped unread (review of S-163).
_HC_CALL_ESCAPED = re.compile(rb"hc(?:\s|\\[nrt])+(?:--json(?:\s|\\[nrt])+)?(?:send|run)\b")
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
    ``<agent-message>`` element or one element hc wrote
    (:func:`is_hc_delivered`)."""
    body = unwrap_paste(text).strip()
    return (
        body.startswith(AGENT_OPEN)
        and body.endswith(AGENT_CLOSE)
        and body.count(AGENT_OPEN) == 1
    ) or _is_hc_element(body)


def is_hc_delivered(text: str) -> bool:
    """The whole text, after at most one paste wrapper, is one element
    herdr-core's ``hc`` wrote, whatever it holds (02 §3a.6 rule 10,
    "delivered by hc")."""
    return _is_hc_element(unwrap_paste(text).strip())


def _is_hc_element(body: str) -> bool:
    """``body`` opens with an hc tag that only its final ``</hc>`` closes.
    Nested hc tags balance; tags inside backtick code are prose and are not
    counted, unless a close is followed anywhere by an opening tag (then every
    tag counts). Two elements with words between them close the first one
    early."""
    first = _HC_OPEN_AT_START.match(body)
    if first is None or not body.endswith(HC_CLOSE) or len(body) < first.end() + len(HC_CLOSE):
        return False
    end = len(body) - len(HC_CLOSE)
    inner = body[first.end():end]
    if _CLOSE_THEN_OPEN.search(inner) is None:
        inner = _CODE.sub(lambda m: " " * len(m.group(0)), inner)
    depth = 1
    for tag in _HC_TAGS.finditer(inner):
        depth += -1 if tag.group(0) == HC_CLOSE else 1
        if depth == 0:
            return False
    return depth == 1


def _hc_inner(text: str) -> str | None:
    """What an hc element holds, without its outer tags; None when ``text``
    is not one (:func:`is_hc_delivered`)."""
    body = unwrap_paste(text).strip()
    first = _HC_OPEN_AT_START.match(body)
    if first is None or not _is_hc_element(body):
        return None
    return body[first.end():len(body) - len(HC_CLOSE)]


def is_send_call(text: str) -> bool:
    """A tool call's text hands text to another terminal: it mentions
    herdr, or runs ``hc send`` or ``hc run`` (sign 3)."""
    return "herdr" in text or _HC_CALL.search(text) is not None


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
    """One tool call that sends (:func:`is_send_call`): when, from which session, its text."""

    at: float
    session: str
    raw: str
    folded: str
    cwd: str | None = None
    file_text: bool = False
    command: str | None = None
    #: A command the person ran themselves (a Claude Code ``!`` command),
    #: never an agent's send: only :meth:`SentIndex.person_sent` reads it.
    by_person: bool = False


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
        unknown. Commands the person ran themselves are never senders."""
        return self._find(unwrap_paste(text).strip(), at, session, by_person=False)

    def person_sent(self, text: str, at: float | None, session: str | None) -> Send | None:
        """The latest command the person ran themselves in a session other
        than ``session`` (a Claude Code ``!`` command), in the same window,
        that holds ``text`` by the same rules as :meth:`sender_of`."""
        return self._find(text.strip(), at, session, by_person=True)

    def _find(self, body: str, at: float | None, session: str | None, *, by_person: bool) -> Send | None:
        if at is None:
            return None
        folded = fold(body)
        if not folded:
            return None
        short = len(folded) < SHORT_CHARS
        lo = bisect.bisect_left(self._times, at - SEND_WINDOW_SECS)
        hi = bisect.bisect_right(self._times, at + SEND_SKEW_SECS)
        for send in reversed(self._sends[lo:hi]):
            if send.by_person != by_person or send.session == session or folded not in send.folded:
                continue
            if send.file_text and folded != send.folded:
                continue
            if short and not send.file_text and not any(q + body + q in send.raw for q in _QUOTES):
                continue
            return send
        return None


def agent_written(entry: dict, text: str, sent: SentIndex | None = None) -> bool:
    """True when the typed turn ``entry``, whose text is ``text``, was
    written by an agent (module docstring: signs 1-3; sign 3, and the
    person's own hc sends, only when ``sent`` is given)."""
    if entry.get("promptSource") == SUGGESTION_ACCEPTED:
        return True
    tagged = is_tagged(text)
    if sent is None or not len(sent):
        return tagged
    ts = entry.get("timestamp")
    att = entry.get("attachment")
    if ts is None and isinstance(att, dict):
        ts = att.get("timestamp")
    at = _epoch(ts)
    session = entry.get("sessionId")
    session = session if isinstance(session, str) else None
    if tagged:
        inner = _hc_inner(text)
        # An agent's tagged text the person relayed with ``!hc send`` stays the agent's.
        return inner is None or is_tagged(inner) or sent.person_sent(inner, at, session) is None
    return sent.sender_of(text, at, session) is not None


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


_BASH_INPUT = re.compile(r"\A<bash-input>(.*)</bash-input>\Z", re.S)


def _claude_person_sends(raw: dict, fallback_session: str) -> list[Send]:
    """A ``!`` command the person ran in a Claude Code session (a user row
    whose whole text is ``<bash-input>…</bash-input>``) that sends."""
    message = raw.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    at = _epoch(raw.get("timestamp"))
    if at is None or raw.get("isMeta") or not isinstance(content, str):
        return []
    m = _BASH_INPUT.match(content.strip())
    if m is None or not is_send_call(m.group(1)):
        return []
    session = raw.get("sessionId")
    session = session if isinstance(session, str) else fallback_session
    cmd = m.group(1)
    return [Send(at, session, cmd, fold(cmd), _cwd(raw.get("cwd")), by_person=True)]


def _claude_sends(raw: dict, fallback_session: str) -> list[Send]:
    if raw.get("type") == "user":
        return _claude_person_sends(raw, fallback_session)
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
        if isinstance(cmd, str) and is_send_call(cmd):
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
    if at is None or not is_send_call(text):
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
_ROW_ERRORS = (OSError, ValueError, TypeError, AttributeError, LookupError, OverflowError, RecursionError)


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
        if isinstance(cmd, str) and is_send_call(cmd):
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
        if isinstance(cmd, str) and is_send_call(cmd):
            out.append(Send(at, session, cmd, fold(cmd), _cwd(args.get("Cwd"))))
    return out


def _read_hermes_sends(path: Path) -> list[Send]:
    """Read only assistant terminal calls; no inferred session directory."""
    out = []
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            rows = db.execute("SELECT session_id, timestamp, tool_calls FROM messages "
                              "WHERE role='assistant' AND (tool_calls LIKE '%herdr%' OR tool_calls LIKE '%hc%')")
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
                        if fn.get("name") == "terminal" and isinstance(cmd, str) and is_send_call(cmd):
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
        text_arg = _text_argument(args)
        literal = candidates.get(text_arg) if text_arg is not None else None
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


#: ``hc run`` options that take a value; every other option is a flag.
_HC_RUN_VALUED = frozenset(("--name", "--cwd", "--on", "--label", "--parent", "--timeout"))
#: ``hc send`` options that take a value.
_HC_SEND_VALUED = frozenset(("--if", "--timeout"))


def _text_argument(args: list[str]) -> str | None:
    """The token that carries the sent text in one simple command, or None:
    the TEXT of ``herdr [--session NAME] agent prompt|pane send-text TARGET
    TEXT``, of ``hc [--json] send [OPTIONS] TARGET TEXT``, or the last
    argument of ``hc [--json] run [OPTIONS] PROGRAM … TASK`` when a program
    word comes before it (02 §3a.6 rule 10, file-backed send)."""
    if not args:
        return None
    if args[0] == "herdr":
        rest = args[1:]
        if rest[:1] == ["--session"]:
            rest = rest[2:]
        if len(rest) < 4 or rest[:2] not in (["agent", "prompt"], ["pane", "send-text"]):
            return None
        return rest[3]
    if args[0] != "hc":
        return None
    rest = args[1:]
    if rest[:1] == ["--json"]:
        rest = rest[1:]
    if not rest or rest[0] not in ("send", "run"):
        return None
    verb, rest = rest[0], rest[1:]
    if verb == "send":
        words, i = [], 0
        while i < len(rest):
            word = rest[i]
            i += 2 if word in _HC_SEND_VALUED else 1
            if not word.startswith("--"):
                words.append(word)
        return words[1] if len(words) == 2 else None
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rest[i] in _HC_RUN_VALUED else 1
    argv = rest[i:]
    return argv[-1] if len(argv) >= 2 else None


Fingerprint = tuple[int, int, int, int, int]


def _fingerprint(path: Path) -> Fingerprint | None:
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size, st.st_ctime_ns, st.st_ino, st.st_mode
    except (OSError, ValueError):
        return None


def _expand_files(sends: Iterable[Send], deps: dict[Path, Fingerprint | None],
                  unread: list[Path] | None = None) -> list[Send]:
    """The text of each FILE the sends named. A file that passed every test
    but could not be opened or read is appended to ``unread``: its text is
    missing for a reason its fingerprint does not record (no file handles
    left, an I/O error), so the caller must not keep the result past this
    process."""
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
                if unread is not None:
                    unread.append(path)
                continue
            after = _fingerprint(path)
            if after is None and unread is not None:
                # The file was just read and now cannot be examined: a passing
                # fault like a failed open, and as invisible to a fingerprint.
                unread.append(path)
            if after != before or len(body.encode("utf-8")) > 1024 * 1024:
                continue
            if body.strip():
                out.append(Send(send.at, send.session, body, fold(body), file_text=True, by_person=send.by_person))
    return out


_Entry = tuple[int, int, tuple[Send, ...], dict[Path, Fingerprint | None]]
_CACHE: dict[str, _Entry] = {}

# ------------------------------------------------- the cache kept on disk
#
# A sweep reads every transcript of every harness (9.35 GB in 3,476 files on
# 2026-11-23: 10 s to scan and 18 s to parse the lines that qualify), and
# `_CACHE` lives only as long as one process, so each `attention packet`
# paid all of it and the inbox page, which waits 15 s, never got one. The
# same entries are therefore kept in one file under the user's cache
# directory and trusted by the same test as `_CACHE`: the transcript's
# mtime and size, and the fingerprint of every brief file its sends named.
# The file is dropped whole when this module's source changes (its hash is
# stored in it), since an entry is only as good as the code that parsed it.
# It holds what the transcripts hold: the text agents sent each other, the
# bodies of the brief files those sends named (up to 1 MiB each), the
# commands the person ran with `!` that send, and the paths and session ids
# of all of them. So it is written 0600 in a 0700 directory, like the
# transcripts it was read from. It is a cache and nothing else: a missing,
# unreadable or malformed file, or one that cannot be written, changes how
# long a sweep takes and never what it returns.
#
# Every sweep READS the file; a sweep WRITES it only inside `saving()`.
# Verbs that promise to change nothing (a miner preview leaves the whole
# cache directory as it found it, a doctor row writes nothing) sweep too,
# so writing is something a caller turns on: building an inbox packet, and
# the miner's real nightly run, which keeps the file warm.

_DISK_VERSION = 1
#: Save during a long sweep at this interval, so a sweep that is cut short
#: (the inbox page stops a packet after 15 s) still leaves its work behind
#: and the next one finishes.
_DISK_SAVE_EVERY_SECS = 5.0
_SEND_FIELDS = {f.name: f for f in dataclasses.fields(Send)}
_SEND_TYPES: dict[str, tuple[type, ...]] = {
    "at": (int, float), "session": (str,), "raw": (str,), "folded": (str,), "cwd": (str, type(None)),
    "file_text": (bool,), "command": (str, type(None)), "by_person": (bool,),
}


class _Disk:
    """The loaded file's entries, where it lives, and whether they changed."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.entries: dict[str, _Entry] = {}
        self.dirty = False
        self.saved_at = 0.0
        #: `provenance.disk_cache`, as each sweep found it when it began.
        self.enabled = True


_DISK = _Disk()
#: One sweep at a time touches the entries or the file: `ask` runs its tools
#: in threads, and a save walks a dict another thread's sweep would add to.
_DISK_LOCK = threading.RLock()
_SAVING: contextvars.ContextVar[bool] = contextvars.ContextVar("self_learn_provenance_saving", default=False)


@contextlib.contextmanager
def saving() -> Iterator[None]:
    """Inside this block a sweep may write what it read to the cache file:
    every :data:`_DISK_SAVE_EVERY_SECS` while sweeps run, and once more when
    the outermost block ends (a packet sweeps once per quoted turn, and one
    save for all of them rewrites the file once, not each time). Outside it
    a sweep only reads the file; what it parses is still kept in memory, and
    written by a later block."""
    outermost = not _SAVING.get()
    token = _SAVING.set(True)
    try:
        yield
    finally:
        if outermost:
            _disk_save(final=True)
        _SAVING.reset(token)
def _hash_code() -> str:
    """The hash of this module's source and the interpreter that runs it
    (`shlex`, `json` and `datetime` come from the interpreter). Empty when
    the source cannot be read: unknown code never matches a stored hash."""
    try:
        return hashlib.sha256(Path(__file__).read_bytes() + b"\0" + sys.version.encode()).hexdigest()
    except OSError:
        return ""


#: Taken when the module is imported, not when the file is first used: a
#: long-lived process whose source changed on disk since it started would
#: otherwise file what its old code parsed under the new code's hash.
_CODE_HASH = _hash_code()


def _code_hash() -> str:
    return _CODE_HASH


def _switch_on() -> bool:
    """The `provenance.disk_cache` setting (config.yaml, the environment, the
    override channel). Off: the file is neither read nor written. A setting
    that cannot be read leaves the file in use, as the default does."""
    try:
        from . import settings
        from .ledger import resolve_home

        value, _source = settings.resolve_setting(resolve_home(), settings.by_name("provenance.disk_cache"))
        return bool(value)
    except Exception:  # noqa: BLE001 - a sweep never fails over a setting
        return True


def _disk_path() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    return base / "self-learn" / "provenance" / "sends.json"


def _send_from(row: object) -> Send:
    """A cached send, or ValueError when the row is not exactly one."""
    if not isinstance(row, dict) or set(row) != set(_SEND_FIELDS):
        raise ValueError("not a cached send")
    for name, types in _SEND_TYPES.items():
        value = row[name]
        if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
            raise ValueError(f"cached send field {name}")
    if not math.isfinite(row["at"]):
        raise ValueError("cached send time")
    return Send(**row)


def _fingerprint_from(row: object) -> Fingerprint | None:
    if row is None:
        return None
    if (not isinstance(row, list) or len(row) != 5
            or not all(isinstance(n, int) and not isinstance(n, bool) for n in row)):
        raise ValueError("not a cached fingerprint")
    return row[0], row[1], row[2], row[3], row[4]


def _disk_read(path: Path) -> dict[str, _Entry]:
    """The file's entries; {} when it is absent, from other code, or malformed
    anywhere (one bad row discards the file, never a row at a time)."""
    code = _code_hash()
    try:
        with path.open("rb") as fh:
            data = json.load(fh)
        if (not isinstance(data, dict) or data.get("version") != _DISK_VERSION
                or not code or data.get("code") != code or not isinstance(data.get("files"), dict)):
            return {}
        out: dict[str, _Entry] = {}
        for key, row in data["files"].items():
            if not isinstance(row, list) or len(row) != 4:
                raise ValueError("not a cached entry")
            mtime_ns, size, sends, deps = row
            if (not all(isinstance(n, int) and not isinstance(n, bool) for n in (mtime_ns, size))
                    or not isinstance(sends, list) or not isinstance(deps, dict)):
                raise ValueError("not a cached entry")
            out[key] = (mtime_ns, size, tuple(_send_from(s) for s in sends),
                        {Path(p): _fingerprint_from(fp) for p, fp in deps.items()})
        return out
    except _ROW_ERRORS:
        return {}


def _disk_entries() -> dict[str, _Entry]:
    """The entries for the cache file the environment names now (a test, or
    a run pointed at a scratch cache, gets its own and never another's)."""
    path = _disk_path()
    with _DISK_LOCK:
        if _DISK.path != path:
            _DISK.path, _DISK.entries, _DISK.dirty = path, _disk_read(path), False
            _DISK.saved_at = time.monotonic()
        return _DISK.entries


def _disk_save(*, final: bool) -> None:
    """Inside :func:`saving`, write the entries if they changed: at once
    when ``final``, else only when the last save is
    :data:`_DISK_SAVE_EVERY_SECS` old. A final save first drops entries
    whose transcript is gone. Never raises."""
    if not _SAVING.get() or not _DISK.enabled:
        return
    with _DISK_LOCK:
        if not _DISK.dirty or _DISK.path is None:
            return
        if not final and time.monotonic() - _DISK.saved_at < _DISK_SAVE_EVERY_SECS:
            return
        path, tmp = _DISK.path, None
        fd: int | None = None
        try:
            # The directory first: an unwritable cache fails here, before the
            # whole payload is built for nothing.
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX, dir=path.parent)  # 0600
            if final:
                for key in [k for k in _DISK.entries if not os.path.exists(k)]:
                    del _DISK.entries[key]
            files = {key: [mtime_ns, size, [dataclasses.asdict(send) for send in sends],
                           {str(p): (None if fp is None else list(fp)) for p, fp in deps.items()}]
                     for key, (mtime_ns, size, sends, deps) in _DISK.entries.items()}
            with os.fdopen(fd, "w", encoding="ascii") as fh:
                fd = None
                json.dump({"version": _DISK_VERSION, "code": _code_hash(), "files": files}, fh)
            os.replace(tmp, path)
            tmp = None
            _DISK.dirty = False
            _drop_stale_temporaries(path.parent)
        except _ROW_ERRORS + (RuntimeError,):
            pass
        finally:
            _DISK.saved_at = time.monotonic()  # a failed write is not retried on every file
            if tmp is not None:
                try:
                    if fd is not None:
                        os.close(fd)
                    os.unlink(tmp)
                except OSError:
                    pass


_TMP_PREFIX, _TMP_SUFFIX = ".sends-", ".tmp"
#: A temporary file this old belongs to a save that was killed (the inbox
#: page stops a packet with SIGKILL, which runs no cleanup), never to one
#: still being written.
_TMP_STALE_SECS = 600.0


def _drop_stale_temporaries(folder: Path) -> None:
    """Unlink the temporary files of saves that never finished. Never raises."""
    try:
        now = time.time()
        for name in os.listdir(folder):
            if name.startswith(_TMP_PREFIX) and name.endswith(_TMP_SUFFIX):
                stale = folder / name
                if now - stale.stat().st_mtime > _TMP_STALE_SECS:
                    stale.unlink()
    except _ROW_ERRORS:
        pass


def forget() -> None:
    """Drop every remembered send, in memory (the Hermes store's too) and
    in the file, so the next sweep reads each store anew. Never raises."""
    _CACHE.clear()
    _HERMES_CACHE.clear()
    path = _disk_path()
    with _DISK_LOCK:
        _DISK.path, _DISK.entries, _DISK.dirty = path, {}, False
        try:
            path.unlink()
        except OSError:
            pass


def _entry_current(entry: _Entry | None, st: os.stat_result) -> bool:
    return (entry is not None and entry[0] == st.st_mtime_ns and entry[1] == st.st_size
            and all(_fingerprint(p) == fp for p, fp in entry[3].items()))


def _file_sends(path: Path) -> tuple[Send, ...]:
    try:
        st = path.stat()
    except (OSError, ValueError):
        return ()
    key = str(path)
    hit = _CACHE.get(key)
    if hit is not None and _entry_current(hit, st):
        return hit[2]
    disk = _disk_entries() if _DISK.enabled else None
    kept = disk.get(key) if disk is not None else None
    if kept is not None and _entry_current(kept, st):
        _CACHE[key] = kept
        return kept[2]
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
                if (_HERDR not in line
                        and (_HC_CALL_GATE.search(line) is None
                             or (_HC_CALL_BYTES.search(line) is None and _HC_CALL_ESCAPED.search(line) is None))
                        and not ((codex or pi) and b'"cwd"' in line)):
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
    unread: list[Path] = []
    sends += _expand_files(sends, deps, unread)
    found = tuple(sends)
    entry: _Entry = (st.st_mtime_ns, st.st_size, found, deps)
    _CACHE[key] = entry
    with _DISK_LOCK:
        if disk is None:
            pass  # `provenance.disk_cache` is off: nothing is kept past this process
        elif unread:
            # A brief could not be read just now. In memory that lasts one
            # process, as it always has; in the file it would make an agent's
            # brief read as the person's words in every later process.
            if disk.pop(key, None) is not None:
                _DISK.dirty = True
        else:
            disk[key] = entry
            _DISK.dirty = True
    _disk_save(final=False)
    return found


def sweep(dirs: Iterable[Path]) -> SentIndex:
    """Read sends from harness stores; absent or malformed stores add nothing."""
    _DISK.enabled = _switch_on()
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
    _disk_save(final=False)
    return SentIndex(sends)
