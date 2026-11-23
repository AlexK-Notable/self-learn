"""Second independent review: synthetic fixtures, no external services."""
import json
from pathlib import Path

import pytest

from self_learn import cli, gitops, select, teach
from self_learn.ledger_ops import LedgerOpsError
from support import init_repo, git, commit_all
from test_select import home, put, ids, snapshot
from test_packr_feedback import feedback_home, _seed

REVIEW_LESSONS = ['Before restarting a docker container, check the compose file for the volume mounts and the restart policy.', 'When editing Hyprland config, use hypr-ipc instead of hyprctl keyword.', 'Python virtual environments live in .venv and are managed by uv.', 'Never run sudo from the agent shell; pam faillock locks the account.', 'Run the test suite through test-sweep, never under timeout.', 'Commit and push personal repositories after each unit of work.', 'Read the live kernel parameters before declaring a modprobe edit applied.', 'Use rg with no-ignore when searching the config directory.', 'Ghostty is built from source with system zig; never use the nix flake.', 'The keyring password must equal the login password.', 'Wine opens the optical drive on every game launch.', 'Pass the model explicitly when launching a subagent.', 'Firewall rules live in ufw user rules; docker ports bypass ufw.', 'Capture lessons quietly without asking for confirmation.', 'Check DDC before repairing a dark monitor after a KVM switch.', 'Prefer sourcing information over inference when answering empirical questions.']

@pytest.mark.parametrize('query,target', [
    ('run the test suite', 4), ('launch a subagent', 11),
    ('hyprland config', 1), ('docker', 0), ('ghostty', 8), ('sudo', 3),
])
def test_short_task_recall(query, target):
    scores = select._lexical({str(n): text for n, text in enumerate(REVIEW_LESSONS)}, query)
    assert scores.get(str(target), 0) >= select.LEXICAL_THRESHOLD

@pytest.mark.parametrize('query', ['use the new api for the search page', 'rules for the user interface'])
def test_generic_overlap_is_not_task_evidence(query):
    scores = select._lexical({str(n): text for n, text in enumerate(REVIEW_LESSONS)}, query)
    assert not {rid for rid, score in scores.items() if score >= select.LEXICAL_THRESHOLD}

@pytest.mark.parametrize('contents', ['[', '[]', 'projects: [{path: /project, future_key: true}]'])
def test_bad_hosts_keeps_user_and_exact_project(home, tmp_path, capsys, contents):
    project = tmp_path / 'project'; init_repo(project)
    put(home, 1); put(home, 2, scope='project', project=project)
    (home / 'hosts.yaml').write_text(contents)
    before = snapshot(tmp_path)
    assert cli.main(['select', '--query', 'Docker container', '--project', str(project), '--no-embed', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert set(ids(result)) == {'lrn-00000001', 'lrn-00000002'}
    assert 'hosts.yaml unreadable; ancestor lessons omitted' in result['note']
    assert snapshot(tmp_path) == before


def test_git_glob_prefix_bounds_inventory(tmp_path, monkeypatch):
    project = tmp_path / 'project'; init_repo(project)
    (project / 'src').mkdir(); (project / 'src/app.py').touch()
    (project / 'large').mkdir()
    for n in range(20): (project / 'large' / str(n)).touch()
    monkeypatch.setattr(select, 'PATH_SCAN_LIMIT', 5)
    assert select.task_paths(['src/*.py'], project) == ['src/app.py']


@pytest.mark.parametrize('tracked', [False, True])
@pytest.mark.parametrize('pattern', ['nested/**/*.py', '**/*.py'])
def test_nested_git_inventory(tmp_path, tracked, pattern):
    project = tmp_path / 'project'; init_repo(project)
    nested = project / 'nested'; init_repo(nested)
    (nested / 'app.py').touch(); (nested / '.gitignore').write_text('ignored.py\n')
    commit_all(nested, 'synthetic nested repository')
    (nested / 'ignored.py').touch()
    if tracked:
        # Git stores the nested checkout as a gitlink, like a submodule.
        git(project, 'add', 'nested'); git(project, 'commit', '-m', 'synthetic gitlink')
    before = snapshot(project)
    assert select.task_paths([pattern], project) == ['nested/app.py']
    assert snapshot(project) == before


def test_git_inventory_disables_fsmonitor(tmp_path):
    project = tmp_path / 'project'; init_repo(project)
    (project / 'app.py').touch(); commit_all(project, 'synthetic tracked file')
    marker = tmp_path / 'monitor-started'
    hook = tmp_path / 'monitor-hook'
    hook.write_text('#!/bin/sh\nprintf called > ' + str(marker) + '\nprintf "synthetic\\0"\n')
    hook.chmod(0o700)
    git(project, 'config', 'core.fsmonitor', str(hook))
    git(project, 'ls-files')
    assert marker.exists(), 'positive control: Git really invokes the configured hook'
    marker.unlink()
    before = snapshot(tmp_path)
    assert select.task_paths(['**/*.py'], project) == ['app.py']
    assert not marker.exists()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('verb', ['note', 'confirm-held', 'supersede', 'teach'])
@pytest.mark.parametrize('error', [LedgerOpsError, OSError])
def test_receipt_read_failure_keeps_committed_result(feedback_home, monkeypatch, capsys, verb, error):
    rid = _seed(feedback_home, routed=True)
    replacement = _seed(feedback_home)
    def fail_read(*args): raise error('synthetic concurrent move')
    monkeypatch.setattr(teach, 'record_receipt', fail_read)
    args = {'note': [rid, '--append', 'Synthetic feedback', '--key', 'event'],
            'confirm-held': [rid, '--key', 'event'],
            'supersede': [rid, replacement],
            'teach': ['--skill', 's', '--type', 'knowledge', '--fact', 'Synthetic capture']}[verb]
    old_head = gitops.head_sha(feedback_home)
    capsys.readouterr()
    assert cli.main([verb, *args, '--json', '--no-push']) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['id'].startswith('lrn-')
    assert receipt['path'] is None
    assert receipt['receipt_error'] == 'record unavailable after operation; use show to reconcile'
    if verb != 'teach': assert receipt['applied'] is True
    assert gitops.head_sha(feedback_home) != old_head


def test_select_without_git_returns_controlled_error(home, tmp_path, monkeypatch, capsys):
    project = tmp_path / 'project'; project.mkdir()
    put(home)
    monkeypatch.setenv('PATH', str(tmp_path / 'empty-bin'))
    before = snapshot(home)
    assert cli.main(['select', '--query', 'Docker container', '--project', str(project), '--no-embed', '--json']) == 5
    output = capsys.readouterr()
    assert output.out == '' and 'Git unavailable' in output.err
    assert 'Traceback' not in output.err
    assert snapshot(home) == before


def test_supersede_retry_reconciles_with_show(feedback_home, capsys):
    old = _seed(feedback_home); new = _seed(feedback_home)
    capsys.readouterr()
    assert cli.main(['supersede', old, new, '--json', '--no-push']) == 0
    assert json.loads(capsys.readouterr().out)['applied'] is True
    head = gitops.head_sha(feedback_home)
    assert cli.main(['supersede', old, new, '--json', '--no-push']) == 1
    assert capsys.readouterr().out == ''
    assert gitops.head_sha(feedback_home) == head
    assert cli.main(['show', old, '--json']) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['status'] == 'superseded' and record['superseded_by'] == new


def test_nested_git_literal_prefix_budget(tmp_path, monkeypatch):
    project = tmp_path / 'project'; init_repo(project)
    nested = project / 'nested'; init_repo(nested)
    (nested / 'src').mkdir(); (nested / 'src/app.py').touch()
    (nested / 'large').mkdir()
    for n in range(20): (nested / 'large' / str(n)).touch()
    monkeypatch.setattr(select, 'PATH_SCAN_LIMIT', 5)
    assert select.task_paths(['nested/src/*.py'], project) == ['nested/src/app.py']
