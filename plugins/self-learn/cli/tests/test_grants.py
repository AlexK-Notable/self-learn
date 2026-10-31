"""S-NEXT-attribution (2026-10-31b decision 6): the user's standing grant.

An agent's shell runs a person-only command (host add|remove|rebind|set-mode,
tier-C config set|unset, skill write|rename|retire) only under the user's
recorded grant and with a reason; the commit says `By: agent`, the grant and
the reason, never `human`.

Written under the user's 2026-10-30 rule (tests run only for a significant
change): the orchestrator runs these once over the combined landing. Each
test names the mutation it was checked against.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import cli, grants, hosts, settings, statements
from self_learn.hosts import host_add, host_mode
from support import commit_all, git, init_repo, make_env

WORDS = "unless sudo is involved, you should never have to tell me, 'X is waiting on you'"


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _body(repo: Path) -> str:
    return git(repo, "log", "-1", "--format=%B").stdout


def _final_block(body: str) -> list[str]:
    return body.strip().rpartition("\n\n")[2].splitlines()


def _transcript(home: Path, tmp_path: Path, rows: list[dict], session: str = "sess-grant") -> str:
    root = tmp_path / "transcripts"
    path = root / "project" / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with (home / "config.yaml").open("a", encoding="utf-8") as fh:
        fh.write(f"\nrefs:\n  transcript_roots: {json.dumps(str(root))}\n")
    commit_all(home, "configure synthetic transcript roots")
    return session


def _typed(text: str) -> dict:
    return {"type": "user", "message": {"content": text}}


def _stmt(home: Path, tmp_path: Path) -> str:
    """The user's typed statement, recorded the way the session recorded it."""
    session = _transcript(home, tmp_path, [_typed(f"let's go one step further. {WORDS}")])
    return statements.add(
        home,
        verbatim=WORDS,
        source={"message_ref": f"transcript:{session}#L1", "surface": "conversation"},
        recorded_by="human",
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def _granted(env, tmp_path) -> str:
    stmt = _stmt(env.ledger, tmp_path)
    grant, created = grants.add(env.ledger, statement=stmt)
    assert created and grants.active(env.ledger) == grant
    return stmt


def _agent(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert settings.agent_caller()


# ------------------------------------------------------------- the record


def test_a_person_records_the_grant_from_a_statement_they_typed(env, tmp_path, capsys):
    stmt = _stmt(env.ledger, tmp_path)
    assert cli.main(["grant", "add", "--statement", stmt]) == 0
    (row,) = grants.list_rows(env.ledger)
    assert (row["op"], row["statement"], row["verbatim"], row["by"]) == ("grant", stmt, WORDS, "human")
    assert row["message_ref"] == "transcript:sess-grant#L1"
    assert _final_block(_body(env.ledger)) == ["By: human"]
    assert cli.main(["grant", "add", "--statement", stmt]) == 0  # idempotent: nothing new
    assert len(grants.list_rows(env.ledger)) == 1


def test_an_agent_records_the_grant_only_with_a_reason_and_as_itself(env, tmp_path, monkeypatch, capsys):
    stmt = _stmt(env.ledger, tmp_path)
    _agent(monkeypatch)
    head = _head(env.ledger)
    assert cli.main(["grant", "add", "--statement", stmt]) == cli.EXIT_USAGE
    assert "--note" in capsys.readouterr().err
    assert _head(env.ledger) == head and grants.active(env.ledger) is None

    assert cli.main(["grant", "add", "--statement", stmt, "--note", "the user said so at 15:13"]) == 0
    body = _body(env.ledger)
    assert "the user said so at 15:13" in body
    assert _final_block(body) == ["By: agent", f"Grant: {stmt}"]
    assert grants.list_rows(env.ledger)[-1]["by"] == "agent"


def test_a_statement_whose_line_cannot_be_read_never_becomes_a_grant(env, tmp_path):
    """`statement add` lets a transcript it cannot find pass; a grant never
    does. Mutation: skip `_typed_words` in `grants.add` -> it is recorded."""
    _transcript(env.ledger, tmp_path, [_typed("hello")])  # control: roots configured
    stmt = statements.add(
        env.ledger, verbatim=WORDS,
        source={"message_ref": "transcript:no-such-session#L1", "surface": "conversation"},
        recorded_by="human",
    )
    with pytest.raises(grants.GrantError, match="cannot be read"):
        grants.add(env.ledger, statement=stmt)
    assert grants.list_rows(env.ledger) == []


def test_a_statement_on_a_line_the_user_did_not_type_never_becomes_a_grant(env, tmp_path):
    """A row written straight into the store, pointing at the assistant's own
    words. Mutation: drop the role check -> it is recorded."""
    session = _transcript(
        env.ledger, tmp_path,
        [_typed("hi"), {"type": "assistant", "message": {"content": WORDS}}],
    )
    path = env.ledger / "user-statements.jsonl"
    row = {
        "id": "stmt-0000beef", "at": "2026-10-31T00:00:00Z", "verbatim": WORDS,
        "answers": {"kind": "proposition", "ref": None, "text": None},
        "source": {"message_ref": f"transcript:{session}#L2", "surface": "conversation"},
        "scope": {"level": "user", "host": None}, "uncertainty": None,
        "recorded_by": "human", "amends": None,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    commit_all(env.ledger, "a forged statement")
    with pytest.raises(grants.GrantError, match="not a line the user typed"):
        grants.add(env.ledger, statement="stmt-0000beef")
    assert grants.list_rows(env.ledger) == []


def test_a_revoked_grant_lets_nothing_run_again(env, tmp_path, monkeypatch, capsys):
    _granted(env, tmp_path)
    proj = tmp_path / "proj"
    init_repo(proj)
    grant = grants.active(env.ledger)
    assert grant is not None
    assert grants.revoke(env.ledger, grant.id) is True
    assert grants.active(env.ledger) is None
    _agent(monkeypatch)
    assert cli.main(["host", "add", str(proj), "--note", "asked"]) == 1
    assert "no standing grant" in capsys.readouterr().err
    assert not hosts.is_project_host(hosts.load_hosts(env.ledger), proj)


# ---------------------------------------------- person-only commands under it


def test_host_set_mode_from_an_agent_shell_runs_under_the_grant_and_records_the_agent(
    env, tmp_path, monkeypatch, capsys
):
    """The hand step the user owed (checkpoint 94 item 1). Mutation: let
    `grants.authorize` return an authority with no grant in force -> the
    no-grant call below goes through."""
    proj = tmp_path / "proj"
    init_repo(proj)
    host_add(env.ledger, proj, "project", mode="git")
    stmt = _stmt(env.ledger, tmp_path)
    _agent(monkeypatch)
    yaml_before = (env.ledger / "hosts.yaml").read_bytes()

    assert cli.main(["host", "set-mode", str(proj), "plain"]) == cli.EXIT_USAGE
    assert "--note" in capsys.readouterr().err
    assert cli.main(["host", "set-mode", str(proj), "plain", "--note", "the user asked"]) == 1
    assert "no standing grant" in capsys.readouterr().err
    assert (env.ledger / "hosts.yaml").read_bytes() == yaml_before  # nothing written either time

    monkeypatch.delenv("CLAUDECODE")
    grants.add(env.ledger, statement=stmt)
    _agent(monkeypatch)
    assert cli.main(["host", "set-mode", str(proj), "plain", "--note", "the user asked"]) == 0
    assert host_mode(env.ledger, proj, registration="project") == "plain"
    body = _body(env.ledger)
    assert "the user asked" in body
    assert _final_block(body) == ["By: agent", f"Grant: {stmt}"]
    assert "By: human" not in body


@pytest.mark.parametrize("verb", ["add", "remove"])
def test_host_add_and_remove_from_an_agent_shell_need_the_grant_too(verb, env, tmp_path, monkeypatch, capsys):
    """New with the grant: before, an agent's shell could run `host add` and
    `host remove` freely while `set-mode` was refused. Mutation: delete the
    `grants.authorize` call in `cli._cmd_host` (the library check stays) ->
    the refusal comes back as a usage error (64) instead of 1."""
    proj = tmp_path / "proj"
    init_repo(proj)
    if verb == "remove":
        host_add(env.ledger, proj, "project", mode="git")
    before = hosts.is_project_host(hosts.load_hosts(env.ledger), proj)
    _agent(monkeypatch)
    assert cli.main(["host", verb, str(proj), "--note", "asked"]) == 1
    assert "no standing grant" in capsys.readouterr().err
    assert hosts.is_project_host(hosts.load_hosts(env.ledger), proj) == before

    monkeypatch.delenv("CLAUDECODE")  # control: a person's terminal needs nothing
    assert cli.main(["host", verb, str(proj)]) == 0
    assert hosts.is_project_host(hosts.load_hosts(env.ledger), proj) != before
    assert _final_block(_body(env.ledger)) == ["By: human"]


def test_a_tier_c_switch_from_an_agent_shell_is_set_under_the_grant(env, tmp_path, monkeypatch, capsys):
    """S-92's refusal, now the grant's. Mutation: drop the `acting(granted)`
    span in `cli._cmd_config` -> the library refuses (no authority in force)."""
    stmt = _granted(env, tmp_path)
    _agent(monkeypatch)
    assert cli.main(["config", "set", "steward.enabled", "1"]) == cli.EXIT_USAGE
    assert "--note" in capsys.readouterr().err
    assert cli.main(["config", "set", "steward.enabled", "1", "--note", "the user wants it on"]) == 0
    body = _body(env.ledger)
    assert "the user wants it on" in body
    assert _final_block(body) == ["By: agent", f"Grant: {stmt}"]
    assert cli.main(["config", "unset", "steward.enabled", "--note", "rolled back"]) == 0
    assert _final_block(_body(env.ledger)) == ["By: agent", f"Grant: {stmt}"]


def test_a_tier_a_switch_needs_no_grant(env, monkeypatch):
    """Control: only person-only commands go through the grant."""
    _agent(monkeypatch)
    assert grants.active(env.ledger) is None
    assert cli.main(["config", "set", "miner.cap_max", "3", "--note", "asked"]) == 0
    assert _final_block(_body(env.ledger)) == ["By: agent"]


def test_skill_commands_from_an_agent_shell_go_through_the_grant(env, tmp_path, monkeypatch, capsys):
    _agent(monkeypatch)
    assert cli.main(["skill", "retire", "no-such", "--case", "case-0000aaaa"]) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "person-only" in err and "--note" in err
    assert cli.main(["skill", "retire", "no-such", "--case", "case-0000aaaa", "--note", "x"]) == 1
    assert "no standing grant" in capsys.readouterr().err


def test_the_library_still_refuses_an_agent_with_no_authority_in_force(env, tmp_path, monkeypatch):
    """The command line puts the grant in force; a caller that skips it is
    refused by the library itself."""
    _granted(env, tmp_path)
    proj = tmp_path / "proj"
    init_repo(proj)
    _agent(monkeypatch)
    with pytest.raises(hosts.HostModeAgentRefusal):
        host_add(env.ledger, proj, "project", mode="git")
    with pytest.raises(settings.AgentSettingRefusal):
        settings.config_set(env.ledger, "steward.enabled", "1", note="x")
