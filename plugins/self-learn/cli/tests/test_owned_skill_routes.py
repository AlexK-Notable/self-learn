"""SK2 (S-NEXT-sk2-routes) -- routes into skills self-learn owns
(skill-writing plan D5 and D7; §4.1 row SK2, tests (a)-(f); §1.3 fact 1).

What changed, in plain words:

- The steward and the overseer may route or reroute a lesson into
  ``new-skill:<name>`` only when ``<name>`` is a skill self-learn owns (a
  live row in the ledger's ``owned-skills.yaml``) and that skill is deployed.
  Before this, nothing in the batch refused such a route, so a steward sheet
  scaffolded a brand-new skill in the skills root (plan §1.3 fact 1, read in
  ``batch._dispatch`` on 2026-10-31: only the shelf and the hook were
  refused there). ``self-learn skill write`` is now the only way an agent
  creates a skill.
- ``reroute`` (RER4) admits ``new-skill:<name>`` for an owned skill, for
  anyone: the lesson's old line comes out and its new one goes into the
  skill's managed section in one motion.
- A person's ``route --dest new-skill:<name>`` still scaffolds, and now also
  links ``~/.claude/skills/<name>`` itself; the "run ./install.sh" note is
  gone. No route ever scaffolds over an owned skill whose files are missing.

Every scenario uses ``test_skill_write``'s scratch environment: a ledger, a
skills root with a marketplace, and a scratch ``~/.claude``
(``SELF_LEARN_CLAUDE_DIR``). An owned skill is made by SK1's own
``skill_writer.write``. No model is called.

Red on master: ``self_learn.skill_writer`` and ``self_learn.skill_registry``
do not exist there, so the module fails at import. With only SK1 merged
(the base this lane was built on), (a) is red because the steward's route
scaffolds ``fresh``, (c) because RER4 refuses the reroute, and (e) because
no link is made and the install.sh note prints.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from self_learn import batch, cli, gitops, ledger_ops, skill_registry, skill_writer, steward, verbs
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from support import commit_all, git, last_verb_sha, make_behavior
from test_skill_write import NAME, Env
from test_steward import _dump_yaml
from test_steward_refusals import _case
from test_u3b_steward_authority import _record_case

AGENTS = ("steward", "overseer")
RID = "lrn-5c2a0001"
RID2 = "lrn-5c2a0002"
RID3 = "lrn-5c2a0003"
FRESH = "fresh-skill"


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _pending(env: Env, rid: str, *, scope: str = "skill:s", project: bool = False) -> None:
    create_record(
        env.home,
        make_behavior(scope=scope, record_id=rid, trigger=f"About to touch {rid} live."),
        project_path=env.root if project else None,
    )
    commit_all(env.home, f"seed {rid}")


def _sheet(tmp_path: Path, items: list[dict], case: str | None = None) -> batch.Sheet:
    path = tmp_path / f"sheet-{len(list(tmp_path.glob('sheet-*.yaml')))}.yaml"
    body: dict = {"version": 1, "items": items}
    if case is not None:
        body["case"] = case
    _dump_yaml(path, body)
    return batch.load_sheet(path)


def _owned(env: Env) -> str:
    """SK1 deploys an owned skill; returns its authored sha256 as deployed."""
    result = env.write()
    assert result.ok, result.problems
    assert skill_registry.load(env.home).is_owned(NAME)  # control: it IS owned
    sha = skill_writer.deployed_authored_sha256(env.home, NAME)
    assert sha is not None
    return sha


def _untouched(env: Env) -> tuple:
    """What a refused route must leave as it was: the ledger's last verb
    commit, the skills root, the links, and no plugin folder for FRESH."""
    links = sorted(p.name for p in (env.claude / "skills").iterdir())
    return (
        last_verb_sha(env.home), env.head(env.root), env.status(env.root), links,
        env.plugin_dir(FRESH).exists(),
    )


def _marketplace_names(env: Env) -> list[str]:
    return [p["name"] for p in json.loads(env.marketplace.read_text(encoding="utf-8"))["plugins"]]


def test_the_rule_is_one_constant_naming_the_two_agents():
    assert batch.NEW_SKILL_OWNED_ONLY_ACTORS == frozenset({"steward", "overseer"})
    assert "human" not in batch.NEW_SKILL_OWNED_ONLY_ACTORS
    assert batch.NEW_SKILL_OWNED_ONLY_ACTORS <= verbs.ROUTING_BY_VALUES


# ============================================ (a) an agent never scaffolds


@pytest.mark.parametrize("actor", AGENTS)
def test_a_an_agent_route_into_a_skill_self_learn_does_not_own_is_refused_and_scaffolds_nothing(
    env, tmp_path, actor
):
    _pending(env, RID)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": f"new-skill:{FRESH}"}])
    before = _untouched(env)

    preview = batch.dry_run(env.home, sheet, actor=actor)
    result = batch.run(env.home, sheet, no_push=True, actor=actor)

    refused, previewed = result.items[0], preview.items[0]
    assert (refused.state, refused.kind) == ("refused", "bad-line"), refused.detail
    assert (previewed.state, previewed.kind) == ("would-refuse", "bad-line")
    assert refused.detail == previewed.detail  # one sentence, run and preview alike
    assert f"new-skill:{FRESH} is refused for the {actor}" in (refused.detail or "")
    assert "not a skill self-learn owns" in (refused.detail or "")
    assert "`self-learn skill write`" in (refused.detail or "")
    assert steward._KIND_ACTIONS[refused.kind] == "return"  # sent back to choose again
    assert _record(env.home, RID).status == "pending"
    assert _untouched(env) == before
    assert not env.plugin_dir(FRESH).exists()
    assert FRESH not in _marketplace_names(env)
    assert not env.link(FRESH).exists() and not env.link(FRESH).is_symlink()

    # positive control: a person's same sheet scaffolds the skill (D5)
    applied = batch.run(env.home, sheet, no_push=True)
    assert applied.items[0].state == "applied", applied.items[0].detail
    assert env.skill_md(FRESH).is_file()
    assert f"*({RID})*" in env.skill_md(FRESH).read_text(encoding="utf-8")
    assert FRESH in _marketplace_names(env)


@pytest.mark.parametrize("actor", AGENTS)
def test_a_a_lines_own_by_does_not_lift_it(env, tmp_path, actor):
    """The rule reads the runner's actor, never the line's `by:`."""
    _pending(env, RID)
    before = _untouched(env)
    line = {"id": RID, "verb": "route", "dest": f"new-skill:{FRESH}", "by": "human"}
    result = batch.run(env.home, _sheet(tmp_path, [line]), no_push=True, actor=actor)
    assert (result.items[0].state, result.items[0].kind) == ("refused", "bad-line")
    assert f"is refused for the {actor}" in (result.items[0].detail or "")
    assert _record(env.home, RID).status == "pending"
    assert _untouched(env) == before


@pytest.mark.parametrize("actor", AGENTS)
def test_a_a_nameless_new_skill_keeps_the_verbs_own_refusal_and_its_kind(env, tmp_path, actor):
    """No name, no scaffold: the verb refuses it as before, with the kind
    the steward's runner parks on (`unclassified`) -- the new rule does not
    turn it into a `bad-line`."""
    _pending(env, RID)
    before = _untouched(env)
    line = {"id": RID, "verb": "route", "dest": "new-skill"}
    result = batch.run(env.home, _sheet(tmp_path, [line]), no_push=True, actor=actor)
    assert (result.items[0].state, result.items[0].kind) == ("refused", "unclassified")
    assert "new-skill needs a name" in (result.items[0].detail or "")
    assert "refused for the" not in (result.items[0].detail or "")
    assert _untouched(env) == before


# ============================================== (b) into an owned skill


@pytest.mark.parametrize("actor", AGENTS)
def test_b_an_agent_route_into_an_owned_skill_applies(env, tmp_path, actor):
    authored = _owned(env)
    _pending(env, RID)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": f"new-skill:{NAME}"}])
    assert f"*({RID})*" not in env.skill_md().read_text(encoding="utf-8")  # control

    preview = batch.dry_run(env.home, sheet, actor=actor)
    result = batch.run(env.home, sheet, no_push=True, actor=actor)

    assert preview.items[0].state == "would-apply", preview.items[0].detail
    assert result.items[0].state == "applied", result.items[0].detail
    record = _record(env.home, RID)
    assert record.status == "routed"
    assert (record.routing or {}).get("destination") == "new-skill"
    assert (record.routing or {}).get("new_skill") == NAME
    assert (record.routing or {}).get("by") == actor
    assert f"*({RID})*" in env.skill_md().read_text(encoding="utf-8")
    assert skill_writer.routed_lessons(env.home, NAME) == [RID]
    # only the managed section moved: the authored text, the stamp and the
    # marketplace are as `skill write` left them
    assert skill_writer.deployed_authored_sha256(env.home, NAME) == authored
    assert _marketplace_names(env).count(NAME) == 1
    assert env.link().resolve() == env.skill_dir().resolve()


# ======================================= (c) a placed lesson rerouted in


def _placed_in_claude_md_with_a_reconsider_case(env: Env, tmp_path: Path, actor: str) -> str:
    """RID is a skill lesson whose first case (recorded while it was
    pending, the way the pipeline records one) chose `route`; it is placed
    in the skills root's CLAUDE.md; a `kind: reconsider` case by *actor*
    now supersedes that first case. Returns the reconsider case's id."""
    _pending(env, RID)
    setup = tmp_path / "setup"
    setup.mkdir()
    prior = _record_case(env.home, setup, _case([RID], "route", "route"))
    verbs.route(env.home, RID, dest="claude-md", no_push=True)
    assert f"*({RID})*" in (env.root / "CLAUDE.md").read_text(encoding="utf-8")  # control
    reconsider = _case([RID], "route", "route")
    reconsider.update(kind="reconsider", supersedes=prior)
    return _record_case(env.home, setup, reconsider, actor=actor)


@pytest.mark.parametrize("actor", AGENTS)
def test_c_an_agent_reroute_of_a_placed_claude_md_lesson_into_an_owned_skill_moves_it(
    env, tmp_path, actor
):
    authored = _owned(env)
    rc = _placed_in_claude_md_with_a_reconsider_case(env, tmp_path, actor)
    claude_md = env.root / "CLAUDE.md"
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": f"new-skill:{NAME}"}], case=rc)

    preview = batch.dry_run(env.home, sheet, actor=actor)
    result = batch.run(env.home, sheet, no_push=True, actor=actor)

    assert preview.items[0].state == "would-apply", preview.items[0].detail
    assert result.items[0].state == "applied", result.items[0].detail
    assert "rerouted (reconsider)" in (result.items[0].detail or "")
    assert f"→ new-skill:{NAME}" in (result.items[0].detail or "")
    record = _record(env.home, RID)
    assert (record.routing or {}).get("destination") == "new-skill"
    assert (record.routing or {}).get("new_skill") == NAME
    displaced = [h for h in record.history if h.get("event") == "routing"]
    assert displaced and displaced[-1]["routing"]["destination"] == "claude-md"
    assert f"*({RID})*" not in claude_md.read_text(encoding="utf-8")  # the old line is out
    assert f"*({RID})*" in env.skill_md().read_text(encoding="utf-8")  # the new one is in
    assert skill_writer.routed_lessons(env.home, NAME) == [RID]
    assert skill_writer.deployed_authored_sha256(env.home, NAME) == authored


@pytest.mark.parametrize("actor", AGENTS)
def test_c_an_agent_reroute_into_a_skill_self_learn_does_not_own_is_still_refused(
    env, tmp_path, actor
):
    rc = _placed_in_claude_md_with_a_reconsider_case(env, tmp_path, actor)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": f"new-skill:{FRESH}"}], case=rc)
    before = _untouched(env)

    result = batch.run(env.home, sheet, no_push=True, actor=actor)

    assert (result.items[0].state, result.items[0].kind) == ("refused", "bad-line")
    assert (_record(env.home, RID).routing or {}).get("destination") == "claude-md"
    assert f"*({RID})*" in (env.root / "CLAUDE.md").read_text(encoding="utf-8")
    assert _untouched(env) == before


def test_c_a_persons_reroute_into_an_owned_skill_applies_and_into_any_other_new_skill_is_refused(env):
    """RER4 is lifted for owned skills only, for a person as for an agent."""
    _owned(env)
    _pending(env, RID)
    verbs.route(env.home, RID, dest="claude-md", no_push=True)
    before = _untouched(env)

    with pytest.raises(verbs.SheetLineError) as refused:
        verbs.reroute(env.home, RID, dest=f"new-skill:{FRESH}", by="human", no_push=True)
    message = str(refused.value)
    assert "reroute --dest new-skill" in message and "one-motion destination" in message
    assert "not a skill self-learn owns" in message
    assert refused.value.exit_code == 1
    assert _untouched(env) == before

    moved = verbs.reroute(env.home, RID, dest=f"new-skill:{NAME}", by="human", no_push=True)
    assert moved.commit_message == f"self-learn: reroute {RID} → new-skill:{NAME}"
    assert f"*({RID})*" in env.skill_md().read_text(encoding="utf-8")
    assert f"*({RID})*" not in (env.root / "CLAUDE.md").read_text(encoding="utf-8")
    assert (_record(env.home, RID).routing or {}).get("new_skill") == NAME


# ================================== (d) a project lesson into an owned skill


@pytest.mark.parametrize("actor", AGENTS)
def test_d_a_project_scope_lesson_routes_into_an_owned_skill(env, tmp_path, actor):
    _owned(env)
    _pending(env, RID3, scope="project", project=True)
    assert _record(env.home, RID3).scope == "project"  # control: a project lesson
    sheet = _sheet(tmp_path, [{"id": RID3, "verb": "route", "dest": f"new-skill:{NAME}"}])

    result = batch.run(env.home, sheet, no_push=True, actor=actor)

    assert result.items[0].state == "applied", result.items[0].detail
    assert f"*({RID3})*" in env.skill_md().read_text(encoding="utf-8")
    assert skill_writer.routed_lessons(env.home, NAME) == [RID3]


# ======================== (e) a person's scaffold links itself, no install.sh


def test_e_a_persons_new_skill_route_scaffolds_links_and_prints_no_install_step(
    env, capsys
):
    _pending(env, RID)
    assert not env.link(FRESH).exists()  # control: nothing linked before

    rc = cli.main(["route", RID, "--dest", f"new-skill:{FRESH}", "--no-push"])

    out = capsys.readouterr().out
    assert rc == 0, out
    assert env.skill_md(FRESH).is_file()
    assert FRESH in _marketplace_names(env)
    assert env.link(FRESH).is_symlink()
    assert env.link(FRESH).resolve() == env.skill_dir(FRESH).resolve()
    assert f"new skill scaffolded at plugins/{FRESH}, linked at" in out
    assert "install.sh" not in out
    # not owned: a person's scaffold is not a skill self-learn owns (D2)
    assert not skill_registry.load(env.home).is_owned(FRESH)


def test_e_the_route_result_carries_the_link_and_a_second_route_leaves_it(env):
    _pending(env, RID)
    _pending(env, RID2)
    first = verbs.route(env.home, RID, dest=f"new-skill:{FRESH}", no_push=True)
    assert getattr(first.compile_result, "linked", None) == "created"
    assert len(first.post_notes) == 1 and "install.sh" not in first.post_notes[0]
    second = verbs.route(env.home, RID2, dest=f"new-skill:{FRESH}", no_push=True)
    assert getattr(second.compile_result, "linked", None) == "unchanged"
    assert second.post_notes == []  # no scaffold, no note
    assert env.link(FRESH).resolve() == env.skill_dir(FRESH).resolve()


def test_e_a_link_the_route_may_not_make_is_a_warning_and_the_route_stands(env):
    _pending(env, RID)
    squatter = env.link(FRESH)
    squatter.mkdir()
    (squatter / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")

    result = verbs.route(env.home, RID, dest=f"new-skill:{FRESH}", no_push=True)

    assert _record(env.home, RID).status == "routed"
    assert env.skill_md(FRESH).is_file()
    assert squatter.is_dir() and not squatter.is_symlink()  # a person's folder, left alone
    assert getattr(result.compile_result, "linked", None) is None
    assert getattr(result.compile_result, "link_problem", None)
    assert any(f"new skill {FRESH}:" in w and "was not linked" in w for w in result.warnings)
    assert any("NOT linked" in note for note in result.post_notes)


def test_e_a_refused_host_commit_leaves_no_link(env, monkeypatch):
    """The link is made only after the host write stood: a refused commit,
    whose undo takes the fresh scaffold away, leaves no dangling link."""
    _pending(env, RID)
    real_commit = gitops.commit

    def refuse_on_root(repo, message, body=None, paths=None):
        if Path(repo).resolve() == env.root.resolve():
            raise gitops.GitOpsError("simulated: a pre-commit hook said no")
        return real_commit(repo, message, body=body, paths=paths)

    monkeypatch.setattr(gitops, "commit", refuse_on_root)
    result = verbs.route(env.home, RID, dest=f"new-skill:{FRESH}", no_push=True)

    assert any("HOST PHASE FAILED" in w for w in result.warnings)
    assert not env.skill_md(FRESH).exists()
    assert not env.link(FRESH).exists() and not env.link(FRESH).is_symlink()


# ============================= an owned skill is never scaffolded over


def test_an_owned_skill_whose_files_are_missing_is_refused_to_everyone(env, tmp_path):
    _owned(env)
    _pending(env, RID)
    _pending(env, RID2)
    # control: while the skill is deployed, a person's route into it applies
    verbs.route(env.home, RID2, dest=f"new-skill:{NAME}", no_push=True)
    assert f"*({RID2})*" in env.skill_md().read_text(encoding="utf-8")
    env.skill_md().unlink()
    commit_all(env.root, "the skill's SKILL.md went missing")
    before = last_verb_sha(env.home)

    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": f"new-skill:{NAME}"}])
    agent = batch.run(env.home, sheet, no_push=True, actor="steward")
    assert (agent.items[0].state, agent.items[0].kind) == ("refused", "destination-unavailable")
    assert "missing" in (agent.items[0].detail or "")

    with pytest.raises(verbs.DestinationUnavailable, match="never scaffolds"):
        verbs.route(env.home, RID, dest=f"new-skill:{NAME}", no_push=True)

    assert not env.skill_md().exists()  # no seed SKILL.md stood in for the authored one
    assert _record(env.home, RID).status == "pending"
    assert last_verb_sha(env.home) == before

    # a recompile (which resolves with `check_dirty=False`) does not re-seed
    # it either, and names it as an owned skill, not as M3-9's foreign
    # plugin (its folder is still there): RID2 is routed there, so its
    # compile set is not empty
    assert skill_writer.routed_lessons(env.home, NAME) == [RID2]
    result = verbs.recompile(env.home, no_push=True)
    assert not env.skill_md().exists()
    assert any(f"new-skill:{NAME} is a skill self-learn owns" in w for w in result.warnings), (
        result.warnings
    )
    assert not any("foreign authored plugin" in w for w in result.warnings)


def _owned_and_a_later_drifted_target(env: Env) -> Path:
    """Fix round 1 (2026-10-31) setup: RID2 is routed into the owned skill,
    RID3 into skill ``s``'s SKILL.md, and RID3's line there is then cut out
    by hand and committed, so a recompile has a real repair to make on a
    target that sorts AFTER the owned skill's. Returns that SKILL.md."""
    _owned(env)
    _pending(env, RID2)
    _pending(env, RID3)
    verbs.route(env.home, RID2, dest=f"new-skill:{NAME}", no_push=True)
    verbs.route(env.home, RID3, dest="skill-md", no_push=True)
    other = env.root / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md"
    assert f"*({RID3})*" in other.read_text(encoding="utf-8")  # control: placed
    assert str(env.skill_md()) < str(other)  # control: recompile reaches it later
    other.write_text(
        other.read_text(encoding="utf-8").replace(f"*({RID3})*", "*(gone)*"), encoding="utf-8"
    )
    commit_all(env.root, "RID3's line cut out by hand")
    assert f"*({RID3})*" not in other.read_text(encoding="utf-8")  # control: drifted
    return other


def test_a_recompile_skips_an_owned_skill_whose_folder_is_gone_and_repairs_the_rest(env):
    """The whole plugin folder is gone, so M3-9 cannot fire. Before fix
    round 1 the target resolved (`check_dirty=False` skipped SK2's check),
    `_apply_new_skill` raised, and the error escaped `recompile`: no later
    target was repaired, and the steward's recovery recompile raised too.
    Now the owned skill is skipped with SK2's sentence, nothing re-seeds
    it, and the later target is repaired."""
    other = _owned_and_a_later_drifted_target(env)
    shutil.rmtree(env.plugin_dir())
    commit_all(env.root, "the owned skill's whole folder went missing")

    result = verbs.recompile(env.home, no_push=True)

    assert not env.plugin_dir().exists()  # nothing scaffolded in its place
    assert any(
        w.startswith(f"{RID2}:") and f"new-skill:{NAME} is a skill self-learn owns" in w
        for w in result.warnings
    ), result.warnings
    assert f"*({RID3})*" in other.read_text(encoding="utf-8")  # the later target repaired

    # the narrow form the steward's and the overseer's crash recovery uses
    # returns too, and names the refusal for the owned skill's record
    narrow = verbs.recompile(env.home, no_push=True, only_records=[RID2])
    assert any(
        f"new-skill:{NAME} is a skill self-learn owns" in r
        for r in verbs.recompile_refusals(narrow, RID2)
    )


def test_a_refusal_while_recompile_writes_one_git_target_skips_only_that_target(env, monkeypatch):
    """Recompile's git leg catches a `VerbError` from the write (fix round
    1): it costs that target alone. `_apply_target` is made to refuse the
    owned skill's write, as `_apply_new_skill`'s last-stop guard would for a
    SKILL.md that went missing after the target was resolved."""
    other = _owned_and_a_later_drifted_target(env)
    real_apply = verbs._apply_target

    def refuse_the_owned_skill(home, spec, *args, **kwargs):
        if spec.destination == "new-skill":
            raise verbs.DestinationUnavailable("simulated: refused while writing")
        return real_apply(home, spec, *args, **kwargs)

    monkeypatch.setattr(verbs, "_apply_target", refuse_the_owned_skill)
    result = verbs.recompile(env.home, no_push=True)

    skipped = [e for e in result.entries if e.skipped and "simulated" in e.skipped]
    assert len(skipped) == 1
    assert Path(skipped[0].target).resolve() == env.skill_md().resolve()
    assert any("simulated: refused while writing" in w for w in result.warnings)
    assert f"*({RID3})*" in other.read_text(encoding="utf-8")  # the later target repaired
    assert env.skill_md().is_file()  # the owned skill itself left as it was


def test_an_unreadable_registry_refuses_an_agent_route_as_needs_person(env, tmp_path):
    _pending(env, RID)
    (env.home / skill_registry.REGISTRY_FILENAME).write_text("skills: [not, a, map\n", encoding="utf-8")
    commit_all(env.home, "a damaged registry")
    with pytest.raises(skill_registry.SkillRegistryError):  # control: it does not load
        skill_registry.load(env.home)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": f"new-skill:{FRESH}"}])

    result = batch.run(env.home, sheet, no_push=True, actor="overseer")

    assert (result.items[0].state, result.items[0].kind) == ("refused", "needs-person")
    assert skill_registry.REGISTRY_FILENAME in (result.items[0].detail or "")
    assert not env.plugin_dir(FRESH).exists()


# =============================================== (f) control: skill-md


@pytest.mark.parametrize("actor", AGENTS)
def test_f_control_an_agents_skill_md_route_is_unchanged(env, tmp_path, actor):
    _owned(env)  # an owned skill exists, and changes nothing for a linked one
    _pending(env, RID)
    skill_md = env.root / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md"
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": "skill-md"}])
    assert batch.dry_run(env.home, sheet, actor=actor).items[0].state == "would-apply"
    result = batch.run(env.home, sheet, no_push=True, actor=actor)
    assert result.items[0].state == "applied", result.items[0].detail
    assert (_record(env.home, RID).routing or {}).get("destination") == "skill-md"
    assert f"*({RID})*" in skill_md.read_text(encoding="utf-8")
    # ... and the new rule is live on this fixture and this actor
    _pending(env, RID2)
    other = _sheet(tmp_path, [{"id": RID2, "verb": "route", "dest": f"new-skill:{FRESH}"}])
    assert batch.run(env.home, other, no_push=True, actor=actor).items[0].state == "refused"


def test_the_ledger_is_never_written_by_a_refused_preview(env, tmp_path):
    _pending(env, RID)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": f"new-skill:{FRESH}"}])
    head = git(env.home, "rev-parse", "HEAD").stdout
    status = env.status(env.home)
    assert batch.dry_run(env.home, sheet, actor="steward").items[0].state == "would-refuse"
    assert git(env.home, "rev-parse", "HEAD").stdout == head
    assert env.status(env.home) == status
    assert ledger_ops.find_record_path(env.home, RID).parent.name == "pending"
