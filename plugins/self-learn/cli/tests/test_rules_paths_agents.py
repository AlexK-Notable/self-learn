"""The steward and the overseer write sheet lines that route into
path-scoped rules files. Since S-74 a globless route into a file that already
has a `paths:` list is refused, so both agents have to be told how to choose
`rules_paths`, and the sheet machinery must carry the keys they would use
(reroute and dry-run included)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import batch, cli, steward, steward_prompt, verbs
from self_learn.overseer import formats
from support import make_env

from test_steward import _enable_steward
from test_steward_refusals import _case, _dispositions, _notifications
from test_u3b_steward_authority import _project_lesson, _stage_pairs, _status


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


METHOD = Path(__file__).resolve().parents[2] / "skills" / "self-learn" / "references" / "steward-method.md"
REVIEW = Path(__file__).resolve().parents[2] / "commands" / "review.md"

# What each agent has to be told, as phrases that would vanish if the text were cut.
MUST_SAY = (
    "refuse",
    "rules_paths",
    "supersedes",
    "existing `paths:`",
    "allow_empty_glob: true",
    "no longer exists",
)


def _text_of(name: str) -> str:
    return " ".join(_raw_text_of(name).lower().split())


def _raw_text_of(name: str) -> str:
    if name == "steward brief":
        return steward_prompt._render_output_contract()
    if name == "overseer rules":
        return formats._rules("B")
    if name == "steward method":
        return METHOD.read_text(encoding="utf-8")
    return REVIEW.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["steward brief", "overseer rules", "steward method"])
def test_each_agents_instructions_cover_choosing_rules_paths(name):
    text = _text_of(name)
    assert "claude-md:rules:" in text  # control: the right text was loaded
    for phrase in MUST_SAY:
        assert phrase.lower() in text, f"{name} lost: {phrase}"


# The sentences that are the guidance itself, one per agent (the generic
# phrases above also occur in unrelated text).
DISTINCTIVE = {
    "steward brief": "choose the globs in this order: (1) the lesson this one supersedes",
    "overseer rules": "choose the globs in this order: the lesson it supersedes",
    "steward method": "choose them in this order",
}


@pytest.mark.parametrize("name", sorted(DISTINCTIVE))
def test_each_agent_carries_the_ordered_guidance(name):
    assert DISTINCTIVE[name] in _text_of(name)


def test_the_shared_reference_is_a_numbered_section_and_review_md_mentions_the_refusal():
    assert "## 15. a path-scoped rule's globs" in _text_of("steward method")
    assert "refused when the line carries no `rules_paths`" in _text_of("review md")


def test_the_sheet_admits_rules_paths_and_allow_empty_glob_on_a_route_line():
    """A reroute under a reconsider case is a `route` line (batch._dispatch_reroute),
    so one key set serves both."""
    assert {"rules_paths", "allow_empty_glob"} <= batch.PERMITTED_KEYS["route"]
    assert "rules_paths" not in batch.PERMITTED_KEYS["reject"]  # control: not blanket-permitted


# ---------------------------------------------------- the steward end to end


def _pathed_topic(env, rid, topic="t"):
    (env.host / "a").mkdir(exist_ok=True)
    (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")
    verbs.route(env.ledger, rid, dest=f"claude-md:rules:{topic}", rules_paths=["a/**"], no_push=True)


def test_a_globless_steward_route_into_a_pathed_file_is_refused_and_one_with_globs_applies(
    tmp_path, monkeypatch
):
    env = make_env(tmp_path)
    home = env.ledger
    first = _project_lesson(env, "lrn-b6000001")
    bare, pathed = (_project_lesson(env, r) for r in ("lrn-b6000002", "lrn-b6000003"))
    _pathed_topic(env, first)
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        return _stage_pairs(spec, {
            bare: (_case([bare], "route", "route", scope="project"),
                   [{"id": bare, "verb": "route", "dest": "claude-md:rules:t"}]),
            pathed: (_case([pathed], "route", "route", scope="project"),
                     [{"id": pathed, "verb": "route", "dest": "claude-md:rules:t",
                       "rules_paths": ["a/**"]}]),
        })

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[pathed]["state"] == "applied"  # positive control
    assert rows[bare]["state"] != "applied"
    assert _status(home, bare).status == "pending"
    detail = json.dumps(rows[bare])
    assert "path-scoped" in detail  # the refusal's own words are what the run records


# ------------------------------------------- reroute and dry-run carry the flag


def _unscoped_routed(env, rid="lrn-b7000001"):
    _project_lesson(env, rid)
    verbs.route(env.ledger, rid, dest="claude-md:rules:t", no_push=True)
    return rid


def test_a_reroute_line_with_a_dead_glob_needs_allow_empty_glob_and_previews_the_same(tmp_path):
    env = make_env(tmp_path)
    rid = _unscoped_routed(env)
    fields = {"dest": "claude-md:rules:t", "rules_paths": ["gone/**"]}
    item = batch.SheetItem(n=1, id=rid, verb="route", fields=dict(fields))
    refused = batch._preview_reroute(env.ledger, item, "human", False)
    assert refused.state == "would-refuse"  # control: the dead glob is refused without the flag
    item = batch.SheetItem(n=1, id=rid, verb="route", fields={**fields, "allow_empty_glob": True})
    assert batch._preview_reroute(env.ledger, item, "human", False).state == "would-apply"
    batch._dispatch_reroute(env.ledger, item, actor="human", hook_activation=False, is_hook_dest=False)
    routing = _status(env.ledger, rid).routing
    assert routing["rules_paths"] == ["gone/**"] and routing["allow_empty_glob"] is True


def test_a_route_dry_run_line_honours_allow_empty_glob(tmp_path):
    env = make_env(tmp_path)
    rid = _project_lesson(env, "lrn-b8000001")
    fields = {"dest": "claude-md:rules:t2", "rules_paths": ["gone/**"]}
    bad = batch.dry_run(env.ledger, [batch.SheetItem(n=1, id=rid, verb="route", fields=dict(fields))])
    assert bad.items[0].state == "would-refuse"  # control
    ok = batch.dry_run(
        env.ledger,
        [batch.SheetItem(n=1, id=rid, verb="route", fields={**fields, "allow_empty_glob": True})],
    )
    assert ok.items[0].state == "would-apply"


# ----------------------------------------------- the agents can see the globs


def test_show_prints_a_routed_lessons_rules_paths(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    rid = _project_lesson(env, "lrn-b9000001")
    _pathed_topic(env, rid)
    assert cli.main(["show", "--json", rid]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["routing"]["rules_paths"] == ["a/**"]
    assert data["routing"]["rules_topic"] == "t"
    assert cli.main(["show", rid]) == 0
    assert "rules_paths: a/**" in capsys.readouterr().out
