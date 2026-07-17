"""ledger.py's watcher half: watch-path discovery, scope tagging,
RefreshHub pub/sub, and a real watchfiles round-trip against a throwaway
ledger (bounded with asyncio.wait_for so a regression fails fast instead
of hanging CI).
"""

from __future__ import annotations

import asyncio

import pytest

from self_learn_ui import ledger

from support import make_behavior, make_env, seed_record


@pytest.fixture
def sandbox(tmp_path):
    return make_env(tmp_path, skills=("s",))


class TestWatchPaths:
    def test_lists_pending_and_proposals_per_bucket_plus_events(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000001"))
        paths = ledger.watch_paths(sandbox.ledger)
        names = {str(p) for p in paths}
        bucket_dir = sandbox.ledger / "skills" / "s"
        assert str(bucket_dir / "pending") in names
        assert str(bucket_dir / "proposals") in names
        assert str(sandbox.ledger / "events.jsonl") in names

    def test_bare_ledger_watches_the_user_bucket_plus_events(self, tmp_path):
        # bare_ledger's layout includes an (empty) user/ dir, which
        # discover_buckets counts as a bucket — watch_paths names its
        # pending/proposals dirs even though they don't exist on disk
        # yet (watch_ledger itself filters to existing paths at watch
        # time; watch_paths is the full candidate list).
        from support import bare_ledger

        home = bare_ledger(tmp_path)
        paths = ledger.watch_paths(home)
        assert paths == [
            home / "user" / "pending",
            home / "user" / "proposals",
            home / "events.jsonl",
        ]


class TestScopeForPath:
    def test_skill_bucket_pending_scopes_to_its_bucket(self, sandbox):
        p = sandbox.ledger / "skills" / "s" / "pending" / "lrn-x.md"
        assert ledger._scope_for_path(sandbox.ledger, p) == "bucket:s"

    def test_project_bucket_proposals_scopes_to_its_bucket(self, sandbox):
        p = sandbox.ledger / "projects" / "some-slug" / "proposals" / "lrn-x.yaml"
        assert ledger._scope_for_path(sandbox.ledger, p) == "bucket:some-slug"

    def test_user_bucket_scopes_to_user(self, sandbox):
        p = sandbox.ledger / "user" / "pending" / "lrn-x.md"
        assert ledger._scope_for_path(sandbox.ledger, p) == "bucket:user"

    def test_events_jsonl_scopes_to_front(self, sandbox):
        p = sandbox.ledger / "events.jsonl"
        assert ledger._scope_for_path(sandbox.ledger, p) == "front"

    def test_path_outside_home_falls_back_to_front(self, sandbox, tmp_path):
        outside = tmp_path / "elsewhere" / "file.md"
        assert ledger._scope_for_path(sandbox.ledger, outside) == "front"


class TestRefreshHub:
    @pytest.mark.asyncio
    async def test_publish_reaches_subscriber(self):
        hub = ledger.RefreshHub()
        q = hub.subscribe()
        await hub.publish(ledger.RefreshEvent(scope="front"))
        event = q.get_nowait()
        assert event.scope == "front"

    @pytest.mark.asyncio
    async def test_unsubscribed_queue_never_receives(self):
        hub = ledger.RefreshHub()
        q = hub.subscribe()
        hub.unsubscribe(q)
        await hub.publish(ledger.RefreshEvent(scope="front"))
        assert q.empty()

    @pytest.mark.asyncio
    async def test_two_subscribers_both_receive(self):
        hub = ledger.RefreshHub()
        q1, q2 = hub.subscribe(), hub.subscribe()
        await hub.publish(ledger.RefreshEvent(scope="bucket:s"))
        assert q1.get_nowait().scope == "bucket:s"
        assert q2.get_nowait().scope == "bucket:s"

    def test_force_refresh_is_sync_callable_and_delivers(self):
        hub = ledger.RefreshHub()
        q = hub.subscribe()
        hub.force_refresh("bucket:s")
        event = q.get_nowait()
        assert event.scope == "bucket:s"

    def test_force_refresh_default_scope_is_front(self):
        hub = ledger.RefreshHub()
        q = hub.subscribe()
        hub.force_refresh()
        assert q.get_nowait().scope == "front"


class TestWatchLedgerLive:
    @pytest.mark.asyncio
    async def test_file_write_under_pending_triggers_a_refresh_event(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000002"))
        hub = ledger.RefreshHub()
        q = hub.subscribe()
        stop = asyncio.Event()
        watcher = asyncio.create_task(
            ledger.watch_ledger(sandbox.ledger, hub, stop_event=stop, debounce_ms=50)
        )
        await asyncio.sleep(0.3)  # let watchfiles' inotify setup settle
        (sandbox.ledger / "skills" / "s" / "pending" / "lrn-aa000003.md").write_text(
            "trigger a change", encoding="utf-8"
        )
        try:
            event = await asyncio.wait_for(q.get(), timeout=5)
        finally:
            stop.set()
            await asyncio.wait_for(watcher, timeout=5)
        assert event.scope == "bucket:s"

    @pytest.mark.asyncio
    async def test_no_watch_paths_exist_returns_immediately(self, tmp_path):
        # A ledger home with no buckets and no events.jsonl on disk yet —
        # watch_paths() still names events.jsonl, but it doesn't exist,
        # so watch_ledger must return rather than hang or raise.
        from support import bare_ledger

        home = bare_ledger(tmp_path)
        hub = ledger.RefreshHub()
        await asyncio.wait_for(ledger.watch_ledger(home, hub), timeout=5)
