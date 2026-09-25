"""O-5 conversation surface guards (S-65/S-66)."""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, statements, user_model
from self_learn.overseer import conversation
from self_learn.overseer import cli as overseer_cli
from support import commit_all, make_home


def _yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = YAML()
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)


def _case(home: Path, tmp_path: Path, suffix: str, dependencies: dict) -> str:
    stage = tmp_path / f"case-{suffix}.yaml"
    _yaml(
        stage,
        {
            "kind": "resolution",
            "trigger": "weekly",
            "outcome": "no-action",
            "records": [f"lrn-{suffix:0>8}"],
            "scope": "user",
            "question": "Should this reading guide later decisions?",
            "evidence": [{"ref": "transcript:conversation#L1", "quote": "the user's words"}],
            "decision": {
                "verb": "no-action",
                "because": "the proposition is decision-relevant",
                "confidence": "settled",
            },
            "dependencies": {
                "statements": dependencies.get("statements", []),
                "user_model": dependencies.get("user_model", []),
                "conditions": [],
                "capabilities": [],
            },
        },
    )
    return cases.record(home, stage, actor="overseer")


def _reading(home: Path, n: int) -> str:
    return user_model.add_entry(
        home,
        container="C",
        title=f"system reading {n}",
        because="a dated statement supports this reading",
        source="system-reading",
        by="overseer",
        statements=[f"stmt-{n:08x}"],
        ref=f"case-{n:08x}",
    )


def _report_and_index(home: Path, questions: list[dict], block: list[str]) -> None:
    overseer = home / "overseer"
    overseer.mkdir(parents=True, exist_ok=True)
    (overseer / "latest-report.md").write_text(
        "# Overseer report\n\n## Examined\n- one\n\n"
        "## Questions for you\n"
        + "\n".join(block)
        + "\n\n## Refused / could not do\n- none\n",
        encoding="utf-8",
    )
    _yaml(overseer / "open-questions.yaml", {"questions": questions})
    commit_all(home, "seed overseer conversation")


def _ask(qid: str, case_ids: list[str], n: int = 1) -> dict:
    return {
        "id": qid, "kind": "ask", "cases": case_ids,
        "text": f"Should the diagram skill be scaffolded now (number {n})? Yes builds it; no parks it.",
        "why": f"decides whether lesson {n} is routed to a new skill",
    }


def test_open_shows_every_indexed_question_and_presents_each(tmp_path):
    """2026-09-24: no count limit. Four readings and two asks: every one is
    displayed and every one records a presentation (the old `[:3]` slice
    showed three and hid the rest behind "N remain")."""
    home = make_home(tmp_path)
    readings = [_reading(home, n) for n in range(1, 5)]
    propositions = [f"{entry}@r1" for entry in readings]
    case_ids = [
        _case(home, tmp_path, f"{n:08x}", {"user_model": [prop]})
        for n, prop in enumerate(propositions, start=1)
    ]
    ask_cases = [_case(home, tmp_path, f"{n:08x}", {}) for n in (5, 6)]
    asks = [_ask("q-diagram-skill", [ask_cases[0]], 1), _ask("q-oo7-binding", [ask_cases[1]], 2)]
    _report_and_index(
        home,
        [{"id": prop, "kind": "reading", "cases": [case_id]} for prop, case_id in zip(propositions, case_ids)]
        + asks,
        [
            f"- {propositions[0]}: Does this apply everywhere?",
            "- q-diagram-skill: scaffold the diagram skill",
        ],
    )
    out = io.StringIO()

    shown = conversation.open_questions(home, out=out)

    text = out.getvalue()
    # Positive control first: the report's own question block rendered.
    assert text.startswith("## Questions for you\n")
    assert f"- {propositions[0]}: Does this apply everywhere?" in text
    assert shown == 6
    for prop in propositions:
        assert prop in text
    assert "remain" not in text
    # An ask displays from the index -- its text, then its why -- in place
    # of the report's short line, and once only.
    assert f"- q-diagram-skill: {asks[0]['text']}\n  why: {asks[0]['why']}" in text
    assert f"- q-oo7-binding: {asks[1]['text']}\n  why: {asks[1]['why']}" in text
    assert "scaffold the diagram skill" not in text
    assert text.count("q-diagram-skill") == 1
    for case_id in case_ids:
        view = cases.show(home, case_id, evidence_only=False)
        assert len(view.frontmatter["presented"]) == 1, case_id
        presentation = view.frontmatter["presented"][0]
        assert presentation["covering"] == "decision"
        assert presentation["via"] == "overseer-conversation"
        assert presentation["outcome"] == "noted"
        assert "overseer presented:" in view.sections["Later observations"]
    for ask, case_id in zip(asks, ask_cases):
        view = cases.show(home, case_id, evidence_only=False)
        assert len(view.frontmatter["presented"]) == 1, case_id
        presentation = view.frontmatter["presented"][0]
        assert presentation["entries"] == []
        assert presentation["covering"] == "dependencies"
        assert presentation["outcome"] == "noted"
        assert f"overseer presented: - {ask['id']}: {ask['text']} (why: {ask['why']})" in (
            view.sections["Later observations"]
        )


def test_a_legacy_index_row_without_a_kind_reads_as_a_reading(tmp_path):
    home = make_home(tmp_path)
    proposition = f"{_reading(home, 1)}@r1"
    case_id = _case(home, tmp_path, "1", {"user_model": [proposition]})
    _report_and_index(home, [{"id": proposition, "cases": [case_id]}], [f"- {proposition}: Apply?"])
    assert conversation.open_questions(home, out=io.StringIO()) == 1
    assert cases.show(home, case_id, evidence_only=False).frontmatter["presented"][0]["entries"] == [
        proposition.split("@")[0]
    ]


def test_respond_to_an_ask_writes_a_question_statement_and_observes_its_cases(tmp_path):
    home = make_home(tmp_path)
    cited = _case(home, tmp_path, "1", {})
    other = _case(home, tmp_path, "2", {})
    ask = _ask("q-diagram-skill", [cited])
    _report_and_index(home, [ask], ["- q-diagram-skill: scaffold it?"])
    conversation.open_questions(home, out=io.StringIO())

    result = conversation.respond(
        home, proposition="q-diagram-skill", scope="user",
        text="Yes, build it this week.",
    )

    stored = next(row for row in statements.list_statements(home) if row["id"] == result.statement_id)
    assert stored["verbatim"] == "Yes, build it this week."
    assert stored["answers"] == {
        "kind": "question",
        "ref": "q-diagram-skill",
        "text": f"- q-diagram-skill: {ask['text']} (why: {ask['why']})",
    }
    assert stored["scope"] == {"level": "user", "host": None}
    assert stored["source"]["message_ref"].startswith("conversation:obs-")
    assert result.observed_cases == (cited,)
    observations = cases.show(home, cited, evidence_only=False).sections["Later observations"]
    assert f"overseer statement: user answered q-diagram-skill (ref: {result.statement_id})" in observations
    assert " statement:" not in cases.show(home, other, evidence_only=False).sections["Later observations"]


def test_decline_an_ask_stores_no_statement(tmp_path):
    home = make_home(tmp_path)
    cited = _case(home, tmp_path, "1", {})
    _report_and_index(home, [_ask("q-diagram-skill", [cited])], [])
    conversation.open_questions(home, out=io.StringIO())
    conversation.decline(home, proposition="q-diagram-skill")
    assert statements.list_statements(home) == []
    assert cases.show(home, cited, evidence_only=False).frontmatter["presented"][-1]["outcome"] == "declined"


def test_open_records_nothing_when_the_print_does_not_complete(tmp_path):
    home = make_home(tmp_path)
    entry = _reading(home, 1)
    proposition = f"{entry}@r1"
    case_id = _case(home, tmp_path, "1", {"user_model": [proposition]})
    _report_and_index(home, [{"id": proposition, "cases": [case_id]}], [f"- {proposition}: Apply globally?"])

    class ClosedPipe(io.StringIO):
        def flush(self) -> None:
            raise BrokenPipeError("reader closed")

    with pytest.raises(BrokenPipeError):
        conversation.open_questions(home, out=ClosedPipe())

    assert cases.show(home, case_id, evidence_only=False).frontmatter["presented"] == []


def test_respond_preserves_words_scope_question_version_and_only_observes_dependencies(tmp_path):
    home = make_home(tmp_path)
    entry = _reading(home, 1)
    proposition = f"{entry}@r1"
    direct = _case(home, tmp_path, "1", {"user_model": [proposition]})
    by_statement = _case(home, tmp_path, "2", {"statements": ["stmt-00000001"]})
    unrelated = _case(home, tmp_path, "3", {"user_model": ["um-dead@r1"]})
    displayed = f"- {proposition}: Does this apply to every repository?"
    _report_and_index(home, [{"id": proposition, "cases": [direct]}], [displayed])
    conversation.open_questions(home, out=io.StringIO())
    before = {
        cid: cases.show(home, cid, evidence_only=False)
        for cid in (direct, by_statement, unrelated)
    }

    result = conversation.respond(
        home,
        proposition=proposition,
        scope="project:/work/repo",
        text="Only this repository, while its deployment stays manual.",
        as_asked="Does this apply to this repository while deployment stays manual?",
    )

    stored = next(row for row in statements.list_statements(home) if row["id"] == result.statement_id)
    assert stored["verbatim"] == "Only this repository, while its deployment stays manual."
    assert stored["scope"] == {"level": "project", "host": "/work/repo"}
    assert stored["answers"] == {
        "kind": "proposition",
        "ref": proposition,
        "text": "Does this apply to this repository while deployment stays manual?",
    }
    assert stored["recorded_by"] == "human"
    assert stored["source"]["message_ref"].startswith("conversation:obs-")

    after = {cid: cases.show(home, cid, evidence_only=False) for cid in before}
    assert set(result.observed_cases) == {direct, by_statement}
    assert f"(ref: {proposition})" in after[direct].sections["Later observations"]
    assert "(ref: stmt-00000001)" in after[by_statement].sections["Later observations"]
    assert " statement:" not in after[unrelated].sections["Later observations"]
    for cid in before:
        assert after[cid].frontmatter["decided_sha256"] == before[cid].frontmatter["decided_sha256"]
        for section in ("Identity and scope", "Evidence", "Decision", "Dependencies"):
            assert after[cid].sections[section] == before[cid].sections[section]
    assert after[direct].frontmatter["presented"][-1]["outcome"] == "corrected"


@pytest.mark.parametrize("scope", ["", "project:"])
def test_respond_refuses_empty_scope_without_a_statement(tmp_path, scope):
    home = make_home(tmp_path)
    with pytest.raises(conversation.ConversationUsageError, match="scope"):
        conversation.respond(home, proposition="um-dead@r1", scope=scope, text="yes")
    assert statements.list_statements(home) == []


def test_decline_updates_the_presentation_and_stores_no_statement(tmp_path):
    home = make_home(tmp_path)
    entry = _reading(home, 1)
    proposition = f"{entry}@r1"
    case_id = _case(home, tmp_path, "1", {"user_model": [proposition]})
    _report_and_index(home, [{"id": proposition, "cases": [case_id]}], [f"- {proposition}: Apply globally?"])
    conversation.open_questions(home, out=io.StringIO())

    result = conversation.decline(home, proposition=proposition)

    assert result.statement_id is None
    assert statements.list_statements(home) == []
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["presented"][-1]["outcome"] == "declined"


def test_cli_exposes_open_respond_and_decline(tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    entry = _reading(home, 1)
    proposition = f"{entry}@r1"
    case_id = _case(home, tmp_path, "1", {"user_model": [proposition]})
    _report_and_index(
        home,
        [{"id": proposition, "cases": [case_id]}],
        [f"- {proposition}: Is this how you want it handled?"],
    )
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="verb", required=True)
    overseer_cli.add_parser(sub)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))

    opened = parser.parse_args(["overseer", "open"])
    assert overseer_cli.dispatch(opened) == 0
    assert proposition in capsys.readouterr().out

    declined = parser.parse_args(
        ["overseer", "respond", "--proposition", proposition, "--decline"]
    )
    assert overseer_cli.dispatch(declined) == 0
    assert "declined" in capsys.readouterr().out

    answered = parser.parse_args(
        [
            "overseer",
            "respond",
            "--proposition",
            proposition,
            "--scope",
            "user",
            "--text",
            "Yes, for my user scope.",
            "--as-asked",
            "Only for your user scope?",
        ]
    )
    assert overseer_cli.dispatch(answered) == 0
    assert "recorded" in capsys.readouterr().out
