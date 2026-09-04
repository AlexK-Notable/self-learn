"""U-pointer: the reachability emitter (docs/specs/self-learn/drafts/
u-pointer-reachability-emitter-spec.md, r3 + builder's r3-a/r3-b/r3-c/r3-d
NIT fold).

Test names embed the spec's §8 test ids (T-SKILL-*, T-CMD-*, T-RULES-*,
T-HOOK-*, T-ROW-*, T-DOMAIN-*, T-RENDER-*, T-REFUSE, T-FACET,
T-ONE-PREDICATE, T-EMPTY-DOMAIN, T-SELFTEST-ROW, T-NO-WRITES,
T-NO-REAL-HOME, T-INSTRUMENT) so the mutation sweep (§10) can find its
target directly.

Every test sets ``SELF_LEARN_CLAUDE_DIR`` explicitly (via
``make_claude_dir``/``missing_claude_dir``) — ``conftest.py`` points it at
``tmp_path / "claude-dir-default"`` by default, a directory that is never
created, so a fixture that forgets to override it is silently exercising
the ``claude-dir-absent`` leg."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from self_learn import report, selfcheck
from self_learn.hook_compiler import generate_script, script_name
from self_learn.reachability import (
    Instrument,
    Verdict,
    read_instrument,
    reachability_rows,
)
from self_learn.records import Record
from self_learn.verbs import _project_rules_dir, _user_rules_dir

from support import init_repo, make_behavior, make_env, make_knowledge

# ============================================================== fixtures


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def make_claude_dir(
    tmp_path: Path,
    monkeypatch,
    *,
    settings: dict | str | None = ...,
    skills: dict[str, Path] | None = None,
    hooks: dict[str, Path] | None = None,
    marketplaces: dict[str, Path] | None = None,
    name: str = "claude-dir",
) -> Path:
    """§8's shared instrument builder. ``settings=None`` writes no file
    (``settings-absent``); a ``str`` is written raw (the unparseable
    fixture); a ``dict`` is JSON-dumped. The ``...`` default (r1 N8) means
    "write a minimal valid ``{}``" — distinct from ``None``."""
    claude = tmp_path / name
    claude.mkdir(parents=True, exist_ok=True)
    if settings is ...:
        (claude / "settings.json").write_text("{}", encoding="utf-8")
    elif isinstance(settings, str):
        (claude / "settings.json").write_text(settings, encoding="utf-8")
    elif isinstance(settings, dict):
        (claude / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    # settings is None -> write nothing -> settings-absent
    if skills:
        skills_dir = claude / "skills"
        skills_dir.mkdir(exist_ok=True)
        for skill_name, target in skills.items():
            link = skills_dir / skill_name
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target)
    if hooks:
        hooks_dir = claude / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        for hook_name, target in hooks.items():
            link = hooks_dir / hook_name
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target)
    if marketplaces:
        plugins_dir = claude / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        data = {mkt: {"installLocation": str(loc)} for mkt, loc in marketplaces.items()}
        (plugins_dir / "known_marketplaces.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    return claude


def missing_claude_dir(tmp_path: Path, monkeypatch, *, name: str = "claude-dir-absent") -> Path:
    claude = tmp_path / name
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    assert not claude.exists()
    return claude


def write_marketplace_json(install_dir: Path, plugins: list[dict]) -> None:
    d = install_dir / ".claude-plugin"
    d.mkdir(parents=True, exist_ok=True)
    (d / "marketplace.json").write_text(json.dumps({"plugins": plugins}), encoding="utf-8")


def write_settings_hooks(claude_dir: Path, registrations: list[tuple[str, str, str]]) -> None:
    hooks_cfg: dict[str, list] = {}
    for event, matcher, command in registrations:
        hooks_cfg.setdefault(event, []).append(
            {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
        )
    (claude_dir / "settings.json").write_text(
        json.dumps({"hooks": hooks_cfg}), encoding="utf-8"
    )


def _bad_utf8(prefix: str = "") -> bytes:
    return prefix.encode("utf-8") + b"\xff\xfe garbage"


# ------------------------------------------------------ record builders


def _route(record: Record, destination: str, **extra) -> None:
    routing = {"routed_at": "2026-08-09T00:00:00Z", "destination": destination, "by": "human"}
    routing.update(extra)
    record.set_routing(routing)
    record.set_status("routed")


def _write_resolved(ledger: Path, bucket_rel: str, record: Record) -> Path:
    resolved = ledger / bucket_rel / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    path = resolved / f"{record.id}.md"
    record.write(path)
    return path


def route_skill_md(env, *, name: str = "s", record_id: str | None = None) -> Record:
    record = make_behavior(scope=f"skill:{name}", record_id=record_id)
    _route(record, "skill-md")
    path = _write_resolved(env.ledger, f"skills/{name}", record)
    return Record.from_path(path)


def ensure_skill_md_dir_without_file(env, name: str) -> None:
    d = env.host / "plugins" / f"{name}-plugin" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)


def ensure_new_skill_target(env, name: str) -> Path:
    d = env.host / "plugins" / name / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    target = d / "SKILL.md"
    if not target.is_file():
        target.write_text(f"# {name} skill\n", encoding="utf-8")
    return target


def route_new_skill(
    env, *, owner: str = "s", new_name: str = "probe", record_id: str | None = None,
    create_target: bool = True,
) -> Record:
    if create_target:
        ensure_new_skill_target(env, new_name)
    record = make_behavior(scope=f"skill:{owner}", record_id=record_id)
    _route(record, "new-skill", new_skill=new_name)
    path = _write_resolved(env.ledger, f"skills/{owner}", record)
    return Record.from_path(path)


def route_cmd_user(env, *, record_id: str | None = None) -> Record:
    record = make_knowledge(scope="user", record_id=record_id)
    _route(record, "claude-md")
    path = _write_resolved(env.ledger, "user", record)
    return Record.from_path(path)


def project_bucket(env, *, slug: str = "proj") -> Path:
    bucket_dir = env.ledger / "projects" / slug
    bucket_dir.mkdir(parents=True, exist_ok=True)
    (bucket_dir / "meta.yaml").write_text(f"path: {env.host}\n", encoding="utf-8")
    return bucket_dir


def route_cmd_project(
    env, *, slug: str = "proj", record_id: str | None = None, variant: str | None = None
) -> Record:
    record = make_knowledge(scope="project", record_id=record_id)
    extra = {}
    if variant is not None:
        extra["variant"] = variant
    _route(record, "claude-md", **extra)
    bucket_dir = project_bucket(env, slug=slug)
    resolved = bucket_dir / "resolved"
    resolved.mkdir(exist_ok=True)
    record.write(resolved / f"{record.id}.md")
    return Record.from_path(resolved / f"{record.id}.md")


def route_rules_user(
    env, *, topic: str = "t", record_id: str | None = None,
    rules_paths: tuple[str, ...] = ("**/*.md",), allow_empty_glob: bool = False,
    glob_bypass_reason: str | None = None,
) -> Record:
    record = make_knowledge(scope="user", record_id=record_id)
    extra: dict = {"variant": "rules", "rules_topic": topic, "rules_paths": list(rules_paths)}
    if allow_empty_glob:
        extra["allow_empty_glob"] = True
    if glob_bypass_reason is not None:
        extra["glob_bypass_reason"] = glob_bypass_reason
    _route(record, "claude-md", **extra)
    path = _write_resolved(env.ledger, "user", record)
    return Record.from_path(path)


def route_rules_project(
    env, *, slug: str = "proj", topic: str = "t", record_id: str | None = None,
    rules_paths: tuple[str, ...] = ("**/*.md",), allow_empty_glob: bool = False,
    glob_bypass_reason: str | None = None,
) -> Record:
    record = make_knowledge(scope="project", record_id=record_id)
    extra: dict = {"variant": "rules", "rules_topic": topic, "rules_paths": list(rules_paths)}
    if allow_empty_glob:
        extra["allow_empty_glob"] = True
    if glob_bypass_reason is not None:
        extra["glob_bypass_reason"] = glob_bypass_reason
    _route(record, "claude-md", **extra)
    bucket_dir = project_bucket(env, slug=slug)
    resolved = bucket_dir / "resolved"
    resolved.mkdir(exist_ok=True)
    record.write(resolved / f"{record.id}.md")
    return Record.from_path(resolved / f"{record.id}.md")


def write_rules_file(path: Path, *, paths: list[str] | None = None, body: str = "# Rule\ncontent\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if paths is None:
        text = body
    else:
        paths_yaml = "\n".join(f'  - "{p}"' for p in paths)
        text = f"---\npaths:\n{paths_yaml}\n---\n\n{body}"
    path.write_text(text, encoding="utf-8")


def route_hook(
    env, *, owner: str = "s", rid: str = "lrn-0a1b2c3d",
    trigger: str = "About to edit .storage while HA is running.",
    tools: tuple[str, ...] = ("Bash",), path_regex: str = r"\.storage/",
    deny_message: str = "stop the container first", write_script: bool = True,
) -> tuple[Record, Path]:
    script_bytes = generate_script(rid, trigger, list(tools), path_regex, deny_message)
    name = script_name(rid, trigger)
    rel = f"plugins/{owner}-plugin/hooks/{name}"
    record = make_behavior(scope=f"skill:{owner}", record_id=rid, trigger=trigger)
    _route(
        record, "hook",
        hook={
            "tools": list(tools), "path_regex": path_regex, "deny_message": deny_message,
            "script_path": rel, "script": script_bytes,
        },
    )
    path = _write_resolved(env.ledger, f"skills/{owner}", record)
    script = env.host / rel
    if write_script:
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(script_bytes, encoding="utf-8")
        script.chmod(0o755)
    return Record.from_path(path), script


def _only(rows):
    assert len(rows) == 1, [r.record_id for r in rows]
    return rows[0]


def _find(rows, record_id: str) -> Verdict:
    for r in rows:
        if r.record_id == record_id:
            return r
    raise AssertionError(f"{record_id} not in {[r.record_id for r in rows]}")


# ==================================================== blind-fixture set


def test_skill_blind(env, tmp_path, monkeypatch):
    """T-SKILL-BLIND."""
    route_skill_md(env)
    claude_dir = missing_claude_dir(tmp_path, monkeypatch)
    assert env.skill_md.is_file()  # the compiled target IS present
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "claude-dir-absent"


def test_cmd_blind(env, tmp_path, monkeypatch):
    """T-CMD-BLIND: never target-missing — the §5.2 row ordering is what
    this pins."""
    route_cmd_user(env)
    claude_dir = missing_claude_dir(tmp_path, monkeypatch)
    target = claude_dir / "CLAUDE.md"
    assert not claude_dir.exists()
    assert not target.exists()
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "claude-dir-absent"


def test_rules_blind(env, tmp_path, monkeypatch):
    """T-RULES-BLIND: never target-missing."""
    route_rules_user(env)
    claude_dir = missing_claude_dir(tmp_path, monkeypatch)
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "t.md"
    assert not claude_dir.exists()
    assert not target.exists()
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "claude-dir-absent"


def test_hook_blind(env, tmp_path, monkeypatch):
    """T-HOOK-BLIND."""
    _, script = route_hook(env)
    claude_dir = missing_claude_dir(tmp_path, monkeypatch)
    assert script.is_file()
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "claude-dir-absent"


def test_row_blind(env, tmp_path, monkeypatch):
    """T-ROW-BLIND — the single most important test in the unit."""
    route_skill_md(env)
    route_cmd_user(env, record_id="lrn-c0000001")
    route_rules_user(env, record_id="lrn-c0000002", topic="rb")
    route_hook(env, rid="lrn-c0000003")
    claude_dir = missing_claude_dir(tmp_path, monkeypatch)

    ok, msg = selfcheck._check_surface(env.ledger, claude_dir)
    assert ok
    assert "0 of 4 verified reachable" in msg
    assert "4 UNMEASURABLE" in msg
    assert "claude-dir-absent" in msg
    assert str(claude_dir) in msg
    assert "UNREACHABLE" not in msg
    assert "4 record(s) reachable" not in msg


def test_row_mixed(env, tmp_path, monkeypatch):
    """T-ROW-MIXED: pinned to a NON-instrument unmeasurable reason
    (target-missing), never claude-dir-absent."""
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    (claude_dir / "CLAUDE.md").write_text("# user canon\n", encoding="utf-8")
    route_cmd_project(env, record_id="lrn-d0000001")
    route_cmd_user(env, record_id="lrn-d0000002")
    ensure_skill_md_dir_without_file(env, "missing1")
    route_skill_md(env, name="missing1", record_id="lrn-d0000003")
    ensure_skill_md_dir_without_file(env, "missing2")
    route_skill_md(env, name="missing2", record_id="lrn-d0000004")

    ok, msg = selfcheck._check_surface(env.ledger, claude_dir)
    assert ok
    assert "2 of 4 verified reachable" in msg
    assert "2 UNMEASURABLE" in msg
    assert "target-missing" in msg
    assert str(claude_dir) not in msg
    assert "claude-dir-absent" not in msg

    user_row = _find(reachability_rows(env.ledger, claude_dir), "lrn-d0000002")
    assert user_row.state == "reachable"
    assert user_row.reason == "user-memory-file"
    assert user_row.target == str((claude_dir / "CLAUDE.md").resolve())


# ============================================================ RP-SKILL


def test_skill_1_personal_symlink(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={}, skills={"s": env.skill_dir})
    route_skill_md(env)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "personal-skill-link"


def test_skill_2_override_wins_over_symlink(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"skillOverrides": {"s": "off"}},
        skills={"s": env.skill_dir},
    )
    route_skill_md(env)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "skill-override-off"


def test_skill_3_dangling_symlink(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    (claude_dir / "skills").mkdir()
    (claude_dir / "skills" / "s").symlink_to(tmp_path / "does-not-exist-anywhere")
    route_skill_md(env)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "not-indexed"


def test_skill_4_plugin_disabled(env, tmp_path, monkeypatch):
    name = "t4"
    route_new_skill(env, new_name=name)
    write_marketplace_json(env.host, [{"name": name, "source": f"./plugins/{name}"}])
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"enabledPlugins": {f"{name}@mkt": False}},
        marketplaces={"mkt": env.host},
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "plugin-disabled"


def test_skill_4b_source_dot_shape(env, tmp_path, monkeypatch):
    """The live `znote@nsys-marketplace` layout: plugin root IS the
    marketplace root; kills a formula hard-coding `plugins/`."""
    name = "t4b"
    route_new_skill(env, new_name=name)
    install_dir = env.host / "plugins" / name  # == the computed plugin_root
    write_marketplace_json(install_dir, [{"name": name, "source": "./"}])
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"enabledPlugins": {f"{name}@mkt": True}},
        marketplaces={"mkt": install_dir},
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "enabled-plugin"


def test_skill_5_undecidable_no_symlink(env, tmp_path, monkeypatch):
    name = "t5"
    route_new_skill(env, new_name=name)
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"enabledPlugins": {f"{name}@ghost-mkt": True}},
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "plugin-route-undecidable"


def test_skill_5b_undecidable_but_personal_symlink_wins(env, tmp_path, monkeypatch):
    name = "t5b"
    route_new_skill(env, new_name=name)
    target_dir = env.host / "plugins" / name / "skills" / name
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"enabledPlugins": {f"{name}@ghost-mkt": True}},
        skills={name: target_dir},
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "personal-skill-link"


def test_skill_5c_undecidable_out_of_scope_not_indexed(env, tmp_path, monkeypatch):
    """r2 BLOCKER, the test r2 lacked: the live-host shape — an
    undecidable entry that is OUT OF SCOPE for this target."""
    name = "t5c"
    route_new_skill(env, new_name=name)
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"enabledPlugins": {"otherplugin@ghost-mkt": True}},
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "not-indexed"


def test_skill_5d_leg1_in_scope_by_name(env, tmp_path, monkeypatch):
    name = "t5d1"
    route_new_skill(env, new_name=name)
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"enabledPlugins": {f"{name}@ghost-mkt": True}},
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "plugin-route-undecidable"


def test_skill_5d_leg2_in_scope_by_ancestor_installlocation(env, tmp_path, monkeypatch):
    """r3-c NIT: the OTHER §5.1A′ disjunct — plugin name does not match,
    but the marketplace's installLocation IS an ancestor of `target`. No
    `.claude-plugin/marketplace.json` under `env.host` -> undecidable at
    step 2, but in scope via the ancestor rule."""
    name = "t5d2"
    route_new_skill(env, new_name=name)
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={"enabledPlugins": {"otherplugin@anc-mkt": True}},
        marketplaces={"anc-mkt": env.host},
    )
    assert not (env.host / ".claude-plugin" / "marketplace.json").exists()
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "plugin-route-undecidable"


def test_skill_6_new_skill_leg_fixed_formula(env, tmp_path, monkeypatch):
    name = "t6"
    route_new_skill(env, new_name=name)
    target_dir = env.host / "plugins" / name / "skills" / name
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={}, skills={name: target_dir})
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "personal-skill-link"
    assert row.target == str((target_dir / "SKILL.md").resolve())


def test_skill_6b_skill_md_leg_uses_glob_not_formula(env, tmp_path, monkeypatch):
    """r3-a NIT (M6h): the skill-md leg resolves via `skill_dir_for`'s
    GLOB, never the new-skill fixed formula — `support.py`'s sandbox
    layout (`plugins/<n>-plugin/skills/<n>`) is exactly the shape where
    the two legs diverge."""
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={}, skills={"s": env.skill_dir})
    route_skill_md(env, name="s")
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "personal-skill-link"
    glob_target = str(env.skill_md.resolve())
    fixed_formula_target = str(env.host / "plugins" / "s" / "skills" / "s" / "SKILL.md")
    assert row.target == glob_target
    assert row.target != fixed_formula_target


def test_skill_7_target_missing(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    ensure_skill_md_dir_without_file(env, "t7")
    route_skill_md(env, name="t7")
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "target-missing"


def test_skill_8_namespaced_override(env, tmp_path, monkeypatch):
    name = "t8"
    route_new_skill(env, new_name=name)
    write_marketplace_json(env.host, [{"name": name, "source": f"./plugins/{name}"}])
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch,
        settings={
            "enabledPlugins": {f"{name}@mkt": True},
            "skillOverrides": {f"{name}:{name}": "off"},
        },
        marketplaces={"mkt": env.host},
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "skill-override-off"


# ============================================================= RP-CMD


def test_cmd_1_user_reachable(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    (claude_dir / "CLAUDE.md").write_text("# user canon\n", encoding="utf-8")
    route_cmd_user(env)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "user-memory-file"
    assert row.target == str((claude_dir / "CLAUDE.md").resolve())


def test_cmd_3_project_root(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_cmd_project(env)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "project-root-memory-file"
    assert "does NOT prove" in row.detail and "cwd" in row.detail


def test_cmd_4_local_variant(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    (env.host / "CLAUDE.local.md").write_text("# local\n", encoding="utf-8")
    route_cmd_project(env, variant="local")
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "project-local-memory-file"
    assert "git-excluded" in row.detail


def test_cmd_5_host_missing(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_cmd_project(env)
    shutil.rmtree(env.host)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "host-missing"


# =========================================================== RP-RULES


def test_rules_1_globs_match(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="r1", rules_paths=("hit-r1/*.md",))
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "r1.md"
    write_rules_file(target, paths=["hit-r1/*.md"])
    (claude_dir.parent / "hit-r1").mkdir(parents=True, exist_ok=True)
    (claude_dir.parent / "hit-r1" / "x.md").write_text("x\n", encoding="utf-8")
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "globs-match"


def test_rules_2_globs_match_nothing(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="r2", rules_paths=("no-such-dir-r2/*.md",))
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "r2.md"
    write_rules_file(target, paths=["no-such-dir-r2/*.md"])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "globs-match-nothing"


def test_rules_3_no_frontmatter_loads_unconditionally(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="r3")
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "r3.md"
    write_rules_file(target, paths=None)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "loads-unconditionally"
    assert "session_start" in row.detail


def test_rules_disk_mutation_catcher(env, tmp_path, monkeypatch):
    """T-RULES-DISK: reads the FILE's own frontmatter, never
    `routing.rules_paths`."""
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="rdisk", rules_paths=("**/*.md",))
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "rdisk.md"
    write_rules_file(target, paths=["**/no-such-file-zzqx-*.xyz"])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "globs-match-nothing"


def test_rules_4_frontmatter_drift_reported_not_promoted(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="r4", rules_paths=("ledger-list-r4/*.md",))
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "r4.md"
    write_rules_file(target, paths=["disk-list-r4/*.md"])
    (claude_dir.parent / "disk-list-r4").mkdir(parents=True, exist_ok=True)
    (claude_dir.parent / "disk-list-r4" / "x.md").write_text("x\n", encoding="utf-8")
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "globs-match"
    assert "disk-list-r4" in row.detail and "ledger-list-r4" in row.detail


def test_rules_5_dir_off_loaded_path(env, tmp_path, monkeypatch):
    """A `rules_topic` containing a path-traversal segment escapes the
    scanned rules directory even though `managed_target_for`'s formula
    was followed literally — the shape §5.3 step 2 exists to catch."""
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="../escaped-t-rules-5")
    target = claude_dir / "escaped-t-rules-5.md"
    write_rules_file(target, paths=None)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "rules-dir-off-loaded-path"


def test_rules_6_undecodable(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="r6")
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "r6.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_bad_utf8("---\npaths:\n"))
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "frontmatter-unreadable"


def test_rules_7_budget_not_none(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="r7", rules_paths=("anything/*.md",))
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "r7.md"
    write_rules_file(target, paths=["anything/*.md"])
    monkeypatch.setattr(
        "self_learn.reachability.glob_reaches", lambda *a, **k: "budget"
    )
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "glob-budget-exhausted"


def test_rules_bypass_three_legs(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})

    # leg 1: zero-match bypass -> reachable/bypass-approved.
    route_rules_user(env, topic="rb1", rules_paths=("nowhere-rb1/*.md",), glob_bypass_reason="zero-match")
    t1 = _user_rules_dir(claude_dir / "CLAUDE.md") / "rb1.md"
    write_rules_file(t1, paths=["nowhere-rb1/*.md"])

    # leg 2: legacy allow_empty_glob, no glob_bypass_reason key.
    route_rules_user(env, topic="rb2", rules_paths=("nowhere-rb2/*.md",), allow_empty_glob=True)
    t2 = _user_rules_dir(claude_dir / "CLAUDE.md") / "rb2.md"
    write_rules_file(t2, paths=["nowhere-rb2/*.md"])

    # leg 3: budget bypass -> NOT exempt.
    route_rules_user(env, topic="rb3", rules_paths=("nowhere-rb3/*.md",), glob_bypass_reason="budget")
    t3 = _user_rules_dir(claude_dir / "CLAUDE.md") / "rb3.md"
    write_rules_file(t3, paths=["nowhere-rb3/*.md"])

    rows = reachability_rows(env.ledger, claude_dir)
    by_topic = {r.target: r for r in rows}
    leg1 = by_topic[str(t1.resolve())]
    leg2 = by_topic[str(t2.resolve())]
    leg3 = by_topic[str(t3.resolve())]
    assert leg1.state == "reachable" and leg1.reason == "bypass-approved"
    assert leg2.state == "reachable" and leg2.reason == "bypass-approved"
    assert leg3.state == "unreachable" and leg3.reason == "globs-match-nothing"


def test_rules_roots_threaded_stays_under_tmp_path(env, tmp_path, monkeypatch):
    """Guards B1's third threading site: unthreaded, `_user_reachability_
    roots` walks the operator's real `$HOME`."""
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_rules_user(env, topic="rroots", rules_paths=("hit-rroots/*.md",))
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "rroots.md"
    write_rules_file(target, paths=["hit-rroots/*.md"])
    (claude_dir.parent / "hit-rroots").mkdir(parents=True, exist_ok=True)
    (claude_dir.parent / "hit-rroots" / "x.md").write_text("x\n", encoding="utf-8")

    captured: list[tuple] = []
    real = __import__("self_learn.reachability", fromlist=["glob_reaches"]).glob_reaches

    def spy(roots, pattern, **kw):
        captured.append(roots)
        return real(roots, pattern, **kw)

    monkeypatch.setattr("self_learn.reachability.glob_reaches", spy)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "globs-match"
    assert captured, "glob_reaches was never called"
    for roots in captured:
        for r in roots:
            assert str(r).startswith(str(tmp_path)), r


# ============================================================ RP-HOOK


def test_hook_1_registered(env, tmp_path, monkeypatch):
    record, script = route_hook(env)
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    write_settings_hooks(claude_dir, [("PreToolUse", "Bash", str(script))])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"
    assert row.reason == "registered"


def test_hook_unreg_two_sided(env, tmp_path, monkeypatch):
    record, script = route_hook(env)
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    # A DIFFERENT registered command -- foreign to _check_hooks, and
    # never matches OUR script's basename.
    write_settings_hooks(claude_dir, [("PreToolUse", "Edit", "$HOME/.claude/hooks/organizer-guard.sh")])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "not-registered"
    ok, _reason = selfcheck._check_hooks(env.ledger, claude_dir)
    assert ok is True


def test_hook_2_wrong_event(env, tmp_path, monkeypatch):
    record, script = route_hook(env)
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    write_settings_hooks(claude_dir, [("PostToolUse", "Bash", str(script))])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "wrong-event"


def test_hook_3_matcher_mismatch(env, tmp_path, monkeypatch):
    record, script = route_hook(env, tools=("Bash", "Edit"))
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    write_settings_hooks(claude_dir, [("PreToolUse", "Bash", str(script))])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "matcher-mismatch"


def test_hook_4_matcher_unparseable(env, tmp_path, monkeypatch):
    record, script = route_hook(env)
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    write_settings_hooks(claude_dir, [("PreToolUse", "[", str(script))])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "matcher-unparseable"


def test_hook_5_matcher_empty_and_star(env, tmp_path, monkeypatch):
    record, script = route_hook(env, tools=("Bash", "Edit"))
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    write_settings_hooks(claude_dir, [("PreToolUse", "", str(script))])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"

    write_settings_hooks(claude_dir, [("PreToolUse", "*", str(script))])
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "reachable"


def test_hook_broken_settings_fails_row(env, tmp_path, monkeypatch):
    record, script = route_hook(env)
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings="{")
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unmeasurable"
    assert row.reason == "settings-unparseable"
    ok, _msg = selfcheck._check_surface(env.ledger, claude_dir)
    assert ok is False


def test_hook_6_no_registrations(env, tmp_path, monkeypatch):
    record, script = route_hook(env)
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings=None)
    row = _only(reachability_rows(env.ledger, claude_dir))
    assert row.state == "unreachable"
    assert row.reason == "no-registrations"


# ============================================== domain, instrument, renderers


def test_domain_user_bucket_counted(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_cmd_user(env)
    rows = reachability_rows(env.ledger, claude_dir)
    assert len(rows) == 1


def test_domain_exclude_reference(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_skill_md(env, record_id="lrn-e0000001")
    ref = make_behavior(scope="skill:s", record_id="lrn-e0000002")
    _route(ref, "reference")
    _write_resolved(env.ledger, "skills/s", ref)
    rows = reachability_rows(env.ledger, claude_dir)
    assert len(rows) == 1
    assert all(r.record_id != "lrn-e0000002" for r in rows)


def test_domain_superseded_excluded(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    record = make_behavior(scope="skill:s", record_id="lrn-e0000003")
    record.set_routing({"routed_at": "2026-08-09T00:00:00Z", "destination": "skill-md", "by": "human"})
    record.set_status("superseded")
    record.set_superseded_by("lrn-deadbeef")
    _write_resolved(env.ledger, "skills/s", record)
    rows = reachability_rows(env.ledger, claude_dir)
    assert len(rows) == 0


def test_domain_unparseable_skipped_and_counted(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_skill_md(env, record_id="lrn-e0000004")
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    (resolved / "lrn-0badbeef.md").write_bytes(_bad_utf8("---\ntype: knowledge\n"))
    rows = reachability_rows(env.ledger, claude_dir)  # must not raise
    assert len(rows) == 1
    assert getattr(rows, "unparseable_records", None) == 1


def test_instrument_four_states(tmp_path):
    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    (ok_dir / "settings.json").write_text("{}", encoding="utf-8")
    inst = read_instrument(ok_dir)
    assert inst.state == "ok"
    assert (inst.claude_dir_usable, inst.settings_usable) == (True, True)

    absent_settings_dir = tmp_path / "settings-absent"
    absent_settings_dir.mkdir()
    inst = read_instrument(absent_settings_dir)
    assert inst.state == "settings-absent"
    assert (inst.claude_dir_usable, inst.settings_usable) == (True, True)

    missing_dir = tmp_path / "missing"
    inst = read_instrument(missing_dir)
    assert inst.state == "claude-dir-absent"
    assert (inst.claude_dir_usable, inst.settings_usable) == (False, False)

    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    (broken_dir / "settings.json").write_text("{", encoding="utf-8")
    inst = read_instrument(broken_dir)
    assert inst.state == "settings-unparseable"
    assert (inst.claude_dir_usable, inst.settings_usable) == (True, False)


def test_render_null_three_legs(env, tmp_path, monkeypatch):
    # leg 1: claude_dir_usable False -> everything null.
    route_skill_md(env, record_id="lrn-f0000001")
    claude_dir = missing_claude_dir(tmp_path, monkeypatch, name="null-leg1")
    facts = report._surface_reach(env.ledger, claude_dir)
    assert facts["reachable"] is None and facts["unreachable"] is None
    for key, counts in facts["by_destination"].items():
        assert counts["reachable"] is None, key
    text = report.render_text(report.gather(env.ledger, claude_dir=claude_dir))
    assert "NOT MEASURED" in text


def test_render_null_leg2_settings_broken_claude_md_survives(tmp_path, monkeypatch):
    env2 = make_env(tmp_path / "leg2-sandbox")
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings="{", name="leg2-claude")
    route_cmd_project(env2)
    route_skill_md(env2, record_id="lrn-f0000002")
    facts = report._surface_reach(env2.ledger, claude_dir)
    assert facts["by_destination"]["skill-md"]["reachable"] is None
    assert facts["by_destination"]["new-skill"]["reachable"] is None
    assert facts["by_destination"]["hook"]["reachable"] is None
    assert isinstance(facts["by_destination"]["claude-md"]["reachable"], int)
    text = report.render_text(report.gather(env2.ledger, claude_dir=claude_dir))
    assert "NOT MEASURED" in text


def test_render_null_leg3_both_usable_nothing_null(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_cmd_project(env)
    facts = report._surface_reach(env.ledger, claude_dir)
    assert facts["reachable"] is not None and facts["unreachable"] is not None
    for counts in facts["by_destination"].values():
        assert counts["reachable"] is not None


def test_render_null_settings_absent_top_level_and_by_destination_null(
    env, tmp_path, monkeypatch
):
    """M-F3 / B-15: `settings-absent` (no settings.json file at all) is
    `claude_dir_usable=True, settings_usable=True` BY DESIGN
    (test_instrument_four_states, PINNED — this test must never make that
    assertion false). The two existing per-facet gates in
    `_surface_reach` are keyed off those two flags, so neither ever fires
    for this state — before this move, the top-level `checked`/
    `unmeasurable` and every `by_destination` count rendered as concrete
    zeros for a settings surface that plain doesn't exist yet,
    indistinguishable from "measured, and empty" (B-15's stated
    collapse). The null gate here is keyed directly off
    `instrument_state`, never by flipping `settings_usable`."""
    claude_dir = make_claude_dir(
        tmp_path, monkeypatch, settings=None, name="null-settings-absent"
    )
    route_cmd_project(env)
    facts = report._surface_reach(env.ledger, claude_dir)

    assert facts["instrument_state"] == "settings-absent"
    # The pinned flags — never flipped by this move.
    assert facts["claude_dir_usable"] is True
    assert facts["settings_usable"] is True

    assert facts["checked"] is None
    assert facts["unmeasurable"] is None
    for key, counts in facts["by_destination"].items():
        assert counts == {
            "reachable": None,
            "unreachable": None,
            "unmeasurable": None,
        }, key

    text = report.render_text(report.gather(env.ledger, claude_dir=claude_dir))
    assert "NOT MEASURED" in text


def test_render_byvariant(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_cmd_project(env, record_id="lrn-f1000001")
    route_rules_user(env, topic="byvariant", rules_paths=("hit-byvariant/*.md",), record_id="lrn-f1000002")
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "byvariant.md"
    write_rules_file(target, paths=["hit-byvariant/*.md"])
    (claude_dir.parent / "hit-byvariant").mkdir(parents=True, exist_ok=True)
    (claude_dir.parent / "hit-byvariant" / "x.md").write_text("x\n", encoding="utf-8")

    facts = report._surface_reach(env.ledger, claude_dir)
    assert facts["by_destination"]["claude-md:rules"]["reachable"] == 1
    assert facts["by_destination"]["claude-md"]["reachable"] == 1
    assert facts["by_destination"]["claude-md:local"] == {
        "reachable": 0, "unreachable": 0, "unmeasurable": 0,
    }
    assert "claude-md:local" in facts["by_destination"]
    assert "claude-md:rules" in facts["by_destination"]


def test_render_order_unreachable_first_reachable_last(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_cmd_project(env, record_id="lrn-f2000001")  # reachable
    route_skill_md(env, record_id="lrn-f2000002")  # not-indexed -> unreachable
    _, _ = route_hook(env, rid="lrn-f2000003", write_script=False)  # target-missing -> unmeasurable

    facts = report._surface_reach(env.ledger, claude_dir)
    rows = facts["rows"]
    assert len(rows) == 3
    assert rows[0]["state"] == "unreachable"
    assert rows[-1]["state"] == "reachable"


def test_render_all_includes_reachable_rows(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    route_cmd_project(env, record_id="lrn-f3000001")
    route_skill_md(env, record_id="lrn-f3000002")
    facts = report._surface_reach(env.ledger, claude_dir)
    ids = {row["record_id"] for row in facts["rows"]}
    assert ids == {"lrn-f3000001", "lrn-f3000002"}


def test_facet_settings_broken_claude_md_stays_determined(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings="{")
    route_cmd_project(env, record_id="lrn-f4000001")
    route_rules_user(env, topic="facet", rules_paths=("hit-facet/*.md",), record_id="lrn-f4000002")
    target = _user_rules_dir(claude_dir / "CLAUDE.md") / "facet.md"
    write_rules_file(target, paths=["hit-facet/*.md"])
    (claude_dir.parent / "hit-facet").mkdir(parents=True, exist_ok=True)
    (claude_dir.parent / "hit-facet" / "x.md").write_text("x\n", encoding="utf-8")
    route_skill_md(env, record_id="lrn-f4000003")

    rows = reachability_rows(env.ledger, claude_dir)
    cmd_row = _find(rows, "lrn-f4000001")
    rules_row = _find(rows, "lrn-f4000002")
    skill_row = _find(rows, "lrn-f4000003")
    assert cmd_row.state != "unmeasurable" or cmd_row.reason != "settings-unparseable"
    assert cmd_row.state == "reachable"
    assert rules_row.state == "reachable"
    assert skill_row.state == "unmeasurable"
    assert skill_row.reason == "settings-unparseable"


def test_refuse_missing_and_not_a_repo_and_hosts_absent(tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})

    missing_home = tmp_path / "no-such-home"
    ok, msg = selfcheck._check_surface(missing_home, claude_dir)
    assert ok is False
    assert msg == selfcheck.home_state_message("missing", missing_home)

    not_repo_home = tmp_path / "not-a-repo-home"
    not_repo_home.mkdir()
    ok, msg = selfcheck._check_surface(not_repo_home, claude_dir)
    assert ok is False
    assert msg == selfcheck.home_state_message("not-a-repo", not_repo_home)

    bare_home = tmp_path / "bare-repo-home"
    init_repo(bare_home)
    ok, msg = selfcheck._check_surface(bare_home, claude_dir)
    assert ok is True
    assert msg == "hosts.yaml absent — reachability not checked"


def test_empty_domain(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})
    ok, msg = selfcheck._check_surface(env.ledger, claude_dir)
    assert ok is True
    assert "no records in the reachability domain" in msg


def test_one_predicate_stub_controls_both_renderers(env, tmp_path, monkeypatch):
    calls = {"n": 0}

    def stub(home, claude_dir, *, user_claude_md=None):
        calls["n"] += 1
        return [
            Verdict(
                record_id="lrn-aaaaaaaa", bucket="skills/s", scope="skill:s",
                destination="skill-md", variant=None, target="/x/SKILL.md",
                state="reachable", reason="personal-skill-link", detail="d",
            ),
            Verdict(
                record_id="lrn-bbbbbbbb", bucket="skills/s", scope="skill:s",
                destination="hook", variant=None, target="/x/hook.sh",
                state="unreachable", reason="not-registered", detail="d",
            ),
        ]

    monkeypatch.setattr(selfcheck, "reachability_rows", stub)
    monkeypatch.setattr(report, "reachability_rows", stub)
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={})

    ok, msg = selfcheck._check_surface(env.ledger, claude_dir)
    assert calls["n"] >= 1, "the stub was never called — the test controls nothing"
    assert "1 of 2 verified reachable" in msg
    assert ok is False

    calls_before_report = calls["n"]
    facts = report._surface_reach(env.ledger, claude_dir)
    assert calls["n"] > calls_before_report
    assert facts["checked"] == 2
    assert facts["reachable"] == 1
    assert facts["unreachable"] == 1


def test_selftest_row_present_and_rc1_on_unreachable(env, tmp_path, monkeypatch, capsys):
    make_claude_dir(tmp_path, monkeypatch, settings={})
    route_skill_md(env)  # no personal symlink, no plugin -> not-indexed
    rc = selfcheck.run_selftest(env.ledger)
    out = capsys.readouterr().out
    lines = [
        line for line in out.splitlines()
        if line.startswith("selftest: PASS ") or line.startswith("selftest: FAIL ")
    ]
    assert len(lines) == 9
    assert any(" surface " in line for line in lines)
    assert rc == 1


def _snapshot(root: Path) -> set[tuple[str, int, str]]:
    out: set[tuple[str, int, str]] = set()
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_symlink():
            st = p.lstat()
            try:
                link_target = os.readlink(p)
            except OSError:
                link_target = ""
            out.add((str(p.relative_to(root)), st.st_mtime_ns, f"symlink:{link_target}"))
            continue
        if p.is_dir():
            continue
        st = p.lstat()
        try:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            digest = "unreadable"
        out.add((str(p.relative_to(root)), st.st_mtime_ns, digest))
    return out


def test_no_writes(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={}, skills={"s": env.skill_dir})
    route_skill_md(env)
    route_hook(env, rid="lrn-0a000001")
    roots = [env.ledger, env.host, claude_dir]
    before = [_snapshot(r) for r in roots]
    reachability_rows(env.ledger, claude_dir)
    after = [_snapshot(r) for r in roots]
    assert before == after


def test_no_real_home(env, tmp_path, monkeypatch):
    claude_dir = make_claude_dir(tmp_path, monkeypatch, settings={}, skills={"s": env.skill_dir})
    route_skill_md(env)
    route_cmd_project(env, record_id="lrn-0a000002")

    allowed_prefixes = (str(env.ledger), str(env.host), str(claude_dir), str(tmp_path))
    opened: list[str] = []
    real_read_text = Path.read_text

    def spy_read_text(self, *a, **kw):
        opened.append(str(self))
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    reachability_rows(env.ledger, claude_dir)
    assert opened, "no reads were observed — the spy controls nothing"
    for p in opened:
        assert any(p.startswith(prefix) for prefix in allowed_prefixes), p
