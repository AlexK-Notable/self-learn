"""pane.py — the Iterate session manager (task U6; 09 §2.4/§4.2/§3 P1-4,
10 §3 U6 row). Covers: full lifecycle happy path (events -> SSE frames ->
transcript state, deltas live + blocks typeset), interrupt, close-discards,
the one-session-rule + armed-interrupt-then-switch, interrupt_active_session
ordering (the verb-dispatch hook), post-session validate per exit code
0/1/2, engine-start failure -> error + retry-ready state, cap-hit
messaging, no-text_delta per-block activity-indicator fallback, XSS
escaping at the SSE frame level, and first_message/excerpt composition
(delegating to self_learn.worker.canon_excerpt) across skill/project/user
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
from self_learn_ui.proposals import PROPOSAL_TOOL_QUALIFIED_NAME, VerbProposal
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


async def _start_and_join(manager: pane.PaneManager, record_id: str, **kwargs) -> str:
    """start() + wait_for_turn(): Y-15 made start return BEFORE the first
    turn completes (own test class below), so every pre-existing test
    asserting post-turn state joins the background drain explicitly."""
    outcome = await manager.start(record_id, **kwargs)
    await manager.wait_for_turn()
    return outcome


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

    outcome = await _start_and_join(manager, RECORD_ID)

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


async def test_finalize_clears_current_before_publishing_no_double_render() -> None:
    """SSE pane_block duplication bug (FW-18 fix 2): ``_finalize_current``
    appended the finalized block to ``blocks`` and then ``await``ed the
    ``pane_block`` publish BEFORE clearing ``current_kind``/``current_text``.
    A ``snapshot()`` taken during that await window (a panel GET — e.g. the
    pane_result completion swap re-fetch, or a mid-drain reload) saw the
    block BOTH in ``blocks`` AND still in-flight as ``current_html``, so the
    server-rendered panel typeset the same block twice.

    This reproduces the exact window deterministically: a hub whose
    ``publish`` takes a snapshot the instant a ``pane_block`` frame is
    published. Kill: reorder ``_finalize_current`` to await the publish
    before clearing ``current_*`` and this reddens — at publish time the
    block's text is renderable twice (``current_kind`` set, ``current_html``
    == the finalized block's html)."""

    class _SnoopHub(AppEventHub):
        def __init__(self, manager_holder: list) -> None:
            super().__init__()
            self._holder = manager_holder
            self.observations: list[dict] = []

        async def publish(self, envelope: dict) -> None:
            if envelope.get("type") == "pane_block" and self._holder:
                snap = self._holder[0].snapshot(RECORD_ID)
                self.observations.append(
                    {
                        "current_kind": snap.current_kind,
                        "current_html": snap.current_html,
                        "block_htmls": [b.html for b in snap.blocks],
                    }
                )
            await super().publish(envelope)

    holder: list = []
    hub = _SnoopHub(holder)
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
    manager, _runner, _app_hub, _refresh_hub = _manager(
        engines={RECORD_ID: engine}, app_hub=hub
    )
    holder.append(manager)

    await _start_and_join(manager, RECORD_ID)

    assert hub.observations, "a pane_block frame must have been published"
    for obs in hub.observations:
        # At the pane_block publish, the block is already in `blocks`; it
        # must NOT still be in-flight as the live block — otherwise a
        # snapshot in this window renders it twice.
        assert obs["current_kind"] is None, (
            "finalize published pane_block while current_* was still set — "
            "a snapshot here double-renders the block"
        )
        assert obs["current_html"] not in obs["block_htmls"], (
            "the finalized block's html is ALSO the live current_html — "
            "double render"
        )


async def test_result_turns_is_none_only_when_engine_reports_none() -> None:
    """When the engine genuinely reports no turn count, render None —
    never 0 or a guess (cost-honesty rule extended to turns)."""
    engine = FakeEngine(turns=[[Result(status="success", cost_usd=None, error=None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await _start_and_join(manager, RECORD_ID)
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
    await _start_and_join(manager, RECORD_ID)
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
    await _start_and_join(manager, RECORD_ID)
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
    await _start_and_join(manager, RECORD_ID)
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
    await _start_and_join(manager, RECORD_ID)
    assert await manager.interrupt("lrn-bb000002") is False


async def test_interrupt_ended_session_is_a_noop_on_the_engines_own_contract() -> None:
    """FakeEngine records interrupt() calls regardless of state (10 §3
    U5's own pinned no-op case lives in the engine, not here) — this test
    only proves the manager still routes the call through when asked."""
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await _start_and_join(manager, RECORD_ID)
    assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT
    await manager.interrupt(RECORD_ID)
    assert engine.interrupt_calls == 1


# -------------------------------------------------------------------- close


async def test_close_discards_transcript_and_returns_to_idle() -> None:
    engine = FakeEngine(
        turns=[[BlockStart(kind="text"), TextDelta(text="x"), Result("success", 0.0, None)]]
    )
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await _start_and_join(manager, RECORD_ID)
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
    await _start_and_join(manager, RECORD_ID)

    outcome = await _start_and_join(manager, "lrn-bb000002")
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
    await _start_and_join(manager, RECORD_ID)
    assert calls["n"] == 1

    outcome = await _start_and_join(manager, RECORD_ID)
    assert outcome == "resumed"
    assert calls["n"] == 1  # no second engine constructed


async def test_forced_iterate_interrupts_and_closes_the_other_session_first() -> None:
    engine_a = FakeEngine(turns=[[Result("success", 0.0, None)]])
    engine_b = FakeEngine(turns=[[Result("success", 0.0, None)]])
    manager, *_ = _manager(engines={RECORD_ID: engine_a, "lrn-bb000002": engine_b})

    await _start_and_join(manager, RECORD_ID)
    armed = await _start_and_join(manager, "lrn-bb000002")
    assert armed == "armed"

    outcome = await _start_and_join(manager, "lrn-bb000002", force=True)
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
    await _start_and_join(manager, RECORD_ID)
    assert manager.snapshot(RECORD_ID).state == pane.STATE_ENDED
    assert calls["n"] == 1

    outcome = await _start_and_join(manager, RECORD_ID)  # retry, no force
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
    await _start_and_join(manager, RECORD_ID)

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
    await _start_and_join(manager, RECORD_ID)

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
    outcome = await _start_and_join(manager, RECORD_ID)
    assert outcome == "started"
    snap = manager.snapshot(RECORD_ID)
    assert snap.state == pane.STATE_ENDED
    assert "blew up" in snap.error_message
    assert snap.cap_hit is False


@pytest.mark.parametrize("status", ["error_max_budget_usd", "error_max_turns"])
async def test_cap_hit_statuses_render_the_pinned_message(status: str) -> None:
    engine = FakeEngine(turns=[[Result(status=status, cost_usd=0.5, error="cap exceeded")]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await _start_and_join(manager, RECORD_ID)
    snap = manager.snapshot(RECORD_ID)
    assert snap.cap_hit is True
    assert snap.state == pane.STATE_ENDED
    assert snap.error_message == "cap exceeded"


async def test_non_cap_error_is_not_flagged_cap_hit() -> None:
    engine = FakeEngine(turns=[[Result(status="error_during_execution", cost_usd=None, error="boom")]])
    manager, *_ = _manager(engines={RECORD_ID: engine})
    await _start_and_join(manager, RECORD_ID)
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
    await _start_and_join(manager, RECORD_ID)
    assert manager.snapshot(RECORD_ID).state == pane.STATE_ENDED

    outcome = await manager.send(RECORD_ID, "are you still there?")
    assert outcome == "not-live"
    assert engine.sent == []


async def test_a_session_ending_in_error_never_runs_post_session_validate() -> None:
    engine = FakeEngine(turns=[[Result(status="error_during_execution", cost_usd=None, error="boom")]])
    runner = FakeRunner()
    manager, runner, *_ = _manager(engines={RECORD_ID: engine}, runner=runner)
    await _start_and_join(manager, RECORD_ID)
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
    await _start_and_join(manager, RECORD_ID)

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

    await _start_and_join(manager, RECORD_ID)

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
    await _start_and_join(manager, RECORD_ID)
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

    await _start_and_join(manager, RECORD_ID)

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
        """FW-48/U-marker-ui: the two needles come from the imported
        compiler constants — no marker spelling is typed in this test.
        (Prior to the fix this fixture hand-wrote the legacy
        ``SELF-LEARN:BEGIN``/``END`` needle, a string no compiler has
        ever emitted, so the test passed BECAUSE the code was broken;
        see u-marker-excerpt-case-spec.md §5 / the CLI sibling fix's
        own positive control in test_worker.py.) This test's own
        claim is the ±20-line WINDOW MATH given arbitrary marker
        placement — see ``test_over_threshold_finds_the_compiler_
        written_section`` below for the compiler-realistic shape."""
        from self_learn.compilers import BEGIN_MARKER, END_MARKER

        fake_home = tmp_path / "fake-home"
        (fake_home / ".claude").mkdir(parents=True)
        lines = [f"line {i}" for i in range(300)]
        lines[150] = BEGIN_MARKER
        lines[160] = END_MARKER
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
        assert BEGIN_MARKER in excerpt
        assert END_MARKER in excerpt

    def test_over_threshold_finds_the_compiler_written_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FW-48/U-marker-ui's positive control, mirrored from the CLI
        sibling fix (test_worker.py::test_canon_excerpt_finds_the_
        compiler_written_markers_in_a_fat_target): the excerpt must
        reach a section the REAL compiler wrote
        (``compile_managed_text``), not a hand-placed sentinel. Red
        pre-fix — the unfixed pane hand-copy searched for a needle
        (``SELF-LEARN:BEGIN``) the compiler has never written, so it
        fell through to the head-of-file truncation regardless of
        where the real section landed."""
        from self_learn.compilers import BEGIN_MARKER, END_MARKER, compile_managed_text, entry_line

        fake_home = tmp_path / "fake-home"
        (fake_home / ".claude").mkdir(parents=True)
        routed_record = make_behavior(record_id="lrn-aa000014")
        routed_record.set_routing(
            {"routed_at": "2026-07-13T18:02:00Z", "destination": "claude-md", "by": "human"}
        )
        routed_record.set_status("routed")

        leading = "\n".join(f"authored line {i}" for i in range(250))
        trailing = "\n".join(f"trailing line {i}" for i in range(30))
        compiled = compile_managed_text(leading, [routed_record])
        full_text = compiled.text + trailing + "\n"
        (fake_home / ".claude" / "CLAUDE.md").write_text(full_text, encoding="utf-8")
        monkeypatch.setenv("HOME", str(fake_home))

        lines = full_text.splitlines()
        begin_idx = next(i for i, ln in enumerate(lines) if BEGIN_MARKER in ln)
        end_idx = next(i for i, ln in enumerate(lines) if END_MARKER in ln)
        # Fixture guard: without this, the test would pass pre-fix
        # whenever the section happened to land inside the first 60
        # lines — same rationale as the CLI sibling's A0.
        assert len(lines) >= 200
        assert begin_idx > 60

        record = make_behavior(scope="user", record_id="lrn-aa000015")
        excerpt = pane.target_canon_excerpt(tmp_path, record, tmp_path / "bucket")
        excerpt_lines = excerpt.splitlines()

        assert BEGIN_MARKER in excerpt
        assert END_MARKER in excerpt
        assert entry_line(routed_record) in excerpt_lines  # the payload, not just the frame
        lo, hi = max(0, begin_idx - 20), min(len(lines), end_idx + 21)
        assert excerpt_lines == lines[lo:hi]

    def test_over_threshold_case_variant_of_compiler_marker_does_not_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FW-48/U-marker-ui's negative control, mirrored from the CLI
        sibling fix (test_worker.py::test_canon_excerpt_case_variant_
        of_compiler_marker_does_not_match): a case-variant of the
        compiler's own marker must NOT match — catches a "defensive"
        case-folded fix (``BEGIN_MARKER.lower() in ln.lower()``) that
        would silently reinstate the legacy needle's failure mode by a
        different route. Both needles are derived from the imported
        constants; no marker spelling is typed in this build."""
        from self_learn.compilers import BEGIN_MARKER, END_MARKER

        fake_home = tmp_path / "fake-home"
        (fake_home / ".claude").mkdir(parents=True)
        lines = [f"line {i}" for i in range(300)]
        lines[150] = BEGIN_MARKER.upper()
        lines[160] = END_MARKER.upper()
        (fake_home / ".claude" / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(fake_home))
        record = make_behavior(scope="user", record_id="lrn-aa000016")
        excerpt = pane.target_canon_excerpt(tmp_path, record, tmp_path / "bucket")
        assert excerpt.splitlines() == [f"line {i}" for i in range(60)] + ["… (truncated)"]

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
        await _start_and_join(manager, RECORD_ID)
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
        await _start_and_join(manager, RECORD_ID)
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
        await _start_and_join(manager, RECORD_ID)
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
        await _start_and_join(manager, RECORD_ID)
        snap = manager.snapshot(RECORD_ID)
        assert snap.state == pane.STATE_ENDED
        await engine.close()  # already closed once by the error path or here
        assert await manager.teardown_parked() is True  # second close: no raise


# ------------------------------------------- Y-15 non-blocking start


class _GatedEngine(PaneEngine):
    """FakeEngine variant whose start() blocks on ``gate`` before yielding
    — the Y-15 test gate: start() must return (and the split must be
    renderable) while this still waits."""

    def __init__(self, events, send_events=()) -> None:
        self.gate = __import__("asyncio").Event()
        self._events = list(events)
        self._send_events = list(send_events)
        self.started = False
        self.sent: list[str] = []
        self.interrupt_calls = 0
        self.close_calls = 0

    async def start(self, ctx: PaneContext):
        self.started = True
        await self.gate.wait()
        for event in self._events:
            yield event

    async def send(self, text: str):
        self.sent.append(text)
        for event in self._send_events:
            yield event

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class _StubbornEngine(PaneEngine):
    """Swallows the drain task's cancellation at its gate — the F3
    identity-guard belt's target: a callee that suppresses
    CancelledError (the bounded-per-callee caveat 09 §4.2 records for
    the real SDK, reproduced deliberately)."""

    def __init__(self) -> None:
        self.gate = __import__("asyncio").Event()
        self.started = False
        self.interrupt_calls = 0
        self.close_calls = 0

    async def start(self, ctx: PaneContext):
        import asyncio

        self.started = True
        while not self.gate.is_set():
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                continue  # deliberately stubborn
        yield TextDelta(text="late orphan text")
        yield Result(status="success", cost_usd=None, error=None)

    async def send(self, text: str):
        raise RuntimeError("never")
        yield  # pragma: no cover

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def _slot_proposal(session_key: str, record_id: str = RECORD_ID) -> VerbProposal:
    return VerbProposal(
        verb="defer", record_id=record_id, bucket_scope="skill",
        bucket_name="s", session_key=session_key, title="T",
        dest=None, note=None, until=None,
    )


class TestNonBlockingStart:
    """09 §4.2 "Start is non-blocking" (§11 Y-15, feedback round 2
    item 1) — the pinned obligations, each named after its review
    finding."""

    async def test_start_returns_before_the_first_turn_completes(self) -> None:
        import asyncio

        engine = _GatedEngine(
            [BlockStart(kind="text"), TextDelta(text="hi"), Result("success", 0.0, None)]
        )
        manager, _runner, app_hub, _refresh = _manager(engines={RECORD_ID: engine})
        sub = app_hub.subscribe()

        outcome = await manager.start(RECORD_ID)

        assert outcome == "started"
        snap = manager.snapshot(RECORD_ID)
        assert snap.state == pane.STATE_STARTING  # the POST renders THIS
        assert snap.blocks == ()

        await asyncio.sleep(0)  # background task runs up to the gate
        assert engine.started is True
        assert manager.snapshot(RECORD_ID).state == pane.STATE_STREAMING
        assert await _drain_queue(sub) == []  # gate closed — nothing streamed yet
        assert manager.has_interruptible_session() is True  # Y-14 leg holds mid-drain

        engine.gate.set()
        await manager.wait_for_turn()

        frames = await _drain_queue(sub)
        types = [f["type"] for f in frames]
        # SSE observed from the BACKGROUND drain — the one transport.
        assert "pane_delta" in types
        assert "pane_result" in types
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT

    async def test_slot_claim_is_synchronous_under_concurrent_starts(self) -> None:
        # F5: guard->assignment has no await, so the first coroutine to
        # run claims and the second takes the armed prompt — never two
        # engines, regardless of arrival interleaving.
        import asyncio

        manager, *_ = _manager()
        outcomes = await asyncio.gather(
            manager.start(RECORD_ID), manager.start("lrn-bb000002")
        )
        assert outcomes == ["started", "armed"]
        assert manager.active_record_id == RECORD_ID
        await manager.wait_for_turn()

    async def test_second_start_same_key_during_background_turn_resumes(self) -> None:
        engine = _GatedEngine([Result("success", 0.0, None)])
        manager, *_ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        assert await manager.start(RECORD_ID) == "resumed"  # never a second engine
        engine.gate.set()
        await manager.wait_for_turn()

    async def test_send_mid_turn_never_dispatches_a_second_engine_turn(self) -> None:
        # The F2 named test: send dispatches ONLY at awaiting-input.
        import asyncio

        engine = _GatedEngine(
            [BlockStart(kind="text"), Result("success", 0.0, None)],
            send_events=[Result("success", 0.0, None)],
        )
        manager, *_ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        assert await manager.send(RECORD_ID, "impatient") == "busy"  # STARTING
        await asyncio.sleep(0)
        assert await manager.send(RECORD_ID, "still impatient") == "busy"  # STREAMING
        assert engine.sent == []  # the engine never saw a second turn

        engine.gate.set()
        await manager.wait_for_turn()
        assert await manager.send(RECORD_ID, "now") == "sent"
        assert engine.sent == ["now"]

    async def test_exception_in_drain_lands_ended_clears_slot_and_pushes_result(self) -> None:
        # F1's exception leg: the wrapper publishes pane_result so the
        # completion swap fires on EVERY completion path; the §4.5
        # clear-set error leg is anchored at drain completion.
        manager, _runner, app_hub, _refresh = _manager(default_engine_factory=_RaisingEngine)
        sub = app_hub.subscribe()
        assert await manager.start(RECORD_ID) == "started"
        manager.proposal_slot.occupy(_slot_proposal(RECORD_ID))
        await manager.wait_for_turn()

        snap = manager.snapshot(RECORD_ID)
        assert snap.state == pane.STATE_ENDED
        assert snap.error_message is not None and "blew up" in snap.error_message
        assert manager.proposal_slot.current is None
        frames = await _drain_queue(sub)
        assert {"type": "pane_result", "status": "error", "cost": None, "turns": None} in frames

    async def test_interrupt_before_the_turn_connects_parks_ended_without_starting(self) -> None:
        # F4, pre-connect window: Esc lands before the background task
        # has run at all — the turn must never dispatch, and the session
        # terminates promptly (ENDED + completion push).
        engine = _GatedEngine([Result("success", 0.0, None)])
        manager, _runner, app_hub, _refresh = _manager(engines={RECORD_ID: engine})
        sub = app_hub.subscribe()
        await manager.start(RECORD_ID)

        assert await manager.interrupt(RECORD_ID) is True
        assert manager.snapshot(RECORD_ID).state == pane.STATE_INTERRUPTING
        await manager.wait_for_turn()

        snap = manager.snapshot(RECORD_ID)
        assert snap.state == pane.STATE_ENDED
        assert engine.started is False  # the turn never dispatched
        assert snap.error_message is not None
        assert "interrupted before the conversation started" in snap.error_message
        frames = await _drain_queue(sub)
        assert any(f["type"] == "pane_result" for f in frames)

    async def test_interrupt_during_starting_replays_at_first_post_connect_boundary(self) -> None:
        # F4, post-connect: the latch re-delivers an Esc the pre-connect
        # engine call may have silently no-op'd (idempotent — delta R4).
        import asyncio

        engine = _GatedEngine(
            [BlockStart(kind="text"), TextDelta(text="x"), Result("success", 0.0, None)]
        )
        manager, *_ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        await asyncio.sleep(0)  # connected, parked at the gate
        assert engine.started is True

        assert await manager.interrupt(RECORD_ID) is True
        calls_at_esc = engine.interrupt_calls
        engine.gate.set()
        await manager.wait_for_turn()
        assert engine.interrupt_calls == calls_at_esc + 1  # replayed once post-connect

    async def test_teardown_cancels_or_awaits_the_drain_before_returning(self) -> None:
        # F3, first half: by the time any teardown path returns, the
        # predecessor's drain cannot run again — a successor claims a
        # clean slot.
        import asyncio

        engine = _GatedEngine([TextDelta(text="never delivered")])
        manager, _runner, app_hub, _refresh = _manager(engines={RECORD_ID: engine})
        sub = app_hub.subscribe()
        await manager.start(RECORD_ID)
        await asyncio.sleep(0)
        live = manager._live
        assert live is not None and live.drain_task is not None
        task = live.drain_task

        assert await manager.interrupt_active_session(RECORD_ID) is True
        assert task.done()  # cancelled-or-awaited BEFORE the teardown returned
        assert manager.active_record_id is None

        engine.gate.set()  # releasing the gate later changes nothing
        await asyncio.sleep(0)
        assert await _drain_queue(sub) == []

    async def test_orphaned_drain_publishes_nothing_and_clears_nothing(self) -> None:
        # F3, second half (the identity-guard belt): a drain whose
        # callee swallowed the cancellation still publishes nothing and
        # clears nothing once it is no longer manager-current — the
        # r-retry same-key window can never wipe a successor's slot.
        import asyncio

        engine = _StubbornEngine()
        manager, _runner, app_hub, _refresh = _manager(engines={RECORD_ID: engine})
        sub = app_hub.subscribe()
        await manager.start(RECORD_ID)
        await asyncio.sleep(0)  # parked at the gate

        teardown = asyncio.create_task(manager.interrupt_active_session(RECORD_ID))
        await asyncio.sleep(0)  # dispose issued the cancel; engine swallowed it
        engine.gate.set()  # the orphan runs on — into the identity guard
        assert await teardown is True

        successor = _slot_proposal("lrn-bb000002", record_id="lrn-bb000002")
        manager.proposal_slot.occupy(successor)
        await asyncio.sleep(0)

        frames = await _drain_queue(sub)
        assert not any(f.get("text") == "late orphan text" for f in frames)
        assert manager.proposal_slot.current is successor  # never wiped

    async def test_retry_same_key_disposes_the_predecessors_drain_first(self) -> None:
        # F3 at the r-retry seam: an ENDED predecessor's drain is joined
        # before the successor claims.
        calls = {"n": 0}

        def factory() -> PaneEngine:
            calls["n"] += 1
            if calls["n"] == 1:
                return _RaisingEngine()
            return FakeEngine(turns=[[Result("success", 0.0, None)]])

        manager, *_ = _manager(default_engine_factory=factory)
        await _start_and_join(manager, RECORD_ID)
        assert manager.snapshot(RECORD_ID).state == pane.STATE_ENDED

        outcome = await _start_and_join(manager, RECORD_ID)
        assert outcome == "started"
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT

    async def test_bucket_session_background_start_and_no_validate(self) -> None:
        # The bucket variant shares the manager and the whole Y-15
        # contract; its clean result still owes no proposal-validate
        # (09 §4.5: bucket sessions write nothing).
        key = pane.bucket_session_key("skill", "s")
        engine = _GatedEngine(
            [BlockStart(kind="text"), TextDelta(text="queue answer"), Result("success", 0.0, None)]
        )
        manager, runner, app_hub, _refresh = _manager(engines={key: engine})
        sub = app_hub.subscribe()

        assert await manager.start(key) == "started"
        assert manager.snapshot(key).state == pane.STATE_STARTING
        engine.gate.set()
        await manager.wait_for_turn()

        assert manager.snapshot(key).state == pane.STATE_AWAITING_INPUT
        assert runner.calls == []  # no validate obligation for bucket sessions
        frames = await _drain_queue(sub)
        assert any(f["type"] == "pane_result" for f in frames)

    async def test_post_session_validate_fires_after_the_background_drain(self) -> None:
        # The 08 §7.1 obligation, unmoved: validate fires when the
        # BACKGROUND drain's clean result lands — not at POST return.
        import asyncio

        engine = _GatedEngine([Result("success", 0.0, None)])
        runner = FakeRunner()
        runner.queue_result(RunResult(0))
        manager, runner, _app_hub, _refresh = _manager(engines={RECORD_ID: engine}, runner=runner)
        await manager.start(RECORD_ID)
        await asyncio.sleep(0)
        assert runner.calls == []  # not yet — the turn is still in flight
        engine.gate.set()
        await manager.wait_for_turn()
        assert runner.calls == [["proposal", "validate", RECORD_ID]]


class _SlowValidateRunner(FakeRunner):
    """Blocks inside the post-session validate — pins the code-review
    MAJOR-1 window: the turn is not over until validate completes, so a
    send landing between the Result event and validate's return must be
    "busy", never a concurrent second engine turn."""

    def __init__(self) -> None:
        import asyncio

        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, argv: list[str]) -> RunResult:
        self.entered.set()
        await self.release.wait()
        return await super().run(argv)


class TestPostResultValidateWindow:
    """Code-review fold (MAJOR-1 + MINOR-1 + NIT-1/NIT-3 branch tests)."""

    async def test_send_during_the_post_result_validate_window_is_busy(self) -> None:
        engine = FakeEngine(
            turns=[
                [Result("success", 0.0, None)],
                [Result("success", 0.0, None)],
            ]
        )
        runner = _SlowValidateRunner()
        runner.queue_result(RunResult(0))
        runner.queue_result(RunResult(0))
        # Keep `runner` bound to the _SlowValidateRunner it already is —
        # _manager returns the same object, but rebinding through its
        # FakeRunner-typed tuple would erase the subclass for pyright.
        manager, _runner, app_hub, _refresh = _manager(engines={RECORD_ID: engine}, runner=runner)
        sub = app_hub.subscribe()

        await manager.start(RECORD_ID)
        await runner.entered.wait()  # the drain is INSIDE validate now

        # pane_result already went out (R2 at-least-once) but the turn
        # is NOT over — awaiting-input arrives only after validate.
        frames = await _drain_queue(sub)
        assert any(f["type"] == "pane_result" for f in frames)
        assert manager.snapshot(RECORD_ID).state == pane.STATE_STREAMING
        assert await manager.send(RECORD_ID, "sneaky mid-validate send") == "busy"
        assert engine.sent == []  # the engine never saw it

        runner.release.set()
        await manager.wait_for_turn()
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT
        assert await manager.send(RECORD_ID, "now") == "sent"
        assert engine.sent == ["now"]

    async def test_retry_closes_the_predecessors_engine(self) -> None:
        # MINOR-1: an errored/cap-hit session's engine was never closed
        # by its own turn — the r-retry same-key branch closes it before
        # the successor claims (no orphaned SDK/CLI child per retry).
        first = _RaisingEngine()
        engines_iter = iter([first, FakeEngine(turns=[[Result("success", 0.0, None)]])])
        manager, *_ = _manager(default_engine_factory=lambda: next(engines_iter))

        await _start_and_join(manager, RECORD_ID)
        assert manager.snapshot(RECORD_ID).state == pane.STATE_ENDED
        assert first.close_calls == 0

        assert await _start_and_join(manager, RECORD_ID) == "started"
        assert first.close_calls == 1
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT

    async def test_concurrent_claim_during_the_retry_dispose_window(self) -> None:
        # NIT-3 (the F5 sub-claim): a start landing while the retry is
        # inside its dispose/close awaits wins the slot; the retry's
        # re-guard loop yields "armed" — never a clobbered claimant.
        import asyncio

        class _SlowCloseEngine(PaneEngine):
            def __init__(self) -> None:
                self.gate = asyncio.Event()
                self.interrupt_calls = 0
                self.close_calls = 0

            async def start(self, ctx: PaneContext):
                raise RuntimeError("first engine dies")
                yield  # pragma: no cover

            async def send(self, text: str):
                raise RuntimeError("never")
                yield  # pragma: no cover

            async def interrupt(self) -> None:
                self.interrupt_calls += 1

            async def close(self) -> None:
                self.close_calls += 1
                await self.gate.wait()

        slow = _SlowCloseEngine()
        calls = {"n": 0}

        def factory() -> PaneEngine:
            calls["n"] += 1
            return slow if calls["n"] == 1 else FakeEngine(turns=[[Result("success", 0.0, None)]])

        manager, *_ = _manager(default_engine_factory=factory)
        await _start_and_join(manager, RECORD_ID)
        assert manager.snapshot(RECORD_ID).state == pane.STATE_ENDED

        retry = asyncio.create_task(manager.start(RECORD_ID))
        await asyncio.sleep(0)  # retry parked inside old.engine.close()
        assert manager.active_record_id is None  # the dispose window is open

        assert await manager.start("lrn-bb000002") == "started"  # concurrent claim
        slow.gate.set()
        assert await retry == "armed"  # the re-guard loop, not a clobber
        assert manager.active_record_id == "lrn-bb000002"
        await manager.wait_for_turn()

    async def test_esc_during_the_validate_window_never_interrupts_the_next_turn(self) -> None:
        # Delta residual on the MAJOR-1 fold: the validate window is
        # INTERRUPTIBLE (state stays streaming) — an Esc there latches,
        # the tail parks awaiting-input WITHOUT clearing the latch, and
        # without the per-turn reset the user's NEXT send turn would
        # replay engine.interrupt() at its first event, interrupting the
        # very turn they just asked for.
        engine = FakeEngine(
            turns=[
                [Result("success", 0.0, None)],
                [BlockStart(kind="text"), TextDelta(text="reply"), Result("success", 0.0, None)],
            ]
        )
        runner = _SlowValidateRunner()
        runner.queue_result(RunResult(0))
        runner.queue_result(RunResult(0))
        manager, _runner, *_ = _manager(engines={RECORD_ID: engine}, runner=runner)

        await manager.start(RECORD_ID)
        await runner.entered.wait()  # inside the validate window
        assert await manager.interrupt(RECORD_ID) is True  # Esc lands here
        calls_after_esc = engine.interrupt_calls

        runner.release.set()
        await manager.wait_for_turn()
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT  # tail parks

        assert await manager.send(RECORD_ID, "follow-up") == "sent"
        # ZERO replays into the new turn — the stale latch was reset at
        # the turn's drain entry.
        assert engine.interrupt_calls == calls_after_esc
        assert manager.snapshot(RECORD_ID).state == pane.STATE_AWAITING_INPUT


# ------------------------------------------------ U21 post-iterate summary


def _route_proposal(
    session_key: str = RECORD_ID,
    record_id: str = RECORD_ID,
    dest: str | None = "skill-md",
    bucket_scope: str = "skill",
) -> VerbProposal:
    return VerbProposal(
        verb="route", record_id=record_id, bucket_scope=bucket_scope,
        bucket_name="s", session_key=session_key, title="T",
        dest=dest, note=None, until=None,
    )


class _MidGatedEngine(PaneEngine):
    """Yields *before* events, waits on ``gate``, then yields *after*
    events — lets a test inject a proposal-slot mutation BETWEEN a
    propose_verb ToolUse and the turn's Result (U21 gate R5's
    current-turn-attribution tests need to control what the slot looks
    like at each of those two moments, which a plain FakeEngine's
    unpaused event list cannot do)."""

    def __init__(self, before, after) -> None:
        self.gate = __import__("asyncio").Event()
        self._before = list(before)
        self._after = list(after)
        self.interrupt_calls = 0
        self.close_calls = 0

    async def start(self, ctx: PaneContext):
        for event in self._before:
            yield event
        await self.gate.wait()
        for event in self._after:
            yield event

    async def send(self, text: str):
        raise RuntimeError("never")
        yield  # pragma: no cover

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class TestComposeFileFacts:
    """Unit — the drain-accumulation classification (§3's own test list):
    record file -> "the lesson text"; proposal sibling (yaml or diff) ->
    "the proposal"; other path -> shortened; none -> "nothing". Pure
    function, no engine/manager machinery."""

    def test_record_file_classifies_as_the_lesson_text(self) -> None:
        path = f"/x/bucket/pending/{RECORD_ID}.md"
        assert pane._compose_file_facts(RECORD_ID, [path]) == "the lesson text"

    def test_proposal_yaml_sibling_classifies_as_the_proposal(self) -> None:
        path = f"/x/bucket/proposals/{RECORD_ID}.yaml"
        assert pane._compose_file_facts(RECORD_ID, [path]) == "the proposal"

    def test_proposal_diff_sibling_also_classifies_as_the_proposal(self) -> None:
        path = f"/x/bucket/proposals/{RECORD_ID}.diff"
        assert pane._compose_file_facts(RECORD_ID, [path]) == "the proposal"

    def test_other_path_is_shown_shortened(self) -> None:
        path = "/x/bucket/other/unrelated.md"
        assert pane._compose_file_facts(RECORD_ID, [path]) == "other/unrelated.md"

    def test_no_paths_is_nothing(self) -> None:
        assert pane._compose_file_facts(RECORD_ID, []) == "nothing"

    def test_dedups_repeated_paths_and_joins_distinct_facts(self) -> None:
        lesson = f"/x/bucket/pending/{RECORD_ID}.md"
        proposal = f"/x/bucket/proposals/{RECORD_ID}.yaml"
        facts = pane._compose_file_facts(RECORD_ID, [proposal, lesson, proposal])
        assert facts == "the proposal and the lesson text"

    def test_bare_record_id_without_lrn_prefix_still_matches_the_stem(self) -> None:
        # _record_stem mirrors engine/charter.py's own tolerant stem
        # derivation — a bare id (no "lrn-" prefix) still classifies
        # correctly against the lrn-prefixed on-disk filename.
        bare = "aa000001"
        path = "/x/bucket/pending/lrn-aa000001.md"
        assert pane._compose_file_facts(bare, [path]) == "the lesson text"


class TestProposalClauseGloss:
    """Verb/destination glossed via ``models.destination_label`` (F5-9's
    single-source resolver over ``_GROUP_LABELS`` — reused, never a
    second map)."""

    def test_route_with_dest_names_verb_and_glossed_destination(self) -> None:
        proposal = _route_proposal(dest="skill-md")
        assert pane._proposal_clause(proposal) == "route to Skill doc"

    def test_parameterized_dest_glosses_by_its_base(self) -> None:
        proposal = _route_proposal(dest="new-skill:foo")
        assert pane._proposal_clause(proposal) == "route to New skill"

    def test_verb_without_dest_names_the_bare_verb(self) -> None:
        proposal = VerbProposal(
            verb="reject", record_id=RECORD_ID, bucket_scope="skill",
            bucket_name="s", session_key=RECORD_ID, title="T",
        )
        assert pane._proposal_clause(proposal) == "reject"

    def test_single_source_no_second_label_map(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A source assertion (F5-9's own guard, mirrored): monkeypatching
        # the SHARED map changes the render — proving there is no
        # second, independent label table for this line.
        from self_learn_ui import models

        monkeypatch.setitem(models._GROUP_LABELS, "skill-md", "MONKEYPATCHED")
        assert pane._proposal_clause(_route_proposal(dest="skill-md")) == "route to MONKEYPATCHED"

    @pytest.mark.parametrize(
        "bucket_scope,label",
        [
            ("user", "User instructions"),
            ("project", "Project instructions"),
            ("skill", "Skills repo instructions"),
        ],
    )
    def test_claude_md_dest_glosses_by_the_proposals_own_bucket_scope(
        self, bucket_scope: str, label: str
    ) -> None:
        # A1 (O-2 d): the F-1 fix at the pane one-liner — claude-md now
        # threads proposal.bucket_scope through destination_label,
        # instead of the scope-blind default "Project instructions".
        # The exact-string equality (never just `in`) also proves no
        # path is appended here (P-A12 is bound to Detail/action-bar
        # only, never the terse pane clause).
        proposal = _route_proposal(dest="claude-md", bucket_scope=bucket_scope)
        assert pane._proposal_clause(proposal) == f"route to {label}"

    def test_rules_variant_dest_glosses_with_topic_never_the_plain_label(self) -> None:
        # A2 §11: proposal.dest is the pane's ONLY variant signal
        # (proposals.py's _DEST_RE qualified-string grammar) — the terse
        # clause must show "User rule — subagents", not fall back to the
        # variant-blind "User instructions" a partition(":")[0]-only read
        # would produce.
        proposal = _route_proposal(dest="claude-md:rules:subagents", bucket_scope="user")
        assert pane._proposal_clause(proposal) == "route to User rule — subagents"

    def test_local_variant_dest_glosses_as_personal_notes(self) -> None:
        proposal = _route_proposal(dest="claude-md:local", bucket_scope="project")
        assert pane._proposal_clause(proposal) == "route to Personal project notes"


class TestPostIterateSummaryIntegration:
    """PaneManager-level: the footer line's full wiring — drain
    accumulation -> Result-time composition -> snapshot persistence."""

    async def test_footer_line_present_after_result_and_on_re_render(self) -> None:
        # "present again on snapshot re-render (navigation-return
        # regression)" — snapshot() is called twice, exactly like a
        # panel GET followed by a later plain Detail reload would.
        lesson_path = f"/x/bucket/pending/{RECORD_ID}.md"
        engine = FakeEngine(turns=[[FileChanged(path=lesson_path), Result("success", 0.0, None)]])
        manager, *_ = _manager(engines={RECORD_ID: engine})

        await _start_and_join(manager, RECORD_ID)
        first = manager.snapshot(RECORD_ID)
        assert first.turn_summary == "This turn changed: the lesson text."

        second = manager.snapshot(RECORD_ID)  # the re-render
        assert second.turn_summary == first.turn_summary

    async def test_no_file_changes_and_no_proposal_renders_nothing(self) -> None:
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        manager, *_ = _manager(engines={RECORD_ID: engine})
        await _start_and_join(manager, RECORD_ID)
        assert manager.snapshot(RECORD_ID).turn_summary == "This turn changed: nothing."

    async def test_proposal_placed_this_turn_names_the_glossed_verb(self) -> None:
        import asyncio

        engine = _MidGatedEngine(
            before=[ToolUse(name=PROPOSAL_TOOL_QUALIFIED_NAME, target=None)],
            after=[Result("success", 0.0, None)],
        )
        manager, *_ = _manager(engines={RECORD_ID: engine})

        await manager.start(RECORD_ID)
        await asyncio.sleep(0)  # background drain runs up to the ToolUse + gate
        # Simulate the propose_verb handler's effect: the slot was EMPTY
        # when the ToolUse landed (nonce_before captured as None), and is
        # now occupied by THIS turn's proposal.
        manager.proposal_slot.occupy(_route_proposal(dest="skill-md"))
        engine.gate.set()
        await manager.wait_for_turn()

        snap = manager.snapshot(RECORD_ID)
        assert snap.turn_summary == "This turn changed: nothing, and proposed: route to Skill doc."

    async def test_tooluse_without_a_placed_proposal_names_no_clause(self) -> None:
        # Signal (a) present, (b) absent (the handler refused for a
        # reason that never occupies the slot, e.g. an invalid verb) —
        # either alone is insufficient.
        import asyncio

        engine = _MidGatedEngine(
            before=[ToolUse(name=PROPOSAL_TOOL_QUALIFIED_NAME, target=None)],
            after=[Result("success", 0.0, None)],
        )
        manager, *_ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        await asyncio.sleep(0)
        # slot stays empty — the handler's refusal never occupies it.
        engine.gate.set()
        await manager.wait_for_turn()
        assert manager.snapshot(RECORD_ID).turn_summary == "This turn changed: nothing."

    async def test_waiting_proposal_without_a_tooluse_names_no_clause(self) -> None:
        # Signal (b) present, (a) absent — a proposal is waiting in the
        # slot but THIS turn's drain never saw a propose_verb ToolUse at
        # all (e.g. it was placed by an earlier session's turn and this
        # turn did nothing proposal-related).
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        manager, *_ = _manager(engines={RECORD_ID: engine})
        manager.proposal_slot.occupy(_route_proposal(dest="skill-md"))
        await _start_and_join(manager, RECORD_ID)
        assert manager.snapshot(RECORD_ID).turn_summary == "This turn changed: nothing."

    async def test_r5_edge_prior_turn_waiting_proposal_never_misattributes(self) -> None:
        # The R5 disaster case, pinned as a negative: a PRIOR turn's
        # still-waiting proposal already occupies the slot when THIS
        # turn's propose_verb ToolUse lands; the real handler would
        # refuse it (refuse-not-replace, slot already occupied) and
        # leave the slot UNCHANGED — simulated here by simply never
        # touching the slot during the gated window.
        import asyncio

        prior = _route_proposal(dest="claude-md")
        engine = _MidGatedEngine(
            before=[ToolUse(name=PROPOSAL_TOOL_QUALIFIED_NAME, target=None)],
            after=[Result("success", 0.0, None)],
        )
        manager, *_ = _manager(engines={RECORD_ID: engine})
        manager.proposal_slot.occupy(prior)

        await manager.start(RECORD_ID)
        await asyncio.sleep(0)  # ToolUse processed; nonce_before captured == prior.nonce
        # THIS turn's call was refused by slot-occupancy — nothing changes.
        engine.gate.set()
        await manager.wait_for_turn()

        snap = manager.snapshot(RECORD_ID)
        assert snap.turn_summary == "This turn changed: nothing."
        assert "proposed" not in snap.turn_summary
        # The prior proposal is still exactly where it was — untouched,
        # never misattributed and never cleared by this turn's summary.
        assert manager.proposal_slot.current is prior

    async def test_armed_proposal_never_counts_as_waiting(self) -> None:
        # (b) requires a WAITING (never armed) proposal — an armed one
        # is mid human-confirm, not a fresh this-turn placement.
        import asyncio

        engine = _MidGatedEngine(
            before=[ToolUse(name=PROPOSAL_TOOL_QUALIFIED_NAME, target=None)],
            after=[Result("success", 0.0, None)],
        )
        manager, *_ = _manager(engines={RECORD_ID: engine})
        await manager.start(RECORD_ID)
        await asyncio.sleep(0)
        manager.proposal_slot.occupy(_route_proposal(dest="skill-md"))
        manager.proposal_slot.arm(RECORD_ID)
        engine.gate.set()
        await manager.wait_for_turn()
        assert manager.snapshot(RECORD_ID).turn_summary == "This turn changed: nothing."

    async def test_bucket_session_matches_by_session_key_not_record_id(self) -> None:
        # A bucket session's live.record_id is the SYNTHETIC bucket key
        # (pane.bucket_session_key), never a real record id — but its
        # propose_verb call names a real PENDING RECORD elsewhere in the
        # bucket. VerbProposal.session_key carries the bucket key
        # (the same identity clear_for_session already matches on);
        # VerbProposal.record_id carries the named record instead. The
        # attribution match MUST use session_key, or a bucket session's
        # own successful proposal would never be attributed to it.
        import asyncio

        key = pane.bucket_session_key("skill", "s")
        engine = _MidGatedEngine(
            before=[ToolUse(name=PROPOSAL_TOOL_QUALIFIED_NAME, target=None)],
            after=[Result("success", 0.0, None)],
        )
        manager, *_ = _manager(engines={key: engine})
        await manager.start(key)
        await asyncio.sleep(0)
        manager.proposal_slot.occupy(
            _route_proposal(session_key=key, record_id="lrn-cc000003", dest="claude-md")
        )
        engine.gate.set()
        await manager.wait_for_turn()

        snap = manager.snapshot(key)
        # A1: _route_proposal hardcodes bucket_scope="skill" (below), so
        # the claude-md gloss is the honest skill-scope label, not the
        # scope-blind "Project instructions".
        assert snap.turn_summary == "This turn changed: nothing, and proposed: route to Skills repo instructions."
