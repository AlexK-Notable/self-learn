"""Shared fixtures (10 §0 rules 7/8: tests never touch the real ledger,
``~/.claude``, real cache, real runtime dir, or the network)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _redirect_env_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autouse cache/env isolation for EVERY UI test (spec:
    ui-test-cache-isolation-spec.md r2 §3.1). Measured cause: without
    this, every UI test that resolves ``self_learn.worker.cache_dir()``
    (directly or transitively — e.g. via ``self_learn_ui.middleware``'s
    token-path fallback or ``self_learn_ui.uilog``) writes a fresh
    ``home-<digest>`` directory into the developer's REAL
    ``~/.cache/self-learn`` as a side effect of merely resolving a path
    (``worker.py`` ``mkdir``s at path-resolution time). Measured leak:
    exactly 176 stray directories per full UI suite run before this
    fixture existed. Mirrors ``cli/tests/conftest.py``'s
    ``_worker_test_defaults`` in intent, adapted to this package (the UI
    package additionally needs ``XDG_RUNTIME_DIR`` for the UI token file
    and doesn't need ``SELF_LEARN_COALESCE_SECS``).

    A future reader deleting this fixture should know it costs: the real
    ``~/.cache/self-learn``, the real ``~/.self-learn`` ledger, the real
    ``~/.claude`` dir, and the real ``~/.claude/projects`` transcripts
    tree all go back to being reachable by every test in this package.

    Ordering / naming (spec §3.1 constraints, verify-don't-assume): this
    fixture is autouse, so pytest instantiates it before the explicitly
    requested ``redirected_xdg`` fixture below when a test asks for both
    — ``redirected_xdg``'s ``setenv`` calls run second and win, so
    ``tests/test_cache_path.py`` (its one consumer) is unaffected. Its
    subdirectory names (``default-*``) are deliberately distinct from
    ``redirected_xdg``'s (``cache``, ``runtime``, ``ledger-home``) even
    though both fixtures share the same ``tmp_path`` — identical names
    would make that ordering claim untestable.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "default-cache"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "default-runtime"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "default-home"))
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(tmp_path / "default-claude"))
    monkeypatch.setenv(
        "SELF_LEARN_TRANSCRIPTS_DIR", str(tmp_path / "default-transcripts")
    )
    # No detached worker/miner spawns from the suite (mirrors the CLI
    # fixture's SELF_LEARN_WORKER_AUTOKICK; the UI package also has a
    # miner-side autokick knob the CLI fixture doesn't need to touch).
    monkeypatch.setenv("SELF_LEARN_WORKER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")


@pytest.fixture
def redirected_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect every XDG/home var this package or its cli dependency
    could resolve, to throwaway dirs under ``tmp_path``. Returns the
    redirected paths so a test can assert against them directly.
    """
    cache_home = tmp_path / "cache"
    runtime_dir = tmp_path / "runtime"
    ledger_home = tmp_path / "ledger-home"
    cache_home.mkdir()
    runtime_dir.mkdir()
    ledger_home.mkdir()

    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("SELF_LEARN_HOME", str(ledger_home))

    return {
        "cache_home": cache_home,
        "runtime_dir": runtime_dir,
        "ledger_home": ledger_home,
    }


@pytest.fixture(autouse=True)
def _client_contexts():
    """Arms support.CLIENT_STACK (Y-15: entered TestClients — one
    persistent loop per test so background pane drains survive across
    requests; exited/cleaned at test end)."""
    import contextlib

    import support

    with contextlib.ExitStack() as stack:
        support.CLIENT_STACK = stack
        yield
    support.CLIENT_STACK = None


# ------------------------------------------------------- P-4 (U-papercuts):
# on-failure diagnostic capture for Playwright-driven tests.
#
# FW-81 (14-forward-work-map.md ~:136): every past episode of the
# host-only actionability-timeout intermittency (`Locator.click: Timeout
# 30000ms`) was diagnosed after the fact from nothing but pytest's own
# one-line summary -- Playwright's OWN diagnostic (the actionability
# retry log embedded in the exception's message: "waiting for locator...
# element is visible, enabled... but not stable" etc.) was never
# captured, because it lives only in the exception object at the moment
# of failure and pytest does not print it by default. This hook captures
# it, plus a screenshot and a host process snapshot, for the NEXT
# recurrence -- it changes nothing about pass behaviour, timeouts, or
# retry logic for any test.


def _capture_playwright_failure(item: pytest.Item, call: pytest.CallInfo) -> Path | None:
    """Fires ONLY for a failing test that requested a Playwright
    ``Page``-shaped fixture -- duck-typed via ``.screenshot``/``.url``/
    ``.context`` rather than a hardcoded fixture name, because the two
    FW-81 files alone name four: ``page``, ``noop_page``, ``holding_page``,
    ``f2_page`` (test_js_dom.py) and ``page`` (test_js_dom_pane_
    persistence.py) -- a future fixture under any other name is still
    caught. Every OTHER test's failure path (no such fixture present) is
    byte-identical to before this function existed: it returns ``None``
    immediately and touches nothing.

    Writes three artifacts to a fresh directory under pytest's own
    ``tmp_path_factory`` basetemp (``item.config._tmp_path_factory`` --
    the exact instance the built-in ``tmp_path``/``tmp_path_factory``
    fixtures already share, per ``_pytest/tmpdir.py``'s own
    ``tmp_path_factory`` fixture, so failure artifacts land under the
    SAME ``pytest-of-<user>/pytest-<N>/`` run directory as everything
    else, not a second parallel temp tree):

    1. ``error.txt`` -- the exception type name and ``str(value)``,
       which for a Playwright ``TimeoutError`` INCLUDES the actionability
       retry log (never captured by any past FW-81 episode).
    2. ``screenshot.png`` -- ``page.screenshot()`` at the moment of
       failure.
    3. ``processes.txt`` -- ``ps -eo pid,ppid,etime,args`` ALREADY
       filtered to matched lines only (``chrom|playwright|headless``,
       never the raw host-wide process table), plus ``WAYLAND_DISPLAY``/
       ``DISPLAY``/``XDG_SESSION_TYPE`` (the 2026-08-27 recurrence found
       orphaned ``playwright-mcp --headless --isolated`` processes on the
       host during the failure window, from earlier UI-walk runs --
       untested as a cause; this is what would let a future session
       actually test that hypothesis instead of re-guessing it). Gate r1
       N-4: this file is written under pytest's own tmp basetemp (a
       LOCAL, uncommitted path, per-run and never version-controlled),
       never anywhere inside the repo working tree.

    Gate r1 M-1: the page-DETECTION step (the loop over ``item.funcargs``
    above, before any of the three capture steps run) is ALSO guarded,
    not merely the three capture steps that follow it -- a fixture whose
    ``__getattr__``/``__getattribute__`` raises (any exception, not only
    ``AttributeError``) would otherwise escape this function, escape the
    ``pytest_runtest_makereport`` hookwrapper's ``yield``, and become an
    ``INTERNALERROR`` that pluggy escalates to a session-level error
    (rc=3) -- destroying every result in the run, the exact inverse of
    what this function exists to do, in a conftest.py shared by the
    whole suite. Every capture step AFTER detection is independently
    try/except-guarded too (a closed browser context, a `ps` binary that
    is momentarily unavailable, a read-only tmp filesystem) so a
    capture-side failure NEVER masks or replaces the original test
    failure -- worst case, a ``*.CAPTURE_FAILED`` sibling file records
    what the capture step itself hit. The whole function, detection
    included, is best-effort: its return value (the directory, or
    ``None``) is informational only and is never raised.
    """
    page = None
    try:
        funcargs = getattr(item, "funcargs", None) or {}
        for value in funcargs.values():
            if (
                hasattr(value, "screenshot")
                and callable(getattr(value, "screenshot", None))
                and hasattr(value, "url")
                and hasattr(value, "context")
            ):
                page = value
                break
    except Exception:
        # Gate r1 M-1: a fixture whose `__getattr__`/`__getattribute__`
        # raises (any exception, not just AttributeError -- a custom
        # `__getattr__` can raise whatever it wants) must not escape this
        # detection loop. Measured on the shipped code before this guard:
        # ONE such fixture turned a single ordinary test failure into an
        # INTERNALERROR from this hookwrapper's `yield` -- pluggy
        # escalates that to a session-level error (rc=3) and destroys
        # every result in the run, the exact inverse of what this
        # function exists to do, in a conftest.py shared by the whole
        # suite. `hasattr()` itself calls `getattr()` under the hood and
        # is exactly as exposed as a direct attribute access.
        return None
    if page is None:
        return None

    try:
        tmp_path_factory = item.config._tmp_path_factory  # type: ignore[attr-defined]
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.nodeid).strip("_")[-150:] or "test"
        out_dir = tmp_path_factory.mktemp(f"pwfail-{safe_name}", numbered=True)
    except Exception:
        # Cannot even allocate the capture directory -- nothing to do.
        return None

    # (1) the full Playwright error text, including its actionability
    # retry log.
    try:
        excinfo = call.excinfo
        if excinfo is not None:
            text = f"{excinfo.typename}: {excinfo.value}\n"
        else:
            text = "(no exception info available on this CallInfo)\n"
        (out_dir / "error.txt").write_text(text, encoding="utf-8")
    except Exception as exc:  # pragma: no cover - best-effort, never masks the real failure
        try:
            (out_dir / "error.txt.CAPTURE_FAILED").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass

    # (2) a screenshot of the page at the moment of failure.
    try:
        page.screenshot(path=str(out_dir / "screenshot.png"))
    except Exception as exc:  # pragma: no cover - best-effort
        try:
            (out_dir / "screenshot.png.CAPTURE_FAILED").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass

    # (3) a process snapshot + the display/session env.
    try:
        ps = subprocess.run(
            ["ps", "-eo", "pid,ppid,etime,args"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        lines = [
            ln
            for ln in ps.stdout.splitlines()
            if re.search(r"chrom|playwright|headless", ln, re.IGNORECASE)
        ]
        env_lines = [
            f"{k}={os.environ.get(k, '(unset)')}"
            for k in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE")
        ]
        (out_dir / "processes.txt").write_text(
            "\n".join(lines) + "\n\n" + "\n".join(env_lines) + "\n", encoding="utf-8"
        )
    except Exception as exc:  # pragma: no cover - best-effort
        try:
            (out_dir / "processes.txt.CAPTURE_FAILED").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass

    return out_dir


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Standard hookwrapper pattern (pytest docs' own incremental-testing
    recipe): let every other plugin/pytest build the report first, then
    inspect and (optionally) annotate the FINISHED report -- never
    replaces it, never changes ``outcome``/pass-fail, so this is a no-op
    on every passing test and every non-Playwright failure."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        out_dir = _capture_playwright_failure(item, call)
        if out_dir is not None:
            report.sections.append(
                ("Playwright failure capture", f"artifacts written to: {out_dir}")
            )
