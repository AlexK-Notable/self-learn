"""routes.py — Front/Bucket/Detail/report routes + the action-bar
arm/disarm/confirm machine (task U3, 09 §2/§3, 10 §1/§3 U3 row).

ALL reads funnel through :mod:`self_learn_ui.ledger` (U2) — this module
never opens a ledger file or shells the CLI directly. ALL verb execution
funnels through the :class:`self_learn_ui.runner.VerbRunner` seam — this
module never spawns a subprocess directly (that's U4's job; here it is
always `request.app.state.runner`, a `FakeRunner` in tests).

Arm-then-confirm is server-rendered, not a client-side JS state machine
(09 §1): ``POST .../action/arm`` renders the armed action-bar fragment
(verb + id + destination + note-presence — never executes anything);
``POST .../action/disarm`` renders it back to normal; ``POST
.../action/confirm`` re-submits the SAME fields and actually runs the
verb. This keeps every interaction round-trip testable with a single
httpx POST + an argv assertion against the fake runner — no browser
needed for T-A (09 §7 / 10 §2 T-A).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.responses import StreamingResponse

from . import ledger, models, pane, proposals, rendering
from .keymap import keymap_as_dicts, keymap_json
from .models import PARAMETER_FREE_DESTINATIONS
from .sse import envelope_applying, envelope_banner, envelope_bulk_progress, event_stream

router = APIRouter()

#: 09 §11 Y-9: never a raw id as a row's leading text. Sentinel notices
#: rendered via a query-string flag — deliberately NOT a session/cookie
#: mechanism (09 §3: "no state that isn't a file", and a flash banner is
#: emphemeral UI chrome, not ledger state).
NOTICE_RESOLVED_ELSEWHERE = "resolved-elsewhere"
NOTICE_BUCKET_CLEAR = "bucket-clear"
NOTICE_NOT_FOUND = "not-found"

_VERB_LABELS = {
    "route": "Approve",
    "reject": "Deny",
    "defer": "Defer",
    "graduate": "Graduate",
    "confirm-recurrence": "Confirm recurrence",
    "link-contradicts": "Link contradiction",
    "followup-done": "Mark follow-up done",
}

_KNOWN_VERBS = frozenset(_VERB_LABELS)


# ------------------------------------------------------------- pure helpers


def build_argv(
    verb: str,
    record_id: str,
    *,
    dest: str | None = None,
    collapse: str | None = None,
    note: str | None = None,
    until: str | None = None,
    event: str | None = None,
    tolerate: bool = False,
    target: str | None = None,
    no_push: bool = False,
) -> list[str]:
    """The exact CLI argv one verb call maps to (matches
    ``plugins/self-learn/cli/src/self_learn/cli.py``'s parser verbatim —
    never re-derived elsewhere). Raises :class:`ValueError` on an unknown
    verb name (a programming error, not a user-reachable state — routes
    validate ``verb`` against :data:`_KNOWN_VERBS` before ever calling
    this)."""
    if verb == "route":
        argv = ["route", record_id]
        if dest:
            argv += ["--dest", dest]
        if collapse:
            argv += ["--collapse", collapse]
    elif verb == "reject":
        argv = ["reject", record_id]
    elif verb == "defer":
        argv = ["defer", record_id]
        if until:
            argv += ["--until", until]
    elif verb == "graduate":
        argv = ["graduate", record_id]
    elif verb == "confirm-recurrence":
        argv = ["confirm-recurrence", record_id, "--event", event or ""]
        if tolerate:
            argv.append("--tolerate")
    elif verb == "link-contradicts":
        argv = ["link", "contradicts", record_id, target or ""]
    elif verb == "followup-done":
        argv = ["followup", "done", record_id]
    else:
        raise ValueError(f"unknown verb: {verb!r}")
    if note:
        argv += ["--note", note]
    if no_push:
        argv.append("--no-push")
    return argv


def cycle_destination(current: str | None) -> str:
    """09 §2.3's `o` pin: cycle among :data:`PARAMETER_FREE_DESTINATIONS`
    ONLY — ``new-skill``/``hook`` are structurally unreachable from this
    function, which is what "the cycle skips them" means in practice
    (there is nothing to skip — they were never in the cycle set)."""
    if current not in PARAMETER_FREE_DESTINATIONS:
        return PARAMETER_FREE_DESTINATIONS[0]
    idx = PARAMETER_FREE_DESTINATIONS.index(current)
    return PARAMETER_FREE_DESTINATIONS[(idx + 1) % len(PARAMETER_FREE_DESTINATIONS)]


def next_record_url(home: Path, bucket_name: str, resolved_id: str) -> str:
    """09 §2 / P3-9's "flow after resolution": the next pending record in
    the SAME bucket (any destination group, oldest-first per the CLI's own
    list order), excluding *resolved_id* itself. ``/?notice=bucket-clear``
    when nothing remains — Front, not the now-empty bucket page (09 §1:
    "if the bucket empties, return to Front with a one-line bucket-clear
    banner")."""
    read = ledger.list_items(home, include_deferred=False)
    if not read.ok or not read.data:
        return f"/?notice={NOTICE_BUCKET_CLEAR}"
    remaining = [
        item
        for item in read.data
        if item.get("bucket") == bucket_name and item.get("id") != resolved_id
    ]
    if not remaining:
        return f"/?notice={NOTICE_BUCKET_CLEAR}"
    return f"/record/{remaining[0]['id']}"


# ---------------------------------------------------------------- template ctx


def _base_ctx(request: Request) -> dict[str, Any]:
    return {
        "request": request,
        "keymap_json": keymap_json(),
        "keymap_entries": keymap_as_dicts(),
    }


def _templates(request: Request):
    return request.app.state.templates


def _home(request: Request) -> Path:
    return request.app.state.env.self_learn_home


def _pane_manager(request: Request) -> "pane.PaneManager | None":
    """``None`` until the orchestrator applies U6's one-line app.py
    wiring (see ``pane.build_pane_manager``'s docstring) — every pane
    route degrades to a 503 rather than crashing when it's absent, so
    the rest of the app (approve/deny/defer/graduate, per 09 §5's
    invariant: "adjudication never depends on any optional subsystem")
    keeps working even before that line lands."""
    return getattr(request.app.state, "pane_manager", None)


def _render(request: Request, name: str, ctx: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    context = {**_base_ctx(request), **ctx}
    return _templates(request).TemplateResponse(request, name, context, status_code=status_code)


# --------------------------------------------------------------------- Front


@router.get("/", response_class=HTMLResponse)
def front(request: Request, notice: str | None = None) -> HTMLResponse:
    home = _home(request)
    list_read = ledger.list_items(home, include_deferred=True)
    status_read = ledger.status(home)
    report_read = ledger.report(home)
    mine_read = ledger.mine_status(home)
    model = models.build_front_model(
        list_read,
        status_read,
        report_read,
        mine_read,
        sentinel_mtime=ledger.sentinel_mtime(),
    )
    return _render(
        request,
        "index.html",
        {"model": model, "notice": notice},
    )


# -------------------------------------------------------------------- Bucket


def _find_bucket(home: Path, scope: str, name: str) -> ledger.Bucket | None:
    for bucket in ledger.discover_buckets(home):
        if bucket.scope == scope and bucket.name == name:
            return bucket
    return None


@router.get("/bucket/{scope}/{name}", response_class=HTMLResponse)
def bucket_page(request: Request, scope: str, name: str, notice: str | None = None) -> Response:
    home = _home(request)
    bucket = _find_bucket(home, scope, name)
    if bucket is None:
        return RedirectResponse(url=f"/?notice={NOTICE_NOT_FOUND}", status_code=303)

    list_read = ledger.list_items(home, include_deferred=True)
    items = [
        item for item in (list_read.data or []) if item.get("bucket") == name
    ] if list_read.ok else []

    proposals_by_id: dict[str, dict | None] = {}
    for item in items:
        if item.get("has_proposal"):
            proposal, _err = ledger.read_proposal_raw(bucket.path, item["id"])
            proposals_by_id[item["id"]] = proposal

    clusters_raw = ledger.read_clusters(bucket.path)
    registry = ledger.read_registry()
    host_registered = items[0].get("host_registered", True) if items else True
    host_add_command = models.host_add_command(scope, ledger.project_path_for(bucket.path))

    model = models.build_bucket_model(
        name,
        scope,
        items,
        proposals_by_id,
        clusters_raw,
        registry,
        host_registered=host_registered,
        host_add_command=host_add_command,
    )

    # Y-13: the bucket pane split (09 §2.2) + any pending proposal on a
    # record of THIS bucket (rendered adjacent to the pane).
    manager = _pane_manager(request)
    key = _bucket_pane_key(scope, name)
    pane_snapshot = manager.snapshot(key) if manager is not None else None
    pane_split = pane_snapshot is not None and pane_snapshot.state != pane.STATE_IDLE
    slot = _proposal_slot(request)
    bucket_proposal = None
    if (
        slot is not None
        and slot.current is not None
        and slot.current.bucket_name == name
        and slot.current.bucket_scope == scope
    ):
        bucket_proposal = slot.current

    return _render(
        request,
        "bucket.html",
        {
            "model": model,
            "notice": notice,
            "list_error": list_read.error,
            "pane": pane_snapshot,
            "pane_split": pane_split,
            "pane_base": f"/bucket/{scope}/{name}/pane",
            "bucket_pane_key": key,
            "bucket_proposal": bucket_proposal,
            "proposal_verb_label": (
                _VERB_LABELS.get(bucket_proposal.verb, bucket_proposal.verb)
                if bucket_proposal is not None
                else None
            ),
        },
    )


# --------------------------------------------------------------------- Detail


def _load_detail(home: Path, record_id: str):
    """Returns ``(location, record, item, bucket)`` or ``None`` triples
    on any failure to resolve — callers branch on ``None``."""
    location = ledger.locate_record(home, record_id)
    if location is None:
        return None
    record = ledger.read_record(location.path)
    if record is None:
        return None
    list_read = ledger.list_items(home, include_deferred=True)
    item = None
    if list_read.ok:
        item = next((i for i in (list_read.data or []) if i.get("id") == record_id), None)
    if item is None:
        # Resolved records fall out of `list --json` (pending-only) —
        # synthesize the minimal shape Detail needs from the record itself.
        item = {
            "id": record.id,
            "has_proposal": False,
            "proposal_fresh": False,
            "destination": None,
            "already_canon": False,
            "deferred_until": None,
            "source": record.source,
            "bucket": location.bucket_name,
            "host_registered": True,
            "title": models.leading_text(None, [], ""),
        }
    return location, record, item


@router.get("/record/{record_id}", response_class=HTMLResponse)
def detail_page(request: Request, record_id: str) -> Response:
    home = _home(request)
    loaded = _load_detail(home, record_id)
    if loaded is None:
        return RedirectResponse(url=f"/?notice={NOTICE_NOT_FOUND}", status_code=303)
    location, record, item = loaded

    if record.status not in ("pending", "deferred"):
        # 09 §11 P1-9c: land on the Bucket page with a banner; Front if
        # the bucket can't be derived. Y-13 clear-set: the record left
        # pending — a proposal on it must not survive (the banner path
        # clears the slot, 09 §4.5).
        slot = _proposal_slot(request)
        if slot is not None:
            slot.clear_for_record(record_id)
        target = f"/bucket/{location.scope}/{location.bucket_name}?notice={NOTICE_RESOLVED_ELSEWHERE}"
        return RedirectResponse(url=target, status_code=303)

    proposal, _err = ledger.read_proposal_raw(location.bucket_dir, record_id)
    diff_text = ledger.read_diff(location.bucket_dir, record_id)
    proposal_raw_text = ledger.read_proposal_text(location.bucket_dir, record_id)
    registry = ledger.read_registry()
    host_registered = item.get("host_registered", True)
    host_add_command = models.host_add_command(
        location.scope, ledger.project_path_for(location.bucket_dir)
    )

    model = models.build_detail_model(
        item,
        record,
        proposal,
        diff_text,
        proposal_raw_text,
        registry,
        bucket=location.bucket_name,
        scope=location.scope,
        host_registered=host_registered,
        host_add_command=host_add_command,
    )

    # 09 §2.4: Detail renders the iterate split whenever a pane session
    # (live OR just-ended) exists for THIS record; otherwise the plain
    # Iterate control (plus any persisted validate badge — 09 §4.3).
    manager = _pane_manager(request)
    pane_snapshot = manager.snapshot(record_id) if manager is not None else None
    pane_split = pane_snapshot is not None and pane_snapshot.state != pane.STATE_IDLE

    # Y-13: a pending proposal on THIS record renders in the standing
    # action-bar region (waiting or armed, from the server-held slot —
    # navigation never clears it, any in-scope render re-renders it).
    slot = _proposal_slot(request)
    record_proposal = None
    if slot is not None and slot.current is not None and slot.current.record_id == record_id:
        record_proposal = slot.current

    return _render(
        request,
        "detail.html",
        {
            "model": model,
            "armed": None,
            "record_id": record_id,
            "pane": pane_snapshot,
            "pane_split": pane_split,
            "pane_base": f"/record/{record_id}/pane",
            "record_proposal": record_proposal,
            "proposal_verb_label": (
                _VERB_LABELS.get(record_proposal.verb, record_proposal.verb)
                if record_proposal is not None
                else None
            ),
        },
    )


# ------------------------------------------------------------------- pane
#
# The iterate split's routes (task U6, 09 §2.4/§4.2). Every route swaps
# the SAME #pane-region-wrapper id via htmx (pane.html / pane_idle.html /
# pane_armed.html all render that one id), so start/send/interrupt/retry
# are interchangeable swap targets from the client's point of view. A
# missing pane_manager (before the orchestrator's one-line app.py wiring
# lands) degrades every route here to a 503 — never a 500 — per 09 §5's
# "adjudication never depends on any optional subsystem" invariant.

def _pane_not_wired() -> HTMLResponse:
    """A fresh response per call (never a shared module-level instance —
    Response objects are mutated in place by SecurityMiddleware's CSP
    header, and reusing one across concurrent requests is a footgun even
    when idempotent in practice)."""
    return HTMLResponse(
        "self-learn-ui: pane manager not wired — see pane.build_pane_manager()",
        status_code=503,
    )


@router.post("/record/{record_id}/pane/start", response_class=HTMLResponse)
async def pane_start(request: Request, record_id: str, force: bool = Form(False)) -> HTMLResponse:
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    outcome = await manager.start(record_id, force=force)
    if outcome == "armed":
        return _render(
            request,
            "partials/pane_armed.html",
            {"record_id": record_id, "blocked_by": manager.active_record_id},
        )
    snapshot = manager.snapshot(record_id)
    return _render(request, "partials/pane.html", {"record_id": record_id, "pane": snapshot})


@router.post("/record/{record_id}/pane/send", response_class=HTMLResponse)
async def pane_send(request: Request, record_id: str, text: str = Form(...)) -> HTMLResponse:
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    await manager.send(record_id, text)
    snapshot = manager.snapshot(record_id)
    return _render(request, "partials/pane.html", {"record_id": record_id, "pane": snapshot})


@router.post("/record/{record_id}/pane/interrupt", response_class=HTMLResponse)
async def pane_interrupt(request: Request, record_id: str) -> HTMLResponse:
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    await manager.interrupt(record_id)
    snapshot = manager.snapshot(record_id)
    return _render(request, "partials/pane.html", {"record_id": record_id, "pane": snapshot})


@router.post("/record/{record_id}/pane/retry", response_class=HTMLResponse)
async def pane_retry(request: Request, record_id: str) -> HTMLResponse:
    """``r`` on an errored/cap-hit pane (09 §5): the record's own ENDED
    session is cleared and a fresh one started — never forces past a
    DIFFERENT record's live session (that is the armed-prompt's job)."""
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    await manager.start(record_id)
    snapshot = manager.snapshot(record_id)
    return _render(request, "partials/pane.html", {"record_id": record_id, "pane": snapshot})


@router.post("/record/{record_id}/pane/close", response_class=HTMLResponse)
async def pane_close(request: Request, record_id: str) -> Response:
    """``q`` (09 §2.4): ends the session, discards the transcript, and
    returns to full (non-split) Detail."""
    manager = _pane_manager(request)
    if manager is not None:
        await manager.close(record_id)
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = f"/record/{record_id}"
    return resp


@router.get("/record/{record_id}/pane/panel", response_class=HTMLResponse)
def pane_panel(request: Request, record_id: str) -> HTMLResponse:
    """Re-render the pane region from CURRENT state with no side effect —
    the armed prompt's Cancel control lands here."""
    manager = _pane_manager(request)
    snapshot = manager.snapshot(record_id) if manager is not None else None
    if snapshot is not None and snapshot.state != pane.STATE_IDLE:
        return _render(request, "partials/pane.html", {"record_id": record_id, "pane": snapshot})
    return _render(request, "partials/pane_idle.html", {"record_id": record_id, "pane": snapshot})


# ---------------------------------------------------------------- miner


@router.post("/mine/run")
async def mine_run(request: Request) -> Response:
    """09 §11 Y-5's ONE miner action (R3's one-action pin): force a
    mining pass. No arm-then-confirm ceremony — the miner run is
    idempotent/non-destructive (unlike route/reject/defer/graduate,
    which is why THOSE verbs get the arm dance and this doesn't)."""
    runner = request.app.state.runner
    await runner.run(["mine", "run", "--trigger", "manual"])
    _force_refresh(request, "front")
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = "/"
    return resp


# -------------------------------------------------------------------- Report


@router.get("/report", response_class=HTMLResponse)
def report_page(request: Request) -> HTMLResponse:
    home = _home(request)
    report_read = ledger.report(home)
    status_read = ledger.status(home)
    metrics = (status_read.data or {}).get("metrics") if status_read.ok else None
    supply_mix = (status_read.data or {}).get("supply_mix") if status_read.ok else None
    return _render(
        request,
        "report.html",
        {
            "report": report_read.data,
            "report_error": report_read.error,
            "metrics": metrics,
            "supply_mix": supply_mix,
            "status_error": status_read.error,
        },
    )


# ------------------------------------------------------------------ cluster


@router.get("/cluster/{scope}/{name}/{cluster_id}", response_class=HTMLResponse)
def cluster_expand(request: Request, scope: str, name: str, cluster_id: str) -> HTMLResponse:
    home = _home(request)
    bucket = _find_bucket(home, scope, name)
    if bucket is None:
        return HTMLResponse("<p>bucket not found</p>", status_code=404)
    clusters = ledger.read_clusters(bucket.path)
    cluster = next((c for c in clusters if c.get("cluster_id") == cluster_id), None)
    if cluster is None:
        return HTMLResponse("<p>cluster not found</p>", status_code=404)
    return _render(
        request,
        "partials/cluster_expanded.html",
        {"cluster": cluster, "scope": scope, "name": name},
    )


# --------------------------------------------------------------- action bar
#
# ONE partial (templates/partials/action_bar.html) renders every action
# bar "kind" in the app — Detail's/a Bucket row's full quad (route/
# reject/defer/graduate — 09 §1: "also usable on a Bucket row"), a Y-4
# holding row's t/c pair, a Y-6 followup row's single done action, and a
# post-route Y-8 contradicts-edge offer. ARMED rendering is verb-agnostic
# (verb/id/destination/note-presence — 09 §1) so the branch is shared;
# UNARMED rendering branches on `kind` because each context's trigger set
# differs. `dom_id` disambiguates multiple action bars on one page
# (Bucket has one per row; a contradicts offer has one per edge).


def _dom_id(kind: str, record_id: str, target: str | None) -> str:
    if kind == "contradicts" and target:
        return f"action-bar-{record_id}-{_slug(target)}"
    return f"action-bar-{record_id}"


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text)


def _unarmed_context(
    *,
    kind: str,
    record_id: str,
    dest: str | None,
    event: str | None,
    target: str | None,
    already_canon: bool = False,
) -> dict[str, Any]:
    return {
        "armed": None,
        "kind": kind,
        "record_id": record_id,
        "dom_id": _dom_id(kind, record_id, target),
        "dest": dest,
        "event": event,
        "target": target,
        # P1-9b: `g` is always available, highlighted (affordance, not
        # qualification logic) when already_canon is set. Threaded only
        # at initial page render (bucket/detail GET) — arm/disarm/cycle
        # round-trips default it to False, a harmless conservative
        # degradation since the highlight is cosmetic, never a gate.
        "already_canon": already_canon,
    }


def _armed_context(
    *,
    kind: str,
    record_id: str,
    verb: str,
    dest: str | None,
    collapse: str | None,
    note: str | None,
    until: str | None,
    event: str | None,
    tolerate: bool,
    target: str | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "dom_id": _dom_id(kind, record_id, target),
        "armed": {
            "record_id": record_id,
            "verb": verb,
            "verb_label": _VERB_LABELS.get(verb, verb),
            "dest": dest,
            "collapse": collapse,
            "note": note,
            "note_present": bool(note),
            "until": until,
            "event": event,
            "tolerate": tolerate,
            "target": target,
            "show_note_hint": verb == "reject" and not note,
        },
        "disarm_vals": {"kind": kind, "dest": dest, "event": event, "target": target},
    }


@router.post("/record/{record_id}/action/arm", response_class=HTMLResponse)
def action_arm(
    request: Request,
    record_id: str,
    verb: str = Form(...),
    kind: str = Form("detail"),
    dest: str | None = Form(None),
    collapse: str | None = Form(None),
    note: str | None = Form(None),
    until: str | None = Form(None),
    event: str | None = Form(None),
    tolerate: bool = Form(False),
    target: str | None = Form(None),
) -> HTMLResponse:
    if verb not in _KNOWN_VERBS:
        return HTMLResponse("unknown verb", status_code=400)
    ctx = _armed_context(
        kind=kind,
        record_id=record_id,
        verb=verb,
        dest=dest or None,
        collapse=collapse or None,
        note=note or None,
        until=until or None,
        event=event or None,
        tolerate=tolerate,
        target=target or None,
    )
    return _render(request, "partials/action_bar.html", ctx)


@router.post("/record/{record_id}/action/disarm", response_class=HTMLResponse)
def action_disarm(
    request: Request,
    record_id: str,
    kind: str = Form("detail"),
    dest: str | None = Form(None),
    event: str | None = Form(None),
    target: str | None = Form(None),
) -> HTMLResponse:
    ctx = _unarmed_context(kind=kind, record_id=record_id, dest=dest, event=event, target=target)
    return _render(request, "partials/action_bar.html", ctx)


@router.post("/record/{record_id}/action/cycle-destination", response_class=HTMLResponse)
def action_cycle_destination(
    request: Request, record_id: str, current: str | None = Form(None)
) -> HTMLResponse:
    new_dest = cycle_destination(current or None)
    ctx = _unarmed_context(kind="detail", record_id=record_id, dest=new_dest, event=None, target=None)
    return _render(request, "partials/action_bar.html", ctx)


async def _publish_applying(request: Request, verb: str, record_id: str, state: str) -> None:
    hub = getattr(request.app.state, "app_hub", None)
    if hub is not None:
        await hub.publish(envelope_applying(verb, record_id, state))


def _sweep_stale_proposal(request: Request) -> None:
    """Review F3/F4: after any verb execution that can resolve records
    this handler didn't name (bulk loops, collapse members), re-check the
    slot's record — if it no longer reads as pending/deferred, clear
    (the 'record leaving pending' clear-set member, swept)."""
    slot = _proposal_slot(request)
    if slot is None or slot.current is None:
        return
    rid = slot.current.record_id
    location = ledger.locate_record(_home(request), rid)
    record = ledger.read_record(location.path) if location is not None else None
    if record is None or record.status not in ("pending", "deferred"):
        slot.clear_for_record(rid)


def _force_refresh(request: Request, scope: str = "front") -> None:
    hub = getattr(request.app.state, "refresh_hub", None)
    if hub is not None:
        hub.force_refresh(scope)


@router.post("/record/{record_id}/action/confirm", response_class=HTMLResponse)
async def action_confirm(
    request: Request,
    record_id: str,
    verb: str = Form(...),
    kind: str = Form("detail"),
    dest: str | None = Form(None),
    collapse: str | None = Form(None),
    note: str | None = Form(None),
    until: str | None = Form(None),
    event: str | None = Form(None),
    tolerate: bool = Form(False),
    target: str | None = Form(None),
) -> Response:
    if verb not in _KNOWN_VERBS:
        return HTMLResponse("unknown verb", status_code=400)

    home = _home(request)
    runner = request.app.state.runner

    argv = build_argv(
        verb,
        record_id,
        dest=dest or None,
        collapse=collapse or None,
        note=note or None,
        until=until or None,
        event=event or None,
        tolerate=tolerate,
        target=target or None,
    )

    # 09 §3 P1-4 / P3-8: resolving a record under active iteration
    # interrupts FIRST, at verb dispatch — never concurrently with a
    # live pane session's writes to the very files this verb is about
    # to git mv/rm.
    manager = _pane_manager(request)
    if manager is not None:
        await manager.interrupt_active_session(record_id)

    await _publish_applying(request, verb, record_id, "start")
    result = await runner.run(argv)
    await _publish_applying(request, verb, record_id, "done" if result.ok else "error")

    if not result.ok:
        _force_refresh(request, f"record:{record_id}")
        ctx = _unarmed_context(kind=kind, record_id=record_id, dest=dest, event=event, target=target)
        ctx["error"] = result.stderr or f"self-learn {' '.join(argv)} failed"
        return _render(request, "partials/action_bar.html", ctx)

    _force_refresh(request, f"record:{record_id}")

    # Y-13 clear-set: the record left pending — a pane proposal on it
    # must not outlive the resolution (this is the same-server half; the
    # detail_page banner path covers external resolutions on next render).
    if verb in ("route", "reject", "graduate", "defer"):
        slot = _proposal_slot(request)
        if slot is not None:
            slot.clear_for_record(record_id)
    # A collapse resolves cluster MEMBERS beyond record_id (review F4).
    if collapse:
        _sweep_stale_proposal(request)

    if verb == "route":
        proposal, _err = ledger.read_proposal_raw(
            _bucket_dir_for(home, record_id), record_id
        )
        contradicts_raw: list[str] = (proposal or {}).get("contradicts") or []
        contradicts: tuple[str, ...] = tuple(contradicts_raw)
        if contradicts:
            edges = [
                {"target": t, "dom_id": _dom_id("contradicts", record_id, t)}
                for t in contradicts
            ]
            return _render(
                request,
                "partials/contradicts_offer.html",
                {"record_id": record_id, "edges": edges},
            )

    bucket_name = _bucket_name_for(home, record_id)
    url = next_record_url(home, bucket_name, record_id) if bucket_name else f"/?notice={NOTICE_BUCKET_CLEAR}"
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = url
    return resp


def _bucket_dir_for(home: Path, record_id: str) -> Path:
    """Best-effort bucket dir for a JUST-resolved id (it moved out of
    ``pending/`` to ``resolved/`` — locate_record still finds it there)."""
    loc = ledger.locate_record(home, record_id)
    return loc.bucket_dir if loc else home


def _bucket_name_for(home: Path, record_id: str) -> str | None:
    loc = ledger.locate_record(home, record_id)
    return loc.bucket_name if loc else None


# -------------------------------------------------------------- armed host-add
#
# 09 §11 Y-11 (amended 2026-07-17): the surface's FIRST bucket-scoped
# mutation — registration of an unregistered project through the same
# arm/confirm SPINE (an .action-bar[data-armed] rendering, so app.js's
# Enter-confirms / any-key-disarms works unchanged) but its own route
# triple, because the record-scoped arm machine has nothing to hang a
# path-parameter verb on. Build pins honored here:
#   - the path is SERVER-derived from the bucket's meta.yaml
#     (ledger.project_path_for) — a client field never supplies it;
#   - the only client-influenced value is which page confirm returns
#     to, constrained to a record-id shape (else the bucket page);
#   - the ARM state renders the consent consequence (the CLI prints it
#     on stdout, which the runner contract discards);
#   - project buckets only — skill/user notices keep prose fallback.

_RECORD_ID_RE = re.compile(r"^lrn-[0-9a-f]{8}$")


def build_host_add_argv(path: str) -> list[str]:
    """``self-learn host add <path>`` — the one argv this surface maps
    to (mirrors the CLI parser verbatim, same rule as build_argv)."""
    return ["host", "add", path]


def _host_add_ctx(
    *,
    scope: str,
    name: str,
    record_id: str | None,
    armed: bool,
    path: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "armed": armed,
        "scope": scope,
        "name": name,
        "record_id": record_id,
        "path": path,
        "can_arm": True,  # routes only render this ctx for project buckets
        "host_registered": False,
        "error": error,
    }


def _host_add_target(request: Request, scope: str, name: str) -> tuple["ledger.Bucket", str] | Response:
    """Resolve bucket + server-derived project path, or an error Response."""
    if scope != "project":
        # Y-11 scope limitation, checked EXPLICITLY — not just via the
        # path being underivable (a stray meta.yaml in a skill bucket
        # must not arm registration; review 2026-07-17 host-add, F5).
        return HTMLResponse("registration arms for project buckets only", status_code=400)
    bucket = _find_bucket(_home(request), scope, name)
    if bucket is None:
        return HTMLResponse("bucket not found", status_code=404)
    path = ledger.project_path_for(bucket.path)
    if not path:
        return HTMLResponse("no registration candidate for this bucket", status_code=400)
    return bucket, path


@router.post("/bucket/{scope}/{name}/host-add/arm", response_class=HTMLResponse)
def host_add_arm(
    request: Request, scope: str, name: str, record_id: str | None = Form(None)
) -> Response:
    resolved = _host_add_target(request, scope, name)
    if isinstance(resolved, Response):
        return resolved
    _bucket, path = resolved
    rid = record_id if record_id and _RECORD_ID_RE.match(record_id) else None
    ctx = _host_add_ctx(scope=scope, name=name, record_id=rid, armed=True, path=path)
    return _render(request, "partials/host_add_bar.html", ctx)


@router.post("/bucket/{scope}/{name}/host-add/disarm", response_class=HTMLResponse)
def host_add_disarm(
    request: Request, scope: str, name: str, record_id: str | None = Form(None)
) -> Response:
    resolved = _host_add_target(request, scope, name)
    if isinstance(resolved, Response):
        return resolved
    rid = record_id if record_id and _RECORD_ID_RE.match(record_id) else None
    ctx = _host_add_ctx(scope=scope, name=name, record_id=rid, armed=False)
    return _render(request, "partials/host_add_bar.html", ctx)


@router.post("/bucket/{scope}/{name}/host-add/confirm", response_class=HTMLResponse)
async def host_add_confirm(
    request: Request, scope: str, name: str, record_id: str | None = Form(None)
) -> Response:
    resolved = _host_add_target(request, scope, name)
    if isinstance(resolved, Response):
        return resolved
    _bucket, path = resolved
    rid = record_id if record_id and _RECORD_ID_RE.match(record_id) else None

    runner = request.app.state.runner
    result = await runner.run(build_host_add_argv(path))
    if not result.ok:
        ctx = _host_add_ctx(
            scope=scope,
            name=name,
            record_id=rid,
            armed=False,
            error=result.stderr or "self-learn host add failed",
        )
        return _render(request, "partials/host_add_bar.html", ctx)

    _force_refresh(request, f"bucket:{name}")
    # Post-success (Y-11 pin): return to the arming page — the notice
    # disappears because host_registered re-reads true on render.
    url = f"/record/{rid}" if rid else f"/bucket/{scope}/{name}"
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = url
    return resp


# ----------------------------------------------------- verb proposals (Y-13)
#
# 09 §4.5 (as reworked 2026-07-17): the pane agent's propose_verb tool
# occupied the server-held slot and pushed an SSE `pane_proposal`; these
# routes are the HUMAN's side. Proposals render WAITING (never
# [data-armed]) — `y` arms through the standard armed contract, Enter
# confirms, any other key disarms BACK TO WAITING, dismiss clears. The
# confirm rebuilds argv from the SLOT (server truth), never from client
# fields — what the human read is byte-identical to what runs.


def _proposal_slot(request: Request) -> "proposals.ProposalSlot | None":
    manager = _pane_manager(request)
    return manager.proposal_slot if manager is not None else None


def _proposal_ctx(prop: "proposals.VerbProposal", kind: str, *, error: str | None = None) -> dict[str, Any]:
    return {
        "proposal": prop,
        "kind": kind,
        "verb_label": _VERB_LABELS.get(prop.verb, prop.verb),
        "error": error,
    }


def _proposal_gone(request: Request, kind: str, record_id: str, *, error: str | None = None) -> HTMLResponse:
    """The slot no longer holds this record's proposal (stale POST, or a
    just-cleared confirm): render the region's unarmed replacement —
    Detail gets its standing unarmed action bar back, Bucket gets an
    empty proposal region."""
    if kind == "detail":
        ctx = _unarmed_context(kind="detail", record_id=record_id, dest=None, event=None, target=None)
        if error:
            ctx["error"] = error
        return _render(request, "partials/action_bar.html", ctx)
    # Bucket pages keep a stable empty region (the SSE re-fetch target);
    # error text goes through the template so it renders escaped.
    return _render(
        request,
        "partials/proposal_bar.html",
        {"proposal": None, "kind": kind, "error": error},
    )


@router.post("/proposal/arm", response_class=HTMLResponse)
async def proposal_arm(
    request: Request,
    record_id: str = Form(...),
    kind: str = Form("detail"),
    nonce: str = Form(...),
) -> HTMLResponse:
    slot = _proposal_slot(request)
    if slot is None:
        return _pane_not_wired()
    # Slot validity re-check at arm (09 §4.5 clear-set: the record leaving
    # pending clears) — a stale proposal never arms. STATUS is the check,
    # not mere existence: locate_record also finds resolved/ records (the
    # _bucket_dir_for note).
    current = slot.current
    if current is not None and current.record_id == record_id:
        location = ledger.locate_record(_home(request), record_id)
        record = ledger.read_record(location.path) if location is not None else None
        if record is None or record.status not in ("pending", "deferred"):
            slot.clear_for_record(record_id)
            return _proposal_gone(request, kind, record_id, error="that record was resolved elsewhere")
    prop = slot.arm(record_id, nonce)
    if prop is None:
        return _proposal_gone(request, kind, record_id)
    return _render(request, "partials/proposal_bar.html", _proposal_ctx(prop, kind))


@router.post("/proposal/disarm", response_class=HTMLResponse)
async def proposal_disarm(
    request: Request,
    record_id: str = Form(...),
    kind: str = Form("detail"),
    nonce: str = Form(...),
) -> HTMLResponse:
    slot = _proposal_slot(request)
    if slot is None:
        return _pane_not_wired()
    prop = slot.disarm(record_id, nonce)
    if prop is None:
        return _proposal_gone(request, kind, record_id)
    return _render(request, "partials/proposal_bar.html", _proposal_ctx(prop, kind))


@router.post("/proposal/dismiss", response_class=HTMLResponse)
async def proposal_dismiss(
    request: Request,
    record_id: str = Form(...),
    kind: str = Form("detail"),
    nonce: str = Form(...),
) -> HTMLResponse:
    slot = _proposal_slot(request)
    if slot is None:
        return _pane_not_wired()
    current = slot.current
    if current is not None and current.record_id == record_id and current.nonce == nonce:
        slot.clear_for_record(record_id)
    return _proposal_gone(request, kind, record_id)


@router.post("/proposal/confirm", response_class=HTMLResponse)
async def proposal_confirm(
    request: Request,
    record_id: str = Form(...),
    kind: str = Form("detail"),
    nonce: str = Form(...),
) -> Response:
    slot = _proposal_slot(request)
    if slot is None:
        return _pane_not_wired()
    prop = slot.current
    if (
        prop is None
        or prop.record_id != record_id
        or not prop.armed
        or prop.nonce != nonce
    ):
        # Stale confirm (slot cleared/changed since the bar rendered) —
        # never execute anything the human isn't looking at.
        return _proposal_gone(request, kind, record_id)

    home = _home(request)
    runner = request.app.state.runner

    # Capture argv from the SLOT before anything can clear it (the
    # interrupt below tears down the proposing session, whose teardown
    # clears the slot by session key).
    argv = build_argv(
        prop.verb,
        prop.record_id,
        dest=prop.dest,
        note=prop.note,
        until=prop.until,
    )
    slot.clear()  # Y-13 clear-set: human confirm

    # Interrupt-first (09 §3 P1-4): a confirmed resolution on the record
    # under active iteration interrupts that session before the verb runs.
    # Bucket sessions never match a record id here — they hold zero write
    # allowance, so they survive the confirm by construction (09 §4.5).
    manager = _pane_manager(request)
    if manager is not None:
        await manager.interrupt_active_session(record_id)

    await _publish_applying(request, prop.verb, record_id, "start")
    result = await runner.run(argv)
    await _publish_applying(request, prop.verb, record_id, "done" if result.ok else "error")
    _force_refresh(request, f"record:{record_id}")

    if not result.ok:
        # The verb's own refusal path (09 §4.5: stderr verbatim, slot
        # stays cleared — the agent can re-propose after the human reads).
        return _proposal_gone(
            request, kind, record_id,
            error=result.stderr or f"self-learn {' '.join(argv)} failed",
        )

    if prop.verb == "route":
        proposal_raw, _err = ledger.read_proposal_raw(
            _bucket_dir_for(home, record_id), record_id
        )
        contradicts: tuple[str, ...] = tuple((proposal_raw or {}).get("contradicts") or [])
        if contradicts:
            edges = [
                {"target": t, "dom_id": _dom_id("contradicts", record_id, t)}
                for t in contradicts
            ]
            return _render(
                request,
                "partials/contradicts_offer.html",
                {"record_id": record_id, "edges": edges},
            )

    if kind == "bucket":
        url = f"/bucket/{prop.bucket_scope}/{prop.bucket_name}"
    else:
        bucket_name = _bucket_name_for(home, record_id)
        url = next_record_url(home, bucket_name, record_id) if bucket_name else f"/?notice={NOTICE_BUCKET_CLEAR}"
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = url
    return resp


# ------------------------------------------------------- bucket pane (Y-13)
#
# 09 §2.2: `p` splits the Bucket page exactly as `i` splits Detail — the
# same PaneManager, the same one-live-session rule (opening either
# variant while the other runs takes the existing armed interrupt
# prompt), a synthetic session key, and zero write allowance in the
# charter. Routes mirror the record pane's; templates parameterize the
# POST base URL (`pane_base`).


def _bucket_pane_key(scope: str, name: str) -> str:
    return pane.bucket_session_key(scope, name)


def _bucket_pane_ctx(scope: str, name: str, snapshot: Any) -> dict[str, Any]:
    return {
        "record_id": _bucket_pane_key(scope, name),
        "pane": snapshot,
        "pane_base": f"/bucket/{scope}/{name}/pane",
        "pane_close_url": f"/bucket/{scope}/{name}",
    }


@router.post("/bucket/{scope}/{name}/pane/start", response_class=HTMLResponse)
async def bucket_pane_start(
    request: Request, scope: str, name: str, force: bool = Form(False)
) -> HTMLResponse:
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    key = _bucket_pane_key(scope, name)
    outcome = await manager.start(key, force=force)
    if outcome == "armed":
        return _render(
            request,
            "partials/pane_armed.html",
            {
                "record_id": key,
                "blocked_by": manager.active_record_id,
                "pane_base": f"/bucket/{scope}/{name}/pane",
            },
        )
    snapshot = manager.snapshot(key)
    return _render(request, "partials/pane.html", _bucket_pane_ctx(scope, name, snapshot))


@router.post("/bucket/{scope}/{name}/pane/send", response_class=HTMLResponse)
async def bucket_pane_send(
    request: Request, scope: str, name: str, text: str = Form(...)
) -> HTMLResponse:
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    key = _bucket_pane_key(scope, name)
    await manager.send(key, text)
    return _render(request, "partials/pane.html", _bucket_pane_ctx(scope, name, manager.snapshot(key)))


@router.post("/bucket/{scope}/{name}/pane/interrupt", response_class=HTMLResponse)
async def bucket_pane_interrupt(request: Request, scope: str, name: str) -> HTMLResponse:
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    key = _bucket_pane_key(scope, name)
    await manager.interrupt(key)
    return _render(request, "partials/pane.html", _bucket_pane_ctx(scope, name, manager.snapshot(key)))


@router.post("/bucket/{scope}/{name}/pane/retry", response_class=HTMLResponse)
async def bucket_pane_retry(request: Request, scope: str, name: str) -> HTMLResponse:
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    key = _bucket_pane_key(scope, name)
    await manager.start(key)
    return _render(request, "partials/pane.html", _bucket_pane_ctx(scope, name, manager.snapshot(key)))


@router.post("/bucket/{scope}/{name}/pane/close", response_class=HTMLResponse)
async def bucket_pane_close(request: Request, scope: str, name: str) -> Response:
    manager = _pane_manager(request)
    if manager is not None:
        await manager.close(_bucket_pane_key(scope, name))
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = f"/bucket/{scope}/{name}"
    return resp


@router.get("/bucket/{scope}/{name}/pane/panel", response_class=HTMLResponse)
def bucket_pane_panel(request: Request, scope: str, name: str) -> HTMLResponse:
    manager = _pane_manager(request)
    key = _bucket_pane_key(scope, name)
    snapshot = manager.snapshot(key) if manager is not None else None
    if snapshot is not None and snapshot.state != pane.STATE_IDLE:
        return _render(request, "partials/pane.html", _bucket_pane_ctx(scope, name, snapshot))
    return _render(
        request,
        "partials/pane_idle.html",
        {**_bucket_pane_ctx(scope, name, snapshot), "bucket_pane": True},
    )


# -------------------------------------------------------------------- SSE


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    refresh_hub = request.app.state.refresh_hub
    app_hub = request.app.state.app_hub
    return StreamingResponse(
        event_stream(refresh_hub, app_hub), media_type="text/event-stream"
    )


# --------------------------------------------------------------- bulk graduate


@router.post("/bucket/{scope}/{name}/graduate-bulk", response_class=HTMLResponse)
async def graduate_bulk(request: Request, scope: str, name: str, ids: str = Form(...)) -> Response:
    home = _home(request)
    runner = request.app.state.runner
    id_list = [i for i in ids.split(",") if i]
    hub = getattr(request.app.state, "app_hub", None)
    manager = _pane_manager(request)

    failed_id: str | None = None
    done = 0
    for record_id in id_list:
        # Same interrupt-first rule as action_confirm — "by keypress OR
        # by a bulk loop reaching it" (09 §3).
        if manager is not None:
            await manager.interrupt_active_session(record_id)
        argv = build_argv("graduate", record_id, no_push=True)
        result = await runner.run(argv)
        if not result.ok:
            failed_id = record_id
            break
        done += 1
        if hub is not None:
            await hub.publish(envelope_bulk_progress(done, len(id_list), failed_id))

    await runner.run(["push"])
    _force_refresh(request, f"bucket:{name}")
    _sweep_stale_proposal(request)  # review F3: bulk-graduated records

    if failed_id is not None:
        return _render(
            request,
            "partials/error_strip.html",
            {"error": f"bulk graduate stopped at {failed_id}"},
            status_code=200,
        )
    return RedirectResponse(url=f"/bucket/{scope}/{name}", status_code=303)
