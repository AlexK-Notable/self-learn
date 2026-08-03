"""Resolution verbs (T7): route / reject / defer / graduate / supersede —
plus the non-resolution filing move `rehome` (02 §2, added 2026-07-18).

Function layer only — T8 wires these into the CLI. Public signatures:

    route(home, record_id, *, dest=None, note=None, no_push=False,
          user_claude_md=None, chezmoi_bin="chezmoi") -> VerbResult
    reject(home, record_id, *, note=None, no_push=False) -> VerbResult
    defer(home, record_id, *, until=None, note=None, no_push=False) -> VerbResult
    graduate(home, record_id, *, note=None, no_push=False) -> VerbResult
    supersede(home, old_id, new_id, *, note=None, no_push=False) -> VerbResult
    rehome(home, record_id, *, to, note=None, no_push=False) -> VerbResult
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
import glob as glob_mod
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import config as policy_config
from . import gitops, sentinel, telemetry
from .hook_compiler import replay_examples, script_name, settings_snippet
from .normalize import sha_anchor
from .skill_scaffold import (
    SkillScaffoldError,
    marketplace_with_entry,
    plugin_manifest_text,
    scaffold_description,
    skill_md_seed,
    validate_skill_name,
)
from . import chezmoi
from .chezmoi import ChezmoiAbort, ChezmoiError, compile_user_scope, preflight_user_scope
from .compilers import (
    BEGIN_MARKER,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_WORDS,
    CompileError,
    SectionResult,
    compile_managed_file,
    compile_managed_text,
    compile_reference,
    reference_target_path,
)
from .hosts import (
    HostsError,
    is_project_host,
    load_hosts,
    skill_dir_for,
    slug_for,
    validate_host_path,
)
from .ledger import discover_buckets
from .ledger_ops import (
    PROPOSAL_DESTINATIONS,
    LedgerOpsError,
    ProposalError,
    bucket_dir_for_scope,
    bucket_project_path,
    defer_record,
    ensure_project_meta,
    find_record_path,
    rehome_record,
    read_proposal,
    record_title,
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
    "CHEZMOI_DRIFT_REFUSAL",
    "COMMIT_DRIFT_SUBJECT",
    "DEFAULT_USER_CLAUDE_MD",
    "GITOPS_DIRTY_MARKER",
    "NOTHING_TO_COMMIT",
    "SURFACE_FILL_CAPPED_DESTINATIONS",
    "CommitDriftResult",
    "DirtyTargetError",
    "NoProposalError",
    "PushReport",
    "RecompileEntry",
    "RecompileResult",
    "SecretRefusal",
    "TargetSpec",
    "VerbError",
    "VerbResult",
    "chezmoi_adopt",
    "commit_drift",
    "confirm_held",
    "confirm_recurrence",
    "defer",
    "one_motion_allowed",
    "followup_done",
    "graduate",
    "link_contradicts",
    "push_pending",
    "recompile",
    "rehome",
    "reject",
    "route",
    "route_direct",
    "supersede",
    "surface_fill",
]

DEFAULT_USER_CLAUDE_MD = Path("~/.claude/CLAUDE.md")

#: Destinations the one-motion path (``teach --route`` /
#: :func:`route_direct`) refuses BY DEFAULT: a ``hook`` route applies
#: human-approved executable bytes (M3-2 — a one-motion capture has no
#: proposal to review), and ``new-skill``'s name slot is a route-time
#: human call (08 §8.1). *S-10 amendment 2026-07-16 (user ruling): the
#: refusal is a DEFAULT, not a hard-code — a committed
#: ``<home>/config.yaml`` ``one_motion_route: {hook: true, …}`` opts a
#: destination in per :func:`one_motion_allowed`; parsing is fail-closed,
#: and the enabled hook path still runs the full integrity chain and
#: prints the applied bytes. settings.json registration stays manual
#: either way — no guard fires without a human edit.*
ONE_MOTION_UNROUTABLE = frozenset({"new-skill", "hook"})

#: 09 §11 Y-20 / 08 §1 `surface_fill` field: the ONLY two destinations a
#: managed-section fill probe ever covers. ``reference`` is never in this
#: set — it is the cap-free overflow sink (``target=None``,
#: ``compile_reference`` has no cap, no ``_compile_set`` managed-section
#: branch exists for it) and carries no "fill against a cap" to report;
#: no builder may invent a reference probe (blind-review F1).
SURFACE_FILL_CAPPED_DESTINATIONS: tuple[str, ...] = ("skill-md", "claude-md")


def one_motion_allowed(home: Path | str, destination: str) -> bool:
    """The S-10 policy gate: True when ``destination`` may route in one
    motion — either it never needed review (not in the set) or the
    operator opted in via the committed config (fail-closed parse)."""
    if destination not in ONE_MOTION_UNROUTABLE:
        return True
    return policy_config.one_motion_enabled(home, destination)


class VerbError(Exception):
    """A resolution verb refused or failed before committing."""

    exit_code = 1


class SecretRefusal(VerbError):
    """P2-7: the full-record-file scan hit — nothing written, no bypass."""

    def __init__(self, message: str, hits: list) -> None:
        super().__init__(message)
        self.hits = hits


#: U20 gate R1 (F5-5 guided commit-first): the pinned, stable substring of
#: the gitops-side dirty-target refusal — extracted so the UI's marker
#: match and the tests import the SAME constant this raise site uses
#: (never a hand-copied substring; chezmoi.py carries the twin for the
#: user-scope leg, ``chezmoi.CHEZMOI_DIRTY_MARKER``).
GITOPS_DIRTY_MARKER = "has unrelated uncommitted changes"


class DirtyTargetError(VerbError):
    """The compile target has unrelated uncommitted changes."""


class NoProposalError(VerbError):
    """route without ``--dest`` and without a proposal sibling."""


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
    diff: str | None = None  # route_direct: staged diff · hook route: the
    #   ENTIRE generated script (08 §8.1 approval flow — never a summary)
    warnings: list[str] = field(default_factory=list)  # callers MUST print
    post_notes: list[str] = field(default_factory=list)  # required manual
    #   steps (M3-11: settings.json snippet, ./install.sh) — callers print
    #   to stdout; the hook is inert by design until the human does them
    # doc 13 §4 two-phase: the HOST half of a canon-touching verb. All None
    # for ledger-only verbs, for the chezmoi user flow (the dotfiles repo
    # commits itself), and after a host-phase failure (drift warning set).
    host_commit_sha: str | None = None
    host_push: gitops.PushResult | None = None
    target: Path | None = None  # the compiled canon file (host side)
    # Resolution-evidence unit (§2.1): three genuinely new fields. All
    # `route`-only (`None` on every other verb) EXCEPT `deferred_until`,
    # which is `defer`-only — never derived by re-parsing `commit_message`
    # (that is what `cli.py`'s `_routed_destination` / the `" until "`
    # split used to do; those still exist for the plain-text summary
    # line, which is unrelated and unchanged). `destination`/`variant`
    # are `spec.destination`/`spec.variant` verbatim — `variant` is what
    # lets a `claude-md:local` route be told apart from a managed
    # `claude-md` route: nothing else on this dataclass does.
    destination: str | None = None
    variant: str | None = None
    deferred_until: str | None = None


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
            f"compile target {target} {GITOPS_DIRTY_MARKER} — "
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
    qualifier) — ``reference:<file>`` names an existing references file
    (08 §1 References-compiler pin), ``new-skill:<name>`` names the skill
    to scaffold (08 §8.1 — the name slot is the human's call), and (A2
    §4.1) ``claude-md:local`` / ``claude-md:rules:<topic>`` carry the
    ``variant`` a bare ``--dest`` selects — ``"local"`` / ``"rules:
    <topic>"`` in the qualifier slot, decoded at
    :func:`_resolve_target`."""
    if dest.startswith("reference:"):
        name = dest.split(":", 1)[1]
        if not name:
            raise VerbError("reference:<file> needs a file name")
        return "reference", name
    if dest.startswith("new-skill:"):
        name = dest.split(":", 1)[1]
        try:
            return "new-skill", validate_skill_name(name)
        except SkillScaffoldError as exc:
            raise VerbError(str(exc)) from exc
    if dest.startswith("claude-md:"):
        qualifier = dest[len("claude-md:") :]
        if qualifier == "local":
            return "claude-md", "local"
        if qualifier.startswith("rules:"):
            topic = qualifier[len("rules:") :]
            if not topic:
                raise VerbError(
                    "claude-md:rules:<topic> needs a topic — "
                    "claude-md:rules:<topic-slug>"
                )
            try:
                validate_skill_name(topic)
            except SkillScaffoldError as exc:
                # Y-9 (A2 §4.1 obligation): a rules topic slug error must
                # name "rules topic", never validate_skill_name's own
                # "new-skill name … must be kebab-case" — that misnames
                # what the user got wrong (it names a rules file, not a
                # skill).
                raise VerbError(
                    f"rules topic {topic!r} must be kebab-case "
                    "([a-z0-9-], starting alphanumeric) — it names the "
                    "rules file"
                ) from exc
            return "claude-md", f"rules:{topic}"
        raise VerbError(
            f"claude-md qualifier {qualifier!r} not recognized — use "
            "claude-md:local or claude-md:rules:<topic>"
        )
    if dest not in PROPOSAL_DESTINATIONS:
        raise VerbError(
            f"--dest must be one of {list(PROPOSAL_DESTINATIONS)} "
            f"(or reference:<file> / new-skill:<name> / claude-md:local / "
            f"claude-md:rules:<topic>), got {dest!r}"
        )
    return dest, None


@dataclass(frozen=True)
class _Destination:
    """A2 §4.4A — the route-time INPUT seam. What a route resolves to,
    structured: ``ref_name`` is the pre-A2 qualifier slot (``reference:``
    file name, ``new-skill:`` name, or an undecoded claude-md qualifier
    string from a bare ``--dest``); ``variant``/``rules_topic``/
    ``rules_paths`` are the A2 fields, sourced from a proposal's own
    keys on the proposal branch. Both branches carry all fields — the
    proposal branch used to return ``data["destination"], None``,
    silently dropping variant/rules_topic/rules_paths (the misroute
    hazard §4.4 names)."""

    destination: str
    ref_name: str | None = None
    variant: str | None = None
    rules_topic: str | None = None
    rules_paths: list[str] | None = None


def _resolve_destination(
    bucket_dir: Path, record_id: str, dest: str | None
) -> _Destination:
    """Destination for a route: ``--dest`` overrides; else the proposal
    sibling; neither → error."""
    if dest is not None:
        destination, qualifier = _parse_dest(dest)
        return _Destination(destination, qualifier)
    proposal_path = bucket_dir / "proposals" / f"{record_id}.yaml"
    if not proposal_path.is_file():
        raise NoProposalError(
            f"no proposal for {record_id} — pass --dest or run review"
        )
    data = read_proposal(proposal_path)
    validate_proposal(data)
    return _Destination(
        data["destination"],
        None,
        data.get("variant"),
        data.get("rules_topic"),
        data.get("rules_paths"),
    )


def _routed_to(
    bucket_dirs: list[Path],
    destination: str,
    *,
    scope_pred=None,
    exclude: frozenset[str] | set[str] = frozenset(),
    variant: str | None = None,
    rules_topic: str | None = None,
) -> list[Record]:
    """Resolved records routed to ``destination`` — the compile set.

    A2 §4.5A: ``variant``/``rules_topic`` partition the set so a rules
    topic file, a ``local`` file, and plain ``claude-md`` never
    cross-contaminate — in EITHER direction. Because ``routing.destination``
    stays ``"claude-md"`` for every rules/local record (R-2), the default
    ``variant=None`` here means "no variant on the record" (a record
    whose routing carries no ``variant`` key, i.e. every plain-claude-md
    / skill-md / new-skill record already routed pre-A2) — the byte-
    identical, P-A6 default. A caller resolving a specific topic passes
    ``variant="rules", rules_topic=<topic>``; a ``local`` target passes
    ``variant="local"``."""
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
            routing = record.routing or {}
            if routing.get("destination") != destination:
                continue
            if routing.get("variant") != variant:
                continue
            if variant == "rules" and routing.get("rules_topic") != rules_topic:
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

    destination: str  # skill-md | claude-md | reference | hook | new-skill
    scope_kind: str  # "skill" | "project" | "skill-root" | "user"
    bucket_dir: Path
    target: Path | None  # None for a default (created-on-demand) reference
    host_repo: Path | None
    refs_dir: Path | None = None
    ref_name: str | None = None
    new_skill: str | None = None  # new-skill only: the human-named skill
    #: A2 §2.1/§4.3: the claude-md scope parameterization — ``None`` (the
    #: byte-identical P-A6 default), ``"rules"``, or ``"local"``. Only
    #: ever set when ``destination == "claude-md"``.
    variant: str | None = None
    rules_topic: str | None = None  # variant == "rules" only
    rules_paths: tuple[str, ...] | None = None  # variant == "rules" only
    #: A2 §5.1: True iff a project-scope zero-match refusal was bypassed
    #: via ``--allow-empty-glob`` (the routing-metadata bypass record,
    #: test obligation §13 item 3).
    glob_bypass: bool = False


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


def _decode_claude_md_qualifier(qualifier: str) -> tuple[str, str | None]:
    """A2 §4.4B: the ONE decode point for a bare ``--dest``'s claude-md
    qualifier (``_parse_dest``'s ``"local"`` / ``"rules:<topic>"``
    strings) into ``(variant, rules_topic)``. Both fresh-route paths —
    ``route`` (via ``_resolve_destination``'s ``--dest`` branch, which
    passes the qualifier through undecoded) and ``route_direct`` (which
    calls ``_parse_dest`` directly) — funnel through here because it
    lives INSIDE :func:`_resolve_target`'s claude-md branch, the single
    site both callers reach. A naive build that skips this decode
    silently resolves a bare ``--dest claude-md:rules:<topic>`` to plain
    ``~/.claude/CLAUDE.md`` (the misroute hazard §4.4 names)."""
    if qualifier == "local":
        return "local", None
    if qualifier.startswith("rules:"):
        return "rules", qualifier[len("rules:") :]
    raise VerbError(f"unrecognized claude-md qualifier {qualifier!r}")


def _user_rules_dir(user_claude_md_target: Path) -> Path:
    """§2.1: ``~/.claude/rules/`` sits beside ``~/.claude/CLAUDE.md`` —
    resolved off the SAME (possibly test-overridden) user target every
    other user-scope call site uses, never a second ``~/.claude`` guess."""
    return user_claude_md_target.parent / "rules"


def _project_rules_dir(host_repo: Path) -> Path:
    """§2.1: ``<host repo>/.claude/rules/``."""
    return host_repo / ".claude" / "rules"


def _validate_project_globs(
    host: Path, patterns: tuple[str, ...], allow_empty_glob: bool
) -> bool:
    """§5.1: project-scope per-pattern zero-match refusal — the one real
    silent-failure guard the parameterization introduces. The matcher is
    stdlib recursive glob over the host working tree (an approximation of
    CC's own gitignore-style matcher, noted as a limitation, not a
    blocker). A pattern with an unparseable bracket does not raise
    (empirically, ``fnmatch.translate`` never raises on an unbalanced
    ``[``) — it degrades to a non-matching literal, exactly like CC's own
    documented partial failure, so "unparseable" folds into "zero-match"
    with no separate parse step (§5.1 Grounding).

    Returns True iff at least one pattern was dead AND the caller passed
    ``allow_empty_glob`` (the bypass this function's caller records into
    routing metadata, test obligation §13 item 3); returns False when
    every pattern matched (nothing to record). Raises :class:`VerbError`
    naming every dead pattern when the escape was not given (P-A7: a
    rule-level "did any match?" would pass a partial failure — this
    refuses per pattern)."""
    dead = [
        pattern
        for pattern in patterns
        if not glob_mod.glob(pattern, root_dir=host, recursive=True)
    ]
    if not dead:
        return False
    if not allow_empty_glob:
        listed = ", ".join(repr(p) for p in dead)
        raise VerbError(
            f"rules_paths pattern(s) match nothing in {host}: {listed} — "
            "a rule with a non-matching pattern never fires; fix the "
            "pattern(s), or pass --allow-empty-glob to route unverified "
            "(the write-the-rule-before-the-files case)"
        )
    return True


def _resolve_local_target(
    home: Path,
    bucket_dir: Path,
    scope: str,
    project_path: Path | None,
    *,
    check_dirty: bool,
) -> TargetSpec:
    """A2 §6: ``CLAUDE.local.md`` — project scope ONLY, via a POSITIVE
    guard (never the ``else``-fallthrough discipline §9 forbids), and
    gitignore-verified (P-A3, the privacy guard) before it is ever routed
    into."""
    if scope != "project":
        raise VerbError(
            "CLAUDE.local.md exists only per project — route to project "
            "scope, or use claude-md/rules"
        )
    host = _project_host_or_refuse(home, bucket_dir, project_path)
    target = host / "CLAUDE.local.md"
    if check_dirty:
        if not gitops.check_ignore(host, target):
            raise VerbError(
                f"{target} is not gitignored in {host} — add "
                "`CLAUDE.local.md` to .gitignore, then re-route (routing "
                "a personal lesson into a tracked file publishes it to "
                "the team)"
            )
        if target.is_file():
            _abort_if_dirty(host, target)
    return TargetSpec(
        "claude-md", "project", bucket_dir, target, host, variant="local"
    )


def _resolve_rules_target(
    home: Path,
    bucket_dir: Path,
    scope: str,
    rules_topic: str | None,
    rules_paths: list[str] | tuple[str, ...] | None,
    *,
    user_claude_md: Path | str | None,
    chezmoi_bin: str,
    project_path: Path | None,
    check_dirty: bool,
    allow_empty_glob: bool,
) -> TargetSpec:
    """A2 §2.1/§9: ``rules:<topic>`` — user or project scope only.
    Skill scope is the P-A13 deferral, raised via a POSITIVE guard (the
    same anti-fallthrough discipline as :func:`_resolve_local_target`) —
    never the unguarded ``claude-md`` ``else`` this replaces for the
    rules case."""
    if rules_topic is None:
        raise VerbError(
            "a rules route needs a topic — claude-md:rules:<topic>"
        )
    if scope not in ("user", "project"):
        raise VerbError(
            f"claude-md:rules:{rules_topic} is not available for scope "
            f"{scope!r} yet — plugin-shipped rules is an unresolved "
            "documentation gap (P-A13); route to user or project scope"
        )
    paths_tuple = tuple(rules_paths) if rules_paths else None
    if scope == "user":
        base = Path(
            user_claude_md if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD
        ).expanduser()
        target = _user_rules_dir(base) / f"{rules_topic}.md"
        if check_dirty:
            # E-17 preflight, same as plain user claude-md: chezmoi
            # drift/dirty aborts BEFORE the ledger commit. U-A2-glob-tree
            # (§5.1): no canonical tree exists for a user-scope glob, so
            # only the schema-shape check (already run at proposal
            # validation, §4.3(4)) applies — no zero-match assertion here.
            preflight_user_scope(target, chezmoi=chezmoi_bin)
        return TargetSpec(
            "claude-md", "user", bucket_dir, target, None,
            variant="rules", rules_topic=rules_topic, rules_paths=paths_tuple,
        )
    host = _project_host_or_refuse(home, bucket_dir, project_path)
    target = _project_rules_dir(host) / f"{rules_topic}.md"
    bypassed = False
    if check_dirty and paths_tuple:
        bypassed = _validate_project_globs(host, paths_tuple, allow_empty_glob)
    if check_dirty and target.is_file():
        _abort_if_dirty(host, target)
    return TargetSpec(
        "claude-md", "project", bucket_dir, target, host,
        variant="rules", rules_topic=rules_topic, rules_paths=paths_tuple,
        glob_bypass=bypassed,
    )


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
    variant: str | None = None,
    rules_topic: str | None = None,
    rules_paths: list[str] | tuple[str, ...] | None = None,
    allow_empty_glob: bool = False,
) -> TargetSpec:
    """PRE-FLIGHT target resolution (doc 13 §4 step c): registry gates
    (H-3) + dirty checks against the HOST repo, all raising BEFORE any
    commit. Pure — writes nothing.

    A2 §4.4: ``variant``/``rules_topic``/``rules_paths`` are the
    structured params a proposal-sourced route carries (threaded by
    ``_resolve_destination``'s callers); when ``variant`` is left
    ``None`` and ``ref_name`` carries a bare-``--dest`` claude-md
    qualifier (``"local"`` / ``"rules:<topic>"``), it is decoded here via
    :func:`_decode_claude_md_qualifier` — the single decode point both
    fresh-route entrypoints reach. ``variant=None`` and a plain
    ``ref_name`` (or none) reproduces today's three-scope claude-md
    resolution byte-identically (P-A6)."""
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
        eff_variant, eff_topic = variant, rules_topic
        if eff_variant is None and ref_name is not None:
            eff_variant, eff_topic = _decode_claude_md_qualifier(ref_name)
        if eff_variant == "local":
            return _resolve_local_target(
                home, bucket_dir, scope, project_path, check_dirty=check_dirty
            )
        if eff_variant == "rules":
            return _resolve_rules_target(
                home, bucket_dir, scope, eff_topic, rules_paths,
                user_claude_md=user_claude_md,
                chezmoi_bin=chezmoi_bin,
                project_path=project_path,
                check_dirty=check_dirty,
                allow_empty_glob=allow_empty_glob,
            )
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

    if destination == "new-skill":
        if ref_name is None:
            raise VerbError(
                "new-skill needs a name — the name slot is the human's "
                "call (08 §8.1): route --dest new-skill:<name>"
            )
        name = validate_skill_name(ref_name)
        hosts = load_hosts(home)
        if hosts.skills_root is None:
            raise VerbError(
                "no skills root registered — the scaffold lands under it; "
                "self-learn host add <path> --skills-root"
            )
        root = _gate_host(home, hosts.skills_root, "skills-root")
        marketplace = root / ".claude-plugin" / "marketplace.json"
        if not marketplace.is_file():
            raise VerbError(
                f"skills root {root} has no .claude-plugin/marketplace.json "
                "— the scaffold appends an entry to an EXISTING marketplace "
                "(08 §8.1); it never creates one"
            )
        plugin_dir = root / "plugins" / name
        target = plugin_dir / "skills" / name / "SKILL.md"
        if plugin_dir.exists():
            # M3-9 collision rule: append only into a self-learn-scaffolded
            # skill (its SKILL.md carries a managed section); anything else
            # is a FOREIGN authored plugin — refuse, never inject.
            if not (
                target.is_file()
                and BEGIN_MARKER in target.read_text(encoding="utf-8")
            ):
                raise VerbError(
                    f"plugins/{name} already exists and is a foreign "
                    "authored plugin (no self-learn managed section in its "
                    "SKILL.md) — refusing to inject (M3-9); pick another "
                    "name or route to its skill-md through review"
                )
        if check_dirty:
            for probe in (target, marketplace):
                if probe.is_file():
                    _abort_if_dirty(root, probe)
        return TargetSpec(
            "new-skill", "skill-root", bucket_dir, target, root, new_skill=name
        )

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


# ---------------------------------------------------------------- hooks (T17)


@dataclass(frozen=True)
class HookApplyResult:
    """Host-phase outcome for a hook script write (mirrors the compile
    results' duck type: ``changed`` gates the host commit)."""

    path: Path
    changed: bool
    applied: bool = True


@dataclass(frozen=True)
class _HookRoute:
    """Everything a hook route pre-flights before any commit."""

    spec: TargetSpec
    meta: dict  # the routing.hook payload (approved compile artifacts)
    snippet: str
    script: str


def _hooks_dir_for(home: Path, scope: str) -> tuple[Path, Path]:
    """M3-7 script placement, via the hosts registry, AS AMENDED by the
    D1 ratification (doc 13 §7.3, 2026-07-17): skill-scoped →
    ``plugins/<p>/hooks/`` (the plugin owning the skill — canon in ITS
    plugin dir, unchanged); project/user-scoped → ``hooks/self-learn/``
    (a canon dir of the skills-root host itself, NOT the product's own
    plugin dir — guard scripts are host canon, and the product repo
    receives nothing but its own development work, doc 13 §7.3's
    governing principle). Both live under the gated skills root (the
    hooks ride install.sh's ``hooks/self-learn/*.sh`` +
    ``plugins/*/hooks/*.sh`` deploy surfaces). Returns
    (host_repo, hooks_dir).

    The two live pre-D1 guards (lrn-dd9489b2, lrn-4f5971c8) were migrated
    by hand at the D1 runbook step 1 — their ``routing.hook.script_path``
    is the truth for THEM; readers of an already-routed hook location use
    that stored path (:func:`_hook_script_location`), never re-derive it
    here. This function only matters for a NEW route."""
    if scope.startswith("skill:"):
        root, skill_dir = _hosts_skill_dir(home, scope.partition(":")[2])
        return root, skill_dir.parent.parent / "hooks"
    hosts = load_hosts(home)
    if hosts.skills_root is None:
        raise VerbError(
            "no skills root registered — hook scripts land under it; "
            "self-learn host add <path> --skills-root"
        )
    root = _gate_host(home, hosts.skills_root, "skills-root")
    return root, root / "hooks" / "self-learn"


def _resolve_hook_target(home: Path, record: Record, bucket_dir: Path) -> TargetSpec:
    """PRE-FLIGHT the hook script path (raises before any commit)."""
    root, hooks_dir = _hooks_dir_for(home, record.scope)
    trigger = record_title(record)
    try:
        name = script_name(record.id, trigger)
    except Exception as exc:  # HookCompileError: unsluggable trigger
        raise VerbError(str(exc)) from exc
    target = hooks_dir / name
    if target.exists():
        raise VerbError(
            f"hook script already exists at {target} — refusing to "
            "overwrite; supersede the record that owns it first"
        )
    scope_kind = "skill" if record.scope.startswith("skill:") else record.scope
    return TargetSpec("hook", scope_kind, bucket_dir, target, root)


def _replay_hook_examples(script: str, examples: dict) -> None:
    """M3-12: replay the analyst's allow/deny examples against the exact
    bytes the route will commit — BEFORE anything commits. Any mismatch
    aborts. (The scratch copy lives in a TemporaryDirectory and is never
    committed anywhere.)"""
    with tempfile.TemporaryDirectory(prefix="self-learn-hook-replay-") as scratch:
        probe = Path(scratch) / "guard.sh"
        probe.write_text(script, encoding="utf-8")
        probe.chmod(0o700)
        mismatches = replay_examples(probe, examples)
    if mismatches:
        raise VerbError(
            "guard replay failed — aborting the route (M3-12; the record "
            "stays pending):\n  " + "\n  ".join(mismatches)
        )


def _prepare_one_motion_hook(
    home: Path, record: Record, bucket_dir: Path, hook_input: dict | None
) -> _HookRoute:
    """The S-10-amended one-motion hook pre-flight: same integrity chain
    as the review-gated path — CLI-generated script (never caller-authored
    bytes), full schema validation, secret scan over every byte the route
    will publish, placement gates, and the M3-12 replay — all BEFORE the
    record or the script land anywhere. The only thing the config opt-in
    removed is the pending-record review pause; visibility survives (the
    caller prints the applied bytes) and activation stays manual."""
    if hook_input is None:
        raise VerbError(
            "one-motion hook route needs the compile input — pass "
            "--hook-input <yaml> carrying {rationale, hook: {tools, "
            "path_regex, deny_message}, examples: {allow, deny}} "
            "(routing-doctrine §5.1)"
        )
    data = dict(hook_input)
    data.setdefault("destination", "hook")
    if data["destination"] != "hook":
        raise VerbError(
            f"--hook-input names destination {data['destination']!r} — "
            "one-motion hook input must be hook-destined"
        )
    # bookkeeping fields the schema requires but that carry no judgment;
    # rationale is NOT defaulted — the over-block statement is the §4
    # judgment and must come from the author.
    data.setdefault("model", "one-motion-cli")
    data.setdefault("analyzed_at", _now_iso())
    # CLI-generated bytes, exactly like stamp_proposal (M2-21 for
    # executables): anything the caller wrote in `script` is overwritten.
    from .ledger_ops import _generate_hook_script  # same module family

    try:
        data["script"] = _generate_hook_script(record, data)
    except ProposalError as exc:
        raise VerbError(str(exc)) from exc
    data["record_sha"] = sha_anchor(record.body)
    try:
        validate_proposal(data)
    except ProposalError as exc:
        raise VerbError(f"hook compile input invalid: {exc}") from exc

    # P2-7: scan EVERY byte this route publishes — the whole compile
    # input (rationale, regex, messages, examples) plus the generated
    # script (the record text is scanned by the caller).
    import json as _json

    findings = secret_scan(_json.dumps(data, default=str))
    if findings:
        raise SecretRefusal(
            "secret scan hit in the hook compile input — refusing this "
            "route (P2-7; no bypass):\n" + format_refusal(findings),
            findings,
        )

    spec = _resolve_hook_target(home, record, bucket_dir)
    _replay_hook_examples(data["script"], data["examples"])

    hook = data["hook"]
    rel = spec.target.relative_to(spec.host_repo).as_posix()
    meta = {
        "tools": list(hook["tools"]),
        "path_regex": hook["path_regex"],
        "deny_message": hook["deny_message"],
        "script_path": rel,
        "script": data["script"],
    }
    snippet = settings_snippet(list(hook["tools"]), spec.target.name)
    return _HookRoute(
        spec=spec, meta=meta, snippet=snippet, script=data["script"]
    )


def _prepare_hook_route(
    home: Path, bucket_dir: Path, record: Record
) -> _HookRoute:
    """The hook route's pre-flight: proposal-carried compile input
    (M3-2), CLI-stamped script, record_sha freshness, replay — every
    refusal lands before any commit."""
    proposal_path = bucket_dir / "proposals" / f"{record.id}.yaml"
    if not proposal_path.is_file():
        raise VerbError(
            f"hook routes apply a proposal-carried, approved script — no "
            f"proposal for {record.id}; author proposals/{record.id}.yaml "
            "with the hook block (routing-doctrine §5.1), then "
            f"`self-learn proposal validate {record.id}`"
        )
    # P2-7: this verb publishes proposal-derived bytes into canon — scan
    # the proposal file itself, not only the record.
    _scan_or_refuse([proposal_path], None)
    data = read_proposal(proposal_path)
    try:
        validate_proposal(data)
    except ProposalError as exc:
        raise VerbError(f"hook proposal invalid: {exc}") from exc
    if data.get("destination") != "hook":
        raise VerbError(
            f"proposal for {record.id} proposes "
            f"{data.get('destination')!r}, not hook — a hook route needs "
            "the §5.1 compile input; re-analyze or author a hook proposal"
        )
    script = data.get("script")
    if not script:
        raise VerbError(
            f"hook proposal for {record.id} has no stamped script — run "
            f"`self-learn proposal validate {record.id}` (the CLI "
            "generates the bytes; they are never model-authored)"
        )
    if data.get("record_sha") != sha_anchor(record.body):
        raise VerbError(
            f"record {record.id} changed since analysis (record_sha "
            "mismatch) — aborting (M3-2: re-analysis + fresh approval, "
            "never silent regeneration); re-review the proposal, then "
            f"`self-learn proposal validate {record.id}` restamps it"
        )
    # m-5 defense-in-depth (review 2026-07-16, accepted follow-up):
    # record_sha binds the RECORD, not the script bytes — a hand edit of
    # the stamped script (or its hook block) after `proposal validate`
    # would otherwise route bytes nobody re-generated. Generation is
    # deterministic, so re-derive and compare.
    from .ledger_ops import _generate_hook_script  # same module family

    try:
        rederived = _generate_hook_script(record, data)
    except ProposalError as exc:
        raise VerbError(str(exc)) from exc
    if rederived != script:
        raise VerbError(
            f"stamped script for {record.id} does not match its "
            "re-derived bytes — the proposal's script or hook block "
            "changed after validation; re-review the hook block, then "
            f"`self-learn proposal validate {record.id}` restamps it "
            "(m-5: what routes is always what the generator produces)"
        )

    spec = _resolve_hook_target(home, record, bucket_dir)
    _replay_hook_examples(script, data["examples"])

    hook = data["hook"]
    rel = spec.target.relative_to(spec.host_repo).as_posix()
    meta = {
        "tools": list(hook["tools"]),
        "path_regex": hook["path_regex"],
        "deny_message": hook["deny_message"],
        "script_path": rel,
        "script": script,
    }
    snippet = settings_snippet(list(hook["tools"]), spec.target.name)
    return _HookRoute(spec=spec, meta=meta, snippet=snippet, script=script)


def _hook_manual_steps(snippet: str, name: str) -> list[str]:
    """M3-11: the route ends by printing the required manual steps — the
    hook is inert by design until both are done."""
    return [
        "hook routed — two manual steps remain (the guard is INERT until "
        "both):",
        f"  1. run ./install.sh — the ~/.claude/hooks/{name} symlink "
        "materializes only then",
        "  2. add this to ~/.claude/settings.json (hooks):\n"
        f"     {snippet}",
    ]


def _write_hook_script(target: Path, script: str) -> HookApplyResult:
    """Write the APPROVED bytes (verbatim — M3-2) + executable bit.
    Idempotent: byte-identical executable content reports unchanged."""
    current = (
        target.read_text(encoding="utf-8") if target.is_file() else None
    )
    executable = target.is_file() and bool(target.stat().st_mode & 0o100)
    if current == script and executable:
        return HookApplyResult(path=target, changed=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script, encoding="utf-8")
    target.chmod(target.stat().st_mode | 0o755)
    return HookApplyResult(path=target, changed=True)


def _hook_script_location(
    home: Path, record: Record, warnings: list[str]
) -> tuple[Path, Path, str] | None:
    """PRE-FLIGHT the M3-4 rollback: where the routed record's script
    lives. Returns (host_repo, script_path, rel), or None (with a loud
    warning) when the record carries no script_path."""
    meta = (record.routing or {}).get("hook") or {}
    rel = meta.get("script_path")
    if not rel:
        warnings.append(
            f"{record.id} is hook-routed but carries no routing.hook."
            "script_path — remove its guard script by hand"
        )
        return None
    hosts = load_hosts(home)
    if hosts.skills_root is None:
        raise VerbError(
            "no skills root registered — cannot locate the hook script to "
            "remove; self-learn host add <path> --skills-root"
        )
    root = _gate_host(home, hosts.skills_root, "skills-root")
    return root, root / rel, rel


def _remove_hook_script(
    home: Path,
    removal: tuple[Path, Path, str],
    record_id: str,
    note: str | None,
    warnings: list[str],
    post_notes: list[str],
) -> str | None:
    """M3-4 host phase: ``git rm`` the script (same resolution flow —
    ledger committed first, host commit pinned ``… (hook removed)``) and
    print the un-registration reminder. A failure is loud, never a
    rollback (the ledger stays truth)."""
    host_repo, script, rel = removal
    name = script.name
    post_notes.append(
        f"hook retired — finish by hand: remove the settings.json "
        f"PreToolUse entry for {name} and the dead ~/.claude/hooks/{name} "
        "symlink (install.sh only adds links, it never removes them)"
    )
    if not script.is_file():
        warnings.append(
            f"hook script {script} already absent — nothing to remove"
        )
        return None
    try:
        with gitops.commit_lock(host_repo):
            gitops._git(  # noqa: SLF001 — same module family
                host_repo, "rm", "-q", "--ignore-unmatch", "--", str(script)
            )
            if script.exists():
                # untracked script: plain unlink — nothing tracked changed,
                # so there is nothing to commit
                script.unlink()
                return None
            return gitops.commit(
                host_repo,
                f"self-learn: apply {record_id} → {rel} (hook removed)",
                body=note,
                paths=[script],
            )
    except (gitops.GitOpsError, OSError) as exc:
        warning = (
            f"HOOK REMOVAL FAILED after the ledger commit ({exc}) — remove "
            f"{script} by hand; the ledger stays truth (H-2)"
        )
        print(f"self-learn: {warning}", file=sys.stderr)
        warnings.append(warning)
        return None


def _compile_set(home: Path, spec: TargetSpec) -> list[Record]:
    """The compile set, read straight off disk (the ledger op commits
    FIRST now — no shadow copies; superseded old records already dropped
    out via the compiler's status filter)."""
    if spec.destination == "skill-md":
        return _routed_to([spec.bucket_dir], "skill-md")
    if spec.destination == "new-skill":
        # a scaffolded skill may collect lessons from ANY bucket — the
        # name on the routing block is the grouping key.
        return [
            r
            for r in _routed_to(_all_bucket_dirs(home), "new-skill")
            if (r.routing or {}).get("new_skill") == spec.new_skill
        ]
    # A2 §4.5A: partition on (variant, rules_topic) — a rules topic file,
    # a `local` file, and plain claude-md must never cross-contaminate,
    # in EITHER direction. `spec.variant`/`spec.rules_topic` compose with
    # (never replace) the scope filtering below; a plain-claude-md spec
    # carries variant=None, which _routed_to reads as "no variant on the
    # record" — the byte-identical P-A6 default.
    if spec.scope_kind == "user":
        return _routed_to(
            _all_bucket_dirs(home), "claude-md", scope_pred=lambda s: s == "user",
            variant=spec.variant, rules_topic=spec.rules_topic,
        )
    # project / skill-root claude-md: ONE file can serve BOTH roles — a
    # repo registered as project host AND skills root (the shipped
    # claude-skills shape). The compile set must be the UNION of every
    # scope that resolves to this file, or each route of one scope
    # ERASES the other scope's lines and recompile cannot restore them
    # (adversarial review 2026-07-17 finding 3; latent since M1). A
    # single-role host degenerates to exactly the old per-scope set.
    host = spec.host_repo.resolve() if spec.host_repo is not None else None
    records: list[Record] = []
    seen: set[str] = set()
    for bucket in discover_buckets(home):
        if bucket.scope != "project":
            continue
        project = bucket_project_path(bucket.path)
        if project is None or host is None:
            continue
        if Path(project).resolve() != host:
            continue
        for r in _routed_to(
            [bucket.path], "claude-md", scope_pred=lambda s: s == "project",
            variant=spec.variant, rules_topic=spec.rules_topic,
        ):
            if r.id not in seen:
                seen.add(r.id)
                records.append(r)
    hosts = load_hosts(home)
    if (
        hosts.skills_root is not None
        and host is not None
        and Path(hosts.skills_root).resolve() == host
    ):
        skill_dirs = [
            b.path for b in discover_buckets(home) if b.scope == "skill"
        ]
        for r in _routed_to(
            skill_dirs, "claude-md", scope_pred=lambda s: s.startswith("skill:"),
            variant=spec.variant, rules_topic=spec.rules_topic,
        ):
            if r.id not in seen:
                seen.add(r.id)
                records.append(r)
    return records


def surface_fill(
    home: Path,
    bucket_dir: Path,
    scope: str,
    *,
    user_claude_md: Path | str | None = None,
    cache: dict[Path, SectionResult] | None = None,
) -> dict[str, dict]:
    """09 §11 Y-20 / 08 §1 `surface_fill` field: a READ-ONLY loaded-surface
    fill probe over the two CAPPED managed-section destinations
    (:data:`SURFACE_FILL_CAPPED_DESTINATIONS`) — ``reference`` is never
    probed (F1).

    For each capped destination: resolve the target through the existing
    :func:`_resolve_target` in E-17 read-only mode (``check_dirty=False``
    — no dirty-abort, no host-mutation preflight; the SAME scope rules the
    `o`-cycle honors, no second scope definition). ANY :class:`VerbError`
    — scope-invalid, missing ``SKILL.md``, unregistered host, an unsound
    registered host, no skills root registered — omits that destination's
    key entirely (never a zero, never a guess; F5). A target that exists
    on disk but carries no managed-section markers yet (bootstrap) or does
    not exist on disk yet (first route to a fresh CLAUDE.md) reads as
    empty text, which :func:`compilers.compile_managed_text` reports as
    ``entries: 0`` / ``words: 0`` — a fully-available surface.

    The compile set is the records ALREADY routed to that target
    (:func:`_compile_set`); :func:`compilers.compile_managed_text` filters
    to ``status == "routed"`` internally (``_eligible``), so a still-
    pending record — including the one this probe is being computed for
    — is never counted (no builder-side pending-exclusion filter needed,
    F8). Caps are the compiler's effective defaults — there is no
    per-target override mechanism yet (F6).

    ``user_claude_md`` overrides the user-scope target the same way
    :func:`route` accepts it (defaults to :data:`DEFAULT_USER_CLAUDE_MD`,
    the real chezmoi-managed file — the correct real destination to
    report fill for; test callers override it, same idiom as every other
    ``_resolve_target`` call site).

    ``cache`` memoizes one compiled :class:`~self_learn.compilers.SectionResult`
    per resolved target path — pass the SAME dict across every record in
    one CLI invocation so records sharing a target (e.g. every record in
    one skill bucket, or every user-scoped record) pay for the compile
    exactly once (08 §1 (e))."""
    if cache is None:
        cache = {}
    result: dict[str, dict] = {}
    for destination in SURFACE_FILL_CAPPED_DESTINATIONS:
        try:
            spec = _resolve_target(
                home,
                bucket_dir,
                scope,
                destination,
                None,
                user_claude_md=user_claude_md,
                check_dirty=False,
            )
            target = spec.target
            if target is None:  # reference-shaped spec — never reached
                continue  # here, kept defensive (TargetSpec.target is Optional)
            key = target.resolve()
            if key not in cache:
                # blind-review F2: the read + compile step is inside the
                # SAME try as the resolve — a corrupted managed-section
                # marker pair (CompileError) or an unreadable/undecodable
                # target (OSError/UnicodeDecodeError) is exactly as
                # degradable as a VerbError (scope-invalid, missing
                # SKILL.md, unregistered host): omit this destination's
                # key and move on, never let one broken target's read
                # crash the WHOLE `list --json` call for every record —
                # that would blank the Detail page's entire proposal/why
                # region for every OTHER record sharing that target too.
                text = target.read_text(encoding="utf-8") if target.is_file() else ""
                cache[key] = compile_managed_text(text, _compile_set(home, spec))
        except (VerbError, CompileError, OSError, UnicodeDecodeError):
            continue
        section = cache[key]
        entry = {
            "entries": section.entry_count,
            "entries_cap": DEFAULT_MAX_ENTRIES,
            "words": section.word_count,
            "words_cap": DEFAULT_MAX_WORDS,
            "over_cap": section.over_cap,
        }
        if destination == "claude-md":
            # A2 §8/P-A9: the >5-topic-files churn signal — a NEW datum
            # with no per-file home, attached only to the claude-md
            # entry. `spec` here is the PLAIN (variant=None) claude-md
            # target (this probe never threads a variant), so its rules
            # dir is derived off that target's own parent (§2.1) — a
            # missing directory counts 0 (no builder-side special case
            # needed: a skill-root scope's rules dir never exists, since
            # skill-scope rules are deferred, §9).
            if scope == "user":
                rules_dir = _user_rules_dir(target)
            elif spec.host_repo is not None:
                rules_dir = _project_rules_dir(spec.host_repo)
            else:
                rules_dir = None
            count = (
                len(list(rules_dir.glob("*.md")))
                if rules_dir is not None and rules_dir.is_dir()
                else 0
            )
            entry["rules_topic_count"] = count
            if count > 5:
                # OR-ed with, never replacing, the per-file over_cap above
                # (§8 pin: both signals feed the SAME WARNING path).
                entry["over_cap"] = True
                entry["cap_reason"] = "rules-topics"
        result[destination] = entry
    return result


@dataclass(frozen=True)
class _Retirement:
    """Pre-flighted host-side cleanup for a ROUTED record being retired
    (standalone supersede, supersede-completion-at-route, graduate): the
    doc target whose compiled entry must drop, or the hook script to
    remove (M3-4). At most one of the two is set; both None means the
    record has no host presence to clean (pending, reference-routed —
    references are append-only)."""

    spec: TargetSpec | None = None
    removal: tuple[Path, Path, str] | None = None


def _retirement_preflight(
    home: Path,
    record: Record,
    bucket_dir: Path,
    warnings: list[str],
    *,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
) -> _Retirement:
    """Resolve a retiring record's host-side cleanup BEFORE any commit
    (doc 13 §4 step c — the standalone supersede verb has always done
    this; route's ``teach --supersedes`` completion and graduate now
    share it, closing the stale-line gap found live 2026-07-16: a
    cross-surface supersede left the old advisory in canon with no
    repair path). Raises (refusal, nothing committed) when the old
    record's host is unsound."""
    if record.status != "routed":
        return _Retirement()
    routing = record.routing or {}
    destination = routing.get("destination")
    if destination in ("skill-md", "claude-md", "new-skill"):
        return _Retirement(
            spec=_resolve_target(
                home,
                bucket_dir,
                record.scope,
                destination,
                routing.get("new_skill") if destination == "new-skill" else None,
                user_claude_md=user_claude_md,
                chezmoi_bin=chezmoi_bin,
                # A2 §4.4B note: this is a RETIREMENT read of the STORED
                # routing block (not a fresh route), so only variant/
                # rules_topic thread through — they are needed to resolve
                # the correct target PATH. rules_paths is deliberately
                # NOT threaded here: re-running the §5.1 zero-match
                # refusal against an OLD record's globs at retirement
                # time would risk blocking a legitimate supersede/
                # graduate over an unrelated stale glob — that
                # re-assertion is selfcheck's job (§5.2), not a
                # retirement preflight's.
                variant=routing.get("variant"),
                rules_topic=routing.get("rules_topic"),
            )
        )
    if destination == "hook":
        return _Retirement(
            removal=_hook_script_location(home, record, warnings)
        )
    return _Retirement()


def _retirement_host_phase(
    home: Path,
    retirement: _Retirement,
    record_id: str,
    *,
    note: str | None,
    chezmoi_bin: str,
    message: str,
    warnings: list[str],
    post_notes: list[str],
    skip_target: Path | None = None,
    user_push: bool = True,
) -> tuple[str | None, Path | None]:
    """HOST phase of a retirement: recompile the doc target (the entry
    drops — the ledger already committed the resolution) or ``git rm``
    the hook script. ``skip_target`` short-circuits when the successor's
    own compile just regenerated the same file (same-target supersede:
    one compile is the whole story). Returns (host_sha, host_repo)."""
    if retirement.spec is not None:
        if skip_target is not None and retirement.spec.target == skip_target:
            return None, None
        _, host_sha = _host_phase(
            home,
            retirement.spec,
            record_id,
            routed_record=None,
            note=note,
            chezmoi_bin=chezmoi_bin,
            message=message,
            warnings=warnings,
            user_push=user_push,
        )
        return host_sha, retirement.spec.host_repo
    if retirement.removal is not None:
        host_sha = _remove_hook_script(
            home, retirement.removal, record_id, note, warnings, post_notes
        )
        return host_sha, retirement.removal[0]
    return None, None


def _apply_target(
    home: Path,
    spec: TargetSpec,
    routed_record: Record | None,
    *,
    chezmoi_bin: str = "chezmoi",
    message: str | None = None,
    user_push: bool = True,
) -> tuple[object, list[Path]]:
    """HOST-phase compile (doc 13 §4 step e): write the target from the
    committed ledger state. Returns (compile_result, host paths to stage —
    empty for the chezmoi user flow, which commits its own repo)."""
    if spec.destination == "new-skill":
        compile_result, host_paths = _apply_new_skill(home, spec)
    elif spec.destination == "hook":
        # M3-2 verbatim apply: the APPROVED bytes ride the routing block
        # (copied there at the ledger phase), so the host phase — and any
        # later recompile repair — re-applies exactly what the human saw.
        meta = (
            (routed_record.routing or {}).get("hook") if routed_record else None
        ) or {}
        script = meta.get("script")
        if not script:
            raise VerbError(
                "hook record carries no routing.hook.script — nothing to apply"
            )
        compile_result = _write_hook_script(spec.target, script)
        host_paths = [spec.target] if compile_result.changed else []
    elif spec.destination == "reference":
        if routed_record is None:  # supersede/recompile never touch references
            raise VerbError("reference targets are append-only — nothing to apply")
        compile_result = compile_reference(
            spec.refs_dir, routed_record, dest=spec.ref_name
        )
        host_paths = [compile_result.path]
    elif spec.scope_kind == "user":
        assert spec.target is not None  # user/rules/local always resolve a target
        if spec.variant in ("rules", "local") and not spec.target.is_file():
            # A2 §4.5B: compile_managed_file (called by compile_user_scope
            # below) refuses a missing target — "the compiler never
            # creates target files". A first route to a NEW rules topic
            # needs its parent dir + an empty file bootstrapped first.
            # Scoped to the NEW variants only: plain ~/.claude/CLAUDE.md
            # keeps its pre-existing missing-is-error semantics (it is
            # never created here).
            spec.target.parent.mkdir(parents=True, exist_ok=True)
            spec.target.write_text("", encoding="utf-8")
        compile_result = compile_user_scope(
            spec.target,
            _compile_set(home, spec),
            chezmoi=chezmoi_bin,
            commit_message=message,
            push=user_push,
            # A2 §10.2/§10.5: the chezmoi-adopt offer fires ONLY for a
            # rules variant (never plain CLAUDE.md — §10.1) — threaded,
            # never guessed from the path.
            offer_adopt=spec.variant == "rules",
        )
        host_paths = []
    else:
        assert spec.target is not None  # skill-md/claude-md/new-skill always resolve one
        if spec.variant in ("rules", "local") and not spec.target.is_file():
            # A2 §4.5B: the host leg's bare write_text below also fails
            # for a project rule/local file whose `.claude/rules/` (or
            # the repo root, for local — always present) parent does not
            # yet exist — mkdir the parent first, scoped to the new
            # variants only.
            spec.target.parent.mkdir(parents=True, exist_ok=True)
        if not spec.target.is_file():
            # Judgment call (T7 brief, carried over): first route to a host
            # with no CLAUDE.md creates it empty and lets the managed-
            # section bootstrap (08 §1 pin) append the marker pair.
            # skill-md never reaches here — preflight refuses.
            spec.target.write_text("", encoding="utf-8")
        compile_result = compile_managed_file(spec.target, _compile_set(home, spec))
        # A2 §6/P-A3: a `local` target is GITIGNORED BY DESIGN (the
        # privacy guard already refused the route otherwise) — it must
        # never be staged/committed to the host repo (git itself refuses
        # `git add` on an ignored path, which is the point: the file
        # stays written on disk, outside git, forever). Every other
        # claude-md/skill-md/new-skill target stages as before.
        host_paths = [] if spec.variant == "local" else [spec.target]

    # surface-budget event (11 §4.3: compilers, inside verb flow) — the
    # attention-tax ledger. Spooled here, flushed by the calling verb.
    telemetry.spool_quiet(
        "surface-budget",
        target=spec.destination,
        words=getattr(compile_result, "word_count", None),
        overflow=bool(getattr(compile_result, "over_cap", False)),
    )
    return compile_result, host_paths


@dataclass(frozen=True)
class NewSkillApplyResult:
    """Host-phase outcome for a new-skill scaffold/recompile (duck-typed
    like the other compile results: ``changed`` gates the host commit)."""

    path: Path
    changed: bool
    scaffolded: bool  # plugin.json/SKILL.md/marketplace entry created now
    section: object | None = None  # the inner SectionResult
    applied: bool = True

    @property
    def over_cap(self) -> bool:
        return bool(getattr(self.section, "over_cap", False))

    @property
    def cap_reason(self):
        return getattr(self.section, "cap_reason", None)

    @property
    def word_count(self):
        return getattr(self.section, "word_count", None)


def _apply_new_skill(home: Path, spec: TargetSpec) -> tuple[NewSkillApplyResult, list[Path]]:
    """The T18 host apply: deterministic scaffold on first route (M3-9 —
    plugin.json + SKILL.md, marketplace entry appended exactly once),
    ordinary managed-section recompile ever after. Idempotent: a second
    run over unchanged records writes nothing."""
    records = _compile_set(home, spec)
    if not records:
        raise VerbError(
            f"no routed records name new-skill:{spec.new_skill} — nothing "
            "to compile"
        )
    name = spec.new_skill
    root = spec.host_repo
    target = spec.target
    plugin_dir = root / "plugins" / name
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    marketplace = root / ".claude-plugin" / "marketplace.json"
    # deterministic description: seeded from the FIRST routed lesson
    # (the compile set is already in pinned (routed_at, id) order).
    description = scaffold_description(records[0])

    changed = False
    scaffolded = False
    if not manifest.is_file():
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            plugin_manifest_text(name, description), encoding="utf-8"
        )
        changed = scaffolded = True
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(skill_md_seed(name, description), encoding="utf-8")
        changed = scaffolded = True
    section = compile_managed_file(target, records)
    changed = changed or section.changed

    try:
        market_text, market_changed = marketplace_with_entry(
            marketplace.read_text(encoding="utf-8"), name, description
        )
    except SkillScaffoldError as exc:
        raise VerbError(str(exc)) from exc
    if market_changed:
        marketplace.write_text(market_text, encoding="utf-8")
        changed = True

    result = NewSkillApplyResult(
        path=target, changed=changed, scaffolded=scaffolded, section=section
    )
    # SKILL.md first: the pinned apply subject names host_paths[0].
    return result, [target, manifest, marketplace]


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
    user_push: bool = True,
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
                home,
                spec,
                routed_record,
                chezmoi_bin=chezmoi_bin,
                message=message,
                user_push=user_push,
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
        # C2 O-5: the ONE user-facing message for a managed-but-broken
        # chezmoi sync (§3 row 4) — the write already succeeded, only the
        # sync degraded. getattr guards the other result types (e.g.
        # NewSkillApplyResult, SectionResult) that carry no such field;
        # absent/unmanaged (rows 1-2) return sync_warning=None, so nothing
        # prints there — silent, per the verbosity ruling.
        sync_warning = getattr(compile_result, "sync_warning", None)
        if sync_warning:
            print(f"self-learn: {sync_warning}", file=sys.stderr)
            warnings.append(sync_warning)
        # A2 §10.4(b): the bare-CLI chezmoi-adopt hint rides this SAME
        # channel — one stderr line, never a blocking prompt. Absent for
        # every result type that carries no such field (skill-md/
        # reference/new-skill/hook, and a plain-CLAUDE.md UserScopeResult,
        # which never sets it — §10.1).
        adopt_hint = getattr(compile_result, "adopt_hint", None)
        if adopt_hint:
            print(f"self-learn: {adopt_hint}", file=sys.stderr)
            warnings.append(adopt_hint)
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
    allow_empty_glob: bool = False,
) -> VerbResult:
    """Route a pending record into canon. See the module docstring for the
    pinned sequence; commit message ``self-learn: route lrn-… → <target>``
    (+ `` (supersedes lrn-…)`` when the record completes a
    ``teach --supersedes`` capture — old record superseded in the SAME
    commit). ``follow_up`` (11 §2.1: {action, unblocks_on?, note?}) rides
    the routing block — known-partial coverage, status stays terminal.
    ``allow_empty_glob`` (A2 §5.1) is the sanctioned escape past a
    project-scope rules route's zero-match glob refusal — the
    write-the-rule-before-the-files case; the bypass is recorded in the
    routing block (§13 item 3)."""
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
    old_record: Record | None = None
    if old_id is not None:
        old_path = find_record_path(home, old_id)
        _scan_or_refuse([old_path], None)  # this verb rewrites it too (P2-7)
        old_record = Record.from_path(old_path)

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
        resolved_dest = _resolve_destination(bucket_dir, record_id, dest)
        destination = resolved_dest.destination
        ref_name = resolved_dest.ref_name

        # (c) PRE-FLIGHT: registry gates (H-3 / doc 13 Q2) + host-repo
        # dirty checks + chezmoi drift/dirty for user scope. Every refusal
        # lands HERE — before any commit; the record stays pending. Hook
        # routes additionally pre-flight the proposal-carried script:
        # stamp presence, record_sha freshness (M3-2), and the M3-12
        # example replay against the exact bytes.
        hook_route: _HookRoute | None = None
        if destination == "hook":
            hook_route = _prepare_hook_route(home, bucket_dir, record)
            spec = hook_route.spec
        else:
            # A2 §4.4A: the proposal's variant/rules_topic/rules_paths
            # (or the bare --dest qualifier's decode) thread through here
            # — never `None`-dropped between _resolve_destination and
            # _resolve_target.
            spec = _resolve_target(
                home,
                bucket_dir,
                record.scope,
                destination,
                ref_name,
                user_claude_md=user_claude_md,
                chezmoi_bin=chezmoi_bin,
                variant=resolved_dest.variant,
                rules_topic=resolved_dest.rules_topic,
                rules_paths=resolved_dest.rules_paths,
                allow_empty_glob=allow_empty_glob,
            )

        # teach --supersedes completion retires a possibly-ROUTED old
        # record: its host-side cleanup (doc-target recompile / hook
        # script removal) pre-flights HERE, same as the standalone
        # supersede verb's step (c) — a refusal must land before any
        # commit.
        warnings: list[str] = []
        old_retire: _Retirement | None = None
        if old_record is not None:
            old_retire = _retirement_preflight(
                home,
                old_record,
                old_path.parent.parent,
                warnings,
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
        message_target = (
            f"new-skill:{ref_name}" if destination == "new-skill" else destination
        )
        message = f"self-learn: route {record_id} → {message_target}{suffix}"
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
        #
        # §2.3: `routing.by` names the actor that CHOSE THE DESTINATION,
        # derived here rather than hardcoded — the review UI's
        # approve-as-proposed argv omits --dest entirely (the proposal,
        # analyst-written, chose it); an explicit --dest is always the
        # human's flag, whether typed at the terminal or appended by the
        # UI's override. Read back below for the `route` telemetry event
        # so the two can never diverge (11 §4.3 / U-reach criterion 24).
        by = "human" if dest is not None else "analyst"
        with _ledger_write(home):
            if merged is not None:
                merged.write(path)
            touched = resolve_record(
                home,
                record_id,
                "routed",
                destination=destination,
                by=by,
                routed_at=routed_at,
                note=note,
                follow_up=follow_up,
                reference_file=ref_name if destination == "reference" else None,
                hook=hook_route.meta if hook_route is not None else None,
                new_skill=ref_name if destination == "new-skill" else None,
                # A2 §4.3/§4.4: persisted FROM the RESOLVED spec, not the
                # pre-decode resolved_dest — a bare --dest's qualifier is
                # only decoded inside _resolve_target, so reading it back
                # off `spec` is the one source that can never diverge from
                # what was actually written (closes the gap a decode-
                # inside-_resolve_target-only design would otherwise leave:
                # a persisted routing block with no variant on a
                # successfully-routed bare-dest rules file).
                variant=spec.variant,
                rules_topic=spec.rules_topic,
                rules_paths=list(spec.rules_paths) if spec.rules_paths else None,
                allow_empty_glob=spec.glob_bypass,
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

        # `route` telemetry (11 §4.3, U-reach §2.2): the resolution plane
        # was previously unobserved — nothing recorded that a routing
        # happened, where it went, or who chose it. Placement is pinned
        # immediately after the ledger commit closes above, NOT at the end
        # of the function: the ledger commit IS the routing (doc 13 §4.1),
        # so a host-phase failure below must still leave this event
        # spooled — undercounting exactly the interesting case would make
        # the instrument worse than silence. `spool_quiet`, never
        # `spool_event`: telemetry must never break a verb (module
        # docstring), so a spool refusal is a stderr warning, nothing more.
        telemetry.spool_quiet(
            "route",
            record=record_id,
            destination=destination,
            scope=record.scope,
            by=by,
            variant=spec.variant,
        )

        # (e) HOST phase: compile from the committed ledger state + host
        # commit (pinned apply subject), still under the sentinel hold.
        # Hook routes log the settings.json snippet in the host commit
        # body (M3-11) alongside any --note.
        host_note = note
        if hook_route is not None:
            snippet_block = f"settings.json snippet:\n{hook_route.snippet}"
            host_note = f"{note}\n\n{snippet_block}" if note else snippet_block
        routed_record = Record.from_path(
            bucket_dir / "resolved" / f"{record_id}.md"
        )
        compile_result, host_sha = _host_phase(
            home,
            spec,
            record_id,
            routed_record=routed_record,
            note=host_note,
            chezmoi_bin=chezmoi_bin,
            message=message,
            warnings=warnings,
            user_push=not no_push,
        )

        # (e2) retirement HOST phase for the superseded old record — its
        # compiled entry drops (or its guard script is removed) in the
        # same motion; skipped when the successor's own compile just
        # regenerated the same target.
        retire_notes: list[str] = []
        old_host_sha = None
        old_host_repo = None
        if old_retire is not None:
            old_host_sha, old_host_repo = _retirement_host_phase(
                home,
                old_retire,
                old_id,
                note=note,
                chezmoi_bin=chezmoi_bin,
                message=message,
                warnings=warnings,
                post_notes=retire_notes,
                skip_target=spec.target,
                user_push=not no_push,
            )

        # (f) push ledger, then push host (pinned retry, has_remote-guarded)
        # unless --no-push.
        push = None if no_push else gitops.push_if_remote(home)
        host_push = None
        if not no_push and host_sha is not None and spec.host_repo is not None:
            host_push = gitops.push_if_remote(spec.host_repo)
        if not no_push and old_host_sha is not None and old_host_repo is not None:
            # possibly the same repo as the successor's — a second push is
            # a no-op, and skipping it would strand the retirement commit
            # whenever the successor's own host commit didn't happen.
            gitops.push_if_remote(old_host_repo)
        return VerbResult(
            action="route",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            compile_result=compile_result,
            sentinel_owned=hold.owned,
            # 08 §8.1 approval flow: the verb shows the ENTIRE script as
            # the diff, and ends by printing the required manual steps.
            diff=hook_route.script if hook_route is not None else None,
            warnings=warnings,
            post_notes=(
                _hook_manual_steps(hook_route.snippet, spec.target.name)
                if hook_route is not None
                else [
                    f"new skill scaffolded at plugins/{ref_name} — run "
                    "./install.sh to symlink it into ~/.claude/skills "
                    "(M3-11); enrich the prose post-hoc whenever you like"
                ]
                if destination == "new-skill"
                and getattr(compile_result, "scaffolded", False)
                else []
            )
            + retire_notes,
            host_commit_sha=host_sha,
            host_push=host_push,
            target=spec.target,
            destination=spec.destination,
            variant=spec.variant,
        )
    finally:
        hold.release()  # (g) release iff owned


def route_direct(
    home: Path | str,
    record: Record,
    *,
    dest: str,
    by: str = "human",
    note: str | None = None,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
    project_path: Path | None = None,
    hook_input: dict | None = None,
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
    approval, so the diff is informational, never a prompt.

    ``by`` (§2.3, defaulted "human" — not required, so ``teach.py:698``'s
    existing call keeps working unmodified): names the actor that CHOSE
    THE DESTINATION. The bare-analyst ``teach --route`` path (destination
    from ``analyst.analyze()``) should thread ``by="analyst"`` — that call
    site is outside this unit's files (§6/§7); the plumbing here is what
    it needs."""
    home = Path(home)
    # BLOCKER 11 (audit 2026-07-16): this path writes a record straight
    # into resolved/ — gate the home BEFORE anything lands on disk.
    try:
        require_writable_home(home)
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
    destination, ref_name = _parse_dest(dest)
    if not one_motion_allowed(home, destination):
        # The DEFAULT posture (S-10 amendment 2026-07-16): refuse with the
        # pinned message; a committed config.yaml opt-in is the only door.
        hint = (
            "the hook flow is capture → analyst proposal (compile input + "
            "examples) → human approval of the exact script: teach WITHOUT "
            "--route, then `self-learn route <id> --dest hook`"
            if destination == "hook"
            else "capture first, then `self-learn route <id> --dest "
            "new-skill:<name>` — the name is a route-time human call"
        )
        raise VerbError(
            f"destination {destination!r} cannot be routed in one motion — "
            + hint
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
    old_record: Record | None = None
    if old_id is not None:
        old_path = find_record_path(home, old_id)
        _scan_or_refuse([old_path], None)  # this verb rewrites it too (P2-7)
        old_record = Record.from_path(old_path)

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
        # write (the composed record is still only in memory). One-motion
        # hook (config-enabled) runs the FULL integrity chain here:
        # CLI-generated script, schema validation, whole-input secret
        # scan, and the M3-12 replay — every refusal lands before any
        # write.
        hook_route: _HookRoute | None = None
        if destination == "hook":
            hook_route = _prepare_one_motion_hook(
                home, record, bucket_dir, hook_input
            )
            spec = hook_route.spec
        else:
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

        # --supersedes completion retires a possibly-ROUTED old record:
        # host-side cleanup pre-flights before any write (same as route).
        warnings: list[str] = []
        old_retire: _Retirement | None = None
        if old_record is not None:
            old_retire = _retirement_preflight(
                home,
                old_record,
                old_path.parent.parent,
                warnings,
                user_claude_md=user_claude_md,
                chezmoi_bin=chezmoi_bin,
            )

        suffix = f" (supersedes {old_id})" if old_id else ""
        message_target = (
            f"new-skill:{ref_name}" if destination == "new-skill" else destination
        )
        message = f"self-learn: route {record.id} → {message_target}{suffix}"

        # dict[str, object]: mixes str/dict/list values below (hook is a
        # dict, rules_paths is a list) — a narrower inferred type makes
        # every one of those a pyright error.
        #
        # §2.3: `by` is the caller's `by` keyword (defaulted "human", never
        # a literal here) — `teach --route --dest X` is the human's flag;
        # the bare-analyst `teach --route` path threads its own value in
        # (§6/§7: that call site is teach.py, outside this unit's files).
        routing: dict[str, object] = {
            "routed_at": _now_iso(), "destination": destination, "by": by
        }
        if destination == "reference" and ref_name is not None:
            routing["reference_file"] = ref_name  # BLOCKER 2: name the file
        if destination == "new-skill":
            routing["new_skill"] = ref_name
        if hook_route is not None:
            routing["hook"] = hook_route.meta
        # A2 §4.4B (test obligation §13 item 16): read back off the
        # RESOLVED spec, not `ref_name` — the qualifier is decoded inside
        # _resolve_target, so `spec` is the one place that can never
        # diverge from what was actually written. A bare
        # `--dest claude-md:rules:<topic>` therefore persists its variant
        # even though route_direct never threads rules_paths (P-A5: globs
        # are proposal-only, and route_direct has no proposal to read).
        if spec.variant is not None:
            routing["variant"] = spec.variant
            if spec.rules_topic is not None:
                routing["rules_topic"] = spec.rules_topic
            if spec.rules_paths:
                routing["rules_paths"] = list(spec.rules_paths)
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

        # `route` telemetry (11 §4.3, U-reach §2.2) — same placement pin as
        # `route`'s: immediately after the ledger commit closes above, so a
        # host-phase failure below still leaves this event spooled (the
        # ledger commit IS the routing, doc 13 §4.1). `spool_quiet`: a
        # spool refusal must never break this verb.
        telemetry.spool_quiet(
            "route",
            record=record.id,
            destination=destination,
            scope=record.scope,
            by=by,
            variant=spec.variant,
        )

        # (e) HOST phase. Hook routes log the settings snippet in the host
        # commit body (M3-11), same as the review-gated path.
        host_note = note
        if hook_route is not None:
            snippet_block = f"settings.json snippet:\n{hook_route.snippet}"
            host_note = f"{note}\n\n{snippet_block}" if note else snippet_block
        compile_result, host_sha = _host_phase(
            home,
            spec,
            record.id,
            routed_record=record,
            note=host_note,
            chezmoi_bin=chezmoi_bin,
            message=message,
            warnings=warnings,
            user_push=not no_push,
        )
        if host_sha is not None and spec.host_repo is not None:
            # the applied-canon half of the printed diff (informational —
            # invocation is the approval, never a prompt).
            host_diff = gitops._git(  # noqa: SLF001 — same module family
                spec.host_repo, "show", "--format=", host_sha
            ).stdout
            diff = diff + host_diff
        if hook_route is not None:
            # The user's ruling keeps VISIBILITY without the gate: the
            # applied script bytes lead the printed diff, in full.
            diff = hook_route.script + "\n--- ledger ---\n" + diff

        # (e2) retirement HOST phase for the superseded old record (same
        # shape as route's; skipped when the successor just regenerated
        # the same target).
        old_host_sha = None
        old_host_repo = None
        retire_notes: list[str] = []
        if old_retire is not None:
            old_host_sha, old_host_repo = _retirement_host_phase(
                home,
                old_retire,
                old_id,
                note=note,
                chezmoi_bin=chezmoi_bin,
                message=message,
                warnings=warnings,
                post_notes=retire_notes,
                skip_target=spec.target,
                user_push=not no_push,
            )

        post_notes: list[str] = []
        if hook_route is not None:
            post_notes = _hook_manual_steps(hook_route.snippet, spec.target.name)
        elif destination == "new-skill" and getattr(
            compile_result, "scaffolded", False
        ):
            post_notes = [
                f"new skill scaffolded at plugins/{ref_name} — run "
                "./install.sh to symlink it into ~/.claude/skills "
                "(M3-11); enrich the prose post-hoc whenever you like"
            ]
        post_notes = post_notes + retire_notes

        # (f) push ledger, then push host (both has_remote-guarded).
        push = None if no_push else gitops.push_if_remote(home)
        host_push = None
        if not no_push and host_sha is not None and spec.host_repo is not None:
            host_push = gitops.push_if_remote(spec.host_repo)
        if not no_push and old_host_sha is not None and old_host_repo is not None:
            # possibly the same repo — a second push is a no-op; skipping
            # would strand the retirement commit when the successor's own
            # host commit didn't happen.
            gitops.push_if_remote(old_host_repo)
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
            post_notes=post_notes,
            host_commit_sha=host_sha,
            host_push=host_push,
            target=spec.target,
        )
    finally:
        hold.release()  # (g) release iff owned


# --------------------------------------------------------- U20 commit-drift
#
# F5-5 guided commit-first (ruled 2026-07-19): the dirty-target refusal
# (DirtyTargetError above / chezmoi.ChezmoiAbort's dirty leg) stays fully
# intact — no override, no force, no bypass anywhere in this verb. This is
# the GUIDED path a human takes instead: commit the TARGET repo's OWN
# pending changes first (their commit, separate from ours, pinned subject
# below), then the UI retries the original route once. It serves the
# DIRTY case only — pre-existing chezmoi DRIFT (chezmoi.py:109-111 in the
# module docstring's step numbering) is refused with the re-add/apply
# explanation below; a commit cannot fix drift (gate M2).

#: Pinned commit subject (§2.1) — never a push, never the ledger, never
#: our own compile; the commit is theirs, in their repo, of their changes.
COMMIT_DRIFT_SUBJECT = "chore: commit drift before self-learn route"

#: gate M2: the drift explanation is deliberately NOT ``chezmoi.py``'s own
#: ChezmoiAbort text (which the UI must never match a button onto) — a
#: fresh, plain-words refusal that names the one thing a commit cannot do.
CHEZMOI_DRIFT_REFUSAL = (
    "the dotfiles file differs from what chezmoi manages — run chezmoi "
    "re-add or apply first; a commit can't fix drift"
)

#: The clean-repo refusal (§2.1: "never an empty commit").
NOTHING_TO_COMMIT = "nothing to commit — the target repo is clean"


@dataclass(frozen=True)
class CommitDriftResult:
    """One ``commit_drift`` outcome. ``commit_sha`` is ``None`` only for
    ``dry_run=True`` — nothing was written."""

    repo: Path
    files: list[str]
    commit_sha: str | None
    commit_message: str
    dry_run: bool


def _commit_drift_targets(spec: TargetSpec) -> list[Path]:
    """Every file this verb's dirty check and scoped commit cover — the
    SAME probe set ``_resolve_target``'s own dirty check used (never a
    second definition of it). Two shapes need more than ``spec.target``:

    - ``new-skill`` dirty-checks BOTH ``target`` (the scaffolded
      SKILL.md) AND ``marketplace.json`` (verbs.py's new-skill branch,
      ``for probe in (target, marketplace)``) — the SAME two paths,
      recomputed the same way (``root / ".claude-plugin" /
      "marketplace.json"``), so a marketplace-only dirt (the scaffold's
      appended entry, uncommitted) is coverable, not a dead-end refusal.
    - ``reference``'s ``TargetSpec.target`` is ``None`` for a default
      (created-on-demand) reference — the same
      :func:`compilers.reference_target_path` call ``_resolve_target``
      itself used recomputes it (never a second implementation of that
      mapping)."""
    if spec.destination == "new-skill":
        if spec.target is None or spec.host_repo is None:
            raise VerbError("commit-drift: new-skill target unresolved")
        marketplace = spec.host_repo / ".claude-plugin" / "marketplace.json"
        return [spec.target, marketplace]
    if spec.target is not None:
        return [spec.target]
    if spec.destination == "reference" and spec.refs_dir is not None:
        return [reference_target_path(spec.refs_dir, spec.ref_name)]
    raise VerbError(
        f"commit-drift: {spec.destination!r} has no compile-target file(s) "
        "to commit"
    )


def commit_drift(
    home: Path | str,
    record_id: str,
    *,
    dest: str | None = None,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
    dry_run: bool = False,
) -> CommitDriftResult:
    """``self-learn host commit-drift`` (§2.1): commit the compile
    target's OWN pending changes — the SAME target-resolution a failed
    ``route <record_id> [--dest dest]`` used (:func:`_resolve_target`,
    ``check_dirty=False`` — the E-17 read-only mode; never a second
    resolver), so this verb refuses any path outside a registered host /
    the dotfiles source by construction.

    Two legs (scope per the resolved target):

    - **user scope** (``spec.host_repo is None``): the dotfiles repo,
      commit-target-agnostic — ``chezmoi diff`` distinguishes drift
      (refuse, :data:`CHEZMOI_DRIFT_REFUSAL`) from dirty (commit), and the
      dirty check + the eventual ``add -A`` are BOTH repo-wide (matches
      ``preflight_user_scope``'s own read path — gate m8's mirror image
      for this leg).
    - **host-repo scope** (skill-md / claude-md project·skill-root /
      reference / new-skill): :func:`gitops.paths_dirty` is already
      target-path scoped, so the commit is too — ``git commit --
      <target(s)>`` (never ``add -A``, gate m8: a repo-wide add would
      sweep unrelated pending work into the pinned-subject commit).
      ``new-skill`` is the one COMPOUND target — ``_resolve_target``'s
      own new-skill branch dirty-checks BOTH the scaffolded SKILL.md
      AND ``marketplace.json`` (its ``for probe in (target,
      marketplace)``), so this verb probes and commits the same two
      paths, scoped to exactly whichever of them is actually dirty.

    ``--dry-run`` (§2.1 gate R3) runs every precondition and refusal
    (incl. the drift refusal) and writes nothing — the UI's armed display
    has no other file-list source (gate m6). ``dry_run=True`` skips the
    sentinel self-hold too (08 §1 Sentinel-scoping pin: a read that
    writes nothing has no host autosync window to pause).

    **No secret scan (P2-7) runs here, deliberately.** Every OTHER verb
    scans because it is AUTHORING content this process composes (a
    record body, a `--note`, a compiled managed section) before writing
    it. This verb authors nothing — it commits bytes that ALREADY sit in
    the human's own working tree, written by their own hand outside
    self-learn entirely. The scan gate exists to catch OUR generated
    text; it has no jurisdiction over content we never touched, and
    running it here would be security theater over someone else's file,
    not a guard on anything this process produced. **No push, ever**
    (the commit is theirs, in their repo — publishing it is not this
    verb's call to make), and **no override/force path anywhere** — the
    dirty-target refusal this verb serves stays fully intact everywhere
    else; this is the guided alternative to it, never a bypass of it."""
    home = Path(home)
    path = find_record_path(home, record_id, statuses=("pending",))
    record = Record.from_path(path)
    bucket_dir = path.parent.parent
    resolved_dest = _resolve_destination(bucket_dir, record_id, dest)
    destination = resolved_dest.destination
    if destination == "hook":
        raise VerbError(
            "commit-drift: hook routes carry no dirty-target gate "
            "(_resolve_hook_target never dirty-checks) — nothing to commit"
        )
    # A2 §4.4A: thread the resolved variant/rules_topic/rules_paths
    # through the SAME as `route`'s caller does — commit-drift is the
    # OTHER fresh-route-shaped `_resolve_destination` caller.
    spec = _resolve_target(
        home,
        bucket_dir,
        record.scope,
        destination,
        resolved_dest.ref_name,
        user_claude_md=user_claude_md,
        chezmoi_bin=chezmoi_bin,
        check_dirty=False,
        variant=resolved_dest.variant,
        rules_topic=resolved_dest.rules_topic,
        rules_paths=resolved_dest.rules_paths,
    )

    hold = sentinel.hold() if not dry_run else None
    if hold is not None:
        sentinel.heartbeat()
    try:
        if spec.host_repo is None:
            # user/chezmoi scope: repo-wide dirty check + repo-wide add,
            # mirroring preflight_user_scope's own two-step read path.
            # A2: `spec.target` (not a re-derived `user_claude_md`) so a
            # user-scope RULES target's own drift is checked, not always
            # plain CLAUDE.md — byte-identical to the pre-A2 computation
            # for the variant-absent case.
            assert spec.target is not None  # user scope always resolves one
            target = spec.target
            status = chezmoi.user_scope_dirty_status(target, chezmoi=chezmoi_bin)
            if status.drift:
                raise VerbError(CHEZMOI_DRIFT_REFUSAL)
            if not status.dirty_files:
                raise VerbError(NOTHING_TO_COMMIT)
            repo = chezmoi.dotfiles_source_path(chezmoi=chezmoi_bin)
            if dry_run:
                return CommitDriftResult(
                    repo=repo,
                    files=status.dirty_files,
                    commit_sha=None,
                    commit_message=COMMIT_DRIFT_SUBJECT,
                    dry_run=True,
                )
            sha = chezmoi.commit_all_user_scope(COMMIT_DRIFT_SUBJECT, chezmoi=chezmoi_bin)
            return CommitDriftResult(
                repo=repo,
                files=status.dirty_files,
                commit_sha=sha,
                commit_message=COMMIT_DRIFT_SUBJECT,
                dry_run=False,
            )

        # host-repo scope: target-path-scoped dirty check + scoped
        # commit, under the host's OWN commit lock (mirrors _host_phase:
        # the window between reading dirty state and committing it is
        # exactly what a racing self-learn producer's `pull --rebase
        # --autostash` could stash away mid-flight — doc 13 §4's
        # rebase-autostash race). `targets` may be more than one path
        # (new-skill: SKILL.md + marketplace.json, gate M2-fold-1) — the
        # commit's pathspec is scoped to exactly the DIRTY subset, never
        # the full candidate set (a clean sibling stays untouched).
        targets = _commit_drift_targets(spec)
        with gitops.commit_lock(spec.host_repo):
            dirty_targets = [
                t for t in targets if gitops.paths_dirty(spec.host_repo, t)
            ]
            if not dirty_targets:
                raise VerbError(NOTHING_TO_COMMIT)
            files = [
                f
                for t in dirty_targets
                for f in gitops.dirty_paths(spec.host_repo, t)
            ]
            if dry_run:
                return CommitDriftResult(
                    repo=spec.host_repo,
                    files=files,
                    commit_sha=None,
                    commit_message=COMMIT_DRIFT_SUBJECT,
                    dry_run=True,
                )
            sha = gitops.commit(
                spec.host_repo, COMMIT_DRIFT_SUBJECT, paths=dirty_targets
            )
        return CommitDriftResult(
            repo=spec.host_repo,
            files=files,
            commit_sha=sha,
            commit_message=COMMIT_DRIFT_SUBJECT,
            dry_run=False,
        )
    finally:
        if hold is not None:
            hold.release()


def chezmoi_adopt(
    home: Path | str,
    path: Path | str,
    *,
    chezmoi_bin: str = "chezmoi",
    no_push: bool = False,
) -> chezmoi.AdoptResult:
    """A2 §10.5's ENTRYPOINT — the accepted §10 offer (the "yes"). Thin
    by design (P-A2b′-offer: the offer adds NO new write mechanism): this
    touches ONLY the dotfiles repo, never the ledger, never a host repo —
    there is no ledger/host mutation here for :func:`gitops.commit_lock`
    to serialize against, so this verb takes none (:func:`_ledger_write`
    guards ledger writes; this is not one). ``home`` is accepted, unused,
    for the same reason every other verb takes it — CLI dispatch calls
    every verb the same shape; adoption itself reads and writes no
    ledger state.

    The bare-CLI hint (:func:`_host_phase`) and the UI-interactive
    "yes" both name THIS verb, via the single command string
    :func:`chezmoi.adopt_command` builds — never a second, independently
    typed command."""
    del home  # unused — see docstring
    target = Path(path).expanduser()
    message = f"self-learn: adopt {target.name} into chezmoi"
    return chezmoi.adopt_user_scope(
        target, message=message, chezmoi=chezmoi_bin, push=not no_push
    )


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
            deferred_until=deferred_until,
        )
    finally:
        hold.release()


def _resolve_rehome_target(home: Path, to: str) -> Path:
    """``--to`` accepts a registered project's path or its bucket slug
    (the ``host rebind`` naming precedent — the two things a human can
    say). hosts.yaml is the only authority (H-3); an unregistered target
    refuses with ``host add`` named as the human's repair (02 §2 —
    the verb registers nothing)."""
    try:
        hosts = load_hosts(home)
    except HostsError as exc:
        raise VerbError(str(exc)) from exc
    candidate = Path(to).expanduser()
    for project in hosts.projects:
        registered = Path(project).expanduser()
        if slug_for(registered) == to or registered.resolve() == candidate.resolve():
            return registered.resolve()
    raise VerbError(
        f"target {to!r} is not a registered project — "
        "self-learn host add <path> is the human's repair"
    )


def rehome(
    home: Path | str,
    record_id: str,
    *,
    to: str,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Move a PENDING record to another registered project bucket
    (02 §2 verb pin; 09 §11 Y-18) — the repair for capture-cwd filing a
    lesson under a narrower repo than its real firing range. Ledger-only
    (one commit, pinned subject ``self-learn: rehome lrn-… →
    projects/<slug>``; ``--note`` rides the commit body only — rehome is
    not a resolution, ``resolution_note`` stays untouched). The record's
    bytes are untouched: a deferred record moves and stays deferred.
    Proposal siblings are swept, never moved, plus any source-bucket
    ``merge-*.yaml`` naming the record (:func:`ledger_ops.rehome_record`).

    Refusals — each on STATUS, never mere existence (``find_record_path``
    also sees ``resolved/``), all BEFORE any commit or dir creation:
    unknown id · not pending/deferred · source not a project bucket (M1
    is project→project only) · target not a registered project (the
    refusal names ``host add``) · target == current bucket · id already
    present in the target bucket, ``pending/`` OR ``resolved/`` (the
    create-record collision precedent, F4)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved

    # (a) scan the record file BEFORE trusting its contents — plus the
    # note (F6: the file scan is a no-op in practice since the bytes do
    # not change, but every record-writing verb scans both and
    # uniformity beats the micro-optimization).
    _scan_or_refuse([path], note)

    record = Record.from_path(path)
    if path.parent.name != "pending" or record.status not in (
        "pending",
        "deferred",
    ):
        raise VerbError(
            f"record {record_id} is not pending (status "
            f"{record.status!r}) — a resolved lesson does not move; "
            "supersede is the correction machinery (02 §2)"
        )
    source_bucket = path.parent.parent
    if source_bucket.parent != home / "projects":
        raise VerbError(
            f"record {record_id} lives in a non-project bucket "
            f"({source_bucket.name}) — rehome is project→project only "
            "(M1); user-scope targets and skill/user-scope sources are "
            "dated future work, not silent extensions"
        )

    target_path = _resolve_rehome_target(home, to)
    target_slug = slug_for(target_path)
    target_bucket = home / "projects" / target_slug
    if target_bucket == source_bucket:
        raise VerbError(
            f"record {record_id} already lives in projects/{target_slug} "
            "— nothing to move"
        )
    # Destination collision (F4 — the create_record precedent), checked
    # BEFORE any target-dir/meta.yaml creation: a duplicated id is
    # corruption to surface, never to merge into.
    for sub in ("pending", "resolved"):
        if (target_bucket / sub / f"{record_id}.md").exists():
            raise VerbError(
                f"record {record_id} already exists in {target_bucket} — "
                "a duplicated id is corruption to surface, never to merge "
                "into; inspect both files by hand"
            )

    # (b) sentinel self-hold + heartbeat (standard record-writing verb
    # sequence; rehome is ledger-only — no host phase).
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: rehome {record_id} → projects/{target_slug}"
        with _ledger_write(home):
            touched = rehome_record(home, record_id, target_bucket, target_path)
            staged, sha = _commit_ledger(home, touched, message, note)
        push = _push_ledger(home, no_push)
        return VerbResult(
            action="rehome",
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
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
) -> VerbResult:
    """Graduate a lesson into authored canon: ``superseded_by: canon``
    (02 §2/§4). Works on a routed record (the hand-weave) or a pending
    already-canon one (the bulk-acknowledge door). Commit: ``self-learn:
    graduate lrn-…``. A ROUTED record's host presence is cleaned in the
    same motion — its managed-section entry drops (or its hook script is
    removed, M3-4) via the shared retirement host phase. It used to be
    metadata-only for doc targets ("drops at the next compile"), which
    stranded the line forever when the graduated record was the target's
    LAST — recompile enumerates targets off routed records, so an
    all-retired target was never revisited (found live 2026-07-16)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    warnings = _orphaned_followup_warning(path, record_id)
    record = Record.from_path(path)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        # Pre-flight the host-side cleanup BEFORE the ledger commit
        # (doc-target recompile or M3-4 hook-script removal).
        retire = _retirement_preflight(
            home,
            record,
            path.parent.parent,
            warnings,
            user_claude_md=user_claude_md,
            chezmoi_bin=chezmoi_bin,
        )

        message = f"self-learn: graduate {record_id}"
        with _ledger_write(home):
            touched = resolve_record(
                home, record_id, "superseded", superseded_by="canon", note=note
            )
            staged, sha = _stage_and_commit(home, touched, message, note)

        post_notes: list[str] = []
        host_sha, host_repo = _retirement_host_phase(
            home,
            retire,
            record_id,
            note=note,
            chezmoi_bin=chezmoi_bin,
            message=message,
            warnings=warnings,
            post_notes=post_notes,
            user_push=not no_push,
        )

        push = _push_ledger(home, no_push)
        host_push = None
        if not no_push and host_sha is not None and host_repo is not None:
            host_push = gitops.push_if_remote(host_repo)
        return VerbResult(
            action="graduate",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
            warnings=warnings,
            post_notes=post_notes,
            host_commit_sha=host_sha,
            host_push=host_push,
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
        # (c) PRE-FLIGHT the recompile target when this drops a live entry
        # — or the hook script this retires (M3-4).
        spec: TargetSpec | None = None
        removal: tuple[Path, Path, str] | None = None
        if old_record.status == "routed":
            routing = old_record.routing or {}
            destination = routing.get("destination")
            if destination in ("skill-md", "claude-md", "new-skill"):
                spec = _resolve_target(
                    home,
                    old_path.parent.parent,
                    old_record.scope,
                    destination,
                    routing.get("new_skill") if destination == "new-skill" else None,
                    user_claude_md=user_claude_md,
                    chezmoi_bin=chezmoi_bin,
                    # A2 §4.4B note: variant/rules_topic only — see the
                    # matching comment in _retirement_preflight.
                    variant=routing.get("variant"),
                    rules_topic=routing.get("rules_topic"),
                )
            elif destination == "hook":
                removal = _hook_script_location(home, old_record, warnings)

        # (d) LEDGER phase (locked from the first mutation through the
        # commit — :func:`_ledger_write`).
        message = f"self-learn: supersede {old_id} → {new_id}"
        with _ledger_write(home):
            touched = supersede_record(home, old_id, new_id, note=note)
            staged, sha = _commit_ledger(home, touched, message, note)

        # (e) HOST phase: recompile the target — the entry drops out. For
        # hooks: git rm the script in the host repo (M3-4 rollback pin)
        # and print the un-registration reminder.
        compile_result = None
        host_sha = None
        post_notes: list[str] = []
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
                user_push=not no_push,
            )
        elif removal is not None:
            host_sha = _remove_hook_script(
                home, removal, old_id, note, warnings, post_notes
            )

        # (f) push ledger, then host (both has_remote-guarded).
        push = None if no_push else gitops.push_if_remote(home)
        host_push = None
        host_repo = (
            spec.host_repo if spec is not None
            else removal[0] if removal is not None
            else None
        )
        if not no_push and host_sha is not None and host_repo is not None:
            host_push = gitops.push_if_remote(host_repo)
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
            post_notes=post_notes,
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


def recompile(
    home: Path | str,
    *,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
    chezmoi_bin: str = "chezmoi",
) -> RecompileResult:
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

    # Enumerate targets off ALL resolved records that ever landed in canon
    # (the ledger is the source of truth — targets are derived, never
    # listed anywhere else). RETIRED records (superseded/graduated) still
    # enumerate their DOC target: the regeneration reads only active
    # records, so revisiting is exactly what drops a stale line. Skipping
    # them (the pre-2026-07-17 shape) meant a target whose LAST record
    # retired was never revisited — the stale advisory lived forever.
    specs: dict[tuple[Path | None, Path | None], TargetSpec] = {}
    ref_work: dict[tuple[Path, Path], tuple[TargetSpec, list[Record]]] = {}
    hook_work: list[tuple[Record, Path, Path, str]] = []  # record, host, abs, rel
    hook_removals: list[tuple[Record, tuple[Path, Path, str]]] = []  # m-4
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except RecordError:
                continue
            destination = (record.routing or {}).get("destination")
            if destination not in (
                "skill-md", "claude-md", "reference", "hook", "new-skill"
            ):
                continue
            retired = (
                record.status != "routed" or record.superseded_by is not None
            )
            if destination == "hook":
                meta = (record.routing or {}).get("hook") or {}
                if retired:
                    # m-4: an interrupted (or historically missed) hook
                    # REMOVAL leaves the retired guard on disk — repair by
                    # removing it. No script_path recorded → nothing to do.
                    if not meta.get("script_path"):
                        continue
                    try:
                        removal = _hook_script_location(
                            home, record, result.warnings
                        )
                    except VerbError as exc:
                        result.warnings.append(f"{record.id}: {exc}")
                        continue
                    if removal is not None and removal[1].is_file():
                        hook_removals.append((record, removal))
                    continue
                # H-2 for hooks: re-APPLY the approved bytes from
                # routing.hook (never a regeneration from new inputs —
                # M3-2's verbatim rule holds here too).
                if not meta.get("script") or not meta.get("script_path"):
                    result.warnings.append(
                        f"{record.id}: hook-routed but routing.hook carries "
                        "no script — cannot repair; supersede + re-route"
                    )
                    continue
                try:
                    removal = _hook_script_location(home, record, result.warnings)
                except VerbError as exc:
                    result.warnings.append(f"{record.id}: {exc}")
                    continue
                if removal is not None:
                    host_repo, script_abs, rel = removal
                    hook_work.append((record, host_repo, script_abs, rel))
                continue
            if destination == "reference":
                if retired:
                    # references are append-only history — a retired entry
                    # stays; there is nothing to regenerate or repair.
                    continue
                ref_name = (record.routing or {}).get("reference_file")
            elif destination == "new-skill":
                ref_name = (record.routing or {}).get("new_skill")
            else:
                ref_name = None
            try:
                spec = _resolve_target(
                    home,
                    bucket.path,
                    record.scope,
                    destination,
                    ref_name,
                    user_claude_md=user_claude_md,
                    chezmoi_bin=chezmoi_bin,
                    check_dirty=False,
                    # A2 §4.4B: variant/rules_topic off the STORED routing
                    # block so a rules-routed record's target groups into
                    # its OWN topic file (`specs` below keys on
                    # (host_repo, target) — distinct topics must resolve
                    # to distinct paths, or recompile would merge every
                    # topic's records into one file). rules_paths is
                    # withheld here for the same reason as the retirement
                    # sites (no glob re-assertion outside selfcheck,
                    # §5.2) — moot regardless, since check_dirty=False
                    # already gates the glob check off.
                    variant=(record.routing or {}).get("variant"),
                    rules_topic=(record.routing or {}).get("rules_topic"),
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
            if host_repo is None:
                # The chezmoi-guarded user file (E-17): run the same
                # drift/dirty preflight the route path uses, and skip
                # LOUDLY on any refusal — recompile repairs, it never
                # guesses at a drifted dotfiles state. The apply goes
                # through _host_phase (compile_user_scope commits its own
                # repo; there is no host repo of ours to lock or stage).
                try:
                    preflight_user_scope(target, chezmoi=chezmoi_bin)
                except (ChezmoiAbort, ChezmoiError) as exc:
                    result.entries.append(
                        RecompileEntry(target=target, changed=False, skipped=str(exc))
                    )
                    result.warnings.append(f"{target}: {exc}")
                    continue
                compile_result, _ = _host_phase(
                    home,
                    spec,
                    "recompile",
                    routed_record=None,
                    note=None,
                    chezmoi_bin=chezmoi_bin,
                    message="self-learn: recompile user CLAUDE.md",
                    warnings=result.warnings,
                    user_push=not no_push,
                )
                result.entries.append(
                    RecompileEntry(
                        target=target,
                        # UserScopeResult reports committed, not changed —
                        # the dotfiles repo commits itself, no commit_sha
                        # of ours to show (delta review finding 1)
                        changed=bool(getattr(compile_result, "committed", False)),
                    )
                )
                continue
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

        # Hook scripts: re-apply the APPROVED bytes where missing, edited,
        # or stripped of the executable bit (a hook two-phase interruption
        # is exactly a missing script — H-2's repair must cover it).
        for record, host_repo, script_abs, rel in sorted(
            hook_work, key=lambda item: str(item[2])
        ):
            if script_abs.is_file() and gitops.paths_dirty(host_repo, script_abs):
                result.entries.append(
                    RecompileEntry(target=script_abs, changed=False, skipped="dirty")
                )
                result.warnings.append(
                    f"{script_abs}: uncommitted changes — commit/stash, then re-run"
                )
                continue
            with gitops.commit_lock(host_repo):  # ledger→host order
                apply_result = _write_hook_script(
                    script_abs, (record.routing or {})["hook"]["script"]
                )
                if not apply_result.changed:
                    result.entries.append(
                        RecompileEntry(target=script_abs, changed=False)
                    )
                    continue
                gitops.stage(host_repo, [script_abs])
                sha = gitops.commit(
                    host_repo,
                    f"self-learn: recompile {rel}",
                    paths=[script_abs],
                )
            result.entries.append(
                RecompileEntry(target=script_abs, changed=True, commit_sha=sha)
            )
            if host_repo not in touched_hosts:
                touched_hosts.append(host_repo)

        # m-4: RETIRED hook records whose script still exists — an
        # interrupted removal (or a pre-fix retirement) left the guard on
        # disk. Same removal flow as the verbs; the un-registration
        # reminder lands in warnings so a repair run is never silent.
        for record, removal in sorted(
            hook_removals, key=lambda item: str(item[1][1])
        ):
            host_repo, script_abs, rel = removal
            if gitops.paths_dirty(host_repo, script_abs):
                result.entries.append(
                    RecompileEntry(target=script_abs, changed=False, skipped="dirty")
                )
                result.warnings.append(
                    f"{script_abs}: uncommitted changes — commit/stash, then re-run"
                )
                continue
            removal_notes: list[str] = []
            sha = _remove_hook_script(
                home, removal, record.id, None, result.warnings, removal_notes
            )
            result.warnings.extend(removal_notes)
            result.entries.append(
                RecompileEntry(
                    target=script_abs, changed=sha is not None, commit_sha=sha
                )
            )
            if sha is not None and host_repo not in touched_hosts:
                touched_hosts.append(host_repo)

        if not no_push:
            # Outside every lock (a push touches no index); the rebase
            # fallback takes the HOST's own lock inside push_with_retry.
            for host_repo in touched_hosts:
                gitops.push_if_remote(host_repo)
    finally:
        hold.release()
    return result
