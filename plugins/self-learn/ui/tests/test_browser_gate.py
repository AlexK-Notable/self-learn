"""U-browserfail: guard-of-the-guard for `conftest.py`'s
`_browser_gate`/`_browser_or_sentinel`/`_no_browser_banner` -- proves the
absent-browser-is-a-FAILURE mechanism actually fires (a committed test
asserting only that the fixtures exist would pass even with a one-line
revert back to the old `pytest.skip(...)` behaviour this whole unit
exists to retire).

Every probe below drives a REAL, isolated pytest sub-session via
`pytester.runpytest_subprocess()`, with a GENERATED conftest.py that
splices the REAL `conftest.py`'s `_browser_gate`/`_browser_or_sentinel`/
`_no_browser_banner` in by absolute path (`importlib.util.spec_from_
file_location`, the same pattern `test_litter_guard_probes.py`'s
`_make_probe_conftest` already uses in this package) and defines local
`browser`/`page` fixtures around them, matching the SHAPE every real
Playwright-driven test module in this package already uses
(`browser.new_context() -> context.new_page() -> page`). Each sub-run
therefore exercises the SHIPPED implementation, never a
reimplementation of it.

Three probes, in the order the unit's own report lists them:

  (a) POSITIVE CONTROL, listed first per this package's own convention
      (`test_pw_failure_capture.py`'s docstring): with a REAL browser
      reachable (`PLAYWRIGHT_BROWSERS_PATH` pointed at this HOST's real
      `~/.cache/ms-playwright`, set explicitly on the sub-run's env --
      never relying on ambient inheritance), a test that touches `page`
      RUNS and PASSES -- not skipped. Asserts on the report
      (`result.assert_outcomes`), never on a flag.

  (b) ABSENCE: `PLAYWRIGHT_BROWSERS_PATH` pointed at a real, EMPTY tmp
      directory -- a genuine `BrowserType.launch: Executable doesn't
      exist at ...` failure from Playwright itself, no monkeypatch of
      the launch call needed (stronger evidence than simulating the
      exception by hand: this is the REAL discovery-and-launch path a
      production run would hit). A test that touches `page` FAILS
      (`report.when == "call"`, pytest's "F" bucket), naming the missing
      executable path and the exact fix command. A SECOND, ordinary test
      in the SAME sub-run passes -- proving a missing browser fails only
      the tests that need one, never crashes the whole session (an
      operator sees "N failed, M passed", not a collection crash).

  (c) ESCAPE HATCH: `SELF_LEARN_UI_NO_BROWSER=1` set (browser
      availability irrelevant -- the hatch is unconditional, see
      `_browser_or_sentinel`'s own docstring). The browser test SKIPS
      (not fails), and the loud session-start banner
      (`_no_browser_banner`) is present in the `-q` output -- settling
      empirically, not by inspection, whether `terminalreporter.
      write_line` really does survive `-q` capture.

Mutation, verified by hand during this unit's build (not itself
committed -- applied, all three probes re-run to confirm RED, then
reverted): reverting `browser`/`_UnavailableBrowser` to the ORIGINAL
`pytest.skip(f"Chromium unavailable for Playwright: {exc}")` body turns
(a) unaffected (browser still present, still passes), (b) RED
(`result.assert_outcomes(passed=1, failed=1, ...)` fails -- the browser
test now SKIPS instead of FAILS, so `failed=0` and `skipped=1`), and (c)
unaffected (still skips, just via the old message -- the banner
assertion is what would need updating, since the OLD code prints
nothing at session start regardless of any env var, so a probe built
against the OLD code would never assert the banner text at all). Each
probe below is written to fail specifically on the property the old
code lacked, which is what makes (b) the one that actually reddens on
that revert.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Gate/precedent: `pytester` is not enabled by default; a plain test
# module's `pytest_plugins` IS the supported activation point (mirrors
# `test_litter_guard_probes.py`/`test_pw_failure_capture.py`, same repo).
pytest_plugins = ["pytester"]

_REAL_CONFTEST = Path(__file__).resolve().parent / "conftest.py"

#: This HOST's real Playwright browsers root -- confirmed by this same
#: build session (`uv run pytest tests/test_js_dom.py tests/test_js_dom_
#: targeting.py tests/test_js_dom_pane_persistence.py`, unmodified env,
#: all 136 real browser tests passed) to hold the Chromium build
#: Playwright 1.61.0 (this package's pinned version) actually needs.
_REAL_BROWSERS_PATH = Path.home() / ".cache" / "ms-playwright"

_FIX_COMMAND = "uv run playwright install chromium-headless-shell"


def _make_probe_conftest(pytester: pytest.Pytester) -> None:
    """Splices the REAL `conftest.py`'s `_browser_gate`/`_browser_or_
    sentinel`/`_no_browser_banner` into the sub-run's own generated
    conftest.py, and defines local `browser`/`page` fixtures around
    them in the SAME shape every real Playwright-driven module in this
    package uses -- so each probe below exercises the SHIPPED
    `_browser_gate`/`_browser_or_sentinel`, never a reimplementation."""
    pytester.makeconftest(
        f"""
        import importlib.util

        import pytest

        _spec = importlib.util.spec_from_file_location(
            "_real_conftest_under_test_browserfail", {str(_REAL_CONFTEST)!r}
        )
        _real = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real)

        _browser_gate = _real._browser_gate
        _browser_or_sentinel = _real._browser_or_sentinel
        _no_browser_banner = _real._no_browser_banner
        _UnavailableBrowser = _real._UnavailableBrowser

        @pytest.fixture(scope="module")
        def browser(_browser_gate):
            yield from _browser_or_sentinel(_browser_gate)

        @pytest.fixture
        def page(browser):
            context = browser.new_context()
            pg = context.new_page()
            try:
                yield pg
            finally:
                context.close()
        """
    )


# ------------------------------------------------------------- Probe A
# (positive control, listed first)


def test_probe_a_real_browser_runs_not_skips(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) With a REAL browser reachable, a test that touches `page`
    RUNS and PASSES -- never skipped, never a poison pill. Asserts on
    the REPORT (`result.assert_outcomes`), not on a flag.

    Inverse edit that reddens this one: make `_browser_or_sentinel`
    unconditionally yield `_UnavailableBrowser(...)` (skip the
    `gate.available` branch entirely) -- the browser IS present here, so
    this probe would flip from `passed=1` to `failed=1`, the one shape
    this specific probe is built to catch (a false "unavailable"
    verdict when a browser genuinely is there).
    """
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(_REAL_BROWSERS_PATH))
    monkeypatch.delenv("SELF_LEARN_UI_NO_BROWSER", raising=False)

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe="""
        def test_uses_browser(page):
            # No network needed -- proves the BROWSER launched and a
            # real page exists, nothing about this host's connectivity.
            page.set_content("<html><body>ok</body></html>")
            assert page.title() == ""
        """
    )
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1, failed=0, skipped=0, errors=0)
    combined = "\n".join(result.outlines + result.errlines)
    assert "1 passed" in combined, combined


# ------------------------------------------------------------- Probe B


def test_probe_b_absent_browser_fails_naming_path_and_fix(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) `PLAYWRIGHT_BROWSERS_PATH` points at a real, EMPTY directory
    -- Playwright's OWN launch attempt genuinely fails with `Executable
    doesn't exist at ...` (no monkeypatch of the launch call: this is
    the real discovery-and-launch path, strictly more honest evidence
    than simulating the exception by hand). The browser-dependent test
    FAILS (not skipped, not erroring the session), naming the missing
    executable path and the exact fix command; a SECOND, ordinary test
    in the SAME sub-run still passes, proving this never crashes the
    whole session.

    Inverse edit that reddens this one: revert `browser`'s body (in
    each of `test_js_dom.py`/`test_js_dom_targeting.py`/`test_js_dom_
    pane_persistence.py`, or equivalently `_browser_or_sentinel` itself)
    to the ORIGINAL `pytest.skip(f"Chromium unavailable for Playwright:
    {exc}")` -- `result.assert_outcomes(passed=2, failed=0, ...)` would
    then need `skipped=1` instead, so THIS assertion (`failed=1,
    skipped=0`) fails first.
    """
    empty_browsers_dir = tmp_path / "empty-browsers-dir"
    empty_browsers_dir.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(empty_browsers_dir))
    monkeypatch.delenv("SELF_LEARN_UI_NO_BROWSER", raising=False)

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe="""
        def test_uses_browser(page):
            page.set_content("<html></html>")

        def test_unrelated_still_runs():
            assert 1 + 1 == 2
        """
    )
    result = pytester.runpytest_subprocess()
    # Outcome counts alone already pin "one test fails, the OTHER one
    # passes" (see docstring) -- no need for a message-text fallback
    # here; that would just make this assertion satisfiable by output
    # shapes unrelated to which specific test passed.
    result.assert_outcomes(passed=1, failed=1, skipped=0, errors=0)
    combined = "\n".join(result.outlines + result.errlines)
    assert "Executable doesn't exist at" in combined, combined
    assert str(empty_browsers_dir) in combined, combined
    assert _FIX_COMMAND in combined, combined
    assert "SELF_LEARN_UI_NO_BROWSER" in combined, combined


# ------------------------------------------------------------- Probe C


def test_probe_c_escape_hatch_skips_with_loud_banner(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) `SELF_LEARN_UI_NO_BROWSER=1` -- unconditional (browser
    availability is irrelevant here on purpose: an empty
    `PLAYWRIGHT_BROWSERS_PATH` dir is used anyway, so this probe cannot
    accidentally pass just because a real browser happened to be
    reachable). The browser test SKIPS (not fails), and one loud banner
    line appears in the SESSION-START output -- run under `-q`
    (matching this package's own suite-running convention), settling
    EMPIRICALLY whether `terminalreporter.write_line` really survives
    `-q` capture, rather than trusting the by-inspection claim in
    `_no_browser_banner`'s own docstring.

    Inverse edit that reddens this one: delete the
    `if not _no_browser_requested(): return` early-return's ELSE path in
    `_no_browser_banner` (i.e. make the function always return
    immediately, unconditionally) -- the banner text disappears from
    `combined` and the second assertion below fails, while the skip
    itself (handled separately, inside `_browser_or_sentinel`) still
    passes, isolating the banner as the thing this probe actually
    exercises.
    """
    empty_browsers_dir = tmp_path / "empty-browsers-dir"
    empty_browsers_dir.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(empty_browsers_dir))
    monkeypatch.setenv("SELF_LEARN_UI_NO_BROWSER", "1")

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe="""
        def test_uses_browser(page):
            page.set_content("<html></html>")
        """
    )
    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=0, failed=0, skipped=1, errors=0)
    combined = "\n".join(result.outlines + result.errlines)
    assert "SELF_LEARN_UI_NO_BROWSER is set" in combined, combined
    assert "skipping every" in combined, combined
