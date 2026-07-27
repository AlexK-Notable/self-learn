"""Shared fixtures (10 §0 rules 7/8: tests never touch the real ledger,
``~/.claude``, real cache, real runtime dir, or the network)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _redirect_env_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autouse cache/env isolation for EVERY UI test (spec:
    ui-test-cache-isolation-spec.md r2 §3.1). Measured cause: without
    this, every UI test that resolves ``self_learn.worker.cache_dir()``
    (directly or transitively — e.g. via ``self_learn_ui.middleware``'s
    token-path fallback or ``self_learn_ui.uilog``) writes a fresh
    ``home-<digest>`` directory into the developer's REAL
    ``~/.cache/self-learn`` as a side effect of merely resolving a path
    (``worker.py`` ``mkdir``s at path-resolution time). Measured leak:
    exactly 176 stray directories per full UI suite run before this
    fixture existed. Mirrors ``cli/tests/conftest.py``'s
    ``_worker_test_defaults`` in intent, adapted to this package (the UI
    package additionally needs ``XDG_RUNTIME_DIR`` for the UI token file
    and doesn't need ``SELF_LEARN_COALESCE_SECS``).

    A future reader deleting this fixture should know it costs: the real
    ``~/.cache/self-learn``, the real ``~/.self-learn`` ledger, the real
    ``~/.claude`` dir, and the real ``~/.claude/projects`` transcripts
    tree all go back to being reachable by every test in this package.

    Ordering / naming (spec §3.1 constraints, verify-don't-assume): this
    fixture is autouse, so pytest instantiates it before the explicitly
    requested ``redirected_xdg`` fixture below when a test asks for both
    — ``redirected_xdg``'s ``setenv`` calls run second and win, so
    ``tests/test_cache_path.py`` (its one consumer) is unaffected. Its
    subdirectory names (``default-*``) are deliberately distinct from
    ``redirected_xdg``'s (``cache``, ``runtime``, ``ledger-home``) even
    though both fixtures share the same ``tmp_path`` — identical names
    would make that ordering claim untestable.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "default-cache"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "default-runtime"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "default-home"))
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "default-claude"))
    monkeypatch.setenv(
        "SELF_LEARN_TRANSCRIPTS_DIR", str(tmp_path / "default-transcripts")
    )
    # No detached worker/miner spawns from the suite (mirrors the CLI
    # fixture's SELF_LEARN_WORKER_AUTOKICK; the UI package also has a
    # miner-side autokick knob the CLI fixture doesn't need to touch).
    monkeypatch.setenv("SELF_LEARN_WORKER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")


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


@pytest.fixture(autouse=True)
def _client_contexts():
    """Arms support.CLIENT_STACK (Y-15: entered TestClients — one
    persistent loop per test so background pane drains survive across
    requests; exited/cleaned at test end)."""
    import contextlib

    import support

    with contextlib.ExitStack() as stack:
        support.CLIENT_STACK = stack
        yield
    support.CLIENT_STACK = None
