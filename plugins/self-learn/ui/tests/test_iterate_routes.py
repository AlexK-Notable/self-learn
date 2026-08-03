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

import re
from pathlib import Path

from starlette.testclient import TestClient

from self_learn_ui import pane
from self_learn_ui.app import create_app
from self_learn_ui.engine.base import BlockStart, FakeEngine, FileChanged, Result, TextDelta
from self_learn_ui.env import load_env
from self_learn_ui.runner import FakeRunner, RunResult

from support import enter_client, join_pane_turn, make_behavior, make_env, seed_record

TOKEN = "test-token"
HX = {"HX-Request": "true"}


def make_client(sb, *, runner: FakeRunner | None = None, port: int = 7357) -> tuple[TestClient, FakeRunner]:
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    # Y-15: pane drains are background tasks on the app's event loop —
    # every client here runs on ONE persistent portal (support.py).
    enter_client(c)
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



def _unarmed_bar_fields(html: str) -> dict[str, str]:
    """Exactly the hidden fields the RENDERED unarmed action bar carries —
    what a browser sends when the human clicks a verb. Never a hand-built
    dict: one built by hand cannot notice a field the template stopped (or
    started) emitting, which is exactly how `dest_touched` went missing
    across the pane round trip and made the UI credit the analyst for a
    destination the human chose."""
    section = html.split('class="action-bar"')[1]
    return dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', section))


def _armed_bar_fields(html: str) -> dict[str, str]:
    """The same, for the armed confirm form the arm response renders."""
    section = html.split('action/confirm"')[1].split("</form>")[0]
    return dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', section))


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
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))  # the post-session validate call

        start = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert start.status_code == 200
        # Y-15: the POST returns the STARTING split — transcript content
        # arrives over SSE, never in this response.
        assert "Starting the conversation" in start.text
        assert 'data-key-action="close_pane"' in start.text

        join_pane_turn(c, manager)
        detail = c.get(f"/record/{rec.id}")
        assert 'class="detail-left"' in detail.text
        assert 'class="detail-right"' in detail.text
        assert "analysis text" in detail.text


# --------------------------------------------------------------- happy path


class TestPaneStartSendInterruptClose:
    def test_start_returns_starting_markup_then_panel_carries_the_result(self, tmp_path: Path) -> None:
        # Y-15: the start POST is prompt — starting markup with the
        # region ids/hooks the SSE handlers target, interrupt live, and
        # the panel URL data attribute (delta R3); the result footer
        # arrives on the completion swap's panel GET, never the POST.
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[[BlockStart(kind="text"), TextDelta(text="hello there"), Result("success", 0.02, None)]]
        )
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))

        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        assert r.status_code == 200
        assert 'data-pane-state="starting"' in r.text
        assert "Starting the conversation" in r.text
        assert 'id="pane-transcript"' in r.text  # the SSE handlers' region exists NOW
        assert f'data-pane-panel-url="/record/{rec.id}/pane/panel"' in r.text
        assert 'data-key-action="interrupt"' in r.text  # Esc works from starting
        assert "hello there" not in r.text  # transcript never rides the POST

        join_pane_turn(c, manager)
        panel = c.get(f"/record/{rec.id}/pane/panel")
        assert "hello there" in panel.text
        assert "success" in panel.text
        assert "0.0200" in panel.text
        # AWAITING_INPUT: nothing in flight -> no interrupt control.
        assert 'data-key-action="interrupt"' not in panel.text
        assert engine.started is True

    def test_send_continues_the_same_session(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[
                [Result("success", 0.0, None)],
                [BlockStart(kind="text"), TextDelta(text="follow-up reply"), Result("success", 0.0, None)],
            ]
        )
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        runner.queue_result(RunResult(0))

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        # Y-15/F6: send's authoritative-swap semantics are untouched —
        # its POST response still renders the post-turn state.
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
        join_pane_turn(c, manager)

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
        join_pane_turn(c, manager)
        assert manager.snapshot(rec.id).blocks

        r = c.post(f"/record/{rec.id}/pane/close", headers=HX)
        assert r.status_code == 200
        assert r.headers.get("hx-redirect") == f"/record/{rec.id}"
        assert engine.close_calls == 1
        assert manager.snapshot(rec.id).state == pane.STATE_IDLE

        detail = c.get(f"/record/{rec.id}")
        assert 'data-key-action="iterate"' in detail.text
        assert "pane-block" not in detail.text


# ------------------------------------ pane-close destination persistence
#
# UI-walk defect: a walker cycled a record's Destination to a non-default
# value, opened Iterate (hit the sandbox's "Not logged in" divergence),
# closed it, then Approved -> Confirmed — and got a raw CLI error
# (`self-learn route: no proposal for <id> — pass --dest or run review`)
# with the Destination control silently reverted to "(analyst
# suggestion)". Root cause: the cycled value lives ONLY in the unarmed
# action bar's own hidden field (a DOM-only, 09 §3-compliant "no state
# that isn't a file" choice) — `pane_close`'s HX-Redirect is the one pane
# route that does a FULL page navigation rather than a targeted
# `#pane-region-wrapper` swap, so it alone regenerates that bar from the
# record's own default, discarding the human's still-pending choice with
# no warning. Repeating cycle-then-approve WITHOUT the Iterate detour
# (TestArmDisarmConfirm.test_confirm_route_calls_runner_with_exact_argv,
# TestOCycle in test_routes.py) already pins the positive control: a
# normal cycle-then-approve works today and must keep working.


class TestPaneCloseDestinationPersistence:
    def test_close_button_wires_the_action_bars_dest_field(self, tmp_path: Path) -> None:
        """The template half of the fix, alone: without this hx-include,
        the server-side carry-through below has nothing to carry — the
        close POST would never see the pending destination at all. The
        close button only renders once a session is live/ended
        (partials/pane.html, `pane_split`) — pane_idle.html (no session
        yet) has no Close button at all, so this must start ONE first."""
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        start = c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        assert 'data-key-action="close_pane"' in start.text  # sanity: the right button
        assert f'hx-include="#form-action-bar-{rec.id}"' in start.text

    def test_close_redirect_carries_the_posted_destination_on_its_query_string(
        self, tmp_path: Path
    ) -> None:
        """The route half, in isolation from the template wiring above —
        exactly what a browser's hx-include-driven POST would send."""
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)

        r = c.post(f"/record/{rec.id}/pane/close", data={"dest": "skill-md"}, headers=HX)
        assert r.status_code == 200
        assert r.headers.get("hx-redirect") == f"/record/{rec.id}?dest=skill-md"

    def test_close_with_no_pending_destination_redirects_exactly_as_before(
        self, tmp_path: Path
    ) -> None:
        """Negative control for the leg above: an UNCYCLED close (dest
        empty, today's overwhelmingly common case) must not grow a
        `?dest=` it has nothing to carry — same bare redirect
        TestPaneStartSendInterruptClose already pins."""
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)

        r = c.post(f"/record/{rec.id}/pane/close", data={"dest": ""}, headers=HX)
        assert r.headers.get("hx-redirect") == f"/record/{rec.id}"

    def test_destination_survives_the_full_cycle_iterate_close_approve_confirm_repro(
        self, tmp_path: Path
    ) -> None:
        """The walker's exact repro, end to end: cycle -> Iterate open ->
        close -> the redirected GET -> Approve -> Confirm must reach the
        CLI with the CYCLED destination — never the bare `no proposal`
        failure, never a silent revert to the analyst default."""
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))  # the pane's post-session validate call

        before = c.get(f"/record/{rec.id}")
        assert 'name="dest" value=""' in before.text  # starts at "(analyst suggestion)"

        cycled = c.post(
            f"/record/{rec.id}/action/cycle-destination", data={"dest": ""}, headers=HX
        )
        assert 'name="dest" value="skill-md"' in cycled.text

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)

        close = c.post(f"/record/{rec.id}/pane/close", data={"dest": "skill-md"}, headers=HX)
        redirect = close.headers["hx-redirect"]
        assert redirect == f"/record/{rec.id}?dest=skill-md"

        detail = c.get(redirect)
        # SURVIVED the round trip — not reverted to "(analyst suggestion)".
        assert 'name="dest" value="skill-md"' in detail.text
        assert "(analyst suggestion)" not in detail.text

        arm = c.post(
            f"/record/{rec.id}/action/arm",
            data={**_unarmed_bar_fields(detail.text), "verb": "route", "kind": "detail"},
            headers=HX,
        )
        assert 'data-armed="true"' in arm.text

        confirm = c.post(
            f"/record/{rec.id}/action/confirm",
            data={**_armed_bar_fields(arm.text), "kind": "detail"},
            headers=HX,
        )
        assert confirm.status_code == 200
        assert "no proposal for" not in confirm.text
        # `--by human` is load-bearing, not incidental: the human worked the
        # (o) cycle before opening Iterate, so carrying the destination back
        # without carrying THAT would record the analyst as the chooser —
        # FW-64's exact dishonesty, reintroduced through the pane door.
        assert runner.calls[-1] == [
            "route", rec.id, "--dest", "skill-md", "--by", "human", "--json"
        ]

    def test_a_second_records_cycle_then_approve_without_iterate_still_works(
        self, tmp_path: Path
    ) -> None:
        """Positive control (method step 2): the walker's own report notes
        the identical cycle-then-approve worked cleanly on a record that
        never took the Iterate detour — pinned here so this fix cannot be
        satisfied by breaking the ordinary path instead."""
        sb, rec = _seed(tmp_path)
        c, runner, _manager = make_client_with_pane(sb)
        cycled = c.post(
            f"/record/{rec.id}/action/cycle-destination", data={"dest": ""}, headers=HX
        )
        assert 'name="dest" value="skill-md"' in cycled.text

        arm = c.post(
            f"/record/{rec.id}/action/arm",
            data={**_unarmed_bar_fields(cycled.text), "verb": "route", "kind": "detail"},
            headers=HX,
        )
        assert 'data-armed="true"' in arm.text

        confirm = c.post(
            f"/record/{rec.id}/action/confirm",
            data={**_armed_bar_fields(arm.text), "kind": "detail"},
            headers=HX,
        )
        assert confirm.status_code == 200
        assert "no proposal for" not in confirm.text
        # `--by human` is load-bearing, not incidental: the human worked the
        # (o) cycle before opening Iterate, so carrying the destination back
        # without carrying THAT would record the analyst as the chooser —
        # FW-64's exact dishonesty, reintroduced through the pane door.
        assert runner.calls[-1] == [
            "route", rec.id, "--dest", "skill-md", "--by", "human", "--json"
        ]


# --------------------------------------------------- U21 post-iterate summary


class TestPostIterateSummaryRoute:
    """The result footer's new plain-words line, rendered — "part of the
    SAME footer block ... persists in the snapshot exactly like the
    footer does" (10 §3 U21 row)."""

    def test_footer_line_present_after_pane_result_and_on_navigation_return(
        self, tmp_path: Path
    ) -> None:
        sb, rec = _seed(tmp_path)
        lesson_path = f"/anywhere/pending/{rec.id}.md"
        engine = FakeEngine(
            turns=[[FileChanged(path=lesson_path), Result("success", 0.0, None)]]
        )
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))  # the post-session validate call

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)

        panel = c.get(f"/record/{rec.id}/pane/panel")
        assert 'class="pane-turn-summary"' in panel.text
        assert "This turn changed: the lesson text." in panel.text

        # navigation-return regression: a later plain Detail GET (the
        # split re-render, not the SSE completion swap) shows the SAME
        # line — the server derives nothing new, it just re-reads the
        # persisted snapshot field.
        detail = c.get(f"/record/{rec.id}")
        assert 'class="pane-turn-summary"' in detail.text
        assert "This turn changed: the lesson text." in detail.text

    def test_no_changes_renders_the_nothing_variant(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)

        panel = c.get(f"/record/{rec.id}/pane/panel")
        assert "This turn changed: nothing." in panel.text


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
        assert "Starting the conversation" in r.text  # the POST is pre-failure
        join_pane_turn(c, manager)
        # Y-15/F1: the failure lands via the pane_result-triggered
        # completion swap — this panel GET is exactly that fetch.
        panel = c.get(f"/record/{rec.id}/pane/panel")
        assert "connection refused" in panel.text
        assert 'data-key-action="retry"' in panel.text
        assert runner.calls == []  # no validate call on a failed session


class TestCapHitAndRetry:
    def test_cap_hit_renders_pinned_message_and_retry_button(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(
            turns=[[Result(status="error_max_budget_usd", cost_usd=1.0, error="budget exceeded")]]
        )
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        r = c.get(f"/record/{rec.id}/pane/panel")  # the completion swap's fetch
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

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        first = c.get(f"/record/{rec.id}/pane/panel")
        assert "boom" in first.text

        # r from the error state: a fresh engine, a fresh starting split.
        second = c.post(f"/record/{rec.id}/pane/retry", headers=HX)
        assert second.status_code == 200
        assert "Starting the conversation" in second.text
        assert "boom" not in second.text
        join_pane_turn(c, manager)
        assert calls["n"] == 2
        assert "boom" not in c.get(f"/record/{rec.id}/pane/panel").text


# ------------------------------------------------------- post-session validate


class TestPostSessionValidateBadges:
    def test_exit_0_shows_no_badge(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        r = c.get(f"/record/{rec.id}/pane/panel")
        assert "scan-blocked" not in r.text
        assert "schema invalid" not in r.text

    def test_exit_1_shows_schema_invalid_strip(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(1, stderr="self-learn: schema-invalid, missing rationale"))
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        r = c.get(f"/record/{rec.id}/pane/panel")
        assert "schema invalid" in r.text
        assert "missing rationale" in r.text

    def test_exit_2_shows_scan_blocked_badge(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(2, stderr="self-learn: secret scan hit"))
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        r = c.get(f"/record/{rec.id}/pane/panel")
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
        join_pane_turn(c, manager)
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
        join_pane_turn(c, manager)
        r = c.post(f"/record/{rec_b.id}/pane/start", data={"force": "true"}, headers=HX)

        assert r.status_code == 200
        assert "Starting the conversation" in r.text  # b's fresh starting split
        join_pane_turn(c, manager)
        assert "record b analysis" in c.get(f"/record/{rec_b.id}/pane/panel").text
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
        join_pane_turn(c, manager)

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
        join_pane_turn(c, manager)
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
        # Resolution-evidence unit: `reject` carries `--json` now.
        reject_call_index = [c for c in runner.calls].index(["reject", rec.id, "--json"])
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
        join_pane_turn(c, manager)
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
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})
        runner.queue_result(RunResult(0))

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        join_pane_turn(c, manager)
        r = c.get(f"/record/{rec.id}/pane/panel")
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


# ------------------------------------------------- Y-15 non-blocking start


class _GatedRouteEngine:
    """PaneEngine-shaped double whose start() blocks on an asyncio.Event —
    proves at the ROUTE level that the start POST returns while the first
    turn is still running (Y-15). The gate is set via the client's portal
    (Event is not thread-safe; the test thread never touches it directly)."""

    def __init__(self, events) -> None:
        import asyncio

        self.gate = asyncio.Event()
        self._events = list(events)
        self.started = False
        self.sent: list[str] = []
        self.interrupt_calls = 0
        self.close_calls = 0

    async def start(self, ctx):
        self.started = True
        await self.gate.wait()
        for event in self._events:
            yield event

    async def send(self, text: str):
        self.sent.append(text)
        return
        yield  # pragma: no cover

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class TestNonBlockingStartRoutes:
    def test_start_post_returns_while_the_turn_is_still_running(self, tmp_path: Path) -> None:
        sb, rec = _seed(tmp_path)
        engine = _GatedRouteEngine(
            [BlockStart(kind="text"), TextDelta(text="slow analysis"), Result("success", 0.0, None)]
        )
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})  # type: ignore[dict-item]
        runner.queue_result(RunResult(0))

        r = c.post(f"/record/{rec.id}/pane/start", headers=HX)

        # The response landed while the engine still holds the gate —
        # the user-hit silent wall is structurally gone.
        assert r.status_code == 200
        assert not engine.gate.is_set()
        assert 'data-pane-state="starting"' in r.text
        assert "Starting the conversation" in r.text
        assert 'id="pane-transcript"' in r.text
        assert f'data-pane-panel-url="/record/{rec.id}/pane/panel"' in r.text
        assert "slow analysis" not in r.text

        assert c.portal is not None
        c.portal.call(engine.gate.set)
        join_pane_turn(c, manager)
        panel = c.get(f"/record/{rec.id}/pane/panel")
        assert "slow analysis" in panel.text
        assert runner.calls == [["proposal", "validate", rec.id]]

    def test_interrupt_during_starting_terminates_the_turn(self, tmp_path: Path) -> None:
        # F4 at the route level: Esc lands while the first turn is in
        # flight; once the engine becomes interruptible the latch is
        # re-delivered and the turn ends.
        sb, rec = _seed(tmp_path)
        engine = _GatedRouteEngine([Result("success", 0.0, None)])
        c, runner, manager = make_client_with_pane(sb, engines={rec.id: engine})  # type: ignore[dict-item]
        runner.queue_result(RunResult(0))

        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        r = c.post(f"/record/{rec.id}/pane/interrupt", headers=HX)
        assert r.status_code == 200

        assert c.portal is not None
        c.portal.call(engine.gate.set)
        join_pane_turn(c, manager)
        assert engine.interrupt_calls >= 1
        # The turn is over: the split is parked or ended, never stuck
        # starting/streaming.
        snap = manager.snapshot(rec.id)
        assert snap.state in (pane.STATE_AWAITING_INPUT, pane.STATE_ENDED)

    def test_bucket_pane_start_returns_starting_markup(self, tmp_path: Path) -> None:
        # The bucket family shares the manager and the Y-15 contract.
        sb, rec = _seed(tmp_path)
        c, runner = make_client(sb)
        key = pane.bucket_session_key("skill", "s")
        engine = _GatedRouteEngine(
            [BlockStart(kind="text"), TextDelta(text="bucket chat reply"), Result("success", 0.0, None)]
        )

        def context_builder(session_key: str) -> "pane.PaneContext":
            parsed = pane.parse_bucket_session_key(session_key)
            assert parsed is not None
            scope, name = parsed
            return pane.build_bucket_pane_context(
                sb.ledger, scope, name, read_doctrine_fn=lambda: "DOCTRINE"
            )

        from typing import cast

        from fastapi import FastAPI

        app = cast(FastAPI, c.app)
        manager = pane.PaneManager(
            engine_factory=lambda: engine,  # type: ignore[arg-type,return-value]
            context_builder=context_builder,
            app_hub=app.state.app_hub,
            refresh_hub=app.state.refresh_hub,
            runner=runner,
        )
        app.state.pane_manager = manager

        r = c.post("/bucket/skill/s/pane/start", headers=HX)
        assert r.status_code == 200
        assert not engine.gate.is_set()
        assert 'data-pane-state="starting"' in r.text
        assert "Starting the conversation" in r.text
        assert 'data-pane-panel-url="/bucket/skill/s/pane/panel"' in r.text

        assert c.portal is not None
        c.portal.call(engine.gate.set)
        join_pane_turn(c, manager)
        panel = c.get("/bucket/skill/s/pane/panel")
        assert "bucket chat reply" in panel.text
        assert runner.calls == []  # bucket sessions owe no validate


class TestLifespanShutdown:
    def test_lifespan_shutdown_tears_down_the_live_pane(self, tmp_path: Path) -> None:
        # Code-review MINOR-2: pre-Y-15 an in-flight turn lived inside a
        # request uvicorn's graceful shutdown waited for; the background
        # drain does not — the lifespan finally must tear it down, never
        # leak a free-floating task or an open engine child.
        from typing import cast

        from fastapi import FastAPI

        from self_learn_ui.engine.base import TextDelta as _TextDelta

        sb, rec = _seed(tmp_path)
        runner = FakeRunner()
        env = load_env(sb.env)
        app = cast(FastAPI, create_app(env=env, token=TOKEN, runner=runner, start_watcher=False))
        engine = _GatedRouteEngine([_TextDelta(text="never delivered")])

        def context_builder(record_id: str) -> "pane.PaneContext":
            return pane.build_pane_context(sb.ledger, record_id, read_doctrine_fn=lambda: "D")

        manager = pane.PaneManager(
            engine_factory=lambda: engine,  # type: ignore[arg-type,return-value]
            context_builder=context_builder,
            app_hub=app.state.app_hub,
            refresh_hub=app.state.refresh_hub,
            runner=runner,
        )
        app.state.pane_manager = manager

        with TestClient(app, base_url="http://127.0.0.1:7357") as c:
            c.cookies.set("slu_token", TOKEN)
            r = c.post(f"/record/{rec.id}/pane/start", headers=HX)
            assert r.status_code == 200
            assert manager.active_record_id == rec.id

        # The with-exit ran the lifespan finally: session gone, engine
        # closed, nothing left running.
        assert manager.active_record_id is None
        assert engine.close_calls == 1
