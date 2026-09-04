"""M-E two-process barrier tests (audit C11): the sentinel's ownership
contract only means something if it holds across REAL, independent
processes racing the same file, not just within one interpreter. Every
test here spawns two real subprocesses, synchronised through a file
barrier before either is allowed to call ``sentinel.hold()`` — see
`_run_pair` for the mechanics and `test_barrier_actually_synchronised`
for the positive control proving the barrier itself is not a no-op.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from self_learn import sentinel

#: The subprocess body. Written to a tmp file per test (never committed
#: as a repo module — the armor list pins cli/tests' non-test_*.py set,
#: and this lives under pytest's own tmp_path instead). Each invocation:
#: (1) optionally sleeps before signalling ready (the deliberate stagger
#: `test_barrier_actually_synchronised` needs), (2) writes its own ready
#: marker, (3) busy-waits for the OTHER side's ready marker — barrier #1
#: — (4) calls `sentinel.hold()`, (5) writes a "held" marker and
#: busy-waits for the OTHER side's held marker — barrier #2, which
#: matters: without it, a fast winner can `hold()` AND `.release()`
#: (deleting its own file) before the loser ever calls `hold()` at all,
#: at which point the loser's `hold()` correctly — but misleadingly —
#: also returns owned=True, since by then there is genuinely nothing
#: live to join. Barrier #2 forces both `hold()` calls to land before
#: either side is allowed to `.release()`, so the race under test is the
#: one this move actually closes (two `hold()`s contending), not an
#: artifact of the harness — (6) optionally calls `.release()`, (7)
#: records everything (including monotonic timestamps — comparable
#: across processes on Linux, since CLOCK_MONOTONIC is system-wide, not
#: per-process) as JSON.
_WORKER_SRC = '''
import json
import os
import sys
import time

cfg = json.loads(open(sys.argv[1], encoding="utf-8").read())

from self_learn import sentinel

t_start = time.monotonic()
sleep_before_ready = cfg.get("sleep_before_ready", 0.0)
if sleep_before_ready:
    time.sleep(sleep_before_ready)

ready_path = cfg["ready_path"]
other_ready_path = cfg["other_ready_path"]
with open(ready_path, "w", encoding="utf-8") as f:
    f.write("ready\\n")
t_ready = time.monotonic()

deadline = time.monotonic() + 30.0
while not os.path.exists(other_ready_path):
    if time.monotonic() >= deadline:
        raise SystemExit("barrier 1: other side never became ready")
    # A tight spin, deliberately not `time.sleep()`-throttled: this is
    # the barrier whose exit latency decides how close together the two
    # `hold()` calls land. A polling sleep (even 5ms) turns into a
    # systematic head start for whichever side becomes ready SECOND (it
    # sees the first side's marker immediately and proceeds without ever
    # sleeping, while the first side only notices the second marker on
    # its next sleep-wakeup) -- reliably wide enough that hold()'s own
    # check-then-write critical section finishes before the other side
    # ever calls it, masking the very race this suite exists to expose.
t_barrier = time.monotonic()

held = sentinel.hold()
t_hold = time.monotonic()

held_path = cfg["held_path"]
other_held_path = cfg["other_held_path"]
with open(held_path, "w", encoding="utf-8") as f:
    f.write("held\\n")
deadline2 = time.monotonic() + 30.0
while not os.path.exists(other_held_path):
    if time.monotonic() >= deadline2:
        raise SystemExit("barrier 2: other side never finished hold()")
    time.sleep(0.005)

released = None
if cfg.get("attempt_release", True):
    released = held.release()

# fold r1 (n2): exists()-then-read_text is two separate filesystem
# calls, and the OTHER process's release() can delete the file in the
# gap between them -- read_text would then raise FileNotFoundError and
# crash this worker (a non-zero exit _run_pair asserts against), not
# quietly report None. try/except collapses it back to one call.
try:
    disk_text_after = held.path.read_text(encoding="utf-8")
    path_exists_after = True
except FileNotFoundError:
    disk_text_after = None
    path_exists_after = False

result = {
    "pid": os.getpid(),
    "owned": held.owned,
    "token": held.token,
    "released": released,
    "path_exists_after": path_exists_after,
    "disk_text_after": disk_text_after,
    "t_start": t_start,
    "t_ready": t_ready,
    "t_barrier": t_barrier,
    "t_hold": t_hold,
}
with open(cfg["out_path"], "w", encoding="utf-8") as f:
    json.dump(result, f)
'''


def _run_pair(
    tmp_path: Path,
    *,
    label: str,
    seed_text: str | None = None,
    seed_age_seconds: float | None = None,
    stagger_seconds: float = 0.0,
    attempt_release: bool = True,
) -> tuple[dict, dict, Path]:
    """Spawn two real subprocesses that both target the SAME
    XDG-redirected sentinel path, synchronised through a file barrier so
    neither calls `hold()` until both have signalled ready. Returns
    (result_a, result_b, final_path) — the JSON dicts each subprocess
    recorded, plus the sentinel path itself (see the note on `final_path`
    below for why it is only meaningful once both processes have exited).

    `seed_text`/`seed_age_seconds` pre-populate the sentinel file (and
    optionally backdate its mtime) before either process starts, for the
    TTL-takeover and old-format scenarios. `stagger_seconds` delays
    process A's ready-signal — used by the positive control to prove the
    barrier genuinely blocks B rather than the two processes coincidentally
    finishing close together.
    """
    xdg = tmp_path / f"xdg-{label}"
    (xdg / "self-learn").mkdir(parents=True)
    env = {**os.environ, "XDG_CACHE_HOME": str(xdg)}

    if seed_text is not None:
        seed_path = xdg / "self-learn" / "autosync-pause"
        seed_path.write_text(seed_text, encoding="utf-8")
        if seed_age_seconds is not None:
            past = time.time() - seed_age_seconds
            os.utime(seed_path, (past, past))

    worker_script = tmp_path / f"worker-{label}.py"
    worker_script.write_text(_WORKER_SRC, encoding="utf-8")

    ready_a = tmp_path / f"ready-{label}-a"
    ready_b = tmp_path / f"ready-{label}-b"
    held_a = tmp_path / f"held-{label}-a"
    held_b = tmp_path / f"held-{label}-b"
    out_a = tmp_path / f"out-{label}-a.json"
    out_b = tmp_path / f"out-{label}-b.json"
    cfg_a = tmp_path / f"cfg-{label}-a.json"
    cfg_b = tmp_path / f"cfg-{label}-b.json"

    cfg_a.write_text(
        json.dumps(
            {
                "ready_path": str(ready_a),
                "other_ready_path": str(ready_b),
                "held_path": str(held_a),
                "other_held_path": str(held_b),
                "out_path": str(out_a),
                "attempt_release": attempt_release,
                "sleep_before_ready": stagger_seconds,
            }
        ),
        encoding="utf-8",
    )
    cfg_b.write_text(
        json.dumps(
            {
                "ready_path": str(ready_b),
                "other_ready_path": str(ready_a),
                "held_path": str(held_b),
                "other_held_path": str(held_a),
                "out_path": str(out_b),
                "attempt_release": attempt_release,
                "sleep_before_ready": 0.0,
            }
        ),
        encoding="utf-8",
    )

    proc_a = subprocess.Popen(
        [sys.executable, str(worker_script), str(cfg_a)], env=env
    )
    proc_b = subprocess.Popen(
        [sys.executable, str(worker_script), str(cfg_b)], env=env
    )
    rc_a = proc_a.wait(timeout=60)
    rc_b = proc_b.wait(timeout=60)
    assert rc_a == 0, f"process A exited {rc_a}"
    assert rc_b == 0, f"process B exited {rc_b}"

    result_a = json.loads(out_a.read_text(encoding="utf-8"))
    result_b = json.loads(out_b.read_text(encoding="utf-8"))
    # Both processes have now fully exited, which — since each writes its
    # own JSON result only AFTER its own (possible) `.release()` call
    # returns — means any release either side attempted has already
    # landed. Reading the sentinel path HERE, from the parent, is the
    # final state: unlike each subprocess's own self-reported
    # `path_exists_after` (a snapshot racing the OTHER process's
    # concurrent release, since there is no barrier between "both sides
    # released" and "both sides recorded their own result"), this read
    # has nothing left to race against.
    final_path = xdg / "self-learn" / "autosync-pause"
    return result_a, result_b, final_path


class TestExactlyOneAcquires:
    def test_exactly_one_acquires_and_the_loser_cannot_release(self, tmp_path):
        """Pre-M-E (C11): hold() was check-then-write, so two processes
        racing a FRESH sentinel could both observe "not live" and both
        write, both believing owned=True — and whichever released last
        would delete the other's live file. Post-fix: the flock
        serialises the check-and-publish, so exactly one process may
        ever become owned=True, and the loser's release (gated on its
        own owned=False) never touches the winner's file at all."""
        a, b, final_path = _run_pair(tmp_path, label="fresh")

        owned_flags = [a["owned"], b["owned"]]
        assert sorted(owned_flags) == [False, True]  # exactly one winner

        winner, loser = (a, b) if a["owned"] else (b, a)
        assert winner["token"] is not None
        assert loser["token"] is None
        assert loser["released"] is False  # never had a file to delete
        assert winner["released"] is True  # the winner released its OWN file
        # Both processes have fully exited (both releases, if any, have
        # already landed) — the winner deleted its own file and nothing
        # else ever wrote it, so nothing survives.
        assert not final_path.exists()


class TestTTLTakeover:
    def test_ttl_takeover_happens_once(self, tmp_path):
        """A stale (pre-aged) sentinel from a THIRD, long-gone holder:
        both processes race to take it over. Exactly one may win the
        takeover — the lock makes "is it stale?" and "publish the
        replacement" one atomic decision, so the loser must observe the
        WINNER's fresh publish (live again) rather than independently
        deciding the same stale file is up for grabs."""
        stale_token = "1111111111111111"
        seed = f"pid=1 host=gone started=2020-01-01T00:00:00Z\ntoken={stale_token}\n"
        a, b, _final_path = _run_pair(
            tmp_path,
            label="stale",
            seed_text=seed,
            seed_age_seconds=sentinel.SENTINEL_TTL_SECONDS + 60,
            attempt_release=False,  # inspect the post-takeover file, don't clean it up
        )

        owned_flags = [a["owned"], b["owned"]]
        assert sorted(owned_flags) == [False, True]

        winner, loser = (a, b) if a["owned"] else (b, a)
        assert winner["token"] != stale_token
        assert loser["token"] is None
        # the file left behind is the WINNER's, not a blend of both and
        # not the original stale one.
        assert winner["disk_text_after"] is not None
        assert f"token={winner['token']}" in winner["disk_text_after"]
        assert stale_token not in winner["disk_text_after"]

    def test_displaced_prior_owner_cannot_release_the_winner(
        self, tmp_path, monkeypatch
    ):
        """C11's release half, in a genuinely cross-process scenario: the
        stale sentinel's ORIGINAL owner (long gone, never actually running
        here — we only need the token it would have held) attempts to
        release AFTER the takeover above has landed in real subprocesses.
        A release keyed only on a local `owned=True` boolean would delete
        the winner's live file; this handle's token no longer matches
        what a genuine takeover just published, so `release()` must
        refuse. Constructed directly (no subprocess needed for this
        actor: `SentinelHold.release` reads only `self.path`/`self.token`
        plus whatever is on disk right now — never `sentinel_path()` or
        any other process-local state), but the race it exercises is the
        one two real subprocesses just closed above, not a same-process
        fabrication.

        fold r1 (m3): the stale token is MINTED by a real `sentinel.hold()`
        call (in its own throwaway XDG dir), not a hand-picked literal —
        a hardcoded stale token can never prove `_new_token` actually
        varies; see `TestTokenUniqueness` below for that, which a constant
        `_new_token` would fail even though every other test in this file
        (this one included, if the constant happened to differ from the
        winner's) would still pass."""
        mint_xdg = tmp_path / "xdg-mint"
        monkeypatch.setenv("XDG_CACHE_HOME", str(mint_xdg))
        minted = sentinel.hold()
        assert minted.owned and minted.token is not None
        stale_token = minted.token
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

        seed = f"pid=1 host=gone started=2020-01-01T00:00:00Z\ntoken={stale_token}\n"
        a, b, final_path = _run_pair(
            tmp_path,
            label="stale-release",
            seed_text=seed,
            seed_age_seconds=sentinel.SENTINEL_TTL_SECONDS + 60,
            attempt_release=False,
        )
        winner = a if a["owned"] else b
        assert winner["token"] is not None and winner["token"] != stale_token

        displaced = sentinel.SentinelHold(
            path=final_path, owned=True, token=stale_token
        )
        assert displaced.release() is False
        assert final_path.exists()
        assert f"token={winner['token']}" in final_path.read_text(encoding="utf-8")


class TestTokenUniqueness:
    def test_tokens_are_not_constant_across_independent_holds(self, tmp_path):
        """fold r1 (m3): a constant `_new_token()` would still pass every
        other test in this file — `TestExactlyOneAcquires`/`TestTTLTakeover`
        never compare a winner's token against anything but the (different)
        stale/absent token of the loser or a prior holder, and a constant
        would trivially differ from those literals too. Prove tokens
        actually vary by comparing the winners of two INDEPENDENT
        `_run_pair` calls (each its own fresh XDG dir, its own pair of real
        subprocesses) against each other. Mutation: make `_new_token`
        return a fixed constant -> both winners mint the identical
        "random" token and this fails."""
        a1, b1, _ = _run_pair(tmp_path, label="uniq-1")
        winner_1 = a1 if a1["owned"] else b1
        a2, b2, _ = _run_pair(tmp_path, label="uniq-2")
        winner_2 = a2 if a2["owned"] else b2

        assert winner_1["token"] is not None
        assert winner_2["token"] is not None
        assert winner_1["token"] != winner_2["token"]


class TestOldFormatReadsUnowned:
    def test_old_format_live_file_read_as_unowned_by_both(self, tmp_path):
        """Rollout pin: a LIVE old-format file (no `token=` line — what
        a pre-M-E process writes) is left alone by every new-format
        holder, not just a lucky one. Both processes must decline it,
        and the file must survive byte-for-byte."""
        old_format = "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n"
        a, b, _final_path = _run_pair(
            tmp_path,
            label="oldformat",
            seed_text=old_format,
            seed_age_seconds=None,  # fresh mtime: live
        )

        assert a["owned"] is False
        assert b["owned"] is False
        assert a["token"] is None
        assert b["token"] is None
        assert a["path_exists_after"] is True
        assert a["disk_text_after"] == old_format
        assert b["disk_text_after"] == old_format


class TestBarrierPositiveControl:
    def test_barrier_actually_synchronised(self, tmp_path):
        """Without a real barrier, the (unstaggered) side B would reach
        `sentinel.hold()` almost immediately after starting — well
        before A's deliberately delayed ready-signal. If the barrier
        works, B's wait loop instead blocks until A's ready marker
        appears, so B cannot cross the barrier before A signals ready.
        Proves the harness's synchronisation is real, not a coincidence
        of process-scheduling timing."""
        stagger = 0.3
        a, b, _final_path = _run_pair(tmp_path, label="barrier", stagger_seconds=stagger)

        # A deliberately slept `stagger` seconds before writing its own
        # ready marker.
        assert a["t_ready"] - a["t_start"] >= stagger * 0.8
        # B must not have crossed the barrier before A became ready —
        # cross-process comparable because CLOCK_MONOTONIC is
        # machine-wide on Linux, not per-process.
        assert b["t_barrier"] >= a["t_ready"] - 0.05
        # ...and, symmetrically, B did have to actually wait for it (not
        # just start late for unrelated reasons):
        assert b["t_barrier"] - b["t_ready"] >= stagger * 0.5
