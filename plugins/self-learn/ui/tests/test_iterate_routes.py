"""Iterate split routes (task U6; 09 §2.4, 10 §3 U6 row): the Detail-page
split render, /pane/start|send|interrupt|close|retry|panel, the armed
one-session-rule prompt, the verb-dispatch interrupt-first wiring in
action_confirm/graduate_bulk, post-session validate exit-code rendering,
and the "pane manager not wired" 503 degradation (09 §5's "adjudication
never depends on any optional subsystem" invariant).

httpx against the ASGI app, in-process, exactly T-A's established pattern
(test_routes.py) — FakeEngine + FakeRunner, no network, no real model.
"""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from self_learn_ui import pane
from self_learn_ui.app import create_app
from self_learn_ui.engine.base import BlockStart, FakeEngine, Result, TextDelta
from self_learn_ui.env import load_env
from self_learn_ui.runner import FakeRunner, RunResult

from support import make_behavior, make_env, seed_record

TOKEN = "test-token"
HX = {"HX-Request": "true"}


def make_client(sb, *, runner: FakeRunner | None = None, port: int = 7357) -> tuple[TestClient, FakeRunner]:
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    return c, runner


def make_client_with_pane(
    sb, *, engines: dict[str, FakeEngine] | None = None, runner: FakeRunner | None = None, port: int = 7357
) -> tuple[TestClient, FakeRunner, "pane.PaneManager"]:
    """Same as make_client, but with a REAL PaneManager wired onto
    app.state — this is exactly the "one line" app.py's create_app()
    will apply at merge (pane.build_pane_manager); tests set the
    attribute directly since app.py itself is off-limits to this track."""
    c, runner = make_client(sb, runner=runner, port=port)
    app = c.app
    engines = engines or {}
    state = {"record_id": None}

    def context_builder(record_id: str) -> "pane.PaneContext":
        state["record_id"] = record_id
        # Doctrine sourced from a fixed string, never the real tracked
        # files/cache (10 §0 rule 7/8) — the excerpt/record/proposal
        # composition still exercises the REAL ledger reads.
        return pane.build_pane_context(sb.ledger, record_id, read_doctrine_fn=lambda: "DOCTRINE")

    def engine_factory() -> FakeEngine:
        return engines.get(state["record_id"], FakeEngine())

    manager = pane.PaneManager(
        engine_factory=engine_factory,
        context_builder=context_builder,
        app_hub=app.state.app_hub,
        refresh_hub=app.state.refresh_hub,
        runner=runner,
    )
    app.state.pane_manager = manager
    return c, runner, manager


def _seed(tmp_path: Path):
    sb = make_env(tmp_path, skills=("s",))
    rec = make_behavior(scope="skill:s")
    seed_record(sb.ledger, rec)
    return sb, rec


# ------------------------------------------------------- pane manager absent


class TestPaneManagerNotWired:
    def test_start_degrades_to_503_never_500(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        c, _runner = make_client(sb)
        # create_app() wires a real pane manager by default since the
        # U6 merge — force the not-wired state the degrade path guards
        # (09 §5: adjudication never depends on an optional subsystem).
        c.app.state.pane_manager = None
        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert r.status_code == 503

    def test_detail_page_still_renders_without_pane_manager(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'data-key-action="iterate"' in r.text


# ------------------------------------------------------------------ Detail


class TestDetailSplitRendering:
    def test_no_session_renders_iterate_control_not_split(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        c, _runner, _manager = make_client_with_pane(sb)
        r = c.get(f"/record/{rec.id}")
        assert r.status_code == 200
        assert 'data-key-action="iterate"' in r.text
        assert "pane-block" not in r.text

    def test_live_session_renders_the_split(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="analysis text"), Result("success", 0.01, None)]]
        )
        c, runner, _manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))  # the post-session validate call

        start = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert start.status_code == 200
        assert "analysis text" in start.text
        assert 'data-key-action="close_pane"' in start.text

        detail = c.get(f"/record/{rec.id}")
        assert 'class="detail-left"' in detail.text
        assert 'class="detail-right"' in detail.text
        assert "analysis text" in detail.text


# --------------------------------------------------------------- happy path


class TestPaneStartSendInterruptClose:
    def test_start_renders_transcript_and_result_footer(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="hello there"), Result("success", 0.02, None)]]
        )
        c, runner, _manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))

        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert r.status_code == 200
        assert "hello there" in r.text
        assert "success" in r.text
        assert "0.0200" in r.text
        # AWAITING_INPUT: nothing in flight -> no interrupt control.
        assert 'data-key-action="interrupt"' not in r.text
        assert engine.started is True

    def test_send_continues_the_same_session(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[
                [Result("success", 0.0, None)],
                [BlockStart(kind="text"), TextDelta(text="follow-up reply"), Result("success", 0.0, None)],
            ]
        )
        c, runner, _manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        runner.queue_result(RunResult(0))

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        r = c.post(f"/record/{rec.id}/pane/send", data={"text": "please clarify"}, headers=HX)
        assert r.status_code == 200
        assert "follow-up reply" in r.text
        assert engine.sent == ["please clarify"]

    def test_interrupt_calls_engine_interrupt(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        c.post(f"/record/{rec.id}/pane/start", headers=HX)

        r = c.post(f"/record/{rec.id}/pane/interrupt", headers=HX)
        assert r.status_code == 200
        assert engine.interrupt_calls == 1

    def test_close_discards_and_redirects_to_plain_detail(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="x"), Result("success", 0.0, None)]]
        )
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert manager.snapshot(rec.id).blocks

        r = c.post(f"/record/{rec.id}/pane/close", headers=HX)
        assert r.status_code == 200
        assert r.headers.get("hx-redirect") == f"/record/{rec.id}"
        assert engine.close_calls == 1
        assert manager.snapshot(rec.id).state == pane.STATE_IDLE

        detail = c.get(f"/record/{rec.id}")
        assert 'data-key-action="iterate"' in detail.text
        assert "pane-block" not in detail.text


# --------------------------------------------------------------- cap hit / r


class _RaisingEngine:
    """A minimal PaneEngine-shaped double whose start() raises before
    yielding — 09 §5's "pane engine start fails" row, exercised at the
    route level (mirrors test_pane.py's identical-purpose double)."""

    def __init__(self) -> None:
        self.interrupt_calls = 0
        self.close_calls = 0
        self.sent: list[str] = []

    async def start(self, ctx):
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    async def send(self, text: str):
        raise RuntimeError("should not be called")
        yield  # pragma: no cover

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class TestEngineStartFailure:
    def test_start_failure_renders_error_and_retry(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        c, runner, manager = make_client_with_pane(sb)
        manager._engine_factory = _RaisingEngine  # type: ignore[method-assign]

        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert r.status_code == 200
        assert "connection refused" in r.text
        assert 'data-key-action="retry"' in r.text
        assert runner.calls == []  # no validate call on a failed session


class TestCapHitAndRetry:
    def test_cap_hit_renders_pinned_message_and_retry_button(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[[Result(status="error_max_budget_usd", cost_usd=1.0, error="budget exceeded")]]
        )
        c, runner, _manager = make_client_with_pane(sb, engines={rec.id: engine})

        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert "cap hit — r to continue in a fresh session" in r.text
        assert 'data-key-action="retry"' in r.text
        # An ENDED session is not continuable by send() — only by retry.
        assert 'data-key-action="pane_send"' not in r.text
        # A capped/errored turn never reaches the post-session validate.
        assert runner.calls == []

    def test_retry_starts_a_fresh_engine_after_error(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        calls = {"n": 0}

        def factory() -> FakeEngine:
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeEngine(turns=[[Result(status="error_during_execution", cost_usd=None, error="boom")]])
            return FakeEngine(turns=[[Result("success", 0.0, None)]])

        c, runner = make_client(sb)
        manager = pane.PaneManager(
            engine_factory=factory,
            context_builder=lambda rid: pane.build_pane_context(sb.ledger, rid, read_doctrine_fn=lambda: "D"),
            app_hub=c.app.state.app_hub,
            refresh_hub=c.app.state.refresh_hub,
            runner=runner,
        )
        c.app.state.pane_manager = manager
        runner.queue_result(RunResult(0))

        first = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert "boom" in first.text

        second = c.post(f"/record/{rec.id}/pane/retry", headers=HX)
        assert second.status_code == 200
        assert calls["n"] == 2
        assert "boom" not in second.text


# ------------------------------------------------------- post-session validate


class TestPostSessionValidateBadges:
    def test_exit_0_shows_no_badge(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, _manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert "scan-blocked" not in r.text
        assert "schema invalid" not in r.text

    def test_exit_1_shows_schema_invalid_strip(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, _manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(1, stderr="self-learn: schema-invalid, missing rationale"))
        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert "schema invalid" in r.text
        assert "missing rationale" in r.text

    def test_exit_2_shows_scan_blocked_badge(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(2, stderr="self-learn: secret scan hit"))
        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert "scan-blocked" in r.text
        assert "secret scan hit" in r.text

        # Persists across a `q` close AND a plain Detail reload (09 §4.3:
        # "until a re-validate exits 0").
        c.post(f"/record/{rec.id}/pane/close", headers=HX)
        detail = c.get(f"/record/{rec.id}")
        assert "scan-blocked" in detail.text
        assert manager.validate_state(rec.id) == (2, "self-learn: secret scan hit")


# ------------------------------------------------------------- one-session-rule


class TestOneSessionRule:
    def test_iterate_elsewhere_while_live_returns_armed_prompt(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s",))
        rec_a = make_behavior(scope="skill:s", record_id="lrn-aa000001")
        rec_b = make_behavior(scope="skill:s", record_id="lrn-aa000002")
        seed_record(sb.ledger, rec_a)
        seed_record(sb.ledger, rec_b)
        engine_a = FakeEngine(turns=[[Result("success", 0.0, None)]])
        engine_b = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(
            sb, engines={rec_a.id: engine_a, rec_b.id: engine_b}
        )
        runner.queue_result(RunResult(0))

        c.post(f"/record/{rec_a.id}/pane/start", headers=HX)
        assert manager.active_record_id == rec_a.id

        armed = c.post(f"/record/{rec_b.id}/pane/start", headers=HX)
        assert armed.status_code == 200
        assert rec_a.id in armed.text
        assert "Interrupt" in armed.text
        assert manager.active_record_id == rec_a.id  # untouched
        assert engine_a.interrupt_calls == 0

    def test_confirming_the_armed_prompt_switches_sessions(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s",))
        rec_a = make_behavior(scope="skill:s", record_id="lrn-aa000001")
        rec_b = make_behavior(scope="skill:s", record_id="lrn-aa000002")
        seed_record(sb.ledger, rec_a)
        seed_record(sb.ledger, rec_b)
        engine_a = FakeEngine(turns=[[Result("success", 0.0, None)]])
        engine_b = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="record b analysis"), Result("success", 0.0, None)]]
        )
        c, runner, manager = make_client_with_pane(
            sb, engines={rec_a.id: engine_a, rec_b.id: engine_b}
        )
        runner.queue_result(RunResult(0))
        runner.queue_result(RunResult(0))

        c.post(f"/record/{rec_a.id}/pane/start", headers=HX)
        r = c.post(f"/record/{rec_b.id}/pane/start", data={"force": "true"}, headers=HX)

        assert r.status_code == 200
        assert "record b analysis" in r.text
        assert engine_a.interrupt_calls == 1
        assert engine_a.close_calls == 1
        assert manager.active_record_id == rec_b.id

    def test_cancel_returns_to_idle_panel_without_side_effects(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s",))
        rec_a = make_behavior(scope="skill:s", record_id="lrn-aa000001")
        rec_b = make_behavior(scope="skill:s", record_id="lrn-aa000002")
        seed_record(sb.ledger, rec_a)
        seed_record(sb.ledger, rec_b)
        engine_a = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec_a.id: engine_a})
        runner.queue_result(RunResult(0))
        c.post(f"/record/{rec_a.id}/pane/start", headers=HX)

        r = c.get(f"/record/{rec_b.id}/pane/panel")
        assert r.status_code == 200
        assert 'data-key-action="iterate"' in r.text
        assert manager.active_record_id == rec_a.id  # untouched
        assert engine_a.interrupt_calls == 0


# ------------------------------------------------- verb-dispatch interrupt-first


class _OrderTrackingRunner(FakeRunner):
    """Records the live engine's interrupt_calls count AT THE MOMENT
    run() is invoked — lets a test prove ordering (interrupt-before-verb)
    rather than just eventual state."""

    def __init__(self, engine: FakeEngine, default: RunResult | None = None) -> None:
        super().__init__(default=default)
        self._engine = engine
        self.interrupt_calls_at_dispatch: list[int] = []

    async def run(self, argv: list[str]) -> RunResult:
        self.interrupt_calls_at_dispatch.append(self._engine.interrupt_calls)
        return await super().run(argv)


class TestResolveUnderIterationInterruptsFirst:
    def test_action_confirm_interrupts_the_live_session_before_running_the_verb(
        self, tmp_path: Path
    ) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        runner = _OrderTrackingRunner(engine)
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine}, runner=runner)
        runner.queue_result(RunResult(0))  # the post-session validate call
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert manager.active_record_id == rec.id

        r = c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "reject", "kind": "detail"},
            headers=HX,
        )
        assert r.status_code == 200
        assert engine.interrupt_calls == 1
        assert engine.close_calls == 1
        assert manager.active_record_id is None
        # The interrupt had ALREADY happened by the time the verb argv
        # was dispatched — ordering, not just eventual state.
        reject_call_index = [c for c in runner.calls].index(["reject", rec.id])
        assert runner.interrupt_calls_at_dispatch[reject_call_index] == 1

    def test_bulk_graduate_interrupts_each_id_under_iteration_first(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s",))
        ids = []
        engines: dict[str, FakeEngine] = {}
        for _ in range(2):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            from support import seed_proposal

            seed_proposal(sb.ledger, rec.id, already_canon=True)
            ids.append(rec.id)
            engines[rec.id] = FakeEngine(turns=[[Result("success", 0.0, None)]])

        c, runner, manager = make_client_with_pane(sb, engines=engines)
        runner.queue_result(RunResult(0))  # first record's iterate validate
        # Only iterate the FIRST id — the second should see a no-op hook call.
        c.post(f"/record/{ids[0]}/pane/start", headers=HX)
        assert manager.active_record_id == ids[0]

        r = c.post(
            f"/bucket/skill/s/graduate-bulk",
            data={"ids": ",".join(ids)},
            headers=HX,
        )
        assert r.status_code in (200, 303)
        assert engines[ids[0]].interrupt_calls == 1
        assert engines[ids[1]].interrupt_calls == 0  # never live -> no-op, never called
        # runner.calls[0] is the earlier iterate's own post-session
        # "proposal validate" call — the bulk loop's argv sequence is
        # everything after it.
        assert runner.calls[1:] == [
            ["graduate", ids[0], "--no-push"],
            ["graduate", ids[1], "--no-push"],
            ["push"],
        ]


# --------------------------------------------------------------------- XSS


class TestPaneTranscriptXss:
    def test_script_payload_in_pane_text_renders_escaped(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        payload = "<script>alert(1)</script>"
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text=payload), Result("success", 0.0, None)]]
        )
        c, runner, _manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))

        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert "<script>alert(1)</script>" not in r.text
        assert "&lt;script&gt;" in r.text


# ----------------------------------------------------------------- security


class TestPaneSecurity:
    def test_start_requires_cookie_and_hx_request(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        c, _runner, _manager = make_client_with_pane(sb)
        c.cookies.clear()
        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert r.status_code == 403
