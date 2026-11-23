"""Stable tier prefixes and explicit evidence explanations (S-161 round 4)."""
import random

import pytest

from self_learn import select, verbs
from test_select import home, put, ids
from test_select_tiers import measured_scores


def rankings(monkeypatch, lexical, semantic, context=None):
    monkeypatch.setattr(select, '_lexical', lambda *a, **k: dict(lexical))
    monkeypatch.setattr(select, '_semantic', lambda home, texts, *a, **k: (
        select.SemanticScores({rid: score for rid, score in semantic.items() if rid in texts},
                              context or {}, 'gemini-embedding-2@3072/i1'), .70, 'synthetic'))


def test_review_flip_keeps_confident_prefix_and_scores(home, monkeypatch):
    # A, B, f1, f2, f3; default rankings are A,f1,B,f2 and f1,B,f2,f3,A.
    for n in range(1, 6):
        put(home, n)
    put(home, 6, scope='skill:synthetic')  # X inserts second/first respectively.
    a, b, f1, f2, f3, x = [f'lrn-{n:08x}' for n in range(1, 7)]
    rankings(monkeypatch, {a: .9, x: .8, f1: .7, b: .6, f2: .5},
             {x: .73, f1: .699, b: .698, f2: .697, f3: .696, a: .695},
             {a: .71, b: .71})
    default = select.select_lessons(home, 'Synthetic task', limit=10)['lessons']
    assert [hit['id'] for hit in default] == [b, a]
    all_hits = select.select_lessons(home, 'Synthetic task', tier='all', limit=10)['lessons']
    assert any(hit['id'] == x and hit['confidence'] == 'possible' for hit in all_hits)
    assert all_hits[:len(default)] == default
    assert ids(select.select_lessons(home, 'Synthetic task', limit=1)) == [b]
    assert ids(select.select_lessons(home, 'Synthetic task', tier='all', limit=1)) == [b]


@pytest.mark.parametrize('seed', range(4))
@pytest.mark.parametrize('mode', ['current', 'partial', 'lexical'])
def test_confident_prefix_across_synthetic_corpora(home, monkeypatch, seed, mode):
    rng = random.Random(seed)
    for n in range(1, 12):
        put(home, n, scope='skill:synthetic' if n in (8, 9) else 'user',
            gates=['src/*.py'] if n in (10, 11) else None,
            text=f'Synthetic corpus {seed} subject {n} needs immutable archive stamps.', knowledge=True)
    names = [f'lrn-{n:08x}' for n in range(1, 12)]
    lexical = {rid: rng.uniform(.01, .95) for rid in names}
    semantic = {rid: (rng.uniform(.76, .99) if i < 4 or i >= 7 else rng.uniform(.60, .74))
                for i, rid in enumerate(names)}
    if mode == 'partial':
        semantic.pop(names[1]); semantic.pop(names[4])
    rankings(monkeypatch, lexical, {} if mode == 'lexical' else semantic)
    kwargs = {'exclude': [names[0]]} if seed % 2 else {}
    all_unlimited = select.select_lessons(home, 'Synthetic task', tier='all', limit=20, **kwargs)['lessons']
    if mode != 'lexical':
        assert any(hit['confidence'] == 'possible' for hit in all_unlimited)
    for limit in (0, 1, 2, 4, 8, 20):
        default = select.select_lessons(home, 'Synthetic task', limit=limit, **kwargs)['lessons']
        expanded = select.select_lessons(home, 'Synthetic task', tier='all', limit=limit, **kwargs)['lessons']
        assert len(expanded) <= limit
        assert expanded[:len(default)] == default
        assert all(hit['confidence'] == 'possible' for hit in expanded[len(default):])


@pytest.mark.parametrize('task,context,lexical', [
    (.8, None, 0.), (.70, None, 0.), (.68, .70, .5),
    (.65, None, .5), (.60, .675, 0.), (None, None, .5),
])
def test_why_distinguishes_vector_from_base_semantic_floor(home, tmp_path, monkeypatch, task, context, lexical):
    put(home, scope='project', project=tmp_path, gates=['src/*.py'])
    measured_scores(monkeypatch, task, context, lexical)
    if task is None:
        monkeypatch.setattr(select, '_semantic', lambda *a, **k: ({}, None, 'no current vectors'))
    result = select.select_lessons(home, 'Synthetic task', project=tmp_path,
                                   literal_paths=['src/planned.py'], tier='all')
    assert ids(result) == ['lrn-00000001']
    why = result['lessons'][0]['why']
    assert ('current vector' in why) is (task is not None)
    assert ('semantic floor' in why) is (task is not None and task >= .70)
    assert ('lexical' in why) is (lexical >= .16)
    assert 'semantic' not in why
    assert 'project scope' in why and 'path gate' in why


def test_user_gate_anchor_uses_routing_constant(home, tmp_path, monkeypatch):
    user = tmp_path / 'synthetic-user'
    user.mkdir()
    monkeypatch.setattr(verbs, 'DEFAULT_USER_CLAUDE_MD', user / '.claude/CLAUDE.md')
    put(home, gates=['src/*.py'])
    assert ids(select.select_lessons(home, 'Docker container restart',
        literal_paths=[str(user / 'src/planned.py')], provider=None)) == ['lrn-00000001']
