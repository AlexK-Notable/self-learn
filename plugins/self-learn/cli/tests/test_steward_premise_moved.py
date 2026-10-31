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
  premises and refuses a premise whose claim is false now, a probe that
  cannot observe refuses the line and writes nothing, the dry run says so
  first, a write that landed on the record while the probes ran is kept,
  and the commit is found by the execution evidence;
* a written premise makes a `premise-moved` input exactly when the daily
  sweep (U2) confirms the move (`premise_sweep.confirmed_moves`, read
  through the sweep's own cache: the seam test runs the real sweep twice);
  a probe move waits seven days after the premise was decided, a
  `contradicts-claim` or `ledger` move does not; `on_change: refresh` never
  reaches the steward; a value that comes back after two decisions is
  offered again;
* the brief shows the moved premise with its recorded and current values,
  the record's premises block to cite, and how to decide (no `reject`, a
  `route` move, `set` for a claim that is false now); every lesson brief
  lists the lesson's premises and its broken probes;
* the stage check refuses a `no-action` decision that does not re-record the
  moved premise, lets a `replace` stand without one, and lets a `kind:
  resolution` case replace or move a placed lesson only on a
  `premise-moved` input no case covers; the batch applies that move as a
  reroute for the steward only;
* end to end, a fake steward decides the input with a rebaseline, and it is
  never offered again.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real `~/.self-learn`). No model call. No probe runs a real
program: every `systemd-show` probe goes through a fake command runner that
fails the test on any argv outside the catalog's read-only shape. Ids, unit
names and texts are synthetic.
"""

from __future__ import annotations

import dataclasses
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
    premise_sweep,
    premises,
    serve,
    steward,
    steward_inputs,
    telemetry,
    verbs,
)
from self_learn.invocation.contract import Outcome
from self_learn.records import Record
from support import commit_all, git, last_verb_sha, make_behavior, make_env, proposal_dict
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
DAY = 24 * 3600


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
    # `route` spools two telemetry events; the first batch would flush them in
    # a commit of their own and move HEAD under a test that compares it
    telemetry.flush(ledger, push=False)
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


def _cache(home: Path) -> Path:
    """The cache the sweep writes and the steward reads (one per home)."""
    return premise_sweep.default_cache_dir(home)


def _store(home: Path, rid: str, pid: str, observation: premises.Observation) -> None:
    """One sweep observation of the lesson's premise *pid* as it stands on
    the record, written the way the sweep writes it (`premise_sweep._row`,
    its own row maker and signature): the steward reads it only through
    `premise_sweep.confirmed_moves`, so the shape is the sweep's to own."""
    premise = next(p for p in _rec(home, rid).premises or [] if p["id"] == pid)
    kind = (
        premise_sweep.KIND_LEDGER if (premise.get("probe") or {}).get("kind") == "ledger"
        else premise_sweep.KIND_PROBE
    )
    history = premise_sweep.read_history(_cache(home))
    row = premise_sweep._row(
        observation.observed_at, rid, pid, kind, observation,
        sig=premise_sweep._premise_sig(premise),
    )
    history.setdefault((rid, pid), []).append(row)
    premise_sweep._store_history(_cache(home), history)


def _observe(home: Path, rid: str, premise: dict, value: str | None, at: str) -> None:
    """One sweep observation of *value* (`None`: `unavailable`)."""
    if value is None:
        observation = premises.unavailable_observation("systemctl is not installed", observed_at=at)
    else:
        observation = premises.observation_from_value(value, premise=premise, observed_at=at)
    _store(home, rid, str(premise["id"]), observation)


def _moved(home: Path) -> list[str]:
    return [row["record"] for row in steward._premise_moved_inputs(home)]


class FakeSystemctl:
    """The probe runner the verb gets: answers `LoadState` with `loaded`
    (the unit exists, U1's first read), prints *out* for the property,
    records every argv, and fails the test on any argv but the catalog's
    read-only `show`. ``calls`` holds the property reads, ``load_calls``
    the LoadState reads."""

    def __init__(self, out: str = "") -> None:
        self.out = out
        self.fail: BaseException | None = None
        self.calls: list[list[str]] = []
        self.load_calls: list[list[str]] = []
        self.during: object = None

    def __call__(self, argv, env, timeout):
        assert argv[:3] == ["systemctl", "--user", "show"] and "--no-ask-password" in argv, argv
        if self.fail is not None:
            raise self.fail
        if "LoadState" in argv:
            self.load_calls.append(list(argv))
            return premises.CommandResult(0, b"loaded\n", b"")
        self.calls.append(list(argv))
        if callable(self.during):
            self.during()  # something else writes while the probe runs
        return premises.CommandResult(0, self.out.encode("utf-8"), b"")


def _show(prop: str) -> list[str]:
    return [
        "systemctl", "--user", "show", "--no-pager", "--no-ask-password",
        "--property", prop, "--value", "--", UNIT,
    ]


@pytest.fixture
def systemctl(tmp_path, monkeypatch) -> FakeSystemctl:
    fake = FakeSystemctl()
    monkeypatch.setattr(
        verbs, "_premise_probe_env",
        lambda home: premises.ProbeEnv(home=tmp_path / "fake-home", ledger_home=Path(home),
                                       runner=fake, path_env="/usr/bin"),
    )
    return fake


def _sheet(tmp_path: Path, items: list[dict], name: str = "sheet", **top) -> batch.Sheet:
    path = tmp_path / f"{name}.yaml"
    _dump_yaml(path, {"version": 1, **top, "items": items})
    return batch.load_sheet(path)


def _apply(home: Path, tmp_path: Path, items: list[dict]) -> batch.ItemResult:
    result = batch.run(home, _sheet(tmp_path, items), no_push=True, actor="steward")
    (got,) = result.items
    return got


def _subject(home: Path) -> str:
    """The newest verb commit's subject: the telemetry flush a batch ends with
    rides on top of it (`support.last_verb_sha`)."""
    return git(home, "log", "-1", "--format=%s", last_verb_sha(home)).stdout.strip()


def _body(home: Path) -> str:
    return git(home, "log", "-1", "--format=%B", last_verb_sha(home)).stdout


# ================================================ 1. the `premises` verb


def test_set_runs_each_probe_once_and_records_what_it_saw(tmp_path, systemctl):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    systemctl.out = "\n"

    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                   "premises": [P_ABSENT, P_BEHAVIOUR]}])

    assert (got.state, got.rc) == ("applied", 0), got
    # one probe, run once, in the catalog's read-only shape (U1 reads the
    # unit's LoadState first, the same command for another property)
    assert systemctl.calls == [_show("BindsTo")]
    assert systemctl.load_calls == [_show("LoadState")]
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
                                    "premises": [P_CHANGED, P_BEHAVIOUR, other]}]).state == "applied"
    before = {p["id"]: p for p in _rec(home, A).premises or []}

    systemctl.out = f"{BUS}\n"
    systemctl.calls.clear()
    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "rebaseline",
                                   "ids": ["p1"], "because": "the bus binding is now intended"}])

    assert (got.state, got.rc) == ("applied", 0), got
    assert systemctl.calls == [_show("BindsTo")]  # only the named premise's probe
    after = {p["id"]: p for p in _rec(home, A).premises or []}
    assert after["p1"]["baseline"]["value_sha"] == _sha(BUS)
    assert after["p1"]["baseline"]["state"] == "holds"  # judged by its value: no claim to break
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


def test_a_rebaseline_of_a_claim_that_is_false_now_is_refused(tmp_path, systemctl):
    """Gate round 1 (MINOR): re-recording a claim-judged premise whose value
    now contradicts its claim would store `contradicts-claim` and leave the
    lesson standing on a premise that says its own claim is false."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    systemctl.out = "\n"
    assert _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                    "premises": [P_ABSENT]}]).state == "applied"
    (held,) = _rec(home, A).premises or []
    assert held["baseline"]["state"] == "holds"  # control: the claim held when written

    systemctl.out = f"{BUS}\n"
    record_bytes = ledger_ops.find_record_path(home, A).read_bytes()
    line = {"id": A, "verb": "premises", "action": "rebaseline", "ids": ["p1"]}
    (shown,) = batch.dry_run(home, _sheet(tmp_path, [line]), actor="steward").items
    assert (shown.state, shown.kind) == ("would-refuse", "bad-line"), shown
    got = _apply(home, tmp_path, [line])
    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert "claim is false now" in str(got.detail) and "action set" in str(got.detail)
    assert ledger_ops.find_record_path(home, A).read_bytes() == record_bytes

    # control: rewriting the claim as what is true now is `set`'s job, and applies
    true_now = {**P_ABSENT, "claim": "the agent unit is bound to the session bus",
                "holds_if": "present"}
    assert _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                    "premises": [true_now]}]).state == "applied"
    (p1,) = _rec(home, A).premises or []
    assert p1["baseline"]["state"] == "holds" and p1["baseline"]["value_sha"] == _sha(BUS)


def test_a_write_that_lands_while_the_probes_run_is_kept(tmp_path, systemctl):
    """Gate round 1 (MINOR): the probes run before the commit lock. A write
    to the same record in that window (here a person's confirmation) used
    to be overwritten by the copy read before the probes ran."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    systemctl.out = "\n"
    path = ledger_ops.find_record_path(home, A)

    def confirm() -> None:
        record = Record.from_path(path)
        record.set_last_confirmed("2026-10-30")
        record.write(path)
        commit_all(home, "a person confirms the lesson")

    systemctl.during = confirm
    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "set",
                                   "premises": [P_CHANGED]}])

    assert got.state == "applied", got
    record = _rec(home, A)
    assert str(record.last_confirmed) == "2026-10-30"  # the other write survived
    assert [p["id"] for p in record.premises or []] == ["p1"]  # and so did this one

    # the premises themselves changed meanwhile: refused, the other write stands
    def rewrite() -> None:
        record = Record.from_path(path)
        record.set_premises([P_BEHAVIOUR])
        record.write(path)
        commit_all(home, "someone else rewrote the premises")

    systemctl.during = rewrite
    got = _apply(home, tmp_path, [{"id": A, "verb": "premises", "action": "rebaseline",
                                   "ids": ["p1"]}])
    assert got.state == "refused", got
    assert "changed while its probes ran" in str(got.detail)
    assert [p["id"] for p in _rec(home, A).premises or []] == ["p2"]


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
    assert systemctl.calls == [] and systemctl.load_calls == []


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


def test_the_real_sweep_twice_makes_the_input(tmp_path, systemctl):
    """Gate round 1 (BLOCKER): the steward reads the sweep's own answer.
    Nothing here writes the cache by hand: `premise_sweep.run` runs twice,
    a day apart, through the same fake `systemctl`, and the steward sees
    the move."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    systemctl.out = f"{BUS}\n"
    probe_env = premises.ProbeEnv(home=tmp_path / "fake-home", runner=systemctl,
                                  path_env="/usr/bin")
    claude = tmp_path / "fake-home" / ".claude"
    now = time.time()

    first = premise_sweep.run(home, _cache(home), now=now - 2 * DAY, env=probe_env,
                              claude_dir=claude)
    assert first.status == "ok", first
    assert _moved(home) == []  # one sweep is not enough
    second = premise_sweep.run(home, _cache(home), now=now - DAY, env=probe_env,
                               claude_dir=claude)
    assert second.status == "ok", second

    (row,) = steward._premise_moved_inputs(home)
    assert row["record"] == A and row["kind"] == steward_inputs.INPUT_PREMISE_MOVED
    (item,) = row["moved"]
    assert (item["source"], item["premise"], item["how"], item["now"]) == (
        "premise", "p1", "probe", BUS
    )
    assert len(systemctl.calls) == 2  # one probe read per sweep


def test_a_probe_premise_moves_on_two_agreeing_sweeps_after_its_baseline(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    at = _iso(-10)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=at, decided=_day(-10)))
    assert _moved(home) == []  # control: nothing observed yet

    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    assert _moved(home) == []  # one sweep is not enough

    _observe(home, A, P_CHANGED, BUS, _iso(-0.01))
    (row,) = steward._premise_moved_inputs(home)
    assert row["kind"] == steward_inputs.INPUT_PREMISE_MOVED and row["record"] == A
    (item,) = row["moved"]
    assert (item["source"], item["premise"], item["how"]) == ("premise", "p1", "probe")
    assert (item["recorded"], item["now"], item["recorded_at"]) == ("", BUS, at)
    assert row["version"] == steward_inputs.premise_moved_version(moved=[("p1", _sha(BUS), at)])
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
    for n in range(2):
        _observe(home, A, P_CHANGED, None, _iso(-3 + n))
    assert steward_inputs.broken_probes(home) == {}  # control: two are not three
    _observe(home, A, P_CHANGED, None, _iso(-1))
    (broken,) = steward_inputs.broken_probes(home)[A]
    assert broken["premise"] == "p1" and "systemctl is not installed" in broken["reason"]
    assert steward_inputs.moved_premises(home) == {}
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


def test_the_week_s_wait_is_per_lesson_not_per_premise(tmp_path):
    """Integration 2026-10-31 (u4 gate MINOR): 02 §3a.10.5 (5) allows one
    probe-triggered re-decision per LESSON per seven days. A lesson whose
    other premise was decided two days ago waits, even though the premise
    that moved was decided ten days ago."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    moved = _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10))
    _premised(home, A, moved)
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.5))
    assert _moved(home) == [A]  # control: alone, the ten-day-old premise moves it
    other = {"id": "p2", "claim": "the agent unit's BindsTo was re-checked", "probe": PROBE}
    _premised(home, A, moved, _with_baseline(other, BUS, at=_iso(-2), decided=_day(-2)))
    assert _moved(home) == []


def test_a_refresh_premise_never_reaches_the_steward(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    refresh = {**P_CHANGED, "on_change": "refresh"}
    _premised(home, A, _with_baseline(refresh, "", at=_iso(-10), decided=_day(-10)))
    _observe(home, A, refresh, BUS, _iso(-1))
    _observe(home, A, refresh, BUS, _iso(-0.5))
    assert _moved(home) == []
    # control: the same observations of a re-decide premise do move it
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    assert _moved(home) == [A]


def test_a_contradicting_first_value_moves_on_the_next_sweep_without_waiting(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_ABSENT, BUS, at=_iso(-1.5), decided=_day(-1),
                                      state="contradicts-claim"))
    assert _moved(home) == []  # the sweep has not looked since it was written
    _observe(home, A, P_ABSENT, BUS, _iso(-0.5))
    (row,) = steward._premise_moved_inputs(home)
    # one sweep is enough, and no seven-day wait (decided yesterday)
    assert row["moved"][0]["how"] == "contradicts-claim"


def test_a_ledger_premise_moves_on_the_first_sweep_that_sees_the_change(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    leans = {"id": "p1", "claim": f"the companion lesson {B} is still placed",
             "probe": {"kind": "ledger", "ref": B}}
    ledger_env = premises.ProbeEnv(ledger_home=home)

    def looked(at: str) -> premises.Observation:
        # the real ledger probe, stamped at a chosen time (the sweep stamps
        # its own); a row counts only when it is later than the baseline
        seen = premises.observe(leans, ledger_env)
        assert seen is not None and seen.state == premises.OBS_OK, seen
        return dataclasses.replace(seen, observed_at=at)

    _premised(home, A, {**leans, "baseline": premises.make_baseline(looked(_iso(-10))),
                        "decided_at": _day(-1)})
    _store(home, A, "p1", looked(_iso(-1)))
    assert _moved(home) == []  # control: B is placed, as recorded

    verbs.retire(home, B, covered_by="skill-md:s", no_push=True)
    _store(home, A, "p1", looked(_iso(-0.1)))

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


def test_a_value_that_comes_back_after_two_decisions_is_offered_again():
    """Gate round 1 (MINOR): A to B (decided, rebaselined to B), back to A
    (decided, rebaselined to A), then to B again. With the value alone in
    the version, the third move hashed like the first, already decided, and
    was never offered. The baseline's time is in it now."""
    first = steward_inputs.premise_moved_version(
        moved=[("p1", _sha("B"), "2026-10-01T03:00:00Z")])  # baseline A, recorded Oct 1
    second = steward_inputs.premise_moved_version(
        moved=[("p1", _sha("A"), "2026-10-10T03:00:00Z")])  # baseline B, rebaselined Oct 10
    third = steward_inputs.premise_moved_version(
        moved=[("p1", _sha("B"), "2026-10-20T03:00:00Z")])  # baseline A again, Oct 20
    assert len({first, second, third}) == 3
    # a park or a refusal leaves the baseline, and so the version, as it was
    assert first == steward_inputs.premise_moved_version(
        moved=[("p1", _sha("B"), "2026-10-01T03:00:00Z")])
    # a two-element pair hashes as it always did (U8 adds a basis since its fix round 2)
    assert steward_inputs.premise_moved_version(moved=[("p1", "aaa")]) == (
        steward_inputs.premise_moved_version(moved=[["p1", "aaa"]])
    )


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


def _decide_block(body: str) -> str:
    return body.split("[how to decide it]", 1)[1]


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
    # how to decide: no case covers it, so a resolution case; the outcomes of
    # 02 section 3a.10.7 (a move included, `reject` not one of them)
    decide = _decide_block(body)
    assert decide.startswith(" no case covers this lesson")
    assert "`kind: resolution` case" in decide
    assert "`action: rebaseline`, `ids: [p1]`" in decide
    assert "`route` with an explicit `dest`" in decide and "`retire`" in decide
    assert "`replace`" in decide and "park it" in decide
    assert "reject" not in decide
    assert "Narrowing, rewriting, moving or retiring" in decide
    assert "method section 17" in decide
    assert "[evidence pack]" not in body


def test_a_moved_claim_is_rewritten_with_set_not_rebaselined(tmp_path):
    """Gate round 1 (MINOR): a claim-judged premise moved because its claim
    is false now; the brief must not tell the steward to rebaseline it."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_ABSENT, "", at=_iso(-10), decided=_day(-10)))
    _observe(home, A, P_ABSENT, BUS, _iso(-1))
    _observe(home, A, P_ABSENT, BUS, _iso(-0.5))
    (row,) = steward._premise_moved_inputs(home)
    decide = _decide_block(_brief(home, row))
    assert "`action: set` with a list in which p1 says what is true now" in decide
    assert "`ids: [p1]`" not in decide


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


@pytest.mark.parametrize("kind", ["lesson", "suspected-violation", "premise-moved"])
def test_a_broken_probe_is_shown_on_every_brief_of_its_lesson(tmp_path, kind):
    """Gate round 1 (MINOR), 02 section 3a.10.5 (3): a probe the sweep could
    not observe three times running shows in the lesson's brief the next
    time it comes up, for any input kind, not only when something else on
    the lesson moved."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    row = {"record": A, "kind": kind}
    for n in range(2):
        _observe(home, A, P_CHANGED, None, _iso(-3 + n))
    assert "[broken probes]" not in _brief(home, row)  # control: two are not three
    _observe(home, A, P_CHANGED, None, _iso(-1))
    body = _brief(home, row)
    assert "[broken probes]" in body
    assert "p1: systemd-show" in body and "systemctl is not installed" in body


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


def _input(rid: str, *, predecessor: str | None = None, holds_if: str = "changed") -> dict:
    row = {"record": rid, "kind": steward_inputs.INPUT_PREMISE_MOVED,
           "moved": [{"source": "premise", "premise": "p1", "how": "probe",
                      "holds_if": holds_if}]}
    if predecessor:
        row["predecessor"] = predecessor
    return row


def test_a_no_action_decision_must_rebaseline_what_moved(tmp_path):
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


def test_a_moved_claim_is_covered_by_a_set_and_not_by_a_rebaseline(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    inputs = {A: _input(A, holds_if="absent")}
    rebaseline = _pair(stage, "rebaseline", _case([A], outcome="no-action"),
                       [{"id": A, "verb": "premises", "action": "rebaseline", "ids": ["p1"]}])
    problem = steward._pair_problem(stage, rebaseline, home, inputs) or ""
    assert f"{A}'s premises ['p1'] moved" in problem
    assert "a rebaseline of a false claim is refused" in problem
    # control: the same line covers a value-judged premise
    assert steward._pair_problem(stage, rebaseline, home, {A: _input(A)}) is None
    rewritten = _pair(stage, "set", _case([A], outcome="no-action"),
                      [{"id": A, "verb": "premises", "action": "set", "premises": [P_BEHAVIOUR]}])
    assert steward._pair_problem(stage, rewritten, home, inputs) is None


def test_a_resolution_case_may_replace_a_placed_lesson_only_on_an_uncovered_moved_premise(
    tmp_path
):
    from test_e3b_agents_replace import _replace_line, _steward_case

    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    first = _pair(stage, "first", _steward_case([A]), [_replace_line(A)])

    # control: without the input, a resolution case never replaces a placed lesson
    refused = steward._pair_problem(stage, first, home) or ""
    assert f"replace {A}: {A} is placed" in refused
    # a premise-moved input no case covers: allowed, and a replace owes no
    # rebaseline (02 section 3a.10.7 asks that of `no-action` alone)
    assert steward._pair_problem(stage, first, home, {A: _input(A)}) is None
    # covered by a case: the reconsider is the way, as before
    covered = steward._pair_problem(stage, first, home, {A: _input(A, predecessor="case-0000c101")})
    assert f"replace {A}: {A} is placed" in (covered or "")
    # a premises line before the replace is still welcome
    rebaseline = {"id": A, "verb": "premises", "action": "rebaseline", "ids": ["p1"]}
    both = _pair(stage, "both", _steward_case([A]), [rebaseline, _replace_line(A)])
    assert steward._pair_problem(stage, both, home, {A: _input(A)}) is None


def test_a_resolution_case_may_move_a_placed_lesson_only_on_an_uncovered_moved_premise(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    move = [{"id": A, "verb": "route", "dest": "claude-md"}]
    pair = _pair(stage, "move", _case([A], outcome="route"), move)

    # control: a resolution case may not move a placed lesson on another input
    assert f"route {A}: {A} is placed" in (steward._pair_problem(stage, pair, home) or "")
    covered = steward._pair_problem(stage, pair, home, {A: _input(A, predecessor="case-0000c101")})
    assert f"route {A}: {A} is placed" in (covered or "")
    # a premise-moved input no case covers: the move rule lets it through
    assert steward._steward_move_problem(
        home, _case([A], outcome="route"), move, label="move.yaml",
        uncovered_moved=frozenset({A}),
    ) is None
    # a reconsider case moves a placed lesson as it always could
    assert steward._steward_move_problem(
        home, _case([A], outcome="route", kind="reconsider"), move, label="move.yaml",
    ) is None


def test_the_batch_applies_that_move_as_a_reroute_for_the_steward_only(tmp_path):
    """02 section 3a.10.7, `route`: "the lesson moves (`batch` applies it as
    `reroute`)". A covered lesson (B) still moves only through a reconsider
    case, as U3b pinned."""
    from test_u3b_steward_authority import _record_case, _route_through_a_case

    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)  # placed by the verb alone: no case covers it
    setup = tmp_path / "setup"
    setup.mkdir()
    _route_through_a_case(home, setup, B)  # placed by a case: covered
    line = {"verb": "route", "dest": "claude-md"}

    # the preview, before the case is recorded: widened only for the named ids
    staged = _sheet(tmp_path, [{"id": A, **line}], name="staged")
    (plain,) = batch.dry_run(home, staged, actor="steward").items
    assert plain.state == "would-refuse", plain  # control: a routed lesson's route
    (widened,) = batch.dry_run(home, staged, actor="steward", rerouted={A}).items
    assert widened.state == "would-apply", widened.detail

    case_id = _record_case(home, setup, _case([A], outcome="route"))
    sheet_path = tmp_path / "move.yaml"
    _dump_yaml(sheet_path, {"version": 1, "case": case_id, "items": [{"id": A, **line}]})
    human = batch.run(home, batch.load_sheet(sheet_path, home=home), no_push=True, actor="human")
    assert human.items[0].state == "refused", human.items[0]  # control: not a person's sheet
    assert (_rec(home, A).routing or {}).get("destination") == "skill-md"

    moved = batch.run(home, batch.load_sheet(sheet_path, home=home), no_push=True, actor="steward")
    assert moved.items[0].state == "applied", moved.items[0].detail
    assert "rerouted (premise moved)" in str(moved.items[0].detail)
    assert (_rec(home, A).routing or {}).get("destination") == "claude-md"

    # a lesson a case covers is not moved by a resolution case
    other = _record_case(home, setup, _case([B], outcome="route"))
    _dump_yaml(sheet_path, {"version": 1, "case": other, "items": [{"id": B, **line}]})
    kept = batch.run(home, batch.load_sheet(sheet_path, home=home), no_push=True, actor="steward")
    assert kept.items[0].state == "refused", kept.items[0]
    assert (_rec(home, B).routing or {}).get("destination") == "skill-md"


def test_the_steward_previews_its_staged_move_as_the_reroute_it_will_be(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    _pair(stage, "move", _case([A], outcome="route"),
          [{"id": A, "verb": "route", "dest": "claude-md"}])
    assert steward._ledger_repair_message(home, stage, {A: "routed"}) is None
    # control: without the widening the ledger refuses the routed lesson's route
    monkeypatch.setattr(steward, "_rerouted_by", lambda case_data: frozenset())
    assert A in (steward._ledger_repair_message(home, stage, {A: "routed"}) or "")


def test_the_contract_and_the_method_say_the_same(tmp_path):
    """The method's text is the premise-spec lane's (S-NEXT-premise,
    steward-method section 17); this lane writes none of its own, so the
    method half of this test passes once that lane has landed with it."""
    from self_learn import steward_prompt, worker

    contract = " ".join(steward_prompt._render_output_contract().split())
    assert "A PREMISE-MOVED INPUT (method section 17)" in contract
    assert "Outcomes: `no-action`, `replaced`, `retire`, `route`, or park." in contract
    assert "a rebaseline of it is refused" in contract
    assert "Never write `baseline` or `decided_at`" in contract
    for kind in premises.PROBE_KINDS:
        assert f" {kind} " in contract, kind
    method = " ".join(
        (worker.package_skill_refs() / "steward-method.md").read_text(encoding="utf-8").split()
    )
    assert "## 17. A premise that moved" in method
    assert "(A lesson that comes to you because a premise moved is different: §17.)" in method
    assert (
        "narrowing, rewriting, moving and retiring a placed lesson are yours without the overseer"
        in method
    )


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
