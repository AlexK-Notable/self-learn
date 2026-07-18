"""pane.py — the Iterate session manager (task U6; 09 §2.4/§4.2/§3 P1-4,
10 §3 U6 row). Covers: full lifecycle happy path (events -> SSE frames ->
transcript state, deltas live + blocks typeset), interrupt, close-discards,
the one-session-rule + armed-interrupt-then-switch, interrupt_active_session
ordering (the verb-dispatch hook), post-session validate per exit code
0/1/2, engine-start failure -> error + retry-ready state, cap-hit
messaging, no-text_delta per-block activity-indicator fallback, XSS
escaping at the SSE frame level, and first_message/excerpt composition
(mirroring self_learn.worker's excerpt rule) across skill/project/user
scope and the <200-line / marker-bounded branches.

No network, no real model anywhere in this file (10 §0 rule 7) — every
engine here is either FakeEngine or a tiny local raising double.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn_ui import pane
from self_learn_ui.engine.base import (
    BlockStart,
    FakeEngine,
    FileChanged,
    PaneContext,
    PaneEngine,
    Result,
    TextDelta,
    ToolUse,
)
from self_learn_ui.ledger import RefreshHub, locate_record, read_diff, read_proposal_raw, read_record
from self_learn_ui.proposals import VerbProposal
from self_learn_ui.runner import FakeRunner, RunResult
from self_learn_ui.sse import AppEventHub

from support import make_behavior, make_env, seed_proposal, seed_record

RECORD_ID = "lrn-aa000001"


# --------------------------------------------------------------- test doubles


class _RaisingEngine(PaneEngine):
    """A PaneEngine whose start() raises before yielding anything —
    09 §5's "pane engine start fails" row."""

    def __init__(self) -> None:
        self.interrupt_calls = 0
        self.close_calls = 0

    async def start(self, ctx: PaneContext):
        raise RuntimeError("engine start blew up")
        yield  # pragma: no cover - unreachable, keeps this a generator fn

    async def send(self, text: str):
        raise RuntimeError("should not be called")
        yield  # pragma: no cover

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def _ctx(record_id: str = RECORD_ID) -> PaneContext:
    return PaneContext(
        record_id=record_id,
        bucket_root=Path("/tmp/bucket"),
        self_learn_home=Path("/tmp/home"),
        system_prompt="doctrine",
        first_message="first message",
    )


def _manager(
    *,
    engines: dict[str, PaneEngine] | None = None,
    default_engine_factory=None,
    runner: FakeRunner | None = None,
    app_hub: AppEventHub | None = None,
    refresh_hub: RefreshHub | None = None,
) -> tuple[pane.PaneManager, FakeRunner, AppEventHub, RefreshHub]:
    """``engines`` lets a test pin exactly which engine instance a given
    record_id's ``start()`` call gets (so the test can assert on THAT
    instance's interrupt/close counters afterward); falls back to a fresh
    FakeEngine (or ``default_engine_factory()``) per unseen record_id."""
    engines = engines or {}
    runner = runner if runner is not None else FakeRunner()
    app_hub = app_hub if app_hub is not None else AppEventHub()
    refresh_hub = refresh_hub if refresh_hub is not None else RefreshHub()

    def engine_factory_for(record_id: str) -> PaneEngine:
        if record_id in engines:
            return engines[record_id]
        return default_engine_factory() if default_engine_factory else FakeEngine()

    # PaneManager's engine_factory takes no args (fresh engine per Iterate,
    # 09 §4.2) — the record_id it's being started for is threaded through
    # a closure keyed by the LAST context_builder call, mirroring how
    # build_pane_manager's own closures work in production.
    state = {"record_id": None}

    def context_builder(record_id: str) -> PaneContext:
        state["record_id"] = record_id
        return _ctx(record_id)

    def engine_factory() -> PaneEngine:
        return engine_factory_for(state["record_id"])

    manager = pane.PaneManager(
        engine_factory=engine_factory,
        context_builder=context_builder,
        app_hub=app_hub,
        refresh_hub=refresh_hub,
        runner=runner,
    )
    return manager, runner, app_hub, refresh_hub


async def _drain_queue(hub_queue) -> list[dict]:
    out = []
    while not hub_queue.empty():
        out.append(hub_queue.get_nowait())
    return out


# ------------------------------------------------------------- happy path


async def test_full_lifecycle_happy_path_publishes_sse_and_typesets_blocks() -> None:
    engine = FakeEngine(
        turns=[
            [
                BlockStart(kind="text"),
                TextDelta(text="Hello "),
                TextDelta(text="world"),
                ToolUse(name="Read", target="/x/record.md"),
                Result(status="success", cost_usd=0.01, error=None),
            ]
        ]
    )
    manager, runner, app_hub, refresh_hub = _manager(engines={RECORD_ID: engine})
    sub = app_hub.subscribe()

    outcome = await manager.start(RECORD_ID)

    assert outcome == "started"
    assert engine.started is True
    assert engine.contexts[0].first_message == "first message"

    snap = manager.snapshot(RECORD_ID)
    assert snap.state == pane.STATE_AWAITING_INPUT
    assert [b.kind for b in snap.blocks] == ["text", "tool"]
    assert "Hello" in snap.blocks[0].html and "world" in snap.blocks[0].html
    assert snap.blocks[1].tool_name == "Read"
    assert snap.blocks[1].tool_target == "/x/record.md"
    assert snap.result_status == "success"
    assert snap.result_cost_usd == 0.01
    assert snap.error_message is None
    assert snap.cap_hit is False

    envelopes = await _drain_queue(sub)
    types = [e["type"] for e in envelopes]
    # deltas live, the text block finalizes at the next boundary (a
    # ToolUse event finalizes the pending text block, chronologically —
    # see pane.py's _handle_event), then the tool line, then the result
    # footer.
    assert types == ["pane_delta", "pane_delta", "pane_block", "pane_tool", "pane_result"]
    assert envelopes[0]["text"] == "Hello "
    assert envelopes[1]["text"] == "world"
    assert "Hello" in envelopes[2]["html"]
    assert envelopes[4] == {"type": "pane_result", "status": "success", "cost": 0.01, "turns": None}


async def test_result_turns_is_none_only_when_engine_reports_none() -> None:
    """When the engine genuinely reports no turn count, render None —
    never 0 or a guess (cost-honesty rule extended to turns)."""
    engine = FakeEngine(turns=[[Result(status="success", cost_usd=None, error=None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    snap = manager.snapshot(RECORD_ID)
    assert snap.result_turns is None
    assert snap.result_cost_usd is None  # absent cost renders as absent, never 0


async def test_result_turns_flows_to_snapshot_and_envelope() -> None:
    """A real engine-reported turn count (ResultMessage.num_turns → the
    seam's Result.turns) must reach BOTH the snapshot and the pane_result
    SSE envelope — the interim-review seam gap was closed, and the pane
    hop must not re-drop it (final-review MINOR: this hop had no positive
    test, so a regression to hardwired None here would pass silently)."""
    engine = FakeEngine(
        turns=[[Result(status="success", cost_usd=0.02, error=None, turns=7)]]
    )
    manager, runner, app_hub, refresh_hub = _manager(engines={RECORD_ID: engine})
    sub = app_hub.subscribe()
    await manager.start(RECORD_ID)
    snap = manager.snapshot(RECORD_ID)
    assert snap.result_turns == 7
    envelopes = await _drain_queue(sub)
    result_env = next(e for e in envelopes if e["type"] == "pane_result")
    assert result_env["turns"] == 7


# -------------------------------------------------------- no text_delta


async def test_no_text_delta_renders_activity_indicator_state() -> None:
    """09 §5: coarse/no partial streaming -> per-block fallback with an
    activity indicator. A block that opens and never gets a delta before
    the turn ends (no Result either — engine just stops) leaves the pane
    in a state where current_kind is set but current_html is empty."""
    engine = FakeEngine(turns=[[BlockStart(kind="text")]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    snap = manager.snapshot(RECORD_ID)
    assert snap.current_kind == "text"
    assert snap.current_html == ""
    assert snap.blocks == ()  # never finalized — no boundary event arrived
    assert snap.state == pane.STATE_AWAITING_INPUT


# --------------------------------------------------------------- interrupt


async def test_interrupt_proxies_to_engine_and_preserves_transcript() -> None:
    engine = FakeEngine(
        turns=[[BlockStart(kind="text"), TextDelta(text="partial"), Result("success", 0.0, None)]]
    )
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    assert manager.snapshot(RECORD_ID).blocks  # something is already there

    ok = await manager.interrupt(RECORD_ID)
    assert ok is True
    assert engine.interrupt_calls == 1
    # 09 §4.2: "interrupting never discards file changes already written"
    # — the transcript survives the interrupt call.
    assert manager.snapshot(RECORD_ID).blocks


async def test_interrupt_on_a_different_or_absent_record_is_a_noop() -> None:
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    assert await manager.interrupt("lrn-bb000002") is False


async def test_interrupt_ended_session_is_a_noop_on_the_engines_own_contract() -> None:
    """FakeEngine records interrupt() calls regardless of state (10 §3
    U5's own pinned no-op case lives in the engine, not here) — this test
    only proves the manager still routes the call through when asked."""
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT
    await manager.interrupt(RECORD_ID)
    assert engine.interrupt_calls == 1


# -------------------------------------------------------------------- close


async def test_close_discards_transcript_and_returns_to_idle() -> None:
    engine = FakeEngine(
        turns=[[BlockStart(kind="text"), TextDelta(text="x"), Result("success", 0.0, None)]]
    )
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    assert manager.snapshot(RECORD_ID).blocks

    ok = await manager.close(RECORD_ID)
    assert ok is True
    assert engine.close_calls == 1
    snap = manager.snapshot(RECORD_ID)
    assert snap.state == pane.STATE_IDLE
    assert snap.blocks == ()
    assert manager.active_record_id is None


async def test_close_on_absent_session_is_a_noop() -> None:
    manager, *_ = _manager()
    assert await manager.close(RECORD_ID) is False


# --------------------------------------------------------- one-session-rule


async def test_iterate_on_another_record_while_live_returns_armed() -> None:
    engine_a = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine_a})
    await manager.start(RECORD_ID)

    outcome = await manager.start("lrn-bb000002")
    assert outcome == "armed"
    assert manager.active_record_id == RECORD_ID  # untouched
    assert engine_a.interrupt_calls == 0
    assert engine_a.close_calls == 0


async def test_double_iterate_on_the_same_live_record_resumes_without_a_new_engine() -> None:
    calls = {"n": 0}
    engine = FakeEngine(turns=[[]])  # no Result -> stays effectively open

    def factory() -> PaneEngine:
        calls["n"] += 1
        return engine

    manager, *_ = _manager(default_engine_factory=factory)
    # First start leaves the session in STREAMING conceptually, but our
    # FakeEngine turn (empty) ends immediately -> AWAITING_INPUT. Force a
    # non-ended state directly to exercise the "still live" branch without
    # depending on FakeEngine's own timing.
    await manager.start(RECORD_ID)
    assert calls["n"] == 1

    outcome = await manager.start(RECORD_ID)
    assert outcome == "resumed"
    assert calls["n"] == 1  # no second engine constructed


async def test_forced_iterate_interrupts_and_closes_the_other_session_first() -> None:
    engine_a = FakeEngine(turns=[[Result("success", 0.0, None)]])
    engine_b = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine_a, "lrn-bb000002": engine_b})

    await manager.start(RECORD_ID)
    armed = await manager.start("lrn-bb000002")
    assert armed == "armed"

    outcome = await manager.start("lrn-bb000002", force=True)
    assert outcome == "started"
    assert engine_a.interrupt_calls == 1
    assert engine_a.close_calls == 1
    assert manager.active_record_id == "lrn-bb000002"
    assert engine_b.started is True


async def test_retry_after_ended_session_starts_a_fresh_engine() -> None:
    """r retry (09 §5): the SAME record's ENDED (errored) session is
    cleared and a fresh engine constructed — force is not needed for a
    same-record retry."""
    calls = {"n": 0}

    def factory() -> PaneEngine:
        calls["n"] += 1
        if calls["n"] == 1:
            return _RaisingEngine()
        return FakeEngine(turns=[[Result("success", 0.0, None)]])

    manager, *_ = _manager(default_engine_factory=factory)
    await manager.start(RECORD_ID)
    assert manager.snapshot(RECORD_ID).state == pane.STATE_ENDED
    assert calls["n"] == 1

    outcome = await manager.start(RECORD_ID)  # retry, no force
    assert outcome == "started"
    assert calls["n"] == 2
    assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT


# ------------------------------------------------------ interrupt_active_session


async def test_interrupt_active_session_calls_interrupt_before_teardown() -> None:
    """09 §3 P1-4 — the ONE hook a verb-dispatch site awaits before
    resolving a record under active iteration. Ordering asserted: engine
    interrupt() happens (never skipped), then the session is fully torn
    down (P3-7's resurrection vector — never left half-live against files
    a verb is about to move)."""
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)

    ok = await manager.interrupt_active_session(RECORD_ID)

    assert ok is True
    assert engine.interrupt_calls == 1
    assert engine.close_calls == 1
    assert manager.active_record_id is None
    # A resolution verb dispatched right after this call sees NO live
    # session in its way — the serialization contract routes.py relies on.
    assert manager.snapshot(RECORD_ID).state == pane.STATE_IDLE


async def test_interrupt_active_session_is_a_noop_for_an_unrelated_record() -> None:
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)

    ok = await manager.interrupt_active_session("lrn-bb000002")

    assert ok is False
    assert engine.interrupt_calls == 0
    assert manager.active_record_id == RECORD_ID  # the live session survives


async def test_interrupt_active_session_with_no_live_session_at_all() -> None:
    manager, *_ = _manager()
    assert await manager.interrupt_active_session(RECORD_ID) is False


# ----------------------------------------------------------- cap hit / errors


async def test_engine_start_failure_ends_the_session_with_an_error() -> None:
    manager, *_ = _manager(default_engine_factory=_RaisingEngine)
    outcome = await manager.start(RECORD_ID)
    assert outcome == "started"
    snap = manager.snapshot(RECORD_ID)
    assert snap.state == pane.STATE_ENDED
    assert "blew up" in snap.error_message
    assert snap.cap_hit is False


@pytest.mark.parametrize("status", ["error_max_budget_usd", "error_max_turns"])
async def test_cap_hit_statuses_render_the_pinned_message(status: str) -> None:
    engine = FakeEngine(turns=[[Result(status=status, cost_usd=0.5, error="cap exceeded")]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    snap = manager.snapshot(RECORD_ID)
    assert snap.cap_hit is True
    assert snap.state == pane.STATE_ENDED
    assert snap.error_message == "cap exceeded"


async def test_non_cap_error_is_not_flagged_cap_hit() -> None:
    engine = FakeEngine(turns=[[Result(status="error_during_execution", cost_usd=None, error="boom")]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    snap = manager.snapshot(RECORD_ID)
    assert snap.cap_hit is False
    assert snap.state == pane.STATE_ENDED


async def test_send_on_an_ended_session_is_a_noop_never_touches_the_dead_engine() -> None:
    """09 §5: 'cap hit -> r to continue in a FRESH session' — an ENDED
    session is not continuable by send(), only by start()'s retry path.
    Calling send() anyway must not reach the (already torn-down-ish)
    engine at all."""
    engine = FakeEngine(turns=[[Result(status="error_during_execution", cost_usd=None, error="boom")]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await manager.start(RECORD_ID)
    assert manager.snapshot(RECORD_ID).state == pane.STATE_ENDED

    outcome = await manager.send(RECORD_ID, "are you still there?")
    assert outcome == "not-live"
    assert engine.sent == []


async def test_a_session_ending_in_error_never_runs_post_session_validate() -> None:
    engine = FakeEngine(turns=[[Result(status="error_during_execution", cost_usd=None, error="boom")]])
    runner = FakeRunner()
    manager, runner, *_ = _manager(engines={RECORD_ID: engine}, runner=runner)
    await manager.start(RECORD_ID)
    assert runner.calls == []  # 09 §4.3: validate runs only on a CLEAN result


# ------------------------------------------------------- mid-session file_changed


async def test_file_changed_forces_a_refresh_never_a_validate_call() -> None:
    engine = FakeEngine(
        turns=[[FileChanged(path="/x/pending/lrn-aa000001.md"), Result("success", 0.0, None)]]
    )
    runner = FakeRunner()
    refresh_hub = RefreshHub()
    sub = refresh_hub.subscribe()
    manager, runner, _app_hub, refresh_hub = _manager(
        engines={RECORD_ID: engine}, runner=runner, refresh_hub=refresh_hub
    )
    await manager.start(RECORD_ID)

    # One force_refresh from FileChanged, one more from the post-session
    # validate's own refresh (exit 0) — never a validate call triggered
    # BY the file_changed event itself (task brief: "never validation").
    assert runner.calls == [["proposal", "validate", RECORD_ID]]
    events = []
    while not sub.empty():
        events.append(sub.get_nowait())
    scopes = [e.scope for e in events]
    assert scopes.count(f"record:{RECORD_ID}") >= 1


# --------------------------------------------------------- post-session validate


@pytest.mark.parametrize(
    "exit_code,stderr",
    [
        (0, ""),
        (1, "self-learn: schema-invalid"),
        (2, "self-learn: secret scan hit"),
    ],
)
async def test_post_session_validate_exit_code_discrimination(exit_code: int, stderr: str) -> None:
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    runner = FakeRunner()
    runner.queue_result(RunResult(exit_code, stderr=stderr))
    manager, runner, _app_hub, refresh_hub = _manager(engines={RECORD_ID: engine}, runner=runner)
    sub = refresh_hub.subscribe()

    await manager.start(RECORD_ID)

    assert runner.calls == [["proposal", "validate", RECORD_ID]]
    assert manager.validate_state(RECORD_ID) == (exit_code, stderr)
    snap = manager.snapshot(RECORD_ID)
    assert snap.validate_exit_code == exit_code
    assert snap.validate_stderr == stderr
    # A refresh is forced regardless of exit code (0 -> the fresh badge
    # flips via ledger data on the next read; 1/2 -> the caller renders
    # the error strip from THIS snapshot, but the record view still
    # re-reads current file state).
    assert not sub.empty()


async def test_validate_result_persists_after_close_never_stderr_parsed_for_logic() -> None:
    """09 §4.3: 'a scan hit badges the item scan-blocked UNTIL a
    re-validate exits 0' — survives the pane session ending. The
    discrimination is exit-code only; stderr is carried verbatim, never
    inspected for content."""
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    runner = FakeRunner()
    runner.queue_result(RunResult(2, stderr="some arbitrary text, not parsed"))
    manager, runner, *_ = _manager(engines={RECORD_ID: engine}, runner=runner)
    await manager.start(RECORD_ID)
    await manager.close(RECORD_ID)

    snap = manager.snapshot(RECORD_ID)
    assert snap.state == pane.STATE_IDLE  # session is gone
    assert snap.validate_exit_code == 2  # badge state is NOT
    assert snap.validate_stderr == "some arbitrary text, not parsed"


# --------------------------------------------------------------------- XSS


async def test_xss_payload_in_pane_text_is_escaped_at_the_sse_frame_level() -> None:
    payload = "<script>alert(1)</script>"
    engine = FakeEngine(
        turns=[[BlockStart(kind="text"), TextDelta(text=payload), Result("success", 0.0, None)]]
    )
    manager, _runner, app_hub, _refresh_hub = _manager(engines={RECORD_ID: engine})
    sub = app_hub.subscribe()

    await manager.start(RECORD_ID)

    envelopes = await _drain_queue(sub)
    block_envelope = next(e for e in envelopes if e["type"] == "pane_block")
    assert "<script>" not in block_envelope["html"]
    assert "&lt;script&gt;" in block_envelope["html"]

    # The equivalent finalized block in the pull-based snapshot (what a
    # plain page render/reconnect sees) is escaped the same way — same
    # primitive, page and SSE frame alike (rendering.py's own contract).
    snap = manager.snapshot(RECORD_ID)
    assert "<script>" not in snap.blocks[0].html
    assert "&lt;script&gt;" in snap.blocks[0].html


# ------------------------------------------------------- excerpt / first_message


class TestTargetCanonExcerpt:
    def test_skill_scope_whole_file_under_threshold(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s",))
        record = make_behavior(scope="skill:s", record_id="lrn-aa000009")
        excerpt = pane.target_canon_excerpt(sb.ledger, record, sb.ledger / "skills" / "s")
        assert "Authored prose stays put." in excerpt

    def test_project_scope_reads_the_registered_host_claude_md(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        record = make_behavior(scope="project", record_id="lrn-aa00000a")
        seed_record(sb.ledger, record, project_path=sb.host)
        from self_learn.hosts import slug_for

        bucket_dir = sb.ledger / "projects" / slug_for(sb.host)
        excerpt = pane.target_canon_excerpt(sb.ledger, record, bucket_dir)
        assert "Authored context stays put." in excerpt

    def test_project_scope_unresolvable_without_meta_yaml(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        record = make_behavior(scope="project", record_id="lrn-aa00000b")
        bucket_dir = tmp_path / "no-meta-bucket"
        bucket_dir.mkdir()
        excerpt = pane.target_canon_excerpt(sb.ledger, record, bucket_dir)
        assert "unresolvable" in excerpt

    def test_skill_scope_unresolvable_without_registered_skills_root(self, tmp_path: Path) -> None:
        home = tmp_path / "bare-ledger"
        home.mkdir()
        record = make_behavior(scope="skill:nope", record_id="lrn-aa00000c")
        excerpt = pane.target_canon_excerpt(home, record, tmp_path / "bucket")
        assert "unresolvable" in excerpt

    def test_target_file_missing_yet(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
        (tmp_path / "fake-home").mkdir()
        record = make_behavior(scope="user", record_id="lrn-aa00000d")
        excerpt = pane.target_canon_excerpt(tmp_path, record, tmp_path / "bucket")
        assert "does not exist yet" in excerpt

    def test_whole_file_passthrough_under_200_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "fake-home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "CLAUDE.md").write_text("short doc\nline two\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(fake_home))
        record = make_behavior(scope="user", record_id="lrn-aa00000e")
        excerpt = pane.target_canon_excerpt(tmp_path, record, tmp_path / "bucket")
        assert excerpt == "short doc\nline two"

    def test_over_threshold_excerpts_around_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "fake-home"
        (fake_home / ".claude").mkdir(parents=True)
        lines = [f"line {i}" for i in range(300)]
        lines[150] = "<!-- SELF-LEARN:BEGIN -->"
        lines[160] = "<!-- SELF-LEARN:END -->"
        (fake_home / ".claude" / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(fake_home))
        record = make_behavior(scope="user", record_id="lrn-aa00000f")
        excerpt = pane.target_canon_excerpt(tmp_path, record, tmp_path / "bucket")
        # lo = max(0, 150-20) = 130; hi = min(len, 160+20+1) = 181 ->
        # lines[130:181] covers indices 130..180 inclusive.
        assert "line 130" in excerpt
        assert "line 180" in excerpt
        assert "line 129" not in excerpt
        assert "line 181" not in excerpt

    def test_over_threshold_no_markers_truncates_first_60(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "fake-home"
        (fake_home / ".claude").mkdir(parents=True)
        lines = [f"line {i}" for i in range(300)]
        (fake_home / ".claude" / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(fake_home))
        record = make_behavior(scope="user", record_id="lrn-aa000010")
        excerpt = pane.target_canon_excerpt(tmp_path, record, tmp_path / "bucket")
        assert "line 0" in excerpt
        assert "line 59" in excerpt
        assert "truncated" in excerpt
        assert "line 60" not in excerpt


class TestComposeFirstMessage:
    def test_includes_record_body_and_no_analysis_marker_when_no_proposal(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path, skills=("s",))
        record = make_behavior(scope="skill:s", record_id="lrn-aa000011")
        seed_record(sb.ledger, record)
        location = locate_record(sb.ledger, record.id)
        loaded = read_record(location.path)
        msg = pane.compose_first_message(
            home=sb.ledger,
            location=location,
            record=loaded,
            proposal=None,
            diff_text=None,
            proposal_raw_text=None,
        )
        assert loaded.body in msg
        assert "no proposal yet" in msg
        assert "CANDIDATE TARGET CANON EXCERPT" in msg
        assert "Authored prose stays put." in msg  # the real SKILL.md content

    def test_includes_proposal_and_diff_when_present(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s",))
        record = make_behavior(scope="skill:s", record_id="lrn-aa000012")
        seed_record(sb.ledger, record)
        seed_proposal(sb.ledger, record.id)
        location = locate_record(sb.ledger, record.id)
        loaded = read_record(location.path)
        proposal, _err = read_proposal_raw(location.bucket_dir, record.id)
        diff_path = location.bucket_dir / "proposals" / f"{record.id}.diff"
        diff_path.write_text("--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")
        diff_text = read_diff(location.bucket_dir, record.id)

        msg = pane.compose_first_message(
            home=sb.ledger,
            location=location,
            record=loaded,
            proposal=proposal,
            diff_text=diff_text,
            proposal_raw_text=None,
        )
        assert "EXISTING PROPOSAL" in msg
        assert "skill-md" in msg  # proposal_dict()'s destination
        assert "PROPOSAL DIFF" in msg
        assert "+new" in msg


class TestBuildPaneContext:
    def test_composes_a_full_pane_context(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s",))
        record = make_behavior(scope="skill:s", record_id="lrn-aa000013")
        seed_record(sb.ledger, record)
        ctx = pane.build_pane_context(
            sb.ledger, record.id, read_doctrine_fn=lambda: "COMPILED DOCTRINE TEXT"
        )
        assert ctx.record_id == record.id
        assert ctx.self_learn_home == sb.ledger
        assert ctx.bucket_root == sb.ledger / "skills" / "s"
        assert ctx.system_prompt == "COMPILED DOCTRINE TEXT"
        assert record.body in ctx.first_message

    def test_unknown_record_raises_lookup_error(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        with pytest.raises(LookupError):
            pane.build_pane_context(sb.ledger, "lrn-ffffffff")


# --------------------------------------------- Y-14 idle-lifecycle surfaces


class TestIdleLifecycleSurfaces:
    """has_interruptible_session / teardown_parked (10 §3 U13) against
    the REAL PaneManager + FakeEngine — the monitor-side behavior is in
    test_idle.py against a FakePane; this class pins the two surfaces'
    real semantics, including the delta-R4 idempotence case."""

    async def test_streaming_session_is_interruptible_parked_is_not(self) -> None:
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="hi"),
                    Result(status="success", cost_usd=0.0, error=None)]]
        )
        manager, _, _, _ = _manager(engines={RECORD_ID: engine})
        assert manager.has_interruptible_session() is False  # no session
        await manager.start(RECORD_ID)
        # FakeEngine turns drain synchronously in start() -> parked at
        # awaiting-input by the time start() returns.
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT
        assert manager.has_interruptible_session() is False

    async def test_teardown_parked_tears_down_awaiting_input(self) -> None:
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="hi"),
                    Result(status="success", cost_usd=0.0, error=None)]]
        )
        manager, _, _, _ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT
        assert await manager.teardown_parked() is True
        # standard teardown ran: engine interrupted + closed, no live left
        assert engine.interrupt_calls == 1
        assert engine.close_calls == 1
        assert manager.active_record_id is None
        assert manager.snapshot(RECORD_ID).state == pane.STATE_IDLE

    async def test_teardown_parked_noop_without_session(self) -> None:
        manager, _, _, _ = _manager()
        assert await manager.teardown_parked() is False

    async def test_teardown_parked_clears_proposal_slot(self) -> None:
        # Y-13 clear-set: teardown ends the proposing session.
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="hi"),
                    Result(status="success", cost_usd=0.0, error=None)]]
        )
        manager, _, _, _ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        proposal = VerbProposal(
            verb="defer", record_id=RECORD_ID, bucket_scope="skill",
            bucket_name="s", session_key=RECORD_ID, title="T",
            dest=None, note=None, until=None,
        )
        manager.proposal_slot.occupy(proposal)
        assert manager.proposal_slot.current is not None
        assert await manager.teardown_parked() is True
        assert manager.proposal_slot.current is None

    async def test_teardown_parked_idempotent_against_ended_engine(self) -> None:
        # Delta R4: a parked ENDED session's engine may already be
        # closed (error paths) — teardown must not raise.
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="x"),
                    Result(status="error", cost_usd=0.0, error="boom")]]
        )
        manager, _, _, _ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        snap = manager.snapshot(RECORD_ID)
        assert snap.state == pane.STATE_ENDED
        await engine.close()  # already closed once by the error path or here
        assert await manager.teardown_parked() is True  # second close: no raise
