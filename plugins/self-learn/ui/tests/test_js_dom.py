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
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import uvicorn

from self_learn_ui.app import create_app
from self_learn_ui.env import EnvConfig
from self_learn_ui.keymap import keymap_as_dicts
from self_learn_ui.proposals import VerbProposal
from self_learn_ui.runner import FakeRunner

from support import make_env, make_behavior, seed_record

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


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    tmp_path = tmp_path_factory.mktemp("js-dom")
    ledger = _seed_ledger(tmp_path)

    # NB: no global os.environ mutation here. The route handlers shell
    # `self-learn ... --json`, and ledger._invoke_json pins SELF_LEARN_HOME
    # to the sandbox per call; the CLI namespaces its cache by that home,
    # so the child never touches the real ledger (the same isolation every
    # in-process route test relies on). Mutating os.environ session-wide
    # would leak into the rest of the suite.
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

    thread = threading.Thread(target=_run, name="js-dom-uvicorn", daemon=True)
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
