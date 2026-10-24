"""Write-time statement evidence checks, with synthetic transcript roots."""
import json
from pathlib import Path
import re

import pytest

from self_learn import refs, statements, steward, steward_prompt
from support import commit_all, make_home
from test_steward import (
    SimulatedKill, _dump_yaml, _enable_steward, _seed_fresh_proposals,
    _write_decision_stage,
)


def transcript(home, tmp_path):
    root = tmp_path / "transcripts"
    path = root / "project" / "synthetic-stmt.jsonl"
    path.parent.mkdir(parents=True)
    entries = [
        {"type": "user", "message": {"content": "Keep it small."}},
        {"type": "user", "message": {"content": "<agent-message>Build this.</agent-message>"}},
        {"type": "user", "isMeta": True, "message": {"content": "Skill instructions."}},
        {"type": "assistant", "message": {"content": "I will build it."}},
        {"type": "user", "isSidechain": True, "message": {"content": "Worker reply."}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "result"}]}},
    ]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    with (home / "config.yaml").open("a") as f:
        f.write(f"\nrefs:\n  transcript_roots: {json.dumps(str(root))}\n")
    commit_all(home, "configure synthetic transcript roots")
    assert refs.transcript_roots(home) == [root]
    return path, root


def add(home, ref, text="Keep it small."):
    return statements.add(home, verbatim=text, source={"message_ref": ref}, recorded_by="human")


@pytest.mark.parametrize("line,role", [(2, "agent"), (3, "relay"), (4, "assistant"),
                                        (5, "subagent"), (6, "tool_result")])
def test_new_statement_refuses_non_user_after_user_positive_control(tmp_path, line, role):
    home = make_home(tmp_path)
    _, root = transcript(home, tmp_path)
    accepted = add(home, "transcript:synthetic-stmt#L1")
    assert statements.list_statements(home)[0]["id"] == accepted
    assert refs.resolve("synthetic-stmt", line=line, roots=[root]).role == role
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match=f"found {role}"):
        add(home, f"transcript:synthetic-stmt#L{line}")
    assert (home / "user-statements.jsonl").read_bytes() == before


@pytest.mark.parametrize("ref", ["transcript:deleted-session#L1", "transcript:synthetic-stmt#L99",
                                 "conversation:obs-1234abcd"])
def test_unresolvable_and_conversation_refs_remain_accepted(tmp_path, ref):
    home = make_home(tmp_path)
    transcript(home, tmp_path)
    first = add(home, "transcript:synthetic-stmt#L1")
    assert statements.list_statements(home)[0]["id"] == first
    second = add(home, ref)
    assert [r["id"] for r in statements.list_statements(home)] == [first, second]


def test_existing_statement_read_dedupe_and_recovery_do_not_recheck(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    path, _ = transcript(home, tmp_path)
    ref = "transcript:synthetic-stmt#L1"
    sid = add(home, ref)
    assert statements.list_statements(home)[0]["id"] == sid
    path.write_text(json.dumps({"type": "assistant", "message": {"content": "Changed."}}) + "\n")
    before = (home / "user-statements.jsonl").read_bytes()

    def must_not_resolve(*args, **kwargs):
        pytest.fail("existing statements must never be re-checked")

    monkeypatch.setattr(refs, "resolve", must_not_resolve)
    assert add(home, ref) == sid
    operation = {"kind": "statement", "payload": {"verbatim": "Keep it small.",
                                                 "source": {"message_ref": ref}}}
    assert steward._maintenance_result(home, operation) == {
        "state": "applied", "id": sid, "recovered": True}
    assert (home / "user-statements.jsonl").read_bytes() == before


def test_steward_apply_refuses_agent_after_user_positive_control(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    transcript(home, tmp_path)

    def write_stage(spec):
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        assert match
        _dump_yaml(Path(match[1]) / "statements.yaml", {"items": [
            {"verbatim": "Keep it small.", "source": {"message_ref": "transcript:synthetic-stmt#L1"}},
            {"verbatim": "Build this.", "source": {"message_ref": "transcript:synthetic-stmt#L2"}},
        ]})
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)
    result = steward.run(home)
    rows = statements.list_statements(home)
    assert len(rows) == 1 and rows[0]["recorded_by"] == "steward"
    assert rows[0]["source"]["message_ref"] == "transcript:synthetic-stmt#L1"
    assert result.status == "partial" and result.refused == 1
    assert "found agent" in steward.journal_path(home).read_text()


def test_steward_owner_commit_recovery_survives_changed_role(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    path, _ = transcript(home, tmp_path)

    def write_stage(spec):
        outcome = _write_decision_stage(spec)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        assert match
        _dump_yaml(Path(match[1]) / "statements.yaml", {"items": [
            {"verbatim": "Keep it small.", "source": {"message_ref": "transcript:synthetic-stmt#L1"}},
        ]})
        return outcome

    real_update = steward._update_manifest

    def kill(home_arg, run_id, *, reason, update):
        if reason.startswith("maintenance result"):
            raise SimulatedKill()
        return real_update(home_arg, run_id, reason=reason, update=update)

    monkeypatch.setattr(steward.invocation, "write_session", write_stage)
    monkeypatch.setattr(steward, "_update_manifest", kill)
    with pytest.raises(SimulatedKill):
        steward.run(home)
    assert len(statements.list_statements(home)) == 1
    before = (home / "user-statements.jsonl").read_bytes()
    path.write_text(json.dumps({"type": "assistant", "message": {"content": "Changed."}}) + "\n")
    monkeypatch.setattr(steward, "_update_manifest", real_update)
    assert steward.run(home).status == "applied"
    assert (home / "user-statements.jsonl").read_bytes() == before


def test_statement_role_rule_is_in_steward_contract():
    contract = steward_prompt._render_output_contract()
    assert "statements.yaml --" in contract
    assert "A statement’s `transcript:` ref must point to a line whose evidence role is `user`." in contract


def question_exchange(home, tmp_path):
    path, _ = transcript(home, tmp_path)
    sid = add(home, "transcript:synthetic-stmt#L1")
    assert statements.list_statements(home)[0]["id"] == sid
    questions = [{"question": "Which route should we take?", "header": "Route",
                  "options": [{"label": "Short route", "description": "Cross the bridge."},
                              {"label": "Long, scenic route", "description": "Follow the river."}],
                  "multiSelect": False}]
    rows = [
        {"type": "user", "message": {"content": "Keep it small."}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "question-1", "name": "AskUserQuestion",
             "input": {"questions": questions}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "question-1",
             "content": "User has answered your questions."}]},
         "toolUseResult": {"questions": questions, "answers": {
             questions[0]["question"]: "Keep typed words."}, "annotations": {}}},
    ]
    return path, rows, questions[0]


def write_question_exchange(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.parametrize("kind", ["other", "multi-other", "notes", "whitespace", "label-in-note"])
def test_typed_question_answer_is_accepted(tmp_path, kind):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    result = rows[2]["toolUseResult"]
    quote = "Keep typed words."
    if kind == "multi-other":
        question["multiSelect"] = True
        result["answers"][question["question"]] = "Short route, Long, scenic route, " + quote
    elif kind in ("notes", "label-in-note"):
        result["answers"][question["question"]] = "Short route"
        if kind == "label-in-note":
            quote = "Short route"
        result["annotations"][question["question"]] = {"preview": "model preview", "notes": quote}
    elif kind == "whitespace":
        result["answers"][question["question"]] = "Before: Keep\n\t typed   words. After."
        quote = "Keep  typed\nwords."
    write_question_exchange(path, rows)
    assert refs.resolve("synthetic-stmt", line=3, roots=[path.parent.parent]).role == "tool_result"
    sid = add(home, "transcript:synthetic-stmt#L3", quote)
    assert statements.list_statements(home)[-1]["id"] == sid


@pytest.mark.parametrize("kind", [
    "label", "description", "question", "multi-label", "preview", "wrapper", "read",
    "wrong-id", "missing-call", "different-questions", "error", "bad-answers",
    "case", "punctuation", "cross-answer-note", "overlapping-labels",
])
def test_question_non_typed_words_are_refused_after_typed_control(tmp_path, kind):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    write_question_exchange(path, rows)
    control = add(home, "transcript:synthetic-stmt#L3", "Keep typed words.")
    assert statements.list_statements(home)[-1]["id"] == control
    result = rows[2]["toolUseResult"]
    block = rows[2]["message"]["content"][0]
    result["answers"][question["question"]] = "Short route"
    quote = "Short route"
    if kind == "description":
        quote = "Cross the bridge."
    elif kind == "question":
        quote = question["question"]
    elif kind == "multi-label":
        question["multiSelect"] = True
        result["answers"][question["question"]] = "Short route, Long, scenic route"
        quote = "scenic route"
    elif kind == "preview":
        quote = "Only model preview."
        result["annotations"][question["question"]] = {"preview": quote}
    elif kind == "wrapper":
        quote = "Only wrapper words."
        block["content"] = quote
    elif kind in ("read", "wrong-id", "missing-call", "different-questions", "error", "bad-answers"):
        quote = "New typed words."
        result["answers"][question["question"]] = quote
        if kind == "read":
            rows[1]["message"]["content"][0]["name"] = "Read"
            block["content"] = quote
        elif kind == "wrong-id":
            block["tool_use_id"] = "unrelated-tool"
        elif kind == "missing-call":
            rows[1]["message"]["content"] = []
        elif kind == "different-questions":
            result["questions"] = []
        elif kind == "error":
            block["is_error"] = True
        else:
            result["answers"] = quote
    elif kind in ("case", "punctuation"):
        result["answers"][question["question"]] = "Typed exactly!"
        quote = "typed exactly!" if kind == "case" else "Typed exactly."
    elif kind == "cross-answer-note":
        quote = "route Some note"
        result["annotations"][question["question"]] = {"notes": "Some note"}
    elif kind == "overlapping-labels":
        question["multiSelect"] = True
        question["options"] = [{"label": label, "description": "An option."}
                               for label in ("A", "A, B", "B, C")]
        result["answers"][question["question"]] = "A, B, C"
        quote = "C"
    write_question_exchange(path, rows)
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="found tool_result.*not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", quote)
    assert (home / "user-statements.jsonl").read_bytes() == before


def test_typed_question_exception_is_in_steward_contract():
    contract = steward_prompt._render_output_contract()
    assert "statements.yaml --" in contract
    assert ("Exception: a matched `AskUserQuestion` tool result may supply only words typed "
            "in an Other answer or added note, never clicked option text.") in contract
