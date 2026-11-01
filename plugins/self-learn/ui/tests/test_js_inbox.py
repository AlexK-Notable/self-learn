"""static/inbox.js in a real browser (attention round, ui-workspace fix
round 1; gate r1 findings 1, 2 and 5).

These three are orderings and page memory — what a reload restores, which
envelope arrives before which response, where focus is when Enter is
pressed — so each is driven through the REAL served inbox page in a REAL
Chromium running the real ``inbox.js``/``app.js``/htmx, the way
``test_js_dom.py`` drives ``app.js``.

The server is one in-process uvicorn running the real ``create_app``.
Page reads (``ledger.attention``, ``ledger.attention_packet``,
``ledger.workspace_rows``) are monkeypatched for the module with the
§4.1/§4.3 shapes; verbs go to a ``FakeRunner`` whose calls are read back
off the server (the argv the answer verb would have run). No ledger, no
CLI, no model.

Each test names the mutation it was checked against.
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

from self_learn_ui import ledger
from self_learn_ui.app import create_app
from self_learn_ui.ask_runner import FakeAskRunner
from self_learn_ui.env import EnvConfig
from self_learn_ui.models import CliRead
from self_learn_ui.runner import FakeRunner, RunResult
from self_learn_ui.sse import AppEventHub

from conftest import _browser_or_sentinel

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

# As test_js_dom.py: pin Playwright's browser registry before any fixture
# redirects XDG_CACHE_HOME.
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "ms-playwright"),
)

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.js

TOKEN = "js-inbox-token"
ID_OO7 = "att-0000000000b2"
ID_HOST = "att-0000000000d4"
DRAFT_ID = "drf-1a2b3c4d"
_WAIT_MS = 10000


def _opt(id_, label, effect="other", *, via="answer", recommended=False, note=None):
    return {"id": id_, "label": label, "effect": effect, "confirm": False, "note": note,
            "recommended": recommended, "via": via}


def _item(id_, kind, because, title, options):
    return {
        "id": id_, "class": "needs-you", "kind": kind, "because": because,
        "subject": f"subj-{id_}", "title": title, "meanwhile": None, "flagged": False,
        "seen": True, "state": "open", "partial": False, "since": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-01T10:00:00Z",
        "source": {"by": "overseer", "run": None, "report": None}, "refs": [],
        "options": list(options), "undo": None, "conversation": {"turns": 0, "last_at": None},
        "answer": None, "run": None,
    }


OO7 = _item(ID_OO7, "ask.system-change", "system-change",
            "Bind oo7-daemon to the session bus so it survives a bus restart?", (
                _opt("opt-yes", "Yes, add the binding", "approve", recommended=True),
                _opt("opt-yes-conditions", "Yes, with conditions", "approve", note="required"),
                _opt("opt-no", "No, keep the manual note", "decline"),
            ))
HOST = _item(ID_HOST, "broken.host", "broken", "The host service has stopped",
             (_opt("opt-restart", "Restart self-learn", via="fix", recommended=True),))

OO7_PACKET = {
    "packet_version": 1, "generated_at": "2026-11-01T11:30:12Z", "item": OO7,
    "question": OO7["title"], "why_you": "It changes how your computer behaves.",
    "meanwhile": "Nothing on your system was changed.",
    "recommendation": {"option": "opt-yes", "text": "Yes, add the binding", "reasoning": "r"},
    "options": [{**o, "does": "d"} for o in OO7["options"]], "alternatives": [],
    "plan": None, "decided": None, "undo": None,
    "evidence": [{"kind": "lesson", "id": "lrn-9b4250f5", "title": "Restart oo7-daemon by hand",
                  "text": "After a bus restart, restart oo7-daemon.", "status": "routed",
                  "placement": "user"}],
    "more": [], "pointers": [], "look_at": [],
    "conversation": {"turns": 1, "last_at": None, "agent_available": True,
                     "agent_unavailable": None},
    "answer": None, "limits": {"bytes": 1000, "truncated": []},
}
#: A short agent draft: exactly the shape the 40-character paste match
#: cannot recognise, so only the draft id keeps it from being "typed".
OO7_ROWS = [
    {"t": 0, "kind": "header"},
    {"t": 1, "role": "user", "origin": "typed", "kind": "question", "text": "draft it"},
    {"t": 2, "role": "agent", "origin": "agent", "kind": "draft", "draft_id": DRAFT_ID,
     "option": "opt-yes-conditions", "text": "Only the first two."},
]


def _doc(*items):
    return {
        "version": 2, "generated_at": "2026-11-01T11:30:12Z", "cache_dir": "/tmp/x",
        "state": "needs-you" if items else "idle",
        "counts": {"needs_you": len(items), "new": 0, "decided_unseen": 0, "approved": 0},
        "tooltip": "self-learn", "error": None, "items": list(items),
    }


class State:
    """What the monkeypatched reads return; tests reset it."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.doc = _doc(OO7, HOST)
        self.remove_on_answer: str | None = None


class Runner(FakeRunner):
    """Records argv; an answer can take its item off the list (as an
    answered ask leaves it), so the verb's own `attention` envelope lacks it."""

    def __init__(self, state: State) -> None:
        super().__init__(RunResult(0, stdout=json.dumps(
            {"state": "open", "recorded_as": "as the agent's draft, edited and sent by you"})))
        self.state = state

    async def run(self, argv):
        gone = self.state.remove_on_answer
        if argv[:2] == ["attention", "answer"] and gone is not None and argv[2] == gone:
            self.state.doc = _doc(*[i for i in self.state.doc["items"] if i["id"] != gone])
            self.calls.append(list(argv))
            return RunResult(0, stdout=json.dumps(
                {"state": "answered", "recorded_as": "as your choice of the offered option"}))
        return await super().run(argv)


class Server:
    def __init__(self, base_url: str, app, loop, state: State) -> None:
        self.base_url = base_url
        self.app = app
        self.loop = loop
        self.state = state

    @property
    def runner(self) -> Runner:
        return self.app.state.runner

    def push(self, envelope: dict) -> None:
        self.loop.call_soon_threadsafe(self.app.state.app_hub.publish_nowait, envelope)

    def wait_for_subscriber(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.app.state.app_hub.subscriber_count >= 1:
                return
            time.sleep(0.02)
        raise AssertionError("the page never opened its event stream")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    state = State()
    patch = pytest.MonkeyPatch()
    patch.setattr(ledger, "attention", lambda home, env=None: CliRead(data=state.doc))
    patch.setattr(ledger, "attention_packet",
                  lambda home, item_id, env=None: ledger.PacketRead(
                      data=OO7_PACKET if item_id == ID_OO7 else None,
                      error=None if item_id == ID_OO7 else "no packet in this fixture"))
    patch.setattr(ledger, "workspace_rows",
                  lambda home, item_id: list(OO7_ROWS) if item_id == ID_OO7 else [])
    home = tmp_path_factory.mktemp("js-inbox") / "home"
    home.mkdir()
    port = _free_port()
    env = EnvConfig(self_learn_home=home, ui_port=port, ui_browser=None, pane_model="m",
                    pane_budget_usd=1.0, pane_max_turns=5, pane_engine="sdk")
    hub = AppEventHub()
    app = create_app(env=env, token=TOKEN, runner=Runner(state), app_hub=hub,
                     start_watcher=False, ask_runner=FakeAskRunner(publish=hub.publish_nowait))
    uv_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                              log_level="warning", lifespan="on"))
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(uv_server.serve())

    thread = threading.Thread(target=_run, name="js-inbox-uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15.0
    while not uv_server.started:
        if time.monotonic() > deadline:
            uv_server.should_exit = True
            patch.undo()
            raise AssertionError("in-process uvicorn never started")
        time.sleep(0.02)
    try:
        yield Server(f"http://127.0.0.1:{port}", app, loop, state)
    finally:
        uv_server.should_exit = True
        thread.join(timeout=10.0)
        patch.undo()


@pytest.fixture(scope="module")
def browser(server: Server, _browser_gate) -> Iterator["Browser"]:
    yield from _browser_or_sentinel(_browser_gate)


@pytest.fixture
def page(browser: "Browser", server: Server) -> Iterator["Page"]:
    server.state.reset()
    server.runner.calls.clear()
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(f"{server.base_url}/?token={TOKEN}", wait_until="load")
    try:
        yield pg
    finally:
        context.close()


def _open(page: "Page", server: Server, item_id: str) -> None:
    page.goto(f"{server.base_url}/inbox/{item_id}", wait_until="load")
    page.wait_for_selector(f'#ws[data-item-id="{item_id}"]')
    server.wait_for_subscriber()


def _answer_calls(server: Server) -> list[list[str]]:
    return [c for c in server.runner.calls if c[:2] == ["attention", "answer"]]


def _wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


# ------------------------------------------------------------- finding 1


def test_a_restored_draft_is_still_sent_as_the_agents_draft_with_its_option(page, server):
    """C6: "Use this draft", then a reload. The restored reply keeps the
    draft's id and option, so the answer verb gets `--draft` (and the
    option) and records the agent's draft, never the person's typed words.
    Mutation: restore the text only (skip applyDraftMeta in restoreUnsent)
    -> red."""
    _open(page, server, ID_OO7)
    page.click(f'[data-draft-card][data-draft-id="{DRAFT_ID}"] [data-use-draft]')
    # Positive control: before any reload the draft is wired into the form.
    assert page.input_value("#ws-reply-draft") == DRAFT_ID
    page.reload(wait_until="load")
    page.wait_for_selector(f'#ws[data-item-id="{ID_OO7}"]')
    page.wait_for_function("document.getElementById('ws-reply-text').value === 'Only the first two.'",
                           timeout=_WAIT_MS)
    assert page.input_value("#ws-reply-draft") == DRAFT_ID
    assert page.get_attribute("#ws-answer-form", "data-draft-option") == "opt-yes-conditions"
    assert page.is_visible("#ws-reply-draft-note")
    page.click("[data-send-reply]")
    _wait_for(lambda: bool(_answer_calls(server)))
    argv = _answer_calls(server)[-1]
    assert argv[argv.index("--draft") + 1] == DRAFT_ID
    assert argv[argv.index("--option") + 1] == "opt-yes-conditions"
    assert "--text-file" in argv


# ------------------------------------------------------------- finding 2


def test_the_persons_own_answer_is_never_called_resolved_elsewhere(page, server):
    """§3.7's resolved-elsewhere banner is for an item resolved away from
    this page. An answer from this page takes the item off the list and
    publishes an `attention` envelope from inside the verb; neither that
    envelope nor a later tick shows the banner. Mutation: drop the
    resolvedByThisPage check in noteResolved -> red."""
    # Positive control: on another item, an envelope without it shows the banner.
    _open(page, server, ID_HOST)
    server.push({"type": "attention", "state": "needs-you", "counts": {}, "ids": [ID_OO7]})
    page.wait_for_selector("[data-resolved-banner]", timeout=_WAIT_MS)

    server.state.remove_on_answer = ID_OO7
    _open(page, server, ID_OO7)
    page.click('#ws-answer [data-option-index="3"]')  # "No, keep the manual note"
    page.wait_for_selector("#ws-answer [data-answer-closed]", timeout=_WAIT_MS)
    assert _answer_calls(server)[-1][:5] == ["attention", "answer", ID_OO7, "--option", "opt-no"]
    time.sleep(0.8)  # the verb's own envelope has arrived by now
    assert page.query_selector("[data-resolved-banner]") is None
    # A later 30 s tick, after the grace: the page's own record still holds.
    time.sleep(3.2)
    server.push({"type": "attention", "state": "needs-you", "counts": {}, "ids": [ID_HOST]})
    time.sleep(0.8)
    assert page.query_selector("[data-resolved-banner]") is None


# ------------------------------------------------------------- finding 5


def test_enter_on_a_focused_control_does_not_reload_the_workspace(page, server):
    """§3.6: Enter opens from the list; a focused control elsewhere does
    its own thing. Mutation: click the selected list link whatever has
    focus -> red."""
    _open(page, server, ID_OO7)
    seen: list[str] = []
    page.on("request", lambda r: seen.append(r.url))
    workspace = f"/inbox/{ID_OO7}/workspace"
    # Positive control: with nothing focused, Enter opens the selected item.
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Enter")
    _wait_for(lambda: any(workspace in u for u in seen))
    page.wait_for_selector(f'#ws[data-item-id="{ID_OO7}"] #ws-packet summary', timeout=_WAIT_MS)
    time.sleep(0.3)
    seen.clear()
    summary = page.locator("#ws-packet details summary").first
    was_open = page.evaluate("document.querySelector('#ws-packet details').open")
    summary.focus()
    page.keyboard.press("Enter")
    time.sleep(0.8)
    assert not any(workspace in u for u in seen), seen
    # The control did its own thing: the evidence entry toggled, and stayed so.
    assert page.evaluate("document.querySelector('#ws-packet details').open") is (not was_open)
