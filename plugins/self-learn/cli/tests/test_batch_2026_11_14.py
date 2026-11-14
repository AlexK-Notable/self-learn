"""The 2026-11-14 repair round (tracker items W-294, W-295, W-296).

W-294: a hook route that carries a new match or message for a lesson that is
already a placed hook was classified "already applied" and changed nothing,
while the overseer's report said it had landed. Now it re-places the hook
(under a reconsider case), is refused by name without one, and the report's
"In short" paragraph gets a runner's note when decisions did not land.

W-295: the word budget never rejects a lesson; the fire count says how many
days it really covers.

W-296: a placed lesson no case covers (placed before decisions were
recorded) can be moved by the overseer under a maintenance case, and the
overseer's stage names the cases that cover each lesson.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir), never the real `~/.self-learn`. No model call is made.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import always_budget, batch, cases, steward
from self_learn.ledger_ops import find_record_path
from self_learn.records import Record
from support import make_env
from test_steward import _dump_yaml
from test_steward_refusals import _case, _seed
from test_u3b_steward_authority import (  # noqa: F401 -- fixtures
    HOOK_TRIGGER,
    _hook_input,
    _record_case,
    _route_through_a_case,
    claude_dir,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _sheet(tmp_path: Path, items: list[dict], case: str | None = None, name: str = "s.yaml"):
    body: dict = {"version": 1, "items": items}
    if case is not None:
        body["case"] = case
    path = tmp_path / name
    _dump_yaml(path, body)
    return path


def _reconsider(home: Path, tmp_path: Path, rid: str, supersedes: str) -> str:
    data = _case([rid], "route", "route")
    data.update(kind="reconsider", supersedes=supersedes)
    return _record_case(home, tmp_path, data)


# ------------------------------------------------------------- W-294 hooks


def _placed_hook(env, tmp_path: Path, rid: str) -> tuple[str, Path]:
    """A lesson routed to its skill by a case, then moved to a hook by a
    reconsider of that case (the steward's runner, activation off: placed
    only). Returns the reconsider case and the script path."""
    home = env.ledger
    (tmp_path / "setup").mkdir(exist_ok=True)
    first = _route_through_a_case(home, tmp_path / "setup", rid)
    rc = _reconsider(home, tmp_path / "setup", rid, first)
    path = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "hook", "hook": _hook_input()}], rc)
    result = batch.run(home, batch.load_sheet(path, home=home), no_push=True, actor="steward")
    assert result.items[0].state == "applied", result.items[0].detail
    meta = (_record(home, rid).routing or {}).get("hook") or {}
    script = env.host / meta["script_path"]
    assert script.is_file()
    return rc, script


def _changed_input() -> dict:
    data = _hook_input()
    data["hook"]["deny_message"] = "stop the HA container first, then edit the file"
    return data


def test_the_change_check_reads_only_the_guard_itself(tmp_path, claude_dir):
    env = make_env(tmp_path)
    rid = "lrn-b1140001"
    _placed_hook(env, tmp_path, rid)
    record = _record(env.ledger, rid)
    assert not batch.hook_input_changes_placed(record, {"hook": _hook_input()})  # control
    assert batch.hook_input_changes_placed(record, {"hook": _changed_input()})
    wider = _hook_input()
    wider["hook"]["path_regex"] = r"\.storage/|\.cloud/"
    assert batch.hook_input_changes_placed(record, {"hook": wider})
    other_examples = _hook_input()
    other_examples["rationale"] = "a different reason, the same guard"
    assert not batch.hook_input_changes_placed(record, {"hook": other_examples})
    assert not batch.hook_input_changes_placed(record, {})


def test_a_changed_guard_on_a_placed_hook_is_re_placed_under_a_reconsider_case(
    tmp_path, claude_dir
):
    """The 0e8a885d shape: the widened match was "already-applied" and the
    placed script kept its old bytes. Mutation: `classify` ignores the
    change -> the item reads already-applied and the message is unchanged."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = "lrn-b1140002"
    rc, script = _placed_hook(env, tmp_path, rid)
    old_bytes = script.read_bytes()
    assert b"stop the HA container first" in old_bytes  # positive control

    second = _reconsider(home, tmp_path / "setup", rid, rc)
    path = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "hook", "hook": _changed_input()}],
                  second, name="widen.yaml")
    sheet = batch.load_sheet(path, home=home)
    assert not batch.classify(home, sheet[0], actor="steward")
    preview = batch.dry_run(home, sheet, actor="steward")
    assert preview.items[0].state == "would-apply", preview.items[0].detail

    result = batch.run(home, sheet, no_push=True, actor="steward")

    assert result.items[0].state == "applied", result.items[0].detail
    record = _record(home, rid)
    assert (record.routing or {}).get("hook", {}).get("deny_message") == (
        "stop the HA container first, then edit the file"
    )
    assert script.is_file()
    assert script.read_bytes() != old_bytes
    assert b"then edit the file" in script.read_bytes()
    displaced = [h for h in record.history if h.get("event") == "routing"]
    assert displaced and displaced[-1]["routing"]["destination"] == "hook"
    # nothing tells anyone to remove a settings.json entry for the same script
    assert "remove the settings.json" not in (result.items[0].detail or "")
    again = batch.run(home, batch.load_sheet(path, home=home), no_push=True, actor="steward")
    assert again.items[0].state == "already-applied"


def test_a_changed_guard_without_a_reconsider_case_is_refused_not_silent(tmp_path, claude_dir):
    env = make_env(tmp_path)
    home = env.ledger
    rid = "lrn-b1140003"
    _rc, script = _placed_hook(env, tmp_path, rid)
    old_bytes = script.read_bytes()
    plain = _record_case(home, tmp_path / "setup", _case([rid], "route", "route"))
    path = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "hook", "hook": _changed_input()}],
                  plain, name="nocase.yaml")

    result = batch.run(home, batch.load_sheet(path, home=home), no_push=True, actor="steward")

    assert result.items[0].state == "refused", result.items[0].detail
    assert script.read_bytes() == old_bytes
    # positive control: the unchanged guard under the same case is a no-op
    same = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "hook", "hook": _hook_input()}],
                  plain, name="same.yaml")
    ok = batch.run(home, batch.load_sheet(same, home=home), no_push=True, actor="steward")
    assert ok.items[0].state == "already-applied", ok.items[0].detail


def test_the_in_short_note_names_what_did_not_land():
    from self_learn.overseer import run as overseer_run

    assert overseer_run._in_short_note(  # noqa: SLF001
        dropped=0, staged=3, lines_dropped=0, items_not_landed=0
    ) is None
    note = overseer_run._in_short_note(  # noqa: SLF001
        dropped=2, staged=4, lines_dropped=1, items_not_landed=1
    )
    assert note is not None
    assert "2 of 4 decision(s)" in note and "1 line(s)" in note and "1 change(s)" in note


def test_finalize_puts_the_note_under_the_in_short_paragraph(tmp_path):
    from self_learn.overseer import run as overseer_run

    path = tmp_path / "report.md"
    headings = ["In short", "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do"]
    body = {h: "- none" for h in headings}
    body["In short"] = "I corrected three things. Nothing needs you."
    path.write_text("# draft\n" + "\n".join(f"## {h}\n{body[h]}\n" for h in headings),
                    encoding="utf-8")
    note = "Runner's note: not all of them were made."

    text = overseer_run._finalize_model_report(  # noqa: SLF001
        path, date="2026-11-14", run_id="12345678", model="m", selected=(),
        population_count=0, excluded=0, model_calls=1, guard=50, refusals=[],
        in_short_note=note,
    )

    short = text.split("## In short\n", 1)[1].split("\n## ", 1)[0]
    assert "I corrected three things." in short and note in short
    assert note not in text.split("## Examined\n", 1)[1]
    plain = overseer_run._finalize_model_report(  # noqa: SLF001
        path, date="2026-11-14", run_id="12345678", model="m", selected=(),
        population_count=0, excluded=0, model_calls=1, guard=50, refusals=[],
    )
    assert "Runner's note" not in plain  # control


# ------------------------------------------------------------ W-295 budget


def test_the_fire_window_says_how_many_days_it_covers():
    placed = datetime(2026, 10, 15, tzinfo=timezone.utc)
    lines = [always_budget.Line("lrn-b1140010", 90, placed_at=placed)]
    young = always_budget.standings(lines, 10, date(2026, 11, 13))["lrn-b1140010"]
    assert young.window_days == 29
    assert "the 29 days since it was placed" in young.detail()
    old = always_budget.standings(
        [always_budget.Line("lrn-b1140011", 90, placed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))],
        10, date(2026, 11, 13),
    )["lrn-b1140011"]
    assert "in 90 days" in old.detail()


def _budget_inputs(rid: str) -> dict:
    return {rid: {"moved": [{"source": "placement", "premise": always_budget.PREMISE_ID}]}}


def test_the_budget_alone_never_rejects_a_lesson():
    """case-d18026ad's shape. Mutation: `_budget_reject_problem` returns None
    -> the reject passes the stage check."""
    rid = "lrn-b1140012"
    case = _case([rid], "reject", "reject")
    items = [{"id": rid, "verb": "reject"}]
    problem = steward._budget_reject_problem(case, items, _budget_inputs(rid), label="c.yaml")  # noqa: SLF001
    assert problem is not None and "never a reason to reject" in problem
    # controls: another input, a parked case, a move instead of a reject
    other = {rid: {"moved": [{"source": "placement", "premise": "@reach"}]}}
    assert steward._budget_reject_problem(case, items, other, label="c.yaml") is None  # noqa: SLF001
    parked = dict(case, kind="parked")
    assert steward._budget_reject_problem(parked, items, _budget_inputs(rid), label="c") is None  # noqa: SLF001
    move = [{"id": rid, "verb": "route", "dest": "claude-md:rules:x"}]
    assert steward._budget_reject_problem(case, move, _budget_inputs(rid), label="c") is None  # noqa: SLF001


# ----------------------------------------------------- W-296 uncovered moves


def _placed_without_a_case(env, rid: str) -> None:
    home = env.ledger
    _seed(home, rid)
    path = env.ledger.parent / f"place-{rid}.yaml"
    _dump_yaml(path, {"version": 1, "items": [{"id": rid, "verb": "route", "dest": "skill-md"}]})
    result = batch.run(home, batch.load_sheet(path, home=home), no_push=True, actor="steward")
    assert result.items[0].state == "applied", result.items[0].detail


def _maintenance(home: Path, tmp_path: Path, rid: str, actor: str = "overseer") -> str:
    data = _case([rid], "route", "route")
    data.update(kind="maintenance", trigger="weekly")
    return _record_case(home, tmp_path, data, actor=actor)


def test_the_overseer_moves_a_placed_lesson_no_case_covers_under_a_maintenance_case(tmp_path):
    """The Hyprland skill's blocker: lessons placed by hand had no case to
    reconsider. Mutation: `_UNCOVERED_MOVE_CASE_KIND` without "overseer" ->
    the line is refused as already routed."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = "lrn-b1140020"
    _placed_without_a_case(env, rid)
    assert batch.uncovered_placed(home, rid)
    (tmp_path / "cases").mkdir()
    case_id = _maintenance(home, tmp_path / "cases", rid)
    path = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "claude-md", "by": "overseer"}],
                  case_id)
    sheet = batch.load_sheet(path, home=home)
    preview = batch.dry_run(home, sheet, actor="overseer")
    assert preview.items[0].state == "would-apply", preview.items[0].detail

    result = batch.run(home, sheet, no_push=True, actor="overseer")

    assert result.items[0].state == "applied", result.items[0].detail
    assert "a lesson no case covers" in (result.items[0].detail or "")
    routing = _record(home, rid).routing or {}
    assert routing.get("destination") == "claude-md"


def test_a_covered_lesson_still_moves_only_through_a_reconsider(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    rid = "lrn-b1140021"
    (tmp_path / "setup").mkdir()
    _route_through_a_case(home, tmp_path / "setup", rid)
    assert not batch.uncovered_placed(home, rid)
    case_id = _maintenance(home, tmp_path / "setup", rid)
    path = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "claude-md", "by": "overseer"}],
                  case_id)

    result = batch.run(home, batch.load_sheet(path, home=home), no_push=True, actor="overseer")

    assert result.items[0].state == "refused", result.items[0].detail
    assert (_record(home, rid).routing or {}).get("destination") == "skill-md"


def test_the_steward_does_not_move_a_lesson_under_a_maintenance_case(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    rid = "lrn-b1140022"
    _placed_without_a_case(env, rid)
    (tmp_path / "cases").mkdir()
    case_id = _maintenance(home, tmp_path / "cases", rid)
    path = _sheet(tmp_path, [{"id": rid, "verb": "route", "dest": "claude-md"}], case_id)

    result = batch.run(home, batch.load_sheet(path, home=home), no_push=True, actor="steward")

    assert result.items[0].state == "refused", result.items[0].detail


def test_the_stage_names_the_cases_that_cover_each_lesson(tmp_path):
    from self_learn.overseer import run as overseer_run

    env = make_env(tmp_path)
    home = env.ledger
    covered, bare = "lrn-b1140023", "lrn-b1140024"
    (tmp_path / "setup").mkdir()
    case_id = _route_through_a_case(home, tmp_path / "setup", covered)
    _placed_without_a_case(env, bare)
    stage = tmp_path / "stage"
    stage.mkdir()

    overseer_run._stage_lessons(home, stage)  # noqa: SLF001

    data = YAML(typ="safe").load(
        (stage / overseer_run.LESSONS_DIR / overseer_run.COVERING_CASES_FILE).read_text()
    )
    assert [row["case"] for row in data["lessons"][covered]] == [case_id]
    assert bare not in data["lessons"]
    assert "maintenance" in data["about"]
    assert cases.list_cases(home, record_id=bare) == []  # control: truly uncovered
