"""Positive witnesses are re-proved; negative verdicts never become truth."""
import pytest

from self_learn import ledger_ops as ops


@pytest.fixture(autouse=True)
def fresh_process_memo():
    ops._GLOB_WITNESSES.clear()
    yield
    ops._GLOB_WITNESSES.clear()


def seed(tmp_path):
    root = tmp_path / 'tree'
    hit = root / 'nested' / 'marker' / 'hit.py'
    hit.parent.mkdir(parents=True)
    hit.write_text('fixture')
    return root, hit, '**/marker/*.py'


def count_probe(monkeypatch):
    calls = []
    original = ops._probe_glob_reaches

    def probe(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(ops, '_probe_glob_reaches', probe)
    return calls


@pytest.mark.parametrize('disk', [False, True])
def test_warm_witness_matches_without_walking(tmp_path, monkeypatch, disk):
    root, hit, pattern = seed(tmp_path)
    assert ops.glob_reaches((root,), pattern) == 'match'
    cache = ops._glob_witness_cache_path((root,), pattern)
    assert cache.is_file()
    if disk:
        ops._GLOB_WITNESSES.clear()
    else:
        cache.unlink()  # prove the process memo is independently useful
    calls = count_probe(monkeypatch)

    def no_walk(*args, **kwargs):
        pytest.fail('warm witness walked the tree')

    with monkeypatch.context() as scoped:
        scoped.setattr(ops.os, 'scandir', no_walk)
        assert ops.glob_reaches((root,), pattern) == 'match'
        assert calls == []


@pytest.mark.parametrize('change', ['delete', 'rename', 'symlink', 'ancestor_symlink'])
def test_stale_witness_reprobes(tmp_path, monkeypatch, change):
    root, hit, pattern = seed(tmp_path)
    assert ops.glob_reaches((root,), pattern) == 'match'
    if change == 'delete':
        hit.unlink()
    elif change == 'rename':
        hit.rename(hit.with_suffix('.txt'))
    elif change == 'symlink':
        outside = tmp_path / 'outside.py'
        hit.rename(outside)
        hit.symlink_to(outside)
    else:
        outside = tmp_path / 'outside'
        (root / 'nested').rename(outside)
        (root / 'nested').symlink_to(outside, target_is_directory=True)
    calls = count_probe(monkeypatch)
    # The existing glob tail follows file symlinks; the DFS refuses
    # directory symlinks. Cache rejection must preserve either fallback.
    expected = 'match' if change == 'symlink' else 'none'
    assert ops.glob_reaches((root,), pattern) == expected
    assert len(calls) == 1


@pytest.mark.parametrize('verdict', ['none', 'budget'])
def test_negative_verdicts_always_probe(tmp_path, monkeypatch, verdict):
    root, hit, pattern = seed(tmp_path)
    hit.unlink()
    if verdict == 'budget':
        monkeypatch.setattr(ops, '_glob_probe_budget_s', lambda: 0.0)
    calls = count_probe(monkeypatch)
    assert ops.glob_reaches((root,), pattern) == verdict
    assert len(calls) == 1
    assert ops.glob_reaches((root,), pattern) == verdict
    assert len(calls) == 2
    assert not ops._glob_witness_cache_path((root,), pattern).exists()
    # Newly reachable files must be seen, including after a budget failure.
    monkeypatch.setattr(ops, '_glob_probe_budget_s', lambda: 30.0)
    hit.write_text('new fixture')
    assert ops.glob_reaches((root,), pattern) == 'match'
    assert len(calls) == 3


@pytest.mark.parametrize('content', ['{broken', '[]', '{"base": 4}', '{"base": "x", "path": null}'])
def test_corrupt_cache_is_ignored(tmp_path, monkeypatch, content):
    root, hit, pattern = seed(tmp_path)
    assert ops.glob_reaches((root,), pattern) == 'match'
    cache = ops._glob_witness_cache_path((root,), pattern)
    ops._GLOB_WITNESSES.clear()
    cache.write_text(content)
    calls = count_probe(monkeypatch)
    assert ops.glob_reaches((root,), pattern) == 'match'
    assert len(calls) == 1
    assert cache.read_text() != content


def test_existing_nonmatching_or_outside_witness_is_rejected(tmp_path, monkeypatch):
    import json
    root, hit, pattern = seed(tmp_path)
    assert ops.glob_reaches((root,), pattern) == 'match'
    cache = ops._glob_witness_cache_path((root,), pattern)
    calls = count_probe(monkeypatch)
    for base, path in [(hit.parent, hit.with_suffix('.txt')),
                       (tmp_path / 'outside', tmp_path / 'outside' / 'hit.py')]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
        ops._GLOB_WITNESSES.clear()
        cache.write_text(json.dumps({'base': str(base), 'path': str(path)}))
        assert ops.glob_reaches((root,), pattern) == 'match'
    assert len(calls) == 2


def test_deleted_witness_is_replaced(tmp_path, monkeypatch):
    root, hit, pattern = seed(tmp_path)
    assert ops.glob_reaches((root,), pattern) == 'match'
    hit.unlink()
    replacement = root / 'other' / 'marker' / 'new.py'
    replacement.parent.mkdir(parents=True)
    replacement.write_text('fixture')
    calls = count_probe(monkeypatch)
    assert ops.glob_reaches((root,), pattern) == 'match'
    assert len(calls) == 1
    assert ops.glob_reaches((root,), pattern) == 'match'
    assert len(calls) == 1


def test_explicit_budget_still_probes(tmp_path, monkeypatch):
    root, hit, pattern = seed(tmp_path)
    assert ops.glob_reaches((root,), pattern) == 'match'
    calls = count_probe(monkeypatch)
    assert ops.glob_reaches((root,), pattern, budget_s=0) == 'budget'
    assert len(calls) == 1


def test_unreadable_cache_and_failed_write_are_nonfatal(tmp_path, monkeypatch):
    root, hit, pattern = seed(tmp_path)
    cache = ops._glob_witness_cache_path((root,), pattern)
    cache.mkdir(parents=True)  # reading and atomically replacing a directory fail
    calls = count_probe(monkeypatch)
    assert ops.glob_reaches((root,), pattern) == 'match'
    assert len(calls) == 1


@pytest.mark.parametrize('pattern', [
    '**/marker/*.py', '**/marker/**', '**/*.py', '**/hit.py',
    'nested/marker/*.py', '**/marker/hit.?y', '**/marker/[h]it.py',
    '**/nested/marker/*.py', '**', '', '**/marker/.*',
])
def test_warm_matches_probe_semantics(tmp_path, monkeypatch, pattern):
    root, hit, _ = seed(tmp_path)
    (hit.parent / '.hidden').write_text('fixture')
    assert ops.glob_reaches((root,), pattern, budget_s=30) == 'match'
    assert ops.glob_reaches((root,), pattern) == 'match'
    ops._GLOB_WITNESSES.clear()
    calls = count_probe(monkeypatch)
    assert ops.glob_reaches((root,), pattern) == 'match'
    assert calls == []


def test_corrupt_base_is_not_a_recursive_hit(tmp_path, monkeypatch):
    import json
    root = tmp_path / 'tree'
    base = root / 'marker'
    base.mkdir(parents=True)
    pattern = 'marker/**'
    cache = ops._glob_witness_cache_path((root,), pattern)
    cache.parent.mkdir(parents=True)
    # iglob('**') skips its initial empty string: an empty directory
    # does not satisfy marker/**. A forged witness must not invent it.
    cache.write_text(json.dumps({'base': str(base), 'path': str(base)}))
    calls = count_probe(monkeypatch)
    assert ops.glob_reaches((root,), pattern) == 'none'
    assert calls == [1]
