"""The SessionStart hook's rendering over `status --fast` (08 §7.1; attention
round, design r2 §3.9: only what the session must act on)."""

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


NOTICE_HEADER = (
    "self-learn notices for this project — yours to carry out in this session "
    "(no sudo needed): do it, then `self-learn notice done <id>`"
)


def _loud_payload() -> dict[str, object]:
    """Every field the hook used to print a line for, set to print: open
    overseer questions, a pending backlog over threshold, a worker staleness
    alarm, a stale miner, and a stale, held steward with stranded lessons."""
    payload = _base_payload()
    payload.update(
        overseer_open_questions=3,
        total_pending=19,
        oldest_days=55,
        escalate=True,
        staleness_alarm=True,
        unanalyzed_total=4,
        miner_stale=True,
        steward_enabled=True,
        steward_stale=True,
        steward_stale_hours=72,
        steward_hold="OAuth session expired",
        steward_hold_fix="run `claude`, then `/login`",
        stranded_count=2,
    )
    return payload


def test_hook_prints_only_what_the_session_must_act_on(tmp_path: Path) -> None:
    """Attention round test 3 (design r2 §3.9, §5.7): with every old line's
    field set, the hook prints a project notice under the M9 header and the
    STOPPED intent (the controls, asserted first) and nothing else: no
    overseer questions, pending, backlog, worker, miner or steward line, and
    nothing about approved inbox work."""
    payload = _loud_payload()
    payload.update(
        intents_stopped_count=1,
        intents_stopped=["int-0001"],
        project_notices=[{"id": "ntc-1", "line": "self-learn: commit CLAUDE.md here"}],
    )
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    # controls: the kept lines print
    assert any("STOPPED transaction intent" in line and "int-0001" in line for line in lines)
    assert lines[-2:] == [NOTICE_HEADER, "self-learn: commit CLAUDE.md here"]
    # and nothing else does
    assert len(lines) == 3, result.stdout
    for gone in ("overseer", "waiting", "pending", "backlog", "review", "await analysis",
                 "miner", "steward", "held", "never selects", "approved", "inbox"):
        assert gone not in result.stdout.lower().replace("self-learn notice done", ""), gone


def test_hook_is_silent_on_a_healthy_ledger_whatever_the_queue(tmp_path: Path) -> None:
    """The same loud payload with no notice, no STOPPED intent and nothing
    unreadable prints nothing at all. Positive control first: adding an
    unreadable count to the very same payload does print."""
    (tmp_path / "control").mkdir()
    (tmp_path / "quiet").mkdir()
    control = _run_hook(tmp_path / "control", {**_loud_payload(), "total_unreadable": 1})
    assert "1 unreadable record(s)" in control.stdout, control.stdout
    result = _run_hook(tmp_path / "quiet", _loud_payload())
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_notices_print_under_one_header_with_the_more_line(tmp_path: Path) -> None:
    """M9: one header before the notices, never one per notice, and the
    count of the rest after them."""
    payload = _base_payload()
    payload.update(
        project_notices=[{"line": "self-learn: first"}, {"line": "self-learn: second"}],
        project_notices_more=2,
    )
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        f"{NOTICE_HEADER}\n"
        "self-learn: first\n"
        "self-learn: second\n"
        "self-learn: 2 more notice(s) for this project — self-learn notice list\n"
    )


def test_hook_is_executable() -> None:
    assert HOOK.is_file()
    assert os.access(HOOK, os.X_OK)
