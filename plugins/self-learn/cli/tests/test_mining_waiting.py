"""Waiting answers (new-miner R2, fix round 4; the user's design): each
checked answer is saved before anything of it lands, the session's cursor
and the judged-uuid store move at that save, and every run that is not a
preview lands the waiting answers oldest first, item by item, never asking
the model again because a landing failed. Families are gone.

The gate probes of rounds 3 and 4 are regression tests here, adapted only
where they asserted family-rule internals: each shows every output landing
exactly once, nothing lost, and no session called again because its landing
failed. Synthetic transcripts and ledgers only; the backend is the engine
tests' fake.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from self_learn import cli, gitops, intents, miner, telemetry
from self_learn.mining import check, contract, engine, flags as flags_mod
from self_learn.mining import waiting as mining_waiting
from self_learn.records import Record
from support import commit_all, git
from test_mining_engine import (  # noqa: F401 -- fixtures
    Backend, FakeOutcome, _called, _flagged, _sighting, _store_rows, _waiting, asst, backend, cursor, home, host,
    journal_last, lesson, output, pending, put_record, root, run, run_dir, session_rows, typed, write_session,
)


def _fork_rows(rows: list[dict], fork: str, n: int, tmp_path: Path, text: str = "and add the export to the nightly job"):
    return [dict(r, sessionId=fork) for r in rows] + [
        typed(fork, n, text, host(tmp_path)), asst(fork, n + 1, "Added.", host(tmp_path))]


def _rc(rid: str, line: int = 4) -> dict:
    return {"record": rid, "outcome": "suspected-violation", "situation": {"line": line}, "action": None}


def _flag_all(monkeypatch, *rids: str) -> None:
    def flagged(index, stretches, **kw):
        return flags_mod.FlagResult(tuple(flags_mod.Flag(r, 2, 4, 5, 0.9, None, 1.0, "rule") for r in rids),
                                    "lexical-only", "")

    monkeypatch.setattr(engine.flags_mod, "flag_rules", flagged)


def _events(home: Path, kind: str) -> list[dict]:
    return [e for e in telemetry.read_events(home) if e.get("kind") == kind]


def _rec(result) -> dict:
    return json.loads((run_dir(result) / "run.json").read_text())


def _rows(result) -> dict[str, dict]:
    return {r["session"]: r for r in _rec(result)["sessions"]}


def _fail_fire(m, rid: str | None = None) -> None:
    real = telemetry.spool_event

    def broken(kind, **kw):
        if kind == "fire" and (rid is None or kw.get("record") == rid):
            raise OSError("synthetic fire did not land")
        return real(kind, **kw)

    m.setattr(telemetry, "spool_event", broken)


class _Busy:
    def __enter__(self):
        raise gitops.GitOpsError("synthetic lock unavailable")

    def __exit__(self, *args):
        return False


def _pending_hashes() -> dict[str, str]:
    folder = mining_waiting.pending_dir(miner.miner_dir())
    if not folder.exists():
        return {}
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


def _crash_at_landed_mark(m) -> None:
    """A stop after an item's write and before its ``landed`` mark: the
    mark that records ``landed`` raises (the intent mark before the write
    goes through)."""
    real = mining_waiting.Answer.mark

    def mark(self):
        if any(e["state"] == "landed" for e in self.items):
            raise RuntimeError("simulated crash after the item's write, before its mark")
        return real(self)

    m.setattr(mining_waiting.Answer, "mark", mark)


def _failures() -> dict:
    f = miner.miner_dir() / engine.FAILURES_NAME
    return json.loads(f.read_text()) if f.exists() else {}


def _restatus(home: Path, rid: str, status: str | None) -> None:
    """Move ``rid`` to ``status`` (None: delete it), committed."""
    for p in [*home.glob(f"*/pending/{rid}.md"), *home.glob(f"*/resolved/{rid}.md")]:
        p.unlink()
    if status is None:
        commit_all(home, f"remove {rid}")
    else:
        put_record(home, rid, status=status)


# ------------------------------------------------------- the waiting answer


def test_an_answer_is_saved_whole_before_anything_of_it_lands(home, root, backend, tmp_path, monkeypatch):
    sid = "s1savefst-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    seen: list[dict] = []
    real = miner.create_record

    def spy(h, record, **kw):
        (answer,) = _waiting()
        seen.append({"items": [e["state"] for e in answer.items], "cursor": cursor(path),
                     "mode": answer.path.stat().st_mode & 0o777, "doc": answer.doc, "where": answer.path})
        return real(h, record, **kw)

    monkeypatch.setattr(miner, "create_record", spy)
    result = run(home)
    assert len(result.landed) == 1 and len(seen) == 1
    (s,) = seen
    # what the write is about to do is on disk before it happens (fix round 5)
    assert s["items"] == ["writing"] and s["cursor"]["lines"] == 7 and s["mode"] == 0o600
    assert s["doc"]["items"][0]["intent"] == {"output": "lesson", "record": None, "origin": f"transcript:{sid}#L3"}
    doc = s["doc"]
    assert doc["session"] == sid and doc["transcript"] == str(path) and doc["run_id"] == result.run_id
    assert doc["method_version"] == "1" and doc["halted"] is False and doc["cursor"] == {"lines": 7,
                                                                                         "size": path.stat().st_size,
                                                                                         "halt": False}
    assert doc["checked"] == json.loads((run_dir(result) / "out" / f"{sid}.json").read_text())
    assert f"{sid}-u-3" in doc["learn"]
    # never inside a run folder; and gone once every item landed
    assert s["where"].parent == miner.miner_dir() / "pending" and "runs" not in s["where"].parts
    assert _waiting() == [] and _rows(result)[sid]["saved"] is True


@pytest.mark.parametrize("how", ["call", "bad-output", "checker"])
def test_a_failed_call_or_check_saves_moves_and_teaches_nothing(home, root, backend, tmp_path, monkeypatch, how):
    sid, other = "s1nosave-0000", "s2isfine-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    write_session(root, other, session_rows(other, host(tmp_path)))  # one call succeeds: the failure counts
    backend.answers[sid] = {"call": [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)],
                            "bad-output": "not json", "checker": output([lesson()])}[how]
    with monkeypatch.context() as m:
        if how == "checker":
            real = check.check_output

            def flaky(text, spine, **kw):
                if spine.session.session_id == sid:
                    raise RuntimeError("planted")
                return real(text, spine, **kw)

            m.setattr(engine.check_mod, "check_output", flaky)
        first = run(home)
    assert [a.session for a in _waiting()] == [] and cursor(path) is None
    assert not any(u.startswith(sid) for u in _store_rows()) and _rows(first)[sid]["saved"] is False
    assert _failures()[str(path)]["failures"] == 1  # a call or check failure is the one thing that counts
    backend.answers[sid] = output([lesson()])
    run(home)
    assert _called(backend).count(sid) == 2 and cursor(path)["lines"] == 7 and str(path) not in _failures()


# ------------------------------------------------- crash between write and mark


@pytest.mark.parametrize("kind", ["lesson", "fold", "fire", "fire-flushed", "recurrence"])
def test_a_crash_between_an_item_s_write_and_its_mark_replays_as_a_no_op(home, root, backend, tmp_path, monkeypatch,
                                                                       kind):
    rid, sid = "lrn-55550001", "s1crashmk-0000"
    rpath = put_record(home, rid, status="pending" if kind == "fold" else "routed")
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    if kind == "lesson":
        backend.answers[sid] = output([lesson()])
    elif kind in ("fold", "recurrence"):
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    else:
        _flagged(monkeypatch, rid)
        backend.answers[sid] = output(rule_checks=[_rc(rid)])
    real_mark = mining_waiting.Answer.mark
    with monkeypatch.context() as m:
        _crash_at_landed_mark(m)
        first = run(home)
    assert first.status == "failed" and cursor(path)["lines"] == 7
    (answer,) = _waiting()
    assert [e["state"] for e in answer.items] == ["writing"]  # control: the write happened, the mark did not
    if kind == "fire-flushed":
        telemetry.flush(home)  # the spooled fire reached the tracked plane before the replay
    assert mining_waiting.Answer.mark is real_mark
    second = run(home)
    assert len(backend.specs) == 1 and _waiting() == []
    assert [o["outcome"] for o in second.outcomes] == ["already-written"]
    if kind == "lesson":
        assert len(pending(home)) == 1
    elif kind == "fold":
        assert Record.from_path(rpath).sightings == 2
    elif kind == "recurrence":
        assert len(_events(home, "recurrence-suspect")) == 1
    else:
        assert len(_events(home, "fire")) == 1


# ------------------------------------------------------------- draining


def test_a_waiting_answer_outlives_the_run_folder_prune(home, root, backend, tmp_path, monkeypatch):
    sid = "s1outlive-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        first = run(home)
        before = _pending_hashes()
        assert len(before) == 1  # control: one answer waits
        for _ in range(engine.KEEP_RUNS + 2):
            run(home)
    runs = sorted((miner.miner_dir() / "runs").iterdir())
    assert len(runs) <= engine.KEEP_RUNS + 1 and not (miner.miner_dir() / "runs" / first.run_id).exists()
    assert _pending_hashes() == before
    last = run(home)
    assert len(backend.specs) == 1 and len(last.landed) == 1 and _waiting() == []


def test_a_run_where_every_call_fails_still_drains(home, root, backend, tmp_path, monkeypatch):
    sid, broken = "s1drainok-0000", "s2callsfl-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    assert len(_waiting()) == 1
    bp = write_session(root, broken, session_rows(broken, host(tmp_path)))
    backend.answers[broken] = [FakeOutcome(ok=False, failure="exit", detail="Not logged in", rc=1)]
    second = run(home)
    assert _called(backend) == [sid, broken] and len(second.landed) == 1 and _waiting() == []
    assert _rec(second)["waiting"]["landed_earlier"] == 1 and _rec(second)["totals"]["called"] == 1
    assert str(bp) not in _failures()  # no call succeeded: nothing is counted


def test_a_run_with_no_new_sessions_drains_and_records_it(home, root, backend, tmp_path, monkeypatch):
    sid = "s1nonewss-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    second = run(home)
    assert len(backend.specs) == 1 and len(second.landed) == 1 and second.status == "ok"
    rec = _rec(second)
    assert rec["sessions"] == [] and rec["waiting"]["found"] == 1 and rec["waiting"]["landed_earlier"] == 1
    assert journal_last()["waiting"]["landed_earlier"] == 1 and journal_last()["sessions_called"] == 0
    contract.load_run(run_dir(second))
    third = run(home)  # nothing waits any more: an idle run, as before
    assert third.status == "idle" and journal_last()["status"] == "idle"


def test_the_flood_gate_holds_waiting_answers_until_it_opens(home, root, backend, tmp_path, monkeypatch):
    sid, held = "s1gatedrn-0000", "s2gatehld-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    before = _pending_hashes()
    assert len(before) == 1  # control: an answer waits
    hp = write_session(root, held, session_rows(held, host(tmp_path)))
    backend.answers[held] = output([lesson()])
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_PENDING_GATE", "0")
        gated = run(home)
    assert gated.status == "held-gate" and len(backend.specs) == 1 and cursor(hp) is None
    assert gated.landed == [] and not pending(home) and _pending_hashes() == before
    assert _rows(gated)[held]["status"] == "not-run" and _rows(gated)[held]["reason"] == "pending-gate"
    assert _rec(gated)["waiting"] == {"found": 1, "landed_earlier": 0, "landed_this_run": 0, "still_waiting": 1,
                                      "stuck": [], "drained": False, "unreadable": []}
    assert journal_last()["status"] == "held-gate" and journal_last()["waiting"]["still_waiting"] == 1
    contract.load_run(run_dir(gated))
    opened = run(home)  # the gate is open again: the waiting answer lands, once, and the held session is called
    assert _called(backend) == [sid, held] and len(opened.landed) == 2 and _waiting() == []
    assert _rec(opened)["waiting"]["landed_earlier"] == 1 and len(pending(home)) == 2
    run(home)
    assert len(pending(home)) == 2


def test_a_busy_lock_leaves_every_waiting_answer_byte_identical(home, root, backend, tmp_path, monkeypatch):
    first_sid, second_sid = "s1busyone-0000", "s2busytwo-0000"
    write_session(root, first_sid, session_rows(first_sid, host(tmp_path)))
    backend.answers[first_sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
        before = _pending_hashes()
        write_session(root, second_sid, session_rows(second_sid, host(tmp_path)))
        backend.answers[second_sid] = output([lesson()])
        second = run(home)
    after = _pending_hashes()
    assert len(after) == 2 and {k: after[k] for k in before} == before
    assert _rec(second)["waiting"] == {"found": 1, "landed_earlier": 0, "landed_this_run": 0, "still_waiting": 2,
                                       "stuck": [], "drained": False, "unreadable": []}
    third = run(home)
    assert len(third.landed) == 2 and _waiting() == [] and len(backend.specs) == 2


def test_the_cap_holds_drained_items_in_their_order(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    sids = ["s1capord-0000", "s2capord-0000", "s3capord-0000"]
    for sid in sids:
        write_session(root, sid, session_rows(sid, host(tmp_path)))
        backend.answers[sid] = output([lesson()])

    def landed_from(result) -> list[str]:
        out = []
        for rid in result.landed:
            (rec,) = [r for r in pending(home) if r.id == rid]
            out.append(rec.evidence[0]["session"])
        return out

    first = run(home)
    order = [r["session"] for r in _rec(first)["sessions"] if r["status"] == "called"]
    assert sorted(order) == sids and landed_from(first) == order[:1]
    assert [o["outcome"] for o in first.outcomes] == ["landed", "waiting-cap", "waiting-cap"]
    late = "s9capnew-0000"
    write_session(root, late, session_rows(late, host(tmp_path)))
    backend.answers[late] = output([lesson()])
    got = [*landed_from(first)]
    for _ in range(3):
        got += landed_from(run(home))
    assert got == [*order, late]  # oldest first: this run's new answer waits behind the earlier ones
    assert _waiting() == [] and len(backend.specs) == 4


def test_a_fork_appearing_while_its_parent_s_answer_waits_lands_each_output_once(home, root, backend, tmp_path,
                                                                                 monkeypatch):
    parent, fork = "s1prntwt-0000", "s2forkwt-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    backend.answers[parent] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    assert cursor(pp)["lines"] == 7 and len(_waiting()) == 1 and not pending(home)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    own = lesson(id="L2", evidence=[{"line": 8, "quote": "add the export to the nightly job"}], steps=[],
                 verification=None, incident_cost=None, trigger="About to add an export to the nightly job",
                 instruction="Ask which job owns exports first, because two jobs write them")
    backend.answers[fork] = output([lesson(), own])
    second = run(home)
    out = json.loads((run_dir(second) / "out" / f"{fork}.json").read_text())
    assert [x["id"] for x in out["lessons"]] == ["L2"]  # control: the fork's copy was already judged
    assert _called(backend) == [parent, fork] and len(second.landed) == 2 and len(pending(home)) == 2
    assert {r.evidence[0]["origin"] for r in pending(home)} == {f"transcript:{parent}#L3", f"transcript:{fork}#L8"}
    assert cursor(fp)["lines"] == 9


# ------------------------------------------------------- stale and stuck


@pytest.mark.parametrize("case", ["sighting-gone", "sighting-moved", "sighting-deferred", "fire-not-routed",
                                  "fire-gone", "lesson-known"])
def test_a_stale_item_is_dropped_with_its_reason(home, root, backend, tmp_path, monkeypatch, case):
    rid, succ, sid = "lrn-55550002", "lrn-55550003", "s1stalei-0000"
    put_record(home, rid, status="routed" if case.startswith("fire") else "pending")
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    if case.startswith("fire"):
        _flagged(monkeypatch, rid)
        backend.answers[sid] = output(rule_checks=[_rc(rid)])
    elif case == "lesson-known":
        backend.answers[sid] = output([lesson()])
    else:
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    assert len(_waiting()) == 1 and cursor(path)["lines"] == 7
    if case == "sighting-gone" or case == "fire-gone":
        _restatus(home, rid, None)
    elif case == "sighting-moved":
        put_record(home, succ)
        _restatus(home, rid, None)
        put_record(home, rid, status="superseded", successor=succ)
    elif case == "sighting-deferred":
        _restatus(home, rid, "deferred")
    elif case == "fire-not-routed":
        _restatus(home, rid, "pending")
    else:  # another record now holds the lesson's origin
        Record.create(type="behavior", scope="user", source="teach", kind="anti-pattern",
                      trigger="About to say checks pass", instruction="Run them first, because they may fail",
                      record_id="lrn-55550004",
                      evidence=[{"quote": "x", "origin": f"transcript:{sid}#L3"}]).write(
            home / "user" / "pending" / "lrn-55550004.md")
        commit_all(home, "known origin")
    second = run(home)
    assert len(backend.specs) == 1 and _waiting() == []
    (o,) = second.outcomes
    expected = {"sighting-gone": ("dropped-invalid", "no live record"),
                "sighting-moved": ("folded", None),
                "sighting-deferred": ("skipped-resolved", "the sighted record is deferred"),
                "fire-not-routed": ("fire-skipped", "the record is pending, not routed"),
                "fire-gone": ("fire-skipped", "the record is gone"),
                "lesson-known": ("skipped-known-origin", "a record already holds this origin")}[case]
    assert o["outcome"] == expected[0] and o["waited_from"] != second.run_id
    if expected[1] is None:
        assert o["record"] == succ and Record.from_path(next(home.glob(f"*/pending/{succ}.md"))).sightings == 2
    else:
        assert expected[1] in o["reason"]
    assert second.landed == [] and second.fires == 0


def _doctor(capsys) -> list[str]:
    assert cli.main(["doctor", "miner"]) == 0
    return [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("doctor: ")]


def test_a_stuck_item_reaches_doctor_and_run_json_and_keeps_retrying(home, root, backend, tmp_path, monkeypatch,
                                                                    capsys):
    sid = "s1stuckit-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    capsys.readouterr()

    def refused(*a, **kw):
        raise OSError("synthetic stuck write")

    results = []
    with monkeypatch.context() as m:
        m.setattr(miner, "create_record", refused)
        for _ in range(mining_waiting.STUCK_AFTER - 1):
            results.append(run(home))
        lines = _doctor(capsys)
        assert any(ln.startswith("doctor: OK waiting-answers — 1 waiting answer(s), 1 item(s)") for ln in lines)
        assert not [ln for ln in lines if "waiting-item-stuck" in ln]  # not yet: two failures
        assert _rec(results[-1])["waiting"]["stuck"] == []
        results.append(run(home))
        (stuck,) = _rec(results[-1])["waiting"]["stuck"]
        assert stuck == {"session": sid, "kind": "lessons", "origin": f"transcript:{sid}#L3",
                         "failures": mining_waiting.STUCK_AFTER, "error": "OSError: synthetic stuck write"}
        contract.load_run(run_dir(results[-1]))
        (warn,) = [ln for ln in _doctor(capsys) if "waiting-item-stuck" in ln]
        assert warn.startswith("doctor: WARN waiting-item-stuck") and f"transcript:{sid}#L3" in warn
        assert "failed to land on 3 runs" in warn and journal_last()["waiting"]["stuck"] == 1
        results.append(run(home))  # it keeps retrying: no drop
        assert [e["failures"] for e in _waiting()[0].items] == [mining_waiting.STUCK_AFTER + 1]
    last = run(home)
    assert len(last.landed) == 1 and _waiting() == [] and len(backend.specs) == 1
    assert not [ln for ln in _doctor(capsys) if "waiting-item-stuck" in ln]


@pytest.mark.parametrize("engine", ["digest", "session"])
def test_doctor_warns_when_waiting_answers_are_stranded_by_the_digest_engine(home, root, backend, tmp_path,
                                                                            monkeypatch, capsys, engine):
    sid = "s1stranded-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    assert len(_waiting()) == 1  # control: an answer waits
    (home / "config.yaml").write_text(f"miner:\n  engine: {engine}\n")
    capsys.readouterr()
    lines = _doctor(capsys)
    assert "doctor: OK waiting-answers — 1 waiting answer(s), 1 item(s) still to land" in lines  # control
    stranded = [ln for ln in lines if "waiting-answers-stranded" in ln]
    if engine == "digest":
        assert stranded == ["doctor: WARN waiting-answers-stranded — 1 waiting answer(s) (1 item(s)) and "
                            "miner.engine is digest: they land only when the session engine runs"]
    else:
        assert stranded == []


def test_doctor_is_quiet_about_the_digest_engine_when_nothing_waits(home, root, capsys):
    (home / "config.yaml").write_text("miner:\n  engine: digest\n")
    lines = _doctor(capsys)
    assert "doctor: OK waiting-answers — 0 waiting answer(s), 0 item(s) still to land" in lines  # control
    assert not [ln for ln in lines if "stranded" in ln]


def test_doctor_names_a_waiting_file_that_does_not_read(home, root, backend, tmp_path, capsys):
    folder = miner.miner_dir() / "pending"
    folder.mkdir(parents=True)
    (folder / "0001-broken.json").write_text("{not json")
    (folder / "0002-other.json").write_text(json.dumps({"contract": "something-else", "items": []}))
    lines = _doctor(capsys)
    assert "doctor: OK waiting-answers — 0 waiting answer(s), 0 item(s) still to land" in lines
    for name in ("0001-broken.json", "0002-other.json"):
        assert any("WARN waiting-answer-unreadable" in ln and name in ln for ln in lines)
    result = run(home)
    assert _rec(result)["waiting"]["unreadable"] == ["0001-broken.json", "0002-other.json"]
    assert [o["outcome"] for o in result.outcomes] == ["waiting-unreadable"] * 2
    assert journal_last()["waiting"]["unreadable"] == ["0001-broken.json", "0002-other.json"]
    assert (folder / "0001-broken.json").is_file() and (folder / "0002-other.json").is_file()  # left in place


# ------------------------------------------------------------- the preview


def test_a_preview_leaves_the_waiting_answers_byte_identical_and_drains_nothing(home, root, backend, tmp_path,
                                                                               monkeypatch):
    sid, other = "s1prvwait-0000", "s2prvnew0-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    before = _pending_hashes()
    assert len(before) == 1  # control: an answer waits
    write_session(root, other, session_rows(other, host(tmp_path)))
    backend.answers[other] = output([lesson()])
    result = run(home, preview=True)
    assert _called(backend) == [sid, other]  # control: the preview judged the new session
    assert _pending_hashes() == before and not pending(home) and result.landed == []
    assert "waiting" not in _rec(result) and "saved" not in _rows(result)[other]


def test_a_preview_creates_no_pending_folder(home, root, backend, tmp_path):
    sid = "s1prvnone-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    result = run(home, preview=True)
    assert len(backend.specs) == 1 and _rec(result)["totals"]["lessons"] == 1  # control: it judged a lesson
    assert not (miner.miner_dir() / "pending").exists()


# ------------------------------------------- round-3 probes (astra3, opus3)


def test_failed_parent_and_capped_fork_replay_each_output_once(home, root, backend, tmp_path, monkeypatch):
    parent, fork, rid = "s1reorder-0000", "s2reorder-0000", "lrn-33330001"
    put_record(home, rid, status="routed")
    _flagged(monkeypatch, rid)
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path,
                                              "always validate the nightly job before enabling it"))
    common = lesson(verification=None, incident_cost=None)
    extra = lesson(id="L2", evidence=[{"line": 8, "quote": "validate the nightly job"}], steps=[],
                   verification=None, incident_cost=None, trigger="About to enable the nightly job",
                   instruction="Validate the nightly job first because it can break exports")
    backend.answers[parent] = output([common], rule_checks=[_rc(rid)])
    backend.answers[fork] = output([common, extra])
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
        _fail_fire(m)
        first = run(home)
    assert len(first.landed) == 1 and cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9
    second = run(home)
    assert _called(backend) == [parent, fork]  # nobody is asked again
    shared = [r for r in pending(home) if any(e.get("ref", {}).get("uuid") == f"{parent}-u-3" for e in r.evidence)]
    assert len(shared) == 1 and len(_events(home, "fire")) == 1 and len(pending(home)) == 2
    assert second.fires == 1
    run(home)
    assert len(pending(home)) == 2 and len(_events(home, "fire")) == 1


def test_a_cited_tool_result_of_a_failed_fire_still_lands_its_fire(home, root, backend, tmp_path, monkeypatch):
    parent, fork = "s1toolhold-0000", "s2toolhold-0000"
    r1, r2 = "lrn-33330002", "lrn-33330003"
    for rid in (r1, r2):
        put_record(home, rid, status="routed")
    _flag_all(monkeypatch, r1, r2)
    rows = session_rows(parent, host(tmp_path))
    rows[3] = {"type": "user", "uuid": "shared-tool-result", "timestamp": rows[3]["timestamp"],
               "sessionId": parent, "cwd": host(tmp_path), "message": {"content": [
                   {"type": "tool_result", "tool_use_id": "check-1", "content": "make check failed on export path"}]}}
    pp = write_session(root, parent, rows)
    write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path, "check the nightly job too"))
    backend.answers[parent] = output(rule_checks=[_rc(r1)])
    backend.answers[fork] = output(rule_checks=[_rc(r2)])
    with monkeypatch.context() as m:
        _fail_fire(m, r1)
        first = run(home)
    assert first.fires == 1 and cursor(pp)["lines"] == 7
    run(home)
    assert sorted(e["record"] for e in _events(home, "fire")) == [r1, r2] and len(backend.specs) == 2
    run(home)
    assert len(_events(home, "fire")) == 2


def test_mixed_call_failure_and_busy_lock_counts_no_session_failure(home, root, backend, tmp_path, monkeypatch):
    bad, good = "s1mixedlock-0000", "s2mixedlock-0000"
    bp = write_session(root, bad, session_rows(bad, host(tmp_path)))
    gp = write_session(root, good, session_rows(good, host(tmp_path)))
    backend.answers[bad] = [FakeOutcome(ok=False, failure="exit", detail="synthetic failed call", rc=1)]
    backend.answers[good] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        first = run(home)
    assert len(backend.specs) == 2 and not first.landed  # control: one call failed, one succeeded
    assert cursor(bp) is None and cursor(gp)["lines"] == 7  # the good one's answer is saved
    assert _failures() == {}  # the ledger lock was not taken: nothing is counted


@pytest.mark.parametrize("owner", ["parent", "fork"])
@pytest.mark.parametrize("mode", ["call", "landing", "cap", "halted-landing"])
def test_claim_owner_matrix_lands_the_missing_lesson_once(home, root, backend, tmp_path, monkeypatch, owner, mode):
    parent = "s1matrix-0000" if owner == "parent" else "s2matrix-0000"
    fork = "s2matrix-0000" if owner == "parent" else "s1matrix-0000"
    rows = session_rows(parent, host(tmp_path))
    fork_rows = _fork_rows(rows, fork, 8, tmp_path, "validate the nightly export too")
    claimer = parent if owner == "parent" else fork  # planned first: the older file
    if mode == "halted-landing":
        if claimer == parent:
            rows = rows + [typed(parent, 8, "<command-name>/self-learn:teach</command-name>", host(tmp_path))]
        else:
            fork_rows += [typed(fork, 10, "<command-name>/self-learn:teach</command-name>", host(tmp_path))]
    paths = {parent: write_session(root, parent, rows), fork: write_session(root, fork, fork_rows)}
    other = fork if claimer == parent else parent
    stamp = max(p.stat().st_mtime for p in paths.values())
    os.utime(paths[claimer], (stamp - 2, stamp - 2))
    os.utime(paths[other], (stamp - 1, stamp - 1))
    for sid in (parent, fork):
        backend.answers[sid] = output([lesson()])
    real = miner.create_record

    def fail_owner(h, record, **kw):
        if record.evidence[0]["session"] == claimer:
            raise OSError("synthetic claimer landing failure")
        return real(h, record, **kw)

    with monkeypatch.context() as m:
        if mode == "call":
            backend.answers[claimer] = [FakeOutcome(ok=False, failure="exit", detail="synthetic failed call", rc=1)]
        elif mode in ("landing", "halted-landing"):
            m.setattr(miner, "create_record", fail_owner)
        else:
            m.setenv("SELF_LEARN_MINE_CAP_MAX", "0")
        first = run(home)
    # a parent planned after its fork has nothing of its own: every turn is the fork's claim
    assert _called(backend) == ([claimer, other] if owner == "parent" else [claimer]) and not first.landed
    assert cursor(paths[other]) is not None  # the other saved its answer, or had nothing new
    if mode == "call":  # the claimer's moments reach the store only through its own save
        assert cursor(paths[claimer]) is None and f"{parent}-u-3" not in _store_rows()
    else:
        assert cursor(paths[claimer]) is not None and f"{parent}-u-3" in _store_rows()
    backend.answers[claimer] = output([lesson()])
    n1 = len(backend.specs)
    run(home)
    assert _called(backend, n1) == ([claimer] if mode == "call" else []) and len(pending(home)) == 1
    run(home)
    assert len(pending(home)) == 1


@pytest.mark.parametrize("kind", ["fire", "recurrence-suspect"])
def test_partial_event_replay_through_fork_is_not_duplicated(home, root, backend, tmp_path, monkeypatch, kind):
    parent, fork = "s1eventfork-0000", "s2eventfork-0000"
    a, b = "lrn-33330004", "lrn-33330005"
    for rid in (a, b):
        put_record(home, rid, status="routed")
    _flag_all(monkeypatch, a, b)
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path, "validate the nightly export too"))
    extra = lesson(id="L2", evidence=[{"line": 8, "quote": "validate the nightly export"}], steps=[],
                   verification=None, incident_cost=None)
    if kind == "fire":
        backend.answers[parent] = output(rule_checks=[_rc(a), _rc(b)])
        backend.answers[fork] = output([extra], rule_checks=[_rc(a)])
    else:
        backend.answers[parent] = output(sightings=[_sighting(parent, a), _sighting(parent, b)])
        backend.answers[fork] = output([extra], sightings=[_sighting(fork, a)])
    real = telemetry.spool_event

    def broken(k, **kw):
        if k == kind and kw.get("record") == b:
            raise OSError("synthetic second-event failure")
        return real(k, **kw)

    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_CAP_MAX", "0")
        m.setattr(telemetry, "spool_event", broken)
        run(home)
    assert cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9
    assert [e["record"] for e in _events(home, kind)] == [a]
    run(home)
    events = _events(home, kind)
    assert sorted(e["record"] for e in events) == [a, b] and len(backend.specs) == 2
    assert {e["origin"] for e in events} == {f"transcript:{parent}#L{4 if kind == 'fire' else 3}"}
    assert len(pending(home)) == 1
    run(home)
    assert len(pending(home)) == 1 and len(_events(home, kind)) == 2


@pytest.mark.parametrize("how", ["call", "landing", "cap", "bad-output", "checker"])
def test_a_claimer_that_fails_lands_once(home, root, backend, tmp_path, monkeypatch, how):
    parent, fork = "s1clmpar-0000", "s2clmfrk-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    backend.answers[fork] = output([lesson()])
    backend.answers[parent] = output([lesson()])
    with monkeypatch.context() as m:
        if how == "call":
            backend.answers[parent] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
        elif how == "bad-output":
            backend.answers[parent] = "not json"
        elif how == "cap":
            m.setenv("SELF_LEARN_MINE_CAP_MAX", "0")
        elif how == "landing":
            m.setattr(miner, "create_record", lambda *a, **k: (_ for _ in ()).throw(miner.LedgerOpsError("x")))
        else:
            real = check.check_output

            def flaky(text, spine, **kw):
                if spine.session.session_id == parent:
                    raise RuntimeError("planted")
                return real(text, spine, **kw)

            m.setattr(engine.check_mod, "check_output", flaky)
        run(home)
    saved = how in ("landing", "cap")
    assert cursor(fp)["lines"] == 9 and (cursor(pp) is not None) is saved
    assert (f"{parent}-u-3" in _store_rows()) is saved
    backend.answers[parent] = output([lesson()])
    run(home)
    assert _called(backend, 2) == ([] if saved else [parent])
    assert len(pending(home)) == 1 and cursor(pp)["lines"] == 7
    run(home)
    assert len(pending(home)) == 1


def test_a_fork_planned_first_that_fails_leaves_the_shared_lesson_to_its_retry(home, root, backend, tmp_path):
    parent, fork = "s1rvspar-0000", "s2rvsfrk-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    os.utime(fp, (1_700_000_000, 1_700_000_000))  # older: planned first, it claims the shared stretch
    backend.answers[fork] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    backend.answers[parent] = output([lesson()])
    first = run(home)
    assert _called(backend) == [fork] and first.engine["skipped"] == {"nothing-new": 1}  # control
    assert first.landed == [] and cursor(pp)["lines"] == 7 and cursor(fp) is None
    assert f"{parent}-u-3" not in _store_rows()  # claimed by the fork: only its own save teaches it
    backend.answers[fork] = output([lesson()])
    second = run(home)
    assert _called(backend, 1) == [fork] and len(second.landed) == 1 and len(pending(home)) == 1
    run(home)
    assert len(pending(home)) == 1 and cursor(fp)["lines"] == 9


def test_a_busy_lock_four_times_then_lands(home, root, backend, tmp_path, monkeypatch):
    sid = "s1lockgu-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        for _ in range(4):
            run(home)
    assert _failures() == {} and len(backend.specs) == 1
    run(home)
    assert len(pending(home)) == 1 and cursor(path)["lines"] == 7


def test_an_outage_counts_nothing(home, root, backend, tmp_path):
    sids = [f"s{i}outage-0000" for i in range(2)]
    for s in sids:
        write_session(root, s, session_rows(s, host(tmp_path)))
        backend.answers[s] = [FakeOutcome(ok=False, failure="exit", detail="Not logged in", rc=1)]
    for _ in range(3):
        run(home)
    assert _failures() == {} and _waiting() == []
    for s in sids:
        backend.answers[s] = output([lesson()])
    run(home)
    assert len(pending(home)) == 2


def test_a_partial_landing_is_never_judged_again_so_a_new_line_cannot_duplicate(home, root, backend, tmp_path,
                                                                                monkeypatch):
    """Opus round-3 MINOR-1: the lesson landed and the sighting's write failed;
    the replay used to ask the model again, which cited the same lesson at
    another line. Now the sighting lands from the saved answer and the model
    is never asked again."""
    rid = "lrn-0000e5e9"
    put_record(home, rid)
    sid = "s1prtrpl-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson(evidence=[{"line": 3, "quote": "you never ran make check"}],
                                          steps=[], verification=None, incident_cost=None)],
                                  sightings=[_sighting(sid, rid, line=6, quote="always run the checks")])
    real_write = Record.write

    def boom(self, p, *a, **k):
        if self.id == rid:
            raise OSError("disk full")
        return real_write(self, p, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(Record, "write", boom)
        first = run(home)
    assert len(first.landed) == 1 and cursor(path)["lines"] == 7
    # what the replay used to be: the same lesson, its evidence now the L6 turn
    backend.answers[sid] = output([lesson(evidence=[{"line": 6, "quote": "always run the checks"}],
                                          steps=[], verification=None, incident_cost=None)],
                                  sightings=[_sighting(sid, rid, line=6, quote="always run the checks")])
    second = run(home)
    assert len(backend.specs) == 1 and second.folded == [rid]
    assert len([r for r in pending(home) if r.id != rid]) == 1
    assert Record.from_path(next(home.glob(f"*/pending/{rid}.md"))).sightings == 2


@pytest.mark.parametrize("where", ["commit", "runjson"])
def test_a_crash_replays_without_duplicates(home, root, backend, tmp_path, monkeypatch, where):
    rid = "lrn-0000e5e1"
    rpath = put_record(home, rid)
    sid = "s1crashr-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()], sightings=[_sighting(sid, rid, line=6, quote="always run the checks")])
    real_put = engine.RunFolder.put_json
    with monkeypatch.context() as m:
        if where == "commit":
            m.setattr(miner, "_commit_landing", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("planted")))
        else:
            def boom(self, rel, obj):
                if rel == "run.json":
                    raise RuntimeError("planted")
                return real_put(self, rel, obj)

            m.setattr(engine.RunFolder, "put_json", boom)
        assert run(home).status == "failed"
    run(home)
    assert len(pending(home)) == 2 and Record.from_path(rpath).sightings == 2 and cursor(path)["lines"] == 7
    assert len(backend.specs) == 1 and git(home, "status", "--porcelain").stdout.strip() == ""


def test_a_preview_tool_never_opens_the_live_index(home, root, backend, tmp_path, monkeypatch):
    from self_learn.index import store as store_mod

    put_record(home, "lrn-0000e6e1")
    run(home)
    opened: list[str] = []
    real = store_mod.LessonIndex.open_at.__func__

    def spy(cls, path, h):
        opened.append(str(path))
        return real(cls, path, h)

    monkeypatch.setattr(store_mod.LessonIndex, "open_at", classmethod(spy))
    sid = "s1toolix-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    replies: list[str] = []
    orig = backend.text_session

    def calling(spec):
        tool = {t.name: t for t in spec.mcp_toolset.tools}
        replies.append(str(asyncio.run(tool["find_similar_lessons"].handler(
            {"draft": "run the checks before claiming they pass"}))))
        return orig(spec)

    backend.text_session = calling
    res = run(home, preview=True)
    assert replies  # control: the tool ran
    assert opened and not [p for p in opened if f"runs/{res.run_id}" not in p]


# ------------------------------------------- round-4 probes (astra4, opus4)


@pytest.mark.parametrize("new_first", [True, False])
def test_a_new_fork_cannot_take_over_an_unfinished_answer(home, root, backend, tmp_path, monkeypatch, new_first):
    parent, fork = "s5newpar-0000", ("s1newfork-0000" if new_first else "s9newfork-0000")
    rid = "lrn-44440001"
    put_record(home, rid, status="routed")
    _flagged(monkeypatch, rid)
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    common = lesson(steps=[], verification=None, incident_cost=None)
    backend.answers[parent] = output([common], rule_checks=[_rc(rid)])
    with monkeypatch.context() as m:
        _fail_fire(m, rid)
        first = run(home)
    assert len(first.landed) == 1 and cursor(pp)["lines"] == 7 and f"{parent}-u-3" in _store_rows()
    fp = write_session(root, fork, [dict(r, sessionId=fork) for r in rows])
    backend.answers[fork] = output([common])
    second = run(home)
    assert _called(backend) == [parent] and second.engine["skipped"] == {"nothing-new": 1}
    assert len(pending(home)) == 1 and len(_events(home, "fire")) == 1 and cursor(fp)["lines"] == 7


def test_different_cursors_do_not_lose_a_fire_of_shared_context(home, root, backend, tmp_path, monkeypatch):
    parent, fork = "s1ctxpar-0000", "s2ctxfork-0000"
    rid = "lrn-44440002"
    put_record(home, rid, status="routed")
    _flagged(monkeypatch, rid)
    rows = session_rows(parent, host(tmp_path))
    rows[3] = {"type": "user", "uuid": "shared-context-tool", "timestamp": rows[3]["timestamp"], "sessionId": parent,
               "cwd": host(tmp_path), "message": {"content": [
                   {"type": "tool_result", "tool_use_id": "t", "content": "export check failed"}]}}
    fp = write_session(root, fork, [dict(r, sessionId=fork) for r in rows])
    backend.answers[fork] = output()
    run(home)
    assert cursor(fp)["lines"] == 7 and "shared-context-tool" not in _store_rows()
    # the parent arrives later; the fork has already read the copied prefix
    pp = write_session(root, parent, rows + [typed(parent, 8, "check the export again", host(tmp_path)),
                                             asst(parent, 9, "checked", host(tmp_path))])
    write_session(root, fork, [dict(r, sessionId=fork) for r in rows] + [
        typed(fork, 8, "always validate the nightly job", host(tmp_path)), asst(fork, 9, "validated", host(tmp_path))])
    backend.answers[parent] = output(rule_checks=[_rc(rid)])
    backend.answers[fork] = output([lesson(evidence=[{"line": 8, "quote": "validate the nightly job"}], steps=[],
                                           verification=None, incident_cost={"line": 4, "text": "export check failed"})])
    with monkeypatch.context() as m:
        _fail_fire(m, rid)
        first = run(home)
    kept = json.loads((run_dir(first) / "out" / f"{fork}.json").read_text())
    assert kept["lessons"][0]["incident_cost"]["ref"]["uuid"] == "shared-context-tool"  # control
    assert first.fires == 0 and len(first.landed) == 1 and cursor(pp)["lines"] == 9
    calls = len(backend.specs)
    run(home)
    assert len(_events(home, "fire")) == 1 and len(backend.specs) == calls  # it landed from the saved answer
    run(home)
    assert len(_events(home, "fire")) == 1


def test_a_same_id_file_appearing_later_cannot_change_who_lands(home, root, backend, tmp_path, monkeypatch):
    parent, fork = "s1twopar-0000", "s2twofork-0000"
    rid = "lrn-44440003"
    put_record(home, rid, status="routed")
    _flagged(monkeypatch, rid)
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path, "check the nightly export too"))
    common = lesson(steps=[], verification=None, incident_cost=None)
    backend.answers[parent] = output([common], rule_checks=[_rc(rid)])
    backend.answers[fork] = output([common])
    with monkeypatch.context() as m:
        _fail_fire(m, rid)
        first = run(home)
    assert len(first.landed) == 1 and cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9
    # a shorter copy with the parent's id appears in another folder, older on disk
    dup = write_session(root, parent, rows[:2], project="-other-copy")
    stamp = min(pp.stat().st_mtime, fp.stat().st_mtime) - 10
    os.utime(dup, (stamp, stamp))
    run(home)
    run(home)
    assert len(pending(home)) == 1 and len(_events(home, "fire")) == 1
    assert _called(backend) == [parent, fork]  # the copy's lines were all judged; nothing was asked again


def test_the_runaway_guard_leaves_unrun_sessions_to_the_next_run(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_RUN_USD", "2")
    parent, fork = "s1costpar-0000", "s2costfork-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path, "check exports nightly"))
    backend.answers[parent] = output([lesson()])
    backend.answers[fork] = output()
    backend.cost = 3.0
    first = run(home)
    assert _called(backend) == [parent] and len(first.landed) == 1
    assert cursor(pp)["lines"] == 7 and cursor(fp) is None
    assert _rows(first)[fork]["status"] == "not-run" and "saved" not in _rows(first)[fork]
    backend.cost = 0.0
    run(home)
    assert _called(backend) == [parent, fork] and len(pending(home)) == 1
    assert cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9


def test_a_preview_over_the_session_limit_lands_and_saves_nothing(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "1")
    parent, fork = "s1prvpar-0000", "s2prvfork-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path, "check exports nightly"))
    backend.answers[parent] = output([lesson()])
    backend.answers[fork] = output([lesson()])
    first = run(home, preview=True)
    assert _called(backend) == [parent] and _rec(first)["counts"]["deferred"] == 1
    assert not pending(home) and cursor(pp) is None and cursor(fp) is None and not _store_rows()
    assert not (miner.miner_dir() / "pending").exists() and "families_over_limit" not in _rec(first)
    run(home)
    assert len(pending(home)) == 1


def _fork_of(root: Path, tmp_path: Path, parent_rows: list[dict], sid: str, n: int) -> Path:
    extra = [typed(sid, 8 + n, f"fork {sid} asks for step {n}", host(tmp_path)),
             asst(sid, 9 + n, f"Did step {n}.", host(tmp_path))]
    return write_session(root, sid, [dict(r, sessionId=sid) for r in parent_rows] + extra)


def test_a_new_fork_on_the_retry_night_does_not_land_the_shared_lesson_again(home, root, backend, tmp_path):
    parent, f, g = "s5parent-0000", "s7fork00-0000", "s1newfrk-0000"
    rows = session_rows(parent, host(tmp_path))
    write_session(root, parent, rows)
    fp = _fork_of(root, tmp_path, rows, f, 1)
    backend.answers[parent] = output([lesson()])
    backend.answers[f] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    first = run(home)
    assert len(first.landed) == 1 and cursor(fp) is None
    _fork_of(root, tmp_path, rows, g, 2)  # next day: a new fork whose id sorts first
    for sid in (parent, f, g):
        backend.answers[sid] = output([lesson()])
    run(home)
    assert _called(backend, 2) == [g, f]  # f failed before: it waits behind the fresh one
    assert [r.evidence[0]["origin"] for r in pending(home)] == [f"transcript:{parent}#L3"]


def test_the_runaway_guard_over_three_nights_reaches_every_session(home, root, tmp_path, monkeypatch):
    b = Backend(cost=3.0)
    monkeypatch.setattr(miner.invocation.registry, "backend_for", lambda *a, **k: b)
    monkeypatch.setenv("SELF_LEARN_MINER_PARALLEL", "1")
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_RUN_USD", "5")
    parent = "s1guardp-0000"
    rows = session_rows(parent, host(tmp_path))
    paths = [write_session(root, parent, rows), _fork_of(root, tmp_path, rows, "s2guardf-0000", 1),
             _fork_of(root, tmp_path, rows, "s3guardg-0000", 2)]
    u = "s9unrela-0000"
    up = write_session(root, u, session_rows(u, host(tmp_path)))
    for i, p in enumerate(paths):
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    os.utime(up, (1_800_000_000, 1_800_000_000))
    nights = []
    for _ in range(3):
        n0 = len(b.specs)
        run(home)
        nights.append(_called(b, n0))
    assert nights == [[parent, "s2guardf-0000"], ["s3guardg-0000", u], []]
    assert all(cursor(p) is not None for p in paths) and cursor(up)["lines"] == 7


def test_skipped_sessions_do_not_use_up_max_sessions(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "3")
    for i in range(3):
        sid = f"s{i}selfmn-0000"
        rows = session_rows(sid, host(tmp_path))
        rows[0] = typed(sid, 1, miner.SELF_PROMPT_HEADERS[0] + "\nmore", host(tmp_path))
        p = write_session(root, sid, rows)
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    u = "s9userss-0000"
    up = write_session(root, u, session_rows(u, host(tmp_path)))
    os.utime(up, (1_800_000_000, 1_800_000_000))
    result = run(home)
    assert result.engine["skipped"] == {"halted": 3}  # control: three sessions planned, none called
    assert result.engine["to_call"] == 1 and result.engine["deferred"] == 0
    assert _called(backend) == [u] and cursor(up)["lines"] == 7


# ------------------------------------------------- shapes that were families


def test_a_chain_whose_middle_fails_lands_each_output_once(home, root, backend, tmp_path):
    a, b, c = "s1chaina-0000", "s2chainb-0000", "s3chainc-0000"
    rows = session_rows(a, host(tmp_path))
    pa = write_session(root, a, rows)
    rows_b = _fork_rows(rows, b, 8, tmp_path, "and add the export to the nightly job")
    pb = write_session(root, b, rows_b)
    pc = write_session(root, c, _fork_rows(rows_b, c, 10, tmp_path, "and document the nightly job"))
    l_b = lesson(id="L2", evidence=[{"line": 8, "quote": "add the export to the nightly job"}], steps=[],
                 verification=None, incident_cost=None, trigger="About to add an export to the nightly job",
                 instruction="Ask which job owns exports first, because two jobs write them")
    l_c = lesson(id="L3", evidence=[{"line": 10, "quote": "document the nightly job"}], steps=[],
                 verification=None, incident_cost=None, trigger="About to document the nightly job",
                 instruction="Write it in the runbook, because that is where the person reads")
    backend.answers[a] = output([lesson()])
    backend.answers[b] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    backend.answers[c] = output([l_c])
    first = run(home)
    assert _called(backend) == [a, b, c] and len(first.landed) == 2
    assert cursor(pa)["lines"] == 7 and cursor(pb) is None and cursor(pc)["lines"] == 11
    assert f"{b}-u-8" not in _store_rows()  # b claimed its turn; c's save does not teach it
    backend.answers[b] = output([l_b])
    second = run(home)
    assert _called(backend, 3) == [b] and len(second.landed) == 1 and len(pending(home)) == 3
    run(home)
    assert len(pending(home)) == 3


def test_a_fork_whose_answer_did_not_check_lands_only_its_own_output_on_retry(home, root, backend, tmp_path):
    parent, fork = "s1frkfal-0000", "s2frkfal-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    l_f = lesson(id="L2", evidence=[{"line": 8, "quote": "add the export to the nightly job"}], steps=[],
                 verification=None, incident_cost=None, trigger="About to add an export to the nightly job",
                 instruction="Ask which job owns exports first, because two jobs write them")
    backend.answers[parent] = output([lesson()])
    backend.answers[fork] = "not json"
    first = run(home)
    assert len(first.landed) == 1 and cursor(pp)["lines"] == 7 and cursor(fp) is None
    backend.answers[fork] = output([lesson(), l_f])
    second = run(home)
    assert _called(backend, 2) == [fork] and len(second.landed) == 1 and len(pending(home)) == 2
    outcomes = [o["outcome"] for o in second.outcomes]
    assert "dropped-check" in outcomes and [o for o in outcomes if o != "dropped-check"] == ["landed"]
    out = json.loads((run_dir(second) / "out" / f"{fork}.json").read_text())
    assert [x["id"] for x in out["lessons"]] == ["L2"]  # its copy of the parent's lesson was already judged
    run(home)
    assert len(pending(home)) == 2


def test_a_fork_of_a_parent_judged_last_night_lands_nothing_twice(home, root, backend, tmp_path):
    parent, fork = "s1lastnt-0000", "s2lastnt-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    backend.answers[parent] = output([lesson()])
    run(home)
    assert len(pending(home)) == 1 and f"{parent}-u-3" in _store_rows()
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    backend.answers[fork] = output([lesson()])
    second = run(home)
    assert _called(backend, 1) == [fork]
    (row,) = _rows(second).values()
    assert row["saved"] is True and "family" not in row and "family_held" not in row
    assert second.landed == [] and len(pending(home)) == 1 and cursor(fp)["lines"] == 9
    assert cursor(pp)["lines"] == 7


def test_an_identical_copy_skipped_for_claimed_moments_leaves_them_to_the_claimer(home, root, backend, tmp_path):
    parent, fork = "s1skpclm-0000", "s2skpclm-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, [dict(r, sessionId=fork) for r in rows])  # an identical copy
    backend.answers[parent] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    first = run(home)
    assert _called(backend) == [parent] and first.engine["skipped"] == {"nothing-new": 1}  # control
    assert cursor(pp) is None and cursor(fp)["lines"] == 7 and f"{parent}-u-3" not in _store_rows()
    backend.answers[parent] = output([lesson()])
    second = run(home)
    assert _called(backend, 1) == [parent] and len(second.landed) == 1 and cursor(pp)["lines"] == 7
    run(home)
    assert len(pending(home)) == 1


# ------------------------------------------------- store and records


def test_a_saved_answer_s_citations_reach_the_store_at_its_save(home, root, backend, tmp_path, monkeypatch):
    """G1 of round 3, under the new rule: the store learns what a saved
    answer cites, citations before the judged range included, at its save,
    whether or not the landing completes."""
    sid = "s1nonspn-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    miner._advance_cursors([(miner.SessionSlice(path, sid, "-work-host", 0, ["x"] * 4, 0), False)])  # pyright: ignore[reportPrivateUsage]
    rows = session_rows(sid, host(tmp_path)) + [typed(sid, 8, "and keep the export log too", host(tmp_path))]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    backend.answers[sid] = output([lesson(evidence=[{"line": 6, "quote": "always run the checks"}], steps=[],
                                          verification={"line": 5, "quote": "The check failed", "how": "it ran"},
                                          incident_cost={"line": 2, "text": "a review spent on a false pass"})])

    def refused(*a, **k):
        raise OSError("synthetic")

    with monkeypatch.context() as m:
        m.setattr(miner, "create_record", refused)
        first = run(home)
    out = json.loads((run_dir(first) / "out" / f"{sid}.json").read_text())
    assert out["lessons"][0]["incident_cost"]["ref"]["line"] == 2  # control: a citation before the range was kept
    assert f"{sid}-a-2" in _store_rows() and f"{sid}-u-3" not in _store_rows()  # cited yes; unjudged line 3 no
    second = run(home)
    assert len(second.landed) == 1 and len(backend.specs) == 1


def test_a_cited_moment_another_session_claimed_stays_out_of_the_store(home, root, backend, tmp_path):
    parent, fork = "s1clmcit-0000", "s2clmcit-0000"
    rows = session_rows(parent, host(tmp_path))
    write_session(root, parent, rows)
    write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    backend.answers[parent] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    backend.answers[fork] = output([lesson(id="L2", evidence=[{"line": 8, "quote": "add the export to the nightly job"}],
                                           steps=[], verification=None,
                                           incident_cost={"line": 5, "text": "the check failed on the export"},
                                           trigger="About to add an export to the nightly job",
                                           instruction="Ask which job owns exports first, because two jobs write them")])
    first = run(home)
    out = json.loads((run_dir(first) / "out" / f"{fork}.json").read_text())
    assert out["lessons"][0]["incident_cost"]["ref"]["uuid"] == f"{parent}-a-5"  # control: the fork cites it
    assert f"{fork}-u-8" in _store_rows() and f"{parent}-a-5" not in _store_rows()
    backend.answers[parent] = output([lesson()])
    run(home)
    assert len(pending(home)) == 2 and f"{parent}-a-5" in _store_rows()


def test_landed_lessons_counts_lessons_only_on_a_run_with_folds(home, root, backend, tmp_path):
    rid = "lrn-0000f1d1"
    put_record(home, rid)
    sid = "s1lndfld-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()], sightings=[_sighting(sid, rid, line=6, quote="always run the checks")])
    result = run(home)
    rec = _rec(result)
    assert result.folded == [rid] and rec["landed"]["lessons"] == 1 and rec["landed"]["folded"] == 1
    assert rec["waiting"]["landed_this_run"] == 2


def test_a_cursor_that_did_not_move_after_a_save_moves_before_the_walk(home, root, backend, tmp_path, monkeypatch):
    from self_learn.mining import uuids

    sid = "s1setcur-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])

    def lost(self, u, on):
        raise uuids.sqlite3.OperationalError("synthetic disk I/O error")

    # the store cannot help here: every write to it fails, this run and the next
    monkeypatch.setattr(uuids.JudgedUuids, "add", lost)
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        m.setattr(miner, "_advance_cursors", lambda processed: None)  # a stop between the save and the cursor
        run(home)
    assert cursor(path) is None and len(_waiting()) == 1 and not _store_rows()  # control: saved, nothing moved
    second = run(home)
    assert len(backend.specs) == 1 and len(second.landed) == 1 and cursor(path)["lines"] == 7


def test_a_store_write_lost_at_save_is_made_again_from_the_waiting_answer(home, root, backend, tmp_path,
                                                                          monkeypatch):
    from self_learn.mining import uuids

    parent, fork = "s1relearn-0000", "s2relearn-0000"
    rows = session_rows(parent, host(tmp_path))
    write_session(root, parent, rows)
    backend.answers[parent] = output([lesson()])
    real_add = uuids.JudgedUuids.add

    def lost(self, u, on):
        raise uuids.sqlite3.OperationalError("synthetic disk I/O error")

    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        m.setattr(uuids.JudgedUuids, "add", lost)
        first = run(home)
    assert _rec(first)["judged_uuids"]["add_failed"] == 1 and not _store_rows()  # control: the write was lost
    assert uuids.JudgedUuids.add is real_add
    write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    backend.answers[fork] = output([lesson()])
    second = run(home)
    assert _rec(second)["judged_uuids"]["relearned"] >= 1 and f"{parent}-u-3" in _store_rows()
    out = json.loads((run_dir(second) / "out" / f"{fork}.json").read_text())
    assert out["lessons"] == []  # the fork's copy read as judged: the parent's moments were learned first
    assert len(pending(home)) == 1 and len(second.landed) == 1


# ------------------------------------------------------------ the contract


def _valid_run(home, root, backend, tmp_path) -> dict:
    sid = "s1contrc-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    return _rec(run(home))


_STUCK = {"session": "s", "kind": "lessons", "origin": "transcript:s#L3", "failures": 3, "error": "x"}


@pytest.mark.parametrize("bad", [
    {"landed": "three"},
    {"landed": {"lessons": 1, "folded": 0, "recurrences": 0}},
    {"landed": {"lessons": -1, "folded": 0, "recurrences": 0, "fires": 0}},
    {"landed": {"lessons": 1, "folded": 0, "recurrences": 0, "fires": 0, "sessions_failed": 0}},
    {"waiting": "none"},
    {"waiting": {"found": 0, "landed_earlier": 0, "landed_this_run": 1, "still_waiting": 0, "stuck": []}},
    {"waiting": {"found": -1, "landed_earlier": 0, "landed_this_run": 1, "still_waiting": 0, "stuck": [],
                 "drained": True}},
    {"waiting": {"found": 0, "landed_earlier": 0, "landed_this_run": 1, "still_waiting": 0, "stuck": [],
                 "drained": "yes"}},
    {"waiting": {"found": 0, "landed_earlier": 0, "landed_this_run": 1, "still_waiting": 1,
                 "stuck": [dict(_STUCK, failures=2)], "drained": True}},
    {"waiting": {"found": 0, "landed_earlier": 0, "landed_this_run": 1, "still_waiting": 1,
                 "stuck": [dict(_STUCK, kind="drops")], "drained": True}},
    {"waiting": {"found": 0, "landed_earlier": 0, "landed_this_run": 1, "still_waiting": 0,
                 "stuck": [_STUCK], "drained": True}},
    {"waiting": {"found": 0, "landed_earlier": 0, "landed_this_run": 1, "still_waiting": 0, "stuck": [],
                 "drained": True, "extra": 1}},
    {"families_over_limit": []},
])
def test_the_contract_refuses_a_malformed_run_level_object(home, root, backend, tmp_path, bad):
    rec = _valid_run(home, root, backend, tmp_path)
    assert contract.validate_run(rec) == []  # control: the record as written is valid
    assert rec["waiting"]["landed_this_run"] == 1 and "landed" in rec  # control: both objects are present
    assert contract.validate_run({**rec, **bad}) != []


def test_the_contract_takes_a_stuck_item_as_written(home, root, backend, tmp_path):
    rec = _valid_run(home, root, backend, tmp_path)
    good = dict(rec, waiting=dict(rec["waiting"], still_waiting=1, stuck=[_STUCK]))
    assert contract.validate_run(good) == []


@pytest.mark.parametrize("key,value", [("saved", "yes"), ("saved", 1), ("landing", "complete"), ("family", "x"),
                                       ("family_held", "x")])
def test_the_contract_refuses_a_bad_session_row_value(home, root, backend, tmp_path, key, value):
    rec = _valid_run(home, root, backend, tmp_path)
    assert contract.validate_run(rec) == [] and rec["sessions"][0]["saved"] is True  # control
    bad = dict(rec, sessions=[dict(rec["sessions"][0], **{key: value})])
    assert contract.validate_run(bad) != []


def test_the_contract_refuses_saved_on_an_answer_that_did_not_check_or_was_not_called(home, root, backend, tmp_path):
    rec = _valid_run(home, root, backend, tmp_path)
    row = rec["sessions"][0]
    assert contract.validate_run(rec) == [] and row["out_status"] == "ok"  # control
    assert contract.validate_run(dict(rec, sessions=[dict(row, out_status="bad-output")])) != []
    assert contract.validate_run(dict(rec, sessions=[dict(row, out_status="bad-output", saved=False)])) == []
    skipped = dict(row, status="skipped", reason="nothing-new", out_status=None)
    totals = dict(rec["totals"], called=0, skipped={"nothing-new": 1}, cost_usd=rec["totals"]["cost_usd"])
    base = dict(rec, sessions=[{k: v for k, v in skipped.items() if k != "saved"}], totals=totals)
    assert contract.validate_run(base) == []  # control: a skipped row without `saved`
    assert contract.validate_run(dict(base, sessions=[skipped])) != []


# ------------------------------------------- round-5 probes (astra5, opus5)


def _saved_while_busy(home, root, backend, tmp_path, monkeypatch, sid="s1edgesv-0000", answer=None):
    rows = session_rows(sid, host(tmp_path))
    path = write_session(root, sid, rows)
    backend.answers[sid] = answer or output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    (a,) = _waiting()
    assert cursor(path)["lines"] == 7  # control: saved, nothing landed
    return sid, path, rows, a


@pytest.mark.parametrize("method_error", [False, True])
def test_a_closed_gate_holds_waiting_answers_on_a_run_with_nothing_to_call(home, root, backend, tmp_path,
                                                                          monkeypatch, method_error):
    sid, _path, _rows, _a = _saved_while_busy(home, root, backend, tmp_path, monkeypatch)
    before = _pending_hashes()
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_PENDING_GATE", "0")
        if method_error:  # the stop() path: the method file cannot be read
            def bad():
                raise engine.EngineError("synthetic unavailable method")

            m.setattr(engine, "shared_instructions", bad)
        held = run(home)
    assert _pending_hashes() == before and not pending(home) and held.landed == []
    assert journal_last()["waiting"]["drained"] is False
    if not method_error:
        assert held.status == "held-gate" and journal_last()["status"] == "held-gate"
    opened = run(home)
    assert len(opened.landed) == 1 and _called(backend) == [sid] and _waiting() == []


def test_the_stop_path_drains_when_the_gate_is_open(home, root, backend, tmp_path, monkeypatch):
    _saved_while_busy(home, root, backend, tmp_path, monkeypatch)

    def bad():
        raise engine.EngineError("synthetic unavailable method")

    with monkeypatch.context() as m:
        m.setattr(engine, "shared_instructions", bad)
        stopped = run(home)
    assert stopped.status == "failed" and len(stopped.landed) == 1 and len(pending(home)) == 1
    assert journal_last()["status"] == "failed" and journal_last()["waiting"]["landed_earlier"] == 1


def test_a_gate_at_its_limit_holds_a_waiting_answer_with_no_new_session(home, root, backend, tmp_path, monkeypatch):
    a, b = "s1gtA-0000", "s1gtB-0000"
    write_session(root, a, session_rows(a, host(tmp_path)))
    backend.answers[a] = output([lesson()])
    assert len(run(home).landed) == 1  # one record pending
    write_session(root, b, session_rows(b, host(tmp_path)))
    backend.answers[b] = output([lesson(trigger="About to drain a waiting answer while the gate is shut",
                                        instruction="Hold it, because the queue is full")])
    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: _Busy())
        run(home)
    before = _pending_hashes()
    assert len(before) == 1 and len(pending(home)) == 1  # control
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_PENDING_GATE", "1")
        held = run(home)
    assert held.status == "held-gate" and _pending_hashes() == before and len(pending(home)) == 1
    assert len(run(home).landed) == 1 and len(pending(home)) == 2 and _waiting() == []


@pytest.mark.parametrize("when", ["save", "relearn"])
def test_a_finished_answer_stays_until_the_store_has_learned_it(home, root, backend, tmp_path, monkeypatch, when):
    from self_learn.mining import uuids

    sid = "s1lostuuid-0000"
    rows = session_rows(sid, host(tmp_path))
    write_session(root, sid, rows)
    backend.answers[sid] = output([lesson()])

    def failed(*a, **kw):
        raise uuids.sqlite3.OperationalError("synthetic disk I/O error")

    if when == "relearn":
        with monkeypatch.context() as m:
            m.setattr(intents, "ledger_write", lambda h: _Busy())
            m.setattr(uuids.JudgedUuids, "add", failed)
            run(home)
        assert len(_waiting()) == 1
    with monkeypatch.context() as m:
        m.setattr(uuids.JudgedUuids, "add", failed)
        landed = run(home)
    assert len(pending(home)) == 1 and not _store_rows()
    (kept,) = _waiting()  # every item landed; the store never learned it, so the file stays
    assert [e["state"] for e in kept.items] == ["landed"]
    assert _rec(landed)["waiting"]["still_waiting"] == 0
    fork = "s2lostuuid-0000"
    write_session(root, fork, [dict(r, sessionId=fork) for r in rows])
    backend.answers[fork] = output([lesson()])
    run(home)
    assert len(pending(home)) == 1 and f"{sid}-u-3" in _store_rows() and _waiting() == []


def test_a_fold_replayed_after_its_record_was_routed_is_not_a_recurrence(home, root, backend, tmp_path,
                                                                        monkeypatch):
    rid = "lrn-55558801"
    rp = put_record(home, rid)
    sid = "s1foldroute-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    with monkeypatch.context() as m:
        _crash_at_landed_mark(m)
        run(home)
    rec = Record.from_path(rp)
    assert rec.sightings == 2  # control: the fold was written, its mark was not
    rec.set_status("routed")
    rec.set_routing({"routed_at": "2026-01-01T00:00:00Z", "by": "user", "destination": "CLAUDE.md"})
    dest = rp.parent.parent / "resolved" / rp.name
    dest.parent.mkdir(exist_ok=True)
    rec.write(dest)
    rp.unlink()
    commit_all(home, "route folded record")
    again = run(home)
    assert [o["outcome"] for o in again.outcomes] == ["already-written"]
    assert not _events(home, "recurrence-suspect") and len(backend.specs) == 1 and _waiting() == []


def test_a_recurrence_replayed_after_its_record_was_superseded_is_not_spooled_again(home, root, backend, tmp_path,
                                                                                   monkeypatch):
    rid, succ = "lrn-55558802", "lrn-55558803"
    rp = put_record(home, rid, status="routed")
    sid = "s1recursup-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    with monkeypatch.context() as m:
        _crash_at_landed_mark(m)
        run(home)
    assert len(telemetry.read_spooled(("recurrence-suspect",))) == 1  # control
    put_record(home, succ, status="routed")
    rec = Record.from_path(rp)
    rec.set_status("superseded")
    rec.set_superseded_by(succ)
    rec.write(rp)
    commit_all(home, "supersede after spool")
    again = run(home)
    events = _events(home, "recurrence-suspect")
    assert [(e["record"], e["origin"]) for e in events] == [(rid, f"transcript:{sid}#L3")]
    assert [o["outcome"] for o in again.outcomes] == ["already-written"] and len(backend.specs) == 1


@pytest.mark.parametrize("kind", ["fold", "fire"])
def test_a_writing_item_whose_recorded_target_is_gone_is_dropped_with_a_reason(home, root, backend, tmp_path,
                                                                             monkeypatch, kind):
    rid = "lrn-55558809"
    put_record(home, rid, status="pending" if kind == "fold" else "routed")
    sid = "s1gonetgt-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    if kind == "fold":
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
        broken = (Record, "write")
    else:
        _flagged(monkeypatch, rid)
        backend.answers[sid] = output(rule_checks=[_rc(rid)])
        broken = (telemetry, "spool_event")
    with monkeypatch.context() as m:
        m.setattr(*broken, lambda *a, **k: (_ for _ in ()).throw(OSError("synthetic write failure")))
        run(home)
    (a,) = _waiting()
    assert a.items[0]["state"] == "writing" and a.items[0]["intent"]["record"] == rid  # control
    _restatus(home, rid, None)
    again = run(home)
    (o,) = again.outcomes
    assert o["outcome"] == "dropped-invalid" and "gone" in o["reason"] and _waiting() == []
    assert not _events(home, "fire") and again.folded == []


def test_a_resurface_replayed_after_a_stop_before_its_mark_lands_once(home, root, backend, tmp_path, monkeypatch):
    rid = "lrn-0000abc9"
    put_record(home, rid, status="rejected")
    sids = [f"s{i}rejct-0000" for i in range(4)]
    for s in sids[:3]:
        write_session(root, s, session_rows(s, host(tmp_path)))
        backend.answers[s] = output(sightings=[_sighting(s, rid)])
    with monkeypatch.context() as m:
        m.setattr(miner, "_rejected_mark_landed", lambda r: (_ for _ in ()).throw(RuntimeError("killed")))
        first = run(home)
    assert [o["outcome"] for o in first.outcomes][-2:] == ["landed", "land-failed"]  # control
    second = run(home)
    assert [o["outcome"] for o in second.outcomes] == ["already-written"]
    write_session(root, sids[3], session_rows(sids[3], host(tmp_path)))
    backend.answers[sids[3]] = output(sightings=[_sighting(sids[3], rid)])
    third = run(home)
    assert [o["outcome"] for o in third.outcomes] == ["dropped-rejected"] and len(pending(home)) == 1


@pytest.mark.parametrize("kind", ["fire", "recurrence-suspect"])
def test_an_event_spool_is_durable_before_its_item_is_marked(home, root, backend, tmp_path, monkeypatch, kind):
    rid, sid = "lrn-55558805", "s1durable-0000"
    put_record(home, rid, status="routed")
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    if kind == "fire":
        _flagged(monkeypatch, rid)
        backend.answers[sid] = output(rule_checks=[_rc(rid)])
    else:
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    synced: list[str] = []
    spooled: list[str] = []
    seen: list[tuple[str, list[str]]] = []
    real_sync, real_spool, real_mark = os.fsync, telemetry.spool_event, mining_waiting.Answer.mark

    def fsync(fd):
        synced.append(os.readlink(f"/proc/self/fd/{fd}"))
        return real_sync(fd)

    def spool(k, **kw):
        p = real_spool(k, **kw)
        if k == kind:
            spooled.append(str(p))
        return p

    def mark(a):
        if any(e["state"] == "landed" for e in a.items):
            seen.append((spooled[0], list(synced)))
        return real_mark(a)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(telemetry, "spool_event", spool)
    monkeypatch.setattr(mining_waiting.Answer, "mark", mark)
    run(home)
    assert len(seen) == 1 and len(_events(home, kind)) == 1  # control: one landed mark, one event
    path, before = seen[0]
    assert path in before and str(Path(path).parent) in before


@pytest.mark.parametrize("bad", ["missing-item", "duplicate-item", "missing-cursor", "missing-learn",
                                 "future-contract", "bad-json", "unreadable", "checked-invalid"])
def test_an_invalid_waiting_file_keeps_its_output_and_says_so(home, root, backend, tmp_path, monkeypatch, capsys,
                                                             bad):
    _sid, _path, _rows, a = _saved_while_busy(home, root, backend, tmp_path, monkeypatch)
    d = json.loads(a.path.read_text())
    if bad == "missing-item":
        d["items"] = []
    elif bad == "duplicate-item":
        d["items"] = d["items"] * 2
    elif bad == "missing-cursor":
        del d["cursor"]
    elif bad == "missing-learn":
        del d["learn"]
    elif bad == "future-contract":
        d["contract"] = "miner-waiting/999"
    elif bad == "checked-invalid":
        del d["checked"]["redactions"]  # valid JSON, a checked part that fails miner-output/1
    if bad != "unreadable":
        a.path.write_text("{not json" if bad == "bad-json" else json.dumps(d))
    original = a.path.read_bytes()
    capsys.readouterr()
    with monkeypatch.context() as m:
        if bad == "unreadable":
            real = Path.read_text

            def unread(p, *args, **kw):
                if p == a.path:
                    raise PermissionError("synthetic unreadable pending file")
                return real(p, *args, **kw)

            m.setattr(Path, "read_text", unread)
        lines = _doctor(capsys)
        result = run(home)
    assert any("WARN waiting-answer-unreadable" in ln and a.path.name in ln for ln in lines)
    assert a.path.read_bytes() == original and not pending(home)
    assert _rec(result)["waiting"]["unreadable"] == [a.path.name]
    assert journal_last()["waiting"]["unreadable"] == [a.path.name]
    (o,) = [o for o in result.outcomes if o["outcome"] == "waiting-unreadable"]
    assert "manual repair" in o["reason"]


def test_the_lock_flag_means_acquired_even_when_the_drain_then_fails(home, root, backend, tmp_path, monkeypatch):
    bad, good = "s1locktaken-0000", "s2locktaken-0000"
    bp = write_session(root, bad, session_rows(bad, host(tmp_path)))
    write_session(root, good, session_rows(good, host(tmp_path)))
    backend.answers[bad] = [FakeOutcome(ok=False, failure="exit", detail="synthetic call failure", rc=1)]
    backend.answers[good] = output([lesson()])
    reached: list[bool] = []

    def crash(*args):
        reached.append(True)
        raise gitops.GitOpsError("synthetic drain failure inside the acquired lock")

    monkeypatch.setattr(miner, "_drain_waiting", crash)
    result = run(home)
    assert reached == [True] and len(backend.specs) == 2  # control: the lock was acquired, the drain failed
    assert _rec(result)["waiting"]["drained"] is True
    assert _failures()[str(bp)]["failures"] == 1


def test_a_preview_never_loads_the_waiting_answers(home, root, backend, tmp_path, monkeypatch):
    _saved_while_busy(home, root, backend, tmp_path, monkeypatch)
    other = "s2prvload-0000"
    write_session(root, other, session_rows(other, host(tmp_path)))
    backend.answers[other] = output([lesson()])
    loads: list[str] = []
    real = mining_waiting.load_all

    def spy(mdir):
        loads.append("load")
        return real(mdir)

    monkeypatch.setattr(mining_waiting, "load_all", spy)
    result = run(home, preview=True)
    assert _rec(result)["totals"]["called"] == 1 and loads == []  # control: it judged the new session
    run(home)
    assert loads  # control: a night run does load them


def test_a_kept_answer_s_moments_stay_judged_while_the_store_cannot_be_written(home, root, backend, tmp_path,
                                                                              monkeypatch):
    from self_learn.mining import uuids

    parent, fork = "s1nostore-0000", "s2nostore-0000"
    rows = session_rows(parent, host(tmp_path))
    write_session(root, parent, rows)
    backend.answers[parent] = output([lesson()])

    def failed(*a, **kw):
        raise uuids.sqlite3.OperationalError("synthetic disk I/O error")

    monkeypatch.setattr(uuids.JudgedUuids, "add", failed)
    assert len(run(home).landed) == 1 and len(_waiting()) == 1  # control: landed, kept, never learned
    write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    backend.answers[fork] = output([lesson()])
    second = run(home)
    assert _rec(second)["judged_uuids"]["relearn_failed"] == 1 and not _store_rows()
    out = json.loads((run_dir(second) / "out" / f"{fork}.json").read_text())
    assert out["lessons"] == []  # the kept answer's moments are in the snapshot though the store has none
    assert len(pending(home)) == 1 and second.landed == []


# ------------------------------------------- round-6 probes (astra6, opus6)


@pytest.mark.parametrize("kind", ["lesson", "fold"])
def test_a_landing_commit_that_fails_leaves_its_items_writing(home, root, backend, tmp_path, monkeypatch, kind):
    sid, rid = "s1commitfail-0000", "lrn-66660001"
    if kind == "fold":
        put_record(home, rid)
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()]) if kind == "lesson" else output(sightings=[_sighting(sid, rid)])
    real, calls = gitops.commit, []

    def failed(h, subject, *a, **kw):
        if subject.startswith("self-learn: mine "):
            calls.append(subject)
            raise gitops.GitOpsError("synthetic landing commit failure")
        return real(h, subject, *a, **kw)

    with monkeypatch.context() as m:
        m.setattr(gitops, "commit", failed)
        r = run(home)
    assert calls and r.landing_uncommitted  # control: the commit failed and the helper swallowed it
    assert len(r.landed if kind == "lesson" else r.folded) == 1
    (a,) = _waiting()
    assert [e["state"] for e in a.items] == ["writing"]
    again = run(home)  # its reconcile commits the output; the replay acknowledges it
    assert [o["outcome"] for o in again.outcomes] == ["already-written"]
    assert len(backend.specs) == 1 and _waiting() == [] and not git(home, "status", "--porcelain").stdout.strip()


@pytest.mark.parametrize("kind", ["lesson", "fold"])
def test_a_replay_keeps_its_answer_while_the_output_is_uncommitted(home, root, backend, tmp_path, monkeypatch,
                                                                   kind):
    sid, rid = "s1replaycommit-0000", "lrn-66660006"
    if kind == "fold":
        put_record(home, rid)
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()]) if kind == "lesson" else output(sightings=[_sighting(sid, rid)])

    def crash(*a, **kw):
        raise gitops.GitOpsError("synthetic stop before the landing commit")

    with monkeypatch.context() as m:
        m.setattr(miner, "_commit_landing", crash)
        run(home)
    assert [a.items[0]["state"] for a in _waiting()] == ["writing"]
    assert git(home, "status", "--porcelain").stdout.strip()  # control: the output is not committed
    with monkeypatch.context() as m:
        m.setattr(miner.reconcile_mod, "reconcile", crash)
        held = run(home)
    assert [o["outcome"] for o in held.outcomes] == ["already-written"]  # control: the replay found it
    assert git(home, "status", "--porcelain").stdout.strip()
    (a,) = _waiting()
    assert [e["state"] for e in a.items] == ["writing"]
    run(home)
    assert _waiting() == [] and len(backend.specs) == 1 and not git(home, "status", "--porcelain").stdout.strip()


@pytest.mark.parametrize("bad", ["missing-record", "null-record", "wrong-output", "wrong-origin", "bool-index",
                                 "negative-cursor", "bad-halt", "transcript-not-text"])
def test_a_field_the_replay_reads_that_is_wrong_makes_the_file_unreadable(home, root, backend, tmp_path,
                                                                         monkeypatch, bad):
    sid, rid = "s1badintent-0000", "lrn-66660003"
    rp = put_record(home, rid)
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    with monkeypatch.context() as m:
        m.setattr(Record, "write", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")))
        run(home)
    (a,) = _waiting()
    assert a.items[0]["state"] == "writing" and a.items[0]["intent"]["output"] == "fold"  # control
    d = json.loads(a.path.read_text())
    e = d["items"][0]
    if bad == "missing-record":
        del e["intent"]["record"]
    elif bad == "null-record":
        e["intent"]["record"] = None
    elif bad == "wrong-output":
        e["intent"]["output"] = "fire"  # a sighting never spools a fire (opus6 k8)
    elif bad == "wrong-origin":
        e["intent"]["origin"] = "not-an-origin"
    elif bad == "bool-index":
        e["index"] = False
    elif bad == "negative-cursor":
        d["cursor"]["lines"] = -7
    elif bad == "bad-halt":
        d["cursor"]["halt"] = "false"
    else:
        d["transcript"] = 17
    a.path.write_text(json.dumps(d))
    before = a.path.read_bytes()
    loaded, broken = mining_waiting.load_all(miner.miner_dir())
    assert loaded == [] and broken == [a.path.name]
    r = run(home)
    assert a.path.read_bytes() == before and not r.folded and Record.from_path(rp).sightings == 1
    assert _rec(r)["waiting"]["unreadable"] == [a.path.name] and _rec(r)["waiting"]["stuck"] == []
    assert [o["outcome"] for o in r.outcomes] == ["waiting-unreadable"]


def test_a_cursor_halt_that_is_not_a_bool_never_halts_the_session(home, root, backend, tmp_path, monkeypatch):
    sid = "s1badhalt-0000"
    rows = session_rows(sid, host(tmp_path))
    path = write_session(root, sid, rows)
    backend.answers[sid] = output([lesson()])

    class Cut(BaseException):
        pass

    def cut(*a, **kw):
        raise Cut()

    with monkeypatch.context() as m:
        m.setattr(miner, "_advance_cursors", cut)
        with pytest.raises(Cut):
            run(home)
    (a,) = _waiting()
    assert cursor(path) is None  # control: saved, the cursor never moved
    a.doc["cursor"]["halt"] = "false"
    a.path.write_text(json.dumps(a.doc))
    write_session(root, sid, rows + [typed(sid, 8, "always validate the nightly job", host(tmp_path)),
                                     asst(sid, 9, "done", host(tmp_path))])
    backend.answers[sid] = output([lesson(evidence=[{"line": 8, "quote": "validate the nightly job"}], steps=[],
                                          verification=None, incident_cost=None)])
    run(home)
    assert not cursor(path).get("halt") and cursor(path)["lines"] == 9


def test_a_fold_is_already_written_only_when_all_its_evidence_is(home, root, backend, tmp_path, monkeypatch):
    rid, sid = "lrn-66660008", "s1partialfold-0000"
    rp = put_record(home, rid)
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    sight = _sighting(sid, rid)
    sight["evidence"].append({"line": 6, "quote": "always run the checks"})
    backend.answers[sid] = output(sightings=[sight])
    with monkeypatch.context() as m:
        m.setattr(Record, "write", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")))
        run(home)
    (a,) = _waiting()
    evidence = a.doc["checked"]["sightings"][0]["evidence"]
    assert a.items[0]["state"] == "writing" and len(evidence) == 2  # control
    with intents.ledger_write(home):  # another writer folds only the first of the two moments
        rec = Record.from_path(rp)
        rec.append_evidence(miner._evidence_entry(evidence[0]))  # pyright: ignore[reportPrivateUsage]
        rec.set_sightings(rec.sightings + 1)
        rec.write(rp)
        commit_all(home, "fold the first quote")
    origins = {e.get("origin") for e in Record.from_path(rp).evidence}
    assert f"transcript:{sid}#L3" in origins and f"transcript:{sid}#L6" not in origins  # control
    run(home)
    origins = {e.get("origin") for e in Record.from_path(rp).evidence}
    assert f"transcript:{sid}#L6" in origins and _waiting() == [] and len(backend.specs) == 1


@pytest.mark.parametrize("kind", ["fire", "recurrence-suspect"])
def test_a_replayed_event_is_synced_before_its_item_is_marked(home, root, backend, tmp_path, monkeypatch, kind):
    sid, rid = "s1retryfsync-0000", "lrn-66660004"
    put_record(home, rid, status="routed")
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    if kind == "fire":
        _flagged(monkeypatch, rid)
        backend.answers[sid] = output(rule_checks=[_rc(rid)])
    else:
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    paths: list = []

    def failed(p):
        paths.append(p)
        raise OSError("synthetic fsync failure after the append")

    with monkeypatch.context() as m:
        m.setattr(mining_waiting, "fsync_file_and_folder", failed)
        m.setattr(telemetry, "flush", lambda *a, **kw: (_ for _ in ()).throw(telemetry.TelemetryError("held")))
        run(home)
    assert paths and len(telemetry.read_spooled((kind,))) == 1  # control: appended, never synced
    assert _waiting()[0].items[0]["state"] == "writing"
    synced: list[str] = []
    marked: list[list[str]] = []
    real_sync, real_mark = os.fsync, mining_waiting.Answer.mark

    def sync(fd):
        synced.append(os.readlink(f"/proc/self/fd/{fd}"))
        return real_sync(fd)

    def mark(a):
        if any(e["state"] == "landed" for e in a.items):
            marked.append(list(synced))
        return real_mark(a)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(mining_waiting.Answer, "mark", mark)
    again = run(home)
    assert [o["outcome"] for o in again.outcomes] == ["already-written"] and len(marked) == 1
    assert str(paths[0]) in marked[0] and str(Path(paths[0]).parent) in marked[0]
    assert len(_events(home, kind)) == 1 and len(backend.specs) == 1


def test_replayed_lessons_respect_this_run_s_cap(home, root, backend, tmp_path, monkeypatch):
    for i in (1, 2):
        sid = f"s{i}capwrite-0000"
        write_session(root, sid, session_rows(sid, host(tmp_path)))
        backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(miner, "create_record", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")))
        run(home)
    assert [a.items[0]["state"] for a in _waiting()] == ["writing", "writing"] and not pending(home)  # control
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
        capped = run(home)
    assert len(capped.landed) == 1 and [o["outcome"] for o in capped.outcomes] == ["landed", "waiting-cap"]
    (left,) = _waiting()
    assert [e["state"] for e in left.items] == ["writing"]
    run(home)
    assert len(pending(home)) == 2 and len(backend.specs) == 2 and _waiting() == []


def test_a_replayed_lesson_pair_in_one_answer_respects_the_cap(home, root, backend, tmp_path, monkeypatch):
    sid = "s1capwrt-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    l2 = lesson(id="L2", trigger="About to merge without reading the diff",
                instruction="Read the diff, because merges hide changes",
                evidence=[{"line": 6, "quote": "always run the checks"}])
    backend.answers[sid] = output([lesson(), l2])
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_CAP_MAX", "5")
        m.setattr(miner, "create_record", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")))
        run(home)
    (a,) = _waiting()
    assert [e["state"] for e in a.items] == ["writing", "writing"]  # control
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
        capped = run(home)
    assert len(capped.landed) == 1 and len(pending(home)) == 1
    run(home)
    assert len(pending(home)) == 2 and len(backend.specs) == 1 and _waiting() == []


def test_a_replayed_resurface_respects_this_run_s_cap(home, root, backend, tmp_path, monkeypatch):
    rid = "lrn-66660009"
    put_record(home, rid, status="rejected")
    for i in range(3):
        sid = f"s{i}resurcap-0000"
        write_session(root, sid, session_rows(sid, host(tmp_path)))
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
        with monkeypatch.context() as m:
            if i == 2:
                m.setattr(miner, "create_record",
                          lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")))
            run(home)
    (a,) = _waiting()
    assert a.items[0]["intent"]["output"] == "resurface" and not pending(home)  # control
    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_CAP_MAX", "0")
        capped = run(home)
    assert [o["outcome"] for o in capped.outcomes] == ["waiting-cap"] and not pending(home) and len(_waiting()) == 1
    run(home)
    assert len(pending(home)) == 1 and len(backend.specs) == 3 and _waiting() == []


def _rejected_marks() -> dict:
    path = miner.miner_dir() / "rejected-sightings.json"
    return json.loads(path.read_text()) if path.exists() else {}


def test_a_lesson_at_a_rejected_record_s_third_sighting_leaves_it_unmarked(home, root, backend, tmp_path):
    rid = "lrn-0000abd1"
    put_record(home, rid, status="rejected")
    for s in ("s1rjone-0000", "s2rjtwo-0000"):
        write_session(root, s, session_rows(s, host(tmp_path)))
        backend.answers[s] = output(sightings=[_sighting(s, rid)])
    run(home)
    s3 = "s3rjthr-0000"
    write_session(root, s3, session_rows(s3, host(tmp_path)))
    backend.answers[s3] = output([lesson()], sightings=[_sighting(s3, rid)])
    second = run(home)
    assert [o["outcome"] for o in second.outcomes] == ["landed", "skipped-known-origin"]  # control
    assert _rejected_marks()[rid] != "landed" and len(pending(home)) == 1
    s4 = "s4rjfou-0000"
    write_session(root, s4, session_rows(s4, host(tmp_path)))
    backend.answers[s4] = output(sightings=[_sighting(s4, rid)])
    third = run(home)
    assert [o["outcome"] for o in third.outcomes] == ["landed", "resurfaced"] and len(pending(home)) == 2


def test_a_resurface_decided_again_after_its_mark_was_lost_marks_the_rejected_record(home, root, backend,
                                                                                    tmp_path, monkeypatch):
    rid = "lrn-0000abda"
    put_record(home, rid, status="rejected")
    sids = [f"s{i}rjlost-0000" for i in range(4)]
    for s in sids[:3]:
        write_session(root, s, session_rows(s, host(tmp_path)))
        backend.answers[s] = output(sightings=[_sighting(s, rid)])
    with monkeypatch.context() as m:
        m.setattr(miner, "_rejected_mark_landed", lambda r: (_ for _ in ()).throw(RuntimeError("killed")))
        run(home)
    (a,) = _waiting()
    assert len(pending(home)) == 1 and _rejected_marks()[rid] != "landed"  # control: copy landed, mark lost
    d = json.loads(a.path.read_text())  # a file from before intents: the item is decided again
    d["items"][0] = {k: v for k, v in d["items"][0].items() if k not in ("intent", "outcome")} | {"state": "waiting"}
    a.path.write_text(json.dumps(d))
    again = run(home)
    assert [o["outcome"] for o in again.outcomes] == ["skipped-known-origin"]
    assert _rejected_marks()[rid] == "landed" and _waiting() == []
    write_session(root, sids[3], session_rows(sids[3], host(tmp_path)))
    backend.answers[sids[3]] = output(sightings=[_sighting(sids[3], rid)])
    fourth = run(home)
    assert [o["outcome"] for o in fourth.outcomes] == ["dropped-rejected"] and len(pending(home)) == 1


@pytest.mark.parametrize("field", ["unreadable", "relearn_failed"])
def test_the_run_record_refuses_a_bad_unreadable_or_relearn_failed(home, root, backend, tmp_path, field):
    sid = "s1badnewfield-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    doc = _rec(run(home))
    good = json.loads(json.dumps(doc))
    if field == "unreadable":
        good["waiting"]["unreadable"] = ["0001-s1badnewfield-0000.json"]
    else:
        good["judged_uuids"]["relearn_failed"] = 2
    assert contract.validate_run(good) == []  # control: a valid value passes
    if field == "unreadable":
        doc["waiting"]["unreadable"] = [17]
    else:
        doc["judged_uuids"]["relearn_failed"] = "not an integer"
    assert contract.validate_run(doc)


@pytest.mark.parametrize("bad", ["lesson-with-record", "failures-bool"])
def test_a_writing_lesson_whose_intent_names_a_record_is_unreadable(home, root, backend, tmp_path, monkeypatch, bad):
    sid = "s1lessrec-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    with monkeypatch.context() as m:
        m.setattr(miner, "create_record", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")))
        run(home)
    (a,) = _waiting()
    assert a.items[0]["intent"]["output"] == "lesson" and a.items[0]["intent"]["record"] is None  # control
    d = json.loads(a.path.read_text())
    if bad == "lesson-with-record":
        d["items"][0]["intent"]["record"] = "lrn-66660011"
    else:
        d["items"][0]["failures"] = True
    a.path.write_text(json.dumps(d))
    before = a.path.read_bytes()
    r = run(home)
    assert a.path.read_bytes() == before and not pending(home)
    assert _rec(r)["waiting"]["unreadable"] == [a.path.name]
