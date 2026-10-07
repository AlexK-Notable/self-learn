"""U4-harness · the offline comparison (``python -m self_learn.mining.compare``).

H1-H7 of the U4 spec's section 7.9, plus H8 (every skipped moment is logged by
key), H9 (the shared-but-maybe-different sample) and H10 (rule checks against
the old miner's fires), which the user's 2026-10-06 decisions and section 7.5
add. Synthetic transcripts, scratch ledgers and scratch caches only: no real
session, no model, no network. The canary strings are not secret-shaped (a
control proves the secret scan leaves them alone) and the fake secrets, if any,
would be built at run time.

On master every test here fails at import (the modules do not exist); each is
also mutation-checked by breaking the behaviour it names (the lane's report
lists the runs).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import refs
from self_learn.index.store import LessonIndex
from self_learn.mining import compare, contract
from self_learn.records import Record
from self_learn.scan import redact

CANARY = "canary-tango-seven"
RUN_ID = "20261006T010203Z-7"
PROJECT = "-work-repo"
T0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- entries


def typed(text):
    return {"type": "user", "origin": {"kind": "human"}, "promptSource": "typed",
            "message": {"role": "user", "content": text}}


def asst(text="ok"):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def result(text="done"):
    return {"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": text}]}}


def relay(text="a relayed message"):
    return {"type": "user", "isMeta": True, "message": {"role": "user", "content": text}}


def sdk(text):
    return {"type": "user", "promptSource": "sdk", "message": {"role": "user", "content": text}}


def old_user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def sysrow(text="system row"):
    return {"type": "system", "content": text}


def conversation(turns, prefix="turn"):
    """``turns`` typed turns, each followed by an assistant message: the
    typed turn k sits at line 2k-1 and its answer at 2k."""
    out = []
    for k in range(1, turns + 1):
        out += [typed(f"{prefix} {k} text"), asst(f"{prefix} {k} answer")]
    return out


def stamp(sid, entries):
    """uuid, timestamp and cwd per entry; an entry that already has one (a
    fork's copy) keeps it."""
    for n, e in enumerate(entries, 1):
        e.setdefault("uuid", f"{sid}-u{n}")
        e.setdefault("timestamp", (T0 + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        e.setdefault("cwd", "/work/repo")
    return entries


# ------------------------------------------------------------------ world


class World:
    """A synthetic frozen set, ledger and shadow run under ``tmp_path``."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.set_dir = tmp_path / "set"
        self.home = tmp_path / "ledger"
        for sub in ("pending", "resolved"):
            (self.home / "user" / sub).mkdir(parents=True)
        self.files: dict[str, list[dict]] = {}
        self.moments: dict[str, list[int]] = {}
        self.subagents: dict[str, int] = {}
        self.written = False
        self.runs = 0

    # -- the set
    def session(self, sid, entries, moments=(), subagents=0):
        self.files[sid] = stamp(sid, entries)
        self.moments[sid] = list(moments)
        self.subagents[sid] = subagents
        return self.files[sid]

    def write_set(self):
        manifest = []
        for sid, entries in self.files.items():
            path = self.set_dir / "sessions" / PROJECT / f"{sid}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
            manifest.append({"session": sid, "project": PROJECT, "file": f"{PROJECT}/{sid}.jsonl",
                             "bytes": path.stat().st_size, "sha256": "0" * 64,
                             "known_moment_lines": sorted(self.moments[sid])})
            for i in range(self.subagents[sid]):
                sub = self.set_dir / "sessions" / PROJECT / sid / "subagents" / f"agent-{i}.jsonl"
                sub.parent.mkdir(parents=True, exist_ok=True)
                sub.write_text(json.dumps(stamp(f"{sid}-sub{i}", [typed("brief")])[0]) + "\n", encoding="utf-8")
                manifest.append({"session": sid, "project": PROJECT,
                                 "file": f"{PROJECT}/{sid}/subagents/agent-{i}.jsonl",
                                 "bytes": 1, "sha256": "0" * 64, "known_moment_lines": []})
        (self.set_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        self.written = True

    # -- pointers
    def typed_lines(self, sid):
        return contract.typed_turn_lines(self.files[sid])

    def ptr(self, sid, line, *, in_file=None):
        """A checked pointer to ``line`` of ``sid`` (the file ``in_file`` when the
        pointer is taken from a fork's own numbering)."""
        entries = self.files[in_file or sid]
        e = entries[line - 1]
        ref = {"session": in_file or sid, "project_dir": PROJECT, "line": line, "uuid": e.get("uuid"),
               "entry_ts": e.get("timestamp"), "cwd": e.get("cwd"), "role": refs.role_of(e)}
        return {"ref": ref, "turn": contract.turn_of(self.typed_lines(in_file or sid), line)}

    def evidence(self, sid, line, quote="a quote", *, in_file=None, verdict="exact", corrected_from=None):
        d = dict(self.ptr(sid, line, in_file=in_file))
        d.update(quote=quote, verdict=verdict, corrected_from=corrected_from)
        return d

    # -- items
    def lesson(self, lid, evidence, *, trigger="About to repeat the mistake", instruction="Check first"):
        return {"id": lid, "shape": "correction", "scope": "user", "type": "behavior", "kind": "anti-pattern",
                "trigger": trigger, "instruction": instruction, "fact": None, "context": None,
                "evidence": evidence, "steps": [], "verification": None, "incident_cost": None,
                "generality": "general-practice", "why_durable": "it recurs", "subagent_cause": None}

    def sighting(self, record, evidence):
        return {"record": record, "evidence": evidence}

    def rule_check(self, record, outcome, sid, line):
        return {"record": record, "outcome": outcome, "situation": self.ptr(sid, line), "action": None}

    def out(self, sid, *, lessons=(), sightings=(), rule_checks=(), status="ok", judged=None,
            drops=(), mode="testset", run_id=RUN_ID):
        n = len(self.files[sid])
        first, last = judged or (1, n)
        typed_lines = self.typed_lines(sid)
        return {
            "contract": "miner-output/1", "run_id": run_id, "mode": mode, "model": "claude-sonnet-5",
            "method_version": "1",
            "session": {"id": sid, "project_dir": PROJECT, "file": f"{PROJECT}/{sid}.jsonl",
                        "judged": {"first_line": first, "last_line": last,
                                   "first_turn": contract.turn_of(typed_lines, first) or None,
                                   "last_turn": contract.turn_of(typed_lines, last) or None},
                        "typed_turns": len(typed_lines), "spine_tokens_est": 100, "over_budget": False,
                        "search_mode": "lexical-only", "flags": []},
            "status": status,
            "lessons": list(lessons) if status == "ok" else [],
            "sightings": list(sightings) if status == "ok" else [],
            "rule_checks": list(rule_checks) if status == "ok" else [],
            "drops": list(drops), "redactions": 0,
        }

    # -- the ledger
    def record(self, rid, source, status, cites, *, via="origin", trigger="Old trigger text", instruction="Old instruction text"):
        evidence = []
        for sid, line in cites:
            item = {"quote": "an old quote", "session": sid, "ts": "2026-09-01T10:00:00Z"}
            if via == "ref":
                item["ref"] = self.ptr(sid, line)["ref"]
            else:
                item["origin"] = f"transcript:{sid}#L{line}"
            evidence.append(item)
        rec = Record.create(type="behavior", scope="user", source=source, kind="anti-pattern",
                            trigger=trigger, instruction=instruction, evidence=evidence, record_id=rid)
        rec.set_status(status)
        folder = "pending" if status == "pending" else "resolved"
        rec.write(self.home / "user" / folder / f"{rid}.md")

    # -- the run
    def run(self, sessions, *, mode="testset", run_id=RUN_ID, started_at="2026-10-06T01:02:03Z", testset=True,
            cost=0.25):
        """``sessions``: ``("called", out_dict)``, ``("skipped", sid, reason)`` or
        ``("not-run", sid, reason)``. Returns the run folder; every document is
        checked with the contract's validators before it is written."""
        if not self.written:
            self.write_set()
        self.runs += 1
        run_dir = self.tmp / f"run-{self.runs}"
        (run_dir / "out").mkdir(parents=True)
        rows, totals_drops, skipped = [], {}, {}
        lessons = sightings = checks = called = not_run = 0
        for spec in sessions:
            if spec[0] == "called":
                out = spec[1]
                sid = out["session"]["id"]
                assert contract.validate_checked_output(out) == [], contract.validate_checked_output(out)
                (run_dir / "out" / f"{sid}.json").write_text(json.dumps(out), encoding="utf-8")
                called += 1
                lessons += len(out["lessons"])
                sightings += len(out["sightings"])
                checks += len(out["rule_checks"])
                for d in out["drops"]:
                    totals_drops[d["reason"]] = totals_drops.get(d["reason"], 0) + 1
                rows.append(_run_row(sid, "called", None, out["status"], cost[sid] if isinstance(cost, dict) else cost))
            else:
                _kind, sid, reason = spec
                if spec[0] == "skipped":
                    skipped[reason] = skipped.get(reason, 0) + 1
                else:
                    not_run += 1
                rows.append(_run_row(sid, spec[0], reason, None, None))
        run = {
            "contract": "miner-shadow-run/1", "run_id": run_id, "mode": mode, "started_at": started_at,
            "finished_at": "2026-10-06T01:20:00Z", "model": "claude-sonnet-5", "method_version": "1",
            "settings": {"parallel": 4, "spine_tokens": 20000, "max_usd": 40.0},
            "testset": ({"dir": str(self.set_dir), "manifest_sha256": hashlib.sha256((self.set_dir / "MANIFEST.json").read_bytes()).hexdigest()}
                        if testset and mode == "testset" else None),
            "status": "ok", "search_mode": "lexical-only", "sessions": rows,
            "totals": {"called": called, "skipped": skipped, "not_run": not_run,
                       "cost_usd": round(sum(cost.values()) if isinstance(cost, dict) else cost * called, 6), "lessons": lessons, "sightings": sightings,
                       "rule_checks": checks, "drops": totals_drops},
        }
        assert contract.validate_run(run) == [], contract.validate_run(run)
        (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
        return run_dir


def _run_row(sid, status, reason, out_status, cost):
    return {"session": sid, "file": f"{PROJECT}/{sid}.jsonl", "status": status, "reason": reason,
            "out_status": out_status, "attempts": 1 if status == "called" else 0, "failure_class": None,
            "cost_usd": cost, "turns": 4 if status == "called" else None,
            "claude_session_id": "c-1" if status == "called" else None, "usage_first_response": None,
            "usage_session": None, "charter_denials": 0, "duration_secs": 5.0 if status == "called" else 0}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "ledger"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("SELF_LEARN_ANALYST_MODEL", raising=False)
    return tmp_path


@pytest.fixture
def world(env):
    return World(env)


def report(world, run_dir, *extra, expect=0, capsys=None, testset=True):
    """Run ``compare report`` in process; returns ``(report.json, stdout, stderr)``."""
    argv = ["report", "--run", str(run_dir), "--home", str(world.home), *extra]
    if testset:
        argv += ["--testset", str(world.set_dir)]
    rc = compare.main(argv)
    cap = capsys.readouterr() if capsys is not None else None
    assert rc == expect, (rc, cap.err if cap else "")
    path = run_dir / "compare" / "report.json"
    rep = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return rep, (cap.out if cap else ""), (cap.err if cap else "")


def bucket(rep, b):
    return rep["moments"]["by_bucket"][b]


# ------------------------------------------------------------------- H1


@pytest.mark.parametrize("status", ["routed", "superseded", "deferred", "pending"])
def test_h1_a_mined_record_that_was_not_rejected_makes_the_moment_bucket_a(world, status, capsys):
    world.session("sess-a", conversation(6), moments=[3])
    world.record("lrn-00000001", "session", status, [("sess-a", 3)])
    run = world.run([("called", world.out("sess-a"))])
    rep, _, _ = report(world, run, capsys=capsys)
    assert bucket(rep, "A")["total"] == 1 and bucket(rep, "B")["total"] == 0


def _buckets_world(world):
    """Moments in every bucket, none found: A at 3 and 11, B at 7 and 21, C at 13, other at 23."""
    world.session("sess-a", conversation(12), moments=[3, 7, 11, 13, 21, 23])
    # 3: a routed mined record → A
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    # 7: rejected mined records only, cited by origin AND by a ref mapping → B
    world.record("lrn-00000002", "session", "rejected", [("sess-a", 7)])
    world.record("lrn-00000003", "session", "rejected", [("sess-a", 7)], via="ref")
    # 11: one routed among rejected ones → A
    world.record("lrn-00000004", "session", "rejected", [("sess-a", 11)])
    world.record("lrn-00000005", "session", "routed", [("sess-a", 11)])
    # 13: only a /teach record → C
    world.record("lrn-00000006", "teach", "pending", [("sess-a", 13)], via="ref")
    # 21: a rejected mined record and a teach record → B (the mined record decides)
    world.record("lrn-00000007", "session", "rejected", [("sess-a", 21)])
    world.record("lrn-00000008", "teach", "pending", [("sess-a", 21)])
    # 23: cited by nobody
    return world.run([("called", world.out("sess-a"))])


def test_h1_buckets_from_the_records_that_cite_the_moments(world, capsys):
    run = _buckets_world(world)
    rep, _, _ = report(world, run, capsys=capsys)
    assert [bucket(rep, b)["total"] for b in ("A", "B", "C")] == [2, 2, 1]
    assert bucket(rep, "other")["total"] == 1
    assert rep["moments"]["total"] == 6
    # B is on its own line and never counts as a miss; A does
    assert bucket(rep, "B")["counts_as_miss"] is False and bucket(rep, "A")["counts_as_miss"] is True
    assert bucket(rep, "A")["missed"] == 2  # nothing was found in this run


def test_h1_a_bucket_b_moment_is_never_called_missed_anywhere(world, capsys):
    run = _buckets_world(world)
    rep, out, _ = report(world, run, capsys=capsys)
    # the list of misses is bucket A's; B, C and other are listed apart, with their bucket, as not found
    assert rep["missed_moments"] == sorted(["sess-a#L3", "sess-a#L11"])
    assert rep["not_found_moments"] == {"sess-a#L7": "B", "sess-a#L21": "B", "sess-a#L13": "C", "sess-a#L23": "other"}
    assert sorted(rep["missed_a_marks"]) == rep["missed_moments"]
    # stdout says "missed" for A and "not found" for the rest
    lines = {ln.split(":")[0]: ln for ln in out.splitlines() if ln.startswith("moments ")}
    assert "missed 2" in lines["moments A"] and "not found" not in lines["moments A"]
    for b, n in (("B", 2), ("C", 1), ("other", 1)):
        assert f"not found {n}" in lines[f"moments {b}"] and "missed" not in lines[f"moments {b}"], lines[f"moments {b}"]
    # report.md too: no "missed" list that holds a B moment, and the table row says "not found"
    md = (run / "compare" / "report.md").read_text(encoding="utf-8")
    assert "Missed, all buckets" not in md
    missed_lines = [ln for ln in md.splitlines() if ln.startswith("**Missed")]
    assert len(missed_lines) == 2  # control: "Missed, to spot-check" and "Missed" both rendered
    for ln in missed_lines:
        assert "sess-a#L3" in ln and "sess-a#L11" in ln
        assert not any(f"sess-a#L{n}`" in ln for n in (7, 13, 21, 23)), ln
    not_found_line = next(ln for ln in md.splitlines() if ln.startswith("**Not found"))
    assert all(f"sess-a#L{n}" in not_found_line for n in (7, 13, 21, 23)) and "sess-a#L3`" not in not_found_line
    # the table: the "missed" and "missed strict" cells of B, C and other read "not found N"; A's are numbers
    lines = md.splitlines()
    head = next(ln for ln in lines if ln.startswith("| line |"))
    cols = [c.strip() for c in head.strip("|\n").split("|")]
    at_missed, at_strict = cols.index("missed"), cols.index("missed strict")

    def cells(prefix: str) -> list[str]:
        ln = next(ln for ln in lines if ln.startswith(prefix))
        return [c.strip() for c in ln.strip("|\n").split("|")]

    assert cells("| A ")[at_missed] == "2" and cells("| A ")[at_strict] == "2"
    for prefix, n in (("| B ", 2), ("| C ", 1), ("| other ", 1)):
        row = cells(prefix)
        assert row[at_missed] == f"not found {n}" and row[at_strict] == f"not found {n}", (prefix, row)


def test_h1_the_spot_check_and_template_hold_only_bucket_a_misses(world, capsys):
    run = _buckets_world(world)
    rep, _, _ = report(world, run, capsys=capsys)
    sheet = (run / "compare" / "spot-check.md").read_text(encoding="utf-8")
    assert "### sess-a#L3\n" in sheet and "### sess-a#L11\n" in sheet  # control: bucket A's are on the sheet
    for key in ("sess-a#L7", "sess-a#L21", "sess-a#L13", "sess-a#L23"):
        assert f"### {key}\n" not in sheet, key
    tpl = json.loads((run / "compare" / "spot-marks.template.json").read_text(encoding="utf-8"))
    assert sorted(tpl) == sorted(["sess-a#L3", "sess-a#L11"])


def test_h1_bucket_of_directly():
    def rec(source, status):
        return compare.CitingRecord("lrn-00000001", source, status, "user/user", "t")

    assert compare.bucket_of([rec("session", "routed")]) == "A"
    assert compare.bucket_of([rec("session", "rejected"), rec("session", "routed")]) == "A"
    assert compare.bucket_of([rec("session", "rejected")]) == "B"
    assert compare.bucket_of([rec("teach", "pending")]) == "C"
    assert compare.bucket_of([rec("session", "rejected"), rec("teach", "pending")]) == "B"
    assert compare.bucket_of([rec("backlog", "routed")]) == "other"
    assert compare.bucket_of([]) == "other"


# ------------------------------------------------------------------- H2


def test_h2_strict_loose_and_missed(world, capsys):
    a = world.session("sess-a", conversation(12), moments=[3, 7, 13, 21])
    # the moment at line 21 has no uuid on its entry
    del a[20]["uuid"]
    # a fork: two system rows, then a copy of sess-a's first 16 lines (same uuids, lines + 2)
    fork = [sysrow("fork header 1"), sysrow("fork header 2")] + [dict(e) for e in a[:16]]
    world.session("sess-f", fork)
    for line in (3, 7, 13, 21):
        world.record(f"lrn-{line:08x}", "session", "routed", [("sess-a", line)])

    # sess-f's own line 5 is the copy of sess-a's line 3 (T2)
    fork_ev = world.evidence("sess-f", 5)
    assert fork_ev["ref"]["uuid"] == a[2]["uuid"] and fork_ev["ref"]["session"] == "sess-f"
    loose_ev = world.evidence("sess-a", 10)  # T5: one turn from the moment at line 7 (T4)
    far_ev = world.evidence("sess-a", 17)  # T9: two turns from the moment at line 13 (T7)
    nouuid_ev = world.evidence("sess-a", 21)
    assert nouuid_ev["ref"]["uuid"] is None  # the null-uuid fallback: same session and line
    run = world.run([
        ("called", world.out("sess-a", lessons=[world.lesson("L1", [loose_ev]), world.lesson("L2", [far_ev]),
                                                  world.lesson("L3", [nouuid_ev])])),
        ("called", world.out("sess-f", lessons=[world.lesson("L1", [fork_ev])])),
    ])
    rep, _, _ = report(world, run, capsys=capsys)
    A = bucket(rep, "A")
    assert A["total"] == 4
    assert A["found_strict"] == 2  # the fork copy (by uuid) and the null-uuid line
    assert A["found_loose"] == 3  # plus the one-turn-away item
    assert A["missed"] == 1 and A["missed_strict"] == 2  # only line 13 is missed even loosely
    assert rep["missed_moments"] == ["sess-a#L13"]
    # items: L2 (two turns from anything) is the only new one
    assert rep["new_items"] == [f"{RUN_ID}/sess-a/L2"]
    assert rep["items"]["matched"] == 3 and rep["items"]["matched_strict"] == 2


def test_h2_a_subagent_pointer_never_hits_by_line(world, capsys):
    a = world.session("sess-a", conversation(6), moments=[3])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    sub = world.evidence("sess-a", 3)
    sub["ref"] = dict(sub["ref"], uuid=None, role="subagent", subagent_file="subagents/agent-1.jsonl")
    # a subagent file's line 3 is not the main session's line 3: not found (and the item is new)
    run = world.run([("called", world.out("sess-a", lessons=[world.lesson("L1", [sub])]))])
    rep, _, _ = report(world, run, capsys=capsys)
    assert bucket(rep, "A")["found_loose"] == 0 and bucket(rep, "A")["missed"] == 1
    # positive control: the same pointer to the main file hits
    run2 = world.run([("called", world.out("sess-a", lessons=[world.lesson("L1", [world.evidence("sess-a", 3)])]))])
    rep2, _, _ = report(world, run2, capsys=capsys)
    assert bucket(rep2, "A")["found_strict"] == 1
    assert a[2]["uuid"]  # the entry did carry a uuid


def test_h2_two_turns_away_is_not_loose(world, capsys):
    world.session("sess-a", conversation(8), moments=[7])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 7)])
    one = world.evidence("sess-a", 9)  # T5 vs the moment's T4
    two = world.evidence("sess-a", 11)  # T6
    run1 = world.run([("called", world.out("sess-a", lessons=[world.lesson("L1", [one])]))])
    run2 = world.run([("called", world.out("sess-a", lessons=[world.lesson("L1", [two])]))])
    r1, _, _ = report(world, run1, capsys=capsys)
    r2, _, _ = report(world, run2, capsys=capsys)
    assert bucket(r1, "A")["found_loose"] == 1 and bucket(r1, "A")["found_strict"] == 0
    assert bucket(r2, "A")["found_loose"] == 0 and bucket(r2, "A")["missed"] == 1


def test_h2_a_fork_holding_the_moments_uuid_counts_for_loose_too(world, capsys):
    a = world.session("sess-a", conversation(8), moments=[7])
    world.session("sess-f", [sysrow("fork header 1"), sysrow("fork header 2")] + [dict(e) for e in a])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 7)])
    # sess-f's line 11 is the copy of sess-a's line 9 (T5), one turn from the moment (T4)
    ev = world.evidence("sess-f", 11)
    assert ev["turn"] == 5 and ev["ref"]["uuid"] == a[8]["uuid"]
    run = world.run([("called", world.out("sess-a")), ("called", world.out("sess-f", lessons=[world.lesson("L1", [ev])]))])
    rep, _, _ = report(world, run, capsys=capsys)
    assert bucket(rep, "A")["found_loose"] == 1 and bucket(rep, "A")["found_strict"] == 0
    # control: a session that does NOT hold the moment's uuid does not count, whatever its turn numbers
    world.session("sess-g", conversation(8))
    ev2 = world.evidence("sess-g", 9)
    assert ev2["turn"] == 5
    run2 = world.run([("called", world.out("sess-a")), ("called", world.out("sess-g", lessons=[world.lesson("L1", [ev2])]))])
    rep2, _, _ = report(world, run2, capsys=capsys)
    assert bucket(rep2, "A")["found_loose"] == 0 and bucket(rep2, "A")["missed"] == 1


def test_h2_a_moment_resolves_through_its_uuid_not_a_same_id_copy(world, capsys):
    entries = conversation(6)
    entries[2] = typed(f"{CANARY} the real moment")
    world.session("sess-a", entries, moments=[3])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    run = world.run([("called", world.out("sess-a"))])
    # a LARGER file with the same session id under the archive root: same line 3, another entry
    decoy = stamp("decoy", conversation(30))
    decoy[2] = typed("decoy text at the same line")
    path = world.set_dir / "sessions" / "from-archive" / "-other-proj" / "sess-a.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in decoy), encoding="utf-8")
    report(world, run, capsys=capsys)
    sheet = (run / "compare" / "spot-check.md").read_text(encoding="utf-8")
    assert "### sess-a#L3\n" in sheet  # control: the missed moment is on the sheet, with an excerpt
    assert CANARY in sheet and "decoy text" not in sheet


def test_h2_a_moment_that_does_not_resolve_is_counted_not_hidden(world, capsys):
    world.session("sess-a", conversation(4), moments=[3, 99])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    world.record("lrn-00000002", "session", "routed", [("sess-a", 99)])
    run = world.run([("called", world.out("sess-a"))])
    rep, _, _ = report(world, run, capsys=capsys)
    assert rep["moments"]["unresolved"] == 1 and bucket(rep, "A")["total"] == 2
    assert rep["skipped_moments"] == {"sess-a#L99": "out-of-range"}


def test_h2_a_sighting_counts_and_names_the_citing_record(world, capsys):
    world.session("sess-a", conversation(10), moments=[3, 9])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    world.record("lrn-00000002", "session", "routed", [("sess-a", 9)])
    s1 = world.sighting("lrn-00000001", [world.evidence("sess-a", 3)])  # names the record that cites line 3
    s2 = world.sighting("lrn-00000009", [world.evidence("sess-a", 9)])  # a different record
    run = world.run([("called", world.out("sess-a", sightings=[s1, s2]))])
    rep, _, _ = report(world, run, capsys=capsys)
    A = bucket(rep, "A")
    assert A["found_as_sighting"] == 2 and A["found_as_lesson"] == 0
    assert A["found_as_sighting_naming_citing_record"] == 1


# ------------------------------------------------------------------- H3


def _not_judged_world(world):
    """One moment (line 3, bucket A) in each kind of session the new miner may not have judged."""
    world.session("sess-ok", conversation(6), moments=[3])
    world.session("sess-old", [old_user("old one"), old_user("old two"), asst(), old_user("old three")], moments=[2])
    world.session("sess-prog", [sdk("a program prompt"), asst(), sdk("another"), asst()], moments=[1])
    world.session("sess-fail", conversation(4), moments=[3])
    world.session("sess-bad", conversation(4), moments=[3])
    world.session("sess-ceil", conversation(4), moments=[3])
    world.session("sess-nir", conversation(4), moments=[3])
    world.session("sess-range", conversation(8), moments=[3])
    world.session("sess-halt", conversation(4), moments=[3])
    world.session("sess-new", conversation(4), moments=[3])
    for i, (sid, line) in enumerate([("sess-ok", 3), ("sess-old", 2), ("sess-prog", 1), ("sess-fail", 3),
                                     ("sess-bad", 3), ("sess-ceil", 3), ("sess-nir", 3), ("sess-range", 3),
                                     ("sess-halt", 3), ("sess-new", 3)], 1):
        world.record(f"lrn-{i:08x}", "session", "routed", [(sid, line)])
    return world.run([
        ("called", world.out("sess-ok")),
        ("skipped", "sess-old", "no-marker"),
        ("skipped", "sess-prog", "no-typed-turns"),
        ("called", world.out("sess-fail", status="failed")),
        ("called", world.out("sess-bad", status="bad-output")),
        ("not-run", "sess-ceil", "spend-ceiling"),
        ("called", world.out("sess-range", judged=(10, 16))),
        ("skipped", "sess-halt", "halted"),
        ("skipped", "sess-new", "nothing-new"),
    ])


def test_h3_a_session_that_was_not_judged_is_not_missed(world, capsys):
    run = _not_judged_world(world)
    rep, _, _ = report(world, run, capsys=capsys)
    A = bucket(rep, "A")
    assert A["total"] == 10
    # the positive control: a moment in a judged session with nothing found IS missed
    assert A["missed"] == 1 and rep["missed_moments"] == ["sess-ok#L3"]
    assert A["not_judged"] == {"no-marker": 1, "failed": 1, "bad-output": 1, "spend-ceiling": 1, "not-in-run": 1,
                               "out-of-range": 1, "halted": 1, "nothing-new": 1}
    assert A["out_of_scope"] == 1  # the program session, shelved by design
    assert A["total"] == A["found_loose"] + A["missed"] + sum(A["not_judged"].values()) + A["out_of_scope"]
    assert rep["sessions"] == {"called": 4, "ok": 2, "bad_output": 1, "failed": 1,
                               "skipped": {"halted": 1, "no-marker": 1, "no-typed-turns": 1, "nothing-new": 1}, "not_run": 1}


# ------------------------------------------------------------------- H8


def test_h8_every_skipped_moment_is_logged_by_key_with_its_reason(world, capsys):
    run = _not_judged_world(world)
    rep, out, _ = report(world, run, capsys=capsys)
    assert rep["skipped_moments"] == {
        "sess-old#L2": "no-marker",
        "sess-prog#L1": "out-of-scope",
        "sess-fail#L3": "failed",
        "sess-bad#L3": "bad-output",
        "sess-ceil#L3": "spend-ceiling",
        "sess-nir#L3": "not-in-run",
        "sess-range#L3": "out-of-range",
        "sess-halt#L3": "halted",
        "sess-new#L3": "nothing-new",
    }
    # the log is exactly what the counts add up to, and the judged-but-missed moment is not in it
    counted = sum(sum(b["not_judged"].values()) + b["out_of_scope"] for b in rep["moments"]["by_bucket"].values())
    assert len(rep["skipped_moments"]) == counted == 9
    assert "sess-ok#L3" not in rep["skipped_moments"]
    # keys only: the log is also in the markdown report
    md = (run / "compare" / "report.md").read_text(encoding="utf-8")
    assert "sess-old#L2" in md and "sess-prog#L1" in md


def test_h8_a_skipped_moment_found_by_another_session_is_not_logged(world, capsys):
    a = world.session("sess-a", conversation(6), moments=[3])
    fork = [dict(e) for e in a]
    world.session("sess-f", fork)  # a copy: every uuid is the same
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    ev = world.evidence("sess-f", 3)
    run = world.run([("skipped", "sess-a", "nothing-new"),
                     ("called", world.out("sess-f", lessons=[world.lesson("L1", [ev])]))])
    rep, _, _ = report(world, run, capsys=capsys)
    assert bucket(rep, "A")["found_strict"] == 1
    assert rep["skipped_moments"] == {}


# ------------------------------------------------------------------- H4


def _canary_world(world):
    """sess-a: the moment at line 3 (bucket A, never found: missed) and a new lesson whose evidence sits at
    line 11, each in a typed turn that carries the canary."""
    entries = conversation(8)
    entries[2] = typed(f"{CANARY} one: the moment nobody found")
    entries[10] = typed(f"{CANARY} two: where the new lesson points")
    a = world.session("sess-a", entries, moments=[3, 15])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    world.record("lrn-00000002", "session", "routed", [("sess-a", 15)])
    matched = world.lesson("L1", [world.evidence("sess-a", 15, "turn 8 text")])
    new = world.lesson("L2", [world.evidence("sess-a", 11, f"{CANARY} two")], trigger="Old trigger text repeated again")
    run = world.run([("called", world.out("sess-a", lessons=[matched, new]))])
    return a, run


def test_h4_new_items_reach_the_spot_check_and_no_text_reaches_the_counts(world, capsys):
    assert redact(CANARY)[0] == CANARY  # control: the secret scan leaves the canary alone
    _a, run = _canary_world(world)
    rep, out, err = report(world, run, "--shared-sample", "0", capsys=capsys)
    assert rep["new_items"] == [f"{RUN_ID}/sess-a/L2"]  # the matched lesson is not new
    assert rep["missed_a_marks"] == {"sess-a#L3": "unmarked"}
    cdir = run / "compare"
    sheet = (cdir / "spot-check.md").read_text(encoding="utf-8")
    # the excerpts are in the spot check ...
    assert sheet.count(CANARY) >= 2
    assert f"### {RUN_ID}/sess-a/L2" in sheet and "### sess-a#L3" in sheet
    assert f"### {RUN_ID}/sess-a/L1" not in sheet  # the matched lesson is not a new item (and no sample was asked for)
    # ... and nowhere a person might paste
    for name in ("report.json", "report.md", "spot-marks.template.json"):
        assert CANARY not in (cdir / name).read_text(encoding="utf-8"), name
    assert CANARY not in out and CANARY not in err
    # the one file with text is private, and so is the file a person writes marks into
    assert (cdir / "spot-check.md").stat().st_mode & 0o777 == 0o600
    assert (cdir / "spot-marks.template.json").stat().st_mode & 0o777 == 0o600


def test_h4_the_sheet_offers_lexical_neighbours_when_an_index_exists(world, capsys, monkeypatch):
    _a, run = _canary_world(world)
    rep, _, _ = report(world, run, "--shared-sample", "0", capsys=capsys)
    assert "no lesson index built" in (run / "compare" / "spot-check.md").read_text(encoding="utf-8")
    # build a lexical index of the scratch ledger, then ask again
    index = LessonIndex.open(world.home)
    index.build(provider=None)
    index.close()
    rep, _, _ = report(world, run, "--shared-sample", "0", capsys=capsys)
    sheet = (run / "compare" / "spot-check.md").read_text(encoding="utf-8")
    assert "no lesson index built" not in sheet
    block = sheet.split("- lexical neighbours (a hint for duplicates):", 1)[1].split("\n- ", 1)[0]
    assert "lrn-0000000" in block and "[routed]" in block


def test_h4_the_sheet_withholds_a_secret_the_ledger_text_carries(world, capsys):
    fake = "ghp_" + "A1b2C3d4" * 5  # built at run time; a GitHub-token shape
    world.session("sess-a", conversation(6), moments=[3])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)], trigger=f"Old trigger {fake}")
    run = world.run([("called", world.out("sess-a"))])
    report(world, run, capsys=capsys)
    sheet = (run / "compare" / "spot-check.md").read_text(encoding="utf-8")
    assert "[redacted:" in sheet and fake not in sheet
    assert "Old trigger" in sheet  # control: the sentence around it is there


def test_h4_a_secret_in_the_models_own_fields_is_redacted_on_the_sheet(world, capsys):
    fake = "ghp_" + "Z9y8X7w6" * 5  # built at run time; a GitHub-token shape
    world.session("sess-a", conversation(6), moments=[3])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    new = world.lesson("L1", [world.evidence("sess-a", 9, f"turn 5 text {fake}")],
                       trigger=f"About to paste {fake} into a prompt", instruction="Redact it first")
    run = world.run([("called", world.out("sess-a", lessons=[new]))])
    report(world, run, "--shared-sample", "0", capsys=capsys)
    sheet = (run / "compare" / "spot-check.md").read_text(encoding="utf-8")
    assert f"### {RUN_ID}/sess-a/L1" in sheet  # control: the new lesson is on the sheet
    assert "[redacted:" in sheet and fake not in sheet
    assert "About to paste" in sheet and "into a prompt" in sheet  # the words around it are kept


# ------------------------------------------------------------------- H5


def _marked_world(world):
    """Two new lessons, one missed bucket-A moment, and three shared candidates."""
    world.session("sess-a", conversation(16), moments=[3, 9, 15, 21])
    for line in (3, 9, 15, 21):
        world.record(f"lrn-{line:08x}", "session", "routed", [("sess-a", line)])
    lessons = [world.lesson("L1", [world.evidence("sess-a", 9)]),
               world.lesson("L2", [world.evidence("sess-a", 15)]),
               world.lesson("L3", [world.evidence("sess-a", 21)]),
               world.lesson("L4", [world.evidence("sess-a", 27)]),   # new
               world.lesson("L5", [world.evidence("sess-a", 31)])]   # new
    return world.run([("called", world.out("sess-a", lessons=lessons))])


def test_h5_marks_change_the_counts_and_a_missing_mark_is_unmarked(world, capsys):
    run = _marked_world(world)
    rep, _, _ = report(world, run, "--shared-sample", "2", capsys=capsys)
    new = rep["new_items"]
    assert new == [f"{RUN_ID}/sess-a/L4", f"{RUN_ID}/sess-a/L5"]
    assert rep["missed_a_marks"] == {"sess-a#L3": "unmarked"}
    assert rep["items"]["marks"] == {"real": 0, "junk": 0, "duplicate": 0, "not-a-lesson": 0, "unmarked": 2}
    shared = list(rep["shared_sample"])
    assert len(shared) == 2
    marks = {
        new[0]: {"mark": "real", "note": "a good one"},
        new[1]: {"mark": "", "note": "not decided"},           # an empty mark stays unmarked
        "sess-a#L3": {"mark": "not-a-lesson", "note": ""},
        shared[0]: {"mark": "new-better", "note": ""},
    }
    mfile = world.tmp / "marks.json"
    mfile.write_text(json.dumps(marks), encoding="utf-8")
    rep2, _, _ = report(world, run, "--shared-sample", "2", "--marks", str(mfile), capsys=capsys)
    assert rep2["items"]["marks"] == {"real": 1, "junk": 0, "duplicate": 0, "not-a-lesson": 0, "unmarked": 1}
    assert rep2["missed_a_marks"] == {"sess-a#L3": "not-a-lesson"}
    assert rep2["shared_sample_marks"] == {"same": 0, "new-better": 1, "old-better": 0, "both-off": 0, "unmarked": 1}
    assert rep2["shared_sample"][shared[0]] == "new-better" and rep2["shared_sample"][shared[1]] == "unmarked"


def test_h5_a_bad_marks_file_is_refused_naming_the_key_not_the_value(world, capsys):
    run = _marked_world(world)
    rep, _, _ = report(world, run, capsys=capsys)
    key = rep["new_items"][0]
    for body, needle in (
        ({key: {"mark": "ZQXjunky"}}, f"marks[{key}].mark"),                 # not an allowed mark
        ({"nobody#L1": {"mark": "real"}}, "marks[nobody#L1]"),               # not a key of this run
        ({key: {"mark": "same"}}, f"marks[{key}].mark"),                      # a shared-sample mark on an item
        ({key: "real"}, f"marks[{key}].mark"),                                # the wrong shape
    ):
        mfile = world.tmp / "bad-marks.json"
        mfile.write_text(json.dumps(body), encoding="utf-8")
        _, _, err = report(world, run, "--marks", str(mfile), expect=2, capsys=capsys)
        assert needle in err and "ZQX" not in err, (body, err)


def test_h5_the_template_lists_every_key_and_never_loses_a_filled_in_mark(world, capsys):
    run = _marked_world(world)
    rep, _, _ = report(world, run, "--shared-sample", "2", capsys=capsys)
    tpl_path = run / "compare" / "spot-marks.template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    assert set(tpl) == set(rep["new_items"]) | set(rep["missed_a_marks"]) | set(rep["shared_sample"])
    assert all(v == {"mark": "", "note": ""} for v in tpl.values())
    # the person fills the template in place and asks for the report again from the same file
    tpl[rep["new_items"][0]] = {"mark": "junk", "note": "dup of an old one"}
    tpl_path.write_text(json.dumps(tpl), encoding="utf-8")
    rep2, _, _ = report(world, run, "--shared-sample", "2", "--marks", str(tpl_path), capsys=capsys)
    assert rep2["items"]["marks"]["junk"] == 1
    kept = json.loads(tpl_path.read_text(encoding="utf-8"))
    assert kept[rep["new_items"][0]] == {"mark": "junk", "note": "dup of an old one"}


def test_h5_a_mark_without_a_note_survives_a_rerun(world, capsys):
    run = _marked_world(world)
    rep, _, _ = report(world, run, "--shared-sample", "0", capsys=capsys)
    key = rep["new_items"][0]
    tpl_path = run / "compare" / "spot-marks.template.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    tpl[key] = {"mark": "junk"}  # no "note"
    tpl_path.write_text(json.dumps(tpl), encoding="utf-8")
    for _ in range(3):  # each rerun reads the marks, then rewrites the template
        again, _, _ = report(world, run, "--shared-sample", "0", "--marks", str(tpl_path), capsys=capsys)
        assert again["items"]["marks"]["junk"] == 1 and again["items"]["marks"]["unmarked"] == 1
    kept = json.loads(tpl_path.read_text(encoding="utf-8"))
    assert kept[key] == {"mark": "junk", "note": ""}  # the mark is kept; the missing note reads as empty


# ------------------------------------------------------------------- H6


def _write_transcripts(world, root):
    for sid, entries in world.files.items():
        path = root / PROJECT / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def _journal_row(ts, outcomes, duration=600):
    return {"ts": ts, "run_id": "j1", "status": "ok", "duration_secs": duration,
            "outcomes": [{"origin": o, "outcome": k} for o, k in outcomes]}


def _telemetry(world, events):
    tdir = world.home / "telemetry"
    tdir.mkdir(exist_ok=True)
    (tdir / "2026-09.test.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def test_h6_a_night_old_finds_by_outcome_fires_by_window_and_program_sessions(world, env, capsys):
    world.session("sess-a", conversation(14))
    world.session("sess-prog", [sdk("a program prompt"), asst()])
    world.write_set()
    troots = env / "transcripts"
    _write_transcripts(world, troots)
    rows = [
        _journal_row("2026-09-29T03:30:00Z", [("transcript:sess-a#L1", "landed")]),  # an earlier night: ignored
        _journal_row("2026-09-30T03:30:00Z", [
            ("transcript:sess-a#L3", "landed"),
            ("transcript:sess-a#L7", "folded"),
            ("transcript:sess-a#L9", "recurrence"),
            ("transcript:sess-a#L11", "recurrence-from-fire"),
            ("transcript:sess-a#L13", "dropped-cap"),
            ("transcript:sess-a#L15", "dropped-rejected"),
            ("transcript:sess-a#L17", "skipped-known-origin"),
            ("(invalid-ref)", "dropped-invalid"),
            ("transcript:sess-prog#L1", "landed"),
        ]),
        _journal_row("2026-10-07T03:30:00Z", [("transcript:sess-a#L19", "landed")]),  # after the run: ignored
    ]
    journal = env / "journal.jsonl"
    journal.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n", encoding="utf-8")
    world.record("lrn-00000003", "session", "routed", [("sess-a", 3)])
    # fires: one inside the night's window (03:30 + 600 s + 300 s slack), one after it, one before
    _telemetry(world, [
        {"kind": "fire", "record": "lrn-00000003", "origin": "transcript:sess-a#L5", "outcome": "suspected-violation", "ts": "2026-09-30T03:35:00Z"},
        {"kind": "fire", "record": "lrn-00000003", "origin": "transcript:sess-a#L5", "outcome": "cannot-tell", "ts": "2026-09-30T05:00:00Z"},
        {"kind": "fire", "record": "lrn-00000003", "origin": "transcript:sess-a#L5", "outcome": "cannot-tell", "ts": "2026-09-29T03:35:00Z"},
    ])
    # the old miner's cost: one log whose run id falls in the window, one that does not
    from self_learn.serve import cache_dir_readonly
    cache = cache_dir_readonly(world.home)
    cache.mkdir(parents=True)
    (cache / "miner-reader.tool-events.20260930T033800Z-11.jsonl").write_text(json.dumps({"type": "meta", "cost_usd": 0.91}) + "\n", encoding="utf-8")
    (cache / "miner-reader.tool-events.20260930T060000Z-12.jsonl").write_text(json.dumps({"type": "meta", "cost_usd": 5.0}) + "\n", encoding="utf-8")

    ev = world.evidence("sess-a", 3)
    run = world.run([
        ("called", world.out("sess-a", mode="night", lessons=[world.lesson("L1", [ev])],
                             rule_checks=[world.rule_check("lrn-00000003", "suspected-violation", "sess-a", 5)])),
        ("skipped", "sess-prog", "no-typed-turns"),
    ], mode="night", started_at="2026-09-30T04:00:00Z")
    rep, out, _ = report(world, run, "--journal", str(journal), "--transcript-root", str(troots), capsys=capsys, testset=False)
    old = rep["old_finds"]
    assert rep["moments"] is None and rep["mode"] == "night"
    # five found outcomes in sess-a plus the program session's origin
    assert old["total"] == 6 and old["found_strict"] == 1 and old["found_loose"] == 1
    # every outcome entry of the night's row, by kind (the earlier and later nights' rows are not counted)
    assert old["by_outcome"] == {"dropped-cap": 1, "dropped-invalid": 1, "dropped-rejected": 1, "folded": 1,
                                 "landed": 2, "recurrence": 1, "recurrence-from-fire": 1, "skipped-known-origin": 1}
    assert old["journal_rows"] == ["2026-09-30T03:30:00Z"]  # the one row this night was compared with
    assert old["rejected_match"] == 1 and old["rejected_match_keys"] == ["sess-a#L15"]
    assert old["out_of_scope"] == 1 and rep["skipped_moments"] == {"sess-prog#L1": "out-of-scope"}
    assert old["missed"] == 4  # folded, recurrence, recurrence-from-fire, dropped-cap in the judged session
    # fires: only the one inside the window
    assert rep["rule_checks"]["old_fires"] == 1 and rep["rule_checks"]["matched"] == 1
    assert rep["rule_checks"]["outcome_same"] == 1 and rep["rule_checks"]["new"] == 0
    assert rep["cost"]["old_usd"] == 0.91 and rep["cost"]["shadow_usd"] == 0.25


def _night_run(world, env, rows):
    world.session("sess-a", conversation(8))
    world.write_set()
    troots = env / "transcripts"
    _write_transcripts(world, troots)
    journal = env / "journal.jsonl"
    journal.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    run = world.run([("called", world.out("sess-a", mode="night"))], mode="night", started_at="2026-09-30T04:00:00Z")
    return run, ["--journal", str(journal), "--transcript-root", str(troots)]


def test_h6_the_report_names_the_journal_rows_it_used(world, env, capsys):
    rows = [
        _journal_row("2026-09-28T03:30:00Z", [("transcript:sess-a#L1", "landed")]),
        _journal_row("2026-09-29T03:30:00Z", [("transcript:sess-a#L3", "landed")]),
        {"ts": "2026-09-30T03:30:00Z", "run_id": "j3", "status": "failed"},  # a failed night: no outcomes, no row for us
        _journal_row("2026-09-30T03:40:00Z", [("transcript:sess-a#L5", "landed")]),
    ]
    run, flags = _night_run(world, env, rows)
    one, _, _ = report(world, run, *flags, capsys=capsys, testset=False)
    assert one["old_finds"]["journal_rows"] == ["2026-09-30T03:40:00Z"] and one["old_finds"]["total"] == 1
    two, _, _ = report(world, run, *flags, "--nights", "2", capsys=capsys, testset=False)
    assert two["old_finds"]["journal_rows"] == ["2026-09-29T03:30:00Z", "2026-09-30T03:40:00Z"]
    assert two["old_finds"]["total"] == 2


def test_h6_an_origin_found_and_rejected_the_same_night_is_a_find(world, env, capsys):
    rows = [_journal_row("2026-09-30T03:30:00Z", [
        ("transcript:sess-a#L3", "dropped-rejected"),  # rejected first, found later in the same row
        ("transcript:sess-a#L3", "landed"),
        ("transcript:sess-a#L5", "dropped-rejected"),  # control: only rejected
    ])]
    run, flags = _night_run(world, env, rows)
    rep, _, _ = report(world, run, *flags, capsys=capsys, testset=False)
    old = rep["old_finds"]
    assert old["total"] == 1 and old["rejected_match"] == 1 and old["rejected_match_keys"] == ["sess-a#L5"]


def test_h6_a_night_with_no_journal_row_is_refused(world, env, capsys):
    world.session("sess-a", conversation(4))
    journal = env / "journal.jsonl"
    journal.write_text(json.dumps(_journal_row("2026-10-08T03:30:00Z", [("transcript:sess-a#L1", "landed")])) + "\n", encoding="utf-8")
    run = world.run([("called", world.out("sess-a", mode="night"))], mode="night", started_at="2026-09-30T04:00:00Z")
    _, _, err = report(world, run, "--journal", str(journal), expect=2, capsys=capsys, testset=False)
    assert "journal" in err


# ------------------------------------------------------------------- H7


def test_h7_the_inventory_counts_and_prints_no_text(world, env, capsys):
    entries = conversation(3)
    entries[2] = typed(f"{CANARY} in a typed turn")
    world.session("sess-a", entries + [result("tool output"), relay("a relay")], moments=[1, 2, 7, 8], subagents=2)
    world.session("sess-old", [old_user("old one"), asst(), old_user("old two"), asst()], moments=[1])
    world.session("sess-prog", [sdk("a program prompt"), asst()], moments=[2])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 1)])
    world.record("lrn-00000002", "session", "rejected", [("sess-a", 2)])
    world.record("lrn-00000003", "teach", "pending", [("sess-a", 7)])
    world.record("lrn-00000004", "session", "routed", [("sess-old", 1)])
    world.write_set()
    out_dir = env / "inv-out"
    rc = compare.main(["inventory", "--testset", str(world.set_dir), "--home", str(world.home), "--out", str(out_dir)])
    cap = capsys.readouterr()
    assert rc == 0
    inv = json.loads((out_dir / "inventory.json").read_text(encoding="utf-8"))
    assert inv["sessions"] == {"total": 3, "with_marker": 2, "without_marker": 1, "without_typed_turns": 1, "with_subagent_logs": 1}
    assert inv["without_marker_ids"] == ["sess-old"] and inv["without_typed_turns_ids"] == ["sess-prog"]
    assert inv["with_subagent_logs_ids"] == ["sess-a"]
    # typed turns per session: sess-a 3, sess-old 2 (the structural rule), sess-prog 0
    assert inv["typed_turns"] == {"median": 2.0, "max": 3}
    m = inv["moments"]
    assert m["total"] == 6 and m["by_bucket"] == {"A": 2, "B": 1, "C": 1, "other": 2}
    assert m["in_sessions_without_marker"] == {"A": 1}
    # lines: sess-a 1 (typed), 2 (assistant), 7 (tool result), 8 (relay); sess-old 1 (older typed); sess-prog 2 (assistant)
    assert m["roles"] == {"user": 2, "assistant": 2, "tool_result": 1, "relay": 1}
    # counts and ids only
    for text in (cap.out, cap.err, (out_dir / "inventory.json").read_text(encoding="utf-8")):
        assert CANARY not in text
        assert not any(t in text for t in ("old one", "old two", "tool output", "a relay", "a program prompt", "turn 1 text"))
    assert "without 1" in cap.out and "sess-old" in cap.out  # control: the output does carry the counts and the id


def test_h7_the_inventory_needs_an_out_directory_and_writes_nothing_to_the_working_directory(world, env, capsys, monkeypatch):
    world.session("sess-a", conversation(3), moments=[1])
    world.write_set()
    cwd = env / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    with pytest.raises(SystemExit) as exc:
        compare.main(["inventory", "--testset", str(world.set_dir), "--home", str(world.home)])
    assert exc.value.code == 2
    assert "--out" in capsys.readouterr().err
    assert list(cwd.iterdir()) == []
    # control: with the flag the file lands where it was told, and still not in the working directory
    assert compare.main(["inventory", "--testset", str(world.set_dir), "--home", str(world.home), "--out", str(env / "inv")]) == 0
    assert (env / "inv" / "inventory.json").exists() and list(cwd.iterdir()) == []


def test_h7_report_writes_only_under_the_run_folder(world, env, capsys, monkeypatch):
    world.session("sess-a", conversation(6), moments=[3])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 3)])
    run = world.run([("called", world.out("sess-a"))])
    cwd = env / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    report(world, run, capsys=capsys)
    assert sorted(p.name for p in (run / "compare").iterdir()) == [
        "report.json", "report.md", "spot-check.md", "spot-marks.template.json"]
    assert list(cwd.iterdir()) == []


def test_h7_the_module_runs_with_dash_m(world, env):
    world.session("sess-a", conversation(3), moments=[1])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 1)])
    world.write_set()
    proc = subprocess.run(
        [sys.executable, "-m", "self_learn.mining.compare", "inventory", "--testset", str(world.set_dir),
         "--home", str(world.home), "--out", str(env / "inv")],
        capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), cwd=str(env),
    )
    assert proc.returncode == 0, proc.stderr
    assert "sessions 1: with marker 1" in proc.stdout and (env / "inv" / "inventory.json").exists()
    bad = subprocess.run([sys.executable, "-m", "self_learn.mining.compare", "report"], capture_output=True, text=True,
                         env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), cwd=str(env))
    assert bad.returncode == 2


# ------------------------------------------------------------------- H9


def _shared_world(world, *, canary=False):
    """Four lessons that strictly hit four moments; three moments are cited by mined records and one only by a
    teach record (not shareable)."""
    entries = conversation(24)
    if canary:
        entries[2] = typed(f"{CANARY} at the first shared moment")
    world.session("sess-a", entries, moments=[3, 9, 15, 21, 27, 33])
    for line in (3, 9, 15, 21, 27):
        world.record(f"lrn-{line:08x}", "session", "routed" if line != 27 else "rejected", [("sess-a", line)])
    world.record("lrn-00000021", "teach", "pending", [("sess-a", 33)])
    lessons = [world.lesson(f"L{i}", [world.evidence("sess-a", line)]) for i, line in enumerate((3, 9, 15, 21, 27, 33), 1)]
    return world.run([("called", world.out("sess-a", lessons=lessons))])


def test_h9_the_sample_is_deterministic_and_seeded_by_the_run_id(world, capsys):
    run = _shared_world(world)
    rep1, _, _ = report(world, run, "--shared-sample", "3", capsys=capsys)
    rep2, _, _ = report(world, run, "--shared-sample", "3", capsys=capsys)
    assert list(rep1["shared_sample"]) == list(rep2["shared_sample"]) and len(rep1["shared_sample"]) == 3
    # candidates: the five lessons that hit a moment a mined record cites (the teach-only moment's lesson is not one)
    cands = [f"{RUN_ID}/sess-a/L{i}" for i in (1, 2, 3, 4, 5)]
    assert set(rep1["shared_sample"]) <= set(cands)
    assert f"{RUN_ID}/sess-a/L6" not in rep1["shared_sample"]
    assert list(rep1["shared_sample"]) == compare.sample_shared(RUN_ID, cands, 3)
    # independent of the order candidates arrive in, and of the sample size's neighbours
    assert compare.sample_shared(RUN_ID, list(reversed(cands)), 3) == compare.sample_shared(RUN_ID, cands, 3)
    assert compare.sample_shared(RUN_ID, cands, 0) == [] and len(compare.sample_shared(RUN_ID, cands, 99)) == 5
    # seeded by the run id: other ids pick other samples
    assert len({tuple(compare.sample_shared(f"run-{i}", cands, 2)) for i in range(25)}) > 1
    # the default size is 8, so all five are sampled
    rep_default, _, _ = report(world, run, capsys=capsys)
    assert compare.DEFAULT_SHARED_SAMPLE == 8 and len(rep_default["shared_sample"]) == 5
    rep_none, _, _ = report(world, run, "--shared-sample", "0", capsys=capsys)
    assert rep_none["shared_sample"] == {} and rep_none["shared_sample_marks"]["unmarked"] == 0


def test_h9_the_marks_are_counted_and_unmarked_stays_unmarked(world, capsys):
    run = _shared_world(world)
    rep, _, _ = report(world, run, "--shared-sample", "4", capsys=capsys)
    keys = list(rep["shared_sample"])
    assert rep["shared_sample_marks"] == {"same": 0, "new-better": 0, "old-better": 0, "both-off": 0, "unmarked": 4}
    mfile = world.tmp / "m.json"
    mfile.write_text(json.dumps({keys[0]: {"mark": "same"}, keys[1]: {"mark": "old-better"}, keys[2]: {"mark": "both-off"}}), encoding="utf-8")
    rep2, _, _ = report(world, run, "--shared-sample", "4", "--marks", str(mfile), capsys=capsys)
    assert rep2["shared_sample_marks"] == {"same": 1, "new-better": 0, "old-better": 1, "both-off": 1, "unmarked": 1}
    assert [rep2["shared_sample"][k] for k in keys] == ["same", "old-better", "both-off", "unmarked"]
    # an item mark on a shared key is refused
    mfile.write_text(json.dumps({keys[0]: {"mark": "real"}}), encoding="utf-8")
    report(world, run, "--shared-sample", "4", "--marks", str(mfile), expect=2, capsys=capsys)


def test_h9_each_shared_item_sits_beside_the_old_record_and_keeps_the_canary_private(world, capsys):
    run = _shared_world(world, canary=True)
    rep, out, err = report(world, run, "--shared-sample", "5", capsys=capsys)
    cdir = run / "compare"
    sheet = (cdir / "spot-check.md").read_text(encoding="utf-8")
    assert "## Shared sample" in sheet
    # the lesson that hit the first moment (line 3) is shown with the old record citing it and the transcript around it
    key = f"{RUN_ID}/sess-a/L1"
    assert key in rep["shared_sample"]
    block = sheet.split(f"### {key}", 1)[1].split("\n### ", 1)[0]
    assert "NEW LESSON" in block and "lrn-00000003" in block and "Old trigger text" in block
    assert CANARY in block  # the excerpt
    # a lesson whose moment only a teach record cites is not in the shared sample
    assert f"### {RUN_ID}/sess-a/L6" not in sheet
    # the same privacy rule as the new-item excerpts
    for name in ("report.json", "report.md", "spot-marks.template.json"):
        assert CANARY not in (cdir / name).read_text(encoding="utf-8"), name
    assert CANARY not in out and CANARY not in err
    assert (cdir / "spot-check.md").stat().st_mode & 0o777 == 0o600
    # the record text is in the sheet too (control for the privacy check above)
    assert sheet.count("Old trigger text") >= 5


def test_h9_a_loose_hit_is_shown_with_its_basis(world, capsys):
    world.session("sess-a", conversation(8), moments=[7])
    world.record("lrn-00000001", "session", "routed", [("sess-a", 7)])
    run = world.run([("called", world.out("sess-a", lessons=[world.lesson("L1", [world.evidence("sess-a", 9)])]))])
    rep, _, _ = report(world, run, capsys=capsys)
    assert list(rep["shared_sample"]) == [f"{RUN_ID}/sess-a/L1"]
    assert "loose" in (run / "compare" / "spot-check.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ H10


def test_h10_rule_checks_against_the_old_fires(world, capsys):
    world.session("sess-a", conversation(14), moments=[1])
    world.session("sess-fail", conversation(4))
    world.session("sess-z", conversation(4))  # not in the set's manifest: its fire is not counted
    world.write_set()
    _telemetry(world, [
        {"kind": "fire", "record": "lrn-00000001", "origin": "transcript:sess-a#L5", "outcome": "suspected-violation", "ts": "2026-09-30T03:35:00Z"},
        {"kind": "fire", "record": "lrn-00000002", "origin": "transcript:sess-a#L9", "outcome": "suspected-compliance", "ts": "2026-09-30T03:35:00Z"},
        {"kind": "fire", "record": "lrn-00000003", "origin": "transcript:sess-a#L13", "outcome": "cannot-tell", "ts": "2026-09-30T03:35:00Z"},
        {"kind": "fire", "record": "lrn-00000004", "origin": "transcript:sess-fail#L1", "outcome": "cannot-tell", "ts": "2026-09-30T03:35:00Z"},
        {"kind": "fire", "record": "lrn-00000005", "origin": "transcript:elsewhere#L1", "outcome": "cannot-tell", "ts": "2026-09-30T03:35:00Z"},
    ])
    checks = [
        world.rule_check("lrn-00000001", "suspected-violation", "sess-a", 5),   # same record, same line, same outcome
        world.rule_check("lrn-00000002", "cannot-tell", "sess-a", 9),           # matched, outcome differs
        world.rule_check("lrn-00000002", "cannot-tell", "sess-a", 25),          # same record, far away: new
        world.rule_check("lrn-00000006", "cannot-tell", "sess-a", 5),           # no fire for that record: new
    ]
    world.record("lrn-00000001", "session", "routed", [("sess-a", 1)])
    run = world.run([("called", world.out("sess-a", rule_checks=checks)),
                     ("called", world.out("sess-fail", status="failed"))])
    rep, _, _ = report(world, run, capsys=capsys)
    rc = rep["rule_checks"]
    assert rc["old_fires"] == 4  # the fire in a session outside the set is ignored
    assert (rc["matched"], rc["missed"], rc["not_judged"], rc["new"]) == (2, 1, 1, 2)
    assert (rc["outcome_same"], rc["outcome_different"]) == (1, 1)
    assert rc["matched_strict"] == 2 and rc["new_strict"] == 2
    assert rep["items"]["rule_checks"] == 4 and rep["items"]["new"] == 2
    assert f"{RUN_ID}/sess-a/rule_checks[2]" in rep["new_items"] and f"{RUN_ID}/sess-a/rule_checks[3]" in rep["new_items"]
    assert "### " + f"{RUN_ID}/sess-a/rule_checks[3]" in (run / "compare" / "spot-check.md").read_text(encoding="utf-8")


# ----------------------------------------------- accuracy, cost, sessions


def test_accuracy_and_cost_are_counted_from_the_outputs_and_the_run(world, capsys):
    world.session("sess-a", conversation(8))
    world.session("sess-b", conversation(4))
    world.session("sess-c", conversation(4))
    lesson = world.lesson("L1", [world.evidence("sess-a", 3, verdict="nearby", corrected_from=1), world.evidence("sess-a", 5)])
    lesson["verification"] = dict(world.evidence("sess-a", 7, verdict="normalised"), how="reran it")
    sighting = world.sighting("lrn-00000001", [world.evidence("sess-a", 9, verdict="elsewhere_in_file", corrected_from=2)])
    drops = [{"item": "L2", "reason": "no-evidence", "detail": ""},
             {"item": "L3.evidence[0]", "reason": "quote-not-found", "detail": ""},
             {"item": "L4.evidence[0]", "reason": "quote-not-found", "detail": "1 other session searched"}]
    run = world.run(
        [("called", world.out("sess-a", lessons=[lesson], sightings=[sighting], drops=drops)),
         ("called", world.out("sess-b")),
         ("called", world.out("sess-c", status="bad-output", drops=[{"item": "output", "reason": "bad-output", "detail": ""}]))],
        cost={"sess-a": 0.5, "sess-b": 0.2, "sess-c": 0.1},
    )
    rep, _, _ = report(world, run, capsys=capsys)
    assert rep["accuracy"] == {"drops": {"bad-output": 1, "no-evidence": 1, "quote-not-found": 2},
                               "verdicts": {"elsewhere_in_file": 1, "exact": 1, "nearby": 1, "normalised": 1}, "corrected": 2}
    assert rep["cost"] == {"shadow_usd": 0.8, "per_called_session_usd": {"median": 0.2, "max": 0.5}, "old_usd": None}
    assert rep["sessions"]["called"] == 3 and rep["sessions"]["bad_output"] == 1 and rep["sessions"]["ok"] == 2
    assert (rep["items"]["lessons"], rep["items"]["sightings"], rep["items"]["rule_checks"]) == (1, 1, 0)


# ------------------------------------------------- bad inputs and contracts


def test_a_run_that_fails_its_contract_is_refused_naming_the_path(world, capsys):
    world.session("sess-a", conversation(6), moments=[3])
    out = world.out("sess-a")
    run = world.run([("called", out)])
    bad = json.loads((run / "out" / "sess-a.json").read_text(encoding="utf-8"))
    bad["lessons"] = [dict(world.lesson("L1", [world.evidence("sess-a", 3)]), shape="ZQXgossip")]
    (run / "out" / "sess-a.json").write_text(json.dumps(bad), encoding="utf-8")
    _, _, err = report(world, run, expect=2, capsys=capsys)
    assert err.startswith("error: out/sess-a.json: lessons[0].shape:") and "ZQX" not in err


def test_a_secret_shaped_key_in_a_run_folder_is_not_named_on_stderr(world, capsys):
    secret = "ghp_" + "Q7w8E9r0" * 4 + "Zx1Y"  # built at run time; a GitHub-token shape used as a key name
    assert redact(secret)[0] != secret  # control: the secret scan flags it
    world.session("sess-a", conversation(6), moments=[3])
    run = world.run([("called", world.out("sess-a"))])
    run_json = json.loads((run / "run.json").read_text(encoding="utf-8"))
    run_json[secret] = 1
    (run / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    _, out, err = report(world, run, expect=2, capsys=capsys)
    assert err.startswith("error: run.json: $: unknown key (name withheld)") and secret not in err and secret not in out
    # and in an out file
    run2 = world.run([("called", world.out("sess-a"))])
    bad = json.loads((run2 / "out" / "sess-a.json").read_text(encoding="utf-8"))
    bad["session"][secret] = 1
    (run2 / "out" / "sess-a.json").write_text(json.dumps(bad), encoding="utf-8")
    _, out2, err2 = report(world, run2, expect=2, capsys=capsys)
    assert "out/sess-a.json: session: unknown key" in err2 and secret not in err2 and secret not in out2
    # control: a plain key is still named
    bad2 = json.loads((run2 / "out" / "sess-a.json").read_text(encoding="utf-8"))
    del bad2["session"][secret]
    bad2["session"]["bogus"] = 1
    (run2 / "out" / "sess-a.json").write_text(json.dumps(bad2), encoding="utf-8")
    _, _, err3 = report(world, run2, expect=2, capsys=capsys)
    assert "out/sess-a.json: session.bogus: unknown key" in err3


def test_a_session_listed_twice_in_a_run_record_is_refused_in_either_order(world, capsys):
    world.session("sess-a", conversation(6), moments=[3])
    world.session("sess-b", conversation(4))
    for order in ("called-then-skipped", "skipped-then-called"):
        run = world.run([("called", world.out("sess-a")), ("skipped", "sess-b", "no-marker")])
        run_json = json.loads((run / "run.json").read_text(encoding="utf-8"))
        dup = dict(run_json["sessions"][1], session="sess-a")  # the skipped row, renamed to the called session
        run_json["sessions"] = [run_json["sessions"][0], dup] if order == "called-then-skipped" else [dup, run_json["sessions"][0]]
        (run / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
        _, _, err = report(world, run, expect=2, capsys=capsys)
        assert err.startswith("error: run.json: sessions[1].session: listed twice"), (order, err)


def test_a_manifest_that_differs_from_the_runs_is_refused(world, capsys):
    world.session("sess-a", conversation(6), moments=[3])
    run = world.run([("called", world.out("sess-a"))])
    manifest = world.set_dir / "MANIFEST.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _, _, err = report(world, run, expect=2, capsys=capsys)
    assert "differs from the manifest the run recorded" in err


def test_a_testset_run_with_no_recorded_set_needs_the_option(world, capsys):
    world.session("sess-a", conversation(4), moments=[3])
    run = world.run([("called", world.out("sess-a"))], testset=False)
    _, _, err = report(world, run, expect=2, capsys=capsys, testset=False)
    assert "--testset" in err
    rep, _, _ = report(world, run, capsys=capsys)  # control: with the option it reports
    assert rep["mode"] == "testset"


def test_a_missing_transcript_or_ledger_is_refused(world, env, capsys):
    world.session("sess-a", conversation(6), moments=[3])
    run = world.run([("called", world.out("sess-a"))])
    (world.set_dir / "sessions" / PROJECT / "sess-a.jsonl").unlink()
    _, _, err = report(world, run, expect=2, capsys=capsys)
    assert "sess-a" in err and "transcript file missing" in err
    rc = compare.main(["report", "--run", str(run), "--home", str(env / "nowhere"), "--testset", str(world.set_dir)])
    assert rc == 2 and "ledger home" in capsys.readouterr().err


def test_bad_arguments_exit_2(world, env):
    for argv in (["report"], ["report", "--run", str(env), "--shared-sample", "-1"], ["inventory"],
                 ["inventory", "--testset", str(env)], []):
        with pytest.raises(SystemExit) as exc:
            compare.main(argv)
        assert exc.value.code == 2
