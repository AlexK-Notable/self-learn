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
    barrier = Path(sys.argv[2])
    writing = barrier.with_suffix(".writing")
    writing.write_text(f'{intent.id} {os.getpid()}', encoding='ascii')
    writing.replace(barrier)
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
    if kwargs["path"].suffix == ".jsonl":
        Path(sys.argv[1]).touch()
    return original(*args, **kwargs)
telemetry.locks.acquire = acquire
if sys.argv[2] == "append":
    telemetry.spool_event("offer-made", sequence=2)
else:
    from self_learn.cli import main
    raise SystemExit(main(["teach", "--user", "--no-push", "--fact", "concurrent lesson"]))
"""
    # Start the late producer only once flush owns the first data file.
    peers = []
    operation = "append"
    acquire = telemetry.locks.acquire
    def contend(fd, *, path, **kwargs):
        lease = acquire(fd, path=path, **kwargs)
        if path == seed and not peers:
            peers.append(subprocess.Popen([sys.executable, "-c", code, str(ready), operation]))
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

    # Repeat with a real teach as the competing producer. The record commits
    # before teach requests the spool lease, and its epilogue drains the late event.
    telemetry.spool_event("offer-made", sequence=3)
    peers.clear()
    ready.unlink()
    operation = "teach"
    try:
        assert telemetry.flush(home, push=False).events == 1
        assert peers[0].wait(timeout=35) == 0
    finally:
        for proc in peers:
            proc.kill()
            proc.wait()
    events = [json.loads(row) for row in git(home, "show", "HEAD:telemetry/" + seed.name).splitlines()[1:]]
    assert [event.get("sequence") for event in events] == [1, 2, 3, None]
    assert events[-1]["kind"] == "capture"
    record_id = events[-1]["record"]
    assert b"concurrent lesson" in git(home, "show", f"HEAD:user/pending/{record_id}.md")
    assert git(home, "status", "--porcelain", "-zuall") == status


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
    outside = spool.parent.parent / "guard"
    outside.write_bytes(b"outside spool")
    before = {p: p.read_bytes() for p in spool.parent.parent.rglob("*") if p.is_file()}
    for invalid in ("../nested/actor", "CON"):
        monkeypatch.setenv("SELF_LEARN_ACTOR", invalid)
        with pytest.raises(telemetry.TelemetryError):
            telemetry.spool_event("offer-made")
    assert {p: p.read_bytes() for p in spool.parent.parent.rglob("*") if p.is_file()} == before


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
    gitops.stage(home, [old.name, match.name])
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
    git(host, "init")
    git(host, "commit", "--allow-empty", "-m", "main worktree")
    linked = tmp_path / "linked checkout"
    git(host, "worktree", "add", "-b", "linked", str(linked))
    assert hosts.capture_host_path(home, linked) == host
    meta = record.parents[1] / "meta.yaml"
    other = tmp_path / "other registered target"
    other.mkdir()
    meta.write_text(f"path: {other.as_posix()}\n", encoding="utf-8")
    snapshot = git(home, "status", "--porcelain", "-zuall")
    head = git(home, "rev-parse", "HEAD")
    with pytest.raises(hosts.HostsError, match="verify"):
        hosts.host_add(home, host, "project", mode="plain")
    with pytest.raises(ValueError, match="verify"):
        gitops.host_lock_path(host, "plain")
    assert git(home, "status", "--porcelain", "-zuall") == snapshot
    assert git(home, "rev-parse", "HEAD") == head


@windows
def test_init_repairs_local_config_before_recovery(home, tmp_path, capsys, monkeypatch):
    from self_learn import cli

    for key, value in (("core.autocrlf", b"false"), ("core.longpaths", b"true")):
        assert git(home, "config", "--local", "--get", key).strip() == value
    git(home, "config", "--unset", "core.longpaths")
    git(home, "config", "core.autocrlf", "true")
    git(home, "config", "core.eol", "crlf")
    (home / ".gitattributes").write_bytes(b"* text=auto\n")
    assert cli.main(["init"]) == 0
    assert "repaired local Git configuration" in capsys.readouterr().out
    assert git(home, "config", "--local", "--get", "core.eol").strip() == b"lf"
    assert git(home, "config", "--local", "--get", "core.longpaths").strip() == b"true"
    assert git(home, "config", "--local", "--get", "core.autocrlf").strip() == b"false"
    path = home / "test.txt"
    path.write_bytes(b"ledger LF\n")
    git(home, "add", "--", path.name, ".gitattributes")
    git(home, "commit", "-m", "LF control")
    fresh = tmp_path / "fresh"
    git(home, "worktree", "add", "--detach", str(fresh))
    assert git(fresh, "show", "HEAD:test.txt") == (fresh / path.name).read_bytes() == path.read_bytes()
    assert git(fresh, "status", "--porcelain", "-z") == b""
    path.write_bytes(b"ledger LF\r\n")
    with pytest.raises(ledger.InitError, match="test.txt"):
        ledger.init_home(home)
    assert path.read_bytes() == b"ledger LF\r\n"
    path.write_bytes(b"ledger LF\n")
    (home / ".gitattributes").write_bytes(b"*.md text eol=crlf\n")
    git(home, "config", "core.autocrlf", "true")
    config = home / ".git" / "config"
    original = config.read_bytes()
    with pytest.raises(ledger.InitError, match="conflicting Git attribute"):
        ledger.init_home(home)
    assert config.read_bytes() == original
    foreign = tmp_path / "unrelated"
    foreign.mkdir()
    git(foreign, "init")
    git(foreign, "commit", "--allow-empty", "-m", "unrelated")
    foreign_config = foreign / ".git" / "config"
    original = foreign_config.read_bytes()
    with pytest.raises(ledger.InitError, match="ledger layout"):
        ledger.init_home(foreign)
    assert foreign_config.read_bytes() == original
    # A repair is needed before recovery can compare bytes, but a stopped
    # intent can still prevent the partial ledger from being topped up.
    (home / ".gitattributes").write_bytes(b"* text=auto\n")
    (home / "cases").rmdir()
    journal = home / ".intents"
    journal.mkdir(exist_ok=True)
    (journal / "broken.json").write_bytes(b"[]")
    before_stop = config.read_bytes()
    original_git = gitops._git
    config_writes = []
    def observe(repo, *args, **kwargs):
        if args[:2] == ("config", "--local") and "--get" not in args:
            config_writes.append(args)
        return original_git(repo, *args, **kwargs)
    monkeypatch.setattr(gitops, "_git", observe)
    with pytest.raises(intents.LedgerStoppedError):
        ledger.init_home(home)
    assert config_writes == [] and config.read_bytes() == before_stop and not (home / "cases").exists()
    broken = journal / "broken.json"
    broken.write_text(json.dumps({"id": "broken", "op": "test", "started": "now", "commit_subject": "test",
                                  "steps": [{"path": "missing.txt", "new_sha": None, "old_sha": "unrecoverable"}]}),
                      encoding="utf-8")
    with pytest.raises(intents.LedgerStoppedError, match="cannot restore missing.txt"):
        ledger.init_home(home)
    assert config_writes == [] and config.read_bytes() == before_stop
    broken.unlink()
    def lose_lock(*args, **kwargs):
        raise gitops.GitOpsError("lock failure witness")
    monkeypatch.setattr(intents, "ledger_write", lose_lock)
    with pytest.raises(ledger.InitError, match="lock failure witness"):
        ledger.init_home(home)
    assert config_writes and config.read_bytes() == before_stop


@windows
def test_cross_drive_pointer_and_git_rejection(home, monkeypatch):
    other_drive = "Z:" if home.drive.upper() != "Z:" else "Y:"
    target = Path(other_drive + "/other/record.md")
    assert names.pointer_token(home / "surface", target) == str(target)
    local = home / "in-root"
    local.touch()
    assert gitops.stage(home, [local.name]) == [local]
    calls = []
    monkeypatch.setattr(gitops, "_git", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(gitops.GitOpsError):
        gitops.stage(home, [target])
    assert calls == []


@windows
def test_foreign_registry_is_readable_and_preserved(home, tmp_path, capsys):
    from self_learn import cli
    from self_learn.records import Record
    registry = home / "hosts.yaml"
    registry.write_bytes(b"skills_root: null\nprojects:\n- path: /foreign/source\n  mode: plain\n")
    bucket = home / "projects" / "historical-linux-bucket"
    pending = bucket / "pending"
    pending.mkdir(parents=True)
    (bucket / "meta.yaml").write_bytes(b"path: /foreign/source\n")
    record = Record.create(type="knowledge", scope="project", source="teach", fact="Historical capture")
    path = pending / (record.id + ".md")
    path.write_bytes(record.to_text().encode("utf-8"))
    git(home, "add", "--", "hosts.yaml", "projects")
    git(home, "commit", "-m", "existing foreign ledger")
    before = registry.read_bytes()
    assert cli.main(["list", "--json"]) == 0
    item, = json.loads(capsys.readouterr().out)
    assert (item["id"], item["bucket"], item["host_registered"]) == (record.id, bucket.name, False)
    assert cli.main(["show", record.id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == record.id
    assert git(home, "show", "HEAD:" + path.relative_to(home).as_posix()) == path.read_bytes()
    assert hosts.load_hosts(home).projects == []
    host = tmp_path / "local"
    host.mkdir()
    assert cli.main(["host", "add", str(host), "--mode", "plain"]) != 0
    assert registry.read_bytes() == before and list(host.iterdir()) == []


@windows
def test_registration_reads_registry_under_shared_lock(home, tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    seen = []
    original = hosts.load_hosts

    def observed(root, **kwargs):
        seen.append(str(gitops.commit_lock_path(home)) in gitops._held_locks)
        return original(root, **kwargs)

    monkeypatch.setattr(hosts, "load_hosts", observed)
    hosts.host_add(home, first, "project", mode="plain")
    child("from self_learn import hosts; import sys; hosts.host_add(*sys.argv[1:], mode='plain')",
          home, second, "project")
    assert seen and all(seen)
    assert set(original(home).projects) == {first, second}
    assert (home / "hosts.yaml").read_bytes() == git(home, "show", "HEAD:hosts.yaml")


@windows
def test_flagged_spool_uses_verified_private_quarantine(home, monkeypatch, capsys):
    from types import SimpleNamespace
    import win32security
    from self_learn import cli

    spool = telemetry.spool_event("offer-made", witness="synthetic-marker")
    flagged = spool.read_bytes()
    # Blank and malformed physical lines precede the hit.
    spool.write_bytes(b"\n\xff\n" + flagged)
    telemetry.spool_event("offer-made", witness="clean sibling")
    original = spool.read_bytes()
    private = telemetry.rejected_dir()
    assert private == names.cache_root() / "private"
    private.mkdir()
    (private / "guard").write_bytes(b"ordinary existing directory")
    monkeypatch.setattr(telemetry, "secret_scan", lambda line: (
        [SimpleNamespace(rule="synthetic-rule")] if "synthetic-marker" in line else []))
    assert cli._flush_spool_best_effort(home, no_push=True) == "refused"
    err = capsys.readouterr().err
    assert spool.name + ":3: synthetic-rule" in err and "synthetic-marker" not in err
    assert spool.read_bytes() == original and list(private.iterdir()) == [private / "guard"]
    (private / "guard").unlink()
    private.rmdir()
    report = telemetry.flush(home, push=False)
    err = capsys.readouterr().err
    assert report.events == 1 and report.rejected == [spool.name + ":3: synthetic-rule"]
    saved, = private.iterdir()
    assert str(saved) in err and report.rejected[0] in err and "synthetic-marker" not in err
    assert saved.read_bytes() == flagged and spool.read_bytes() == b""
    acl = win32security.GetFileSecurity(str(saved), win32security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
    allowed = {win32security.ConvertSidToStringSid(acl.GetAce(i)[2]) for i in range(acl.GetAceCount())}
    import win32api
    import win32con
    from contextlib import closing
    with closing(win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)) as token:
        owner = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
    assert allowed == {owner, "S-1-5-18", "S-1-5-32-544"}
    blob = git(home, "show", "HEAD:telemetry/" + spool.name)
    assert json.loads(blob)["witness"] == "clean sibling"
    assert telemetry.flush(home, push=False).events == 0
    # An earlier verified folder can be replaced while the CLI process remains live.
    saved_dir = private.with_name("previous-private")
    private.rename(saved_dir)
    private.mkdir()
    guard = private / "guard"
    guard.write_bytes(b"ordinary replacement")
    telemetry.spool_event("offer-made", witness="synthetic-marker")
    before = spool.read_bytes()
    assert cli._flush_spool_best_effort(home, no_push=True) == "refused"
    assert spool.read_bytes() == before and list(private.iterdir()) == [guard]
    assert guard.read_bytes() == b"ordinary replacement"
    assert (saved_dir / saved.name).read_bytes() == flagged


@windows
@pytest.mark.parametrize("junction", ["cache", "spool"])
def test_committed_receipt_survives_cache_junction(home, tmp_path, junction):
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    guard = outside / "guard"
    guard.write_bytes(b"untouched")
    target = names.cache_root() if junction == "cache" else telemetry.spool_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(outside), str(target))
    assert target.is_junction() and target.samefile(outside)
    result = subprocess.run([sys.executable, "-m", "self_learn.cli", "teach", "--user",
                             "--no-push", "--json", "--fact", "committed exactly once"],
                            capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    path, = (home / "user" / "pending").glob("*.md")
    assert path == Path(receipt["path"]) and path.stem == receipt["id"]
    assert git(home, "show", "HEAD:" + path.relative_to(home).as_posix()) == path.read_bytes()
    assert git(home, "log", "--format=%s", "--grep=^self-learn: capture ").count(b"capture ") == 1
    assert b"telemetry spool failed" in result.stderr and b"telemetry flush refused" in result.stderr
    assert list(outside.iterdir()) == [guard] and guard.read_bytes() == b"untouched"


@windows
def test_flush_preflights_all_targets(home, tmp_path, monkeypatch):
    import _winapi
    first = telemetry.spool_event("offer-made", sequence=1)
    monkeypatch.setenv("SELF_LEARN_ACTOR", "z-last")
    last = telemetry.spool_event("offer-made", sequence=2)
    assert first.name < last.name
    outside = tmp_path / "outside"
    outside.mkdir()
    bad = home / "telemetry" / last.name
    _winapi.CreateJunction(str(outside), str(bad))
    before = [first.read_bytes(), last.read_bytes(), git(home, "rev-parse", "HEAD")]
    with pytest.raises(telemetry.TelemetryError):
        telemetry.flush(home, push=False)
    assert before == [first.read_bytes(), last.read_bytes(), git(home, "rev-parse", "HEAD")]
    assert not (bad.parent / first.name).exists() and list(outside.iterdir()) == []
    bad.rmdir()
    assert telemetry.flush(home, push=False).events == 2


@windows
@pytest.mark.parametrize("behind", [False, True], ids=["fast-forward", "remote-moved"])
def test_plain_teach_pushes_to_local_remote(home, tmp_path, monkeypatch, capsys, behind):
    from self_learn import cli

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    branch = git(home, "branch", "--show-current").decode().strip()
    dirty = home / "unrelated.txt"
    dirty.write_bytes(b"clean original\n")
    git(home, "add", "--", dirty.name)
    git(home, "commit", "-m", "base")
    git(home, "remote", "add", "origin", str(remote))
    git(home, "push", "-u", "origin", branch)
    upstream = git(remote, "rev-parse", branch)
    if behind:
        peer = tmp_path / "peer"
        git(tmp_path, "clone", "-b", branch, str(remote), str(peer))
        (peer / "peer.txt").write_bytes(b"independent remote change\n")
        git(peer, "add", "--", "peer.txt")
        git(peer, "commit", "-m", "peer advanced")
        git(peer, "push")
        assert git(remote, "rev-parse", branch) != upstream
    dirty.write_bytes(b"local dirty content\n")
    calls = []
    original_git = gitops._git

    def observe(repo, *args, **kwargs):
        result = original_git(repo, *args, **kwargs)
        if args[0] in ("push", "pull"):
            calls.append((args, result.returncode))
        return result

    monkeypatch.setattr(gitops, "_git", observe)
    assert cli.main(["teach", "--user", "--json", "--fact", "native push witness"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    path = Path(receipt["path"])
    assert path.read_bytes() == git(remote, "show", branch + ":" + path.relative_to(home).as_posix())
    assert git(home, "rev-parse", "HEAD") == git(remote, "rev-parse", branch)
    assert dirty.read_bytes() == b"local dirty content\n"
    assert git(home, "status", "--porcelain", "-z") == b" M unrelated.txt\0"
    assert calls[0][0] == ("push", "-q") and (calls[0][1] != 0) == behind
    assert [(args, rc) for args, rc in calls if args[0] == "pull"] == (
        [(("pull", "--rebase", "--autostash", "-q"), 0)] if behind else [])
    if behind:
        assert (home / "peer.txt").read_bytes() == b"independent remote change\n"


@windows
def test_windows_git_error_contracts(home, tmp_path, monkeypatch):
    from self_learn.primitives import _capture_windows as native

    with pytest.raises(gitops.GitOpsError):
        gitops._git(home, "add", "--", str(tmp_path / "outside"))
    assert native.git_argv(home, ("commit", "-m", "--", "-m", "check-ignore", "--", "literal[1]")) == [
        "git.exe", "-C", str(home), "--literal-pathspecs", "commit", "-m", "--", "-m", "check-ignore",
        "--", "literal[1]"]
    # A commit message can also spell the global option itself.
    assert native.git_argv(home, ("commit", "-m", "--literal-pathspecs", "--", "literal[1]")) == [
        "git.exe", "-C", str(home), "--literal-pathspecs", "commit", "-m", "--literal-pathspecs",
        "--", "literal[1]"]
    with monkeypatch.context() as m:
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        m.setattr(native.procs, "run_bounded", timeout)
        with pytest.raises(gitops.GitOpsError, match="exceeded"):
            native.git_bytes(home, "status", timeout=1)
        with pytest.raises(ledger.InitError, match="exceeded"):
            ledger._configure_windows_ledger(home, {})
    host = tmp_path / "main"
    host.mkdir()
    git(host, "init")
    git(host, "commit", "--allow-empty", "-m", "main")
    linked = tmp_path / "linked"
    git(host, "worktree", "add", "-b", "linked", str(linked))
    hosts.host_add(home, host, "project")
    assert hosts.capture_host_path(home, linked) == host
    def unavailable(*args, **kwargs):
        raise gitops.GitOpsError("worktree enumeration unavailable")
    monkeypatch.setattr(native, "git_bytes", unavailable)
    assert hosts.capture_host_path(home, linked) == linked


@windows
def test_first_capture_heals_missing_project_meta(home, tmp_path, monkeypatch, capsys):
    from self_learn import cli
    project = tmp_path / "project"
    project.mkdir()
    hosts.host_add(home, project, "project", mode="plain")
    monkeypatch.chdir(project)
    bucket = home / "projects" / hosts.slug_for(project)
    bucket.mkdir()
    assert not list(bucket.iterdir())
    assert cli.main(["teach", "--project", "--no-push", "--json", "--fact", "recover first capture"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    from self_learn import ledger_ops
    assert ledger_ops.bucket_project_path(bucket) == project
    assert Path(receipt["path"]).parents[1] == bucket
    assert git(home, "show", "HEAD:" + (bucket / "meta.yaml").relative_to(home).as_posix()) == (bucket / "meta.yaml").read_bytes()


@windows
def test_repair_hints_follow_capabilities_and_statement_captures(home, tmp_path, monkeypatch, capsys):
    from self_learn import cli, statements, teach
    from self_learn.primitives import capabilities
    source = tmp_path / "sessions"
    project = source / "test-project"
    project.mkdir(parents=True)
    row = {"type": "user", "message": {"content": "Keep it small."}}
    (project / "synthetic-stmt.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (home / "config.yaml").write_text("refs:\n  transcript_roots: " + json.dumps(str(source)) + "\n", encoding="utf-8")
    assert cli.main(["teach", "--user", "--fact", "small changes", "--no-push",
                     "--session", "synthetic-stmt", "--statement", "Keep it small."]) == 0
    item, = statements.list_statements(home)
    assert item["source"]["message_ref"] == "transcript:synthetic-stmt#L1"
    assert b"Keep it small." in git(home, "show", "HEAD:user-statements.jsonl")
    assert len(list((home / "user" / "pending").glob("*.md"))) == 1
    capsys.readouterr()
    assert "not available on Windows yet" in teach._statement_retry_hint("words", "ref")
    with monkeypatch.context() as m:
        m.setattr(cli, "_main", lambda *args: (_ for _ in ()).throw(gitops.GitOpsError("test")))
        assert cli._netted_main([]) == cli.EXIT_GIT_FAILED
        assert "self-learn reconcile and self-learn status are not available" in capsys.readouterr().err
    with monkeypatch.context() as m:
        m.setattr(gitops, "push_pending", lambda *args, **kwargs: gitops.PushResult(ok=False))
        assert cli.main(["teach", "--user", "--fact", "push hint witness"]) == 0
        assert "self-learn push is not available on Windows yet" in capsys.readouterr().err
    with monkeypatch.context() as m:
        def refuse_stage(*args, **kwargs):
            raise gitops.GitOpsError("stage failure witness")
        m.setattr(gitops, "stage", refuse_stage)
        assert cli.main(["teach", "--user", "--no-push", "--fact", "stage hint witness"]) == teach.EXIT_HALF_WRITTEN
        err = capsys.readouterr().err
        assert "CAPTURE NOT COMMITTED" in err and "self-learn reconcile is not available on Windows yet" in err
    intent = intents.intents_dir(home) / "broken.json"
    intent.parent.mkdir(exist_ok=True)
    intent.write_bytes(b'{"id":"broken","steps":null}')
    with pytest.raises(intents.LedgerStoppedError, match="self-learn reconcile is not available"):
        with intents.ledger_write(home):
            pytest.fail("a malformed intent must stop the writer")
    with pytest.raises(hosts.HostsError, match="kind must be"):
        hosts.host_add(home, tmp_path, "invalid")
    monkeypatch.setitem(capabilities.AVAILABLE, "ledger", True)
    assert "not available" not in teach._statement_retry_hint("words", "ref")
    with pytest.raises(intents.LedgerStoppedError) as stopped:
        with intents.ledger_write(home):
            pytest.fail("the malformed intent still exists")
    assert "not available" not in str(stopped.value)


@windows
@pytest.mark.parametrize("setup", ["git-init", "empty-clone"])
def test_init_bootstraps_empty_repository(tmp_path, monkeypatch, capsys, setup):
    from self_learn import cli

    env = scratch_env(tmp_path)
    for key, value in env.items():
        if os.environ.get(key) != value:
            monkeypatch.setenv(key, value)
    root = Path(env["SELF_LEARN_HOME"])
    if setup == "empty-clone":
        remote = tmp_path / "upstream.git"
        git(tmp_path, "init", "--bare", str(remote))
        git(tmp_path, "clone", str(remote), str(root))
    else:
        git(tmp_path, "init", str(root))
    remotes = git(root, "remote", "-v")
    assert bool(remotes) == (setup == "empty-clone")
    git(root, "config", "--local", "core.autocrlf", "true")
    config = root / ".git" / "config"
    before = config.read_bytes()
    witness = root / "work.txt"
    witness.write_bytes(b"existing work\n")
    for staged in (False, True):
        if staged:
            git(root, "add", "--", witness.name)
        status = git(root, "status", "--porcelain", "-z")
        assert status.startswith(b"A " if staged else b"??")
        with pytest.raises(ledger.InitError, match="Choose an empty repository"):
            ledger.init_home(root)
        assert config.read_bytes() == before
        assert git(root, "status", "--porcelain", "-z") == status
    git(root, "rm", "--cached", "--", witness.name)
    witness.unlink()
    assert git(root, "status", "--porcelain", "-z") == b""
    assert cli.main(["init"]) == 0
    output = capsys.readouterr().out
    assert "topped up" in output and "repaired local Git configuration" in output
    assert all((root / name).is_dir() for name in ledger._LAYOUT)
    assert git(root, "log", "--format=%s").decode().splitlines() == [ledger.INIT_COMMIT_SUBJECT]
    assert git(root, "ls-tree", "-z", "HEAD") == b""
    assert [git(root, "config", "--local", "--get", key).strip() for key in
            ("core.autocrlf", "core.longpaths", "core.eol")] == [b"false", b"true", b"lf"]
    assert git(root, "remote", "-v") == remotes
    assert cli.main(["init"]) == 0 and "already complete" in capsys.readouterr().out
    assert git(root, "rev-list", "--count", "HEAD").strip() == b"1"


@windows
def test_init_finds_original_subject_in_clone(home, tmp_path):
    git(home, "commit", "--allow-empty", "-m", "later commit", "-m", ledger.INIT_COMMIT_SUBJECT)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(home), str(clone))
    head = git(clone, "rev-parse", "HEAD")
    assert ledger.home_state(clone) == "uninitialized"
    assert set(ledger.init_home(clone).added_dirs) == set(ledger._LAYOUT)
    assert git(clone, "rev-parse", "HEAD") == head


@windows
def test_init_reports_failed_config_rollback(home, monkeypatch):
    (home / "cases").rmdir()
    git(home, "config", "--local", "core.eol", "crlf")
    with monkeypatch.context() as m:
        def fail_recovery(*args, **kwargs):
            def unavailable(*args, **kwargs):
                raise gitops.GitOpsError("rollback lock busy")
            m.setattr(gitops, "commit_lock", unavailable)
            raise gitops.GitOpsError("recovery lock lost")

        m.setattr(intents, "ledger_write", fail_recovery)
        with pytest.raises(ledger.InitError) as failed:
            ledger.init_home(home)
    message = str(failed.value)
    assert all(word in message for word in ("recovery lock lost", str(home / ".git" / "config"), "rollback lock busy"))
    assert git(home, "config", "--local", "--get", "core.eol").strip() == b"lf"
    assert ledger.init_home(home).added_dirs == ("cases",)


@windows
@pytest.mark.parametrize("store", ["symlink", "malformed"])
def test_statement_failure_preserves_committed_receipt(home, tmp_path, store):
    source = tmp_path / "sessions"
    project = source / "project"
    project.mkdir(parents=True)
    quote = "Keep changes small."
    row = {"type": "user", "message": {"content": quote}}
    (project / "statement-witness.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (home / "config.yaml").write_text("refs:\n  transcript_roots: " + json.dumps(str(source)) + "\n", encoding="utf-8")
    path = home / "user-statements.jsonl"
    outside = tmp_path / "outside.jsonl"
    if store == "symlink":
        outside.write_bytes(b"\n")
        path.symlink_to(outside)
    else:
        path.write_bytes(b"null\n")
    before = path.read_bytes()
    result = subprocess.run([sys.executable, "-m", "self_learn.cli", "teach", "--user", "--no-push",
                             "--json", "--fact", "post-commit witness", "--session", "statement-witness",
                             "--statement", quote], capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    record, = (home / "user" / "pending").glob("*.md")
    assert record == Path(receipt["path"]) and record.stem == receipt["id"]
    assert git(home, "show", "HEAD:" + record.relative_to(home).as_posix()) == record.read_bytes()
    assert len(git(home, "log", "--format=%s", "--grep=^self-learn: capture ").splitlines()) == 1
    assert b"the lesson was captured, but --statement failed" in result.stderr
    assert b"Do not run teach again" in result.stderr and b"self-learn statement add" in result.stderr
    assert b"Traceback" not in result.stderr
    assert path.read_bytes() == before and git(home, "ls-files", "-z", "--", path.name) == b""
    if store == "symlink":
        assert path.is_symlink() and outside.read_bytes() == before
