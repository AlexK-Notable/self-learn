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

_LOGGING_LAUNCH_TMPL = """
echo "$*" >> "{log}"
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
            log=hyprctl_log, clients_json='[{"class":"self-learn-ui"}]'
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
    assert "dispatch focuswindow class:self-learn-ui" in hyprctl_content
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

    result = _run(env)

    assert result.returncode == 0
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
        systemctl=_LOGGING_LAUNCH_TMPL.format(log=systemctl_log),
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
