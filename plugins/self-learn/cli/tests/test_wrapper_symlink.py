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
T1's own concern above) under a controlled, minimal environment. Gate r1
fold (2026-08-29, MAJOR-1): every PATH built here is HERMETIC -- it names
ONLY a directory this test itself populated, with `bash` as the sole
non-stub entry (needed so the wrapper's own `#!/usr/bin/env bash` shebang
resolves at all). The original version of these tests instead hardcoded
`PATH=/usr/local/bin:/usr/bin:/bin` and just assumed no real `uv` lived
there -- true on the host this was built on, false on any host that
packages `uv` in one of those directories (Arch's `community/uv`,
Homebrew, a CI image), where two of the four original tests would have
failed and one would have silently exec'd a REAL `uv run`, exactly the
network dependency ui/tests/test_wrapper.py's docstring promises this
suite never has. `_hermetic_bin` below is what makes every candidate
directory here provably uv-free regardless of host."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "self-learn"


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
    # a real (or stray stub) `uv` anywhere: the ONE directory on PATH
    # holds exactly the bash symlink this helper put there.
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash"}

    env = {"HOME": str(fake_home), "PATH": str(hermetic_bin)}
    result = subprocess.run(
        [str(WRAPPER), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("STUB_UV_INVOKED: run --project ")
    assert "self-learn status --json" in result.stdout


def test_wrapper_fails_loudly_with_no_bare_127_when_uv_is_nowhere(tmp_path):
    """Not-found path: PATH is `_hermetic_bin`'s single uv-free
    directory, and $HOME/.local/bin/uv (the only fallback candidate
    this sandboxed HOME could satisfy) doesn't exist either. Before the
    fix this was the measured failure itself:
    `/…/self-learn: line 6: exec: uv: not found` with no diagnostic
    naming what was looked for. The wrapper must now name every
    location it checked and exit non-zero -- on any host, not just one
    that happens to lack a packaged uv in the old hardcoded PATH."""
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()

    hermetic_bin = _hermetic_bin(tmp_path)
    assert {p.name for p in hermetic_bin.iterdir()} == {"bash"}

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

    # The PATH-visible directory carries BOTH bash (so the shebang
    # resolves) and the PATH-visible uv stub -- the one and only PATH
    # entry, so this is hermetic by construction too (MAJOR-1's
    # concern): no other directory, no real uv, can be found via PATH.
    path_bin = _hermetic_bin(tmp_path, name="path-visible-bin")
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
