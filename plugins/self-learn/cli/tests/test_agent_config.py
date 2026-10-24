"""Tier-C shell refusals, with real scratch-ledger writes as controls."""

import pytest

from self_learn import cli, intents, settings
from support import git, make_home


TIER_C = [s for s in settings.REGISTRY if s.tier == "C"]
MARKERS = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT",
    "CODEX_THREAD_ID", "CODEX_SESSION_ID", "HERMES_SESSION_ID",
)


@pytest.mark.parametrize("setting", TIER_C, ids=lambda s: s.name)
@pytest.mark.parametrize("operation", ["set", "unset"])
def test_each_tier_c_refused_before_lock(setting, operation, tmp_path, monkeypatch):
    home = make_home(tmp_path)
    raw = "0" if setting.kind == "bool" else str(setting.default)
    before = git(home, "rev-parse", "HEAD").stdout
    settings.config_set(home, setting.name, raw)
    assert git(home, "rev-parse", "HEAD").stdout != before
    before = git(home, "rev-parse", "HEAD").stdout
    assert settings.config_unset(home, setting.name)[1]
    assert git(home, "rev-parse", "HEAD").stdout != before
    settings.config_set(home, setting.name, raw)
    original = (home / "config.yaml").read_bytes()
    head = git(home, "rev-parse", "HEAD").stdout
    monkeypatch.setenv("CODEX_THREAD_ID", "synthetic")

    def locked(*args, **kwargs):
        pytest.fail("agent refusal must happen before requesting the ledger lock")

    monkeypatch.setattr(intents, "ledger_write", locked)
    with pytest.raises(settings.AgentSettingRefusal, match="human's switch"):
        if operation == "set":
            settings.config_set(home, setting.name, raw)
        else:
            settings.config_unset(home, setting.name)
    assert (home / "config.yaml").read_bytes() == original
    assert git(home, "rev-parse", "HEAD").stdout == head


@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize("operation", ["set", "unset"])
def test_each_marker_cli_refuses(marker, operation, tmp_path, monkeypatch, capsys):
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    args = ["config", operation, "miner.engine"]
    if operation == "set":
        args.append("session")
    before = git(home, "rev-parse", "HEAD").stdout
    settings.config_set(home, "miner.engine", "digest")
    assert git(home, "rev-parse", "HEAD").stdout != before
    before = git(home, "rev-parse", "HEAD").stdout
    assert cli.main(args) == 0
    assert git(home, "rev-parse", "HEAD").stdout != before
    settings.config_set(home, "miner.engine", "digest")
    original = (home / "config.yaml").read_bytes()
    head = git(home, "rev-parse", "HEAD").stdout
    capsys.readouterr()
    monkeypatch.setenv(marker, "")
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "miner.engine is the human's switch" in captured.err
    assert "run the same command in your own terminal (not through an agent)" in captured.err
    assert (home / "config.yaml").read_bytes() == original
    assert git(home, "rev-parse", "HEAD").stdout == head


def test_tier_a_agent_and_human_herdr_terminal(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    monkeypatch.setenv("HERDR_ENV", "synthetic")
    assert not settings.agent_caller()
    settings.config_set(home, "miner.engine", "session")
    assert settings.resolve_setting(home, settings.by_name("miner.engine"))[0] == "session"
    for marker in MARKERS:
        monkeypatch.setenv(marker, "synthetic")
    before = git(home, "rev-parse", "HEAD").stdout
    settings.config_set(home, "miner.cap_max", "7")
    assert git(home, "rev-parse", "HEAD").stdout != before
    assert settings.resolve_setting(home, settings.by_name("miner.cap_max"))[0] == 7
    before = git(home, "rev-parse", "HEAD").stdout
    assert settings.config_unset(home, "miner.cap_max")[1]
    assert git(home, "rev-parse", "HEAD").stdout != before
