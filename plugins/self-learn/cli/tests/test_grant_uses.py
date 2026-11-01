"""The grant-use record (attention round 2026-10-31c, design r2 §3.4.6;
§5.1 test 14).

Person's-shell tests by default (the module fixture deletes every agent
marker); the agent-shell test sets one marker itself.
"""

from __future__ import annotations

import json

import pytest

from self_learn import attention, cli, grant_uses, grants, settings
from support import commit_all, git, init_repo, make_env
from test_grants import _stmt


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def _granted(env, tmp_path) -> str:
    stmt = _stmt(env.ledger, tmp_path)
    grants.add(env.ledger, statement=stmt)
    return stmt


def test_a_tier_c_config_set_under_the_grant_is_recorded_with_its_prior(env, tmp_path, monkeypatch, capsys):
    """Mutation: drop `use=` at the `config` call site in cli.py -> red."""
    stmt = _granted(env, tmp_path)
    name = "worker.autokick"
    assert settings.by_name(name).tier == "C"

    # A person's own shell needs no authority and records nothing.
    assert cli.main(["config", "set", name, "0"]) == 0
    assert grant_uses.read(env.ledger) == []
    assert cli.main(["config", "unset", name]) == 0
    capsys.readouterr()

    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["config", "set", name, "0", "--note", "the user asked for it"]) == 0
    (row,) = grant_uses.read(env.ledger)
    assert row["verb"] == "config set" and row["args"] == [name, "0"]
    assert row["prior"] is None and row["statement"] == stmt and row["proof"] is None
    assert row["note"] == "the user asked for it" and row["id"].startswith("gu-")
    body = git(env.ledger, "log", "-1", "--format=%B").stdout.strip()
    assert body.rpartition("\n\n")[2].splitlines() == ["By: agent", f"Grant: {stmt}"]
    assert git(env.ledger, "log", "-1", "--format=%s").stdout.strip().startswith("self-learn: grant use gu-")
    assert git(env.ledger, "status", "--porcelain").stdout == ""

    assert cli.main(["config", "set", name, "1", "--note", "and back"]) == 0
    rows = grant_uses.read(env.ledger)
    assert len(rows) == 2 and rows[1]["prior"] == "0"

    monkeypatch.delenv("CLAUDECODE")
    items = [i for i in attention.read(env.ledger)["items"] if i["kind"] == "decided.grant-use"]
    assert {i["subject"] for i in items} == {r["id"] for r in rows}
    first = next(i for i in items if i["subject"] == rows[0]["id"])
    assert first["undo"] == {"label": "Undo it", "redo_label": "Do it again", "redo": False}
    assert first["source"]["by"] == "agent"
    found = attention.find(env.ledger, first["id"])
    assert found is not None and found["_undo_verb"] == ["config", "unset", name]
    second = attention.find(env.ledger, next(i["id"] for i in items if i["subject"] == rows[1]["id"]))
    assert second is not None and second["_undo_verb"] == ["config", "set", name, "--", "0"]


def test_a_refused_verb_under_the_grant_records_nothing(env, tmp_path, monkeypatch, capsys):
    _granted(env, tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    code = cli.main(["host", "remove", str(tmp_path / "not-registered"), "--note", "tidy up"])
    assert code != 0
    assert grant_uses.read(env.ledger) == []


def test_a_host_add_under_the_grant_records_the_prior_registration(env, tmp_path, monkeypatch, capsys):
    _granted(env, tmp_path)
    project = tmp_path / "plain-project"
    init_repo(project)
    (project / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(project, "seed")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["host", "add", str(project), "--mode", "plain", "--note", "register it"]) == 0
    (row,) = grant_uses.read(env.ledger)
    assert row["verb"] == "host add" and row["prior"] is None
    assert row["args"] == [str(project), "--mode", "plain"]
    code = cli.main(["host", "set-mode", str(project), "git", "--project", "--note", "switch"])
    assert code == 0, capsys.readouterr().err
    rows = grant_uses.read(env.ledger)
    assert rows[1]["verb"] == "host set-mode"
    assert rows[1]["prior"] == {"kind": "project", "path": str(project.resolve()), "mode": "plain"}
    monkeypatch.delenv("CLAUDECODE")
    item = next(i for i in attention.read(env.ledger)["items"] if i["kind"] == "decided.grant-use")
    found = attention.find(env.ledger, item["id"])
    assert found is not None and found["_undo_verb"][:2] == ["host", "remove"]
    # An agent's own act never shows as a separate "registered" item too.
    assert not [i for i in attention.read(env.ledger)["items"] if i["kind"] == "decided.registration"]
