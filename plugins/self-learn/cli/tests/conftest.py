"""Suite-wide defaults.

The M2 worker is kick-driven: real `teach`/`import` end by spawning a
detached coalescing run. Tests must never leak detached processes, so
auto-kick is disabled globally here; worker tests opt back in (or drive
`worker.kick`/`worker.run` directly) by clearing/overriding the env var.
Coalesce sleep is zeroed for the same reason.

Incident 2026-08-09: notifications are ALSO suppressed globally here
(`SELF_LEARN_NO_NOTIFY=1`, same convention as AUTOKICK above) — both
`worker._notify` and `worker._notify_with_ids` resolve their helper via
PATH, which on a dev machine finds the REAL deployed ~/bin scripts
regardless of sandboxing, so an unsuppressed worker test notified the
operator's REAL desktop. Tests exercising notify behavior opt back out
via `monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)` — same
convention as AUTOKICK — and use the PATH-shimmed
`self-learn-notify`/`notify-send`, never the real ones.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _no_real_sdk_spawn_tripwire():
    """U-sdk code-gate fold, BLOCKER-1 fix-proof. `claude_agent_sdk`'s
    `_find_cli()` is the ONLY mechanism in this codebase that can resolve
    a `None` `cli_path` to a REAL, credentialed Claude Code binary
    (`_bundled/claude` or `shutil.which("claude")`) -- exactly the
    mechanism BLOCKER-1 exploited (a stray `monkeypatch.undo()` reverted
    `sdk_cli_path`'s `SELF_LEARN_SDK_CLI_PATH` mid-test, so `cli_path`
    fell through to `None` and the SDK silently spawned a real, ~4s,
    uncapped-budget session under the operator's own credentials).

    Every legitimate SDK-driving test in this suite sets
    `SELF_LEARN_SDK_CLI_PATH` (via `test_invocation_sdk.py`'s
    `sdk_cli_path` fixture), which flows into `ClaudeAgentOptions.cli_path`
    and keeps `self._cli_path` non-`None` at `connect()` time -- so
    `_find_cli()` should NEVER be called during this test session. Hard-
    blocking it turns a silent, timing-dependent real-session hazard into
    an immediate, deterministic test failure the instant the bug's class
    recurs, rather than a hope that a `ps` sampler catches a ~4s window.

    Lives HERE (not in `test_invocation_sdk.py`) so it is shared test
    infrastructure, not an `autouse` fixture inside the unit's own file
    (`Sim-1a` forbids that specifically in `test_invocation_sdk.py`).
    `claude_agent_sdk` is imported lazily and guarded -- this fixture must
    not fail collection in an environment where the SDK is absent."""
    try:
        import claude_agent_sdk._internal.transport.subprocess_cli as _subprocess_cli
    except ImportError:
        yield
        return

    def _tripped(self):
        raise AssertionError(
            "claude_agent_sdk._find_cli() was called during the test suite. "
            "This resolves cli_path=None to a REAL, credentialed Claude Code "
            "binary (_bundled/claude or PATH) -- exactly the hazard U-sdk's "
            "code-gate BLOCKER-1 found. Every session-driving test must set "
            "SELF_LEARN_SDK_CLI_PATH (the sdk_cli_path fixture) BEFORE the "
            "session runs, and must never call monkeypatch.undo() on the "
            "shared fixture instance -- use a nested pytest.MonkeyPatch() "
            "context for state that needs to unwind mid-test instead."
        )

    original = _subprocess_cli.SubprocessCLITransport._find_cli
    _subprocess_cli.SubprocessCLITransport._find_cli = _tripped
    try:
        yield
    finally:
        _subprocess_cli.SubprocessCLITransport._find_cli = original


#: U-cleanup-B: `_cli_backend_unreached_tripwire` (U-cleanup-A `AG1`) is
#: RETIRED here, exactly as its own docstring said it would be -- its
#: subject, `CliBackend._run`, no longer exists (§8.1), so there is
#: nothing left to guard being unreached. `AG2`'s negative control
#: (`test_u_sdka.py::test_ag2_tripwire_fires_on_direct_clibackend_call`)
#: is deleted alongside it, not retargeted -- it existed solely to prove
#: THIS tripwire arms, and there is no tripwire left to prove.


@pytest.fixture(autouse=True)
def _worker_test_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_WORKER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_COALESCE_SECS", "0")
    monkeypatch.setenv("SELF_LEARN_NO_NOTIFY", "1")
    # Cache isolation for EVERY test (found 2026-07-15: status tests read
    # the real ~/.cache worker.last-run once a real worker run existed on
    # the machine — the suite must never see real cache state). Tests that
    # redirect XDG themselves simply override this default.
    # MINOR 4 (code gate): before `init` existed no verb could CREATE a
    # home, so an unset SELF_LEARN_HOME was harmless. It no longer is.
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-default"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache-default"))
    # Config isolation for EVERY test (found 2026-08-27, U-servehermetic:
    # `serve.unit_dir()` falls back to `XDG_CONFIG_HOME`, then to the
    # real `~/.config/systemd/user`, exactly mirroring the cache-isolation
    # reasoning above -- without this, a test session on a host that has
    # ever linked the `self-learn-host.service` reference unit reads that
    # REAL unit as "configured" and produces a live-host-dependent FAIL/
    # SKIP split invisible to the U-engine Phase 2 gate, which ran before
    # any host had linked the unit). Tests that redirect XDG themselves
    # simply override this default, same convention as XDG_CACHE_HOME.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-default"))
    # Miner defaults: no detached watchdog spawns, and the transcript root
    # NEVER defaults to the real ~/.claude/projects inside tests.
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv(
        "SELF_LEARN_TRANSCRIPTS_DIR", str(tmp_path / "_no_transcripts")
    )
    # The selftest hook check reads settings.json + ~/.claude/hooks (M3):
    # tests must never see the real ~/.claude — redirect it per-test.
    monkeypatch.setenv(
        "SELF_LEARN_CLAUDE_DIR", str(tmp_path / "claude-dir-default")
    )
    # U-cleanup-A `AG3`: the three suite-wide `cli` pins that used to sit
    # here (U-sdka `Armor-1`'s analyst pin, U-flip's worker/miner pins)
    # are REMOVED, not merely edited. Their premise was "every
    # pre-existing test drives a bash PATH shim or a patched
    # `subprocess.run`, i.e. the cli transport, and names no backend" --
    # CV2/CB-3's migration has made that premise false: the ~109
    # behaviour tests now drive `SdkBackend` -> `fake_claude.py`
    # end to end (`sdk_fake_worker`/`sdk_fake_analyst`,
    # `reader_leg`, `backend`). With no pin left here, EVERY surface now
    # resolves through `DEFAULT_BACKEND_FOR_SURFACE` (all `sdk` since
    # U-flip) unless a test overrides it.
    # U-cleanup-B (code gate r1, NIT-5): this paragraph used to end by
    # pointing at "the suite-wide default this unit's own `AG1`
    # tripwire on `CliBackend._run` is meant to prove unreached in
    # practice, not merely in theory" and "every remaining test that
    # still needs `cli` for real names it explicitly via its own
    # `monkeypatch.setenv`" -- both stale. `AG1`/`_cli_backend_
    # unreached_tripwire` is RETIRED (see the docstring 30 lines above
    # this fixture); `CliBackend._run` no longer exists to be reached
    # or unreached. And no test "needs `cli` for real" any more --
    # `cli` is a NAMED REFUSAL now (`registry._resolve`), never a
    # second transport a test could drive; the handful of tests that
    # still `monkeypatch.setenv(..., "cli")` (SEL1-6, the scoping-
    # precedence tests) are asserting the refusal fires, not reaching
    # a real subprocess.


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
#: that missing half.
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
    `_INPROCESS_HITS` above."""
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
