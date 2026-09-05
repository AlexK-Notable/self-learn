"""Tests for the ``self-learn-ui paths`` verb (D8: 10 §1, decision D8 —
Python owns the cache-directory and token-path derivations;
``scripts/self-learn-ui-open`` asks for them through this verb instead of
re-deriving them in bash, and only falls back to its own bash mirror
when the verb is unavailable — see that script's own tests in
``test_launcher.py`` for the contract-equality and fallback coverage).

These tests exercise the verb IN-PROCESS (``self_learn_ui.cli.main``),
never as a subprocess — that boundary is exactly what
``test_launcher.py``'s contract test crosses (it drives the real
console-script binary), and this file's job is the verb's own contract:
what it prints, in which format, and that it never mutates the
filesystem as a side effect of merely being asked a path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from self_learn.serve import cache_dir_readonly
from self_learn_ui import cli
from self_learn_ui.middleware import resolve_token_path


def test_paths_default_output_is_key_value_lines(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["paths"])

    assert rc == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("cache_dir=")
    assert lines[1].startswith("token_path=")
    printed_cache_dir = lines[0].removeprefix("cache_dir=")
    printed_token_path = lines[1].removeprefix("token_path=")
    assert printed_cache_dir == str(cache_dir_readonly())
    assert printed_token_path == str(resolve_token_path())


def test_paths_json_flag_emits_json_object(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["paths", "--json"])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert set(payload.keys()) == {"cache_dir", "token_path"}
    assert payload["cache_dir"] == str(cache_dir_readonly())
    assert payload["token_path"] == str(resolve_token_path())
    # Positive control for the parse itself: a single JSON document on
    # one line, not the two "key=value" lines the default format prints
    # — proves this assertion would fail against the OTHER format.
    assert len(out.splitlines()) == 1


def test_paths_never_creates_cache_directory() -> None:
    """Pinned contract: the verb never creates a directory or file (D8
    build brief). Precondition, measured during the build: this only
    holds when $XDG_RUNTIME_DIR is set (conftest's autouse
    ``_redirect_env_defaults`` sets it for every UI test, matching the
    normal desktop case) — resolve_token_path()'s OWN
    XDG_RUNTIME_DIR-unset fallback calls self_learn.worker.cache_dir()
    (mkdir + migration side effects), not the read-only variant, which
    is pre-existing behaviour in middleware.py outside this verb's
    surface. See the D8 build report for the measured XDG_RUNTIME_DIR-
    unset counter-case; this test intentionally exercises only the
    scenario where the pinned "never creates" claim is actually true.

    Mutation check performed during the build (not automated here):
    swapping `cache_dir_readonly` for `self_learn.worker.cache_dir` in
    `cli.py`'s `_paths` turns this test red (the swapped call mkdirs the
    cache root); reverted after confirming.
    """
    assert "XDG_RUNTIME_DIR" in os.environ

    rc = cli.main(["paths", "--json"])

    assert rc == 0
    cache_home = Path(os.environ["XDG_CACHE_HOME"])
    assert not (cache_home / "self-learn").exists()


def test_paths_exit_code_zero_even_with_extra_json_flag_variants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # --json before/without other args — argparse store_true, no
    # ordering sensitivity; guards against a future regression that
    # makes --json positional-order-dependent.
    assert cli.main(["paths", "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["paths"]) == 0
