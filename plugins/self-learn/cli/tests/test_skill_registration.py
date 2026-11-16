"""S-157 registration, editorial boundaries, adoption and agent requests."""
from pathlib import Path
import json

import pytest

import test_skill_write as sk1
from self_learn import cli, skill_registration as reg, skill_registry, skill_writer, skill_requests
from self_learn.ledger_ops import create_record
from self_learn.skill_scaffold import _read_frontmatter
from support import commit_all, git, make_behavior

NAME = sk1.NAME


@pytest.fixture
def env(tmp_path, monkeypatch):
    return sk1.Env(tmp_path, monkeypatch)


def seed(env, path=None, *, text=None):
    path = path or env.skill_dir()
    path.mkdir(parents=True, exist_ok=True)
    for rel, value in sk1.draft().items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text if rel == "SKILL.md" and text is not None else value)
    if path.is_relative_to(env.root):
        commit_all(env.root, "seed user skill")
    return path


def register(env, path=None):
    return reg.register(env.home, str(path or NAME), note="Keep this user skill current", by="agent")


@pytest.mark.parametrize("failure", ["mkdir", "before-move", "both-complete", "commit", "partial-target", "rename"])
def test_adoption_rollback_preserves_original_copy(env, monkeypatch, failure):
    path = seed(env, env.claude / "skills" / NAME)
    original = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    inode = path.stat().st_ino
    target = env.skill_dir()
    real_mkdir, real_move, real_copy = Path.mkdir, reg.shutil.move, reg.shutil.copytree
    copies_back = []

    def copy(source, destination, *args, **kwargs):
        if Path(destination) == path:
            copies_back.append(destination)
            if failure in ("mkdir", "before-move", "both-complete", "commit"):
                raise OSError("backup restore unavailable")
        return real_copy(source, destination, *args, **kwargs)

    def mkdir(folder, *args, **kwargs):
        if failure == "mkdir" and folder == target.parent:
            raise OSError("target parent unavailable")
        return real_mkdir(folder, *args, **kwargs)

    def move(source, destination):
        if failure == "before-move":
            raise OSError("move did not start")
        if failure == "both-complete":
            real_copy(source, destination)
            raise OSError("copy complete but source untouched")
        real_move(source, destination)
        if failure == "partial-target":
            (target / "SKILL.md").unlink()
            raise OSError("incomplete moved copy")

    def commit(*args, **kwargs):
        raise OSError("commit unavailable")

    def rename(*args, **kwargs):
        raise OSError("rename unavailable")

    monkeypatch.setattr(reg.shutil, "copytree", copy)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(reg.shutil, "move", move)
    monkeypatch.setattr(reg.gitops, "stage_and_commit", commit)
    if failure == "rename":
        monkeypatch.setattr(reg.os, "rename", rename)
    with pytest.raises(reg.RegistrationError, match="adoption failed"):
        register(env, path)
    assert path.is_dir()
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()} == original
    if failure in ("mkdir", "before-move", "both-complete", "commit"):
        assert path.stat().st_ino == inode
        assert copies_back == []
    else:
        assert len(copies_back) == 1
    assert not env.plugin_dir().exists()


def test_change_request_refuses_vetoed_registration(env):
    seed(env)
    register(env)
    assert skill_requests.veto(env.home, NAME, by="human", no_push=True).ok
    before = env.head(env.home)
    with pytest.raises(ValueError, match=NAME + " is vetoed; upkeep is disabled"):
        skill_requests.file_request(env.home, "change", NAME, lessons=[], note="Improve examples", by="agent")
    assert env.head(env.home) == before
    assert skill_requests.requests(env.home) == []


def test_build_request_checks_loaded_inventory(env):
    name = "already-loaded"
    seed(env, env.claude / "skills" / name, text=sk1.draft(name)["SKILL.md"])
    create_record(env.home, make_behavior(record_id=sk1.RID))
    commit_all(env.home, "seed build lesson")
    loaded, problems, _ = skill_writer._loaded_names(env.home, leaving_out=None)
    assert name in loaded and not problems
    before = env.head(env.home)
    with pytest.raises(ValueError, match="already loaded: " + name):
        skill_requests.file_request(env.home, "build", name, lessons=[sk1.RID], note="Combine examples", by="agent")
    assert env.head(env.home) == before
    assert skill_requests.requests(env.home) == []


def test_register_in_place_and_withdraw(env, monkeypatch, capsys):
    seed(env)
    monkeypatch.setenv("CLAUDECODE", "1")
    before = env.head(env.root)
    assert cli.main(["skill", "register", NAME, "--note", "Keep the procedure current"]) == 0
    row = skill_registry.load(env.home).registrations[NAME]
    assert row["registered"]["by"] == "agent"
    assert row["registered"]["path"] == str(env.skill_dir())
    assert row["registered"]["checks"]
    assert row["registered"]["note"] == "Keep the procedure current"
    assert row["registered"]["at"]
    assert not skill_registry.load(env.home).is_owned(NAME)
    assert skill_registry.load(env.home).may_edit(NAME)
    assert env.head(env.root) == before
    head = env.head(env.home)
    assert register(env)["state"] == "already registered"
    assert env.head(env.home) == head
    assert cli.main(["skill", "list", "--json"]) == 0
    assert '"registrations"' in capsys.readouterr().out
    assert cli.main(["skill", "unregister", NAME, "--note", "I will maintain this myself"]) == 0
    registry = skill_registry.load(env.home)
    assert not registry.may_edit(NAME)
    assert registry.registrations[NAME]["withdrawn"]["by"] == "agent"
    assert env.skill_md().exists()
    assert register(env)["state"] == "registered"


@pytest.mark.parametrize("signal", ["aws", "agents", "lock", "plugin", "synced", "npm", "codex", "marker", "upstream", "repo", "malformed-lock", "symlink", "layout"])
def test_refusal_signals(env, monkeypatch, signal):
    agents = env.tmp / "agents"
    codex = env.tmp / "codex"
    monkeypatch.setenv("SELF_LEARN_AGENTS_DIR", str(agents))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    paths = {"agents": agents / "skills" / NAME, "plugin": env.claude / "plugins" / NAME,
        "synced": env.claude / "skills" / "synced" / NAME,
        "npm": env.tmp / "node_modules" / NAME, "codex": codex / "skills" / ".system" / NAME,
        "repo": env.tmp / "foreign" / NAME,
        "layout": env.root / "plugins" / "wrong" / "skills" / NAME}
    path = seed(env, paths.get(signal, env.claude / "skills" / NAME))
    expected = {"aws": ".aws-skill-metadata", "agents": ".agents/", "lock": ".skill-lock.json",
        "plugin": "plugins/", "synced": "synced/", "npm": "node_modules/", "codex": ".system/",
        "marker": "LOCAL ADDITIONS BELOW", "upstream": "metadata.upstream", "repo": "another git repository",
        "malformed-lock": "cannot check .skill-lock.json", "symlink": "symlinks", "layout": "not in plugins/"}[signal]
    if signal == "aws":
        (path / ".aws-skill-metadata").write_text("{}")
    if signal in ("lock", "malformed-lock"):
        agents.mkdir(exist_ok=True)
        (agents / ".skill-lock.json").write_text(json.dumps({"skills": {NAME: {}}}) if signal == "lock" else "broken")
    if signal == "marker":
        (path / "SKILL.md").write_text(sk1.draft(extra="LOCAL ADDITIONS BELOW")["SKILL.md"])
    if signal == "upstream":
        (path / "SKILL.md").write_text(sk1.draft(metadata={"upstream": "vendor"})["SKILL.md"])
    if signal == "repo":
        git(path.parent, "init")
    if signal == "symlink":
        (env.tmp / "foreign.txt").write_text("Preserve this file.")
        (path / "linked").symlink_to(env.tmp / "foreign.txt")
    if signal in ("agents", "plugin", "synced", "npm", "codex"):
        alias = env.claude / "skills" / NAME
        alias.symlink_to(path)
        path = alias
    before = env.head(env.home)
    with pytest.raises(reg.RegistrationError, match=expected):
        register(env, path)
    assert env.head(env.home) == before
    assert not skill_registry.load(env.home).may_edit(NAME)
    assert path.is_dir()


@pytest.mark.parametrize("bad", ["missing", "frontmatter", "name", "note", "owned", "veto"])
def test_input_refusals(env, bad):
    path = seed(env)
    if bad == "missing":
        (path / "SKILL.md").unlink()
    if bad == "frontmatter":
        (path / "SKILL.md").write_text("no frontmatter")
    if bad == "name":
        (path / "SKILL.md").write_text(sk1.draft("other-name")["SKILL.md"])
    if bad == "owned":
        # Give an already present user skill a genuine writer-created owned peer.
        result = skill_writer.write(env.home, "other-name", sk1.draft("other-name"), case=None, by="human", no_push=True)
        assert result.ok, result
        path = env.skill_dir("other-name")
    if bad == "veto":
        assert skill_requests.veto(env.home, NAME, by="human", no_push=True).ok
    with pytest.raises(reg.RegistrationError):
        reg.register(env.home, str(path), note="" if bad == "note" else "upkeep", by="agent")


@pytest.mark.parametrize("argument", ["name", "path"])
def test_adopt_backup_links_and_manifest(env, argument):
    path = seed(env, env.claude / "skills" / NAME)
    before = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    result = register(env, path if argument == "path" else None)
    assert result["adopted"]
    backup = Path(result["backup"])
    assert {p.relative_to(backup): p.read_bytes() for p in backup.rglob("*") if p.is_file()} == before
    assert path.is_symlink() and path.resolve() == env.skill_dir()
    assert env.skill_md().read_bytes() == before[Path("SKILL.md")]
    assert json.loads((env.plugin_dir() / ".claude-plugin/plugin.json").read_text())["name"] == NAME
    assert any(p["name"] == NAME for p in json.loads(env.marketplace.read_text())["plugins"])
    assert result["host_commit"] == env.head(env.root)
    assert not env.status(env.root)
    assert not skill_registry.load(env.home).is_owned(NAME)


def test_registered_writer_hash_and_boundaries(env):
    seed(env)
    register(env)
    result = skill_writer.write(env.home, NAME, sk1.draft(extra="Updated procedure.\n"), case=None, by="human", no_push=True)
    assert result.ok and result.updating, result
    registry = skill_registry.load(env.home)
    assert registry.may_edit(NAME) and not registry.is_owned(NAME)
    stamp = _read_frontmatter(env.skill_md().read_text()).mapping["metadata"]["self-learn"]
    assert stamp["registered_by"] == "agent" and "authored_by" not in stamp
    assert _read_frontmatter(env.skill_md().read_text()).mapping["name"] == NAME
    assert registry.row(NAME)["last_write"]["authored_sha256"] == skill_writer.deployed_authored_sha256(env.home, NAME)
    assert not skill_writer.rename(env.home, NAME, "new-name", case=None, by="human", no_push=True).ok
    assert not skill_writer.retire(env.home, NAME, case=None, by="human", no_push=True).ok
    assert not skill_requests.request_retire(env.home, NAME, by="human").ok
    env.skill_md().write_text(env.skill_md().read_text() + "A person's later edit.\n")
    fresh = skill_writer.deployed_authored_sha256(env.home, NAME)
    assert not skill_writer.write(env.home, NAME, sk1.draft(extra="Next edit"), case=None, by="human", no_push=True).ok
    assert not skill_writer.write(env.home, NAME, sk1.draft(extra="Next edit"), expect_sha=fresh, case=None, by="human", no_push=True).ok
    commit_all(env.root, "person's edit")
    assert not skill_writer.write(env.home, NAME, sk1.draft(extra="Next edit"), expect_sha=result.authored_sha256, case=None, by="human", no_push=True).ok
    assert skill_writer.write(env.home, NAME, sk1.draft(extra="Next edit"), expect_sha=fresh, case=None, by="human", no_push=True).ok
    reg.unregister(env.home, NAME, note="withdraw", by="agent")
    assert not skill_writer.write(env.home, NAME, sk1.draft(), updating=True, case=None, by="human", no_push=True).ok


def test_first_write_preserves_intervening_edit(env):
    seed(env)
    register(env)
    env.skill_md().write_text(env.skill_md().read_text() + "Person edited after registration.\n")
    commit_all(env.root, "person edits before first write")
    assert not skill_writer.write(env.home, NAME, sk1.draft(), case=None, by="human", no_push=True).ok


def test_requests_agent_no_grant_and_validation(env, monkeypatch):
    seed(env)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["skill", "request", "change", NAME, "--note", "Improve examples"]) == 1
    register(env)
    assert cli.main(["skill", "request", "change", NAME, "--note", "Improve examples"]) == 0
    with pytest.raises(ValueError, match="does not exist"):
        skill_requests.file_request(env.home, "build", "new-name", lessons=["lrn-1234abcd"], note="Combine", by="agent")
    create_record(env.home, make_behavior(record_id="lrn-1234abcd"))
    commit_all(env.home, "seed lesson")
    assert cli.main(["skill", "request", "build", "--name", "new-name", "--lessons", "lrn-1234abcd", "--note", "Combine"]) == 0
    rows = skill_requests.requests(env.home, open_only=True)
    assert len(rows) == 2 and all(r["by"] == "agent" for r in rows)
    assert rows[1]["lessons"] == ["lrn-1234abcd"]
    assert rows[0]["note"] == "Improve examples"


@pytest.mark.parametrize("failure", ["plain", "collision", "dirty", "commit"])
def test_adoption_refusal_and_rollback(env, monkeypatch, failure):
    from self_learn import gitops
    path = seed(env, env.claude / "skills" / NAME)
    original = (path / "SKILL.md").read_bytes()
    market = env.marketplace.read_bytes()
    if failure == "plain":
        hosts = env.home / "hosts.yaml"
        from ruamel.yaml import YAML
        data = YAML(typ="safe").load(hosts.read_text())
        data["skills_root"] = {"path": str(env.root), "mode": "plain"}
        import io
        stream = io.StringIO()
        YAML().dump(data, stream)
        hosts.write_text(stream.getvalue())
        commit_all(env.home, "plain root")
        (env.root / ".self-learn-host").write_text("synthetic host marker")
    elif failure == "collision":
        env.plugin_dir().mkdir(parents=True)
    elif failure == "dirty":
        changed = json.loads(market)
        changed["metadata"]["description"] = "A person changed this."
        env.marketplace.write_text(json.dumps(changed, indent=2) + "\n")
    else:
        real = gitops.stage_and_commit
        def fail(repo, *args, **kwargs):
            if repo == env.root:
                gitops.stage(repo, args[0])
                raise gitops.GitOpsError("synthetic commit failure")
            return real(repo, *args, **kwargs)
        monkeypatch.setattr(gitops, "stage_and_commit", fail)
    with pytest.raises((reg.RegistrationError, gitops.GitOpsError)):
        register(env, path)
    assert path.is_dir() and not path.is_symlink()
    assert (path / "SKILL.md").read_bytes() == original
    assert not skill_registry.load(env.home).is_registered(NAME)
    if failure == "commit":
        assert env.marketplace.read_bytes() == market
        assert not env.plugin_dir().exists()
        assert not env.status(env.root)


def test_registered_reference_reorganization(env):
    seed(env)
    register(env)
    files = sk1.draft()
    files["references/new.md"] = "# New procedure\n\nUpdated reference.\n"
    files["SKILL.md"] = files["SKILL.md"].replace(sk1.REF, "references/new.md")
    del files[sk1.REF]
    result = skill_writer.write(env.home, NAME, files, case=None, by="human", no_push=True)
    assert result.ok, result
    assert (env.skill_dir() / "references/new.md").is_file()
    assert not (env.skill_dir() / sk1.REF).exists()
    assert skill_registry.load(env.home).is_registered(NAME)


def test_adopt_arbitrary_location_and_resolve_existing_link(env):
    path = seed(env, env.tmp / "loose" / NAME)
    result = register(env, path)
    assert result["adopted"] and path.is_symlink()
    assert path.resolve() == env.skill_dir()
    assert not env.link().exists()
    assert register(env, path)["state"] == "already registered"
    assert not env.link().exists()
    assert skill_writer.write(env.home, NAME, sk1.draft(), case=None, by="human", no_push=True).ok
    assert not env.link().exists() and path.resolve() == env.skill_dir()


def test_registered_stamp_is_not_stray_authorship(env):
    from self_learn import selfcheck
    seed(env)
    register(env)
    assert skill_writer.write(env.home, NAME, sk1.draft(), case=None, by="human", no_push=True).ok
    verdict, detail = selfcheck._check_owned_skills_registry(env.home, env.claude)
    assert verdict == selfcheck.Verdict.PASS, detail
    reg.unregister(env.home, NAME, note="withdraw", by="agent")
    verdict, detail = selfcheck._check_owned_skills_registry(env.home, env.claude)
    assert verdict == selfcheck.Verdict.PASS, detail


def test_in_place_plain_root_uses_plain_host_lock(env):
    import io
    from ruamel.yaml import YAML
    root = env.tmp / "plain-root"
    path = seed(env, root / "plugins" / NAME / "skills" / NAME)
    (root / ".self-learn-host").write_text("synthetic host marker")
    hosts = env.home / "hosts.yaml"
    data = YAML(typ="safe").load(hosts.read_text())
    data["skills_root"] = {"path": str(root), "mode": "plain"}
    stream = io.StringIO()
    YAML().dump(data, stream)
    hosts.write_text(stream.getvalue())
    commit_all(env.home, "plain root without git")
    assert not (root / ".git").exists()
    result = register(env, path)
    assert result["state"] == "registered" and not result["adopted"]
    assert skill_registry.load(env.home).may_edit(NAME)
    assert not skill_writer.write(env.home, NAME, sk1.draft(), case=None, by="human", no_push=True).ok


@pytest.mark.parametrize("verb", ["register", "unregister", "build", "change", "withdraw"])
def test_secret_notes_refused_without_echo(env, monkeypatch, capsys, verb):
    seed(env)
    register(env)
    row = skill_requests.file_request(env.home, "change", NAME, lessons=[], note="Review examples", by="agent")
    monkeypatch.setenv("CLAUDECODE", "1")
    bad = "Mention token: EXAMPLE_CREDENTIAL"
    args = {"register": ["register", NAME], "unregister": ["unregister", NAME],
        "build": ["request", "build", "--name", "new-example", "--lessons", sk1.RID],
        "change": ["request", "change", NAME], "withdraw": ["request", "withdraw", row["id"]]}[verb]
    before = env.head(env.home)
    assert cli.main(["skill", *args, "--note", bad]) != 0
    output = capsys.readouterr()
    assert "credential-assignment" in output.err
    assert "EXAMPLE_CREDENTIAL" not in output.err + output.out
    assert env.head(env.home) == before
    if verb == "withdraw":
        assert cli.main(["skill", "request", "withdraw", row["id"], "--note", "No longer useful"]) == 0
        closed = skill_requests.requests(env.home)[0]
        assert closed["answer"] == "withdrawn" and closed["state"] == "closed"
        assert closed["withdrawn_by"] == "agent" and closed["reason"] == "No longer useful"


@pytest.mark.parametrize("name,extra", [
    ("cron-claude", ""),
    ("web-research", "allowed-tools: [Read, Bash]\n"),
    ("wow-addon-management", "version: '2.3'\n")])
def test_registered_frontmatter_shapes_preserved(env, name, extra):
    # Synthetic shapes, deliberately no text copied from installed skills.
    files = sk1.draft(name=name, metadata={"owner": "user", "category": "examples"})
    files["SKILL.md"] = files["SKILL.md"].replace("---\n\n", extra + "---\n\n", 1)
    path = env.skill_dir(name)
    seed(env, path, text=files["SKILL.md"])
    register(env, path)
    before = _read_frontmatter(files["SKILL.md"]).mapping
    files["SKILL.md"] += "\nA clearer example.\n"
    result = skill_writer.write(env.home, name, files, case=None, by="human", no_push=True)
    assert result.ok, result
    after = _read_frontmatter(env.skill_md(name).read_text()).mapping
    for key, value in before.items():
        assert after[key] == value if key != "metadata" else all(after[key][k] == v for k, v in value.items())
    assert "registered_by" in after["metadata"]["self-learn"]
    # Description remains editable while opaque keys stay fixed.
    files["SKILL.md"] = files["SKILL.md"].replace(sk1.DESCRIPTION, "Use when reviewing the example procedure.")
    assert skill_writer.write(env.home, name, files, case=None, by="human", no_push=True).ok
    if extra:
        for changed in ("", extra.replace("2.3", "3.0").replace("Read, Bash", "Read")):
            bad = dict(files)
            bad["SKILL.md"] = bad["SKILL.md"].replace(extra, changed)
            result = skill_writer.check(env.home, name, bad)
            assert not result.ok and "frontmatter-carried-key-changed" in str(result.problems)
    bad = dict(files)
    bad["SKILL.md"] = bad["SKILL.md"].replace("---\n\n", "model: large\n---\n\n", 1)
    assert not skill_writer.check(env.home, name, bad).ok


def test_registration_unfixable_frontmatter_rule(env):
    path = seed(env, text=sk1.draft()["SKILL.md"].replace("---\n\n", "metadata: scalar\n---\n\n", 1))
    with pytest.raises(reg.RegistrationError, match="metadata-not-mapping"):
        register(env, path)


@pytest.mark.parametrize("failure", ["index", "partial-move", "link-once", "link-always"])
def test_adoption_failure_recovery(env, monkeypatch, failure):
    from self_learn import gitops
    path = seed(env, env.claude / "skills" / NAME)
    original = (path / "SKILL.md").read_bytes()
    market = env.marketplace.read_bytes()
    real_link = skill_writer._place_link
    attempts = []
    if failure == "index":
        (env.root / ".git" / "index.lock").write_text("test lock")
    elif failure == "partial-move":
        def partial_move(source, destination):
            import shutil
            shutil.copytree(source, destination)
            (Path(source) / "SKILL.md").unlink()
            raise OSError("partial cross-device move")
        monkeypatch.setattr(reg.shutil, "move", partial_move)
    else:
        def link(link, target):
            attempts.append(link)
            if failure == "link-always" or len(attempts) == 1:
                raise OSError("link unavailable")
            return real_link(link, target)
        monkeypatch.setattr(skill_writer, "_place_link", link)
    if failure == "link-once":
        assert register(env, path)["state"] == "registered"
        assert len(attempts) == 2 and path.is_symlink()
    else:
        with pytest.raises(reg.RegistrationError, match="backup:") as error:
            register(env, path)
        if failure == "link-always":
            assert str(path) in str(error.value) and "repair link" in str(error.value)
            monkeypatch.setattr(skill_writer, "_place_link", real_link)
            assert register(env)["state"] == "registered"
            assert path.is_symlink()
        else:
            assert path.is_dir() and not path.is_symlink()
            assert (path / "SKILL.md").read_bytes() == original
            assert not env.plugin_dir().exists()
            assert env.marketplace.read_bytes() == market
            backups = list((env.tmp / "xdg-cache").rglob("skill-adoptions/*"))
            assert backups and (backups[0] / "SKILL.md").read_bytes() == original


def test_reregister_repairs_link_and_moved_root_advice(env):
    seed(env)
    register(env)
    assert env.link().is_symlink()
    env.link().unlink()
    assert register(env)["state"] == "already registered"
    assert env.link().resolve() == env.skill_dir()
    def moved(registry):
        registry.registrations[NAME]["registered"]["path"] = str(env.tmp / "old-root" / NAME)
    skill_registry.with_update(env.home, moved, subject="synthetic moved root")
    with pytest.raises(reg.RegistrationError, match="unregister and register again"):
        register(env)
    result = skill_writer.check(env.home, NAME, sk1.draft())
    assert not result.ok and "unregister and register again" in str(result.problems)


def test_withdrawn_history_allows_owned_creation(env, monkeypatch):
    import shutil
    seed(env)
    register(env)
    reg.unregister(env.home, NAME, note="Replace this obsolete skill", by="human")
    env.link().unlink()
    shutil.rmtree(env.plugin_dir())
    commit_all(env.root, "remove obsolete skill")
    from self_learn import gitops
    real_deploy = skill_writer._deploy
    def failed_deploy(*args, **kwargs):
        raise gitops.GitOpsError("synthetic host failure")
    monkeypatch.setattr(skill_writer, "_deploy", failed_deploy)
    failed = env.write()
    assert not failed.ok
    restored = skill_registry.load(env.home)
    assert not restored.is_owned(NAME)
    assert restored.registrations[NAME]["status"] == "withdrawn"
    monkeypatch.setattr(skill_writer, "_deploy", real_deploy)
    result = env.write()
    assert result.ok, result
    registry = skill_registry.load(env.home)
    assert registry.is_owned(NAME) and not registry.is_registered(NAME)
    assert registry.registrations[NAME]["status"] == "withdrawn"
    assert "created" in registry.row(NAME)


def test_build_names_and_duplicate_requests(env):
    import test_overseer_skill_build as build
    build._lesson(env, sk1.RID)
    seed(env)
    register(env)
    creation = skill_writer.check(env.home, NAME, sk1.draft(), updating=False)
    assert not creation.ok and "already registered" in str(creation.problems)
    with pytest.raises(ValueError, match="already registered"):
        skill_requests.file_request(env.home, "build", NAME, lessons=[sk1.RID], note="Build it", by="agent")
    with pytest.raises(ValueError, match="name-reserved-word"):
        skill_requests.file_request(env.home, "build", "cron-claude", lessons=[sk1.RID], note="Build it", by="agent")
    first = skill_requests.file_request(env.home, "build", "new-example", lessons=[sk1.RID], note="First reason", by="agent")
    second = skill_requests.file_request(env.home, "build", "new-example", lessons=[sk1.RID], note="Another reason", by="human")
    assert first["id"] == second["id"]
    rows = skill_requests.requests(env.home)
    assert len(rows) == 1 and rows[0]["followups"][0]["note"] == "Another reason"


def test_registered_mixed_routes_share_managed_section(env):
    from self_learn import verbs
    import test_overseer_skill_build as build
    seed(env)
    register(env)
    create_record(env.home, make_behavior(scope="skill:" + NAME, record_id=sk1.RID))
    commit_all(env.home, "seed skill scoped lesson")
    build._lesson(env, sk1.RID2)
    assert skill_writer.write(env.home, NAME, sk1.draft(), case=None, by="human", no_push=True).ok
    assert verbs.route(env.home, sk1.RID, dest="skill-md", no_push=True)
    assert verbs.route(env.home, sk1.RID2, dest=f"new-skill:{NAME}", no_push=True)
    assert sk1.RID in env.skill_md().read_text() and sk1.RID2 in env.skill_md().read_text()
    third = "lrn-0000cccc"
    create_record(env.home, make_behavior(scope="skill:" + NAME, record_id=third))
    commit_all(env.home, "seed another skill scoped lesson")
    assert verbs.route(env.home, third, dest="skill-md", no_push=True)
    text = env.skill_md().read_text()
    assert sk1.RID in text and sk1.RID2 in text
    assert text.count("<!-- self-learn:begin") == 1
    assert set(skill_writer.routed_lessons(env.home, NAME)) == {sk1.RID, sk1.RID2, third}


def test_writer_registry_refusal_is_not_retryable_git(env, monkeypatch):
    def invalid(*args, **kwargs):
        raise skill_registry.SkillRegistryError("invalid ownership state")
    monkeypatch.setattr(skill_writer, "_write_locked", invalid)
    result = env.write()
    assert not result.ok and result.kind == skill_writer.KIND_BAD_LINE


@pytest.mark.parametrize("description", ["", "description: ''\n", "description: [fix, later]\n"])
def test_registration_accepts_rewrite_fixable_description(env, description):
    path = seed(env, env.claude / "skills" / NAME,
        text="---\nname: mouse-care\n" + description + "---\n\n# User procedure\n")
    before = (path / "SKILL.md").read_bytes()
    result = register(env, path)
    assert result["adopted"]
    assert env.skill_md().read_bytes() == before
    assert skill_writer.write(env.home, NAME, sk1.draft(), case=None, by="human", no_push=True).ok
    assert _read_frontmatter(env.skill_md().read_text()).mapping["description"] == sk1.DESCRIPTION
