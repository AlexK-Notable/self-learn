"""S-NEXT-u4-steward (premise-check design, unit U4): the steward decides a
placed lesson whose written premise moved, and the `premises` sheet verb
records what a lesson rests on.

The case that prompted the design (2026-10-30): a routed lesson said
"nothing binds this daemon to the bus" long after a drop-in bound it. U3
made a closed follow-up a `premise-moved` input; U4 adds the premises a
lesson records (`premises.py`, U1) as movers, the verb that writes them, and
the rules the steward's case must follow.

What this file pins, each of it failing on master (the verb, the movers, the
brief lines and the stage rules do not exist there):

* the `premises` sheet verb: `set` runs each probe once and records what it
  saw (a first value against the claim as `contradicts-claim`), a sheet never
  writes `baseline` or `decided_at`, `rebaseline` re-records only the named
  premises, a probe that cannot observe refuses the line and writes nothing,
  the dry run says so first, and the commit is found by the execution
  evidence;
* a written premise makes a `premise-moved` input only when the sweep saw the
  same new value on its last two observations after the baseline (one is not
  enough, a flapping value is not, `unavailable` never is, and a stale
  observation from before the baseline never is); a `ledger` premise moves at
  once; a `contradicts-claim` baseline moves from the next night; a probe
  move waits seven days after the premise was decided; `on_change: refresh`
  never reaches the steward;
* the brief shows the moved premise with its recorded and current values,
  the record's premises block to cite, and how to decide, and every lesson
  brief lists the lesson's premises;
* the stage check refuses a decision that keeps the lesson without
  re-recording the moved premise (before a `replace`), and lets a `kind:
  resolution` case replace a placed lesson only on a `premise-moved` input no
  case covers;
* end to end, a fake steward decides the input with a rebaseline, and it is
  never offered again.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real `~/.self-learn`). No model call. No probe runs a real
program: every `systemd-show` probe goes through a fake command runner that
fails the test on any argv outside the catalog's read-only shape. Ids, unit
names and texts are synthetic.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import (
    batch,
    execution_evidence,
    gitops,
    ledger_ops,
    premises,
    serve,
    steward,
    steward_inputs,
    verbs,
)
from self_learn.invocation.contract import Outcome
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env, proposal_dict
from test_steward import _configure_steward, _dump_yaml, _stage_dir

A = "lrn-f6a00001"
B = "lrn-f6a00002"
C = "lrn-f6a00003"
D = "lrn-f6a00004"

UNIT = "example-agent.service"
BUS = "example-bus.service"
PROBE = {"kind": "systemd-show", "scope": "user", "unit": UNIT, "property": "BindsTo"}
#: A claim judged against the value: holds while BUS is NOT in it.
P_ABSENT = {"id": "p1", "claim": "the agent unit is not bound to the session bus",
            "probe": PROBE, "holds_if": "absent", "match": BUS}
#: A claim that holds while the value is what it was (the default).
P_CHANGED = {"id": "p1", "claim": "the agent unit's BindsTo is as recorded", "probe": PROBE}
#: A behaviour: written down, never probed.
P_BEHAVIOUR = {"id": "p2", "claim": "the agent can outlive a bus restart without reconnecting",
               "probe": None}


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    # A user-scope placement compiles into ~/.claude: never the real one.
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


# ------------------------------------------------------------- helpers


def _day(offset: int = 0) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()


def _iso(days: float = 0) -> str:
    moment = datetime.now(timezone.utc) + timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(text: str) -> str:
    return premises.value_sha(premises.normalize_value(text))


def _routed(env, rid: str, **route_kwargs) -> str:
    ledger = env.ledger
    ledger_ops.create_record(ledger, make_behavior(record_id=rid, scope="skill:s"))
    ledger_ops.write_proposal(ledger, rid, proposal_dict(scope="skill:s"))
    commit_all(ledger, f"seed {rid}")
    verbs.route(ledger, rid, dest="skill-md", no_push=True, **route_kwargs)
    return rid


def _rec(home: Path, rid: str) -> Record:
    return Record.from_path(ledger_ops.find_record_path(home, rid))


def _premised(home: Path, rid: str, *entries: dict) -> None:
    """Write *entries* (baselines included) straight onto the record, as a
    decision made earlier would have left them."""
    path = ledger_ops.find_record_path(home, rid)
    record = Record.from_path(path)
    record.set_premises([dict(entry) for entry in entries])
    record.write(path)
    commit_all(home, f"premises on {rid}")


def _with_baseline(premise: dict, value: str, *, at: str, decided: str,
                   state: str = "holds") -> dict:
    baseline = {"state": state, "value_sha": _sha(value), "observed_at": at}
    if value:  # an empty value has no shown text (`premises._shown`)
        baseline["shown"] = value
    return {**premise, "baseline": baseline, "decided_at": decided}


def _observe(home: Path, rid: str, premise: dict, value: str | None, at: str) -> None:
    """One sweep observation in the cache file the sweep (U2) keeps; *value*
    `None` is an `unavailable` observation."""
    if value is None:
        observation = premises.unavailable_observation("systemctl is not installed", observed_at=at)
    else:
        observation = premises.observation_from_value(value, premise=premise, observed_at=at)
    path = steward_inputs.observations_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": rid, "premise": premise["id"],
                             "observation": observation.as_dict()}) + "\n")


def _moved(home: Path) -> list[str]:
    return [row["record"] for row in steward._premise_moved_inputs(home)]


class FakeSystemctl:
    """The probe runner the verb gets: prints *out*, records every argv, and
    fails the test on any argv but the catalog's read-only `show`."""

    def __init__(self, out: str = "") -> None:
        self.out = out
        self.fail: BaseException | None = None
        self.calls: list[list[str]] = []

    def __call__(self, argv, env, timeout):
        self.calls.append(list(argv))
        assert argv[:3] == ["systemctl", "--user", "show"] and "--no-ask-password" in argv, argv
        if self.fail is not None:
            raise self.fail
        return premises.CommandResult(0, self.out.encode("utf-8"), b"")


@pytest.fixture
def systemctl(tmp_path, monkeypatch) -> FakeSystemctl:
    fake = FakeSystemctl()
    monkeypatch.setattr(
        verbs, "_premise_probe_env",
        lambda home: premises.ProbeEnv(home=tmp_path / "fake-home", ledger_home=Path(home),
                                       runner=fake, path_env="/usr/bin"),
    )
    return fake


def _sheet(tmp_path: Path, items: list[dict], name: str = "sheet") -> batch.Sheet:
    path = tmp_path / f"{name}.yaml"
    _dump_yaml(path, {"version": 1, "items": items})
    return batch.load_sheet(path)


def _apply(home: Path, tmp_path: Path, items: list[dict]) -> batch.ItemResult:
    result = batch.run(home, _sheet(tmp_path, items), no_push=True, actor="steward")
    (got,) = result.items
    return got


def _subject(home: Path) -> str:
    return git(home, "log", "-1", "--format=%s").stdout.strip()


def _body(home: Path) -> str:
    return git(home, "log", "-1", "--format=%B").stdout


# ================================================ 1. the `premises` verb


def test_set_runs_each_probe_once_and_records_what_it_saw(tmp_path, systemctl):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    systemctl.out = "\n"

    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                   "premises": [P_ABSENT, P_BEHAVIOUR]}])

    assert (got.state, got.rc) == ("applied", 0), got
    # one probe, run once, in the catalog's read-only shape
    assert systemctl.calls == [[
        "systemctl", "--user", "show", "--no-pager", "--no-ask-password",
        "--property", "BindsTo", "--value", "--", UNIT,
    ]]
    p1, p2 = _rec(home, A).premises or []
    assert p1["baseline"]["state"] == "holds"
    assert p1["baseline"]["value_sha"] == _sha("\n")
    assert p1["decided_at"] == _day()
    # a behaviour has no probe and so no baseline
    assert p2["probe"] is None and "baseline" not in p2 and p2["decided_at"] == _day()
    assert _subject(home) == f"self-learn: premises set {A}"
    assert "p2: no probe" in _body(home)


def test_a_first_value_against_the_claim_is_recorded_as_contradicting_it(tmp_path, systemctl):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    systemctl.out = f"{BUS}\n"

    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                   "premises": [P_ABSENT]}])

    assert (got.state, got.rc) == ("applied", 0), got
    (p1,) = _rec(home, A).premises or []
    assert p1["baseline"]["state"] == "contradicts-claim"
    assert p1["baseline"]["value_sha"] == _sha(BUS)


@pytest.mark.parametrize("key", ["baseline", "decided_at"])
def test_a_sheet_never_writes_what_the_runner_records(tmp_path, key):
    entry = {**P_ABSENT, key: "2026-10-01" if key == "decided_at" else
             {"state": "holds", "value_sha": "0" * 32, "observed_at": "2026-10-01T00:00:00Z"}}
    with pytest.raises(batch.BatchError, match="the runner records"):
        _sheet(tmp_path, [{"id": A, "verb": "premises", "action": "set", "premises": [entry]}])
    # control: the same line without it loads
    assert _sheet(tmp_path, [{"id": A, "verb": "premises", "action": "set",
                              "premises": [P_ABSENT]}], name="clean")


@pytest.mark.parametrize("line, fragment", [
    ({"action": "set"}, "needs `premises`"),
    ({"action": "set", "premises": [], "ids": ["p1"]}, "`ids` belongs to action rebaseline"),
    ({"action": "rebaseline"}, "needs `ids`"),
    ({"action": "rebaseline", "ids": ["p1"], "premises": []}, "`premises` belongs to action set"),
    ({"action": "restore"}, "`action` must be one of"),
])
def test_a_premises_line_of_the_wrong_shape_refuses_the_whole_sheet(tmp_path, line, fragment):
    with pytest.raises(batch.BatchError, match=re.escape(fragment)):
        _sheet(tmp_path, [{"id": A, "verb": "premises", **line}])


def test_rebaseline_rewrites_only_the_named_premise_and_an_unavailable_probe_writes_nothing(
    tmp_path, systemctl
):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    other = {"id": "p3", "claim": "the agent unit is wanted by the session",
             "probe": {**PROBE, "property": "WantedBy"}}
    systemctl.out = ""
    assert _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                    "premises": [P_ABSENT, P_BEHAVIOUR, other]}]).state == "applied"
    before = {p["id"]: p for p in _rec(home, A).premises or []}

    systemctl.out = f"{BUS}\n"
    systemctl.calls.clear()
    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "rebaseline",
                                   "ids": ["p1"], "because": "the bus binding is now intended"}])

    assert (got.state, got.rc) == ("applied", 0), got
    assert len(systemctl.calls) == 1 and systemctl.calls[0][6] == "BindsTo"
    after = {p["id"]: p for p in _rec(home, A).premises or []}
    assert after["p1"]["baseline"]["value_sha"] == _sha(BUS)
    assert after["p1"]["baseline"]["state"] == "contradicts-claim"
    assert after["p3"] == before["p3"] and after["p2"] == before["p2"]
    assert _subject(home) == f"self-learn: premises rebaseline {A}"
    body = _body(home)
    assert "the bus binding is now intended" in body and f"now '{BUS}'" in body

    # a probe that cannot observe cannot be a baseline: refused, nothing written
    systemctl.fail = FileNotFoundError("systemctl")
    record_bytes = ledger_ops.find_record_path(home, A).read_bytes()
    head = gitops.head_sha(home)
    preview = batch.dry_run(home, _sheet(tmp_path, [{"id": A, "verb": "premises",
                                                     "action": "rebaseline", "ids": ["p1"]}]),
                            actor="steward")
    (shown,) = preview.items
    assert (shown.state, shown.kind) == ("would-refuse", "bad-line"), shown
    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "rebaseline",
                                   "ids": ["p1"]}])
    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert "cannot be a baseline" in str(got.detail)
    assert ledger_ops.find_record_path(home, A).read_bytes() == record_bytes
    assert gitops.head_sha(home) == head

    # a premise with no probe, or one the lesson does not have, is refused by name
    systemctl.fail = None
    for ids, fragment in ((["p2"], "has no probe"), (["p4"], "no premise ['p4']")):
        got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "rebaseline",
                                       "ids": ids}])
        assert got.state == "refused" and fragment in str(got.detail), (ids, got)


def test_the_dry_run_previews_a_clean_line_and_writes_nothing(tmp_path, systemctl):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    head = gitops.head_sha(home)
    preview = batch.dry_run(home, _sheet(tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                                     "premises": [P_ABSENT]}]), actor="steward")
    (shown,) = preview.items
    assert shown.state == "would-apply", shown
    assert systemctl.calls  # the preview ran the probe ...
    assert gitops.head_sha(home) == head and _rec(home, A).premises is None  # ... and wrote nothing


def test_an_empty_list_is_written_once_and_then_already_applied(tmp_path, systemctl):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    line = {"id": A, "verb": "premises", "action": "set", "premises": []}
    assert _apply(home, tmp_path, [line]).state == "applied"
    assert _rec(home, A).premises == []
    assert _apply(home, tmp_path, [line]).state == "already-applied"
    assert systemctl.calls == []


def test_the_commit_is_found_as_the_lines_proof_and_a_refresh_is_not():
    ref = execution_evidence.ExecutionRef(
        run_id="run-u4-premises", case_id="case-acde1234", sheet_sha="12ab34cd",
        sheet_digest="a" * 64, item=1, record_id=A, verb="premises", actor="steward",
    )
    for action in ("set", "rebaseline"):
        assert execution_evidence._subject_matches(ref, f"self-learn: premises {action} {A}")
    assert not execution_evidence._subject_matches(ref, f"self-learn: premises refresh {A}")
    assert not execution_evidence._subject_matches(ref, f"self-learn: premises set {B}")


# ============================================ 2. what makes the input


def test_a_probe_premise_moves_on_two_agreeing_sweeps_after_its_baseline(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    assert _moved(home) == []  # control: nothing observed yet

    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    assert _moved(home) == []  # one sweep is not enough

    _observe(home, A, P_CHANGED, BUS, _iso(-0.01))
    (row,) = steward._premise_moved_inputs(home)
    assert row["kind"] == steward_inputs.INPUT_PREMISE_MOVED and row["record"] == A
    (item,) = row["moved"]
    assert (item["source"], item["premise"], item["how"]) == ("premise", "p1", "probe")
    assert (item["recorded"], item["now"]) == ("", BUS)
    assert row["version"] == steward_inputs.premise_moved_version(moved=[("p1", _sha(BUS))])
    assert "predecessor" not in row
    assert "p1" in row["reason"]


@pytest.mark.parametrize("values, why", [
    (["one-bus.service", "two-bus.service"], "a value that keeps changing"),
    ([None, None, None], "unavailable is neither holds nor moved"),
    ([BUS, None], "the latest sweep could not observe"),
])
def test_no_two_agreeing_moved_sweeps_no_input(tmp_path, values, why):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    for n, value in enumerate(values):
        _observe(home, A, P_CHANGED, value, _iso(-3 + n))
    assert _moved(home) == [], why


def test_three_unavailable_sweeps_are_a_broken_probe_and_no_input(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    for n in range(3):
        _observe(home, A, P_CHANGED, None, _iso(-3 + n))
    found = steward_inputs.moved_premises(home)[A]
    assert found.items == [] and [b["premise"] for b in found.broken] == ["p1"]
    assert _moved(home) == []


def test_observations_from_before_the_baseline_never_move_it(tmp_path):
    """A decision re-recorded the baseline; the sweep lines that showed the
    old change are older than it and must not bring the case back."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-0.5), decided=_day(-10)))
    _observe(home, A, P_CHANGED, BUS, _iso(-2))
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    assert _moved(home) == []
    # control: the same two lines after the baseline move it
    _observe(home, A, P_CHANGED, BUS, _iso(-0.2))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.1))
    assert _moved(home) == [A]


def test_a_probe_move_waits_a_week_after_the_premise_was_decided(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-2)))
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.5))
    assert _moved(home) == []
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-7)))
    assert _moved(home) == [A]  # control: a week on, the same move is offered


def test_a_refresh_premise_never_reaches_the_steward(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    refresh = {**P_CHANGED, "on_change": "refresh"}
    _premised(home, A, _with_baseline(refresh, "", at=_iso(-10), decided=_day(-10)))
    _observe(home, A, refresh, BUS, _iso(-1))
    _observe(home, A, refresh, BUS, _iso(-0.5))
    assert _moved(home) == []


def test_a_contradicting_first_value_moves_from_the_next_night(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_ABSENT, BUS, at=_iso(0), decided=_day(),
                                      state="contradicts-claim"))
    assert _moved(home) == []  # recorded tonight: not yet
    _premised(home, A, _with_baseline(P_ABSENT, BUS, at=_iso(-1.5), decided=_day(-1),
                                      state="contradicts-claim"))
    (row,) = steward._premise_moved_inputs(home)
    assert row["moved"][0]["how"] == "contradicts-claim"  # and no seven-day wait


def test_a_ledger_premise_moves_at_once_when_the_lesson_it_names_is_retired(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    leans = {"id": "p1", "claim": f"the companion lesson {B} is still placed",
             "probe": {"kind": "ledger", "ref": B}}
    _premised(home, A, _with_baseline(leans, "routed", at=_iso(-10), decided=_day(-1)))
    assert _moved(home) == []  # control: B is placed, as recorded

    verbs.retire(home, B, covered_by="skill-md:s", no_push=True)

    (row,) = steward._premise_moved_inputs(home)
    (item,) = row["moved"]
    assert item["how"] == "ledger" and item["now"].startswith("superseded:")


def test_a_closed_follow_up_and_a_moved_premise_are_one_input(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A, follow_up={"action": "bind the unit", "unblocks_on": "the unit is bound"})
    verbs.followup_done(home, A, note="bound now", no_push=True)
    (alone,) = steward._premise_moved_inputs(home)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.5))

    (row,) = steward._premise_moved_inputs(home)
    assert [item["source"] for item in row["moved"]] == ["follow-up-done", "premise"]
    assert row["version"] != alone["version"]  # a new move is a new input


def test_the_steward_due_check_sees_a_moved_premise(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _configure_steward(home)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    cache = tmp_path / "cache"
    now = time.time()
    assert serve._steward_is_due(home, cache, now) is False  # control
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.5))
    assert serve._steward_is_due(home, cache, now) is True


# ======================================================== 3. the brief


def _brief(home: Path, row: dict) -> str:
    briefs = steward_inputs.build_briefs(
        home, [steward._brief_input(row)],
        find_record_path=ledger_ops.find_record_path, head=gitops.head_sha(home), roots=[],
    )
    return briefs[row["record"]].body


def test_the_brief_shows_the_moved_premise_and_how_to_decide_it(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)),
              P_BEHAVIOUR)
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.5))
    (row,) = steward._premise_moved_inputs(home)
    body = _brief(home, row)

    assert "premise p1 moved: the daily check saw it change on two checks in a row" in body
    assert "claim: the agent unit's BindsTo is as recorded" in body
    assert "recorded value: ''" in body and f"value now: '{BUS}'" in body
    # the behaviour premise is listed with the lesson
    assert "p2: the agent can outlive a bus restart without reconnecting [no probe" in body
    # the premises block, with the span to cite
    path = ledger_ops.find_record_path(home, A)
    lines = path.read_text(encoding="utf-8").splitlines()
    first = lines.index("premises:") + 1
    rel = path.relative_to(home).as_posix()
    assert f":{rel}#L{first}-" in body and f"L{first}: premises:" in body
    # how to decide: no case covers it, so a resolution case; the rebaseline it owes
    assert "[how to decide it] no case covers this lesson" in body
    assert "`kind: resolution` case" in body
    assert "`ids: [p1]`" in body
    assert "method section 17" in body
    assert "[evidence pack]" not in body


def test_every_lesson_brief_lists_the_lessons_premises(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    plain = _brief(home, {"record": A, "kind": "lesson"})
    assert "premises (what it rests on)" not in plain  # control: none recorded, none shown
    assert "premises: none" not in plain
    _premised(home, A, P_BEHAVIOUR)
    body = _brief(home, {"record": A, "kind": "lesson"})
    assert "premises (what it rests on):" in body
    assert "p2: the agent can outlive a bus restart without reconnecting" in body
    _premised(home, A)
    assert "premises: none (decided" in _brief(home, {"record": A, "kind": "lesson"})


# =================================================== 4. the stage rules


def _case(records: list[str], *, outcome: str, kind: str = "resolution", **extra) -> dict:
    case = {
        "kind": kind, "trigger": "nightly", "outcome": outcome, "records": records,
        "scope": "skill:s", "question": "is the lesson still true now that its premise moved?",
        "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
        "decision": {"verb": "premises", "because": "the moved value leaves it true",
                     "confidence": "settled"},
        "dependencies": {"statements": [], "user_model": [], "conditions": [],
                         "capabilities": []},
    }
    case.update(extra)
    return case


def _pair(stage: Path, name: str, case: dict, items: list[dict]) -> Path:
    _dump_yaml(stage / "cases" / f"{name}.yaml", case)
    _dump_yaml(stage / "sheets" / f"{name}.yaml",
               {"version": 1, "case": "$CASE_ID", "items": items})
    return stage / "cases" / f"{name}.yaml"


def _input(rid: str, *, predecessor: str | None = None) -> dict:
    row = {"record": rid, "kind": steward_inputs.INPUT_PREMISE_MOVED,
           "moved": [{"source": "premise", "premise": "p1", "how": "probe"}]}
    if predecessor:
        row["predecessor"] = predecessor
    return row


def test_a_decision_that_keeps_the_lesson_must_rebaseline_what_moved(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    inputs = {A: _input(A)}
    note = {"id": A, "verb": "note", "append": "checked: still true"}
    bare = _pair(stage, "bare", _case([A], outcome="no-action"), [note])

    problem = steward._pair_problem(stage, bare, home, inputs) or ""
    assert f"{A}'s premises ['p1'] moved" in problem and "rebaseline" in problem
    # control: the same pair is fine when the input is not a moved premise
    assert steward._pair_problem(stage, bare, home) is None

    for action in ({"action": "rebaseline", "ids": ["p1"]},
                   {"action": "set", "premises": [P_BEHAVIOUR]}):
        fixed = _pair(stage, "fixed", _case([A], outcome="no-action"),
                      [{"id": A, "verb": "premises", **action}])
        assert steward._pair_problem(stage, fixed, home, inputs) is None, action

    # a rebaseline naming the wrong premise does not cover it
    wrong = _pair(stage, "wrong", _case([A], outcome="no-action"),
                  [{"id": A, "verb": "premises", "action": "rebaseline", "ids": ["p2"]}])
    assert "['p1'] moved" in (steward._pair_problem(stage, wrong, home, inputs) or "")

    # a retire leaves nothing to re-record; a parked case is never applied
    gone = _pair(stage, "gone", _case([A], outcome="retire"),
                 [{"id": A, "verb": "retire", "covered_by": "skill-md:s"}])
    assert steward._pair_problem(stage, gone, home, inputs) is None
    parked = _case([A], outcome="parked", kind="parked", parked_for="overseer",
                   parked_reason="authority-unclear")
    parked["decision"]["confidence"] = "provisional"
    assert steward._pair_problem(stage, _pair(stage, "parked", parked, [note]), home, inputs) is None


def test_a_resolution_case_may_replace_a_placed_lesson_only_on_an_uncovered_moved_premise(
    tmp_path
):
    from test_e3b_agents_replace import _replace_line, _steward_case

    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    rebaseline = {"id": A, "verb": "premises", "action": "rebaseline", "ids": ["p1"]}
    first = _pair(stage, "first", _steward_case([A]), [rebaseline, _replace_line(A)])

    # control: without the input, a resolution case never replaces a placed lesson
    refused = steward._pair_problem(stage, first, home) or ""
    assert f"replace {A}: {A} is placed" in refused
    # a premise-moved input no case covers: allowed
    assert steward._pair_problem(stage, first, home, {A: _input(A)}) is None
    # covered by a case: the reconsider is the way, as before
    covered = steward._pair_problem(stage, first, home, {A: _input(A, predecessor="case-0000c101")})
    assert f"replace {A}: {A} is placed" in (covered or "")

    # the rebaseline must come BEFORE the replace: the new lesson carries the premises
    after = _pair(stage, "after", _steward_case([A]), [_replace_line(A), rebaseline])
    late = steward._pair_problem(stage, after, home, {A: _input(A)}) or ""
    assert "before its `replace` line" in late
    none = _pair(stage, "none", _steward_case([A]), [_replace_line(A)])
    assert "['p1'] moved" in (steward._pair_problem(stage, none, home, {A: _input(A)}) or "")


def test_the_contract_and_the_method_say_the_same(tmp_path):
    from self_learn import steward_prompt, worker

    contract = " ".join(steward_prompt._render_output_contract().split())
    assert "A PREMISE-MOVED INPUT (method section 17)" in contract
    assert "Never write `baseline` or `decided_at`" in contract
    for kind in premises.PROBE_KINDS:
        assert f" {kind} " in contract, kind
    method = " ".join(
        (worker.package_skill_refs() / "steward-method.md").read_text(encoding="utf-8").split()
    )
    assert "## 17. A premise that moved" in method
    assert "(A lesson that comes to you because a premise moved is different: §17.)" in method
    assert "narrowing, rewriting and retiring a placed lesson are yours without waiting" in method


# ===================================================== 5. through a run


def test_a_run_decides_a_moved_premise_with_a_rebaseline_once(tmp_path, monkeypatch, systemctl):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.5))
    systemctl.out = BUS
    _configure_steward(home)
    seen: list[str] = []

    def fake(spec):
        seen.append(spec.prompt)
        stage = _stage_dir(spec)
        for rid in re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M):
            _dump_yaml(stage / "cases" / f"{rid}.yaml", _case([rid], outcome="no-action"))
            _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
                "version": 1, "case": "$CASE_ID",
                "items": [{"id": rid, "verb": "premises", "action": "rebaseline", "ids": ["p1"],
                           "because": "the binding is intended; the lesson still holds"}],
            })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", fake)
    result = steward.run(home)

    assert result.status == "applied", result
    assert len(seen) == 1 and "[input] premise-moved" in seen[0]
    assert f"value now: '{BUS}'" in seen[0]
    (p1,) = _rec(home, A).premises or []
    assert p1["baseline"]["value_sha"] == _sha(BUS) and p1["decided_at"] == _day()
    manifest = steward.committed_manifests(home)[-1]
    assert [(row["record"], row["kind"]) for row in manifest["inputs"]] == [(A, "premise-moved")]
    # decided: never offered again, and the next run is idle
    assert steward._premise_moved_inputs(home) == []
    assert steward.run(home).status == "idle"
    assert len(seen) == 1
