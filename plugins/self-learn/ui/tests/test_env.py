"""Env parsing tests (09 §4.4 / 10 §1; task U1 test bullet 2).

All calls pass an explicit ``environ`` mapping — never ``os.environ`` —
so these tests are hermetic regardless of the real process environment
(10 §0 rule 7/8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn_ui.env import (
    DEFAULT_PANE_BUDGET_USD,
    DEFAULT_PANE_ENGINE,
    DEFAULT_PANE_MAX_TURNS,
    DEFAULT_PANE_MODEL,
    DEFAULT_UI_PORT,
    ENGINE_NOT_BUILT_MESSAGE,
    EngineNotBuiltError,
    EnvError,
    load_env,
)


def test_defaults_with_empty_environ() -> None:
    cfg = load_env({})
    assert cfg.self_learn_home == Path("~/.self-learn").expanduser()
    assert cfg.ui_port == DEFAULT_UI_PORT == 7357
    assert cfg.ui_browser is None
    assert cfg.pane_model == DEFAULT_PANE_MODEL == "claude-sonnet-5"
    assert cfg.pane_budget_usd == DEFAULT_PANE_BUDGET_USD == 1.00
    assert cfg.pane_max_turns == DEFAULT_PANE_MAX_TURNS == 15
    assert cfg.pane_engine == DEFAULT_PANE_ENGINE == "sdk"


def test_all_vars_overridden() -> None:
    cfg = load_env(
        {
            "SELF_LEARN_HOME": "/tmp/some-ledger",
            "SELF_LEARN_UI_PORT": "9001",
            "SELF_LEARN_UI_BROWSER": "firefox",
            "SELF_LEARN_PANE_MODEL": "claude-opus-4",
            "SELF_LEARN_PANE_BUDGET_USD": "2.50",
            "SELF_LEARN_PANE_MAX_TURNS": "30",
            "SELF_LEARN_PANE_ENGINE": "sdk",
        }
    )
    assert cfg.self_learn_home == Path("/tmp/some-ledger")
    assert cfg.ui_port == 9001
    assert cfg.ui_browser == "firefox"
    assert cfg.pane_model == "claude-opus-4"
    assert cfg.pane_budget_usd == 2.50
    assert cfg.pane_max_turns == 30
    assert cfg.pane_engine == "sdk"


def test_home_is_expanded() -> None:
    cfg = load_env({"SELF_LEARN_HOME": "~/custom-ledger"})
    assert cfg.self_learn_home == Path("~/custom-ledger").expanduser()
    assert "~" not in str(cfg.self_learn_home)


def test_cli_engine_raises_pinned_exit() -> None:
    """09 §4.1: SELF_LEARN_PANE_ENGINE=cli must exit with this exact
    pinned message — never a silent fallback to sdk."""
    with pytest.raises(EngineNotBuiltError) as excinfo:
        load_env({"SELF_LEARN_PANE_ENGINE": "cli"})
    assert str(excinfo.value) == ENGINE_NOT_BUILT_MESSAGE
    assert ENGINE_NOT_BUILT_MESSAGE == "engine not built — see 09 §4.1"


def test_unknown_engine_value_raises_env_error() -> None:
    with pytest.raises(EnvError):
        load_env({"SELF_LEARN_PANE_ENGINE": "not-a-real-engine"})


def test_bad_port_raises_env_error() -> None:
    with pytest.raises(EnvError):
        load_env({"SELF_LEARN_UI_PORT": "not-a-number"})


def test_bad_budget_raises_env_error() -> None:
    with pytest.raises(EnvError):
        load_env({"SELF_LEARN_PANE_BUDGET_USD": "free"})


def test_bad_max_turns_raises_env_error() -> None:
    with pytest.raises(EnvError):
        load_env({"SELF_LEARN_PANE_MAX_TURNS": "lots"})
