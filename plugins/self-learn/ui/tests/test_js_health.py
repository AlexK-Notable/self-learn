"""Health page, in a real browser (humane lane 2, gate r1 M-1).

The rule filter is a form. `app.js` cancels every form submit that htmx
will not take (the submit guard, fail-closed), so a plain `method="get"`
form does NOTHING in a browser while every `TestClient` test of it passes
(no JavaScript runs there). This module drives the real page: type a query,
submit by Enter and by the Find button, and read the filtered list.

Same bring-up as `test_js_dom_targeting.py` (uvicorn in a thread, one
browser per module via `conftest._browser_or_sentinel`). `ledger.report` and
`ledger.status` are monkeypatched at module level (page reads are, per
CLAUDE.md), and the server shares this process, so the patch reaches it.
"""

from __future__ import annotations

import asyncio
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

pytest.importorskip("playwright.sync_api")
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
    try:
        yield pg
    finally:
        context.close()


def _titles(page: "Page") -> list[str]:
    return [t.strip() for t in page.locator("#health-rules-list td.health-rule").all_inner_texts()]


class TestRuleFilterInABrowser:
    def test_positive_control_all_rules_are_listed_before_filtering(self, page: "Page") -> None:
        assert len(_titles(page)) == 3
        assert page.locator("#health-rule-filter").is_visible()

    def test_enter_filters_the_list(self, page: "Page") -> None:
        box = page.locator("#health-rule-filter")
        box.fill("pkill")
        box.press("Enter")
        page.wait_for_function(
            "document.querySelectorAll('#health-rules-list td.health-rule').length === 1", timeout=5000
        )
        assert "pkill" in _titles(page)[0]
        assert "1 of 3 rules match" in page.locator("#health-rules-list").inner_text()
        assert "q=pkill" in page.url  # the filter is in the address: Back and a shared link keep it
        # the box keeps what was typed and stays on the page (only the list was swapped)
        assert page.locator("#health-rule-filter").input_value() == "pkill"

    def test_the_find_button_filters_the_list(self, page: "Page") -> None:
        page.locator("#health-rule-filter").fill("empty result")
        page.locator(".health-filter button[type=submit]").click()
        page.wait_for_function(
            "document.querySelectorAll('#health-rules-list td.health-rule').length === 1", timeout=5000
        )
        assert "empty result" in _titles(page)[0]

    def test_a_query_with_no_match_says_so_and_can_be_cleared(self, page: "Page") -> None:
        box = page.locator("#health-rule-filter")
        box.fill("zzzz-nothing")
        box.press("Enter")
        page.wait_for_selector("#health-rules-list >> text=No rule matches", timeout=5000)
        page.locator("#health-rules-list a", has_text="Show every rule").click()
        page.wait_for_function(
            "document.querySelectorAll('#health-rules-list td.health-rule').length === 3", timeout=5000
        )

    def test_typing_in_the_box_does_not_fire_the_keymap(self, page: "Page") -> None:
        box = page.locator("#health-rule-filter")
        box.click()
        box.type("? j")
        assert box.input_value() == "? j"
