"""The inbox's walk fixes, server side (S-130; the source-blind
walk of 2026-11-01, misc/build-2026-10-31c/walk-attention.md).

As in test_inbox.py: page reads (`ledger.attention`,
`ledger.attention_packet`, `ledger.workspace_rows`, and here
`ledger.answer_preview`) are monkeypatched; `FakeRunner` carries verb
invocations only. Every absence assertion is preceded by a positive
control that the region it looks in rendered. Each test names the
mutation it was checked against.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import markupsafe

from self_learn_ui import inbox_routes, keymap, ledger, rendering
from self_learn_ui.runner import FakeRunner, RunResult

from test_inbox import (  # noqa: F401 -- person is an autouse fixture
    APPROVED,
    HOOK,
    HOOK_PACKET,
    HX,
    ID_APPROVED,
    ID_HOOK,
    ID_LOGIN,
    ID_OO7,
    ID_REGISTER,
    LOGIN,
    OO7,
    OO7_PACKET,
    REGISTER,
    Reads,
    _doc,
    _item,
    _opt,
    make_client,
    person,
)

_OK = RunResult(0, stdout='{"state": "open", "recorded_as": "as your words", "transcript_row": 4}')


def _bar(page: str) -> str:
    start = page.index('id="ws-answer"')
    return page[start: page.index("</section>", start)]


def _answers(runner) -> list[list[str]]:
    return [c for c in runner.calls if c[:2] == ["attention", "answer"]]


# ------------------------------------------------------------ item 1: keys


def test_a_key_on_an_approve_option_arms_it_and_a_click_arms_it_too(tmp_path, monkeypatch):
    """Walk item 1: `keyed=1` (inbox.js sets it for a number key) on an
    approve option arms it with words that say it approves, and runs no
    verb. Walk 2 (D1, revising design r2 §0 call 3): the same option
    clicked (no `keyed`) arms too; only Confirm sends. Mutations: ignore
    `keyed` -> red (the key approves); a click on an approve option sends
    at once (the old rule) -> red."""
    runner = FakeRunner(_OK)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                             runner=runner)
    keyed = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes", "keyed": "1"},
                        headers=HX)
    assert "data-armed-answer" in keyed.text and "approves this change" in keyed.text
    assert "a key never approves on its own" in keyed.text
    assert 'name="confirm" value="1"' in keyed.text
    assert _answers(runner) == []

    clicked = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes"}, headers=HX)
    assert "data-armed-answer" in clicked.text and "approves this change" in clicked.text
    assert "a key never" not in clicked.text  # a click says nothing about a key
    assert _answers(runner) == []
    client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes", "confirm": "1"}, headers=HX)
    assert _answers(runner) == [["attention", "answer", ID_OO7, "--option", "opt-yes", "--json"]]


def test_a_key_on_a_decline_option_arms_it_and_a_click_sends_it(tmp_path, monkeypatch):
    """Walk 2 (D2): a key never settles anything, so a key on a plain "No"
    arms it too, in words that say what it does; (D1) a mouse click on the
    same ordinary answer still sends at once. Mutations: arm only approve
    and register keys (the old rule) -> red; arm every click -> red."""
    runner = FakeRunner(_OK)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                             runner=runner)
    keyed = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-no", "keyed": "1"},
                        headers=HX)
    words = markupsafe.Markup(keyed.text).unescape()
    assert "data-armed-answer" in words  # control: the armed panel rendered
    assert "“No, keep the manual note”: nothing will be changed" in words
    assert "a key never answers on its own" in words
    assert _answers(runner) == []
    client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-no"}, headers=HX)
    assert _answers(runner) == [["attention", "answer", ID_OO7, "--option", "opt-no", "--json"]]


def test_the_key_hints_say_approve_and_register_plainly(tmp_path, monkeypatch):
    """Walk item 1: under the options, each number key says what it does;
    approve and register options say so in words. Mutation: hint by label
    only -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7, REGISTER), {ID_OO7: OO7_PACKET}))
    oo7 = _bar(client.get(f"/inbox/{ID_OO7}").text)
    assert "data-key-hints" in oo7  # control
    assert "<kbd>1</kbd> approve: Yes, add the binding" in oo7
    assert "<kbd>3</kbd> No, keep the manual note" in oo7
    # Walk 2 (D2, D4): every key only arms, and the hints say the panel's steps.
    assert "A key only arms its option." in oo7 and keymap.ARMED_HOW in oo7
    assert 'data-effect="approve"' in oo7 and 'data-effect="decline"' in oo7
    reg = _bar(client.get(f"/inbox/{ID_REGISTER}").text)
    assert "<kbd>1</kbd> register: Yes, register it" in reg


# ------------------------------------------------------------ item 2: provenance


def test_the_reply_box_has_one_provenance_line(tmp_path, monkeypatch):
    """Walk item 2: one line says how the box's text is recorded; the old
    second "Using the agent's draft" line is gone, and the plan line says
    only what words alone do. Mutation: render the old draft note -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}))
    bar = _bar(client.get(f"/inbox/{ID_OO7}").text)
    assert bar.count("data-provenance-line") == 1  # control and the claim
    assert str(markupsafe.escape(inbox_routes.PROVENANCE_EMPTY)) in bar
    assert "Using the agent's draft" not in bar and "ws-reply-draft-note" not in bar
    assert "Recorded as your words." not in bar
    assert inbox_routes.PLAN_LINE in bar


def test_the_provenance_route_reports_the_verbs_rule_in_words(tmp_path, monkeypatch):
    """The page asks POST .../provenance as the box changes; the answer is
    the CLI preview, in words. Mutations: report "as your words" for a
    draft-edited preview -> red; drop the matched words -> red."""
    calls = []

    def preview(home, item_id, *, text, draft_id, option=None):
        calls.append((item_id, text, draft_id))
        if text and "agent says" in text:
            return {"origin": "draft-edited", "recorded_as": "as the agent's draft, edited and sent by you",
                    "matched": "the agent says this long thing", "problem": None}
        return {"origin": "typed", "recorded_as": "as your words", "matched": None, "problem": None}

    monkeypatch.setattr(ledger, "answer_preview", preview)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)))
    mine = client.post(f"/inbox/{ID_OO7}/provenance", data={"text": "my own words"}, headers=HX).json()
    theirs = client.post(f"/inbox/{ID_OO7}/provenance",
                         data={"text": "so the agent says this long thing", "draft_id": ""},
                         headers=HX).json()
    bad = client.post(f"/inbox/{ID_OO7}/provenance", data={"text": "x", "draft_id": "nope"},
                      headers=HX).json()

    assert mine == {"line": "Sending this records it as your words.", "origin": "typed", "matched": None}
    assert theirs["origin"] == "draft-edited"
    assert theirs["line"].startswith("Sending this records it as the agent's draft, edited and sent "
                                     "by you, not as your words")
    assert "“the agent says this long thing”" in theirs["line"]
    assert bad["origin"] is None and "would not be recorded" in bad["line"]
    assert calls == [(ID_OO7, "my own words", None), (ID_OO7, "so the agent says this long thing", None)]


def test_a_refused_send_keeps_the_text_and_says_how_it_would_be_recorded(tmp_path, monkeypatch):
    """A bar redrawn with text in the box (a refusal) carries the preview of
    that text, never the general line. Mutation: skip the server-side
    preview in `_workspace_ctx` -> red."""
    monkeypatch.setattr(ledger, "answer_preview", lambda home, item_id, **kw: {
        "origin": "draft-edited", "recorded_as": "as the agent's draft, edited and sent by you",
        "matched": "pasted words", "problem": None})
    runner = FakeRunner(RunResult(3, stderr="refused for this test"))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)), runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"text": "pasted words here"}, headers=HX)
    bar = _bar(resp.text)
    assert "data-answer-error" in bar and "pasted words here" in bar  # control
    assert "as the agent&#39;s draft, edited and sent by you, not as your words" in bar
    assert str(markupsafe.escape(inbox_routes.PROVENANCE_EMPTY)) not in bar


# ------------------------------------------------------------ item 3: no retyping


def test_words_sent_alone_are_offered_as_the_required_note(tmp_path, monkeypatch):
    """Walk item 3: after a words-only send the bar carries the row
    (`sent_t`); "Yes, with conditions" with an empty box then offers those
    words in one click, which sends `--words-from`. Mutations: drop
    `sent_t` from the recorded bar -> red; drop the offer -> red; send the
    words as --text-file (a second statement) -> red."""
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET}, rows={ID_OO7: [
        {"t": 0, "kind": "header"},
        {"t": 4, "role": "user", "origin": "typed", "kind": "reply", "option": None,
         "text": "Only if it does not restart my desktop session."},
    ]})
    runner = FakeRunner(_OK)
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    sent = client.post(f"/inbox/{ID_OO7}/answer",
                       data={"text": "Only if it does not restart my desktop session."}, headers=HX)
    assert 'name="sent_t" value="4"' in sent.text

    refused = client.post(f"/inbox/{ID_OO7}/answer",
                          data={"option": "opt-yes-conditions", "sent_t": "4"}, headers=HX)
    assert "needs a note" in refused.text  # control: the refusal rendered
    assert "data-reuse-offer" in refused.text
    assert "“Only if it does not restart my desktop session.”" in refused.text
    assert "stay recorded as your words" in refused.text
    assert len(_answers(runner)) == 1

    # Walk 2 (D1): the option approves, so it asks once more, quoting the
    # words that go with it; Confirm sends them by reference.
    armed = client.post(f"/inbox/{ID_OO7}/answer",
                        data={"option": "opt-yes-conditions", "words_from": "4", "sent_t": "4"},
                        headers=HX)
    assert "data-armed-answer" in armed.text and len(_answers(runner)) == 1
    assert 'name="words_from" value="4"' in armed.text
    client.post(f"/inbox/{ID_OO7}/answer",
                data={"option": "opt-yes-conditions", "words_from": "4", "sent_t": "4",
                      "confirm": "1"}, headers=HX)
    assert _answers(runner)[-1] == ["attention", "answer", ID_OO7, "--option", "opt-yes-conditions",
                                    "--words-from", "4", "--json"]


def test_no_offer_without_words_sent_in_this_visit_or_for_someone_elses_row(tmp_path, monkeypatch):
    """No `sent_t`, or a row that is not the person's typed reply, offers
    nothing (the refusal still renders), and a forged `words_from` is
    refused without a verb call. Mutation: offer any row -> red."""
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET}, rows={ID_OO7: [
        {"t": 2, "role": "agent", "origin": "agent", "kind": "answer", "text": "The agent's words."},
    ]})
    runner = FakeRunner(_OK)
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    for data in ({"option": "opt-yes-conditions"}, {"option": "opt-yes-conditions", "sent_t": "2"}):
        resp = client.post(f"/inbox/{ID_OO7}/answer", data=data, headers=HX)
        assert "needs a note" in resp.text and "data-reuse-offer" not in resp.text
    forged = client.post(f"/inbox/{ID_OO7}/answer",
                         data={"option": "opt-yes-conditions", "words_from": "2"}, headers=HX)
    assert forged.status_code == 400 and _answers(runner) == []


# ------------------------------------------------------------ item 4: login


def test_a_working_login_puts_the_result_at_the_top_and_clears_the_ask_note(tmp_path, monkeypatch):
    """Walk item 4: on success the response carries, out of band, a banner
    for the top of the page (closed, why it left the list, what is next),
    the redrawn list, and the ask panel's note replaced. Mutation: drop
    the out-of-band banner -> red."""
    monkeypatch.setattr(ledger, "scheduler_next", lambda home: "mine at 2026-11-02T03:31:00")
    login_packet = {**OO7_PACKET, "item": LOGIN, "plan": None, "conversation": {
        **OO7_PACKET["conversation"], "agent_available": False, "agent_unavailable": "login"}}
    reads = Reads(_doc(LOGIN, OO7), {ID_LOGIN: login_packet})
    client, _runner, ask, _hub = make_client(tmp_path, monkeypatch, reads)
    page = client.get(f"/inbox/{ID_LOGIN}").text
    assert 'id="ws-top-result"' in page and 'data-ask-off="login"' in page  # controls
    assert "The agent can't answer right now: the Claude login is broken." in page

    reads.doc = _doc(OO7)  # the check cleared the hold
    resp = client.post(f"/inbox/{ID_LOGIN}/check-login", headers=HX)
    top = resp.text.split('id="ws-top-result" hx-swap-oob="true"')[1].split('id="ws-ask-off"')[0]
    assert "This item is closed." in top and "left the Needs you list" in top
    assert "mine at 2026-11-02T03:31:00" in top
    assert f'href="/inbox/{ID_OO7}"' in top  # the next item
    assert 'id="ws-ask-off" class="ws-ask-off ws-ask-off-ok" role="note" hx-swap-oob="true"' in resp.text
    assert 'id="inbox-list"' in resp.text and f'data-inbox-item="{ID_LOGIN}"' not in resp.text


# ------------------------------------------------------------ item 5: plain words


def test_undo_says_what_it_did_in_words_and_redraws_what_it_changes_now(tmp_path, monkeypatch):
    """Walk item 5: "Turn it off" answers in words, the verb's line (ids)
    sits in a details fold, and "What it changes now" is redrawn from the
    fresh read. Mutations: print the verb's stdout as the main text ->
    red; drop the out-of-band meanwhile -> red."""
    undone_packet = {**HOOK_PACKET, "decided": {**HOOK_PACKET["decided"],
                                                "changes_now": "Nothing now: you turned the hook off."}}
    reads = Reads(_doc(HOOK), {ID_HOOK: HOOK_PACKET})

    class Undo(FakeRunner):
        async def run(self, argv):
            reads.packets[ID_HOOK] = undone_packet
            return await super().run(argv)

    client, runner, *_ = make_client(tmp_path, monkeypatch, reads, runner=Undo(RunResult(
        0, stdout="attention undo: hook deactivate lrn-9b4bb8f0")))
    resp = client.post(f"/inbox/{ID_HOOK}/undo", data={"confirm": "1"}, headers=HX)
    bar = _bar(resp.text)
    main = bar.split("<details")[0]
    assert "data-undone" in main  # control
    assert "Turned off: the hook no longer runs in new Claude Code sessions." in main
    assert "attention undo" not in main and "lrn-9b4bb8f0" not in main
    assert "attention undo: hook deactivate lrn-9b4bb8f0" in bar  # in the fold
    oob = resp.text.split('id="ws-meanwhile"')[1]
    assert 'hx-swap-oob="true"' in oob.split(">")[0]
    assert "Nothing now: you turned the hook off." in oob.split("</section>")[0]


def test_feedback_says_what_changed_and_folds_the_ids(tmp_path, monkeypatch):
    """Walk item 5: "Should have asked me" says the item moved to Needs
    you, with no ids in the words. Mutation: show the verb's stdout as the
    words -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK)), runner=FakeRunner(RunResult(
        0, stdout=f"attention feedback: fb-329de851 on {ID_HOOK}: this item's kind is now shown as needs-you")))
    resp = client.post(f"/inbox/{ID_HOOK}/feedback", data={"wanted": "needs-you"}, headers=HX)
    words = resp.text.split("<details")[0]
    assert "data-feedback-ok" in words  # control
    assert "now wait for you under Needs you, so this one has moved there" in words
    assert "fb-329de851" not in words and ID_HOOK not in words
    assert "fb-329de851" in resp.text  # in the fold


def test_a_verbs_times_are_humanized_in_the_run_result(tmp_path, monkeypatch):
    """Walk item 5: "Running in a terminal (started 2026-...Z)" reads
    "started just now", with the instant kept on hover. Mutation: render
    the message raw -> red."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    approved = {**APPROVED, "state": "approved", "options": []}
    runner = FakeRunner(RunResult(0, stdout='{"exit": 0, "message": "Running in a terminal (started '
                                            + now + ').", "command": null, "brief": "/b"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(approved)), runner=runner)
    resp = client.post(f"/inbox/{ID_APPROVED}/run", headers=HX)
    assert "Running in a terminal (started" in resp.text  # control
    assert f"started {now}" not in resp.text and "just now" in resp.text
    assert f'title="{now}"' in resp.text or now in resp.text.split("just now")[0]


def test_plain_times_escapes_and_humanizes_every_instant():
    """The filter humanizes ISO instants and escapes the rest. Mutation:
    no escape -> red."""
    out = rendering.plain_times("<b> at 2026-10-30T15:13:00Z and 2026-10-30T15:13:00+00:00",
                                now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "&lt;b&gt;" in out and out.count(">yesterday</span>") == 2 and "T15:13" not in out.split("title=")[0]


# ------------------------------------------------------------ item 6: evidence


def test_the_evidence_reads_as_a_person_needs_it(tmp_path, monkeypatch):
    """Walk item 6 on the page: a conflict quote says when and which is
    newer; a hook leads with its trigger and rule and folds the script; a
    folder is said to be one with its ~ path; a lesson lists its
    sightings. Mutations: drop the side chip -> red; script before the
    trigger -> red; "The file" for a folder -> red; drop the sightings
    list -> red."""
    packet = {**OO7_PACKET, "evidence": [
        {"kind": "statement", "id": "stmt-aaaaaaaa", "at": "2026-10-30T19:58:00Z", "side": "newer",
         "verbatim": "legit things are fine", "answers": None, "ref": "transcript:s#L1",
         "context": None, "context_note": "not found on this machine: the conversation file it "
                                          "came from was moved or deleted (the words themselves are kept)"},
        {"kind": "statement", "id": "stmt-bbbbbbbb", "at": "2026-10-30T15:13:00Z", "side": "older",
         "verbatim": "never say waiting on you", "answers": None, "ref": None, "context": None,
         "context_note": None},
        {"kind": "hook", "record": "lrn-9b4bb8f0", "trigger": "About to edit .storage.",
         "instruction": "Stop the container first.", "script_excerpt": "#!/bin/sh\nexit 2",
         "registration": "{}"},
        {"kind": "file", "path": "/home/user/.config/systemd/user", "display": "~/.config/systemd/user",
         "is_dir": True, "excerpt": "oo7-daemon.service", "truncated": False},
        {"kind": "lesson", "id": "lrn-9b4250f5", "title": "An update to intel-ucode comes up.",
         "trigger": "An update to intel-ucode comes up.", "instruction": "Treat it as harmless.",
         "text": "## Trigger\n...", "status": "routed", "placement": "user", "sightings": 2,
         "seen": [{"at": "2026-10-20T10:00:00Z", "quote": "harmless again"},
                  {"at": "2026-10-01T10:00:00Z", "quote": "fine last time"}]},
    ]}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: packet}))
    page = client.get(f"/inbox/{ID_OO7}").text
    ev = page[page.index('id="ws-evidence-h"'):page.index('id="ws-answer"')]
    assert 'data-side="newer">the newer one' in ev and 'data-side="older">the older one' in ev
    assert "Said Oct 30, 2026 at 19:58 UTC; it holds until you answer." in ev
    assert "Said Oct 30, 2026 at 15:13 UTC." in ev
    assert "moved or deleted" in ev and "RefError" not in ev
    hook = ev[ev.index('data-evidence-kind="hook"'):]
    assert hook.index("data-hook-trigger") < hook.index("data-hook-script") < hook.index("#!/bin/sh")
    assert "What is in the folder <code class=\"ws-path\">~/.config/systemd/user</code>" in ev
    assert "The file <code" not in ev.split('data-evidence-kind="lesson"')[0].split(
        'data-evidence-kind="file"')[1]
    assert "Seen 2 times" in ev and "“harmless again”" in ev


# ------------------------------------------------------------ item 7: running


def _running(minutes_ago: float, claimed: str | None = None) -> dict:
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {**APPROVED, "state": "running", "options": [_opt("opt-no", "No, leave it", "decline")],
            "run": {"unit": "self-learn-run-000000000107", "at": at, "claimed_by": claimed}}


def test_run_it_now_is_never_offered_while_it_runs(tmp_path, monkeypatch):
    """Walk item 7: a fresh launch offers no relaunch; one no session has
    claimed for two minutes offers "Open a new terminal", saying why;
    approved work that is not running offers "Start it in a new
    terminal". Mutation: show the button whenever unclaimed -> red."""
    fresh = _bar(make_client(tmp_path, monkeypatch, Reads(_doc(_running(0.2))))[0].get(
        f"/inbox/{ID_APPROVED}").text)
    assert "data-approved" in fresh and "Running in a terminal" in fresh  # control
    assert "data-run-now" not in fresh
    stale = _bar(make_client(tmp_path, monkeypatch, Reads(_doc(_running(5))))[0].get(
        f"/inbox/{ID_APPROVED}").text)
    assert "data-unclaimed-stale" in stale and "Open a new terminal to carry it out" in stale
    idle = _bar(make_client(tmp_path, monkeypatch, Reads(_doc({**APPROVED, "options": []})))[0].get(
        f"/inbox/{ID_APPROVED}").text)
    assert "Start it in a new terminal" in idle
    claimed = _bar(make_client(tmp_path, monkeypatch, Reads(_doc(_running(5, "sess-1"))))[0].get(
        f"/inbox/{ID_APPROVED}").text)
    assert "data-claimed-words" in claimed and "data-run-now" not in claimed


def test_words_on_running_work_never_say_you_can_change_your_answer(tmp_path, monkeypatch):
    """Walk item 7: "Tell it something" on running work records the words
    and says to tell the session in its terminal, not "You can change your
    answer until it is carried out". Mutation: the old else-branch -> red."""
    runner = FakeRunner(RunResult(0, stdout='{"state": "running", "recorded_as": "as your words", '
                                            '"transcript_row": 3}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(_running(0.2))), runner=runner)
    resp = client.post(f"/inbox/{ID_APPROVED}/answer", data={"text": "keep my session up"}, headers=HX)
    bar = _bar(resp.text)
    assert "Recorded as your words." in bar  # control
    assert "data-running-words" in bar and "tell that session in its terminal" in bar
    assert "You can change your answer until it is carried out" not in bar


# ------------------------------------------------------------ item 8: small


def test_a_decided_item_never_says_nothing_is_done_until_you_answer(tmp_path, monkeypatch):
    """Walk item 8: a decided item without a "changes now" says it is a
    record. Mutation: the old fallback -> red."""
    run = _item("att-0000000000ab", "decided.overseer-run", "decided", None,
                "The overseer's weekly run, 2026-10-31", flagged=True)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(run)))
    page = client.get("/inbox/att-0000000000ab").text
    section = page[page.index('id="ws-meanwhile"'):].split("</section>")[0]
    assert "What it changes now" in section  # control
    assert "Nothing is done until you answer" not in section
    assert "Nothing waits on you: this is a record of what was decided for you." in section


def test_the_new_mark_reads_the_same_in_the_header_and_the_list(tmp_path, monkeypatch):
    """Walk item 8: an unseen decided item shows the same word in the page
    header as in its list row, flagged or not. Mutation: header only for
    flagged -> red."""
    plain = {**HOOK, "flagged": False}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(plain), {ID_HOOK: HOOK_PACKET}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    head = page[page.index('class="ws-head"'):page.index("</header>", page.index('class="ws-head"'))]
    row = page[page.index(f'data-inbox-item="{ID_HOOK}"'):].split("</li>")[0]
    # Humane UI lane 3 (proposal §4): the row's mark is a dot whose word is
    # its accessible name; the word is still the header's.
    assert '<span class="dot-new" title="not seen yet"><span class="visually-hidden">unseen</span></span>' in row  # control
    assert '<span class="dot-new" data-new-mark>unseen</span>' in head


def test_the_draft_card_says_send_the_draft(tmp_path, monkeypatch):
    """Walk item 8: the card's button is never just "Send as is".
    Mutation: the old label -> red."""
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET}, rows={ID_OO7: [
        {"t": 1, "role": "agent", "origin": "agent", "kind": "draft", "draft_id": "drf-1a2b3c4d",
         "option": None, "text": "Only the first two."}]})
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    page = client.get(f"/inbox/{ID_OO7}").text
    assert "data-draft-card" in page  # control
    assert ">Send the draft as is</button>" in page and ">Send as is<" not in page


def test_the_ask_off_note_is_a_notice_at_the_top_of_the_panel(tmp_path, monkeypatch):
    """Walk item 4: the off note leads the ask panel, before the
    conversation, and the input says it is off. Mutation: the note below
    the conversation -> red."""
    packet = {**OO7_PACKET, "conversation": {**OO7_PACKET["conversation"],
                                             "agent_unavailable": "login", "agent_available": False}}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7, LOGIN), {ID_OO7: packet}))
    page = client.get(f"/inbox/{ID_OO7}").text
    panel = page[page.index('id="ws-ask"'):]
    assert 'data-ask-off="login"' in panel  # control
    assert panel.index('data-ask-off="login"') < panel.index('id="ws-conversation"')
    assert 'placeholder="Off until the Claude login works again"' in panel


# ------------------------------------------------------------ gate r1


def test_an_approve_option_carried_by_a_draft_arms_whatever_sent_it(tmp_path, monkeypatch):
    """Gate r1 F2: an approve option that rides with the agent's draft
    (`from_draft=1`: inbox.js sets it when the option comes from the used
    draft, the draft card carries it) arms with words that say sending the
    draft approves, and runs no verb; Ctrl+Enter (`keyed=1` as well) arms
    the same way; the option's own button, clicked with no draft, still
    sends at once (with a draft id it arms too: gate r2 N1).
    The armed bar says only Confirm goes ahead and carries a Cancel the
    page can focus. Mutation: ignore `from_draft` -> red."""
    runner = FakeRunner(_OK)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                             runner=runner)
    sent = {"option": "opt-yes", "text": "Only the first two.", "draft_id": "drf-1a2b3c4d"}
    by_draft = client.post(f"/inbox/{ID_OO7}/answer", data={**sent, "from_draft": "1"}, headers=HX)
    words = markupsafe.Markup(by_draft.text).unescape()
    assert "data-armed-answer" in words
    assert "The agent's draft is sent as “" in words and "”, and that approves this change" in words
    assert "data-armed-how" in words and "Number keys do nothing here" in words
    assert "data-armed-cancel" in words
    keyed = client.post(f"/inbox/{ID_OO7}/answer", data={**sent, "from_draft": "1", "keyed": "1"},
                        headers=HX)
    assert "data-armed-answer" in keyed.text and "a key never approves on its own" in keyed.text
    assert _answers(runner) == []

    # Walk 2 (D1): the option's own button, clicked with no draft, arms
    # too, in its own words (not the draft's); Confirm sends it.
    clicked = markupsafe.Markup(client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes"},
                                            headers=HX).text).unescape()
    assert "data-armed-answer" in clicked and "The agent's draft is sent" not in clicked
    client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes", "confirm": "1"}, headers=HX)
    assert _answers(runner)[-1] == ["attention", "answer", ID_OO7, "--option", "opt-yes", "--json"]


def test_the_draft_card_marks_its_option_as_carried_by_the_draft(tmp_path, monkeypatch):
    """Gate r1 F2: "Send the draft as is" on a card with an option posts
    `from_draft=1`, so an approve option arms. Mutation: drop the hidden
    field -> red."""
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET}, rows={ID_OO7: [
        {"t": 1, "role": "agent", "origin": "agent", "kind": "draft", "draft_id": "drf-1a2b3c4d",
         "option": "opt-yes-conditions", "text": "Only the first two."}]})
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    page = client.get(f"/inbox/{ID_OO7}").text
    card = page[page.index("data-draft-card"):].split("</form>")[0]
    assert 'name="option" value="opt-yes-conditions"' in card  # control
    assert '<input type="hidden" name="from_draft" value="1">' in card


def test_a_launch_waiting_two_minutes_is_described_as_maybe_waiting(tmp_path, monkeypatch):
    """Gate r1 F4: after two minutes unclaimed the page never says the
    terminal "probably did not open" (it may be open at a prompt); it says
    what to do either way. Mutation: the old sentence -> red."""
    stale = _bar(make_client(tmp_path, monkeypatch, Reads(_doc(_running(5))))[0].get(
        f"/inbox/{ID_APPROVED}").text)
    assert "data-unclaimed-stale" in stale  # control
    assert "probably did not open" not in stale
    assert "If that terminal is open and waiting for you" in stale
    assert "answer it there" in stale and "open a new one" in stale


def test_a_terminal_already_open_is_said_in_words_with_no_retry(tmp_path, monkeypatch):
    """Gate r1 F4: `attention run` answering `already_open` (this
    approval's unit is still active) renders its plain sentence as a
    status, with no "Try again: open a new terminal" under it. Mutation:
    drop the already_open branch -> red (error strip and a retry)."""
    message = ("A terminal for this is already open: the one opened for it earlier is still "
               "running, and no session in it has started the work yet.")
    approved = {**APPROVED, "state": "approved", "options": []}
    runner = FakeRunner(RunResult(3, stdout='{"exit": 3, "message": "' + message + '", '
                                            '"command": null, "brief": "/b", "already_open": true}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(approved)), runner=runner)
    resp = client.post(f"/inbox/{ID_APPROVED}/run", headers=HX)
    assert "data-already-open" in resp.text and message in resp.text
    assert "error-strip" not in resp.text and "data-run-now" not in resp.text

    failed = FakeRunner(RunResult(3, stdout='{"exit": 3, "message": "the terminal did not open", '
                                            '"command": null, "brief": "/b"}'))
    other, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(approved)), runner=failed)
    plain = other.post(f"/inbox/{ID_APPROVED}/run", headers=HX)
    assert "data-run-now" in plain.text and "data-already-open" not in plain.text  # control


# ------------------------------------------------------------ gate r2


_DRAFT_ROWS = {ID_OO7: [
    {"t": 1, "role": "agent", "origin": "agent", "kind": "draft", "draft_id": "drf-1a2b3c4d",
     "option": "opt-yes-conditions", "text": "Only the first two."}]}


def test_a_draft_send_without_its_option_still_arms_from_the_server(tmp_path, monkeypatch):
    """Gate r2 N1: a send that carries only the draft id (the page forgot
    the draft's option: blocked storage) arms the approval the draft
    carries, read from the item's transcript on the server, and runs no
    verb; a click on an approve option's own button with a draft id arms
    too; the Confirm sends `--confirm`, which the verb now requires.
    Mutations: drop the server's draft-option read -> red; drop
    `--confirm` for a draft's approval -> red."""
    runner = FakeRunner(_OK)
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET},
                                                          rows=_DRAFT_ROWS), runner=runner)
    sent = {"text": "Only the first two.", "draft_id": "drf-1a2b3c4d"}
    bare = client.post(f"/inbox/{ID_OO7}/answer", data=sent, headers=HX)
    assert "data-armed-answer" in bare.text and "Yes, with conditions" in bare.text
    clicked = client.post(f"/inbox/{ID_OO7}/answer", data={**sent, "option": "opt-yes"}, headers=HX)
    assert "data-armed-answer" in clicked.text
    assert _answers(runner) == []

    client.post(f"/inbox/{ID_OO7}/answer",
                data={**sent, "option": "opt-yes-conditions", "confirm": "1"}, headers=HX)
    argv = _answers(runner)[-1]
    assert argv[argv.index("--option") + 1] == "opt-yes-conditions"
    assert argv[argv.index("--draft") + 1] == "drf-1a2b3c4d" and "--confirm" in argv


def test_the_verbs_draft_confirm_refusal_reads_in_words(tmp_path, monkeypatch):
    """Gate r2 N1: when the page could not tell which option the draft
    carries (no such row) and the verb asks for the confirmation, the page
    says in words what to do, never the verb's `--confirm`. Mutation: show
    the verb's message -> red."""
    from self_learn.attention_answers import DRAFT_NEEDS_CONFIRM

    refusal = ("self-learn attention answer: «Yes, with conditions» " + DRAFT_NEEDS_CONFIRM
               + "; nothing was recorded. Send it again with --confirm")
    runner = FakeRunner(RunResult(3, stderr=refusal))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                             runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer",
                       data={"text": "Only the first two.", "draft_id": "drf-1a2b3c4d"}, headers=HX)
    assert len(_answers(runner)) == 1 and "data-answer-error" in resp.text  # control
    words = markupsafe.Markup(resp.text).unescape()
    assert inbox_routes.DRAFT_CONFIRM_UNARMED in words and "--confirm" not in words


def test_an_approvals_own_launch_finding_its_terminal_open_is_a_plain_status(tmp_path, monkeypatch):
    """Gate r2 N2: the approval click's own launch answering `already_open`
    shows the verb's plain sentence under the recorded answer as a status,
    with no error strip and no "Try again". Mutation: drop `run_already_open` from
    the answer bar -> red."""
    message = "A terminal for this is already open: the one opened for it earlier is still running."

    def answered(already_open: bool) -> str:
        run = {"exit": 3, "message": message, "command": None, "brief": "/b"}
        if already_open:
            run["already_open"] = True
        stdout = json.dumps({"state": "running", "recorded_as": "as your choice of the offered option",
                             "transcript_row": 3, "run": run})
        runner = FakeRunner(RunResult(0, stdout=stdout))
        client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                                 runner=runner)
        return _bar(client.post(f"/inbox/{ID_OO7}/answer",
                                data={"option": "opt-yes", "confirm": "1"}, headers=HX).text)

    plain = answered(False)
    assert message in plain and "error-strip" in plain  # control: the old rendering
    bar = answered(True)
    assert "data-already-open" in bar and message in bar
    assert "error-strip" not in bar and "Try again: open a new terminal" not in bar
