"""End-to-end tests for `scripts/land`, against THROWAWAY git fixture
repos only (never the real repo or the real remote) -- test_landing_fixture.py
builds a fresh bare "origin" + main-checkout "repo" per test, under
tmp_path, with XDG_CACHE_HOME/SELF_LEARN_HOME redirected there too.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import test_landing_fixture as LF


# ---------------------------------------------------------------------------
# happy paths

def test_happy_path_docs_only_lane(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-docs", edits={"docs/specs/self-learn/drafts/notes.md": "hello\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-docs", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "pushed:" in r.stdout
    subject = LF.git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == "Merge branch 'u-docs' (docs — v)"
    # positive control (M47/M48): a pure-docs change must genuinely take
    # the DOCS lane, not just happen to still exit 0 -- a missing/never-run
    # full lane can otherwise vacuously "pass" via the empty-allowlist path.
    logs_dir = Path(r.stdout.split("logs=")[-1].strip())
    assert (logs_dir / "docslane.log").exists()
    assert not (logs_dir / "cli.log").exists()


def test_happy_path_full_lane_with_ui(tmp_path):
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(repo, "u-code", edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_gamma():\n    assert True\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-code", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    # the UI suite must have genuinely run FROM ui/ (M69): its own log
    # shows the real collected test, not a directory it was never meant
    # to run from (a wrong-cwd invocation that vacuously "passes" via the
    # empty-allowlist fallback would leave no such line).
    ui_log = Path(r.stdout.split("logs=")[-1].strip() + "/ui.log").read_text()
    assert "1 passed" in ui_log, ui_log


def test_happy_path_with_conflict_and_named_resolver(tmp_path):
    repo = LF.make_repo(tmp_path)
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    LF.git(repo, "checkout", "-q", "-b", "u-conflict")
    (repo / fw).write_text(
        (repo / fw).read_text() + "| FW-3 | branch-added | WATCH | n |\n"
    )
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "branch change")
    LF.git(repo, "checkout", "-q", "master")
    (repo / fw).write_text(
        (repo / fw).read_text() + "| FW-4 | master-added | WATCH | n |\n"
    )
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "master change")

    r = LF.run_land(
        repo, tmp_path,
        "--branch", "u-conflict", "--verdict", "v",
        "--resolver", f"{fw}=numeric-rows",
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    text = (repo / fw).read_text()
    assert "FW-3" in text and "FW-4" in text
    assert "<<<<<<<" not in text


# ---------------------------------------------------------------------------
# PRE1-PRE8

def test_pre2_refuses_off_master(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x")
    LF.git(repo, "checkout", "-q", "u-x")
    r = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "v")
    assert r.returncode == 2
    assert "PRE2" in r.stderr


def test_pre2_positive_control_on_master_proceeds(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "v", timeout=180)
    assert r.returncode == 0


def test_pre3_refuses_dirty_master(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    (repo / "docs/specs/self-learn/dirty.md").write_text("uncommitted\n")
    r = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "v")
    assert r.returncode == 2
    assert "PRE3" in r.stderr


def test_pre4_refuses_dirty_branch_worktree(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    wt = tmp_path / "wt-u-x"
    LF.git(repo, "worktree", "add", str(wt), "u-x")
    (wt / "dirty.txt").write_text("uncommitted in the worktree\n")
    r = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "v")
    assert r.returncode == 2
    assert "PRE4" in r.stderr


def test_pre5_refuses_missing_branch(tmp_path):
    repo = LF.make_repo(tmp_path)
    r = LF.run_land(repo, tmp_path, "--branch", "u-does-not-exist", "--verdict", "v")
    assert r.returncode == 2
    assert "PRE5" in r.stderr


def test_pre5_refuses_master_as_branch(tmp_path):
    repo = LF.make_repo(tmp_path)
    r = LF.run_land(repo, tmp_path, "--branch", "master", "--verdict", "v")
    assert r.returncode == 2
    assert "PRE5" in r.stderr


def test_pre6_refuses_unreachable_origin(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    LF.git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
    r = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "v")
    assert r.returncode == 2
    assert "PRE6" in r.stderr


def test_pre8_refuses_when_its_own_fetch_moves_origin_master(tmp_path):
    """gate M-8: PRE8's fetch runs before any scope is computed, and if
    THAT FETCH ITSELF discovers origin/master has moved (someone else
    pushed since this checkout's local knowledge), land refuses rather
    than building a landing on a base the operator never saw."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    # simulate a second machine pushing straight to origin, without this
    # checkout ever fetching it
    other = tmp_path / "other-clone"
    LF.git(repo, "clone", "-q", str(tmp_path / "origin.git"), str(other), check=True)
    LF.git(other, "config", "user.email", "t@example.invalid")
    LF.git(other, "config", "user.name", "Test")
    (other / "docs/specs/self-learn/drafts").mkdir(parents=True, exist_ok=True)
    (other / "docs/specs/self-learn/drafts/from-other.md").write_text("other\n")
    LF.git(other, "add", "-A")
    LF.git(other, "commit", "-q", "-m", "other push")
    LF.git(other, "push", "-q", "origin", "master")

    r = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "v", timeout=180)
    assert r.returncode == 2
    assert "PRE8" in r.stderr
    # land's own fetch already caught local master up to origin/master's
    # NEW tip in its ref namespace; fast-forward the local branch itself
    # (an operator step land never performs on its own) before re-running.
    LF.git(repo, "merge", "-q", "--ff-only", "origin/master")
    r2 = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "v", timeout=180)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert (repo / "docs/specs/self-learn/drafts/from-other.md").exists()


# ---------------------------------------------------------------------------
# PRV1/PRV2

def test_prv1_refuses_resolver_without_conflict(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    r = LF.run_land(
        repo, tmp_path, "--branch", "u-x", "--verdict", "v",
        "--resolver", "docs/specs/self-learn/drafts/n.md=keep-both",
    )
    assert r.returncode == 3
    assert "PRV1" in r.stderr


def test_prv2_refuses_unmapped_conflict_and_suggests(tmp_path):
    repo = LF.make_repo(tmp_path)
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    LF.git(repo, "checkout", "-q", "-b", "u-conflict")
    (repo / fw).write_text((repo / fw).read_text() + "| FW-3 | b |  | |\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "b")
    LF.git(repo, "checkout", "-q", "master")
    (repo / fw).write_text((repo / fw).read_text() + "| FW-4 | m |  | |\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "m")

    r = LF.run_land(repo, tmp_path, "--branch", "u-conflict", "--verdict", "v")
    assert r.returncode == 3
    assert "PRV2" in r.stderr
    assert fw in r.stderr
    assert "numeric-rows" in r.stderr  # the suggestion surface (ruling Q-4)
    # tree restored -- no merge commit, master unmoved
    assert LF.git(repo, "status", "--porcelain").stdout.strip() == ""


# ---------------------------------------------------------------------------
# CHK*

def test_chk2_refuses_pin_mismatch(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.git(repo, "checkout", "-q", "-b", "u-badpin")
    (repo / "plugins/self-learn/cli/tests/backends.py").write_text("CHANGED\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "change pinned file without updating the pin")
    LF.git(repo, "checkout", "-q", "master")
    r = LF.run_land(repo, tmp_path, "--branch", "u-badpin", "--verdict", "v")
    assert r.returncode == 4
    assert "CHK2" in r.stderr
    assert LF.git(repo, "status", "--porcelain").stdout.strip() == ""


def test_chk3_refuses_row_disorder(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-disorder",
        edits={"docs/specs/self-learn/14-forward-work-map.md":
               "| FW-1 | first | WATCH | n |\n| FW-2 | second | WATCH | n |\n| FW-1 | dup | WATCH | n |\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-disorder", "--verdict", "v")
    assert r.returncode == 4
    assert "CHK3" in r.stderr


def test_chk4_refuses_landing_state_prose(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-prose",
        edits={"docs/specs/self-learn/drafts/u-prose.md": "worktree left uncommitted\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-prose", "--verdict", "v")
    assert r.returncode == 4
    assert "CHK4" in r.stderr


def test_chk6_refuses_empty_verdict(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-x", "--verdict", "")
    assert r.returncode == 2  # caught at argument-parsing time


# ---------------------------------------------------------------------------
# SUI*

def test_sui1_refuses_red_suite(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-red",
        edits={"plugins/self-learn/cli/tests/test_red.py": "def test_fails():\n    assert False\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-red", "--verdict", "v", timeout=180)
    assert r.returncode == 5
    assert "suite red" in r.stderr
    # the merge commit STAYS LOCAL
    subject = LF.git(repo, "log", "-1", "--format=%s").stdout
    assert "u-red" in subject


def test_sui3_known_failure_allowlist_tolerates_exactly_that_id(tmp_path):
    # with_ui=True is load-bearing (SUI9): this is a FULL-lane landing, so
    # the UI suite must genuinely exist and run. Before SUI9 this fixture
    # had no ui/ tree at all, the UI suite's cwd did not exist, and its
    # empty log was adjudicated "no failing ids -> allowlisted only" --
    # a suite that never ran reading as green, inside the very test that
    # exists to prove the allowlist is exact.
    repo = LF.make_repo(tmp_path, with_ui=True)
    node_id = "plugins/self-learn/cli/tests/test_red.py::test_fails"
    (repo / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt").write_text(node_id + "\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "allowlist")
    LF.make_branch(
        repo, "u-allowlisted",
        edits={"plugins/self-learn/cli/tests/test_red.py": "def test_fails():\n    assert False\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-allowlisted", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr


def test_sui3_extra_failure_beyond_the_allowlist_still_refuses(tmp_path):
    repo = LF.make_repo(tmp_path)
    node_id = "plugins/self-learn/cli/tests/test_red.py::test_fails"
    (repo / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt").write_text(node_id + "\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "allowlist")
    LF.make_branch(
        repo, "u-twofail",
        edits={
            "plugins/self-learn/cli/tests/test_red.py": "def test_fails():\n    assert False\n",
            "plugins/self-learn/cli/tests/test_red2.py": "def test_also_fails():\n    assert False\n",
        },
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-twofail", "--verdict", "v", timeout=180)
    assert r.returncode == 5


def test_sui6_rename_into_docs_without_no_renames_takes_full_lane(tmp_path):
    """SUI6 leg (h) (M71): a src module RENAMED into docs/ must still take
    the FULL lane -- git's rename detection (without --no-renames) would
    otherwise report the change as a single path already under docs/,
    hiding what is really a deleted src module."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.git(repo, "checkout", "-q", "-b", "u-rename")
    (repo / "docs/specs/self-learn/drafts").mkdir(parents=True, exist_ok=True)
    # A keeper test, so the rename cannot empty the CLI suite. Without it
    # the fixture's suite collected ZERO tests and exited pytest's rc 5,
    # which the pre-SUI9 adjudicator read as green (no FAILED/ERROR lines
    # to compare) -- the full lane "ran" and proved nothing. The lane
    # question this test asks (M71/--no-renames) is independent of that.
    (repo / "plugins/self-learn/cli/tests/test_keep.py").write_text(
        "def test_keep():\n    assert True\n"
    )
    LF.git(
        repo, "mv",
        "plugins/self-learn/cli/tests/test_alpha.py",
        "docs/specs/self-learn/drafts/renamed-test-alpha.py",
    )
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "rename a src module into docs/")
    LF.git(repo, "checkout", "-q", "master")
    r = LF.run_land(repo, tmp_path, "--branch", "u-rename", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    # the CLI suite log must exist (full lane ran it)
    assert Path(r.stdout.split("logs=")[-1].strip() + "/cli.log").exists()


def test_sui6_non_py_non_docs_file_takes_full_lane(tmp_path):
    """SUI6 leg (c) (M48): a non-.py, non-docs file (e.g. UI's static JS)
    must take the FULL lane -- a `\\.py$`-only detector would wrongly send
    it to the docs lane, skipping the UI suite while U-jsdom is live."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-jsonly",
        edits={"plugins/self-learn/ui/static/app.js": "console.log('hi');\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-jsonly", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert Path(r.stdout.split("logs=")[-1].strip() + "/cli.log").exists()


def test_sui6_docs_plus_py_takes_full_lane(tmp_path):
    """SUI6 leg (b): docs + a .py file must NOT take the docs lane."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-mixed",
        edits={
            "docs/specs/self-learn/drafts/n.md": "x\n",
            "plugins/self-learn/cli/tests/test_gamma.py": "def test_gamma():\n    assert True\n",
        },
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-mixed", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    # the CLI suite log must exist (full lane ran it); the docs-lane log must not
    assert Path(r.stdout.split("logs=")[-1].strip() + "/cli.log").exists()


# ---------------------------------------------------------------------------
# SAN2/SAN4

def test_san2_seeded_hit_refuses(tmp_path):
    repo = LF.make_repo(tmp_path)
    origin_before = LF.git(repo, "rev-parse", "origin/master").stdout
    LF.make_branch(
        repo, "u-secret",
        edits={"docs/specs/self-learn/drafts/n.md": "the fixture password is SEEDED-VALUE\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-secret", "--verdict", "v", timeout=180)
    assert r.returncode == 6
    assert "sanitize" in r.stderr.lower()
    # not pushed -- origin/master unmoved
    LF.git(repo, "fetch", "origin", "master")
    origin_after = LF.git(repo, "rev-parse", "origin/master").stdout
    assert origin_before == origin_after


def test_san2_positive_control_clean_diff_proceeds(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-clean", edits={"docs/specs/self-learn/drafts/n.md": "nothing sensitive\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-clean", "--verdict", "v", timeout=180)
    assert r.returncode == 0


def test_san4_ack_lets_a_verified_hit_through(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-ack",
        edits={"docs/specs/self-learn/drafts/n.md": "the fixture password is SEEDED-VALUE\n"},
    )
    refusal = LF.run_land(repo, tmp_path, "--branch", "u-ack", "--verdict", "v", timeout=180)
    assert refusal.returncode == 6
    # the refusal prints a paste-ready ack suggestion (N-18)
    ack_lines = [l for l in refusal.stderr.splitlines() if "--sanitize-ack" in l]
    assert ack_lines, refusal.stderr
    import re
    m = re.search(r"--sanitize-ack '([^']+)'", ack_lines[0])
    assert m
    ack_key = m.group(1)  # "<file>:<line>:<sha>="
    r = LF.run_land(
        repo, tmp_path, "--branch", "u-ack", "--continue",
        "--sanitize-ack", ack_key + "verified fixture literal, not a real secret",
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# PSH*

def test_psh3_no_force_capability_in_the_shipped_script():
    land = LF.LAND
    text = land.read_text()
    assert "--force" not in text
    assert "--no-ff" in text  # the absence control: --no-ff IS present


def test_psh4_prunes_worktree_and_branch_after_push(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-prune", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    wt = tmp_path / "wt-u-prune"
    LF.git(repo, "worktree", "add", str(wt), "u-prune")
    r = LF.run_land(repo, tmp_path, "--branch", "u-prune", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not wt.exists()
    branches = LF.git(repo, "branch", "--list", "u-prune").stdout
    assert "u-prune" not in branches


def test_psh4_no_worktree_still_prunes_cleanly(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-noworktree", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-noworktree", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# DRY1-DRY3

def test_dry_run_touches_nothing_on_master(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-dry", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    before_sha = LF.git(repo, "rev-parse", "master").stdout
    before_status = LF.git(repo, "status", "--porcelain").stdout
    before_wt_count = len(LF.git(repo, "worktree", "list").stdout.splitlines())

    r = LF.run_land(repo, tmp_path, "--branch", "u-dry", "--verdict", "v", "--dry-run", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY RUN" in r.stdout

    after_sha = LF.git(repo, "rev-parse", "master").stdout
    after_status = LF.git(repo, "status", "--porcelain").stdout
    after_wt_count = len(LF.git(repo, "worktree", "list").stdout.splitlines())
    assert before_sha == after_sha
    assert before_status == after_status
    assert before_wt_count == after_wt_count
    # branch untouched, not pushed
    assert LF.git(repo, "rev-parse", "u-dry").stdout  # still exists


def test_dry_run_still_runs_the_landing_checks(tmp_path):
    """DRY2 (M42): --dry-run must still run the landing checks (CHK1-6,
    world/pins) inside its throwaway worktree -- a pin mismatch must
    refuse under --dry-run exactly as it does for real."""
    repo = LF.make_repo(tmp_path)
    LF.git(repo, "checkout", "-q", "-b", "u-drypin")
    (repo / "plugins/self-learn/cli/tests/backends.py").write_text("CHANGED\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "change pinned file without updating the pin")
    LF.git(repo, "checkout", "-q", "master")
    r = LF.run_land(repo, tmp_path, "--branch", "u-drypin", "--verdict", "v", "--dry-run")
    assert r.returncode == 4
    assert "CHK2" in r.stderr


def test_dry_run_refusal_matches_the_real_refusal(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-dryred",
        edits={"docs/specs/self-learn/drafts/n.md": "the fixture password is SEEDED-VALUE\n"},
    )
    dry = LF.run_land(repo, tmp_path, "--branch", "u-dryred", "--verdict", "v", "--dry-run", timeout=180)
    real = LF.run_land(repo, tmp_path, "--branch", "u-dryred", "--verdict", "v", timeout=180)
    assert dry.returncode == real.returncode == 6


# ---------------------------------------------------------------------------
# CNT1/CNT2 -- via the sanitize refusal, which lands AFTER the commit

def test_cnt1_bare_rerun_after_commit_refusal_refuses(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-resume",
        edits={"docs/specs/self-learn/drafts/n.md": "the fixture password is SEEDED-VALUE\n"},
    )
    first = LF.run_land(repo, tmp_path, "--branch", "u-resume", "--verdict", "v", timeout=180)
    assert first.returncode == 6
    # a bare re-run (no --continue) must refuse, naming --continue
    again = LF.run_land(repo, tmp_path, "--branch", "u-resume", "--verdict", "v", timeout=180)
    assert again.returncode == 2
    assert "--continue" in again.stderr


def test_cnt1_no_state_file_control_proceeds_normally(tmp_path):
    """A branch with NO prior refused landing must not be affected by
    CNT1 at all."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-fresh", edits={"docs/specs/self-learn/drafts/n.md": "clean\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-fresh", "--verdict", "v", timeout=180)
    assert r.returncode == 0


def test_cnt2_continue_resumes_and_lands(tmp_path):
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-resume2",
        edits={"docs/specs/self-learn/drafts/n.md": "the fixture password is SEEDED-VALUE\n"},
    )
    first = LF.run_land(repo, tmp_path, "--branch", "u-resume2", "--verdict", "v", timeout=180)
    assert first.returncode == 6
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout

    import re
    m = re.search(r"--sanitize-ack '([^']+)'", first.stderr)
    assert m
    ack_key = m.group(1)

    second = LF.run_land(
        repo, tmp_path, "--branch", "u-resume2", "--continue",
        "--sanitize-ack", ack_key + "verified fixture literal",
        timeout=180,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    head_after_merge = LF.git(repo, "rev-parse", "origin/master").stdout
    assert head_before.strip() != ""  # sanity: it was a real commit


def test_cnt2_fourth_precondition_rejects_an_amended_merge(tmp_path):
    """gate M-13: an amended merge commit passes conditions (1)-(3) but
    must be rejected by the fourth (recorded merge sha + parents)."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-amend",
        edits={"docs/specs/self-learn/drafts/n.md": "the fixture password is SEEDED-VALUE\n"},
    )
    first = LF.run_land(repo, tmp_path, "--branch", "u-amend", "--verdict", "v", timeout=180)
    assert first.returncode == 6

    LF.git(repo, "commit", "--amend", "-q", "-m", "amended message")

    r = LF.run_land(repo, tmp_path, "--branch", "u-amend", "--continue", "--verdict", "v", timeout=180)
    assert r.returncode == 2
    assert "impossible" in r.stderr


# ---------------------------------------------------------------------------
# PRE1 / PRE5 (merge-base leg) / PRE7 -- gaps filled during mutation testing

def test_pre1_refuses_when_not_run_from_main_checkout(tmp_path):
    """PRE1: a worktree's own git-dir differs from its git-common-dir --
    running `land` with cwd inside a SECONDARY worktree (not the main
    checkout) must refuse, never silently operate from there."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    other_wt = tmp_path / "secondary-wt"
    LF.git(repo, "worktree", "add", "--detach", str(other_wt), "master")
    env = LF.env_for(tmp_path)
    r = subprocess.run(
        [str(LF.LAND), "--branch", "u-x", "--verdict", "v"],
        cwd=str(other_wt), env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 2
    assert "PRE1" in r.stderr


def test_pre5_refuses_unrelated_history(tmp_path):
    """PRE5's merge-base leg: a branch sharing NO history with master
    (an orphan branch) must refuse -- distinct from 'branch is master' and
    'branch does not exist', which a merge-base-check deletion would not
    catch."""
    repo = LF.make_repo(tmp_path)
    LF.git(repo, "checkout", "-q", "--orphan", "u-orphan")
    LF.git(repo, "rm", "-rq", "--cached", ".", check=False)
    (repo / "orphan-file.txt").write_text("no shared history\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "orphan root")
    LF.git(repo, "checkout", "-q", "master")
    r = LF.run_land(repo, tmp_path, "--branch", "u-orphan", "--verdict", "v")
    assert r.returncode == 2
    assert "PRE5" in r.stderr


def test_pre7_no_merge_abort_call_anywhere_in_the_precondition_block():
    """PRE7: a precondition refusal must never invoke `git merge --abort`
    (nothing has merged yet at that point) -- every `merge --abort` call
    in the shipped script lives inside run_merge_and_checks(), never in
    the Step-1 precondition block that precedes it."""
    text = LF.LAND.read_text()
    pre_block, _, _rest = text.partition("run_merge_and_checks() {")
    assert "run_merge_and_checks() {" in text, "structural anchor missing"
    assert "merge --abort" not in pre_block


# ---------------------------------------------------------------------------
# PRV2 (two conflicts) / PRV4 -- gaps filled during mutation testing

def test_prv2_two_conflicts_names_only_the_unmapped_one(tmp_path):
    """PRV2 (M9): a resolver mapping for one conflicted path must not
    excuse land from refusing the OTHER, unmapped one -- 'require a
    resolver for the first conflicted path only' must still redden."""
    repo = LF.make_repo(tmp_path)
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    d3 = "docs/specs/self-learn/03-decisions.md"
    LF.git(repo, "checkout", "-q", "-b", "u-twoconf")
    (repo / fw).write_text((repo / fw).read_text() + "| FW-3 | b |  | |\n")
    (repo / d3).write_text((repo / d3).read_text() + "| S-3 | b | r |\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "b")
    LF.git(repo, "checkout", "-q", "master")
    (repo / fw).write_text((repo / fw).read_text() + "| FW-4 | m |  | |\n")
    (repo / d3).write_text((repo / d3).read_text() + "| S-4 | m | r |\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "m")

    # map the ALPHABETICALLY-FIRST conflicted path (03-decisions.md sorts
    # before 14-forward-work-map.md) -- a 'first path only' bug would
    # check exactly this one, find it mapped, and never notice the
    # second, unmapped path.
    r = LF.run_land(
        repo, tmp_path, "--branch", "u-twoconf", "--verdict", "v",
        "--resolver", f"{d3}=numeric-rows",
    )
    assert r.returncode == 3
    assert "PRV2" in r.stderr
    assert fw in r.stderr  # the UNMAPPED path is named
    assert LF.git(repo, "status", "--porcelain").stdout.strip() == ""


# ---------------------------------------------------------------------------
# CHK1 (merge-touched set, not a hardcoded doc list) / CHK7 (HEAD unmoved
# on refusal) / CHK8 (ordering) / CHK5 (real shipped test, not a private
# grep) -- gaps filled during mutation testing

def test_chk1_finds_markers_outside_the_hardcoded_three_docs_e2e(tmp_path):
    """M19: CHK1 must scan the MERGE-TOUCHED set, not a hardcoded
    three-doc list -- a marker-shaped literal committed cleanly in an
    ordinary src file (well outside the three docs) must still refuse."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-fakemarker",
        edits={
            "plugins/self-learn/cli/tests/looks_like_conflict.py":
                "# example of a conflict marker, not a real one:\n<<<<<<< HEAD\n",
        },
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-fakemarker", "--verdict", "v")
    assert r.returncode == 4
    assert "CHK1" in r.stderr


def test_chk_refusal_leaves_masters_head_exactly_where_it_was(tmp_path):
    """M29/CHK7: a CHK* refusal must never commit -- master's HEAD sha is
    byte-identical before and after the refused attempt (porcelain-empty
    alone doesn't discriminate 'aborted' from 'committed', since a
    successful commit also leaves a clean tree)."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-disorder2",
        edits={"docs/specs/self-learn/14-forward-work-map.md":
               "| FW-1 | first | WATCH | n |\n| FW-2 | second | WATCH | n |\n| FW-1 | dup | WATCH | n |\n"},
    )
    before = LF.git(repo, "rev-parse", "master").stdout.strip()
    r = LF.run_land(repo, tmp_path, "--branch", "u-disorder2", "--verdict", "v")
    assert r.returncode == 4
    after = LF.git(repo, "rev-parse", "master").stdout.strip()
    assert before == after


def test_chk8_world_and_pins_check_run_strictly_before_commit():
    """CHK8/WLD2/CHK2 (M18/M21/M55): nothing test-shaped runs between the
    armor re-measure/pins check and `git commit` -- a textual-position
    proxy over the shipped, straight-line script: every world-detection
    and pins-check call site occurs BEFORE the commit line."""
    text = LF.LAND.read_text()
    commit_idx = text.index('git -C "$GITROOT" commit -q -m "$SUBJECT"')
    for marker in ('checks --root "$gr" world', 'checks --root "$gr" pins', "remeasure.log"):
        idx = text.index(marker)
        assert idx < commit_idx, f"{marker!r} must precede the commit line"


def test_chk5_invokes_the_real_shipped_personal_literals_test_not_a_private_grep():
    """M25: CHK5 must shell out to U-scrub's real test_personal_literals.py
    via pytest, never reimplement it as a private in-runner grep scoped to
    docs/ (which would miss any hit outside docs/)."""
    text = LF.LAND.read_text()
    chk5_start = text.index("CHK5 --")
    chk5_block = text[chk5_start:chk5_start + 700]
    assert "test_personal_literals.py" in chk5_block
    assert "pytest" in chk5_block
    assert "grep" not in chk5_block


# ---------------------------------------------------------------------------
# SUI2 (timeout message) / SUI4+SUI8c (collection error) -- gaps filled
# during mutation testing

def test_sui2_timeout_case_is_a_distinct_branch_not_the_generic_red_message():
    """M31: rc 124 (SUITE_TIMEOUT) must produce a message distinct from
    the ordinary 'suite red' path -- a textual-structure proxy: the
    adjudicate_suite() case statement has its own `124)` arm."""
    text = LF.LAND.read_text()
    adj_start = text.index("adjudicate_suite() {")
    adj_block = text[adj_start:adj_start + 700]
    assert "124)" in adj_block
    assert "TIMED OUT" in adj_block


def test_sui4_and_sui8c_collection_error_refuses_distinctly_not_via_allowlist(tmp_path):
    """M33/M70: a pytest COLLECTION error (rc 2) must refuse distinctly,
    never fall through to the allowlist adjudication (which would find no
    named FAILED/ERROR node id to check and pass vacuously)."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(
        repo, "u-collecterr",
        edits={"plugins/self-learn/cli/tests/test_broken_syntax.py": "def test_broken(:\n    pass\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-collecterr", "--verdict", "v", timeout=180)
    assert r.returncode == 5
    assert "COLLECTION ERROR" in r.stderr


# ---------------------------------------------------------------------------
# PSH4's `-D` leg / prune-only-after-push -- gaps filled during mutation
# testing

def test_psh4_never_force_deletes_the_branch():
    """PSH4's second leg: `-d`, never `-D` (PSH3's no-force rule extends
    to the prune step too)."""
    text = LF.LAND.read_text()
    assert "branch -D" not in text
    assert "branch -d" in text


def test_psh_prune_runs_only_after_a_successful_push(tmp_path):
    """M40's first leg: if push fails, the branch/worktree must still be
    there afterward -- prune must not run before push."""
    repo = LF.make_repo(tmp_path)
    LF.make_branch(repo, "u-pushfail", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    wt = tmp_path / "wt-u-pushfail"
    LF.git(repo, "worktree", "add", str(wt), "u-pushfail")
    # make the push fail: replace origin with a bare repo that rejects
    # non-fast-forward-looking updates by way of a pre-receive hook.
    origin = tmp_path / "origin.git"
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    r = LF.run_land(repo, tmp_path, "--branch", "u-pushfail", "--verdict", "v", timeout=180)
    assert r.returncode == 7
    assert wt.exists()
    branches = LF.git(repo, "branch", "--list", "u-pushfail").stdout
    assert "u-pushfail" in branches


# ---------------------------------------------------------------------------
# EXC1 / UN1 / UN2 -- shell contract and shipped-file invariants

def test_exc1_shell_contract():
    text = LF.LAND.read_text()
    assert "set -uo pipefail" in text
    assert "set -euo pipefail" not in text.split("\n")[0:5]  # not the top-level contract
    import re
    assert not re.search(r"^set -e\b", text, re.M)


def test_un1_suite_script_is_the_real_one_not_edited_by_this_unit():
    """This unit does not change scripts/suite -- a static content check
    against what this build actually ships."""
    suite = LF.THIS_REPO_CLI / "scripts" / "suite"
    assert suite.exists()
    assert "uv sync" in suite.read_text()


def test_un2_never_touches_the_ledger():
    """UN2: no `SELF_LEARN_HOME` env read and no functional `.self-learn`
    path construction anywhere in the shipped script/package. Prose
    explaining the exclusion (this module's own docstrings, which quote
    the term to say it is never touched) is not itself a violation --
    the check is for FUNCTIONAL usage: an env-var read, or the literal
    used as a path component/argument rather than as documentation."""
    import re

    func_patterns = [
        re.compile(r"os\.environ.{0,20}SELF_LEARN_HOME"),
        re.compile(r"getenv\(.{0,5}SELF_LEARN_HOME"),
        re.compile(r'"\.self-learn"'),
        re.compile(r"'\.self-learn'"),
    ]

    def offenders(text: str) -> list[str]:
        return [p.pattern for p in func_patterns if p.search(text)]

    assert offenders(LF.LAND.read_text()) == []
    for py in LF.LANDING_PKG.glob("*.py"):
        assert offenders(py.read_text()) == [], py


# ---------------------------------------------------------------------------
# WLD2 / the armor `--remeasure` world (U-armor, live on master since 9ada450)
#
# The contract these exercise was MEASURED against the REAL
# cli/tests/test_armor.py in an isolated clone before any of it was
# fixtured -- misc/u-land-work/armor_contract_probe.sh and
# armor_owed_probe.sh, 2026-08-29:
#
#   success  --anchor $(git rev-parse --short=7 HEAD) read mid-merge
#            (= master's tip = the merge's first parent) -> rc 0,
#            "ANCHOR 6815503 -> dfa2a24", the module rewritten
#   no-op    --anchor == the ANCHOR already in the file -> rc 1,
#            "ANCHOR did not change (6815503 -> 6815503)", bytes unchanged
#   owed     --anchor 15fb676 -> rc 1, 2 "OWED:" lines, bytes unchanged
#
# and, separately measured on the same clone: ARM5 (`test_arm5_anchor_is_
# not_stale`) is RED before the merge commit exists and GREEN after it --
# rc 1 then rc 0 -- which is why `land` runs NO armor test between
# `--remeasure` and `git commit` (CHK8), and runs the suites only after.


def _armor_anchor(repo: Path) -> str:
    text = (repo / "plugins/self-learn/cli/tests/test_armor.py").read_text()
    m = re.search(r'^ANCHOR = "([^"]*)"', text, re.M)
    assert m is not None, text[:200]
    return m.group(1)


def test_wld1_detect_world_reads_the_two_worlds_apart(tmp_path):
    """WLD1. Both fixture worlds, and the REAL repo, adjudicated by the
    shipped detector -- not by reasoning about what it should say."""
    from self_learn.landing.checks import (
        WORLD_ARMOR_SHAS,
        WORLD_REMEASURE,
        detect_world,
    )

    shas_repo = LF.make_repo(tmp_path / "a", armor="shas")
    rem_repo = LF.make_repo(tmp_path / "b", armor="remeasure")
    assert detect_world(shas_repo) == WORLD_ARMOR_SHAS
    assert detect_world(rem_repo) == WORLD_REMEASURE

    # The live tree this unit will actually land on. U-armor deleted
    # `_ARMOR_SHAS` outright rather than emptying it, so the failure mode
    # worth ruling out is `armor_shas` reached with ZERO pins (which
    # CHK2's N<1 floor would then refuse for the wrong reason).
    real_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=LF.THIS_REPO_CLI, capture_output=True, text=True, check=True,
        ).stdout.strip()
    )
    assert detect_world(real_root) == WORLD_REMEASURE


def test_wld2_remeasure_advances_the_anchor_inside_the_merge_commit(tmp_path):
    """WLD2/CHK8. The success leg, end to end: `land` runs the TARGET
    tree's own test_armor.py with `--anchor $(rev-parse --short=7 HEAD)`
    read while HEAD is still master's pre-merge tip, and the rewritten
    module rides INSIDE the merge commit -- never after it (incident 2)."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    pre_merge_tip = LF.git(repo, "rev-parse", "--short=7", "HEAD").stdout.strip()
    assert _armor_anchor(repo) == "0000000"

    LF.make_branch(
        repo, "u-armorworld",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-armorworld", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    # the anchor advanced, and to exactly the merge's FIRST PARENT
    assert _armor_anchor(repo) == pre_merge_tip
    parents = LF.git(repo, "log", "-1", "--format=%P").stdout.split()
    assert LF.git(repo, "rev-parse", "--short=7", parents[0]).stdout.strip() == pre_merge_tip

    # and the rewrite is IN the merge commit's own tree, not a later edit
    committed = LF.git(
        repo, "show", "HEAD:plugins/self-learn/cli/tests/test_armor.py",
    ).stdout
    assert f'ANCHOR = "{pre_merge_tip}"' in committed
    # negative control: the pre-merge tree carried the stale literal
    old = LF.git(
        repo, "show", f"{parents[0]}:plugins/self-learn/cli/tests/test_armor.py",
    ).stdout
    assert 'ANCHOR = "0000000"' in old


def test_wld2_owed_refusal_aborts_the_chain_and_commits_nothing(tmp_path):
    """WLD2. A watched node edited since the anchor with no exemption
    entry: `--remeasure` prints OWED: lines, writes nothing, exits 1 --
    and the &&-chain must abort with NO merge commit."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    LF.make_branch(
        repo, "u-owed",
        edits={
            # edits test_watched_one's BODY -- an EDIT, not an addition
            "plugins/self-learn/cli/tests/test_watched.py":
                "def test_watched_one():\n    assert (2 + 2) == 5 - 1\n\n\n"
                "def test_watched_two():\n    assert (3 * 3) == 9\n",
        },
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-owed", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "WLD2: --remeasure refused" in r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _armor_anchor(repo) == "0000000"
    # the refusal names the log that carries the OWED: lines
    log = Path(r.stderr.split("cat ")[-1].strip()).read_text()
    assert "OWED:" in log, log


def test_wld2_noop_anchor_refusal_aborts_the_chain(tmp_path):
    """WLD2. `--remeasure`'s OTHER rc-1 leg: the anchor did not change.
    Both refusals are rc 1 from the same CLI and both must abort -- a
    runner that only modelled the OWED leg would land an un-advanced
    anchor and redden ARM5 (b) on the NEXT landing."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    tip = LF.git(repo, "rev-parse", "--short=7", "HEAD").stdout.strip()
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    armor_src = (repo / "plugins/self-learn/cli/tests/test_armor.py").read_text()
    LF.make_branch(
        repo, "u-noop",
        edits={
            "plugins/self-learn/cli/tests/test_armor.py":
                armor_src.replace('ANCHOR = "0000000"', f'ANCHOR = "{tip}"', 1),
        },
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-noop", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "WLD2: --remeasure refused" in r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    log = Path(r.stderr.split("cat ")[-1].strip()).read_text()
    assert "ANCHOR did not change" in log, log


def test_arm5_is_a_post_commit_property_and_the_runner_never_runs_it_early(tmp_path):
    """The armor anchor-staleness check passes only AFTER the merge commit
    exists (its walk root is `git merge-base master HEAD`, i.e. master's
    OLD tip until then). Two legs:

    (a) RED control, measured, not assumed: the fixture's ARM5-shaped test
        fails on the pre-landing tree.
    (b) the landing nevertheless succeeds, and the suite log shows that
        same test PASSING -- so the runner ran it strictly after `git
        commit`, which is what CHK8's ordering buys.
    """
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    node = "plugins/self-learn/cli/tests/test_armor.py::test_fixture_arm5_anchor_is_not_stale"

    red = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "-p", "no:cacheprovider"],
        cwd=repo, capture_output=True, text=True,
    )
    assert red.returncode != 0, red.stdout + red.stderr
    assert "no first-parent merge on master yet" in (red.stdout + red.stderr)

    # That control run left cached bytecode for test_armor.py. It is the
    # guard's own positive control, not incidental: `--remeasure` swaps a
    # 7-char anchor for another 7-char anchor, so the file's SIZE is
    # unchanged, and CPython's (mtime, size) staleness check -- both at
    # 1-second resolution -- can therefore keep serving the OLD module.
    # Measured: the suite read ANCHOR "0000000" from such a .pyc while
    # the file on disk said "69d6b72", and the landing refused at exit 5
    # on a false ARM5 red. If this assert stops holding, the rest of this
    # test is no longer exercising that path.
    pycache = repo / "plugins/self-learn/cli/tests/__pycache__"
    assert list(pycache.glob("test_armor.*.pyc")), sorted(pycache.glob("*"))

    LF.make_branch(
        repo, "u-arm5",
        edits={"plugins/self-learn/cli/tests/test_delta.py": "def test_d():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-arm5", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    cli_log = Path(r.stdout.split("logs=")[-1].strip() + "/cli.log").read_text()
    assert "passed" in cli_log and "failed" not in cli_log, cli_log
    assert not list(pycache.glob("test_armor.*.pyc")) or _armor_anchor(repo) != "0000000"

    green = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "-p", "no:cacheprovider"],
        cwd=repo, capture_output=True, text=True,
    )
    assert green.returncode == 0, green.stdout + green.stderr


def test_chk8_no_test_shaped_run_between_the_armor_step_and_the_commit():
    """CHK8, on the shipped text (M55/M56). Everything test-shaped --
    CHK5's pytest shell-out, `run_suite`, the suite scripts -- must sit
    either strictly before the `--remeasure`/pins step or strictly after
    `git commit`. Nothing in between."""
    text = LF.LAND.read_text()
    armor_at = text.index("--remeasure --anchor")
    commit_at = text.index('commit -q -m "$SUBJECT"')
    assert armor_at < commit_at
    between = text[armor_at:commit_at]
    for needle in ("pytest", "run_suite", "scripts/suite", "adjudicate_suite"):
        assert needle not in between, (needle, between)


# ---------------------------------------------------------------------------
# SUI9 -- a suite verdict that could not see its target is a REFUSAL
#
# The shape S-56 exists to end: `allowlisted_only` returned "no violations
# found" whenever the log carried no FAILED/ERROR line at all, which is
# also what a suite that never ran looks like. Both of the fixtures below
# were passing green before the fix.


def test_sui9_a_suite_that_could_not_run_refuses_instead_of_passing(tmp_path):
    """A full-lane landing whose UI tree does not exist: the UI suite's
    cwd is missing, so it produces a non-zero rc and an empty log. That
    must REFUSE. Positive control: the identical landing with a real UI
    tree proceeds, so the refusal is about the blind adjudication and not
    about the fixture being broken in some other way."""
    repo = LF.make_repo(tmp_path / "blind", with_ui=False)
    LF.make_branch(
        repo, "u-noui",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path / "blind", "--branch", "u-noui", "--verdict", "v", timeout=180)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "NO FAILED/ERROR node id" in r.stderr, r.stderr
    assert "SUI9" in r.stderr

    ok_repo = LF.make_repo(tmp_path / "seeing", with_ui=True)
    LF.make_branch(
        ok_repo, "u-ui",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    ok = LF.run_land(ok_repo, tmp_path / "seeing", "--branch", "u-ui", "--verdict", "v", timeout=180)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    verdict = Path(ok.stdout.split("logs=")[-1].strip() + "/ui.rc").read_text().strip()
    assert verdict == "0"


def test_sui9_an_empty_collection_is_not_green(tmp_path):
    """pytest's rc 5 -- ran, collected NOTHING. Before the fix this was
    adjudicated green: no FAILED/ERROR lines to compare against the
    allowlist. Measured live while building this: a `git mv` of the
    fixture's only test out of cli/tests made the CLI suite collect zero
    tests and the landing exit 0."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.git(repo, "checkout", "-q", "-b", "u-empty")
    LF.git(repo, "rm", "-q", "plugins/self-learn/cli/tests/test_alpha.py")
    (repo / "plugins/self-learn/cli/tests/notatest.py").write_text("X = 1\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "empty the cli suite")
    LF.git(repo, "checkout", "-q", "master")
    r = LF.run_land(repo, tmp_path, "--branch", "u-empty", "--verdict", "v", timeout=180)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "collected NO TESTS" in r.stderr, r.stderr


def test_sui9_writes_a_distinguishable_verdict_per_outcome(tmp_path):
    """The positive control the fix ships with: the adjudication file's
    CONTENT differs between "allowlisted-only" and every refusal reason,
    so "the allowlist saw nothing" can never be read back as "the
    allowlist found nothing wrong"."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    node_id = "plugins/self-learn/cli/tests/test_red.py::test_fails"
    (repo / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt").write_text(node_id + "\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "allowlist")
    LF.make_branch(
        repo, "u-adj",
        edits={"plugins/self-learn/cli/tests/test_red.py": "def test_fails():\n    assert False\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-adj", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())
    assert (logs / "cli.adjudication").read_text().startswith("allowlisted-only ")
    assert node_id in (logs / "cli.adjudication").read_text()


def test_sui9_source_shape_the_empty_case_never_returns_success():
    """A source-level guard on the exact line that was wrong: the
    `[ -n "$failing" ] || return 0` form must not come back."""
    text = LF.LAND.read_text()
    assert '[ -n "$failing" ] || return 0' not in text
    assert 'printf \'unparseable-log %s\\n\'' in text


# ---------------------------------------------------------------------------
# CHK5 under --dry-run (M61): the dry-run worktree's OWN copy, not $ROOT's


def test_chk5_dry_run_judges_the_dry_run_worktree_not_the_main_checkout(tmp_path):
    """M61/DRY2. The seeded literal exists only on the BRANCH, so it is
    present in the dry-run worktree (which has the merge applied) and
    absent from the main checkout (which does not). A CHK5 that ran
    $ROOT's copy would pass and let the landing through."""
    repo = LF.make_repo(tmp_path, with_ui=True, with_literals=True)
    LF.make_branch(repo, "u-seeded", edits={"seeded_literal.txt": "a personal path\n"})

    dry = LF.run_land(
        repo, tmp_path, "--branch", "u-seeded", "--verdict", "v", "--dry-run", timeout=180,
    )
    assert dry.returncode == 4, dry.stdout + dry.stderr
    assert "CHK5" in dry.stderr, dry.stderr
    # positive control: the same fixture WITHOUT the seeded file dry-runs clean,
    # so CHK5 is genuinely running and genuinely passing on a clean tree.
    clean = LF.make_repo(tmp_path / "clean", with_ui=True, with_literals=True)
    LF.make_branch(
        clean, "u-clean",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    ok = LF.run_land(
        clean, tmp_path / "clean", "--branch", "u-clean", "--verdict", "v", "--dry-run", timeout=180,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "DRY RUN" in ok.stdout


# ---------------------------------------------------------------------------
# PRE1 (M68): the git-dir predicate must be the absolute-path compare


def test_pre1_predicate_is_the_absolute_compare_not_the_dot_git_string(tmp_path):
    """M68. Measured (misc/u-land-work/pre1_probe.sh, 2026-08-29): in a
    main checkout created with `git init --separate-git-dir`, the shipped
    predicate (`--path-format=absolute --git-dir` == `--git-common-dir`)
    correctly PASSES while r2's string form (`git rev-parse --git-dir` ==
    ".git") REFUSES. The three-way probe -- plain checkout / linked
    worktree / separate git dir -- is reproduced here so the claim is not
    a reading of the script's text."""
    plain = tmp_path / "plain"
    subprocess.run(["git", "init", "-q", "-b", "master", str(plain)], check=True)
    LF.git(plain, "config", "user.email", "t@example.invalid")
    LF.git(plain, "config", "user.name", "T")
    (plain / "f").write_text("x\n")
    LF.git(plain, "add", "-A")
    LF.git(plain, "commit", "-q", "-m", "base")
    linked = tmp_path / "linked"
    LF.git(plain, "worktree", "add", "-q", "--detach", str(linked))
    sep = tmp_path / "sep"
    subprocess.run(
        ["git", "init", "-q", "-b", "master", f"--separate-git-dir={tmp_path / 'sep.git'}", str(sep)],
        check=True,
    )
    LF.git(sep, "config", "user.email", "t@example.invalid")
    LF.git(sep, "config", "user.name", "T")
    (sep / "f").write_text("x\n")
    LF.git(sep, "add", "-A")
    LF.git(sep, "commit", "-q", "-m", "base")

    def verdicts(where: Path) -> tuple[bool, bool]:
        gd = LF.git(where, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip()
        cd_ = LF.git(where, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        rel = LF.git(where, "rev-parse", "--git-dir").stdout.strip()
        return (gd == cd_, rel == ".git")

    assert verdicts(plain) == (True, True)
    assert verdicts(linked) == (False, False)
    # THE discriminating row: shipped says "main checkout", r2's says "no"
    assert verdicts(sep) == (True, False)

    # and the shipped script uses the form that gets `sep` right
    text = LF.LAND.read_text()
    assert 'git rev-parse --path-format=absolute --git-dir' in text
    assert 'git rev-parse --path-format=absolute --git-common-dir' in text
    assert '= ".git"' not in text


# ---------------------------------------------------------------------------
# SUI8 -- the UI suite's collection root (gate B-2, M-19, N-17)


def _repo_root() -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=LF.THIS_REPO_CLI, capture_output=True, text=True, check=True,
        ).stdout.strip()
    )


def _collect(cwd: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("SELF_LEARN_ANALYST_MODEL", "SELF_LEARN_ANALYST_TIMEOUT")}
    return subprocess.run(
        ["uv", "run", *extra, "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=cwd, capture_output=True, text=True, env=env, timeout=300,
    )


def _node_ids(out: str) -> list[str]:
    return [ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(("E ", "ERROR"))]


def test_sui8_ui_suite_collection_root(tmp_path):
    """SUI8, all five legs.

    (a) the shipped script runs the UI suite with cwd = the UI package;
    (b) the STABLE PREDICATES (never the counts -- §4.6's OBSERVED table:
        331/3327 on a populated root vs 32/2668 in a fresh worktree, the
        difference being only git-excluded misc/): from the repo root
        rc == 2 with at least one collected id under cli/tests; from the
        UI package rc == 0 with zero ids outside ui/tests;
    (c) rc 2 is adjudicated as a collection error, never handed to the
        allowlist;
    (d) there is no root-level pytest config -- that is the mechanism;
    (e) every collected id maps to a file in `git ls-files`, since a bare
        prefix check passes with an UNTRACKED scratch test inside
        ui/tests/ (N-17). The control for (e) is constructed live.
    """
    root = _repo_root()
    ui = root / "plugins/self-learn/ui"

    # (a)
    text = LF.LAND.read_text()
    assert 'run_suite ui "$GITROOT/plugins/self-learn/ui"' in text

    # (d) -- the mechanism: nothing at the root sets pytest's collection root
    for name in ("pytest.ini", "pyproject.toml", "conftest.py", "setup.cfg", "tox.ini"):
        assert not (root / name).exists(), name

    # (c)
    assert 'COLLECTION ERROR (rc 2)' in text
    assert 'the allowlist cannot adjudicate it' in text
    two_arm = text.index('2) record_refusal_step suites')
    star_arm = text.index('*)\n        if ! allowlisted_only')
    assert two_arm < star_arm

    # (b)
    from_root = _collect(root, "--project", "plugins/self-learn/ui")
    assert from_root.returncode == 2, from_root.stdout[-2000:]
    assert "plugins/self-learn/cli/tests" in (from_root.stdout + from_root.stderr)

    from_ui = _collect(ui)
    assert from_ui.returncode == 0, from_ui.stdout[-2000:]
    ids = _node_ids(from_ui.stdout)
    assert ids, from_ui.stdout[-2000:]
    outside = [i for i in ids if not i.startswith("tests/")]
    assert outside == [], outside[:10]

    # (e) -- tracked membership, with the prefix check's blind spot shown
    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ui, capture_output=True, text=True, check=True,
        ).stdout.split()
    )
    files = {i.split("::", 1)[0] for i in ids}
    assert files <= tracked, sorted(files - tracked)[:10]

    scratch = ui / "tests" / "test_sui8_untracked_scratch_probe.py"
    assert not scratch.exists()
    scratch.write_text("def test_probe():\n    assert True\n")
    try:
        again = _collect(ui)
        ids2 = _node_ids(again.stdout)
        probe = [i for i in ids2 if "test_sui8_untracked_scratch_probe" in i]
        assert probe, again.stdout[-2000:]
        # the prefix check is satisfied by it -- that is the blind spot
        assert all(i.startswith("tests/") for i in probe), probe
        # the ls-files check is NOT
        files2 = {i.split("::", 1)[0] for i in ids2}
        assert not files2 <= tracked
    finally:
        scratch.unlink()
    assert not scratch.exists()


# ---------------------------------------------------------------------------
# DOC1-DOC3 -- the three doc criteria


def _spec_docs() -> Path:
    return _repo_root() / "docs" / "specs" / "self-learn"


_STEP_RE = re.compile(r"^# Step (\d+) [-—]+ (\S+)", re.M)
_DIE_RE = re.compile(r"\bdie ([2-9]) ")


def test_s56_matches_the_runner():
    """DOC1. The S-56 row's claims about the runner are compared to the
    SCRIPT, both directions, and both derived (never a hand-copied list):
    every `# Step N` label the script declares must be named in the row,
    and the row's stated exit-code range must equal the script's own
    `die` codes. Positive control: the same comparison against a doctored
    copy of the row, with one stage word deleted, reports the mismatch."""
    row = [
        ln for ln in (_spec_docs() / "03-decisions.md").read_text().splitlines()
        if ln.startswith("| S-56 |")
    ]
    assert len(row) == 1, len(row)
    row_text = row[0]

    script = LF.LAND.read_text()
    steps = [label.strip("(,.:").lower() for _, label in _STEP_RE.findall(script)]
    assert len(steps) >= 5, steps

    def missing(text: str) -> list[str]:
        return [s for s in steps if s not in text.lower()]

    assert missing(row_text) == [], missing(row_text)

    codes = sorted({int(c) for c in _DIE_RE.findall(script)})
    assert codes == [2, 3, 4, 5, 6, 7], codes
    assert f"exit code ({codes[0]}-{codes[-1]})" in row_text

    # positive control -- the comparison is not vacuous on an unchanged row.
    # Every occurrence goes, not just the first: the row names some stages
    # more than once, and a one-shot replace leaves the check green.
    doctored = re.sub(re.escape(steps[-1]), "", row_text, flags=re.I)
    assert missing(doctored) == [steps[-1]], missing(doctored)


def test_fw_rows_added_and_ordered():
    """DOC2. FW-142 and FW-143 exist and sit in a monotonic run.
    Positive control: the same check against `99d310e` -- before the rows
    were written -- reports them missing."""
    from self_learn.landing.checks import check_duplicate_rows, check_row_order

    fw_path = _spec_docs() / "14-forward-work-map.md"
    text = fw_path.read_text()
    assert "| FW-142 |" in text and "| FW-143 |" in text
    assert text.index("| FW-142 |") < text.index("| FW-143 |")
    assert check_duplicate_rows(text, "FW") == []
    # the two rows are adjacent and ascending -- neither appears in the
    # descending-pair set, so this unit ADDED no disorder
    assert (143, 142) not in check_row_order(text, "FW")
    assert not [p for p in check_row_order(text, "FW") if 142 in p or 143 in p]

    before = subprocess.run(
        ["git", "show", "99d310e:docs/specs/self-learn/14-forward-work-map.md"],
        cwd=_repo_root(), capture_output=True, text=True, check=True,
    ).stdout
    assert "| FW-142 |" not in before and "| FW-143 |" not in before


def _runbook_section_one() -> str:
    text = (_spec_docs() / "15-orchestration-runbook.md").read_text()
    start = text.index("\n## 1. ")
    end = text.index("\n## 2. ", start)
    body = text[start:end]
    # comment-blind: a mention buried in an HTML comment does not count
    return re.sub(r"<!--.*?-->", "", body, flags=re.S)


def test_runbook_names_the_runner():
    """DOC3. §1 of the runbook -- the round lifecycle -- names
    `scripts/land` as the landing step, in prose and not in a comment.
    Three controls, because a bare `in` test would pass on almost
    anything: the extractor finds a string that IS in §1 already; it does
    NOT find one that lives only in a later section; and it does not
    count a mention inside an HTML comment."""
    section = _runbook_section_one()

    assert "plugins/self-learn/cli/scripts/land" in section
    assert "scripts/suite" in section  # foreground rule, cited beside it

    # control 1 -- the extractor really reads §1
    assert "test_armor.py::ARMOR" in section
    # control 2 -- and really stops at §2 (this phrase is §2's, not §1's)
    assert "orchestrator = the main session" not in section
    # control 3 -- comment-blindness, on a constructed sample
    sample = "## 1. x\n<!-- plugins/self-learn/cli/scripts/land -->\n## 2. y\n"
    stripped = re.sub(r"<!--.*?-->", "", sample, flags=re.S)
    assert "plugins/self-learn/cli/scripts/land" not in stripped


# ---------------------------------------------------------------------------
# CHK3, rebuilt after it was measured refusing the real repository
#
# Measured 2026-08-29 against this branch's own tree:
#   python3 -m self_learn.landing.checks --root <repo> roworder
#     -> REFUSE: row order violations: FW=[(53,52), (52,49), (70,62),
#        (67,57), (61,54), (56,50), (127,120), (132,128), (131,122)] S=[]
# identical on `master`. Those nine pairs are INSIDE one contiguous table
# (FW-48/53/52/49/60/61/54 on consecutive lines, grouped by fix batch),
# so the spec's "per contiguous table run" framing does not exclude them
# and the shipped strict form would have exited 4 on every landing --
# this unit's own bootstrap included.


def test_chk3_duplicate_leg_red_green_on_real_history():
    """CHK3 leg 1, on the spec's own MEASURED pair. `37f48c4` carries the
    duplicate `FW-130` a keep-both merge left; its child `6038eee`
    collapsed it. Per contiguous run, not whole-file: `FW-30` appears in
    two different tables on purpose, and a whole-file duplicate check
    returns `[130, 30]` / `[30]` for the same two commits -- green
    nowhere, so it could not tell the defect from the corpus."""
    from self_learn.landing.checks import check_duplicate_rows

    def fw(rev: str) -> str:
        return subprocess.run(
            ["git", "show", f"{rev}:docs/specs/self-learn/14-forward-work-map.md"],
            cwd=_repo_root(), capture_output=True, text=True, check=True,
        ).stdout

    assert check_duplicate_rows(fw("37f48c4"), "FW") == [130]
    assert check_duplicate_rows(fw("6038eee"), "FW") == []
    assert check_duplicate_rows(fw("master"), "FW") == []
    assert check_duplicate_rows(fw("HEAD"), "FW") == []
    # and the whole-file form, shown to be useless on this corpus
    ids_37 = [n for run in __import__(
        "self_learn.landing.checks", fromlist=["_row_runs"]
    )._row_runs(fw("37f48c4").split("\n"), "FW") for n in run]
    assert len(ids_37) != len(set(ids_37))


def test_chk3_passes_on_the_real_repository_with_its_own_baseline():
    """The regression this rebuild exists for: CHK3 must be GREEN on the
    tree `land` will actually land, given master as the baseline. Two
    controls, so green here is not green-because-blind:
    (a) with NO baseline the same call still refuses (the strict form is
        intact, it is only the baseline that forgives);
    (b) a baseline with the nine pairs REMOVED makes it refuse again, so
        the forgiveness is genuinely pair-by-pair and not a switch."""
    from self_learn.landing.checks import (
        CheckFailure,
        check_row_order,
        check_row_order_or_raise,
    )

    root = _repo_root()
    fw_rel = "docs/specs/self-learn/14-forward-work-map.md"
    d03_rel = "docs/specs/self-learn/03-decisions.md"
    base = {
        rel: subprocess.run(
            ["git", "show", f"master:{rel}"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout
        for rel in (fw_rel, d03_rel)
    }

    check_row_order_or_raise(root, base)  # must not raise

    with pytest.raises(CheckFailure):
        check_row_order_or_raise(root, None)

    live_pairs = check_row_order((root / fw_rel).read_text(), "FW")
    assert len(live_pairs) == 9, live_pairs
    # (b) an ordered baseline forgives nothing
    ordered = "\n".join(
        [ln for ln in base[fw_rel].split("\n") if not ln.startswith("| FW-")]
    )
    with pytest.raises(CheckFailure):
        check_row_order_or_raise(root, {fw_rel: ordered, d03_rel: base[d03_rel]})


def test_chk3_still_refuses_disorder_a_merge_introduces(tmp_path):
    """CHK3 leg 2 keeps its teeth end to end: the fixture's master is
    ordered, the branch adds a descending row, and the landing refuses
    with exit 4 -- the baseline forgives only what master already had."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    LF.make_branch(
        repo, "u-disorder",
        edits={fw: (repo / fw).read_text() + "| FW-1 | out of order | WATCH | n |\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-disorder", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "CHK3" in r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_chk3_refuses_a_duplicate_row_a_merge_introduces(tmp_path):
    """CHK3 leg 1 end to end -- the keep-both-merge shape the criterion
    was written for. The sharp point is that leg 1 is BASELINE-PROOF: a
    duplicate refuses even when the baseline already contains that exact
    pair, which is what stops the leg-2 forgiveness from becoming an
    amnesty for the one defect CHK3 has a real red/green pair for."""
    from self_learn.landing.checks import (
        CheckFailure,
        check_duplicate_rows,
        check_row_order_or_raise,
    )

    repo = LF.make_repo(tmp_path, with_ui=True)
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    LF.make_branch(
        repo, "u-dupe",
        edits={fw: (repo / fw).read_text() + "| FW-2 | duplicated by a keep-both | WATCH | n |\n"},
    )

    LF.git(repo, "checkout", "-q", "u-dupe")
    branch_text = (repo / fw).read_text()
    assert check_duplicate_rows(branch_text, "FW") == [2]
    # baseline-proof: hand it its OWN content as the baseline, so leg 2
    # forgives every pair, and it still refuses on leg 1
    with pytest.raises(CheckFailure) as exc:
        check_row_order_or_raise(repo, {fw: branch_text,
                                        "docs/specs/self-learn/03-decisions.md":
                                            (repo / "docs/specs/self-learn/03-decisions.md").read_text()})
    assert "duplicates" in str(exc.value) and "2" in str(exc.value)
    LF.git(repo, "checkout", "-q", "master")

    r = LF.run_land(repo, tmp_path, "--branch", "u-dupe", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "CHK3" in r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_chk3_a_new_row_file_stays_strict():
    """The baseline must not become a blanket amnesty: a row file ABSENT
    at the baseline has no prior disorder to forgive, and the other
    file's baseline must survive that."""
    from self_learn.landing.checks import CheckFailure, check_row_order_or_raise

    root = _repo_root()
    fw_rel = "docs/specs/self-learn/14-forward-work-map.md"
    d03_rel = "docs/specs/self-learn/03-decisions.md"
    d03 = subprocess.run(
        ["git", "show", f"master:{d03_rel}"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout
    with pytest.raises(CheckFailure) as exc:
        check_row_order_or_raise(root, {d03_rel: d03})
    assert "FW" in str(exc.value)


def test_chk3_an_absent_baseline_file_does_not_void_the_others(tmp_path):
    """CHK3's baseline is per FILE. A row file that does not exist at the
    baseline has no prior disorder to forgive and stays strict -- and that
    must NOT collapse the whole baseline to None, which would hand the
    OTHER file back to the strict form and refuse a correct landing.

    Driven through the shipped CLI, because that is where the baseline is
    assembled. The fixture puts pre-existing disorder in the FW file at
    the base and adds the decisions file only in the working tree.
    """
    repo = tmp_path / "r"
    (repo / "docs/specs/self-learn").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    LF.git(repo, "config", "user.email", "t@example.invalid")
    LF.git(repo, "config", "user.name", "T")
    fw = repo / "docs/specs/self-learn/14-forward-work-map.md"
    fw.write_text(
        "| id | s | st | n |\n|---|---|---|---|\n"
        "| FW-5 | five | WATCH | n |\n| FW-3 | three | WATCH | n |\n"
    )
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "base: FW already disordered, 03 absent")

    d03 = repo / "docs/specs/self-learn/03-decisions.md"
    d03.write_text("| id | s | r |\n|---|---|---|\n| S-1 | one | r |\n| S-2 | two | r |\n")

    def roworder() -> subprocess.CompletedProcess:
        return subprocess.run(
            ["uv", "run", "--no-sync", "python3", "-m", "self_learn.landing.checks",
             "--root", str(repo), "roworder", "--base", "HEAD"],
            cwd=LF.THIS_REPO_CLI, capture_output=True, text=True,
        )

    ok = roworder()
    assert ok.returncode == 0, ok.stdout + ok.stderr
    # the baseline really was partial -- one file, not two
    assert "1 file(s)" in ok.stdout, ok.stdout

    # positive control: disorder this "merge" ADDS is still refused
    fw.write_text(fw.read_text() + "| FW-1 | one | WATCH | n |\n")
    bad = roworder()
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "INTRODUCED by this merge" in bad.stderr, bad.stderr


# ---------------------------------------------------------------------------
# SUI7 -- the docs-only lane's test set is a checked-in file, and the walk
# ships as code
#
# Found unbuilt at build time, and the shipped file had already ROTTED:
# measured 2026-08-29, `walk.py --union` derived 11 modules while
# doc_reading_set.txt carried 8 -- missing test_armor.py (which arrived
# with U-armor's merge) and this unit's own test_land_runner.py /
# test_landing_checks.py / test_landing_fixture.py, and still carrying
# test_u_sdka.py, whose doc literal U-armor removed. A docs-only landing
# would have run a set that omitted the modules that actually read docs,
# including the ones reading 03-decisions.md and 14-forward-work-map.md.


def _walk(*args: str) -> str:
    return subprocess.run(
        [sys.executable, str(LF.THIS_REPO_CLI / "scripts/measured/walk.py"), *args],
        cwd=_repo_root(), capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_doc_reading_set():
    """SUI7, six legs.

    (a) the shipped set EQUALS the union of direct-hit and part-constant
        modules under the walk;
    (b) the strict `src/` count is 0 and must stay 0 -- a detector: any
        `src/` module gaining a real doc-path constant forces the full
        lane. Positive control constructed live;
    (c) the three columns are reported together, naive >= inclusive >=
        strict, so a docstring-inclusive count can never again be shown
        as strict;
    (d) `test_reader_contract.py` -- which holds `'docs'` and `'specs'`
        as SEPARATE constants -- is in the set, pinning the part-built
        route;
    (e) a SYNTHETIC part-built module that is not a direct hit is picked
        up by the union (today the part-built set is a subset of the
        direct set, so a dropped union step would otherwise be invisible);
    (f) the walk reads the same with the §6.1 helpers installed at their
        SHIPPED path -- and demonstrably different if they were under
        `cli/tests/`, which is why they are not.

    The absolute counts are deliberately NOT pinned. They drift with the
    corpus (144 modules at spec time, 153 now), and pinning a drifting
    number into a criterion is the M-19 class of defect: a build that
    refuses everywhere but one machine at one moment.
    """
    root = _repo_root()
    shipped_path = root / "plugins/self-learn/cli/src/self_learn/landing/doc_reading_set.txt"
    shipped = [l for l in shipped_path.read_text().split("\n") if l.strip()]

    # (a)
    union = [l for l in _walk("--union").split("\n") if l.strip()]
    assert sorted(shipped) == sorted(union), {
        "missing_from_shipped": sorted(set(union) - set(shipped)),
        "stale_in_shipped": sorted(set(shipped) - set(union)),
    }
    assert shipped == sorted(shipped), "the shipped set must be sorted, so a diff is readable"

    # (b) -- the detector, with a live positive control
    assert _walk("src", "strict") == "0"
    probe = root / "plugins/self-learn/cli/src/self_learn/probe_sui7b.py"
    assert not probe.exists()
    probe.write_text('DOC = "docs/specs/self-learn/03-decisions.md"\n')
    try:
        assert _walk("src", "strict") != "0", "leg (b) is vacuous: a real src doc constant went unseen"
    finally:
        probe.unlink()
    assert _walk("src", "strict") == "0"

    # (c)
    naive, incl, strict = (int(_walk("tests", c)) for c in ("naive", "incl", "strict"))
    assert naive >= incl >= strict > 0, (naive, incl, strict)

    # (d)
    assert "plugins/self-learn/cli/tests/test_reader_contract.py" in shipped

    # (e) -- a synthetic part-built module that is NOT a direct hit
    synth = root / "plugins/self-learn/cli/tests/test_sui7e_partbuilt_probe.py"
    assert not synth.exists()
    synth.write_text('_A = "docs"\n_B = "specs"\nPATH = _A + "/" + _B\n')
    try:
        union2 = [l for l in _walk("--union").split("\n") if l.strip()]
        direct = [l for l in _walk("--direct").split("\n") if l.strip()]
        rel = "plugins/self-learn/cli/tests/test_sui7e_partbuilt_probe.py"
        assert rel not in direct, "the probe must NOT be a direct hit, or leg (e) proves nothing"
        assert rel in union2, "the union dropped a part-built module"
    finally:
        synth.unlink()
    assert not synth.exists()

    # (f) -- the shipped location, and the location that would self-count
    before = _walk("tests", "strict")
    probe_dir = root / "plugins/self-learn/cli/tests/measured_sui7f_probe"
    probe_dir.mkdir()
    try:
        shutil.copy(LF.THIS_REPO_CLI / "scripts/measured/walk.py", probe_dir / "walk.py")
        after = _walk("tests", "strict")
        assert int(after) > int(before), (
            "leg (f) is vacuous: walk.py under cli/tests did not count itself, so the "
            "shipped location under cli/scripts/measured/ is not load-bearing"
        )
    finally:
        shutil.rmtree(probe_dir)
    assert _walk("tests", "strict") == before
