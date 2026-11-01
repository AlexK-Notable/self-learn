"""CU-3 / CU-4 step 2: the commit-cursor census and the trailer-first classifier.

``report.ledger_log`` walks the ancestry range from the last published census
(``overseer/census.yaml``) to HEAD, never ``git log --since``: a commit made on
a clock set to the past sits behind a newer one and a date cut drops it. A
report that carries the census moves the cursor in its own commit; a run that
publishes nothing leaves it. Runner-built reports carry the census too.

Every test builds a throwaway git repository or ledger; no model, no real ledger.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from self_learn import execution_evidence, report
from self_learn.overseer import health
from self_learn.overseer import run as overseer_run
from support import git, init_repo, make_home
from test_hand_steps import NOW, _commit
from test_overseer_phase_b_facts import _section
from test_overseer_run import _enabled, _fake_two_phase, _silence_notifications


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "ledger"
    init_repo(path)
    return path


def _skewed(repo: Path) -> str:
    """A (the cursor), B, C (a skewed clock: 30 days old but made after B), D.
    Returns A's sha."""
    _commit(repo, "self-learn: reject lrn-0000a001", days_ago=10)
    cursor = _head(repo)
    _commit(repo, "self-learn: reject lrn-0000a002", days_ago=3)
    _commit(repo, "self-learn: reject lrn-0000a003", days_ago=30)
    _commit(repo, "self-learn: reject lrn-0000a004", days_ago=1)
    return cursor


def _subjects(census: dict) -> list[str]:
    return sorted(step["subject"] for step in census["steps"])


# ============================================================ the walk


def test_a_cursor_walk_lists_the_commit_behind_a_skewed_clock(repo):
    cursor = _skewed(repo)
    census = report.hand_steps(repo, now=NOW, cursor=cursor, cursor_run="run-aaaa")
    assert census["state"] == "ok"
    assert _subjects(census) == [
        "self-learn: reject lrn-0000a002",
        "self-learn: reject lrn-0000a003",  # 30 days old, made after B
        "self-learn: reject lrn-0000a004",
    ]
    assert census["head"] == _head(repo)
    assert census["label"] == f"since the census of run-aaaa ({cursor[:7]})"
    assert census["since"].startswith("2026-10-21")  # the cursor commit's own date


def test_without_a_cursor_the_dated_fallback_still_lists_the_commit_behind_a_skew(repo):
    _skewed(repo)
    census = report.hand_steps(repo, now=NOW)
    # B is within seven days and sits BEHIND the 30-day-old C in the log; a
    # --since walk stops at C and never reaches it.
    assert _subjects(census) == ["self-learn: reject lrn-0000a002", "self-learn: reject lrn-0000a004"]
    assert census["label"] == "no earlier census; the last 7 days"


@pytest.mark.parametrize("kind", ["orphan", "unknown"])
def test_a_cursor_that_is_not_in_this_history_falls_back_and_says_so(repo, kind):
    _skewed(repo)
    if kind == "orphan":
        tree = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-t", "tree", "-w", "--stdin"],
            input="", check=True, capture_output=True, text=True,
        ).stdout.strip()
        cursor = subprocess.run(
            ["git", "-C", str(repo), "commit-tree", tree, "-m", "elsewhere"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    else:
        cursor = "0123456789abcdef0123456789abcdef01234567"
    census = report.hand_steps(repo, now=NOW, cursor=cursor)
    assert census["state"] == "ok", census
    assert "not in this history" in census["label"]
    assert _subjects(census) == ["self-learn: reject lrn-0000a002", "self-learn: reject lrn-0000a004"]


def test_a_cursor_at_head_is_an_empty_window_not_an_unavailable_one(repo):
    _skewed(repo)
    census = report.hand_steps(repo, now=NOW, cursor=_head(repo))
    assert census["state"] == "ok" and census["total"] == 0


def test_the_cursor_file_reads_back_and_a_bad_one_reads_as_none(repo):
    assert report.read_census_cursor(repo) is None
    path = report.census_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.census_cursor_text(head="abc1234", run="run-1", at="2026-10-31T01:00:00Z"))
    assert report.read_census_cursor(repo) == {"head": "abc1234", "run": "run-1", "at": "2026-10-31T01:00:00Z"}
    path.write_text("head: not a sha!\n")
    assert report.read_census_cursor(repo) is None
    path.write_text("- a list\n")
    assert report.read_census_cursor(repo) is None


def test_premise_refreshes_use_the_same_walk(repo):
    _commit(repo, "seed", days_ago=10)
    cursor = _head(repo)
    _commit(repo, "self-learn: premises refresh lrn-0000a001 p1", days_ago=3, note="refreshed.\np1: a -> b")
    _commit(repo, "self-learn: premises refresh lrn-0000a002 p1", days_ago=30, note="refreshed.\np1: c -> d")
    _commit(repo, "self-learn: premises refresh lrn-0000a003 p1", days_ago=1, note="refreshed.\np1: e -> f")
    with_cursor = health.premise_refreshes(repo, now=NOW, cursor=cursor)
    assert sorted(c["lesson"] for c in with_cursor["commits"]) == [
        "lrn-0000a001", "lrn-0000a002", "lrn-0000a003",
    ]
    fallback = health.premise_refreshes(repo, now=NOW)
    assert sorted(c["lesson"] for c in fallback["commits"]) == ["lrn-0000a001", "lrn-0000a003"]


def test_the_phase_b_row_reads_the_cursor_from_the_ledger(repo):
    _commit(repo, "self-learn: reject lrn-0000a001", days_ago=10)
    cursor = _head(repo)
    _commit(repo, "self-learn: reject lrn-0000a002", days_ago=30)
    path = report.census_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.census_cursor_text(head=cursor, run="run-1", at="2026-10-30T00:00:00Z"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "self-learn: overseer census cursor")
    row = health.hand_steps_row(repo, now=NOW)
    assert row["kind"] == "hand-steps-this-week"
    assert "census of run-1" in row["label"]
    subjects = [s["subject"] for s in row["steps"]]
    assert "self-learn: reject lrn-0000a002" in subjects  # the skewed 30-day-old step
    assert row["head"] == _head(repo)


# ============================================================ the classifier (CU-4 step 2)


def test_the_by_trailer_decides_before_the_subject_list(repo):
    # A job's trailer on a subject the list never heard of: not a hand step.
    _commit(repo, "self-learn: reconcile 3 record(s)", trailer="By: miner")
    _commit(repo, "self-learn: recompile resync", trailer="By: worker")
    _commit(repo, "self-learn: recovered lrn-0000a001", trailer="By: serve")
    _commit(repo, "self-learn: premises sweep", trailer="By: sweep")
    # A shell's trailer on a subject the list would have skipped: a hand step.
    _commit(repo, "self-learn: mine 2 candidate(s)", trailer="By: human")
    _commit(repo, "self-learn: worker 1 proposals", trailer="By: agent")
    # No trailer (history): the subject lists still judge.
    _commit(repo, "self-learn: mine 9 candidate(s)")  # a job's subject
    _commit(repo, "self-learn: reconcile 1 record(s)")  # unknown subject, no trailer: counts
    census = report.hand_steps(repo, now=NOW)
    by_subject = {s["subject"]: s["by"] for s in census["steps"]}
    assert by_subject == {
        "self-learn: mine 2 candidate(s)": "human",
        "self-learn: worker 1 proposals": "agent",
        "self-learn: reconcile 1 record(s)": "none",
    }


def test_new_knowledge_subjects_are_never_hand_steps_whoever_made_them(repo):
    _commit(repo, "self-learn: capture lrn-0000a009 (user)", trailer="By: human")
    _commit(repo, "self-learn: statement add stmt-0123abcd", trailer="By: agent")
    _commit(repo, "self-learn: defer lrn-0000a005", trailer="By: human")  # control
    assert [s["subject"] for s in report.hand_steps(repo, now=NOW)["steps"]] == [
        "self-learn: defer lrn-0000a005"
    ]


# ============================================================ the cursor moves with a published census


def _ok_census(head: str) -> dict:
    return {"state": "ok", "head": head, "label": "x", "steps": [], "total": 0, "window_days": 7}


def _failed_attempt(home: Path, *, report_text: str | None, census: dict | None):
    return overseer_run._commit_failed_attempt(
        home, None, coverage_path=None, coverage_before=None, report_text=report_text,
        date="2026-10-31", run_id="run-test0001", week="2026-W44",
        started="2026-10-31T01:00:00Z", attempt=1, cap=3, kind="schema-repair",
        detail="x", closed_text=None, census=census,
    )


def test_a_run_that_publishes_nothing_leaves_the_cursor_and_the_next_census_covers_both(tmp_path):
    home = make_home(tmp_path)
    _commit(home, "self-learn: reject lrn-0000a001", days_ago=0.5, note="step one")
    first_head = _head(home)

    # Nothing published: no report text, so the cursor is not written.
    _failed_attempt(home, report_text=None, census=_ok_census(first_head))
    assert not report.census_path(home).exists()

    # A report that carries the census writes the cursor in the same commit.
    published = _failed_attempt(home, report_text="# Overseer report\n", census=_ok_census(first_head))
    cursor = report.read_census_cursor(home)
    assert cursor is not None and cursor["head"] == first_head and cursor["run"] == "run-test0001"
    assert published.is_file()
    assert "overseer/census.yaml" in subprocess.run(
        ["git", "-C", str(home), "show", "--name-only", "--format=", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.split()

    # A census that was not taken or not read does not move it.
    _commit(home, "self-learn: reject lrn-0000a002", days_ago=0.2, note="step two")
    second_head = _head(home)
    _failed_attempt(home, report_text="# Overseer report 2\n", census=None)
    _failed_attempt(home, report_text="# Overseer report 3\n", census={"state": "unavailable", "head": second_head})
    assert report.read_census_cursor(home)["head"] == first_head

    # A later run's census lists the steps made since the cursor, once.
    _commit(home, "self-learn: reject lrn-0000a003", days_ago=0.1, note="step three")
    row = health.hand_steps_row(home)
    subjects = [s["subject"] for s in row["steps"]]
    assert "self-learn: reject lrn-0000a002" in subjects and "self-learn: reject lrn-0000a003" in subjects
    assert "self-learn: reject lrn-0000a001" not in subjects


# ============================================================ whole runs


def _hand_commit(home: Path, subject: str) -> None:
    git(home, "commit", "--allow-empty", "-q", "-m", subject, "-m", "a note")


def test_a_whole_run_moves_the_cursor_to_the_head_it_listed(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_two_phase(monkeypatch)
    _hand_commit(home, "self-learn: reject lrn-0000a001")
    before = _head(home)

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code) == ("applied", 0), result
    record = execution_evidence.read_manifest(home, result.run)
    head = record["hand_steps"]["head"]
    assert head and _is_ancestor(home, before, head)
    cursor = report.read_census_cursor(home)
    assert cursor == {**cursor, "head": head, "run": result.run}
    body = _section((home / "overseer" / "latest-report.md").read_text(encoding="utf-8"))
    assert "lrn-0000a001" in body and "window: no earlier census" in body


def _is_ancestor(home: Path, old: str, new: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(home), "merge-base", "--is-ancestor", old, new], capture_output=True
    ).returncode == 0


def test_a_refused_phase_b_publishes_the_census_and_moves_the_cursor(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_two_phase(monkeypatch)
    real = overseer_run.invocation.write_session
    seen = {"phase_b": 0}

    def drop_a_required_file(spec):
        out = real(spec)
        if spec.label != "phase-s" and (spec.cwd / "report.md").exists():
            seen["phase_b"] += 1
            (spec.cwd / "user-model-delta.yaml").unlink()
        return out

    monkeypatch.setattr(overseer_run.invocation, "write_session", drop_a_required_file)
    _hand_commit(home, "self-learn: reject lrn-0000a001")

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert seen["phase_b"] == 1, "positive control: phase B ran and lost a file"
    assert result.status == "refused", result
    text = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "phase B incomplete" in text
    body = _section(text)
    assert "lrn-0000a001" in body and "the overseer did not name the gap" in body
    assert "was not taken" not in body
    assert report.read_census_cursor(home) is not None


def test_a_runner_built_report_without_a_census_says_it_was_not_taken():
    text = overseer_run._report_text(
        date="2026-10-31", run_id="run-x", model="m", selected=(), population_count=0,
        excluded=0, model_calls=0, guard=0, reason="closed",
    )
    body = _section(text)
    assert "the census was not taken this run" in body and "next report covers" in body
