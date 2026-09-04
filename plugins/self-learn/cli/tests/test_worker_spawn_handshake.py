"""Sprint 1 lane L9, move M-T — the C17 spawn handshake.

`worker._open_window` used to spawn the child (`_spawn_window`) and write
its pid to `worker.window` only afterwards: a crash (or the whole process
getting SIGKILLed) in that gap left no window on disk at all, so a later
kick saw nothing live and spawned a SECOND worker alongside the detached
first one. The fix writes a durable "spawning" marker into `worker.window`
(temp + rename + fsync, `worker._write_window_durable`) BEFORE ever
calling `_spawn_window`, so a crash in the gap still leaves proof on disk;
a later kick that finds a fresh marker reports ``absorbed-race`` instead
of racing a double spawn.

A marker older than `worker.SPAWN_MARKER_DEADLINE_SECS` is reclaimed as
an abandoned attempt. As of fold r3 this deadline is a fixed, startup-
scale number, NOT `coalesce_secs(home) + margin` — the spawned child now
registers its own real pid (`worker._register_running_pid`, fold r2)
before its coalesce sleep and before `worker.lock`, so a live, coalescing
child no longer sits behind a bare marker for the length of its own
sleep; the deadline only needs to cover a crash between `Popen` returning
(parent side) and that registration write landing (child side) —
interpreter startup and one import, not a multi-minute coalesce window.

This file exercises ONLY that handshake, at the `worker._open_window` /
`worker.kick` level, against a bare XDG cache namespace — it never needs a
real ledger (git) home, since `worker.cache_dir()` only hashes the
resolved home PATH (`ledger.resolve_home`), never reads it. It does not
import from `tests/test_worker.py` (armor-pinned; that file is run
unchanged alongside this one). Two tests call `worker.run()` directly:
`test_run_registers_the_pid_before_the_coalesce_sleep_and_the_lock`
(fold r3), which observes ORDER between its first few statements and
stops it there, and
`test_a_failed_registration_is_logged_and_does_not_abort_run` (fold r4),
which lets it run to completion against the fake `home` (an idle run: no
`worker.dirty`, so no follow-on spawn); see each test's own docstring.

Fold history: **r1** (audit 2026-09-02 gate, 1 MAJOR + 1 MINOR + 3 NIT)
folded MAJOR 1 (an exception out of `_spawn_window` now leaves no marker
behind), NIT 1 (`_write_window_durable` cleans up its own temp file on a
mid-write failure), and NIT 2 (the D3 ceiling check moved ahead of the
marker write) — MINOR 1 (child self-registration) was BLOCKED, deferred,
because it required one `tests/test_lock_invariant.py` line that r1's
DONE WHEN forbade. **r2** shipped MINOR 1 once the coordinator confirmed
that file's `NOT_REPO_TRUTH` allowlist may take exactly one new entry per
lane — but proved only that `run()` calls the registration function
somewhere, not that it runs before the coalesce sleep and the lock,
which is the entire point of MINOR 1. **r3** closes that: pins the
order with a real test, and rewrites the deadline rationale and value
now that the child registers at startup rather than after its own
coalesce sleep (see the paragraph above). **r4** (this state; an
integration find, not a gate round) makes the registration BEST-EFFORT:
an `OSError` out of the window write is logged and swallowed, because
the armor-pinned `tests/test_attrib.py` IN8 test patches `os.replace`
globally and the escaping error aborted `worker.run()` on the merged
sprint tree.
"""

from __future__ import annotations

import contextlib
import fcntl
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
    once `_spawn_window` is mocked, as it is in every test below except
    the fold-r4 run-to-completion test, whose idle `run()` never reaches
    `_open_window` because no `worker.dirty` exists).
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
    stale(window): return "absorbed-race"` staleness check in
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
    and report `absorbed-race` for up to `SPAWN_MARKER_DEADLINE_SECS`,
    even though no child was ever spawned to eventually clear it — C17's
    double-spawn risk inverted into a permanent-refusal risk.

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
    `SPAWN_MARKER_DEADLINE_SECS`). This test
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
    """A marker older than `worker.SPAWN_MARKER_DEADLINE_SECS` is an
    abandoned attempt (the writer died before registering or removing
    it) — a later kick must reclaim the window and actually spawn, not
    absorb forever. The deadline is read from `worker.SPAWN_MARKER_
    DEADLINE_SECS` rather than a literal number so this test holds even
    if that constant's value changes.

    Mutation that proves this bites: replacing the ``if not
    _spawn_marker_stale(window): return "absorbed-race"`` branch
    with an unconditional ``return "absorbed-race"`` (i.e. treating
    every marker as permanently live) fails this test — the outcome
    would be ``"absorbed-race"``, not the asserted ``"spawned"``, and
    the mocked `_spawn_window` (which would prove a real reclaim
    happened) would never be reached at all."""
    window = _window(home)
    worker._write_window_durable(window, worker._SPAWN_MARKER)
    stale_mtime = time.time() - worker.SPAWN_MARKER_DEADLINE_SECS - 5
    os.utime(window, (stale_mtime, stale_mtime))

    real_pid = os.getpid()
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: real_pid
    )
    outcome = worker._open_window(home)
    assert outcome == "spawned"
    assert window.read_text(encoding="utf-8").strip() == str(real_pid)


def test_marker_is_reclaimed_independent_of_the_coalesce_window(home, monkeypatch):
    """Fold r3 (MINOR 1 + NIT 3) replaces `test_marker_survives_at_
    least_the_coalesce_window` (pre-r3: proved a marker must survive at
    least `coalesce_secs(home)` before reclaim, since the child used to
    clear it only after its own coalesce sleep). That premise is now
    FALSE: the child registers its own pid at startup (fold r2), before
    its coalesce sleep even begins, so a bare marker outliving
    `SPAWN_MARKER_DEADLINE_SECS` means the child crashed before
    registering — full stop, regardless of how long the configured
    coalesce window is. A LARGE configured coalesce window (600s) must
    NOT extend the deadline: a marker aged just past `SPAWN_MARKER_
    DEADLINE_SECS` is reclaimed anyway.

    Mutation that proves this bites: reintroducing `coalesce_secs(home)`
    into `_spawn_marker_stale`'s formula (e.g. `age >= coalesce_secs
    (home) + SPAWN_MARKER_DEADLINE_SECS`) fails this test — with a 600s
    coalesce window, a marker aged `SPAWN_MARKER_DEADLINE_SECS + 5`
    would no longer be stale, and `_open_window` would report
    `absorbed-race` (reaching the guarded `_spawn_window`) instead of
    the asserted `spawned`."""
    monkeypatch.setenv("SELF_LEARN_COALESCE_SECS", "600")
    window = _window(home)
    worker._write_window_durable(window, worker._SPAWN_MARKER)
    aged_mtime = time.time() - worker.SPAWN_MARKER_DEADLINE_SECS - 5
    os.utime(window, (aged_mtime, aged_mtime))

    real_pid = os.getpid()
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: real_pid
    )
    outcome = worker._open_window(home)
    assert outcome == "spawned"
    assert window.read_text(encoding="utf-8").strip() == str(real_pid)


# ------------------------------------------------- child self-registration


def test_a_registered_child_absorbs_a_later_kick_as_a_live_pid_not_a_marker(
    home, monkeypatch
):
    """Fold r2 MINOR 1: the spawned child registers its own pid
    (`worker._register_running_pid`) early in `run()`, before its
    coalesce sleep and before `worker.lock` (order proven by the
    companion test below, fold r3) — bounding the marker's exposure to
    child STARTUP instead of the multi-minute window a bare marker
    could otherwise sit for. Simulates the sequence directly: the
    parent's marker write (`_open_window`/`_spawn_window`, not
    re-exercised here — see the crash tests above), then the child's
    own registration call, exactly as `run()` performs it.

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


def test_run_registers_the_pid_before_the_coalesce_sleep_and_the_lock(
    home, monkeypatch
):
    """Fold r3 MAJOR 1: MINOR 1's whole fix only matters if the ORDER
    holds — `_register_running_pid()` must run before BOTH the coalesce
    sleep and the `worker.lock` acquisition, or a kick can still reclaim
    the marker while the (not-yet-registered) child is asleep or
    waiting on the lock, exactly the race MINOR 1 exists to close.
    Fold r2's wiring test only proved `run()` calls the function
    somewhere before a spy-raised exception aborts it — never that the
    sleep and the lock come strictly AFTER it, which is the entire
    point. This test records a timeline instead: `time.sleep` and
    `fcntl.flock` are wrapped, not replaced (`run()` still needs to
    actually reach and pass the lock to keep going, and a follow-on
    `worker.spawn.lock` acquisition inside `_open_window` — never
    reached here, since `home` fails before then — would otherwise also
    need real behavior), each appending an event before delegating to
    the real call; `_register_running_pid` is wrapped the same way.
    `coalesce=True` forces the sleep branch to actually execute;
    `SELF_LEARN_COALESCE_SECS=0` keeps the (real, delegated) sleep from
    costing any wall-clock time. `run()` is let run past the lock into
    its real body, which fails fast against the fake `home` (empirically
    confirmed by fold r2's own mutation run, which reached this same
    depth without hanging) — `contextlib.suppress(Exception)` absorbs
    whatever ordinary exception that raises, or doesn't; only the
    recorded timeline is asserted. `Exception`, not `BaseException`
    (fold nits NIT 1): a bare `BaseException` also swallows
    `KeyboardInterrupt`/`SystemExit`, which this test has no business
    intercepting — nothing about "let run() fail against the fake home"
    needs those.

    `recording_flock` (fold nits NIT 2) records a `"lock"` event only
    for the flock call whose fd resolves (`/proc/self/fd/<fd>`) to a
    path ending in `worker.lock` — the SPECIFIC lock this test's name
    and docstring are about — not just whichever flock call happens
    first. Today `worker.lock`'s is the only flock call `run()` reaches
    before failing against the fake `home`, so an unfiltered "first
    flock call" wrapper currently means the same thing; the filter
    exists so a FUTURE flock call earlier in `run()` (a new lock, a
    lint/audit hook, anything) can't silently satisfy this test's
    `"lock"` slot while the real `worker.lock` vs. registration order
    goes unchecked.

    Mutation that proves this bites: moving `run()`'s
    `_register_running_pid()` call to AFTER the `if coalesce:
    time.sleep(...)` block (still before `worker.lock`) fails this test
    — `"sleep"` appears before `"register"` in the recorded timeline."""
    events: list[str] = []

    real_sleep = time.sleep

    def recording_sleep(seconds: float) -> None:
        events.append("sleep")
        real_sleep(0)

    monkeypatch.setattr(worker.time, "sleep", recording_sleep)

    real_flock = fcntl.flock

    def recording_flock(fd, op, *args, **kwargs):
        if "lock" not in events:
            try:
                fd_path = os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                fd_path = ""
            if fd_path.endswith("worker.lock"):
                events.append("lock")
        return real_flock(fd, op, *args, **kwargs)

    monkeypatch.setattr(worker.fcntl, "flock", recording_flock)

    real_register = worker._register_running_pid

    def recording_register() -> None:
        events.append("register")
        real_register()

    monkeypatch.setattr(worker, "_register_running_pid", recording_register)

    monkeypatch.setenv("SELF_LEARN_COALESCE_SECS", "0")
    with contextlib.suppress(Exception):
        worker.run(home, coalesce=True)

    assert events[:3] == ["register", "sleep", "lock"]


def test_a_failed_registration_is_logged_and_does_not_abort_run(home, monkeypatch):
    """Fold r4 (integration find, gate on the merged tree): registration
    is BEST-EFFORT — an `OSError` out of `_write_window_durable`'s
    `os.replace` call (disk full, a permission error, or — measured
    live — the armor-pinned `test_attrib.py::test_in8_interrupted_
    install_is_recovered_not_stalled_forever` part (e), which
    monkeypatched `os.replace` GLOBALLY to simulate a crash mid-install-
    copy until the 2026-09-04 integration scoping, so this function's
    write shared the fake)
    must never abort the whole `worker.run()`. This test reproduces that
    shape — `os.replace` patched to fail for the window write, `worker.run(home)`
    called directly (not `_register_running_pid()` in isolation), the
    same call the real armor-pinned test makes — and checks the THREE
    things `_register_running_pid`'s fix promises: `run()` does not
    raise, the skip is logged (not silent), and no `.worker.window.
    <pid>.tmp` litter survives (already guaranteed by fold r1 NIT 1's
    cleanup inside `_write_window_durable` itself — this test re-proves
    it end-to-end through `run()`, not just the unit call).

    Mutation that proves this bites: removing the `try: ... except
    OSError as exc: log(...)` wrapper from `_register_running_pid`
    (letting the OSError propagate) fails this test — `worker.run(home)`
    raises `OSError("simulated os.replace crash")` instead of returning
    normally."""

    real_replace = os.replace

    def raising_replace(src, dst):
        # Scoped to the window write (2026-09-04 integration find): a
        # global fake also trips M-E's sentinel publish later in run(),
        # which is not this test's subject.
        if Path(dst).name == "worker.window":
            raise OSError("simulated os.replace crash")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", raising_replace)

    try:
        worker.run(home)
    except Exception as exc:  # pragma: no cover - failure path only
        pytest.fail(f"run() must not raise when pid registration fails: {exc!r}")

    log_path = worker.cache_dir() / "worker.log"
    assert log_path.is_file()
    assert "pid registration skipped" in log_path.read_text(encoding="utf-8")

    window = _window(home)
    leftovers = list(window.parent.glob(f".{window.name}.*.tmp"))
    assert leftovers == []


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
