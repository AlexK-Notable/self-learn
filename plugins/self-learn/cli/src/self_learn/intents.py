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
     "steps": [{"path": "<home-relative>", "old_sha": "<hex>"|null,
                "new_sha": "<hex>"|"-"|null}, ...],
     "commit_subject": "..."}

One step per PATH the transaction touches (not per mutation of that
path -- a path rewritten twice, or renamed then rewritten, is still one
step: only its state at the two endpoints matters for recovery).
``path`` is stored HOME-RELATIVE (gate r1 minor-2), not absolute: an
intent is read back against whatever ``home`` the CALLER passes to
:func:`recover`, which is not always the same absolute path that wrote
it (a ledger restored from backup, or moved) -- resolving relative to
the CURRENT ``home`` at every read means a moved ledger recovers
exactly like one that never moved, with no path-membership check able
to fail along the way. ``old_sha`` is the path's sha256 before the
transaction began, or ``null`` when it did not exist yet. ``new_sha``
starts ``null`` (unrecorded); :func:`complete` fills in every step's
ACTUAL final state in one pass, right after the last mutation lands and
before the commit -- a real sha256 if the path exists, the sentinel
``"-"`` if it does not (the vanished half of a rename). A step whose
``new_sha`` is still ``null`` at recovery time is proof the crash landed
before :func:`complete` ran, i.e. mid-mutation -- unambiguous, unlike a
pre-guessed "expected absent" written at :func:`begin` time would have
been (that would collide with "unrecorded" on the same ``null``).
:func:`add_step` registers one more step on an ALREADY-OPEN intent, for
a path not knowable until :func:`begin` time has passed (gate r1
MAJOR-1: a collapse's compile-record writes resolve their target's host
slug mid-transaction) -- same before-the-mutation discipline, same
schema, appended in place.

**Pin-implied key.** The schema above adds one key beyond
``{path, old_sha, new_sha}``: ``old_inline`` (base64, omitted unless
present), the untracked-file bytes :func:`begin` captures ONLY when a
path's pre-transaction content cannot be recovered from git (untracked,
or a symlink) and is small enough (<= 64 KiB) to carry inline. Recovery
needs SOME source for "the bytes this path held before" that survives a
crash; git's own object store is that source for a TRACKED path
(``git show HEAD:<relpath>``) -- but HEAD may well have moved by the
time recovery runs (gate r1 BLOCKER-1: an ordinary verb against a
DIFFERENT record can land a real commit while this intent sits
unresolved), so this is never a "HEAD is still where it was" assumption.
What decides recoverability is CONTENT, checked by hash: current on-disk
bytes against ``old_sha`` first, then ``HEAD``'s blob at this path
against that same ``old_sha`` (whichever commit HEAD now names), then
the inline copy. Only when none of the three matches does this key
become the fallback restore has no other source for.

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
offending path is reported -- a human decides from there. Gate r1
BLOCKER-1: a STOPped intent used to still let :func:`reconcile.reconcile`
stage and commit its OWN ordinary orphan scan below it -- which can
include the very files the stuck transaction half-wrote -- while
reporting "nothing was written". ``reconcile()`` now refuses that whole
batch too whenever recovery leaves anything ``stopped``, the same
all-or-nothing contract a blocked rename or an invalid orphan already
carry; see its own docstring for the operator-facing consequence (a
single stuck intent freezes ALL orphan healing, including the miner's
own carry-over, until a human clears it).

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
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops
from .compiled import sha256_hex
from .primitives import chrono, fsops

__all__ = [
    "Intent",
    "RecoverResult",
    "StopDetail",
    "LedgerStoppedError",
    "add_step",
    "begin",
    "complete",
    "finish",
    "recover",
    "recover_or_raise",
    "ledger_write",
    "announce_recovered",
    "clear_stopped",
    "classify_status",
    "StatusClass",
    "IntentStatus",
    "intents_dir",
]

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
    is not in ``HEAD`` at all. Not :func:`gitops._git` (which decodes with
    ``text=True``) -- a byte-exact compare against a recorded sha256 must
    never go through a text codec that can silently change bytes. Routed
    through ``procs.run_bounded(..., binary=True)`` (gate r1 minor-3
    follow-up): gets the same process-group kill on timeout every other
    bounded child call site has, while still forcing bytes output
    regardless of ``input`` (there is none here)."""
    from .primitives import procs

    try:
        proc = procs.run_bounded(
            ["git", "-C", str(home), "show", f"HEAD:{relpath}"],
            timeout=gitops.GIT_LOCAL_TIMEOUT,
            binary=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise gitops.GitOpsError(
            f"git show HEAD:{relpath} in {home} exceeded "
            f"{gitops.GIT_LOCAL_TIMEOUT:g}s and was killed"
            f"{gitops._index_lock_note(home)}; nothing further was attempted"  # noqa: SLF001
        ) from exc
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
    dataclass would need its own codec for anyway.

    ``stopped`` (S-62, §7.2a.1) is ``None`` until a recovery attempt on
    this intent fails; from then on it carries ``{"reason": ..., "at":
    ...}``, rewritten by :func:`_mark_stopped` on every subsequent failed
    attempt -- the field records the LAST attempt, never a decision to
    stop trying."""

    home: Path
    op: str
    id: str
    started: str
    steps: list[dict]
    commit_subject: str
    stopped: dict | None = None

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
        out = {
            "op": self.op,
            "id": self.id,
            "started": self.started,
            "steps": steps,
            "commit_subject": self.commit_subject,
        }
        if self.stopped is not None:
            out["stopped"] = self.stopped
        return out


def _from_dict(home: Path, data: dict) -> Intent:
    return Intent(
        home=home,
        op=data["op"],
        id=data["id"],
        started=data["started"],
        steps=[dict(s) for s in data["steps"]],
        commit_subject=data["commit_subject"],
        stopped=data.get("stopped"),
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
    takes no lock of its own. *paths* are absolute (every existing caller
    already has them that way); stored HOME-RELATIVE (gate r1 minor-2)."""
    home = Path(home)
    steps = []
    for p in paths:
        p = Path(p)
        old_sha, old_inline = _capture_old_state(home, p)
        steps.append(
            {
                "path": _relpath(home, p),
                "old_sha": old_sha,
                "old_inline": old_inline,
                "new_sha": None,
            }
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


def add_step(intent: Intent | None, path: Path | str) -> None:
    """Register one more step on an ALREADY-OPEN *intent*, for a path not
    knowable at :func:`begin` time (gate r1 MAJOR-1: a collapse's
    compile-record writes resolve their target's host slug mid-
    transaction, not before it). A no-op when *intent* is ``None`` -- a
    plain, non-collapse route never opens one -- so every call site can
    pass *intent* unconditionally rather than guarding at each one.
    Captures ``old_sha``/``old_inline`` for *path* AS OF THIS CALL, same
    before-the-mutation discipline :func:`begin` itself documents:
    callers must call this immediately before *path*'s own first
    mutation of this transaction. A *path* already present as a step (by
    exact match, once both are home-relative) is a no-op, so a caller
    that resolves the same path twice within one transaction attempt (a
    retry) never duplicates it."""
    if intent is None:
        return
    p = Path(path)
    relpath = _relpath(intent.home, p)
    if any(s["path"] == relpath for s in intent.steps):
        return
    old_sha, old_inline = _capture_old_state(intent.home, p)
    intent.steps.append(
        {"path": relpath, "old_sha": old_sha, "old_inline": old_inline, "new_sha": None}
    )
    _write_intent(intent)


def complete(intent: Intent) -> None:
    """Record every step's ACTUAL current state as its final one -- call
    this once, right after the transaction's last mutation lands and
    before its commit. A crash before this call leaves every ``new_sha``
    ``None`` (unrecorded -> restore); a crash after it leaves every
    ``new_sha`` present (-> roll forward, even if the commit itself never
    ran)."""
    for step in intent.steps:
        p = Path(intent.home) / step["path"]
        step["new_sha"] = sha256_hex(p.read_bytes()) if p.is_file() else ABSENT
    _write_intent(intent)


def finish(intent: Intent) -> None:
    """The transaction's commit has landed: the intent's job is done."""
    intent.file_path.unlink(missing_ok=True)


def _mark_stopped(intent: Intent, reason: str) -> bool:
    """Persist a STOP on *intent* (S-62, §7.2a.1/§7.2a.3): the SAME
    single writer (:func:`_write_intent`) rewrites the file with
    ``stopped`` set/refreshed. Called on every failed recovery attempt,
    including a RETRY of an already-stopped intent -- the field records
    the LAST attempt, never a decision to stop trying, so it is
    unconditionally overwritten rather than checked-then-set.

    Returns True iff the rewrite is confirmed durable. False is the
    marker-publication-failure case (§7.2a.3): the STOP itself is still
    real -- this attempt's OWN recovery genuinely failed, which is a
    fact about the attempt, not about whether the marker landed -- but
    the caller must report BOTH facts (the demonstrated failure, and
    "could not be durably confirmed") and must assume NOTHING about
    which bytes are now on disk (unmarked, the new marker, or an
    earlier retry's)."""
    intent.stopped = {"reason": reason, "at": _now_iso()}
    try:
        _write_intent(intent)
    except OSError:
        return False
    return True


def _step_verifies_final(home: Path, step: dict) -> bool:
    new_sha = step.get("new_sha")
    if new_sha is None:
        return False
    path = Path(home) / step["path"]
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
    path = Path(home) / step["path"]
    if old_sha is None:
        return True, None
    if path.is_file() and sha256_hex(path.read_bytes()) == old_sha:
        return True, path.read_bytes()
    # `step["path"]` is already home-relative (gate r1 minor-2) -- no
    # `_relpath` round-trip needed here, which is exactly what removes
    # the read-side crash a moved `home` used to cause (a stored
    # ABSOLUTE path could fall outside the NEW home's subtree and raise
    # `ValueError`; a relative one resolves against whatever `home` is
    # passed to `recover` unconditionally).
    head_bytes = _head_show(home, step["path"])
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
class StopDetail:
    """One STOP, structured (S-62) so the exception message, the
    ``--json`` envelope and the persisted ``Intent.stopped`` field all
    build from the SAME facts rather than three independent renderings
    that can drift. ``id`` is the intent id, or (the unreadable-file
    case) the ``.json`` file's stem -- there is no parsed intent to name
    an id from. ``marker_uncertain`` is true only for the two-fact report
    of §7.2a.3's marker-publication-failure cases: the STOP is real, but
    :func:`_mark_stopped`'s own rewrite could not be confirmed durable."""

    id: str
    reason: str
    marker_uncertain: bool = False


@dataclass
class RecoverResult:
    """One entry per intent :func:`recover` found. ``stopped`` entries
    leave their intent file in place (a human repairs it by hand or by
    naming what to do next; nothing here silently discards a recovery it
    could not complete). ``stopped`` (list[str]) is kept for existing
    callers/tests -- ``"{id}: {reason}"`` -- built FROM ``stopped_detail``,
    never the other way, so the two never disagree."""

    rolled_forward: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    stopped_detail: list[StopDetail] = field(default_factory=list)

    def _stop(self, id_: str, reason: str, *, marker_uncertain: bool = False) -> None:
        self.stopped_detail.append(StopDetail(id_, reason, marker_uncertain))
        self.stopped.append(f"{id_}: {reason}")

    @property
    def acted(self) -> bool:
        return bool(self.rolled_forward or self.restored)


def _recover_one(home: Path, intent: Intent, result: RecoverResult) -> None:
    if all(_step_verifies_final(home, s) for s in intent.steps):
        paths = [Path(home) / s["path"] for s in intent.steps]
        try:
            gitops.stage_and_commit(home, paths, intent.commit_subject, allow_empty=True)
        except gitops.HalfWrittenError as exc:
            reason = f"roll-forward commit failed: {exc}"
            marked = _mark_stopped(intent, reason)
            result._stop(intent.id, reason, marker_uncertain=not marked)
            return
        finish(intent)
        result.rolled_forward.append(intent.id)
        return

    plan: list[tuple[Path, bytes | None]] = []
    for step in intent.steps:
        ok, content = _resolvable_old_bytes(home, step)
        if not ok:
            reason = (
                f"cannot restore {step['path']} "
                "(no matching content in the worktree, HEAD, or the intent's own copy)"
            )
            marked = _mark_stopped(intent, reason)
            result._stop(intent.id, reason, marker_uncertain=not marked)
            return
        plan.append((Path(home) / step["path"], content))
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
        reason = f"restore failed partway ({exc}) -- repair by hand"
        marked = _mark_stopped(intent, reason)
        result._stop(intent.id, reason, marker_uncertain=not marked)
        return
    finish(intent)
    result.restored.append(intent.id)


def recover(home: Path | str) -> RecoverResult:
    """Find and resolve every intent left behind under *home* -- called
    from :func:`reconcile.reconcile` (before its own orphan scan: an
    incomplete collapse/rebind leaves a staged rename reconcile's scan
    would otherwise report ``blocked`` forever) and from
    :func:`worker.run` at start. Idempotent and cheap when nothing is
    there (one directory listing under the lock).

    Gate r1 minor-2: :func:`_recover_one` runs INSIDE the same
    ``try``/``except`` that guards reading the intent file, with
    ``ValueError`` in the caught set — not just around the JSON decode.
    Storing ``step["path"]`` home-relative (this same fold) already
    removes the one call (``_relpath`` at read time) that used to raise
    it when a step's absolute path fell outside a MOVED ``home``'s
    subtree; this is defense in depth for anything else inside
    :func:`_recover_one` that could still raise it, converting an
    unresolvable step into a ``stopped`` entry that names it rather than
    propagating past every caller — `reconcile()`, `push`, the miner's
    own ``except gitops.GitOpsError`` (which does not catch
    ``ValueError``), and ``worker.run``'s unguarded call."""
    home = Path(home)
    result = RecoverResult()
    d = intents_dir(home)
    if not d.is_dir():
        return result
    with gitops.commit_lock(home):
        for f in sorted(d.glob("*.json")):
            # Gate r2 nit-1: split by PHASE, not folded into one message
            # -- a genuinely corrupt file (can't even be read/parsed)
            # names a different repair (fix/delete the file) than a
            # real, half-written step the JSON itself parses fine but
            # cannot resolve (inspect the path it names).
            #
            # Gate r3: the guard is `ValueError`, not the narrower
            # `json.JSONDecodeError` -- `f.read_text(encoding="utf-8")`
            # on a non-UTF-8 file raises `UnicodeDecodeError`, ALSO a
            # `ValueError` subclass, before `json.loads` is even
            # reached. The narrower guard let that escape uncaught out
            # of `recover()`, `reconcile()` (so `push` and the miner,
            # whose `except gitops.GitOpsError` does not catch a bare
            # `ValueError`), and `worker.run`'s unguarded call -- both
            # phrases below stay exact, since `JSONDecodeError` is
            # itself a `ValueError` subclass too.
            #
            # S-62: an unreadable file cannot carry the persisted
            # `stopped` field -- unreadability is itself the STOP any
            # reader can see (§7.2a.3) -- so this leg never calls
            # `_mark_stopped`, and the reported "id" is the file's own
            # stem (there is no parsed intent to name one from).
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                result._stop(f.stem, f"unreadable intent file ({exc})")
                continue
            try:
                intent = _from_dict(home, data)
            except (ValueError, KeyError) as exc:
                result._stop(f.stem, f"unresolvable intent ({exc})")
                continue
            try:
                _recover_one(home, intent, result)
            except (OSError, ValueError, KeyError, gitops.GitOpsError) as exc:
                # Unlike the two legs above, an `Intent` DID parse here
                # -- `_recover_one` itself raised, past its own two
                # `_stop` call sites -- so the marker CAN be persisted,
                # naming this bug-shaped failure the same way an
                # ordinary STOP is named. `GitOpsError` is in this set
                # too: the restore leg's own `git reset` (not behind
                # `stage_and_commit`'s HalfWrittenError conversion) can
                # raise one on a wedged subprocess -- WE hold
                # `commit_lock` for this whole call, so that is never
                # "a live writer", and letting it escape unmarked here
                # would (via `clear_stopped`'s identically-widened catch,
                # below) mislabel a failed recovery attempt as a lock
                # refusal instead of the STOP it demonstrably is.
                reason = f"unresolvable intent ({exc})"
                marked = _mark_stopped(intent, reason)
                result._stop(intent.id, reason, marker_uncertain=not marked)
    return result


def recover_or_raise(
    home: Path | str, *, earlier_commits: list[str] | None = None
) -> RecoverResult:
    """:func:`recover`, then raise :class:`LedgerStoppedError` if
    anything is left ``stopped`` -- the shape :func:`ledger_write` (and
    any other caller that wants "recover, or refuse") needs.
    ``earlier_commits`` (§7.2a.5(4), multi-span) is threaded straight
    through to the exception: this function has no notion of "spans"
    itself, only the caller (a multi-span verb's own accumulator) does."""
    result = recover(home)
    if result.stopped_detail:
        raise LedgerStoppedError(result, earlier_commits=earlier_commits)
    return result


class LedgerStoppedError(gitops.GitOpsError):
    """S-62's refusal type (§7.2a.5(5)): raised by :func:`ledger_write`
    (and, at the ledger rebase leg, by :func:`gitops.push_with_retry`)
    when recovery leaves an intent STOPPED. ``result`` carries the full
    outcome -- every STOP's id/path/reason, plus whatever
    :attr:`RecoverResult.rolled_forward` / ``.restored`` this SAME
    recovery attempt already completed (§7.2a.5(4)(b): reported, never
    hidden behind the refusal).

    The message is deliberately the FULL text §7.2a.5(5) mandates: every
    existing ``except gitops.GitOpsError as exc: print(f"...: {exc}")``
    site in this tree already renders it correctly (str(exc) IS the
    message), so no per-surface edit was needed at any of them -- only
    `main()`'s own net catch, which prints a DIFFERENT, false hedge for
    a plain `GitOpsError` ("this surface did not say whether anything
    was written"), needed a dedicated arm ahead of it."""

    def __init__(
        self, result: RecoverResult, *, earlier_commits: list[str] | None = None
    ) -> None:
        self.result = result
        #: §7.2a.5(4), the multi-span case: subjects of commits THIS SAME
        #: invocation already landed, in an earlier outer lock span,
        #: before the span where this STOP was found. Empty for every
        #: single-span verb (the overwhelming majority) -- non-empty only
        #: when a caller like `verbs.recompile` (several sequential
        #: outermost ledger spans in one call) threads its own
        #: accumulator through. Non-empty is what tells a catch arm the
        #: invocation is NOT "wrote nothing": exit 8, never 6.
        self.earlier_commits = list(earlier_commits or [])
        lines = []
        for intent_id in result.rolled_forward:
            lines.append(
                f"self-learn: recovered {intent_id} (rolled forward: its commit "
                "landed — the host phase did not run; run 'self-learn recompile')"
            )
        for intent_id in result.restored:
            lines.append(f"self-learn: recovered {intent_id} (restored: its mutation was undone)")
        if self.earlier_commits:
            subjects = "; ".join(self.earlier_commits)
            wrote_clause = f"no further requested writes; earlier commits: {subjects}"
        else:
            wrote_clause = "this verb wrote nothing"
        for d in result.stopped_detail:
            note = " (its stopped-state marker could not be durably confirmed)" if d.marker_uncertain else ""
            lines.append(
                f"self-learn: transaction intent {d.id} is STOPPED ({d.reason}){note}; "
                f"{wrote_clause} — every ledger write refuses until it is "
                "cleared. Inspect the offender, then run 'self-learn reconcile "
                f"--clear-intent {d.id}' to accept its current on-disk state, or "
                f"delete <home>/.intents/{d.id}.json by hand."
            )
        super().__init__("\n".join(lines))


@contextlib.contextmanager
def ledger_write(
    home: Path | str, *, earlier_commits: list[str] | None = None
) -> Iterator[RecoverResult]:
    """THE ledger-write wrapper (S-62, §7.2a.5(1)) -- every lock-holding
    ledger commit path takes this instead of a bare
    ``gitops.commit_lock(home)``. ``verbs._ledger_write`` is a thin
    delegate to it (one edit converts every one of that name's ~25 call
    sites); every direct ``gitops.commit_lock(<ledger home>)`` site
    outside the exempt list (§7.2a.5(1): this function itself,
    :func:`recover`, :func:`clear_stopped`, ``ledger.init_home``'s
    fresh/empty takes) converts to a literal ``with intents.
    ledger_write(home):`` too.

    **Ordering (§7.2a.5(2)).** The check runs exactly once per process,
    on the OUTERMOST acquisition of the ledger lock -- tested by asking
    whether ``home``'s lock path is already in :data:`gitops._held_locks`
    BEFORE acquiring, the same re-entrancy test :func:`gitops.
    commit_lock` itself uses -- and strictly BEFORE the caller's own
    ``intents.begin``. A nested acquire (this process already holds the
    lock) is a pure pass-through: recovery does NOT re-run, which is
    what makes the in-flight transaction's OWN intent exempt BY
    ORDERING -- it does not exist yet when the outermost check ran, so
    there is nothing to identify and no id to thread. (Re-running the
    check on a nested acquire, after the caller's own ``intents.begin``,
    would see that intent with every ``new_sha`` still null, classify it
    restorable, and undo the live transaction's own writes mid-flight —
    the single sharpest edge in this whole design, and the mandatory
    mutation §7.2a.8 names.)

    Raises :class:`LedgerStoppedError` before yielding when recovery
    leaves anything STOPPED, so a caller's own first mutation never
    runs. On success yields the :class:`RecoverResult` (empty on a
    nested acquire, since recovery only ever runs on the outermost
    one) — callers that want to announce a roll-forward/restore
    ("finish and tell", §7.2a.5(3)) read it from there.

    ``earlier_commits`` (§7.2a.5(4), multi-span verbs only): subjects of
    commits THIS SAME invocation already landed in an earlier outer
    lock span of its own, before this acquisition. A single-span verb
    (nearly every call site) never passes it. A multi-span verb
    (``verbs.recompile``'s ``--adopt`` commit, then a later per-target
    span) threads its own accumulator through so a STOP found at a
    LATER span reports "no further requested writes" truthfully,
    rather than the single-span "this verb wrote nothing" -- the
    earlier commits are the verb's own completed work, and hiding them
    behind the refusal's exit code would be the exact under-reporting
    §7.2a.5(4)(b) forbids for a single acquisition's own recoveries."""
    home = Path(home)
    key = str(gitops.commit_lock_path(home))
    already_held = key in gitops._held_locks  # noqa: SLF001 -- same re-entrancy test commit_lock uses
    with gitops.commit_lock(home):
        if already_held:
            yield RecoverResult()
            return
        yield recover_or_raise(home, earlier_commits=earlier_commits)


def announce_recovered(result: RecoverResult) -> None:
    """§7.2a.5(3), the ATTENDED half of "finish and tell": prints, to
    stderr, the same wording :func:`reconcile.reconcile`'s own CLI
    surface (``cli._cmd_reconcile``) uses for a roll-forward/restore,
    for every attended ledger-write call site (every direct caller of
    :func:`ledger_write` outside the unattended list §7.2a.5(3) names
    by name -- the miner's landing commit, the worker's commit and
    harvest locks, and ``telemetry.flush`` when the miner or worker
    calls it, which log each id on their own line instead). A no-op on
    a nested acquire or a clean outermost one (both yield an empty
    :class:`RecoverResult`), so calling this unconditionally at every
    attended site is safe -- only the genuinely populated outermost
    result ever prints anything."""
    for intent_id in result.rolled_forward:
        print(
            f"self-learn: recovered {intent_id} (rolled forward: its commit "
            "landed — the host phase did not run; run 'self-learn recompile')",
            file=sys.stderr,
        )
    for intent_id in result.restored:
        print(
            f"self-learn: recovered {intent_id} (restored: its mutation was undone)",
            file=sys.stderr,
        )


#: `clear_stopped`'s own lock acquisition: bounded short, never the
#: 150s producer default -- a live writer means "wait a moment and
#: retry", not "hang the CLI".
_CLEAR_INTENT_TIMEOUT = 5.0


def clear_stopped(home: Path | str, intent_id: str) -> str:
    """§7.2a.6's clear leg — ``self-learn reconcile --clear-intent
    <id>``. Removes ``<home>/.intents/<id>.json`` ONLY if *intent_id*
    classifies STOPPED under §7.2a.4's rule, decided in the SAME
    protected span as the deletion: unreadable; already carrying the
    persisted ``stopped`` field; or — for an unmarked file — THIS
    call's own recovery attempt on it, made in this span, has just
    failed. An unmarked intent that RECOVERS (finishes) is recovered and
    reported, not cleared — a ``status`` snapshot taken earlier
    authorises nothing; only the attempt made right here does.

    Exempt from :func:`ledger_write`'s own check (§7.2a.5(1)), for the
    same reason :func:`recover` is: it must run BEFORE that check would
    refuse on the very intent being cleared, or the clear could never
    run at all.

    Returns one of ``"cleared"`` / ``"recovered"`` (not cleared) /
    ``"not-found"`` / ``"refused"`` (a live writer holds the lock)."""
    home = Path(home)
    path = intents_dir(home) / f"{intent_id}.json"
    try:
        with gitops.commit_lock(home, timeout=_CLEAR_INTENT_TIMEOUT):
            if not path.is_file():
                return "not-found"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
                return "cleared"
            try:
                intent = _from_dict(home, data)
            except (ValueError, KeyError):
                path.unlink(missing_ok=True)
                return "cleared"
            if intent.stopped is not None:
                path.unlink(missing_ok=True)
                return "cleared"
            # Unmarked: attempt the exact recovery an ordinary run would,
            # in THIS span. Recovers -> report it, never clear. Fails ->
            # `_recover_one` has already persisted the `stopped` field
            # (the demonstrated failure IS the authorisation) and this
            # call now deletes the file that failure was written to.
            # `GitOpsError` is caught here too, same reason as `recover`'s
            # own call site: a wedged `git reset` inside THIS span is a
            # failed attempt, not the OUTER `except gitops.GitOpsError:
            # return "refused"` below's case (this call already holds
            # the lock throughout, so nothing here is ever "a live
            # writer") -- left uncaught, it would escape to that outer
            # handler and mislabel the failure instead of clearing it.
            probe = RecoverResult()
            try:
                _recover_one(home, intent, probe)
            except (OSError, ValueError, KeyError, gitops.GitOpsError):
                pass
            if probe.acted:
                return "recovered"
            path.unlink(missing_ok=True)
            return "cleared"
    except gitops.GitOpsError:
        return "refused"


@dataclass(frozen=True)
class IntentStatus:
    """One intent's read-only classification (§7.2a.7). ``cls`` is
    ``"busy"`` (the probe found the lock held — this intent is
    somebody's, not classified further), ``"stopped"``, or
    ``"pending"``. ``reason``/``at`` are set only for ``"stopped"``."""

    id: str
    cls: str
    reason: str | None = None
    at: str | None = None


@dataclass(frozen=True)
class StatusClass:
    """§7.2a.7's whole-home snapshot. ``probe`` is ``"ok"`` (the lock
    was free; ``intents`` reflects what was read while holding the
    probe), ``"busy"`` (contention: a transaction or a recovery is in
    flight right now), or ``"error"`` (the probe itself failed for a
    reason other than contention — never rendered as "free")."""

    probe: str
    intents: list[IntentStatus] = field(default_factory=list)
    error: str | None = None

    @property
    def stopped(self) -> list[IntentStatus]:
        return [i for i in self.intents if i.cls == "stopped"]

    @property
    def busy(self) -> bool:
        return self.probe == "busy"


def classify_status(home: Path | str) -> StatusClass:
    """§7.2a.7: read-only, non-blocking, ONE coherent snapshot — never
    :func:`gitops._flock_lock`/`commit_lock` (that helper truncates the
    holder's pid on open and is the MUTATING house pattern). Opens the
    lock file ``O_RDONLY|O_CREAT`` (an empty file created when absent is
    the only byte this can cause, and it is not a ledger write; it never
    truncates, so a live holder's pid survives being probed) and takes
    ``LOCK_EX|LOCK_NB`` exactly once — the only lock interaction this
    function performs. On contention every intent on disk is
    ``"busy"``, precedence over any marker it might carry (a marker
    under a live holder is a HISTORICAL failed attempt, not current
    state). Never mutates, never runs recovery."""
    home = Path(home)
    d = intents_dir(home)
    try:
        lock_path = gitops.commit_lock_path(home)
    except gitops.GitOpsError as exc:
        return StatusClass(probe="error", error=str(exc))
    try:
        fh = os.open(str(lock_path), os.O_RDONLY | os.O_CREAT)
    except OSError as exc:
        return StatusClass(probe="error", error=str(exc))
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            names = [f.stem for f in sorted(d.glob("*.json"))] if d.is_dir() else []
            return StatusClass(probe="busy", intents=[IntentStatus(id=n, cls="busy") for n in names])
        except OSError as exc:
            return StatusClass(probe="error", error=str(exc))
        try:
            out: list[IntentStatus] = []
            if d.is_dir():
                for f in sorted(d.glob("*.json")):
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                    except FileNotFoundError:
                        # Vanished between listing and reading, under
                        # the probe: an observed absence, classified as
                        # neither pending nor stopped (§7.2a.7).
                        continue
                    except (OSError, ValueError):
                        out.append(IntentStatus(id=f.stem, cls="stopped", reason="unreadable intent file"))
                        continue
                    stopped = data.get("stopped")
                    if stopped:
                        out.append(
                            IntentStatus(
                                id=data.get("id", f.stem), cls="stopped",
                                reason=stopped.get("reason"), at=stopped.get("at"),
                            )
                        )
                    else:
                        out.append(IntentStatus(id=data.get("id", f.stem), cls="pending"))
            return StatusClass(probe="ok", intents=out)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        os.close(fh)
