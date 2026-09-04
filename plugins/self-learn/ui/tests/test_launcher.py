"""Launcher tests for ``scripts/self-learn-ui-open`` (10 §1 "Companion
scripts" row; 09 §3 "Deep-link + launcher"; task U7).

Every desktop-facing binary this script can reach (hyprctl, systemctl,
browsers, xdg-open) is PATH-shimmed inside a FULLY hermetic bin dir —
NO fallback to the real system PATH — so these tests never touch the
real desktop (10 §0 rule 8). That matters concretely on this build host:
it runs Hyprland, so a leaky PATH would let a "hyprctl absent" test
silently invoke the REAL hyprctl instead of exercising the degradation
branch. ``XDG_RUNTIME_DIR``/``XDG_CACHE_HOME``/``SELF_LEARN_HOME`` are
always pointed at ``tmp_path`` subdirectories via an explicit ``env``
dict handed to ``subprocess.run`` (this suite drives the script as a
subprocess with its own environment, independent of the
``redirected_xdg`` fixture in ``conftest.py``, which patches THIS
process's os.environ instead).
"""

from __future__ import annotations

import hashlib
import shutil
import socket
import stat
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "self-learn-ui-open"

# Real coreutils the script's OWN plumbing depends on (sha256sum, jq,
# cut for the token-path formula; readlink/dirname/cat/mkdir elsewhere in
# the surface's script family) — always symlinked in from the host.
# What's actually under test — hyprctl, systemctl, the browsers,
# xdg-open — is shimmed per test, never these.
_REQUIRED_REAL_BINS = (
    "bash",
    "env",
    "sha256sum",
    "jq",
    "cut",
    "cat",
    "mkdir",
    "dirname",
    "readlink",
    "sleep",
    # M-F2 (C22): the script now wraps every systemctl/hyprctl call in
    # `timeout 4` — a fully hermetic PATH (no fallback to the real
    # system PATH, per this file's own header) must supply it too, or
    # every one of those calls "command not found"s instead of
    # exercising the fake systemctl/hyprctl this suite installs.
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
    """A PATH with ONLY symlinks to the required real coreutils plus one
    fake script per keyword arg (``_``-separated arg name -> ``-``
    binary name, e.g. ``google_chrome_stable=`` -> ``google-chrome-stable``).
    Nothing else is reachable — a binary omitted here is genuinely
    absent to the script under test."""
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


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _wait_for_nonempty(path: Path, timeout: float = 2.0) -> str:
    """The launch/focus action runs backgrounded + disowned in the real
    script (it must return promptly, never block on the browser
    process) — poll briefly for the fake binary's log instead of racing
    it with an immediate read."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8")
        time.sleep(0.02)
    return path.read_text(encoding="utf-8") if path.exists() else ""


_LOG_HYPRCTL = "hyprctl_log"
_LOG_CHROMIUM = "chromium_log"
_LOG_XDG_OPEN = "xdg_open_log"
_LOG_SYSTEMCTL = "systemctl_log"

_HYPRCTL_BODY_TMPL = """
echo "$*" >> "{log}"
if [[ "$1" == "clients" ]]; then
  echo '{clients_json}'
fi
exit 0
"""

# M-F2 (C22): a `hyprctl` that never returns on its own — logs its args
# immediately (so the call DID happen), then blocks well past the
# script's own `timeout 4` bound before ever printing anything. Proves
# the launcher's hyprctl calls are actually BOUNDED, not merely
# preceded by a `command -v hyprctl` presence check (presence says
# nothing about a wedged compositor that hangs mid-call).
_SLEEPY_HYPRCTL_TMPL = """
echo "$*" >> "{log}"
sleep {sleep_s}
echo '[]'
exit 0
"""

_LOGGING_LAUNCH_TMPL = """
echo "$*" >> "{log}"
exit 0
"""

# Y-14 readiness-wait fakes: a systemctl that reports a snapshot state
# on `is-active` (stdout — the launcher captures it) and can run an
# arbitrary hook on `start` (e.g. writing the fresh token, simulating
# the server coming up).
_SYSTEMCTL_TMPL = """
echo "$*" >> "{log}"
if [[ "$2" == "is-active" ]]; then
  echo "{state}"
fi
exit 0
"""

_SYSTEMCTL_START_HOOK_TMPL = """
echo "$*" >> "{log}"
if [[ "$2" == "is-active" ]]; then
  echo "{state}"
fi
if [[ "$2" == "start" ]]; then
  {start_hook}
  exit {start_rc}
fi
exit 0
"""


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing launcher at {SCRIPT}"
    import os

    assert os.access(SCRIPT, os.X_OK)


def test_unknown_argument_exits_nonzero(tmp_path: Path) -> None:
    bindir = _hermetic_bindir(tmp_path)
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(tmp_path / "runtime"))
    result = _run(env, "--bogus")
    assert result.returncode == 2


# --- X-3: window-presence detection (never branch on dispatch's exit
# code — query `hyprctl clients -j` for the class FIRST) --------------


def test_window_present_dispatches_focuswindow_and_never_launches(
    tmp_path: Path,
) -> None:
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(
            log=hyprctl_log,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front"}]',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    # Give the (non-backgrounded, synchronous) dispatch call a moment —
    # there is nothing to launch, so poll the hyprctl log directly.
    hyprctl_content = _wait_for_nonempty(hyprctl_log)
    # Focus is dispatched by the matched window's ADDRESS, never by keying
    # off `focuswindow`'s (always-0) exit code (final-review MAJOR, X-3).
    assert "dispatch focuswindow address:0xAAA" in hyprctl_content
    assert not chromium_log.exists() or chromium_log.stat().st_size == 0


def test_window_absent_launches_browser_and_never_dispatches(
    tmp_path: Path,
) -> None:
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(log=hyprctl_log, clients_json="[]"),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    start = time.monotonic()
    result = _run(env)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    # Delta F3: SELF_LEARN_UI_MONITOR unset must mean NO placement poll
    # on the fresh-launch path — a ≤5 s poll here would show as ≥5 s.
    assert elapsed < 3.0, "monitor unset: fresh launch must not poll"
    chromium_content = _wait_for_nonempty(chromium_log)
    assert "--class=self-learn-ui" in chromium_content
    assert "--app=http://127.0.0.1:7357/" in chromium_content
    hyprctl_content = hyprctl_log.read_text(encoding="utf-8")
    assert "dispatch" not in hyprctl_content


def test_hyprctl_absent_skips_detection_and_launches(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(chromium_log)
    assert "--class=self-learn-ui" in content


def test_hyprctl_call_is_bounded_by_timeout(tmp_path: Path) -> None:
    """M-F2 (C22): every hyprctl call this script makes is wrapped in
    `timeout 4` — a wedged compositor must not hang the launcher forever.
    This node covers ONE of the nine wrapped call sites (`clients -j`
    inside `_ui_window_address`); the sibling tests further down this
    file (systemctl, the three `_ensure_on_monitor` dispatch calls, the
    three remaining read calls) cover the rest.

    Mutation target: strip any `timeout N ` prefix from a hyprctl
    invocation (starting with the `clients -j` read inside
    `_ui_window_address`, the very first hyprctl call on this code path)
    and this fake, which sleeps well past that bound before ever
    printing, makes the whole script run long past it too — this test's
    own generous ceiling (well under the fake's sleep duration) then
    fails instead of the ~4s a correctly-bounded call takes.
    """
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_SLEEPY_HYPRCTL_TMPL.format(log=hyprctl_log, sleep_s=12),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=20
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 8.0, (
        f"hyprctl call took {elapsed:.1f}s (fake sleeps 12s) — the "
        "`timeout 4` wrap around the launcher's hyprctl calls appears to "
        "be missing"
    )
    # The wrap bounds the CALL only; the launcher still degrades exactly
    # as it does for an absent window (a timed-out `clients -j` reads as
    # empty via the existing `|| return 0`) and launches normally.
    content = _wait_for_nonempty(chromium_log)
    assert "--class=self-learn-ui" in content
    hyprctl_content = hyprctl_log.read_text(encoding="utf-8")
    assert "clients -j" in hyprctl_content


# M-F2 gate follow-up (fold r0): the mutation-test coverage above only
# reached ONE of the script's nine `timeout`-wrapped external calls
# (`clients -j` inside `_ui_window_address`). The tests below close the
# rest of the gap: a sleepy `systemctl` (the is-active/start pair near
# the top of the script), a sleepy `hyprctl dispatch` (the
# focuswindow/movewindow pair inside `_ensure_on_monitor`, which a first
# pass of this move left UNWRAPPED — nine call sites exist, not seven;
# see the build report), and — fold r1 MAJOR 1 — a sleepy set of
# READ-style hyprctl calls (`clients -j`/`monitors -j` inside
# `_window_monitor_name`, `activewindow -j` inside `_ensure_on_monitor`)
# that the dispatch test below answers INSTANTLY and so never actually
# proves are bounded. Together with the presence-check test above, all
# nine sites now each have a node that would redden if their `timeout 4`
# wrap were removed.

_SLEEPY_SYSTEMCTL_TMPL = """
echo "$*" >> "{log}"
sleep {sleep_s}
if [[ "$2" == "is-active" ]]; then
  echo "{state}"
fi
exit 0
"""


def test_systemctl_calls_are_bounded_by_timeout(tmp_path: Path) -> None:
    """M-F2 (C22): both `systemctl --user is-active` and `systemctl
    --user start` are wrapped in `timeout 4`.

    `state="active"` skips the Y-14 readiness-wait loop entirely (its
    guard is `_PRE_STATE != "active"`), isolating this test to just the
    two systemctl calls themselves — no confound from the poll loop's
    own up-to-10s budget. hyprctl is left absent (irrelevant to this
    call pair) so the script falls straight through to `_launch`.

    Mutation target: strip `timeout 4` from EITHER the `is-active` or
    the `start` invocation. This fake sleeps unconditionally on every
    call, so a stripped wrap lets that one call run the full 12s
    instead of being cut to ~4s — pushing total elapsed past this
    test's ceiling.
    """
    systemctl_log = tmp_path / "systemctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        systemctl=_SLEEPY_SYSTEMCTL_TMPL.format(
            log=systemctl_log, sleep_s=12, state="active"
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=40
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    # fold r1 m1: tightened from 15.0 -- the wrapped run measures ~8s
    # (4s + 4s), a single stripped wrap measures ~24s (12s + 4s); 12.0
    # sits with real margin on both sides instead of close to either.
    assert elapsed < 12.0, (
        f"systemctl calls took {elapsed:.1f}s (fake sleeps 12s per call) — "
        "a `timeout 4` wrap around is-active or start appears to be missing"
    )
    log = systemctl_log.read_text(encoding="utf-8")
    assert "is-active" in log
    assert "start" in log
    assert _wait_for_nonempty(chromium_log), "the launch must still happen"


_SLEEPY_DISPATCH_HYPRCTL_TMPL = """
echo "$*" >> "{log}"
if [[ "$1" == "clients" ]]; then
  echo '{clients_json}'
elif [[ "$1" == "monitors" ]]; then
  echo '{monitors_json}'
elif [[ "$1" == "activewindow" ]]; then
  echo '{active_json}'
elif [[ "$1" == "dispatch" ]]; then
  sleep {sleep_s}
fi
exit 0
"""


def test_ensure_on_monitor_dispatch_calls_are_bounded_by_timeout(
    tmp_path: Path,
) -> None:
    """M-F2 (C22): the focuswindow/movewindow dispatches INSIDE
    `_ensure_on_monitor` are wrapped in `timeout 4` — this node covers
    the THREE dispatch-verb call sites specifically; the three
    read-verb sites on the same code path (clients/monitors/
    activewindow) answer instantly here on purpose and are covered
    separately by test_hyprctl_read_calls_are_bounded_by_timeout below.

    `clients`/`monitors`/`activewindow` all answer instantly here; only
    `dispatch` sleeps. `monitors_json="[]"` (unknown current placement)
    forces the unconditional-move path, and `active_json` echoes OUR
    address so the F2 stale-address gate passes — walking through all
    THREE dispatch calls the script makes on this code path: the
    top-level focus-on-presence-check dispatch (already wrapped before
    this move), then `_ensure_on_monitor`'s own focuswindow and
    movewindow dispatches (the two this follow-up wraps).

    Mutation target: strip `timeout 4` from either dispatch inside
    `_ensure_on_monitor`. Each unwrapped dispatch then runs the fake's
    full 12s sleep instead of being cut to ~4s, and this test's ceiling
    (well under two full unbounded sleeps) catches it.
    """
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_SLEEPY_DISPATCH_HYPRCTL_TMPL.format(
            log=hyprctl_log,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front","monitor":0}]',
            monitors_json="[]",
            active_json='{"address":"0xAAA"}',
            sleep_s=12,
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-9",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=40
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    # fold r1 m1: tightened from 20.0 -- the wrapped run measures ~12s
    # (4s x 3 dispatches), a single stripped wrap measures ~28s (4s+4s+
    # 12s); 16.0 sits with real margin on both sides instead of close
    # to either.
    assert elapsed < 16.0, (
        f"dispatch calls took {elapsed:.1f}s (fake sleeps 12s per dispatch) "
        "— a `timeout 4` wrap around one of _ensure_on_monitor's two "
        "dispatch calls appears to be missing"
    )
    log = hyprctl_log.read_text(encoding="utf-8")
    assert log.count("dispatch") == 3, (
        "expected the top-level focus dispatch plus _ensure_on_monitor's "
        f"focuswindow and movewindow dispatches (3 total); log was: {log!r}"
    )


_DELAYED_NTH_CALL_HYPRCTL_TMPL = """
count_file="{count_file}"
n=$(( $(cat "$count_file" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$count_file"
echo "$*" >> "{log}"
if [[ "$n" == "{slow_n}" ]]; then
  sleep {sleep_s}
fi
case "$1" in
  clients) echo '{clients_json}' ;;
  monitors) echo '{monitors_json}' ;;
  activewindow) echo '{active_json}' ;;
esac
exit 0
"""
# MAJOR 1 (fold r1): a NUMBERED-call fake, not a per-verb one. `clients
# -j` is the SAME literal invocation whether it comes from the
# presence-check `_ui_window_address` (already covered by
# test_hyprctl_call_is_bounded_by_timeout above) or from
# `_window_monitor_name`'s own read — an earlier draft that made ALL
# reads sleep discovered empirically that this doesn't work anyway: a
# read call that genuinely runs past the `timeout 4` bound makes
# `timeout` itself exit 124 regardless of what JSON the fake already
# printed, and every read site here is guarded by `|| return 0` — so
# the CALLER bails immediately on ANY killed read, never reaching the
# next one. There is no scenario where two DIFFERENT reads can both be
# slow in the same run and still walk the intended path. So exactly
# ONE call — identified by its 1-based position in the whole hyprctl
# call sequence, tracked via `{count_file}` — sleeps past the bound;
# every other call (including any OTHER `clients -j`) answers
# instantly and correctly, so the script walks deterministically up to
# the targeted call before that one, alone, gets bounded.
#
# The full call sequence for "window present, monitor set, no match"
# (used by every test below) is: 1=clients (presence check), 2=dispatch
# focuswindow (presence-check branch), 3=clients (_window_monitor_name),
# 4=monitors (_window_monitor_name), 5=dispatch focuswindow
# (_ensure_on_monitor), 6=activewindow (_ensure_on_monitor), 7=dispatch
# movewindow (_ensure_on_monitor).


def test_window_monitor_name_clients_read_is_bounded_by_timeout(
    tmp_path: Path,
) -> None:
    """MAJOR 1 (fold r1): `_window_monitor_name`'s OWN `clients -j` read
    (call #3 in the sequence — distinct from the presence check's
    `clients -j`, call #1, already covered above) is `timeout 4`-wrapped.

    Mutation target: strip `timeout 4` from THIS specific `clients -j`
    site and call #3 runs the fake's full 12s instead of being cut to
    ~4s, pushing elapsed past this test's ceiling — while call #1 (the
    presence check, still correctly wrapped or not, doesn't matter
    here) stays fast either way.
    """
    hyprctl_log = tmp_path / "hyprctl.log"
    count_file = tmp_path / "call-count"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_DELAYED_NTH_CALL_HYPRCTL_TMPL.format(
            log=hyprctl_log,
            count_file=count_file,
            slow_n=3,
            sleep_s=12,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front","monitor":0}]',
            monitors_json="[]",
            active_json='{"address":"0xAAA"}',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-9",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=20
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 8.0, (
        f"took {elapsed:.1f}s — the `timeout 4` wrap around "
        "_window_monitor_name's clients -j read appears to be missing"
    )
    log = hyprctl_log.read_text(encoding="utf-8")
    assert log.count("clients -j") == 2, log


def test_window_monitor_name_monitors_read_is_bounded_by_timeout(
    tmp_path: Path,
) -> None:
    """MAJOR 1 (fold r1): `_window_monitor_name`'s `monitors -j` read
    (call #4) is `timeout 4`-wrapped — reached only once its own
    `clients -j` read (call #3) resolves a numeric monitor id, which it
    does here since that call answers instantly.

    Mutation target: strip `timeout 4` from the `monitors -j` site and
    call #4 runs the full 12s instead of ~4s.
    """
    hyprctl_log = tmp_path / "hyprctl.log"
    count_file = tmp_path / "call-count"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_DELAYED_NTH_CALL_HYPRCTL_TMPL.format(
            log=hyprctl_log,
            count_file=count_file,
            slow_n=4,
            sleep_s=12,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front","monitor":0}]',
            monitors_json="[]",
            active_json='{"address":"0xAAA"}',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-9",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=20
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 8.0, (
        f"took {elapsed:.1f}s — the `timeout 4` wrap around "
        "_window_monitor_name's monitors -j read appears to be missing"
    )
    log = hyprctl_log.read_text(encoding="utf-8")
    assert "monitors -j" in log


def test_ensure_on_monitor_activewindow_read_is_bounded_by_timeout(
    tmp_path: Path,
) -> None:
    """MAJOR 1 (fold r1): `_ensure_on_monitor`'s `activewindow -j` read
    (call #6, the F2 stale-address gate) is `timeout 4`-wrapped —
    reached only once the focuswindow dispatch at call #5 has fired,
    which it does here since every call before #6 answers instantly.

    Mutation target: strip `timeout 4` from the `activewindow -j` site
    and call #6 runs the full 12s instead of ~4s.
    """
    hyprctl_log = tmp_path / "hyprctl.log"
    count_file = tmp_path / "call-count"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_DELAYED_NTH_CALL_HYPRCTL_TMPL.format(
            log=hyprctl_log,
            count_file=count_file,
            slow_n=6,
            sleep_s=12,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front","monitor":0}]',
            monitors_json="[]",
            active_json='{"address":"0xAAA"}',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-9",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=20
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 8.0, (
        f"took {elapsed:.1f}s — the `timeout 4` wrap around "
        "_ensure_on_monitor's activewindow -j read appears to be missing"
    )
    log = hyprctl_log.read_text(encoding="utf-8")
    assert "activewindow -j" in log



def test_opener_still_works_without_timeout_on_path(tmp_path: Path) -> None:
    """m2 (fold r1): `timeout` itself can be legitimately absent from a
    host's PATH — it was never a dependency before C22 introduced it.
    `_TO` must degrade to an empty array so `systemctl`/`hyprctl` still
    run DIRECTLY, unbounded, rather than never executing at all: a bare
    `timeout 4 systemctl …` prefix means that when `timeout` 404s,
    `systemctl` never even execs (this was the false half of the
    header's old "identical tolerance" claim, worst for `systemctl
    start`'s real side effect).

    Builds its own bindir (rather than `_hermetic_bindir`, which always
    symlinks every `_REQUIRED_REAL_BINS` name including `timeout`) with
    everything else present but `timeout` deliberately excluded, and
    proves systemctl AND hyprctl are still actually invoked (their fake
    logs receive the real arg lines) and the launch still happens.
    """
    bindir = tmp_path / "bin-no-timeout"
    bindir.mkdir()
    for name in _REQUIRED_REAL_BINS:
        if name == "timeout":
            continue
        real = shutil.which(name)
        assert real, f"host is missing {name}, required by the test harness itself"
        (bindir / name).symlink_to(real)
    systemctl_log = tmp_path / "systemctl.log"
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    _write_fake(
        bindir,
        "systemctl",
        _SYSTEMCTL_TMPL.format(log=systemctl_log, state="active"),
    )
    _write_fake(
        bindir,
        "hyprctl",
        _HYPRCTL_BODY_TMPL.format(log=hyprctl_log, clients_json="[]"),
    )
    _write_fake(bindir, "chromium", _LOGGING_LAUNCH_TMPL.format(log=chromium_log))
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    assert "timeout" not in {p.name for p in bindir.iterdir()}
    # Fold r2 / M-F2 NIT 1: name the failure — without this, a broken
    # `_TO` degrade (systemctl never invoked) reddens this test via a
    # bare FileNotFoundError from read_text() on a log that was never
    # written, not a message that says what actually went wrong.
    assert systemctl_log.exists(), "systemctl was never invoked — _TO did not degrade"
    systemctl_content = systemctl_log.read_text(encoding="utf-8")
    assert "is-active" in systemctl_content
    assert "start" in systemctl_content
    hyprctl_content = hyprctl_log.read_text(encoding="utf-8")
    assert "clients -j" in hyprctl_content
    assert _wait_for_nonempty(chromium_log), "the launch must still happen"


def test_window_present_by_title_focuses_when_class_is_url_derived(
    tmp_path: Path,
) -> None:
    """T-D live trial (2026-07-17): when chromium is already running it
    derives the --app window's app_id from the URL and IGNORES --class,
    so the window's class is e.g. `chrome-127.0.0.1__record_lrn-…-Default`,
    never `self-learn-ui`. The launcher must still recognize an existing
    UI window by its "self-learn — " TITLE prefix and focus it, rather
    than spawning yet another window."""
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(
            log=hyprctl_log,
            clients_json=(
                '[{"class":"chrome-127.0.0.1__record_lrn-07dcbf0f-Default",'
                '"address":"0xBEEF","title":"self-learn — lrn-07dcbf0f"}]'
            ),
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    hyprctl_content = _wait_for_nonempty(hyprctl_log)
    # The class is URL-derived (not self-learn-ui), so the window is found
    # by TITLE and focused by its ADDRESS — proving the fix is effective,
    # not merely that some dispatch was emitted (final-review MAJOR). If
    # the title match were removed, the address would be empty and chromium
    # would launch instead — this assertion would then fail.
    assert "dispatch focuswindow address:0xBEEF" in hyprctl_content
    assert not chromium_log.exists() or chromium_log.stat().st_size == 0


# --- Token resolution: primary vs. X-8/X-12 fallback -------------------


def test_token_primary_path_used_when_xdg_runtime_dir_set(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    token_dir = runtime_dir / "self-learn"
    token_dir.mkdir()
    (token_dir / "ui-token").write_text("primarytok", encoding="utf-8")
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(chromium_log)
    assert "token=primarytok" in content


def test_token_x8_fallback_when_xdg_runtime_dir_unset(tmp_path: Path) -> None:
    """09 §11 Y-3 / 10 §5 X-8-X-12: XDG_RUNTIME_DIR unset (headless/SSH)
    falls back to the home-namespaced cache dir's ui-token. The digest
    formula is independently recomputed here with Python's hashlib
    against the SAME string the CLI hashes
    (``hashlib.sha256(str(Path(home).expanduser())
    .encode()).hexdigest()[:8]`` — self_learn.worker.cache_dir /
    self_learn.ledger.resolve_home) so this test fails if the script's
    bash mirror of that formula ever drifts."""
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    ledger_home = tmp_path / "ledger-home"
    ledger_home.mkdir(exist_ok=True)
    cache_home = tmp_path / "cache-home"
    cache_home.mkdir()

    digest = hashlib.sha256(str(ledger_home).encode("utf-8")).hexdigest()[:8]
    token_dir = cache_home / "self-learn" / f"home-{digest}"
    token_dir.mkdir(parents=True)
    (token_dir / "ui-token").write_text("fallbacktok", encoding="utf-8")

    env = _env(tmp_path, bindir, XDG_CACHE_HOME=str(cache_home))
    assert "XDG_RUNTIME_DIR" not in env  # genuinely unset, not empty

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(chromium_log)
    assert "token=fallbacktok" in content


def test_missing_token_file_omits_query_string(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(chromium_log)
    assert "?token=" not in content
    assert "--app=http://127.0.0.1:7357/" in content


# --- Browser resolution order -------------------------------------------


def test_browser_env_override_wins_over_chromium(tmp_path: Path) -> None:
    custom_log = tmp_path / "custom.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        my_custom_browser=_LOGGING_LAUNCH_TMPL.format(log=custom_log),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_BROWSER="my-custom-browser",
    )

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(custom_log)
    assert "--class=self-learn-ui" in content
    assert not chromium_log.exists() or chromium_log.stat().st_size == 0


def test_google_chrome_stable_used_when_chromium_absent(tmp_path: Path) -> None:
    gcs_log = tmp_path / "gcs.log"
    bindir = _hermetic_bindir(
        tmp_path, google_chrome_stable=_LOGGING_LAUNCH_TMPL.format(log=gcs_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(gcs_log)
    assert "--class=self-learn-ui" in content


def test_xdg_open_fallback_when_no_chromium_family_browser(tmp_path: Path) -> None:
    xdg_open_log = tmp_path / "xdg-open.log"
    bindir = _hermetic_bindir(
        tmp_path, xdg_open=_LOGGING_LAUNCH_TMPL.format(log=xdg_open_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(xdg_open_log)
    assert "http://127.0.0.1:7357/" in content
    # No --app/--class here: xdg-open just opens a plain tab.
    assert "--class" not in content


# --- systemctl ensure-service step --------------------------------------


def test_systemctl_absent_is_skipped_silently(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    assert result.stderr == ""
    # Still reaches the launch step despite systemctl's total absence.
    assert _wait_for_nonempty(chromium_log)


def test_systemctl_present_starts_the_service(tmp_path: Path) -> None:
    systemctl_log = tmp_path / "systemctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        # Answers "active" to is-active: a WARM service, so this test
        # never enters the Y-14 readiness wait (that wait has its own
        # tests below) — it pins only that start is always invoked.
        systemctl=_SYSTEMCTL_TMPL.format(log=systemctl_log, state="active"),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    content = systemctl_log.read_text(encoding="utf-8")
    assert "--user start self-learn-ui.service" in content


# --- --record URL shape ---------------------------------------------------


def test_record_id_builds_record_path(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env, "--record", "lrn-abcdef01")

    assert result.returncode == 0
    content = _wait_for_nonempty(chromium_log)
    assert "--app=http://127.0.0.1:7357/record/lrn-abcdef01" in content


def test_no_record_id_builds_root_path(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    content = _wait_for_nonempty(chromium_log)
    assert "--app=http://127.0.0.1:7357/" in content
    assert "/record/" not in content


def test_port_override_respected(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_PORT="9999",
    )

    result = _run(env, "--record", "lrn-x")

    assert result.returncode == 0
    content = _wait_for_nonempty(chromium_log)
    assert "http://127.0.0.1:9999/record/lrn-x" in content


# --- Y-14 readiness wait (09 §3 "Deep-link + launcher"; 10 §3 U13) --------
#
# Cold ⟺ is-active snapshot anything other than `active`; one ≤5 s
# budget: fresh token THEN TCP connect; unchanged-token-plus-connect
# counts as ready (delta R2); timeout degrades to the stale-token URL
# (the 403 page names this script). Durations are asserted coarsely —
# fast paths must finish far under the 5 s budget, the timeout path
# must actually burn it.


def _listener() -> tuple[socket.socket, int]:
    """A real localhost listener — bash's /dev/tcp connect completes
    against the listen backlog, no accept() needed."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def _closed_port() -> int:
    """An ephemeral port that is bound-then-closed, so connects fail fast."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_warm_service_skips_readiness_wait(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    systemctl_log = tmp_path / "systemctl.log"
    bindir = _hermetic_bindir(
        tmp_path,
        systemctl=_SYSTEMCTL_TMPL.format(log=systemctl_log, state="active"),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "self-learn").mkdir(parents=True)
    (runtime_dir / "self-learn" / "ui-token").write_text("tok-warm", encoding="utf-8")
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_PORT=str(_closed_port()),  # nothing listening: a wait would burn 5 s
    )

    start = time.monotonic()
    result = _run(env)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 3.0, "warm service must skip the wait entirely"
    assert "token=tok-warm" in _wait_for_nonempty(chromium_log)


def test_cold_start_waits_for_fresh_token_then_connect(tmp_path: Path) -> None:
    chromium_log = tmp_path / "chromium.log"
    systemctl_log = tmp_path / "systemctl.log"
    runtime_dir = tmp_path / "runtime"
    token_path = runtime_dir / "self-learn" / "ui-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("tok-stale", encoding="utf-8")

    sock, port = _listener()
    try:
        bindir = _hermetic_bindir(
            tmp_path,
            # `start` writes the fresh token — the simulated server
            # coming up (write precedes bind; the listener is already
            # bound here, which only shortens phase 2).
            systemctl=_SYSTEMCTL_START_HOOK_TMPL.format(
                log=systemctl_log,
                state="inactive",
                start_hook=f'printf tok-fresh > "{token_path}"',
                start_rc=0,
            ),
            chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
        )
        env = _env(
            tmp_path,
            bindir,
            XDG_RUNTIME_DIR=str(runtime_dir),
            SELF_LEARN_UI_PORT=str(port),
        )

        start = time.monotonic()
        result = _run(env)
        elapsed = time.monotonic() - start
    finally:
        sock.close()

    assert result.returncode == 0
    assert elapsed < 3.0, "fresh token + open port must release immediately"
    assert "token=tok-fresh" in _wait_for_nonempty(chromium_log)


def test_unchanged_token_with_connect_counts_as_ready(tmp_path: Path) -> None:
    # Delta R2, the double-click case: the second launcher snapshots the
    # already-fresh token during the first launcher's cold start — a
    # token change never comes, but a successful connect is proof.
    chromium_log = tmp_path / "chromium.log"
    systemctl_log = tmp_path / "systemctl.log"
    runtime_dir = tmp_path / "runtime"
    token_path = runtime_dir / "self-learn" / "ui-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("tok-fresh", encoding="utf-8")

    sock, port = _listener()
    try:
        bindir = _hermetic_bindir(
            tmp_path,
            systemctl=_SYSTEMCTL_TMPL.format(log=systemctl_log, state="activating"),
            chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
        )
        env = _env(
            tmp_path,
            bindir,
            XDG_RUNTIME_DIR=str(runtime_dir),
            SELF_LEARN_UI_PORT=str(port),
        )

        start = time.monotonic()
        result = _run(env)
        elapsed = time.monotonic() - start
    finally:
        sock.close()

    assert result.returncode == 0
    assert elapsed < 3.0, "connect success must not burn the budget on token-watch"
    assert "token=tok-fresh" in _wait_for_nonempty(chromium_log)


def test_cold_start_polls_for_a_delayed_token(tmp_path: Path) -> None:
    # Code-review NIT, folded: the synchronous-start-hook test releases
    # on iteration 1, so this variant delays BOTH signals past several
    # poll iterations — the real Type=simple shape (start returns,
    # token lands later, bind later still) — pinning that the loop
    # actually polls rather than checking once.
    import threading

    chromium_log = tmp_path / "chromium.log"
    systemctl_log = tmp_path / "systemctl.log"
    runtime_dir = tmp_path / "runtime"
    token_path = runtime_dir / "self-learn" / "ui-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("tok-stale", encoding="utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]  # bound but NOT listening yet

    def server_comes_up() -> None:
        token_path.write_text("tok-fresh", encoding="utf-8")
        sock.listen(1)

    timer = threading.Timer(0.4, server_comes_up)
    try:
        bindir = _hermetic_bindir(
            tmp_path,
            systemctl=_SYSTEMCTL_TMPL.format(log=systemctl_log, state="inactive"),
            chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
        )
        env = _env(
            tmp_path,
            bindir,
            XDG_RUNTIME_DIR=str(runtime_dir),
            SELF_LEARN_UI_PORT=str(port),
        )
        timer.start()
        start = time.monotonic()
        result = _run(env)
        elapsed = time.monotonic() - start
    finally:
        timer.cancel()
        sock.close()

    assert result.returncode == 0
    assert 0.3 < elapsed < 3.0, "must poll past the delay, then release promptly"
    assert "token=tok-fresh" in _wait_for_nonempty(chromium_log)


def test_cold_start_timeout_degrades_to_stale_token(tmp_path: Path) -> None:
    # Token never changes, nothing ever listens: the launcher burns the
    # ≤5 s budget, then proceeds with what is readable — today's 403
    # degradation (the page names this script), never a hard failure.
    chromium_log = tmp_path / "chromium.log"
    systemctl_log = tmp_path / "systemctl.log"
    runtime_dir = tmp_path / "runtime"
    token_path = runtime_dir / "self-learn" / "ui-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("tok-stale", encoding="utf-8")

    bindir = _hermetic_bindir(
        tmp_path,
        systemctl=_SYSTEMCTL_TMPL.format(log=systemctl_log, state="inactive"),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_PORT=str(_closed_port()),
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=15
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed >= 4.0, "the budget must actually be spent before degrading"
    assert "token=tok-stale" in _wait_for_nonempty(chromium_log)


def test_failed_start_skips_the_wait(tmp_path: Path) -> None:
    # start exiting non-zero (unit missing, masked, ...) is not a cold
    # start the launcher can wait out — proceed immediately.
    chromium_log = tmp_path / "chromium.log"
    systemctl_log = tmp_path / "systemctl.log"
    bindir = _hermetic_bindir(
        tmp_path,
        systemctl=_SYSTEMCTL_START_HOOK_TMPL.format(
            log=systemctl_log, state="inactive", start_hook=":", start_rc=1
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_PORT=str(_closed_port()),
    )

    start = time.monotonic()
    result = _run(env)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 3.0
    assert _wait_for_nonempty(chromium_log)


# --- SELF_LEARN_UI_MONITOR placement (feedback round 2 item 6; 09 §4.4) --
#
# Launcher-only, same X-1 posture as SELF_LEARN_UI_BROWSER. Set + hyprctl
# present: the window (fresh or existing) is ensured onto the named
# monitor via focuswindow-by-address THEN `movewindow mon:<name>` —
# skipped when clients -j/monitors -j already place it there. Unset =
# zero new dispatches; hyprctl absent or window-never-appears = silent
# degrade. The dispatches run in the script's foreground (only the
# browser launch is backgrounded), so hyprctl's log is complete once the
# subprocess returns — read it directly, no polling needed.

# A fake hyprctl answering all three placement reads — `clients -j`
# (the clients `monitor` field is a NUMERIC id), `monitors -j` (the
# id→name map), and `activewindow -j` (the F2 stale-address gate: the
# move only fires when OUR address holds focus).
_HYPRCTL_PLACEMENT_TMPL = """
echo "$*" >> "{log}"
if [[ "$1" == "clients" ]]; then
  echo '{clients_json}'
fi
if [[ "$1" == "monitors" ]]; then
  echo '{monitors_json}'
fi
if [[ "$1" == "activewindow" ]]; then
  echo '{active_json}'
fi
exit 0
"""

# A fake hyprctl whose window "appears" only AFTER the first clients
# query (flag file = the launch happened): the presence check sees [],
# the placement poll then finds the window — the real fresh-launch
# timeline. activewindow answers ours so the F2 gate passes.
_HYPRCTL_APPEARING_TMPL = """
echo "$*" >> "{log}"
if [[ "$1" == "clients" ]]; then
  if [[ -f "{flag}" ]]; then
    echo '{clients_json}'
  else
    : > "{flag}"  # builtin redirect — `touch` is not in the hermetic bin dir
    echo '[]'
  fi
fi
if [[ "$1" == "activewindow" ]]; then
  echo '{active_json}'
fi
exit 0
"""


def test_monitor_set_moves_existing_window_focus_then_move(
    tmp_path: Path,
) -> None:
    # Window present; the fake serves an EMPTY monitors -j map, so
    # current placement is unknown -> the script must move
    # unconditionally (idempotent), with focuswindow-by-address strictly
    # BEFORE movewindow (movewindow acts on the focused window).
    # activewindow answers OUR address, so the F2 gate passes.
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_PLACEMENT_TMPL.format(
            log=hyprctl_log,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front","monitor":0}]',
            monitors_json="[]",
            active_json='{"address":"0xAAA"}',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-2",
    )

    result = _run(env)

    assert result.returncode == 0
    log = hyprctl_log.read_text(encoding="utf-8")
    focus_at = log.index("dispatch focuswindow address:0xAAA")
    move_at = log.index("dispatch movewindow mon:DP-2")
    assert focus_at < move_at, "focus-by-address must precede the move"
    assert not chromium_log.exists() or chromium_log.stat().st_size == 0


def test_monitor_set_fresh_launch_polls_then_places(tmp_path: Path) -> None:
    # Fresh launch: presence check sees [], chromium launches, the ≤5 s
    # placement poll finds the new window on its first iteration and the
    # focus+move pair fires — fast (never burns the budget).
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_APPEARING_TMPL.format(
            log=hyprctl_log,
            flag=tmp_path / "window-appeared.flag",
            # honest hyprctl shape (delta F4): real clients rows always
            # carry a numeric `monitor` id; no monitors -j answer here,
            # so placement stays unknown -> move fires.
            clients_json='[{"class":"self-learn-ui","address":"0xF00","title":"self-learn — Front","monitor":0}]',
            active_json='{"address":"0xF00"}',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-2",
    )

    start = time.monotonic()
    result = _run(env)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 3.0, "window on first poll iteration must release fast"
    assert _wait_for_nonempty(chromium_log), "the launch must still happen"
    log = hyprctl_log.read_text(encoding="utf-8")
    focus_at = log.index("dispatch focuswindow address:0xF00")
    move_at = log.index("dispatch movewindow mon:DP-2")
    assert focus_at < move_at


def test_monitor_set_skips_move_when_already_on_target(tmp_path: Path) -> None:
    # The refinement: clients -j carries a NUMERIC monitor id (1); the
    # script maps it via monitors -j to "DP-2" == the target -> zero
    # placement dispatches (the step-3 focus still fires as always).
    # TWO-window fixture (delta F4): an unrelated window sits FIRST on a
    # NON-target monitor — a selector bug that read the first row's
    # monitor instead of OUR address's would resolve DP-1 and move.
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_PLACEMENT_TMPL.format(
            log=hyprctl_log,
            clients_json=(
                '[{"class":"kitty","address":"0xDEAD","title":"shell","monitor":0},'
                '{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front","monitor":1}]'
            ),
            monitors_json='[{"id":0,"name":"DP-1"},{"id":1,"name":"DP-2"}]',
            active_json='{"address":"0xAAA"}',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-2",
    )

    result = _run(env)

    assert result.returncode == 0
    log = hyprctl_log.read_text(encoding="utf-8")
    assert "dispatch focuswindow address:0xAAA" in log
    assert "movewindow" not in log, "already on target: zero move dispatches"


def test_stale_address_skips_move_of_unrelated_window(tmp_path: Path) -> None:
    # Delta F2: the window vanished between address resolve and focus —
    # activewindow -j reports a DIFFERENT address (the user's unrelated
    # window). The move must be skipped (an X-3-compliant JSON gate,
    # never an rc branch on the focus dispatch): moving would relocate
    # a window the user never asked us to touch.
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_PLACEMENT_TMPL.format(
            log=hyprctl_log,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front","monitor":0}]',
            monitors_json="[]",
            active_json='{"address":"0xBEEF"}',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-2",
    )

    result = _run(env)

    assert result.returncode == 0
    assert result.stderr == ""
    log = hyprctl_log.read_text(encoding="utf-8")
    assert "dispatch focuswindow address:0xAAA" in log
    assert "movewindow" not in log, "focus not ours: the move must not fire"


def test_non_json_hyprctl_output_degrades_to_launch(tmp_path: Path) -> None:
    # Delta F1 regression (the demonstrated rc-5 exit): hyprctl exits 0
    # but prints NON-JSON — jq exits 5 inside _ui_window_address, which
    # under set -e used to kill the launcher from within $() at the
    # presence check (and ×50 in the placement poll). The source-level
    # `|| true` makes garbage read as "no window": launch proceeds,
    # rc 0, and the placement poll gives up silently on its budget.
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(
            log=hyprctl_log, clients_json="not json at all"
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    # Monitor UNSET keeps this on the fast path: the presence check is
    # the exposure being pinned (the poll's ×50 exposure is the same
    # guarded call; the slow degrade path has its own test above).
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    result = _run(env)

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--class=self-learn-ui" in _wait_for_nonempty(chromium_log)


def test_monitor_set_window_never_appears_degrades_silently(
    tmp_path: Path,
) -> None:
    # Fresh launch whose window NEVER shows up in clients -j (browser
    # crashed, slow session, ...): the placement poll burns its ≤5 s
    # budget then gives up silently — launch still happened, rc 0, no
    # stderr, no movewindow. The one placement test allowed to be slow
    # (mirrors the readiness-timeout test's posture: the budget must
    # actually be spent, bounded by an explicit subprocess timeout).
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(log=hyprctl_log, clients_json="[]"),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-2",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=15
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert result.stderr == ""
    assert elapsed >= 4.0, "the placement budget must actually be spent"
    assert _wait_for_nonempty(chromium_log), "degrade never loses the launch"
    assert "movewindow" not in hyprctl_log.read_text(encoding="utf-8")


def test_place_fresh_window_deadline_is_wall_clock_not_iteration_count(
    tmp_path: Path,
) -> None:
    # Fold r2 / M-F2 MAJOR 1 (r2 gate): fold r1 replaced
    # _place_fresh_window's 50-ITERATION poll count with a `SECONDS`-based
    # wall-clock deadline (self-learn-ui-open ~:355-365), because each
    # iteration now costs up to `timeout 4` under C22 — 50 iterations at
    # ~4s each is ~205s, not the documented ~5s. The sibling test above
    # (test_monitor_set_window_never_appears_degrades_silently) cannot
    # tell the two designs apart: its hyprctl is INSTANT, so 50 iterations
    # x 0.1s sleep costs ~5s under EITHER design. This test makes every
    # iteration expensive with the SLEEPY hyprctl (each `clients -j` call
    # costs ~4s under the timeout wrap) and a window that never appears,
    # so the two designs diverge sharply.
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_SLEEPY_HYPRCTL_TMPL.format(log=hyprctl_log, sleep_s=4),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-2",
    )

    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 25.0, (
        f"took {elapsed:.1f}s — an iteration count at ~4s per (sleepy, "
        "timeout-wrapped) hyprctl call is ~205s; only a wall-clock "
        "deadline bounds _place_fresh_window's poll loop this tightly"
    )
    assert _wait_for_nonempty(chromium_log), "degrade never loses the launch"


def test_monitor_unset_never_dispatches_movewindow(tmp_path: Path) -> None:
    # Unset = today's behavior exactly: focus the existing window, zero
    # placement dispatches, zero placement polling (fast path stays fast).
    hyprctl_log = tmp_path / "hyprctl.log"
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path,
        hyprctl=_HYPRCTL_BODY_TMPL.format(
            log=hyprctl_log,
            clients_json='[{"class":"self-learn-ui","address":"0xAAA","title":"self-learn — Front"}]',
        ),
        chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log),
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(tmp_path, bindir, XDG_RUNTIME_DIR=str(runtime_dir))

    start = time.monotonic()
    result = _run(env)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 3.0, "no monitor var -> no placement poll"
    log = hyprctl_log.read_text(encoding="utf-8")
    assert "dispatch focuswindow address:0xAAA" in log
    assert "movewindow" not in log


def test_hyprctl_absent_with_monitor_set_still_launches(tmp_path: Path) -> None:
    # hyprctl absent entirely: placement is skipped silently along with
    # detection — the browser still launches, rc 0, no stderr.
    chromium_log = tmp_path / "chromium.log"
    bindir = _hermetic_bindir(
        tmp_path, chromium=_LOGGING_LAUNCH_TMPL.format(log=chromium_log)
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = _env(
        tmp_path,
        bindir,
        XDG_RUNTIME_DIR=str(runtime_dir),
        SELF_LEARN_UI_MONITOR="DP-2",
    )

    start = time.monotonic()
    result = _run(env)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert result.stderr == ""
    assert elapsed < 3.0, "no hyprctl -> no placement poll either"
    assert "--class=self-learn-ui" in _wait_for_nonempty(chromium_log)
