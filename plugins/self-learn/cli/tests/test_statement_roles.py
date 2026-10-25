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
    assert 'Exception: a matched interactive `AskUserQuestion` tool result may supply human-provided Other/text/number answers, freeform responses or added notes, never clicked option text, SDK/model answers or agent-written text.' in contract


@pytest.mark.parametrize("kind", [
    "sdk-result", "sdk-session", "sdk-later", "sdk-prompt-result", "sdk-prompt-session",
    "model-answers", "model-annotations", "agent-answer", "agent-note", "agent-response",
    "suggestion", "herdr-answer", "herdr-note", "system-result", "afk",
])
def test_question_author_must_be_human_after_positive_control(tmp_path, kind):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    rows[2].update(sessionId="synthetic-stmt", timestamp="2026-10-24T12:00:01Z")
    write_question_exchange(path, rows)
    control = add(home, "transcript:synthetic-stmt#L3", "Keep typed words.")
    assert statements.list_statements(home)[-1]["id"] == control
    quote = "New typed words."
    result = rows[2]["toolUseResult"]
    result["answers"][question["question"]] = quote
    if kind == "sdk-result":
        rows[2]["entrypoint"] = "sdk-py"
    elif kind == "sdk-session":
        rows[0]["entrypoint"] = "sdk-cli"
    elif kind == "sdk-later":
        rows.append({"type": "system", "entrypoint": "sdk-py"})
    elif kind == "sdk-prompt-result":
        rows[2]["promptSource"] = "sdk"
    elif kind == "sdk-prompt-session":
        rows[0]["promptSource"] = "sdk"
    elif kind in ("model-answers", "model-annotations"):
        key = kind.removeprefix("model-")
        rows[1]["message"]["content"][0]["input"][key] = result[key]
    elif kind.startswith("agent-"):
        tagged = f"<agent-message>{quote}</agent-message>"
        if kind == "agent-answer":
            result["answers"][question["question"]] = tagged
        elif kind == "agent-note":
            result["answers"][question["question"]] = "Short route"
            result["annotations"][question["question"]] = {"notes": tagged}
        else:
            result["answers"] = {}
            result["response"] = tagged
    elif kind == "suggestion":
        rows[2]["promptSource"] = "suggestion_accepted"
    elif kind.startswith("herdr-"):
        if kind == "herdr-note":
            result["answers"][question["question"]] = "Short route"
            result["annotations"][question["question"]] = {"notes": quote}
        sender = {"type": "assistant", "sessionId": "sender", "timestamp": "2026-10-24T12:00:00Z",
                  "message": {"content": [{"type": "tool_use", "id": "send", "name": "Bash",
                      "input": {"command": f'herdr pane send-text pane "{quote}"'}}]}}
        (path.parent / "sender.jsonl").write_text(json.dumps(sender) + "\n")
    elif kind == "system-result":
        rows[2]["promptSource"] = "system"
    else:
        result["afkTimeoutMs"] = 1000
    write_question_exchange(path, rows)
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="found tool_result.*not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", quote)
    assert (home / "user-statements.jsonl").read_bytes() == before


@pytest.mark.parametrize("kind", ["overlap-min", "join-free-note"])
def test_question_gate_surviving_mutants_are_killed(tmp_path, kind):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    result = rows[2]["toolUseResult"]
    if kind == "overlap-min":
        question["multiSelect"] = True
        question["options"] = [{"label": "A"}, {"label": "A, B"}]
        result["answers"][question["question"]] = "A, B, typed"
        accepted_quote, refused_quote = "typed", "B, typed"
    else:
        result["answers"][question["question"]] = "Typed answer"
        result["annotations"][question["question"]] = {"notes": "Typed note"}
        accepted_quote, refused_quote = "Typed answer", "answer Typed note"
    write_question_exchange(path, rows)
    control = add(home, "transcript:synthetic-stmt#L3", accepted_quote)
    assert statements.list_statements(home)[-1]["id"] == control
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", refused_quote)


@pytest.mark.parametrize("kind", [
    "permission-user", "permission-result", "utf8-user", "utf8-result", "null-before",
    "null-target", "vanish-locate", "vanish-read", "corrupt-json", "corrupt-scalar", "changed-role",
])
def test_transcript_damage_is_a_named_refusal_after_positive_control(tmp_path, monkeypatch, kind):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    write_question_exchange(path, rows)
    control = add(home, "transcript:synthetic-stmt#L3", "Keep typed words.")
    assert statements.list_statements(home)[-1]["id"] == control
    rows[2]["toolUseResult"]["answers"][question["question"]] = "New typed words."
    write_question_exchange(path, rows)
    line = 1 if kind.endswith("user") or kind == "changed-role" else 3
    cause = ""
    if kind.startswith("permission"):
        statements._check_evidence(home, f"transcript:synthetic-stmt#L{line}", "New typed words.")
        path.chmod(0)
        cause = "permission denied"
    elif kind.startswith("utf8"):
        path.write_bytes(path.read_bytes() + b'\xff\n')
        cause = "invalid UTF-8"
    elif kind == "null-before":
        rows[1:1] = [{"type": "assistant", "message": None}]
        write_question_exchange(path, rows)
        line, cause = 4, "malformed transcript message"
    elif kind == "null-target":
        rows[2]["message"] = None
        write_question_exchange(path, rows)
        cause = "malformed transcript message"
    elif kind in ("vanish-locate", "vanish-read", "changed-role"):
        resolve = refs.resolve
        def after_resolve(*args, **kwargs):
            ref = resolve(*args, **kwargs)
            if kind == "changed-role":
                rows[line - 1] = {"type": "assistant", "message": {"content": "Changed."}}
                write_question_exchange(path, rows)
            elif kind == "vanish-locate":
                path.unlink()
            return ref
        monkeypatch.setattr(refs, "resolve", after_resolve)
        if kind == "vanish-read":
            locate = refs.locate
            def after_locate(*args, **kwargs):
                found = locate(*args, **kwargs)
                found.unlink()
                return found
            monkeypatch.setattr(refs, "locate", after_locate)
        cause = "changed between reads" if kind == "changed-role" else "disappeared"
    else:
        lines = path.read_text().splitlines()
        lines[2] = "{broken" if kind == "corrupt-json" else "null"
        path.write_text("\n".join(lines) + "\n")
        cause = "corrupt target row"
    before = (home / "user-statements.jsonl").read_bytes()
    try:
        with pytest.raises(statements.StatementUsageError, match=cause):
            add(home, f"transcript:synthetic-stmt#L{line}", "New typed words.")
        assert (home / "user-statements.jsonl").read_bytes() == before
    finally:
        if path.exists():
            path.chmod(0o600)


@pytest.mark.parametrize("kind", ["note-no-answer", "text", "number", "response", "preview-dropped", "kind-added"])
def test_supported_human_question_shapes_are_accepted(tmp_path, kind):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    write_question_exchange(path, rows)
    control = add(home, "transcript:synthetic-stmt#L3", "Keep typed words.")
    assert statements.list_statements(home)[-1]["id"] == control
    result = rows[2]["toolUseResult"]
    quote = "New typed words."
    if kind == "note-no-answer":
        result["answers"][question["question"]] = None
        result["annotations"][question["question"]] = {"notes": quote}
    elif kind in ("text", "number"):
        question["kind"] = kind
        question["options"] = []
        if kind == "number":
            question.update(min=0, max=100)
            quote = "42"
        result["answers"][question["question"]] = quote
    elif kind == "response":
        result["answers"] = {}
        result["response"] = quote
    else:
        result["answers"][question["question"]] = quote
        result["questions"] = json.loads(json.dumps(result["questions"]))
        if kind == "preview-dropped":
            question["options"][0]["preview"] = "A model-generated preview."
        else:
            result["questions"][0]["kind"] = "choice"
    write_question_exchange(path, rows)
    sid = add(home, "transcript:synthetic-stmt#L3", quote)
    assert statements.list_statements(home)[-1]["id"] == sid


@pytest.mark.parametrize("separator", ["\u2028", "\r"], ids=["unicode", "carriage-return"])
def test_question_reader_uses_refs_line_boundaries(tmp_path, separator):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    write_question_exchange(path, rows)
    assert add(home, "transcript:synthetic-stmt#L3", "Keep typed words.")
    # The Unicode separator is a line boundary in this branch's refs reader;
    # after the lineno merge refs will keep it inside the JSON string.
    rows[0]["message"]["content"] = "Before" + separator + "after"
    rows[2]["toolUseResult"]["answers"][question["question"]] = "New typed words."
    read_row = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "read", "content": "New typed words."}]},
        "toolUseResult": {"type": "text"}}
    rows.insert(2 if separator == "\u2028" else 3, read_row)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).replace("\\r", "\r"))
    # Ask refs which row holds each result rather than implementing line splitting.
    logical = refs._lines(path)
    result_line = next(i for i, raw in enumerate(logical, 1) if '"type": "text"' in raw)
    assert refs.resolve("synthetic-stmt", line=result_line, roots=[path.parent.parent]).role == "tool_result"
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, f"transcript:synthetic-stmt#L{result_line}", "New typed words.")


def test_statement_evidence_resolution_runs_without_commit_lock(tmp_path, monkeypatch):
    from self_learn import gitops
    home = make_home(tmp_path)
    transcript(home, tmp_path)
    resolve = refs.resolve
    seen = []
    def outside_lock(*args, **kwargs):
        assert str(gitops.commit_lock_path(home)) not in gitops._held_locks
        seen.append(True)
        return resolve(*args, **kwargs)
    monkeypatch.setattr(refs, "resolve", outside_lock)
    sid = add(home, "transcript:synthetic-stmt#L1")
    assert statements.list_statements(home)[-1]["id"] == sid
    assert seen == [True]


def test_concurrent_duplicate_wins_over_deferred_evidence_failure(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    transcript(home, tmp_path)
    ref = "transcript:synthetic-stmt#L1"
    real_check = statements._check_evidence
    recorded = []
    def concurrent_check(*args, **kwargs):
        monkeypatch.setattr(statements, "_check_evidence", real_check)
        recorded.append(add(home, ref))
        raise statements.StatementUsageError("deferred evidence failure")
    monkeypatch.setattr(statements, "_check_evidence", concurrent_check)
    assert add(home, ref) == recorded[0]
    assert [r["id"] for r in statements.list_statements(home)] == recorded


@pytest.mark.parametrize("kind", ["question-text", "option-label"])
def test_question_binding_requires_question_text_and_labels(tmp_path, kind):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    write_question_exchange(path, rows)
    assert add(home, "transcript:synthetic-stmt#L3", "Keep typed words.")
    result = rows[2]["toolUseResult"]
    result["answers"][question["question"]] = "New typed words."
    result["questions"] = json.loads(json.dumps(result["questions"]))
    if kind == "question-text":
        result["questions"][0]["question"] = "A different question?"
    else:
        result["questions"][0]["options"][0]["label"] = "A different option"
    write_question_exchange(path, rows)
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", "New typed words.")


def encoded_question_control(tmp_path):
    home = make_home(tmp_path)
    path, rows, question = question_exchange(home, tmp_path)
    write_question_exchange(path, rows)
    sid = add(home, "transcript:synthetic-stmt#L3", "Keep typed words.")
    assert statements.list_statements(home)[-1]["id"] == sid
    return home, path, rows, question


def cc_multi_answer(items):
    # Claude Code 2.1.310 ODt: JSON-quote items holding a comma-space or quote.
    return ", ".join(json.dumps(item, ensure_ascii=False)
                     if ', ' in item or '"' in item else item for item in items)


@pytest.mark.parametrize("kind", ["pair", "single", "quote", "prefix", "unicode"])
def test_encoded_clicked_labels_are_refused(tmp_path, kind):
    home, path, rows, question = encoded_question_control(tmp_path)
    question["multiSelect"] = True
    label = {"quote": 'Use the "fast" path', "unicode": "Long, café route"}.get(
        kind, "Long, scenic route")
    question["options"][1]["label"] = label
    items = ["Short route", label] if kind == "pair" else [label]
    if kind == "prefix":
        items.append("A fresh typed answer.")
    rows[2]["toolUseResult"]["answers"][question["question"]] = cc_multi_answer(items)
    write_question_exchange(path, rows)
    quote = 'Use the' if kind == "quote" else label
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", quote)
    assert (home / "user-statements.jsonl").read_bytes() == before


@pytest.mark.parametrize("kind", ["single-double-space", "single-tab", "multi-double-space"])
def test_displayed_clicked_labels_are_refused(tmp_path, kind):
    # Claude Code records a clicked label as displayed: whitespace runs
    # collapse to one space (gate-stmt-r3 MINOR D, probes D1, D4, D2).
    home, path, rows, question = encoded_question_control(tmp_path)
    label = {"single-tab": "Ship it\tnow"}.get(kind, "Ship it  now")
    shown = "Ship it now"
    question["options"][1]["label"] = label
    if kind.startswith("multi"):
        question["multiSelect"] = True
        label = "Long,  scenic route"
        question["options"][1]["label"] = label
        shown = "Long, scenic route"
        answer = cc_multi_answer(["Short route", shown])
    else:
        answer = shown
    rows[2]["toolUseResult"]["answers"][question["question"]] = answer
    write_question_exchange(path, rows)
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", shown)
    assert (home / "user-statements.jsonl").read_bytes() == before


@pytest.mark.parametrize("quote, typed_by_user", [
    ("My own words", True), ("(Image attached)", False), ("words (Image attached)", False)])
def test_single_select_image_suffix_is_not_typed(tmp_path, quote, typed_by_user):
    # Claude Code appends " (Image attached)" to a typed single-select answer
    # when an image was pasted (gate-stmt-r3 NIT 1).
    home, path, rows, question = encoded_question_control(tmp_path)
    rows[2]["toolUseResult"]["answers"][question["question"]] = "My own words (Image attached)"
    write_question_exchange(path, rows)
    if typed_by_user:
        sid = add(home, "transcript:synthetic-stmt#L3", quote)
        assert statements.list_statements(home)[-1]["id"] == sid
        return
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", quote)
    assert (home / "user-statements.jsonl").read_bytes() == before


@pytest.mark.parametrize("typed", ['Say "hi" now', '"Fast" is what I said'])
def test_legacy_typed_other_with_quotes_is_accepted(tmp_path, typed):
    # Older transcripts joined multi-select items unquoted; a typed leftover
    # that is not one whole JSON string stays the user's words.
    home, path, rows, question = encoded_question_control(tmp_path)
    question["multiSelect"] = True
    rows[2]["toolUseResult"]["answers"][question["question"]] = "Short route, " + typed
    write_question_exchange(path, rows)
    sid = add(home, "transcript:synthetic-stmt#L3", typed)
    assert statements.list_statements(home)[-1]["id"] == sid


@pytest.mark.parametrize("kind", ["quote", "comma", "quoted-prefix"])
def test_encoded_other_answers_are_accepted(tmp_path, kind):
    home, path, rows, question = encoded_question_control(tmp_path)
    question["multiSelect"] = True
    typed = 'Say "hello" first' if kind == "quote" else "Go north, then east"
    prefix = "Long, scenic route" if kind == "quoted-prefix" else "Short route"
    rows[2]["toolUseResult"]["answers"][question["question"]] = cc_multi_answer([prefix, typed])
    write_question_exchange(path, rows)
    sid = add(home, "transcript:synthetic-stmt#L3", typed)
    assert statements.list_statements(home)[-1]["id"] == sid


@pytest.mark.parametrize("field", ["response", "followUp"])
def test_host_supplied_call_fields_are_refused(tmp_path, field):
    home, path, rows, question = encoded_question_control(tmp_path)
    typed = "New host supplied words."
    rows[1]["message"]["content"][0]["input"][field] = typed if field == "response" else True
    rows[2]["toolUseResult"]["answers"] = {}
    rows[2]["toolUseResult"]["response"] = typed
    write_question_exchange(path, rows)
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", typed)
    assert (home / "user-statements.jsonl").read_bytes() == before


@pytest.mark.parametrize("kind", ["text", "number"])
def test_text_number_kind_with_options_cannot_authorize_clicked_label(tmp_path, kind):
    home, path, rows, question = encoded_question_control(tmp_path)
    call_question = json.loads(json.dumps(question))
    call_question["kind"] = kind
    rows[1]["message"]["content"][0]["input"]["questions"] = [call_question]
    rows[2]["toolUseResult"]["answers"][question["question"]] = "Short route"
    write_question_exchange(path, rows)
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", "Short route")
    assert (home / "user-statements.jsonl").read_bytes() == before


@pytest.mark.parametrize("placeholder", ["(notes only)", "(Image attached)", "__other__"])
@pytest.mark.parametrize("field", ["answer", "multi-answer", "notes", "response"])
def test_question_placeholders_are_not_typed(tmp_path, placeholder, field):
    home, path, rows, question = encoded_question_control(tmp_path)
    result = rows[2]["toolUseResult"]
    result["answers"] = {}
    if field in ("answer", "multi-answer"):
        question["multiSelect"] = field == "multi-answer"
        result["answers"][question["question"]] = (
            cc_multi_answer(["Short route", placeholder]) if question["multiSelect"] else placeholder)
    elif field == "notes":
        result["annotations"][question["question"]] = {"notes": placeholder}
    else:
        result["response"] = placeholder
    write_question_exchange(path, rows)
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L3", placeholder)
    assert (home / "user-statements.jsonl").read_bytes() == before


def test_question_call_after_target_cannot_authorize_answer(tmp_path):
    home, path, rows, question = encoded_question_control(tmp_path)
    rows[2]["toolUseResult"]["answers"][question["question"]] = "Fresh future call words."
    rows.append(rows.pop(1))
    write_question_exchange(path, rows)
    before = (home / "user-statements.jsonl").read_bytes()
    with pytest.raises(statements.StatementUsageError, match="not typed by the user"):
        add(home, "transcript:synthetic-stmt#L2", "Fresh future call words.")
    assert (home / "user-statements.jsonl").read_bytes() == before
