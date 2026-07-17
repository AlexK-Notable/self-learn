"""runner.py — the verb-execution seam (U3 task brief). No I/O, no
FastAPI — a plain async unit test of the seam + FakeRunner."""

from __future__ import annotations

import pytest

from self_learn_ui.runner import FakeRunner, NotWiredRunner, RunResult


class TestRunResult:
    def test_ok_true_on_zero_exit(self) -> None:
        assert RunResult(0).ok is True

    def test_ok_false_on_nonzero_exit(self) -> None:
        assert RunResult(1).ok is False
        assert RunResult(2).ok is False


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
