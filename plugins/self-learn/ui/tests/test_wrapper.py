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

MAJOR-1 (round 1) — every subprocess test's PATH was made HERMETIC
(built by `_hermetic_bin`). The original version hardcoded
`PATH=/usr/local/bin:/usr/bin:/bin` and assumed no real `uv` lived
there — true on the host this was built on, false on any host that
packages `uv` in one of those directories.

MAJOR-2 / M5 — the static assertions below use `_has_exact_token`
instead of a naive `in` substring check. The gate's M5 mutation renamed
`uv` -> `uvx` throughout the wrapper and every static test that used
plain `"... uv" in content` stayed GREEN, because `"...uv"` is a
substring of `"...uvx"` (the mutated name). `_has_exact_token` requires
the character right after the token to be a non-identifier character
(or end of string), so an extended name like `uvx` cannot satisfy a
check meant to prove the token `uv` is really there.

Gate r2 fold (2026-08-29): three further findings, all closed here.

MAJOR-1 (round 2 — round 1's fix was incomplete) — `_hermetic_bin`
hermeticizes PATH, but the wrapper's fallback candidates
($HOME/.local/bin/uv, /usr/local/bin/uv, /usr/bin/uv) are checked by
ABSOLUTE path regardless of PATH — that is their whole purpose, so a
hermetic PATH proves nothing about them. The gate proved this with a
mount namespace planting a real uv at /usr/local/bin/uv: the wrapper
found and exec'd it, bypassing every PATH-only test double (control
CLI 5/5, UI 12/12 green; treatment CLI 2 failed, UI 1 failed). Fixed by
DECOMPOSITION, not a test-only hook: the wrapper's `_resolve_uv_bin`
function takes the candidate list as ARGUMENTS, so `_call_resolve_uv_bin`
below sources the wrapper (loading it as a library — the wrapper's own
BASH_SOURCE[0]-vs-$0 guard skips the resolve-and-exec sequence when
sourced, a plain general bash idiom, not a test-only branch) and calls
the function directly with temp-path candidates standing in for the
real system paths.

MAJOR-3 — `test_wrapper_falls_back_to_well_known_absolute_uv_locations`
did not test the fallback's ROLE. Deleting /usr/local/bin/uv and
/usr/bin/uv from both wrappers' `_resolve_uv_bin` invocations left
17/17 tests green, because `_has_exact_token` only proved the string
exists somewhere in the file — the diagnostic message mentioning those
paths was enough. The test now extracts the exact `_resolve_uv_bin`
invocation line and checks the paths appear THERE, as arguments.

Minor — `_hermetic_bin` only provided `bash`, so `dirname`/`readlink`
(both needed by the wrapper's own last line) silently failed inside
every subprocess test's environment (two "command not found" lines,
`--project /../ui`) while the tests passed anyway, because none of them
checked stderr. Now provides `dirname` and `readlink` too, and every
call site asserts the directory holds exactly those three names — the
docstring's "each caller makes the assertion" claim was false for 1 of
this file's 3 call sites in round 1; true now, not merely re-asserted.

Minor — `_uv_is_valid` (in the wrapper itself) now also requires `-r`
(readable): `-f`+`-x` alone still admits a mode-0111 (execute-only, no
read bit) file — `exec`ing one produces bash's own "Permission denied"
(rc=126), not this script's diagnostic, since reading a shebang line
needs read permission too."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

WRAPPER = (
    Path(__file__).resolve().parents[2] / "scripts" / "self-learn-ui"
)

_BASH = shutil.which("bash")


def _has_exact_token(content: str, token: str) -> bool:
    """True iff `token` occurs in `content` and is not immediately
    followed by another identifier character — so a check for `uv`
    cannot be satisfied by `uvx`, only by `uv` itself (followed by
    whitespace, a quote, a slash, end of string, ...)."""
    return re.search(re.escape(token) + r"(?![A-Za-z0-9_])", content) is not None


def _hermetic_bin(tmp_path: Path, name: str = "hermetic-bin") -> Path:
    """A directory containing ONLY symlinks to `bash`, `dirname`, and
    `readlink` -- no other file, `uv` included, real or stub. These
    three are the only external binaries the wrapper's own EXECUTION
    needs (bash for the shebang; dirname/readlink for its last line's
    `readlink -f "$0"` / `dirname` resolution). Used as the sole PATH
    entry so `command -v uv` is GUARANTEED to find nothing via PATH on
    any host, packaged `uv` or not -- proven, not assumed, by the
    directory-contents assertion EVERY caller in this file makes."""
    real_bash = shutil.which("bash")
    real_dirname = shutil.which("dirname")
    real_readlink = shutil.which("readlink")
    assert real_bash and real_dirname and real_readlink, (
        "bash, dirname, and readlink must all be resolvable to build a hermetic PATH"
    )
    d = tmp_path / name
    d.mkdir()
    (d / "bash").symlink_to(real_bash)
    (d / "dirname").symlink_to(real_dirname)
    (d / "readlink").symlink_to(real_readlink)
    return d


def _write_stub_uv(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/usr/bin/env bash\necho "{marker}: $*"\n', encoding="utf-8")
    path.chmod(0o755)


def _call_resolve_uv_bin(*candidates: str) -> subprocess.CompletedProcess:
    """Gate r2 MAJOR-1: `source` the wrapper (defines `_resolve_uv_bin`/
    `_uv_is_valid` as library functions -- the wrapper's own guard skips
    the resolve-and-exec sequence when BASH_SOURCE[0] != $0, i.e. when
    sourced rather than executed) and call `_resolve_uv_bin` directly
    with test-controlled candidates, under `PATH=""` so `command -v uv`
    is guaranteed to find nothing via PATH -- proving whatever the
    candidate list finds, it finds by ABSOLUTE path, independent of
    PATH, exactly the property production relies on for
    /usr/local/bin/uv and /usr/bin/uv. `bash` is invoked by its own
    resolved absolute path (not the bare name) so launching this
    subprocess never itself depends on PATH."""
    assert _BASH, "bash must be resolvable to run this helper"
    script = 'source "$1"; shift; _resolve_uv_bin "$@"'
    return subprocess.run(
        [_BASH, "-c", script, "_", str(WRAPPER), *candidates],
        env={"PATH": ""},
        capture_output=True,
        text=True,
        timeout=30,
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
    """Gate r2 MAJOR-3: deleting /usr/local/bin/uv and /usr/bin/uv from
    BOTH wrappers' `_resolve_uv_bin` invocations left 17/17 tests green
    under the round-1 `_has_exact_token` check, because it only proved
    the STRING exists somewhere in the file — the diagnostic message
    alone was enough, without these paths ever playing the ROLE of an
    actual fallback candidate. This test extracts the exact
    `_resolve_uv_bin` invocation line and asserts each path appears
    THERE, as an argument, not merely somewhere in the file."""
    content = WRAPPER.read_text(encoding="utf-8")
    invocation_line = next(
        line for line in content.splitlines() if "_resolve_uv_bin " in line
    )
    assert _has_exact_token(invocation_line, "$HOME/.local/bin/uv")
    assert _has_exact_token(invocation_line, "/usr/local/bin/uv")
    assert _has_exact_token(invocation_line, "/usr/bin/uv")


def test_wrapper_fails_loudly_when_uv_is_nowhere() -> None:
    """Never a silent bare 127 — a one-line diagnostic naming what was
    looked for, then a non-zero exit."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert _has_exact_token(content, "uv not found")
    assert "exit 127" in content


def test_wrapper_requires_a_regular_executable_file_not_just_dash_x() -> None:
    """Gate r1 MINOR-2/MINOR-5, extended at gate r2: `-f`+`-x` alone
    still admits a mode-0111 (execute-only, no read bit) file —
    `exec`ing one produces bash's own opaque "Permission denied"
    (rc=126, measured), not this script's diagnostic, because reading a
    script's shebang line needs read permission too. Every candidate —
    including the `command -v` hit — must pass `-f` (regular file) AND
    `-r` (readable) AND `-x` (executable) before being trusted."""
    content = WRAPPER.read_text(encoding="utf-8")
    assert "_uv_is_valid" in content
    assert '[[ -n "$1" && -f "$1" && -r "$1" && -x "$1" ]]' in content


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
    # Positive proof the PATH this test hands the wrapper cannot contain
    # a real (or stray stub) `uv` anywhere, AND that the wrapper's own
    # execution has everything it needs (gate r2 Minor: dirname/readlink
    # were missing in round 1, silently breaking this same test).
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

    env = {"HOME": str(fake_home), "PATH": str(hermetic_bin)}
    result = subprocess.run(
        [str(WRAPPER), "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
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
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

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

    # The PATH-visible directory carries bash/dirname/readlink (so the
    # shebang AND the wrapper's own execution resolve) plus the
    # PATH-visible uv stub — the one and only PATH entry, so this is
    # hermetic by construction too (MAJOR-1's concern): no other
    # directory, no real uv, can be found via PATH.
    path_bin = _hermetic_bin(tmp_path, name="path-visible-bin")
    assert {p.name for p in path_bin.iterdir()} == {"bash", "dirname", "readlink"}
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
    assert result.stderr == ""
    assert result.stdout.startswith("PATH_UV_INVOKED: run --project ")
    assert "FALLBACK_UV_INVOKED" not in result.stdout


def test_resolve_uv_bin_finds_a_candidate_regardless_of_path(tmp_path):
    """Gate r2 MAJOR-1: round 1's `_hermetic_bin` only hermeticized
    PATH, but the wrapper's fallback candidates ($HOME/.local/bin/uv,
    /usr/local/bin/uv, /usr/bin/uv) are checked by ABSOLUTE path
    regardless of PATH -- a hermetic PATH proves nothing about them.
    This test proves the actual property: `_resolve_uv_bin` finds a
    candidate under `PATH=""` (nothing findable via PATH at all,
    enforced by `_call_resolve_uv_bin`), simulating a real system uv at
    a fixed location the way /usr/local/bin/uv would behave in
    production, without needing root or a mount namespace."""
    stub = tmp_path / "sim-system-location" / "uv"
    _write_stub_uv(stub, "SIM_SYSTEM_UV_INVOKED")

    result = _call_resolve_uv_bin("/no/such/path1", str(stub), "/no/such/path3")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(stub)


def test_resolve_uv_bin_returns_failure_when_no_candidate_is_valid(tmp_path):
    """The failure leg of the same decomposed function: no candidate
    valid -> empty stdout, non-zero return -- exactly what the
    resolve-and-exec sequence checks to decide whether to print the
    loud diagnostic."""
    result = _call_resolve_uv_bin("/no/such/path1", "/no/such/path2")
    assert result.returncode == 1
    assert result.stdout == ""


def test_resolve_uv_bin_rejects_a_mode_0111_candidate(tmp_path):
    """Gate r2 Minor (continued from gate r1 MINOR-2/MINOR-5): `-f`+`-x`
    alone still admits a mode-0111 (execute-only, no read bit) file --
    `exec`ing one produces bash's own opaque "Permission denied"
    (rc=126, measured directly against a throwaway mode-0111 script),
    not this script's diagnostic, because reading a shebang line needs
    read permission too. `_uv_is_valid`'s `-r` check must reject it and
    let resolution fall through to the next candidate (or failure)."""
    candidate = tmp_path / "mode0111" / "uv"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("#!/usr/bin/env bash\necho should-never-run\n", encoding="utf-8")
    candidate.chmod(0o111)

    result = _call_resolve_uv_bin(str(candidate))
    assert result.returncode == 1
    assert result.stdout == ""
