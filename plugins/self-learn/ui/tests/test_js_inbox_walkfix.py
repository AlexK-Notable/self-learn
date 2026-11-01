"""The inbox's walk fixes in a real browser (S-NEXT-walkfix; the
source-blind walk of 2026-11-01, misc/build-2026-10-31c/walk-attention.md).

Keys, the live provenance line, the busy state a non-answer request left
behind, the seen mark, the title block, and the login result: orderings and
page behaviour, so each is driven through the real served inbox page in a
real Chromium, with test_js_inbox.py's in-process server (page reads
monkeypatched, verbs to a FakeRunner whose argv are read back).

Each test names the mutation it was checked against.
"""

from __future__ import annotations

import pytest

import test_js_inbox as base
from test_js_inbox import (  # noqa: F401 -- fixtures: server, browser, page
    ID_OO7,
    _answer_calls,
    _doc,
    _item,
    _open,
    _opt,
    _wait_for,
    _wait_line,
    browser,
    page,
    server,
)

pytestmark = pytest.mark.js

ID_RUN = "att-0000000000f7"
ID_NEW = "att-0000000000a8"
ID_LOGIN = "att-0000000000a9"
_WAIT_MS = 10000


def _calls(server, verb: str) -> list[list[str]]:
    return [c for c in server.runner.calls if c[:2] == ["attention", verb]]


# ------------------------------------------------------------ item 1


def test_a_number_key_arms_an_approve_option_and_never_sends_it(page, server):
    """Walk item 1: pressing 1 on "Yes, add the binding" arms it (the
    once-more confirmation) and sends nothing; pressing 1 again confirms.
    Mutation: drop the `keyed` parameter in inbox.js -> red (the key
    sends the approval at once)."""
    _open(page, server, ID_OO7)
    assert page.get_attribute('#ws-answer [data-option-index="1"]', "data-effect") == "approve"
    page.click("h1")
    page.keyboard.press("1")
    page.wait_for_selector("#ws-answer [data-armed-answer]", timeout=_WAIT_MS)
    assert "approves this change" in page.inner_text("[data-armed-answer]")
    assert _answer_calls(server) == []
    # As a person would: the confirm is pressed after htmx wired the swapped
    # form (app.js blocks a native submit in the swap/settle gap).
    page.wait_for_function(
        "() => !!document.querySelector('[data-confirm-armed]').closest('form')['htmx-internal-data']",
        timeout=_WAIT_MS)
    page.keyboard.press("1")
    _wait_for(lambda: bool(_answer_calls(server)))
    argv = _answer_calls(server)[-1]
    assert argv[argv.index("--option") + 1] == "opt-yes"


def test_a_number_key_on_a_decline_option_sends_it(page, server):
    """Only approve and register arm. Mutation: arm every keyed option ->
    red."""
    _open(page, server, ID_OO7)
    page.click("h1")
    page.keyboard.press("3")
    _wait_for(lambda: bool(_answer_calls(server)))
    argv = _answer_calls(server)[-1]
    assert argv[argv.index("--option") + 1] == "opt-no"


# ------------------------------------------------------------ item 2


AGENT_ANSWER = ("A bus restart kills the daemon today and an agent restarts it by hand every "
                "single time it happens.")


def test_the_provenance_line_follows_the_box_by_the_verbs_rule(page, server, monkeypatch):
    """Walk item 2, step 6: own words read "as your words"; once the box
    holds 40 characters of the agent's answer the one line says the
    agent's draft, edited, and quotes them; while the server has not
    answered it claims nothing. Mutations: drop the input listener's
    askProvenance -> red; show the old line until the answer arrives (no
    "Checking") -> red."""
    rows = [*base.OO7_ROWS, {"t": 3, "role": "agent", "origin": "agent", "kind": "answer",
                             "text": AGENT_ANSWER}]
    monkeypatch.setattr(base, "OO7_ROWS", rows)
    _open(page, server, ID_OO7)
    assert page.locator("[data-provenance-line]").count() == 1
    page.locator("#ws-reply-text").focus()
    page.keyboard.type("Both hold; ask me only when it needs me.")
    assert "Checking how this would be recorded" in page.text_content("#ws-reply-line")
    _wait_line(page, "Sending this records it as your words.")
    page.keyboard.type(" " + AGENT_ANSWER[:50])
    _wait_line(page, "as the agent's draft, edited and sent by you, not as your words")
    assert AGENT_ANSWER[:40] in page.text_content("#ws-reply-line")
    assert page.locator("[data-provenance-line]").count() == 1
    assert page.locator("#ws-reply-draft-note").count() == 0


# ------------------------------------------------------------ item 7


def test_send_records_after_a_request_that_did_not_redraw_the_bar(page, server):
    """Walk item 7: after "Start it in a new terminal" (a POST .../run that
    only fills its own result box) the bar must not stay busy: the Send
    click records. Before the fix every button stayed aria-disabled and
    "Recording..." stayed under the box, and the walker's Send click
    recorded nothing. Mutation: mark the bar busy for every request inside
    it (the old rule) -> red."""
    approved = {**_item(ID_RUN, "approved.pending", None, "Add the safe-update list",
                        (_opt("opt-no", "No, keep asking", "decline"),)),
                "class": "approved", "state": "approved"}
    server.state.doc = _doc(approved)
    _open(page, server, ID_RUN)
    page.click("[data-run-now]")
    _wait_for(lambda: bool(_calls(server, "run")))
    page.wait_for_function("() => !document.querySelector('#ws-answer [aria-disabled]')",
                           timeout=_WAIT_MS)
    assert "Recording" not in page.text_content("#ws-reply-line")
    page.fill("#ws-reply-text", "Please keep my desktop session up.")
    page.click("[data-send-reply]", timeout=_WAIT_MS)
    _wait_for(lambda: bool(_answer_calls(server)))
    assert "--text-file" in _answer_calls(server)[-1]


# ------------------------------------------------------------ item 8


def test_the_new_mark_leaves_the_header_and_the_list_together(page, server):
    """Walk item 8: once the seen click is recorded, the "new" mark goes
    from the page header and from the item's list row. Mutation: drop
    dropNewMarks -> red (the header keeps "new")."""
    fresh = {**_item(ID_NEW, "decided.overseer-run", "decided", "The overseer's weekly run", ()),
             "class": "decided", "state": "done", "flagged": True, "seen": False}
    server.state.doc = _doc(fresh)
    page.goto(f"{server.base_url}/inbox/{ID_NEW}", wait_until="load")
    page.wait_for_selector(f'#ws[data-item-id="{ID_NEW}"]')
    assert page.locator("#ws [data-new-mark]").count() == 1  # control: both marked
    assert page.locator(f'#inbox-list [data-inbox-item="{ID_NEW}"] .dot-new').count() == 1
    _wait_for(lambda: bool(_calls(server, "seen")))
    _wait_for(lambda: page.locator("#ws [data-new-mark]").count() == 0)
    assert page.locator(f'#inbox-list [data-inbox-item="{ID_NEW}"] .dot-new').count() == 0


def test_the_title_block_never_covers_the_section_scrolled_under_it(page, server):
    """Walk item 8: the workspace's <header> matched the page-wide sticky
    header rule and covered the first line scrolled under it. A section
    scrolled into view is the topmost element at its own first line.
    Mutation: drop the `header.ws-head` rule -> red."""
    _open(page, server, ID_OO7)
    page.set_viewport_size({"width": 1440, "height": 500})
    hit = page.evaluate("""() => {
        const h = document.querySelector('#ws-evidence-h');
        h.closest('section').scrollIntoView({block: 'start'});
        const r = h.getBoundingClientRect();
        const at = document.elementFromPoint(r.left + 4, r.top + 4);
        return {sticky: getComputedStyle(document.querySelector('.ws-head')).position,
                scrolled: window.scrollY > 0, own: !!at && h.contains(at)};
    }""")
    assert hit["scrolled"]  # control: the page did scroll
    assert hit["sticky"] != "sticky" and hit["own"]


# ------------------------------------------------------------ item 4


def test_a_working_login_shows_its_result_at_the_top_in_view(page, server):
    """Walk item 4: "Check now" that works puts "This item is closed" at
    the top of the page and brings it into view, and the ask panel's note
    changes. Mutation: drop the out-of-band banner -> red; drop the
    oobAfterSwap scroll -> red (the banner is above the viewport)."""
    login = _item(ID_LOGIN, "hold.credentials", "credentials", "Log in to Claude", (
        _opt("opt-login", "Open a login terminal", via="run --login", recommended=True),
        _opt("opt-check", "Check now", via="check-login")))
    server.state.doc = _doc(login)
    page.set_viewport_size({"width": 1440, "height": 400})
    _open(page, server, ID_LOGIN)
    page.locator('#ws-answer button:has-text("Check now")').scroll_into_view_if_needed()
    assert page.evaluate("() => window.scrollY") > 0  # control: the button is below the top
    page.click('#ws-answer button:has-text("Check now")')
    page.wait_for_selector("#ws-top-result [data-login-fixed]", timeout=_WAIT_MS)
    assert "This item is closed." in page.inner_text("#ws-top-result")
    top = page.evaluate("() => document.querySelector('#ws-top-result').getBoundingClientRect().top")
    assert 0 <= top < 400
    assert "this item is closed" in page.inner_text("#ws-ask-off")
