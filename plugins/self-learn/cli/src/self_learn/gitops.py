"""Targeted staging, pinned commits, per-verb push with rebase-retry (T7).

Pins implemented (08 §1 Resolution-verbs + Push rows; §5 playbooks):

- Staging is TARGETED: ``git add -- <touched paths that still exist>``,
  never ``-A``. Deletions among a verb's touched paths are pre-staged by
  ledger_ops (``git mv`` / ``git rm``) or were untracked — see its
  docstring — so filtering to still-existing paths is exact.
- Commit: pinned message as the subject; the optional note becomes the
  commit BODY (02 §2: ``resolution_note`` → commit body).
- Push policy (the pinned retry): ``git push``; on failure try
  ``git pull --rebase --autostash`` then retry the push ONCE.
  * rebase conflict → ``git rebase --abort``, LOUD stderr message, local
    commit kept, distinct failure (:data:`EXIT_REBASE_CONFLICT`) — mirror
    of ``claude-skills-sync``'s never-auto-resolve policy.
  * any other push failure → LOUD stderr warning, local commit kept,
    :data:`EXIT_PUSH_FAILED`; ``self-learn push`` retries later.
- :func:`push_pending` is the bare ``self-learn push`` verb's behavior:
  re-attempt publishing whatever local commits exist, same retry policy.

Nothing here decides WHAT to commit — verbs.py owns sequences; this module
owns the git mechanics.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

__all__ = [
    "EXIT_PUSH_FAILED",
    "EXIT_REBASE_CONFLICT",
    "GitOpsError",
    "PushResult",
    "commit",
    "paths_dirty",
    "push_pending",
    "push_with_retry",
    "stage",
]

#: Distinct non-zero exits (08 §1 Push pin: failures are loud AND distinct).
EXIT_PUSH_FAILED = 3
EXIT_REBASE_CONFLICT = 4


class GitOpsError(Exception):
    """A local git operation (stage/commit) failed — always an error;
    push failures are NOT exceptions (commit kept, loud result instead)."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )


def _git_ok(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = _git(repo, *args)
    if proc.returncode != 0:
        raise GitOpsError(
            f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}"
        )
    return proc


def stage(repo: Path, paths: Iterable[Path | str]) -> list[Path]:
    """``git add -- <existing touched paths>`` — targeted staging, never
    ``-A``. Vanished paths (deletions pre-staged by git mv/rm, or
    untracked-and-gone) are skipped. Returns what was actually staged."""
    existing = [Path(p) for p in paths if Path(p).exists()]
    if existing:
        _git_ok(repo, "add", "--", *[str(p) for p in existing])
    return existing


def commit(repo: Path, message: str, body: str | None = None) -> str:
    """Commit the index with the pinned subject; ``body`` (the resolution
    note) becomes the commit body. Returns the new commit's sha."""
    args = ["commit", "-q", "-m", message]
    if body:
        args += ["-m", body]
    _git_ok(repo, *args)
    return _git_ok(repo, "rev-parse", "HEAD").stdout.strip()


def paths_dirty(repo: Path, target: Path | str) -> bool:
    """True iff ``target`` has uncommitted changes (tracked-modified OR
    untracked) — the dirty-compile-target abort predicate."""
    proc = _git_ok(repo, "status", "--porcelain", "--", str(target))
    return bool(proc.stdout.strip())


@dataclass(frozen=True)
class PushResult:
    """Outcome of one push attempt (with the pinned retry)."""

    ok: bool
    retried: bool = False  # the pull-rebase-retry path was taken
    rebase_conflict: bool = False
    detail: str = ""

    @property
    def exit_code(self) -> int:
        if self.ok:
            return 0
        return EXIT_REBASE_CONFLICT if self.rebase_conflict else EXIT_PUSH_FAILED


def _rebase_in_progress(repo: Path) -> bool:
    gitdir = Path(_git_ok(repo, "rev-parse", "--git-dir").stdout.strip())
    if not gitdir.is_absolute():
        gitdir = Path(repo) / gitdir
    return (gitdir / "rebase-merge").exists() or (gitdir / "rebase-apply").exists()


def push_with_retry(repo: Path) -> PushResult:
    """The pinned per-verb push. Never raises for push failures — the
    commit is kept and the result says loudly what happened."""
    first = _git(repo, "push", "-q")
    if first.returncode == 0:
        return PushResult(ok=True)

    # Non-FF (or any push failure): pull --rebase --autostash, retry ONCE.
    pull = _git(repo, "pull", "--rebase", "--autostash", "-q")
    if pull.returncode != 0:
        if _rebase_in_progress(repo):
            _git(repo, "rebase", "--abort")
            print(
                "self-learn: PUSH BLOCKED — rebase conflict while syncing with the "
                "remote. The rebase was aborted and your commit is KEPT locally. "
                "Resolve the divergence manually (git pull --rebase), then run "
                "`self-learn push`.",
                file=sys.stderr,
            )
            return PushResult(
                ok=False,
                retried=True,
                rebase_conflict=True,
                detail=(pull.stderr or pull.stdout).strip(),
            )
        print(
            "self-learn: PUSH FAILED — could not reach/sync the remote. Your "
            "commit is KEPT locally; run `self-learn push` to retry.",
            file=sys.stderr,
        )
        return PushResult(
            ok=False,
            retried=True,
            detail=(pull.stderr or first.stderr).strip(),
        )

    second = _git(repo, "push", "-q")
    if second.returncode == 0:
        return PushResult(ok=True, retried=True)
    print(
        "self-learn: PUSH FAILED after rebase-retry. Your commit is KEPT "
        "locally; run `self-learn push` to retry.",
        file=sys.stderr,
    )
    return PushResult(ok=False, retried=True, detail=second.stderr.strip())


def push_pending(repo: Path) -> PushResult:
    """The bare ``self-learn push`` verb: publish whatever local commits
    exist, with the same pinned retry policy."""
    return push_with_retry(repo)
