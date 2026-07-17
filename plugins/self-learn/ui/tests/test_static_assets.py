"""Static asset tests (10 §1 Dependencies row; verify-at-build ledger:
"htmx vendored file sha256 matches the recorded release hash")."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
HTMX_PATH = STATIC_DIR / "htmx-2.0.9.min.js"

#: Independently verified 2026-07-17 against BOTH unpkg.com and
#: cdn.jsdelivr.net mirrors of htmx.org@2.0.9/dist/htmx.min.js (identical
#: bytes on both) — recorded in the file's own header comment too.
EXPECTED_HTMX_SHA256 = (
    "57d9191515339922bd1356d7b2d80b1ee3b29f1b3a2c65a078bb8b2e8fd9ae5f"
)

_HEADER_SHA_RE = re.compile(r"sha256:\s*([0-9a-f]{64})")


def test_htmx_file_exists() -> None:
    assert HTMX_PATH.is_file()


def test_htmx_header_records_the_correct_sha256() -> None:
    text = HTMX_PATH.read_text(encoding="utf-8")
    first_line = text.splitlines()[0]
    match = _HEADER_SHA_RE.search(first_line)
    assert match, "header comment line must record a sha256:<hex> hash"
    assert match.group(1) == EXPECTED_HTMX_SHA256


def test_htmx_content_hash_matches_the_recorded_hash() -> None:
    """The recorded hash is of the RELEASE content — i.e. everything
    after the header comment line we added — not of the file-with-header
    as a whole."""
    text = HTMX_PATH.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    body = "".join(lines[1:])  # drop our header comment line
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert digest == EXPECTED_HTMX_SHA256


def test_htmx_content_looks_like_htmx() -> None:
    text = HTMX_PATH.read_text(encoding="utf-8")
    assert "htmx" in text[:200].lower()
    assert "function" in text


def test_app_js_exists_and_has_keydown_and_eventsource_stubs() -> None:
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "keydown" in app_js
    assert "EventSource" in app_js


def test_app_js_has_column_sort_handler() -> None:
    """Feedback round 1 item 1: the Front table's client-side sort lives
    here (CSP: no inline JS anywhere else to put it)."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "data-sort-key" in app_js
    assert "aria-sort" in app_js


def test_style_css_filters_keymap_footer_by_context() -> None:
    """Feedback round 1 item 4: only the current page's usable keys show
    in the footer — driven by body[data-page] + :has(), zero JS."""
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert '.keymap-footer-entry[data-context="global"]' in css
    assert 'body[data-page="front"]' in css
    assert 'body:has(.pane-region[data-pane-state])' in css


def test_style_css_has_prefers_color_scheme_block() -> None:
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert "--slu-bg" in css  # a custom-property token is actually defined


def test_no_inline_style_attributes_in_style_css_comment_examples() -> None:
    """Not a template check (there's no rendered HTML yet at U1) — just
    guards that this file doesn't itself demonstrate the banned pattern
    it documents."""
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert 'style="' not in css
