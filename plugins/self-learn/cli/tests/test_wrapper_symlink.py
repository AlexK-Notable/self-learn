"""CLI-through-symlink test (T1).

install.sh deploys plugins/self-learn/scripts/self-learn as a ~/bin symlink;
the wrapper must locate the uv project via `readlink -f` (resolving the real
script path), not `dirname $0` (which would resolve beside the symlink).
This test exercises exactly that path: symlink in a tmpdir -> wrapper ->
`uv run --project .../cli self-learn status --json` against an empty sandbox.
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
