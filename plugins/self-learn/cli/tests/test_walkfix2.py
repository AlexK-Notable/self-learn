"""The inbox after a second source-blind walk (walk 2 of 2026-11-01,
misc/build-2026-11-01/walk2-attention.md): the CLI halves.

* D5 (C6: a click is a choice, typed words are the person's, an agent's
  draft is the agent's): "Send the draft as is" on a needs-you item with a
  plan, no option, is RECORDED as the agent's draft (the walk's "Recorded
  as your words" was the page's receipt, not the record); an approval's
  conditions carry whose words they are (``conditions_how``), so the
  carried-out page never labels the agent's draft as the person's.
* D3 ("Change my answer"): ``attention_answers.answered_item`` finds an
  answered ask whose answer can still change (by id, or by the subject an
  approved item shares), read-only, public fields only.

Every test is a person's shell (test_attention_answers' autouse fixtures
remove the agent markers and put logging shims on a hermetic PATH). Each
test names the mutation it was checked against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import attention, attention_answers as answers, attention_packet, workspace
from support import make_home
from test_attention_answers import (  # noqa: F401 -- person/shims are autouse fixtures
    _choices,
    _index,
    _item,
    _seal_agent,
    _stmts,
    _system_ask,
    person,
    shims,
)

_CONDITIONS = "Yes, but only if it does not restart my desktop session."


def _plan_item(tmp_path: Path) -> tuple[Path, dict]:
    home = make_home(tmp_path)
    ask = _system_ask("q-restart-daemon", [])
    ask["options"] = [*ask["options"], {"id": "opt-yes-conditions", "label": "Yes, with conditions",
                                        "effect": "approve", "note": "required"}]
    _index(home, [ask])
    return home, _item(home, "q-restart-daemon")


# ------------------------------------------------------------ D5


def test_the_draft_sent_as_is_on_a_plan_item_is_recorded_as_the_agents_draft(tmp_path):
    """Walk 2 #015: "Send the draft as is" (the draft id, no option, no
    edit) on a needs-you item with a plan. The record is the agent's draft
    accepted by the person: the transcript row's origin, the choice row's
    `how`, `recorded_as`, and no statement of the person's words. Nothing
    is decided (the item stays open). Mutation: record a draft with no
    option as typed (origin `typed` in `_origin_of`'s draft branch) -> red."""
    home, item = _plan_item(tmp_path)
    _seal_agent(home, item, _CONDITIONS, draft="drf-0a1b2c3d")

    result = answers.answer(home, item["id"], draft_id="drf-0a1b2c3d")

    assert result.state == "open"  # control: words alone decide nothing on a plan
    assert result.recorded_as == "as the agent's draft, accepted by you"
    assert result.statement is None and _stmts(home) == []
    (choice,) = _choices(home)
    assert choice["how"] == "draft-accepted" and choice["option"] is None
    assert choice["offered_by"] == "agent" and choice["text"] == _CONDITIONS
    row = workspace.resolve(home, f"workspace:{item['id']}#T{result.transcript_row}")
    assert row is not None and row["origin"] == "draft-accepted" and row["draft_id"] == "drf-0a1b2c3d"


def test_an_approvals_conditions_say_whose_words_they_are(tmp_path):
    """Walk 2 #019: the carried-out page printed the agent's draft under
    "Your conditions:". The approved item's packet now says whose words
    the conditions are, from the approval's own record: the agent's draft
    accepted, the person's typed words, or the words they sent before
    (their statement). Mutations: drop `conditions_how` from the packet ->
    red; call every condition the person's (`typed`) -> red."""
    home, item = _plan_item(tmp_path)
    _seal_agent(home, item, _CONDITIONS, draft="drf-0a1b2c3d", option="opt-yes-conditions")
    answers.answer(home, item["id"], draft_id="drf-0a1b2c3d", confirm=True)
    approved = _item(home, "q-restart-daemon", "approved.pending")
    plan = attention_packet.build(home, approved["id"])["plan"]
    assert plan["conditions"] == _CONDITIONS  # control: the draft became the conditions
    assert plan["conditions_how"] == "draft-accepted"

    home2, item2 = _plan_item(tmp_path / "typed")
    answers.answer(home2, item2["id"], option="opt-yes-conditions", text="Only on weekdays.")
    typed = attention_packet.build(home2, _item(home2, "q-restart-daemon", "approved.pending")["id"])
    assert typed["plan"]["conditions"] == "Only on weekdays."
    assert typed["plan"]["conditions_how"] == "typed"

    home3, item3 = _plan_item(tmp_path / "reused")
    words = answers.answer(home3, item3["id"], text="Leave the .d folder alone.")
    answers.answer(home3, item3["id"], option="opt-yes-conditions", words_from=words.transcript_row)
    reused = attention_packet.build(home3, _item(home3, "q-restart-daemon", "approved.pending")["id"])
    assert reused["plan"]["conditions_how"] == "typed"

    home4, item4 = _plan_item(tmp_path / "bare")
    answers.answer(home4, item4["id"], option="opt-yes")
    bare = attention_packet.build(home4, _item(home4, "q-restart-daemon", "approved.pending")["id"])
    assert bare["plan"]["conditions"] is None and bare["plan"]["conditions_how"] is None


def test_conditions_provenance_reads_the_choice_row():
    """The one rule: a click citing a statement is typed words; drafts and
    relays say so; anything else is unknown, never the person's. Mutation:
    return `typed` for a click with no statement -> red."""
    rule = attention.conditions_provenance
    assert rule({"how": "clicked", "statement": "stmt-1"}) == "typed"
    assert rule({"how": "draft-accepted", "statement": None}) == "draft-accepted"
    assert rule({"how": "draft-edited"}) == "draft-edited"
    assert rule({"how": "relayed", "statement": "stmt-2"}) == "relayed"
    assert rule({"how": "clicked", "statement": None}) == "unknown"


# ------------------------------------------------------------ D3


def test_an_answered_ask_can_be_found_to_change_the_answer(tmp_path):
    """Walk 2 D3: after a No the ask leaves the list, but a later answer
    still replaces it; `answered_item` finds it by its id with its options
    and no private fields, and by subject after an approval was withdrawn
    (the approved item has its own id). An ask still open is not "answered"
    by subject. Mutations: return None for an answered ask -> red; keep
    the private fields -> red; skip the still-open check -> red."""
    home, item = _plan_item(tmp_path)
    assert answers.answered_item(home, subject="q-restart-daemon") is None  # still open

    answers.answer(home, item["id"], option="opt-no")
    assert not [i for i in attention.read(home)["items"] if i["id"] == item["id"]]  # control
    found = answers.answered_item(home, item_id=item["id"])
    assert found is not None and found["id"] == item["id"]
    assert [o["id"] for o in found["options"]] == ["opt-yes", "opt-no", "opt-yes-conditions"]
    assert not [k for k in found if k.startswith("_")]
    assert answers.answered_item(home, subject="q-restart-daemon")["id"] == item["id"]

    # The answer changes: approve now (the newest answer counts).
    answers.answer(home, item["id"], option="opt-yes", launch=False)
    approved = _item(home, "q-restart-daemon", "approved.pending")
    answers.answer(home, approved["id"], option="opt-no")
    again = answers.answered_item(home, subject=approved["subject"])
    assert again is not None and again["id"] == item["id"]
    assert answers.answered_item(home, item_id="att-000000000000") is None


def test_the_conflict_side_the_page_names_is_the_verbs(tmp_path):
    """The page's receipt says which statement holds by the verb's own
    rule. Mutation: swap newer and older in `conflict_side` -> red."""
    assert answers.conflict_side({"id": "opt-newer", "label": "Keep the newer one: never ask"}) == "newer"
    assert answers.conflict_side({"id": "opt-older", "label": "Keep the older one"}) == "older"
    assert answers.conflict_side({"id": "opt-both", "label": "Both"}) == "both"
    assert answers.conflict_side(None) == "both"


# ------------------------------------------------------------ gate r1 F1, F4


def _calls_of(tmp_path: Path, name: str) -> list[list[str]]:
    from test_attention_answers import _calls

    return _calls(tmp_path, name)


def test_a_stale_ask_id_answers_by_the_approved_items_rules(tmp_path):
    """Gate r1 F1: an old tab still showing the open question sends its
    answer to the ask's id after the person approved it elsewhere. The
    verb answers it as the approved item: a live claim refuses a
    withdrawal (nothing recorded), an approval is not sent twice, and once
    the work was carried out nothing starts it over. `answered_item` gives
    nothing for that ask, and `ask_successor` names the item that took it
    over. Mutations: drop the redirect to the approved item -> red (the
    claimed work is declined); drop the carried-out refusal -> red (a new
    terminal); drop `answered_item`'s listed-subject check -> red."""
    home, item = _plan_item(tmp_path)
    answers.answer(home, item["id"], option="opt-yes", launch=False)
    approved = _item(home, "q-restart-daemon", "approved.pending")
    answers.claim(home, approved["id"], "sess-busy")
    before = len(_choices(home))

    assert answers.answered_item(home, item_id=item["id"]) is None
    assert answers.ask_successor(home, item["id"])["id"] == approved["id"]
    with pytest.raises(answers.AnswerError) as claimed:
        answers.answer(home, item["id"], option="opt-no")
    assert claimed.value.exit_code == 3 and "sess-busy" in str(claimed.value)
    with pytest.raises(answers.AnswerError) as again:
        answers.answer(home, item["id"], option="opt-yes")
    assert again.value.exit_code == 3 and "is already approved" in str(again.value)
    assert len(_choices(home)) == before  # nothing recorded
    assert [i["kind"] for i in attention.collect(home, all_items=True)
            if i["subject"] == "q-restart-daemon"] == ["approved.pending"]  # control: still there

    answers.done(home, approved["id"], session="sess-busy", note="did it")
    launches = len(_calls_of(tmp_path, "systemd-run"))
    for option in ("opt-yes", "opt-no"):
        with pytest.raises(answers.AnswerError) as finished:
            answers.answer(home, item["id"], option=option)
        assert finished.value.exit_code == 3
        assert "already carried out" in str(finished.value)
    assert len(_calls_of(tmp_path, "systemd-run")) == launches  # no new terminal
    assert [i["kind"] for i in attention.collect(home, all_items=True)
            if i["subject"] == "q-restart-daemon"] == ["decided.approved-done"]
    assert answers.answered_item(home, item_id=item["id"]) is None


def test_a_stale_ask_id_withdraws_unclaimed_work_as_the_approved_item(tmp_path):
    """Gate r1 F1: unclaimed, the old tab's No is the approved item's own
    change of mind (recorded on that item, the approval withdrawn), never
    a second answer beside it. Mutation: drop the redirect -> red (the
    choice lands on the ask's id)."""
    home, item = _plan_item(tmp_path)
    answers.answer(home, item["id"], option="opt-yes", launch=False)
    approved = _item(home, "q-restart-daemon", "approved.pending")
    result = answers.answer(home, item["id"], option="opt-no")
    assert result.item == approved["id"] and result.state == "answered"
    assert _choices(home)[-1]["item"] == approved["id"]
    assert not [i for i in attention.collect(home, all_items=True)
                if i["subject"] == "q-restart-daemon"]


def test_words_typed_with_an_option_are_reusable_without_a_second_statement(tmp_path):
    """Gate r1 F4 (the orchestrator's ruling): after "Change my answer",
    the note typed with the first option is the person's own words and may
    be the next option's note by reference: one statement, cited by both
    choices. Mutation: refuse a typed row that carries an option -> red."""
    home, item = _plan_item(tmp_path)
    first = answers.answer(home, item["id"], option="opt-no", text="Not while I am at work.")
    assert first.statement is not None and len(_stmts(home)) == 1  # control
    result = answers.answer(home, item["id"], option="opt-yes-conditions",
                            words_from=first.transcript_row, launch=False)
    assert [s["id"] for s in _stmts(home)] == [first.statement]
    assert _choices(home)[-1]["statement"] == first.statement
    assert _choices(home)[-1]["text"] == "Not while I am at work."
    assert result.recorded_as == "as your choice of the offered option, with the words you sent before"


# ------------------------------------------------------------ gate r2


_OPTS_R2 = [{"id": "opt-yes", "label": "Yes, restart it", "effect": "approve"},
            {"id": "opt-no", "label": "No, leave it", "effect": "decline"},
            {"id": "opt-other", "label": "Something else", "effect": "other", "note": "required"}]


def test_a_stale_reused_note_is_refused_never_read_in_the_approved_items_rows(tmp_path):
    """Gate r2 R2-F1 (the gate's `words` case): the ask's T1 and the
    approved item's T1 are different words. An old tab's "use these words"
    (`--words-from 1` on the ask's id) is refused before the redirect, in
    plain words, and records nothing; it never takes the approved item's
    T1 as the note. Mutation: drop the refusal -> red (the choice lands on
    the approved item with "Leave the .d folder alone.")."""
    home = make_home(tmp_path)
    _index(home, [_system_ask("q-restart-daemon", [], options=_OPTS_R2)])
    ask = _item(home, "q-restart-daemon")
    ask_t = answers.answer(home, ask["id"], text="Only on weekdays.").transcript_row
    answers.answer(home, ask["id"], option="opt-yes", launch=False)
    approved = _item(home, "q-restart-daemon", "approved.pending")
    approved_t = answers.answer(home, approved["id"], text="Leave the .d folder alone.").transcript_row
    assert ask_t == approved_t  # control: one number, two transcripts, two texts
    assert [r["text"] for r in workspace.rows(home, approved["id"]) if r.get("t") == approved_t] == [
        "Leave the .d folder alone."]
    before = len(_choices(home))
    with pytest.raises(answers.AnswerError) as stale:
        answers.answer(home, ask["id"], option="opt-other", words_from=ask_t)
    assert stale.value.exit_code == 3
    assert f"the note offered with this answer was sent on {ask['id']}" in str(stale.value)
    assert approved["id"] in str(stale.value) and len(_choices(home)) == before
