"""Ledger-home resolution and bucket discovery (doc 13 §3 layout).

Pins (doc 13 §1 Q1 / §3; H-1):
- Ledger home: ``SELF_LEARN_HOME`` env var, default ``~/.self-learn``,
  expanduser'd — explicit, never inferred from cwd. All bucket paths
  resolve against it.
- Bucket discovery on the independent-home layout:
  ``skills/<name>/`` → one skill bucket each (name = the dir name);
  ``projects/<slug>/`` → one project bucket each (name = the slug dir,
  path recorded in the sibling ``meta.yaml`` — the slug alone is lossy);
  ``user/`` → the single user bucket. Only dirs that exist.

Queue semantics (deferred_until hiding, eligibility) live in
:mod:`self_learn.ledger_ops` — :func:`Bucket.pending_files` is the raw
directory listing that feeds them, never a queue definition of its own.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import gitops
from .hosts import is_repo_root

DEFAULT_HOME = "~/.self-learn"

#: The layout dirs + registry that a bootstrapped home has (doc 13 §3).
_LAYOUT = ("skills", "projects", "user", "telemetry")

HOME_STATES = ("ok", "missing", "not-a-repo", "uninitialized")

#: A surface asked about a home that is missing / not a git repo. Distinct
#: from "empty ledger" (0) and from a refusal (1): the question could not be
#: answered at all. It lives HERE, beside :func:`home_state`, because it is
#: a home fact — `cli` and `teach` both import it rather than each pinning
#: their own integer (audit 2026-07-16 MINOR G: they had drifted, `teach`
#: returning 2 for a bad home where all eight other surfaces returned 5).
EXIT_NO_HOME = 5


def resolve_home() -> Path:
    """Resolve the ledger home: $SELF_LEARN_HOME, else the default, expanded."""
    raw = os.environ.get("SELF_LEARN_HOME") or DEFAULT_HOME
    return Path(raw).expanduser()


def home_state(home: Path | str | None = None) -> str:
    """Classify the resolved home — the silent-failure gate (audit
    2026-07-16 BLOCKER 11).

    ``discover_buckets`` globs; a home that does not exist simply globs to
    ``[]``, so every read surface rendered a confident all-clear ("0
    pending", exit 0) for a home that was never there — a wrong or unset
    ``SELF_LEARN_HOME`` (a systemd unit resolving a different home than
    the shell is the live case) made the whole ledger invisible with no
    error anywhere. Zero pending and no ledger at all are opposite facts
    and must never render the same.

    States: ``missing`` (no such dir) · ``not-a-repo`` (a dir, but not a
    git work tree — the ledger IS a git repo, doc 13 §2) ·
    ``uninitialized`` (a git repo with no layout dirs and no hosts.yaml —
    never bootstrapped) · ``ok``. An initialized home with zero records is
    ``ok``: an empty ledger is a legitimate, and quiet, state."""
    home = Path(home) if home is not None else resolve_home()
    if not home.is_dir():
        return "missing"
    proc = subprocess.run(
        ["git", "-C", str(home), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return "not-a-repo"
    if any((home / d).is_dir() for d in _LAYOUT) or (home / "hosts.yaml").is_file():
        return "ok"
    return "uninitialized"


def home_state_message(state: str, home: Path | str) -> str:
    """The loud, actionable line every read surface prints for a bad home
    (and every write surface refuses with)."""
    if state == "missing":
        return (
            f"ledger home {home} does not exist — self-learn cannot see any "
            "records (this is NOT an empty ledger). Check $SELF_LEARN_HOME, "
            "or bootstrap it with `self-learn init` (or clone the ledger "
            "repo there)."
        )
    if state == "not-a-repo":
        return (
            f"ledger home {home} is not a git repo — the ledger is a git "
            "repo (doc 13 §2) and every producer commits its own writes "
            "(H-5). Check $SELF_LEARN_HOME, or run `self-learn init` to "
            "bootstrap it (or clone the ledger repo there)."
        )
    if state == "uninitialized":
        return (
            f"ledger home {home} has no layout dirs and no hosts.yaml — it "
            "was never bootstrapped (doc 13 §3). Clone the ledger repo, or "
            "create skills/ projects/ user/ telemetry/ + register a host "
            "(`self-learn host add <path>`)."
        )
    return f"ledger home {home} ok"


@dataclass(frozen=True)
class Bucket:
    """One ledger bucket: its directory, scope, and display name."""

    path: Path
    scope: str  # "skill" | "project" | "user"
    name: str

    def pending_files(self) -> list[Path]:
        """Raw listing: every pending/*.md file, sorted by name. Queue
        membership (deferral hiding) is computed in ledger_ops.queue()."""
        pending_dir = self.path / "pending"
        if not pending_dir.is_dir():
            return []
        return sorted(p for p in pending_dir.glob("*.md") if p.is_file())


def discover_buckets(home: Path | None = None) -> list[Bucket]:
    """Return every existing bucket under the ledger home (may be empty).

    Skill buckets under ``skills/``, per-project buckets under
    ``projects/`` (named by slug), and the single ``user/`` bucket.
    """
    if home is None:
        home = resolve_home()
    buckets: list[Bucket] = []
    for p in sorted(home.glob("skills/*")):
        if p.is_dir():
            buckets.append(Bucket(path=p, scope="skill", name=p.name))
    for p in sorted(home.glob("projects/*")):
        if p.is_dir():
            buckets.append(Bucket(path=p, scope="project", name=p.name))
    user = home / "user"
    if user.is_dir():
        buckets.append(Bucket(path=user, scope="user", name="user"))
    return buckets


# --------------------------------------------------------------- init verb


#: C1 §2.2 P-C1.15: mirrors hosts.py's ``INIT_COMMIT_SUBJECT`` pattern — a
#: pinned, greppable subject for the ``--allow-empty`` root/top-up commit.
#: No keep-files (empty dirs are recreated by a future `init`, never
#: phantom buckets — ``discover_buckets`` filters on ``is_dir()``).
INIT_COMMIT_SUBJECT = "self-learn: init ledger home"


class InitError(Exception):
    """``self-learn init`` refused — the target is not a place it may
    write (C1 §2.2 steps 2/4), or a git operation it ran failed."""


@dataclass(frozen=True)
class InitResult:
    """What :func:`init_home` did, for the CLI's one-line report."""

    path: Path
    created_repo: bool  # step 3 or step 5: `git init` ran here
    added_dirs: tuple[str, ...]  # `_LAYOUT` dirs newly created (any step)
    made_head: bool  # an `--allow-empty` commit was made
    already_complete: bool  # step 6, nothing missing, HEAD already existed


def _is_empty_dir(path: Path) -> bool:
    """True iff *path* has zero entries; raises :class:`InitError` when
    the directory cannot be read. An unreadable dir cannot be PROVEN
    empty, and must not be reported as "non-empty" either — that message
    (step 4) names foreign files that may not exist. Refuse, in its own
    words (C1 §2.2 P-C1.24's sibling: refuse rather than guess)."""
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError as exc:  # NIT 6: refuse, but never claim "non-empty"
        raise InitError(
            f"cannot read {path}: {exc.strerror or exc} — self-learn "
            "init cannot tell whether it is empty; fix its permissions, "
            "then re-run"
        ) from exc
    return False


def _git_init(target: Path) -> None:
    # Delta code gate: `git init` names the target as an ARGUMENT (the
    # repo does not exist yet, so `-C` cannot address it) — the one call
    # here that cannot go through gitops._git. Bounded explicitly.
    try:
        proc = subprocess.run(
            ["git", "init", str(target)],
            capture_output=True,
            text=True,
            timeout=gitops.GIT_LOCAL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise InitError(f"git init {target} failed: {exc}") from exc
    if proc.returncode != 0:
        raise InitError(f"git init {target} failed: {proc.stderr.strip()}")


def _has_head(target: Path) -> bool:
    # Via gitops._git: bounded, and VISIBLE to test_lock_invariant's
    # structural analysis, which parses `_git`/`_git_ok` calls only. Raw
    # subprocess here made the whole init path invisible to the invariant
    # that module exists to enforce (delta code gate).
    return gitops._git(target, "rev-parse", "--verify", "-q", "HEAD").returncode == 0


def _commit_allow_empty(target: Path) -> None:
    # Via gitops._git — this is THE call the lock invariant cares about
    # (step 6 commits a pre-existing repo). Raw subprocess made it
    # invisible to the structural analysis (delta code gate).
    proc = gitops._git(
        target, "commit", "--allow-empty", "-m", INIT_COMMIT_SUBJECT
    )
    if proc.returncode != 0:
        raise InitError(
            f"{target} was initialized but the empty root commit failed: "
            f"{proc.stderr.strip()} — fix your git identity (or commit in "
            "the repo yourself), then re-run `self-learn init`"
        )


def _create_layout(target: Path) -> tuple[str, ...]:
    """Create whatever `_LAYOUT` dirs are missing at *target*; return the
    ones actually created (C1 §2.2 P-C1.14: per-directory, never per-state
    — this is safe to call on ANY repo shape, including one that already
    has some of the four)."""
    created = []
    for name in _LAYOUT:
        d = target / name
        if not d.is_dir():
            try:
                d.mkdir()
            except OSError as exc:  # MAJOR 1: never a raw traceback
                raise InitError(
                    f"cannot create {d}: {exc.strerror or exc} — the "
                    "ledger home is not writable; fix its permissions, "
                    "then re-run `self-learn init`"
                ) from exc
            created.append(name)
    return tuple(created)


def init_home(path: Path | str) -> InitResult:
    """``self-learn init`` (C1 §2.2): bootstrap *path* as the ledger home,
    following the ratified ``host add --init`` precedent's shape
    (P-C1.12/P-C1.13 — confined to the ledger home) but departing from its
    "creates nothing" rule where a brand-new ledger requires it.

    Step sequence (exact — C1 §2.2; the caller has already echoed *path*
    per P-C1.10, step 1):

    2. *path* exists (``os.path.lexists`` — P-C1.24: a DANGLING SYMLINK
       must refuse here, not fall through to a raw ``mkdir`` error) and is
       NOT a directory (regular file, FIFO, socket, device node, dangling
       symlink) → refuse.
    3. *path* is absent → create it, ``git init``, all four `_LAYOUT`
       dirs, initial ``--allow-empty`` commit. Done.
    4. :func:`~self_learn.hosts.is_repo_root` is False and the dir is
       NON-EMPTY → refuse. Never ``git init`` over foreign files.
    5. :func:`~self_learn.hosts.is_repo_root` is False and the dir is
       EMPTY → ``git init`` in place, layout, commit (a nested empty dir
       lands here and gets its own repo — doc 13 §3 blesses nested init).
    6. :func:`~self_learn.hosts.is_repo_root` is True → TOP UP per
       directory (P-C1.14): create whichever `_LAYOUT` dirs are missing;
       if the repo has no HEAD, commit (P-C1.16 — every successful path
       ends with one). Nothing missing + HEAD already exists → report
       already-complete, mutate nothing (this is O-2; branching on
       ``home_state`` here — an any-of predicate — was the MAJOR-A bug a
       prior revision shipped).

    P-C1.20: the branch predicate for steps 4-6 is
    :func:`~self_learn.hosts.is_repo_root`, NEVER an is-inside-work-tree
    check — the latter answers TRUE for a path a PARENT repo's work tree
    swallows, which would route a nested ledger home's `init` into the
    user's unrelated project repo.

    P-C1.9: never adds, prompts for, or infers a remote — local-only is
    the default and the whole of what this function does."""
    target = Path(path).expanduser()

    # Step 2 (P-C1.24): lexists, not exists — a dangling symlink answers
    # exists()==False, so an exists()-keyed check would fall through to
    # step 3 and crash on a raw `mkdir` FileExistsError.
    if os.path.lexists(target) and not target.is_dir():
        raise InitError(
            f"{target} exists and is not a directory — self-learn init "
            "initializes directories only; remove or rename it, then "
            "re-run `self-learn init`"
        )

    if not os.path.lexists(target):
        # Step 3: absent → create everything, including a `git init` on a
        # brand-new dir (P-C1.12: the departure from "creates nothing" —
        # confined to the ledger home, never `host add --init`).
        # MAJOR 1 (code gate): every mkdir is guarded — an unguarded
        # one leaks a raw OSError traceback at the same exit code as a
        # clean refusal, so a crash was indistinguishable from a refusal.
        # NIT 9: no parents=True — §2.2 step 3 says "create dir", and a
        # mistyped deep $SELF_LEARN_HOME must refuse loudly rather than
        # silently materialize a chain of directories (P-C1.10).
        try:
            target.mkdir()
        except OSError as exc:
            raise InitError(
                f"cannot create {target}: {exc.strerror or exc} — check "
                "that its parent directory exists and is writable, then "
                "re-run `self-learn init`"
            ) from exc
        _git_init(target)
        added = _create_layout(target)
        # Locked even though nothing can race a repo created microseconds
        # ago: test_lock_invariant's rule is ABSOLUTE ("no mutation may
        # precede its commit_lock"), and buying an exemption here would
        # weaken it for every producer. Acquisition on a fresh repo is
        # uncontended and effectively free.
        with gitops.commit_lock(target):
            _commit_allow_empty(target)
        return InitResult(target.resolve(), True, added, True, False)

    resolved = target.resolve()
    if not is_repo_root(resolved):
        if not _is_empty_dir(resolved):
            # Step 4: refuse — never `git init` over foreign files.
            raise InitError(
                f"{resolved} exists, is non-empty, and is not a git repo "
                "— self-learn init never runs `git init` over foreign "
                "files; point $SELF_LEARN_HOME elsewhere, or clear the "
                "directory yourself, then re-run"
            )
        # Step 5: empty non-repo dir → git init in place. Nested inside a
        # parent work tree lands here too — doc 13 §3 blesses nested init;
        # P-C1.21's obligation is that the PARENT stays untouched, which
        # `git init <resolved>` (never the parent's toplevel) guarantees.
        _git_init(resolved)
        added = _create_layout(resolved)
        with gitops.commit_lock(resolved):  # see step 3 — absolute rule
            _commit_allow_empty(resolved)
        return InitResult(resolved, True, added, True, False)

    # Step 6: already a repo root — top up per directory (P-C1.14).
    missing_before = tuple(name for name in _LAYOUT if not (resolved / name).is_dir())
    had_head_before = _has_head(resolved)
    if not missing_before and had_head_before:
        return InitResult(resolved, False, (), False, True)
    # MAJOR 2 (code gate): step 6 is the ONLY init path that mutates a
    # repo self-learn did not just create, so it is the only one exposed
    # to a racing producer. `git commit --allow-empty` commits whatever
    # is STAGED, so without this lock a concurrent producer's staged
    # index lands under INIT_COMMIT_SUBJECT.
    #
    # MAJOR (delta code gate) + its own follow-on: the acquisition must be
    # GUARDED (commit_lock does a raw mkdir + open(), so a read-only .git
    # leaked a PermissionError traceback at rc=1 — the very signature
    # MAJOR 1 named) AND must stay a literal `with gitops.commit_lock(...)`
    # statement, because test_lock_invariant's structural analysis
    # recognizes only that form. A manual __enter__/__exit__ pair guarded
    # the acquisition and made the whole init path invisible to the
    # invariant. try/except AROUND the `with` satisfies both. InitError is
    # not an OSError, so the body's own guarded raises pass through.
    made_head = False
    try:
        with gitops.commit_lock(resolved):
            for name in missing_before:
                try:
                    (resolved / name).mkdir()
                except OSError as exc:  # MAJOR 1
                    raise InitError(
                        f"cannot create {resolved / name}: "
                        f"{exc.strerror or exc} — the ledger home is not "
                        "writable; fix its permissions, then re-run"
                    ) from exc
            if not had_head_before:
                _commit_allow_empty(resolved)
                made_head = True
    except OSError as exc:
        raise InitError(
            f"cannot take the commit lock for {resolved}: "
            f"{exc.strerror or exc} — the ledger repo is not writable; "
            "fix its permissions, then re-run `self-learn init`"
        ) from exc
    return InitResult(resolved, False, missing_before, made_head, False)
