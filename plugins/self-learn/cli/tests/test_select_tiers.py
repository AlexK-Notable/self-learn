"""Task evidence, bounded disclosure and confidence tiers (S-161)."""
import json

import pytest

from self_learn import select
from self_learn.index.gemini import GeminiEmbedder
from self_learn.index.store import LessonIndex
from test_select import home, put, ids


def recording_provider(home, monkeypatch):
    calls = []
    def transport(action, body, timeout):
        calls.append(body)
        return {'embeddings': [{'values': [1., 0.]} for _ in body['requests']]}
    provider = GeminiEmbedder(dim=2, api_key='synthetic', transport=transport)
    index = LessonIndex.open(home); index.build(provider); index.close()
    # The synthetic dimension deliberately differs from the calibrated model.
    monkeypatch.setitem(select.TASK_COSINE_THRESHOLDS, provider.model_id, .70)
    calls.clear()
    return provider, calls


def test_expanded_names_never_reach_embedding_request(home, tmp_path, monkeypatch):
    project = tmp_path / 'private-project-name'; project.mkdir()
    alias = tmp_path / 'caller-typed-alias'; alias.symlink_to(project, target_is_directory=True)
    (project / 'private-witness.py').touch()
    put(home, scope='project', project=project, gates=['*.py'])
    provider, calls = recording_provider(home, monkeypatch)
    result = select.select_lessons(home, 'Docker container restart', project=alias,
                                   paths=['*.py'], provider=provider)
    assert ids(result) == ['lrn-00000001']
    assert result['lessons'][0]['matched_paths'] == ['private-witness.py']
    assert len(calls) == 1 and len(calls[0]['requests']) == 2
    assert '*.py' in json.dumps(calls)
    assert 'private-witness.py' not in json.dumps(calls)
    assert 'caller-typed-alias' in json.dumps(calls)
    assert 'private-project-name' not in json.dumps(calls)


@pytest.mark.parametrize("width", [1, 110])
def test_caller_context_has_line_and_utf8_byte_caps(home, tmp_path, monkeypatch, width):
    put(home)
    provider, calls = recording_provider(home, monkeypatch)
    paths = ['planned/' + ('é' * width) + str(n) for n in range(40)]
    result = select.select_lessons(home, 'Docker container restart', project=tmp_path,
                                   literal_paths=paths, provider=provider)
    assert ids(result) == ['lrn-00000001'] and calls
    text = calls[0]['requests'][-1]['content']['parts'][0]['text']
    context = text.split('Task context:\n', 1)[1]
    assert len(context.encode()) <= 2048
    assert context.count('File: ') <= 20
    assert paths[-1] not in text
    assert 'context truncated' in result['note']


def test_context_cannot_supply_task_evidence():
    from test_provider_review2 import REVIEW_LESSONS as lessons
    REVIEW_LESSONS = {f"r{n:02d}": text for n, text in enumerate(lessons)}
    assert select._lexical(REVIEW_LESSONS, 'ghostty')  # corpus positive control
    assert not select._lexical(REVIEW_LESSONS, 'fix a typo in the readme', context='Project: ghostty')
    assert not select._lexical(REVIEW_LESSONS, 'update copyright year', context='File: docs/game-launch.md')


def test_word_order_and_regular_inflections_preserve_local_evidence():
    from test_provider_review2 import REVIEW_LESSONS as lessons
    REVIEW_LESSONS = {f"r{n:02d}": text for n, text in enumerate(lessons)}
    for query, target in [('docker web container restart', 'r00'), ('ghostty build with nix fails', 'r08')]:
        assert select._lexical(REVIEW_LESSONS, query).get(target, 0) >= select.LEXICAL_THRESHOLD
    assert select._lexical({'one': 'Archives stamp immutable registries.'}, 'Archival stamps immutable registry')


def test_context_semantics_cannot_override_unrelated_task(home, tmp_path, monkeypatch):
    put(home, knowledge=True, text='Amber registry requires immutable stamps.')
    class Provider:
        model_id = 'synthetic-task-context'
        dim = 2
        def embed(self, texts): return [[1., 0.] for _ in texts]
        def embed_query(self, texts):
            return [[1., 0.] if 'Task context:' in text else [0., 1.] for text in texts]
    fake = Provider()
    monkeypatch.setitem(select.TASK_COSINE_THRESHOLDS, fake.model_id, .70)
    index = LessonIndex.open(home); index.build(fake); index.close()
    project = tmp_path / 'amber-registry'; project.mkdir()
    assert not ids(select.select_lessons(home, 'Fix the spelling error', project=project, provider=fake))


def test_gemini_confident_floor_is_calibrated_and_inclusive(home):
    import math
    class ExactCosine:
        model_id = 'gemini-embedding-2@3072/i1'
        dim = 3072
        similarity = .70
        def embed(self, texts):
            return [[1., 0.] + [0.] * 3070 for _ in texts]
        def embed_query(self, texts):
            return [[self.similarity, math.sqrt(1 - self.similarity ** 2)] + [0.] * 3070 for _ in texts]
    put(home)
    fake = ExactCosine()
    index = LessonIndex.open(home); index.build(fake); index.close()
    assert select.TASK_COSINE_THRESHOLDS[fake.model_id] == .70
    for value, expected in [(.69999, []), (.70, ['lrn-00000001'])]:
        fake.similarity = value
        assert ids(select.select_lessons(home, 'Docker container restart', provider=fake)) == expected


def test_two_tiers_preserve_default_and_confident_priority(home, monkeypatch):
    for number in range(1, 4):
        put(home, number)
    values = {'lrn-00000001': .75, 'lrn-00000002': .68, 'lrn-00000003': .3}
    monkeypatch.setattr(select, '_semantic', lambda *a, **k: (
        select.SemanticScores({rid: values[rid] for rid in a[1]}, {}, 'gemini-embedding-2@3072/i1'), .70, ''))
    # A lower-confidence candidate outranks the confident one by raw RRF.
    monkeypatch.setattr(select, '_lexical', lambda *a, **k: {'lrn-00000002': 1.0})
    confident = select.select_lessons(home, 'No shared wording')
    assert ids(confident) == ['lrn-00000001']
    assert confident['lessons'][0]['confidence'] == 'confident'
    all_hits = select.select_lessons(home, 'No shared wording', tier='all')
    assert ids(all_hits) == ['lrn-00000001', 'lrn-00000002']
    assert all_hits['lessons'][1]['confidence'] == 'possible'
    assert 'current vector' in all_hits['lessons'][1]['why']
    assert 'semantic floor' not in all_hits['lessons'][1]['why']
    assert ids(select.select_lessons(home, 'No shared wording', tier='all', limit=1)) == ['lrn-00000001']
    assert ids(select.select_lessons(home, 'No shared wording', tier='all', exclude=['lrn-00000001'])) == ['lrn-00000002']


@pytest.mark.parametrize('query,target', [
    ('write documentation explaining why the agent shell prompt is blue', 3),
    ('translate the login password field labels into french for the signup page', 9),
    ('draw a diagram of the docker container logo for the slides', 0),
    ('summarize the kvm switch product reviews for a purchase decision', 14),
])
def test_lexical_sense_limit_is_guarded_by_current_semantics(home, monkeypatch, query, target):
    from test_provider_review2 import REVIEW_LESSONS
    texts = {f'lrn-{n + 1:08x}': text for n, text in enumerate(REVIEW_LESSONS)}
    # Lexical retrieval cannot distinguish these senses: preserve that explicit
    # limitation as a positive control, rather than inventing a word blacklist.
    assert select._lexical(texts, query).get(f'lrn-{target + 1:08x}', 0) >= select.LEXICAL_THRESHOLD
    for n, text in enumerate(REVIEW_LESSONS, 1):
        put(home, n, text=text, knowledge=True)
    monkeypatch.setattr(select, '_semantic', lambda *a, **k: ({rid: .2 for rid in a[1]}, .70, ''))
    assert not ids(select.select_lessons(home, query))
    assert not ids(select.select_lessons(home, query, tier='all'))


def measured_scores(monkeypatch, task, context=None, lexical=0., model='gemini-embedding-2@3072/i1'):
    def semantic(home, texts, query, provider, **kwargs):
        return select.SemanticScores({rid: task for rid in texts},
            {} if context is None else {rid: context for rid in texts}, model), .70, ''
    monkeypatch.setattr(select, '_semantic', semantic)
    monkeypatch.setattr(select, '_lexical', lambda texts, *a, **k: {rid: lexical for rid in texts})


@pytest.mark.parametrize('task,context,lexical,confidence', [
    (.70, None, 0., 'possible'), (.75, None, 0., 'confident'),
    (.70, None, .5, 'confident'), (.69999, None, .5, 'possible'),
    (.675, .70, .5, 'confident'), (.67499, .70, .5, 'possible'),
    (.65, None, .5, 'possible'), (.64999, None, .5, None),
])
def test_corroboration_decides_confidence(home, monkeypatch, task, context, lexical, confidence):
    put(home)
    measured_scores(monkeypatch, task, context, lexical)
    kwargs = {'project': home.parent} if context is not None else {}
    result = select.select_lessons(home, 'Synthetic task', tier='all', **kwargs)
    assert [hit['confidence'] for hit in result['lessons']] == ([confidence] if confidence else [])
    default = select.select_lessons(home, 'Synthetic task', **kwargs)
    assert bool(default['lessons']) is (confidence == 'confident')


@pytest.mark.parametrize('task,context,matched,expected', [
    (.60, .675, True, True), (.59999, .8, True, False),
    (.60, .67499, True, False), (.60, .8, False, False),
    (0., 1., True, False),
])
def test_possible_context_requires_task_evidence_and_matching_gate(home, tmp_path, monkeypatch, task, context, matched, expected):
    put(home, scope='project', project=tmp_path, gates=['src/*.py'] if matched else None)
    measured_scores(monkeypatch, task, context)
    result = select.select_lessons(home, 'Synthetic task', project=tmp_path,
                                   literal_paths=['src/planned.py'], tier='all')
    assert bool(result['lessons']) is expected
    if expected:
        assert result['lessons'][0]['confidence'] == 'possible'
        assert 'path gate' in result['lessons'][0]['why']
    assert not ids(select.select_lessons(home, 'Synthetic task', project=tmp_path,
                                        literal_paths=['src/planned.py']))


@pytest.mark.parametrize('scope,task,expected', [
    ('skill:synthetic', .725, True), ('skill:synthetic', .72499, False),
    ('user', .75, True), ('user', .74999, False),
])
def test_missing_scope_is_possible_only_on_strong_task_semantics(home, monkeypatch, scope, task, expected):
    put(home, scope=scope, gates=['src/*.py'] if scope == 'user' else None)
    measured_scores(monkeypatch, task, 1., 0.)
    assert not ids(select.select_lessons(home, 'Synthetic task'))
    result = select.select_lessons(home, 'Synthetic task', tier='all')
    assert bool(result['lessons']) is expected
    if expected:
        assert result['lessons'][0]['confidence'] == 'possible'
        assert ('skill not requested' if scope.startswith('skill:') else 'path not supplied') in result['lessons'][0]['why']
    if scope.startswith('skill:'):
        assert not ids(select.select_lessons(home, 'Synthetic task', skills=['different'], tier='all'))
    else:
        assert not ids(select.select_lessons(home, 'Synthetic task', literal_paths=['other.txt'], tier='all'))


def test_scope_exceptions_never_use_lexical_fallback(home, monkeypatch):
    put(home, 1, scope='skill:synthetic')
    put(home, 2, gates=['src/*.py'])
    monkeypatch.setattr(select, '_semantic', lambda *a, **k: ({}, None, 'missing vectors'))
    assert not ids(select.select_lessons(home, 'Docker container restart', tier='all'))
    assert ids(select.select_lessons(home, 'Docker container restart', skills=['synthetic'], tier='all')) == ['lrn-00000001']


def test_unmeasured_model_gets_no_weaker_tier(home, monkeypatch):
    put(home)
    measured_scores(monkeypatch, .69, 1., .9, model='uncalibrated-synthetic')
    assert not ids(select.select_lessons(home, 'Synthetic task', tier='all'))
    measured_scores(monkeypatch, .70, model='uncalibrated-synthetic')
    assert ids(select.select_lessons(home, 'Synthetic task', tier='all')) == ['lrn-00000001']


def test_local_evidence_does_not_bridge_a_long_task_span():
    texts = {'target': 'Amber registry exports require atomic snapshots.',
             **{str(n): f'Synthetic subject{n} has a separate reference.' for n in range(20)}}
    assert select._lexical(texts, 'Inspect amber exports from registry')['target'] >= select.LEXICAL_THRESHOLD
    assert 'target' not in select._lexical(texts,
        'Inspect amber one two three four five six seven eight nine registry')


def test_gapped_anchor_preserves_relative_term_order():
    texts = {'target': 'A cobalt collector needs an amber lock before making changes.',
             **{str(n): f'Synthetic subject{n} has a separate reference.' for n in range(20)}}
    assert select._lexical(texts, 'Inspect cobalt following a discussion of amber')['target'] >= select.LEXICAL_THRESHOLD
    # Two topic words in the opposite relation are insufficient evidence. This
    # pins the retrieval rule, not a claim that lexical order proves relevance.
    assert 'target' not in select._lexical(texts, 'Inspect amber following a discussion of cobalt')


@pytest.mark.parametrize('task,context,gate,expected', [
    (.65, .65, True, True), (.64999, .65, True, False),
    (.65, .64999, True, False), (.65, .65, False, False),
])
def test_balanced_task_context_supports_possible_gate(home, tmp_path, monkeypatch, task, context, gate, expected):
    put(home, scope='project', project=tmp_path, gates=['src/*.py'] if gate else None)
    measured_scores(monkeypatch, task, context)
    result = select.select_lessons(home, 'Synthetic task', project=tmp_path,
                                   literal_paths=['src/planned.py'], tier='all')
    assert bool(result['lessons']) is expected
    if expected:
        assert result['lessons'][0]['confidence'] == 'possible'
        assert 'task/context corroboration' in result['lessons'][0]['why']
    assert not ids(select.select_lessons(home, 'Synthetic task', project=tmp_path,
                                        literal_paths=['src/planned.py']))


@pytest.mark.parametrize('task,lexical,expected', [
    (.70, .16, True), (.69999, .9, False), (.70, .15999, False),
])
def test_missing_user_path_accepts_strong_task_corroboration(home, monkeypatch, task, lexical, expected):
    put(home, gates=['src/*.py'])
    measured_scores(monkeypatch, task, 1., lexical)
    assert not ids(select.select_lessons(home, 'Synthetic task'))
    result = select.select_lessons(home, 'Synthetic task', tier='all')
    assert bool(result['lessons']) is expected
    if expected:
        assert result['lessons'][0]['confidence'] == 'possible'
        assert 'path not supplied' in result['lessons'][0]['why']
        assert result['lessons'][0]['matched_paths'] == []
    assert not ids(select.select_lessons(home, 'Synthetic task', tier='all', literal_paths=['other.txt']))
