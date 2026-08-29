"""state.py — the landing-state file `--continue` reads (§4.10a).

Written the moment `git commit` creates the merge commit (branch, base
sha, resolver mapping, verdict, the MERGE SHA and its PARENT SHAS), and
updated on every refusal at step >= commit (the failing step name + exit
code). Lives under `${XDG_CACHE_HOME:-~/.cache}/self-learn/` — NEVER in
the tree (`gitops.py:489-504`'s convention; UN2 — this package never
reads or writes `~/.self-learn`, a different directory entirely).

`evaluate_continue()` is CNT1/CNT2's four-precondition check: `--continue`
is accepted iff all four hold; a bare re-run in the same bad state (no
`--continue`) must REFUSE (CNT1) rather than silently re-merging.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RESUMABLE_STEPS = ("suites", "sanitize", "push")  # exit codes 5, 6, 7 respectively
STEP_FOR_CODE = {5: "suites", 6: "sanitize", 7: "push"}


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "self-learn"


def state_path(branch: str) -> Path:
    return cache_dir() / f"landing-{branch}.state"


def write_state(branch: str, **fields) -> Path:
    p = state_path(branch)
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    data.update(fields)
    data["branch"] = branch
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return p


def read_state(branch: str) -> dict | None:
    p = state_path(branch)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_state(branch: str) -> None:
    p = state_path(branch)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# git helpers, all --root-relative (N-19: never bare/relative to the shell's cwd)

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def head_merge_parent2(root: Path) -> str | None:
    """HEAD^2 if HEAD is a merge commit, else None."""
    p = _git(root, "rev-parse", "HEAD^2")
    return p.stdout.strip() if p.returncode == 0 else None


def head_sha(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def parent_shas(root: Path, ref: str = "HEAD") -> list[str]:
    out = _git(root, "log", "-1", "--format=%P", ref).stdout.strip()
    return out.split() if out else []


def head_is_ancestor_of(root: Path, ref: str) -> bool:
    p = _git(root, "merge-base", "--is-ancestor", "HEAD", ref)
    return p.returncode == 0


# ---------------------------------------------------------------------------
# CNT1 / CNT2

@dataclass
class ContinueDecision:
    in_post_commit_refusal_state: bool  # CNT1's trigger condition
    ok: bool  # True iff all four CNT2 preconditions hold
    reason: str
    resume_step: str | None = None
    recorded: dict = field(default_factory=dict)


def evaluate_continue(root: Path, branch: str) -> ContinueDecision:
    merge_p2 = head_merge_parent2(root)
    is_merge = merge_p2 is not None
    not_on_origin = is_merge and not head_is_ancestor_of(root, "origin/master")

    st = read_state(branch)
    step_ok = False
    recorded_step = None
    if st is not None:
        recorded_step = st.get("refusal_step")
        base_matches = st.get("base_sha") == _git(root, "rev-parse", "origin/master").stdout.strip()
        branch_matches = st.get("branch") == branch
        step_ok = bool(
            base_matches and branch_matches and recorded_step in RESUMABLE_STEPS
        )

    in_post_commit_refusal_state = is_merge and not_on_origin and step_ok

    if not in_post_commit_refusal_state:
        return ContinueDecision(False, ok=False, reason="not in a post-commit refusal state", recorded=st or {})

    # condition 4: the recorded merge sha and parent list match HEAD exactly
    recorded_merge_sha = (st or {}).get("merge_sha")
    recorded_parents = (st or {}).get("parent_shas")
    actual_sha = head_sha(root)
    actual_parents = parent_shas(root)
    if recorded_merge_sha != actual_sha or recorded_parents != actual_parents:
        return ContinueDecision(
            True, ok=False,
            reason=(
                "--continue impossible: HEAD is not the merge this refusal recorded "
                f"(state file {state_path(branch)}: merge_sha={recorded_merge_sha!r} "
                f"parents={recorded_parents!r}; HEAD={actual_sha!r} parents={actual_parents!r})"
            ),
            recorded=st or {},
        )

    return ContinueDecision(True, ok=True, reason="resumable", resume_step=recorded_step, recorded=st or {})


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m self_learn.landing.state")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--branch", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write")
    p_write.add_argument("--json", required=True, help="a JSON object to merge into the state")

    sub.add_parser("read")
    sub.add_parser("clear")
    sub.add_parser("check")  # CNT1/CNT2 evaluation
    sub.add_parser("path")

    args = ap.parse_args(argv)
    root = args.root.resolve()

    if args.cmd == "write":
        fields = json.loads(args.json)
        p = write_state(args.branch, **fields)
        print(p)
        return 0
    if args.cmd == "read":
        st = read_state(args.branch)
        print(json.dumps(st) if st is not None else "null")
        return 0 if st is not None else 1
    if args.cmd == "clear":
        clear_state(args.branch)
        return 0
    if args.cmd == "path":
        print(state_path(args.branch))
        return 0
    if args.cmd == "check":
        d = evaluate_continue(root, args.branch)
        # bash-friendly key=value lines (no JSON parsing needed on that side)
        print(f"in_post_commit_refusal_state={'yes' if d.in_post_commit_refusal_state else 'no'}")
        print(f"ok={'yes' if d.ok else 'no'}")
        print(f"resume_step={d.resume_step or ''}")
        print(f"reason={d.reason}")
        return 0 if d.ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
