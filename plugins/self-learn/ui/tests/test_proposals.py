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

from self_learn.hosts import slug_for

from support import (
    RouteSideEffectRunner,
    commit_all,
    enter_client,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    resolve_record_directly,
    seed_proposal,
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

    def test_rescope_is_not_in_the_pane_proposable_verb_list(
        self, tmp_path: Path
    ) -> None:
        """u-rescope §3 rationale 2 / §9 out-of-scope item 4: `rescope`
        does NOT join the closed proposable set — it starts human-only
        (CLI-driven, §6.1), unlike `rehome` which is agent-proposable
        (Y-13/Y-18). This is a guard against a later drive-by widening,
        not a change this unit makes."""
        assert "rescope" not in proposals.PROPOSABLE_VERBS
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "rescope", "record_id": rec.id, "to": "skill:s"},
        )
        assert isinstance(result, str)
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

    def test_a2_claude_md_variant_forms_parse(self, tmp_path: Path) -> None:
        """A2 §4.2 site 3: the UI-side twin of the CLI's ``_parse_dest``
        must accept the SAME new forms — obligation 19's "no split-brain"
        (a proposal carrying ``claude-md:rules:<topic>`` must pass BOTH
        UI validation and the CLI's own parse)."""
        sb, (rec,) = _seed(tmp_path)
        for dest in ("claude-md:local", "claude-md:rules:subagents", "claude-md:rules:a"):
            result = validate_proposal(
                sb.ledger, _record_scope(rec), {"verb": "route", "record_id": rec.id, "dest": dest}
            )
            assert isinstance(result, VerbProposal), dest
        for dest in ("claude-md:rules:", "claude-md:bogus", "claude-md:rules:Not_Kebab!"):
            result = validate_proposal(
                sb.ledger, _record_scope(rec), {"verb": "route", "record_id": rec.id, "dest": dest}
            )
            assert isinstance(result, str), dest

    def test_a2_refusal_message_enumerates_the_new_forms(self, tmp_path: Path) -> None:
        """A2 §4.2 NIT 1 (obligation 19): a mistyped dest's refusal lists
        BOTH new variant forms among the accepted ones — the message and
        the regex move together, or a mistyped new-form dest gets a
        refusal that omits exactly the forms A2 added."""
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger, _record_scope(rec),
            {"verb": "route", "record_id": rec.id, "dest": "claude-md:bogus"},
        )
        assert isinstance(result, str)
        assert "claude-md:rules:<topic>" in result
        assert "claude-md:local" in result

    def test_skill_md_refused_for_a_project_record(self, tmp_path: Path) -> None:
        """09 §4.5 as amended 2026-07-18 (feedback round 2 item 3): dest
        is scope-checked at intake — the human never sees an
        armable-but-impossible proposal, and the refusal teaches the
        agent the valid alternatives."""
        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        scope = SessionScope(kind="record", session_key=rec.id, record_id=rec.id)
        result = validate_proposal(
            sb.ledger, scope, {"verb": "route", "record_id": rec.id, "dest": "skill-md"}
        )
        assert isinstance(result, str)
        assert "skill-md only exists for skill-scoped lessons" in result
        assert "project-scoped" in result
        assert "claude-md or reference" in result

    def test_skill_md_refused_from_a_bucket_session_too(self, tmp_path: Path) -> None:
        from self_learn_ui import ledger as ui_ledger

        sb = make_env(tmp_path)
        rec = make_knowledge(scope="project")
        seed_record(sb.ledger, rec, project_path=sb.host)
        loc = ui_ledger.locate_record(sb.ledger, rec.id)
        assert loc is not None
        scope = SessionScope(
            kind="bucket",
            session_key=pane.bucket_session_key("project", loc.bucket_name),
            bucket_dir=loc.bucket_dir,
            bucket_scope="project",
            bucket_name=loc.bucket_name,
        )
        result = validate_proposal(
            sb.ledger, scope, {"verb": "route", "record_id": rec.id, "dest": "skill-md"}
        )
        assert isinstance(result, str)
        assert "skill-md only exists for skill-scoped lessons" in result

    def test_user_record_refuses_skill_md_and_reference(self, tmp_path: Path) -> None:
        # The user host is the chezmoi-managed CLAUDE.md alone — no
        # references dir (the route verb's own refusal, honored at intake).
        sb = make_env(tmp_path)
        rec = make_behavior(scope="user")
        seed_record(sb.ledger, rec)
        scope = SessionScope(kind="record", session_key=rec.id, record_id=rec.id)
        r1 = validate_proposal(
            sb.ledger, scope, {"verb": "route", "record_id": rec.id, "dest": "skill-md"}
        )
        assert isinstance(r1, str)
        assert "use claude-md" in r1
        assert "reference" not in r1  # user scope must not be taught reference
        r2 = validate_proposal(
            sb.ledger, scope,
            {"verb": "route", "record_id": rec.id, "dest": "reference:notes.md"},
        )
        assert isinstance(r2, str)
        assert "reference files live with a skill or project" in r2
        # claude-md stays proposable everywhere.
        ok = validate_proposal(
            sb.ledger, scope, {"verb": "route", "record_id": rec.id, "dest": "claude-md"}
        )
        assert isinstance(ok, VerbProposal)

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

    def test_resolved_record_refused_at_intake(self, tmp_path: Path) -> None:
        """Review F1: 'resolves to a PENDING record' means STATUS —
        locate_record also finds resolved/ records; a consent bar must
        never advertise an impossible action."""
        sb, (rec,) = _seed(tmp_path)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        result = validate_proposal(
            sb.ledger, _bucket_scope(sb), {"verb": "route", "record_id": rec.id, "dest": "skill-md"}
        )
        assert isinstance(result, str)
        assert "resolved" in result

    def test_title_captured_for_the_y9_leading_line(self, tmp_path: Path) -> None:
        """Review F2: the bar LEADS with the record's human line."""
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger, _record_scope(rec), {"verb": "graduate", "record_id": rec.id}
        )
        assert isinstance(result, VerbProposal)
        assert result.title  # the Trigger first line, non-empty

    def test_dest_intake_length_cap(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger, _record_scope(rec),
            {"verb": "route", "record_id": rec.id, "dest": "new-skill:" + "x" * 200},
        )
        assert isinstance(result, str)

    def test_trailing_newline_dest_refused(self, tmp_path: Path) -> None:
        """Review F8: \Z anchors — an invisible trailing byte must not
        validate."""
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger, _record_scope(rec),
            {"verb": "route", "record_id": rec.id, "dest": "skill-md\n"},
        )
        assert isinstance(result, str)

    def test_empty_string_optionals_are_absent(self, tmp_path: Path) -> None:
        """T-B(6) live finding 2026-07-17: the model filled optional tool
        params with "" — an empty dest/note/until must read as ABSENT,
        never refuse a valid proposal."""
        sb, (rec,) = _seed(tmp_path)
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "route", "record_id": rec.id, "dest": "skill-md",
             "note": "n", "until": ""},
        )
        assert isinstance(result, VerbProposal)
        assert result.until is None
        result2 = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "graduate", "record_id": rec.id, "dest": "", "note": "", "until": ""},
        )
        assert isinstance(result2, VerbProposal)
        assert result2.dest is None and result2.note is None

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

    def test_nonce_mismatch_never_arms_or_disarms(self) -> None:
        """Review F5: a clear-then-reoccupy mints a new nonce — a POST
        carrying the OLD nonce takes the stale path, never the new
        content."""
        slot = ProposalSlot()
        first = self._proposal()
        slot.occupy(first)
        old_nonce = first.nonce
        slot.clear()
        second = self._proposal()
        slot.occupy(second)
        assert slot.arm("lrn-aa000001", old_nonce) is None
        assert slot.current is not None and not slot.current.armed
        assert slot.arm("lrn-aa000001", second.nonce) is not None

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
        await manager.wait_for_turn()  # Y-15: the first turn drains in the background
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
            await manager.wait_for_turn()  # Y-15: join before the follow-up turn
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
    # Y-15: pane drains are background tasks on the app's event loop —
    # run every request of a test on ONE persistent portal (support.py).
    enter_client(c)

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
        prop = _occupy(manager, rec)
        armed = c.post(
            "/proposal/arm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
        assert 'data-armed="true"' in armed
        assert "Enter" in armed
        disarmed = c.post(
            "/proposal/disarm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
        assert 'data-proposal="waiting"' in disarmed
        assert manager.proposal_slot.current is not None  # back to waiting, not cleared

    def test_stale_nonce_confirm_is_a_no_op(self, tmp_path: Path) -> None:
        """Review F5, the confirm half: dismiss + re-propose between the
        human's read and their Enter — the old bar's confirm carries the
        old nonce and must execute NOTHING."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        first = _occupy(manager, rec, verb="reject")
        manager.proposal_slot.arm(rec.id)
        old_nonce = first.nonce
        manager.proposal_slot.clear()
        second = _occupy(manager, rec, verb="route", dest="skill-md")
        manager.proposal_slot.arm(rec.id)
        c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": old_nonce},
            headers=HX,
        )
        assert runner.calls == []
        assert manager.proposal_slot.current is not None  # untouched

    def test_bar_leads_with_the_human_line_id_trailing(self, tmp_path: Path) -> None:
        """Review F2 (Y-9): the waiting bar's leading text is the record
        title; the lrn- id renders after it as metadata."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec, title="About to edit .storage while HA is running.")
        page = c.get(f"/record/{rec.id}").text
        title_pos = page.find("About to edit .storage")
        id_pos = page.find(rec.id, title_pos)
        assert title_pos != -1 and id_pos != -1
        assert title_pos < id_pos

    def test_confirm_executes_exactly_the_slot_argv_and_clears(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec, verb="defer", until="2026-09-01", note="agent thought")
        armed_prop = manager.proposal_slot.arm(rec.id)
        assert armed_prop is not None
        resp = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": armed_prop.nonce},
            headers=HX,
        )
        # Resolution-evidence unit: `defer` carries `--json` on every
        # confirm now, and — being one of the four evidence-bearing
        # verbs — no longer auto-redirects (§3.4's 4th site: the
        # pane-proposal confirm path).
        assert [
            "defer", rec.id, "--until", "2026-09-01", "--json", "--note", "agent thought"
        ] in runner.calls
        assert manager.proposal_slot.current is None
        assert "HX-Redirect" not in resp.headers
        assert 'data-verb-success="true"' in resp.text

    def test_route_proposal_with_dest_records_by_agent(self, tmp_path: Path) -> None:
        """FW-64: the SDK pane is a THIRD chooser, previously
        misrepresented as one of the other two — when the agent's own
        `propose_verb` tool call names a `dest` itself (its own choice,
        not the deterministic analyst heuristic and not a human's own
        pick), the dispatched argv must say `--by agent`. Before this
        fix, `verbs.route`'s dest-is-not-None heuristic alone would have
        read "human" here (an explicit `--dest` present) — exactly the
        second wrong branch the FW-64 brief names."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec, verb="route", dest="skill-md")
        armed_prop = manager.proposal_slot.arm(rec.id)
        assert armed_prop is not None
        c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": armed_prop.nonce},
            headers=HX,
        )
        assert ["route", rec.id, "--dest", "skill-md", "--by", "agent", "--json"] in runner.calls

    def test_route_proposal_without_dest_records_by_analyst(self, tmp_path: Path) -> None:
        """The twin: a bare `route` proposal (the agent deferring to
        whatever the analyst's own stored proposal already names) omits
        `--dest` — exactly like a bare CLI `route <id>` — and the
        dispatched argv says `--by analyst`, never "agent" (the agent
        chose to ROUTE, but did not choose the DESTINATION) and never
        the old "analyst when dest omitted" GUESS this call site used to
        rely on implicitly."""
        sb, (rec,) = _seed(tmp_path)
        seed_proposal(sb.ledger, rec.id, destination="skill-md")
        c, runner, manager = make_client(sb)
        _occupy(manager, rec, verb="route")
        armed_prop = manager.proposal_slot.arm(rec.id)
        assert armed_prop is not None
        c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": armed_prop.nonce},
            headers=HX,
        )
        assert ["route", rec.id, "--by", "analyst", "--json"] in runner.calls

    def test_confirm_on_waiting_bar_executes_nothing(self, tmp_path: Path) -> None:
        """Enter never acts on a waiting bar — and even a forged confirm
        POST against an un-armed slot is a no-op."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        prop = _occupy(manager, rec)
        c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        )
        assert runner.calls == []
        assert manager.proposal_slot.current is not None  # untouched

    def test_missing_nonce_is_a_422_never_a_bypass(self, tmp_path: Path) -> None:
        """Delta residual 1: an empty/missing nonce must never bypass the
        identity check — the field is REQUIRED on all four routes."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        manager.proposal_slot.arm(rec.id)
        for path in ("/proposal/arm", "/proposal/disarm", "/proposal/dismiss", "/proposal/confirm"):
            resp = c.post(path, data={"record_id": rec.id, "kind": "detail"}, headers=HX)
            assert resp.status_code == 422, path
        assert runner.calls == []
        assert manager.proposal_slot.current is not None

    def test_dismiss_clears_and_next_proposal_succeeds(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        prop = _occupy(manager, rec)
        out = c.post(
            "/proposal/dismiss",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
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
        # FW-64: the human's confirm never cycled the destination (their
        # POST carries `dest` alone, no `dest_touched`), so this is an
        # unmodified approve-as-proposed — `by` reads "analyst".
        assert ["route", rec.id, "--dest", "skill-md", "--by", "analyst", "--json"] in runner.calls
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
        """U-grad-ui spec criterion 4(b) (this test IS that criterion's
        exact behaviour — updated in place, not superseded by a new
        test): the record's own Detail page now renders (200) instead of
        redirecting, but the clear-set behaviour `routes.py` performed on
        the deleted redirect path survives unchanged — the slot is still
        cleared, and (the paired absence half, so this isn't just "a page
        rendered") no proposal bar appears in the resolved body."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        resp = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert resp.status_code == 200
        assert manager.proposal_slot.current is None
        assert "Agent proposes:" not in resp.text
        assert 'data-proposal="waiting"' not in resp.text

    def test_stale_arm_after_external_resolution_renders_gone(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        prop = _occupy(manager, rec)
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        out = c.post(
            "/proposal/arm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
        assert "resolved elsewhere" in out
        assert manager.proposal_slot.current is None
        assert runner.calls == []

    def test_confirm_failure_shows_stderr_verbatim_and_slot_stays_cleared(self, tmp_path: Path) -> None:
        sb, (rec,) = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="refused: scan hit"))
        c, runner, manager = make_client(sb, runner=runner)
        prop = _occupy(manager, rec)
        manager.proposal_slot.arm(rec.id)
        out = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
        assert "refused: scan hit" in out
        assert manager.proposal_slot.current is None

    def test_failed_pane_route_confirm_shows_error_not_the_contradicts_offer(
        self, tmp_path: Path
    ) -> None:
        """Review fold 2 (NIT), the pane twin: a FAILED `route` proposal
        confirm — even one whose record's proposal carries contradicts: —
        takes the ordinary stale/error leg (_proposal_gone, stderr
        verbatim), never the Y-8 offer."""
        sb, (rec,) = _seed(tmp_path)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md",
            contradicts=["skills/other/SKILL.md"],
        )
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="refused: scan hit"))
        c, _runner, manager = make_client(sb, runner=runner)
        _occupy(manager, rec, verb="route", dest="skill-md")
        prop = manager.proposal_slot.arm(rec.id)
        assert prop is not None
        out = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
        assert "refused: scan hit" in out
        assert "data-contradicts-offer" not in out
        assert "skills/other/SKILL.md" not in out

    def test_pane_route_confirm_offer_survives_the_routes_own_proposal_deletion(
        self, tmp_path: Path
    ) -> None:
        """U-C3 regression: :func:`proposal_confirm` (the pane/propose_verb
        confirm route — 09 §4.5, U12) has the SAME Y-8 contradicts-offer
        branch as ``/record/.../action/confirm``, reading the record's
        proposal sibling. It has the identical pre-fix hazard: the real
        `route` CLI deletes that sibling as part of resolving the record
        (ledger_ops.resolve_record -> remove_proposal_siblings, 08 §1), so
        a read AFTER runner.run() finds nothing. RouteSideEffectRunner
        reproduces exactly that deletion; the offer must still render
        with the edge, proving this route also captures BEFORE dispatch."""
        sb, (rec,) = _seed(tmp_path)
        seed_proposal(
            sb.ledger, rec.id, destination="skill-md",
            contradicts=["skills/other/SKILL.md"],
        )
        runner = RouteSideEffectRunner(sb.ledger)
        c, _runner, manager = make_client(sb, runner=runner)
        _occupy(manager, rec, verb="route", dest="skill-md")
        prop = manager.proposal_slot.arm(rec.id)
        assert prop is not None
        resp = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        )
        assert resp.status_code == 200
        assert "skills/other/SKILL.md" in resp.text
        assert "HX-Redirect" not in resp.headers
        # Review fold 1 (MINOR): assert the ACTUAL rendered partial
        # carries app.js's leg (d) reload-defer marker (see the
        # test_routes.py twin's identical fold note) — this route shares
        # the same contradicts_offer.html template.
        assert "data-contradicts-offer" in resp.text
        assert not (
            _bucket_dir(sb) / "proposals" / f"{rec.id}.yaml"
        ).exists()

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

    def test_bulk_graduate_sweeps_a_stale_proposal(self, tmp_path: Path) -> None:
        """Review F3: bulk-resolved records must not leave a stale bar."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        _occupy(manager, rec)
        # The fake runner doesn't move files — simulate the resolution the
        # real graduate performs, then run the bulk loop (whose sweep
        # re-reads status).
        resolve_record_directly(sb.ledger, _bucket_dir(sb), rec)
        c.post(
            "/bucket/skill/s/graduate-bulk",
            data={"ids": rec.id},
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
        """Resolution-evidence unit (§3.4's 4th site): `graduate` is one
        of the four evidence-bearing verbs, so this no longer redirects
        — the evidence leg renders with a "back to the bucket" link
        carrying the SAME target the old auto-redirect used to jump to."""
        sb, (rec,) = _seed(tmp_path)
        c, runner, manager = make_client(sb)
        prop = VerbProposal(
            verb="graduate", record_id=rec.id, bucket_scope="skill", bucket_name="s",
            session_key=pane.bucket_session_key("skill", "s"),
        )
        manager.proposal_slot.occupy(prop)
        manager.proposal_slot.arm(rec.id)
        resp = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "bucket", "nonce": prop.nonce},
            headers=HX,
        )
        assert ["graduate", rec.id, "--json"] in runner.calls
        assert resp.headers.get("HX-Redirect") is None
        assert 'data-verb-success="true"' in resp.text
        assert 'href="/bucket/skill/s"' in resp.text

    def test_bucket_confirm_failure_error_strip_carries_reload_defer_marker(
        self, tmp_path: Path
    ) -> None:
        """f5-errstrip live-DoD fix, the proposal_bar.html leg: unlike
        kind="detail" (which renders via action_bar.html), a FAILED
        kind="bucket" confirm renders _proposal_gone's proposal_bar.html
        branch — proposal_confirm calls _force_refresh(f"record:{id}")
        BEFORE checking result.ok, the exact race action_bar.html's fix
        addresses. Plain render-shape assertion (the ordering hazard is
        modeled in test_js_dom.py, which needs a real browser)."""
        sb, (rec,) = _seed(tmp_path)
        runner = FakeRunner()
        runner.queue_result(RunResult(1, stderr="refused: scan hit"))
        c, _runner, manager = make_client(sb, runner=runner)
        prop = VerbProposal(
            verb="graduate", record_id=rec.id, bucket_scope="skill", bucket_name="s",
            session_key=pane.bucket_session_key("skill", "s"),
        )
        manager.proposal_slot.occupy(prop)
        manager.proposal_slot.arm(rec.id)
        out = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "bucket", "nonce": prop.nonce},
            headers=HX,
        ).text
        assert "refused: scan hit" in out
        assert 'data-verb-error="true"' in out


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


# ------------------------------------------------------- rehome (Y-18 / U15)
#
# 09 §4.5 as amended 2026-07-18 (feedback round 3 item 3; §11 Y-18):
# `rehome` joins the closed proposable set with required `to`, validated
# AT INTAKE against hosts.yaml; the resolved target is a server-truth bar
# field; the bucket-change staleness leg clears the slot + renders a
# plain-words notice on the arm AND confirm routes — never a disarm.

from self_learn_ui.routes import NOTICE_PROPOSAL_MOVED, build_argv  # noqa: E402


def _seed_two_projects(tmp_path: Path):
    """A ledger with TWO registered projects: host A (make_env's combined
    host, holding the record's bucket) and host B — a second registered
    project with a distinctive basename and NO bucket yet."""
    sb = make_env(tmp_path)
    host_b = tmp_path / "repos" / "keyboards"
    init_repo(host_b)
    (host_b / "README.md").write_text("b\n", encoding="utf-8")
    commit_all(host_b, "host-b seed")
    (sb.ledger / "hosts.yaml").write_text(
        f"skills_root: {sb.host}\nprojects:\n  - path: {sb.host}\n"
        f"  - path: {host_b}\n",
        encoding="utf-8",
    )
    rec = make_knowledge(scope="project")
    seed_record(sb.ledger, rec, project_path=sb.host)
    return sb, host_b, rec


def _project_bucket(sb, host) -> Path:
    return sb.ledger / "projects" / slug_for(host)


def _move_record_cli_side(sb, rec, host_b) -> None:
    """Simulate a CLI-side `rehome`: the record file leaves its bucket
    for host B's (freshly created) bucket — pending, bytes untouched."""
    src = _project_bucket(sb, sb.host) / "pending" / f"{rec.id}.md"
    dst = _project_bucket(sb, host_b) / "pending" / f"{rec.id}.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)


class TestValidateRehome:
    def test_happy_path_stores_the_resolved_registered_path(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "rehome", "record_id": rec.id, "to": str(host_b)},
        )
        assert isinstance(result, VerbProposal)
        assert result.verb == "rehome"
        # server truth: the RESOLVED hosts.yaml path, never the raw string
        assert result.to == str(host_b.resolve())
        assert result.to_basename == "keyboards"
        assert result.bucket_scope == "project"
        assert result.bucket_name == slug_for(sb.host)

    def test_to_accepts_the_bucket_slug(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "rehome", "record_id": rec.id, "to": slug_for(host_b)},
        )
        assert isinstance(result, VerbProposal)
        assert result.to == str(host_b.resolve())

    def test_rehome_requires_to(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        for args in (
            {"verb": "rehome", "record_id": rec.id},
            {"verb": "rehome", "record_id": rec.id, "to": ""},
        ):
            result = validate_proposal(sb.ledger, _record_scope(rec), args)
            assert isinstance(result, str)
            assert "rehome needs to" in result

    def test_to_refused_on_every_other_verb(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "route", "record_id": rec.id, "to": str(host_b)},
        )
        assert result == "proposal refused: to only applies to rehome proposals"

    def test_unregistered_target_teaches_the_register_affordance(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        stranger = tmp_path / "repos" / "stranger"
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "rehome", "record_id": rec.id, "to": str(stranger)},
        )
        assert isinstance(result, str)
        assert "not a registered project" in result
        # the teaching string names the human's register affordance
        assert "Register control" in result
        assert "self-learn host add <path>" in result

    def test_target_equals_current_bucket_refuses(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "rehome", "record_id": rec.id, "to": str(sb.host)},
        )
        assert isinstance(result, str)
        assert "nothing to move" in result

    def test_non_project_source_now_succeeds(self, tmp_path: Path) -> None:
        """U-verbs MOVE9: the CLI-side ``_move`` widened to accept any
        live-status source scope, and the UI's own source-scope refusal
        (the old "project→project only (M1)" line) was deleted to match
        — only the TARGET stays narrowed to a registered project. A
        skill-scoped record proposing ``rehome`` to a registered project
        now VALIDATES (a :class:`VerbProposal`, not a refusal string)."""
        sb, host_b, _ = _seed_two_projects(tmp_path)
        skill_rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, skill_rec)
        result = validate_proposal(
            sb.ledger,
            _record_scope(skill_rec),
            {"verb": "rehome", "record_id": skill_rec.id, "to": str(host_b)},
        )
        assert isinstance(result, VerbProposal)
        assert result.verb == "rehome"
        assert result.record_id == skill_rec.id
        assert result.to == str(host_b)


class TestRehomeProposalRoutes:
    def _occupy_rehome(self, manager, sb, host_b, rec, **kw) -> VerbProposal:
        prop = VerbProposal(
            verb="rehome",
            record_id=rec.id,
            bucket_scope="project",
            bucket_name=slug_for(sb.host),
            session_key=rec.id,
            title="The router reserves 192.0.2.232 for the Beacon.",
            to=str(host_b.resolve()),
            **kw,
        )
        assert manager.proposal_slot.occupy(prop)
        return prop

    def test_build_argv_rehome(self) -> None:
        assert build_argv("rehome", "lrn-0000aaaa", to="/w/keyboards", note="n") == [
            "rehome", "lrn-0000aaaa", "--to", "/w/keyboards", "--note", "n",
        ]

    def test_waiting_bar_copy_leads_domestic_with_resolved_path_trailing(self, tmp_path: Path) -> None:
        """Y-18 fold F7: the leading line is 'move this lesson to the
        ⟨basename⟩ project'; the resolved path renders as trailing
        disambiguating metadata beside the id."""
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        self._occupy_rehome(manager, sb, host_b, rec)
        page = c.get(f"/record/{rec.id}").text
        assert "move this lesson to the keyboards project" in page
        assert str(host_b.resolve()) in page
        assert 'data-proposal="waiting"' in page
        lead = page.find("move this lesson to the keyboards project")
        path_pos = page.find(str(host_b.resolve()), lead)
        id_pos = page.find(rec.id, lead)
        assert lead != -1 and path_pos != -1 and id_pos != -1
        assert lead < path_pos
        assert lead < id_pos

    def test_confirm_rebuilds_argv_from_the_slot_resolved_target(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        self._occupy_rehome(manager, sb, host_b, rec, note="umbrella project")
        armed = manager.proposal_slot.arm(rec.id)
        assert armed is not None
        resp = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": armed.nonce},
            headers=HX,
        )
        assert [
            "rehome", rec.id, "--to", str(host_b.resolve()),
            "--note", "umbrella project",
        ] in runner.calls
        assert manager.proposal_slot.current is None
        assert "HX-Redirect" in resp.headers

    def test_human_action_bar_has_no_rehome_path(self, tmp_path: Path) -> None:
        """Y-18 decision 3: no human-side re-home key or control in M1 —
        the standing action-bar routes refuse the verb outright."""
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        for path in (
            f"/record/{rec.id}/action/arm",
            f"/record/{rec.id}/action/confirm",
        ):
            resp = c.post(path, data={"verb": "rehome", "kind": "detail"}, headers=HX)
            assert resp.status_code == 400, path
        assert runner.calls == []


class TestBucketStalenessLeg:
    """Y-18 folds F2/F5/F10: a CLI-side rehome while a proposal is
    WAITING or ARMED — the arm AND confirm routes compare the slot's
    captured bucket against locate_record's current bucket, and on
    mismatch the outcome is identical: cleared slot + plain-words
    notice. Never the verb, never a disarm, never a waiting bar."""

    def _occupy_project(self, manager, sb, rec, **kw) -> VerbProposal:
        prop = VerbProposal(
            verb="reject",
            record_id=rec.id,
            bucket_scope="project",
            bucket_name=slug_for(sb.host),
            session_key=rec.id,
            **kw,
        )
        assert manager.proposal_slot.occupy(prop)
        return prop

    def _assert_cleared_with_notice(self, manager, runner, text: str) -> None:
        assert NOTICE_PROPOSAL_MOVED in text
        assert manager.proposal_slot.current is None
        assert 'data-armed="true"' not in text
        assert 'data-proposal="waiting"' not in text
        assert runner.calls == []

    def test_waiting_proposal_arm_after_cli_move_clears_with_notice(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        prop = self._occupy_project(manager, sb, rec)
        _move_record_cli_side(sb, rec, host_b)
        out = c.post(
            "/proposal/arm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
        self._assert_cleared_with_notice(manager, runner, out)

    def test_armed_proposal_confirm_after_cli_move_clears_with_notice(self, tmp_path: Path) -> None:
        """The load-bearing confirm-side check: without it Enter on a
        stale armed bar would execute the verb against the record in its
        NEW bucket."""
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        self._occupy_project(manager, sb, rec)
        armed = manager.proposal_slot.arm(rec.id)
        assert armed is not None
        _move_record_cli_side(sb, rec, host_b)
        out = c.post(
            "/proposal/confirm",
            data={"record_id": rec.id, "kind": "detail", "nonce": armed.nonce},
            headers=HX,
        ).text
        self._assert_cleared_with_notice(manager, runner, out)

    def test_armed_proposal_arm_rerender_after_cli_move_same_outcome(self, tmp_path: Path) -> None:
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        self._occupy_project(manager, sb, rec)
        armed = manager.proposal_slot.arm(rec.id)
        assert armed is not None
        _move_record_cli_side(sb, rec, host_b)
        out = c.post(
            "/proposal/arm",
            data={"record_id": rec.id, "kind": "detail", "nonce": armed.nonce},
            headers=HX,
        ).text
        self._assert_cleared_with_notice(manager, runner, out)

    def test_bucket_kind_gets_the_same_cleared_outcome(self, tmp_path: Path) -> None:
        """WAITING and ARMED end in the IDENTICAL cleared-slot+notice
        outcome on the bucket pane's region too."""
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        prop = self._occupy_project(manager, sb, rec)
        _move_record_cli_side(sb, rec, host_b)
        out = c.post(
            "/proposal/arm",
            data={"record_id": rec.id, "kind": "bucket", "nonce": prop.nonce},
            headers=HX,
        ).text
        self._assert_cleared_with_notice(manager, runner, out)
        assert "proposal-region-empty" in out

    def test_rehome_proposal_itself_goes_stale_when_record_moves(self, tmp_path: Path) -> None:
        """A rehome proposal whose record was ALREADY moved CLI-side dies
        the same way — the agent re-proposes against the new home."""
        sb, host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client(sb)
        prop = VerbProposal(
            verb="rehome",
            record_id=rec.id,
            bucket_scope="project",
            bucket_name=slug_for(sb.host),
            session_key=rec.id,
            to=str(host_b.resolve()),
        )
        assert manager.proposal_slot.occupy(prop)
        _move_record_cli_side(sb, rec, host_b)
        out = c.post(
            "/proposal/arm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers=HX,
        ).text
        self._assert_cleared_with_notice(manager, runner, out)


class TestObligation13UISideSingleCommandString:
    """A2 §13 item 13 (the UI half): the review UI's own package must
    never independently reconstruct the chezmoi-adopt invocation string
    — it can only ever come from ``self_learn.chezmoi.adopt_command``
    (the CLI's single source, §10.5). This package has ``self_learn``
    importable (proposals.py itself already imports from
    ``self_learn.hosts``), so this check runs here rather than in the
    CLI suite's own venv-isolated twin
    (plugins/self-learn/cli/tests/test_a2_rules_local.py)."""

    def test_ui_package_never_hardcodes_the_adopt_invocation(self) -> None:
        import self_learn_ui
        from self_learn import chezmoi

        needle = chezmoi.ADOPT_COMMAND_PREFIX  # "self-learn chezmoi-adopt "
        pkg_dir = Path(self_learn_ui.__file__).parent
        for py in pkg_dir.rglob("*.py"):
            assert needle not in py.read_text(encoding="utf-8"), py

    def test_adopt_command_is_the_single_source(self) -> None:
        from self_learn import chezmoi

        target = Path("/tmp/example/rules/subagents.md")
        assert chezmoi.adopt_command(target) == f"self-learn chezmoi-adopt {target}"
