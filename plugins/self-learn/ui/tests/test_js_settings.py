"""The settings page's script (static/settings.js, humane lane 4), in a real
browser: "Find a setting" filtering as you type, a row's Save button
appearing only once its value changed, a jump chip opening a closed group,
and a saved row coming back swapped in with its Save button hidden again.

The server is one in-process uvicorn running the real ``create_app``; the
page read (`ledger.settings`) is monkeypatched with a small fixture whose
rows use real group ids, and verbs go to a FakeRunner whose argv are read
back. Each test names the mutation it was checked against.
"""

from __future__ import annotations

import asyncio
import json
import os
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
from self_learn_ui.runner import FakeRunner, RunResult

from conftest import _browser_or_sentinel

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "ms-playwright"),
)

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.js

TOKEN = "js-settings-token"


def _row(name, group, label, plain, kind="bool", value=True, source="default", tier="A",
         description="a technical note"):
    return {"name": name, "value": value, "source": source, "kind": kind, "default": value,
            "description": description, "group": group, "label": label, "plain": plain,
            "tier": tier, "warn": None, "note": None}


ROWS = [
    _row("miner.enabled", "runs", "Read my sessions overnight", "Each night, read the day's sessions."),
    _row("overseer.enabled", "runs", "Weekly check", "Once a week, re-check decisions."),
    _row("miner.max_run_usd", "limits", "Most one overnight read may use", "No new session starts past this.",
         kind="float", value=8.0),
    _row("models.miner", "models", "Overnight read", "The model that reads your sessions.",
         kind="str", value="sonnet"),
    _row("worker.coalesce_secs", "time", "Wait before drafting", "Seconds drafting waits.",
         kind="float", value=600.0, description="seconds the worker sleeps to coalesce a run"),
    _row("provider.bedrock.region", "bedrock", "Bedrock region", "The region.", kind="str", value=None),
]


class Server:
    def __init__(self, base_url: str, app) -> None:
        self.base_url = base_url
        self.app = app

    @property
    def runner(self) -> FakeRunner:
        return self.app.state.runner


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    patch = pytest.MonkeyPatch()
    patch.setattr(ledger, "settings", lambda home, env=None: CliRead(data=[dict(r) for r in ROWS]))
    home = tmp_path_factory.mktemp("js-settings") / "home"
    home.mkdir()
    port = _free_port()
    env = EnvConfig(self_learn_home=home, ui_port=port, ui_browser=None, pane_model="m",
                    pane_budget_usd=1.0, pane_max_turns=5, pane_engine="sdk")
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    uv_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                              log_level="warning", lifespan="on"))
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(uv_server.serve())

    thread = threading.Thread(target=_run, name="js-settings-uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15.0
    while not uv_server.started:
        if time.monotonic() > deadline:
            uv_server.should_exit = True
            patch.undo()
            raise AssertionError("in-process uvicorn never started")
        time.sleep(0.02)
    try:
        yield Server(f"http://127.0.0.1:{port}", app)
    finally:
        uv_server.should_exit = True
        thread.join(timeout=10.0)
        patch.undo()


@pytest.fixture(scope="module")
def browser(server: Server, _browser_gate) -> Iterator["Browser"]:
    yield from _browser_or_sentinel(_browser_gate)


@pytest.fixture
def page(browser: "Browser", server: Server) -> Iterator["Page"]:
    server.runner.calls.clear()
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(f"{server.base_url}/?token={TOKEN}", wait_until="load")
    pg.goto(f"{server.base_url}/settings", wait_until="load")
    pg.wait_for_selector("#setting-row-miner-enabled")
    try:
        yield pg
    finally:
        context.close()


def _visible_rows(page: "Page") -> list[str]:
    return page.eval_on_selector_all(
        "li.setting:not([hidden])",
        "els => els.filter(e => e.checkVisibility()).map(e => e.id)")


def _poll(predicate, timeout: float = 5.0) -> bool:
    """htmx settles a swap a beat after inserting it; poll from Python (a
    string predicate would be evaluated in the page, which the CSP refuses)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_typing_filters_the_rows_and_opens_the_group_that_holds_a_match(page):
    """Positive control first: every row is visible and the folded `time`
    group is closed. Typing a word only the technical note of one row has
    shows that row alone and opens its group; clearing the box brings every
    row back and closes the group again. Mutations: `row.hidden = !hit`
    removed -> red (all rows stay); the open-on-match lines removed -> red
    (the match stays inside a closed group); the restore on clear removed
    -> red (the group stays open)."""
    assert len(_visible_rows(page)) == len([r for r in ROWS if r["group"] not in ("time", "bedrock")])
    assert page.evaluate("document.getElementById('group-time').open") is False
    page.fill("#settings-q", "sleeps")
    assert _visible_rows(page) == ["setting-row-worker-coalesce_secs"]
    assert page.evaluate("document.getElementById('group-time').open") is True
    assert page.is_hidden("#group-runs")
    assert "1 setting matches" in page.inner_text("[data-settings-status]")
    page.fill("#settings-q", "")
    assert page.evaluate("document.getElementById('group-time').open") is False
    assert "setting-row-miner-enabled" in _visible_rows(page)
    assert page.inner_text("[data-settings-status]").strip() == ""


def test_a_word_hides_the_other_rows_of_a_group_that_still_has_a_match(page):
    """The rows of a group that holds a match are filtered one by one, not only
    hidden along with an empty group. "weekly" is in Weekly check's name and in
    no other row of the same group. Mutation: `row.hidden = !hit` replaced by
    `row.hidden = false` -> red (Read my sessions overnight stays)."""
    assert "setting-row-miner-enabled" in _visible_rows(page)  # positive control
    page.fill("#settings-q", "weekly")
    assert _visible_rows(page) == ["setting-row-overseer-enabled"]
    page.fill("#settings-q", "")
    assert "setting-row-miner-enabled" in _visible_rows(page)


def test_a_search_with_no_match_says_so(page):
    """Mutation: the empty-result line is never unhidden -> red."""
    page.fill("#settings-q", "zzzz")
    assert _visible_rows(page) == []
    assert page.is_visible("[data-settings-none]")
    page.fill("#settings-q", "")
    assert page.is_hidden("[data-settings-none]")


def test_save_shows_only_once_a_value_changed(page):
    """Mutations: the initial `save.hidden = true` removed -> red (the button
    shows on a fresh page); `update` only ever shows, never hides again ->
    red (changing back leaves Save showing)."""
    save = "#setting-row-miner-max_run_usd [data-setting-save]"
    assert page.is_hidden(save)
    page.fill("#setting-row-miner-max_run_usd input[name=value]", "9")
    assert page.is_visible(save)
    page.fill("#setting-row-miner-max_run_usd input[name=value]", "8.0")
    assert page.is_hidden(save)
    page.select_option("#setting-row-miner-enabled select[name=value]", "0")
    assert page.is_visible("#setting-row-miner-enabled [data-setting-save]")


def test_a_jump_chip_opens_the_closed_group(page):
    """Mutation: the chip click handler removed -> red (the group stays
    closed behind the anchor)."""
    assert page.evaluate("document.getElementById('group-bedrock').open") is False
    page.click('[data-settings-chip="bedrock"]')
    assert page.evaluate("document.getElementById('group-bedrock').open") is True


def test_a_saved_row_comes_back_with_its_save_button_hidden_and_says_saved(page, server):
    """The save goes through the row's own form (`config set`), the swapped-in
    row says it was saved, and its new Save button is hidden again.
    Mutation: the `htmx:load` watcher removed -> red (the swapped row's
    Save button shows)."""
    saved = _row("miner.max_run_usd", "limits", "Most one overnight read may use", "p",
                 kind="float", value=9.0, source="config:miner.max_run_usd")
    server.runner.queue_result(RunResult(0, stdout=json.dumps(saved)))
    page.fill("#setting-row-miner-max_run_usd input[name=value]", "9")
    page.click("#setting-row-miner-max_run_usd [data-setting-save]")
    page.wait_for_selector("#setting-row-miner-max_run_usd .setting-saved")
    assert server.runner.calls == [["config", "set", "miner.max_run_usd", "--json", "--", "9"]]
    assert "Set in config.yaml" in page.inner_text("#setting-row-miner-max_run_usd")
    # the word "Saved." holds off the page reload the save itself causes (09 §3.5 leg f)
    assert page.locator("#setting-row-miner-max_run_usd .setting-saved[data-verb-success]").count() == 1
    assert _poll(lambda: page.is_hidden("#setting-row-miner-max_run_usd [data-setting-save]"))
    # the same swapped row keeps working: a new edit shows Save again
    page.fill("#setting-row-miner-max_run_usd input[name=value]", "10")
    assert page.is_visible("#setting-row-miner-max_run_usd [data-setting-save]")
