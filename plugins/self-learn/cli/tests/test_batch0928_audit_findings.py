"""Batch 2026-09-28, unit G: the morning fail-state audit's findings 9, 10,
12, 13 and 14 (`misc/failstate-audit-2026-09-27/REPORT.md`, untracked).

The user's words (2026-09-28 11:54 PDT): "fix the rest of 3"; standing
since 2026-09-27 06:58: "Make the fix. Look for any other similarly
outlandish fail states." The rule: a bad item costs that item, nothing
crashes uncounted, nothing is silently lost.

Every scenario runs on a pytest sandbox ledger with fake model sessions;
the ids and texts are synthetic, and secret-shaped values are built at
runtime.
"""

from __future__ import annotations

import json

import pytest

from self_learn import miner, telemetry
from test_miner import candidate, pending_ids, shim_reader, u, write_transcript


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


# ------------------------------------------------------------ finding 13


def test_one_flagged_telemetry_line_no_longer_blocks_every_flush(tmp_path):
    """Before: one line the secret scan refused made every flush raise
    `ScanRefusal` with the spool intact -- so it was refused again on every
    later flush, and fire and recurrence events stopped reaching the
    ledger for good. Now that line is moved to a cache-only rejected file
    and the rest flushes."""
    from support import make_home

    home = make_home(tmp_path)
    telemetry.spool_event("offer-made")
    spool = next(telemetry.spool_dir().glob("*.jsonl"))
    flagged = "pass" + "word = " + "zq8Kx2mPw7Lr"
    with open(spool, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "capture", "note": flagged}) + "\n")

    report = telemetry.flush(home)
    telemetry.spool_event("offer-made")
    later = telemetry.flush(home)

    tracked = "".join(p.read_text() for p in telemetry.telemetry_dir(home).glob("*.jsonl"))
    assert tracked.count("offer-made") == 2  # positive control: both flushes moved a line
    assert report.events == 1 and later.events == 1
    assert flagged not in tracked
    assert len(report.rejected) == 1 and flagged not in report.rejected[0]
    assert flagged in (telemetry.rejected_dir() / spool.name).read_text()
    assert later.rejected == []


def test_a_spool_holding_only_a_flagged_line_is_emptied_once(tmp_path):
    """The flagged line is taken out of the spool even when nothing else
    is there to flush (so phase 2, which truncates the spool, never runs):
    a second flush finds nothing to hold back again."""
    from support import make_home

    home = make_home(tmp_path)
    telemetry.spool_dir().mkdir(parents=True, exist_ok=True)
    spool = telemetry.spool_dir() / "2026-09.testhost.jsonl"
    flagged = "pass" + "word = " + "zq8Kx2mPw7Lr"
    spool.write_text(json.dumps({"kind": "capture", "note": flagged}) + "\n", encoding="utf-8")

    first = telemetry.flush(home)
    second = telemetry.flush(home)

    assert len(first.rejected) == 1  # positive control: it was held back
    assert spool.read_text() == ""
    assert second.rejected == []
    assert (telemetry.rejected_dir() / spool.name).read_text().count(flagged) == 1


# ------------------------------------------------------------ finding 14


@pytest.fixture()
def mine_home(tmp_path, monkeypatch):
    from support import make_home

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    root = tmp_path / "transcripts"
    (root / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    miner._save_cursors({"__initialized__": "test-fixture"})
    return home, root


def test_a_hosts_file_that_does_not_load_holds_only_the_skill_candidate(mine_home, monkeypatch):
    """Before: a malformed hosts.yaml made the skill-scope check raise
    `HostsError`, which the landing loop did not catch, so the whole mine
    pass failed after its reader call, every two hours. Now only the
    skill-scoped candidate is held (its session's cursor is held, so it is
    read again once hosts.yaml loads); the user-scoped one lands."""
    home, root = mine_home
    write_transcript(root, "sess-hosts", [u("work")])
    shim_reader(monkeypatch, {
        "candidates": [
            candidate(session="sess-hosts", line=1),
            candidate(session="sess-hosts", line=2, scope="user",
                      trigger="About to rsync a whole home directory"),
        ],
        "fires": [],
    })
    (home / "hosts.yaml").write_text("hosts: [unclosed\n", encoding="utf-8")

    result = miner.run(home)

    assert result.status != "failed"
    assert len(result.landed) == 1 and len(pending_ids(home)) == 1  # positive control
    outcomes = miner.read_journal()[-1]["outcomes"]
    held = [o for o in outcomes if o["outcome"] == "dropped-invalid"]
    assert len(held) == 1 and held[0]["cursor"] == "held"
    logged = (miner.miner_dir() / "miner.log").read_text(encoding="utf-8")
    assert "held — hosts.yaml does not load (HostsError)" in logged
    assert "sess-hosts" in result.held_sessions


# ------------------------------------------------------------ finding 10


def test_a_reconsider_case_whose_outcome_does_not_fit_is_refused_alone(tmp_path, monkeypatch):
    """A lesson the user rejected has its case observed (a statement it
    rested on changed), so the steward reconsiders it; the model's
    reconsider case says `rehome`, which does not apply to a rejected
    lesson. Before: `verbs.reconsider` raised out of the run after the case
    was committed, and the next packet was never reached, run after run.
    Now that case is refused with the reason and the rest of the run --
    here a second, ordinary lesson -- is decided."""
    import re
    from pathlib import Path

    from self_learn import cases, ledger_ops, statements, steward, verbs
    from self_learn.invocation.contract import Outcome
    from self_learn.records import Record
    from support import make_home
    from test_steward import _dump_yaml, _enable_steward, _seed_fresh_proposals
    from test_steward_refusals import _notifications

    home = make_home(tmp_path)
    bad, good = _seed_fresh_proposals(home, 2)
    statement_id = statements.add(
        home, verbatim="The answer changed.",
        source={"message_ref": "transcript:session#L7"}, recorded_by="human",
    )
    original_stage = tmp_path / "original-case.yaml"
    deps = {"statements": [statement_id], "user_model": [], "conditions": [], "capabilities": []}
    _dump_yaml(original_stage, {
        "kind": "resolution", "trigger": "human", "outcome": "reject", "records": [bad],
        "scope": "skill:s", "question": "should this be retained?",
        "evidence": [{"ref": "transcript:session#L1", "quote": "old evidence"}],
        "decision": {"verb": "reject", "because": "old condition", "confidence": "settled"},
        "dependencies": deps,
    })
    original_case = cases.record(home, original_stage, actor="human")
    verbs.reject(home, bad, by="human", no_push=True)
    cases.observe(home, original_case, "statement", text="the answer changed",
                  ref=statement_id, by="steward")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts = []

    def session(spec):
        prompts.append(spec.prompt)
        match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
        stage = Path(match.group(1))
        if bad in spec.prompt:
            _dump_yaml(stage / "cases" / f"{bad}.yaml", {
                "kind": "reconsider", "trigger": "reconsider", "outcome": "rehome",
                "records": [bad], "scope": "skill:s",
                "question": "does the changed statement alter the decision?",
                "evidence": [{"ref": statement_id, "quote": "the answer changed"}],
                "decision": {"verb": "rehome", "because": "it belongs elsewhere", "confidence": "settled"},
                "dependencies": deps,
            })
            _dump_yaml(stage / "sheets" / f"{bad}.yaml", {
                "version": 1, "case": "$CASE_ID", "items": [{"id": bad, "verb": "rehome", "to": "user"}],
            })
        if f"### brief: {good}" in spec.prompt:
            _dump_yaml(stage / "cases" / f"{good}.yaml", {
                "kind": "resolution", "trigger": "nightly", "outcome": "reject",
                "records": [good], "scope": "skill:s", "question": "keep this lesson?",
                "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
                "decision": {"verb": "reject", "because": "too narrow", "confidence": "settled"},
                "dependencies": {"statements": [], "user_model": [], "conditions": [], "capabilities": []},
            })
            _dump_yaml(stage / "sheets" / f"{good}.yaml", {
                "version": 1, "case": "$CASE_ID", "items": [{"id": good, "verb": "reject"}],
            })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)

    # Positive control: the ordinary lesson was decided in the same run.
    assert Record.from_path(ledger_ops.find_record_path(home, good)).status == "rejected"
    assert good in result.decided
    # The misfit reconsider case cost only itself: the lesson is untouched.
    assert bad not in result.decided
    assert Record.from_path(ledger_ops.find_record_path(home, bad)).status == "rejected"
    journal = steward.journal_path(home).read_text(encoding="utf-8")
    assert "does not apply to a 'rejected' record" in journal
    assert any(bad in prompt for prompt in prompts)


# ------------------------------------------------------------ finding 9


def _overseer_env(tmp_path, monkeypatch):
    from support import make_home
    from test_overseer_run import _enabled

    home = make_home(tmp_path)
    _enabled(monkeypatch)
    return home


def _decided_case(home, tmp_path, rid):
    from self_learn import cases
    from self_learn.ledger_ops import create_record
    from support import commit_all, make_behavior
    from test_overseer_run import _dump

    create_record(home, make_behavior(record_id=rid))
    commit_all(home, f"seed {rid}")
    path = tmp_path / f"decided-{rid}.yaml"
    _dump(path, {
        "kind": "resolution", "trigger": "nightly", "outcome": "reject",
        "records": [rid], "scope": "skill:s", "question": "keep this lesson?",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "reject", "because": "too narrow", "confidence": "settled"},
    })
    return cases.record(home, path, actor="steward")


def _view(case_id, confidence="clear"):
    return {"id": case_id, "what_i_would_do": "reject", "why": "narrow",
            "what_evidence_decides_it": "record evidence", "confidence": confidence}


def _refused_section(home) -> str:
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    return report.split("## Refused / could not do", 1)[1]


def test_a_bad_phase_a_entry_costs_that_entry_not_the_attempt(tmp_path, monkeypatch):
    """Before: one duplicate or unknown id in selection.yaml, or one
    initial view with `confidence: high`, refused the whole attempt after
    phase A's ~9 minutes. Now each bad entry is dropped and named; the
    case whose only view was bad is de-selected (phase A's rule that every
    selected case has a view is kept that way); the rest goes on."""
    from self_learn.overseer import run as overseer_run
    from test_failstate_overseer import _ok, _phase_b_common
    from test_overseer_run import _dump

    home = _overseer_env(tmp_path, monkeypatch)
    good = _decided_case(home, tmp_path, "lrn-0c000001")
    shaky = _decided_case(home, tmp_path, "lrn-0c000002")
    phase_b_prompts = []

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {
                "cases": [{"id": good}, {"id": good}, {"id": "case-0dd0dd00"}, {"id": shaky}],
                "why_these": "oldest", "why_stopped": "enough",
            })
            _dump(stage / "initial-views.yaml", {
                "cases": [_view(good), _view(shaky, confidence="high")],
            })
        else:
            phase_b_prompts.append((stage / "selection.yaml").read_text(encoding="utf-8")
                                   + (stage / "initial-views.yaml").read_text(encoding="utf-8"))
            _phase_b_common(stage)
            _dump(stage / "findings.yaml", {"findings": [
                {"case": good, "kind": "examined", "text": "decision held"},
            ]})
            _dump(stage / "sheet.yaml", {"version": 1, "items": []})
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)

    assert result.status != "refused"
    assert result.examined == (good,)  # positive control: the good case went through
    refused = _refused_section(home)
    assert f"selection.yaml entry 2 ({good}): dropped — selected twice" in refused
    assert "selection.yaml entry 3 (case-0dd0dd00): dropped — not a case of this week's population" in refused
    assert f"initial-views.yaml entry 2 ({shaky}): dropped — confidence must be clear or close-call" in refused
    assert f"{shaky}: de-selected — no valid initial view" in refused
    # Phase B read the kept phase-A files: the good case, never the dropped.
    (seen,) = phase_b_prompts
    assert good in seen and shaky not in seen and "case-0dd0dd00" not in seen


def _two_parked_successor_run(tmp_path, monkeypatch, second_case=None, second_sheet=None):
    from self_learn.overseer import run as overseer_run
    from test_failstate_overseer import _ok, _phase_a, _phase_b_common, _successor, _two_parked
    from test_overseer_run import _dump

    home = _overseer_env(tmp_path, monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _phase_b_common(stage)
            _dump(stage / "case-a.yaml", _successor(rid_a, parked_a))
            _dump(stage / "sheet-a.yaml", {"version": 1, "items": [{"id": rid_a, "verb": "reject"}]})
            _dump(stage / "case-b.yaml", second_case(rid_b, parked_b, parked_a) if second_case else _successor(rid_b, parked_b))
            _dump(stage / "sheet-b.yaml", second_sheet(rid_b) if second_sheet else {
                "version": 1, "items": [{"id": rid_b, "verb": "reject"}],
            })
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)
    return home, result, rid_a, rid_b, parked_b


def _status(home, rid):
    from self_learn.ledger_ops import find_record_path
    from self_learn.records import Record

    return Record.from_path(find_record_path(home, rid)).status


def test_one_bad_sheet_costs_its_pair_not_the_run(tmp_path, monkeypatch):
    """Before: one sheet item with a key the sheet schema refuses refused
    the whole run (~22 minutes of phase B). Now that pair is dropped and
    named, and the other decided case applies."""
    home, result, rid_a, rid_b, parked_b = _two_parked_successor_run(
        tmp_path, monkeypatch,
        second_sheet=lambda rid: {"version": 1, "items": [
            {"id": rid, "verb": "reject", "reason": "a key reject does not take"},
        ]},
    )
    assert result.status != "refused"
    assert _status(home, rid_a) == "rejected"  # positive control: the good pair applied
    assert _status(home, rid_b) == "pending"
    refused = _refused_section(home)
    assert "case-b.yaml: dropped with sheet-b.yaml — " in refused
    assert "unknown key" in refused
    assert str(tmp_path) not in refused  # the stage's absolute path is taken out


def test_a_second_successor_for_one_parked_case_costs_that_pair(tmp_path, monkeypatch):
    """Before: two decided cases naming the same parked case refused the
    whole run. Now the second is dropped and named; the first applies."""
    from test_failstate_overseer import _successor

    home, result, rid_a, rid_b, _parked_b = _two_parked_successor_run(
        tmp_path, monkeypatch,
        second_case=lambda rid, parked, parked_a: _successor(rid, parked_a),
    )
    assert result.status != "refused"
    assert _status(home, rid_a) == "rejected"  # positive control
    assert _status(home, rid_b) == "pending"
    refused = _refused_section(home)
    assert "case-b.yaml: dropped with sheet-b.yaml — case-b.yaml: a second successor for " in refused


def test_a_secret_in_one_pair_costs_that_pair_not_the_run(tmp_path, monkeypatch):
    """Before: a scan hit anywhere in the stage refused the whole run. A
    hit in one decided case's `because` now drops that pair (nothing of it
    reaches the ledger) and the other applies. The secret is built at
    runtime."""
    import subprocess

    from test_failstate_overseer import _successor

    secret = "ghp_" + "A1b2C3d4" * 5
    home, result, rid_a, rid_b, _parked_b = _two_parked_successor_run(
        tmp_path, monkeypatch,
        second_case=lambda rid, parked, _a: _successor(rid, parked, because=f"token {secret}"),
    )
    assert result.status != "refused"
    assert _status(home, rid_a) == "rejected"  # positive control
    assert _status(home, rid_b) == "pending"
    refused = _refused_section(home)
    assert "case-b.yaml and sheet-b.yaml: dropped — the secret scan matched case-b.yaml" in refused
    grep = subprocess.run(["git", "-C", str(home), "grep", "-c", secret, "HEAD"],
                          capture_output=True, text=True)
    assert grep.returncode == 1 and grep.stdout == ""
