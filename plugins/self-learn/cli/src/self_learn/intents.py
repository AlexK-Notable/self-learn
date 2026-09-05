"""Crash-safe multi-file ledger transactions (Sprint 2 lane L7, D7).

**The gap this closes.** :mod:`reconcile` heals a SINGLE orphaned write
(a producer wrote one file and could not commit it). Two of this
repo's writers mutate MULTIPLE files under one lock before their one
commit: collapse (inside :func:`verbs._execute_route`, when its
``collapse`` argument is set) folds losers into a survivor, git-mv's it
into ``resolved/``, and supersedes each loser -- several files, one
commit; :func:`hosts.host_rebind` git-mv's an entire project bucket,
rewrites its ``meta.yaml``, and rewrites ``hosts.yaml`` -- again several
files, one commit. A ``SIGKILL`` between two of those writes leaves a
mix reconcile cannot repair: a staged rename reads as ``R`` in
``git status``, which :data:`reconcile._BLOCKING_CODES` refuses to
touch (a half-committed ``git mv`` must never be completed one file at
a time), and ``hosts.yaml`` itself has NO path-shape match in
:data:`reconcile._RECONCILABLE_HOME` at all -- a crash after
``save_hosts`` and before the commit is invisible to reconcile, not
even reported as blocked.

**The mechanism.** An *intent* is one atomic JSON file, written under
the caller's own lock BEFORE its first mutation and removed after its
commit:

    {"op": "...", "id": "...", "started": "<iso>",
     "steps": [{"path": "<abs>", "old_sha": "<hex>"|null,
                "new_sha": "<hex>"|"-"|null}, ...],
     "commit_subject": "..."}

One step per PATH the transaction touches (not per mutation of that
path -- a path rewritten twice, or renamed then rewritten, is still one
step: only its state at the two endpoints matters for recovery).
``old_sha`` is the path's sha256 before the transaction began, or
``null`` when it did not exist yet. ``new_sha`` starts ``null``
(unrecorded); :func:`complete` fills in every step's ACTUAL final state
in one pass, right after the last mutation lands and before the
commit -- a real sha256 if the path exists, the sentinel ``"-"`` if it
does not (the vanished half of a rename). A step whose ``new_sha`` is
still ``null`` at recovery time is proof the crash landed before
:func:`complete` ran, i.e. mid-mutation -- unambiguous, unlike a
pre-guessed "expected absent" written at :func:`begin` time would have
been (that would collide with "unrecorded" on the same ``null``).

**Pin-implied key.** The schema above adds one key beyond
``{path, old_sha, new_sha}``: ``old_inline`` (base64, omitted unless
present), the untracked-file bytes :func:`begin` captures ONLY when a
path's pre-transaction content cannot be recovered from git (untracked,
or a symlink) and is small enough (<= 64 KiB) to carry inline. Recovery
needs SOME source for "the bytes this path held before" that survives a
crash; git's own object store is that source for a TRACKED path
(``git show HEAD:<relpath>`` -- HEAD has not moved, since the crash is
mid-transaction, before this transaction's own commit), and this key is
the fallback for everything git cannot answer.

**Recovery** (:func:`recover`, called from :func:`reconcile.reconcile`
before its own orphan scan, and from :func:`worker.run` at start) reads
every ``.intents/*.json`` under the lock and, per intent: every step's
``new_sha`` present and verified against the real path (a hash match, or
confirmed absent for ``"-"``) -> ROLL FORWARD: stage every step path
that exists and commit with the recorded subject
(``allow_empty=True`` -- a crash between the commit landing and this
intent's own removal leaves every step already verified with nothing
left to stage, and that must read as success, not a `HalfWrittenError`).
Otherwise -> RESTORE: for every step, resolve the pre-transaction bytes
(current content already matches ``old_sha``; else git HEAD; else the
inline copy) -- if EVERY step resolves, write them all back (a ``null``
``old_sha`` restores by deleting the path) and ``git reset -q --`` every
step path so the index matches the restored worktree, then remove the
intent. If restore cannot resolve even one step's prior content (the
untracked-and-too-big case, or a repo whose HEAD no longer holds the
blob), NOTHING is touched for that intent, it is left in place, and the
offending path is reported -- a human decides from there.

**Location: `<home>/.intents/`, not the XDG cache dir.** The choice is
pinned open in the brief; this module answers it in favor of the ledger
home. `reconcile()`/`worker.run` recovery is keyed on `home` alone, and
`cache_dir(home)` -- the alternative -- lives under
`$XDG_CACHE_HOME`, which is explicitly not guaranteed to survive a
reboot (systemd-tmpfiles, a user's own `rm -rf ~/.cache/*`) and is
addressed by a DIFFERENT hash-of-home namespace than the ledger itself.
An intent describes a specific, in-progress mutation OF the ledger; its
only durability requirement is "outlives the crash it recovers from",
which the ledger's own directory already satisfies by construction (it
is the thing being protected). No ``.gitignore`` entry is added for it:
an untracked ``.intents/*.json`` never matches any
:data:`reconcile._RECONCILABLE_KINDS` / :data:`reconcile._RECONCILABLE_HOME`
pattern (parent is neither a bucket nor ``home`` for a ``compiled/``-shaped
name), so it is never staged or committed by anything in this tree, and
a stray directory listed in ``git status`` after a crash is a visible
diagnostic, not litter that need hiding.
"""

from __future__ import annotations

import base64
import json
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops
from .compiled import sha256_hex
from .primitives import chrono, fsops

__all__ = ["Intent", "RecoverResult", "begin", "complete", "finish", "recover", "intents_dir"]

#: 64 KiB (D7 pin): the largest untracked file this module will carry
#: inline in the intent JSON itself. Bigger, and recovery's restore leg
#: simply cannot resolve that step's prior bytes -- it STOPS rather than
#: silently dropping data (see the module docstring's Recovery section).
_INLINE_CAP = 64 * 1024

#: The ``new_sha`` sentinel :func:`complete` writes for a step whose path
#: does not exist at completion time (the vanished half of a rename, or a
#: merge-proposal sibling removed outright). Never confused with
#: "unrecorded" (``None``): only :func:`complete` ever writes this value,
#: and it always writes SOME value for every step in the same pass.
ABSENT = "-"


def intents_dir(home: Path | str) -> Path:
    return Path(home) / ".intents"


def _now_iso() -> str:
    return chrono.now_iso()


def _relpath(home: Path, path: Path) -> str:
    return str(Path(path).resolve().relative_to(Path(home).resolve()))


def _head_show(home: Path, relpath: str) -> bytes | None:
    """The exact bytes ``HEAD:<relpath>`` holds, or ``None`` when *relpath*
    is not in ``HEAD`` at all. A bespoke call (not :func:`gitops._git`,
    which decodes with ``text=True``) -- a byte-exact compare against a
    recorded sha256 must never go through a text codec that can silently
    change bytes."""
    proc = subprocess.run(
        ["git", "-C", str(home), "show", f"HEAD:{relpath}"],
        capture_output=True,
        timeout=gitops.GIT_LOCAL_TIMEOUT,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _capture_old_state(home: Path, path: Path) -> tuple[str | None, str | None]:
    """(``old_sha``, ``old_inline``) for *path* BEFORE any mutation of
    this transaction. ``None, None`` when *path* does not exist yet.
    Otherwise the real sha256, plus an inline base64 copy iff the path's
    current bytes are NOT already recoverable from ``HEAD`` (untracked,
    or locally modified ahead of HEAD -- capturing defensively costs
    nothing) and small enough to carry."""
    if not path.exists() or path.is_dir():
        return None, None
    data = path.read_bytes()
    sha = sha256_hex(data)
    head_bytes = _head_show(home, _relpath(home, path))
    if head_bytes is not None and sha256_hex(head_bytes) == sha:
        return sha, None
    inline = base64.b64encode(data).decode("ascii") if len(data) <= _INLINE_CAP else None
    return sha, inline


@dataclass
class Intent:
    """One in-flight (or just-recovered) transaction. ``steps`` are plain
    dicts, not a nested dataclass -- they round-trip through JSON
    unchanged (:meth:`to_dict` / :func:`_from_dict`), which a nested
    dataclass would need its own codec for anyway."""

    home: Path
    op: str
    id: str
    started: str
    steps: list[dict]
    commit_subject: str

    @property
    def file_path(self) -> Path:
        return intents_dir(self.home) / f"{self.id}.json"

    def to_dict(self) -> dict:
        steps = []
        for s in self.steps:
            step = {"path": s["path"], "old_sha": s["old_sha"], "new_sha": s["new_sha"]}
            if s.get("old_inline"):
                step["old_inline"] = s["old_inline"]
            steps.append(step)
        return {
            "op": self.op,
            "id": self.id,
            "started": self.started,
            "steps": steps,
            "commit_subject": self.commit_subject,
        }


def _from_dict(home: Path, data: dict) -> Intent:
    return Intent(
        home=home,
        op=data["op"],
        id=data["id"],
        started=data["started"],
        steps=[dict(s) for s in data["steps"]],
        commit_subject=data["commit_subject"],
    )


def _write_intent(intent: Intent) -> None:
    """The ONE writer of ``.intents/*.json`` -- every :func:`begin` /
    :func:`complete` call funnels through here, so the raw-write gate and
    the lock-invariant walker each have a single site to reason about.
    Callers already hold the repo's ``commit_lock`` (the intent brackets
    a locked transaction); this function does not open one itself."""
    intents_dir(intent.home).mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(
        intent.file_path,
        json.dumps(intent.to_dict(), indent=2, sort_keys=True) + "\n",
        fsync=True,
    )


def begin(home: Path | str, op: str, paths: list[Path], commit_subject: str) -> Intent:
    """Open a transaction: capture every *path*'s pre-mutation state and
    write the intent file. Call this BEFORE the first mutation, inside
    the same ``commit_lock``/``host_lock`` the transaction itself runs
    under (the docstring's "under the lock" pin) -- :func:`_write_intent`
    takes no lock of its own."""
    home = Path(home)
    steps = []
    for p in paths:
        p = Path(p)
        old_sha, old_inline = _capture_old_state(home, p)
        steps.append(
            {"path": str(p), "old_sha": old_sha, "old_inline": old_inline, "new_sha": None}
        )
    intent = Intent(
        home=home,
        op=op,
        id=uuid.uuid4().hex[:12],
        started=_now_iso(),
        steps=steps,
        commit_subject=commit_subject,
    )
    _write_intent(intent)
    return intent


def complete(intent: Intent) -> None:
    """Record every step's ACTUAL current state as its final one -- call
    this once, right after the transaction's last mutation lands and
    before its commit. A crash before this call leaves every ``new_sha``
    ``None`` (unrecorded -> restore); a crash after it leaves every
    ``new_sha`` present (-> roll forward, even if the commit itself never
    ran)."""
    for step in intent.steps:
        p = Path(step["path"])
        step["new_sha"] = sha256_hex(p.read_bytes()) if p.is_file() else ABSENT
    _write_intent(intent)


def finish(intent: Intent) -> None:
    """The transaction's commit has landed: the intent's job is done."""
    intent.file_path.unlink(missing_ok=True)


def _step_verifies_final(step: dict) -> bool:
    new_sha = step.get("new_sha")
    if new_sha is None:
        return False
    path = Path(step["path"])
    if new_sha == ABSENT:
        return not path.exists()
    return path.is_file() and sha256_hex(path.read_bytes()) == new_sha


def _resolvable_old_bytes(home: Path, step: dict) -> tuple[bool, bytes | None]:
    """(resolvable?, bytes-to-restore-or-None-to-delete) for *step*'s
    PRE-transaction state. Tries, in order: already-correct on disk (a
    step that never actually got mutated); ``HEAD`` (tracked); the
    intent's own inline copy (untracked, <= 64 KiB). ``old_sha is None``
    always resolves (restore = "this path must not exist")."""
    old_sha = step.get("old_sha")
    path = Path(step["path"])
    if old_sha is None:
        return True, None
    if path.is_file() and sha256_hex(path.read_bytes()) == old_sha:
        return True, path.read_bytes()
    head_bytes = _head_show(home, _relpath(home, path))
    if head_bytes is not None and sha256_hex(head_bytes) == old_sha:
        return True, head_bytes
    inline = step.get("old_inline")
    if inline:
        data = base64.b64decode(inline)
        if sha256_hex(data) == old_sha:
            return True, data
    return False, None


def _prune_empty_dirs(home: Path, start: Path) -> None:
    """After a restore deletes a path, walk its parent chain up toward
    *home* removing any directory the deletion left empty — a rebind
    restore's per-file steps each unlink one file out of the NEW bucket
    directory, and without this the directory itself survives empty,
    which then blocks a retry of the SAME rebind (`host_rebind`'s own
    ``new_bucket.exists()`` refusal)."""
    home = home.resolve()
    d = start.resolve()
    while d != home and home in d.parents:
        try:
            next(d.iterdir())
            return  # not empty -- stop, and so does everything further up
        except (StopIteration, FileNotFoundError, NotADirectoryError):
            pass
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


@dataclass
class RecoverResult:
    """One entry per intent :func:`recover` found. ``stopped`` entries
    leave their intent file in place (a human repairs it by hand or by
    naming what to do next; nothing here silently discards a recovery it
    could not complete)."""

    rolled_forward: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)

    @property
    def acted(self) -> bool:
        return bool(self.rolled_forward or self.restored)


def _recover_one(home: Path, intent: Intent, result: RecoverResult) -> None:
    if all(_step_verifies_final(s) for s in intent.steps):
        paths = [Path(s["path"]) for s in intent.steps]
        try:
            gitops.stage_and_commit(home, paths, intent.commit_subject, allow_empty=True)
        except gitops.HalfWrittenError as exc:
            result.stopped.append(f"{intent.id}: roll-forward commit failed: {exc}")
            return
        finish(intent)
        result.rolled_forward.append(intent.id)
        return

    plan: list[tuple[Path, bytes | None]] = []
    for step in intent.steps:
        ok, content = _resolvable_old_bytes(home, step)
        if not ok:
            result.stopped.append(
                f"{intent.id}: cannot restore {step['path']} "
                "(no matching content in the worktree, HEAD, or the intent's own copy)"
            )
            return
        plan.append((Path(step["path"]), content))
    try:
        for path, content in plan:
            if content is None:
                parent = path.parent
                path.unlink(missing_ok=True)
                _prune_empty_dirs(home, parent)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                fsops.atomic_write(path, content, follow_symlinks=True)
        # `git reset -- <path>` un-stages an entry regardless of whether
        # *path* currently exists (a staged rename's vanished OLD half
        # included) -- every step path goes in, unconditionally.
        touched = [str(p) for p, _ in plan]
        gitops._git(home, "reset", "-q", "--", *touched)  # noqa: SLF001 -- same module family
    except OSError as exc:
        result.stopped.append(f"{intent.id}: restore failed partway ({exc}) -- repair by hand")
        return
    finish(intent)
    result.restored.append(intent.id)


def recover(home: Path | str) -> RecoverResult:
    """Find and resolve every intent left behind under *home* -- called
    from :func:`reconcile.reconcile` (before its own orphan scan: an
    incomplete collapse/rebind leaves a staged rename reconcile's scan
    would otherwise report ``blocked`` forever) and from
    :func:`worker.run` at start. Idempotent and cheap when nothing is
    there (one directory listing under the lock)."""
    home = Path(home)
    result = RecoverResult()
    d = intents_dir(home)
    if not d.is_dir():
        return result
    with gitops.commit_lock(home):
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                intent = _from_dict(home, data)
            except (OSError, ValueError, KeyError) as exc:
                result.stopped.append(f"{f.name}: unreadable intent file ({exc})")
                continue
            _recover_one(home, intent, result)
    return result
