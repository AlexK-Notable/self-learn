"""Resolution verbs (T7): route / reject / defer / graduate / supersede.

Function layer only — T8 wires these into the CLI. Public signatures:

    route(home, record_id, *, dest=None, note=None, no_push=False,
          user_claude_md=None, chezmoi_bin="chezmoi") -> VerbResult
    reject(home, record_id, *, note=None, no_push=False) -> VerbResult
    defer(home, record_id, *, until=None, note=None, no_push=False) -> VerbResult
    graduate(home, record_id, *, note=None, no_push=False) -> VerbResult
    supersede(home, old_id, new_id, *, note=None, no_push=False) -> VerbResult
    push_pending(home) -> PushReport                 # bare `self-learn push`

Every verb runs the pinned sequence (08 §1 Resolution-verbs / Secret-scan /
Sentinel-scoping pins; 02 §2 commit formats; doc 13 §4 two-phase revision):

(a) FULL-record-file secret scan (P2-7): the verb scans every record file
    it will rewrite (plus the ``--note`` text, which is published via the
    record and the commit message). A hit refuses the verb — span + rule in
    the error, nothing written, no bypass.
(b) Sentinel self-hold: take the autosync-pause sentinel unless another
    LIVE holder exists (skip-if-held-by-other), then heartbeat. Released in
    a ``finally`` — but only if this verb created it. The sentinel is
    GLOBAL (doc 13 §4.4): it pauses HOST autosync during the canon apply.
(c) PRE-FLIGHT (canon-touching verbs): resolve the compile target through
    hosts.yaml — H-3: skills root / project host registration is checked
    HERE, and an unregistered project host refuses with ``host not
    registered — self-learn host add <path>`` so the review card says why
    (doc 13 §1 Q2). Dirty-compile-target aborts run against the HOST repo;
    user scope runs the chezmoi drift/dirty preflight. All refusals land
    BEFORE any commit — the record stays pending.
(d) LEDGER commit: the ledger op via ledger_ops (record move + proposal
    sweeps), staged surgically in the LEDGER repo, pinned subject.
(e) HOST phase: compile the target from the now-committed ledger state
    and commit the HOST repo — pinned subject ``self-learn: apply lrn-… →
    <relative target> (<destination>)``. A failure HERE is loud and names
    ``self-learn recompile`` — the ledger is truth, canon is stale-not-
    lost (H-2); NO rollback is attempted.
(f) Push ledger, then push host (pinned retry) unless ``no_push``; a
    failed push is loud but the commit is kept.
(g) Release the sentinel iff owned.

Ledger-only verbs (reject, defer, graduate — the managed-section line
drops at the target's next recompile) stay single-commit in the ledger
repo. ``supersede`` of a ROUTED record is canon-touching: its entry must
drop, so the host phase recompiles the target.

Compile-set note (doc 13): because the ledger op now commits FIRST, the
compile set is read straight off disk — no shadow copies. skill-md
compiles from the record's own skill bucket; claude-md splits by scope:
``user`` → the chezmoi-managed user file (all user-scoped records),
``project`` → that project bucket's records into the registered host's
CLAUDE.md, ``skill:*`` → the skills-root host's own CLAUDE.md (doc 13 §2:
the skills root hosts its own CLAUDE.md canon).
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import gitops, sentinel, telemetry
from .chezmoi import ChezmoiAbort, ChezmoiError, compile_user_scope, preflight_user_scope
from .compilers import (
    CompileError,
    compile_managed_file,
    compile_reference,
    reference_target_path,
)
from .hosts import (
    HostsError,
    is_project_host,
    load_hosts,
    skill_dir_for,
    validate_host_path,
)
from .ledger import discover_buckets
from .ledger_ops import (
    PROPOSAL_DESTINATIONS,
    LedgerOpsError,
    bucket_dir_for_scope,
    bucket_project_path,
    defer_record,
    ensure_project_meta,
    find_record_path,
    read_proposal,
    require_writable_home,
    resolve_record,
    supersede_record,
    validate_merge_proposal,
    validate_proposal,
)
from .records import RECORD_ID_RE, Record, RecordError, _validate_follow_up
from .scan import format_refusal
from .scan import scan as secret_scan

__all__ = [
    "DEFAULT_USER_CLAUDE_MD",
    "DestinationNotBuilt",
    "DirtyTargetError",
    "NoProposalError",
    "PushReport",
    "RecompileEntry",
    "RecompileResult",
    "SecretRefusal",
    "TargetSpec",
    "VerbError",
    "VerbResult",
    "confirm_held",
    "confirm_recurrence",
    "defer",
    "followup_done",
    "graduate",
    "link_contradicts",
    "push_pending",
    "recompile",
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
    # doc 13 §4 two-phase: the HOST half of a canon-touching verb. All None
    # for ledger-only verbs, for the chezmoi user flow (the dotfiles repo
    # commits itself), and after a host-phase failure (drift warning set).
    host_commit_sha: str | None = None
    host_push: gitops.PushResult | None = None
    target: Path | None = None  # the compiled canon file (host side)


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


def _abort_if_dirty(repo: Path, target: Path) -> None:
    """(c) dirty-compile-target abort — against the HOST repo (doc 13 §4:
    the target lives in a host now, so the dirty check must too)."""
    if gitops.paths_dirty(repo, target):
        raise DirtyTargetError(
            f"compile target {target} has unrelated uncommitted changes — "
            "commit/stash first, then re-run"
        )


def _ledger_write(home: Path):
    """THE ledger critical section: hold :func:`gitops.commit_lock` from a
    verb's first ledger mutation through its commit — and no further
    (audit 2026-07-16 round 3; see the ``gitops`` module docstring for the
    probe that fixed this scope).

    It must open before the first mutation, not at ``commit()``:
    ``resolve_record`` ``git mv``s (staging a rename instantly) and
    rewrites record files in the worktree, and a racing producer entering
    ``pull --rebase --autostash`` in that window stashes both away — probed
    to leave the record in pending/ AND resolved/ at once, exit 0, `git
    status` clean.

    It must CLOSE at the commit. The previous shape (a whole-verb
    decorator) also held the ledger lock across the compile, the host
    phase and the push, none of which touch the ledger's index — a wedged
    remote therefore blocked every other producer for a full TCP timeout,
    and, worse, the shape made it look like host rebases were covered when
    they took no host lock at all. Pushes now sit outside; the rebase takes
    its own lock inside :func:`gitops.push_with_retry`, in whichever repo
    is actually being rebased.

    Re-entrant, so a verb may hold it across helpers that take it again."""
    return gitops.commit_lock(home)


def _stage_and_commit(
    home: Path,
    touched: list[Path],
    message: str,
    note: str | None,
) -> tuple[list[Path], str]:
    """Stage → pinned commit. **Callers must already hold**
    :func:`_ledger_write` (it is re-entrant, and taken here too so a future
    caller that forgets still gets the commit half).

    ``paths=touched`` — NOT ``paths=staged``: :func:`gitops.stage` returns
    only paths that still EXIST, but a resolution's touched list also names
    the ``git mv``-ed old path, which must ride the pathspec or the commit
    splits the rename in half (see :func:`gitops.known_paths`, which
    filters the list git cannot match)."""
    with gitops.commit_lock(home):
        return _commit_ledger(home, touched, message, note)


def _commit_ledger(
    home: Path, touched: list[Path], message: str, note: str | None = None
) -> tuple[list[Path], str]:
    """Stage → pinned commit, INSIDE the caller's :func:`_ledger_write`,
    with the state fact attached to any failure.

    Everything this function does is post-mutation by construction — the
    caller has already run ``resolve_record`` (a ``git mv`` + a record
    rewrite) — and ``ledger_ops`` raises ``LedgerOpsError``, never
    ``GitOpsError``. So a ``GitOpsError`` reaching HERE can only come from
    ``stage``/``commit``, which means: the ledger is mutated and the commit
    did not land. That is :class:`gitops.HalfWrittenError`, and it is
    raised HERE — in the verb layer — precisely because ``gitops`` cannot
    know it (audit 2026-07-16 round 7 BLOCKER 2; the gitops docstring
    already said "that is the verb's fact to state, not this module's",
    and the verb was stating the opposite fact unconditionally)."""
    try:
        staged = gitops.stage(home, touched)
        sha = gitops.commit(home, message, body=note, paths=touched)
    except gitops.HalfWrittenError:
        raise
    except gitops.GitOpsError as exc:
        raise gitops.HalfWrittenError.for_commit(home, message, touched, exc) from exc
    return staged, sha


def _push_ledger(home: Path, no_push: bool) -> gitops.PushResult | None:
    """The ledger push — OUTSIDE the commit lock (no index involvement)
    and behind the no-remote guard (audit 2026-07-16 MAJOR E: seven verbs
    still called ``push_with_retry`` unguarded, so on a remote-less ledger
    — the state doc 13 §7.1 step 5 creates on purpose — every one of them
    exited 3 with a false "PUSH FAILED" over a perfect commit)."""
    return None if no_push else gitops.push_if_remote(home)


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


@dataclass(frozen=True)
class TargetSpec:
    """A pre-flighted compile target (doc 13 §4): where the canon lands,
    which HOST repo commits it, and how to gather the compile set.
    ``host_repo`` is None only for the chezmoi user flow (the dotfiles
    repo commits itself)."""

    destination: str  # skill-md | claude-md | reference
    scope_kind: str  # "skill" | "project" | "skill-root" | "user"
    bucket_dir: Path
    target: Path | None  # None for a default (created-on-demand) reference
    host_repo: Path | None
    refs_dir: Path | None = None
    ref_name: str | None = None


def _gate_host(home: Path, path: Path | str, kind: str) -> Path:
    """PREFLIGHT the host itself (audit 2026-07-16 MAJOR 5b/6): registered
    is not the same as sound. hosts.yaml is data — a hand edit, or a repo
    that MOVED since registration, can name a path that does not exist, is
    not a git repo, or IS the ledger home. Unchecked, the old code sailed
    past preflight (``target.is_file()`` is False for a vanished host, so
    even the dirty check was skipped), COMMITTED THE LEDGER, and only then
    failed at ``write_text`` — drift with no repair, or canon written
    outside any repo. This raises before any commit."""
    try:
        return validate_host_path(home, path, kind)
    except HostsError as exc:
        raise VerbError(str(exc)) from exc


def _hosts_skill_dir(home: Path, name: str) -> tuple[Path, Path]:
    """(skills_root, host skill dir) via the registry — HostsError →
    VerbError. The root is gate-validated (MAJOR 6: a typo'd
    ``skills_root`` must never reach a compiler)."""
    hosts = load_hosts(home)
    try:
        skill_dir = skill_dir_for(hosts, name)
    except HostsError as exc:
        raise VerbError(str(exc)) from exc
    return _gate_host(home, hosts.skills_root, "skills-root"), skill_dir


def _project_host_or_refuse(
    home: Path, bucket_dir: Path, project_path: Path | None = None
) -> Path:
    """The doc 13 Q2 gate: a project bucket compiles into its recorded
    host ONLY when that host is registered at route time AND that host is
    sound on disk. The refusal messages are pinned so the review card can
    show the one command that unblocks it — ``host add`` for a host that
    was never registered, ``host rebind`` for one whose repo moved (audit
    2026-07-16 MAJOR 5: the old refusal named ``host add /old/path``,
    which then refused because /old/path no longer exists — an impossible
    command)."""
    host = project_path if project_path is not None else bucket_project_path(bucket_dir)
    if host is None:
        raise VerbError(
            f"project bucket {bucket_dir} has no meta.yaml — its project "
            "path is unknown; re-capture, or write meta.yaml by hand"
        )
    if not is_project_host(load_hosts(home), host):
        raise VerbError(f"host not registered — self-learn host add {host}")
    return _gate_host(home, host, "project")


def _resolve_target(
    home: Path,
    bucket_dir: Path,
    scope: str,
    destination: str,
    ref_name: str | None,
    *,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
    project_path: Path | None = None,
    check_dirty: bool = True,
) -> TargetSpec:
    """PRE-FLIGHT target resolution (doc 13 §4 step c): registry gates
    (H-3) + dirty checks against the HOST repo, all raising BEFORE any
    commit. Pure — writes nothing."""
    if destination == "skill-md":
        if not scope.startswith("skill:"):
            raise VerbError(
                "skill-md destination needs skill:<name> scope, "
                f"got {scope!r} — use claude-md or reference"
            )
        root, skill_dir = _hosts_skill_dir(home, scope.partition(":")[2])
        target = skill_dir / "SKILL.md"
        if not target.is_file():
            raise VerbError(
                f"no SKILL.md at {target} — the compiler never creates "
                "target files, only the section inside an existing one"
            )
        if check_dirty:
            _abort_if_dirty(root, target)
        return TargetSpec("skill-md", "skill", bucket_dir, target, root)

    if destination == "claude-md":
        if scope == "user":
            target = Path(
                user_claude_md if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD
            ).expanduser()
            if check_dirty:
                # E-17 preflight: chezmoi drift/dirty aborts BEFORE the
                # ledger commit — the record stays pending (§5 playbook).
                preflight_user_scope(target, chezmoi=chezmoi_bin)
            return TargetSpec("claude-md", "user", bucket_dir, target, None)
        if scope == "project":
            host = _project_host_or_refuse(home, bucket_dir, project_path)
            target = host / "CLAUDE.md"
            if check_dirty and target.is_file():
                _abort_if_dirty(host, target)
            return TargetSpec("claude-md", "project", bucket_dir, target, host)
        # skill:<name> scope → the skills-root host's own CLAUDE.md
        # (doc 13 §2: claude-skills hosts SKILL.md sections + its own
        # CLAUDE.md; the old <home>/CLAUDE.md target maps here).
        hosts = load_hosts(home)
        if hosts.skills_root is None:
            raise VerbError(
                "no skills root registered — self-learn host add <path> --skills-root"
            )
        root = _gate_host(home, hosts.skills_root, "skills-root")
        target = root / "CLAUDE.md"
        if check_dirty and target.is_file():
            _abort_if_dirty(root, target)
        return TargetSpec("claude-md", "skill-root", bucket_dir, target, root)

    if destination == "reference":
        if scope.startswith("skill:"):
            root, skill_dir = _hosts_skill_dir(home, scope.partition(":")[2])
            host, refs_dir, kind = root, skill_dir / "references", "skill"
        elif scope == "project":
            host = _project_host_or_refuse(home, bucket_dir, project_path)
            refs_dir, kind = host / "references", "project"
        else:
            raise VerbError(
                "reference destination needs skill:<name> or project scope — "
                "the user host is the chezmoi-managed CLAUDE.md, it has no "
                "references dir (doc 13 §2)"
            )
        # The compiler owns this mapping — "the one place that mapping
        # lives" (compilers.reference_target_path's docstring). This site
        # re-implemented it with its own "LEARNINGS.md" literal (audit
        # 2026-07-16 MINOR 7): two copies of one rule, free to drift.
        probe = reference_target_path(refs_dir, ref_name)
        if check_dirty and probe.is_file():
            _abort_if_dirty(host, probe)
        return TargetSpec(
            "reference", kind, bucket_dir, None, host, refs_dir=refs_dir, ref_name=ref_name
        )

    raise VerbError(f"unroutable destination {destination!r}")


def _compile_set(home: Path, spec: TargetSpec) -> list[Record]:
    """The compile set, read straight off disk (the ledger op commits
    FIRST now — no shadow copies; superseded old records already dropped
    out via the compiler's status filter)."""
    if spec.destination == "skill-md":
        return _routed_to([spec.bucket_dir], "skill-md")
    if spec.scope_kind == "user":
        return _routed_to(
            _all_bucket_dirs(home), "claude-md", scope_pred=lambda s: s == "user"
        )
    if spec.scope_kind == "project":
        return _routed_to(
            [spec.bucket_dir], "claude-md", scope_pred=lambda s: s == "project"
        )
    # skill-root: every skill bucket's claude-md-routed records
    skill_dirs = [b.path for b in discover_buckets(home) if b.scope == "skill"]
    return _routed_to(
        skill_dirs, "claude-md", scope_pred=lambda s: s.startswith("skill:")
    )


def _apply_target(
    home: Path,
    spec: TargetSpec,
    routed_record: Record | None,
    *,
    chezmoi_bin: str = "chezmoi",
    message: str | None = None,
) -> tuple[object, list[Path]]:
    """HOST-phase compile (doc 13 §4 step e): write the target from the
    committed ledger state. Returns (compile_result, host paths to stage —
    empty for the chezmoi user flow, which commits its own repo)."""
    if spec.destination == "reference":
        if routed_record is None:  # supersede/recompile never touch references
            raise VerbError("reference targets are append-only — nothing to apply")
        compile_result = compile_reference(
            spec.refs_dir, routed_record, dest=spec.ref_name
        )
        host_paths = [compile_result.path]
    elif spec.scope_kind == "user":
        compile_result = compile_user_scope(
            spec.target,
            _compile_set(home, spec),
            chezmoi=chezmoi_bin,
            commit_message=message,
        )
        host_paths = []
    else:
        if not spec.target.is_file():
            # Judgment call (T7 brief, carried over): first route to a host
            # with no CLAUDE.md creates it empty and lets the managed-
            # section bootstrap (08 §1 pin) append the marker pair.
            # skill-md never reaches here — preflight refuses.
            spec.target.write_text("", encoding="utf-8")
        compile_result = compile_managed_file(spec.target, _compile_set(home, spec))
        host_paths = [spec.target]

    # surface-budget event (11 §4.3: compilers, inside verb flow) — the
    # attention-tax ledger. Spooled here, flushed by the calling verb.
    telemetry.spool_quiet(
        "surface-budget",
        target=spec.destination,
        words=getattr(compile_result, "word_count", None),
        overflow=bool(getattr(compile_result, "over_cap", False)),
    )
    return compile_result, host_paths


#: Host-phase failure classes: loud drift warning, never a rollback (H-2).
_HOST_PHASE_ERRORS = (
    CompileError,
    ChezmoiAbort,
    ChezmoiError,
    gitops.GitOpsError,
    VerbError,
    OSError,
)


def _host_phase(
    home: Path,
    spec: TargetSpec,
    record_id: str,
    *,
    routed_record: Record | None,
    note: str | None,
    chezmoi_bin: str,
    message: str,
    warnings: list[str],
) -> tuple[object | None, str | None]:
    """Steps (e): compile + HOST commit under the sentinel hold. On ANY
    failure after the ledger commit: loud drift warning naming
    ``self-learn recompile``; the ledger stays truth (doc 13 §4.2).

    The HOST's commit lock spans compile→commit, for the same reason the
    ledger's spans mutation→commit: the compile WRITES the managed file
    into the host worktree, and a racing self-learn producer rebasing that
    host (``push_with_retry`` → ``pull --rebase --autostash``) would stash
    the freshly compiled file away mid-flight. Always ledger→host, the one
    ordering, so composing them cannot deadlock. Note the lock is partial
    by design for hosts — a human's own ``git add`` in their repo takes no
    lock of ours, which is exactly why the commit is ALSO pathspec-scoped
    to ``host_paths``."""
    lock = (
        gitops.commit_lock(spec.host_repo)
        if spec.host_repo is not None
        else contextlib.nullcontext()
    )
    try:
        with lock:
            compile_result, host_paths = _apply_target(
                home, spec, routed_record, chezmoi_bin=chezmoi_bin, message=message
            )
            host_sha = None
            if spec.host_repo is not None and host_paths:
                changed = getattr(compile_result, "changed", None)
                applied = getattr(compile_result, "applied", None)
                if changed is not False and applied is not False:
                    gitops.stage(spec.host_repo, host_paths)
                    rel = host_paths[0].relative_to(spec.host_repo)
                    host_sha = gitops.commit(
                        spec.host_repo,
                        f"self-learn: apply {record_id} → {rel} ({spec.destination})",
                        body=note,
                        paths=host_paths,
                    )
        return compile_result, host_sha
    except _HOST_PHASE_ERRORS as exc:
        warning = (
            f"HOST PHASE FAILED after the ledger commit ({exc}) — canon is "
            "stale, never lost (H-2); run `self-learn recompile` to repair"
        )
        print(f"self-learn: {warning}", file=sys.stderr)
        warnings.append(warning)
        return None, None


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

        # (c) PRE-FLIGHT: registry gates (H-3 / doc 13 Q2) + host-repo
        # dirty checks + chezmoi drift/dirty for user scope. Every refusal
        # lands HERE — before any commit; the record stays pending.
        spec = _resolve_target(
            home,
            bucket_dir,
            record.scope,
            destination,
            ref_name,
            user_claude_md=user_claude_md,
            chezmoi_bin=chezmoi_bin,
        )

        if collapse is not None:
            # Pinned commit shape: route lrn-X → <target> (collapse
            # merge-<cid>, supersedes lrn-Y, lrn-Z) — a teach --supersedes
            # link on the survivor rides the same list (audit 2026-07-15:
            # it used to vanish from the subject).
            superseded = losers + ([old_id] if old_id else [])
            suffix = f" (collapse {collapse}, supersedes {', '.join(superseded)})"
        else:
            suffix = f" (supersedes {old_id})" if old_id else ""
        message = f"self-learn: route {record_id} → {destination}{suffix}"
        routed_at = _now_iso()

        merged: Record | None = None
        if collapse is not None:
            # Merge the losers into an IN-MEMORY survivor: evidence gains
            # their provenance plus one merged_from marker per loser, and
            # sightings becomes the cluster total. Nothing touches disk
            # until preflight has passed; the merged_from markers make a
            # crash-window retry idempotent (an already-folded loser is
            # skipped) — audit 2026-07-15.
            merged = Record.from_path(path)
            already_folded = {
                e.get("merged_from")
                for e in merged.evidence
                if e.get("merged_from")
            }
            total_sightings = merged.sightings
            for rid in losers:
                if rid in already_folded:
                    continue
                lr = Record.from_path(path.parent / f"{rid}.md")
                for entry in lr.evidence:
                    merged.append_evidence(entry)
                merged.append_evidence(
                    {"merged_from": rid, "sightings": lr.sightings, "ts": routed_at}
                )
                total_sightings += lr.sightings
            merged.set_sightings(total_sightings)

        # (d) LEDGER phase (doc 13 §4.1: ledger commit FIRST — the ledger
        # is the source of truth; canon is compiled from it afterwards).
        # The lock opens HERE — at the first mutation, not at the commit —
        # and closes at the commit; see :func:`_ledger_write`.
        with _ledger_write(home):
            if merged is not None:
                merged.write(path)
            touched = resolve_record(
                home,
                record_id,
                "routed",
                destination=destination,
                routed_at=routed_at,
                note=note,
                follow_up=follow_up,
                reference_file=ref_name if destination == "reference" else None,
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
            # paths=touched, not paths=staged: the git mv-ed OLD path is
            # gone from the worktree (so `stage` drops it) but MUST ride
            # the pathspec or the rename commits in half.
            staged, sha = _commit_ledger(home, touched, message, note)

        # (e) HOST phase: compile from the committed ledger state + host
        # commit (pinned apply subject), still under the sentinel hold.
        warnings: list[str] = []
        routed_record = Record.from_path(
            bucket_dir / "resolved" / f"{record_id}.md"
        )
        compile_result, host_sha = _host_phase(
            home,
            spec,
            record_id,
            routed_record=routed_record,
            note=note,
            chezmoi_bin=chezmoi_bin,
            message=message,
            warnings=warnings,
        )

        # (f) push ledger, then push host (pinned retry, has_remote-guarded)
        # unless --no-push.
        push = None if no_push else gitops.push_if_remote(home)
        host_push = None
        if not no_push and host_sha is not None and spec.host_repo is not None:
            host_push = gitops.push_if_remote(spec.host_repo)
        return VerbResult(
            action="route",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            compile_result=compile_result,
            sentinel_owned=hold.owned,
            warnings=warnings,
            host_commit_sha=host_sha,
            host_push=host_push,
            target=spec.target,
        )
    finally:
        hold.release()  # (g) release iff owned


def route_direct(
    home: Path | str,
    record: Record,
    *,
    dest: str,
    note: str | None = None,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
    project_path: Path | None = None,
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
    # BLOCKER 11 (audit 2026-07-16): this path writes a record straight
    # into resolved/ — gate the home BEFORE anything lands on disk.
    try:
        require_writable_home(home)
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
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
        bucket_dir = bucket_dir_for_scope(
            home, record.scope, project_path=project_path
        )
        resolved_path = bucket_dir / "resolved" / f"{record.id}.md"
        if resolved_path.exists() or (
            bucket_dir / "pending" / f"{record.id}.md"
        ).exists():
            raise VerbError(f"record {record.id} already exists in {bucket_dir}")

        # (c) PRE-FLIGHT — registry gates + host dirty checks, before any
        # write (the composed record is still only in memory).
        spec = _resolve_target(
            home,
            bucket_dir,
            record.scope,
            destination,
            ref_name,
            user_claude_md=user_claude_md,
            chezmoi_bin=chezmoi_bin,
            project_path=project_path,
        )

        suffix = f" (supersedes {old_id})" if old_id else ""
        message = f"self-learn: route {record.id} → {destination}{suffix}"

        routing = {"routed_at": _now_iso(), "destination": destination, "by": "human"}
        if destination == "reference" and ref_name is not None:
            routing["reference_file"] = ref_name  # BLOCKER 2: name the file
        record.set_routing(routing)
        record.set_status("routed")
        if note is not None:
            record.set_resolution_note(note)

        # (d) LEDGER phase: write directly to resolved/ — the pending/ dir
        # is never touched (02 §2 lifecycle note). Locked from the first
        # mutation through the commit (:func:`_ledger_write`).
        with _ledger_write(home):
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            record.write(resolved_path)
            touched: list[Path] = [resolved_path]
            if record.scope == "project":
                touched.append(ensure_project_meta(bucket_dir, project_path))
            if old_id is not None:
                # teach --supersedes completion-at-route: SAME commit (08 §1
                # Corrective-supersession pin).
                touched = touched + supersede_record(home, old_id, record.id)
            try:
                staged = gitops.stage(home, touched)
                diff = gitops.staged_diff(home, staged)
            except gitops.GitOpsError as exc:  # post-mutation: see _commit_ledger
                raise gitops.HalfWrittenError.for_commit(
                    home, message, touched, exc
                ) from exc
            _, sha = _commit_ledger(home, touched, message, note)

        # (e) HOST phase.
        warnings: list[str] = []
        compile_result, host_sha = _host_phase(
            home,
            spec,
            record.id,
            routed_record=record,
            note=note,
            chezmoi_bin=chezmoi_bin,
            message=message,
            warnings=warnings,
        )
        if host_sha is not None and spec.host_repo is not None:
            # the applied-canon half of the printed diff (informational —
            # invocation is the approval, never a prompt).
            host_diff = gitops._git(  # noqa: SLF001 — same module family
                spec.host_repo, "show", "--format=", host_sha
            ).stdout
            diff = diff + host_diff

        # (f) push ledger, then push host (both has_remote-guarded).
        push = None if no_push else gitops.push_if_remote(home)
        host_push = None
        if not no_push and host_sha is not None and spec.host_repo is not None:
            host_push = gitops.push_if_remote(spec.host_repo)
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
            warnings=warnings,
            host_commit_sha=host_sha,
            host_push=host_push,
            target=spec.target,
        )
    finally:
        hold.release()  # (g) release iff owned


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
        message = f"self-learn: reject {record_id}"
        with _ledger_write(home):
            touched = resolve_record(home, record_id, "rejected", note=note)
            staged, sha = _stage_and_commit(home, touched, message, note)
        push = _push_ledger(home, no_push)
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
        with _ledger_write(home):
            touched = defer_record(home, record_id, until)
            deferred_until = _date_str(Record.from_path(touched[0]).deferred_until)
            message = f"self-learn: defer {record_id} until {deferred_until}"
            staged, sha = _stage_and_commit(home, touched, message, note)
        push = _push_ledger(home, no_push)
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
        message = f"self-learn: graduate {record_id}"
        with _ledger_write(home):
            touched = resolve_record(
                home, record_id, "superseded", superseded_by="canon", note=note
            )
            staged, sha = _stage_and_commit(home, touched, message, note)
        push = _push_ledger(home, no_push)
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
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
) -> VerbResult:
    """Corrective supersession (08 §1 pin): mark ``old`` superseded by
    ``new`` (which must exist). Commit: ``self-learn: supersede lrn-old →
    lrn-new``. When the old record was ROUTED to a managed target this
    verb is canon-touching (doc 13 §4): its entry must drop, so after the
    ledger commit the host phase recompiles the target and commits the
    host. A pending old record stays a single ledger commit. Reference-
    routed records need no host phase — references are append-only."""
    home = Path(home)
    if old_id == new_id:
        raise VerbError("a record cannot supersede itself")
    old_path = find_record_path(home, old_id)  # pending OR routed flavor
    find_record_path(home, new_id)  # the replacement must exist
    _scan_or_refuse([old_path], note)
    warnings = _orphaned_followup_warning(old_path, old_id)
    old_record = Record.from_path(old_path)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        # (c) PRE-FLIGHT the recompile target when this drops a live entry.
        spec: TargetSpec | None = None
        if old_record.status == "routed":
            destination = (old_record.routing or {}).get("destination")
            if destination in ("skill-md", "claude-md"):
                spec = _resolve_target(
                    home,
                    old_path.parent.parent,
                    old_record.scope,
                    destination,
                    None,
                    user_claude_md=user_claude_md,
                    chezmoi_bin=chezmoi_bin,
                )

        # (d) LEDGER phase (locked from the first mutation through the
        # commit — :func:`_ledger_write`).
        message = f"self-learn: supersede {old_id} → {new_id}"
        with _ledger_write(home):
            touched = supersede_record(home, old_id, new_id, note=note)
            staged, sha = _commit_ledger(home, touched, message, note)

        # (e) HOST phase: recompile the target — the entry drops out.
        compile_result = None
        host_sha = None
        if spec is not None:
            compile_result, host_sha = _host_phase(
                home,
                spec,
                old_id,
                routed_record=None,
                note=note,
                chezmoi_bin=chezmoi_bin,
                message=message,
                warnings=warnings,
            )

        # (f) push ledger, then host (both has_remote-guarded).
        push = None if no_push else gitops.push_if_remote(home)
        host_push = None
        if not no_push and host_sha is not None and spec.host_repo is not None:
            host_push = gitops.push_if_remote(spec.host_repo)
        return VerbResult(
            action="supersede",
            record_id=old_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            compile_result=compile_result,
            sentinel_owned=hold.owned,
            warnings=warnings,
            host_commit_sha=host_sha,
            host_push=host_push,
            target=spec.target if spec is not None else None,
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
        message = f"self-learn: follow-up done on {record_id}"
        with _ledger_write(home):
            record.write(path)
            staged, sha = _stage_and_commit(home, [path], message, note)
        push = _push_ledger(home, no_push)
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
    if any(r.get("ref") == event_ref for r in record.recurrences):
        raise VerbError(
            f"event {event_ref} is already confirmed on {record_id} — "
            "double-confirming would overstate recurrence pressure, the "
            "exact signal this verb keeps honest (audit 2026-07-15)"
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
        message = f"self-learn: recurrence confirmed on {record_id}"
        with _ledger_write(home):
            record.write(path)
            staged, sha = _stage_and_commit(home, [path], message, note)
        push = _push_ledger(home, no_push)
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
        message = f"self-learn: confirmed holding {record_id}"
        with _ledger_write(home):
            record.write(path)
            staged, sha = _stage_and_commit(home, [path], message, note)
        push = _push_ledger(home, no_push)
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
    if target == record_id:
        raise VerbError("a record cannot contradict itself")
    if RECORD_ID_RE.match(target):
        find_record_path(home, target)  # record-id targets must exist
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
        message = f"self-learn: link {record_id} contradicts {target}"
        with _ledger_write(home):
            record.write(path)
            staged, sha = _stage_and_commit(home, [path], message, note)
        push = _push_ledger(home, no_push)
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


@dataclass(frozen=True)
class PushReport:
    """What ``self-learn push`` published, per repo (ledger first, then
    every registered host that had unpushed commits)."""

    entries: list[tuple[Path, gitops.PushResult]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for _repo, r in self.entries)

    @property
    def retried(self) -> bool:
        return any(r.retried for _repo, r in self.entries)

    @property
    def exit_code(self) -> int:
        for _repo, r in self.entries:
            if not r.ok:
                return r.exit_code
        return 0


def push_pending(home: Path | str) -> PushReport:
    """The bare ``self-learn push`` verb: publish pending local commits
    with the pinned retry — for the LEDGER **and every registered host**
    (audit 2026-07-16 MAJOR 4: a failed HOST push had no retry path at
    all; ``push`` was ledger-only, so the one command the failure message
    names — "run `self-learn push`" — could not actually republish the
    canon commit it was talking about).

    Hosts with nothing unpushed are skipped silently; a host whose repo is
    unsound (moved away, hand-edited entry) is skipped LOUDLY rather than
    failing the ledger push — publishing truth must not hinge on a broken
    canon host. Read-only w.r.t. records — no sentinel, no heartbeat (it
    mutates nothing the watcher could race)."""
    home = Path(home)
    entries: list[tuple[Path, gitops.PushResult]] = [
        (home, gitops.push_pending(home))
    ]

    try:
        hosts = load_hosts(home)
    except HostsError as exc:
        print(f"self-learn push: hosts.yaml unreadable ({exc})", file=sys.stderr)
        return PushReport(entries)

    seen: set[Path] = {home.resolve()}
    candidates = [(hosts.skills_root, "skills-root")] + [
        (p, "project") for p in hosts.projects
    ]
    for raw, kind in candidates:
        if raw is None:
            continue
        problem = None
        try:
            repo = validate_host_path(home, raw, kind)
        except HostsError as exc:
            problem = str(exc)
            repo = Path(raw).expanduser()
        if problem is not None:
            print(f"self-learn push: skipping {repo} — {problem}", file=sys.stderr)
            continue
        if repo in seen:
            continue
        seen.add(repo)
        if gitops.unpushed_commits(repo):
            entries.append((repo, gitops.push_if_remote(repo)))
    return PushReport(entries)


# --------------------------------------------------------------- recompile


@dataclass(frozen=True)
class RecompileEntry:
    """One managed target's recompile outcome."""

    target: Path
    changed: bool
    commit_sha: str | None = None
    skipped: str | None = None  # why the target was left alone


@dataclass
class RecompileResult:
    entries: list[RecompileEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def committed(self) -> int:
        return sum(1 for e in self.entries if e.commit_sha is not None)


def recompile(home: Path | str, *, no_push: bool = False) -> RecompileResult:
    """The doc-13 drift repair (H-2: recompile is always safe and repairs
    any two-phase interruption). For every ROUTED record, recompute each
    managed target — skill-md files and project/skill-root claude-md files
    (the chezmoi-managed user file keeps its own guarded flow) — and
    RE-APPEND every reference-routed record to its references file, then
    commit any HOST whose file changed (pinned subject ``self-learn:
    recompile <relative target>``).

    References are append-only, which is exactly why they belong here
    (audit 2026-07-16 BLOCKER 2): a ``reference`` route interrupted
    between the ledger commit and the host apply used to leave NO canon
    entry and NO way back — recompile filtered references out, so the one
    advertised repair did nothing and the drift check called it clean.
    :func:`compilers.compile_reference` is record-id-idempotent, so
    re-appending an entry that IS there is a no-op and re-appending one
    that is missing is the repair.

    Idempotent overall: a second run compiles byte-identical content and
    commits nothing. Unregistered/unsound hosts and dirty targets are
    skipped LOUDLY, never guessed at (H-3)."""
    home = Path(home)
    result = RecompileResult()

    # Enumerate targets off the routed records (the ledger is the source of
    # truth — targets are derived, never listed anywhere else).
    specs: dict[tuple[Path | None, Path | None], TargetSpec] = {}
    ref_work: dict[tuple[Path, Path], tuple[TargetSpec, list[Record]]] = {}
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except RecordError:
                continue
            if record.status != "routed" or record.superseded_by is not None:
                continue
            destination = (record.routing or {}).get("destination")
            if destination not in ("skill-md", "claude-md", "reference"):
                continue
            if destination == "claude-md" and record.scope == "user":
                continue  # chezmoi flow owns the user file — not recompiled
            ref_name = (
                (record.routing or {}).get("reference_file")
                if destination == "reference"
                else None
            )
            try:
                spec = _resolve_target(
                    home,
                    bucket.path,
                    record.scope,
                    destination,
                    ref_name,
                    check_dirty=False,
                )
            except VerbError as exc:
                result.warnings.append(f"{record.id}: {exc}")
                continue
            if destination == "reference":
                probe = reference_target_path(spec.refs_dir, spec.ref_name)
                entry = ref_work.setdefault((spec.host_repo, probe), (spec, []))
                entry[1].append(record)
                continue
            specs.setdefault((spec.host_repo, spec.target), spec)

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        touched_hosts: list[Path] = []
        for (host_repo, target), spec in sorted(
            specs.items(), key=lambda kv: str(kv[0][1])
        ):
            if target.is_file() and gitops.paths_dirty(host_repo, target):
                result.entries.append(
                    RecompileEntry(target=target, changed=False, skipped="dirty")
                )
                result.warnings.append(
                    f"{target}: uncommitted changes — commit/stash, then re-run"
                )
                continue
            # compile→commit under the HOST's lock (see :func:`_host_phase`:
            # the compile writes the managed file into the host worktree, so
            # a racing autostash there would stash it away mid-flight).
            with gitops.commit_lock(host_repo):
                try:
                    compile_result, host_paths = _apply_target(home, spec, None)
                except (CompileError, OSError) as exc:
                    result.entries.append(
                        RecompileEntry(target=target, changed=False, skipped=str(exc))
                    )
                    result.warnings.append(f"{target}: {exc}")
                    continue
                if not compile_result.changed:
                    result.entries.append(
                        RecompileEntry(target=target, changed=False)
                    )
                    continue
                gitops.stage(host_repo, host_paths)
                rel = target.relative_to(host_repo)
                sha = gitops.commit(
                    host_repo, f"self-learn: recompile {rel}", paths=host_paths
                )
            result.entries.append(
                RecompileEntry(target=target, changed=True, commit_sha=sha)
            )
            if host_repo not in touched_hosts:
                touched_hosts.append(host_repo)

        # Reference targets: re-append every routed record (idempotent per
        # record id), commit the file ONCE if anything landed.
        for (host_repo, probe), (spec, records) in sorted(
            ref_work.items(), key=lambda kv: str(kv[0][1])
        ):
            if probe.is_file() and gitops.paths_dirty(host_repo, probe):
                result.entries.append(
                    RecompileEntry(target=probe, changed=False, skipped="dirty")
                )
                result.warnings.append(
                    f"{probe}: uncommitted changes — commit/stash, then re-run"
                )
                continue
            # The lock ENCLOSES the compile loop (audit 2026-07-16 round 7
            # MAJOR 3): ``compile_reference`` APPENDS to the references
            # file, which is TRACKED in the host — the one shape a racing
            # autostash does not leave alone (verified: autostash leaves
            # conflict markers in tracked modifications; untracked files
            # survive, which is why the teach/worker/miner windows are the
            # benign ones and this was not). It used to open at the commit
            # below, asymmetric with the managed-file path above, which
            # correctly wraps ``_apply_target``. Same rule, both paths:
            # lock before the first mutation of the repo.
            with gitops.commit_lock(host_repo):  # ledger→host order
                applied = False
                failed = False
                for record in sorted(records, key=lambda r: r.id):
                    try:
                        ref_result = compile_reference(
                            spec.refs_dir, record, dest=spec.ref_name
                        )
                    except (CompileError, OSError) as exc:
                        result.warnings.append(f"{record.id}: {exc}")
                        failed = True
                        continue
                    applied = applied or ref_result.applied or ref_result.created
                if not applied:
                    if not failed:
                        result.entries.append(
                            RecompileEntry(target=probe, changed=False)
                        )
                    continue
                gitops.stage(host_repo, [probe])
                rel = probe.relative_to(host_repo)
                sha = gitops.commit(
                    host_repo, f"self-learn: recompile {rel}", paths=[probe]
                )
            result.entries.append(
                RecompileEntry(target=probe, changed=True, commit_sha=sha)
            )
            if host_repo not in touched_hosts:
                touched_hosts.append(host_repo)

        if not no_push:
            # Outside every lock (a push touches no index); the rebase
            # fallback takes the HOST's own lock inside push_with_retry.
            for host_repo in touched_hosts:
                gitops.push_if_remote(host_repo)
    finally:
        hold.release()
    return result
