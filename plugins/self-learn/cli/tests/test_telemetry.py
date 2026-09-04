"""Telemetry spool + flush (11 §4 v2): cache-only appends, verb-triggered
flush into the tracked plane, scan-at-flush refusal, closed enums.

The spool is XDG-redirected per test; the tracked plane lives in a sandbox
ledger home. No real ~/.cache, no real ledger.
"""

import contextlib
import json
from datetime import datetime, timezone

import pytest

from self_learn import gitops, telemetry
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
    # make_env pre-creates <home>/telemetry/ — the pin is that spooling
    # writes NOTHING into the tracked plane, so it must stay empty.
    assert list(telemetry.telemetry_dir(home).iterdir()) == []


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
    assert list(telemetry.telemetry_dir(home).iterdir()) == []


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
    assert list(telemetry.telemetry_dir(home).iterdir()) == []
    assert len(spool.read_text().splitlines()) == 2


def test_flush_summary_names_files(home):
    telemetry.spool_event("offer-made", now=NOW)
    report = telemetry.flush(home)
    assert "1 event" in report.summary()
    assert "2026-07.testhost.jsonl" in report.summary()


# --------------------------------------------------- M-M: lock-start gate


def test_flush_locks_before_tracked_append_and_scan_runs_first(home, monkeypatch):
    """M-M (P7 lock-start gate): the tracked-plane append must run only
    while `commit_lock` is held, and the secret scan must still run
    BEFORE any lock is taken (phase 1 stays unlocked; only phase 2's
    append moved inside the lock). Observed the way the brief asks:
    wrap the REAL `commit_lock` to snapshot the tracked file's content at
    enter/exit, and the REAL `secret_scan` to record when it ran, rather
    than asserting on internals `flush` doesn't expose."""
    telemetry.spool_event("offer-made", now=NOW)
    tracked = telemetry.telemetry_dir(home) / "2026-07.testhost.jsonl"

    events: list[tuple[str, str | None]] = []
    real_lock = gitops.commit_lock
    real_scan = telemetry.secret_scan

    @contextlib.contextmanager
    def probe_lock(repo, **kwargs):
        with real_lock(repo, **kwargs):
            events.append(("enter", tracked.read_text() if tracked.exists() else None))
            yield
            events.append(("exit", tracked.read_text() if tracked.exists() else None))

    def probe_scan(line):
        events.append(("scan", None))
        return real_scan(line)

    monkeypatch.setattr(gitops, "commit_lock", probe_lock)
    monkeypatch.setattr(telemetry, "secret_scan", probe_scan)

    report = telemetry.flush(home, push=False)
    assert report.events == 1

    kinds = [k for k, _ in events]
    first_enter = kinds.index("enter")
    # positive control: the scan really ran, and only BEFORE the first lock
    assert kinds[:first_enter] == ["scan"], (
        f"scan did not run before the first commit_lock: {kinds}"
    )
    # the tracked append happened INSIDE that first lock hold: nothing
    # written yet at enter, the event line written by exit
    assert events[first_enter][1] is None
    exit_idx = first_enter + 1
    assert kinds[exit_idx] == "exit"
    assert events[exit_idx][1] and "offer-made" in events[exit_idx][1]


def test_flush_defers_loud_but_not_fatal_when_commit_lock_is_busy(
    home, monkeypatch, capsys
):
    """M-M's new lock acquisition must keep flush's documented contract
    ('Git trouble is loud but never fatal'): none of `flush`'s four
    callers (cli.py's `_cmd_telemetry` and `_flush_spool_best_effort`,
    miner.py, worker.py) catch a bare `gitops.GitOpsError`, so a busy
    commit_lock here must never propagate past `flush` — it must defer,
    leaving the spool intact for the next attempt, exactly like a git
    failure inside `_commit_flush` already does."""
    telemetry.spool_event("offer-made", now=NOW)
    spool = telemetry.spool_dir() / "2026-07.testhost.jsonl"
    before = spool.read_text()

    def wedged(repo, **kwargs):
        raise gitops.GitOpsError("commit lock <path> still held after 0.3s")

    monkeypatch.setattr(gitops, "commit_lock", wedged)

    report = telemetry.flush(home, push=False)  # must not raise

    assert report.events == 0
    assert list(telemetry.telemetry_dir(home).iterdir()) == []
    assert spool.read_text() == before  # nothing moved, nothing truncated
    assert "deferred" in capsys.readouterr().err


# ------------------------------------------------------------- read_events


def test_read_events_ts_ordered_and_lenient(home):
    tdir = telemetry.telemetry_dir(home)
    tdir.mkdir(parents=True, exist_ok=True)  # make_env pre-creates it
    (tdir / "2026-07.other.jsonl").write_text(
        '{"ts":"2026-07-15T13:00:00Z","kind":"capture"}\n'
        "not json at all\n"
        '{"ts":"2026-07-15T11:00:00Z","kind":"offer-made"}\n'
    )
    events = telemetry.read_events(home)
    assert [e["kind"] for e in events] == ["offer-made", "capture"]


def test_read_events_missing_dir(home):
    assert telemetry.read_events(home) == []


# ---------------------------------------------- FW-53: decode safety
#
# `read_events` and `flush` sit on the miner's `_reconcile_and_land` path
# (`_event_seen` calls `read_events` first thing; `flush` runs at the end
# of every productive run). A single byte that is not valid UTF-8 —
# anywhere in a tracked or spooled file — must never take down every
# OTHER event in that file, and must never escape as an uncaught
# `UnicodeDecodeError` (the miner's outer handler turns that into
# `status: failed` for the whole run).


def test_read_events_skips_undecodable_line_keeps_good_lines_same_file(home):
    tdir = telemetry.telemetry_dir(home)
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / "2026-07.other.jsonl"
    path.write_bytes(
        b'{"ts":"2026-07-15T11:00:00Z","kind":"offer-made"}\n'
        b"\xff\xfe not decodable\n"
        b'{"ts":"2026-07-15T13:00:00Z","kind":"capture"}\n'
    )
    events = telemetry.read_events(home)
    assert [e["kind"] for e in events] == ["offer-made", "capture"]


def test_flush_skips_undecodable_spool_line_keeps_good_lines(home):
    telemetry.spool_event("offer-made", now=NOW)
    spool = telemetry.spool_dir() / "2026-07.testhost.jsonl"
    with open(spool, "ab") as fh:
        fh.write(b"\xff\xfe not decodable\n")
    telemetry.spool_event("capture", now=NOW, source="teach")

    report = telemetry.flush(home)  # must not raise UnicodeDecodeError

    assert report.events == 2
    tracked = telemetry.telemetry_dir(home) / "2026-07.testhost.jsonl"
    kinds = [json.loads(ln)["kind"] for ln in tracked.read_text().splitlines()]
    assert kinds == ["offer-made", "capture"]
