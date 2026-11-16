"""S-157: routing bootstraps registered user files, never missing skills."""

import pytest

from self_learn import batch, skill_registry
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from support import commit_all, last_verb_sha
from test_owned_skill_routes import RID, _owned, _pending, _record, _sheet
from test_skill_registration import register, seed
from test_skill_write import NAME, Env

ACTORS = ("overseer", "steward", "agent", "human")
DESTINATIONS = (f"new-skill:{NAME}", "skill-md")
PROSE = (
    f"---\nname: {NAME}\ndescription: A user-maintained procedure.\n---\n\n"
    "# A user's procedure\n\nKeep this café text, spacing  and punctuation.\n\n"
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def route_sheet(env, tmp_path, destination):
    _pending(env, RID, scope=f"skill:{NAME}")
    return _sheet(tmp_path, [{
        "id": RID, "verb": "route", "dest": destination, "by": "agent",
    }])


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("destination", DESTINATIONS)
def test_registered_file_bootstraps_and_preserves_user_bytes(env, tmp_path, actor, destination):
    seed(env, text=PROSE)
    register(env)
    registry = skill_registry.load(env.home)
    assert registry.is_registered(NAME) and not registry.is_owned(NAME)
    original = env.skill_md().read_bytes()
    assert original == PROSE.encode() and BEGIN_MARKER.encode() not in original
    sheet = route_sheet(env, tmp_path, destination)
    before = (last_verb_sha(env.home), env.head(env.root))

    preview = batch.dry_run(env.home, sheet, actor=actor)
    assert preview.items[0].state == "would-apply", preview.items[0].detail
    assert env.skill_md().read_bytes() == original
    assert (last_verb_sha(env.home), env.head(env.root)) == before

    result = batch.run(env.home, sheet, no_push=True, actor=actor)
    assert result.items[0].state == "applied", result.items[0].detail
    placed = env.skill_md().read_bytes()
    prefix, section = placed.split(BEGIN_MARKER.encode())
    body, suffix = section.split(END_MARKER.encode())
    assert prefix == original
    assert suffix == b"\n"
    assert f"*({RID})*".encode() in body
    assert _record(env.home, RID).status == "routed"
    assert _record(env.home, RID).routing["destination"] == destination.split(":")[0]
    assert not skill_registry.load(env.home).is_owned(NAME)


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("destination", DESTINATIONS)
@pytest.mark.parametrize("state", ("owned-no-section", "registered-missing"))
def test_routes_refuse_damaged_owned_or_missing_registered_skills(
    env, tmp_path, actor, destination, state,
):
    if state == "owned-no-section":
        _owned(env)
        env.skill_md().write_text(PROSE)
    else:
        seed(env, text=PROSE)
        register(env)
        env.skill_md().unlink()
    commit_all(env.root, "simulate unavailable skill")
    sheet = route_sheet(env, tmp_path, destination)
    before = (
        last_verb_sha(env.home), env.head(env.root),
        env.skill_md().read_bytes() if env.skill_md().exists() else None,
    )

    preview = batch.dry_run(env.home, sheet, actor=actor)
    result = batch.run(env.home, sheet, no_push=True, actor=actor)
    assert preview.items[0].state == "would-refuse", preview.items[0].detail
    assert result.items[0].state == "refused", result.items[0].detail
    detail = result.items[0].detail or ""
    if state == "owned-no-section":
        assert "managed section" in detail
    else:
        assert "missing" in detail or "no SKILL.md" in detail
    assert _record(env.home, RID).status == "pending"
    assert (
        last_verb_sha(env.home), env.head(env.root),
        env.skill_md().read_bytes() if env.skill_md().exists() else None,
    ) == before
