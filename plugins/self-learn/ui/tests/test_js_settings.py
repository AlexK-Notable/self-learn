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
    _row("worker.repair_timeout_secs", "time", "Repair time limit", "Seconds one repair round may run.",
         kind="float", value=600.0, description="seconds one repair round may run"),
    _row("provider.bedrock.region", "bedrock", "Bedrock region", "The region.", kind="str", value=None),
]


class Server:
    def __init__(self, base_url: str, app, loop) -> None:
        self.base_url = base_url
        self.app = app
        self.loop = loop

    def push_refresh(self) -> None:
        """A broadcast refresh, as the ledger watcher or a verb's post-run push
        sends it: app.js answers it with a full page reload unless a hold applies."""
        self.loop.call_soon_threadsafe(self.app.state.refresh_hub.force_refresh, "front")

    def wait_for_subscriber(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.app.state.refresh_hub.subscriber_count >= 1:
                return
            time.sleep(0.02)
        raise AssertionError("the page never opened its event stream")

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
        yield Server(f"http://127.0.0.1:{port}", app, loop)
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
    server.wait_for_subscriber()
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


# ---- the holds a save puts the page under, and their release (gate r1 MINOR-1) ----

ROW = "#setting-row-miner-max_run_usd"


def _save(page, server, *, value="9", result=None):
    saved = _row("miner.max_run_usd", "limits", "Most one overnight read may use", "p",
                 kind="float", value=float(value), source="config:miner.max_run_usd")
    server.runner.queue_result(result or RunResult(0, stdout=json.dumps(saved)))
    page.fill(f"{ROW} input[name=value]", value)
    page.click(f"{ROW} [data-setting-save]")
    page.wait_for_selector(f"{ROW} [data-setting-message]")


def _mark(page) -> None:
    page.evaluate("window.__mark = 1")


def _reloaded(page, timeout: float = 5.0) -> bool:
    """The page navigated: its marker is gone, or the read raced the navigation."""
    def gone() -> bool:
        try:
            return page.evaluate("window.__mark") is None
        except sync_api.Error:  # "Execution context was destroyed": it is navigating
            return True

    return _poll(gone, timeout)


def _held(page) -> bool:
    """A refresh was pushed and the page did NOT reload for a while."""
    time.sleep(1.2)
    return page.evaluate("window.__mark") == 1


def test_dismissing_saved_releases_the_refresh_it_held(page, server):
    """After a save the page holds a broadcast refresh (leg f) so "Saved." is
    not wiped; Dismiss removes the message and the held refresh fires. The
    positive control is that the refresh was held at all (the page had not
    reloaded 1.2 s after it was pushed). Mutations: the dismiss handler removed
    -> red (no Dismiss reaches the page); `release()` not dispatched after the
    removal -> red (the page never reloads)."""
    _save(page, server)
    assert page.locator(f"{ROW} .setting-saved[data-verb-success]").count() == 1
    _mark(page)
    server.push_refresh()
    assert _held(page)
    page.click(f"{ROW} [data-setting-dismiss]")
    assert page.locator(f"{ROW} [data-setting-message]").count() == 0
    assert _reloaded(page)


def test_dismissing_a_refusal_releases_the_refresh_it_held(page, server):
    """The same for a refused save's strip (leg a). Mutation: the strip loses
    its Dismiss button -> red."""
    _save(page, server, result=RunResult(1, stderr="self-learn config set: miner.max_run_usd='x' is not a float"))
    assert page.locator(f"{ROW} [data-setting-error][data-verb-error]").count() == 1
    _mark(page)
    server.push_refresh()
    assert _held(page)
    page.click(f"{ROW} [data-setting-dismiss]")
    assert _reloaded(page)


def test_editing_retires_the_message_and_holds_until_the_edit_is_taken_back(page, server):
    """The next edit retires the stale "Saved." but the page stays held while a
    value is half-typed (leg g: a reload would throw the edit away); taking the
    edit back releases the held refresh. Mutations: the edit does not remove
    the message -> red; the dirty marker not set -> red (the refresh reloads
    under the typing); the release after taking the edit back removed -> red."""
    _save(page, server)
    _mark(page)
    server.push_refresh()
    assert _held(page)
    page.fill(f"{ROW} input[name=value]", "11")
    assert page.locator(f"{ROW} [data-setting-message]").count() == 0
    assert page.locator(f"{ROW} form[data-setting-dirty]").count() == 1
    assert _held(page)  # the typed value is still there
    assert page.input_value(f"{ROW} input[name=value]") == "11"
    page.fill(f"{ROW} input[name=value]", "9.0")
    assert _reloaded(page)


def test_a_search_the_server_filtered_clears_in_the_page(page, server):
    """A page opened as `?q=sleeps` is already narrowed by the server; clearing
    the box brings every row back, the group's count follows the search ("1 of
    2", then "2"), and "Show all" goes once the box is empty. Mutations: the
    count update removed -> red; `clear.hidden` removed -> red (Show all
    outlives the search)."""
    page.goto(f"{server.base_url}/settings?q=sleeps", wait_until="load")
    assert page.is_visible("[data-settings-clear]")
    assert page.inner_text("#group-time [data-settings-count]") == "(1 of 2)"
    assert "setting-row-miner-enabled" not in _visible_rows(page)  # positive control: narrowed
    page.fill("#settings-q", "")
    assert "setting-row-miner-enabled" in _visible_rows(page)
    assert page.is_hidden("[data-settings-clear]")
    assert page.inner_text("#group-time [data-settings-count]") == "(2)"
