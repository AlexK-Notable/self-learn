"""Shared fixtures (10 §0 rules 7/8: tests never touch the real ledger,
``~/.claude``, real cache, real runtime dir, or the network)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

#: Coordinator's "MINE" item (code-gate review r1 2026-09-01): this
#: package's own venv `self-learn` binary, derived from `sys.
#: executable`'s own directory -- NEVER a hardcoded path, since the venv
#: location is not fixed across machines/CI. Both `self_learn_ui.
#: runner.resolve_self_learn_argv_prefix` (the POST/write path) and
#: `self_learn_ui.ledger._self_learn_bin` (the read path) now resolve
#: `SELF_LEARN_UI_CLI_BIN` FIRST, ahead of `shutil.which`'s raw-PATH
#: lookup -- pinning it here closes the gap BOTH resolvers had: a test
#: process invoked in some non-canonical way (`.venv/bin` not first on
#: `PATH`) could silently resolve to PRODUCTION's real `~/bin/self-learn`
#: instead of this worktree's own binary. Measured: before this pin
#: existed, 10 of 11 `test_settings_route.py` tests 503'd exactly this
#: way, because production's `self-learn` on master has no `config` verb
#: at all -- a route test that "passes" by hitting a 503 from the WRONG
#: binary is a measurement hazard, not a green test.
_VENV_SELF_LEARN_BIN = Path(sys.executable).parent / "self-learn"


@pytest.fixture(autouse=True)
def _pin_self_learn_cli_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autouse for every UI test (mirrors `_redirect_env_defaults` right
    below): pin `SELF_LEARN_UI_CLI_BIN` to this package's own venv
    binary so every subprocess call this suite makes -- through either
    resolver -- runs the CODE UNDER TEST, never whatever `self-learn`
    the invoking shell's PATH happens to turn up first. See
    `_VENV_SELF_LEARN_BIN`'s own comment for the measured failure this
    closes."""
    monkeypatch.setenv("SELF_LEARN_UI_CLI_BIN", str(_VENV_SELF_LEARN_BIN))


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


# ===================================================================== #
# U-cachelit (2026-08-28, code gate r1 M-1/M-2/M-3/N-1/N-3): the
# session-wide hermetic floor + the litter-namespace guard
# ===================================================================== #
#
# Measured 2026-08-27/28: ~/.cache/self-learn held 31,291 stray
# `home-<digest>` namespaces (1.1 GB), rising across suite runs. Root
# cause and fix: see `docs/specs/self-learn/14-forward-work-map.md`
# FW-130 and `13-hosting-and-separation.md` §6. `_env_floor_session`
# below is the ROOT fix -- a session-wide floor UNDERNEATH this
# package's own per-test redirect, so a module-scoped fixture in ANY
# test file (this package's own `test_js_dom.py`/`test_js_dom_pane_
# persistence.py`, or a future CLI file that grows one) cannot reopen
# the gap a per-test-only redirect leaves between a module fixture's
# instantiation and the first test's own setup (code gate r1 M-2:
# the CLI package initially had only the function-scoped `_worker_
# test_defaults`/`_redirect_env_defaults`; this fixture makes doc 13
# §6's "every suite redirects for the whole session" claim true rather
# than merely aspirational). `_litter_namespace_guard` is the forward
# BACKSTOP against a regression of the same class -- see its own
# docstring.

import hashlib
import os
import re
import subprocess
from pathlib import Path

from self_learn import gitops as _gitops_mod


@pytest.fixture(scope="session", autouse=True)
def _env_floor_session(tmp_path_factory: pytest.TempPathFactory):
    """The session-wide hermetic FLOOR underneath this package's own
    per-test redirect. Session-scoped: pytest instantiates it before
    every module-scoped fixture of every test (session > module > class
    > function, regardless of file order), and its `setenv` calls are
    never reverted until this fixture's OWN teardown runs, at the very
    end of the whole session (`pytest.MonkeyPatch()` instantiated
    directly, undone explicitly below -- the documented pattern for a
    fixture broader than function scope, since the built-in
    `monkeypatch` fixture is function-scoped only). Concretely: once
    this fixture has run, `os.environ` for these vars is NEVER unset
    again until the session itself ends -- when a per-test redirect's
    own `monkeypatch.setenv` undoes at that test's teardown, it restores
    the value THIS fixture set, never the real unset default. That
    closes the gap regardless of exactly when a background task's env
    read lands (the measured UI-package mechanism -- see FW-130), and
    regardless of which module-scoped fixture in which test file
    reopens it next.

    The floor's own `SELF_LEARN_HOME` is registered into
    `_SESSION_HOMES` (`_track_home` below) for the litter guard's
    attribution -- belt-and-braces on top of the dynamic `os.environ`
    fallback the `subprocess.Popen` patch already provides (every
    `monkeypatch.setenv` call, including this one, mutates the SAME
    live `os.environ` that fallback reads)."""
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("session-env-floor")
    floor_home = base / "home"
    mp.setenv("XDG_CACHE_HOME", str(base / "cache"))
    mp.setenv("XDG_RUNTIME_DIR", str(base / "runtime"))
    mp.setenv("SELF_LEARN_HOME", str(floor_home))
    mp.setenv("SELF_LEARN_CLAUDE_DIR", str(base / "claude"))
    mp.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(base / "transcripts"))
    mp.setenv("SELF_LEARN_WORKER_AUTOKICK", "0")
    mp.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    _track_home(floor_home)
    yield
    mp.undo()


#: The REAL cache root, resolved from the environment exactly as it
#: stood when this file was first imported by pytest -- module import
#: happens at collection time, before ANY fixture (including
#: `_env_floor_session` above) has run a single `monkeypatch.setenv`.
#: Mirrors `worker.cache_dir()`'s own resolution
#: (`${XDG_CACHE_HOME:-~/.cache}/self-learn`) without its `mkdir` side
#: effect -- the guard only ever reads this directory, never creates it.
_cache_env = os.environ.get("XDG_CACHE_HOME")
_REAL_CACHE_ROOT = (
    Path(_cache_env).expanduser() if _cache_env else Path("~/.cache").expanduser()
) / "self-learn"

_HOME_DIR_RE = re.compile(re.escape(str(_REAL_CACHE_ROOT)) + r"/home-[0-9a-f]{8}$")

#: D-1 (U-hostmode code gate r1 fold, 2026-08-28): the SAME real-cache
#: litter channel, one file-shape wider. `gitops.host_lock_path`'s plain
#: branch (U-hostmode §4.3) writes `host-<slug>.commit.lock` FILES
#: directly under `_REAL_CACHE_ROOT` -- a sibling of the `home-<digest>`
#: NAMESPACE DIRS this guard already watches, through the identical
#: XDG_CACHE_HOME-redirect mechanism, but the gate found 35 such files
#: already stranded there (pre-`_env_floor_session`, now flat) and noted
#: this guard "structurally cannot see this new file-shaped channel" --
#: `_HOME_DIR_RE` only ever matched a directory basename. This regex is
#: that missing half. (CLI package: `cli/tests/conftest.py`'s own
#: identical widening, same day, same reasoning.)
_LOCK_FILE_RE = re.compile(re.escape(str(_REAL_CACHE_ROOT)) + r"/host-[^/]+\.commit\.lock$")

#: Namespace dirs THIS interpreter created under `_REAL_CACHE_ROOT` --
#: 100% certain attribution, no digest-matching needed (it happened in
#: this process). Populated by the `Path.mkdir` patch below.
_INPROCESS_HITS: set[str] = set()

#: D-1: lock files THIS interpreter created under `_REAL_CACHE_ROOT` via
#: `gitops._flock_lock` -- same 100% certain in-process attribution as
#: `_INPROCESS_HITS` above, populated by the wrap installed alongside
#: the `Path.mkdir`/`subprocess.Popen` patches below. Unlike a
#: `home-<digest>` namespace, a lock file's name is keyed by the HOST
#: PATH's slug (`hosts.slug_for`), not by `SELF_LEARN_HOME` -- there is
#: no digest scheme to attribute a lock file this session did NOT
#: create in-process to a subprocess THIS session spawned, so (below)
#: any such file is reported, never asserted against (same posture as
#: `theirs`/`_WARN_NAMESPACES` for namespace dirs).
_INPROCESS_LOCK_HITS: set[str] = set()

#: Every home this session has HANDED OUT: the floor's own home, and
#: every `SELF_LEARN_HOME` a spawned subprocess's environment carried --
#: either an EXPLICIT `env=` mapping, or (code gate r1 M-3, "probe C")
#: this PARENT process's own live `os.environ` at spawn time when no
#: `env=` override was given at all (that is what the child actually
#: inherits -- `subprocess.Popen`'s own documented default). Raw values
#: as seen; `_home_digests()` normalizes before hashing (M-3, "probe
#: E") so a differently-spelled but equivalent path still matches.
_SESSION_HOMES: set[str] = set()


def _track_home(home) -> None:
    if home:
        _SESSION_HOMES.add(str(home))


def _install_litter_guards():
    """Two CLASS-level patches, deliberately never a rebound FUNCTION
    name: `cli.py`/`worker.py`/`self_learn_ui.pane`/`middleware` all do
    `from ... import resolve_home`/`cache_dir` at import time, which a
    same-module patch installed after collection cannot reach -- the
    caller's own bound name still points at the ORIGINAL function.
    `pathlib.Path` and `subprocess.Popen` are shared, mutable class
    objects instead: patching a method on the class itself is visible
    through every already-bound reference, however it was imported,
    because attribute lookup on an instance resolves through the class
    at CALL time, not at import time.

    D-1 (code gate r1 fold) adds a THIRD patch that IS a rebound
    function name (`gitops._flock_lock`) -- safe here for a reason the
    class-patch rule above does not cover: `_flock_lock` is never
    imported anywhere outside `gitops.py` itself (`grep -rn
    '_flock_lock' cli/src/self_learn/*.py` -- one definition, one
    module-internal call site each in `host_lock`/`commit_lock`, no
    `from .gitops import _flock_lock` anywhere). `host_lock`/
    `commit_lock` reference the bare name `_flock_lock` from INSIDE the
    same module, which Python resolves through `gitops.__dict__` at
    CALL time, not at their own def time -- rebinding
    `_gitops_mod._flock_lock` from here is visible to both, the exact
    property the class patches above rely on for `Path`/`Popen`, just
    reached through a different mechanism (module globals rather than a
    shared class).

    Returns the three ORIGINAL (unpatched) callables so the guard
    fixture's teardown can restore them (code gate r1 N-3): a
    session-scoped patch of shared interpreter state must not outlive
    the session it was installed for -- left patched, it would leak
    into whatever runs next in the same interpreter (a `pytester`
    sub-session sharing this venv, a plugin hook, anything importing
    `pathlib`/`subprocess`/`gitops` afterward)."""
    orig_mkdir = Path.mkdir

    def _tracked_mkdir(self, *a, **kw):
        if _HOME_DIR_RE.fullmatch(str(self)):
            _INPROCESS_HITS.add(str(self))
        return orig_mkdir(self, *a, **kw)

    Path.mkdir = _tracked_mkdir

    orig_popen_init = subprocess.Popen.__init__

    def _tracked_popen_init(self, *args, **kwargs):
        try:
            if "env" in kwargs and kwargs["env"] is not None:
                _track_home(kwargs["env"].get("SELF_LEARN_HOME"))
            else:
                # No `env=` override at all (code gate r1 M-3, "probe
                # C") -- subprocess.Popen's own documented default is
                # "inherit THIS process's os.environ verbatim", so that
                # is what the child (and any setsid grandchild it spawns
                # the same way) actually sees.
                _track_home(os.environ.get("SELF_LEARN_HOME"))
        except Exception:  # noqa: BLE001 -- tracking must never break a spawn
            pass
        return orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _tracked_popen_init

    orig_flock_lock = _gitops_mod._flock_lock

    def _tracked_flock_lock(path, timeout, wedged_by):
        if _LOCK_FILE_RE.fullmatch(str(path)):
            _INPROCESS_LOCK_HITS.add(str(path))
        return orig_flock_lock(path, timeout, wedged_by)

    _gitops_mod._flock_lock = _tracked_flock_lock

    return orig_mkdir, orig_popen_init, orig_flock_lock


def _normalized_digests(home: str) -> set[str]:
    """Code gate r1 M-3, "probe E": a RAW, non-normalized
    `SELF_LEARN_HOME` string (a trailing slash, a double slash, an
    unexpanded `~`) must still match the digest the REAL `resolve_
    home()`/`cache_dir()` call chain produces --
    ``hashlib.sha256(str(resolve_home())...)`` where ``resolve_home()``
    is ``Path(raw).expanduser()`` (expanduser only, never a full
    ``.resolve()``). Hashing the raw string directly, as the first
    version of this guard did, caused exactly this class of mismatch.
    Registers BOTH the `.expanduser()` form (the literal production
    algorithm) and the additionally-`.resolve()`-d form (`..`-safe,
    symlink-safe) -- verified identical to the `.expanduser()` form for
    every path this suite ever actually produces (no `..` segments, and
    no tmp directory on this host sits behind a symlink: `Path("/tmp").
    is_symlink()` is `False` here) -- so a match holds regardless of
    which normalization a caller's path needed, without risking a
    silent divergence from what `cache_dir()` itself will compute."""
    p = Path(home)
    out = {hashlib.sha256(str(p.expanduser()).encode("utf-8")).hexdigest()[:8]}
    try:
        out.add(
            hashlib.sha256(str(p.expanduser().resolve()).encode("utf-8")).hexdigest()[:8]
        )
    except OSError:
        pass
    return out


def _home_digests() -> set[str]:
    digests: set[str] = set()
    for h in _SESSION_HOMES:
        digests |= _normalized_digests(h)
    return digests


#: Code gate r1 M-3: namespaces reported (not failed) this session --
#: read by `pytest_terminal_summary` below, which is ALWAYS printed
#: (even under `-q`), unlike a bare `print()` during a session
#: fixture's teardown, which pytest's own capture manager can swallow.
_WARN_NAMESPACES: list[str] = []


@pytest.fixture(scope="session", autouse=True)
def _litter_namespace_guard():
    """Fails the SESSION loudly, by name, the instant this run's OWN
    activity -- in-process or a spawned subprocess -- creates a real
    `home-<digest>` namespace under `~/.cache/self-learn` (the exact
    defect FW-130 fixed; `_env_floor_session` above is the intended
    ROOT fix, this is the forward backstop against a regression neither
    of them anticipated). Concurrency on this shared host: another
    builder's suite may add namespaces during this session too -- those
    are reported via `pytest_terminal_summary` (a warning naming them)
    but never fail this session, since this session did not create them
    and cannot know it is safe to blame them. Disabling this fixture,
    or either assertion below, is exactly the mutation this guard's own
    `pytester`-driven tests (`test_litter_guard_probes.py`) are built to
    catch.

    D-1 (code gate r1 fold) widens the SAME guard to a sibling litter
    shape: `host-*.commit.lock` FILES (`gitops.host_lock_path`'s plain
    branch), not just `home-<digest>` DIRS. The before/after
    `os.listdir` diff below already swept any such file into `theirs`
    (it is not `home-`-prefixed, so it was never `mine`) -- reported,
    never asserted on, indistinguishable from a genuine concurrent
    sibling. `_INPROCESS_LOCK_HITS` (populated by the `gitops.
    _flock_lock` wrap in `_install_litter_guards`) closes that gap with
    the SAME certain, in-process attribution `_INPROCESS_HITS` already
    has for directories: THIS interpreter calling `_flock_lock` on a
    real-cache-rooted lock path is 100% this session's own doing, no
    digest-matching needed, so it is asserted on, hard, exactly like
    `_INPROCESS_HITS` above.

    D-1 (code gate r2 fold), scope: this guard runs only INSIDE a
    pytest session (this fixture) -- an ad-hoc script run outside
    pytest (a dev-loop probe against the real ~/.cache/self-learn,
    never through `tmp_path`/`XDG_CACHE_HOME`) is invisible to it and
    can still litter `host-*.commit.lock` files the guard has no
    chance to catch or report; five such files, dated 06:09-06:20 on
    2026-08-28, were the r1 fold's own B-2 probes and were deleted by
    hand as part of this fold. From now on, every ad-hoc script sets
    `XDG_CACHE_HOME` to a temp dir before importing anything from this
    package."""
    orig_mkdir, orig_popen_init, orig_flock_lock = _install_litter_guards()
    try:
        before = set(os.listdir(_REAL_CACHE_ROOT))
    except FileNotFoundError:
        before = set()
    yield
    # N-3: restore the THREE patches BEFORE this fixture's own
    # assertions run, so a failed assertion here never leaves shared
    # interpreter state patched for whatever runs next in this process.
    Path.mkdir = orig_mkdir
    subprocess.Popen.__init__ = orig_popen_init
    _gitops_mod._flock_lock = orig_flock_lock
    assert not _INPROCESS_HITS, (
        "self-learn cache-litter guard: THIS interpreter created the "
        f"real namespace dir(s) {sorted(_INPROCESS_HITS)} during this "
        "session -- XDG_CACHE_HOME did not reach whatever called "
        "worker.cache_dir()/sentinel.sentinel_path() for that home. "
        "Find the call site and fix it there, never by widening this "
        "guard."
    )
    # D-1: same hard-fail shape as `_INPROCESS_HITS`, for lock files.
    assert not _INPROCESS_LOCK_HITS, (
        "self-learn cache-litter guard: THIS interpreter took a real "
        f"host-mode lock at {sorted(_INPROCESS_LOCK_HITS)} during this "
        "session -- XDG_CACHE_HOME did not reach whatever called "
        "gitops.host_lock()/host_lock_path() for that host. Find the "
        "call site and fix it there, never by widening this guard."
    )
    try:
        after = set(os.listdir(_REAL_CACHE_ROOT))
    except FileNotFoundError:
        after = set()
    new = after - before
    if not new:
        return
    digests = _home_digests()
    mine = sorted(n for n in new if n.startswith("home-") and n[len("home-"):] in digests)
    theirs = sorted(new - set(mine))
    if theirs:
        _WARN_NAMESPACES.extend(theirs)
    assert not mine, (
        "self-learn cache-litter guard: a subprocess THIS session "
        f"spawned created real namespace dir(s) {mine} -- its env "
        "dropped XDG_CACHE_HOME. Find the spawn site and fix its env, "
        "never by widening this guard."
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Code gate r1 M-3: the "concurrent sibling, not failed" warning
    must be VISIBLE even under `-q` -- a bare `print()` during a session
    fixture's teardown is captured/swallowed by pytest's own capture
    manager under `-q` and never reaches the terminal.
    `pytest_terminal_summary` is always printed, `-q` or not."""
    if _WARN_NAMESPACES:
        terminalreporter.write_sep("-", "self-learn cache-litter guard")
        terminalreporter.write_line(
            f"{len(_WARN_NAMESPACES)} new real {_REAL_CACHE_ROOT} namespace(s) "
            "appeared this session that do not match any SELF_LEARN_HOME "
            "this session itself handed out -- presumed a concurrent "
            f"sibling suite on this shared host, reported but not failed: "
            f"{_WARN_NAMESPACES}"
        )
