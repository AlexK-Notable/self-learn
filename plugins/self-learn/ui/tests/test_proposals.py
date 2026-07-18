"""Y-13 verb proposals (09 §4.5 as reworked 2026-07-17; 10 §2's T-A
Y-13 block; task U12): the propose_verb handler driven directly (no
live engine), the server-held slot's lifecycle, the waiting/armed
proposal bar routes, the F1 collision fixture (a proposal landing
while a human-armed bar is out must not alter what the pending Enter
confirms), the bucket pane split, and the charter's bucket zero-write
variant. httpx against the ASGI app, FakeRunner/FakeEngine — exactly
the established T-A pattern (test_routes.py / test_iterate_routes.py).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from self_learn_ui import pane, proposals
from self_learn_ui.app import create_app
from self_learn_ui.engine.base import BlockStart, FakeEngine, Result, TextDelta
from self_learn_ui.engine.charter import build_can_use_tool
from self_learn_ui.env import load_env
from self_learn_ui.proposals import (
    NOTE_MAX_CHARS,
    PROPOSAL_TOOL_QUALIFIED_NAME,
    ProposalSlot,
    SessionScope,
    TOOL_ACCEPTED_MESSAGE,
    VerbProposal,
    make_propose_handler,
    validate_proposal,
)
from self_learn_ui.runner import FakeRunner, RunResult

from support import (
    make_behavior,
    make_env,
    resolve_record_directly,
    seed_record,
)

TOKEN = "test-token"
HX = {"HX-Request": "true"}


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _seed(tmp_path: Path, *, n: int = 1):
    sb = make_env(tmp_path, skills=("s",))
    records = []
    for _ in range(n):
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        records.append(rec)
    return sb, records


def _bucket_dir(sb) -> Path:
    return sb.ledger / "skills" / "s"


def _record_scope(rec) -> SessionScope:
    return SessionScope(kind="record", session_key=rec.id, record_id=rec.id)


def _bucket_scope(sb) -> SessionScope:
    return SessionScope(
        kind="bucket",
        session_key=pane.bucket_session_key("skill", "s"),
        bucket_dir=_bucket_dir(sb),
        bucket_scope="skill",
        bucket_name="s",
    )


# ---------------------------------------------------------- validation


class TestValidateProposal:
    def test_valid_route_with_dest_and_note(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "route", "record_id": rec.id, "dest": "skill-md", "note": "n"},
        )
        assert isinstance(result, VerbProposal)
        assert result.verb == "route"
        assert result.record_id == rec.id
        assert result.bucket_name == "s"
        assert result.bucket_scope == "skill"
        assert not result.armed

    def test_closed_list_refuses_host_add_and_everything_else(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        for verb in ("host add", "host-add", "collapse", "confirm-recurrence", "push", ""):
            result = validate_proposal(
                sb.ledger, _record_scope(rec), {"verb": verb, "record_id": rec.id}
            )
            assert isinstance(result, str), verb
            assert "refused" in result

    def test_record_session_may_only_name_its_own_record(self, tmp_path: Path) -> None:
        sb, (rec, other) = _seed(tmp_path, n=2)
        result = validate_proposal(
            sb.ledger, _record_scope(rec), {"verb": "reject", "record_id": other.id}
        )
        assert isinstance(result, str)
        assert rec.id in result

    def test_bucket_session_refuses_record_outside_its_bucket(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path, skills=("s", "t"))
        rec_s = make_behavior(scope="skill:s")
        rec_t = make_behavior(scope="skill:t")
        seed_record(sb.ledger, rec_s)
        seed_record(sb.ledger, rec_t)
        result = validate_proposal(
            sb.ledger, _bucket_scope(sb), {"verb": "defer", "record_id": rec_t.id}
        )
        assert isinstance(result, str)
        assert "outside this bucket" in result

    def test_bucket_session_accepts_own_bucket_record(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger, _bucket_scope(sb), {"verb": "graduate", "record_id": rec.id}
        )
        assert isinstance(result, VerbProposal)
        assert result.session_key == pane.bucket_session_key("skill", "s")

    def test_unknown_record_refused(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger, _bucket_scope(sb), {"verb": "reject", "record_id": "lrn-00000000"}
        )
        assert isinstance(result, str)

    def test_malformed_record_id_refused(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        for bad in ("lrn-XYZ", "aa000001", "lrn-aa000001; rm -rf /", None, 7):
            result = validate_proposal(
                sb.ledger, _record_scope(rec), {"verb": "reject", "record_id": bad}
            )
            assert isinstance(result, str), bad

    def test_dest_forms_full_02s1_surface(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        ok = ("skill-md", "claude-md", "reference", "reference:notes.md", "new-skill:foo", "hook")
        for dest in ok:
            result = validate_proposal(
                sb.ledger, _record_scope(rec), {"verb": "route", "record_id": rec.id, "dest": dest}
            )
            assert isinstance(result, VerbProposal), dest
        for dest in ("new-skill", "SKILL-MD", "canon", "reference:"):
            result = validate_proposal(
                sb.ledger, _record_scope(rec), {"verb": "route", "record_id": rec.id, "dest": dest}
            )
            assert isinstance(result, str), dest

    def test_dest_only_on_route_until_only_on_defer(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        r1 = validate_proposal(
            sb.ledger, _record_scope(rec), {"verb": "reject", "record_id": rec.id, "dest": "skill-md"}
        )
        assert isinstance(r1, str)
        r2 = validate_proposal(
            sb.ledger, _record_scope(rec), {"verb": "route", "record_id": rec.id, "until": "2026-08-01"}
        )
        assert isinstance(r2, str)

    def test_until_must_parse_as_a_real_date(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        good = validate_proposal(
            sb.ledger, _record_scope(rec), {"verb": "defer", "record_id": rec.id, "until": "2026-08-30"}
        )
        assert isinstance(good, VerbProposal)
        for bad in ("soon", "2026-13-01", "2026-02-30", "08/30/2026"):
            result = validate_proposal(
                sb.ledger, _record_scope(rec), {"verb": "defer", "record_id": rec.id, "until": bad}
            )
            assert isinstance(result, str), bad

    def test_note_capped_at_intake_never_truncated(self, tmp_path: Path) -> None:
        """Delta R4: the displayed note must be byte-identical to the
        executed --note — over-cap notes REFUSE, they never truncate."""
        sb, (rec,) = _seed(tmp_path)
        ok = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "reject", "record_id": rec.id, "note": "x" * NOTE_MAX_CHARS},
        )
        assert isinstance(ok, VerbProposal)
        assert ok.note == "x" * NOTE_MAX_CHARS
        over = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "reject", "record_id": rec.id, "note": "x" * (NOTE_MAX_CHARS + 1)},
        )
        assert isinstance(over, str)
        assert str(NOTE_MAX_CHARS) in over


# ------------------------------------------------------- handler + slot


class TestProposeHandler:
    def _handler(self, sb, rec, slot: ProposalSlot, published: list[dict]):
        async def publish(envelope: dict) -> None:
            published.append(envelope)

        return make_propose_handler(
            home=sb.ledger, scope=_record_scope(rec), slot=slot, publish=publish
        )

    def test_valid_proposal_occupies_slot_and_publishes_scoped_envelope(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        slot, published = ProposalSlot(), []
        handle = self._handler(sb, rec, slot, published)
        result = run(handle({"verb": "defer", "record_id": rec.id, "until": "2026-09-01"}))
        assert result == TOOL_ACCEPTED_MESSAGE
        assert slot.current is not None and slot.current.verb == "defer"
        assert not slot.current.armed  # proposals arrive WAITING, never armed
        assert published == [
            {"type": "pane_proposal", "record_id": rec.id, "bucket": "s"}
        ]

    def test_refuse_not_replace_while_waiting_and_while_armed(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        slot, published = ProposalSlot(), []
        handle = self._handler(sb, rec, slot, published)
        assert run(handle({"verb": "reject", "record_id": rec.id})) == TOOL_ACCEPTED_MESSAGE
        # waiting
        second = run(handle({"verb": "graduate", "record_id": rec.id}))
        assert "already awaiting the human" in second
        assert slot.current is not None and slot.current.verb == "reject"
        # armed
        slot.arm(rec.id)
        third = run(handle({"verb": "graduate", "record_id": rec.id}))
        assert "already awaiting the human" in third
        assert slot.current.verb == "reject"
        assert len(published) == 1  # refusals render nothing

    def test_invalid_args_render_nothing(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        slot, published = ProposalSlot(), []
        handle = self._handler(sb, rec, slot, published)
        result = run(handle({"verb": "host add", "record_id": rec.id}))
        assert "refused" in result
        assert slot.current is None
        assert published == []


class TestProposalSlotLifecycle:
    def _proposal(self, session_key: str = "lrn-aa000001") -> VerbProposal:
        return VerbProposal(
            verb="reject",
            record_id="lrn-aa000001",
            bucket_scope="skill",
            bucket_name="s",
            session_key=session_key,
        )

    def test_disarm_returns_to_waiting_never_clears(self) -> None:
        slot = ProposalSlot()
        assert slot.occupy(self._proposal())
        assert slot.arm("lrn-aa000001") is not None
        disarmed = slot.disarm("lrn-aa000001")
        assert disarmed is not None and not disarmed.armed
        assert slot.current is not None  # still occupied — dismiss is the clear

    def test_clear_for_record_and_session(self) -> None:
        slot = ProposalSlot()
        slot.occupy(self._proposal(session_key="bucket:skill/s"))
        assert not slot.clear_for_record("lrn-ffffffff")
        assert not slot.clear_for_session("lrn-other")
        assert slot.clear_for_session("bucket:skill/s")
        assert slot.current is None

    def test_manager_clears_slot_when_proposing_session_ends(self, tmp_path: Path) -> None:
        """Y-13 clear-set: session end for any reason — here `q` close
        and an error result — frees the slot (no permanent wedge)."""
        sb, (rec,) = _seed(tmp_path)
        slot = ProposalSlot()

        def context_builder(record_id: str) -> pane.PaneContext:
            return pane.build_pane_context(sb.ledger, record_id, read_doctrine_fn=lambda: "D")

        from self_learn_ui.ledger import RefreshHub
        from self_learn_ui.sse import AppEventHub

        manager = pane.PaneManager(
            engine_factory=lambda: FakeEngine(
                turns=[[BlockStart(kind="text"), TextDelta(text="hi"), Result(status="ok", cost_usd=None, error=None)]]
            ),
            context_builder=context_builder,
            app_hub=AppEventHub(),
            refresh_hub=RefreshHub(),
            runner=FakeRunner(),
            proposal_slot=slot,
        )
        run(self._close_flow(manager, slot, rec))

    async def _close_flow(self, manager: pane.PaneManager, slot: ProposalSlot, rec) -> None:
        await manager.start(rec.id)
        slot.occupy(self._proposal(session_key=rec.id))
        await manager.close(rec.id)
        assert slot.current is None  # q close cleared it

    def test_manager_error_result_clears_slot(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        slot = ProposalSlot()

        from self_learn_ui.ledger import RefreshHub
        from self_learn_ui.sse import AppEventHub

        async def flow() -> None:
            manager = pane.PaneManager(
                engine_factory=lambda: FakeEngine(
                    turns=[
                        [Result(status="ok", cost_usd=None, error=None)],
                        [Result(status="error", cost_usd=None, error="boom")],
                    ]
                ),
                context_builder=lambda rid: pane.build_pane_context(
                    sb.ledger, rid, read_doctrine_fn=lambda: "D"
                ),
                app_hub=AppEventHub(),
                refresh_hub=RefreshHub(),
                runner=FakeRunner(),
                proposal_slot=slot,
            )
            await manager.start(rec.id)
            slot.occupy(self._proposal(session_key=rec.id))
            await manager.send(rec.id, "again")  # turn 2 -> error result -> ENDED
            assert slot.current is None

        run(flow())


# --------------------------------------------------------------- routes


def make_client(sb, *, runner: FakeRunner | None = None) -> tuple[TestClient, FakeRunner, pane.PaneManager]:
    runner = runner if runner is not None else FakeRunner()
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url="http://127.0.0.1:7357")
    c.cookies.set("slu_token", TOKEN)

    slot = ProposalSlot()

    def context_builder(session_key: str) -> pane.PaneContext:
        parsed = pane.parse_bucket_session_key(session_key)
        if parsed is not None:
            scope, name = parsed
            return pane.build_bucket_pane_context(
                sb.ledger, scope, name, read_doctrine_fn=lambda: "D",
                slot=slot, publish=app.state.app_hub.publish,
            )
        return pane.build_pane_context(
            sb.ledger, session_key, read_doctrine_fn=lambda: "D",
            slot=slot, publish=app.state.app_hub.publish,
        )

    manager = pane.PaneManager(
        engine_factory=lambda: FakeEngine(
            turns=[[Result(status="ok", cost_usd=None, error=None)]]
        ),
        context_builder=context_builder,
        app_hub=app.state.app_hub,
        refresh_hub=app.state.refresh_hub,
        runner=runner,
        proposal_slot=slot,
    )
    app.state.pane_manager = manager
    return c, runner, manager


def _occupy(manager: pane.PaneManager, rec, *, verb: str = "reject", **kw) -> VerbProposal:
    prop = VerbProposal(
        verb=verb,
        record_id=rec.id,
        bucket_scope="skill",
        bucket_name="s",
        session_key=rec.id,
        **kw,
    )
    assert manager.proposal_slot.occupy(prop)
    return prop


class TestProposalRoutes:
    def test_detail_renders_waiting_bar_not_armed(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        page = c.get(f"/record/{rec.id}").text
        assert 'data-proposal="waiting"' in page
        assert "Agent proposes:" in page
        assert page.count('data-armed="true"') == 0
        # the standing quad is replaced by the proposal bar in that region
        assert "Approve (e)" not in page

    def test_navigation_survival_rerenders_waiting_bar(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        assert 'data-proposal="waiting"' in c.get(f"/record/{rec.id}").text
        assert 'data-proposal="waiting"' in c.get(f"/record/{rec.id}").text  # again

    def test_arm_disarm_roundtrip(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        armed = c.post("/proposal/arm", data={"record_id": rec.id, "kind": "detail"}, headers=HX).text
        assert 'data-armed="true"' in armed
        assert "Enter" in armed
        disarmed = c.post("/proposal/disarm", data={"record_id": rec.id, "kind": "detail"}, headers=HX).text
        assert 'data-proposal="waiting"' in disarmed
        assert manager.proposal_slot.current is not None  # back to waiting, not cleared

    def test_confirm_executes_exactly_the_slot_argv_and_clears(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec, verb="defer", until="2026-09-01", note="agent thought")
        manager.proposal_slot.arm(rec.id)
        resp = c.post("/proposal/confirm", data={"record_id": rec.id, "kind": "detail"}, headers=HX)
        assert ["defer", rec.id, "--until", "2026-09-01", "--note", "agent thought"] in runner.calls
        assert manager.proposal_slot.current is None
        assert "HX-Redirect" in resp.headers

    def test_confirm_on_waiting_bar_executes_nothing(self, tmp_path: Path) -> None:
        """Enter never acts on a waiting bar — and even a forged confirm
        POST against an un-armed slot is a no-op."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        c.post("/proposal/confirm", data={"record_id": rec.id, "kind": "detail"}, headers=HX)
        assert runner.calls == []
        assert manager.proposal_slot.current is not None  # untouched

    def test_dismiss_clears_and_next_proposal_succeeds(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        out = c.post("/proposal/dismiss", data={"record_id": rec.id, "kind": "detail"}, headers=HX).text
        assert manager.proposal_slot.current is None
        assert "Approve (e)" in out  # detail region got its standing bar back
        assert manager.proposal_slot.occupy(
            VerbProposal(verb="graduate", record_id=rec.id, bucket_scope="skill",
                         bucket_name="s", session_key=rec.id)
        )

    def test_f1_collision_pending_human_enter_confirms_the_humans_verb(self, tmp_path: Path) -> None:
        """The F1 fixture (10 §2): a proposal landing while a HUMAN-armed
        bar is rendered must not alter what the pending Enter confirms.
        The human's armed fragment carries ITS OWN fields; their confirm
        re-submits those fields — the proposal (server slot) never
        touches them."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        # human arms route
        armed_page = c.post(
            f"/record/{rec.id}/action/arm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        ).text
        assert 'data-armed="true"' in armed_page
        # agent proposal lands while the human bar is out
        _occupy(manager, rec, verb="reject", note="agent says no")
        # the human's pending Enter fires their confirm with THEIR fields
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "route", "kind": "detail", "dest": "skill-md"},
            headers=HX,
        )
        assert ["route", rec.id, "--dest", "skill-md"] in runner.calls
        assert not any(call and call[0] == "reject" for call in runner.calls)

    def test_no_full_page_render_ever_has_two_armed_bars(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        assert c.get(f"/record/{rec.id}").text.count('data-armed="true"') == 0
        manager.proposal_slot.arm(rec.id)
        page = c.get(f"/record/{rec.id}").text
        assert page.count('data-armed="true"') == 1
        page = c.get("/bucket/skill/s").text
        assert page.count('data-armed="true"') <= 1

    def test_resolved_elsewhere_clears_slot_on_detail_render(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        resp = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert resp.status_code == 303
        assert manager.proposal_slot.current is None

    def test_stale_arm_after_external_resolution_renders_gone(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        out = c.post("/proposal/arm", data={"record_id": rec.id, "kind": "detail"}, headers=HX).text
        assert "resolved elsewhere" in out
        assert manager.proposal_slot.current is None
        assert runner.calls == []

    def test_confirm_failure_shows_stderr_verbatim_and_slot_stays_cleared(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="refused: scan hit"))
        c, runner, manager = make_client(sb, runner=runner)
        _occupy(manager, rec)
        manager.proposal_slot.arm(rec.id)
        out = c.post("/proposal/confirm", data={"record_id": rec.id, "kind": "detail"}, headers=HX).text
        assert "refused: scan hit" in out
        assert manager.proposal_slot.current is None

    def test_human_resolution_clears_proposal_on_same_record(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        c.post(
            f"/record/{rec.id}/action/confirm",
            data={"verb": "graduate", "kind": "detail"},
            headers=HX,
        )
        assert manager.proposal_slot.current is None


class TestBucketPane:
    def test_bucket_page_renders_pane_region_and_p_affordance(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        page = c.get("/bucket/skill/s").text
        assert 'data-key-action="bucket_pane"' in page
        assert "Open bucket chat (p)" in page

    def test_bucket_pane_start_renders_split_with_bucket_base_urls(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        out = c.post("/bucket/skill/s/pane/start", headers=HX).text
        assert "pane-region" in out
        assert "/bucket/skill/s/pane/send" in out
        assert manager.active_record_id == pane.bucket_session_key("skill", "s")

    def test_one_live_session_across_variants(self, tmp_path: Path) -> None:
        """Opening the bucket pane while a record session is live takes
        the existing armed interrupt prompt (09 §4.2 as amended)."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        c.post(f"/record/{rec.id}/pane/start", headers=HX)
        out = c.post("/bucket/skill/s/pane/start", headers=HX).text
        assert "Interrupt" in out  # the armed prompt, not a silent switch

    def test_bucket_proposal_renders_on_bucket_page(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        prop = VerbProposal(
            verb="defer", record_id=rec.id, bucket_scope="skill", bucket_name="s",
            session_key=pane.bucket_session_key("skill", "s"), until="2026-09-01",
        )
        manager.proposal_slot.occupy(prop)
        page = c.get("/bucket/skill/s").text
        assert 'data-proposal="waiting"' in page

    def test_bucket_confirm_redirects_to_bucket_page(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        prop = VerbProposal(
            verb="graduate", record_id=rec.id, bucket_scope="skill", bucket_name="s",
            session_key=pane.bucket_session_key("skill", "s"),
        )
        manager.proposal_slot.occupy(prop)
        manager.proposal_slot.arm(rec.id)
        resp = c.post("/proposal/confirm", data={"record_id": rec.id, "kind": "bucket"}, headers=HX)
        assert ["graduate", rec.id] in runner.calls
        assert resp.headers.get("HX-Redirect") == "/bucket/skill/s"


class TestBucketContext:
    def test_compose_bucket_message_caps_with_honest_truncation(self) -> None:
        items = [
            {"id": f"lrn-{i:08x}", "title": f"lesson {i}", "destination": "skill-md",
             "has_proposal": True, "proposal_fresh": True}
            for i in range(60)
        ]
        msg = pane.compose_bucket_message("skill", "s", items, [])
        assert "lesson 49" in msg
        assert "lesson 50" not in msg
        assert "showing 50 of 60" in msg

    def test_compose_bucket_message_tags(self) -> None:
        items = [
            {"id": "lrn-aa000001", "title": "T", "destination": None,
             "has_proposal": False, "proposal_fresh": False,
             "deferred_until": "2026-09-01", "source": "session"},
        ]
        msg = pane.compose_bucket_message(
            "skill", "s", items, [{"cluster_id": "merge-deadbeef", "members": ["a", "b"], "suggested_survivor": "a"}],
            host_registered=False,
        )
        assert "id=lrn-aa000001" in msg
        assert "unanalyzed" in msg
        assert "deferred until 2026-09-01" in msg
        assert "mined" in msg
        assert "host NOT registered" in msg
        assert "merge-deadbeef" in msg

    def test_bucket_context_is_bucket_kind_with_handler(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        slot = ProposalSlot()

        async def publish(env: dict) -> None:  # pragma: no cover - not fired here
            pass

        ctx = pane.build_bucket_pane_context(
            sb.ledger, "skill", "s", read_doctrine_fn=lambda: "D", slot=slot, publish=publish
        )
        assert ctx.session_kind == "bucket"
        assert ctx.propose_handler is not None
        assert rec.id in ctx.first_message


class TestBucketCharterVariant:
    def test_zero_write_denies_edit_and_write_with_venue_reason(self, tmp_path: Path) -> None:
        cb = build_can_use_tool(
            self_learn_home=tmp_path,
            bucket_root=tmp_path,
            record_id="bucket:skill/s",
            canon_read_roots_fn=lambda: [],
            plugin_references_dir_fn=lambda: tmp_path / "refs",
            zero_write=True,
        )

        async def check() -> None:
            for tool_name in ("Edit", "Write", "NotebookEdit"):
                result = await cb(tool_name, {"file_path": str(tmp_path / "x")}, None)
                assert type(result).__name__ == "PermissionResultDeny", tool_name
                assert "record" in result.message

        run(check())

    def test_extra_allowed_tools_exact_name_only(self, tmp_path: Path) -> None:
        cb = build_can_use_tool(
            self_learn_home=tmp_path,
            bucket_root=tmp_path,
            record_id="lrn-aa000001",
            canon_read_roots_fn=lambda: [],
            plugin_references_dir_fn=lambda: tmp_path / "refs",
            extra_allowed_tools=(PROPOSAL_TOOL_QUALIFIED_NAME,),
        )

        async def check() -> None:
            allowed = await cb(PROPOSAL_TOOL_QUALIFIED_NAME, {}, None)
            assert type(allowed).__name__ == "PermissionResultAllow"
            denied = await cb("mcp__self-learn-surface__other_tool", {}, None)
            assert type(denied).__name__ == "PermissionResultDeny"
            prefix = await cb(PROPOSAL_TOOL_QUALIFIED_NAME + "x", {}, None)
            assert type(prefix).__name__ == "PermissionResultDeny"

        run(check())
