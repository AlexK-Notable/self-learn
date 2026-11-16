"""S-159 reference pack contract; HTTP and model boundaries are fakes only."""
import json
from datetime import date
from pathlib import Path

import pytest
from ruamel.yaml import YAML

import test_skill_write as sk1
import test_skill_registration as sr
import test_overseer_skill_build as ob
from self_learn import cli, skill_reference as ref, skill_registry, skill_writer
from self_learn.skill_scaffold import check_skill, skill_md_seed, SkillScaffoldError, _read_frontmatter
from self_learn.overseer import skills, formats
from support import commit_all


@pytest.fixture
def env(tmp_path, monkeypatch):
    return sk1.Env(tmp_path, monkeypatch)


def check(files, **kwargs):
    return check_skill(files, loaded_names=(), vetoed_names=(), **kwargs)


def test_pack_manifest_and_show(capsys):
    doc = YAML(typ="safe").load((ref.PACK_DIR / "sources.yaml").read_text())
    assert doc['version'] == ref.VERSION and doc['date_read'] == ref.READ_DATE
    assert doc['normalization'] == ref.NORMALIZATION
    assert len(ref.sources()) == 5
    assert all(len(s['sha256']) == 64 and s['url'].startswith('https://') for s in ref.sources())
    assert cli.main(['skill', 'reference', 'show']) == 0
    text = capsys.readouterr().out
    assert ref.VERSION in text and 'R07' in text and 'G06' in text
    assert cli.main(['skill', 'reference', 'show', '--path']) == 0
    assert Path(capsys.readouterr().out.strip()).read_text() == (ref.PACK_DIR/'PACK.md').read_text()


def test_normalization_preserves_content():
    assert ref.digest('A\r\n cafe\u0301  B') == ref.digest('A café\tB')
    assert ref.digest('A B') != ref.digest('A C')
    assert ref.digest('read 2026-11-14') != ref.digest('read 2026-11-15')


@pytest.mark.parametrize('name,rule', [('bad-', 'name-hyphens'), ('bad--name','name-hyphens'), ('synced','name-synced')])
def test_new_name_refusals(env, name, rule):
    files = sk1.draft(name=name)
    assert rule in check(files).problem_rules
    before = env.snapshot()
    result = env.write(files, name=name)
    assert not result.ok and any(rule in p for p in result.problems)
    assert env.snapshot() == before
    with pytest.raises(SkillScaffoldError, match=rule):
        skill_md_seed(name, 'Use when checking names.')


@pytest.mark.parametrize('value', ['x'*501, 12])
def test_compatibility_refusal_and_carried_note(value):
    files=sk1.draft()
    files['SKILL.md']=files['SKILL.md'].replace('---\n\n', 'compatibility: '+json.dumps(value)+'\n---\n\n')
    assert 'compatibility-limit' in check(files).problem_rules
    carried={'compatibility':value}
    result=check(files, carried_frontmatter=carried)
    assert result.ok and 'compatibility-limit' in result.note_rules
    assert 'existing user setting retained' in str(result.notes)
    good=sk1.draft(); good['SKILL.md']=good['SKILL.md'].replace('---\n\n', 'compatibility: '+json.dumps('x'*500)+'\n---\n\n')
    assert check(good).ok


def test_guidance_never_refuses_and_write_reports_it(env):
    files=sk1.draft(description='You process < 3 documents.', extra='detail '*3000, ref_text='line\n'*101, metadata={'nested':{'key':'value'}})
    result=check(files)
    expected={'guidance-description-trigger','guidance-description-person','guidance-angle-brackets','guidance-body-tokens','guidance-reference-contents','metadata-string-values'}
    assert result.ok and expected <= set(result.note_rules)
    written=env.write(files)
    assert written.ok, written.problems
    assert all(any(rule in n for n in written.notes) for rule in expected)


def test_registered_preserves_name_and_settings(env, capsys):
    name='claude--helper-'
    files=sk1.draft(name=name)
    files['SKILL.md']=files['SKILL.md'].replace('---\n\n', 'compatibility: '+json.dumps('x '*250+'x')+'\nallowed-tools: Bash\n---\n\n')
    for rel,text in files.items():
        path=env.skill_dir(name)/rel; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text)
    commit_all(env.root,'seed existing user settings')
    from self_learn.skill_registration import register
    assert register(env.home,name,note='Keep user intent',by='human')['state']=='registered'
    result=env.write(files,name=name)
    assert result.ok, result.problems
    assert any('name-hyphens' in n for n in result.notes)
    assert any('compatibility-limit' in n for n in result.notes)
    assert cli.main(['skill','reference','check',str(env.skill_dir(name))]) == 0
    output=capsys.readouterr().out
    assert 'existing user setting retained' in output and 'source:' in output
    changed=dict(files); changed['SKILL.md']=changed['SKILL.md'].replace('allowed-tools: Bash','allowed-tools: Read')
    assert not env.write(changed,name=name).ok


@pytest.mark.parametrize('registered',[False,True])
def test_stamps_rows_list_and_repeat(env, registered, capsys):
    if registered:
        sr.seed(env); sr.register(env)
    result=env.write(sk1.draft())
    assert result.ok, result.problems
    stamp=_read_frontmatter(env.skill_md().read_text()).mapping['metadata']['self-learn']
    assert stamp['reference_pack']==ref.VERSION
    assert ('registered_by' if registered else 'authored_by') in stamp
    row=skill_registry.load(env.home).row(sk1.NAME)
    assert row['last_write']['reference_pack']==ref.VERSION
    assert cli.main(['skill','list']) == 0
    assert ref.VERSION in capsys.readouterr().out
    repeat=env.write(sk1.draft())
    assert repeat.ok and not repeat.changed


def test_cli_check_path_name_and_write_version(env,capsys):
    sr.seed(env)
    before=env.snapshot()
    assert cli.main(['skill','reference','check',sk1.NAME])==0
    assert ref.VERSION in capsys.readouterr().out
    assert env.snapshot()==before
    source=env.skill_dir()
    assert cli.main(['skill','write',sk1.NAME,'--from',str(source),'--check','--json'])==1
    assert json.loads(capsys.readouterr().out)['reference_pack']==ref.VERSION


def test_offline_and_fetch_status(env,monkeypatch,capsys):
    monkeypatch.setattr(ref,'sources',lambda:[{'url':'https://example.test/a','title':'A','date_read':ref.READ_DATE,'sha256':ref.digest('same')}, {'url':'https://example.test/b','title':'B','date_read':ref.READ_DATE,'sha256':ref.digest('old')}])
    monkeypatch.setattr(ref,'fetch_text',lambda url: 'same' if url.endswith('/a') else 'new')
    before=env.snapshot()
    offline=ref.status(env.home,today=date(2026,11,17))
    assert offline['age_days']==2 and 'last_fetch' not in offline
    assert not ref.status_path(env.home).exists() and env.snapshot()==before
    assert cli.main(['skill','reference','status','--fetch'])==1
    assert 'changed: https://example.test/b' in capsys.readouterr().out
    saved=ref.status(env.home)
    assert [r['state'] for r in saved['last_fetch']['checks']]==['unchanged','changed']
    def fail(url): raise OSError('do not leak response')
    monkeypatch.setattr(ref,'fetch_text',fail)
    assert cli.main(['skill','reference','status'])==0
    assert 'changed' in capsys.readouterr().out
    assert cli.main(['skill','reference','status','--fetch'])==1
    assert 'unreachable' in capsys.readouterr().out
    assert 'do not leak' not in ref.status_path(env.home).read_text()
    monkeypatch.setattr(ref,'fetch_text',lambda url:'same' if url.endswith('/a') else 'old')
    assert cli.main(['skill','reference','status','--fetch'])==0
    assert 'unchanged' in capsys.readouterr().out


def test_native_examples_and_missing(env,monkeypatch,tmp_path):
    plugin=tmp_path/'plugin'; synced=tmp_path/'synced'
    monkeypatch.setenv('SELF_LEARN_SKILL_REFERENCE_PLUGIN_ROOT',str(plugin))
    monkeypatch.setenv('SELF_LEARN_SKILL_REFERENCE_SYNCED_ROOT',str(synced))
    assert ref.local_examples()=={}
    creator=plugin/'v1/skills/skill-creator'; creator.mkdir(parents=True)
    (creator/'SKILL.md').write_text('native creator')
    account=synced/'account'; account.mkdir(parents=True)
    (account/'manifest.json').write_text(json.dumps({'skills':[{'name':'docs','source':'anthropic-example'},{'name':'personal','source':'user'}]}))
    for name in ['docs','personal']:
        folder=account/name;folder.mkdir();(folder/'SKILL.md').write_text('native '+name)
    assert set(ref.local_examples())=={'local-skill-creator','synced-docs'}
    stage=tmp_path/'stage'
    def write(stage,path,text): path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    staged=skills.stage_phase_b(env.home,stage,[],skills.WritingState('on',True),write)
    assert (stage/'skill-reference/PACK.md').read_text()==(ref.PACK_DIR/'PACK.md').read_text()
    assert (stage/'skill-reference/examples/synced-docs/SKILL.md').read_text()=='native docs'
    assert 'synced-personal' not in (stage/'skill-reference/EXAMPLES.md').read_text()
    assert ref.VERSION in '\n'.join(staged.reference_lines)
    monkeypatch.setenv('SELF_LEARN_SKILL_REFERENCE_PLUGIN_ROOT',str(tmp_path/'missing1'))
    monkeypatch.setenv('SELF_LEARN_SKILL_REFERENCE_SYNCED_ROOT',str(tmp_path/'missing2'))
    ref.stage_pack(env.home,tmp_path/'absent',write)
    assert 'No native examples' in (tmp_path/'absent/skill-reference/EXAMPLES.md').read_text()


@pytest.mark.parametrize("mode", ["on", "off"])
def test_overseer_uses_pack_and_reports_guidance(env,monkeypatch,mode):
    ob._set_writing(env,json.dumps(mode))
    real=ob.settings.resolve_setting
    monkeypatch.setattr(ob.settings,'resolve_setting',lambda home,setting:(True,'test') if setting.name=='overseer.enabled' else real(home,setting))
    ob._lesson(env,ob.RID)
    seen={}
    ob._phases(monkeypatch,ob._build_b([ob.RID],files=sk1.draft(description='Processes documents.')),seen=seen)
    ref.record_status(env.home,dict(ref.status(env.home),checked_at='2026-11-15T00:00:00Z',checks=[{'url':'https://example.test/changed','state':'changed'}]))
    result=ob._run(env)
    report=ob._report(result)
    assert result.status=='applied',report
    assert 'skill-reference/PACK.md' in seen['stage']
    assert ref.VERSION in report and 'age ' in report and 'reference source changed' in report
    assert 'guidance-description-trigger' in report
    assert 'skill-reference/PACK.md' in ob.overseer_run._phase_b_prompt(Path('stage'),(),())
    assert 'skill-reference/PACK.md' in '\n'.join(formats._skills_rules())


def test_seed_uses_pack_stamp_and_registry(env):
    from self_learn import verbs
    stamp={'authored_by':'human','case':None,'created':'2026-11-15T00:00:00Z'}
    seed=skill_md_seed(sk1.NAME,'Use when checking seeds.')
    stamped=skill_writer.stamp_skill_md(seed,by='human',case=None,created=stamp['created'])
    assert _read_frontmatter(stamped).mapping['metadata']['self-learn']['reference_pack']==ref.VERSION
    registry=skill_registry.load(env.home)
    verbs._add_owned_scaffold_row(registry,name=sk1.NAME,sha='a'*64,stamp=stamp)
    assert registry.row(sk1.NAME)['last_write']['reference_pack']==ref.VERSION


def test_example_scan_and_manifest_hashes(env,monkeypatch,tmp_path):
    from self_learn import scan
    folder=tmp_path/'native';folder.mkdir()
    sensitive='token' + '=abcdefghijklmno'
    (folder/'SKILL.md').write_text(sensitive)
    monkeypatch.setattr(ref,'local_examples',lambda notes=None:{'native':folder})
    stage=tmp_path/'stage'
    ref.stage_pack(env.home,stage,ob.overseer_run._write_stage)
    manifest=(stage/'skill-reference/sources.yaml').read_text()
    assert 'Model-facing copy' in manifest and len(ref.sources())==5
    assert ref.sources()[0]['sha256'][:12] in manifest
    assert not scan.scan(manifest)
    text=(stage/'skill-reference/examples/native/SKILL.md').read_text()
    assert 'credential-assignment' in text and sensitive not in text
    assert not ob.overseer_run._secret_files(stage)


def test_http_layer_is_bounded_and_rejects_html(monkeypatch):
    import io
    seen=[]
    def urlopen(request,timeout):
        seen.append((request.full_url,timeout,request.get_header('Accept')))
        return io.BytesIO(b'# Official Markdown\n')
    monkeypatch.setattr(ref,'urlopen',urlopen)
    assert ref.fetch_text('https://example.test/page.md')=='# Official Markdown\n'
    assert seen==[('https://example.test/page.md',20,'text/markdown, text/plain')]
    monkeypatch.setattr(ref,'urlopen',lambda *a,**kw:io.BytesIO(b'<!doctype html>challenge'))
    with pytest.raises(ValueError,match='expected nonempty Markdown'):
        ref.fetch_text('https://example.test/page.md')


def test_report_only_retains_staged_reference(env,tmp_path):
    stage=tmp_path/'stage'
    ref.stage_pack(env.home,stage,ob.overseer_run._write_stage)
    report=ob.overseer_run._write_report_only(stage,'# Report\n')
    assert ref.VERSION in report.read_text() and 'age ' in report.read_text()


def test_rename_preserves_reference_version(env):
    assert env.write().ok
    result=skill_writer.rename(env.home,sk1.NAME,'mouse-remapping',by='human',case=None,no_push=True)
    assert result.ok, result.problems
    row=skill_registry.load(env.home).row('mouse-remapping')
    assert row['last_write']['reference_pack']==ref.VERSION


def test_upgrade_pack_updates_row_even_for_same_hash(env,monkeypatch):
    assert env.write().ok
    registry=skill_registry.load(env.home)
    row=registry.row(sk1.NAME)
    before=dict(row['last_write'])
    monkeypatch.setattr(skill_writer,'REFERENCE_VERSION','anthropic-2099-01-01')
    skill_writer._registry_after_write(registry,name=sk1.NAME,sha=before['authored_sha256'],
                                      case=None,by='human',now='2099-01-01T00:00:00Z')
    assert registry.row(sk1.NAME)['last_write']['reference_pack']=='anthropic-2099-01-01'


def test_reference_check_reports_hard_finding(env,capsys):
    folder=env.claude/'skills'/'bad--name';folder.mkdir(parents=True)
    (folder/'SKILL.md').write_text(sk1.draft(name='bad--name')['SKILL.md'])
    before=(folder/'SKILL.md').read_bytes()
    assert cli.main(['skill','reference','check',str(folder)])==1
    text=capsys.readouterr().out
    assert 'refusal: name-hyphens' in text and ref.SPEC in text
    assert (folder/'SKILL.md').read_bytes()==before


def test_status_ignores_corrupt_cache(env):
    current=ref.status(env.home)
    ref.record_status(env.home,dict(current,checked_at='now',checks='broken'))
    result=ref.status(env.home)
    assert 'last_fetch' not in result
    assert 'no fetch recorded' in '\n'.join(ref.status_lines(result))
