"""S-160 blind-review regressions. All sessions/files are fake or scratch."""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
import test_skill_scripts as original
import test_skill_write as sk1
import test_overseer_skill_build as build
from self_learn import cli, gitops, intents, maintenance, settings, skill_scripts as scripts, skill_writer, verbs
from self_learn.invocation_sdk import backend as sdk
from self_learn.overseer import skills, skill_work_requests as work
from self_learn.script_screen import screen
from support import git

env = original.env
GOOD = original.GOOD
PROBES = json.loads((Path(__file__).parent / 'data/script_screen_probes.json').read_text())


@pytest.mark.parametrize('name', list(PROBES))
def test_reviewer_screen_probes(name):
    checked = screen(PROBES[name])
    assert checked.ok == name.endswith('allowed_report'), (name, checked.rules)
    if not checked.ok:
        assert checked.rules and all(':' in rule for rule in checked.rules)


@pytest.mark.parametrize('code', [
    'import os\nprint(os.getenv("X"))',
    'from os import environb\nprint(environb)',
    'import argparse\nf = argparse.FileType\nf("w")("existing")',
    'import os.path\np = os.path\nprint(p.expanduser("~"))',
    'import os\n[m] = [os]\nprint(m.getcwd())',
    'import os\ndef f(m=os): return m.getcwd()\nprint(f())',
    'import os\ndef f(m=os.path): return m.abspath(".")\nprint(f())',
    'import sys\nlist(map(open, [sys.argv[1]], ["w"]))',
    'import sys\nfrom functools import partial\nf = partial(open, mode="w")\nlist(map(f, [sys.argv[1]]))',
    'import sys\nfrom pathlib import Path\np = Path(sys.argv[1])\nlist(map(p.open, ["w"]))',
    'import argparse\nprint("{0.__init__.__globals__[_os].environ}".format(argparse.ArgumentParser))',
    'import sys, argparse\nprint(sys.argv[1].format(argparse.ArgumentParser))',
    'from pathlib import Path\nprint(Path("/proc/self/environ").read_text())',
    'from pathlib import Path\nprint(Path(".netrc").read_text())',
])
def test_additional_member_indirection(code):
    assert not screen(original.PY + code + '\n').ok


@pytest.mark.parametrize('name', ['PATH', 'IFS', 'BASH_ENV', 'LD_PRELOAD'])
def test_shell_control_variables_refused(name):
    assert not screen(original.SH + name + '="$1"\ncat "$2"\n').ok


def active(env, monkeypatch, name='count'):
    original.fake(monkeypatch)
    row = scripts.review(env.home, original.held(env, name=name)['id'], note='test')
    assert row['state'] == 'active', row
    return row


@pytest.mark.parametrize('route', ['audit', 'cli', 'overseer'])
def test_approved_activation_retries_without_spending(env, monkeypatch, route, capsys):
    calls = original.fake(monkeypatch)
    env.skill_md().write_text(env.skill_md().read_text() + '\nUncommitted prose.\n')
    row = scripts.review(env.home, original.held(env)['id'], note='test')
    assert row['state'] == 'approved' and row['activation_error']
    assert cli.main(['skill', 'script', 'list']) == 0
    assert 'activation_error' in capsys.readouterr().out
    git(env.root, 'add', str(env.skill_md()))
    git(env.root, 'commit', '-m', 'user commits prose')
    if route == 'cli':
        assert cli.main(['skill', 'script', 'activate', row['id']]) == 0
    elif route == 'overseer':
        from self_learn.overseer import run
        monkeypatch.setattr(run, '_run', lambda *a, **k: run.RunResult('test', 0, 'test', 0, (), ()))
        run.run(env.home, no_push=True)
    else:
        scripts.audit(env.home)
    assert scripts.get(env.home, row['id'])['state'] == 'active'
    assert len(calls) == 1


def test_new_draft_preserves_active_until_approved_swap(env, monkeypatch):
    old = active(env, monkeypatch)
    target = env.skill_dir() / 'scripts/count'
    new = original.held(env, text=GOOD + 'print("next")\n')
    assert scripts.get(env.home, old['id'])['state'] == 'active'
    assert target.read_text() == GOOD
    assert scripts.review(env.home, new['id'], note='upgrade')['state'] == 'active'
    assert scripts.get(env.home, old['id'])['state'] == 'drafted'
    assert target.read_text() == GOOD + 'print("next")\n'
    assert scripts.audit(env.home) == []
    rejected = original.held(env, text=GOOD + 'print("rejected")\n')
    original.fake(monkeypatch, verdict='reject')
    scripts.review(env.home, rejected['id'], note='reject')
    assert scripts.get(env.home, new['id'])['state'] == 'active'


@pytest.mark.parametrize('change', ['folder-link', 'skill-link', 'mode', 'restored', 'unreadable', 'git-failure', 'corrupt-index', 'unreadable-index'])
def test_integrity_contains_damage_and_keeps_other_work(env, monkeypatch, change):
    row = active(env, monkeypatch)
    folder = env.skill_dir()
    target = folder / 'scripts/count'
    if change in {'folder-link', 'skill-link'}:
        moved = env.tmp / 'moved-original'
        swapped = folder / 'scripts' if change == 'folder-link' else folder
        swapped.rename(moved)
        swapped.symlink_to(moved, target_is_directory=True)
    elif change == 'mode':
        target.chmod(0o4777)
    elif change == 'restored':
        raw, md = target.read_bytes(), env.skill_md().read_bytes()
        scripts.deactivate(env.home, row['id'], note='test')
        target.write_bytes(raw); target.chmod(0o755); env.skill_md().write_bytes(md)
    elif change in {'corrupt-index', 'unreadable-index'}:
        (env.home / scripts.INDEX).write_text('{broken')
        assert 'index unreadable' in ' '.join(scripts.review_pending(env.home, 'run-test'))
        if change == 'unreadable-index':
            real_read = Path.read_bytes
            original_inode = (env.home / scripts.INDEX).stat().st_ino
            def unreadable_index(path):
                if path.exists() and path.stat().st_ino == original_inode: raise PermissionError('unreadable index')
                return real_read(path)
            monkeypatch.setattr(Path, 'read_bytes', unreadable_index)
    else:
        target.write_text('unapproved hand edit')
        if change == 'git-failure':
            real = gitops.commit
            def fail(root, *a, **kw):
                if root == env.root: raise gitops.GitOpsError('simulated host failure')
                return real(root, *a, **kw)
            monkeypatch.setattr(gitops, 'commit', fail)
        else:
            real_read = Path.read_bytes
            def unreadable(path):
                if path == target: raise PermissionError('simulated read failure')
                return real_read(path)
            monkeypatch.setattr(Path, 'read_bytes', unreadable)
    notices = scripts.audit(env.home)
    assert notices
    if change in {'corrupt-index', 'unreadable-index'}:
        assert target.read_text() == GOOD
        assert scripts.get(env.home, row['id'])['state'] == 'active'
    else:
        assert not target.exists() and not target.is_symlink()
        assert not any(r['state'] == 'active' for r in scripts.rows(env.home))
    # A normal compile still returns; no global crash after a malformed index.
    verbs.recompile(env.home, no_push=True)
    if change in {'folder-link', 'skill-link'}:
        assert moved.exists()
    elif change not in {'unreadable', 'corrupt-index', 'unreadable-index'}:
        assert any(Path(r['quarantine']).exists() for r in scripts.rows(env.home) if r.get('quarantine'))


def test_corrupt_index_does_not_block_unrelated_retirement(env):
    (env.home / scripts.INDEX).write_text('{broken')
    result = skill_writer.retire(env.home, sk1.NAME, case=None, by='human', no_push=True)
    assert result.ok, result


@pytest.mark.parametrize('damage', ['missing', 'changed', 'forged', 'wrong-version'])
def test_transcript_required_for_activation_audit_and_listing(env, monkeypatch, damage):
    row = active(env, monkeypatch)
    transcript = env.home / row['review']['transcript']
    if damage == 'missing':
        transcript.unlink()
    elif damage == 'changed':
        transcript.write_text(transcript.read_text() + '{}\n')
    else:
        records = scripts.rows(env.home)
        if damage == 'forged': records[0]['review']['session'] = 'made-up'
        else: records[0]['review']['version'] = '0' * 64
        (env.home / scripts.INDEX).write_text(json.dumps({'version': 1, 'scripts': records}))
    assert scripts.listed(env.home)[0]['state'] == 'unverified'
    assert 'unverified' in ' '.join(scripts.audit(env.home, enforce=False))
    scripts.audit(env.home)
    assert not (env.skill_dir() / 'scripts/count').exists()


def test_tool_use_rejected_from_real_outcome_field(env, monkeypatch):
    original.fake(monkeypatch)
    real = sdk.SdkBackend.text_session
    def with_tool(self, spec):
        return replace(real(self, spec), tool_events=({'type': 'tool_use', 'name': 'Bash'},))
    monkeypatch.setattr(sdk.SdkBackend, 'text_session', with_tool)
    row = scripts.review(env.home, original.held(env)['id'], note='test')
    assert row['review']['verdict'] == 'no review' and row['state'] == 'drafted'


def test_fenced_verdict_is_accepted(env, monkeypatch):
    original.fake(monkeypatch)
    real = sdk.SdkBackend.text_session
    def fenced(self, spec):
        outcome = real(self, spec)
        text = '```json\n' + outcome.stdout + '\n```'
        messages = tuple({**m, 'text': text} if m['type'] == 'assistant' else m for m in outcome.review_messages)
        return replace(outcome, stdout=text, review_messages=messages)
    monkeypatch.setattr(sdk.SdkBackend, 'text_session', fenced)
    assert scripts.review(env.home, original.held(env)['id'], note='test')['state'] == 'active'


def test_doctor_read_only_and_nightly_enforcement(env, monkeypatch, capsys):
    row = active(env, monkeypatch)
    target = env.skill_dir() / 'scripts/count'
    target.write_text('hand edit')
    before = env.head(env.home), env.head(env.root), target.read_bytes(), (env.home / scripts.INDEX).read_bytes()
    cli.main(['doctor', 'settings'])
    assert 'FAIL script-integrity' in capsys.readouterr().out
    assert before == (env.head(env.home), env.head(env.root), target.read_bytes(), (env.home / scripts.INDEX).read_bytes())
    from self_learn import selfcheck
    monkeypatch.setattr(selfcheck, 'unrecorded_targets', lambda _: {})
    monkeypatch.setattr(verbs, 'stale_warn_hooks', lambda _: ([], {}))
    monkeypatch.setattr(verbs, 'pending_warn_hook_placements', lambda _: ([], {}))
    maintenance.run(env.home, env.tmp / 'maintenance-cache')
    assert scripts.get(env.home, row['id'])['state'] == 'drafted'
    assert not target.exists()


@pytest.mark.parametrize('key', ['scripts.reviews_per_day', 'overseer.script_reviews_per_run'])
def test_caps_person_or_grant_only_and_no_env_raise(env, monkeypatch, key):
    entry = settings.by_name(key)
    assert entry.tier == 'C' and entry.env_var is None and not entry.override_channel
    legacy = 'SELF_LEARN_SCRIPT_REVIEWS_PER_DAY' if key.startswith('scripts.') else 'SELF_LEARN_OVERSEER_SCRIPT_REVIEWS_PER_RUN'
    monkeypatch.setenv(legacy, '999')
    # Set only in this isolated process, never export an override to a test command.
    monkeypatch.setenv(settings._override_env_var(key), '999')
    assert settings.resolve_setting(env.home, entry)[0] == entry.default
    monkeypatch.delenv(settings._override_env_var(key))
    monkeypatch.delenv('CODEX_THREAD_ID', raising=False)
    monkeypatch.delenv('CLAUDECODE', raising=False)
    settings.config_set(env.home, key, '2')
    monkeypatch.setenv('CODEX_THREAD_ID', 'synthetic')
    with pytest.raises(settings.AgentSettingRefusal): settings.config_set(env.home, key, '20')
    import test_grants
    from types import SimpleNamespace
    monkeypatch.delenv("CODEX_THREAD_ID")
    test_grants._granted(SimpleNamespace(ledger=env.home), env.tmp)
    monkeypatch.setenv("CODEX_THREAD_ID", "synthetic")
    assert cli.main(["config", "set", key, "3", "--note", "test under standing grant"]) == 0
    assert settings.resolve_setting(env.home, entry)[0] == 3


def test_deactivation_preserves_uncommitted_prose_and_damaged_staging(env, monkeypatch):
    row = active(env, monkeypatch)
    md = env.skill_md()
    marker_like = '- `scripts/count`: Example outside the managed block.'
    md.write_text(marker_like + '\n' + md.read_text() + '\nUser uncommitted prose.\n')
    md.write_text(md.read_text().replace(scripts.END, '').replace(row['usage'], 'Changed managed usage.'))
    assert skill_writer.draft_view(skill_writer.deployed_files(env.home, sk1.NAME))
    assert skill_writer.deployed_authored_sha256(env.home, sk1.NAME)
    scripts.audit(env.home)
    assert marker_like in md.read_text() and 'User uncommitted prose.' in md.read_text()
    assert 'Changed managed usage.' not in md.read_text()
    committed = git(env.root, 'show', 'HEAD:' + str(md.relative_to(env.root))).stdout
    assert marker_like not in committed and 'User uncommitted prose.' not in committed
    assert scripts.BEGIN not in committed
    assert scripts.get(env.home, row['id'])['state'] == 'drafted'


def test_creation_collision_never_quarantines_newcomer(env, monkeypatch):
    original.fake(monkeypatch)
    real = scripts._save
    target = env.skill_dir() / 'scripts/count'
    def collision(home, records, subject, extra=(), **kwargs):
        real(home, records, subject, extra, **kwargs)
        if subject.startswith('script activation pending'):
            target.parent.mkdir(exist_ok=True)
            target.write_text('unrelated newcomer')
    monkeypatch.setattr(scripts, '_save', collision)
    row = scripts.review(env.home, original.held(env)['id'], note='test')
    assert row['state'] == 'approved'
    scripts.audit(env.home)
    assert target.read_text() == 'unrelated newcomer'
    assert not scripts.get(env.home, row['id']).get('quarantine')


@pytest.mark.parametrize('usage', ['Counts arguments\nwrapped over two lines.\n', '<!-- forbidden -->', None, 'unreadable', 'holding-fails'])
def test_usage_draft_fake_overseer_run_and_resume(env, monkeypatch, usage):
    real_setting = settings.resolve_setting
    monkeypatch.setattr(settings, 'resolve_setting', lambda home, entry: (True, 'test') if entry.name == 'overseer.enabled' else real_setting(home, entry))
    original.fake(monkeypatch)
    build._lesson(env, build.RID)
    build._lesson(env, build.RID2)
    def phase(stage):
        build._rewrite_b('Prose rewrite applied.')(stage)
        folder = stage / 'skills' / sk1.NAME / 'scripts'
        folder.mkdir()
        (folder / 'count').write_text(GOOD)
        if usage is not None: (folder / 'count.usage.md').write_text(usage)
        build._build_b([build.RID2], name='later-skill')(stage)
    build._phases(monkeypatch, phase)
    if usage == 'holding-fails':
        def failed_hold(*a, **kw): raise ValueError('holding refused')
        monkeypatch.setattr(scripts, 'draft', failed_hold)
    if usage == 'unreadable':
        real_read = Path.read_bytes
        def failed_usage(path):
            if path.name == 'count.usage.md': raise PermissionError('unreadable usage')
            return real_read(path)
        monkeypatch.setattr(Path, 'read_bytes', failed_usage)
    real_write = skill_writer.write
    deferred = []
    def pause_later(home, name, files, **kw):
        if name == 'later-skill' and not deferred:
            deferred.append(name)
            return build._git_refusal(name)
        return real_write(home, name, files, **kw)
    monkeypatch.setattr(skill_writer, 'write', pause_later)
    first = build._run(env)
    first_report = build._report(first)
    assert 'Prose rewrite applied.' in env.skill_md().read_text()
    assert deferred and build.overseer_run._unfinished_manifest(env.home) is not None
    second = build._run(env)
    assert build.overseer_run._unfinished_manifest(env.home) is None
    assert build._status(env, build.RID2) == 'routed'
    if usage and '<!--' not in usage and usage not in {'unreadable', 'holding-fails'}:
        assert scripts.rows(env.home)[0]['usage'] == 'Counts arguments wrapped over two lines.'
    else:
        assert 'dropped' in build._section(first_report, 'Refused / could not do')
        assert 'dropped' in build._section(build._report(second), 'Refused / could not do')


def test_change_request_closes_for_any_applied_write_to_same_skill(env, monkeypatch):
    from self_learn import skill_requests
    request = skill_requests.file_request(env.home, 'change', sk1.NAME, lessons=[], note='missing step', by='agent')
    answer = {**request, 'answer': 'changed', 'reason': 'step added', 'case': 'dropped.yaml'}
    manifest = {'run_id': 'test-run', 'skills': {'requests': [answer]}, 'cases': {
        'one': {'case_name': 'other.yaml', 'skill': {'action': 'write', 'state': 'applied', 'name': sk1.NAME}},
        'two': {'case_name': 'dropped.yaml', 'skill': {'action': 'write', 'state': 'refused', 'name': sk1.NAME}}}}
    work.settle(env.home, manifest, complete=True)
    assert skill_requests.requests(env.home)[0]['state'] == 'closed'
    assert skill_requests.requests(env.home)[0]['answer'] == 'changed'


def test_native_sdk_transcript_marks_tool_use(env, monkeypatch):
    import asyncio
    from claude_agent_sdk import AssistantMessage, SystemMessage, TextBlock, ToolUseBlock, ClaudeAgentOptions
    from self_learn.invocation_sdk.events import EventLog
    from self_learn import script_proof
    verdict = json.dumps({"verdict": "approve", "reasons": ["claimed"], "changes": [], "version": "a" * 64})
    messages = [SystemMessage(subtype="init", data={"model": scripts.MODEL, "session_id": "native"}),
        AssistantMessage(content=[TextBlock(text=verdict), ToolUseBlock(id="use", name="Bash", input={"command": "unused"})], model=scripts.MODEL)]
    class Client:
        async def connect(self): pass
        async def query(self, prompt): pass
        async def receive_response(self):
            for message in messages: yield message
    monkeypatch.setattr(sdk.lifecycle, "child_pid_of", lambda _: None)
    spec = sdk.TextOnlySpec(surface="analyst", prompt="review", cwd=env.home, timeout=2,
        containment=original.Containment("", "", (), (), True, "default"), log=lambda _: None, model=scripts.MODEL)
    events, observed = EventLog(), []
    asyncio.run(sdk._run_session(spec, Client(), ClaudeAgentOptions(), events, lambda _: None, None, [], observed))
    assert events.tool_events and observed[-1]["tool_use"] is True
    with pytest.raises(ValueError, match="tool"):
        script_proof.inspect(observed, session="native", version="a" * 64)


def test_corrupt_index_does_not_adopt_a_foreign_collision(env, monkeypatch):
    original.held(env)
    target = env.skill_dir() / 'scripts/count'
    target.parent.mkdir(); target.write_text('user-owned file')
    (env.home / scripts.INDEX).write_text('{broken')
    assert scripts.audit(env.home)
    assert target.read_text() == 'user-owned file'
    assert not scripts.rows(env.home)[0].get('owns_target')


@pytest.mark.parametrize('field,value', [('run', 'different-run'), ('at', '1900-01-01'), ('cost_usd', 0), ('proof', {})])
def test_verdict_cannot_overwrite_session_metadata(env, monkeypatch, field, value):
    original.fake(monkeypatch)
    real = sdk.SdkBackend.text_session
    def injected(self, spec):
        outcome = real(self, spec)
        result = json.loads(outcome.stdout)
        result[field] = value
        text = json.dumps(result)
        messages = [dict(m) for m in outcome.review_messages]
        messages[-1]['text'] = text
        return replace(outcome, stdout=text, review_messages=tuple(messages))
    monkeypatch.setattr(sdk.SdkBackend, 'text_session', injected)
    row = scripts.review(env.home, original.held(env)['id'], note='test')
    assert row['state'] == 'drafted' and row['review']['verdict'] == 'no review'
    assert row['review']['run'] is None and row['review']['cost_usd'] == 0.12
    assert not row['review']['at'].startswith('1900')


def test_shell_control_variables_printf_refused():
    # Verify the installed Bash's side effect using an inert local variable.
    # Never execute the candidate that assigns PATH.
    import subprocess
    result = subprocess.run(['/usr/bin/bash', '--noprofile', '--norc', '-c',
        'x=original; printf %n x; printf "%s" "$x"'],
        env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, check=True)
    assert result.stdout == '0'
    assert not screen(original.SH + 'printf %n PATH\ncat "$1"\n').ok
    assert screen(original.SH + 'printf "%s" "$1"\n').ok


@pytest.mark.parametrize('code', [
    'print("Count: {:04d}".format(3))',
    'print("{name}".format_map({"name": "report"}))',
])
def test_literal_format_reports_allowed(code):
    # A benign control demonstrates why format fields need their own check.
    assert "{0.__class__.__name__}".format(1) == "int"
    assert screen(original.PY + code + '\n').ok


@pytest.mark.parametrize('code', [
    'import os\nprint(os.getcwd())',
    'import os, sys\nprint([entry.name for entry in os.scandir(sys.argv[1])])',
])
def test_additional_read_reports_allowed(code):
    assert screen(original.PY + code + '\n').ok
