"""Notifier tests for ``scripts/self-learn-notify`` (10 §1 "Companion
scripts" row; 09 §3 "Notifications"; task U7/U8's script half — P3-6).

Hermetic PATH shimming and the never-touch-the-real-desktop discipline
mirror ``test_launcher.py`` (10 §0 rule 8) — duplicated here rather than
imported, since this suite owns only its own test files (task brief) and
``conftest.py`` belongs to a different track. ``notify-send`` is the
binary under test; when the "open" action fires this script ``exec``s
the sibling ``self-learn-ui-open`` (also PATH-shimmed downstream), so
several tests assert on the FULL delegation chain's effect (e.g. the
fake browser being launched with the right ``/record/<id>`` URL) rather
than mocking the exec boundary.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "self-learn-notify"
UI_OPEN_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "self-learn-ui-open"

_REQUIRED_REAL_BINS = (
    "bash",
    "env",
    "readlink",
    "dirname",
    "sha256sum",
    "jq",
    "cut",
    "cat",
    "mkdir",
    "timeout",
)

_EXEC_MODE = (
    stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
)


def _write_fake(bindir: Path, name: str, body: str) -> Path:
    path = bindir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(_EXEC_MODE)
    return path


def _hermetic_bindir(tmp_path: Path, **fakes: str) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name in _REQUIRED_REAL_BINS:
        real = shutil.which(name)
        assert real, f"host is missing {name}, required by the test harness itself"
        link = bindir / name
        if not link.exists():
            link.symlink_to(real)
    for name, body in fakes.items():
        _write_fake(bindir, name.replace("_", "-"), body)
    return bindir


def _env(tmp_path: Path, bindir: Path, **extra: str) -> dict[str, str]:
    home = tmp_path / "home"
    ledger_home = tmp_path / "ledger-home"
    home.mkdir(exist_ok=True)
    ledger_home.mkdir(exist_ok=True)
    base = {
        "PATH": str(bindir),
        "HOME": str(home),
        "SELF_LEARN_HOME": str(ledger_home),
    }
    base.update(extra)
    return base


def _run(
    env: dict[str, str], script: Path = SCRIPT, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _wait_for_nonempty(path: Path, timeout: float = 2.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8")
        time.sleep(0.02)
    return path.read_text(encoding="utf-8") if path.exists() else ""


# A fake notify-send that logs full argv, then behaves per its own argv:
# with -A it prints "open" (the clicked action) to stdout and exits 0;
# without -A (the plain fallback call) it just logs and exits 0.
_NOTIFY_SEND_CLICKS_OPEN = """
echo "$*" >> "{log}"
if [[ "$1" == "-A" ]]; then
  echo "open"
fi
exit 0
"""

# Dismissed/expired: rc 0, empty stdout (the CLAUDE.md-pinned swaync
# --expire-time semantics — timeout gives rc 0 + empty action output).
_NOTIFY_SEND_DISMISSED = """
echo "$*" >> "{log}"
exit 0
"""

# The -A/--wait invocation itself fails (simulates a non-action-capable
# notify-send/daemon); the plain fallback call (no -A) succeeds.
_NOTIFY_SEND_NO_ACTION_SUPPORT = """
echo "$*" >> "{log}"
if [[ "$1" == "-A" ]]; then
  exit 1
fi
exit 0
"""

_HYPRCTL_ABSENT_CHROMIUM = """
echo "$*" >> "{log}"
exit 0
"""


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing notifier at {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK)


# --- argv contract (P3-6, pinned verbatim) ------------------------------


def test_pinned_argv_contract_is_accepted(tmp_path: Path) -> None:
    """self-learn-notify --line "<rendered human string>" --ids <csv> —
    exactly this shape, exactly these two flags."""
    notify_log = tmp_path / "notify-send.log"
    bindir = _hermetic_bindir(
        tmp_path, notify_send=_NOTIFY_SEND_DISMISSED.format(log=notify_log)
    )
    env = _env(tmp_path, bindir)

    result = _run(
        env,
        SCRIPT,
        "--line",
        "self-learn: 3 new proposals for demo-skill",
        "--ids",
        "lrn-aaa,lrn-bbb",
    )

    assert result.returncode == 0
    assert notify_log.exists()


def test_missing_required_flags_exits_nonzero(tmp_path: Path) -> None:
    bindir = _hermetic_bindir(tmp_path)
    env = _env(tmp_path, bindir)

    result = _run(env, SCRIPT, "--line", "only a line")

    assert result.returncode == 2


def test_unknown_argument_exits_nonzero(tmp_path: Path) -> None:
    bindir = _hermetic_bindir(tmp_path)
    env = _env(tmp_path, bindir)

    result = _run(env, SCRIPT, "--bogus", "value")

    assert result.returncode == 2


# --- bounded --expire-time (CLAUDE.md lrn-c9044f8c pinned lesson) -------


def test_expire_time_is_bounded_and_present(tmp_path: Path) -> None:
    notify_log = tmp_path / "notify-send.log"
    bindir = _hermetic_bindir(
        tmp_path, notify_send=_NOTIFY_SEND_DISMISSED.format(log=notify_log)
    )
    env = _env(tmp_path, bindir)

    result = _run(env, SCRIPT, "--line", "line", "--ids", "lrn-1")

    assert result.returncode == 0
    content = notify_log.read_text(encoding="utf-8")
    # NAME=open (not a bare "open" — the installed notify-send 0.8.8's
    # `-A [NAME=]Text` prints NAME on click, defaulting to a numeric
    # index when omitted; see the script's BUILD FINDING comment).
    assert "-A open=" in content
    assert "--wait" in content
    assert "--expire-time" in content
    # A bounded, non-zero, non-"critical urgency" value — never absent,
    # never literally 0 (both are the unbounded-hang shapes the pinned
    # lesson names).
    tokens = content.split()
    idx = tokens.index("--expire-time")
    value = int(tokens[idx + 1])
    assert value > 0


# --- action "open" -> exec self-learn-ui-open --record <first-id> ------


def test_action_open_execs_ui_open_with_first_id(tmp_path: Path) -> None:
    notify_log = tmp_path / "notify-send.log"
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        notify_send=_NOTIFY_SEND_CLICKS_OPEN.format(log=notify_log),
        hyprctl=(
            'echo "$*" >> "' + str(hyprctl_log) + '"\n'
            'if [[ "$1" == "clients" ]]; then echo \'[]\'; fi\nexit 0'
        ),
        chromium=_HYPRCTL_ABSENT_CHROMIUM.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(
        env, SCRIPT, "--line", "line", "--ids", "lrn-first,lrn-second,lrn-third"
    )

    assert result.returncode == 0
    # Delegation happened for real (this is the REAL sibling
    # self-learn-ui-open running under exec, not a mock): the FIRST id
    # in the csv landed in the /record/<id> URL a fake browser received.
    content = _wait_for_nonempty(chromium_log)
    assert "/record/lrn-first" in content
    assert "lrn-second" not in content
    assert "lrn-third" not in content


# --- no-action-support fallback -----------------------------------------


def test_no_action_capable_daemon_falls_back_to_plain_notify(
    tmp_path: Path,
) -> None:
    notify_log = tmp_path / "notify-send.log"
    bindir = _hermetic_bindir(
        tmp_path,
        notify_send=_NOTIFY_SEND_NO_ACTION_SUPPORT.format(log=notify_log),
    )
    env = _env(tmp_path, bindir)

    result = _run(env, SCRIPT, "--line", "rendered line", "--ids", "lrn-1")

    assert result.returncode == 0
    lines = notify_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("-A open=")  # the failed action attempt
    # The plain fallback call: no -A, carries the same informative line
    # (M2's existing informative-only behavior).
    assert "-A" not in lines[1]
    assert "rendered line" in lines[1]


def test_dismissed_or_expired_action_does_nothing_further(tmp_path: Path) -> None:
    notify_log = tmp_path / "notify-send.log"
    bindir = _hermetic_bindir(
        tmp_path, notify_send=_NOTIFY_SEND_DISMISSED.format(log=notify_log)
    )
    env = _env(tmp_path, bindir)

    result = _run(env, SCRIPT, "--line", "line", "--ids", "lrn-1")

    assert result.returncode == 0
    # Only the one -A attempt — no plain-fallback second call, since the
    # daemon WAS action-capable (rc 0); it was simply dismissed/expired.
    lines = notify_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_no_daemon_at_all_exits_silently(tmp_path: Path) -> None:
    bindir = _hermetic_bindir(tmp_path)  # no notify-send shim at all
    env = _env(tmp_path, bindir)

    result = _run(env, SCRIPT, "--line", "line", "--ids", "lrn-1")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# --- sibling resolution through a symlink (P3-1) -------------------------


def test_resolves_sibling_ui_open_through_a_symlink(tmp_path: Path) -> None:
    """install.sh deploys ~/bin/self-learn-notify as a SYMLINK back into
    this repo (P3-1). Invoking through a symlink that lives somewhere
    else entirely must still find the REAL self-learn-ui-open beside the
    symlink's TARGET, never a (nonexistent) file beside the symlink
    itself."""
    notify_log = tmp_path / "notify-send.log"
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        notify_send=_NOTIFY_SEND_CLICKS_OPEN.format(log=notify_log),
        hyprctl=(
            'echo "$*" >> "' + str(hyprctl_log) + '"\n'
            'if [[ "$1" == "clients" ]]; then echo \'[]\'; fi\nexit 0'
        ),
        chromium=_HYPRCTL_ABSENT_CHROMIUM.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    # A symlink in a directory with NO self-learn-ui-open beside it —
    # a broken dirname($0) would fail to find the sibling at all.
    fake_home_bin = tmp_path / "fake-home-bin"
    fake_home_bin.mkdir()
    symlink = fake_home_bin / "self-learn-notify"
    symlink.symlink_to(SCRIPT)
    assert not (fake_home_bin / "self-learn-ui-open").exists()

    result = _run(env, symlink, "--line", "line", "--ids", "lrn-only")

    assert result.returncode == 0, result.stderr
    content = _wait_for_nonempty(chromium_log)
    assert "/record/lrn-only" in content


# --- sanity: the real sibling script this suite delegates to exists ----


def test_sibling_ui_open_script_exists() -> None:
    assert UI_OPEN_SCRIPT.is_file(), f"missing sibling at {UI_OPEN_SCRIPT}"
