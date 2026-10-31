"""S-103 as amended by S-NEXT-attribution (cures CU-1): a typed yes
registers a host from an agent's shell only when it answers THAT question.

Part A: the assistant's own visible message between the person's previous
typed row and the yes must name the question's id, the path and the mode,
and no other open registration question. Part B: an ask may carry
`register: {action: set-mode}`, and a switch to git mode takes self-learn's
own exclude lines for the files git mode now commits.

Written under the user's 2026-10-30 rule (tests run only for a significant
change): the orchestrator runs these once over the combined landing. Each
test names the mutation it was checked against.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from self_learn import attribution, gitops, settings, statements
from self_learn.hosts import MARKER_FILENAME, host_add, host_mode, host_set_mode, is_project_host, load_hosts
from self_learn.overseer import conversation
from support import git, init_repo, make_env
from test_cures_b import _answers, _ask_row, _transcript, _typed
from test_overseer_conversation import _case, _report_and_index


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _said(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _naming(qid: str, path: Path, mode: str = "git") -> dict:
    return _said(f"Register {path} as a project host in {mode} mode ({qid})? Type yes to do it.")


def _seed(tmp_path: Path, asks: list[dict] | None = None):
    new = tmp_path / "new-host"
    init_repo(new)
    env = make_env(tmp_path)
    ask = _ask_row(env.ledger, tmp_path, new)
    rows = [ask, *(asks or [])]
    _report_and_index(env.ledger, rows, [f"- {row['id']}: a question" for row in rows])
    conversation.open_questions(env.ledger, out=io.StringIO())
    return env.ledger, ask, new


def _agent(monkeypatch, session: str) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)


def _refused(home: Path, ask: dict, match: str) -> None:
    answers, head = _answers(home), _head(home)
    with pytest.raises(conversation.ConversationError, match=match):
        conversation.respond(home, proposition=ask["id"], scope="user", text="yes")
    assert _answers(home) == answers and _head(home) == head  # nothing recorded


# --------------------------------------------------------------- part A


def test_a_yes_to_a_message_about_something_else_registers_nothing(tmp_path, monkeypatch):
    """T1. Mutation: return proved right after the plain-yes check in
    `consent.prove_typed_yes` -> it registers."""
    home, ask, new = _seed(tmp_path)
    session = _transcript(home, tmp_path, [
        _typed("can you look at the tests"), _said("Shall I run the tests now?"), _typed("yes"),
    ])
    _agent(monkeypatch, session)
    _refused(home, ask, "does not name q-register-newhost, the path, git mode")
    assert not is_project_host(load_hosts(home), new)


def test_a_yes_to_a_message_naming_the_question_registers(tmp_path, monkeypatch):
    """T1's control, and T5: the commit says who did it and why. Mutation:
    drop `note=` from the `host_add` call in `_carry_out_registration` ->
    the `Answers:` line is gone."""
    home, ask, new = _seed(tmp_path)
    session = _transcript(home, tmp_path, [
        _typed("what is waiting"), _naming(ask["id"], new), _typed("yes"),
    ])
    _agent(monkeypatch, session)
    result = conversation.respond(home, proposition=ask["id"], scope="user", text="yes")
    assert result.registered is True
    assert is_project_host(load_hosts(home), new)
    log = git(home, "log", "--format=%s%n%b%x00").stdout.split("\x00")
    commit = next(entry for entry in log if "self-learn: host add project" in entry)
    assert commit.strip().splitlines()[0] == f"self-learn: host add project {new}"  # subject pinned
    assert "Answers: q-register-newhost" in commit
    assert commit.strip().splitlines()[-2:] == ["By: agent", f"Proof: transcript:{session}#L3"]


def test_a_persons_own_yes_records_what_it_answered(tmp_path):
    """In a person's terminal no proof is needed and the commit says `By:
    human`; its body still names the question. Mutation: drop `note=` from
    the `host_add` call in `_carry_out_registration` -> no `Answers:` line
    (in an agent's shell the authority's reason carries the same words)."""
    home, ask, new = _seed(tmp_path)
    with attribution.process("human"):  # what `cli.main` sets for a person's terminal
        result = conversation.respond(home, proposition=ask["id"], scope="user", text="yes")
    assert result.registered is True
    log = git(home, "log", "--format=%s%n%b%x00").stdout.split("\x00")
    commit = next(entry for entry in log if "self-learn: host add project" in entry)
    assert "Answers: q-register-newhost" in commit
    assert commit.strip().splitlines()[-1] == "By: human"


def test_a_message_naming_two_registration_questions_is_ambiguous(tmp_path, monkeypatch):
    """T2. Mutation: drop the `ambiguous` loop -> it registers."""
    other_path = tmp_path / "other-host"
    init_repo(other_path)
    home, ask, new = _seed(tmp_path)
    second = {
        "id": "q-register-other", "kind": "ask", "cases": ask["cases"],
        "text": f"Register {other_path} as a canon host in git mode? Yes registers it.",
        "why": "decides it", "register": {"kind": "project", "path": str(other_path), "mode": "git"},
    }
    _report_and_index(home, [ask, second], ["- q-register-newhost: a", "- q-register-other: b"])
    session = _transcript(home, tmp_path, [
        _typed("go"),
        _said(f"Register {new} in git mode (q-register-newhost) and {other_path} in git mode "
              "(q-register-other)? Type yes."),
        _typed("yes"),
    ])
    _agent(monkeypatch, session)
    _refused(home, ask, "also names q-register-other")
    assert not is_project_host(load_hosts(home), new)


def test_naming_it_only_in_a_tool_call_or_its_output_does_not_count(tmp_path, monkeypatch):
    """T3: the person reads the assistant's text, not a tool's input or
    output. Mutation: build `asked` from `refs._raw_text` -> it registers."""
    home, ask, new = _seed(tmp_path)
    shown = f"- q-register-newhost: Register {new} as a canon host in git mode?"
    session = _transcript(home, tmp_path, [
        _typed("anything waiting?"),
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": f"self-learn overseer open  # q-register-newhost {new} git mode"}},
        ]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": shown}]}},
        _said("Shall I?"),
        _typed("yes"),
    ])
    _agent(monkeypatch, session)
    _refused(home, ask, "does not name")
    assert not is_project_host(load_hosts(home), new)


def test_a_question_named_two_typed_rows_back_must_be_restated(tmp_path, monkeypatch):
    """T4. Mutation: start the window at the session's first row instead of
    the person's previous typed row -> it registers."""
    home, ask, new = _seed(tmp_path)
    session = _transcript(home, tmp_path, [
        _typed("anything?"),
        _naming(ask["id"], new),
        _typed("what does that do?"),
        _said("It lets self-learn commit its lessons there."),
        _typed("yes"),
    ])
    _agent(monkeypatch, session)
    _refused(home, ask, "restate")
    assert not is_project_host(load_hosts(home), new)


def test_typed_turn_reads_only_the_visible_text_since_the_previous_typed_row(tmp_path):
    env = make_env(tmp_path)
    session = _transcript(env.ledger, tmp_path, [
        _typed("one"), _said("first"), _typed("two"), _said("second"),
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "x", "input": {"a": "hidden"}}]}},
        _said("third"), _typed("yes"),
    ])
    turn = statements.typed_turn(env.ledger, session)
    assert (turn.ref, turn.text) == (f"transcript:{session}#L7", "yes")
    assert turn.asked == "second\nthird"
    assert statements.latest_user_typed(env.ledger, session) == (turn.ref, turn.text)


# --------------------------------------------------------------- part B


def _set_mode_ask(home: Path, tmp_path: Path, path: Path, mode: str) -> dict:
    return {
        "id": "q-switch-mode", "kind": "ask", "cases": [_case(home, tmp_path, "9", {})],
        "text": f"Switch {path} to {mode} mode? Yes switches it; no leaves it.",
        "why": "decides who commits there",
        "register": {"kind": "project", "path": str(path), "mode": mode, "action": "set-mode"},
    }


def test_a_set_mode_question_answered_yes_switches_the_mode(tmp_path):
    """Mutation: dispatch every register to `host_add` -> refused "registered
    in the other mode"."""
    env = make_env(tmp_path)
    proj = tmp_path / "proj"
    init_repo(proj)
    host_add(env.ledger, proj, "project", mode="plain")
    ask = _set_mode_ask(env.ledger, tmp_path, proj, "git")
    assert conversation.normalize_register(ask["register"], ask["text"])[0] == ask["register"]
    _report_and_index(env.ledger, [ask], ["- q-switch-mode: switch it"])
    shown = io.StringIO()
    conversation.open_questions(env.ledger, out=shown)
    assert f"a plain yes does: switch project host {proj} to git mode" in shown.getvalue()
    result = conversation.respond(env.ledger, proposition=ask["id"], scope="user", text="yes")
    assert result.registered is True
    assert host_mode(env.ledger, proj, registration="project") == "git"
    again = conversation.respond(env.ledger, proposition=ask["id"], scope="user", text="yes")
    assert again.registration.startswith("already so")


def test_an_unknown_register_action_is_refused(tmp_path):
    reg = {"kind": "project", "path": "/srv/app", "mode": "git", "action": "remove"}
    register, problem = conversation.normalize_register(reg, "Register /srv/app in git mode?")
    assert register is None and "register.action" in (problem or "")


def test_switching_to_git_takes_out_self_learns_own_lines_for_committed_files(tmp_path):
    """Mutation: skip `_unexclude_for_git` -> the CLAUDE.md line stays."""
    env = make_env(tmp_path)
    proj = tmp_path / "proj"
    init_repo(proj)
    host_add(env.ledger, proj, "project", mode="plain")
    gitops.ensure_excluded(proj, ["/CLAUDE.md", "/CLAUDE.local.md", "/.claude/rules/x.md"])
    exclude = gitops.git_path(proj, "info/exclude")
    exclude.write_text("# mine\n/notes.txt\n" + exclude.read_text(encoding="utf-8"), encoding="utf-8")
    before = exclude.read_text(encoding="utf-8")
    assert "/CLAUDE.md\n" in before and f"/{MARKER_FILENAME}\n" in before  # control

    changed = host_set_mode(env.ledger, proj, "git")

    after = exclude.read_text(encoding="utf-8")
    assert set(changed.unexcluded) == {"/CLAUDE.md", "/.claude/rules/x.md"}
    assert "/CLAUDE.md\n" not in after and "/.claude/rules/x.md" not in after
    for kept in ("# mine\n/notes.txt\n", "/CLAUDE.local.md\n", f"/{MARKER_FILENAME}\n",
                 gitops.EXCLUDE_BEGIN, gitops.EXCLUDE_END):
        assert kept in after


def test_a_git_mode_commit_cannot_stage_a_file_the_block_still_excludes(tmp_path):
    """Why the removal is needed (measured, not assumed): git refuses to
    stage a new file its ignore rules match, so a git-mode compile into a
    target the plain host had excluded fails its commit."""
    proj = tmp_path / "proj"
    init_repo(proj)
    gitops.ensure_excluded(proj, ["/CLAUDE.md"])
    (proj / "CLAUDE.md").write_text("canon\n", encoding="utf-8")
    added = subprocess.run(
        ["git", "-C", str(proj), "add", "--", "CLAUDE.md"], capture_output=True, text=True
    )
    assert added.returncode != 0 and "ignored" in (added.stderr + added.stdout)
    assert gitops.drop_excluded(proj, "/", ["CLAUDE.local.md"]) == ["/CLAUDE.md"]
    again = subprocess.run(
        ["git", "-C", str(proj), "add", "--", "CLAUDE.md"], capture_output=True, text=True
    )
    assert again.returncode == 0


def test_a_path_still_plain_in_its_other_registration_keeps_every_line(tmp_path):
    env = make_env(tmp_path)  # env.host is registered as the skills root and a project, both git
    host_set_mode(env.ledger, env.host, "plain", registration="project")
    host_set_mode(env.ledger, env.host, "plain", registration="skills-root")
    gitops.ensure_excluded(env.host, ["/CLAUDE.md"])
    changed = host_set_mode(env.ledger, env.host, "git", registration="skills-root")
    assert changed.changed and changed.unexcluded == ()
    assert "/CLAUDE.md\n" in gitops.git_path(env.host, "info/exclude").read_text(encoding="utf-8")
