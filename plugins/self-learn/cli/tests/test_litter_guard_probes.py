"""U-cachelit code gate r1 M-1/M-3, plus U-xdist code gate r1 Minor
(probe F): guard-of-the-guard for `conftest.py`'s
`_litter_namespace_guard`/`_env_floor_session`/the worker -> controller
relay -- proves the guard
actually FIRES (a committed test asserting only that the fixture and its
assertions exist would pass even with a one-line `return` gutting the
teardown check entirely; the unchanged 2419/1270 suite counts after this
unit's first build were exactly that tell, per the code gate's own r1
finding).

Every probe below drives a REAL, isolated pytest sub-session via
`pytester.runpytest_subprocess()`, with the sub-session's own REAL-cache
resolution (`conftest.py`'s `_REAL_CACHE_ROOT`) pointed at a SCRATCH
directory under this test's own `tmp_path` -- via the sub-session's
PRE-FIXTURE environment (`pytester`'s `popen()` copies `os.environ` into
the child's env at spawn time, BEFORE the sub-session's own conftest.py
is even imported, so setting env vars on the OUTER test just before
`runpytest_subprocess()` controls exactly what the sub-session's
module-level `_REAL_CACHE_ROOT` resolves to).

Two knobs are used together, matching `worker.cache_dir()`'s own
resolution order: `XDG_CACHE_HOME` (when SET, used directly) and `HOME`
(the fallback base once `XDG_CACHE_HOME` is absent -- `Path("~/.cache").
expanduser()` reads `HOME`, and Python falls back to the OS password
database, the REAL user's home, only when `HOME` is unset too). Probes
that simulate "XDG_CACHE_HOME absent" (A, C) sandbox `HOME` to a scratch
directory FOR THE WHOLE SUB-SESSION as well, so the absence resolves
into the scratch tree the guard is watching, not the operator's own
`~/.cache` — the bug class under test, reproduced without ever risking
the real cache. Probes that spawn a child with an EXPLICIT (replacing)
`env=` mapping (B, E) include `HOME` in that mapping for the same
reason. Probe D targets `_REAL_CACHE_ROOT` directly (re-exported from
the real conftest) and needs neither knob.

These tests therefore never touch the operator's own `~/.cache/self-
learn`, by construction -- verified per-probe below (the created
namespace is found under the SCRATCH root).

The sub-session's own conftest.py is generated (`_make_probe_conftest`)
to import the REAL `conftest.py` by absolute path
(`importlib.util.spec_from_file_location`, the same splicing pattern
`test_pw_failure_capture.py` already uses in this repo) and re-export
its guard fixtures/hook under their real names -- so every probe
exercises the SHIPPED implementation, never a reimplementation of it.

Probe table (A-F), each proving one class of bypass the guard must
catch (or correctly decline to blame):

  A. In-process `delenv` + a direct `worker.cache_dir()` call --
     caught by the `Path.mkdir` patch, 100% certain attribution.
  B. A subprocess with an EXPLICIT `env=` mapping carrying
     `SELF_LEARN_HOME` (no `XDG_CACHE_HOME`) -- caught by digest
     matching against `_SESSION_HOMES`.
  C. A subprocess spawned with NO `env=` kwarg at all (mirrors
     `worker._spawn_run`'s own `start_new_session=True` detached-miner
     shape) -- before the fix, this fell to warn-only (nothing was
     tracked when the `env=` kwarg was simply absent); the fix falls
     back to this PARENT process's own live `os.environ` at spawn time,
     which is exactly what the child inherits.
  D. A namespace this session never tracked, created via a raw
     `os.makedirs` (bypassing both the `Path.mkdir` patch and the
     `Popen` patch on purpose) -- simulates a CONCURRENT SIBLING
     builder's own process; must be WARNED (via `pytest_terminal_
     summary`), never FAILED.
  E. A subprocess whose `env=` mapping carries a NON-NORMALIZED
     `SELF_LEARN_HOME` (a trailing/doubled slash) -- before the fix,
     hashing the RAW tracked string mismatched the digest
     `resolve_home()`'s `Path(raw).expanduser()` actually produces,
     falling to warn-only; the fix normalizes before hashing.
  F. Probe D's own scenario, driven under `-n 2` instead of the
     default serial run -- proves the worker -> controller relay
     (`pytest_sessionfinish`/`pytest_testnodedown`, U-xdist,
     2026-08-28) reports the one real namespace EXACTLY ONCE even
     when two separate worker processes each independently observe
     it, rather than the byte-pin `test_armor.py` already carries
     for the hooks' own source text -- a hook-ordering change could
     resurrect the pre-fix silence, or a dedup regression could
     double-report, while a byte pin alone stays green either way.

Mutation, verified by hand during this unit's build (not itself
committed -- a one-line source mutation applied, ALL FIVE probes
re-run to confirm RED, then reverted, sha256-diffed byte-identical to
before): a bare `return` inserted immediately after `_litter_namespace_
guard`'s `yield` (before its `Path.mkdir`/`Popen` restoration and both
assertions) skips EVERYTHING the fixture's teardown does -- turning
probes A, B, C, and E from an "errors=1" outcome to "errors=0" (their
own `result.assert_outcomes(...)` then fails), AND leaving `_WARN_
NAMESPACES` never populated, so probe D's own `"reported but not
failed" in combined` assertion fails too (`pytest_terminal_summary`
finds nothing to print). All five went red under this one mutation.

Probe F's own two mutations, verified by hand during the U-xdist code
gate r1 fold the same way (applied, probe F re-run solo to confirm
RED, reverted, sha256-diffed byte-identical to before): (1) with
`pytest_sessionfinish`/`pytest_testnodedown` deleted from the SPLICED
conftest (`_make_probe_conftest`'s own re-export lines removed, not
the real conftest.py), probe F's sub-session goes SILENT under `-n
2` -- no "cache-litter guard" separator at all -- while the same
scenario re-run with no `-n` flag (serial) still reports it, proving
the silence is specific to the relay, not the scenario; (2) with the
dedup's `if namespace not in _WARN_NAMESPACES` guard in the real
`pytest_testnodedown` replaced by a plain `.extend()`, the SAME `-n
2` scenario reports "2 new real ... namespace(s)" for the one real
directory, and `home-deadbeef` appears twice in the printed list.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# Gate r1 M-1: `pytester` is not enabled by default; a plain test
# module's `pytest_plugins` is the supported activation point (mirrors
# `test_pw_failure_capture.py`, same repo).
pytest_plugins = ["pytester"]

_REAL_CONFTEST = Path(__file__).resolve().parent / "conftest.py"


def _digest(home) -> str:
    """The SAME normalization `resolve_home()`/`cache_dir()` itself
    applies -- `Path(raw).expanduser()`, never a full `.resolve()` --
    so this predicts the EXACT `home-<digest>` name a given
    `SELF_LEARN_HOME` value will produce."""
    return hashlib.sha256(str(Path(home).expanduser()).encode("utf-8")).hexdigest()[:8]


def _make_probe_conftest(pytester: pytest.Pytester) -> None:
    """Splices the REAL conftest.py's guard fixtures/hooks (including
    U-xdist's worker -> controller relay, `pytest_sessionfinish`/
    `pytest_testnodedown`, needed by probe F) into the
    sub-run's own generated conftest.py -- `importlib.util.spec_from_
    file_location` loads the REAL file by absolute path so the sub-run
    exercises the SHIPPED implementation (same pattern `test_pw_
    failure_capture.py::test_page_detection_survives_a_raising_fixture_
    getattr` already uses in this package for `pytest_runtest_
    makereport`)."""
    pytester.makeconftest(
        f"""
        import importlib.util

        _spec = importlib.util.spec_from_file_location(
            "_real_conftest_under_test_cachelit", {str(_REAL_CONFTEST)!r}
        )
        _real = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real)

        _env_floor_session = _real._env_floor_session
        _litter_namespace_guard = _real._litter_namespace_guard
        pytest_terminal_summary = _real.pytest_terminal_summary
        pytest_sessionfinish = _real.pytest_sessionfinish
        pytest_testnodedown = _real.pytest_testnodedown
        _REAL_CACHE_ROOT = _real._REAL_CACHE_ROOT
        """
    )


# ------------------------------------------------------------- Probe A


def test_probe_a_inprocess_bypass_fails_the_session(pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A: in-process `delenv` + a direct `worker.cache_dir()` call.
    Caught by the `Path.mkdir` patch -- 100% certain attribution, no
    digest matching needed. `HOME` is sandboxed to a scratch dir for the
    WHOLE sub-session (never touched by `_env_floor_session`, which only
    ever sets `XDG_*`/`SELF_LEARN_*`) so "XDG_CACHE_HOME absent" resolves
    `~/.cache` into the scratch tree the guard is watching, not the
    operator's own home. The probe test itself PASSES (the mkdir
    genuinely succeeds -- that is the bypass); the SUB-SESSION fails at
    teardown, naming the namespace."""
    scratch_home = tmp_path / "scratch-home"
    scratch_home.mkdir()
    home = tmp_path / "probe-a-home"
    monkeypatch.setenv("HOME", str(scratch_home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe=f"""
        from self_learn import worker

        def test_probe(monkeypatch):
            monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
            monkeypatch.setenv("SELF_LEARN_HOME", {str(home)!r})
            d = worker.cache_dir()
            assert d.is_dir()
        """
    )
    result = pytester.runpytest_subprocess()
    combined = "\n".join(result.outlines + result.errlines)
    result.assert_outcomes(passed=1, failed=0, errors=1)
    expected = f"home-{_digest(home)}"
    assert expected in combined, combined
    assert "cache-litter guard" in combined
    assert (scratch_home / ".cache" / "self-learn" / expected).is_dir()


# ------------------------------------------------------------- Probe B


def test_probe_b_subprocess_with_explicit_env_fails_the_session(pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B: a subprocess with an EXPLICIT `env=` mapping carrying
    `SELF_LEARN_HOME` (no `XDG_CACHE_HOME`) -- caught by digest matching
    against `_SESSION_HOMES` (`_track_home` records `env.get(
    "SELF_LEARN_HOME")` whenever an explicit `env=` is given). An
    explicit `env=` REPLACES the child's environment entirely (no
    inheritance), so `HOME` is included in the constructed mapping --
    otherwise Python's `expanduser()` falls back to the OS password
    database (the REAL user's home) once `HOME` is absent from env too,
    which no in-mapping value can prevent short of setting it."""
    scratch_home = tmp_path / "scratch-home"
    scratch_home.mkdir()
    home = tmp_path / "probe-b-home"
    monkeypatch.setenv("HOME", str(scratch_home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe=f"""
        import subprocess
        import sys

        def test_probe():
            env = {{"HOME": {str(scratch_home)!r}, "SELF_LEARN_HOME": {str(home)!r}, "PATH": "/usr/bin:/bin"}}
            subprocess.run(
                [sys.executable, "-c", "from self_learn import worker; worker.cache_dir()"],
                env=env, check=True, timeout=30,
            )
        """
    )
    result = pytester.runpytest_subprocess()
    combined = "\n".join(result.outlines + result.errlines)
    result.assert_outcomes(passed=1, failed=0, errors=1)
    expected = f"home-{_digest(home)}"
    assert expected in combined, combined
    assert (scratch_home / ".cache" / "self-learn" / expected).is_dir()


# ------------------------------------------------------------- Probe C


def test_probe_c_no_env_kwarg_falls_back_to_os_environ_and_still_fails(pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C: a subprocess spawned with NO `env=` kwarg at all -- mirrors
    `worker._spawn_run`'s own shape (`SELF_LEARN_HOME` set on the
    PARENT, a detached child Popen'd with `start_new_session=True` and
    no `env=`, inheriting `os.environ` verbatim -- `HOME` included,
    since it was sandboxed for the whole sub-session, same as probe A).
    Before the fix, the `Popen` patch's `if env:` guard skipped tracking
    entirely whenever the kwarg was absent, so this fell to warn-only;
    the fix falls back to `os.environ.get("SELF_LEARN_HOME")` -- exactly
    what the child (and any setsid grandchild it spawns the same way)
    actually inherits."""
    scratch_home = tmp_path / "scratch-home"
    scratch_home.mkdir()
    home = tmp_path / "probe-c-home"
    monkeypatch.setenv("HOME", str(scratch_home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe=f"""
        import subprocess
        import sys

        def test_probe(monkeypatch):
            monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
            monkeypatch.setenv("SELF_LEARN_HOME", {str(home)!r})
            proc = subprocess.Popen(
                [sys.executable, "-c", "from self_learn import worker; worker.cache_dir()"],
                start_new_session=True,
            )
            rc = proc.wait(timeout=30)
            assert rc == 0
        """
    )
    result = pytester.runpytest_subprocess()
    combined = "\n".join(result.outlines + result.errlines)
    result.assert_outcomes(passed=1, failed=0, errors=1)
    expected = f"home-{_digest(home)}"
    assert expected in combined, combined
    assert (scratch_home / ".cache" / "self-learn" / expected).is_dir()


# ------------------------------------------------------------- Probe D


def test_probe_d_unattributable_namespace_is_warned_not_failed(pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D: a namespace this session never tracked, created via a raw
    `os.makedirs` -- deliberately bypasses BOTH the `Path.mkdir` patch
    (a different call, not `pathlib.Path.mkdir`) and the `Popen` patch
    (no subprocess at all), simulating a CONCURRENT SIBLING builder's
    own process creating a namespace on this shared host: this
    session's `Path.mkdir` patch, which only ever sees calls made
    THROUGH THIS interpreter, correctly cannot and must not see it
    either. Targets `_REAL_CACHE_ROOT` directly (re-exported from the
    real conftest), so this probe needs no `HOME` sandboxing -- an
    explicit `XDG_CACHE_HOME` is enough. Must be WARNED (surfaced via
    `pytest_terminal_summary`, which is unconditionally printed), never
    FAILED -- the sub-session's own exit is clean."""
    scratch_cache = tmp_path / "fake-real-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(scratch_cache))

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe="""
        import os

        from conftest import _REAL_CACHE_ROOT

        def test_probe():
            foreign = _REAL_CACHE_ROOT / "home-deadbeef"
            os.makedirs(foreign, exist_ok=True)
        """
    )
    result = pytester.runpytest_subprocess()
    combined = "\n".join(result.outlines + result.errlines)
    result.assert_outcomes(passed=1, failed=0, errors=0)
    assert "home-deadbeef" in combined, combined
    assert "reported but not failed" in combined, combined
    assert (scratch_cache / "self-learn" / "home-deadbeef").is_dir()


# ------------------------------------------------------------- Probe E


def test_probe_e_non_normalized_home_still_fails(pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E: a subprocess whose `env=` mapping carries a NON-NORMALIZED
    `SELF_LEARN_HOME` (a trailing, doubled slash) -- `Path("X//").
    expanduser()` normalizes to `Path("X")` (pathlib parses this at
    CONSTRUCTION time, no `.resolve()` needed), exactly what `resolve_
    home()` itself does before `cache_dir()` hashes it. Before the fix,
    `_home_digests()` hashed the tracked RAW string directly, so the
    doubled-slash spelling never matched the (normalized) digest the
    child actually produced, falling to warn-only; the fix normalizes
    before hashing. Same `HOME`-in-mapping reasoning as probe B."""
    scratch_home = tmp_path / "scratch-home"
    scratch_home.mkdir()
    home = tmp_path / "probe-e-home"
    non_normalized = str(home) + "//"
    monkeypatch.setenv("HOME", str(scratch_home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe=f"""
        import subprocess
        import sys

        def test_probe():
            env = {{"HOME": {str(scratch_home)!r}, "SELF_LEARN_HOME": {non_normalized!r}, "PATH": "/usr/bin:/bin"}}
            subprocess.run(
                [sys.executable, "-c", "from self_learn import worker; worker.cache_dir()"],
                env=env, check=True, timeout=30,
            )
        """
    )
    result = pytester.runpytest_subprocess()
    combined = "\n".join(result.outlines + result.errlines)
    result.assert_outcomes(passed=1, failed=0, errors=1)
    expected = f"home-{_digest(home)}"  # the NORMALIZED digest
    assert expected in combined, combined
    assert (scratch_home / ".cache" / "self-learn" / expected).is_dir()


# ------------------------------------------------------------- Probe F


def test_probe_f_xdist_relay_reports_a_concurrent_sibling_exactly_once(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F (U-xdist code gate r1, Minor): pins the worker -> controller
    relay (`pytest_sessionfinish`/`pytest_testnodedown`, appended to
    `conftest.py` for U-xdist) by BEHAVIOUR, not merely by the byte sha
    `test_armor.py` already carries for the file -- a hook-ordering
    change could resurrect the exact silent-under-`-n` failure this
    relay exists to fix while a byte pin alone stays green.

    Same probe-D scenario (a foreign namespace, unattributable to this
    session, created via a raw `os.makedirs` that bypasses both the
    `Path.mkdir` and `Popen` patches -- simulating a CONCURRENT SIBLING
    builder's own process on this shared host) but driven under `-n 2`
    with TWO test items. BOTH items create the SAME namespace
    (`exist_ok=True`, so idempotent regardless of ordering), and
    BOTH synchronize on a marker-file BARRIER before creating it
    (code gate r2 nit, structural over statistical, 2026-08-29): each
    item touches its own `PYTEST_XDIST_WORKER`-named file under a
    shared `PROBE_F_MARKER_DIR`, then waits (bounded, 5s) for a peer
    marker to appear. Since fixture setup (the `before` scan)
    unconditionally precedes the test BODY, observing a peer marker
    proves both workers' `before` scans are already done -- a
    guarantee, not a margin. An earlier version used a fixed 0.5s
    sleep on both items instead of the barrier: sound by a wide
    measured margin on its own (gate-measured worker-start skew:
    <=1.0 ms unloaded, <=3.0 ms stressed under a manufactured load
    average of 48.8 on 28 cores -- a ~165x margin over 0.5s) but
    still statistical rather than structural. It replaced a version
    with only ONE item sleeping, on the theory that whichever worker
    landed which item, both before/after windows would still likely
    span the directory's appearance -- measured false 1 run in 3
    (code gate r1 fold, 2026-08-28): a late-starting second worker's
    `before` scan landed AFTER the first worker's near-instant
    mkdir, so the second worker saw no "new" directory at all and
    only one relay fired, regardless of the dedup under test --
    silently passing a mutation this probe exists to catch. The
    barrier removes that failure mode by construction rather than by
    margin. When xdist splits the two items across two separate
    worker processes (the common, intended case -- two items, `-n
    2`), each worker session
    independently discovers the SAME namespace as "new" in its own
    before/after diff and relays it to the controller; this is
    exactly the double-observation race the dedup in
    `pytest_testnodedown` exists to collapse.

    Asserts the controller's terminal summary reports it EXACTLY ONCE,
    via TWO independent, both-measured discriminators: (1)
    `pytest_terminal_summary`'s own `f"{len(_WARN_NAMESPACES)} new
    real..."` count line, and (2) a raw substring count of
    "home-deadbeef" in the combined output. Corrected 2026-08-29
    (code gate r2, MINOR-3): an earlier version of (2) asserted
    `<= 2`, which is INERT for this mutation -- MEASURED count is 1 for
    the clean scenario and 2 for the dedup-removed one, and 1 <= 2 and
    2 <= 2 both pass, so it discriminated nothing; the earlier
    docstring here claimed a substring count "would in fact catch it
    too", which was also false as written (asserted `<= 2`, not `==
    1`). The fix is `== 1`: "home-deadbeef" appears exactly once, in
    `_WARN_NAMESPACES`'s own list repr at the end of the printed line,
    and MEASURED nowhere else in the combined output for either
    scenario, so `== 1` is a real second discriminator, not the same
    check restated.

    Verified by hand during this unit's code gate r1 fold (not itself
    committed -- applied, probe F re-run solo to confirm RED, reverted,
    sha256-diffed byte-identical to before): (1) with
    `pytest_sessionfinish`/`pytest_testnodedown` deleted from the
    SPLICED conftest (`_make_probe_conftest`'s own re-export lines
    removed -- the real conftest.py is untouched), this same scenario
    goes SILENT under `-n 2` (no "cache-litter guard" separator in the
    combined output at all) while the identical scenario re-run with no
    `-n` flag (serial, one process, no worker/controller split) still
    reports it -- proving the silence is specific to the relay's
    absence, not the scenario. (2) with the real `pytest_testnodedown`'s
    dedup (`if namespace not in _WARN_NAMESPACES`) replaced by a plain
    `.extend()`, the SAME `-n 2` scenario reports "2 new real ...
    namespace(s)" for the one real directory, with `home-deadbeef`
    appearing twice in the printed list."""
    scratch_cache = tmp_path / "fake-real-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(scratch_cache))
    marker_dir = tmp_path / "probe-f-markers"
    marker_dir.mkdir()
    monkeypatch.setenv("PROBE_F_MARKER_DIR", str(marker_dir))

    _make_probe_conftest(pytester)
    pytester.makepyfile(
        test_probe_1="""
        import os
        import time
        from pathlib import Path

        from conftest import _REAL_CACHE_ROOT

        def test_probe_1():
            # Structural barrier (code gate r2 nit), not a timing
            # margin: an earlier version had item 2 alone sleep 0.5s
            # before creating, on the theory that this was comfortably
            # longer than xdist's own worker-connection time -- sound
            # (gate-measured worker-start skew: <=1.0 ms unloaded,
            # <=3.0 ms stressed, a ~165x margin), but still statistical.
            # This touches a marker file for THIS worker
            # (`PYTEST_XDIST_WORKER`, e.g. 'gw0'/'gw1') and waits
            # (bounded, 5s) for the OTHER worker's marker to appear
            # before creating the namespace -- both workers' fixture
            # setup (their own `before` scan) has unconditionally
            # already run by the time either test BODY starts, so
            # observing a peer marker here proves both `before` scans
            # are done, structurally, not by a measured margin.
            marker_dir = Path(os.environ["PROBE_F_MARKER_DIR"])
            my_id = os.environ.get("PYTEST_XDIST_WORKER", "solo")
            (marker_dir / my_id).touch()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if any(p.name != my_id for p in marker_dir.iterdir()):
                    break
                time.sleep(0.01)
            foreign = _REAL_CACHE_ROOT / "home-deadbeef"
            os.makedirs(foreign, exist_ok=True)
        """,
        test_probe_2="""
        import os
        import time
        from pathlib import Path

        from conftest import _REAL_CACHE_ROOT

        def test_probe_2():
            # Same structural barrier as test_probe_1 -- see its
            # comment for the rationale.
            marker_dir = Path(os.environ["PROBE_F_MARKER_DIR"])
            my_id = os.environ.get("PYTEST_XDIST_WORKER", "solo")
            (marker_dir / my_id).touch()
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if any(p.name != my_id for p in marker_dir.iterdir()):
                    break
                time.sleep(0.01)
            foreign = _REAL_CACHE_ROOT / "home-deadbeef"
            os.makedirs(foreign, exist_ok=True)
        """,
    )
    result = pytester.runpytest_subprocess("-n", "2")
    combined = "\n".join(result.outlines + result.errlines)
    result.assert_outcomes(passed=2, failed=0, errors=0)
    assert "home-deadbeef" in combined, combined
    assert "1 new real" in combined, combined
    # MINOR-3 fix (code gate r2, 2026-08-29): `<= 2` was INERT for the
    # dedup mutation -- clean measures count 1, doubled measures count 2,
    # and 1 <= 2 and 2 <= 2 both pass, so it discriminated nothing (the
    # docstring above claiming a substring count "would in fact catch it
    # too" was false; only the "1 new real" line above actually did).
    # `== 1` is the real, independently-measured count for the clean
    # scenario -- "home-deadbeef" appears exactly once, inside `_WARN_
    # NAMESPACES`'s own list repr at the end of the printed line, and
    # nowhere else in the combined output. A second, independent
    # discriminator alongside "1 new real" -- both must hold for a pass.
    assert combined.count("home-deadbeef") == 1, combined
    assert "reported but not failed" in combined, combined
    assert (scratch_cache / "self-learn" / "home-deadbeef").is_dir()
