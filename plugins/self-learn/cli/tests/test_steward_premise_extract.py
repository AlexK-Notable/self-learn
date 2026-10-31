"""S-NEXT-u6-backfill (premise-check design, unit U6): the backfill. A placed
lesson with no `premises` field is offered to the steward as a
`premise-extract` input, so the premises of the lessons placed before
premises existed get written, a few a night; and a premise the steward finds
already false while writing them is recorded as `contradicts-claim`, which
brings the lesson back the next night as a `premise-moved` input.

What this file pins, each of it failing on master (the input kind, its
selection, its brief, its stage rule and the setting do not exist there):

* selection: a ROUTED lesson whose record has no `premises` key is an input;
  `premises: []` (decided: rests on nothing) and a written list are not; a
  pending lesson is not; a held lesson is not; its version is
  `extract:<committed blob>`, decided once, and a changed record is a new
  version;
* order and pace: `environment-specific` lessons first, then lessons whose
  covering case wrote "What would change this decision" lines, then the
  rest; at most `premises.backfill_per_night` a run (10 by default, tier C;
  0 pauses it); off with the premise check;
* a lesson with a `premise-moved` input -- taken tonight or waiting past its
  cap -- is not offered for extract;
* the scheduler's due check sees an extract input, and not a paused one;
* the brief: the lesson's generality, open follow-up, `env` pins and the
  numbered "what would change" lines of its covering cases, how to decide,
  and no transcript evidence pack;
* the stage rule: an extract input's case is `kind: resolution`, `outcome:
  no-action`, no `supersedes`, with exactly one `premises set` line on the
  lesson -- a retire, replace, note, or a reconsider case is refused; a
  parked case is not judged;
* through a run: the steward writes a premise whose first value contradicts
  its claim; the run records it as `contradicts-claim`, the lesson is not
  offered again that night, and the next night it is a `premise-moved`
  input (the oo7 replay through the backfill).

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real `~/.self-learn`). No model call. No probe runs a real
program: the `systemd-show` probe goes through a fake command runner that
fails the test on any argv outside the catalog's read-only shape. Ids, unit
names and texts are synthetic.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import (
    cases,
    gitops,
    ledger_ops,
    premises,
    serve,
    settings,
    steward,
    steward_inputs,
    steward_prompt,
    verbs,
    worker,
)
from self_learn.invocation.contract import Outcome
from self_learn.records import Record
from support import commit_all, make_behavior, make_env, proposal_dict
from test_steward import _configure_steward, _dump_yaml, _stage_dir
from test_steward_inputs import _publish_disposition
from test_steward_premise_moved import (
    BUS,
    P_ABSENT,
    P_BEHAVIOUR,
    FakeSystemctl,
    _case,
    _iso,
    _observe,
    _pair,
    _premised,
    _rec,
    _sha,
    _with_baseline,
)

A = "lrn-f6e00001"
B = "lrn-f6e00002"
C = "lrn-f6e00003"
D = "lrn-f6e00004"

EXTRACT = steward_inputs.INPUT_PREMISE_EXTRACT


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    # A user-scope placement compiles into ~/.claude: never the real one.
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


@pytest.fixture
def systemctl(tmp_path, monkeypatch) -> FakeSystemctl:
    fake = FakeSystemctl()
    monkeypatch.setattr(
        verbs, "_premise_probe_env",
        lambda home: premises.ProbeEnv(home=tmp_path / "fake-home", ledger_home=Path(home),
                                       runner=fake, path_env="/usr/bin"),
    )
    return fake


# ------------------------------------------------------------- helpers


def _routed(env, rid: str, *, generality: str | None = None, env_pins: dict | None = None,
            **route_kwargs) -> str:
    ledger = env.ledger
    record = make_behavior(record_id=rid, scope="skill:s")
    if generality is not None:
        record.set_generality(generality)
    if env_pins is not None:
        record.set_env(env_pins)
    ledger_ops.create_record(ledger, record)
    ledger_ops.write_proposal(ledger, rid, proposal_dict(scope="skill:s"))
    commit_all(ledger, f"seed {rid}")
    verbs.route(ledger, rid, dest="skill-md", no_push=True, **route_kwargs)
    return rid


def _pending(env, rid: str) -> str:
    ledger_ops.create_record(env.ledger, make_behavior(record_id=rid, scope="skill:s"))
    commit_all(env.ledger, f"seed {rid}")
    return rid


def _extract(home: Path, **kwargs) -> list[str]:
    return [row["record"] for row in steward._premise_extract_inputs(home, **kwargs)]


def _backfill(home: Path, n: int) -> None:
    (home / "config.yaml").write_text(f"premises:\n  backfill_per_night: {n}\n", encoding="utf-8")
    commit_all(home, f"backfill {n} a night")


def _case_index(rows: list[dict]):
    """`cases.list_cases` over *rows*: the overseer's holds (`parked_for=`)
    are found empty, every other query gets every row."""

    def list_cases(home_, *, parked_for=None, **kwargs):
        return [] if parked_for is not None else [dict(row) for row in rows]

    return list_cases


def _would_change(by_case: dict[str, list[str]]):
    """`cases.show` whose Decision section lists *by_case*'s bullets under
    "What would change this decision:" (and nothing for any other case)."""

    def show(home_, case_id, evidence_only=True):
        bullets = by_case.get(case_id, [])
        decision = "- verb: route\n- because: the host had nothing then\n"
        if bullets:
            decision += "\nWhat would change this decision:\n" + "".join(f"- {b}\n" for b in bullets)
        return SimpleNamespace(sections={"Decision": decision})

    return show


def _brief(home: Path, row: dict) -> str:
    briefs = steward_inputs.build_briefs(
        home, [steward._brief_input(row)],
        find_record_path=ledger_ops.find_record_path, head=gitops.head_sha(home), roots=[],
    )
    return briefs[row["record"]].body


def _extract_input(rid: str) -> dict:
    return {"record": rid, "kind": EXTRACT}


# ============================================================ 1. selection


def test_a_placed_lesson_with_no_premises_is_an_extract_input(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _pending(env, A)
    # control: a pending lesson is not placed, so it is not offered
    assert _extract(home) == []

    _routed(env, B)
    (row,) = steward._premise_extract_inputs(home)
    assert steward_inputs.INPUT_PREMISE_EXTRACT == "premise-extract"
    assert EXTRACT in steward_inputs.INPUT_KINDS
    assert (row["record"], row["kind"], row["record_status"]) == (B, EXTRACT, "routed")
    path = ledger_ops.find_record_path(home, B)
    _rel, blob = steward._committed_blob(home, path)
    assert row["version"] == row["blob"] == f"extract:{blob}"
    assert "predecessor" not in row  # nothing to supersede
    assert row["reason"] and steward._brief_input(row)["reason"] == row["reason"]


def test_a_written_list_and_an_empty_list_are_never_offered(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    for rid in (A, B, C):
        _routed(env, rid)
    assert _extract(home) == [A, B, C]  # control: none has the field

    _premised(home, A, P_BEHAVIOUR)
    _premised(home, B)  # `premises: []`: decided, it rests on nothing
    assert _rec(home, B).premises == []
    assert _extract(home) == [C]
    found = {record.id for _path, record in steward_inputs.routed_without_premises(home)}
    assert found == {C}


def test_a_held_lesson_is_not_offered(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    monkeypatch.setattr(cases, "held_lessons", lambda home_: {A: [{"case": "case-0000aaaa"}]})
    assert _extract(home) == [B]


def test_a_decided_version_is_not_offered_again_and_a_changed_record_is(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    (row,) = steward._premise_extract_inputs(home)

    # a decision recorded under a `lesson` input's identity (the bare blob)
    # does not decide the extract input: the prefix keeps the two apart
    bare = row["version"].removeprefix("extract:")
    _publish_disposition(home, A, bare, "applied", "run-f6e000000001")
    assert _extract(home) == [A]

    _publish_disposition(home, A, row["version"], "parked", "run-f6e000000002")
    assert _extract(home) == []

    # a record that changed for another reason is a new version
    path = ledger_ops.find_record_path(home, A)
    record = Record.from_path(path)
    record.set_env({"exampletool": "1.0"})
    record.write(path)
    commit_all(home, f"a later edit of {A}")
    (again,) = steward._premise_extract_inputs(home)
    assert again["version"] != row["version"] and again["version"].startswith("extract:")


def test_the_committed_blobs_are_read_in_one_call(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    a, b = (ledger_ops.find_record_path(home, rid) for rid in (A, B))
    never = a.parent / "lrn-ffffffff.md"  # not committed: absent, so it waits
    outside = tmp_path / "elsewhere.md"   # outside the ledger: absent
    blobs = steward._committed_blobs(home, [a, b, never, outside])
    # positive control: the one-call read agrees with the per-file read
    assert blobs == {
        a: steward._committed_blob(home, a)[1],
        b: steward._committed_blob(home, b)[1],
    }


def test_off_with_the_premise_check(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    assert _extract(home) == [A]  # control
    monkeypatch.setattr(steward_inputs, "premises_enabled", lambda home_: False)
    assert _extract(home) == []


# ===================================================== 2. order and pace


def test_the_backfill_offers_environment_specific_then_would_change_then_the_rest(
    tmp_path, monkeypatch
):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A, generality="general-practice")
    _routed(env, B, generality="environment-specific")
    _routed(env, C)
    _routed(env, D)
    rows = [
        {"case": "case-0000c001", "opened_at": "2026-09-22T06:00:00Z", "records": [C]},
        {"case": "case-0000d001", "opened_at": "2026-09-22T06:00:00Z", "records": [D]},
        # a superseded case's prediction no longer stands
        {"case": "case-0000d002", "opened_at": "2026-09-23T06:00:00Z", "records": [D],
         "superseded_by": "case-0000d003"},
    ]
    monkeypatch.setattr(cases, "list_cases", _case_index(rows))
    monkeypatch.setattr(cases, "show", _would_change({
        "case-0000c001": ["a drop-in binds the unit to the bus"],
        "case-0000d002": ["the old prediction"],
    }))

    # control: unordered, the order is the ledger's
    assert _extract(home, ordered=False) == [A, B, C, D]
    assert _extract(home) == [B, C, A, D]
    assert steward_inputs.extract_rank(home, _rec(home, B), []) == (
        steward_inputs.EXTRACT_RANK_ENVIRONMENT
    )

    _backfill(home, 2)
    assert _extract(home) == [B, C]
    assert _extract(home, limit=1) == [B]


def test_the_pace_is_ten_by_default_tier_c_and_zero_pauses_it(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    setting = settings.by_name("premises.backfill_per_night")
    assert (setting.default, setting.tier, setting.override_channel) == (10, "C", False)
    assert steward_inputs.premise_backfill_per_night(home) == 10
    _routed(env, A)
    assert _extract(home) == [A]
    _backfill(home, 0)
    assert steward_inputs.premise_backfill_per_night(home) == 0
    assert _extract(home) == []


def test_ten_a_night_from_a_larger_backlog(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    ids = [f"lrn-f6e001{n:02d}" for n in range(12)]
    for rid in ids:
        _routed(env, rid)
    assert _extract(home) == ids[:10]


# ======================================== 3. a moved premise comes first


def test_a_lesson_whose_move_waits_is_not_offered_for_extract(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A, follow_up={"action": "bind the unit", "unblocks_on": "the unit is bound"})
    _routed(env, B)
    verbs.followup_done(home, A, note="bound now", no_push=True)

    rows = steward._premise_inputs(home, exclude=set())
    assert [(row["record"], row["kind"]) for row in rows] == [
        (A, steward_inputs.INPUT_PREMISE_MOVED), (B, EXTRACT),
    ]
    # past the nightly cap A's move waits, and A is still not offered for extract
    monkeypatch.setattr(steward_inputs, "PREMISE_MOVED_PER_RUN", 0)
    rows = steward._premise_inputs(home, exclude=set())
    assert [(row["record"], row["kind"]) for row in rows] == [(B, EXTRACT)]
    # an earlier input of the run that names B keeps B out too
    assert steward._premise_inputs(home, exclude={B}) == []


# ===================================================== 4. the due check


def test_the_steward_due_check_sees_an_extract_input_and_not_a_paused_one(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    cache = tmp_path / "cache"
    now = time.time()
    _configure_steward(home)  # the shared setup pauses the backfill
    assert serve._steward_is_due(home, cache, now) is False
    _configure_steward(home, premise_backfill=10)
    assert serve._steward_is_due(home, cache, now) is True


# ========================================================= 5. the brief


def test_the_brief_gives_what_is_needed_to_write_premises(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A, generality="environment-specific", env_pins={"exampletool": "0.56.2"},
            follow_up={"action": "bind the unit to the bus", "unblocks_on": "a drop-in exists"})
    rows = [{"case": "case-0000a001", "opened_at": "2026-09-22T06:00:00Z", "records": [A]}]
    monkeypatch.setattr(cases, "list_cases", _case_index(rows))
    monkeypatch.setattr(cases, "show", _would_change({
        "case-0000a001": ["a drop-in binds the unit to the bus", "the guard re-checks"],
    }))
    (row,) = steward._premise_extract_inputs(home)
    body = _brief(home, row)

    assert "[input] premise-extract" in body
    assert "[why it is here]" in body and "[why it is back]" not in body
    assert "[what to write]" in body
    assert "generality as recorded: environment-specific" in body
    assert "what it asks for: bind the unit to the bus" in body
    assert "it is to be closed when: a drop-in exists" in body
    assert "exampletool 0.56.2" in body
    assert "[what the case that covers it (case-0000a001) said would change it]" in body
    assert "  [1] a drop-in binds the unit to the bus" in body
    assert "  [2] the guard re-checks" in body
    assert "the host had nothing then" not in body  # only the list, never the decision
    assert "`kind: resolution` case with `outcome: no-action`" in body
    assert "`premise_probe`" in body and "`premises: []`" in body
    assert "contradicting the claim" in body
    assert "method section 17" in body
    assert "[evidence pack]" not in body


def test_a_lesson_no_case_covers_says_so(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    body = _brief(home, {"record": A, "kind": EXTRACT, "reason": "no premises"})
    assert "[covering case] none" in body
    assert "said would change it]" not in body


# =================================================== 6. the stage rule


def _extract_case(records: list[str], **extra) -> dict:
    case = _case(records, outcome="no-action")
    case["question"] = "what does this placed lesson rest on?"
    case["decision"]["because"] = "it rests on one unit binding"
    case.update(extra)
    return case


def test_an_extract_case_writes_premises_and_nothing_else(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    inputs = {A: _extract_input(A)}
    write = {"id": A, "verb": "premises", "action": "set", "premises": [P_ABSENT]}

    good = _pair(stage, "good", _extract_case([A]), [write])
    assert steward._pair_problem(stage, good, home, inputs) is None
    empty = _pair(stage, "empty", _extract_case([A]), [{**write, "premises": []}])
    assert steward._pair_problem(stage, empty, home, inputs) is None

    retire = {"id": A, "verb": "retire", "covered_by": "skill-md:s"}
    note = {"id": A, "verb": "note", "append": "checked"}
    for name, case, items, fragment in (
        ("retire", _case([A], outcome="retire"), [retire], "outcome 'retire'"),
        ("both", _extract_case([A]), [write, note], "got ['premises set', 'note']"),
        ("noted", _extract_case([A]), [note], "got ['note']"),
        ("rebase", _extract_case([A]), [{"id": A, "verb": "premises", "action": "rebaseline",
                                         "ids": ["p1"]}], "got ['premises rebaseline']"),
        ("recon", _extract_case([A], kind="reconsider", supersedes="case-0000a001"), [write],
         "kind 'reconsider'"),
        ("super", _extract_case([A], supersedes="case-0000a001"), [write],
         "supersedes 'case-0000a001'"),
    ):
        path = _pair(stage, name, case, items)
        problem = steward._pair_problem(stage, path, home, inputs) or ""
        assert "came to you only for" in problem and fragment in problem, (name, problem)
        assert "`premise-moved` input" in problem, name

    # control: the same retire is not this rule's business without the input
    retired = _pair(stage, "retire", _case([A], outcome="retire"), [retire])
    assert "came to you only for" not in (steward._pair_problem(stage, retired, home) or "")
    # a parked case is never applied: not judged
    parked = _case([A], outcome="parked", kind="parked", parked_for="overseer",
                   parked_reason="authority-unclear")
    parked["decision"]["confidence"] = "provisional"
    path = _pair(stage, "parked", parked, [retire])
    assert steward._pair_problem(stage, path, home, inputs) is None


# =================================================== 7. contract and method


def test_the_contract_and_the_method_say_the_same():
    contract = " ".join(steward_prompt._render_output_contract().split())
    assert "WRITING PREMISES (method section 17). With every `route`" in contract
    assert "A PREMISE-EXTRACT INPUT is a placed lesson with no premises recorded" in contract
    method = " ".join(
        (worker.package_skill_refs() / "steward-method.md").read_text(encoding="utf-8").split()
    )
    assert "**Writing premises.** With every `route`, put a `premises` line" in method
    assert "**A `premise-extract` input** is a placed lesson with no premises recorded" in method
    # integration 2026-10-31 (u6 gate MINOR): at route time the case id is
    # not minted yet, so the method no longer asks for `source: <case id>#...`;
    # the "What would change" line names the premise instead.
    assert "write that condition as a premise and name the premise's id in the line" in method
    assert "`source: <case id>#what_would_change[<n>]`" not in method
    # and premises about where the lesson sits are left to code (design M3)
    assert "Do not write premises about where the lesson sits" in method
    assert "You can try a probe first with the `premise_probe` tool" in method


# ======================================================== 8. through a run


def _extract_fake(seen: list[str]):
    """A steward that writes, for every premise-extract brief, a case whose
    one line sets a premise the probe will show is already false."""

    def fake(spec):
        seen.append(spec.prompt)
        stage = _stage_dir(spec)
        for rid in re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M):
            _dump_yaml(stage / "cases" / f"{rid}.yaml", _extract_case([rid]))
            _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
                "version": 1, "case": "$CASE_ID",
                "items": [{"id": rid, "verb": "premises", "action": "set",
                           "premises": [P_ABSENT, P_BEHAVIOUR],
                           "because": "the lesson says the unit is not bound"}],
            })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return fake


def test_a_run_writes_premises_and_a_false_one_comes_back_the_next_night(
    tmp_path, monkeypatch, systemctl
):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    systemctl.out = f"{BUS}\n"  # the unit IS bound: the claim is already false
    _configure_steward(home, premise_backfill=10)
    seen: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session", _extract_fake(seen))

    result = steward.run(home)

    assert result.status == "applied", result
    assert len(seen) == 1 and "[input] premise-extract" in seen[0]
    manifest = steward.committed_manifests(home)[-1]
    ((rid, kind, version),) = [
        (row["record"], row["kind"], row["version"]) for row in manifest["inputs"]
    ]
    assert (rid, kind) == (A, EXTRACT) and version.startswith("extract:")
    p1, p2 = _rec(home, A).premises or []
    assert p1["baseline"]["state"] == "contradicts-claim"
    assert p1["baseline"]["value_sha"] == _sha(BUS)
    assert p2["probe"] is None
    # the record's status is unchanged: the placement stands
    assert _rec(home, A).status == "routed"

    # the same night: neither an extract input (it has premises) nor a moved one
    assert steward._premise_extract_inputs(home) == []
    assert steward._premise_moved_inputs(home) == []
    assert steward.run(home).status == "idle"
    assert len(seen) == 1

    # the next night: the contradicting first value makes it a premise-moved input
    _premised(home, A, _with_baseline(P_ABSENT, BUS, at=_iso(-1.5), decided=p1["decided_at"],
                                      state="contradicts-claim"), P_BEHAVIOUR)
    assert steward._premise_moved_inputs(home) == []  # the sweep has not looked since
    _observe(home, A, P_ABSENT, BUS, _iso(-0.5))  # the night's sweep: the claim is still false
    (row,) = steward._premise_moved_inputs(home)
    assert row["record"] == A and row["moved"][0]["how"] == "contradicts-claim"
