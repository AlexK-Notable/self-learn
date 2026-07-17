"""CLI entry-point tests — --help works fully at U1; serve wires the real
server at U4 (this file's one updated baseline test, per the U4 task
brief: the "not implemented until U3" stub assertion is replaced with an
assertion that `serve` actually builds + runs the real app under uvicorn
on 127.0.0.1:$SELF_LEARN_UI_PORT). The pinned engine-not-built exit
(SELF_LEARN_PANE_ENGINE=cli) still short-circuits before uvicorn is ever
touched — unchanged from U1. Full end-to-end serve coverage (a real
subprocess, a real port, the token flow via httpx) lives in
``test_serve.py``, not here — this file stays a fast, non-blocking unit
test of the wiring."""

from __future__ import annotations

from pathlib import Path

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


def test_serve_wires_and_runs_the_real_app_under_uvicorn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """U4: `serve` no longer stubs — it builds the real ASGI app (default
    runner = RealRunner, per app.py) and hands it to uvicorn.run() on
    127.0.0.1:$SELF_LEARN_UI_PORT, in the foreground (rc 0 once uvicorn
    returns). uvicorn.run is monkeypatched so this stays a fast,
    non-blocking unit test — the real end-to-end server is test_serve.py's
    job."""
    _clear_self_learn_env(monkeypatch)
    ledger_home = tmp_path / "ledger-home"
    ledger_home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(ledger_home))
    monkeypatch.setenv("SELF_LEARN_UI_PORT", "18357")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    (tmp_path / "runtime").mkdir()
    (tmp_path / "cache").mkdir()

    import uvicorn

    calls: list[dict] = []

    def fake_run(app, *, host: str, port: int, **kwargs) -> None:
        calls.append({"app": app, "host": host, "port": port})

    monkeypatch.setattr(uvicorn, "run", fake_run)

    rc = main(["serve"])
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 18357
    # A real FastAPI app was actually constructed, not a stand-in.
    assert calls[0]["app"].__class__.__name__ == "FastAPI"

    # The per-start token was minted and written 0600 (middleware pin).
    token_path = tmp_path / "runtime" / "self-learn" / "ui-token"
    assert token_path.exists()
    assert oct(token_path.stat().st_mode)[-3:] == "600"


def test_serve_cli_engine_exits_with_pinned_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_self_learn_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_PANE_ENGINE", "cli")
    rc = main(["serve"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "engine not built — see 09 §4.1" in err
