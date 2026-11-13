"""Speed batch 2: the pages' shared read cache, concurrent reads, and the
sections that load after the page appears."""
from __future__ import annotations

import threading
import time

import pytest

from self_learn_ui import ledger, models, readcache
from self_learn_ui.models import CliRead
from support import commit_all, make_behavior, make_env, seed_record
from test_humane_home import _client


# ------------------------------------------------------------ the cache itself


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _cache(ttl=30.0):
    clock = Clock()
    return readcache.ReadCache(ttl=ttl, clock=clock), clock


def test_a_cached_read_is_reused_inside_the_expiry_and_dropped_after_it():
    cache, clock = _cache()
    calls = []

    def produce():
        calls.append(1)
        return CliRead(data={"n": len(calls)})

    assert cache.get("report", "s1", produce).data == {"n": 1}
    clock.now += 29
    assert cache.get("report", "s1", produce).data == {"n": 1}
    assert len(calls) == 1
    clock.now += 2  # 31 s after the read
    assert cache.get("report", "s1", produce).data == {"n": 2}
    assert len(calls) == 2


def test_a_ledger_change_invalidates_at_once():
    cache, _clock = _cache()
    calls = []

    def produce():
        calls.append(1)
        return CliRead(data=len(calls))

    assert cache.get("status", (1, "abc"), produce).data == 1
    assert cache.get("status", (1, "abc"), produce).data == 1
    # the refresh generation moved (a verb finished or the watcher fired)
    assert cache.get("status", (2, "abc"), produce).data == 2
    # git HEAD moved with no event at all (a commit made elsewhere)
    assert cache.get("status", (2, "def"), produce).data == 3
    # and the old state does not come back from the dead
    assert cache.get("status", (1, "abc"), produce).data == 4


def test_a_failed_read_is_never_kept():
    cache, _clock = _cache()
    results = [CliRead(data=None, error="boom"), CliRead(data={"ok": True})]
    calls = []

    def produce():
        calls.append(1)
        return results[len(calls) - 1]

    first = cache.get("report", "s", produce)
    assert not first.ok
    second = cache.get("report", "s", produce)
    assert second.ok and second.data == {"ok": True}
    assert len(calls) == 2
    assert cache.get("report", "s", produce).data == {"ok": True}
    assert len(calls) == 2  # the success is kept


def test_concurrent_requests_share_one_read():
    cache, _clock = _cache()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def produce():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return CliRead(data="answer")

    out = []
    threads = [threading.Thread(target=lambda: out.append(cache.get("report", "s", produce))) for _ in range(4)]
    threads[0].start()
    assert started.wait(5)
    for t in threads[1:]:
        t.start()
    time.sleep(0.2)  # the other three are now waiting on the read in flight
    release.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert [r.data for r in out] == ["answer"] * 4


def test_a_read_in_flight_is_shared_even_with_nothing_kept():
    cache, _clock = _cache()
    started, release, calls = threading.Event(), threading.Event(), []

    def produce():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return CliRead(data="x")

    out = []
    first = threading.Thread(target=lambda: out.append(cache.get("attention", "s", produce, ttl=0)))
    first.start()
    assert started.wait(5)
    second = threading.Thread(target=lambda: out.append(cache.get("attention", "s", produce, ttl=0)))
    second.start()
    time.sleep(0.2)
    release.set()
    first.join(5)
    second.join(5)
    assert len(calls) == 1 and len(out) == 2
    cache.get("attention", "s", produce, ttl=0)  # nothing was stored
    assert len(calls) == 2


def test_a_failure_in_flight_reaches_every_waiter_and_is_not_kept():
    cache, _clock = _cache()
    started, release = threading.Event(), threading.Event()

    def produce():
        started.set()
        assert release.wait(5)
        return CliRead(data=None, error="down")

    out = []
    threads = [threading.Thread(target=lambda: out.append(cache.get("r", "s", produce))) for _ in range(2)]
    threads[0].start()
    assert started.wait(5)
    threads[1].start()
    time.sleep(0.2)
    release.set()
    for t in threads:
        t.join(5)
    assert [r.error for r in out] == ["down", "down"]
    assert cache.get("r", "s", lambda: CliRead(data=1)).data == 1


def test_what_a_caller_edits_does_not_reach_the_next_caller():
    cache, _clock = _cache()
    a = cache.get("r", "s", lambda: CliRead(data={"rows": [1]}))
    a.data["rows"].append(2)
    b = cache.get("r", "s", lambda: CliRead(data={"rows": ["fresh"]}))
    assert b.data == {"rows": [1]}


def test_head_signature_follows_the_ledgers_commits(tmp_path):
    sb = make_env(tmp_path)
    before = readcache.head_signature(sb.ledger)
    assert before and len(before) >= 40
    (sb.ledger / "note.txt").write_text("x")
    commit_all(sb.ledger, "another commit")
    after = readcache.head_signature(sb.ledger)
    assert after and after != before
    assert readcache.head_signature(tmp_path / "not-a-repo") is None


# -------------------------------------------------------------------- pages


class Reads:
    """Count (and optionally gate) the page reads the routes make."""

    def __init__(self, monkeypatch):
        self.calls: dict[str, int] = {}
        self.fail: set[str] = set()
        self.gate = None
        self.report_data = {"buckets": [], "routed_live": [], "series": None}
        for name, attr in (("list", "list_items"), ("status", "status"), ("status-fast", "status_fast"),
                           ("report", "report"), ("mine", "mine_status")):
            monkeypatch.setattr(ledger, attr, self._make(name))

    def _make(self, name):
        def read(home, **kw):
            self.calls[name] = self.calls.get(name, 0) + 1
            if self.gate is not None:
                self.gate(name)
            if name in self.fail:
                return CliRead(data=None, error=f"the {name} read failed")
            return CliRead(data=self._data(name))
        return read

    def _data(self, name):
        if name == "list":
            return []
        if name == "report":
            return self.report_data
        if name == "mine":
            return {"last_run": None, "stale": False, "runs": []}
        return {"buckets": [], "total_pending": 0, "open_followups": 0, "worker_last_run": None,
                "home_state": "ok"}


@pytest.fixture
def reads(monkeypatch):
    return Reads(monkeypatch)


def _bucket_env(tmp_path):
    sb = make_env(tmp_path, skills=("s",))
    seed_record(sb.ledger, make_behavior(scope="skill:s"))
    return sb


def test_pages_share_reads_and_a_ledger_change_drops_them(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    with _client(sb) as client:
        assert client.get("/").status_code == 200
        assert client.get("/report/body").status_code == 200
        assert client.get("/bucket/skill/s/later").status_code == 200
        # Home, Health and the bucket page asked for report and status once between them
        assert reads.calls["report"] == 1 and reads.calls["status"] == 1
        # a finished verb or a watcher event: the next page reads afresh
        client.app.state.refresh_hub.force_refresh("front")
        assert client.get("/report/body").status_code == 200
        assert reads.calls["report"] == 2 and reads.calls["status"] == 2
        # a commit made by anything else, with no event at all
        (sb.ledger / "note.txt").write_text("x")
        commit_all(sb.ledger, "outside write")
        assert client.get("/report/body").status_code == 200
        assert reads.calls["report"] == 3 and reads.calls["status"] == 3


def test_a_page_after_a_write_shows_the_new_state(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    with _client(sb) as client:
        reads.report_data = {"buckets": [], "routed_live": [], "series": None,
                             "counters": {"marker": "old-state"}}
        old = client.get("/report/body")
        assert old.status_code == 200
        reads.report_data = {"buckets": [], "routed_live": [], "series": None,
                             "counters": {"marker": "new-state"}}
        # still inside the expiry and nothing changed: the remembered read is served
        assert client.get("/report/body").text == old.text
        # the runner's refresh callback fires after every verb
        client.app.state.refresh_hub.force_refresh("record:lrn-x")
        fresh = client.get("/report/body")
        assert fresh.text != old.text
        assert "new-state" in fresh.text and "old-state" not in fresh.text


def test_a_browser_reload_forgets_the_remembered_reads(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    with _client(sb) as client:
        client.get("/report/body")
        client.get("/report/body")
        assert reads.calls["report"] == 1
        assert client.get("/report", headers={"Cache-Control": "max-age=0"}).status_code == 200
        client.get("/report/body")
        assert reads.calls["report"] == 2


def test_a_failed_page_read_is_shown_and_not_kept(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    with _client(sb) as client:
        reads.fail.add("report")
        broken = client.get("/report/body")
        assert broken.status_code == 200
        assert "the report read failed" in broken.text and 'role="alert"' in broken.text
        reads.fail.clear()
        healed = client.get("/report/body")
        assert "the report read failed" not in healed.text and 'class="health-tile' in healed.text
        assert reads.calls["report"] == 2  # the failure was not remembered


def test_the_bucket_section_that_loads_late_shows_its_error_state(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    with _client(sb) as client:
        reads.fail.add("report")
        late = client.get("/bucket/skill/s/later")
        assert late.status_code == 200
        assert "Routed here (unavailable)" in late.text
        assert "the report read failed" in late.text
        # a body for a place that is not there is an error status, not a blank
        assert client.get("/bucket/skill/nope/later").status_code == 404


def test_shells_answer_without_waiting_for_the_slow_reads(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    with _client(sb) as client:
        health = client.get("/report")
        assert health.status_code == 200
        assert 'hx-get="/report/body"' in health.text and "Counting the ledger" in health.text
        assert 'data-lazy-section' in health.text and 'data-background-read' in health.text
        bucket = client.get("/bucket/skill/s")
        assert bucket.status_code == 200
        assert 'hx-get="/bucket/skill/s/later' in bucket.text and "Reading what was routed" in bucket.text
        assert "report" not in reads.calls and "status" not in reads.calls
        # the query carries over to the body request
        assert 'hx-get="/report/body?q=pkill"' in client.get("/report?q=pkill").text


def test_a_page_runs_its_reads_at_the_same_time(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    barrier = threading.Barrier(4, timeout=5)
    reads.gate = lambda name: barrier.wait() if name in ("list", "status", "report", "mine") else None
    with _client(sb) as client:
        started = time.monotonic()
        # four reads that can only all finish if all four are running at once
        response = client.get("/")
        assert response.status_code == 200, response.text[:300]
    assert time.monotonic() - started < 4.5


def test_concurrent_page_requests_start_one_read(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    release = threading.Event()
    reads.gate = lambda name: release.wait(5) if name == "report" else None
    with _client(sb) as client:
        statuses = []
        threads = [threading.Thread(target=lambda: statuses.append(client.get("/report/body").status_code))
                   for _ in range(2)]
        threads[0].start()
        deadline = time.monotonic() + 5
        while reads.calls.get("report", 0) < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        threads[1].start()
        time.sleep(0.4)
        release.set()
        for t in threads:
            t.join(10)
    assert statuses == [200, 200]
    assert reads.calls["report"] == 1


def test_health_filter_reuses_the_page_reads_but_not_across_a_change(tmp_path, reads):
    sb = _bucket_env(tmp_path)
    hx = {"HX-Request": "true"}
    with _client(sb) as client:
        client.get("/report/body")
        client.get("/report", params={"q": "x"}, headers=hx)
        client.get("/report", params={"all": "1"}, headers=hx)
        assert reads.calls["report"] == 1
        client.app.state.refresh_hub.force_refresh("front")
        client.get("/report", params={"q": "y"}, headers=hx)
        assert reads.calls["report"] == 2
