"""Base template skeleton tests (10 §3 task U1 bullet 4)."""

from __future__ import annotations

from pathlib import Path

BASE_HTML = (
    Path(__file__).resolve().parents[1] / "templates" / "base.html"
).read_text(encoding="utf-8")

# Documentation comments in the file legitimately mention the banned
# patterns by name (explaining the rule) — strip HTML comments before
# scanning for actual occurrences of those patterns in markup.
import re as _re  # noqa: E402

BASE_HTML_NO_COMMENTS = _re.sub(r"<!--.*?-->", "", BASE_HTML, flags=_re.S)


def test_base_template_exists_with_expected_blocks() -> None:
    for block in (
        "{% block header %}",
        "{% block status_strip %}",
        "{% block content %}",
        "{% block keymap_footer %}",
        "{% block keymap_json %}",
    ):
        assert block in BASE_HTML, f"missing {block}"


def test_base_template_has_autoescape_marker_comment() -> None:
    assert "AUTOESCAPE MARKER" in BASE_HTML
    assert "autoescape=True" in BASE_HTML


def test_base_template_has_no_inline_style_attributes() -> None:
    assert 'style="' not in BASE_HTML_NO_COMMENTS


def test_base_template_has_no_inline_style_blocks() -> None:
    assert "<style>" not in BASE_HTML_NO_COMMENTS


def test_base_template_has_no_inline_script_blocks() -> None:
    """Only the JSON data blob script tag is allowed — no executable
    inline <script> (CSP: script-src 'self', app.js is vendored)."""
    assert 'src="/static/app.js"' not in BASE_HTML  # not yet wired at U1
    assert "static/htmx-2.0.9.min.js" in BASE_HTML
    assert 'type="application/json"' in BASE_HTML
