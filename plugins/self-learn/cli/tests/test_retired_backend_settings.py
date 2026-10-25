"""2026-10-24 retirement: selectors are inert and diagnostics name them."""
from pathlib import Path

import pytest

from self_learn import cli, provider, settings
from self_learn.invocation import backend_for
from self_learn.invocation_sdk import SdkBackend


@pytest.mark.parametrize("channel,key", [
    ("config", "backend"),
    ("config", "backend_worker"),
    ("config", "backend_miner-session"),
    ("env", "SELF_LEARN_BACKEND"),
    ("env", "SELF_LEARN_BACKEND_WORKER"),
    ("env", "SELF_LEARN_OVERRIDE_INVOCATION_BACKEND"),
    ("env", "SELF_LEARN_OVERRIDE_INVOCATION_BACKEND_WORKER_REPAIR"),
])
@pytest.mark.parametrize("value", ["cli", "sdk", "unknown", ""])
def test_retired_selector_is_ignored_and_named_by_both_doctors(tmp_path, monkeypatch, capsys, channel, key, value):
    home = tmp_path / "ledger"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    # Positive control: both doctors render real rows before testing absence.
    for view in ("settings", "invocation"):
        cli.main(["doctor", view])
        out = capsys.readouterr().out
        assert "doctor:" in out
        assert ("provider.name" if view == "settings" else "switches") in out
        assert "retired and has no effect" not in out
    if channel == "config":
        from ruamel.yaml import YAML
        with (home / "config.yaml").open("w") as fh:
            YAML().dump({"invocation": {key: value}}, fh)
        label = f"invocation.{key}"
    else:
        monkeypatch.setenv(key, value)
        label = key
    assert isinstance(backend_for("worker", home=home), SdkBackend)
    resolved = provider.resolve(home, "worker")
    assert resolved.backend == "sdk" and resolved.backend_refused is None
    for view in ("settings", "invocation"):
        cli.main(["doctor", view])
        out = capsys.readouterr().out
        assert any("WARN" in row and label in row and "retired and has no effect" in row
                   for row in out.splitlines())
    assert settings.by_name("provider.name").name == "provider.name"
    with pytest.raises(KeyError):
        settings.by_name("invocation.backend")


@pytest.mark.parametrize("value", [None, 123, {}, {"nested": "private"}, ["private"]])
def test_malformed_retired_config_value_is_named_without_exposure(tmp_path, value):
    from ruamel.yaml import YAML
    (tmp_path / "config.yaml").write_text("provider:\n  name: anthropic\n")
    assert any(row.name == "provider.name" for row in settings.preflight(tmp_path))
    assert settings.retired_keys(tmp_path) == []
    with (tmp_path / "config.yaml").open("w") as fh:
        YAML().dump({"invocation": {"backend": value}}, fh)
    assert settings.retired_keys(tmp_path) == ["invocation.backend"]
    rows = [r for r in settings.preflight(tmp_path) if r.name == "retired"]
    assert len(rows) == 1 and rows[0].verdict == "WARN"
    assert "invocation.backend is retired and has no effect" in rows[0].detail
    assert "private" not in rows[0].detail
    assert isinstance(backend_for("worker", home=tmp_path), SdkBackend)


def test_real_failure_outranks_retired_warning_in_selftest(tmp_path, monkeypatch, capsys):
    from self_learn import selfcheck
    from support import make_env

    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "anthropic")
    path = env.ledger / "config.yaml"
    path.write_text("invocation:\n  backend: cli\n")
    assert cli.main(["--selftest"]) == 0
    assert "WARN invocation" in capsys.readouterr().out
    # A real provider failure, not an injected selftest verdict.
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_REGION", "")
    monkeypatch.setenv("SELF_LEARN_WORKER_MODEL", "claude-sonnet-5")
    rows = provider.preflight(env.ledger)
    assert any(r.name == "retired" and r.verdict == "WARN" for r in rows)
    assert any(r.name == "consistency" and r.verdict == "FAIL" for r in rows)
    assert selfcheck._check_invocation(env.ledger)[0] is selfcheck.Verdict.FAIL
    assert cli.main(["--selftest"]) == 1
    out = capsys.readouterr().out
    assert "FAIL invocation" in out
    assert "WARN invocation" not in out


def test_bedrock_consistency_still_runs_with_retired_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_REGION", "")
    monkeypatch.setenv("SELF_LEARN_WORKER_MODEL", "claude-sonnet-5")
    baseline = {(r.surface, r.cause) for r in provider.preflight(tmp_path)
                if r.name == "consistency" and r.verdict == "FAIL"}
    assert ("worker", "bedrock-needs-region") in baseline
    assert ("worker", "bedrock-model-is-alias") in baseline
    (tmp_path / "config.yaml").write_text("invocation:\n  backend_worker: cli\n")
    rows = provider.preflight(tmp_path)
    assert any(r.name == "retired" and r.verdict == "WARN" for r in rows)
    assert {(r.surface, r.cause) for r in rows
            if r.name == "consistency" and r.verdict == "FAIL"} == baseline


def test_unparseable_config_does_not_crash_health_views(tmp_path, monkeypatch, capsys):
    from support import make_env

    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    path = env.ledger / "config.yaml"
    path.write_text("invocation:\n  backend: cli\n")
    assert settings.retired_keys(env.ledger) == ["invocation.backend"]
    path.write_text("invocation: [\n")
    assert settings.retired_keys(env.ledger) == []
    for args, marker in [(["doctor", "settings"], "doctor:"),
                         (["doctor", "invocation"], "doctor:"),
                         (["--selftest"], "selftest:")]:
        cli.main(args)
        output = capsys.readouterr()
        assert marker in output.out
        assert "Traceback" not in output.out + output.err


@pytest.mark.parametrize("key", ["backend", "backend_worker-repair", "backend_old-surface"])
def test_retired_config_unset_commits_names_only_and_is_idempotent(tmp_path, monkeypatch, capsys, key):
    from ruamel.yaml import YAML
    from self_learn import intents
    from support import commit_all, git, make_env

    env = make_env(tmp_path)
    home = env.ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    path = home / "config.yaml"
    with path.open("w") as fh:
        YAML().dump({"invocation": {key: {"private-value": ["do-not-print"]}},
                     "provider": {"name": "anthropic"}}, fh)
    commit_all(home, "seed retired config")
    name = f"invocation.{key}"
    assert settings.retired_keys(home) == [name]
    for rows in (settings.preflight(home), provider.preflight(home)):
        assert any(r.name == "retired" and f"self-learn config unset {name}" in r.detail for r in rows)
    capsys.readouterr()
    assert cli.main(["config", "unset", name]) == 0
    output = capsys.readouterr()
    assert output.out.strip() == f"config unset: {name}"
    assert "private-value" not in output.out + output.err
    assert "do-not-print" not in output.out + output.err
    assert git(home, "log", "-1", "--format=%s").stdout.strip() == f"self-learn: config unset {name}"
    committed = git(home, "show", "HEAD:config.yaml").stdout
    assert YAML(typ="safe").load(committed) == {"provider": {"name": "anthropic"}}
    assert path.read_text() == committed
    assert settings.retired_keys(home) == []
    before = git(home, "rev-parse", "HEAD").stdout

    def no_lock(*args, **kwargs):
        pytest.fail("already-absent retired key must not acquire the ledger lock")

    monkeypatch.setattr(intents, "ledger_write", no_lock)
    assert cli.main(["config", "unset", name]) == 0
    assert "already unset" in capsys.readouterr().out
    assert git(home, "rev-parse", "HEAD").stdout == before
    assert settings.by_name("provider.name").name == "provider.name"
    with pytest.raises(KeyError):
        settings.by_name(name)
    assert cli.main(["config", "set", name, "sdk"]) == cli.EXIT_USAGE
    assert cli.main(["config", "unset", "invocation.other"]) == cli.EXIT_USAGE


def test_retired_unset_uses_normal_refusal_and_lock_order(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from self_learn import config, intents
    from support import commit_all, make_env

    home = make_env(tmp_path).ledger
    (home / "config.yaml").write_text("invocation:\n  backend: cli\n")
    commit_all(home, "seed retired config")
    events = []
    locked = False
    original_lock = intents.ledger_write

    @contextmanager
    def lock(*args, **kwargs):
        nonlocal locked
        events.append("lock")
        with original_lock(*args, **kwargs) as recovered:
            locked = True
            try:
                yield recovered
            finally:
                locked = False

    def spy(module, attr, label, requires_lock=False):
        original = getattr(module, attr)
        def call(*args, **kwargs):
            events.append(label)
            assert locked is requires_lock, label
            return original(*args, **kwargs)
        monkeypatch.setattr(module, attr, call)

    spy(settings, "_scan_config_write_or_refuse", "scan")
    spy(settings, "_dirty_config_check", "dirty")
    spy(config, "present", "present")
    spy(config, "unset_leaf", "unset", True)
    spy(settings, "_commit_or_half_written", "commit", True)
    monkeypatch.setattr(intents, "ledger_write", lock)
    setting, removed = settings.config_unset(home, "invocation.backend")
    assert setting.name == "invocation.backend" and removed is True
    assert events == ["scan", "dirty", "present", "lock", "unset", "commit"]


@pytest.mark.parametrize("refusal,expected", [("dirty", "uncommitted changes"),
                                            ("malformed", "not a mapping"),
                                            ("note", "secret scan")])
def test_retired_unset_refuses_before_lock_without_changes(tmp_path, monkeypatch, capsys, refusal, expected):
    from self_learn import intents
    from support import commit_all, git, make_env

    home = make_env(tmp_path).ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    path = home / "config.yaml"
    path.write_text("invocation:\n  backend: cli\n")
    commit_all(home, "seed retired config")
    assert cli.main(["config", "unset", "invocation.backend"]) == 0
    assert "config unset: invocation.backend" in capsys.readouterr().out
    path.write_text("invocation:\n  backend: cli\n")
    commit_all(home, "reseed retired config")
    args = ["config", "unset", "invocation.backend"]
    if refusal == "dirty":
        path.write_text("invocation:\n  backend: sdk\n")
    elif refusal == "malformed":
        path.write_text("invocation: 5\n")
        commit_all(home, "malformed retired section")
    else:
        args += ["--note", "ghp_" + "a" * 36]
    before = path.read_bytes()
    head = git(home, "rev-parse", "HEAD").stdout

    def no_lock(*args, **kwargs):
        pytest.fail("preflight refusal must precede the ledger lock")

    monkeypatch.setattr(intents, "ledger_write", no_lock)
    assert cli.main(args) == 1
    output = capsys.readouterr()
    assert expected in output.err
    assert "Traceback" not in output.err
    assert path.read_bytes() == before
    assert git(home, "rev-parse", "HEAD").stdout == head
