"""File publication contracts across the platform boundary (S-166)."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap

import pytest

from self_learn.primitives import fsops


linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux filesystem contract")


@linux
def test_publish_and_modes_under_umask(tmp_path):
    path = tmp_path / "published"
    previous = os.umask(0o027)
    try:
        fsops.atomic_write(str(path), "café", encoding="latin-1")
        assert path.read_bytes() == b"caf\xe9"
        assert stat.S_IMODE(path.stat().st_mode) == 0o640

        path.chmod(0o673)
        with path.open("rb") as old:
            fsops.atomic_write(path, b"next\x00")
            assert old.read() == b"caf\xe9"
            assert path.read_bytes() == b"next\x00"
        assert stat.S_IMODE(path.stat().st_mode) == 0o673

        fsops.atomic_write(path, b"explicit", mode=0o757)
        assert (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) == (b"explicit", 0o757)
        fsops.private_write(path, "private\n")
        assert (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) == (b"private\n", 0o600)
    finally:
        os.umask(previous)


@linux
def test_replace_staged_entry_and_error_fields(tmp_path, monkeypatch):
    src, dst = tmp_path / "stage", tmp_path / "published"
    missing, referent = tmp_path / "missing", tmp_path / "referent"
    referent.write_bytes(b"referent")
    dst.symlink_to(missing)
    src.write_bytes(b"regular")
    fsops.replace_staged(str(src), dst)
    assert dst.is_file() and not dst.is_symlink() and dst.read_bytes() == b"regular"
    assert {p.name for p in tmp_path.iterdir()} == {"published", "referent"}

    src.symlink_to(referent.name)
    fsops.replace_staged(src, dst, method="path")
    assert dst.readlink() == Path(referent.name)
    assert {p.name for p in tmp_path.iterdir()} == {"published", "referent"}
    assert referent.read_bytes() == b"referent"

    src.write_bytes(b"retried")
    raised = []

    def fail_replace(source, target):
        exc = OSError(errno.EACCES, "replace failed", str(source), None, str(target))
        raised.append(exc)
        raise exc

    with monkeypatch.context() as faults:
        faults.setattr(os, "replace", fail_replace)
        with pytest.raises(PermissionError) as raw:
            fsops.replace_staged(src, dst)
        assert raw.value is raised[0]
        assert (raw.value.errno, raw.value.filename, raw.value.filename2) == (
            errno.EACCES, str(src), str(dst))
        assert src.read_bytes() == b"retried" and dst.readlink() == Path(referent.name)
    fsops.replace_staged(src, dst)
    assert dst.read_bytes() == b"retried" and not dst.is_symlink()
    assert referent.read_bytes() == b"referent"

    with monkeypatch.context() as faults:
        faults.setattr(os, "replace", fail_replace)
        with pytest.raises(PermissionError) as atomic:
            fsops.atomic_write(dst, b"atomic")
        assert atomic.value is raised[1]
        assert (atomic.value.errno, atomic.value.filename, atomic.value.filename2) == (
            errno.EACCES, str(dst), str(dst))
        assert {p.name for p in tmp_path.iterdir()} == {"published", "referent"}
        assert dst.read_bytes() == b"retried"
    fsops.atomic_write(dst, b"atomic")
    assert dst.read_bytes() == b"atomic"


@linux
def test_fsync_order_and_post_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "published"
    real_sync = os.fsync
    calls = []

    def observe(fd):
        st = os.fstat(fd)
        calls.append((stat.S_IFMT(st.st_mode), st.st_ino))
        real_sync(fd)

    monkeypatch.setattr(os, "fsync", observe)
    fsops.atomic_write(path, b"enabled")
    pair = [(stat.S_IFREG, path.stat().st_ino), (stat.S_IFDIR, tmp_path.stat().st_ino)]
    assert path.read_bytes() == b"enabled" and calls == pair

    calls.clear()
    with path.open("rb") as reader:
        fsops.flush_file(reader.fileno())
        assert reader.read() == b"enabled"
    fsops.sync_parent(path)
    fsops.sync_file_and_parent(path)
    assert calls == pair + pair

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "parent sync failed")
        observe(fd)

    with monkeypatch.context() as faults:
        faults.setattr(os, "fsync", fail_directory)
        with pytest.raises(OSError, match="parent sync failed"):
            fsops.atomic_write(path, b"already renamed")
        assert path.read_bytes() == b"already renamed"

    calls.clear()
    fsops.atomic_write(path, b"unsynced", fsync=False)
    assert path.read_bytes() == b"unsynced" and calls == []
    fsops.atomic_write(path, b"synced again", mode=0o600)
    assert path.read_bytes() == b"synced again"
    assert calls == [(stat.S_IFREG, path.stat().st_ino), pair[1]]


@linux
def test_private_temp_and_reopenable_text(tmp_path):
    parent = tmp_path / "private"
    prev = os.umask(0o022)
    try:
        fsops.ensure_private_parent(parent)
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700
        parent.chmod(0o750)
        fsops.ensure_private_parent(parent)
        assert stat.S_IMODE(parent.stat().st_mode) == 0o750
        path = parent / "reply"
        fd = fsops.open_private_new(path)
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"first\n")
        assert path.read_bytes() == b"first\n" and stat.S_IMODE(path.stat().st_mode) == 0o600
        with pytest.raises(FileExistsError):
            fsops.open_private_new(path)
        assert path.read_bytes() == b"first\n"

        fd, name = fsops.private_temp(parent, prefix="probe-", suffix=".txt")
        with os.fdopen(fd, "wb") as private:
            private.write(b"new\n")
        assert isinstance(name, str)
        temp = Path(name)
        assert temp.parent == parent and temp.name.startswith("probe-") and temp.suffix == ".txt"
        assert stat.S_IMODE(temp.stat().st_mode) == 0o600 and temp.read_bytes() == b"new\n"
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF

        # Exclusive creation still honors a mask that removes owner bits.
        os.umask(0o277)
        masked = parent / "masked"
        with os.fdopen(fsops.open_private_new(masked), "wb") as stream:
            stream.write(b"owned")
        assert stat.S_IMODE(masked.stat().st_mode) == 0o400 and masked.read_bytes() == b"owned"
    finally:
        os.umask(prev)

    with fsops.reopenable_text("ignore-é\n", prefix="exclude-", suffix=".txt") as probe:
        assert probe.read_bytes() == "ignore-é\n".encode()
    assert not probe.exists()
    with fsops.open_for_mode(path, "a", mode=0o600, encoding="utf-8") as stream:
        stream.write("second\n")
    assert stream.closed and path.read_bytes() == b"first\nsecond\n"
    other = parent / "exclusive"
    with fsops.open_for_mode(other, "xb", mode=0o751) as binary:
        binary.write(b"exclusive")
    fsops.finish_mode(other, 0o751)
    with pytest.raises(FileExistsError):
        fsops.open_for_mode(other, "x", encoding="utf-8")
    assert other.read_bytes() == b"exclusive" and stat.S_IMODE(other.stat().st_mode) == 0o751


@linux
def test_read_policy_and_directory_scope(tmp_path, monkeypatch):
    from self_learn import cache_gc

    file = tmp_path / "file"
    file.write_bytes(b"ordinary")
    link = tmp_path / "link"
    link.symlink_to(file)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    # Keep a writer available so a regressed blocking read-open cannot hang the suite.
    with os.fdopen(os.open(fifo, os.O_RDWR | os.O_NONBLOCK), "rb"):
        for policy in ("premise", "provenance"):
            with os.fdopen(fsops.open_regular(str(file), policy=policy), "rb") as reader:
                assert reader.read() == b"ordinary"
            with os.fdopen(fsops.open_regular(fifo, policy=policy), "rb") as pipe:
                assert stat.S_ISFIFO(os.fstat(pipe.fileno()).st_mode)
                assert not os.get_blocking(pipe.fileno())
    with pytest.raises(OSError) as refused:
        fsops.open_regular(str(link), policy="premise")
    assert refused.value.errno == errno.ELOOP
    with os.fdopen(fsops.open_regular(link, policy="provenance"), "rb") as reader:
        assert reader.read() == b"ordinary"

    root = tmp_path / cache_gc.GLOB_WITNESS_DIR
    held, outside = tmp_path / "held", tmp_path / "outside"
    name = "a" * 64 + ".json"
    for folder, content in [(root, b"stale"), (outside, b"keep")]:
        folder.mkdir()
        (folder / name).write_bytes(content)
        os.utime(folder / name, (0, 0))
    real_acquire = fsops.safe_directory

    def swap_after_open(path):
        scope = real_acquire(path)
        path.rename(held)
        path.symlink_to(outside, target_is_directory=True)
        return scope

    def prune():
        result = cache_gc.PruneResult()
        cache_gc._prune_glob_witnesses(tmp_path, cache_gc.GLOB_WITNESS_MAX_AGE_SECS + 1, False, result)
        return result.removed_glob_witnesses

    with monkeypatch.context() as swap:
        swap.setattr(fsops, "safe_directory", swap_after_open)
        assert prune() == [name]
    assert not (held / name).exists() and (outside / name).read_bytes() == b"keep"
    assert prune() == []  # O_NOFOLLOW rejects the swapped directory during acquisition.
    assert (outside / name).read_bytes() == b"keep"
    root.unlink()
    held.rename(root)
    (root / name).write_bytes(b"stale again")
    os.utime(root / name, (0, 0))

    def fail_scan(fd):
        assert os.fstat(fd).st_ino == root.stat().st_ino
        raise OSError(errno.EIO, "scandir failed")

    with monkeypatch.context() as faults:
        faults.setattr(os, "scandir", fail_scan)
        with pytest.raises(OSError, match="scandir failed"):
            prune()
    assert (root / name).read_bytes() == b"stale again"
    real_close = os.close

    def fail_close(fd):
        assert os.fstat(fd).st_ino == root.stat().st_ino
        real_close(fd)
        raise OSError(errno.EIO, "close failed")

    with monkeypatch.context() as faults:
        faults.setattr(os, "close", fail_close)
        with pytest.raises(OSError, match="close failed"):
            prune()
    assert not (root / name).exists()
    (root / name).write_bytes(b"final")
    os.utime(root / name, (0, 0))
    assert prune() == [name]
    assert not (root / name).exists() and (outside / name).read_bytes() == b"keep"


@linux
def test_worker_install_visibility_and_crash(tmp_path, monkeypatch):
    from self_learn import gitops, worker
    from self_learn.ledger_ops import QueueEntry, _dumps_yaml, create_record, read_proposal
    from self_learn.normalize import sha_anchor
    from support import make_behavior, make_home
    from test_lock_invariant import _Analysis
    from test_worker import PROPOSAL_YAML_TEMPLATE

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    record = make_behavior(record_id="lrn-0000aaaa")
    pending = create_record(home, record)
    entry = QueueEntry(path=pending, record=record)
    dest = entry.proposal_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = b"record_sha: stale\n"
    dest.write_bytes(old)
    staged = worker.stage_dir() / dest.name
    staged.parent.mkdir(parents=True, exist_ok=True)
    roster = worker.skill_roster(home)
    payload = PROPOSAL_YAML_TEMPLATE.format(roster_sha=roster.sha)
    staged.write_text(payload, encoding="utf-8")
    expected = read_proposal(staged)
    expected["record_sha"] = sha_anchor(record.body)
    landed = _dumps_yaml(expected).encode()
    temp = dest.parent / f".install-{record.id}.tmp"
    journal = worker.cache_dir() / "worker.install-journal"
    snapshot = {dest: sha_anchor(old.decode())}
    real_replace = os.replace

    def fail_install(src, dst):
        if src == temp and dst == dest:
            assert json.loads(journal.read_bytes()) == {"dest": str(dest), "digest": sha_anchor(payload)}
            raise OSError(errno.EIO, "install interrupted")
        return real_replace(src, dst)

    with monkeypatch.context() as faults:
        faults.setattr(os, "replace", fail_install)
        with gitops.commit_lock(home):
            result = worker._validate_written(home, [staged], [entry], roster, snap0=snapshot)
        assert result.proposed == []
        assert temp.read_bytes() == payload.encode() and dest.read_bytes() == old
        assert json.loads(journal.read_bytes()) == {"dest": str(dest), "digest": sha_anchor(payload)}

    staged.write_text(payload, encoding="utf-8")
    with gitops.commit_lock(home):
        recovered = worker._validate_written(home, [staged], [entry], roster, snap0=snapshot)
    assert recovered.proposed == [record.id] and dest.read_bytes() == landed
    assert journal.read_bytes() == b"" and not temp.exists()

    source = tmp_path / "walker"
    source.mkdir()
    module = source / "planted.py"
    control = "def control(home):\n    home.write_text('unrelated')\n"
    for leaf, args in [("replace_staged", "home, home"), ("open_for_mode", "home, 'x'"),
                       ("finish_mode", "home, 0o600")]:
        call = f"fsops.{leaf}({args})"
        module.write_text(f"def root(home):\n    {call}\n" + control)
        assert _Analysis(source).requires_lock() == {
            "planted.root": (2, f"fsops.{leaf}"), "planted.control": (4, "Path.write_text")}
        module.write_text(f"def root(home):\n    with gitops.commit_lock(home):\n        {call}\n" + control)
        assert _Analysis(source).requires_lock() == {"planted.control": (5, "Path.write_text")}


@linux
def test_windows_import_and_first_operation(tmp_path):
    sibling = tmp_path / "sibling"
    sibling.write_bytes(b"original")
    names = ("atomic_write", "private_write", "replace_staged", "flush_file", "sync_parent",
             "sync_file_and_parent", "ensure_private_parent", "open_private_new", "private_temp",
             "reopenable_text", "open_for_mode", "finish_mode", "open_regular", "safe_directory")
    script = """
        import os, secrets, sys
        from pathlib import Path
        from unittest.mock import patch

        root = Path(sys.argv[1])
        names = tuple(sys.argv[2:])
        # Native NT needs no substitution. On Linux select NT during the fresh
        # import and each invocation, leaving pathlib's own platform untouched.
        from types import SimpleNamespace
        assert "self_learn.primitives.fsops" not in sys.modules
        with patch.object(os, "name", "nt"):
            from self_learn.primitives import fsops
        if os.name != "nt":
            fsops.os = SimpleNamespace(name="nt")
        assert all(callable(getattr(fsops, name)) for name in names)
        assert "self_learn.primitives._fsops_posix" not in sys.modules
        print("imported", *names, flush=True)

        sibling, new = root / "sibling", root / "new"
        def snapshot():
            return {p.name: (p.read_bytes(), p.stat().st_mode) for p in root.iterdir()}
        before = snapshot()
        assert before["sibling"][0] == b"original"
        control = root / "control"
        events = []
        def observe(event, args):
            if event in ("open", "os.chmod", "os.mkdir", "os.remove", "os.rename", "os.scandir"):
                events.append(event)
        sys.addaudithook(observe)
        control.write_bytes(b"witness")
        assert "open" in events
        baseline = snapshot()
        assert baseline == {**before, "control": (b"witness", control.stat().st_mode)}

        def enter(scope):
            with scope:
                pass
        with control.open("r+b") as stream:
            operations = [
                lambda: fsops.atomic_write(sibling, b"changed", follow_symlinks=True),
                lambda: fsops.private_write(sibling, b"changed"),
                lambda: fsops.replace_staged(sibling, new),
                lambda: fsops.flush_file(stream.fileno()),
                lambda: fsops.sync_parent(sibling),
                lambda: fsops.sync_file_and_parent(sibling),
                lambda: fsops.ensure_private_parent(new),
                lambda: fsops.open_private_new(new),
                lambda: fsops.private_temp(root, prefix="temp-", suffix=".txt"),
                lambda: enter(fsops.reopenable_text("probe", prefix="temp-", suffix=".txt")),
                lambda: fsops.open_for_mode(new, "x"),
                lambda: fsops.finish_mode(sibling, 0o600),
                lambda: fsops.open_regular(sibling, policy="premise"),
                lambda: enter(fsops.safe_directory(root)),
            ]
            for name, operation in zip(names, operations, strict=True):
                events.clear()
                with (
                    patch.object(Path, "resolve", side_effect=AssertionError("resolved target")),
                    patch.object(Path, "is_symlink", side_effect=AssertionError("inspected target")),
                    patch.object(os, "fsync", side_effect=AssertionError("synced descriptor")),
                ):
                    try:
                        operation()
                    except NotImplementedError:
                        pass
                    else:
                        raise AssertionError(f"{name} returned on Windows")
                assert not events, (name, events)
                assert snapshot() == baseline, name
        assert "self_learn.primitives._fsops_posix" not in sys.modules
    """
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(script), str(tmp_path), *names],
                          capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["imported " + " ".join(names)]
    assert sibling.read_bytes() == b"original" and (tmp_path / "control").read_bytes() == b"witness"


windows = pytest.mark.skipif(os.name != "nt", reason="native Windows filesystem contract")


def test_lazy_native_dispatch(tmp_path):
    script = """
        import os, sys
        from pathlib import Path
        from self_learn.primitives import fsops
        prefix = "self_learn.primitives._fsops_"
        assert not any(name.startswith(prefix) for name in sys.modules)
        path = Path(sys.argv[1])
        fsops.atomic_write(path, b"dispatch")
        assert path.read_bytes() == b"dispatch"
        native = "windows" if os.name == "nt" else "posix"
        assert [n for n in sys.modules if n.startswith(prefix)] == [prefix + native]
        if os.name != "nt":
            assert {"win32file", "pywintypes", "win32security"}.isdisjoint(sys.modules)
    """
    subprocess.run([sys.executable, "-c", textwrap.dedent(script), str(tmp_path / "entry")], check=True)


@windows
def test_whole_versions_visible_to_child(tmp_path):
    import time

    path = tmp_path / "published"
    ready, seen_new, seen_old, stop = (tmp_path / n for n in ("ready", "seen-new", "seen-old", "stop"))
    old, new = (c * 131072 + b"\x00\n" for c in (b"a", b"b"))
    path.write_bytes(old)
    script = """
        import sys, time
        from pathlib import Path
        from contextlib import closing
        import win32con, win32file
        path, ready, seen_new, seen_old, stop = map(Path, sys.argv[1:])
        def read_version():
            # Share DELETE so an open reader and the rename can overlap.
            with closing(win32file.CreateFile(str(path), win32con.GENERIC_READ,
                    7, None, win32con.OPEN_EXISTING, 0, None)) as handle:
                return win32file.ReadFile(handle, 262144)[1]
        old, new = (c * 131072 + b"\\x00\\n" for c in (b"a", b"b"))
        assert read_version() == old
        ready.touch()
        while not stop.exists():
            data = read_version()
            assert data in (old, new), (len(data), data[:8])
            if data == new and not seen_new.exists():
                seen_new.touch()
            if data == old and seen_new.exists() and not seen_old.exists():
                seen_old.touch()
            time.sleep(0)
    """
    def wait_for(signal, child):
        end = time.monotonic() + 10
        while not signal.exists():
            assert child.poll() is None and time.monotonic() < end, signal.name
            time.sleep(0.005)

    with subprocess.Popen([sys.executable, "-c", textwrap.dedent(script),
                           path, ready, seen_new, seen_old, stop]) as child:
        try:
            wait_for(ready, child)
            fsops.atomic_write(path, new)
            wait_for(seen_new, child)
            fsops.atomic_write(path, old)
            wait_for(seen_old, child)
            for _ in range(24):
                fsops.atomic_write(path, old)
                fsops.atomic_write(path, new)
        finally:
            stop.touch()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                raise
    assert child.returncode == 0 and path.read_bytes() == new


@windows
@pytest.mark.parametrize("winerror", [32, 5])
def test_transient_replace_retries_only_rename(tmp_path, monkeypatch, winerror):
    from self_learn.primitives import _fsops_windows as native
    path = tmp_path / "published"
    path.write_bytes(b"old")
    real_replace = os.replace
    attempts, delays = [], []
    monkeypatch.setattr(native, "sleep", delays.append)

    def busy_once(src, dst):
        source = Path(src)
        attempts.append((source, source.stat().st_ino))
        assert source.parent == path.parent and source.read_bytes() == b"caf\xe9\n"
        assert Path(dst).read_bytes() == b"old"
        if len(attempts) == 1:
            raise OSError(0, "busy", str(src), winerror, str(dst))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", busy_once)
    fsops.atomic_write(str(path), "café\n", encoding="latin-1")
    first, retry = attempts
    assert first == retry and delays == [pytest.approx(0.010)]
    assert path.read_bytes() == b"caf\xe9\n" and list(tmp_path.iterdir()) == [path]


@windows
def test_persistent_denial_expires_with_last_exception(tmp_path, monkeypatch):
    from self_learn.primitives import _fsops_windows as native
    src, dst = tmp_path / "stage", tmp_path / "published"
    src.write_bytes(b"stage")
    dst.write_bytes(b"old")
    now = 0.0
    attempts = []

    def advance(seconds):
        nonlocal now
        assert 0 < seconds <= 0.011
        now += seconds

    def deny(source, target):
        exc = OSError(0, "busy", str(source), 5, str(target))
        attempts.append((now, exc))
        assert len(attempts) < 30
        raise exc

    monkeypatch.setattr(native, "monotonic", lambda: now)
    monkeypatch.setattr(native, "sleep", advance)
    monkeypatch.setattr(os, "replace", deny)
    with pytest.raises(PermissionError) as caught:
        fsops.replace_staged(src, dst, method="path")
    assert 0.240 <= now <= 0.250001 and 20 <= len(attempts) <= 26
    assert caught.value is attempts[-1][1]
    assert (caught.value.winerror, caught.value.errno, caught.value.strerror,
            caught.value.filename, caught.value.filename2) == (5, errno.EACCES, "busy", str(src), str(dst))
    assert src.read_bytes() == b"stage" and dst.read_bytes() == b"old"


@windows
def test_permanent_replace_errors_and_atomic_cleanup(tmp_path, monkeypatch):
    from self_learn.primitives import _fsops_windows as native
    src, dst = tmp_path / "stage", tmp_path / "published"
    src.write_bytes(b"stage")
    dst.write_bytes(b"old")

    def no_retry(seconds):
        pytest.fail(f"retried permanent error after {seconds}s")

    monkeypatch.setattr(native, "sleep", no_retry)
    def fields(exc):
        return type(exc), exc.errno, exc.winerror, exc.strerror, exc.filename, exc.filename2

    dst.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PermissionError) as reference:
            os.replace(src, dst)
        with pytest.raises(PermissionError) as staged:
            fsops.replace_staged(src, dst)
        assert fields(staged.value) == fields(reference.value)
        with pytest.raises(PermissionError) as published:
            fsops.atomic_write(dst, b"new")
        assert fields(published.value) == (*fields(reference.value)[:4], str(dst), str(dst))
    finally:
        dst.chmod(stat.S_IWRITE)
    for source, target in [(tmp_path / "absent", dst), (src, tmp_path / "absent" / "dst")]:
        with pytest.raises(FileNotFoundError) as original:
            os.replace(source, target)
        with pytest.raises(FileNotFoundError) as missing:
            fsops.replace_staged(source, target)
        assert fields(missing.value) == fields(original.value)
    # CI's checkout and system temp are on separate local volumes. The injected
    # NOT_SAME_DEVICE check below also runs on single-volume developer machines.
    if Path.cwd().drive.casefold() != tmp_path.drive.casefold():
        import tempfile
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            other = Path(folder) / "target"
            assert src.lstat().st_dev != other.parent.stat().st_dev
            with pytest.raises(OSError) as original:
                os.replace(src, other)
            with pytest.raises(OSError) as different_volumes:
                fsops.replace_staged(src, other)
            assert original.value.winerror == 17 and fields(different_volumes.value) == fields(original.value)

            # A scanner may return DENIED before the move checks volume identity.
            denied = OSError(0, "busy", str(src), 5, str(other))
            def busy(source, target):
                raise denied
            with monkeypatch.context() as faults:
                faults.setattr(os, "replace", busy)
                with pytest.raises(PermissionError) as caught:
                    fsops.replace_staged(src, other)
                assert caught.value is denied
            assert src.read_bytes() == b"stage" and not other.exists()

    cross_device = OSError(0, "different volumes", str(src), 17, str(dst))
    def fail_move(source, target):
        raise cross_device
    monkeypatch.setattr(os, "replace", fail_move)
    with pytest.raises(OSError) as cross:
        fsops.replace_staged(src, dst)
    assert cross.value is cross_device
    assert set(tmp_path.iterdir()) == {src, dst} and (src.read_bytes(), dst.read_bytes()) == (b"stage", b"old")


@windows
def test_flush_before_replace_and_no_directory_sync(tmp_path, monkeypatch):
    path = tmp_path / "file"
    real_sync, real_replace = os.fsync, os.replace
    events = []
    def observe_sync(fd):
        events.append(("sync", os.fstat(fd).st_size))
        real_sync(fd)

    def observe_replace(src, dst):
        assert Path(src).parent == path.parent
        events.append(("replace", Path(src).read_bytes()))
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", observe_sync)
    monkeypatch.setattr(os, "replace", observe_replace)
    fsops.atomic_write(path, b"enabled\n")
    fsops.atomic_write(path, b"off\n", fsync=False)
    fsops.sync_parent(path)
    assert events == [("sync", 8), ("replace", b"enabled\n"), ("replace", b"off\n")]
    assert path.read_bytes() == b"off\n"


@windows
def test_existing_file_flush_preserves_bytes(tmp_path, monkeypatch):
    import win32con
    import win32file
    path = tmp_path / "existing"
    path.write_bytes(b"retained\n")
    calls = []
    real_create, real_flush = win32file.CreateFile, win32file.FlushFileBuffers
    def create(name, access, share, security, disposition, flags, template):
        calls.append((access, share, disposition))
        return real_create(name, access, share, security, disposition, flags, template)

    def flush(handle):
        calls.append("flush")
        return real_flush(handle)

    monkeypatch.setattr(win32file, "CreateFile", create)
    monkeypatch.setattr(win32file, "FlushFileBuffers", flush)
    fsops.sync_file_and_parent(path)
    assert calls == [(win32con.GENERIC_WRITE, 7, win32con.OPEN_EXISTING), "flush"]
    with path.open("r+b") as writable:
        fsops.flush_file(writable.fileno())
    with path.open("rb") as readonly:
        with pytest.raises(OSError):
            fsops.flush_file(readonly.fileno())
    path.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PermissionError):
            fsops.sync_file_and_parent(path)
    finally:
        path.chmod(stat.S_IWRITE)
    assert path.read_bytes() == b"retained\n"


@pytest.fixture
def private_root(tmp_path):
    return tmp_path / "injected-cache" / "private"


@windows
def test_private_parent_and_first_child_inheritance(private_root):
    from contextlib import closing
    import ntsecuritycon
    import win32api
    import win32con
    import win32security as security

    def inspect(path):
        sd = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
                                           security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        dacl = sd.GetSecurityDescriptorDacl()
        aces = [dacl.GetAce(i) for i in range(dacl.GetAceCount())]
        return sd, dacl, aces

    with closing(security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)) as token:
        user = security.GetTokenInformation(token, security.TokenUser)[0]
        default_owner = security.GetTokenInformation(token, security.TokenOwner)
    expected = {str(user), str(security.CreateWellKnownSid(security.WinLocalSystemSid)),
                str(security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid))}
    inherit = security.CONTAINER_INHERIT_ACE | security.OBJECT_INHERIT_ACE
    fsops.ensure_private_parent(private_root)
    sd, _, aces = inspect(private_root)
    assert sd.GetSecurityDescriptorOwner() == user
    assert sd.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED
    assert len(aces) == len(expected) and {str(ace[2]) for ace in aces} == expected
    assert all((header, mask) == ((security.ACCESS_ALLOWED_ACE_TYPE, inherit), ntsecuritycon.FILE_ALL_ACCESS)
               for header, mask, _ in aces)
    fsops.ensure_private_parent(private_root)  # already provisioned
    first = private_root / "first"
    with os.fdopen(fsops.open_private_new(first), "wb") as stream:
        child, dacl, aces = inspect(first)
        assert os.fstat(stream.fileno()).st_size == 0
        assert child.GetSecurityDescriptorOwner() in (user, default_owner)
        assert not child.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED
        assert len(aces) == len(expected) and {str(ace[2]) for ace in aces} == expected
        assert all((header, mask) == ((security.ACCESS_ALLOWED_ACE_TYPE, security.INHERITED_ACE),
                                      ntsecuritycon.FILE_ALL_ACCESS) for header, mask, _ in aces)
        # Effective access for an unrelated local group against both ACLs.
        guests = security.CreateWellKnownSid(security.WinBuiltinGuestsSid)
        trustee = dict(TrusteeForm=security.TRUSTEE_IS_SID,
                       TrusteeType=security.TRUSTEE_IS_WELL_KNOWN_GROUP, Identifier=guests)
        control = security.ACL()
        control.AddAccessAllowedAce(security.ACL_REVISION, ntsecuritycon.FILE_GENERIC_READ, guests)
        assert control.GetEffectiveRightsFromAcl(trustee) & ntsecuritycon.FILE_READ_DATA
        assert dacl.GetEffectiveRightsFromAcl(trustee) == 0
        stream.write(b"owned\n")
    with pytest.raises(FileExistsError):
        fsops.open_private_new(first)
    fd, name = fsops.private_temp(private_root, prefix="temp-", suffix=".bin")
    with os.fdopen(fd, "wb") as stream:
        assert Path(name).parent == private_root and Path(name).stat().st_size == 0
        assert {str(ace[2]) for ace in inspect(name)[2]} == expected
        stream.write(b"temp\n")
    assert Path(name).read_bytes() == b"temp\n" and first.read_bytes() == b"owned\n"
    fsops.private_write(first, "réécrit\n")
    assert first.read_bytes() == "réécrit\n".encode()
    assert {str(ace[2]) for ace in inspect(first)[2]} == expected


@windows
def test_unsafe_existing_private_directory_refused(private_root):
    import ntsecuritycon
    import win32security as security

    private_root.mkdir(parents=True)
    with pytest.raises(OSError):
        fsops.ensure_private_parent(private_root)
    private_root.rmdir()
    fsops.ensure_private_parent(private_root)
    info = security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION
    acl = security.GetNamedSecurityInfo(str(private_root), security.SE_FILE_OBJECT,
                                         security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
    acl.AddAccessAllowedAce(security.ACL_REVISION, ntsecuritycon.FILE_GENERIC_READ,
                            security.CreateWellKnownSid(security.WinBuiltinGuestsSid))
    security.SetNamedSecurityInfo(str(private_root), security.SE_FILE_OBJECT, info, None, None, acl, None)
    for create in (lambda: fsops.ensure_private_parent(private_root),
                   lambda: fsops.open_private_new(private_root / "child"),
                   lambda: fsops.private_temp(private_root, prefix="p", suffix=".tmp")):
        with pytest.raises(PermissionError):
            create()
    assert list(private_root.iterdir()) == []
    # Product paths outside an explicitly verified directory still publish in place.
    legacy = private_root.parent / "legacy"
    legacy.write_bytes(b"previous")
    fsops.private_write(legacy, "updated\n")
    assert legacy.read_bytes() == b"updated\n"


@windows
def test_static_junction_escape_refused(tmp_path):
    import _winapi
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    sentinel = outside / "entry"
    sentinel.write_bytes(b"outside")
    junction = root / "redirect"
    _winapi.CreateJunction(str(outside), str(junction))
    assert junction.is_junction() and junction.samefile(outside)
    for attempt in (lambda: fsops.atomic_write(junction / "entry", b"redirect"),
                    lambda: fsops.private_write(junction / "entry", b"redirect"),
                    lambda: fsops.atomic_write(junction, b"redirect"),
                    lambda: fsops.ensure_private_parent(junction / "child"),
                    lambda: fsops.safe_directory(junction)):
        with pytest.raises(fsops.SymlinkRefused) as rejected:
            attempt()
        assert rejected.value.path == junction
    fsops.atomic_write(root / "entry", b"inside", follow_symlinks=True)
    assert (root / "entry").read_bytes() == b"inside"
    assert sentinel.read_bytes() == b"outside" and list(outside.iterdir()) == [sentinel]


@windows
def test_raw_link_entries_and_opt_in_follow(tmp_path):
    real, link, dst = (tmp_path / n for n in ("file", "link", "dst"))
    real.write_bytes(b"old")
    link.symlink_to(real.name)
    with pytest.raises(fsops.SymlinkRefused):
        fsops.atomic_write(link, b"refused")
    assert real.read_bytes() == b"old" and link.readlink() == Path(real.name)
    fsops.atomic_write(link, b"new", follow_symlinks=True)
    assert real.read_bytes() == b"new" and link.readlink() == Path(real.name)
    dst.symlink_to("absent")
    fsops.replace_staged(link, dst, method="path")
    assert dst.readlink() == Path(real.name) and not link.is_symlink()
    link.write_bytes(b"ordinary")
    fsops.replace_staged(link, dst)
    assert not dst.is_symlink() and dst.read_bytes() == b"ordinary" and real.read_bytes() == b"new"
    assert not (tmp_path / "absent").exists()


@windows
def test_reopenable_text_lf_and_cleanup(tmp_path):
    text = "ignore-é\\ \nnext\n"
    script = """
        import sys
        from pathlib import Path
        p = Path(sys.argv[1])
        with p.open("r+b") as peer:
            assert peer.read() == bytes.fromhex(sys.argv[2])
        moved = p.with_suffix(".moved")
        p.rename(moved)
        moved.rename(p)
    """
    with pytest.raises(RuntimeError, match="caller"):
        with fsops.reopenable_text(text, prefix="exclude-", suffix=".txt") as path:
            subprocess.run([sys.executable, "-c", textwrap.dedent(script), str(path), text.encode().hex()],
                           check=True, timeout=15)
            raise RuntimeError("caller")
    assert not path.exists()
    with fsops.reopenable_text("ours", prefix="exclude-", suffix=".txt") as path:
        sibling = path.with_suffix(".owned")
        path.rename(sibling)
        path.write_bytes(b"replacement")
    try:
        assert path.read_bytes() == b"replacement" and sibling.read_bytes() == b"ours"
    finally:
        path.unlink(missing_ok=True)
        sibling.unlink(missing_ok=True)


@windows
def test_mode_opens_and_readonly_mapping(tmp_path):
    path = tmp_path / "entry"
    with fsops.open_for_mode(path, "x", encoding="utf-8", mode=0o600) as stream:
        stream.write("é\n")
    with pytest.raises(FileExistsError):
        fsops.open_for_mode(path, "xb")
    with fsops.open_for_mode(path, "a", encoding="utf-8") as stream:
        stream.write("appended\n")
    assert path.read_bytes() == "é\nappended\n".encode()
    other = tmp_path / "binary"
    with fsops.open_for_mode(other, "xb") as stream:
        stream.write(b"\xff\n")
    assert other.read_bytes() == b"\xff\n"
    try:
        fsops.finish_mode(path, 0o455)
        assert path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
        with pytest.raises(PermissionError):
            fsops.open_for_mode(path, "a")
        fsops.finish_mode(path, 0o200, method="os")
        assert not path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
    finally:
        path.chmod(stat.S_IWRITE)


@windows
def test_regular_read_descriptor_and_link_policy(tmp_path):
    regular, link = tmp_path / "regular", tmp_path / "link"
    payload = b"\xff\r\n\x1a\n"
    regular.write_bytes(payload)
    link.symlink_to(regular)
    for path, policy in [(regular, "premise"), (regular, "provenance"), (link, "provenance")]:
        fd = fsops.open_regular(str(path), policy=policy)
        try:
            assert os.read(fd, 100) == payload
        finally:
            os.close(fd)
    with pytest.raises(OSError) as refusal:
        fsops.open_regular(link, policy="premise")
    assert refusal.value.errno == errno.ELOOP


@windows
def test_safe_directory_lists_and_unlinks_by_name(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    victim, sibling = root / "entry", tmp_path / "keep"
    victim.write_bytes(b"stale")
    sibling.write_bytes(b"keep")
    with fsops.safe_directory(root) as directory:
        with directory.entries() as entries:
            assert [e.name for e in entries] == [victim.name]
        for invalid in ("../keep", str(sibling), ".."):
            with pytest.raises(ValueError):
                directory.unlink(invalid)
        directory.unlink(victim.name)
    assert list(root.iterdir()) == [] and sibling.read_bytes() == b"keep"


@windows
def test_ordinary_publish_inherits_folder_permissions(tmp_path):
    import ntsecuritycon
    import win32security as security

    target, peer = tmp_path / "published", tmp_path / "peer"
    target.write_bytes(b"old")
    peer.write_bytes(b"peer")

    def descriptor(path):
        return security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
                                             security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)

    def entries(sd):
        acl = sd.GetSecurityDescriptorDacl()
        return [(header, mask, str(sid)) for header, mask, sid in
                (acl.GetAce(i) for i in range(acl.GetAceCount()))]

    original = descriptor(target)
    acl = security.ACL()
    acl.AddAccessAllowedAce(security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS,
                            original.GetSecurityDescriptorOwner())
    security.SetNamedSecurityInfo(str(target), security.SE_FILE_OBJECT, security.DACL_SECURITY_INFORMATION |
                                  security.PROTECTED_DACL_SECURITY_INFORMATION, None, None, acl, None)
    expected = entries(descriptor(peer))
    assert expected and entries(descriptor(target)) != expected
    fsops.atomic_write(target, b"ordinary")
    published = descriptor(target)
    assert entries(published) == expected
    assert not published.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED
    assert target.read_bytes() == b"ordinary" and peer.read_bytes() == b"peer"


@windows
def test_cloud_tags_take_ordinary_file_paths(tmp_path, monkeypatch):
    import win32api
    import win32file
    from self_learn.primitives import _fsops_windows as native

    assert all(native._link_tag(tag) for tag in (
        stat.IO_REPARSE_TAG_SYMLINK, stat.IO_REPARSE_TAG_MOUNT_POINT, stat.IO_REPARSE_TAG_APPEXECLINK))
    assert not any(native._link_tag(tag) for tag in (0, 0x80000013, 0x9000001A, 0x9000701A, 0x9000F01A))
    folder = tmp_path / "Documents"
    fsops.ensure_private_parent(folder)
    path = folder / "record"
    path.write_bytes(b"old")
    attributes = win32api.GetFileAttributes
    get_info = win32file.GetFileInformationByHandleEx
    reopen = win32file.ReOpenFile
    reads = []

    def cloud_attributes(name):
        bits = attributes(name)
        return bits | stat.FILE_ATTRIBUTE_REPARSE_POINT if Path(name) in (folder, path) else bits

    def cloud_info(handle, kind):
        info = get_info(handle, kind)
        assert kind == win32file.FileAttributeTagInfo
        return {**info, "ReparseTag": 0x9000F01A,
                "FileAttributes": info["FileAttributes"] | stat.FILE_ATTRIBUTE_REPARSE_POINT}

    def open_data(handle, access, share, flags):
        reads.append(flags)
        return reopen(handle, access, share, flags)

    monkeypatch.setattr(win32api, "GetFileAttributes", cloud_attributes)
    monkeypatch.setattr(win32file, "GetFileInformationByHandleEx", cloud_info)
    monkeypatch.setattr(win32file, "ReOpenFile", open_data)
    fsops.ensure_private_parent(folder)
    fsops.atomic_write(path, b"ordinary\n")
    assert path.read_bytes() == b"ordinary\n"
    fsops.private_write(path, b"private\n")
    with os.fdopen(fsops.open_regular(path, policy="premise"), "rb") as reader:
        assert reader.read() == b"private\n"
    import win32con
    directory_fd = fsops.open_regular(folder, policy="premise")
    try:
        assert stat.S_ISDIR(os.fstat(directory_fd).st_mode)
    finally:
        os.close(directory_fd)
    assert reads == [0, win32con.FILE_FLAG_BACKUP_SEMANTICS]
    with fsops.safe_directory(folder) as directory, directory.entries() as entries:
        assert [entry.name for entry in entries] == [path.name]


@windows
@pytest.mark.parametrize("kind", ["directory_symlink", "junction"])
def test_linked_parent_and_uninspected_ancestor(tmp_path, monkeypatch, kind):
    import _winapi
    import pywintypes
    import win32api

    base, linked = tmp_path / "folders", tmp_path / "alias"
    inner = base / "ordinary"
    inner.mkdir(parents=True)
    if kind == "junction":
        _winapi.CreateJunction(str(base), str(linked))
        assert linked.is_junction()
    else:
        linked.symlink_to(base, target_is_directory=True)
        assert linked.is_symlink()
    assert linked.samefile(base)

    with pytest.raises(fsops.SymlinkRefused):
        fsops.atomic_write(linked / "settings", b"refused")
    get_attrs = win32api.GetFileAttributes
    inspected = []

    def guarded(name):
        inspected.append(Path(name))
        if Path(name) in (linked, tmp_path):
            raise pywintypes.error(5, "GetFileAttributes", "no attribute access")
        return get_attrs(name)

    monkeypatch.setattr(win32api, "GetFileAttributes", guarded)
    with pytest.raises(pywintypes.error):
        guarded(str(tmp_path))
    inspected.clear()
    fsops.atomic_write(linked / "settings", b"config", follow_symlinks=True)
    fsops.atomic_write(linked / "ordinary" / "note", b"record")
    assert linked not in inspected and tmp_path not in inspected
    assert (base / "settings").read_bytes() == b"config" and (inner / "note").read_bytes() == b"record"


@windows
def test_exclusive_creates_refuse_occupied_link_names(private_root, monkeypatch):
    import win32con
    import win32file

    fsops.ensure_private_parent(private_root)
    existing = private_root / "existing"
    existing.write_bytes(b"original")
    real_create = win32file.CreateFile
    requests = []

    def create(name, access, share, security, disposition, flags, template):
        if disposition == win32con.CREATE_NEW:
            assert flags & win32file.FILE_FLAG_OPEN_REPARSE_POINT
            requests.append(Path(name))
        return real_create(name, access, share, security, disposition, flags, template)

    monkeypatch.setattr(win32file, "CreateFile", create)
    for target in (existing, private_root / "absent"):
        link = private_root / (target.name + "-link")
        link.symlink_to(target.name)
        for kind in ("private", "x", "xb"):
            with pytest.raises(FileExistsError) as collision:
                if kind == "private":
                    os.close(fsops.open_private_new(link))
                else:
                    fsops.open_for_mode(link, kind).close()
            assert collision.value.winerror in (80, 183)
            assert requests.pop() == link
        assert link.readlink() == Path(target.name)
    assert existing.read_bytes() == b"original" and not (private_root / "absent").exists()


@windows
def test_default_text_encoding_and_string_mode_paths(tmp_path):
    text = "水é\n"
    path = str(tmp_path / "text")
    with fsops.open_for_mode(path, "x") as stream:
        stream.write(text)
    with fsops.open_for_mode(path, "a") as stream:
        stream.write(text)
    assert Path(path).read_bytes() == (text * 2).encode("utf-8")
    with fsops.open_for_mode(path, "a", encoding="latin-1") as stream:
        stream.write("é\n")
    assert Path(path).read_bytes().endswith(b"\xc3\xa9\n\xe9\n")
    try:
        fsops.finish_mode(path, 0o444, method="os")
        assert Path(path).stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
    finally:
        os.chmod(path, stat.S_IWRITE)


@windows
def test_directory_error_types_and_reader_classification(tmp_path):
    missing, regular = tmp_path / "missing", tmp_path / "regular"
    regular.touch()
    with pytest.raises(FileNotFoundError):
        fsops.safe_directory(missing)
    with pytest.raises(NotADirectoryError):
        fsops.safe_directory(regular)
    with pytest.raises(FileExistsError):
        fsops.ensure_private_parent(regular)
    for policy in ("provenance", "premise"):
        with pytest.raises(FileNotFoundError):
            fsops.open_regular(missing, policy=policy)
        fd = fsops.open_regular(tmp_path, policy=policy)
        try:
            assert stat.S_ISDIR(os.fstat(fd).st_mode)
        finally:
            os.close(fd)


@windows
def test_private_creates_require_existing_parent(private_root):
    for create in (lambda: fsops.open_private_new(private_root / "new"),
                   lambda: fsops.private_temp(private_root, prefix="p", suffix=".tmp")):
        with pytest.raises(FileNotFoundError):
            create()
        assert not private_root.parent.exists()


@windows
def test_verify_inherited_private_subdirectory(private_root, monkeypatch):
    import ntsecuritycon
    import win32security as security

    fsops.ensure_private_parent(private_root)
    child = private_root / "runs" / "session"
    child.mkdir(parents=True)
    fsops.ensure_private_parent(child)
    with os.fdopen(fsops.open_private_new(child / "reply"), "wb") as stream:
        stream.write(b"reply\n")
    monkeypatch.chdir(private_root)
    fd, name = fsops.private_temp(child.relative_to(private_root), prefix="p", suffix=".tmp")
    with os.fdopen(fd, "w+b") as stream:
        assert not os.get_inheritable(fd)
        stream.write(b"temporary")
        stream.seek(0)
        assert stream.read() == b"temporary"
    assert Path(name).parent == child and (child / "reply").read_bytes() == b"reply\n"

    # A non-inheriting entry at the origin leaves the child's three entries intact.
    # Verification must still detect the change to the origin.
    def acl(path):
        sd = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, security.DACL_SECURITY_INFORMATION)
        return sd.GetSecurityDescriptorDacl()
    dacl = acl(private_root)
    dacl.AddAccessAllowedAce(security.ACL_REVISION, ntsecuritycon.FILE_READ_ATTRIBUTES,
                             security.CreateWellKnownSid(security.WinBuiltinGuestsSid))
    security.SetNamedSecurityInfo(str(private_root), security.SE_FILE_OBJECT,
                                  security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
                                  None, None, dacl, None)
    assert acl(child).GetAceCount() == 3
    with pytest.raises(PermissionError):
        fsops.ensure_private_parent(child)


@windows
def test_native_errors_keep_winerror_and_cause(tmp_path, monkeypatch):
    import pywintypes
    import tempfile
    import win32api
    import win32file
    import win32security

    path = tmp_path / "entry"
    fsops.atomic_write(path, b"before")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    def text():
        with fsops.reopenable_text("body", prefix="probe-", suffix=".tmp"):
            pass
    for module, name, operation in (
        (win32api, "GetFileAttributes", lambda: fsops.atomic_write(path, b"changed")),
        (win32security, "OpenProcessToken", lambda: fsops.open_private_new(path)),
        (win32file, "CreateFile", lambda: fsops.open_for_mode(tmp_path / "new", "x")),
        (win32file, "FlushFileBuffers", lambda: fsops.sync_file_and_parent(path)),
        (win32file, "GetFileInformationByHandleEx", lambda: fsops.open_regular(path, policy="premise")),
        (win32file, "GetFileInformationByHandle", text),
        (win32file, "SetFileInformationByHandle", text),
    ):
        failure = pywintypes.error(5, name, "injected denial")
        def deny(*args):
            raise failure
        with monkeypatch.context() as faults:
            faults.setattr(module, name, deny)
            with pytest.raises(PermissionError) as caught:
                operation()
        assert caught.value.winerror == 5 and caught.value.__cause__ is failure
        assert caught.value.filename
        if name == "SetFileInformationByHandle":
            # Deletion itself failed. Its handle must still have closed.
            [left] = tmp_path.glob("probe-*.tmp")
            left.unlink()
        assert list(tmp_path.iterdir()) == [path]
    assert path.read_bytes() == b"before"


@windows
def test_publication_temp_name_and_collision(tmp_path, monkeypatch):
    import re

    target = tmp_path / ("a" * 64 + ".json")
    collision = tmp_path / "occupied"
    collision.write_bytes(b"keep")
    factory = fsops._temp_path
    names = []
    def candidate(dest):
        assert dest == target
        name = factory(dest) if names else collision
        names.append(name)
        return name
    monkeypatch.setattr(fsops, "_temp_path", candidate)
    fsops.atomic_write(target, b"complete")
    assert len(names) == 2
    assert re.fullmatch(r"\.[0-9a-f]{64}\.json\.[0-9]+\.[0-9a-f]{8}\.tmp", names[1].name)
    assert collision.read_bytes() == b"keep" and target.read_bytes() == b"complete"
    assert set(tmp_path.iterdir()) == {collision, target}


@windows
def test_no_sleep_in_final_retry_slice(tmp_path, monkeypatch):
    from self_learn.primitives import _fsops_windows as native

    src, dst = tmp_path / "source", tmp_path / "dest"
    src.touch()
    dst.touch()
    times = iter([0, 0.245])
    monkeypatch.setattr(native, "monotonic", lambda: next(times))
    monkeypatch.setattr(native, "sleep", lambda delay: pytest.fail(f"unused final sleep {delay}"))
    error = OSError(0, "busy", str(src), 32, str(dst))
    def busy(source, target):
        raise error
    monkeypatch.setattr(os, "replace", busy)
    with pytest.raises(PermissionError) as caught:
        fsops.replace_staged(src, dst)
    assert caught.value is error
