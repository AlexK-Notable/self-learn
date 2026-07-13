"""SELF_LEARN_HOME resolution (08-build-plan §1 Ledger-home pin)."""

from pathlib import Path

from self_learn.ledger import resolve_home


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path))
    assert resolve_home() == tmp_path


def test_default_when_unset(monkeypatch):
    monkeypatch.delenv("SELF_LEARN_HOME", raising=False)
    assert resolve_home() == Path("~/repos/claude-skills").expanduser()


def test_empty_env_var_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SELF_LEARN_HOME", "")
    assert resolve_home() == Path("~/repos/claude-skills").expanduser()


def test_tilde_in_env_var_is_expanded(monkeypatch):
    monkeypatch.setenv("SELF_LEARN_HOME", "~/somewhere/ledger")
    resolved = resolve_home()
    assert resolved == Path("~/somewhere/ledger").expanduser()
    assert "~" not in str(resolved)
