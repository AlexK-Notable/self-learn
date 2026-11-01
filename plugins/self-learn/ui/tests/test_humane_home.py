"""Humane lane 1 (S-136; proposal §2, §3, §10 in
misc/build-2026-11-01/humane/proposal.md): the shared header, the Home
page, and the bucket/detail fixes.

Model tests build `CliRead`s by hand; route tests monkeypatch the page
READS (`ledger.report`, `ledger.attention`, ...) directly, never through
FakeRunner, which carries verb invocations only (CLAUDE.md). Every
absence assertion has a positive control proving its region rendered.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from self_learn_ui import ledger as ledger_mod
from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.models import (
    CliRead,
    build_front_model,
    build_home_model,
    build_jobs,
    placed_text,
)
from self_learn_ui.runner import FakeRunner

from support import make_behavior, make_env, resolve_record_directly, seed_record

TOKEN = "t" * 43
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def _client(sb) -> TestClient:
    app = create_app(env=load_env(sb.env), token=TOKEN, runner=FakeRunner(), start_watcher=False)
    c = TestClient(app, base_url="http://127.0.0.1:7357")
    c.cookies.set("slu_token", TOKEN)
    return c


def _bucket(name, scope, *, pending=0, label="", path=None, path_exists=None, oldest=None,
            unanalyzed=0):
    return {"bucket": name, "scope": scope, "pending": pending, "oldest_days": oldest,
            "unanalyzed": unanalyzed, "label": label, "path": path, "path_exists": path_exists}


def _home(buckets, *, items=(), report=None, mine=None, status_extra=None):
    status = CliRead(data={"buckets": list(buckets), "total_pending": 0, "open_followups": 0,
                           "worker_last_run": None, **(status_extra or {})})
    list_read = CliRead(data=list(items))
    report_read = CliRead(data=report if report is not None else {})
    mine_read = CliRead(data=mine if mine is not None else {"last_run": None, "stale": False,
                                                             "runs": []})
    front = build_front_model(list_read, status, report_read, mine_read,
                              sentinel_mtime=None, now=NOW)
    return front, build_home_model(front, list_read, status, report_read, mine_read, now=NOW)


# ------------------------------------------------------------------ places


class TestPlacesSplit:
    def test_only_places_with_something_waiting_are_rows_and_gone_folders_fold_apart(self):
        far = "2099-01-01T00:00:00Z"
        _front, home = _home(
            [
                _bucket("user", "user", pending=2, label="Your instructions", path="~/.claude",
                        path_exists=True, oldest=3),
                _bucket("-r-later-1", "project", label="later", path="~/r/later",
                        path_exists=True),
                _bucket("-r-quiet-2", "project", label="quiet", path="~/r/quiet",
                        path_exists=True),
                _bucket("-r-gone-3", "project", label="gone (worktree x)", path="~/r/gone",
                        path_exists=False),
                # A gone folder that still holds waiting work is NEVER folded away.
                _bucket("-r-gonebusy-4", "project", pending=1, label="gone-busy",
                        path="~/r/gb", path_exists=False, oldest=1),
                _bucket("herdr", "skill", label="herdr"),
            ],
            items=[{"id": "lrn-aaaaaaa1", "bucket": "-r-later-1", "scope": "project",
                    "deferred_until": far}],
            report={"buckets": [{"bucket": "user", "scope": "user", "counts": {"routed": 77}},
                                {"bucket": "herdr", "scope": "skill", "counts": {"routed": 7}}]},
        )
        assert [p.label for p in home.places_waiting] == ["Your instructions", "gone-busy",
                                                          "later"]
        assert {p.label for p in home.places_quiet} == {"quiet", "herdr"}
        assert [p.label for p in home.places_gone] == ["gone (worktree x)"]
        (user,) = [p for p in home.places_waiting if p.scope == "user"]
        assert user.in_use == 77 and user.path == "~/.claude"
        (later,) = [p for p in home.places_waiting if p.label == "later"]
        assert later.pending == 0 and later.deferred == 1

    def test_a_skill_with_no_path_record_is_quiet_not_gone(self):
        """`path_exists: null` means "not applicable" (lane 0 contract §1),
        never "gone"."""
        _front, home = _home([_bucket("herdr", "skill", label="herdr", path_exists=None)])
        assert [p.label for p in home.places_quiet] == ["herdr"]
        assert home.places_gone == ()


# ----------------------------------------------------------- holding rows


class TestRuleTitles:
    def test_a_rule_seen_again_is_titled_by_its_own_words(self):
        report = {
            "recurrence_suspects": [
                {"id": "lrn-aaaaaaa1", "nonce": "n1", "seen_at": "2026-10-30T00:00:00Z",
                 "basis": "miner-match", "title": "About to use pgrep -f.",
                 "scope": "user", "bucket": "user", "bucket_label": "Your instructions"},
            ],
            "routed_live": [{"id": "lrn-aaaaaaa1", "bucket": "user", "scope": "user",
                             "routed_days_ago": 14, "destination": "hook",
                             "title": "About to use pgrep -f.",
                             "bucket_label": "Your instructions"}],
        }
        front, _home_model = _home([], report=report)
        (row,) = front.holding
        assert row.title == "About to use pgrep -f."
        assert row.place_label == "Your instructions"
        assert row.destination == "hook"
        assert placed_text(row.destination, row.scope, row.place_label) == (
            "Placed in your instructions, as a warning hook"
        )

    def test_the_title_falls_back_to_the_routed_row(self):
        report = {
            "recurrence_suspects": [{"id": "lrn-aaaaaaa1", "nonce": "n1",
                                     "seen_at": "2026-10-30T00:00:00Z"}],
            "routed_live": [{"id": "lrn-aaaaaaa1", "bucket": "s", "scope": "skill",
                             "routed_days_ago": 3, "title": "Stop the container first.",
                             "bucket_label": "s"}],
        }
        front, _ = _home([], report=report)
        assert front.holding[0].title == "Stop the container first."

    def test_an_unknown_destination_is_shown_raw_never_dropped(self):
        assert placed_text("some-future-kind", "project", "proj") == (
            "Placed in proj, as some-future-kind"
        )
        assert placed_text("claude-md", "project", "proj") == "Placed in proj"


# -------------------------------------------------------------------- jobs


def _run(**kw):
    base = {"ts": "2026-11-01T10:00:00Z", "status": "ok", "sessions_scanned": 2,
            "landed": 0, "recurrences": 1}
    base.update(kw)
    return base


class TestJobs:
    def _jobs(self, *, mine=None, status=None, worker_stale=False, unanalyzed=0):
        return build_jobs(
            CliRead(data=status or {}),
            CliRead(data=mine) if mine is not None else CliRead(data=None, error="boom"),
            worker_stale=worker_stale, total_unanalyzed=unanalyzed, now=NOW,
        )

    def test_all_on_time_says_so_and_names_the_last_read(self):
        jobs, line = self._jobs(mine={"last_run": "2026-11-01T10:00:00Z", "stale": False,
                                      "runs": [_run()]})
        assert line.late is False
        assert line.text == "All jobs ran on time"
        assert line.last_read == "2026-11-01T10:00:00Z"
        assert jobs[0].detail == "Read 2 sessions, found 0 new lessons, saw 1 rule come up again."

    def test_a_stale_overnight_read_is_named_in_words(self):
        jobs, line = self._jobs(mine={"last_run": "2026-10-29T10:00:00Z", "stale": True,
                                      "runs": [_run(ts="2026-10-29T10:00:00Z")]})
        assert line.late is True
        assert line.text == "The overnight read has not run for 3 days"
        assert jobs[0].late is True

    def test_a_failed_last_read_is_late_even_when_recent(self):
        _jobs, line = self._jobs(mine={"last_run": "2026-11-01T10:00:00Z", "stale": False,
                                       "runs": [_run(status="failed")]})
        assert _jobs[0].detail == "The last run failed."  # positive control: the row
        assert line.late is True and "failed" in line.text
        assert _jobs[0].late is True  # gate r1 MINOR-1: its own row is marked too

    def test_a_behind_drafting_job_and_an_unreadable_miner_both_show(self):
        _jobs, line = self._jobs(mine=None, worker_stale=True, unanalyzed=3)
        assert "Drafting suggestions is behind" in line.text
        assert "overnight read's status could not be read" in line.text

    def test_an_unreadable_status_is_never_called_on_time(self):
        """Gate r1 MINOR-2: with `status --json` failing, the header names
        it and never prints the all-clear, even with a healthy miner."""
        mine = {"last_run": "2026-11-01T10:00:00Z", "stale": False, "runs": [_run()]}
        assert self._jobs(mine=mine)[1].text == "All jobs ran on time"  # control
        _jobs, line = build_jobs(
            CliRead(data=None, error="status: boom"), CliRead(data=mine),
            worker_stale=False, total_unanalyzed=0, now=NOW,
        )
        assert line.late is True
        assert "Job status could not be read" in line.text
        assert "All jobs ran on time" not in line.text

    def test_a_held_nightly_review_is_named_in_the_header(self):
        """Gate r1 MINOR-3: the steward's own hold, carried by `status
        --json`, turns its row and the header late, in plain words."""
        mine = {"last_run": "2026-11-01T10:00:00Z", "stale": False, "runs": [_run()]}
        jobs, line = self._jobs(mine=mine, status={"steward_enabled": True,
                                                   "steward_hold": "OAuth session expired"})
        steward = jobs[2]
        assert steward.key == "steward"  # positive control: the right row
        assert steward.late is True
        assert steward.detail == "On hold: OAuth session expired."
        assert line.late is True and line.text == "The nightly review is on hold"

    def test_a_behind_nightly_review_is_named_in_the_header(self):
        mine = {"last_run": "2026-11-01T10:00:00Z", "stale": False, "runs": [_run()]}
        jobs, line = self._jobs(mine=mine, status={"steward_enabled": True,
                                                   "steward_stale": True,
                                                   "steward_stale_hours": 48})
        assert jobs[2].late is True
        assert jobs[2].detail == "Behind: no finished run for over 48 hours while lessons wait."
        assert line.late is True and line.text == "The nightly review is behind"
        # A steward that is neither held nor stale is never called late.
        quiet, ok = self._jobs(mine=mine, status={"steward_enabled": True,
                                                  "steward_stale": False})
        assert quiet[2].late is False and ok.text == "All jobs ran on time"

    def test_an_overnight_read_that_never_ran_is_not_called_on_time(self):
        """Gate r1 NIT-4: nothing is late, but the all-clear would be false
        beside a job that has not run yet."""
        jobs, line = self._jobs(mine={"last_run": None, "stale": False, "runs": []})
        assert jobs[0].detail == "Has not run yet."  # positive control
        assert line.late is False and line.waiting is True
        assert line.text == "The overnight read has not run yet"

    def test_the_weekly_check_is_late_only_a_day_after_its_time(self):
        mine = {"last_run": "2026-11-01T10:00:00Z", "stale": False, "runs": [_run()]}
        due_soon = (NOW - timedelta(hours=20)).isoformat()
        overdue = (NOW - timedelta(days=2)).isoformat()
        assert self._jobs(mine=mine, status={"overseer_next": due_soon})[1].late is False
        _jobs, line = self._jobs(mine=mine, status={"overseer_next": overdue})
        assert line.late is True and line.text == "The weekly check is overdue"


# ------------------------------------------------------------------ routes


def _holding_report():
    return {
        "recurrence_suspects": [
            {"id": "lrn-aaaaaaa1", "nonce": "n1", "seen_at": "2026-10-30T00:00:00Z",
             "basis": "miner-match", "title": "About to use pgrep -f from the Bash tool.",
             "scope": "skill", "bucket": "s", "bucket_label": "s"},
        ],
        "routed_live": [{"id": "lrn-aaaaaaa1", "bucket": "s", "scope": "skill",
                         "routed_days_ago": 14, "destination": "skill-md",
                         "title": "About to use pgrep -f from the Bash tool.",
                         "bucket_label": "s"}],
        "buckets": [],
        "series": {"days": 1, "tz": "+00:00", "error": None,
                   "rows": [{"date": "2026-11-01", "pending": 1, "deferred": 0, "captured": 0,
                             "decided": {"use": 0, "no": 0, "later": 0, "kept": 0},
                             "decided_by": {}, "verbs": {}}]},
    }


class TestHomeRoute:
    def test_a_rule_row_shows_its_words_and_folds_its_four_choices(self, tmp_path, monkeypatch):
        sb = make_env(tmp_path)
        monkeypatch.setattr(ledger_mod, "report", lambda home, **kw: CliRead(data=_holding_report()))
        r = _client(sb).get("/")
        assert r.status_code == 200
        assert "Rules seen again (1)" in r.text  # positive control: the region rendered
        assert '<p class="home-row-what">About to use pgrep -f from the Bash tool.</p>' in r.text
        assert "Placed in s, 14 days ago" in r.text
        assert "Routed 14d ago" not in r.text  # the old date-only wording is gone
        fold = r.text.split('<details class="decide-fold">', 1)[1].split("</details>", 1)[0]
        assert "Decide&hellip;" in fold
        for action in ("tolerate", "confirm_recurrence", "retire", "dismiss_suspect"):
            assert f'data-key-action="{action}"' in fold

    def test_the_series_block_reaches_the_template_for_the_charts(self, tmp_path, monkeypatch):
        sb = make_env(tmp_path)
        report = _holding_report()
        monkeypatch.setattr(ledger_mod, "report", lambda home, **kw: CliRead(data=report))
        r = _client(sb).get("/")
        assert r.context["series"] == report["series"]

    def test_home_never_waits_on_the_inbox_and_the_tile_fills_in_after(self, tmp_path,
                                                                       monkeypatch):
        sb = make_env(tmp_path)
        reads: list[str] = []

        def attention(home, env=None):
            reads.append("attention")
            return CliRead(data={"counts": {"needs_you": 3, "new": 5}, "items": []})

        monkeypatch.setattr(ledger_mod, "attention", attention)
        c = _client(sb)
        page = c.get("/").text
        assert 'hx-get="/home/needs-you"' in page  # positive control: the placeholder
        assert reads == []
        tile = c.get("/home/needs-you").text
        assert reads == ["attention"]
        assert '<span class="home-tile-value">3</span>' in tile  # needs_you only, not +new
        monkeypatch.setattr(ledger_mod, "attention",
                            lambda home, env=None: CliRead(data=None, error="boom"))
        assert '<span class="home-tile-value">?</span>' in c.get("/home/needs-you").text

    def test_a_quiet_place_is_folded_and_not_a_keyboard_row(self, tmp_path):
        sb = make_env(tmp_path, skills=("s", "t"))
        seed_record(sb.ledger, make_behavior(scope="skill:s"))
        quiet = make_behavior(scope="skill:t")  # a place with only a decided rule
        seed_record(sb.ledger, quiet)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "t", quiet)
        html = _client(sb).get("/").text
        table = html.split('<table class="bucket-walk places-table">', 1)[1].split("</table>", 1)[0]
        assert 'href="/bucket/skill/s"' in table  # positive control: the waiting place is a row
        assert 'href="/bucket/skill/t"' not in table
        fold = html.split('<details class="places-more">', 1)[1].split("</details>", 1)[0]
        assert 'href="/bucket/skill/t"' in fold
        assert "data-row" not in fold


class TestSharedHeader:
    def test_another_page_fetches_the_jobs_line_after_load(self, tmp_path, monkeypatch):
        sb = make_env(tmp_path)
        page = _client(sb).get("/report").text
        assert 'class="site-header"' in page
        assert 'hx-get="/header/jobs"' in page
        assert '<a href="/report" aria-current="page">Health</a>' in page
        # Health's level above is Home: Esc goes there.
        assert '<a href="/" data-key-action="up"' in page
        monkeypatch.setattr(ledger_mod, "mine_status", lambda home, **kw: CliRead(
            data={"last_run": "2026-10-20T00:00:00Z", "stale": True, "runs": []}))
        line = _client(sb).get("/header/jobs").text
        assert "jobs-line-late" in line and "The overnight read has not run for" in line

    def test_settings_has_no_up_target_and_marks_its_place(self, tmp_path):
        sb = make_env(tmp_path)
        page = _client(sb).get("/settings").text
        assert '<a href="/settings" aria-current="page">Settings</a>' in page
        assert 'data-key-action="up"' not in page

    def test_a_detail_page_goes_up_to_its_place_by_name(self, tmp_path):
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        page = _client(sb).get(f"/record/{rec.id}").text
        crumbs = page.split('<nav class="crumbs"', 1)[1].split("</nav>", 1)[0]
        assert 'data-key-action="up" href="/bucket/skill/s"' in crumbs
        assert page.count('data-key-action="up"') == 1
        assert f'title="Its id in the ledger: {rec.id}"' in crumbs


# ------------------------------------------------------- bucket and detail


class TestBucketAndDetailWords:
    def test_an_empty_place_says_nothing_is_waiting(self, tmp_path):
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")  # one decided rule, nothing waiting
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec)
        page = _client(sb).get("/bucket/skill/s").text
        assert '<h1 class="place-title">s</h1>' in page
        assert "Nothing is waiting here. 1 rule from here is in use" in page

    def test_a_place_with_waiting_work_does_not_say_it_is_empty(self, tmp_path):
        sb = make_env(tmp_path)
        seed_record(sb.ledger, make_behavior(scope="skill:s"))
        page = _client(sb).get("/bucket/skill/s").text
        assert 'class="record-row' in page  # positive control: the work renders
        assert "Nothing is waiting here." not in page

    def test_approve_is_not_primary_until_there_is_a_suggestion(self, tmp_path):
        from support import seed_proposal

        sb = make_env(tmp_path)
        bare = make_behavior(scope="skill:s")
        seed_record(sb.ledger, bare)
        suggested = make_behavior(scope="skill:s")
        seed_record(sb.ledger, suggested)
        seed_proposal(sb.ledger, suggested.id)
        c = _client(sb)
        page = c.get(f"/record/{bare.id}").text
        assert 'data-key-action="route" class="approve-unsuggested"' in page
        assert "Destination: not suggested yet (o)" in page
        other = c.get(f"/record/{suggested.id}").text
        assert "Approve (e)" in other  # positive control
        assert "approve-unsuggested" not in other
        assert "Ask for a suggestion" not in other

    def test_a_decided_rule_is_not_told_twice(self, tmp_path):
        sb = make_env(tmp_path)
        trigger = "About to hand-edit a synced dotfile directly."
        rec = make_behavior(scope="skill:s", trigger=trigger,
                            instruction="Run the sync script instead.")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec)
        page = _client(sb).get(f"/record/{rec.id}").text
        assert f'<h1 class="resolved-title">{trigger}</h1>' in page
        assert "Run the sync script instead." in page  # positive control: the body renders
        assert page.count(trigger) == 1


@pytest.mark.parametrize("sightings, words", [(1, "1 sighting ·"), (2, "2 sightings ·")])
def test_sightings_are_counted_in_words(tmp_path, sightings, words):
    from self_learn_ui.models import _build_finding

    rec = make_behavior(scope="skill:s")
    rec.set_sightings(sightings)
    assert words in _build_finding(rec, "t").provenance_text + " ·"


# ------------------------------------------------------ gate r1 fold (lane 1)


class TestGateR1Fold:
    def test_an_empty_place_counts_the_rules_replaced_there_from_the_report(
        self, tmp_path, monkeypatch
    ):
        """MINOR-6 (proposal §10): the count is `report --json`'s own
        per-bucket `counts.superseded`, from the read the page already makes."""
        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec)
        calls: list[str] = []

        def report(home, **kw):
            calls.append("report")
            return CliRead(data={"routed_live": [], "recurrence_suspects": [], "buckets": [
                {"bucket": "s", "scope": "skill", "counts": {"routed": 1, "superseded": 2}},
                {"bucket": "s", "scope": "project", "counts": {"superseded": 9}},
            ]})

        monkeypatch.setattr(ledger_mod, "report", report)
        page = _client(sb).get("/bucket/skill/s").text
        assert "Nothing is waiting here." in page  # positive control: the sentence
        assert "2 earlier rules from here were later replaced or retired." in page
        assert calls == ["report"]  # one report read for the whole page
        monkeypatch.setattr(ledger_mod, "report",
                            lambda home, **kw: CliRead(data=None, error="boom"))
        failed = _client(sb).get("/bucket/skill/s").text
        assert "Nothing is waiting here." in failed
        assert "replaced or retired" not in failed

    def test_home_reads_the_inbox_once_and_fills_the_header_link_from_it(
        self, tmp_path, monkeypatch
    ):
        """NIT-1: Home's header link is filled out of band by the SAME
        attention read as the tile; other pages still fetch their count."""
        sb = make_env(tmp_path)
        reads: list[str] = []

        def attention(home, env=None):
            reads.append("attention")
            return CliRead(data={"counts": {"needs_you": 2, "new": 0}, "items": []})

        monkeypatch.setattr(ledger_mod, "attention", attention)
        c = _client(sb)
        home = c.get("/").text
        assert 'id="nav-inbox"' in home and 'hx-get="/home/needs-you"' in home  # control
        assert 'hx-get="/inbox/count"' not in home
        assert 'hx-get="/inbox/count"' in c.get("/report").text
        tile = c.get("/home/needs-you").text
        assert reads == ["attention"]
        oob = tile.split('<span id="nav-inbox"', 1)[1].split("</span>", 1)[0]
        assert 'hx-swap-oob="true"' in oob
        assert "Inbox (2)" in oob

    def test_the_bucket_page_names_a_shared_folder_by_its_path_like_home(self, tmp_path):
        """NIT-2: two projects sharing a folder name are told apart by their
        `~` path on the bucket page, as on Home (resolved together)."""
        from self_learn_ui.routes import _place

        sb = make_env(tmp_path)
        for slug, where in (("a-app", tmp_path / "a" / "app"), ("b-app", tmp_path / "b" / "app")):
            where.mkdir(parents=True)
            d = sb.ledger / "projects" / slug
            d.mkdir(parents=True)
            (d / "meta.yaml").write_text(f"path: {where}\n", encoding="utf-8")
        a = _place(sb.ledger, "project", "a-app")
        b = _place(sb.ledger, "project", "b-app")
        assert a["path"] and b["path"]  # positive control: both resolved
        assert a["label"] == a["path"] and b["label"] == b["path"]
        assert a["label"] != b["label"]

    def test_home_words_a_suggestion_as_its_bucket_row_arms_it(self):
        """NIT-3: a user-scope lesson whose proposal recommends waiting (the
        reference file does not fit there) is not "suggested" on Home."""
        item = {"id": "lrn-00000001", "bucket": "user", "scope": "user",
                "destination": "reference", "has_proposal": True, "title": "x"}
        fits = {"id": "lrn-00000002", "bucket": "user", "scope": "user",
                "destination": "claude-md", "has_proposal": True, "title": "y"}
        status = CliRead(data={"buckets": [_bucket("user", "user", pending=2)],
                               "total_pending": 2, "open_followups": 0,
                               "worker_last_run": None})
        list_read = CliRead(data=[item, fits])
        report_read = CliRead(data={})
        mine_read = CliRead(data={"last_run": None, "stale": False, "runs": []})
        front = build_front_model(list_read, status, report_read, mine_read,
                                  sentinel_mtime=None, now=NOW)
        model = build_home_model(
            front, list_read, status, report_read, mine_read, now=NOW,
            proposals={"lrn-00000001": {"recommendation": "defer",
                                        "destination": "reference"},
                       "lrn-00000002": {"recommendation": "route",
                                        "destination": "claude-md"}},
        )
        by_id = {row.id: row.suggestion_text for row in model.lessons}
        assert by_id["lrn-00000002"] == "suggested: your instructions"  # control
        assert by_id["lrn-00000001"] == (
            "no place chosen yet: the suggestion does not fit here"
        )
