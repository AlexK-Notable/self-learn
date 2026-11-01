"""summary_routes.py — the "In short" box on reports (humane UI lane 5,
proposal §7; S-NEXT-humane-l5).

Three kinds of summary fill the box, in this order of preference:

- **scheduled**: the overseer's own ``## In short`` section of a weekly
  report, written inside its weekly run (no extra model call);
- **counted**: a nightly review's counts in words, built by the CLI's
  packet from the run's own record (``run.in_short``; no model at all);
- **on demand**: a summary written by ``self-learn summarise`` when the
  person clicks "Summarise this", saved in the ledger against the report's
  exact text (``self_learn.summarise``).

**Nothing starts on a page view.** ``GET /summary/<kind>/<ref>`` and every
page that includes the box only READ: the saved summary for the report's
current hash (``summarise.state``, files only) and the runner's in-memory
view of a run in flight. Only ``POST /summary/<kind>/<ref>`` (the button)
starts the verb, through the inbox's ask runner (its cap of two model turns
in flight, its watchdog, its Stop). While a run is in flight the box asks
for itself again every second (htmx), so the text streams in without a new
script, and stops asking once the run ends.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from . import ledger
from .ask_runner import AskRunner, summary_key

__all__ = ["box_for_item", "box_for_report", "router"]

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ITEM_RE = re.compile(r"^att-[0-9a-f]{12}$")
#: The item kinds whose page carries the box (lane 3's slots).
REPORT_ITEM_KINDS = ("decided.steward-run", "decided.overseer-run")
#: What the box says under the button: the cost, in words.
COST_LINE = ("One model call on your Claude plan (no API charge), usually 10 to 30 seconds. "
             "The summary is saved, so it is only written once for this report.")
MONEY_LINE = "Summaries are off: this setup would bill money."


def _home(request: Request) -> Path:
    return request.app.state.env.self_learn_home


def _runner(request: Request) -> AskRunner:
    from .inbox_routes import ask_runner

    return ask_runner(request)


def _valid(kind: str, ref: str) -> bool:
    if kind == "overseer-report":
        return ref == "latest" or bool(_DATE_RE.match(ref))
    if kind == "inbox-item":
        return bool(_ITEM_RE.match(ref))
    return False


def when_words(at: object, now: datetime | None = None) -> str | None:
    """``"today at 16:02"``, ``"Sun 25 Oct at 16:02"``, in local time."""
    if not isinstance(at, str) or not at:
        return None
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone()
    today = (now or datetime.now(timezone.utc)).astimezone().date()
    clock = local.strftime("%H:%M")
    if local.date() == today:
        return f"today at {clock}"
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')} at {clock}"


def _cost_words(record: dict) -> str | None:
    parts = []
    cost = record.get("cost_usd")
    if isinstance(cost, (int, float)):
        parts.append(f"${cost:.2f} notional, on your plan")
    secs = record.get("duration_secs")
    if isinstance(secs, (int, float)):
        parts.append(f"{secs:.0f} seconds")
    return ", ".join(parts) or None


def _summary_view(record: dict | None) -> dict | None:
    if not isinstance(record, dict) or not isinstance(record.get("text"), str):
        return None
    return {**record, "when": when_words(record.get("created_at")),
            "cost_words": _cost_words(record)}


def _box(request: Request, kind: str, ref: str, *, state: dict | None,
         scheduled: str | None = None, counted: str | None = None) -> dict[str, Any]:
    """The box's view. *state* is ``summarise.state`` (files only), or
    ``None`` when only the runner is consulted (a poll while it runs)."""
    view = _runner(request).summary_view(summary_key(kind, ref))
    running = view if view is not None and view.get("running") else None
    result = view.get("result") if view is not None and not view.get("running") else None
    summary = _summary_view((state or {}).get("summary"))
    if summary is None and isinstance(result, dict) and result.get("ev") == "done":
        # Just written by a run of this page's runner: shown at once, even
        # before (or without) the ledger read catching up.
        raw = result.get("summary")
        record: dict = raw if isinstance(raw, dict) else {}
        if not record or record.get("source_sha256") in (None, (state or {}).get("sha256")):
            summary = _summary_view({**record, "text": record.get("text") or result.get("text")})
    failed = None
    if isinstance(result, dict) and result.get("ev") == "error" and summary is None:
        failed = {"code": result.get("code"),
                  "message": MONEY_LINE if result.get("code") == "money"
                  else str(result.get("message") or "the summary could not be written")}
    stale = _summary_view((state or {}).get("stale")) if summary is None else None
    error = (state or {}).get("error")
    return {
        "kind": kind, "ref": ref, "url": f"/summary/{kind}/{ref}",
        "scheduled": scheduled, "counted": counted, "summary": summary, "stale": stale,
        "running": running, "failed": failed, "error": error,
        # The button: a report with no summary of any kind yet, or a
        # nightly review that has only its counts ("in words").
        "offer": (running is None and summary is None and scheduled is None
                  and error is None and (failed or {}).get("code") != "money"),
        "cost_line": COST_LINE,
    }


def box_for_report(request: Request, report_text: str | None, date: str | None) -> dict | None:
    """The weekly report page's box (and an overseer-run item's)."""
    if report_text is None:
        return None
    from self_learn import summarise

    ref = summarise.report_date(report_text) or date or "latest"
    scheduled = summarise.scheduled_in_short(report_text)
    state = summarise.state(_home(request), "overseer-report", ref, text=report_text)
    return _box(request, "overseer-report", ref, state=state, scheduled=scheduled)


def box_for_item(request: Request, item: dict, packet: dict | None, *,
                 deferred: bool = False) -> dict | None:
    """A report item's box: a nightly review's counts and its on-demand
    summary; an overseer run's weekly report box. ``lazy`` when the packet
    has not arrived yet (the box then loads itself)."""
    kind = item.get("kind")
    item_id = str(item.get("id") or "")
    if kind not in REPORT_ITEM_KINDS or not _ITEM_RE.match(item_id):
        return None
    if kind == "decided.overseer-run":
        date = (item.get("source") or {}).get("report") if isinstance(item.get("source"), dict) else None
        date = date or item.get("report")
        if not isinstance(date, str) or not _DATE_RE.match(date):
            return None
        text, _error = ledger.overseer_report(_home(request), date)
        return box_for_report(request, text, date)
    if packet is None:
        if deferred:
            return {"lazy": True, "url": f"/summary/inbox-item/{item_id}"}
        return None
    from self_learn import summarise

    raw_run = packet.get("run")
    run: dict = raw_run if isinstance(raw_run, dict) else {}
    counted = run.get("in_short") if isinstance(run.get("in_short"), str) else None
    state = summarise.state(_home(request), "inbox-item", item_id, packet=packet)
    return _box(request, "inbox-item", item_id, state=state, counted=counted)


def _render(request: Request, box: dict | None, status_code: int = 200) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "partials/in_short.html", {"request": request, "in_short": box},
        status_code=status_code)


async def _full_box(request: Request, kind: str, ref: str) -> dict | None:
    home = _home(request)
    if kind == "overseer-report":
        text, _error = ledger.overseer_report(home, None if ref == "latest" else ref)
        if text is None and ref != "latest":
            # The page drew the latest report, named by the date in its
            # first line; read it back the same way.
            latest, _error = ledger.overseer_report(home, None)
            from self_learn import summarise

            if latest is not None and summarise.report_date(latest) == ref:
                text = latest
        return box_for_report(request, text, None if ref == "latest" else ref)
    read = await asyncio.to_thread(ledger.attention, home)
    data = read.data if isinstance(read.data, dict) else {}
    item = next((i for i in data.get("items") or [] if isinstance(i, dict) and i.get("id") == ref),
                None) or {"id": ref, "kind": "decided.steward-run"}
    packet_read = await asyncio.to_thread(ledger.attention_packet, home, ref)
    return box_for_item(request, item, packet_read.data)


@router.get("/summary/{kind}/{ref}", response_class=HTMLResponse)
async def summary_box(request: Request, kind: str, ref: str) -> HTMLResponse:
    """The box, read only: never starts anything."""
    if not _valid(kind, ref):
        return HTMLResponse("unknown report", status_code=404)
    view = _runner(request).summary_view(summary_key(kind, ref))
    if view is not None and view.get("running"):
        return _render(request, _box(request, kind, ref, state=None))
    return _render(request, await _full_box(request, kind, ref))


@router.post("/summary/{kind}/{ref}", response_class=HTMLResponse)
async def summary_start(request: Request, kind: str, ref: str,
                        again: str | None = Form(None)) -> HTMLResponse:
    """The "Summarise this" button (and "Write it again"): start one run.
    A second click while one runs gets the running one (409)."""
    if not _valid(kind, ref):
        return HTMLResponse("unknown report", status_code=404)
    runner = _runner(request)
    refused = await runner.start_summary(kind, ref, again=again == "1")
    box = _box(request, kind, ref, state=None)
    if refused is not None:
        if box["running"] is None:
            box["failed"] = {"code": "busy", "message": refused}
            box["offer"] = True
        return _render(request, box, status_code=409)
    return _render(request, box)


@router.post("/summary/{kind}/{ref}/stop", response_class=HTMLResponse)
async def summary_stop(request: Request, kind: str, ref: str) -> HTMLResponse:
    if not _valid(kind, ref):
        return HTMLResponse("unknown report", status_code=404)
    await _runner(request).stop(summary_key(kind, ref))
    return _render(request, await _full_box(request, kind, ref))
