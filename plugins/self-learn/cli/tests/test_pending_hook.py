"""O-5 pending-hook rendering over the additive fast-status field."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


HOOK = Path(__file__).resolve().parents[2] / "hooks" / "self-learn-pending.sh"
_MODE = stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH


def _run_hook(tmp_path: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("bash", "env", "jq", "timeout", "cat"):
        resolved = shutil.which(name)
        assert resolved is not None, f"required harness binary missing: {name}"
        (bindir / name).symlink_to(resolved)
    fake = bindir / "self-learn"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "cat <<'STATUS_JSON'\n"
        f"{json.dumps(payload)}\n"
        "STATUS_JSON\n",
        encoding="utf-8",
    )
    fake.chmod(_MODE)
    env = {
        "PATH": str(bindir),
        "HOME": str(tmp_path / "home"),
        "SELF_LEARN_HOME": str(tmp_path / "ledger"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "SELF_LEARN_CLAUDE_DIR": str(tmp_path / "claude"),
    }
    return subprocess.run(
        [str(HOOK)], env=env, text=True, capture_output=True, timeout=10
    )


def _base_payload() -> dict[str, object]:
    return {
        "home_state": "ok",
        "total_pending": 0,
        "oldest_days": 0,
        "staleness_alarm": False,
        "escalate": False,
        "unanalyzed_total": 0,
        "miner_stale": False,
        "intents_probe": "clear",
        "intents_stopped_count": 0,
    }


def test_hook_prints_exact_question_line_when_field_is_present(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["overseer_open_questions"] = 1
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "self-learn: the overseer has 1 interpretation questions — "
        "/self-learn:overseer\n"
    )


def test_hook_prints_no_question_line_when_field_is_absent(tmp_path: Path) -> None:
    result = _run_hook(tmp_path, _base_payload())
    assert result.returncode == 0, result.stderr
    assert "overseer has" not in result.stdout


def test_hook_is_executable() -> None:
    assert HOOK.is_file()
    assert os.access(HOOK, os.X_OK)
