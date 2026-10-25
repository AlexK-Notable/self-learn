"""Both engines meet digest-era citations; synthetic transcripts and fake models."""
import json

import pytest

from self_learn import intents, miner, provenance, refs, telemetry, transcript_lines
from self_learn.mining import check, spine
from self_learn.records import Record, RecordError
from test_mining_engine import (  # fixtures and the established fake model seam
    PROJECT, backend, home, host, lesson, output, pending, put_record, root, run, session_rows, _sighting,
)


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    return path


def record(home, origin, quote='you never ran make check', rid='lrn-55550001'):
    rec = Record.create(type='behavior', scope='user', source='session', kind='anti-pattern',
                        trigger='About to claim checks pass', instruction='Run them first', record_id=rid,
                        evidence=[{'origin': origin, 'quote': quote}])
    path = home/'user/pending'/f'{rid}.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    rec.write(path)
    return path


@pytest.mark.parametrize('stored_line', [3, 4])  # LF positive controls run first
@pytest.mark.parametrize('backfill', [False, True])
def test_session_engine_nightly_cites_digest_era_moment(home, root, backend, tmp_path, stored_line, backfill):
    sid = 's1nightly-0000'
    rows = session_rows(sid, host(tmp_path))
    rows[0]['message']['content'][0]['text'] = 'set up\u2028the export script'
    path = write(root/PROJECT/f'{sid}.jsonl', rows[:4])
    cursors = miner._load_cursors()
    cursors[str(path)] = {'lines': 4, 'size': path.stat().st_size, 'line_format': 'newline-v1'}
    miner._save_cursors(cursors)
    assert miner._load_cursors()[str(path)]['lines'] == 4
    old = record(home, f'transcript:{sid}#L{stored_line}')
    before = old.read_bytes()
    write(path, rows)
    backend.answers[sid] = output(lessons=[lesson(evidence=[
        {'line': 3, 'quote': 'you never ran make check'},
        {'line': 6, 'quote': 'always run the checks before you say they pass'}])])
    result = run(home, **({'since': '2000-01-01'} if backfill else {}))
    assert len(backend.specs) == 1 and result.status == 'ok'
    assert 'skipped-known-origin' in [o['outcome'] for o in result.outcomes]
    assert len(pending(home)) == 1 and old.read_bytes() == before


def test_pending_sighting_follows_its_records_old_origin(home, root, backend, tmp_path):
    sid = 's1heldorigin-0000'
    rows = session_rows(sid, host(tmp_path))
    rows[0]['message']['content'][0]['text'] += '\u2028extra'
    write(root/PROJECT/f'{sid}.jsonl', rows)
    path = record(home, f'transcript:{sid}#L4')
    before = path.read_bytes()
    backend.answers[sid] = output(sightings=[_sighting(sid, 'lrn-55550001')])
    result = run(home)
    assert len(backend.specs) == 1
    assert [o['outcome'] for o in result.outcomes] == ['skipped-known-origin']
    assert result.folded == [] and path.read_bytes() == before


@pytest.mark.parametrize('tracked', [False, True])
def test_recurrence_seen_events_follow_old_origins(home, root, backend, tmp_path, tracked):
    sid, rid = 's1recurrenceold-0000', 'lrn-55550002'
    rows = session_rows(sid, host(tmp_path))
    rows[0]['message']['content'][0]['text'] += '\u2028extra'
    write(root/PROJECT/f'{sid}.jsonl', rows)
    put_record(home, rid, status='routed')
    telemetry.spool_event('recurrence-suspect', record=rid, origin=f'transcript:{sid}#L4')
    if tracked:
        telemetry.flush(home, push=False)
    events = telemetry.read_events(home) if tracked else telemetry.read_spooled(('recurrence-suspect',))
    assert any(e.get('record') == rid for e in events)
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    result = run(home)
    assert len(backend.specs) == 1
    assert [o['outcome'] for o in result.outcomes] == ['recurrence-already-known']
    assert result.recurrences == []


def test_new_events_mark_lf_origins_before_later_replay(home, root, backend, tmp_path):
    sid, rid = 's1recurrencenew-0000', 'lrn-55550003'
    rows = session_rows(sid, host(tmp_path))
    rows[0]['message']['content'][0]['text'] += '\u2028extra'
    write(root/PROJECT/f'{sid}.jsonl', rows)
    put_record(home, rid, status='routed')
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    assert run(home).recurrences == [rid]
    event = next(e for e in telemetry.read_events(home) if e.get('kind') == 'recurrence-suspect')
    assert event['line_format'] == 'newline-v1'
    assert miner._OriginIndex(home).event(dict(event, origin=f'transcript:{sid}#L2')) == f'transcript:{sid}#L3'
    # Even UUID-less events written now must never be translated again.
    event.pop('moment', None)
    assert miner._OriginIndex(home).event(event) == f'transcript:{sid}#L3'


@pytest.mark.parametrize('tracked', [False, True])
def test_digest_recurrence_uses_same_event_index(home, root, tmp_path, tracked):
    sid, rid = 's1digestevent-0000', 'lrn-55550004'
    rows = session_rows(sid, host(tmp_path))
    rows[0]['message']['content'][0]['text'] += '\u2028extra'
    write(root/PROJECT/f'{sid}.jsonl', rows)
    put_record(home, rid, status='routed')
    telemetry.spool_event('recurrence-suspect', record=rid, origin=f'transcript:{sid}#L4')
    if tracked:
        telemetry.flush(home, push=False)
    events = telemetry.read_events(home) if tracked else telemetry.read_spooled(('recurrence-suspect',))
    assert any(e.get('record') == rid for e in events)
    result = miner.MineResult(status='ok')
    with intents.ledger_write(home):
        miner._reconcile_and_land(home, {'candidates': [
            {'session': sid, 'line': 3, 'match': {'record': rid}}]}, result, 5)
    assert [o['outcome'] for o in result.outcomes] == ['recurrence-already-known']
    assert result.recurrences == []


def test_unavailable_new_sighting_is_marked_and_later_converges(home, root):
    origin = 'transcript:late#L2'
    assert miner._rejected_counter_bump('lrn-1', origin) == 1
    path = miner.miner_dir()/'rejected-sightings.json'
    assert json.loads(path.read_text())['lrn-1'] == ['newline-v1:' + origin]
    write(root/PROJECT/'late.jsonl', [
        {'uuid': 'first', 'type': 'user', 'message': {'content': 'a\u2028b'}},
        {'uuid': 'same', 'type': 'user', 'message': {'content': 'moment'}}])
    assert miner._rejected_counter_bump('lrn-1', origin) == 1
    assert json.loads(path.read_text())['lrn-1'] == ['uuid:same']


def test_sighting_uuid_collapses_a_fork_copy(home, root):
    rows = [{'uuid': 'shared', 'type': 'user', 'message': {'content': 'same moment'}}]
    write(root/PROJECT/'parent.jsonl', rows)
    write(root/PROJECT/'fork.jsonl', rows)
    assert miner._rejected_counter_bump('lrn-1', 'transcript:parent#L1') == 1
    assert miner._rejected_counter_bump('lrn-1', 'transcript:fork#L1') == 1
    assert json.loads((miner.miner_dir()/'rejected-sightings.json').read_text())['lrn-1'] == ['uuid:shared']


def test_unavailable_raw_sighting_keeps_exact_origin_dedupe(home, root):
    path = miner.miner_dir()/'rejected-sightings.json'
    origin = 'transcript:missing#L3'
    path.write_text(json.dumps({'lrn-1': [origin]}))
    assert json.loads(path.read_text())['lrn-1'] == [origin]
    assert miner._rejected_counter_bump('lrn-1', origin) == 1
    assert json.loads(path.read_text())['lrn-1'] == [origin]


@pytest.mark.parametrize('uuid', [None, 'sub'])
def test_subagent_old_key_suppresses_a_new_lf_moment(home, root, uuid):
    rows = [{'type': 'user', 'message': {'content': text}} for text in ('a\u2028b', 'old moment', 'new moment')]
    if uuid:
        for n, r in enumerate(rows):
            r['uuid'] = f'{uuid}-{n}'
    write(root/PROJECT/'sess/subagents/agent-x.jsonl', rows)
    origin = 'transcript:sess/subagents/agent-x.jsonl#L3'
    path = miner.miner_dir()/'rejected-sightings.json'
    path.write_text(json.dumps({'lrn-1': [origin]}))
    old = miner._follow_origin(origin, legacy=True)
    assert old is not None
    assert old.line == 2 and old.subagent_file == 'subagents/agent-x.jsonl'
    assert miner._rejected_counter_bump('lrn-1', origin) == 2
    if not uuid:
        assert json.loads(path.read_text())['lrn-1'] == [
            'newline-v1:transcript:sess/subagents/agent-x.jsonl#L2', 'newline-v1:' + origin]


def test_checker_itself_uses_fresh_numbering_for_distant_quote(home, root):
    rows = [{'type': 'user', 'message': {'content': 'a' + '\u2028'*50 + 'b'}},
            {'type': 'user', 'message': {'content': 'padding'}},
            {'type': 'user', 'message': {'content': 'target words'}}]
    rows += [{'type': 'user', 'message': {'content': 'unrelated'}} for _ in range(50)]
    path = write(root/PROJECT/'distant.jsonl', rows)
    checker = check._Checker(spine.build_spine(spine.read_session(path), 1, 53), [root], frozenset(), frozenset())
    assert checker.quoted({'line': 3, 'quote': 'target words'})[0]['verdict'] == 'exact'
    evidence, found = checker.quoted({'line': 53, 'quote': 'target words'})
    assert found.line == 3 and evidence['corrected_from'] == 53
    assert evidence['verdict'] == 'elsewhere_in_file'


@pytest.mark.parametrize('separator', ['\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'])
def test_index_only_resolves_affected_files_and_reuses_run_sends(home, root, monkeypatch, separator):
    target = {'type': 'user', 'uuid': 'target', 'message': {'content': 'target words'}}
    path = write(root/PROJECT/'affected.jsonl', [target, target, {'type': 'user'}])
    path.write_bytes(('{}' + separator + '{}\n' + json.dumps(target) + '\n{}\n').encode())
    clean = write(root/PROJECT/'clean.jsonl', [target])
    clean.write_bytes(clean.read_bytes().replace(b'\n', b'\r\n'))
    record(home, 'transcript:clean#L1', quote='target words')
    record(home, 'transcript:affected#L3', quote='target words', rid='lrn-55550002')
    sent = provenance.SentIndex()
    calls, reads = [], []
    resolve, stream = refs.resolve, transcript_lines.iter_file
    def resolved(*a, **kw):
        assert kw.get('sent') is sent
        calls.append(a[0])
        return resolve(*a, **kw)
    def streamed(p, **kw):
        reads.append(p)
        yield from stream(p, **kw)
    monkeypatch.setattr(refs, 'resolve', resolved)
    monkeypatch.setattr(refs, 'sent_index', lambda *a, **kw: pytest.fail('unexpected sends sweep'))
    monkeypatch.setattr(transcript_lines, 'iter_file', streamed)
    index = miner._OriginIndex(home, sent)
    assert miner._known_mining_origins(home, index=index) == {'transcript:clean#L1', 'transcript:affected#L2'}
    assert calls == ['affected']
    assert set(reads) == {path, clean}
    assert index.origin('transcript:clean#L1') == 'transcript:clean#L1'
    assert len(reads) == 2  # a drain reuses each file's classification


def test_corrupt_record_retains_its_raw_origin_independently(home, root):
    rows = [{'type': 'user', 'message': {'content': text}} for text in ('a\u2028b', 'target words', 'other')]
    write(root/PROJECT/'corrupt-control.jsonl', rows)
    origin = 'transcript:corrupt-control#L3'
    valid = record(home, origin, quote='target words')
    assert miner._known_mining_origins(home) == {'transcript:corrupt-control#L2'}
    broken = valid.with_name('lrn-55550002.md')
    broken.write_text('---\nnot: [valid\n---\norigin: "' + origin + '"\n')
    with pytest.raises(RecordError):
        Record.from_path(broken)
    assert miner._known_mining_origins(home) == {origin, 'transcript:corrupt-control#L2'}


@pytest.mark.parametrize('surface', ['session', 'digest-recurrence', 'digest-fire', 'legacy-fire'])
def test_all_event_writers_mark_new_line_counts(home, root, surface):
    rid, sid = 'lrn-55550009', 's1eventmarker-0000'
    put_record(home, rid, status='routed')
    result = miner.MineResult(status='ok')
    origin = f'transcript:{sid}#L3'
    with intents.ledger_write(home):
        if surface == 'session':
            st = miner._Landing(home, result, 5, set(), set())
            miner._write_event(st, 'recurrence-suspect', rid, origin, None)
        elif surface == 'legacy-fire':
            miner._raise_recurrence_suspect(result, set(), rid, origin, 'fire-suspected-violation')
        else:
            parsed = ({'candidates': [{'session': sid, 'line': 3, 'match': {'record': rid}}]}
                      if surface == 'digest-recurrence' else
                      {'fires': [{'record': rid, 'session': sid, 'line': 3, 'outcome': 'cannot-tell'}]})
            miner._reconcile_and_land(home, parsed, result, 5)
    events = [e for e in telemetry.read_spooled(('fire', 'recurrence-suspect')) if e.get('record') == rid]
    assert len(events) == 1 and events[0]['origin'] == origin
    assert events[0]['line_format'] == 'newline-v1'
