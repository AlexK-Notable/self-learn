"""self-learn-notify (Bug A, incident 2026-08-09): the bash script itself,
exercised directly via subprocess with a PATH-shimmed FAKE notify-send —
same idiom as test_wrapper_symlink.py (real script, real subprocess, no
mocking of the interpreter).

HARD SAFETY: every notify-send here is a PATH shim this file writes.
NEVER the real notify-send, NEVER an unbounded -A --wait client. The
REAL script is COPIED into a per-test tmp dir (never invoked from its
repo location) alongside a FAKE self-learn-ui-open in the SAME
directory — the script resolves its sibling via `readlink -f "$0")`'s
OWN dirname (P3-1, load-bearing, NOT a PATH lookup), so this is the only
way to keep the "open" action branch from ever reaching the real
self-learn-ui-open.
"""

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

#: <repo>/plugins — tests/ → cli/ → self-learn/ → plugins/
PLUGINS_ROOT = Path(__file__).resolve().parents[3]
REAL_SCRIPT = PLUGINS_ROOT / "self-learn" / "scripts" / "self-learn-notify"


def _make_copy(tmp_path: Path) -> Path:
    """Copy the REAL script (never a rewrite) into an isolated
    ``scripts/`` dir, plus a fake ``self-learn-ui-open`` sibling — the
    directory `readlink -f "$0")` will resolve to when the copy runs."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    copy = scripts_dir / "self-learn-notify"
    copy.write_bytes(REAL_SCRIPT.read_bytes())
    copy.chmod(copy.stat().st_mode | stat.S_IEXEC)
    return copy


def _make_fake_ui_open(scripts_dir: Path, log: Path) -> None:
    fake = scripts_dir / "self-learn-ui-open"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\0\' "$@" > "{log}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)


def _shim_dir_with_notify_send(tmp_path: Path, script_body: str) -> Path:
    shims = tmp_path / "shims"
    shims.mkdir()
    fake = shims / "notify-send"
    fake.write_text(script_body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return shims


@pytest.mark.skipif(not REAL_SCRIPT.is_file(), reason="script not found")
def test_blocking_daemon_is_bounded_and_takes_the_no_action_branch(tmp_path):
    """Bug A's core claim: a notify-send that never returns (the
    daemon-down/bus-degraded shape the incident's 39.3h chain lived in —
    `--expire-time` never starts a timer because the client blocks before
    ANY notification is posted) no longer hangs the wrapper forever. The
    fake sleeps on the first (`-A ... --wait`) invocation — where
    `timeout --kill-after=5 40` must kill it — and exits immediately on
    the plain fallback invocation, so the whole run's wall clock is
    dominated by ONE 40s+5s bound, not two: comfortably under 50s wall
    clock, several orders of magnitude short of "still running 39.3h
    later"."""
    copy = _make_copy(tmp_path)
    log = tmp_path / "ui-open.log"
    _make_fake_ui_open(copy.parent, log)
    shims = _shim_dir_with_notify_send(
        tmp_path,
        "#!/usr/bin/env bash\n"
        # Only the action-capable (-A) invocation hangs — the plain
        # fallback exits immediately, isolating THIS test's assertion to
        # the ONE bound under test rather than summing two.
        'for a in "$@"; do [[ "$a" == "-A" ]] && exec sleep 999999; done\n'
        "exit 0\n",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(copy), "--line", "hello", "--ids", "lrn-aaaaaaaa"],
        env={**os.environ, "PATH": f"{shims}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=90,  # the pytest-level safety net; the script's OWN
        # bound (asserted below) must fire well before this.
    )
    elapsed = time.monotonic() - start

    assert elapsed < 55.0, (
        f"self-learn-notify did not return within its own bound "
        f"(took {elapsed:.1f}s) — a finite notify-send --expire-time is "
        f"NOT a sufficient bound (falsified by the incident); the "
        f"external timeout(1) wrapper must be what returns here"
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    # the no-action branch: never execs self-learn-ui-open
    assert not log.exists(), "must not have taken the 'open' action branch"


@pytest.mark.skipif(not REAL_SCRIPT.is_file(), reason="script not found")
def test_blocking_fallback_leg_is_independently_bounded(tmp_path):
    """FOLD 3 (gate NOTE 1, code gate 2026-08-09) — the FALLBACK
    notify-send's own `timeout` wrap had ZERO mutation coverage: dropping
    it survived the gate's mutation instrument, because the sibling test
    above only ever hangs the FIRST (-A) invocation and lets the
    fallback return instantly, so a bug that un-bounded the fallback
    specifically would never show up as a slow test.

    Inverted here: the first invocation fails FAST (simulating "no
    action-capable daemon" — the real trigger for taking the fallback
    branch at all), and the FALLBACK (plain, no -A) invocation is what
    hangs. Bounded return here can ONLY be explained by the fallback
    line's OWN `timeout ... notify-send` wrap, not the primary one."""
    copy = _make_copy(tmp_path)
    log = tmp_path / "ui-open.log"
    _make_fake_ui_open(copy.parent, log)
    shims = _shim_dir_with_notify_send(
        tmp_path,
        "#!/usr/bin/env bash\n"
        # The action-capable (-A) invocation fails FAST — this is what
        # actually drives the script into the fallback branch. The
        # PLAIN (fallback) invocation hangs, isolating this test's
        # assertion to the fallback's own bound.
        'for a in "$@"; do [[ "$a" == "-A" ]] && exit 1; done\n'
        "exec sleep 999999\n",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(copy), "--line", "hello", "--ids", "lrn-eeeeeeee"],
        env={**os.environ, "PATH": f"{shims}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=90,  # pytest-level safety net only
    )
    elapsed = time.monotonic() - start

    assert elapsed < 55.0, (
        f"the FALLBACK notify-send leg did not return within its own "
        f"bound (took {elapsed:.1f}s) — its `timeout ... notify-send` "
        f"wrap must be what returns here, independent of the primary "
        f"invocation's own bound"
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert not log.exists(), "must not have taken the 'open' action branch"


@pytest.mark.skipif(not REAL_SCRIPT.is_file(), reason="script not found")
def test_every_notify_send_invocation_is_timeout_bounded():
    """FOLD 3 (gate NOTE 1, cheap belt-and-braces) — static check: every
    LINE in the real script that actually invokes `notify-send` (never
    the `command -v notify-send` probe, which is not an invocation) also
    names `timeout` on the same line. A future edit that adds a bare
    notify-send call (primary, fallback, or any new leg) fails this
    immediately, without needing a slow subprocess-timing test to notice."""
    src = REAL_SCRIPT.read_text(encoding="utf-8")
    invocation_lines = [
        ln
        for ln in src.splitlines()
        if "notify-send" in ln
        and not ln.strip().startswith("#")
        and "command -v notify-send" not in ln
    ]
    assert invocation_lines, "no notify-send invocation line found — nothing to pin"
    for ln in invocation_lines:
        assert "timeout" in ln, (
            f"a notify-send invocation is not timeout-wrapped: {ln!r}"
        )


@pytest.mark.skipif(not REAL_SCRIPT.is_file(), reason="script not found")
def test_open_action_fires_self_learn_ui_open_with_the_first_id(tmp_path):
    """The action-output branching survives the timeout wrap: a
    notify-send that prints "open" (the pinned NAME=open action id,
    BUILD FINDING in the script's own header) still execs the sibling
    self-learn-ui-open with the FIRST id in the --ids csv — the SAME
    behavior the pre-Bug-A script had, now reached through `timeout
    ... notify-send` rather than a bare one."""
    copy = _make_copy(tmp_path)
    log = tmp_path / "ui-open.log"
    _make_fake_ui_open(copy.parent, log)
    shims = _shim_dir_with_notify_send(
        tmp_path,
        "#!/usr/bin/env bash\n"
        'echo "open"\n'
        "exit 0\n",
    )

    result = subprocess.run(
        [str(copy), "--line", "hello", "--ids", "lrn-bbbbbbbb,lrn-cccccccc"],
        env={**os.environ, "PATH": f"{shims}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert log.exists(), "self-learn-ui-open (the shim) was never invoked"
    argv = log.read_text(encoding="utf-8").split("\0")[:-1]
    # the pinned deep-link rule: the FIRST id in the csv, never the rest.
    assert argv == ["--record", "lrn-bbbbbbbb"]


@pytest.mark.skipif(not REAL_SCRIPT.is_file(), reason="script not found")
def test_missing_daemon_exits_silently(tmp_path):
    """Degradation ladder, unchanged by Bug A: no notify-send on PATH at
    all -> exit 0, nothing attempted, no hang (this leg was never the
    incident's shape, but it must survive the timeout-wrapping edit).

    On THIS host notify-send is installed system-wide at
    /usr/bin/notify-send — the SAME directory bash/readlink/dirname live
    in, so excluding "/usr/bin" from PATH is not an option (the script
    would fail to even start). Build a PATH of ONLY the essentials
    (symlinks, never notify-send) instead."""
    copy = _make_copy(tmp_path)
    log = tmp_path / "ui-open.log"
    _make_fake_ui_open(copy.parent, log)
    essential_bin = tmp_path / "essential-bin"
    essential_bin.mkdir()
    for name in ("bash", "readlink", "dirname"):
        real = shutil.which(name)
        assert real, f"{name} not found on the host PATH — cannot build the test env"
        (essential_bin / name).symlink_to(real)

    result = subprocess.run(
        [str(copy), "--line", "hello", "--ids", "lrn-dddddddd"],
        env={**os.environ, "PATH": str(essential_bin)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert not log.exists()
