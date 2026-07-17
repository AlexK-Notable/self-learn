"""CLI entry-point tests — --help works fully at U1; serve is a stub that
reports "not implemented until U3" (or the pinned engine-not-built exit)
and returns non-zero (10 §3 task U1 DoD)."""

from __future__ import annotations

import pytest

from self_learn_ui.cli import build_parser, main

_ENV_VARS = (
    "SELF_LEARN_HOME",
    "SELF_LEARN_UI_PORT",
    "SELF_LEARN_UI_BROWSER",
    "SELF_LEARN_PANE_MODEL",
    "SELF_LEARN_PANE_BUDGET_USD",
    "SELF_LEARN_PANE_MAX_TURNS",
    "SELF_LEARN_PANE_ENGINE",
)


def _clear_self_learn_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic isolation from the real shell environment (10 §0 rule 7/8)
    — a dev machine's own SELF_LEARN_* vars must never leak into these
    process-level tests."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "self-learn-ui" in out
    assert "serve" in out


def test_no_args_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_serve_stub_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_self_learn_env(monkeypatch)
    rc = main(["serve"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not implemented until U3" in err


def test_serve_cli_engine_exits_with_pinned_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_self_learn_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_PANE_ENGINE", "cli")
    rc = main(["serve"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "engine not built — see 09 §4.1" in err
