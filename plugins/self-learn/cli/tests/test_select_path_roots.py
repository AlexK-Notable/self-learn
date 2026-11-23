"""User path reachability and a shared inventory deadline."""
from types import SimpleNamespace

from self_learn import select
from support import init_repo
from test_select import home, put, ids


def test_user_gates_include_registered_hosts_outside_home(home, tmp_path, monkeypatch):
    user = tmp_path / 'person'; user.mkdir()
    monkeypatch.setenv('HOME', str(user))
    project = tmp_path / 'external-host'; project.mkdir()
    (project / 'src').mkdir(); (project / 'src/component.py').touch()
    (home / 'hosts.yaml').write_text(f'projects:\n  - path: {project}\n')
    put(home, gates=['src/*.py'])
    result = select.select_lessons(home, 'Docker container restart', project=project,
                                   paths=['src/component.py'], provider=None)
    assert ids(result) == ['lrn-00000001']
    assert result['lessons'][0]['matched_paths'] == ['src/component.py']
    # Removing registration removes this extra user-glob root.
    (home / 'hosts.yaml').write_text('projects: []\n')
    assert not ids(select.select_lessons(home, 'Docker container restart', project=project,
                                         paths=['src/component.py'], provider=None))


def test_nested_git_inventories_share_elapsed_time_budget(tmp_path, monkeypatch):
    import time
    root = tmp_path / 'root'; init_repo(root)
    nested = root / 'nested'; init_repo(nested)
    (nested / 'hit.py').touch()
    elapsed = [0.]
    monkeypatch.setattr(time, 'monotonic', lambda: elapsed[0])
    deadlines = []
    def bounded(argv, **kwargs):
        if 'ls-files' not in argv:
            return SimpleNamespace(returncode=0, stdout=str(root).encode() + b'\n', stderr=b'')
        deadlines.append(kwargs['timeout'])
        elapsed[0] += 20 if len(deadlines) == 1 else 1
        data = b'nested/\0' if str(kwargs['cwd']) == str(root) else b'hit.py\0'
        return SimpleNamespace(returncode=0, stdout=data, stderr=b'')
    monkeypatch.setattr(select.procs, 'run_bounded', bounded)
    assert select.task_paths(['**/*.py'], root) == ['nested/hit.py']
    assert len(deadlines) == 2 and deadlines[0] == 30
    assert deadlines[1] == 10


def test_absolute_path_groups_share_inventory_budget(tmp_path, monkeypatch):
    import pytest
    user = tmp_path / 'person'; init_repo(user)
    project = user / 'project'; init_repo(project)
    other = user / 'other'; other.mkdir()
    monkeypatch.setenv('HOME', str(user))
    for folder in (project, other):
        (folder / 'one.py').touch(); (folder / 'two.py').touch()
    patterns = [str(project / '*.py'), str(other / '*.py')]
    assert len(select._absolute_task_paths(patterns, project, [], [])) == 4
    monkeypatch.setattr(select, 'PATH_SCAN_LIMIT', 3)
    with pytest.raises(select.PathScanError, match='budget'):
        select._absolute_task_paths(patterns, project, [], [])
