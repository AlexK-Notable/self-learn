"""S-164. Exercise the private interface with independent open file descriptions."""

from __future__ import annotations

import errno
import io
import os
import queue
import stat
import subprocess
import sys
import textwrap
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn.primitives import locks

posix = pytest.mark.skipif(os.name == "nt", reason="native locking begins in Stage 3")


class _Peer:
    def __init__(self, proc):
        self.proc = proc
        self.lines = queue.Queue()

        def read_pipe():
            for line in proc.stdout:
                self.lines.put(line.rstrip("\n"))
            self.lines.put("<EOF>")

        self.reader = threading.Thread(target=read_pipe, daemon=True)
        self.reader.start()

    def send(self, command):
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def expect(self, line):
        assert self.lines.get(timeout=8) == line


@contextmanager
def _peer(path, body):
    script = (
        "import sys, time\nfrom pathlib import Path\nfrom self_learn.primitives import locks\n"
        "path = Path(sys.argv[1])\n" + textwrap.dedent(body)
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", script, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    peer = _Peer(proc)
    try:
        yield peer
    finally:
        proc.stdin.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=8)
        peer.reader.join(timeout=8)
        assert not peer.reader.is_alive()
        proc.stdout.close()


_HOLDER = """
    with locks.open_lock(path, purpose="append") as fh, locks.acquire(
        fh.fileno(), path=path, wait=None
    ):
        print("HELD")
        assert input() == "release"
    print("RELEASED")
"""

_PROBE = """
    with locks.open_lock(path, purpose="append") as fh:
        for command in sys.stdin:
            try:
                lease = locks.acquire(fh.fileno(), path=path, wait=0)
            except BlockingIOError:
                print("BUSY")
            else:
                lease.release()
                print("ACQUIRED")
"""


def _probe(peer, expected):
    peer.send("probe")
    peer.expect(expected)


@posix
def test_try_timed_blocking_between_interpreters(tmp_path):
    path = tmp_path / "owner"
    waiter = """
        with locks.open_lock(path, purpose="append") as fh:
            for wait in (0, -1, 0.12):
                start = time.monotonic()
                try:
                    locks.acquire(fh.fileno(), path=path, wait=wait)
                except BlockingIOError:
                    elapsed = time.monotonic() - start
                    assert max(0, wait) <= elapsed < 3
                    print("BUSY", wait)
            print("WAITING")
            with locks.acquire(fh.fileno(), path=path, wait=None):
                print("ACQUIRED")
            print("DONE")
    """
    with _peer(path, _HOLDER) as owner:
        owner.expect("HELD")
        with _peer(path, waiter) as contender:
            for wait in (0, -1, 0.12):
                contender.expect(f"BUSY {wait}")
            contender.expect("WAITING")
            with _peer(tmp_path / "other", _PROBE) as control:
                _probe(control, "ACQUIRED")
            # A default ten-second timeout would report failure or EOF here.
            with pytest.raises(queue.Empty):
                contender.lines.get(timeout=10.2)
            owner.send("release")
            owner.expect("RELEASED")
            contender.expect("ACQUIRED")
            contender.expect("DONE")
            assert contender.proc.wait(timeout=8) == 0


@posix
def test_nested_repo_section_keeps_peer_out(tmp_path):
    path = tmp_path / "repo.lock"
    def section():
        return locks.repo_section(path, 0, "host", timeout_error=ValueError)

    with _peer(path, _PROBE) as contender:
        with section():
            _probe(contender, "BUSY")
            with section():
                _probe(contender, "BUSY")
            _probe(contender, "BUSY")
        _probe(contender, "ACQUIRED")


@posix
def test_owner_death_releases_with_exec_child_alive(tmp_path):
    path = tmp_path / "owner.lock"
    # The exec child inherits the owner's command pipes. close_fds=False
    # deliberately gives a mistakenly inheritable lock fd a chance to escape.
    owner_script = """
        import subprocess
        with locks.open_lock(path, purpose="append") as fh, locks.acquire(
            fh.fileno(), path=path, wait=None
        ):
            print("HELD")
            child = 'print("READY"); assert input() == "ping"; print("ALIVE")'
            subprocess.run([sys.executable, "-u", "-c", child], close_fds=False,
                           timeout=30, check=True)
    """
    with _peer(path, owner_script) as owner, _peer(path, _PROBE) as contender:
        owner.expect("HELD")
        owner.expect("READY")
        _probe(contender, "BUSY")
        owner.proc.kill()
        assert owner.proc.wait(timeout=8) != 0
        _probe(contender, "ACQUIRED")
        owner.send("ping")
        owner.expect("ALIVE")


@posix
def test_held_set_identity_and_pid_probe(tmp_path):
    from self_learn import gitops, intents
    from support import make_home

    home = make_home(tmp_path)
    path = gitops.commit_lock_path(home)
    assert gitops._held_locks is locks._held_locks
    pid = f"{os.getpid()}\n".encode()
    with gitops.commit_lock(home):
        with gitops.commit_lock(home):
            assert locks.held_here(path) and str(path) in gitops._held_locks
            assert path.read_bytes() == pid
            assert intents.classify_status(home).probe == "busy"
            assert path.read_bytes() == pid
        assert locks.held_here(path)
    assert not locks.held_here(path)
    assert intents.classify_status(home).probe == "ok"
    assert path.read_bytes() == pid


@posix
def test_deadline_survives_inode_reopen(tmp_path, monkeypatch):
    import fcntl
    from self_learn.primitives import _locks_posix as backend

    path = tmp_path / "replace.lock"
    clock_reads, sleeps, inodes = [], [], []
    def now():
        clock_reads.append(1)
        return 10.0 + len(clock_reads) / 100

    real_flock = fcntl.flock
    attempts = 0
    def contend_then_replace(fd, flags):
        nonlocal attempts
        if flags != fcntl.LOCK_UN:
            assert flags == fcntl.LOCK_EX | fcntl.LOCK_NB
            attempts += 1
            if attempts in (1, 3):
                raise BlockingIOError()
        real_flock(fd, flags)
        if flags != fcntl.LOCK_UN:
            inodes.append(os.fstat(fd).st_ino)
            if attempts == 2:
                path.unlink()
                path.touch()  # allocate while the old inode is still held

    monkeypatch.setattr(backend, "time", SimpleNamespace(monotonic=now, sleep=sleeps.append))
    monkeypatch.setattr(fcntl, "flock", contend_then_replace)
    with locks.repo_section(path, 1, "commit", timeout_error=RuntimeError):
        assert path.stat().st_ino == inodes[1] != inodes[0]
    assert sleeps == [0.02, 0.02]
    assert len(clock_reads) == 3  # one budget, then a check on each busy result


@posix
def test_probe_creation_and_flags(tmp_path, monkeypatch):
    import fcntl
    from self_learn import intents
    from self_learn.primitives import _locks_posix as backend

    path = tmp_path / "probe"
    private = tmp_path / "private"
    mask = os.umask(0o027)
    try:
        with locks.open_lock(path, purpose="probe") as fh:
            assert isinstance(fh, io.FileIO) and not fh.writable()
            assert fcntl.fcntl(fh, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
            assert stat.S_IMODE(path.stat().st_mode) == 0o750
        with locks.open_lock(private, purpose="private") as fh:
            assert isinstance(fh, io.FileIO) and fh.writable() and fh.readable()
            assert stat.S_IMODE(private.stat().st_mode) == 0o600
            fh.write(b"payload")
        with locks.open_lock(private, purpose="private") as fh:
            assert fh.read() == b"payload"
    finally:
        os.umask(mask)
    assert intents.os is backend.os
    failed = []
    def fail_wrap(fd, mode, buffering):
        failed.append(fd)
        raise OSError("wrap failed")

    with path.open("rb") as control:
        monkeypatch.setattr(backend.os, "fdopen", fail_wrap)
        with pytest.raises(OSError, match="wrap failed"):
            locks.open_lock(path, purpose="probe")
        assert len(failed) == 1
        with pytest.raises(OSError) as closed:
            os.fstat(failed[0])
        assert closed.value.errno == errno.EBADF
        assert os.fstat(control.fileno()).st_ino == path.stat().st_ino


@posix
def test_text_open_modes_and_sentinel_deadline(tmp_path, monkeypatch, capsys):
    import inspect
    from self_learn import gitops, sentinel
    from self_learn.primitives import _locks_posix as backend

    path = tmp_path / "sentinel"
    lock_path = sentinel._lock_path(path)
    with locks.open_lock(lock_path, purpose="truncate") as fh:
        assert fh.mode == "w" and fh.encoding == "utf-8"
        fh.write("first")
    with locks.open_lock(lock_path, purpose="append") as fh:
        assert fh.mode == "a" and fh.encoding == "utf-8"
        fh.write(" second")
    with locks.open_lock(lock_path, purpose="append-read") as fh:
        assert fh.mode == "a+" and fh.encoding == "utf-8"
        fh.seek(0)
        assert fh.read() == "first second"

    assert gitops.time is sentinel.time is backend.time
    assert gitops.COMMIT_LOCK_TIMEOUT == 150
    assert inspect.signature(sentinel._lock_section).parameters["timeout"].default == 5
    reads = iter([1.0, 1.001, 1.011])
    sleeps = []
    monkeypatch.setattr(backend, "time", SimpleNamespace(monotonic=reads.__next__, sleep=sleeps.append))
    with _peer(lock_path, _HOLDER) as owner:
        owner.expect("HELD")
        with sentinel._lock_section(path, timeout=0.01) as acquired:
            assert acquired is False
        assert sleeps == [0.01]
        assert capsys.readouterr().err == (
            f"self-learn sentinel: lock timeout after 0.01s waiting for {lock_path} — "
            f"treating as contended, not adopting {path}\n"
        )
        assert lock_path.read_bytes() == b"first second"
        # A competing repo open truncates before taking its first try.
        monkeypatch.setattr(backend, "time", SimpleNamespace(monotonic=lambda: 1))
        with pytest.raises(gitops.GitOpsError) as exc:
            with gitops._flock_lock(lock_path, 0.0, "host"):
                pytest.fail("busy repo section entered")
        assert str(exc.value) == (
            f"host lock {lock_path} still held after 0s — another self-learn "
            "producer (worker/miner/verb) is wedged mid-host"
        )
        assert exc.value.__suppress_context__ and exc.value.__cause__ is None
        assert lock_path.read_bytes() == b""
        owner.send("release")
        owner.expect("RELEASED")


@posix
def test_raw_flock_interoperates_both_directions(tmp_path):
    import fcntl

    path = tmp_path / "raw.lock"
    with _peer(path, _PROBE) as contender, path.open("a") as raw:
        fcntl.flock(raw, fcntl.LOCK_EX)
        _probe(contender, "BUSY")
        fcntl.flock(raw, fcntl.LOCK_UN)
        _probe(contender, "ACQUIRED")
        with _peer(path, _HOLDER) as owner:
            owner.expect("HELD")
            with pytest.raises(BlockingIOError):
                fcntl.flock(raw, fcntl.LOCK_EX | fcntl.LOCK_NB)
            owner.send("release")
            owner.expect("RELEASED")
            fcntl.flock(raw, fcntl.LOCK_EX | fcntl.LOCK_NB)


@posix
def test_retire_busy_then_idle(tmp_path, monkeypatch):
    path = tmp_path / "retire.lock"
    with _peer(path, _HOLDER) as owner:
        owner.expect("HELD")
        inode = path.stat().st_ino
        assert locks.can_retire_idle()
        assert not locks.retire_if_idle(path)
        assert path.stat().st_ino == inode
        owner.send("release")
        owner.expect("RELEASED")
    with _peer(path, _PROBE) as contender:
        _probe(contender, "ACQUIRED")
        real_unlink = os.unlink
        def observe_unlink(target):
            assert target == path and path.stat().st_ino == inode
            _probe(contender, "BUSY")
            real_unlink(target)
        with monkeypatch.context() as patch:
            patch.setattr(os, "unlink", observe_unlink)
            assert locks.retire_if_idle(path)
        assert not path.exists()


@posix
def test_lease_exit_and_unlock_error_dispositions(tmp_path, monkeypatch):
    import fcntl
    from self_learn import ask, miner, steward, summarise

    path = tmp_path / "turn.lock"
    real_flock = fcntl.flock
    explicit, nonblocking, unlock = fcntl.LOCK_EX, fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN
    calls, streams = [], []
    faults = {}
    real_open = locks.open_lock

    def observe_open(path, *, purpose):
        fh = real_open(path, purpose=purpose)
        streams.append(fh)  # keep it alive so implicit GC cannot disguise a missing close
        close = fh.close
        def observe_close():
            calls.append("close")
            close()
        fh.close = observe_close
        return fh

    def flock(fd, flags):
        assert os.fstat(fd)  # release must precede close
        calls.append(flags)
        if flags in faults:
            raise faults[flags]
        real_flock(fd, flags)

    monkeypatch.setattr(locks, "open_lock", observe_open)
    monkeypatch.setattr(fcntl, "flock", flock)
    with locks.open_lock(path, purpose="append") as fh, _peer(path, _PROBE) as contender:
        lease = locks.acquire(fh.fileno(), path=path, wait=None)
        with pytest.raises(ValueError, match="body"), lease as entered:
            assert entered is lease
            _probe(contender, "BUSY")
            raise ValueError("body")
        lease.release()
        assert calls == [explicit, unlock]
        _probe(contender, "ACQUIRED")
        assert not fh.closed

    calls.clear()
    lock = ask._TurnLock(tmp_path)
    assert lock.acquire()
    faults[unlock] = OSError("unlock failed")
    with pytest.raises(OSError, match="unlock failed"):
        lock.release()
    assert calls == [nonblocking, unlock] and not streams[-1].closed
    del faults[unlock]
    lock.release()  # failed unlock left a live lease
    assert calls == [nonblocking, unlock, unlock, "close"] and streams[-1].closed

    calls.clear()
    faults[nonblocking] = BlockingIOError()
    faults[unlock] = OSError("unlock failed")
    result = miner._run_job(tmp_path, preview=True, no_push=True)
    assert result.status == "busy"
    assert calls == [nonblocking, unlock, "close"] and streams[-1].closed
    assert miner._LOG_TO is None

    calls.clear()
    del faults[nonblocking]
    def fail_in_miner():
        raise ValueError("miner body")

    monkeypatch.setattr(miner, "_now_iso", fail_in_miner)
    with pytest.raises(ValueError, match="miner body"):
        miner._run_job(tmp_path, preview=True, no_push=True)
    assert calls == [nonblocking, unlock, "close"] and streams[-1].closed

    calls.clear()
    faults[explicit] = OSError("journal acquire failed")
    with pytest.raises(OSError, match="unlock failed"):
        summarise._journal(tmp_path, {"row": 1})
    assert calls == [explicit, unlock] and not streams[-1].closed
    streams[-1].close()
    del faults[unlock]
    calls.clear()
    summarise._journal(tmp_path, {"row": 2})
    assert calls == [explicit, unlock, "close"] and streams[-1].closed

    # Stop at the first protected step. A raising body unwinds the steward
    # lease, then its stream. The stream close is the only Linux unlock.
    calls.clear()
    faults[unlock] = OSError("unexpected explicit unlock")
    monkeypatch.setattr(steward.intents, "recover", lambda home: SimpleNamespace(stopped=[]))
    steward_path = steward.cache_dir(tmp_path) / "steward.lock"
    with _peer(steward_path, _PROBE) as contender:
        def end_run(home):
            _probe(contender, "BUSY")
            raise ValueError("steward body")
        monkeypatch.setattr(steward, "_reconcile_runs", end_run)
        with pytest.raises(ValueError, match="steward body"):
            steward._run(tmp_path, dry_run=True)
        assert calls == [nonblocking, "close"] and streams[-1].closed
        _probe(contender, "ACQUIRED")


@posix
def test_worker_uncontended_spawn(tmp_path, monkeypatch):
    from self_learn import worker

    calls = []
    def spawn(home, *, no_push):
        marker = (worker.cache_dir() / "worker.window").read_text().strip()
        calls.append((home, no_push, marker))
        return 321

    monkeypatch.setattr(worker, "_spawn_window", spawn)
    monkeypatch.setattr(worker, "_ceiling_refused", lambda: False)
    assert worker._open_window(tmp_path, no_push=True) == "spawned"
    assert calls == [(tmp_path, True, worker._SPAWN_MARKER)]
    assert (worker.cache_dir() / "worker.window").read_text().strip() == "321"


@posix
def test_flush_preserves_unrelated_staged_bytes(tmp_path, monkeypatch):
    from self_learn import telemetry
    from support import make_home

    home = make_home(tmp_path)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=home, timeout=8)

    unrelated = home / "unrelated"
    unrelated.write_bytes(b"staged\n")
    git("add", "--", unrelated.name)
    unrelated.write_bytes(b"unstaged\n")
    status = git("status", "--porcelain=v1", "-z")
    assert b"AM unrelated\0" in status
    index = git("ls-files", "--stage", "--", unrelated.name)
    assert git("show", ":unrelated") == b"staged\n"
    spool = telemetry.spool_event("offer-made")
    payload = spool.read_bytes()
    other = spool.with_name("z-last.jsonl")
    other.write_bytes(payload)
    spools = [spool, other]
    inodes = [path.stat().st_ino for path in spools]
    spool_order, target_inodes = [], []
    acquire = locks.acquire
    acquire_target = locks.acquire_ledger_target

    def record_acquire(fd, **kwargs):
        if kwargs["path"].parent == spool.parent:
            assert kwargs["wait"] is None and os.fstat(fd).st_ino == kwargs["path"].stat().st_ino
            spool_order.append(kwargs["path"])
        return acquire(fd, **kwargs)

    def record_target(fd):
        target_inodes.append(os.fstat(fd).st_ino)
        return acquire_target(fd)

    monkeypatch.setattr(locks, "acquire", record_acquire)
    monkeypatch.setattr(locks, "acquire_ledger_target", record_target)
    report = telemetry.flush(home, push=False)
    assert report.events == 2 and [p.name for p in report.files] == [p.name for p in spools]
    assert spool_order == spools and target_inodes == [p.stat().st_ino for p in report.files]
    for target, source, inode in zip(report.files, spools, inodes, strict=True):
        assert git("show", "HEAD:" + target.relative_to(home).as_posix()) == payload
        assert source.stat().st_ino == inode and source.read_bytes() == b""
    assert git("status", "--porcelain=v1", "-z") == status
    assert git("ls-files", "--stage", "--", unrelated.name) == index


def test_stub_import_then_first_use(tmp_path):
    # A fresh interpreter applies the Stage 0 floor before product imports.
    # Linux also exercises lazy imports, with fcntl unavailable and only the
    # facade's dispatch selector simulated. The native runner uses its real OS.
    cli_root = Path(__file__).resolve().parents[1]
    guard = tmp_path / "guard"
    guard.mkdir()
    control = guard / "control"
    control.write_bytes(b"writable")
    script = """
        import os, runpy, sys
        from pathlib import Path
        from types import SimpleNamespace
        cli, guard = map(Path, sys.argv[1:])
        floor = runpy.run_path(str(cli / "_test_home_floor.py"))
        with floor["home_floor"]() as profile:
            if os.name == "nt":
                assert profile.is_dir() and Path.home() == profile
            sys.modules["fcntl"] = None
            from self_learn import cli as product_cli, settings
            from self_learn.primitives import locks
            for root in (cli, cli.parent / "ui"):
                config = runpy.run_path(str(root / "tests" / "conftest.py"))
                assert callable(config["_gitops_mod"]._flock_lock)
            assert "self_learn.primitives._locks_posix" not in sys.modules
            if os.name != "nt":
                locks.os = SimpleNamespace(name="nt")
            assert not locks.can_retire_idle()
            path = guard / "missing" / "repo.lock"
            section = locks.repo_section(path, 0, "commit", timeout_error=ValueError)
            for call in (lambda: locks.open_lock(guard / "direct", purpose="truncate"),
                         section.__enter__, lambda: locks.acquire(-1, path=path, wait=None),
                         lambda: locks.acquire_ledger_target(-1), lambda: locks.release_open(-1, None),
                         lambda: locks.retire_if_idle(path), lambda: locks.held_here(path)):
                try:
                    call()
                except NotImplementedError:
                    pass
                else:
                    raise AssertionError("operation did not raise NotImplementedError")
            assert (guard / "control").read_bytes() == b"writable"
    """
    subprocess.run([sys.executable, "-c", textwrap.dedent(script), str(cli_root), str(guard)],
                   check=True, timeout=15)
    assert list(guard.iterdir()) == [control]
