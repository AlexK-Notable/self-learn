"""S-161 independent-review regressions; synthetic ledger and local Git only."""
import json
from pathlib import Path

import pytest

from self_learn import cli, gitops, select, verbs
from self_learn.index.related import COSINE_THRESHOLDS
from self_learn.index.store import FROM_ENV, LessonIndex
from self_learn.records import Record
from support import init_repo
from test_index import TopicProvider
from test_packr_feedback import feedback_home, _seed
from test_select import home, ids, put, snapshot


@pytest.mark.parametrize('verb', ['note', 'confirm-held'])
@pytest.mark.parametrize('key', ['a' * 64, 'Ab9x' * 12, 'Ab9x' * 10, '', 'two words'])
def test_key_refused_before_any_write(feedback_home, capsys, verb, key):
    rid = _seed(feedback_home, routed=True)
    before = snapshot(feedback_home)
    sha = gitops.head_sha(feedback_home)
    capsys.readouterr()
    extra = ['--append', 'A synthetic observation'] if verb == 'note' else []
    assert cli.main([verb, rid, *extra, '--key', key, '--json', '--no-push']) == 64
    output = capsys.readouterr()
    assert output.out == '' and '--key' in output.err
    assert snapshot(feedback_home) == before
    assert gitops.head_sha(feedback_home) == sha


@pytest.mark.parametrize('verb', ['note', 'confirm-held'])
def test_safe_key_retry_and_later_verb(feedback_home, capsys, verb):
    rid = _seed(feedback_home, routed=True)
    key = 'event:0123456789abcdef0123456789abcdef'
    extra = ['--append', 'A synthetic observation'] if verb == 'note' else []
    capsys.readouterr()
    for applied in (True, False):
        assert cli.main([verb, rid, *extra, '--key', key, '--json', '--no-push']) == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt['applied'] is applied
        assert receipt['pushed'] == 'not_requested'
    assert verbs.note(feedback_home, rid, append='Later observation', no_push=True).staged


def test_lexical_score_does_not_depend_on_exclusion_or_scope(home, tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    target = put(home, text='Restart the web container after changing the config file', knowledge=True)
    other = put(home, 2, text='Use isolated tests for database migrations', knowledge=True)
    put(home, 3, text='Configure login password storage in the keyring', knowledge=True,
        scope='project', project=project)
    query = 'restart web container with changed configuration'
    results = [select.select_lessons(home, query, provider=None, **kw) for kw in (
        {}, {'exclude': [other.stem]}, {'project': project}, {'paths': ['src/new.py']})]
    assert all(target.stem in ids(r) for r in results)
    scores = [next(x['score']['lexical'] for x in r['lessons'] if x['id'] == target.stem) for r in results]
    assert scores == [scores[0]] * len(scores)
    assert scores[0] >= select.LEXICAL_THRESHOLD


# Labels concern task applicability, not mere word overlap. Fixed before the fix.
CALIBRATION_LESSONS = [
    'Before editing Docker container configuration check container health and restart the web container.',
    'Store the login password in the desktop keyring for the desktop session.',
    'Run integration tests through test sweep for shared machine test budgets.',
    'Pass the model explicitly when launching a subagent.',
    'Check the config file path before changing terminal font settings.',
    'Keep parser fixtures isolated and parse escaped delimiters before tokenizing input.',
    'Back up database snapshots before applying database migrations.',
    'Verify screenshot pixels before describing browser visibility.',
    'Use stable feedback keys when retrying lesson observations.',
    'Preserve symlink spelling when matching project file paths.',
    'Bound notification waits when sending action buttons.',
    'Keep generated vector dimensions aligned with the embedding model.',
    'Rotate application log files before disk space is exhausted.',
    'Use atomic rename when replacing a stored document.',
    'Resolve transaction conflicts before retrying database writes.',
    'Retain source attribution when summarizing research documents.',
]
CALIBRATION_CASES = [
    ('add a login page', set()),
    ('launch the game', set()),
    ('check the config file', set()),
    ('a file', set()),
    ('write unit tests for the parser', set()),
    ('medieval watercolor astronomy', set()),
    ('restart Docker container configuration', {1}),
    ('store desktop login password in keyring', {2}),
    ('parse escaped delimiters in parser fixtures', {6}),
    ('back up database snapshots before migrations', {7}),
    ('retry lesson observations with stable feedback keys', {9}),
    ('match project file paths preserving symlink spelling', {10}),
]


@pytest.mark.parametrize('query,expected', CALIBRATION_CASES)
def test_task_lexical_calibration(home, query, expected):
    for number, text in enumerate(CALIBRATION_LESSONS, 1):
        put(home, number, text=text, knowledge=True)
    result = select.select_lessons(home, query, provider=None)
    assert set(ids(result)) == {f'lrn-{n:08x}' for n in expected}


def test_ancestor_project_scope_and_ancestor_relative_gate(home, tmp_path):
    parent = tmp_path / 'parent'; child = parent / 'child'; sibling = parent / 'sibling'
    for p in (parent, child, sibling):
        init_repo(p)
    (home / 'hosts.yaml').write_text(f'projects:\n  - path: {parent}\n  - path: {child}\n  - path: {sibling}\n')
    put(home, 1, scope='project', project=parent, gates=['child/src/**/*.py'])
    put(home, 2, scope='project', project=child)
    put(home, 3, scope='project', project=sibling)
    result = select.select_lessons(home, 'Docker container health', project=child,
                                   paths=['src/new.py'], provider=None)
    assert set(ids(result)) == {'lrn-00000001', 'lrn-00000002'}
    ancestor = next(x for x in result['lessons'] if x['id'] == 'lrn-00000001')
    assert ancestor['scope_relation'] == 'ancestor-project'
    assert 'ancestor project scope' in ancestor['why']
    assert ancestor['matched_paths'] == ['child/src/new.py']


def test_glob_ignores_git_and_ignored_trees(home, tmp_path, monkeypatch):
    project = tmp_path / 'project'; init_repo(project)
    (project / '.gitignore').write_text('node_modules/\n.venv/\n')
    for directory in ('.git/objects/synthetic', 'node_modules', '.venv'):
        root = project / directory; root.mkdir(parents=True, exist_ok=True)
        for i in range(40):
            (root / f'file{i}.py').touch()
    (project / 'src').mkdir(); (project / 'src/main.py').touch()
    monkeypatch.setattr(select, 'PATH_SCAN_LIMIT', 10)
    assert select.task_paths(['**/*.py'], project) == ['src/main.py']


def test_glob_budget_preserves_ungated_lessons(home, tmp_path, monkeypatch):
    project = tmp_path / 'project'; project.mkdir()
    for i in range(4):
        (project / f'file{i}.py').touch()
    put(home, 1); put(home, 2, gates=['**/*.py'])
    monkeypatch.setattr(select, 'PATH_SCAN_LIMIT', 1)
    result = select.select_lessons(home, 'Docker container health', project=project,
                                   paths=['**/*.py'], provider=None)
    assert ids(result) == ['lrn-00000001']
    assert 'path-gated lessons omitted' in result['note']


@pytest.mark.parametrize('exists', [True, False])
def test_bracket_path_existing_or_explicit_literal(home, tmp_path, capsys, exists):
    project = tmp_path / 'project'; project.mkdir()
    path = project / 'app/[slug]/page.tsx'
    if exists:
        path.parent.mkdir(parents=True); path.touch()
    put(home, gates=['app/**/page.tsx'])
    flag = '--path' if exists else '--literal-path'
    assert cli.main(['select', '--query', 'Docker container health', '--project', str(project),
                     flag, 'app/[slug]/page.tsx', '--no-embed', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert ids(result) == ['lrn-00000001']
    assert result['lessons'][0]['matched_paths'] == ['app/[slug]/page.tsx']


def test_symlink_literal_uses_given_name_and_outside_does_not_abort(home, tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    (project / 'actual.py').touch()
    (project / 'named.py').symlink_to(project / 'actual.py')
    (tmp_path / 'external.py').touch()
    (project / 'external.py').symlink_to(tmp_path / 'external.py')
    put(home, 1); put(home, 2, gates=['named.py']); put(home, 3, gates=['external.py'])
    result = select.select_lessons(home, 'Docker container health', project=project,
                                   paths=['named.py', 'external.py'], provider=None)
    assert set(ids(result)) == {'lrn-00000001', 'lrn-00000002'}
    assert result['lessons'][1]['matched_paths'] == ['named.py']
    assert 'outside project' in result['note']


def test_nonrouted_confirmation_refuses_before_lock(feedback_home, monkeypatch):
    rid = _seed(feedback_home)
    def forbidden(*args, **kwargs):
        pytest.fail('invalid confirmation acquired a write-side resource')
    monkeypatch.setattr(verbs.sentinel, 'hold', forbidden)
    monkeypatch.setattr(verbs, '_ledger_write', forbidden)
    with pytest.raises(verbs.VerbError, match='pending'):
        verbs.confirm_held(feedback_home, rid, key='observation', no_push=True)


@pytest.mark.parametrize('args', [['--query', ' '], ['--query', 'x', '--limit', '-1']])
def test_select_value_errors_use_usage_code(home, args):
    assert cli.main(['select', *args, '--no-embed']) == 64


@pytest.mark.parametrize('verb', ['note', 'confirm-held', 'supersede'])
def test_feedback_help_names_receipt(home, capsys, verb):
    assert cli.main([verb, '--help']) == 0
    out = capsys.readouterr().out
    assert 'receipt' in out and 'applied' in out and 'pushed' in out
    if verb == 'note':
        assert 'provider' in out and 'sheet-line hash' not in out


def test_from_env_without_key_with_vectors_is_read_only(home, tmp_path, monkeypatch):
    put(home)
    fake = TopicProvider()
    monkeypatch.setitem(COSINE_THRESHOLDS, fake.model_id, .75)
    ix = LessonIndex.open(home); ix.build(fake); ix.close()
    monkeypatch.setattr(select, 'load_provider', lambda: (None, 'fixture: no embedding key'))
    before = snapshot(tmp_path)
    result = select.select_lessons(home, 'Docker container health', provider=FROM_ENV)
    assert ids(result) == ['lrn-00000001'] and result['mode'] == 'lexical-only'
    assert 'no embedding key' in result['note']
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('verb', ['confirm-held', 'supersede'])
@pytest.mark.parametrize('conflict', [False, True])
def test_other_feedback_push_failure_receipt(feedback_home, monkeypatch, capsys, verb, conflict):
    rid = _seed(feedback_home, routed=verb == 'confirm-held')
    extra = ['--key', 'event'] if verb == 'confirm-held' else [_seed(feedback_home)]
    def failed_push(repo, **kwargs):
        return gitops.PushResult(ok=False, rebase_conflict=conflict, detail='synthetic offline')
    for name in ('push_pending', 'push_if_remote', 'push_with_retry'):
        monkeypatch.setattr(gitops, name, failed_push)
    capsys.readouterr()
    assert cli.main([verb, rid, *extra, '--json']) == (
        gitops.EXIT_REBASE_CONFLICT if conflict else gitops.EXIT_PUSH_FAILED)
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['id'] == rid and receipt['applied'] is True
    assert receipt['pushed'] == 'failed'


@pytest.mark.parametrize('link', ['statement', 'supersedes'])
def test_teach_linked_json_is_one_object(feedback_home, monkeypatch, capsys, link):
    from self_learn import teach
    if link == 'statement':
        monkeypatch.setattr(teach.statements, 'user_message_ref', lambda *a: 'transcript:fixture#L1')
        extra = ['--statement', 'Keep synthetic operations isolated', '--session', 'fixture']
    else:
        old = _seed(feedback_home)
        extra = ['--supersedes', old]
    capsys.readouterr()
    assert cli.main(['teach', '--skill', 's', '--type', 'knowledge', '--fact',
                     'Synthetic operations use an isolated fixture', '--json', '--no-push', *extra]) == 0
    receipt = json.loads(capsys.readouterr().out)
    record = Record.from_path(receipt['path'])
    assert record.id == receipt['id'] and record.status == 'pending'
    if link == 'statement':
        row = json.loads((feedback_home / 'user-statements.jsonl').read_text())
        assert row['verbatim'] == 'Keep synthetic operations isolated'
    else:
        assert record.supersedes == old


@pytest.mark.parametrize('verb', ['note', 'confirm-held'])
def test_direct_verb_rejects_unsafe_key_before_resources(feedback_home, monkeypatch, verb):
    rid = _seed(feedback_home, routed=True)
    before = snapshot(feedback_home)
    def forbidden(*args, **kwargs):
        pytest.fail('unsafe key reached a write resource')
    monkeypatch.setattr(verbs.sentinel, 'hold', forbidden)
    operation = verbs.note if verb == 'note' else verbs.confirm_held
    extra = {'append': 'Synthetic observation'} if verb == 'note' else {}
    with pytest.raises(verbs.VerbUsageError, match='--key'):
        operation(feedback_home, rid, key='Ab9x' * 10, no_push=True, **extra)
    assert snapshot(feedback_home) == before


def test_git_inventory_read_only_and_budget_reaps_child(home, tmp_path, monkeypatch):
    project = tmp_path / 'project'; init_repo(project)
    for n in range(4):
        (project / f'file{n}.py').touch()
    put(home, 1); put(home, 2, gates=['**/*.py'])
    before = snapshot(tmp_path)
    result = select.select_lessons(home, 'Docker container health', project=project,
                                   paths=['**/*.py'], provider=None)
    assert set(ids(result)) == {'lrn-00000001', 'lrn-00000002'}
    assert snapshot(tmp_path) == before
    opened = []
    popen = select.subprocess.Popen
    def tracked(*args, **kwargs):
        child = popen(*args, **kwargs)
        opened.append(child)
        return child
    monkeypatch.setattr(select.subprocess, 'Popen', tracked)
    monkeypatch.setattr(select, 'PATH_SCAN_LIMIT', 1)
    result = select.select_lessons(home, 'Docker container health', project=project,
                                   paths=['**/*.py'], provider=None)
    assert ids(result) == ['lrn-00000001'] and 'path-gated lessons omitted' in result['note']
    assert opened and all(child.poll() is not None for child in opened)
    assert snapshot(tmp_path) == before


def test_record_keeps_oldest_confirmation_key(feedback_home):
    rid = _seed(feedback_home, routed=True)
    for n in range(8):
        verbs.confirm_held(feedback_home, rid, key=f'event-{n}', no_push=True)
    before = snapshot(feedback_home)
    result = verbs.confirm_held(feedback_home, rid, key='event-0', no_push=True)
    assert not result.staged
    assert snapshot(feedback_home) == before
    record = Record.from_path(next(feedback_home.rglob(f'{rid}.md')))
    assert all(record.confirmation_has_key(f'event-{n}') for n in range(8))


def test_feedback_receipt_separates_verb_diagnostics(feedback_home, monkeypatch, capsys):
    rid = _seed(feedback_home)
    real_note = verbs.note
    def noisy_note(*args, **kwargs):
        print('Synthetic diagnostic from verb')
        return real_note(*args, **kwargs)
    monkeypatch.setattr(verbs, 'note', noisy_note)
    capsys.readouterr()
    assert cli.main(['note', rid, '--append', 'Synthetic observation', '--key', 'event',
                     '--json', '--no-push']) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['applied'] is True
    assert 'Synthetic diagnostic from verb' in output.err


def test_batch_preview_refuses_unsafe_feedback_key(feedback_home):
    from self_learn import batch
    rid = _seed(feedback_home)
    before = snapshot(feedback_home)
    item = batch.SheetItem(1, rid, 'note', {'append': 'Synthetic observation', 'key': 'a' * 64})
    preview = batch.dry_run(feedback_home, [item])
    assert preview.items[0].state == 'would-refuse'
    assert '--key' in str(preview.items[0])
    assert snapshot(feedback_home) == before
