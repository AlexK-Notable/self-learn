"""FW-17 — the JS DOM harness for ``static/app.js`` (forward/ui-ux.md §1).

``app.js`` guards real invariants (the Y-16 reload-defer three-legged
predicate, ensureRowSelected/ensureContentFocus, the data-key-action
dispatch against the keymap) with ZERO test coverage until now — every
one was verified only by a live trial at ship time. This suite drives the
REAL served pages in a REAL browser (the only engine that runs app.js +
htmx + EventSource) against a throwaway sandbox ledger.

Harness (builder's choice, gate to judge): **pytest + Playwright
(python), sync API**, driving one in-process uvicorn instance of the real
``create_app`` (10 §0 rules 7/8: SELF_LEARN_HOME + XDG all redirected
under a pytest tmpdir — never the real ledger, cache, or runtime dir; no
network beyond 127.0.0.1). Playwright's python package is a pip/uv
dependency whose browser driver is bundled — it adds no npm/node
toolchain the developer manages; the matched Chromium build is fetched
once via ``uv run playwright install chromium``. The whole module is
marked ``js`` (``-m js`` / ``-m 'not js'``) and AUTO-SKIPS when that
browser is not installed, so the default ``pytest`` run never depends on
it. ONE browser + ONE seeded server are reused across every test (MODULE
scope — not session: Playwright's sync API holds an event loop on the main
thread, so the browser must be torn down at this module's end, before any
other module's pytest-asyncio tests run, or they collide with "another
loop is running"); each test gets a fresh browser CONTEXT/page so app.js
module state (confirmInFlight/reloadPending) and injected DOM never leak.

Reaching the closure-private predicate: app.js wraps everything in an
IIFE, so ``reloadDeferred``/``ensureContentFocus`` etc. are not callable
directly. They are exercised the only way production does — through real
DOM events and their observable effects:
  * the reload() CHOKEPOINT is triggered by pushing a real SSE ``refresh``
    frame from the server (``force_refresh`` on the app's own event loop);
    "did it reload?" is read from a window sentinel that a real
    ``location.reload()`` wipes.
  * the htmx lifecycle legs (beforeRequest/afterSettle/error family) are
    driven by dispatching the same CustomEvents htmx itself fires.
  * focus/selection/dispatch are driven by real key presses and load.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import uvicorn

from self_learn.verbs import GITOPS_DIRTY_MARKER

from self_learn_ui.app import create_app
from self_learn_ui.env import EnvConfig
from self_learn_ui.keymap import keymap_as_dicts
from self_learn_ui.proposals import VerbProposal
from self_learn_ui.runner import FakeRunner, RunResult
from self_learn_ui.sse import envelope_applying, envelope_bulk_progress

from support import (
    make_env,
    make_behavior,
    resolve_record_directly,
    seed_proposal,
    seed_record,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

# Pin Playwright's browser registry to its REAL location NOW, at import —
# before the server fixture redirects XDG_CACHE_HOME under a tmpdir (which
# would otherwise send Playwright looking for Chromium in the sandbox and
# never finding it). PLAYWRIGHT_BROWSERS_PATH overrides that XDG lookup.
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "ms-playwright"),
)

# Playwright's python package + its Chromium are optional dev extras; the
# whole module skips cleanly when either is missing (keeps `pytest` green
# on a machine that never ran `playwright install`).
sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

pytestmark = pytest.mark.js

_STARTUP_TIMEOUT_S = 15.0
_SHUTDOWN_TIMEOUT_S = 10.0
#: A generous ceiling for a same-host SSE frame to arrive and reload() to
#: navigate. Frames land in <50 ms on loopback; this is only the failure
#: bound.
_RELOAD_TIMEOUT_MS = 5000
#: How long to wait before concluding a reload was correctly DEFERRED.
#: Also loopback-fast; a held leg must never navigate within this window.
_DEFER_QUIET_S = 0.6

TOKEN = "js-dom-harness-token"

# Record ids seeded once for the whole module.
REC_BRIEF = "lrn-b71e0001"  # in bucket skill:s — carries an Episode brief
REC_PROP = "lrn-90020002"  # in bucket skill:t — target of proposal-slot tests


# --------------------------------------------------------------- server


class ServerHandle:
    """A running in-process uvicorn server plus the seams a browser test
    needs to poke it deterministically: push an SSE refresh, occupy/clear
    the in-memory proposal slot, count SSE subscribers."""

    def __init__(self, base_url: str, app, loop: asyncio.AbstractEventLoop) -> None:
        self.base_url = base_url
        self._app = app
        self._loop = loop

    @property
    def _refresh_hub(self):
        return self._app.state.refresh_hub

    @property
    def _slot(self):
        return self._app.state.pane_manager.proposal_slot

    @property
    def _app_hub(self):
        return self._app.state.app_hub

    @property
    def runner(self):
        return self._app.state.runner

    def push_applying(self, verb: str, record_id: str, state: str) -> None:
        """§5.7 test seam: publish a real `applying` SSE frame — via
        `publish_nowait` (§4.5: `AppEventHub.publish` is `async def`;
        handing it straight to `call_soon_threadsafe` would hand over an
        un-awaited coroutine and publish nothing, silently). Must hop
        onto the server's own loop, same as push_refresh."""
        self._loop.call_soon_threadsafe(
            self._app_hub.publish_nowait, envelope_applying(verb, record_id, state)
        )

    def push_bulk_progress(
        self, done: int, total: int, failed_id: str | None = None
    ) -> None:
        self._loop.call_soon_threadsafe(
            self._app_hub.publish_nowait, envelope_bulk_progress(done, total, failed_id)
        )

    def push_envelope(self, envelope: dict) -> None:
        """Raw seam for test 7's synthetic unknown envelope type — the
        two typed helpers above only build the two pinned shapes."""
        self._loop.call_soon_threadsafe(self._app_hub.publish_nowait, envelope)

    def push_refresh(self, scope: str = "front") -> None:
        """Emit one real ``refresh`` SSE frame to every connected client.
        Must hop onto the server's own loop — force_refresh wakes the
        stream's awaiting task, which only works from that loop."""
        self._loop.call_soon_threadsafe(self._refresh_hub.force_refresh, scope)

    def subscriber_count(self) -> int:
        return self._refresh_hub.subscriber_count

    def wait_for_subscriber(self, minimum: int = 1, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.subscriber_count() >= minimum:
                return
            time.sleep(0.02)
        raise AssertionError(
            f"no SSE subscriber appeared within {timeout}s "
            f"(count={self.subscriber_count()})"
        )

    def occupy_proposal(self, proposal: VerbProposal) -> None:
        self._slot.clear()
        self._slot.occupy(proposal)

    def clear_proposal(self) -> None:
        self._slot.clear()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_ledger(tmp_path: Path) -> Path:
    """Two buckets (skill:s, skill:t) with one pending record each; the
    skill:s record additionally carries an ``## Episode brief`` section so
    the Detail page renders the `b`-toggled disclosure."""
    sb = make_env(tmp_path, skills=("s", "t"))
    brief = make_behavior(
        scope="skill:s",
        record_id=REC_BRIEF,
        trigger="About to edit .storage while HA is running.",
        instruction="Stop the container first.",
    )
    path = seed_record(sb.ledger, brief)
    # Append a real brief section to the record body (the miner writes it
    # the same way; models._split_episode_brief reads it back).
    path.write_text(
        path.read_text(encoding="utf-8").rstrip("\n")
        + "\n\n## Episode brief\n"
        + "Tried to hand-edit the running config and it clobbered live "
        + "state; stopping the service first fixed it.\n",
        encoding="utf-8",
    )
    other = make_behavior(
        scope="skill:t",
        record_id=REC_PROP,
        trigger="About to force-push over a shared branch.",
        instruction="Pull and rebase first.",
    )
    seed_record(sb.ledger, other)
    return sb.ledger


def _start_server(ledger: Path, thread_name: str) -> Iterator[ServerHandle]:
    """The uvicorn-in-thread bring-up shared by every module server
    fixture below (extracted at F5-1/F5-2, feedback round 5, U19 §1.2,
    so a second ledger — ``noop_server``'s — doesn't hand-duplicate the
    whole lifecycle). NB: no global os.environ mutation here. The route
    handlers shell `self-learn ... --json`, and ledger._invoke_json pins
    SELF_LEARN_HOME to the sandbox per call; the CLI namespaces its cache
    by that home, so the child never touches the real ledger (the same
    isolation every in-process route test relies on). Mutating
    os.environ session-wide would leak into the rest of the suite."""
    port = _free_port()
    env = EnvConfig(
        self_learn_home=ledger,
        ui_port=port,
        ui_browser=None,
        pane_model="test-model",
        pane_budget_usd=1.0,
        pane_max_turns=5,
        pane_engine="sdk",
    )
    app = create_app(
        env=env,
        token=TOKEN,
        runner=FakeRunner(),
        start_watcher=False,  # refreshes are pushed explicitly per test
    )

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"
    )
    uv_server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(uv_server.serve())

    thread = threading.Thread(target=_run, name=thread_name, daemon=True)
    thread.start()

    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    while not uv_server.started:
        if time.monotonic() > deadline:
            uv_server.should_exit = True
            raise AssertionError("in-process uvicorn never started")
        time.sleep(0.02)

    try:
        yield ServerHandle(f"http://127.0.0.1:{port}", app, loop)
    finally:
        uv_server.should_exit = True
        thread.join(timeout=_SHUTDOWN_TIMEOUT_S)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    tmp_path = tmp_path_factory.mktemp("js-dom")
    ledger = _seed_ledger(tmp_path)
    yield from _start_server(ledger, "js-dom-uvicorn")


@pytest.fixture(scope="module")
def browser(server: ServerHandle) -> Iterator["Browser"]:
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # pragma: no cover - env-dependent
            pytest.skip(f"Chromium unavailable for Playwright: {exc}")
        try:
            yield b
        finally:
            b.close()


@pytest.fixture
def page(browser: "Browser", server: ServerHandle) -> Iterator["Page"]:
    context = browser.new_context()
    pg = context.new_page()
    try:
        yield pg
    finally:
        context.close()
        server.clear_proposal()


# F5-1/F5-2 (feedback round 5, U19 §1.2): a SEPARATE module-scoped ledger
# + server from the pair above — the singleton `o`-cycle case needs a
# user-scope record, which neither of `_seed_ledger`'s two skill-scoped
# buckets provide, and adding one there would perturb every other test's
# Front-page row-count/selection assumptions in this file for no reason.
REC_USER = "lrn-05100001"  # scope=user — the everywhere-valid singleton cycle
REC_NOOP_MULTI = "lrn-05300003"  # scope=skill:s, no brief — armed/proposal/`b` cases


def _seed_noop_ledger(tmp_path: Path) -> Path:
    sb = make_env(tmp_path, skills=("s",))
    seed_record(
        sb.ledger,
        make_behavior(
            scope="user",
            record_id=REC_USER,
            trigger="About to hand-edit a chezmoi-managed dotfile.",
            instruction="Run chezmoi apply instead.",
        ),
    )
    seed_record(
        sb.ledger,
        make_behavior(
            scope="skill:s",
            record_id=REC_NOOP_MULTI,
            trigger="About to force-push over a shared branch.",
            instruction="Pull and rebase first.",
        ),
    )
    return sb.ledger


@pytest.fixture(scope="module")
def noop_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    tmp_path = tmp_path_factory.mktemp("js-dom-noop")
    ledger = _seed_noop_ledger(tmp_path)
    yield from _start_server(ledger, "js-dom-noop-uvicorn")


@pytest.fixture
def noop_page(browser: "Browser", noop_server: ServerHandle) -> Iterator["Page"]:
    context = browser.new_context()
    pg = context.new_page()
    try:
        yield pg
    finally:
        context.close()
        noop_server.clear_proposal()


# F3's `tolerate`/`confirm_recurrence` tests need a REAL "is it holding?"
# row (09 §11 Y-4) — a routed record with an unconfirmed recurrence-
# suspect telemetry event, which only the real `self-learn report --json`
# CLI can compute (report.py's `recurrence_suspects()` reads the tracked
# `<home>/telemetry/*.jsonl` plane). A dedicated ledger/server, same
# reasoning as noop_server above: adding a holding row to the SHARED
# ledger would perturb every other test's Front-page row-count/selection
# assumptions in this file for no reason. Built the same way
# `resolve_record_directly` already builds hard-to-reach ledger states —
# bypassing the real `route`/miner machinery, writing the tracked files
# directly — never a new mechanism.
REC_HOLDING = "lrn-a0100001"


def _seed_holding_ledger(tmp_path: Path) -> Path:
    sb = make_env(tmp_path, skills=("s",))
    rec = make_behavior(
        scope="skill:s",
        record_id=REC_HOLDING,
        trigger="About to edit .storage while HA is running.",
        instruction="Stop the container first.",
    )
    path = seed_record(sb.ledger, rec)
    bucket_dir = path.parent.parent
    resolve_record_directly(sb.ledger, bucket_dir, rec, status="routed")
    tel_dir = sb.ledger / "telemetry"
    tel_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "kind": "recurrence-suspect",
        "record": REC_HOLDING,
        "nonce": "js-dom-holding-nonce",
        "ts": "2026-07-20T00:00:00Z",
    }
    (tel_dir / "2026-07.js-dom-fixture.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8"
    )
    return sb.ledger


@pytest.fixture(scope="module")
def holding_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    tmp_path = tmp_path_factory.mktemp("js-dom-holding")
    ledger = _seed_holding_ledger(tmp_path)
    yield from _start_server(ledger, "js-dom-holding-uvicorn")


@pytest.fixture
def holding_page(browser: "Browser", holding_server: ServerHandle) -> Iterator["Page"]:
    context = browser.new_context()
    pg = context.new_page()
    try:
        yield pg
    finally:
        context.close()


# F2's disabling tests need REAL failed-route/commit-drift and
# already-canon-bulk states, plus control over exactly when the runner
# responds (test 19's commit-drift setup) — a dedicated ledger/server +
# FakeRunner, isolated from the shared server's tests above.
REC_F2_PLAIN = "lrn-f2000001"  # pending — setup A (tests 14-18)
REC_F2_DRIFT = "lrn-f2000002"  # pending — setup B (test 19, commit-drift)
REC_F2_PROP = "lrn-f2000003"  # pending — setup C (test 20, proposal)
REC_F2_BULK = "lrn-f2000004"  # already-canon proposal — setup D (test 21)


def _seed_f2_ledger(tmp_path: Path) -> Path:
    sb = make_env(tmp_path, skills=("s",))
    for rid in (REC_F2_PLAIN, REC_F2_PROP):
        seed_record(sb.ledger, make_behavior(scope="skill:s", record_id=rid))
    drift_rec = make_behavior(scope="skill:s", record_id=REC_F2_DRIFT)
    seed_record(sb.ledger, drift_rec)
    # test 19's commit-drift ARM tap runs a REAL `self-learn host
    # commit-drift --dry-run --json` subprocess (ledger.py's
    # commit_drift_dry_run, never a FakeRunner seam — see
    # test_commit_drift.py's own module docstring for why: the armed
    # leg's file list has no other data source, gate m6). Deliberately
    # NO seeded proposal here (unlike test_commit_drift.py's `_seed()`):
    # a "skill-md"-destined proposal would land REC_F2_DRIFT in the SAME
    # bucket group as REC_F2_BULK (models.py's `_group_key_for` groups by
    # destination), breaking test 21's "all rows already_canon" group
    # invariant that `bulk_collapse` requires (measured: it did, on a
    # first attempt). No proposal keeps it in "no-analysis" — excluded
    # from bulk_collapse consideration entirely — while dest resolves to
    # None, so the dry-run runs with no --dest flag against the dirtied
    # skill_md below.
    bulk_rec = make_behavior(scope="skill:s", record_id=REC_F2_BULK)
    seed_record(sb.ledger, bulk_rec)
    seed_proposal(sb.ledger, bulk_rec.id, destination="skill-md", already_canon=True)
    # Same technique as test_commit_drift.py's `_seed_dirty`: append an
    # uncommitted edit to the REAL, sandboxed skill_md so the dry-run
    # subprocess has actual git drift to report.
    sb.skill_md.write_text(
        sb.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
        encoding="utf-8",
    )
    return sb.ledger


@pytest.fixture(scope="module")
def f2_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    tmp_path = tmp_path_factory.mktemp("js-dom-f2")
    ledger = _seed_f2_ledger(tmp_path)
    yield from _start_server(ledger, "js-dom-f2-uvicorn")


@pytest.fixture
def f2_page(browser: "Browser", f2_server: ServerHandle) -> Iterator["Page"]:
    context = browser.new_context()
    pg = context.new_page()
    try:
        yield pg
    finally:
        context.close()
        f2_server.clear_proposal()


# --------------------------------------------------------------- helpers


def _authenticate(page: "Page", server: ServerHandle) -> None:
    """Token-URL -> cookie once per page; later gotos ride the cookie."""
    page.goto(f"{server.base_url}/?token={TOKEN}", wait_until="load")


def _open(page: "Page", server: ServerHandle, path: str) -> None:
    if not page.context.cookies():
        _authenticate(page, server)
    page.goto(f"{server.base_url}{path}", wait_until="load")
    server.wait_for_subscriber(1)


def _arm_reload_sentinel(page: "Page") -> None:
    """Set a window flag that a real ``location.reload()`` (fresh JS
    context) wipes — the observable difference between deferred and fired."""
    page.evaluate("window.__navMarker = true")


def _assert_deferred(page: "Page") -> None:
    time.sleep(_DEFER_QUIET_S)
    assert page.evaluate("window.__navMarker === true"), "reload was NOT deferred (page reloaded)"


def _assert_reloaded(page: "Page") -> None:
    page.wait_for_function("window.__navMarker === undefined", timeout=_RELOAD_TIMEOUT_MS)


def _dispatch_htmx(page: "Page", event_name: str, path: str) -> None:
    """Fire an htmx lifecycle CustomEvent app.js listens for, carrying the
    request path shape isConfirmRequest() reads."""
    page.evaluate(
        """([name, path]) => {
            const e = new CustomEvent(name, { detail: { requestConfig: { path } } });
            document.dispatchEvent(e);
        }""",
        [event_name, path],
    )


def _selected_index(page: "Page") -> int:
    return page.evaluate(
        """() => {
            const rows = Array.from(
                document.querySelectorAll('#self-learn-ui-content [data-row]')
            );
            return rows.findIndex(r => r.classList.contains('selected'));
        }"""
    )


def _proposal(record_id: str, *, verb: str = "route", armed: bool = False) -> VerbProposal:
    return VerbProposal(
        verb=verb,
        record_id=record_id,
        bucket_scope="skill",
        bucket_name="t",
        session_key=record_id,
        title="Pull and rebase first.",
        dest="skill-md",
        armed=armed,
    )


def _applying_strip(page: "Page"):
    return page.locator("#self-learn-ui-applying-strip")


def _wrap_event_source(page: "Page") -> None:
    """Test-side EventSource capture, installed via ``add_init_script`` so
    it runs before app.js constructs its own EventSource (no production
    change — R3-m1).

    MEASURED (2026-07-25): spec §6 test 10's named seam,
    ``BrowserContext.set_offline``, does NOT sever an already-open
    EventSource connection in the installed Playwright/Chromium. Four
    independent checks confirmed this: (1) the reconnect strip never
    appears within 60s of ``set_offline(True)``; (2) plain ``fetch()``
    DOES immediately fail while offline, proving the emulation itself is
    active — it just never reaches an established streaming response;
    (3) polling the EventSource's own ``readyState`` directly shows it
    stays ``1`` (OPEN) throughout; (4) a direct CDP
    ``Network.emulateNetworkConditions({offline: true, ...})`` call via
    ``context.new_cdp_session()`` reproduces the same non-effect. This is
    a spec defect in the named seam, not a harness bug — reported to the
    orchestrator rather than silently worked around.

    The substitute seam below captures the real EventSource instance and
    lets the test dispatch a genuine ``error`` Event at it directly,
    invoking app.js's actual ``source.onerror`` production handler (the
    same technique this module already uses in ``_dispatch_htmx`` to
    drive htmx's own lifecycle events)."""
    page.add_init_script(
        """
        window.__esInstances = [];
        const RealES = window.EventSource;
        function WrappedES(...args) {
            const es = new RealES(...args);
            window.__esInstances.push(es);
            return es;
        }
        WrappedES.prototype = RealES.prototype;
        WrappedES.CONNECTING = RealES.CONNECTING;
        WrappedES.OPEN = RealES.OPEN;
        WrappedES.CLOSED = RealES.CLOSED;
        window.EventSource = WrappedES;
        """
    )


def _simulate_sse_error(page: "Page") -> None:
    """Dispatch a real ``error`` Event at the captured EventSource
    instance — drives app.js's production ``source.onerror`` handler
    directly. See ``_wrap_event_source`` for why ``set_offline`` cannot
    be used here."""
    page.evaluate(
        "window.__esInstances[window.__esInstances.length - 1]"
        ".dispatchEvent(new Event('error'))"
    )


def _hold_post(page: "Page", suffix: str) -> dict:
    """Intercept the next POST whose URL ends in *suffix*, capturing the
    Route object for a LATER `.fulfill()` rather than resolving it now —
    F2's "hold the request open" seam (§4.5: `page.route()` intercepts in
    the browser, so a held POST never reaches the real handler). Also
    used for `iterate`/`bucket_pane`/`retry` keymap tests: those verbs'
    routes call `PaneManager.start()`/`.resume()` for real (a genuine SDK
    engine call) — this file's `create_app()` wires the REAL engine
    factory (no test override), so letting the request complete would
    fire a real, uncontrolled network call. Intercepting still proves
    "the control was activated" (the right request was dispatched) without
    ever letting it run."""
    held: dict = {}

    def handler(route) -> None:
        if route.request.method == "POST" and route.request.url.endswith(suffix):
            held["route"] = route
        else:
            route.continue_()

    page.route("**/*", handler)
    return held


def _wait_for_held(held: dict, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while "route" not in held:
        if time.monotonic() > deadline:
            raise AssertionError("the expected POST was never intercepted")
        time.sleep(0.02)


def _wait_for_js_flag(page: "Page", expr: str, timeout: float = 5.0) -> None:
    """Poll a page-global boolean from the Python side. Equivalent in
    effect to Playwright's `wait_for_function` on the same expression;
    either is correct here.

    CORRECTION (code gate, 2026-07-25): an earlier version of this
    docstring claimed, as MEASURED, that `wait_for_function` trips this
    app's pinned CSP (`script-src 'self'`). **That claim was false.** The
    gate probed it directly against a page served by this app and the
    expression form returned OK with zero console CSP violations — and
    this very file already uses `wait_for_function` successfully in the
    end-to-end tests below. The rationale is corrected rather than the
    code: this helper works, and rewriting working waits on a false
    premise would be the larger risk. Recorded rather than deleted so the
    false "MEASURED" claim cannot be resurrected from git history as
    though it had been verified."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expr):
            return
        time.sleep(0.02)
    raise AssertionError(f"{expr!r} never became true within {timeout}s")


def _start_frame_recorder(page: "Page") -> None:
    """A SECOND, in-page EventSource — app.js's own is closure-private,
    so the only way to observe real server-published SSE frames from a
    test is to open another subscriber and record what it sees (§4.5's
    end-to-end tests: real submissions, no `page.route()`)."""
    page.evaluate(
        """() => {
            window.__frames = [];
            window.__frameSource = new EventSource('/events');
            window.__frameSource.onmessage = function (e) {
                window.__frames.push(JSON.parse(e.data));
            };
        }"""
    )


# ============================================================= item 1:
# reload-defer predicate — three legs + defer-never-drop.
#
# Each leg: (1) hold the leg, arm the sentinel, push a real refresh ->
# assert DEFERRED; (2) release the leg + fire a settle/error -> assert the
# deferred reload FIRES (defer-never-drop).


class TestReloadDeferLegA:
    """Leg (a): a [data-verb-error] element in the document defers."""

    def test_verb_error_defers_then_fires_on_clear(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div data-verb-error>boom</div>')"
        )
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)  # leg (a) holds

        # Dismiss the error, then a (non-confirm) settle drives releaseReload.
        page.evaluate("document.querySelector('[data-verb-error]').remove()")
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/arm")
        _assert_reloaded(page)  # deferred-not-dropped


class TestReloadDeferLegB:
    """Leg (b): a verb-confirm POST in flight defers; the flag clears on
    settle AND on every error/abort/timeout listener (the :383 list)."""

    def test_confirm_in_flight_defers_then_fires_on_settle(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        _dispatch_htmx(page, "htmx:beforeRequest", "/record/x/action/confirm")
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)  # leg (b) holds

        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/confirm")
        _assert_reloaded(page)  # settle clears the flag AND releases

    @pytest.mark.parametrize(
        "error_event",
        [
            "htmx:responseError",
            "htmx:swapError",
            "htmx:sendError",
            "htmx:sendAbort",
            "htmx:timeout",
        ],
    )
    def test_confirm_flag_clears_on_error_family(
        self, page: "Page", server: ServerHandle, error_event: str
    ) -> None:
        """A confirm that dies without a swap must not leave the tab
        deferring forever — every listener in the :383 family clears the
        flag. Removing any one (e.g. htmx:swapError) leaves its
        parametrization deferred-forever, so this test kills that mutation."""
        _open(page, server, "/")
        _dispatch_htmx(page, "htmx:beforeRequest", "/record/x/action/confirm")
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)

        _dispatch_htmx(page, error_event, "/record/x/action/confirm")
        _assert_reloaded(page)


class TestReloadDeferLegC:
    """Leg (c): any [data-armed="true"] bar defers."""

    def test_armed_bar_defers_then_fires_on_disarm(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div class=\"action-bar\" data-armed=\"true\" id=\"t-armed\"></div>')"
        )
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)  # leg (c) holds

        # Disarm, then a settle releases.
        page.evaluate("document.getElementById('t-armed').setAttribute('data-armed', 'false')")
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/arm")
        _assert_reloaded(page)


class TestCommitDriftArmedSurvivesRefresh:
    """U20 §2.2 (F5-5 guided commit-first): the commit-drift armed
    sub-state — a `.action-bar[data-armed="true"]` shape rendered INSIDE
    the existing error strip (no new region, O-9) — reuses leg (c)
    verbatim: no new JS, per the round spec's own pin. This drives the
    EXACT markup ``action_bar.html`` renders once armed (rather than a
    synthetic stand-in), closing the loop that the template's shape
    really does carry the attribute app.js's selector reads."""

    def test_armed_flow_survives_the_refresh_push(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div id=\"t-commit-drift\" class=\"action-bar\" data-armed=\"true\">"
            "<p class=\"error-strip\" role=\"alert\">route failed</p>"
            "<form><p class=\"commit-drift-armed\">Commit repo (1 file(s)): "
            "SKILL.md</p><button data-key-action=\"commit_drift_confirm\">"
            "Confirm</button></form></div>')"
        )
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)  # leg (c) holds the armed guided-commit bar

        # Confirm/second-refusal always re-renders the WHOLE #dom_id
        # element unarmed (never a partial patch) — simulate that swap,
        # then a settle re-checks the predicate and releases.
        page.evaluate(
            'document.getElementById("t-commit-drift").setAttribute("data-armed", "false")'
        )
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/commit-drift/confirm")
        _assert_reloaded(page)


class TestErrorStripSurvivesInFlightRefresh:
    """Live DoD defect (f5-errstrip): dirty SKILL.md + route confirm on a
    real record → the verb refused correctly, the response carried the
    error strip + the commit-drift button — and the post-verb refresh
    push (routes.py's ``_force_refresh``, fired BEFORE the failure
    response is even built) reloaded the page before the human could
    read/act, wiping both. Root cause: leg (a) keys on
    ``[data-verb-error]``, which ``action_bar.html``'s error strip never
    carried (only ``host_add_bar.html``'s did) — every failed-verb error
    on the Detail/Bucket action bar has been reload-wiped live;
    FakeRunner tests never push the post-subprocess refresh, so the
    existing suite never saw it (this module's own real uvicorn +
    real SSE push is what finally can).

    Models the EXACT ordering ``TestReloadRaceLiveOrdering`` established
    for leg (d): the refresh isn't a discrete "before" or "after" the
    response, it can arrive WHILE the confirm is in flight and be
    released at the SAME settle instant the error markup lands — so the
    assertion that matters is what ``releaseReload()`` sees AT that
    settle, not merely "eventually stays put"."""

    def test_confirm_failure_error_and_button_survive_inflight_refresh(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        # The pre-confirm armed bar — same shape action_bar.html renders
        # while armed, about to POST .../action/confirm.
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div class=\"action-bar\" data-armed=\"true\" id=\"t-bar\"></div>')"
        )
        _dispatch_htmx(page, "htmx:beforeRequest", "/record/x/action/confirm")
        _arm_reload_sentinel(page)

        # The refresh races the response — pushed mid-flight, exactly as
        # RealRunner's post-subprocess refresh_callback (and routes.py's
        # explicit _force_refresh, called before result.ok is even
        # checked) do in production.
        server.push_refresh(f"record:{REC_BRIEF}")
        _assert_deferred(page)  # leg (b) holds — nothing armed/erroring yet

        # The confirm response arrives: a failed verb re-renders the
        # WHOLE action-bar unarmed, carrying the error strip AND (when
        # eligible) the commit-drift button — the REAL shape
        # action_bar.html emits post-fix.
        page.evaluate(
            "document.getElementById('t-bar').outerHTML = "
            "'<div class=\"action-bar\" data-armed=\"false\" id=\"t-bar\">"
            "<p class=\"error-strip\" role=\"alert\" data-verb-error=\"true\">"
            "compile target has unrelated uncommitted changes</p>"
            "<form><button data-key-action=\"commit_drift_arm\">Commit that "
            "repo\\'s changes, then retry</button></form></div>'"
        )
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/confirm")
        # THE ASSERTION: releaseReload()'s predicate re-check at the exact
        # instant leg (b) lets go must find leg (a) already holding — the
        # error strip AND the commit-drift button must still be showing,
        # unreloaded, and therefore actionable.
        _assert_deferred(page)
        assert page.query_selector("[data-verb-error]") is not None
        assert (
            page.query_selector('[data-key-action="commit_drift_arm"]')
            is not None
        )

        # Defer-never-drop, chained: dismiss/re-render removes the strip
        # (leg (a)'s pinned release) and a settle still fires the reload.
        page.evaluate("document.getElementById('t-bar').remove()")
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/arm")
        _assert_reloaded(page)


class TestReloadDeferLegD:
    """Leg (d), U-C3 (09 §11 Y-8): a [data-contradicts-offer] element
    defers — the post-route contradicts offer renders every edge UNARMED
    (leg (c) alone would not hold it), yet the same route confirm that
    swaps it in also fires the routine post-verb forced-refresh push.
    Without this leg, that refresh's reload() wipes the just-rendered
    offer before the human can arm a single edge — the exact hazard
    live-trial found (the offer never even rendering was the server-side
    half of the same defect; this is the client-side half a naive server
    fix alone would still leave open)."""

    def test_contradicts_offer_defers_then_fires_on_removal(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div data-contradicts-offer=\"true\" id=\"t-offer\">"
            "<div class=\"action-bar\" data-armed=\"false\"></div></div>')"
        )
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)  # leg (d) holds — even though nothing is armed

        # The offer's only pinned release is navigating away; simulate the
        # human having left this rendering (removed from the DOM) followed
        # by a settle, which re-checks the predicate and releases.
        page.evaluate("document.getElementById('t-offer').remove()")
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/arm")
        _assert_reloaded(page)


class TestReloadDeferLegE:
    """Leg (e), A2 §10.4(a): a [data-adopt-offer] element defers — same
    hazard as leg (d) (the post-route chezmoi-adopt offer also renders
    UNARMED first, so leg (c) alone would not hold it). Two releases,
    unlike (d): navigating away (mirrors (d) exactly), AND tapping "Not
    now", which wipes the `#adopt-offer-*` element client-side without
    any navigation (§10.2: no persisted declined-state) — both must
    release the hold."""

    def test_adopt_offer_defers_then_fires_on_removal(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div data-adopt-offer=\"true\" id=\"t-adopt-offer\">"
            "<div class=\"action-bar\" data-armed=\"false\"></div></div>')"
        )
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)  # leg (e) holds — even though nothing is armed

        # Navigating away (element gone) is one pinned release, same as (d).
        page.evaluate("document.getElementById('t-adopt-offer').remove()")
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/arm")
        _assert_reloaded(page)

    def test_adopt_offer_defers_then_fires_on_decline_swap(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """The non-navigation release: "Not now" swaps `#adopt-offer-*`'s
        outerHTML to empty (the dismiss route's real response shape) —
        the marker is gone without leaving the page, and that alone must
        release leg (e)."""
        _open(page, server, "/")
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div data-adopt-offer=\"true\" id=\"t-adopt-offer\">"
            "<div class=\"action-bar\" data-armed=\"false\"></div></div>')"
        )
        _arm_reload_sentinel(page)

        server.push_refresh("front")
        _assert_deferred(page)

        # Simulate the dismiss route's outerHTML swap to empty content —
        # the element (and its marker) disappears with no navigation.
        page.evaluate("document.getElementById('t-adopt-offer').outerHTML = ''")
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/adopt-offer/dismiss")
        _assert_reloaded(page)


class TestReloadDeferLegF:
    """Leg (f), resolution-evidence unit (spec §3.5's app.js extension of
    the Y-16 chokepoint): a [data-verb-success] element in the document
    defers a broadcast reload — the success-leg analog of leg (a)'s
    [data-verb-error]. Drives the REAL confirm route (FakeRunner-backed,
    but a real uvicorn + real app.js + real SSE push), not a synthetic
    stand-in — so the assertion also closes the loop that
    ``action_bar.html``'s evidence include really does emit the marker
    ``app.js``'s selector reads, the same "does the template actually
    carry the attribute" concern ``TestCommitDriftArmedSurvivesRefresh``
    raised for its own new sub-state above.

    This is precisely the gap the spec's persistence test-plan bullet
    names: ``action_bar.html``'s own comment records that "FakeRunner
    tests never push the post-subprocess refresh, so this was invisible
    to the suite" — the exact mechanism that shipped the U14 error-strip
    wipe bug at this same file. The FakeRunner-driven TestClient tests in
    ``test_resolution_evidence.py`` prove the marker renders; only a real
    uvicorn + real app.js + a real pushed refresh can prove it survives
    one."""

    def test_verb_success_defers_then_fires_on_navigation(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, f"/record/{REC_BRIEF}")
        envelope = {
            "action": "reject",
            "record_id": REC_BRIEF,
            "canon_path": None,
            "host_commit_sha": None,
            "ledger_paths": [f"skills/s/resolved/{REC_BRIEF}.md"],
            "commit_message": f"self-learn: reject {REC_BRIEF}",
            "destination": None,
            "variant": None,
            "deferred_until": None,
            "warnings": [],
            "created": None,
            "outcome_state": "landed",
            "over_cap": None,
            "pushed": "pushed",
            "host_pushed": None,
        }
        server.runner.queue_result(RunResult(0, stdout=json.dumps(envelope)))
        _arm_reload_sentinel(page)

        # The real "x" path (TestNeverPressedKeymapActions pins "x" arms
        # reject on this exact record) to arm, then a Locator click to
        # confirm — Locator.click() auto-waits for the swapped-in button
        # to be attached/stable/actionable (F2's own established pattern,
        # e.g. test_14_submitter_carries_disabled), unlike a raw
        # `keyboard.press("Enter")` immediately after the arm swap, which
        # measurably races htmx's post-swap processing under full-suite
        # load and falls through to a native (non-htmx) form GET. Still a
        # genuine confirm POST/response/swap cycle through the production
        # route, not a synthetic stand-in.
        page.keyboard.press("x")
        page.wait_for_selector(f'#action-bar-{REC_BRIEF}[data-armed="true"]')
        page.locator('[data-key-action="confirm"]').click()
        page.wait_for_selector("[data-verb-success]")
        assert f"skills/s/resolved/{REC_BRIEF}.md" in page.content()

        # THE ASSERTION: a refresh pushed AFTER the success leg has
        # already settled into the DOM — leg (b)'s in-flight hold
        # released at that same settle, so it cannot be masking this —
        # must still be deferred. Before this unit's app.js change,
        # nothing held it, and this exact push would have reloaded the
        # page, wiping the just-rendered evidence before a human could
        # read it.
        server.push_refresh(f"record:{REC_BRIEF}")
        _assert_deferred(page)  # leg (f) holds

        # Defer-never-drop: the leg's only pinned release is navigating
        # away (§3.5 — no dismiss route exists for it). Simulate that,
        # then a settle re-checks the predicate and releases.
        page.evaluate('document.querySelector("[data-verb-success]").remove()')
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/arm")
        _assert_reloaded(page)


class TestSuccessFooterNeverAdvertisesADeadKey:
    """Code-gate finding (MAJOR): the footer must never print a key the
    page has nothing to dispatch to.

    ``app.js`` dispatches ``[data-key-action="<action>"]`` globally, so a
    footer entry whose element is absent is a key a human is TOLD exists
    and that does nothing. This codebase has shipped that defect twice —
    ``c`` (three partials sharing one action, fixed 2026-07-25) and ``h``
    (printed on the header back-link, still open) — and §0 rule 6 of the
    spec named §3.6 as the place this unit would most likely make it
    three. It did: ``style.css`` gated the whole ``data-context="success"``
    group on the STRIP being present, while the three links inside it are
    INDIVIDUALLY conditional (``success_view`` renders only for ``defer``;
    ``success_next`` only when the bucket has another pending record). A
    route confirm therefore advertised ``v`` and ``j`` with neither bound.

    Asserted as the general invariant rather than per key, so a fourth
    success key added later cannot reintroduce it by omission. Only a
    real browser can decide this: it turns on COMPUTED display, which no
    template-string assertion can see (``test_static_assets.py`` only
    checks that the CSS selector text exists — which stayed true while
    the bug was live)."""

    def test_route_confirm_footer_advertises_only_keys_that_exist(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, f"/record/{REC_BRIEF}")
        envelope = {
            "action": "route",
            "record_id": REC_BRIEF,
            "canon_path": "/host/plugins/s-plugin/skills/s/SKILL.md",
            "host_commit_sha": "deadbeefcafe",
            "ledger_paths": [f"skills/s/resolved/{REC_BRIEF}.md"],
            "commit_message": f"self-learn: route {REC_BRIEF} → skill-md",
            "destination": "skill-md",
            "variant": None,
            "deferred_until": None,
            "warnings": [],
            "created": False,
            "outcome_state": "landed",
            "over_cap": None,
            "pushed": "pushed",
            "host_pushed": "pushed",
        }
        server.runner.queue_result(RunResult(0, stdout=json.dumps(envelope)))

        page.keyboard.press("e")
        page.wait_for_selector(f'#action-bar-{REC_BRIEF}[data-armed="true"]')
        page.locator('[data-key-action="confirm"]').click()
        page.wait_for_selector("[data-verb-success]")

        # ANCHOR, first: both assertions below iterate sets that can be
        # empty, and both pass vacuously when they are. Measured: forcing
        # a leg with zero links makes `dead == []` (nothing shown) AND
        # `unadvertised == []` (nothing to iterate) — the whole class goes
        # silently green together. No reachable state produces that today
        # (`bucket_url` comes from `locate_record`, which resolves records
        # out of `resolved/`; verified against the real CLI for all four
        # verbs), so this guards against FIXTURE DRIFT rather than a live
        # defect. Named no key on purpose: pinning `success_bucket` here
        # would defend only the keys that already have rules, which is the
        # blind spot this class was rewritten to remove.
        bound = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('[data-key-action^="success_"]')
            ).map((e) => e.getAttribute("data-key-action"))"""
        )
        assert bound, (
            "no success_* keys rendered at all — both assertions below are "
            "vacuous; the fixture stopped producing the state this test "
            "exists to check"
        )

        dead = page.evaluate(
            """() => {
                const out = [];
                document
                  .querySelectorAll('.keymap-footer-entry[data-context="success"]')
                  .forEach((e) => {
                    if (getComputedStyle(e).display === "none") return;
                    const action = e.getAttribute("data-action");
                    if (!document.querySelector('[data-key-action="' + action + '"]'))
                      out.push(action);
                  });
                return out;
            }"""
        )
        assert dead == [], (
            f"footer advertises {dead} with no element to dispatch to — the "
            "advertised-key-bound-to-nothing defect, third instance"
        )

        # The invariant above is HALF of the property, and on its own it
        # fails open: `.keymap-footer-entry` defaults to `display: none`,
        # so a key with no CSS rule is simply silent, and "every entry
        # shown has an element" is trivially true of silence. A footer
        # showing NOTHING passes it. So does a fourth success key added
        # with no rule — measured: bound, dispatchable, advertised to
        # nobody, full suite green.
        #
        # An earlier version pinned `success_bucket` by name here, which
        # only defended the keys that already had rules — the omission it
        # was supposed to catch was precisely the one it could not see.
        # Derived from the DOM instead, so it covers keys that do not
        # exist yet (lrn-ea833a5b: ask what the check reports when it
        # cannot see its target at all; if that equals "pass", it is
        # worthless).
        unadvertised = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('[data-key-action^="success_"]')
            ).map((e) => e.getAttribute("data-key-action"))
             .filter((action) => {
                const entry = document.querySelector(
                  '.keymap-footer-entry[data-action="' + action + '"]');
                return !entry || getComputedStyle(entry).display === "none";
             })"""
        )
        assert unadvertised == [], (
            f"{unadvertised} are bound on this page but not advertised in the "
            "footer — a key nobody is told about. Adding a success key means "
            "adding its per-key rule to style.css; this is the check that "
            "notices when you don't."
        )


class TestReloadRaceLiveOrdering:
    """fw32-offer-race (follow-up to U-C3): a LIVE DoD retrial still lost
    the offer after the leg-(d) fix merged — browser landed on
    ``/bucket/skill/ha-ops?notice=resolved-elsewhere`` (the Detail GET's
    own 303 "resolved elsewhere" redirect, proving a real
    ``window.location.reload()`` fired and re-requested ``/record/<id>``
    after the record had already resolved).

    Live-instrumented reproduction (console/SSE/htmx-lifecycle/Mutation-
    Observer logging against a REAL uvicorn server + REAL ``self-learn``
    CLI subprocess + real Chromium, both with and without the ledger
    file-watcher, both single- and double-Enter) FALSIFIED the original
    "applying-state swap" hypothesis — ``type: "applying"`` SSE frames
    are inert client-side (app.js's ``default:`` case ignores them
    entirely; verified by grep AND by the instrumented trace showing the
    armed bar is removed only by the CONFIRM response's own htmx swap,
    never by an "applying" frame). The REAL race, reproduced 100% of the
    time (4/4 runs, no file-watcher even needed) by deleting JUST leg
    (d) from app.js and 0/11 times with leg (d) present: the routine
    post-route ``_force_refresh(f"record:{id}")`` push (routes.py) can
    arrive and be RELEASED (leg (b)'s ``confirmInFlight`` clears at
    ``htmx:afterSettle``) at effectively the SAME instant the offer's
    own swap completes — leg (b) alone only defers a refresh that
    arrives BEFORE settle; the human never gets a chance to arm a
    single edge unless something ALSO holds AT and AFTER that exact
    settle instant. This models that precise ordering: an armed bar is
    live, `htmx:beforeRequest` fires (leg (b) engages), a refresh
    arrives WHILE still in flight (deferred by leg (b) — the offer does
    not exist yet, so leg (d) cannot help at this instant), THEN the
    confirm's own swap replaces the armed bar with the unarmed
    contradicts offer and `htmx:afterSettle` fires (clearing leg (b)
    and triggering releaseReload()'s predicate re-check) — asserting
    the page does NOT reload at that release point (leg (d) now holds),
    then confirming defer-never-drop still eventually fires once the
    offer is actually gone."""

    def test_inflight_refresh_then_offer_settles_never_reloads(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        # The pre-confirm armed bar (kind=detail, verb=route) — same
        # shape action_bar.html renders while armed.
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div class=\"action-bar\" data-armed=\"true\" id=\"t-bar\"></div>')"
        )
        _dispatch_htmx(page, "htmx:beforeRequest", "/record/x/action/confirm")
        _arm_reload_sentinel(page)

        # The refresh that races the response — pushed while the confirm
        # is still in flight, exactly as RealRunner's own post-subprocess
        # refresh_callback (and routes.py's explicit _force_refresh) do
        # before the handler has even finished building the response.
        server.push_refresh(f"record:{REC_BRIEF}")
        _assert_deferred(page)  # leg (b) holds — offer doesn't exist yet

        # The confirm response arrives and htmx swaps: the armed bar is
        # replaced by the (unarmed) contradicts offer.
        page.evaluate(
            "document.getElementById('t-bar').outerHTML = "
            "'<div class=\"contradicts-offer\" data-contradicts-offer=\"true\" id=\"t-offer\">"
            "<div class=\"action-bar\" data-armed=\"false\"></div></div>'"
        )
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/confirm")
        # THE ASSERTION: releaseReload()'s predicate re-check at the exact
        # instant leg (b) lets go must find leg (d) already holding — the
        # offer must still be showing, unreloaded.
        _assert_deferred(page)

        # Defer-never-drop, chained: once the offer is genuinely gone, a
        # settle still releases the pending reload.
        page.evaluate("document.getElementById('t-offer').remove()")
        _dispatch_htmx(page, "htmx:afterSettle", "/record/x/action/arm")
        _assert_reloaded(page)


class TestReloadFiresWhenClear:
    """Control: with NO leg holding, a refresh reloads immediately — proves
    the defer tests above are detecting a real, otherwise-absent reload."""

    def test_refresh_reloads_when_no_leg_holds(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        _arm_reload_sentinel(page)
        server.push_refresh("front")
        _assert_reloaded(page)


# ============================================================= item 2:
# focus management — ensureRowSelected / ensureContentFocus + negatives.


class TestFocusManagement:
    def test_first_row_auto_selected_on_load(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        assert _selected_index(page) == 0
        # exactly one selection
        assert page.evaluate(
            "document.querySelectorAll('#self-learn-ui-content [data-row].selected').length"
        ) == 1

    def test_content_focused_on_load(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        assert page.evaluate("document.activeElement && document.activeElement.id") == (
            "self-learn-ui-content"
        )

    def test_focus_not_stolen_from_pane_input(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """ensureContentFocus must never yank focus off a live pane send
        input. Registered at document-start (before app.js's own
        DOMContentLoaded handler), we focus a pane-shaped input so that
        when ensureContentFocus runs, the active element is legitimately
        NOT body/html — the guard must leave it alone."""
        self._assert_focus_preserved(
            page,
            server,
            '<form id="pane-input-form"><input name="text" id="probe"></form>',
        )

    def test_focus_not_stolen_from_armed_bar_input(
        self, page: "Page", server: ServerHandle
    ) -> None:
        self._assert_focus_preserved(
            page,
            server,
            '<div class="action-bar" data-armed="true"><input name="note" id="probe"></div>',
        )

    @staticmethod
    def _assert_focus_preserved(
        page: "Page", server: ServerHandle, markup: str
    ) -> None:
        # Runs at document-start on every navigation, BEFORE app.js. It
        # registers a DOMContentLoaded listener earlier than app.js's, so
        # it focuses the probe input first; app.js's ensureContentFocus
        # then sees a non-body/html active element and must not steal it.
        page.add_init_script(
            """
            document.addEventListener('DOMContentLoaded', function () {
                const content = document.getElementById('self-learn-ui-content');
                if (!content) return;
                content.insertAdjacentHTML('beforeend', %r);
                document.getElementById('probe').focus();
            });
            """
            % markup
        )
        _open(page, server, "/")
        assert page.evaluate("document.activeElement && document.activeElement.id") == "probe"


# ============================================================= item 3:
# key dispatch — the data-key-action / clickAction table agrees with
# keymap.py, against the real served DOM.


class TestKeyDispatch:
    def test_served_keymap_blob_matches_source(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """The one source of truth: the JSON blob app.js parses is exactly
        keymap.py's table (covers navigation, y=arm_proposal, Enter/d=
        drill_in, b=toggle_brief, Escape=up — every binding at once)."""
        _open(page, server, "/")
        blob = page.evaluate(
            "JSON.parse(document.getElementById('self-learn-ui-keymap').textContent)"
        )
        assert blob == keymap_as_dicts()

    def test_navigation_keys_move_selection(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        assert _selected_index(page) == 0
        page.keyboard.press("s")  # move_down
        assert _selected_index(page) == 1
        page.keyboard.press("w")  # move_up
        assert _selected_index(page) == 0

    def test_drill_in_opens_selected_row(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        href = page.evaluate(
            "document.querySelector('#self-learn-ui-content [data-row].selected a[href]')"
            ".getAttribute('href')"
        )
        page.keyboard.press("d")  # drill_in
        page.wait_for_url(f"{server.base_url}{href}")

    def test_b_toggles_episode_brief(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, f"/record/{REC_BRIEF}")
        assert page.evaluate("document.querySelector('details.episode-brief').open") is False
        page.keyboard.press("b")  # toggle_brief -> clicks <summary data-key-action=toggle_brief>
        assert page.evaluate("document.querySelector('details.episode-brief').open") is True

    def test_b_scrolls_the_toggled_brief_into_view(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """UI-walk defect fix: `b` toggled real DOM state (the test
        above) but gave a scrolled-away human nothing ON SCREEN — a
        cold-open walker reported it as a dead key. Reproduced with a
        short viewport scrolled to the page bottom: the toggled
        `<details>` landed with a fully negative `top` (entirely above
        the viewport) and an identical before/after screenshot.
        `clickAction` now scrolls its target into view (`block:
        "nearest"`) after clicking — positive control first: start
        scrolled away with the target confirmed off-screen, so the
        assertion below can't pass by accident (the element already
        being in view)."""
        _open(page, server, f"/record/{REC_BRIEF}")
        page.set_viewport_size({"width": 1280, "height": 300})
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        before = page.evaluate(
            "document.querySelector('details.episode-brief').getBoundingClientRect().top"
        )
        assert before < 0  # positive control: confirmed off-screen before the fix applies

        page.keyboard.press("b")

        rect = page.evaluate(
            "JSON.stringify(document.querySelector('details.episode-brief').getBoundingClientRect())"
        )
        import json as _json

        r = _json.loads(rect)
        viewport_height = page.evaluate("window.innerHeight")
        # "in view" per scrollIntoView's own "nearest" contract: some part
        # of the element's box intersects [0, viewport_height].
        assert r["bottom"] > 0
        assert r["top"] < viewport_height

    def test_escape_first_rung_interrupts_pane_before_up(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """Esc ladder first rung: with a pane in an interruptible state,
        Escape clicks [data-key-action=interrupt] and does NOT fall through
        to `up` navigation (goUp's interrupt-first branch)."""
        _open(page, server, f"/record/{REC_BRIEF}")
        # An interruptible pane region + an interrupt target. The target is
        # an anchor to a hash (not an inline onclick — the page CSP
        # script-src 'self' blocks inline handlers), so clickAction's
        # el.click() leaves an observable, non-navigating hash change.
        page.evaluate(
            """() => {
                document.body.insertAdjacentHTML('beforeend',
                  '<div class="pane-region" data-pane-state="streaming">'
                  + '<a data-key-action="interrupt" href="#interrupted">stop</a></div>');
            }"""
        )
        page.keyboard.press("Escape")
        page.wait_for_function("location.hash === '#interrupted'")
        # interrupt fired first: still on the record, never followed `up`.
        assert f"/record/{REC_BRIEF}" in page.url

    def test_escape_navigates_up_when_no_pane(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """Second rung: no interruptible pane -> Escape clicks the served
        [data-key-action=up] link (Escape==up binding)."""
        _open(page, server, f"/record/{REC_BRIEF}")
        up_href = page.evaluate(
            "document.querySelector('[data-key-action=\"up\"]').getAttribute('href')"
        )
        page.keyboard.press("Escape")
        page.wait_for_url(f"{server.base_url}{up_href}")

    def test_y_arms_waiting_proposal(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """`y` -> arm_proposal clicks the served WAITING bar's arm button;
        the real /proposal/arm POST flips the slot to armed."""
        server.occupy_proposal(_proposal(REC_PROP))
        _open(page, server, f"/record/{REC_PROP}")
        assert page.get_attribute("#proposal-bar", "data-armed") == "false"
        page.keyboard.press("y")
        page.wait_for_selector('#proposal-bar[data-armed="true"]')

    def test_enter_confirms_armed_proposal(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """Armed-bar branch: Enter -> clickAction('confirm') fires the
        served confirm form's POST."""
        server.occupy_proposal(_proposal(REC_PROP, armed=True))
        _open(page, server, f"/record/{REC_PROP}")
        assert page.get_attribute("#proposal-bar", "data-armed") == "true"
        with page.expect_request(lambda r: r.url.endswith("/proposal/confirm")):
            page.keyboard.press("Enter")

    def test_other_key_disarms_armed_proposal(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """Armed-bar branch: any non-Enter key -> clickAction('disarm')
        fires the served disarm form's POST."""
        server.occupy_proposal(_proposal(REC_PROP, armed=True))
        _open(page, server, f"/record/{REC_PROP}")
        with page.expect_request(lambda r: r.url.endswith("/proposal/disarm")):
            page.keyboard.press("z")


# ============================================================= item 5:
# F5-3 (feedback round 5, U19 §1.1) — help-overlay key containment. The
# severest reported item: an open overlay let Escape fall through to
# goUp() -> clickAction("interrupt"), silently cancelling a running
# Iterate. Pinned negative: overlay open + Escape -> overlay closes AND
# no interrupt fires.


class TestHelpOverlayContainment:
    def test_escape_closes_overlay_and_does_not_interrupt_inflight_pane(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, f"/record/{REC_BRIEF}")
        # The exact reported disaster: a pane turn plausibly in flight
        # (same synthetic shape as the Esc-ladder test above) while the
        # overlay is open.
        page.evaluate(
            """() => {
                document.body.insertAdjacentHTML('beforeend',
                  '<div class="pane-region" data-pane-state="streaming">'
                  + '<a data-key-action="interrupt" href="#interrupted">stop</a></div>');
            }"""
        )
        page.keyboard.press("?")
        page.wait_for_selector("#self-learn-ui-help:not([hidden])")
        page.keyboard.press("Escape")
        assert page.evaluate("document.getElementById('self-learn-ui-help').hidden") is True
        time.sleep(0.2)  # the interrupt link, if clicked, changes the hash synchronously
        assert page.evaluate("location.hash") == ""

    def test_s_closes_overlay_and_leaves_selection_unmoved(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        before = _selected_index(page)
        page.keyboard.press("?")
        page.wait_for_selector("#self-learn-ui-help:not([hidden])")
        page.keyboard.press("s")  # would move_down if it reached KEYMAP dispatch
        assert page.evaluate("document.getElementById('self-learn-ui-help').hidden") is True
        assert _selected_index(page) == before

    def test_question_mark_still_toggles_open_and_closed(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        assert page.evaluate("document.getElementById('self-learn-ui-help').hidden") is True
        page.keyboard.press("?")
        assert page.evaluate("document.getElementById('self-learn-ui-help').hidden") is False
        page.keyboard.press("?")
        assert page.evaluate("document.getElementById('self-learn-ui-help').hidden") is True

    def test_keypress_in_focused_input_reaches_input_overlay_stays_open(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """n11 ordering: the text-input guard runs BEFORE the dismiss
        check — a focused input keeps receiving keys, and an
        independently-opened overlay is left exactly as it was."""
        _open(page, server, "/")
        page.keyboard.press("?")
        page.wait_for_selector("#self-learn-ui-help:not([hidden])")
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<input id=\"probe\" type=\"text\">')"
        )
        page.focus("#probe")
        page.keyboard.press("s")
        assert page.input_value("#probe") == "s"
        assert page.evaluate("document.getElementById('self-learn-ui-help').hidden") is False


# ============================================================= item 6:
# F5-1/F5-2 (feedback round 5, U19 §1.2) — silent no-op key feedback.
# Uses noop_page/noop_server (REC_USER, REC_NOOP_MULTI) — see the fixture
# block above for why this needed its own ledger.


class TestNoopKeyHints:
    def test_o_on_user_scope_shows_scope_hint_dest_unchanged(
        self, noop_page: "Page", noop_server: ServerHandle
    ) -> None:
        _open(noop_page, noop_server, f"/record/{REC_USER}")
        before = noop_page.text_content(f"#action-bar-{REC_USER}")
        noop_page.keyboard.press("o")
        hint = noop_page.wait_for_selector("[data-noop-hint-active]")
        assert hint.text_content() == "only one destination fits this lesson's scope"
        after = noop_page.text_content(f"#action-bar-{REC_USER}")
        assert before == after  # the destination text itself never changed

    def test_o_on_proposal_replaced_bar_shows_no_hint(
        self, noop_page: "Page", noop_server: ServerHandle
    ) -> None:
        noop_server.occupy_proposal(_proposal(REC_NOOP_MULTI))
        _open(noop_page, noop_server, f"/record/{REC_NOOP_MULTI}")
        noop_page.wait_for_selector("#proposal-bar")
        assert noop_page.query_selector('[data-key-action="cycle_destination"]') is None
        noop_page.keyboard.press("o")
        time.sleep(0.3)
        assert noop_page.query_selector("[data-noop-hint-active]") is None

    def test_b_on_briefless_record_shows_brief_hint(
        self, noop_page: "Page", noop_server: ServerHandle
    ) -> None:
        _open(noop_page, noop_server, f"/record/{REC_NOOP_MULTI}")
        assert noop_page.query_selector("details.episode-brief") is None
        noop_page.keyboard.press("b")
        hint = noop_page.wait_for_selector("[data-noop-hint-active]")
        assert hint.text_content() == "no episode brief on this record"

    def test_hint_clears_on_next_keypress(
        self, noop_page: "Page", noop_server: ServerHandle
    ) -> None:
        _open(noop_page, noop_server, f"/record/{REC_NOOP_MULTI}")
        noop_page.keyboard.press("b")
        noop_page.wait_for_selector("[data-noop-hint-active]")
        noop_page.keyboard.press("w")  # any unrelated key
        assert noop_page.query_selector("[data-noop-hint-active]") is None

    def test_b_hint_scrolls_into_view_when_scrolled_away(
        self, noop_page: "Page", noop_server: ServerHandle
    ) -> None:
        """UI-walk defect fix, same root cause as the toggle case above:
        `showNoopHint` always PREPENDS to `#self-learn-ui-content`, so a
        human scrolled away from the top never saw it — this is the
        MORE common of the two `b` repros, since most records carry no
        episode brief at all. Reproduced with a short viewport scrolled
        to the bottom: the inserted hint's `getBoundingClientRect().top`
        landed negative. Positive control first."""
        _open(noop_page, noop_server, f"/record/{REC_NOOP_MULTI}")
        noop_page.set_viewport_size({"width": 1280, "height": 300})
        noop_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        scroll_y_before = noop_page.evaluate("window.scrollY")
        assert scroll_y_before > 0  # positive control: genuinely scrolled away

        noop_page.keyboard.press("b")

        hint = noop_page.wait_for_selector("[data-noop-hint-active]")
        assert hint.text_content() == "no episode brief on this record"
        rect = hint.bounding_box()
        viewport_height = noop_page.evaluate("window.innerHeight")
        assert rect is not None
        assert rect["y"] + rect["height"] > 0
        assert rect["y"] < viewport_height

    def test_no_hint_when_a_bar_is_armed_and_o_is_pressed(
        self, noop_page: "Page", noop_server: ServerHandle
    ) -> None:
        _open(noop_page, noop_server, f"/record/{REC_NOOP_MULTI}")
        noop_page.keyboard.press("e")  # route -> arms the bar
        noop_page.wait_for_selector(f'#action-bar-{REC_NOOP_MULTI}[data-armed="true"]')
        noop_page.keyboard.press("o")  # armed branch: disarms, never dispatches
        time.sleep(0.3)
        assert noop_page.query_selector("[data-noop-hint-active]") is None


# ============================================================= item 7:
# UI in-flight feedback spec — the applying/bulk-progress strip (§4.1-
# §4.3/§5.1), F1's client-rendering half (13 tests: 1-10, 8b, 9b, 10b).
# All driven against the SHARED `server`/`page` fixture via
# `push_applying`/`push_bulk_progress` (§5.7, `publish_nowait` — see
# ServerHandle above for why `publish` alone would silently publish
# nothing from a foreign thread).


class TestApplyingStripClientRendering:
    def test_1_strip_not_visible_on_load(self, page: "Page", server: ServerHandle) -> None:
        _open(page, server, "/")
        expect(_applying_strip(page)).to_be_hidden()

    def test_2_applying_start_renders_visible_with_badge_and_detail(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        before = page.locator("body").aria_snapshot()
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "applying"
        assert (
            page.locator("#self-learn-ui-applying-text").text_content()
            == f"route → {REC_BRIEF}"
        )
        after = page.locator("body").aria_snapshot()
        assert after != before

    def test_2b_force_run_applying_renders_visible_with_badge_and_detail(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """UI-walk defect fix: "Force run" (worker kick / miner run) now
        publishes through this SAME mechanism (routes.py's worker_kick /
        mine_run, `_publish_applying`) — this is the client-rendering
        half of that fix, same oracle as test_2 above (aria_snapshot
        inequality; text_content is blind to opacity, which is why the
        inequality check rides alongside it here too, per S-20's own
        measured blind spot)."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        before = page.locator("body").aria_snapshot()
        server.push_applying("worker", "kick", "start")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "applying"
        assert page.locator("#self-learn-ui-applying-text").text_content() == "worker → kick"
        after = page.locator("body").aria_snapshot()
        assert after != before
        server.push_applying("worker", "kick", "done")
        expect(strip).to_be_hidden()

    def test_3_applying_done_hides_strip(self, page: "Page", server: ServerHandle) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        server.push_applying("route", REC_BRIEF, "done")
        expect(strip).to_be_hidden()

    def test_4_applying_error_shows_failed_strip(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """FW-76 §1.3/F: this test used to pin the DEFECT (a failed
        Force run rendered identically to a succeeded one — strip
        appears, strip disappears either way). It now pins the FIX:
        `error` renders a distinct, persistent failed strip. Do not
        "restore" the old hides-the-strip assertion — that is the bug
        this unit exists to remove (spec §1.1)."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        server.push_applying("route", REC_BRIEF, "error")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "failed"
        assert (
            page.locator("#self-learn-ui-applying-text").text_content()
            == f"route → {REC_BRIEF}"
        )

    def test_5_bulk_progress_renders_done_plus_one_of_total(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        before = page.locator("body").aria_snapshot()
        server.push_bulk_progress(0, 3)
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-text").text_content() == "1 of 3"
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "graduating"
        after = page.locator("body").aria_snapshot()
        assert after != before

    def test_6_bulk_terminal_hides_strip_after_showing_it_first(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """R3-M3: a terminal on an empty Map is a no-op, so the strip
        must be shown FIRST — a test that skips the show step would
        assert "hidden" on a strip that was never visible."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_bulk_progress(0, 1)
        expect(strip).to_be_visible()
        server.push_bulk_progress(1, 1)  # terminal: done == total
        expect(strip).to_be_hidden()

    def test_7_unknown_envelope_ignored_and_no_pageerror(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """A bare "nothing happened" assertion stays green when the
        handler throws (the throw escapes to window.onerror, leaving the
        DOM untouched) — pageerror is the assertion that actually catches
        V-6 (a case that throws)."""
        _open(page, server, "/")
        errors: list = []
        page.on("pageerror", lambda exc: errors.append(exc))
        server.push_envelope({"type": "some-future-envelope-type", "junk": True})
        # `page.wait_for_timeout`, NEVER `time.sleep`. time.sleep does not
        # enter playwright-python's sync event dispatcher, so `errors` is
        # empty at assert time regardless of how long it sleeps — which makes
        # the pageerror assertion structurally dead and lets V-6 survive.
        # Measured by the code gate (2026-07-25): under V-6 this test passed
        # with time.sleep(0.3) AND with time.sleep(1.5) — so a longer sleep is
        # NOT the fix — while wait_for_timeout(300) fails it correctly.
        page.wait_for_timeout(300)
        expect(_applying_strip(page)).to_be_hidden()
        assert errors == [], f"unknown envelope type raised in the handler: {errors}"

    def test_8_two_distinct_starts_one_matching_done_stays_visible(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("route", REC_BRIEF, "start")
        server.push_applying("reject", REC_PROP, "start")
        expect(strip).to_be_visible()
        server.push_applying("route", REC_BRIEF, "done")
        expect(strip).to_be_visible()  # the OTHER entry still holds it
        # A done for a verb never started is a no-op — must not hide a
        # strip another entry owns.
        server.push_applying("defer", "lrn-dead0000", "done")
        expect(strip).to_be_visible()

    def test_8b_unmatched_done_against_live_bulk_stays_visible(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """R6-M1: an unmatched applying/done `delete`s a key that was
        never present — a no-op on the Map, so a live "bulk" entry is
        untouched and the strip keeps showing (and the bulk run keeps
        rendering subsequent progress)."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_bulk_progress(0, 3)
        expect(strip).to_be_visible()
        server.push_applying("route", "lrn-dead0001", "done")  # never started
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "graduating"
        server.push_bulk_progress(1, 3)
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-text").text_content() == "2 of 3"

    def test_9_bare_bulk_terminal_does_not_evict_applying_entry(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """R3-B2/V-10: a bulk terminal with no "bulk" key present (the
        empty-bulk case) must be a no-op, never touching an applying
        entry that still owns the strip."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        server.push_bulk_progress(0, 0)  # terminal, no "bulk" key ever set
        expect(strip).to_be_visible()
        assert (
            page.locator("#self-learn-ui-applying-text").text_content()
            == f"route → {REC_BRIEF}"
        )
        server.push_applying("route", REC_BRIEF, "done")
        expect(strip).to_be_hidden()

    def test_9b_bulk_terminal_after_real_progress_reverts_to_applying(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """R4-M1's class, retained under the Map as the direct regression
        test: the bulk genuinely opens (unlike test 9's bare terminal),
        and its terminal must revert the render to the applying label
        (R5-m1) rather than hold "graduating 3 of 3" for finished work."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        server.push_bulk_progress(0, 3)
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "graduating"
        server.push_bulk_progress(3, 3)  # terminal
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "applying"
        assert (
            page.locator("#self-learn-ui-applying-text").text_content()
            == f"route → {REC_BRIEF}"
        )
        server.push_applying("route", REC_BRIEF, "done")
        expect(strip).to_be_hidden()

    def test_10_connection_loss_clears_map_and_hides_strip(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """Seam note: spec §6 test 10 names ``BrowserContext.set_offline``
        as the seam; empirically that call does not sever an
        already-open EventSource in this environment (see
        ``_wrap_event_source``'s docstring for the four measurements).
        Substituted here with a direct ``error`` Event dispatched at the
        captured EventSource instance, which drives the SAME production
        ``source.onerror`` handler app.js registers — no production code
        changed, and the assertions below are unchanged from the spec's
        intent (strip hides, reconnect strip shows)."""
        _wrap_event_source(page)
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        _simulate_sse_error(page)
        expect(strip).to_be_hidden()
        expect(page.locator("#self-learn-ui-reconnect-strip")).to_be_visible()

    def test_10b_stale_entry_does_not_survive_reconnect(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """R5-M1, retargeted R7: the observable consequence of a stale
        entry under the Map is that it WINS the render over a later
        applying entry (a fresh bulk's own progress frame would overwrite
        a stale bulk entry by construction — immune by construction). Open
        a bulk, simulate connection loss before its terminal, then push
        an applying/start: the strip must render "applying", not a stale
        "graduating".

        Seam note: same substitution as test 10 (``_simulate_sse_error``
        instead of ``set_offline`` — see that test's docstring and
        ``_wrap_event_source``). One consequence: because the socket was
        never actually severed at the network level (only ``onerror`` was
        invoked directly), the client stays subscribed throughout — no
        reconnect wait or resubscription dance is needed before the
        follow-up push."""
        _wrap_event_source(page)
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_bulk_progress(0, 3)
        expect(strip).to_be_visible()
        _simulate_sse_error(page)
        expect(strip).to_be_hidden()  # cleared on the simulated loss
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "applying"
        assert (
            page.locator("#self-learn-ui-applying-text").text_content()
            == f"route → {REC_BRIEF}"
        )

    # ------------------------------------------------------------ FW-76
    # §2.1/§3: a failed Force run must render differently from a
    # succeeded one (B), must survive a broadcast refresh (C), must
    # never be masked by live work without the marker outliving that
    # render (D), unmatched-error hygiene (E). All criteria drive
    # server.push_applying/server.push_refresh only, per §3's own rule
    # (no `.click()` — the 14 environmental failures are all
    # Locator.click actionability timeouts on this host); B4 alone also
    # uses page.set_viewport_size + a page.evaluate scroll, the SAME
    # pair test_b_scrolls_the_toggled_brief_into_view (:1372) already
    # uses this way.

    def test_b1_error_renders_failed_badge_and_detail(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "start")
        expect(strip).to_be_visible()
        server.push_applying("worker", "kick", "error")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "failed"
        assert page.locator("#self-learn-ui-applying-text").text_content() == "worker → kick"

    def test_b2_terminal_snapshots_differ_error_vs_done(
        self, page: "Page", server: ServerHandle, browser: "Browser"
    ) -> None:
        """B2 — a DISCRIMINATING snapshot comparison. NOT
        applying-vs-error (that pair already differs on master — the
        strip merely disappearing changes the body snapshot). Compares
        instead the two TERMINAL states at the SAME key from the SAME
        start: two independent pages (so each terminal is reached from
        an identical prior state, never a comparison against a page
        whose Map was mutated by the other arm first) each push `start`
        then diverge to `error`/`done`."""
        _open(page, server, "/")
        server.push_applying("worker", "kick", "start")
        expect(_applying_strip(page)).to_be_visible()
        server.push_applying("worker", "kick", "error")
        error_snapshot = page.locator("body").aria_snapshot()

        context2 = browser.new_context()
        page2 = context2.new_page()
        try:
            _open(page2, server, "/")
            # `_open`'s own wait_for_subscriber(1) is already satisfied by
            # `page`'s still-open connection above, so it can return
            # before page2's OWN /events stream is actually live — wait
            # for the SECOND subscriber explicitly before pushing, or the
            # frame below can race page2's EventSource connect.
            server.wait_for_subscriber(2)
            server.push_applying("worker", "kick", "start")
            expect(_applying_strip(page2)).to_be_visible()
            server.push_applying("worker", "kick", "done")
            done_snapshot = page2.locator("body").aria_snapshot()
        finally:
            context2.close()

        assert error_snapshot != done_snapshot

    def test_b3_marker_and_role_both_present_on_the_failed_render(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """B3 — here the rendered entry IS the failed one, so the two
        keyings (data-verb-error Map-scoped, role=alert render-scoped)
        coincide; D3 is where they must not."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "start")
        expect(strip).to_be_visible()
        server.push_applying("worker", "kick", "error")
        expect(strip).to_have_attribute("data-verb-error", "true")
        expect(strip).to_have_attribute("role", "alert")

    def test_b4_failure_is_scrolled_into_view(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """B4 — the failure is where the human is looking. Copies
        test_b_scrolls_the_toggled_brief_into_view's (:1372) two
        structural moves: (1) a short viewport so the page genuinely
        scrolls — without it the front page may not overflow the
        default viewport, scrollTo is a no-op, and the top-of-body strip
        is already in view; (2) a positive control asserted BEFORE the
        fix can fire — `start` never sets [data-verb-error] (§2.1's
        scrollIntoView fires only on the marker's absent->present
        transition), so the strip is legitimately off-screen here, and
        the assertion below can't pass by accident. to_be_visible() is
        deliberately NOT the oracle for the second assertion: a
        non-empty box does not imply viewport intersection, which is
        exactly how this defect class hides."""
        _open(page, server, f"/record/{REC_BRIEF}")
        strip = _applying_strip(page)
        page.set_viewport_size({"width": 1280, "height": 300})
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        server.push_applying("worker", "kick", "start")
        expect(strip).to_be_visible()
        expect(strip).not_to_be_in_viewport()  # positive control

        server.push_applying("worker", "kick", "error")
        expect(strip).to_be_in_viewport()

    def test_c0_refresh_reloads_on_an_empty_map(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """C0 — positive control: without it C1 could pass on a harness
        whose refresh never arrives at all."""
        _open(page, server, "/")
        _arm_reload_sentinel(page)
        server.push_refresh("front")
        _assert_reloaded(page)

    def test_c1_failed_entry_defers_a_broadcast_refresh(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "start")
        server.push_applying("worker", "kick", "error")
        expect(strip).to_be_visible()
        _arm_reload_sentinel(page)
        server.push_refresh("front")
        _assert_deferred(page)
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "failed"

    def test_c2_done_for_the_failed_key_releases_the_deferred_reload(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "start")
        server.push_applying("worker", "kick", "error")
        expect(strip).to_be_visible()
        _arm_reload_sentinel(page)
        server.push_refresh("front")
        _assert_deferred(page)
        server.push_applying("worker", "kick", "done")
        expect(strip).to_be_hidden()
        _assert_reloaded(page)

    def test_d1_live_work_outranks_a_failure_notice(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "error")  # unseen key: creates a failed entry
        expect(strip).to_be_visible()
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "applying"
        assert (
            page.locator("#self-learn-ui-applying-text").text_content()
            == f"route → {REC_BRIEF}"
        )

    def test_d2_failure_resumes_rendering_once_live_work_completes(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """The failure was HELD, not dropped, while it was masked."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "error")
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        server.push_applying("route", REC_BRIEF, "done")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "failed"
        assert page.locator("#self-learn-ui-applying-text").text_content() == "worker → kick"

    def test_d3_marker_outlives_the_render_it_is_not_attached_to(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """D3 — the criterion that makes §2.1's Map-vs-render keying
        testable. A builder writing `if (rendered.failed)
        setAttribute(...)` would pass B, C and D1/D2 (B3's two keyings
        coincide there; C is scoped to a pure-failure Map) and only this
        fails."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "error")
        server.push_applying("route", REC_BRIEF, "start")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "applying"
        assert (
            page.locator("#self-learn-ui-applying-text").text_content()
            == f"route → {REC_BRIEF}"
        )
        # (i) the marker is present even though the render is the LIVE
        # entry, not the failed one — and the role does NOT follow it.
        expect(strip).to_have_attribute("data-verb-error", "true")
        expect(strip).not_to_have_attribute("role", "alert")

        # (ii) it still defers a broadcast refresh while masked.
        _arm_reload_sentinel(page)
        server.push_refresh("front")
        _assert_deferred(page)

        # (iii) the failure survived, unmasked by the live work's own done.
        server.push_applying("route", REC_BRIEF, "done")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "failed"

    def test_e1_error_for_a_key_never_started_still_renders_failed(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """E1 — a real failure elsewhere is still a failure."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_applying("worker", "kick", "error")  # this page never saw "start"
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "failed"
        assert page.locator("#self-learn-ui-applying-text").text_content() == "worker → kick"

    def test_e2_error_does_not_displace_a_live_bulk_render_then_reverts(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """E2 — two arms. The bulk entry MUST be seeded first (an
        error-before-bulk fixture would let first-insertion-order-wins
        alone pass this, which is M6's mutation, not M11's — see the
        spec's own note on why this fixture order matters). The first
        assertion here is green on master too (master's `error` is a
        no-op `delete` on an absent key, so bulk keeps rendering there
        as well) — it is the TERMINAL step below that reddens on master
        (the Map goes empty once bulk clears there, hiding the strip
        instead of reverting to "failed")."""
        _open(page, server, "/")
        strip = _applying_strip(page)
        server.push_bulk_progress(0, 3)
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "graduating"
        server.push_applying("worker", "kick", "error")
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "graduating"
        server.push_bulk_progress(3, 3)  # bulk terminal
        expect(strip).to_be_visible()
        assert page.locator("#self-learn-ui-applying-badge").text_content() == "failed"
        assert page.locator("#self-learn-ui-applying-text").text_content() == "worker → kick"


# F1's server-publish half (3, js): real submissions, no page.route() —
# an in-page SSE frame recorder observes what the SERVER actually
# publishes (§4.5: synthetic seams alone would let a build delete every
# server publish and stay green).


class TestApplyingStripServerPublish:
    # MEASURED (2026-07-25): opening "/" (the Front page) for these tests
    # is unsafe — `_force_refresh` after a real confirm/bulk publishes a
    # "refresh" SSE frame that app.js's OWN (production) EventSource on
    # that page receives; `inScope()` treats a page whose own scope is
    # "front" as matching EVERY refresh scope (app.js: "the Front page
    # matches every scope"), so `reload()` fires for real and
    # `window.location.reload()` destroys the execution context —
    # wiping `window.__frames` out from under the recorder before the
    # assertion can run (confirmed via a standalone repro: the page
    # navigates and a subsequent `page.evaluate` raises "Execution
    # context was destroyed"). None of reload()'s five defer legs are
    # held, because these are raw `page.request.post` calls, not
    # htmx-driven submissions. Opening a detail page for an UNRELATED
    # record (REC_PROP — different id, different bucket) instead keeps
    # `currentScopes()` narrow (["record:<REC_PROP>"]), so the
    # `record:<REC_BRIEF>`/`bucket:s` refresh scopes these tests trigger
    # never match and no reload occurs — while the frame recorder's own,
    # separate `/events` connection still observes every frame regardless
    # of scope (scope filtering is client-side, in the production
    # EventSource's "refresh" case only; the recorder is a second, raw
    # subscriber with no such filter).
    def test_11_real_confirm_emits_applying_frame(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, f"/record/{REC_PROP}")
        _start_frame_recorder(page)
        server.wait_for_subscriber(2)
        resp = page.request.post(
            f"{server.base_url}/record/{REC_BRIEF}/action/confirm",
            form={"verb": "route", "kind": "detail"},
            headers={"HX-Request": "true"},
        )
        assert resp.ok
        page.wait_for_function(
            "id => window.__frames.some(f => f.type === 'applying' "
            "&& f.verb === 'route' && f.id === id)",
            arg=REC_BRIEF,
        )

    def test_12_real_bulk_emits_frame_for_item_one(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, f"/record/{REC_PROP}")
        _start_frame_recorder(page)
        server.wait_for_subscriber(2)
        resp = page.request.post(
            f"{server.base_url}/bucket/skill/s/graduate-bulk",
            form={"ids": REC_BRIEF},
            headers={"HX-Request": "true"},
        )
        assert resp.ok
        page.wait_for_function(
            "() => window.__frames.some(f => f.type === 'bulk_progress' && f.done === 0)"
        )

    def test_13_real_bulk_failure_emits_terminal_with_failed_id(
        self, page: "Page", server: ServerHandle
    ) -> None:
        """The path F5 showed was unreachable before §5.6's fix."""
        _open(page, server, f"/record/{REC_PROP}")
        _start_frame_recorder(page)
        server.wait_for_subscriber(2)
        server.runner.queue_result(RunResult(1, stderr="boom"))
        resp = page.request.post(
            f"{server.base_url}/bucket/skill/s/graduate-bulk",
            form={"ids": REC_BRIEF},
            headers={"HX-Request": "true"},
        )
        assert resp.ok  # the failed-bulk response is still a 200 (error_strip)
        page.wait_for_function(
            "id => window.__frames.some(f => f.type === 'bulk_progress' "
            "&& f.failed_id === id)",
            arg=REC_BRIEF,
        )


# F2 — in-flight disabling (8, js). hx-disabled-elt="find button" (§5.4)
# is the LOCAL cue (§4.2) — instant, per-tab, independent of the strip.
# POST held open via page.route() (§4.5: page.route() intercepts in the
# browser, so a held POST never reaches the handler — none of these
# tests touch the server's SSE publish path).


class TestNoteKeyOnAnArmedBar:
    """The armed strip advertises "n to say why" one line under "any other
    key cancels", and app.js honoured only the second: pressing the key
    the UI offered threw the pending action away, with no note and no
    message. Found in a UI walk — the walker followed the on-screen hint
    and lost the denial it was mid-way through, twice.

    `n` still disarms: the note input exists only on the unarmed bar, so
    there is nothing to focus while the confirm strip is up. What it must
    now do is leave the caret in that field once the plain bar swaps back,
    which is what the hint promises."""

    def test_n_does_not_destroy_the_pending_action(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="true"]')
        f2_page.keyboard.press("n")
        # The armed bar must SURVIVE — losing a half-made decision to the
        # key the UI itself offered is the defect. A no-op hint explains
        # the state instead.
        f2_page.wait_for_selector('[data-noop-hint-active="true"]')
        assert (
            f2_page.get_attribute(f"#action-bar-{REC_F2_PLAIN}", "data-armed") == "true"
        )

    def test_a_non_note_key_still_just_disarms(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        """Control: the fix must not turn EVERY cancel into a note focus.
        `z` disarms and leaves focus alone."""
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="true"]')
        f2_page.keyboard.press("z")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="false"]')
        f2_page.wait_for_selector('.action-bar input[name="note"]')
        focused_note = f2_page.evaluate(
            "() => { const n = document.querySelector("
            "'.action-bar input[name=\"note\"]'); "
            "return n !== null && document.activeElement === n; }"
        )
        assert focused_note is False


class TestQuestionMarkSwallowedByTextInputShowsHint:
    """`?` was silently swallowed by a focused text input — the SAME
    inert-while-typing rule the header contract documents (and keeps:
    ordinary typing must never trigger a global shortcut), but with zero
    feedback that the on-screen "?" for Help never fired. A UI walk hit
    this pressing `?` in the Note field, expecting the help overlay."""

    def test_question_mark_still_types_and_shows_a_hint(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        note = f2_page.locator('.action-bar input[name="note"]')
        note.click()
        f2_page.keyboard.press("?")
        # The character landed in the field exactly as typed — this
        # branch must NEVER preventDefault or otherwise steal it; that
        # would trade one silent defect for a worse one.
        assert note.input_value() == "?"
        # ...but the human is now told why Help didn't also open.
        f2_page.wait_for_selector('[data-noop-hint-active="true"]')
        assert f2_page.is_hidden("#self-learn-ui-help")

    def test_ordinary_note_typing_stays_silent(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        """Control (the method's own guardrail): the fix must not make
        ordinary note-taking noisy. Every letter typed here is ALSO a
        keymap-bound global shortcut (e/s/a/t/...) that stays silent —
        only `?` gets the hint, never the rest."""
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        note = f2_page.locator('.action-bar input[name="note"]')
        note.click()
        f2_page.keyboard.type("because it matters")
        assert note.input_value() == "because it matters"
        assert f2_page.query_selector('[data-noop-hint-active="true"]') is None


class TestInFlightDisabling:
    def test_14_submitter_carries_disabled(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="true"]')
        held = _hold_post(f2_page, "/action/confirm")
        f2_page.locator('[data-key-action="confirm"]').click()
        _wait_for_held(held)
        assert f2_page.locator('[data-key-action="confirm"]').get_attribute(
            "disabled"
        ) is not None
        held["route"].fulfill(status=200, content_type="text/html", body="<div>ok</div>")

    def test_15_aria_snapshot_differs_during_flight(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="true"]')
        before = f2_page.locator("body").aria_snapshot()
        held = _hold_post(f2_page, "/action/confirm")
        confirm = f2_page.locator('[data-key-action="confirm"]')
        confirm.click()
        _wait_for_held(held)
        expect(confirm).to_be_visible()
        after = f2_page.locator("body").aria_snapshot()
        assert after != before
        held["route"].fulfill(status=200, content_type="text/html", body="<div>ok</div>")

    def test_16_disabled_element_is_the_submitter_not_a_sibling(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        """The Disarm button is a DIFFERENT <form> in the same armed bar
        — hx-disabled-elt is placed only on the Confirm form's own
        `<form>`, so "find button" must never reach the Disarm button."""
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="true"]')
        held = _hold_post(f2_page, "/action/confirm")
        f2_page.locator('[data-key-action="confirm"]').click()
        _wait_for_held(held)
        assert f2_page.locator('[data-key-action="confirm"]').get_attribute(
            "disabled"
        ) is not None
        assert f2_page.locator('[data-key-action="disarm"]').get_attribute(
            "disabled"
        ) is None
        held["route"].fulfill(status=200, content_type="text/html", body="<div>ok</div>")

    def test_17_disabled_style_matches_css_rule(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="true"]')
        held = _hold_post(f2_page, "/action/confirm")
        confirm = f2_page.locator('[data-key-action="confirm"]')
        confirm.click()
        _wait_for_held(held)
        expect(confirm).to_have_css("opacity", "0.45")
        expect(confirm).to_have_css("cursor", "not-allowed")
        held["route"].fulfill(status=200, content_type="text/html", body="<div>ok</div>")

    def test_18_settle_action_bar_confirm_detaches(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        _open(f2_page, f2_server, f"/record/{REC_F2_PLAIN}")
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_PLAIN}[data-armed="true"]')
        handle = f2_page.query_selector('[data-key-action="confirm"]')
        held = _hold_post(f2_page, "/action/confirm")
        f2_page.locator('[data-key-action="confirm"]').click()
        _wait_for_held(held)
        held["route"].fulfill(
            status=200,
            content_type="text/html",
            body=f'<div id="action-bar-{REC_F2_PLAIN}" class="action-bar" data-armed="false"></div>',
        )
        # state="attached": the synthetic fulfill body is a contentless
        # div with no CSS-given height, so it has an empty bounding box
        # and never satisfies wait_for_selector's default "visible" wait
        # — the assertion under test is DOM presence/detachment, not
        # perceptibility, so "attached" is the correct wait here.
        f2_page.wait_for_selector(
            f'#action-bar-{REC_F2_PLAIN}[data-armed="false"]', state="attached"
        )
        assert f2_page.evaluate("el => !document.body.contains(el)", handle) is True

    def test_19_settle_commit_drift_confirm_detaches(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        _open(f2_page, f2_server, f"/record/{REC_F2_DRIFT}")
        # MEASURED (2026-07-25, full-suite runs only): calling
        # `page.evaluate` as the very FIRST action right after `_open()`
        # (rather than a `keyboard.press`/`wait_for_selector` round trip
        # first, as every sibling test in this class does) intermittently
        # raises Playwright's "Cannot find context with specified id" —
        # the page's own execution context is still settling immediately
        # post-navigation. Waiting for the button "o" is about to target
        # gives the same natural settle window the other tests get for
        # free from their leading keypress + wait_for_selector.
        f2_page.wait_for_selector(f'[data-key-action="cycle_destination"]')
        # REC_F2_DRIFT carries no seeded proposal (see _seed_f2_ledger's
        # comment) so `dest` starts empty; cycle it to "skill-md" first —
        # the ARM tap's real dry-run subprocess needs an explicit --dest
        # to find the dirtied skill_md (measured: without it, the dry
        # run reports nothing and the armed state never renders).
        # MEASURED: pressing "e" immediately after the cycle swap's DOM
        # content lands is a real race — htmx's post-swap processing
        # (which wires up the newly-swapped-in buttons' own hx-*
        # listeners) can trail the content update by a beat, so a
        # same-tick click finds the button but nothing listens yet (no
        # request, no error). Rather than a fixed sleep — flake-prone
        # under load, and this test's own arm step runs a REAL dry-run
        # subprocess — arm a one-shot listener for htmx's own
        # `htmx:afterSettle` BEFORE pressing "o", and wait on it: that
        # event fires as the last step of htmx's swap pipeline, after
        # processing (listener wiring) completes, so it is a
        # deterministic signal rather than a guessed delay. (A first
        # attempt used Playwright's `wait_for_function` for this poll;
        # MEASURED it throws — this app's CSP forbids the in-page
        # `Function()` construction `wait_for_function` compiles its
        # predicate with. `_wait_for_js_flag` polls from the Python side
        # instead, sidestepping that.)
        f2_page.evaluate(
            "window.__f2SettleO = false;"
            "document.body.addEventListener('htmx:afterSettle',"
            " () => { window.__f2SettleO = true; }, { once: true });"
        )
        f2_page.keyboard.press("o")
        _wait_for_js_flag(f2_page, "window.__f2SettleO === true")
        # Belt-and-braces: confirm the dest the arm tap actually needs is
        # the one that landed (the settle signal proves htmx is done, not
        # which dest string won the cycle).
        f2_page.wait_for_selector(
            f'#action-bar-{REC_F2_DRIFT} input[name="dest"][value="skill-md"]',
            state="attached",
        )
        f2_page.keyboard.press("e")
        f2_page.wait_for_selector(f'#action-bar-{REC_F2_DRIFT}[data-armed="true"]')
        # A REAL failed route confirm carrying the pinned dirty marker —
        # this round-trip is allowed to complete for real (the confirm
        # route never touches the pane manager / a real engine).
        f2_server.runner.queue_result(
            RunResult(
                1,
                stderr=f"self-learn route: compile target X {GITOPS_DIRTY_MARKER} present",
            )
        )
        f2_page.locator('[data-key-action="confirm"]').click()
        f2_page.wait_for_selector('[data-key-action="commit_drift_arm"]')
        f2_page.locator('[data-key-action="commit_drift_arm"]').click()
        f2_page.wait_for_selector('[data-key-action="commit_drift_confirm"]')
        handle = f2_page.query_selector('[data-key-action="commit_drift_confirm"]')
        held = _hold_post(f2_page, "/action/commit-drift/confirm")
        f2_page.locator('[data-key-action="commit_drift_confirm"]').click()
        _wait_for_held(held)
        # ROOT-CAUSED (2026-07-25): the earlier real "confirm" click above
        # (line ~1817) fails for real, and `action_confirm`'s failure
        # branch (routes.py ~1210) calls `_force_refresh(request,
        # f"record:{REC_F2_DRIFT}")` — a real SSE broadcast scoped to
        # THIS page's own record. app.js's reload chokepoint (Y-16, 09
        # §11) defers that reload on leg (a): a `[data-verb-error]`
        # element is in the document (the error-strip `partials/
        # action_bar.html` renders whenever `ctx["error"]` is set, which
        # both the route-confirm failure and commit-drift's own failure
        # branches do). A first version of this synthetic fulfill body
        # omitted that marker — the swap it drives removes the ONLY thing
        # holding leg (a), so the deferred reload releases and fires a
        # REAL `window.location.reload()` right as this test's own
        # assertions run, racing them (MEASURED: intermittently threw
        # Playwright's "Cannot find context with specified id" on the
        # final evaluate, reproducing in ~1/2 full-suite runs). Carrying
        # `data-verb-error` here is not a claim about what a real
        # SUCCESSFUL commit-drift confirm response looks like (it
        # wouldn't have this marker) — it exists solely to keep leg (a)
        # held so the reload this test's OWN earlier forced failure left
        # pending never fires mid-assertion.
        held["route"].fulfill(
            status=200,
            content_type="text/html",
            body=(
                f'<div id="action-bar-{REC_F2_DRIFT}" class="action-bar" '
                'data-armed="false" data-verb-error="true"></div>'
            ),
        )
        # state="attached" — see test_18's comment on the same pattern.
        f2_page.wait_for_selector(
            f'#action-bar-{REC_F2_DRIFT}[data-armed="false"]', state="attached"
        )
        assert f2_page.evaluate("el => !document.body.contains(el)", handle) is True

    def test_20_settle_proposal_confirm_detaches(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        f2_server.occupy_proposal(_proposal(REC_F2_PROP, armed=True))
        _open(f2_page, f2_server, f"/record/{REC_F2_PROP}")
        f2_page.wait_for_selector('#proposal-bar[data-armed="true"]')
        handle = f2_page.query_selector('#proposal-bar [data-key-action="confirm"]')
        held = _hold_post(f2_page, "/proposal/confirm")
        f2_page.locator('#proposal-bar [data-key-action="confirm"]').click()
        _wait_for_held(held)
        held["route"].fulfill(
            status=200,
            content_type="text/html",
            body='<div id="proposal-bar" class="proposal-region-empty"></div>',
        )
        # state="attached" — see test_18's comment on the same pattern.
        f2_page.wait_for_selector(
            "#proposal-bar.proposal-region-empty", state="attached"
        )
        assert f2_page.evaluate("el => !document.body.contains(el)", handle) is True

    def test_21_settle_bulk_graduate_reenables(
        self, f2_page: "Page", f2_server: ServerHandle
    ) -> None:
        """hx-swap="none": the button is NEVER swapped out, so htmx's own
        post-request re-enable (independent of swap) is what must fire —
        re-enabled, not detached."""
        _open(f2_page, f2_server, "/bucket/skill/s")
        button = f2_page.locator(".bulk-collapse-row button[data-key-action='graduate']")
        expect(button).to_be_visible()
        held = _hold_post(f2_page, "/graduate-bulk")
        button.click()
        _wait_for_held(held)
        assert button.get_attribute("disabled") is not None
        held["route"].fulfill(status=200, content_type="text/html", body="")
        expect(button).to_be_enabled()
        assert f2_page.evaluate(
            "el => document.body.contains(el)", button.element_handle()
        ) is True


# F3 — keymap binding (10, js; 8 of 10 here — retry/close_pane live in
# test_js_dom_pane_persistence.py, which owns the pane server fixture).
# Each presses the key in a context where the control renders and
# asserts the control was ACTIVATED, never that the key was accepted.


class TestNeverPressedKeymapActions:
    def test_reject_arms_deny(self, page: "Page", server: ServerHandle) -> None:
        _open(page, server, f"/record/{REC_BRIEF}")
        with page.expect_request(
            lambda r: r.url.endswith("/action/arm") and "verb=reject" in (r.post_data or "")
        ):
            page.keyboard.press("x")

    def test_defer_arms_defer(self, page: "Page", server: ServerHandle) -> None:
        _open(page, server, f"/record/{REC_PROP}")
        with page.expect_request(
            lambda r: r.url.endswith("/action/arm") and "verb=defer" in (r.post_data or "")
        ):
            page.keyboard.press("f")

    def test_graduate_arms_graduate(self, page: "Page", server: ServerHandle) -> None:
        _open(page, server, f"/record/{REC_BRIEF}")
        with page.expect_request(
            lambda r: r.url.endswith("/action/arm") and "verb=graduate" in (r.post_data or "")
        ):
            page.keyboard.press("g")

    def test_note_focuses_note_input(self, page: "Page", server: ServerHandle) -> None:
        _open(page, server, f"/record/{REC_BRIEF}")
        page.keyboard.press("n")
        assert page.evaluate("document.activeElement.getAttribute('name')") == "note"

    def test_iterate_starts_pane(self, page: "Page", server: ServerHandle) -> None:
        """Held via page.route() — PaneManager.start() is a real SDK
        engine call in this harness (no test override); see _hold_post."""
        _open(page, server, f"/record/{REC_PROP}")
        held = _hold_post(page, "/pane/start")
        page.keyboard.press("i")
        _wait_for_held(held)
        assert held["route"].request.url.endswith(f"/record/{REC_PROP}/pane/start")
        held["route"].fulfill(status=200, content_type="text/html", body="<div>ok</div>")

    def test_bucket_pane_starts_bucket_pane(
        self, page: "Page", server: ServerHandle
    ) -> None:
        _open(page, server, "/bucket/skill/t")
        held = _hold_post(page, "/pane/start")
        page.keyboard.press("p")
        _wait_for_held(held)
        assert held["route"].request.url.endswith("/bucket/skill/t/pane/start")
        held["route"].fulfill(status=200, content_type="text/html", body="<div>ok</div>")

    def test_tolerate_arms_with_tolerate_field(
        self, holding_page: "Page", holding_server: ServerHandle
    ) -> None:
        _open(holding_page, holding_server, "/")
        holding_page.wait_for_selector(".holding-row")
        with holding_page.expect_request(
            lambda r: r.url.endswith("/action/arm")
            and "verb=confirm-recurrence" in (r.post_data or "")
            and "tolerate=true" in (r.post_data or "")
        ):
            holding_page.keyboard.press("t")

    def test_c_arms_confirm_recurrence_not_the_generic_confirm(
        self, holding_page: "Page", holding_server: ServerHandle
    ) -> None:
        """F6's regression test (V-9). Vacuous-pass warning (spec):
        driving this on an ARMED bar instead would pass via
        Enter -> clickAction("confirm") and prove nothing — the Front
        page has NOTHING armed here, and (control) carries no
        [data-key-action="confirm"] element at all (host_add_bar.html,
        the only other "confirm" site, is included by bucket.html/
        detail.html, never index.html) — under V-9's reversion, `c`
        would find no target and this request would never fire."""
        _open(holding_page, holding_server, "/")
        holding_page.wait_for_selector(".holding-row")
        assert holding_page.query_selector('[data-key-action="confirm"]') is None
        with holding_page.expect_request(
            lambda r: r.url.endswith("/action/arm")
            and "verb=confirm-recurrence" in (r.post_data or "")
            and "tolerate" not in (r.post_data or "")
        ):
            holding_page.keyboard.press("c")
