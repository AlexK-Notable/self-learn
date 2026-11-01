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
    DRAFT_ID,
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


def _armed_and_wired(page) -> None:
    """The armed bar is in and htmx wired its form (app.js blocks a native
    submit in the swap/settle gap, so a person's next act lands after)."""
    page.wait_for_selector("#ws-answer [data-armed-answer]", timeout=_WAIT_MS)
    page.wait_for_function(
        "() => !!document.querySelector('[data-confirm-armed]').closest('form')['htmx-internal-data']",
        timeout=_WAIT_MS)


def _nothing_sent_for(server, seconds: float = 1.5) -> bool:
    try:
        _wait_for(lambda: bool(_answer_calls(server)), timeout=seconds)
    except AssertionError:
        return True
    return False


def test_a_number_key_arms_an_approve_option_and_never_sends_it(page, server):
    """Walk item 1, gate r1 F1: pressing 1 on "Yes, add the binding" arms
    it and sends nothing; pressing 1 again does nothing (no number key
    confirms); only the Confirm button does, here by Enter with it
    focused. Mutations: drop the `keyed` parameter in inbox.js -> red (the
    key sends the approval at once); let key 1 click the armed Confirm
    (the old rule) -> red."""
    _open(page, server, ID_OO7)
    assert page.get_attribute('#ws-answer [data-option-index="1"]', "data-effect") == "approve"
    page.click("h1")
    page.keyboard.press("1")
    _armed_and_wired(page)
    assert "approves this change" in page.inner_text("[data-armed-answer]")
    assert "Number keys do nothing here" in page.inner_text("[data-armed-answer]")
    assert _answer_calls(server) == []
    page.keyboard.press("1")
    assert _nothing_sent_for(server)
    page.locator("[data-confirm-armed]").focus()
    page.keyboard.press("Enter")
    _wait_for(lambda: bool(_answer_calls(server)))
    argv = _answer_calls(server)[-1]
    assert argv[argv.index("--option") + 1] == "opt-yes"


def test_key_2_then_key_1_approves_nothing(page, server):
    """Gate r1 F1 (the gate's probe): with two approve options, 2 arms the
    second; then 1, which the hints say means the first, approves neither.
    Mutation: let key 1 click the armed Confirm (the old rule) -> red (the
    second option is approved)."""
    two = _item("att-0000000000c3", "ask.system-change", "system-change", "Pick one", (
        _opt("opt-a", "Yes, the small change", "approve", recommended=True),
        _opt("opt-b", "Yes, the big change", "approve")))
    server.state.doc = _doc(two)
    _open(page, server, "att-0000000000c3")
    page.click("h1")
    page.keyboard.press("2")
    _armed_and_wired(page)
    assert "Yes, the big change" in page.inner_text("[data-armed-answer]")  # control
    page.keyboard.press("1")
    assert _nothing_sent_for(server)
    assert page.locator("#ws-answer [data-armed-answer]").count() == 1


def test_a_held_keys_auto_repeat_never_acts(page, server):
    """Gate r1 F1 (the gate's probe): one press held down. Its auto-repeat
    keydowns (`event.repeat`) never act: not on the armed bar, and not on
    an option that would send at once. Mutations: let key 1 confirm the
    armed bar -> red; drop the `event.repeat` check -> red (the repeat of
    3 sends the decline)."""
    _open(page, server, ID_OO7)
    page.click("h1")
    repeat = "(k) => document.dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true, repeat: true}))"
    page.evaluate(repeat, "3")
    assert _nothing_sent_for(server)
    page.keyboard.press("1")
    _armed_and_wired(page)
    page.evaluate(repeat, "1")
    assert _nothing_sent_for(server)
    page.locator("#ws-answer [data-armed-cancel]").click()
    page.wait_for_selector('#ws-answer [data-option-index="3"]', timeout=_WAIT_MS)
    page.wait_for_function("() => !!document.querySelector('#ws-answer-form')['htmx-internal-data']",
                           timeout=_WAIT_MS)
    page.click("h1")
    page.keyboard.press("3")  # control: a real press of 3 sends the decline
    _wait_for(lambda: bool(_answer_calls(server)))
    argv = _answer_calls(server)[-1]
    assert argv[argv.index("--option") + 1] == "opt-no"


def test_ctrl_enter_on_a_draft_carrying_an_approve_option_arms_it(page, server):
    """Gate r1 F2 (the gate's probe): "Use this draft" on a draft whose
    option approves, then Ctrl+Enter in the box: the page arms it and asks
    once more; nothing is sent until Confirm. A mouse click on Send arms
    the same way (the person never clicked a button naming the approval),
    in words that say sending the draft approves. Mutations: drop
    `from_draft` in inbox.js -> red (the mouse Send sends at once); drop
    the key mark on Ctrl+Enter -> red (the bar does not say a key was
    pressed); both together (the gate's code) -> red."""
    _open(page, server, ID_OO7)
    page.click(f'[data-draft-card][data-draft-id="{DRAFT_ID}"] [data-use-draft]')
    _wait_for(lambda: page.get_attribute("#ws-answer-form", "data-draft-option") == "opt-yes-conditions")
    page.click("[data-send-reply]")
    _armed_and_wired(page)
    assert "Sending a draft never approves on its own" in page.inner_text("[data-armed-answer]")
    assert _nothing_sent_for(server)
    page.click("#ws-answer [data-armed-cancel]")
    _wait_for(lambda: page.get_attribute("#ws-answer-form", "data-draft-option") == "opt-yes-conditions")
    page.wait_for_function("() => !!document.querySelector('#ws-answer-form')['htmx-internal-data']",
                           timeout=_WAIT_MS)
    page.locator("#ws-reply-text").focus()
    page.keyboard.press("Control+Enter")
    _armed_and_wired(page)
    assert "Yes, with conditions" in page.inner_text("[data-armed-answer]")
    assert "a key never approves on its own" in page.inner_text("[data-armed-answer]")
    assert _nothing_sent_for(server)
    page.locator("[data-confirm-armed]").click()
    _wait_for(lambda: bool(_answer_calls(server)))
    argv = _answer_calls(server)[-1]
    assert argv[argv.index("--option") + 1] == "opt-yes-conditions"
    assert argv[argv.index("--draft") + 1] == DRAFT_ID


_BAD_FOCUS = """
window.__badFocus = [];
document.addEventListener('focusin', function (e) {
  var t = e.target;
  if (t && t.matches && t.matches('[data-effect="approve"], [data-effect="register"], [data-confirm-armed]'))
    window.__badFocus.push(t.outerHTML.slice(0, 120));
}, true);
"""


def test_the_page_never_moves_focus_onto_an_approve_button(page, server):
    """Gate r1 F3 (the orchestrator's ruling): Enter or Space on a focused
    approve button stays a click, so the page itself never puts focus on
    one: not on load, not after "Use this draft" (the box), not after
    arming (Cancel), not after an answer. No key presses Tab here, so any
    focus on such a button is the page's own. Mutation: focus the armed
    Confirm instead of Cancel -> red."""
    page.add_init_script(_BAD_FOCUS)
    _open(page, server, ID_OO7)
    page.click(f'[data-draft-card][data-draft-id="{DRAFT_ID}"] [data-use-draft]')
    assert page.evaluate("() => document.activeElement.id") == "ws-reply-text"
    page.keyboard.press("Control+Enter")
    _armed_and_wired(page)
    _wait_for(lambda: page.evaluate(
        "() => document.activeElement.hasAttribute('data-armed-cancel')"))
    page.keyboard.press("Enter")  # on Cancel: backs out, approves nothing
    page.wait_for_selector('#ws-answer [data-option-index="1"]', timeout=_WAIT_MS)
    page.wait_for_function("() => !!document.querySelector('#ws-answer-form')['htmx-internal-data']",
                           timeout=_WAIT_MS)
    page.click("h1")
    page.keyboard.press("1")
    _armed_and_wired(page)
    _wait_for(lambda: page.evaluate(
        "() => document.activeElement.hasAttribute('data-armed-cancel')"))
    page.keyboard.press("Space")
    page.wait_for_selector('#ws-answer [data-option-index="3"]', timeout=_WAIT_MS)
    page.wait_for_function("() => !!document.querySelector('#ws-answer-form')['htmx-internal-data']",
                           timeout=_WAIT_MS)
    page.click("h1")
    page.keyboard.press("3")
    page.wait_for_selector("#ws-answer [data-recorded]", timeout=_WAIT_MS)
    assert _answer_calls(server)[-1][4] == "opt-no"  # control: only the decline was sent
    assert len(_answer_calls(server)) == 1
    assert page.evaluate("() => window.__badFocus") == []


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


def _paste_agent_words_before_the_turn_is_sealed(page, server):
    _open(page, server, ID_OO7)
    page.locator("#ws-reply-text").focus()
    page.keyboard.type("Fine by me. " + AGENT_ANSWER[:50])
    _wait_line(page, "Sending this records it as your words.")  # control: not sealed yet


def test_the_provenance_line_is_asked_again_when_an_ask_turn_ends(page, server, monkeypatch):
    """Gate r1 F5: words copied from the agent's answer while it streams
    read "as your words" (the turn is not sealed); once the turn ends and
    is sealed the line is asked again and says the agent's draft, as the
    recorder will. Mutation: drop the re-check in the ask `end` handler ->
    red."""
    _paste_agent_words_before_the_turn_is_sealed(page, server)
    monkeypatch.setattr(base, "OO7_ROWS", [*base.OO7_ROWS, {
        "t": 3, "role": "agent", "origin": "agent", "kind": "answer", "text": AGENT_ANSWER}])
    page.evaluate("(id) => document.dispatchEvent(new CustomEvent('self-learn:sse', "
                  "{detail: {type: 'ask', ev: 'end', item: id, exit: 0}}))", ID_OO7)
    _wait_line(page, "as the agent's draft, edited and sent by you, not as your words")


def test_the_provenance_line_is_asked_again_when_the_item_changes(page, server, monkeypatch):
    """Gate r1 F5: an attention event (the agent texts the rule reads may
    have changed) asks the line again while the box holds text. Mutation:
    drop the re-check on attention events -> red."""
    _paste_agent_words_before_the_turn_is_sealed(page, server)
    monkeypatch.setattr(base, "OO7_ROWS", [*base.OO7_ROWS, {
        "t": 3, "role": "agent", "origin": "agent", "kind": "answer", "text": AGENT_ANSWER}])
    page.evaluate("(id) => document.dispatchEvent(new CustomEvent('self-learn:sse', "
                  "{detail: {type: 'attention', ids: []}}))", ID_OO7)
    _wait_line(page, "as the agent's draft, edited and sent by you, not as your words")


# ------------------------------------------------------------ item 7


def test_send_records_after_a_request_that_did_not_redraw_the_bar(page, server):
    """Walk item 7: after "Start it in a new terminal" (a POST .../run that
    only fills its own result box) the bar must not stay busy: the Send
    click records. Before the fix every button stayed aria-disabled and
    "Recording..." stayed under the box, and the walker's Send click
    recorded nothing. Mutation: the pre-fix code (busy for every
    request inside the bar AND no cleanup after a request) -> red. Each
    half alone is pinned by the two tests below (gate r1 F6: J4a, J4b)."""
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


def _approved_run_item(server) -> None:
    approved = {**_item(ID_RUN, "approved.pending", None, "Add the safe-update list",
                        (_opt("opt-no", "No, keep asking", "decline"),)),
                "class": "approved", "state": "approved"}
    server.state.doc = _doc(approved)


def test_a_request_that_does_not_redraw_the_bar_never_marks_it_busy(page, server):
    """Gate r1 F6 (J4a): while "Start it in a new terminal" is in flight,
    no button in the bar is aria-disabled and the line never says
    "Recording...". Mutation: mark the bar busy for every request inside
    it -> red."""
    _approved_run_item(server)
    _open(page, server, ID_RUN)
    held = []
    page.route("**/run", lambda route: held.append(route))
    page.click("[data-run-now]")
    _wait_for(lambda: bool(held))
    try:
        assert page.locator("#ws-answer [data-send-reply]").count() == 1  # control
        assert page.locator("#ws-answer [aria-disabled]").count() == 0
        assert "Recording" not in (page.text_content("#ws-reply-line") or "")
    finally:
        held[0].continue_()


def test_a_bar_request_that_fails_without_a_redraw_leaves_it_live(page, server):
    """Gate r1 F6 (J4b): a Send whose answer never comes back as a bar (a
    server error htmx does not swap) leaves no aria-disabled button and no
    "Recording..." behind. Mutation: drop the afterRequest cleanup -> red."""
    _open(page, server, ID_OO7)
    page.route("**/answer", lambda route: route.fulfill(status=500, body="boom"))
    page.fill("#ws-reply-text", "My own words.")
    with page.expect_response("**/answer"):
        page.click("[data-send-reply]")
    _wait_for(lambda: page.locator("#ws-answer [aria-disabled]").count() == 0)
    assert page.locator("#ws-answer [data-send-reply]").count() == 1  # control
    assert "Recording" not in (page.text_content("#ws-reply-line") or "")


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


# ------------------------------------------------------------ gate r2 N1


def test_with_storage_blocked_a_draft_send_after_a_failed_confirm_still_arms(page, server):
    """Gate r2 N1 (the gate's probe P9): site storage throws (a private
    window, blocked site data). Use this draft, Send, Confirm; the verb
    refuses; the bar comes back with the draft id but no option (the page
    could not remember it). A second Send must still arm, and its Confirm
    sends `--confirm`. Mutation: drop the server's read of the draft's
    option -> red (the second Send goes straight to the verb)."""
    from test_js_inbox import RunResult

    page.add_init_script(
        "Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked'); }});")
    _open(page, server, ID_OO7)
    page.click(f'[data-draft-card][data-draft-id="{DRAFT_ID}"] [data-use-draft]')
    _wait_for(lambda: page.get_attribute("#ws-answer-form", "data-draft-option") == "opt-yes-conditions")
    page.click("[data-send-reply]")
    _armed_and_wired(page)
    server.runner.queue_result(RunResult(3, stderr="refused for this test"))
    page.click("[data-confirm-armed]")
    page.wait_for_selector("#ws-answer [data-answer-error]", timeout=_WAIT_MS)
    first = list(_answer_calls(server))
    assert len(first) == 1 and "--confirm" in first[0]  # the confirm went with --confirm
    assert page.input_value("#ws-reply-draft") == DRAFT_ID  # control: the draft id is kept
    assert page.get_attribute("#ws-answer-form", "data-draft-option") is None  # the option is lost
    page.wait_for_function("() => !!document.querySelector('#ws-answer-form')['htmx-internal-data']",
                           timeout=_WAIT_MS)
    page.click("[data-send-reply]")
    _armed_and_wired(page)
    assert "Yes, with conditions" in page.inner_text("[data-armed-answer]")
    try:
        _wait_for(lambda: len(_answer_calls(server)) > 1, timeout=1.5)
    except AssertionError:
        pass
    assert len(_answer_calls(server)) == 1  # the second Send sent nothing
    page.click("[data-confirm-armed]")
    _wait_for(lambda: len(_answer_calls(server)) == 2)
    argv = _answer_calls(server)[-1]
    assert argv[argv.index("--option") + 1] == "opt-yes-conditions" and "--confirm" in argv
