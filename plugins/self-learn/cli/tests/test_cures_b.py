"""S-103: `host set-mode` and a typed yes that registers a host.

Written under the user's 2026-10-30 rule (tests run only for a significant
change): the orchestrator runs these once over the combined landing. Each
test names the master behaviour it fails on.

Agent markers are cleared for every test in this module by its `redirect`
fixture, so every call here models a person's own terminal unless a test
sets one.
"""

from __future__ import annotations

import argparse
import io
import json
import shlex
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, cli, intents, settings, statements
from self_learn.hosts import (
    MARKER_FILENAME,
    HostModeAgentRefusal,
    HostsError,
    host_add,
    host_mode,
    host_set_mode,
    is_project_host,
    load_hosts,
)
from self_learn.overseer import cli as overseer_cli
from self_learn.overseer import conversation
from self_learn.overseer import run as overseer_run
from support import commit_all, git, init_repo, make_env, verb_subject
from test_overseer_conversation import _case, _report_and_index


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    for marker in settings.AGENT_CALLER_MARKERS:  # every test is a person's shell unless it says so
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)  # set only by the tests that model an agent's own session


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _project(env, tmp_path: Path, name: str, mode: str, *, repo: bool = True) -> Path:
    """A project host registered in *mode* (a plain one need not be a repo)."""
    path = tmp_path / name
    if repo:
        init_repo(path)
    else:
        path.mkdir()
    host_add(env.ledger, path, "project", mode=mode)
    return path


# ------------------------------------------------------------ host set-mode


def test_git_to_plain_writes_the_marker_its_exclude_line_and_one_commit(tmp_path):
    """Master has no `host_set_mode` (the only route was remove + add)."""
    env = make_env(tmp_path)
    proj = _project(env, tmp_path, "proj", "git")
    assert host_mode(env.ledger, proj, registration="project") == "git"  # control
    assert not (proj / MARKER_FILENAME).exists()
    before = _head(env.ledger)

    result = host_set_mode(env.ledger, proj, "plain")

    assert (result.kind, result.old_mode, result.new_mode, result.changed) == (
        "project", "git", "plain", True,
    )
    assert host_mode(env.ledger, proj, registration="project") == "plain"
    assert (proj / MARKER_FILENAME).is_file()
    assert MARKER_FILENAME in (proj / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert _head(env.ledger) != before
    assert verb_subject(env.ledger) == (
        f"self-learn: host set-mode project {proj.resolve()} git → plain"
    )


def test_plain_to_git_drops_the_mode_key_and_leaves_the_marker(tmp_path):
    env = make_env(tmp_path)
    proj = _project(env, tmp_path, "plainproj", "plain", repo=False)
    init_repo(proj)  # a git work tree now, so going to git is sound
    assert load_hosts(env.ledger).project_modes == {str(proj.resolve()): "plain"}  # control

    result = host_set_mode(env.ledger, proj, "git")

    assert result.changed and (result.old_mode, result.new_mode) == ("plain", "git")
    assert host_mode(env.ledger, proj, registration="project") == "git"
    assert load_hosts(env.ledger).project_modes == {}  # git is the unwritten default
    assert (proj / MARKER_FILENAME).is_file()  # like `host remove`, the marker stays


def test_plain_to_git_on_a_directory_that_is_not_a_repo_refuses_and_writes_nothing(tmp_path):
    env = make_env(tmp_path)
    proj = _project(env, tmp_path, "norepo", "plain", repo=False)
    yaml_before = (env.ledger / "hosts.yaml").read_bytes()
    head = _head(env.ledger)

    with pytest.raises(HostsError, match="not a git repo"):
        host_set_mode(env.ledger, proj, "git")

    assert (env.ledger / "hosts.yaml").read_bytes() == yaml_before
    assert _head(env.ledger) == head
    assert host_mode(env.ledger, proj, registration="project") == "plain"


def test_a_host_already_in_the_mode_writes_nothing_and_repairs_a_missing_marker(tmp_path):
    env = make_env(tmp_path)
    proj = _project(env, tmp_path, "already", "plain")
    head = _head(env.ledger)

    again = host_set_mode(env.ledger, proj, "plain")
    assert not again.changed and not again.marker_restored
    assert _head(env.ledger) == head

    (proj / MARKER_FILENAME).unlink()
    repaired = host_set_mode(env.ledger, proj, "plain")
    assert not repaired.changed and repaired.marker_restored
    assert (proj / MARKER_FILENAME).is_file()
    assert _head(env.ledger) == head


def test_an_unregistered_path_is_refused_naming_host_add(tmp_path):
    env = make_env(tmp_path)
    stranger = tmp_path / "stranger"
    init_repo(stranger)
    with pytest.raises(HostsError, match="not a registered host.*host add"):
        host_set_mode(env.ledger, stranger, "plain")
    assert not (stranger / MARKER_FILENAME).exists()


def test_a_path_registered_both_ways_needs_the_registration_named(tmp_path):
    env = make_env(tmp_path)  # env.host is the skills root AND a project host
    yaml_before = (env.ledger / "hosts.yaml").read_bytes()
    with pytest.raises(HostsError, match="registered twice"):
        host_set_mode(env.ledger, env.host, "plain")
    assert (env.ledger / "hosts.yaml").read_bytes() == yaml_before  # nothing written

    result = host_set_mode(env.ledger, env.host, "plain", registration="skills-root")

    assert result.kind == "skills-root"
    assert host_mode(env.ledger, env.host, registration="skills-root") == "plain"
    assert host_mode(env.ledger, env.host, registration="project") == "git"  # untouched


def test_host_add_still_refuses_a_mode_change_and_now_names_set_mode(tmp_path):
    env = make_env(tmp_path)
    proj = _project(env, tmp_path, "flip", "git")
    with pytest.raises(HostsError, match="host set-mode"):
        host_add(env.ledger, proj, "project", mode="plain")
    assert host_mode(env.ledger, proj, registration="project") == "git"


def test_an_agent_shell_is_refused_before_any_write_even_for_a_no_op(tmp_path, monkeypatch):
    """The refusal comes before the lock and before the marker; it names the
    marker it saw and never its value."""
    env = make_env(tmp_path)
    proj = _project(env, tmp_path, "agentproj", "git")
    yaml_before = (env.ledger / "hosts.yaml").read_bytes()
    head = _head(env.ledger)
    monkeypatch.setenv("CODEX_THREAD_ID", "synthetic-private-value")
    real_ledger_write = intents.ledger_write

    def locked(*args, **kwargs):
        pytest.fail("the agent refusal must come before the ledger lock")

    monkeypatch.setattr(intents, "ledger_write", locked)
    with pytest.raises(HostModeAgentRefusal) as caught:
        host_set_mode(env.ledger, proj, "plain")
    assert "CODEX_THREAD_ID" in str(caught.value)
    assert "synthetic-private-value" not in str(caught.value)
    with pytest.raises(HostModeAgentRefusal):  # a request that changes nothing too
        host_set_mode(env.ledger, proj, "git")
    assert not (proj / MARKER_FILENAME).exists()
    assert (env.ledger / "hosts.yaml").read_bytes() == yaml_before
    assert _head(env.ledger) == head

    # Positive control: the same call from a person's shell goes through
    # (no `monkeypatch.undo()`: it would also undo the conftest fixture that
    # clears the agent markers).
    monkeypatch.setattr(intents, "ledger_write", real_ledger_write)
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert host_set_mode(env.ledger, proj, "plain").changed


def test_the_cli_maps_the_agent_refusal_to_exit_1_and_a_usage_mistake_to_64(
    tmp_path, monkeypatch, capsys
):
    env = make_env(tmp_path)
    proj = _project(env, tmp_path, "cliproj", "git")
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))

    monkeypatch.setenv("AI_AGENT", "1")
    assert cli.main(["host", "set-mode", str(proj), "plain"]) == 1
    assert "person's command" in capsys.readouterr().err
    assert host_mode(env.ledger, proj, registration="project") == "git"
    monkeypatch.delenv("AI_AGENT")

    stranger = tmp_path / "stranger"
    init_repo(stranger)
    assert cli.main(["host", "set-mode", str(stranger), "plain"]) == 64
    capsys.readouterr()

    assert cli.main(["host", "set-mode", str(proj), "plain"]) == 0
    out = capsys.readouterr().out
    assert f"project {proj.resolve()}: git → plain" in out
    assert "consent (plain mode)" in out
    assert host_mode(env.ledger, proj, registration="project") == "plain"

    assert cli.main(["host", "set-mode", str(proj), "plain"]) == 0
    assert "already plain — nothing changed" in capsys.readouterr().out


# ----------------------------------------------- a yes that registers a host


def _ask_row(home: Path, tmp_path: Path, host_path: Path, mode: str = "git") -> dict:
    case_id = _case(home, tmp_path, "7", {})
    return {
        "id": "q-register-newhost",
        "kind": "ask",
        "cases": [case_id],
        "text": (
            f"Register {host_path} as a canon host in {mode} mode? Yes registers it; "
            "no leaves it unregistered."
        ),
        "why": "decides whether lessons for that project can be routed there",
        "register": {"kind": "project", "path": str(host_path), "mode": mode},
    }


def _seed_registration_question(tmp_path, host_path: Path, mode: str = "git"):
    env = make_env(tmp_path)
    ask = _ask_row(env.ledger, tmp_path, host_path, mode)
    _report_and_index(env.ledger, [ask], ["- q-register-newhost: register the project"])
    shown = io.StringIO()
    conversation.open_questions(env.ledger, out=shown)
    return env.ledger, ask, shown.getvalue()


def _answers(home: Path) -> int:
    return len(statements.list_statements(home))


def test_open_shows_what_a_plain_yes_will_register(tmp_path):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, shown = _seed_registration_question(tmp_path, new)
    assert "q-register-newhost" in shown  # control: the ask itself is shown
    assert f"a plain yes registers: project host {new} in git mode" in shown
    # The one-line text recorded on the cited case carries the same words.
    observed = cases.show(home, ask["cases"][0], evidence_only=False).sections["Later observations"]
    assert "a plain yes registers:" in observed


@pytest.mark.parametrize("typed", ["yes", "Yes.", "y", "  YES!  "])
def test_a_bare_yes_registers_the_host_and_records_the_answer(tmp_path, typed):
    """Master: `respond` only recorded the statement; an agent ran `host add`."""
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    assert not is_project_host(load_hosts(home), new)  # control
    answers = _answers(home)

    result = conversation.respond(home, proposition=ask["id"], scope="user", text=typed)

    assert result.registered is True
    assert result.registration == f"registered project host {new} in git mode"
    assert is_project_host(load_hosts(home), new)
    assert host_mode(home, new, registration="project") == "git"
    assert _answers(home) == answers + 1
    assert conversation.open_question_count(home) == 0


def test_a_plain_mode_question_registers_plain(tmp_path):
    new = tmp_path / "scratch-dir"
    new.mkdir()  # not a git repo: only a plain registration is sound here
    home, ask, _shown = _seed_registration_question(tmp_path, new, mode="plain")

    conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert host_mode(home, new, registration="project") == "plain"
    assert (new / MARKER_FILENAME).is_file()


@pytest.mark.parametrize("typed", ["yes, but use plain mode", "not yet", "no", "yes please do it"])
def test_anything_but_a_bare_yes_records_the_answer_and_registers_nothing(tmp_path, typed):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    answers = _answers(home)

    result = conversation.respond(home, proposition=ask["id"], scope="user", text=typed)

    assert result.registered is False
    assert result.registration.startswith("nothing registered: the answer was not a plain yes")
    assert not is_project_host(load_hosts(home), new)
    assert _answers(home) == answers + 1  # the words are still the answer


def test_from_an_agent_shell_without_a_session_nothing_is_recorded_and_the_question_stays_open(
    tmp_path, monkeypatch
):
    """Round 2 MAJOR: an answer recorded without the registration read as done
    (S-96 hides an answered question). On master a yes from an agent's shell
    had no proof step at all; in round 1 it was recorded and nothing registered."""
    new = tmp_path / "new host"  # a space: the printed command must be shell-quoted
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    monkeypatch.setenv("CLAUDECODE", "1")
    answers = _answers(home)
    head = _head(home)

    with pytest.raises(conversation.ConversationError) as raised:
        conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    message = str(raised.value)
    assert "NOT registered" in message and "question stays open" in message
    assert "--session" in message  # it says how to get the typing checked
    assert f"self-learn host add {shlex.quote(str(new))}" in message
    assert not is_project_host(load_hosts(home), new)
    assert _answers(home) == answers and _head(home) == head  # nothing recorded


def _typed(text: str) -> dict:
    return {"type": "user", "message": {"content": text}}


def _transcript(home: Path, tmp_path: Path, rows: list[dict], session: str = "sess-yes") -> str:
    """A synthetic transcript under a configured root; returns the session id."""
    root = tmp_path / "transcripts"
    path = root / "project" / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with (home / "config.yaml").open("a", encoding="utf-8") as fh:
        fh.write(f"\nrefs:\n  transcript_roots: {json.dumps(str(root))}\n")
    commit_all(home, "configure synthetic transcript roots")
    return session


_ASSISTANT = {"type": "assistant", "message": {"content": "Register it?"}}
_CLICK = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "yes"}]}}


def test_from_an_agent_shell_a_session_whose_last_typed_row_is_a_yes_registers(tmp_path, monkeypatch):
    """The 10-28 hand step: the user answered in chat and an agent ran `host
    add`. The agent relaying the answer is the product's normal path, so it
    must register when the transcript proves the typing."""
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    session = _transcript(home, tmp_path, [_typed("go ahead and register it"), _ASSISTANT, _typed("yes")])
    # control: the proof itself reads the last typed row
    assert statements.latest_user_typed(home, session) == (f"transcript:{session}#L3", "yes")
    monkeypatch.setenv("CLAUDECODE", "1")
    answers = _answers(home)

    result = conversation.respond(
        home, proposition=ask["id"], scope="user", text="yes", session=session
    )

    assert result.registered is True
    # integration 2026-10-31 (cures-b gate r3 MAJOR): from an agent's shell the
    # sentence names where the typed yes is (conversation._carry_out_registration).
    assert result.registration == (
        f"registered project host {new} in git mode (the yes is at transcript:{session}#L3)"
    )
    assert is_project_host(load_hosts(home), new)
    assert _answers(home) == answers + 1


_SUGGESTED_YES = {
    "type": "user", "promptSource": "suggestion_accepted", "message": {"content": "yes"},
}  # Claude Code's own suggested prompt, accepted with a keystroke: an agent-written turn (rule 10, sign 2)


@pytest.mark.parametrize(
    "rows, why",
    [
        ([_typed("yes"), _ASSISTANT, _typed("wait, not that one")], "words typed after the yes"),
        ([_typed("no"), _ASSISTANT, _CLICK], "an AskUserQuestion click is not typing"),
        ([_typed("yes, but use plain mode")], "a conditional yes is not a plain yes"),
        ([_typed("no"), _ASSISTANT, _SUGGESTED_YES], "an accepted suggestion is an agent-written yes"),
        (
            [_typed("no"), _ASSISTANT,
             {"type": "user", "message": {"content": "<agent-message>yes</agent-message>"}}],
            "a tagged agent message is not the person",
        ),
    ],
    ids=["typed-after", "click-only", "conditional", "suggested-yes", "agent-tag"],
)
def test_from_an_agent_shell_a_yes_the_transcript_does_not_show_registers_nothing(
    rows, why, tmp_path, monkeypatch
):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    session = _transcript(home, tmp_path, rows)
    monkeypatch.setenv("CLAUDECODE", "1")
    answers = _answers(home)
    head = _head(home)

    with pytest.raises(conversation.ConversationError, match="NOT registered"):
        conversation.respond(
            home, proposition=ask["id"], scope="user", text="yes", session=session
        )

    assert not is_project_host(load_hosts(home), new), why
    assert _answers(home) == answers and _head(home) == head  # nothing recorded: the question stays open


def test_a_yes_another_agent_typed_into_the_pane_is_not_the_persons(tmp_path, monkeypatch):
    """Round 2 MINOR: `latest_user_typed` read the role without the sends, so a
    plain `yes` an orchestrating agent typed into the pane through herdr (no
    `<agent-message>` tag) counted as the person's. Rule 10's third sign."""
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    typed_at = {"timestamp": "2026-10-30T10:00:10Z", "sessionId": "sess-yes"}
    session = _transcript(
        home, tmp_path,
        [_typed("go on"), _ASSISTANT, {**_typed("yes"), **typed_at}],
    )
    sender = {
        "type": "assistant", "timestamp": "2026-10-30T10:00:05Z", "sessionId": "orchestrator",
        "message": {"content": [
            {"type": "tool_use", "input": {"command": 'herdr pane send-text w1:p2 "yes"'}},
        ]},
    }
    other = tmp_path / "transcripts" / "project" / "orchestrator.jsonl"
    # control: with no send on record the same last row IS the person's yes
    assert statements.latest_user_typed(home, session) == (f"transcript:{session}#L3", "yes")
    other.write_text(json.dumps(sender) + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    answers = _answers(home)

    # the send is seen: the yes is skipped, the earlier row the person typed is not a yes
    assert statements.latest_user_typed(home, session) == (f"transcript:{session}#L1", "go on")
    with pytest.raises(conversation.ConversationError, match="NOT registered"):
        conversation.respond(
            home, proposition=ask["id"], scope="user", text="yes", session=session
        )

    assert not is_project_host(load_hosts(home), new)
    assert _answers(home) == answers


def test_from_an_agent_shell_an_unknown_session_registers_nothing_and_records_nothing(
    tmp_path, monkeypatch
):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    _transcript(home, tmp_path, [_typed("yes")])  # control: transcripts are configured
    monkeypatch.setenv("CLAUDECODE", "1")
    answers = _answers(home)

    with pytest.raises(conversation.ConversationError, match="could not be checked"):
        conversation.respond(
            home, proposition=ask["id"], scope="user", text="yes", session="no-such-session"
        )

    assert not is_project_host(load_hosts(home), new)
    assert _answers(home) == answers


def test_an_agent_shell_proves_the_yes_in_its_own_session_without_being_told_the_id(
    tmp_path, monkeypatch
):
    """Round 2 MAJOR: an agent does not know its session id (teach.md says to
    omit it), so `--session` could not be passed on the normal path. The
    shell's own `$CLAUDE_CODE_SESSION_ID` is the default."""
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    session = _transcript(home, tmp_path, [_typed("register it?"), _ASSISTANT, _typed("yes")])
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)

    result = conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert result.registered is True
    assert result.registration == (
        f"registered project host {new} in git mode (the yes is at transcript:{session}#L3)"
    )
    assert is_project_host(load_hosts(home), new)


def test_a_session_other_than_the_shells_own_is_refused(tmp_path, monkeypatch):
    """Round 2 MINOR: the proof was tied neither to the caller's session nor to
    the question, so an agent could name an older session where the person had
    said yes to something else."""
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    older = _transcript(home, tmp_path, [_typed("yes")], session="older-session")
    own = tmp_path / "transcripts" / "project" / "own-session.jsonl"
    own.write_text(json.dumps(_typed("what about the host?")) + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "own-session")
    # control: the older session's last typed row IS a plain yes, so only the binding refuses it
    assert statements.latest_user_typed(home, older)[1] == "yes"
    answers = _answers(home)

    with pytest.raises(conversation.ConversationError, match="other than this shell's own"):
        conversation.respond(home, proposition=ask["id"], scope="user", text="yes", session=older)
    with pytest.raises(conversation.ConversationError, match="NOT registered"):  # and its own says no yes
        conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert not is_project_host(load_hosts(home), new)
    assert _answers(home) == answers


def test_naming_the_shells_own_session_explicitly_is_fine(tmp_path, monkeypatch):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    session = _transcript(home, tmp_path, [_typed("yes")])
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)

    result = conversation.respond(
        home, proposition=ask["id"], scope="user", text="yes", session=session
    )

    assert result.registered is True


def test_a_registration_done_by_hand_needs_no_proof_when_the_answer_comes_after(tmp_path, monkeypatch):
    """The recovery the refusal names: run `host add`, then answer again. It
    must not hit the same refusal (nothing is being registered)."""
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    host_add(home, new, "project", mode="git")
    monkeypatch.setenv("CLAUDECODE", "1")  # an agent's shell, no session, no transcript
    answers = _answers(home)

    result = conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert result.registered is True
    assert result.registration == f"already registered, left as it was: project host {new} in git mode"
    assert _answers(home) == answers + 1


def test_a_person_s_own_terminal_needs_no_session(tmp_path):
    """The proof is for an agent's shell only: the person typing the command
    is the consent (no session, no transcript configured)."""
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)

    result = conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert result.registered is True and is_project_host(load_hosts(home), new)


def test_a_skills_root_yes_that_would_replace_the_registered_root_is_refused(tmp_path):
    env = make_env(tmp_path)  # registers host-repo as the git skills root
    new = tmp_path / "other-root"
    init_repo(new)
    ask = {
        "id": "q-register-newhost", "kind": "ask", "cases": [_case(env.ledger, tmp_path, "7", {})],
        "text": f"Make {new} the skills root in git mode? Yes registers it; no leaves things as they are.",
        "why": "decides where skills are compiled",
        "register": {"kind": "skills-root", "path": str(new), "mode": "git"},
    }
    _report_and_index(env.ledger, [ask], ["- q-register-newhost: the skills root"])
    conversation.open_questions(env.ledger, out=io.StringIO())
    root_before = load_hosts(env.ledger).skills_root
    assert root_before is not None and root_before.resolve() != new.resolve()  # control
    answers = _answers(env.ledger)
    head = _head(env.ledger)

    with pytest.raises(conversation.ConversationError, match="would replace it"):
        conversation.respond(env.ledger, proposition=ask["id"], scope="user", text="yes")

    assert load_hosts(env.ledger).skills_root == root_before
    assert _answers(env.ledger) == answers and _head(env.ledger) == head


def test_a_registration_host_add_refuses_leaves_the_question_open_and_records_nothing(tmp_path):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    # The repository moved between the report and the answer.
    assert new.is_dir()  # control: it was there when the question was asked
    new.rename(new.with_name("moved-away"))
    answers = _answers(home)
    head = _head(home)

    with pytest.raises(conversation.ConversationError, match="Nothing was recorded"):
        conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert _answers(home) == answers
    assert _head(home) == head
    assert conversation.open_question_count(home) == 1  # still open


def test_a_path_registered_in_the_other_mode_refuses_the_whole_answer(tmp_path):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new, mode="plain")
    host_add(home, new, "project", mode="git")  # registered meanwhile, as git
    answers = _answers(home)

    with pytest.raises(conversation.ConversationError, match="host set-mode"):
        conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert _answers(home) == answers
    assert host_mode(home, new, registration="project") == "git"


def test_a_path_already_registered_in_the_asked_mode_is_left_as_it_was(tmp_path):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    host_add(home, new, "project", mode="git")
    yaml_before = (home / "hosts.yaml").read_bytes()

    result = conversation.respond(home, proposition=ask["id"], scope="user", text="yes")

    assert result.registered and result.registration.startswith("already registered, left as it was")
    assert (home / "hosts.yaml").read_bytes() == yaml_before  # registry untouched
    assert sum(1 for p in load_hosts(home).projects if p.resolve() == new.resolve()) == 1


def test_the_overseer_respond_command_prints_what_the_yes_did(tmp_path, monkeypatch, capsys):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    parser = argparse.ArgumentParser()
    overseer_cli.add_parser(parser.add_subparsers(dest="verb", required=True))

    args = parser.parse_args(
        ["overseer", "respond", "--proposition", ask["id"], "--scope", "user", "--text", "yes"]
    )
    assert overseer_cli.dispatch(args) == 0

    out = capsys.readouterr().out
    assert "recorded" in out
    assert f"registered project host {new} in git mode" in out
    assert is_project_host(load_hosts(home), new)


def test_the_overseer_respond_command_takes_a_session_for_an_agent_shell(tmp_path, monkeypatch, capsys):
    new = tmp_path / "new-host"
    init_repo(new)
    home, ask, _shown = _seed_registration_question(tmp_path, new)
    session = _transcript(home, tmp_path, [_typed("yes")])
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("CLAUDECODE", "1")
    parser = argparse.ArgumentParser()
    overseer_cli.add_parser(parser.add_subparsers(dest="verb", required=True))

    args = parser.parse_args(
        ["overseer", "respond", "--proposition", ask["id"], "--scope", "user", "--text", "yes",
         "--session", session]
    )
    assert args.session == session
    assert overseer_cli.dispatch(args) == 0

    assert f"registered project host {new} in git mode" in capsys.readouterr().out
    assert is_project_host(load_hosts(home), new)


# ------------------------------------------------ the register field's rules


def _register(path, mode="git", kind="project"):
    return {"path": path, "mode": mode, "kind": kind}


@pytest.mark.parametrize(
    "register, text, fragment",
    [
        (_register("/srv/app"), "Register /srv/app in git mode?", None),
        (_register("/srv/app", "plain", "skills-root"), "Make /srv/app a PLAIN skills root?", None),
        ({"path": "/srv/app", "mode": "git"}, "Register /srv/app in git mode?", None),
        (_register("/srv/app"), "Enable the new feature? Yes turns it on (git mode).", "text must name"),
        # the path must be the whole path, and the mode a phrase, not a stray word
        (_register("/srv/app"), "Register /srv/app-old in git mode?", "text must name"),
        (_register("/srv/app"), "Register /srv/app/sub in git mode?", "text must name"),
        (_register("/srv/app"), "Register /home/user/srv/app in git mode?", "text must name"),
        (_register("/srv/app"), "Register /srv/app.git in git mode?", "text must name"),
        (_register("/srv/app"), "Register /srv/app, a git repository?", "text must name"),
        # round 2: ordinary prose is not a mode, and a text naming the other mode names neither
        (_register("/srv/app", "plain"), "Register /srv/app in plain words?", "text must name"),
        (_register("/srv/app", "git"),
         "Register /srv/app as a plain host? Its CLAUDE.md is tracked in git history.", "text must name"),
        (_register("/srv/app", "plain"),
         "Register /srv/app as a plain host? Its CLAUDE.md is tracked in git history.", None),
        (_register("/srv/app", "git"), "Register /srv/app in git mode, not plain mode?", "text must name"),
        (_register("/srv/app", "plain"), "Register /srv/app? A plain yes will do.", "text must name"),
        (_register("/srv/app"), "Register /srv/app (git mode).", None),
        (_register("/srv/app", "plain"), "Register /srv/app as a plain host.", None),
        (_register("/srv/app", "plain"), "Register /srv/app?", "text must name"),
        (_register("srv/app"), "Register srv/app in git mode?", "absolute path"),
        (_register("/srv/app\n/etc"), "Register /srv/app in git mode?", "absolute path"),
        (_register("/srv/app", "both"), "Register /srv/app both?", "register.mode"),
        (_register("/srv/app", "git", "workspace"), "Register /srv/app in git mode?", "register.kind"),
        ({"path": "/srv/app"}, "Register /srv/app?", "path and mode"),
        ({"path": "/srv/app", "mode": "git", "extra": 1}, "Register /srv/app in git mode?", "path and mode"),
        ("/srv/app", "Register /srv/app in git mode?", "path and mode"),
    ],
)
def test_normalize_register_accepts_only_what_the_question_says(register, text, fragment):
    normalized, problem = conversation.normalize_register(register, text)
    if fragment is None:
        assert problem is None and normalized is not None
        assert normalized["kind"] == register.get("kind", "project")
    else:
        assert normalized is None and fragment in problem


def _dump(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        YAML().dump(data, fh)


def test_the_runner_keeps_a_good_register_and_drops_one_the_text_does_not_name(tmp_path):
    case_id = "case-12345678"
    good = {
        "id": "q-register-app", "kind": "ask", "cases": [case_id],
        "text": "Register /srv/app as a canon host in git mode? Yes registers it; no does not.",
        "why": "decides whether its lessons can be routed there",
        "register": {"path": "/srv/app", "mode": "git"},
    }
    hidden = {
        "id": "q-enable-feature", "kind": "ask", "cases": [case_id],
        "text": "Do you want the nightly report enabled? Yes enables it.",
        "why": "decides whether the report is built",
        "register": {"path": "/srv/app", "mode": "git"},
    }
    path = tmp_path / "questions.yaml"
    _dump(path, {"questions": [good, hidden]})

    index, dropped = overseer_run._questions(path, {}, {case_id})

    assert [row["id"] for row in index["questions"]] == ["q-register-app"]  # control: one kept
    assert index["questions"][0]["register"] == {"kind": "project", "path": "/srv/app", "mode": "git"}
    assert len(dropped) == 1 and "q-enable-feature" in dropped[0] and "text must name" in dropped[0]


def test_an_ask_with_no_register_is_unchanged(tmp_path):
    case_id = "case-12345678"
    plain = {
        "id": "q-plain-ask", "kind": "ask", "cases": [case_id],
        "text": "Will you keep using this repository next month?", "why": "decides retention",
    }
    path = tmp_path / "questions.yaml"
    _dump(path, {"questions": [plain]})
    index, dropped = overseer_run._questions(path, {}, {case_id})
    assert dropped == [] and "register" not in index["questions"][0]


def test_a_reading_in_the_index_cannot_carry_a_register(tmp_path):
    env = make_env(tmp_path)
    row = {
        "id": "um-1a2b@r1", "kind": "reading", "cases": [_case(env.ledger, tmp_path, "8", {})],
        "register": {"path": "/srv/app", "mode": "git"},
    }
    _report_and_index(env.ledger, [row], ["- um-1a2b@r1: a reading"])
    with pytest.raises(conversation.ConversationError, match="cannot carry a register"):
        conversation.open_question_count(env.ledger)


def test_the_phase_b_prompt_tells_the_overseer_about_register(tmp_path):
    flat = " ".join(overseer_run._phase_b_prompt(tmp_path, (), ()).split())
    assert "kind: ask is a decision or fact only the user has" in flat  # control: the ask rules are there
    assert "register: {path: <absolute path>, mode: git or plain" in flat
    assert "must name that path exactly and that mode" in flat


def test_the_printed_host_add_line_is_quoted_for_a_shell():
    line = conversation._hand_command({"kind": "skills-root", "path": "/srv/my app", "mode": "plain"})
    assert line == "`self-learn host add '/srv/my app' --skills-root --mode plain`"
    assert conversation._hand_command({"kind": "project", "path": "/srv/app", "mode": "git"}) == (
        "`self-learn host add /srv/app --mode git`"
    )
