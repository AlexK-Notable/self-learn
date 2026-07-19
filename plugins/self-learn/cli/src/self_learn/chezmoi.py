"""User-scope chezmoi flow (T6): compile the managed section into a
chezmoi-managed target (canonically ``~/.claude/CLAUDE.md``) safely.

Why this exists (01 §3.5 / §5, E-17): ``~/.claude/CLAUDE.md`` is
chezmoi-managed. Editing the real file alone is same-machine-only — the next
``chezmoi apply`` anywhere serves the old committed state and clobbers the
section. So the compiler must ``chezmoi re-add`` after writing AND commit+push
the dotfiles repo. And it must never ``re-add`` over pre-existing drift, or it
would silently canonize unrelated local edits.

The pinned sequence (08 §3 T6 row / §5 playbook), all paths parameterized:

1. ``chezmoi diff <target>``          -> ABORT on any pre-existing drift
2. ``chezmoi git -- status --porcelain`` -> ABORT if the dotfiles repo is dirty
3. edit the real target file (managed-section compiler)
4. ``chezmoi re-add <target>``
5. ``chezmoi git -- add -A`` ; ``chezmoi git -- commit -m <msg>`` ;
   ``chezmoi git -- push``

Step-5 form (documented call): ``add -A`` inside the dotfiles repo is safe
here *because* step 2 proved the repo clean before we touched anything — the
only staged change can be step 4's re-add. Aborts raise
:class:`ChezmoiAbort` with the §5 playbook message ("fix drift / commit
dotfiles first, or route to project scope") and happen BEFORE any edit, so
the target file is untouched and the record stays pending. A no-op compile
(section already current) stops after step 3: there is nothing to re-add or
commit.

``chezmoi`` is invoked through PATH (parameterizable binary name), so tests
drive the whole flow with a PATH-shimmed fake that records argv and
simulates drift / dirty / clean.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .compilers import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_WORDS,
    SectionResult,
    compile_managed_file,
)
from .records import Record

__all__ = [
    "CHEZMOI_DIRTY_MARKER",
    "ChezmoiAbort",
    "ChezmoiError",
    "UserScopeDirtyStatus",
    "UserScopeResult",
    "commit_all_user_scope",
    "compile_user_scope",
    "dotfiles_source_path",
    "preflight_user_scope",
    "user_scope_dirty_status",
]

#: §5 playbook intent, verbatim tail on both abort paths.
_ABORT_ADVICE = (
    "fix drift / commit dotfiles first, or route to project scope; "
    "the record stays pending"
)

#: U20 gate R1 (F5-5 guided commit-first): the pinned, stable substring of
#: the dirty-repo abort message (never the drift abort, which contains
#: neither this string nor gitops's — the dirty-vs-drift boundary is
#: string-detectable by construction). Extracted so the UI's marker match
#: and the tests import the SAME constant this raise site uses — never a
#: hand-copied substring (verbs.py carries the gitops-side twin,
#: ``GITOPS_DIRTY_MARKER``).
CHEZMOI_DIRTY_MARKER = "dotfiles repo has uncommitted changes"


class ChezmoiError(Exception):
    """A chezmoi invocation failed (missing binary, nonzero exit)."""


class ChezmoiAbort(Exception):
    """The guarded route must not proceed (pre-existing drift / dirty repo).

    Raised BEFORE any edit — the target file is untouched.
    """


@dataclass(frozen=True)
class UserScopeResult:
    """Outcome of one user-scope compile-and-sync."""

    section: SectionResult
    committed: bool  # False = compile was a no-op; steps 4-5 skipped
    commit_message: str | None


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ChezmoiError(f"cannot run {argv[0]!r}: {exc}") from exc


def _check(proc: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    if proc.returncode != 0:
        raise ChezmoiError(
            f"{' '.join(proc.args)} failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc


@dataclass(frozen=True)
class UserScopeDirtyStatus:
    """Read-only companion to :func:`preflight_user_scope` (U20:
    ``commit_drift`` needs to tell drift and dirty APART — the preflight
    only ever refuses on either, undifferentiated to its callers)."""

    drift: bool
    dirty_files: list[str]


def user_scope_dirty_status(
    target: Path | str, *, chezmoi: str = "chezmoi"
) -> UserScopeDirtyStatus:
    """The same two probes :func:`preflight_user_scope` runs (``chezmoi
    diff`` then ``chezmoi git -- status --porcelain``), but reporting the
    outcome instead of raising — writes nothing, same as its sibling
    through step 2. ``dirty_files`` parses porcelain's ``XY <path>`` lines
    (2-char status + one space, per ``git status --porcelain`` — chezmoi's
    ``git`` passthrough is a real git, same format)."""
    target = Path(target)
    diff = _check(_run([chezmoi, "diff", str(target)]))
    status = _check(_run([chezmoi, "git", "--", "status", "--porcelain"]))
    files = [line[3:] for line in status.stdout.splitlines() if line.strip()]
    return UserScopeDirtyStatus(drift=bool(diff.stdout.strip()), dirty_files=files)


def dotfiles_source_path(*, chezmoi: str = "chezmoi") -> Path:
    """``chezmoi source-path`` — the dotfiles repo's absolute path, i.e.
    what ``chezmoi git`` operates inside (U20: the commit-drift verb's
    ``repo`` field for the user-scope leg; never ``chezmoi cd``, which
    spawns an interactive child shell — precedent in
    tests/test_route_hook.py's hook deny_message)."""
    return Path(_check(_run([chezmoi, "source-path"])).stdout.strip())


def commit_all_user_scope(message: str, *, chezmoi: str = "chezmoi") -> str:
    """``chezmoi git -- add -A`` + ``commit -m <message>`` — the user-scope
    leg's own write step (U20 commit-drift: repo-wide, matching
    :func:`preflight_user_scope`'s own repo-wide read path, gate m8's
    mirror image for this leg — never target-path-scoped, unlike the
    host-repo leg). Callers pre-flight (:func:`user_scope_dirty_status`);
    this never checks drift/dirty itself. Returns the new commit's sha."""
    _check(_run([chezmoi, "git", "--", "add", "-A"]))
    _check(_run([chezmoi, "git", "--", "commit", "-m", message]))
    return _check(_run([chezmoi, "git", "--", "rev-parse", "HEAD"])).stdout.strip()


def preflight_user_scope(target: Path | str, *, chezmoi: str = "chezmoi") -> None:
    """Steps 1–2 of the guarded sequence, standalone (doc 13 §4: two-phase
    routes run every dirty-check in PRE-FLIGHT, before the ledger commit —
    for the chezmoi-managed user file, these two checks ARE that check).
    Raises :class:`ChezmoiAbort` on drift/dirty; nothing has been touched."""
    target = Path(target)

    # 1. Pre-existing drift on the target? Never re-add over drift (§5).
    diff = _check(_run([chezmoi, "diff", str(target)]))
    if diff.stdout.strip():
        raise ChezmoiAbort(
            f"chezmoi reports pre-existing drift on {target}: {_ABORT_ADVICE}"
        )

    # 2. Dotfiles repo clean? A dirty repo would entangle our commit.
    status = _check(_run([chezmoi, "git", "--", "status", "--porcelain"]))
    if status.stdout.strip():
        raise ChezmoiAbort(f"{CHEZMOI_DIRTY_MARKER}: {_ABORT_ADVICE}")


def compile_user_scope(
    target: Path | str,
    records: list[Record],
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_words: int = DEFAULT_MAX_WORDS,
    chezmoi: str = "chezmoi",
    commit_message: str | None = None,
    push: bool = True,
) -> UserScopeResult:
    """Run the full guarded sequence against ``target``. See module docstring.

    Raises :class:`ChezmoiAbort` (target untouched) on drift or a dirty
    dotfiles repo; :class:`ChezmoiError` on invocation failures.
    """
    target = Path(target)

    preflight_user_scope(target, chezmoi=chezmoi)  # steps 1–2

    # 3. Edit the real target file (managed-section compiler).
    section = compile_managed_file(
        target, records, max_entries=max_entries, max_words=max_words
    )
    if not section.changed:
        return UserScopeResult(section=section, committed=False, commit_message=None)

    # 4. Fold the edit back into chezmoi's source state.
    _check(_run([chezmoi, "re-add", str(target)]))

    # 5. Commit + push the dotfiles repo — re-add alone is same-machine-only.
    message = commit_message or f"self-learn: update managed section in {target.name}"
    _check(_run([chezmoi, "git", "--", "add", "-A"]))
    _check(_run([chezmoi, "git", "--", "commit", "-m", message]))
    if push:
        _check(_run([chezmoi, "git", "--", "push"]))

    return UserScopeResult(section=section, committed=True, commit_message=message)
