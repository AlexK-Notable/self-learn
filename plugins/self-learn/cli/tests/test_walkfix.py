"""Walk fixes of the attention round (S-NEXT-walkfix; the source-blind
walk of 2026-11-01, misc/build-2026-10-31c/walk-attention.md).

The CLI halves of the fixes:

* item 2: one provenance rule -- ``attention_answers.preview`` (what the
  page shows before sending) and ``answer`` (what is recorded) decide the
  origin by the same function, so the page is never more generous than
  the record (C6);
* item 3: ``answer --words-from T`` sends an option with words the person
  already sent, citing their statement, never a second one;
* item 5: an undone decided item says what it changes now; a hook item's
  title names what the lesson is about, not its id;
* item 6: a lesson's title is its trigger and it lists its sightings; a
  conflict's two quotes say which is newer; a hook item leads with the
  trigger and instruction; a folder is said to be one, its path with ~;
  a statement whose conversation is gone says so in words.

Every test is a person's shell (the fixtures of test_attention_answers
remove the agent markers and put logging shims on a hermetic PATH) unless
it sets a marker itself. Each test names the mutation it was checked
against.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from self_learn import attention, attention_answers as answers, attention_packet, statements, workspace
from support import make_env, make_home
from test_attention_answers import (  # noqa: F401 -- person/shims are autouse fixtures
    DRAFT,
    _agent,
    _calls,
    _choices,
    _index,
    _item,
    _iso,
    _seal_agent,
    _stead_ask,
    _stmts,
    _system_ask,
    person,
    shims,
)

# ------------------------------------------------------------ item 2


def test_the_preview_and_the_record_agree_on_every_origin(tmp_path):
    """The page's line before sending and the record after it come from
    one rule. For each reply shape, preview's origin and words equal what
    `answer` then records. Mutations: drop the paste match from
    `_origin_of` -> red here and in the paste test; make preview call a
    copy of the old rule without the draft branch -> red."""
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    _seal_agent(home, item, DRAFT, draft="drf-1a2b3c4d")
    shapes = [
        {"text": "Build it, but only after the move."},
        {"text": f"Sure. {DRAFT[:45]} and so on."},
        {"draft_id": "drf-1a2b3c4d"},
        {"draft_id": "drf-1a2b3c4d", "text": "Keep it for now."},
    ]
    seen = []
    for shape in shapes:
        before = answers.preview(home, item["id"], **shape)
        after = answers.answer(home, item["id"], **shape)
        assert before["recorded_as"] == after.recorded_as, shape
        seen.append(before["origin"])
    assert seen == ["typed", "draft-edited", "draft-accepted", "draft-edited"]


def test_the_preview_names_the_agents_words_it_matched(tmp_path):
    """Walk item 2, step 6: own words around a pasted run of the agent's
    text read "the agent's draft, edited", and the preview says which words
    made the match. Mutation: return no `matched` -> red."""
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    _seal_agent(home, item, DRAFT)

    mine = answers.preview(home, item["id"], text="Both hold: ask me only when it needs me.")
    pasted = answers.preview(home, item["id"], text=f"I agree. {DRAFT[:50]}")

    assert mine["origin"] == "typed" and mine["matched"] is None  # control
    assert pasted["origin"] == "draft-edited"
    assert pasted["matched"] == " ".join(DRAFT[:50].split())
    assert pasted["recorded_as"] == "as the agent's draft, edited and sent by you"


def test_the_preview_says_what_would_be_refused_and_records_nothing(tmp_path):
    """An unknown draft and a secret are problems, not origins, and a
    preview writes nothing. Mutation: let `_origin_of`'s refusal escape
    `preview` -> red (it raises)."""
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    empty = answers.preview(home, item["id"], text="   ")
    unknown = answers.preview(home, item["id"], draft_id="drf-00000000")
    secret = answers.preview(home, item["id"], text="my key is sk-ant-api03-" + "A" * 90)

    assert empty == {"origin": None, "recorded_as": None, "matched": None, "problem": None}
    assert unknown["origin"] is None and "names no sealed draft" in unknown["problem"]
    assert secret["origin"] is None and "secret scan" in secret["problem"]
    assert _stmts(home) == [] and _choices(home) == []
    assert workspace.rows(home, item["id"]) == []


# ------------------------------------------------------------ item 3


def _plan_item(tmp_path: Path) -> tuple[Path, dict]:
    home = make_home(tmp_path)
    ask = _system_ask("q-restart-daemon", [])
    ask["options"] = [*ask["options"], {"id": "opt-yes-conditions", "label": "Yes, with conditions",
                                        "effect": "approve", "note": "required"}]
    _index(home, [ask])
    return home, _item(home, "q-restart-daemon")


def test_words_sent_before_become_the_options_note_without_a_second_statement(tmp_path):
    """Walk item 3: words sent alone, then "Yes, with conditions" with
    those words (`--words-from T`): one statement only, the choice cites
    it, the approval's conditions are the words. Mutations: record a new
    statement for reused words -> red; drop the choice's `statement` ->
    red; skip the note-required check's view of the reused text -> red
    (refused)."""
    home, item = _plan_item(tmp_path)
    words = answers.answer(home, item["id"], text="Only if it does not restart my session.")
    assert words.statement is not None and words.state == "open"  # control: words alone

    result = answers.answer(home, item["id"], option="opt-yes-conditions",
                            words_from=words.transcript_row)

    assert [s["id"] for s in _stmts(home)] == [words.statement]
    (choice,) = _choices(home)
    assert choice["how"] == "clicked" and choice["statement"] == words.statement
    assert choice["text"] == "Only if it does not restart my session."
    assert result.recorded_as == "as your choice of the offered option, with the words you sent before"
    approved = _item(home, "q-restart-daemon", "approved.pending")
    assert approved["_conditions"] == "Only if it does not restart my session."
    row = workspace.resolve(home, f"workspace:{item['id']}#T{result.transcript_row}")
    assert row is not None and row["origin"] == "clicked" and row["words_from"] == words.transcript_row


def test_words_from_names_only_the_persons_own_reply(tmp_path, monkeypatch):
    """A row that is not a typed reply without an option (an agent's
    answer, a pasted reply, a typed note that already went with a choice),
    a missing option, extra text, and an agent's shell are refused, and
    nothing is recorded. Mutations: drop the origin check in
    `_reused_words` -> red; drop its option check -> red (gate r1 F6, C6c);
    drop the agent-shell refusal -> red."""
    home, item = _plan_item(tmp_path)
    _seal_agent(home, item, DRAFT)
    agent_t = max(r["t"] for r in workspace.rows(home, item["id"]))
    # A reply that pasted the agent's text: the person's row, but the
    # agent's words (origin draft-edited), never reusable as their words.
    pasted = answers.answer(home, item["id"], text=f"Fine. {DRAFT[:45]}")
    assert workspace.resolve(home, f"workspace:{item['id']}#T{pasted.transcript_row}")[
        "origin"] == "draft-edited"  # control
    # The person's typed words that already went with a choice, as its
    # note: they are that choice's, never offered again as a reply.
    workspace.append(home, item["id"], [{"role": "user", "origin": "typed", "kind": "reply",
                                         "text": "Only on weekdays.", "option": "opt-no"}],
                     header={"item_kind": item["kind"], "subject": item["subject"],
                             "title": item["title"]})
    noted_t = max(r["t"] for r in workspace.rows(home, item["id"]))
    assert workspace.resolve(home, f"workspace:{item['id']}#T{noted_t}")["option"] == "opt-no"
    words = answers.answer(home, item["id"], text="My own words.")
    before = (len(_stmts(home)), len(_choices(home)))

    for kwargs in (
        {"option": "opt-yes-conditions", "words_from": agent_t},
        {"option": "opt-yes-conditions", "words_from": pasted.transcript_row},
        {"option": "opt-yes-conditions", "words_from": noted_t},
        {"option": "opt-yes-conditions", "words_from": 999},
        {"words_from": words.transcript_row},
        {"option": "opt-yes-conditions", "words_from": words.transcript_row, "text": "x"},
    ):
        with pytest.raises(answers.AnswerError) as refused:
            answers.answer(home, item["id"], **kwargs)
        assert refused.value.exit_code == 64, kwargs
    _agent(monkeypatch)
    with pytest.raises(answers.AnswerError) as agent:
        answers.answer(home, item["id"], option="opt-yes-conditions",
                       words_from=words.transcript_row, note="n")
    assert agent.value.exit_code == 64 and "--words-from is the person's click" in str(agent.value)
    assert (len(_stmts(home)), len(_choices(home))) == before


# ------------------------------------------------------------ items 5 and 6


def _hook_world(tmp_path: Path, monkeypatch) -> tuple[Path, str, dict]:
    from self_learn import verbs
    from self_learn.ledger_ops import create_record
    from support import commit_all, make_behavior

    env = make_env(tmp_path)
    home = env.ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    lesson = "lrn-0000bbbb"
    record = make_behavior(scope="user", record_id=lesson,
                           trigger="About to edit Home Assistant's .storage files.",
                           instruction="Stop the container first.")
    # Routed to a hook (the packet reads its script path and registration).
    record._fm["routing"] = {  # noqa: SLF001 -- a test record
        "destination": "hook", "by": "overseer", "routed_at": _iso(-timedelta(hours=2)),
        "hook": {"script_path": "hooks/self-learn/guard.sh", "event": "PreToolUse",
                 "matcher": "Edit"},
    }
    create_record(home, record)
    commit_all(home, "seed the lesson")
    runs = home / "cases" / "runs"
    runs.mkdir(parents=True)
    at = _iso(-timedelta(hours=1))
    (runs / "run-bbbbbbbbbbbb.json").write_text(json.dumps({
        "version": 1, "actor": "overseer", "run_id": "run-bbbbbbbbbbbb", "ledger_effects": [],
        "status": "complete", "last_attempt_at": at, "week": at[:10],
        "attention_effects": [{"lesson": lesson, "verb": "route", "destination": "hook",
                               "always_loaded": False, "hook_activated": True, "at": at}],
    }), encoding="utf-8")
    monkeypatch.setattr(verbs, "hook_deactivate", lambda h, rid, **kw: None)
    monkeypatch.setattr(verbs, "hook_activate", lambda h, rid, **kw: None)
    return home, lesson, _item(home, f"{lesson}@{at}")


def test_an_undone_hook_says_it_changes_nothing_now_and_a_redo_restores_it(tmp_path, monkeypatch):
    """Walk item 5: after "Turn it off" the item's "what it changes now"
    and meanwhile describe the undone state (in the reader and the packet);
    after "Turn it back on" the original words return. Mutation: skip the
    UNDONE_NOW substitution in `collect` -> red."""
    home, _lesson, hook = _hook_world(tmp_path, monkeypatch)
    assert hook["_decided"]["changes_now"] == "the hook runs on matching tool calls"  # control

    answers.undo(home, hook["id"])
    undone = _item(home, hook["subject"])
    packet = attention_packet.build(home, hook["id"])
    assert undone["meanwhile"] == attention.UNDONE_NOW["decided.hook-activated"]
    assert packet["decided"]["changes_now"] == attention.UNDONE_NOW["decided.hook-activated"]
    assert packet["meanwhile"].startswith("Nothing now: you turned the hook off")

    answers.undo(home, hook["id"], redo=True)
    assert _item(home, hook["subject"])["_decided"]["changes_now"] == "the hook runs on matching tool calls"


def test_a_hook_item_names_its_lesson_in_words_and_leads_with_its_rule(tmp_path, monkeypatch):
    """Walk items 5 and 6: the title says what the lesson is about, not its
    id; the hook evidence comes first and carries the trigger and the
    instruction; the lesson is not repeated under the script. Mutations:
    title by id -> red; hook evidence without trigger -> red; keep the
    lesson entry -> red."""
    home, lesson, hook = _hook_world(tmp_path, monkeypatch)

    assert hook["title"] == ("The overseer turned on a hook: About to edit Home Assistant's "
                             ".storage files.")
    assert lesson not in hook["title"] and lesson not in hook["_decided"]["what"]
    packet = attention_packet.build(home, hook["id"])
    first = packet["evidence"][0]
    assert first["kind"] == "hook" and first["record"] == lesson
    assert first["trigger"] == "About to edit Home Assistant's .storage files."
    assert first["instruction"] == "Stop the container first."
    assert not [e for e in packet["evidence"] if e["kind"] == "lesson" and e["id"] == lesson]


def test_a_lessons_title_is_its_trigger_and_it_lists_when_it_was_seen(tmp_path, monkeypatch):
    """Walk item 6: "came up at least twice" can be checked -- a lesson
    entry lists its sightings (newest first, with the quote), and its
    title is the trigger, not the heading's name "Trigger". Mutations:
    title from the first line -> red ("Trigger"); drop `seen` -> red."""
    from self_learn.ledger_ops import create_record
    from support import commit_all, make_behavior

    env = make_env(tmp_path)
    record = make_behavior(scope="user", record_id="lrn-0000cccc",
                           trigger="An update to intel-ucode comes up.",
                           instruction="Treat it as harmless.")
    record._fm["sightings"] = 2  # noqa: SLF001 -- a test record
    record._fm["evidence"] = [  # noqa: SLF001
        {"session": "s-old", "ts": "2026-10-01T10:00:00Z", "quote": "it was fine last time"},
        {"session": "s-new", "ts": "2026-10-20T10:00:00Z", "quote": "harmless again"},
    ]
    create_record(env.ledger, record)
    commit_all(env.ledger, "seed")
    limits = attention_packet._Limits()  # noqa: SLF001
    entry = attention_packet._lesson(env.ledger, "lrn-0000cccc", limits, "evidence[0]")  # noqa: SLF001

    assert entry is not None and entry["title"] == "An update to intel-ucode comes up."
    assert entry["trigger"] == "An update to intel-ucode comes up."
    assert entry["sightings"] == 2
    assert [(s["at"], s["quote"]) for s in entry["seen"]] == [
        ("2026-10-20T10:00:00Z", "harmless again"), ("2026-10-01T10:00:00Z", "it was fine last time")]


def _conflict(tmp_path: Path, older_at: str, newer_at: str) -> tuple[Path, dict, str, str]:
    home = make_home(tmp_path)
    older = statements.add(home, verbatim="unless sudo is involved, never say X is waiting on you",
                           source={"message_ref": "transcript:gone-older#L3"}, recorded_by="human")
    newer = statements.add(home, verbatim="legit things that need my attention are fine",
                           source={"message_ref": "transcript:gone-newer#L9"}, recorded_by="human")
    path = home / "user-statements.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row["at"] = {older: older_at, newer: newer_at}.get(row["id"], row["at"])
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    _index(home, [{
        "id": "q-which-holds", "kind": "ask", "cases": [], "statements": [older, newer],
        "text": "Two things you said disagree. Which one holds?", "why": "both are yours",
        "needs": "user", "because": "conflict", "default": "The newer one holds meanwhile.",
        "options": [{"id": "opt-newer", "label": "The newer one is right", "effect": "other"},
                    {"id": "opt-older", "label": "The older one still holds", "effect": "other"}],
        "recommend": {"option": "opt-newer", "reasoning": "r"},
    }])
    return home, _item(home, "q-which-holds"), older, newer


def test_a_conflicts_quotes_say_which_one_is_newer(tmp_path):
    """Walk item 6: each quote carries `side` by when it was said (whatever
    order the ask names them in), with the words the options use; equal
    times mark neither. Mutations: mark by the ask's order instead of
    time, either way round -> red (the second case names the newer one
    first; gate r1 F6, C13b); drop `_mark_conflict_sides` -> red."""
    home, item, older, newer = _conflict(tmp_path, "2026-10-30T15:13:00Z", "2026-10-30T19:58:00Z")
    packet = attention_packet.build(home, item["id"])
    sides = {e["id"]: e.get("side") for e in packet["evidence"] if e["kind"] == "statement"}
    assert sides == {older: "older", newer: "newer"}

    # The ask names the NEWER statement first: its first-named quote is
    # the one said later, so only the times can tell.
    flip_home, flip_item, first, second = _conflict(tmp_path / "flip", "2026-10-30T19:58:00Z",
                                                    "2026-10-30T15:13:00Z")
    flipped = attention_packet.build(flip_home, flip_item["id"])
    assert {e["id"]: e.get("side") for e in flipped["evidence"] if e["kind"] == "statement"} == {
        first: "newer", second: "older"}

    same_home, same_item, a, b = _conflict(tmp_path / "same", "2026-10-30T15:13:00Z",
                                           "2026-10-30T15:13:00Z")
    same = attention_packet.build(same_home, same_item["id"])
    assert {e["id"]: e.get("side") for e in same["evidence"] if e["kind"] == "statement"} == {
        a: None, b: None}


def test_a_statement_whose_conversation_is_gone_says_so_in_words(tmp_path):
    """Walk item 6: the RefError the walk saw was the sandbox citing
    sessions that did not exist; on a real machine a transcript can be
    deleted too, and the page must say so in words, not an exception's
    class name. Mutation: restore `f"not read ({type(exc).__name__})"` ->
    red."""
    home, item, _older, _newer = _conflict(tmp_path, "2026-10-30T15:13:00Z", "2026-10-30T19:58:00Z")
    packet = attention_packet.build(home, item["id"])
    notes = [e["context_note"] for e in packet["evidence"] if e["kind"] == "statement"]
    assert len(notes) == 2
    for note in notes:
        assert "RefError" not in note and "Error" not in note
        assert note.startswith("not found on this machine")


def test_a_folder_in_the_evidence_is_said_to_be_one_with_its_path_from_home(tmp_path, monkeypatch):
    """Walk item 6: the bus item's evidence read "The file <cut path>" over
    a bare listing. A folder is marked `is_dir`, and `display` writes the
    home folder as ~ with the whole path kept. Mutation: drop `is_dir` ->
    red; display = path -> red."""
    fake_home = tmp_path / "home"
    folder = fake_home / ".config" / "systemd" / "user"
    (folder / "oo7-daemon.service.d").mkdir(parents=True)
    (folder / "oo7-daemon.service").write_text("[Unit]\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    entry = attention_packet._file(str(folder), attention_packet._Limits(), "evidence[0]")  # noqa: SLF001
    plain = attention_packet._file(str(folder / "oo7-daemon.service"), attention_packet._Limits(), "e")  # noqa: SLF001

    assert entry["is_dir"] is True and entry["display"] == "~/.config/systemd/user"
    assert entry["excerpt"].splitlines() == ["oo7-daemon.service", "oo7-daemon.service.d/"]
    assert plain["is_dir"] is False and plain["display"] == "~/.config/systemd/user/oo7-daemon.service"


# ------------------------------------------------------------ gate r1 F4


def test_a_new_terminal_while_this_approvals_terminal_is_open_says_so_in_words(tmp_path, monkeypatch):
    """Gate r1 F4: "Open a new terminal" two minutes after a launch, while
    the terminal launched for this approval is still open (it may be
    waiting at a prompt): one bounded `systemctl --user is-active` on this
    approval's own unit, no second `systemd-run`, and a plain sentence
    saying a terminal for it is already open, never systemd's own error.
    A unit still stopping ("deactivating") counts as open. Once that unit
    is gone, a new terminal opens. Mutations: skip the is-active check ->
    red; check it before any launch (no run record) -> red (the approval's
    first launch is refused); drop "deactivating" from the open states ->
    red (gate r2 N3)."""
    from test_followups2 import _launched

    home = make_home(tmp_path)
    _approved, approved_id = _launched(home, tmp_path, monkeypatch, state="active")
    launches = len(_calls(tmp_path, "systemd-run"))
    assert launches == 1  # control: the approval opened one terminal

    result = answers.run(home, approved_id)

    assert result.exit == 3 and result.already_open is True
    assert result.message == answers.ALREADY_OPEN_MESSAGE
    assert "already open" in result.message and "systemd" not in result.message
    assert result.to_json()["already_open"] is True
    assert len(_calls(tmp_path, "systemd-run")) == launches
    assert ["systemctl", "--user", "is-active", attention.run_unit(approved_id)] in _calls(
        tmp_path, "systemctl")

    (tmp_path / "unit-state").write_text("deactivating\n", encoding="utf-8")
    stopping = answers.run(home, approved_id)
    assert stopping.exit == 3 and stopping.already_open is True
    assert len(_calls(tmp_path, "systemd-run")) == launches

    (tmp_path / "unit-state").write_text("inactive\n", encoding="utf-8")
    again = answers.run(home, approved_id)
    assert again.exit == 0 and again.already_open is False
    assert len(_calls(tmp_path, "systemd-run")) == launches + 1


# ------------------------------------------------------------ gate r2 N1


DRAFTED = "Only the first two steps, please; leave the binary check out of it for now."


def test_an_approval_sent_with_the_agents_draft_needs_confirm_at_the_verb(tmp_path):
    """Gate r2 N1: the verb itself refuses an approve option that comes
    with the agent's draft, whether the option is named or taken from the
    draft, unless `confirm` is passed; nothing is recorded and no terminal
    opens. With `confirm` it is recorded as the agent's draft, accepted.
    So a page that forgot the draft's option (blocked storage) still
    cannot approve in one step. Mutation: drop the verb's draft check ->
    red."""
    home, item = _plan_item(tmp_path)
    _seal_agent(home, item, DRAFTED, draft="drf-1a2b3c4d", option="opt-yes-conditions")
    before = (len(_stmts(home)), len(_choices(home)))

    for kwargs in ({"draft_id": "drf-1a2b3c4d"},
                   {"draft_id": "drf-1a2b3c4d", "option": "opt-yes-conditions"},
                   {"draft_id": "drf-1a2b3c4d", "option": "opt-yes"}):
        with pytest.raises(answers.AnswerError) as refused:
            answers.answer(home, item["id"], **kwargs)
        assert refused.value.exit_code == 3, kwargs
        assert answers.DRAFT_NEEDS_CONFIRM in str(refused.value)
    assert (len(_stmts(home)), len(_choices(home))) == before
    assert _calls(tmp_path, "systemd-run") == []
    assert _item(home, "q-restart-daemon")["state"] == "open"

    sent = answers.answer(home, item["id"], draft_id="drf-1a2b3c4d", confirm=True)
    choice = _choices(home)[-1]
    assert (choice["option"], choice["how"], choice["text"]) == (
        "opt-yes-conditions", "draft-accepted", DRAFTED)
    assert sent.recorded_as == "as the agent's draft, accepted by you"
