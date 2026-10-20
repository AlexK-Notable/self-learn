"""A parent and its forks are one family (new-miner R2, fix round 3; the
user's design): planned and called in a fixed order, admitted whole, and
complete or held as a whole. The round-3 gate probes are regression tests
here, each showing the missing output lands exactly once and nothing lands
twice. Synthetic transcripts and ledgers only; the backend is the engine
tests' fake.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from self_learn import gitops, intents, miner, telemetry
from self_learn.mining import check, contract, engine, flags as flags_mod
from self_learn.records import Record
from support import git
from test_mining_engine import (  # noqa: F401 -- fixtures
    FakeOutcome, PROJECT, _called, _flagged, _sighting, _store_rows, asst, backend, cursor, home, host, lesson,
    output, pending, put_record, root, run, run_dir, session_rows, typed, write_session,
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


def _rows(result) -> dict[str, dict]:
    return {r["session"]: r for r in json.loads((run_dir(result) / "run.json").read_text())["sessions"]}


# ------------------------------------------------------------- grouping


def test_families_group_by_any_shared_uuid_in_a_fixed_order(tmp_path):
    def sl(sid: str, rows: list[dict]):
        path = tmp_path / f"{sid}.jsonl"
        lines = [json.dumps(r) for r in rows]
        path.write_text("\n".join(lines) + "\n")
        return miner.SessionSlice(path, sid, PROJECT, 0, lines, path.stat().st_size)

    tool = {"type": "user", "uuid": "only-a-tool-result", "timestamp": "2026-10-01T10:00:00.000Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "x"}]}}
    a = sl("s9late-0000", [typed("s9late-0000", 1, "hello there", "/h"), tool])
    b = sl("s1earl-0000", [dict(typed("s1earl-0000", 1, "hi", "/h"), timestamp="2026-09-01T00:00:00.000Z"), tool])
    c = sl("s5chain-0000", [typed("s5chain-0000", 1, "x", "/h"), dict(b.lines and json.loads(b.lines[0]))])
    alone = sl("s3alone-0000", [typed("s3alone-0000", 1, "alone", "/h")])
    fams = engine.families([a, alone, c, b])
    # a and b share only a tool result; c shares b's first turn: one chain
    assert [[m.session_id for m in f] for f in fams] == [
        ["s1earl-0000", "s5chain-0000", "s9late-0000"], ["s3alone-0000"]]


def test_the_order_inside_a_family_ignores_mtime_and_failure_history(home, root, backend, tmp_path, monkeypatch):
    parent, fork = "s1ordpar-0000", "s2ordfrk-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    os.utime(pp, (1_800_000_000, 1_800_000_000))
    os.utime(fp, (1_700_000_000, 1_700_000_000))  # the fork is older on disk
    data = {str(fp): {"start": 0, "failures": 0}, str(pp): {"start": 0, "failures": 2}}
    (miner.miner_dir() / engine.FAILURES_NAME).write_text(json.dumps(data))  # the parent failed before
    backend.answers[parent] = output([lesson()])
    backend.answers[fork] = output([lesson()])
    result = run(home)
    assert _called(backend) == [parent, fork] and len(result.landed) == 1
    assert {s: r["family"] for s, r in _rows(result).items()} == {parent: parent, fork: parent}


def test_a_family_of_one_behaves_as_before(home, root, backend, tmp_path):
    sid = "s1single-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    result = run(home)
    assert len(result.landed) == 1 and cursor(path)["lines"] == 7 and f"{sid}-u-3" in _store_rows()
    (row,) = _rows(result).values()
    assert row["family"] == sid and "family_held" not in row and row["landing"] == "complete"
    assert not [o for o in result.outcomes if o["outcome"] == "family-held"]


# -------------------------------------------------- the round-3 probes


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
    real = telemetry.spool_event

    def broken(kind, **kw):
        if kind == "fire":
            raise OSError("synthetic fire failure after parent lesson")
        return real(kind, **kw)

    with monkeypatch.context() as m:
        m.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
        m.setattr(telemetry, "spool_event", broken)
        first = run(home)
    assert len(first.landed) == 1 and cursor(pp) is None and cursor(fp) is None and not _store_rows()
    held = [o for o in first.outcomes if o["outcome"] == "family-held"]
    assert held and held[0]["origin"] == f"transcript:{parent}"
    second = run(home)
    assert _called(backend) == [parent, fork, parent, fork]
    shared = [r for r in pending(home) if any(e.get("ref", {}).get("uuid") == f"{parent}-u-3" for e in r.evidence)]
    assert len(shared) == 1 and len(_events(home, "fire")) == 1 and len(pending(home)) == 2
    assert second.fires == 1 and cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9
    run(home)
    assert len(pending(home)) == 2 and len(_events(home, "fire")) == 1


def test_a_cited_tool_result_of_a_failed_member_is_not_learned(home, root, backend, tmp_path, monkeypatch):
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
    real = telemetry.spool_event

    def broken(kind, **kw):
        if kind == "fire" and kw.get("record") == r1:
            raise OSError("synthetic first record fire failure")
        return real(kind, **kw)

    with monkeypatch.context() as m:
        m.setattr(telemetry, "spool_event", broken)
        first = run(home)
    assert first.fires == 1 and cursor(pp) is None
    assert "shared-tool-result" not in _store_rows()
    run(home)
    assert sorted(e["record"] for e in _events(home, "fire")) == [r1, r2]
    run(home)
    assert len(_events(home, "fire")) == 2


def test_mixed_call_failure_and_busy_lock_counts_no_session_failure(home, root, backend, tmp_path, monkeypatch):
    bad, good = "s1mixedlock-0000", "s2mixedlock-0000"
    bp = write_session(root, bad, session_rows(bad, host(tmp_path)))
    gp = write_session(root, good, session_rows(good, host(tmp_path)))
    backend.answers[bad] = [FakeOutcome(ok=False, failure="exit", detail="synthetic failed call", rc=1)]
    backend.answers[good] = output([lesson()])

    class Busy:
        def __enter__(self):
            raise gitops.GitOpsError("synthetic lock unavailable")

        def __exit__(self, *args):
            return False

    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: Busy())
        first = run(home)
    assert len(backend.specs) == 2 and not first.landed  # control: one call failed, one succeeded
    assert cursor(bp) is None and cursor(gp) is None
    f = miner.miner_dir() / engine.FAILURES_NAME
    assert (json.loads(f.read_text()) if f.exists() else {}) == {}


@pytest.mark.parametrize("owner", ["parent", "fork"])
@pytest.mark.parametrize("mode", ["call", "landing", "cap", "halted-landing"])
def test_claim_owner_matrix_retries_missing_lesson(home, root, backend, tmp_path, monkeypatch, owner, mode):
    parent = "s1matrix-0000" if owner == "parent" else "s2matrix-0000"
    fork = "s2matrix-0000" if owner == "parent" else "s1matrix-0000"
    rows = session_rows(parent, host(tmp_path))
    fork_rows = _fork_rows(rows, fork, 8, tmp_path, "validate the nightly export too")
    claimer = parent if owner == "parent" else fork  # the fixed order: same first timestamp, then the id
    if mode == "halted-landing":
        if claimer == parent:
            rows = rows + [typed(parent, 8, "<command-name>/self-learn:teach</command-name>", host(tmp_path))]
        else:
            fork_rows += [typed(fork, 10, "<command-name>/self-learn:teach</command-name>", host(tmp_path))]
    paths = {parent: write_session(root, parent, rows), fork: write_session(root, fork, fork_rows)}
    other = fork if claimer == parent else parent
    stamp = max(p.stat().st_mtime for p in paths.values())
    os.utime(paths[claimer], (stamp - 1, stamp - 1))
    os.utime(paths[other], (stamp - 2, stamp - 2))  # mtime says the other one is older: it must not matter
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
    assert _called(backend)[0] == claimer and not first.landed
    assert cursor(paths[claimer]) is None and cursor(paths[other]) is None
    assert not any(u.startswith(parent) or u.startswith(fork) for u in _store_rows())
    backend.answers[claimer] = output([lesson()])
    run(home)
    assert len(pending(home)) == 1
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
    assert cursor(pp) is None and cursor(fp) is None and not _store_rows()
    assert [e["record"] for e in _events(home, kind)] == [a]
    run(home)
    events = _events(home, kind)
    assert sorted(e["record"] for e in events) == [a, b]
    assert {e["origin"] for e in events} == {f"transcript:{parent}#L{4 if kind == 'fire' else 3}"}
    assert cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9 and len(pending(home)) == 1
    run(home)
    assert len(pending(home)) == 1 and len(_events(home, kind)) == 2


@pytest.mark.parametrize("how", ["call", "landing", "cap", "bad-output", "checker"])
def test_a_claimer_that_fails_lands_next_run_once(home, root, backend, tmp_path, monkeypatch, how):
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
    assert cursor(pp) is None and cursor(fp) is None and f"{parent}-u-3" not in _store_rows()
    backend.answers[parent] = output([lesson()])
    run(home)
    assert len(pending(home)) == 1 and cursor(pp)["lines"] == 7
    run(home)
    assert len(pending(home)) == 1


def test_a_fork_planned_first_by_mtime_changes_nothing(home, root, backend, tmp_path):
    parent, fork = "s1rvspar-0000", "s2rvsfrk-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    os.utime(fp, (1_700_000_000, 1_700_000_000))
    backend.answers[fork] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    backend.answers[parent] = output([lesson()])
    first = run(home)
    # the parent judged the shared stretch and landed; the fork failed, so the family holds
    assert len(first.landed) == 1 and cursor(pp) is None and cursor(fp) is None
    backend.answers[fork] = output([lesson()])
    second = run(home)
    assert second.landed == [] and len(pending(home)) == 1  # the replayed lesson is known by its origin
    assert cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9


def test_a_busy_lock_four_times_then_lands(home, root, backend, tmp_path, monkeypatch):
    sid = "s1lockgu-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])

    class Busy:
        def __enter__(self):
            raise gitops.GitOpsError("lock busy")

        def __exit__(self, *a):
            return False

    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: Busy())
        for _ in range(4):
            run(home)
    f = miner.miner_dir() / engine.FAILURES_NAME
    assert (json.loads(f.read_text()) if f.exists() else {}) == {}
    run(home)
    assert len(pending(home)) == 1 and cursor(path)["lines"] == 7


def test_an_outage_counts_nothing(home, root, backend, tmp_path):
    sids = [f"s{i}outage-0000" for i in range(2)]
    for s in sids:
        write_session(root, s, session_rows(s, host(tmp_path)))
        backend.answers[s] = [FakeOutcome(ok=False, failure="exit", detail="Not logged in", rc=1)]
    for _ in range(3):
        run(home)
    f = miner.miner_dir() / engine.FAILURES_NAME
    assert (json.loads(f.read_text()) if f.exists() else {}) == {}
    for s in sids:
        backend.answers[s] = output([lesson()])
    run(home)
    assert len(pending(home)) == 2


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
    assert git(home, "status", "--porcelain").stdout.strip() == ""


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


# -------------------------------------------------------- family shapes


def test_a_three_member_chain_holds_whole_when_its_middle_fails(home, root, backend, tmp_path):
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
    assert {r["family"] for r in _rows(first).values()} == {a}
    assert all(r["family_held"].startswith(f"{b}:") for r in _rows(first).values())
    assert cursor(pa) is None and cursor(pb) is None and cursor(pc) is None and not _store_rows()
    backend.answers[b] = output([l_b])
    second = run(home)
    assert _called(backend, 3) == [a, b, c] and len(second.landed) == 1 and len(pending(home)) == 3
    assert cursor(pa)["lines"] == 7 and cursor(pb)["lines"] == 9 and cursor(pc)["lines"] == 11
    run(home)
    assert len(pending(home)) == 3


def test_a_family_whose_fork_fails_lands_the_fork_s_output_once(home, root, backend, tmp_path):
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
    assert len(first.landed) == 1 and cursor(pp) is None and cursor(fp) is None
    backend.answers[fork] = output([l_f])
    second = run(home)
    assert len(second.landed) == 1 and len(pending(home)) == 2
    assert [o["outcome"] for o in second.outcomes] == ["skipped-known-origin", "landed"]
    run(home)
    assert len(pending(home)) == 2


def test_a_fork_of_a_parent_judged_last_night_is_a_family_of_one(home, root, backend, tmp_path):
    parent, fork = "s1lastnt-0000", "s2lastnt-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    backend.answers[parent] = output([lesson()])
    run(home)
    assert len(pending(home)) == 1 and f"{parent}-u-3" in _store_rows()
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    backend.answers[fork] = output([lesson()])
    second = run(home)
    assert _called(backend, 1) == [fork]  # the parent has no new lines: the family is the fork alone
    (row,) = _rows(second).values()
    assert row["family"] == fork and "family_held" not in row
    assert second.landed == [] and len(pending(home)) == 1 and cursor(fp)["lines"] == 9
    assert cursor(pp)["lines"] == 7


def test_max_sessions_admits_a_family_whole_or_not_at_all(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "2")
    single = "s1single-0000"
    parent, fork = "s2famadm-0000", "s3famadm-0000"
    write_session(root, single, session_rows(single, host(tmp_path)))
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    first = run(home)
    assert _called(backend) == [single] and first.engine["deferred"] == 2  # the pair does not fit beside it
    assert cursor(pp) is None and cursor(fp) is None
    run(home)
    assert _called(backend, 1) == [parent, fork] and cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9


def test_a_family_larger_than_the_cap_is_admitted_whole_when_first(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "1")
    parent, fork = "s1famcap-0000", "s2famcap-0000"
    rows = session_rows(parent, host(tmp_path))
    write_session(root, parent, rows)
    write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    later = "s9later-0000"
    write_session(root, later, session_rows(later, host(tmp_path)))
    result = run(home)
    assert _called(backend) == [parent, fork] and result.engine["deferred"] == 1
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert rec["admitted_over_cap"] == [{"family": parent, "members": 2}]
    contract.load_run(run_dir(result))


def test_a_family_over_the_lesson_cap_completes_over_successive_runs(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    parent, fork = "s1lescap-0000", "s2lescap-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    l_f = lesson(id="L2", evidence=[{"line": 8, "quote": "add the export to the nightly job"}], steps=[],
                 verification=None, incident_cost=None, trigger="About to add an export to the nightly job",
                 instruction="Ask which job owns exports first, because two jobs write them")
    backend.answers[parent] = output([lesson()])
    backend.answers[fork] = output([l_f])
    first = run(home)
    assert len(first.landed) == 1 and cursor(pp) is None and cursor(fp) is None
    assert _rows(first)[fork]["landing"] == "held" and _rows(first)[parent]["family_held"].startswith(f"{fork}:")
    second = run(home)
    # the parent's landed lesson is known by its origin and does not count against the cap
    assert [o["outcome"] for o in second.outcomes] == ["skipped-known-origin", "landed"]
    assert len(pending(home)) == 2 and cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 9
    run(home)
    assert len(pending(home)) == 2


# ------------------------------------------------- store and records


def test_an_incomplete_session_s_non_spine_citations_stay_out_of_the_store(home, root, backend, tmp_path, monkeypatch):
    sid = "s1nonspn-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    miner._advance_cursors([(miner.SessionSlice(path, sid, PROJECT, 0, ["x"] * 4, 0), False)])  # pyright: ignore[reportPrivateUsage]
    rows = session_rows(sid, host(tmp_path)) + [typed(sid, 8, "and keep the export log too", host(tmp_path))]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    backend.answers[sid] = output([lesson(evidence=[{"line": 6, "quote": "always run the checks"}], steps=[],
                                          verification={"line": 5, "quote": "The check failed", "how": "it ran"},
                                          incident_cost={"line": 2, "text": "a review spent on a false pass"})])
    real = miner.create_record

    def refused(*a, **k):
        raise OSError("synthetic")

    with monkeypatch.context() as m:
        m.setattr(miner, "create_record", refused)
        first = run(home)
    out = json.loads((run_dir(first) / "out" / f"{sid}.json").read_text())
    assert out["lessons"][0]["incident_cost"]["ref"]["line"] == 2  # control: a citation before the range was kept
    assert _store_rows() == frozenset()
    assert real is miner.create_record
    second = run(home)
    assert len(second.landed) == 1 and f"{sid}-a-2" in _store_rows()


def test_landed_lessons_counts_lessons_only_on_a_run_with_folds(home, root, backend, tmp_path):
    rid = "lrn-0000f1d1"
    put_record(home, rid)
    sid = "s1lndfld-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()], sightings=[_sighting(sid, rid, line=6, quote="always run the checks")])
    result = run(home)
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert result.folded == [rid] and rec["landed"]["lessons"] == 1 and rec["landed"]["folded"] == 1


def _valid_run(home, root, backend, tmp_path) -> dict:
    sid = "s1contrc-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    return json.loads((run_dir(run(home)) / "run.json").read_text())


@pytest.mark.parametrize("bad", [
    {"landed": "three"},
    {"landed": {"lessons": 1, "folded": 0, "recurrences": 0, "fires": 0}},
    {"landed": {"lessons": -1, "folded": 0, "recurrences": 0, "fires": 0, "sessions_failed": 0}},
    {"landed": {"lessons": 1, "folded": 0, "recurrences": 0, "fires": 0, "sessions_failed": 0, "extra": 1}},
    {"admitted_over_cap": [{"family": "x", "members": 1}]},
])
def test_the_contract_refuses_a_malformed_landed_object(home, root, backend, tmp_path, bad):
    rec = _valid_run(home, root, backend, tmp_path)
    assert contract.validate_run(rec) == []  # control: the record as written is valid
    assert contract.validate_run({**rec, **bad}) != []


@pytest.mark.parametrize("key,value", [("landing", "landed"), ("landing", 3), ("family", ""), ("family_held", 7)])
def test_the_contract_refuses_a_bad_session_row_value(home, root, backend, tmp_path, key, value):
    rec = _valid_run(home, root, backend, tmp_path)
    assert contract.validate_run(rec) == [] and rec["sessions"][0]["landing"] == "complete"  # control
    bad = dict(rec, sessions=[dict(rec["sessions"][0], **{key: value})])
    assert contract.validate_run(bad) != []


def test_a_member_skipped_only_for_its_claimed_moments_holds_with_its_family(home, root, backend, tmp_path):
    parent, fork = "s1skpclm-0000", "s2skpclm-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, [dict(r, sessionId=fork) for r in rows])  # an identical copy
    backend.answers[parent] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    first = run(home)
    assert _called(backend) == [parent] and first.engine["skipped"] == {"nothing-new": 1}  # control
    assert _rows(first)[fork]["family_held"].startswith(f"{parent}:")
    assert cursor(pp) is None and cursor(fp) is None
    backend.answers[parent] = output([lesson()])
    second = run(home)
    assert len(second.landed) == 1 and cursor(pp)["lines"] == 7 and cursor(fp)["lines"] == 7


def test_a_family_with_a_member_that_failed_before_waits_behind_a_fresh_one(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "2")
    parent, fork, fresh = "s1fwaitp-0000", "s2fwaitf-0000", "s3fresh0-0000"
    rows = session_rows(parent, host(tmp_path))
    pp = write_session(root, parent, rows)
    fp = write_session(root, fork, _fork_rows(rows, fork, 8, tmp_path))
    write_session(root, fresh, session_rows(fresh, host(tmp_path)))
    data = {str(fp): {"start": 0, "failures": 1}}  # only the fork failed before
    (miner.miner_dir() / engine.FAILURES_NAME).write_text(json.dumps(data))
    run(home)
    assert _called(backend) == [fresh] and cursor(pp) is None and cursor(fp) is None
    run(home)
    assert _called(backend, 1) == [parent, fork]
