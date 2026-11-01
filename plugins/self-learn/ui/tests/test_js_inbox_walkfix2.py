"""The inbox after a second source-blind walk, in a real browser (walk 2
of 2026-11-01, misc/build-2026-11-01/walk2-attention.md; decisions D1,
D2, D4, D7).

Keys that only arm, Escape on an armed panel, Tab from Cancel to
Confirm, a held key, and results brought into view at 1440x900: page
behaviour, so each is driven through the real served inbox page in a real
Chromium with test_js_inbox.py's in-process server (page reads
monkeypatched, verbs to a FakeRunner whose argv are read back).

Each test names the mutation it was checked against.
"""

from __future__ import annotations

import pytest

import test_js_inbox as base
from test_js_inbox import (  # noqa: F401 -- fixtures: server, browser, page
    ID_HOOK,
    ID_HOST,
    ID_OO7,
    _answer_calls,
    _open,
    _wait_for,
    browser,
    page,
    server,
)

pytestmark = pytest.mark.js

_WAIT_MS = 10000


def _calls(server, *head: str) -> list[list[str]]:
    return [c for c in server.runner.calls if c[:len(head)] == list(head)]


def _quiet(server, head: tuple[str, ...], seconds: float = 1.5) -> bool:
    try:
        _wait_for(lambda: bool(_calls(server, *head)), timeout=seconds)
    except AssertionError:
        return True
    return False


def _focused(page, attribute: str) -> bool:
    return page.evaluate("(a) => !!document.activeElement && document.activeElement.hasAttribute(a)",
                         attribute)


def test_u_arms_the_undo_and_escape_cancels_it(page, server):
    """D2: `u` only arms the undo (a keyed undo answers with its armed
    panel, focus on Cancel); a held `u` does nothing more; D4: Escape
    cancels the armed panel and the undo button is back, with nothing
    sent. Mutations: `u` clicks the undo without `keyed` (the old rule)
    -> red (this kind's undo is sent at once); Escape no longer cancels
    an armed panel -> red."""
    _open(page, server, ID_HOOK)
    page.click("h1")
    page.keyboard.press("u")
    page.wait_for_selector("#ws-answer [data-armed-undo]", timeout=_WAIT_MS)
    assert "a key never acts on its own" in page.inner_text("[data-armed-undo]")
    _wait_for(lambda: _focused(page, "data-armed-cancel"))
    page.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', "
                  "{key: 'u', bubbles: true, repeat: true}))")
    assert _quiet(server, ("attention", "undo"))
    page.keyboard.press("Escape")
    page.wait_for_selector("#ws-answer [data-undo]", timeout=_WAIT_MS)
    assert page.locator("#ws-answer [data-armed-undo]").count() == 0
    assert _calls(server, "attention", "undo") == []


def test_s_arms_mark_all_seen_and_tab_then_enter_confirms_it(page, server):
    """D2, D4: `s` arms Mark all seen on the page (the same panel and
    words as every armed panel), nothing is sent; Tab from the focused
    Cancel reaches Confirm and Enter sends it. Mutations: `s` clicks Mark
    all seen (the old rule) -> red; the local panel puts Confirm before
    Cancel -> red."""
    _open(page, server, ID_HOOK)
    page.click("h1")
    page.keyboard.press("s")
    page.wait_for_selector("[data-armed-local]", timeout=_WAIT_MS)
    panel = page.inner_text("[data-armed-local]")
    assert "Mark all seen" in panel and "It marks every decided item as seen" in panel
    assert "press Tab to reach Confirm, then Enter" in panel
    assert _quiet(server, ("attention", "seen", "--all-decided"))
    assert _focused(page, "data-armed-cancel")
    page.keyboard.press("Tab")
    assert _focused(page, "data-confirm-armed")
    page.keyboard.press("Enter")
    _wait_for(lambda: bool(_calls(server, "attention", "seen", "--all-decided")))


def test_a_key_on_a_fix_option_arms_it_on_the_page(page, server):
    """D2: a number key on an option the server would run at once (a fix
    here) arms it on the page, saying what it does; only Confirm runs it.
    Mutation: number keys click `data-arm="local"` options (the old rule)
    -> red."""
    _open(page, server, ID_HOST)
    page.click("h1")
    page.keyboard.press("1")
    page.wait_for_selector("[data-armed-local]", timeout=_WAIT_MS)
    assert "Restart self-learn" in page.inner_text("[data-armed-local]")
    assert _quiet(server, ("attention", "fix"))
    page.keyboard.press("2")  # number keys do nothing on an armed panel
    page.click("[data-armed-local] [data-confirm-armed]")
    _wait_for(lambda: bool(_calls(server, "attention", "fix")))
    assert _calls(server, "attention", "fix")[-1][-2:] == ["--option", "opt-restart"]


def test_escape_cancels_a_server_armed_answer(page, server):
    """D4: Escape on an armed answer goes back to the options; nothing is
    sent. Mutation: drop the Escape branch for armed panels -> red."""
    _open(page, server, ID_OO7)
    page.click("h1")
    page.keyboard.press("1")
    page.wait_for_selector("#ws-answer [data-armed-answer]", timeout=_WAIT_MS)
    page.wait_for_function("() => !!document.querySelector('[data-armed-cancel]')"
                           ".closest('form')['htmx-internal-data']", timeout=_WAIT_MS)
    page.keyboard.press("Escape")
    page.wait_for_selector('#ws-answer [data-option-index="1"]', timeout=_WAIT_MS)
    assert page.locator("#ws-answer [data-armed-answer]").count() == 0
    assert _answer_calls(server) == []


def test_a_click_on_an_approve_option_arms_with_focus_on_cancel(page, server):
    """D1: a mouse click on "Yes, add the binding" asks once more; the page
    puts focus on Cancel (S-130's rule), never on Confirm. Mutation: send
    an approve click at once (the old rule) -> red."""
    _open(page, server, ID_OO7)
    page.click('#ws-answer [data-option-index="1"]')
    page.wait_for_selector("#ws-answer [data-armed-answer]", timeout=_WAIT_MS)
    _wait_for(lambda: _focused(page, "data-armed-cancel"))
    assert _answer_calls(server) == []


def test_ctrl_enter_never_settles_and_a_held_one_never_sends(page, server):
    """D2: words on an item with no plan answer it, so Ctrl+Enter arms
    them ("Send your words?"); a held Ctrl+Enter's auto-repeat sends
    nothing. Mutations: drop the keyed arm for words that settle -> red;
    drop the repeat check on Ctrl+Enter -> red."""
    _open(page, server, ID_HOST)
    page.fill("#ws-reply-text", "Restart it only after the nightly mine.")
    page.focus("#ws-reply-text")
    page.evaluate("() => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', "
                  "{key: 'Enter', ctrlKey: true, bubbles: true, repeat: true}))")
    assert _quiet(server, ("attention", "answer"))
    assert page.locator("#ws-answer [data-armed-answer]").count() == 0  # nothing happened
    page.keyboard.press("Control+Enter")
    page.wait_for_selector("#ws-answer [data-armed-answer]", timeout=_WAIT_MS)
    assert "Send your words?" in page.inner_text("[data-armed-answer]")
    assert _answer_calls(server) == []


def test_the_receipt_is_brought_into_view_at_1440x900(page, server, monkeypatch):
    """D7: at 1440x900 the answer bar sits below the fold on an item with
    a plan and evidence. Arm "No" by its key (the panel takes focus, so it
    is in view), Tab to Confirm, then look back at the top of the page
    (scroll up) and press Enter: the receipt is brought into view where
    the person is looking. Mutation: drop the scroll of the swapped answer
    bar's result -> red (the receipt stays below the fold)."""
    tall = {**base.OO7_PACKET, "evidence": [
        {"kind": "lesson", "id": f"lrn-9b4250{n:02d}", "title": f"Lesson {n}",
         "text": "After a bus restart, restart oo7-daemon. " * 6, "status": "routed",
         "placement": "user"} for n in range(14)]}
    monkeypatch.setattr(base, "OO7_PACKET", tall)
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, server, ID_OO7)
    top = page.evaluate("() => document.querySelector('#ws-answer').getBoundingClientRect().top")
    assert top > 900  # control: the answer bar starts below the fold
    page.click("h1")
    page.keyboard.press("3")
    page.wait_for_selector("#ws-answer [data-armed-answer]", timeout=_WAIT_MS)
    page.wait_for_function("() => !!document.querySelector('[data-confirm-armed]')"
                           ".closest('form')['htmx-internal-data']", timeout=_WAIT_MS)
    page.keyboard.press("Tab")
    assert _focused(page, "data-confirm-armed")
    page.evaluate("() => window.scrollTo(0, 0)")
    page.keyboard.press("Enter")
    page.wait_for_selector("#ws-answer [data-recorded]", timeout=_WAIT_MS)
    _wait_for(lambda: 0 <= page.evaluate(
        "() => document.querySelector('#ws-answer [data-recorded]').getBoundingClientRect().top")
        < 900, timeout=3.0)
