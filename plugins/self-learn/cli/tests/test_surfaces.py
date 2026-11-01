"""Attention round, lane `surfaces` (design r2 §3.9, §5.7): the one popup
kind, agents recording their own acts as `agent` (C7), the product's
documents after silent capture and the congruence review, the hook route
text (M4) and the guard prefix (n5).

Marker rule (§3.4.1): the package-root conftest clears
``settings.AGENT_CALLER_MARKERS`` for every test, so a test here models a
person's terminal unless it sets one marker itself (``_agent``).
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from ruamel.yaml import YAML

from self_learn import cli, hook_compiler, serve, settings, skill_cli, statements, steward, teach, user_model
from self_learn.overseer import conversation, notify
from self_learn.overseer import run as overseer_run
from support import commit_all, git, make_env, make_home
from test_statement_roles import transcript

PLUGIN = Path(__file__).resolve().parents[2]
LOGIN_CAUSE = "Failed to authenticate: OAuth session expired and could not be refreshed"
OTHER_CAUSE = "Please update Claude Code"


def _agent(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")


def _last_body(home: Path) -> str:
    return git(home, "log", "-1", "--format=%B").stdout.strip()


def _by_block(home: Path) -> list[str]:
    return _last_body(home).rpartition("\n\n")[2].splitlines()


# ============================================== the hold callers pass a kind


@pytest.fixture()
def sent(monkeypatch):
    rows: list[dict] = []

    def fake(home, cue, summary, ids, *, kind="silent"):
        rows.append({"cue": cue, "summary": summary, "ids": ids, "kind": kind})

    monkeypatch.setattr(notify, "send", fake)
    return rows


def test_the_steward_hold_pops_up_only_for_a_login(tmp_path, sent):
    """Mutation: drop `kind=` at the steward's call site -> the login hold
    is sent silent."""
    home = make_home(tmp_path)
    steward._notify_environment_hold(home, "run-1", LOGIN_CAUSE)  # noqa: SLF001
    steward._notify_environment_hold(home, "run-2", OTHER_CAUSE)  # noqa: SLF001
    assert [row["kind"] for row in sent] == ["hold.credentials", "silent"]


def test_the_serve_hold_pops_up_only_for_a_login(tmp_path, sent):
    home = make_home(tmp_path)
    serve._notify_due_hold(home, "steward", LOGIN_CAUSE)  # noqa: SLF001
    serve._notify_due_hold(home, "steward", OTHER_CAUSE)  # noqa: SLF001
    assert [row["kind"] for row in sent] == ["hold.credentials", "silent"]
    # Gate r1 NIT 2: the one popup says what to type. Mutation: send the
    # bare text without `notify.with_hold_fix`.
    assert LOGIN_CAUSE in sent[0]["summary"]
    assert "To fix it: run `claude`, then `/login`." in sent[0]["summary"]


def test_the_overseer_hold_pops_up_only_for_a_login(tmp_path, sent, monkeypatch):
    home = make_home(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    login = SimpleNamespace(failure="auth", detail=LOGIN_CAUSE)
    other = SimpleNamespace(failure="version", detail=OTHER_CAUSE)
    overseer_run._environment_hold(home, "run-1", "phase-a", login)  # noqa: SLF001
    overseer_run._environment_hold(home, "run-2", "phase-a", other)  # noqa: SLF001
    assert [row["kind"] for row in sent] == ["hold.credentials", "silent"]
    # Gate r1 NIT 2. Mutation: send the bare text without the step.
    assert "cannot run here" in sent[0]["summary"]
    assert "To fix it: run `claude`, then `/login`." in sent[0]["summary"]


# ====================================================== C7: agent as recorder


def _case_stage(tmp_path: Path) -> Path:
    stage = tmp_path / "case.yaml"
    with stage.open("w", encoding="utf-8") as fh:
        YAML().dump({
            "kind": "resolution", "trigger": "human", "outcome": "no-action",
            "records": ["lrn-00000001"], "scope": "user", "question": "q?",
            "evidence": [{"ref": "transcript:s#L1", "quote": "x"}],
            "decision": {"verb": "no-action", "because": "nothing to do", "confidence": "settled"},
            "dependencies": {"statements": [], "user_model": [], "conditions": [], "capabilities": []},
        }, fh)
    return stage


def test_an_agent_records_its_own_acts_as_agent(tmp_path, monkeypatch, capsys):
    """Test 4, first part: from an agent's shell (one marker set) each verb
    succeeds, stores `agent` and commits `By: agent`."""
    env = make_env(tmp_path)
    home = env.ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    transcript(home, tmp_path)
    _agent(monkeypatch)

    # case record --actor agent
    assert cli.main(["case", "record", str(_case_stage(tmp_path)), "--actor", "agent"]) == 0, capsys.readouterr().err
    case_id = re.search(r"case-[0-9a-f]{8}", capsys.readouterr().out).group(0)
    text = next(home.glob(f"cases/*/{case_id}.md")).read_text(encoding="utf-8")
    assert re.search(r"^actor: agent$", text, re.M)
    assert _by_block(home)[0] == "By: agent"

    # case observe --by agent
    assert cli.main(["case", "observe", case_id, "--by", "agent", "--kind", "examined",
                     "--text", "looked again"]) == 0, capsys.readouterr().err
    text = next(home.glob(f"cases/*/{case_id}.md")).read_text(encoding="utf-8")
    assert re.search(r"obs-[0-9a-f]{8} \S+ agent examined: looked again", text)
    assert _by_block(home)[0] == "By: agent"

    # statement add --recorded-by agent, with a transcript ref
    capsys.readouterr()
    assert cli.main(["statement", "add", "--verbatim", "Keep it small.",
                     "--ref", "transcript:synthetic-stmt#L1", "--recorded-by", "agent",
                     "--json"]) == 0, capsys.readouterr().err
    stmt_id = json.loads(capsys.readouterr().out)["statement"]
    row = next(r for r in statements.list_statements(home) if r["id"] == stmt_id)
    assert row["recorded_by"] == "agent"
    assert _by_block(home)[0] == "By: agent"

    # user-model add --by agent
    assert cli.main(["user-model", "add", "--container", "A", "--title", "prefers small changes",
                     "--because", "said so", "--source", "own-words", "--by", "agent",
                     "--statements", stmt_id, "--ref", stmt_id]) == 0, capsys.readouterr().err
    doc = user_model.show(home)
    entries = [e for es in doc["containers"].values() for e in es]
    assert any(e["title"] == "prefers small changes" for e in entries)
    assert re.search(r"^updated_by: agent$", user_model._doc_path(home).read_text(encoding="utf-8"), re.M)  # noqa: SLF001
    assert _by_block(home)[0] == "By: agent"


def test_an_agent_cannot_record_its_statement_as_the_persons(tmp_path, monkeypatch, capsys):
    """Test 4: `statement add --recorded-by human` from an agent's shell
    exits 64 and writes nothing. Control first: the same command from a
    person's terminal succeeds. Mutation: drop the refusal -> exit 0."""
    env = make_env(tmp_path)
    home = env.ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    transcript(home, tmp_path)
    argv = ["statement", "add", "--verbatim", "Keep it small.",
            "--ref", "transcript:synthetic-stmt#L1", "--recorded-by", "human"]
    assert not settings.agent_caller()
    assert cli.main(argv) == 0, capsys.readouterr().err  # control: a person's terminal
    capsys.readouterr()
    before = len(statements.list_statements(home))
    head = git(home, "rev-parse", "HEAD").stdout
    _agent(monkeypatch)
    assert cli.main([*argv[:-1], "human"]) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "an agent's shell records as agent" in err and "CLAUDECODE" in err
    assert len(statements.list_statements(home)) == before
    assert git(home, "rev-parse", "HEAD").stdout == head
    # the library does not refuse: teach and respond call it
    assert statements.add(home, verbatim="Keep it small.",
                          source={"message_ref": "transcript:synthetic-stmt#L1"},
                          recorded_by="human")


def _teach_statement(home: Path) -> str:
    code = cli.main(["teach", "--user", "--type", "knowledge", "--fact", "Smaller changes land faster.",
                     "--session", "synthetic-stmt", "--statement", "Keep it small."])
    assert code == 0
    (row,) = statements.list_statements(home)
    return row["recorded_by"]


def test_teach_records_the_statement_as_agent_from_an_agent_shell(tmp_path, monkeypatch, capsys):
    """Test 4: `teach --statement` stores `recorded_by: agent` from an
    agent's shell and `human` from a person's. Mutation: hard-code `human`
    in `teach.py` -> the agent leg reads human."""
    for who, marker in (("person", False), ("agent", True)):
        env = make_env(tmp_path / who)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        transcript(env.ledger, tmp_path / who)
        if marker:
            _agent(monkeypatch)
        assert _teach_statement(env.ledger) == ("agent" if marker else "human"), capsys.readouterr().err
    # the retry hint names the recorder that will not be refused
    assert "--recorded-by agent" in teach._statement_retry_hint("x", "transcript:s#L1")  # noqa: SLF001


def _ask_home(tmp_path: Path) -> Path:
    from test_overseer_conversation import _ask, _case, _report_and_index

    home = make_home(tmp_path)
    cited = _case(home, tmp_path, "1", {})
    _report_and_index(home, [_ask("q-diagram-skill", [cited])], ["- q-diagram-skill: scaffold it?"])
    conversation.open_questions(home, out=io.StringIO())
    return home


def test_respond_records_agent_from_an_agent_shell(tmp_path, monkeypatch):
    """Test 4: `overseer respond` stores `recorded_by: agent` from an
    agent's shell and `human` from a person's. Mutation: hard-code `human`
    in `respond` -> the agent leg reads human."""
    for who, marker in (("person", False), ("agent", True)):
        home = _ask_home(tmp_path / who)
        if marker:
            _agent(monkeypatch)
        result = conversation.respond(home, proposition="q-diagram-skill", scope="user",
                                      text="Yes, build it this week.")
        row = next(r for r in statements.list_statements(home) if r["id"] == result.statement_id)
        assert row["recorded_by"] == ("agent" if marker else "human")


def test_skill_by_defaults_to_who_ran_it(monkeypatch):
    """Test 4: `skill write|retire --by` defaults to `agent` in an agent's
    shell, `human` otherwise. Mutation: default `--by` to `human` in an
    agent's shell -> red. (In an agent's shell `dispatch` also forces
    `agent` once the grant authorizes the run, so the CLI leg below cannot
    tell the default from the override; this unit leg can.)"""
    assert skill_cli.default_by() == "human"
    _agent(monkeypatch)
    assert skill_cli.default_by() == "agent"
    parser = cli._build_parser()  # noqa: SLF001
    for argv in (["skill", "retire", "some-skill"], ["skill", "write", "some-skill", "--from", "d"]):
        assert parser.parse_args(argv).by is None  # resolved at dispatch, never a parse-time "human"


def test_an_agents_veto_with_no_by_is_the_agents(tmp_path, monkeypatch, capsys):
    """Test 4: `skill veto --note x` with no `--by`, from an agent's shell
    under the grant, is recorded `agent`."""
    from test_grants import _stmt
    from self_learn import grants, skill_registry

    env = make_env(tmp_path)
    home = env.ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    stmt = _stmt(home, tmp_path)
    assert grants.add(home, statement=stmt)[1] is True
    _agent(monkeypatch)
    assert cli.main(["skill", "veto", "bad-name", "--note", "x", "--no-push"]) == 0, capsys.readouterr().err
    entry = skill_registry.load(home).veto_of("bad-name")
    assert entry is not None and entry["by"] == "agent"
    assert _by_block(home)[0] == "By: agent"


# ===================================================== documents (test 5, 7)


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


DOCS = {
    "skills/self-learn/SKILL.md": "compose and capture with `self-learn teach`; report the id in one line only if the user is mid-conversation about it",
    "commands/teach.md": "compose and capture with `self-learn teach`; report the id in one line only if the user is mid-conversation about it",
    "commands/review.md": "**Decide what you can yourself.**",
    "skills/self-learn/references/routing-doctrine.md": "let the decider (the steward, the overseer, or a person who steps in) judge",
    "skills/self-learn/references/pane-surface-model.md": "The steward decides each one nightly",
    "README.md": "compose and capture with `self-learn teach`; report the id in one line only if I am mid-conversation about it",
    "hooks/self-learn-pending.sh": "yours to carry out in this session (no sudo needed)",
}

GONE = (
    "human decision gate", "Echo and confirm", "ask for confirmation",
    "still waiting for you", "registration stays manual", "The human runs these",
    "the human then keeps it", "When to offer capture", "offer once", "want me to capture",
    "offer-declined", "Capture nothing they haven't seen", "One AskUserQuestion per record",
)


@pytest.mark.parametrize("rel", sorted(DOCS))
def test_a_document_says_the_new_thing_and_none_of_the_old(rel):
    """Test 5: each document's anchor sentence first (the control: the file
    was read and holds the new text), then the absence of every phrase the
    congruence review and answer 9 retired. Mutation: restore one phrase."""
    text = _flat(PLUGIN / rel)
    assert DOCS[rel] in text, rel
    for phrase in GONE:
        assert phrase not in text, (rel, phrase)


def test_no_product_text_tells_an_agent_it_may_run_sudo():
    texts = [_flat(PLUGIN / rel) for rel in DOCS] + [_flat(PLUGIN / "commands" / "overseer.md")]
    assert all("sudo unless" not in t for t in texts)


def test_overseer_command_points_to_the_inbox():
    """Test 7: `commands/overseer.md` points to the inbox and to `self-learn
    attention`, and no longer has the agent hand the person a `respond` to
    run (m14). Mutation: restore "have the person run the same `respond`"."""
    text = _flat(PLUGIN / "commands" / "overseer.md")
    assert "self-learn-ui-open --page /inbox" in text
    assert "`self-learn attention`" in text
    assert "have the person run" not in text
    assert "the person run the same `respond`" not in text
    assert "--recorded-by human" not in text
    # Gate r1 MAJOR 1: a needs-you ask waits for the user, and one with a
    # plan is decided only by an option. Mutation: drop the needs-you passage.
    # Step 2 names each line as `overseer open` prints it (whitespace
    # flattened), read from the code's own labels so the two cannot drift.
    assert f"` {conversation.NEEDS_YOU_LABEL}: <what holds" in text
    assert f"` {conversation.DEFAULT_LABEL}: <default>`" in text
    assert "self-learn attention answer <att-id> --option" in text
    assert "decided **only by choosing one of its options**" in text
    assert "Nothing in either place is waiting on them" not in text
    # Surfaces gate r2 NIT 1 (added at integration): the session route
    # names --confirm for a confirm or register option, which `attention
    # answer` refuses without it. Mutation: drop the sentence -> red.
    assert "every `register` option, also needs `--confirm`" in text
    # Surfaces gate r2 NIT 2: SKILL.md and the routing doctrine carry the
    # same correction, so neither can drift back to "does not wait".
    # Mutations: restore either round-1 wording -> red.
    skill = _flat(PLUGIN / "skills" / "self-learn" / "SKILL.md")
    assert "ask waits for the user, and one with a plan is decided only by choosing" in skill
    doctrine = _flat(PLUGIN / "skills" / "self-learn" / "references" / "routing-doctrine.md")
    assert "a needs-you question (a change to their system" in doctrine
    assert "does wait, states what holds meanwhile" in doctrine
    assert "is decided only by choosing one of its options" in doctrine


def test_review_never_hands_by_to_a_verb_that_refuses_it():
    """Gate r1 MINOR 3: `reject`, `retire`, `supersede`, `dismiss-suspect`,
    `confirm-recurrence` and the rest take no `--by` (rc 64), so review.md
    tells the agent to decide with `--note` and names the verbs that take
    `--by agent`. Mutation: restore "apply the verb with `--by agent --note"."""
    text = _flat(PLUGIN / "commands" / "review.md")
    # positive control first: the corrected sentence is there
    assert "apply the verb with `--note \"<why>\"` (recorded `By: agent`; on `route`," in text
    assert "the other verbs take no `--by`" in text
    assert "apply the verb with `--by agent --note" not in text
    assert "decide it with `--by agent` and" not in text


def test_documented_examples_show_agent_for_the_agents_own_acts():
    """C7: the examples an agent copies record its act as `agent`."""
    review = _flat(PLUGIN / "commands" / "review.md")
    assert "case observe <id> --by agent" in review
    assert "case record <stage-file> --actor agent" in review
    assert "--by agent --statements" in review
    assert "--recorded-by agent" in review


# ======================================================= M4, n5 (tests 6, 8)


def test_the_hook_route_text_names_hook_activate():
    """Test 6. Mutation: restore the two manual steps."""
    from self_learn import verbs

    snippet = ('"PreToolUse": [{"matcher": "Edit", "hooks": '
               '[{"type": "command", "command": "/h/hooks/g.sh"}]}]')
    text = "\n".join(verbs._hook_manual_steps(snippet, "g.sh", record_id="lrn-0000abcd"))  # noqa: SLF001
    assert "self-learn hook activate lrn-0000abcd" in text
    assert "./install.sh" not in text and "two manual steps" not in text


def test_a_stored_prefix_is_not_doubled_in_the_guard():
    """Test 8 (n5): a `deny_message` that already begins `self-learn <id>: `
    yields the prefix once; a plain message yields it once too (control).
    Mutation: drop the strip -> the doubled prefix comes back."""
    rid = "lrn-9b4bb8f0"
    plain = hook_compiler.generate_script(rid, "about to run systemctl", ["Bash"], "systemctl",
                                          "plain words here")
    assert plain.count(f"self-learn {rid}: plain words here") == 1
    doubled = hook_compiler.generate_script(rid, "about to run systemctl", ["Bash"], "systemctl",
                                            f"self-learn {rid}: doubled words here")
    assert f"self-learn {rid}: self-learn {rid}:" not in doubled
    assert doubled.count(f"self-learn {rid}: doubled words here") == 1
    # the warning path shares the rule
    assert hook_compiler.warn_context(rid, f"self-learn {rid}: w") == f"self-learn {rid}: w"
    # another record's prefix is not this record's to strip
    other = hook_compiler.prefixed_message(rid, "self-learn lrn-00000000: x")
    assert other == f"self-learn {rid}: self-learn lrn-00000000: x"


# ============================================================ report line


def test_the_offer_ledger_says_capture_is_silent(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    assert cli.main(["report"]) == 0
    out = capsys.readouterr().out
    assert "silent capture since 2026-10-31; offers are no longer made" in out
    assert "declined (logged" not in out  # nothing logged, nothing to label
