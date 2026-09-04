"""Sprint 1 lane L9, move M-T — the C17 spawn handshake.

`worker._open_window` used to spawn the child (`_spawn_window`) and write
its pid to `worker.window` only afterwards: a crash (or the whole process
getting SIGKILLed) in that gap left no window on disk at all, so a later
kick saw nothing live and spawned a SECOND worker alongside the detached
first one. The fix writes a durable "spawning" marker into `worker.window`
(temp + rename + fsync, `worker._write_window_durable`) BEFORE ever
calling `_spawn_window`, so a crash in the gap still leaves proof on disk;
a later kick that finds a fresh marker reports ``absorbed-race`` instead
of racing a double spawn, and a marker older than
``worker.coalesce_secs(home) + worker.SPAWN_MARKER_DEADLINE_MARGIN_SECS``
is reclaimed as an abandoned attempt — the coalesce floor matters because
the ONE realistic way a marker outlives a plain Popen call is a crash
between `Popen` returning and the immediate pid-rewrite that follows it,
and in that case the already-launched detached child is what eventually
clears `worker.window`, only after its OWN coalesce sleep ends.

This file exercises ONLY that handshake, at the `worker._open_window` /
`worker.kick` level, against a bare XDG cache namespace — it never needs a
real ledger (git) home, since `worker.cache_dir()` only hashes the
resolved home PATH (`ledger.resolve_home`), never reads it. It does not
import from `tests/test_worker.py` (armor-pinned; that file is run
unchanged alongside this one).

Fold r1 (audit 2026-09-02 gate, one MAJOR + one MINOR + three NIT):
folds MAJOR 1 (an exception out of `_spawn_window` now leaves no marker
behind — the two original crash-simulation tests are rewritten to
construct the real crash state directly on disk instead of raising a
Python exception, which only ever modeled a HANDLED outcome; a new test
covers the exception case itself), NIT 1 (`_write_window_durable` now
cleans up its own temp file on a mid-write failure), and NIT 2 (the D3
ceiling check moved ahead of the marker write in `_open_window`, so a
certain refusal never writes one). MINOR 1 (the spawned child
self-registering its own pid at startup) is DEFERRED — see
`misc/audit-2026-09-02/sprint-1/build-worker-spawn.md`'s "Fold r1"
section for why it conflicts with `tests/test_lock_invariant.py`, which
this fold may not edit.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from self_learn import worker


@pytest.fixture()
def home(tmp_path, monkeypatch) -> Path:
    """A minimal ledger-home PATH for spawn-handshake tests. Only
    `worker.cache_dir()`'s XDG-cache bookkeeping (`worker.window`,
    `worker.spawn.lock`) is exercised here, never the ledger itself, so
    `home` need not exist or be a git repo — but every function under
    test still takes one (it rides into a real spawn's `cwd`, irrelevant
    once `_spawn_window` is mocked, as it is in every test below).
    Explicit `SELF_LEARN_HOME`/`XDG_CACHE_HOME` redirection (rather than
    relying on `tests/conftest.py`'s autouse `_worker_test_defaults`)
    keeps this file self-contained and independent of fixture ordering."""
    h = tmp_path / "ledger-home"
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return h


def _window(home: Path) -> Path:
    return worker.cache_dir() / "worker.window"


# --------------------------------------------------------- marker durability


def test_a_marker_left_by_a_real_crash_absorbs_a_later_kick(home, monkeypatch):
    """Fold MAJOR 1 rewrite (audit 2026-09-02 gate r1): the ORIGINAL
    versions of this pair of tests modeled "crash between the marker
    write and the pid rewrite" as a Python exception raised INSIDE
    `_spawn_window` — but that models a HANDLED non-spawn outcome (fold
    MAJOR 1's own `except BaseException: window.unlink(...); raise`
    cleans the marker up and re-raises), not the real crash the marker
    exists to survive. A real SIGKILL never runs any of `_open_window`'s
    Python code afterwards, handled or not — it just stops, mid-critical
    -section, with whatever was durably on disk at that instant. The
    true crash state is constructed directly here instead: the marker
    written (`_write_window_durable`, the same durable helper `_open_
    window` itself uses) and nothing else touched — no `_spawn_window`
    call, no `_open_window` call, no exception anywhere. (A real crash
    also releases the `worker.spawn.lock` flock automatically — the
    kernel drops it when the holding process's last fd closes — so the
    later `_open_window` call below reaches its ordinary fresh-marker
    check, not the held-lock one.)

    Mutation that proves this bites: replacing the `if not _spawn_marker_
    stale(window, home): return "absorbed-race"` staleness check in
    `_open_window` with a bare `pass` (the fresh marker is recognized
    but no longer short-circuits absorption) fails this test — the
    marker constructed here falls straight through to the guarded
    `_spawn_window` call, reddening with `Failed: must not spawn a
    second worker while a crash-left marker is fresh`."""
    window = _window(home)
    worker._write_window_durable(window, worker._SPAWN_MARKER)
    assert window.read_text(encoding="utf-8").strip() == worker._SPAWN_MARKER

    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "must not spawn a second worker while a crash-left marker is fresh"
        ),
    )
    assert worker._open_window(home) == "absorbed-race"


def test_an_exception_from_spawn_window_leaves_no_marker_and_the_next_kick_spawns(
    home, monkeypatch
):
    """Fold MAJOR 1 (new test, audit 2026-09-02 gate r1): an exception
    out of `_spawn_window` ITSELF (a failed `Popen`, ENOSPC on its log
    open, a missing interpreter) is a HANDLED non-spawn outcome —
    `_open_window`'s `except BaseException: window.unlink(missing_ok=
    True); raise` removes the marker and re-raises, exactly like the
    `pid <= 0` (depth-limited) branch just below it in the source. Left
    un-cleaned, EVERY later kick would read the leftover marker as fresh
    and report `absorbed-race` for up to `coalesce_secs(home) +
    SPAWN_MARKER_DEADLINE_MARGIN_SECS`, even though no child was ever
    spawned to eventually clear it — C17's double-spawn risk inverted
    into a permanent-refusal risk.

    Mutation that proves this bites: removing the `except BaseException:
    window.unlink(missing_ok=True); raise` wrapper around the
    `_spawn_window(...)` call in `_open_window` (letting the exception
    propagate with the marker still on disk) fails this test — the
    marker survives the raise, and the follow-up kick reads it as fresh
    and returns `absorbed-race` instead of the asserted `spawned`."""

    def boom(home, *, no_push=False):
        raise RuntimeError("simulated Popen failure")

    monkeypatch.setattr(worker, "_spawn_window", boom)
    with pytest.raises(RuntimeError, match="simulated Popen failure"):
        worker._open_window(home)
    window = _window(home)
    assert not window.exists()

    real_pid = os.getpid()
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: real_pid
    )
    assert worker._open_window(home) == "spawned"
    assert window.read_text(encoding="utf-8").strip() == str(real_pid)


def test_write_window_durable_cleans_up_its_temp_file_on_a_mid_write_failure(
    home, monkeypatch
):
    """Fold NIT 1 (audit 2026-09-02 gate r1): a failure between creating
    the temp file and the rename (disk full mid-write, a permission
    error) must not leave `.worker.window.<pid>.tmp` litter behind for a
    later run to trip over. Faking the FIRST `os.fsync` call (the temp
    file's data fsync, before `os.replace` ever runs) to raise models
    exactly that gap; the second call (the directory-entry fsync after
    a successful rename) is left real so an unrelated write later in the
    suite is not silently broken by this monkeypatch.

    Mutation that proves this bites: removing the `except BaseException:
    tmp.unlink(missing_ok=True); raise` wrapper in `_write_window_
    durable` (letting a mid-write failure propagate with the temp file
    still on disk) fails this test — the glob below finds the leftover
    `.tmp` file instead of an empty list."""
    window = _window(home)
    real_fsync = os.fsync
    calls = {"n": 0}

    def flaky_fsync(fd):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated disk-full mid-write")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", flaky_fsync)
    with pytest.raises(OSError, match="simulated disk-full"):
        worker._write_window_durable(window, "irrelevant")

    leftovers = list(window.parent.glob(f".{window.name}.*.tmp"))
    assert leftovers == []
    assert not window.exists()


# ------------------------------------------------------- non-spawn cleanup


def test_marker_removed_on_a_depth_limited_refusal(home, monkeypatch):
    """`_spawn_window` refusing under the D3 chain-depth ceiling (returns
    <= 0, never actually spawning) is a non-spawn outcome: the marker
    written just before the call must not survive it, or a later kick
    would read a permanently-fresh "spawning" marker as an in-flight spawn
    that will never resolve, wedging real kicks shut forever.

    Mutation that proves this bites: deleting the
    `window.unlink(missing_ok=True)` line from `_open_window`'s
    `pid <= 0` branch (keeping the marker-write step intact) fails this
    test — `worker.window` would still hold ``"spawning"`` afterwards
    instead of being gone."""
    monkeypatch.setattr(worker, "_spawn_window", lambda home, *, no_push=False: -1)
    outcome = worker._open_window(home)
    assert outcome == "depth-limited"
    assert not _window(home).exists()


def test_open_window_never_touches_the_window_at_the_real_ceiling(home, monkeypatch):
    """Fold NIT 2 (audit 2026-09-02 gate r1): the D3 chain-depth ceiling
    check (`_ceiling_refused`) now runs in `_open_window` BEFORE the
    marker is ever written — a certain refusal must never see a marker
    on disk at all, not even transiently (a SIGKILL landing between an
    earlier marker-write and the ceiling check would otherwise strand an
    un-clearable marker with no child anywhere, reclaimed only after
    `coalesce_secs(home) + SPAWN_MARKER_DEADLINE_MARGIN_SECS`). This test
    sets the REAL env var (`worker.FOLLOWON_DEPTH_ENV`) to the REAL
    ceiling (`worker.FOLLOWON_DEPTH_CEILING`) rather than mocking
    `_spawn_window` to return `-1` (as the test above does) — and guards
    `_spawn_window` with `pytest.fail`, so this also proves `_open_
    window` refuses BEFORE ever calling it, not merely reacts after.

    Mutation that proves this bites: deleting the `if _ceiling_refused():
    return "depth-limited"` pre-check fold NIT 2 added to `_open_window`
    (leaving only `_spawn_window`'s own internal check) fails this test
    two ways at once — `worker.window` would transiently hold the marker
    (written before the call), and `_spawn_window` itself would be
    called (hitting the `pytest.fail` guard) instead of being refused
    before ever being reached."""
    monkeypatch.setenv(worker.FOLLOWON_DEPTH_ENV, str(worker.FOLLOWON_DEPTH_CEILING))
    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "must refuse before ever calling _spawn_window at the real ceiling"
        ),
    )
    outcome = worker._open_window(home)
    assert outcome == "depth-limited"
    assert not _window(home).exists()


# ---------------------------------------------------------- stale reclaim


def test_stale_marker_is_reclaimed_past_the_deadline(home, monkeypatch):
    """A marker older than ``coalesce_secs(home) +
    SPAWN_MARKER_DEADLINE_MARGIN_SECS`` is an abandoned attempt (the
    writer died before rewriting or removing it) — a later kick must
    reclaim the window and actually spawn, not absorb forever. The
    deadline is computed from `worker.coalesce_secs`/`worker.
    SPAWN_MARKER_DEADLINE_MARGIN_SECS` rather than a literal number so
    this test holds regardless of the suite's own coalesce default.

    Mutation that proves this bites: replacing the ``if not
    _spawn_marker_stale(window, home): return "absorbed-race"`` branch
    with an unconditional ``return "absorbed-race"`` (i.e. treating
    every marker as permanently live) fails this test — the outcome
    would be ``"absorbed-race"``, not the asserted ``"spawned"``, and
    the mocked `_spawn_window` (which would prove a real reclaim
    happened) would never be reached at all."""
    window = _window(home)
    worker._write_window_durable(window, worker._SPAWN_MARKER)
    deadline = worker.coalesce_secs(home) + worker.SPAWN_MARKER_DEADLINE_MARGIN_SECS
    stale_mtime = time.time() - deadline - 5
    os.utime(window, (stale_mtime, stale_mtime))

    real_pid = os.getpid()
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: real_pid
    )
    outcome = worker._open_window(home)
    assert outcome == "spawned"
    assert window.read_text(encoding="utf-8").strip() == str(real_pid)


def test_marker_survives_at_least_the_coalesce_window(home, monkeypatch):
    """The crash-after-Popen case: a SIGKILL strictly between `Popen`
    returning and the immediate pid-rewrite that follows it leaves the
    ALREADY-LAUNCHED detached child alive, coalescing — and that child,
    not a later kick, is what eventually clears `worker.window` (only
    after ITS OWN `coalesce_secs` sleep ends and it takes `worker.lock`).
    A marker aged past a fixed short deadline but still within the
    CURRENT `coalesce_secs(home)` must not be reclaimed, or a second kick
    spawns a second worker while the first is still alive and asleep —
    exactly the double-spawn C17 exists to prevent.

    Mutation that proves this bites: computing the deadline from a flat
    constant (e.g. the pre-fix ``SPAWN_MARKER_DEADLINE_SECS = 60.0``)
    instead of `coalesce_secs(home) + SPAWN_MARKER_DEADLINE_MARGIN_SECS`
    fails this test — 90s exceeds a flat 60s deadline, so `_open_window`
    would reclaim and reach the guarded `_spawn_window` below."""
    monkeypatch.setenv("SELF_LEARN_COALESCE_SECS", "120")
    window = _window(home)
    worker._write_window_durable(window, worker._SPAWN_MARKER)
    # 90s old: past a flat 60s deadline, but well inside a 120s coalesce
    # window (the child that already exists has not even reached its own
    # `worker.lock` acquisition yet).
    aged_mtime = time.time() - 90
    os.utime(window, (aged_mtime, aged_mtime))
    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "must not spawn while the first detached child is still coalescing"
        ),
    )
    assert worker._open_window(home) == "absorbed-race"


# ------------------------------------------------- child self-registration


def test_a_registered_child_absorbs_a_later_kick_as_a_live_pid_not_a_marker(
    home, monkeypatch
):
    """Fold r2 MINOR 1: the spawned child registers its own pid
    (`worker._register_running_pid`) at the very start of `run()`,
    before its coalesce sleep and before `worker.lock` — bounding the
    marker's exposure to child STARTUP instead of the whole
    `coalesce_secs(home)` sleep that follows (the old floor, still the
    safety net for a child that dies before registering). Simulates the
    sequence directly: the parent's marker write
    (`_open_window`/`_spawn_window`, not re-exercised here — see the
    crash tests above), then the child's own registration call, exactly
    as `run()` performs it as its very first act (see the companion
    wiring test below for proof `run()` actually calls it there).

    Mutation that proves this bites: replacing `_register_running_pid`'s
    body with a no-op fails this test — `worker.window` would still hold
    the "spawning" marker, `_open_window` would judge it by
    `_spawn_marker_stale`'s deadline heuristic instead of `_pid_alive`,
    and (since it is still fresh) report `absorbed-race`, not the
    asserted `absorbed-window`."""
    window = _window(home)
    worker._write_window_durable(window, worker._SPAWN_MARKER)

    worker._register_running_pid()  # exactly what run() does, first thing

    assert window.read_text(encoding="utf-8").strip() == str(os.getpid())

    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "a registered live pid must absorb the kick without spawning"
        ),
    )
    assert worker._open_window(home) == "absorbed-window"


def test_run_calls_register_running_pid_before_anything_else(home, monkeypatch):
    """Wiring check, companion to the test above: `run()` must call
    `_register_running_pid()` as literally its first act — before the
    coalesce sleep, before `worker.lock`, before the sentinel hold and
    `_cache_clear("worker.window")` that immediately follows taking that
    lock (which would otherwise erase the very pid the previous test
    proves gets written). A spy replacing `_register_running_pid` raises
    immediately once called, aborting `run()` before it ever needs a
    real git ledger `home` — this file otherwise never exercises `run()`
    itself, exactly because of that `_cache_clear` call.

    Mutation that proves this bites: deleting the `_register_running_
    pid()` call from `run()` (fold r2's "drop the self-registration"
    case, as opposed to gutting the function's own body, which the test
    above already covers) fails this test — the spy is never invoked, so
    `run()` proceeds unaborted (either completing against the non-git
    `home` or raising some OTHER, unrelated exception), and
    `pytest.raises(RuntimeError, match="stop-after-registration")` does
    not see the expected exception."""
    calls: list[bool] = []

    def spy() -> None:
        calls.append(True)
        raise RuntimeError("stop-after-registration")

    monkeypatch.setattr(worker, "_register_running_pid", spy)
    with pytest.raises(RuntimeError, match="stop-after-registration"):
        worker.run(home)
    assert calls == [True]


# --------------------------------------------------------- positive control


def test_kick_still_records_a_real_pid_through_the_full_handshake(
    home, monkeypatch
):
    """Positive control: the ordinary (no-crash) path still ends with the
    marker rewritten to a REAL, alive pid — not left as ``"spawning"`` —
    and that pid then absorbs a second kick exactly as before M-T. A real
    (`os.getpid()`), not fabricated, pid is used so `_pid_alive` is
    genuinely exercised, the same convention `tests/test_worker.py`'s own
    `_spawn_window` fakes use.

    Mutation that proves this bites: dropping the SECOND
    `_write_window_durable(window, str(pid))` call (the rewrite-with-pid
    step) after a successful spawn fails this test — `worker.window`
    would still read back ``"spawning"`` instead of the real pid."""
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)
    real_pid = os.getpid()
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: real_pid
    )
    assert worker.kick(home) == "spawned"
    window = _window(home)
    assert window.read_text(encoding="utf-8").strip() == str(real_pid)
    # the marker's job is done; ordinary pid-liveness absorption resumes.
    assert worker.kick(home) == "absorbed-window"
