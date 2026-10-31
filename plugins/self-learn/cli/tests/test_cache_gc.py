"""S-99: orphaned per-home cache directories and idle host lock
files are removed; nothing that belongs to an existing home or a held lock
ever is.

Every test works under the autouse scratch ``XDG_CACHE_HOME`` /
``SELF_LEARN_HOME`` of ``conftest.py``; none touches the real cache.
"""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

from self_learn import cache_gc, gitops, serve, worker

DAY = 86400.0


def _root() -> Path:
    root = cache_gc.cache_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _age(path: Path, days: float) -> None:
    """Set *path* and everything under it to *days* ago."""
    stamp = time.time() - days * DAY
    for dirpath, dirnames, filenames in os.walk(path):
        for name in (*dirnames, *filenames):
            os.utime(os.path.join(dirpath, name), (stamp, stamp), follow_symlinks=False)
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _cache_for(home: Path, *, age_days: float = 0.0, pointer: bool = True) -> Path:
    """The namespace dir for *home*, with a file inside, as `worker.cache_dir`
    would leave it."""
    d = _root() / f"home-{cache_gc.home_digest(home)}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "miner").mkdir(exist_ok=True)
    (d / "miner" / "journal.jsonl").write_text("{}\n", encoding="utf-8")
    if pointer:
        cache_gc.record_home(d, home)
    if age_days:
        _age(d, age_days)
    return d


def _lock(name: str, *, age_days: float) -> Path:
    p = _root() / name
    p.write_text("123\n", encoding="utf-8")
    _age(p, age_days)
    return p


# ------------------------------------------------------------- the pointer


def test_cache_dir_records_which_home_it_belongs_to(tmp_path):
    home = tmp_path / "some-home"
    d = worker.cache_dir(home)
    assert (d / cache_gc.HOME_POINTER).read_text(encoding="utf-8").strip() == str(home)
    assert cache_gc.read_home_pointer(d) == home


def test_cache_dir_records_the_expanded_home_it_hashed(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = worker.cache_dir(Path("~/x"))
    pointer = cache_gc.read_home_pointer(d)
    assert pointer == tmp_path / "x"
    assert d.name == f"home-{cache_gc.home_digest(pointer)}"


def test_unusable_pointers_read_as_none(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    assert cache_gc.read_home_pointer(d) is None  # missing
    for bad in ("", "relative/path\n", "/a\n/b\n", "/a\0b\n"):
        (d / cache_gc.HOME_POINTER).write_text(bad, encoding="utf-8")
        assert cache_gc.read_home_pointer(d) is None, bad


# ------------------------------------------------------------ home caches


def test_orphan_home_cache_is_removed_once_idle_long_enough(tmp_path):
    gone = tmp_path / "scratch-ledger"  # never created: the home does not exist
    d = _cache_for(gone, age_days=8)
    assert d.is_dir()  # positive control: there was something to remove
    result = cache_gc.prune()
    assert result.removed_homes == [d.name]
    assert not d.exists()


def test_deleted_home_is_an_orphan(tmp_path):
    home = tmp_path / "ledger"
    home.mkdir()
    d = _cache_for(home, age_days=8)
    assert cache_gc.prune().removed_homes == []  # home exists: kept
    assert d.is_dir()
    home.rmdir()
    assert cache_gc.prune().removed_homes == [d.name]
    assert not d.exists()


def test_existing_homes_cache_is_never_removed(tmp_path):
    home = tmp_path / "ledger"
    home.mkdir()
    d = _cache_for(home, age_days=400)
    result = cache_gc.prune()
    assert result.removed_homes == []
    assert d.is_dir() and (d / "miner" / "journal.jsonl").is_file()


def test_a_recent_orphan_is_kept_and_counted(tmp_path):
    d = _cache_for(tmp_path / "gone", age_days=2)
    result = cache_gc.prune()
    assert d.is_dir()
    assert result.removed_homes == [] and result.too_recent == 1


def test_one_recent_file_deep_inside_keeps_the_whole_directory(tmp_path):
    d = _cache_for(tmp_path / "gone", age_days=30)
    fresh = d / "miner" / "journal.jsonl"
    now = time.time()
    os.utime(fresh, (now, now))  # an append deep in the tree, dir mtimes untouched
    assert cache_gc.prune().removed_homes == []
    assert d.is_dir()


def test_dir_without_a_record_is_left_alone_and_counted(tmp_path):
    d = _cache_for(tmp_path / "gone", age_days=400, pointer=False)
    result = cache_gc.prune()
    assert d.is_dir()
    assert result.removed_homes == [] and result.unattributed == 1


def test_record_that_does_not_hash_to_the_dir_name_is_not_trusted(tmp_path):
    d = _cache_for(tmp_path / "gone", age_days=400, pointer=False)
    (d / cache_gc.HOME_POINTER).write_text(str(tmp_path / "other-gone") + "\n", encoding="utf-8")
    _age(d, 400)
    result = cache_gc.prune()
    assert d.is_dir()
    assert result.removed_homes == [] and result.unattributed == 1


def test_the_ambient_home_and_named_keep_homes_survive_even_when_missing(monkeypatch, tmp_path):
    ambient = tmp_path / "ambient-not-created"
    named = tmp_path / "named-not-created"
    monkeypatch.setenv("SELF_LEARN_HOME", str(ambient))
    a = _cache_for(ambient, age_days=400)
    n = _cache_for(named, age_days=400)
    other = _cache_for(tmp_path / "other-not-created", age_days=400)
    result = cache_gc.prune(keep_homes=[named])
    assert result.removed_homes == [other.name]
    assert a.is_dir() and n.is_dir() and not other.exists()


def test_a_symlink_named_like_a_home_dir_is_not_followed(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x", encoding="utf-8")
    gone = tmp_path / "gone"
    link = _root() / f"home-{cache_gc.home_digest(gone)}"
    link.symlink_to(victim, target_is_directory=True)
    cache_gc.record_home(victim, gone)
    _age(victim, 400)
    result = cache_gc.prune()
    assert (victim / "keep.txt").is_file()
    # skipped outright: not "tried to remove it and failed" (rmtree refuses a link)
    assert result.removed_homes == [] and result.errors == []


def test_other_entries_in_the_cache_root_are_never_touched(tmp_path):
    root = _root()
    sentinel = root / "autosync-pause.lock"
    state = root / "landing-u-land.state"
    odd = root / "home-notahash"
    for p in (sentinel, state):
        p.write_text("x", encoding="utf-8")
        _age(p, 400)
    odd.mkdir()
    _age(odd, 400)
    cache_gc.prune()
    assert sentinel.is_file() and state.is_file() and odd.is_dir()


def test_dry_run_reports_without_removing(tmp_path):
    d = _cache_for(tmp_path / "gone", age_days=8)
    lock = _lock("host--home-x-aaaaaaaa.commit.lock", age_days=40)
    result = cache_gc.prune(dry_run=True)
    assert result.removed_homes == [d.name]
    assert result.removed_locks == [lock.name]
    assert d.is_dir() and lock.is_file()


def test_a_missing_cache_root_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "no-such-cache"))
    result = cache_gc.prune()
    assert result.removed_homes == [] and result.removed_locks == [] and result.errors == []
    assert not (tmp_path / "no-such-cache").exists()  # and it created nothing


# ------------------------------------------------------------- lock files


def test_an_old_unheld_host_lock_is_removed(tmp_path):
    lock = _lock("host--home-x-aaaaaaaa.commit.lock", age_days=31)
    assert lock.is_file()
    assert cache_gc.prune().removed_locks == [lock.name]
    assert not lock.exists()


def test_a_recent_host_lock_is_kept(tmp_path):
    lock = _lock("host--home-x-aaaaaaaa.commit.lock", age_days=10)
    result = cache_gc.prune()
    assert lock.is_file() and result.removed_locks == [] and result.too_recent == 1


def test_a_tmp_host_lock_goes_after_a_day(tmp_path):
    tmp_lock = _lock("host--tmp-pytest-of-x-abcd1234.commit.lock", age_days=2)
    real = _lock("host--home-x-aaaaaaaa.commit.lock", age_days=2)
    assert cache_gc.prune().removed_locks == [tmp_lock.name]
    assert real.is_file()


def test_a_held_lock_is_never_removed(tmp_path):
    lock = _lock("host--home-x-aaaaaaaa.commit.lock", age_days=400)
    with open(lock, "r+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = cache_gc.prune()
        assert lock.is_file() and result.removed_locks == []
    # positive control: released, the same file goes
    assert cache_gc.prune().removed_locks == [lock.name]


def test_flock_lock_retries_on_a_fresh_file_when_its_file_was_unlinked(monkeypatch, tmp_path):
    """The race the inode re-check closes: a pruner unlinks the lock file
    between our `open` and our `flock`. Without the re-check the lock is
    taken on an orphaned inode and excludes nobody."""
    path = tmp_path / "locks" / "host-x.commit.lock"
    path.parent.mkdir()
    real_flock = fcntl.flock
    calls: list[int] = []

    def flock_then_lose_the_file(fd, op):
        real_flock(fd, op)
        calls.append(fd)
        if len(calls) == 1:
            path.unlink()  # the pruner, just after we locked the old inode

    monkeypatch.setattr(gitops.fcntl, "flock", flock_then_lose_the_file)
    with gitops._flock_lock(path, 5.0, "host"):
        assert path.is_file()  # we hold the file now at `path`
        monkeypatch.setattr(gitops.fcntl, "flock", real_flock)
        probe = os.open(path, os.O_RDWR)
        try:
            # a second taker is excluded by OUR lock: the proof it is on the real file
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                excluded = False
            except BlockingIOError:
                excluded = True
        finally:
            os.close(probe)
        assert excluded
    assert len(calls) == 2  # locked the lost file, noticed, locked the fresh one


# ------------------------------------------------------------ the daemon


def test_the_daemon_sweep_removes_orphans_and_keeps_its_own_home(tmp_path):
    served = tmp_path / "served-not-created"
    mine = _cache_for(served, age_days=400)
    orphan = _cache_for(tmp_path / "gone", age_days=400)
    serve._sweep_cache(served)
    assert mine.is_dir() and not orphan.exists()


def test_run_forever_sweeps_once_per_interval_not_every_tick(monkeypatch, tmp_path):
    seen: list[list[Path]] = []

    def fake_prune(*, keep_homes=(), **kw):
        seen.append(list(keep_homes))
        return cache_gc.PruneResult()

    monkeypatch.setattr(serve.cache_gc, "prune", fake_prune)
    monkeypatch.setattr(serve, "_run_tick", lambda *a, **k: [])
    home = tmp_path / "home"
    cd = tmp_path / "cd"
    cd.mkdir()
    assert serve.run_forever(home, tick_secs=0.01, cache_dir=cd, max_ticks=4) == 0
    assert seen == [[home]]
