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

from self_learn import cli, intents, miner, telemetry
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
    prompt, corrupt = miner._compose_prompt(home, ["(digest)"], Path("/tmp/out.json"))
    assert corrupt == []
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


# U-cleanup-B DELETE (§8.4a: "test_hosting.py, test_miner.py:746 and
# test_lock_invariant.py:148 cannot be migrated: their subject -- that a
# settings file is written to a particular place -- is deleted"):
# `test_reader_argv_and_settings` drove `miner.write_reader_settings` and
# `miner.build_reader_argv`, both deleted (§8.1/§8.3) -- the reader round
# has no argv and no on-disk settings file any more (`options_kwargs(spec)`
# feeds the sdk seam directly, `settings=None`). Every guarantee this test
# checked survives elsewhere against the real sdk transport:
#   - allow-rule scoped to .../spool/**, repo out of write reach ->
#     test_reader_contract.py::test_ct2_options_kwargs_matches_c_c_table_
#     and_key_set, test_ct4_write_to_spool_artifact_allowed_lands_on_disk,
#     test_ct5_write_outside_spool_denied_two_targets
#   - defaultMode "default" (the security hotfix) ->
#     test_reader_contract.py::test_ct2 (settings=None pins the same
#     default-mode contract at the containment layer)
#   - no filesystem tools reach the model (Bash/Edit/Read/Grep/Glob/
#     WebFetch denied) ->
#     test_reader_contract.py::test_ct6_read_grep_glob_denied_with_step1_
#     wording, test_ct5, test_ct8_hatch_permanently_closed_even_with_
#     enforce_scope_unset
#   - prompt never in argv, always on stdin (audit B1) ->
#     test_reader_contract.py::test_rc7_prompt_reaches_the_model_on_
#     stdin_never_argv
#   - no dead settings file survives under the cache dir ->
#     test_reader_contract.py::test_rc8_no_dead_settings_write_under_
#     the_cache_dir


# U-cleanup-B DELETE (code gate r1, NIT-6): `test_reader_survives_
# oversize_prompt` -- left `@pytest.mark.skip`ped by Phase A with no
# further disposition, per A's inherit list. Its subject (E2BIG-via-
# argv on a >128KiB prompt) is a `CliBackend` transport-mechanics
# concern that cannot recur under `SdkBackend` -- the prompt never
# touches argv/exec at all -- and its own skip reason already named
# the replacement: `test_reader_contract.py::test_rc7_prompt_reaches_
# the_model_on_stdin_never_argv` (200KiB, spies the real wire + the
# real child's argv log). This was also the suite's LAST surviving
# FUNCTIONAL inline bash `claude` shim -- one whose script actually
# answers on the model's behalf (writes an `OUTPUT_BASENAME` payload)
# rather than existing purely as a PATH-hygiene negative control.
# `test_reader_contract.py::_shadow_claude` still writes a decoy to a
# `shims/claude` path -- deliberately, per its own docstring: it
# exits 1 and answers nothing, a tripwire for "this leg should never
# reach here", not a functioning fake CLI. That one is not this NIT's
# subject and stays.


def test_artifact_contract_sweeps_strays(home, tmp_path, monkeypatch):
    spool = miner.spool_dir()
    # U-cleanup-A: sdk-backed replacement for the bash `claude` PATH shim
    # -- `fake_claude.py`'s `shim_script` scenario interprets these SAME
    # `echo CONTENT > path` lines via its `_ECHO_RE` idiom (bare,
    # unquoted paths -- no spaces in a pytest tmp_path, matching every
    # other write idiom this interpreter already supports).
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    monkeypatch.setenv(
        "SELF_LEARN_SDK_CLI_PATH",
        str(Path(__file__).parent / "fixtures" / "fake_claude.py"),
    )
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "shim_script")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"echo stray > {spool}/litter.txt\n"
        f'echo \'{{"candidates": [], "fires": []}}\' > {spool}/{miner.OUTPUT_BASENAME}\n',
    )
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


# ---------------------------------------- cursor hold (U-cursorhold, FW-73)
#
# Rule-H (spec §3.1): a cap-dropped candidate holds its originating
# session's cursor UNLESS that slice is halted (M-5 wins) or unmatched
# (the reader never actually saw that session's text this run).


def test_A1_cap_drop_holds_cursor_clean_session_advances(home, transcripts, monkeypatch):
    """A1: a cap-dropped candidate holds its session's cursor; a clean
    session in the SAME run does not. Both env pins are required — cap_for
    scales with len(digests), so a per-session cap of 1 over two sessions
    is a cap of 2 without SELF_LEARN_MINE_CAP_MAX=1 too."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-cap", [u("work")])
    write_transcript(transcripts, "sess-clean", [u("other work")])
    pre = miner.walk()
    pre_cap_start = next(s.start_line for s in pre if s.session_id == "sess-cap")
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-cap", line=1),
                candidate(session="sess-cap", line=2,
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_drop = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_drop["cursor"] == "held"
    after = miner.walk()
    held = [s for s in after if s.session_id == "sess-cap"]
    assert len(held) == 1 and held[0].start_line == pre_cap_start  # never written
    assert not any(s.session_id == "sess-clean" for s in after)  # advanced


def test_A2_scan_refused_and_invalid_drops_do_not_hold(home, transcripts, monkeypatch):
    """A2: no over-hold. scan-refused and dropped-invalid are decisions
    about the CANDIDATE, not the run — a re-read reproduces them
    identically, so holding on them is an infinite loop with no possible
    progress (§7.1). Neither session's cursor is held."""
    write_transcript(transcripts, "sess-scan", [u("work")])
    write_transcript(transcripts, "sess-inv", [u("more work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-scan",
                    quote="token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6Q7r8",
                ),
                candidate(session="sess-inv", line=1, kind="not-a-real-kind"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    outcomes = [o["outcome"] for o in miner.read_journal()[-1]["outcomes"]]
    assert "scan-refused" in outcomes
    assert "dropped-invalid" in outcomes
    assert result.held_sessions == set()
    assert miner.walk() == []  # both sessions advanced normally


def test_A3_multi_candidate_session_held_once_replayed_without_double_landing(
    home, transcripts, monkeypatch
):
    """A3: modelled on the measured run 28117725. One session, cap 1,
    three distinct candidates: 1 lands, 2 dropped-cap, session held. Raise
    the cap and replay the IDENTICAL payload: the landed origin dedups,
    both previously-capped candidates land, and the ledger ends with
    exactly three pending records with distinct ids."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-multi", [u("work")])
    payload = {
        "candidates": [
            candidate(session="sess-multi", line=1),
            candidate(session="sess-multi", line=2,
                      trigger="Second distinct trigger about rsync"),
            candidate(session="sess-multi", line=3,
                      trigger="Third distinct trigger about tar"),
        ],
        "fires": [],
    }
    shim_reader(monkeypatch, payload)
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 2  # C3: held drops still count
    outcomes = miner.read_journal()[-1]["outcomes"]
    held_outcomes = [o for o in outcomes if o["outcome"] == "dropped-cap"]
    assert len(held_outcomes) == 2
    assert all(o["cursor"] == "held" for o in held_outcomes)
    first_origin = next(o["origin"] for o in outcomes if o["outcome"] == "landed")

    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "5")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "10")
    shim_reader(monkeypatch, payload)  # the IDENTICAL payload, replayed
    miner.run(home)
    outcomes2 = miner.read_journal()[-1]["outcomes"]
    names2 = [o["outcome"] for o in outcomes2]
    assert names2.count("skipped-known-origin") == 1
    assert names2.count("landed") == 2
    dedup = next(o for o in outcomes2 if o["outcome"] == "skipped-known-origin")
    assert dedup["origin"] == first_origin

    ids = pending_ids(home)
    assert len(ids) == 3 and len(set(ids)) == 3
    records = [
        Record.from_path(p)
        for p in list(home.glob("skills/*/pending/lrn-*.md"))
        + list(home.glob("projects/*/pending/lrn-*.md"))
        + list(home.glob("user/pending/lrn-*.md"))
    ]
    carriers = [r for r in records if any(e.get("origin") == first_origin for e in r.evidence)]
    assert len(carriers) == 1


def test_A4_hold_touches_advance_only_never_canary_scoring(home, transcripts, monkeypatch):
    """A4: the H-3 filter touches `_advance_cursors` only. Canary scoring
    (`:1926`) keeps the FULL `processed` set — a held session was still
    mined this run, so its canary scores `missed`, not left `open`."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-canary-hold")
    miner.plant_canary("prefer editing files over rewriting them whole")
    write_transcript(transcripts, "sess-eater", [u("eater work")])
    write_transcript(
        transcripts, "sess-canary-hold", [u("unrelated content about pizza")]
    )
    captured = {}
    real_score = miner._score_canaries

    def spy(home_, record_ids, mined_session_ids):
        captured["mined_session_ids"] = set(mined_session_ids)
        return real_score(home_, record_ids, mined_session_ids)

    monkeypatch.setattr(miner, "_score_canaries", spy)
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-eater", line=1),
                candidate(session="sess-canary-hold", line=1,
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.held_sessions == {"sess-canary-hold"}
    assert "sess-canary-hold" in captured["mined_session_ids"]  # unfiltered `processed`
    summary = miner.read_canaries_summary()
    assert summary["missed"] == 1
    assert summary["caught"] == 0


def test_A5_halted_slice_advances_and_stays_halted(home, transcripts, monkeypatch):
    """A5: M-5 wins. A cap-dropped candidate from an ALREADY-halted slice
    advances with its halt persisted, unconditionally — the halted case is
    a declared residual (§7.2-R2), journaled visibly as `advanced-halted`,
    never silently deferred to a re-derivation this unit isn't entitled
    to rely on."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    p = write_transcript(
        transcripts, "sess-halt",
        [
            u("work turn one"),
            u("work turn two"),
            u("<command-name>/self-learn:review</command-name> go"),
        ],
    )
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-halt", line=1),
                candidate(session="sess-halt", line=2,
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_drop = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_drop["cursor"] == "advanced-halted"
    assert result.held_sessions == set()
    assert miner._load_cursors()[str(p)]["halt"] is True
    assert miner.walk() == []  # the halted file is skipped, not re-offered


def test_A6i_fabricated_session_holds_nothing(home, transcripts, monkeypatch):
    """A6 leg (i): a cap-dropped candidate citing a session id no
    transcript has holds nothing — there is nothing to hold."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-real", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-real", line=1),
                candidate(session="sess-ghost", line=1,
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_drop = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_drop["cursor"] == "advanced-unmatched"
    assert result.held_sessions == set()


def test_A6ii_excluded_session_holds_nothing_and_still_advances(
    home, transcripts, monkeypatch
):
    """A6 leg (ii): a cap-dropped candidate citing a REAL transcript that
    produced no digest (entered `processed` but never `digested`) also
    holds nothing, and that transcript's cursor still advances to its
    end. This is the leg M6 (building `digested` from all of `processed`)
    reddens."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-real", [u("work")])
    p_tool = write_transcript(
        transcripts, "sess-toolonly", [tool("Bash", "ls", "t1")]
    )
    assert miner.digest_transcript(slice_of(p_tool)) == (None, False)  # sanity
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-real", line=1),
                candidate(session="sess-toolonly", line=1,
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_drop = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_drop["cursor"] == "advanced-unmatched"
    assert result.held_sessions == set()
    assert miner.walk() == []  # both sessions' cursors advanced


def test_A7_hold_writes_nothing_absent_and_present_cases(home, transcripts, monkeypatch):
    """A7: a hold writes NOTHING for that transcript — the cursors file
    entry is byte-identical to what it was before the run, whether that
    entry was absent (first read) or present (a prior partial read),
    while a second, non-held session in the same run IS written."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    p_pre = write_transcript(transcripts, "sess-cap-pre", [u("first turn")])
    pre_slices = miner.walk()
    miner._advance_cursors([(s, False) for s in pre_slices])
    with open(p_pre, "a", encoding="utf-8") as fh:
        fh.write(u("second turn") + "\n")
    before = json.loads(miner._cursors_path().read_text(encoding="utf-8"))
    assert str(p_pre) in before  # present case: a pre-existing entry

    p_fresh = write_transcript(transcripts, "sess-cap-fresh", [u("fresh work")])
    p_land = write_transcript(transcripts, "sess-land-a7", [u("landing work")])

    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-land-a7", line=1),
                candidate(session="sess-cap-pre", line=2,
                          trigger="Second distinct trigger about rsync"),
                candidate(session="sess-cap-fresh", line=1,
                          trigger="Third distinct trigger about tar"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 2

    after = json.loads(miner._cursors_path().read_text(encoding="utf-8"))
    assert after[str(p_pre)] == before[str(p_pre)]  # present: byte-identical
    assert str(p_fresh) not in after  # absent: stays absent
    assert str(p_land) in after  # non-held: written


def test_A8_no_model_authored_value_reaches_cursor(home, transcripts, monkeypatch):
    """A8: a cap-dropped candidate's `line` is model-authored and must
    never steer a cursor. A candidate carrying `line: 1` from a session
    whose slice starts far beyond line 1 changes nothing: the held
    entry stays exactly as it was, and the NEXT run's slice starts at the
    same place — never 0, never `line - 1`."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    p = write_transcript(
        transcripts, "sess-inject",
        [u("turn one"), u("turn two"), u("turn three")],
    )
    first = miner.walk()
    s0 = first[0]
    s0.lines = s0.lines[:2]  # simulate a prior run that advanced 2 lines
    miner._advance_cursors([(s0, False)])
    assert miner._load_cursors()[str(p)]["lines"] == 2
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(u("turn four") + "\n")
    pre_run_slices = miner.walk()
    pre_start = next(s.start_line for s in pre_run_slices if s.path == p)
    assert pre_start == 2 and pre_start != 0

    write_transcript(transcripts, "sess-inject-other", [u("other work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-inject-other", line=1),
                candidate(session="sess-inject", line=1,  # model-authored, fabricated
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    assert miner._load_cursors()[str(p)]["lines"] == 2  # unchanged (A7)
    next_slice = next(s for s in miner.walk() if s.path == p)
    assert next_slice.start_line == pre_start  # never 0, never line-1 (== 0 here too)


def test_A9_aliasing_never_costs_a_halt(home, transcripts, monkeypatch):
    """A9: the corner H-3's `and not halt` half exists for. Two
    transcripts share a stem under different project directories; the
    halted twin must sort EARLIER by mtime (pinned with os.utime) so
    `digested["sess-dup"]` ends up False (the unhalted twin's flag,
    last-writer-wins) and the drop classifies `held`. Even so, the
    halted twin still advances and still persists its halt — M20
    (session-id-only filtering) is the mutation this guards against."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-plain", [u("plain work")])
    p_halted = write_transcript(
        transcripts, "sess-dup",
        [u("proj work"), u("<command-name>/self-learn:review</command-name> go")],
        project="-home-u-proj",
    )
    (transcripts / "-home-u-other").mkdir()  # write_transcript does not
    p_unhalted = write_transcript(
        transcripts, "sess-dup", [u("other project work")],
        project="-home-u-other",
    )
    old = time.time() - 100
    os.utime(p_halted, (old, old))  # vacuity guard: halted twin sorts first
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-plain", line=1),
                candidate(session="sess-dup", line=1,
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_drop = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_drop["cursor"] == "held"
    cursors = miner._load_cursors()
    assert cursors[str(p_halted)]["halt"] is True
    remaining = {s.path for s in miner.walk()}
    assert p_halted not in remaining
    assert p_unhalted in remaining  # the aliasing cost: an unhalted re-read, never an exclusion


_A10_OVERLENGTH_WHY_DURABLE = (
    "This candidate exists to model the exact drained scenario measured "
    "in the run journal, where a single session produced far more "
    "distinct lessons than the per run landing cap could ever absorb in "
    "one pass, and the fourth of those dropped candidates carried a "
    "snippet so long that the near miss surface itself refused to keep "
    "any content at all, leaving only a bare overlength marker behind "
    "for a human reviewer to see, which is precisely why holding that "
    "candidate cursor is the only path back to it, since the near miss "
    "promote button had genuinely nothing else to offer this session."
)


def test_A10_measured_incident_drained_over_consecutive_runs(
    home, transcripts, monkeypatch
):
    """A10: the run-28117725 shape, drained over three consecutive
    capping runs at a cap that is never raised. The third candidate's
    snippet sums past MAX_NEARMISS_SNIPPET_CHARS (scan-clean PROSE, never
    repeated filler — the cap branch `continue`s before `_scan_candidate`,
    so this candidate meets the scanner for the first time on the run
    that lands it), scoring `promotable: false` — the one drop with no
    other recovery path."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-drain", [u("work")])
    payload = {
        "candidates": [
            candidate(session="sess-drain", line=1),
            candidate(session="sess-drain", line=2,
                      trigger="Second distinct trigger about rsync"),
            candidate(
                session="sess-drain", line=3,
                trigger="Third distinct trigger about a very long overlength snippet",
                why_durable=_A10_OVERLENGTH_WHY_DURABLE,
            ),
        ],
        "fires": [],
    }

    # --- run 1: one lands, two hold (including the non-promotable one)
    shim_reader(monkeypatch, payload)
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 2
    entry = miner.read_journal()[-1]
    assert entry["cursors_held"] == 1
    cap_drops = [o for o in entry["outcomes"] if o["outcome"] == "dropped-cap"]
    assert len(cap_drops) == 2
    assert all(o["cursor"] == "held" for o in cap_drops)
    overlength = next(o for o in cap_drops if o["snippet"] == {"overlength": True})
    assert overlength["promotable"] is False

    # --- run 2: the run-1 origin dedups (doesn't consume cap), the second
    # candidate lands (a deduped candidate never consumes cap, §3.4), the
    # overlength one drops again and the session is still held
    shim_reader(monkeypatch, payload)
    result2 = miner.run(home)
    outcomes2 = miner.read_journal()[-1]["outcomes"]
    names2 = [o["outcome"] for o in outcomes2]
    assert names2.count("skipped-known-origin") == 1
    assert names2.count("landed") == 1
    cap_drop2 = next(o for o in outcomes2 if o["outcome"] == "dropped-cap")
    assert cap_drop2["snippet"] == {"overlength": True}
    assert cap_drop2["cursor"] == "held"
    assert result2.held_sessions == {"sess-drain"}

    # --- run 3: both earlier origins dedup, the overlength candidate
    # finally lands, nothing drops, and the session's cursor advances
    shim_reader(monkeypatch, payload)
    result3 = miner.run(home)
    outcomes3 = miner.read_journal()[-1]["outcomes"]
    names3 = [o["outcome"] for o in outcomes3]
    assert names3.count("skipped-known-origin") == 2
    assert names3.count("landed") == 1
    assert "dropped-cap" not in names3
    assert result3.held_sessions == set()
    assert miner.walk() == []


def test_B1_cursor_present_complete_and_enumerated(home, transcripts, monkeypatch):
    """B1: (i) every `dropped-cap` outcome carries `cursor`, (ii) its
    value is always one of the three literals, (iii) no outcome of any
    other name carries the key, (iv) all three values are observed in
    ONE run — a single fixture, never a module-level accumulator that
    degrades silently under `-k`/`-x`/a solo re-run (NOTE 2)."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-land-b1", [u("land work")])
    write_transcript(transcripts, "sess-hold-b1", [u("hold work")])
    write_transcript(
        transcripts, "sess-halt-b1",
        [u("halt work"), u("<command-name>/self-learn:review</command-name> go")],
    )
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-land-b1", line=1),
                candidate(session="sess-hold-b1", line=1,
                          trigger="Second distinct trigger about rsync"),
                candidate(session="sess-halt-b1", line=1,
                          trigger="Third distinct trigger about tar"),
                candidate(session="sess-ghost-b1", line=1,
                          trigger="Fourth distinct trigger about zip"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 3
    entry = miner.read_journal()[-1]
    assert entry["cursors_held"] == 1
    outcomes = entry["outcomes"]
    for o in outcomes:
        if o["outcome"] == "dropped-cap":
            assert o["cursor"] in {"held", "advanced-halted", "advanced-unmatched"}
        else:
            assert "cursor" not in o  # (iii): no other outcome carries the key
    cap_outcomes = [o for o in outcomes if o["outcome"] == "dropped-cap"]
    assert len(cap_outcomes) == 3
    assert {o["cursor"] for o in cap_outcomes} == {
        "held", "advanced-halted", "advanced-unmatched",
    }  # (iv): all three, one run


def test_B2_cursors_held_counts_distinct_sessions(home, transcripts, monkeypatch):
    """B2: `cursors_held` counts distinct SESSIONS, not drops. The
    asymmetric fixture (2 drops from one session, 1 from another) is
    mandatory — with one drop per session the two numbers would agree
    and the criterion would be vacuous."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_MAX", "1")
    write_transcript(transcripts, "sess-eater-b2", [u("eater work")])
    write_transcript(transcripts, "sess-two-drops-b2", [u("two drops work")])
    write_transcript(transcripts, "sess-one-drop-b2", [u("one drop work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-eater-b2", line=1),
                candidate(session="sess-two-drops-b2", line=1,
                          trigger="Second distinct trigger about rsync"),
                candidate(session="sess-two-drops-b2", line=2,
                          trigger="Third distinct trigger about tar"),
                candidate(session="sess-one-drop-b2", line=1,
                          trigger="Fourth distinct trigger about zip"),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.dropped == 3
    entry = miner.read_journal()[-1]
    assert entry["cursors_held"] == 2


def test_B3i_cli_surface_byte_identical_with_cursor_present(
    home, transcripts, monkeypatch
):
    """B3 leg (i): the CLI surface is byte-identical — outcome name,
    disposition, reason and promotable are exactly what they were before
    this unit; `cursor` is the ONE addition."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    write_transcript(transcripts, "sess-b3", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-b3", line=1),
                candidate(session="sess-b3", line=2,
                          trigger="Second distinct trigger about rsync"),
            ],
            "fires": [],
        },
    )
    miner.run(home)
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_drop = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_drop["outcome"] == "dropped-cap"
    assert cap_drop["disposition"] == "cap-refused"
    assert (
        cap_drop["reason"]
        == "a real lesson, but this run had already landed its cap"
    )
    assert cap_drop["promotable"] is True
    assert cap_drop["cursor"] == "held"


def test_B3iii_mine_status_one_liner_unchanged(home, transcripts, monkeypatch, capsys):
    """B3 leg (iii): `mine status`'s one-liner is unchanged — it still
    carries `cap=`/`near-misses=` and gains no held count (BD4: the
    per-candidate `cursor` value already renders through the extras
    dict on its own line, so the aggregate would be redundant)."""
    write_transcript(transcripts, "sess-b3-cli", [u("work")])
    shim_reader(monkeypatch, {"candidates": [candidate(session="sess-b3-cli")], "fires": []})
    monkeypatch.setattr(miner.worker, "kick", lambda h, **kw: "disabled")
    assert cli.main(["mine", "run"]) == 0
    capsys.readouterr()
    assert cli.main(["mine", "status"]) == 0
    lines = capsys.readouterr().out.splitlines()
    summary_line = next(ln for ln in lines if "cap=" in ln)
    assert "near-misses=" in summary_line
    assert "held=" not in summary_line
    assert "cursors_held" not in summary_line


def test_fire_and_recurrence_replays_deduped(home, transcripts, monkeypatch):
    """Audit M2: --since replays and crash-replays must not duplicate
    fire / recurrence-suspect telemetry.

    AC9: the candidate-match (origin L7) and the violated fire (origin
    L9) are TWO distinct sightings on the same routed record — under
    U-recur that is legitimately two recurrence-suspect events, not one.
    This is a contract update, not a test bent to fit (spec §2.4): the
    replay half below (result.recurrences == [], exactly one fresh
    `fire`) is untouched — it is the pre-existing proof that cross-run
    dedupe still works.

    Disclosed collateral (code-gate review): this test's payload carries
    a live crossover, so M4 (the naive per-record guard in the shared
    helper) and M5 (deleting that helper's key guard) also turn this
    test red — M4 because the candidate-match's own `result.recurrences`
    append blocks the crossover's later call for the same record id; M5
    because THE BACKFILL's replay-run call to the same shared helper then
    re-raises and re-appends without the key check, breaking
    `result.recurrences == []` on the replay leg."""
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
    assert len([e for e in events if e.get("kind") == "recurrence-suspect"]) == 2


# --------------------------------------------------- U-recur: fire crossover


def test_violated_fire_raises_recurrence_suspect(home, transcripts, monkeypatch):
    """AC1 — THE CROSSOVER fires: a `violated` fire against a routed
    record also raises exactly one recurrence-suspect, sharing the
    fire's origin byte-for-byte. Absent THE CROSSOVER this reads zero
    suspects and fails outright — not vacuous."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-cross", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "fires": [
                {"record": routed.id, "session": "sess-cross", "line": 5,
                 "outcome": "violated"}
            ],
        },
    )
    result = miner.run(home)
    assert result.status == "ok"
    events = telemetry.read_events(home)
    fires = [e for e in events if e.get("kind") == "fire"]
    suspects = [e for e in events if e.get("kind") == "recurrence-suspect"]
    assert len(fires) == 1
    assert len(suspects) == 1
    assert suspects[0]["record"] == routed.id
    assert suspects[0]["basis"] == "fire-violated"
    assert suspects[0]["origin"] == "transcript:sess-cross#L5"
    assert suspects[0]["origin"] == fires[0]["origin"]


def test_complied_fire_raises_no_suspect(home, transcripts, monkeypatch):
    """AC2 — the discriminator: a `complied` fire is the rule WORKING and
    must never cross over. Without this, a fix that raises a suspect for
    every fire would pass AC1 just as well."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-comply", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "fires": [
                {"record": routed.id, "session": "sess-comply", "line": 5,
                 "outcome": "complied"}
            ],
        },
    )
    miner.run(home)
    events = telemetry.read_events(home)
    assert [e for e in events if e.get("kind") == "recurrence-suspect"] == []
    assert len([e for e in events if e.get("kind") == "fire"]) == 1


def test_two_violated_sightings_one_run_raise_two_suspects(home, transcripts, monkeypatch):
    """AC3 — two distinct sightings in one run are two suspects: the live
    `lrn-5d0c592a` shape (same record, same session, different lines,
    both violated, one run). A "one suspect per record per run" guard
    (M4) swallows the second; assert the origin SET, not just the
    count."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-two", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "fires": [
                {"record": routed.id, "session": "sess-two", "line": 9,
                 "outcome": "violated"},
                {"record": routed.id, "session": "sess-two", "line": 11,
                 "outcome": "violated"},
            ],
        },
    )
    miner.run(home)
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert len(suspects) == 2
    assert {s["origin"] for s in suspects} == {
        "transcript:sess-two#L9", "transcript:sess-two#L11",
    }


def test_recurrence_suspect_idempotent_across_replay_and_backfill(
    home, transcripts, monkeypatch
):
    """AC4 — idempotence across runs: a replay of the identical payload
    (the crash / --since replay shape) must not re-raise, and neither
    must a THIRD, genuinely productive run (fresh transcript, no
    candidates/fires) whose only live code path is THE BACKFILL —
    it must not re-raise what it already raised."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-idem", [u("work")])
    payload = {
        "candidates": [],
        "fires": [
            {"record": routed.id, "session": "sess-idem", "line": 4,
             "outcome": "violated"}
        ],
    }
    shim_reader(monkeypatch, payload)
    assert miner.run(home).status == "ok"
    telemetry.flush(home)
    shim_reader(monkeypatch, payload)
    result = miner.run(home, since="2020-01-01")
    assert result.recurrences == [] and result.fires == 0
    events = telemetry.read_events(home)
    assert len([e for e in events if e.get("kind") == "fire"]) == 1
    assert len([e for e in events if e.get("kind") == "recurrence-suspect"]) == 1
    # third run: a fresh transcript so it clears the idle-before-reader
    # trap, no candidates and no fires of its own — only THE BACKFILL runs.
    write_transcript(transcripts, "sess-idem2", [u("more work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    result3 = miner.run(home)
    assert result3.status == "ok"
    assert result3.recurrences == []
    events = telemetry.read_events(home)
    assert len([e for e in events if e.get("kind") == "recurrence-suspect"]) == 1


def test_cross_channel_same_origin_one_suspect_miner_match_wins(
    home, transcripts, monkeypatch
):
    """AC5 — cross-channel, one origin, one suspect: a candidate-match AND
    a violated fire at the SAME origin are one sighting. The candidate
    loop runs first and wins; basis stays miner-match."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-x", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-x", line=7,
                          match={"record": routed.id, "status": "routed"})
            ],
            "fires": [
                {"record": routed.id, "session": "sess-x", "line": 7,
                 "outcome": "violated"}
            ],
        },
    )
    miner.run(home)
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert len(suspects) == 1
    assert suspects[0]["basis"] == "miner-match"
    assert suspects[0]["origin"] == "transcript:sess-x#L7"


def test_backfill_raises_suspect_for_ledgered_violation(home, transcripts, monkeypatch):
    """AC6 — THE BACKFILL, and the flush gate: a `violated` fire already
    in the TRACKED plane (no live crossover involved — pre-seeded, then
    flushed) still raises a suspect on the next productive run. NO
    explicit flush is called in this test after `miner.run`: with
    `landed`/`folded`/`fires` all empty, only `result.recurrences`
    opens the flush gate for a backfill-only run — the precise shape of
    "the fix ran and nothing is visible" if that append is missing."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    telemetry.spool_quiet(
        "fire", record=routed.id, origin="transcript:sess-old#L5",
        outcome="violated",
    )
    telemetry.flush(home)
    assert [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ] == []
    # a fresh transcript makes this run PRODUCTIVE (the idle-before-reader
    # trap) — the payload itself carries no candidates and no fires.
    write_transcript(transcripts, "sess-new", [u("unrelated work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    result = miner.run(home)
    assert result.status == "ok"
    assert result.recurrences == [routed.id]
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert len(suspects) == 1
    assert suspects[0]["record"] == routed.id
    assert suspects[0]["origin"] == "transcript:sess-old#L5"
    assert suspects[0]["basis"] == "fire-violated"


def test_backfill_skips_non_routed_and_unresolvable_records(
    home, transcripts, monkeypatch
):
    """AC7 — THE BACKFILL respects live routed coverage, mirroring the
    live crossover's `routed` guard EXACTLY including its `found is
    None` half: a superseded record's stale violation and a violation
    against an id that resolves to no record on disk must both be
    skipped, silently — never raised as a permanent-litter suspect, and
    never a crash that would wedge every future nightly run (run()'s
    outer handler turns an escaping exception into status: failed, and
    the offending telemetry row never goes away)."""
    superseded = make_behavior()
    _resolve(home, superseded, "superseded")
    telemetry.spool_quiet(
        "fire", record=superseded.id, origin="transcript:sess-old#L5",
        outcome="violated",
    )
    telemetry.spool_quiet(
        "fire", record="lrn-00000000", origin="transcript:sess-old#L6",
        outcome="violated",
    )
    telemetry.flush(home)
    write_transcript(transcripts, "sess-new2", [u("unrelated work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    result = miner.run(home)
    assert result.status == "ok"
    assert result.recurrences == []
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert suspects == []


def test_crossover_journal_row_is_not_a_near_miss(home, transcripts, monkeypatch):
    """AC8 — the journal row is not a near-miss: THE CROSSOVER journals
    `recurrence-from-fire`, which carries no `disposition` key (nothing
    was dropped, there was no candidate) and must not inflate
    `near_miss_count`."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    write_transcript(transcripts, "sess-journal", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "fires": [
                {"record": routed.id, "session": "sess-journal", "line": 5,
                 "outcome": "violated"}
            ],
        },
    )
    miner.run(home)
    entry = miner.read_journal()[-1]
    assert entry["near_miss_count"] == 0
    rows = [o for o in entry["outcomes"] if o["outcome"] == "recurrence-from-fire"]
    assert len(rows) == 1
    row = rows[0]
    assert row["record"] == routed.id
    assert row["origin"] == "transcript:sess-journal#L5"
    assert "disposition" not in row


def test_backfill_ignores_complied_fires(home, transcripts, monkeypatch):
    """AC10 — THE BACKFILL ignores `complied`: `_event_seen` runs BEFORE
    the fires loop, so AC2 (a `complied` fire raised THIS run) can never
    see THE BACKFILL at all — a build that drops the outcome filter
    passes AC1-AC9 and would raise 22 suspects on the live ledger instead
    of 4. Assert the ORIGIN, not just the count: a build that backfills
    every tracked fire produces two suspects here too."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    telemetry.spool_quiet(
        "fire", record=routed.id, origin="transcript:sess-old#L5",
        outcome="complied",
    )
    telemetry.spool_quiet(
        "fire", record=routed.id, origin="transcript:sess-old#L6",
        outcome="violated",
    )
    telemetry.flush(home)
    write_transcript(transcripts, "sess-new3", [u("unrelated work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    miner.run(home)
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert len(suspects) == 1
    assert suspects[0]["origin"] == "transcript:sess-old#L6"


def test_backfill_raises_one_suspect_per_sighting_not_per_record(
    home, transcripts, monkeypatch
):
    """AC11 — THE BACKFILL raises one suspect per sighting, not per
    record: the backfill-side twin of AC3/M4 (M12) — a "don't spam, one
    per record" guard placed INSIDE the backfill loop passes every other
    criterion in this spec while silently halving the live ledger's
    4-suspect recovery to 2. This is the direct test of the §2.2
    four-suspect claim."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    telemetry.spool_quiet(
        "fire", record=routed.id, origin="transcript:sess-old#L5",
        outcome="violated",
    )
    telemetry.spool_quiet(
        "fire", record=routed.id, origin="transcript:sess-old#L6",
        outcome="violated",
    )
    telemetry.flush(home)
    write_transcript(transcripts, "sess-new4", [u("unrelated work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    result = miner.run(home)
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert len(suspects) == 2
    assert {s["origin"] for s in suspects} == {
        "transcript:sess-old#L5", "transcript:sess-old#L6",
    }
    assert result.recurrences == [routed.id, routed.id]


def test_live_crossover_skips_non_routed_record(home, transcripts, monkeypatch):
    """Code-gate F1 — THE CROSSOVER's `routed` guard has no criterion on
    the LIVE path (AC7/M9/M13 pin the routed guard on THE BACKFILL only;
    the live path's twin was unpinned). A `violated` fire naming a
    `superseded` record must raise no `fire` and no `recurrence-suspect`
    at all — the routed guard sits ABOVE the crossover call in the fires
    loop, so a build that hoists the crossover call above that guard
    would emit permanent litter here: a suspect `confirm_recurrence`
    refuses and `report.recurrence_suspects` filters out forever."""
    superseded = make_behavior()
    _resolve(home, superseded, "superseded")
    write_transcript(transcripts, "sess-nonrouted", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "fires": [
                {"record": superseded.id, "session": "sess-nonrouted",
                 "line": 5, "outcome": "violated"}
            ],
        },
    )
    result = miner.run(home)
    assert result.fires == 0
    assert result.recurrences == []
    events = telemetry.read_events(home)
    assert [e for e in events if e.get("kind") == "fire"] == []
    assert [e for e in events if e.get("kind") == "recurrence-suspect"] == []


def test_backfill_survives_non_string_record_row(home, transcripts, monkeypatch):
    """Code-gate F2 — THE BACKFILL's untrusted-input validation on
    `violated_fires` (spec §4 decision 4: "never a crash, never a guessed
    id") is unpinned by AC7 alone: AC7's `lrn-00000000` is
    well-formed-but-absent, so it never reaches `RECORD_ID_RE.match` with
    a non-string argument. One malformed tracked row — `record` landed
    as an int, which telemetry's scalar-payload check happily accepts —
    must not raise `TypeError` and wedge the run into `status: failed`
    (the same permanent-wedge shape AC7/M13 exists to prevent, through a
    different door). A GOOD row in the same run must still backfill
    correctly — presence-paired by construction, per the spec's own
    fail-open rule."""
    routed = make_behavior()
    _resolve(home, routed, "routed")
    telemetry.spool_quiet(
        "fire", record=12345, origin="transcript:sess-bad#L1",
        outcome="violated",
    )
    telemetry.spool_quiet(
        "fire", record=routed.id, origin="transcript:sess-old#L5",
        outcome="violated",
    )
    telemetry.flush(home)
    write_transcript(transcripts, "sess-new5", [u("unrelated work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    result = miner.run(home)
    assert result.status == "ok"
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert len(suspects) == 1
    assert suspects[0]["origin"] == "transcript:sess-old#L5"


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


# =================================================== FW-34: near-miss visibility

SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6Q7r8"


def test_cap_refused_journals_snippet(home, transcripts, monkeypatch):
    """t-a: a cap-refused candidate journals a `snippet` that round-trips
    its trigger/instruction, folded to disposition `cap-refused` and
    marked `promotable`."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    write_transcript(transcripts, "sess-nm-a", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-nm-a", line=1),
                candidate(
                    session="sess-nm-a",
                    line=2,
                    trigger="Second distinct trigger about rsync",
                ),
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert len(result.landed) == 1 and result.dropped == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_refused = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_refused["disposition"] == "cap-refused"
    assert cap_refused["promotable"] is True
    assert cap_refused["reason"]
    snippet = cap_refused["snippet"]
    assert snippet["type"] == "behavior"
    assert snippet["trigger"] == "Second distinct trigger about rsync"
    assert snippet["instruction"]
    assert "why_durable" in snippet
    assert "quote" not in snippet  # §1.2/F3-(a): no evidence quote, ever


def test_cap_refused_secret_in_why_durable_refused(home, transcripts, monkeypatch):
    """t-b (cap-refused leg): the pre-`_outcome` scan the dropped-cap
    branch used to lack entirely — a planted secret in `why_durable` is
    caught and never reaches the journal file's bytes."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    write_transcript(transcripts, "sess-nm-b", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-nm-b", line=1),
                candidate(
                    session="sess-nm-b",
                    line=2,
                    trigger="Second distinct trigger about rsync",
                    why_durable=f"leaked token {SECRET} rotated",
                ),
            ],
            "fires": [],
        },
    )
    miner.run(home)
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_refused = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_refused["snippet"] == {"scan_refused_rule": "github-token"}
    assert cap_refused["promotable"] is False
    raw = miner.journal_path().read_text(encoding="utf-8")
    assert SECRET not in raw


def test_rubric_dropped_secret_in_why_durable_refused(home, transcripts, monkeypatch):
    """t-b (rubric-dropped leg): the SAME secret-in-`why_durable` plant,
    on the `near_misses[]` handler — a partial (trigger/instruction-only)
    scan would miss it; the field-by-field scan must not."""
    write_transcript(transcripts, "sess-nm-c", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "near_misses": [
                {
                    "type": "behavior",
                    "trigger": "About to do something risky",
                    "instruction": "Don't",
                    "why_durable": f"leaked token {SECRET} rotated",
                    "session": "sess-nm-c",
                    "line": 5,
                    "confidence": "medium",
                }
            ],
            "fires": [],
        },
    )
    miner.run(home)
    outcomes = miner.read_journal()[-1]["outcomes"]
    rubric = next(o for o in outcomes if o["outcome"] == "rubric-dropped")
    assert rubric["disposition"] == "rubric-dropped"
    assert rubric["snippet"] == {"scan_refused_rule": "github-token"}
    assert rubric["promotable"] is False
    raw = miner.journal_path().read_text(encoding="utf-8")
    assert SECRET not in raw


def test_cap_refused_overlength_snippet_no_content(home, transcripts, monkeypatch):
    """t-c: an over-cap snippet becomes `{overlength: True}` — never a
    clipped draft."""
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    write_transcript(transcripts, "sess-nm-d", [u("work")])
    big = "X" * 700
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-nm-d", line=1),
                candidate(session="sess-nm-d", line=2, trigger=big),
            ],
            "fires": [],
        },
    )
    miner.run(home)
    outcomes = miner.read_journal()[-1]["outcomes"]
    cap_refused = next(o for o in outcomes if o["outcome"] == "dropped-cap")
    assert cap_refused["snippet"] == {"overlength": True}
    assert cap_refused["promotable"] is False
    raw = miner.journal_path().read_text(encoding="utf-8")
    assert big not in raw


def test_rubric_dropped_journals_snippet(home, transcripts, monkeypatch):
    """A clean `near_misses[]` entry round-trips through `rubric-dropped`,
    never lands, and is counted in `near_miss_count`."""
    write_transcript(transcripts, "sess-nm-g", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "near_misses": [
                {
                    "type": "behavior",
                    "trigger": "Trigger text",
                    "instruction": "Instruction text",
                    "why_durable": "will recur",
                    "session": "sess-nm-g",
                    "line": 7,
                    "confidence": "low",
                }
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.landed == []
    entry = miner.read_journal()[-1]
    rubric = next(o for o in entry["outcomes"] if o["outcome"] == "rubric-dropped")
    assert rubric["origin"] == "transcript:sess-nm-g#L7"
    assert rubric["disposition"] == "rubric-dropped"
    assert rubric["promotable"] is True
    assert rubric["snippet"] == {
        "type": "behavior",
        "trigger": "Trigger text",
        "instruction": "Instruction text",
        "why_durable": "will recur",
    }
    assert entry["near_miss_count"] == 1


def test_rubric_dropped_max_field_chars_refuse_not_clip(home, transcripts, monkeypatch):
    """t-d (field cap): an over-`MAX_FIELD_CHARS` field drops the WHOLE
    near-miss — never a clipped/guessed shape."""
    write_transcript(transcripts, "sess-nm-e", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "near_misses": [
                {
                    "type": "behavior",
                    "trigger": "T" * (miner.MAX_FIELD_CHARS + 1),
                    "instruction": "short",
                    "why_durable": "will recur",
                    "session": "sess-nm-e",
                    "line": 5,
                }
            ],
            "fires": [],
        },
    )
    miner.run(home)
    outcomes = miner.read_journal()[-1]["outcomes"]
    assert not any(o["outcome"] == "rubric-dropped" for o in outcomes)


def test_rubric_dropped_invalid_ref_drops_whole_near_miss(home, transcripts, monkeypatch):
    """t-d (`_valid_ref` gating): a bad session id drops the whole
    near-miss — never a guessed origin."""
    write_transcript(transcripts, "sess-nm-f", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [],
            "near_misses": [
                {
                    "type": "behavior",
                    "trigger": "trigger",
                    "instruction": "instruction",
                    "why_durable": "will recur",
                    "session": "bad session id!",
                    "line": 5,
                }
            ],
            "fires": [],
        },
    )
    miner.run(home)
    outcomes = miner.read_journal()[-1]["outcomes"]
    assert not any(o["outcome"] == "rubric-dropped" for o in outcomes)
    assert miner.read_journal()[-1]["near_miss_count"] == 0


def test_dropped_rejected_no_snippet_no_record_id(home, transcripts, monkeypatch):
    """t-e: the §1.1 double-absence — `dropped-rejected` carries neither
    `snippet` nor `record`, counts-only."""
    rejected = make_behavior()
    _resolve(home, rejected, "rejected")
    write_transcript(transcripts, "sess-rej-nm", [u("sighting")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-rej-nm",
                    match={"record": rejected.id, "status": "rejected"},
                )
            ],
            "fires": [],
        },
    )
    miner.run(home)
    outcomes = miner.read_journal()[-1]["outcomes"]
    dropped = next(o for o in outcomes if o["outcome"] == "dropped-rejected")
    assert dropped["disposition"] == "rejected"
    assert dropped["promotable"] is False
    assert "snippet" not in dropped
    assert "record" not in dropped
    assert dropped["sightings"] == 1


def test_folded_disposition_is_already_canon_with_record_id(home, transcripts, monkeypatch):
    """Blind-review fold 1: the `already-canon` fold-table row (folded,
    skipped-resolved, recurrence, recurrence-already-known,
    skipped-known-origin) was left unpinned — a silent remap (e.g.
    `folded -> other`) would drop the matched-record link and show the
    wrong plain-words reason, and every prior test still passed. Pins
    BOTH: `disposition == "already-canon"` AND the matched record id
    surviving into the journal entry."""
    existing = make_behavior()
    create_record(home, existing)
    write_transcript(transcripts, "sess-fold-nm", [u("hit it again")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-fold-nm",
                    match={"record": existing.id, "status": "pending"},
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.folded == [existing.id]
    outcomes = miner.read_journal()[-1]["outcomes"]
    folded = next(o for o in outcomes if o["outcome"] == "folded")
    assert folded["disposition"] == "already-canon"
    assert folded["record"] == existing.id  # the matched-record link survives
    assert folded["reason"]  # plain-words, Y-9 register — never empty
    assert folded["promotable"] is False
    assert "snippet" not in folded  # already-canon rows never carry one


def test_every_disposition_has_a_reason(home):
    """Blind-review fold 1 (table-completeness): every value
    `_NEARMISS_DISPOSITION` can produce must have a plain-words reason —
    an addition to the fold table with no matching `_NEARMISS_REASON`
    entry would KeyError at journal-write time on the very outcome it
    was meant to enrich (`_enrich_near_miss`'s `_NEARMISS_REASON[disposition]`
    lookup, not `.get`)."""
    dispositions = set(miner._NEARMISS_DISPOSITION.values())
    assert dispositions  # the table itself is non-empty — a vacuous pass is not a pass
    missing = dispositions - set(miner._NEARMISS_REASON)
    assert not missing, f"disposition(s) in the fold table with no reason: {missing}"


# ------------------------------------------------------- FW-34 §3: canaries


def test_canary_plant_writes_cache_entry(home):
    canary_id = miner.plant_canary(
        "always run go vet before committing Go changes", expect="go vet"
    )
    assert canary_id
    canaries = miner._load_canaries()
    assert len(canaries) == 1
    assert canaries[0]["id"] == canary_id
    assert canaries[0]["lesson"] == "always run go vet before committing Go changes"
    assert canaries[0]["expect"] == "go vet"
    assert canaries[0]["status"] == "open"


def test_canary_caught_on_matching_landed_record(home, transcripts, monkeypatch):
    """t-f (catch leg): a later run that lands a title-matching record
    scores the open canary `caught`."""
    miner.plant_canary(
        "always run go vet before committing Go changes", expect="go vet"
    )
    write_transcript(transcripts, "sess-canary-catch", [u("go vet is important")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-canary-catch",
                    trigger="always run go vet before committing Go changes",
                    instruction="run go vet",
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.landed
    summary = miner.read_canaries_summary()
    assert summary == {"planted": 1, "caught": 1, "missed": 0, "open": []}


def test_canary_missed_when_source_session_mined_without_match(
    home, transcripts, monkeypatch
):
    """t-f (missed leg): once the canary's own (best-effort) source
    session has been mined with no match, it scores `missed`."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-canary-src")
    miner.plant_canary("prefer editing files over rewriting them whole")
    write_transcript(
        transcripts, "sess-canary-src", [u("totally unrelated content about pizza")]
    )
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    miner.run(home)
    summary = miner.read_canaries_summary()
    assert summary["missed"] == 1
    assert summary["caught"] == 0
    assert summary["open"] == []


def test_canary_plant_refuses_dp2(home):
    """t-g: `plant --lesson` naming DP-2 is refused — the standing
    window-placement experiment is never planted artificially."""
    with pytest.raises(miner.CanaryError):
        miner.plant_canary("the DP-2 window placement rule should always apply")
    assert miner._load_canaries() == []
    # case-insensitive + inside --expect too
    with pytest.raises(miner.CanaryError):
        miner.plant_canary("a fine lesson", expect="matches dp-2 somehow")
    assert miner._load_canaries() == []


def test_canary_plant_cli_refuses_dp2(home, capsys):
    """The CLI surface: a usage exit, nothing written."""
    rc = cli.main(["canary", "plant", "--lesson", "always honor DP-2"])
    assert rc == cli.EXIT_USAGE
    assert "DP-2" in capsys.readouterr().err
    assert miner._load_canaries() == []


def test_canary_plant_writes_no_transcript(home, transcripts):
    """t-h: plant creates/mutates no `*.jsonl` under any transcripts
    dir — the honesty pin: canaries never forge transcript content."""
    before = sorted(transcripts.rglob("*.jsonl"))
    miner.plant_canary("always double check migrations before applying them")
    after = sorted(transcripts.rglob("*.jsonl"))
    assert before == after == []
    assert miner.canaries_path().is_file()


def test_canary_catch_does_not_affect_supply_metrics(tmp_path, monkeypatch):
    """t-i: a run that scores a `caught` canary leaves `supply_mix` and
    the mined-accept-rate byte-identical to the no-canary run."""
    from self_learn import report as report_mod

    def run_scenario(subdir: str, *, plant: bool) -> Path:
        home = make_home(tmp_path / subdir)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        root = tmp_path / f"{subdir}-transcripts"
        (root / "-home-u-proj").mkdir(parents=True)
        monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
        miner._save_cursors({"__initialized__": "test-fixture"})
        if plant:
            miner.plant_canary(
                "always run go vet before committing Go changes", expect="go vet"
            )
        write_transcript(root, "sess", [u("go vet is important")])
        shim_reader(
            monkeypatch,
            {
                "candidates": [
                    candidate(
                        session="sess",
                        trigger="always run go vet before committing Go changes",
                        instruction="run go vet",
                    )
                ],
                "fires": [],
            },
        )
        result = miner.run(home)
        assert result.landed
        return home

    home_a = run_scenario("a", plant=True)
    assert miner.read_canaries_summary()["caught"] == 1  # sanity: it WAS caught

    home_b = run_scenario("b", plant=False)
    assert miner.read_canaries_summary() is None  # sanity: no canary here

    assert report_mod.supply_mix(home_a) == report_mod.supply_mix(home_b)
    mined_a = report_mod.gather(home_a)["mined"]
    mined_b = report_mod.gather(home_b)["mined"]
    assert mined_a == mined_b


def test_mine_status_json_carries_canaries_and_near_miss_count(
    home, transcripts, monkeypatch, capsys
):
    """§4: `mine status --json` gains the top-level `canaries` block
    (absent when none) and each run's `near_miss_count`."""
    rc = cli.main(["mine", "status", "--json"])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert "canaries" not in payload  # nothing planted yet

    miner.plant_canary("always run go vet before committing Go changes")
    monkeypatch.setenv("SELF_LEARN_MINE_CAP_PER_SESSION", "1")
    write_transcript(transcripts, "sess-status", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(session="sess-status", line=1),
                candidate(
                    session="sess-status",
                    line=2,
                    trigger="Second distinct trigger about rsync",
                ),
            ],
            "fires": [],
        },
    )
    miner.run(home)
    rc = cli.main(["mine", "status", "--json"])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["canaries"]["planted"] == 1
    last_run = payload["runs"][-1]
    assert last_run["near_miss_count"] == 1
    outcome = next(o for o in last_run["outcomes"] if o["outcome"] == "dropped-cap")
    assert outcome["disposition"] == "cap-refused"
    assert outcome["promotable"] is True


# ============================================== FW-53: ledger decode safety
#
# A record file that is not valid UTF-8 (a torn write, a bad merge, a
# hand edit) must never wedge a whole `mine run`. Confirmed pre-existing:
# `_compose_prompt` -> `_ledger_index` -> `Record.from_path` -> `read_text`
# ran BEFORE `_reconcile_and_land`, so `run()`'s outer handler turned the
# ENTIRE run into `status: failed` on one bad byte, before the reader was
# ever invoked. Decision: skip the corrupt file, count it, land everything
# else (the nightly producer degrades, it does not stop) — but the skip
# is REPORTED, never silent: `result.corrupt_records`, every journal entry
# from the point of detection onward, `miner.log`, and the human-readable
# `mine status` one-liner all carry it.


def _write_bad_bytes(path: Path, prefix: str = "") -> None:
    """`prefix` (valid UTF-8) + bytes that are not valid UTF-8 anywhere —
    guaranteed to raise `UnicodeDecodeError` on decode (mirrors
    selfcheck.py's own FW-66 helper of the same name/shape)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(prefix.encode("utf-8") + b"\xff\xfe garbage")


def test_ledger_index_skips_undecodable_record_and_reports_it(home):
    good = make_behavior(record_id="lrn-00009999")
    pending = home / "skills/s/pending"
    pending.mkdir(parents=True, exist_ok=True)
    good.write(pending / f"{good.id}.md")
    bad_path = pending / "lrn-0badbeef.md"
    _write_bad_bytes(bad_path, "---\ntype: behavior\nid: lrn-0badbeef\n---\n")

    corrupt: list[Path] = []
    index = miner._ledger_index(home, corrupt)

    assert good.id in index
    assert "lrn-0badbeef" not in index
    assert corrupt == [bad_path]


def test_canon_index_skips_undecodable_record_and_reports_it(home):
    routed = make_behavior(record_id="lrn-00009999")
    _resolve(home, routed, "routed")
    bad_path = home / "skills/s/resolved" / "lrn-0badbeef.md"
    _write_bad_bytes(
        bad_path, "---\ntype: behavior\nid: lrn-0badbeef\nstatus: routed\n---\n"
    )

    corrupt: list[Path] = []
    index = miner._canon_index(home, corrupt)

    assert routed.id in index
    assert "lrn-0badbeef" not in index
    assert corrupt == [bad_path]


def test_compose_prompt_surfaces_corrupt_records_without_crashing(home):
    _write_bad_bytes(
        home / "skills/s/pending" / "lrn-0badbeef.md",
        "---\ntype: behavior\nid: lrn-0badbeef\n---\n",
    )

    prompt, corrupt = miner._compose_prompt(home, ["(digest)"], Path("/tmp/out.json"))

    assert len(corrupt) == 1
    assert corrupt[0].name == "lrn-0badbeef.md"
    assert "(digest)" in prompt  # composition still completed


def test_find_record_returns_none_for_undecodable_file_never_raises(home):
    _write_bad_bytes(
        home / "skills/s/pending" / "lrn-0badbeef.md",
        "---\ntype: behavior\nid: lrn-0badbeef\n---\n",
    )

    assert miner._find_record(home, "lrn-0badbeef") is None


def test_run_survives_corrupt_pending_record_lands_the_rest(
    home, transcripts, monkeypatch
):
    """The end-to-end proof: a corrupt pending record sits in the ledger
    while a normal, healthy session comes through — the run must still
    land the healthy candidate (skip-and-continue, not skip-and-stop),
    and the corruption must be visible in BOTH the result and the
    journal, not swallowed."""
    bad_path = home / "skills/s/pending" / "lrn-0badbeef.md"
    _write_bad_bytes(bad_path, "---\ntype: behavior\nid: lrn-0badbeef\n---\n")
    write_transcript(transcripts, "sess-e2e", [u("work"), a("found the cause")])
    shim_reader(monkeypatch, {"candidates": [candidate()], "fires": []})

    result = miner.run(home)

    assert result.status == "ok"
    assert len(result.landed) == 1  # the healthy candidate still landed
    assert result.corrupt_records == [str(bad_path)]
    entry = miner.read_journal()[-1]
    assert entry["status"] == "ok"
    assert entry["corrupt_records"] == [str(bad_path)]
    # the corrupt file itself is untouched — never rewritten or deleted
    assert bad_path.is_file()


def test_match_claim_to_undecodable_record_demotes_to_landing(
    home, transcripts, monkeypatch
):
    """Mirrors `test_invalid_match_claim_demotes_to_landing`: a `match`
    claim naming a record id that resolves to a FILE ON DISK, but one
    that fails to decode, must be treated exactly like a claim naming a
    record that does not exist at all — demoted to landing, never a
    crash."""
    _write_bad_bytes(
        home / "skills/s/pending" / "lrn-0badbeef.md",
        "---\ntype: behavior\nid: lrn-0badbeef\n---\n",
    )
    write_transcript(transcripts, "sess-claim2", [u("work")])
    shim_reader(
        monkeypatch,
        {
            "candidates": [
                candidate(
                    session="sess-claim2",
                    match={"record": "lrn-0badbeef", "status": "pending"},
                )
            ],
            "fires": [],
        },
    )
    result = miner.run(home)
    assert result.status == "ok"
    assert len(result.landed) == 1
    outcomes = miner.read_journal()[-1]["outcomes"]
    assert outcomes[0]["outcome"] == "match-claim-invalid"
    assert outcomes[1]["outcome"] == "landed"


def test_backfill_skips_undecodable_matched_record(home, transcripts, monkeypatch):
    """AC7's own twin, for decode failure rather than absence: THE
    BACKFILL must skip a `violated` fire whose record id resolves to a
    FILE that fails to decode — silently, like any other unresolvable
    row — never a crash that would wedge every future nightly run."""
    _write_bad_bytes(
        home / "skills/s/resolved" / "lrn-0badbeef.md",
        "---\ntype: behavior\nid: lrn-0badbeef\nstatus: routed\n---\n",
    )
    telemetry.spool_quiet(
        "fire", record="lrn-0badbeef", origin="transcript:sess-old#L5",
        outcome="violated",
    )
    telemetry.flush(home)
    write_transcript(transcripts, "sess-new3", [u("unrelated work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})

    result = miner.run(home)

    assert result.status == "ok"
    assert result.recurrences == []
    suspects = [
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    ]
    assert suspects == []


def test_mine_status_reports_corrupt_records_in_human_output(
    home, transcripts, monkeypatch, capsys
):
    """The human-readable `mine status` one-liner (not just `--json`) must
    surface a corrupt-record skip — never silent even in the terse path a
    person actually reads."""
    _write_bad_bytes(
        home / "skills/s/pending" / "lrn-0badbeef.md",
        "---\ntype: behavior\nid: lrn-0badbeef\n---\n",
    )
    write_transcript(transcripts, "sess-status2", [u("work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    miner.run(home)

    rc = cli.main(["mine", "status"])

    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "1 ledger file(s) not UTF-8, skipped" in out


def test_M_S_fold_r1_mine_record_model_field_reads_models_miner_config(
    home, transcripts, monkeypatch
):
    """M-S (S-58 code-gate fold r1, minor-1): the mine record's `model`
    field must reflect `models.miner: X` in config.yaml even with no env
    var set -- `miner_model()`'s old bare env-or-default stamp was
    invisible to this config.yaml rung entirely; `provider.model_for`
    (the actual stamp now used) resolves it correctly."""
    monkeypatch.delenv("SELF_LEARN_MINER_MODEL", raising=False)
    (home / "config.yaml").write_text("models:\n  miner: CONFIG-MINER-MODEL-ID\n", encoding="utf-8")
    write_transcript(transcripts, "sess-model-stamp", [u("some work")])
    shim_reader(monkeypatch, {"candidates": [], "fires": []})
    result = miner.run(home)
    assert result.status == "ok"
    assert miner.read_journal()[-1]["model"] == "CONFIG-MINER-MODEL-ID"


# ============================== M-W/D7 gate r1 fold: BLOCKER-2/MAJOR-3(d)


def test_mine_recovers_a_restorable_intent_and_logs_it(home):
    """Gate r1 BLOCKER-2 / MAJOR-3(d): a mine START must recover a
    RESTORABLE intent left by a previous run's crash, complete
    normally, and LOG the recovery — pins the fix at `_run_locked`'s own
    self-heal block. Before the fix, `if healed.healed:` was true here
    with `healed.committed` empty (nothing to reconcile, only an intent
    to recover), and `healed.sha[:7]` crashed the WHOLE mine run with an
    uncaught `TypeError` — this is the identical shape, minus the
    SIGKILL: a real intent planted directly, recovery running for real
    inside a real `miner.run(home)` call. No cursors are initialized, so
    this reaches `status == "initialized"` (the first-activation path)
    right after recovery, without ever touching the reader/SDK — the
    self-heal step runs BEFORE that check, so it is exercised either
    way."""
    f = home / "a.txt"
    f.write_text("old", encoding="utf-8")
    commit_all(home, "seed")
    intent = intents.begin(home, "test-op", [f], "self-learn: test op")
    f.write_text("mutated, crash before complete()", encoding="utf-8")  # never completed

    result = miner.run(home)

    assert result.status == "initialized"  # the mine run itself completes, no crash
    assert f.read_text(encoding="utf-8") == "old"
    assert not intent.file_path.exists()
    log_text = (miner.miner_dir() / "miner.log").read_text(encoding="utf-8")
    assert f"recovered {intent.id} (restored: its mutation was undone)" in log_text
