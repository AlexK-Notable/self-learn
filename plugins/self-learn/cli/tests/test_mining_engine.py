"""The session engine inside ``miner.run`` (new-miner plan §1, §3; unit R2;
tests E1-E14).

No model is called: a test-local backend stands in for the seam's backend
(``invocation.registry.backend_for`` is patched, as ``install_fake`` does),
answers each call by the session id on its spine's header, and counts the
calls in flight. Transcripts are synthetic JSONL in ``tmp_path``; the ledger
is a sandbox (``support.make_home``); fake secrets are built at run time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from self_learn import cli, invocation, miner, provenance, settings, steward_inputs, telemetry
from self_learn.mining import check, contract, engine, flags as flags_mod, tools, uuids
from self_learn.mining.spine import SESSION_OPENINGS, SpineFlag
from self_learn.records import Record
from support import commit_all, git, make_home

PROJECT = "-work-host"


# ------------------------------------------------------------------ fixtures


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "claude-dir"))
    return h


@pytest.fixture()
def root(tmp_path, monkeypatch, home):
    r = tmp_path / "transcripts"
    (r / PROJECT).mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(r))
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPT_ROOTS", str(r))
    miner._save_cursors({  # pyright: ignore[reportPrivateUsage]
        "__initialized__": "test-fixture",
        miner._HEADERS_CHECKED_KEY: miner._headers_fingerprint(),  # pyright: ignore[reportPrivateUsage]
        miner._SCHEDULED_CHECKED_KEY: miner._scheduled_fingerprint(frozenset()),  # pyright: ignore[reportPrivateUsage]
    })
    return r


def host(tmp_path: Path) -> str:
    return str(tmp_path / "host-repo")


def _ts(sid: str, n: int) -> str:
    base = int(hashlib.sha256(sid.encode()).hexdigest()[:4], 16) % 50
    return f"2026-10-0{1 + base % 9}T10:{n // 60:02d}:{n % 60:02d}.000Z"


def typed(sid: str, n: int, text: str, cwd: str) -> dict:
    return {"type": "user", "uuid": f"{sid}-u-{n}", "timestamp": _ts(sid, n), "cwd": cwd, "sessionId": sid,
            "origin": {"kind": "human"}, "promptSource": "typed",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def asst(sid: str, n: int, text: str, cwd: str) -> dict:
    return {"type": "assistant", "uuid": f"{sid}-a-{n}", "timestamp": _ts(sid, n), "cwd": cwd, "sessionId": sid,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def session_rows(sid: str, cwd: str) -> list[dict]:
    return [
        typed(sid, 1, "set up the export script", cwd),                        # L1 T1
        asst(sid, 2, "Done. I ran make check and every check passes.", cwd),  # L2
        typed(sid, 3, "stop. you never ran make check, the log is empty", cwd),  # L3 T2
        asst(sid, 4, "You're right; running it now.", cwd),                  # L4
        asst(sid, 5, "The check failed on the export path.", cwd),           # L5
        typed(sid, 6, "always run the checks before you say they pass", cwd),  # L6 T3
        asst(sid, 7, "Understood.", cwd),                                    # L7
    ]


def write_session(root: Path, sid: str, rows: list[dict], project: str = PROJECT) -> Path:
    path = root / project / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def lesson(**over) -> dict:
    out = {
        "id": "L1", "shape": "correction", "scope": "user", "type": "behavior", "kind": "anti-pattern",
        "trigger": "About to tell the person the checks pass without having run them",
        "instruction": "Run make check and read its log first, because a claimed pass that was never run costs a review",
        "fact": None, "context": "The person caught a claimed pass the log did not show.",
        "evidence": [{"line": 3, "quote": "you never ran make check"}],
        "steps": [{"line": 2, "what": "the agent claims every check passes"},
                  {"line": 3, "what": "the person says the check never ran"}],
        "verification": {"line": 5, "quote": "The check failed", "how": "the agent ran it and it failed"},
        "incident_cost": {"line": 4, "text": "a review spent on a false pass"},
        "generality": "general-practice", "why_durable": "claiming unrun checks recurs across sessions",
        "subagent_cause": None,
    }
    out.update(over)
    return out


def output(lessons=(), sightings=(), rule_checks=()) -> str:
    return json.dumps({"contract": contract.MODEL_CONTRACT, "lessons": list(lessons),
                       "sightings": list(sightings), "rule_checks": list(rule_checks)})


def put_record(home: Path, rid: str, *, status: str = "pending", successor: str | None = None,
               trigger: str = "About to deploy on a Friday", quote: str = "an old observation") -> Path:
    record = Record.create(type="behavior", scope="user", source="teach", kind="anti-pattern",
                           trigger=trigger, instruction="Wait until Monday, because nobody is around",
                           record_id=rid, evidence=[{"quote": quote, "origin": f"transcript:old-{rid}#L1"}])
    record.set_status(status)
    if status in ("routed", "superseded"):
        record.set_routing({"routed_at": "2026-01-01T00:00:00Z", "by": "user", "destination": "CLAUDE.md"})
    if successor:
        record.set_superseded_by(successor)
    folder = home / "user" / ("pending" if status == "pending" else "resolved")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{rid}.md"
    record.write(path)
    commit_all(home, f"seed {rid}")
    return path


# ------------------------------------------------------------- the backend


@dataclass
class FakeOutcome:
    ok: bool
    stdout: str = ""
    detail: str = ""
    failure: str | None = None
    rc: int | None = 0
    cost_usd: float | None = None
    turns: int | None = 3
    session_id: str | None = None
    usage_first_response: dict | None = None
    usage_session: dict | None = None
    denials: tuple = ()
    failure_class: str | None = None
    transcript: dict | None = None


@dataclass
class Backend:
    """Answers each call by the session id on the spine's header line;
    ``answers[sid]`` is a list of FakeOutcome (one per attempt) or a str
    (the final message of a call that succeeds)."""

    answers: dict[str, Any] = field(default_factory=dict)
    default: str = ""
    delay: float = 0.0
    cost: float | None = None
    specs: list = field(default_factory=list)
    log: list = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0

    def __post_init__(self) -> None:
        self.lock = threading.Lock()
        self.attempts: dict[str, int] = {}

    def text_session(self, spec):
        sid = re.search(r"^SESSION (\S+)", spec.prompt, re.M).group(1)
        with self.lock:
            self.specs.append(spec)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.log.append(("start", sid, time.monotonic()))
            n = self.attempts.get(sid, 0)
            self.attempts[sid] = n + 1
        try:
            if self.delay:
                time.sleep(self.delay)
            answer = self.answers.get(sid, self.default or output())
            if isinstance(answer, list):
                return answer[min(n, len(answer) - 1)]
            return FakeOutcome(ok=True, stdout=answer, cost_usd=self.cost, session_id=f"claude-{sid}")
        finally:
            with self.lock:
                self.in_flight -= 1
                self.log.append(("end", sid, time.monotonic()))

    def write_session(self, spec):  # pragma: no cover - never reached
        raise AssertionError("the session engine calls text_session only")


@pytest.fixture()
def backend(monkeypatch):
    b = Backend()
    monkeypatch.setattr(invocation.registry, "backend_for", lambda *a, **k: b)
    return b


def run(home: Path, **kw) -> miner.MineResult:
    kw.setdefault("engine", "session")
    return miner.run(home, no_push=True, **kw)


def run_dir(result: miner.MineResult) -> Path:
    return miner.miner_dir() / "runs" / result.run_id


def journal_last() -> dict:
    return miner.read_journal(1)[-1]


def cursor(path: Path) -> dict | None:
    return miner._load_cursors().get(str(path))  # pyright: ignore[reportPrivateUsage]


def pending(home: Path) -> list[Record]:
    return [Record.from_path(p) for p in sorted((home).glob("*/pending/lrn-*.md"))
            + sorted(home.glob("*/*/pending/lrn-*.md"))]


# ===================================================================== E1


def test_e1_one_call_per_session_with_the_spec_of_section_3_4(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_PARALLEL", "1")
    sids = ["s1aaaaaa-0000", "s2bbbbbb-0000"]
    for sid in sids:
        write_session(root, sid, session_rows(sid, host(tmp_path)))
    result = run(home)
    assert result.status == "ok", result.engine
    assert len(backend.specs) == 2
    folder = run_dir(result)
    shared = folder / "shared-instructions.md"
    for k, spec in enumerate(backend.specs):
        sid = re.search(r"^SESSION (\S+)", spec.prompt, re.M).group(1)
        plan = json.loads((folder / "plans" / f"{sid}.json").read_text())
        assert spec.prompt == plan["spine"] and spec.prompt.startswith(SESSION_OPENINGS[0] + "\n" + SESSION_OPENINGS[1])
        assert spec.surface == "miner-session"
        names = spec.mcp_toolset.qualified_names
        assert names == ("mcp__miner__open_stretch", "mcp__miner__find_similar_lessons", "mcp__miner__search_subagent")
        assert spec.containment.allowed_tools == ",".join(names)
        assert spec.containment.disallowed_tools == miner.READER_DISALLOWED_TOOLS
        assert spec.append_system_prompt_file == shared and spec.exclude_dynamic_sections is True
        assert spec.extra_env == invocation.NO_AUTO_MEMORY_ENV
        assert spec.sidecar_key == f"{result.run_id}-{k}"
        assert spec.skip_orphan_sweep is (k != 0)
        assert spec.cwd == miner.miner_dir() / "session-stage" and spec.ledger_home == home
        assert spec.timeout == miner.reader_timeout_secs(home) and spec.transcript_group == result.run_id
        assert spec.max_turns is None
    assert len({s.sidecar_key for s in backend.specs}) == 2


def test_e1_the_shared_instructions_are_method_passage_and_schema_byte_identical(home, root, backend, tmp_path):
    for sid in ("s1aaaaaa-0000", "s2bbbbbb-0000"):
        write_session(root, sid, session_rows(sid, host(tmp_path)))
    run(home)
    texts = {Path(s.append_system_prompt_file).read_bytes() for s in backend.specs}
    assert len(texts) == 1
    text = texts.pop().decode()
    method = (Path(miner.worker.package_skill_refs()) / "miner-method.md").read_text()
    assert text.startswith(method.rstrip("\n"))
    from self_learn import lesson_writing

    assert lesson_writing.extract(text) == lesson_writing.text()
    tail = text.split(f"=== OUTPUT SCHEMA ({contract.MODEL_CONTRACT}) ===\n", 1)[1]
    assert json.loads(tail) == contract.model_output_json_schema()
    assert engine.shared_instructions() == (text, "1")


# ===================================================================== E2


def test_e2_at_most_parallel_calls_in_flight_and_the_warm_up_first(home, root, tmp_path, monkeypatch):
    b = Backend(delay=0.15)
    monkeypatch.setattr(invocation.registry, "backend_for", lambda *a, **k: b)
    monkeypatch.setenv("SELF_LEARN_MINER_PARALLEL", "4")
    for i in range(8):
        sid = f"s{i}cccccc-0000"
        write_session(root, sid, session_rows(sid, host(tmp_path)))
    result = run(home)
    assert result.status == "ok" and len(b.specs) == 8
    assert b.max_in_flight == 4
    starts = [t for kind, _sid, t in b.log if kind == "start"]
    first_end = next(t for kind, _sid, t in b.log if kind == "end")
    assert b.log[0][0] == "start" and b.log[1][0] == "end"  # the warm-up ran alone
    assert all(t >= first_end for t in starts[1:])


def test_e2_parallel_is_clamped_to_eight(home, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_PARALLEL", "50")
    monkeypatch.setenv("SELF_LEARN_MINER_SPINE_TOKENS", "10")
    cfg = engine.EngineSettings.resolve(home)
    assert cfg.parallel == 8 and cfg.spine_tokens == 2_000


# ===================================================================== E3


def test_e3_the_runaway_guard_stops_calls_and_keeps_their_cursors(home, root, tmp_path, monkeypatch):
    b = Backend(cost=3.0)
    monkeypatch.setattr(invocation.registry, "backend_for", lambda *a, **k: b)
    monkeypatch.setenv("SELF_LEARN_MINER_PARALLEL", "1")
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_RUN_USD", "5")
    paths = []
    for i in range(4):
        sid = f"s{i}dddddd-0000"
        paths.append(write_session(root, sid, session_rows(sid, host(tmp_path))))
    result = run(home)
    assert len(b.specs) == 2  # 0 + 0 < 5, then 3 + 0 < 5, then 6 >= 5
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert rec["status"] == "stopped-ceiling"
    rows = {r["session"]: r for r in rec["sessions"]}
    called = {r["session"] for r in rec["sessions"] if r["status"] == "called"}
    not_run = [r for r in rec["sessions"] if r["status"] == "not-run"]
    assert len(called) == 2 and len(not_run) == 2 and all(r["reason"] == "spend-ceiling" for r in not_run)
    for p in paths:
        if p.stem in called:
            assert cursor(p)["lines"] == 7  # control: the called ones advanced
        else:
            assert cursor(p) is None and rows[p.stem]["out_status"] is None
    assert contract.validate_run(rec) == []


def test_e3_an_unreported_cost_counts_as_a_heavy_call():
    assert engine.CallRecord("s", 0, attempts=2).counted_usd == pytest.approx(2 * engine.HEAVY_CALL_USD)
    assert engine.CallRecord("s", 0, attempts=1, cost_usd=0.01).counted_usd == 0.01


# ===================================================================== E4


@pytest.mark.parametrize(
    "detail,attempts",
    [("API Error: 529 overloaded", 2), ("Claude Code stopped: error_max_turns", 1), ("something odd", 1)],
)
def test_e4_a_transient_failure_is_retried_once_and_others_never(home, root, backend, tmp_path, detail, attempts):
    sid = "s1eeeeee-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = [FakeOutcome(ok=False, failure="exit", detail=detail, rc=1),
                            FakeOutcome(ok=True, stdout=output(), cost_usd=0.1)]
    result = run(home)
    assert backend.attempts[sid] == attempts
    calls = json.loads((run_dir(result) / "calls" / f"{sid}.json").read_text())
    assert calls["attempts"] == attempts
    if attempts == 2:
        assert backend.specs[1].skip_orphan_sweep is True  # the retry never sweeps
        assert calls["ok"] is True
    else:
        assert calls["ok"] is False and result.status == "failed"


# ===================================================================== E5


def test_e5_a_lesson_lands_as_a_pending_record_with_refs_and_steps(home, root, backend, tmp_path):
    sid = "s1ffffff-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    result = run(home)
    assert result.status == "ok" and len(result.landed) == 1
    (record,) = [r for r in pending(home) if r.id == result.landed[0]]
    assert record.source == "session" and record.type == "behavior" and record.kind == "anti-pattern"
    body = record.body
    assert "## Context\nThe person caught a claimed pass" in body
    brief = body.split("## Episode brief\n", 1)[1]
    assert brief.splitlines()[:2] == [
        "L2 (assistant, T1): the agent claims every check passes",
        "L3 (user, T2): the person says the check never ran",
    ]
    ev = record.evidence
    assert ev[0]["ref"]["line"] == 3 and ev[0]["ref"]["uuid"] == f"{sid}-u-3" and ev[0]["ref"]["role"] == "user"
    assert ev[0]["quote"] == "you never ran make check" and ev[0]["origin"] == f"transcript:{sid}#L3"
    assert ev[0]["ts"] == _ts(sid, 3) and ev[0]["session"] == sid
    assert [e.get("why") for e in ev] == [None, "verification", "incident-cost"]
    text = record.to_text()
    assert "verified: true" in text and "verified_how: the agent ran it and it failed" in text
    assert "incident_cost: a review spent on a false pass" in text and "generality: general-practice" in text
    # committed in the landing commit, and the steward's pack reads the ref first
    assert git(home, "status", "--porcelain").stdout.strip() == ""
    items, _stats = steward_inputs.evidence_pack(record, roots=[root], budget=4000)
    assert items[0].verdict == "exact"


def test_e5_a_withheld_quote_lands_without_a_quote(home, root, backend, tmp_path):
    sid = "s2ffffff-0000"
    token = "ghp_" + "Ab12" * 10
    rows = session_rows(sid, host(tmp_path))
    rows[2] = typed(sid, 3, f"stop. you never ran make check, the key {token} leaked", host(tmp_path))
    write_session(root, sid, rows)
    backend.answers[sid] = output([lesson(evidence=[{"line": 3, "quote": "the key [redacted:github-token] leaked"},
                                                    {"line": 3, "quote": "you never ran make check"}])])
    result = run(home)
    assert len(result.landed) == 1, result.outcomes
    (record,) = [r for r in pending(home) if r.id == result.landed[0]]
    first = record.evidence[0]
    assert "quote" not in first and first["ref"]["line"] == 3  # the pointer stays, the text does not
    items, _ = steward_inputs.evidence_pack(record, roots=[root], budget=4000)
    assert items[0].verdict == steward_inputs.NO_QUOTE


def _sighting(sid: str, rid: str, line: int = 3, quote: str = "you never ran make check") -> dict:
    return {"record": rid, "evidence": [{"line": line, "quote": quote}]}


def test_e5_a_sighting_of_a_pending_record_folds(home, root, backend, tmp_path):
    rid = "lrn-0000aaa1"
    path = put_record(home, rid)
    sid = "s3ffffff-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    result = run(home)
    assert result.folded == [rid]
    record = Record.from_path(path)
    assert record.sightings == 2
    assert record.evidence[-1]["ref"]["uuid"] == f"{sid}-u-3"
    assert git(home, "status", "--porcelain").stdout.strip() == ""  # the fold is committed


def test_e5_a_sighting_follows_superseded_by_to_the_live_record(home, root, backend, tmp_path):
    live = put_record(home, "lrn-0000aaa2")
    old = put_record(home, "lrn-0000aaa3", status="superseded", successor="lrn-0000aaa2")
    sid = "s4ffffff-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, "lrn-0000aaa3")])
    before = old.read_bytes()
    result = run(home)
    assert result.folded == ["lrn-0000aaa2"]
    assert Record.from_path(live).sightings == 2 and old.read_bytes() == before


def test_e5_a_sighting_of_a_routed_record_spools_a_recurrence_suspect(home, root, backend, tmp_path):
    rid = "lrn-0000aaa4"
    put_record(home, rid, status="routed")
    sid = "s5ffffff-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    result = run(home)
    assert result.recurrences == [rid]
    events = [e for e in telemetry.read_events(home) if e.get("kind") == "recurrence-suspect"]
    assert [(e["record"], e["origin"], e["basis"]) for e in events] == [(rid, f"transcript:{sid}#L3", "miner-match")]


def _flagged(monkeypatch, rid: str, turn: int = 2) -> None:
    def fake(index, stretches, *, cwd, entries=(), provider=None):
        return flags_mod.FlagResult((flags_mod.Flag(rid, turn, 4, 5, 0.9, None, 1.0, "rule"),), "lexical-only", "")
    monkeypatch.setattr(engine.flags_mod, "flag_rules", fake)


def test_e5_a_rule_check_spools_a_fire_the_steward_reads(home, root, backend, tmp_path, monkeypatch):
    rid = "lrn-0000aaa5"
    put_record(home, rid, status="routed")
    _flagged(monkeypatch, rid)
    sid = "s6ffffff-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(rule_checks=[{"record": rid, "outcome": "suspected-violation",
                                                "situation": {"line": 4}, "action": {"line": 5}}])
    result = run(home)
    assert result.fires == 1
    from self_learn.miner import _find_record  # pyright: ignore[reportPrivateUsage]

    found = steward_inputs.suspected_violations(home, lambda h, r: (_find_record(h, r) or (None,))[0])
    (event,) = found[rid]
    assert event["origin"] == f"transcript:{sid}#L4" and event["action"] == f"transcript:{sid}#L5"
    plan = json.loads((run_dir(result) / "plans" / f"{sid}.json").read_text())
    assert f"FLAG {rid} (user) matched this stretch [lexical]" in plan["spine"]


# ===================================================================== E6


def test_e6_cursors_advance_once_for_judged_sessions_and_not_for_failed(home, root, backend, tmp_path):
    good = write_session(root, "s1gggggg-0000", session_rows("s1gggggg-0000", host(tmp_path)))
    bad = write_session(root, "s2gggggg-0000", session_rows("s2gggggg-0000", host(tmp_path)))
    backend.answers["s2gggggg-0000"] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    run(home)
    assert cursor(good)["lines"] == 7 and cursor(bad) is None
    calls_before = len(backend.specs)
    run(home)  # the next run: only the failed session is judged again
    again = [re.search(r"^SESSION (\S+)", s.prompt, re.M).group(1) for s in backend.specs[calls_before:]]
    assert again == ["s2gggggg-0000"]


# ===================================================================== E7


def _tree_hashes(base: Path) -> dict[str, str]:
    return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file() and ".git" not in p.parts}


def test_e7_preview_leaves_the_ledger_cursors_and_uuid_store_byte_identical(home, root, backend, tmp_path):
    rid = "lrn-0000aaa6"
    put_record(home, rid)
    sid = "s1hhhhhh-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    store = uuids.JudgedUuids(miner.miner_dir() / uuids.STORE_NAME)
    from datetime import date

    store.add(["an-old-uuid"], date(2026, 1, 2))  # past 120 days: a night run would prune it
    backend.answers[sid] = output([lesson()], sightings=[_sighting(sid, rid)])
    ledger = _tree_hashes(home)
    head = git(home, "rev-parse", "HEAD").stdout
    cursors = (miner.miner_dir() / "cursors.json").read_bytes()
    store_bytes = store.path.read_bytes()
    journal = miner.journal_path().read_bytes() if miner.journal_path().exists() else b""
    result = run(home, preview=True)
    assert result.status == "preview"
    out = json.loads((run_dir(result) / "out" / f"{sid}.json").read_text())
    assert out["lessons"] and out["sightings"]  # positive control: the run produced output
    assert _tree_hashes(home) == ledger and git(home, "rev-parse", "HEAD").stdout == head
    assert git(home, "status", "--porcelain").stdout == ""
    assert (miner.miner_dir() / "cursors.json").read_bytes() == cursors
    assert store.path.read_bytes() == store_bytes
    assert (miner.journal_path().read_bytes() if miner.journal_path().exists() else b"") == journal
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert rec["preview"] is True and rec["totals"]["lessons"] == 1


def test_e7_preview_of_named_sessions_judges_their_whole_files(home, root, backend, tmp_path, capsys):
    sid = "s2hhhhhh-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    miner._advance_cursors([(miner.SessionSlice(path, sid, PROJECT, 0, ["x"] * 7, path.stat().st_size), False)])  # pyright: ignore[reportPrivateUsage]
    canary = "CANARY-" + "q" * 12
    rows = session_rows(sid, host(tmp_path))
    rows[5] = typed(sid, 6, f"always run the checks {canary}", host(tmp_path))
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rc = cli.main(["mine", "run", "--engine", "session", "--preview", "--session", sid, "--session", "nope-0000"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 to call" in out and "1 not found" in out and canary not in out
    folder = sorted((miner.miner_dir() / "runs").iterdir())[-1]
    plan = json.loads((folder / "plans" / f"{sid}.json").read_text())
    assert plan["judged"]["first_line"] == 1 and canary in plan["spine"]  # control: the text was there


# ===================================================================== E8

OLD_JOURNAL_KEYS = {
    "ts", "run_id", "trigger", "rubric_version", "model", "status", "landing_uncommitted", "sessions_scanned",
    "excluded", "deferred_files", "cap", "landed", "folded", "recurrences", "fires", "outcomes",
    "near_miss_count", "corrupt_records", "cursors_held", "duration_secs",
}


def test_e8_the_journal_row_keeps_every_old_key_and_adds_the_new(home, root, backend, tmp_path):
    sid = "s1iiiiii-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson(evidence=[{"line": 3, "quote": "words nobody wrote"}])])
    run(home)
    row = journal_last()
    assert OLD_JOURNAL_KEYS <= set(row)
    assert row["engine"] == "session" and row["sessions_called"] == 1 and row["method_version"] == "1"
    assert row["drops"] == {"quote-not-found": 1, "no-evidence": 1}
    assert {"origin": f"transcript:{sid}", "outcome": "dropped-check", "reason": "quote-not-found",
            "item": "L1.evidence[0]"} in row["outcomes"]
    assert row["model"] == miner.provider.model_for("miner-session", home=home)


# ===================================================================== E9


def test_e9_run_folders_past_thirty_are_pruned(home, root, backend, tmp_path):
    runs = miner.miner_dir() / "runs"
    for i in range(35):
        d = runs / f"old{i:02d}"
        d.mkdir(parents=True)
        (d / "run.json").write_text("{}")
        t = 1_700_000_000 + i
        os.utime(d, (t, t))
    sid = "s1jjjjjj-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    result = run(home)
    names = sorted(p.name for p in runs.iterdir())
    assert len(names) == 30 and result.run_id in names
    assert "old34" in names and "old06" in names and "old05" not in names  # the 29 newest old ones stay


def test_e9_transcript_copies_of_the_surface_are_pruned_too(tmp_path):
    base = tmp_path / "sessions"
    for i in range(33):
        (base / "miner-session" / f"g{i:02d}").mkdir(parents=True)
    (base / "steward" / "g00").mkdir(parents=True)
    assert engine.prune_session_copies(base, keep=30) == 3
    assert len(list((base / "miner-session").iterdir())) == 30 and (base / "steward" / "g00").is_dir()


# ===================================================================== E10


def test_e10_the_digest_engine_runs_the_old_path(home, root, tmp_path, monkeypatch):
    calls: list[str] = []

    def reader(_home, prompt):
        calls.append(prompt)
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": []}))
        return out

    monkeypatch.setattr(miner, "_invoke_reader", reader)
    monkeypatch.setattr(miner, "_session_call", lambda spec: pytest.fail("the session engine was called"))
    sid = "s1kkkkkk-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    result = miner.run(home, no_push=True)  # miner.engine's default
    assert settings.resolve_setting(home, settings.by_name("miner.engine"))[0] == "digest"
    assert result.status == "ok" and len(calls) == 1
    assert "engine" not in journal_last() and not (miner.miner_dir() / "runs").exists()


def test_e10_the_setting_switches_the_engine(home, root, backend, tmp_path):
    (home / "config.yaml").write_text("miner:\n  engine: session\n")
    commit_all(home, "config")
    sid = "s2kkkkkk-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    assert miner.run(home, no_push=True).status == "ok"
    assert len(backend.specs) == 1 and journal_last()["engine"] == "session"


# ===================================================================== E12


@pytest.mark.parametrize(
    "argv",
    [
        ["mine", "run", "--engine", "session"],
        ["mine", "run", "--session", "abcd-0001"],
        ["mine", "run", "--preview"],
        ["mine", "run", "--engine", "digest", "--preview"],
        ["mine", "run", "--engine", "session", "--preview", "--session", "../x"],
    ],
)
def test_e12_the_session_engine_lands_only_after_the_user_s_flip(home, root, argv, capsys, monkeypatch):
    monkeypatch.setattr(miner, "run", lambda *a, **k: pytest.fail("refused flags must never start a run"))
    assert cli.main(argv) == cli.EXIT_USAGE
    assert "self-learn mine:" in capsys.readouterr().err


def test_e12_preview_alone_is_allowed_once_the_setting_is_session(home, root, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(miner, "run", lambda h, **k: seen.update(k) or miner.MineResult(status="preview", run_id="r"))
    (home / "config.yaml").write_text("miner:\n  engine: session\n")
    assert cli.main(["mine", "run", "--preview"]) == 0
    assert seen["preview"] is True and seen["engine"] is None
    assert cli.main(["mine", "run", "--engine", "digest"]) == 0  # a one-run rollback is allowed


def test_e12_miner_engine_is_tier_c_without_an_env_var():
    s = settings.by_name("miner.engine")
    assert s.tier == "C" and s.env_var is None and s.default == "digest"
    assert s.accepts is not None and s.accepts("session") and not s.accepts("other")


# ===================================================================== E13


@pytest.mark.parametrize("failure", ["checker", "bad-output", "transport"])
def test_e13_one_session_s_failure_leaves_the_others_landed(home, root, backend, tmp_path, monkeypatch, failure):
    good = write_session(root, "s1llllll-0000", session_rows("s1llllll-0000", host(tmp_path)))
    bad = write_session(root, "s2llllll-0000", session_rows("s2llllll-0000", host(tmp_path)))
    backend.answers["s1llllll-0000"] = output([lesson()])
    if failure == "checker":
        real = check.check_output

        def flaky(text, spine, **kw):
            if spine.session.session_id == "s2llllll-0000":
                raise check.CheckerError("planted")
            return real(text, spine, **kw)

        monkeypatch.setattr(engine.check_mod, "check_output", flaky)
        backend.answers["s2llllll-0000"] = output([lesson()])
    elif failure == "bad-output":
        backend.answers["s2llllll-0000"] = "this is not JSON"
    else:
        backend.answers["s2llllll-0000"] = [FakeOutcome(ok=False, failure="exit", detail="connection reset", rc=1)] * 2
    result = run(home)
    assert result.status == "ok" and len(result.landed) == 1
    assert cursor(good)["lines"] == 7 and cursor(bad) is None
    rec = json.loads((run_dir(result) / "run.json").read_text())
    row = {r["session"]: r for r in rec["sessions"]}["s2llllll-0000"]
    assert row["out_status"] == ("bad-output" if failure == "bad-output" else "failed")
    assert row.get("error") == {"checker": "checker-error", "bad-output": None, "transport": "call"}[failure]
    contract.load_run(run_dir(result))  # the folder agrees with itself


# ===================================================================== E14


LABELS = ("YOU", "AGENT", "AGENT-WRITTEN", "RELAY", "SUBAGENT")


def test_e14_spine_tools_and_method_agree_on_every_label(home, root, tmp_path):
    sid = "s1mmmmmm-0000"
    cwd = host(tmp_path)
    rows = session_rows(sid, cwd)
    rows.insert(3, {"type": "user", "uuid": f"{sid}-r", "timestamp": _ts(sid, 3), "cwd": cwd, "sessionId": sid,
                    "origin": {"kind": "peer"}, "message": {"content": [{"type": "text", "text": "a peer says hi"}]}})
    rows.insert(4, typed(sid, 4, "<agent-message>a brief another agent typed</agent-message>", cwd))
    rows.insert(5, {"type": "assistant", "uuid": f"{sid}-t", "timestamp": _ts(sid, 4), "cwd": cwd,
                    "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Agent",
                                             "input": {"prompt": "look into it"}}]}})
    rows.insert(6, {"type": "user", "uuid": f"{sid}-tr", "timestamp": _ts(sid, 4), "cwd": cwd,
                    "toolUseResult": {"agentId": "abc123"},
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "found it"}]}})
    path = write_session(root, sid, rows)
    sub = root / PROJECT / sid / "subagents" / "agent-abc123.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text(json.dumps({"type": "user", "timestamp": _ts(sid, 4), "message": {"content": "look into it"}}) + "\n"
                   + json.dumps({"type": "assistant", "timestamp": _ts(sid, 4),
                                 "message": {"content": [{"type": "text", "text": "found it"}]}}) + "\n")
    plan = engine.plan_session(path, 0, len(rows), None, home=home, sent=provenance.SentIndex(),
                               judged_uuids=frozenset(), spine_tokens=20_000, index=None, records={})
    assert plan.spine is not None and plan.toolset is not None
    spine_text = plan.spine.text
    for shown in ("\nYOU: ", "\nAGENT (L", "\nAGENT-WRITTEN (L", "\nRELAY (L"):
        assert shown in spine_text, shown
    tool = {t.name: t for t in plan.toolset.tools}
    import asyncio

    stretch = asyncio.run(tool["open_stretch"].handler({"after_turn": 2})).text
    for shown in (" AGENT-WRITTEN: ", " AGENT: ", " RELAY: ", " SUBAGENT abc123"):
        assert shown in stretch, shown
    found = asyncio.run(tool["search_subagent"].handler({"subagent": "abc123", "query": "found"})).text
    assert "SUBAGENT abc123 / SUBAGENT" in found
    assert set(LABELS) <= set(tools.ROLE_LABELS.values())
    method = (Path(miner.worker.package_skill_refs()) / "miner-method.md").read_text()
    for label in LABELS:
        assert f"`{label}`" in method, label


# ======================================================== integration points


def test_flags_map_onto_spine_flags(home):
    put_record(home, "lrn-0000bbb1", status="routed")
    know = Record.create(type="knowledge", scope="user", source="teach", fact="The port is 8096",
                         context="Docker publishes it", record_id="lrn-0000bbb2")
    records = {"lrn-0000bbb1": (None, Record.from_path(home / "user" / "resolved" / "lrn-0000bbb1.md")),
               "lrn-0000bbb2": (None, know)}
    result = flags_mod.FlagResult(
        (flags_mod.Flag("lrn-0000bbb1", 2, 4, 5, 0.5, None, 1.0, "q"),
         flags_mod.Flag("lrn-0000bbb2", 3, 6, 7, 0.1, 0.8, 0.9, "q"),
         flags_mod.Flag("lrn-gone0000", 1, 1, 2, 0.5, None, 0.5, "q")),
        "hybrid", "",
    )
    got = engine.spine_flags(result, records)
    assert got == (
        SpineFlag("lrn-0000bbb1", "user", 2, "lexical",
                  "Trigger: About to deploy on a Friday — Instruction: Wait until Monday, because nobody is around"),
        SpineFlag("lrn-0000bbb2", "user", 3, "lexical+meaning", "Fact: The port is 8096 — Context: Docker publishes it"),
    )


def test_the_run_s_sends_reach_the_checker_and_nothing_sweeps_per_session(home, root, backend, tmp_path, monkeypatch):
    sid = "s1nnnnnn-0000"
    rows = session_rows(sid, host(tmp_path))
    write_session(root, sid, rows)
    backend.answers[sid] = output([lesson()])
    swept: list[int] = []
    real = provenance.sweep

    def counting(dirs):
        swept.append(1)
        return real(dirs)

    monkeypatch.setattr(provenance, "sweep", counting)
    result = run(home)
    assert len(result.landed) == 1
    assert len(swept) == 1  # once, by `_run_locked`; never by a ref's role


def test_the_checker_reads_rule_10_from_the_sends_it_is_given(home, root, tmp_path, monkeypatch):
    sid = "s2nnnnnn-0000"
    rows = session_rows(sid, host(tmp_path))
    path = write_session(root, sid, rows)
    text = "stop. you never ran make check, the log is empty"
    sends = provenance.SentIndex([provenance.Send(provenance._epoch(_ts(sid, 3)) - 2, "other-session",  # pyright: ignore[reportPrivateUsage]
                                                  text, provenance.fold(text))])
    monkeypatch.setattr(miner.refs, "sent_index", lambda roots=None: pytest.fail("swept per ref"))
    plan = engine.plan_session(path, 0, 7, None, home=home, sent=sends, judged_uuids=frozenset(),
                               spine_tokens=20_000, index=None, records={})
    res = check.check_output(output([lesson()]), plan.spine, run_id="r", model="m", method_version="1",
                             roots=[root], sent=sends)
    # the turn at L3 is another agent's (the sends say so): never the person's correction
    assert [d["reason"] for d in res.checked["drops"]] == ["no-user-evidence"]


def test_search_subagent_sees_only_the_spine_s_logs_up_to_the_judged_end(home, root, tmp_path):
    sid = "s1oooooo-0000"
    cwd = host(tmp_path)
    rows = session_rows(sid, cwd)
    path = write_session(root, sid, rows)
    subdir = root / PROJECT / sid / "subagents"
    subdir.mkdir(parents=True)
    early = [{"type": "user", "timestamp": _ts(sid, 2), "message": {"content": "brief one"}},
             {"type": "assistant", "timestamp": _ts(sid, 2), "message": {"content": [{"type": "text", "text": "early words"}]}},
             {"type": "assistant", "timestamp": "2027-01-01T00:00:00.000Z",
              "message": {"content": [{"type": "text", "text": "late words"}]}}]
    (subdir / "agent-early1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in early))
    late = [{"type": "user", "timestamp": "2027-01-01T00:00:00.000Z", "message": {"content": "brief two"}}]
    (subdir / "agent-late22.jsonl").write_text("".join(json.dumps(r) + "\n" for r in late))
    plan = engine.plan_session(path, 0, 7, None, home=home, sent=provenance.SentIndex(), judged_uuids=frozenset(),
                               spine_tokens=20_000, index=None, records={})
    assert set(plan.spine.subagents) == {"early1"}  # control: the spine lists only the log begun in time
    tool = {t.name: t for t in plan.toolset.tools}
    import asyncio

    reply = asyncio.run(tool["search_subagent"].handler({"subagent": "late22", "query": "brief"}))
    assert reply.is_error and "early1" in reply.text and "late22" not in reply.text
    found = asyncio.run(tool["search_subagent"].handler({"subagent": "early1", "query": "words"})).text
    assert "early words" in found and "late words" not in found


def test_one_moment_from_a_fork_and_its_parent_lands_once(home, root, backend, tmp_path, monkeypatch):
    rid, rule = "lrn-0000ccc1", "lrn-0000ccc2"
    put_record(home, rid)
    put_record(home, rule, status="routed")
    _flagged(monkeypatch, rule)
    parent, fork = "s1pppppp-0000", "s2pppppp-0000"
    rows = session_rows(parent, host(tmp_path))
    write_session(root, parent, rows)
    write_session(root, fork, [dict(r, sessionId=fork) for r in rows])  # a fork copies uuids
    for sid in (parent, fork):
        backend.answers[sid] = output(
            [lesson()],
            sightings=[_sighting(sid, rid)],
            rule_checks=[{"record": rule, "outcome": "cannot-tell", "situation": {"line": 4}, "action": None}],
        )
    result = run(home)
    # the fork's copies read as judged once the parent is planned: nothing new, never called
    assert len(backend.specs) == 1 and result.engine["skipped"] == {"nothing-new": 1}
    assert result.folded == [rid] and result.fires == 1 and len(result.landed) == 1


def test_a_fork_with_new_turns_sees_its_parent_s_moments_as_mined(home, root, backend, tmp_path):
    parent, fork = "s1forkpa-0000", "s2forkch-0000"
    rows = session_rows(parent, host(tmp_path))
    write_session(root, parent, rows)
    extra = [typed(fork, 8, "and add the export to the nightly job", host(tmp_path)),
             asst(fork, 9, "Added.", host(tmp_path))]
    write_session(root, fork, [dict(r, sessionId=fork) for r in rows] + extra)
    for sid in (parent, fork):
        backend.answers[sid] = output([lesson()])
    result = run(home)
    assert len(backend.specs) == 2  # control: the fork has a new turn, so it is called
    fork_prompt = next(s.prompt for s in backend.specs if f"SESSION {fork}" in s.prompt)
    parent_prompt = next(s.prompt for s in backend.specs if f"SESSION {parent}" in s.prompt)
    assert "already mined" in fork_prompt and "already mined" not in parent_prompt
    assert len(result.landed) == 1 and len(pending(home)) == 1
    out = json.loads((run_dir(result) / "out" / f"{fork}.json").read_text())
    assert out["lessons"] == [] and "already-judged" in {d["reason"] for d in out["drops"]}


def _checked_lesson(sid: str, uid: str, line: int = 3) -> dict:
    ref = {"session": sid, "line": line, "uuid": uid, "role": "user", "project_dir": PROJECT,
           "file": f"{sid}.jsonl", "entry_ts": "2026-10-01T10:00:03.000Z"}
    item = {"ref": ref, "quote": "you never ran make check"}
    return {"id": "L1", "shape": "correction", "scope": "user", "type": "behavior", "kind": "anti-pattern",
            "trigger": "About to tell the person the checks pass without having run them",
            "instruction": "Run make check and read its log first, because a claimed pass costs a review",
            "fact": None, "context": None, "evidence": [item], "steps": [], "verification": None,
            "incident_cost": None, "generality": None, "why_durable": "recurs", "subagent_cause": None}


def test_the_landing_lands_one_lesson_per_moment_even_past_the_plan(home):
    doc = {"lessons": [], "sightings": [], "rule_checks": [], "drops": []}
    a = dict(doc, lessons=[_checked_lesson("s1landpa-0000", "shared-u-3")])
    b = dict(doc, lessons=[_checked_lesson("s2landfk-0000", "shared-u-3")])
    result = miner.MineResult(status="ok")
    from self_learn import intents

    with intents.ledger_write(home):
        landings = miner._land_checked(home, [("s1landpa-0000", a, None, False), ("s2landfk-0000", b, None, False)],  # pyright: ignore[reportPrivateUsage]
                                       result, 10)
    assert len(result.landed) == 1 and all(x.complete for x in landings.values())
    assert [o["outcome"] for o in result.outcomes] == ["landed", "skipped-duplicate-moment"]


def test_the_store_learns_a_session_only_after_it_landed(home, root, backend, tmp_path, monkeypatch):
    sid = "s1qqqqqq-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    store = uuids.JudgedUuids(miner.miner_dir() / uuids.STORE_NAME)
    order: list[str] = []
    real_add = uuids.JudgedUuids.add
    real_commit = miner._commit_landing  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(uuids.JudgedUuids, "add", lambda self, u, on: order.append("add") or real_add(self, u, on))
    monkeypatch.setattr(miner, "_commit_landing", lambda *a, **k: order.append("commit") or real_commit(*a, **k))
    result = run(home)
    assert order == ["commit", "add"]
    assert {f"{sid}-u-3", f"{sid}-a-2", f"{sid}-a-5"} <= store.snapshot()
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert rec["judged_uuids"]["added"] == len(store.snapshot())
    # the next run sees those moments as judged: a fork of the session has nothing new
    fork = "s2qqqqqq-0000"
    write_session(root, fork, [dict(r, sessionId=fork) for r in session_rows(sid, host(tmp_path))])
    before = len(backend.specs)
    second = run(home)
    assert len(backend.specs) == before and second.engine["skipped"] == {"nothing-new": 1}


def test_a_held_session_adds_nothing_to_the_store(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "0")
    sid = "s1rrrrrr-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])
    result = run(home)
    assert [o["outcome"] for o in result.outcomes if o["outcome"] == "dropped-cap"] == ["dropped-cap"]
    assert sid in result.held_sessions and cursor(path) is None
    assert uuids.JudgedUuids(miner.miner_dir() / uuids.STORE_NAME).snapshot() == frozenset()


def test_a_damaged_store_is_rebuilt_and_the_run_record_says_so(home, root, backend, tmp_path):
    p = miner.miner_dir() / uuids.STORE_NAME
    p.write_bytes(b"not a database " * 50)
    sid = "s1ssssss-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    result = run(home)
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert rec["judged_uuids"]["state"] == "rebuilt" and rec["judged_uuids"]["aside"].startswith(uuids.STORE_NAME)
    assert (p.parent / rec["judged_uuids"]["aside"]).is_file()
    assert f"judged-uuid store damaged; moved aside to {rec['judged_uuids']['aside']}" in (
        miner.miner_dir() / "miner.log").read_text()


def test_the_ledger_lock_not_taken_holds_every_called_cursor(home, root, backend, tmp_path, monkeypatch):
    from self_learn import gitops, intents

    sid = "s1tttttt-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])

    class Busy:
        def __enter__(self):
            raise gitops.GitOpsError("lock busy")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(intents, "ledger_write", lambda h: Busy())
    result = run(home)
    assert result.landed == [] and cursor(path) is None
    assert uuids.JudgedUuids(miner.miner_dir() / uuids.STORE_NAME).snapshot() == frozenset()


# ============================================ fix round (gate-r2 findings)
# Gate probes adapted: a landing that did not complete is held; fires and
# recurrence-suspects are output; replay dedupes spooled events; sighting
# replay is per (record, moment).


def _store_rows() -> frozenset[str]:
    return uuids.JudgedUuids(miner.miner_dir() / uuids.STORE_NAME).snapshot()


def test_a_record_write_that_fails_holds_the_session_and_lands_next_run(home, root, backend, tmp_path, monkeypatch):
    sid = "failed-0001"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])

    def refused(*a, **kw):
        raise miner.LedgerOpsError("synthetic temporary landing failure")

    with monkeypatch.context() as m:
        m.setattr(miner, "create_record", refused)
        first = run(home)
    assert first.landed == [] and first.status == "failed"
    assert [o["cursor"] for o in first.outcomes if o["outcome"] == "dropped-land-failed"] == ["held"]
    assert cursor(path) is None and _store_rows() == frozenset()
    assert journal_last()["sessions_land_failed"] == 1
    again = run(home)
    assert len(backend.specs) == 2 and len(again.landed) == 1 and len(pending(home)) == 1
    assert cursor(path)["lines"] == 7 and f"{sid}-u-3" in _store_rows()


def test_a_landing_that_raises_inside_the_lock_judges_nothing(home, root, backend, tmp_path, monkeypatch):
    from self_learn import gitops

    sid = "partial-0001"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])

    def fail(*a, **kw):
        raise gitops.GitOpsError("synthetic error inside the acquired lock before the first write")

    with monkeypatch.context() as m:
        m.setattr(miner, "_land_checked", fail)
        first = run(home)
    assert len(backend.specs) == 1  # control: the session was called
    assert first.landed == [] and cursor(path) is None and _store_rows() == frozenset()
    again = run(home)
    assert len(again.landed) == 1 and cursor(path)["lines"] == 7


def test_one_session_s_failed_landing_leaves_the_others_landed(home, root, backend, tmp_path, monkeypatch):
    good, bad = "s1landed-0000", "s2landfl-0000"
    gp = write_session(root, good, session_rows(good, host(tmp_path)))
    bp = write_session(root, bad, session_rows(bad, host(tmp_path)))
    backend.answers[good] = output([lesson()])
    backend.answers[bad] = output([lesson(scope="user")])
    real = miner.create_record

    def flaky(home_, record, **kw):
        if any(e["session"] == bad for e in record.evidence):
            raise OSError("disk full")
        return real(home_, record, **kw)

    monkeypatch.setattr(miner, "create_record", flaky)
    result = run(home)
    assert result.status == "ok" and len(result.landed) == 1
    assert cursor(gp)["lines"] == 7 and cursor(bp) is None
    assert f"{good}-u-1" in _store_rows() and not any(u.startswith(bad) for u in _store_rows())


def test_a_failed_fire_spool_holds_the_session(home, root, backend, tmp_path, monkeypatch):
    rid, sid = "lrn-11110003", "spooled-0001"
    put_record(home, rid, status="routed")
    _flagged(monkeypatch, rid)
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(rule_checks=[{
        "record": rid, "outcome": "suspected-violation", "situation": {"line": 4}, "action": None,
    }])
    real = telemetry.spool_event

    def broken(kind, **kw):
        if kind == "fire":
            raise OSError("synthetic disk full")
        return real(kind, **kw)

    with monkeypatch.context() as m:
        m.setattr(telemetry, "spool_event", broken)
        first = run(home)
    assert len(backend.specs) == 1 and first.fires == 0
    assert cursor(path) is None and _store_rows() == frozenset()
    assert not [e for e in telemetry.read_events(home) if e.get("kind") == "fire"]
    again = run(home)
    assert again.fires == 1 and cursor(path)["lines"] == 7
    assert len([e for e in telemetry.read_events(home) if e.get("kind") == "fire"]) == 1


def test_a_failed_recurrence_spool_holds_the_session(home, root, backend, tmp_path, monkeypatch):
    rid, sid = "lrn-0000f1a2", "s1recurr-0000"
    put_record(home, rid, status="routed")
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
    real = telemetry.spool_event

    def broken(kind, **kw):
        if kind == "recurrence-suspect":
            raise OSError("synthetic disk full")
        return real(kind, **kw)

    with monkeypatch.context() as m:
        m.setattr(telemetry, "spool_event", broken)
        first = run(home)
    assert first.recurrences == [] and cursor(path) is None
    again = run(home)
    assert again.recurrences == [rid] and cursor(path)["lines"] == 7


@pytest.mark.parametrize("kind", ["fire", "recurrence-suspect"])
def test_a_crash_after_the_spool_replays_without_a_second_event(home, root, backend, tmp_path, monkeypatch, kind):
    rid, sid = "lrn-11110004", "crashed-0001"
    put_record(home, rid, status="routed")
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    if kind == "fire":
        _flagged(monkeypatch, rid)
        backend.answers[sid] = output(rule_checks=[{
            "record": rid, "outcome": "suspected-violation", "situation": {"line": 4}, "action": None,
        }])
    else:
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])

    def crash(*a, **kw):
        raise RuntimeError("simulated interruption after the spool, before any progress write")

    with monkeypatch.context() as m:
        m.setattr(miner, "_commit_landing", crash)
        first = run(home)
    assert first.status == "failed" and cursor(path) is None
    spooled = [e for e in telemetry.read_spooled([kind])]
    assert len(spooled) == 1  # control: the first run did spool its event
    second = run(home)
    assert second.status == "ok" and cursor(path)["lines"] == 7
    events = [e for e in telemetry.read_events(home) if e.get("kind") == kind]
    assert [(e["record"], e["origin"]) for e in events] == [(rid, f"transcript:{sid}#L{4 if kind == 'fire' else 3}")]


def test_two_records_sighted_at_one_moment_both_fold(home, root, backend, tmp_path):
    a, b = "lrn-11110001", "lrn-11110002"
    pa, pb = put_record(home, a), put_record(home, b)
    sid = "sighting-0001"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, a), _sighting(sid, b)])
    result = run(home)
    checked = json.loads((run_dir(result) / "out" / f"{sid}.json").read_text())
    assert len(checked["sightings"]) == 2  # control: both survived the check
    assert set(result.folded) == {a, b}
    assert Record.from_path(pa).sightings == 2 and Record.from_path(pb).sightings == 2


def test_a_sighting_at_a_new_lesson_s_moment_still_folds(home, root, backend, tmp_path):
    rid = "lrn-0000f1a3"
    put_record(home, rid)
    sid = "s1lesfol-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()], sightings=[_sighting(sid, rid)])
    result = run(home)
    assert len(result.landed) == 1 and result.folded == [rid]


def test_a_replayed_sighting_does_not_fold_twice(home, root, backend, tmp_path, monkeypatch):
    rid = "lrn-0000f1a4"
    path = put_record(home, rid)
    sid = "s1replay-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, rid)])

    def crash(*a, **kw):
        raise RuntimeError("simulated interruption after the fold, before any progress write")

    with monkeypatch.context() as m:
        m.setattr(miner, "_commit_landing", crash)
        run(home)
    assert Record.from_path(path).sightings == 2  # control: the fold was written
    again = run(home)
    assert again.folded == [] and Record.from_path(path).sightings == 2
    assert [o["outcome"] for o in again.outcomes] == ["skipped-known-origin"]


@pytest.mark.parametrize("where", ["check", "first-call", "pool-call"])
def test_an_unexpected_exception_fails_one_session_only(home, root, backend, tmp_path, monkeypatch, where):
    monkeypatch.setenv("SELF_LEARN_MINER_PARALLEL", "2")
    sids = ["s1unexpa-0000", "s2unexpb-0000", "s3unexpc-0000"]
    paths = {sid: write_session(root, sid, session_rows(sid, host(tmp_path))) for sid in sids}
    for sid in sids:
        backend.answers[sid] = output([lesson()])
    bad = {"check": sids[1], "first-call": sids[0], "pool-call": sids[2]}[where]
    if where == "check":
        real = check.check_output

        def flaky(text, spine, **kw):
            if spine.session.session_id == bad:
                raise KeyError("a defect, not a CheckerError")
            return real(text, spine, **kw)

        monkeypatch.setattr(engine.check_mod, "check_output", flaky)
    else:
        real_call = miner._session_call  # pyright: ignore[reportPrivateUsage]

        def call(spec):
            if f"SESSION {bad}" in spec.prompt:
                raise TypeError("a defect in the seam")
            return real_call(spec)

        monkeypatch.setattr(miner, "_session_call", call)
    result = run(home)
    assert result.status == "ok" and len(result.landed) == 2
    assert cursor(paths[bad]) is None and all(cursor(paths[s])["lines"] == 7 for s in sids if s != bad)
    rec = json.loads((run_dir(result) / "run.json").read_text())
    row = {r["session"]: r for r in rec["sessions"]}[bad]
    assert row["error"] == ("checker-error" if where == "check" else "call")


def _called(backend: Backend, since: int = 0) -> list[str]:
    return [re.search(r"^SESSION (\S+)", s.prompt, re.M).group(1) for s in backend.specs[since:]]


def test_a_ceiling_stop_counts_no_failure(home, root, tmp_path, monkeypatch):
    b = Backend(cost=3.0)
    monkeypatch.setattr(invocation.registry, "backend_for", lambda *a, **k: b)
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_RUN_USD", "2")
    first, second = "s1ceilfl-0000", "s2ceilnr-0000"
    p1 = write_session(root, first, session_rows(first, host(tmp_path)))
    p2 = write_session(root, second, session_rows(second, host(tmp_path)))
    b.answers[first] = "this is not JSON"
    run(home)
    assert len(b.specs) == 1  # control: the guard stopped the second call
    data = json.loads((miner.miner_dir() / engine.FAILURES_NAME).read_text())
    assert data[str(p1)]["failures"] == 1 and str(p2) not in data


def _cache_hashes(base: Path, skip: Path) -> dict[str, str]:
    return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file() and skip not in p.parents}


def test_a_preview_changes_nothing_in_the_cache_outside_its_run_folder(home, root, backend, tmp_path):
    from test_mining_check import _crash_image

    rid = "lrn-0000f1a5"
    put_record(home, rid)
    run(home)  # an idle night run first: the lock, the log, the index exist as they do on a live host
    live = miner.miner_dir() / uuids.STORE_NAME
    crash = _crash_image(tmp_path)
    live.write_bytes(crash.read_bytes())
    journal = live.with_name(live.name + "-journal")
    journal.write_bytes(crash.with_name(crash.name + "-journal").read_bytes())
    runs = miner.miner_dir() / "runs"
    for n in range(31):
        d = runs / f"old-{n:02d}"
        d.mkdir(parents=True)
        (d / "run.json").write_text('{"retained":true}')
        os.utime(d, (1_700_000_000 + n, 1_700_000_000 + n))
    copies = miner.miner_dir().parent / "sessions" / "miner-session"
    for n in range(31):
        (copies / f"g{n:02d}").mkdir(parents=True)
        (copies / f"g{n:02d}" / "copy.jsonl").write_text("{}\n")
    sid = "s1prvwhj-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()], sightings=[_sighting(sid, rid)])
    cache = tmp_path / "xdg-cache"
    before = _cache_hashes(cache, runs / "none")
    lock = miner.miner_dir() / "miner.lock"
    os.utime(lock, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    assert journal.stat().st_size > 0 and len(before) > 70  # control: a hot journal and a populated cache
    result = run(home, preview=True)
    folder = run_dir(result)
    out = json.loads((folder / "out" / f"{sid}.json").read_text())
    assert out["lessons"] and out["sightings"]  # control: the preview judged the session
    after = _cache_hashes(cache, folder)
    assert after == before
    assert lock.stat().st_mtime_ns == 1_700_000_000_000_000_000  # the run lock is not truncated
    assert (folder / "miner.log").is_file() and not (folder / "copies").exists()
    assert backend.specs[0].skip_orphan_sweep is True and backend.specs[0].cwd == folder / "stage"


def test_the_override_channel_cannot_switch_the_engine(home, root, tmp_path, monkeypatch):
    calls: list[str] = []

    def reader(_home, prompt):
        calls.append(prompt)
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": []}))
        return out

    monkeypatch.setattr(miner, "_invoke_reader", reader)
    monkeypatch.setattr(miner, "_session_call", lambda spec: pytest.fail("the session engine was called"))
    from self_learn import config

    var = config.override_env_var("miner.engine")
    assert var == "SELF_LEARN_OVERRIDE_MINER_ENGINE"
    monkeypatch.setenv(var, "session")
    # control: the same channel does move an ordinary entry
    monkeypatch.setenv("SELF_LEARN_OVERRIDE_MINER_PARALLEL", "3")
    assert settings.resolve_setting(home, settings.by_name("miner.parallel")) == (3, "override:miner.parallel")
    assert settings.resolve_setting(home, settings.by_name("miner.engine"))[0] == "digest"
    sid = "s1ovrrde-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    result = miner.run(home, no_push=True)
    assert result.status == "ok" and len(calls) == 1 and "engine" not in journal_last()
    assert var in settings.unknown_override_vars()  # doctor settings names it: set, and doing nothing
    with pytest.raises(ValueError):
        with settings.override("miner.engine", "session"):
            pass


def test_a_subagent_line_s_origin_is_read_by_the_steward(home, root, tmp_path):
    sid = "s1subagt-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    log = root / PROJECT / sid / "subagents" / "agent-a1b2.jsonl"
    log.parent.mkdir(parents=True)
    sub_rows = [dict(asst(sid, 1, "Looking at the export path.", host(tmp_path)), isSidechain=True),
                dict(asst(sid, 2, "The export path is wrong in the config.", host(tmp_path)), isSidechain=True)]
    log.write_text("".join(json.dumps(r) + "\n" for r in sub_rows))
    origin = miner._ref_origin({"session": sid, "subagent_file": "subagents/agent-a1b2.jsonl", "line": 2})  # pyright: ignore[reportPrivateUsage]
    assert origin == f"transcript:{sid}/subagents/agent-a1b2.jsonl#L2"
    text, stats = steward_inputs.fire_pack(
        [{"nonce": "n1", "ts": "2026-10-01T10:00:00Z", "outcome": "suspected-violation", "origin": origin}],
        roots=[root], budget=4000,
    )
    assert "could not be read" not in text and stats["excerpted"] == 1
    assert "The export path is wrong in the config." in text
    record = Record.create(type="behavior", scope="user", source="session", kind="anti-pattern",
                           trigger="About to change the export path", instruction="Read the config first, because it is wrong",
                           record_id="lrn-0000f1a6",
                           evidence=[{"origin": origin, "quote": "The export path is wrong in the config."}])
    items, _ = steward_inputs.evidence_pack(record, roots=[root], budget=4000)
    assert items[0].verdict == "exact" and items[0].found is not None
    assert items[0].found.subagent_file == "subagents/agent-a1b2.jsonl" and items[0].found.line == 2


# ------------------------------------------- branches the gate found untested


def test_a_rule_check_against_a_record_not_routed_spools_no_fire(home, root, backend, tmp_path, monkeypatch):
    rid = "lrn-0000f1b1"
    put_record(home, rid)  # pending, not routed
    _flagged(monkeypatch, rid)
    sid = "s1notrtd-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(rule_checks=[{"record": rid, "outcome": "suspected-violation",
                                                "situation": {"line": 4}, "action": None}])
    result = run(home)
    out = json.loads((run_dir(result) / "out" / f"{sid}.json").read_text())
    assert len(out["rule_checks"]) == 1  # control: the check kept it
    assert result.fires == 0 and [o["outcome"] for o in result.outcomes] == ["fire-skipped"]
    assert not [e for e in telemetry.read_spooled(["fire"])] and cursor(path)["lines"] == 7


def test_two_transient_failures_in_a_row_make_exactly_one_retry(home, root, backend, tmp_path):
    sid = "s1twotrn-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    busy = FakeOutcome(ok=False, failure="exit", detail="API Error: 529 overloaded", rc=1)
    backend.answers[sid] = [busy, busy, FakeOutcome(ok=True, stdout=output(), cost_usd=0.1)]
    result = run(home)
    assert backend.attempts[sid] == 2 and result.status == "failed" and cursor(path) is None
    calls = json.loads((run_dir(result) / "calls" / f"{sid}.json").read_text())
    assert calls["attempts"] == 2 and calls["ok"] is False


def test_max_sessions_per_run_defers_the_rest_behind_their_cursors(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "2")
    sids = ["s1maxone-0000", "s2maxtwo-0000", "s3maxthr-0000"]
    paths = [write_session(root, sid, session_rows(sid, host(tmp_path))) for sid in sids]
    first = run(home)
    assert _called(backend) == sids[:2] and first.engine["deferred"] == 1
    assert cursor(paths[2]) is None and cursor(paths[0])["lines"] == 7
    run(home)
    assert _called(backend, 2) == sids[2:] and cursor(paths[2])["lines"] == 7


def test_a_rejected_lesson_resurfaces_on_its_third_sighting_and_only_once(home, root, backend, tmp_path):
    rid = "lrn-0000f1b2"
    put_record(home, rid, status="rejected")
    for n in range(1, miner.REJECTED_RESURFACE_SIGHTINGS + 2):
        sid = f"s{n}rejsig-0000"
        write_session(root, sid, session_rows(sid, host(tmp_path)))
        backend.answers[sid] = output(sightings=[_sighting(sid, rid)])
        result = run(home)
        assert len(backend.specs) == n  # control: each sighting was judged in its own run
        expected = 0 if n < miner.REJECTED_RESURFACE_SIGHTINGS else 1
        assert len(pending(home)) == expected, (n, result.outcomes)
        if n == miner.REJECTED_RESURFACE_SIGHTINGS:
            assert [o["outcome"] for o in result.outcomes] == ["landed", "resurfaced"]
            assert pending(home)[0].id != rid
        else:
            assert [o["outcome"] for o in result.outcomes] == ["dropped-rejected"]


def test_a_capped_halted_session_advances_to_its_halt(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "0")
    sid = "s1caphlt-0000"
    rows = session_rows(sid, host(tmp_path)) + [
        typed(sid, 8, "<command-name>/self-learn:teach</command-name>", host(tmp_path))]
    path = write_session(root, sid, rows)
    backend.answers[sid] = output([lesson()])
    result = run(home)
    capped = [o for o in result.outcomes if o["outcome"] == "dropped-cap"]
    assert [o["cursor"] for o in capped] == ["advanced-halted"]
    assert sid not in result.held_sessions and cursor(path) is not None
    assert f"{sid}-u-3" in _store_rows()


def test_a_second_file_with_the_same_session_id_waits_for_the_next_run(home, root, backend, tmp_path):
    sid = "s1twinid-0000"
    a = write_session(root, sid, session_rows(sid, host(tmp_path)))
    other = [dict(r, uuid=r["uuid"] + "-b") for r in session_rows(sid, host(tmp_path))]  # not a copy of a
    b = write_session(root, sid, other, project="-work-other")
    first = run(home)
    assert len(backend.specs) == 1 and first.engine["deferred"] == 1
    assert [cursor(a) is None, cursor(b) is None].count(True) == 1  # one judged, one held
    run(home)
    assert len(backend.specs) == 2 and cursor(a) is not None and cursor(b) is not None


def test_a_long_episode_brief_is_cut_to_the_digest_ceiling(home, root, backend, tmp_path):
    sid = "s1longbr-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    words = "the agent says the checks pass and the person asks for the log once more "
    steps = [{"line": n, "what": (f"step {n} " + words * 4)[:290]} for n in range(1, 7)]
    backend.answers[sid] = output([lesson(steps=steps)])
    result = run(home)
    assert len(result.landed) == 1, result.outcomes
    (record,) = pending(home)
    brief = record.body.split("## Episode brief\n", 1)[1].strip("\n")
    assert len(brief) <= miner.MAX_EPISODE_BRIEF_CHARS < sum(len(s["what"]) for s in steps)
    *kept, last = brief.split("\n")
    assert kept and all(f"step {n} " in line for n, line in enumerate(kept, 1))
    assert last.startswith(f"… {6 - len(kept)} more step(s) left out")
    # the marker's own room is kept: three 395-character lines fit 1,200 alone, not with the marker
    cut = miner._capped_brief(["y" * 395] * 4)  # pyright: ignore[reportPrivateUsage]
    assert len(cut) <= miner.MAX_EPISODE_BRIEF_CHARS and cut.count("y" * 395) == 2


def test_damaged_stores_past_the_newest_three_are_deleted(home, root, backend, tmp_path):
    mdir = miner.miner_dir()
    names = [f"{uuids.STORE_NAME}.damaged-2026010{d}T000000Z" for d in range(1, 6)]
    for name in names:
        (mdir / name).write_bytes(b"old")
        (mdir / (name + "-journal")).write_bytes(b"old")
    sid = "s1damprn-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    run(home, preview=True)
    assert all((mdir / n).exists() for n in names)  # a preview deletes none
    run(home)
    left = sorted(p.name for p in mdir.glob(f"{uuids.STORE_NAME}.damaged-*"))
    assert left == sorted([*names[2:], *(n + "-journal" for n in names[2:])])


# ============================================ fix round 2 (gate-r2 round 2)
# The store rule: the judged-uuid store learns only from a session whose
# landing completed, and a moment claimed at planning only once its claimer
# completed. Each replay below lands the missing output exactly once.


def test_a_partly_landed_session_teaches_the_store_nothing(home, root, backend, tmp_path, monkeypatch):
    rid = "lrn-0000f1a1"
    put_record(home, rid, status="routed")
    sid = "s1partly-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()], sightings=[_sighting(sid, rid, line=6, quote="always run the checks")])
    real = telemetry.spool_event

    def broken(kind, **kw):
        if kind == "recurrence-suspect":
            raise OSError("synthetic disk full")
        return real(kind, **kw)

    with monkeypatch.context() as m:
        m.setattr(telemetry, "spool_event", broken)
        first = run(home)
    assert len(first.landed) == 1 and cursor(path) is None  # control: the lesson landed, the session is held
    assert _store_rows() == frozenset()
    rec = json.loads((run_dir(first) / "run.json").read_text())
    assert {r["session"]: r for r in rec["sessions"]}[sid]["landing"] == "failed"
    second = run(home)  # the lesson is known by its origin; the recurrence spools once
    assert second.landed == [] and second.recurrences == [rid] and len(pending(home)) == 1
    assert [o["outcome"] for o in second.outcomes] == ["skipped-known-origin", "recurrence"]
    assert cursor(path)["lines"] == 7 and f"{sid}-u-3" in _store_rows()


def test_a_partial_fold_failure_folds_the_other_record_on_retry(home, root, backend, tmp_path, monkeypatch):
    a, b = "lrn-22220001", "lrn-22220002"
    pa, pb = put_record(home, a), put_record(home, b)
    sid = "partialfold-0001"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(sightings=[_sighting(sid, a), _sighting(sid, b)])
    real = Record.write

    def flaky(self, target, *args, **kwargs):
        if self.id == b:
            raise OSError("synthetic second-record write failure")
        return real(self, target, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Record, "write", flaky)
        first = run(home)
    assert first.folded == [a] and cursor(path) is None
    assert Record.from_path(pa).sightings == 2 and Record.from_path(pb).sightings == 1
    second = run(home)
    assert second.folded == [b] and cursor(path)["lines"] == 7
    assert Record.from_path(pa).sightings == 2 and Record.from_path(pb).sightings == 2


def test_a_partial_lesson_landing_whose_fire_failed_spools_it_once(home, root, backend, tmp_path, monkeypatch):
    rid, sid = "lrn-22220003", "partialfire-0001"
    put_record(home, rid, status="routed")
    _flagged(monkeypatch, rid)
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()], rule_checks=[{
        "record": rid, "outcome": "suspected-violation", "situation": {"line": 4}, "action": None}])
    real = telemetry.spool_event

    def flaky(kind, **kwargs):
        if kind == "fire":
            raise OSError("synthetic fire spool failure")
        return real(kind, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(telemetry, "spool_event", flaky)
        first = run(home)
    assert len(first.landed) == 1 and first.fires == 0 and cursor(path) is None
    second = run(home)
    assert second.landed == [] and second.fires == 1 and cursor(path)["lines"] == 7
    assert len([e for e in telemetry.read_events(home) if e.get("kind") == "fire"]) == 1
    assert len(pending(home)) == 1


def test_a_second_fire_that_failed_spools_once_and_the_first_not_again(home, root, backend, tmp_path, monkeypatch):
    r1, r2 = "lrn-22220005", "lrn-22220006"
    put_record(home, r1, status="routed")
    put_record(home, r2, status="routed")

    def fake(index, stretches, *, cwd, entries=(), provider=None):
        return flags_mod.FlagResult(tuple(flags_mod.Flag(r, 2, 4, 5, 0.9, None, 1.0, "rule") for r in (r1, r2)),
                                    "lexical-only", "")

    monkeypatch.setattr(engine.flags_mod, "flag_rules", fake)
    sid = "s1twofir-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output(rule_checks=[
        {"record": r1, "outcome": "suspected-violation", "situation": {"line": 4}, "action": None},
        {"record": r2, "outcome": "suspected-violation", "situation": {"line": 4}, "action": None}])
    real = telemetry.spool_event

    def flaky(kind, **kwargs):
        if kind == "fire" and kwargs.get("record") == r2:
            raise OSError("synthetic fire spool failure")
        return real(kind, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(telemetry, "spool_event", flaky)
        first = run(home)
    assert first.fires == 1 and cursor(path) is None
    second = run(home)
    assert second.fires == 1 and cursor(path)["lines"] == 7
    fires = sorted(e["record"] for e in telemetry.read_events(home) if e.get("kind") == "fire")
    assert fires == [r1, r2]


def _fork_pair(root: Path, tmp_path: Path) -> tuple[str, str, Path]:
    parent, fork = "s1claimr-0000", "s2claimd-0000"
    rows = session_rows(parent, host(tmp_path))
    path = write_session(root, parent, rows)
    write_session(root, fork, [dict(r, sessionId=fork) for r in rows] + [
        typed(fork, 8, "and add the export to the nightly job", host(tmp_path)),
        asst(fork, 9, "Added.", host(tmp_path))])
    return parent, fork, path


@pytest.mark.parametrize("failure", ["call", "landing", "cap"])
def test_a_fork_never_certifies_moments_its_unlanded_claimer_holds(home, root, backend, tmp_path, monkeypatch, failure):
    parent, fork, path = _fork_pair(root, tmp_path)
    backend.answers[fork] = output([lesson()])
    backend.answers[parent] = output([lesson()])
    if failure == "call":
        backend.answers[parent] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]

    def refused(*args, **kwargs):
        raise OSError("synthetic parent landing failure")

    with monkeypatch.context() as m:
        if failure == "landing":
            m.setattr(miner, "create_record", refused)
        elif failure == "cap":
            m.setenv("SELF_LEARN_MINE_CAP_MAX", "0")
        first = run(home)
    assert len(backend.specs) == 2 and first.landed == [] and cursor(path) is None
    out = json.loads((run_dir(first) / "out" / f"{fork}.json").read_text())
    assert out["lessons"] == []  # control: the fork's copy of the lesson was the parent's to judge
    rows = _store_rows()
    assert f"{fork}-u-8" in rows  # the fork's own new turn is learned
    assert not any(u.startswith(parent) for u in rows)  # the claimer's moments are not
    backend.answers[parent] = output([lesson()])
    second = run(home)
    assert len(backend.specs) == 3 and len(second.landed) == 1 and len(pending(home)) == 1
    assert cursor(path)["lines"] == 7
    third = run(home)
    assert third.landed == [] and len(pending(home)) == 1  # exactly once


def test_a_halted_session_whose_landing_failed_keeps_its_cursor(home, root, backend, tmp_path, monkeypatch):
    sid = "s1hltfal-0000"
    rows = session_rows(sid, host(tmp_path)) + [
        typed(sid, 8, "<command-name>/self-learn:teach</command-name>", host(tmp_path))]
    path = write_session(root, sid, rows)
    backend.answers[sid] = output([lesson()])

    def refused(*args, **kwargs):
        raise OSError("synthetic")

    with monkeypatch.context() as m:
        m.setattr(miner, "create_record", refused)
        first = run(home)
    assert [o["outcome"] for o in first.outcomes] == ["dropped-land-failed"]  # control: it was called and held
    assert cursor(path) is None and _store_rows() == frozenset()
    again = run(home)
    assert len(again.landed) == 1 and cursor(path) is not None


def test_a_failed_landing_shows_in_the_run_record(home, root, backend, tmp_path, monkeypatch):
    sid = "failedrecord-0001"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])

    def refused(*args, **kwargs):
        raise OSError("synthetic unavailable disk")

    monkeypatch.setattr(miner, "create_record", refused)
    result = run(home)
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert result.status == "failed" and rec["status"] == "failed"
    assert rec["totals"]["lessons"] == 1  # what the check kept
    assert rec["landed"] == {"lessons": 0, "folded": 0, "recurrences": 0, "fires": 0, "sessions_failed": 1}
    (row,) = rec["sessions"]
    assert row["out_status"] == "ok" and row["landing"] == "failed"
    contract.load_run(run_dir(result))


def test_a_landed_run_record_names_each_landing(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    sids = ["s1recdon-0000", "s2recapd-0000"]
    for sid in sids:
        write_session(root, sid, session_rows(sid, host(tmp_path)))
        backend.answers[sid] = output([lesson()])
    result = run(home)
    rec = json.loads((run_dir(result) / "run.json").read_text())
    assert rec["status"] == "ok" and rec["landed"]["lessons"] == 1 and rec["landed"]["sessions_failed"] == 0
    assert {r["session"]: r["landing"] for r in rec["sessions"]} == {sids[0]: "complete", sids[1]: "held"}
    contract.load_run(run_dir(result))


def test_a_failing_session_waits_behind_the_others(home, root, backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "2")
    bad, good, new = "s1waitbh-0000", "s2waitok-0000", "s3getsin-0000"
    bp = write_session(root, bad, session_rows(bad, host(tmp_path)))
    write_session(root, good, session_rows(good, host(tmp_path)))
    backend.answers[bad] = [FakeOutcome(ok=False, failure="exit", detail="boom", rc=1)]
    run(home)
    assert _called(backend) == [bad, good]
    failing = json.loads((miner.miner_dir() / engine.FAILURES_NAME).read_text())
    assert failing[str(bp)]["failures"] == 1
    np_ = write_session(root, new, session_rows(new, host(tmp_path)))
    monkeypatch.setenv("SELF_LEARN_MINER_MAX_SESSIONS_PER_RUN", "1")
    run(home)
    assert _called(backend, 2) == [new] and cursor(np_)["lines"] == 7  # path order puts bad first
    backend.answers[bad] = output()
    run(home)
    assert _called(backend, 3) == [bad] and cursor(bp)["lines"] == 7
    assert str(bp) not in json.loads((miner.miner_dir() / engine.FAILURES_NAME).read_text())  # landed: cleared


def test_a_failure_count_belongs_to_its_cursor():
    f = engine.Failures(Path("/nonexistent"), {})
    f.failed("k", 0)
    f.failed("k", 0)
    assert f.count("k", 0) == 2 and f.count("k", 5) == 0
    assert f.failed("k", 5) == 1


def test_a_run_whose_lock_was_not_taken_counts_no_failure(home, root, backend, tmp_path, monkeypatch):
    from self_learn import gitops, intents

    sid = "s1lockbs-0000"
    path = write_session(root, sid, session_rows(sid, host(tmp_path)))
    backend.answers[sid] = output([lesson()])

    class Busy:
        def __enter__(self):
            raise gitops.GitOpsError("lock busy")

        def __exit__(self, *a):
            return False

    with monkeypatch.context() as m:
        m.setattr(intents, "ledger_write", lambda h: Busy())
        for _ in range(3):
            run(home)
    assert len(backend.specs) == 3 and cursor(path) is None  # control: called each time, never landed
    f = miner.miner_dir() / engine.FAILURES_NAME
    assert str(path) not in (json.loads(f.read_text()) if f.exists() else {})
    assert len(run(home).landed) == 1 and cursor(path)["lines"] == 7


def test_a_run_where_no_call_succeeded_counts_no_failure(home, root, backend, tmp_path):
    sids = ["s1logout-0000", "s2logout-0000"]
    paths = [write_session(root, sid, session_rows(sid, host(tmp_path))) for sid in sids]
    for sid in sids:
        backend.answers[sid] = [FakeOutcome(ok=False, failure="exit", detail="Not logged in", rc=1)]
    for _ in range(3):
        run(home)
    assert len(backend.specs) == 6  # control: every call was made, and failed
    f = miner.miner_dir() / engine.FAILURES_NAME
    data = json.loads(f.read_text()) if f.exists() else {}
    assert not any(str(p) in data for p in paths)
    for sid in sids:
        backend.answers[sid] = output([lesson()])
    assert len(run(home).landed) == 2


def test_a_preview_s_tools_read_its_own_copy_of_the_lesson_index(home, root, tmp_path, monkeypatch):
    import asyncio

    from self_learn.index.store import LessonIndex, index_path

    rid = "lrn-0000f1c1"
    put_record(home, rid)
    steward_inputs.refresh_index(home)[0].close()  # a live index, as a night run leaves it
    live = index_path(home)
    assert live.is_file()
    before = live.read_bytes()
    replies: list[str] = []
    opened: list[Path] = []
    real_open_at = LessonIndex.open_at.__func__

    def spy_open_at(cls, path, home_):
        opened.append(Path(path))
        return real_open_at(cls, path, home_)

    monkeypatch.setattr(LessonIndex, "open_at", classmethod(spy_open_at))
    monkeypatch.setattr(LessonIndex, "open_existing",
                        classmethod(lambda cls, h=None: pytest.fail("a preview's tool opened the live index")))

    class ToolBackend(Backend):
        def text_session(self, spec):
            tool = next(t for t in spec.mcp_toolset.tools if t.name == "find_similar_lessons")
            reply = asyncio.run(tool.handler({"draft": "About to deploy on a Friday afternoon"}))
            replies.append(str(reply))
            return super().text_session(spec)

    b = ToolBackend()
    monkeypatch.setattr(invocation.registry, "backend_for", lambda *a, **k: b)
    sid = "s1prvtol-0000"
    write_session(root, sid, session_rows(sid, host(tmp_path)))
    result = run(home, preview=True)
    folder = run_dir(result)
    assert replies and rid in replies[0]  # control: the tool ran and found the lesson
    tool_opens = [p for p in opened if p.name == live.name]
    assert tool_opens and all(folder in p.parents for p in tool_opens)
    assert live.read_bytes() == before
