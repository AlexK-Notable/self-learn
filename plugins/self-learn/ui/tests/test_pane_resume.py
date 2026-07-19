"""U22 (Y-28, 10 §3 U22 row) — durable pane/Iterate transcripts with
resume, at the PaneManager level. test_store.py covers the store in
isolation; this file covers §7's remaining test obligations that need a
live PaneManager + FakeEngine: the SIGKILL/no-flush leg through the
manager, restart-resume integration, the rehome invalidation case, the
errored-session predicate case, `q` = park-not-delete, and the
proposal-slot-never-resurrects pin.

No network, no real model anywhere in this file (10 §0 rule 7).
"""

from __future__ import annotations

from pathlib import Path

from self_learn_ui import pane
from self_learn_ui.engine.base import BlockStart, FakeEngine, PaneContext, PaneEngine, Result, TextDelta, ToolUse
from self_learn_ui.ledger import RefreshHub
from self_learn_ui.runner import FakeRunner
from self_learn_ui.sse import AppEventHub
from self_learn_ui.store import PaneTranscriptStore

from support import make_behavior, make_env, seed_record

RECORD_ID = "lrn-aa000001"


def _manager(
    *,
    home: Path,
    bucket_root: Path,
    store: PaneTranscriptStore | None,
    engines: dict[str, PaneEngine] | None = None,
    default_engine_factory=None,
) -> tuple[pane.PaneManager, dict]:
    engines = engines or {}
    state = {"record_id": None, "ctxs": []}

    def engine_factory_for(record_id: str) -> PaneEngine:
        if record_id in engines:
            return engines[record_id]
        return default_engine_factory() if default_engine_factory else FakeEngine(
            turns=[
                [
                    BlockStart(kind="text"),
                    TextDelta(text="hello"),
                    Result(status="success", cost_usd=0.001, error=None, turns=1, session_id="sdk-sess-1"),
                ]
            ]
        )

    def context_builder(record_id: str) -> PaneContext:
        state["record_id"] = record_id
        ctx = PaneContext(
            record_id=record_id,
            bucket_root=bucket_root,
            self_learn_home=home,
            system_prompt="doctrine",
            first_message="first message",
        )
        state["ctxs"].append(ctx)
        return ctx

    def engine_factory() -> PaneEngine:
        return engine_factory_for(state["record_id"])

    manager = pane.PaneManager(
        engine_factory=engine_factory,
        context_builder=context_builder,
        app_hub=AppEventHub(),
        refresh_hub=RefreshHub(),
        runner=FakeRunner(),
        store=store,
        home=home,
    )
    return manager, state


async def _start_and_join(manager: pane.PaneManager, record_id: str, **kwargs) -> str:
    outcome = await manager.start(record_id, **kwargs)
    await manager.wait_for_turn()
    return outcome


async def _resume_and_join(manager: pane.PaneManager, record_id: str, **kwargs) -> str:
    outcome = await manager.resume(record_id, **kwargs)
    await manager.wait_for_turn()
    return outcome


def _seed(tmp_path: Path):
    sandbox = make_env(tmp_path)
    record = make_behavior(scope="skill:s")
    path = seed_record(sandbox.ledger, record)
    bucket_dir = path.parent.parent
    return sandbox, record, bucket_dir


# ------------------------------------------------------------- persistence


async def test_completed_session_reconstructs_deep_equal_snapshot(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)

    await _start_and_join(manager, record.id)
    live_snap = manager.snapshot(record.id)

    # A fresh manager over the SAME store dir, with no live session.
    store2 = PaneTranscriptStore(tmp_path / "panes")
    manager2, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store2)
    idle_snap = manager2.snapshot(record.id)

    assert idle_snap.has_persisted_transcript is True
    assert idle_snap.persisted_block_count == len(live_snap.blocks)
    view = manager2.view_snapshot(record.id)
    assert view is not None
    assert [b.html for b in view.blocks] == [b.html for b in live_snap.blocks]
    assert view.result_status == live_snap.result_status
    assert view.result_cost_usd == live_snap.result_cost_usd


async def test_q_close_parks_to_disk_not_delete(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)

    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    snap = manager.snapshot(record.id)
    assert snap.state == pane.STATE_IDLE
    assert snap.has_persisted_transcript is True
    assert snap.persisted_block_count and snap.persisted_block_count > 0


async def test_resolve_verb_leaves_transcript_but_not_resumable(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)

    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    # Simulate a resolution verb: move pending -> resolved, flip status.
    pending_path = bucket_dir / "pending" / f"{record.id}.md"
    record.set_status("routed")
    resolved_path = bucket_dir / "resolved" / f"{record.id}.md"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    record.write(resolved_path)
    pending_path.unlink()

    snap = manager.snapshot(record.id)
    assert snap.has_persisted_transcript is True
    assert snap.resumable is False
    assert snap.persisted_lifecycle_words == "finished"


async def test_rehome_bucket_move_invalidates_resumable(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)

    await _start_and_join(manager, record.id)
    await manager.close(record.id)
    assert manager.snapshot(record.id).resumable is True

    # Simulate rehome: record STAYS pending/deferred but moves buckets.
    new_bucket = sandbox.ledger / "skills" / "other-skill"
    (new_bucket / "pending").mkdir(parents=True)
    old_path = bucket_dir / "pending" / f"{record.id}.md"
    new_path = new_bucket / "pending" / f"{record.id}.md"
    new_path.write_bytes(old_path.read_bytes())
    old_path.unlink()

    snap = manager.snapshot(record.id)
    assert snap.has_persisted_transcript is True
    assert snap.resumable is False  # bucket_dir moved — §4e MAJOR-2


async def test_errored_session_predicate_excludes_resumable(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    engine = FakeEngine(
        turns=[[Result(status="error_during_execution", cost_usd=None, error="boom", turns=1)]]
    )
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store, engines={record.id: engine})

    await _start_and_join(manager, record.id)
    # An errored session parks ENDED, live session still occupies the
    # slot (never torn down automatically) — close it to park to disk.
    await manager.close(record.id)

    snap = manager.snapshot(record.id)
    assert snap.has_persisted_transcript is True
    assert snap.resumable is False
    assert snap.persisted_lifecycle_words == "hit an error"


async def test_cap_hit_session_predicate_excludes_resumable(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    engine = FakeEngine(
        turns=[[Result(status="error_max_turns", cost_usd=0.5, error="cap hit", turns=15)]]
    )
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store, engines={record.id: engine})

    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    snap = manager.snapshot(record.id)
    assert snap.resumable is False
    assert snap.persisted_lifecycle_words == "stopped early"


# --------------------------------------------------------- SIGKILL leg


async def test_sigkill_leg_through_manager_survives_no_teardown(tmp_path: Path) -> None:
    """§7's pinned MUST: drive a FakeEngine to finalize >= 2 blocks, then
    drop ALL manager references with NO shutdown/close/teardown call —
    a fresh manager over the same store dir reconstructs every finalized
    block."""
    sandbox, record, bucket_dir = _seed(tmp_path)
    panes_dir = tmp_path / "panes"
    store = PaneTranscriptStore(panes_dir)
    engine = FakeEngine(
        turns=[
            [
                BlockStart(kind="text"),
                TextDelta(text="block one"),
                ToolUse(name="Read", target="/x/y"),
                # No Result — the "turn" is still in flight; the manager
                # is dropped before any teardown/flush path runs.
            ]
        ]
    )
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store, engines={record.id: engine})
    await _start_and_join(manager, record.id)
    del manager  # NO shutdown()/close()/teardown call anywhere

    store2 = PaneTranscriptStore(panes_dir)
    manager2, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store2)
    snap = manager2.snapshot(record.id)
    assert snap.has_persisted_transcript is True
    view = manager2.view_snapshot(record.id)
    assert view is not None
    kinds = [b.kind for b in view.blocks]
    assert "text" in kinds and "tool" in kinds
    assert len(view.blocks) >= 2


# --------------------------------------------------------------- resume


async def test_resume_tier2_when_sdk_session_id_captured(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, state = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)

    await _start_and_join(manager, record.id)
    await manager.close(record.id)
    assert manager.snapshot(record.id).resumable is True

    resume_engine = FakeEngine(
        turns=[
            [
                BlockStart(kind="text"),
                TextDelta(text="continuing"),
                Result(status="success", cost_usd=0.001, error=None, turns=1, session_id="sdk-sess-2"),
            ]
        ]
    )
    manager2, state2 = _manager(
        home=sandbox.ledger, bucket_root=bucket_dir, store=store, engines={record.id: resume_engine}
    )
    outcome = await _resume_and_join(manager2, record.id)
    assert outcome == "started"
    ctx_used = resume_engine.contexts[-1]
    assert ctx_used.resume_session_id == "sdk-sess-1"

    snap = manager2.snapshot(record.id)
    assert snap.lifecycle_note == "(resumed — earlier turns restored)"
    # The proposal slot must NEVER resurrect across a resume.
    assert manager2.proposal_slot.current is None


async def test_resume_tier1_5_reinjects_when_no_session_id(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    # A completed session whose engine never reported a session_id.
    engine = FakeEngine(
        turns=[
            [
                BlockStart(kind="text"),
                TextDelta(text="hello no session id"),
                Result(status="success", cost_usd=0.001, error=None, turns=1, session_id=None),
            ]
        ]
    )
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store, engines={record.id: engine})
    await _start_and_join(manager, record.id)
    await manager.close(record.id)
    assert manager.snapshot(record.id).resumable is True

    resume_engine = FakeEngine(
        turns=[
            [
                BlockStart(kind="text"),
                TextDelta(text="continuing"),
                Result(status="success", cost_usd=0.001, error=None, turns=1),
            ]
        ]
    )
    manager2, _ = _manager(
        home=sandbox.ledger, bucket_root=bucket_dir, store=store, engines={record.id: resume_engine}
    )
    outcome = await _resume_and_join(manager2, record.id)
    assert outcome == "started"
    ctx_used = resume_engine.contexts[-1]
    assert ctx_used.resume_session_id is None
    assert "hello no session id" in ctx_used.first_message
    assert "PRIOR CONVERSATION" in ctx_used.first_message

    snap = manager2.snapshot(record.id)
    assert snap.lifecycle_note == "(continued — earlier turns re-read as context)"


async def test_resume_continues_same_file_not_archived(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)
    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    resume_engine = FakeEngine(
        turns=[
            [
                BlockStart(kind="text"),
                TextDelta(text="turn two"),
                Result(status="success", cost_usd=0.001, error=None, turns=1, session_id="sdk-sess-2"),
            ]
        ]
    )
    manager2, _ = _manager(
        home=sandbox.ledger, bucket_root=bucket_dir, store=store, engines={record.id: resume_engine}
    )
    await _resume_and_join(manager2, record.id)

    archive_dir = tmp_path / "panes" / "archive"
    assert not archive_dir.is_dir() or not list(archive_dir.glob("*.jsonl"))
    view = manager2.view_snapshot(record.id)
    assert view is not None
    assert len(view.blocks) >= 2  # first session's block(s) + resumed turn's block


async def test_resume_returns_not_resumable_without_store(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=None)
    outcome = await manager.resume(record.id)
    assert outcome == "not-resumable"


async def test_resume_returns_not_resumable_when_predicate_fails(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)
    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    # Resolve the record — resumable should now be False.
    pending_path = bucket_dir / "pending" / f"{record.id}.md"
    record.set_status("routed")
    resolved_path = bucket_dir / "resolved" / f"{record.id}.md"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    record.write(resolved_path)
    pending_path.unlink()

    manager2, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)
    outcome = await manager2.resume(record.id)
    assert outcome == "not-resumable"


async def test_resume_armed_when_a_different_record_is_live(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    other = make_behavior(scope="skill:s")
    seed_record(sandbox.ledger, other)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)

    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    # A DIFFERENT record is live now.
    await manager.start(other.id)
    outcome = await manager.resume(record.id)
    assert outcome == "armed"


# --------------------------------------------------------------- view


async def test_view_snapshot_none_when_nothing_persisted(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)
    assert manager.view_snapshot(record.id) is None


async def test_view_snapshot_is_view_only_and_ended(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    store = PaneTranscriptStore(tmp_path / "panes")
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)
    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    view = manager.view_snapshot(record.id)
    assert view is not None
    assert view.view_only is True
    assert view.state == pane.STATE_ENDED
    assert view.lifecycle_note == "(view only)"


# ------------------------------------------------ corrupt/missing degrades


async def test_corrupt_store_degrades_to_fresh_idle_snapshot(tmp_path: Path) -> None:
    sandbox, record, bucket_dir = _seed(tmp_path)
    panes_dir = tmp_path / "panes"
    store = PaneTranscriptStore(panes_dir)
    manager, _ = _manager(home=sandbox.ledger, bucket_root=bucket_dir, store=store)
    await _start_and_join(manager, record.id)
    await manager.close(record.id)

    # Corrupt the file from the very first line.
    path = panes_dir / f"{record.id}.jsonl"
    path.write_text("not json at all\n")

    snap = manager.snapshot(record.id)
    assert snap.state == pane.STATE_IDLE
    assert snap.has_persisted_transcript is False  # nothing parses -> "no history" (§8 degrade)
