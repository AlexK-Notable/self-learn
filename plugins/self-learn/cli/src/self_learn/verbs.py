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
mutation. Crash between compile and ledger op = compiled-but-uncommitted;
recovery is TWO steps (tested, audit 2026-07-15): the bare re-run refuses
on the now-dirty target — commit/stash the half-applied compile, then
re-run ``route`` (regeneration is idempotent, so the committed content
survives byte-identical).

Compile-set note: regenerating a managed section gathers every resolved
record routed to that target — skill-md from the record's own bucket;
claude-md across ALL buckets, split by scope (``user`` → the chezmoi-managed
user file, everything else → ``<home>/CLAUDE.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import gitops, sentinel, telemetry
from .chezmoi import compile_user_scope
from .compilers import compile_managed_file, compile_reference
from .ledger import discover_buckets
from .ledger_ops import (
    PROPOSAL_DESTINATIONS,
    bucket_dir_for_scope,
    defer_record,
    find_record_path,
    read_proposal,
    resolve_record,
    supersede_record,
    validate_merge_proposal,
    validate_proposal,
)
from .records import Record, RecordError, _validate_follow_up
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
    "confirm_held",
    "confirm_recurrence",
    "defer",
    "followup_done",
    "graduate",
    "link_contradicts",
    "push_pending",
    "reject",
    "route",
    "route_direct",
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

    def over_cap_note(self) -> str | None:
        """02 §4: the compiler flags-on-exceed; callers MUST surface it —
        the next review session opens with a graduation card."""
        cr = self.compile_result
        if cr is not None and getattr(cr, "over_cap", False):
            return (
                f"WARNING: managed section over cap ({getattr(cr, 'cap_reason', '?')})"
                " — graduate the oldest entries; next review opens with a"
                " graduation card (02 §4)"
            )
        return None
    sentinel_owned: bool = False
    diff: str | None = None  # route_direct: staged diff (pre-commit), T8 prints it
    warnings: list[str] = field(default_factory=list)  # callers MUST print


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


def _orphaned_followup_warning(path: Path, record_id: str) -> list[str]:
    """A record leaving 'routed' with an OPEN follow-up drops off the
    open-follow-up list (status gate) — say so loudly instead of letting
    the planned upgrade dead-letter (E-2; audit 2026-07-15)."""
    try:
        record = Record.from_path(path)
    except RecordError:
        return []
    fu = record.follow_up
    if fu is None or record.status != "routed":
        return []
    return [
        f"WARNING: {record_id} carries an open follow-up "
        f"({fu.get('action')!r}) — this resolution retires it from the "
        "open list; if the upgrade is still wanted, put it on the "
        "successor (route --follow-up) or a fresh capture"
    ]


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


def _parse_dest(dest: str) -> tuple[str, str | None]:
    """Parse an explicit ``--dest`` value. Returns (destination,
    named-reference-file) — the ``reference:<file>`` form names an existing
    references file (08 §1 References-compiler pin's "another existing
    references file")."""
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


def _resolve_destination(
    bucket_dir: Path, record_id: str, dest: str | None
) -> tuple[str, str | None]:
    """Destination for a route: ``--dest`` overrides; else the proposal
    sibling; neither → error."""
    if dest is not None:
        return _parse_dest(dest)
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


def _compile_for_destination(
    home: Path,
    bucket_dir: Path,
    record: Record,
    shadow: Record,
    destination: str,
    ref_name: str | None,
    exclude: set[str],
    *,
    user_claude_md: Path | str | None,
    chezmoi_bin: str,
    message: str,
) -> tuple[object, Path | None]:
    """The per-destination compile step, shared by :func:`route` (existing
    pending record) and :func:`route_direct` (teach --route's not-yet-on-disk
    record). ``record`` carries scope/identity; ``shadow`` is the routed
    compile input (for route_direct they are the same object). Returns
    (compile_result, target_path) — target_path is staged iff the target
    lives in the ledger repo (None for the chezmoi-managed user file)."""
    compile_result: object | None = None
    target_path: Path | None = None

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

    else:  # unreachable: enum-checked by callers
        raise VerbError(f"unroutable destination {destination!r}")

    # surface-budget event (11 §4.3: compilers, inside verb flow) — the
    # attention-tax ledger. Spooled here, flushed by the calling verb.
    telemetry.spool_quiet(
        "surface-budget",
        target=destination,
        words=getattr(compile_result, "word_count", None),
        overflow=bool(getattr(compile_result, "over_cap", False)),
    )

    return compile_result, target_path


# -------------------------------------------------------------------- verbs


def _load_cluster(
    home: Path, bucket_dir: Path, record_id: str, cluster_id: str
) -> tuple[Path, list[str]]:
    """Collapse preflight (08 §7.1 Merge-proposals pin): the merge proposal
    must exist, be schema-valid, name the survivor, and every member must
    still be pending in THIS bucket (any member resolved ⇒ the cluster is
    invalidated — the worker sweeps it; refuse here)."""
    merge_path = bucket_dir / "proposals" / f"{cluster_id}.yaml"
    if not merge_path.is_file():
        raise VerbError(f"no merge proposal {cluster_id} in {bucket_dir}")
    data = read_proposal(merge_path)
    validate_merge_proposal(data)
    members = list(data["records"])
    if record_id not in members:
        raise VerbError(
            f"survivor {record_id} is not a member of {cluster_id} "
            f"({', '.join(members)})"
        )
    for rid in members:
        if not (bucket_dir / "pending" / f"{rid}.md").is_file():
            raise VerbError(
                f"cluster {cluster_id} is invalidated: member {rid} is no "
                "longer pending — the worker sweeps it; nothing to collapse"
            )
    return merge_path, [rid for rid in members if rid != record_id]


def route(
    home: Path | str,
    record_id: str,
    *,
    dest: str | None = None,
    note: str | None = None,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
    follow_up: dict | None = None,
    collapse: str | None = None,
) -> VerbResult:
    """Route a pending record into canon. See the module docstring for the
    pinned sequence; commit message ``self-learn: route lrn-… → <target>``
    (+ `` (supersedes lrn-…)`` when the record completes a
    ``teach --supersedes`` capture — old record superseded in the SAME
    commit). ``follow_up`` (11 §2.1: {action, unblocks_on?, note?}) rides
    the routing block — known-partial coverage, status stays terminal."""
    home = Path(home)
    if follow_up is not None:
        try:
            _validate_follow_up(follow_up)
        except RecordError as exc:
            raise VerbError(str(exc)) from exc
    path = find_record_path(home, record_id, statuses=("pending",))

    # (a) scan the record file BEFORE trusting its contents.
    _scan_or_refuse([path], note)
    record = Record.from_path(path)
    old_id = record.supersedes
    if old_id is not None:
        old_path = find_record_path(home, old_id)
        _scan_or_refuse([old_path], None)  # this verb rewrites it too (P2-7)

    losers: list[str] = []
    merge_path: Path | None = None
    if collapse is not None:
        merge_path, losers = _load_cluster(
            home, path.parent.parent, record_id, collapse
        )
        # every loser file is rewritten by this verb (P2-7)
        _scan_or_refuse(
            [path.parent / f"{rid}.md" for rid in losers], None
        )

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

        if collapse is not None:
            # Pinned commit shape: route lrn-X → <target> (collapse
            # merge-<cid>, supersedes lrn-Y, lrn-Z)
            suffix = f" (collapse {collapse}, supersedes {', '.join(losers)})"
        else:
            suffix = f" (supersedes {old_id})" if old_id else ""
        message = f"self-learn: route {record_id} → {destination}{suffix}"
        routed_at = _now_iso()

        if collapse is not None:
            # Merge the losers into the survivor's PENDING file first:
            # evidence gains their provenance (append-only is the door),
            # sightings becomes the cluster total. The shadow below then
            # reads the merged content, so the compile sees it too.
            loser_records = [
                Record.from_path(path.parent / f"{rid}.md") for rid in losers
            ]
            total_sightings = record.sightings + sum(
                lr.sightings for lr in loser_records
            )
            survivor = Record.from_path(path)
            for lr in loser_records:
                for entry in lr.evidence:
                    survivor.append_evidence(entry)
            survivor.set_sightings(total_sightings)
            survivor.write(path)

        # In-memory routed copy: the compile input for the record being
        # routed (its file is only rewritten at the ledger op below). The
        # follow_up rides here too, so a malformed one fails BEFORE the
        # compile step, never between compile and ledger op.
        shadow_routing = {
            "routed_at": routed_at,
            "destination": destination,
            "by": "human",
        }
        if follow_up is not None:
            shadow_routing["follow_up"] = dict(follow_up)
        shadow = Record.from_path(path)
        shadow.set_routing(shadow_routing)
        shadow.set_status("routed")

        exclude = {record_id} | ({old_id} if old_id else set())
        compile_result, target_path = _compile_for_destination(
            home,
            bucket_dir,
            record,
            shadow,
            destination,
            ref_name,
            exclude,
            user_claude_md=user_claude_md,
            chezmoi_bin=chezmoi_bin,
            message=message,
        )

        # (d) the ledger op — same routed_at the compile used.
        touched = resolve_record(
            home,
            record_id,
            "routed",
            destination=destination,
            routed_at=routed_at,
            note=note,
            follow_up=follow_up,
        )
        if old_id is not None:
            # teach --supersedes completion-at-route: SAME commit (08 §1
            # Corrective-supersession pin).
            touched = touched + supersede_record(home, old_id, record_id)
        for loser_id in losers:
            # collapse: losers superseded by the survivor, SAME commit;
            # their analysis proposals (and the merge proposal, via the
            # survivor's own sibling sweep) are removed by resolve_record.
            touched = touched + supersede_record(home, loser_id, record_id)
        if merge_path is not None and merge_path.exists():
            # belt-and-braces: the sibling sweep removes it when it names
            # the survivor; an inconsistent leftover is removed here.
            from .ledger_ops import _remove_file

            if _remove_file(home, merge_path):
                touched = touched + [merge_path]
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


def route_direct(
    home: Path | str,
    record: Record,
    *,
    dest: str,
    note: str | None = None,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
) -> VerbResult:
    """``teach --route``'s writer (02 §2 lifecycle note): the composed,
    not-yet-on-disk record is written DIRECTLY into its bucket's
    ``resolved/`` as ``status: routed`` — never transiting ``pending/``.

    Same pinned sequence as :func:`route` (scan, sentinel self-hold +
    heartbeat, dirty-target abort, compile, targeted stage, pinned commit
    ``self-learn: route lrn-… → <target>``, per-verb push, release-iff-
    owned), same ``--supersedes`` completion in the SAME commit. The
    destination is required — the caller (structured ``--dest``, or the
    one-shot analyst) supplies it; there is no proposal sibling to read.
    ``VerbResult.diff`` carries the staged pre-commit diff (``git diff
    --cached`` of the touched paths) for T8 to print — invocation is the
    approval, so the diff is informational, never a prompt."""
    home = Path(home)
    destination, ref_name = _parse_dest(dest)
    if destination in M3_DESTINATIONS:
        raise DestinationNotBuilt(
            f"destination {destination!r} is not built until M3"
        )

    # (a) P2-7 rider: scan every byte this call publishes — the FULL record
    # text, frontmatter included, exactly like the on-disk verbs' whole-file
    # scan (audit 2026-07-15: body-only scanning let frontmatter metadata
    # — env values, evidence session ids — reach a pushed commit unscanned).
    findings = secret_scan(record.to_text())
    if findings:
        raise SecretRefusal(
            "secret scan hit — refusing this route (P2-7; no bypass):\n"
            + format_refusal(findings),
            findings,
        )
    if note:
        note_hits = secret_scan(note)
        if note_hits:
            raise SecretRefusal(
                "secret scan hit in --note — refusing this route (P2-7; "
                "no bypass):\n" + format_refusal(note_hits),
                note_hits,
            )
    old_id = record.supersedes
    if old_id is not None:
        old_path = find_record_path(home, old_id)
        _scan_or_refuse([old_path], None)  # this verb rewrites it too (P2-7)

    # (b) sentinel self-hold + heartbeat.
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        bucket_dir = bucket_dir_for_scope(home, record.scope)
        resolved_path = bucket_dir / "resolved" / f"{record.id}.md"
        if resolved_path.exists() or (
            bucket_dir / "pending" / f"{record.id}.md"
        ).exists():
            raise VerbError(f"record {record.id} already exists in {bucket_dir}")

        suffix = f" (supersedes {old_id})" if old_id else ""
        message = f"self-learn: route {record.id} → {destination}{suffix}"

        # The record itself becomes the routed compile input — no shadow
        # needed, its only on-disk form will already be the routed one.
        record.set_routing(
            {"routed_at": _now_iso(), "destination": destination, "by": "human"}
        )
        record.set_status("routed")
        if note is not None:
            record.set_resolution_note(note)

        exclude = {record.id} | ({old_id} if old_id else set())
        compile_result, target_path = _compile_for_destination(
            home,
            bucket_dir,
            record,
            record,
            destination,
            ref_name,
            exclude,
            user_claude_md=user_claude_md,
            chezmoi_bin=chezmoi_bin,
            message=message,
        )

        # (d) write directly to resolved/ — the pending/ dir is never touched.
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        record.write(resolved_path)
        touched: list[Path] = [resolved_path]
        if old_id is not None:
            # teach --supersedes completion-at-route: SAME commit (08 §1
            # Corrective-supersession pin).
            touched = touched + supersede_record(home, old_id, record.id)
        if target_path is not None:
            touched = touched + [target_path]

        # (f)/(g) targeted stage, diff for the caller, pinned commit, push.
        staged = gitops.stage(home, touched)
        diff = gitops.staged_diff(home, staged)
        sha = gitops.commit(home, message, body=note)
        push = None if no_push else gitops.push_with_retry(home)
        return VerbResult(
            action="route",
            record_id=record.id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            compile_result=compile_result,
            sentinel_owned=hold.owned,
            diff=diff,
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
    warnings = _orphaned_followup_warning(path, record_id)
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
            warnings=warnings,
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
    warnings = _orphaned_followup_warning(old_path, old_id)
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
            warnings=warnings,
        )
    finally:
        hold.release()


def followup_done(
    home: Path | str,
    record_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Clear a routed record's open follow-up (11 §2.5): move
    ``routing.follow_up`` to a dated ``follow_up_done`` block. Standard
    resolution-verb sequence; commit ``self-learn: follow-up done on
    lrn-…``; the note lands in ``follow_up_done.done_note`` + the commit
    body — ``resolution_note`` stays write-once and untouched (02 §2)."""
    home = Path(home)
    path = find_record_path(home, record_id)
    _scan_or_refuse([path], note)
    record = Record.from_path(path)
    if record.follow_up is None:
        raise VerbError(
            f"record {record_id} has no open follow-up — nothing to clear"
        )
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        try:
            record.complete_follow_up(done_note=note)
        except RecordError as exc:
            raise VerbError(str(exc)) from exc
        record.write(path)
        message = f"self-learn: follow-up done on {record_id}"
        staged, sha, push = _commit_and_push(home, [path], message, note, no_push)
        return VerbResult(
            action="followup-done",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def confirm_recurrence(
    home: Path | str,
    record_id: str,
    *,
    event_ref: str,
    tolerate: bool = False,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Human confirmation of a recurrence suspect (11 §2.2/§2.5): append
    to the record's append-only ``recurrences:`` list, copying the minimal
    facts (ts, origin) OUT of the telemetry event named by ``event_ref``
    (the event's ``nonce``); the ref stays a courtesy pointer. Tolerate
    (``--tolerate --note "<why the rule stays>"``) records the why in
    ``recurrences[].note`` — NEVER ``resolution_note`` (write-once, 02 §2).
    Commit: ``self-learn: recurrence confirmed on lrn-…``."""
    home = Path(home)
    if tolerate and not note:
        raise VerbError(
            "--tolerate needs --note: 'the rule stays' without the why is "
            "exactly the dead-letter 11 §2.2 exists to prevent"
        )
    event = next(
        (
            e
            for e in telemetry.read_events(home)
            if e.get("kind") == "recurrence-suspect"
            and e.get("nonce") == event_ref
        ),
        None,
    )
    if event is None:
        raise VerbError(
            f"no recurrence-suspect event with nonce {event_ref!r} in the "
            "tracked telemetry — flush first (`self-learn telemetry flush`) "
            "or check `self-learn report`"
        )
    path = find_record_path(home, record_id)
    _scan_or_refuse([path], note)
    record = Record.from_path(path)
    if record.status != "routed":
        raise VerbError(
            f"record {record_id} is {record.status!r} — recurrences confirm "
            "against LIVE routed coverage (11 §2.2)"
        )
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        entry = {
            "ts": event.get("ts"),
            "origin": event.get("origin"),
            "ref": event_ref,
        }
        if note is not None:
            entry["note"] = note
        try:
            record.append_recurrence(entry)
        except RecordError as exc:
            raise VerbError(str(exc)) from exc
        record.write(path)
        message = f"self-learn: recurrence confirmed on {record_id}"
        staged, sha, push = _commit_and_push(home, [path], message, note, no_push)
        return VerbResult(
            action="confirm-recurrence",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def confirm_held(
    home: Path | str,
    record_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """A human observed the rule working (11 §2.2): write
    ``last_confirmed`` (today). Age-since-confirmation, not
    age-since-capture, is the staleness metric. Commit:
    ``self-learn: confirmed holding lrn-…``."""
    home = Path(home)
    path = find_record_path(home, record_id)
    _scan_or_refuse([path], note)
    record = Record.from_path(path)
    if record.status != "routed":
        raise VerbError(
            f"record {record_id} is {record.status!r} — only live routed "
            "rules can be confirmed as holding"
        )
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        record.set_last_confirmed(_now_iso()[:10])
        record.write(path)
        message = f"self-learn: confirmed holding {record_id}"
        staged, sha, push = _commit_and_push(home, [path], message, note, no_push)
        return VerbResult(
            action="confirm-held",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def link_contradicts(
    home: Path | str,
    record_id: str,
    target: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """First-class contradiction edge (11 §2.4): append ``target`` (a
    record id or canon anchor) to ``links.contradicts``. Commit:
    ``self-learn: link lrn-… contradicts <target>``."""
    home = Path(home)
    path = find_record_path(home, record_id)
    _scan_or_refuse([path], note)
    if secret_scan(target):
        raise SecretRefusal(
            "secret scan hit in the contradicts target — refusing (P2-7)",
            secret_scan(target),
        )
    record = Record.from_path(path)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        try:
            record.append_contradicts(target)
        except RecordError as exc:
            raise VerbError(str(exc)) from exc
        record.write(path)
        message = f"self-learn: link {record_id} contradicts {target}"
        staged, sha, push = _commit_and_push(home, [path], message, note, no_push)
        return VerbResult(
            action="link-contradicts",
            record_id=record_id,
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
