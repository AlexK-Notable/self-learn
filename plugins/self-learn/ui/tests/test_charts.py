"""Humane lane 2 (S-137): charts.py, partials/home_charts.html and
the Health page. Every chart here draws COUNTS the CLI wrote; these tests
pin the three promises that make that honest and readable:

* an unknown day is a GAP, never a zero;
* every chart carries a "Show as a table" fold that holds every value, and a
  narrow variant for a phone;
* nothing the CLI sent reaches the page unescaped, and no inline style or
  script is emitted (09 §3 W-9 CSP).

A chart's own mark counts are asserted against a positive control first (the
region rendered at all) before any absence is claimed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from self_learn import series as cli_series
from self_learn_ui import charts, health
from self_learn_ui.app import _build_templates, create_app
from self_learn_ui.env import load_env
from self_learn_ui.models import CliRead
from self_learn_ui.runner import FakeRunner

from support import make_behavior, make_env, seed_record

TOKEN = "test-token"


def _row(day: int, pending, deferred=0, **decided):
    d = {g: 0 for g in cli_series.OUTCOME_GROUPS}
    d.update(decided)
    return {
        "date": f"2026-10-{day:02d}",
        "pending": pending,
        "deferred": deferred if pending is not None else None,
        "captured": 0,
        "decided": d,
        "decided_by": {},
        "verbs": {},
    }


def _series(pendings, per_day=None):
    per_day = per_day or {}
    rows = [_row(i + 1, p, **per_day.get(i, {})) for i, p in enumerate(pendings)]
    return {"days": len(rows), "tz": "+00:00", "error": None, "rows": rows}


def _svgs(html: str) -> list[str]:
    return re.findall(r"<svg .*?</svg>", str(html), flags=re.S)


def _lines(svg: str) -> list[str]:
    return re.findall(r'<path class="cv-line"', svg)


# --------------------------------------------------------------- the gap


class TestWaitingChartGap:
    def test_positive_control_a_full_series_draws_one_line_per_drawing(self) -> None:
        html = charts.waiting_chart(_series([4, 3, 5, 2, 1, 6, 2, 2]))
        svgs = _svgs(html)
        assert len(svgs) == 3  # narrow, wide, xwide
        assert all(len(_lines(s)) == 1 for s in svgs)

    def test_an_unknown_day_breaks_the_line_in_every_drawing(self) -> None:
        html = charts.waiting_chart(_series([4, 3, None, None, 1, 6, 2, 2]))
        svgs = _svgs(html)
        assert len(svgs) == 3
        assert all(len(_lines(s)) == 2 for s in svgs), "a null day must split the line, not bridge or zero it"

    def test_an_unknown_day_is_labelled_not_known_and_is_not_a_zero(self) -> None:
        html = str(charts.waiting_chart(_series([4, None, 2])))
        assert "2 Oct: not known" in html
        assert "2 Oct: 0 waiting" not in html
        # the table says so too, and carries the real zero distinctly
        html0 = str(charts.waiting_chart(_series([4, 0, 2])))
        assert "2 Oct: 0 waiting for a decision" in html0
        assert "not known" not in html0

    def test_a_lone_known_day_between_gaps_is_still_drawn(self) -> None:
        svg = _svgs(charts.waiting_chart(_series([None, 3, None, 5, 6])))[0]
        assert 'class="cv-dot"' in svg  # the isolated day
        assert len(_lines(svg)) == 1  # the 5-6 run

    def test_no_end_label_when_today_is_unknown(self) -> None:
        with_today = str(charts.waiting_chart(_series([1, 2, 3])))
        without = str(charts.waiting_chart(_series([1, 2, None])))
        assert "3 now" in with_today
        assert " now<" not in without

    def test_all_unknown_draws_words_not_a_chart(self) -> None:
        s = _series([None, None, None])
        s["error"] = "could not read the ledger's git history"
        html = str(charts.waiting_chart(s))
        assert "<svg" not in html
        assert "could not read the ledger&#x27;s git history" in html or "could not read the ledger's git history" in html


class TestRoomUnderTheAxis:
    def test_each_drawing_keeps_30_units_under_the_plot_for_its_date_labels(self) -> None:
        """Gate r1 n-4: at 26 the axis "0" and the first date label touched
        in the narrow drawing. Heights: top 12 + plot + bottom 30."""
        html = str(charts.waiting_chart(_series([3, 2, 1, 4])))
        heights = [int(h) for h in re.findall(r'viewBox="0 0 \d+ (\d+)"', html)]
        assert heights == [12 + 150 + 30, 12 + 150 + 30, 12 + 170 + 30]


class TestWaitingSentence:
    def test_quotes_first_and_last_counts(self) -> None:
        s = charts.waiting_sentence(_series([16, 9, 4, 2]))
        assert "16 lessons were waiting" in s and "Now there are 2" in s

    def test_singular_and_unchanged(self) -> None:
        assert "Now there is 1" in charts.waiting_sentence(_series([5, 1]))
        assert "still 3" in charts.waiting_sentence(_series([3, 7, 3]))

    def test_skips_leading_and_trailing_unknown_days(self) -> None:
        s = charts.waiting_sentence(_series([None, 7, 5, None]))
        assert "On 2 Oct, 7 lessons" in s and "On 3 Oct there are 5" in s


# ------------------------------------------------- the stacked decisions


class TestDecidedChart:
    def _series(self):
        return _series(
            [1, 1, 1],
            {
                0: {"use": 4, "no": 2},
                1: {},
                2: {"later": 1, "kept": 9},
            },
        )

    def test_one_segment_per_present_group_in_stack_order(self) -> None:
        html = str(charts.decided_chart(self._series()))
        svg = _svgs(html)[1]  # the wide drawing
        classes = re.findall(r'<path class="cv-(use|no|later|kept)"', svg)
        assert classes == ["use", "no", "later", "kept"]  # day 1: use,no; day 3: later,kept

    @staticmethod
    def _heights(svg: str, group: str) -> list[float]:
        """Drawn height of every `group` segment: from its baseline end
        (the path's M) up to its top (the Q control point of a rounded top,
        else the V target)."""
        out = []
        for m in re.finditer(rf'<path class="cv-{group}" d="M[\d.]+,([\d.]+) V([\d.]+)( Q[\d.]+,([\d.]+))?', svg):
            top = float(m.group(4)) if m.group(4) else float(m.group(2))
            out.append(float(m.group(1)) - top)
        return out

    def test_segment_height_follows_the_count(self) -> None:
        # two lone "use" columns, 4 then 2: the first is twice as tall
        svg = _svgs(charts.decided_chart(_series([1, 1], {0: {"use": 4}, 1: {"use": 2}})))[1]
        h4, h2 = self._heights(svg, "use")
        assert h2 > 0
        assert h4 / h2 == pytest.approx(2.0, rel=0.02)

    def test_stacked_segments_leave_a_gap_and_keep_their_own_heights(self) -> None:
        svg = _svgs(charts.decided_chart(self._series()))[1]
        (use,) = self._heights(svg, "use")
        (no,) = self._heights(svg, "no")
        assert use > no > 0  # 4 is drawn taller than 2 within the same column

    def test_a_quiet_night_is_an_empty_slot_not_a_mark(self) -> None:
        svg = _svgs(charts.decided_chart(self._series()))[1]
        assert "2 Oct: nothing decided" in svg
        assert svg.count('class="cv-') > 4  # positive control: the rest rendered

    def test_table_holds_every_value(self) -> None:
        html = str(charts.decided_chart(self._series()))
        table = html.split('<table class="chart-data">', 1)[1].split("</table>", 1)[0]
        for words in charts.GROUP_WORDS.values():
            assert f">{words}</th>" in table
        row1 = re.search(r"<tr><th scope=\"row\">1 Oct</th>(.*?)</tr>", table).group(1)
        assert re.findall(r">(\d+)<", row1) == ["4", "2", "0", "0"]
        row3 = re.search(r"<tr><th scope=\"row\">3 Oct</th>(.*?)</tr>", table).group(1)
        assert re.findall(r">(\d+)<", row3) == ["0", "0", "1", "9"]

    def test_sentence_sums_the_counts(self) -> None:
        s = charts.decided_sentence(self._series())
        assert s.startswith("16 decisions in the last 3 days:")
        assert "4 put to use" in s and "9 looked at and kept as is" in s

    def test_an_empty_window_says_nothing_was_decided(self) -> None:
        s = _series([0, 0])
        assert "Nothing was decided" in charts.decided_sentence(s)

    def test_every_outcome_group_the_cli_defines_has_words_and_a_colour_class(self) -> None:
        css = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text()
        for g in cli_series.OUTCOME_GROUPS:
            assert g in charts.GROUP_WORDS
            # the real rule, with its colour: the forced-colors override also
            # names `.cv-<g>`, so the bare selector would match it too
            assert re.search(rf"\.chart-svg \.cv-{g} \{{ fill: var\(--chart-{g}\); \}}", css)
            assert re.search(rf"\.chart-key-{g} \{{ background: var\(--chart-{g}\); \}}", css)
        legend = str(charts.decided_legend())
        for words in charts.GROUP_WORDS.values():
            assert words in legend

    def test_only_the_last_three_weeks_are_drawn(self) -> None:
        s = _series([1] * 28)
        table = str(charts.decided_chart(s)).split("<tbody>", 1)[1]
        assert table.count('<th scope="row">') == charts.DECIDED_DAYS


# ------------------------------------------------------- supply, generic


class TestSupplyChart:
    MIX = {"teach": 83, "session": 243, "rewrite": 11, "backlog": 32}

    def test_ranked_high_to_low_with_words(self) -> None:
        table = str(charts.supply_chart(self.MIX)).split("<tbody>", 1)[1]
        order = re.findall(r'<th scope="row">(.*?)</th>', table)
        assert order == [
            "Found in your sessions overnight",
            "Taught during a session",
            "Imported from older notes",
            "Rewrites of earlier lessons",
        ]

    def test_sentence_quotes_the_total_and_the_top_source(self) -> None:
        assert charts.supply_sentence(self.MIX) == (
            "Of 369 lessons so far, 243 came from your sessions, read overnight."
        )

    def test_every_ledger_source_has_words(self) -> None:
        from self_learn.records import SOURCES

        for key in SOURCES:
            assert key in charts.SUPPLY_WORDS, f"no words for the lesson source {key!r}"

    def test_an_unknown_key_shows_raw_never_dropped(self) -> None:
        html = str(charts.supply_chart({"session": 3, "brand-new": 2}))
        assert "brand-new" in html


# ------------------------------------------------ shape and safety, all


ALL = {
    "waiting": lambda: charts.waiting_chart(_series([3, 2, 1, 4])),
    "decided": lambda: charts.decided_chart(_series([1, 1], {0: {"use": 2}})),
    "supply": lambda: charts.supply_chart({"session": 5, "teach": 1}),
}


@pytest.mark.parametrize("kind", sorted(ALL))
class TestEveryChart:
    def test_has_a_table_fold_and_three_drawings(self, kind: str) -> None:
        html = str(ALL[kind]())
        assert f'data-chart="{kind}"' in html
        assert "<summary>Show as a table</summary>" in html
        assert 'class="chart-data"' in html
        widths = [int(w) for w in re.findall(r'viewBox="0 0 (\d+) ', html)]
        assert widths == [320, 560, 960]  # narrow (390 px phone), wide, xwide

    def test_each_drawing_is_a_described_image(self, kind: str) -> None:
        for svg in _svgs(ALL[kind]()):
            assert 'role="img"' in svg and 'aria-label="' in svg

    def test_no_inline_style_or_script_reaches_the_page(self, kind: str) -> None:
        html = str(ALL[kind]())
        assert 'style="' not in html and "<style" not in html and "<script" not in html
        assert "onclick" not in html and "onmouseover" not in html


class TestEscaping:
    def test_hostile_text_from_the_cli_is_escaped(self) -> None:
        evil = '<script>alert(1)</script>"'
        s = _series([1, 2])
        s["rows"][0]["date"] = evil
        html = str(charts.waiting_chart(s))
        assert "<script>" not in html and "&lt;script&gt;" in html
        html2 = str(charts.supply_chart({evil: 4}))
        assert "<script>" not in html2 and "&lt;script&gt;" in html2

    def test_malformed_series_never_raises(self) -> None:
        for bad in (None, {}, {"rows": "x"}, {"rows": [1, None, {"date": 3}]}, [], "nope"):
            charts.waiting_chart(bad)
            charts.decided_chart(bad)
            charts.waiting_sentence(bad)
            charts.decided_sentence(bad)
        for bad in (None, {}, {"a": "x"}, {"a": True}, []):
            charts.supply_chart(bad)
            charts.supply_sentence(bad)


# ------------------------------------------------------- the Home partial


class TestHomeChartsPartial:
    def _render(self, **ctx) -> str:
        env = _build_templates().env
        return env.get_template("partials/home_charts.html").render(**ctx)

    def test_renders_both_charts_from_a_fixture_series(self) -> None:
        html = self._render(series=_series([16, 9, 5, 2], {3: {"use": 3, "no": 1}}))
        assert "Is it keeping up?" in html
        assert "What got decided, night by night" in html
        assert 'data-chart="waiting"' in html and 'data-chart="decided"' in html
        assert html.count("Show as a table") == 2
        assert "On 1 Oct, 16 lessons were waiting for a decision. Now there are 2." in html

    def test_a_null_pending_day_is_a_gap_in_the_partial(self) -> None:
        html = self._render(series=_series([4, None, 2, 1]))
        svg = _svgs(html)[1]
        assert len(_lines(svg)) == 1 and 'class="cv-dot"' in svg  # 4 alone, then 2-1
        assert "2 Oct: not known" in html

    def test_without_a_series_the_partial_renders_nothing(self) -> None:
        assert "chart" not in self._render()
        assert "chart" not in self._render(series=None)

    def test_the_decisions_table_matches_the_cli_groups(self) -> None:
        html = self._render(series=_series([1, 1]))
        for group in cli_series.OUTCOME_GROUPS:
            assert charts.GROUP_WORDS[group] in html


# --------------------------------------------------------- Health page


REPORT = {
    "generated": "2026-11-01",
    "buckets": [],
    "routed_ever": 211,
    "superseded_after_routing": 22,
    "supersede_rate": 0.1043,
    "graduated": 58,
    "rejected": 112,
    "mined": {"pending": 0, "accept_rate": 0.5593},
    "telemetry": {"events_by_kind": {"capture": 322}, "capture_rate_ceiling": 0.9, "decline_reasons": {}},
    "routed_live": [
        {"id": "lrn-aaaa0001", "bucket": "user", "scope": "user", "bucket_label": "Your instructions",
         "title": "About to accept an empty result as proof a check passed", "destination": "claude-md",
         "routed_days_ago": 99, "last_confirmed": None, "recurrences": 2, "dismissed_suspects": 0},
        {"id": "lrn-aaaa0002", "bucket": "user", "scope": "user", "bucket_label": "Your instructions",
         "title": "About to run <b>pkill -f</b> on a name in your own command", "destination": "hook",
         "routed_days_ago": 120, "last_confirmed": None, "recurrences": 0, "dismissed_suspects": 0},
        {"id": "lrn-aaaa0003", "bucket": "herdr", "scope": "skill", "bucket_label": "herdr",
         "title": "", "destination": "mystery", "routed_days_ago": 1, "last_confirmed": None,
         "recurrences": 0, "dismissed_suspects": 0},
    ],
    "recurrence_suspects": [
        {"id": "lrn-aaaa0001", "nonce": "n1", "seen_at": "2026-10-26T10:45:28Z", "basis": "miner-match",
         "title": "About to accept an empty result as proof a check passed", "scope": "user",
         "bucket": "user", "bucket_label": "Your instructions"},
        {"id": "lrn-aaaa0001", "nonce": "n2", "seen_at": "2026-10-28T10:45:28Z", "basis": "fire-violated",
         "title": "About to accept an empty result as proof a check passed", "scope": "user",
         "bucket": "user", "bucket_label": "Your instructions"},
    ],
    "open_followups": [
        {"id": "lrn-ffff0001", "bucket": "user", "action": "Check back on the search-only gap",
         "unblocks_on": "2026-08-01T00:00:00Z", "routed_at": "2026-07-01T00:00:00Z"},
    ],
    "series": _series([8, 7, 5, 2]),
    "destinations": {"claude-md": 107, "skill-md": 42, "hook": 8},
    "deferred": [
        {"id": "lrn-dddd0001", "bucket": "-home-me-repos-widget-8c7fedb5", "until": "2026-10-30", "overdue_days": 2},
        {"id": "lrn-dddd0002", "bucket": "-home-me-repos-widget-8c7fedb5", "until": "2026-10-01", "overdue_days": 31},
        {"id": "lrn-dddd0003", "bucket": "herdr", "until": "2026-11-09", "overdue_days": -7},
    ],
    "suspects_dismissed": [
        {"id": "lrn-aaaa0001", "ref": "r1", "ts": "2026-10-21T10:44:41Z", "dismissed_at": "2026-10-21",
         "basis": "fire-suspected-violation", "why": "unrelated"},
        {"id": "lrn-gone0001", "ref": "r2", "ts": "2026-09-13T10:44:25Z", "dismissed_at": "2026-09-28",
         "basis": "fire-violated", "why": "rule-followed"},
    ],
    "context_budget": {
        "tokens_per_word_est": 1.33,
        "composition": {"flagged": True, "surfaces": [
            {"surface": "project-claude-md", "key": "8c7fedb5", "flagged": True, "flagged_by": ["caution", "growth"]},
            {"surface": "user-claude-md", "key": "~/.claude/CLAUDE.md", "flagged": False, "flagged_by": []},
        ]},
        "conditional": {"rules_cofire": {"flagged": True, "threshold_max_fanin": 5, "scopes": [
            {"scope": "project", "key": "8c7fedb5", "crowded": True, "max_fanin": 15, "pairs": [["a", "b"]]},
            {"scope": "user", "key": "~/.claude/rules", "crowded": False, "max_fanin": 0, "pairs": []},
        ]}},
        "budget": {
            "severity": "informational",
            "window_days": 30,
            "surfaces": [
                {"surface": "user-claude-md", "key": "~/.claude/CLAUDE.md", "state": "absent", "file_words": None,
                 "managed_words": None, "managed_share": None, "flagged": False},
                {"surface": "project-claude-md", "key": "8c7fedb5", "state": "ok", "file_words": 1735,
                 "managed_words": 0, "managed_share": 0.0, "flagged": True},
            ],
        },
    },
    "reference_shelf": {"instrumented": False, "instrument_state": "script-missing", "targets_total": 13, "targets": [{}, {}]},
    "surface_reach": {
        "checked": 163, "reachable": 43, "unreachable": 56, "unmeasurable": 64,
        "by_destination": {"hook": {"reachable": 0, "unreachable": 8, "unmeasurable": 0}},
        "rows": [{"record_id": "lrn-aaaa0001"}],
    },
}
REPORT["buckets"] = [
    {"bucket": "-home-me-repos-widget-8c7fedb5", "scope": "project", "label": "widget",
     "path": "~/repos/widget_" + "unbreakable" * 12,  # no hyphen or slash to break at: it must wrap anywhere
     "path_exists": True, "counts": {"routed": 3, "superseded": 1}},
    {"bucket": "herdr", "scope": "skill", "label": "herdr", "path": None, "path_exists": None, "counts": {}},
]
STATUS = {
    "buckets": [{"bucket": "user", "scope": "user", "label": "Your instructions", "path": "~/.claude",
                 "path_exists": True, "pending": 2, "oldest_days": 0, "unanalyzed": 0, "unreadable": 0}],
    "supply_mix": {"session": 243, "teach": 83, "rewrite": 11, "backlog": 32},
    "metrics": {"time_to_triage_median_days": 1.0, "pending_total": 2,
                "pending_over_30d_pct": 0.0, "routed_and_corrected": 22},
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    sb = make_env(tmp_path)
    # a deferred lesson whose own words the page can read (lrn-dddd0002 has no file)
    seed_record(sb.ledger, make_behavior(scope="skill:s", record_id="lrn-dddd0001", trigger="Putting off the widget cleanup."))
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    c = TestClient(app, base_url="http://127.0.0.1:7357")
    c.cookies.set("slu_token", TOKEN)
    from self_learn_ui import ledger

    calls = {"report": 0, "status": 0}

    def _report(home):
        calls["report"] += 1
        return CliRead(data=REPORT)

    def _status(home):
        calls["status"] += 1
        return CliRead(data=STATUS)

    monkeypatch.setattr(ledger, "report", _report)
    monkeypatch.setattr(ledger, "status", _status)
    c.calls = calls  # type: ignore[attr-defined]
    return c


class TestHealthPage:
    def test_positive_control_the_page_rendered_with_its_regions(self, client) -> None:
        r = client.get("/report/body")
        assert r.status_code == 200
        for region in ("rules in use", "rules seen again", "open follow-ups", "is it keeping up",
                       "where lessons come from", "what got decided"):
            assert f'aria-label="{region}"' in r.text
        assert 'data-page="report"' in client.get("/report").text  # the shell carries the page kind

    def test_tiles_quote_the_cli_numbers(self, client) -> None:
        text = client.get("/report/body").text
        tiles = re.findall(r'health-tile-label">(.*?)</div>\s*<div class="health-tile-value">(.*?)</div>', text)
        assert tiles == [
            ("Rules in use", "3"),
            ("Waiting for a decision", "2"),
            ("Typical wait", "1 day"),
            ("Rules later corrected", "22"),
        ]
        assert "of 211 put to use, 10%: replaced later by a better rule" in text

    def test_rules_are_listed_by_their_words_not_their_ids(self, client) -> None:
        text = client.get("/report/body").text
        table = text.split('aria-label="rules in use"', 1)[1].split("</table>", 1)[0]
        assert "About to accept an empty result as proof a check passed" in table
        # the id is only the link target, never visible text
        visible = re.sub(r'href="[^"]*"', "", table)
        assert "lrn-" not in visible
        assert 'href="/record/lrn-aaaa0001"' in table
        # a rule with no text says so; an unknown destination shows raw
        assert "A rule with no recorded text" in table and "mystery" in table
        assert "Your instructions" in table and "Warning hook" in table

    def test_most_seen_again_first(self, client) -> None:
        table = client.get("/report/body").text.split('aria-label="rules in use"', 1)[1]
        assert table.index("empty result") < table.index("pkill")

    def test_no_raw_json_and_no_old_machine_headings(self, client) -> None:
        text = client.get("/report/body").text
        assert 'class="raw-report"' not in text and "Raw (verbatim)" not in text
        assert "&#34;routed_live&#34;" not in text and '"routed_live"' not in text
        assert "<pre" not in text

    def test_counters_keep_their_cli_names_with_rates_as_percent(self, client) -> None:
        text = client.get("/report/body").text
        fold = text.split("All counters, with their names", 1)[1]
        assert "<code>routed_ever</code></td><td class=\"num\">211</td>" in fold
        assert "<code>supersede_rate</code></td><td class=\"num\">10.4%</td>" in fold
        assert "<code>mined.accept_rate</code></td><td class=\"num\">55.9%</td>" in fold
        assert "<code>telemetry.events_by_kind.capture</code></td><td class=\"num\">322</td>" in fold
        assert "<code>metrics.pending_over_30d_pct</code></td><td class=\"num\">0%</td>" in fold

    def test_seen_again_groups_sightings_by_rule(self, client) -> None:
        text = client.get("/report/body").text
        sec = text.split('aria-label="rules seen again"', 1)[1].split("</section>", 1)[0]
        assert sec.count("<tr>") == 2  # header + ONE row for two sightings
        assert re.search(r'<td class="num" data-label="Times seen">2</td>', sec)
        assert "A transcript matched the rule&#39;s text" in sec and "A session broke the rule" in sec

    def test_filter_is_server_side(self, client) -> None:
        text = client.get("/report/body", params={"q": "pkill"}).text
        table = text.split('aria-label="rules in use"', 1)[1].split("</table>", 1)[0]
        assert "pkill" in table and "empty result" not in table
        assert "1 of 3 rules match" in text
        none = client.get("/report/body", params={"q": "zzzz"}).text
        assert "No rule matches" in none

    def test_the_filter_text_is_escaped(self, client) -> None:
        text = client.get("/report/body", params={"q": '"><script>x</script>'}).text
        assert "<script>x</script>" not in text

    def test_rows_are_limited_until_show_all(self, client, monkeypatch) -> None:
        from self_learn_ui import ledger

        many = dict(REPORT)
        many["routed_live"] = [
            {**REPORT["routed_live"][0], "id": f"lrn-{i:08x}", "title": f"Rule number {i}", "recurrences": 0}
            for i in range(health.DEFAULT_LIMIT + 7)
        ]
        monkeypatch.setattr(ledger, "report", lambda home: CliRead(data=many))
        text = client.get("/report/body").text
        assert text.count('class="health-rule"') >= health.DEFAULT_LIMIT
        assert f"Show all {health.DEFAULT_LIMIT + 7}" in text
        full = client.get("/report/body", params={"all": "1"}).text
        assert "Rule number %d" % (health.DEFAULT_LIMIT + 6) in full
        assert "Rule number %d" % (health.DEFAULT_LIMIT + 6) not in text
        assert f"Showing all {health.DEFAULT_LIMIT + 7}." in full
        # gate r1 n-5 / r2 n-3: "Showing all" compares the MATCHED count with the limit
        few = client.get("/report/body", params={"all": "1", "q": "number 3"}).text
        assert "rules match" in few and "Showing all" not in few
        # gate r2 n-8: filtering from the "all" view keeps it (a hidden field in the form)
        assert 'name="all" value="1"' in few and 'name="all"' not in text

    def test_a_filter_request_from_the_page_does_not_re_read_the_report(self, client, monkeypatch) -> None:
        """Gate r2 m-1: `report --json` takes about 8 s on the real ledger.
        The page's own htmx filter reuses the reads the page's body made (its
        `/report/body` fetch); a change to the ledger, or the reads growing
        stale, makes the next request read again."""
        from self_learn_ui import routes

        client.get("/report")  # the shell: it reads nothing, its body does
        assert client.calls == {"report": 0, "status": 0}
        client.get("/report/body")
        assert client.calls == {"report": 1, "status": 1}
        hx = {"HX-Request": "true"}
        r = client.get("/report", params={"q": "pkill"}, headers=hx)
        assert "1 of 3 rules match" in r.text
        client.get("/report", params={"all": "1"}, headers=hx)
        assert client.calls == {"report": 1, "status": 1}, "a filter must not re-run the CLI"
        client.app.state.refresh_hub.force_refresh("front")  # the ledger changed
        client.get("/report", params={"q": "pkill"}, headers=hx)
        assert client.calls == {"report": 2, "status": 2}
        monkeypatch.setattr(routes, "_REPORT_CACHE_TTL", 0.0)  # a stale cache is re-read
        client.get("/report", params={"q": "x"}, headers=hx)
        assert client.calls == {"report": 3, "status": 3}

    def test_the_address_after_a_filter_is_the_clean_one(self, client) -> None:
        hx = {"HX-Request": "true"}
        assert client.get("/report", params={"q": ""}, headers=hx).headers["HX-Push-Url"] == "/report"
        assert client.get("/report", params={"q": "a b"}, headers=hx).headers["HX-Push-Url"] == "/report?q=a%20b"
        assert client.get("/report", params={"q": "x", "all": "1"}, headers=hx).headers["HX-Push-Url"] == "/report?all=1&q=x"
        # a plain page load, and a Back/Forward restore, push nothing
        assert "HX-Push-Url" not in client.get("/report", params={"q": "x"}).headers
        restore = {"HX-Request": "true", "HX-History-Restore-Request": "true"}
        assert "HX-Push-Url" not in client.get("/report", params={"q": "x"}, headers=restore).headers

    def test_the_filter_form_shows_a_search_indicator_and_disables_its_button(self, client) -> None:
        text = client.get("/report/body").text
        form = text.split('<form class="health-filter"', 1)[1].split("</form>", 1)[0]
        assert 'hx-disabled-elt="find button"' in form
        assert 'class="health-searching" role="status">Searching' in form
        css = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text()
        assert ".health-filter.htmx-request .health-searching {\n  display: inline;" in css

    def test_every_report_fact_reaches_the_page(self, client) -> None:
        """Gate r1 M-2: nothing the old page printed may be dropped. Every
        top-level key of `report --json` is a counter in the fold under its
        CLI name (the lists of rows as an entry count), and the facts a
        person would look for are also in readable sections."""
        text = client.get("/report/body").text
        fold = text.split("All counters, with their names", 1)[1]
        names = re.findall(r"<code>([^<]+)</code>", fold)
        assert names, "positive control: the counters fold rendered rows"
        for key in REPORT:
            assert any(n == key or n.startswith(key + ".") for n in names), f"report key {key!r} reaches no counter"
        for key in STATUS["metrics"]:
            assert f"metrics.{key}" in names
        for key in STATUS["supply_mix"]:  # gate r2 n-1: the decision row says supply_mix is in the fold
            assert f"supply_mix.{key}" in names
        # an empty dict is a row ("empty"), not a vanished one (gate r2 n-4)
        assert "<code>telemetry.decline_reasons</code></td><td class=\"num\">empty</td>" in fold
        assert "<code>surface_reach.by_destination.hook.unreachable</code></td><td class=\"num\">8</td>" in fold
        assert "<code>context_budget.budget.severity</code></td><td class=\"num\">informational</td>" in fold
        assert "<code>deferred</code></td><td class=\"num\">3 entries</td>" in fold
        assert "<code>reference_shelf.targets</code></td><td class=\"num\">2 entries</td>" in fold

    def test_deferred_lessons_have_readable_rows(self, client) -> None:
        text = client.get("/report/body").text
        sec = text.split('aria-label="put off for later"', 1)[1].split("</section>", 1)[0]
        assert "Put off for later (3)" in sec
        assert "widget" in sec  # the place by its label, not the bucket slug
        assert "-home-me-repos-widget" not in sec
        assert "2 days overdue (overdue)" in sec and "2026-10-30" in sec
        assert 'href="/record/lrn-dddd0001"' in sec
        assert "due in 7 days" in sec
        # the lesson's own words (gate r2 n-7); one whose file is missing says so
        assert ">Putting off the widget cleanup.</a>" in sec
        assert "A lesson (its text could not be read)" in sec
        visible = re.sub(r'href="[^"]*"', "", sec)
        assert "lrn-" not in visible and "Open the lesson" not in sec

    def test_deferred_rows_are_most_overdue_first_and_not_yet_due_last(self, client) -> None:
        sec = client.get("/report/body").text.split('aria-label="put off for later"', 1)[1]
        assert sec.index("31 days overdue") < sec.index("2 days overdue") < sec.index("due in 7 days")

    def test_flagged_checks_name_the_file_in_words(self, client) -> None:
        """Gate r2 m-5: a warning the CLI raised reads with the file it is
        about, not only as a counter that says "yes"."""
        text = client.get("/report/body").text
        budget = text.split('aria-label="instruction file size"', 1)[1].split("</details>", 1)[0]
        assert "2 flagged</summary>" in budget
        assert "widget: most of what self-learn wrote there is warnings; self-learn&#39;s share of the file grew fast this month." in budget
        assert "widget: many rules files are read together (up to 15 at once; the limit is 5)." in budget
        assert "Your instructions: " not in budget.split("What the checks flagged:", 1)[1].split("</ul>", 1)[0]  # the unflagged file is not listed
        assert "pair-by-pair detail behind these is in the command-line report" in budget
        fold = text.split("All counters, with their names", 1)[1]
        assert "the rows themselves are in the command-line report" in fold

    def test_dismissed_sightings_have_readable_rows(self, client) -> None:
        text = client.get("/report/body").text
        sec = text.split('aria-label="dismissed sightings"', 1)[1].split("</details>", 1)[0]
        assert "(2)" in sec
        assert "About to accept an empty result as proof a check passed" in sec  # the rule's words
        assert "A rule that is no longer in use" in sec  # a rule not in use any more
        assert "Not about this rule" in sec and "The rule was followed" in sec
        assert "A session may have broken the rule" in sec
        visible = re.sub(r'href="[^"]*"', "", sec)
        assert "lrn-" not in visible

    def test_reach_budget_places_and_destinations_in_words(self, client) -> None:
        text = client.get("/report/body").text
        reach = text.split('aria-label="reach"', 1)[1].split("</details>", 1)[0]
        assert "Of 163 rules checked: 43 reach a place the assistant reads, 56 do not, and 64 could not be measured." in reach
        assert '<td class="health-rule">Warning hook</td><td class="num" data-label="Reach">0</td><td class="num" data-label="Do not reach">8</td>' in reach
        budget = text.split('aria-label="instruction file size"', 1)[1].split("</details>", 1)[0]
        assert '<td class="health-rule">Your instructions</td><td class="num" data-label="Words">not known</td>' in budget
        assert '<td data-label="State">no file</td>' in budget  # `absent`, in words (gate r2 m-3)
        assert '<td class="health-rule">widget</td><td class="num" data-label="Words">1735</td>' in budget
        assert '<td data-label="State">measured (flagged)</td>' in budget
        assert ">ok<" not in budget and ">absent<" not in budget
        places = text.split('aria-label="lessons by place"', 1)[1].split("</details>", 1)[0]
        assert "3 in use, 1 replaced or retired" in places and "herdr" not in places  # empty places are not listed
        assert 'data-label="Lessons"' in places  # stacked on a phone, like the rules tables
        assert "By kind: 107 instructions files, 42 skills, 8 warning hooks." in text  # plurals (gate r2 n-6)
        assert "13 reference files are tracked. Reads of them are not being counted yet: the counting script is not installed." in text
        assert "script-missing" not in text.split("All counters, with their names", 1)[0]
        assert "Counted on 2026-11-01." in text

    def test_the_two_seen_again_numbers_say_what_each_counts(self, client) -> None:
        text = client.get("/report/body").text
        assert 'title="Times a sighting of this rule was confirmed">Confirmed again</th>' in text
        sec = text.split('aria-label="rules seen again"', 1)[1]
        assert "Rules seen again, not yet decided (1)" in sec
        assert "Times seen</th>" in sec and "that nobody has judged yet" in sec

    def test_a_user_level_hook_does_not_read_as_living_in_the_instructions(self, client) -> None:
        text = client.get("/report/body").text
        table = text.split('aria-label="rules in use"', 1)[1].split("</table>", 1)[0]
        # lrn-aaaa0002 is a hook in the USER bucket, whose label is "Your instructions"
        assert 'Warning hook<span class="health-where">For all your work</span>' in table
        assert 'Warning hook<span class="health-where">Your instructions</span>' not in table
        # a rule in a skill's own bucket names the skill; a user instructions rule is one line
        assert 'mystery<span class="health-where">herdr</span>' in table
        assert '<td data-label="Where"><div>Your instructions</div></td>' in table

    def test_a_failed_cli_shows_its_error_and_no_page_model(self, tmp_path: Path, monkeypatch) -> None:
        sb = make_env(tmp_path)
        app = create_app(env=load_env(sb.env), token=TOKEN, runner=FakeRunner(), start_watcher=False)
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        c.cookies.set("slu_token", TOKEN)
        from self_learn_ui import ledger

        monkeypatch.setattr(ledger, "report", lambda home: CliRead(data=None, error="report failed: boom"))
        monkeypatch.setattr(ledger, "status", lambda home: CliRead(data=None, error="status failed"))
        r = c.get("/report/body")
        assert r.status_code == 200
        assert "report failed: boom" in r.text
        assert "health-tile" not in r.text


class TestHealthModelUnits:
    def test_days_in_words(self) -> None:
        assert [health.days_in_words(x) for x in (0, 1, 99, None)] == ["today", "1 day", "99 days", "not known"]

    def test_user_claude_md_reads_as_one_line(self) -> None:
        assert health.place_words("claude-md", "user", "Your instructions") == ("Your instructions", "")
        assert health.place_words("hook", "skill", "herdr") == ("Warning hook", "herdr")
        assert health.place_words("odd", "skill", "x") == ("odd", "x")

    def test_missing_numbers_are_not_known_never_zero(self) -> None:
        tiles = {t["label"]: t["value"] for t in health.build_health({"routed_live": []}, {}, {}, [])["tiles"]}
        assert tiles["Waiting for a decision"] == "not known"
        assert tiles["Rules later corrected"] == "not known"

    def test_status_failed_typical_wait_is_not_known_not_none_yet(self) -> None:
        # gate r1 m-2: with `status` unreadable the page must not claim no
        # lesson was ever decided
        tiles = {t["label"]: t for t in health.build_health(REPORT, None, None, None)["tiles"]}
        assert tiles["Typical wait"]["value"] == "not known"
        assert "no lesson has been decided" not in tiles["Typical wait"]["note"]
        # a readable status whose metric is None really means none yet
        ok = {t["label"]: t for t in health.build_health(REPORT, {"pending_total": 0}, None, [])["tiles"]}
        assert ok["Typical wait"]["value"] == "none yet"

    def test_a_missing_recurrence_count_is_not_known_not_zero(self) -> None:
        report = {"routed_live": [
            {"id": "lrn-a", "title": "A", "scope": "skill", "bucket": "b", "bucket_label": "b", "destination": "hook", "routed_days_ago": 1},
            {"id": "lrn-b", "title": "B", "scope": "skill", "bucket": "b", "bucket_label": "b", "destination": "hook", "routed_days_ago": 9, "recurrences": 0},
        ]}
        rows = {r["title"]: r for r in health.build_health(report, {}, {}, [])["rules"]}
        assert rows["A"]["seen_words"] == "not known" and rows["B"]["seen_words"] == "0"
        order = [r["title"] for r in health.build_health(report, {}, {}, [])["rules"]]
        assert order == ["B", "A"]  # a known count sorts before an unknown one

    def test_user_level_places_read_as_for_all_your_work(self) -> None:
        assert health.place_words("hook", "user", "Your instructions") == ("Warning hook", "For all your work")
        assert health.place_words("claude-md", "user", "Your instructions") == ("Your instructions", "")


    def test_counts_are_plural_when_they_should_be(self) -> None:
        line = health.build_health({"destinations": {"claude-md": 107, "skill-md": 1, "hook": 8, "new-skill": 1}}, {}, {}, [])["destinations_line"]
        assert line == "By kind: 107 instructions files, 8 warning hooks, 1 skill, 1 new skill."

    def test_an_empty_dict_is_a_counter_row_not_nothing(self) -> None:
        names = dict(health.build_health({"destinations": {}, "telemetry": {"decline_reasons": {}, "captures": 3}}, {}, {}, [])["counters"])
        assert names["destinations"] == "empty"
        assert names["telemetry.decline_reasons"] == "empty" and names["telemetry.captures"] == "3"

    def test_deferred_rows_sort_by_real_overdue_days(self) -> None:
        rows = health.build_health(
            {"deferred": [
                {"id": "a", "bucket": "x", "until": "u", "overdue_days": 1},
                {"id": "b", "bucket": "x", "until": "u", "overdue_days": 31},
                {"id": "c", "bucket": "x", "until": "u", "overdue_days": None},
                {"id": "d", "bucket": "x", "until": "u", "overdue_days": -3},
            ]}, {}, {}, [])["deferred"]
        assert [r["id"] for r in rows] == ["b", "a", "d", "c"]

    def test_state_and_instrument_words_fall_back_to_what_was_sent(self) -> None:
        assert health.STATE_WORDS.get("weird", "weird") == "weird"
        note = health.build_health({"reference_shelf": {"instrumented": False, "instrument_state": "new-state", "targets_total": 2}}, {}, {}, [])["reference_note"]
        assert note.endswith("not being counted yet: new-state.")
