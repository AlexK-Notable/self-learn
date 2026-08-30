"""Wrapper script tests (10 §1 Code layout row, P3-1; task U1 test
bullet 4). Mostly static checks — no REAL `uv run` invocation anywhere
in this suite, so it never depends on network access for `uv run`'s own
resolution (the real invocation is exercised manually per the DoD, not
in CI). U-uvpath (2026-08-29) adds subprocess-driven tests for the uv
*resolution* logic itself (below the static checks) — those exec the
wrapper against a STUB `uv` (or none at all) on a controlled PATH/HOME,
never a real `uv run`, so the constraint above still holds."""

from __future__ import annotations

import os
import subprocess
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
    """U-uvpath (2026-08-29): the wrapper no longer execs a bare `uv` —
    it resolves an absolute $UV_BIN first (see the tests below) and
    execs THAT. The literal command shape changed; what must still hold
    is that whatever is resolved gets `run --project .../ui
    self-learn-ui` handed to it."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert 'exec "$UV_BIN" run --project' in content
    assert "../ui" in content
    assert "self-learn-ui" in content


def test_wrapper_resolves_uv_via_command_dash_v_first() -> None:
    """A normal interactive invocation, or any user-chosen `uv` earlier
    on PATH, must be unchanged by the fallback below."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert "command -v uv" in content


def test_wrapper_falls_back_to_well_known_absolute_uv_locations() -> None:
    """U-uvpath (2026-08-29): self-learn-host.service crash-looped six
    times on 2026-08-28 22:17-22:18 with `exec: uv: not found` (exit
    127/n/a) because a bare `exec uv` depends on ambient PATH, and the
    systemd user manager's PATH does not reliably include
    $HOME/.local/bin (uv's pipx install dir on this host). The wrapper
    must fall back to well-known absolute locations rather than give up
    the moment PATH comes up empty."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert "$HOME/.local/bin/uv" in content
    assert "/usr/local/bin/uv" in content
    assert "/usr/bin/uv" in content


def test_wrapper_fails_loudly_when_uv_is_nowhere() -> None:
    """Never a silent bare 127 — a one-line diagnostic naming what was
    looked for, then a non-zero exit."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert "uv not found" in content
    assert "exit 127" in content


def test_wrapper_falls_back_to_home_local_bin_uv_when_path_lacks_it(
    tmp_path,
) -> None:
    """Behavioral counterpart to the static checks above: drive the
    wrapper with a PATH that has no uv on it at all and a HOME whose
    only uv lives at $HOME/.local/bin/uv (a stub — never a real `uv
    run`, preserving this module's own no-network-dependency
    constraint). The wrapper must still find and exec it."""
    fake_home = tmp_path / "home"
    stub_bin = fake_home / ".local" / "bin"
    stub_bin.mkdir(parents=True)
    stub_uv = stub_bin / "uv"
    stub_uv.write_text(
        '#!/usr/bin/env bash\necho "STUB_UV_INVOKED: $*"\n', encoding="utf-8"
    )
    stub_uv.chmod(0o755)

    env = {"HOME": str(fake_home), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    result = subprocess.run(
        [str(WRAPPER), "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("STUB_UV_INVOKED: run --project ")
    assert "self-learn-ui --help" in result.stdout


def test_wrapper_fails_loudly_with_no_bare_127_when_uv_is_nowhere(
    tmp_path,
) -> None:
    """Not-found path: PATH has no uv, and $HOME/.local/bin/uv (the
    only fallback candidate this sandboxed HOME could satisfy) doesn't
    exist either. Before the fix this was the measured failure itself:
    a bare `exec: uv: not found` with no diagnostic naming what was
    looked for. The wrapper must now name every location it checked and
    exit non-zero."""
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()

    env = {"HOME": str(fake_home), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    result = subprocess.run(
        [str(WRAPPER), "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "uv not found" in result.stderr
    assert "$HOME/.local/bin/uv" in result.stderr
    assert "/usr/local/bin/uv" in result.stderr
    assert "/usr/bin/uv" in result.stderr
