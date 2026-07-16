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
    h = make_home(tmp_path)
    (h / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md").write_text(
        "# s\n", encoding="utf-8"
    )
    commit_all(h, "seed")
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


@pytest.fixture()
def transcripts(tmp_path, monkeypatch):
    root = tmp_path / "transcripts"
    (root / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(root))
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
    digest = miner.digest_transcript(slice_of(p))
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
    digest = miner.digest_transcript(slice_of(p))
    assert "ERROR" in digest
    assert "[retry-cluster Bash:make build ×3, 2 error(s)]" in digest


def test_digest_excludes_own_machinery(transcripts):
    p = write_transcript(
        transcripts,
        "worker-sess",
        [u("You are the self-learn routing analyst worker. Records below."), a("ok")],
    )
    assert miner.digest_transcript(slice_of(p)) is None
    p2 = write_transcript(
        transcripts,
        "miner-sess",
        [u("You are the self-learn transcript miner. Digests below."), a("ok")],
    )
    assert miner.digest_transcript(slice_of(p2)) is None


def test_digest_excludes_selflearn_command_span(transcripts):
    p = write_transcript(
        transcripts,
        "sess3",
        [
            u("normal work before"),
            u("<command-name>/self-learn:review</command-name> run it"),
            a("Card 1 of 3: the lesson about storage edits…"),
            u("back to normal work now"),
            a("resuming the actual task"),
        ],
    )
    digest = miner.digest_transcript(slice_of(p))
    assert "normal work before" in digest
    assert "Card 1 of 3" not in digest  # inside the span
    assert "back to normal work now" in digest
    assert "resuming the actual task" in digest


def test_digest_plain_string_content(transcripts):
    p = write_transcript(transcripts, "sess4", [u_str("string-content user turn")])
    assert "string-content user turn" in miner.digest_transcript(slice_of(p))


# ------------------------------------------------------------- walk


def test_walk_cursor_advance_and_append(transcripts):
    p = write_transcript(transcripts, "sess5", [u("one"), u("two")])
    slices = miner.walk()
    assert len(slices) == 1 and slices[0].start_line == 0
    miner._advance_cursors(slices)
    assert miner.walk() == []
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(u("three") + "\n")
    slices = miner.walk()
    assert len(slices) == 1
    assert slices[0].start_line == 2 and len(slices[0].lines) == 1


def test_walk_since_rereads_from_zero(transcripts):
    p = write_transcript(transcripts, "sess6", [u("old content")])
    miner._advance_cursors(miner.walk())
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
    for d in home.glob("plugins/*/skills/*/.self-learn/pending/lrn-*.md"):
        out.append(d.stem)
    for d in home.glob(".self-learn/pending/lrn-*.md"):
        out.append(d.stem)
    return out


def test_run_lands_candidate(home, transcripts, monkeypatch):
    write_transcript(transcripts, "sess-e2e", [u("work"), a("found the cause")])
    shim_reader(monkeypatch, {"candidates": [candidate()], "fires": []})
    kicked = []
    monkeypatch.setattr(miner.worker, "kick", lambda h: kicked.append(h) or "spawned")
    result = miner.run(home, trigger="timer")
    assert result.status == "ok"
    assert len(result.landed) == 1
    rid = result.landed[0]
    path = home / "plugins/s-plugin/skills/s/.self-learn/pending" / f"{rid}.md"
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
        home / "plugins/s-plugin/skills/s/.self-learn/pending" / f"{existing.id}.md"
    )
    assert any(
        ev.get("origin") == "transcript:sess-fold#L42" for ev in refreshed.evidence
    )
    assert len(pending_ids(home)) == 1


def _resolve(home, record, status):
    """Move a pending record to resolved/ with the given status."""
    record.set_status(status)
    resolved = home / "plugins/s-plugin/skills/s/.self-learn/resolved"
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
    outcome = miner.read_journal()[-1]["outcomes"][0]
    assert outcome["outcome"] == "landed"
    assert "previously rejected" in outcome["why"]
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
    argv = miner.build_reader_argv("PROMPT", settings)
    assert argv[:3] == ["claude", "-p", "PROMPT"]
    assert "claude-test-model" in argv
    i = argv.index("--allowedTools")
    assert argv[i + 1] == "Read,Grep,Glob"
    j = argv.index("--disallowedTools")
    assert "Bash" in argv[j + 1] and "Edit" in argv[j + 1]


def test_artifact_contract_sweeps_strays(home, tmp_path, monkeypatch):
    shims = tmp_path / "shims"
    shims.mkdir()
    spool = miner.spool_dir()
    shim = shims / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
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
    monkeypatch.setattr(miner, "_spawn_run", lambda h: spawned.append(h) or 4242)
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
    monkeypatch.setattr(miner.worker, "kick", lambda h: "disabled")
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
    monkeypatch.setattr(miner.worker, "kick", lambda h: "disabled")
    rid = miner.run(home).landed[0]
    facts = report.gather(home)
    assert facts["mined"]["pending"] == 1
    assert facts["mined"]["adjudicated"] == 0
    assert facts["mined"]["accept_rate"] is None  # honesty: none adjudicated
    # adjudicate it: mark routed, accept rate becomes 1.0
    path = home / "plugins/s-plugin/skills/s/.self-learn/pending" / f"{rid}.md"
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
