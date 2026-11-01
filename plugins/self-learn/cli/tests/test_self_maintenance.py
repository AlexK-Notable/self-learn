"""L6 (2026-10-31 interventions survey; decisions.md 8): self-maintenance of
the host process and of the compile records.

1. `serve` re-executes itself on new code between jobs, never mid-job, and
   never onto code that does not import (13 §5).
2. A host unit file that changed after the process started leaves a project
   notice naming the reload and restart, cleared once the service restarted.
3. A daily maintenance job recompiles the targets that carry self-learn's
   markers with no compile record, and `--selftest` stops telling a person
   to run `recompile` while it runs.
4. `recompile` stops warning about a retired lesson whose target is gone
   from disk (13 §4 item 2), and still removes a retired line where the
   target exists.
5. `overseer.hook_activation` is a registered setting: `doctor settings`
   no longer warns about it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from self_learn import (
    compiled,
    config,
    maintenance,
    notices,
    report,
    selfcheck,
    serve,
    settings,
    skill_registry,
    verbs,
)
from self_learn.hosts import host_add, host_remove
from self_learn.ledger_ops import create_record
from support import git, init_repo, make_behavior, make_env

_SRC_DIR = Path(serve.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    # A test run under a systemd unit (the test budget's slice) carries
    # INVOCATION_ID; the unit-file check reads it, so every test starts
    # without it and the one that wants it sets it.
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv("SELF_LEARN_SERVE_STARTED_AT", raising=False)
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)


class _Execed(BaseException):
    """Raised by the stubbed exec, so it leaves `run_forever` the way a real
    exec leaves it: nothing after it runs."""


def _code_tree(tmp_path: Path) -> Path:
    """A stand-in package: a git checkout with two committed source files."""
    root = tmp_path / "checkout"
    init_repo(root)
    pkg = root / "self_learn"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "serve.py").write_text("X = 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed")
    return pkg


def _stub_exec(monkeypatch, calls: list) -> None:
    def fake(argv, env):
        calls.append((argv, env))
        raise _Execed()

    monkeypatch.setattr(serve, "_reexec", fake)


# ------------------------------------------------------------------ re-exec


def test_an_uncommitted_code_change_with_no_job_running_re_execs(tmp_path, monkeypatch):
    """The landing case without a landing: the checkout's HEAD never moves,
    one source file gets an uncommitted edit, and the daemon picks it up
    after it has read the same on two ticks."""
    pkg = _code_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (True, ""))
    head = git(pkg.parent, "rev-parse", "HEAD").stdout
    ticks: list[int] = []

    def tick(home, cache_dir, **_kw):
        ticks.append(1)
        if len(ticks) == 1:
            (pkg / "serve.py").write_text("X = 2\n", encoding="utf-8")
        return []

    monkeypatch.setattr(serve, "_run_tick", tick)
    calls: list = []
    _stub_exec(monkeypatch, calls)
    cache = tmp_path / "cache"

    with pytest.raises(_Execed):
        serve.run_forever(tmp_path / "home", cache_dir=cache, tick_secs=0.01, max_ticks=10)

    # control: the change is uncommitted -- HEAD alone could not see it
    assert git(pkg.parent, "rev-parse", "HEAD").stdout == head
    assert git(pkg.parent, "status", "--porcelain").stdout.strip() == "M self_learn/serve.py"
    assert len(calls) == 1
    # the first tick wrote the change; the checks after ticks 1 and 2 read
    # it the same (REEXEC_STABLE_TICKS), and the exec followed the second
    assert len(ticks) == serve.REEXEC_STABLE_TICKS == 2
    argv, env = calls[0]
    assert argv == serve._exec_argv()
    assert float(env["SELF_LEARN_SERVE_STARTED_AT"]) <= time.time()
    assert "SELF_LEARN_SERVE_STARTED_AT" not in os.environ  # never this process's env
    rows = [json.loads(line) for line in (cache / serve.SERVE_JOURNAL_FILENAME).read_text().splitlines()]
    assert [r["status"] for r in rows] == ["reexec"]
    assert rows[0]["from"] != rows[0]["to"]
    assert serve.read_heartbeat(cache)["next_job"].startswith("restarting on new code")


def test_unchanged_code_never_re_execs(tmp_path, monkeypatch):
    """Positive control for the test above: the same loop, no edit."""
    pkg = _code_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    monkeypatch.setattr(serve, "_run_tick", lambda *a, **k: [])
    calls: list = []
    _stub_exec(monkeypatch, calls)
    assert serve.run_forever(tmp_path / "home", cache_dir=tmp_path / "c", tick_secs=0.01, max_ticks=5) == 0
    assert calls == []


def test_a_running_job_holds_the_re_exec_until_it_ends(tmp_path, monkeypatch):
    """Never mid-job: the check, asked while a job runs, does nothing however
    long the new code has been stable; asked again once the job is over, it
    re-executes."""
    pkg = _code_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (True, ""))
    calls: list = []
    _stub_exec(monkeypatch, calls)
    home, cache = tmp_path / "home", tmp_path / "cache"
    watch = serve._CodeWatch(running=serve.code_fingerprint(), started_at=time.time())
    (pkg / "serve.py").write_text("X = 3\n", encoding="utf-8")

    def job():
        for _ in range(4):
            serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
        return "done"

    record = serve.run_one_job(cache, serve.Job("mine", "miner-reader", job), tick_secs=60.0)
    assert record.ok and record.result == "done"
    assert calls == []
    assert watch.seen >= serve.REEXEC_STABLE_TICKS  # control: it WAS ready to go
    assert serve._jobs_in_flight == 0

    with pytest.raises(_Execed):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    assert len(calls) == 1


def test_new_code_that_does_not_import_is_not_run_and_not_retried_within_the_hour(tmp_path, monkeypatch):
    pkg = _code_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    asked: list[int] = []

    def broken(timeout=120.0):
        asked.append(1)
        return False, "SyntaxError: invalid syntax"

    monkeypatch.setattr(serve, "_new_code_imports", broken)
    calls: list = []
    _stub_exec(monkeypatch, calls)
    home, cache = tmp_path / "home", tmp_path / "cache"
    watch = serve._CodeWatch(running=serve.code_fingerprint(), started_at=time.time())
    (pkg / "serve.py").write_text("X = (\n", encoding="utf-8")
    for _ in range(5):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    assert calls == []
    assert asked == [1]  # asked once for this code, not on every tick
    rows = [json.loads(line) for line in (cache / serve.SERVE_JOURNAL_FILENAME).read_text().splitlines()]
    assert [r["status"] for r in rows] == ["reexec-refused"]
    assert "SyntaxError" in rows[0]["error"]

    # the code changes again (fixed): it is checked again and run
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (True, ""))
    (pkg / "serve.py").write_text("X = 4\n", encoding="utf-8")
    with pytest.raises(_Execed):
        for _ in range(3):
            serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    assert len(calls) == 1


def test_the_import_check_reads_a_real_broken_tree(tmp_path):
    """The real import check, against a real interpreter: a package copy with
    a syntax error fails it and the shipped package passes it."""
    copy = tmp_path / "src"
    shutil.copytree(_SRC_DIR, copy / "self_learn", ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(os.environ, PYTHONPATH=str(copy))
    ok = subprocess.run(
        [sys.executable, "-P", "-c", "import self_learn.cli, self_learn.serve"],
        env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    assert ok.returncode == 0, ok.stderr
    with (copy / "self_learn" / "serve.py").open("a", encoding="utf-8") as fh:
        fh.write("\ndef broken(:\n")
    old = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(copy)
    try:
        good, why = serve._new_code_imports()
    finally:
        if old is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old
    assert good is False and "SyntaxError" in why


def test_the_rollback_switch_keeps_the_running_code(tmp_path, monkeypatch):
    pkg = _code_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("serve:\n  restart_on_new_code: false\n", encoding="utf-8")
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (True, ""))
    calls: list = []
    _stub_exec(monkeypatch, calls)
    watch = serve._CodeWatch(running=serve.code_fingerprint(), started_at=time.time())
    (pkg / "serve.py").write_text("X = 5\n", encoding="utf-8")
    for _ in range(4):
        serve._consider_reexec(home, tmp_path / "c", watch, pid=os.getpid(), tick_secs=60.0)
    assert calls == []
    assert watch.seen >= serve.REEXEC_STABLE_TICKS  # control: only the switch held it


def test_a_real_serve_process_re_execs_onto_new_code_in_place(tmp_path):
    """End to end, no stubs: a `serve` subprocess running a copy of the
    package; a source edit in that copy makes the same process (same pid)
    load the new code, which says so by writing its pid to a probe file at
    import, and it keeps ticking."""
    copy = tmp_path / "src"
    shutil.copytree(_SRC_DIR, copy / "self_learn", ignore=shutil.ignore_patterns("__pycache__"))
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    probe = tmp_path / "probe.txt"
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(copy),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "SELF_LEARN_HOME": str(home),
        "SELF_LEARN_MINER": "0",
        "SELF_LEARN_MINER_AUTOKICK": "0",
        "SELF_LEARN_SERVE_TICK_SECS": "0.2",
        "PROBE_FILE": str(probe),
    })
    env.pop("INVOCATION_ID", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "self_learn.cli", "serve"], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        cache = serve.cache_dir_readonly(home).relative_to(Path(os.environ["XDG_CACHE_HOME"]))
        beat = tmp_path / "cache" / cache / serve.HEARTBEAT_FILENAME
        deadline = time.time() + 30
        while time.time() < deadline and proc.poll() is None and not beat.is_file():
            time.sleep(0.05)
        assert beat.is_file(), "serve never ticked"
        with (copy / "self_learn" / "serve.py").open("a", encoding="utf-8") as fh:
            fh.write(
                "\nimport os as _os\n"
                "with open(_os.environ['PROBE_FILE'], 'a', encoding='utf-8') as _fh:\n"
                "    _fh.write(str(_os.getpid()) + '\\n')\n"
            )
        deadline = time.time() + 60
        while time.time() < deadline and proc.poll() is None and not probe.is_file():
            time.sleep(0.1)
        # The import check (a separate interpreter) loads the new code first
        # and writes its own pid; the serve process itself must follow.
        deadline = time.time() + 60
        while (time.time() < deadline and proc.poll() is None
               and str(proc.pid) not in (probe.read_text().split() if probe.is_file() else [])):
            time.sleep(0.1)
        assert probe.is_file(), "the edited code was never loaded"
        assert str(proc.pid) in probe.read_text().split(), "same process, new code"
        before = json.loads(beat.read_text())["ts"]
        deadline = time.time() + 15
        while time.time() < deadline and json.loads(beat.read_text())["ts"] == before:
            time.sleep(0.05)
        assert json.loads(beat.read_text())["ts"] != before, "no tick after the re-exec"
        assert proc.poll() is None
    finally:
        proc.terminate()
        try:
            _out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            _out, err = proc.communicate(timeout=15)
    assert proc.returncode == 0, err
    assert "restarting the host process between jobs" in err


# ---------------------------------------------------------- the unit file


def test_a_changed_unit_file_leaves_a_notice_cleared_after_a_restart(tmp_path, monkeypatch):
    units = tmp_path / "units"
    units.mkdir()
    checkout = tmp_path / "checkout"
    init_repo(checkout)
    unit_src = checkout / "systemd" / serve.HOST_UNIT_NAME
    unit_src.parent.mkdir()
    unit_src.write_text("[Service]\n", encoding="utf-8")
    (units / serve.HOST_UNIT_NAME).symlink_to(unit_src)  # install.sh's shape
    monkeypatch.setenv("SELF_LEARN_SERVE_UNIT_DIR", str(units))
    home = tmp_path / "home"
    home.mkdir()

    # not under systemd: nothing, whatever the times say
    serve._check_unit_file(home, serve._CodeWatch(running="a", started_at=0.0))
    assert notices.all_notices(home) == []

    monkeypatch.setenv("INVOCATION_ID", "test")
    started = unit_src.stat().st_mtime - 60  # the file changed after the start
    serve._check_unit_file(home, serve._CodeWatch(running="a", started_at=started))
    made = notices.all_notices(home)
    assert len(made) == 1
    assert made[0].project == os.path.realpath(checkout)
    assert "daemon-reload" in made[0].text and serve.HOST_UNIT_NAME in made[0].text
    assert notices.is_live(made[0], notices.datetime.now(notices.timezone.utc))

    # restarted after the change: the same file version's notice is done
    serve._check_unit_file(home, serve._CodeWatch(running="a", started_at=time.time() + 5))
    (after,) = notices.all_notices(home)
    assert after.id == made[0].id and after.done_at is not None


# --------------------------------------------------- maintenance recompile


def _routed_plain_without_a_record(tmp_path, rid="lrn-0000d0a1"):
    """A plain host whose CLAUDE.md carries self-learn's region and no compile
    record (verdict `unknown`), as every host before compile records."""
    env = make_env(tmp_path)
    plain_host = tmp_path / "maint-plain"
    plain_host.mkdir()
    host_add(env.ledger, plain_host, "project", mode="plain")
    create_record(env.ledger, make_behavior(scope="project", record_id=rid), project_path=plain_host)
    verbs.route(env.ledger, rid, dest="claude-md", no_push=True)
    shutil.rmtree(env.ledger / "compiled")
    return env, plain_host


def _only_maintenance_due(monkeypatch):
    for name in ("_mine_is_due", "_premises_is_due", "_steward_is_due", "_overseer_is_due"):
        monkeypatch.setattr(serve, name, lambda *a, **k: False)


def test_the_daily_maintenance_job_records_a_clean_unknown_target_once(tmp_path, monkeypatch):
    env, plain_host = _routed_plain_without_a_record(tmp_path)
    target = plain_host / "CLAUDE.md"
    slug = verbs.host_slug(env.ledger, plain_host, scope_kind="project")
    key = compiled.region_key(plain_host, target)
    before = target.read_bytes()
    # controls: selftest sees exactly this target as unrecorded
    assert selfcheck.unrecorded_targets(env.ledger) == {target: ["lrn-0000d0a1"]}
    assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is None
    _only_maintenance_due(monkeypatch)
    cache = tmp_path / "cache"
    now = time.time()

    ran = serve._run_tick(env.ledger, cache, now=now, pid=os.getpid(), tick_secs=60.0)

    assert [r.name for r in ran] == ["maintenance"]
    assert ran[0].ok, ran[0].error
    assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is not None
    assert target.read_bytes() == before  # recorded, never rewritten
    assert "recompile resync record" in git(env.ledger, "log", "-1", "--format=%s").stdout
    state = maintenance.read_state(cache)
    assert state["status"] == "ran"
    assert state["recorded"] == [str(target)] and state["refused"] == {}
    assert selfcheck.unrecorded_targets(env.ledger) == {}

    # once a day: the next tick is not due, and a later day finds nothing to do
    head = git(env.ledger, "rev-parse", "HEAD").stdout
    assert serve._run_tick(env.ledger, cache, now=now + 60, pid=os.getpid(), tick_secs=60.0) == []
    later = serve._run_tick(env.ledger, cache, now=now + 86400 + 60, pid=os.getpid(), tick_secs=60.0)
    assert [r.name for r in later] == ["maintenance"] and later[0].result.status == "idle"
    assert git(env.ledger, "rev-parse", "HEAD").stdout == head


def test_a_hand_edited_unknown_target_is_left_and_logged_with_its_reason(tmp_path, monkeypatch, capsys):
    env, plain_host = _routed_plain_without_a_record(tmp_path)
    target = plain_host / "CLAUDE.md"
    text = target.read_text(encoding="utf-8")
    assert verbs.BEGIN_MARKER in text
    target.write_text(
        text.replace(verbs.BEGIN_MARKER, verbs.BEGIN_MARKER + "\nHAND-EDITED LINE\n"),
        encoding="utf-8",
    )
    edited = target.read_bytes()
    assert edited != text.encode("utf-8")  # control: the edit happened
    result = maintenance.run(env.ledger, tmp_path / "cache", now=time.time())
    assert result.status == "ran"
    assert result.recorded == [] and list(result.refused) == [str(target)]
    assert target.read_bytes() == edited  # a hand edit is never overwritten
    assert "left 1 target(s) unrecorded" in capsys.readouterr().err
    assert maintenance.read_state(tmp_path / "cache")["refused"] == result.refused


def test_selftest_stops_asking_a_person_to_recompile_while_the_job_runs(tmp_path):
    env, plain_host = _routed_plain_without_a_record(tmp_path)
    # positive control: no host process -> the old advice, naming the command
    verdict, reason = selfcheck._check_drift(env.ledger)
    assert verdict is selfcheck.Verdict.PASS
    assert "1 target(s) carry self-learn markers with no compile record" in reason
    assert "run `self-learn recompile`" in reason

    cache = serve.cache_dir_readonly(env.ledger)
    serve.write_heartbeat(cache, pid=os.getpid(), next_job="x", tick_secs=60.0)
    verdict, reason = selfcheck._check_drift(env.ledger)
    assert verdict is selfcheck.Verdict.PASS
    assert "1 target(s) carry self-learn markers with no compile record" in reason
    assert "daily maintenance recompile records them" in reason
    assert "run `self-learn recompile`" not in reason
    assert "--adopt" not in reason

    # a target the last run could not record keeps its own repair
    target = plain_host / "CLAUDE.md"
    maintenance._store_state(cache, {"last_attempt_at": "2026-10-31T00:00:00Z",
                                     "refused": {str(target): "hand-edited"}})
    _verdict, reason = selfcheck._check_drift(env.ledger)
    assert f"could not record {target} (hand-edited)" in reason
    assert f"`self-learn recompile --adopt {target}`" in reason


# ------------------------------------------------- retired, target gone


def _retired_in_a_vanished_host(tmp_path, env, rid):
    gone_host = tmp_path / "gone-host"
    gone_host.mkdir()
    host_add(env.ledger, gone_host, "project", mode="plain")
    create_record(env.ledger, make_behavior(scope="project", record_id=rid), project_path=gone_host)
    verbs.route(env.ledger, rid, dest="claude-md", no_push=True)
    verbs.retire(env.ledger, rid, covered_by="claude-md:elsewhere", no_push=True)
    host_remove(env.ledger, gone_host)
    shutil.rmtree(gone_host)
    return gone_host


def test_a_retired_lesson_whose_host_is_gone_is_counted_not_warned(tmp_path):
    env = make_env(tmp_path)
    gone_host = _retired_in_a_vanished_host(tmp_path, env, "lrn-0000d0b1")

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == ["lrn-0000d0b1"]
    assert not [w for w in result.warnings if "lrn-0000d0b1" in w], result.warnings
    assert not [w for w in result.warnings if str(gone_host) in w], result.warnings
    outcome = verbs.post_run_recompile(env.ledger, ["lrn-0000d0b1"])
    assert outcome["gone"] == 1 and outcome["warnings"] == []


def test_the_skip_is_narrow_a_retired_lesson_on_an_existing_unregistered_path_still_warns(tmp_path):
    """The path is still on disk, so its file may still hold the line: the
    warning (and its `host add`) stays."""
    env = make_env(tmp_path)
    gone_host = _retired_in_a_vanished_host(tmp_path, env, "lrn-0000d0b2")
    gone_host.mkdir()
    result = verbs.recompile(env.ledger, no_push=True)
    assert result.gone == []
    assert [w for w in result.warnings if w.startswith("lrn-0000d0b2:") and "host add" in w]


def test_a_retired_lesson_whose_host_exists_still_has_its_line_removed(tmp_path):
    """Positive control: where the target is on disk, recompile still takes
    a retired lesson's line out (an interrupted retirement left it there)."""
    env = make_env(tmp_path)
    host = tmp_path / "kept-host"
    host.mkdir()
    host_add(env.ledger, host, "project", mode="plain")
    rid = "lrn-0000d0b3"
    create_record(env.ledger, make_behavior(scope="project", record_id=rid), project_path=host)
    verbs.route(env.ledger, rid, dest="claude-md", no_push=True)
    target = host / "CLAUDE.md"
    with_line = target.read_bytes()
    assert f"({rid})".encode() in with_line
    verbs.retire(env.ledger, rid, covered_by="claude-md:elsewhere", no_push=True)
    assert f"({rid})".encode() not in target.read_bytes()
    target.write_bytes(with_line)  # the retirement's host write did not land

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == []
    assert f"({rid})".encode() not in target.read_bytes()
    assert [e for e in result.entries if e.target == target and e.changed]


def test_a_retired_skill_lesson_whose_skill_folder_is_gone_is_counted_not_warned(tmp_path):
    env = make_env(tmp_path, skills=("s", "doomed"))
    rid = "lrn-0000d0b4"
    create_record(env.ledger, make_behavior(scope="skill:doomed", record_id=rid))
    verbs.route(env.ledger, rid, dest="skill-md", no_push=True)
    verbs.retire(env.ledger, rid, covered_by="skill-md:s", no_push=True)
    shutil.rmtree(env.host / "plugins" / "doomed-plugin")
    git(env.host, "add", "-A")
    git(env.host, "commit", "-q", "-m", "drop the doomed skill")

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == [rid]
    assert not [w for w in result.warnings if rid in w or "doomed" in w], result.warnings


# ----------------------------------------------- overseer.hook_activation


def test_hook_activation_is_a_registered_setting_with_no_doctor_warning(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "overseer:\n  hook_activation: true\n  bogus_key: 1\n", encoding="utf-8"
    )
    rows = settings.preflight(home)
    warns = [r.detail for r in rows if r.verdict == "WARN"]
    # positive control: a really unknown key in the same section still warns
    assert "unknown settings config key: overseer.bogus_key" in warns
    assert not [w for w in warns if "hook_activation" in w], warns
    value, source = settings.resolve_setting(home, settings.by_name("overseer.hook_activation"))
    assert (value, source) == (True, "config:overseer.hook_activation")
    assert config.hook_activation_enabled(home) is True  # the reader agrees


@pytest.mark.parametrize(
    "text, expected",
    [
        ("overseer:\n  hook_activation: false\n", False),
        ("overseer:\n  enabled: true\n", False),
        ("overseer:\n  hook_activation: 'true'\n", False),
    ],
)
def test_the_registry_and_the_reader_agree(tmp_path, text, expected):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(text, encoding="utf-8")
    value, _source = settings.resolve_setting(home, settings.by_name("overseer.hook_activation"))
    assert value is expected
    assert config.hook_activation_enabled(home) is expected
    setting = settings.by_name("overseer.hook_activation")
    assert setting.tier == "C" and setting.env_var is None and setting.override_channel is False


# ================================================================ fix round 1
#
# Gate r1 finding 1 (MAJOR): a landing that changes dependencies must not
# leave `serve` on old code. The project files (`pyproject.toml`, `uv.lock`)
# are in the fingerprint; a change to them syncs the venv before the import
# check; an import that fails on a dependency syncs and checks again; and a
# refused fingerprint is tried again after `REEXEC_RETRY_SECS`, with a
# project notice while it is held.


def _project_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in uv project in a git checkout: `cli/pyproject.toml`,
    `cli/uv.lock` and `cli/src/self_learn/`, the shipped layout."""
    checkout = tmp_path / "checkout"
    init_repo(checkout)
    project = checkout / "cli"
    pkg = project / "src" / "self_learn"
    pkg.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "serve.py").write_text("X = 1\n", encoding="utf-8")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "seed")
    return project, pkg


def _watch_now() -> "serve._CodeWatch":
    env = serve.env_fingerprint()
    return serve._CodeWatch(
        running=serve._fingerprint(serve.code_fingerprint(), env),
        started_at=time.time(), running_env=env,
    )


@pytest.mark.parametrize("changed", ["uv.lock", "pyproject.toml"])
def test_a_changed_lock_file_syncs_the_venv_before_the_re_exec(tmp_path, monkeypatch, changed):
    """Fix r2 (gate NIT 4): either project file alone is a change the venv
    must follow."""
    project, pkg = _project_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    assert serve._project_root() == project  # control: the layout is found
    order: list[str] = []
    monkeypatch.setattr(serve, "_sync_venv", lambda p, timeout=600.0: (order.append(f"sync {p}"), (True, ""))[1])
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (order.append("import"), (True, ""))[1])
    calls: list = []
    _stub_exec(monkeypatch, calls)
    home, cache = tmp_path / "home", tmp_path / "cache"
    watch = _watch_now()
    code_before = serve.code_fingerprint()
    with (project / changed).open("a", encoding="utf-8") as fh:
        fh.write("# a new dependency\n")
    assert serve.code_fingerprint() == code_before  # no Python file changed

    serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    with pytest.raises(_Execed):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)

    assert order == [f"sync {project}", "import"]
    assert len(calls) == 1


def test_a_failed_sync_keeps_the_running_code(tmp_path, monkeypatch):
    """The lock changed and `uv sync` failed: the import check could still
    pass on the old venv (a lazy import of the new dependency), so the
    re-exec is refused on the sync failure itself."""
    project, pkg = _project_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    monkeypatch.setattr(serve, "_sync_venv", lambda p, timeout=600.0: (False, "error: no network"))
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (True, ""))
    calls: list = []
    _stub_exec(monkeypatch, calls)
    cache = tmp_path / "cache"
    watch = _watch_now()
    (project / "uv.lock").write_text("version = 1\n# a new dependency\n", encoding="utf-8")
    for _ in range(3):
        serve._consider_reexec(tmp_path / "h", cache, watch, pid=os.getpid(), tick_secs=60.0)
    assert calls == []
    rows = [json.loads(line) for line in (cache / serve.SERVE_JOURNAL_FILENAME).read_text().splitlines()]
    assert [r["status"] for r in rows] == ["reexec-refused"]
    assert rows[0]["error"] == "uv sync failed: error: no network"


def test_a_code_only_change_does_not_sync(tmp_path, monkeypatch):
    """Control for the test above: same tree, a Python edit only."""
    project, pkg = _project_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    synced: list[Path] = []
    monkeypatch.setattr(serve, "_sync_venv", lambda p, timeout=600.0: (synced.append(p), (True, ""))[1])
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (True, ""))
    calls: list = []
    _stub_exec(monkeypatch, calls)
    watch = _watch_now()
    (pkg / "serve.py").write_text("X = 2\n", encoding="utf-8")
    with pytest.raises(_Execed):
        for _ in range(3):
            serve._consider_reexec(tmp_path / "h", tmp_path / "c", watch, pid=os.getpid(), tick_secs=60.0)
    assert synced == [] and len(calls) == 1


def test_a_missing_dependency_syncs_the_venv_and_then_runs(tmp_path, monkeypatch):
    """The venv is behind the lock with the lock unchanged (a sync skipped
    since the last start): the import fails on the dependency, the venv is
    synced, the check passes, the re-exec goes ahead."""
    project, pkg = _project_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    state = {"synced": False}
    order: list[str] = []

    def sync(p, timeout=600.0):
        order.append("sync")
        state["synced"] = True
        return True, ""

    def imports(timeout=120.0):
        order.append("import")
        if state["synced"]:
            return True, ""
        return False, "ModuleNotFoundError: No module named 'newdep'"

    monkeypatch.setattr(serve, "_sync_venv", sync)
    monkeypatch.setattr(serve, "_new_code_imports", imports)
    calls: list = []
    _stub_exec(monkeypatch, calls)
    watch = _watch_now()
    (pkg / "serve.py").write_text("import newdep\n", encoding="utf-8")
    with pytest.raises(_Execed):
        for _ in range(3):
            serve._consider_reexec(tmp_path / "h", tmp_path / "c", watch, pid=os.getpid(), tick_secs=60.0)
    assert order == ["import", "sync", "import"]
    assert len(calls) == 1


def test_a_syntax_error_is_not_synced_for(tmp_path, monkeypatch):
    """Only a dependency failure is worth a sync: broken code is refused
    as it is."""
    project, pkg = _project_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    synced: list[Path] = []
    monkeypatch.setattr(serve, "_sync_venv", lambda p, timeout=600.0: (synced.append(p), (True, ""))[1])
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (False, "SyntaxError: x"))
    calls: list = []
    _stub_exec(monkeypatch, calls)
    watch = _watch_now()
    (pkg / "serve.py").write_text("X = (\n", encoding="utf-8")
    for _ in range(3):
        serve._consider_reexec(tmp_path / "h", tmp_path / "c", watch, pid=os.getpid(), tick_secs=60.0)
    assert synced == [] and calls == []
    assert watch.refused is not None


def test_a_refused_fingerprint_is_tried_again_after_the_retry_interval(tmp_path, monkeypatch):
    """The environment is fixed while the code stays the same: the refused
    code is tried again once `REEXEC_RETRY_SECS` have passed, not before.
    While it is held, a project notice for the checkout says so; the
    re-exec that finally goes ahead marks it done."""
    pkg = _code_tree(tmp_path)
    checkout = pkg.parent
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    result = {"ok": False}
    asked: list[float] = []

    def imports(timeout=120.0):
        asked.append(1)
        return (True, "") if result["ok"] else (False, "ImportError: cannot import name 'x'")

    monkeypatch.setattr(serve, "_new_code_imports", imports)
    calls: list = []
    _stub_exec(monkeypatch, calls)
    home, cache = tmp_path / "home", tmp_path / "cache"
    watch = _watch_now()
    (pkg / "serve.py").write_text("from os import x\n", encoding="utf-8")
    t0 = time.time()
    for i in range(4):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0, now=t0 + i)
    assert len(asked) == 1 and calls == []
    (held,) = [n for n in notices.all_notices(home) if n.project == os.path.realpath(checkout)]
    assert "held on its old code" in held.text and "ImportError" in held.text
    assert notices.is_live(held, notices.datetime.now(notices.timezone.utc))

    # still inside the interval: not asked again
    serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0,
                           now=t0 + serve.REEXEC_RETRY_SECS - 10)
    assert len(asked) == 1

    # the venv got fixed (nothing in the code changed); past the interval
    result["ok"] = True
    with pytest.raises(_Execed):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0,
                               now=t0 + serve.REEXEC_RETRY_SECS + 5)
    assert len(asked) == 2 and len(calls) == 1
    rows = [json.loads(line) for line in (cache / serve.SERVE_JOURNAL_FILENAME).read_text().splitlines()]
    assert [r["status"] for r in rows] == ["reexec-refused", "reexec"]
    # fix r2 (gate NIT 5): the exec itself does not mark it done ...
    (pending,) = [n for n in notices.all_notices(home) if n.id == held.id]
    assert pending.done_at is None
    # ... the new image does, as it starts
    monkeypatch.setattr(serve, "_run_tick", lambda *a, **k: [])
    assert serve.run_forever(home, cache_dir=cache, tick_secs=0.01, max_ticks=1) == 0
    (after,) = [n for n in notices.all_notices(home) if n.id == held.id]
    assert after.done_at is not None


def test_the_sync_runs_the_uv_that_started_the_process(tmp_path, monkeypatch):
    """`_sync_venv` against a stand-in `uv` named by `UV` (what `uv run`
    sets): the exact command, and a failure's last line as the reason."""
    log = tmp_path / "uv-argv.txt"
    fake = tmp_path / "fake-uv"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {log}\n"
        "if [ -n \"$FAKE_UV_FAIL\" ]; then echo 'error: no network' >&2; exit 2; fi\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("UV", str(fake))
    project = tmp_path / "proj"
    project.mkdir()
    assert serve._sync_venv(project) == (True, "")
    assert log.read_text().split("\n")[:4] == ["sync", "--project", str(project), "--inexact"]
    monkeypatch.setenv("FAKE_UV_FAIL", "1")
    assert serve._sync_venv(project) == (False, "error: no network")


# Gate r1 finding 2 (MINOR): the maintenance job's ledger commit is a job's.


def test_the_maintenance_commit_is_not_a_hand_step(tmp_path):
    env, plain_host = _routed_plain_without_a_record(tmp_path)
    result = maintenance.run(env.ledger, tmp_path / "cache", now=time.time())
    assert result.recorded == [str(plain_host / "CLAUDE.md")]
    job_sha = git(env.ledger, "rev-parse", "--short", "HEAD").stdout.strip()
    assert "By: maintenance" in git(env.ledger, "log", "-1", "--format=%B").stdout

    # positive control: the same repair run by hand is a hand step
    shutil.rmtree(env.ledger / "compiled")
    git(env.ledger, "add", "-A")
    git(env.ledger, "commit", "-q", "-m", "drop the record again")
    verbs.recompile(env.ledger, no_push=True)
    hand_sha = git(env.ledger, "rev-parse", "--short", "HEAD").stdout.strip()
    assert "recompile resync record" in git(env.ledger, "log", "-1", "--format=%s").stdout

    census = report.hand_steps(env.ledger)
    commits = {step["commit"]: step for step in census["steps"]}
    assert census["state"] == "ok"
    assert hand_sha in commits and commits[hand_sha]["by"] == "none"
    assert job_sha not in commits


# Gate r1 finding 3 (MINOR): three stated behaviours, pinned.


def test_a_retired_lesson_on_a_registered_host_whose_path_vanished_still_warns(tmp_path):
    """13 §4 item 2 as amended: a registered host whose path vanished is a
    broken registration (`host rebind` repairs it), so its warning stays."""
    env = make_env(tmp_path)
    host = tmp_path / "moved-host"
    host.mkdir()
    host_add(env.ledger, host, "project", mode="plain")
    rid = "lrn-0000d0c1"
    create_record(env.ledger, make_behavior(scope="project", record_id=rid), project_path=host)
    verbs.route(env.ledger, rid, dest="claude-md", no_push=True)
    verbs.retire(env.ledger, rid, covered_by="claude-md:elsewhere", no_push=True)
    shutil.rmtree(host)  # still registered in hosts.yaml

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == []
    assert [w for w in result.warnings if w.startswith(f"{rid}:") and str(host) in w], result.warnings


def _retired_new_skill(tmp_path, rid, name, *, retire=True, vetoed=False):
    env = make_env(tmp_path)
    marketplace = env.host / ".claude-plugin" / "marketplace.json"
    marketplace.parent.mkdir()
    marketplace.write_text(json.dumps({
        "name": "m", "owner": {"name": "o"},
        "plugins": [{"name": "s-plugin", "source": "./plugins/s-plugin",
                     "description": "seeded plugin", "version": "1.0.0"}],
    }) + "\n", encoding="utf-8")
    git(env.host, "add", "-A")
    git(env.host, "commit", "-q", "-m", "marketplace seed")
    create_record(env.ledger, make_behavior(scope="skill:s", record_id=rid))
    if vetoed:
        # S-110 SK-G: a route scaffold under a vetoed name stays
        # the person's (no owned row), so recompile may scaffold it again.
        def add(registry):
            registry.add_veto(name, at="2026-10-31T00:00:00Z", by="human")

        skill_registry.with_update(env.ledger, add, subject=f"veto {name}")
    verbs.route(env.ledger, rid, dest=f"new-skill:{name}", no_push=True)
    assert (env.host / "plugins" / name).is_dir()  # control: it was scaffolded
    if retire:
        verbs.retire(env.ledger, rid, covered_by="skill-md:s", no_push=True)
    return env


def test_a_retired_new_skill_lesson_whose_plugin_is_gone_is_counted_not_warned(tmp_path):
    rid = "lrn-0000d0c2"
    env = _retired_new_skill(tmp_path, rid, "doomed-new")
    shutil.rmtree(env.host / "plugins" / "doomed-new")
    git(env.host, "add", "-A")
    git(env.host, "commit", "-q", "-m", "drop the doomed plugin")

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == [rid]
    assert not [w for w in result.warnings if rid in w or "doomed-new" in w], result.warnings


def test_a_retired_new_skill_lesson_whose_plugin_is_still_there_is_not_gone(tmp_path):
    """The narrow side: the plugin is on disk, so its SKILL.md is still
    compiled for the retired lesson (here: the existing "nothing to compile"
    warning for a skill whose every lesson retired), never counted gone."""
    rid = "lrn-0000d0c3"
    env = _retired_new_skill(tmp_path, rid, "kept-new")
    skill_md = env.host / "plugins" / "kept-new" / "skills" / "kept-new" / "SKILL.md"
    assert skill_md.is_file()

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == []
    assert [e for e in result.entries if e.target == skill_md], result.entries


def test_the_start_time_carried_across_a_re_exec_keeps_the_unit_notice(tmp_path, monkeypatch):
    """`run_forever` reads its start from `SELF_LEARN_SERVE_STARTED_AT` (set
    by the re-exec): the unit file changed after the FIRST start, so the
    notice must stay live even though this image began after the change."""
    units = tmp_path / "units"
    units.mkdir()
    checkout = tmp_path / "checkout"
    init_repo(checkout)
    unit_src = checkout / "systemd" / serve.HOST_UNIT_NAME
    unit_src.parent.mkdir()
    unit_src.write_text("[Service]\n", encoding="utf-8")
    (units / serve.HOST_UNIT_NAME).symlink_to(unit_src)
    monkeypatch.setenv("SELF_LEARN_SERVE_UNIT_DIR", str(units))
    monkeypatch.setenv("INVOCATION_ID", "test")
    monkeypatch.setattr(serve, "_run_tick", lambda *a, **k: [])
    home = tmp_path / "home"
    home.mkdir()

    # positive control: no carried start -> this image began after the
    # change, so no notice is live
    assert serve.run_forever(home, cache_dir=tmp_path / "c1", tick_secs=0.01, max_ticks=2) == 0
    assert not [n for n in notices.all_notices(home)
                if notices.is_live(n, notices.datetime.now(notices.timezone.utc))]

    monkeypatch.setenv("SELF_LEARN_SERVE_STARTED_AT", repr(unit_src.stat().st_mtime - 60))
    assert serve.run_forever(home, cache_dir=tmp_path / "c2", tick_secs=0.01, max_ticks=2) == 0
    live = [n for n in notices.all_notices(home)
            if notices.is_live(n, notices.datetime.now(notices.timezone.utc))]
    assert len(live) == 1 and "daemon-reload" in live[0].text


# Gate r1 NIT 5: the drift row names a failed maintenance run.


def test_selftest_names_a_failed_maintenance_run(tmp_path):
    env, _plain_host = _routed_plain_without_a_record(tmp_path)
    cache = serve.cache_dir_readonly(env.ledger)
    serve.write_heartbeat(cache, pid=os.getpid(), next_job="x", tick_secs=60.0)
    _verdict, reason = selfcheck._check_drift(env.ledger)
    assert "daily maintenance recompile records them" in reason
    assert "its last run failed" not in reason  # control: no run on file, no failure named
    maintenance._store_state(cache, {"last_attempt_at": "2026-10-31T00:00:00Z", "status": "failed",
                                     "refused": {}, "error": "HostsError: boom"})
    _verdict, reason = selfcheck._check_drift(env.ledger)
    assert "its last run failed (HostsError: boom)" in reason


# ================================================================ fix round 2


def _held(tmp_path, monkeypatch, why="ImportError: cannot import name 'x'"):
    """A stand-in checkout whose new code is refused: the watch, the home
    and the cache, with the hold notice live (checked here, so every test
    below starts from that positive control)."""
    pkg = _code_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (False, why))
    calls: list = []
    _stub_exec(monkeypatch, calls)
    home, cache = tmp_path / "home", tmp_path / "cache"
    watch = _watch_now()
    (pkg / "serve.py").write_text("from os import x\n", encoding="utf-8")
    for _ in range(serve.REEXEC_STABLE_TICKS):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    assert calls == [] and watch.refused is not None
    (held,) = notices.all_notices(home)
    assert held.done_at is None and why.split(":")[0] in held.text
    return pkg, home, cache, watch, calls, held


def _notice(home, nid):
    (found,) = [n for n in notices.all_notices(home) if n.id == nid]
    return found


# Gate r2 finding 1 (MINOR): the `retired` guard on the new-skill gone branch.


def test_a_live_owned_new_skill_whose_plugin_is_gone_is_not_counted_gone(tmp_path):
    """The other side of the retired-and-gone skip, for a skill self-learn
    owns: since S-110 SK-G a route's scaffold under a fresh name
    is owned, and an owned skill's missing SKILL.md is restored by the overseer
    (SK-E), never scaffolded by a recompile. The LIVE lesson is still never
    counted gone: recompile names the owned skill's repair instead
    (integration w31b: self-maint's test predates SK-G)."""
    rid = "lrn-0000d0c5"
    env = _retired_new_skill(tmp_path, rid, "live-owned", retire=False)
    shutil.rmtree(env.host / "plugins" / "live-owned")
    git(env.host, "add", "-A")
    git(env.host, "commit", "-q", "-m", "drop the live plugin")
    skill_md = env.host / "plugins" / "live-owned" / "skills" / "live-owned" / "SKILL.md"

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == []
    assert [w for w in result.warnings if rid in w and "self-learn owns" in w], result.warnings
    assert not skill_md.exists()


def test_a_live_new_skill_lesson_whose_plugin_is_gone_is_rebuilt_not_counted_gone(tmp_path):
    """The other side of the retired-and-gone skip: a LIVE lesson routed to a
    new skill whose plugin folder was deleted is compiled again (its plugin
    comes back), never counted gone. The skill is the person's (a scaffold
    under a vetoed name, SK-G), since an owned one is the overseer's to
    restore (the test above)."""
    rid = "lrn-0000d0c4"
    env = _retired_new_skill(tmp_path, rid, "live-new", retire=False, vetoed=True)
    shutil.rmtree(env.host / "plugins" / "live-new")
    git(env.host, "add", "-A")
    git(env.host, "commit", "-q", "-m", "drop the live plugin")
    skill_md = env.host / "plugins" / "live-new" / "skills" / "live-new" / "SKILL.md"
    assert not skill_md.exists()

    result = verbs.recompile(env.ledger, no_push=True)

    assert result.gone == []
    assert not [w for w in result.warnings if rid in w], result.warnings
    assert skill_md.is_file()
    assert [e for e in result.entries if e.target == skill_md], result.entries


# Gate r2 finding 2 (MINOR): the hold notice ends when the hold ends.


def test_a_fresh_start_marks_the_hold_notice_done(tmp_path, monkeypatch):
    """A reboot or a restart of the unit starts the process on the code on
    disk: the notice an earlier image left is done at start-up."""
    _pkg, home, cache, _watch, _calls, held = _held(tmp_path, monkeypatch)
    monkeypatch.setattr(serve, "_run_tick", lambda *a, **k: [])
    assert serve.run_forever(home, cache_dir=cache, tick_secs=0.01, max_ticks=1) == 0
    assert _notice(home, held.id).done_at is not None


def test_code_reverted_to_the_running_code_marks_the_hold_notice_done(tmp_path, monkeypatch):
    pkg, home, cache, watch, calls, held = _held(tmp_path, monkeypatch)
    # control: another check with the code still changed keeps it live
    serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    assert _notice(home, held.id).done_at is None
    (pkg / "serve.py").write_text("X = 1\n", encoding="utf-8")  # the committed code again
    serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    assert _notice(home, held.id).done_at is not None
    assert watch.refused is None and calls == []


# Gate r2 NIT 5: the notice's reason and its done-ness follow the real state.


def test_a_later_refusal_for_another_reason_replaces_the_notice_words(tmp_path, monkeypatch):
    pkg, home, cache, watch, _calls, held = _held(tmp_path, monkeypatch)
    monkeypatch.setattr(serve, "_new_code_imports",
                        lambda timeout=120.0: (False, "SyntaxError: invalid syntax"))
    (pkg / "serve.py").write_text("X = (\n", encoding="utf-8")
    for _ in range(serve.REEXEC_STABLE_TICKS):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    now = _notice(home, held.id)
    assert now.done_at is None
    assert "SyntaxError" in now.text and "ImportError" not in now.text


def test_a_failed_exec_leaves_the_hold_notice_live(tmp_path, monkeypatch):
    pkg = _code_tree(tmp_path)
    monkeypatch.setattr(serve, "_code_root", lambda: pkg)
    monkeypatch.setattr(serve, "_new_code_imports", lambda timeout=120.0: (True, ""))

    def fail(argv, env):
        raise OSError("exec format error")

    monkeypatch.setattr(serve, "_reexec", fail)
    home, cache = tmp_path / "home", tmp_path / "cache"
    watch = _watch_now()
    (pkg / "serve.py").write_text("X = 9\n", encoding="utf-8")
    for _ in range(serve.REEXEC_STABLE_TICKS):
        serve._consider_reexec(home, cache, watch, pid=os.getpid(), tick_secs=60.0)
    rows = [json.loads(line) for line in (cache / serve.SERVE_JOURNAL_FILENAME).read_text().splitlines()]
    assert [r["status"] for r in rows] == ["reexec", "reexec-failed"]
    (held,) = notices.all_notices(home)
    assert held.done_at is None and "restart failed" in held.text
