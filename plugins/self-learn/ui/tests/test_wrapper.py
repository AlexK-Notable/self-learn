"""Wrapper script tests (10 §1 Code layout row, P3-1; task U1 test
bullet 4). Static checks only — no subprocess invocation here, so this
suite never depends on network access for `uv run`'s own resolution
(the real invocation is exercised manually per the DoD, not in CI)."""

from __future__ import annotations

import os
from pathlib import Path

WRAPPER = (
    Path(__file__).resolve().parents[2] / "scripts" / "self-learn-ui"
)


def test_wrapper_exists() -> None:
    assert WRAPPER.is_file(), f"missing wrapper at {WRAPPER}"


def test_wrapper_is_executable() -> None:
    assert os.access(WRAPPER, os.X_OK), f"{WRAPPER} is not executable"


def test_wrapper_has_bash_shebang() -> None:
    first_line = WRAPPER.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env bash"


def test_wrapper_uses_readlink_f() -> None:
    """P3-1, load-bearing: install.sh deploys this file as a ~/bin
    symlink, so a bare $(dirname "$0") would resolve beside the symlink,
    not the repo. readlink -f is what makes it resolve correctly."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert "readlink -f" in content


def test_wrapper_execs_uv_run_against_the_ui_project() -> None:
    content = WRAPPER.read_text(encoding="utf-8")
    assert "exec uv run" in content
    assert "../ui" in content
    assert "self-learn-ui" in content
