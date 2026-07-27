"""Guard for `tests/conftest.py`'s autouse `_redirect_env_defaults` fixture
(spec ui-test-cache-isolation-spec.md r2 §3.2).

Asserts the MECHANISM, not the fixture's own `setenv` calls — reading
`os.environ["XDG_CACHE_HOME"]` back and checking it starts with `tmp_path`
would be near-tautological (it would pass even against a fixture that
redirects the wrong variable, since the assertion never calls the code
that actually consumes the var). Instead each test below calls the REAL
production resolver named in spec §3.2 and asserts ITS return value lands
under `tmp_path`.

§2 puts five variables in scope; a fixture that redirects only
`XDG_CACHE_HOME` must fail four of these five tests — that is the
point (verified by criterion 3: each variable removed independently from
the fixture, one mutation at a time, confirms exactly its own assertion
here fails while the other four still pass — `lrn-fe16fceb`, "a guard
that passes in both states is theatre").
"""

from __future__ import annotations

import os
from pathlib import Path

from self_learn.ledger import resolve_home
from self_learn.miner import transcripts_root
from self_learn.selfcheck import claude_runtime_dir
from self_learn.worker import cache_dir

from self_learn_ui.middleware import resolve_token_path


def _assert_under_tmp(resolved: Path, tmp_path: Path, var: str) -> None:
    # `is_relative_to`, NOT `str().startswith()`: a string prefix passes for a
    # SIBLING of tmp_path (`<tmp_path>-elsewhere`, or `…di1` against `…di10`),
    # so the assertion would report "under tmp_path" for a path that is not.
    # Demonstrated live at the 2026-07-27 code gate (mutation EXTRA-2b).
    assert resolved.is_relative_to(tmp_path), (
        f"{var}'s resolver returned {resolved!r}, which is NOT under this "
        f"test's tmp_path ({tmp_path!r}) — the autouse redirect for "
        f"{var} is missing or broken, and this test would otherwise be "
        "free to resolve real user state."
    )


def test_xdg_cache_home_is_redirected(tmp_path: Path) -> None:
    """`self_learn.worker.cache_dir()` — worker.py:112. The leak itself:
    a read-only call `mkdir`s this path as a side effect."""
    _assert_under_tmp(cache_dir(), tmp_path, "XDG_CACHE_HOME")


def test_xdg_runtime_dir_is_redirected(tmp_path: Path) -> None:
    """`self_learn_ui.middleware.resolve_token_path()` — middleware.py:77.
    Asserted WITH the var set: its unset-fallback is `cache_dir()`, which
    would mask a missing `XDG_RUNTIME_DIR` redirect by silently passing
    via the cache-dir path instead."""
    assert os.environ.get("XDG_RUNTIME_DIR"), (
        "XDG_RUNTIME_DIR is unset in this test's environment — the "
        "autouse fixture must set it so this assertion exercises the "
        "runtime-dir branch, not resolve_token_path()'s cache_dir() "
        "fallback."
    )
    _assert_under_tmp(resolve_token_path(), tmp_path, "XDG_RUNTIME_DIR")


def test_self_learn_home_is_redirected(tmp_path: Path) -> None:
    """`self_learn.ledger.resolve_home()` — ledger.py:44. Also the
    cache-namespace key: an unredirected home is how a unique ledger
    home per test mints a unique cache namespace (spec §1)."""
    _assert_under_tmp(resolve_home(), tmp_path, "SELF_LEARN_HOME")


def test_self_learn_claude_dir_is_redirected(tmp_path: Path) -> None:
    """`self_learn.selfcheck.claude_runtime_dir()` — selfcheck.py:471."""
    _assert_under_tmp(claude_runtime_dir(), tmp_path, "SELF_LEARN_CLAUDE_DIR")


def test_self_learn_transcripts_dir_is_redirected(tmp_path: Path) -> None:
    """`self_learn.miner.transcripts_root()` — miner.py:182."""
    _assert_under_tmp(transcripts_root(), tmp_path, "SELF_LEARN_TRANSCRIPTS_DIR")
