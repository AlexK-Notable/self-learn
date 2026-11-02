"""Batch-one read savings, checked against real CLI reads and rendered headers."""
from datetime import datetime, timezone

import pytest

from self_learn_ui import ledger, models, routes
from test_humane_home import _client
from support import make_behavior, make_env, seed_record


@pytest.mark.parametrize("pending", [False, True])
def test_fast_header_matches_full_status_on_same_ledger(tmp_path, pending):
    sb = make_env(tmp_path, skills=("s",))
    if pending:
        seed_record(sb.ledger, make_behavior(scope="skill:s"))
    full = ledger.status(sb.ledger, env=sb.env)
    fast = ledger.status_fast(sb.ledger, env=sb.env)
    mine = ledger.mine_status(sb.ledger, env=sb.env)
    assert full.ok and fast.ok and mine.ok
    assert fast.data["home_state"] == "ok"
    now = datetime.now(timezone.utc)
    old = models.build_jobs_line(full, mine, now=now)
    new = models.build_jobs_line(fast, mine, now=now)
    assert old.text
    assert new == old


@pytest.mark.parametrize("state", ["uninitialized", "missing", "not-a-repo"])
def test_fast_header_preserves_real_home_result(tmp_path, state):
    import subprocess

    sb = make_env(tmp_path / "sandbox")
    home = tmp_path / "empty-home"
    if state != "missing":
        home.mkdir()
    if state == "uninitialized":
        subprocess.run(["git", "init", "-q", str(home)], check=True, env=sb.env)
    full = ledger.status(home, env=sb.env)
    fast = ledger.status_fast(home, env=sb.env)
    mine = models.CliRead(data={"runs": []})
    old = models.build_jobs_line(full, mine)
    new = models.build_jobs_line(fast, mine)
    assert old.text
    assert new == old
    if state == "uninitialized":
        assert full.ok and fast.ok
        assert fast.data["home_state"] == state
        assert new.text == "The overnight read has not run yet"
    else:
        assert not full.ok and not fast.ok
        assert "Job status could not be read" in new.text


@pytest.mark.parametrize("valid_pending", [False, True])
def test_fast_header_rejects_invalid_body_like_full_status(tmp_path, valid_pending):
    from ruamel.yaml import YAML
    from self_learn.records import Record, RecordError

    sb = make_env(tmp_path, skills=("s",))
    path = seed_record(sb.ledger, make_behavior(scope="skill:s", record_id="lrn-aa000001"))
    text = path.read_text().replace("## Trigger", "## Wrong section")
    path.write_text(text)
    # Positive control: this is valid pending frontmatter, but not a valid record.
    assert YAML(typ="safe").load(text.split("---")[1])["status"] == "pending"
    with pytest.raises(RecordError):
        Record.from_path(path)
    if valid_pending:
        seed_record(sb.ledger, make_behavior(scope="skill:s", record_id="lrn-aa000002"))
    full = ledger.status(sb.ledger, env=sb.env)
    fast = ledger.status_fast(sb.ledger, env=sb.env)
    mine = ledger.mine_status(sb.ledger, env=sb.env)
    assert full.ok and fast.ok and mine.ok
    now = datetime.now(timezone.utc)
    old = models.build_jobs_line(full, mine, now=now)
    assert old.text
    assert models.build_jobs_line(fast, mine, now=now) == old
    assert full.data["total_pending"] == fast.data["total_pending"] == int(valid_pending)
    assert full.data["total_unreadable"] == fast.data["total_unreadable"] == 1
    for key in ("pending", "unanalyzed", "unreadable", "oldest_days"):
        full_bucket = next(b for b in full.data["buckets"] if b["bucket"] == "s")
        fast_bucket = next(b for b in fast.data["buckets"] if b["bucket"] == "s")
        assert full_bucket[key] == fast_bucket[key]


def test_header_uses_fast_status_and_expires_on_refresh_and_ttl(tmp_path, monkeypatch):
    sb = make_env(tmp_path)
    calls = []
    def invoke(args, **kw):
        calls.append(args)
        return models.CliRead(data={"home_state": "ok", "runs": []})
    monkeypatch.setattr(ledger, "_invoke_json", invoke)
    with _client(sb) as client:
        first = client.get("/header/jobs")
        assert first.status_code == 200 and "jobs-line" in first.text
        assert calls == [["status", "--json", "--fast"], ["mine", "status", "--json"]]
        assert client.get("/header/jobs").text == first.text
        assert len(calls) == 2
        client.app.state.refresh_hub.force_refresh("front")
        client.get("/header/jobs")
        assert len(calls) == 4
        cache = client.app.state.humane_jobs_line
        stamp, line = cache["line"]
        cache["line"] = (stamp - 31, line)
        client.get("/header/jobs")
        assert len(calls) == 6


@pytest.mark.parametrize("path", ["/report", "/bucket/skill/s"])
def test_page_passes_status_to_background_header(tmp_path, monkeypatch, path):
    sb = make_env(tmp_path, skills=("s",))
    seed_record(sb.ledger, make_behavior(scope="skill:s"))
    calls = []
    original = ledger._invoke_json
    def invoke(args, **kw):
        calls.append(args)
        return original(args, **kw)
    monkeypatch.setattr(ledger, "_invoke_json", invoke)
    with _client(sb) as client:
        response = client.get(path)
        assert response.status_code == 200 and 'class="site-header"' in response.text
        assert 'data-background-read hx-get="/header/jobs"' in response.text
        full_calls = [c for c in calls if c[0] == "status"]
        assert full_calls == [["status", "--json"]]
        header = client.get("/header/jobs")
        assert "jobs-line" in header.text
        assert [c for c in calls if c[0] == "status"] == full_calls


def test_inbox_reads_attention_once_and_seeds_count(tmp_path, monkeypatch):
    from test_inbox import OO7, OO7_PACKET, _doc
    sb = make_env(tmp_path)
    calls = []
    def attention(home):
        calls.append(home)
        return models.CliRead(data=_doc(OO7))
    monkeypatch.setattr(ledger, "attention", attention)
    monkeypatch.setattr(ledger, "attention_packet", lambda *a: ledger.PacketRead(data=OO7_PACKET))
    with _client(sb) as client:
        page = client.get("/inbox")
        assert page.status_code == 200 and OO7["title"] in page.text
        assert len(calls) == 1
        count = client.get("/inbox/count")
        assert count.status_code == 200 and "Inbox (1)" in count.text
        assert len(calls) == 1
        client.app.state.refresh_hub.force_refresh("front")
        client.get("/inbox/count")
        assert len(calls) == 2
        cache = client.app.state.humane_jobs_line
        stamp, link = cache["inbox"]
        cache["inbox"] = (stamp - 31, link)
        client.get("/inbox/count")
        assert len(calls) == 3


def test_detail_one_list_read_retains_queue_but_probes_only_current(tmp_path, monkeypatch):
    sb = make_env(tmp_path, skills=("s",))
    current = make_behavior(scope="skill:s", record_id="lrn-aa000001")
    later = make_behavior(scope="skill:s", record_id="lrn-aa000002")
    for record in (current, later):
        seed_record(sb.ledger, record)
    calls = []
    original = ledger.list_items
    def read(home, **kw):
        result = original(home, env=sb.env, **kw)
        calls.append(result)
        return result
    monkeypatch.setattr(ledger, "list_items", read)
    warmed = []
    monkeypatch.setattr(routes, "_warm_detail_prefetch", lambda cache, hub, home, rid: warmed.append(rid))
    with _client(sb) as client:
        response = client.get(f"/record/{current.id}")
        assert response.status_code == 200 and current.id in response.text
    assert warmed == [later.id]
    assert len(calls) == 1
    rows = {i["id"]: i for i in calls[0].data}
    assert "surface_fill" in rows[current.id]
    assert "surface_fill" not in rows[later.id]


def test_prefetch_from_superset_skips_deferred_and_other_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "_belongs_to_bucket", lambda h, rid, s, b: rid != "other")
    rows = models.CliRead(data=[
        {"id": "current", "bucket": "same", "status": "pending"},
        {"id": "deferred", "bucket": "same", "status": "pending", "deferred_until": "2099-01-01T00:00:00Z"},
        {"id": "routed", "bucket": "same", "status": "routed"},
        {"id": "other", "bucket": "same", "status": "pending"},
        {"id": "next", "bucket": "same", "status": "pending"},
    ])
    assert routes._next_pending_id(tmp_path, "skill", "same", "current", list_read=rows) == "next"


def test_health_search_cache_cannot_extend_header_status_lifetime(tmp_path, monkeypatch):
    sb = make_env(tmp_path)
    monkeypatch.setattr(ledger, "report", lambda home: models.CliRead(data={}))
    monkeypatch.setattr(ledger, "status", lambda home: models.CliRead(data={"steward_hold": "old hold"}))
    monkeypatch.setattr(ledger, "status_fast", lambda home: models.CliRead(data={"steward_hold": "new hold"}))
    monkeypatch.setattr(ledger, "mine_status", lambda home: models.CliRead(data={"runs": []}))
    with _client(sb) as client:
        assert client.get("/report").status_code == 200
        assert "on hold" in client.get("/header/jobs").text
        cache = client.app.state.humane_jobs_line
        stamp, line = cache["line"]
        cache["line"] = (stamp - 31, line)
        # A cached Health search must not re-seed its older status snapshot.
        assert client.get("/report?q=rule", headers={"HX-Request": "true"}).status_code == 200
        # Both holds word the header identically, so observe which read the
        # header actually requests as well as the rendered positive control.
        reads = []
        def fast(home):
            reads.append(home)
            return models.CliRead(data={"steward_stale": True})
        monkeypatch.setattr(ledger, "status_fast", fast)
        header = client.get("/header/jobs")
        assert "The nightly review is behind" in header.text
        assert reads == [sb.ledger]


@pytest.mark.parametrize("path", ["/", "/report", "/bucket/skill/s"])
def test_page_drops_header_seed_if_refresh_arrives_during_read(tmp_path, monkeypatch, path):
    sb = make_env(tmp_path, skills=("s",))
    # An empty bucket redirects to Home, which would test Home twice.
    seed_record(sb.ledger, make_behavior(scope="skill:s"))
    monkeypatch.setattr(ledger, "report", lambda home: models.CliRead(data={}))
    monkeypatch.setattr(ledger, "mine_status", lambda home: models.CliRead(data={"runs": []}))
    calls = []
    def fast(home):
        calls.append(home)
        return models.CliRead(data={"steward_stale": True})
    monkeypatch.setattr(ledger, "status_fast", fast)
    with _client(sb) as client:
        def old_status(home):
            client.app.state.refresh_hub.force_refresh("front")
            return models.CliRead(data={"steward_hold": "old hold"})
        monkeypatch.setattr(ledger, "status", old_status)
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200 and 'class="site-header"' in response.text
        header = client.get("/header/jobs")
        assert "jobs-line" in header.text
        assert "The nightly review is behind" in header.text
        assert "on hold" not in header.text
        assert calls == [sb.ledger]


@pytest.mark.parametrize("failed", [models.CliRead(data=None, error="unavailable"),
                                   models.CliRead(data={"error": "unavailable"}),
                                   models.CliRead(data=None)])
def test_inbox_count_retries_failure_then_caches_success(tmp_path, monkeypatch, failed):
    sb = make_env(tmp_path)
    reads = []
    def attention(home):
        reads.append(home)
        return failed if len(reads) == 1 else models.CliRead(data={"counts": {"needs_you": 2}})
    monkeypatch.setattr(ledger, "attention", attention)
    with _client(sb) as client:
        first = client.get("/inbox/count")
        assert first.status_code == 200 and "Inbox (?)" in first.text
        second = client.get("/inbox/count")
        assert second.status_code == 200 and "Inbox (2)" in second.text
        assert "Inbox (2)" in client.get("/inbox/count").text
        assert reads == [sb.ledger, sb.ledger]
