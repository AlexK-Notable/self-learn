"""Shared fixtures (10 §0 rules 7/8: tests never touch the real ledger,
``~/.claude``, real cache, real runtime dir, or the network)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def redirected_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect every XDG/home var this package or its cli dependency
    could resolve, to throwaway dirs under ``tmp_path``. Returns the
    redirected paths so a test can assert against them directly.
    """
    cache_home = tmp_path / "cache"
    runtime_dir = tmp_path / "runtime"
    ledger_home = tmp_path / "ledger-home"
    cache_home.mkdir()
    runtime_dir.mkdir()
    ledger_home.mkdir()

    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("SELF_LEARN_HOME", str(ledger_home))

    return {
        "cache_home": cache_home,
        "runtime_dir": runtime_dir,
        "ledger_home": ledger_home,
    }
