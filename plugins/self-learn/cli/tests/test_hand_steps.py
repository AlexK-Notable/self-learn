"""S-NEXT-u7c (hand-maintenance cures, lane C): ``report.hand_steps``, the
week's census of ledger changes made from a person's or an agent's shell.

Every test builds a throwaway git repository whose commits carry chosen
dates, subjects, notes and trailers. No ledger of the user's, no model.
Each "not a hand step" test pairs with a positive control: the same repo holds
one real hand step, so an empty answer cannot come from a census that sees
nothing at all (lrn-ea833a5b).
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import report
from support import init_repo

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _commit(repo: Path, subject: str, *, days_ago: float = 1, note: str | None = None,
            trailer: str | None = None) -> None:
    """One empty commit dated *days_ago* before NOW; *note* and *trailer* are
    separate paragraphs, the way ``verbs._body_with_by_trailer`` writes them."""
    when = (NOW - timedelta(days=days_ago)).isoformat()
    paragraphs = [text for text in (note, trailer) if text]
    args = ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", subject]
    for text in paragraphs:
        args += ["-m", text]
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(args, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "ledger"
    init_repo(path)
    return path


def _census(repo: Path, **kw) -> dict:
    return report.hand_steps(repo, now=NOW, **kw)


def _subjects(census: dict) -> list[str]:
    return [step["subject"] for step in census["steps"]]


def test_a_verb_with_no_trailer_is_a_hand_step_with_by_none(repo):
    _commit(repo, "self-learn: reject lrn-0000a001", note="not a durable lesson")
    census = _census(repo)
    assert census["state"] == "ok" and census["total"] == 1
    step = census["steps"][0]
    assert step["subject"] == "self-learn: reject lrn-0000a001"
    assert step["by"] == "none"
    assert step["note"] == "not a durable lesson"
    assert len(step["commit"]) >= 7 and step["at"].endswith("Z")


def test_by_human_and_by_agent_trailers_are_named(repo):
    _commit(repo, "self-learn: retire lrn-0000a001", note="covered by a hook", trailer="By: human")
    _commit(repo, "self-learn: revise lrn-0000a002", note="shorter wording", trailer="By: agent")
    steps = {step["subject"]: step for step in _census(repo)["steps"]}
    assert steps["self-learn: retire lrn-0000a001"]["by"] == "human"
    assert steps["self-learn: revise lrn-0000a002"]["by"] == "agent"
    # The trailer paragraph is not part of the note.
    assert steps["self-learn: revise lrn-0000a002"]["note"] == "shorter wording"


@pytest.mark.parametrize(
    "subject",
    [
        "self-learn: mine 3 candidate(s)",
        "self-learn: worker 2 proposals",
        "self-learn: steward manifest run-0123456789ab",
        "self-learn: case record case-0123abcd",
        "self-learn: case receipt case-0123abcd",
        "self-learn: case observe case-0123abcd",
        "self-learn: telemetry flush",
        "self-learn: overseer run 2026-10-30",
        "self-learn: overseer manifest run-1",
        "self-learn: capture lrn-0000a009 (user)",
        "self-learn: statement add stmt-0123abcd",
        "self-learn: user-model add um-1234 (C)",
        "self-learn: premises refresh lrn-0000a001 p1",
    ],
)
def test_a_job_s_commit_is_not_a_hand_step(repo, subject):
    _commit(repo, subject)
    _commit(repo, "self-learn: reject lrn-0000a001", note="the one real hand step")
    assert _subjects(_census(repo)) == ["self-learn: reject lrn-0000a001"]


def test_a_commit_with_a_case_trailer_or_a_job_actor_is_not_a_hand_step(repo):
    runner_block = "By: steward\nCase: case-0123abcd\nSheet: 0123abcd\nItem: 1"
    _commit(repo, "self-learn: revise lrn-0000a001", note="receipt", trailer=runner_block)
    _commit(repo, "self-learn: route lrn-0000a002 → claude-md", trailer="By: overseer")
    _commit(repo, "self-learn: route lrn-0000a003 → claude-md", trailer="By: analyst")
    # A Case trailer alone is a job's identity, whoever the By line names.
    _commit(repo, "self-learn: note lrn-0000a004", trailer="By: human\nCase: case-0123abcd\nSheet: 0123abcd\nItem: 2")
    _commit(repo, "self-learn: defer lrn-0000a005", note="hand", trailer="By: human")
    assert _subjects(_census(repo)) == ["self-learn: defer lrn-0000a005"]


def test_a_commit_a_person_made_with_plain_git_is_a_hand_step_too(repo):
    """A subject nobody anticipated still counts: a new kind of hand
    maintenance must show up instead of being filtered by a list that never
    heard of it."""
    _commit(repo, "fix the shelf by hand")
    assert _subjects(_census(repo)) == ["fix the shelf by hand"]


def test_the_window_is_seven_days(repo):
    _commit(repo, "self-learn: reject lrn-0000a001", days_ago=8)
    _commit(repo, "self-learn: reject lrn-0000a002", days_ago=6.5)
    census = _census(repo)
    assert _subjects(census) == ["self-learn: reject lrn-0000a002"]
    assert census["window_days"] == 7
    # The window is a parameter, not a constant buried in the walk.
    assert len(_census(repo, days=10)["steps"]) == 2


def test_no_note_reads_as_no_reason_recorded_and_a_long_note_is_clipped(repo):
    _commit(repo, "self-learn: reject lrn-0000a001", days_ago=2)
    _commit(repo, "self-learn: reject lrn-0000a002", days_ago=1, note="word " * 200)
    by_subject = {step["subject"]: step for step in _census(repo)["steps"]}
    assert by_subject["self-learn: reject lrn-0000a001"]["note"] == "(no reason recorded)"
    long_note = by_subject["self-learn: reject lrn-0000a002"]["note"]
    assert long_note.startswith("word word") and long_note.endswith("…") and len(long_note) <= 240


def test_a_note_that_trips_the_secret_scan_is_withheld(repo):
    token = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
    _commit(repo, "self-learn: note lrn-0000a001", days_ago=2, note=f"token = {token}")
    _commit(repo, "self-learn: note lrn-0000a002", days_ago=1, note="a harmless note")
    census = _census(repo)
    by_subject = {step["subject"]: step for step in census["steps"]}
    assert by_subject["self-learn: note lrn-0000a002"]["note"] == "a harmless note"  # control
    withheld = by_subject["self-learn: note lrn-0000a001"]["note"]
    assert withheld.startswith("(withheld: the secret scan matched")
    assert token not in repr(census)


def test_the_cap_keeps_the_newest_and_counts_the_rest(repo):
    for n in range(5):
        _commit(repo, f"self-learn: reject lrn-0000a00{n}", days_ago=5 - n)
    census = _census(repo, limit=2)
    assert census["total"] == 5
    assert _subjects(census) == ["self-learn: reject lrn-0000a004", "self-learn: reject lrn-0000a003"]


def test_an_unreadable_history_is_unavailable_never_an_empty_week(tmp_path):
    not_a_repo = tmp_path / "plain-folder"
    not_a_repo.mkdir()
    census = report.hand_steps(not_a_repo, now=NOW)
    assert census["state"] == "unavailable"
    assert census["reason"]
    assert census["steps"] == [] and census["total"] == 0


def test_a_note_that_only_looks_like_a_trailer_stays_the_note(repo):
    """Only a final paragraph holding a ``By:`` line is a trailer block."""
    _commit(repo, "self-learn: note lrn-0000a001", note="Reason: the host moved")
    step = _census(repo)["steps"][0]
    assert step["note"] == "Reason: the host moved" and step["by"] == "none"
