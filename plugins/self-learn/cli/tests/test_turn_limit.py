"""The turn limit, and what the seam tells a runner about it.

Measured 2026-09-19 on three real steward sessions and one deliberate
probe. `--max-turns` stops a session on MODEL RESPONSES; when it does,
Claude Code reports `is_error: true`, `subtype: error_max_turns`,
`errors: ['Reached maximum number of turns (N)']`. `num_turns` on the
same result message counts roughly one per tool RESULT, so a session of
61 responses reported 104. A runner that compared `num_turns` with the
limit threw away three finished sessions (all 29 decided lessons).

So the seam carries the result message's own `subtype` on a failed
outcome, and a runner that needs to say "stopped at the turn limit"
reads that -- `test_steward.py` holds the runner's half.
"""

from __future__ import annotations

from test_invocation_sdk import _run, _spec, sdk_cli_path  # noqa: F401 - fixture


def test_a_failed_session_carries_the_reason_claude_code_gave(tmp_path, sdk_cli_path):  # noqa: F811
    home = tmp_path / "limit-home"
    home.mkdir()

    outcome = _run(_spec("worker", home=home, prompt="error_result"))

    assert (outcome.ok, outcome.failure) == (False, "exit")
    assert outcome.result_subtype == "error_during_execution"


def test_a_session_that_ended_normally_carries_no_such_reason(tmp_path, sdk_cli_path):  # noqa: F811
    home = tmp_path / "limit-home"
    home.mkdir()

    outcome = _run(_spec("worker", home=home, prompt="ok_text"))

    assert outcome.ok is True
    assert outcome.result_subtype is None
