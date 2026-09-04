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


def test_marker_written_durably_before_a_crashed_spawn(home, monkeypatch):
    """A crash INSIDE `_spawn_window` (the only realistic stand-in, in a
    single-process test, for the parent getting SIGKILLed between the
    marker write and the pid rewrite: a real crash never runs `_open_
    window`'s own `finally`-unlock either, so the exception path here is
    the closest same-process analogue) must still leave the marker on
    disk — that is the entire point of writing it BEFORE the spawn
    instead of the pid AFTER it.

    Mutation that proves this bites: reverting `_open_window` to its
    pre-M-T shape (spawn first, `window.write_text(pid)` only after)
    fails this test — the original code writes NOTHING to `worker.window`
    until `_spawn_window` returns, so a crash inside it leaves the file
    absent, not marked."""

    def crash(home, *, no_push=False):
        raise RuntimeError("simulated crash between marker and spawn")

    monkeypatch.setattr(worker, "_spawn_window", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        worker._open_window(home)
    window = _window(home)
    assert window.is_file()
    assert window.read_text(encoding="utf-8").strip() == worker._SPAWN_MARKER


def test_fresh_marker_absorbs_a_later_kick_instead_of_double_spawning(
    home, monkeypatch
):
    """After the crash above, the flock is released (the dead writer no
    longer holds it — same as a real SIGKILL) but the marker survives.
    A LATER `_open_window` call — the crash-recovery kick, or a
    concurrent one that lost the race for entirely different reasons —
    must not attempt a second spawn while the marker is still fresh: the
    first (detached, `start_new_session=True`) child may well still be
    alive and about to write its own pid.

    Mutation that proves this bites: reverting to pre-M-T `_open_window`
    fails this test two ways — the marker was never written in the first
    place (see the test above), so this second call sees an empty
    `worker.window` and proceeds straight to `_spawn_window`, which is
    guarded here with `pytest.fail` precisely to catch a double spawn."""

    def crash(home, *, no_push=False):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "_spawn_window", crash)
    with pytest.raises(RuntimeError):
        worker._open_window(home)

    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "must not spawn a second worker while the marker is fresh"
        ),
    )
    assert worker._open_window(home) == "absorbed-race"


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
