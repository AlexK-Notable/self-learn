"""The session miner's three bounded, read-only tools (12 §13).

R2 calls ``build_toolset`` once per session. Paths and the judged end are
trusted engine inputs, never model arguments. All I/O runs off the event loop.

The engine passes the spine's own subagent logs (``Spine.subagents``), never
every file it finds, and the spine's ``end_ts``: a subagent's log is shown
only up to the judged range's end in time, as the spine and the checker
bound it, so no tool shows a line the checker would refuse as past the end.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, validators

from .. import refs, transcript_lines
from ..index import fts5, textquery
from ..index.protocol import EmbedProvider
from ..index.store import FROM_ENV, LessonIndex, _sections
from ..invocation.contract import McpTool, McpToolset, ToolReply
from ..ledger import Bucket, discover_buckets
from ..provenance import SentIndex
from ..records import Record
from ..scan import redact
from .contract import typed_turn_lines
from .spine import epoch

_log = logging.getLogger(__name__)
StrictValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda checker, value: isinstance(value, int) and not isinstance(value, bool)
    ),
)
#: Hook output these events inject is context the agent read (a reminder in
#: front of it matters to a rule check), so their ``hook_success`` rows stay.
_CONTEXT_HOOK_EVENTS = frozenset({"SessionStart", "UserPromptSubmit"})
_NOISE_ATTACHMENTS = frozenset({
    "hook_success", "total_tokens_reminder", "token_usage_reminder", "usage_reminder",
})

TOOL_DEFINITIONS = (
    {"name": "open_stretch", "description": "Show the agent's work after one of the user's typed turns, up to the next typed turn: each tool call with its input and whether it failed, the first and last lines of each tool output, the agent's messages in full, relayed messages, and subagent launches with their ids. Line numbers are the session file's. Long stretches come in pages.",
     "input_schema": {"type": "object", "properties": {
         "after_turn": {"type": "integer", "minimum": 0, "description": "k of T<k> on the spine; 0 = before the first typed turn"},
         "page": {"type": "integer", "minimum": 1, "default": 1}}, "required": ["after_turn"], "additionalProperties": False}},
    {"name": "find_similar_lessons", "description": "Find existing lessons that may be the same as one you are drafting. Give the draft's Trigger and Instruction, or its Fact. Returns up to five existing lessons, closest first, in full, with each one's status, scope and where it is placed.",
     "input_schema": {"type": "object", "properties": {"draft": {"type": "string", "minLength": 20, "maxLength": 2000}}, "required": ["draft"], "additionalProperties": False}},
    {"name": "search_subagent", "description": "Search one subagent's own records from this session. Give the subagent id shown on the spine or by open_stretch, and words or a quoted phrase to look for. Returns the brief it was given, the report it returned, and the matching lines of its log — never the whole log.",
     "input_schema": {"type": "object", "properties": {"subagent": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}, "query": {"type": "string", "minLength": 2, "maxLength": 200}}, "required": ["subagent", "query"], "additionalProperties": False}},
)

ROLE_LABELS = {"user": "YOU", "agent": "AGENT-WRITTEN", "assistant": "AGENT",
               "relay": "RELAY", "tool_result": "TOOL_RESULT", "subagent": "SUBAGENT"}


def read_entries(path: Path, end: int | None = None) -> list[dict | None]:
    """Keep physical line slots, including malformed/non-object JSON."""
    out: list[dict | None] = []
    for line in transcript_lines.iter_file(path, end=end):
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        out.append(entry if isinstance(entry, dict) else None)
    return out


def display(text: str) -> str:
    """Content never creates a physical output row; only templates may do that."""
    return " ⏎ ".join(redact(text)[0].splitlines())


def clip(text: str, limit: int) -> str:
    """Redact and flatten BEFORE clipping; preserve head and tail."""
    text = display(text)
    if len(text) <= limit:
        return text
    head = (limit - 3) // 2
    return text[:head] + " ⋯ " + text[-(limit - 3 - head):]


def raw(entry: dict) -> str:
    return refs._raw_text(entry)  # pyright: ignore[reportPrivateUsage]


def blocks(entry: dict) -> list[dict]:
    return refs._blocks(entry)  # pyright: ignore[reportPrivateUsage]


def strings(value: object) -> list[str]:
    return refs._strings(value)  # pyright: ignore[reportPrivateUsage]


def edges(text: str, limit: int = 200) -> str:
    lines = redact(text)[0].splitlines()
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0][:limit]
    return lines[0][:limit] + " ⋯ " + lines[-1][:limit]


@dataclass(frozen=True)
class Stretch:
    after_turn: int
    start_line: int
    end_line: int
    text: str


def stretches(entries: list[dict | None], sent: SentIndex | None = None) -> list[Stretch]:
    """Work-only documents for flags; never include the person's typed text."""
    turns = typed_turn_lines(entries, sent=sent)
    out = []
    for k, start in enumerate([0] + turns):
        end = turns[k] - 1 if k < len(turns) else len(entries)
        parts = []
        for entry in entries[start:end]:
            if not entry or refs.role_of(entry, sent=sent) not in ("assistant", "tool_result"):
                continue
            for b in blocks(entry):
                if b.get("type") == "tool_result":
                    parts.append(edges(refs._result_text(b)))  # pyright: ignore[reportPrivateUsage]
                elif b.get("type") == "text":
                    parts.append(str(b.get("text", "")))
                elif b.get("type") == "tool_use":
                    parts.extend([str(b.get("name", "")), *strings(b.get("input"))])
        out.append(Stretch(k, start + 1, end, redact("\n".join(parts))[0]))
    return out


def load_records(home: Path) -> dict[str, tuple[Bucket, Record]]:
    records = {}
    for bucket in discover_buckets(home):
        for folder in ("pending", "resolved"):
            for path in sorted((bucket.path / folder).glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                except (OSError, ValueError):
                    continue
                records[record.id] = (bucket, record)
    return records


def live_record(rid: str, records: Mapping[str, tuple[Bucket, Record]]) -> str | None:
    seen: set[str] = set()
    while rid in records and rid not in seen:
        seen.add(rid)
        record = records[rid][1]
        successor = record.superseded_by
        if successor:
            rid = successor
        else:
            return None if record.status == "superseded" else rid
    return None


class SessionTools:
    def __init__(self, session_file: Path, subagents: Mapping[str, Path], judged_end: int,
                 home: Path, *, sent: SentIndex | None = None,
                 provider: EmbedProvider | None = FROM_ENV, end_ts: float | None = None,
                 index_file: Path | None = None) -> None:
        self.session_file = session_file
        #: The lesson index ``find_similar_lessons`` reads: the run's own
        #: (a preview's copy inside its run folder), else the live one.
        self.index_file = index_file
        self.subagents = dict(subagents)
        self.judged_end = judged_end
        #: A subagent log is cut at its first entry written after this time.
        self.end_ts = end_ts
        self.home = home
        self.sent = sent
        self.provider = provider
        # Immutable SQLite images may cross threads; live connections never do.
        self._logs: dict[str, tuple[list[dict | None], bytes]] = {}
        self._lock = threading.Lock()

    def toolset(self) -> McpToolset:
        tools = []
        for definition in TOOL_DEFINITIONS:
            name = definition["name"]
            validator = StrictValidator(definition["input_schema"])

            async def handler(args: dict[str, Any], name=name, validator=validator) -> ToolReply:
                return await asyncio.to_thread(self._dispatch, name, validator, args)

            tools.append(McpTool(name, definition["description"], definition["input_schema"], handler))
        return McpToolset("miner", tuple(tools))

    def _dispatch(self, name: str, validator: Any, args: dict) -> ToolReply:
        error = next(validator.iter_errors(args), None)
        if error is not None:
            field = ".".join(str(part) for part in error.absolute_path) or "arguments"
            reason = clip(f"invalid arguments for {name}: {field}: {error.message}", 1000)
            return ToolReply(reason, is_error=True)
        try:
            text = getattr(self, name)(**args)
            return ToolReply(redact(text)[0])
        except ValueError as exc:
            return ToolReply(clip(str(exc), 1000), is_error=True)
        except Exception as exc:
            _log.error("%s failed unexpectedly (%s)", name, type(exc).__name__)
            return ToolReply(redact(f"{name}: data unavailable")[0], is_error=True)

    def _log(self, sid: str) -> tuple[list[dict | None], bytes]:
        with self._lock:
            if sid not in self._logs:
                entries = read_entries(self.subagents[sid])
                if self.end_ts is not None:
                    # cut where the judged range ends in time (spine.Spine.end_ts)
                    for n, e in enumerate(entries):
                        at = epoch(e.get("timestamp")) if e else None
                        if at is not None and at > self.end_ts:
                            entries = entries[:n]
                            break
                conn = sqlite3.connect(":memory:")
                try:
                    conn.execute(fts5.FTS_DDL)
                    conn.executemany("INSERT INTO lessons_fts VALUES (?, ?)",
                                     [(str(n), redact(raw(e))[0]) for n, e in enumerate(entries, 1) if e])
                    conn.commit()
                    self._logs[sid] = (entries, conn.serialize())
                finally:
                    conn.close()
            return self._logs[sid]

    def _launches(self, entries: list[dict | None]) -> dict[str, str]:
        links = {}
        for e in entries:
            if not e:
                continue
            result = e.get("toolUseResult")
            if isinstance(result, dict) and result.get("agentId") in self.subagents:
                for b in blocks(e):
                    if b.get("type") == "tool_result":
                        links[b.get("tool_use_id")] = result["agentId"]
        for e in entries:
            if not e:
                continue
            for b in blocks(e):
                if b.get("type") != "tool_use" or b.get("name") not in ("Task", "Agent") or b.get("id") in links:
                    continue
                prompt = (b.get("input") or {}).get("prompt")
                if not isinstance(prompt, str) or not prompt:
                    continue
                matches = []
                for sid in self.subagents:
                    logs, _ = self._log(sid)
                    first = next((raw(x) for x in logs if x and x.get("type") == "user"), "")
                    if first == prompt:
                        matches.append(sid)
                if len(matches) == 1:
                    links[b.get("id")] = matches[0]
        return links

    def open_stretch(self, after_turn: int, page: int = 1) -> str:
        entries = read_entries(self.session_file, self.judged_end)
        turns = typed_turn_lines(entries, sent=self.sent)
        if after_turn > len(turns):
            raise ValueError(f"after_turn must be in range 0..{len(turns)} (got {after_turn})")
        start = turns[after_turn - 1] if after_turn else 0
        end = turns[after_turn] - 1 if after_turn < len(turns) else len(entries)
        results = {}
        for n, e in enumerate(entries, 1):
            if e:
                for b in blocks(e):
                    if b.get("type") == "tool_result":
                        results[b.get("tool_use_id")] = (n, b)
        links = self._launches(entries)
        lines = []
        for n in range(start + 1, end + 1):
            e = entries[n - 1]
            if not e:
                continue
            role = refs.role_of(e, sent=self.sent)
            attachment = e.get("attachment")
            if role == "tool_result" or (e.get("type") == "attachment"
                    and isinstance(attachment, dict) and attachment.get("type") in _NOISE_ATTACHMENTS
                    and attachment.get("hookEvent") not in _CONTEXT_HOOK_EVENTS):
                continue
            label = ROLE_LABELS[role]
            if role != "assistant":
                if raw(e):
                    detail = clip(raw(e), 300)
                    lines.append(f"L{n} {label}: {detail}")
                continue
            for b in blocks(e):
                if b.get("type") == "text":
                    lines.append(f"L{n} AGENT: {clip(str(b.get('text', '')), 4000)}")
                elif b.get("type") == "tool_use":
                    name, inp = str(b.get("name", "")), b.get("input") or {}
                    result = results.get(b.get("id"))
                    outcome = "pending (no result in judged range)"
                    if result:
                        rn, rb = result
                        outcome = ("FAILED" if rb.get("is_error") else "ok") + f" (L{rn} TOOL_RESULT): " + edges(refs._result_text(rb))  # pyright: ignore[reportPrivateUsage]
                    if name == "Bash":
                        detail = clip(str(inp.get("command", "")), 300)
                    elif name in ("Edit", "Write", "Read"):
                        detail = clip(str(inp.get("file_path", inp.get("path", ""))), 200)
                    else:
                        detail = clip(" ".join(strings(inp)), 200)
                    lines.append(f"L{n} TOOL {name}: {detail} → {outcome}")
                    if b.get("id") in links:
                        sid = links[b["id"]]
                        logs, _ = self._log(sid)
                        report = next((raw(x) for x in reversed(logs) if x and x.get("type") == "assistant" and any(z.get("type") == "text" for z in blocks(x))), "")
                        brief = display(str(inp.get('prompt', '')))[:600]
                        lines.append(f"L{n} SUBAGENT {sid}: brief {brief} … report {clip(report, 603)}")
        # Reserve footer space; never split an entry across pages.
        pages: list[list[str]] = [[]]
        size = 0
        for line in lines:
            line = clip(line, 5000)
            if size + len(line) + 1 > 23700 and pages[-1]:
                pages.append([])
                size = 0
            pages[-1].append(line)
            size += len(line) + 1
        if page > len(pages):
            raise ValueError(f"page must be in range 1..{len(pages)} (got {page})")
        if page < len(pages):
            footer = f"page {page} of {len(pages)} — call open_stretch(after_turn={after_turn}, page={page + 1}) for more"
        elif after_turn < len(turns):
            footer = f"end of stretch (T{after_turn + 1} at L{turns[after_turn]})"
        else:
            footer = "end of stretch (end of judged range)"
        return "\n".join([*pages[page - 1], footer])

    def find_similar_lessons(self, draft: str) -> str:
        if self.index_file is not None:
            index = LessonIndex.open_at(self.index_file, self.home) if self.index_file.is_file() else None
        else:
            index = LessonIndex.open_existing(self.home)
        if index is None:
            return "search: word match only (index not built)"
        try:
            result = textquery.nearest_text(index, draft, limit=max(5, len(index.docs())), provider=self.provider)
        finally:
            index.close()
        records = load_records(self.home)
        first = "search: hybrid" if result.mode == "hybrid" else f"search: word match only ({result.note})"
        shown: set[str] = set()
        output = [clip(first, 500)]
        for hit in result.hits:
            rid = live_record(hit.id, records)
            if rid is None or rid in shown:
                continue
            shown.add(rid)
            bucket, record = records[rid]
            sections = _sections(record.body)
            names = ("Trigger", "Instruction") if record.type == "behavior" else ("Fact", "Context")
            body = "\n".join(f"{name}: {sections[name]}" for name in names if name in sections)
            routing = record.routing or {}
            placed = routing.get("destination") or "not placed"
            quote = next((str(e["quote"]) for e in record.evidence if e.get("quote")), "")
            header = f"{rid} [{record.status}] ({bucket.scope}/{bucket.name}) placed: {placed}"
            output.append(clip(header + "\n" + body + "\nevidence: " + clip(quote, 300), 1800))
            if len(shown) == 5:
                break
        return "\n\n".join(output)

    def search_subagent(self, subagent: str, query: str) -> str:
        if subagent not in self.subagents:
            raise ValueError("unknown subagent; valid ids: " + ", ".join(sorted(self.subagents)))
        entries, database = self._log(subagent)
        brief = next(((n, e) for n, e in enumerate(entries, 1) if e and e.get("type") == "user"), None)
        report = next(((n, e) for n, e in reversed(list(enumerate(entries, 1))) if e and e.get("type") == "assistant" and any(b.get("type") == "text" for b in blocks(e))), None)
        def named(name: str, item) -> str:
            if item is None:
                return f"{name}: (none)"
            n, e = item
            role = ROLE_LABELS[refs.role_of(e, in_subagent_file=True, sent=self.sent)]
            return f"{name}: L{n} SUBAGENT {display(subagent)} / {role}: " + display(raw(e))[:1500]
        output = [named("BRIEF", brief), named("REPORT", report)]
        query = redact(query)[0]
        phrase = query[1:-1].casefold() if query.startswith('"') and query.endswith('"') else None
        if phrase is not None:
            hits = [n for n, e in enumerate(entries, 1) if e and phrase in redact(raw(e))[0].casefold()][:20]
        else:
            conn = sqlite3.connect(":memory:")
            try:
                conn.deserialize(database)
                hits = [int(n) for n, _ in fts5.search(conn, query, limit=20)]
            finally:
                conn.close()
        for n in hits:
            e = entries[n - 1]
            assert e is not None
            text = redact(raw(e))[0]
            needles = [phrase] if phrase is not None else fts5.tokenize(query)
            positions = [text.casefold().find(word.casefold()) for word in needles]
            pos = min((p for p in positions if p >= 0), default=0)
            width = len(phrase) if phrase is not None else 50
            excerpt = text[max(0, pos - 150):pos + width + 150]
            role = ROLE_LABELS[refs.role_of(e, in_subagent_file=True, sent=self.sent)]
            output.append(f"L{n} SUBAGENT {display(subagent)} / {role}: …{display(excerpt)}…")
        return "\n".join(output)[:12000]


def build_toolset(session_file: Path, subagents: Mapping[str, Path], judged_end: int,
                  home: Path, *, sent: SentIndex | None = None,
                  provider: EmbedProvider | None = FROM_ENV, end_ts: float | None = None,
                  index_file: Path | None = None) -> McpToolset:
    return SessionTools(session_file, subagents, judged_end, home, sent=sent, provider=provider,
                        end_ts=end_ts, index_file=index_file).toolset()
