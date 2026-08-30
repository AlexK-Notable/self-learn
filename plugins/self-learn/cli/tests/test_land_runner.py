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
from typing import Any

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
    repo = LF.make_repo(tmp_path, with_ui=True)
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
    """SUI3 leg 2. `with_ui=True` is load-bearing exactly as it is one
    screen above: without a UI tree, B-2's `need_dir` exits 5 BEFORE the
    allowlist is ever consulted, so inverting the allowlist rule wholesale
    left both SUI3 tests green (gate r2). The refusal must come from the
    adjudication, and the assertions below say so."""
    repo = LF.make_repo(tmp_path, with_ui=True)
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
    assert r.returncode == 5, r.stdout + r.stderr
    # the refusal is the ALLOWLIST's, naming the id that is not on it --
    # not a guard that fired before the allowlist ran
    assert "not-allowlisted" in r.stderr, r.stderr
    assert "test_red2.py::test_also_fails" in r.stderr, r.stderr


def test_sui6_rename_into_docs_without_no_renames_takes_full_lane(tmp_path):
    """SUI6 leg (h) (M71): a src module RENAMED into docs/ must still take
    the FULL lane -- git's rename detection (without --no-renames) would
    otherwise report the change as a single path already under docs/,
    hiding what is really a deleted src module."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.git(repo, "checkout", "-q", "-b", "u-rename")
    (repo / "docs/specs/self-learn/drafts").mkdir(parents=True, exist_ok=True)
    # The keeper (`test_keep.py`) lives on MASTER, not here. Gate r1 M-4:
    # adding it on the BRANCH made this test vacuous -- it became a second
    # changed non-docs path, so NONDOC was 2 with `--no-renames` and 1
    # without, and BOTH forms took the full lane. The rename must be the
    # branch's ONLY change for the detector's two forms to disagree.
    LF.git(
        repo, "mv",
        "plugins/self-learn/cli/tests/test_alpha.py",
        "docs/specs/self-learn/drafts/renamed-test-alpha.py",
    )
    LF.git(repo, "commit", "-q", "-m", "rename a src module into docs/")
    LF.git(repo, "checkout", "-q", "master")

    # the discriminating measurement, before the landing: the two detector
    # forms must DISAGREE on this branch, or the test proves nothing
    def nondoc(*extra: str) -> int:
        out = LF.git(repo, "diff", *extra, "--name-only", f"master..u-rename").stdout
        return len([l for l in out.split("\n") if l.strip() and not l.startswith("docs/")])

    assert nondoc("--no-renames") == 1, LF.git(repo, "diff", "--no-renames", "--name-only", "master..u-rename").stdout
    assert nondoc() == 0, LF.git(repo, "diff", "--name-only", "master..u-rename").stdout

    r = LF.run_land(repo, tmp_path, "--branch", "u-rename", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())
    assert (logs / "cli.log").exists(), "took the docs lane -- --no-renames was not applied"
    assert not (logs / "docslane.log").exists()


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
    assert "run_merge_and_checks() {" in text, "structural anchor missing"

    # The property is about what the STEP-1 precondition block EXECUTES.
    # Two things a substring over "everything above run_merge_and_checks"
    # gets wrong, both measured: it flags the COMMENT explaining why the
    # call is absent, and it flags a helper DEFINED above that block and
    # only ever CALLED from inside the merge.
    # NIT-4: the audited region starts at the `--continue`/CNT1 block, not
    # at Step 1 -- CNT1 runs BEFORE the preconditions and can refuse, and it
    # was outside the slice entirely.
    start = text.index("# --continue / CNT1")
    end = text.index("# GITROOT:")
    step1 = text[start:end]
    assert "CNT1" in step1 and "PRE1" in step1, "the slice lost one of the two blocks"
    funcs = _shell_functions(text)
    reachable = _reachable_text(step1, funcs)

    def calls(block: str) -> list[str]:
        return [
            ln.strip() for ln in block.split("\n")
            if "merge --abort" in ln and not ln.lstrip().startswith("#")
        ]

    assert calls(reachable) == [], calls(reachable)

    # control 1 -- a direct call in the block IS reported
    assert calls(_reachable_text(step1 + '\n  git -C "$ROOT" merge --abort\n', funcs))
    # control 2 -- and so is one reached THROUGH a helper, which a flat
    # slice of the block alone could not see
    assert "abort_merge_unless_resuming" in funcs
    assert calls(_reachable_text(step1 + '\n  abort_merge_unless_resuming "$ROOT"\n', funcs))
    # the prose the old form tripped on is still in the file
    assert "merge --abort" in text


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


def _shell_functions(text: str) -> dict[str, str]:
    """name -> body, for every `name() {` ... `}` at any indent. The closing
    brace is found by brace depth, so nested blocks do not end a body early."""
    out: dict[str, str] = {}
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{\s*$", line)
        if not m:
            continue
        depth = 1
        body: list[str] = []
        for nxt in lines[i + 1:]:
            depth += nxt.count("{") - nxt.count("}")
            if depth <= 0:
                break
            body.append(nxt)
        out[m.group(2)] = "\n".join(body)
    return out


def _reachable_text(slice_text: str, funcs: dict[str, str]) -> str:
    """`slice_text` plus the bodies of every function it calls, transitively.
    A file-position slice alone cannot see a helper DEFINED earlier and
    CALLED inside the window -- which is exactly what CHK8 forbids."""
    seen: set[str] = set()
    acc = [slice_text]
    frontier = [slice_text]
    while frontier:
        chunk = frontier.pop()
        for name, body in funcs.items():
            if name in seen:
                continue
            if re.search(r"(?:^|[\s;(&|`$])" + re.escape(name) + r"(?:\s|$|;|\))", chunk, re.M):
                seen.add(name)
                acc.append(body)
                frontier.append(body)
    return "\n".join(acc)


def _post_remeasure_window(text: str, funcs: dict[str, str]) -> tuple[str, str]:
    """The text that actually EXECUTES between the armor re-measure and
    `git commit`, which is not a file slice:

      (a) the tail of the function that CONTAINS the re-measure, from that
          line to the end of its body; then
      (b) from that function's call site to the commit line.

    Returns (window, owner-function-name).
    """
    owner = next((n for n, b in funcs.items() if "--remeasure --anchor" in b), None)
    assert owner is not None, "no function contains the re-measure"
    body = funcs[owner]
    tail = body[body.index("--remeasure --anchor"):]
    call_at = text.index(owner + ' "$GITROOT"')
    commit_at = text.index('commit -q -m "$SUBJECT"')
    assert call_at < commit_at
    after_call = text[call_at + len(owner):commit_at]
    return tail + "\n" + after_call, owner


def test_chk8_nothing_test_shaped_runs_between_the_armor_step_and_the_commit():
    """CHK8 (M55/M56). Gate r1 M-2: the old test was a file-position slice,
    which the criterion explicitly forbids -- a pytest helper DEFINED
    earlier in the script and CALLED inside the window satisfied it.

    This models EXECUTION order (see `_post_remeasure_window`) and then
    resolves every function call in that window to its body, transitively,
    before searching. Two positive controls, both constructed live: an
    injected call to an earlier-defined helper is caught, and a bare
    injected `pytest` is caught.
    """
    text = LF.LAND.read_text()
    funcs = _shell_functions(text)
    assert "run_suite" in funcs and "adjudicate_suite" in funcs, sorted(funcs)

    window, owner = _post_remeasure_window(text, funcs)
    callable_bodies = {n: b for n, b in funcs.items() if n != owner}
    reachable = _reachable_text(window, callable_bodies)
    for needle in ("pytest", "run_suite", "adjudicate_suite"):
        assert needle not in reachable, (needle, window[:400])

    # control 1 -- a CALL to an earlier-defined test-shaped helper, which a
    # file-position slice cannot see and this instrument must. The needle
    # SET is what the real assertion uses, so that is what is controlled.
    needles = ("pytest", "run_suite", "adjudicate_suite")
    doctored = _reachable_text(window + "\n  adjudicate_suite cli\n", callable_bodies)
    assert any(n in doctored for n in needles), doctored[-400:]
    # and it reached through the helper to its OWN callees, not just matched
    # the injected token -- `allowlisted_only` is one hop further in
    assert "allowlisted_only" in doctored

    # control 2 -- a bare inline invocation
    assert "pytest" in _reachable_text(window + "\n  uv run pytest x\n", callable_bodies)


def test_chk8_the_instrument_resolves_calls_transitively():
    """The resolver's own unit control: a two-hop chain (window -> outer ->
    inner) must reach `inner`'s body. Without transitivity CHK8 is only a
    one-level check and a helper that wraps a helper slips through."""
    funcs = {
        "outer": "  inner\n",
        "inner": "  uv run pytest something\n",
        "unrelated": "  echo hi\n",
    }
    assert "pytest" in _reachable_text("  outer\n", funcs)
    assert "pytest" not in _reachable_text("  unrelated\n", funcs)


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
    # (i) the suite's own working directory is absent: B-2's guard catches
    # this BEFORE the suite runs, and says so.
    repo = LF.make_repo(tmp_path / "blind", with_ui=False)
    LF.make_branch(
        repo, "u-noui",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path / "blind", "--branch", "u-noui", "--verdict", "v", timeout=180)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "working directory: required directory is ABSENT" in r.stderr, r.stderr

    # (ii) the suite RUNS, fails, and prints nothing a node id can be parsed
    # from -- the shape the allowlist genuinely cannot adjudicate.
    silent = LF.make_repo(tmp_path / "silent", with_ui=True)
    LF.git(silent, "checkout", "-q", "-b", "u-silent")
    s = silent / "plugins/self-learn/cli/scripts/suite"
    s.write_text("#!/usr/bin/env bash\necho 'the runner exploded' >&2\nexit 3\n")
    s.chmod(0o755)
    LF.git(silent, "add", "-A")
    LF.git(silent, "commit", "-q", "-m", "a suite that fails without reporting")
    LF.git(silent, "checkout", "-q", "master")
    r2 = LF.run_land(silent, tmp_path / "silent", "--branch", "u-silent", "--verdict", "v", timeout=180)
    assert r2.returncode == 5, r2.stdout + r2.stderr
    assert "NO FAILED/ERROR node id" in r2.stderr, r2.stderr
    assert "SUI9" in r2.stderr

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
    # Point the suite runner at a directory that holds no tests -- the
    # realistic shape of this regression (a suite whose target path moved),
    # and one that leaves CHK5's own gate file in place, since an ABSENT
    # personal-literals gate is now its own fatal refusal (B-2).
    suite = repo / "plugins/self-learn/cli/scripts/suite"
    suite.write_text(suite.read_text().replace(
        "plugins/self-learn/cli/tests", "plugins/self-learn/cli/src", 1))
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "point the suite at a directory with no tests")
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


def test_sui9_the_empty_case_never_returns_success():
    """The adjudicator's own unit control, at the seam where the defect
    lived. An empty failing set is `unparseable-log`, never the OK verdict
    -- and the OK verdict requires at least one id that IS allowlisted, so
    "found nothing" and "found nothing wrong" can never coincide."""
    from self_learn.landing import suites as S

    root = _repo_root()
    allow = root / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt"
    entry = S.allowlist_entries(allow)[0]
    ui = root / "plugins/self-learn/ui"

    assert S.adjudicate("", ui, root, allow)[0] == S.VERDICT_UNPARSEABLE
    assert S.adjudicate("1 failed, 0 passed\n", ui, root, allow)[0] == S.VERDICT_UNPARSEABLE
    # positive control: a parseable, allowlisted failure IS the OK verdict
    local = entry.split("plugins/self-learn/ui/", 1)[1]
    assert S.adjudicate(f"FAILED {local}\n", ui, root, allow)[0] == S.VERDICT_OK
    # and one more failure alongside it is not
    assert S.adjudicate(f"FAILED {local}\nFAILED tests/test_other.py::test_z\n",
                        ui, root, allow)[0] == S.VERDICT_NOT_ALLOWLISTED
    # a missing allowlist is its own refusal, never a pass
    assert S.adjudicate(f"FAILED {local}\n", ui, root, root / "nope.txt")[0] == S.VERDICT_NO_ALLOWLIST
    # the shell no longer carries the defective form
    assert '[ -n "$failing" ] || return 0' not in LF.LAND.read_text()


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


def _armor_anchor(repo: Path) -> str:
    text = (repo / "plugins/self-learn/cli/tests/test_armor.py").read_text()
    m = re.search(r'^ANCHOR = "([^"]*)"', text, re.M)
    assert m is not None, text[:200]
    return m.group(1)


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
    # The predicate is "no USABLE collection", not a specific failing code.
    # Measured 2 (collection errors) until U-xdist landed and 3 (pluggy
    # INTERNALERROR -- the CLI conftest declares `pytest_testnodedown`,
    # which the UI venv has no plugin for) after it. Pinning the code would
    # have reddened this on a correct tree the day that landed: the M-19
    # lesson, one criterion over.
    assert from_root.returncode != 0, from_root.stdout[-2000:]
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

    # N-17's blind spot, WITHOUT writing into the live tracked tree.
    # Gate r4 MIN-4: this used to create `ui/tests/test_sui8_untracked_
    # scratch_probe.py` in the production checkout. A sibling agent's stray
    # probe in that exact directory nearly broke a landing tonight -- while
    # present it would have tripped PRE3 at exit 2 -- and a test that does
    # it is worse than an agent doing it, because it recurs.
    #
    # The property does not need pytest to collect the file: it is that a
    # PREFIX check and an `ls-files` MEMBERSHIP check disagree about a path
    # that is inside `tests/` but untracked. That is decidable from the
    # real collected ids plus one synthetic id, and touches nothing.
    synthetic = "tests/test_sui8_untracked_scratch_probe.py::test_probe"
    assert synthetic.split("::", 1)[0] not in tracked, "the probe path is tracked; control void"
    ids_with_probe = ids + [synthetic]

    def prefix_ok(node_ids: list[str]) -> bool:
        """The check N-17 measured as INSUFFICIENT."""
        return all(i.startswith("tests/") for i in node_ids)

    def membership_ok(node_ids: list[str]) -> bool:
        """Leg (e) itself: every collected id maps to a TRACKED file."""
        return {i.split("::", 1)[0] for i in node_ids} <= tracked

    # on the real collection the two agree, so neither is trivially false
    assert prefix_ok(ids) and membership_ok(ids)

    # the whole of leg (e) is that they DISAGREE about an untracked path
    # inside tests/. Stated as the disagreement, so replacing the
    # membership check with a prefix check cannot pass: the two would then
    # agree and this assertion fails.
    assert prefix_ok(ids_with_probe), "the prefix check should be satisfied -- that is the blind spot"
    assert not membership_ok(ids_with_probe), "leg (e) did not see the untracked path"
    assert prefix_ok(ids_with_probe) != membership_ok(ids_with_probe), (
        "leg (e) has collapsed into the prefix check it exists to strengthen"
    )

    # and nothing was written into the live tree by this test at all
    assert not (ui / "tests" / "test_sui8_untracked_scratch_probe.py").exists()


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


def test_doc_reading_set(tmp_path):
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
    corpus (144 modules at spec time, 153 then, more now), and pinning a
    drifting number into a criterion is the M-19 class of defect.

    **Every leg that WRITES runs in a throwaway clone.** Legs (b), (e) and
    (f) used to create and delete probe files in the live tree; under
    U-xdist's `-n auto` that raced other workers -- measured, it reddened
    this test and `test_armor.py::test_arm6_refusal_writes_nothing`, both
    of which pass alone. A test that mutates the tree the suite is reading
    cannot be parallel-safe, and the fix is isolation, not serialisation.
    """
    root = _repo_root()
    shipped_path = root / "plugins/self-learn/cli/src/self_learn/landing/doc_reading_set.txt"
    shipped = [l for l in shipped_path.read_text().split("\n") if l.strip()]

    # (a) -- read-only against the live tree
    union = [l for l in _walk("--union").split("\n") if l.strip()]
    assert sorted(shipped) == sorted(union), {
        "missing_from_shipped": sorted(set(union) - set(shipped)),
        "stale_in_shipped": sorted(set(shipped) - set(union)),
    }
    assert shipped == sorted(shipped), "the shipped set must be sorted, so a diff is readable"

    # (c) -- read-only
    naive, incl, strict = (int(_walk("tests", c)) for c in ("naive", "incl", "strict"))
    assert naive >= incl >= strict > 0, (naive, incl, strict)

    # (d) -- read-only
    assert "plugins/self-learn/cli/tests/test_reader_contract.py" in shipped

    # --- the writing legs, in a throwaway clone
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(root), str(clone)],
                   check=True, capture_output=True)
    # A clone carries COMMITTED content, so an uncommitted edit to the walk
    # -- which is exactly what a mutation is, and what a code gate reviews --
    # would be invisible to every leg below. The live instrument is copied
    # in, and asserted byte-identical, so the clone isolates the WRITES
    # without also isolating the code under test. Measured: without this,
    # M92 (dropping the part-built union) came back STILL-GREEN.
    live_measured = root / "plugins/self-learn/cli/scripts/measured"
    clone_measured = clone / "plugins/self-learn/cli/scripts/measured"

    # NIT-1: asserting the copy equals its source right after copying is a
    # tautology, and this assertion IS the fix for the clone blind spot --
    # a tautological one leaves the blind spot free to come back. So the
    # clone's copy is POISONED first: the assertion below now fails if the
    # refresh is removed, which is exactly the regression it guards.
    poison = b"raise SystemExit('the clone was not refreshed from the live tree')\n"
    (clone_measured / "walk.py").write_bytes(poison)
    assert (clone_measured / "walk.py").read_bytes() == poison

    shutil.rmtree(clone_measured)
    shutil.copytree(live_measured, clone_measured,
                    ignore=shutil.ignore_patterns("__pycache__"))
    walk_py = clone_measured / "walk.py"
    assert walk_py.read_bytes() == (live_measured / "walk.py").read_bytes()
    assert walk_py.read_bytes() != poison

    def cwalk(*args: str) -> str:
        return subprocess.run(
            [sys.executable, str(walk_py), *args],
            cwd=clone, capture_output=True, text=True, check=True,
        ).stdout.strip()

    # the clone reproduces the live reading, or the legs below prove nothing
    assert cwalk("src", "strict") == _walk("src", "strict")
    assert [l for l in cwalk("--union").split("\n") if l.strip()] == union

    # (b) -- the detector, with a live positive control
    assert cwalk("src", "strict") == "0"
    probe = clone / "plugins/self-learn/cli/src/self_learn/probe_sui7b.py"
    probe.write_text('DOC = "docs/specs/self-learn/03-decisions.md"\n')
    assert cwalk("src", "strict") != "0", "leg (b) is vacuous: a real src doc constant went unseen"
    probe.unlink()
    assert cwalk("src", "strict") == "0"

    # (e) -- a synthetic part-built module that is NOT a direct hit
    synth = clone / "plugins/self-learn/cli/tests/test_sui7e_partbuilt_probe.py"
    synth.write_text('_A = "docs"\n_B = "specs"\nPATH = _A + "/" + _B\n')
    rel = "plugins/self-learn/cli/tests/test_sui7e_partbuilt_probe.py"
    direct = [l for l in cwalk("--direct").split("\n") if l.strip()]
    union2 = [l for l in cwalk("--union").split("\n") if l.strip()]
    assert rel not in direct, "the probe must NOT be a direct hit, or leg (e) proves nothing"
    assert rel in union2, "the union dropped a part-built module"
    synth.unlink()

    # (f) -- the shipped location, and the location that would self-count
    before = cwalk("tests", "strict")
    probe_dir = clone / "plugins/self-learn/cli/tests/measured_sui7f_probe"
    probe_dir.mkdir()
    shutil.copy(walk_py, probe_dir / "walk.py")
    after = cwalk("tests", "strict")
    assert int(after) > int(before), (
        "leg (f) is vacuous: walk.py under cli/tests did not count itself, so the "
        "shipped location under cli/scripts/measured/ is not load-bearing"
    )
    shutil.rmtree(probe_dir)
    assert cwalk("tests", "strict") == before

    # and the LIVE tree was never touched by any of it
    assert not (root / "plugins/self-learn/cli/src/self_learn/probe_sui7b.py").exists()
    assert not (root / "plugins/self-learn/cli/tests/measured_sui7f_probe").exists()
    assert not (root / rel).exists()



# ---------------------------------------------------------------------------
# Restored verbatim after a slice-based edit removed them (r2 build round).
# Recovered from the bytes saved before the edit, not retyped from memory.

def test_chk5_invokes_the_real_shipped_personal_literals_test_not_a_private_grep():
    """M25: CHK5 must shell out to U-scrub's real test_personal_literals.py
    via pytest, never reimplement it as a private in-runner grep scoped to
    docs/ (which would miss any hit outside docs/)."""
    text = LF.LAND.read_text()
    # Structural, not a fixed-width slice: take every NON-comment line that
    # mentions the gate file, plus the command they are part of. A byte
    # window silently stops covering the invocation the moment the block
    # grows -- which is exactly what happened when CHK5's absence became
    # fatal and the block gained six lines.
    lines = [
        ln for ln in text.split("\n")
        if "test_personal_literals.py" in ln and not ln.lstrip().startswith("#")
    ]
    assert lines, "CHK5 names the gate file nowhere outside comments"
    # follow the variable the path is bound to, so the check does not depend
    # on the invocation spelling the filename out
    var = None
    for ln in lines:
        m = re.match(r"\s*local\s+([A-Za-z_][A-Za-z0-9_]*)=", ln)
        if m:
            var = m.group(1)
            break
    assert var, lines
    users = [ln for ln in text.split("\n")
             if f'${var}' in ln and not ln.lstrip().startswith("#")]
    invocation = [ln for ln in users if "pytest" in ln]
    assert invocation, users
    assert all("grep" not in ln for ln in lines + users), lines + users
    # it runs the TARGET TREE's copy ($gr), never the main checkout's ($ROOT)
    assert any('"$gr/plugins/self-learn/cli/tests/test_personal_literals.py"' in ln
               or '$gr/plugins/self-learn/cli/tests/test_personal_literals.py' in ln
               for ln in lines), lines
    # and absence is FATAL, not a skip (B-2)
    assert "refusing to land unscanned" in text


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
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-collecterr",
        edits={"plugins/self-learn/cli/tests/test_broken_syntax.py": "def test_broken(:\n    pass\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-collecterr", "--verdict", "v", timeout=180)
    assert r.returncode == 5
    assert "COLLECTION ERROR" in r.stderr


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


def test_un2_never_touches_the_ledger():
    """UN2. Neither the runner nor the landing package may read or write
    the ledger (`~/.self-learn`, `SELF_LEARN_HOME`).

    Gate r2 MAJOR-4: this used to be PYTHON regexes applied to a BASH
    script -- `os.environ.*SELF_LEARN_HOME` and two quoted-literal forms --
    so a shell `${SELF_LEARN_HOME:-...}` read passed straight through, and
    only 47 fixtures breaking incidentally caught the case. Each language
    is now checked in its own terms, and the claim is narrowed to what is
    actually detected: the TOKENS, anywhere outside a comment or docstring.

    Positive controls, constructed live, for BOTH languages.
    """
    import ast as _ast

    TOKENS = ("SELF_LEARN_HOME", ".self-learn")

    def shell_offenders(text: str) -> list[str]:
        """Bash: any occurrence outside a whole-line comment. Deliberately
        blunt -- the runner has no legitimate use for either token, so
        there is nothing to distinguish and no reason to parse."""
        out = []
        for i, line in enumerate(text.split("\n"), 1):
            if line.lstrip().startswith("#"):
                continue
            for tok in TOKENS:
                if tok in line:
                    out.append(f"{i}: {line.strip()}")
        return out

    def python_offenders(text: str) -> list[str]:
        """Python: every string constant and every Name/Attribute, with
        docstrings excluded by walking the AST rather than by regex --
        prose that NAMES the ledger to say it is never touched is not a
        read, and `state.py`'s module docstring does exactly that."""
        tree = _ast.parse(text)
        docstrings = set()
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], _ast.Expr) and isinstance(body[0].value, _ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        out = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                if any(tok in node.value for tok in TOKENS):
                    out.append(f"line {node.lineno}: string {node.value[:40]!r}")
            elif isinstance(node, _ast.Name) and any(tok in node.id for tok in TOKENS):
                out.append(f"line {node.lineno}: name {node.id}")
            elif isinstance(node, _ast.Attribute) and any(tok in node.attr for tok in TOKENS):
                out.append(f"line {node.lineno}: attribute {node.attr}")
        return out

    land_text = LF.LAND.read_text()
    assert shell_offenders(land_text) == [], shell_offenders(land_text)
    for py in sorted(LF.LANDING_PKG.glob("*.py")):
        found = python_offenders(py.read_text())
        assert found == [], (py.name, found)

    # --- positive control 1: the SHELL form the old check could not see
    shell_probe = 'HOME_DIR="${SELF_LEARN_HOME:-$HOME/.self-learn}"\n'
    assert shell_offenders(shell_probe), "the shell check cannot see a ${...} read"
    # and the OLD regex form is shown blind to it, so the control is real
    old_form = [
        re.compile(r"os\.environ.{0,20}SELF_LEARN_HOME"),
        re.compile(r"getenv\(.{0,5}SELF_LEARN_HOME"),
        re.compile(r'"\.self-learn"'),
        re.compile(r"'\.self-learn'"),
    ]
    assert not any(p.search(shell_probe) for p in old_form), (
        "the old regexes DO catch this, so MAJOR-4's premise no longer holds"
    )

    # --- positive control 2: the PYTHON forms
    assert python_offenders('import os\nx = os.environ["SELF_LEARN_HOME"]\n')
    assert python_offenders('p = Path.home() / ".self-learn"\n')
    # ... and prose that merely NAMES it is not a violation
    assert python_offenders('"""never reads ~/.self-learn."""\n') == []



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
    # the refusal names the LEG and counts its lines (runbook 5.1)
    assert "refused BEFORE writing" in r.stderr, r.stderr
    assert "1 OWED" in r.stderr, r.stderr
    assert "file intact: yes" in r.stderr, r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _armor_anchor(repo) == "0000000"
    log = Path(r.stderr.split("cat ")[-1].strip()).read_text()
    assert log.startswith("OWED: "), log
    # the trailer carries no bare token, so an anchored match is the contract
    assert "refusing to write test_armor.py (" in log


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
    assert "nothing to advance (the no-op guard)" in r.stderr, r.stderr
    # the no-op is POST-write: the contract promises byte-IDENTICAL, and the
    # runner verifies that rather than trusting it
    assert "file intact: yes" in r.stderr, r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    log = Path(r.stderr.split("cat ")[-1].strip()).read_text()
    assert log.startswith("ANCHOR did not change ("), log


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

    # PYTHONDONTWRITEBYTECODE is explicitly REMOVED: this run exists to
    # author the .pyc whose staleness the rest of the test is about, so it
    # must not inherit an ambient setting that suppresses it (the mutation
    # harness sets exactly that).
    bytecode_env = {k: v for k, v in os.environ.items()
                    if k != "PYTHONDONTWRITEBYTECODE"}
    red = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "-p", "no:cacheprovider"],
        cwd=repo, capture_output=True, text=True, env=bytecode_env,
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
        cwd=repo, capture_output=True, text=True, env=bytecode_env,
    )
    assert green.returncode == 0, green.stdout + green.stderr


def test_exc1_shell_contract():
    """EXC1. The shell contract is `set -uo pipefail`, never `-e`.

    Gate r1 M-6: the previous form was vacuous in BOTH directions.
    `"set -uo pipefail" in text` was satisfied by the header COMMENT that
    explains the rule, so dropping the real directive passed; and
    `re.search(r"^set -e\b")` never matched `set -euo pipefail`, because
    the character after `-e` is `u`, a word character, so there is no word
    boundary there. Both mutants were green.

    The fix is to derive the EXECUTABLE directives and compare the LIST.
    """
    text = LF.LAND.read_text()
    directives = [
        ln.strip() for ln in text.split("\n")
        if ln.strip().startswith("set ") and not ln.lstrip().startswith("#")
    ]
    assert directives == ["set -uo pipefail"], directives

    # every mutant the old form let through, shown caught by THIS comparison
    for mutant in ("set -euo pipefail", "set -uo", "set -e", "set -eo pipefail"):
        assert [mutant] != directives

    # and the comment that used to satisfy the old check is still present,
    # so this is not passing merely because the explanatory prose vanished
    assert "set -uo pipefail, NOT -e" in text


# ---------------------------------------------------------------------------
# B-3 / SUI4 -- the allowlist's own accuracy, and the frame it lives in
#
# This criterion was `[A]` with NO test, and it is the one that would have
# caught B-1: the shipped allowlist entry named a node id in the repo-root
# frame while the UI suite ran from `plugins/self-learn/ui`, so pytest
# printed `tests/…` and the entry matched nothing. Every real landing
# refused. A bogus entry left 139/139 green.


def test_sui4_known_failures_all_resolve():
    """SUI4. Every id in `known_failures.txt` must still COLLECT, run from
    the package that owns it (found by walking up to the nearest
    `pyproject.toml`, never a hardcoded suite table). Two controls:
    a bogus id must NOT collect, and a real one must."""
    from self_learn.landing import suites as S

    root = _repo_root()
    allow = root / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt"
    entries = S.allowlist_entries(allow)
    assert entries, "an EMPTY allowlist would make this test vacuous"

    results = S.collect_check(root, entries)
    stale = [(e, rc) for e, rc in results if rc != 0]
    assert not stale, stale

    # positive control -- a bogus id in the same frame must be reported stale
    bogus = "plugins/self-learn/ui/tests/test_service_unit.py::test_this_does_not_exist"
    assert S.collect_check(root, [bogus])[0][1] != 0

    # and the package resolution is real, not a guess
    assert S.package_root_for(root, "plugins/self-learn/ui/tests/test_service_unit.py") \
        == root / "plugins/self-learn/ui"
    assert S.package_root_for(root, "plugins/self-learn/cli/tests/test_land_runner.py") \
        == root / "plugins/self-learn/cli"


def test_sui4_the_allowlist_is_readable_in_the_frame_the_suite_runs_from():
    """B-1's regression guard, stated as the property that failed: every
    allowlist entry must normalise to the SAME string whether it is read
    from the repo root or produced by pytest in the package it belongs to.

    Red control first: the naive same-frame comparison that shipped is
    shown to reject the very entry the repository carries."""
    from self_learn.landing import suites as S

    root = _repo_root()
    allow = root / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt"
    for entry in S.allowlist_entries(allow):
        rel_file, rest = S.split_node_id(entry)
        pkg = S.package_root_for(root, rel_file)
        as_pytest_prints_it = str(Path(rel_file).relative_to(pkg.relative_to(root))) + rest \
            if pkg != root else entry

        # the shipped, naive comparison -- what B-1 actually was
        assert as_pytest_prints_it != entry or pkg == root, (
            "this entry is in the same frame either way, so it cannot "
            "demonstrate the defect"
        )
        naive_ok = as_pytest_prints_it in set(S.allowlist_entries(allow))
        assert not naive_ok, "the naive compare accepted it -- the red control is gone"

        # the shipped fix
        assert S.to_root_frame(as_pytest_prints_it, pkg, root) == \
            S.to_root_frame(entry, root, root)


def test_sui4_a_bogus_allowlist_entry_makes_a_landing_refuse(tmp_path):
    """SUI4 end to end. An allowlist naming a test that does not exist must
    not quietly tolerate a red suite: the failing id is compared against it
    and does not match, so the landing refuses."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    (repo / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt").write_text(
        "plugins/self-learn/cli/tests/test_ghost.py::test_that_never_existed\n"
    )
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "a stale allowlist")
    LF.make_branch(
        repo, "u-stale",
        edits={"plugins/self-learn/cli/tests/test_red.py": "def test_fails():\n    assert False\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-stale", "--verdict", "v", timeout=180)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "not-allowlisted" in r.stderr, r.stderr


# ---------------------------------------------------------------------------
# B-4 / UN4 -- the MEASURED ledger's instruments are exercised by the suite
#
# `floor.py` and `parse.py` ran nowhere in the suite, so gutting `_lib.sh`'s
# `need()` left 139/139 green. Both reproduce today; this is coverage, and
# an instrument nothing exercises is one nobody will notice breaking.


def _measured(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LF.THIS_REPO_CLI / "scripts/measured" / args[0]), *args[1:]],
        cwd=_repo_root(), capture_output=True, text=True,
    )


def test_un4_the_derived_floor_holds():
    """UN4 leg (b). `floor.py` compares the SET of MEASURED-labelled rows
    against the SET of ledger blocks. Control: `--delete-one` removes a
    block and the floor must report it missing."""
    ok = _measured("floor.py")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "missing=none extra=none" in ok.stdout, ok.stdout
    assert "totals-line MATCH" in ok.stdout, ok.stdout

    red = _measured("floor.py", "--delete-one")
    assert red.returncode != 0, red.stdout
    assert "missing=M" in red.stdout, red.stdout


def test_un4_every_measured_block_reproduces():
    """UN4 legs (a)/(c). `parse.py` RUNS every ledger block and compares the
    last line of stdout to `expect:`. This is the only thing in the suite
    that executes the helper scripts at all."""
    r = _measured("parse.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "fail=0" in r.stdout, r.stdout
    n = int(r.stdout.split("pass=")[1].split()[0])
    assert n >= 13, r.stdout


def test_un4_a_helper_with_a_missing_dependency_fails_LOUDLY(tmp_path):
    """UN4 leg (e), the property `need()` exists for: a helper whose input
    is gone must exit non-zero, never print an empty/plausible value at
    rc 0. Measured before this guard existed: `m54.sh` with `pat.txt`
    absent matched all 7 lines at rc 0 instead of 4.

    Driven against a COPY of the helper tree, so the shipped one is never
    modified."""
    # The copy must sit INSIDE the repository: `_lib.sh` resolves ROOT with
    # `git rev-parse --show-toplevel` and refuses outside it -- which is the
    # guard working, but not the one under test here. `misc/` is
    # git-excluded, so nothing tracked is touched.
    src = LF.THIS_REPO_CLI / "scripts" / "measured"
    holder = _repo_root() / "misc" / "u-land-work"
    holder.mkdir(parents=True, exist_ok=True)
    dst = holder / f"_un4_probe_{os.getpid()}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))

    baseline = subprocess.run(["bash", str(dst / "m54.sh")], cwd=_repo_root(),
                              capture_output=True, text=True)
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    assert baseline.stdout.strip().splitlines()[-1] == "4", baseline.stdout

    def run() -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(dst / "m54.sh")], cwd=_repo_root(),
                              capture_output=True, text=True)

    try:
        # (i) the input is ABSENT -- `_lib.sh`'s `need()` must refuse
        pat = dst / "pat.txt"
        saved = pat.read_bytes()
        pat.unlink()
        gone = run()
        assert gone.returncode != 0, (
            "a helper with its input removed exited 0 -- `need()` is not guarding it"
        )
        assert "FATAL" in (gone.stdout + gone.stderr), gone.stdout + gone.stderr

        # (ii) the input EXISTS but is EMPTY -- a distinct hole, and the more
        # dangerous one: an empty pattern matches EVERY line, so the helper
        # would print 7 at rc 0 instead of 4. `need()` cannot see this case
        # (the file is there), so the helper carries its own second guard.
        pat.write_bytes(b"")
        empty = run()
        assert empty.returncode != 0, (
            "a helper whose pattern file is EMPTY exited 0 -- an empty pattern "
            "matches every line, so this reports a plausible wrong number"
        )
        assert "FATAL" in (empty.stdout + empty.stderr), empty.stdout + empty.stderr

        # positive control: restored, it measures 4 again
        pat.write_bytes(saved)
        assert run().stdout.strip().splitlines()[-1] == "4"
    finally:
        shutil.rmtree(dst, ignore_errors=True)
    assert not dst.exists()


def test_un4_the_shared_need_guard_refuses_a_missing_path(tmp_path):
    """`_lib.sh`'s `need()` on its own. It has exactly ONE call site, and
    there a second guard fires first for the absent case -- so without this
    direct test, `need()` can be gutted with every suite still green.
    Measured while building: that mutation WAS invisible."""
    lib = LF.THIS_REPO_CLI / "scripts" / "measured" / "_lib.sh"
    probe = _repo_root() / "misc" / "u-land-work" / f"_need_probe_{os.getpid()}.sh"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        f'source "{lib}"\n'
        'need "$HERE/definitely-not-there.txt"\n'
        'echo "REACHED THE CODE AFTER need()"\n'
    )
    try:
        r = subprocess.run(["bash", str(probe)], cwd=_repo_root(),
                           capture_output=True, text=True)
        assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
        assert "FATAL" in r.stderr, r.stderr
        assert "REACHED THE CODE AFTER" not in r.stdout, r.stdout
        # positive control: an EXISTING path passes straight through
        probe.write_text(
            f'source "{lib}"\n'
            f'need "{lib}"\n'
            'echo "REACHED THE CODE AFTER need()"\n'
        )
        ok = subprocess.run(["bash", str(probe)], cwd=_repo_root(),
                            capture_output=True, text=True)
        assert ok.returncode == 0, (ok.stdout, ok.stderr)
        assert "REACHED THE CODE AFTER" in ok.stdout
    finally:
        probe.unlink(missing_ok=True)


def test_un4_every_helper_sources_the_shared_guard():
    """UN4 leg (e), structurally: every `.sh` helper must source `_lib.sh`,
    which is where `set -uo pipefail` and `need()` live. A helper that does
    not is one that can fail open."""
    src = LF.THIS_REPO_CLI / "scripts" / "measured"
    helpers = sorted(p for p in src.glob("*.sh") if p.name != "_lib.sh")
    assert helpers, "no helpers found -- this check would be vacuous"
    for h in helpers:
        assert "_lib.sh" in h.read_text(), h.name


# ---------------------------------------------------------------------------
# B-5 / SAN3 -- a deleted line beginning `-- ` must not spoof a file header
#
# The secret scanner gates the push on its hit COUNT. Under r5's
# `---`-then-`+++` header heuristic a deleted line whose content begins
# `-- ` supplies the first half of that pair, and the next added line
# beginning `++ ` is eaten as a header. Measured on real git output, both
# legs below: the credential is either attributed to a path that does not
# exist in the tree (so its ack key can never be verified) or dropped
# ENTIRELY -- a scanner that reports clean while a credential goes out to a
# public repository.


def _r5_added_lines(diff_text: str):
    """r5's rule, reimplemented here as the RED control, so the
    discrimination is demonstrated rather than asserted."""
    from self_learn.landing.sanitize import HUNK_RE

    out, path, ln, prev_minus = [], None, 0, False
    for l in diff_text.split("\n"):
        if l.startswith("--- "):
            prev_minus = True
            continue
        if l.startswith("+++ ") and prev_minus:
            path = l[6:] if l.startswith("+++ b/") else l[4:]
            prev_minus = False
            continue
        prev_minus = False
        m = HUNK_RE.match(l)
        if m:
            ln = int(m.group(1))
            continue
        if l.startswith("\\"):
            continue
        if l.startswith("+"):
            out.append((path, ln, l[1:]))
            ln += 1
    return out


def _spoof_repo(tmp_path: Path, head_first_line: str, head_third_line: str):
    from self_learn.landing import sanitize as SAN

    repo = tmp_path / "r"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    LF.git(repo, "config", "user.email", "t@example.invalid")
    LF.git(repo, "config", "user.name", "T")
    # line 1's content begins "-- ", so its DELETION is wired as "--- x"
    (repo / "f.md").write_text("-- x\nkeep\nplaceholder\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "base")
    base = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "f.md").write_text(f"{head_first_line}\nkeep\n{head_third_line}\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "head")
    rng = f"{base}..HEAD"
    raw = subprocess.run(["git", "diff", "--unified=0", "--no-renames", rng],
                         cwd=repo, capture_output=True, text=True, check=True).stdout
    return repo, rng, raw, SAN


def test_san3_a_deleted_dash_line_cannot_spoof_a_file_header(tmp_path):
    """SAN3's deleted-`-- ` leg, both shapes, on real `git diff` output.

    Leg A -- the credential sits on a later added line: the shipped parser
    reports it at `f.md:3`; the r5 heuristic reports `evil-path:3`, a file
    that is not in the tree, so `SAN4`'s `(file, line, sha)` ack key is
    fabricated and can never be verified against anything.

    Leg B -- the credential is ON the spoofed line: the shipped parser
    reports `f.md:1`; the r5 heuristic reports NOTHING. That is the
    fail-open case, and the one that matters, because the runner gates the
    push on this count.
    """
    import re as _re

    cred = _re.compile(r"ghp_")

    def creds(rows):
        return sorted((f, n) for f, n, txt in rows if cred.search(txt))

    # --- leg A
    repo, rng, raw, SAN = _spoof_repo(
        tmp_path / "a", "++ b/evil-path", "SEEDED ghp_deadbeefcafe1234")
    shipped = creds(SAN.added_lines(repo, rng))
    mutant = creds(_r5_added_lines(raw))
    assert shipped == [("f.md", 3)], shipped
    assert mutant == [("evil-path", 3)], mutant
    assert shipped != mutant
    # the fabricated path is not in the tree -- that is why it matters
    assert not (repo / "evil-path").exists()

    # --- leg B: the credential is DROPPED
    repo2, rng2, raw2, SAN2 = _spoof_repo(
        tmp_path / "b", "++ b/evil-path ghp_deadbeefcafe1234", "placeholder")
    shipped2 = creds(SAN2.added_lines(repo2, rng2))
    mutant2 = creds(_r5_added_lines(raw2))
    assert shipped2 == [("f.md", 1)], shipped2
    assert mutant2 == [], mutant2

    # and the full gate, not just the parser: the seeded credential must be
    # an UNACKED hit, so the runner would refuse
    hits = SAN2.hits(repo2, rng2, LF.LANDING_PKG / "sanitize_fragments.txt")
    assert any(cred.search(t) for _, _, t in hits), hits


def test_san3_the_shipped_gate_refuses_the_seeded_credential(tmp_path):
    """The end of the chain: a seeded credential reaches `--check` as an
    UNACKED hit and the CLI exits non-zero. Positive control: acking that
    exact (file, line, sha) lets it through, so the refusal is content-
    bound and not a blanket."""
    from self_learn.landing import sanitize as SAN

    frags = LF.LANDING_PKG / "sanitize_fragments.txt"
    repo, rng, raw, _ = _spoof_repo(
        tmp_path, "++ b/evil-path ghp_deadbeefcafe1234", "placeholder")
    hits = [h for h in SAN.hits(repo, rng, frags) if "ghp_" in h[2]]
    assert len(hits) == 1, hits
    f, n, text = hits[0]
    assert (f, n) == ("f.md", 1)

    rc = SAN.main(["--root", str(repo), "--range", rng, "--check",
                   "--fragments", str(frags)])
    assert rc != 0

    ack = f"{f}:{n}:{SAN.line_sha(text)}=seeded by this test"
    rc_ok = SAN.main(["--root", str(repo), "--range", rng, "--check",
                      "--fragments", str(frags), "--sanitize-ack", ack])
    assert rc_ok == 0


# ---------------------------------------------------------------------------
# M-1 / CHK3 -- the baseline is load-bearing, measured end to end


def test_chk3_the_baseline_is_load_bearing_on_a_disordered_master(tmp_path):
    """CHK3 (gate r1 M-1). Dropping `--base HEAD` left 139/139 green,
    because no fixture had PRE-EXISTING disorder on master -- the state the
    real repository is in, and the state that made the strict form refuse
    every landing.

    This fixture's master carries disorder; the branch adds none. The
    landing must SUCCEED. Red control, measured in the same test: the
    baseline-free form of the very same check refuses this tree.
    """
    from self_learn.landing.checks import (
        CheckFailure, check_row_order, check_row_order_or_raise,
    )

    repo = LF.make_repo(tmp_path, with_ui=True, fw_disorder=True)
    fw_rel = "docs/specs/self-learn/14-forward-work-map.md"
    d03_rel = "docs/specs/self-learn/03-decisions.md"

    # the fixture really is disordered, or this proves nothing
    pre = check_row_order((repo / fw_rel).read_text(), "FW")
    assert len(pre) >= 2, pre

    # red control: the strict form refuses this tree
    with pytest.raises(CheckFailure):
        check_row_order_or_raise(repo, None)
    # and the baseline form does not
    base = {rel: (repo / rel).read_text() for rel in (fw_rel, d03_rel)}
    check_row_order_or_raise(repo, base)

    LF.make_branch(
        repo, "u-clean",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-clean", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())
    assert "baseline" in (logs / "chk3.log").read_text(), (logs / "chk3.log").read_text()

    # and disorder the branch ADDS is still refused, on the same tree
    repo2 = LF.make_repo(tmp_path / "b", with_ui=True, fw_disorder=True)
    LF.make_branch(
        repo2, "u-more",
        edits={fw_rel: (repo2 / fw_rel).read_text() + "| FW-2 | added out of order | WATCH | n |\n"},
    )
    r2 = LF.run_land(repo2, tmp_path / "b", "--branch", "u-more", "--verdict", "v", timeout=180)
    assert r2.returncode == 4, r2.stdout + r2.stderr
    assert "CHK3" in r2.stderr


# ---------------------------------------------------------------------------
# B-2 -- the input audit, as a test


def _docs_lane_repo(tmp_path: Path, name: str, mutate) -> tuple[Path, Path]:
    """A fixture whose MASTER carries the (possibly broken) docs-lane input,
    and whose branch changes ONLY a docs path -- so the landing genuinely
    takes the docs lane and the input under test is the thing that decides."""
    repo = LF.make_repo(tmp_path / name, with_ui=True)
    mutate(repo)
    LF.git(repo, "add", "-A")
    if LF.git(repo, "status", "--porcelain").stdout.strip():
        LF.git(repo, "commit", "-q", "-m", f"master state for {name}")
    # pushed, so `origin/master..HEAD` covers ONLY the branch's docs change --
    # otherwise the master-side edit is itself a non-docs path in the range
    # and the landing takes the full lane, testing nothing about the input
    LF.git(repo, "push", "-q", "origin", "master")
    LF.make_branch(repo, f"u-{name}", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    return repo, tmp_path / name


def _origin_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "--git-dir", str(repo.parent / "origin.git"), "rev-parse", "master"],
        capture_output=True, text=True, check=True).stdout.strip()


def test_b2_every_declared_input_is_fail_closed(tmp_path):
    """B-2. Every input the runner reads goes through a fail-closed reader,
    and an absent / empty / unresolvable one is FATAL -- never "nothing to
    check". Driven end to end against `doc_reading_set.txt`, the one that
    shipped broken: deleted or emptied it produced an empty argument list, a
    bare root `pytest`, rc 0, and a PUSH.

    Each leg asserts the ORIGIN did not move, because "it refused" and "it
    pushed and then refused" are not the same outcome.
    """
    DOC_SET = "plugins/self-learn/cli/src/self_learn/landing/doc_reading_set.txt"

    # (a) absent
    repo, tp = _docs_lane_repo(tmp_path, "gone", lambda r: (r / DOC_SET).unlink())
    before = _origin_head(repo)
    r = LF.run_land(repo, tp, "--branch", "u-gone", "--verdict", "v", timeout=180)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "ABSENT" in r.stderr, r.stderr
    assert "pushed:" not in r.stdout
    assert _origin_head(repo) == before

    # (b) present but with no usable line
    repo2, tp2 = _docs_lane_repo(
        tmp_path, "empty",
        lambda r: (r / DOC_SET).write_text("# every line a comment\n\n"))
    before2 = _origin_head(repo2)
    r2 = LF.run_land(repo2, tp2, "--branch", "u-empty", "--verdict", "v", timeout=180)
    assert r2.returncode == 5, r2.stdout + r2.stderr
    assert "NO usable lines" in r2.stderr, r2.stderr
    assert _origin_head(repo2) == before2

    # (c) an entry naming a file that is not there
    repo3, tp3 = _docs_lane_repo(
        tmp_path, "ghost",
        lambda r: (r / DOC_SET).write_text(
            "plugins/self-learn/cli/tests/test_alpha.py\n"
            "plugins/self-learn/cli/tests/test_never_existed.py\n"))
    before3 = _origin_head(repo3)
    r3 = LF.run_land(repo3, tp3, "--branch", "u-ghost", "--verdict", "v", timeout=180)
    assert r3.returncode == 5, r3.stdout + r3.stderr
    assert "ABSENT" in r3.stderr, r3.stderr
    assert _origin_head(repo3) == before3

    # positive control -- the UNTOUCHED input takes the docs lane and PASSES,
    # so the three refusals are about the input and not about the lane
    repo4, tp4 = _docs_lane_repo(tmp_path, "ok", lambda r: None)
    before4 = _origin_head(repo4)
    ok = LF.run_land(repo4, tp4, "--branch", "u-ok", "--verdict", "v", timeout=180)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "docs lane over 1 module(s)" in ok.stdout, ok.stdout
    assert _origin_head(repo4) != before4, "the control did not actually push"


def test_b2_an_empty_sanitize_pattern_set_is_fatal(tmp_path):
    """B-2, the other file the gate reads. An empty fragment file compiles
    to the empty regex, which matches at position 0 of EVERY line -- so the
    scanner would refuse every landing while looking like it found hits.
    Fatal instead, with a message that names the cause."""
    from self_learn.landing import sanitize as SAN

    frags = tmp_path / "frag.txt"
    frags.write_text("# nothing but a comment\n\n")
    with pytest.raises(ValueError, match="EMPTY"):
        SAN.assemble_pattern(frags, "/nowhere")
    # positive control: the shipped file assembles, and to more than nothing
    real = SAN.assemble_pattern(LF.LANDING_PKG / "sanitize_fragments.txt", "/nowhere")
    assert real.search("ghp_deadbeefcafe")
    assert not real.search("an ordinary sentence")


def test_b2_the_audit_covers_every_input_the_script_reads():
    """The audit itself, kept honest.

    Gate r2: the previous version's docstring claimed more than it
    checked -- it looked only at `$GITROOT/...` paths ending `.txt`, so a
    `.json` input or an unguarded suite working directory both left it
    green. The guard is WIDENED rather than the claim narrowed:

      (a) every `$GITROOT/`- or `$gr/`-rooted path literal WITH A FILE
          EXTENSION, whatever the extension;
      (b) every directory handed to `run_suite` as its working directory;
      (c) every executable the script runs from the target tree.

    Each must be reached by one of the three fail-closed readers, either
    on the spot or through the variable it is bound to.

    Two positive controls, constructed live: an unguarded `.json` input
    and an unguarded suite cwd are both reported.
    """
    text = LF.LAND.read_text()
    code = [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
    body = "\n".join(code)

    GUARDS = ("need_file", "need_nonempty_file", "need_dir")
    assert all(g in body for g in GUARDS), body[:200]

    def declared_inputs(lines: list[str]) -> set[str]:
        joined = "\n".join(lines)
        # (a) any extension, not just .txt
        paths = set(re.findall(r'\$(?:GITROOT|gr)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+', joined))
        # (b) the second argument of every run_suite call
        paths |= {m.group(1) for m in
                  re.finditer(r'run_suite\s+\S+\s+"([^"]+)"', joined)}
        return paths

    # `run_suite` guards its own second argument, so a path handed to it is
    # reached even though the guard names `$dir` rather than the literal.
    funcs = _shell_functions("\n".join(code))
    assert "need_dir" in funcs.get("run_suite", ""), (
        "run_suite no longer guards its working directory, so passing a path "
        "to it can no longer be treated as guarded"
    )

    def unguarded(lines: list[str]) -> list[str]:
        joined = "\n".join(lines)
        run_suite_args = {m.group(1) for m in
                          re.finditer(r'run_suite\s+\S+\s+"([^"]+)"', joined)}
        out = []
        for expr in sorted(declared_inputs(lines)):
            users = [ln for ln in lines if expr in ln]
            if not users:
                continue
            if expr in run_suite_args:
                continue          # guarded inside run_suite, asserted above
            # bindings may be lowercase and `local`
            names = {m.group(1) for m in
                     (re.match(r'\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)=', ln)
                      for ln in users) if m}
            def guards(ln: str) -> bool:
                # one of the three readers, or an explicit existence test
                return (any(g in ln for g in GUARDS)
                        or re.search(r'\[\s*!?\s*-[fdre]\s+"\$', ln) is not None)
            reached = any(guards(ln) for ln in users) or any(
                guards(ln) and any(f'${n}' in ln or f'${{{n}}}' in ln for n in names)
                for ln in lines
            )
            if not reached:
                out.append(expr)
        return out

    found = declared_inputs(code)
    assert len(found) >= 4, sorted(found)
    assert unguarded(code) == [], unguarded(code)

    # --- control 1: a `.json` input, which the old `.txt`-only form missed
    probe_json = code + ['  CFG="$GITROOT/plugins/self-learn/cli/src/self_learn/landing/x.json"',
                         '  cat "$CFG"']
    assert unguarded(probe_json), "a .json input is still invisible to this guard"

    # --- control 2: a directory used WITHOUT going through `run_suite`.
    # A path handed TO run_suite is genuinely guarded (its body calls
    # need_dir, asserted above), so the hole is a suite run some other way.
    probe_dir = code + [
        '  OTHER="$GITROOT/plugins/self-learn/other.d"',
        '  ( cd "$OTHER" && env true )',
    ]
    assert unguarded(probe_dir), "a directory used outside run_suite is invisible"


#: The path this unit ADDS, and nothing else does. It is how the landing
#: that brought this unit in is found in history -- see `_unit_diff_frame`.
_UNIT_MARKER_PATH = "plugins/self-learn/cli/scripts/land"


def _unit_diff_frame(root: Path) -> tuple[list[str], str]:
    """(git-diff range arguments, state) for "this unit's own diff".

    Gate r5 BLOCKER-1: `git merge-base master HEAD` is the right base while
    BUILDING and a degenerate one once LANDED -- the moment the merge
    commit is on master, the merge-base IS `HEAD`, so both the measurement
    and its positive control compare a tree against itself, return `""`,
    and the control fires. Measured end to end: the CLI suite went
    `1 failed, 3033 passed`, `land` refused at exit 5, and it stayed red
    permanently. The control was telling the truth; the BASE was the
    defect.

    `test_armor.py` solved the same shape with a hand-pinned
    `_LANDING_BASE`/`_LANDING_TIP` pair (`_landing_is_absorbed`, and the
    post-landing commit `dfa2a24` that wrote the numbers). That works, but
    the pin can only be written AFTER the landing exists, so the criterion
    is red in the window between them -- which is exactly the window that
    would block this unit's own bootstrap.

    So the pair is DERIVED instead of pinned. The commit that ADDED
    `scripts/land` on first-parent history is:

      * while building -- the branch commit that created it, so the frame
        is the build base against the working tree (an uncommitted edit to
        the suite runner is exactly what this criterion forbids, and the
        code gate reads the tree);
      * once landed -- the MERGE that brought the unit in, because
        first-parent history attributes the addition to the merge. Its
        `^1` is master's pre-merge tip, so `^1..merge` is precisely "what
        this landing brought in", and it is fixed forever.

    Verified in a simulated landing (see the test below): post-merge it
    resolves to the merge commit, yields `suite` empty and `land`
    non-empty, and stays put after further commits on master.
    """
    add = subprocess.run(
        ["git", "log", "--first-parent", "--diff-filter=A", "--format=%H",
         "--", _UNIT_MARKER_PATH],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.split()
    if add:
        tip = add[-1]                      # the EARLIEST such commit
        parents = subprocess.run(
            ["git", "log", "-1", "--format=%P", tip], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout.split()
        if len(parents) >= 2:
            return [f"{parents[0]}", tip], "landed"
    base = subprocess.run(
        ["git", "merge-base", "master", "HEAD"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return [base], "building"


def test_un1_this_unit_does_not_change_the_suite_runner():
    """UN1. Gate r1 M-3: the old test asserted `"uv sync" in text`, so
    rewriting the whole file left it green. The property is BYTE identity
    across this unit's own diff, so that is what is measured -- with a
    positive control, because an empty diff is also what a broken diff
    command returns.

    Gate r5 BLOCKER-1: the FRAME that diff is taken in now survives this
    unit's own landing. See `_unit_diff_frame`.
    """
    root = _repo_root()
    rng, state = _unit_diff_frame(root)
    assert state in ("building", "landed"), state

    def numstat(rel: str) -> str:
        return subprocess.run(
            ["git", "diff", "--numstat", *rng, "--", rel],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.strip()

    # NIT-5: the two states differ in WHAT is compared, and a reader should
    # meet that here rather than infer it. While BUILDING the range is one
    # ref, so git diffs it against the WORKING TREE and an uncommitted edit
    # to the suite runner is caught. Once LANDED it is two commits, so the
    # working tree is no longer in the comparison at all -- correctly, since
    # after landing "this unit's diff" is a fixed piece of history.
    assert (len(rng) == 1) == (state == "building"), (state, rng)

    target = "plugins/self-learn/cli/scripts/suite"
    assert (root / target).is_file()
    assert numstat(target) == "", (state, rng, numstat(target))

    # positive control: the SAME command over a file this unit definitely
    # changed must be non-empty, so "unchanged" cannot be "looked at
    # nothing". This is the assertion that exposed BLOCKER-1; it is not
    # weakened, it is given a frame in which it can still speak.
    assert numstat(_UNIT_MARKER_PATH) != "", (
        f"UN1's instrument reported no diff for a file this unit wrote "
        f"(state={state}, range={rng}) -- the frame has collapsed"
    )


def test_un1_the_frame_survives_this_units_own_landing(tmp_path):
    """BLOCKER-1's regression guard, itself rebuilt for gate r6's BLOCKER-1.

    The first version cloned and ran `git checkout -B u-land origin/u-land`
    -- and `land`'s own Step-6 prune DELETES that branch after a successful
    push, so a clone of post-landing master has no such ref. Measured by
    rehearsing a landing to a real push and running master's suite:
    `1 failed, 3040 passed`, cause `rc 128`, with
    `prune.log: "Deleted branch u-land"`. The blocker was RELOCATED, not
    fixed -- from the measurement to its guard -- and invisible to the
    landing, because the suite runs BEFORE the prune.

    The ruling is the one that produced the derived pair: **depend on
    history, not on a ref**. The merge is in first-parent history forever;
    the branch is deleted by design, by this very tool. So:

      * if the unit has ALREADY landed, verify the frame in place -- there
        is nothing to simulate and no ref to want;
      * if it has not, simulate by merging the unit's tip **by sha**, never
        by branch name.

    Either way the guard then deletes every `u-land` ref it can see and
    re-resolves, which is the state the prune actually leaves behind.
    """
    root = _repo_root()
    rng_here, state_here = _unit_diff_frame(root)

    if state_here == "landed":
        work = root
        note = "already landed; verified in place"
    else:
        unit_tip = LF.git(root, "rev-parse", "HEAD").stdout.strip()
        work = tmp_path / "clone"
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(root), str(work)],
                       check=True, capture_output=True)
        LF.git(work, "config", "user.email", "t@example.invalid")
        LF.git(work, "config", "user.name", "T")
        LF.git(work, "checkout", "-q", "-B", "master", "origin/master")
        # by SHA -- a branch name is what this unit's own success destroys
        LF.git(work, "merge", "-q", "--no-ff", "-m",
               "Merge branch 'u-land' (simulated)", unit_tip)
        note = "simulated by sha"

    # the OLD base is degenerate here -- this is r5's BLOCKER-1 itself
    old_base = LF.git(work, "merge-base", "master", "HEAD").stdout.strip()
    assert old_base == LF.git(work, "rev-parse", "HEAD").stdout.strip(), (
        f"the landed state was not reproduced ({note})"
    )
    assert LF.git(work, "diff", "--numstat", old_base, "--",
                  _UNIT_MARKER_PATH).stdout.strip() == "", (
        "the old frame is no longer degenerate; this guard is void")

    # POST-PRUNE: remove every u-land ref, which is what Step 6 does
    for ref in ("u-land", "origin/u-land"):
        LF.git(work, "branch", "-D", ref, check=False)
        LF.git(work, "branch", "-rD", ref, check=False)
    refs = LF.git(work, "for-each-ref", "--format=%(refname)").stdout
    assert "u-land" not in refs, refs

    rng, state = _unit_diff_frame(work)
    assert state == "landed", (state, rng, note)
    assert len(rng) == 2, rng

    def numstat(rel: str) -> str:
        return LF.git(work, "diff", "--numstat", *rng, "--", rel).stdout.strip()

    assert numstat("plugins/self-learn/cli/scripts/suite") == "", numstat(
        "plugins/self-learn/cli/scripts/suite")
    assert numstat(_UNIT_MARKER_PATH) != "", (rng, "the control cannot speak after landing")

    # and it stays put once master moves on
    (work / "later_probe.txt").write_text("x\n")
    LF.git(work, "add", "--", "later_probe.txt")
    LF.git(work, "commit", "-q", "-m", "a later unrelated commit")
    rng2, state2 = _unit_diff_frame(work)
    assert (rng2, state2) == (rng, state), (rng2, rng)
    if work is root:
        LF.git(root, "reset", "-q", "--soft", "HEAD~1")
        (root / "later_probe.txt").unlink(missing_ok=True)


def test_un1_the_guard_depends_on_no_branch_ref():
    """The regression in its own terms. `land` deletes the branch after a
    successful push, so anything a guard needs from `origin/<branch>` is
    something this unit's success destroys -- and no landing can catch it,
    because the suite runs BEFORE the prune.

    Source-level, because the failure is structural: neither UN1 nor its
    guard may name a branch ref.
    """
    src = (LF.THIS_REPO_CLI / "tests" / "test_land_runner.py").read_text()
    fns = ("_unit_diff_frame",
           "test_un1_this_unit_does_not_change_the_suite_runner",
           "test_un1_the_frame_survives_this_units_own_landing")

    # The forbidden thing is naming a REMOTE-TRACKING branch of this unit --
    # the ref the prune destroys. A commit MESSAGE mentioning the branch is
    # prose, and `branch -D u-land` is the guard deliberately removing it,
    # so the rule is about the tracking ref specifically.
    import ast as _ast

    def refs_used_as_revisions(body: str) -> list[str]:
        """Every branch-shaped string handed to a git subcommand that
        RESOLVES a revision. Docstring prose about the old form, and the
        guard's own `branch -D`, are not that -- the defect was using the
        ref as a source to check out or merge."""
        RESOLVING = {"checkout", "merge", "rev-parse", "rev-list", "merge-base"}
        out = []
        for node in _ast.walk(_ast.parse(body)):
            if not isinstance(node, _ast.Call):
                continue
            args = [a.value for a in node.args
                    if isinstance(a, _ast.Constant) and isinstance(a.value, str)]
            if not (RESOLVING & set(args)):
                continue
            # a commit MESSAGE is not a revision -- skip whatever follows -m
            skip = {i + 1 for i, a in enumerate(args) if a in ("-m", "--message")}
            out += [a for i, a in enumerate(args)
                    if "u-land" in a and i not in skip]
        return out

    for fn in fns:
        body = _python_function_source(src, fn)
        assert body, fn
        assert refs_used_as_revisions(body) == [], (fn, refs_used_as_revisions(body))

    # positive control: the form that WAS shipped is detected
    assert refs_used_as_revisions(
        'def f():\n    LF.git(clone, "checkout", "-q", "-B", "u-land", "origin/u-land")\n'
    ) == ["u-land", "origin/u-land"]

    # ... and the simulation merges a SHA, held in a variable, not a name
    sim = _python_function_source(src, "test_un1_the_frame_survives_this_units_own_landing")
    assert 'unit_tip = LF.git(root, "rev-parse", "HEAD")' in sim
    assert '"merge", "-q", "--no-ff", "-m",' in sim
    assert "unit_tip)" in sim



    # and the prune that motivates it is really there, in the shipped runner
    land = LF.LAND.read_text()
    assert 'branch -d "$BRANCH"' in land
    assert "prune.log" in land


def _python_function_source(src: str, name: str) -> str:
    import ast as _ast

    for node in _ast.parse(src).body:
        if isinstance(node, _ast.FunctionDef) and node.name == name:
            return _ast.get_source_segment(src, node) or ""
    return ""


# ---------------------------------------------------------------------------
# The detector for the CLASS this round is about: an `[A]` criterion with no
# test at all. Three were found that way across two gate rounds (SUI7, SUI8,
# then SUI4 and UN4), each time by a human walking the table. This walks it.


def _spec_criteria() -> list[tuple[str, str]]:
    spec = (_spec_docs() / "drafts/u-land-landing-runner-spec.md").read_text()
    section = spec[spec.index("## 5. "):spec.index("## 6. Mutation plan")]
    # the kind cell is sometimes bolded (`**[A]**`) -- measured: RES7 is, and
    # a regex that missed it silently under-counted the table by one
    return re.findall(
        r"^\| \*\*([A-Z]+\d+[a-z]?)\*\* \| \*{0,2}\[(A|B)\]", section, re.M)


def _all_test_source() -> str:
    d = LF.THIS_REPO_CLI / "tests"
    return "".join(
        (d / n).read_text() for n in (
            "test_land_runner.py", "test_landing_checks.py",
            "test_landing_resolvers.py", "test_landing_fixture.py",
        )
    )


#: UN5's registry: every `[A]` criterion -> the test FUNCTIONS that cover
#: it. Gate r2 MAJOR-3: the previous form was a substring search over the
#: test files' TEXT, so deleting CHK7's only test left it green -- a group
#: HEADING still named CHK7. A comment cannot satisfy this one: each name
#: is resolved to a real function object on a real module.
CRITERION_TESTS: dict[str, tuple[str, ...]] = {
    "PRE1": (
        "test_pre1_predicate_is_the_absolute_compare_not_the_dot_git_string",
        "test_pre1_refuses_when_not_run_from_main_checkout",
    ),
    "PRE2": (
        "test_pre2_positive_control_on_master_proceeds",
        "test_pre2_refuses_off_master",
    ),
    "PRE3": (
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
        "test_pre3_refuses_dirty_master",
    ),
    "PRE4": (
        "test_pre4_refuses_dirty_branch_worktree",
    ),
    "PRE5": (
        "test_pre5_refuses_master_as_branch",
        "test_pre5_refuses_missing_branch",
        "test_pre5_refuses_unrelated_history",
    ),
    "PRE6": (
        "test_pre6_refuses_unreachable_origin",
    ),
    "PRE7": (
        "test_pre7_no_merge_abort_call_anywhere_in_the_precondition_block",
    ),
    "PRE8": (
        "test_pre8_refuses_when_its_own_fetch_moves_origin_master",
    ),
    "PRV1": (
        "test_prv1_refuses_resolver_without_conflict",
        "test_prv4_a_conflict_refusal_restores_masters_tree",
    ),
    "PRV2": (
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
        "test_prv2_refuses_unmapped_conflict_and_suggests",
        "test_prv2_two_conflicts_names_only_the_unmapped_one",
        "test_prv4_a_conflict_refusal_restores_masters_tree",
    ),
    "PRV3": (
        "test_blocks_no_base_marker_raises",
        "test_prv3_the_runner_supplies_diff3_itself_observed_end_to_end",
        "test_prv4_a_conflict_refusal_restores_masters_tree",
    ),
    "PRV4": (
        "test_prv4_a_conflict_refusal_restores_masters_tree",
    ),
    "RES1": (
        "test_res1_keep_both_purely_additive",
        "test_res1_keep_both_refuses_nonempty_base",
        "test_res1_keep_both_refuses_overlap",
    ),
    "RES2": (
        "test_res2_per_key_executed_duplicate_key_case_now_refuses",
        "test_res2_per_key_refuses_both_changed_no_rederive",
        "test_res2_per_key_refuses_differing_key_sets",
        "test_res2_per_key_refuses_line_with_no_colon",
        "test_res2_per_key_side_differing_from_base_wins",
    ),
    "RES3": (
        "test_res3_numeric_rows_refuses_duplicate",
        "test_res3_numeric_rows_refuses_non_row_line",
        "test_res3_numeric_rows_unions_and_sorts",
    ),
    "RES4": (
        "test_res4_candidates_for_empty_base_suggests_keep_both",
        "test_res4_candidates_for_key_value_suggests_per_key",
        "test_res4_candidates_for_unrecognisable_block_suggests_nothing",
        "test_res4_registry_matches_expected_names",
        "test_res4_unknown_resolver_name_refuses_at_cli_not_a_silent_keep_both",
    ),
    "RES5": (
        "test_res5_rederive_refuses_trivial_reason",
        "test_res5_rederive_refuses_without_date",
        "test_res5_rederive_writes_sha_of_merged_bytes",
    ),
    "RES6": (
        "test_blocks_no_base_marker_raises",
        "test_res6_every_test_function_here_reaches_a_git_merge",
        "test_res6_positive_control_hand_written_markers_would_be_caught",
    ),
    "RES7": (
        "test_res7_count_line_arithmetic",
        "test_res7_count_line_refuses_multiline_side",
        "test_res7_count_line_refuses_name_mismatch",
        "test_res7_count_line_refuses_negative_result",
    ),
    "CHK1": (
        "test_chk1_finds_markers_outside_the_hardcoded_three_docs",
        "test_chk1_finds_markers_outside_the_hardcoded_three_docs_e2e",
        "test_chk1_floor_zero_scanned_is_a_refusal_not_a_pass",
        "test_chk1_positive_control_clean_files_pass",
        "test_chk4_floor_end_to_end_a_missing_named_doc_refuses",
        "test_dry_run_still_runs_the_landing_checks",
    ),
    "CHK2": (
        "test_chk2_positive_control_matching_pins_pass",
        "test_chk2_refuses_on_mismatch",
        "test_chk2_refuses_pin_mismatch",
        "test_chk2_refuses_when_zero_pins_checked_gate_m6",
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
        "test_wld1_detection_reads_the_POST_merge_tree_observed_through_the_runner",
    ),
    "CHK3": (
        "test_chk3_a_new_row_file_stays_strict",
        "test_chk3_an_absent_baseline_file_does_not_void_the_others",
        "test_chk3_duplicate_leg_red_green_on_real_history",
        "test_chk3_passes_on_the_real_repository_with_its_own_baseline",
        "test_chk3_positive_control_monotonic_passes",
        "test_chk3_real_history_duplicate_fw130_is_a_genuine_red_green_pair",
        "test_chk3_refuses_a_duplicate_row_a_merge_introduces",
        "test_chk3_refuses_row_disorder",
        "test_chk3_refuses_within_one_contiguous_run",
        "test_chk3_separate_tables_do_not_collide",
        "test_chk3_still_refuses_disorder_a_merge_introduces",
        "test_chk3_the_baseline_is_load_bearing_on_a_disordered_master",
    ),
    "CHK4": (
        "test_chk4_finds_a_live_hit",
        "test_chk4_floor_end_to_end_a_missing_named_doc_refuses",
        "test_chk4_positive_control_clean_docs_pass",
        "test_chk4_quoted_pattern_table_is_exempt",
        "test_chk4_refuses_landing_state_prose",
    ),
    "CHK5": (
        "test_chk5_dry_run_judges_the_dry_run_worktree_not_the_main_checkout",
        "test_chk5_invokes_the_real_shipped_personal_literals_test_not_a_private_grep",
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
    ),
    "CHK6": (
        "test_chk6_158_chars_is_within_budget",
        "test_chk6_positive_control_normal_verdict_passes",
        "test_chk6_refuses_empty",
        "test_chk6_refuses_empty_verdict",
        "test_chk6_refuses_newline",
        "test_chk6_refuses_over_budget",
    ),
    "CHK7": (
        "test_chk_refusal_leaves_masters_head_exactly_where_it_was",
    ),
    "CHK8": (
        "test_arm5_is_a_post_commit_property_and_the_runner_never_runs_it_early",
        "test_chk8_nothing_test_shaped_runs_between_the_armor_step_and_the_commit",
        "test_chk8_the_instrument_resolves_calls_transitively",
        "test_wld2_remeasure_advances_the_anchor_inside_the_merge_commit",
    ),
    "SUI1": (
        "test_sui1_refuses_red_suite",
    ),
    "SUI2": (
        "test_sui2_timeout_case_is_a_distinct_branch_not_the_generic_red_message",
    ),
    "SUI3": (
        "test_sui3_extra_failure_beyond_the_allowlist_still_refuses",
        "test_sui3_known_failure_allowlist_tolerates_exactly_that_id",
    ),
    "SUI4": (
        "test_sui4_a_bogus_allowlist_entry_makes_a_landing_refuse",
        "test_sui4_and_sui8c_collection_error_refuses_distinctly_not_via_allowlist",
        "test_sui4_known_failures_all_resolve",
        "test_sui4_the_allowlist_is_readable_in_the_frame_the_suite_runs_from",
    ),
    "SUI5": (
        "test_sui5_each_suite_rc_is_captured_unpiped_and_adjudicated_separately",
        "test_sui5_each_suite_gets_its_own_rc_file_observed_through_the_runner",
    ),
    "SUI6": (
        "test_sui6_docs_plus_py_takes_full_lane",
        "test_sui6_non_py_non_docs_file_takes_full_lane",
        "test_sui6_rename_into_docs_without_no_renames_takes_full_lane",
    ),
    "SUI7": (
        "test_doc_reading_set",
    ),
    "SUI9": (
        "test_sui9_a_suite_that_could_not_run_refuses_instead_of_passing",
        "test_sui9_an_empty_collection_is_not_green",
        "test_sui9_the_empty_case_never_returns_success",
        "test_sui9_writes_a_distinguishable_verdict_per_outcome",
    ),
    "SUI10": (
        "test_minor3_a_suite_that_silently_skipped_is_not_green",
        "test_minor3_the_ceiling_clears_the_real_skip_counts",
    ),
    "SUI8": (
        "test_sui4_and_sui8c_collection_error_refuses_distinctly_not_via_allowlist",
        "test_sui8_ui_suite_collection_root",
    ),
    "SAN1": (
        "test_san1_no_home_literal_and_the_prefix_comes_from_the_environment",
    ),
    "SAN2": (
        "test_san2_positive_control_clean_diff_proceeds",
        "test_san2_seeded_hit_refuses",
    ),
    "SAN3": (
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
        "test_san3_a_deleted_dash_line_cannot_spoof_a_file_header",
        "test_san3_modifying_a_file_does_not_rescan_its_unchanged_lines",
        "test_san3_the_shipped_gate_refuses_the_seeded_credential",
        "test_san_collision_line_that_looks_like_a_header_is_still_content",
    ),
    "SAN4": (
        "test_san3_a_deleted_dash_line_cannot_spoof_a_file_header",
        "test_san4_ack_lets_a_verified_hit_through",
    ),
    "SAN5": (
        "test_san5_pattern_is_read_from_the_given_fragments_file_not_hardcoded",
        "test_san_fragment_file_scores_zero_self_hits",
    ),
    "PSH1": (
        "test_psh1_and_psh2_push_once_and_print_a_real_before_after_pair",
    ),
    "PSH2": (
        "test_psh1_and_psh2_push_once_and_print_a_real_before_after_pair",
    ),
    "PSH3": (
        "test_psh3_no_force_capability_in_the_shipped_script",
        "test_psh4_never_force_deletes_the_branch",
    ),
    "PSH4": (
        "test_psh4_never_force_deletes_the_branch",
        "test_psh4_no_worktree_still_prunes_cleanly",
        "test_psh4_prunes_worktree_and_branch_after_push",
    ),
    "DRY1": (
        "test_dry1_and_dry3_dry_run_touches_nothing_and_never_pushes",
    ),
    "DRY2": (
        "test_chk5_dry_run_judges_the_dry_run_worktree_not_the_main_checkout",
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
        "test_dry_run_still_runs_the_landing_checks",
    ),
    "DRY3": (
        "test_dry1_and_dry3_dry_run_touches_nothing_and_never_pushes",
    ),
    "WLD1": (
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
        "test_wld1_detect_world_reads_the_two_worlds_apart",
        "test_wld1_detection_reads_the_POST_merge_tree_observed_through_the_runner",
        "test_wld1_refuses_when_both_or_neither_mechanism_is_present",
    ),
    "WLD2": (
        "test_dry2_refusals_match_the_real_run_over_every_named_case",
        "test_minor2_every_in_merge_refusal_aborts_or_announces",
        "test_wld2_noop_anchor_refusal_aborts_the_chain",
        "test_wld2_owed_refusal_aborts_the_chain_and_commits_nothing",
        "test_wld2_remeasure_advances_the_anchor_inside_the_merge_commit",
    ),
    "EXC1": (
        "test_exc1_a_git_add_that_stages_nothing_is_caught_by_a_count",
        "test_exc1_every_refusal_family_exits_its_own_code",
        "test_exc1_every_stage_boundary_is_explicitly_gated",
        "test_exc1_no_die_is_reachable_from_a_command_substitution",
        "test_exc1_shell_contract",
    ),
    "CNT1": (
        "test_cnt1_bare_rerun_after_commit_refusal_refuses",
        "test_cnt1_no_state_file_control_proceeds_normally",
        "test_cnt1_state_check_failure_refuses_rather_than_assuming_clean",
    ),
    "CNT2": (
        "test_cnt2_continue_resumes_and_lands",
        "test_cnt2_fourth_precondition_rejects_an_amended_merge",
    ),
    "UN1": (
        "test_un1_this_unit_does_not_change_the_suite_runner",
        "test_un1_the_frame_survives_this_units_own_landing",
        "test_un1_the_guard_depends_on_no_branch_ref",
    ),
    "UN2": (
        "test_un2_never_touches_the_ledger",
    ),
    "UN5": (
        "test_every_a_criterion_is_named_by_a_test",
    ),
    "UN6": (
        "test_the_unit_leaves_masters_suite_green_after_the_prune",
    ),
    "UN4": (
        "test_un4_a_helper_with_a_missing_dependency_fails_LOUDLY",
        "test_un4_every_helper_sources_the_shared_guard",
        "test_un4_every_measured_block_reproduces",
        "test_un4_the_derived_floor_holds",
        "test_un4_the_shared_need_guard_refuses_a_missing_path",
    ),
    "DOC1": (
        "test_s56_matches_the_runner",
    ),
    "DOC2": (
        "test_fw_rows_added_and_ordered",
    ),
    "DOC3": (
        "test_runbook_names_the_runner",
    ),
}


_TEST_MODULES = (
    "test_land_runner", "test_landing_checks",
    "test_landing_resolvers", "test_landing_fixture",
)


def _resolve_test(name: str):
    """The test FUNCTION of that name, from whichever test module defines
    it, or None. Resolution is by attribute lookup on an imported module --
    never by searching text -- which is the whole of MAJOR-3's fix.

    It must also be something PYTEST WOULD COLLECT (gate r3): a registry
    entry repointed at an ordinary helper used to stay green, latent only
    because every name in the registry happens to start `test_`. Collection
    is decided the way pytest decides it -- the default `python_functions`
    prefix -- and a non-collectable object resolves to None."""
    import importlib
    import inspect

    for mod_name in _TEST_MODULES:
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, name, None)
        if fn is None:
            continue
        if not inspect.isfunction(fn):
            return None
        if not fn.__name__.startswith("test"):
            return None          # pytest's python_functions default
        if getattr(fn, "__module__", None) not in _TEST_MODULES:
            return None          # imported from elsewhere, not collected here
        return fn
    return None


def test_every_a_criterion_is_named_by_a_test():
    """UN5. Every `[A]` criterion maps to at least one test FUNCTION that
    exists, is callable, and is collected as a test.

    Gate r2 MAJOR-3: the previous form searched the test files' TEXT for
    the criterion id, so deleting CHK7's only test left it GREEN -- the
    group heading `# CHK7 ...` still contained the string. A criterion
    could be "covered" by a comment.

    Four controls, all constructed live:
      (a) a fabricated criterion id is reported missing;
      (b) a fabricated test NAME does not resolve;
      (c) a criterion whose id appears only in a COMMENT is not satisfied,
          which is the exact defect this replaces;
      (d) resolution really is by object -- the returned value is the
          function pytest itself would run.
    """
    rows = _spec_criteria()
    assert len(rows) >= 55, len(rows)
    a_ids = [i for i, kind in rows if kind == "A"]
    assert len(a_ids) >= 55, len(a_ids)

    # (1) every [A] criterion has at least one registered test
    unregistered = [i for i in a_ids if not CRITERION_TESTS.get(i)]
    assert not unregistered, f"[A] criteria with no registered test: {unregistered}"

    # (2) the registry may not rot in the other direction either
    stale_ids = sorted(set(CRITERION_TESTS) - set(a_ids))
    assert not stale_ids, f"registry names criteria that are not [A]: {stale_ids}"

    # (3) every registered name resolves to a real, callable test function
    unresolved = []
    for cid, names in CRITERION_TESTS.items():
        for nm in names:
            fn = _resolve_test(nm)
            if fn is None or not callable(fn) or getattr(fn, "__name__", None) != nm:
                unresolved.append((cid, nm))
    assert not unresolved, f"registered tests that do not resolve: {unresolved}"

    # --- (a) a fabricated criterion id
    probe_id = "Q" + "ZX" + "97"
    assert probe_id not in CRITERION_TESTS
    assert not CRITERION_TESTS.get(probe_id)

    # --- (b) a fabricated test name
    assert _resolve_test("test_" + "definitely_not_a_real_" + "function") is None

    # --- (b2) a real MODULE-LEVEL HELPER that pytest would never collect.
    # This is gate r3's finding: repointing an entry at one of these used to
    # stay green. Chosen from this module's own helpers, so the control
    # cannot rot into naming something that does not exist.
    assert callable(_repo_root)
    assert _resolve_test("_repo_root") is None
    assert _resolve_test("_shell_functions") is None

    # --- (c) THE defect this replaces: a comment naming a criterion does
    #         not make it covered, because a comment is not a function
    commentish = "# CHK7 -- a group heading that names the criterion\n"
    assert "CHK7" in commentish
    assert _resolve_test("CHK7") is None

    # --- (d) resolution is by object: this very test resolves to itself
    assert _resolve_test("test_every_a_criterion_is_named_by_a_test") is \
        test_every_a_criterion_is_named_by_a_test



# ---------------------------------------------------------------------------
# The four criteria the detector found unnamed


def test_sui5_each_suite_rc_is_captured_unpiped_and_adjudicated_separately():
    """SUI5. `-e` and rc-capture are mutually exclusive (gate B-1 of the
    spec round): each suite's rc is taken by redirect, written to its own
    `.rc` file, and adjudicated by a SEPARATE statement -- never read
    downstream of a pipe, where it would be the pipe's status.

    Derived from the shipped text: the capture line, the write line, and
    the adjudication must be three distinct statements, and no `.rc` value
    may be produced through a pipe.
    """
    text = LF.LAND.read_text()
    funcs = _shell_functions(text)
    body = funcs["run_suite"]

    # the invocation is a redirect, and the rc is taken on the NEXT line
    lines = [ln.strip() for ln in body.split("\n")
             if ln.strip() and not ln.strip().startswith("#")]
    redirect = next(i for i, ln in enumerate(lines) if ln.startswith("( cd "))

    # PROPERTIES, not positions. The body legitimately gained the
    # porcelain snapshots (MIN-3), and a positional assertion turned that
    # into a false failure -- the same brittleness CHK8's file-position
    # slice had.
    assert '>"$OUT/$name.log" 2>&1' in lines[redirect], lines[redirect]
    assert "|" not in lines[redirect].split(">")[0], lines[redirect]

    # the rc is taken on the very next line, before anything can clobber $?
    assert lines[redirect + 1] == "local rc=$?", lines[redirect + 1]
    # ... and written to its own file, from the VARIABLE, so later commands
    # cannot change what is recorded
    assert any('printf \'%s\\n\' "$rc" >"$OUT/$name.rc"' in ln for ln in lines), lines

    # and `run_suite` returns 0 deliberately -- the rc is DATA, never an abort
    assert lines[-1] == "return 0", lines[-1]

    # the adjudication is a separate function reading the file back
    adj = funcs["adjudicate_suite"]
    assert 'rc=$(cat "$OUT/$n.rc"' in adj
    assert "case \"$rc\" in" in adj

    # nothing anywhere pipes into an rc read
    for ln in text.split("\n"):
        if "rc=$?" in ln:
            assert "|" not in ln, ln


def test_sui5_each_suite_gets_its_own_rc_file_observed_through_the_runner(tmp_path):
    """SUI5, observed end to end rather than only in the script's shape:
    a full-lane landing must leave a SEPARATE `.rc` file per suite, each
    carrying that suite's own exit code, and the adjudication must read
    them back. A single shared file would let one suite's verdict stand in
    for the other's."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-rc",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-rc", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())

    rcs = sorted(p.name for p in logs.glob("*.rc"))
    assert rcs == ["cli.rc", "ui.rc"], rcs
    for name in rcs:
        assert (logs / name).read_text().strip() == "0", name
    # each suite also recorded the cwd it ran from -- the pairing B-1 needs
    cwds = sorted(p.name for p in logs.glob("*.cwd"))
    assert cwds == ["cli.cwd", "ui.cwd"], cwds
    assert (logs / "ui.cwd").read_text().strip().endswith("plugins/self-learn/ui")
    assert not (logs / "cli.cwd").read_text().strip().endswith("plugins/self-learn/ui")


def test_san1_no_home_literal_and_the_prefix_comes_from_the_environment():
    """SAN1. The shipped runner and the landing package contain NO absolute
    home path, and the home prefix is substituted from `$HOME` at read
    time via the `%HOME%` placeholder.

    Positive control: the assembled pattern is shown to MATCH a path built
    from the current `$HOME`, so "no literal" cannot mean "no coverage"."""
    from self_learn.landing import sanitize as SAN

    home = os.environ.get("HOME", "")
    assert home and home != "/", home

    files = [LF.LAND] + sorted(LF.LANDING_PKG.glob("*.py")) + \
        sorted(LF.LANDING_PKG.glob("*.txt"))
    for f in files:
        assert home not in f.read_text(), f"absolute home path in {f.name}"

    # the placeholder is what carries it instead
    frag = (LF.LANDING_PKG / "sanitize_fragments.txt").read_text()
    assert "%HOME%" in frag

    # positive control: assembled with a home value, the pattern matches a
    # path under it, and the placeholder itself is gone
    pat = SAN.assemble_pattern(LF.LANDING_PKG / "sanitize_fragments.txt", home)
    assert pat.search(f"{home}/repos/self-learn/x.py")
    assert "%HOME%" not in pat.pattern
    # and with a DIFFERENT home it does not
    other = SAN.assemble_pattern(LF.LANDING_PKG / "sanitize_fragments.txt", "/opt/elsewhere")
    assert not other.search(f"{home}/repos/self-learn/x.py") or home.startswith("/opt/elsewhere")


def test_psh1_and_psh2_push_once_and_print_a_real_before_after_pair(tmp_path):
    """PSH1/PSH2. On success the runner pushes `origin master` exactly once
    and prints `old..new`, where both ends are read from `origin/master`
    around the push -- a REAL pair, not a formatted guess.

    Legs: the printed `old` equals the origin's head BEFORE the run and the
    printed `new` equals it AFTER; and the pair genuinely moved."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    origin = tmp_path / "origin.git"

    def origin_head() -> str:
        return subprocess.run(["git", "--git-dir", str(origin), "rev-parse", "master"],
                              capture_output=True, text=True, check=True).stdout.strip()

    before = origin_head()
    LF.make_branch(
        repo, "u-push",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-push", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    after = origin_head()

    line = [ln for ln in r.stdout.split("\n") if ln.startswith("pushed: ")]
    assert len(line) == 1, r.stdout
    old_printed, _, new_printed = line[0][len("pushed: "):].partition("..")
    assert old_printed == before, (old_printed, before)
    assert new_printed == after, (new_printed, after)
    assert before != after, "the control did not actually move origin"

    # PSH1: exactly one push invocation in the shipped script
    text = LF.LAND.read_text()
    pushes = [ln for ln in text.split("\n")
              if "push origin master" in ln and not ln.lstrip().startswith("#")]
    assert len(pushes) == 1, pushes
    assert "|" not in pushes[0], pushes[0]
    assert 'PUSH_RC=$?' in text


# ---------------------------------------------------------------------------
# The FLOOR AUDIT, as an executable table (gate r2 MAJOR-5)
#
# One rule: every check that can return an empty result must distinguish
# "I looked and found nothing" from "I could not look". Two instances of
# that shape shipped in this unit in one round (CHK1 got a floor, CHK4 did
# not), which is why the audit is a table here rather than prose in a
# handoff: a new check that cannot tell the two apart fails this.


def test_floor_audit_every_emptiable_check_refuses_when_it_could_not_look(tmp_path):
    """Each row: a check, an input on which it CANNOT look, and the refusal
    it must produce. Every row is executed; a row that passes silently is
    itself a failure, because the point is that the empty case is loud."""
    from self_learn.landing import checks as CH
    from self_learn.landing import sanitize as SAN
    from self_learn.landing import suites as SU

    root = tmp_path / "r"
    (root / "docs/specs/self-learn/drafts").mkdir(parents=True)
    (root / "plugins/self-learn/cli/tests").mkdir(parents=True)

    # --- CHK1: an unreadable path in the merge-touched set
    d = root / "a-directory-not-a-file"
    d.mkdir()
    with pytest.raises(CH.CheckFailure, match="could not read"):
        CH.check_no_markers([d])
    # and the clean case reports WHAT IT SCANNED
    good = root / "clean.md"
    good.write_text("nothing here\n")
    assert CH.check_no_markers([good]) == 1
    # a DELETED merge-touched path is legitimately absent, not unreadable
    assert CH.check_no_markers([root / "was-deleted.md"]) == 0

    # --- CHK4: a NAMED landing-state doc that is absent
    with pytest.raises(CH.CheckFailure, match="ABSENT"):
        CH.check_prose_or_raise(root)
    for rel in CH.DEFAULT_DOCS:
        (root / rel).write_text("ordinary prose\n")
    assert CH.check_prose_or_raise(root) >= 3
    # ... and zero documents read is refused even with none named missing
    with pytest.raises(CH.CheckFailure, match="read 0 documents"):
        CH.check_prose_or_raise(root, docs=[])

    # --- CHK3: a row file with no rows at all
    fw = root / "docs/specs/self-learn/14-forward-work-map.md"
    d03 = root / "docs/specs/self-learn/03-decisions.md"
    fw.write_text("# forward work\n\nno rows here\n")
    d03.write_text("# decisions\n\nno rows here\n")
    with pytest.raises(CH.CheckFailure, match="ZERO"):
        CH.check_row_order_or_raise(root, None)
    # ... and an absent row file is its own refusal
    fw.unlink()
    with pytest.raises(CH.CheckFailure, match="ABSENT"):
        CH.check_row_order_or_raise(root, None)

    # --- SAN: an empty pattern set, and an empty scan
    frag = root / "frag.txt"
    frag.write_text("# only a comment\n")
    with pytest.raises(ValueError, match="EMPTY"):
        SAN.assemble_pattern(frag, "/nowhere")

    # --- SUI3/SUI9: a log with nothing to adjudicate
    allow = root / "allow.txt"
    allow.write_text("plugins/self-learn/cli/tests/test_x.py::test_y\n")
    assert SU.adjudicate("", root, root, allow)[0] == SU.VERDICT_UNPARSEABLE
    assert SU.adjudicate("x\n", root, root, root / "gone.txt")[0] == SU.VERDICT_NO_ALLOWLIST

    # --- CHK2: zero pins
    (root / "plugins/self-learn/cli/tests/test_worker_contract.py").write_text(
        '"""no pins here"""\n'
    )
    with pytest.raises(CH.CheckFailure, match="N < 1"):
        CH.check_pins_or_raise(root)


def test_chk1_floor_zero_scanned_is_a_refusal_not_a_pass(tmp_path):
    """CHK1's floor at the CLI seam, which is what `land` actually calls:
    an EMPTY path list must refuse, not print 'no conflict markers'.
    That is M97's oracle -- the spec row existed with no mutation behind
    it until this round."""
    from self_learn.landing import checks as CH

    root = tmp_path / "r"
    root.mkdir()
    # given NOTHING to scan
    assert CH.main(["--root", str(root), "markers"]) == 1

    # a path that exists but cannot be READ is fatal too
    (root / "adir").mkdir()
    assert CH.main(["--root", str(root), "markers", "adir"]) == 1

    # but a DELETED merge-touched path is not a hole -- a delete-only merge
    # legitimately scans zero files, and refusing that is a false refusal
    assert CH.main(["--root", str(root), "markers", "was-deleted.md"]) == 0

    # positive control: one real file scanned prints the count and passes
    f = root / "f.md"
    f.write_text("ordinary\n")
    assert CH.main(["--root", str(root), "markers", "f.md"]) == 0


def test_chk4_floor_end_to_end_a_missing_named_doc_refuses(tmp_path):
    """CHK4's floor through the RUNNER. Before this round a tree missing
    every named landing-state doc produced `[]` and the CLI printed 'no
    landing-state prose' -- the identical shape CHK1 was given a floor for
    in the same round."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    LF.git(repo, "checkout", "-q", "-b", "u-nodoc")
    LF.git(repo, "rm", "-q", "docs/specs/self-learn/13-hosting-and-separation.md")
    LF.git(repo, "commit", "-q", "-m", "delete a named landing-state doc")
    LF.git(repo, "checkout", "-q", "master")
    r = LF.run_land(repo, tmp_path, "--branch", "u-nodoc", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "CHK4" in r.stderr, r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_cnt1_state_check_failure_refuses_rather_than_assuming_clean(tmp_path):
    """CNT1's guard used to discard the state check's rc: if the module
    failed, its output was empty, the `[ "$IN_STATE" = "yes" ]` test did
    not fire, and the guard silently not running looked exactly like the
    guard passing.

    Driven by making the state module unrunnable for the duration."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-state",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    env = LF.env_for(tmp_path)
    # a PYTHONPATH entry that shadows the landing package with a broken
    # module makes `python3 -m self_learn.landing.state` fail loudly
    shadow = tmp_path / "shadow"
    (shadow / "self_learn" / "landing").mkdir(parents=True)
    (shadow / "self_learn" / "__init__.py").write_text("")
    (shadow / "self_learn" / "landing" / "__init__.py").write_text("")
    (shadow / "self_learn" / "landing" / "state.py").write_text("raise SystemExit(9)\n")
    env["PYTHONPATH"] = str(shadow)
    r = subprocess.run(
        [str(LF.LAND), "--branch", "u-state", "--verdict", "v"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "CNT1: the landing-state check" in r.stderr, r.stderr

    # positive control: without the shadow, the same landing proceeds
    ok = LF.run_land(repo, tmp_path, "--branch", "u-state", "--verdict", "v", timeout=180)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_san_floor_zero_scanned_added_lines_refuses(tmp_path):
    """The sanitize gate's own floor: 'sanitize OK' over a range with no
    added lines is not a result. The push is gated on this verdict."""
    from self_learn.landing import sanitize as SAN

    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    LF.git(repo, "config", "user.email", "t@example.invalid")
    LF.git(repo, "config", "user.name", "T")
    (repo / "f.md").write_text("one line\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "base")
    frags = LF.LANDING_PKG / "sanitize_fragments.txt"

    # an EMPTY range: nothing added between a commit and itself
    rc = SAN.main(["--root", str(repo), "--range", "HEAD..HEAD", "--check",
                   "--fragments", str(frags)])
    assert rc == 1

    # positive control: a range WITH added lines and no hits passes, and
    # says how many lines that verdict is about
    (repo / "f.md").write_text("one line\ntwo line\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "add")
    assert SAN.main(["--root", str(repo), "--range", "HEAD~1..HEAD", "--check",
                     "--fragments", str(frags)]) == 0


# ---------------------------------------------------------------------------
# The helper-not-runner shape (gate r2's five Majors)
#
# A criterion about WHEN or IN WHAT ORDER the runner does something cannot
# be verified by calling the helper in isolation. WLD1's six tests all
# exercised `detect_world()` on hand-built trees; none observed when `land`
# actually calls it, so moving the call PRE-merge left the full suite green.
#
# The fixture below makes the two answers DIFFER. Master is the pre-U-armor
# world (pins, no test_armor.py); the branch is U-armor's own shape --
# it DELETES the pins and ADDS test_armor.py. So:
#
#   detection on master's tree      -> "armor_shas"  -> CHK2 -> 0 pins -> refuse
#   detection on the merged tree    -> "remeasure"   -> the anchor advances
#
# and the landing's OUTCOME reports which tree was read.


def _divergent_world_repo(tmp_path: Path) -> Path:
    """Master: pins, no test_armor.py. Branch: no pins, test_armor.py.
    The world differs pre- and post-merge, which is what makes WLD1's
    'POST-merge' clause observable from outside."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="shas")
    cli = repo / "plugins/self-learn/cli"
    # The watched file must exist AT THE ANCHOR -- the anchor is master's
    # pre-merge tip, and a census of a file that is not there at that rev is
    # an error, not a clean read. So it lands on master first.
    (cli / "tests" / "test_watched.py").write_text(LF._FIXTURE_WATCHED)
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "the watched behaviour file")
    LF.git(repo, "push", "-q", "origin", "master")

    LF.git(repo, "checkout", "-q", "-b", "u-armorworld")
    (cli / "tests" / "test_worker_contract.py").write_text(
        '"""_ARMOR_SHAS retired by U-armor; the census lives in test_armor.py."""\n'
    )
    (cli / "tests" / "test_armor.py").write_text(
        LF._FIXTURE_ARMOR.replace("@@ANCHOR@@", "0000000")
    )
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "retire the pins, add the census")
    LF.git(repo, "checkout", "-q", "master")
    return repo


def test_wld1_detection_reads_the_POST_merge_tree_observed_through_the_runner(tmp_path):
    """WLD1, observed end to end rather than by calling the helper.

    Red control FIRST, measured on this very fixture: the two trees give
    DIFFERENT answers, so the criterion is discriminable here. Then the
    landing is run, and the artefacts say which tree was read -- a
    `remeasure.log` means the merged tree, a `chk2.log` means master's.
    """
    from self_learn.landing.checks import (
        WORLD_ARMOR_SHAS, WORLD_REMEASURE, detect_world,
    )

    repo = _divergent_world_repo(tmp_path)

    # the discriminating precondition, measured
    assert detect_world(repo) == WORLD_ARMOR_SHAS          # master's tree
    LF.git(repo, "checkout", "-q", "u-armorworld")
    assert detect_world(repo) == WORLD_REMEASURE           # the branch's
    LF.git(repo, "checkout", "-q", "master")

    r = LF.run_land(repo, tmp_path, "--branch", "u-armorworld", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())
    assert (logs / "remeasure.log").exists(), sorted(p.name for p in logs.iterdir())
    assert not (logs / "chk2.log").exists(), "took the pins branch -- detection read master's tree"
    assert "ANCHOR 0000000 ->" in (logs / "remeasure.log").read_text()


def test_wld1_refuses_when_both_or_neither_mechanism_is_present(tmp_path):
    """WLD1's other two cells, also through the runner: exactly one
    mechanism must be present. Both -> refuse; neither -> refuse. The
    `0:0` cell is the one that matters, since a pre-merge detector would
    pick `armor_shas` and then find zero pins."""
    # BOTH
    both = LF.make_repo(tmp_path / "both", with_ui=True, armor="shas")
    cli = both / "plugins/self-learn/cli"
    LF.git(both, "checkout", "-q", "-b", "u-both")
    (cli / "tests" / "test_watched.py").write_text(LF._FIXTURE_WATCHED)
    (cli / "tests" / "test_armor.py").write_text(
        LF._FIXTURE_ARMOR.replace("@@ANCHOR@@", "0000000"))
    LF.git(both, "add", "-A")
    LF.git(both, "commit", "-q", "-m", "add the census WITHOUT retiring the pins")
    LF.git(both, "checkout", "-q", "master")
    rb = LF.run_land(both, tmp_path / "both", "--branch", "u-both", "--verdict", "v", timeout=180)
    assert rb.returncode == 4, rb.stdout + rb.stderr
    assert "BOTH armor mechanisms" in rb.stderr, rb.stderr

    # NEITHER
    none = LF.make_repo(tmp_path / "none", with_ui=True, armor="shas")
    LF.git(none, "checkout", "-q", "-b", "u-none")
    (none / "plugins/self-learn/cli/tests/test_worker_contract.py").write_text(
        '"""no pins, and no census either"""\n')
    LF.git(none, "add", "-A")
    LF.git(none, "commit", "-q", "-m", "retire the pins with nothing to replace them")
    LF.git(none, "checkout", "-q", "master")
    rn = LF.run_land(none, tmp_path / "none", "--branch", "u-none", "--verdict", "v", timeout=180)
    assert rn.returncode == 4, rn.stdout + rn.stderr
    assert "NEITHER armor mechanism" in rn.stderr, rn.stderr


def test_prv3_the_runner_supplies_diff3_itself_observed_end_to_end(tmp_path):
    """PRV3, three legs, through the runner.

    (a) the confound control: the fixture's repo-local
        `merge.conflictStyle` is asserted UNSET, so a pass cannot come
        from the fixture's own configuration;
    (b) the landing runs with `GIT_CONFIG_GLOBAL`/`SYSTEM` neutralised --
        this machine sets `merge.conflictStyle=diff3` globally, and
        without that isolation the runner could drop its own `-c` and
        still see base markers;
    (c) the conflicted file really did carry a `|||||||` base section
        during the merge, which is what the resolver needs.
    """
    repo = LF.make_repo(tmp_path, with_ui=True)
    fw = "docs/specs/self-learn/14-forward-work-map.md"

    # (a) confound control
    got = LF.git(repo, "config", "--local", "--get", "merge.conflictStyle", check=False)
    assert got.returncode != 0, f"the fixture sets merge.conflictStyle locally: {got.stdout!r}"

    LF.git(repo, "checkout", "-q", "-b", "u-conflict")
    (repo / fw).write_text((repo / fw).read_text() + "| FW-3 | branch | WATCH | n |\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "branch row")
    LF.git(repo, "checkout", "-q", "master")
    (repo / fw).write_text((repo / fw).read_text() + "| FW-4 | master | WATCH | n |\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "master row")

    # (c) what the merge itself produces under the runner's own -c, with the
    # operator's config neutralised exactly as `land` runs it
    import os as _os
    probe_env = dict(_os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    subprocess.run(["git", "-C", str(repo), "-c", "merge.conflictStyle=diff3",
                    "merge", "--no-ff", "--no-commit", "u-conflict"],
                   capture_output=True, text=True, env=probe_env)
    with_c = (repo / fw).read_text()
    subprocess.run(["git", "-C", str(repo), "merge", "--abort"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "--no-commit", "u-conflict"],
                   capture_output=True, text=True, env=probe_env)
    without_c = (repo / fw).read_text()
    subprocess.run(["git", "-C", str(repo), "merge", "--abort"], capture_output=True)
    assert "|||||||" in with_c, with_c[:400]
    assert "|||||||" not in without_c, (
        "the fixture produced base markers WITHOUT the runner's -c, so this "
        "test cannot tell whether the runner supplies it"
    )

    # (b) and the real landing, which needs those markers to resolve
    r = LF.run_land(repo, tmp_path, "--branch", "u-conflict", "--verdict", "v",
                    "--resolver", f"{fw}=numeric-rows", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    text = (repo / fw).read_text()
    assert "FW-3" in text and "FW-4" in text and "<<<<<<<" not in text


def test_prv4_a_conflict_refusal_restores_masters_tree(tmp_path):
    """PRV4. Every conflict refusal must leave master's tree restored --
    `git merge --abort` ran, porcelain 0, HEAD unmoved. Driven on PRV1,
    PRV2 and PRV3's refusal paths, because a refusal that leaves a
    half-merged tree is worse than the conflict."""
    fw = "docs/specs/self-learn/14-forward-work-map.md"

    def state(repo: Path) -> tuple[str, str]:
        return (LF.git(repo, "rev-parse", "HEAD").stdout.strip(),
                LF.git(repo, "status", "--porcelain").stdout.strip())

    # PRV1: --resolver given but the preview is clean
    a = LF.make_repo(tmp_path / "prv1", with_ui=True)
    LF.make_branch(a, "u-clean", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    before = state(a)
    ra = LF.run_land(a, tmp_path / "prv1", "--branch", "u-clean", "--verdict", "v",
                     "--resolver", f"{fw}=numeric-rows", timeout=180)
    assert ra.returncode == 3, ra.stdout + ra.stderr
    assert state(a) == before, (state(a), before)

    # PRV2: a conflicted path with no --resolver mapping
    b = LF.make_repo(tmp_path / "prv2", with_ui=True)
    LF.git(b, "checkout", "-q", "-b", "u-conf")
    (b / fw).write_text((b / fw).read_text() + "| FW-3 | branch | WATCH | n |\n")
    LF.git(b, "add", "-A"); LF.git(b, "commit", "-q", "-m", "branch")
    LF.git(b, "checkout", "-q", "master")
    (b / fw).write_text((b / fw).read_text() + "| FW-4 | master | WATCH | n |\n")
    LF.git(b, "add", "-A"); LF.git(b, "commit", "-q", "-m", "master")
    before_b = state(b)
    rb = LF.run_land(b, tmp_path / "prv2", "--branch", "u-conf", "--verdict", "v", timeout=180)
    assert rb.returncode == 3, rb.stdout + rb.stderr
    assert state(b) == before_b, (state(b), before_b)
    assert "PRV2" in rb.stderr


def test_dry1_and_dry3_dry_run_touches_nothing_and_never_pushes(tmp_path):
    """DRY1/DRY3. After `--dry-run`: master's sha, the porcelain output and
    the `git worktree list` line count are all identical to pre-run, the
    origin has not moved, and the run says `DRY RUN`."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-dry",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )

    def snapshot():
        return (
            LF.git(repo, "rev-parse", "master").stdout.strip(),
            LF.git(repo, "status", "--porcelain").stdout,
            len(LF.git(repo, "worktree", "list").stdout.strip().split("\n")),
            subprocess.run(["git", "--git-dir", str(tmp_path / "origin.git"),
                            "rev-parse", "master"], capture_output=True,
                           text=True, check=True).stdout.strip(),
        )

    before = snapshot()
    r = LF.run_land(repo, tmp_path, "--branch", "u-dry", "--verdict", "v",
                    "--dry-run", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY RUN" in r.stdout and "nothing pushed" in r.stdout
    assert "pushed:" not in r.stdout
    assert snapshot() == before, (snapshot(), before)

    # positive control: the SAME landing without --dry-run does move things,
    # so "identical" above is not a statement about a run that did nothing
    ok = LF.run_land(repo, tmp_path, "--branch", "u-dry", "--verdict", "v", timeout=180)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert snapshot() != before


def test_dry2_refusals_match_the_real_run_over_every_named_case(tmp_path):
    """DRY2, parameterised over all SIX cases the spec names -- PRE3, PRV2,
    CHK2, CHK5, SAN3 and WLD1/WLD2 -- not the three that were built.

    For each: the dry run and the real run must produce the SAME exit code
    and the same refusal message, and the dry run must have judged `$TMP`
    rather than the main checkout.
    """
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    cases: list[tuple[str, Any]] = []

    def _pre3(repo: Path) -> str:
        # the dirt must be created AFTER the branch, or `make_branch`'s own
        # `git add -A` commits it and master is clean again
        LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
        (repo / "dirty.txt").write_text("uncommitted\n")
        return "u-x"

    def _prv2(repo: Path) -> str:
        LF.git(repo, "checkout", "-q", "-b", "u-x")
        (repo / fw).write_text((repo / fw).read_text() + "| FW-3 | b | WATCH | n |\n")
        LF.git(repo, "add", "-A"); LF.git(repo, "commit", "-q", "-m", "b")
        LF.git(repo, "checkout", "-q", "master")
        (repo / fw).write_text((repo / fw).read_text() + "| FW-4 | m | WATCH | n |\n")
        LF.git(repo, "add", "-A"); LF.git(repo, "commit", "-q", "-m", "m")
        return "u-x"

    def _chk2(repo: Path) -> str:
        LF.git(repo, "checkout", "-q", "-b", "u-x")
        (repo / "plugins/self-learn/cli/tests/backends.py").write_text("CHANGED\n")
        LF.git(repo, "add", "-A"); LF.git(repo, "commit", "-q", "-m", "break the pin")
        LF.git(repo, "checkout", "-q", "master")
        return "u-x"

    def _chk5(repo: Path) -> str:
        LF.make_branch(repo, "u-x", edits={"seeded_literal.txt": "a personal path\n"})
        return "u-x"

    def _san3(repo: Path) -> str:
        LF.make_branch(repo, "u-x", edits={"docs/specs/self-learn/drafts/n.md":
                                           "ghp_deadbeefcafe1234\n"})
        return "u-x"

    def _wld(repo: Path) -> str:
        LF.git(repo, "checkout", "-q", "-b", "u-x")
        (repo / "plugins/self-learn/cli/tests/test_worker_contract.py").write_text(
            '"""no pins, and no census either"""\n')
        LF.git(repo, "add", "-A"); LF.git(repo, "commit", "-q", "-m", "neither mechanism")
        LF.git(repo, "checkout", "-q", "master")
        return "u-x"

    cases = [("PRE3", _pre3), ("PRV2", _prv2), ("CHK2", _chk2),
             ("CHK5", _chk5), ("SAN3", _san3), ("WLD", _wld)]

    seen = []
    for name, build in cases:
        dry_dir = tmp_path / f"{name}-dry"
        real_dir = tmp_path / f"{name}-real"
        results = {}
        for kind, base in (("dry", dry_dir), ("real", real_dir)):
            repo = LF.make_repo(base, with_ui=True, with_literals=True)
            branch = build(repo)
            args = ["--branch", branch, "--verdict", "v"]
            if kind == "dry":
                args.append("--dry-run")
            r = LF.run_land(repo, base, *args, timeout=180)
            results[kind] = (r.returncode, r.stderr.strip())
        assert results["dry"][0] != 0, (name, results["dry"])
        assert results["dry"][0] == results["real"][0], (name, results)
        # the messages differ only in the mktemp'd log directory
        import re as _re
        norm = lambda s: _re.sub(r"/tmp/self-learn-land\.[A-Za-z0-9]+", "<OUT>",
                                 _re.sub(r"/tmp/[^ \n]*", "<PATH>", s))
        assert norm(results["dry"][1]) == norm(results["real"][1]), (name, results)
        seen.append(name)

    assert seen == ["PRE3", "PRV2", "CHK2", "CHK5", "SAN3", "WLD"], seen


def test_exc1_every_refusal_family_exits_its_own_code(tmp_path):
    """EXC1 leg 1, which was never built: each refusal family exits its OWN
    §4.10 code, end to end. Six families, six codes, all distinct -- the
    grep leg above says `-e` is absent, this one says the codes that
    replace it actually arrive.

    Exit 7 is driven by a `pre-receive` hook in the throwaway origin, so
    the push genuinely fails rather than being simulated.
    """
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    got: dict[int, str] = {}

    # 2 -- precondition (HEAD is not master)
    a = LF.make_repo(tmp_path / "c2", with_ui=True)
    LF.make_branch(a, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    LF.git(a, "checkout", "-q", "u-x")
    r = LF.run_land(a, tmp_path / "c2", "--branch", "u-x", "--verdict", "v", timeout=180)
    got[r.returncode] = "PRE2"

    # 3 -- preview/merge family (an unmapped conflicted path)
    b = LF.make_repo(tmp_path / "c3", with_ui=True)
    LF.git(b, "checkout", "-q", "-b", "u-x")
    (b / fw).write_text((b / fw).read_text() + "| FW-3 | b | WATCH | n |\n")
    LF.git(b, "add", "-A"); LF.git(b, "commit", "-q", "-m", "b")
    LF.git(b, "checkout", "-q", "master")
    (b / fw).write_text((b / fw).read_text() + "| FW-4 | m | WATCH | n |\n")
    LF.git(b, "add", "-A"); LF.git(b, "commit", "-q", "-m", "m")
    r = LF.run_land(b, tmp_path / "c3", "--branch", "u-x", "--verdict", "v", timeout=180)
    got[r.returncode] = "PRV2"

    # 4 -- landing checks (an empty verdict)
    c = LF.make_repo(tmp_path / "c4", with_ui=True)
    LF.make_branch(c, "u-x", edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    LF.git(c, "checkout", "-q", "-b", "u-y")
    (c / fw).write_text((c / fw).read_text() + "| FW-1 | out of order | WATCH | n |\n")
    LF.git(c, "add", "-A"); LF.git(c, "commit", "-q", "-m", "disorder")
    LF.git(c, "checkout", "-q", "master")
    r = LF.run_land(c, tmp_path / "c4", "--branch", "u-y", "--verdict", "v", timeout=180)
    got[r.returncode] = "CHK3"

    # 5 -- the suites
    d = LF.make_repo(tmp_path / "c5", with_ui=True)
    LF.make_branch(d, "u-x", edits={"plugins/self-learn/cli/tests/test_red.py":
                                    "def test_fails():\n    assert False\n"})
    r = LF.run_land(d, tmp_path / "c5", "--branch", "u-x", "--verdict", "v", timeout=180)
    got[r.returncode] = "SUI1"

    # 6 -- the sanitize gate
    e = LF.make_repo(tmp_path / "c6", with_ui=True)
    LF.make_branch(e, "u-x", edits={"docs/specs/self-learn/drafts/n.md":
                                    "ghp_deadbeefcafe1234\n"})
    r = LF.run_land(e, tmp_path / "c6", "--branch", "u-x", "--verdict", "v", timeout=180)
    got[r.returncode] = "SAN"

    # 7 -- the push, refused by the origin itself
    f = LF.make_repo(tmp_path / "c7", with_ui=True)
    hook = tmp_path / "c7" / "origin.git" / "hooks" / "pre-receive"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'refused by the receiving end' >&2\nexit 1\n")
    hook.chmod(0o755)
    LF.make_branch(f, "u-x", edits={"plugins/self-learn/cli/tests/test_gamma.py":
                                    "def test_g():\n    assert True\n"})
    r = LF.run_land(f, tmp_path / "c7", "--branch", "u-x", "--verdict", "v", timeout=180)
    got[r.returncode] = "PSH"

    assert sorted(got) == [2, 3, 4, 5, 6, 7], got
    assert len(set(got.values())) == 6, got


def _logical_statements(text: str) -> list[tuple[int, str, list[str]]]:
    """(line-number, joined statement, following lines). Continuation lines
    ending in a backslash are joined, so a multi-line invocation is one
    statement -- which is what "gated by `|| die`" is a property of."""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        start = i
        parts = [lines[i]]
        while parts[-1].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            parts.append(lines[i])
        out.append((start + 1, " ".join(p.rstrip().rstrip("\\").strip() for p in parts),
                    [l.strip() for l in lines[i + 1:i + 3]]))
        i += 1
    return out


def _dying_functions(funcs: dict[str, str]) -> set[str]:
    """Functions whose body can `die`, transitively. Calling one of these IS
    a gate -- `need_file`, `staged_add` and friends refuse on their own."""
    # seeded on `die` OR a bare `exit` -- `die` itself refuses via `exit`,
    # not by calling itself, so seeding on the name alone misses the root
    dying = {n for n, b in funcs.items()
             if re.search(r"(?:^|[\s;&|])(?:die |exit )", b)}
    changed = True
    while changed:
        changed = False
        for n, b in funcs.items():
            if n in dying:
                continue
            if any(re.search(r"(?:^|[\s;&|(`$])" + re.escape(d) + r"(?:\s|$|;|\))", b, re.M)
                   for d in dying):
                dying.add(n)
                changed = True
    return dying


def test_exc1_every_stage_boundary_is_explicitly_gated():
    """EXC1's second leg, WIDENED (gate r3 MAJOR-1).

    The previous form audited only bare `py_landing ` statements -- 6 of the
    script's boundaries, and zero `git`/`uv`/`timeout` ones. The gate
    de-gated `git commit` and `uv sync` and both stayed GREEN, and the claim
    the leg made was false of the shipped script: the two `git add`s were
    genuinely ungated.

    This audits EVERY statement that runs a state-mutating command,
    whatever the command. A statement is gated when it carries `|| die` or
    an explicit best-effort `|| true`, when it is the condition of an `if`,
    when its rc is captured on the next line or returned, when it is the
    last statement of a function whose rc the caller reads, or when it
    calls a helper that dies on its own behalf (derived transitively, so
    `staged_add` counts without being named here).

    Three positive controls, all constructed live and all naming boundaries
    the OLD leg could not see: `git commit`, `uv sync`, and `git add`.
    """
    text = LF.LAND.read_text()
    funcs = _shell_functions(text)
    dying = _dying_functions(funcs)
    assert {"die", "need_file", "staged_add"} <= dying, sorted(dying)

    MUTATING = re.compile(
        r"\b(?:"
        r"git\s+(?:-C\s+\S+\s+)?(?:-c\s+\S+\s+)?"
        r"(?:add|commit|merge|push|fetch|worktree\s+add|worktree\s+remove|branch\s+-d)\b"
        r"|uv\s+sync\b"
        r"|py_landing\b"
        r")"
    )

    def boundaries(lines: list[str]) -> list[tuple[int, str, list[str]]]:
        out = []
        for ln, stmt, nxt in _logical_statements("\n".join(lines)):
            s = stmt.strip()
            if s.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{", s):
                continue
            if s.startswith("done <") or s.startswith("while ") or s.startswith("for "):
                continue
            if MUTATING.search(s):
                out.append((ln, s, nxt))
        return out

    def gated(stmt: str, nxt: list[str]) -> bool:
        """A gate is a CONTROL-FLOW construct, not a string in the vicinity.

        Gate r6 MAJOR-1: this used to accept `'"$?"' in following`, which
        treats a PRINTED rc as a gate. Two probes showed how badly: de-gating
        `git commit` left this leg passing (the red came only from a control
        breaking), and a synthetic ungated `git fetch` whose rc was merely
        printf'd left the whole test green. A captured rc counts only if the
        variable is later TESTED.
        """
        s = stmt.strip()
        if "|| die" in s or "|| true" in s:
            return True
        if s.startswith("if ") or s.startswith("elif "):
            return True                     # the condition IS the gate
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=\$\(", s):
            return True                     # a capture; its value is floored
        following = nxt[0] if nxt else ""
        if following in ("return $?", "}"):
            return True
        m = re.match(r"^(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)=\$\?$", following)
        if m:
            var = m.group(1)
            # captured -- but only a gate if something later TESTS it
            tested = re.search(
                r"(?:\[\s+\"?\$\{?" + re.escape(var) + r"\}?|case\s+\"?\$\{?"
                + re.escape(var) + r"\}?|\[\s+\"\$" + re.escape(var) + r"\")",
                text)
            return bool(tested)
        called = re.findall(r"(?:^|[\s;&|(`])([A-Za-z_][A-Za-z0-9_]*)\b", s)
        return any(c in dying for c in called)

    code = [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
    found = boundaries(code)
    # the audit must be looking at a real population, not a handful
    assert len(found) >= 20, len(found)
    # and at more than one command family, which is the whole of MAJOR-1
    families = {("git" if " git " in f" {s} " or s.startswith("git ") else
                 "uv" if "uv sync" in s else "py_landing")
                for _, s, _ in found}
    assert families >= {"git", "uv", "py_landing"}, families

    ungated = [(ln, s) for ln, s, nxt in found if not gated(s, nxt)]
    assert not ungated, f"ungated stage boundaries: {ungated}"

    # --- control 1: de-gate `git commit`
    probe = [ln.replace(' || die 4 "git commit failed"', "") for ln in code]
    assert [s for _, s in
            [(l, st) for l, st, nx in boundaries(probe) if not gated(st, nx)]
            if "commit -q -m" in s], "de-gating git commit is invisible"

    # --- control 2: de-gate `uv sync`
    probe2 = [ln.replace(
        ' || die 2 "uv sync (this build\'s own CLI project) failed"', "") for ln in code]
    assert [s for _, s in
            [(l, st) for l, st, nx in boundaries(probe2) if not gated(st, nx)]
            if "uv sync" in s], "de-gating uv sync is invisible"

    # --- control 3: a bare `git add`, the shape that WAS shipped ungated
    probe3 = code + ['  git -C "$gr" add -- some/path', '  echo next']
    assert [s for _, s in
            [(l, st) for l, st, nx in boundaries(probe3) if not gated(st, nx)]
            if "add -- some/path" in s], "a bare git add is invisible"

    # --- control 4 (gate r6 MAJOR-1's own probe): an rc that is merely
    # PRINTED is not a gate. Injected where no other control splices.
    probe4 = code + ['  git -C "$ROOT" fetch origin master',
                     '  printf \'fetch rc=%s\\n\' "$?"']
    assert [s for _, s in
            [(l, st) for l, st, nx in boundaries(probe4) if not gated(st, nx)]
            if "fetch origin master" in s], "a printf'd rc still counts as a gate"

    # --- control 5: a captured rc that nothing tests is not a gate either
    probe5 = code + ['  git -C "$ROOT" fetch origin master',
                     '  unused_rc_probe=$?']
    assert [s for _, s in
            [(l, st) for l, st, nx in boundaries(probe5) if not gated(st, nx)]
            if "fetch origin master" in s], "an untested captured rc counts as a gate"


def test_exc1_a_git_add_that_stages_nothing_is_caught_by_a_count(tmp_path):
    """MAJOR-1's other half. `git add` exits 0 when it stages NOTHING, so an
    exit-code gate cannot tell "added" from "added nothing" -- which is why
    `staged_add`'s gate is a COUNT.

    Measured here rather than argued: a `git add` of a pathspec matching no
    change exits 0 and stages 0 paths.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    LF.git(repo, "config", "user.email", "t@example.invalid")
    LF.git(repo, "config", "user.name", "T")
    (repo / "f.md").write_text("one\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "base")

    # a pathspec that matches an EXISTING, UNCHANGED file
    r = LF.git(repo, "add", "--", "f.md")
    assert r.returncode == 0, r.stderr
    staged = LF.git(repo, "diff", "--cached", "--name-only", "--", "f.md").stdout.strip()
    assert staged == "", "the premise is gone: this add DID stage something"

    # the count is what tells them apart
    (repo / "f.md").write_text("one\ntwo\n")
    LF.git(repo, "add", "--", "f.md")
    staged2 = LF.git(repo, "diff", "--cached", "--name-only", "--", "f.md").stdout.strip()
    assert staged2 == "f.md"

    # and the shipped runner uses exactly that shape
    text = LF.LAND.read_text()
    assert "diff --cached --name-only" in text
    assert 'staged $n change(s)' in text
    adds = [ln for ln in text.split("\n")
            if re.search(r'git -C \S+ add --', ln) and not ln.lstrip().startswith("#")]
    assert len(adds) == 1, adds          # exactly one, inside staged_add
    assert "staged_add" in text



# ---------------------------------------------------------------------------
# The four-leg `--remeasure` refusal contract (runbook §5.1)
#
# Implemented against that PROSE, not against test_armor.py -- which is what
# the section exists for. All four legs, both parse traps, and the
# unmodelled case that must never be read as either success or a known
# refusal.


def _armor_branch(repo: Path, name: str, edit) -> None:
    """A branch that mutates the fixture's armor stand-in in place.

    It also carries ONE ordinary change, so the merge has content of its
    own. Without that, an in-merge edit that happens to revert the armor
    change leaves the merge net-empty and CHK1's floor refuses it -- true
    of the fixture, but not of any real landing, and it would make the
    resume path untestable for the wrong reason."""
    src = repo / "plugins/self-learn/cli/tests/test_armor.py"
    LF.git(repo, "checkout", "-q", "-b", name)
    src.write_text(edit(src.read_text()))
    (repo / f"plugins/self-learn/cli/tests/test_{name.replace('-', '_')}.py").write_text(
        "def test_carried():\n    assert True\n"
    )
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", f"branch {name}")
    LF.git(repo, "checkout", "-q", "master")


def test_wld2_vacuous_leg_aborts_the_chain(tmp_path):
    """`VACUOUS:` -- an exemption entry the new anchor no longer owes. A
    pre-write leg: the file is byte-unchanged and nothing is committed.

    The entry shapes deliberately include the two the contract calls traps:
    a `new_stmt_keys` entry containing a `|`, and a `missing` entry whose
    node key contains its own `:`. The runner must not split on either.
    """
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    _armor_branch(
        repo, "u-vacuous",
        lambda s: s.replace(
            'STRANDED: tuple[str, ...] = ()',
            'STRANDED: tuple[str, ...] = (\n'
            '    "repinned",\n'
            '    "missing:assign:REWRITTEN",\n'
            '    "new_stmt_keys:assign|SESSION_ID",\n'
            ')', 1),
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-vacuous", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "refused BEFORE writing" in r.stderr, r.stderr
    assert "3 VACUOUS" in r.stderr, r.stderr
    assert "file intact: yes" in r.stderr, r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before

    log = Path(r.stderr.split("cat ")[-1].strip()).read_text()
    lines = [l for l in log.split("\n") if l.startswith("VACUOUS: ")]
    assert len(lines) == 3, log

    # the contract's parse rule: split(": ", 2), never on ':' or '|'
    parsed = [l.split(": ", 2) for l in lines]
    assert all(len(p) == 3 for p in parsed), parsed
    entries = [p[2] for p in parsed]
    assert "repinned" in entries                      # bare, no suffix
    assert "missing:assign:REWRITTEN" in entries      # three colon parts
    assert "new_stmt_keys:assign|SESSION_ID" in entries  # contains a pipe
    # and the naive splits the contract warns about would both mangle it
    assert "new_stmt_keys:assign|SESSION_ID".split("|")[0] != "new_stmt_keys:assign|SESSION_ID"
    assert len("missing:assign:REWRITTEN".split(":")) == 3


def test_wld2_stale_leg_aborts_the_chain(tmp_path):
    """`STALE:` -- a transcribed MEASURED literal the new anchor
    invalidates. A three-line record whose third line pastes verbatim into
    the row's `value=`."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    _armor_branch(
        repo, "u-stale",
        lambda s: s.replace(
            "MEASURED: dict[str, str] = {}",
            "MEASURED: dict[str, str] = {'nodes': '99'}", 1),
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-stale", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "refused BEFORE writing" in r.stderr, r.stderr
    assert "1 STALE" in r.stderr, r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before

    log = Path(r.stderr.split("cat ")[-1].strip()).read_text()
    stale = [l for l in log.split("\n") if l.startswith("STALE: ")]
    assert len(stale) == 3, log        # the record is always three lines
    assert "MEASURED['nodes']" in stale[0]
    # both values are python reprs; the shipped one is the row's literal
    # verbatim, so `99` (a repr of an int), not a quoted string
    assert "shipped value: 99" in stale[1], stale[1]
    assert "value at " in stale[2]
    # the third line's value pastes straight into that row's `value=`
    pasted = stale[2].split(": ", 2)[2]
    assert pasted.isdigit(), pasted
    assert pasted != "99", "the fixture's shipped value is not actually stale"


def test_wld2_three_pre_write_legs_can_fire_together(tmp_path):
    """The contract says the three pre-write legs "can appear together in
    one run -- a landing behind a sibling unit routinely produces two or
    three at once". A runner that stopped at the first token would report
    one of three and send its operator round the loop twice more."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    def edit(s: str) -> str:
        s = s.replace('STRANDED: tuple[str, ...] = ()',
                      'STRANDED: tuple[str, ...] = ("repinned",)', 1)
        s = s.replace("MEASURED: dict[str, str] = {}",
                      "MEASURED: dict[str, str] = {'nodes': '99'}", 1)
        return s
    _armor_branch(repo, "u-all3", edit)
    # and an OWED one too: edit the watched node's body on the same branch
    LF.git(repo, "checkout", "-q", "u-all3")
    w = repo / "plugins/self-learn/cli/tests/test_watched.py"
    w.write_text(w.read_text().replace("(2 + 2) == 4", "(2 + 2) == 5 - 1", 1))
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "and an owed node")
    LF.git(repo, "checkout", "-q", "master")

    r = LF.run_land(repo, tmp_path, "--branch", "u-all3", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "1 OWED" in r.stderr and "1 VACUOUS" in r.stderr and "1 STALE" in r.stderr, r.stderr
    log = Path(r.stderr.split("cat ")[-1].strip()).read_text()
    assert any(l.startswith("OWED: ") for l in log.split("\n"))
    assert any(l.startswith("VACUOUS: ") for l in log.split("\n"))
    assert any(l.startswith("STALE: ") for l in log.split("\n"))


def test_wld2_an_unmodelled_failure_is_not_read_as_a_known_refusal(tmp_path):
    """The contract's last clause: "rc 1 with none of these -- an unmodelled
    failure; do not proceed." A runner that treated every non-zero as a
    known refusal would report the wrong cause and, worse, a runner that
    treated a non-1 rc as success would proceed on a run that modelled
    nothing."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    _armor_branch(
        repo, "u-unmodelled",
        # exits 3 with a diagnostic that carries none of the four tokens
        lambda s: s.replace(
            "    old = ANCHOR\n",
            '    old = ANCHOR\n'
            '    print("something went wrong in a way this contract does not model",\n'
            '          file=sys.stderr)\n'
            '    raise SystemExit(3)\n', 1),
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-unmodelled", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "UNMODELLED" in r.stderr, r.stderr
    assert "rc=3" in r.stderr, r.stderr
    assert "refused BEFORE writing" not in r.stderr
    assert "no-op guard" not in r.stderr
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_wld2_success_asserts_the_streams_the_contract_promises(tmp_path):
    """Success: rc 0, stdout EMPTY, stderr exactly the advance line, and the
    file actually changed. The runner asserts all four, because a success
    that talked on the wrong stream is a contract change it must not ride
    over silently."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    tip = LF.git(repo, "rev-parse", "--short=7", "HEAD").stdout.strip()
    LF.make_branch(
        repo, "u-ok",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-ok", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())
    assert (logs / "remeasure.out").read_text() == "", "stdout was not empty"
    err = (logs / "remeasure.err").read_text().strip().split("\n")
    assert len(err) == 1, err
    assert err[0] == f"ANCHOR 0000000 -> {tip}", err
    assert _armor_anchor(repo) == tip

    # and the staged-add positive control fired
    assert "staged: plugins/self-learn/cli/tests/test_armor.py (1 path)" in r.stdout, r.stdout


def test_exc1_no_die_is_reachable_from_a_command_substitution():
    """`die` runs `exit`. Inside `$( ... )` that ends only the SUBSHELL: the
    refusal prints, the script carries on, and a guard not firing looks
    exactly like a guard passing.

    This unit shipped that shape THREE times -- `allowlisted_only`'s empty
    failing set, `state_check`'s discarded rc, and `need_nonempty_file`
    called inside `$( )` -- so it gets a sweep rather than a third one-off
    fix. Any function that can reach `die` or `exit`, transitively, may not
    be called from a command substitution.

    Positive control: an injected `$(need_file ...)` is reported.
    """
    text = LF.LAND.read_text()
    funcs = _shell_functions(text)
    dying = _dying_functions(funcs)
    assert "die" in dying and "need_file" in dying, sorted(dying)

    def offenders(src: str) -> list[tuple[int, str]]:
        out = []
        for lineno, line in enumerate(src.split("\n"), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in re.finditer(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)", line):
                called = set(re.findall(r"(?:^|[\s;&|(`])([A-Za-z_][A-Za-z0-9_]*)\b",
                                        m.group(1)))
                if called & dying:
                    out.append((lineno, sorted(called & dying)[0]))
        return out

    assert offenders(text) == [], offenders(text)

    # the sweep must be able to SEE one, or its empty result means nothing
    probe = text + '\nX=$(need_file "$SOME" "probe" 2)\n'
    assert offenders(probe), "the sweep cannot see a die inside $( )"

    # and the split that fixes it is the shipped shape: a PURE reader beside
    # a dying guard, so nothing has to be called from a substitution to get
    # both a refusal and a value
    assert "usable_lines()" in text
    assert "need_nonempty_file " in text


def test_sui6_the_lane_detector_refuses_a_range_that_saw_nothing(tmp_path):
    """SUI6's detector had no floor: `grep -cv` over an empty diff yields 0,
    which selects the NARROWER docs lane. A miscount that silently runs
    FEWER tests is the worst direction for this one to fail.

    Driven through the runner with a `--continue` state whose recorded base
    equals HEAD, so the range is genuinely empty."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-lane",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-lane", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    # the detector reports what it counted, so a lane choice is never silent
    assert "lane detector --" in r.stdout, r.stdout
    m = re.search(r"lane detector -- (\d+) changed path\(s\), (\d+) outside docs/", r.stdout)
    assert m, r.stdout
    changed, nondoc = int(m.group(1)), int(m.group(2))
    assert changed >= 1 and nondoc >= 1, (changed, nondoc)

    # and the floor itself, at the seam: zero changed paths refuses
    text = LF.LAND.read_text()
    assert "changed ZERO paths" in text
    assert 'CHANGED_N" -ge 1' in text


def test_sui4_an_empty_allowlist_is_a_refusal_not_a_pass(tmp_path):
    """`verify-allowlist` returned rc 0 on an EMPTY allowlist: "0 entries,
    all fine" and "there is nothing here to check" were the same output.
    SUI4 exists to prove the ids still resolve, and it cannot prove that of
    none."""
    from self_learn.landing import suites as S

    empty = tmp_path / "empty.txt"
    empty.write_text("# only a comment\n\n")
    assert S.main(["--root", str(_repo_root()), "verify-allowlist",
                   "--allow", str(empty)]) == 1

    # positive control: the real allowlist verifies at rc 0
    real = _repo_root() / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt"
    assert S.allowlist_entries(real), "the real allowlist is empty; control is void"
    assert S.main(["--root", str(_repo_root()), "verify-allowlist",
                   "--allow", str(real)]) == 0


def test_the_shape_sweep_cannot_be_satisfied_by_a_string_literal():
    """Gate r3 demonstrated the classifier passing itself: `CHK7`'s non-NONE
    standing came partly from the literal `commentish = "# CHK7 -- a group
    heading..."` inside the UN5 meta-test -- the exact comment shape UN5 was
    rebuilt to reject.

    The coverage map now comes from the REGISTRY, which resolves to function
    objects, so no literal can enter. Asserted here by construction: the
    classifier's input is `CRITERION_TESTS`, and every name in it resolves.
    """
    # the literal that used to do it is still present, so this is not
    # passing because the evidence vanished
    text = (LF.THIS_REPO_CLI / "tests" / "test_land_runner.py").read_text()
    assert 'commentish = "# CHK7' in text

    # CHK7's standing comes from a resolvable function, not from that string
    names = CRITERION_TESTS["CHK7"]
    assert names, "CHK7 has no registered test"
    for n in names:
        assert _resolve_test(n) is not None, n
    # and none of its registered names is the meta-test that holds the literal
    assert "test_every_a_criterion_is_named_by_a_test" not in names


def test_staged_add_refuses_an_add_that_stages_nothing(tmp_path):
    """MAJOR-1's positive control, driven against the SHIPPED function.

    `git add` exits 0 when it stages nothing, so `staged_add`'s gate is a
    COUNT. The function's body is lifted out of the script and run against
    a real repository with a stub `die`, so the assertion is about the
    shipped code and not about a paraphrase of it.

    Two legs: a pathspec matching no change refuses with the count in the
    message; a real change stages exactly one path and exits 0.
    """
    body = _shell_functions(LF.LAND.read_text())["staged_add"]
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "set -uo pipefail\n"
        'die() { printf "DIE %s: %s\\n" "$1" "$2" >&2; exit "$1"; }\n'
        "staged_add() {\n" + body + "\n}\n"
        'staged_add "$1" "$2" "probe" 9\n'
    )

    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    LF.git(repo, "config", "user.email", "t@example.invalid")
    LF.git(repo, "config", "user.name", "T")
    (repo / "f.md").write_text("one\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "base")

    def run() -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(probe), str(repo), "f.md"],
                              capture_output=True, text=True,
                              env={**os.environ, "OUT": str(tmp_path)})

    # leg 1: nothing to stage. `git add` itself exits 0 -- measured -- so
    # only the count can tell this apart from a real add.
    plain = LF.git(repo, "add", "--", "f.md")
    assert plain.returncode == 0, plain.stderr
    refused = run()
    assert refused.returncode == 9, (refused.stdout, refused.stderr)
    assert "staged 0 change(s)" in refused.stderr, refused.stderr

    # leg 2: a real change stages exactly one path
    (repo / "f.md").write_text("one\ntwo\n")
    ok = run()
    assert ok.returncode == 0, (ok.stdout, ok.stderr)
    assert "staged: f.md (1 path)" in ok.stdout, ok.stdout


# ---------------------------------------------------------------------------
# MAJ-1: a refusal may not describe a state it has destroyed
#
# `land` used to run `git merge --abort` and then, eight lines later, tell
# the operator to "fix each inside this still-uncommitted merge". Measured
# on a real run: porcelain 0, no MERGE_HEAD, HEAD unmoved -- there was no
# merge to fix anything inside. It fires with certainty on the bootstrap
# (`0 OWED, 2 VACUOUS, 2 STALE`), so it was the first thing the bootstrap
# operator would read, and it was wrong.
#
# The three WLD2 tests asserted that the abort HAPPENED; none asserted that
# the sentence beside it was TRUE. That is the shape this unit has now
# fixed five times: the mechanism pinned, the claim unchecked.


def _tree_state(repo: Path) -> dict:
    """What the tree actually is, in the two terms the messages claim."""
    return {
        "merge_in_progress": (repo / ".git" / "MERGE_HEAD").exists(),
        "porcelain_lines": len(
            [l for l in LF.git(repo, "status", "--porcelain").stdout.split("\n") if l.strip()]
        ),
        "head": LF.git(repo, "rev-parse", "HEAD").stdout.strip(),
    }


def assert_message_matches_tree(stderr: str, repo: Path) -> str:
    """Every refusal that says something about the tree must be TRUE of it.

    Returns the claim it recognised, so a caller can assert WHICH claim was
    made and this cannot pass by recognising none.
    """
    left = "The merge is LEFT UNCOMMITTED" in stderr
    aborted = "The merge was ABORTED and the tree restored" in stderr
    assert left != aborted, (
        "a refusal must make exactly one claim about the tree it left; "
        f"left={left} aborted={aborted}\n{stderr}"
    )
    state = _tree_state(repo)
    if left:
        assert state["merge_in_progress"], (
            "the message says the merge is left uncommitted, but there is no "
            f"MERGE_HEAD: {state}"
        )
        assert state["porcelain_lines"] > 0, (
            f"the message says there is a merge to edit, but the tree is clean: {state}"
        )
        return "left-uncommitted"
    assert not state["merge_in_progress"], (
        f"the message says the merge was aborted, but MERGE_HEAD is present: {state}"
    )
    assert state["porcelain_lines"] == 0, (
        f"the message says the tree was restored, but it is dirty: {state}"
    )
    return "aborted"


def test_maj1_a_prewrite_refusal_really_does_leave_the_merge_to_edit(tmp_path):
    """The bootstrap's own case. `--remeasure` refuses before writing, and
    the operator is told to make the edits HERE and re-run -- so the merge
    must still be there to edit, with `test_armor.py` in it.

    Then the loop is CLOSED in the same test: the edit is made in place,
    the same landing is re-run, and it succeeds. That is the runbook §5.1
    workflow end to end, and it is only possible because the refusal
    preserved the merge."""
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    _armor_branch(
        repo, "u-strand",
        lambda s: s.replace('STRANDED: tuple[str, ...] = ()',
                            'STRANDED: tuple[str, ...] = ("repinned",)', 1),
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-strand", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr

    # the claim, checked against the tree
    assert assert_message_matches_tree(r.stderr, repo) == "left-uncommitted"
    assert "1 VACUOUS" in r.stderr
    assert "STALE record(s)" in r.stderr, r.stderr
    assert "merge --abort" in r.stderr, "the escape hatch is not offered"
    assert "--continue-merge" in r.stderr, "the message names no way to finish"
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before

    # the merged test_armor.py really is present and editable
    armor = repo / "plugins/self-learn/cli/tests/test_armor.py"
    assert armor.exists()
    assert 'STRANDED: tuple[str, ...] = ("repinned",)' in armor.read_text()

    # --- close the loop, in place, exactly as the message instructs
    armor.write_text(armor.read_text().replace(
        'STRANDED: tuple[str, ...] = ("repinned",)',
        'STRANDED: tuple[str, ...] = ()', 1))
    again = LF.run_land(repo, tmp_path, "--branch", "u-strand", "--verdict", "v",
                        "--continue-merge", timeout=180)
    assert again.returncode == 0, again.stdout + again.stderr
    # and the transcription rode INSIDE the merge commit
    committed = LF.git(repo, "show", "HEAD:plugins/self-learn/cli/tests/test_armor.py").stdout
    assert 'STRANDED: tuple[str, ...] = ()' in committed
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() != head_before


def test_maj1_the_other_two_legs_really_do_restore_the_tree(tmp_path):
    """The no-op and UNMODELLED legs give the operator nothing to edit, so
    they abort -- and they say so. Same assertion, opposite claim, so the
    checker cannot be passing by recognising only one."""
    # no-op
    a = LF.make_repo(tmp_path / "noop", with_ui=True, armor="remeasure")
    tip = LF.git(a, "rev-parse", "--short=7", "HEAD").stdout.strip()
    _armor_branch(a, "u-noop2",
                  lambda s: s.replace('ANCHOR = "0000000"', f'ANCHOR = "{tip}"', 1))
    ra = LF.run_land(a, tmp_path / "noop", "--branch", "u-noop2", "--verdict", "v", timeout=180)
    assert ra.returncode == 4, ra.stdout + ra.stderr
    assert assert_message_matches_tree(ra.stderr, a) == "aborted"

    # unmodelled
    b = LF.make_repo(tmp_path / "unmod", with_ui=True, armor="remeasure")
    _armor_branch(
        b, "u-unmod2",
        lambda s: s.replace("    old = ANCHOR\n",
                            '    old = ANCHOR\n'
                            '    print("unmodelled", file=sys.stderr)\n'
                            '    raise SystemExit(3)\n', 1),
    )
    rb = LF.run_land(b, tmp_path / "unmod", "--branch", "u-unmod2", "--verdict", "v", timeout=180)
    assert rb.returncode == 4, rb.stdout + rb.stderr
    assert assert_message_matches_tree(rb.stderr, b) == "aborted"


def test_sui3_the_fixture_stub_matches_the_shipped_suite_output_contract(tmp_path):
    """MAJ-2. Every SUI3 test drives the fixture's `scripts/suite` stub, so
    the criterion is only worth what that stub's OUTPUT CONTRACT shares
    with the shipped one.

    The shipped runner redirects pytest into its own `$OUT/suite.log` and
    prints two summary lines, the second ending `logs=<dir>`. The stub used
    to pipe pytest straight to stdout, so a red CLI suite adjudicated
    `unparseable-log` on the real path and the allowlist never applied --
    fail-closed, but proving nothing.

    Three legs: the shipped contract is asserted from the shipped file, the
    stub is asserted to match it, and the adjudicator is shown to recover
    node ids through the `logs=` pointer.
    """
    from self_learn.landing import suites as S

    # (a) the SHIPPED contract, read from the shipped file
    shipped = (LF.THIS_REPO_CLI / "scripts" / "suite").read_text()
    assert '> "$OUT/suite.log" 2>&1' in shipped
    assert "logs=%s" in shipped
    assert "printf 'suite rc=%s" in shipped

    # (b) the stub reproduces it
    repo = LF.make_repo(tmp_path, with_ui=True)
    stub = (repo / "plugins/self-learn/cli/scripts/suite").read_text()
    assert '"$OUT/suite.log" 2>&1' in stub
    assert "logs=%s" in stub
    # and it does NOT pipe pytest to stdout, which is what made it lie
    assert "pytest plugins/self-learn/cli/tests -q -p no:cacheprovider\n" not in stub

    # (c) the adjudicator recovers ids through the pointer
    logdir = tmp_path / "suitelogs"
    logdir.mkdir()
    (logdir / "suite.log").write_text(
        "FAILED plugins/self-learn/cli/tests/test_red.py::test_fails - assert False\n"
        "1 failed, 10 passed in 3.0s\n"
    )
    runner_stdout = (
        "suite rc=1  1 failed, 10 passed in 3.0s\n"
        f"suite total rc=1  3s  logs={logdir}\n"
    )
    # the runner's own captured stdout carries NO node id -- that is the
    # whole problem, and it is asserted rather than assumed
    assert S.parse_failing(runner_stdout) == []
    assert S.parse_failing(S._expand_referenced_logs(runner_stdout)) == [
        "plugins/self-learn/cli/tests/test_red.py::test_fails"
    ]

    allow = tmp_path / "allow.txt"
    allow.write_text("plugins/self-learn/cli/tests/test_red.py::test_fails\n")
    root = _repo_root()
    assert S.adjudicate(runner_stdout, root, root, allow)[0] == S.VERDICT_OK
    # ... and one that is NOT on the list still refuses
    allow.write_text("plugins/self-learn/cli/tests/test_other.py::test_x\n")
    assert S.adjudicate(runner_stdout, root, root, allow)[0] == S.VERDICT_NOT_ALLOWLISTED
    # a pointer to a directory that is not there contributes nothing, and
    # the empty-set rule then refuses rather than passing
    gone = runner_stdout.replace(str(logdir), str(tmp_path / "nope"))
    assert S.adjudicate(gone, root, root, allow)[0] == S.VERDICT_UNPARSEABLE


def test_sui3_a_red_cli_suite_is_adjudicated_by_the_allowlist_end_to_end(tmp_path):
    """The real path, through the runner: a CLI suite that fails ONLY on an
    allowlisted id must land. Before MAJ-2 this refused with
    `unparseable-log`, because the ids lived in the suite's own log and
    nothing followed the pointer."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    node_id = "plugins/self-learn/cli/tests/test_red.py::test_fails"
    (repo / "plugins/self-learn/cli/src/self_learn/landing/known_failures.txt").write_text(
        node_id + "\n")
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "allowlist the known CLI failure")
    LF.make_branch(
        repo, "u-cliallow",
        edits={"plugins/self-learn/cli/tests/test_red.py": "def test_fails():\n    assert False\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-cliallow", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())
    verdict = (logs / "cli.adjudication").read_text()
    assert verdict.startswith("allowlisted-only"), verdict
    assert node_id in verdict, verdict


def test_sui2_the_suite_budget_clears_the_measured_ui_cost(tmp_path):
    """MAJ-3. The per-suite budget must clear the SLOWER suite by a real
    margin, not by 1 %.

    The UI suite runs SERIALLY -- no xdist in the UI venv -- and an
    undivided run has failed to finish inside 580 s. Against the old 600 s
    budget that is a cliff: a machine 1 % slower turns a green suite into a
    SUI2 timeout refusal, which is a refusal that says nothing true about
    the code.

    Deliberately, this test names NO measurement of its own. The runs live
    in the script's `UI_MEASUREMENT:` rows and both the worst cost and the
    described tree size are read out of them, because the version that
    hardcoded 608 s here was stale within one round.
    """
    text = LF.LAND.read_text()
    m = re.search(r"SUITE_TIMEOUT=\$\{SUITE_TIMEOUT:-(\d+)\}", text)
    assert m, "the budget is no longer a single overridable default"
    budget = int(m.group(1))

    # Every number this test judges the budget by is DERIVED from the
    # record. The previous version hardcoded 608 as the worst observed, and
    # by the next round a 674.3 s run had been measured -- a number written
    # down twice goes stale in one place first, which is MINOR-1's shape in
    # the time dimension rather than the count one.
    rows = re.findall(
        r"UI_MEASUREMENT: (\d+) tests, ([\d.]+) s \+ ([\d.]+) s = ([\d.]+) s",
        text,
    )
    assert len(rows) >= 3, f"the record carries {len(rows)} measured runs: {rows}"
    # the SPLIT must be reproducible: each row's parts must sum to its total
    for n, p1, p2, tot in rows:
        assert abs((float(p1) + float(p2)) - float(tot)) < 0.5, (n, p1, p2, tot)
    worst = max(float(r[3]) for r in rows)
    assert budget >= 2.5 * worst, (
        f"budget {budget}s is under 2.5x the worst RECORDED run ({worst}s). "
        f"Rows: {rows}"
    )
    # MINOR-1: the record must still DESCRIBE THE TREE, not merely add up.
    # The newest row is the one that makes that claim.
    recorded = int(rows[-1][0])
    live = _collect(_repo_root() / "plugins/self-learn/ui")
    assert live.returncode == 0, live.stdout[-1000:]
    m3 = re.search(r"(\d+) tests collected", live.stdout)
    assert m3, live.stdout[-500:]
    live_n = int(m3.group(1))
    assert abs(live_n - recorded) <= 25, (
        f"the budget record's newest run describes {recorded} collected tests "
        f"but the tree now has {live_n} -- re-measure and restate before "
        f"trusting it"
    )
    assert "568" in text, (

        "the budget's justifying measurement is not recorded in the script"
    )
    # and it stays overridable, since the attended bootstrap raises it
    assert "SUITE_TIMEOUT:-" in text


def test_min3_a_suite_run_records_what_it_left_behind(tmp_path):
    """MIN-3. A killed suite can leave artefacts in the tree being landed,
    and nothing observed that -- the same 'an outcome nothing notices'
    family as everything else this unit has fixed.

    Every suite run now snapshots the porcelain either side of itself and
    records the delta, so 'the suite left the tree as it found it' is a
    measurement. Asserted on a clean run, and the timeout message is
    asserted to name the count."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-litter",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-litter", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = Path(r.stdout.split("logs=")[-1].strip())

    for name in ("cli", "ui"):
        assert (logs / f"{name}.porcelain.before").exists(), name
        assert (logs / f"{name}.porcelain.after").exists(), name
        assert (logs / f"{name}.litter").exists(), name
        count = (logs / f"{name}.litter.count").read_text().strip()
        assert count.isdigit(), (name, count)

    # the timeout refusal names the count, so a killed suite's leavings are
    # reported rather than discovered later
    text = LF.LAND.read_text()
    assert "litter.count" in text
    assert "a killed suite does not clean up after itself" in text

    # NIT-2: the noun must match what is counted. The porcelain delta counts
    # CHANGED paths -- new, modified or deleted -- so calling them
    # "untracked" describes a narrower thing than the number measures. Same
    # class as the STALE records-versus-lines noun.
    reports = [ln for ln in text.split("\n")
               if "$litter" in ln or "litter.count" in ln]
    assert reports
    assert not any("untracked" in ln for ln in reports), reports
    assert any("changed path(s)" in ln for ln in reports), reports


def test_doc3_the_runbook_command_works_at_bootstrap_time():
    """MIN-2. Step 8's literal command exits 127 at bootstrap time: the
    runner does not exist on `master` until the unit adding it has landed.
    The runbook must give the form that works -- the branch worktree's copy
    by ABSOLUTE path, with the cwd on master -- which is what §4.1's
    root-resolution rule is built for."""
    section = _runbook_section_one()
    assert "plugins/self-learn/cli/scripts/land" in section

    # the corrected form, and the reason it is needed
    assert "absolute path" in section.lower()
    assert "127" in section
    assert "cd <main checkout>" in section

    # the shipped script really does decouple its own location from --root,
    # which is what makes the absolute-path invocation work at all
    text = LF.LAND.read_text()
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    assert 'ROOT=$(git rev-parse --path-format=absolute --show-toplevel' in text


def test_major1_a_refusing_resume_keeps_the_staged_transcription(tmp_path):
    """MAJOR-1 (gate r5). `--continue-merge` exists so the merge survives a
    refusal. A SECOND refusal must not throw away the work the FIRST one
    asked the operator to do -- measured before this guard: `EDIT
    SURVIVED: False`, with no message naming the loss, and unstaged edits
    surviving only by accident. **No test covered a refusing resume.**

    The path here: refuse on the armor leg, make the transcription AND
    STAGE it, then resume in a state that refuses again for a DIFFERENT
    reason (CHK4). The staged edit must still be there, the merge must
    still be in progress, and the refusal must say so.
    """
    repo = LF.make_repo(tmp_path, with_ui=True, armor="remeasure")
    _armor_branch(
        repo, "u-resume",
        lambda s: s.replace('STRANDED: tuple[str, ...] = ()',
                            'STRANDED: tuple[str, ...] = ("repinned",)', 1),
    )
    first = LF.run_land(repo, tmp_path, "--branch", "u-resume", "--verdict", "v", timeout=180)
    assert first.returncode == 4, first.stdout + first.stderr
    assert assert_message_matches_tree(first.stderr, repo) == "left-uncommitted"

    # the operator does what the message says, and STAGES it
    armor = repo / "plugins/self-learn/cli/tests/test_armor.py"
    # A REAL transcription: drop the stranded entry and record why, dated --
    # what 4.7 requires of an exemption edit anyway. It matters here that the
    # result differs from BOTH sides of the merge, or the staged diff is
    # empty and there is nothing to lose.
    armor.write_text(armor.read_text().replace(
        'STRANDED: tuple[str, ...] = ("repinned",)',
        'STRANDED: tuple[str, ...] = ()  # dropped 2026-08-30, no longer owed', 1))
    LF.git(repo, "add", "--", "plugins/self-learn/cli/tests/test_armor.py")
    staged_before = LF.git(repo, "diff", "--cached", "--name-only").stdout
    assert "test_armor.py" in staged_before

    # ... and something else now makes the resume refuse, for a reason
    # that has nothing to do with the armor edit
    doc = repo / "docs/specs/self-learn/13-hosting-and-separation.md"
    doc.write_text(doc.read_text() + "\nstill uncommitted\n")

    second = LF.run_land(repo, tmp_path, "--branch", "u-resume", "--verdict", "v",
                         "--continue-merge", timeout=180)
    assert second.returncode == 4, second.stdout + second.stderr
    assert "CHK4" in second.stderr, second.stderr

    # THE PROPERTY: the merge and the staged transcription both survived
    assert (repo / ".git" / "MERGE_HEAD").exists(), "the resume aborted the merge"
    assert 'no longer owed' in armor.read_text(), "the edit was lost"
    assert "test_armor.py" in LF.git(repo, "diff", "--cached", "--name-only").stdout, (
        "the STAGED transcription was lost"
    )
    # and the refusal SAYS so, rather than leaving the operator to find out
    assert "your in-merge edits are KEPT" in second.stderr, second.stderr

    # and the loop still closes from there
    doc.write_text(doc.read_text().replace("\nstill uncommitted\n", ""))
    third = LF.run_land(repo, tmp_path, "--branch", "u-resume", "--verdict", "v",
                        "--continue-merge", timeout=180)
    assert third.returncode == 0, third.stdout + third.stderr
    committed = LF.git(repo, "show", "HEAD:plugins/self-learn/cli/tests/test_armor.py").stdout
    assert 'no longer owed' in committed


def test_major1_a_FIRST_pass_refusal_still_aborts(tmp_path):
    """The other direction, so the guard is not just "never abort": without
    `--continue-merge` a check refusal must still restore the tree, because
    there is no operator work in it to protect."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    head_before = LF.git(repo, "rev-parse", "HEAD").stdout.strip()
    fw = "docs/specs/self-learn/14-forward-work-map.md"
    LF.make_branch(repo, "u-dis",
                   edits={fw: (repo / fw).read_text() + "| FW-1 | out of order | WATCH | n |\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-dis", "--verdict", "v", timeout=180)
    assert r.returncode == 4, r.stdout + r.stderr
    assert not (repo / ".git" / "MERGE_HEAD").exists(), "a first-pass refusal left the merge"
    assert LF.git(repo, "status", "--porcelain").stdout.strip() == ""
    assert LF.git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_minor4_the_suite_step_is_resumable_after_an_interrupt(tmp_path):
    """MINOR-4, FIXED rather than documented. The suite step is the longest
    phase and the one an operator is most likely to interrupt, and it used
    to leave NO resumable state -- the step was recorded only on a refusal.

    Asserted at the seam and through the runner: the state file names
    `suites` while they run, and `sanitize` once they pass, so a resume
    does not redo an eleven-minute phase that already succeeded."""
    text = LF.LAND.read_text()
    suites_at = text.index("record_refusal_step suites\n\n  if [ \"$LANE\" = \"docs\" ]")
    sanitize_at = text.index("record_refusal_step sanitize")
    step5_at = text.index("# Step 5 — sanitize")
    assert suites_at < sanitize_at < step5_at, (suites_at, sanitize_at, step5_at)

    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(
        repo, "u-int",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r = LF.run_land(repo, tmp_path, "--branch", "u-int", "--verdict", "v", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    # a completed landing clears its state, which is the other half of the
    # contract -- a stale `suites` would send the next run round again
    state = subprocess.run(
        ["uv", "run", "--no-sync", "python3", "-m", "self_learn.landing.state",
         "--root", str(repo), "--branch", "u-int", "read"],
        cwd=LF.THIS_REPO_CLI, capture_output=True, text=True,
        env={**LF.env_for(tmp_path)},
    )
    assert state.returncode != 0 or state.stdout.strip() in ("", "null"), state.stdout


def test_nit5_dry_run_and_continue_merge_are_refused_by_name(tmp_path):
    """NIT-5. `--continue-merge` resumes a merge in the MAIN checkout;
    `--dry-run` builds a throwaway worktree that has no such merge, so the
    combination used to refuse with a message about the wrong tree."""
    repo = LF.make_repo(tmp_path, with_ui=True)
    LF.make_branch(repo, "u-both",
                   edits={"docs/specs/self-learn/drafts/n.md": "x\n"})
    r = LF.run_land(repo, tmp_path, "--branch", "u-both", "--verdict", "v",
                    "--dry-run", "--continue-merge", timeout=180)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "mutually exclusive" in r.stderr, r.stderr
    assert "PRE3" not in r.stderr, "it still refuses via a message about the wrong tree"


def test_minor3_the_printed_escape_hatch_actually_works(tmp_path):
    """MINOR-3. A message that invalidates its own advice is worse than no
    advice: the printed `git merge --abort` stopped working once the
    operator did what the SAME message told them to do.

    Measured here rather than asserted: with the edits unstaged a bare
    abort exits 128 and the merge survives; staging them first makes it
    work. The runner prints the form that works."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    LF.git(repo, "config", "user.email", "t@example.invalid")
    LF.git(repo, "config", "user.name", "T")
    (repo / "f.txt").write_text("base\n")
    (repo / "g.txt").write_text("other\n")
    LF.git(repo, "add", "-A"); LF.git(repo, "commit", "-q", "-m", "base")
    LF.git(repo, "checkout", "-q", "-b", "br")
    (repo / "g.txt").write_text("branch\n")
    LF.git(repo, "add", "-A"); LF.git(repo, "commit", "-q", "-m", "br")
    LF.git(repo, "checkout", "-q", "master")
    (repo / "f.txt").write_text("master\n")
    LF.git(repo, "add", "-A"); LF.git(repo, "commit", "-q", "-m", "m")
    LF.git(repo, "merge", "--no-ff", "--no-commit", "br", check=False)

    # the operator transcribes, in place, exactly as instructed
    (repo / "g.txt").write_text((repo / "g.txt").read_text() + "transcribed\n")

    bare = LF.git(repo, "merge", "--abort", check=False)
    assert bare.returncode != 0, "the premise is gone: a bare abort now works"
    assert LF.git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD",
                  check=False).returncode == 0, "the merge vanished anyway"

    LF.git(repo, "add", "-A")
    staged = LF.git(repo, "merge", "--abort", check=False)
    assert staged.returncode == 0, staged.stderr
    assert LF.git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD",
                  check=False).returncode != 0
    assert LF.git(repo, "status", "--porcelain").stdout.strip() == ""

    # and that is what the runner prints
    text = LF.LAND.read_text()
    assert "add -A && git -C $gr merge --abort" in text
    assert "a BARE abort refuses" in text


def test_minor1_the_state_sentence_derives_both_halves():
    """MINOR-1/NIT-4. The first half was derived; the second ("and the tree
    restored") was still asserted. Deriving the first half is what exposed
    the swallowed `merge --abort` rc and the os.replace trap, so the second
    gets the same treatment -- including a THIRD case for a tree that is
    neither, which an assert-only form cannot express."""
    body = _shell_functions(LF.LAND.read_text())["tree_state_sentence"]
    assert "status --porcelain" in body, "the restored half is not measured"
    assert "rev-parse -q --verify MERGE_HEAD" in body
    # three outcomes, not two
    assert body.count("printf") >= 3, body
    assert "NOT clean" in body, "there is no case for an abort that left changes"


def test_minor3_a_suite_that_silently_skipped_is_not_green(tmp_path):
    """MINOR-3 (gate r6). A UI run that silently SKIPPED 136 browser tests
    was adjudicated GREEN and pushed. That is this unit's own shape landing
    in the adjudicator: an outcome that is not a failure being read as a
    success. A suite that skipped that many is not green -- it is
    UNMEASURED.

    Two legs, both through the runner: a branch whose tests all skip is
    refused; the untouched fixture, which skips none, still lands.
    """
    # (a) a suite that runs and skips everything
    repo = LF.make_repo(tmp_path / "skip", with_ui=True)
    LF.git(repo, "checkout", "-q", "-b", "u-skip")
    many = "\n".join(
        f"@pytest.mark.skip(reason='browser unavailable')\ndef test_s{i}():\n    assert True\n"
        for i in range(25)
    )
    (repo / "plugins/self-learn/cli/tests/test_skips.py").write_text(
        "import pytest\n\n" + many)
    LF.git(repo, "add", "-A")
    LF.git(repo, "commit", "-q", "-m", "a suite that skips 25 tests")
    LF.git(repo, "checkout", "-q", "master")
    r = LF.run_land(repo, tmp_path / "skip", "--branch", "u-skip", "--verdict", "v", timeout=180)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "SKIPPED 25 tests" in r.stderr, r.stderr
    assert "UNMEASURED, not green" in r.stderr, r.stderr

    # (b) positive control: no skips, and it lands -- so the floor is not
    # simply refusing everything
    ok = LF.make_repo(tmp_path / "clean", with_ui=True)
    LF.make_branch(
        ok, "u-noskip",
        edits={"plugins/self-learn/cli/tests/test_gamma.py": "def test_g():\n    assert True\n"},
    )
    r2 = LF.run_land(ok, tmp_path / "clean", "--branch", "u-noskip", "--verdict", "v", timeout=180)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    # and the count is REPORTED on the green path, so "0 skipped" is a
    # measurement rather than an absence of news
    assert "suite green (0 skipped, ceiling" in r2.stdout, r2.stdout


def test_minor3_the_ceiling_clears_the_real_skip_counts():
    """The ceiling is grounded in measurement, not taste. Measured
    2026-08-30: the CLI suite skips **6** (sanctioned, stable across every
    run this session), the UI suite skips **0**, and the pathological run
    the gate observed skipped **136**. The ceiling must clear the real ones
    and catch that one."""
    text = LF.LAND.read_text()
    m = re.search(r"SUITE_SKIP_CEILING=\$\{SUITE_SKIP_CEILING:-(\d+)\}", text)
    assert m, "the ceiling is no longer a single overridable default"
    ceiling = int(m.group(1))
    assert ceiling >= 3 * 6, f"ceiling {ceiling} is under 3x the CLI's 6 sanctioned skips"
    assert ceiling < 136, f"ceiling {ceiling} would not have caught the observed 136"
    # the numbers that justify it are recorded beside it
    for n in ("6", "0", "136"):
        assert n in text


def test_minor2_every_in_merge_refusal_aborts_or_announces():
    """MINOR-2 (gate r6). Ten in-merge refusals neither aborted nor
    announced, and one of them -- a typo'd `--resolver` path -- is a
    CONFLICT refusal, which contradicts PRV4 outright.

    The invariant, derived from the script rather than listed: every `die`
    raised inside `run_merge_and_checks` must either

      * run BEFORE the merge exists (the preview and PRV1), or
      * route through `die_in_merge` / `abort_merge_unless_resuming`, or
      * carry `tree_state_sentence` itself, which announces the measured
        state.

    Positive control: an injected bare `die` inside the merge is reported.
    """
    text = LF.LAND.read_text()
    lines = text.split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("run_merge_and_checks() {"))
    depth, end = 1, start
    for i in range(start + 1, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth <= 0:
            end = i
            break
    assert end > start, "could not delimit run_merge_and_checks"

    # everything before the real merge invocation is pre-merge
    merge_at = next(i for i in range(start, end)
                    if "merge --no-ff --no-commit" in lines[i]
                    and not lines[i].lstrip().startswith("#"))

    def bare_dies(body: list[str], first: int, merge_line: int) -> list[tuple[int, str]]:
        out, last_guard = [], -99
        for i, l in enumerate(body, start=first):
            if not l.lstrip().startswith("#") and (
                    "abort_merge_unless_resuming" in l or "die_in_merge" in l):
                last_guard = i
            if l.lstrip().startswith("#"):
                continue
            if not re.search(r"(?:^|[\s;&|{])die \d", l):
                continue
            if i <= merge_line:
                continue                      # nothing merged yet
            if "tree_state_sentence" in l:
                continue                      # announces the measured state
            if i - last_guard <= 6:
                continue                      # guarded just above
            out.append((i + 1, l.strip()[:90]))
        return out

    assert bare_dies(lines[start:end + 1], start, merge_at) == [], \
        bare_dies(lines[start:end + 1], start, merge_at)

    # the typo'd-resolver refusal specifically -- the one that contradicted PRV4
    assert 'die_in_merge "$gr" 3 "PRV2: --resolver names a path not in the conflict' in text

    # positive control, on a synthetic body so the splice arithmetic cannot
    # be what makes it pass: a bare die AFTER the merge line is reported,
    # and the same die BEFORE it is not.
    synth = [
        '  git -C "$gr" merge --no-ff --no-commit "$BRANCH"',
    ] + ['  echo filler'] * 8 + [
        '  die 4 "a bare refusal inside the merge"',
    ]
    assert bare_dies(synth, 0, 0), "a bare in-merge die is invisible"
    synth_pre = ['  die 4 "a refusal before anything merged"',
                 '  git -C "$gr" merge --no-ff --no-commit "$BRANCH"']
    assert bare_dies(synth_pre, 0, 1) == [], "a pre-merge die is wrongly reported"


def _land_by_hand(clone: Path, src_cli: Path) -> str | None:
    """Do to `clone` exactly what a successful landing does, ending in the
    POST-PRUNE state: merge --no-ff, advance the anchor, stage it, commit,
    and delete every ref naming the branch. Returns the merge sha.

    Returns None when the clone's SOURCE is already a post-landing master:
    there is then no branch to merge, because the prune deleted it, and the
    tree in hand is the real article rather than a simulation of it.

    That branch is not a convenience. The first version of this helper read
    `origin/u-land` unconditionally, and running master's own suite on a
    post-prune clone made it die with `rev-parse origin/u-land` exit 128 --
    the terminal criterion's own probe depending on the very ref whose
    deletion is the thing being measured, which is the Blocker's shape one
    level further out. Measured 2026-08-30 at `0ed1f18`."""
    LF.git(clone, "checkout", "-q", "-B", "master", "origin/master")
    tip = LF.git(clone, "rev-parse", "-q", "--verify", "origin/u-land",
                 check=False)
    if tip.returncode != 0:
        # Positive control: 'no branch to merge' must mean ALREADY LANDED,
        # never 'could not look'. A clone with neither the ref nor the
        # landing in its history has nothing here to measure, and must say
        # so rather than passing quietly.
        assert (clone / "plugins/self-learn/cli/scripts/land").exists(), (
            "no `u-land` ref and no `scripts/land` either -- this clone is "
            "not a post-landing master, so there is nothing to measure"
        )
        rng, state = _unit_diff_frame(clone)
        assert state == "landed", (
            f"no `u-land` ref, but the history does not carry the landing "
            f"either: frame={rng} state={state}"
        )
        return None
    unit_tip = tip.stdout.strip()
    # `-c` is a GIT option, not a merge one, so it precedes the subcommand.
    # Placed after it the whole call fails, and with check=False that failure
    # is silent -- measured: the merge never happened and the frame came back
    # "building".
    m = LF.git(clone, "-c", "merge.conflictStyle=diff3", "merge", "--no-ff",
               "--no-commit", unit_tip, check=False)
    assert LF.git(clone, "rev-parse", "-q", "--verify", "MERGE_HEAD",
                  check=False).returncode == 0, (m.returncode, m.stdout, m.stderr)
    anchor = LF.git(clone, "rev-parse", "--short=7", "HEAD").stdout.strip()
    armor = clone / "plugins/self-learn/cli/tests/test_armor.py"
    if armor.exists():
        r = subprocess.run(
            ["uv", "run", "--no-sync", "python3", str(armor),
             "--remeasure", "--anchor", anchor],
            cwd=src_cli, capture_output=True, text=True,
            env={k: v for k, v in os.environ.items()
                 if k not in ("SELF_LEARN_ANALYST_MODEL", "SELF_LEARN_ANALYST_TIMEOUT")},
        )
        assert r.returncode == 0, (r.returncode, r.stderr[-1500:])
        LF.git(clone, "add", "--", "plugins/self-learn/cli/tests/test_armor.py")
    LF.git(clone, "commit", "-q", "-m", "Merge branch 'u-land' (post-prune probe)")
    # Step 6's prune, and then the ref a fresh clone of master would not have
    LF.git(clone, "branch", "-D", "u-land", check=False)
    LF.git(clone, "branch", "-rD", "origin/u-land", check=False)
    return LF.git(clone, "rev-parse", "HEAD").stdout.strip()


def test_the_unit_leaves_masters_suite_green_after_the_prune(tmp_path):
    """THE terminal criterion (gate r6). The landing was correct end to end
    and rehearsed to a real push, and it still left production's suite
    permanently red -- because `land`'s Step-6 prune deletes the branch
    AFTER the suite has already run, so no landing can ever catch a test
    that depends on that ref.

    Measured twice with the full runner on a fresh clone of post-landing
    master, 2026-08-30. The first run, on a clone taken at `1adaa2a`:

        POST_PRUNE_SUITE_RC=0
        suite rc=0  3045 passed, 6 skipped in 89.55s

    Re-taken at the shipping tip, it came back RED -- and the failure was
    THIS TEST, whose helper read `origin/u-land` unconditionally and died
    128 in a tree where the prune had deleted it. One measurement is not a
    property; the criterion is a claim about every future master, so it is
    re-taken whenever the tip moves. Post-prune master `<POSTPRUNE_SHA>`:

        POST_PRUNE_SUITE_RC=<POSTPRUNE_RC>
        suite rc=<POSTPRUNE_RC>  <POSTPRUNE_LINE>

    Re-running the whole suite here would cost ~90 s plus a venv sync, so
    this test carries the part that was actually red -- every landing test,
    executed against a post-prune tree with no `u-land` ref anywhere.
    """
    root = _repo_root()
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(root), str(clone)],
                   check=True, capture_output=True)
    LF.git(clone, "config", "user.email", "t@example.invalid")
    LF.git(clone, "config", "user.name", "T")
    _land_by_hand(clone, LF.THIS_REPO_CLI)

    # the state the prune actually leaves: no ref names this branch
    refs = LF.git(clone, "for-each-ref", "--format=%(refname)").stdout
    assert "u-land" not in refs, refs
    # ... and the merge is still in first-parent history, which is the whole
    # point of deriving from history rather than from a ref
    rng, state = _unit_diff_frame(clone)
    assert state == "landed", (state, rng)

    env = {k: v for k, v in os.environ.items()
           if k not in ("SELF_LEARN_ANALYST_MODEL", "SELF_LEARN_ANALYST_TIMEOUT")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    tests = clone / "plugins/self-learn/cli/tests"
    # Scoped to the tests that were ACTUALLY red post-prune -- UN1 and its
    # guard. Running the whole landing set here would re-enter this very
    # test inside the clone, and would run the clone's e2e tests against the
    # SOURCE venv, so `self_learn.landing` would resolve to the wrong
    # package: both are harness artefacts, not post-prune findings. The
    # whole-suite figure in the docstring is the real measurement, taken
    # with the shipped runner in a properly synced fresh clone.
    r = subprocess.run(
        ["uv", "run", "--no-sync", "pytest",
         str(tests / "test_land_runner.py"),
         "-q", "-p", "no:cacheprovider", "-k", "un1"],
        cwd=LF.THIS_REPO_CLI, capture_output=True, text=True, env=env, timeout=900,
    )
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    assert " failed" not in r.stdout, r.stdout[-1500:]
    assert "passed" in r.stdout, r.stdout[-500:]
