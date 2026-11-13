"""The znote tracker, as the unfinished-work filer reaches it (S-155).

znote serves its MCP tools from a local daemon over plain HTTP (``POST
/mcp``, stateless, JSON replies); its stdio front end only forwards each
JSON-RPC line there. A program that is not a Claude Code session has no
caller stamp (the stamp is made by znote's own Claude Code hook, keyed by a
file only that hook may read), so the daemon gives it the rights of an
unverified caller: it may read, and it may create an ``idea``, which it owns
through its worker label (``as_worker``). That is all this module does. It
never reads the daemon's ``admin.token`` or ``caller.key`` and never calls an
``/admin/`` route.

The address follows znote's own variables, ``ZNOTE_HTTP_HOST`` (default
127.0.0.1) and ``ZNOTE_HTTP_PORT`` (default 8742). A daemon that is not
running is not started from here: the caller keeps its work for the next
night.
"""

from __future__ import annotations

import http.client
import itertools
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

__all__ = ["WORKER_LABEL", "Project", "Tracker", "TrackerError", "TrackerRefused", "default_url"]

#: The worker label every item self-learn files carries, and so its owner.
WORKER_LABEL = "self-learn"
_ITEM_ID_RE = re.compile(r"\bW-\d+\b")
_ids = itertools.count(1)


class TrackerError(RuntimeError):
    """The tracker could not be reached, or refused the call."""


class TrackerRefused(TrackerError):
    """The tracker answered and refused this one call (a project that is
    gone, a title it will not take): the next item may still go through."""


#: The daemon is on this machine: never send its traffic through a proxy
#: the environment names (``http_proxy`` would otherwise apply to 127.0.0.1).
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_PROJECT_RE = re.compile(r"^(\s*)\* (\S+)\s*$")
_FIELD_RE = re.compile(r"^(\s+)([A-Za-z][A-Za-z ]*):\s?(.*)$")


def default_url() -> str:
    host = os.environ.get("ZNOTE_HTTP_HOST") or "127.0.0.1"
    port = os.environ.get("ZNOTE_HTTP_PORT") or "8742"
    return f"http://{host}:{port}/mcp"


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    description: str


class Tracker:
    """A small client for the tools the filer needs."""

    def __init__(self, url: str | None = None, *, timeout: float = 30.0) -> None:
        self.url = url or default_url()
        self.timeout = timeout

    # ---- transport

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """``tools/call`` of ``tool``: the result object (``content``,
        ``structuredContent``, ``isError``). Raises :class:`TrackerError` on
        any transport failure, a JSON-RPC error, or ``isError``."""
        body = json.dumps(
            {"jsonrpc": "2.0", "id": next(_ids), "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
        try:
            with _OPENER.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
            raise TrackerError(f"the znote daemon did not answer ({type(exc).__name__})") from None
        try:
            doc = json.loads(raw)
        except (ValueError, RecursionError):
            raise TrackerError("the znote daemon's reply is not JSON") from None
        if not isinstance(doc, dict) or "error" in doc:
            err = doc.get("error") if isinstance(doc, dict) else None
            msg = err.get("message") if isinstance(err, dict) else None
            raise TrackerRefused(f"znote refused {tool}: {str(msg)[:200]}")
        result = doc.get("result")
        if not isinstance(result, dict):
            raise TrackerError(f"znote's reply to {tool} has no result")
        if result.get("isError"):
            raise TrackerRefused(f"znote refused {tool}: {self.text(result)[:300]}")
        return result

    @staticmethod
    def text(result: dict[str, Any]) -> str:
        parts = result.get("content") or []
        return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))

    @staticmethod
    def structured(result: dict[str, Any]) -> dict[str, Any]:
        s = result.get("structuredContent")
        return s if isinstance(s, dict) else {}

    # ---- reads

    def projects(self) -> list[Project]:
        """The active projects, sub-projects included, parsed from
        ``zk_manage_projects list``: each ``* <id>`` line opens one (a
        sub-project's is indented two spaces per level), and the field lines
        under it, indented deeper than it, are its own."""
        text = self.text(self.call("zk_manage_projects", {"action": "list", "include_note_counts": False}))
        out: list[Project] = []
        cur: dict[str, str] | None = None
        depth = 0
        for line in text.splitlines():
            m = _PROJECT_RE.match(line)
            if m:
                if cur:
                    out.append(Project(cur["id"], cur.get("name", cur["id"]), cur.get("description", "")))
                cur, depth = {"id": m.group(2)}, len(m.group(1))
                continue
            f = _FIELD_RE.match(line)
            if cur is not None and f and len(f.group(1)) > depth:
                cur.setdefault(f.group(2).strip().lower(), f.group(3).strip())
        if cur:
            out.append(Project(cur["id"], cur.get("name", cur["id"]), cur.get("description", "")))
        return [p for p in out if p.id]

    def items(self, project: str, *, include_closed: bool = True, limit: int = 5000) -> list[dict[str, Any]]:
        """A project's tracker items, newest first (znote lists them oldest
        first, by id, so every page is read and the order turned round)."""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            s = self.structured(
                self.call(
                    "zk_work",
                    {"action": "list", "project": project, "include_closed": include_closed, "limit": 100, "offset": offset},
                )
            )
            if s.get("ok") is False:
                err = s.get("error") or {}
                raise TrackerRefused(f"znote refused the list: {str(err.get('message', ''))[:200]}")
            page = s.get("items") or []
            out.extend(i for i in page if isinstance(i, dict))
            total = s.get("total") or 0
            offset += len(page)
            if not page or offset >= total or len(out) >= limit:
                return list(reversed(out))[:limit]

    def search_notes(self, query: str, project: str | None = None, limit: int = 5) -> str:
        args: dict[str, Any] = {"query": query, "limit": limit, "sources": "notes", "output": "full"}
        if project:
            args["project"] = project
        return self.text(self.call("zk_search_notes", args))

    # ---- the one write

    def create_idea(self, *, project: str, title: str, why: str, quote: str | None = None) -> str:
        """Create an ``idea`` in ``project`` under the worker label; returns
        its id (``W-<n>``). Raises :class:`TrackerError` on a refusal."""
        args: dict[str, Any] = {
            "action": "create",
            "project": project,
            "stage": "idea",
            "title": title,
            "why": why,
            "as_worker": WORKER_LABEL,
        }
        if quote:
            args["quote"] = quote
        result = self.call("zk_work", args)
        s = self.structured(result)
        if s.get("ok") is False:
            err = s.get("error") or {}
            raise TrackerRefused(f"znote refused the create: {str(err.get('message', ''))[:300]}")
        for candidate in (s.get("item") or {}).get("id") if isinstance(s.get("item"), dict) else None, s.get("summary"):
            if isinstance(candidate, str):
                m = _ITEM_ID_RE.search(candidate)
                if m:
                    return m.group(0)
        m = _ITEM_ID_RE.search(self.text(result))
        if m:
            return m.group(0)
        raise TrackerError("znote created the item but its reply names no id")
