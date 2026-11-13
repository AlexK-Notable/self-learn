"""Health page, in a real browser (humane lane 2, gate r1 M-1).

The rule filter is a form. `app.js` cancels every form submit that htmx
will not take (the submit guard, fail-closed), so a plain `method="get"`
form does NOTHING in a browser while every `TestClient` test of it passes
(no JavaScript runs there). This module drives the real page: type a query,
submit by Enter and by the Find button, and read the filtered list.

Waits use LOCATORS (`expect(locator)...`), never `page.wait_for_function("<js>")`:
the app's CSP has no `unsafe-eval`, so Playwright's string predicate can be
evaluated once but not re-polled, and a test that only passes when the swap is
already done at the first check is flaky (gate r2 M-1: 4 failures in 10 runs).

Same bring-up as `test_js_dom_targeting.py` (uvicorn in a thread, one
browser per module via `conftest._browser_or_sentinel`). `ledger.report` and
`ledger.status` are monkeypatched at module level (page reads are, per
CLAUDE.md), and the server shares this process, so the patch reaches it.
"""

from __future__ import annotations

import asyncio
import re
import socket
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import pytest
import uvicorn

from self_learn_ui import ledger
from self_learn_ui.app import create_app
from self_learn_ui.env import EnvConfig
from self_learn_ui.models import CliRead
from self_learn_ui.runner import FakeRunner

from conftest import _browser_or_sentinel
from support import make_env
from test_charts import REPORT, STATUS

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect
pytestmark = pytest.mark.js

TOKEN = "u-health-js-token"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def health_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    sb = make_env(tmp_path_factory.mktemp("ut-health"))
    mp = pytest.MonkeyPatch()
    mp.setattr(ledger, "report", lambda home: CliRead(data=REPORT))
    mp.setattr(ledger, "status", lambda home: CliRead(data=STATUS))
    port = _free_port()
    env = EnvConfig(
        self_learn_home=sb.ledger, ui_port=port, ui_browser=None, pane_model="test-model",
        pane_budget_usd=1.0, pane_max_turns=5, pane_engine="sdk",
    )
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    thread = threading.Thread(target=_run, name="ut-health-uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            mp.undo()
            raise AssertionError("in-process uvicorn never started")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        mp.undo()


@pytest.fixture(scope="module")
def browser(request, _browser_gate) -> Iterator["Browser"]:
    yield from _browser_or_sentinel(_browser_gate)


@pytest.fixture
def page(browser: "Browser", health_server: str) -> Iterator["Page"]:
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(f"{health_server}/?token={TOKEN}", wait_until="load")
    pg.goto(f"{health_server}/report", wait_until="load")
    # the body loads itself after the page: wait until it has swapped in (the
    # filter form is processed by htmx at the swap), not merely "load"
    expect(pg.locator("#health-rules-list")).to_be_attached()
    expect(pg.locator("#health-body")).to_have_count(0)
    expect(pg.locator(".htmx-added")).to_have_count(0)  # htmx has settled (the form is wired)
    try:
        yield pg
    finally:
        context.close()


RULES = "#health-rules-list td.health-rule"


def _titles(page: "Page") -> list[str]:
    return [t.strip() for t in page.locator(RULES).all_inner_texts()]


class TestRuleFilterInABrowser:
    def test_positive_control_all_rules_are_listed_before_filtering(self, page: "Page") -> None:
        expect(page.locator(RULES)).to_have_count(3)
        assert page.locator("#health-rule-filter").is_visible()

    def test_enter_filters_the_list(self, page: "Page") -> None:
        box = page.locator("#health-rule-filter")
        box.fill("pkill")
        box.press("Enter")
        expect(page.locator(RULES)).to_have_count(1)
        assert "pkill" in _titles(page)[0]
        expect(page.locator("#health-rules-list p.health-more", has_text="rules match")).to_contain_text("1 of 3 rules match")
        expect(page).to_have_url(re.compile(r"/report\?q=pkill$"))  # Back and a shared link keep the filter
        # the box keeps what was typed and stays on the page (only the list was swapped)
        expect(page.locator("#health-rule-filter")).to_have_value("pkill")

    def test_the_find_button_filters_the_list(self, page: "Page") -> None:
        page.locator("#health-rule-filter").fill("empty result")
        page.locator(".health-filter button[type=submit]").click()
        expect(page.locator(RULES)).to_have_count(1)
        assert "empty result" in _titles(page)[0]

    def test_a_query_with_no_match_says_so_and_can_be_cleared(self, page: "Page") -> None:
        box = page.locator("#health-rule-filter")
        box.fill("zzzz-nothing")
        box.press("Enter")
        expect(page.locator("#health-rules-list p.health-more", has_text="No rule matches")).to_be_visible()
        expect(page.locator(RULES)).to_have_count(0)
        page.locator("#health-rules-list a", has_text="Show every rule").click()
        expect(page.locator(RULES)).to_have_count(3)

    def test_a_cleared_box_leaves_a_clean_address(self, page: "Page", health_server: str) -> None:
        box = page.locator("#health-rule-filter")
        box.fill("pkill")
        box.press("Enter")
        expect(page.locator(RULES)).to_have_count(1)
        box.fill("")
        box.press("Enter")
        expect(page.locator(RULES)).to_have_count(3)
        expect(page).to_have_url(f"{health_server}/report")  # not /report?q=

    def test_filtering_from_the_all_view_keeps_it(self, page: "Page", health_server: str) -> None:
        page.goto(f"{health_server}/report?all=1", wait_until="load")
        expect(page.locator("#health-body")).to_have_count(0)  # the body loads itself after the page
        expect(page.locator(".htmx-added")).to_have_count(0)  # and htmx has settled
        box = page.locator("#health-rule-filter")
        box.fill("rule")
        box.press("Enter")
        expect(page).to_have_url(re.compile(r"/report\?all=1&q=rule$"))

    def test_while_searching_it_says_so_and_the_button_is_off(self, page: "Page") -> None:
        held: list = []
        page.route("**/report?q=*", lambda route: held.append(route))  # hold the request in flight
        page.locator("#health-rule-filter").fill("pkill")
        page.locator(".health-filter button[type=submit]").click()
        searching = page.locator(".health-filter .health-searching")
        expect(searching).to_be_visible()
        expect(page.locator(".health-filter button[type=submit]")).to_be_disabled()
        assert len(held) == 1
        held[0].continue_()  # let it through
        expect(page.locator(RULES)).to_have_count(1)
        expect(searching).to_be_hidden()
        expect(page.locator(".health-filter button[type=submit]")).to_be_enabled()

    def test_back_and_forward_keep_the_filter_without_console_errors(self, page: "Page") -> None:
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        box = page.locator("#health-rule-filter")
        box.fill("pkill")
        box.press("Enter")
        expect(page.locator(RULES)).to_have_count(1)
        page.go_back()
        expect(page.locator(RULES)).to_have_count(3)
        page.go_forward()
        expect(page.locator(RULES)).to_have_count(1)
        assert errors == [], errors


class TestTypingInTheBoxLeavesTheKeymapAlone:
    def test_letters_that_navigate_elsewhere_stay_in_the_box(self, page: "Page", health_server: str) -> None:
        """`h` goes up a level, `s` and `w` move, `a` acts, `?` opens help,
        outside a text box. Inside it they are text. Deleting the text-input
        guard in app.js (`focusIsTextInput`) makes `h` navigate away, which
        this test sees as a document request and a changed address."""
        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url) if r.resource_type == "document" else None)
        box = page.locator("#health-rule-filter")
        box.click()
        box.type("hasdw? j")
        page.wait_for_timeout(500)  # long enough for a navigation a deleted guard would start
        expect(page).to_have_url(f"{health_server}/report")
        expect(box).to_have_value("hasdw? j")
        assert requests == [], requests
        expect(page.locator("#self-learn-ui-help")).to_be_hidden()


class TestNarrowScreen:
    def test_lessons_by_place_counts_stay_on_screen_at_390px(self, browser: "Browser", health_server: str) -> None:
        """Gate r2 m-4: a long path in the Place column pushed the counts
        past the right edge."""
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        try:
            pg = ctx.new_page()
            pg.goto(f"{health_server}/?token={TOKEN}", wait_until="load")
            pg.goto(f"{health_server}/report", wait_until="load")
            fold = pg.locator('details[aria-label="lessons by place"]')
            fold.locator("summary").click()
            cell = fold.locator('td[data-label="Lessons"]').first
            expect(cell).to_be_visible()
            assert "in use" in cell.inner_text()  # positive control: the counts rendered
            box = cell.bounding_box()
            assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 390 + 1, box
            assert pg.evaluate("document.documentElement.scrollWidth") <= 390
        finally:
            ctx.close()


class TestBodyLoadsAfterThePage:
    """Speed batch 2: the page is a shell that fetches its own body."""

    def test_a_failed_body_shows_an_error_and_try_again_recovers(self, browser: "Browser", health_server: str) -> None:
        ctx = browser.new_context()
        try:
            pg = ctx.new_page()
            pg.goto(f"{health_server}/?token={TOKEN}", wait_until="load")
            failing = {"on": True}

            def handle(route) -> None:
                if failing["on"]:
                    route.fulfill(status=500, body="boom")
                else:
                    route.continue_()

            pg.route("**/report/body*", handle)
            pg.goto(f"{health_server}/report", wait_until="load")
            expect(pg.locator("#health-body .lazy-failed")).to_contain_text("could not be loaded")
            expect(pg.locator("#health-body")).to_have_attribute("aria-busy", "false")
            expect(pg.locator(RULES)).to_have_count(0)
            failing["on"] = False
            pg.locator("#health-body .lazy-retry").click()
            expect(pg.locator(RULES)).to_have_count(3)  # the body came in on the retry
            expect(pg.locator("#health-body")).to_have_count(0)  # the placeholder is gone
        finally:
            ctx.close()

    def test_keyboard_focus_stays_put_when_the_body_arrives(self, browser: "Browser", health_server: str) -> None:
        ctx = browser.new_context()
        try:
            pg = ctx.new_page()
            pg.goto(f"{health_server}/?token={TOKEN}", wait_until="load")
            held: list = []
            pg.route("**/report/body*", lambda route: held.append(route))
            pg.goto(f"{health_server}/report", wait_until="load")
            deadline = time.monotonic() + 10
            while not held and time.monotonic() < deadline:
                pg.wait_for_timeout(50)
            assert held, "positive control: the body request was made and is being held"
            expect(pg.locator("#health-body .lazy-loading")).to_contain_text("Counting")  # the loading state shows
            link = pg.locator('a[data-key-action="up"]').first
            link.focus()
            expect(link).to_be_focused()
            held[0].continue_()
            expect(pg.locator(RULES)).to_have_count(3)
            expect(link).to_be_focused()
        finally:
            ctx.close()
