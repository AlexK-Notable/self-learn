"""CLI-through-symlink test (T1).

install.sh deploys plugins/self-learn/scripts/self-learn as a ~/bin symlink;
the wrapper must locate the uv project via `readlink -f` (resolving the real
script path), not `dirname $0` (which would resolve beside the symlink).
This test exercises exactly that path: symlink in a tmpdir -> wrapper ->
`uv run --project .../cli self-learn status --json` against an empty sandbox.

U-uvpath (2026-08-29) adds the functions below it: self-learn-host.service
crash-looped six times on 2026-08-28 22:17-22:18 with `exec: uv: not found`
(exit 127/n/a) because the wrapper's old last line, `exec uv run ...`,
resolved `uv` off ambient PATH alone, and the systemd user manager's PATH
does not reliably include ~/.local/bin (uv's pipx install dir on this host).
These tests drive the wrapper directly (not through a symlink -- that is
T1's own concern above) under a controlled, minimal environment.

Gate r1 fold (2026-08-29, MAJOR-1 round 1): every subprocess PATH built
here is HERMETIC -- it names ONLY a directory this test itself populated.

Gate r2 fold (2026-08-29): two further findings, both closed here.

MAJOR-1 (round 1's fix was incomplete): `_hermetic_bin` hermeticizes
PATH, but the wrapper's fallback candidates ($HOME/.local/bin/uv,
/usr/local/bin/uv, /usr/bin/uv) are checked by ABSOLUTE path regardless
of PATH -- that is their whole purpose. A hermetic PATH proves nothing
about them; the gate proved this with a mount namespace planting a real
uv at /usr/local/bin/uv and watching the wrapper find and exec it,
bypassing every PATH-only test double. Fixed by DECOMPOSITION, not a
test-only hook: the wrapper's `_resolve_uv_bin` function takes the
candidate list as ARGUMENTS, so `_call_resolve_uv_bin` below sources the
wrapper (loading it as a library -- the wrapper's own BASH_SOURCE[0]-vs-$0
guard skips the resolve-and-exec sequence when sourced, a plain general
bash idiom, not a test-only branch) and calls the function directly with
temp-path candidates standing in for the real system paths.

Minor (round 1): `_hermetic_bin` only provided `bash`, so `dirname`/
`readlink` -- both of which the wrapper's own last line needs --
silently failed inside every subprocess test's environment (two
"command not found" lines, `--project /../cli`) while the tests passed
anyway, because none of them checked stderr. Now provides `dirname` and
`readlink` too, and every call site asserts the directory holds exactly
those three names -- proof, not assumption, and no longer overclaimed
in this docstring (round 1's version claimed "each caller" already made
the assertion; it was false for 2 of this file's 4 call sites)."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "self-learn"

_BASH = shutil.which("bash")


def _has_exact_token(content: str, token: str) -> bool:
    """True iff `token` occurs in `content` and is not immediately
    followed by another identifier character -- so a check for a
    literal path cannot be satisfied by an extended/renamed variant of
    it (gate r1 M5's `uv`->`uvx` class)."""
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


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_wrapper_runs_through_symlink(tmp_path):
    assert WRAPPER.is_file() and os.access(WRAPPER, os.X_OK)

    link = tmp_path / "bin" / "self-learn"
    link.parent.mkdir()
    link.symlink_to(WRAPPER)

    # An INITIALIZED, record-less home (git repo + hosts.yaml — what a
    # fresh clone is): a bare dir is a BROKEN home and now exits non-zero,
    # loudly (audit 2026-07-16 BLOCKER 11). This test is about the
    # WRAPPER's path resolution, so it hands the CLI a home it can answer.
    sandbox_home = tmp_path / "empty-repo"
    sandbox_home.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(sandbox_home)], check=True)
    (sandbox_home / "hosts.yaml").write_text(
        "skills_root: null\nprojects: []\n", encoding="utf-8"
    )

    env = dict(os.environ, SELF_LEARN_HOME=str(sandbox_home))
    result = subprocess.run(
        [str(link), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "buckets": [],
        "total_pending": 0,
        "total_unreadable": 0,
        "open_followups": 0,
        "worker_last_run": None,
        # T19 blocks (zero-state: empty mix, null medians — never fake 0s)
        "supply_mix": {},
        "metrics": {
            "time_to_triage_median_days": None,
            "pending_total": 0,
            "pending_over_30d_pct": None,
            "routed_and_corrected": 0,
        },
    }


def test_wrapper_falls_back_to_home_local_bin_uv_when_path_lacks_it(tmp_path):
    """The minimal-PATH positive control (measured 2026-08-29):
    `env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin bash -c
    'command -v uv'` finds nothing on THIS host, because uv lives only
    at ~/.local/bin/uv (a pipx symlink) -- exactly the PATH shape a
    systemd user-manager unit that loses the boot-order race sees. This
    test does not rely on that host fact holding everywhere, though:
    PATH here is `_hermetic_bin`'s single, provably uv-free directory,
    so the fallback below is the ONLY way this can succeed on ANY host.
    HOME's only uv is a stub at $HOME/.local/bin/uv; the wrapper must
    still find and exec it."""
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
        [str(WRAPPER), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("STUB_UV_INVOKED: run --project ")
    assert "self-learn status --json" in result.stdout


def test_wrapper_fails_loudly_with_no_bare_127_when_uv_is_nowhere(tmp_path):
    """Not-found path: PATH is `_hermetic_bin`'s single uv-free
    directory, and $HOME/.local/bin/uv (the only fallback candidate
    this sandboxed HOME could satisfy) doesn't exist either. Before the
    fix this was the measured failure itself:
    `/…/self-learn: line 6: exec: uv: not found` with no diagnostic
    naming what was looked for. The wrapper must now name every
    location it checked and exit non-zero."""
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

    env = {"HOME": str(fake_home), "PATH": str(hermetic_bin)}
    result = subprocess.run(
        [str(WRAPPER), "status", "--json"],
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


def test_wrapper_prefers_a_path_visible_uv_over_the_fallback_location(tmp_path):
    """Gate r1 MAJOR-2: the wrapper's own comment promises "a normal
    interactive invocation, or any user-chosen uv earlier on PATH, is
    unchanged" -- nothing enforced that claim until this test. Plant
    TWO distinguishable stub `uv`s: one PATH-visible (must win), one at
    the fallback location $HOME/.local/bin/uv (must lose). If the
    wrapper ever resolved the fallback first, or resolved either
    non-deterministically, this fails."""
    fake_home = tmp_path / "home"
    _write_stub_uv(fake_home / ".local" / "bin" / "uv", "FALLBACK_UV_INVOKED")

    # The PATH-visible directory carries bash/dirname/readlink (so the
    # shebang AND the wrapper's own execution resolve) plus the
    # PATH-visible uv stub -- the one and only PATH entry, so this is
    # hermetic by construction too (MAJOR-1's concern): no other
    # directory, no real uv, can be found via PATH.
    path_bin = _hermetic_bin(tmp_path, name="path-visible-bin")
    assert {p.name for p in path_bin.iterdir()} == {"bash", "dirname", "readlink"}
    _write_stub_uv(path_bin / "uv", "PATH_UV_INVOKED")

    env = {"HOME": str(fake_home), "PATH": str(path_bin)}
    result = subprocess.run(
        [str(WRAPPER), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("PATH_UV_INVOKED: run --project ")
    assert "FALLBACK_UV_INVOKED" not in result.stdout


def test_wrapper_rejects_a_directory_named_uv_at_the_fallback_location(tmp_path):
    """Gate r1 MINOR-2/MINOR-5 (behavioral counterpart to the static
    check in ui/tests/test_wrapper.py -- the same `_uv_is_valid` fix
    covers this wrapper too): a DIRECTORY named `uv` sitting exactly
    where the fallback would look must be treated as invalid, not
    exec'd. Before the fix, bare `[[ -x ]]` accepts a directory (it is
    traversable) and `exec`ing it produces bash's own opaque "Is a
    directory" (rc=126) -- measured against the pre-tightening wrapper
    in the same scratch sandbox this test uses. The fixed wrapper must
    fall through to the loud not-found diagnostic instead."""
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin" / "uv").mkdir(parents=True)

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash", "dirname", "readlink"}

    env = {"HOME": str(fake_home), "PATH": str(hermetic_bin)}
    result = subprocess.run(
        [str(WRAPPER), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "uv not found" in result.stderr
    assert "Is a directory" not in result.stderr


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


def test_wrapper_falls_back_to_well_known_absolute_uv_locations() -> None:
    """Gate r2 MAJOR-3: deleting /usr/local/bin/uv and /usr/bin/uv from
    BOTH wrappers' `_resolve_uv_bin` invocations left 17/17 tests green
    under the round-1 `_has_exact_token` check, because it only proved
    the STRING exists somewhere in the file -- the diagnostic message
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
