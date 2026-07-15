"""Telemetry spool + flush (11 §4 v2): cache-only appends, verb-triggered
flush into the tracked plane, scan-at-flush refusal, closed enums.

The spool is XDG-redirected per test; the tracked plane lives in a sandbox
ledger home. No real ~/.cache, no real ledger.
"""

import json
from datetime import datetime, timezone

import pytest

from self_learn import telemetry
from support import make_home


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture()
def home(tmp_path):
    return make_home(tmp_path)


NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ spool


def test_spool_event_writes_single_json_line(tmp_path):
    path = telemetry.spool_event("offer-made", now=NOW)
    assert path == telemetry.spool_dir() / "2026-07.testhost.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["kind"] == "offer-made"
    assert event["actor"] == "testhost"
    assert event["schema_version"] == telemetry.SCHEMA_VERSION
    assert event["ts"] == "2026-07-15T12:00:00Z"


def test_spool_appends_not_overwrites(tmp_path):
    telemetry.spool_event("offer-made", now=NOW)
    telemetry.spool_event("capture", now=NOW, source="teach", record="lrn-0000aaaa")
    lines = (telemetry.spool_dir() / "2026-07.testhost.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["record"] == "lrn-0000aaaa"


def test_spool_is_cache_only_never_touches_home(home):
    telemetry.spool_event("offer-made", now=NOW)
    assert not (home / ".self-learn" / "telemetry").exists()


def test_unknown_kind_refused():
    with pytest.raises(telemetry.TelemetryError, match="unknown event kind"):
        telemetry.spool_event("made-up-kind")


def test_decline_reason_enum_enforced():
    telemetry.spool_event("offer-declined", now=NOW, reason="not-durable")
    with pytest.raises(telemetry.TelemetryError, match="closed enum"):
        telemetry.spool_event("offer-declined", reason="felt like it")


def test_reason_only_valid_on_offer_declined():
    with pytest.raises(telemetry.TelemetryError, match="offer-declined only"):
        telemetry.spool_event("offer-made", reason="later")


def test_non_scalar_payload_refused():
    with pytest.raises(telemetry.TelemetryError, match="scalar"):
        telemetry.spool_event("capture", extras={"nested": "map"})


def test_none_payload_values_dropped(tmp_path):
    path = telemetry.spool_event("offer-declined", now=NOW, reason=None)
    event = json.loads(path.read_text().splitlines()[0])
    assert "reason" not in event


# ------------------------------------------------------------------ flush


def test_flush_moves_events_to_tracked_plane(home):
    telemetry.spool_event("offer-made", now=NOW)
    telemetry.spool_event("offer-declined", now=NOW, reason="later")
    report = telemetry.flush(home)
    assert report.events == 2
    tracked = telemetry.telemetry_dir(home) / "2026-07.testhost.jsonl"
    assert report.files == [tracked]
    assert len(tracked.read_text().splitlines()) == 2
    # spool file survives (inode-stable truncate) but is empty
    spool = telemetry.spool_dir() / "2026-07.testhost.jsonl"
    assert spool.exists()
    assert spool.read_text() == ""


def test_flush_appends_across_runs(home):
    telemetry.spool_event("offer-made", now=NOW)
    telemetry.flush(home)
    telemetry.spool_event("capture", now=NOW, source="teach")
    telemetry.flush(home)
    tracked = telemetry.telemetry_dir(home) / "2026-07.testhost.jsonl"
    assert len(tracked.read_text().splitlines()) == 2


def test_flush_empty_spool_is_noop(home):
    report = telemetry.flush(home)
    assert report.events == 0
    assert "spool empty" in report.summary()
    assert not (home / ".self-learn" / "telemetry").exists()


def test_flush_scan_hit_refuses_and_keeps_spool(home):
    telemetry.spool_event("offer-made", now=NOW)
    # An injected line carrying a credential shape — the exact class the
    # scan-at-flush exists to stop (schema can't block a hand-written line).
    spool = telemetry.spool_dir() / "2026-07.testhost.jsonl"
    with open(spool, "a", encoding="utf-8") as fh:
        fh.write('{"kind":"capture","note":"password = hunter2secret"}\n')
    with pytest.raises(telemetry.ScanRefusal, match="spool intact"):
        telemetry.flush(home)
    # nothing moved, spool intact
    assert not (home / ".self-learn" / "telemetry").exists()
    assert len(spool.read_text().splitlines()) == 2


def test_flush_summary_names_files(home):
    telemetry.spool_event("offer-made", now=NOW)
    report = telemetry.flush(home)
    assert "1 event" in report.summary()
    assert "2026-07.testhost.jsonl" in report.summary()


# ------------------------------------------------------------- read_events


def test_read_events_ts_ordered_and_lenient(home):
    tdir = telemetry.telemetry_dir(home)
    tdir.mkdir(parents=True)
    (tdir / "2026-07.other.jsonl").write_text(
        '{"ts":"2026-07-15T13:00:00Z","kind":"capture"}\n'
        "not json at all\n"
        '{"ts":"2026-07-15T11:00:00Z","kind":"offer-made"}\n'
    )
    events = telemetry.read_events(home)
    assert [e["kind"] for e in events] == ["offer-made", "capture"]


def test_read_events_missing_dir(home):
    assert telemetry.read_events(home) == []
