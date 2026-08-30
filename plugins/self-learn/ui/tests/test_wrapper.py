"""Wrapper script tests (10 §1 Code layout row, P3-1; task U1 test
bullet 4). Mostly static checks — no REAL `uv run` invocation anywhere
in this suite, so it never depends on network access for `uv run`'s own
resolution (the real invocation is exercised manually per the DoD, not
in CI). U-uvpath (2026-08-29) adds subprocess-driven tests for the uv
*resolution* logic itself (below the static checks) — those exec the
wrapper against a STUB `uv` (or none at all) on a controlled PATH/HOME,
never a real `uv run`, so the constraint above still holds.

Gate r1 fold (2026-08-29): two weaknesses in the first version of these
additions, both closed here.

MAJOR-1 — every subprocess test's PATH is now HERMETIC (built by
`_hermetic_bin`: one directory, containing only a `bash` symlink this
test itself planted, nothing else). The original version hardcoded
`PATH=/usr/local/bin:/usr/bin:/bin` and assumed no real `uv` lived
there — true on the host this was built on, false on any host that
packages `uv` in one of those directories (Arch's `community/uv`,
Homebrew, a CI image); two of the four subprocess tests would have
failed there, and one would have silently exec'd a REAL `uv run`,
exactly what this docstring promises never happens.

MAJOR-2 / M5 — the static assertions below now use `_has_exact_token`
instead of a naive `in` substring check. The gate's M5 mutation renamed
`uv` -> `uvx` throughout the wrapper and every static test that used
plain `"... uv" in content` stayed GREEN, because `"...uv"` is a
substring of `"...uvx"` (the mutated name). `_has_exact_token` requires
the character right after the token to be a non-identifier character
(or end of string), so an extended name like `uvx` cannot satisfy a
check meant to prove the token `uv` is really there."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

WRAPPER = (
    Path(__file__).resolve().parents[2] / "scripts" / "self-learn-ui"
)


def _has_exact_token(content: str, token: str) -> bool:
    """True iff `token` occurs in `content` and is not immediately
    followed by another identifier character — so a check for `uv`
    cannot be satisfied by `uvx`, only by `uv` itself (followed by
    whitespace, a quote, a slash, end of string, ...)."""
    return re.search(re.escape(token) + r"(?![A-Za-z0-9_])", content) is not None


def _hermetic_bin(tmp_path: Path, name: str = "hermetic-bin") -> Path:
    """A directory containing ONLY a symlink to the real `bash` -- no
    other file, `uv` included, real or stub. Used as the sole PATH
    entry so `env bash` (the wrapper's shebang) still resolves, while
    `command -v uv` is GUARANTEED to find nothing via PATH on any host,
    packaged `uv` or not -- proven, not assumed, by the directory-
    contents assertion each caller makes after building on top of it."""
    real_bash = shutil.which("bash")
    assert real_bash, "bash must be resolvable to build a hermetic PATH"
    d = tmp_path / name
    d.mkdir()
    (d / "bash").symlink_to(real_bash)
    return d


def _write_stub_uv(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/usr/bin/env bash\necho "{marker}: $*"\n', encoding="utf-8")
    path.chmod(0o755)


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
    on PATH, must be unchanged by the fallback below. Anchored with
    `_has_exact_token` (gate r1 M5): a naive `"command -v uv" in
    content` substring check stays green even if the wrapper resolved
    `command -v uvx` instead — `uv` is a prefix of `uvx`. See
    `test_wrapper_prefers_a_path_visible_uv_over_the_fallback_location`
    below for the behavioral half of this same promise (PATH actually
    wins over the fallback, not just that both code shapes are present)."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert _has_exact_token(content, "command -v uv")


def test_wrapper_falls_back_to_well_known_absolute_uv_locations() -> None:
    """U-uvpath (2026-08-29): self-learn-host.service crash-looped six
    times on 2026-08-28 22:17-22:18 with `exec: uv: not found` (exit
    127/n/a) because a bare `exec uv` depends on ambient PATH, and the
    systemd user manager's PATH does not reliably include
    $HOME/.local/bin (uv's pipx install dir on this host). The wrapper
    must fall back to well-known absolute locations rather than give up
    the moment PATH comes up empty. Anchored with `_has_exact_token`
    (gate r1 M5): each of these three paths is itself a prefix of the
    corresponding `...uvx` path a uv->uvx rename would produce, so a
    naive substring check cannot tell the two apart."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert _has_exact_token(content, "$HOME/.local/bin/uv")
    assert _has_exact_token(content, "/usr/local/bin/uv")
    assert _has_exact_token(content, "/usr/bin/uv")


def test_wrapper_fails_loudly_when_uv_is_nowhere() -> None:
    """Never a silent bare 127 — a one-line diagnostic naming what was
    looked for, then a non-zero exit."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert _has_exact_token(content, "uv not found")
    assert "exit 127" in content


def test_wrapper_requires_a_regular_executable_file_not_just_dash_x() -> None:
    """Gate r1 MINOR-2/MINOR-5: `[[ -x ]]` alone accepts a DIRECTORY
    named `uv` (exec on it produces bash's own "Is a directory", not
    this script's diagnostic), and this bash's own `command -v` can
    hand back a path that isn't actually an executable regular file.
    Every candidate — including the `command -v` hit — must pass a
    combined `-f` (regular file, following a symlink to its target so
    uv's real pipx symlink shape still works) AND `-x` check before
    being trusted."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert "_uv_is_valid" in content
    assert '-f "$1" && -x "$1"' in content


def test_wrapper_falls_back_to_home_local_bin_uv_when_path_lacks_it(
    tmp_path,
) -> None:
    """Behavioral counterpart to the static checks above: drive the
    wrapper with a hermetic PATH (MAJOR-1 — provably uv-free on any
    host, not just this one) and a HOME whose only uv lives at
    $HOME/.local/bin/uv (a stub — never a real `uv run`, preserving
    this module's own no-network-dependency constraint). The wrapper
    must still find and exec it."""
    fake_home = tmp_path / "home"
    _write_stub_uv(fake_home / ".local" / "bin" / "uv", "STUB_UV_INVOKED")

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash"}

    env = {"HOME": str(fake_home), "PATH": str(hermetic_bin)}
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
    """Not-found path: PATH is `_hermetic_bin`'s single uv-free
    directory, and $HOME/.local/bin/uv (the only fallback candidate
    this sandboxed HOME could satisfy) doesn't exist either. Before the
    fix this was the measured failure itself: a bare `exec: uv: not
    found` with no diagnostic naming what was looked for. The wrapper
    must now name every location it checked and exit non-zero — on any
    host, not just one lacking a packaged uv in the old hardcoded PATH."""
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash"}

    env = {"HOME": str(fake_home), "PATH": str(hermetic_bin)}
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


def test_wrapper_prefers_a_path_visible_uv_over_the_fallback_location(
    tmp_path,
) -> None:
    """Gate r1 MAJOR-2: the wrapper's own comment promises "a normal
    interactive invocation, or any user-chosen uv earlier on PATH, is
    unchanged" -- nothing enforced that claim until this test. Plant
    TWO distinguishable stub `uv`s: one PATH-visible (must win), one at
    the fallback location $HOME/.local/bin/uv (must lose). If the
    wrapper ever resolved the fallback first, or resolved either
    non-deterministically, this fails. (Mutation-verified: reversing
    the wrapper's resolution order — fallback loop first, `command -v`
    last — turns this RED; see the builder handoff for the exact
    signature.)"""
    fake_home = tmp_path / "home"
    _write_stub_uv(fake_home / ".local" / "bin" / "uv", "FALLBACK_UV_INVOKED")

    # The PATH-visible directory carries BOTH bash (so the shebang
    # resolves) and the PATH-visible uv stub — the one and only PATH
    # entry, so this is hermetic by construction too (MAJOR-1's
    # concern): no other directory, no real uv, can be found via PATH.
    path_bin = _hermetic_bin(tmp_path, name="path-visible-bin")
    _write_stub_uv(path_bin / "uv", "PATH_UV_INVOKED")

    env = {"HOME": str(fake_home), "PATH": str(path_bin)}
    result = subprocess.run(
        [str(WRAPPER), "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("PATH_UV_INVOKED: run --project ")
    assert "FALLBACK_UV_INVOKED" not in result.stdout
