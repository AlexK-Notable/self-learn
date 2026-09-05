"""M-U/D5 -- install.sh: real dry-run, collision-proof backups with
rollback, bounded external commands, and the legacy miner units opt-in.

Every test here drives the REAL repo copy of `install.sh` as a
subprocess against a throwaway fake `$HOME` under `tmp_path` -- NEVER
the real `$HOME` (`~/.self-learn` is the user's live ledger; this file
never reads or writes it, and never runs a real `systemctl`). PATH is
built from SCRATCH for every subprocess: a shim directory (logging
fakes of `systemctl`/`uv`/`update-desktop-database`, plus test-specific
fakes of `date`/`ln` where a test needs one) ahead of a curated
real-binary directory (`bash`, `mkdir`, `mv`, `ln`, `date`, `readlink`,
`sed`, `timeout`, `cat`) -- never the ambient PATH, so a test's tool
surface is exactly what it claims.

Harness SHAPE copied from `test_serve.py`'s
`_run_install_sh_with_logging_shim` (PORT2) -- not imported: that file
is owned by another concern and stays unedited by this unit. The two
harnesses independently agree that `install.sh` never runs a real
`enable`/`disable`, which is exactly the property `test_serve.py`'s own
PORT2 tests keep proving from the OUTSIDE.

Letter labels below (a)-(i) match the build brief's targeted-behavior
list one-to-one, plus a negative control this file owns for itself
(PORT2's own negative control lives in test_serve.py and is not
duplicated here)."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
INSTALL_SH = REPO_ROOT / "install.sh"

_REAL_BIN_NAMES = (
    "bash",
    "dirname",
    "mkdir",
    "mv",
    "ln",
    "date",
    "readlink",
    "sed",
    "timeout",
    "cat",
)

_DEFAULT_SYSTEMCTL_BODY = (
    'echo "$@" >> "$SYSTEMCTL_LOG"\n'
    'for a in "$@"; do\n'
    '  if [ "$a" = "is-enabled" ]; then\n'
    '    if [ "${SYSTEMCTL_IS_ENABLED_OUTPUT:-}" = "enabled" ]; then\n'
    '      echo "enabled"; exit 0\n'
    "    else\n"
    '      echo "disabled"; exit 1\n'
    "    fi\n"
    "  fi\n"
    "done\n"
    "exit 0\n"
)


def _real_bin_dir(tmp_path: Path) -> Path:
    """A directory of symlinks to the small, named set of REAL binaries
    install.sh's own execution needs (bash, mkdir, mv, ln, date,
    readlink, sed, timeout, cat) -- never a bare inherited PATH, so a
    test's tool surface is exactly what it claims and nothing more."""
    d = tmp_path / "real-bin"
    d.mkdir()
    for name in _REAL_BIN_NAMES:
        real = shutil.which(name)
        assert real, f"{name} must be resolvable on this host to build the harness"
        (d / name).symlink_to(real)
    return d


def _write_shim(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}", encoding="utf-8")
    path.chmod(0o755)


def _install_env(
    tmp_path: Path,
    *,
    home_name: str = "home",
    shim_overrides: dict[str, str] | None = None,
    omit_timeout: bool = False,
    xdg_config_home: str | None = None,
) -> tuple[dict[str, str], Path, Path]:
    """Builds one fully hermetic subprocess env for an install.sh run.
    Returns (env, fake_home, systemctl_log). No variable is inherited
    from the pytest process's own environment -- PATH is built
    entirely from a shim dir (systemctl/uv/update-desktop-database
    always present; `shim_overrides` replaces/adds to that set, e.g.
    a controlled `date` or `ln`) ahead of `_real_bin_dir`."""
    shims = tmp_path / "shims"
    shims.mkdir(exist_ok=True)
    systemctl_log = tmp_path / "systemctl.calls.log"
    systemctl_log.touch()

    bodies = {
        "systemctl": _DEFAULT_SYSTEMCTL_BODY,
        "uv": "exit 0\n",
        "update-desktop-database": "exit 0\n",
    }
    if shim_overrides:
        bodies.update(shim_overrides)
    for name, body in bodies.items():
        _write_shim(shims / name, body)

    real_bin = _real_bin_dir(tmp_path)
    if omit_timeout:
        (real_bin / "timeout").unlink()

    fake_home = tmp_path / home_name
    fake_home.mkdir(parents=True, exist_ok=True)

    env = {
        "HOME": str(fake_home),
        "PATH": f"{shims}:{real_bin}",
        "SYSTEMCTL_LOG": str(systemctl_log),
        "XDG_CONFIG_HOME": xdg_config_home or str(fake_home / ".config"),
    }
    return env, fake_home, systemctl_log


def _run(
    args: list[str], env: dict[str, str], *, trace: bool = False, timeout: int = 60
) -> subprocess.CompletedProcess:
    cmd = ["bash"]
    if trace:
        cmd.append("-x")
    cmd += [str(INSTALL_SH), *args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _snapshot(home: Path) -> str:
    """A sorted `find $home -printf '%p %y %l\\n'` -- name, type, and
    (for a symlink) target, so a re-point counts as a change too."""
    result = subprocess.run(
        ["find", str(home), "-printf", "%p %y %l\n"],
        capture_output=True,
        text=True,
        check=True,
    )
    return "\n".join(sorted(result.stdout.splitlines()))


# ------------------------------------------------------------------- (a)


def test_a_dry_run_leaves_a_nonempty_apostrophe_home_byte_identical(tmp_path):
    """`--dry-run` must touch NOTHING, proven against a NONEMPTY home
    whose path itself contains an apostrophe -- the exact character
    that broke the old `run() { eval "$*"; }` idiom when a raw value
    was hand-wrapped in single quotes (`'$dst'`) instead of shell-quoted
    via `printf %q`. The positive control (a real run afterward, same
    home) proves the comparison mechanism is not vacuously
    always-equal."""
    env, fake_home, _log = _install_env(tmp_path, home_name="ali's home")
    (fake_home / ".claude" / "skills").mkdir(parents=True)
    (fake_home / ".claude" / "skills" / "self-learn").write_text("old stub\n")
    (fake_home / "unrelated.txt").write_text("leave me alone\n")

    before = _snapshot(fake_home)
    result = _run(["--dry-run"], env)
    assert result.returncode == 0, (result.stdout, result.stderr)
    after = _snapshot(fake_home)
    assert before == after, "--dry-run touched the filesystem"

    result2 = _run([], env)
    assert result2.returncode == 0, (result2.stdout, result2.stderr)
    after_real = _snapshot(fake_home)
    assert before != after_real, (
        "positive control failed -- a real run left the tree unchanged too, "
        "so the identity check above proves nothing"
    )


# ------------------------------------------------------------------- (b)


def test_b_same_nanosecond_backup_collision_aborts_and_leaves_dst_untouched(tmp_path):
    """`date +%s%N` shimmed to a FIXED value simulates the same-
    nanosecond collision the old code silently no-op'd through (`mv -n`
    declining to clobber an existing backup path, then `ln -sfn`
    nesting into -- or clobbering -- $dst). The fixed script must abort,
    name the exact colliding path, and leave both $dst and the
    pre-existing backup untouched."""
    real_date = shutil.which("date")
    assert real_date
    date_body = (
        'if [ "$1" = "+%s%N" ]; then echo "1234567890123456789"; exit 0; fi\n'
        f"exec {shlex.quote(real_date)} \"$@\"\n"
    )
    env, fake_home, _log = _install_env(tmp_path, shim_overrides={"date": date_body})

    skills = fake_home / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "self-learn").write_text("original\n")
    (skills / "self-learn.bak.1234567890123456789").write_text("pre-existing collision\n")

    result = _run([], env)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "self-learn.bak.1234567890123456789" in result.stderr
    assert (skills / "self-learn").read_text() == "original\n"
    assert (skills / "self-learn.bak.1234567890123456789").read_text() == (
        "pre-existing collision\n"
    )


# ------------------------------------------------------------------- (c)


def test_c_ln_failure_after_backup_restores_it_and_aborts(tmp_path):
    """`ln` shimmed to fail for exactly one destination (everything else
    still runs the real `ln`): the backup that already happened for
    that destination must be moved BACK, the script must exit non-zero,
    and no backup file may be left lying around."""
    # Computed BEFORE the one _install_env call below (a second call
    # would crash on `_real_bin_dir`'s bare `mkdir()` re-running against
    # an already-populated directory) -- "home" is `_install_env`'s own
    # default `home_name`.
    fail_target = str(tmp_path / "home" / ".claude" / "skills" / "self-learn")
    real_ln = shutil.which("ln")
    assert real_ln
    ln_body = (
        'for a in "$@"; do\n'
        f"  if [ \"$a\" = {shlex.quote(fail_target)} ]; then\n"
        '    echo "ln: simulated failure" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "done\n"
        f"exec {shlex.quote(real_ln)} \"$@\"\n"
    )
    env, fake_home, _log = _install_env(tmp_path, shim_overrides={"ln": ln_body})
    skills = fake_home / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "self-learn").write_text("original content\n")

    result = _run([], env)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "simulated failure" in result.stderr
    assert "restored" in result.stderr

    dst = skills / "self-learn"
    assert not dst.is_symlink(), "the failed ln must not have left a symlink behind"
    assert dst.read_text() == "original content\n"
    assert list(skills.glob("self-learn.bak.*")) == [], "a backup was left behind after restore"


# ------------------------------------------------------------------- (d)


def test_d_real_directory_at_skills_dir_is_backed_up_not_nested(tmp_path):
    """A REAL (non-symlink) directory sitting at the skill's link target
    must be moved aside intact and the symlink placed in its stead --
    never `ln -sfn` nesting a new link INSIDE the old directory (the
    GNU `ln` behavior a same-second backup collision used to trigger)."""
    env, fake_home, _log = _install_env(tmp_path)
    skill_dir = fake_home / ".claude" / "skills" / "self-learn"
    skill_dir.mkdir(parents=True)
    (skill_dir / "OLDMARKER").write_text("legacy content\n")

    result = _run([], env)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert skill_dir.is_symlink(), "self-learn must now be the live symlink"
    assert skill_dir.resolve() == (
        REPO_ROOT / "plugins" / "self-learn" / "skills" / "self-learn"
    ).resolve()

    backups = list((fake_home / ".claude" / "skills").glob("self-learn.bak.*"))
    assert len(backups) == 1, backups
    assert backups[0].is_dir() and not backups[0].is_symlink()
    assert (backups[0] / "OLDMARKER").read_text() == "legacy content\n"


# ------------------------------------------------------------------- (e)


def test_e_legacy_miner_flag_links_units_and_its_absence_does_not(tmp_path):
    env, fake_home, _log = _install_env(tmp_path)
    unit_dir = Path(env["XDG_CONFIG_HOME"]) / "systemd" / "user"

    result = _run([], env)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert not (unit_dir / "self-learn-miner.service").exists()
    assert not (unit_dir / "self-learn-miner.timer").exists()
    assert "skipped (opt-in)" in result.stdout

    result2 = _run(["--legacy-miner"], env)
    assert result2.returncode == 0, (result2.stdout, result2.stderr)
    assert (unit_dir / "self-learn-miner.service").is_symlink()
    assert (unit_dir / "self-learn-miner.timer").is_symlink()
    assert (unit_dir / "self-learn-miner.service").resolve() == (
        REPO_ROOT / "systemd" / "self-learn-miner.service"
    ).resolve()
    assert (unit_dir / "self-learn-miner.timer").resolve() == (
        REPO_ROOT / "systemd" / "self-learn-miner.timer"
    ).resolve()

    # A third run WITHOUT the flag must leave the just-linked units alone
    # and say so, never silently drop them.
    result3 = _run([], env)
    assert result3.returncode == 0, (result3.stdout, result3.stderr)
    assert "left alone" in result3.stdout
    assert (unit_dir / "self-learn-miner.service").is_symlink()
    assert (unit_dir / "self-learn-miner.timer").is_symlink()


# ------------------------------------------------------------------- (f)


def test_f_is_enabled_enabled_prints_disable_command_never_calls_enable_or_disable(
    tmp_path,
):
    """Once a self-learn-miner.timer symlink exists, install.sh queries
    `systemctl --user is-enabled` (bounded, read-only) and -- if it
    reports "enabled" -- prints the exact disable command for the human.
    Token-exact check (not substring): "is-enabled" legitimately
    contains "enable" as a substring, so the log is checked by SPLIT
    WORDS, proving neither a real `enable` nor a real `disable` verb was
    ever invoked."""
    env, fake_home, log = _install_env(tmp_path)
    result1 = _run(["--legacy-miner"], env)
    assert result1.returncode == 0, (result1.stdout, result1.stderr)

    env2 = dict(env)
    env2["SYSTEMCTL_IS_ENABLED_OUTPUT"] = "enabled"
    log.write_text("")  # isolate the assertion window to this second run
    result2 = _run([], env2)
    assert result2.returncode == 0, (result2.stdout, result2.stderr)
    assert "systemctl --user disable --now self-learn-miner.timer" in result2.stdout

    calls = [line.split() for line in log.read_text().splitlines() if line.strip()]
    assert calls, "systemctl was never invoked in the second run -- is-enabled should have fired"
    for tokens in calls:
        assert "enable" not in tokens, calls
        assert "disable" not in tokens, calls


def test_negative_control_a_real_enable_call_would_be_caught(tmp_path):
    """Proves the exact-token check just above is not vacuous: mutate a
    COPY of install.sh (same technique as test_serve.py's own PORT2
    negative control) so it actually runs `systemctl --user enable
    --now self-learn-host.service`, and confirm the token check would
    flag it. This file's own copy of that control, as required --
    PORT2's copy in test_serve.py is not duplicated here."""
    env, fake_home, log = _install_env(tmp_path)
    text = INSTALL_SH.read_text(encoding="utf-8")

    repo_anchor = 'REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"'
    assert repo_anchor in text
    text = text.replace(repo_anchor, f"REPO={shlex.quote(str(REPO_ROOT))}", 1)

    anchor = 'say "  enable with: systemctl --user enable --now self-learn-host.service"'
    assert anchor in text, "install.sh's host-unit block shape changed -- update this mutation"
    text = text.replace(
        anchor,
        anchor + "\nsystemctl --user enable --now self-learn-host.service",
        1,
    )
    mutated = tmp_path / "install-mutated.sh"
    mutated.write_text(text, encoding="utf-8")

    result = subprocess.run(
        ["bash", str(mutated)], env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    calls = [line.split() for line in log.read_text().splitlines() if line.strip()]
    assert any("enable" in tokens for tokens in calls), (
        "the mutated install.sh should have actually invoked `enable` -- "
        "this negative control itself is broken if it did not"
    )


# ------------------------------------------------------------------- (g)


def test_g_every_external_command_is_timeout_wrapped(tmp_path):
    """A `bash -x` trace names the literal command line as it was
    invoked -- checked here for every bound external command install.sh
    runs: `uv sync`, every `systemctl --user daemon-reload`,
    `update-desktop-database`, and (with a linked miner timer, via
    --legacy-miner) `systemctl --user is-enabled`."""
    env, fake_home, _log = _install_env(tmp_path)
    result = _run(["--legacy-miner"], env, trace=True)
    assert result.returncode == 0, (result.stdout, result.stderr)
    trace = result.stderr
    assert "timeout 60 uv sync" in trace, trace
    assert "timeout 10 systemctl --user daemon-reload" in trace, trace
    assert "timeout 10 update-desktop-database" in trace, trace
    assert "timeout 5 systemctl --user is-enabled self-learn-miner.timer" in trace, trace


# ------------------------------------------------------------------- (h)


def test_h_unknown_flag_is_rejected_with_usage_error(tmp_path):
    env, _fake_home, _log = _install_env(tmp_path)
    result = _run(["--bogus-flag"], env)
    assert result.returncode == 64, (result.stdout, result.stderr)
    assert "Usage: install.sh" in result.stderr


def test_help_flag_prints_usage_and_exits_zero(tmp_path):
    """Positive control for (h): --help is a KNOWN flag, must exit 0,
    and must never require any of the shimmed tools (systemctl/uv) to
    even be reachable -- proven by a bare env that intentionally leaves
    both out, so this test would fail loudly if --help tried to run
    anything beyond printing usage."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "Usage: install.sh" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--legacy-miner" in result.stdout


# ------------------------------------------------------------------- (i)


def test_i_missing_timeout_on_path_refuses_to_start(tmp_path):
    env, _fake_home, _log = _install_env(tmp_path, omit_timeout=True)
    result = _run([], env)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "'timeout'" in result.stderr
    assert "not found on PATH" in result.stderr
