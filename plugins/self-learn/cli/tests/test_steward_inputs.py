"""U3a (2026-09-27) -- what the steward reads (spec 02-schema.md §3a.8).

The user, 2026-09-26: the pipeline is "a series of builders ... miner
finds lesson material > steward builds lessons > overseer builds a
coherent system out of those lessons"; on retiring the analyst, "basically,
i think i agree with you"; on suspected violations, "do both a and b".

Covers: a lesson with no analyst proposal is selected, and its identity is
the RECORD's committed blob (a run decided under the old proposal identity
still counts); packets follow U2's groups (a same-session pair together, an
11th related lesson spills, never more than 5 unrelated); the evidence pack
shows each quote's verdict with the corrected ref; the shared part of the
brief stays byte-identical with real packs; a suspected-violation fire is
an input once and never again after its case; the run record carries the
data points.

Synthetic transcripts only, under ``tmp_path`` (this repository is public).
No real model call (the fakes write the stage files), no embedding call
(``SELF_LEARN_EMBED_PROVIDER=none``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from self_learn import (
    cli,
    ledger_ops,
    refs,
    steward,
    steward_inputs,
    steward_prompt,
    telemetry,
    verbs,
)
from self_learn.index.store import LessonIndex
from self_learn.invocation.contract import Outcome
from self_learn.invocation_sdk.backend import SdkOutcome
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env, proposal_dict
from test_steward import _configure_steward, _dump_yaml, _stage_dir, _write_decision_stage

SID = "11111111-2222-3333-4444-555555555555"
OTHER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
THIRD = "99999999-8888-7777-6666-555555555555"
PROJ = "-work-repo"


# ------------------------------------------------------------ fixtures


def _ts(n: int) -> str:
    return f"2026-09-01T10:{n // 60:02d}:{n % 60:02d}.000Z"


def _user(text: str, n: int) -> dict:
    return {"type": "user", "uuid": f"u-{n}", "timestamp": _ts(n), "cwd": "/work/repo",
            "origin": {"kind": "human"}, "promptSource": "typed",
            "message": {"role": "user", "content": text}}


def _asst(text: str, n: int) -> dict:
    return {"type": "assistant", "uuid": f"a-{n}", "timestamp": _ts(n), "cwd": "/work/repo",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _write_session(root: Path, session: str, entries: list[dict]) -> None:
    path = root / PROJ / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Transcript roots under tmp_path only; word search only."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPT_ROOTS", str(root))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    _write_session(root, SID, [
        _user("please stop the container before editing the storage files", 1),
        _asst("stopping the container first, then editing", 2),
        _user("the storage folder was written while it ran and it got clobbered", 3),
        _asst("understood; I will always stop it first", 4),
    ])
    _write_session(root, OTHER, [
        _user("an unrelated turn about lights", 1),
        _asst("the kill command matched its own shell and stopped itself", 2),
    ])
    _write_session(root, THIRD, [
        _user("nothing to see here", 1),
        _asst("I ran the command and checked the result", 2),
    ])
    return root


def _behavior(rid: str, *, scope: str = "skill:s", evidence=None, created_at=None,
              trigger: str | None = None, instruction: str | None = None) -> Record:
    return Record.create(
        type="behavior", scope=scope, source="session", kind="anti-pattern",
        trigger=trigger or f"About to edit storage for case {rid}.",
        instruction=instruction or f"Stop the container first ({rid}).",
        evidence=evidence, record_id=rid, created_at=created_at,
    )


def _ev(session: str, line: int, quote: str | None) -> dict:
    item = {"session": session, "ts": "2026-09-01T11:00:00Z",
            "origin": f"transcript:{session}#L{line}"}
    if quote is not None:
        item["quote"] = quote
    return item


def _blob(home: Path, path: Path) -> str:
    rel = path.relative_to(home).as_posix()
    return git(home, "rev-parse", f"HEAD:{rel}").stdout.strip()


def _publish_disposition(home: Path, rid: str, version: str, state: str, run_id: str) -> None:
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": run_id,
        "started_at": "2026-09-23T00:00:00Z", "status": "complete",
        "packets": [{
            "index": 1, "inputs": [{"record": rid, "version": version}], "records": [rid],
            "dispositions": {rid: {"state": state, "input_version": version,
                                   "case": "case-0000beef"}},
        }],
    }, reason=f"a {state} row")


def _selected(home: Path) -> list[str]:
    return [entry.record.id for entry, _row in steward._eligible_lessons(home)]


# ------------------------------------------------ 1. eligibility, identity


def test_a_lesson_with_no_analyst_proposal_is_selected(tmp_path, roots):
    home = make_env(tmp_path).ledger
    ledger_ops.create_record(home, _behavior("lrn-a0000001"))
    commit_all(home, "one pending lesson, no proposal")
    entry = next(e for b in steward.discover_buckets(home) for e in ledger_ops.queue(b))
    # positive control: it really has no proposal, which the old
    # eligibility predicate called "unanalyzed" and skipped
    assert not entry.proposal_path.exists()
    assert ledger_ops.is_unanalyzed(entry)

    rows = steward._eligible_lessons(home)
    assert [e.record.id for e, _ in rows] == ["lrn-a0000001"]
    row = rows[0][1]
    assert row["version"] == _blob(home, entry.path)
    assert row["kind"] == "lesson" and row["record_status"] == "pending"
    assert "proposal" not in row and "legacy_version" not in row


def test_identity_is_the_record_and_changes_when_the_record_changes(tmp_path, roots):
    home = make_env(tmp_path).ledger
    ledger_ops.create_record(home, _behavior("lrn-a0000002"))
    ledger_ops.write_proposal(home, "lrn-a0000002", proposal_dict())
    commit_all(home, "a lesson with a proposal")
    (_entry, row), = steward._eligible_lessons(home)
    first = row["version"]
    record_path = ledger_ops.find_record_path(home, "lrn-a0000002")
    assert first == _blob(home, record_path)
    assert row["legacy_version"] == _blob(home, record_path.parent.parent / "proposals" / "lrn-a0000002.yaml")

    _publish_disposition(home, "lrn-a0000002", first, "parked", "run-aaaaaaaa0001")
    assert _selected(home) == [], "decided at this version: not offered again"

    # an analyst proposal rewritten beside the record changes nothing ...
    proposal = proposal_dict()
    proposal["rationale"] = "a second opinion"
    ledger_ops.write_proposal(home, "lrn-a0000002", proposal)
    commit_all(home, "proposal rewritten")
    assert _selected(home) == []

    # ... an edit to the record is a new version, needing a new decision
    text = record_path.read_text(encoding="utf-8").replace(
        "Stop the container first", "Stop the container and wait first"
    )
    record_path.write_text(text, encoding="utf-8")
    commit_all(home, "record edited")
    (_entry, row), = steward._eligible_lessons(home)
    assert row["version"] != first and row["version"] == _blob(home, record_path)


def test_a_version_decided_under_the_proposal_identity_is_still_decided(tmp_path, roots):
    """Every run record before U3a keyed its dispositions by the PROPOSAL
    blob. A lesson parked for the overseer then stays pending; without the
    bridge it would be offered again every night."""
    home = make_env(tmp_path).ledger
    for rid in ("lrn-a0000003", "lrn-a0000004"):
        ledger_ops.create_record(home, _behavior(rid))
        ledger_ops.write_proposal(home, rid, proposal_dict())
    commit_all(home, "two lessons with proposals")
    assert _selected(home) == ["lrn-a0000003", "lrn-a0000004"], "positive control"
    proposal = ledger_ops.find_record_path(home, "lrn-a0000003").parent.parent / "proposals" / "lrn-a0000003.yaml"
    _publish_disposition(home, "lrn-a0000003", _blob(home, proposal), "parked", "run-aaaaaaaa0002")

    assert _selected(home) == ["lrn-a0000004"]


# --------------------------------------------------------- 2. the batches


def _index(home: Path) -> LessonIndex:
    index = LessonIndex.open(home)
    index.build(None)
    return index


def test_packets_follow_the_groups_and_respect_both_caps(tmp_path, roots):
    home = make_env(tmp_path).ledger
    # eleven lessons from ONE session: all related; seven lessons with no
    # evidence in seven different buckets' worth of words: unrelated
    related = [f"lrn-b00000{n:02x}" for n in range(1, 12)]
    for n, rid in enumerate(related, start=1):
        ledger_ops.create_record(home, _behavior(
            rid, evidence=[_ev(SID, 3, "the storage folder was written")],
            created_at=f"2026-01-{n:02d}T00:00:00Z",
        ))
    lonely = [f"lrn-c00000{n:02x}" for n in range(1, 8)]
    words = ["kayak", "violin", "glacier", "turnip", "saxophone", "lantern", "quartz"]
    for n, (rid, word) in enumerate(zip(lonely, words), start=1):
        ledger_ops.create_record(home, _behavior(
            rid, trigger=f"About the {word} alone.", instruction=f"Mind the {word}.",
            created_at=f"2026-02-{n:02d}T00:00:00Z",
        ))
    commit_all(home, "eighteen lessons")
    index = _index(home)
    try:
        plans, grouping = steward_inputs.plan_packets(related + lonely, index, 10)
    finally:
        index.close()

    sizes = [len(p.members) for p in plans]
    assert all(size <= 10 for size in sizes)
    assert all(len(p.unrelated) <= 5 for p in plans)
    # the one session's lessons: ten together, the eleventh spills over
    homes = [sorted(set(p.members) & set(related)) for p in plans]
    assert sorted(len(h) for h in homes if h) == [1, 10]
    first = next(p for p in plans if len(set(p.members) & set(related)) == 10)
    assert first.links and all("session" in link["reasons"] for link in first.links)
    assert first.basis_counts["lexical"] > 0
    # every lesson in exactly one packet
    assert sorted(rid for p in plans for rid in p.members) == sorted(related + lonely)
    assert grouping["max_size"] == 10 and grouping["max_unrelated"] == 5


def test_a_same_session_pair_lands_in_one_packet_through_the_run(tmp_path, roots, monkeypatch):
    home = make_env(tmp_path).ledger
    _configure_steward(home, packet_size=10)
    # the pair is oldest and newest; six unrelated lessons sit between them
    ledger_ops.create_record(home, _behavior(
        "lrn-d0000001", evidence=[_ev(SID, 1, "please stop the container")],
        created_at="2026-01-01T00:00:00Z"))
    words = ["kayak", "violin", "glacier", "turnip", "saxophone", "lantern"]
    for n, word in enumerate(words, start=2):
        ledger_ops.create_record(home, _behavior(
            f"lrn-d00000{n:02x}", trigger=f"About the {word} alone.",
            instruction=f"Mind the {word}.", created_at=f"2026-01-{n:02d}T00:00:00Z"))
    ledger_ops.create_record(home, _behavior(
        "lrn-d00000ff", evidence=[_ev(SID, 3, "the storage folder was written")],
        created_at="2026-03-01T00:00:00Z"))
    commit_all(home, "eight lessons")
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)

    result = steward.run(home, dry_run=True)

    run = json.loads((steward.steward_dir(home) / "runs" / result.run_id / "run.json").read_text())
    packets = [p["records"] for p in run["packets"]]
    together = [p for p in packets if "lrn-d0000001" in p]
    assert "lrn-d00000ff" in together[0], packets
    assert all(len(p) <= 10 for p in packets)
    assert all(len(p["group"]["unrelated"]) <= 5 for p in run["packets"])
    assert run["grouping"]["index"]["mode"] == "lexical-only"
    assert "SELF_LEARN_EMBED_PROVIDER=none" in run["grouping"]["index"]["mode_reason"]


# --------------------------------------------------- 3. the evidence pack


def test_the_pack_shows_exact_not_found_and_other_session_with_the_corrected_ref(tmp_path, roots):
    home = make_env(tmp_path).ledger
    rid = "lrn-e0000001"
    ledger_ops.create_record(home, _behavior(rid, evidence=[
        _ev(SID, 3, "the storage folder was written while it ran"),        # exact
        _ev(SID, 4, "the user confirmed it twice, loudly"),                 # not found
        _ev(SID, 2, "the kill command matched its own shell"),              # in OTHER, line 2
    ]))
    commit_all(home, "one lesson, three evidence items")
    inputs = [{"id": rid, "kind": "lesson"}]

    briefs = steward_inputs.build_briefs(
        home, inputs, find_record_path=ledger_ops.find_record_path, head="0" * 40,
    )
    body = briefs[rid].body

    assert "[evidence pack] 3 item(s)" in body
    items = re.split(r"\n  item \d+: ", body)
    assert "verdict: exact" in items[1]
    assert "verdict: not_found -- NOT FOUND" in items[2]
    assert "this evidence does not check out" in items[2]
    assert "verdict: other_session" in items[3]
    assert f"corrected ref: session {OTHER}" in items[3]
    assert f"(cite transcript:{OTHER}#L2)" in items[3]
    # the excerpt names who spoke on each line and marks the cited line
    assert "L3 user:  <- this line the storage folder was written" in items[1]
    assert "L2 assistant:" in items[1]
    # the stats the run record keeps
    assert briefs[rid].stats["verdicts"] == {"exact": 1, "not_found": 1, "other_session": 1}
    assert briefs[rid].stats["excerpt_chars"] > 0
    # the record is citable by its own file lines
    assert "[record] ledger@000000000000:skills/s/pending/lrn-e0000001.md" in body
    assert re.search(r"Instruction \(L\d+\):\n    Stop the container first", body)


def test_a_second_copy_of_one_moment_is_one_sighting(tmp_path, roots):
    home = make_env(tmp_path).ledger
    fork = "12121212-3434-5656-7878-909090909090"
    entries = [json.loads(line) for line in
               (roots / PROJ / f"{SID}.jsonl").read_text().splitlines()]
    _write_session(roots, fork, entries)  # a resumed copy: same uuids
    rid = "lrn-e0000002"
    ledger_ops.create_record(home, _behavior(rid, evidence=[
        _ev(SID, 3, "the storage folder was written"),
        _ev(fork, 3, "the storage folder was written"),
    ]))
    commit_all(home, "one lesson, two copies of one moment")

    brief = steward_inputs.build_briefs(
        home, [{"id": rid}], find_record_path=ledger_ops.find_record_path)[rid]

    assert "same transcript moment as item 1" in brief.body
    assert brief.stats["excerpted"] == 1 and brief.stats["same_moment"] == 1


def test_the_shared_part_stays_byte_identical_with_real_packs(tmp_path, roots):
    home = make_env(tmp_path).ledger
    for rid, line in (("lrn-e0000003", 1), ("lrn-e0000004", 3)):
        ledger_ops.create_record(home, _behavior(rid, evidence=[_ev(SID, line, None)]))
    commit_all(home, "two lessons")
    items = steward.conditions.steward_feed(home, [("lrn-e0000003", {}), ("lrn-e0000004", {})])
    packets = []
    for n, rid in enumerate(("lrn-e0000003", "lrn-e0000004"), start=1):
        run = steward_prompt.RunContext(
            run_id="run-shared0001", stage_dir=tmp_path / "stage" / str(n), packet_index=n,
            packet_count=2, last_run_at=None, verbs_the_runner_executes=("batch",))
        packets.append(steward_prompt.assemble(
            home, tmp_path / "cache", run, [{"id": rid}], conditions_items=items))
    # positive control: each packet's pack is in its own part
    assert "[evidence pack] 1 item(s)" in packets[0].per_packet
    assert "L1 user:" in packets[0].per_packet and "L3 user:" in packets[1].per_packet
    assert packets[0].shared.encode() == packets[1].shared.encode()
    for packet in packets:
        assert "[evidence pack]" not in packet.shared and "lrn-e000000" not in packet.shared


# ------------------------------------------- 4. suspected rule violations


def _routed(home: Path, rid: str) -> None:
    ledger_ops.create_record(home, make_behavior(record_id=rid))
    ledger_ops.write_proposal(home, rid, proposal_dict())
    commit_all(home, "pending")
    assert cli.main(["route", rid, "--no-push"]) == 0


def _fire(home: Path, rid: str, *, line: int = 2, outcome: str = "suspected-violation",
          session: str = OTHER) -> str:
    before = {e.get("nonce") for e in telemetry.read_events(home)}
    telemetry.spool_event("fire", record=rid, origin=f"transcript:{session}#L{line}",
                          outcome=outcome)
    telemetry.flush(home)
    return next(e["nonce"] for e in telemetry.read_events(home)
                if e.get("kind") == "fire" and e.get("nonce") not in before)


@pytest.fixture
def ledger(tmp_path, roots, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    return env.ledger


def _confirm_stage(spec):
    """A fake steward: for every suspected-violation brief, one no-action
    case whose sheet confirms each event the brief lists."""
    stage = _stage_dir(spec)
    for rid, body in re.findall(r"^### brief: (lrn-[0-9a-f]{8})\n(.*?)(?=^### |\Z)",
                                spec.prompt, re.M | re.S):
        events = re.findall(r"^  event ([0-9a-f]+): ", body, re.M)
        _dump_yaml(stage / "cases" / f"{rid}.yaml", {
            "kind": "resolution", "trigger": "nightly", "outcome": "no-action",
            "records": [rid], "scope": "skill:s",
            "question": "did the session act against this routed rule?",
            "evidence": [{"ref": f"transcript:{OTHER}#L2", "quote": "matched its own shell"}],
            "decision": {"verb": "confirm-recurrence", "because": "the excerpt shows it",
                         "confidence": "settled"},
            "dependencies": {"statements": [], "user_model": [], "conditions": [],
                             "capabilities": []},
        })
        _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "confirm-recurrence", "event": nonce}
                      for nonce in events] or [{"id": rid, "verb": "confirm-held"}],
        })
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


def test_a_suspected_violation_fire_is_an_input_once_and_never_after_its_case(ledger, monkeypatch):
    home = ledger
    rid = "lrn-f0000001"
    _routed(home, rid)
    compliance = _fire(home, rid, outcome="suspected-compliance")
    nonce = _fire(home, rid)
    _configure_steward(home)

    rows = steward._suspected_violation_inputs(home)
    assert [r["record"] for r in rows] == [rid]
    assert [e["nonce"] for e in rows[0]["events"]] == [nonce], "compliance is not an input"
    assert compliance != nonce

    seen = []

    def _fake(spec):
        seen.append(spec.prompt)
        return _confirm_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", _fake)
    result = steward.run(home)
    assert result.status == "applied", result
    # the brief showed the event, its resolved pointer and an excerpt
    assert f"  event {nonce}: " in seen[0]
    assert f"ref: session {OTHER}" in seen[0]
    assert "L2 assistant:  <- this line the kill command matched its own shell" in seen[0]
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert [r.get("ref") for r in record.recurrences] == [nonce]

    assert steward._suspected_violation_inputs(home) == []
    assert steward.run(home).status == "idle"
    assert len(seen) == 1

    # a later fire about the same rule is a new input carrying only itself
    later = _fire(home, rid, line=2)
    rows = steward._suspected_violation_inputs(home)
    assert [e["nonce"] for e in rows[0]["events"]] == [later]


def test_a_parked_suspected_violation_is_not_offered_again(ledger, monkeypatch):
    home = ledger
    rid = "lrn-f0000002"
    _routed(home, rid)
    _fire(home, rid)
    _configure_steward(home)

    def _park(spec):
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / "p.yaml", {
            "kind": "parked", "trigger": "nightly", "outcome": "parked",
            "parked_for": "overseer", "parked_reason": "authority-unclear",
            "records": [rid], "scope": "skill:s", "question": "whose call is this?",
            "evidence": [{"ref": f"transcript:{OTHER}#L2", "quote": "matched its own shell"}],
            "decision": {"verb": "confirm-recurrence", "because": "unsure",
                         "confidence": "provisional"},
            "dependencies": {"statements": [], "user_model": [], "conditions": [],
                             "capabilities": []},
        })
        _dump_yaml(stage / "sheets" / "p.yaml", {
            "version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "confirm-held"}]})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", _park)
    steward.run(home)
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert record.recurrences == (), "positive control: nothing handled the event"
    assert steward._suspected_violation_inputs(home) == []


def test_the_recurrence_verbs_take_a_suspected_violation_fire(ledger):
    home = ledger
    rid = "lrn-f0000003"
    _routed(home, rid)
    violation = _fire(home, rid)
    compliance = _fire(home, rid, outcome="suspected-compliance")
    other = _fire(home, rid)

    verbs.confirm_recurrence(home, rid, event_ref=violation, no_push=True)
    with pytest.raises(verbs.SheetLineError):
        verbs.confirm_recurrence(home, rid, event_ref=compliance, no_push=True)
    verbs.dismiss_suspect(home, rid, event_ref=other, why="rule-followed", no_push=True)

    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert [r["ref"] for r in record.recurrences] == [violation]
    assert record.dismissed_suspects[0]["basis"] == "fire-suspected-violation"
    assert steward._suspected_violation_inputs(home) == []


# ------------------------------------------------------- 5. data points


def test_the_run_record_carries_the_data_points(tmp_path, roots, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _configure_steward(home)
    for rid, line in (("lrn-a1000001", 3), ("lrn-a1000002", 1)):
        ledger_ops.create_record(home, _behavior(rid, evidence=[
            _ev(SID, line, "no such words were ever typed")]))
    commit_all(home, "two lessons from one session")

    def _fake(spec):
        _write_decision_stage(spec)
        return SdkOutcome(
            ok=True, rc=0, stdout="", detail="", failure=None, turns=3,
            tool_events=(
                {"kind": "tool_use", "id": "1", "name": "Read",
                 "input": {"file_path": f"{roots}/{PROJ}/{SID}.jsonl"}},
                {"kind": "tool_result", "tool_use_id": "1", "is_error": False, "content": "x"},
                {"kind": "tool_use", "id": "2", "name": "Read",
                 "input": {"file_path": f"{home}/skills/s/pending/lrn-a1000001.md"}},
                {"kind": "tool_use", "id": "3", "name": "Write",
                 "input": {"file_path": "cases/x.yaml", "content": "..."}},
            ),
        )

    monkeypatch.setattr(steward.invocation, "write_session", _fake)
    result = steward.run(home)
    assert result.status == "applied", result

    manifest = json.loads(git(home, "show", f"HEAD:cases/runs/{result.run_id}.json").stdout)
    assert manifest["grouping"]["basis"] in ("lexical", "none")
    assert manifest["grouping"]["index"]["mode"] == "lexical-only"
    packet, = manifest["packets"]
    assert packet["records"] == ["lrn-a1000001", "lrn-a1000002"]
    assert packet["group"]["basis_counts"] == {"cosine": 0, "lexical": 1, "none": 0}
    assert any("session" in link["reasons"] for link in packet["group"]["links"])
    attempt = packet["attempts"][0]
    assert attempt["brief"]["lessons"] == 2
    assert attempt["brief"]["verdicts"] == {"not_found": 2}
    assert attempt["brief"]["pack_chars"] > 0 and attempt["brief"]["brief_chars"] > 0
    assert attempt["reads"] == {
        "tool_uses": 3, "transcript_reads": 1, "ledger_record_reads": 1,
        "by_tool": {"Read": 2, "Write": 1},
    }


def test_a_fake_without_tool_events_reports_no_reads():
    assert steward_inputs.tool_reads(
        Outcome(ok=True, rc=0, stdout="", detail="", failure=None), Path("/h")) is None
    assert refs.VERDICTS  # the verdict vocabulary the pack extends is U1's


def test_an_excerpt_skips_relayed_rows_that_say_nothing(tmp_path, roots):
    """Measured on the live queue: an empty attachment (``{}``) and the
    harness's token notice took context slots in most excerpts."""
    home = make_env(tmp_path).ledger
    noise = {"type": "attachment", "uuid": "at-2", "timestamp": _ts(2),
             "attachment": {"type": "reminder", "content": "<total_tokens>12 left</total_tokens>"}}
    empty = {"type": "attachment", "uuid": "at-3", "timestamp": _ts(3),
             "attachment": {"type": "reminder", "content": "{}"}}
    session = "34343434-5656-7878-9090-121212121212"
    _write_session(roots, session, [
        _user("first real turn about the storage", 1), noise, empty,
        _asst("the cited answer about the storage", 4),
    ])
    rid = "lrn-e0000005"
    ledger_ops.create_record(home, _behavior(rid, evidence=[_ev(session, 4, "the cited answer")]))
    commit_all(home, "one lesson")

    body = steward_inputs.build_briefs(
        home, [{"id": rid}], find_record_path=ledger_ops.find_record_path)[rid].body

    assert "L4 assistant:  <- this line the cited answer" in body
    assert "L1 user: first real turn" in body, "positive control: the real neighbour is kept"
    assert "total_tokens" not in body and "L3 relay" not in body


def test_a_lesson_sent_back_before_the_change_is_still_shown_as_sent_back(tmp_path, roots):
    home = make_env(tmp_path).ledger
    rid = "lrn-a0000006"
    ledger_ops.create_record(home, _behavior(rid))
    ledger_ops.write_proposal(home, rid, proposal_dict())
    commit_all(home, "one lesson")
    (_entry, row), = steward._eligible_lessons(home)
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": "run-aaaaaaaa0006",
        "started_at": "2026-09-23T00:00:00Z", "status": "complete",
        "packets": [{"index": 1, "inputs": [], "records": [rid], "dispositions": {rid: {
            "state": "returned", "input_version": row["legacy_version"],
            "case": "case-0000beef", "reason": "the line was refused"}}}],
    }, reason="a returned row under the proposal identity")

    assert steward._returned_for(home, [row]) == {
        rid: {"case": "case-0000beef", "lines": ["the line was refused"]}
    }
    assert rid in _selected(home), "returned is not decided: it comes back"
