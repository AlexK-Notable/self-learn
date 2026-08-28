"""U-papercuts P-4 — on-failure diagnostic capture for Playwright-driven
tests (`conftest.py`'s `_capture_playwright_failure` /
`pytest_runtest_makereport` hookwrapper).

FW-81 (14-forward-work-map.md ~:136): every past episode of the
host-only actionability-timeout intermittency was diagnosed from
nothing but pytest's own one-line failure summary — Playwright's own
diagnostic (the actionability retry log embedded in the exception's
`str()`) was never captured. This file proves the capture function
itself actually writes the three artifacts it claims to on a failure
that touched a `page`-shaped fixture, and that it is a true no-op
(allocates nothing) on a failure that did not.

The first two tests are exercised as direct fixture-level unit tests
against `_capture_playwright_failure`: the function under test takes
plain `item`/`call`-shaped objects (duck typed the same way
`pytest.Item`/`pytest.CallInfo` are) and needs neither a real browser
nor a real server to prove it writes what it says it writes.

A THIRD test (gate r1 M-1) needs the real hookwrapper mechanics, not a
direct call: it proves a fixture whose `__getattr__` raises during the
page-detection loop does not crash the whole run via an INTERNALERROR
(pluggy's escalation of an exception escaping a hookwrapper's `yield`
to a session-level error, rc=3, destroying every other test's result in
the same run — the exact inverse of what this capture mechanism exists
for). That needs pytest's OWN `pytest_runtest_makereport` protocol
actually firing, which only a real (sub-)run exercises — hence
`pytester`, driving a real `runpytest_subprocess()` against a two-test
file, importing the REAL `pytest_runtest_makereport` out of this
package's `conftest.py` so the sub-run exercises the shipped
implementation, not a reimplementation of it.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from conftest import _capture_playwright_failure

# Gate r1 M-1's invariant test needs the `pytester` fixture, which pytest
# does not enable by default (it is not a "top-level conftest.py" -- a
# plain test module's `pytest_plugins` IS the supported place for this,
# unlike a non-root conftest.py, which pytest refuses at collection time).
pytest_plugins = ["pytester"]


class _FakePage:
    """Duck-types exactly the three attributes `_capture_playwright_
    failure` checks for (`.screenshot`, `.url`, `.context`) — nothing
    else about a real Playwright `Page` is needed to exercise the
    capture path."""

    def __init__(self) -> None:
        self.url = "http://fake.example/"
        self.context = object()
        self.screenshot_calls: list[str] = []

    def screenshot(self, path: str) -> None:
        self.screenshot_calls.append(path)
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nFAKE-SCREENSHOT-BYTES")


class _FakeExcInfo:
    """Mirrors the two attributes `_capture_playwright_failure` reads off
    a real `pytest.ExceptionInfo` (`.typename`, `.value`) — verified
    against `_pytest._code.code.ExceptionInfo` directly (both exist,
    `str(.value)` preserves embedded newlines, matching how a real
    Playwright `TimeoutError`'s multi-line retry log survives capture).
    """

    def __init__(self, typename: str, value: BaseException) -> None:
        self.typename = typename
        self.value = value


def _fake_item(tmp_path_factory: pytest.TempPathFactory, funcargs: dict, nodeid: str):
    config = types.SimpleNamespace(_tmp_path_factory=tmp_path_factory)
    return types.SimpleNamespace(funcargs=funcargs, config=config, nodeid=nodeid)


def test_capture_fires_and_writes_three_artifacts_on_page_failure(tmp_path_factory):
    """Positive control (listed first, per this unit's own instruction):
    a failing test that requested a `page`-shaped fixture must produce
    all three artifacts, each with real (non-placeholder) content —
    including the actionability-retry-log line inside `error.txt`, the
    one piece of evidence every past FW-81 episode never captured.

    Mutation that turns this red: replace `_capture_playwright_failure`'s
    body with an unconditional `return None` (equivalently: delete the
    `if page is None: return None` early-exit's ELSE path, i.e. make the
    function always take the "no page" branch) — `out_dir` becomes
    `None` and the very first assertion below fails.
    """
    page = _FakePage()
    item = _fake_item(
        tmp_path_factory,
        funcargs={"server": object(), "page": page},
        nodeid="test_fake.py::test_thing_times_out",
    )
    exc = TimeoutError(
        'Locator.click: Timeout 30000ms exceeded.\n'
        'waiting for locator("#close-pane")\n'
        "  - element is visible, enabled — but not stable"
    )
    call = types.SimpleNamespace(excinfo=_FakeExcInfo("TimeoutError", exc))

    out_dir = _capture_playwright_failure(item, call)  # type: ignore[arg-type]  # SimpleNamespace stands in for pytest.Item/CallInfo (gate r2 N-9)

    assert out_dir is not None
    assert out_dir.is_dir()

    error_text = (out_dir / "error.txt").read_text(encoding="utf-8")
    assert "TimeoutError" in error_text
    assert "not stable" in error_text  # the actionability retry log line

    screenshot = out_dir / "screenshot.png"
    assert screenshot.is_file()
    assert screenshot.stat().st_size > 0
    assert page.screenshot_calls == [str(screenshot)]

    processes_text = (out_dir / "processes.txt").read_text(encoding="utf-8")
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE"):
        assert key in processes_text


def test_capture_is_a_noop_without_a_page_shaped_fixture(tmp_path_factory):
    """Negative control: a failing test whose funcargs carry nothing
    `page`-shaped (the ordinary case for the other ~1200 UI tests) must
    NOT allocate a capture directory at all — proves the hook is a true
    no-op on every non-Playwright failure, not merely "returns something
    that happens to be empty".

    Mutation that turns this red: remove the `if page is None: return
    None` early exit (or weaken the duck-type check so an unrelated
    fixture value matches it) — every failing test in the whole UI suite
    would start allocating a `pwfail-*` tmp directory, and the `before
    == after` directory-listing assertion below would fail.
    """
    item = _fake_item(
        tmp_path_factory,
        funcargs={"tmp_path": tmp_path_factory.mktemp("unrelated")},
        nodeid="test_fake.py::test_unrelated_failure",
    )
    call = types.SimpleNamespace(
        excinfo=_FakeExcInfo("AssertionError", AssertionError("nope"))
    )

    before = sorted(p.name for p in tmp_path_factory.getbasetemp().iterdir())
    out_dir = _capture_playwright_failure(item, call)  # type: ignore[arg-type]  # SimpleNamespace stands in for pytest.Item/CallInfo (gate r2 N-9)
    after = sorted(p.name for p in tmp_path_factory.getbasetemp().iterdir())

    assert out_dir is None
    assert before == after


def test_page_detection_survives_a_raising_fixture_getattr(pytester: pytest.Pytester) -> None:
    """Gate r1 M-1's invariant: a fixture whose ``__getattr__`` raises
    (simulating a duck-type probe hitting a fixture that explodes on any
    attribute access -- a broken lazy property, a closed resource proxy,
    anything) must still report as ONE ordinary test failure, with every
    OTHER test's result in the same run intact. Before the M-1 fix, the
    (then-unguarded) ``hasattr(value, "screenshot")`` probe inside
    ``_capture_playwright_failure``'s page-detection loop would call
    this fixture's ``__getattr__``, which raises; that exception escaped
    the function, escaped the ``pytest_runtest_makereport`` hookwrapper's
    ``yield``, and pluggy turned it into a session-level
    ``INTERNALERROR`` (rc=3) -- destroying every result in the run, not
    just the one test that used the exploding fixture.

    Drives the REAL shipped hook (imported out of this package's
    ``conftest.py`` into the pytester sub-run's own generated conftest,
    under a private module name to avoid a `conftest`-vs-`conftest`
    self-import collision) against a real ``runpytest_subprocess()``, so
    this exercises pytest's actual ``pytest_runtest_makereport``
    protocol, not a direct call to the function (that is what the two
    tests above already cover).

    Mutation that turns this red: remove the M-1 guard -- the
    ``try/except Exception`` around the detection loop (measured by gate
    r2: only that one reddens; reverting
    ``getattr(item, "funcargs", None) or {}`` back to plain
    ``item.funcargs`` alone stays green because the same except catches the
    AttributeError -- the getattr is belt-and-braces against a non-Function item,
    not independently covered)
    ``item.funcargs`` -- and the sub-run internal-errors instead of
    reporting ``1 passed, 1 failed``: ``result.assert_outcomes(passed=1,
    failed=1, errors=0)`` fails outright (an internal-errored run does
    not print a normal outcome summary line for ``parseoutcomes()`` to
    match), and the ``INTERNALERROR`` string shows up in the captured
    output.
    """
    real_conftest_path = str(Path(__file__).parent / "conftest.py")
    pytester.makeconftest(
        f"""
        import importlib.util

        _spec = importlib.util.spec_from_file_location(
            "_real_ui_conftest_under_test_m1", {real_conftest_path!r}
        )
        _real = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real)

        # Re-export the REAL hookwrapper under its hook-spec name so
        # THIS sub-run's own (generated) conftest.py registers it as a
        # plugin, exactly as the real ui suite's conftest.py does.
        pytest_runtest_makereport = _real.pytest_runtest_makereport
        """
    )
    pytester.makepyfile(
        test_exploding_fixture="""
        import pytest

        class _Exploding:
            def __getattr__(self, name):
                raise RuntimeError("simulated exploding fixture attribute access")

        @pytest.fixture
        def boom():
            return _Exploding()

        def test_uses_exploding_fixture_and_fails(boom):
            assert False, "deliberate failure -- exercises pytest_runtest_makereport"

        def test_ordinary_pass():
            assert True
        """
    )

    result = pytester.runpytest_subprocess()

    combined = "\n".join(result.outlines + result.errlines)
    assert "INTERNALERROR" not in combined, combined
    result.assert_outcomes(passed=1, failed=1, errors=0)
