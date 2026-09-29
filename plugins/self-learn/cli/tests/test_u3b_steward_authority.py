"""U3b (2026-09-28): the steward's authority -- always-loaded lines under the
combined test, hook scripts, re-deciding a placed lesson, path-scoped rules
with the steward's own globs.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real `~/.self-learn`) with the fake session writer the
other steward tests use: the "model" writes its stage files, the runner does
the rest for real. No real model call is made anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import always_loaded, cases, ledger_ops, steward, steward_prompt
from self_learn.invocation.contract import Outcome
from self_learn.ledger_ops import find_record_path
from self_learn.records import Record
from support import make_behavior, make_env
from test_steward import _dump_yaml, _enable_steward, _stage_dir
from test_steward_refusals import _REPAIR_HEADER, _case, _dispositions, _notifications, _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


REF = "transcript:fake#L1"


def _three(ref: str = REF, *, drop: str | None = None) -> dict:
    return {
        key: {"because": f"why {key} holds", "refs": [ref]}
        for key in always_loaded.TEST_KEYS
        if key != drop
    }


def _project_lesson(env, rid: str) -> str:
    return _seed(
        env.ledger, rid, scope="project",
        record=make_behavior(record_id=rid, scope="project"),
        project_path=env.host,
    )


def _status(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _stage_pairs(spec, pairs: dict[str, tuple[dict, list[dict]]]) -> Outcome:
    stage = _stage_dir(spec)
    for name, (case, items) in pairs.items():
        _dump_yaml(stage / "cases" / f"{name}.yaml", case)
        _dump_yaml(stage / "sheets" / f"{name}.yaml",
                   {"version": 1, "case": "$CASE_ID", "items": items})
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


# ------------------------------------------------ 1. the combined test (unit)


def _route_case(block: dict | None, **extra) -> dict:
    case = _case(["lrn-a1000001"], "route", "route")
    if block is not None:
        case["decision"]["always_loaded"] = block
    case.update(extra)
    return case


def test_all_three_tests_evidenced_passes_and_each_missing_one_is_named():
    items = [{"id": "lrn-a1000001", "verb": "route", "dest": "claude-md"}]
    assert always_loaded.route_problem(_route_case(_three()), items) is None  # control
    for key in always_loaded.TEST_KEYS:
        problem = always_loaded.route_problem(_route_case(_three(drop=key)), items)
        assert problem is not None and key in problem, key
        others = [k for k in always_loaded.TEST_KEYS if k != key]
        assert all(f"'{k}'" not in problem for k in others), (key, problem)


def test_a_test_without_because_or_refs_or_with_a_foreign_ref_is_not_evidenced():
    items = [{"id": "lrn-a1000001", "verb": "route", "dest": "claude-md:local"}]
    for broken in (
        {"because": "", "refs": [REF]},
        {"because": "holds", "refs": []},
        {"because": "holds"},
        {"because": "holds", "refs": ["transcript:other#L9"]},  # not one of the case's refs
    ):
        block = _three()
        block["cheaper_fixes_fail"] = broken
        problem = always_loaded.route_problem(_route_case(block), items)
        assert problem is not None and "cheaper_fixes_fail" in problem, broken


def test_a_ref_to_evidence_the_runner_drops_is_not_evidence():
    """`cases.split_runner_evidence` drops an item whose quote is a heading
    line before the case is recorded; a test resting on it has no evidence
    on record."""
    case = _route_case(_three())
    case["evidence"].append({"ref": "file:CLAUDE.md@2026-01-01T00:00:00Z", "quote": "## Heading line"})
    case["decision"]["always_loaded"]["always_applies"]["refs"] = ["file:CLAUDE.md@2026-01-01T00:00:00Z"]
    items = [{"id": "lrn-a1000001", "verb": "route", "dest": "claude-md"}]
    problem = always_loaded.route_problem(case, items)
    assert problem is not None and "always_applies" in problem


def test_only_an_always_loaded_route_of_a_decided_case_needs_the_test():
    for dest in ("reference:shell.md", "skill-md", "claude-md:rules:shell"):
        assert always_loaded.route_problem(
            _route_case(None), [{"id": "lrn-a1000001", "verb": "route", "dest": dest}]
        ) is None, dest
    parked = _route_case(None, kind="parked", outcome="parked",
                         parked_for="overseer", parked_reason="always-loaded-user-scope")
    items = [{"id": "lrn-a1000001", "verb": "route", "dest": "claude-md"}]
    assert always_loaded.route_problem(parked, items) is None
    assert always_loaded.route_problem(_route_case(None), items) is not None  # control


def test_a_dest_less_route_is_tested_through_the_proposal_it_would_take():
    items = [{"id": "lrn-a1000001", "verb": "route"}]
    assert always_loaded.route_problem(_route_case(None), items) is None  # no resolver
    assert always_loaded.route_problem(
        _route_case(None), items, resolve=lambda rid: ("claude-md", None)
    ) is not None
    assert always_loaded.route_problem(
        _route_case(None), items, resolve=lambda rid: ("claude-md", "rules")
    ) is None


def test_the_case_writer_renders_and_scans_the_block_and_refuses_a_bad_shape(tmp_path):
    case = _route_case(_three())
    fields = cases.check_case_data(case)
    assert fields.decision["always_loaded"]
    rendered = cases._render_decision(fields.decision)
    assert "Always-loaded test (all three must hold):" in rendered
    for _key, headline, _text in always_loaded.TESTS:
        assert headline in rendered
    # a case without the block renders exactly as before
    assert "Always-loaded" not in cases._render_decision(_case(["lrn-a1000001"], "route", "route")["decision"])
    bad = _route_case({"always_applies": "just text"})
    with pytest.raises(cases.CaseError, match="always_loaded"):
        cases.check_case_data(bad)
    heading = _route_case(_three())
    heading["decision"]["always_loaded"]["always_applies"]["because"] = "## a heading"
    with pytest.raises(cases.CaseError):
        cases.check_case_data(heading)


def test_the_method_and_the_doctrine_carry_the_tests_verbatim():
    from self_learn import worker

    refs = worker.package_skill_refs()
    for name in ("steward-method.md", "routing-doctrine.md"):
        text = (refs / name).read_text(encoding="utf-8")
        for _key, headline, body in always_loaded.TESTS:
            assert f"**{headline}** {body}" in text, (name, headline)


def test_the_brief_lists_the_tests_from_the_constant():
    text = steward_prompt._render_output_contract()
    for key, headline, _body in always_loaded.TESTS:
        assert f"{key}: {headline}" in text


# ------------------------------------------- 1. the combined test (steward.run)


def test_an_evidenced_always_loaded_route_applies_and_a_missing_test_is_refused_alone(
    tmp_path, monkeypatch
):
    env = make_env(tmp_path)
    home = env.ledger
    good, bad, other = (
        _project_lesson(env, rid) for rid in ("lrn-a1000011", "lrn-a1000012", "lrn-a1000013")
    )
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        good_case = _case([good], "route", "route", scope="project")
        good_case["decision"]["always_loaded"] = _three()
        bad_case = _case([bad], "route", "route", scope="project")
        bad_case["decision"]["always_loaded"] = _three(drop="missing_costs_more")
        return _stage_pairs(spec, {
            good: (good_case, [{"id": good, "verb": "route", "dest": "claude-md"}]),
            bad: (bad_case, [{"id": bad, "verb": "route", "dest": "claude-md"}]),
            other: (_case([other], "reject", "reject", scope="project"),
                    [{"id": other, "verb": "reject"}]),
        })

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[good]["state"] == "applied"
    assert rows[other]["state"] == "applied"
    assert rows[bad]["state"] == "unfinished" and rows[bad]["reason"] == "not-covered"
    assert _status(home, good).status == "routed"
    assert (_status(home, good).routing or {}).get("destination") == "claude-md"
    assert _status(home, other).status == "rejected"
    assert _status(home, bad).status == "pending"
    # the repair turn named the missing test, and only for the bad case
    assert len(prompts) == 2
    repair = prompts[1].split(_REPAIR_HEADER, 1)[1]
    assert "missing_costs_more" in repair and f"{bad}.yaml" in repair
    assert f"{good}.yaml" not in repair
    # SA-1's hold is lifted (S-72): nothing about the evidenced route was parked
    assert cases.list_cases(home, record_id=good, parked_for="overseer") == []
    # the recorded case carries the evidence it was decided on
    decided = cases.list_cases(home, record_id=good)
    assert decided
    view = cases.show(home, decided[0]["case"], evidence_only=False)
    assert "Always-loaded test (all three must hold):" in view.sections["Decision"]


# ------------------------------------------- 1. the combined test (overseer)


def _overseer_route_run(tmp_path, monkeypatch, block: dict | None):
    from self_learn.overseer import run as overseer_run
    from support import make_home
    from test_failstate_overseer import (
        _dump, _ok, _phase_a, _phase_b_common, _successor, _two_parked,
    )
    from test_overseer_run import _enabled

    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)
    case_a = _successor(rid_a, parked_a)
    case_a.update(outcome="route")
    case_a["decision"]["verb"] = "route"
    if block is not None:
        case_a["decision"]["always_loaded"] = {
            key: {"because": "holds", "refs": [f"record:{rid_a}"]} for key in block
        }

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            _dump(spec.cwd / "case-a.yaml", case_a)
            _dump(spec.cwd / "sheet-a.yaml", {"version": 1, "items": [
                {"id": rid_a, "verb": "route", "dest": "claude-md"}]})
            _dump(spec.cwd / "case-b.yaml", _successor(rid_b, parked_b))
            _dump(spec.cwd / "sheet-b.yaml", {"version": 1, "items": [
                {"id": rid_b, "verb": "reject"}]})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    overseer_run.run(home, no_push=True)
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    return home, rid_a, rid_b, report.split("## Refused / could not do", 1)[1]


def test_the_overseer_drops_an_always_loaded_route_missing_a_test_and_the_rest_applies(
    tmp_path, monkeypatch
):
    home, rid_a, rid_b, refused = _overseer_route_run(
        tmp_path, monkeypatch, ("always_applies", "missing_costs_more")
    )
    assert _status(home, rid_b).status == "rejected"  # positive control
    assert "case-a.yaml: dropped with sheet-a.yaml" in refused
    assert "cheaper_fixes_fail" in refused and "always-loaded line" in refused
    assert _status(home, rid_a).status == "pending"


def test_the_overseer_does_not_drop_an_always_loaded_route_with_all_three_tests(
    tmp_path, monkeypatch
):
    _home, _rid_a, _rid_b, refused = _overseer_route_run(
        tmp_path, monkeypatch, always_loaded.TEST_KEYS
    )
    assert "always-loaded line" not in refused


# ------------------------------------------------------------ 2. SA-1 lifts


def test_the_brief_no_longer_carries_the_sa1_hold_and_quotes_s72():
    rendered = steward_prompt._render_method()
    assert "S-72" in rendered  # positive control: the rulings block rendered
    assert "STANDING RULINGS YOU WOULD OTHERWISE GO LOOKING FOR" in rendered
    assert "Q1 HELD" not in rendered
    assert "no new escalation to always-loaded lines" not in rendered
    assert "SA-1" not in dict(steward_prompt.STANDING_RULINGS)


def test_sa1_is_marked_superseded_by_s72_in_the_decisions_register():
    spec = Path(__file__).resolve().parents[4] / "docs/specs/self-learn/03-decisions.md"
    text = spec.read_text(encoding="utf-8")
    sa1 = next(line for line in text.splitlines() if line.startswith("| SA-1 |"))
    assert "Superseded 2026-09-28 by S-72" in sa1
    s72 = next(line for line in text.splitlines() if line.startswith("| S-72 |"))
    assert "leave the overseer the job of corrercting it" in s72  # the user's own words
    assert "not a user ruling" in s72


# ------------------------------------------------- 3. hooks the steward writes


from test_hook_activation import _real_claude_dir_never_touched  # noqa: E402,F401 -- the real-~/.claude control

HOOK_TRIGGER = "About to edit `.storage/*.json` while HA is running."


def _hook_input(*, deny_path: str = "/x/.storage/core.config") -> dict:
    return {
        "rationale": "Blocks an Edit or Write under .storage/; every other file stays allowed.",
        "hook": {
            "tools": ["Edit", "Write"],
            "path_regex": r"\.storage/",
            "deny_message": "stop the HA container first",
        },
        "examples": {
            "allow": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/x/configuration.yaml"}},
                {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
            ],
            "deny": [
                {"tool_name": "Edit", "tool_input": {"file_path": deny_path}},
                {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/auth"}},
            ],
        },
    }


@pytest.fixture
def claude_dir(tmp_path, monkeypatch):
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    return claude


def _behavior_lesson(env, rid: str) -> str:
    return _seed(env.ledger, rid, record=make_behavior(record_id=rid, trigger=HOOK_TRIGGER))


def test_a_steward_hook_is_placed_with_the_delegated_receipt_when_activation_is_off(
    tmp_path, monkeypatch, claude_dir
):
    from self_learn.hook_compiler import script_name

    env = make_env(tmp_path)
    home = env.ledger
    rid = _behavior_lesson(env, "lrn-a3000001")
    _enable_steward(home)
    _notifications(monkeypatch)

    def session(spec):
        return _stage_pairs(spec, {rid: (
            _case([rid], "route", "route"),
            [{"id": rid, "verb": "route", "dest": "hook", "hook": _hook_input()}],
        )})

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[rid]["state"] == "applied", rows[rid]
    record = _status(home, rid)
    assert record.status == "routed"
    hook_meta = (record.routing or {}).get("hook") or {}
    assert (record.routing or {}).get("destination") == "hook"
    assert hook_meta.get("script", "").startswith("#!")  # the CLI generated it
    name = script_name(rid, HOOK_TRIGGER)
    assert (claude_dir / "hooks" / name).is_symlink()  # placed
    assert not (claude_dir / "settings.json").exists()  # never registered
    entry = next(h for h in record.history if h.get("event") == "hook-activated")
    assert "switched off" in (entry.get("note") or "")
    assert cases.list_cases(home, record_id=rid, parked_for="overseer") == []


def test_a_steward_hook_whose_replay_fails_is_refused_alone(tmp_path, monkeypatch, claude_dir):
    """The deny example does not match the regex, so the generated guard
    would allow a call the steward said it denies: that line is refused,
    the repair turn is told, and the packet's other case applies."""
    env = make_env(tmp_path)
    home = env.ledger
    bad = _behavior_lesson(env, "lrn-a3000002")
    other = _seed(home, "lrn-a3000003")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        return _stage_pairs(spec, {
            bad: (_case([bad], "route", "route"), [{
                "id": bad, "verb": "route", "dest": "hook",
                "hook": _hook_input(deny_path="/x/config/core.config"),
            }]),
            other: (_case([other], "reject", "reject"), [{"id": other, "verb": "reject"}]),
        })

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[other]["state"] == "applied"  # positive control
    assert _status(home, other).status == "rejected"
    assert _status(home, bad).status == "pending"
    assert rows[bad]["state"] != "applied"
    assert "guard replay failed" in (rows[bad].get("reason") or ""), rows[bad]
    assert len(prompts) == 2 and "guard replay failed" in prompts[1]
    assert not any((claude_dir / "hooks").iterdir())


def test_a_hook_compile_input_is_shape_checked_with_the_sheet(tmp_path):
    from self_learn import batch

    def load(item: dict):
        path = tmp_path / "sheet.yaml"
        _dump_yaml(path, {"version": 1, "items": [item]})
        return batch.load_sheet(path)

    good = {"id": "lrn-a3000004", "verb": "route", "dest": "hook", "hook": _hook_input()}
    assert load(good)[0].fields["hook"]["hook"]["tools"] == ["Edit", "Write"]  # control
    with pytest.raises(batch.BatchError, match="needs dest: hook"):
        load({**good, "dest": "reference:x.md"})
    with pytest.raises(batch.BatchError, match="missing"):
        load({**good, "hook": {"rationale": "r", "hook": {}}})
    with pytest.raises(batch.BatchError, match="must be a mapping"):
        load({**good, "hook": "script text"})


def test_the_hook_route_is_open_to_the_steward_and_the_overseer_only():
    from self_learn import batch

    assert batch.HOOK_ROUTING_ACTORS == {"overseer", "steward"}
