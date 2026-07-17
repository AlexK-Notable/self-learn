"""rendering.py — the W-1/W-9 render-path hardening pins. Pure functions,
no filesystem, no FastAPI."""

from __future__ import annotations

from pathlib import Path

from self_learn_ui.rendering import (
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
