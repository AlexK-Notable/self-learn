"""U22 (Y-28, 10 §3 U22 row / §7's js-marked obligation) — the collapsed
prior-conversation card, driven in a REAL browser against a REAL server
(FW-17's harness pattern, mirrored from test_js_dom.py; a separate module
rather than an addition to that shared file, to stay additive-only on a
file other in-flight f5-round units also touch).

Setup seeds the PERSISTED STORE directly (``PaneManager._store`` —
legitimate white-box test setup, not mocking the code under test) rather
than driving a real SDK session, so these tests need no model/network —
consistent with 10 §0 rule 7 for the DOM legs; the live SDK trial lives
in ``docs/specs/self-learn/fixtures/ui-trials.md`` instead.

Covers §7's pinned obligation: the card renders inside
``#pane-region-wrapper`` (no new region), Resume/View/Start-fresh swap
the SAME id, and Resume is absent when ``resumable == False``.
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
from self_learn_ui.runner import FakeRunner
from self_learn_ui.store import PaneTranscriptStore

from support import make_behavior, make_env, seed_record

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "ms-playwright"),
)

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.js

_STARTUP_TIMEOUT_S = 15.0
_SHUTDOWN_TIMEOUT_S = 10.0

TOKEN = "js-dom-pane-persistence-token"

REC_RESUMABLE = "lrn-aa000001"  # pending, bucket_dir matches -> resumable
REC_REHOMED = "lrn-bb000002"  # still pending, but bucket_dir moved -> NOT resumable (§4e)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerHandle:
    def __init__(self, base_url: str, app, loop: asyncio.AbstractEventLoop) -> None:
        self.base_url = base_url
        self.app = app
        self._loop = loop

    @property
    def pane_manager(self):
        return self.app.state.pane_manager


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerHandle]:
    tmp_path = tmp_path_factory.mktemp("js-dom-pane-persist")
    sandbox = make_env(tmp_path, skills=("s", "t"))

    resumable_record = make_behavior(scope="skill:s", record_id=REC_RESUMABLE)
    resumable_path = seed_record(sandbox.ledger, resumable_record)
    resumable_bucket_dir = resumable_path.parent.parent

    rehomed_record = make_behavior(scope="skill:s", record_id=REC_REHOMED)
    rehomed_path = seed_record(sandbox.ledger, rehomed_record)
    rehomed_original_bucket_dir = rehomed_path.parent.parent
    # Simulate a rehome (§4e MAJOR-2): the record STAYS pending but its
    # bucket moves — Detail must still render it (status pending, no
    # resolved-elsewhere redirect), while the recorded transcript's
    # bucket_dir (below) points at the OLD location.
    new_bucket_dir = sandbox.ledger / "skills" / "t"
    new_pending = new_bucket_dir / "pending" / f"{REC_REHOMED}.md"
    new_pending.parent.mkdir(parents=True, exist_ok=True)
    new_pending.write_bytes(rehomed_path.read_bytes())
    rehomed_path.unlink()

    port = _free_port()
    env = EnvConfig(
        self_learn_home=sandbox.ledger,
        ui_port=port,
        ui_browser=None,
        pane_model="test-model",
        pane_budget_usd=1.0,
        pane_max_turns=5,
        pane_engine="sdk",
    )
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)

    # Seed BOTH transcripts directly into the manager's own store — a
    # tmp_path-rooted store (never the real cache_dir()), independent of
    # PaneManager's lazy production wiring.
    store = PaneTranscriptStore(tmp_path / "seeded-panes")
    app.state.pane_manager._store = store
    app.state.pane_manager._pruned_once = True  # skip the opportunistic prune for this seeded store

    store.start_new(REC_RESUMABLE, record_id_or_bucket=REC_RESUMABLE, bucket_dir=str(resumable_bucket_dir))
    store.append_block(REC_RESUMABLE, kind="text", html="<p>hello from a prior turn</p>")
    store.append_block(REC_RESUMABLE, kind="tool", tool_name="Read", tool_target="/x/y")
    store.append_result(
        REC_RESUMABLE, status="success", cost_usd=0.01, turns=1, error=None, cap_hit=False, session_id="sdk-sess-1"
    )

    # Recorded against the ORIGINAL bucket_dir — the record itself now
    # lives in "t", so the §4e bucket-match clause fails -> not resumable.
    store.start_new(REC_REHOMED, record_id_or_bucket=REC_REHOMED, bucket_dir=str(rehomed_original_bucket_dir))
    store.append_block(REC_REHOMED, kind="text", html="<p>a conversation before the rehome</p>")
    store.append_result(
        REC_REHOMED, status="success", cost_usd=0.01, turns=1, error=None, cap_hit=False, session_id="sdk-sess-2"
    )

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    uv_server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(uv_server.serve())

    thread = threading.Thread(target=_run, name="js-dom-pane-persist-uvicorn", daemon=True)
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


def _open(page: "Page", server: ServerHandle, path: str) -> None:
    if not page.context.cookies():
        page.goto(f"{server.base_url}/?token={TOKEN}", wait_until="load")
    page.goto(f"{server.base_url}{path}", wait_until="load")


# ------------------------------------------------------------------ tests


def test_resumable_card_renders_inside_pane_region_wrapper(page: "Page", server: ServerHandle) -> None:
    _open(page, server, f"/record/{REC_RESUMABLE}")
    wrapper = page.locator("#pane-region-wrapper")
    assert wrapper.count() == 1
    assert wrapper.locator(".pane-prior-conversation").count() == 1
    summary = wrapper.locator(".pane-prior-summary").inner_text()
    assert "2 blocks" in summary
    assert "waiting for you" in summary


def test_resumable_card_shows_resume_view_and_start_fresh(page: "Page", server: ServerHandle) -> None:
    _open(page, server, f"/record/{REC_RESUMABLE}")
    wrapper = page.locator("#pane-region-wrapper")
    buttons = wrapper.locator(".pane-prior-controls button")
    labels = [buttons.nth(i).inner_text() for i in range(buttons.count())]
    assert "Resume" in labels
    assert "View" in labels
    assert "Start fresh" in labels


def test_rehomed_card_has_no_resume_button(page: "Page", server: ServerHandle) -> None:
    """Resume is absent when resumable == False (§7's pinned js
    assertion) — this record was REHOMED (stays pending, but its bucket
    moved — §4e MAJOR-2), so its persisted transcript still shows
    (has_persisted_transcript) but is view/start-fresh only."""
    _open(page, server, f"/record/{REC_REHOMED}")
    wrapper = page.locator("#pane-region-wrapper")
    assert wrapper.locator(".pane-prior-conversation").count() == 1
    buttons = wrapper.locator(".pane-prior-controls button")
    labels = [buttons.nth(i).inner_text() for i in range(buttons.count())]
    assert "Resume" not in labels
    assert "View" in labels
    assert "Start fresh" in labels
    summary = wrapper.locator(".pane-prior-summary").inner_text()
    assert "finished" in summary


def test_view_swaps_same_id_to_readonly_transcript_and_back(page: "Page", server: ServerHandle) -> None:
    _open(page, server, f"/record/{REC_RESUMABLE}")
    page.locator("#pane-region-wrapper .pane-prior-controls button", has_text="View").click()
    page.wait_for_selector("#pane-region-wrapper #pane-transcript")
    wrapper = page.locator("#pane-region-wrapper")
    # Still the SAME id — no new region — and the transcript is visible.
    assert wrapper.count() == 1
    assert "hello from a prior turn" in wrapper.inner_text()
    assert wrapper.locator(".pane-lifecycle-note", has_text="view only").count() == 1
    # No live controls in view-only mode.
    assert wrapper.locator("#pane-input-form").count() == 0

    # Back returns to the collapsed card, same id.
    page.locator("#pane-region-wrapper button", has_text="Back").click()
    page.wait_for_selector("#pane-region-wrapper .pane-prior-conversation")
    assert page.locator("#pane-region-wrapper").count() == 1
