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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.responses import StreamingResponse

from self_learn.chezmoi import CHEZMOI_DIRTY_MARKER
from self_learn.hosts import is_repo_root
from self_learn.records import Record
from self_learn.verbs import GITOPS_DIRTY_MARKER

from . import ledger, models, pane, proposals, rendering
from .keymap import keymap_as_dicts, keymap_json
from .prefetch import DetailPrefetchCache
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
    "rehome": "Move",
    "confirm-recurrence": "Confirm recurrence",
    "link-contradicts": "Link contradiction",
    "followup-done": "Mark follow-up done",
}

#: Verbs the HUMAN action-bar routes accept. `rehome` is deliberately
#: absent (09 §11 Y-18 decision 3: no human-side re-home key or control
#: in M1 — agent proposal + the CLI verb are the two hands); its label
#: above serves the proposal bar only.
_KNOWN_VERBS = frozenset(_VERB_LABELS) - {"rehome"}

#: The Y-18 bucket-change staleness notice (plain words, the
#: resolved-elsewhere shape): a CLI-side rehome moved the record while
#: a proposal was waiting/armed — the slot clears, never a disarm.
NOTICE_PROPOSAL_MOVED = (
    "that lesson moved to another project — the proposal no longer applies"
)


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
    to: str | None = None,
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
    elif verb == "rehome":
        # Y-18: the confirm rebuilds this from the slot's RESOLVED
        # target (server truth) — `rehome <id> --to <resolved-path>`.
        argv = ["rehome", record_id, "--to", to or ""]
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


#: FW-34 §2.3: pulls the session id out of a validated `transcript:<sid>#L<n>`
#: origin — the ONLY provenance the promote argv ever carries (never `--quote`).
_ORIGIN_RE = re.compile(r"^transcript:([^#]+)#L\d+$")


def near_miss_teach_argv(snippet: dict, origin: str | None) -> list[str] | None:
    """FW-34 §2.3: the exact `teach` argv a promotable near-miss snippet
    builds — `teach --<scope> --type <t> [--kind …] --trigger …
    --instruction …` (or `--fact`/`--context`) `--session <sid>`, NEVER
    `--quote` (F3-(a) — a near-miss carries no journaled evidence span).
    `--<scope>` falls back to teach's own documented project default
    (01 §2) when the snippet carries none — the leaner `near_misses[]`
    reader schema (§1.3) has no scope field at all, unlike a full
    `candidates[]` entry. Returns `None` when the snippet/origin cannot
    build a valid call (missing type, unparseable origin) — the caller
    refuses rather than guess."""
    if not isinstance(snippet, dict):
        return None
    match = _ORIGIN_RE.match(origin or "")
    if not match:
        return None
    session_id = match.group(1)
    scope = snippet.get("scope") or "project"
    if isinstance(scope, str) and scope.startswith("skill:"):
        argv = ["teach", "--skill", scope.partition(":")[2]]
    elif scope == "user":
        argv = ["teach", "--user"]
    else:
        argv = ["teach", "--project"]
    rtype = snippet.get("type")
    if rtype == "behavior":
        trigger, instruction = snippet.get("trigger"), snippet.get("instruction")
        if not trigger or not instruction:
            return None
        argv += ["--type", "behavior"]
        if snippet.get("kind"):
            argv += ["--kind", snippet["kind"]]
        argv += ["--trigger", trigger, "--instruction", instruction]
    elif rtype == "knowledge":
        fact = snippet.get("fact")
        if not fact:
            return None
        argv += ["--type", "knowledge", "--fact", fact]
        if snippet.get("context"):
            argv += ["--context", snippet["context"]]
    else:
        return None
    argv += ["--session", session_id]
    return argv


def cycle_destination(current: str | None, scope: str) -> str:
    """09 §2.3's `o` pin: cycle among the parameter-free destinations
    ONLY — ``new-skill``/``hook`` are structurally unreachable from this
    function, which is what "the cycle skips them" means in practice
    (there is nothing to skip — they were never in the cycle set). As
    amended 2026-07-18 (feedback round 2 item 3) the set is additionally
    scope-filtered (:func:`models.destinations_for_scope`) — the CLI's
    own scope rules, honored BEFORE the human can arm anything: a
    project/user record can never cycle onto skill-md."""
    cycle = models.destinations_for_scope(scope)
    if current not in cycle:
        return cycle[0]
    idx = cycle.index(current)
    return cycle[(idx + 1) % len(cycle)]


def _next_pending_id(home: Path, bucket_name: str, exclude_id: str) -> str | None:
    """The next pending record in the SAME bucket (any destination group,
    oldest-first per the CLI's own list order), excluding *exclude_id*
    itself, or ``None`` when nothing remains. The ONE shared computation
    (P2-4) behind both :func:`next_record_url` (the queue-walk's actual
    hop target) and the Y-19 item 1 prefetch trigger in
    :func:`detail_page` — the prefetch warms exactly the record the walk
    would land on next, never a second guess at what "next" means."""
    read = ledger.list_items(home, include_deferred=False)
    if not read.ok or not read.data:
        return None
    for item in read.data:
        if item.get("bucket") == bucket_name and item.get("id") != exclude_id:
            return item["id"]
    return None


def next_record_url(home: Path, bucket_name: str, resolved_id: str) -> str:
    """09 §2 / P3-9's "flow after resolution": the next pending record in
    the SAME bucket, excluding *resolved_id* itself. ``/?notice=bucket-
    clear`` when nothing remains — Front, not the now-empty bucket page
    (09 §1: "if the bucket empties, return to Front with a one-line
    bucket-clear banner")."""
    next_id = _next_pending_id(home, bucket_name, resolved_id)
    if next_id is None:
        return f"/?notice={NOTICE_BUCKET_CLEAR}"
    return f"/record/{next_id}"


# --------------------------------------------------- Y-19 item 1: prefetch


@dataclass(frozen=True)
class DetailReadBundle:
    """Everything Detail's reads assemble for one record — the exact
    shape :func:`_gather_detail_bundle` returns, cached verbatim by the
    Y-19 item 1 prefetch (:mod:`self_learn_ui.prefetch`). Deliberately
    excludes anything live/in-memory (pane snapshot, proposal slot) —
    those are never cached, always read fresh at render time, per
    09 §3's "no state that isn't a file" posture: this bundle is a memo
    of FILE reads only."""

    location: ledger.RecordLocation
    record: Record
    item: dict
    proposal: dict | None
    diff_text: str | None
    proposal_raw_text: str | None
    registry: list[dict]
    host_registered: bool
    host_add_command: str | None


def _gather_detail_bundle(home: Path, record_id: str) -> DetailReadBundle | None:
    """The full CLI-read set Detail needs, assembled ONCE (P2-4) and
    shared by two callers: the fresh-render path in :func:`detail_page`
    on a cache miss, and the Y-19 item 1 background prefetch task
    (:func:`_warm_detail_prefetch`). ``None`` when the record can't be
    resolved at all (unknown id) — callers branch on that exactly as the
    former ``_load_detail`` did."""
    location = ledger.locate_record(home, record_id)
    if location is None:
        return None
    record = ledger.read_record(location.path)
    if record is None:
        return None
    # 09 §11 Y-20 / delta F9: the ONE call site that passes --surface-fill,
    # scoped via --id to this one record — Front/Bucket never request it
    # (blind-review F4). Riding inside this bundle means the budget datum
    # is cached and invalidated by the SAME Y-19 generation gate as the
    # rest of Detail (global on any verb completion — Y-20 decision 3).
    list_read = ledger.list_items(
        home, include_deferred=True, surface_fill=True, record_id=record_id
    )
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
    proposal, _err = ledger.read_proposal_raw(location.bucket_dir, record_id)
    diff_text = ledger.read_diff(location.bucket_dir, record_id)
    proposal_raw_text = ledger.read_proposal_text(location.bucket_dir, record_id)
    registry = ledger.read_registry()
    host_registered = item.get("host_registered", True)
    host_add_command = models.host_add_command(
        location.scope, ledger.project_path_for(location.bucket_dir)
    )
    return DetailReadBundle(
        location=location,
        record=record,
        item=item,
        proposal=proposal,
        diff_text=diff_text,
        proposal_raw_text=proposal_raw_text,
        registry=registry,
        host_registered=host_registered,
        host_add_command=host_add_command,
    )


def _warm_detail_prefetch(
    cache: DetailPrefetchCache,
    hub: "ledger.RefreshHub",
    home: Path,
    record_id: str,
) -> None:
    """09 §11 Y-19 item 1 (survey P2b): warm the queue-walk's likely next
    hop. The generation is captured BEFORE the reads run — if a refresh
    (a concurrent resolution, a mined arrival, anything) lands mid-read,
    the entry is stamped against an already-superseded generation and is
    therefore stale the INSTANT it is written, never served (the
    CRITICAL staleness rule: no window where a half-fresh read can look
    valid). A read failure (the record vanished between the trigger and
    this task running) simply stores nothing — the next navigation falls
    through to the ordinary fresh path, exactly the cache-miss behavior.
    Runs as a plain sync function (FastAPI/Starlette dispatches a
    non-coroutine ``BackgroundTasks`` callable through a threadpool) —
    :func:`_gather_detail_bundle` is blocking I/O (subprocess + file
    reads), never a model call (zero token cost, per the survey's own
    framing)."""
    generation = hub.generation
    bundle = _gather_detail_bundle(home, record_id)
    if bundle is not None:
        cache.put(record_id, generation, bundle)


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

    # 09 §5 unreadable-record row: the skip-and-count line's number comes
    # from `status --json`'s per-bucket `unreadable` field — never a
    # server-side ledger derivation. A failed/old-CLI read (absent field)
    # degrades to 0 (no line), never a crash.
    status_read = ledger.status(home)
    unreadable = 0
    if status_read.ok and status_read.data:
        for b in status_read.data.get("buckets", []):
            if b.get("bucket") == name and b.get("scope") == scope:
                unreadable = b.get("unreadable", 0)
                break

    model = models.build_bucket_model(
        name,
        scope,
        items,
        proposals_by_id,
        clusters_raw,
        registry,
        host_registered=host_registered,
        host_add_command=host_add_command,
        unreadable=unreadable,
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


def _detail_cache(request: Request) -> DetailPrefetchCache | None:
    return getattr(request.app.state, "detail_prefetch", None)


def _refresh_hub(request: Request) -> "ledger.RefreshHub | None":
    return getattr(request.app.state, "refresh_hub", None)


@router.get("/record/{record_id}", response_class=HTMLResponse)
def detail_page(request: Request, record_id: str, background_tasks: BackgroundTasks) -> Response:
    home = _home(request)
    hub = _refresh_hub(request)
    generation = hub.generation if hub is not None else 0

    # Y-19 item 1: a warm hit skips every subprocess/file read below —
    # bundle is IDENTICAL in shape whether it came from the cache or a
    # fresh gather (same function produced it either way, P2-4). A miss
    # (never prefetched, or prefetched-then-invalidated) falls through to
    # the ordinary read exactly as before this amendment.
    cache = _detail_cache(request)
    bundle = cache.get(record_id, generation) if cache is not None else None
    if bundle is None:
        bundle = _gather_detail_bundle(home, record_id)
    if bundle is None:
        # _gather_detail_bundle returns None for TWO cases: an unknown id
        # (locate_record found nothing) OR a located-but-unreadable record
        # (read_record failed — any of the 09 §5 failure classes). Re-locate
        # to tell them apart: a genuine miss redirects to Front; a file that
        # exists on disk but can't be read renders the degraded salvage view
        # (never a 500, never a silent "not found" — 09 §5 unreadable row).
        location = ledger.locate_record(home, record_id)
        if location is None:
            return RedirectResponse(url=f"/?notice={NOTICE_NOT_FOUND}", status_code=303)
        salvage = ledger.salvage_record(location.path, record_id)
        return _render(
            request,
            "detail_degraded.html",
            {
                "salvage": salvage,
                "record_id": record_id,
                "bucket": location.bucket_name,
                "scope": location.scope,
            },
        )
    location, record, item = bundle.location, bundle.record, bundle.item

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

    model = models.build_detail_model(
        item,
        record,
        bundle.proposal,
        bundle.diff_text,
        bundle.proposal_raw_text,
        bundle.registry,
        bucket=location.bucket_name,
        scope=location.scope,
        host_registered=bundle.host_registered,
        host_add_command=bundle.host_add_command,
    )

    # 09 §2.4: Detail renders the iterate split whenever a pane session
    # (live OR just-ended) exists for THIS record; otherwise the plain
    # Iterate control (plus any persisted validate badge — 09 §4.3).
    # Deliberately NEVER cached (prefetch.py's docstring): live/in-memory
    # state is read fresh on every render regardless of the bundle's
    # cache/miss origin.
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

    response = _render(
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

    # Y-19 item 1: warm the queue-walk's likely next hop — the exact
    # record next_record_url would land on if the human resolves THIS
    # one right now. Scheduled as a background task (FastAPI attaches it
    # below) so it never delays this page's own paint; explicitly
    # attached to the response rather than relied on to auto-attach,
    # since this route returns a Response object directly (FastAPI only
    # auto-attaches BackgroundTasks when it builds the Response itself).
    if cache is not None and hub is not None:
        next_id = _next_pending_id(home, location.bucket_name, record_id)
        if next_id is not None:
            background_tasks.add_task(_warm_detail_prefetch, cache, hub, home, next_id)
            response.background = background_tasks

    return response


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


@router.post("/record/{record_id}/pane/resume", response_class=HTMLResponse)
async def pane_resume(request: Request, record_id: str, force: bool = Form(False)) -> HTMLResponse:
    """U22 (Y-28 §5's Resume control, idle-region-only): reopens a
    persisted-but-not-live session. Same armed-prompt outcome as
    ``start`` when a DIFFERENT record is live; degrades to the idle
    region (never a 500) when the server-side §4e predicate refuses —
    defense in depth beneath the button's own ``resumable`` gating."""
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    outcome = await manager.resume(record_id, force=force)
    if outcome == "armed":
        return _render(
            request,
            "partials/pane_armed.html",
            {"record_id": record_id, "blocked_by": manager.active_record_id},
        )
    if outcome == "not-resumable":
        snapshot = manager.snapshot(record_id)
        return _render(request, "partials/pane_idle.html", {"record_id": record_id, "pane": snapshot})
    snapshot = manager.snapshot(record_id)
    return _render(request, "partials/pane.html", {"record_id": record_id, "pane": snapshot})


@router.get("/record/{record_id}/pane/view", response_class=HTMLResponse)
def pane_view(request: Request, record_id: str) -> HTMLResponse:
    """U22 (Y-28 §5's View control): a read-only reconstruction of the
    persisted transcript, independent of any live session — swaps the
    SAME ``#pane-region-wrapper`` id (no new page region). Degrades to
    the idle region when nothing is persisted (a stale/raced click)."""
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    view = manager.view_snapshot(record_id)
    if view is None:
        snapshot = manager.snapshot(record_id)
        return _render(request, "partials/pane_idle.html", {"record_id": record_id, "pane": snapshot})
    return _render(request, "partials/pane.html", {"record_id": record_id, "pane": view})


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
    """``q`` (09 §2.4). U22 (Y-28 §4c) reworked this from a hard discard
    to a park-to-disk: the live session tears down and returns to full
    (non-split) Detail exactly as before, but the transcript now
    survives on disk — the next Iterate open shows the collapsed
    prior-conversation card (§5) instead of a bare prompt."""
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


# --------------------------------------------------------------- worker


@router.post("/worker/kick")
async def worker_kick(request: Request) -> Response:
    """09 §11 Y-19 item 2 (survey P2a): the missing symmetric affordance
    to :func:`mine_run` below — the M2 proposal drafter had NO UI trigger
    at all before this route (the survey's "single most surprising
    finding"). Same pattern as ``mine_run``: no arm-then-confirm ceremony
    (this is ``worker kick``, the idempotent-by-construction trigger — see
    below — never a resolution verb), a forced front-scope refresh so the
    status strip's ``worker: …`` label and the bucket table's
    ``unanalyzed`` counts update as proposals land, an ``HX-Redirect``
    back to Front.

    UNLIKE ``mine_run``, this does NOT hold the server resident for the
    whole analysis pass (Y-14 — ``mine run`` "executes immediately", 12
    §"R2"/08 §7.1, so THAT await genuinely spans the whole mining run;
    ``worker kick`` is a different verb): per 08 §7.1, ``self-learn
    worker kick`` touches ``worker.dirty``, takes ``worker.spawn.lock``,
    and — unless a coalescing window is already open — ``setsid``-spawns
    the real ``worker run --coalesce`` DETACHED before returning. The
    subprocess this route awaits is that short-lived kick, not the
    worker's own run, so this request's in-flight window is the kick's
    own runtime (milliseconds to the flock, no model call in it at all);
    the detached worker keeps analyzing — and can itself outlive an
    idle-exit — long after this request and even this server process are
    gone. This is exactly the "detached spawn, not an in-process await"
    posture the parallel affordance needs.

    Double-click safety is CLI-owned, not button-owned — mirroring
    ``mine_run``'s own template, which carries no client-side guard
    either (10 §1 "Verb runner" row's one-subprocess-at-a-time
    serialization is the only brace either button gets from THIS layer).
    ``worker.kick()``'s own flock + ``worker.window`` pid file absorb a
    second kick landing while a window is already open — the CLI
    documents the outcomes as ``spawned`` \\| ``absorbed-window`` \\|
    ``absorbed-race`` \\| ``disabled``; two rapid clicks can produce AT
    MOST one spawned worker, never two, by construction in the CLI layer
    this route calls into unchanged."""
    runner = request.app.state.runner
    await runner.run(["worker", "kick"])
    _force_refresh(request, "front")
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = "/"
    return resp


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


@router.post("/mine/near-miss/promote")
async def mine_near_miss_promote(
    request: Request, run_id: str = Form(...), index: int = Form(...)
) -> Response:
    """09 §11 Y-24 §2.3 — the ONE near-miss action. The body is only a
    coordinate (run-id + outcome index); the server RE-READS the
    snippet from a FRESH `mine status --json` (server truth, never a
    client-supplied body — mirrors the Y-18 rehome re-resolve) and
    rejects a non-promotable index outright (400): a drill row can never
    offer a Promote control the endpoint would then accept from a stale
    or tampered post, because both read the identical `promotable` flag.
    No arm-then-confirm ceremony (matches `/mine/run`/`/worker/kick` —
    the tap IS the confirmation; `teach` is the human-capture writer with
    its own full scan/field-cap/pending-gate discipline)."""
    home = _home(request)
    mine_read = ledger.mine_status(home)
    run = None
    if mine_read.ok and mine_read.data:
        run = next(
            (r for r in (mine_read.data.get("runs") or []) if r.get("run_id") == run_id),
            None,
        )
    outcomes = (run or {}).get("outcomes") or []
    outcome = outcomes[index] if 0 <= index < len(outcomes) else None
    if outcome is None or not outcome.get("promotable"):
        return HTMLResponse("that near-miss is not promotable", status_code=400)
    argv = near_miss_teach_argv(outcome.get("snippet") or {}, outcome.get("origin"))
    if argv is None:
        return HTMLResponse("that near-miss is not promotable", status_code=400)
    runner = request.app.state.runner
    await runner.run(argv)
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
    scope: str = "user",
) -> dict[str, Any]:
    return {
        "armed": None,
        # U20 §2.2: set only by action_confirm's failure leg (and the
        # commit-drift arm/disarm/confirm routes themselves) — every
        # OTHER caller of this helper (Front/Bucket/Detail GETs, ordinary
        # disarm, cycle-destination) has no error to attach a button to.
        "commit_drift": None,
        "kind": kind,
        "record_id": record_id,
        "dom_id": _dom_id(kind, record_id, target),
        "dest": dest,
        # The scope-correction note (09 §2.3 as amended 2026-07-18) is
        # threaded only at initial page render, like already_canon below
        # — a round-trip drops the explanation, never the correction:
        # `dest` itself is always a scope-valid value on every path.
        "dest_note": None,
        "event": event,
        "target": target,
        # P1-9b: `g` is always available, highlighted (affordance, not
        # qualification logic) when already_canon is set. Threaded only
        # at initial page render (bucket/detail GET) — arm/disarm/cycle
        # round-trips default it to False, a harmless conservative
        # degradation since the highlight is cosmetic, never a gate.
        "already_canon": already_canon,
        # F5-1 (feedback round 5, U19 §1.2 gate M1): the server-signaled
        # singleton-cycle no-op — action_bar.html renders the cycle
        # control without data-key-action when this has exactly one
        # element. `scope` defaults to the everywhere-valid "user" so an
        # un-threaded caller degrades to the same singleton the ledger's
        # own unlocatable-record fallback uses (never a wider cycle than
        # the record's actual scope could ever produce).
        "destination_cycle": models.destinations_for_scope(scope),
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


def _record_scope(request: Request, record_id: str) -> str:
    """Scope from the ledger, never a client field — shared by every site
    that needs a record's scope to compute either a scope-corrected dest
    (:func:`_scope_corrected_dest`) or its destination cycle (F5-1,
    feedback round 5, U19 §1.2 gate M1). An unlocatable record degrades
    to "user" — its cycle is the everywhere-valid claude-md singleton, so
    even this fallback can never offer a destination the CLI would
    refuse on scope."""
    location = ledger.locate_record(_home(request), record_id)
    return location.scope if location is not None else "user"


def _scope_corrected_dest(request: Request, record_id: str, dest: str | None) -> str | None:
    """Client-echoed dest values re-enter ARMABLE renders (disarm, a
    failed confirm's re-render) — re-derive validity server-side so
    every unarmed bar's hidden field is scope-valid by construction,
    never by trusting the echo (review 2026-07-18 F2). Scope from the
    ledger, never a client field; the corrected value is what renders
    AND arms (displayed == armed == executed)."""
    scope = _record_scope(request, record_id)
    corrected, _note = models.correct_destination(scope, dest or None)
    return corrected


@router.post("/record/{record_id}/action/disarm", response_class=HTMLResponse)
def action_disarm(
    request: Request,
    record_id: str,
    kind: str = Form("detail"),
    dest: str | None = Form(None),
    event: str | None = Form(None),
    target: str | None = Form(None),
) -> HTMLResponse:
    dest = _scope_corrected_dest(request, record_id, dest)
    ctx = _unarmed_context(
        kind=kind,
        record_id=record_id,
        dest=dest,
        event=event,
        target=target,
        scope=_record_scope(request, record_id),
    )
    return _render(request, "partials/action_bar.html", ctx)


@router.post("/record/{record_id}/action/cycle-destination", response_class=HTMLResponse)
def action_cycle_destination(
    request: Request, record_id: str, dest: str | None = Form(None)
) -> HTMLResponse:
    # The Form param is `dest` because that is the field the rendered
    # form actually carries (action_bar.html's hidden input, posted via
    # hx-include) — review 2026-07-18 F1: the handler read a `current`
    # field no template sent, so the cycle never advanced in a browser.
    # test_routes.py's template-truth test drives this route with the
    # rendered form's own fields so that class of mismatch fails loudly.
    #
    # Scope from the ledger, never a client field (09 §2.3 as amended
    # 2026-07-18). An unlocatable record degrades to "user" — its cycle
    # is the everywhere-valid claude-md singleton, so even this fallback
    # can never offer a destination the CLI would refuse on scope.
    # Located-but-RESOLVED is accepted-risk under the stateless-bar
    # posture (review 2026-07-18 F3): the cycle still renders, and a
    # later confirm takes the CLI's own refusal path while the SSE
    # refresh lands the resolved-elsewhere banner (09 §3).
    scope = _record_scope(request, record_id)
    new_dest = cycle_destination(dest or None, scope)
    ctx = _unarmed_context(
        kind="detail", record_id=record_id, dest=new_dest, event=None, target=None, scope=scope
    )
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

    # U-C3 fix: Y-8's contradicts offer is read from the PENDING record's
    # proposal sibling — capture it BEFORE the verb runs (see
    # _capture_contradicts's docstring for why an after-the-fact read is
    # unsound for `route` specifically). Non-route verbs never consult
    # this, so the read is skipped for them.
    contradicts_pre: tuple[str, ...] = (
        _capture_contradicts(home, record_id) if verb == "route" else ()
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
        # F2: the re-render is armable again — the echoed dest goes back
        # through the scope rule, same as disarm.
        corrected = _scope_corrected_dest(request, record_id, dest)
        ctx = _unarmed_context(
            kind=kind,
            record_id=record_id,
            dest=corrected,
            event=event,
            target=target,
            scope=_record_scope(request, record_id),
        )
        error_text = result.stderr or f"self-learn {' '.join(argv)} failed"
        ctx["error"] = error_text
        # U20 §2.2: the ONE dirty-target guided-commit button — eligible
        # only for a failed `route` whose stderr carries a pinned dirty
        # marker (never the drift refusal, gate M2).
        if _commit_drift_eligible(verb, result.stderr):
            ctx["commit_drift"] = _commit_drift_ctx(
                record_id=record_id,
                kind=kind,
                error_text=error_text,
                retry=_commit_drift_retry_ctx(
                    dest=dest, collapse=collapse, note=note, until=until,
                    event=event, tolerate=tolerate, target=target,
                ),
                armed=None,
            )
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

    if verb == "route" and contradicts_pre:
        return _contradicts_offer_response(request, record_id, contradicts_pre)

    bucket_name = _bucket_name_for(home, record_id)
    url = next_record_url(home, bucket_name, record_id) if bucket_name else f"/?notice={NOTICE_BUCKET_CLEAR}"
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = url
    return resp


def _bucket_dir_for(home: Path, record_id: str) -> Path:
    """Best-effort bucket dir for *record_id* regardless of which side of
    resolution it's on — ``locate_record`` finds it in ``pending/`` (the
    pre-verb :func:`_capture_contradicts` call) exactly as it finds it in
    ``resolved/`` afterward (every other caller here)."""
    loc = ledger.locate_record(home, record_id)
    return loc.bucket_dir if loc else home


def _capture_contradicts(home: Path, record_id: str) -> tuple[str, ...]:
    """U-C3 fix: read a PENDING record's proposal ``contradicts:`` list
    — this MUST run before the verb's own subprocess executes. `route`'s
    CLI success path (``ledger_ops.resolve_record`` ->
    ``remove_proposal_siblings``, 08 §1 proposal-lifecycle pin) deletes
    the proposal sibling as part of resolving the record; reading it
    AFTER ``runner.run()`` returns therefore always finds the file
    already gone in production (a real subprocess actually ran the
    delete — the previous code only passed its own tests because the
    FakeRunner records argv without executing it, leaving the seeded
    proposal file untouched: mock theater). Capturing this tuple BEFORE
    dispatch and rendering the Y-8 offer from it afterward is the fix."""
    proposal, _err = ledger.read_proposal_raw(
        _bucket_dir_for(home, record_id), record_id
    )
    return tuple((proposal or {}).get("contradicts") or [])


def _contradicts_offer_response(
    request: Request, record_id: str, contradicts: tuple[str, ...]
) -> HTMLResponse:
    """Y-8's per-edge offer, rendered from an ALREADY-CAPTURED contradicts
    tuple (see :func:`_capture_contradicts`) — never a fresh read, which
    would race the verb's own proposal-sibling deletion."""
    edges = [
        {"target": t, "dom_id": _dom_id("contradicts", record_id, t)}
        for t in contradicts
    ]
    return _render(
        request,
        "partials/contradicts_offer.html",
        {"record_id": record_id, "edges": edges},
    )


def _bucket_name_for(home: Path, record_id: str) -> str | None:
    loc = ledger.locate_record(home, record_id)
    return loc.bucket_name if loc else None


# ------------------------------------------------------ commit-drift (U20)
#
# f5-round-spec.md §2.2 (F5-5 guided commit-first): the dirty-target
# refusal stays fully intact — this is the GUIDED path a human takes
# instead of it. When a `route` confirm fails AND the stderr matches one
# of the two pinned DIRTY-specific refusal clauses (never the shared
# advice tail, never the drift clause — gate M2: the drift refusal
# carries NEITHER marker by construction, so it never grows a button),
# the error strip gains ONE action button: "Commit that repo's changes,
# then retry." Armed, two-step, composing INSIDE the existing
# error-strip/action-bar machinery (no new region, O-9) — never a
# separate route triple's own template the way host-add needed one,
# because this state lives INSIDE action_bar.html's existing `error`
# leg, not a whole alternate `kind`.
#
# gate n12: the marker match imports the SAME constants the CLI raise
# sites use (self_learn.chezmoi.CHEZMOI_DIRTY_MARKER /
# self_learn.verbs.GITOPS_DIRTY_MARKER, imported at module top) — never
# a hand-copied substring, so the marker and the message cannot drift
# apart undetected.
COMMIT_DRIFT_MARKERS = (GITOPS_DIRTY_MARKER, CHEZMOI_DIRTY_MARKER)


def _commit_drift_eligible(verb: str, stderr: str | None) -> bool:
    """§2.2: the button renders ONLY for a failed ``route`` whose stderr
    carries one of the two pinned dirty markers — never for any other
    verb (reject/defer/graduate/… never touch a compile target), and
    never for the drift refusal, which carries neither (gate M2)."""
    if verb != "route" or not stderr:
        return False
    return any(marker in stderr for marker in COMMIT_DRIFT_MARKERS)


def _commit_drift_retry_ctx(
    *,
    dest: str | None,
    collapse: str | None,
    note: str | None,
    until: str | None,
    event: str | None,
    tolerate: bool,
    target: str | None,
) -> dict[str, Any]:
    """The original failed route confirm's own fields, carried through
    every commit-drift leg so the eventual retry rebuilds the EXACT same
    argv the human's Approve tap originally armed (displayed == armed ==
    executed, the same discipline :func:`_armed_context` follows)."""
    return {
        "dest": dest,
        "collapse": collapse,
        "note": note,
        "until": until,
        "event": event,
        "tolerate": tolerate,
        "target": target,
    }


def _commit_drift_ctx(
    *,
    record_id: str,
    kind: str,
    error_text: str,
    retry: dict[str, Any],
    armed: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "kind": kind,
        "error_text": error_text,
        "retry": retry,
        "armed": armed,
    }


@router.post("/record/{record_id}/action/commit-drift/arm", response_class=HTMLResponse)
def commit_drift_arm(
    request: Request,
    record_id: str,
    kind: str = Form("detail"),
    error_text: str = Form(""),
    dest: str | None = Form(None),
    collapse: str | None = Form(None),
    note: str | None = Form(None),
    until: str | None = Form(None),
    event: str | None = Form(None),
    tolerate: bool = Form(False),
    target: str | None = Form(None),
) -> HTMLResponse:
    """§2.2 armed two-step, tap 1: read the new verb's OWN ``--dry-run
    --json`` (gate m6 — no other dirty-file-list source exists) and show
    the repo + file list. Server derives the list; the human never types
    a path. A race (the target went clean/drift since the refusal) fails
    SAFE — back to the plain error, never an armed state built on stale
    data."""
    home = _home(request)
    read = ledger.commit_drift_dry_run(home, record_id, dest=dest or None)
    retry = _commit_drift_retry_ctx(
        dest=dest, collapse=collapse, note=note, until=until,
        event=event, tolerate=tolerate, target=target,
    )
    corrected = _scope_corrected_dest(request, record_id, dest)
    ctx = _unarmed_context(kind=kind, record_id=record_id, dest=corrected, event=event, target=target, scope=_record_scope(request, record_id))
    if not read.ok:
        ctx["error"] = read.error or "commit-drift dry-run failed"
        ctx["commit_drift"] = None
        return _render(request, "partials/action_bar.html", ctx)
    data = read.data or {}
    ctx["error"] = error_text or "route failed — dirty compile target"
    ctx["commit_drift"] = _commit_drift_ctx(
        record_id=record_id,
        kind=kind,
        error_text=error_text,
        retry=retry,
        armed={"repo": data.get("repo", ""), "files": data.get("files") or []},
    )
    return _render(request, "partials/action_bar.html", ctx)


@router.post("/record/{record_id}/action/commit-drift/disarm", response_class=HTMLResponse)
def commit_drift_disarm(
    request: Request,
    record_id: str,
    kind: str = Form("detail"),
    error_text: str = Form(""),
    dest: str | None = Form(None),
    collapse: str | None = Form(None),
    note: str | None = Form(None),
    until: str | None = Form(None),
    event: str | None = Form(None),
    tolerate: bool = Form(False),
    target: str | None = Form(None),
) -> HTMLResponse:
    """Cancel: back to the SAME error-plus-button state — never a fresh
    dry-run (that only runs when the human arms again)."""
    retry = _commit_drift_retry_ctx(
        dest=dest, collapse=collapse, note=note, until=until,
        event=event, tolerate=tolerate, target=target,
    )
    corrected = _scope_corrected_dest(request, record_id, dest)
    ctx = _unarmed_context(kind=kind, record_id=record_id, dest=corrected, event=event, target=target, scope=_record_scope(request, record_id))
    ctx["error"] = error_text or "commit-drift refused"
    ctx["commit_drift"] = _commit_drift_ctx(
        record_id=record_id, kind=kind, error_text=error_text, retry=retry, armed=None
    )
    return _render(request, "partials/action_bar.html", ctx)


@router.post("/record/{record_id}/action/commit-drift/confirm", response_class=HTMLResponse)
async def commit_drift_confirm(
    request: Request,
    record_id: str,
    kind: str = Form("detail"),
    dest: str | None = Form(None),
    collapse: str | None = Form(None),
    note: str | None = Form(None),
    until: str | None = Form(None),
    event: str | None = Form(None),
    tolerate: bool = Form(False),
    target: str | None = Form(None),
) -> Response:
    """Tap 2: run the guided commit for real, then — on success — re-fire
    the ORIGINAL route confirm automatically, once, with the SAME argv
    (§2.2). A second dirty refusal (or any other retry failure) renders
    PLAINLY: no loop, and the commit-drift button never re-appears on
    that leg — only a fresh `route` confirm failure can re-offer it."""
    home = _home(request)
    runner = request.app.state.runner

    commit_argv = ["host", "commit-drift", record_id]
    if dest:
        commit_argv += ["--dest", dest]
    commit_result = await runner.run(commit_argv)
    if not commit_result.ok:
        corrected = _scope_corrected_dest(request, record_id, dest)
        ctx = _unarmed_context(kind=kind, record_id=record_id, dest=corrected, event=event, target=target, scope=_record_scope(request, record_id))
        ctx["error"] = commit_result.stderr or "self-learn host commit-drift failed"
        return _render(request, "partials/action_bar.html", ctx)

    # Commit landed — auto-retry the original route confirm, same argv,
    # same interrupt-first / contradicts-capture discipline as a normal
    # confirm (action_confirm's own sequence, mirrored here because this
    # is a SECOND verb dispatch inside one request, not a client re-post).
    contradicts_pre = _capture_contradicts(home, record_id)
    manager = _pane_manager(request)
    if manager is not None:
        await manager.interrupt_active_session(record_id)
    route_argv = build_argv(
        "route",
        record_id,
        dest=dest or None,
        collapse=collapse or None,
        note=note or None,
        until=until or None,
        event=event or None,
        tolerate=tolerate,
        target=target or None,
    )
    await _publish_applying(request, "route", record_id, "start")
    retry = await runner.run(route_argv)
    await _publish_applying(request, "route", record_id, "done" if retry.ok else "error")

    if not retry.ok:
        _force_refresh(request, f"record:{record_id}")
        corrected = _scope_corrected_dest(request, record_id, dest)
        ctx = _unarmed_context(kind=kind, record_id=record_id, dest=corrected, event=event, target=target, scope=_record_scope(request, record_id))
        ctx["error"] = retry.stderr or f"self-learn {' '.join(route_argv)} failed"
        return _render(request, "partials/action_bar.html", ctx)

    _force_refresh(request, f"record:{record_id}")
    slot = _proposal_slot(request)
    if slot is not None:
        slot.clear_for_record(record_id)
    if collapse:
        _sweep_stale_proposal(request)
    if contradicts_pre:
        return _contradicts_offer_response(request, record_id, contradicts_pre)

    bucket_name = _bucket_name_for(home, record_id)
    url = next_record_url(home, bucket_name, record_id) if bucket_name else f"/?notice={NOTICE_BUCKET_CLEAR}"
    # 07 §4 contract 2 / 09 §3: verb stdout is never parsed for control or
    # display (a real runner's stdout is human-formatted, not a data
    # contract) — the commit's own sha is therefore not surfaced here;
    # the redirect target's re-read state IS the ground truth, same as
    # every other successful confirm.
    resp = Response(content="Committed. Retrying…", status_code=200)
    resp.headers["HX-Redirect"] = url
    return resp


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
#     to, constrained to a record-id shape (else the bucket page),
#     PLUS — on disclosure arms only — the Y-17 one-bit marker below;
#   - the ARM state renders the consent consequence (the CLI prints it
#     on stdout, which the runner contract discards);
#   - project buckets only — skill/user notices keep prose fallback.
#
# 09 §11 Y-17 (2026-07-18, U14): `needs_init` is derived SERVER-side at
# arm AND re-derived at confirm via the CLI-owned `is_repo_root` helper
# (imported — the canon_read_roots posture, never a second
# implementation). Operationalization of record (builder's choice, the
# marker-field variant): the arm-with-disclosure rendering carries a
# server-rendered hidden field `init_disclosed=1` in its confirm form —
# ONE client-supplied bit standing for "the ARM rendering displayed the
# disclosure". The consent invariant (Y-17 F1): the executed argv
# includes `--init` only when that bit is present AND the confirm-time
# re-derivation still holds; ANY mismatch runs plain `host add`. The
# bit can only ever WEAKEN execution (toward plain add / a clean
# refusal), never strengthen it — a forged or stale marker on a
# repo-root path is neutralized by the re-derivation (worst outcome: a
# clean refusal), and read-run divergence is permitted in the
# weaker-than-read direction ONLY (F13).
#
# 09 §11 Y-16 (2026-07-18, U14): the confirm's error leg renders the
# plain-words failure sentence LEADING with the CLI stderr demoted to a
# secondary detail line (the narrow dated §5 exception, this leg only),
# carries the `[data-verb-error]` marker app.js's reload-defer keys on,
# and persists until dismiss (the disarm route — no fourth route) or
# re-arm. The wipe mechanism is pinned empirically in
# tests/test_registration_wipe.py + 10's appendix (U14 entry).

_RECORD_ID_RE = re.compile(r"^lrn-[0-9a-f]{8}$")

#: Y-16's required copy (the F2/F11 twice-corrected sentence): true in
#: EVERY failure leg, including HalfWritten — where hosts.yaml already
#: carries the entry and "was not registered" would be false. The
#: demoted stderr detail carries the state facts and the repair.
HOST_ADD_ERROR_LEAD = "Registration did not complete."


def build_host_add_argv(path: str, *, init: bool = False) -> list[str]:
    """``self-learn host add [--init] <path>`` — the one argv this
    surface maps to (mirrors the CLI parser verbatim, same rule as
    build_argv). ``init`` is decided by the Y-17 consent invariant at
    the confirm route, never by a client field alone."""
    return ["host", "add", "--init", path] if init else ["host", "add", path]


def _needs_init(path: str) -> bool:
    """Y-17: does registering *path* require the ``--init`` leg — i.e.
    is the exact resolved path NOT already a git repo root? One
    predicate, CLI-owned (:func:`self_learn.hosts.is_repo_root`),
    imported for both the arm derivation and the confirm re-derivation."""
    return not is_repo_root(path)


def _host_add_ctx(
    *,
    scope: str,
    name: str,
    record_id: str | None,
    armed: bool,
    path: str | None = None,
    error: str | None = None,
    needs_init: bool = False,
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
        "error_lead": HOST_ADD_ERROR_LEAD,
        "needs_init": needs_init,
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
    ctx = _host_add_ctx(
        scope=scope,
        name=name,
        record_id=rid,
        armed=True,
        path=path,
        # Y-17: server-derived, never a client field — when True the arm
        # banner shows the git-init disclosure + the real --init argv,
        # and the confirm form carries the server-rendered marker bit.
        needs_init=_needs_init(path),
    )
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
    request: Request,
    scope: str,
    name: str,
    record_id: str | None = Form(None),
    init_disclosed: str | None = Form(None),
) -> Response:
    resolved = _host_add_target(request, scope, name)
    if isinstance(resolved, Response):
        return resolved
    _bucket, path = resolved
    rid = record_id if record_id and _RECORD_ID_RE.match(record_id) else None

    # Y-17 consent invariant (F1): `--init` executes ONLY when (a) the
    # arm rendering displayed the disclosure (the server-rendered marker
    # bit, posted back verbatim) AND (b) the confirm-time re-derivation
    # still holds. Any mismatch — becomes-repo (disclosed, but a root by
    # now: --init dropped, the plain add registers) or goes-stale (not
    # disclosed, a non-root by now: the plain add runs and the CLI's
    # committability refusal flows into the Y-16 error leg) — runs plain
    # `host add`; never a silent init. A forged marker cannot force an
    # init on a repo-root path: the re-derivation gates every init, so
    # the bit only ever WEAKENS execution relative to what was read.
    use_init = init_disclosed == "1" and _needs_init(path)

    runner = request.app.state.runner
    result = await runner.run(build_host_add_argv(path, init=use_init))
    if not result.ok:
        # Y-16 error leg: plain-words sentence leading, stderr demoted,
        # [data-verb-error] marker, dismiss via the disarm route — and
        # it PERSISTS client-side (app.js defers broadcast reloads while
        # the marker is in the DOM).
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
        ctx = _unarmed_context(
            kind="detail",
            record_id=record_id,
            dest=None,
            event=None,
            target=None,
            scope=_record_scope(request, record_id),
        )
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
        # Y-18 bucket-change leg (09 §4.5 as extended 2026-07-18, folds
        # F2/F5/F10): rehome made a pending record's bucket facts
        # mutable — compare the slot's captured bucket against the
        # record's CURRENT bucket. Mismatch → clear the slot + a
        # plain-words notice, NEVER a disarm (a surviving waiting bar
        # would carry exactly the stale bucket facts this leg kills);
        # the agent re-proposes against the record's new home.
        if location is not None and (
            location.scope,
            location.bucket_name,
        ) != (current.bucket_scope, current.bucket_name):
            slot.clear_for_record(record_id)
            return _proposal_gone(
                request, kind, record_id, error=NOTICE_PROPOSAL_MOVED
            )
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

    # Y-18 bucket-change leg, the CONFIRM side — load-bearing, not belt
    # (09 §4.5 as extended 2026-07-18): the CLI verbs locate records
    # across ALL buckets, so without this check Enter on a stale armed
    # bar would execute the verb against the record in its NEW bucket —
    # compiling into a different project's canon than the bar the human
    # read. Mismatch → clear the slot + plain-words notice (the
    # resolved-elsewhere shape), never the verb and never a waiting bar.
    # A missing/unlocatable record deliberately falls through: the
    # stale-record confirm keeps taking the verb's own refusal path.
    location = ledger.locate_record(home, record_id)
    if location is not None and (
        location.scope,
        location.bucket_name,
    ) != (prop.bucket_scope, prop.bucket_name):
        slot.clear_for_record(record_id)
        return _proposal_gone(request, kind, record_id, error=NOTICE_PROPOSAL_MOVED)

    # Capture argv from the SLOT before anything can clear it (the
    # interrupt below tears down the proposing session, whose teardown
    # clears the slot by session key).
    argv = build_argv(
        prop.verb,
        prop.record_id,
        dest=prop.dest,
        note=prop.note,
        until=prop.until,
        to=prop.to,
    )
    # U-C3 fix: same pre-verb capture as action_confirm (see
    # _capture_contradicts) — `route`'s CLI success path deletes the
    # proposal sibling as part of resolving the record, so this MUST be
    # read before runner.run(), not after.
    contradicts_pre: tuple[str, ...] = (
        _capture_contradicts(home, record_id) if prop.verb == "route" else ()
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

    if prop.verb == "route" and contradicts_pre:
        return _contradicts_offer_response(request, record_id, contradicts_pre)

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


@router.post("/bucket/{scope}/{name}/pane/resume", response_class=HTMLResponse)
async def bucket_pane_resume(
    request: Request, scope: str, name: str, force: bool = Form(False)
) -> HTMLResponse:
    """U22 — the bucket pane's Resume control (§5: "the bucket key is a
    first-class session key, so the store, the card, and the controls
    are the same code path")."""
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    key = _bucket_pane_key(scope, name)
    outcome = await manager.resume(key, force=force)
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
    if outcome == "not-resumable":
        snapshot = manager.snapshot(key)
        return _render(
            request, "partials/pane_idle.html", {**_bucket_pane_ctx(scope, name, snapshot), "bucket_pane": True}
        )
    snapshot = manager.snapshot(key)
    return _render(request, "partials/pane.html", _bucket_pane_ctx(scope, name, snapshot))


@router.get("/bucket/{scope}/{name}/pane/view", response_class=HTMLResponse)
def bucket_pane_view(request: Request, scope: str, name: str) -> HTMLResponse:
    """U22 — the bucket pane's View control."""
    manager = _pane_manager(request)
    if manager is None:
        return _pane_not_wired()
    key = _bucket_pane_key(scope, name)
    view = manager.view_snapshot(key)
    if view is None:
        snapshot = manager.snapshot(key)
        return _render(
            request, "partials/pane_idle.html", {**_bucket_pane_ctx(scope, name, snapshot), "bucket_pane": True}
        )
    return _render(request, "partials/pane.html", _bucket_pane_ctx(scope, name, view))


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
    # Y-14: the tracker rides along so the stream's own disconnect
    # stamps the activity clock (the middleware's completion stamp for
    # a streaming response fires at CONNECT time — dispatch returns
    # when the response starts, not when the stream closes).
    tracker = getattr(request.app.state, "activity_tracker", None)
    return StreamingResponse(
        event_stream(refresh_hub, app_hub, tracker=tracker),
        media_type="text/event-stream",
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
