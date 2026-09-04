"""``RealRunner`` tests (task U4 — 10 §3's "Verb runner" row / 09 §3
"Verb invocation"): the serialized async subprocess queue that replaces
U3's seam stub. Every subprocess-spawning test drives the PATH/
``argv_prefix``-shimmed fake ``self-learn`` in
``tests/fixtures/fake_self_learn.py`` (10 §0 rule 7 — no real CLI
invocation, no network, no real ledger) — mirrors
``tests/test_engine_sdk.py``'s ``fake_claude.py`` convention.

Covers: serialization (two concurrent submissions -> strictly sequential
subprocess spawns), the exact argv shapes for every pinned verb
(route/reject/defer/graduate/confirm-recurrence ± --tolerate/link
contradicts/followup done/route --collapse — P3-2), the bulk-graduate
loop end-to-end through the REAL routes.py endpoint with a REAL runner
(--no-push sequence + terminal push on success AND on abort-at-item-N +
halt-with-failing-id), the interrupt-first dispatch race (P1-4), non-zero
exit -> stderr surfaced verbatim, and the forced refresh push after every
verb. PATH resolution itself (vs. direct argv_prefix injection) gets one
dedicated test.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.routes import build_argv
from self_learn_ui.runner import (
    RealRunner,
    RunResult,
    SELF_LEARN_BIN_ENV,
    communicate_bounded,
    extract_record_id,
    resolve_self_learn_argv_prefix,
)

from support import make_behavior, make_env, seed_proposal, seed_record

FAKE_SELF_LEARN = Path(__file__).parent / "fixtures" / "fake_self_learn.py"
assert FAKE_SELF_LEARN.exists(), "fake_self_learn.py fixture is missing"

TOKEN = "test-token"


# ------------------------------------------------------- fake-binary helpers


def _direct_prefix() -> list[str]:
    """Bypass PATH/resolution entirely — the simplest, most hermetic way
    to point a :class:`RealRunner` at the fake binary."""
    return [sys.executable, str(FAKE_SELF_LEARN)]


def _read_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]


_EXEC_MODE = stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH


def _hermetic_bindir_with_self_learn(tmp_path: Path) -> Path:
    """A PATH dir containing ONLY an executable named ``self-learn`` (the
    fake, symlinked in) — for the one test that exercises genuine PATH
    resolution rather than direct argv_prefix injection."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    link = bindir / "self-learn"
    link.symlink_to(FAKE_SELF_LEARN)
    return bindir


# --------------------------------------------------------- extract_record_id


class TestExtractRecordId:
    def test_route_argv(self) -> None:
        assert extract_record_id(["route", "lrn-aa000001", "--dest", "skill-md"]) == "lrn-aa000001"

    def test_reject_argv(self) -> None:
        assert extract_record_id(["reject", "lrn-aa000001"]) == "lrn-aa000001"

    def test_link_contradicts_picks_the_record_id_not_the_target(self) -> None:
        argv = ["link", "contradicts", "lrn-aa000001", "lrn-bb000002"]
        assert extract_record_id(argv) == "lrn-aa000001"

    def test_followup_done_argv(self) -> None:
        assert extract_record_id(["followup", "done", "lrn-aa000001"]) == "lrn-aa000001"

    def test_push_has_no_record_id(self) -> None:
        assert extract_record_id(["push"]) is None

    def test_mine_run_has_no_record_id(self) -> None:
        assert extract_record_id(["mine", "run", "--trigger", "manual"]) is None

    def test_note_text_is_not_mistaken_for_an_id_unless_verbatim(self) -> None:
        argv = ["reject", "lrn-aa000001", "--note", "not an id at all"]
        assert extract_record_id(argv) == "lrn-aa000001"


# ------------------------------------------------ resolve_self_learn_argv_prefix


class TestResolveArgvPrefix:
    def test_env_override_wins_and_is_shlex_split(self) -> None:
        prefix = resolve_self_learn_argv_prefix(
            {SELF_LEARN_BIN_ENV: f"{sys.executable} {FAKE_SELF_LEARN}"}
        )
        assert prefix == [sys.executable, str(FAKE_SELF_LEARN)]

    def test_path_resolution_scoped_to_given_environ_never_real_os_environ(
        self, tmp_path: Path
    ) -> None:
        bindir = _hermetic_bindir_with_self_learn(tmp_path)
        prefix = resolve_self_learn_argv_prefix({"PATH": str(bindir)})
        assert prefix == [str(bindir / "self-learn")]
        # The hermetic bindir was never added to this TEST PROCESS's own
        # PATH — proof the function looked ONLY at the environ dict it
        # was handed, never fell back to (or was influenced by) the real
        # os.environ (10 §0 rules 7/8).
        assert str(bindir) not in os.environ.get("PATH", "").split(os.pathsep)

    def test_falls_through_to_literal_when_nothing_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Both PATH lookup AND the sys.executable-relative fallback must
        # miss to reach the final literal — this venv's own
        # sys.executable sits beside a real `self-learn` (path
        # dependency), so that fallback is stubbed out too.
        monkeypatch.setattr(sys, "executable", "/does/not/exist/python3")
        prefix = resolve_self_learn_argv_prefix({"PATH": "/does/not/exist"})
        assert prefix == ["self-learn"]


# ------------------------------------------------------------- unit: RealRunner


class TestRealRunnerSpawn:
    async def test_argv_is_passed_through_verbatim(self, tmp_path: Path) -> None:
        log = tmp_path / "calls.jsonl"
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            env={"FAKE_SELF_LEARN_LOG": str(log)},
        )
        argv = build_argv("route", "lrn-aa000001", dest="skill-md", collapse="cl-1")
        result = await runner.run(argv)
        assert result.ok
        entries = _read_log(log)
        assert len(entries) == 1
        assert entries[0]["argv"] == argv
        assert entries[0]["home"] == str(home)

    async def test_nonzero_exit_surfaces_stderr_verbatim(self, tmp_path: Path) -> None:
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            env={
                "FAKE_SELF_LEARN_EXIT_CODE": "2",
                "FAKE_SELF_LEARN_STDERR": "self-learn: scan hit — record not stamped",
            },
        )
        result = await runner.run(["reject", "lrn-aa000001"])
        assert result.exit_code == 2
        assert result.ok is False
        assert result.stderr.strip() == "self-learn: scan hit — record not stamped"

    async def test_failed_spawn_never_raises(self, tmp_path: Path) -> None:
        """An unresolvable binary is a RunResult, not an exception (task
        pin, carried from the seam's original contract: routes.py must
        never catch an ad hoc exception from a verb call)."""
        home = tmp_path / "ledger-home"
        runner = RealRunner(home=home, argv_prefix=["/definitely/not/a/real/binary"])
        result = await runner.run(["push"])
        assert result.ok is False
        assert result.exit_code != 0

    async def test_refresh_callback_fires_scoped_to_record_after_every_verb(
        self, tmp_path: Path
    ) -> None:
        scopes: list[str] = []
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            refresh_callback=scopes.append,
        )
        await runner.run(["route", "lrn-aa000001"])
        await runner.run(["push"])
        assert scopes == ["record:lrn-aa000001", "front"]

    async def test_interrupt_hook_awaited_before_spawn_when_record_id_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The dispatch-order race test (P1-4): the interrupt hook must
        be fully awaited BEFORE the subprocess spawn call, never
        concurrently with it — proven by recording ordering into a
        shared in-process list rather than trusting the source order."""
        order: list[tuple[str, object]] = []

        async def fake_interrupt(record_id: str) -> None:
            order.append(("interrupt", record_id))

        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            interrupt_active_session=fake_interrupt,
        )

        async def fake_spawn(argv: list[str]) -> RunResult:
            order.append(("spawn", tuple(argv)))
            return RunResult(0)

        monkeypatch.setattr(runner, "_spawn", fake_spawn)
        await runner.run(["route", "lrn-aa000001"])
        assert order == [
            ("interrupt", "lrn-aa000001"),
            ("spawn", ("route", "lrn-aa000001")),
        ]

    async def test_interrupt_hook_not_called_for_id_less_verbs(
        self, tmp_path: Path
    ) -> None:
        calls: list[str] = []

        async def fake_interrupt(record_id: str) -> None:
            calls.append(record_id)

        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            interrupt_active_session=fake_interrupt,
        )
        await runner.run(["push"])
        assert calls == []

    async def test_set_interrupt_hook_replaces_the_hook_post_construction(
        self, tmp_path: Path
    ) -> None:
        """Task brief point 4: the pane track (U6) must be able to plug
        its session manager in without editing runner.py — a setter is
        the documented mechanism."""
        home = tmp_path / "ledger-home"
        runner = RealRunner(home=home, argv_prefix=_direct_prefix())
        calls: list[str] = []

        async def later_hook(record_id: str) -> None:
            calls.append(record_id)

        runner.set_interrupt_hook(later_hook)
        await runner.run(["reject", "lrn-aa000001"])
        assert calls == ["lrn-aa000001"]

        runner.set_interrupt_hook(None)  # restores the no-op default
        await runner.run(["reject", "lrn-bb000002"])
        assert calls == ["lrn-aa000001"]  # unchanged — no-op this time

    async def test_serialization_two_concurrent_submissions_never_overlap(
        self, tmp_path: Path
    ) -> None:
        """ONE verb subprocess at a time server-wide (10 §1) — proven by
        timing evidence, not by trusting the lock exists: each fake
        invocation logs its own [start, end] window; if the runner
        failed to serialize, the second call's window would overlap the
        first's (both sleep long enough that unserialized execution
        would visibly race)."""
        log = tmp_path / "calls.jsonl"
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            env={"FAKE_SELF_LEARN_LOG": str(log), "FAKE_SELF_LEARN_SLEEP": "0.3"},
        )
        results = await asyncio.gather(
            runner.run(["route", "lrn-aa000001"]),
            runner.run(["reject", "lrn-bb000002"]),
        )
        assert all(r.ok for r in results)
        entries = _read_log(log)
        assert len(entries) == 2
        entries.sort(key=lambda e: e["start"])
        # The second invocation must not have started until the first
        # had fully finished — a strict, non-overlapping handoff.
        assert entries[1]["start"] >= entries[0]["end"]

    async def test_serialization_holds_across_three_submissions(self, tmp_path: Path) -> None:
        log = tmp_path / "calls.jsonl"
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            env={"FAKE_SELF_LEARN_LOG": str(log), "FAKE_SELF_LEARN_SLEEP": "0.15"},
        )
        await asyncio.gather(
            runner.run(["route", "lrn-aa000001"]),
            runner.run(["reject", "lrn-bb000002"]),
            runner.run(["defer", "lrn-cc000003"]),
        )
        entries = _read_log(log)
        entries.sort(key=lambda e: e["start"])
        assert len(entries) == 3
        for earlier, later in zip(entries, entries[1:]):
            assert later["start"] >= earlier["end"]

    async def test_path_resolution_genuinely_invokes_the_fake_binary(
        self, tmp_path: Path
    ) -> None:
        """End-to-end proof that PATH resolution (not just direct
        argv_prefix injection) works: RealRunner constructed with NO
        argv_prefix, only an `env` whose PATH points at the hermetic
        bindir — resolve_self_learn_argv_prefix must find and the
        subprocess must actually run the fake."""
        bindir = _hermetic_bindir_with_self_learn(tmp_path)
        # The fake's `#!/usr/bin/env python3` shebang needs `python3` on
        # PATH too — append the real interpreter's own dir (this test is
        # about proving `self-learn` PATH resolution, not about
        # sandboxing the Python interpreter itself, unlike
        # test_launcher.py's fully hermetic desktop-binary shims).
        path = os.pathsep.join([str(bindir), str(Path(sys.executable).parent)])
        log = tmp_path / "calls.jsonl"
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            env={"PATH": path, "FAKE_SELF_LEARN_LOG": str(log)},
        )
        result = await runner.run(["push"])
        assert result.ok
        entries = _read_log(log)
        assert entries == [
            {
                "argv": ["push"],
                "start": entries[0]["start"],
                "end": entries[0]["end"],
                "pid": entries[0]["pid"],
                "home": str(home),
            }
        ]


# ------------------------------------------------------- M-H: bounded runner
#
# C05: `RealRunner.run` used to hold its server-wide lock across a bare
# `await proc.communicate()` -- a hung verb blocked every later UI verb
# forever, and a cancelled request left the child running. Below: the
# pinned fixture itself (a REAL TERM-ignoring child, killable only by
# SIGKILL) exercised directly against `communicate_bounded`, then through
# the real `RealRunner.run()` to prove the lock/busy/interrupt-hook
# contract holds end to end.


async def _spawn_term_ignoring_child() -> asyncio.subprocess.Process:
    """The pinned fixture (M-H task brief): a REAL OS process that
    ignores SIGTERM outright -- `terminate()` is a no-op against it, only
    `kill()` (SIGKILL, which cannot be blocked or ignored) ends it."""
    return await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        'trap "" TERM; sleep 60',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


class TestCommunicateBoundedAgainstRealTermIgnoringChild:
    """`test_runner.py`'s `_ScriptedProcess` proves the escalation logic
    in isolation; this proves it against the real signal semantics a
    scripted double can only simulate."""

    async def test_bounded_and_actually_reaped_not_a_zombie(self) -> None:
        proc = await _spawn_term_ignoring_child()
        try:
            start = time.monotonic()
            stdout_b, stderr_b, code = await communicate_bounded(
                proc, timeout=0.2, kill_grace=0.3
            )
            elapsed = time.monotonic() - start
            # Bounded: the fixture sleeps 60s -- an unbounded wait would
            # take at least that long. Generous slack over timeout +
            # 2*kill_grace below, not a tight timing assertion.
            assert elapsed < 5.0
            assert code != 0
            assert proc.returncode is not None  # reaped -- no zombie left
            assert b"terminated" in stderr_b
            # Independent of asyncio's own bookkeeping: the OS itself
            # agrees the pid is gone (a still-alive pid would raise
            # nothing here -- this must raise).
            with pytest.raises(ProcessLookupError):
                os.kill(proc.pid, 0)
        finally:
            if proc.returncode is None:  # pragma: no cover - safety net only
                proc.kill()
                await proc.wait()

    async def test_task_cancellation_kills_and_reaps_the_real_child(self) -> None:
        proc = await _spawn_term_ignoring_child()
        try:
            task = asyncio.ensure_future(communicate_bounded(proc, timeout=60, kill_grace=0.3))
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5.0)
            assert proc.returncode is not None
            with pytest.raises(ProcessLookupError):
                os.kill(proc.pid, 0)
        finally:
            if proc.returncode is None:  # pragma: no cover - safety net only
                proc.kill()
                await proc.wait()


class TestRealRunnerBoundedTimeoutAndLockRelease:
    async def test_hung_verb_no_longer_blocks_a_later_verb_forever(
        self, tmp_path: Path
    ) -> None:
        """The C05 regression itself, through the real `RealRunner.run`:
        before M-H this would hang forever on the first call, so a
        second call would never even start. Proven by actually running
        the TERM-ignoring child through the runner, then a second verb
        through the SAME instance right after."""
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home, argv_prefix=["bash", "-c"], verb_timeout=0.2, kill_grace=0.3
        )
        start = time.monotonic()
        first = await runner.run(['trap "" TERM; sleep 60'])
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert first.ok is False
        assert runner.busy is False

        # The lock is genuinely free -- not just reporting False -- proven
        # by a second call through the SAME runner actually completing.
        second = await runner.run(["true"])
        assert second.ok is True
        assert runner.busy is False

    async def test_cancelled_run_releases_the_lock_and_kills_the_child(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home, argv_prefix=["bash", "-c"], verb_timeout=60, kill_grace=0.3
        )
        task = asyncio.ensure_future(runner.run(['trap "" TERM; sleep 60']))
        await asyncio.sleep(0.1)
        assert runner.busy is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5.0)
        assert runner.busy is False

        second = await runner.run(["true"])
        assert second.ok is True

    async def test_interrupt_hook_bounded_verb_still_runs(self, tmp_path: Path) -> None:
        """Task brief point 4: the injected interrupt hook is bounded
        too -- a wedged pane engine must not hold the lock (and every
        OTHER tab's dispatch behind it) forever. Proven against a REAL
        fake-self-learn subprocess so the verb's actual execution is
        also confirmed, not just that `run()` returns."""

        async def hangs_forever(record_id: str) -> None:
            await asyncio.Event().wait()

        log = tmp_path / "calls.jsonl"
        home = tmp_path / "ledger-home"
        runner = RealRunner(
            home=home,
            argv_prefix=_direct_prefix(),
            env={"FAKE_SELF_LEARN_LOG": str(log)},
            interrupt_active_session=hangs_forever,
            interrupt_timeout=0.05,
        )
        result = await asyncio.wait_for(runner.run(["route", "lrn-aa000001"]), timeout=5.0)
        assert result.ok is True
        entries = _read_log(log)
        assert entries[0]["argv"] == ["route", "lrn-aa000001"]
        assert runner.busy is False

    async def test_fast_verb_unaffected_by_the_bounded_communicate_change(
        self, tmp_path: Path
    ) -> None:
        """Positive control (task brief): the bounded wrapper must not
        perturb an ordinary fast verb -- default timeouts, real
        fake-self-learn subprocess, exact same shape as pre-M-H."""
        home = tmp_path / "ledger-home"
        runner = RealRunner(home=home, argv_prefix=_direct_prefix())
        result = await runner.run(["push"])
        assert result.ok is True
        assert runner.busy is False


# ------------------------------------------------- argv shapes (full matrix)
#
# One RealRunner call per pinned verb, argv built via routes.py's OWN
# build_argv (never re-derived here — routes.py is owned by the
# concurrent track and already unit-tests build_argv's shapes against
# FakeRunner in test_routes.py; this class proves the REAL runner passes
# those exact same argvs through to a real subprocess unmodified).


class TestArgvMatrixThroughRealSubprocess:
    async def _run_and_log(self, tmp_path: Path, argv: list[str]) -> list[dict]:
        log = tmp_path / "calls.jsonl"
        home = tmp_path / "ledger-home"
        runner = RealRunner(home=home, argv_prefix=_direct_prefix(), env={"FAKE_SELF_LEARN_LOG": str(log)})
        result = await runner.run(argv)
        assert result.ok
        return _read_log(log)

    async def test_route_with_dest_and_collapse(self, tmp_path: Path) -> None:
        argv = build_argv("route", "lrn-aa000001", dest="skill-md", collapse="cl-9")
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == ["route", "lrn-aa000001", "--dest", "skill-md", "--collapse", "cl-9"]

    async def test_reject(self, tmp_path: Path) -> None:
        argv = build_argv("reject", "lrn-aa000001", note="too narrow")
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == ["reject", "lrn-aa000001", "--note", "too narrow"]

    async def test_defer(self, tmp_path: Path) -> None:
        argv = build_argv("defer", "lrn-aa000001", until="2026-08-01")
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == ["defer", "lrn-aa000001", "--until", "2026-08-01"]

    async def test_graduate(self, tmp_path: Path) -> None:
        argv = build_argv("graduate", "lrn-aa000001")
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == ["graduate", "lrn-aa000001"]

    async def test_confirm_recurrence_without_tolerate(self, tmp_path: Path) -> None:
        argv = build_argv("confirm-recurrence", "lrn-aa000001", event="ev-1")
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == ["confirm-recurrence", "lrn-aa000001", "--event", "ev-1"]

    async def test_confirm_recurrence_with_tolerate(self, tmp_path: Path) -> None:
        argv = build_argv("confirm-recurrence", "lrn-aa000001", event="ev-1", tolerate=True)
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == [
            "confirm-recurrence",
            "lrn-aa000001",
            "--event",
            "ev-1",
            "--tolerate",
        ]

    async def test_link_contradicts(self, tmp_path: Path) -> None:
        argv = build_argv("link-contradicts", "lrn-aa000001", target="lrn-bb000002")
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == ["link", "contradicts", "lrn-aa000001", "lrn-bb000002"]

    async def test_followup_done(self, tmp_path: Path) -> None:
        argv = build_argv("followup-done", "lrn-aa000001")
        entries = await self._run_and_log(tmp_path, argv)
        assert entries[0]["argv"] == ["followup", "done", "lrn-aa000001"]


# --------------------------------------------------- bulk loop, end to end
#
# Through the REAL routes.py `/bucket/{scope}/{name}/graduate-bulk`
# endpoint (owned by the concurrent track, imported/used here — not
# edited) with a REAL RealRunner wired via create_app, proving the
# already-tested (against FakeRunner, in test_routes.py) bulk-loop
# contract holds when actual subprocesses spawn: --no-push sequence,
# terminal push on success AND on abort, halt-with-failing-id.


def _make_real_client(
    sb, tmp_path: Path, *, fail_argv_contains: str | None = None
) -> tuple[TestClient, Path]:
    log = tmp_path / "bulk-calls.jsonl"
    env_for_fake: dict[str, str] = {"FAKE_SELF_LEARN_LOG": str(log)}
    if fail_argv_contains is not None:
        env_for_fake["FAKE_SELF_LEARN_FAIL_ARGV_CONTAINS"] = fail_argv_contains
        env_for_fake["FAKE_SELF_LEARN_EXIT_CODE"] = "1"
        env_for_fake["FAKE_SELF_LEARN_STDERR"] = "self-learn: graduate failed"
    runner = RealRunner(home=sb.ledger, argv_prefix=_direct_prefix(), env=env_for_fake)
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=runner, start_watcher=False)
    c = TestClient(app, base_url="http://127.0.0.1:7357")
    c.cookies.set("slu_token", TOKEN)
    return c, log


class TestBulkGraduateThroughRealRunner:
    def test_success_sequence_no_push_then_terminal_push(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        ids = []
        for _ in range(3):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            seed_proposal(sb.ledger, rec.id, already_canon=True)
            ids.append(rec.id)

        c, log = _make_real_client(sb, tmp_path)
        r = c.post(
            "/bucket/skill/s/graduate-bulk",
            data={"ids": ",".join(ids)},
            headers={"HX-Request": "true"},
        )
        assert r.status_code in (200, 303)
        entries = _read_log(log)
        assert [e["argv"] for e in entries] == [
            ["graduate", ids[0], "--no-push"],
            ["graduate", ids[1], "--no-push"],
            ["graduate", ids[2], "--no-push"],
            ["push"],
        ]

    def test_abort_at_item_two_still_runs_terminal_push_and_shows_failing_id(
        self, tmp_path: Path
    ) -> None:
        sb = make_env(tmp_path)
        ids = []
        for _ in range(3):
            rec = make_behavior(scope="skill:s")
            seed_record(sb.ledger, rec)
            seed_proposal(sb.ledger, rec.id, already_canon=True)
            ids.append(rec.id)

        c, log = _make_real_client(sb, tmp_path, fail_argv_contains=ids[1])
        r = c.post(
            "/bucket/skill/s/graduate-bulk",
            data={"ids": ",".join(ids)},
            headers={"HX-Request": "true"},
        )
        entries = _read_log(log)
        assert [e["argv"] for e in entries] == [
            ["graduate", ids[0], "--no-push"],
            ["graduate", ids[1], "--no-push"],
            ["push"],  # terminal push runs on ABORT too (08 §1 amendment)
        ]
        assert ids[1] in r.text  # the failing id is shown, per the halt contract
        assert ids[2] not in [e["argv"][1] for e in entries if e["argv"][0] == "graduate"]
