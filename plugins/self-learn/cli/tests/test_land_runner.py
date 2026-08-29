"""End-to-end tests for `scripts/land`, against THROWAWAY git fixture
repos only (never the real repo or the real remote) -- landing_fixture.py
builds a fresh bare "origin" + main-checkout "repo" per test, under
tmp_path, with XDG_CACHE_HOME/SELF_LEARN_HOME redirected there too.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import landing_fixture as LF


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
    repo = LF.make_repo(tmp_path)
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
    LF.git(
        repo, "mv",
        "plugins/self-learn/cli/tests/test_alpha.py",
        "docs/specs/self-learn/drafts/renamed-test-alpha.py",
    )
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
