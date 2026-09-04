"""Telemetry spool + flush (11 §4 v2): cache-only appends, verb-triggered
flush into the tracked plane, scan-at-flush refusal, closed enums.

The spool is XDG-redirected per test; the tracked plane lives in a sandbox
ledger home. No real ~/.cache, no real ledger.
"""

import contextlib
import fcntl
import json
from datetime import datetime, timezone

import pytest

from self_learn import cli, gitops, telemetry
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
    # M-M fold r1 MINOR m-1: append and its commit are now ONE continuous
    # hold, not two separate acquisitions — so there is exactly ONE
    # enter/exit pair for the whole flush, not one around the append and
    # a second inside the (pre-fold) `_commit_flush`.
    assert kinds.count("enter") == 1, (
        f"commit_lock entered {kinds.count('enter')} times in one flush "
        f"— append and its commit must share ONE hold: {kinds}"
    )
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


def test_flush_holds_commit_lock_once_across_append_and_commit(home, monkeypatch):
    """M-M fold r1 MINOR m-1, isolated: counts how many times the REAL
    `commit_lock` is entered during one `flush()` call. The pre-fold
    shape opened it TWICE — once around the tracked append in `flush`,
    once again inside `_commit_flush`'s own stage+commit — leaving a gap
    a second writer could slip into between "appended" and "committed".
    After the fold there must be exactly one entry: one continuous hold
    spanning append through commit, push still outside it."""
    telemetry.spool_event("offer-made", now=NOW)
    real_lock = gitops.commit_lock
    entries: list[int] = []

    @contextlib.contextmanager
    def counting_lock(repo, **kwargs):
        entries.append(1)
        with real_lock(repo, **kwargs):
            yield

    monkeypatch.setattr(gitops, "commit_lock", counting_lock)
    report = telemetry.flush(home, push=False)

    assert report.events == 1
    assert len(entries) == 1, (
        f"commit_lock was entered {len(entries)} time(s) in one flush — "
        "expected exactly 1 (append and commit sharing one hold)"
    )


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
    err = capsys.readouterr().err
    assert "deferred" in err
    # Fold r1 MAJOR M-1: the deferral is on the REPORT OBJECT, not just
    # stderr — every reader of `FlushReport` (not only one printing it)
    # must be able to tell "deferred" from "spool empty". The reason
    # comes straight from the exception text (fold r1 NIT n-1: never
    # hardcoded — a `GitOpsError` here is not always "lock busy").
    assert report.deferred_reason == "commit lock <path> still held after 0.3s"
    assert report.deferred_events == 1
    assert "commit lock <path> still held after 0.3s" in err
    assert "1 event" in report.summary()
    assert "remain spooled" in report.summary()


def test_flush_drains_the_spool_on_the_next_attempt_after_a_deferral(
    home, monkeypatch
):
    """Fold r1 MAJOR M-1's other half: a deferred flush must not lose the
    event — the NEXT flush (once the lock is free again) drains it like
    nothing happened."""
    telemetry.spool_event("offer-made", now=NOW)
    real_lock = gitops.commit_lock  # NOT monkeypatch.undo(): the autouse
    # `redirect` fixture shares this SAME monkeypatch instance (fixture
    # caching, one per test) for its own XDG_CACHE_HOME/SELF_LEARN_ACTOR
    # setenv calls — `.undo()` would revert THOSE too, silently pointing
    # `spool_dir()` at a different (real) cache dir and making this test
    # pass for the wrong reason (measured: `.undo()` here made the
    # "drained" flush read an empty spool — a DIFFERENT directory, not a
    # genuinely-drained one). Re-setattr only the one thing patched.

    def wedged(repo, **kwargs):
        raise gitops.GitOpsError("commit lock <path> still held after 0.3s")

    monkeypatch.setattr(gitops, "commit_lock", wedged)
    deferred = telemetry.flush(home, push=False)
    assert deferred.deferred_reason is not None
    assert deferred.events == 0

    monkeypatch.setattr(gitops, "commit_lock", real_lock)
    drained = telemetry.flush(home, push=False)

    assert drained.deferred_reason is None
    assert drained.events == 1
    tracked = telemetry.telemetry_dir(home) / "2026-07.testhost.jsonl"
    assert "offer-made" in tracked.read_text()
    assert (telemetry.spool_dir() / "2026-07.testhost.jsonl").read_text() == ""


def test_flush_reports_not_deferred_when_spool_is_empty_even_if_lock_is_busy(
    home, monkeypatch, capsys
):
    """M-M fold r2 MINOR m-1: an empty spool meeting a busy commit_lock
    is NOT a deferral -- there is nothing pending for a busy lock to
    defer. Before this fix, `flush()` still tried to acquire the lock
    for an empty spool (it had nothing to protect there) and, on a busy
    lock, reported `deferred_reason` set with `deferred_events == 0` --
    flipping `counts_are_lower_bound` True for a run where nothing was
    actually held back."""
    # A spool file that EXISTS but carries no events (as opposed to no
    # spool directory at all, which `flush()` already short-circuits on
    # before ever reaching the lock -- that pre-existing early return
    # would make this test vacuous if it were the only spool state
    # exercised).
    telemetry.spool_dir().mkdir(parents=True, exist_ok=True)
    (telemetry.spool_dir() / "2026-07.testhost.jsonl").write_text("")

    calls: list[int] = []

    def wedged(repo, **kwargs):
        calls.append(1)
        raise gitops.GitOpsError("commit lock <path> still held after 0.3s")

    monkeypatch.setattr(gitops, "commit_lock", wedged)

    report = telemetry.flush(home, push=False)

    assert report.events == 0
    assert report.deferred_reason is None
    assert report.deferred_events == 0
    # The lock must never even be attempted for an empty spool -- not
    # just "attempted and correctly not reported as a deferral".
    assert calls == []
    assert "deferred" not in capsys.readouterr().err


def test_flush_appended_but_commit_failed_is_not_deferred(home, monkeypatch):
    """M-M fold r2 MINOR m-2: the discriminator's OTHER branch -- append
    succeeded, only `_commit_flush`'s stage+commit failed -- was
    unwitnessed after fold r1 (collapsing it reddened nothing). This
    must read as NOT deferred: the event already landed in the tracked
    plane, `read_events` sees it, the spool is drained, and the caller
    that consumes the outcome (`cli._flush_spool_best_effort`) must
    report "ok" -- not "deferred" -- for exactly this case (gate's
    prescribed shape, r2)."""

    def failing_commit(*args, **kwargs):
        raise gitops.GitOpsError("simulated commit failure")

    monkeypatch.setattr(gitops, "commit", failing_commit)

    telemetry.spool_event("offer-made", now=NOW)
    report = telemetry.flush(home, push=False)

    assert report.events == 1
    assert report.deferred_reason is None
    events = telemetry.read_events(home)
    assert len(events) == 1
    assert events[0]["kind"] == "offer-made"
    assert (telemetry.spool_dir() / "2026-07.testhost.jsonl").read_text() == ""

    # The consumer-facing path (`cli._flush_spool_best_effort`), still
    # under the same commit-failure condition, on a FRESH event -- not
    # the one already drained above, which would take the empty-spool
    # early-return path (m-1, above) and prove nothing about THIS
    # branch.
    telemetry.spool_event("offer-made", now=NOW)
    state = cli._flush_spool_best_effort(home, no_push=True)
    assert state == "ok"


def test_flush_releases_each_spool_flock_before_the_git_commit(home, monkeypatch):
    """M-M fold r3 MINOR m-1: fold r2's spool-flock narrowing (release +
    close each spool file's flock right after ITS OWN truncate, before
    `_commit_flush`'s stage+commit runs) had no witness -- reverting to
    fold r1's wider hold (flock held through the git commit too) leaves
    every visible consequence identical (same report, same tracked
    file, same drained spool), because nothing else in this suite reads
    the flock's STATE, only its eventual effects. Only WHEN a
    concurrent producer is unblocked differs -- exactly the regression
    that happened once already in this lane (fold r1 widened the hold
    as an unintended side effect of the single-hold restructure).

    `flock` is per open-file-description, so a SEPARATE, independent
    open of the same spool file can probe -- non-blockingly, no timing,
    no second process -- whether flush()'s own open still holds an
    exclusive lock on it at the moment `gitops.commit` runs (i.e.
    still inside `commit_lock`, mid stage+commit)."""
    telemetry.spool_event("offer-made", now=NOW)
    spool = telemetry.spool_dir() / "2026-07.testhost.jsonl"
    held: list[int] = []
    probed: list[int] = []
    real_commit = gitops.commit

    def probing_commit(h, msg, paths=None):
        probed.append(1)
        fh = open(spool, "r+b")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except BlockingIOError:
            held.append(1)
        finally:
            fh.close()
        return real_commit(h, msg, paths=paths)

    monkeypatch.setattr(gitops, "commit", probing_commit)
    assert telemetry.flush(home, push=False).events == 1
    # probed guards the probe itself: if flush() is ever refactored to call
    # the commit function by a different name/path, the monkeypatch stops
    # landing and probing_commit silently never runs -- without this check
    # `held == []` would then pass VACUOUSLY (no probe, so nothing recorded),
    # not because the property holds.
    assert probed == [1], "probing_commit never ran -- the monkeypatch didn't land on the name flush() calls"
    assert held == [], "the spool flock was still held during the git commit"


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
