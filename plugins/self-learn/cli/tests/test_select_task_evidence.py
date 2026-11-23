"""Task retrieval evidence: synthetic context, paraphrases and generic overlap."""
from pathlib import Path

from self_learn import select
from self_learn.index.related import COSINE_THRESHOLDS
from self_learn.index.store import LessonIndex
from test_select import home, put, ids, snapshot


def test_verbose_task_preserves_distinctive_local_evidence(home):
    put(home, text='Amber registry requires immutable stamps for archival recovery.', knowledge=True)
    result = select.select_lessons(home,
        'Investigate the amber registry after a colleague reported inconsistent behavior yesterday; '
        'work out the underlying problem and explain what we should do next.', provider=None)
    assert ids(result) == ['lrn-00000001']


def test_paraphrase_uses_query_embedding_role(home, monkeypatch):
    class Asymmetric:
        model_id = 'synthetic-query-role'
        dim = 2
        query_calls = []
        def embed(self, texts):
            return [[1.0, 0.0] if 'Cryogenic' in t else [0.0, 1.0] for t in texts]
        def embed_query(self, texts):
            self.query_calls.extend(texts)
            return [[1.0, 0.0] for _ in texts]
    put(home, text='Cryogenic repositories require redundant generators.', knowledge=True)
    fake = Asymmetric()
    monkeypatch.setitem(COSINE_THRESHOLDS, fake.model_id, .75)
    index = LessonIndex.open(home); index.build(fake); index.close()
    query = 'Power loss threatens our preserved specimens'
    assert not ids(select.select_lessons(home, query, provider=None))
    result = select.select_lessons(home, query, provider=fake)
    assert ids(result) == ['lrn-00000001'] and fake.query_calls == [query]
    assert result['lessons'][0]['score']['basis'] == 'cosine'


def test_absolute_user_gate_is_home_relative_and_supplies_context(home, tmp_path, monkeypatch):
    user = tmp_path / 'person'; user.mkdir()
    project = user / 'workspace'; project.mkdir()
    monkeypatch.setenv('HOME', str(user))
    monkeypatch.chdir(project)
    path = user / 'notes/amber_registry.ini'
    path.parent.mkdir(); path.touch()
    put(home, text='Amber registry requires immutable stamps for archival recovery.', knowledge=True,
        gates=['notes/amber_registry.ini'])
    before = snapshot(tmp_path)
    result = select.select_lessons(home, 'Amber registry', paths=[str(path)], provider=None)
    assert ids(result) == ['lrn-00000001']
    assert result['lessons'][0]['matched_paths'] == ['notes/amber_registry.ini']
    assert snapshot(tmp_path) == before
    assert not ids(select.select_lessons(home, 'Amber registry', paths=[str(user / 'other.ini')], provider=None))


def test_project_context_narrows_scope_but_requires_task_evidence(home, tmp_path):
    project = tmp_path / 'amber-registry'; project.mkdir()
    put(home, scope='project', project=project,
        text='Amber registry requires immutable stamps for archival recovery.', knowledge=True)
    assert not ids(select.select_lessons(home, 'Review the planned change', provider=None))
    result = select.select_lessons(home, 'Review the planned change', project=project, provider=None)
    assert not ids(result)
    assert ids(select.select_lessons(home, 'Amber registry', project=project, provider=None)) == ['lrn-00000001']
    other = tmp_path / 'unrelated-project'; other.mkdir()
    assert not ids(select.select_lessons(home, 'Amber registry', project=other, provider=None))


def test_explicit_path_context_is_not_inferred_from_query_or_gold(home, tmp_path):
    project = tmp_path / 'amber-registry'; project.mkdir()
    put(home, scope='project', project=project, gates=['settings/*.ini'],
        text='Amber registry requires immutable stamps.', knowledge=True)
    assert not ids(select.select_lessons(home, 'Amber registry settings.ini', project=project, provider=None))


def test_numeric_address_fragments_do_not_establish_a_topic():
    texts = {'network': 'Container port mappings bypass firewall rules. Probe 172.31.8.90 from another machine.',
             'other': 'Immutable archival stamps identify amber registry snapshots.'}
    texts.update({str(n): 'Allow SSH from another machine through firewall rules and inspect policy ' + str(n) for n in range(8)})
    assert 'network' not in select._lexical(texts, 'Allow SSH from 172.31.0.0/16 through the firewall rules')
    assert 'network' in select._lexical(texts, 'Container port mappings')


def test_specific_file_context_does_not_inherit_generic_project_match(home, tmp_path):
    project = tmp_path / 'amber-registry'; project.mkdir()
    put(home, scope='project', project=project,
        text='Amber registry deployment requires checking the production revision.', knowledge=True)
    result = select.select_lessons(home, 'Review the planned change', project=project,
        literal_paths=['scripts/chart_report.py'], provider=None)
    assert not ids(result)
    assert ids(select.select_lessons(home, 'Amber registry deployment', project=project, provider=None))


def test_current_semantic_negative_is_not_overridden_by_word_overlap(home, monkeypatch):
    put(home, text='Amber registry requires immutable stamps for archival recovery.', knowledge=True)
    monkeypatch.setattr(select, '_semantic', lambda *a, **k: ({'lrn-00000001': .2}, .75, ''))
    assert not ids(select.select_lessons(home, 'Amber registry'))
    # An absent vector is missing evidence, not negative evidence.
    monkeypatch.setattr(select, '_semantic', lambda *a, **k: ({}, .75, 'no current vectors'))
    assert ids(select.select_lessons(home, 'Amber registry')) == ['lrn-00000001']


def test_longer_distinctive_phrase_combines_moderately_common_terms():
    texts = {'target': 'Amber registry settings require immutable archival stamps.'}
    for term in ('amber', 'registry', 'settings'):
        for n in range(2):
            texts[f'{term}-{n}'] = f'{term} requires a separate workflow for unrelated purposes'
    for n, term in enumerate(('marble', 'spruce', 'cobalt')):
        texts[str(n)] = f'{term} has synthetic unrelated specifications'
    scores = select._lexical(texts,
        'Investigate amber registry settings after yesterday; explain the underlying issue to a colleague.')
    assert scores.get('target', 0) >= select.LEXICAL_THRESHOLD
    assert not select._lexical(texts, 'Explain the general workflow for the new project')


def test_context_does_not_join_words_from_different_files():
    texts = {'target': 'Amber registry requires immutable archival stamps.'}
    context = 'File: some/unrelated/tree/amber\nFile: registry/another/unrelated/place'
    assert not select._lexical(texts, 'Review the planned change', context=context)
    assert not select._lexical(texts, 'Review the planned change', context='File: amber_registry.ini')
    assert select._lexical(texts, 'Amber registry', context='File: amber_registry.ini')


def test_task_supported_context_fields_still_do_not_join():
    words = ['amber', 'registry', *(f'token{n}' for n in range(30))]
    texts = {'target': ' '.join(words)}
    separate = 'File: ' + ' '.join(words[:16]) + '\nFile: ' + ' '.join(words[16:])
    together = 'File: ' + ' '.join(words)
    split_score = select._lexical(texts, 'Amber registry', context=separate)['target']
    joined_score = select._lexical(texts, 'Amber registry', context=together)['target']
    assert split_score >= select.LEXICAL_THRESHOLD
    assert joined_score > split_score
