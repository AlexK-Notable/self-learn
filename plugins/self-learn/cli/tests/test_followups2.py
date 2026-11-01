"""Follow-ups 2 of the attention round (2026-11-01; S-NEXT-followups2).

1. A hand-edited case's decided text: ``cases.decided_text`` (read-only,
   capped, secret-scanned, the lookup ``refreeze --restore`` uses), shown in
   the packet's ``case_edit`` by the verbs that build it, and by the ask
   agent's ``case`` tool.
2. Changing an answer on approved work by a click: ``attention --json``
   carries the ask's other options on an approved item, off while a session
   holds a claim, and ``attention stop`` ("Stop it") for a claim made in the
   terminal the page opened.
3. ``attention run --json`` and the ``command`` field.

Every test is a person's shell unless it sets an agent marker itself (the
fixtures from ``test_attention_answers``: no agent markers, a hermetic PATH
of logging shims and the real git, so no real terminal or unit can start).
Each test names the mutation it was checked against.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import ask, attention, attention_answers as answers, attention_packet, cases, cli
from self_learn import settings, workspace
from support import commit_all
from test_attention_answers import (  # noqa: F401 -- the autouse fixtures apply here too
    _calls,
    _choices,
    _index,
    _item,
    _system_ask,
    person,
    shims,
)
from test_attention_packet import TOKEN, _case_with_links

# ------------------------------------------------------------------ 1. decided text


_EDIT_FROM = "it changes the user's desktop"
_EDIT_TO = "I decided this myself"


def _tampered(tmp_path: Path, monkeypatch) -> tuple[Path, str, Path]:
    ledger, case_id, _stmt = _case_with_links(tmp_path, monkeypatch)
    path = next((ledger / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    edited = text.replace(_EDIT_FROM, _EDIT_TO)
    assert edited != text  # positive control: the edit landed
    path.write_text(edited, encoding="utf-8")
    with pytest.raises(cases.CaseError):
        cases.show(ledger, case_id, evidence_only=False)  # control: the freeze check fails
    return ledger, case_id, path


def test_decided_text_skips_a_committed_hand_edit_and_shows_what_was_decided(tmp_path, monkeypatch):
    """The edit is committed, so the newest commit fails its own hash; the
    decided text is the commit before it. Mutation: `_decided_version`
    returns the first commit that parses, without the hash check -> red
    (it shows the edit)."""
    ledger, case_id, _path = _tampered(tmp_path, monkeypatch)
    commit_all(ledger, "a hand edit, committed")

    found = cases.decided_text(ledger, case_id)

    assert found is not None
    assert _EDIT_FROM in found["text"] and _EDIT_TO not in found["text"]
    assert found["text"].startswith("## ") and "## Application" not in found["text"]
    assert len(found["commit"]) == 40 and found["committed_at"]
    assert found["truncated"] is False and found["redacted"] == []
    # The same lookup restores the same text (one lookup, two uses).
    cases.refreeze(ledger, case_id, keep=False)
    view = cases.show(ledger, case_id, evidence_only=False)
    assert _EDIT_FROM in view.to_text()


def test_decided_text_is_secret_scanned_and_capped(tmp_path, monkeypatch):
    """Mutations: return the frozen text unscanned -> red (the token
    shows); drop the cap -> red."""
    ledger, case_id, _path = _tampered(tmp_path, monkeypatch)
    real = cases._decided_version  # noqa: SLF001

    def with_secret(home, path):
        sha, when, frozen, digest = real(home, path)
        return sha, when, frozen + f"\n- note: the token is {TOKEN}\n", digest

    monkeypatch.setattr(cases, "_decided_version", with_secret)
    found = cases.decided_text(ledger, case_id)
    assert found is not None and "the token is" in found["text"]  # control: the line is there
    assert TOKEN not in found["text"] and found["redacted"]

    def huge(home, path):
        sha, when, frozen, digest = real(home, path)
        return sha, when, frozen + "a plain line\n" * (cases.DECIDED_TEXT_MAX_CHARS // 6), digest

    monkeypatch.setattr(cases, "_decided_version", huge)
    big = cases.decided_text(ledger, case_id)
    assert big is not None and big["truncated"] is True
    assert len(big["text"]) <= cases.DECIDED_TEXT_MAX_CHARS + 1


def test_decided_text_says_none_when_no_commit_matches(tmp_path, monkeypatch):
    ledger, case_id, _path = _tampered(tmp_path, monkeypatch)
    monkeypatch.setattr(cases, "_frozen_history", lambda home, path: iter(()))
    assert cases.decided_text(ledger, case_id) is None
    with pytest.raises(cases.CaseUsageError):
        cases.decided_text(ledger, "case-00000000")


def _tampered_item(ledger: Path, case_id: str, monkeypatch) -> dict:
    item = attention._new_item(  # noqa: SLF001
        "conflict.case-tampered", case_id, title="A parked case file was edited",
        since=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), refs=[case_id],
    )
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])
    return item


def test_the_packet_of_a_hand_edited_case_shows_what_was_decided_beside_the_file_now(
        tmp_path, monkeypatch, capsys):
    """Mutations: `_case_edit` ignores the reader -> red; the packet verb
    passes no reader -> red (its JSON says "not looked up")."""
    ledger, case_id, _path = _tampered(tmp_path, monkeypatch)
    item = _tampered_item(ledger, case_id, monkeypatch)

    bare = attention_packet.build(ledger, item["id"])
    assert bare["case_edit"]["decided"] is None  # control: no reader, no git
    assert bare["case_edit"]["note"] == "the decided text was not looked up here"
    assert _EDIT_TO in bare["case_edit"]["now"]

    packet = attention_packet.build(ledger, item["id"], decided_reader=cases.decided_text)
    edit = packet["case_edit"]
    assert edit["case"] == case_id and edit["note"] is None
    assert _EDIT_FROM in edit["decided"]["text"] and _EDIT_TO not in edit["decided"]["text"]
    assert len(edit["changes"]) == 1
    assert _EDIT_FROM in edit["changes"][0]["was"] and _EDIT_TO in edit["changes"][0]["now"]
    assert "case_edit" in json.dumps(packet) and packet["limits"]["bytes"] <= attention_packet.MAX_BYTES
    assert any(p.get("tool") == "case" for p in packet["pointers"])
    assert "## The hand edit of" in attention_packet.render_md(packet)

    assert cli.main(["attention", "packet", item["id"], "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert _EDIT_FROM in printed["case_edit"]["decided"]["text"]


def test_an_unreadable_history_leaves_the_page_working_and_says_why(tmp_path, monkeypatch):
    ledger, case_id, _path = _tampered(tmp_path, monkeypatch)
    item = _tampered_item(ledger, case_id, monkeypatch)

    def boom(home, case):
        raise OSError("git is gone")

    packet = attention_packet.build(ledger, item["id"], decided_reader=boom)
    assert packet["case_edit"]["decided"] is None
    assert packet["case_edit"]["note"] == "the ledger's history could not be read (OSError)"
    assert packet["evidence"][0]["kind"] == "case"  # the rest of the page is built


def test_other_kinds_carry_no_case_edit(tmp_path, monkeypatch):
    ledger, case_id, _stmt = _case_with_links(tmp_path, monkeypatch)
    item = attention._new_item(  # noqa: SLF001
        "ask.system-change", "q-x", title="Bind it?", by="overseer",
        since="2026-10-01T00:00:00Z", refs=["q-x", case_id],
    )
    monkeypatch.setattr(attention, "collect", lambda _home, **_k: [item])
    called: list[str] = []
    packet = attention_packet.build(ledger, item["id"],
                                    decided_reader=lambda h, c: called.append(c) or None)
    assert packet["case_edit"] is None and called == []


def test_the_ask_agents_case_tool_shows_the_decided_text_of_a_hand_edited_case(
        tmp_path, monkeypatch):
    """Mutation: drop the `_decided_block` line from `AskTools.case` -> red."""
    ledger, case_id, _path = _tampered(tmp_path, monkeypatch)
    item = _tampered_item(ledger, case_id, monkeypatch)
    folder = ask.workspace_dir(ledger, item["id"])
    folder.mkdir(parents=True, exist_ok=True)
    tools = ask.AskTools(ledger, attention.public(item), roots=ask.read_roots(ledger),
                         denied=ask.read_denied(ledger), cwd=folder)

    text = tools.case({"id": case_id})

    now_part, decided_part = text.split("Sections 1-4 as decided", 1)
    assert _EDIT_TO in now_part  # control: the file as it is now comes first
    assert _EDIT_FROM in decided_part and _EDIT_TO not in decided_part.split("Line of successors")[0]


# ------------------------------------------------------------------ 2. change of mind


_STATE_SHIM = """#!/bin/sh
name=${0##*/}
printf '%s' "$name" >> "$SHIM_LOG"
for a in "$@"; do printf '\\037%s' "$a" >> "$SHIM_LOG"; done
printf '\\n' >> "$SHIM_LOG"
case "$2" in
  is-active) if [ -f "$SHIM_STATE" ]; then read -r s < "$SHIM_STATE"; echo "$s"; else echo inactive; fi ;;
  stop) if [ -z "$SHIM_STUCK" ]; then echo inactive > "$SHIM_STATE"; fi ;;
esac
exit 0
"""


def _launched(home: Path, tmp_path: Path, monkeypatch, *, state: str = "active") -> tuple[dict, str]:
    """An approved, launched system-change ask, its terminal unit reported
    `state` by a systemctl shim that `stop` turns inactive."""
    shim = tmp_path / "shim-bin" / "systemctl"
    shim.write_text(_STATE_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("SHIM_STATE", str(tmp_path / "unit-state"))
    (tmp_path / "unit-state").write_text(state + "\n", encoding="utf-8")
    settings.config_set(home, "attention.terminal", "alacritty -e")
    _index(home, [_system_ask("q-restart-daemon", [])])
    first = _item(home, "q-restart-daemon")
    result = answers.answer(home, first["id"], option="opt-yes")
    assert result.state == "running"  # control: launched
    approved = _item(home, "q-restart-daemon", "approved.pending")
    return approved, approved["id"]


def test_approved_work_offers_the_other_options_as_one_click_changes(tmp_path, monkeypatch):
    """Before a session claims it, the ask's decline is one click on the
    approved item, and taking it closes the work. Mutation: approved items
    carry no options (the old reader) -> red."""
    from support import make_home

    home = make_home(tmp_path)
    approved, approved_id = _launched(home, tmp_path, monkeypatch)
    public = next(i for i in attention.read(home)["items"] if i["id"] == approved_id)
    assert public["state"] == "running" and public["run"]["claimed_by"] is None
    assert [(o["id"], o.get("disabled")) for o in public["options"]] == [("opt-no", None)]

    changed = answers.answer(home, approved_id, option="opt-no")

    assert changed.state == "answered" and changed.recorded_as == "as your choice of the offered option"
    assert [c["option"] for c in _choices(home)] == ["opt-yes", "opt-no"]
    assert all(i["subject"] != "q-restart-daemon" for i in attention.read(home)["items"])
    # The terminal's session, claiming afterwards, is refused and changes nothing.
    with pytest.raises(answers.AnswerError):
        answers.claim(home, approved_id, "sess-late")


def test_a_claimed_change_turns_the_options_off_and_offers_stop_it(tmp_path, monkeypatch):
    """Mutation: `change_options` leaves the options on under a claim ->
    red; `stoppable` true for any claim -> red (the second half)."""
    from support import make_home

    home = make_home(tmp_path)
    _approved, approved_id = _launched(home, tmp_path, monkeypatch)
    answers.claim(home, approved_id, "sess-ours")

    item = next(i for i in attention.read(home)["items"] if i["id"] == approved_id)
    by_id = {o["id"]: o for o in item["options"]}
    assert set(by_id) == {"opt-no", attention.STOP_OPTION_ID}
    assert "Stop it first" in by_id["opt-no"]["disabled"]
    assert by_id[attention.STOP_OPTION_ID]["via"] == "stop"
    with pytest.raises(answers.AnswerError) as refused:
        answers.answer(home, approved_id, option="opt-no")  # the verb's own safety stays
    assert refused.value.exit_code == answers.EXIT_REFUSED

    # A claim older than the page's launch is a session the page did not open.
    claim_path = attention.cache_dir(home) / "attention" / "claims" / f"{approved_id}.json"
    early = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    claim_path.write_text(json.dumps({"session": "sess-agent", "at": early}), encoding="utf-8")
    item = next(i for i in attention.read(home)["items"] if i["id"] == approved_id)
    assert [o["id"] for o in item["options"]] == ["opt-no"]
    assert "did not open" in item["options"][0]["disabled"]
    with pytest.raises(answers.AnswerError) as not_ours:
        answers.stop(home, approved_id)
    assert not_ours.value.exit_code == answers.EXIT_REFUSED
    assert [c for c in _calls(tmp_path, "systemctl") if "stop" in c] == []


def test_stop_it_closes_the_launched_terminal_and_the_answer_can_change(tmp_path, monkeypatch):
    """Mutations: `stop` leaves the claim -> red (the decline is refused);
    `stop` does not mark the launch stopped -> red (still running)."""
    from support import make_home

    home = make_home(tmp_path)
    _approved, approved_id = _launched(home, tmp_path, monkeypatch)
    answers.claim(home, approved_id, "sess-ours")
    unit = f"self-learn-run-{approved_id[4:]}"

    said = answers.stop(home, approved_id)

    assert said == answers.STOPPED_MESSAGE
    assert ["systemctl", "--user", "stop", unit] in _calls(tmp_path, "systemctl")
    item = next(i for i in attention.read(home)["items"] if i["id"] == approved_id)
    assert item["state"] == "approved" and item["run"] is None
    assert [(o["id"], o.get("disabled")) for o in item["options"]] == [("opt-no", None)]
    rows = workspace.rows(home, approved_id, pending=False)
    assert rows[-1]["kind"] == "stop" and rows[-1]["origin"] == "clicked"
    changed = answers.answer(home, approved_id, option="opt-no")
    assert changed.state == "answered"


def test_stop_it_on_a_terminal_already_closed_clears_the_hold(tmp_path, monkeypatch):
    from support import make_home

    home = make_home(tmp_path)
    _approved, approved_id = _launched(home, tmp_path, monkeypatch, state="inactive")
    answers.claim(home, approved_id, "sess-ours")
    assert answers.stop(home, approved_id) == answers.ALREADY_CLOSED_MESSAGE
    assert [c for c in _calls(tmp_path, "systemctl") if "stop" in c] == []
    assert attention._claim(home, approved_id, datetime.now(timezone.utc)) is None  # noqa: SLF001


def test_stop_it_refuses_when_the_unit_will_not_stop_and_keeps_the_claim(tmp_path, monkeypatch):
    """Mutation: skip the is-active check after `stop` -> red."""
    from support import make_home

    home = make_home(tmp_path)
    monkeypatch.setenv("SHIM_STUCK", "1")
    _approved, approved_id = _launched(home, tmp_path, monkeypatch)
    answers.claim(home, approved_id, "sess-ours")
    with pytest.raises(answers.AnswerError) as stuck:
        answers.stop(home, approved_id)
    assert stuck.value.exit_code == answers.EXIT_REFUSED and "did not stop" in str(stuck.value)
    assert attention._claim(home, approved_id, datetime.now(timezone.utc)) is not None  # noqa: SLF001


def test_stop_it_is_the_persons_click_and_needs_a_claim(tmp_path, monkeypatch, capsys):
    """Mutation: drop the agent-shell refusal in `stop` -> red."""
    from support import make_home

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _approved, approved_id = _launched(home, tmp_path, monkeypatch)
    assert cli.main(["attention", "stop", approved_id]) == answers.EXIT_REFUSED  # nothing claimed
    assert "no session has claimed it" in capsys.readouterr().err
    answers.claim(home, approved_id, "sess-ours")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["attention", "stop", approved_id]) == answers.EXIT_USAGE
    assert "refused from an agent's shell" in capsys.readouterr().err
    assert attention._claim(home, approved_id, datetime.now(timezone.utc)) is not None  # noqa: SLF001
    assert cli.main(["attention", "stop", "att-000000000000"]) == answers.EXIT_USAGE  # still refused first


# ------------------------------------------------------------------ 3. run --json


def test_attention_run_json_names_the_command_when_no_terminal_is_found(tmp_path, monkeypatch, capsys):
    """Mutation: `RunResult.to_json` without `command` -> red."""
    from support import make_home

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    (tmp_path / "shim-bin" / "alacritty").unlink()  # no terminal anywhere on PATH
    _index(home, [_system_ask("q-restart-daemon", [])])
    first = _item(home, "q-restart-daemon")
    answered = answers.answer(home, first["id"], option="opt-yes")
    assert answered.run is not None and answered.run["exit"] == answers.EXIT_NO_TERMINAL
    assert answered.run["command"].startswith("claude '") and answered.run["brief"]
    approved_id = attention.item_id("approved.pending", "q-restart-daemon")

    assert cli.main(["attention", "run", approved_id, "--json"]) == answers.EXIT_NO_TERMINAL
    printed = json.loads(capsys.readouterr().out)
    assert printed["exit"] == answers.EXIT_NO_TERMINAL
    assert printed["brief"].endswith("brief.md") and Path(printed["brief"]).is_file()
    assert printed["command"].startswith("claude '") and printed["brief"] in printed["command"]
    assert printed["command"] in printed["message"]  # the sentence still says it, for a terminal

    # Without --json the sentence goes to stderr, as before.
    assert cli.main(["attention", "run", approved_id]) == answers.EXIT_NO_TERMINAL
    out = capsys.readouterr()
    assert out.out == "" and "no terminal found" in out.err


def test_a_login_terminal_not_found_names_claude_as_the_command(tmp_path, monkeypatch):
    (tmp_path / "shim-bin" / "alacritty").unlink()
    login = {"id": "att-111111111111", "kind": "hold.credentials", "class": "needs-you",
             "subject": "credentials@x", "title": "Log in"}
    monkeypatch.setattr(answers, "_items", lambda _home: [login])
    result = answers.run(tmp_path, login["id"], login=True)
    assert result.exit == answers.EXIT_NO_TERMINAL and result.to_json()["command"] == "claude"
    assert result.to_json()["brief"] is None
