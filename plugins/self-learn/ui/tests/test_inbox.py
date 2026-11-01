"""The inbox and its decision workspace (attention round 2026-10-31c,
design r2 §5.5 tests 1-5, 8, 10, 11, 13-15; §2, §3.6, §3.7, §4.7).

Page reads (`ledger.attention`, `ledger.attention_packet`,
`ledger.workspace_rows`) are monkeypatched with the §4.1/§4.3 shapes —
`FakeRunner` carries verb invocations only (this package's own trap:
`ui-test-fixtures-that-control-nothing`). Every absence assertion is
preceded by a positive control that the region it looks in rendered.

Each test names the mutation it was checked against (the lane report has
the runs).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from self_learn_ui import ledger
from self_learn_ui.app import create_app
from self_learn_ui.ask_runner import FakeAskRunner
from self_learn_ui.env import EnvConfig
from self_learn_ui.models import CliRead
from self_learn_ui.runner import FakeRunner, RunResult
from self_learn_ui.sse import AppEventHub

import support

TOKEN = "test-token"

ID_LOGIN = "att-0000000000a1"
ID_OO7 = "att-0000000000b2"
ID_HOOK = "att-0000000000c3"
ID_HOST = "att-0000000000d4"
ID_TAMPER = "att-0000000000e5"
ID_SUDO = "att-0000000000f6"
ID_APPROVED = "att-000000000107"
ID_REGISTER = "att-000000000118"


def _opt(id_, label, effect="other", *, via="answer", recommended=False, confirm=False, note=None):
    return {"id": id_, "label": label, "effect": effect, "confirm": confirm, "note": note,
            "recommended": recommended, "via": via}


def _item(id_, kind, klass, because, title, *, since="2026-10-01T10:00:00Z", options=(),
          state=None, flagged=False, seen=False, undo=None, meanwhile=None, run=None):
    return {
        "id": id_, "class": klass, "kind": kind, "because": because, "subject": f"subj-{id_}",
        "title": title, "meanwhile": meanwhile, "flagged": flagged, "seen": seen,
        "state": state or ("done" if klass == "decided" else "open"),
        "partial": False, "since": since, "updated_at": since,
        "source": {"by": "overseer", "run": None, "report": None}, "refs": [],
        "options": list(options), "undo": undo, "conversation": {"turns": 0, "last_at": None},
        "answer": None, "run": run,
    }


OO7_OPTIONS = (
    _opt("opt-yes", "Yes, add the binding", "approve", recommended=True),
    _opt("opt-yes-conditions", "Yes, with conditions", "approve", note="required"),
    _opt("opt-no", "No, keep the manual note", "decline"),
)
LOGIN = _item(ID_LOGIN, "hold.credentials", "needs-you", "credentials",
              "Log in to Claude: the model cannot be used", since="2026-10-30T22:07:00Z",
              options=(_opt("opt-login", "Open a login terminal", via="run --login", recommended=True),
                       _opt("opt-check", "Check now", via="check-login")))
OO7 = _item(ID_OO7, "ask.system-change", "needs-you", "system-change",
            "Bind oo7-daemon to the session bus so it survives a bus restart?",
            since="2026-09-28T04:15:00Z", options=OO7_OPTIONS,
            meanwhile="Nothing on your system was changed.")
HOOK = _item(ID_HOOK, "decided.hook-activated", "decided", None,
             "The overseer turned on a hook for lrn-9b4bb8f0", since="2026-10-31T09:00:00Z",
             flagged=True, undo={"label": "Turn it off", "redo_label": "Turn it back on", "redo": False})
HOST = _item(ID_HOST, "broken.host", "needs-you", "broken", "The host service has stopped",
             options=(_opt("opt-restart", "Restart self-learn", via="fix", recommended=True),))
TAMPER = _item(ID_TAMPER, "conflict.case-tampered", "needs-you", "conflict",
               "A case file was edited by hand",
               options=(_opt("opt-keep", "I edited it on purpose: keep my edit", via="refreeze --keep"),
                        _opt("opt-restore", "I didn't: restore it", via="refreeze --restore")))
SUDO = _item(ID_SUDO, "ask.system-change", "needs-you", "sudo", "Install the udev rule?",
             state="awaiting-sudo", options=OO7_OPTIONS)
APPROVED = _item(ID_APPROVED, "approved.pending", "approved", None, "Add the safe-update list",
                 state="approved", run=None)
REGISTER = _item(ID_REGISTER, "ask.foreign-history", "needs-you", "foreign-history",
                 "Register ~/repos/x as a git-mode host?",
                 options=(_opt("opt-register", "Yes, register it", "register", confirm=True),
                          _opt("opt-no", "No", "decline")))


def _doc(*items, error=None):
    return {
        "version": 2, "generated_at": "2026-11-01T11:30:12Z", "cache_dir": "/tmp/x",
        "state": "needs-you" if any(i["class"] == "needs-you" for i in items) else "idle",
        "counts": {"needs_you": sum(1 for i in items if i["class"] == "needs-you"),
                   "new": sum(1 for i in items if i["class"] == "decided" and i["flagged"] and not i["seen"]),
                   "decided_unseen": 0, "approved": 0},
        "tooltip": "self-learn: …", "error": error, "items": list(items),
    }


OO7_PACKET = {
    "packet_version": 1, "generated_at": "2026-11-01T11:30:12Z", "item": OO7,
    "question": "Bind oo7-daemon to the session bus so it survives a bus restart?",
    "why_you": "It changes how your computer or tools behave, outside self-learn.",
    "meanwhile": "Nothing on your system was changed; agents restart it by hand.",
    "recommendation": {"option": "opt-yes", "text": "Yes, add the binding",
                       "reasoning": "A bus restart kills the daemon today."},
    "options": [{**o, "does": "approves the change; an agent carries it out"} for o in OO7_OPTIONS],
    "alternatives": [{"option": "opt-no", "does": "nothing is changed"}],
    "plan": {"summary": "Add a systemd drop-in.", "cwd": None,
             "checks": [{"say": "No drop-in binds it yet",
                         "command": "systemctl --user show oo7-daemon.service --property=DropInPaths"}],
             "steps": [{"say": "Reload user units", "command": "systemctl --user daemon-reload",
                        "sudo": False}],
             "files": [{"path": "~/.config/systemd/user/oo7-daemon.service.d/bind-dbus.conf",
                        "content": "[Unit]\nBindsTo=dbus-broker.service\n"}],
             "sudo": False, "money": False, "conditions": None, "written_at": None, "by": "overseer"},
    "decided": None, "undo": None,
    "evidence": [
        {"kind": "lesson", "id": "lrn-9b4250f5", "title": "Restart oo7-daemon by hand",
         "text": "After a bus restart, restart oo7-daemon.", "status": "routed", "placement": "user"},
        {"kind": "statement", "id": "stmt-526d9b44", "at": "2026-10-14T10:00:00Z",
         "verbatim": "hooks on", "answers": {"kind": "proposition", "ref": None},
         "ref": "transcript:s#L1", "context": None, "context_note": "not read (time budget)"},
        {"kind": "case", "id": "case-0fcce296", "question": "Bind it?", "decision": "parked",
         "because": "a system change", "excerpt": "…"},
    ],
    "more": [], "pointers": [], "look_at": [],
    "conversation": {"turns": 0, "last_at": None, "agent_available": True, "agent_unavailable": None},
    "answer": None, "limits": {"bytes": 1000, "truncated": []},
}
SUDO_PACKET = {
    **OO7_PACKET, "item": SUDO,
    "plan": {**OO7_PACKET["plan"], "sudo": True, "steps": [
        {"say": "Install the rule", "command": "sudo install -m644 99-x.rules /etc/udev/rules.d/",
         "sudo": True},
        {"say": "Reload user units", "command": "systemctl --user daemon-reload", "sudo": False},
    ]},
}
HOOK_PACKET = {
    **OO7_PACKET, "item": HOOK, "question": HOOK["title"], "recommendation": None, "options": [],
    "alternatives": [], "plan": None,
    "decided": {"what": "turned on the hook compiled from lrn-9b4bb8f0", "by": "overseer",
                "at": "2026-10-31T09:00:00Z", "because": "you said hooks on",
                "changes_now": "the hook runs on matching tool calls"},
    "undo": {"label": "Turn it off", "redo_label": "Turn it back on"},
    "evidence": [{"kind": "hook", "record": "lrn-9b4bb8f0", "script_excerpt": "#!/bin/sh\nexit 2",
                  "registration": "PreToolUse Bash"}],
}


@pytest.fixture(autouse=True)
def person(monkeypatch):
    """Design r2 §3.4.1, "Tests in agent shells": a person's shell."""
    from self_learn import settings

    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)


class Reads:
    """The monkeypatched page reads, editable per test."""

    def __init__(self, doc, packets=None, rows=None):
        self.doc = doc
        self.packets = dict(packets or {})
        self.rows = dict(rows or {})
        self.packet_calls: list[str] = []


def make_client(tmp_path, monkeypatch, reads: Reads, *, runner=None, ask=None, enter=False):
    monkeypatch.setattr(ledger, "attention", lambda home, env=None: CliRead(data=reads.doc))

    def packet(home, item_id, env=None):
        reads.packet_calls.append(item_id)
        value = reads.packets.get(item_id)
        if isinstance(value, ledger.PacketRead):
            return value
        if value is None:
            return ledger.PacketRead(data=None, error="no packet in this fixture")
        return ledger.PacketRead(data=value)

    monkeypatch.setattr(ledger, "attention_packet", packet)
    monkeypatch.setattr(ledger, "workspace_rows", lambda home, item_id: list(reads.rows.get(item_id, [])))
    hub = AppEventHub()
    runner = runner if runner is not None else FakeRunner()
    if callable(ask) and not hasattr(ask, "start"):
        ask = ask(hub)
    ask = ask if ask is not None else FakeAskRunner(publish=hub.publish_nowait)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = EnvConfig(self_learn_home=home, ui_port=7357, ui_browser=None, pane_model="m",
                    pane_budget_usd=1.0, pane_max_turns=5, pane_engine="sdk")
    app = create_app(env=env, token=TOKEN, runner=runner, app_hub=hub, start_watcher=False,
                     ask_runner=ask)
    client = TestClient(app, base_url="http://127.0.0.1:7357")
    client.cookies.set("slu_token", TOKEN)
    if enter:
        support.enter_client(client)
    return client, runner, ask, hub


HX = {"HX-Request": "true"}


# ----------------------------------------------------------------- 1. order


def test_inbox_redirects_to_the_login_hold_ahead_of_an_older_system_change(tmp_path, monkeypatch):
    """§2.1 item 1. The reader's order is not trusted: the fixture lists
    the older system-change ask first, the login hold second.
    Mutation: sort by `since` only -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7, HOOK, LOGIN)))
    resp = client.get("/inbox", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/inbox/{ID_LOGIN}"


def test_inbox_with_nothing_renders_the_empty_state_and_no_list_items(tmp_path, monkeypatch):
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc()))
    resp = client.get("/inbox", follow_redirects=False)
    assert resp.status_code == 200
    # Positive control: the region rendered, with its words.
    assert "data-inbox-empty" in resp.text and "Nothing needs you, and nothing new." in resp.text
    assert 'id="inbox-list"' in resp.text
    assert "data-inbox-item=" not in resp.text


def test_only_decided_items_select_the_first_unseen_one(tmp_path, monkeypatch):
    seen_old = {**HOOK, "id": "att-0000000000aa", "seen": True, "flagged": False,
                "since": "2026-10-31T10:00:00Z", "updated_at": "2026-10-31T10:00:00Z"}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(seen_old, HOOK)))
    resp = client.get("/inbox", follow_redirects=False)
    assert resp.headers["location"] == f"/inbox/{ID_HOOK}"
    page = client.get(f"/inbox/{ID_HOOK}")
    assert "Nothing needs you" in page.text


# ----------------------------------------------------------------- 2. the workspace


def test_the_workspace_renders_everything_needed_to_decide(tmp_path, monkeypatch):
    """§2.1 items 2-7. Mutation: drop the evidence loop -> red; drop the
    "(recommended)" text -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}))
    page = client.get(f"/inbox/{ID_OO7}").text
    assert '<h1 id="ws-question">Bind oo7-daemon to the session bus so it survives a bus restart?</h1>' in page
    assert "Why you" in page and "outside self-learn" in page
    assert "Meanwhile" in page and "agents restart it by hand" in page
    recommendation = page[page.index('id="ws-rec-h"'):page.index('id="ws-plan-h"')]
    assert "Yes, add the binding" in recommendation and "(recommended)" in recommendation
    assert "A bus restart kills the daemon today." in page
    assert 'role="group" aria-label="Options"' in page
    for label in ("Yes, add the binding", "Yes, with conditions", "No, keep the manual note"):
        assert label in page
    assert 'id="ws-reply-text"' in page
    for evidence_id in ("lrn-9b4250f5", "stmt-526d9b44", "case-0fcce296"):
        assert evidence_id in page
    assert "systemctl --user show oo7-daemon.service --property=DropInPaths" in page
    assert "systemctl --user daemon-reload" in page
    assert "bind-dbus.conf" in page and "BindsTo=dbus-broker.service" in page
    # The ask panel is there, with its fixed chips.
    assert "Ask about this" in page and "What happens if I say no?" in page
    # The list marks the selected item.
    assert 'aria-current="page"' in page


def test_a_decided_item_renders_undo_and_no_option_group(tmp_path, monkeypatch):
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: HOOK_PACKET}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    assert "data-undo" in page and "Turn it off" in page  # positive control first
    assert "What was decided" in page and "you said hooks on" in page
    assert 'aria-label="Options"' not in page
    assert "Should have asked me" in page
    assert "Why was this decided?" in page


def test_an_unseen_item_marks_itself_seen_after_one_second(tmp_path, monkeypatch):
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: HOOK_PACKET}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    assert f'hx-post="/inbox/{ID_HOOK}/seen" hx-trigger="load delay:1s"' in page


# ----------------------------------------------------------------- 3. answers


def test_an_option_click_runs_answer_with_the_option(tmp_path, monkeypatch):
    runner = FakeRunner(RunResult(0, stdout='{"item": "x", "state": "approved", '
                                            '"recorded_as": "as your choice of the offered option"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                             runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes"}, headers=HX)
    assert resp.status_code == 200
    assert runner.calls[0][:5] == ["attention", "answer", ID_OO7, "--option", "opt-yes"]
    assert "--text-file" not in runner.calls[0]
    assert "Recorded as your choice of the offered option." in resp.text


def test_typed_words_reach_the_verb_as_a_0600_file_that_is_gone_afterwards(tmp_path, monkeypatch):
    """§4.7: the reply reaches the verb as `--text-file`, never argv.
    Mutation: pass the text in argv -> red."""
    seen: dict = {}

    class Peek(FakeRunner):
        async def run(self, argv):
            path = Path(argv[argv.index("--text-file") + 1])
            seen["mode"] = stat.S_IMODE(os.stat(path).st_mode)
            seen["text"] = path.read_text(encoding="utf-8")
            seen["path"] = path
            return await super().run(argv)

    runner = Peek(RunResult(0, stdout='{"state": "open", "recorded_as": "as your words"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)), runner=runner)
    words = "yes, but only if it doesn't restart my desktop session"
    client.post(f"/inbox/{ID_OO7}/answer", data={"text": words}, headers=HX)
    argv = runner.calls[0]
    assert argv[:3] == ["attention", "answer", ID_OO7]
    assert words not in argv
    assert seen["text"] == words and seen["mode"] == 0o600
    assert not seen["path"].exists()


# ----------------------------------------------------------------- 4. arming


def test_a_confirm_option_arms_first_and_runs_on_the_second_post(tmp_path, monkeypatch):
    """Mutation: skip arming -> red."""
    runner = FakeRunner(RunResult(0, stdout='{"state": "answered", "recorded_as": "as your choice of the offered option"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(REGISTER)), runner=runner)
    first = client.post(f"/inbox/{ID_REGISTER}/answer", data={"option": "opt-register"}, headers=HX)
    assert "data-armed-answer" in first.text and "Confirm: Yes, register it" in first.text
    assert runner.calls == []
    second = client.post(f"/inbox/{ID_REGISTER}/answer",
                         data={"option": "opt-register", "confirm": "1"}, headers=HX)
    assert second.status_code == 200
    assert runner.calls[0][:5] == ["attention", "answer", ID_REGISTER, "--option", "opt-register"]
    assert "--confirm" in runner.calls[0]


def test_an_approve_on_a_plan_with_sudo_steps_arms_and_lists_them(tmp_path, monkeypatch):
    open_sudo_item = {**SUDO, "state": "open", "because": "system-change"}
    runner = FakeRunner()
    client, *_ = make_client(tmp_path, monkeypatch,
                             Reads(_doc(open_sudo_item), {ID_SUDO: SUDO_PACKET}), runner=runner)
    resp = client.post(f"/inbox/{ID_SUDO}/answer", data={"option": "opt-yes"}, headers=HX)
    assert "data-armed-answer" in resp.text
    assert "sudo install -m644 99-x.rules /etc/udev/rules.d/" in resp.text
    assert "You run these yourself" in resp.text
    assert runner.calls == []


def test_a_note_required_option_refuses_without_a_note(tmp_path, monkeypatch):
    runner = FakeRunner()
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)), runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes-conditions"}, headers=HX)
    assert "data-answer-error" in resp.text and "needs a note" in resp.text
    assert runner.calls == []


# ----------------------------------------------------------------- 5. drafts


def test_a_draft_id_is_forwarded_and_an_edited_text_keeps_it(tmp_path, monkeypatch):
    """The server decides the origin, not this page. Mutation: drop
    `--draft` -> red."""
    runner = FakeRunner(RunResult(0, stdout='{"state": "open", "recorded_as": "as the agent\'s draft, edited and sent by you"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)), runner=runner)
    client.post(f"/inbox/{ID_OO7}/answer",
                data={"text": "Add only the first two, please", "draft_id": "drf-1a2b3c4d"}, headers=HX)
    argv = runner.calls[0]
    assert argv[argv.index("--draft") + 1] == "drf-1a2b3c4d"
    assert "--text-file" in argv


def test_a_draft_card_with_an_option_says_send_as(tmp_path, monkeypatch):
    rows = [{"t": 0, "kind": "header"},
            {"t": 1, "role": "user", "origin": "typed", "kind": "question", "text": "draft it"},
            {"t": 2, "role": "agent", "origin": "agent", "kind": "answer", "text": "Here you go."},
            {"t": 3, "role": "agent", "origin": "agent", "kind": "draft", "draft_id": "drf-1a2b3c4d",
             "option": "opt-yes-conditions", "text": "Add only the first two; leave the binary check out"}]
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET},
                                                          rows={ID_OO7: rows}))
    page = client.get(f"/inbox/{ID_OO7}").text
    assert "data-draft-card" in page and "Use this draft" in page
    assert "Send as: Yes, with conditions" in page
    assert 'name="draft_id" value="drf-1a2b3c4d"' in page


# ----------------------------------------------------------------- 6. ask (routes)


async def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def test_ask_streams_through_the_hub_in_order_and_refuses_a_second_turn(tmp_path, monkeypatch):
    """Mutation: drop the in-flight check -> red."""
    script = [{"ev": "start", "turn": 1}, {"ev": "delta", "text": "Hel"},
              {"ev": "delta", "text": "lo"}, {"ev": "done", "text": "Hello", "turn": 2}]
    box: dict = {}

    def factory(hub):
        box["ask"] = FakeAskRunner(publish=hub.publish_nowait, script=script, hold=True)
        return box["ask"]

    client, runner, ask, hub = make_client(tmp_path, monkeypatch,
                                           Reads(_doc(OO7), {ID_OO7: OO7_PACKET}),
                                           ask=factory, enter=True)
    queue = client.portal.call(_subscribe, hub)
    first = client.post(f"/inbox/{ID_OO7}/ask", data={"message": "is this already done?"}, headers=HX)
    assert first.status_code == 200 and "ws-live-bubble" in first.text
    second = client.post(f"/inbox/{ID_OO7}/ask", data={"message": "and now?"}, headers=HX)
    assert second.status_code == 409 and "Still answering your last question" in second.text
    assert ask.calls == [(ID_OO7, "is this already done?")]
    ask.release(ID_OO7)
    client.portal.call(ask.wait, ID_OO7)
    envelopes = client.portal.call(_drain, queue)
    asks = [e for e in envelopes if e.get("type") == "ask"]
    assert [e["ev"] for e in asks] == ["start", "delta", "delta", "done", "end"]
    assert all(e["item"] == ID_OO7 for e in asks)
    assert "".join(e.get("text", "") for e in asks if e["ev"] == "delta") == "Hello"
    assert runner.calls == []


async def _subscribe(hub):
    return hub.subscribe()


def test_stop_ends_the_turn_and_check_login_never_uses_the_verb_runner(tmp_path, monkeypatch):
    client, runner, ask, _hub = make_client(
        tmp_path, monkeypatch, Reads(_doc(LOGIN, OO7)), enter=True,
        ask=lambda hub: FakeAskRunner(publish=hub.publish_nowait, hold=True, script=[
            {"ev": "start"}, {"ev": "delta", "text": "x"}, {"ev": "done", "text": "x"}]))
    client.post(f"/inbox/{ID_OO7}/ask", data={"message": "why?"}, headers=HX)
    stopped = client.post(f"/inbox/{ID_OO7}/ask/stop", headers=HX)
    assert "Stopping" in stopped.text and ask.stops == [ID_OO7]
    client.portal.call(ask.wait, ID_OO7)
    assert ask.in_flight(ID_OO7) is None

    resp = client.post(f"/inbox/{ID_LOGIN}/check-login", headers=HX)
    assert resp.status_code == 200 and "The login works." in resp.text
    assert ask.login_checks == 1
    assert runner.calls == []


# ----------------------------------------------------------------- 8. seen


def test_seen_runs_the_seen_verb(tmp_path, monkeypatch):
    """Mutation: answer 204 without running the verb -> red."""
    client, runner, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK)))
    resp = client.post(f"/inbox/{ID_HOOK}/seen", headers=HX)
    assert resp.status_code == 204
    assert runner.calls == [["attention", "seen", ID_HOOK]]


def test_mark_all_seen_runs_the_verb_and_returns_the_list(tmp_path, monkeypatch):
    client, runner, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK, OO7)))
    resp = client.post("/inbox/seen-all", data={"selected": ID_OO7}, headers=HX)
    assert runner.calls[0] == ["attention", "seen", "--all-decided"]
    assert 'id="inbox-list"' in resp.text


# ----------------------------------------------------------------- 10. keys


def test_the_inbox_keymap_lists_its_keys_and_the_help_overlay_shows_them(tmp_path, monkeypatch):
    """§3.6. Mutation: render the review pages' keymap on the inbox -> red."""
    from self_learn_ui.keymap import INBOX_KEYMAP

    keys = {k for entry in INBOX_KEYMAP for k in entry.keys}
    assert {"j", "k", "Enter", "1", "2", "3", "4", "r", "a", "Ctrl+Enter", "Escape", "u", "s", "?"} <= keys
    all_keys = [k for entry in INBOX_KEYMAP for k in entry.keys]
    assert len(all_keys) == len(set(all_keys)), "every inbox key is unique in its table"
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7), {ID_OO7: OO7_PACKET}))
    page = client.get(f"/inbox/{ID_OO7}").text
    overlay = page[page.index('id="self-learn-ui-help"'):]
    assert "Keyboard reference" in overlay  # positive control: the overlay rendered
    for label in ("Next item", "Write your own answer", "Ask about this",
                  "Send the box you are typing in", "Mark all seen"):
        assert label in overlay
    assert "Ctrl+Enter" in overlay
    blob = page[page.index('id="self-learn-ui-keymap"'):]
    assert '"inbox_next"' in blob and '"route"' not in blob
    assert 'data-page="inbox"' in page and "/static/inbox.js" in page


# ----------------------------------------------------------------- 11. failures


def test_an_answer_that_exits_3_shows_the_verbs_message_and_keeps_the_text(tmp_path, monkeypatch):
    """§3.7 "Answer failed". Mutation: drop the kept text -> red."""
    runner = FakeRunner(RunResult(3, stderr="self-learn attention answer: «No» needs --confirm"))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)), runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-no", "text": "not now, later"},
                       headers=HX)
    assert "data-answer-error" in resp.text
    assert "needs --confirm" in resp.text
    assert ">not now, later</textarea>" in resp.text


def test_a_packet_failure_shows_the_error_block_and_the_answer_bar_still_works(tmp_path, monkeypatch):
    reads = Reads(_doc(OO7), {ID_OO7: ledger.PacketRead(data=None, error="KeyError: 'plan'")})
    client, *_ = make_client(tmp_path, monkeypatch, reads)
    page = client.get(f"/inbox/{ID_OO7}").text
    assert "data-answer-bar" in page and 'aria-label="Options"' in page  # control first
    assert "data-packet-error" in page and "KeyError: &#39;plan&#39;" in page
    assert 'id="ws-reply-text"' in page


def test_the_reader_failing_shows_the_error_panel_with_retry(tmp_path, monkeypatch):
    doc = _doc(error="OSError: the cache is gone")
    doc["state"] = "broken"
    client, *_ = make_client(tmp_path, monkeypatch, Reads(doc))
    page = client.get("/inbox", follow_redirects=False).text
    assert "data-reader-error" in page and "OSError: the cache is gone" in page
    assert ">Retry</a>" in page


# ----------------------------------------------------------------- 13. run and fix


def test_run_and_fix_run_their_verbs_and_a_missing_terminal_shows_the_command(tmp_path, monkeypatch):
    import json as _json

    runner = FakeRunner()
    # `attention run --json`'s exit-5 object (follow-ups 2, gap 3): the page
    # copies `command` and names `brief`; it never parses the sentence, so
    # here the sentence names neither.
    runner.queue_result(RunResult(5, stdout=_json.dumps({
        "exit": 5, "message": "no terminal found, so nothing was started",
        "command": "claude 'self-learn: read the brief'",
        "brief": "/c/attention/runs/x/brief.md"})))
    runner.queue_result(RunResult(0, stdout="self-learn-host.service restarted"))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(APPROVED, HOST)), runner=runner)
    resp = client.post(f"/inbox/{ID_APPROVED}/run", headers=HX)
    assert runner.calls[0] == ["attention", "run", ID_APPROVED, "--json"]
    assert "No terminal was found" in resp.text
    assert 'data-copy="#ws-run-cmd"' in resp.text
    # Gate r1 finding 3: the copy block holds the command alone, which runs
    # when pasted; the verb's sentence around it is prose outside the block.
    copied = resp.text.split('id="ws-run-cmd" data-run-command>')[1].split("</pre>")[0]
    assert copied == "claude &#39;self-learn: read the brief&#39;"
    assert "/c/attention/runs/x/brief.md" in resp.text
    assert "Run it now" in resp.text and 'hx-target="closest .ws-run"' in resp.text
    fix = client.post(f"/inbox/{ID_HOST}/fix", data={"option": "opt-restart"}, headers=HX)
    assert runner.calls[1] == ["attention", "fix", ID_HOST, "--option", "opt-restart"]
    assert "restarted" in fix.text


def test_open_a_login_terminal_runs_run_login(tmp_path, monkeypatch):
    runner = FakeRunner(RunResult(0, stdout='{"exit": 0, "message": "A terminal is open running '
                                         'claude: type /login there.", "command": null, "brief": null}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(LOGIN)), runner=runner)
    resp = client.post(f"/inbox/{ID_LOGIN}/run", data={"login": "1"}, headers=HX)
    assert runner.calls == [["attention", "run", ID_LOGIN, "--login", "--json"]]
    assert "/login" in resp.text


# ----------------------------------------------------------------- 14. words alone on a plan


def test_typed_words_on_a_plan_say_pick_an_option_and_the_item_stays_under_needs_you(tmp_path, monkeypatch):
    runner = FakeRunner(RunResult(0, stdout='{"state": "open", "recorded_as": "as your words"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(OO7)), runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"text": "what about my desktop?"}, headers=HX)
    # Positive control: the list rendered (out of band) in this response.
    assert 'id="inbox-list"' in resp.text and 'hx-swap-oob="true"' in resp.text
    assert "data-pick-an-option" in resp.text and "To decide, pick an option." in resp.text
    needs = resp.text[resp.text.index('data-group="needs-you"'):]
    needs = needs[: needs.index("</ul>")]
    assert ID_OO7 in needs


# ----------------------------------------------------------------- 15. code kinds


@pytest.mark.parametrize("item, labels", [
    (LOGIN, ("Open a login terminal", "Check now")),
    (HOST, ("Restart self-learn",)),
    (TAMPER, ("I edited it on purpose: keep my edit", "I didn&#39;t: restore it")),
])
def test_each_code_kind_renders_its_own_options(tmp_path, monkeypatch, item, labels):
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(item)))
    page = client.get(f"/inbox/{item['id']}").text
    assert 'role="group" aria-label="Options"' in page
    for label in labels:
        assert label in page


def test_keep_my_edit_goes_through_the_answer_verb(tmp_path, monkeypatch):
    runner = FakeRunner(RunResult(0, stdout='{"state": "answered", "recorded_as": "as your choice of the offered option"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(TAMPER)), runner=runner)
    client.post(f"/inbox/{ID_TAMPER}/answer", data={"option": "opt-keep"}, headers=HX)
    assert runner.calls[0][:5] == ["attention", "answer", ID_TAMPER, "--option", "opt-keep"]


def test_awaiting_sudo_renders_copy_buttons_and_i_ran_it(tmp_path, monkeypatch):
    runner = FakeRunner(RunResult(0, stdout='{"state": "approved", "recorded_as": "as your choice of the offered option"}'))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(SUDO), {ID_SUDO: SUDO_PACKET}),
                             runner=runner)
    page = client.get(f"/inbox/{ID_SUDO}").text
    assert "data-awaiting-sudo" in page
    assert "sudo install -m644 99-x.rules /etc/udev/rules.d/" in page
    assert 'data-copy="#ws-sudo-1"' in page
    assert "I ran it" in page
    client.post(f"/inbox/{ID_SUDO}/answer", data={"option": "opt-ran-sudo"}, headers=HX)
    assert runner.calls[0][:5] == ["attention", "answer", ID_SUDO, "--option", "opt-ran-sudo"]


# ----------------------------------------------------------------- the front page link


def test_the_front_page_links_the_inbox_with_its_count(tmp_path, monkeypatch):
    """§4.7 "Inbox (N)". Gate r1 NIT 2: the front page itself never waits
    on `attention --json`; the link fills its count in after load."""
    sb = support.make_env(tmp_path)
    from self_learn_ui import models as ui_models  # noqa: F401 -- the front model is real

    reads: list[str] = []

    def attention(home, env=None):
        reads.append("attention")
        return CliRead(data=_doc(LOGIN, HOOK))

    monkeypatch.setattr(ledger, "attention", attention)
    from self_learn_ui.env import load_env

    app = create_app(env=load_env(sb.env), token=TOKEN, runner=FakeRunner(), start_watcher=False)
    client = TestClient(app, base_url="http://127.0.0.1:7357")
    client.cookies.set("slu_token", TOKEN)
    page = client.get("/").text
    assert 'href="/inbox"' in page and 'hx-get="/inbox/count"' in page
    assert reads == []
    link = client.get("/inbox/count", headers=HX).text
    assert 'href="/inbox"' in link and "Inbox (2)" in link and reads == ["attention"]
    monkeypatch.setattr(ledger, "attention", lambda home, env=None: CliRead(data=None, error="boom"))
    assert "Inbox (?)" in client.get("/inbox/count", headers=HX).text


def test_the_weekly_report_renders_read_only(tmp_path, monkeypatch):
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc()))
    home = tmp_path / "home"
    (home / "overseer").mkdir(parents=True)
    (home / "overseer" / "latest-report.md").write_text("# Overseer report\n\n## Hooks\n- one\n")
    (home / "overseer" / "2026-10-25-report.md").write_text("# Older\n")
    page = client.get("/overseer-report").text
    assert "Overseer report" in page and "/overseer-report/2026-10-25" in page
    assert "hx-post" not in page.split('id="self-learn-ui-content"')[1].split("<footer")[0]
    assert client.get("/overseer-report/not-a-date").status_code == 404


def test_an_approval_that_moves_the_item_on_links_to_it_and_offers_no_old_options(tmp_path, monkeypatch):
    """After an approve click the ask leaves "Needs you" and an approved
    item with its own id takes its place: the page links to it and does
    not offer the old options again. Mutation: render the options form on
    a closed item -> red."""
    approved = {**APPROVED, "subject": OO7["subject"], "title": OO7["title"], "state": "running",
                "run": {"unit": "self-learn-run-x", "at": "2026-11-01T10:00:00Z", "claimed_by": None}}
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET})

    class Moves(FakeRunner):
        async def run(self, argv):
            reads.doc = _doc(approved)
            return await super().run(argv)

    runner = Moves(RunResult(0, stdout='{"state": "running", "recorded_as": "as your choice of the offered option", '
                                       '"run": {"exit": 0, "message": "Launched in a terminal."}}'))
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes"}, headers=HX)
    assert "data-recorded" in resp.text and "Launched in a terminal." in resp.text  # control
    assert "data-answer-closed" in resp.text and f'href="/inbox/{ID_APPROVED}"' in resp.text
    answer_bar = resp.text[: resp.text.index('id="inbox-list"')]
    assert 'aria-label="Options"' not in answer_bar
    assert 'id="ws-answer-form"' not in answer_bar


# ----------------------------------------------------------------- fix round 1 (gate r1)


def test_a_login_no_terminal_offers_claude_alone_to_copy(tmp_path, monkeypatch):
    """Gate r1 finding 3, the login variant: the copy block holds `claude`,
    not the verb's sentence. Follow-ups 2 (gap 3): the command comes from
    `attention run --json`'s `command` field; the sentence is not parsed."""
    import json as _json

    runner = FakeRunner(RunResult(5, stdout=_json.dumps({
        "exit": 5, "message": "no terminal found, so nothing was started",
        "command": "claude", "brief": None})))
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(LOGIN)), runner=runner)
    resp = client.post(f"/inbox/{ID_LOGIN}/run", data={"login": "1"}, headers=HX)
    assert "No terminal was found" in resp.text  # control: the no-terminal branch rendered
    copied = resp.text.split('id="ws-run-cmd" data-run-command>')[1].split("</pre>")[0]
    assert copied == "claude"
    assert "type /login" in resp.text


def test_an_approval_whose_launch_found_no_terminal_offers_run_it_now_for_the_successor(
        tmp_path, monkeypatch):
    """Gate r1 finding 3, the approve path: the approval moved the item on
    (its approved successor has its own id), the launch found no terminal,
    and the page offers Run it now for the successor plus the command alone.
    Mutation: Run it now for the old needs-you item (run_item = item) -> red."""
    approved = {**APPROVED, "subject": OO7["subject"], "title": OO7["title"], "state": "approved"}
    reads = Reads(_doc(OO7), {ID_OO7: OO7_PACKET})

    class Moves(FakeRunner):
        async def run(self, argv):
            reads.doc = _doc(approved)
            return await super().run(argv)

    # Follow-ups 2 (gap 3): the answer verb's `run` carries `command` and
    # `brief`; the sentence is not parsed, so it names neither here.
    run = {"exit": 5, "message": "no terminal found, so nothing was started",
           "command": "claude 'go'", "brief": "/c/b.md"}
    import json as _json

    runner = Moves(RunResult(0, stdout=_json.dumps({
        "state": "approved", "recorded_as": "as your choice of the offered option", "run": run})))
    client, *_ = make_client(tmp_path, monkeypatch, reads, runner=runner)
    resp = client.post(f"/inbox/{ID_OO7}/answer", data={"option": "opt-yes"}, headers=HX)
    assert "data-answer-closed" in resp.text and "No terminal was found" in resp.text  # control
    assert f'hx-post="/inbox/{ID_APPROVED}/run"' in resp.text and "data-run-now" in resp.text
    assert f'hx-post="/inbox/{ID_OO7}/run"' not in resp.text
    copied = resp.text.split('id="ws-run-cmd" data-run-command>')[1].split("</pre>")[0]
    assert copied == "claude &#39;go&#39;"


@pytest.mark.parametrize("item, rows", [
    ({**HOOK, "undo": {**HOOK["undo"], "redo": True}}, []),
    (HOOK, [{"t": 0, "kind": "header"},
            {"t": 1, "role": "user", "origin": "clicked", "kind": "undo", "text": None, "option": None}]),
])
def test_after_a_reload_an_undone_item_offers_redo_not_the_undo_again(tmp_path, monkeypatch, item, rows):
    """Gate r1 finding 4: redo survives a reload, from `undo.redo` or from
    the item's transcript (its last undo/redo row is an undo). Mutation:
    ignore `redo_next` (always offer the undo) -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(item), {ID_HOOK: HOOK_PACKET},
                                                          rows={ID_HOOK: rows}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    bar = page[page.index('class="ws-undo"'):]
    bar = bar[: bar.index("</div>")]
    assert "data-undo" in bar  # positive control: the undo region rendered its button
    assert "Turn it back on" in bar and '"redo": "1"' in bar
    assert "Turn it off" not in bar


def test_a_redone_item_offers_the_undo_again(tmp_path, monkeypatch):
    """The other half: after undo then redo the next act is the undo."""
    rows = [{"t": 1, "role": "user", "origin": "clicked", "kind": "undo"},
            {"t": 2, "role": "user", "origin": "clicked", "kind": "redo"}]
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: HOOK_PACKET},
                                                          rows={ID_HOOK: rows}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    bar = page[page.index('class="ws-undo"'):]
    bar = bar[: bar.index("</div>")]
    assert "Turn it off" in bar and "Turn it back on" not in bar


def test_an_undo_that_moves_the_item_on_says_so(tmp_path, monkeypatch):
    """Gate r1 finding 2's undo side: reopening a withdrawn ask removes the
    decided item from the list; the page says the click did it
    (data-answer-closed), which keeps inbox.js from calling it "resolved
    elsewhere", and offers neither redo nor the undo again."""
    withdrawn = _item("att-0000000000aa", "decided.withdrawn", "decided", None,
                      "The overseer withdrew a question", undo={"label": "Ask me anyway",
                                                                 "redo_label": None, "redo": False})
    reopened = _item("att-0000000000bb", "ask.system-change", "needs-you", "system-change",
                     "Bind oo7-daemon?", options=OO7_OPTIONS)
    reopened["subject"] = withdrawn["subject"]
    reads = Reads(_doc(withdrawn))

    class Moves(FakeRunner):
        async def run(self, argv):
            reads.doc = _doc(reopened)
            return await super().run(argv)

    client, runner, *_ = make_client(tmp_path, monkeypatch, reads, runner=Moves(RunResult(0, stdout="reopened")))
    resp = client.post(f"/inbox/{withdrawn['id']}/undo", headers=HX)
    assert runner.calls[0] == ["attention", "undo", withdrawn["id"]]
    assert "Undone." in resp.text  # control
    assert "data-answer-closed" in resp.text and 'href="/inbox/att-0000000000bb"' in resp.text
    bar = resp.text[: resp.text.index('id="inbox-list"')]
    assert "Ask me anyway" not in bar and 'id="ws-answer-form"' not in bar


def test_the_register_confirm_names_the_question(tmp_path, monkeypatch):
    """Gate r1 NIT 1 (§3.7 "This registers <path> in git mode. Confirm?"):
    the armed line repeats the question, which names the path and mode."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(REGISTER)), runner=FakeRunner())
    resp = client.post(f"/inbox/{ID_REGISTER}/answer", data={"option": "opt-register"}, headers=HX)
    assert "data-armed-answer" in resp.text
    assert "Register ~/repos/x as a git-mode host?" in resp.text.split("data-armed-answer")[1]


def test_the_register_confirm_quotes_the_full_question_not_the_cut_title(tmp_path, monkeypatch):
    """Gate r2 NIT A: the list title is cut at 200 characters, and the
    register path can sit past the cut; the armed line quotes the packet's
    full question. Mutation: quote item.title again -> red."""
    long_q = ("After the overseer read three weeks of your sessions in that repository, "
              "it found a history of hand-made commits that self-learn did not make, "
              "and it asks whether to take it over: Register ~/repos/far/away/x as a git-mode host?")
    cut = long_q[:199].rstrip() + "…"
    item = {**REGISTER, "title": cut}
    packet = {**OO7_PACKET, "item": item, "question": long_q}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(item), packets={ID_REGISTER: packet}),
                             runner=FakeRunner())
    resp = client.post(f"/inbox/{ID_REGISTER}/answer", data={"option": "opt-register"}, headers=HX)
    armed = resp.text.split("data-armed-answer")[1]
    assert "Confirm: Yes, register it" in armed  # control: the armed line rendered
    assert "Register ~/repos/far/away/x as a git-mode host?" in armed


def test_a_stale_heartbeat_names_no_next_run(tmp_path, monkeypatch):
    """Gate r2 NIT B: a host that stopped leaves its heartbeat file; its
    next_job is no longer a promise. Mutation: drop the freshness check in
    ledger.scheduler_next -> red."""
    import json as _json
    import time as _time

    from self_learn import attention as sl_attention
    from self_learn import serve as sl_serve

    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(sl_attention, "cache_dir", lambda home: cache)

    def beat(age: float) -> None:
        sl_serve.heartbeat_path(cache).write_text(_json.dumps(
            {"ts": _time.time() - age, "tick_secs": 60, "next_job": "mine at 2026-11-02T03:31:00"}),
            encoding="utf-8")

    beat(5)
    assert ledger.scheduler_next(tmp_path) == "mine at 2026-11-02T03:31:00"  # control: fresh
    beat(3600)
    assert ledger.scheduler_next(tmp_path) is None


def test_a_working_login_says_when_the_held_jobs_run_again(tmp_path, monkeypatch):
    """Gate r1 NIT 3 (§2.3 d): the page says when held jobs retry, in the
    host's own words from serve.heartbeat. Mutation: drop the line -> red."""
    monkeypatch.setattr(ledger, "scheduler_next", lambda home: "mine at 2026-11-02T03:31:00")
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(LOGIN)))
    resp = client.post(f"/inbox/{ID_LOGIN}/check-login", headers=HX)
    assert "The login works." in resp.text and "data-item-resolved" in resp.text
    assert "Next scheduled: mine at 2026-11-02T03:31:00" in resp.text


def test_the_apps_idle_monitor_waits_for_an_ask_turn(tmp_path, monkeypatch):
    """Gate r1 finding 6: `create_app` itself hands the idle monitor the
    ask runner's busy flag (test 7 builds its monitor by hand). Mutation:
    delete `ask_busy=` from app.py's IdleMonitor call -> red."""
    from self_learn_ui import app as app_module
    from self_learn_ui.idle import IdleMonitor

    built: list[dict] = []

    class Recording(IdleMonitor):
        def __init__(self, **kwargs):
            built.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(app_module, "IdleMonitor", Recording)
    monkeypatch.setattr(ledger, "attention", lambda home, env=None: CliRead(data=_doc(OO7)))
    monkeypatch.setattr(ledger, "workspace_rows", lambda home, item_id: [])
    hub = AppEventHub()
    ask = FakeAskRunner(publish=hub.publish_nowait, hold=True,
                        script=[{"ev": "start"}, {"ev": "done", "text": "x"}])
    home = tmp_path / "home"
    home.mkdir()
    env = EnvConfig(self_learn_home=home, ui_port=7357, ui_browser=None, pane_model="m",
                    pane_budget_usd=1.0, pane_max_turns=5, pane_engine="sdk")
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), app_hub=hub, start_watcher=False,
                     ask_runner=ask, idle_exit_seconds=600, idle_exit_callback=lambda: None)
    with TestClient(app, base_url="http://127.0.0.1:7357") as client:
        client.cookies.set("slu_token", TOKEN)
        assert len(built) == 1  # control: the app built its monitor
        ask_leg = built[0].get("ask_busy")
        assert callable(ask_leg) and ask_leg() is False
        resp = client.post(f"/inbox/{ID_OO7}/ask", data={"message": "still there?"}, headers=HX)
        assert resp.status_code == 200 and ask.busy
        assert ask_leg() is True
        ask.release(ID_OO7)
        client.portal.call(ask.wait, ID_OO7)
        assert ask_leg() is False


def test_a_decision_self_learn_noticed_says_so_in_words(tmp_path, monkeypatch):
    """Integration: attention-core writes `decided.by: code` for what
    self-learn noticed itself (a plain registration); the page says so in
    words instead of "By the code". Mutation: render the raw value -> red."""
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: HOOK_PACKET}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    assert "By the overseer" in page  # positive control: the known actor in words
    noticed = {**HOOK_PACKET, "decided": {**HOOK_PACKET["decided"], "by": "code"}}
    client, *_ = make_client(tmp_path, monkeypatch, Reads(_doc(HOOK), {ID_HOOK: noticed}))
    page = client.get(f"/inbox/{ID_HOOK}").text
    # 2026-11-01: worded so no `self-learn <word>` sits in the template,
    # which 09 §11 Y-11's template check reads as a terminal command.
    assert "By self-learn (it noticed this itself; no model decided it)" in page
    assert "By the code" not in page
