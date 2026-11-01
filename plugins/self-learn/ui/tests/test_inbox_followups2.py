"""Follow-ups 2 of the attention round (2026-11-01; S-NEXT-followups2), the
page's side.

- Gap 1: a hand-edited case's page shows what was decided beside what the
  file says now (the packet's ``case_edit``).
- Gap 2: approved work offers the ask's other options as one click before a
  session claims it; once one has, they are off, said in words, and "Stop
  it" (``attention stop``) is offered when the page opened that terminal.

Page reads (``ledger.attention``, ``ledger.attention_packet``,
``ledger.workspace_rows``) are monkeypatched (``test_inbox.make_client``);
``FakeRunner`` carries verb invocations only. Each test names the mutation
it was checked against.
"""

from __future__ import annotations

from self_learn_ui.runner import FakeRunner, RunResult

from test_inbox import (  # noqa: F401 -- `person` is an autouse fixture
    APPROVED,
    HX,
    ID_APPROVED,
    ID_TAMPER,
    OO7_PACKET,
    TAMPER,
    Reads,
    _doc,
    _opt,
    make_client,
    person,
)

# ------------------------------------------------------------------ gap 1

_CASE_EDIT = {
    "case": "case-0fcce296",
    "decided": {"text": "## Identity and scope\n- question: Bind it?\n## Decision\n- because: it changes the desktop",
                "commit": "1cb2f283fa3d", "committed_at": "2026-10-20T10:00:00Z", "truncated": False},
    "now": "## Identity and scope\n- question: Bind it?\n## Decision\n- because: I decided this myself",
    "changes": [{"was": "- because: it changes the desktop", "now": "- because: I decided this myself"}],
    "note": None,
}
_TAMPER_PACKET = {**OO7_PACKET, "item": TAMPER, "question": TAMPER["title"], "plan": None,
                  "recommendation": None, "alternatives": [], "options": [], "case_edit": _CASE_EDIT}


def _section(page: str) -> str:
    start = page.index("data-case-edit")
    return page[start: page.index("</section>", start)]


def test_a_hand_edited_case_shows_what_was_decided_beside_the_file_now(tmp_path, monkeypatch):
    """Mutation: the template's case_edit section removed -> red."""
    reads = Reads(_doc(TAMPER), {ID_TAMPER: _TAMPER_PACKET})
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    page = client.get(f"/inbox/{ID_TAMPER}").text
    assert "I edited it on purpose: keep my edit" in page  # control: the workspace rendered
    edit = _section(page)
    assert "What was decided, and what the file says now" in edit
    change = edit[edit.index("data-case-change"):]
    assert change.index("it changes the desktop") < change.index("I decided this myself")
    assert "Was decided:" in change and "The file says now:" in change
    assert "data-decided-text" in edit


def test_a_case_whose_decided_text_is_missing_says_why(tmp_path, monkeypatch):
    missing = {**_CASE_EDIT, "decided": None, "changes": [],
               "note": "no commit of this case holds the text it was decided with, so it cannot be "
                       "shown, and restoring it would be refused"}
    reads = Reads(_doc(TAMPER), {ID_TAMPER: {**_TAMPER_PACKET, "case_edit": missing}})
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    edit = _section(client.get(f"/inbox/{ID_TAMPER}").text)
    assert "data-decided-missing" in edit and "restoring it would be refused" in edit
    assert "I decided this myself" in edit  # the file as it is now is still shown
    assert "data-case-change" not in edit


def test_other_pages_have_no_case_edit_section(tmp_path, monkeypatch):
    reads = Reads(_doc(TAMPER), {ID_TAMPER: {**_TAMPER_PACKET, "case_edit": None}})
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    page = client.get(f"/inbox/{ID_TAMPER}").text
    assert 'id="ws-evidence-h"' in page  # control: the packet's parts rendered
    assert "data-case-edit" not in page


# ------------------------------------------------------------------ gap 2

_DECLINE = _opt("opt-no", "No, leave it", "decline")
_RUN = {"unit": "self-learn-run-000000000107", "at": "2026-11-01T10:00:00Z", "claimed_by": None}
_UNCLAIMED = {**APPROVED, "state": "running", "run": _RUN, "options": [_DECLINE]}
_OFF = ("a session (sess-1) is carrying it out now and a different answer cannot reach it; "
        "Stop it first")
_CLAIMED = {**APPROVED, "state": "running", "run": {**_RUN, "claimed_by": "sess-1"},
            "options": [{**_DECLINE, "disabled": _OFF},
                        _opt("opt-stop", "Stop it", via="stop", confirm=True)]}
_NOT_OURS = {**APPROVED, "state": "running", "run": {**_RUN, "claimed_by": "sess-2"},
             "options": [{**_DECLINE, "disabled": "a session (sess-2) that this page did not open "
                                                  "is carrying it out now; tell it in its own terminal"}]}


def _bar(page: str) -> str:
    start = page.index('id="ws-answer"')
    return page[start: page.index("</section>", start)]


def test_unclaimed_approved_work_offers_a_one_click_change(tmp_path, monkeypatch):
    """Mutation: the answer bar drops options on approved items -> red."""
    runner = FakeRunner(RunResult(0, stdout='{"state": "answered", "recorded_as": '
                                            '"as your choice of the offered option"}'))
    reads = Reads(_doc(_UNCLAIMED))
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    bar = _bar(client.get(f"/inbox/{ID_APPROVED}").text)
    assert "data-approved" in bar  # control: the approved block rendered
    assert 'name="option" value="opt-no"' in bar
    assert "disabled" not in bar.split('value="opt-no"')[1].split(">")[0]
    assert "No session has claimed the work yet" in bar
    resp = client.post(f"/inbox/{ID_APPROVED}/answer", data={"option": "opt-no"}, headers=HX)
    assert runner.calls == [["attention", "answer", ID_APPROVED, "--option", "opt-no", "--json"]]
    assert "Recorded as your choice of the offered option" in resp.text


def test_claimed_work_turns_options_off_in_words_and_offers_stop_it(tmp_path, monkeypatch):
    """Mutations: render the off option enabled -> red; drop the `stop`
    branch of the option buttons -> red."""
    runner = FakeRunner()
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(_CLAIMED)), runner=runner)
    bar = _bar(client.get(f"/inbox/{ID_APPROVED}").text)
    assert "data-claimed-words" in bar  # control
    button = bar.split('value="opt-no"')[1].split(">")[0]
    assert "disabled" in button
    assert f"No, leave it is off: {_OFF}" in bar
    assert f'hx-post="/inbox/{ID_APPROVED}/stop"' in bar and "data-stop" in bar
    assert "a step it is in the middle of stops there and is not undone" in bar
    # Clicking the off option anyway runs nothing.
    resp = client.post(f"/inbox/{ID_APPROVED}/answer", data={"option": "opt-no"}, headers=HX)
    assert "data-answer-error" in resp.text and "is off:" in resp.text
    assert runner.calls == []


def test_work_claimed_by_a_session_the_page_did_not_open_says_tell_it_there(tmp_path, monkeypatch):
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(_NOT_OURS)))
    bar = _bar(client.get(f"/inbox/{ID_APPROVED}").text)
    assert "data-claimed-words" in bar  # control
    assert "tell it in its own terminal" in bar
    assert "/stop" not in bar


def test_stop_it_asks_first_then_runs_the_verb_and_redraws_the_bar(tmp_path, monkeypatch):
    """Mutation: the route runs `attention stop` on the first click (no
    arming) -> red."""
    stopped_item = {**APPROVED, "state": "approved", "run": None, "options": [_DECLINE]}
    reads = Reads(_doc(_CLAIMED))

    class Stops(FakeRunner):
        async def run(self, argv):
            reads.doc = _doc(stopped_item)
            return await super().run(argv)

    runner = Stops(RunResult(0, stdout="Stopped. The terminal opened for this work is closed."))
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)

    armed = client.post(f"/inbox/{ID_APPROVED}/stop", headers=HX)
    assert "data-armed-stop" in armed.text and "data-confirm-stop" in armed.text
    assert "is not undone" in armed.text
    assert runner.calls == []

    done = client.post(f"/inbox/{ID_APPROVED}/stop", data={"confirm": "1"}, headers=HX)
    assert runner.calls == [["attention", "stop", ID_APPROVED]]
    assert "data-stopped" in done.text and "Stopped. The terminal" in done.text
    bar = _bar(done.text)
    button = bar.split('value="opt-no"')[1].split(">")[0]
    assert "disabled" not in button  # the change of mind is one click again
    assert "data-run-now" in bar


def test_stop_it_on_an_item_that_offers_none_runs_nothing(tmp_path, monkeypatch):
    runner = FakeRunner()
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(_UNCLAIMED)), runner=runner)
    resp = client.post(f"/inbox/{ID_APPROVED}/stop", data={"confirm": "1"}, headers=HX)
    assert resp.status_code == 400 and "data-stop-error" in resp.text
    assert runner.calls == []


def test_a_refused_stop_says_why(tmp_path, monkeypatch):
    runner = FakeRunner(RunResult(3, stderr="self-learn attention stop: self-learn-run-x did not stop"))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(_CLAIMED)), runner=runner)
    resp = client.post(f"/inbox/{ID_APPROVED}/stop", data={"confirm": "1"}, headers=HX)
    assert "data-stop-error" in resp.text and "did not stop" in resp.text
