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

Concurrency — TWO layers, both here so no caller can forget either:

- :func:`commit` takes ``paths``: with a pathspec, ``git commit -- <paths>``
  carries only its own files. This is the layer that closes the
  index-sweep interleave (a racing index-wide ``git commit`` absorbing
  someone else's staged work), and it is the one doing most of the work.
- :func:`commit_lock` serializes the one hazard a pathspec CANNOT survive:
  ``git pull --rebase --autostash`` (:func:`push_with_retry`'s non-FF
  fallback) rewrites the index AND the worktree out from under whoever
  else is mid-write. H-5 ("producers commit their own writes") silently
  assumed a single writer; M3 broke that by adding two BACKGROUND
  committers to the ledger — the worker (Popen-detached, kicked by every
  teach/import) and the nightly miner — alongside the foreground verbs.
  ``sentinel.hold()`` does not serialize them (it is advisory: a
  pre-existing hold returns ``owned=False`` and the caller CONTINUES), and
  ``worker.lock`` excludes worker-vs-worker only.

**The lock's scope, re-derived from a probe (audit 2026-07-16, round 3).**
The lock used to be held across the WHOLE verb including the push, which
protected nothing there (``git push`` touches no index) while the thing
that DOES rewrite the index — the rebase — ran unlocked in host repos.
Probed in a real sandbox (bare remote + third clone pushing a conflicting
edit, /tmp probe p3):

1. Inside a pathspec ``git commit`` git holds ``index.lock``, so a racing
   autostash there merely FAILS ("fatal: Cannot autostash"). Not the
   hazard.
2. The real window is between a verb's first ledger mutation (``git mv``
   / a record rewrite) and its ``commit`` — no git process holds the
   index there. A racer entering ``pull --rebase --autostash`` in that
   window stashed the staged rename; the autostash restore CONFLICTED, so
   the work was left in an orphaned stash, and the victim's pathspec
   commit then landed only half the rename: **HEAD ended with the record
   in BOTH pending/ and resolved/, `git status` clean, exit 0** — the
   record silently both pending and resolved forever, the rewrite lost.

Hence the scope implemented here: the lock covers [first mutation →
commit] (short, local, no network) and [pull --rebase --autostash →
re-push] in the repo being rebased (:func:`push_with_retry` takes it
itself, so ledger and HOST are both covered and no caller can forget).
The ordinary ``git push`` is OUTSIDE the lock.

Every git subprocess carries a ``timeout`` (:data:`GIT_LOCAL_TIMEOUT` /
:data:`GIT_NETWORK_TIMEOUT`); a timeout raises :class:`GitOpsError`
rather than hanging — before this, ``subprocess.run`` had no timeout at
all and a wedged push blocked a ``teach`` indefinitely (probed
2026-07-16: 120 s and counting).

Nothing here decides WHAT to commit — verbs.py owns sequences; this module
owns the git mechanics.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

__all__ = [
    "EXIT_GIT_FAILED",
    "head_sha",
    "EXIT_HALF_WRITTEN",
    "EXIT_PUSH_FAILED",
    "EXIT_REBASE_CONFLICT",
    "COMMIT_LOCK_TIMEOUT",
    "GIT_LOCAL_TIMEOUT",
    "GIT_NETWORK_TIMEOUT",
    "GitOpsError",
    "HalfWrittenError",
    "PushResult",
    "check_ignore",
    "commit",
    "commit_lock",
    "commit_lock_path",
    "dirty_paths",
    "has_remote",
    "host_lock",
    "host_lock_path",
    "known_paths",
    "paths_dirty",
    "push_if_remote",
    "push_pending",
    "push_with_retry",
    "unpushed_commits",
    "stage",
    "staged_diff",
    "toplevel",
]

#: Distinct non-zero exits (08 §1 Push pin: failures are loud AND distinct).
EXIT_PUSH_FAILED = 3
EXIT_REBASE_CONFLICT = 4

#: A git operation FAILED or timed out — a :class:`GitOpsError` reached a
#: dispatch surface (lock timeout, wedged git, unwritable repo). Distinct
#: from a push failure (3): there, the commit landed and `self-learn push`
#: republishes it; here, the write itself may not have happened.
#: Added 2026-07-16 (audit BLOCKER B) — before it, every one of these was
#: an uncaught traceback, and a `teach` whose commit failed exited 0.
#:
#: **6 means NOTHING WAS WRITTEN** — that is the whole content of the code,
#: and it is a promise every surface returning it must be able to keep
#: (audit 2026-07-16 round 7 BLOCKER 2). It is therefore the code for a
#: failure that happened BEFORE the first mutation: a lock timeout taken
#: ahead of the write, a home that is not a repo. A git failure AFTER a
#: mutation is a DIFFERENT fact and gets :data:`EXIT_HALF_WRITTEN`.
EXIT_GIT_FAILED = 6

#: A git failure struck AFTER the repo was mutated: the write landed on
#: disk / in the index but its commit did not. The surface that returns
#: this MUST print the exact repair command — the state is recoverable but
#: only by hand, and a blind retry is NOT safe (audit 2026-07-16 round 7
#: BLOCKER 2, the probe: `reject` with a commit-failing git exited 6 while
#: the record had ALREADY moved pending→resolved, so the documented "safe
#: to retry" then failed with 64 "record not found" — one code, two
#: opposite states, and the doc could only describe one of them).
EXIT_HALF_WRITTEN = 7


#: Wall-clock ceiling on a LOCAL git call (add/commit/mv/rev-parse/…).
#: Generous by orders of magnitude for the sizes involved; its only job is
#: to convert "wedged forever" into a loud error.
GIT_LOCAL_TIMEOUT = 30.0

#: Wall-clock ceiling on a git call that talks to a remote (push/pull).
#: The ledger's remote is a small private repo — a minute is already
#: pathological, and hanging is strictly worse than failing (a kept commit
#: is republished by `self-learn push`; a hung `teach` blocks the session).
GIT_NETWORK_TIMEOUT = 60.0


class GitOpsError(Exception):
    """A local git operation (stage/commit/lock) failed, OR any git call
    exceeded its timeout — always an error. Ordinary push FAILURES are not
    exceptions (commit kept, loud result instead); a push TIMEOUT is one,
    because a hang is not a result.

    Every CLI dispatch surface maps this to ``EXIT_GIT_FAILED`` and never
    lets it reach a traceback (audit 2026-07-16 BLOCKER B: a second
    process merely holding the lock made reject/push/recompile and the
    detached worker die with a stack dump).

    This class carries NO claim about what was written — see
    :class:`HalfWrittenError` for the subclass that does. Raising the base
    class means "the git op failed"; whether the repo was already mutated
    is the VERB's fact, and only the verb may state it."""


class HalfWrittenError(GitOpsError):
    """A git failure that struck AFTER this repo was already mutated: the
    write is on disk / staged, its commit is not (audit 2026-07-16 round 7
    BLOCKER 2).

    Constructed by the VERB, never by this module — the module cannot know
    where a caller's first mutation was, and the round-3 fix that made
    `commit_lock`'s error text stop claiming "nothing was written" was
    exactly that lesson. What the module CAN own is the type and the
    shape: a distinct class so dispatch maps it to
    :data:`EXIT_HALF_WRITTEN` instead of :data:`EXIT_GIT_FAILED`, and a
    mandatory ``repair`` string so no surface can report this state
    without also saying how to fix it.

    ``repair`` is the literal command a human can paste."""

    def __init__(self, message: str, *, repair: str) -> None:
        super().__init__(message)
        self.repair = repair

    @staticmethod
    def for_commit(
        repo: Path,
        message: str,
        paths: Iterable[Path | str],
        cause: Exception,
    ) -> "HalfWrittenError":
        """The standard shape: <repo> was mutated for the commit
        ``message``, and the commit failed with ``cause``. The repair is
        the same pathspec commit the verb was about to make."""
        spec = " ".join(str(p) for p in paths)
        return HalfWrittenError(
            f"{cause}",
            repair=f"git -C {repo} add -- {spec} && "
            f"git -C {repo} commit -m {message!r} -- {spec}",
        )


def _git(
    repo: Path, *args: str, timeout: float = GIT_LOCAL_TIMEOUT
) -> subprocess.CompletedProcess:
    """One git call, always bounded. ``subprocess.run`` with no timeout is
    why "blocking with a sane timeout" was fiction (audit 2026-07-16)."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitOpsError(
            f"git {' '.join(args)} in {repo} exceeded {timeout:g}s and was "
            f"killed{_index_lock_note(repo)}; nothing further was attempted"
        ) from exc


def _index_lock_note(repo: Path) -> str:
    """Name the stranded ``index.lock`` precisely, if there is one.

    **Judged, not overlooked (audit 2026-07-16 round 7 MINOR).** Killing a
    git that blew its timeout can strand ``.git/index.lock``, and nothing
    cleans it: every subsequent git in that repo then fails until a human
    removes it. The tempting fix — delete it when it looks stale and ours
    — is REFUSED here, and the asymmetry is the reason:

    - the benefit is self-healing a rare wedge whose manual repair is one
      obvious ``rm``;
    - the cost of getting it wrong is deleting a LIVE git's lock and
      corrupting the index — and we cannot reliably tell. We do not own
      the repo (a human's own ``git commit`` in a host takes no lock of
      ours, and hosts are repos people work in), git spawns children we
      never see, and mtime is a guess, not evidence. "Clearly stale and
      clearly ours" is not a state this process can establish.

    So: never delete, but never be vague either. The old text said the
    tree "may hold a stale index.lock" — a hedge the reader has to go
    check. This looks, and either names the exact path with the exact
    command or says nothing at all. Reading is free; guessing is not."""
    try:
        proc = _git_nolock(repo, "rev-parse", "--git-dir")
        if proc.returncode != 0:
            return ""
        gitdir = Path(proc.stdout.strip())
        if not gitdir.is_absolute():
            gitdir = Path(repo) / gitdir
        lock = gitdir / "index.lock"
        if not lock.exists():
            return ""
        return (
            f" and left {lock} behind — every later git in this repo will "
            f"fail until it is removed. If no other git is running here: "
            f"rm {lock}"
        )
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_nolock(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """A short git call for error-reporting only — never raises, so a
    diagnostic can never become the exception it is describing."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=5,
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


def staged_diff(repo: Path, paths: Iterable[Path | str] = ()) -> str:
    """``git diff --cached [-- <paths>]`` — the pre-commit diff of what a
    verb staged. T8's ``teach --route`` prints this (08 §1 `teach --route`
    pin: prints the diff as it applies)."""
    args = ["diff", "--cached"]
    path_args = [str(p) for p in paths]
    if path_args:
        args += ["--", *path_args]
    return _git_ok(repo, *args).stdout


#: Seconds :func:`commit_lock` waits before giving up. Sized from the
#: LONGEST legitimate hold, which is the rebase path in
#: :func:`push_with_retry`: ``pull --rebase --autostash`` + the re-push =
#: 2 × :data:`GIT_NETWORK_TIMEOUT`, both now bounded. 150 > 120 leaves
#: slack, so a timeout here means a holder is genuinely wedged rather than
#: merely busy. (The COMMON path — [mutation → commit] — is local and
#: measured in milliseconds; nobody waits on that.)
#:
#: **It does NOT cover three-deep contention, deliberately** (audit
#: 2026-07-16 round 7 MINOR — judged: leave it, and say why). Two stacked
#: rebase holders can legitimately hold 240 s > 150, and flock does not
#: queue fairly, so a third waiter can time out while everyone is merely
#: busy. Raising the ceiling to cover it was rejected on the trade:
#:
#: - a spurious timeout costs a CLEAN REFUSAL — nothing written, one
#:   sentence, re-run it. That is only true because of the round-7
#:   invariant (the lock precedes the first mutation); before it, this
#:   number was a correctness parameter and under-sizing it stranded
#:   records. Now it is a LATENCY parameter.
#: - a longer ceiling costs a human's foreground `teach`/`reject` hanging
#:   for that many seconds — and 150 s is already at the edge of what an
#:   interactive verb may take.
#:
#: So the bet is deliberate: prefer an occasional "try again" over a
#: guaranteed multi-minute hang. Three producers rebasing at once is also
#: not a state to accommodate quietly — it means three non-fast-forward
#: pushes are racing, and the question to ask is why, not how to wait
#: longer.
#:
#: flock is released by the kernel on process death, so a crashed holder
#: can never leave a stale lock — there is nothing to break, only to
#: report.
#:
#: A timeout here is safe for every caller that obeys the invariant (the
#: lock opens before the first mutation, so nothing was written) — but
#: this module still does not SAY so, and that is deliberate. It cannot
#: know: it has no idea what its caller did before calling. The claim is
#: the caller's to make, and callers get it wrong — `teach` used to write
#: the record BEFORE committing it, so "nothing was written" was a lie
#: there (audit 2026-07-16 BLOCKER B — the sentence used to live in the
#: error text below, where it was attached to every caller
#: indiscriminately; round 7 moved teach's lock ahead of its write, which
#: is what finally made the sentence TRUE for teach — by changing the
#: code, not the text).
#:
#: The invariant is enforced structurally, not by this comment:
#: tests/test_lock_invariant.py walks the package's call graph and fails
#: when any entrypoint can reach a mutation without passing through here.
COMMIT_LOCK_TIMEOUT = 150.0

#: Lock paths this PROCESS already holds. flock() associates a lock with an
#: open file *description*, so a nested acquire on a second fd would block
#: on ourselves forever; nesting is a pass-through instead (audit
#: 2026-07-16 BLOCKER 4: verbs commit to the ledger and then to a host, and
#: future callers must not be able to self-deadlock by composing).
_held_locks: set[str] = set()


def commit_lock_path(repo: Path) -> Path:
    """Where the commit lock for *repo* lives: ``<git-dir>/self-learn.
    commit.lock``, derived from the repo itself (never from the ledger
    home) so the SAME rule covers ledger and host repos — the contended
    resource is a repo's index, so the lock belongs to the repo.

    ``--git-common-dir`` (not ``--git-dir``) so every linked worktree of
    one repo shares a single lock: worktrees have separate indexes but the
    commits land in one object store and one branch namespace.

    For host repos the guarantee is partial by design: it serializes
    self-learn's own writers (a route's host phase vs. recompile), but a
    human's ``git add`` in their own repo takes no lock of ours. That is
    exactly why :func:`commit` also scopes by pathspec — layer (b) is what
    holds when layer (a) cannot."""
    proc = _git(repo, "rev-parse", "--git-common-dir")
    if proc.returncode != 0:
        raise GitOpsError(f"{repo} is not a git repository")
    gitdir = Path(proc.stdout.strip())
    if not gitdir.is_absolute():
        gitdir = Path(repo) / gitdir
    return gitdir / "self-learn.commit.lock"


@contextlib.contextmanager
def _flock_lock(path: Path, timeout: float, wedged_by: str) -> Iterator[None]:
    """The shared flock body behind both :func:`commit_lock` and
    :func:`host_lock` — one implementation, one :data:`_held_locks`
    bookkeeping (U-hostmode §4.3: a plain host's lock is a REAL flock,
    not an omission, so it shares this exactly rather than reimplementing
    it). ``wedged_by`` names what a timeout blames, in the caller's own
    words."""
    key = str(path)
    if key in _held_locks:  # already ours — nesting must not self-deadlock
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "w", encoding="utf-8")
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise GitOpsError(
                        f"{wedged_by} lock {path} still held after "
                        f"{timeout:g}s — another self-learn producer "
                        f"(worker/miner/verb) is wedged mid-{wedged_by}"
                    ) from None
                time.sleep(0.02)
        _held_locks.add(key)
        try:
            with contextlib.suppress(OSError):
                fh.write(f"{os.getpid()}\n")
                fh.flush()
            yield
        finally:
            _held_locks.discard(key)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


@contextlib.contextmanager
def commit_lock(repo: Path, *, timeout: float | None = None) -> Iterator[None]:
    """Serialize a repo's INDEX-AND-WORKTREE-mutating critical sections
    against every other self-learn producer writing *repo*.

    Two — and only two — sections take this lock (see the module docstring
    for the probe that fixed the scope; audit 2026-07-16 round 3):

    1. **[first mutation → commit]**, held by each producer. It must open
       BEFORE the first mutation, not at ``commit()``: ``resolve_record``
       ``git mv``s (staging a rename instantly) and rewrites record files
       in the worktree, and BOTH are things a racing autostash sweeps
       away. Short, local, no network.
    2. **[pull --rebase --autostash → re-push]**, taken by
       :func:`push_with_retry` itself, in the repo being rebased — the
       ledger for a ledger push, the HOST for a host push. That is where
       the index actually gets rewritten, so that is what needs exclusion.

    Explicitly NOT covered: the ordinary ``git push``, which touches no
    index and no worktree, and the compile/host phase of a verb, which
    touches a different repo. Holding those was the old whole-verb scope:
    it serialized the network (making a wedged remote block every other
    producer for the length of a TCP timeout) while leaving the actual
    hazard — a HOST rebase — unlocked.

    Blocking with a bounded wait; on timeout raises :class:`GitOpsError`
    rather than proceeding, because proceeding IS the race this closes.
    Re-entrant within one process (see :data:`_held_locks`), so a verb may
    hold it across a helper that acquires it again.

    ``timeout=None`` reads :data:`COMMIT_LOCK_TIMEOUT` at CALL time, not at
    def time — a default argument would freeze the value at import and make
    the constant unadjustable by anything (including a test that wants to
    prove the timeout path without sitting for 150 s)."""
    if timeout is None:
        timeout = COMMIT_LOCK_TIMEOUT
    with _flock_lock(commit_lock_path(repo), timeout, "commit"):
        yield


def host_lock_path(path: Path, mode: str) -> Path:
    """U-hostmode §4.3: where a HOST's commit lock lives, by mode.

    ``mode == "git"`` — byte-identical to :func:`commit_lock_path` (UN8):
    ``<git-common-dir>/self-learn.commit.lock``, derived from the repo
    itself.

    ``mode == "plain"`` — a plain host has no ``.git`` to hold a lock
    file, so the lock moves to the global cache dir, keyed by the SAME
    slug shape ``hosts.slug_for`` uses (the sentinel's own reasoning,
    ``sentinel.py``: global and NOT ledger-home-namespaced, because a host
    can be registered by more than one ledger home and the contended
    resource is the HOST's file, not any one home's view of it):
    ``${XDG_CACHE_HOME:-~/.cache}/self-learn/host-<slug>.commit.lock``."""
    if mode == "git":
        return commit_lock_path(Path(path))
    if mode == "plain":
        # N-1 (code gate r1 fold): `hosts.slug_for` used to be
        # duplicated here verbatim (as `_plain_host_cache_key`) to dodge
        # a `gitops`<->`hosts` import cycle (`hosts.py` already imports
        # `gitops`) — the SAME dodge `hosts.host_remove` and
        # `reconcile._is_reconcilable` already use elsewhere in this
        # codebase: a function-LOCAL import, resolved only once both
        # modules are fully loaded, instead of a module-level one two
        # copies of one slug, free to drift.
        from .hosts import slug_for

        cache_env = os.environ.get("XDG_CACHE_HOME")
        base = Path(cache_env).expanduser() if cache_env else Path("~/.cache").expanduser()
        slug = slug_for(path)
        return base / "self-learn" / f"host-{slug}.commit.lock"
    raise GitOpsError(f"unknown host mode {mode!r} — expected 'git' or 'plain'")


@contextlib.contextmanager
def host_lock(path: Path, mode: str, *, timeout: float | None = None) -> Iterator[None]:
    """U-hostmode §4.3/§4.5b: THE host-side lock, real in both modes —
    a mode DISPATCH, never an omission for plain hosts. Shares
    :func:`commit_lock`'s exact flock body (:func:`_flock_lock`) so a
    plain host's serialization guarantee is the same primitive a git
    host's always had, not a weaker cousin of it.

    Callers take this in the CALLEE, at entry, BEFORE the first ledger
    mutation of the resolution it is protecting (REC12) — never
    caller-side, which would leave some host-write paths (``supersede``,
    ``graduate``) writing the host unlocked. Re-entrant within one
    process via the SAME :data:`_held_locks` set :func:`commit_lock`
    uses, keyed by the resolved lock PATH — so a git-mode host's
    ``host_lock`` and its ``commit_lock`` (git host, same repo) name the
    SAME file and correctly pass through one another."""
    if timeout is None:
        timeout = COMMIT_LOCK_TIMEOUT
    with _flock_lock(host_lock_path(path, mode), timeout, "host"):
        yield


def known_paths(repo: Path, paths: Iterable[Path | str]) -> list[str]:
    """The subset of *paths* a pathspec commit may name: those that exist
    in the worktree, OR that git knows (index or HEAD).

    The HEAD half is load-bearing and non-obvious — verified by probe
    (2026-07-16): after ``git mv old new`` the OLD path is gone from the
    worktree AND from the index, surviving only in HEAD, yet it MUST ride
    the pathspec. Naming only the new half commits the addition and orphans
    the deletion in the index (probed: leftover ``D old``) — a rename split
    across two commits. Conversely a pathspec naming a never-tracked absent
    path makes git fail the whole commit ("did not match any file(s) known
    to git"), so unknown paths are dropped rather than passed through."""
    out: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.exists():
            out.append(str(p))
            continue
        # --with-tree=HEAD widens ls-files from the index to the index UNION
        # HEAD, which is what catches the git-mv'd / git-rm'd old path.
        probe = _git(
            repo, "ls-files", "--error-unmatch", "--with-tree=HEAD", "--", str(p)
        )
        if probe.returncode == 0:
            out.append(str(p))
    return out


def commit(
    repo: Path,
    message: str,
    body: str | None = None,
    paths: Iterable[Path | str] | None = None,
) -> str:
    """Commit with the pinned subject; ``body`` (the resolution note)
    becomes the commit body. Returns the new commit's sha.

    ``paths`` scopes the commit to its OWN files via ``git commit --
    <paths>`` (audit 2026-07-16 BLOCKER 4, layer b): with two background
    committers now sharing the ledger, a bare index-wide ``git commit``
    lets whoever fires first absorb everyone else's staged work. Pass the
    paths the caller staged; they are filtered through :func:`known_paths`
    (see it for the git-mv rename subtlety). Omitting ``paths`` keeps the
    legacy index-wide behavior — correct only under :func:`commit_lock`.

    Note ``git commit -- <paths>`` commits those paths' WORKTREE content,
    bypassing the index, and leaves everyone else's staged entries staged
    (probed 2026-07-16) — which is precisely the isolation wanted here."""
    args = ["commit", "-q", "-m", message]
    if body:
        args += ["-m", body]
    if paths is not None:
        scoped = known_paths(repo, paths)
        if not scoped:
            raise GitOpsError(
                f"commit {message!r}: none of the given paths are known to git"
            )
        args += ["--", *scoped]
    _git_ok(repo, *args)
    return _git_ok(repo, "rev-parse", "HEAD").stdout.strip()


def head_sha(repo: Path) -> str:
    """The repo's current ``HEAD`` sha — U-verbs' `note --key`
    already-applied leg reads this to report a no-op success without
    opening the commit lock (nothing changed, so nothing to stage)."""
    return _git_ok(repo, "rev-parse", "HEAD").stdout.strip()


def has_remote(repo: Path) -> bool:
    """True iff the repo has any configured remote — the best-effort-push
    gate for producer commits (doc 13 H-5: producers push their own
    writes; a remoteless sandbox/bootstrap ledger simply keeps them)."""
    proc = _git(repo, "remote")
    return proc.returncode == 0 and bool(proc.stdout.strip())


def toplevel(path: Path | str) -> Path | None:
    """``git rev-parse --show-toplevel`` for *path*'s repo, or None when
    outside any repo — the project-path resolver teach/import use
    (doc 13 §3: producers know the path; teach uses cwd's toplevel)."""
    proc = _git(Path(path), "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return Path(out) if out else None


def paths_dirty(repo: Path, target: Path | str) -> bool:
    """True iff ``target`` has uncommitted changes (tracked-modified OR
    untracked) — the dirty-compile-target abort predicate."""
    proc = _git_ok(repo, "status", "--porcelain", "--", str(target))
    return bool(proc.stdout.strip())


def dirty_paths(repo: Path, target: Path | str) -> list[str]:
    """The porcelain-reported paths under ``target`` — the file-list
    companion to :func:`paths_dirty` (U20: the commit-drift verb's
    ``--dry-run --json`` mode has no other data source, gate m6)."""
    proc = _git_ok(repo, "status", "--porcelain", "--", str(target))
    return [line[3:] for line in proc.stdout.splitlines() if line.strip()]


def check_ignore(repo: Path, target: Path | str) -> bool:
    """True iff ``git`` reports ``target`` ignored in ``repo`` (A2 §6,
    P-A3: the ``CLAUDE.local.md`` privacy guard). ``git check-ignore``
    exits 0 when the path IS ignored, 1 when it is not (an ordinary,
    non-error outcome — never raised), and >1 on a real usage error, which
    DOES raise via :func:`_git_ok`. Deliberately not a substring scan of
    ``.gitignore`` (P-A3 mechanism pin): this honors nested
    ``.gitignore`` files, negations, and the user's global excludes."""
    proc = _git(repo, "check-ignore", "-q", "--", str(target))
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    raise GitOpsError(
        f"git check-ignore failed: {(proc.stderr or proc.stdout).strip()}"
    )


@dataclass(frozen=True)
class PushResult:
    """Outcome of one push attempt (with the pinned retry). ``skipped``
    marks the no-remote case (:func:`push_if_remote`): nothing to publish
    to, which is success-shaped but must never render as "pushed"."""

    ok: bool
    retried: bool = False  # the pull-rebase-retry path was taken
    rebase_conflict: bool = False
    detail: str = ""
    skipped: bool = False

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
    """The pinned per-verb push. Never raises for push FAILURES — the
    commit is kept and the result says loudly what happened. A push
    TIMEOUT does raise :class:`GitOpsError` (a hang is not a result).

    Lock discipline (audit 2026-07-16 round 3 — the re-scope):

    - The first ``git push`` runs with NO lock. It touches neither index
      nor worktree, so serializing it only made a slow remote everybody
      else's problem.
    - The rebase fallback runs UNDER ``commit_lock(repo)`` — ``pull
      --rebase --autostash`` rewrites this repo's index and worktree, and
      probing showed an unlocked one silently splitting a racing verb's
      ``git mv`` rename in half (module docstring). Taking the lock HERE
      rather than at the call sites is what finally covers HOST pushes:
      every host rebase used to run with no host lock at all, which is the
      exact hazard the lock was justified by."""
    first = _git(repo, "push", "-q", timeout=GIT_NETWORK_TIMEOUT)
    if first.returncode == 0:
        return PushResult(ok=True)

    # Non-FF (or any push failure): pull --rebase --autostash, retry ONCE.
    # Re-entrant if the caller already holds it (e.g. `self-learn push`
    # taking it for a repo it is also committing to).
    with commit_lock(repo):
        pull = _git(
            repo, "pull", "--rebase", "--autostash", "-q",
            timeout=GIT_NETWORK_TIMEOUT,
        )
        if pull.returncode != 0:
            if _rebase_in_progress(repo):
                _git(repo, "rebase", "--abort")
                print(
                    "self-learn: PUSH BLOCKED — rebase conflict while syncing "
                    "with the remote. The rebase was aborted and your commit is "
                    "KEPT locally. Resolve the divergence manually (git pull "
                    "--rebase), then run `self-learn push`.",
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

        second = _git(repo, "push", "-q", timeout=GIT_NETWORK_TIMEOUT)
    if second.returncode == 0:
        return PushResult(ok=True, retried=True)
    print(
        "self-learn: PUSH FAILED after rebase-retry. Your commit is KEPT "
        "locally; run `self-learn push` to retry.",
        file=sys.stderr,
    )
    return PushResult(ok=False, retried=True, detail=second.stderr.strip())


def push_if_remote(repo: Path) -> PushResult:
    """:func:`push_with_retry` behind the :func:`has_remote` guard — the
    policy every producer uses (audit 2026-07-16 MINOR 7: route /
    route_direct / supersede pushed unguarded, so on a remote-less ledger
    every route exited 3 with a loud PUSH FAILED despite perfect
    commits)."""
    if not has_remote(repo):
        return PushResult(ok=True, skipped=True, detail="no remote configured")
    return push_with_retry(repo)


def unpushed_commits(repo: Path) -> int | None:
    """How many local commits the current branch has beyond its upstream.
    None = unanswerable (no remote, no upstream, detached HEAD) — the
    caller treats that as "nothing to retry here"."""
    if not has_remote(repo):
        return None
    proc = _git(repo, "rev-list", "--count", "@{upstream}..HEAD")
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def push_pending(repo: Path) -> PushResult:
    """The bare ``self-learn push`` verb: publish whatever local commits
    exist, with the same pinned retry policy — behind the same no-remote
    guard as every producer (audit 2026-07-16 MAJOR E's class: on the
    remote-less ledger doc 13 §7.1 step 5 creates on purpose, this
    reported a loud "PUSH FAILED" for the entirely normal state of having
    nowhere to publish to yet)."""
    return push_if_remote(repo)
