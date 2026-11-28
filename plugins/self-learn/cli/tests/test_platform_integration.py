"""Cross-process witnesses for capture's ledger, host, cache, and Git contracts."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from self_learn import compiled, gitops, hosts, intents, ledger, serve, telemetry, worker
from self_learn.primitives import names
from test_windows_capture import git, scratch_env, windows


@pytest.fixture
def home(tmp_path, monkeypatch):
    for key, value in scratch_env(tmp_path).items():
        if os.environ.get(key) != value:
            monkeypatch.setenv(key, value)
    root = Path(os.environ["SELF_LEARN_HOME"])
    ledger.init_home(root)
    return root


def child(code, *args):
    return subprocess.run([sys.executable, "-c", code, *map(str, args)],
                          check=True, capture_output=True, timeout=40).stdout.strip()


def wait_for(path, process):
    until = time.monotonic() + 25
    while not path.exists():
        assert process.poll() is None and time.monotonic() < until, path
        time.sleep(0.02)


def test_worktrees_and_modes_share_commit_lock(home, tmp_path, monkeypatch):
    linked = tmp_path / "linked"
    git(home, "worktree", "add", "-b", "linked", str(linked))
    plain = tmp_path / "plain"
    plain.mkdir()
    assert gitops.host_lock_path(linked, "git") == gitops.commit_lock_path(home)
    probe = """
from pathlib import Path
import sys
from self_learn import gitops
try:
    with gitops.host_lock(Path(sys.argv[1]), 'plain', timeout=0.15):
        print('held')
except gitops.GitOpsError:
    print('busy')
"""
    for holder, peer in ((home, linked), (plain, plain)):
        with gitops.host_lock(holder, "plain"):
            monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "other-ledger"))
            assert child(probe, peer) == b"busy"
        assert child(probe, peer) == b"held"


def test_recovery_after_killed_writer(home, tmp_path):
    host = tmp_path / "plain"
    host.mkdir()
    ready = tmp_path / "ready"
    code = """
from pathlib import Path
import os, sys, time
from self_learn import hosts, intents
original = intents.complete
def stop_after_durable_intent(intent):
    original(intent)
    Path(sys.argv[2]).write_text(f'{intent.id} {os.getpid()}', encoding='ascii')
    time.sleep(90)
intents.complete = stop_after_durable_intent
hosts.host_add(os.environ['SELF_LEARN_HOME'], sys.argv[1], 'project', mode='plain')
"""
    proc = subprocess.Popen([sys.executable, "-c", code, str(host), str(ready)])
    try:
        wait_for(ready, proc)
        iid, writer = ready.read_text().split()
        assert intents.classify_status(home).probe == "busy"
        assert gitops.commit_lock_path(home).read_text().strip() == writer
        assert (home / ".intents" / (iid + ".json")).is_file()
    finally:
        if ready.exists():
            os.kill(int(ready.read_text().split()[1]), signal.SIGTERM)
        else:
            proc.kill()
        proc.wait(timeout=15)
    with intents.ledger_write(home) as recovered:
        assert recovered.rolled_forward == [iid]
    assert intents.classify_status(home).probe == "ok"
    assert git(home, "show", "HEAD:hosts.yaml") == (home / "hosts.yaml").read_bytes()
    assert host in hosts.load_hosts(home).projects
    assert not list((home / ".intents").glob("*.json"))


def test_concurrent_flush_and_append(home, tmp_path, monkeypatch):
    seed = telemetry.spool_event("offer-made", sequence=1)
    target = home / "telemetry" / seed.name
    target.write_bytes(b"torn")
    git(home, "add", "--", "telemetry")
    git(home, "commit", "-m", "seed torn tail")
    (home / "sentinel").write_bytes(b"staged")
    git(home, "add", "--", "sentinel")
    status = git(home, "status", "--porcelain", "-zuall")
    assert status == b"A  sentinel\0"
    ready = tmp_path / "late-writer"
    code = """
from pathlib import Path
import sys
from self_learn import telemetry
original = telemetry.locks.acquire
def acquire(*args, **kwargs):
    Path(sys.argv[1]).touch()
    return original(*args, **kwargs)
telemetry.locks.acquire = acquire
telemetry.spool_event('offer-made', sequence=2)
"""
    # Start the late producer only once flush owns the first data file.
    peers = []
    acquire = telemetry.locks.acquire
    def contend(fd, *, path, **kwargs):
        lease = acquire(fd, path=path, **kwargs)
        if path == seed and not peers:
            peers.append(subprocess.Popen([sys.executable, "-c", code, str(ready)]))
            wait_for(ready, peers[0])
        return lease

    monkeypatch.setattr(telemetry.locks, "acquire", contend)
    try:
        assert telemetry.flush(home, push=False).events == 1
    finally:
        for proc in peers:
            try:
                assert proc.wait(timeout=25) == 0
            finally:
                proc.kill()
                proc.wait()
    assert json.loads(seed.read_bytes())["sequence"] == 2
    assert telemetry.flush(home, push=False).events == 1
    blob = git(home, "show", "HEAD:telemetry/" + seed.name)
    assert blob == target.read_bytes()
    torn, first, second = blob.splitlines()
    assert torn == b"torn" and [json.loads(row)["sequence"] for row in (first, second)] == [1, 2]
    assert seed.read_bytes() == b"" and git(home, "status", "--porcelain", "-zuall") == status
    assert git(home, "show", ":sentinel") == b"staged"


def test_git_excludes_trailing_space(home):
    line = gitops.exclude_pattern("leaf ")
    assert gitops.ignored_with_line(home, "leaf ", line)
    assert not gitops.ignored_with_line(home, "leaf", line)


def test_readonly_and_creating_cache_have_same_path(home):
    root = names.cache_root()
    root.mkdir(parents=True, exist_ok=True)
    guard = root / "guard"
    guard.write_bytes(b"guard")
    historical = root.parent / "claude-skills" / "self-learn"
    historical.mkdir(parents=True)
    (historical / "old-state").write_bytes(b"prior")
    dest = serve.cache_dir_readonly(home)
    assert dest.parent == root and set(root.iterdir()) == {guard}
    assert worker.cache_dir(home) == dest
    assert (dest / ".home").read_text().strip() == names.home_spelling(home)
    assert (dest / "old-state").read_bytes() == b"prior" and guard.read_bytes() == b"guard"


@windows
def test_component_rejects_invalid_actor_without_creating_spool(home, monkeypatch):
    spool = telemetry.spool_event("offer-made")
    assert spool.parent == names.home_cache() / "spool"
    assert json.loads(spool.read_bytes())["actor"] == "capture-test"
    before = {p: p.read_bytes() for p in spool.parent.rglob("*") if p.is_file()}
    monkeypatch.setenv("SELF_LEARN_ACTOR", "../nested/actor")
    with pytest.raises(ValueError):
        telemetry.spool_event("offer-made")
    assert {p: p.read_bytes() for p in spool.parent.rglob("*") if p.is_file()} == before


@windows
def test_static_junction_escape_refused(home, tmp_path):
    import _winapi
    from self_learn import cli

    outside = tmp_path / "outside"
    outside.mkdir()
    guard = outside / "guard"
    guard.write_bytes(b"guard")
    junction = home / "user" / "pending"
    _winapi.CreateJunction(str(outside), str(junction))
    assert junction.is_junction() and junction.samefile(outside)
    assert cli.main(["teach", "--no-push", "--user", "--fact", "scratch lesson"]) != 0
    assert list(outside.iterdir()) == [guard] and guard.read_bytes() == b"guard"
    junction.rmdir()
    assert cli.main(["teach", "--no-push", "--user", "--fact", "scratch lesson"]) == 0
    assert len(list(junction.glob("*.md"))) == 1


@windows
def test_git_tree_keys_and_literal_pathspec_with_unrelated_index_entry(home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    name = "café [1]"
    old, match = home / name, home / "café 1"
    old.write_bytes(b"\xff\0old")
    match.write_bytes(b"index control")
    gitops.stage(home, [old, match])
    gitops.commit(home, "both", paths=[old, match])
    git(home, "mv", "--", name, "renamed")
    match.write_bytes(b"pending")
    git(home, "add", "--", match.name)
    assert ("R ", home / "renamed") in gitops.porcelain_paths(home)
    assert intents._head_show(home, name) == b"\xff\0old"
    gitops.commit(home, "rename only", paths=[old, home / "renamed"])
    assert git(home, "show", "HEAD:renamed") == b"\xff\0old"
    assert git(home, "show", "HEAD:" + match.name) == b"index control"
    assert git(home, "show", ":" + match.name) == b"pending"
    assert gitops.porcelain_paths(home) == [("M ", match)]


@windows
def test_existing_buckets_roundtrip_without_rekey(home, tmp_path):
    from self_learn import cli
    for host in (tmp_path / "project A", tmp_path / "project B"):
        host.mkdir()
        hosts.host_add(home, host, "project", mode="plain")
        result = subprocess.run([sys.executable, "-m", "self_learn.cli", "teach", "--project", "--no-push",
                                 "--json", "--fact", "historical bucket witness"], cwd=host,
                                capture_output=True, check=True, timeout=40)
        receipt = json.loads(result.stdout)
        record = Path(receipt["path"])
        bucket = record.parents[1]
        assert bucket.name == hosts.slug_for(host) == compiled.compiled_record_path(home, bucket.name).stem
        assert cli.main(["show", receipt["id"], "--json"]) == 0
        assert git(home, "show", "HEAD:" + record.relative_to(home).as_posix()) == record.read_bytes()
    initial = {p: p.read_bytes() for p in (home / "projects").rglob("*") if p.is_file()}
    names_before = set((home / "projects").iterdir())
    assert len(names_before) == 2
    child("from self_learn import hosts; import sys; hosts.host_add(*sys.argv[1:], mode='plain')",
          home, str(host).swapcase(), "project")
    assert set((home / "projects").iterdir()) == names_before
    assert all(p.read_bytes() == data for p, data in initial.items())
    assert len(hosts.load_hosts(home).projects) == 2


@windows
def test_init_repairs_local_config_before_recovery(home, tmp_path):
    for key, value in (("core.autocrlf", b"false"), ("core.longpaths", b"true")):
        assert git(home, "config", "--local", "--get", key).strip() == value
    git(home, "config", "--unset", "core.longpaths")
    git(home, "config", "core.autocrlf", "true")
    assert ledger.init_home(home).already_complete
    assert git(home, "config", "--local", "--get", "core.longpaths").strip() == b"true"
    assert git(home, "config", "--local", "--get", "core.autocrlf").strip() == b"false"
    path = home / "test.txt"
    path.write_bytes(b"ledger LF\n")
    git(home, "add", "--", path.name)
    git(home, "commit", "-m", "LF control")
    fresh = tmp_path / "fresh"
    git(home, "worktree", "add", "--detach", str(fresh))
    assert git(fresh, "show", "HEAD:test.txt") == (fresh / path.name).read_bytes() == path.read_bytes()
    assert git(fresh, "status", "--porcelain", "-z") == b""
    path.write_bytes(b"ledger LF\r\n")
    with pytest.raises(ledger.InitError, match="test.txt"):
        ledger.init_home(home)
    assert path.read_bytes() == b"ledger LF\r\n"
