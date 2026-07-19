"""Pure model tests: build_front_model. Every assertion is field-by-field
against constructed CliRead inputs — no filesystem, no subprocess."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from self_learn_ui.models import CliRead, build_front_model

NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)


def _status(buckets=None, **overrides):
    data = {
        "buckets": buckets or [],
        "total_pending": sum(b["pending"] for b in (buckets or [])),
        "open_followups": 0,
        "worker_last_run": None,
        "supply_mix": {},
        "metrics": {},
    }
    data.update(overrides)
    return CliRead(data=data)


def _report(**overrides):
    data = {
        "generated": "2026-07-17",
        "buckets": [],
        "destinations": {},
        "routed_live": [],
        "routed_ever": 0,
        "open_followups": [],
        "recurrence_suspects": [],
        "deferred": [],
        "mined": {},
        "telemetry": {},
    }
    data.update(overrides)
    return CliRead(data=data)


def _mine(**overrides):
    data = {"last_run": None, "stale": False, "runs": []}
    data.update(overrides)
    return CliRead(data=data)


EMPTY_LIST = CliRead(data=[])


class TestCliFailurePropagation:
    def test_all_ok_front_model_is_ok(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert model.ok is True
        assert model.errors == ()

    def test_a_single_cli_failure_flips_ok_false_and_is_surfaced_verbatim(self):
        failing_status = CliRead(data=None, error="ledger home /x does not exist")
        model = build_front_model(
            EMPTY_LIST, failing_status, _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert model.ok is False
        assert "ledger home /x does not exist" in model.errors
        # a CLI failure never masquerades as an empty-but-fine bucket list
        assert model.buckets == ()

    def test_multiple_failures_all_surface(self):
        f1 = CliRead(data=None, error="list failed")
        f2 = CliRead(data=None, error="report failed")
        model = build_front_model(f1, _status(), f2, _mine(), sentinel_mtime=None, now=NOW)
        assert set(model.errors) == {"list failed", "report failed"}


class TestBucketOrdering:
    def test_buckets_sorted_oldest_first(self):
        buckets = [
            {"bucket": "a", "scope": "skill", "pending": 1, "oldest_days": 3, "unanalyzed": 0},
            {"bucket": "b", "scope": "skill", "pending": 1, "oldest_days": 40, "unanalyzed": 0},
            {"bucket": "c", "scope": "skill", "pending": 1, "oldest_days": 10, "unanalyzed": 0},
        ]
        model = build_front_model(
            EMPTY_LIST, _status(buckets), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert [b.name for b in model.buckets] == ["b", "c", "a"]

    def test_null_oldest_days_sorts_last(self):
        buckets = [
            {"bucket": "empty-ish", "scope": "skill", "pending": 0, "oldest_days": None, "unanalyzed": 0},
            {"bucket": "has-age", "scope": "skill", "pending": 1, "oldest_days": 5, "unanalyzed": 0},
        ]
        model = build_front_model(
            EMPTY_LIST, _status(buckets), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert [b.name for b in model.buckets] == ["has-age", "empty-ish"]

    def test_bucket_row_fields_pass_through(self):
        buckets = [
            {"bucket": "s", "scope": "skill", "pending": 3, "oldest_days": 7, "unanalyzed": 2},
        ]
        model = build_front_model(
            EMPTY_LIST, _status(buckets), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        row = model.buckets[0]
        assert (row.name, row.scope, row.pending, row.oldest_days, row.unanalyzed) == (
            "s", "skill", 3, 7, 2,
        )


class TestDeferredColumn:
    """Feedback round 1 item 8: per-bucket deferred counts, computed from
    the SAME list read Front already makes."""

    def _buckets(self):
        return [
            {"bucket": "a", "scope": "skill", "pending": 2, "oldest_days": 3, "unanalyzed": 0},
            {"bucket": "b", "scope": "skill", "pending": 1, "oldest_days": 1, "unanalyzed": 0},
        ]

    def test_future_deferrals_count_per_bucket(self):
        future = (NOW + timedelta(days=10)).isoformat()
        list_read = CliRead(data=[
            {"id": "lrn-1", "bucket": "a", "deferred_until": future},
            {"id": "lrn-2", "bucket": "a", "deferred_until": future},
            {"id": "lrn-3", "bucket": "b", "deferred_until": None},
        ])
        model = build_front_model(
            list_read, _status(self._buckets()), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        by_name = {b.name: b.deferred for b in model.buckets}
        assert by_name == {"a": 2, "b": 0}

    def test_expired_deferral_does_not_count(self):
        past = (NOW - timedelta(days=1)).isoformat()
        list_read = CliRead(data=[
            {"id": "lrn-1", "bucket": "a", "deferred_until": past},
        ])
        model = build_front_model(
            list_read, _status(self._buckets()), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert {b.name: b.deferred for b in model.buckets} == {"a": 0, "b": 0}

    def test_failed_list_read_yields_zero_counts_not_a_crash(self):
        failing = CliRead(data=None, error="list failed")
        model = build_front_model(
            failing, _status(self._buckets()), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert all(b.deferred == 0 for b in model.buckets)


class TestWorkerStaleness:
    def test_no_unanalyzed_supply_never_alarms_even_if_worker_never_ran(self):
        buckets = [{"bucket": "s", "scope": "skill", "pending": 1, "oldest_days": 1, "unanalyzed": 0}]
        model = build_front_model(
            EMPTY_LIST,
            _status(buckets, worker_last_run=None),
            _report(), _mine(), sentinel_mtime=None, now=NOW,
        )
        assert model.status.worker_stale is False
        assert "nothing unanalyzed" in model.status.worker_stale_label

    def test_unanalyzed_supply_and_worker_never_ran_alarms(self):
        buckets = [{"bucket": "s", "scope": "skill", "pending": 1, "oldest_days": 1, "unanalyzed": 1}]
        model = build_front_model(
            EMPTY_LIST,
            _status(buckets, worker_last_run=None),
            _report(), _mine(), sentinel_mtime=None, now=NOW,
        )
        assert model.status.worker_stale is True
        assert model.status.worker_stale_label == "worker overdue"

    def test_unanalyzed_supply_and_recent_run_is_not_stale(self):
        buckets = [{"bucket": "s", "scope": "skill", "pending": 1, "oldest_days": 1, "unanalyzed": 1}]
        recent = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        model = build_front_model(
            EMPTY_LIST,
            _status(buckets, worker_last_run=recent),
            _report(), _mine(), sentinel_mtime=None, now=NOW,
        )
        assert model.status.worker_stale is False
        assert model.status.worker_stale_label == "worker current"

    def test_unanalyzed_supply_and_run_older_than_threshold_is_stale(self):
        buckets = [{"bucket": "s", "scope": "skill", "pending": 1, "oldest_days": 1, "unanalyzed": 1}]
        # STALE_AFTER_SECS is 3 days (worker.py) — 4 days ago must alarm.
        old = (NOW - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        model = build_front_model(
            EMPTY_LIST,
            _status(buckets, worker_last_run=old),
            _report(), _mine(), sentinel_mtime=None, now=NOW,
        )
        assert model.status.worker_stale is True


class TestSentinel:
    def test_no_sentinel_file_is_not_live(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert model.status.sentinel_live is False
        assert model.status.sentinel_label == "autosync live"

    def test_fresh_sentinel_mtime_is_live(self):
        recent_mtime = (NOW - timedelta(minutes=5)).timestamp()
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(),
            sentinel_mtime=recent_mtime, now=NOW,
        )
        assert model.status.sentinel_live is True
        assert "paused" in model.status.sentinel_label

    def test_stale_sentinel_mtime_older_than_ttl_is_not_live(self):
        old_mtime = (NOW - timedelta(hours=3)).timestamp()  # TTL is 2h
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(),
            sentinel_mtime=old_mtime, now=NOW,
        )
        assert model.status.sentinel_live is False


class TestHoldingRows:
    def test_no_suspects_yields_no_rows(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert model.holding == ()

    def test_suspect_joined_with_routed_live_bucket_and_age(self):
        report = _report(
            recurrence_suspects=[{"id": "lrn-aa000001", "nonce": "n1", "seen_at": "2026-07-15T00:00:00Z"}],
            routed_live=[{"id": "lrn-aa000001", "bucket": "s", "routed_days_ago": 12, "last_confirmed": None, "recurrences": 0}],
        )
        model = build_front_model(
            EMPTY_LIST, _status(), report, _mine(), sentinel_mtime=None, now=NOW
        )
        (row,) = model.holding
        assert row.id == "lrn-aa000001"
        assert row.bucket == "s"
        assert row.routed_days_ago == 12
        assert row.sighted_count == 1
        assert row.text == "Routed 12d ago. Sighted 1 time since."

    def test_multiple_suspects_for_same_record_count_and_newest_nonce_wins(self):
        report = _report(
            recurrence_suspects=[
                {"id": "lrn-aa000001", "nonce": "n1", "seen_at": "2026-07-10T00:00:00Z"},
                {"id": "lrn-aa000001", "nonce": "n2", "seen_at": "2026-07-15T00:00:00Z"},
            ],
            routed_live=[{"id": "lrn-aa000001", "bucket": "s", "routed_days_ago": 20, "last_confirmed": None, "recurrences": 0}],
        )
        model = build_front_model(
            EMPTY_LIST, _status(), report, _mine(), sentinel_mtime=None, now=NOW
        )
        (row,) = model.holding
        assert row.sighted_count == 2
        assert row.newest_nonce == "n2"
        assert "Sighted 2 times since" in row.text

    def test_a_suspect_with_no_matching_routed_live_row_still_renders(self):
        # exposed CLI data is trusted verbatim — a join miss must not
        # silently drop the row (that would hide a real suspect).
        report = _report(
            recurrence_suspects=[{"id": "lrn-aa000002", "nonce": "n1", "seen_at": "2026-07-15T00:00:00Z"}],
            routed_live=[],
        )
        model = build_front_model(
            EMPTY_LIST, _status(), report, _mine(), sentinel_mtime=None, now=NOW
        )
        (row,) = model.holding
        assert row.bucket == ""
        assert row.routed_days_ago is None
        assert "Routing date unknown" in row.text


class TestFollowupRows:
    def test_passthrough_fields(self):
        report = _report(
            open_followups=[
                {"id": "lrn-aa000003", "bucket": "s", "action": "add real ERE check", "unblocks_on": "M3", "note": "why", "routed_at": "2026-06-01T00:00:00Z"}
            ]
        )
        model = build_front_model(
            EMPTY_LIST, _status(), report, _mine(), sentinel_mtime=None, now=NOW
        )
        (row,) = model.followups
        assert row.id == "lrn-aa000003"
        assert row.action == "add real ERE check"
        assert row.unblocks_on == "M3"
        assert row.routed_at == "2026-06-01T00:00:00Z"


class TestMinerBlock:
    def test_never_run(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(last_run=None, stale=False),
            sentinel_mtime=None, now=NOW,
        )
        assert model.miner.ok is True
        assert model.miner.last_run is None
        assert model.miner.stale is False
        assert model.miner.stale_label == "miner current"

    def test_stale_run_carries_a_text_label(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(last_run="2026-01-01T00:00:00Z", stale=True),
            sentinel_mtime=None, now=NOW,
        )
        assert model.miner.stale is True
        assert model.miner.stale_label
        assert "overdue" in model.miner.stale_label

    def test_run_rows_carry_status_labels(self):
        runs = [
            {"ts": "2026-07-16T00:00:00Z", "status": "ok", "trigger": "timer", "sessions_scanned": 4, "landed": 2, "folded": 1, "recurrences": 0, "fires": 3},
            {"ts": "2026-07-15T00:00:00Z", "status": "failed", "trigger": "manual", "reason": "boom"},
        ]
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(runs=runs), sentinel_mtime=None, now=NOW
        )
        assert len(model.miner.runs) == 2
        ok_run, failed_run = model.miner.runs
        assert ok_run.status_label == "completed"
        assert ok_run.landed == 2
        assert failed_run.status_label == "failed"

    def test_mine_status_cli_failure_surfaces_as_explicit_state(self):
        failure = CliRead(data=None, error="mine status blew up")
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), failure, sentinel_mtime=None, now=NOW
        )
        assert model.miner.ok is False
        assert model.miner.error == "mine status blew up"
        # never a silent "everything's fine" default
        assert model.miner.stale is True


class TestNearMissDrill:
    """09 §11 Y-24 (FW-34 §2): the one-liner's N/K/M + the drill rows,
    drawn from the LATEST ok/landed-uncommitted run only (F4)."""

    def _run(self, **overrides):
        base = {
            "run_id": "abc12345",
            "status": "ok",
            "trigger": "manual",
            "sessions_scanned": 3,
            "landed": 1,
            "folded": 0,
            "recurrences": 0,
            "fires": 0,
            "near_miss_count": 2,
            "outcomes": [
                {
                    "origin": "transcript:sess-a#L10",
                    "outcome": "dropped-cap",
                    "disposition": "cap-refused",
                    "reason": "a real lesson, but this run had already landed its cap",
                    "promotable": True,
                    "snippet": {
                        "type": "behavior",
                        "trigger": "About to rm -rf the wrong dir",
                        "instruction": "Double check pwd first",
                    },
                },
                {
                    "origin": "transcript:sess-b#L20",
                    "outcome": "folded",
                    "disposition": "already-canon",
                    "reason": "this is already reflected in an existing lesson",
                    "promotable": False,
                    "record": "lrn-bbbbbbbb",
                },
                {
                    "origin": "transcript:sess-c#L1",
                    "outcome": "landed",
                    "record": "lrn-cccccccc",
                },
            ],
        }
        base.update(overrides)
        return base

    def test_one_liner_counts_come_from_the_latest_ok_run(self):
        runs = [
            {"ts": "old", "status": "held-gate", "sessions_scanned": 99},
            self._run(),
        ]
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(runs=runs), sentinel_mtime=None, now=NOW
        )
        assert model.miner.latest_sessions_scanned == 3
        assert model.miner.latest_landed == 1
        assert model.miner.near_miss_count == 2
        assert model.miner.latest_run_id == "abc12345"

    def test_drill_rows_exclude_landed_and_carry_badge_reason_promotable(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(runs=[self._run()]),
            sentinel_mtime=None, now=NOW,
        )
        rows = model.miner.near_miss_rows
        assert len(rows) == 2  # `landed` contributes no row
        cap_row, canon_row = rows
        assert cap_row.index == 0
        assert cap_row.badge.kind == "cap-refused"
        assert cap_row.badge.text  # Y-10: never empty
        assert cap_row.promotable is True
        assert cap_row.draft_line == "About to rm -rf the wrong dir — Double check pwd first"
        assert cap_row.record_id is None
        assert canon_row.index == 1
        assert canon_row.badge.kind == "already-canon"
        assert canon_row.promotable is False
        assert canon_row.draft_line is None
        assert canon_row.record_id == "lrn-bbbbbbbb"

    def test_older_runs_near_misses_never_resurface_as_rows(self):
        """F4: the drill is a snapshot of the latest run, never an
        accumulating multi-run list."""
        older = self._run(
            near_miss_count=9,
            outcomes=[
                {
                    "origin": "transcript:old#L1",
                    "outcome": "dropped-cap",
                    "disposition": "cap-refused",
                    "reason": "old",
                    "promotable": True,
                    "snippet": {"type": "behavior", "trigger": "t", "instruction": "i"},
                }
            ],
        )
        newer = self._run(run_id="newer1", near_miss_count=1)
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(runs=[older, newer]),
            sentinel_mtime=None, now=NOW,
        )
        assert model.miner.latest_run_id == "newer1"
        assert model.miner.near_miss_count == 1
        assert len(model.miner.near_miss_rows) == 2  # from `newer` only

    def test_non_promotable_row_never_carries_a_draft_line_even_with_snippet(self):
        """A malformed/absent snippet must never leak into a draft line —
        promotable gates the derivation, not merely snippet presence."""
        run = self._run(
            outcomes=[
                {
                    "origin": "transcript:sess-x#L1",
                    "outcome": "scan-refused",
                    "disposition": "scan-blocked",
                    "reason": "held back",
                    "promotable": False,
                    "snippet": {"scan_refused_rule": "github-token"},
                }
            ]
        )
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(runs=[run]), sentinel_mtime=None, now=NOW
        )
        (row,) = model.miner.near_miss_rows
        assert row.promotable is False
        assert row.draft_line is None

    def test_canaries_absent_when_none_planted(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(), _mine(), sentinel_mtime=None, now=NOW
        )
        assert model.miner.canaries is None

    def test_canaries_summary_carried_verbatim(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(),
            _mine(canaries={"planted": 3, "caught": 2, "missed": 1, "open": []}),
            sentinel_mtime=None, now=NOW,
        )
        assert model.miner.canaries.planted == 3
        assert model.miner.canaries.caught == 2

    def test_no_ok_run_yet_yields_empty_drill_and_zero_counts(self):
        model = build_front_model(
            EMPTY_LIST, _status(), _report(),
            _mine(runs=[{"ts": "x", "status": "failed", "reason": "boom"}]),
            sentinel_mtime=None, now=NOW,
        )
        assert model.miner.near_miss_count == 0
        assert model.miner.near_miss_rows == ()
        assert model.miner.latest_run_id is None
