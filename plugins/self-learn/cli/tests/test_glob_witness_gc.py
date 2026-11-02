"""Witness files join the existing prune pass; only their owned names expire."""
import os

import pytest

from self_learn import cache_gc, ledger_ops, serve
from self_learn.primitives import fsops

DAY = 86400


def seed_cache(tmp_path):
    root = cache_gc.cache_root()
    directory = root / cache_gc.GLOB_WITNESS_DIR
    directory.mkdir(parents=True)
    now = 100 * DAY
    files = {}
    for label, name, age in [
        ('old', 'a' * 64 + '.json', 31 * DAY),
        ('recent', 'b' * 64 + '.json', 29 * DAY),
        ('old_temp', fsops._temp_path(directory / ('c' * 64 + '.json')).name, 2 * DAY),
        ('recent_temp', fsops._temp_path(directory / ('d' * 64 + '.json')).name, DAY / 2),
        ('unrelated', 'leave-me.txt', 90 * DAY),
    ]:
        path = directory / name
        path.write_text('fixture')
        os.utime(path, (now - age, now - age))
        files[label] = path
    return root, now, files


@pytest.mark.parametrize('dry_run', [False, True])
def test_prune_witness_age_and_interrupted_temps(tmp_path, dry_run):
    root, now, files = seed_cache(tmp_path)
    assert all(path.is_file() for path in files.values())
    result = cache_gc.prune(root=root, now=now, dry_run=dry_run)
    assert result.errors == []
    assert set(result.removed_glob_witnesses) == {files['old'].name, files['old_temp'].name}
    assert result.too_recent == 2
    assert files['old'].exists() is dry_run
    assert files['old_temp'].exists() is dry_run
    assert all(files[label].is_file() for label in ('recent', 'recent_temp', 'unrelated'))


def test_witness_cleanup_does_not_follow_symlinks(tmp_path):
    root, now, files = seed_cache(tmp_path)
    outside = tmp_path / 'outside'
    outside.write_text('keep')
    link = files['old'].parent / ('e' * 64 + '.json')
    link.symlink_to(outside)
    os.utime(link, (0, 0), follow_symlinks=False)
    result = cache_gc.prune(root=root, now=now)
    assert files['old'].name in result.removed_glob_witnesses
    assert link.is_symlink() and outside.read_text() == 'keep'
    # A symlink replacing the cache directory must not redirect cleanup.
    directory = files['old'].parent
    moved = tmp_path / 'moved-cache'
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    result = cache_gc.prune(root=root, now=now + 90 * DAY)
    assert result.errors == [] and result.removed_glob_witnesses == []
    assert files['recent'].is_file()


def test_daemon_prunes_witnesses_and_next_call_rebuilds(tmp_path, monkeypatch):
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'hit.py').write_text('fixture')
    assert ledger_ops.glob_reaches((tree,), '*.py') == 'match'
    cache = ledger_ops._glob_witness_cache_path((tree,), '*.py')
    assert cache.is_file()
    written = cache.stat().st_mtime
    monkeypatch.setattr(cache_gc.time, 'time', lambda: written + 31 * DAY)
    serve._sweep_cache(tmp_path / 'scratch-home')
    assert not cache.exists()
    ledger_ops._GLOB_WITNESSES.clear()
    assert ledger_ops.glob_reaches((tree,), '*.py') == 'match'
    assert cache.is_file()
