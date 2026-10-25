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
