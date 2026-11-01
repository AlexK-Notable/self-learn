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
    # S-109: with no authority in force (the CLI puts the
    # user's standing grant there, grants.authorize) the library refuses.
    with pytest.raises(settings.AgentSettingRefusal, match="person-only"):
        if operation == "set":
            settings.config_set(home, setting.name, raw)
        else:
            settings.config_unset(home, setting.name)
    assert (home / "config.yaml").read_bytes() == original
    assert git(home, "rev-parse", "HEAD").stdout == head


@pytest.mark.parametrize("markers", [(m,) for m in MARKERS] + [MARKERS, ("AI_AGENT", "CLAUDECODE")])
@pytest.mark.parametrize("marker_value", ["", "synthetic-private-value"])
@pytest.mark.parametrize("operation", ["set", "unset"])
def test_each_marker_cli_refuses(markers, marker_value, operation, tmp_path, monkeypatch, capsys):
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
    for marker in markers:
        monkeypatch.setenv(marker, marker_value)
    # S-109: an agent's shell sets a tier-C switch only under the
    # user's standing grant and with --note; without the note it is a usage
    # refusal (64), before the lock.
    assert cli.main(args) == 64
    captured = capsys.readouterr()
    assert captured.out == ""
    detected = ", ".join(marker for marker in MARKERS if marker in markers)
    assert captured.err == (
        f"self-learn config {operation}: config {operation} miner.engine is a person-only "
        "command; from an agent's shell it runs under the user's standing grant and needs "
        "--note TEXT saying why (the ledger records By: agent, the grant and the reason) "
        f"(agent shell detected: {detected})\n"
    )
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
