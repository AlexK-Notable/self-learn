"""The inbox's answers (attention round 2026-10-31c, design r2 §3.4; §5.3
tests 1-17).

Every test is a person's shell unless it sets an agent marker itself
(design r2 §3.4.1, "Tests in agent shells"): the module fixture deletes
``settings.AGENT_CALLER_MARKERS``. PATH is hermetic: a shim directory holds
fake ``systemd-run``, ``systemctl`` and ``alacritty`` that only log their
argv, and a link to the real ``git``; nothing else is on it, so no real
terminal, unit or Claude Code session can ever be launched from here.

Each test names the mutation it was checked against.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import (
    attention,
    attention_answers as answers,
    attribution,
    attention_packet,
    cases,
    cli,
    grant_uses,
    grants,
    hosts,
    settings,
    statements,
    steward,
    steward_prompt,
    verbs,
    workspace,
)
from self_learn.overseer import conversation
from support import git, init_repo, make_env, make_home
from test_cures_b import _transcript, _typed
from test_grants import _stmt
from test_overseer_answered_questions import _deferred_case
from test_overseer_conversation import _report_and_index
from test_steward import _dump_yaml
from test_steward_refusals import _case as _steward_case
from test_steward_refusals import _seed

_BILLING = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX", "TERMINAL")

_SHIM = """#!/bin/sh
name=${0##*/}
printf '%s' "$name" >> "$SHIM_LOG"
for a in "$@"; do printf '\\037%s' "$a" >> "$SHIM_LOG"; done
printf '\\n' >> "$SHIM_LOG"
exit ${SHIM_RC:-0}
"""


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    for name in ("CLAUDE_CODE_SESSION_ID", *_BILLING):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


@pytest.fixture(autouse=True)
def shims(tmp_path, monkeypatch) -> Path:
    """A hermetic PATH: logging shims and the real git only."""
    real_git = shutil.which("git")
    assert real_git is not None
    folder = tmp_path / "shim-bin"
    folder.mkdir()
    (folder / "git").symlink_to(real_git)
    for name in ("systemd-run", "systemctl", "alacritty"):
        (folder / name).write_text(_SHIM, encoding="utf-8")
        (folder / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(folder))
    monkeypatch.setenv("SHIM_LOG", str(tmp_path / "shim.log"))
    return folder


def _calls(tmp_path: Path, name: str | None = None) -> list[list[str]]:
    log = tmp_path / "shim.log"
    if not log.exists():
        return []
    rows = [line.split("\x1f") for line in log.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if name is None or row[0] == name]


def _agent(monkeypatch, session: str | None = None) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    if session is not None:
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)


def _iso(delta: timedelta = timedelta()) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _observations(home: Path, case_id: str) -> str:
    return cases.show(home, case_id, evidence_only=False).sections.get("Later observations", "")


def _choices(home: Path) -> list[dict]:
    return conversation.choice_rows(home)


def _stmts(home: Path) -> list[dict]:
    return statements.list_statements(home)


def _item(home: Path, subject: str, kind: str | None = None) -> dict:
    found = [i for i in attention.collect(home, all_items=True)
             if i["subject"] == subject and (kind is None or i["kind"] == kind)]
    assert found, f"no item for {subject} ({kind})"
    return found[0]


def _index(home: Path, rows: list[dict]) -> None:
    _report_and_index(home, rows, [f"- {row['id']}: a question" for row in rows])


_YES_NO = [{"id": "opt-yes", "label": "Yes, restart it", "effect": "approve"},
           {"id": "opt-no", "label": "No, leave it", "effect": "decline"}]


def _plan(*, sudo_steps: int = 0, plain_steps: int = 1, cwd: str | None = None) -> dict:
    steps = [{"say": f"Run root step {n}", "command": f"sudo true {n}", "sudo": True}
             for n in range(sudo_steps)]
    steps += [{"say": f"Restart it {n}", "command": "systemctl --user restart d", "sudo": False}
              for n in range(plain_steps)]
    return {"summary": "Restart the daemon.", "cwd": cwd,
            "checks": [{"say": "It is installed", "command": "systemctl --user is-active d"}],
            "steps": steps, "files": []}


def _system_ask(qid: str, case_ids: list[str], **extra) -> dict:
    row = {
        "id": qid, "kind": "ask", "cases": case_ids,
        "text": "Restart the daemon so it picks up the new socket?",
        "why": "It changes how your desktop runs a service, outside self-learn.",
        "needs": "user", "because": "system-change",
        "default": conversation.SYSTEM_DEFAULT,
        "options": [*_YES_NO], "recommend": {"option": "opt-yes", "reasoning": "it is stale"},
        "plan": _plan(),
    }
    row.update(extra)
    return row


def _stead_ask(qid: str, case_ids: list[str]) -> dict:
    return {
        "id": qid, "kind": "ask", "cases": case_ids,
        "text": "Should the diagram skill be built?", "why": "decides where the lesson goes",
        "needs": "stead", "default": "I kept the lesson where it is.",
        "options": [{"id": "opt-build", "label": "Build it", "effect": "other"},
                    {"id": "opt-keep", "label": "Keep it where it is", "effect": "other"}],
        "recommend": {"option": "opt-keep", "reasoning": "one lesson is not a skill"},
    }


def _sudo_ask(qid: str, case_ids: list[str]) -> dict:
    return {
        "id": qid, "kind": "ask", "cases": case_ids,
        "text": "Will you install the package with pacman?", "why": "it needs root",
        "needs": "user", "because": "sudo", "default": "Nothing was installed.",
        "options": [{"id": "opt-will", "label": "I'll run it", "effect": "other"},
                    {"id": "opt-no", "label": "No", "effect": "decline"}],
        "recommend": {"option": "opt-will", "reasoning": "the lesson needs it"},
    }


# --------------------------------------------------------- 1. a click is a choice


def test_a_click_on_a_stead_ask_is_a_choice_and_brings_its_case_back(tmp_path):
    """Mutations: revert `_ASK_OVERTURN_OBSERVATION_RE`'s ref group to
    `stmt-` only -> red (no reconsider); revert its observer group to
    `overseer` only -> red."""
    home = make_home(tmp_path)
    rid, case_id = _deferred_case(home, tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [case_id])])
    assert steward._reconsider_proposals(home)[0] == []  # control: nothing yet
    item = _item(home, "q-diagram-skill", "decided.ask-default")

    result = answers.answer(home, item["id"], option="opt-build")

    assert result.statement is None and _stmts(home) == []  # a click is never words
    (choice,) = _choices(home)
    assert choice["id"] == result.choice and choice["how"] == "clicked"
    assert (choice["option"], choice["label"], choice["recorded_by"]) == ("opt-build", "Build it", "human")
    assert choice["source"]["message_ref"] == f"workspace:{item['id']}#T{result.transcript_row}"
    line = (f"human statement: user answered q-diagram-skill after its default was applied "
            f"(ref: {result.choice})")
    assert line in _observations(home, case_id)
    ((entry, card),) = steward._reconsider_proposals(home)[0]
    assert (entry.record.id, entry.predecessor) == (rid, case_id)
    unresolved = card["card"]["unresolved"]
    assert "They chose the offered option «Build it» (not their words)" in unresolved
    assert "Their words" not in unresolved


def test_a_click_on_a_needs_you_ask_without_a_plan_brings_a_deferral_back(tmp_path):
    """Mutation: revert `_ASK_ANSWER_OBSERVATION_RE`'s ref group to `stmt-`
    only, or its observer group to `overseer` only -> red."""
    home = make_home(tmp_path)
    rid, case_id = _deferred_case(home, tmp_path)
    _index(home, [_sudo_ask("q-install-pkg", [case_id])])
    item = _item(home, "q-install-pkg", "ask.sudo")

    result = answers.answer(home, item["id"], option="opt-will")

    assert result.state == "answered" and result.statement is None
    assert f"human statement: user answered q-install-pkg (ref: {result.choice})" in _observations(
        home, case_id)
    ((entry, _card),) = steward._reconsider_proposals(home)[0]
    assert entry.record.id == rid
    assert not [i for i in attention.read(home)["items"] if i["subject"] == "q-install-pkg"]


# --------------------------------------------------------- 2. typed words


def test_typed_words_from_the_page_are_the_persons_statement(tmp_path):
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")

    result = answers.answer(home, item["id"], text="Build it, but only after the move.")

    row = workspace.resolve(home, f"workspace:{item['id']}#T{result.transcript_row}")
    assert row is not None and (row["role"], row["origin"], row["kind"]) == ("user", "typed", "reply")
    (stmt,) = _stmts(home)
    assert stmt["id"] == result.statement and stmt["recorded_by"] == "human"
    assert stmt["source"]["message_ref"] == f"workspace:{item['id']}#T{result.transcript_row}"
    assert stmt["answers"]["ref"] == "q-diagram-skill" and stmt["answers"]["kind"] == "question"
    assert result.choice is None and result.recorded_as == "as your words"


def test_an_agent_shell_relays_words_only_with_the_transcript_line(tmp_path, monkeypatch):
    """Mutation: allow typed text from an agent's shell (drop the --ref /
    --text-file requirement) -> red."""
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    _agent(monkeypatch)
    with pytest.raises(answers.AnswerError) as no_ref:
        answers.answer(home, item["id"], text="build it", note="relaying")
    assert no_ref.value.exit_code == 64
    with pytest.raises(answers.AnswerError) as no_text:
        answers.answer(home, item["id"], option="opt-build", ref="transcript:s1#L4", note="relaying")
    assert no_text.value.exit_code == 64
    assert _stmts(home) == [] and _choices(home) == []  # nothing recorded

    words = answers.answer(home, item["id"], text="build it", ref="transcript:s1#L4",
                           note="the person said so in my session")
    (stmt,) = _stmts(home)
    assert stmt["id"] == words.statement and stmt["recorded_by"] == "agent"
    assert stmt["source"]["message_ref"] == "transcript:s1#L4" and words.choice is None
    row = workspace.resolve(home, f"workspace:{item['id']}#T{words.transcript_row}")
    assert row is not None and row["origin"] == "relayed" and row["ref"] == "transcript:s1#L4"

    with attribution.process("agent"):  # what `cli.main` sets in an agent's shell
        both = answers.answer(home, item["id"], option="opt-build", text="yes, build it",
                              ref="transcript:s1#L6", note="relaying their click")
    (choice,) = _choices(home)
    assert choice["how"] == "relayed" and choice["recorded_by"] == "agent"
    assert choice["statement"] == both.statement
    body = git(home, "log", "-1", "--format=%B").stdout
    assert body.strip().splitlines()[-1] == "By: agent"


# --------------------------------------------------------- 3. drafts and pastes


def _seal_agent(home: Path, item: dict, text: str, *, draft: str | None = None,
                option: str | None = None) -> None:
    row: dict = {"role": "agent", "origin": "agent", "kind": "draft" if draft else "answer",
                 "text": text}
    if draft:
        row.update(draft_id=draft, option=option)
    workspace.append(home, item["id"], [row], header={"item_kind": item["kind"],
                                                      "subject": item["subject"],
                                                      "title": item["title"]})


DRAFT = "Keep it where it is; one lesson is not enough to build a whole skill around."


def test_an_agent_draft_is_recorded_as_the_agents_never_as_words(tmp_path, monkeypatch):
    """Mutation: treat an edited draft as typed (origin `typed`) -> red."""
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    _seal_agent(home, item, DRAFT, draft="drf-1a2b3c4d")

    accepted = answers.answer(home, item["id"], draft_id="drf-1a2b3c4d")
    edited = answers.answer(home, item["id"], draft_id="drf-1a2b3c4d",
                            text="Keep it where it is for now.")

    assert accepted.statement is None and edited.statement is None and _stmts(home) == []
    first, second = _choices(home)
    assert (first["how"], first["text"], first["offered_by"]) == ("draft-accepted", DRAFT, "agent")
    assert (second["how"], second["text"], second["draft_text"]) == (
        "draft-edited", "Keep it where it is for now.", DRAFT)
    assert edited.recorded_as == "as the agent's draft, edited and sent by you"

    with pytest.raises(answers.AnswerError) as unknown:
        answers.answer(home, item["id"], draft_id="drf-00000000")
    assert unknown.value.exit_code == 64
    _agent(monkeypatch)
    with pytest.raises(answers.AnswerError) as from_agent:
        answers.answer(home, item["id"], draft_id="drf-1a2b3c4d", text="x", ref="transcript:s#L1",
                       note="n")
    assert from_agent.value.exit_code == 64


def test_a_reply_that_pastes_40_characters_of_the_agent_is_its_draft(tmp_path):
    """Mutation: drop the paste match (always `typed`) -> red."""
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    _seal_agent(home, item, DRAFT)
    forty = DRAFT[:40]
    assert len(forty) == 40

    pasted = answers.answer(home, item["id"], text=f"ok.  {forty}  thanks")
    typed = answers.answer(home, item["id"], text=f"ok {DRAFT[:39]}")

    assert pasted.statement is None and pasted.recorded_as.startswith("as the agent's draft")
    (choice,) = _choices(home)
    assert choice["how"] == "draft-edited" and choice["draft_id"] is None
    assert choice["draft_text"] == DRAFT
    assert typed.statement is not None and typed.recorded_as == "as your words"


# --------------------------------------------------------- 4. words never approve


def test_a_typed_no_on_an_item_with_a_plan_decides_nothing(tmp_path):
    """Mutation: approve on any typed reply (critique 1) -> red."""
    home = make_home(tmp_path)
    _index(home, [_system_ask("q-restart-daemon", [])])
    item = _item(home, "q-restart-daemon", "ask.system-change")

    result = answers.answer(home, item["id"], text="no")

    assert result.state == "open" and result.choice is None and result.statement is not None
    assert _choices(home) == []
    document = attention.read(home)
    still = [i for i in document["items"] if i["subject"] == "q-restart-daemon"]
    assert [i["kind"] for i in still] == ["ask.system-change"] and still[0]["state"] == "open"
    assert document["counts"]["needs_you"] == 1
    assert _calls(tmp_path, "systemd-run") == []


# --------------------------------------------------------- 5. approve and launch


def test_an_approve_click_launches_the_brief_in_a_terminal(tmp_path, monkeypatch):
    """Mutation: launch before the billing check -> red (the API-key run
    spawns)."""
    home = make_home(tmp_path)
    settings.config_set(home, "attention.terminal", "alacritty -e")
    _index(home, [_system_ask("q-restart-daemon", [])])
    item = _item(home, "q-restart-daemon")

    result = answers.answer(home, item["id"], option="opt-yes")

    approved_id = attention.item_id("approved.pending", "q-restart-daemon")
    assert result.state == "running" and result.run == {"exit": 0, "message": result.run["message"]}
    brief = attention.cache_dir(home) / "attention" / "runs" / approved_id / "brief.md"
    title = item["title"]
    assert brief.read_text(encoding="utf-8") == answers.RUN_BRIEF.format(id=approved_id, title=title)
    first = answers.RUN_BRIEF.format(id=approved_id, title=title).splitlines()[0]
    ((name, *argv),) = _calls(tmp_path, "systemd-run")
    assert argv == [
        "--user", "--collect", "--quiet", f"--unit=self-learn-run-{approved_id[4:]}",
        f"--working-directory={os.path.expanduser('~')}", "--", "alacritty", "-e", "claude",
        f"{first} Read {brief} and follow it.",
    ]
    running = _item(home, "q-restart-daemon", "approved.pending")
    assert running["state"] == "running" and running["run"]["unit"].startswith("self-learn-run-")


def test_a_launch_that_would_bill_money_or_finds_no_terminal_is_refused(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _index(home, [_system_ask("q-restart-daemon", []), _system_ask("q-other", [])])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    money = answers.answer(home, _item(home, "q-restart-daemon")["id"], option="opt-yes")
    assert money.state == "approved" and money.run is not None and money.run["exit"] == 4
    assert _calls(tmp_path, "systemd-run") == []  # nothing spawned
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    (tmp_path / "shim-bin" / "alacritty").unlink()  # no terminal anywhere on PATH
    none = answers.answer(home, _item(home, "q-other")["id"], option="opt-yes")
    assert none.run is not None and none.run["exit"] == 5
    assert "brief is at" in none.run["message"] and "claude " in none.run["message"]
    assert _calls(tmp_path, "systemd-run") == []
    # The approvals stand: "Run it now" can launch later.
    assert len(_choices(home)) == 2


def test_yes_with_conditions_needs_a_note_and_carries_it_into_the_plan(tmp_path):
    home = make_home(tmp_path)
    options = [*_YES_NO, {"id": "opt-yes-conditions", "label": "Yes, with conditions",
                          "effect": "approve", "note": "required"}]
    _index(home, [_system_ask("q-restart-daemon", [], options=options)])
    item = _item(home, "q-restart-daemon")
    with pytest.raises(answers.AnswerError) as bare:
        answers.answer(home, item["id"], option="opt-yes-conditions")
    assert bare.value.exit_code == 3 and _choices(home) == []

    answers.answer(home, item["id"], option="opt-yes-conditions",
                   text="only if it does not restart my desktop session")

    approved = _item(home, "q-restart-daemon", "approved.pending")
    packet = attention_packet.build(home, approved["id"])
    assert packet["plan"]["conditions"] == "only if it does not restart my desktop session"


# --------------------------------------------------------- 6. sudo


def test_an_approve_on_a_plan_with_sudo_steps_waits_for_i_ran_it(tmp_path):
    """Mutation: launch on approve regardless of sudo steps (critique 2) ->
    red."""
    home = make_home(tmp_path)
    settings.config_set(home, "attention.terminal", "alacritty -e")
    _index(home, [_system_ask("q-restart-daemon", [], plan=_plan(sudo_steps=1))])
    item = _item(home, "q-restart-daemon")

    first = answers.answer(home, item["id"], option="opt-yes")

    assert first.state == "awaiting-sudo" and _calls(tmp_path, "systemd-run") == []
    waiting = _item(home, "q-restart-daemon", "ask.system-change")
    assert (waiting["class"], waiting["because"], waiting["state"]) == ("needs-you", "sudo", "awaiting-sudo")
    assert answers.RAN_SUDO_OPTION in [o["id"] for o in answers._options_for(waiting, None)]

    ran = answers.answer(home, item["id"], option=answers.RAN_SUDO_OPTION)

    assert ran.state == "running" and len(_calls(tmp_path, "systemd-run")) == 1
    assert _choices(home)[-1]["how"] == "ran-sudo" and ran.statement is None


def test_a_plan_of_only_sudo_steps_is_done_when_the_person_ran_them(tmp_path):
    home = make_home(tmp_path)
    _index(home, [_system_ask("q-root-only", [], plan=_plan(sudo_steps=2, plain_steps=0))])
    item = _item(home, "q-root-only")
    answers.answer(home, item["id"], option="opt-yes")
    result = answers.answer(home, item["id"], option=answers.RAN_SUDO_OPTION)
    assert result.state == "done" and _calls(tmp_path, "systemd-run") == []
    (outcome,) = conversation.outcome_rows(home)
    assert (outcome["by"], outcome["result"], outcome["note"]) == ("human", "done", "you ran the sudo steps")
    assert _item(home, "q-root-only", "decided.approved-done")["flagged"]


def test_no_brief_packet_or_hook_text_lets_an_agent_run_sudo(tmp_path):
    home = make_home(tmp_path)
    _index(home, [_system_ask("q-restart-daemon", [], plan=_plan(sudo_steps=1))])
    item = _item(home, "q-restart-daemon")
    rendered = [answers.RUN_BRIEF, attention_packet.render_md(attention_packet.build(home, item["id"]))]
    hooks = Path(__file__).resolve().parents[2] / "hooks"
    texts = [p.read_text(encoding="utf-8") for p in sorted(hooks.rglob("*")) if p.is_file()]
    assert texts, "positive control: the plugin's hook texts are read"
    assert "Never run sudo" in answers.RUN_BRIEF
    for text in rendered + texts:
        assert "sudo unless" not in text.lower()


# --------------------------------------------------------- 7. a relayed approval


def _said(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def test_an_approve_from_an_agent_shell_needs_the_persons_typed_yes(tmp_path, monkeypatch):
    """Mutation: skip the proof (`_prove` not called) -> red."""
    home = make_home(tmp_path)
    _index(home, [_system_ask("q-restart-daemon", [])])
    item = _item(home, "q-restart-daemon")
    vague = _transcript(home, tmp_path, [_typed("what is open"), _said("Shall I go ahead?"),
                                         _typed("yes")], session="sess-vague")
    _agent(monkeypatch, vague)
    with pytest.raises(answers.AnswerError) as unproved:
        answers.answer(home, item["id"], option="opt-yes", text="yes",
                       ref=f"transcript:{vague}#L3", note="relaying their yes")
    assert unproved.value.exit_code == 64 and _choices(home) == [] and _stmts(home) == []

    # Gate r1 MINOR 5: the yes was given to a DIFFERENT option of the same
    # item. The id is named, so only the label half of the proof refuses it.
    # Mutation: the label check always true -> red.
    other = "sess-other-option"
    rows = [_typed("what is open"),
            _said(f"{item['id']} asks whether to restart the daemon. Choose «No, leave it»? "
                  "Type yes."),
            _typed("yes")]
    (tmp_path / "transcripts" / "project" / f"{other}.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", other)
    with pytest.raises(answers.AnswerError) as wrong_label:
        answers.answer(home, item["id"], option="opt-yes", text="yes",
                       ref=f"transcript:{other}#L3", note="relaying their yes")
    assert wrong_label.value.exit_code == 64 and "Yes, restart it" in str(wrong_label.value)
    assert _choices(home) == [] and _stmts(home) == []

    # The same transcript root `_transcript` configured above.
    named = "sess-named"
    rows = [_typed("what is open"),
            _said(f"{item['id']} asks whether to restart the daemon. Choose «Yes, restart it»? "
                  "Type yes."),
            _typed("yes")]
    (tmp_path / "transcripts" / "project" / f"{named}.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", named)
    with attribution.process("agent"):
        result = answers.answer(home, item["id"], option="opt-yes", text="yes",
                                ref=f"transcript:{named}#L3", note="relaying their yes")

    (choice,) = _choices(home)
    assert choice["proof"] == f"transcript:{named}#L3" and choice["how"] == "relayed"
    body = git(home, "log", "-1", "--format=%B").stdout.strip().splitlines()
    assert body[-2:] == ["By: agent", f"Proof: transcript:{named}#L3"]
    assert result.state == "approved" and result.run is not None and result.run["exit"] is None
    assert _calls(tmp_path, "systemd-run") == []  # nothing launched from an agent's shell
    assert answers.run(home, item["id"]).exit == 64


# --------------------------------------------------------- 8. claim and done


def _approved(home: Path, tmp_path: Path) -> str:
    settings.config_set(home, "attention.terminal", "alacritty -e")
    _index(home, [_system_ask("q-restart-daemon", [])])
    answers.answer(home, _item(home, "q-restart-daemon")["id"], option="opt-yes")
    return attention.item_id("approved.pending", "q-restart-daemon")


def test_claim_and_done_belong_to_one_session(tmp_path):
    """Mutations: ignore the TTL / the other session in `claim` -> red;
    ignore the session on `done` -> red."""
    home = make_home(tmp_path)
    approved = _approved(home, tmp_path)
    answers.claim(home, approved, "sess-a")
    with pytest.raises(answers.AnswerError) as second:
        answers.claim(home, approved, "sess-b")
    assert second.value.exit_code == 3 and "sess-a" in str(second.value)
    with pytest.raises(answers.AnswerError) as other:
        answers.done(home, approved, session="sess-b", note="did it")
    assert other.value.exit_code == 3 and "sess-a" in str(other.value)
    assert conversation.outcome_rows(home) == []

    # A claim older than the 2-hour TTL no longer holds.
    stale = attention.cache_dir(home) / "attention" / "claims" / f"{approved}.json"
    stale.write_text(json.dumps({"session": "sess-a", "at": _iso(-timedelta(hours=3))}), "utf-8")
    answers.claim(home, approved, "sess-b")

    answers.done(home, approved, session="sess-b", note="the unit is missing; changed nothing",
                 failed=True)
    back = _item(home, "q-restart-daemon", "ask.system-change")
    assert back["state"] == "open"
    packet = attention_packet.build(home, back["id"])
    assert "the unit is missing" in json.dumps(packet["evidence"][0])


# --------------------------------------------------------- 9. undo and redo


def test_undo_runs_each_kinds_inverse(tmp_path, monkeypatch):
    """Mutations: swap hook deactivate/activate -> red; ignore `prior`
    (always `config unset`) -> red."""
    env = make_env(tmp_path)
    home = env.ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    runs = home / "cases" / "runs"
    runs.mkdir(parents=True)
    (runs / "run-aaaaaaaaaaaa.json").write_text(json.dumps({
        "version": 1, "actor": "steward", "run_id": "run-aaaaaaaaaaaa", "ledger_effects": [],
        "completed_at": _iso(-timedelta(hours=1)), "started_at": _iso(-timedelta(hours=2)),
        "decided": ["lrn-0000aaaa"],
        "attention_effects": [{"lesson": "lrn-0000aaaa", "verb": "route", "destination": "hook",
                               "always_loaded": False, "hook_activated": True,
                               "at": _iso(-timedelta(hours=1))}],
    }), encoding="utf-8")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(verbs, "hook_deactivate", lambda h, rid, **kw: calls.append(("off", rid)))
    monkeypatch.setattr(verbs, "hook_activate", lambda h, rid, **kw: calls.append(("on", rid)))
    hook = _item(home, "lrn-0000aaaa@" + json.loads(
        (runs / "run-aaaaaaaaaaaa.json").read_text())["attention_effects"][0]["at"])

    answers.undo(home, hook["id"])
    assert answers.redo_offered(home, hook["id"])
    answers.undo(home, hook["id"], redo=True)
    assert calls == [("off", "lrn-0000aaaa"), ("on", "lrn-0000aaaa")]
    assert not answers.redo_offered(home, hook["id"])

    digest = _item(home, "run-aaaaaaaaaaaa", "decided.steward-run")
    with pytest.raises(answers.AnswerError) as none:
        answers.undo(home, digest["id"])
    assert none.value.exit_code == 3

    # A tier-C config set an agent ran under the grant: undo restores the prior.
    grants.add(home, statement=_stmt(home, tmp_path))
    name = "worker.autokick"
    assert cli.main(["config", "set", name, "0"]) == 0  # the person's own value
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["config", "set", name, "1", "--note", "the user asked"]) == 0
    monkeypatch.delenv("CLAUDECODE")
    (row,) = grant_uses.read(home)
    assert row["prior"] == "0"
    use = _item(home, row["id"], "decided.grant-use")
    did = answers.undo(home, use["id"])
    assert did == f"self-learn config set {name} 0"
    assert settings.resolve_setting(home, settings.by_name(name))[0] in (False, 0, "0")


# --------------------------------------------------------- 10. a register click


def _register_ask(path: Path) -> dict:
    return {
        "id": "q-register-newhost", "kind": "ask", "cases": [],
        "text": f"Register {path} as a canon host in git mode? Yes registers it; no does not.",
        "why": "decides whether lessons for that project can be routed there",
        "register": {"kind": "project", "path": str(path), "mode": "git"},
        "needs": "user", "because": "foreign-history",
        "default": conversation.REGISTER_DEFAULT,
        "options": [{"id": "opt-register", "label": "Register it in git mode", "effect": "register",
                     "confirm": True},
                    {"id": "opt-no", "label": "No", "effect": "decline"}],
        "recommend": {"option": "opt-register", "reasoning": "its lessons wait for it"},
    }


def test_a_register_click_registers_through_the_text_free_core(tmp_path):
    """Not monkeypatched. Mutation: route the click through the bare-yes
    text rule (`_carry_out_registration` with the label as text) -> red
    (nothing registered)."""
    new = tmp_path / "new-host"
    init_repo(new)
    home = make_home(tmp_path)
    _index(home, [_register_ask(new)])
    item = _item(home, "q-register-newhost")
    with pytest.raises(answers.AnswerError) as unconfirmed:
        answers.answer(home, item["id"], option="opt-register")
    assert unconfirmed.value.exit_code == 3
    assert not hosts.is_project_host(hosts.load_hosts(home), new)

    result = answers.answer(home, item["id"], option="opt-register", confirm=True)

    assert hosts.is_project_host(hosts.load_hosts(home), new)
    assert hosts.host_mode(home, new, registration="project") == "git"
    assert result.registration and "registered" in result.registration
    assert result.state == "answered" and _choices(home)[0]["effect"] == "register"


# --------------------------------------------------------- 11. conflicts


def _case_on(home: Path, tmp_path: Path, rid: str, statement: str) -> str:
    _seed(home, rid)
    case = _steward_case([rid], "defer", "defer", scope="user")
    case["trigger"] = "weekly"
    case["dependencies"]["statements"] = [statement]
    stage = tmp_path / f"case-{rid}.yaml"
    _dump_yaml(stage, case)
    case_id = cases.record(home, stage, actor="overseer")
    verbs.defer(home, rid, until="2099-01-01", by="steward", no_push=True)
    return case_id


def _conflict(home: Path, tmp_path: Path) -> tuple[str, str, str, str]:
    older = statements.add(home, verbatim="always ask me first",
                           source={"message_ref": "transcript:old#L1"}, recorded_by="human")
    newer = statements.add(home, verbatim="never ask me unless sudo is involved",
                           source={"message_ref": "transcript:new#L1"}, recorded_by="human")
    on_older = _case_on(home, tmp_path, "lrn-c0000001", older)
    on_newer = _case_on(home, tmp_path, "lrn-c0000002", newer)
    _index(home, [{
        "id": "q-which-holds", "kind": "ask", "cases": [on_older, on_newer],
        "text": "Two of your statements disagree; which holds?", "why": "they conflict",
        "needs": "user", "because": "conflict", "default": "The newer statement holds meanwhile.",
        "statements": [older, newer],
        "options": [{"id": "opt-newer", "label": "Keep the newer one: never ask", "effect": "other"},
                    {"id": "opt-older", "label": "Keep the older one: always ask", "effect": "other"}],
        "recommend": {"option": "opt-newer", "reasoning": "it is the latest"},
    }])
    return older, newer, on_older, on_newer


def test_a_conflict_ruling_brings_back_the_losing_sides_cases(tmp_path):
    """Mutation: observe the older statement's cases when the older one
    holds -> red."""
    home = make_home(tmp_path)
    older, newer, on_older, on_newer = _conflict(home, tmp_path)
    item = _item(home, "q-which-holds", "ask.conflict")

    result = answers.answer(home, item["id"], option="opt-older")

    assert result.state == "answered" and result.statement is None
    line = f"human statement: user ruled on conflict:{older}+{newer} in the inbox (ref: {result.choice})"
    assert line in _observations(home, on_newer)
    assert "ruled on" not in _observations(home, on_older)
    ((entry, card),) = steward._reconsider_proposals(home)[0]
    assert entry.predecessor == on_newer and "ruled on" in card["card"]["unresolved"]
    assert not [i for i in attention.read(home)["items"] if i["subject"] == "q-which-holds"]


def test_words_on_a_conflict_are_an_instruction_on_both_sides(tmp_path):
    home = make_home(tmp_path)
    older, newer, on_older, on_newer = _conflict(home, tmp_path)
    item = _item(home, "q-which-holds")
    result = answers.answer(home, item["id"], text="Both: ask me only when it changes my system.")
    stmt = next(s for s in _stmts(home) if s["id"] == result.statement)
    assert stmt["answers"]["kind"] == "instruction"
    assert stmt["answers"]["ref"] == f"conflict:{older}+{newer}"
    for case_id in (on_older, on_newer):
        assert f"(ref: {result.statement})" in _observations(home, case_id)


# --------------------------------------------------------- 12. refreeze


def _tamper(home: Path, case_id: str) -> Path:
    path = next((home / "cases").glob(f"*/{case_id}.md"))
    text = path.read_text(encoding="utf-8")
    edited = text.replace("what should become of this pending lesson?",
                          "what should become of this lesson, edited by hand?", 1)
    assert edited != text
    path.write_text(edited, encoding="utf-8")
    return path


def test_refreeze_keeps_or_restores_a_hand_edited_case(tmp_path, monkeypatch, capsys):
    """Mutation: hash the whole body in `refreeze --keep` -> red."""
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _rid, case_id = _deferred_case(home, tmp_path)
    original = next((home / "cases").glob(f"*/{case_id}.md")).read_text(encoding="utf-8")
    _tamper(home, case_id)
    with pytest.raises(cases.CaseError):
        cases.show(home, case_id)  # control: the freeze check fails

    cases.refreeze(home, case_id, keep=True)
    view = cases.show(home, case_id, evidence_only=False)
    assert "edited by hand" in view.sections["Identity and scope"]
    # A refreeze appends nothing; observing still works on the kept text.
    cases.observe(home, case_id, "statement", text="still readable", by="human")

    _tamper_again = next((home / "cases").glob(f"*/{case_id}.md"))
    _tamper_again.write_text(_tamper_again.read_text(encoding="utf-8").replace(
        "edited by hand", "edited twice"), encoding="utf-8")
    cases.refreeze(home, case_id, keep=False)
    restored = cases.show(home, case_id, evidence_only=False)
    assert "edited by hand" in restored.sections["Identity and scope"]  # the last good commit
    assert "edited twice" not in restored.sections["Identity and scope"]
    assert "still readable" in restored.sections["Later observations"]
    assert original != _tamper_again.read_text(encoding="utf-8")

    _tamper_again.write_text(_tamper_again.read_text(encoding="utf-8").replace(
        "edited by hand", "edited thrice"), encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["case", "refreeze", case_id, "--keep", "--note", "n"]) == 64
    assert "refused from an agent's shell" in capsys.readouterr().err


# --------------------------------------------------------- 13. fix


def test_fix_restarts_only_the_host_unit(tmp_path, monkeypatch):
    """Mutation: restart `self-learn-ui.service` as well -> red."""
    home = make_home(tmp_path)
    broken = {"id": "att-0123456789ab", "kind": "broken.host", "class": "needs-you",
              "subject": "host@never", "title": "self-learn's host service has stopped"}
    monkeypatch.setattr(answers, "_find", lambda _home, item_id, items=None: (
        broken if item_id == broken["id"] else None))

    message = answers.fix(home, broken["id"], "opt-restart")

    assert [row[1:] for row in _calls(tmp_path, "systemctl")] == [
        ["--user", "reset-failed", "self-learn-host.service"],
        ["--user", "restart", "self-learn-host.service"],
    ]
    assert "restarted" in message
    with pytest.raises(answers.AnswerError) as wrong:
        answers.fix(home, broken["id"], "opt-other")
    assert wrong.value.exit_code == 3
    _agent(monkeypatch)
    with pytest.raises(answers.AnswerError) as agent:
        answers.fix(home, broken["id"], "opt-restart")
    assert agent.value.exit_code == 64 and len(_calls(tmp_path, "systemctl")) == 2


# --------------------------------------------------------- 14. the steward's card


def test_the_steward_card_says_chose_for_a_choice_and_quotes_a_relayed_statement(tmp_path):
    home = make_home(tmp_path)
    stmt = statements.add(home, verbatim="build it after the move",
                          source={"message_ref": "transcript:s#L2"}, recorded_by="agent")
    conversation.record_choice(home, {
        "id": "chc-0000aaaa", "item": "att-0123456789ab", "subject": "q-x", "how": "clicked",
        "option": "opt-build", "label": "Build it", "effect": "other", "recorded_by": "human"})
    conversation.record_choice(home, {
        "id": "chc-0000bbbb", "item": "att-0123456789ab", "subject": "q-x", "how": "relayed",
        "option": "opt-build", "label": "Build it", "effect": "other", "statement": stmt,
        "recorded_by": "agent"})
    clicked = steward._ask_context(home, (
        "- obs-1234abcd 2026-11-01T00:00:00Z human statement: user answered q-diagram after its "
        "default was applied (ref: chc-0000aaaa)"))
    relayed = steward._ask_context(home, (
        "- obs-1234abcd 2026-11-01T00:00:00Z agent statement: user answered q-diagram after its "
        "default was applied (ref: chc-0000bbbb)"))
    assert clicked is not None and "chose the offered option «Build it» (not their words)" in clicked
    assert "said" not in clicked and "Their words" not in clicked
    assert relayed is not None and "Relayed by an agent from their session" in relayed
    assert "build it after the move" in relayed


# --------------------------------------------------------- 15. questions reach the steward


def test_the_stewards_input_lists_typed_questions_since_its_last_run_not_replies(tmp_path):
    """Mutation: include `reply` rows -> red."""
    home = make_home(tmp_path)
    item = "att-0123456789ab"
    header = {"item_kind": "ask.sudo", "subject": "q-x", "title": "Install the package?"}
    workspace.append(home, item, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "old question",
         "at": "2026-01-01T00:00:00Z"},
    ], header=header)
    workspace.append(home, item, [
        {"role": "user", "origin": "typed", "kind": "question", "text": "never restart my desktop"},
        {"role": "user", "origin": "typed", "kind": "reply", "text": "a reply is a statement already"},
        {"role": "agent", "origin": "agent", "kind": "answer", "text": "an agent's answer"},
    ])

    rows = steward._workspace_questions(home, "2026-06-01T00:00:00Z")

    assert [r["text"] for r in rows] == ["never restart my desktop"]
    assert rows[0]["ref"] == f"workspace:{item}#T2" and rows[0]["title"] == "Install the package?"
    assert len(steward._workspace_questions(home, None)) == 2  # control: the older one counts with no floor
    packet = steward_prompt.assemble(
        home, tmp_path / "cache", steward_prompt.RunContext(
            run_id="r", stage_dir=tmp_path / "stage", packet_index=1, packet_count=1,
            last_run_at=None, verbs_the_runner_executes=()),
        [], conditions_items=[], workspace_questions=rows,
    )
    assert steward_prompt.WORKSPACE_QUESTIONS_TITLE in packet.per_packet
    assert f"workspace:{item}#T2" in packet.per_packet
    assert steward_prompt.WORKSPACE_QUESTIONS_TITLE not in packet.shared

    # Gate r1 MINOR 4: one a statement already cites (an earlier run
    # recorded it) is not shown again. Mutation: drop the cited filter -> red.
    statements.add(home, verbatim="never restart my desktop", recorded_by="agent",
                   source={"message_ref": f"workspace:{item}#T2", "surface": "inbox"})
    assert steward._workspace_questions(home, "2026-06-01T00:00:00Z") == []


def test_more_questions_than_fit_say_how_many_were_left_out(tmp_path):
    """Gate r1 MINOR 4: the cap keeps the newest and the block says how many
    older ones did not fit. Mutation: render without the count -> red."""
    home = make_home(tmp_path)
    item = "att-0123456789ab"
    rows = [{"role": "user", "origin": "typed", "kind": "question", "text": f"question {n}",
             "at": f"2026-07-01T00:{n // 60:02d}:{n % 60:02d}Z"}
            for n in range(steward.WORKSPACE_QUESTIONS_MAX + 3)]
    workspace.append(home, item, rows, header={"item_kind": "ask.sudo", "subject": "q-x",
                                               "title": "Install the package?"})

    kept, omitted = steward._workspace_questions_for_run(home)

    assert (len(kept), omitted) == (steward.WORKSPACE_QUESTIONS_MAX, 3)
    assert kept[0]["text"] == "question 3" and kept[-1]["text"] == f"question {len(rows) - 1}"
    packet = steward_prompt.assemble(
        home, tmp_path / "cache", steward_prompt.RunContext(
            run_id="r", stage_dir=tmp_path / "stage", packet_index=1, packet_count=1,
            last_run_at=None, verbs_the_runner_executes=()),
        [], conditions_items=[], workspace_questions=kept, workspace_questions_omitted=omitted,
    )
    assert "3 older question(s) since your last run are not shown" in packet.per_packet


def test_a_steward_run_hands_packet_1_the_questions_and_reads_them_once(tmp_path, monkeypatch):
    """Gate r1 MINOR 4: the `_run` wiring, end to end through a fake
    session. Mutations: drop `workspace_questions=` from `_run` -> red (the
    prompt lacks the question); `_workspace_questions_since` returns None
    -> red (the question shows again); floor on the run's `completed_at`
    -> red (a question sealed while the run worked is lost)."""
    from self_learn import worker
    from test_steward import _enable_steward, _seed_fresh_proposals, _write_decision_stage

    monkeypatch.setenv(worker.NO_PUSH_ENV, "1")
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    item = "att-0123456789ab"
    header = {"item_kind": "ask.sudo", "subject": "q-x", "title": "Install the package?"}
    workspace.append(home, item, [{"role": "user", "origin": "typed", "kind": "question",
                                   "text": "never restart my desktop"}], header=header)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", session)

    assert steward.run(home, dry_run=False).status == "applied"

    assert prompts and steward_prompt.WORKSPACE_QUESTIONS_TITLE in prompts[0]
    assert f"workspace:{item}#T1" in prompts[0] and "never restart my desktop" in prompts[0]
    assert steward._workspace_questions_for_run(home) == ([], 0)  # read once, not every night

    # The floor is when packet 1 last started (its prompt was assembled
    # then), not when the run completed: a question sealed in between was
    # never shown, and must be next time. Stretch the run to make the gap.
    (manifest,) = [m for m in steward.committed_manifests(home) if m.get("status") == "complete"]
    started = manifest["packets"][0]["last_attempt_at"]
    assert steward._workspace_questions_since(home) == started
    rel = next(p for p in git(home, "ls-files", "cases/runs").stdout.split()
               if manifest["run_id"] in p)
    data = json.loads((home / rel).read_text(encoding="utf-8"))
    data["completed_at"] = "2099-01-01T00:00:00Z"
    (home / rel).write_text(json.dumps(data), encoding="utf-8")
    git(home, "commit", "-q", "-am", "fixture: a long run")
    during = (datetime.strptime(started[:19], "%Y-%m-%dT%H:%M:%S")
              + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    workspace.append(home, item, [{"role": "user", "origin": "typed", "kind": "question",
                                   "text": "asked while it worked", "at": during}])
    kept, _omitted = steward._workspace_questions_for_run(home)
    assert [r["text"] for r in kept] == ["asked while it worked"]


# --------------------------------------------------------- fix round 1


def test_an_approval_not_yet_carried_out_can_be_changed(tmp_path):
    """Gate r1 MAJOR 1: "the answer stays changeable until it is carried
    out" (§0 call 3, §1.3). Mutations: refuse every other option on
    approved work again -> red; drop `approved` from
    `attention._approval_track`'s change states -> red (the approved item
    stays); the same in `conversation.approval_track` -> red."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    _index(home, [_system_ask("q-restart-daemon", [case_id])])
    (tmp_path / "shim-bin" / "alacritty").unlink()  # no terminal: nothing launches
    item = _item(home, "q-restart-daemon", "ask.system-change")
    first = answers.answer(home, item["id"], option="opt-yes")
    assert first.state == "approved" and first.run is not None and first.run["exit"] == 5
    approved = _item(home, "q-restart-daemon", "approved.pending")

    # A session that claimed it is carrying it out: refused, naming it.
    answers.claim(home, approved["id"], "sess-busy")
    with pytest.raises(answers.AnswerError) as busy:
        answers.answer(home, approved["id"], option="opt-no")
    assert busy.value.exit_code == 3 and "sess-busy" in str(busy.value)
    assert "close that terminal" not in str(busy.value).lower()
    assert len(_choices(home)) == 1
    (attention.cache_dir(home) / "attention" / "claims" / f"{approved['id']}.json").unlink()

    changed = answers.answer(home, approved["id"], option="opt-no")

    assert changed.state == "answered" and _choices(home)[-1]["effect"] == "decline"
    left = [i["kind"] for i in attention.read(home)["items"] if i["subject"] == "q-restart-daemon"]
    assert left == []  # no approved item, nothing needing you
    (row,) = [r for r in conversation._load_questions(home) if r["id"] == "q-restart-daemon"]
    track = conversation.approval_track(row, _choices(home), conversation.outcome_rows(home))
    assert track.state == "answered"
    assert f"human statement: user answered q-restart-daemon (ref: {changed.choice})" in (
        _observations(home, case_id))
    with pytest.raises(answers.AnswerError) as late:
        answers.claim(home, approved["id"], "sess-late")
    assert "changed their answer" in str(late.value)
    assert _calls(tmp_path, "systemd-run") == []


def test_a_draft_or_a_pasted_reply_with_no_option_on_a_plan_decides_nothing(tmp_path):
    """Gate r1 MINOR 2. Mutation: the plan guard back on `result.choice is
    None` -> red (the case is told and the steward re-decides)."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    _index(home, [_system_ask("q-restart-daemon", [case_id])])
    item = _item(home, "q-restart-daemon", "ask.system-change")
    _seal_agent(home, item, DRAFT, draft="drf-1a2b3c4d")

    sent = answers.answer(home, item["id"], draft_id="drf-1a2b3c4d")
    pasted = answers.answer(home, item["id"], text=f"fine by me. {DRAFT}")

    assert (sent.state, pasted.state) == ("open", "open")
    assert [c["how"] for c in _choices(home)] == ["draft-accepted", "draft-edited"]  # recorded
    assert "user answered" not in _observations(home, case_id)
    assert steward._reconsider_proposals(home)[0] == []
    assert _item(home, "q-restart-daemon", "ask.system-change")["state"] == "open"
    assert _calls(tmp_path, "systemd-run") == []


def test_words_on_finished_approved_work_are_an_overturn(tmp_path):
    """Gate r1 MINOR 3: "After an approved item is done, a new answer is an
    overturn" (§3.4.4). Mutation: keep the ask's row for a decided item
    (answered as the question) -> red."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    settings.config_set(home, "attention.terminal", "alacritty -e")
    _index(home, [_system_ask("q-restart-daemon", [case_id])])
    answers.answer(home, _item(home, "q-restart-daemon")["id"], option="opt-yes")
    approved = attention.item_id("approved.pending", "q-restart-daemon")
    answers.claim(home, approved, "sess-a")
    answers.done(home, approved, session="sess-a", note="restarted it")
    finished = _item(home, "q-restart-daemon", "decided.approved-done")
    assert steward._reconsider_proposals(home)[0] == []  # control

    result = answers.answer(home, finished["id"], text="Actually undo that, it broke my desktop.")

    stmt = next(s for s in _stmts(home) if s["id"] == result.statement)
    assert stmt["answers"] == {"kind": "instruction", "ref": case_id, "text": finished["title"]}
    line = f"human statement: user overturned {finished['id']} in the inbox (ref: {result.statement})"
    assert line in _observations(home, case_id)
    ((entry, _card),) = steward._reconsider_proposals(home)[0]
    assert entry.predecessor == case_id
    # NIT 7: "Run it now" on finished work is "not approved", not "unknown".
    assert answers.run(home, approved).exit == 3
    assert answers.run(home, _item(home, "q-restart-daemon", "decided.approved-done")["id"]).exit == 3


def test_redo_of_a_skill_write_writes_it_again_from_its_draft(tmp_path, monkeypatch):
    """Gate r1 MINOR 6: a grant use's redo is "the original verb with its
    recorded args" (§3.4.6), `skill write` included. Mutation: drop the
    `skill write` branch from `_run_argv` -> red (exit 3)."""
    from self_learn import skill_writer

    home = make_home(tmp_path)
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "SKILL.md").write_text("---\nname: diagrams\ndescription: d\n---\nbody\n", "utf-8")
    use_id = grant_uses.append(home, {"verb": "skill write",
                                      "args": ["diagrams", "--from", str(draft)],
                                      "statement": None, "note": "the overseer asked", "prior": None})
    written: list[tuple[str, list[str], str]] = []

    class _Ok:
        ok, problems = True, ()

    def fake_write(h, name, files, *, case, by, no_push=False, **kw):
        written.append((name, sorted(files), by))
        return _Ok()

    monkeypatch.setattr(skill_writer, "write", fake_write)
    item = _item(home, use_id, "decided.grant-use")

    did = answers.undo(home, item["id"], redo=True)

    assert did == f"self-learn skill write diagrams --from {draft}"
    assert written == [("diagrams", ["SKILL.md"], "human")]
    shutil.rmtree(draft)
    with pytest.raises(answers.AnswerError) as gone:
        answers.undo(home, item["id"], redo=True)
    assert gone.value.exit_code == 3 and "draft folder" in str(gone.value)
    assert len(written) == 1


def test_done_failed_on_a_stopped_ledger_gives_the_item_back(tmp_path):
    """Gate r1 NIT 8: the session that looked and chose not to clear the
    stopped write reports it with --failed; nothing can be committed, so the
    held click and the claim are dropped and the item is the person's
    again. Mutation: refuse `done --failed` while STOPPED -> red (exit 10)."""
    from self_learn import intents
    from test_recover_or_refuse import _plant_stop

    home = make_home(tmp_path)
    settings.config_set(home, "attention.terminal", "alacritty -e")
    target = home / "user" / "stop-probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("seed\n", encoding="utf-8")
    git(home, "add", "--", str(target))
    git(home, "commit", "-q", "-m", "seed probe")
    intent = _plant_stop(home, target)
    with pytest.raises(intents.LedgerStoppedError):
        with intents.ledger_write(home):
            pass
    path = home / ".intents" / f"{intent.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["started"] = _iso(-timedelta(days=2))
    path.write_text(json.dumps(data), encoding="utf-8")
    item = _item(home, intent.id, "broken.stopped")
    head = git(home, "rev-parse", "HEAD").stdout
    answers.answer(home, item["id"], option="opt-agent")
    answers.claim(home, item["id"], "sess-look")
    with pytest.raises(answers.AnswerError) as plain_done:
        answers.done(home, item["id"], session="sess-look", note="cleared it")
    assert plain_done.value.exit_code == 10  # control: a done still needs the ledger

    said = answers.done(home, item["id"], session="sess-look", failed=True,
                        note="the intent names a file I cannot account for; left it")

    assert "nothing committed" in said and git(home, "rev-parse", "HEAD").stdout == head
    assert attention._claim(home, item["id"], datetime.now(timezone.utc)) is None
    assert answers._held_approval(home, item["id"]) is None
    assert _item(home, intent.id, "broken.stopped")["state"] == "open"


# --------------------------------------------------------- 16. the lock invariant


def test_the_lock_invariant_walker_reaches_every_new_writer():
    """Mutation: move `record_choice`'s write out of `ledger_write` -> red."""
    from test_lock_invariant import _Analysis

    analysis = _Analysis()
    requires = analysis.requires_lock()
    for qual in ("overseer/conversation.record_choice", "attention_answers.append_outcome",
                 "cases.refreeze"):
        assert qual in analysis.funcs, qual
        assert analysis.mutations(qual, set(requires)), qual  # positive control
        assert analysis.unguarded(qual, set(requires)) == [], qual
        assert qual not in requires, qual


# --------------------------------------------------------- 17. change my answer


def test_a_second_answer_appends_and_the_latest_shows(tmp_path):
    home = make_home(tmp_path)
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    answers.answer(home, item["id"], option="opt-build")
    later = answers.answer(home, item["id"], text="Actually keep it where it is.")
    assert len(_choices(home)) == 1 and len(_stmts(home)) == 1
    shown = next(i for i in attention.read(home)["items"] if i["id"] == item["id"])
    assert shown["answer"]["how"] == "typed" and shown["answer"]["statement"] == later.statement


def test_an_answered_ask_still_takes_a_changed_answer_until_the_next_run(tmp_path):
    home = make_home(tmp_path)
    _index(home, [_sudo_ask("q-install-pkg", [])])
    item = _item(home, "q-install-pkg")
    answers.answer(home, item["id"], option="opt-will")
    assert not [i for i in attention.read(home)["items"] if i["id"] == item["id"]]
    answers.answer(home, item["id"], option="opt-no")
    assert [c["option"] for c in _choices(home)] == ["opt-will", "opt-no"]


# --------------------------------------------------------- the CLI


def test_the_cli_answers_with_json_and_refuses_an_unknown_item(tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _index(home, [_stead_ask("q-diagram-skill", [])])
    item = _item(home, "q-diagram-skill")
    reply = tmp_path / "reply.txt"
    reply.write_text("Build it next week.", encoding="utf-8")
    assert cli.main(["attention", "answer", item["id"], "--text-file", str(reply), "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["item"] == item["id"] and out["statement"].startswith("stmt-") and out["choice"] is None
    assert cli.main(["attention", "answer", "att-000000000000", "--option", "opt-x"]) == 2
    assert cli.main(["attention", "undo", item["id"]]) == 3
    assert cli.main(["attention", "run", "att-000000000000"]) == 2


# --------------------------------------------------------- the STOPPED ledger


def test_an_agent_look_at_a_stopped_ledger_is_held_launched_and_committed_by_done(tmp_path):
    """§3.4.8's `broken.stopped` "Have an agent look at it": nothing can be
    committed while the ledger is STOPPED, so the click is held on this
    machine and launched; `done` commits it once the intent is cleared.
    Mutation: refuse every answer while STOPPED (no held path) -> red."""
    from self_learn import intents
    from test_recover_or_refuse import _plant_stop

    home = make_home(tmp_path)
    settings.config_set(home, "attention.terminal", "alacritty -e")
    target = home / "user" / "stop-probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("seed\n", encoding="utf-8")
    git(home, "add", "--", str(target))
    git(home, "commit", "-q", "-m", "seed probe")
    intent = _plant_stop(home, target)
    with pytest.raises(intents.LedgerStoppedError):
        with intents.ledger_write(home):
            pass
    path = home / ".intents" / f"{intent.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["started"] = _iso(-timedelta(days=2))
    path.write_text(json.dumps(data), encoding="utf-8")
    item = _item(home, intent.id, "broken.stopped")
    head = git(home, "rev-parse", "HEAD").stdout

    with pytest.raises(answers.AnswerError) as words:
        answers.answer(home, item["id"], text="please look")
    assert words.value.exit_code == 10  # words cannot be held: nothing to cite
    result = answers.answer(home, item["id"], option="opt-agent")

    assert result.state == "running" and len(_calls(tmp_path, "systemd-run")) == 1
    assert git(home, "rev-parse", "HEAD").stdout == head and _choices(home) == []
    answers.claim(home, item["id"], "sess-fix")
    with pytest.raises(answers.AnswerError) as early:
        answers.done(home, item["id"], session="sess-fix", note="cleared it")
    assert early.value.exit_code == 10

    assert intents.clear_stopped(home, intent.id) == "cleared"
    answers.done(home, item["id"], session="sess-fix", note="inspected and cleared the intent")
    (choice,) = _choices(home)
    assert choice["id"] == result.choice and choice["effect"] == "approve"
    (outcome,) = conversation.outcome_rows(home)
    assert outcome["result"] == "done" and outcome["item"] == item["id"]
