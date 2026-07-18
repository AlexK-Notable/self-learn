"""Doc 12 (transcript miner): digest determinism + M-5 exclusions, cursor
walk, use-scaled caps, gate/dedup/reconciliation, scan-gated landing,
journal contract, watchdog, and the CLI/status surface.

The reader model is shimmed at `_invoke_reader` (unit/e2e) or via a PATH
`claude` shim (artifact-contract test) — the same honesty rule as the
worker suite: shims emit what the model actually would, never
pre-satisfied spec-forbidden fields.
"""

import fcntl
import json
import os
import time
from pathlib import Path

import pytest

from self_learn import cli, miner, telemetry
from self_learn.ledger_ops import create_record
from self_learn.records import Record
from support import commit_all, make_behavior, make_home


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    # doc-13: `home` is the LEDGER; make_home also builds the paired HOST
    # (tmp_path/host-repo) whose registered skill dir supplies skill:s.
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def transcripts(tmp_path, monkeypatch):
    root = tmp_path / "transcripts"
    (root / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
    # Most tests exercise steady-state mining: mark the forward-only
    # initialization as already done (its own behavior is tested in
    # test_first_run_initializes_forward_only).
    miner._save_cursors({"__initialized__": "test-fixture"})
    return root


# ------------------------------------------------------- line builders


def u(text):
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    )


def u_str(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def a(text):
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )


def tool(name, command, tid):
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": tid, "name": name, "input": {"command": command}}
                ]
            },
        }
    )


def result(tid, text, is_error=False):
    return json.dumps(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "is_error": is_error,
                        "content": [{"type": "text", "text": text}],
                    }
                ],
            },
        }
    )


def write_transcript(root, name, lines, project="-home-u-proj"):
    path = root / project / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def slice_of(path, start=0):
    lines = path.read_text(encoding="utf-8").splitlines()
    return miner.SessionSlice(
        path=path,
        session_id=path.stem,
        project=path.parent.name,
        start_line=start,
        lines=lines[start:],
    )


# ------------------------------------------------------------- digest


def test_digest_keeps_speech_drops_tool_bodies(transcripts):
    body = "\n".join(f"noise line {i}" for i in range(50))
    p = write_transcript(
        transcripts,
        "sess1",
        [
            u("please fix the flaky test"),
            tool("Bash", "uv run pytest -q", "t1"),
            result("t1", body),
            a("The root cause was a stale fixture."),
        ],
    )
    digest, halt = miner.digest_transcript(slice_of(p))
    assert not halt
    assert "please fix the flaky test" in digest
    assert "The root cause was a stale fixture." in digest
    assert "noise line 25" not in digest  # body dropped to edges
    assert "noise line 0" in digest and "noise line 49" in digest
    assert "uv run pytest" in digest  # command shape survives
    assert "[user L1]" in digest and "L4]" in digest  # line refs for origins


def test_digest_error_and_retry_cluster(transcripts):
    lines = []
    for i in range(3):
        lines.append(tool("Bash", "make build --fast", f"t{i}"))
        lines.append(result(f"t{i}", "boom", is_error=(i < 2)))
    lines.append(u("ugh, again"))
    p = write_transcript(transcripts, "sess2", lines)
    digest, _halt = miner.digest_transcript(slice_of(p))
    assert "ERROR" in digest
    assert "[retry-cluster Bash:make build ×3, 2 error(s)]" in digest


def test_digest_excludes_own_machinery(transcripts):
    p = write_transcript(
        transcripts,
        "worker-sess",
        [u("You are the self-learn routing analyst worker. Records below."), a("ok")],
    )
    assert miner.digest_transcript(slice_of(p)) == (None, True)
    p2 = write_transcript(
        transcripts,
        "miner-sess",
        [u("You are the self-learn transcript miner. Digests below."), a("ok")],
    )
    assert miner.digest_transcript(slice_of(p2)) == (None, True)


def test_digest_selflearn_tag_halts_rest_of_session(transcripts):
    """Audit 2026-07-15 B2: the old span rule collapsed on the first user
    reply — a review session's card content (verbatim lesson text) was
    mined back as fake sightings. The tag now halts the WHOLE remainder,
    including the user's own review replies, forever."""
    p = write_transcript(
        transcripts,
        "sess3",
        [
            u("normal work before"),
            u("<command-name>/self-learn:review</command-name> run it"),
            a("Card 1 of 3: the lesson about storage edits…"),
            u("route it"),  # the realistic next turn — a review reply
            a("Card 2 of 3: another lesson's full trigger text…"),
        ],
    )
    digest, halt = miner.digest_transcript(slice_of(p))
    assert halt is True
    assert "normal work before" in digest
    assert "Card 1 of 3" not in digest
    assert "route it" not in digest
    assert "Card 2 of 3" not in digest


def test_halt_persists_across_slices(home, transcripts, monkeypatch):
    """Exclusion state must survive cursor splits: a review session still
    being written when the miner runs must stay excluded when its TAIL
    arrives in the next run's slice."""
    p = write_transcript(
        transcripts,
        "sess-split",
        [u("real work"), u("<command-name>/self-learn:review</command-name> go")],
    )
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    assert miner.run(home).status == "ok"
    # the session continues after the first run
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(a("Card 1: verbatim lesson text that must never be mined") + "\n")
    captured = {}

    def spy(h, prompt):
        captured["prompt"] = prompt
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": [], "fires": []}))
        return out

    monkeypatch.setattr(miner, "_invoke_reader", spy)
    result = miner.run(home)
    assert result.status == "idle"  # halted file skipped without reading
    assert "captured" not in captured or "Card 1" not in captured.get("prompt", "")


def test_digest_plain_string_content(transcripts):
    p = write_transcript(transcripts, "sess4", [u_str("string-content user turn")])
    digest, _halt = miner.digest_transcript(slice_of(p))
    assert "string-content user turn" in digest


# ------------------------------------------------------------- walk


def test_walk_cursor_advance_and_append(transcripts):
    p = write_transcript(transcripts, "sess5", [u("one"), u("two")])
    slices = miner.walk()
    assert len(slices) == 1 and slices[0].start_line == 0
    miner._advance_cursors([(s, False) for s in slices])
    assert miner.walk() == []
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(u("three") + "\n")
    slices = miner.walk()
    assert len(slices) == 1
    assert slices[0].start_line == 2 and len(slices[0].lines) == 1


def test_walk_since_rereads_from_zero(transcripts):
    p = write_transcript(transcripts, "sess6", [u("old content")])
    miner._advance_cursors([(s, False) for s in miner.walk()])
    assert miner.walk() == []
    slices = miner.walk(since="2020-01-01")
    assert len(slices) == 1 and slices[0].start_line == 0
    assert miner.walk(since="2999-01-01") == []
    assert p.is_file()


# ------------------------------------------------------------- caps


def test_cap_scales_with_use(monkeypatch):
    assert miner.cap_for(1) == 2
    assert miner.cap_for(4) == 8
    assert miner.cap_for(50) == 15  # ceiling
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "5")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "40")
    assert miner.cap_for(4) == 20
    assert miner.cap_for(100) == 40


# ------------------------------------------------- run: guards + journal


def test_run_disabled(home, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    assert miner.run(home).status == "disabled"


def test_run_busy_under_live_lock(home, transcripts):
    lock = miner.miner_dir() / "miner.lock"
    with open(lock, "w", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        assert miner.run(home).status == "busy"


def test_run_idle_journals_and_touches(home, transcripts):
    result = miner.run(home)
    assert result.status == "idle"
    assert (miner.miner_dir() / "miner.last-run").is_file()
    entries = miner.read_journal()
    assert entries and entries[-1]["status"] == "idle"
    assert entries[-1]["trigger"] == "manual"


def test_run_held_gate_keeps_cursors(home, transcripts, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINE_PENDING_GATE", "1")
    create_record(home, make_behavior())
    p = write_transcript(transcripts, "sess7", [u("real user content here")])
    called = []
    monkeypatch.setattr(miner, "_invoke_reader", lambda *a: called.append(1))
    result = miner.run(home)
    assert result.status == "held-gate"
    assert not called  # reader never invoked
    assert miner.read_journal()[-1]["status"] == "held-gate"
    # cursors NOT advanced: the next run still sees the session
    assert len(miner.walk()) == 1
    assert p.is_file()


# ----------------------------------------------- run: e2e with shimmed reader


def shim_reader(monkeypatch, payload):
    """Replace the model pass: write `payload` as the output artifact."""

    def fake(home, prompt):
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps(payload), encoding="utf-8")
        return out

    monkeypatch.setattr(miner, "_invoke_reader", fake)


def candidate(**over):
    base = {
        "scope": "skill:s",
        "type": "behavior",
        "kind": "anti-pattern",
        "trigger": "About to cp -r a uv project into a sandbox",
        "instruction": "Delete the copied .venv first — the editable install points at the original tree",
        "quote": "rm -rf .venv fixed it",
        "session": "sess-e2e",
        "line": 42,
        "verified": True,
        "verified_how": "reproduced twice in-session",
        "incident_cost": "two invalidated runs",
        "generality": "general-practice",
        "confidence": "high",
        "why_durable": "will recur in any sandboxed uv experiment",
        "match": {"record": None, "status": None},
    }
    base.update(over)
    return base


def pending_ids(home):
    out = []
    for d in home.glob("skills/*/pending/lrn-*.md"):
        out.append(d.stem)
    for d in home.glob("projects/*/pending/lrn-*.md"):
        out.append(d.stem)
    for d in home.glob("user/pending/lrn-*.md"):
        out.append(d.stem)
    return out


def test_run_lands_candidate(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-e2e", [u("work"), a("found the cause")])
    shim_reader(monkeypatch, {"candidates": [candidate()], "fires": []})
    kicked = []
    monkeypatch.setattr(
        miner.worker, "kick", lambda h, **kw: kicked.append(h) or "spawned"
    )
    result = miner.run(home, trigger="timer")
    assert result.status == "ok"
    assert len(result.landed) == 1
    rid = result.landed[0]
    path = home / "skills/s/pending" / f"{rid}.md"
    assert path.is_file()
    record = Record.from_path(path)
    assert record.source == "session"
    assert record.verified is True
    assert record.evidence[0]["origin"] == "transcript:sess-e2e#L42"
    assert record.evidence[0]["quote"] == "rm -rf .venv fixed it"
    assert kicked  # analyzed before any human sees the card
    entry = miner.read_journal()[-1]
    assert entry["status"] == "ok" and entry["landed"] == 1
    assert entry["trigger"] == "timer"
    assert entry["outcomes"][0]["outcome"] == "landed"
    assert entry["rubric_version"]  # stamped (A3)
    # cursor advanced: a second run with no new lines is idle
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    assert miner.run(home).status == "idle"


def test_run_dedupes_by_origin_across_runs(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-dup", [u("work one")])
    shim_reader(
        monkeypatch, {"candidates": [candidate(session="sess-dup")], "fires": []}
    )
    assert len(miner.run(home).landed) == 1
    write_transcript(transcripts, "sess-dup2", [u("work two")])
    shim_reader(
        monkeypatch, {"candidates": [candidate(session="sess-dup")], "fires": []}
    )
    result = miner.run(home)
    assert result.landed == []
    assert miner.read_journal()[-1]["outcomes"][0]["outcome"] == "skipped-known-origin"
    assert len(pending_ids(home)) == 1


# --------------------------------------------- episode briefs (12 §11 / U18)


def test_episode_brief_lands_in_body_for_session_source(home, transcripts, monkeypatch):
    """m-e (partial, unit-level): a candidate's optional episode_brief
    composes into the landed record's '## Episode brief' body section."""
    brief = "Tried the quick fix first, it broke the build, so we reverted and did it properly."
    write_transcript(transcripts, "sess-brief", [u("work")])
    shim_reader(
        monkeypatch,
        {"candidates": [candidate(session="sess-brief", episode_brief=brief)], "fires": []},
    )
    result = miner.run(home)
    assert len(result.landed) == 1
    record = Record.from_path(home / "skills/s/pending" / f"{result.landed[0]}.md")
    assert record.source == "session"
    assert "## Episode brief" in record.body
    assert brief in record.body


def test_episode_brief_absent_when_not_provided(home, transcripts, monkeypatch):
    """The section is optional — no episode_brief in the candidate means no
    section on the landed record (no-backfill posture: absence is valid)."""
    write_transcript(transcripts, "sess-nobrief", [u("work")])
    shim_reader(
        monkeypatch, {"candidates": [candidate(session="sess-nobrief")], "fires": []}
    )
    result = miner.run(home)
    assert len(result.landed) == 1
    record = Record.from_path(home / "skills/s/pending" / f"{result.landed[0]}.md")
    assert "## Episode brief" not in record.body


def test_teach_sourced_record_never_carries_episode_brief(home):
    """The brief is written ONLY by the miner's _build_record — a
    teach/import-created record (this ledger's create_record path, never
    touching miner.py) has no section, by construction (12 §11)."""
    record = make_behavior()
    create_record(home, record)
    landed = Record.from_path(home / "skills/s/pending" / f"{record.id}.md")
    assert landed.source == "teach"
    assert "## Episode brief" not in landed.body


def test_episode_brief_not_added_on_sighting_append(home, transcripts, monkeypatch):
    """Phase 3 fold path (matched sighting on a pending record) never
    writes or overwrites a brief — only a net-new landing carries one."""
    existing = make_behavior()
    create_record(home, existing)
    write_transcript(transcripts, "sess-fold-brief", [u("hit it again")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-fold-brief",
                    episode_brief="This should never land on the folded record.",
                    match={"record": existing.id, "status": "pending"},
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.folded == [existing.id] and result.landed == []
    refreshed = Record.from_path(home / "skills/s/pending" / f"{existing.id}.md")
    assert "## Episode brief" not in refreshed.body


def test_episode_brief_over_cap_refuses_whole_candidate(home, transcripts, monkeypatch):
    """m-f: a brief over the ≤1200-char ceiling refuses the WHOLE
    candidate (refuse-not-clip) and journals it — never a truncated brief
    on a landed record."""
    write_transcript(transcripts, "sess-overcap", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-overcap", episode_brief="X" * 1300)
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.landed == []
    outcomes = [o["outcome"] for o in miner.read_journal()[-1]["outcomes"]]
    assert "dropped-invalid" in outcomes
    assert pending_ids(home) == []


def test_episode_brief_only_secret_refused_at_landing(home, transcripts, monkeypatch):
    """m-g: the compose-before-scan proof. A secret placed ONLY in the
    episode_brief field (Trigger/Instruction/quote all clean) is still
    caught, because _build_record composes the brief into record.body
    BEFORE _scan_candidate runs — the whole-record scan then walks it as
    ordinary body bytes, no new scan path required."""
    secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6Q7r8"
    write_transcript(transcripts, "sess-brief-secret", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-brief-secret",
                    episode_brief=f"Fixed it by rotating the leaked token {secret} immediately.",
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.landed == []
    assert miner.read_journal()[-1]["outcomes"][0]["outcome"] == "scan-refused"
    assert pending_ids(home) == []


def test_reader_prompt_pins_episode_brief_instruction(home):
    """Live model output cannot be asserted in a unit test — pin the
    prompt TEXT instead (100-200 words, plain-words retell-never-quote
    register, optional-and-omittable framing)."""
    prompt = miner._compose_prompt(home, ["(digest)"], Path("/tmp/out.json"))
    assert '"episode_brief"' in prompt
    assert "100-200 words" in prompt
    assert "RETELL, never quote" in prompt
    assert "optional" in prompt.lower()


def test_fold_into_matching_pending(home, transcripts, monkeypatch):
    existing = make_behavior()
    create_record(home, existing)
    write_transcript(transcripts, "sess-fold", [u("hit it again")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-fold",
                    match={"record": existing.id, "status": "pending"},
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.folded == [existing.id] and result.landed == []
    refreshed = Record.from_path(
        home / "skills/s/pending" / f"{existing.id}.md"
    )
    assert any(
        ev.get("origin") == "transcript:sess-fold#L42" for ev in refreshed.evidence
    )
    assert len(pending_ids(home)) == 1


def _resolve(home, record, status):
    """Move a pending record to resolved/ with the given status."""
    record.set_status(status)
    resolved = home / "skills/s/resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    path = resolved / f"{record.id}.md"
    record.write(path)
    return path


def test_routed_match_becomes_recurrence(home, transcripts, monkeypatch):
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-rec", [u("same mistake again")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-rec", match={"record": routed.id, "status": "routed"}
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.recurrences == [routed.id] and result.landed == []
    events = telemetry.read_events(home)
    suspects = [e for e in events if e.get("kind") == "recurrence-suspect"]
    assert suspects and suspects[-1]["record"] == routed.id
    assert suspects[-1]["basis"] == "miner-match"


def test_rejected_resurfaces_on_third_sighting(home, transcripts, monkeypatch):
    rejected = make_behavior()
    _resolve(home, rejected, "rejected")
    for i in range(3):
        write_transcript(transcripts, f"sess-rej{i}", [u(f"sighting {i}")])
        shim_reader(
            monkeypatch,
            {
                "candidates": [
                    candidate(
                        session=f"sess-rej{i}",
                        line=10 + i,
                        match={"record": rejected.id, "status": "rejected"},
                    )
                ],
                "fires": [],
            },
        )
        result = miner.run(home)
        if i < 2:
            assert result.landed == []
            assert (
                miner.read_journal()[-1]["outcomes"][0]["outcome"]
                == "dropped-rejected"
            )
    assert len(result.landed) == 1  # third sighting resurfaces (§8 Q4)
    outcomes = miner.read_journal()[-1]["outcomes"]
    assert any(o["outcome"] == "resurfaced" for o in outcomes)
    landed = next(o for o in outcomes if o["outcome"] == "landed")
    assert "previously rejected" in landed["why"]
    # …and only once: a fourth sighting stays dropped
    write_transcript(transcripts, "sess-rej3", [u("sighting 3")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-rej3",
                    line=99,
                    match={"record": rejected.id, "status": "rejected"},
                )
            ],
            "fires": [],
        },
    )
    assert miner.run(home).landed == []


def test_invalid_match_claim_demotes_to_landing(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-claim", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-claim",
                    match={"record": "lrn-deadbeef", "status": "pending"},
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    assert outcomes[0]["outcome"] == "match-claim-invalid"
    assert outcomes[1]["outcome"] == "landed"


def test_secret_candidate_refused(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-sec", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-sec",
                    quote="token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6Q7r8",
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.landed == []
    assert miner.read_journal()[-1]["outcomes"][0]["outcome"] == "scan-refused"
    assert pending_ids(home) == []


def test_cap_clips_and_journals(home, transcripts, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    write_transcript(transcripts, "sess-cap", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-cap", line=1),
                candidate(session="sess-cap", line=2, trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    outcomes = [o["outcome"] for o in miner.read_journal()[-1]["outcomes"]]
    assert outcomes.count("dropped-cap") == 1


def test_unknown_skill_scope_dropped(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-scope", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [candidate(session="sess-scope", scope="skill:nonexistent")],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.landed == []
    assert miner.read_journal()[-1]["outcomes"][0]["outcome"] == "dropped-invalid"
    # no phantom bucket was created
    assert not (home / "plugins" / "nonexistent").exists()


def test_fires_spooled_only_for_real_records(home, transcripts, monkeypatch):
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-fire", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "fires": [
                {"record": routed.id, "session": "sess-fire", "line": 3, "outcome": "violated"},
                {"record": "lrn-deadbeef", "session": "sess-fire", "line": 4, "outcome": "complied"},
                {"record": routed.id, "session": "sess-fire", "line": 5, "outcome": "nonsense"},
            ],
        },
    )
    result = miner.run(home)
    assert result.fires == 1
    fires = [e for e in telemetry.read_events(home) if e.get("kind") == "fire"]
    assert len(fires) == 1 and fires[0]["record"] == routed.id
    assert fires[0]["outcome"] == "violated"


def test_failed_reader_keeps_cursors(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-fail", [u("real content")])
    monkeypatch.setattr(miner, "_invoke_reader", lambda *a: None)
    result = miner.run(home)
    assert result.status == "failed"
    assert miner.read_journal()[-1]["status"] == "failed"
    assert len(miner.walk()) == 1  # nothing missed


# --------------------------------------------------- reader containment


def test_reader_argv_and_settings(home, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_MINER_MODEL", "claude-test-model")
    settings = miner.write_reader_settings()
    rules = json.loads(settings.read_text())["permissions"]["allow"]
    assert len(rules) == 1
    assert rules[0].startswith("Edit(/") and rules[0].endswith("/spool/**)")
    assert str(home) not in rules[0]  # repo entirely out of write reach
    argv = miner.build_reader_argv(settings)
    # audit B1: the prompt is NEVER in argv (128 KiB kernel cap) — stdin.
    assert argv[:2] == ["claude", "-p"]
    assert "PROMPT" not in argv
    assert "claude-test-model" in argv
    # injection hardening: the reader gets NO filesystem tools at all —
    # its whole evidence base is in the prompt.
    assert "--allowedTools" not in argv
    j = argv.index("--disallowedTools")
    for tool in ("Bash", "Edit", "Read", "Grep", "Glob", "WebFetch"):
        assert tool in argv[j + 1]


def test_reader_survives_oversize_prompt(home, tmp_path, monkeypatch):
    """Audit B1 regression: a >128 KiB prompt must reach the reader (via
    stdin) instead of crashing exec with E2BIG — exercised through the
    REAL exec path with a PATH shim."""
    shims = tmp_path / "shims-big"
    shims.mkdir()
    spool = miner.spool_dir()
    got = tmp_path / "got-prompt"
    shim = shims / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'cat > "{got}"\n'
        f'echo \'{{"candidates": [], "fires": []}}\' > "{spool}/{miner.OUTPUT_BASENAME}"\n'
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}:/usr/bin")
    big_prompt = "X" * 300_000  # > the 131072-byte argv limit
    out = miner._invoke_reader(home, big_prompt)
    assert out is not None and out.is_file()
    assert got.stat().st_size == 300_000


def test_artifact_contract_sweeps_strays(home, tmp_path, monkeypatch):
    shims = tmp_path / "shims"
    shims.mkdir()
    spool = miner.spool_dir()
    shim = shims / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "cat > /dev/null\n"  # consume the stdin prompt
        f'echo stray > "{spool}/litter.txt"\n'
        f'echo \'{{"candidates": [], "fires": []}}\' > "{spool}/{miner.OUTPUT_BASENAME}"\n'
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}:{Path('/usr/bin')}")
    out = miner._invoke_reader(home, "PROMPT")
    assert out is not None and out.is_file()
    assert not (spool / "litter.txt").exists()


# ----------------------------------------------------------- watchdog


def test_maybe_kick_disabled_fresh_spawned(home, monkeypatch):
    assert miner.maybe_kick(home) == "disabled"  # conftest sets AUTOKICK=0
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "1")
    spawned = []
    monkeypatch.setattr(
        miner, "_spawn_run", lambda h, **kw: spawned.append(h) or 4242
    )
    assert miner.maybe_kick(home) == "spawned"  # no last-run = infinitely old
    assert spawned == [home]
    (miner.miner_dir() / "miner.last-run").touch()
    assert miner.maybe_kick(home) == "fresh"
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    assert miner.maybe_kick(home) == "disabled"


def test_stale_predicate(home, monkeypatch):
    assert miner.stale() is True  # never ran = alarm (self-healing via kick)
    (miner.miner_dir() / "miner.last-run").touch()
    assert miner.stale() is False
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    assert miner.stale() is False  # deliberately disabled never alarms


# ------------------------------------------------------------ CLI surface


def test_status_fast_carries_miner_keys(home, capsys):
    assert cli.main(["status", "--fast"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["miner_last_run"] is None
    assert data["miner_stale"] is True


def test_cli_mine_run_and_status(home, transcripts, monkeypatch, capsys):
    write_transcript(transcripts, "sess-cli", [u("work")])
    shim_reader(monkeypatch, {"candidates": [candidate(session="sess-cli")], "fires": []})
    monkeypatch.setattr(miner.worker, "kick", lambda h, **kw: "disabled")
    assert cli.main(["mine", "run", "--trigger", "timer"]) == 0
    out = capsys.readouterr().out
    assert "mine run: ok — 1 landed" in out
    assert cli.main(["mine", "status"]) == 0
    out = capsys.readouterr().out
    assert "landed=1" in out and "trigger=timer" in out
    assert cli.main(["mine", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["runs"][-1]["status"] == "ok"
    assert data["stale"] is False


# ------------------------------------------------------- report (T-M5)


def test_report_tracks_mined_supply(home, transcripts, monkeypatch, capsys):
    from self_learn import report

    write_transcript(transcripts, "sess-rep", [u("work")])
    shim_reader(monkeypatch, {"candidates": [candidate(session="sess-rep")], "fires": []})
    monkeypatch.setattr(miner.worker, "kick", lambda h, **kw: "disabled")
    rid = miner.run(home).landed[0]
    facts = report.gather(home)
    assert facts["mined"]["pending"] == 1
    assert facts["mined"]["adjudicated"] == 0
    assert facts["mined"]["accept_rate"] is None  # honesty: none adjudicated
    # adjudicate it: mark routed, accept rate becomes 1.0
    path = home / "skills/s/pending" / f"{rid}.md"
    record = Record.from_path(path)
    record.set_status("routed")
    resolved = path.parent.parent / "resolved"
    resolved.mkdir(exist_ok=True)
    record.write(resolved / path.name)
    path.unlink()
    facts = report.gather(home)
    assert facts["mined"]["routed"] == 1
    assert facts["mined"]["accept_rate"] == 1.0
    text = report.render_text(facts)
    assert "Mined supply (transcript miner)" in text


# ----------------------------------------- audit-fix regressions (round 1)


def test_first_run_initializes_forward_only(home, transcripts, monkeypatch):
    """Audit B2: night one seeds cursors at EOF and mines NOTHING; history
    is reachable only via --since. A pre-existing file containing
    self-learn machinery markers is halted outright."""
    miner._save_cursors({})  # fresh machine: not initialized
    write_transcript(transcripts, "sess-history", [u("old lesson-rich work")])
    write_transcript(
        transcripts,
        "sess-live-review",
        [u("work"), u("<command-name>/self-learn:review</command-name> go")],
    )
    called = []
    monkeypatch.setattr(miner, "_invoke_reader", lambda *a: called.append(1))
    result = miner.run(home)
    assert result.status == "initialized"
    assert not called  # nothing mined
    assert miner.read_journal()[-1]["status"] == "initialized"
    assert miner.read_journal()[-1]["files_seeded"] == 2
    assert miner.initialized()
    # in-flight review session halted even though its cursor was seeded
    cursors = miner._load_cursors()
    halted = [k for k, v in cursors.items() if isinstance(v, dict) and v.get("halt")]
    assert any("sess-live-review" in k for k in halted)
    # second run: nothing new → idle, history untouched
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    assert miner.run(home).status == "idle"
    # new appends after initialization ARE mined
    with open(transcripts / "-home-u-proj" / "sess-history.jsonl", "a") as fh:
        fh.write(u("fresh correction after init") + "\n")
    spy = {}

    def fake(h, prompt):
        spy["prompt"] = prompt
        out = miner.spool_dir() / miner.OUTPUT_BASENAME
        out.write_text(json.dumps({"candidates": [], "fires": []}))
        return out

    monkeypatch.setattr(miner, "_invoke_reader", fake)
    assert miner.run(home).status == "ok"
    assert "fresh correction after init" in spy["prompt"]
    assert "old lesson-rich work" not in spy["prompt"]


def test_torn_trailing_line_left_for_next_run(transcripts):
    p = transcripts / "-home-u-proj" / "sess-torn.jsonl"
    p.write_text(u("complete line") + "\n" + '{"type":"user","mes', encoding="utf-8")
    slices = miner.walk()
    assert len(slices) == 1 and len(slices[0].lines) == 1
    miner._advance_cursors([(slices[0], False)])
    # the torn tail completes later
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('sage":{"role":"user","content":"finished now"}}\n')
    slices = miner.walk()
    assert len(slices) == 1
    assert slices[0].start_line == 1  # the once-torn line is NOW read
    assert "finished now" in slices[0].lines[0]


def test_walk_skips_unchanged_files_without_reading(transcripts, monkeypatch):
    p = write_transcript(transcripts, "sess-skip", [u("one")])
    slices = miner.walk()
    miner._advance_cursors([(s, False) for s in slices])
    reads = []
    real = miner._complete_lines
    monkeypatch.setattr(
        miner, "_complete_lines", lambda path: reads.append(path) or real(path)
    )
    assert miner.walk() == []
    assert reads == []  # size unchanged → no I/O
    assert p.is_file()


def test_watchdog_cooldown_after_failed_attempt(home, transcripts, monkeypatch):
    """Audit M1/M4: a failing reader must not turn every CLI invocation
    into a fresh mining attempt — attempts have their own 2h cool-down."""
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "1")
    write_transcript(transcripts, "sess-cool", [u("work")])
    monkeypatch.setattr(miner, "_invoke_reader", lambda *a: None)  # reader broken
    assert miner.run(home).status == "failed"
    assert not (miner.miner_dir() / "miner.last-run").is_file()  # alarm intact
    spawned = []
    monkeypatch.setattr(miner, "_spawn_run", lambda h, **kw: spawned.append(h) or 1)
    assert miner.maybe_kick(home) == "cooling"  # attempt marker is fresh
    assert spawned == []
    # once the cool-down passes, the watchdog may retry
    old = time.time() - miner.ATTEMPT_COOLDOWN_SECS - 60
    os.utime(miner.miner_dir() / "miner.last-attempt", (old, old))
    assert miner.maybe_kick(home) == "spawned"


def test_resurface_not_killed_by_cap(home, transcripts, monkeypatch):
    """Audit M1 (code): reaching the resurface threshold in a run whose
    cap is exhausted must NOT permanently mark the rejected id landed."""
    rejected = make_behavior()
    _resolve(home, rejected, "rejected")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    # two prior sightings on the counter
    for i in range(2):
        miner._rejected_counter_bump(rejected.id, f"transcript:seed#L{i}")
    write_transcript(transcripts, "sess-rescap", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                # cap-eater lands first
                candidate(session="sess-rescap", line=1,
                          trigger="Unrelated first candidate trigger"),
                # third sighting arrives with the cap already consumed
                candidate(session="sess-rescap", line=2,
                          match={"record": rejected.id, "status": "rejected"}),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1  # only the cap-eater
    outcomes = [o["outcome"] for o in miner.read_journal()[-1]["outcomes"]]
    assert "dropped-cap" in outcomes
    # the pathway is NOT dead: next run (cap free) lands the resurfaced one
    write_transcript(transcripts, "sess-rescap2", [u("more work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-rescap2", line=3,
                          match={"record": rejected.id, "status": "rejected"})
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1
    assert any(
        o["outcome"] == "resurfaced" for o in miner.read_journal()[-1]["outcomes"]
    )


def test_fire_and_recurrence_replays_deduped(home, transcripts, monkeypatch):
    """Audit M2: --since replays and crash-replays must not duplicate
    fire / recurrence-suspect telemetry."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-replay", [u("work")])
    payload = {
        "candidates": [
            candidate(session="sess-replay", line=7,
                      match={"record": routed.id, "status": "routed"})
        ],
        "fires": [
            {"record": routed.id, "session": "sess-replay", "line": 9,
             "outcome": "violated"}
        ],
    }
    shim_reader(monkeypatch, payload)
    assert miner.run(home).status == "ok"
    # flush so read_events sees them, then replay the same session
    telemetry.flush(home)
    shim_reader(monkeypatch, payload)
    result = miner.run(home, since="2020-01-01")
    assert result.recurrences == [] and result.fires == 0
    events = telemetry.read_events(home)
    assert len([e for e in events if e.get("kind") == "fire"]) == 1
    assert len([e for e in events if e.get("kind") == "recurrence-suspect"]) == 1


def test_bad_session_ref_and_oversize_fields_dropped(home, transcripts, monkeypatch):
    """Audit M3: model-authored session/line are validated (they build the
    origin that lands in tracked files + telemetry); oversize fields are
    refused, oversize quotes dropped."""
    write_transcript(transcripts, "sess-val", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="ghp_secretlooking token !!", line=1),
                candidate(session="sess-val", line="not-an-int"),
                candidate(session="sess-val", line=2,
                          trigger="T" * 2000),  # over MAX_FIELD_CHARS
                candidate(session="sess-val", line=3,
                          quote="Q" * 1000),  # quote dropped, candidate lands
            ],
            "fires": [
                {"record": "lrn-deadbeef", "session": "x y z", "line": 1,
                 "outcome": "violated"}
            ],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1
    outcomes = [o["outcome"] for o in miner.read_journal()[-1]["outcomes"]]
    assert outcomes.count("dropped-invalid") == 3  # 2 bad refs + 1 oversize field
    assert "quote-dropped-overlength" in outcomes
    rid = result.landed[0]
    for bucket_dir in home.glob("skills/*/pending"):
        path = bucket_dir / f"{rid}.md"
        if path.is_file():
            record = Record.from_path(path)
            assert all("quote" not in ev for ev in record.evidence)


def test_bad_kind_dropped_not_coerced(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-kind", [u("work")])
    shim_reader(
        monkeypatch,
        {"candidates": [candidate(session="sess-kind", kind="brilliant-idea")],
         "fires": []},
    )
    result = miner.run(home)
    assert result.landed == []
    assert miner.read_journal()[-1]["outcomes"][0]["outcome"] == "dropped-invalid"


def test_fold_bumps_sightings(home, transcripts, monkeypatch):
    existing = make_behavior()
    create_record(home, existing)
    write_transcript(transcripts, "sess-sigh", [u("again")])
    shim_reader(
        monkeypatch,
        {"candidates": [candidate(session="sess-sigh",
                                  match={"record": existing.id, "status": "pending"})],
         "fires": []},
    )
    miner.run(home)
    refreshed = Record.from_path(
        home / "skills/s/pending" / f"{existing.id}.md"
    )
    assert refreshed.sightings == 2


def test_crash_mid_run_still_journals(home, transcripts, monkeypatch):
    """Audit B1 (journal half): ANY unhandled error inside the run must
    leave a failed journal entry, never vanish."""
    write_transcript(transcripts, "sess-crash", [u("work")])
    def boom(*a, **k):
        raise RuntimeError("synthetic mid-run crash")
    monkeypatch.setattr(miner, "_compose_prompt", boom)
    result = miner.run(home)
    assert result.status == "failed"
    entry = miner.read_journal()[-1]
    assert entry["status"] == "failed" and "synthetic mid-run crash" in entry["reason"]
