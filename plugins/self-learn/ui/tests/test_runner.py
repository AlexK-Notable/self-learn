"""runner.py — the verb-execution seam (U3 task brief). No I/O, no
FastAPI — a plain async unit test of the seam + FakeRunner.

``TestCommunicateBounded`` (M-H) tests the terminate -> grace -> kill ->
reap escalation logic against a scripted in-process fake ``Process``
double — no real OS subprocess, keeping this file I/O-free per its own
rule above. The REAL end-to-end proof against an actual TERM-ignoring
``bash`` child lives in ``tests/test_runner_real.py``."""

from __future__ import annotations

import asyncio
import json

import pytest

from self_learn_ui.runner import FakeRunner, NotWiredRunner, RunResult, communicate_bounded


class TestRunResult:
    def test_ok_true_on_zero_exit(self) -> None:
        assert RunResult(0).ok is True

    def test_ok_false_on_nonzero_exit(self) -> None:
        assert RunResult(1).ok is False
        assert RunResult(2).ok is False


class TestRunResultEvidence:
    """Resolution-evidence unit (§3.1): `evidence` parses the CLI's
    `--json` envelope, populated ONLY on a zero exit, and a parse
    failure must never move `ok` — outcome stays exit-status-only."""

    def test_evidence_parses_on_success(self) -> None:
        envelope = {"action": "route", "record_id": "lrn-aa000001", "outcome_state": "landed"}
        result = RunResult(0, stdout=json.dumps(envelope))
        assert result.evidence == envelope
        assert result.ok is True

    def test_malformed_stdout_on_zero_exit_still_reports_success(self) -> None:
        """§5 Runner bullet: "malformed stdout on a zero exit still
        reports success with evidence = None"."""
        result = RunResult(0, stdout="not json at all {{{")
        assert result.ok is True
        assert result.evidence is None

    def test_missing_stdout_leaves_evidence_none(self) -> None:
        result = RunResult(0)
        assert result.evidence is None
        assert result.ok is True

    def test_nonzero_exit_never_parses_stdout_into_evidence(self) -> None:
        """Evidence is populated ONLY when the exit status is ALREADY
        success (§3.1) — a failed verb's stdout (which the CLI never
        promises is JSON-shaped on a refusal) must not be read at all."""
        envelope = {"action": "route", "outcome_state": "landed"}
        result = RunResult(1, stdout=json.dumps(envelope))
        assert result.ok is False
        assert result.evidence is None

    def test_outcome_never_moves_when_the_envelope_claims_failure(self) -> None:
        """§5 mutation bullet: "mutate the envelope to claim failure —
        the outcome must not move." `ok` reads `exit_code` alone, always
        — a `--json` envelope has no `ok`/`success` field to begin with,
        and even a hostile stdout payload that FAKES one must not
        influence it."""
        hostile = {"ok": False, "success": False, "exit_code": 1}
        result = RunResult(0, stdout=json.dumps(hostile))
        assert result.ok is True  # exit_code (the constructor arg) wins
        assert result.evidence == hostile  # parsed verbatim, never interpreted

    def test_evidence_passed_explicitly_is_never_overwritten_by_stdout(self) -> None:
        """A test may inject an evidence dict directly (§5's render-layer
        drift test: "inject a drift envelope directly — no fixture
        needed") — this must NOT be clobbered by parsing `stdout`, which
        may be empty or unrelated."""
        injected = {"action": "route", "outcome_state": "drift"}
        result = RunResult(0, stdout="{}", evidence=injected)
        assert result.evidence == injected

    def test_non_dict_json_does_not_become_evidence(self) -> None:
        """A JSON array or scalar parses without error but is not an
        envelope — evidence must stay `None`, never a non-dict value a
        template would choke on."""
        result = RunResult(0, stdout=json.dumps([1, 2, 3]))
        assert result.evidence is None


class TestFakeRunner:
    async def test_records_argv(self) -> None:
        runner = FakeRunner()
        await runner.run(["route", "lrn-aa000001", "--dest", "skill-md"])
        await runner.run(["reject", "lrn-bb000002"])
        assert runner.calls == [
            ["route", "lrn-aa000001", "--dest", "skill-md"],
            ["reject", "lrn-bb000002"],
        ]

    async def test_default_result_is_success(self) -> None:
        runner = FakeRunner()
        result = await runner.run(["graduate", "lrn-aa000001"])
        assert result.ok is True
        assert result.exit_code == 0

    async def test_queued_results_are_fifo_then_fall_back_to_default(self) -> None:
        runner = FakeRunner(default=RunResult(0, stderr="default"))
        runner.queue_result(RunResult(1, stderr="first failure"))
        runner.queue_result(RunResult(2, stderr="second failure"))

        first = await runner.run(["route", "lrn-aa000001"])
        second = await runner.run(["route", "lrn-bb000002"])
        third = await runner.run(["route", "lrn-cc000003"])

        assert (first.exit_code, first.stderr) == (1, "first failure")
        assert (second.exit_code, second.stderr) == (2, "second failure")
        assert (third.exit_code, third.stderr) == (0, "default")


class TestNotWiredRunner:
    async def test_raises_loudly(self) -> None:
        runner = NotWiredRunner()
        with pytest.raises(RuntimeError, match="no VerbRunner wired"):
            await runner.run(["route", "lrn-aa000001"])


class _ScriptedProcess:
    """A minimal async-``Process`` double for testing
    ``communicate_bounded``'s escalation logic in isolation — no real OS
    process. ``ignores_term=True`` models the exact fixture
    ``test_runner_real.py`` drives for real (``bash -c 'trap "" TERM;
    sleep 60'``): ``terminate()`` is a no-op, only ``kill()`` ends it."""

    def __init__(self, *, hang_forever: bool = False, ignores_term: bool = False) -> None:
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._hang_forever = hang_forever
        self._ignores_term = ignores_term
        self._exited = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang_forever:
            await asyncio.Event().wait()  # a future that never resolves on its own
        await self._exited.wait()
        return b"", b""

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self._ignores_term:
            self.returncode = -15
            self._exited.set()

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


class TestCommunicateBounded:
    async def test_normal_completion_returns_promptly_without_escalation(self) -> None:
        """Positive control: a fast/well-behaved process is returned
        exactly as before — no terminate/kill ever fires."""
        proc = _ScriptedProcess()
        proc.returncode = 0
        proc._exited.set()
        stdout_b, stderr_b, code = await communicate_bounded(proc, timeout=5.0)
        assert (stdout_b, stderr_b, code) == (b"", b"", 0)
        assert proc.terminate_calls == 0
        assert proc.kill_calls == 0

    async def test_process_exiting_on_term_never_escalates_to_kill(self) -> None:
        proc = _ScriptedProcess(hang_forever=True, ignores_term=False)
        _, _, code = await communicate_bounded(proc, timeout=0.05, kill_grace=5.0)
        assert proc.terminate_calls == 1
        assert proc.kill_calls == 0
        assert code == -15

    async def test_term_ignoring_process_escalates_to_kill(self) -> None:
        proc = _ScriptedProcess(hang_forever=True, ignores_term=True)
        _, _, code = await communicate_bounded(proc, timeout=0.05, kill_grace=0.05)
        assert proc.terminate_calls == 1
        assert proc.kill_calls == 1
        assert code == -9

    async def test_timeout_reports_a_diagnosable_stderr_message(self) -> None:
        proc = _ScriptedProcess(hang_forever=True, ignores_term=True)
        _, stderr_b, _ = await communicate_bounded(proc, timeout=0.05, kill_grace=0.05)
        assert b"terminated" in stderr_b

    async def test_already_exited_process_is_a_no_op(self) -> None:
        proc = _ScriptedProcess()
        proc.returncode = 0
        proc._exited.set()
        await communicate_bounded(proc, timeout=5.0)
        assert proc.terminate_calls == 0
        assert proc.kill_calls == 0

    async def test_cancellation_terminates_kills_reaps_then_reraises(self) -> None:
        """The other trigger for escalation (M-H): the AWAITING TASK
        itself cancelled (HTTP disconnect, server shutdown) — not a
        timeout at all (the passed ``timeout`` here is 60s, never hit).
        Cleanup must still run, and the cancellation must still
        propagate to the caller (never silently swallowed)."""
        proc = _ScriptedProcess(hang_forever=True, ignores_term=True)
        task = asyncio.ensure_future(communicate_bounded(proc, timeout=60, kill_grace=0.2))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert proc.terminate_calls == 1
        assert proc.kill_calls == 1
        assert proc.returncode == -9
