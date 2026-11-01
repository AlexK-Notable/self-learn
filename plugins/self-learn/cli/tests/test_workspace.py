"""The workspace transcript (attention round 2026-10-31c, design r2 §3.4.2;
§5.1 tests 10 and 11).

Person's-shell tests: the module fixture deletes every agent marker.
"""

from __future__ import annotations

import json

import pytest

from self_learn import attention, intents, settings, statements, workspace
from support import git, make_home
from test_lock_invariant import _Analysis
from test_recover_or_refuse import _plant_stop


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


ITEM = attention.item_id("ask.system-change", "q-workspace-test")
HEADER = {"item_kind": "ask.system-change", "subject": "q-workspace-test", "title": "A question?"}


def _rows(home):
    path = workspace.transcript_path(home, ITEM)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _restore(home, target) -> None:
    """Put the stop fixture's planted file back to its committed bytes."""
    rel = target.relative_to(home).as_posix()
    target.write_text(git(home, "show", f"HEAD:{rel}").stdout, encoding="utf-8")


def _count(home) -> int:
    return int(git(home, "rev-list", "--count", "HEAD").stdout)


# ------------------------------------------------------------------ 10


def test_append_numbers_rows_under_the_lock_and_commits(tmp_path):
    home = make_home(tmp_path)
    before = _count(home)
    assert workspace.append(home, ITEM, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "is this already done?"},
    ], header=HEADER) == [1]
    assert workspace.append(home, ITEM, [
        {"role": "agent", "origin": "agent", "kind": "answer", "text": "yes"},
        {"role": "agent", "origin": "agent", "kind": "draft", "draft_id": "drf-1a2b3c4d", "text": "No thanks."},
    ]) == [2, 3]
    rows = _rows(home)
    assert [r["t"] for r in rows] == [0, 1, 2, 3]
    assert rows[0]["kind"] == "header" and rows[0]["item_kind"] == "ask.system-change"
    assert _count(home) == before + 2
    assert git(home, "status", "--porcelain").stdout == ""
    assert git(home, "log", "-1", "--format=%s").stdout.strip() == f"self-learn: workspace {ITEM} T2-T3"


def test_a_secret_in_a_row_is_redacted_before_it_is_written(tmp_path):
    home = make_home(tmp_path)
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    assert workspace.secret_rule(f"my token is {token}") is not None
    workspace.append(home, ITEM, [
        {"role": "agent", "origin": "agent", "kind": "answer", "text": f"found {token}"},
    ], header=HEADER)
    text = workspace.transcript_path(home, ITEM).read_text(encoding="utf-8")
    assert token not in text
    row = _rows(home)[1]
    assert row["text"] is None and row["redacted"]


def test_the_lock_invariant_walker_reaches_both_appends():
    """Mutation: move `workspace.append`'s write out of `ledger_write` ->
    the walker names it (red)."""
    analysis = _Analysis()
    requires = analysis.requires_lock()
    for qual in ("workspace.append", "grant_uses.append"):
        assert qual in analysis.funcs
        # Positive control: the walker sees the writes inside it...
        assert analysis.mutations(qual, set(requires)), qual
        # ...and every one is under the lock.
        assert analysis.unguarded(qual, set(requires)) == [], qual
        assert qual not in requires, qual


def test_a_stopped_ledger_keeps_rows_pending_and_the_next_append_seals_them_first(tmp_path):
    """Mutation: drop the flush of `pending.jsonl` -> red."""
    home = make_home(tmp_path)
    workspace.append(home, ITEM, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "first"},
    ], header=HEADER)
    target = home / "user" / "stop-probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("seed\n", encoding="utf-8")
    git(home, "add", "--", str(target))
    git(home, "commit", "-q", "-m", "seed probe")
    intent = _plant_stop(home, target)
    with pytest.raises(intents.LedgerStoppedError):
        with intents.ledger_write(home):
            pass
    head = git(home, "rev-parse", "HEAD").stdout
    assert workspace.append(home, ITEM, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "kept 1"},
        {"role": "agent", "origin": "agent", "kind": "answer", "text": "kept 2"},
    ]) == []
    assert git(home, "rev-parse", "HEAD").stdout == head
    pending = workspace.pending_path(home, ITEM)
    assert [json.loads(l)["t"] for l in pending.read_text().splitlines()] == [None, None]
    shown = workspace.rows(home, ITEM)
    assert [r.get("text") for r in shown] == [None, "first", "kept 1", "kept 2"]
    assert [r["t"] for r in shown][-2:] == [None, None]

    intents.clear_stopped(home, intent.id)
    _restore(home, target)
    assert workspace.append(home, ITEM, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "after"},
    ]) == [4]
    rows = _rows(home)
    assert [(r["t"], r.get("text")) for r in rows[1:]] == [
        (1, "first"), (2, "kept 1"), (3, "kept 2"), (4, "after")]
    assert not pending.exists()


# ------------------------------------------------------------------ 11


def _seal(home, row) -> str:
    (t,) = workspace.append(home, ITEM, [row], header=HEADER)
    return f"workspace:{ITEM}#T{t}"


def _add(home, ref, verbatim):
    return statements.add(
        home, verbatim=verbatim, source={"message_ref": ref}, recorded_by="human",
        answers={"kind": "question", "ref": "q-workspace-test"},
    )


def test_a_statement_cites_only_a_typed_user_row(tmp_path):
    """Mutation: accept any origin in `_check_workspace_evidence` -> red."""
    home = make_home(tmp_path)
    reply = _seal(home, {"role": "user", "origin": "typed", "kind": "reply",
                         "text": "Yes, but only   if it doesn't restart my desktop."})
    question = _seal(home, {"role": "user", "origin": "typed", "kind": "question",
                            "text": "Is this already done?"})
    accepted = _seal(home, {"role": "user", "origin": "draft-accepted", "kind": "reply",
                            "text": "No thanks.", "draft_id": "drf-1a2b3c4d"})
    first = _add(home, reply, "only if it doesn't restart my desktop")
    assert statements.list_statements(home)[0]["source"]["message_ref"] == reply
    assert _add(home, question, "Is this already done?") != first
    with pytest.raises(statements.StatementUsageError, match="draft-accepted"):
        _add(home, accepted, "No thanks.")
    with pytest.raises(statements.StatementUsageError, match="no sealed workspace row"):
        _add(home, f"workspace:{ITEM}#T99", "anything")
    with pytest.raises(statements.StatementUsageError, match="not in workspace row"):
        _add(home, reply, "words they never typed")
    assert len(statements.list_statements(home)) == 2


def test_a_pending_row_cannot_be_cited_until_sealed(tmp_path):
    home = make_home(tmp_path)
    _seal(home, {"role": "user", "origin": "typed", "kind": "question", "text": "sealed"})
    target = home / "user" / "stop-probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("seed\n", encoding="utf-8")
    git(home, "add", "--", str(target))
    git(home, "commit", "-q", "-m", "seed probe")
    intent = _plant_stop(home, target)
    with pytest.raises(intents.LedgerStoppedError):
        with intents.ledger_write(home):
            pass
    assert workspace.append(home, ITEM, [
        {"role": "user", "origin": "typed", "kind": "reply", "text": "kept while stopped"},
    ]) == []
    intents.clear_stopped(home, intent.id)
    _restore(home, target)
    # The row is shown (pending), yet no number names it until it is sealed.
    assert [r.get("text") for r in workspace.rows(home, ITEM)][-1] == "kept while stopped"
    with pytest.raises(statements.StatementUsageError, match="no sealed workspace row"):
        _add(home, f"workspace:{ITEM}#T2", "kept while stopped")
    workspace.append(home, ITEM, [{"role": "system", "origin": "system", "kind": "note", "text": "n"}])
    assert workspace.resolve(home, f"workspace:{ITEM}#T2")["text"] == "kept while stopped"
    assert _add(home, f"workspace:{ITEM}#T2", "kept while stopped").startswith("stmt-")


def test_the_conflict_ref_form_is_accepted_for_an_instruction(tmp_path):
    """§3.4.4: a conflict ruling in words answers `conflict:<a>+<b>`.
    `statements.add` does not validate `answers.ref` by kind, so the form
    needs no widening; this pins that it stays accepted."""
    home = make_home(tmp_path)
    ref = _seal(home, {"role": "user", "origin": "typed", "kind": "reply", "text": "the newer one is right"})
    sid = statements.add(
        home, verbatim="the newer one is right", source={"message_ref": ref}, recorded_by="human",
        answers={"kind": "instruction", "ref": "conflict:stmt-0000aaaa+stmt-0000bbbb"},
    )
    (row,) = statements.list_statements(home)
    assert row["id"] == sid and row["answers"]["ref"] == "conflict:stmt-0000aaaa+stmt-0000bbbb"


def test_excerpt_labels_roles_around_a_row(tmp_path):
    home = make_home(tmp_path)
    workspace.append(home, ITEM, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "q1"},
        {"role": "agent", "origin": "agent", "kind": "answer", "text": "a1"},
        {"role": "user", "origin": "typed", "kind": "reply", "text": "r1"},
    ], header=HEADER)
    text = workspace.excerpt(home, f"workspace:{ITEM}#T2", before=1, after=1)
    assert text is not None
    lines = text.splitlines()
    assert len(lines) == 3 and lines[0].startswith("T1 you") and lines[1].startswith("T2 agent")
    assert workspace.excerpt(home, f"workspace:{ITEM}#T9") is None
