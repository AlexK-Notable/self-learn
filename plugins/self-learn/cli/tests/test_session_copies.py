"""2026-09-28 -- a copy of every model session's transcript, kept per run.

The user's words: "go ahead and just capture everything." After each
session self-learn runs, the seam copies Claude Code's own transcript
file (and its subagent files) into the cache under
`sessions/<surface>/<group>/`, records the copy on the outcome and in the
session's event log, and the steward's and the overseer's run records
carry it per session (counts only). Every session also asks for
summarized thinking. One setting, `sdk.capture_sessions`, turns both off.

No test here crosses the real SDK boundary: the backend drives a
`FakeSdkClient` (or, for the command-line check, `fixtures/fake_claude.py`),
and the steward and overseer run against fake `write_session`s."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock

from self_learn import execution_evidence, scan, session_copies, steward, worker
from self_learn.invocation_sdk import backend
from self_learn.overseer import run as overseer_run
from self_learn.sdksession.fake import FakeSdkClient
from support import make_home

SID = "0b6f7a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
RUN = "run-0a1b2c3d4e5f"
TOKEN = "SENTINEL-SESSION-COPY-7f3a91"

_TRANSCRIPT_LINES = [
    {"type": "user", "message": {"role": "user", "content": "the packet"}},
    {"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "a summary of the reasoning"},
        {"type": "text", "text": "reading"},
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
    ]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "file text"},
    ]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
    {"type": "system", "subtype": "turn_duration"},
]


def _plant_transcript(claude_dir: Path, *, sid: str = SID, subagent: bool = True) -> Path:
    project = claude_dir / "projects" / "-some-other-project"
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{sid}.jsonl"
    text = "".join(json.dumps(line) + "\n" for line in _TRANSCRIPT_LINES) + "not json\n"
    path.write_text(text, encoding="utf-8")
    if subagent:
        sub = project / sid / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-a1.jsonl").write_text('{"type": "user"}\n', encoding="utf-8")
    return path


def _messages(*, result: bool = True) -> list:
    out: list = [
        SystemMessage(subtype="init", data={"type": "system", "subtype": "init", "session_id": SID}),
        AssistantMessage(content=[TextBlock(text="done")], model="m", session_id=SID),
    ]
    if result:
        out.append(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                                 is_error=False, num_turns=1, session_id=SID))
    return out


@pytest.fixture
def seam(tmp_path, monkeypatch):
    """A ledger home, a Claude Code directory, and the steward session spec
    for run `RUN` -- the event log and the copies resolve to this home's
    cache."""
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec = steward._session_spec(home, run_dir, "per-packet text", label="steward-t", run_id=RUN)
    return home, claude_dir, spec


def _drive(monkeypatch, spec, messages):
    monkeypatch.setattr(
        backend, "ClaudeSDKClient", lambda options: FakeSdkClient(pid=None, messages=messages)
    )
    return backend.SdkBackend().write_session(spec)


def _event_meta(home: Path) -> dict:
    logs = sorted(worker.cache_dir(home).glob("steward.tool-events.*.jsonl"))
    assert len(logs) == 1, logs
    return json.loads(logs[0].read_text(encoding="utf-8").splitlines()[0])


# ------------------------------------------------------------ the copy


def test_a_finished_sessions_transcript_is_copied_into_the_cache_and_counted(seam, monkeypatch):
    home, claude_dir, spec = seam
    source = _plant_transcript(claude_dir)

    outcome = _drive(monkeypatch, spec, _messages())

    assert outcome.ok
    rel = f"sessions/steward/{RUN}/{SID}.jsonl"
    copy = worker.cache_dir(home) / rel
    assert copy.read_bytes() == source.read_bytes()
    assert (copy.parent / SID / "subagents" / "agent-a1.jsonl").is_file()
    expected = {
        "session_id": SID,
        "path": rel,
        "bytes": source.stat().st_size,
        "entries": {"assistant": 2, "system": 1, "unparsed": 1, "user": 2},
        "assistant_blocks": {"text": 2, "thinking": 1, "tool_use": 1},
        "subagent_files": 1,
        "subagent_bytes": len('{"type": "user"}\n'),
    }
    assert outcome.transcript == expected
    # The session's own journal line carries the same record ...
    assert _event_meta(home)["transcript"] == expected
    # ... whose path is relative, so the committed run records that carry
    # it pass the secret scan (an absolute cache path does not).
    assert not Path(expected["path"]).is_absolute() and scan.scan(json.dumps(expected)) == []
    # The copy outlives Claude Code's cleanup of the original.
    source.unlink()
    assert copy.is_file()


def test_a_session_that_ended_without_a_result_is_copied_by_the_id_its_messages_carried(
    seam, monkeypatch,
):
    home, claude_dir, spec = seam
    _plant_transcript(claude_dir)

    outcome = _drive(monkeypatch, spec, _messages(result=False))

    assert not outcome.ok and outcome.session_id is None  # no result message
    assert outcome.transcript is not None
    assert outcome.transcript.get("path") == f"sessions/steward/{RUN}/{SID}.jsonl"
    assert (worker.cache_dir(home) / outcome.transcript["path"]).is_file()


def test_a_missing_transcript_is_journaled_and_never_fails_the_session(seam, monkeypatch):
    home, _claude_dir, spec = seam

    outcome = _drive(monkeypatch, spec, _messages())

    assert outcome.ok and outcome.failure is None
    assert outcome.transcript == {
        "session_id": SID, "error": "no transcript file found for this session",
    }
    assert _event_meta(home)["transcript"] == outcome.transcript
    assert not session_copies.sessions_dir(home).exists()


def test_a_copy_that_raises_is_journaled_and_never_fails_the_session(seam, monkeypatch):
    home, claude_dir, spec = seam
    _plant_transcript(claude_dir)

    def refuse(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(session_copies.shutil, "copyfile", refuse)

    outcome = _drive(monkeypatch, spec, _messages())

    assert outcome.ok and outcome.failure is None
    assert outcome.transcript is not None
    assert outcome.transcript["session_id"] == SID
    assert outcome.transcript["error"] == "copy failed: OSError: disk full"
    assert _event_meta(home)["transcript"] == outcome.transcript


def test_the_setting_off_makes_no_copy_and_asks_for_no_thinking(seam, monkeypatch):
    home, claude_dir, spec = seam
    _plant_transcript(claude_dir)
    # Positive control: on (the default), the option is there.
    assert backend.options_kwargs(spec)["thinking"] == {"type": "adaptive", "display": "summarized"}

    (home / "config.yaml").write_text("sdk:\n  capture_sessions: false\n", encoding="utf-8")

    assert "thinking" not in backend.options_kwargs(spec)
    outcome = _drive(monkeypatch, spec, _messages())
    assert outcome.ok
    assert outcome.transcript is None
    assert _event_meta(home)["transcript"] is None
    assert not session_copies.sessions_dir(home).exists()


def test_summarized_thinking_reaches_claude_codes_command_line(tmp_path, monkeypatch):
    from test_invocation_sdk import FAKE_CLI, _spec

    home = tmp_path / "argv-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    argv_log = tmp_path / "argv.log"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))

    outcome = backend.SdkBackend().write_session(_spec("worker", home=home))

    assert outcome.ok
    argv = argv_log.read_text(encoding="utf-8").split("\0")
    at = argv.index("--thinking-display")
    assert argv[at + 1] == "summarized"
    assert argv[argv.index("--thinking") + 1] == "adaptive"


# ------------------------------------------------------------ run records


def _record() -> dict:
    return {"session_id": SID, "path": f"sessions/steward/{RUN}/{SID}.jsonl", "bytes": 10,
            "entries": {"assistant": 1}, "assistant_blocks": {"text": 1}}


def test_the_steward_run_record_carries_each_calls_transcript_copy(tmp_path, monkeypatch):
    from test_steward import _enable_steward, _head_manifest, _seed_fresh_proposals, _write_decision_stage

    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    record = _record()
    groups: list[str | None] = []

    def with_copy(spec):
        groups.append(spec.transcript_group)
        _write_decision_stage(spec)
        return backend.SdkOutcome(ok=True, rc=0, stdout="", detail="", failure=None,
                                  transcript=record)

    monkeypatch.setattr(steward.invocation, "write_session", with_copy)

    result = steward.run(home)

    assert groups == [result.run_id]
    attempt = _head_manifest(home, result.run_id)["packets"][0]["attempts"][0]
    assert attempt["kind"] == "decision"
    assert attempt["session"] == record


def test_the_overseer_run_record_and_journal_carry_each_phases_transcript_copy(tmp_path, monkeypatch):
    from test_overseer_run import _enabled, _fake_two_phase

    home = make_home(tmp_path)
    _enabled(monkeypatch)
    calls = _fake_two_phase(monkeypatch)
    fake = overseer_run.invocation.write_session

    def with_copy(spec):
        outcome = fake(spec)
        outcome.transcript = {**_record(), "session_id": f"sid-{len(calls)}"}
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", with_copy)

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied"
    assert [spec.transcript_group for spec in calls] == [result.run, result.run]
    sessions = execution_evidence.read_manifest(home, result.run)["sessions"]
    assert [(row["phase"], row["session_id"]) for row in sessions] == [
        ("phase-a", "sid-1"), ("phase-b", "sid-2"),
    ]
    journal = [
        json.loads(line)
        for line in overseer_run.journal_path(home).read_text(encoding="utf-8").splitlines()
    ]
    returned = {row["status"]: row for row in journal if row.get("run") == result.run}
    assert returned["phase-a-returned"]["session"]["session_id"] == "sid-1"
    assert returned["phase-b-returned"]["session"]["session_id"] == "sid-2"


# ------------------------------------------------ never fed to a model


def _plant_sentinels(home: Path) -> list[Path]:
    root = session_copies.sessions_dir(home)
    paths = []
    for surface in ("steward", "overseer", "worker"):
        path = root / surface / "run-old" / f"{SID}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "user", "message": {"content": TOKEN}}) + "\n",
                        encoding="utf-8")
        paths.append(path)
    return paths


def _texts_under(root: Path) -> list[str]:
    return [p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*") if p.is_file()]


def test_no_steward_brief_or_stage_ever_includes_a_session_copy(tmp_path, monkeypatch):
    from test_steward import _enable_steward, _seed_fresh_proposals, _write_decision_stage

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    ids = _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    sentinels = _plant_sentinels(home)
    seen: list[str] = []

    def capture(spec):
        seen.append(spec.prompt)
        seen.append(Path(spec.append_system_prompt_file).read_text(encoding="utf-8"))
        seen.extend(_texts_under(spec.cwd))
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", capture)

    result = steward.run(home)

    # Positive controls: the copies are on disk, and the brief was built.
    assert all(path.read_text(encoding="utf-8").count(TOKEN) == 1 for path in sentinels)
    assert result.calls == 1 and ids[0] in seen[0]
    assert "=== method ===" in seen[1]
    assert not [text for text in seen if TOKEN in text]


def test_no_overseer_prompt_or_workspace_ever_includes_a_session_copy(tmp_path, monkeypatch):
    from test_overseer_run import _fake_selected_phases, _seed_decided_case

    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _rid, case_id = _seed_decided_case(home, tmp_path)
    _fake_selected_phases(monkeypatch, case_id)
    sentinels = _plant_sentinels(home)
    fake = overseer_run.invocation.write_session
    seen: list[str] = []

    def capture(spec):
        seen.append(spec.prompt)
        seen.extend(_texts_under(spec.cwd))
        return fake(spec)

    monkeypatch.setattr(overseer_run.invocation, "write_session", capture)

    result = overseer_run.run(home, dry_run=True, no_push=True)

    assert result.status == "dry-run"
    assert all(path.read_text(encoding="utf-8").count(TOKEN) == 1 for path in sentinels)
    # Positive control: both phases' inputs were built and name the case.
    assert sum(case_id in text for text in seen) >= 2
    assert not [text for text in seen if TOKEN in text]

