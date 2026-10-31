"""S-96: an answered overseer question stops being open
at once, releases the case that waited on it, and the user model stores a
list field given as one string as one item.

Written under the user's 2026-10-30 rule (tests run only for significant
changes): the orchestrator runs these once over the combined landing.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from self_learn import cases, ledger_ops, statements, steward, user_model, verbs
from self_learn.overseer import conversation
from self_learn.overseer import run as overseer_run
from support import commit_all, make_home
from test_overseer_conversation import _ask, _case, _reading, _report_and_index
from test_steward import _dump_yaml
from test_steward_refusals import _case as _steward_case
from test_steward_refusals import _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _two_questions(tmp_path: Path):
    """A report listing one ask and one reading, both indexed."""
    home = make_home(tmp_path)
    proposition = f"{_reading(home, 1)}@r1"
    reading_case = _case(home, tmp_path, "1", {"user_model": [proposition]})
    ask_case = _case(home, tmp_path, "2", {})
    ask = _ask("q-diagram-skill", [ask_case])
    _report_and_index(
        home,
        [{"id": proposition, "kind": "reading", "cases": [reading_case]}, ask],
        [f"- {proposition}: Does this apply everywhere?", "- q-diagram-skill: scaffold it?"],
    )
    return home, proposition, ask, ask_case


def test_an_answered_ask_is_no_longer_counted_or_listed(tmp_path):
    home, proposition, ask, ask_case = _two_questions(tmp_path)
    # Positive control: before any answer both questions are open and shown.
    assert conversation.open_question_count(home) == 2
    first = io.StringIO()
    assert conversation.open_questions(home, out=first) == 2
    assert "q-diagram-skill" in first.getvalue() and proposition in first.getvalue()

    conversation.respond(home, proposition="q-diagram-skill", scope="user", text="Yes, build it.")

    assert conversation.open_question_count(home) == 1
    second = io.StringIO()
    assert conversation.open_questions(home, out=second) == 1
    shown = second.getvalue()
    assert shown.startswith("## Questions for you\n")
    assert proposition in shown  # the unanswered reading is still listed
    assert "q-diagram-skill" not in shown  # neither its report line nor its text
    assert ask["text"] not in shown
    # Not presented again: only the first `open` recorded a presentation.
    assert len(cases.show(home, ask_case, evidence_only=False).frontmatter["presented"]) == 1


def test_an_answered_reading_is_no_longer_counted_or_listed(tmp_path):
    home, proposition, _ask_row, _ask_case = _two_questions(tmp_path)
    conversation.open_questions(home, out=io.StringIO())

    conversation.respond(home, proposition=proposition, scope="user", text="Yes", as_asked="Apply?")

    assert conversation.open_question_count(home) == 1
    out = io.StringIO()
    conversation.open_questions(home, out=out)
    assert proposition not in out.getvalue()
    assert "q-diagram-skill" in out.getvalue()


def test_when_every_question_is_answered_the_block_says_none(tmp_path):
    home, _proposition, _ask_row, _ask_case = _two_questions(tmp_path)
    conversation.open_questions(home, out=io.StringIO())
    conversation.respond(home, proposition="q-diagram-skill", scope="user", text="Yes.")
    conversation.respond(home, proposition=_proposition, scope="user", text="Yes", as_asked="Apply?")

    assert conversation.open_question_count(home) == 0
    out = io.StringIO()
    assert conversation.open_questions(home, out=out) == 0
    assert out.getvalue() == "## Questions for you\n- none\n"


def test_a_new_index_written_after_the_answer_asks_the_question_again(tmp_path):
    home, _proposition, _ask_row, _ask_case = _two_questions(tmp_path)
    conversation.open_questions(home, out=io.StringIO())
    conversation.respond(home, proposition="q-diagram-skill", scope="user", text="Yes.")
    assert conversation.open_question_count(home) == 1  # control: answered

    index = home / "overseer" / "open-questions.yaml"
    later = index.stat().st_mtime + 3600
    os.utime(index, (later, later))  # a weekly run rewrote the index

    assert conversation.open_question_count(home) == 2


def test_the_answer_stays_in_the_store_for_the_next_weekly_run(tmp_path):
    home, _proposition, _ask_row, _ask_case = _two_questions(tmp_path)
    conversation.open_questions(home, out=io.StringIO())
    result = conversation.respond(home, proposition="q-diagram-skill", scope="user", text="Yes.")

    kept = [row for row in overseer_run._question_answers(home) if row["ref"] == "q-diagram-skill"]
    assert [row["id"] for row in kept] == [result.statement_id]
    assert kept[0]["verbatim"] == "Yes."
    assert any(row["id"] == result.statement_id for row in statements.list_statements(home))


def test_an_unreadable_statement_store_leaves_the_questions_listed(tmp_path):
    home, _proposition, _ask_row, _ask_case = _two_questions(tmp_path)
    (home / "user-statements.jsonl").write_text("{not json\n", encoding="utf-8")
    assert conversation.open_question_count(home) == 2


# ---- 2. an answer releases the case that deferred a lesson on it


def _deferred_case(home: Path, tmp_path: Path) -> tuple[str, str]:
    rid = _seed(home, "lrn-d0a00001")
    case = _steward_case([rid], "defer", "defer", scope="user")
    case["trigger"] = "weekly"
    stage = tmp_path / "defer-case.yaml"
    _dump_yaml(stage, case)
    case_id = cases.record(home, stage, actor="overseer")
    verbs.defer(home, rid, until="2099-01-01", by="steward", no_push=True)
    return rid, case_id


def test_an_answer_to_an_ask_brings_a_deferred_lesson_back_to_the_steward(tmp_path):
    home = make_home(tmp_path)
    rid, case_id = _deferred_case(home, tmp_path)
    # Control: a deferred lesson whose case saw nothing new is not brought back.
    assert steward._reconsider_proposals(home)[0] == []

    ask = _ask("q-diagram-skill", [case_id])
    _report_and_index(home, [ask], ["- q-diagram-skill: scaffold it?"])
    conversation.open_questions(home, out=io.StringIO())
    conversation.respond(home, proposition="q-diagram-skill", scope="user", text="Yes.")

    ((entry, _card),) = steward._reconsider_proposals(home)[0]
    assert (entry.record.id, entry.record.status) == (rid, "deferred")
    assert entry.predecessor == case_id


def test_an_answer_does_not_bring_back_a_case_that_did_not_defer(tmp_path):
    """A case that decided something else has acted on its question's answer
    already; only a deferral waits on one."""
    home = make_home(tmp_path)
    rid = _seed(home, "lrn-d0a00002")
    case = _steward_case([rid], "reject", "reject", scope="user")
    stage = tmp_path / "reject-case.yaml"
    _dump_yaml(stage, case)
    case_id = cases.record(home, stage, actor="overseer")
    verbs.reject(home, rid, by="steward", no_push=True)

    _report_and_index(home, [_ask("q-diagram-skill", [case_id])], ["- q-diagram-skill: scaffold it?"])
    conversation.open_questions(home, out=io.StringIO())
    conversation.respond(home, proposition="q-diagram-skill", scope="user", text="Yes.")

    assert ledger_ops.find_record_path(home, rid) is not None  # control: the lesson exists
    assert steward._reconsider_proposals(home)[0] == []


# ---- 3. the user model's list fields


def _add(home: Path, **extra) -> str:
    return user_model.add_entry(
        home, container="D", title="a regularity", because="a dated statement supports it",
        source="system-reading", by="overseer", statements=["stmt-00000001"],
        ref="case-00000001", **extra,
    )


def _entry(home: Path, entry_id: str) -> dict:
    for entries in user_model.show(home)["containers"].values():
        for entry in entries:
            if entry["id"] == entry_id:
                return entry
    raise AssertionError(entry_id)


def test_a_basis_given_as_one_string_is_stored_as_one_item(tmp_path):
    home = make_home(tmp_path)
    entry_id = _add(home, basis="Bears on the question bar: decide and report")
    assert _entry(home, entry_id)["basis"] == ["Bears on the question bar: decide and report"]
    text = (home / "user-model.md").read_text(encoding="utf-8")
    assert "- basis: [Bears on the question bar: decide and report]" in text


def test_a_conditions_or_statements_string_is_one_item_too(tmp_path):
    home = make_home(tmp_path)
    entry_id = user_model.add_entry(
        home, container="D", title="a regularity", because="a dated statement supports it",
        source="system-reading", by="overseer", statements="stmt-00000001",
        ref="case-00000001", conditions="the repo stays private",
    )
    entry = _entry(home, entry_id)
    assert entry["statements"] == ["stmt-00000001"]
    assert entry["conditions"] == ["the repo stays private"]


def test_a_list_field_that_is_not_text_is_refused_before_any_write(tmp_path):
    home = make_home(tmp_path)
    before = (home / "user-model.md").read_text(encoding="utf-8") if (home / "user-model.md").exists() else None
    with pytest.raises(user_model.UserModelUsageError):
        _add(home, basis={"a": "b"})
    with pytest.raises(user_model.UserModelUsageError):
        _add(home, basis=["fine", 3])
    after = (home / "user-model.md").read_text(encoding="utf-8") if (home / "user-model.md").exists() else None
    assert before == after


_SPELLED = "- basis: [B, e, a, r, s, o, n, t, h, e, q, u, e, s, t, i, o, n, ., P, r, o]"


def test_a_basis_spelled_one_character_at_a_time_heals_on_read_and_on_the_next_write(tmp_path):
    """um-cea0 (2026-10-11): a string was iterated as a list. The malformed
    entry reads back as the one string it spells, and the next write of the
    document stores it that way."""
    home = make_home(tmp_path)
    healthy = _add(home, basis=["one reason", "another reason"])
    broken = _add(home)
    path = home / "user-model.md"
    text = path.read_text(encoding="utf-8")
    block_end = text.index("- provisional", text.index(f"### {broken}"))
    path.write_text(text[:block_end] + _SPELLED + "\n" + text[block_end:], encoding="utf-8")
    commit_all(home, "plant the malformed entry")

    assert _entry(home, broken)["basis"] == ["Bearsonthequestion.Pro"]
    # Control: a real list, and its commas, are left alone.
    assert _entry(home, healthy)["basis"] == ["one reason", "another reason"]

    user_model.add_entry(
        home, container="D", title="another", because="a dated statement supports it",
        source="system-reading", by="overseer", statements=["stmt-00000002"], ref="case-00000002",
    )
    stored = path.read_text(encoding="utf-8")
    assert _SPELLED not in stored
    assert "- basis: [Bearsonthequestion.Pro]" in stored
    assert "- basis: [one reason, another reason]" in stored
