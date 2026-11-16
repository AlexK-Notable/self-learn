"""S-159 review F1-F8: failure boundaries, installed views and report facts."""
import json
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_overseer_skill_build as ob
import test_skill_write as sk1
import test_skill_registration as sr
from self_learn import cli, skill_cli, skill_reference as ref, skill_registry, skill_writer, verbs
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from self_learn.skill_scaffold import SkillScaffoldError, _read_frontmatter, skill_md_seed
from self_learn.overseer import skills
from support import commit_all, make_behavior, last_verb_sha

RID = "lrn-5c2a0091"
RID2 = "lrn-5c2a0092"


@pytest.fixture
def env(tmp_path, monkeypatch):
    return sk1.Env(tmp_path, monkeypatch)


def pending(env, rid=RID, trigger="About to run npm i -g <pkg> from a tool call."):
    create_record(env.home, make_behavior(scope="skill:s", record_id=rid, trigger=trigger))
    commit_all(env.home, "seed pending lesson")


@pytest.mark.parametrize("trigger", ["About to run npm i -g <pkg> from a tool call.", "About to use <pkg> " + "long " * 250])
def test_route_seed_description_is_valid_and_recompile_repairs(env, monkeypatch, trigger):
    pending(env, trigger=trigger)
    # Historic unowned scaffolds are allowed to be regenerated.
    monkeypatch.setattr(verbs, "_scaffold_owner", lambda *a: None)
    assert cli.main(["route", RID, "--dest", "new-skill:npm-tips", "--no-push"]) == 0
    target = env.skill_md("npm-tips")
    front = _read_frontmatter(target.read_text()).mapping
    assert "<" not in front["description"] and ">" not in front["description"]
    assert len(front["description"]) <= 1024
    assert RID in target.read_text()
    shutil.rmtree(env.plugin_dir("npm-tips"))
    commit_all(env.root, "simulate missing historic scaffold")
    result = verbs.recompile(env.home, no_push=True)
    assert target.is_file(), result.warnings
    assert RID in target.read_text()
    assert _read_frontmatter(target.read_text()).mapping["description"] == front["description"]


@pytest.mark.parametrize("name,rule", [("tips-", "name-hyphens"), ("a--b", "name-hyphens"),
                                      ("claude-tips", "name-reserved-word"), ("synced", "name-synced")])
def test_route_bad_seed_name_refuses_before_commit(env, capsys, name, rule):
    pending(env)
    before = (last_verb_sha(env.home), env.snapshot())
    assert cli.main(["route", RID, "--dest", "new-skill:" + name, "--no-push"]) != 0
    output = capsys.readouterr()
    assert rule in output.err + output.out
    assert Record.from_path(find_record_path(env.home, RID)).status == "pending"
    assert (last_verb_sha(env.home), env.snapshot()) == before


def test_recompile_bad_historic_seed_does_not_stop_other_targets(env, monkeypatch):
    pending(env)
    pending(env, RID2)
    with monkeypatch.context() as patch:
        patch.setattr(verbs, "_scaffold_owner", lambda *a: None)
        patch.setattr(verbs, "validate_seed_name", lambda name: name)
        patch.setattr(verbs, "skill_md_seed", lambda name, desc: skill_md_seed("valid-name", desc).replace("valid-name", name))
        verbs.route(env.home, RID, dest="new-skill:tips-", no_push=True)
        verbs.route(env.home, RID2, dest="new-skill:working-tips", no_push=True)
    shutil.rmtree(env.plugin_dir("tips-"))
    shutil.rmtree(env.plugin_dir("working-tips"))
    commit_all(env.root, "simulate historic targets absent")
    result = verbs.recompile(env.home, no_push=True)
    assert any("name-hyphens" in line and RID in line for line in result.warnings)
    assert env.skill_md("working-tips").is_file(), result.warnings
    assert RID2 in env.skill_md("working-tips").read_text()
    assert not env.skill_md("tips-").exists()


def test_seed_failure_after_commit_is_reported_and_recompile_continues(env, monkeypatch):
    pending(env)
    pending(env, RID2)
    original = verbs.skill_md_seed
    def seed(name, description):
        if name == "broken-tips":
            raise SkillScaffoldError("synthetic seed refusal")
        return original(name, description)
    monkeypatch.setattr(verbs, "skill_md_seed", seed)
    monkeypatch.setattr(verbs, "_scaffold_owner", lambda *a: None)
    routed = verbs.route(env.home, RID, dest="new-skill:broken-tips", no_push=True)
    assert any("HOST PHASE FAILED" in line for line in routed.warnings)
    assert Record.from_path(find_record_path(env.home, RID)).status == "routed"
    verbs.route(env.home, RID2, dest="new-skill:working-tips", no_push=True)
    shutil.rmtree(env.plugin_dir("working-tips"))
    commit_all(env.root, "simulate another missing target")
    repaired = verbs.recompile(env.home, no_push=True)
    assert any("synthetic seed refusal" in line for line in repaired.warnings)
    assert RID2 in env.skill_md("working-tips").read_text()


def test_seed_is_computed_at_write_boundary(env, monkeypatch):
    pending(env)
    monkeypatch.setattr(verbs, "_scaffold_owner", lambda *a: None)
    verbs.route(env.home, RID, dest="new-skill:npm-tips", no_push=True)
    target = env.skill_md("npm-tips")
    spec = verbs._resolve_target(env.home, find_record_path(env.home, RID).parent.parent,
                                 "skill:s", "new-skill", "npm-tips", check_dirty=False)
    real = Path.is_file
    seen = 0
    def race(path):
        nonlocal seen
        answer = real(path)
        if path == target:
            seen += 1
            if seen == 1:
                target.unlink()
                return True
        return answer
    monkeypatch.setattr(Path, "is_file", race)
    verbs._apply_new_skill(env.home, spec)
    assert target.read_text().startswith("---\nname: npm-tips\n")
    assert RID in target.read_text()


def native(env, monkeypatch):
    plugin = env.home.parent / "native-plugin"
    synced = env.home.parent / "native-synced"
    monkeypatch.setenv("SELF_LEARN_SKILL_REFERENCE_PLUGIN_ROOT", str(plugin))
    monkeypatch.setenv("SELF_LEARN_SKILL_REFERENCE_SYNCED_ROOT", str(synced))
    creator = plugin / "v1/skills/skill-creator"
    creator.mkdir(parents=True)
    (creator / "SKILL.md").write_text("native creator")
    account = synced / "account"
    account.mkdir(parents=True)
    return creator, account


@pytest.mark.parametrize("shape", [[], "text", None, {"skills": None}, {"skills": 3}, {"skills": [None]}, {}, {"skills": [{"source": []}]}])
def test_bad_example_manifest_never_refuses_weekly_run(env, monkeypatch, shape):
    creator, account = native(env, monkeypatch)
    (account / "manifest.json").write_text(json.dumps(shape))
    ob._set_writing(env, '"on"')
    enable_overseer(monkeypatch)
    ob._lesson(env, ob.RID)
    ob._phases(monkeypatch, ob._build_b([ob.RID]))
    result = ob._run(env)
    report = ob._report(result)
    assert result.status == "applied", report
    assert "omitted" in ob._section(report, "Refused / could not do")
    assert "skill reference example" in ob._section(report, "Refused / could not do")
    assert ref.VERSION in report


@pytest.mark.parametrize("failure", ["candidate-stat", "file-stat", "read", "manifest-read", "disappeared"])
def test_unreadable_or_disappearing_example_is_omitted(env, monkeypatch, failure):
    creator, account = native(env, monkeypatch)
    manifest = account / "manifest.json"
    manifest.write_text('{"skills": []}')
    real_stat, real_read, real_glob = Path.stat, Path.read_text, Path.glob
    entry = creator / "SKILL.md"
    if failure == "candidate-stat":
        def stat(path, *a, **kw):
            if path == entry:
                raise FileNotFoundError("removed")
            return real_stat(path, *a, **kw)
        monkeypatch.setattr(Path, "stat", stat)
    elif failure == "disappeared":
        def glob(path, pattern):
            found = list(real_glob(path, pattern))
            if path == creator.parents[2]:
                entry.unlink()
                creator.rmdir()
            return iter(found)
        monkeypatch.setattr(Path, "glob", glob)
    elif failure == "file-stat":
        monkeypatch.setattr(ref, "local_examples", lambda notes=None: {"native": creator})
        def stat(path, *a, **kw):
            if path == entry:
                raise FileNotFoundError("removed")
            return real_stat(path, *a, **kw)
        monkeypatch.setattr(Path, "stat", stat)
    else:
        def read(path, *a, **kw):
            if path == (manifest if failure == "manifest-read" else entry):
                raise PermissionError("unreadable")
            return real_read(path, *a, **kw)
        monkeypatch.setattr(Path, "read_text", read)
    stage = env.home.parent / "stage"
    staged = skills.stage_phase_b(env.home, stage, [], skills.WritingState("on", True), ob.overseer_run._write_stage)
    assert (stage / "skill-reference/PACK.md").is_file()
    assert any("omitted" in note for note in staged.notes), staged.notes
    assert "omitted" in (stage / "skill-reference/EXAMPLES.md").read_text()
    if failure != "manifest-read":
        assert not (stage / "skill-reference/examples/local-skill-creator/SKILL.md").exists()


def test_pack_failure_is_reported_without_aborting(env, monkeypatch):
    def broken(): raise OSError("missing package manifest")
    monkeypatch.setattr(ref, "sources", broken)
    staged = skills.stage_phase_b(env.home, env.home.parent / "stage", [], skills.WritingState("on", True), ob.overseer_run._write_stage)
    assert any("staging could not finish" in note for note in staged.notes)
    assert ref.VERSION in "\n".join(staged.reference_lines)


@pytest.mark.parametrize("registered", [False, True])
def test_reference_check_uses_writer_view_and_retains_assets(env, capsys, registered):
    if registered:
        sr.seed(env)
        sr.register(env)
    assert env.write().ok
    pending(env)
    verbs.route(env.home, RID, dest="reference", no_push=True)
    # Put a real managed shelf/pointer into this target's skill bucket.
    create_record(env.home, make_behavior(scope="skill:" + sk1.NAME, record_id=RID2))
    commit_all(env.home, "seed skill reference lesson")
    verbs.route(env.home, RID2, dest="reference", no_push=True)
    target = env.skill_dir()
    (target / "plugins.json").write_text('{"owned": "user"}')
    (target / "asset.bin").write_bytes(b"\xff")
    (target / "asset-link").symlink_to(target / "asset.bin")
    commit_all(env.root, "add user assets")
    files = skill_writer.draft_view(skill_writer.deployed_files(env.home, sk1.NAME))
    checked = skill_writer.check(env.home, sk1.NAME, files)
    assert checked.ok, checked.problems
    before = env.snapshot()
    assert cli.main(["skill", "reference", "check", str(target)]) == 0
    text = capsys.readouterr().out
    assert "0 refusals" in text
    assert "references/LEARNINGS.md: left in place by writes" in text
    assert "plugins.json: left in place by writes" in text
    assert "asset-link: left in place by writes" in text
    assert env.snapshot() == before


def test_check_owned_carried_name_and_broken_hosts(env, monkeypatch, capsys):
    assert env.write().ok
    # Existing names are passed exactly as the writer does for an owned row.
    from self_learn import skill_scaffold
    real = skill_scaffold.check_skill
    seen = []
    def check(*a, **kw):
        seen.append(kw["existing_name"])
        return real(*a, **kw)
    monkeypatch.setattr(skill_scaffold, "check_skill", check)
    assert cli.main(["skill", "reference", "check", str(env.skill_dir())]) == 0
    assert seen == [sk1.NAME]
    (env.home / "hosts.yaml").write_text("broken: [")
    assert cli.main(["skill", "reference", "check", sk1.NAME]) == skill_cli.EXIT_USAGE
    assert "skill reference check:" in capsys.readouterr().err


def enable_overseer(monkeypatch):
    real = ob.settings.resolve_setting
    monkeypatch.setattr(ob.settings, "resolve_setting", lambda home, setting:
        (True, "test") if setting.name == "overseer.enabled" else real(home, setting))


def test_reference_report_facts_and_only_kept_guidance(env, monkeypatch):
    ob._set_writing(env, '"on"')
    enable_overseer(monkeypatch)
    ob._lesson(env, ob.RID)
    ob._phases(monkeypatch, ob._build_b([ob.RID], files=sk1.draft(description="Processes documents.")))
    result = ob._run(env)
    report = ob._report(result)
    assert result.status == "applied", report
    decided = ob._section(report, "Decided in the user's stead")
    assert "[new skill]" in decided
    assert ref.VERSION not in decided and "guidance-" not in decided
    section = ob._section(report, "Skill reference")
    assert ref.VERSION in section and "guidance-description-trigger" in section
    manifest = {"skills": {"reference_lines": ["pack fact"]}, "cases": {
        "applied": {"skill": {"state": "applied", "name": "kept", "reference_notes": ["kept guidance"]}},
        "refused": {"skill": {"state": "refused", "name": "lost", "reference_notes": ["lost guidance"]}}}}
    assert skills.reference_report_lines(manifest) == ["pack fact", "kept: kept guidance"]
    stage = env.home.parent / "report-stage"
    ref.stage_pack(env.home, stage, ob.overseer_run._write_stage)
    once = ob.overseer_run._write_report_only(stage, report).read_text()
    assert once.count("## Skill reference") == 1


def test_status_fetch_overall_deadline_including_stuck_http(env, monkeypatch):
    monkeypatch.setattr(ref, "FETCH_TOTAL_SECONDS", 0.04)
    monkeypatch.setattr(ref, "FETCH_SOURCE_SECONDS", 1)
    source = {"url": "https://example.test/slow", "sha256": ref.digest("ok")}
    monkeypatch.setattr(ref, "sources", lambda: [dict(source), dict(source), dict(source)])
    unblock = threading.Event()
    calls = []
    def stuck(url):
        calls.append(url)
        unblock.wait()
        return "ok"
    start = time.monotonic()
    try:
        result = ref.status(env.home, fetch=True, fetcher=stuck)
    finally:
        unblock.set()
    assert time.monotonic() - start < 0.5
    assert len(calls) == 1
    assert [r["state"] for r in result["checks"]] == ["unreachable"] * 3
    assert all(r["error"] == "TimeoutError" for r in result["checks"])
    assert ref.status(env.home)["last_fetch"]["checks"] == result["checks"]


def test_rollback_contract_and_description_policy(env, monkeypatch):
    assert env.write().ok
    row = skill_registry.load(env.home).row(sk1.NAME)
    assert row["last_write"]["reference_pack"] == ref.VERSION
    # Positive reproduction of the old strict parser: a code-only rollback fails.
    monkeypatch.setattr(skill_registry, "_WRITE_KEYS", tuple(k for k in skill_registry._WRITE_KEYS if k != "reference_pack"))
    with pytest.raises(skill_registry.SkillRegistryError, match="reference_pack"):
        skill_registry.load(env.home)
    root = Path(__file__).resolve().parents[4]
    spec = (root / "docs/specs/self-learn/02-schema.md").read_text()
    assert "S-159 rollback note" in spec and "last_write.reference_pack" in spec
    assert "code-only rollback incompatible" in spec
    pack = (ref.PACK_DIR / "PACK.md").read_text()
    for phrase in ("even though it performs no uploads", "shortened in its first rewrite",
                   "listing-text-too-long", "when-to-use-not-text", "when-to-use-xml-tag"):
        assert phrase in pack


def test_version_printed_only_after_read_and_check(env, monkeypatch, capsys):
    args = SimpleNamespace(as_json=False, source=env.home / "absent", check=True,
                           name=sk1.NAME, expect_sha=None)
    assert skill_cli._write(env.home, args) == skill_cli.EXIT_USAGE
    assert "skill reference checked" not in capsys.readouterr().out
    source = env.home.parent / "draft"
    source.mkdir()
    (source / "SKILL.md").write_text(sk1.draft()["SKILL.md"])
    args.source = source
    real = skill_writer.check
    def checked(*a, **kw):
        assert "skill reference checked" not in capsys.readouterr().out
        return real(*a, **kw)
    monkeypatch.setattr(skill_writer, "check", checked)
    skill_cli._write(env.home, args)
    assert "skill reference checked: " + ref.VERSION in capsys.readouterr().out


def test_registered_overlong_description_must_be_shortened_on_first_rewrite(env):
    files = sk1.draft(description="Use when " + "x" * 1100)
    sr.seed(env, text=files["SKILL.md"])
    sr.register(env)
    checked = skill_writer.check(env.home, sk1.NAME, files)
    assert not checked.ok and any("description-too-long" in p for p in checked.problems)
    files["SKILL.md"] = files["SKILL.md"].replace("Use when " + "x" * 1100, "Use when configuring a mouse.")
    assert env.write(files).ok


def test_guidance_from_a_refused_write_is_not_reported_as_applied(env, monkeypatch):
    ob._set_writing(env, '"on"')
    enable_overseer(monkeypatch)
    ob._lesson(env, ob.RID)
    ob._phases(monkeypatch, ob._build_b([ob.RID], files=sk1.draft(description="Processes documents.")))
    calls = []
    def refuse(home, name, files, **kwargs):
        calls.append(name)
        return skill_writer.WriteResult(name, False, kind=skill_writer.KIND_TARGET_BUSY,
                                        problems=("synthetic apply refusal",))
    monkeypatch.setattr(skill_writer, "write", refuse)
    result = ob._run(env)
    report = ob._report(result)
    assert calls == [sk1.NAME]
    assert "synthetic apply refusal" in ob._section(report, "Refused / could not do")
    assert ref.VERSION in ob._section(report, "Skill reference")
    assert "guidance-description-trigger" not in report


@pytest.mark.parametrize("name", ["cron-claude", "anthropic-helper", "tips-", "a--b", "synced"])
def test_existing_legacy_name_allows_route_recompile_and_reroute(env, name):
    from self_learn.compilers import BEGIN_MARKER, END_MARKER
    folder = env.skill_dir(name)
    folder.mkdir(parents=True)
    authored = f"---\nname: {name}\ndescription: Use when scheduling jobs.\n---\n\n# Existing skill\n"
    (folder / "SKILL.md").write_text(authored + f"\n{BEGIN_MARKER}\n{END_MARKER}\n")
    commit_all(env.root, "seed existing user skill")
    pending(env)
    result = verbs.route(env.home, RID, dest="new-skill:" + name, no_push=True)
    assert not result.warnings, result.warnings
    assert RID in (folder / "SKILL.md").read_text()
    compiled = verbs.recompile(env.home, no_push=True)
    assert not any("name-" in note for note in compiled.warnings), compiled.warnings
    assert RID in (folder / "SKILL.md").read_text()
    moved = verbs.reroute(env.home, RID, dest="reference", no_push=True)
    assert not any("HOST PHASE FAILED" in note for note in moved.warnings), moved.warnings
    assert RID not in (folder / "SKILL.md").read_text()
    assert (folder / "SKILL.md").read_text().startswith(authored)
    assert Record.from_path(find_record_path(env.home, RID)).routing["destination"] == "reference"


@pytest.mark.parametrize("registered", [False, True])
def test_reference_modes_match_draft_and_installed_writer_views(env, capsys, registered):
    if registered:
        sr.seed(env)
        sr.register(env)
    assert env.write().ok
    deployed = env.skill_dir()
    (deployed / "scripts").mkdir()
    (deployed / "scripts/helper.py").write_text("print('fixture helper')\n")
    commit_all(env.root, "user-owned asset")
    assert cli.main(["skill", "reference", "check", str(deployed)]) == 0
    installed_output = capsys.readouterr().out
    assert "mode: installed" in installed_output and "retained-file: scripts/helper.py" in installed_output
    # The reviewer's folder shape: stamped SKILL.md, compiler block, helper.
    draft = env.home.parent / "draft-probe"
    shutil.copytree(deployed, draft)
    from self_learn.compilers import BEGIN_MARKER, END_MARKER
    md = draft / "SKILL.md"
    md.write_text(md.read_text() + f"\n{BEGIN_MARKER}\n- a line\n{END_MARKER}\n")
    before = {str(p): p.read_bytes() for p in draft.rglob("*") if p.is_file()}
    supplied = skill_writer.read_draft_dir(draft)
    checked = skill_writer.check(env.home, sk1.NAME, supplied)
    assert not checked.ok and any("metadata-self-learn" in line for line in checked.problems)
    assert cli.main(["skill", "reference", "check", str(draft)]) == 1
    output = capsys.readouterr().out
    assert "mode: draft" in output
    for rule in ("metadata-self-learn", "file-outside-references", "file-not-markdown"):
        assert rule in output and any(rule in line for line in checked.problems)
    assert cli.main(["skill", "write", sk1.NAME, "--from", str(draft), "--check"]) == 1
    capsys.readouterr()
    assert cli.main(["skill", "reference", "check", str(deployed), "--draft"]) == 1
    assert "mode: draft" in capsys.readouterr().out
    # Force the installed interpretation of an off-root copy named like its skill.
    installed_copy = env.home.parent / "installed-copy" / sk1.NAME
    shutil.copytree(deployed, installed_copy)
    assert cli.main(["skill", "reference", "check", str(installed_copy), "--installed"]) == 0
    assert "mode: installed" in capsys.readouterr().out
    assert {str(p): p.read_bytes() for p in draft.rglob("*") if p.is_file()} == before


def test_draft_mode_keeps_pointer_and_shelf_refusals(env, capsys):
    assert env.write().ok
    create_record(env.home, make_behavior(scope="skill:" + sk1.NAME, record_id=RID))
    commit_all(env.home, "seed shelf lesson")
    verbs.route(env.home, RID, dest="reference", no_push=True)
    source = env.home.parent / "incoming-draft"
    shutil.copytree(env.skill_dir(), source)
    assert cli.main(["skill", "reference", "check", str(source)]) == 1
    text = capsys.readouterr().out
    assert "mode: draft" in text and "reference-shelf" in text and "pointer-block" in text
    files = skill_writer.draft_view(skill_writer.deployed_files(env.home, sk1.NAME))
    shutil.rmtree(source)
    source.mkdir()
    for key, value in files.items():
        path = source / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    assert skill_writer.check(env.home, sk1.NAME, files).ok
    assert cli.main(["skill", "reference", "check", str(source)]) == 0
    assert "mode: draft" in capsys.readouterr().out


@pytest.mark.parametrize("mapping", [False, True])
@pytest.mark.parametrize("bad", [None, {}, {"source": []}, {"source": "anthropic", "name": "../bad"},
                                 {"source": "anthropic", "name": "not-downloaded"}])
def test_one_bad_manifest_row_keeps_other_examples(env, monkeypatch, mapping, bad):
    _, account = native(env, monkeypatch)
    good = [{"source": "anthropic", "name": "before"}, {"source": "anthropic-example", "name": "after"}]
    for row in good:
        folder = account / row["name"]
        folder.mkdir()
        (folder / "SKILL.md").write_text("Example " + row["name"])
    rows = [good[0], bad, good[1]]
    if mapping:
        rows = {row.get("name", "bad") if isinstance(row, dict) else "bad": row for row in rows}
    (account / "manifest.json").write_text(json.dumps({"skills": rows}))
    stage = env.home.parent / "stage"
    staged = skills.stage_phase_b(env.home, stage, [], skills.WritingState("on", True), ob.overseer_run._write_stage)
    for name in ("before", "after"):
        assert (stage / f"skill-reference/examples/synced-{name}/SKILL.md").read_text() == "Example " + name
    assert len(staged.notes) == 1 and "row 2 omitted" in staged.notes[0], staged.notes
    index = (stage / "skill-reference/EXAMPLES.md").read_text()
    assert "synced-before" in index and "synced-after" in index
