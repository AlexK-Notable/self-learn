"""inbox_routes.py — the inbox and its decision workspace (attention
round, design r2 §2, §3.5-§3.7; routes contract §4.7; the user's answer 10
and decision C4).

The page one click from the tray: the item list beside the selected item's
workspace, which holds everything needed to decide in one place — the
question in plain words, why it needs the person, what happens meanwhile,
the recommendation and the alternatives, every piece of evidence readable
in place, one-click options plus a reply box, and an "ask about this"
conversation with an agent that already holds the item's context.

The rules this module keeps (the same as :mod:`self_learn_ui.routes`):

- every read goes through :mod:`self_learn_ui.ledger` (``attention --json``,
  ``attention packet <id> --json``, the workspace transcript);
- every mutation goes through the app's :class:`VerbRunner`
  (``attention answer|undo|feedback|seen|run|fix``, ``case refreeze``);
- ask turns and ``attention check-login`` go through the app's
  :class:`self_learn_ui.ask_runner.AskRunner`, never the verb runner, so a
  click never waits behind a model call;
- the reply text reaches the verb as ``--text-file`` (0600, deleted after
  the run), never as argv;
- the server decides nothing the verbs decide: which origin a reply has
  (typed, a draft accepted or edited) is the answer verb's call from the
  ``draft_id`` and the text; this module only forwards them.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import self_learn.primitives.chrono as chrono

from . import ledger, uilog
from .ask_runner import AskRunner, build_ask_runner
from .keymap import inbox_keymap_as_dicts, inbox_keymap_json
from .runner import RunResult

router = APIRouter()

__all__ = [
    "KEY_ORDER",
    "NAVIGATE_PREFIXES",
    "inbox_order",
    "publish_attention",
    "router",
    "starter_chips",
]

#: §2.1 item 1: needs-you by key, in this order.
KEY_ORDER = ("credentials", "broken", "money", "sudo", "conflict", "system-change",
             "foreign-history")
#: The key in words (the chip and the list): mirrors the CLI's own
#: ``attention.KEY_WORDS``; the CLI's sentence is used whenever the packet
#: carries one.
KEY_CHIP = {
    "credentials": "log in",
    "broken": "self-learn is broken",
    "money": "spending money",
    "sudo": "a sudo step",
    "conflict": "two of your statements disagree",
    "system-change": "a change to your system",
    "foreign-history": "another repository's history",
}
CLASS_WORDS = {"needs-you": "Needs you", "decided": "Decided", "approved": "Being carried out"}
#: §4.7 /navigate: the only pages a navigate envelope may send a window to.
NAVIGATE_PREFIXES = ("/inbox", "/overseer-report")
_NAVIGATE_RE = re.compile(r"^/(inbox|overseer-report)(/[A-Za-z0-9._~-]*)*/?$")
_ITEM_ID_RE = re.compile(r"^att-[0-9a-f]{12}$")
_OPTION_ID_RE = re.compile(r"^opt-[a-z0-9-]{1,48}$")
_DRAFT_ID_RE = re.compile(r"^drf-[0-9a-f]{8}$")
#: The approve-with-sudo arming and the "pick an option" line need the plan.
PLAN_LINE = "Your words are recorded and the overseer reads them; to decide, pick an option."
WORDS_ALONE_LINE = ("Recorded as your words. The overseer reads them on its next run. "
                    "To decide, pick an option.")
#: §2.2: the starter chips, fixed per class by code, never by the model.
_CHIPS_NEEDS = ("What happens if I say no?", "Why does this need me?",
                "What exactly would change?", "Draft a reply for me")
_CHIPS_DECIDED = ("Why was this decided?", "What would undo change?")
_CHIPS_APPROVED = ("What will the agent do?", "Can I still change my answer?")


# ------------------------------------------------------------------ pure helpers


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def inbox_order(item: dict) -> tuple:
    """§2.1 item 1, re-applied here so the page never depends on the order
    the reader happened to print: needs-you by key, oldest first; then
    unseen flagged decided items; then other unseen decided items; then
    the work being carried out; then everything already seen, newest first."""
    klass = item.get("class")
    since = str(item.get("since") or item.get("updated_at") or "")
    updated = _parse(item.get("updated_at") or item.get("since"))
    newest_first = -updated.timestamp() if updated is not None else 0.0
    if klass == "needs-you":
        because = item.get("because")
        rank = KEY_ORDER.index(because) if because in KEY_ORDER else len(KEY_ORDER)
        return (0, rank, since, str(item.get("id")))
    if klass == "decided" and not item.get("seen"):
        return (1 if item.get("flagged") else 2, 0, newest_first, str(item.get("id")))
    if klass == "approved":
        return (3, 0, since, str(item.get("id")))
    return (4, 0, newest_first, str(item.get("id")))


def starter_chips(item: dict) -> tuple[str, ...]:
    klass = item.get("class")
    if klass == "decided":
        return _CHIPS_DECIDED
    if klass == "approved":
        return _CHIPS_APPROVED
    return _CHIPS_NEEDS


def _age_words(since: object, now: datetime | None = None) -> str:
    when = _parse(since)
    if when is None:
        return ""
    days = chrono.age_days(when, now or datetime.now(timezone.utc))
    if days < 1:
        return "today"
    if days < 14:
        return f"{days} day{'s' if days != 1 else ''}"
    weeks = days // 7
    return f"{weeks} weeks"


#: ``attention run``'s exit-5 sentences (attention_answers.run): the
#: approved-work one ends "...; open a terminal and run: claude '<line>'",
#: the login one says "run `claude`, then type /login".
_NO_TERMINAL_BRIEF_RE = re.compile(
    r"The brief is at (?P<brief>.+?); open a terminal and run: (?P<cmd>\S.*)$", re.S)
_NO_TERMINAL_LOGIN_RE = re.compile(r"run `(?P<cmd>[^`]+)`, then type /login")
_NO_TERMINAL_ANY_RE = re.compile(r"\brun: (?P<cmd>\S.*)$", re.S)


def no_terminal(message: str) -> dict[str, str | None]:
    """Split the verb's no-terminal sentence into the command alone (the
    copy block holds only what runs when pasted; gate r1 finding 3) and a
    line of prose for around it. With no command in the sentence, the
    sentence itself is the prose and nothing is offered to copy."""
    text = (message or "").strip()
    match = _NO_TERMINAL_BRIEF_RE.search(text)
    if match:
        return {"command": match.group("cmd").strip(),
                "lead": f"The brief it follows is at {match.group('brief').strip()}."}
    match = _NO_TERMINAL_LOGIN_RE.search(text)
    if match:
        return {"command": match.group("cmd").strip(),
                "lead": "Then type /login in that session, and press Check now."}
    match = _NO_TERMINAL_ANY_RE.search(text)
    if match:
        return {"command": match.group("cmd").strip(), "lead": None}
    return {"command": None, "lead": text or None}


def _with_command(run: object, exit_code: int | None = None) -> object:
    """A run result (``{exit, message}``) with ``command``/``lead`` added
    when it is the no-terminal refusal."""
    if not isinstance(run, dict):
        return run
    code = run.get("exit") if exit_code is None else exit_code
    if code != 5:
        return run
    return {**run, **no_terminal(str(run.get("message") or ""))}


def redo_next(item: dict, rows: list[dict]) -> bool:
    """Whether the decided item's next one-click act is redo (gate r1
    finding 4): the reader's ``undo.redo`` when it says so, else the
    item's transcript, whose last undo/redo row is the last act (the
    CLI's own ``attention_answers.redo_offered`` reads the same rows)."""
    undo = item.get("undo") if isinstance(item.get("undo"), dict) else None
    if undo is None:
        return False
    if undo.get("redo"):
        return True
    acts = [r.get("kind") for r in rows if r.get("kind") in ("undo", "redo")]
    return bool(acts) and acts[-1] == "undo"


def _sudo_steps(packet: dict | None) -> list[dict]:
    plan = (packet or {}).get("plan") or {}
    return [s for s in plan.get("steps") or [] if isinstance(s, dict) and s.get("sudo")]


def _chip(item: dict) -> str:
    klass = item.get("class")
    if klass == "needs-you":
        words = KEY_CHIP.get(str(item.get("because")))
        return f"Needs you · {words}" if words else "Needs you"
    return CLASS_WORDS.get(str(klass), str(klass))


def _group(items: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"needs-you": [], "approved": [], "decided": []}
    for item in sorted(items, key=inbox_order):
        out.setdefault(str(item.get("class")), []).append(item)
    return out


def _view_item(item: dict) -> dict:
    """The item plus the words the templates need."""
    return {**item, "chip": _chip(item), "age": _age_words(item.get("since"))}


# ------------------------------------------------------------------ app state


def _home(request: Request) -> Path:
    return request.app.state.env.self_learn_home


def ask_runner(request: Request) -> AskRunner:
    """The app's ask runner (``app.py`` builds it; this fallback keeps a
    bare app working)."""
    runner = getattr(request.app.state, "ask_runner", None)
    if runner is None:
        runner = build_ask_runner(home=_home(request),
                                  publish=request.app.state.app_hub.publish_nowait)
        request.app.state.ask_runner = runner
    return runner


def _templates(request: Request):
    return request.app.state.templates


def _render(request: Request, name: str, ctx: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    context = {
        "request": request,
        "keymap_json": inbox_keymap_json(),
        "keymap_entries": inbox_keymap_as_dicts(),
        "class_words": CLASS_WORDS,
        "plan_line": PLAN_LINE,
        **ctx,
    }
    return _templates(request).TemplateResponse(request, name, context, status_code=status_code)


async def _doc(request: Request) -> ledger.CliRead:
    return await asyncio.to_thread(ledger.attention, _home(request))


async def _packet(request: Request, item_id: str) -> ledger.PacketRead:
    return await asyncio.to_thread(ledger.attention_packet, _home(request), item_id)


def _items(read: ledger.CliRead) -> list[dict]:
    data = read.data if isinstance(read.data, dict) else {}
    return [i for i in data.get("items") or [] if isinstance(i, dict)]


def _find(read: ledger.CliRead, item_id: str) -> dict | None:
    return next((i for i in _items(read) if i.get("id") == item_id), None)


def _list_ctx(read: ledger.CliRead, selected: str | None) -> dict[str, Any]:
    data = read.data if isinstance(read.data, dict) else {}
    items = [_view_item(i) for i in _items(read)]
    groups = _group(items)
    reader_error = read.error or data.get("error")
    return {
        "groups": groups,
        "selected_id": selected,
        "counts": data.get("counts") or {},
        "reader_error": reader_error,
        "ids": [i["id"] for i in items],
    }


def _conversation_ctx(request: Request, item: dict) -> dict[str, Any]:
    rows = ledger.workspace_rows(_home(request), str(item.get("id")))
    visible = [r for r in rows if r.get("kind") != "header"]
    return {
        "rows": visible,
        "redo_next": redo_next(item, rows),
        "in_flight": ask_runner(request).in_flight(str(item.get("id"))),
        "options_by_id": {o.get("id"): o for o in item.get("options") or []},
    }


def _ask_state(packet: dict | None) -> dict[str, Any]:
    conv = (packet or {}).get("conversation") or {}
    unavailable = conv.get("agent_unavailable")
    return {"unavailable": unavailable if unavailable in ("login", "money") else None}


def _workspace_ctx(
    request: Request, item: dict, packet_read: ledger.PacketRead | None, *, deferred: bool,
    answer: dict | None = None,
) -> dict[str, Any]:
    packet = packet_read.data if packet_read is not None else None
    options = item.get("options") or []
    packet_options = {o.get("id"): o for o in (packet or {}).get("options") or []}
    view_options = [{**o, "does": (packet_options.get(o.get("id")) or {}).get("does")}
                    for o in options]
    has_plan = bool((packet or {}).get("plan")) or any(o.get("effect") == "approve" for o in options)
    return {
        "item": _view_item(item),
        "packet": packet,
        "packet_error": None if packet_read is None or packet_read.data is not None else packet_read.error,
        "deferred": deferred,
        "options": view_options,
        "option_labels": {o.get("id"): o.get("label") for o in options},
        "has_plan": has_plan,
        "sudo_steps": _sudo_steps(packet),
        "chips": starter_chips(item),
        "ask": _ask_state(packet),
        "answer_result": answer,
        **_conversation_ctx(request, item),
    }


async def publish_attention(request: Request) -> None:
    """§4.8: an ``attention`` envelope after any attention verb (the page
    refreshes its list from it; the tray reads the same state itself)."""
    read = await _doc(request)
    data = read.data if isinstance(read.data, dict) else {}
    request.app.state.app_hub.publish_nowait({
        "type": "attention", "state": data.get("state", "broken"),
        "counts": data.get("counts") or {}, "ids": [i.get("id") for i in _items(read)],
    })


async def attention_ticker(app, *, interval: float = 30.0) -> None:
    """§4.8: every 30 s while a client is connected, the attention state.
    Started by ``app.py``'s lifespan; it reads nothing while no page is open."""
    hub = app.state.app_hub
    home = app.state.env.self_learn_home
    while True:
        await asyncio.sleep(interval)
        if hub.subscriber_count == 0:
            continue
        try:
            read = await asyncio.to_thread(ledger.attention, home)
        except Exception as exc:  # noqa: BLE001 - a tick never kills the ticker
            uilog.log(f"attention ticker: read failed: {exc}")
            continue
        data = read.data if isinstance(read.data, dict) else {}
        hub.publish_nowait({"type": "attention", "state": data.get("state", "broken"),
                            "counts": data.get("counts") or {},
                            "ids": [i.get("id") for i in _items(read)]})


async def _run_verb(request: Request, argv: list[str]) -> RunResult:
    result = await request.app.state.runner.run(argv)
    try:
        await publish_attention(request)
    except Exception as exc:  # noqa: BLE001 - the verb's outcome stands regardless
        uilog.log(f"inbox: attention envelope not published: {exc}")
    return result


def _reply_file(request: Request, text: str) -> Path:
    """``<cache>/ui/reply-<random>.txt``, 0600 (§4.7): the reply reaches the
    verb as a file, never argv. Deleted by the caller after the run."""
    from self_learn import attention as sl_attention

    folder = Path(sl_attention.cache_dir(_home(request))) / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"reply-{secrets.token_hex(8)}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _verb_message(result: RunResult) -> str:
    text = (result.stderr or "").strip() or (result.stdout or "").strip()
    return text or f"the verb exited {result.exit_code}"


# ------------------------------------------------------------------ pages


@router.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request) -> Response:
    read = await _doc(request)
    ctx = _list_ctx(read, None)
    items = [i for group in ctx["groups"].values() for i in group]
    if items and not ctx["reader_error"]:
        first = sorted(items, key=inbox_order)[0]
        return RedirectResponse(url=f"/inbox/{first['id']}", status_code=303)
    return _render(request, "inbox.html", {**ctx, "item": None})


@router.get("/inbox/list", response_class=HTMLResponse)
async def inbox_list(request: Request, selected: str | None = None) -> HTMLResponse:
    """The list alone (the page refreshes it on an ``attention`` envelope)."""
    read = await _doc(request)
    return _render(request, "partials/workspace_list.html", _list_ctx(read, selected))


def inbox_link(read: ledger.CliRead) -> dict[str, Any]:
    """The front page's "Inbox (N)" (design r2 §4.7): N is the items that
    need you plus the new decisions made for you; "?" when the inbox could
    not be read (the inbox page then says why)."""
    data = read.data if isinstance(read.data, dict) else None
    if data is None or read.error or data.get("error"):
        return {"count": 0, "label": "?"}
    counts = data.get("counts") or {}
    count = int(counts.get("needs_you") or 0) + int(counts.get("new") or 0)
    return {"count": count, "label": str(count)}


@router.get("/inbox/count", response_class=HTMLResponse)
async def inbox_count(request: Request) -> HTMLResponse:
    """The front page's link, filled in after the page loaded, so the front
    page itself never waits on ``attention --json`` (gate r1 NIT 2)."""
    read = await _doc(request)
    return _render(request, "partials/workspace_inbox_link.html", {"inbox": inbox_link(read)})


async def _workspace_for(request: Request, item_id: str, *, budget: float | None):
    read = await _doc(request)
    item = _find(read, item_id)
    if item is None:
        return read, None, None, False
    task = asyncio.ensure_future(_packet(request, item_id))
    try:
        packet_read = await (asyncio.wait_for(asyncio.shield(task), timeout=budget)
                             if budget is not None else task)
        deferred = False
    except TimeoutError:
        packet_read, deferred = None, True
    return read, item, packet_read, deferred


@router.get("/inbox/{item_id}", response_class=HTMLResponse)
async def inbox_item(request: Request, item_id: str) -> HTMLResponse:
    read, item, packet_read, deferred = await _workspace_for(request, item_id, budget=1.5)
    ctx = _list_ctx(read, item_id)
    if item is None:
        return _render(request, "inbox.html", {**ctx, "item": None, "gone": item_id},
                       status_code=404)
    return _render(request, "inbox.html",
                   {**ctx, **_workspace_ctx(request, item, packet_read, deferred=deferred)})


@router.get("/inbox/{item_id}/workspace", response_class=HTMLResponse)
async def inbox_workspace(request: Request, item_id: str) -> HTMLResponse:
    read, item, packet_read, deferred = await _workspace_for(request, item_id, budget=1.5)
    if item is None:
        return _render(request, "partials/workspace_gone.html", {"gone": item_id}, status_code=404)
    return _render(request, "partials/workspace.html",
                   _workspace_ctx(request, item, packet_read, deferred=deferred))


@router.get("/inbox/{item_id}/evidence", response_class=HTMLResponse)
async def inbox_evidence(request: Request, item_id: str) -> HTMLResponse:
    read, item, packet_read, _deferred = await _workspace_for(request, item_id, budget=None)
    if item is None:
        return _render(request, "partials/workspace_gone.html", {"gone": item_id}, status_code=404)
    return _render(request, "partials/workspace_packet.html",
                   _workspace_ctx(request, item, packet_read, deferred=False))


@router.get("/inbox/{item_id}/conversation", response_class=HTMLResponse)
async def inbox_conversation(request: Request, item_id: str) -> HTMLResponse:
    read = await _doc(request)
    item = _find(read, item_id) or {"id": item_id, "options": []}
    return _render(request, "partials/workspace_conversation.html",
                   {"item": _view_item(item), **_conversation_ctx(request, item)})


@router.get("/overseer-report", response_class=HTMLResponse)
@router.get("/overseer-report/{date}", response_class=HTMLResponse)
async def overseer_report(request: Request, date: str | None = None) -> HTMLResponse:
    text, error = ledger.overseer_report(_home(request), date)
    return _render(request, "overseer_report.html", {
        "report_text": text, "report_error": error, "date": date,
        "dates": ledger.overseer_report_dates(_home(request)),
    }, status_code=200 if text is not None or date is None else 404)


# ------------------------------------------------------------------ mutations


@router.post("/inbox/seen-all", response_class=HTMLResponse)
async def inbox_seen_all(request: Request, selected: str | None = Form(None)) -> HTMLResponse:
    await _run_verb(request, ["attention", "seen", "--all-decided"])
    read = await _doc(request)
    return _render(request, "partials/workspace_list.html", _list_ctx(read, selected))


@router.post("/inbox/{item_id}/seen")
async def inbox_seen(request: Request, item_id: str) -> Response:
    if not _ITEM_ID_RE.match(item_id):
        return Response(status_code=400)
    await request.app.state.runner.run(["attention", "seen", item_id])
    return Response(status_code=204)


def _answer_partial(request: Request, item: dict, packet_read: ledger.PacketRead | None,
                    answer: dict, *, list_read: ledger.CliRead | None = None,
                    status_code: int = 200) -> HTMLResponse:
    ctx = _workspace_ctx(request, item, packet_read, deferred=False, answer=answer)
    if list_read is not None:
        ctx.update({"oob_list": True, **_list_ctx(list_read, item.get("id"))})
    return _render(request, "partials/workspace_answer.html", ctx, status_code=status_code)


@router.post("/inbox/{item_id}/answer", response_class=HTMLResponse)
async def inbox_answer(
    request: Request,
    item_id: str,
    option: str | None = Form(None),
    text: str | None = Form(None),
    draft_id: str | None = Form(None),
    confirm: str | None = Form(None),
) -> HTMLResponse:
    read = await _doc(request)
    item = _find(read, item_id)
    if item is None:
        return _render(request, "partials/workspace_gone.html", {"gone": item_id}, status_code=404)
    option = (option or "").strip() or None
    draft_id = (draft_id or "").strip() or None
    text = text if text is not None and text.strip() else None
    packet_read: ledger.PacketRead | None = None

    def fail(message: str, status: int = 200) -> HTMLResponse:
        return _answer_partial(request, item, packet_read,
                               {"state": "error", "message": message, "text": text,
                                "draft_id": draft_id}, status_code=status)

    if option is not None and not _OPTION_ID_RE.match(option):
        return fail("That option is not one this item offers.", 400)
    if draft_id is not None and not _DRAFT_ID_RE.match(draft_id):
        return fail("That draft is not one this item holds.", 400)
    if option is None and text is None and draft_id is None:
        return fail("Pick an option or write your answer first.")
    chosen = next((o for o in item.get("options") or [] if o.get("id") == option), None)
    if option is not None and chosen is None and option != "opt-ran-sudo":
        return fail("That option is not one this item offers.", 400)
    if chosen is not None and chosen.get("note") == "required" and text is None:
        return fail(f"“{chosen.get('label')}” needs a note: write it in the box, then click it "
                    "again.")
    armed = confirm == "1"
    if chosen is not None and not armed:
        if chosen.get("confirm") or chosen.get("effect") == "register":
            # §3.7 "This registers <path> in git mode. Confirm?": the path
            # and mode are in the question itself (the overseer's validator
            # refuses an ask whose text does not name the register path
            # exactly and its mode), so the armed line repeats the question
            # rather than a path field §4.1/§4.3 do not carry. The packet's
            # full question, not the list title: the title is cut at 200
            # characters and the path can sit past the cut (gate r2 NIT A).
            packet_read = await _packet(request, item_id)
            packet_q = (packet_read.data or {}).get("question") if isinstance(
                packet_read.data, dict) else None
            question = packet_q if isinstance(packet_q, str) and packet_q.strip() else item.get("title")
            return _answer_partial(request, item, packet_read, {
                "state": "armed", "option": chosen, "text": text, "draft_id": draft_id,
                "message": f"“{chosen.get('label')}” answers “{question}”, and it acts "
                           "outside self-learn once you confirm it. Confirm?",
            })
        if chosen.get("effect") == "approve":
            packet_read = await _packet(request, item_id)
            sudo = _sudo_steps(packet_read.data)
            if sudo:
                return _answer_partial(request, item, packet_read, {
                    "state": "armed", "option": chosen, "text": text, "draft_id": draft_id,
                    "sudo": sudo,
                    "message": "You run these yourself; the agent does the rest after you click "
                               "I ran it.",
                })
    argv = ["attention", "answer", item_id]
    if option is not None:
        argv += ["--option", option]
    reply_path: Path | None = None
    try:
        if text is not None:
            reply_path = _reply_file(request, text)
            argv += ["--text-file", str(reply_path)]
        if draft_id is not None:
            argv += ["--draft", draft_id]
        if armed and chosen is not None and (chosen.get("confirm") or chosen.get("effect") == "register"):
            argv.append("--confirm")
        argv.append("--json")
        result = await _run_verb(request, argv)
    finally:
        if reply_path is not None:
            try:
                reply_path.unlink()
            except OSError:
                pass
    if not result.ok:
        return fail(_verb_message(result))
    evidence = result.evidence or {}
    state = evidence.get("state")
    # No option chosen (typed words, or an agent draft sent without one):
    # on an item with a plan that decides nothing (§1.3), and the page says so.
    no_option = option is None
    list_read = await _doc(request)
    fresh = _find(list_read, item_id)
    # The answer can move the item on: an approval becomes a "Being carried
    # out" item with its own id, an answered ask leaves the list. Its old
    # options are then not offered again on this page.
    successor = None if fresh is not None else next(
        (_view_item(i) for i in _items(list_read)
         if i.get("subject") == item.get("subject") and i.get("id") != item_id), None)
    return _answer_partial(request, fresh or item, packet_read, {
        "state": "recorded",
        "recorded_as": evidence.get("recorded_as") or "",
        "item_state": state,
        "closed": fresh is None,
        "successor": successor,
        "words_alone_on_plan": no_option and state == "open" and (
            any(o.get("effect") == "approve" for o in item.get("options") or [])
        ),
        "run": _with_command(evidence.get("run")),
        "warnings": evidence.get("warnings") or [],
        "registration": evidence.get("registration"),
    }, list_read=list_read)


@router.post("/inbox/{item_id}/undo", response_class=HTMLResponse)
async def inbox_undo(request: Request, item_id: str, redo: str | None = Form(None)) -> HTMLResponse:
    read = await _doc(request)
    item = _find(read, item_id)
    if item is None:
        return _render(request, "partials/workspace_gone.html", {"gone": item_id}, status_code=404)
    argv = ["attention", "undo", item_id] + (["--redo"] if redo == "1" else [])
    result = await _run_verb(request, argv)
    if not result.ok:
        return _answer_partial(request, item, None,
                               {"state": "error", "message": _verb_message(result)})
    # An undo can move the item on (reopening a withdrawn ask makes it a
    # needs-you item again, under its own id): the page then says so, so
    # its own click is never reported as "resolved elsewhere".
    list_read = await _doc(request)
    fresh = _find(list_read, item_id)
    successor = None if fresh is not None else next(
        (_view_item(i) for i in _items(list_read)
         if i.get("subject") == item.get("subject") and i.get("id") != item_id), None)
    answer = {"state": "undone", "redo": redo == "1", "message": (result.stdout or "").strip(),
              "closed": fresh is None, "successor": successor}
    return _answer_partial(request, fresh or item, None, answer, list_read=list_read)


@router.post("/inbox/{item_id}/feedback", response_class=HTMLResponse)
async def inbox_feedback(request: Request, item_id: str, wanted: str = Form(...)) -> HTMLResponse:
    if wanted not in ("needs-you", "decided", "silent"):
        return HTMLResponse("unknown feedback", status_code=400)
    result = await _run_verb(request, ["attention", "feedback", item_id, "--wanted", wanted])
    return _render(request, "partials/workspace_feedback.html", {
        "ok": result.ok, "message": (result.stdout if result.ok else _verb_message(result)).strip(),
        "item_id": item_id,
    })


@router.post("/inbox/{item_id}/run", response_class=HTMLResponse)
async def inbox_run(request: Request, item_id: str, login: str | None = Form(None)) -> HTMLResponse:
    read = await _doc(request)
    item = _find(read, item_id)
    if item is None:
        return _render(request, "partials/workspace_gone.html", {"gone": item_id}, status_code=404)
    argv = ["attention", "run", item_id] + (["--login"] if login == "1" else [])
    result = await _run_verb(request, argv)
    message = ((result.stdout if result.ok else result.stderr) or "").strip() or _verb_message(result)
    split = no_terminal(message) if result.exit_code == 5 else {"command": None, "lead": None}
    return _render(request, "partials/workspace_run.html", {
        "item": _view_item(item), "exit": result.exit_code, "login": login == "1",
        "message": message, **split,
    })


@router.post("/inbox/{item_id}/fix", response_class=HTMLResponse)
async def inbox_fix(request: Request, item_id: str, option: str = Form(...)) -> HTMLResponse:
    read = await _doc(request)
    item = _find(read, item_id)
    if item is None:
        return _render(request, "partials/workspace_gone.html", {"gone": item_id}, status_code=404)
    offered = {o.get("id") for o in item.get("options") or [] if o.get("via") == "fix"}
    if option not in offered:
        return _render(request, "partials/workspace_run.html", {
            "item": _view_item(item), "exit": 3, "login": False,
            "message": "That option is not one this item offers."}, status_code=400)
    argv = ["attention", "fix", item_id, "--option", option]
    result = await _run_verb(request, argv)
    return _render(request, "partials/workspace_run.html", {
        "item": _view_item(item), "exit": result.exit_code, "login": False, "fix": True,
        "message": ((result.stdout if result.ok else result.stderr) or "").strip()
        or _verb_message(result),
    })


@router.post("/inbox/{item_id}/check-login", response_class=HTMLResponse)
async def inbox_check_login(request: Request, item_id: str) -> HTMLResponse:
    outcome = await ask_runner(request).check_login()
    try:
        await publish_attention(request)
    except Exception as exc:  # noqa: BLE001
        uilog.log(f"inbox: attention envelope not published: {exc}")
    next_jobs = (await asyncio.to_thread(ledger.scheduler_next, _home(request))
                 if outcome.ok else None)
    return _render(request, "partials/workspace_login.html", {
        "ok": outcome.ok, "exit": outcome.exit_code, "message": outcome.message,
        "item_id": item_id, "next_jobs": next_jobs,
    })


@router.post("/inbox/{item_id}/ask", response_class=HTMLResponse)
async def inbox_ask(request: Request, item_id: str, message: str = Form("")) -> HTMLResponse:
    if not _ITEM_ID_RE.match(item_id):
        return HTMLResponse("unknown item", status_code=400)
    message = message.strip()
    if not message:
        return _render(request, "partials/workspace_ask_refused.html",
                       {"message": "Write a question first."}, status_code=400)
    runner = ask_runner(request)
    refused = runner.refusal(item_id)
    if refused is not None:
        return _render(request, "partials/workspace_ask_refused.html", {"message": refused},
                       status_code=409)
    read = await _doc(request)
    item = _find(read, item_id) or {}
    header = {"item_kind": item.get("kind"), "subject": item.get("subject"),
              "title": item.get("title")}
    refused = await runner.start(item_id, message, header=header)
    if refused is not None:
        return _render(request, "partials/workspace_ask_refused.html", {"message": refused},
                       status_code=409)
    return _render(request, "partials/workspace_ask_turn.html",
                   {"item_id": item_id, "message": message})


@router.post("/inbox/{item_id}/ask/stop", response_class=HTMLResponse)
async def inbox_ask_stop(request: Request, item_id: str) -> HTMLResponse:
    stopped = await ask_runner(request).stop(item_id)
    return _render(request, "partials/workspace_ask_refused.html", {
        "message": "Stopping the agent's answer…" if stopped else "Nothing was being answered.",
    })


# ------------------------------------------------------------------ navigate


@router.post("/navigate")
async def navigate(request: Request, path: str = Form("")) -> Response:
    """§4.7 (critique 10): ``self-learn-ui-open --page <path>`` tells an open
    window where to go. 204 when at least one connected page got it; 409
    when none is connected (the launcher then opens a window itself); 400
    for anything but an inbox or weekly-report path."""
    if not _NAVIGATE_RE.match(path) or "//" in path or ".." in path:
        return Response("navigate: only /inbox and /overseer-report paths", status_code=400)
    hub = request.app.state.app_hub
    if hub.subscriber_count == 0:
        return Response(status_code=409)
    await hub.publish({"type": "navigate", "path": path})
    return Response(status_code=204)
