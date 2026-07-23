"""User-scope chezmoi flow (T6): compile the managed section into a
chezmoi-managed target (canonically ``~/.claude/CLAUDE.md``) safely.

Why this exists (01 §3.5 / §5, E-17): ``~/.claude/CLAUDE.md`` is
chezmoi-managed. Editing the real file alone is same-machine-only — the next
``chezmoi apply`` anywhere serves the old committed state and clobbers the
section. So the compiler must ``chezmoi re-add`` after writing AND commit+push
the dotfiles repo. And it must never ``re-add`` over pre-existing drift, or it
would silently canonize unrelated local edits.

C2 (chezmoi: HARD dependency -> DETECTED capability): chezmoi is optional,
not a hard dependency. :func:`user_scope_capability` probes which of three
states applies — absent, present-but-unmanaged, or managed — and only the
managed state runs the guarded sync below; the other two silently degrade
to a plain file write (§3 of the C2 spec).

The pinned sequence (08 §3 T6 row / §5 playbook), all paths parameterized,
runs in full ONLY when the target is chezmoi-managed:

1. ``chezmoi diff <target>``          -> ABORT on any pre-existing drift
2. ``chezmoi git -- status --porcelain`` -> ABORT if the dotfiles repo is dirty
3. edit the real target file (managed-section compiler)
4. ``chezmoi re-add <target>``
5. ``chezmoi git -- add -A`` ; ``chezmoi git -- commit -m <msg>`` ;
   ``chezmoi git -- push``

Step 3 (the write) always runs, capability or not. Steps 1-2 and 4-5 are
skipped entirely when chezmoi is absent or the target is unmanaged (§3 rows
1-2, silent). When managed, steps 1-2 are unchanged: aborts raise
:class:`ChezmoiAbort` with the §5 playbook message ("fix drift / commit
dotfiles first, or route to project scope") and happen BEFORE any edit, so
the target file is untouched and the record stays pending. If a step 4/5
command fails on an otherwise-healthy managed target (a broken source or
remote), the write already happened — that is caught and turned into a
WARN, never a re-raise or rollback (§3 row 4). A no-op compile (section
already current) stops after step 3: there is nothing to re-add or commit.

Step-5 form (documented call): ``add -A`` inside the dotfiles repo is safe
here *because* step 2 proved the repo clean before we touched anything — the
only staged change can be step 4's re-add.

``chezmoi`` is invoked through PATH (parameterizable binary name), so tests
drive the whole flow with a PATH-shimmed fake that records argv and
simulates drift / dirty / clean / unmanaged.
"""

from __future__ import annotations

import shutil
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
    "ADOPT_COMMAND_PREFIX",
    "CHEZMOI_DIRTY_MARKER",
    "ChezmoiAbort",
    "ChezmoiError",
    "USER_SCOPE_ABSENT",
    "USER_SCOPE_MANAGED",
    "USER_SCOPE_UNMANAGED",
    "AdoptResult",
    "UserScopeDirtyStatus",
    "UserScopeResult",
    "adopt_command",
    "adopt_user_scope",
    "commit_all_user_scope",
    "compile_user_scope",
    "dotfiles_source_path",
    "preflight_user_scope",
    "user_scope_capability",
    "user_scope_dirty_status",
]

#: C2 §3 detection states for a user-scope compile target — see
#: :func:`user_scope_capability`. Exported so callers/tests import the SAME
#: literals this function returns (discipline already established for
#: ``CHEZMOI_DIRTY_MARKER``).
USER_SCOPE_ABSENT = "absent"
USER_SCOPE_UNMANAGED = "unmanaged"
USER_SCOPE_MANAGED = "managed"

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
    committed: bool  # True only on a managed, fully-synced write (§3 row 3)
    commit_message: str | None
    synced: bool = False  # True <=> full re-add+commit(+push) ran (row 3)
    sync_warning: str | None = None  # row 4 only: the single WARN string
    #: A2 §10.5 (U-A2-2): the chezmoi-adopt offer's hint text, set ONLY on
    #: USER_SCOPE_UNMANAGED when the caller opted in via ``offer_adopt``
    #: (never ABSENT — nothing to adopt; never MANAGED — already syncs).
    #: ``None`` everywhere else, including every pre-A2 caller (plain
    #: ``~/.claude/CLAUDE.md`` never passes ``offer_adopt=True`` — §10.1).
    adopt_hint: str | None = None


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


def user_scope_capability(target: Path | str, *, chezmoi: str = "chezmoi") -> str:
    """Which of the three C2 §3 detection states applies to ``target``:
    :data:`USER_SCOPE_ABSENT` (no ``chezmoi`` on PATH), or, when present,
    :data:`USER_SCOPE_MANAGED` / :data:`USER_SCOPE_UNMANAGED` from
    ``chezmoi source-path <target>`` (rc 0 = managed, nonzero = unmanaged —
    "not managed" is the expected, non-error outcome for an unmanaged
    target, empirically verified against chezmoi v2.71.0; ``chezmoi
    managed <path>`` is NOT a discriminator, it returns rc 0 even for an
    unmanaged path). Never raises on the unmanaged branch: uses :func:`_run`
    (not :func:`_check`) because a nonzero ``source-path`` here is a
    detection SIGNAL, not an invocation failure. (Row 4, a managed target
    whose sync breaks, is a sync-time failure, not a state this probe can
    see — decided in :func:`compile_user_scope`.)"""
    if shutil.which(chezmoi) is None:
        return USER_SCOPE_ABSENT
    proc = _run([chezmoi, "source-path", str(target)])
    return USER_SCOPE_MANAGED if proc.returncode == 0 else USER_SCOPE_UNMANAGED


def _drift_dirty_guard(target: Path, *, chezmoi: str) -> None:
    """Steps 1-2 body: pre-existing-drift + dirty-repo checks, assuming the
    caller has already established :data:`USER_SCOPE_MANAGED`. Factored out
    of :func:`preflight_user_scope` so :func:`compile_user_scope` — which
    computes the capability itself to pick its branch — can run these two
    checks without a second, redundant ``source-path`` probe."""
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


def preflight_user_scope(target: Path | str, *, chezmoi: str = "chezmoi") -> None:
    """Steps 1–2 of the guarded sequence, standalone (doc 13 §4: two-phase
    routes run every dirty-check in PRE-FLIGHT, before the ledger commit —
    for the chezmoi-managed user file, these two checks ARE that check).

    C2: gated on capability first (§3 rows 1-2) — an absent or unmanaged
    target has nothing to sync, so there is nothing to drift-check; this
    returns cleanly, doing nothing. For a managed target the rest is
    UNCHANGED: raises :class:`ChezmoiAbort` on drift/dirty; nothing has
    been touched."""
    target = Path(target)
    if user_scope_capability(target, chezmoi=chezmoi) != USER_SCOPE_MANAGED:
        return
    _drift_dirty_guard(target, chezmoi=chezmoi)


#: The invocation's fixed lead, factored out so a CONSUMER (the review
#: UI, across the subprocess boundary) can locate + parse the hint's
#: trailing command out of stderr text via the SAME literal
#: :func:`adopt_command` builds from — never a hand-copied marker string
#: that could drift from the generator (the gate-n12 discipline
#: ``routes.py``'s ``COMMIT_DRIFT_MARKERS`` already uses for its own
#: stderr-borne signals).
ADOPT_COMMAND_PREFIX = "self-learn chezmoi-adopt "


def adopt_command(target: Path | str) -> str:
    """A2 §10.3/§10.5: the ONE user-facing command that adopts ``target``
    into chezmoi management — the single source the bare-CLI hint and the
    UI-interactive "yes" both name (§4.2-style sync discipline: never a
    second command string to drift from this one)."""
    return f"{ADOPT_COMMAND_PREFIX}{target}"


def compile_user_scope(
    target: Path | str,
    records: list[Record],
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_words: int = DEFAULT_MAX_WORDS,
    chezmoi: str = "chezmoi",
    commit_message: str | None = None,
    push: bool = True,
    offer_adopt: bool = False,
) -> UserScopeResult:
    """Run the full guarded sequence against ``target``. See module docstring.

    C2: the WRITE (step 3) always runs. For an absent or unmanaged target
    (§3 rows 1-2) that is ALL that runs — no preflight, no sync, silent.
    For a managed target, steps 1-2 (drift/dirty) and, when the compile
    changed anything, steps 4-5 (re-add + commit/push) run as before; a
    genuine drift/dirty :class:`ChezmoiAbort` still propagates (target
    untouched). If steps 4-5 raise :class:`ChezmoiError` on an otherwise
    healthy managed target (row 4: a broken source or remote), the write
    already happened — that failure is caught and turned into
    ``sync_warning``, never re-raised, never rolled back (H-2).

    ``offer_adopt`` (A2 §10.2, U-A2-2): when True AND the target reads
    UNMANAGED, the result carries an ``adopt_hint`` — self-learn just
    wrote a NEW file whose whole point ("so it syncs") is defeated by
    staying untracked, so it is worth offering to adopt (§10.1). Callers
    thread this ONLY for a ``rules`` variant (never plain
    ``~/.claude/CLAUDE.md`` — that file's unmanaged state is the user's
    own prior choice, §10.1) — this function cannot infer variant from
    the path robustly, so it is threaded, not guessed (§10.5). ABSENT
    (nothing to adopt) and MANAGED (already syncs) never carry a hint,
    regardless of ``offer_adopt``.
    """
    target = Path(target)
    cap = user_scope_capability(target, chezmoi=chezmoi)

    if cap != USER_SCOPE_MANAGED:
        # §3 rows 1-2: WRITE only, silent — no preflight, no sync.
        section = compile_managed_file(
            target, records, max_entries=max_entries, max_words=max_words
        )
        adopt_hint = None
        if offer_adopt and cap == USER_SCOPE_UNMANAGED:
            adopt_hint = (
                f"wrote {target} — not tracked by chezmoi, so it will not "
                "sync to your other machines. To sync it: "
                f"{adopt_command(target)}"
            )
        return UserScopeResult(
            section=section, committed=False, commit_message=None,
            synced=False, sync_warning=None, adopt_hint=adopt_hint,
        )

    _drift_dirty_guard(target, chezmoi=chezmoi)  # steps 1–2, unchanged

    # 3. Edit the real target file (managed-section compiler).
    section = compile_managed_file(
        target, records, max_entries=max_entries, max_words=max_words
    )
    if not section.changed:
        return UserScopeResult(
            section=section, committed=False, commit_message=None,
            synced=False, sync_warning=None,
        )

    message = commit_message or f"self-learn: update managed section in {target.name}"
    try:
        # 4. Fold the edit back into chezmoi's source state.
        _check(_run([chezmoi, "re-add", str(target)]))

        # 5. Commit + push — re-add alone is same-machine-only.
        _check(_run([chezmoi, "git", "--", "add", "-A"]))
        _check(_run([chezmoi, "git", "--", "commit", "-m", message]))
        if push:
            _check(_run([chezmoi, "git", "--", "push"]))
    except ChezmoiError as exc:
        # §3 row 4: broken source/remote. The write already landed; warn,
        # don't re-raise, don't roll back (H-2). Accurate across a
        # re-add/commit failure AND a push-only failure (where the commit
        # already landed locally, so no false "clobber" claim there either
        # — the wording below covers both without over-claiming).
        warning = (
            f"wrote {target} but chezmoi sync did not complete ({exc}) — "
            "your edit is on disk but may not be captured in the dotfiles "
            "source, so a later `chezmoi apply` elsewhere could clobber "
            "it. Fix the dotfiles source/remote, then `self-learn "
            "recompile`."
        )
        return UserScopeResult(
            section=section, committed=False, commit_message=message,
            synced=False, sync_warning=warning,
        )

    return UserScopeResult(
        section=section, committed=True, commit_message=message,
        synced=True, sync_warning=None,
    )


@dataclass(frozen=True)
class AdoptResult:
    """Outcome of one chezmoi-adopt (A2 §10.3). ``tracked`` is True as
    soon as ``chezmoi add`` succeeds — the file is under chezmoi
    management from that instant, even if the sync tail below degrades
    (H-2: never rolled back). ``synced`` is True only on a full
    commit(+push)."""

    tracked: bool
    synced: bool
    commit_sha: str | None = None
    warning: str | None = None


def adopt_user_scope(
    target: Path | str,
    *,
    message: str,
    chezmoi: str = "chezmoi",
    push: bool = True,
) -> AdoptResult:
    """A2 §10.3: the accepted §10 offer — bring an UNMANAGED, self-learn-
    written user-scope target under chezmoi management. Self-contained
    (P-A2b′-offer: no new write mechanism, only a tracking follow-up),
    and reuses this module's own machinery end to end (§10.3's "reinvents
    nothing" pin):

    1. **Porcelain-only dirty guard.** Abort if the dotfiles repo already
       has uncommitted changes, so the ``add -A`` below sweeps in ONLY
       this adopt's own new source file. Deliberately NOT
       :func:`_drift_dirty_guard` (its ``chezmoi diff`` half errors on an
       unmanaged target — empirically ``rc=1 "not managed"``, see the A2
       spec's Grounding transcript) — only the porcelain half applies
       pre-add.
    2. **``chezmoi add <target>``** — the one genuinely new primitive.
       Exit 0 folds the file into chezmoi's source state and flips the
       target to MANAGED. Raises on failure: nothing was tracked yet, so
       there is nothing to degrade.
    3. **Commit + push** — :func:`commit_all_user_scope`, the SAME sync
       tail :func:`compile_user_scope` runs on a managed write. A failure
       HERE, after step 2 already tracked the file, degrades to
       ``warning`` — never a rollback (H-2): the file is tracked on disk;
       only the sync degraded.
    """
    target = Path(target)

    status = _check(_run([chezmoi, "git", "--", "status", "--porcelain"]))
    if status.stdout.strip():
        raise ChezmoiAbort(
            f"{CHEZMOI_DIRTY_MARKER}: commit or stash the dotfiles repo's "
            "own changes first, then retry the adopt"
        )

    _check(_run([chezmoi, "add", str(target)]))

    try:
        sha = commit_all_user_scope(message, chezmoi=chezmoi)
        if push:
            _check(_run([chezmoi, "git", "--", "push"]))
    except ChezmoiError as exc:
        warning = (
            f"{target} is now tracked by chezmoi, but the sync commit/push "
            f"did not complete ({exc}) — fix the dotfiles source/remote, "
            "then `self-learn recompile` (re-running the adopt is safe: "
            "`chezmoi add` is idempotent)."
        )
        return AdoptResult(tracked=True, synced=False, warning=warning)

    return AdoptResult(tracked=True, synced=True, commit_sha=sha)
