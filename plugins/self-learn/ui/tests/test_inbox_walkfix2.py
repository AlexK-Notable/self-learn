"""The inbox after a second source-blind walk, server side (walk 2 of
2026-11-01, misc/build-2026-11-01/walk2-attention.md; the orchestrator's
decisions D1-D7, which revise design r2 §0 call 3 and S-130).

As in test_inbox.py: page reads (`ledger.attention`,
`ledger.attention_packet`, `ledger.workspace_rows`, and here
`ledger.answered_item`) are monkeypatched; `FakeRunner` carries verb
invocations only. Every absence assertion is preceded by a positive
control that the region it looks in rendered. Each test names the
mutation it was checked against.
"""

from __future__ import annotations

import json

import markupsafe

from self_learn_ui import keymap, ledger
from self_learn_ui.runner import FakeRunner, RunResult

from test_inbox import (  # noqa: F401 -- person is an autouse fixture
    APPROVED,
    HOOK,
    HOOK_PACKET,
    HX,
    ID_APPROVED,
    ID_HOOK,
    ID_HOST,
    ID_LOGIN,
    ID_OO7,
    ID_REGISTER,
    ID_SUDO,
    HOST,
    LOGIN,
    OO7,
    OO7_PACKET,
    REGISTER,
    SUDO,
    Reads,
    _doc,
    _item,
    _opt,
    make_client,
    person,
)

ID_CONFLICT = "att-000000000129"
ID_WITHDRAWN = "att-00000000013a"
CONFLICT = _item(ID_CONFLICT, "ask.conflict", "needs-you", "conflict",
                 "Two things you said about being asked disagree", options=(
                     _opt("opt-newer", "The newer one is right"),
                     _opt("opt-older", "The older one is right"),
                     _opt("opt-both", "Both: here is how they fit", note="required")))
WITHDRAWN = _item(ID_WITHDRAWN, "decided.withdrawn", "decided", None, "A question was withdrawn",
                  undo={"label": "Ask me anyway", "redo_label": None, "redo": False})
_UNCLAIMED = {**APPROVED, "state": "running",
              "run": {"unit": "self-learn-run-000000000107", "at": "2026-11-01T10:00:00Z",
                      "claimed_by": None},
              "options": [_opt("opt-no", "No, keep the manual note", "decline")]}


def _ok(state: str, recorded_as: str, **extra) -> RunResult:
    return RunResult(0, stdout=json.dumps({"state": state, "recorded_as": recorded_as, **extra}))


def _bar(page: str) -> str:
    start = page.index('id="ws-answer"')
    return page[start: page.index("</section>", start)]


def _words(text: str) -> str:
    return str(markupsafe.Markup(text).unescape())


def _answers(runner) -> list[list[str]]:
    return [c for c in runner.calls if c[:2] == ["attention", "answer"]]


def _no_answered(monkeypatch, found=None):
    calls: list[dict] = []

    def answered(home, *, item_id=None, subject=None):
        calls.append({"item_id": item_id, "subject": subject})
        return found(item_id, subject) if callable(found) else found

    monkeypatch.setattr(ledger, "answered_item", answered)
    return calls


# ------------------------------------------------------------ D1


def test_consequential_answers_ask_once_more_even_on_a_mouse_click(tmp_path, monkeypatch):
    """D1: approve, register, and withdrawing approved work arm on a plain
    click (no `keyed`), each in words saying what will happen; ordinary
    answers (a plain No on an item, a conflict side) are one click.
    Mutations: send approve clicks at once (the old rule) -> red; drop
    the approved-work branch of `consequential` -> red; arm every click ->
    red."""
    _no_answered(monkeypatch)
    runner = FakeRunner(_ok("answered", "as your choice of the offered option"))
    reads = Reads(_doc(OO7, REGISTER, _UNCLAIMED, CONFLICT), {ID_OO7: OO7_PACKET})
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)

    approve = _words(client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes"},
                                 headers=HX).text)
    assert "data-armed-answer" in approve
    assert "“Yes, add the binding” approves this change: an agent then carries it out" in approve
    register = client.post(f"/inbox/{ID_REGISTER}/answer", data={"option": "opt-register"},
                           headers=HX).text
    assert "data-armed-answer" in register
    withdraw = _words(client.post(f"/inbox/{ID_APPROVED}/answer", data={"option": "opt-no"},
                                  headers=HX).text)
    assert "data-armed-answer" in withdraw
    assert "withdraws your approval: nothing will be carried out" in withdraw
    assert _answers(runner) == []

    plain_no = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-no"}, headers=HX)
    assert "data-recorded" in plain_no.text and "data-armed-answer" not in plain_no.text
    side = client.post(f"/inbox/{ID_CONFLICT}/answer", data={"option": "opt-newer"}, headers=HX)
    assert "data-recorded" in side.text and "data-armed-answer" not in side.text
    assert [c[4] for c in _answers(runner)] == ["opt-no", "opt-newer"]


def test_an_approval_with_a_note_quotes_the_note_before_it_is_sent(tmp_path, monkeypatch):
    """D1 (walk 2 #036: "my words not quoted back"): the armed approval
    quotes the note that goes with it, and the panel's provenance line
    says how it would be recorded. Mutation: drop the note from
    `arm_line` -> red."""
    runner = FakeRunner()
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                             runner=runner)
    resp = _words(client.post(f"/inbox/{ID_OO7}/answer",
                              data={"option": "opt-yes-conditions", "text": "Leave the .d folder alone."},
                              headers=HX).text)
    assert "data-armed-answer" in resp  # control
    assert "Your note goes with it: “Leave the .d folder alone.”" in resp
    assert "data-armed-provenance" in resp
    assert runner.calls == []


def test_an_undo_that_turns_something_off_asks_once_more_and_a_reopen_does_not(tmp_path, monkeypatch):
    """D1: the hook's "Turn it off" (and "Turn it back on") arm on a click,
    saying what they do; the panel's Confirm runs the verb. A withdrawn
    ask's "Ask me anyway" only puts a question back: one click.
    Mutations: drop `undo_arms` -> red; arm every undo click -> red."""
    runner = FakeRunner(RunResult(0, stdout="attention undo: done"))
    reads = Reads(_doc(HOOK, WITHDRAWN), {ID_HOOK: HOOK_PACKET})
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)

    off = _words(client.post(f"/inbox/{ID_HOOK}/undo", headers=HX).text)
    assert "data-armed-undo" in off  # control: the armed panel rendered
    assert "“Turn it off” turns the hook off: it no longer runs in new Claude Code sessions." in off
    on = _words(client.post(f"/inbox/{ID_HOOK}/undo", data={"redo": "1"}, headers=HX).text)
    assert "“Turn it back on” turns the hook back on" in on
    assert 'hx-vals=\'{"confirm": "1", "redo": "1"}\'' in on
    assert [c for c in runner.calls if c[:2] == ["attention", "undo"]] == []

    client.post(f"/inbox/{ID_HOOK}/undo", data={"confirm": "1"}, headers=HX)
    reopen = client.post(f"/inbox/{ID_WITHDRAWN}/undo", headers=HX)
    assert "data-armed-undo" not in reopen.text
    assert [c[:3] for c in runner.calls if c[:2] == ["attention", "undo"]] == [
        ["attention", "undo", ID_HOOK], ["attention", "undo", ID_WITHDRAWN]]


# ------------------------------------------------------------ D2


def test_a_key_arms_every_answer_and_words_that_would_settle_the_item(tmp_path, monkeypatch):
    """D2: `keyed=1` arms any option (here a conflict side and "I ran it"),
    words Ctrl+Enter sends that would answer an item without a plan, and
    `u` on any undo (even the reopen a click sends at once); words on an
    item with a plan decide nothing, so Ctrl+Enter sends them. Mutations:
    arm keyed options only when they approve -> red; never arm keyed words
    -> red; arm keyed words on a plan item -> red; ignore `keyed` on undo
    -> red."""
    _no_answered(monkeypatch)
    runner = FakeRunner(_ok("open", "as your words", transcript_row=3))
    reads = Reads(_doc(OO7, CONFLICT, SUDO, WITHDRAWN), {ID_OO7: OO7_PACKET})
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)

    side = _words(client.post(f"/inbox/{ID_CONFLICT}/answer",
                              data={"option": "opt-older", "keyed": "1"}, headers=HX).text)
    assert "data-armed-answer" in side
    assert "“The older one is right”: the older of your two statements holds" in side
    words = _words(client.post(f"/inbox/{ID_CONFLICT}/answer",
                               data={"text": "Ask only when it changes my system.", "keyed": "1"},
                               headers=HX).text)
    assert "data-armed-answer" in words and "Send your words? This settles it" in words
    assert "Confirm: send your words" in words
    ran = client.post(f"/inbox/{ID_SUDO}/answer", data={"option": "opt-ran-sudo", "keyed": "1"},
                      headers=HX).text
    assert "data-armed-answer" in ran and "Confirm: I ran it" in ran
    reopen = client.post(f"/inbox/{ID_WITHDRAWN}/undo", data={"keyed": "1"}, headers=HX).text
    assert "data-armed-undo" in reopen and "a key never acts on its own" in _words(reopen)
    assert runner.calls == []

    plan_words = client.post(f"/inbox/{ID_OO7}/answer",
                             data={"text": "What about my desktop?", "keyed": "1"}, headers=HX)
    assert "data-recorded" in plan_words.text
    assert len(_answers(runner)) == 1


# ------------------------------------------------------------ D3


def test_a_receipt_names_the_decision_what_happens_next_and_offers_a_change(tmp_path, monkeypatch):
    """D3: "You answered “No, keep the manual note”: nothing will be
    changed; the overseer reads this on its next run." The top of the page
    re-reads (chips and Meanwhile, out of band: no longer "Needs you"), and
    while the answer can change the receipt offers "Change my answer",
    which brings back the options of the answered ask (not in the list any
    more), whose next answer runs the verb. Mutations: drop the receipt ->
    red; drop the out-of-band chips -> red; drop the change offer -> red;
    the answer route ignores answered asks -> red (404)."""
    answered_oo7 = {**OO7, "state": "answered"}
    calls = _no_answered(monkeypatch, lambda item_id, subject: answered_oo7
                         if item_id == ID_OO7 else None)
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET})

    class Leaves(FakeRunner):
        async def run(self, argv):
            reads.doc = _doc()
            return await super().run(argv)

    runner = Leaves(_ok("answered", "as your choice of the offered option"))
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-no"}, headers=HX)
    text = _words(resp.text)
    assert "data-recorded" in text  # control
    # The receipt itself (the same sentence also feeds the out-of-band
    # Meanwhile, so it is read from the receipt's own element).
    receipt = text.split("data-receipt>")[1].split("</p>")[0]
    assert ("You answered “No, keep the manual note”: nothing will be changed; the overseer reads "
            "this on its next run.") in receipt
    assert "Recorded as your choice of the offered option." in text
    chips = text.split('id="ws-chips"')[1].split("</p>")[0]
    assert 'hx-swap-oob="true"' in chips and "Answered" in chips and "Needs you" not in chips
    meanwhile = text.split('id="ws-meanwhile"')[1].split("</section>")[0]
    assert 'hx-swap-oob="true"' in meanwhile and "Nothing waits on you here now." in meanwhile
    assert "data-change-answer" in text and f'hx-get="/inbox/{ID_OO7}/change"' in text
    assert {"item_id": ID_OO7, "subject": None} in calls

    change = client.get(f"/inbox/{ID_OO7}/change", headers=HX).text
    assert "data-changing" in change and 'name="option" value="opt-yes"' in change
    again = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes", "confirm": "1"},
                        headers=HX)
    assert again.status_code == 200
    assert [c[4] for c in _answers(runner)] == ["opt-no", "opt-yes"]


def test_an_approval_receipt_says_it_is_being_carried_out_and_where_to_change_it(tmp_path, monkeypatch):
    """D3: an approval's receipt names it and what is happening now; the
    change offer opens the work being carried out (its other options live
    there until a session claims it). Mutation: the receipt's state words
    for a running launch dropped -> red."""
    _no_answered(monkeypatch)
    moved = {**_UNCLAIMED, "subject": OO7["subject"], "title": OO7["title"],
             "meanwhile": "You approved it; an agent carries it out in a terminal you can see."}
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET})

    class Moves(FakeRunner):
        async def run(self, argv):
            reads.doc = _doc(moved)
            return await super().run(argv)

    runner = Moves(_ok("running", "as your choice of the offered option",
                       run={"exit": 0, "message": "Launched in a terminal."}))
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    text = _words(client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes", "confirm": "1"},
                              headers=HX).text)
    assert "data-recorded" in text  # control
    assert ("You approved “Yes, add the binding”: an agent is carrying it out in a terminal you can "
            "see.") in text
    assert f'hx-get="/inbox/{ID_APPROVED}/workspace"' in text.split("data-change-offer")[1]
    chips = text.split('id="ws-chips"')[1].split("</p>")[0]
    assert "Being carried out" in chips
    meanwhile = text.split('id="ws-meanwhile"')[1].split("</section>")[0]
    assert "You approved it; an agent carries it out" in meanwhile


def test_a_conflict_receipt_says_which_statement_now_holds(tmp_path, monkeypatch):
    """D3 (walk 2 #034b: "The result never says which option it recorded"):
    the side the record took, in words. Mutation: one generic receipt for
    every option -> red."""
    _no_answered(monkeypatch)
    runner = FakeRunner(_ok("answered", "as your choice of the offered option"))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(CONFLICT)), runner=runner)
    text = _words(client.post(f"/inbox/{ID_CONFLICT}/answer", data={"option": "opt-newer"},
                              headers=HX).text)
    assert "data-recorded" in text  # control
    assert ("You answered “The newer one is right”: the newer of your two statements holds, and "
            "the cases that relied on the older one are decided again.") in text


def test_words_on_running_work_are_echoed_in_the_receipt(tmp_path, monkeypatch):
    """D3 (walk 2 item 8: two sends "looked identical", nothing echoed):
    the receipt quotes the words sent and says they do not reach the
    session. Mutation: drop `sent_text` -> red."""
    runner = FakeRunner(_ok("running", "as your words", transcript_row=5))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(_UNCLAIMED)), runner=runner)
    text = _words(client.post(f"/inbox/{ID_APPROVED}/answer",
                              data={"text": "Please leave the .d folder alone."}, headers=HX).text)
    assert "data-recorded" in text  # control
    assert "“Please leave the .d folder alone.”" in text.split("data-sent-words")[1]
    assert "they are kept for the overseer and do not reach the session carrying it out" in text


def test_a_working_login_check_redraws_the_chip_at_the_top(tmp_path, monkeypatch):
    """D3 (walk 2 #004: the closed login item still read "Needs you · log
    in"): the check that works redraws the chip out of band. Mutation:
    drop the chips from the login partial -> red."""
    monkeypatch.setattr(ledger, "scheduler_next", lambda home: None)
    reads = Reads(_doc(LOGIN, OO7))
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    reads.doc = _doc(OO7)
    resp = client.post(f"/inbox/{ID_LOGIN}/check-login", headers=HX).text
    assert "data-login-fixed" in resp  # control: the check worked
    chips = resp.split('id="ws-chips"')[1].split("</p>")[0]
    assert 'hx-swap-oob="true"' in chips and "Closed: the login works again" in chips


# ------------------------------------------------------------ D4


def test_the_help_the_footer_and_every_armed_panel_say_the_same_steps(tmp_path, monkeypatch):
    """D4: the `?` overlay's intro on inbox pages is the inbox's own (with
    keymap.ARMED_HOW in it), every armed panel prints ARMED_HOW and puts
    Cancel before Confirm (so Tab from the focused Cancel reaches
    Confirm), and the footer's number-key label says Tab then Enter. The
    review pages keep their own intro. Mutations: the old "then Enter to
    confirm" intro on the inbox -> red; Confirm before Cancel -> red."""
    _no_answered(monkeypatch)
    reads = Reads(_doc(OO7, HOOK, _UNCLAIMED), {ID_OO7: OO7_PACKET, ID_HOOK: HOOK_PACKET})
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    page = _words(client.get(f"/inbox/{ID_OO7}").text)
    intro = page.split("data-inbox-help-intro>")[1].split("</p>")[0]
    assert keymap.ARMED_HOW in intro and "A key never settles anything here." in intro
    assert "then <kbd>Enter</kbd> to confirm or any other key to cancel" not in page
    assert "Arm that option (a key never answers): Tab to Confirm, then Enter" in page
    assert f'data-armed-how="{keymap.ARMED_HOW}"' in page

    panels = [
        client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes"}, headers=HX).text,
        client.post(f"/inbox/{ID_HOOK}/undo", headers=HX).text,
    ]
    for panel in panels:
        words = _words(panel)
        assert "data-armed-cancel" in words  # control: an armed panel rendered
        assert keymap.ARMED_HOW in words
        assert words.index("data-armed-cancel") < words.index("data-confirm-armed")


def test_the_review_pages_keep_their_own_help_intro(tmp_path, monkeypatch):
    """D4 changes only the inbox's overlay. Mutation: print the inbox
    intro whatever the page -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)))
    overlay = client.app.state.templates.get_template("partials/help_overlay.html")
    review = overlay.render(keymap_entries=[])
    inbox = overlay.render(keymap_entries=[], inbox_help_intro=keymap.INBOX_HELP_INTRO)
    assert 'id="self-learn-ui-help"' in review  # control: the overlay rendered
    assert "data-inbox-help-intro" not in review
    assert "press once to <strong>arm</strong> it" in review
    assert "data-inbox-help-intro" in inbox and "press once to <strong>arm</strong>" not in inbox


# ------------------------------------------------------------ D5


def test_the_draft_sent_as_is_never_reads_as_your_words(tmp_path, monkeypatch):
    """D5 (walk 2 #015): "Send the draft as is" with no option on an item
    with a plan: the verb records the agent's draft (test_walkfix2's verb
    test); the receipt said "Recorded as your words." from a line written
    in the template. It now prints the verb's own `recorded_as`, and its
    lead says the agent's draft was sent. Mutation: restore the template's
    fixed "Recorded as your words." for words on a plan -> red."""
    runner = FakeRunner(_ok("open", "as the agent's draft, accepted by you", transcript_row=6))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                             runner=runner)
    text = _words(client.post(f"/inbox/{ID_OO7}/answer",
                              data={"draft_id": "drf-1a2b3c4d", "text": "Only on weekdays."},
                              headers=HX).text)
    assert "data-recorded" in text and "data-pick-an-option" in text  # control
    assert "Recorded as the agent's draft, accepted by you." in text
    assert "You sent the agent's draft: nothing is decided yet" in text
    receipt = text.split("data-recorded>")[1].split("</div>")[0]
    assert "Recorded as the agent's draft" in receipt  # control: the receipt block
    assert "as your words" not in receipt


def test_conditions_are_labelled_by_whose_words_they_are(tmp_path, monkeypatch):
    """D5 (walk 2 #019): "Your conditions:" printed the agent's draft as the
    person's. The plan's conditions are labelled from `conditions_how`.
    Mutations: the old fixed "Your conditions:" label -> red; label an
    unknown provenance as the person's -> red."""
    def page_for(how):
        plan = {**OO7_PACKET["plan"], "conditions": "Only if it does not restart my session.",
                "conditions_how": how}
        packet = {**OO7_PACKET, "item": _UNCLAIMED, "plan": plan}
        client, *_ = make_client(tmp_path, monkeypatch,
                                 Reads(_doc(_UNCLAIMED), {ID_APPROVED: packet}))
        return _words(client.get(f"/inbox/{ID_APPROVED}").text)

    drafted = page_for("draft-accepted")
    line = drafted.split("data-conditions=")[1].split("</p>")[0]
    assert "Only if it does not restart my session." in line  # control
    assert "Conditions, the agent's draft, accepted by you:" in line and "Your conditions" not in line
    typed = page_for("typed").split("data-conditions=")[1].split("</p>")[0]
    assert "Your conditions, in your words:" in typed
    unknown = page_for(None).split("data-conditions=")[1].split("</p>")[0]
    assert "Conditions sent with the approval:" in unknown and "Your" not in unknown


# ------------------------------------------------------------ D6


def test_words_sent_by_any_path_are_offered_as_the_note(tmp_path, monkeypatch):
    """D6: with no `sent_t` (a reload, a redraw, an item switch; Send or
    Ctrl+Enter alike), the item's newest answer row is offered when it is
    words with no option: the person's typed words by reference
    (`words_from`), the agent's draft they sent again with its draft id
    (never as their words). A reply that went with an option is not
    offered. Mutations: offer only `sent_t` (the S-130 path) -> red; offer
    a draft row by `words_from` -> red; offer a row that went with an
    option -> red."""
    rows = {ID_OO7: [
        {"t": 0, "kind": "header"},
        {"t": 2, "role": "user", "origin": "typed", "kind": "reply", "option": None,
         "text": "Only if it does not restart my desktop session."},
    ]}
    runner = FakeRunner()
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET}, rows=rows)
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    typed = _words(client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes-conditions"},
                               headers=HX).text)
    assert "needs a note" in typed  # control: the refusal rendered
    offer = typed.split("data-reuse-offer")[1].split("</div>")[0]
    assert "“Only if it does not restart my desktop session.”" in offer
    assert 'name="words_from" value="2"' in offer

    rows[ID_OO7].append({"t": 3, "role": "user", "origin": "draft-accepted", "kind": "reply",
                         "option": None, "draft_id": "drf-1a2b3c4d", "text": "The agent's draft."})
    drafted = _words(client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes-conditions"},
                                 headers=HX).text)
    offer = drafted.split("data-reuse-offer")[1].split("</div>")[0]
    assert "Or use the agent's draft you sent as the note:" in offer
    assert 'name="draft_id" value="drf-1a2b3c4d"' in offer and "words_from" not in offer
    assert "never as your words" in offer

    rows[ID_OO7].append({"t": 4, "role": "user", "origin": "typed", "kind": "reply",
                         "option": "opt-no", "text": "No, on reflection."})
    went = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes-conditions"},
                       headers=HX).text
    assert "needs a note" in went and "data-reuse-offer" not in went
    assert runner.calls == []


def test_the_empty_box_is_not_said_to_be_kept(tmp_path, monkeypatch):
    """Walk 2 #014/#034: "Your text is kept in the box" over an empty box.
    Mutation: print it whatever the box held -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}))
    empty = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes-conditions"},
                        headers=HX).text
    assert "needs a note" in empty and "Your text is kept in the box." not in empty
    held = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-x", "text": "mine"},
                       headers=HX).text
    assert "Your text is kept in the box." in held  # a refusal with text keeps saying it
