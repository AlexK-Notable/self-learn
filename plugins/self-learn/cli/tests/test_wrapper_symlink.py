"""CLI-through-symlink test (T1).

install.sh deploys plugins/self-learn/scripts/self-learn as a ~/bin symlink;
the wrapper must locate the uv project via `readlink -f` (resolving the real
script path), not `dirname $0` (which would resolve beside the symlink).
This test exercises exactly that path: symlink in a tmpdir -> wrapper ->
`uv run --project .../cli self-learn status --json` against an empty sandbox.

U-uvpath (2026-08-29) adds the two functions below it: self-learn-host.service
crash-looped six times on 2026-08-28 22:17-22:18 with `exec: uv: not found`
(exit 127/n/a) because the wrapper's old last line, `exec uv run ...`,
resolved `uv` off ambient PATH alone, and the systemd user manager's PATH
does not reliably include ~/.local/bin (uv's pipx install dir on this host).
These two tests drive the wrapper directly (not through a symlink -- that is
T1's own concern above) under a controlled, minimal environment: one proves
the ~/.local/bin/uv fallback actually fires when PATH lacks it, the other
proves the not-found path fails loudly rather than reproducing the bare,
unexplained 127. Both use a STUB `uv` (or no `uv` at all) rather than a real
one, so — like ui/tests/test_wrapper.py's docstring states for its own
suite — this never depends on network access for `uv run`'s own resolution.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "self-learn"


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
    'command -v uv'` finds nothing on this host, because uv lives only
    at ~/.local/bin/uv (a pipx symlink) -- exactly the PATH shape a
    systemd user-manager unit that loses the boot-order race sees. Give
    the wrapper that same PATH and a HOME whose ONLY uv is a stub at
    $HOME/.local/bin/uv; the wrapper must still find and exec it."""
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
    """Not-found path: PATH has no uv, and $HOME/.local/bin/uv (the
    only fallback candidate this sandboxed HOME could satisfy) doesn't
    exist either. Before the fix this was the measured failure itself:
    `/…/self-learn: line 6: exec: uv: not found` with no diagnostic
    naming what was looked for. The wrapper must now name every
    location it checked and exit non-zero."""
    fake_home = tmp_path / "empty-home"
    fake_home.mkdir()

    env = {"HOME": str(fake_home), "PATH": "/usr/local/bin:/usr/bin:/bin"}
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
