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


def test_app_js_reload_chokepoint_defers_on_the_three_leg_predicate() -> None:
    """Y-16 (U14): the reload-defer is browser-level behavior proven at
    the live re-trial; what is pinnable headless is the STRUCTURE — one
    reload() chokepoint whose defer predicate names all three legs, an
    unconditional in-flight release on error/abort (the F14 fold), and
    no reload path bypassing the chokepoint."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # Leg (a): the error-rendering marker.
    assert "[data-verb-error]" in app_js
    # Leg (b): the confirm-in-flight flag, set at request start…
    assert "confirmInFlight" in app_js
    assert "htmx:beforeRequest" in app_js
    # …cleared at swap settle AND on the no-swap failure legs (F14).
    assert "htmx:afterSettle" in app_js
    for event in (
        "htmx:responseError",
        "htmx:swapError",
        "htmx:sendError",
        "htmx:sendAbort",
        "htmx:timeout",
    ):
        assert event in app_js, f"missing unconditional-release event {event}"
    # Leg (c): any armed bar (findArmedBar inside the predicate).
    assert "reloadDeferred" in app_js
    # Deferred, never dropped:
    assert "reloadPending" in app_js
    # The chokepoint is the ONLY caller of window.location.reload() —
    # every present and future reload path is covered structurally (F3).
    assert app_js.count("window.location.reload()") == 1


def test_app_js_auto_selects_first_row_and_guards_content_focus() -> None:
    """09 §11 Y-19 item 3 (survey P1a): the JS half of "first actionable
    row selected on load, keys live without a prior click" is browser
    behavior — this pins the STRUCTURE (the DoD's live-trial line covers
    the actual visible cursor + keypress). One DOMContentLoaded hook
    drives both the selection and the focus guard; the focus guard must
    read document.activeElement before acting (never steal focus
    unconditionally) — that guard is what keeps this item from breaking
    the pane-input / armed-bar focus behaviors it must not fight."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function ensureRowSelected" in app_js
    assert "function ensureContentFocus" in app_js
    assert "DOMContentLoaded" in app_js
    assert "self-learn-ui-content" in app_js
    # The steal-nothing guard: only acts when nothing else already holds
    # focus on purpose.
    assert "document.activeElement" in app_js
    assert "ensureRowSelected();" in app_js
    assert "ensureContentFocus();" in app_js


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
