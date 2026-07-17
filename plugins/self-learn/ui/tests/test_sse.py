"""sse.py — envelope helpers, AppEventHub pub/sub, and the merged
event_stream (10 §1 SSE protocol row). Pure asyncio, no FastAPI/httpx."""

from __future__ import annotations

import asyncio
import json

import pytest

from self_learn_ui.ledger import RefreshEvent, RefreshHub
from self_learn_ui.sse import (
    AppEventHub,
    envelope_applying,
    envelope_banner,
    envelope_bulk_progress,
    envelope_refresh,
    event_stream,
    format_sse,
)


class TestEnvelopeHelpers:
    def test_refresh_envelope_shape(self) -> None:
        assert envelope_refresh("bucket:s") == {"type": "refresh", "scope": "bucket:s"}

    def test_applying_envelope_shape(self) -> None:
        env = envelope_applying("route", "lrn-aa000001", "start")
        assert env == {
            "type": "applying",
            "verb": "route",
            "id": "lrn-aa000001",
            "state": "start",
        }

    def test_bulk_progress_envelope_shape(self) -> None:
        env = envelope_bulk_progress(2, 5, failed_id=None)
        assert env == {"type": "bulk_progress", "done": 2, "total": 5, "failed_id": None}

    def test_banner_envelope_shape(self) -> None:
        assert envelope_banner("bucket clear") == {"type": "banner", "text": "bucket clear"}

    def test_format_sse_is_data_prefixed_json_double_newline_terminated(self) -> None:
        frame = format_sse({"type": "banner", "text": "hi"})
        assert frame.startswith("data: ")
        assert frame.endswith("\n\n")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {"type": "banner", "text": "hi"}


class TestAppEventHub:
    async def test_subscribe_receives_published_envelope(self) -> None:
        hub = AppEventHub()
        q = hub.subscribe()
        await hub.publish({"type": "banner", "text": "x"})
        got = await asyncio.wait_for(q.get(), timeout=1)
        assert got == {"type": "banner", "text": "x"}

    async def test_unsubscribed_queue_receives_nothing(self) -> None:
        hub = AppEventHub()
        q = hub.subscribe()
        hub.unsubscribe(q)
        await hub.publish({"type": "banner", "text": "x"})
        assert q.empty()

    def test_publish_nowait_is_sync_callable(self) -> None:
        hub = AppEventHub()
        q = hub.subscribe()
        hub.publish_nowait({"type": "applying", "verb": "route", "id": "lrn-x", "state": "start"})
        assert q.get_nowait() == {
            "type": "applying",
            "verb": "route",
            "id": "lrn-x",
            "state": "start",
        }

    async def test_multiple_subscribers_all_receive(self) -> None:
        hub = AppEventHub()
        q1, q2 = hub.subscribe(), hub.subscribe()
        await hub.publish({"type": "banner", "text": "both"})
        assert (await q1.get())["text"] == "both"
        assert (await q2.get())["text"] == "both"


class TestEventStreamMerge:
    async def test_refresh_hub_events_come_through_as_refresh_envelopes(self) -> None:
        refresh_hub = RefreshHub()
        app_hub = AppEventHub()
        stream = event_stream(refresh_hub, app_hub)

        async def produce() -> None:
            await asyncio.sleep(0.01)
            await refresh_hub.publish(RefreshEvent(scope="front"))

        task = asyncio.ensure_future(produce())
        frame = await asyncio.wait_for(stream.__anext__(), timeout=2)
        await task
        assert frame == format_sse({"type": "refresh", "scope": "front"})
        await stream.aclose()

    async def test_app_hub_events_pass_through_verbatim(self) -> None:
        refresh_hub = RefreshHub()
        app_hub = AppEventHub()
        stream = event_stream(refresh_hub, app_hub)

        async def produce() -> None:
            await asyncio.sleep(0.01)
            await app_hub.publish({"type": "banner", "text": "bucket clear"})

        task = asyncio.ensure_future(produce())
        frame = await asyncio.wait_for(stream.__anext__(), timeout=2)
        await task
        assert frame == format_sse({"type": "banner", "text": "bucket clear"})
        await stream.aclose()

    async def test_events_from_both_hubs_interleave_in_order_sent(self) -> None:
        # A subscriber queue only exists once the async generator body has
        # started running (lazily, on the first __anext__ call) — publish
        # from a background task that waits for the consumer to be
        # mid-await, exactly like the two tests above.
        refresh_hub = RefreshHub()
        app_hub = AppEventHub()
        stream = event_stream(refresh_hub, app_hub)

        async def produce_first() -> None:
            await asyncio.sleep(0.01)
            await refresh_hub.publish(RefreshEvent(scope="front"))

        task1 = asyncio.ensure_future(produce_first())
        first = await asyncio.wait_for(stream.__anext__(), timeout=2)
        await task1
        assert first == format_sse({"type": "refresh", "scope": "front"})

        async def produce_second() -> None:
            await asyncio.sleep(0.01)
            await app_hub.publish({"type": "banner", "text": "next"})

        task2 = asyncio.ensure_future(produce_second())
        second = await asyncio.wait_for(stream.__anext__(), timeout=2)
        await task2
        assert second == format_sse({"type": "banner", "text": "next"})
        await stream.aclose()

    async def test_disconnect_unsubscribes_both_hubs(self) -> None:
        refresh_hub = RefreshHub()
        app_hub = AppEventHub()
        stream = event_stream(refresh_hub, app_hub)

        async def produce() -> None:
            await asyncio.sleep(0.01)
            await refresh_hub.publish(RefreshEvent(scope="front"))

        task = asyncio.ensure_future(produce())
        await asyncio.wait_for(stream.__anext__(), timeout=2)
        await task
        assert len(refresh_hub._subscribers) == 1
        assert len(app_hub._subscribers) == 1
        await stream.aclose()
        assert len(refresh_hub._subscribers) == 0
        assert len(app_hub._subscribers) == 0
