"""rendering.py — the W-1/W-9 render-path hardening pins. Pure functions,
no filesystem, no FastAPI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from self_learn_ui.rendering import (
    humanize_ts,
    pygments_stylesheet,
    render_bash,
    render_diff,
    render_markdown,
    render_yaml,
)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


class TestMarkdownHtmlFalse:
    def test_script_tag_is_escaped_not_executed(self) -> None:
        html = render_markdown("<script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_img_onerror_payload_is_escaped(self) -> None:
        html = render_markdown('<img src=x onerror="alert(1)">')
        assert "<img" not in html
        assert "&lt;img" in html

    def test_ordinary_markdown_still_renders(self) -> None:
        html = render_markdown("hello **world**")
        assert "<strong>world</strong>" in html

    def test_empty_and_none_safe(self) -> None:
        assert render_markdown("") == ""
        assert render_markdown(None) == ""  # type: ignore[arg-type]


class TestPygmentsClassMode:
    def test_diff_render_has_no_inline_style_attribute(self) -> None:
        html = render_diff("--- a\n+++ b\n-old\n+new\n")
        assert 'style="' not in html
        assert "highlight" in html  # the served CSS class

    def test_yaml_render_has_no_inline_style_attribute(self) -> None:
        html = render_yaml("destination: skill-md\nrationale: x\n")
        assert 'style="' not in html

    def test_bash_render_has_no_inline_style_attribute(self) -> None:
        html = render_bash("#!/usr/bin/env bash\necho hi\n")
        assert 'style="' not in html

    def test_diff_content_escaped_when_containing_html(self) -> None:
        html = render_diff("+<script>alert(1)</script>\n")
        assert "<script>" not in html


class TestPygmentsStylesheet:
    def test_stylesheet_nonempty_and_has_no_inline_style_marker(self) -> None:
        css = pygments_stylesheet()
        assert css.strip()
        assert 'style="' not in css

    def test_served_stylesheet_file_matches_generator(self) -> None:
        served = (STATIC_DIR / "pygments.css").read_text(encoding="utf-8")
        assert served == pygments_stylesheet()


class TestHumanizeTs:
    """F5-6 (feedback round 5, U19 §1.4): the pinned bucket boundaries,
    each exercised right at its edge, plus the garbage/empty/future
    passthrough legs. `now` is a fixed reference so these never flake."""

    NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)

    def _iso(self, **delta) -> str:
        dt = self.NOW - timedelta(**delta)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_just_now_under_90_seconds(self) -> None:
        html = humanize_ts(self._iso(seconds=89), now=self.NOW)
        assert ">just now<" in html

    def test_one_minute_ago_at_90_seconds(self) -> None:
        html = humanize_ts(self._iso(seconds=90), now=self.NOW)
        assert ">1 minute ago<" in html

    def test_minutes_ago_plural(self) -> None:
        html = humanize_ts(self._iso(minutes=5), now=self.NOW)
        assert ">5 minutes ago<" in html

    def test_one_hour_ago_at_60_minutes(self) -> None:
        html = humanize_ts(self._iso(minutes=60), now=self.NOW)
        assert ">1 hour ago<" in html

    def test_hours_ago_plural(self) -> None:
        html = humanize_ts(self._iso(hours=5), now=self.NOW)
        assert ">5 hours ago<" in html

    def test_yesterday_at_24_hours(self) -> None:
        html = humanize_ts(self._iso(hours=24), now=self.NOW)
        assert ">yesterday<" in html

    def test_days_ago(self) -> None:
        html = humanize_ts(self._iso(days=5), now=self.NOW)
        assert ">5 days ago<" in html

    def test_days_ago_upper_edge_at_13_days(self) -> None:
        html = humanize_ts(self._iso(days=13), now=self.NOW)
        assert ">13 days ago<" in html

    def test_month_day_at_14_days_current_year(self) -> None:
        html = humanize_ts(self._iso(days=14), now=self.NOW)
        assert ">Jul 05<" in html

    def test_month_day_year_for_a_prior_year(self) -> None:
        html = humanize_ts("2025-01-15T00:00:00Z", now=self.NOW)
        assert ">Jan 15, 2025<" in html

    def test_title_attribute_carries_the_full_iso_string(self) -> None:
        html = humanize_ts(self._iso(days=5), now=self.NOW)
        assert f'title="{self._iso(days=5)}"' in html

    def test_garbage_input_renders_verbatim_never_crashes(self) -> None:
        html = humanize_ts("not-a-timestamp-at-all", now=self.NOW)
        assert ">not-a-timestamp-at-all<" in html

    def test_future_timestamp_uses_direction_neutral_absolute_date(self) -> None:
        """unblocks_on is routinely a future instant — past-tense "ago"/
        "yesterday" wording would lie about direction, so a future value
        always renders the same absolute-date form the >=14-day past
        bucket uses, regardless of how near it is."""
        future = (self.NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        html = humanize_ts(future, now=self.NOW)
        assert ">Jul 20<" in html
        assert "ago" not in html

    def test_future_timestamp_next_year_carries_year(self) -> None:
        html = humanize_ts("2027-01-15T00:00:00Z", now=self.NOW)
        assert ">Jan 15, 2027<" in html

    def test_empty_and_none_never_blank_crash_but_render_empty(self) -> None:
        assert humanize_ts("", now=self.NOW) == ""
        assert humanize_ts(None, now=self.NOW) == ""

    def test_html_in_garbage_is_escaped(self) -> None:
        html = humanize_ts("<script>alert(1)</script>", now=self.NOW)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
