"""R5-R6: mandatory review commits and optional native evidence retention."""
import json
from pathlib import Path

import pytest
import test_skill_scripts as original
import test_script_fix_round2 as round2
from self_learn import script_proof, session_copies, skill_scripts as scripts
from self_learn.invocation_sdk import backend as sdk
from support import git

env = original.env
NOTICE = 'review transcript no longer present; verified from the ledger review commit'


def _native(path, session, verdict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'type': 'assistant', 'sessionId': session,
        'message': {'model': scripts.MODEL, 'content': [{'type': 'text', 'text': json.dumps(verdict)}]}}) + '\n')


def _approve(env, monkeypatch):
    original.fake(monkeypatch)
    fake = sdk.SdkBackend.text_session
    path = script_proof.native_path(env.home, 'fake-session')
    def run(self, spec):
        result = fake(self, spec)
        _native(path, 'fake-session', json.loads(result.stdout))
        return result
    monkeypatch.setattr(sdk.SdkBackend, 'text_session', run)
    row = scripts.review(env.home, original.held(env)['id'], note='native evidence test')
    assert row['state'] == 'active'
    assert row['review']['corroboration']['kind'] == 'native'
    assert script_proof.verify(env.home, row) is None
    log = git(env.home, 'log', '--format=%B').stdout
    assert f"self-learn: script review {row['id']}: approve" in log
    assert f"Script-Version: {row['version']}" in log
    assert 'Script-Session: fake-session' in log
    return row, path


@pytest.mark.parametrize('missing', [True, False], ids=['deleted', 'unreadable'])
def test_native_loss_keeps_active_and_notices_once(env, monkeypatch, missing):
    row, native = _approve(env, monkeypatch)
    if missing:
        native.unlink()
    else:
        read = Path.read_bytes
        def unreadable(path):
            if path == native:
                raise PermissionError('unreadable native transcript')
            return read(path)
        monkeypatch.setattr(Path, 'read_bytes', unreadable)
    assert scripts.listed(env.home)[0]['approval_status'] == 'verified'
    assert NOTICE in ' '.join(scripts.audit(env.home))
    assert scripts.get(env.home, row['id'])['state'] == 'active'
    target = env.skill_dir() / 'scripts/count'
    assert target.read_text() == original.GOOD
    assert target.stat().st_mode & 0o111
    assert 'scripts/count' in env.skill_md().read_text()
    assert NOTICE not in ' '.join(scripts.audit(env.home))
    assert script_proof.verify(env.home, scripts.get(env.home, row['id'])) is None


def test_native_only_forgery_requires_review_commit(env):
    row = round2._forge(env, original.GOOD)
    review = row['review']
    native = script_proof.native_path(env.home, review['session'])
    verdict = {k: review[k] for k in ('verdict', 'reasons', 'changes', 'version')}
    _native(native, review['session'], verdict)
    review['corroboration'] = {'kind': 'native', 'path': str(native),
        'sha256': script_proof.native_digest(native, review['session'], row['version'], verdict)}
    (env.home / scripts.INDEX).write_text(json.dumps({'version': 1, 'scripts': [row]}))
    assert 'matching self-learn review commit' in script_proof.verify(env.home, row)
    assert scripts.listed(env.home)[0]['state'] == 'unverified'
    scripts.activate(env.home, row['id'])
    scripts.audit(env.home)
    assert not (env.skill_dir() / 'scripts/forged').exists()


@pytest.mark.parametrize('change', ['model', 'tool', 'verdict', 'version', 'digest', 'malformed'])
def test_present_contradicting_native_is_unverified(env, monkeypatch, change):
    row, native = _approve(env, monkeypatch)
    data = json.loads(native.read_text())
    message = data['message']
    if change == 'model':
        message['model'] = 'other-model'
    elif change == 'tool':
        message['content'].append({'type': 'tool_use', 'name': 'Read'})
    elif change in {'verdict', 'version'}:
        verdict = json.loads(message['content'][0]['text'])
        verdict[change] = 'reject' if change == 'verdict' else 'other-version'
        verdict['changes'] = ['change required']
        message['content'][0]['text'] = json.dumps(verdict)
    # Reformatting the assistant line alone changes its digest.
    native.write_text('{broken' if change == 'malformed' else json.dumps(data, separators=(',', ':')) + '\n')
    assert script_proof.verify(env.home, row) is not None
    assert scripts.listed(env.home)[0]['state'] == 'unverified'
    assert 'deactivated' in ' '.join(scripts.audit(env.home))
    assert not (env.skill_dir() / 'scripts/count').exists()


def test_native_lookup_never_reads_other_project(env, monkeypatch):
    original.fake(monkeypatch)
    fake = sdk.SdkBackend.text_session
    native = session_copies.claude_projects_dir() / 'wrong-project' / 'fake-session.jsonl'
    def run(self, spec):
        result = fake(self, spec)
        _native(native, 'fake-session', json.loads(result.stdout))
        return result
    monkeypatch.setattr(sdk.SdkBackend, 'text_session', run)
    read = Path.read_bytes
    def guarded(path):
        assert path != native, 'must not read transcript planted in another project'
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded)
    row = scripts.review(env.home, original.held(env)['id'], note='expected location only')
    assert row['state'] == 'active'
    assert row['review']['corroboration'] == {'kind': 'git'}
