"""P1 of the 2026-10-31 premises design (S-NEXT-rotation): every placed
lesson is re-read by the steward about once every `premises.rotation_days`
days (default 90, decisions 2026-10-31b item 3), and a lesson with a broken
probe is re-read now.

What this file pins (each with the mutation that must make it fail, named in
the lane report):

1. a lesson last looked at 90 or 91 days ago is offered; one at 89 is not;
2. any case that names the lesson is a look -- a `no-action` extract case
   and a parked case included -- not only a deciding case;
3. a refused review comes back one period later, never the next night;
4. a `premise-extract` candidate is never offered for review; a lesson whose
   extract version went terminal without premises is;
5. a lesson with a probe `unavailable` on three sweeps is offered at age one
   day, first in the order;
6. the nightly quota: `auto` is ceil(placed / days) + 1, a number overrides
   it, 0 days offers nothing;
7. the case shape: `replace` / `retire` refused by name, a missing `premises
   set` on a lesson with no key refused, a `note` alone accepted;
8. the due check: a review rides along until 7 days past due;
9. the predecessor of a `premise-moved` decision prefers the routing case
   over a newer extract case;
10. both settings are tier C with no override channel;
11. doctor WARNs when the oldest review is overdue by more than the period;
plus the brief, and one run end to end.

Fix round 1 (gate r1) adds: a quota of 0 never makes the steward due by
itself (it would start an idle run every tick); a lesson with an undecided
move and a lesson the overseer holds are never offered; the due check's
last path (pending lessons no run is new work for) still asks the rotation;
a broken probe on a lesson just past its age is not "overdue by a period";
the doctor row reads `doctor_rows`' own cache and clock.

Sandbox ledger only (`support.make_env` under tmpdir); no model call.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import (
    cases,
    ledger_ops,
    premise_sweep,
    serve,
    settings,
    steward,
    steward_inputs,
)
from self_learn.invocation.contract import Outcome
from self_learn.overseer import health
from self_learn.records import Record
from support import commit_all, make_env
from test_steward import _configure_steward, _dump_yaml, _stage_dir
from test_steward_inputs import _publish_disposition
from test_steward_premise_moved import (
    BUS,
    P_BEHAVIOUR,
    P_CHANGED,
    _case,
    _day,
    _iso,
    _observe,
    _pair,
    _premised,
    _rec,
    _routed,
    _with_baseline,
)

A = "lrn-f8a00001"
B = "lrn-f8a00002"
C = "lrn-f8a00003"
D = "lrn-f8a00004"
E = "lrn-f8a00005"
REVIEW = "premise-review"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _ago(days: int) -> str:
    """Midday UTC *days* calendar days ago: the day count never straddles
    a midnight while the test runs."""
    day = _today() - timedelta(days=days)
    return f"{day.isoformat()}T12:00:00Z"


def _age(home: Path, rid: str, days: int) -> None:
    """Date the lesson's routing *days* ago (its last look, with no case)."""
    path = ledger_ops.find_record_path(home, rid)
    record = Record.from_path(path)
    routing = dict(record.routing or {})
    routing["routed_at"] = _ago(days)
    record.set_routing(routing)
    record.write(path)
    commit_all(home, f"date the routing of {rid}")


def _placed(env, rid: str, days: int, *premises: dict) -> str:
    """A routed lesson last looked at *days* ago that records premises
    (`[]` when none given), so it is no extract candidate."""
    _routed(env, rid)
    _age(env.ledger, rid, days)
    _premised(env.ledger, rid, *premises)
    return rid


def _offered(home: Path, **kwargs) -> list[str]:
    return [row["record"] for row in steward._premise_review_inputs(home, **kwargs)]


def _config(home: Path, text: str) -> None:
    (home / "config.yaml").write_text(text, encoding="utf-8")
    commit_all(home, "config")


# ============================================== 1. when a lesson is due


def test_a_lesson_is_due_once_its_last_look_is_a_whole_period_old(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 89)
    _placed(env, B, 90)
    _placed(env, C, 91)
    # the nightly quota is not what keeps A out (`auto` would be 2 here)
    _config(home, "premises:\n  rotation_per_night: '10'\n")

    rows = steward._premise_review_inputs(home)
    assert sorted(row["record"] for row in rows) == [B, C]
    by = {row["record"]: row for row in rows}
    assert by[B]["kind"] == REVIEW == steward_inputs.INPUT_PREMISE_REVIEW
    assert REVIEW in steward_inputs.INPUT_KINDS
    assert by[B]["version"] == f"review:{(_today() - timedelta(days=90)).isoformat()}:1"
    assert by[B]["review"]["looked_by"] == "routed_at" and by[B]["review"]["period"] == 90
    assert by[B]["record_status"] == "routed" and by[B]["version"] == by[B]["blob"]
    # the longest since its last look first (both rank "no-probe": premises [])
    assert [row["record"] for row in rows] == [C, B]
    # the brief gets the facts it carries
    assert steward._brief_input(by[B])["review"] == by[B]["review"]


def test_a_shorter_period_set_by_hand_re_offers_under_it(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 40)
    assert _offered(home) == []  # control: 40 < 90
    _config(home, "premises:\n  rotation_days: 30\n")
    (row,) = steward._premise_review_inputs(home)
    assert row["version"].endswith(":1") and row["review"]["period"] == 30
    _config(home, "premises:\n  rotation_days: 0\n")
    assert _offered(home) == []


# ================================ 2. any case that names it is a look


def _fake_index(monkeypatch, rows: list[dict]) -> None:
    def list_cases(home_, *, parked_for=None, record_id=None, **kwargs):
        if parked_for is not None:
            return []
        return [dict(r) for r in rows if record_id is None or record_id in r.get("records", [])]

    monkeypatch.setattr(cases, "list_cases", list_cases)


def test_a_no_action_extract_case_and_a_parked_case_each_count_as_a_look(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 120)
    _placed(env, B, 120)
    assert sorted(_offered(home)) == [A, B]  # positive control: both due by their routing

    _fake_index(monkeypatch, [
        {"case": "case-0000aa01", "kind": "resolution", "outcome": "no-action",
         "records": [A], "opened_at": _ago(10)},
        {"case": "case-0000aa02", "kind": "parked", "outcome": "parked",
         "records": [B], "opened_at": _ago(20), "superseded_by": "case-0000aa03"},
    ])
    assert _offered(home) == []
    looked = steward_inputs.last_reviews(home, [_rec(home, A), _rec(home, B)])
    assert looked[A][1] == "case:case-0000aa01" and looked[B][1] == "case:case-0000aa02"
    # neither is a DECISION (the follow-up rule's reading): the two differ on purpose
    assert steward_inputs.last_decision(home, _rec(home, A))[1] == "routed_at"
    assert steward_inputs.last_decision(home, _rec(home, B))[1] == "routed_at"


# ================================== 3. a refusal waits a whole period


def test_a_refused_review_returns_one_period_later_not_the_next_night(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 95)
    (row,) = steward._premise_review_inputs(home)
    _publish_disposition(home, A, row["version"], "refused", "run-0000f8a1")

    assert _offered(home) == []
    assert _offered(home, today=_today() + timedelta(days=1)) == []  # not the next night
    assert _offered(home, today=_today() + timedelta(days=84)) == []  # 179 days: cycle 1 still
    (later,) = steward._premise_review_inputs(home, today=_today() + timedelta(days=85))
    assert later["version"].endswith(":2") and later["version"] != row["version"]


# ============================ 4. the extract is the look of its own


def test_an_extract_candidate_is_never_reviewed_but_a_terminal_extract_is(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _age(home, A, 120)  # old, but it records no premises: an extract candidate
    (extract,) = steward._premise_extract_inputs(home)
    assert extract["record"] == A
    assert _offered(home) == []

    # its extract was refused: terminal without premises -- rotation takes it
    _publish_disposition(home, A, extract["version"], "refused", "run-0000f8a2")
    assert steward._premise_extract_inputs(home) == []
    (row,) = steward._premise_review_inputs(home)
    assert row["record"] == A and row["review"]["has_premises"] is False
    assert row["review"]["rank"] == "no-probe"


# ========================== 5. a broken probe is re-read now, first


def _broken(home: Path, rid: str) -> None:
    for at in (-3, -2, -1):
        _observe(home, rid, P_CHANGED, None, _iso(at))


def test_a_lesson_with_a_broken_probe_is_offered_at_age_one_day_first(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 1, P_CHANGED, P_BEHAVIOUR)
    _placed(env, B, 100)  # an ordinary due lesson, older
    assert _offered(home) == [B]  # control: A's probe is fine so far
    _broken(home, A)
    assert steward_inputs.broken_probes(home) .keys() == {A}

    rows = steward._premise_review_inputs(home)
    assert [row["record"] for row in rows] == [A, B]
    assert rows[0]["review"]["rank"] == "broken-probe" and rows[0]["review"]["broken"] == ["p1"]
    assert rows[0]["version"].startswith("review:broken:p1:")

    # decided: it is not offered again for the same broken probe, and waits for its age
    _publish_disposition(home, A, rows[0]["version"], "applied", "run-0000f8a3")
    assert _offered(home) == [B]


# ============================================ 6. the nightly quota


def test_the_quota_is_auto_by_default_and_a_number_overrides_it(tmp_path):
    assert steward_inputs.rotation_quota("auto", 149, 90) == 3
    assert steward_inputs.rotation_quota("auto", 300, 90) == 5
    assert steward_inputs.rotation_quota("auto", 0, 90) == 1
    assert steward_inputs.rotation_quota("5", 149, 90) == 5
    assert steward_inputs.rotation_quota("0", 149, 90) == 0
    assert steward_inputs.rotation_quota("auto", 149, 0) == 0

    env = make_env(tmp_path)
    home = env.ledger
    for rid in (A, B, C, D, E):
        _placed(env, rid, 100)
    # auto at five placed lessons: ceil(5/90) + 1 = 2
    assert len(_offered(home)) == 2
    _config(home, "premises:\n  rotation_per_night: '4'\n")
    assert len(_offered(home)) == 4
    _config(home, "premises:\n  rotation_per_night: '0'\n")
    assert _offered(home) == []


# ============================================== 7. the case shape


def _review_input(rid: str, *, has_premises: bool = True) -> dict:
    return {"record": rid, "kind": REVIEW, "review": {"has_premises": has_premises}}


def _review_case(records: list[str], **extra) -> dict:
    case = _case(records, outcome="no-action")
    case["question"] = "is this placed lesson still true and relevant?"
    case["decision"]["because"] = "every sentence still holds"
    case.update(extra)
    return case


def test_a_review_case_may_hold_a_note_and_one_premises_line_and_nothing_else(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    inputs = {A: _review_input(A)}
    note = {"id": A, "verb": "note", "append": "checked every sentence: still true"}
    rebase = {"id": A, "verb": "premises", "action": "rebaseline", "ids": ["p1"]}

    good = _pair(stage, "good", _review_case([A]), [note])
    assert steward._pair_problem(stage, good, home, inputs) is None
    both = _pair(stage, "both", _review_case([A]), [rebase, note])
    assert steward._pair_problem(stage, both, home, inputs) is None

    for verb, extra in (("retire", {"covered_by": "skill-md:s"}),
                        ("replace", {"text": "x"})):
        line = {"id": A, "verb": verb, **extra}
        problem = steward._premise_review_problem(_review_case([A]), [line], inputs, label="c")
        assert problem is not None and f"`{verb}` line on it is refused" in problem
    restore = {"id": A, "verb": "premises", "action": "restore-region"}
    problem = steward._premise_review_problem(_review_case([A]), [restore], inputs, label="c")
    assert problem is not None and "`premises restore-region`" in problem
    two_notes = steward._premise_review_problem(_review_case([A]), [note, note], inputs, label="c")
    assert two_notes is not None and "at most one" in two_notes
    shape = steward._premise_review_problem(
        _review_case([A], outcome="retire"), [note], inputs, label="c"
    )
    assert shape is not None and "outcome 'retire'" in shape
    sup = steward._premise_review_problem(
        _review_case([A], supersedes="case-0000beef"), [note], inputs, label="c"
    )
    assert sup is not None and "supersedes" in sup
    merged = steward._premise_review_problem(
        _review_case([A, B]), [{"id": B, "verb": "replace", "also": [A]}], inputs, label="c"
    )
    assert merged is not None and "merges it" in merged

    # no `premises` key: a `set` is required, a note alone is refused
    bare = {A: _review_input(A, has_premises=False)}
    missing = steward._premise_review_problem(_review_case([A]), [note], bare, label="c")
    assert missing is not None and "must write them" in missing
    setting = {"id": A, "verb": "premises", "action": "set", "premises": []}
    assert steward._premise_review_problem(_review_case([A]), [setting, note], bare, label="c") is None
    # a parked case is not judged; neither is a case on another input
    assert steward._premise_review_problem(
        _review_case([A], kind="parked"), [{"id": A, "verb": "retire"}], inputs, label="c"
    ) is None
    assert steward._premise_review_problem(
        _review_case([A]), [{"id": A, "verb": "retire"}], {A: {"record": A, "kind": "lesson"}},
        label="c",
    ) is None


# =============================================== 8. the due check


def test_reviews_ride_along_until_seven_days_past_due(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _configure_steward(home)
    _placed(env, A, 96)  # six days past due
    cache = tmp_path / "cache"
    now = time.time()
    assert _offered(home) == [A]  # positive control: it is due ...
    assert serve._steward_is_due(home, cache, now) is False  # ... but rides along
    _age(home, A, 97)  # seven days past due
    assert serve._steward_is_due(home, cache, now) is True
    _config(home, "steward:\n  enabled: true\npremises:\n  backfill_per_night: 0\n"
                  "  rotation_days: 0\n")
    assert serve._steward_is_due(home, cache, now) is False


def test_an_overdue_review_respects_the_cooldown(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _configure_steward(home)
    _placed(env, A, 200)
    cache = tmp_path / "cache"
    now = time.time()
    monkeypatch.setattr(steward, "last_run_iso", lambda h: _iso(-0.001))
    assert serve._steward_is_due(home, cache, now) is False
    monkeypatch.setattr(steward, "last_run_iso", lambda h: _iso(-2))
    assert serve._steward_is_due(home, cache, now) is True


# ===================================== 9. the predecessor (lineage)


def test_the_predecessor_prefers_the_routing_case_over_a_newer_extract_case(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    rows = [
        {"case": "case-0000ab01", "kind": "resolution", "outcome": "route",
         "records": [A], "opened_at": _ago(60)},
        {"case": "case-0000ab02", "kind": "resolution", "outcome": "no-action",
         "records": [A], "opened_at": _ago(5)},
    ]
    _fake_index(monkeypatch, rows)
    monkeypatch.setattr(steward, "_covering_cases", lambda h, rid: ["case-0000ab01", "case-0000ab02"])
    assert steward._premise_predecessor(home, A) == "case-0000ab01"
    # with no deciding case among them, the newest covering case of any outcome
    rows[0]["outcome"] = "no-action"
    assert steward._premise_predecessor(home, A) == "case-0000ab02"


# ======================================================= 10. tier C


@pytest.mark.parametrize("name, default", [
    ("premises.rotation_days", 90), ("premises.rotation_per_night", "auto"),
])
def test_both_settings_are_tier_c_with_no_override_channel(name, default):
    setting = settings.by_name(name)
    assert setting.tier == "C" and setting.override_channel is False and setting.env_var is None
    assert setting.default == default


def test_the_default_period_constant_is_the_registry_s_default():
    # steward_inputs keeps its own copy for an unreadable registry entry
    assert steward_inputs.ROTATION_DAYS_DEFAULT == settings.by_name("premises.rotation_days").default


def test_rotation_per_night_takes_auto_or_a_whole_number(tmp_path):
    value = settings._rotation_per_night_value
    assert value("auto") == "auto" and value(" 5 ") == "5" and value("0") == "0"
    assert value("five") is None and value("-1") is None and value("2.5") is None
    assert value(5) is None  # a YAML int is not the str setting's form
    setting = settings.by_name("premises.rotation_per_night")
    assert setting.accepts is not None and setting.accepts("7") and not setting.accepts("x")
    home = make_env(tmp_path).ledger
    _config(home, "premises:\n  rotation_per_night: lots\n")
    assert settings.resolve_setting(home, setting) == (
        "auto", "config:premises.rotation_per_night"
    )


# ===================================================== 11. doctor


def _rotation_row(home: Path) -> premise_sweep.DoctorRow:
    (row,) = [r for r in premise_sweep.doctor_rows(home) if r.name == "rotation"]
    return row


def test_doctor_warns_when_the_oldest_review_is_overdue_by_more_than_a_period(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 100)
    row = _rotation_row(home)
    assert row.verdict == "INFO"
    assert row.detail.startswith("every 90 days, 2 a night; 1 due, oldest overdue 10 day(s); ")
    assert row.detail.endswith("0 reviewed in the last 30 days")
    _age(home, A, 181)
    row = _rotation_row(home)
    assert row.verdict == "WARN" and "oldest overdue 91 day(s)" in row.detail
    _config(home, "premises:\n  rotation_days: 0\n")
    row = _rotation_row(home)
    assert (row.verdict, row.detail) == ("INFO", "off (premises.rotation_days is 0)")


def test_the_overseer_s_facts_carry_the_rotation(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 100)
    facts = health.premise_facts(home)
    assert facts["rotation"] == {
        "state": "ok", "period_days": 90, "per_night": 2, "due": 1,
        "oldest_overdue_days": 10, "reviewed_last_30_days": 0,
    }
    _config(home, "premises:\n  rotation_days: 0\n")
    assert health.premise_facts(home)["rotation"]["state"] == "off"


# ======================================================== the brief


def test_the_brief_says_why_now_shows_the_premises_and_how_to_decide(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 100, P_CHANGED, P_BEHAVIOUR)
    _observe(home, A, P_CHANGED, "example-bus.service", _iso(-0.5))
    (row,) = steward._premise_review_inputs(home)
    briefs = steward_inputs.build_briefs(
        home, [steward._brief_input(row)],
        find_record_path=ledger_ops.find_record_path, roots=[],
    )
    body = briefs[A].body
    assert body.startswith(f"[input] {REVIEW}")
    assert "[why it is here] This placed lesson is re-read about once every 90 days" in body
    assert "[why now] nothing was observed to change" in body
    assert f"last looked at on {(_today() - timedelta(days=100)).isoformat()} (routed_at), 100 day(s) ago" in body
    assert "[premises as the daily check last judged them]" in body
    assert "p1: " in body and "p2: no probe (a behaviour)" in body
    assert "recurrences recorded since that look: 0" in body
    assert "[how to decide it] one `kind: resolution` case with `outcome: no-action`" in body
    assert "REQUIRED" not in body  # it records premises
    assert "No `replace`, `retire`, `route`, `reject` or `restore-region` line" in body
    # no transcript evidence pack
    assert "[evidence]" not in body and briefs[A].stats["kind"] == REVIEW


# ======================================================= through a run


def _review_fake(seen: list[str]):
    def fake(spec):
        seen.append(spec.prompt)
        stage = _stage_dir(spec)
        for rid in re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M):
            _dump_yaml(stage / "cases" / f"{rid}.yaml", _review_case([rid]))
            _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
                "version": 1, "case": "$CASE_ID",
                "items": [{"id": rid, "verb": "note",
                           "append": "re-read: every sentence still holds"}],
            })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return fake


def test_a_run_reviews_an_overdue_lesson_once_and_its_case_is_the_new_look(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 120)
    _configure_steward(home)
    assert serve._steward_is_due(home, tmp_path / "cache", time.time()) is True
    seen: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session", _review_fake(seen))

    result = steward.run(home)

    assert result.status == "applied", result
    assert len(seen) == 1 and f"[input] {REVIEW}" in seen[0]
    manifest = steward.committed_manifests(home)[-1]
    assert [(row["record"], row["kind"]) for row in manifest["inputs"]] == [(A, REVIEW)]
    assert _rec(home, A).status == "routed"  # the placement stands
    last, by = steward_inputs.last_review(home, _rec(home, A))
    assert by.startswith("case:") and last is not None and last.date() == _today()
    # the case is the new look: nothing due, the next run idle
    assert _offered(home) == []
    assert steward.run(home).status == "idle"
    status = steward.premise_rotation_status(home)
    assert (status.due, status.reviewed_30d) == (0, 1)


def test_the_contract_and_the_method_describe_the_review():
    from self_learn import steward_prompt, worker

    contract = " ".join(steward_prompt._render_output_contract().split())
    assert "A PREMISE-REVIEW INPUT is a placed lesson back to be re-read whole" in contract
    assert "a `set` is required when it records no premises" in contract
    method = " ".join(
        (worker.package_skill_refs() / "steward-method.md").read_text(encoding="utf-8").split()
    )
    assert "**A `premise-review` input** is a placed lesson that comes back to be re-read whole" in method
    assert "the runner refuses a `replace`, `retire`, `route`, `reject` or `restore-region` line" in method


# ================================================= fix round 1 (gate r1)


def test_a_quota_of_zero_never_makes_the_steward_due_by_itself(tmp_path, monkeypatch):
    """Gate r1 MAJOR 1: with `rotation_per_night: '0'` the run takes no
    review and ends `idle`, which arms no cooldown; a due check that still
    said True started that idle run on every tick."""
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 200)
    cache = tmp_path / "cache"
    now = time.time()
    monkeypatch.setattr(steward, "last_run_iso", lambda h: _iso(-2))
    _config(home, "steward:\n  enabled: true\npremises:\n  backfill_per_night: 0\n")
    assert serve._steward_is_due(home, cache, now) is True  # positive control: `auto`
    _config(home, "steward:\n  enabled: true\npremises:\n  backfill_per_night: 0\n"
                  "  rotation_per_night: '0'\n")
    assert serve._steward_is_due(home, cache, now) is False
    assert steward.run(home).status == "idle"  # what a True would have started, every tick
    assert serve._steward_is_due(home, cache, now) is False
    # the doctor still shows it due (nothing is hidden), at 0 a night
    status = steward.premise_rotation_status(home)
    assert (status.per_night, status.due) == (0, 1)


def test_a_lesson_whose_move_is_undecided_is_not_offered_to_be_re_read(tmp_path):
    """02 §3a.10.4 "Never offered", an undecided `premise-moved` input:
    its move is decided first, and that decision re-records the premises."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _age(home, A, 120)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    _placed(env, B, 120)  # a sibling, due the same way
    _config(home, "premises:\n  rotation_per_night: '10'\n")
    assert sorted(_offered(home)) == [A, B]  # positive control: both due, nothing moved

    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.01))  # two agreeing sweeps: a confirmed move
    assert [row["record"] for row in steward._premise_moved_inputs(home)] == [A]
    assert _offered(home) == [B]


def test_a_lesson_the_overseer_holds_is_not_offered_to_be_re_read(tmp_path, monkeypatch):
    """02 §3a.10.4 "Never offered", S-81: a lesson named by a case parked
    for the overseer is the overseer's until it decides."""
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 120)
    _placed(env, B, 120)
    _config(home, "premises:\n  rotation_per_night: '10'\n")
    assert sorted(_offered(home)) == [A, B]  # positive control
    monkeypatch.setattr(
        cases, "awaiting_overseer",
        lambda h: [{"case": "case-0000cc01", "kind": "parked", "records": [A]}],
    )
    assert A in cases.held_lessons(home)  # through the hold's own reading
    assert _offered(home) == [B]


def test_with_pending_lessons_no_run_is_new_work_for_the_rotation_still_decides(
    tmp_path, monkeypatch,
):
    """`serve._steward_is_due`'s last path: lessons are waiting but every
    one was already selected by a run, so only an overdue review can make
    the steward due -- 7 days past due, not 6."""
    env = make_env(tmp_path)
    home = env.ledger
    _configure_steward(home)
    _placed(env, A, 96)  # six days past due
    cache = tmp_path / "cache"
    now = time.time()
    pending = home / "lrn-f8a0000f.yaml"
    monkeypatch.setattr(serve, "_eligible_input_paths", lambda h: [pending])
    monkeypatch.setattr(steward, "last_run_iso", lambda h: _iso(-2))
    # positive control: the pending lesson is new work -> due, the rotation not asked
    monkeypatch.setattr(serve, "_input_commit_epoch", lambda h, path: now)
    assert serve._steward_is_due(home, cache, now) is True
    # already selected by the last run: nothing new, and the review rides along
    monkeypatch.setattr(serve, "_input_commit_epoch", lambda h, path: now - 30 * 86400)
    assert serve._steward_is_due(home, cache, now) is False
    _age(home, A, 98)  # eight days past due
    assert serve._steward_is_due(home, cache, now) is True


def test_a_broken_probe_on_a_lesson_just_past_its_age_is_not_overdue_by_a_period(tmp_path):
    """Gate r1 MINOR 3: the doctor's "overdue" is days past the age at
    which the lesson would be offered anyway; a broken-probe review's
    grace counts from its last look, but that is not how late it is."""
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 92, P_CHANGED, P_BEHAVIOUR)
    row = _rotation_row(home)
    assert row.verdict == "INFO" and "1 due, oldest overdue 2 day(s)" in row.detail  # control
    _broken(home, A)
    (offered,) = steward._premise_review_inputs(home)
    assert offered["review"]["rank"] == "broken-probe"
    row = _rotation_row(home)
    assert row.verdict == "INFO", row
    assert "1 due, oldest overdue 2 day(s)" in row.detail
    assert health.premise_facts(home)["rotation"]["oldest_overdue_days"] == 2
    # a broken probe on a lesson looked at yesterday: due, and 0 days past its age
    _age(home, A, 1)
    assert steward.premise_rotation_status(home).oldest_overdue == 0
    # the due check's grace still counts a broken review from its last look
    candidates, _days, _placed_n = steward._premise_review_candidates(home)
    assert [(c.overdue, c.past_due) for c in candidates] == [(1, 0)]


def test_the_doctor_row_reads_doctor_rows_own_cache_and_clock(tmp_path):
    """Gate r1 NIT 6: `doctor_rows(home, cache_dir, now=...)` judges the
    rotation on that day and with that cache, like its other rows."""
    env = make_env(tmp_path)
    home = env.ledger
    _placed(env, A, 50, P_CHANGED, P_BEHAVIOUR)

    def rotation(cache_dir=None, now=None):
        (row,) = [r for r in premise_sweep.doctor_rows(home, cache_dir, now=now)
                  if r.name == "rotation"]
        return row

    assert "0 due, none overdue" in rotation().detail  # control: 50 < 90
    later = time.time() + 50 * 86400
    assert "1 due, oldest overdue 10 day(s)" in rotation(now=later).detail
    _broken(home, A)
    assert "1 due, oldest overdue 0 day(s)" in rotation().detail  # broken, in the default cache
    empty = tmp_path / "another-cache"
    empty.mkdir()
    assert "0 due, none overdue" in rotation(cache_dir=empty).detail


# ================================================= fix round 2 (gate r2)


def test_a_broken_probe_alone_makes_the_steward_due_counted_from_its_last_look(
    tmp_path, monkeypatch,
):
    """Gate r2 MINOR 1: the due check's grace reads `overdue` (for a
    broken-probe review, days since the lesson's last look; 02 §3a.10.4),
    never the doctor's `past_due` (days past the age, 0 here). A lesson
    looked at 8 days ago whose probe broke makes a quiet steward due by
    itself; read from `past_due`, it would wait until it was 97 days old."""
    env = make_env(tmp_path)
    home = env.ledger
    _configure_steward(home)
    _placed(env, A, 6, P_CHANGED, P_BEHAVIOUR)
    cache = tmp_path / "cache"
    now = time.time()
    _broken(home, A)
    # positive control: it is offered as a broken-probe review, and nothing
    # else is waiting (no move, no pending lesson, no extract candidate)
    (offered,) = steward._premise_review_inputs(home)
    assert (offered["record"], offered["review"]["rank"]) == (A, "broken-probe")
    assert steward._premise_moved_inputs(home) == []
    assert serve._eligible_input_paths(home) == []
    assert serve._premise_extract_waiting(home) is False
    (candidate,) = steward._premise_review_candidates(home)[0]
    assert (candidate.overdue, candidate.past_due) == (6, 0)

    # the last run was 2 days ago (the cooldown has passed)
    monkeypatch.setattr(steward, "last_run_iso", lambda h: _iso(-2))
    assert serve._steward_is_due(home, cache, now) is False  # six days: rides along
    _age(home, A, 8)  # eight days since its last look, 0 days past its age
    assert steward._premise_review_candidates(home)[0][0].past_due == 0
    assert serve._steward_is_due(home, cache, now) is True

    # no run ever: the due check's first path asks the same question
    monkeypatch.setattr(steward, "last_run_iso", lambda h: None)
    _age(home, A, 5)
    assert serve._steward_is_due(home, cache, now) is False
    _age(home, A, 8)
    assert serve._steward_is_due(home, cache, now) is True
