"""Tests added by the 2026-07-15 testing-regime audit (static reviewer +
mutation prober). Each test here exists because a specific planted bug
survived the suite or a specific documented claim had no test:

- capture-rate formula was unasserted (mutation o survived)
- spool locking was untested narrative (mutation k survived; no test
  observed flock, no test exercised concurrency)
- analyst timeout was undetectable when removed
- teach --route's never-lost promise was tested for only the analyst
  door, not the route-failure door
- route_direct's duplicate-id guard was untested
- spool_quiet's "telemetry never breaks the verb" was untested
- the crash-window recovery claim in verbs.py was an untested docstring
- the two shell suites (sentinel-test.sh, install-commands-test.sh) were
  orphaned — nothing ran them
- the chezmoi flow ended at a shim everywhere; real-binary round trip
  now runs where chezmoi is installed
"""

import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from self_learn import cli, telemetry, verbs
from self_learn.analyst import doctrine_path
from self_learn.compilers import BEGIN_MARKER, compile_managed_file
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env, proposal_dict

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = Path(__file__).resolve().parents[1] / "src"

SKILL_MD = "# s skill\n\nAuthored prose stays put.\n"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


class Env:
    """doc-13 pair: `home` is the LEDGER; `bucket` its skill:s bucket;
    canon (skill_md) lives in the paired HOST repo (make_env seeds it with
    the same content as SKILL_MD)."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir  # HOST skill dir
        self.skill_md = sandbox.skill_md
        self.bucket = self.home / "skills" / "s"  # LEDGER skill bucket
        self.bare = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.bare)],
            check=True,
        )
        git(self.home, "remote", "add", "origin", str(self.bare))
        git(self.home, "push", "-q", "-u", "origin", "main")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


# ------------------------------------------------- capture-rate arithmetic


def test_capture_rate_ceiling_value_is_right_way_up(env, capsys):
    """Mutation o (captures/declined swapped) survived: the labels were
    asserted, the NUMBER never was. 1 capture + 3 logged declines must
    yield a ceiling of 0.25 — the swapped formula yields 0.75."""
    telemetry.spool_event("capture", source="teach", record="lrn-0000aaaa")
    for _ in range(3):
        telemetry.spool_event("offer-declined", reason="later")
    telemetry.flush(env.home)
    rc = cli.main(["report", "--json"])
    assert rc == 0
    facts = json.loads(capsys.readouterr().out)
    t = facts["telemetry"]
    assert t["captures"] == 1
    assert t["declined_logged"] == 3
    assert t["capture_rate_ceiling"] == 0.25


def test_report_counts_each_terminal_status(env, capsys):
    """report.py's status-counting branches were its largest untested
    region (82% coverage): seed one record per outcome and assert the
    aggregate numbers, not just the labels."""
    for rid, args in [
        ("lrn-0000aaaa", ["route", "lrn-0000aaaa"]),
        ("lrn-0000bbbb", ["reject", "lrn-0000bbbb"]),
        ("lrn-0000cccc", ["graduate", "lrn-0000cccc"]),
        ("lrn-0000dddd", ["defer", "lrn-0000dddd", "--until", "2026-01-01"]),
    ]:
        create_record(env.home, make_behavior(record_id=rid))
        write_proposal(env.home, rid, proposal_dict())
        commit_all(env.home, f"pending {rid}")
        assert cli.main(args) == 0
    capsys.readouterr()
    assert cli.main(["report", "--json"]) == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts["routed_ever"] == 1
    assert facts["rejected"] == 1
    assert facts["graduated"] == 1
    assert len(facts["deferred"]) == 1
    # the 2026-01-01 deferral is past due — overdue must be positive
    assert facts["deferred"][0]["overdue_days"] > 0


# --------------------------------------------------------- spool locking


def test_spool_event_holds_exclusive_lock_around_write(monkeypatch, tmp_path):
    """Mutation k (flock removed) survived: nothing observed locking.
    Record the flock ops around a spool append: LOCK_EX before the
    write, LOCK_UN after."""
    calls: list[int] = []
    real_flock = fcntl.flock

    def recording_flock(fd, op):
        calls.append(op)
        real_flock(fd, op)

    monkeypatch.setattr(telemetry.fcntl, "flock", recording_flock)
    telemetry.spool_event("offer-made")
    assert calls[0] == fcntl.LOCK_EX
    assert calls[-1] == fcntl.LOCK_UN


def test_flush_locks_spool_and_target(monkeypatch, tmp_path, env):
    calls: list[int] = []
    real_flock = fcntl.flock

    def recording_flock(fd, op):
        calls.append(op)
        real_flock(fd, op)

    telemetry.spool_event("offer-made")
    monkeypatch.setattr(telemetry.fcntl, "flock", recording_flock)
    telemetry.flush(env.home)
    # at least two exclusive locks: the spool file and the tracked target
    assert calls.count(fcntl.LOCK_EX) >= 2
    assert calls[-1] == fcntl.LOCK_UN


def test_concurrent_spool_appends_from_processes_all_parse(env):
    """The system's own design scenario: several processes appending to
    ONE spool file (same actor, same month). Every event must land as
    its own parseable line — no tearing, no loss."""
    procs_n, events_n = 4, 50
    code = (
        "from self_learn import telemetry\n"
        f"for _ in range({events_n}):\n"
        "    telemetry.spool_event('offer-made')\n"
    )
    child_env = dict(os.environ, PYTHONPATH=str(SRC_DIR))
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(procs_n)
    ]
    for p in procs:
        _out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode()
    spool_files = list(telemetry.spool_dir().glob("*.jsonl"))
    assert len(spool_files) == 1  # same actor + month → one file
    lines = spool_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == procs_n * events_n
    for line in lines:
        assert json.loads(line)["kind"] == "offer-made"


# --------------------------------------- teach --route: the never-lost doors


DOCTRINE_TEXT = "# Routing doctrine\n\nNarrowest surface wins.\n"

TEACH_ROUTE_ARGS = [
    "teach",
    "--skill",
    "s",
    "--type",
    "behavior",
    "--kind",
    "anti-pattern",
    "--trigger",
    "About to edit .storage while HA is running.",
    "--instruction",
    "Stop the container first.",
    "--route",
]


def _install_doctrine(env):
    # doc 13 T-H3: the routing doctrine ships PACKAGE-relative (beside the
    # skill), not in any ledger home — it is always present, so nothing to
    # install. Assert the invariant instead of writing a home copy.
    assert doctrine_path().is_file()


def test_analyst_timeout_captures_to_pending(env, tmp_path, monkeypatch, capsys):
    """A wedged `claude -p` must not hang teach --route forever: the
    timeout fires, the record lands in pending, exit 4."""
    _install_doctrine(env)
    shims = tmp_path / "shims"
    shims.mkdir()
    shim = shims / "claude"
    shim.write_text("#!/usr/bin/env bash\nsleep 30\n", encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
    # U-cleanup-A: point the sdk transport straight at this test's own
    # `sleep 30` shim so `cli_path` is never `None` -- otherwise the
    # analyst (sdk by default post-AG3) would hit `_find_cli()`'s
    # real-binary fallback and trip `_no_real_sdk_spawn_tripwire`
    # instead of exercising the real subject under test.
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(shim))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv("SELF_LEARN_ANALYST_TIMEOUT", "0.3")

    rc = cli.main(TEACH_ROUTE_ARGS)
    assert rc == 4
    err = capsys.readouterr().err
    assert "timed out" in err
    pending = list((env.bucket / "pending").glob("lrn-*.md"))
    assert len(pending) == 1  # never lost


def test_route_failure_door_captures_to_pending(env, capsys):
    """The OTHER never-lost door: analyst fine (deterministic --dest),
    but the route itself refuses (dirty compile target). Record must
    land in pending with exit 4, and the capture event must be spooled
    (the numerator stays exactly counted)."""
    env.skill_md.write_text(SKILL_MD + "\nuncommitted drift\n", encoding="utf-8")
    rc = cli.main(TEACH_ROUTE_ARGS + ["--dest", "skill-md"])
    assert rc == 4
    err = capsys.readouterr().err
    assert "captured to pending" in err
    pending = list((env.bucket / "pending").glob("lrn-*.md"))
    assert len(pending) == 1
    # teach is a flushing verb, so by exit the event is in the TRACKED
    # plane, not the spool.
    events = telemetry.read_events(env.home)
    assert any(e["kind"] == "capture" for e in events)


def test_route_direct_duplicate_id_refused(env):
    rid = "lrn-0000aaaa"
    create_record(env.home, make_behavior(record_id=rid))
    commit_all(env.home, "pending")
    dupe = make_behavior(record_id=rid)
    with pytest.raises(verbs.VerbError, match="already exists"):
        verbs.route_direct(env.home, dupe, dest="skill-md", no_push=True)


# ------------------------------------------------ telemetry never breaks verbs


def test_spool_quiet_failure_never_breaks_teach(env, tmp_path, capsys):
    """Cache unwritable (the spool_quiet swallow path): teach must still
    capture and exit 0, with a loud stderr warning."""
    cache_root = tmp_path / "xdg-cache"
    cache_root.mkdir(exist_ok=True)
    os.chmod(cache_root, 0o555)
    try:
        rc = cli.main(
            ["teach", "--skill", "s", "--type", "knowledge", "--fact", "A fact."]
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "telemetry spool failed" in captured.err
        pending = list(
            (env.bucket / "pending").glob("lrn-*.md")
        )
        assert len(pending) == 1
    finally:
        os.chmod(cache_root, 0o755)


# ------------------------------------------------- crash-window recovery


def test_route_crash_window_recovery_is_two_step(env, capsys):
    """Documented claim check (verbs.py route-ordering note): a crash
    between compile and ledger op leaves the target compiled but the
    record pending. The honest recovery: the re-run REFUSES on the dirty
    target; committing the half-applied target and re-running succeeds,
    and the idempotent re-compile leaves the content identical."""
    rid = "lrn-0000aaaa"
    record = make_behavior(record_id=rid)
    create_record(env.home, record)
    write_proposal(env.home, rid, proposal_dict())
    commit_all(env.home, "pending")

    # Simulate the crashed first run: compile landed, ledger op did not.
    shadow = Record.from_path(
        env.bucket / "pending" / f"{rid}.md"
    )
    shadow.set_routing(
        {"routed_at": "2026-07-15T00:00:00Z", "destination": "skill-md", "by": "human"}
    )
    shadow.set_status("routed")
    compile_managed_file(env.skill_md, [shadow])
    assert BEGIN_MARKER in env.skill_md.read_text(encoding="utf-8")

    # Step 1: re-run refuses — the target is dirty.
    rc = cli.main(["route", rid])
    assert rc == 1
    assert "commit/stash first" in capsys.readouterr().err

    # Step 2: commit the half-applied target, re-run: succeeds, content
    # identical (regeneration idempotent), record resolved. The target
    # lives in the HOST repo now (doc 13 §4), so commit there.
    commit_all(env.host, "half-applied compile from crashed run")
    before = env.skill_md.read_text(encoding="utf-8")
    assert cli.main(["route", rid]) == 0
    assert env.skill_md.read_text(encoding="utf-8") == before
    assert (env.bucket / "resolved" / f"{rid}.md").is_file()


# ------------------------------------------------------- shell-suite wrappers


SENTINEL_SH = REPO_ROOT / "tests" / "sentinel-test.sh"
INSTALL_SH = Path(__file__).resolve().parent / "install-commands-test.sh"


@pytest.mark.skipif(not SENTINEL_SH.is_file(), reason="repo-root suite absent")
def test_sentinel_shell_suite_runs():
    """sentinel-test.sh proves the autosync SIDE of the sentinel contract
    (the sync script pausing on a fresh sentinel). It was orphaned — no
    runner invoked it. It self-sandboxes (mktemp + redirected XDG)."""
    proc = subprocess.run(
        ["bash", str(SENTINEL_SH)], capture_output=True, text=True, timeout=180
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all 3 cases pass" in proc.stdout


@pytest.mark.skipif(not INSTALL_SH.is_file(), reason="script absent")
def test_install_commands_shell_suite_runs():
    """install-commands-test.sh runs the real install.sh against a fake
    HOME (systemctl/uv shimmed). Also previously orphaned."""
    proc = subprocess.run(
        ["bash", str(INSTALL_SH)], capture_output=True, text=True, timeout=180
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(not INSTALL_SH.is_file(), reason="script absent")
def test_install_commands_shell_suite_xdg_config_home_positive_control(tmp_path):
    """`install-commands-test.sh`'s own header claims it touches nothing
    outside its fake `$HOME` -- that claim went false the moment
    `install.sh`'s `UNIT_DIR` started honoring `$XDG_CONFIG_HOME`
    (U-servehermetic, this same unit): the script's `run_install` only
    pinned `HOME`, so a CALLER's own `XDG_CONFIG_HOME` leaked straight
    through `bash "$INSTALL"` and install.sh linked all four systemd
    units under that real/external directory instead of under the fake
    home -- invisible to every check inside the script (all scoped to
    `$FAKE_HOME`) and never cleaned by its own trap (which only removes
    its internal `$TMP`). Measured before the fix: the script's own PASS
    line and a zero exit, plus four stray symlinks left under the
    external directory.

    This test drives the scenario for real: an EXTERNAL `XDG_CONFIG_HOME`
    (this test's own `tmp_path`, standing in for whatever the invoking
    shell happens to have set) is exported into the subprocess env, the
    script still reports its own internal pass line (its fake-`HOME`
    checks are unaffected), and the external directory must stay
    completely empty afterward -- nothing must land there.

    MUTATION that turns this red: drop the `XDG_CONFIG_HOME="$FAKE_HOME/
    .config"` pin from `run_install` in `install-commands-test.sh` -- the
    external `tmp_path` then gains a `systemd/user/` subdirectory holding
    the four unit symlinks."""
    external_xdg_config_home = tmp_path / "external-xdg-config"
    external_xdg_config_home.mkdir()
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(external_xdg_config_home)

    proc = subprocess.run(
        ["bash", str(INSTALL_SH)], capture_output=True, text=True, timeout=180, env=env
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "commands surface" in proc.stdout

    leaked = list(external_xdg_config_home.rglob("*"))
    assert leaked == [], (
        f"install-commands-test.sh leaked into the external XDG_CONFIG_HOME: {leaked}"
    )


# ---------------------------------------------------- real-chezmoi round trip


@pytest.mark.skipif(shutil.which("chezmoi") is None, reason="chezmoi not installed")
def test_real_chezmoi_round_trip(tmp_path):
    """The chezmoi leg previously ended at an argv-logging shim in every
    test. Where the real binary exists, run the full guarded sequence
    against a sandboxed source/destination/config — real diff semantics,
    real re-add, real git commit+push — and assert the round trip."""
    sandbox = tmp_path / "cz"
    src = sandbox / "source"
    dst = sandbox / "dest"
    cfg = sandbox / "config"
    data = sandbox / "data"
    bare = sandbox / "dotfiles.git"
    for d in (src, dst / ".claude", cfg, data):
        d.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
    )

    # Source repo manages .claude/CLAUDE.md
    (src / "dot_claude").mkdir()
    base = "# CLAUDE.md\n\nHuman prose.\n"
    (src / "dot_claude" / "CLAUDE.md").write_text(base, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    git(src, "config", "user.email", "t@local")
    git(src, "config", "user.name", "t")
    git(src, "remote", "add", "origin", str(bare))
    commit_all(src, "dotfiles seed")
    git(src, "push", "-q", "-u", "origin", "main")

    # Wrapper: real chezmoi, fully sandboxed (source/dest/config/state).
    wrapper = sandbox / "chezmoi-sandboxed"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f'export XDG_CONFIG_HOME="{cfg}"\n'
        f'export XDG_DATA_HOME="{data}"\n'
        f'exec chezmoi --source "{src}" --destination "{dst}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)

    subprocess.run([str(wrapper), "apply", "--force"], check=True)
    target = dst / ".claude" / "CLAUDE.md"
    assert target.read_text(encoding="utf-8") == base

    from self_learn.chezmoi import compile_user_scope

    record = make_behavior(scope="user")
    record.set_routing(
        {"routed_at": "2026-07-15T00:00:00Z", "destination": "claude-md", "by": "human"}
    )
    record.set_status("routed")
    result = compile_user_scope(
        target, [record], chezmoi=str(wrapper), commit_message="test: managed section"
    )
    assert result.committed is True

    # Round trip: target edited, folded into source, committed, pushed,
    # and no drift remains.
    assert BEGIN_MARKER in target.read_text(encoding="utf-8")
    assert BEGIN_MARKER in (src / "dot_claude" / "CLAUDE.md").read_text(
        encoding="utf-8"
    )
    assert git(src, "log", "-1", "--format=%s").stdout.strip() == "test: managed section"
    remote_head = subprocess.run(
        ["git", "-C", str(bare), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert remote_head == "test: managed section"
    diff = subprocess.run(
        [str(wrapper), "diff", str(target)], capture_output=True, text=True, check=True
    )
    assert diff.stdout.strip() == ""
