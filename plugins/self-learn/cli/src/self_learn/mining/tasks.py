"""Unfinished work found in sessions, checked and filed in the znote tracker
(S-155, 12-transcript-miner.md §14).

The owner, 2026-08-19: "there's another shape of information other than
learning that would be valuable to mine and keep track of: oustanding tasks.
being able to look through a transcript and find all of the tasks that were
supposed to get completed, then verifying whether or not they've been
completed".

Three steps, all inside the nightly mine job:

1. **Found.** The session engine's one call per session may also return up
   to three ``tasks`` (the method's unfinished-work section); the checker
   verifies each one's quote (``check.check_tasks``) and the run adds the
   survivors here, in the cache (:class:`Store`), once the session's answer
   is saved.
2. **Checked.** A found item waits :data:`SETTLE_DAYS`, so the sessions that
   follow it exist. Then one small call per night (:func:`check_batch`,
   at most :data:`CHECK_BATCH` items) searches the later sessions, the
   project's tracker items and the notes, and decides for each: file it, or
   skip it with a reason (done later, already tracked, written down, set
   aside, not real work, unsure). Unsure is a skip.
3. **Filed.** What the check approves is filed as an ``idea`` in the chosen
   project, at most ``miner.tasks_per_night`` a night, through
   :class:`tracker.Tracker` -- the worker label ``self-learn`` owns it. Its
   ``why`` says what was left undone and in which session, with the line.

Nothing here touches the ledger. A tracker that cannot be reached keeps
every item where it is for the next night.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..invocation.contract import McpTool, McpToolset, ToolReply
from ..primitives import fsops
from ..scan import redact
from . import spine as spine_mod
from .tracker import Project, Tracker, TrackerError

__all__ = [
    "CHECK_BATCH",
    "REASONS",
    "SETTLE_DAYS",
    "Store",
    "check_batch",
    "file_approved",
    "night",
]

STORE_NAME = "tasks.json"
NIGHTS_NAME = "tasks-nights.jsonl"
#: Days a found item waits before its check, so the sessions after it exist.
SETTLE_DAYS = 2
#: Items one check call decides.
CHECK_BATCH = 8
#: Check calls that returned no usable decision for an item before it is
#: given up on (skipped, ``unchecked``).
MAX_CHECKS = 3
#: A found item still not checked after this many days (the tracker was down
#: all that time) is given up on.
EXPIRE_DAYS = 30
#: How a check decides an item: ``still-open`` files it, every other skips.
SKIP_REASONS = ("done-later", "already-tracked", "written-down", "set-aside", "not-real-work", "unsure")
REASONS = ("still-open", *SKIP_REASONS)
TITLE_MAX = 120
WHY_MAX = 500
NOTE_MAX = 400
WORKER_DIRS = re.compile(r"--cache-|-tmp-")
_WORD_RE = re.compile(r"[\w.\-/]{3,}", re.U)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(ts: object) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _norm(title: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", title.casefold()).split())


# ---------------------------------------------------------------- the store


class Store:
    """``<miner dir>/tasks.json``: every item found, keyed
    ``<session>#L<line>``, with where it stands: ``held`` (waiting for its
    check), ``approved`` (to be filed), ``filed``, ``skipped`` or
    ``expired``. Cache state (mode 0600: it holds transcript quotes), written
    whole."""

    def __init__(self, path: Path, items: dict[str, dict]) -> None:
        self.path = path
        self.items = items

    @classmethod
    def load(cls, path: Path) -> "Store":
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        items = doc.get("items") if isinstance(doc, dict) else None
        if not isinstance(items, dict):
            items = {}
        return cls(Path(path), {k: v for k, v in items.items() if isinstance(v, dict)})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fsops.private_write(self.path, json.dumps({"version": 1, "items": self.items}, indent=1, sort_keys=True) + "\n")

    def add(
        self,
        found: Iterable[Mapping[str, Any]],
        *,
        session: str,
        transcript: str,
        cwd: str | None,
        run_id: str,
        now: datetime | None = None,
    ) -> int:
        """Add the checked tasks of one session's answer; returns how many
        were new. An item already here (same session and line, or same
        session and the same title) is left as it is."""
        now = now or _now()
        added = 0
        for t in found:
            ev = t["evidence"]
            ref = ev["ref"]
            key = f"{session}#L{ref['line']}"
            title = str(t["title"])
            if key in self.items or any(
                i.get("session") == session and _norm(i.get("title", "")) == _norm(title) for i in self.items.values()
            ):
                continue
            self.items[key] = {
                "key": key,
                "session": session,
                "transcript": transcript,
                "project_dir": ref.get("project_dir"),
                "cwd": ref.get("cwd") or cwd,
                "line": ref["line"],
                "uuid": ref.get("uuid"),
                "entry_ts": ref.get("entry_ts"),
                "role": ref.get("role"),
                "quote": ev["quote"],
                "title": title,
                "left_undone": str(t["left_undone"]),
                "found_run": run_id,
                "found_at": _iso(now),
                "status": "held",
                "checks": 0,
                "decision": None,
                "item": None,
                "filed_at": None,
            }
            added += 1
        return added

    def when(self, item: Mapping[str, Any]) -> datetime:
        return _parse(item.get("entry_ts")) or _parse(item.get("found_at")) or _now()

    def ripe(self, now: datetime, settle_days: float = SETTLE_DAYS) -> list[dict]:
        cut = now - timedelta(days=settle_days)
        out = [i for i in self.items.values() if i.get("status") == "held" and self.when(i) <= cut]
        return sorted(out, key=lambda i: (self.when(i), i["key"]))

    def approved(self) -> list[dict]:
        out = [i for i in self.items.values() if i.get("status") == "approved"]
        return sorted(out, key=lambda i: (self.when(i), i["key"]))

    def expire(self, now: datetime) -> int:
        # counted from when the item was found, not from its session: an old
        # session read by a backfill is not stale on arrival
        cut = now - timedelta(days=EXPIRE_DAYS)
        n = 0
        for i in self.items.values():
            found = _parse(i.get("found_at")) or now
            if i.get("status") == "held" and found <= cut:
                i["status"] = "expired"
                n += 1
        return n

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.items.values():
            out[str(i.get("status"))] = out.get(str(i.get("status")), 0) + 1
        return dict(sorted(out.items()))


# ----------------------------------------------------------- the check's tools


def _entry_texts(entry: Mapping[str, Any]) -> list[tuple[str, str]]:
    """``(role label, text)`` pairs a search may match in one transcript
    row: what the person typed, what the assistant wrote, and the gist of
    each tool call (its command, path or description). Tool output is left
    out: it is long, and the work shows in the calls."""
    out: list[tuple[str, str]] = []
    kind = entry.get("type")
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return out
    content = msg.get("content")
    if kind == "user":
        if isinstance(content, str):
            out.append(("YOU", content))
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                    out.append(("YOU", b["text"]))
    elif kind == "assistant" and isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                out.append(("AGENT", b["text"]))
            elif b.get("type") == "tool_use":
                raw_in = b.get("input")
                inp: dict[str, Any] = raw_in if isinstance(raw_in, dict) else {}
                gist = " ".join(
                    str(inp[k]) for k in ("command", "file_path", "path", "description", "action", "title", "query")
                    if isinstance(inp.get(k), (str, int))
                )
                out.append((f"TOOL {b.get('name', '?')}", gist[:600]))
    return out


def _excerpt(text: str, words: Sequence[str], width: int = 320) -> str:
    low = text.casefold()
    pos = min((p for p in (low.find(w) for w in words) if p >= 0), default=0)
    start = max(0, pos - width // 2)
    piece = text[start : start + width]
    return ("…" if start else "") + " ⏎ ".join(piece.splitlines()) + ("…" if start + width < len(text) else "")


def _family(project_dir: str) -> str:
    """The transcript folder of a repository and of its worktrees share this
    prefix: a worktree's folder name continues with ``--claude-worktrees-``."""
    return project_dir.split("--claude-worktrees-", 1)[0]


@dataclass
class CheckTools:
    """The check call's three read-only tools over the items of one batch."""

    items: Mapping[str, Mapping[str, Any]]  # "T1" -> store item
    root: Path
    tracker: Tracker
    project_ids: frozenset[str]
    max_hits: int = 25
    _calls: int = field(default=0)

    DEFINITIONS = (
        {
            "name": "search_later_sessions",
            "description": (
                "Search the sessions after an item for words: the rest of the item's own session after its line, "
                "and every later session in the same folder (a repository and its worktrees), or in every folder "
                "with all_folders. All words must occur in one message. Returns matching messages the person typed, "
                "messages the assistant wrote, and tool calls (command, path or description), oldest first, with "
                "the session id and date. Use distinctive words: a file name, a command, a feature name."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "pattern": "^T[0-9]{1,2}$"},
                    "words": {"type": "string", "minLength": 3, "maxLength": 200},
                    "all_folders": {"type": "boolean", "default": False},
                },
                "required": ["item", "words"],
                "additionalProperties": False,
            },
        },
        {
            "name": "tracker_items",
            "description": (
                "List a znote project's tracker items (ideas, tasks, plans), open and closed, with id, stage, "
                "status and title. Give words to keep only items whose title holds any of them."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 80},
                    "words": {"type": "string", "maxLength": 200, "default": ""},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
        },
        {
            "name": "search_notes",
            "description": (
                "Search the person's znote notes (reports, plans, follow-up lists) by meaning and keywords. "
                "Write the query as a sentence. Give project to search one project only."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 5, "maxLength": 300},
                    "project": {"type": "string", "maxLength": 80, "default": ""},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    )

    def toolset(self) -> McpToolset:
        tools = []
        for d in self.DEFINITIONS:
            name = d["name"]

            async def handler(args: dict[str, Any], name: str = name) -> ToolReply:
                return await asyncio.to_thread(self.dispatch, name, args)

            tools.append(McpTool(name, d["description"], d["input_schema"], handler))
        return McpToolset("tasks", tuple(tools))

    def dispatch(self, name: str, args: Mapping[str, Any]) -> ToolReply:
        self._calls += 1
        try:
            if name == "search_later_sessions":
                text = self.search_later_sessions(str(args.get("item", "")), str(args.get("words", "")),
                                                  bool(args.get("all_folders", False)))
            elif name == "tracker_items":
                text = self.tracker_items(str(args.get("project", "")), str(args.get("words", "") or ""))
            elif name == "search_notes":
                text = self.search_notes(str(args.get("query", "")), str(args.get("project", "") or ""))
            else:
                return ToolReply(f"no tool {name}", is_error=True)
        except (ValueError, TrackerError) as exc:
            return ToolReply(redact(str(exc))[0][:1000], is_error=True)
        except Exception as exc:  # noqa: BLE001 -- a tool never crashes the session
            return ToolReply(f"{name}: data unavailable ({type(exc).__name__})", is_error=True)
        return ToolReply(redact(text)[0])

    # ---- tools

    def search_later_sessions(self, item_id: str, words: str, all_folders: bool = False) -> str:
        item = self.items.get(item_id)
        if item is None:
            raise ValueError(f"no item {item_id} in this check")
        phrase = re.findall(r'"([^"]{3,})"', words)
        terms = [p.casefold() for p in phrase] or [w.casefold() for w in _WORD_RE.findall(words)]
        if not terms:
            raise ValueError("give at least one word of three or more characters")
        after = _parse(item.get("entry_ts"))
        after_epoch = after.timestamp() if after else 0.0
        own = Path(str(item.get("transcript") or ""))
        family = _family(str(item.get("project_dir") or own.parent.name))
        rarest = max(terms, key=len).encode("utf-8")
        files: list[Path] = []
        if self.root.is_dir():
            for d in self.root.iterdir():
                if not d.is_dir() or WORKER_DIRS.search(d.name):
                    continue
                if not all_folders and not d.name.startswith(family):
                    continue
                for f in d.glob("*.jsonl"):
                    try:
                        if f.stat().st_mtime >= after_epoch - 60:
                            files.append(f)
                    except OSError:
                        continue
        hits: list[tuple[float, str]] = []
        scanned = 0
        for f in files:
            try:
                raw = f.read_bytes()
            except OSError:
                continue
            scanned += 1
            if rarest not in raw.lower():
                continue
            same = own.name == f.name
            for n, line in enumerate(raw.decode("utf-8", errors="replace").split("\n"), 1):
                if same and n <= int(item.get("line") or 0):
                    continue
                low = line.lower()
                if not all(t in low for t in terms):
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("isSidechain"):
                    continue
                ts = _parse(entry.get("timestamp"))
                if not same and (ts is None or ts.timestamp() <= after_epoch):
                    continue
                for role, text in _entry_texts(entry):
                    if all(t in text.casefold() for t in terms):
                        when = ts.astimezone().strftime("%Y-%m-%d %H:%M") if ts else "?"
                        tag = "same session" if same else f"session {f.stem}"
                        hits.append((ts.timestamp() if ts else 0.0,
                                     f"{tag}, {when}, L{n}, {role}: {_excerpt(text, terms)}"))
        hits.sort(key=lambda h: h[0])
        head = f"{len(hits)} match(es) in {scanned} later session file(s)"
        if not hits:
            return head + "."
        shown = hits[: self.max_hits]
        more = f"\n(+{len(hits) - len(shown)} more; narrow the words)" if len(hits) > len(shown) else ""
        return head + ":\n" + "\n".join(h for _t, h in shown) + more

    def tracker_items(self, project: str, words: str = "") -> str:
        if project not in self.project_ids:
            raise ValueError(f"no project {project!r}; use one of the listed projects")
        items = self.tracker.items(project, include_closed=True, limit=300)
        terms = [w.casefold() for w in _WORD_RE.findall(words)]
        if terms:
            items = [i for i in items if any(t in str(i.get("title", "")).casefold() for t in terms)]
        if not items:
            return f"No tracker items in {project}" + (" with those words." if terms else ".")
        rows = [
            f"{i.get('id')} [{i.get('stage')}/{i.get('status')}] {i.get('title')} (owner {i.get('owner')})"
            for i in items[:120]
        ]
        return f"{len(items)} item(s) in {project}:\n" + "\n".join(rows)

    def search_notes(self, query: str, project: str = "") -> str:
        if project and project not in self.project_ids:
            raise ValueError(f"no project {project!r}; use one of the listed projects")
        return self.tracker.search_notes(query, project or None, limit=5)[:6000]


# ----------------------------------------------------------------- the check


_INSTRUCTIONS = """\
This call checks unfinished work that the nightly read found in past Claude
Code sessions, before any of it is filed in the person's znote tracker. The
person does not read these items; agents and the weekly project summaries do.
A wrong item misleads them. For each item below, decide whether to file it.

File an item only when every one of these holds:

1. It was not done later. Search with `search_later_sessions` using the
   item's distinctive words (a file or function name, a command, a feature),
   two or three searches with different words before you conclude. The work
   done later in the same session, or in a later one, means `done-later`.
2. It is not in the tracker. Check `tracker_items` for the project you would
   file it in. An item that covers the same work, open or closed, means
   `already-tracked`.
3. It was not written down elsewhere. Check `search_notes`. A note that lists
   it as a follow-up, a next step or something not done means `written-down`.
4. Nobody set it aside. A later session where the person declined it, chose
   another way, or called the thing it belongs to abandoned or defunct means
   `set-aside`.
5. It is real work someone could pick up, not a lesson, a wish or a question:
   otherwise `not-real-work`.
6. One of the listed projects clearly fits it, judged from the session's
   folder and the item's subject. Otherwise `unsure`.

When you are not sure of any of these, skip it with `unsure`.

For an item you file (`still-open`), write:
- `title`: what to do to what, as an instruction in plain words, at most 100
  characters, with no item ids and no shorthand only the session would know;
- `why`: one or two plain sentences on what was left undone and why it still
  matters. The session id, date and quoted line are added after it for you.

For every item, write `note`: one sentence on what you found, naming the
session or tracker item that shows it.

Return one JSON object as your whole final message, no fences:
{"decisions": [{"id": "T1", "file": true, "reason": "still-open",
  "project": "<project id>", "title": "...", "why": "...", "note": "..."},
 {"id": "T2", "file": false, "reason": "done-later", "project": null,
  "title": null, "why": null, "note": "..."}]}
with exactly one decision per item. `reason` is one of: still-open,
done-later, already-tracked, written-down, set-aside, not-real-work, unsure.
"""


def _local_date(ts: object) -> str:
    dt = _parse(ts)
    return dt.astimezone().strftime("%Y-%m-%d") if dt else "an unknown date"


def _role_word(role: object) -> str:
    return {"user": "the person typed", "assistant": "the assistant wrote"}.get(str(role), "relayed text")


def check_prompt(batch: Mapping[str, Mapping[str, Any]], projects: Sequence[Project]) -> str:
    lines = [*spine_mod.SESSION_OPENINGS, "", "self-learn unfinished-work check.", "", _INSTRUCTIONS, "## Items", ""]
    for tid, i in batch.items():
        lines += [
            f"{tid}: session {i['session']}, folder {i.get('cwd') or i.get('project_dir')}, {_local_date(i.get('entry_ts'))}",
            f"  Found: {i['title']}",
            f"  Left undone: {i['left_undone']}",
            f"  Line L{i['line']} ({_role_word(i.get('role'))}): “{i['quote']}”",
            "",
        ]
    lines += ["## Projects (id: name, description)", ""]
    for p in projects:
        desc = f" — {p.description[:140]}" if p.description else ""
        lines.append(f"- {p.id}: {p.name}{desc}")
    return "\n".join(lines) + "\n"


def parse_decisions(text: str, batch_ids: Iterable[str], project_ids: Iterable[str]) -> dict[str, dict]:
    """The valid decisions in the check's final message, by item id. A
    decision that breaks any rule is left out (its item is checked again)."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        doc = json.loads(m.group(0))
    except ValueError:
        return {}
    raw = doc.get("decisions") if isinstance(doc, dict) else None
    if not isinstance(raw, list):
        return {}
    ids, projects = set(batch_ids), set(project_ids)
    out: dict[str, dict] = {}
    for d in raw:
        if not isinstance(d, dict) or d.get("id") not in ids or d["id"] in out:
            continue
        reason, file_it = d.get("reason"), d.get("file")
        if reason not in REASONS or not isinstance(file_it, bool) or file_it != (reason == "still-open"):
            continue
        raw_note = d.get("note")
        note = raw_note if isinstance(raw_note, str) else ""
        dec: dict[str, Any] = {"file": file_it, "reason": reason, "note": redact(note)[0][:NOTE_MAX]}
        if file_it:
            project, title, why = d.get("project"), d.get("title"), d.get("why")
            if project not in projects or not isinstance(title, str) or not isinstance(why, str):
                continue
            title, why = " ".join(redact(title)[0].split()), " ".join(redact(why)[0].split())
            if not 8 <= len(title) <= TITLE_MAX or not 20 <= len(why) <= WHY_MAX:
                continue
            dec.update(project=project, title=title, why=why)
        out[d["id"]] = dec
    return out


@dataclass
class CheckOutcome:
    decided: int = 0
    approved: int = 0
    skipped: int = 0
    undecided: int = 0
    cost_usd: float | None = None
    failure: str | None = None


def check_batch(
    items: Sequence[dict],
    *,
    projects: Sequence[Project],
    tracker: Tracker,
    root: Path,
    make_spec: Callable[[str, McpToolset, int], Any],
    call: Callable[[Any], Any],
    run_id: str,
    k: int = 0,
    now: datetime | None = None,
) -> CheckOutcome:
    """One check call over ``items`` (at most :data:`CHECK_BATCH`); each
    item's ``status`` and ``decision`` are set in place."""
    now = now or _now()
    batch = {f"T{n}": i for n, i in enumerate(items[:CHECK_BATCH], 1)}
    tools = CheckTools(batch, root, tracker, frozenset(p.id for p in projects))
    toolset = tools.toolset()
    spec = make_spec(check_prompt(batch, projects), toolset, k)
    out = CheckOutcome()
    try:
        outcome = call(spec)
    except Exception as exc:  # noqa: BLE001 -- a failed check leaves its items for the next night
        out.failure = f"the check call raised {type(exc).__name__}"
        outcome = None
    cost = getattr(outcome, "cost_usd", None)
    out.cost_usd = float(cost) if isinstance(cost, (int, float)) else None
    if outcome is not None and not getattr(outcome, "ok", False):
        out.failure = str(getattr(outcome, "failure", None) or "the check call failed")[:300]
    stdout = str(getattr(outcome, "stdout", "") or "") if outcome is not None and getattr(outcome, "ok", False) else ""
    decisions = parse_decisions(stdout, batch, (p.id for p in projects)) if stdout else {}
    for tid, item in batch.items():
        dec = decisions.get(tid)
        if dec is None:
            if out.failure is None:  # a failed call is the run's, not the item's
                item["checks"] = int(item.get("checks") or 0) + 1
                if item["checks"] >= MAX_CHECKS:
                    item["status"] = "skipped"
                    item["decision"] = {"file": False, "reason": "unchecked", "note": "no usable decision in three checks",
                                        "run": run_id, "at": _iso(now)}
            out.undecided += 1
            continue
        item["decision"] = {**dec, "run": run_id, "at": _iso(now)}
        item["status"] = "approved" if dec["file"] else "skipped"
        out.decided += 1
        if dec["file"]:
            out.approved += 1
        else:
            out.skipped += 1
    return out


# ------------------------------------------------------------------ filing


def why_text(item: Mapping[str, Any]) -> str:
    dec = item.get("decision") or {}
    quote = str(item.get("quote") or "")
    if len(quote) > 220:
        quote = quote[:219] + "…"
    folder = item.get("cwd") or item.get("project_dir") or "?"
    return (
        f"{dec.get('why', item.get('left_undone'))} Found by self-learn in session {item['session']} "
        f"({folder}, {_local_date(item.get('entry_ts'))}), line {item['line']}: “{quote}”"
    )


@dataclass
class FileOutcome:
    filed: list[str] = field(default_factory=list)
    duplicates: int = 0
    failure: str | None = None


def file_approved(store: Store, tracker: Tracker, cap: int, *, run_id: str, now: datetime | None = None) -> FileOutcome:
    """File approved items, oldest first, at most ``cap``. An item whose
    title the project already has (same words, any status) is skipped as
    ``already-tracked``. The first refusal or transport failure stops the
    filing; what is left stays approved."""
    now = now or _now()
    out = FileOutcome()
    titles: dict[str, set[str]] = {}
    for item in store.approved():
        if len(out.filed) >= cap:
            break
        dec = item["decision"]
        project = dec["project"]
        try:
            if project not in titles:
                titles[project] = {_norm(str(i.get("title", ""))) for i in tracker.items(project, limit=500)}
            if _norm(dec["title"]) in titles[project]:
                item["status"] = "skipped"
                item["decision"] = {**dec, "reason": "already-tracked", "note": "the project has an item with this title"}
                out.duplicates += 1
                continue
            wid = tracker.create_idea(
                project=project,
                title=dec["title"],
                why=why_text(item),
                # the tracker reads `quote` as the person's own words: only a
                # line they typed is one
                quote=str(item["quote"]) if item.get("role") == "user" else None,
            )
        except TrackerError as exc:
            out.failure = str(exc)[:300]
            break
        item.update(status="filed", item=wid, filed_at=_iso(now), filed_run=run_id)
        titles[project].add(_norm(dec["title"]))
        out.filed.append(wid)
    return out


# ------------------------------------------------------------------ the night


@dataclass
class NightReport:
    enabled: bool = True
    found_held: int = 0
    ripe: int = 0
    checked: int = 0
    approved: int = 0
    skipped: int = 0
    filed: list[str] = field(default_factory=list)
    duplicates: int = 0
    expired: int = 0
    cost_usd: float = 0.0
    failure: str | None = None
    dry_run: bool = False
    decisions: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "decisions"}


def night(
    store: Store,
    *,
    tracker: Tracker,
    root: Path,
    make_spec: Callable[[str, McpToolset, int], Any],
    call: Callable[[Any], Any],
    run_id: str,
    cap: int,
    max_batches: int = 1,
    settle_days: float = SETTLE_DAYS,
    dry_run: bool = False,
    now: datetime | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> NightReport:
    """The checked-and-filed half of one night: approved items left from an
    earlier night are filed first, then up to ``max_batches`` check calls
    over the ripe items, then the newly approved are filed, ``cap`` in all.
    ``dry_run``: the checks run, nothing is filed. The caller saves the
    store."""
    now = now or _now()
    rep = NightReport(dry_run=dry_run)
    rep.expired = store.expire(now)
    ripe = store.ripe(now, settle_days)
    rep.ripe = len(ripe)
    rep.found_held = sum(1 for i in store.items.values() if i.get("status") == "held")
    if not ripe and not store.approved():
        return rep
    try:
        projects = tracker.projects()
    except TrackerError as exc:
        rep.failure = str(exc)
        log(f"tasks: {exc}; every item waits for the next night")
        return rep
    if not projects:
        rep.failure = "the znote tracker lists no projects"
        return rep
    remaining = cap
    if not dry_run and store.approved() and remaining > 0:
        f = file_approved(store, tracker, remaining, run_id=run_id, now=now)
        rep.filed += f.filed
        rep.duplicates += f.duplicates
        remaining -= len(f.filed)
        if f.failure:
            rep.failure = f.failure
            log(f"tasks: filing stopped ({f.failure}); the rest wait")
            return rep
    for k in range(max_batches):
        batch = store.ripe(now, settle_days)[:CHECK_BATCH]
        if not batch:
            break
        o = check_batch(batch, projects=projects, tracker=tracker, root=root, make_spec=make_spec, call=call,
                        run_id=run_id, k=k, now=now)
        rep.checked += o.decided
        rep.approved += o.approved
        rep.skipped += o.skipped
        rep.cost_usd += o.cost_usd or 0.0
        rep.decisions += [dict(i) for i in batch]
        if o.failure:
            rep.failure = o.failure
            log(f"tasks: the check failed ({o.failure}); its items wait for the next night")
            break
    if not dry_run and remaining > 0 and store.approved():
        f = file_approved(store, tracker, remaining, run_id=run_id, now=now)
        rep.filed += f.filed
        rep.duplicates += f.duplicates
        if f.failure:
            rep.failure = f.failure
            log(f"tasks: filing stopped ({f.failure}); the rest wait")
    rep.cost_usd = round(rep.cost_usd, 6)
    return rep


def append_night(miner_dir: Path, run_id: str, rep: NightReport) -> None:
    """One line per night in ``tasks-nights.jsonl``: counts and ids only."""
    path = Path(miner_dir) / NIGHTS_NAME
    row = {"ts": _iso(_now()), "run_id": run_id, **rep.as_dict()}
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        path.chmod(0o600)
    except OSError:
        pass


def store_path(miner_dir: Path) -> Path:
    return Path(miner_dir) / STORE_NAME

