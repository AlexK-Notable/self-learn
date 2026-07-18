"""prefetch.py — the U16/Y-19 item 1 next-record prefetch cache. Pure
unit tests, no ledger/httpx dependency (mirrors test_sse.py's "pure
asyncio, no FastAPI/httpx" posture) — the CRITICAL staleness rule lives
entirely in :class:`DetailPrefetchCache`'s generation comparison, so it
is provable here in isolation before any route-level integration test.
"""

from __future__ import annotations

from self_learn_ui.prefetch import DetailPrefetchCache


class TestWarmHit:
    def test_put_then_get_at_the_same_generation_returns_the_value(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 3, "bundle-a")
        assert cache.get("lrn-aa000001", 3) == "bundle-a"

    def test_miss_on_an_empty_cache(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        assert cache.get("lrn-aa000001", 0) is None

    def test_miss_on_a_different_key_even_at_the_same_generation(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 3, "bundle-a")
        assert cache.get("lrn-aa000002", 3) is None

    def test_single_slot_a_second_put_evicts_the_first(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 1, "bundle-a")
        cache.put("lrn-aa000002", 1, "bundle-b")
        assert cache.get("lrn-aa000001", 1) is None
        assert cache.get("lrn-aa000002", 1) == "bundle-b"


class TestNeverStale:
    """The CRITICAL rule: a generation mismatch is ALWAYS a miss, in
    either direction — a warmed entry can never be served against a
    generation other than the exact one it was stamped with."""

    def test_stale_generation_after_a_refresh_is_a_miss(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 5, "bundle-a")
        # A refresh/verb bumped the generation past what this entry was
        # stamped with (5) — any later generation invalidates it.
        assert cache.get("lrn-aa000001", 6) is None

    def test_a_generation_that_never_advanced_is_also_a_miss(self) -> None:
        """Defensive: an entry stamped AHEAD of the caller's observed
        generation (should never happen — generation is monotonic in
        production) is still never served; equality is the only match."""
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 5, "bundle-a")
        assert cache.get("lrn-aa000001", 4) is None

    def test_a_stale_hit_clears_the_entry_so_it_cannot_leak_to_a_later_lookup(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 5, "bundle-a")
        assert cache.get("lrn-aa000001", 6) is None  # stale — invalidates
        # Even re-asking at the ORIGINAL generation now misses — the
        # stale read dropped the entry rather than leaving it sitting
        # there to be misread by a differently-timed second lookup.
        assert cache.get("lrn-aa000001", 5) is None

    def test_clear_removes_any_held_entry_regardless_of_generation(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 1, "bundle-a")
        cache.clear()
        assert cache.get("lrn-aa000001", 1) is None


class TestPeekGeneration:
    def test_peek_generation_reports_the_stamped_value(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        cache.put("lrn-aa000001", 7, "bundle-a")
        assert cache.peek_generation("lrn-aa000001") == 7

    def test_peek_generation_none_for_a_different_or_absent_key(self) -> None:
        cache: DetailPrefetchCache[str] = DetailPrefetchCache()
        assert cache.peek_generation("lrn-aa000001") is None
        cache.put("lrn-aa000001", 1, "bundle-a")
        assert cache.peek_generation("lrn-aa000002") is None
