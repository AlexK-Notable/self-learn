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
