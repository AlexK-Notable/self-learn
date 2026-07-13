"""Resolution verbs (T7): route / reject / defer / graduate / supersede.

Function layer only — T8 wires these into the CLI. Public signatures:

    route(home, record_id, *, dest=None, note=None, no_push=False,
          user_claude_md=None, chezmoi_bin="chezmoi") -> VerbResult
    reject(home, record_id, *, note=None, no_push=False) -> VerbResult
    defer(home, record_id, *, until=None, note=None, no_push=False) -> VerbResult
    graduate(home, record_id, *, note=None, no_push=False) -> VerbResult
    supersede(home, old_id, new_id, *, note=None, no_push=False) -> VerbResult
    push_pending(home) -> gitops.PushResult          # bare `self-learn push`

Every verb runs the pinned sequence (08 §1 Resolution-verbs / Secret-scan /
Sentinel-scoping pins; 02 §2 commit formats):

(a) FULL-record-file secret scan (P2-7): the verb scans every record file
    it will rewrite (plus the ``--note`` text, which is published via the
    record and the commit message). A hit refuses the verb — span + rule in
    the error, nothing written, no bypass.
(b) Sentinel self-hold: take the autosync-pause sentinel unless another
    LIVE holder exists (skip-if-held-by-other), then heartbeat. Released in
    a ``finally`` — but only if this verb created it.
(c) Dirty-compile-target abort (route only): if the compile target has
    unrelated uncommitted changes, abort with "commit/stash first".
    Non-compiling verbs check nothing.
(d/e) The ledger op via ledger_ops; route additionally compiles its target
    (destination from the proposal sibling, ``--dest`` overrides; both
    absent → error). ``new-skill``/``hook`` are M3 (exit 2).
(f) Stage ONLY touched paths; commit with the pinned message; note → body.
(g) Push (pinned retry) unless ``no_push``.
(h) Release the sentinel iff owned.

Route ordering note (recorded structural decision): the compile step runs
BEFORE the ledger op, against an in-memory routed copy of the record. The
lettered checklist reads (d) then (e), but a literal order is impossible —
the proposal sibling must be read before ``resolve_record`` deletes it —
and compile-first is what makes the §5 chezmoi playbook true ("abort that
route … the record stays pending"): a ChezmoiAbort fires before any ledger
mutation. Crash between compile and ledger op = compiled-but-uncommitted,
recoverable by re-running ``route`` (regeneration is idempotent).

Compile-set note: regenerating a managed section gathers every resolved
record routed to that target — skill-md from the record's own bucket;
claude-md across ALL buckets, split by scope (``user`` → the chezmoi-managed
user file, everything else → ``<home>/CLAUDE.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import gitops, sentinel
from .chezmoi import compile_user_scope
from .compilers import compile_managed_file, compile_reference
from .ledger import discover_buckets
from .ledger_ops import (
    PROPOSAL_DESTINATIONS,
    defer_record,
    find_record_path,
    read_proposal,
    resolve_record,
    supersede_record,
    validate_proposal,
)
from .records import Record, RecordError
from .scan import format_refusal
from .scan import scan as secret_scan

__all__ = [
    "DEFAULT_USER_CLAUDE_MD",
    "DestinationNotBuilt",
    "DirtyTargetError",
    "NoProposalError",
    "SecretRefusal",
    "VerbError",
    "VerbResult",
    "defer",
    "graduate",
    "push_pending",
    "reject",
    "route",
    "supersede",
]

DEFAULT_USER_CLAUDE_MD = Path("~/.claude/CLAUDE.md")

#: Destinations whose compilers land at M3 (08 §1 route pin: exit 2 "M3").
M3_DESTINATIONS = frozenset({"new-skill", "hook"})


class VerbError(Exception):
    """A resolution verb refused or failed before committing."""

    exit_code = 1


class SecretRefusal(VerbError):
    """P2-7: the full-record-file scan hit — nothing written, no bypass."""

    def __init__(self, message: str, hits: list) -> None:
        super().__init__(message)
        self.hits = hits


class DirtyTargetError(VerbError):
    """The compile target has unrelated uncommitted changes."""


class NoProposalError(VerbError):
    """route without ``--dest`` and without a proposal sibling."""


class DestinationNotBuilt(VerbError):
    """new-skill / hook route: the compiler lands at M3."""

    exit_code = 2


@dataclass
class VerbResult:
    """What one verb did — T8 renders this."""

    action: str
    record_id: str
    commit_message: str
    commit_sha: str
    staged: list[Path] = field(default_factory=list)
    push: gitops.PushResult | None = None  # None = --no-push
    compile_result: object | None = None  # SectionResult | ReferenceResult | UserScopeResult
    sentinel_owned: bool = False


# ------------------------------------------------------------------ helpers


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_str(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    return str(value)


def _scan_or_refuse(paths: list[Path], note: str | None) -> None:
    """(a) Full-record-file secret scan (P2-7) + the note text. A hit
    refuses the verb with span + rule; nothing has been written yet."""
    findings: list[tuple[str, list]] = []
    for path in paths:
        hits = secret_scan(path.read_text(encoding="utf-8"))
        if hits:
            findings.append((str(path), hits))
    if note:
        hits = secret_scan(note)
        if hits:
            findings.append(("--note", hits))
    if not findings:
        return
    parts = [f"{label}:\n{format_refusal(hits)}" for label, hits in findings]
    all_hits = [h for _, hits in findings for h in hits]
    raise SecretRefusal(
        "secret scan hit — refusing this verb (P2-7; no bypass):\n"
        + "\n".join(parts),
        all_hits,
    )


def _abort_if_dirty(home: Path, target: Path) -> None:
    if gitops.paths_dirty(home, target):
        raise DirtyTargetError(
            f"compile target {target} has unrelated uncommitted changes — "
            "commit/stash first, then re-run"
        )


def _commit_and_push(
    home: Path,
    touched: list[Path],
    message: str,
    note: str | None,
    no_push: bool,
) -> tuple[list[Path], str, gitops.PushResult | None]:
    staged = gitops.stage(home, touched)
    sha = gitops.commit(home, message, body=note)
    push = None if no_push else gitops.push_with_retry(home)
    return staged, sha, push


def _resolve_destination(
    bucket_dir: Path, record_id: str, dest: str | None
) -> tuple[str, str | None]:
    """Destination for a route: ``--dest`` overrides; else the proposal
    sibling; neither → error. Returns (destination, named-reference-file)
    — the ``reference:<file>`` form names an existing references file
    (08 §1 References-compiler pin's "another existing references file")."""
    if dest is not None:
        if dest.startswith("reference:"):
            name = dest.split(":", 1)[1]
            if not name:
                raise VerbError("reference:<file> needs a file name")
            return "reference", name
        if dest not in PROPOSAL_DESTINATIONS:
            raise VerbError(
                f"--dest must be one of {list(PROPOSAL_DESTINATIONS)} "
                f"(or reference:<file>), got {dest!r}"
            )
        return dest, None
    proposal_path = bucket_dir / "proposals" / f"{record_id}.yaml"
    if not proposal_path.is_file():
        raise NoProposalError(
            f"no proposal for {record_id} — pass --dest or run review"
        )
    data = read_proposal(proposal_path)
    validate_proposal(data)
    return data["destination"], None


def _routed_to(
    bucket_dirs: list[Path],
    destination: str,
    *,
    scope_pred=None,
    exclude: frozenset[str] | set[str] = frozenset(),
) -> list[Record]:
    """Resolved records routed to ``destination`` — the compile set."""
    out: list[Record] = []
    for bdir in bucket_dirs:
        resolved = bdir / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except RecordError:
                continue  # unparseable resolved file: never a compile input
            if record.id in exclude or record.status != "routed":
                continue
            if (record.routing or {}).get("destination") != destination:
                continue
            if scope_pred is not None and not scope_pred(record.scope):
                continue
            out.append(record)
    return out


def _all_bucket_dirs(home: Path) -> list[Path]:
    return [b.path for b in discover_buckets(home)]


# -------------------------------------------------------------------- verbs


def route(
    home: Path | str,
    record_id: str,
    *,
    dest: str | None = None,
    note: str | None = None,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
) -> VerbResult:
    """Route a pending record into canon. See the module docstring for the
    pinned sequence; commit message ``self-learn: route lrn-… → <target>``
    (+ `` (supersedes lrn-…)`` when the record completes a
    ``teach --supersedes`` capture — old record superseded in the SAME
    commit)."""
    home = Path(home)
    path = find_record_path(home, record_id, statuses=("pending",))

    # (a) scan the record file BEFORE trusting its contents.
    _scan_or_refuse([path], note)
    record = Record.from_path(path)
    old_id = record.supersedes
    if old_id is not None:
        old_path = find_record_path(home, old_id)
        _scan_or_refuse([old_path], None)  # this verb rewrites it too (P2-7)

    # (b) sentinel self-hold + heartbeat.
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        bucket_dir = path.parent.parent
        destination, ref_name = _resolve_destination(bucket_dir, record_id, dest)
        if destination in M3_DESTINATIONS:
            raise DestinationNotBuilt(
                f"destination {destination!r} is not built until M3"
            )

        suffix = f" (supersedes {old_id})" if old_id else ""
        message = f"self-learn: route {record_id} → {destination}{suffix}"
        routed_at = _now_iso()

        # In-memory routed copy: the compile input for the record being
        # routed (its file is only rewritten at the ledger op below).
        shadow = Record.from_path(path)
        shadow.set_routing(
            {"routed_at": routed_at, "destination": destination, "by": "human"}
        )
        shadow.set_status("routed")

        exclude = {record_id} | ({old_id} if old_id else set())
        compile_result: object | None = None
        target_path: Path | None = None  # staged iff the target is in-repo

        if destination == "skill-md":
            if not record.scope.startswith("skill:"):
                raise VerbError(
                    "skill-md destination needs skill:<name> scope, "
                    f"got {record.scope!r} — use claude-md or reference"
                )
            target = bucket_dir.parent / "SKILL.md"
            _abort_if_dirty(home, target)  # (c)
            records = _routed_to([bucket_dir], "skill-md", exclude=exclude)
            compile_result = compile_managed_file(target, records + [shadow])
            target_path = target

        elif destination == "claude-md":
            if record.scope == "user":
                # E-17: the user file is chezmoi-managed; the guarded flow
                # (drift/dirty aborts, re-add, dotfiles commit+push) owns it.
                # It lives in the dotfiles repo, so nothing is staged here.
                target = Path(
                    user_claude_md
                    if user_claude_md is not None
                    else DEFAULT_USER_CLAUDE_MD
                ).expanduser()
                records = _routed_to(
                    _all_bucket_dirs(home),
                    "claude-md",
                    scope_pred=lambda s: s == "user",
                    exclude=exclude,
                )
                compile_result = compile_user_scope(
                    target,
                    records + [shadow],
                    chezmoi=chezmoi_bin,
                    commit_message=message,
                )
            else:
                target = home / "CLAUDE.md"
                if target.is_file():
                    _abort_if_dirty(home, target)  # (c)
                else:
                    # Judgment call (T7 brief): first route to a repo with no
                    # CLAUDE.md creates it empty and lets the managed-section
                    # bootstrap (08 §1 pin) append the marker pair — refusing
                    # would dead-end claude-md routing on every fresh repo.
                    target.write_text("", encoding="utf-8")
                records = _routed_to(
                    _all_bucket_dirs(home),
                    "claude-md",
                    scope_pred=lambda s: s != "user",
                    exclude=exclude,
                )
                compile_result = compile_managed_file(target, records + [shadow])
                target_path = target

        elif destination == "reference":
            refs_dir = (
                bucket_dir.parent / "references"
                if record.scope.startswith("skill:")
                else home / "references"
            )
            probe = refs_dir / (ref_name or "LEARNINGS.md")
            if probe.is_file():
                _abort_if_dirty(home, probe)  # (c)
            compile_result = compile_reference(refs_dir, shadow, dest=ref_name)
            target_path = compile_result.path

        else:  # unreachable: enum-checked above
            raise VerbError(f"unroutable destination {destination!r}")

        # (d) the ledger op — same routed_at the compile used.
        touched = resolve_record(
            home,
            record_id,
            "routed",
            destination=destination,
            routed_at=routed_at,
            note=note,
        )
        if old_id is not None:
            # teach --supersedes completion-at-route: SAME commit (08 §1
            # Corrective-supersession pin).
            touched = touched + supersede_record(home, old_id, record_id)
        if target_path is not None:
            touched = touched + [target_path]

        # (f)/(g) targeted stage, pinned commit, per-verb push.
        staged, sha, push = _commit_and_push(home, touched, message, note, no_push)
        return VerbResult(
            action="route",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            compile_result=compile_result,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()  # (h) release iff owned


def reject(
    home: Path | str,
    record_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Reject a pending record. Commit: ``self-learn: reject lrn-…``."""
    home = Path(home)
    path = find_record_path(home, record_id, statuses=("pending",))
    _scan_or_refuse([path], note)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        touched = resolve_record(home, record_id, "rejected", note=note)
        message = f"self-learn: reject {record_id}"
        staged, sha, push = _commit_and_push(home, touched, message, note, no_push)
        return VerbResult(
            action="reject",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def defer(
    home: Path | str,
    record_id: str,
    *,
    until=None,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Defer a pending record (default +30 d). Commit: ``self-learn: defer
    lrn-… until <date>``. The note rides the commit body only —
    ``resolution_note`` is reserved for resolutions (02 §2), and deferral
    is not one."""
    home = Path(home)
    path = find_record_path(home, record_id, statuses=("pending",))
    _scan_or_refuse([path], note)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        touched = defer_record(home, record_id, until)
        deferred_until = _date_str(Record.from_path(touched[0]).deferred_until)
        message = f"self-learn: defer {record_id} until {deferred_until}"
        staged, sha, push = _commit_and_push(home, touched, message, note, no_push)
        return VerbResult(
            action="defer",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def graduate(
    home: Path | str,
    record_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Graduate a lesson into authored canon: ``superseded_by: canon``
    (02 §2/§4). Works on a routed record (the hand-weave) or a pending
    already-canon one (the bulk-acknowledge door). Commit: ``self-learn:
    graduate lrn-…``. Metadata-only — the managed-section line drops at
    that target's next compile."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        touched = resolve_record(
            home, record_id, "superseded", superseded_by="canon", note=note
        )
        message = f"self-learn: graduate {record_id}"
        staged, sha, push = _commit_and_push(home, touched, message, note, no_push)
        return VerbResult(
            action="graduate",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def supersede(
    home: Path | str,
    old_id: str,
    new_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Bare metadata-only supersession (08 §1 Corrective-supersession pin):
    mark ``old`` superseded by ``new`` (which must exist). Commit:
    ``self-learn: supersede lrn-old → lrn-new``."""
    home = Path(home)
    if old_id == new_id:
        raise VerbError("a record cannot supersede itself")
    old_path = find_record_path(home, old_id)  # pending OR routed flavor
    find_record_path(home, new_id)  # the replacement must exist
    _scan_or_refuse([old_path], note)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        touched = supersede_record(home, old_id, new_id, note=note)
        message = f"self-learn: supersede {old_id} → {new_id}"
        staged, sha, push = _commit_and_push(home, touched, message, note, no_push)
        return VerbResult(
            action="supersede",
            record_id=old_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def push_pending(home: Path | str) -> gitops.PushResult:
    """The bare ``self-learn push`` verb: publish pending local commits
    with the pinned retry. Read-only w.r.t. records — no sentinel, no
    heartbeat (it mutates nothing the watcher could race)."""
    return gitops.push_pending(Path(home))
