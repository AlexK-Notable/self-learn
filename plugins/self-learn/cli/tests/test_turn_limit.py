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

import dataclasses

from self_learn import steward
from self_learn.invocation_sdk import backend as backend_mod

from support import commit_all, make_home
from test_invocation_sdk import _run, _spec, sdk_cli_path  # noqa: F401 - fixture
from test_steward import _seed_fresh_proposals, _write_decision_stage


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


# --------------------------------------------------------------------- #
# The limit itself: `steward.turns_per_lesson` for each lesson in the
# batch (the user's instruction, 2026-09-19: "we first increase teh limit
# to 200 per lesson").
# --------------------------------------------------------------------- #


def _steward_specs(home, monkeypatch) -> list:
    """Run the steward with a stub model and return every session spec it
    asked for."""
    seen: list = []

    def invoke(spec):
        seen.append(spec)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", invoke)
    steward.run(home, dry_run=False)
    return seen


def _write_steward_config(home, body: str) -> None:
    (home / "config.yaml").write_text("steward:\n  enabled: true\n" + body, encoding="utf-8")
    commit_all(home, "configure steward")


def test_a_steward_session_gets_200_turns_for_each_lesson_in_its_batch(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 3)
    _write_steward_config(home, "")

    specs = _steward_specs(home, monkeypatch)

    assert [spec.max_turns for spec in specs] == [600]


def test_the_limit_follows_each_batchs_own_size_and_the_setting(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 3)
    _write_steward_config(home, "  packet_size: 2\n  turns_per_lesson: 7\n")

    specs = _steward_specs(home, monkeypatch)

    assert [spec.max_turns for spec in specs] == [14, 7]  # a batch of 2, then a batch of 1


def test_the_repair_round_keeps_the_batchs_limit(tmp_path):
    home = make_home(tmp_path)
    run_dir = tmp_path / "limit-stage"
    run_dir.mkdir()
    spec = steward._session_spec(home, run_dir, "PROMPT", label="limit", lessons=4)
    assert spec.max_turns == 800  # the control: the first round has one

    assert steward._repair_spec(spec, "bad stage").max_turns == 800


def test_claude_code_is_handed_the_sessions_own_limit(tmp_path):
    home = make_home(tmp_path)
    run_dir = tmp_path / "limit-stage"
    run_dir.mkdir()
    spec = steward._session_spec(home, run_dir, "PROMPT", label="limit", lessons=4)

    assert backend_mod.options_kwargs(spec)["max_turns"] == 800


def test_a_session_that_names_no_limit_still_gets_its_surfaces(tmp_path):
    home = make_home(tmp_path)
    run_dir = tmp_path / "limit-stage"
    run_dir.mkdir()
    spec = steward._session_spec(home, run_dir, "PROMPT", label="limit", lessons=4)
    unsized = dataclasses.replace(spec, max_turns=None)

    assert backend_mod.options_kwargs(unsized)["max_turns"] == 80  # sdk.max_turns.steward
