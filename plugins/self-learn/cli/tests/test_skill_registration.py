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


@pytest.mark.parametrize("bad", ["missing", "frontmatter", "name", "description", "note", "owned", "veto"])
def test_input_refusals(env, bad):
    path = seed(env)
    if bad == "missing":
        (path / "SKILL.md").unlink()
    if bad == "frontmatter":
        (path / "SKILL.md").write_text("no frontmatter")
    if bad == "name":
        (path / "SKILL.md").write_text(sk1.draft("other-name")["SKILL.md"])
    if bad == "description":
        (path / "SKILL.md").write_text("---\nname: mouse-care\n---\n")
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
    assert result["adopted"] and path.is_symlink() and env.link().is_symlink()
    assert env.link().resolve() == path.resolve() == env.skill_dir()
    assert register(env, env.link())["state"] == "already registered"


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
