"""Resolution verbs (T7): route / reject / defer / graduate / supersede —
plus the non-resolution filing moves `rehome` (02 §2, added 2026-07-18)
and `rescope` (u-rescope, added 2026-08-23 — the `user <-> skill:<name>`
sibling; `rehome` stays project<->project only).

Function layer only — T8 wires these into the CLI. Public signatures:

    route(home, record_id, *, dest=None, note=None, no_push=False,
          user_claude_md=None) -> VerbResult
    reject(home, record_id, *, note=None, no_push=False) -> VerbResult
    defer(home, record_id, *, until=None, note=None, no_push=False) -> VerbResult
    graduate(home, record_id, *, note=None, no_push=False) -> VerbResult
    supersede(home, old_id, new_id, *, note=None, no_push=False) -> VerbResult
    rehome(home, record_id, *, to, note=None, no_push=False) -> VerbResult
    rescope(home, record_id, *, to, note=None, no_push=False) -> VerbResult
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
    user scope runs the same compile-record predicate every plain host
    uses (§4.5a). All refusals land
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
``user`` → the user-scope canon file (all user-scoped records),
``project`` → that project bucket's records into the registered host's
CLAUDE.md, ``skill:*`` → the skills-root host's own CLAUDE.md (doc 13 §2:
the skills root hosts its own CLAUDE.md canon).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path

from . import config as policy_config
from . import domain, gitops, intents, ledger_ops, sentinel, telemetry
from .primitives import chrono, fsops
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
from . import compiled
from .compilers import (
    BEGIN_MARKER,
    DEFAULT_REFERENCE_BASENAME,
    FORBIDDEN_REFERENCE_BASENAME,
    CompileError,
    PathsResult,
    SectionResult,
    apply_paths_frontmatter,
    apply_pointer,
    compile_managed_file,
    compile_managed_text,
    compile_pointer_text,
    compile_reference,
    has_paths_key,
    pointer_line,
    pointer_token,
    read_paths_frontmatter,
    reference_target_path,
    retire_reference,
    surface_names_target,
)
# REC7: reference/pointer prediction reuses compilers.py's own private
# helpers directly (never reimplemented) so this module's prediction and
# the real write cannot drift apart.
from .compilers import _LEARNINGS_HEADER, _reference_block, _retire_reference_text
from .hosts import (
    HostsError,
    ancestors_of,
    host_marker_path,
    host_mode,
    host_slug,
    is_project_host,
    load_hosts,
    skill_dir_for,
    slug_for,
    validate_host_path,
)
from .ledger import Bucket, discover_buckets, resolve_home
from .ledger_ops import (
    PROPOSAL_DESTINATIONS,
    ROSTER_UNAVAILABLE,
    DEFERRED_ONLY,
    LedgerOpsError,
    LIVE_STATUSES,
    ProposalError,
    QueueEntry,
    REOPENABLE_STATUSES,
    RESOLVABLE_STATUSES,
    ROUTED_ONLY,
    bucket_dir_for_scope,
    bucket_project_path,
    defer_record,
    ensure_project_meta,
    find_record_path,
    glob_reaches,
    globs_may_intersect,
    move_record,
    proposal_info,
    read_proposal,
    reopen_record,
    record_title,
    remove_proposal_siblings,
    reroute_record,
    require_status,
    require_writable_home,
    resolve_record,
    supersede_cycle_check,
    supersede_record,
    validate_merge_proposal,
    validate_proposal,
)
from . import records as records_mod
from .records import RECORD_ID_RE, Record, RecordError, _validate_follow_up
from .scan import format_refusal
from .scan import scan as secret_scan

__all__ = [
    "COMMIT_DRIFT_SUBJECT",
    "DEFAULT_USER_CLAUDE_MD",
    "DISMISS_REASONS",
    "GITOPS_DIRTY_MARKER",
    "NO_PROPOSAL_MARKER",
    "NOTHING_TO_COMMIT",
    "ROUTING_BY_VALUES",
    "SURFACE_FILL_PROBED_DESTINATIONS",
    "CommitDriftResult",
    "DirtyTargetError",
    "NoProposalError",
    "PushReport",
    "RecompileEntry",
    "RecompileResult",
    "RouteDryRunResult",
    "SecretRefusal",
    "TargetSpec",
    "VerbError",
    "VerbResult",
    "VerbUsageError",
    "commit_drift",
    "confirm_held",
    "confirm_recurrence",
    "defer",
    "dismiss_suspect",
    "one_motion_allowed",
    "followup_done",
    "graduate",
    "link_contradicts",
    "managed_target_for",
    "note",
    "push_pending",
    "recompile",
    "rehome",
    "reopen",
    "reroute",
    "rescope",
    "reject",
    "route",
    "route_direct",
    "route_dry_run",
    "show",
    "supersede",
    "surface_fill",
    "undefer",
]

DEFAULT_USER_CLAUDE_MD = Path("~/.claude/CLAUDE.md")

#: U-pointer §3.5: the pointer block's <label> free text, threaded from
#: the caller and keyed by TargetSpec.scope_kind -- compilers.py has no
#: notion of scope, so giving it one to write two words would be the
#: wrong seam (§6-D5).
POINTER_LABELS = {
    "skill": "captured lessons for this skill",
    "project": "captured lessons for this project",
}

#: Destinations the one-motion path (``teach --route`` /
#: :func:`route_direct`) refuses BY DEFAULT: a ``hook`` route applies
#: human-approved executable bytes (M3-2 — a one-motion capture has no
#: proposal to review), and a ``new-skill`` route creates a plugin
#: directory. (Its NAME is the analyst's proposal, validated by the CLI
#: and confirmed by the human — S-21, ratified 2026-07-27; what the
#: default refusal guards here is the scaffold, not the naming.)
#: *S-10 amendment 2026-07-16 (user ruling): the
#: refusal is a DEFAULT, not a hard-code — a committed
#: ``<home>/config.yaml`` ``one_motion_route: {hook: true, …}`` opts a
#: destination in per :func:`one_motion_allowed`; parsing is fail-closed,
#: and the enabled hook path still runs the full integrity chain and
#: prints the applied bytes. settings.json registration stays manual
#: either way — no guard fires without a human edit.*
ONE_MOTION_UNROUTABLE = frozenset({"new-skill", "hook"})

#: 09 §11 Y-20 / 08 §1 `surface_fill` field (renamed by U-cap §6.3 — the
#: word "capped" is false after this unit; there is nothing to cap). The ONLY two
#: destinations a managed-section COMPILE PROBE ever covers. ``reference``
#: is never compile-probed — feeding ``LEARNINGS.md`` to
#: ``compile_managed_text`` would bootstrap a marker pair that does not
#: belong there (08 §1 F1; that prohibition survives verbatim). U-cap adds
#: a `reference` KEY to the payload (§6.3) sourced from
#: `report.reference_read_verdict`, never from a compile probe — no
#: builder may invent a reference compile probe.
SURFACE_FILL_PROBED_DESTINATIONS: tuple[str, ...] = ("skill-md", "claude-md")

#: FW-64: the closed value set for ``routing.by`` — the actor that CHOSE
#: THE DESTINATION. U-reach shipped v1 as an unenumerated two-value
#: convention (``"human"`` | ``"analyst"``); FW-64 found it wrong on
#: every live write site (the review UI always sends ``--dest``, so
#: `route()`'s own dest-is-not-None heuristic read "human" even on an
#: unmodified approve-as-proposed) and added a genuine third chooser:
#: the SDK pane's own `propose_verb` route proposals are neither the
#: deterministic `analyst.analyze()` heuristic nor a human's own
#: decision — a real LLM choosing a destination in a chat turn, distinct
#: from both. Enumerated here (previously nothing validated the value at
#: all) so a future call site cannot silently mistype it. This is a
#: value-set addition inside the EXISTING `route` telemetry kind, never a
#: new `EVENT_KINDS` member — SCHEMA_VERSION's own contract ("extending
#: the CLOSED KIND SET is a version bump", telemetry.py) does not cover
#: it, and 16-ecology-spec.md §10 (FW-65) already warns that constant is
#: double-booked for an unrelated future bump; this change does not
#: touch it.
ROUTING_BY_VALUES = frozenset({"human", "analyst", "agent"})


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


class VerbUsageError(VerbError):
    """A verb refused a MALFORMED invocation before touching any state
    -- sysexits EX_USAGE, distinct from VerbError's normal exit_code=1
    domain refusal (U-verbs S-54 META5): ``reclassify`` with neither
    ``--kind``/``--type``, or an out-of-enum value for either, is a
    usage error, never a business-rule one -- the SAME distinction
    cli.py's own EXIT_USAGE=64 comment draws for argparse's flag
    errors, mirrored here for the one verb whose usage gate lives
    inside the verbs layer (a direct :func:`reclassify` call bypasses
    argparse's own ``choices=`` entirely)."""

    exit_code = 64


class SecretRefusal(VerbError):
    """P2-7: the full-record-file scan hit — nothing written, no bypass."""

    def __init__(self, message: str, hits: list) -> None:
        super().__init__(message)
        self.hits = hits


#: U20 gate R1 (F5-5 guided commit-first): the pinned, stable substring of
#: the gitops-side dirty-target refusal — extracted so the UI's marker
#: match and the tests import the SAME constant this raise site uses
#: (never a hand-copied substring — the dotfiles-sync module that used
#: to carry a twin for the user-scope leg is gone, Phase 2).
GITOPS_DIRTY_MARKER = "has unrelated uncommitted changes"


class DirtyTargetError(VerbError):
    """The compile target has unrelated uncommitted changes."""


#: The stable substring self-learn-ui's action_confirm matches on to
#: rewrite this CLI-voice message into plain words for the human surface
#: (self_learn_ui.routes) — a pinned marker, mirroring GITOPS_DIRTY_MARKER
#: above, so the UI's match and this message can never drift apart
#: silently the way a hand-copied substring could.
NO_PROPOSAL_MARKER = "no proposal for"


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

    def budget_note(self) -> str | None:
        """U-cap §6.2: the post-route budget FACT — never imperative, never
        the token 'WARNING'. `None` when there is no managed-section
        compile result to describe (e.g. `defer`, `reject`, a `reference`
        or `hook` route). Printed to stderr at the same two call sites the
        predecessor of this method used (`cli.py`, `teach.py`)."""
        cr = self.compile_result
        if cr is None:
            return None
        section = getattr(cr, "section", cr)  # UserScopeResult/NewSkillApplyResult wrap one
        entry_count = getattr(section, "entry_count", None)
        word_count = getattr(section, "word_count", None)
        if entry_count is None or word_count is None:
            return None

        from .report import TOKENS_PER_WORD_EST

        dest = self.destination or "target"
        parts = [
            f"budget: {dest} section now holds {entry_count} entries / "
            f"{word_count} words"
        ]
        file_words: int | None = None
        target_str: str | None = None
        target = self.target
        if target is not None:
            try:
                file_words = len(target.read_text(encoding="utf-8").split())
            # NIT N5 (u-cap code gate r1): a whole-file read can fail
            # either way -- an unreadable file (OSError) or one that
            # exists but is not valid UTF-8 (UnicodeDecodeError). T11.3
            # names this the same "degrades to the managed half alone"
            # leg either way; the note must not raise on the second form.
            except (OSError, UnicodeDecodeError):
                file_words = None
            # NIT N4: sec 6.2's own example prints the tilde form
            # (`~/.claude/CLAUDE.md`), never the expanded absolute path
            # (the note is pasted into public issues, same reasoning as
            # the budget row `key` in report.py). Falls back to the
            # absolute path for a project-scope target, which is never
            # under $HOME. Computed inside the SAME `target is not None`
            # guard as `file_words` above (pyright cleanup, code gate
            # r1) -- `target_str` is only ever consulted below when
            # `file_words is not None`, which can only be true when this
            # branch ran.
            try:
                target_str = "~/" + str(target.relative_to(Path.home()))
            except ValueError:
                target_str = str(target)
        if file_words is not None:
            tokens_est = round(file_words * TOKENS_PER_WORD_EST)
            parts.append(f"{target_str} is {file_words} words (~{tokens_est} tokens est)")
            if file_words > 0:
                share = round(100 * word_count / file_words)
                parts.append(f"managed share {share}%")
        else:
            parts.append("surface size unavailable")

        if self.destination == "new-skill":
            scaffolded = bool(getattr(cr, "scaffolded", False))
            desc_words = getattr(cr, "description_words", None)
            if scaffolded and desc_words is not None:
                desc_tokens = round(desc_words * TOKENS_PER_WORD_EST)
                parts.append(
                    f"new-skill scaffolded: +{desc_words} always-on description "
                    f"words (~{desc_tokens} tokens est)"
                )
            else:
                parts.append(
                    "new-skill: +0 always-on words (existing description unchanged)"
                )

        return " · ".join(parts)

    sentinel_owned: bool = False
    diff: str | None = None  # route_direct: staged diff · hook route: the
    #   ENTIRE generated script (08 §8.1 approval flow — never a summary)
    warnings: list[str] = field(default_factory=list)  # callers MUST print
    post_notes: list[str] = field(default_factory=list)  # required manual
    #   steps (M3-11: settings.json snippet, ./install.sh) — callers print
    #   to stdout; the hook is inert by design until the human does them
    # doc 13 §4 two-phase: the HOST half of a canon-touching verb. All None
    # for ledger-only verbs, for a plain host (no host commit exists
    # there — PLAIN3), and after a host-phase failure (drift warning set).
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
    #: U-hostmode PLAIN3: the resolved TargetSpec's mode, when a spec was
    #: resolved (route/route_direct/supersede) — `cli._outcome_state`
    #: reads this to widen the `wrote_uncommitted` branch to every plain
    #: host.
    #: `None` for ledger-only verbs (reject/defer/graduate).
    mode: str | None = None


# ------------------------------------------------------------------ helpers


def _now_iso() -> str:
    return chrono.now_iso()


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


#: U-hostmode REC2's own text: what a refusing region-predicate verdict
#: names, distinct from GITOPS_DIRTY_MARKER (a committed in-marker hand
#: edit is invisible to `git status`, so this refusal must read
#: differently from "uncommitted changes").
REGION_VERDICT_MARKER = "was hand-edited outside self-learn"


def _abort_if_region_unsound(
    home: Path,
    host_path: Path,
    mode: str,
    target: Path,
    region_kind: str,
    *,
    scope_kind: str,
    spec: "TargetSpec | None" = None,
) -> None:
    """U-hostmode §4.5a's six-case predicate, run at PRE-FLIGHT (before
    any ledger mutation), for BOTH modes (REC2/REC4: the record is
    written for git hosts too, and it is the ONLY instrument that sees a
    committed in-marker hand edit — a real hazard on a git host as well,
    which ``gitops.paths_dirty`` cannot see because ``git status`` is
    clean). Refuses on ``edited`` in EITHER mode; ``unknown provenance``
    (no record at all yet) refuses ONLY on a plain host —
    :func:`compiled.refuses` is the mode split, and its own docstring is
    the reasoning: a git host's existing content is provenanced by its
    commit history, and an uncommitted foreign edit is already caught by
    :func:`_abort_if_dirty` (UN2, byte-unchanged). Every other verdict
    (fresh/clean/missing/stale) proceeds silently.

    ``spec`` (M-3, code gate r2 fold — REC5's seventh row): when the
    verdict is ``unknown`` on a ``managed`` target, an ``unknown``
    provenance is not automatically foreign — it is the state of EVERY
    registered host the moment this unit first ships (no compile record
    has ever existed for anything routed before it). Given a ``spec``,
    this compiles what the LEDGER'S CURRENT records (this call's own new
    record not yet among them — pre-flight runs before ``resolve_record``
    marks it routed) would render for this exact target; a byte-for-byte
    match means the on-disk region IS self-learn's own prior output, just
    missing its ledger-side receipt, and is ADOPTED — printed, not
    refused — instead of blocking every existing host's first post-
    upgrade route. Content that does not match is genuinely foreign
    (H-3) and still refuses, exactly as before this fold. Callers that
    omit ``spec`` (or the non-``managed`` region kinds — REC5's row 2 is
    a ``managed``-only compiler comparison; ``reference``/``pointer``/
    ``script`` have no equivalent single-target render to compile
    against) keep the pre-M-3 behaviour byte-unchanged."""
    if not target.is_file():
        return  # nothing to hash yet — "fresh" or "missing", both proceed
    try:
        text = target.read_text(encoding="utf-8")
        region = compiled.region_bytes(text, region_kind)
    except (OSError, UnicodeDecodeError, compiled.CompiledRecordError):
        # let the ordinary compile path raise its own, more specific error
        return
    if region is None:
        return  # region absent on disk — "fresh"/"missing", proceeds
    slug = host_slug(home, host_path, scope_kind=scope_kind)
    entry = compiled.entry_for(compiled.load_record(home, slug), compiled.region_key(host_path, target))
    observed_hash = compiled.sha256_hex(region)
    verdict = compiled.verdict_for(entry, observed_hash)
    if verdict == "unknown" and region_kind == "managed" and spec is not None:
        try:
            expected = _expected_managed_region(home, spec)
        except (OSError, UnicodeDecodeError, compiled.CompiledRecordError, CompileError):
            expected = None
        if expected is not None and region == expected:
            # M-3: adopt — the caller's own normal REC9 resync (in the
            # SAME ledger commit as always) writes the record entry with
            # `based_on_sha256=observed_hash`, exactly the entry a real
            # first `route` was always going to write. Nothing extra to
            # write HERE; this function only decides refuse-vs-proceed.
            print(
                f"self-learn: adopting {target} — self-learn-compiled "
                "content with no compile record yet (first route under "
                "U-hostmode); this route writes the record entry",
                file=sys.stderr,
            )
            return
    if compiled.refuses(verdict, mode):
        raise DirtyTargetError(
            f"compile target {target} {REGION_VERDICT_MARKER} ({verdict}) "
            "— the managed region no longer matches what self-learn last "
            f"wrote; run `self-learn recompile --adopt {target}` to accept "
            "the on-disk region as authoritative, or restore self-learn's "
            "last write"
        )


def _abort_if_unsound(
    home: Path,
    host_path: Path,
    mode: str,
    target: Path,
    region_kind: str,
    *,
    scope_kind: str,
    spec: "TargetSpec | None" = None,
) -> None:
    """The (c) dirty/edited gate, mode-composed: git mode keeps
    :func:`_abort_if_dirty` byte-unchanged (UN2) AND additionally runs
    the region predicate (REC2/REC4); plain mode has ONLY the predicate
    (§4.5a — there is no git status to consult).

    ``spec`` (M-3, code gate r2 fold): threaded straight through to
    :func:`_abort_if_region_unsound` — see its own docstring. ``None``
    (the default) is byte-identical to pre-M-3 behaviour.

    N-9 (code gate r1 fold): master guarded EACH of its three original
    call sites with ``target.is_file()`` before calling
    ``_abort_if_dirty`` — consolidating them into this one function
    dropped that guard, so a not-yet-created target now runs an extra
    ``git status``/``git diff`` per resolve in git mode (harmless, but a
    behaviour delta under a UN group that promises byte-identity).
    Restored here, in the ONE place both legs now live."""
    if mode == "git" and target.is_file():
        _abort_if_dirty(host_path, target)
    _abort_if_region_unsound(
        home, host_path, mode, target, region_kind, scope_kind=scope_kind, spec=spec
    )


def _region_kind_for(spec: TargetSpec) -> str | None:
    """Which of the four compile-record region kinds this spec's
    PRIMARY target is via the ``managed``-only, self-computing
    convenience path (:func:`_write_compile_record_entry`) — ``None``
    when the destination is explicitly OUT of the record's scope
    (``new-skill``, §8 OUT-7: a whole file created once, already
    covered by its own collision rule) OR when the destination's real
    write target resolves OUTSIDE ``spec.target`` entirely
    (``reference`` — see below) or needs externally-supplied bytes this
    function cannot derive on its own (``hook`` — the APPROVED script
    rides the routing block, not the ledger's compile set).

    REC7 (the four region kinds ARE all covered, D-3 completion, code
    gate r1 fold): every verb that writes ANY of the four kinds —
    ``route``, ``route_direct``, ``supersede``, ``graduate``,
    ``recompile`` — resyncs the compile record for it, in the SAME
    ledger commit as whatever ledger-side work that write does. This
    function stays ``managed``-only by DESIGN, not by gap: ``reference``/
    ``pointer``/``script`` are always written through the generic,
    ``spec.target``-independent :func:`_resync_region_entry`, by name,
    at each write site — see ``route``'s block right before its own
    ``_commit_ledger`` call for the canonical shape every other site
    mirrors."""
    if spec.destination in ("skill-md", "claude-md"):
        return "managed"
    return None


def _expected_managed_region(
    home: Path, spec: TargetSpec, *, extra_record: Record | None = None
) -> bytes | None:
    """U-hostmode §4.5/§4.5a: the ``managed`` region THIS write will leave
    behind, computed from the ledger's NOW-UPDATED record set —
    independent of the target's current on-disk bytes (the compiler
    regenerates the whole region from ``_eligible(records)`` alone, per
    ``compilers.compile_managed_text``'s own contract), so an empty
    starting string is exactly as accurate as reading the real file and
    is used here to avoid a second read of a possibly-large file.

    ``extra_record`` (U-verbs §4.3, DRY1/DRY2): `route --dry-run`'s ONE
    hook into this function — an in-memory, AS-IF-ROUTED copy of the
    record being previewed (never written to disk). ``compilers.
    _eligible`` sorts by ``(routing.routed_at, id)``, so appending it
    anywhere in the list is enough; its final position is exactly where
    a real route would place it. Every other caller passes nothing, and
    the byte-identical default keeps the real `route`/`recompile`/
    `supersede` paths untouched (UN1)."""
    records = _compile_set(home, spec)
    if extra_record is not None and extra_record.id not in {r.id for r in records}:
        records = [*records, extra_record]
    text = compile_managed_text("", records).text
    return compiled.region_bytes(text, "managed")


def _write_compile_record_entry(
    home: Path,
    spec: TargetSpec,
    observed_hash: str | None,
    *,
    by: str,
    intent: "intents.Intent | None" = None,
) -> Path | None:
    """U-hostmode REC1/REC9: write (but do not commit) the compile-record
    entry for ``spec``'s primary target, if it is a region kind this
    build tracks (:func:`_region_kind_for`). The caller adds the
    returned path to its OWN ``touched`` list and commits it in the SAME
    ledger commit as the resolution (REC9) — this function never opens a
    lock and never commits anything itself.

    Returns ``None`` (writing nothing) when the destination is untracked
    (``_region_kind_for`` — new-skill) or the target could not be
    resolved into region bytes (defensive: a compile-record failure must
    never break the resolution it is meant to make safer).

    *intent* (gate r1 MAJOR-1, ``None`` for every caller outside a
    collapse route): registered via :func:`intents.add_step` right
    before the write below, at the ONE place this function's compile-
    record path (``home/compiled/<slug>.yaml``) becomes known — a
    collapse's intent cannot cover this path at :func:`intents.begin`
    time, since the slug depends on ``spec``, which is not resolved
    until deep inside ``_execute_route``. A no-op for every other
    caller, since :func:`intents.add_step` itself no-ops on
    ``intent=None``."""
    region_kind = _region_kind_for(spec)
    if region_kind is None or spec.target is None:
        return None
    try:
        if region_kind == "managed":
            expected = _expected_managed_region(home, spec)
        else:
            return None
        if expected is None:
            return None
        key = compiled.region_key(spec.host_path, spec.target)
        slug = host_slug(home, spec.host_path, scope_kind=spec.scope_kind)
        host_label = "(user scope — ~/.claude)" if spec.scope_kind == "user" else str(spec.host_path)
        intents.add_step(intent, compiled.compiled_record_path(home, slug))
        return compiled.write_entry(
            home,
            slug,
            key,
            region=region_kind,
            sha256=compiled.sha256_hex(expected),
            based_on_sha256=observed_hash,
            nbytes=len(expected),
            by=by,
            host=host_label,
            mode=spec.mode,
        )
    except (OSError, UnicodeDecodeError, compiled.CompiledRecordError, CompileError):
        # Defensive only (§4.5's own compile step will raise its own,
        # more specific error at the host phase if the ledger state is
        # genuinely broken) — never let record bookkeeping break a
        # resolution that would otherwise succeed.
        return None


def _observe_region_hash_at(target: Path, region_kind: str) -> str | None:
    """The generic twin of :func:`_observe_region_hash`, decoupled from
    ``TargetSpec`` — REC7's ``reference``/``pointer``/``script`` kinds
    resolve their real target OUTSIDE ``spec.target`` (a reference
    file's path lives at :func:`compilers.reference_target_path`, a
    pointer surface at ``spec.pointer_surface``), so the observer
    cannot be keyed off ``spec.target`` for those. Same contract as the
    ``spec``-keyed version: read BEFORE the caller's first mutation of
    THIS target."""
    if not target.is_file():
        return None
    try:
        region = compiled.region_bytes(target.read_text(encoding="utf-8"), region_kind)
    except (OSError, UnicodeDecodeError, compiled.CompiledRecordError):
        return None
    return compiled.sha256_hex(region) if region is not None else None


def _observe_region_hash(spec: TargetSpec) -> str | None:
    """U-hostmode §4.5a: the region hash OBSERVED ON DISK at pre-flight —
    ``based_on_sha256``. Must be read BEFORE the caller's first ledger
    mutation (REC12/REC13: this is "the state this write is based on",
    never the previous expectation)."""
    region_kind = _region_kind_for(spec)
    if region_kind is None or spec.target is None:
        return None
    return _observe_region_hash_at(spec.target, region_kind)


def _resync_region_entry(
    home: Path,
    *,
    host_path: Path,
    scope_kind: str,
    mode: str,
    target: Path,
    region_kind: str,
    expected: bytes | None,
    observed_hash: str | None,
    by: str,
    delete: bool = False,
    intent: "intents.Intent | None" = None,
) -> Path | None:
    """THE single place, for every verb and every region kind, that
    writes (or clears) a compile-record entry after a region write —
    coordinator ruling (code gate r1 fold, D-3 completion): "the
    compile record is a fact about bytes self-learn wrote, independent
    of both host mode and region kind — and independent of which verb
    wrote them." ``expected`` is the region's bytes as of THIS write,
    supplied by the caller either PREDICTED (route/route_direct, before
    the host write, riding the ledger's own commit — REC9) or OBSERVED
    for real off disk after the write already happened (recompile,
    supersede/graduate's retirement legs, and any hook-script repair —
    D-2/D-3's "standalone resync commit, same subject convention"
    shape). Decoupled from ``TargetSpec`` because REC7's ``reference``/
    ``pointer``/``script`` kinds resolve their real target OUTSIDE
    ``spec.target`` — see :func:`_observe_region_hash_at`.

    ``delete=True`` (code gate r2 fold, D-2) is the ONLY way this
    clears an existing entry (:func:`compiled.delete_entry`) — a
    caller that POSITIVELY knows the region is gone (a hook script just
    removed) passes it explicitly. A stale entry left behind for a
    region that is legitimately gone would misread as ``edited`` the
    next time anything checks this key (REC5's "entry present + region
    absent" row), refusing a future write over content that was never
    a hand edit — ``delete=True`` is what closes that gap.

    ``expected=None`` WITHOUT ``delete=True`` is a true no-op — nothing
    written, nothing cleared. Before this fold, ``expected=None`` alone
    deleted the entry, which conflated two different callers: a
    deliberate removal (the case above) and a predictive leg with
    genuinely nothing to predict yet (:func:`_expected_reference_region`
    /:func:`_expected_pointer_region` returning ``None`` for a NAMED
    reference file that does not exist YET — a first route to it). The
    latter must leave any existing entry untouched, not erase it: D-2's
    own finding was that this path was reachable and untested.

    *intent* (gate r1 MAJOR-1): same shape as
    :func:`_write_compile_record_entry`'s own — registered via
    :func:`intents.add_step` right before whichever real mutation below
    is about to run, never for the two no-op returns above (nothing
    mutates there)."""
    try:
        key = compiled.region_key(host_path, target)
        slug = host_slug(home, host_path, scope_kind=scope_kind)
        step_path = compiled.compiled_record_path(home, slug)
        if delete:
            intents.add_step(intent, step_path)
            return compiled.delete_entry(home, slug, key)
        if expected is None:
            return None
        intents.add_step(intent, step_path)
        host_label = "(user scope — ~/.claude)" if scope_kind == "user" else str(host_path)
        return compiled.write_entry(
            home,
            slug,
            key,
            region=region_kind,
            sha256=compiled.sha256_hex(expected),
            based_on_sha256=observed_hash,
            nbytes=len(expected),
            by=by,
            host=host_label,
            mode=mode,
        )
    except (OSError, UnicodeDecodeError, compiled.CompiledRecordError, CompileError):
        # Defensive only, matching `_write_compile_record_entry` (never
        # let record bookkeeping break a resolution that would
        # otherwise succeed).
        return None


def _expected_reference_region(
    spec: TargetSpec, routed_record: Record, ref_path: Path
) -> bytes | None:
    """REC7: predict :func:`compilers.compile_reference`'s final bytes
    for THIS write, without writing — calls the SAME pure piece
    (``compilers._reference_block``) ``compile_reference`` itself
    calls, over the file's CURRENT (pre-write) text, so prediction and
    the real write independently compute from identical inputs and
    cannot drift. ``routed_record`` must be the record AS RESOLVED (its
    ``routing.routed_at`` already set) — ``_reference_block`` reads
    that field, so predicting from the pre-resolve record would drift
    on the ``day`` heading whenever the wall-clock date has since
    ticked over (a real, if narrow, race the pre-resolve record cannot
    close)."""
    if ref_path.name == FORBIDDEN_REFERENCE_BASENAME:
        return None
    if spec.ref_name is not None:
        if not ref_path.is_file():
            return None
        text = ref_path.read_text(encoding="utf-8")
    else:
        text = ref_path.read_text(encoding="utf-8") if ref_path.is_file() else _LEARNINGS_HEADER
    if routed_record.id in text:
        return text.encode("utf-8")
    block = _reference_block(routed_record)
    new_text = text.rstrip("\n") + "\n\n" + block + "\n"
    return new_text.encode("utf-8")


def _expected_pointer_region(spec: TargetSpec, reference_path: Path) -> bytes | None:
    """REC7: predict :func:`compilers.apply_pointer`'s final bytes for
    the pointer surface without writing — mirrors its own idempotence
    leg (``surface_names_target``) and pure block arithmetic
    (``compile_pointer_text``) exactly, over the surface's CURRENT
    text, then slices out just the pointer region the same way
    :func:`compiled.region_bytes` does for the real write (the pointer
    region is NOT the whole surface file, unlike ``reference``/
    ``script``)."""
    surface = spec.pointer_surface
    if surface is None or not surface.is_file():
        return None  # apply_pointer creates an absent surface; nothing to predict pre-write
    original_text = surface.read_text(encoding="utf-8")
    if surface_names_target(surface, reference_path):
        return compiled.region_bytes(original_text, "pointer")
    token = pointer_token(surface, reference_path)
    line = pointer_line(token, POINTER_LABELS[spec.scope_kind])
    new_text, _bootstrapped = compile_pointer_text(original_text, line)
    return compiled.region_bytes(new_text, "pointer")


def _observe_retirement_region(retire: _Retirement) -> str | None:
    """The retirement-side twin of :func:`_observe_region_hash`, read at
    the SAME pre-mutation point as the retirement preflight itself
    (before ``resolve_record``/``supersede_record`` runs) — ``None`` when
    this retirement has no doc-target spec (a hook removal, or nothing to
    retire)."""
    if retire.spec is None:
        return None
    return _observe_region_hash(retire.spec)


def _write_retirement_compile_record(
    home: Path,
    retire: _Retirement,
    observed_hash: str | None,
    *,
    by: str,
    skip_target: Path | None = None,
    intent: "intents.Intent | None" = None,
) -> Path | None:
    """The retirement-side twin of :func:`_write_compile_record_entry`.

    A retirement's own host phase (:func:`_retirement_host_phase`)
    REWRITES its doc target's managed region (the retiring record's
    entry drops out) — when that target differs from the caller's own
    (``skip_target``), the compile record has no other way to learn the
    file changed, and the NEXT ``check_dirty=True`` resolve against it
    would misread the retirement's own repair as a hand edit it never
    made (found live: ``graduate`` regenerating a shared skill-md file
    left the record pointing at the pre-graduation region, and the very
    next ``supersede`` against that same file refused with ``edited``).
    Skipped, like the host write itself, when the retirement's target IS
    ``skip_target`` — one compile, one record entry, never two racing
    writes for the same key."""
    if retire.spec is None or retire.spec.target is None:
        return None
    if skip_target is not None and retire.spec.target == skip_target:
        return None
    return _write_compile_record_entry(
        home, retire.spec, observed_hash, by=by, intent=intent
    )


def _ledger_write(home: Path):
    """THE ledger critical section: hold :func:`gitops.commit_lock` from a
    verb's first ledger mutation through its commit (audit 2026-07-16
    round 3; see the ``gitops`` module docstring for the probe that fixed
    this scope).

    It must open before the first mutation, not at ``commit()``:
    ``resolve_record`` ``git mv``s (staging a rename instantly) and
    rewrites record files in the worktree, and a racing producer entering
    ``pull --rebase --autostash`` in that window stashes both away — probed
    to leave the record in pending/ AND resolved/ at once, exit 0, `git
    status` clean.

    **U-hostmode §4.5b widens the CLOSE.** It used to close at the ledger
    commit; it now stays open through the compile-record's pre-flight
    OBSERVATION (before ``resolve_record``), the record WRITE (riding
    this same commit, REC9), and — nested with :func:`gitops.host_lock`
    — the HOST write itself, because a concurrent producer's ledger
    commit landing in that window would make ``_compile_set`` re-read a
    record set our own expectation did not account for, and the next
    route would misread the result as a hand edit (§4.5b's defect trace).
    The push still sits OUTSIDE both locks — the reason the whole-verb
    decorator was retired in round 3 (a wedged remote blocking every
    other producer) does not apply to the compile/host-write span, which
    is local file I/O plus one local ``git commit``, no network.

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
    """Stage → pinned commit, INSIDE the caller's :func:`_ledger_write` —
    now the thin `verbs` face of :func:`gitops.stage_and_commit` (audit
    2026-09-02 sprint-1 M-O). The try/except this docstring used to
    describe moved there verbatim; what stays HERE is `_commit_ledger`'s
    own contract — the ``(staged, sha)`` tuple every one of its call
    sites unpacks, which :func:`gitops.stage_and_commit` (pinned to
    return only ``str | None``) does not itself carry.

    Everything this function does is post-mutation by construction — the
    caller has already run ``resolve_record`` (a ``git mv`` + a record
    rewrite) — and by the time control reaches HERE, any earlier
    ``GitOpsError`` from a ledger_ops mutation (e.g. ``_remove_file``) has
    already been caught and converted by THAT call's own caller (see
    ``_remove_file``'s docstring). So a ``GitOpsError`` from
    ``stage``/``commit`` means the ledger is mutated and the commit did
    not land — that is :class:`gitops.HalfWrittenError`, which
    :func:`gitops.stage_and_commit` now raises directly (audit
    2026-07-16 round 7 BLOCKER 2; the gitops docstring already said
    "that is the verb's fact to state, not this module's", and the verb
    used to state the opposite fact unconditionally — the seam function
    inherits that same posture, not a new one).

    Fold r1 MINOR 1: ``staged`` is the same existence-filter
    :func:`gitops.stage` itself applies (``[p for p in touched if
    p.exists()]``) — computed here directly rather than by calling
    ``gitops.stage`` a second time, since :func:`gitops.stage_and_commit`
    below already stages every one of ``touched`` for real. Two ``git
    add`` calls for the same paths were harmless (idempotent) but
    redundant."""
    staged = [p for p in touched if p.exists()]
    sha = gitops.stage_and_commit(home, touched, message, note)
    if sha is None:
        # D-3 (code-gate r2 fold on this lane): an `assert` here is
        # STRIPPED under `python -O` (D-3's own finding, applied
        # verbatim to this guard's Fold r1 version, matching the same
        # fix at verbs.py's own ~:4026 and settings.py's
        # NoConfigRungError) -- an explicit raise stays load-bearing
        # regardless of interpreter flags. Provably unreachable in
        # practice: `allow_empty` defaults False, and `_commit_ledger`
        # never passes `allow_empty=True`, so `gitops.stage_and_commit`
        # cannot return `None` here unless that changes.
        raise VerbError(
            "internal invariant violated: stage_and_commit returned "
            f"None without allow_empty=True (commit {message!r})"
        )
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
    sibling; neither → error.

    U-demand-user §3.2: an explicit ``--dest claude-md:rules:<topic>``
    inherits the proposal sibling's ``rules_paths`` — but ONLY when the
    sibling is schema-valid and names the SAME destination/variant/topic
    (a bare ``claude-md`` never inherits; a different topic never
    inherits). This is the review UI's only entrypoint (every route it
    issues carries an explicit ``--dest``), and closes D2: an explicit
    rules route silently dropping the human-reviewed globs. A missing,
    unparseable, or schema-invalid sibling never raises here — the read
    is guarded, not trusted (A6); it degrades to no inheritance, exactly
    like today's ``--dest`` branch with no sibling at all."""
    if dest is not None:
        destination, qualifier = _parse_dest(dest)
        rules_paths: list[str] | None = None
        if (
            destination == "claude-md"
            and qualifier is not None
            and qualifier.startswith("rules:")
        ):
            topic = qualifier[len("rules:") :]
            sibling_path = bucket_dir / "proposals" / f"{record_id}.yaml"
            if sibling_path.is_file():
                try:
                    sibling = read_proposal(sibling_path)
                    validate_proposal(sibling)
                except ProposalError:
                    sibling = None
                if (
                    sibling is not None
                    and sibling.get("destination") == "claude-md"
                    and sibling.get("variant") == "rules"
                    and sibling.get("rules_topic") == topic
                ):
                    rules_paths = sibling.get("rules_paths")
        return _Destination(destination, qualifier, rules_paths=rules_paths)
    proposal_path = bucket_dir / "proposals" / f"{record_id}.yaml"
    if not proposal_path.is_file():
        raise NoProposalError(
            f"{NO_PROPOSAL_MARKER} {record_id} — pass --dest or run review"
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
    which HOST commits it (or not — U-hostmode), and how to gather the
    compile set.

    U-hostmode §4.1: ``host_repo`` is renamed ``host_path`` and is NEVER
    ``None`` after Phase 1 — user scope became a first-class PLAIN host
    (``~/.claude``, §4.8) rather than the sentinel this field used to
    carry for the old dotfiles-managed user flow. ``mode`` (``"git"`` |
    ``"plain"``)
    is the NEW field that carries the posture; no site may infer one from
    ``host_path`` (MODE9)."""

    destination: str  # skill-md | claude-md | reference | hook | new-skill
    scope_kind: str  # "skill" | "project" | "skill-root" | "user"
    bucket_dir: Path
    target: Path | None  # None for a default (created-on-demand) reference
    host_path: Path
    refs_dir: Path | None = None
    ref_name: str | None = None
    new_skill: str | None = None  # new-skill only: analyst-proposed, CLI-validated, human-confirmed (S-21)
    #: A2 §2.1/§4.3: the claude-md scope parameterization — ``None`` (the
    #: byte-identical P-A6 default), ``"rules"``, or ``"local"``. Only
    #: ever set when ``destination == "claude-md"``.
    variant: str | None = None
    rules_topic: str | None = None  # variant == "rules" only
    rules_paths: tuple[str, ...] | None = None  # variant == "rules" only
    #: A2 §5.1: True iff a zero-match/budget refusal was bypassed via
    #: ``--allow-empty-glob`` (the routing-metadata bypass record, test
    #: obligation §13 item 3). Kept for byte-compatibility with existing
    #: readers; U-glob §6.4's ``glob_bypass_reason`` is what the ledger
    #: actually reasons from.
    glob_bypass: bool = False
    #: U-glob §6.4: WHAT was bypassed — ``"zero-match"`` | ``"budget"`` |
    #: ``None``. Set only when ``glob_bypass`` is True.
    glob_bypass_reason: str | None = None
    #: U-pointer §3.4: the ALWAYS-loaded surface (SKILL.md / CLAUDE.md) a
    #: `reference` route must ALSO write a pointer into -- set only in
    #: `_resolve_target`'s reference branch; ``None`` for every other
    #: destination.
    pointer_surface: Path | None = None
    #: U-xscope §3.1(1): the SAME route-time/test override
    #: :func:`_resolve_target` accepted for a user-scope claude-md target
    #: (plain or ``rules``) -- carried on the spec so :func:`managed_target_for`
    #: can be called with the override that produced THIS spec's target,
    #: never re-derived from ``spec.target`` (a bare-target re-derivation
    #: would desync the moment either side's resolution logic changes).
    #: ``None`` for every non-user-scope spec.
    user_claude_md: Path | str | None = None
    #: U-hostmode §4.1: the ONE field that carries a host's posture.
    #: ``"git"`` (default; byte-identical to pre-unit behaviour) or
    #: ``"plain"``. Always set explicitly by every ``TargetSpec(...)``
    #: construction site via ``hosts.host_mode(home, host_path)`` — the
    #: default here exists only so a stray positional-only construction
    #: fails LOUD elsewhere (a wrong host write) rather than crashing at
    #: import time; MODE9's AST sweep is what actually enforces "every
    #: site threads it".
    mode: str = "git"

    def __post_init__(self) -> None:
        # U-hostmode USER4: host_path is NEVER None after Phase 1 — the
        # root-cause fix for the retired `host_repo is None` overload
        # (§2.5a). A frozen dataclass's __post_init__ may still validate
        # (it just may not reassign a field via plain attribute set).
        if self.host_path is None:
            raise TypeError(
                "TargetSpec.host_path must never be None (U-hostmode "
                "USER4) — user scope now carries a real plain host path"
            )


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
    # `skill_dir_for` above raises HostsError when `hosts.skills_root is
    # None` (same immutable `hosts` object, no reassignment in between)
    # — provably not None here, but pyright cannot see across that
    # function-call boundary; the assert documents the invariant
    # instead of leaving a live false-positive.
    assert hosts.skills_root is not None
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


def _glob_probe_budget_display(home: Path | str | None = None) -> str:
    """U-glob §7.4: the active reachability budget, formatted with
    ``:g`` so ``30.0`` renders ``30`` — resolved through the SAME
    `ledger.glob_probe_budget_s` registry entry
    :func:`ledger_ops._glob_probe_budget_s` itself reads (M-5, review
    2026-09-01), so the refusal text never disagrees with the probe
    that produced it. `home` defaults to :func:`resolve_home`."""
    value = ledger_ops._glob_probe_budget_s(home if home is not None else resolve_home())
    return f"{value:g}"


def managed_target_for(
    home: Path,
    bucket: Bucket,
    record: Record,
    *,
    user_claude_md: Path | str | None = None,
) -> Path | None:
    """U-xscope §3.1: the compiled canon file ONE record's routing
    resolves to — the SAME resolution :func:`_resolve_target` applies at
    route time, re-derived read-only from a resolved record's stored
    ``routing`` block. Single implementation, two callers:
    :func:`self_learn.selfcheck._target_for` delegates here for its
    read-only enumeration, and :func:`_compile_set` calls it per candidate
    record to detect a skill-md/new-skill target collision (below).

    Every live plugin under a registered skills root lays out
    ``plugins/<name>/skills/<name>/`` — so :func:`~self_learn.hosts.
    skill_dir_for`'s glob (the skill-md leg) and the new-skill formula
    ``<skills_root>/plugins/<name>/skills/<name>/SKILL.md`` (the new-skill
    leg) resolve to the SAME file for every one of them. A skill-md route
    and a new-skill route naming that skill therefore compile the SAME
    physical target from two different ``routing.destination`` values —
    comparing this function's output across both is how :func:`_compile_set`
    tells they must union rather than overwrite each other.

    ``user_claude_md`` threads the SAME test/route-time override
    :func:`_resolve_target` accepts for a user-scope claude-md target
    (plain or ``rules``) — never re-derived from anything on ``record`` or
    ``bucket``, which carry no memory of it. Re-deriving the default here
    would return ``~/.claude/CLAUDE.md`` for every override-based caller —
    every sandboxed test, and a real user-scope route — silently emptying
    every
    user-scope compile set (and, read-only, aiming selfcheck's checks at
    the operator's REAL file instead of the sandbox under test).

    Normalizes via ``.resolve()`` exactly once, here, on the return value
    — nothing downstream re-normalizes a value this function already
    returned. A caller comparing against a target NOT produced by this
    function (:func:`_compile_set`'s own ``spec.target``) must resolve it
    the same way at the comparison site.

    ``None`` = unresolvable (unregistered/missing host, or a scope this
    destination never routes) or a destination with no marker-bearing
    file at all (``reference``/``hook``)."""
    destination = (record.routing or {}).get("destination")
    if destination == "skill-md" and bucket.scope == "skill":
        try:
            return (skill_dir_for(load_hosts(home), bucket.name) / "SKILL.md").resolve()
        except HostsError:
            return None
    if destination == "new-skill":
        name = (record.routing or {}).get("new_skill")
        try:
            root = load_hosts(home).skills_root
        except HostsError:
            return None
        if not name or root is None:
            return None
        return (root / "plugins" / name / "skills" / name / "SKILL.md").resolve()
    if destination == "claude-md":
        routing = record.routing or {}
        variant = routing.get("variant")
        if variant == "local":
            host = bucket_project_path(bucket.path)
            return None if host is None else (Path(host) / "CLAUDE.local.md").resolve()
        if variant == "rules":
            topic = routing.get("rules_topic")
            if not topic:
                return None
            if record.scope == "user":
                base = Path(
                    user_claude_md if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD
                ).expanduser()
                return (_user_rules_dir(base) / f"{topic}.md").resolve()
            if record.scope == "project":
                host = bucket_project_path(bucket.path)
                return (
                    None
                    if host is None
                    else (_project_rules_dir(Path(host)) / f"{topic}.md").resolve()
                )
            return None  # skill-scope rules: deferred (§9), never routed
        if record.scope == "user":
            target = Path(
                user_claude_md if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD
            ).expanduser()
            return target.resolve()
        if record.scope == "project":
            host = bucket_project_path(bucket.path)
            return None if host is None else (Path(host) / "CLAUDE.md").resolve()
        root = load_hosts(home).skills_root  # skill-scoped claude-md
        return None if root is None else (root / "CLAUDE.md").resolve()
    return None  # reference/hook: no managed markers


def _user_reachability_roots(home: Path, user_claude_md_target: Path) -> tuple[Path, ...]:
    """U-glob §4.1: the anchored-probe root set for a USER-scope glob —
    ``$HOME`` (derived from the already-overridable user CLAUDE.md
    target's ``.parent.parent``, NEVER ``Path.home()``, so every
    existing test that overrides ``user_claude_md`` also relocates the
    root set with no second override handle invented) plus any
    registered project host or ``skills_root`` that sits OUTSIDE
    ``$HOME`` (M4: the registered hosts alone would refuse the only live
    pathed user rule on this host). De-duplicated, ``$HOME`` first, the
    remainder sorted. ``HostsError`` is not fatal here — it yields just
    ``($HOME,)``, exactly like a missing ``hosts.yaml``."""
    home_root = user_claude_md_target.parent.parent
    try:
        hosts = load_hosts(home)
    except HostsError:
        return (home_root,)
    candidates = list(hosts.projects)
    if hosts.skills_root is not None:
        candidates.append(hosts.skills_root)
    home_resolved = home_root.resolve()
    extra: dict[str, Path] = {}
    for candidate in candidates:
        try:
            candidate_resolved = candidate.resolve()
        except OSError:
            candidate_resolved = candidate
        if candidate_resolved == home_resolved or home_resolved in candidate_resolved.parents:
            continue
        extra.setdefault(str(candidate_resolved), candidate_resolved)
    remainder = sorted(extra.values(), key=str)
    return (home_root, *remainder)


def _validate_rules_globs(
    roots: tuple[Path, ...], patterns: tuple[str, ...], allow_empty_glob: bool
) -> str | None:
    """U-glob §6.2: scope-general per-pattern reachability check — the
    ANCHORED PROBE (:func:`ledger_ops.glob_reaches`) against `roots`,
    never a bare ``glob.glob`` pointed at a root (which does not
    terminate against a ``$HOME``-scale tree, measured M1-M3).

    Returns ``None`` when every pattern reached (``"match"``); when at
    least one pattern did NOT reach and ``allow_empty_glob`` was passed,
    returns the bypass reason — ``"zero-match"`` (more actionable, and
    wins when both kinds are present, §6.2/§7.5) or ``"budget"``.
    Raises :class:`VerbError` naming every dead/undecided pattern
    otherwise (P-A7: a rule-level "did any match?" would pass a partial
    failure — this refuses per pattern, and both failure kinds are
    collected before either raising or bypassing)."""
    dead: list[str] = []
    undecided: list[str] = []
    for pattern in patterns:
        verdict = glob_reaches(roots, pattern)
        if verdict == "none":
            dead.append(pattern)
        elif verdict == "budget":
            undecided.append(pattern)
    if not dead and not undecided:
        return None
    if allow_empty_glob:
        return "zero-match" if dead else "budget"
    roots_str = ", ".join(str(r) for r in roots)
    messages: list[str] = []
    if dead:
        listed = ", ".join(repr(p) for p in dead)
        messages.append(
            f"rules_paths pattern(s) match nothing under {roots_str}: {listed} — "
            "a rule with a non-matching pattern never fires; fix the "
            "pattern(s), or pass --allow-empty-glob to route unverified "
            "(the write-the-rule-before-the-files case)"
        )
    if undecided:
        listed = ", ".join(repr(p) for p in undecided)
        budget = _glob_probe_budget_display()
        messages.append(
            f"rules_paths pattern(s) could not be checked within the "
            f"{budget}s reachability budget under {roots_str}: {listed} — "
            "self-learn refuses rather than route a glob it could not "
            "verify; anchor the pattern with a literal directory segment "
            "(e.g. '**/<dir>/...'), raise SELF_LEARN_GLOB_PROBE_BUDGET_S, "
            "or pass --allow-empty-glob to route unverified"
        )
    raise VerbError(" ... and ".join(messages))


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
    mode = host_mode(home, host)
    # N-4 (code gate r3 fold): ONE `TargetSpec` for both the check_dirty
    # and no-check_dirty legs — r1/r2 built it twice, byte-identically,
    # once inside the `if check_dirty:` branch and once again as the
    # bare fallthrough return; the only difference was whether
    # `_abort_if_unsound` ran on the way out.
    spec = TargetSpec(
        "claude-md", "project", bucket_dir, target, host, variant="local", mode=mode
    )
    if check_dirty:
        # U-hostmode PLAIN9/§4.11: check_ignore is a GIT-tracking privacy
        # guard (P-A3) — a plain host tracks NOTHING, so nothing can be
        # published by being tracked; the hazard cannot occur. Skipped
        # for plain, unchanged (and still refusing) for git.
        if mode == "git" and not gitops.check_ignore(host, target):
            raise VerbError(
                f"{target} is not gitignored in {host} — add "
                "`CLAUDE.local.md` to .gitignore, then re-route (routing "
                "a personal lesson into a tracked file publishes it to "
                "the team)"
            )
        _abort_if_unsound(home, host, mode, target, "managed", scope_kind="project", spec=spec)
    return spec


def _resolve_rules_target(
    home: Path,
    bucket_dir: Path,
    scope: str,
    rules_topic: str | None,
    rules_paths: list[str] | tuple[str, ...] | None,
    *,
    user_claude_md: Path | str | None,
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
    # U-pathed §3.4(1): an absolute or ``~``-leading glob never fires
    # against a project/user tree (canary measurement 1.2) — and it is a
    # live fail-open in shipped code: ``glob.glob(pattern, root_dir=host)``
    # IGNORES ``root_dir`` for an absolute pattern, so
    # ``_validate_rules_globs`` today happily passes (and would emit) a
    # pattern that provably can never match. Shape-only — no filesystem, no
    # ``check_dirty`` gate — so it is deterministic and covers user scope
    # too.
    if paths_tuple:
        _bad_globs = [
            p for p in paths_tuple if p.startswith("~") or Path(p).is_absolute()
        ]
        if _bad_globs:
            _listed = ", ".join(repr(p) for p in _bad_globs)
            raise VerbError(
                f"rules_paths pattern(s) are absolute or home-relative, "
                f"which never fire as a glob against a project/user tree: "
                f"{_listed} — make the pattern(s) relative"
            )
    if scope == "user":
        base = Path(
            user_claude_md if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD
        ).expanduser()
        target = _user_rules_dir(base) / f"{rules_topic}.md"
        bypassed_reason: str | None = None
        if check_dirty and paths_tuple:
            # U-glob §6.3: the glob check comes FIRST — before the
            # plain-host region-predicate refusal below (§4.5a) —
            # because it is the cheaper and more common refusal, and a
            # target with a dead glob should name the dead glob (the
            # thing the human can actually fix), not the pre-flight
            # gate.
            bypassed_reason = _validate_rules_globs(
                _user_reachability_roots(home, base), paths_tuple, allow_empty_glob
            )
        user_host = base.parent
        spec = TargetSpec(
            "claude-md", "user", bucket_dir, target, user_host,
            variant="rules", rules_topic=rules_topic, rules_paths=paths_tuple,
            glob_bypass=bool(bypassed_reason), glob_bypass_reason=bypassed_reason,
            user_claude_md=user_claude_md, mode="plain",
        )
        if check_dirty:
            # U-hostmode §4.8.1: user scope is a first-class PLAIN host —
            # the write goes through the same ordinary plain path every
            # other plain host uses, so the pre-flight gate is the SAME
            # region predicate every plain host gets (§4.5a), not a
            # dotfiles-management "managed" check. USER2/CHEZ0: this
            # route calls no dotfiles-management function at all.
            _abort_if_unsound(
                home, user_host, "plain", target, "managed",
                scope_kind="user", spec=spec,
            )
        return spec
    host = _project_host_or_refuse(home, bucket_dir, project_path)
    target = _project_rules_dir(host) / f"{rules_topic}.md"
    mode = host_mode(home, host)
    bypassed_reason = None
    if check_dirty and paths_tuple:
        bypassed_reason = _validate_rules_globs((host,), paths_tuple, allow_empty_glob)
    spec = TargetSpec(
        "claude-md", "project", bucket_dir, target, host, mode=mode,
        variant="rules", rules_topic=rules_topic, rules_paths=paths_tuple,
        glob_bypass=bool(bypassed_reason), glob_bypass_reason=bypassed_reason,
    )
    if check_dirty:
        _abort_if_unsound(
            home, host, mode, target, "managed", scope_kind="project", spec=spec
        )
    return spec


def _resolve_target(
    home: Path,
    bucket_dir: Path,
    scope: str,
    destination: str,
    ref_name: str | None,
    *,
    user_claude_md: Path | str | None = None,
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
        mode = host_mode(home, root)
        spec = TargetSpec("skill-md", "skill", bucket_dir, target, root, mode=mode)
        if check_dirty:
            _abort_if_unsound(
                home, root, mode, target, "managed", scope_kind="skill", spec=spec
            )
        return spec

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
                project_path=project_path,
                check_dirty=check_dirty,
                allow_empty_glob=allow_empty_glob,
            )
        if scope == "user":
            target = Path(
                user_claude_md if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD
            ).expanduser()
            user_host = target.parent
            spec = TargetSpec(
                "claude-md", "user", bucket_dir, target, user_host,
                user_claude_md=user_claude_md, mode="plain",
            )
            if check_dirty:
                # U-hostmode §4.8.1: user scope is a first-class PLAIN
                # host — the same region predicate every plain host gets
                # (§4.5a), no dotfiles-management call (USER2/CHEZ0).
                _abort_if_unsound(
                    home, user_host, "plain", target, "managed",
                    scope_kind="user", spec=spec,
                )
            return spec
        if scope == "project":
            host = _project_host_or_refuse(home, bucket_dir, project_path)
            target = host / "CLAUDE.md"
            mode = host_mode(home, host)
            spec = TargetSpec("claude-md", "project", bucket_dir, target, host, mode=mode)
            if check_dirty:
                _abort_if_unsound(
                    home, host, mode, target, "managed", scope_kind="project", spec=spec
                )
            return spec
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
        mode = host_mode(home, root)
        spec = TargetSpec("claude-md", "skill-root", bucket_dir, target, root, mode=mode)
        if check_dirty:
            _abort_if_unsound(
                home, root, mode, target, "managed", scope_kind="skill-root", spec=spec
            )
        return spec

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
        new_skill_mode = host_mode(home, root)
        if check_dirty and new_skill_mode == "git":
            # U-hostmode §8 OUT-7: new-skill scaffolds are explicitly NOT
            # covered by the compile record (created once, whole files) —
            # git mode keeps its unchanged paths_dirty gate; plain mode
            # has no record-based gate for this destination.
            for probe in (target, marketplace):
                if probe.is_file():
                    _abort_if_dirty(root, probe)
        return TargetSpec(
            "new-skill", "skill-root", bucket_dir, target, root,
            new_skill=name, mode=new_skill_mode,
        )

    if destination == "reference":
        if scope.startswith("skill:"):
            root, skill_dir = _hosts_skill_dir(home, scope.partition(":")[2])
            host, refs_dir, kind = root, skill_dir / "references", "skill"
            pointer_surface = skill_dir / "SKILL.md"
        elif scope == "project":
            host = _project_host_or_refuse(home, bucket_dir, project_path)
            refs_dir, kind = host / "references", "project"
            pointer_surface = host / "CLAUDE.md"
        else:
            # S-23 (2), §3.1: the dotfiles-management tool this repo used
            # to depend on was retired 2026-07-24 — that ground is dead.
            # The condition below stays byte-identical (the
            # refusal's EFFECT is what S-23 mandates); only the reason
            # changed. Item 3 is deliberately conditional (F6, cross-unit
            # with U-composer's D4): naming a rules topic unconditionally
            # would steer a non-file-scoped lesson to an UNPATHED rules
            # file — ALWAYS-tier cost under a different filename, the
            # silent upgrade D4 forbids.
            raise VerbError(
                "reference destination needs skill:<name> or project "
                "scope — user scope has no references dir. S-23 (2): a "
                "user-level reference file would have no SKILL.md to "
                "hang a pointer off, so it would be unreachable canon, "
                "exactly the failure mode S-23 exists to close. If this "
                "lesson is file-scoped, route it to a pathed rules topic "
                "instead (claude-md:rules:<topic>); if it is not, route "
                "it to project scope, or defer"
            )
        # The compiler owns this mapping — "the one place that mapping
        # lives" (compilers.reference_target_path's docstring). This site
        # re-implemented it with its own "LEARNINGS.md" literal (audit
        # 2026-07-16 MINOR 7): two copies of one rule, free to drift.
        ref_mode = host_mode(home, host)
        probe = reference_target_path(refs_dir, ref_name)
        if check_dirty:
            _abort_if_unsound(home, host, ref_mode, probe, "reference", scope_kind=kind)
        # U-pointer §3.9: three preflight refusals over `pointer_surface`,
        # all gated on `check_dirty` (the same parameter that already
        # gates `_abort_if_dirty` above) — `recompile` calls this with
        # `check_dirty=False` and reaches its own warn-and-skip handling
        # instead (§3.7). Ungating these would make an unregistered/
        # missing SKILL.md `continue` past the ENTIRE ref_work entry at
        # recompile, losing the record appends too (r2 MAJOR 7).
        if check_dirty:
            if kind == "skill" and not pointer_surface.is_file():
                # L2: a skill-scope reference route with no SKILL.md to
                # hang a pointer off would write unreachable canon — the
                # exact defect FW-40 exists to close. Refuse before the
                # ledger commit rather than create it.
                raise VerbError(
                    f"no SKILL.md at {pointer_surface} — self-learn cannot "
                    "write a reference route with nowhere to point a "
                    "pointer at; run `self-learn host rebind` or repair "
                    "the skill first"
                )
            if pointer_surface.is_file():
                # L4: dirty pointer surface — same call already made for
                # `probe` above.
                _abort_if_unsound(home, host, ref_mode, pointer_surface, "pointer", scope_kind=kind)
                # L5: an undecodable pointer surface can't be searched by
                # the reachability predicate either — refuse here rather
                # than committing the ledger and dying in the host phase.
                try:
                    pointer_surface.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise VerbError(
                        f"pointer surface {pointer_surface} is not valid "
                        f"UTF-8 ({exc}) — refusing before the ledger commit"
                    ) from exc
        return TargetSpec(
            "reference", kind, bucket_dir, None, host, refs_dir=refs_dir,
            ref_name=ref_name, pointer_surface=pointer_surface, mode=ref_mode,
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
    scope_kind = _hook_scope_kind(record)
    return TargetSpec("hook", scope_kind, bucket_dir, target, root, mode=host_mode(home, root))


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


#: Genuine RECORD-sourced quote for the one-motion hook trace's t1/t2
#: evidence (`import_backlog.py`'s `_RECORD_QUOTE` sibling pattern — gate
#: FOLD 4 caught the PREVIOUS version of this trace pointing at a
#: fabricated string, "a human supplied --hook-input: this is a hook
#: route by construction", that appears nowhere in any record and would
#: be REFUSED the instant a caller supplied `record_text=`). The record
#: this trace accompanies is composed in memory by `Record.create`
#: (`records.py:203` stamps `status: pending` unconditionally) and is
#: not re-stamped `routed` until `route_direct`'s own
#: `record.set_status("routed")` — well after `_prepare_one_motion_hook`
#: returns (`verbs.py` around the `hook_route = _prepare_one_motion_hook`
#: call, itself before the `set_status` call) — so "status: pending" is
#: always, genuinely contained in `record.to_text()` at the point this
#: trace is built. It carries no reasoning of its own (t1's actual
#: judgment — a human explicitly chose --hook-input, which this pre-
#: flight treats as field-shaped/separable/cost-bearing by construction —
#: lives in the CLI's control flow, not in the record's bytes; there is
#: no genuinely record-sourced quote that would ALSO read as an argument
#: for "yes", so this one is honest about being a placeholder rather than
#: fabricating one that reads as more than it is).
_ONE_MOTION_HOOK_QUOTE = "status: pending"


#: A schema-valid decision trace for the one-motion hook path (S-26:
#: `ledger_ops.TRACE_REQUIRED` made the trace mandatory here too — this
#: call site is a real producer, not a test fixture). `validate_proposal`
#: is currently called (below, in `_prepare_one_motion_hook`) WITHOUT
#: `record_text=`/`scope=`, so today neither containment nor Table-1/
#: Render-1 derivation runs against it in production — but this trace no
#: longer merely ASSUMES it would survive both if a future caller started
#: threading them through:
#: `tests/test_one_motion_config.py::TestOneMotionHookGatesSurviveContainmentAndDerivation`
#: calls `validate_proposal` on this exact skeleton with `record_text=`,
#: `scope=`, and both together, and asserts each is ACCEPTED — closing
#: the gap between the claim and the proof. Concretely: t1's H row
#: (field_shaped/separable/cost_bearing all "yes") points at a genuine
#: record-contained quote (`_ONE_MOTION_HOOK_QUOTE`, never fabricated
#: prose); t2/t3/tn all answer "no" and t4's own legs are "no"/
#: INDETERMINATE, which is `gates.load_class`'s "otherwise" branch —
#: DEMAND — whose Render-1 destination is "reference"; R-HOOK requires
#: the proposal's `alternates` contain that destination, which
#: `_prepare_one_motion_hook` now MERGES in alongside this trace (never
#: silently overwriting a caller-supplied `alternates`, and never
#: silently leaving one short) — that same test class's
#: `test_production_call_site_actually_merges_reference_in` proves the
#: real call site does this, not a hand-mirrored copy.
def _one_motion_hook_gates() -> dict:
    evidence = _ONE_MOTION_HOOK_QUOTE
    return {
        "g0": {
            "reject": {"answer": "no"},
            "defer": {"answer": "no"},
            "canon": {"answer": "no"},
        },
        "t1": {
            "attempted": True,
            "field_shaped": {"answer": "yes", "evidence": evidence},
            "separable": {"answer": "yes", "evidence": evidence},
            "cost_bearing": {"answer": "yes", "evidence": evidence},
        },
        "t2": {"answer": "no", "evidence": evidence, "match_path": None},
        "t3": {
            "answer": "no",
            "owner": None,
            "scan_terms": ["one-motion", "hook-input"],
            "roster_sha": ROSTER_UNAVAILABLE,
        },
        "t3a": None,
        "tn": {"answer": "no", "terms": [], "members": [], "proposed_name": None},
        "t4": {
            "depth_behind_rule": {"answer": "no", "evidence": None},
            "conduct_mode": {"answer": "no", "evidence": None},
            "fs": {"verdict": "INDETERMINATE", "evidence": None},
        },
        "e1": {"sightings": 1, "post_demand_recurrence": False},
        "outcome": "HOOK",
    }


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
    # S-26 (ledger_ops.TRACE_REQUIRED): every proposal now needs a trace —
    # `evidence-gap` names t3's ROSTER_UNAVAILABLE honestly (X3), same
    # posture as the backlog importer's own GRADUATE trace.
    data.setdefault("gates", _one_motion_hook_gates())
    data.setdefault("flags", ["evidence-gap"])
    data.setdefault("recommendation", "route")
    # u-table §3.3 R-HOOK: alternates must name the FALLBACK load class's
    # own Render-1 destination. `_one_motion_hook_gates`'s t2/t3/tn/t4
    # answers all fall through to `gates.load_class`'s final "otherwise"
    # branch — DEMAND — whose destination is "reference"
    # (`ledger_ops._RENDER_DESTINATIONS["DEMAND"]`). MERGED in, never
    # merely defaulted (`setdefault` would leave a caller-supplied list —
    # e.g. `--hook-input`'s own `alternates: [skill-md]` — silently
    # inconsistent with what the trace it ships alongside actually
    # derives): "reference" is a property of the TRACE's own math, not
    # something a human authoring the compile input should have to know
    # to name. Order-preserving, duplicate-free.
    alternates = list(dict.fromkeys(data.get("alternates") or []))
    if "reference" not in alternates:
        alternates.append("reference")
    data["alternates"] = alternates
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
    # `_resolve_hook_target` always constructs its TargetSpec with a
    # real `target` (`hooks_dir / name`) -- `TargetSpec.target` is
    # `Path | None` generically (a default reference route's own
    # created-on-demand case), but this constructor never takes that
    # branch; the assert documents the invariant for this call site
    # instead of leaving a live pyright false-positive.
    assert spec.target is not None
    _replay_hook_examples(data["script"], data["examples"])

    hook = data["hook"]
    rel = spec.target.relative_to(spec.host_path).as_posix()
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
    # `_resolve_hook_target` always constructs its TargetSpec with a
    # real `target` (`hooks_dir / name`) -- `TargetSpec.target` is
    # `Path | None` generically (a default reference route's own
    # created-on-demand case), but this constructor never takes that
    # branch; the assert documents the invariant for this call site
    # instead of leaving a live pyright false-positive.
    assert spec.target is not None
    _replay_hook_examples(script, data["examples"])

    hook = data["hook"]
    rel = spec.target.relative_to(spec.host_path).as_posix()
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


def _hook_scope_kind(record: Record) -> str:
    """The compile-record ``scope_kind`` a hook-routed record's script
    resolves under — same derivation :func:`_resolve_hook_target` has
    always used inline (D-3 completion, code gate r1 fold: pulled out
    here so every OTHER site that needs a hook's ``scope_kind`` for a
    record resync — a removal, a repair — computes it the SAME way,
    never a second, drifting copy of the rule)."""
    return "skill" if record.scope.startswith("skill:") else record.scope


def _write_hook_script(target: Path, script: str) -> HookApplyResult:
    """Write the APPROVED bytes (verbatim — M3-2) + executable bit.
    Idempotent: byte-identical executable content reports unchanged.

    Sprint 2 M-I (D6): the hook-script class — ``fsops.atomic_write``
    with an explicit ``mode=0o755`` (every rwx bit set regardless of
    umask or whatever the PREVIOUS script's mode was), atomic and
    fsync'd, symlinks refused (the default)."""
    current = (
        target.read_text(encoding="utf-8") if target.is_file() else None
    )
    executable = target.is_file() and bool(target.stat().st_mode & 0o100)
    if current == script and executable:
        return HookApplyResult(path=target, changed=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(target, script, mode=0o755)
    return HookApplyResult(path=target, changed=True)


def _hook_script_location(
    home: Path, record: Record, warnings: list[str]
) -> tuple[Path, Path, str, str] | None:
    """PRE-FLIGHT the M3-4 rollback: where the routed record's script
    lives. Returns (host_repo, script_path, rel, mode), or None (with a
    loud warning) when the record carries no script_path."""
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
    return root, root / rel, rel, host_mode(home, root)


def _remove_hook_script(
    home: Path,
    removal: tuple[Path, Path, str, str],
    record_id: str,
    note: str | None,
    warnings: list[str],
    post_notes: list[str],
) -> str | None:
    """M3-4 host phase, mode-branched (U-hostmode PLAIN11): git mode
    ``git rm``s the script (same resolution flow — ledger committed
    first, host commit pinned ``… (hook removed)``); plain mode DEGRADES
    to ``Path.unlink`` — no ``git rm``, no commit (H-j, §2.3). Either way
    prints the un-registration reminder. A failure is loud, never a
    rollback (the ledger stays truth). Takes its OWN host lock (REC12:
    this call site is not lexically inside a caller's ``_ledger_write``
    block by the time it runs)."""
    host_repo, script, rel, mode = removal
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
        with gitops.host_lock(host_repo, mode):
            if mode != "git":
                script.unlink()
                return None
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


def _target_matched_records(
    home: Path,
    target: Path | None,
    destinations: tuple[str, ...],
    *,
    user_claude_md: Path | str | None,
) -> list[Record]:
    """§3.2's C(T): every ROUTED record, across every bucket, whose
    ``managed_target_for`` resolution equals ``target`` — restricted to
    ``destinations`` (a candidate-pruning filter only; MEMBERSHIP itself
    is decided by target equality alone, never by destination or bucket,
    per §3.2 items 1-2). ``user_claude_md`` threads the caller's own
    resolution context into every candidate's resolution (§3.1(1)) — the
    SAME override that produced ``target`` in the first place, so a
    user-scope union built through a sandboxed override sees exactly the
    records that ALSO resolve through that override, never the operator's
    real default."""
    if target is None:
        return []
    records: list[Record] = []
    seen: set[str] = set()
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except RecordError:
                continue  # unparseable resolved file: never a compile input
            if record.id in seen or record.status != "routed":
                continue
            if (record.routing or {}).get("destination") not in destinations:
                continue
            if (
                managed_target_for(home, bucket, record, user_claude_md=user_claude_md)
                != target
            ):
                continue
            seen.add(record.id)
            records.append(record)
    return records


def _compile_set(home: Path, spec: TargetSpec) -> list[Record]:
    """The compile set, read straight off disk (the ledger op commits
    FIRST now — no shadow copies; superseded old records already dropped
    out via the compiler's status filter)."""
    if spec.destination in ("skill-md", "new-skill"):
        # U-xscope: a skill-md route and a new-skill route can name the
        # SAME physical SKILL.md (every live plugin lays out
        # `plugins/<name>/skills/<name>/`, so skill_dir_for's glob and
        # new-skill's `plugins/<name>/skills/<name>/SKILL.md` formula
        # collide byte-for-byte) — filtering the compile set by
        # `spec.destination`/`spec.bucket_dir`/`spec.new_skill` alone (the
        # pre-fix shape) built DISJOINT sets for the two destinations, and
        # `compile_managed_text` regenerates the WHOLE section, so each
        # destination's compile DELETED the other's entries. The compile
        # set here is the UNION of every ROUTED record, across EITHER
        # destination and every bucket, whose `managed_target_for`
        # resolution is THIS spec's target — a single-role skill
        # degenerates to exactly the old per-destination set.
        target = spec.target.resolve() if spec.target is not None else None
        return _target_matched_records(
            home, target, ("skill-md", "new-skill"),
            user_claude_md=spec.user_claude_md,
        )
    if spec.scope_kind == "user":
        # U-xscope MAJOR 5 fold: target-matching here too (not a
        # `_routed_to` scope_pred filter), so `spec.user_claude_md` is
        # genuinely load-bearing on this leg exactly like the union
        # above — B1's blanking route ran through an un-threaded
        # override, and this is the other place one could hide.
        # `variant`/`rules_topic` need no separate filter: each
        # candidate's OWN `managed_target_for` resolution already varies
        # by its own variant/topic, so only records whose target equals
        # THIS spec's target (already variant-specific) ever match —
        # the partition survives for free, per §3.5.
        target = spec.target.resolve() if spec.target is not None else None
        return _target_matched_records(
            home, target, ("claude-md",), user_claude_md=spec.user_claude_md,
        )
    # project / skill-root claude-md: ONE file can serve BOTH roles — a
    # repo registered as project host AND skills root (the shipped
    # claude-skills shape). The compile set must be the UNION of every
    # scope that resolves to this file, or each route of one scope
    # ERASES the other scope's lines and recompile cannot restore them
    # (adversarial review 2026-07-17 finding 3; latent since M1). A
    # single-role host degenerates to exactly the old per-scope set.
    # U-hostmode MODE9/USER4: host_path is NEVER None after Phase 1 — the
    # highest-consequence of the retired 17-site overload (a wrong `None`
    # here silently blanked this UNION, which decides which records
    # compile into this target).
    host = spec.host_path.resolve()
    records: list[Record] = []
    seen: set[str] = set()
    for bucket in discover_buckets(home):
        if bucket.scope != "project":
            continue
        project = bucket_project_path(bucket.path)
        if project is None:
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


def _rules_cofire(rules_dir: Path | None) -> dict[str, object]:
    """U-glob §5.3: the co-firing datum for one resolved rules directory
    — which topic globs COULD match the same file, decided SYMBOLICALLY
    (:func:`ledger_ops.globs_may_intersect`, §5.2), no filesystem access
    beyond reading the topic files' own text. `max_fanin` is an UPPER
    BOUND (pairwise intersection does not compose), not a guarantee some
    single real file matches every counted topic.

    Membership of ``unpathed`` is decided by ``has_paths_key`` returning
    False — the RAW-KEY predicate, never :func:`read_paths_frontmatter`
    (which normalizes ``paths: []`` / ``paths: null`` / a scalar all
    down to the same falsy ``()`` as "no key at all") — so a topic that
    DOES carry a (possibly malformed) ``paths:`` key lands in ``topics``
    with an empty pattern set, never in ``unpathed`` (§5.3)."""
    topics: dict[str, tuple[str, ...]] = {}
    unpathed: list[str] = []
    if rules_dir is not None and rules_dir.is_dir():
        for topic_file in sorted(rules_dir.glob("*.md")):
            try:
                text = topic_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # §6.7: an unreadable/undecodable topic file is skipped
                # — its stem lands in neither list, the same degradation
                # discipline surface_fill already applies elsewhere.
                continue
            stem = topic_file.stem
            if has_paths_key(text):
                topics[stem] = read_paths_frontmatter(text)
            else:
                unpathed.append(stem)
    topic_names = sorted(topics)
    pairs: list[list[str]] = []
    fanin = dict.fromkeys(topic_names, 0)
    for idx, a in enumerate(topic_names):
        for b in topic_names[idx + 1 :]:
            if any(
                globs_may_intersect(p, q) for p in topics[a] for q in topics[b]
            ):
                pairs.append([a, b])
                fanin[a] += 1
                fanin[b] += 1
    if topic_names:
        max_fanin = len(unpathed) + max(1 + fanin[name] for name in topic_names)
    else:
        max_fanin = len(unpathed)
    return {
        "topics": topic_names,
        "unpathed": sorted(unpathed),
        "pairs": pairs,
        "max_fanin": max_fanin,
    }


def surface_fill(
    home: Path,
    bucket_dir: Path,
    scope: str,
    *,
    user_claude_md: Path | str | None = None,
    cache: dict | None = None,
) -> dict[str, dict]:
    """09 §11 Y-20 / 08 §1 `surface_fill` field: a READ-ONLY loaded-surface
    fill probe over the two PROBED managed-section destinations
    (:data:`SURFACE_FILL_PROBED_DESTINATIONS`) — ``reference`` is never
    COMPILE-probed (F1); U-cap §6.3 adds it as a separate read-rate KEY,
    sourced from `report.reference_read_verdict`, never from a compile.

    For each probed destination: resolve the target through the existing
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
    F8). Nothing here is capped, and there is no per-target override
    mechanism (U-cap).

    ``user_claude_md`` overrides the user-scope target the same way
    :func:`route` accepts it (defaults to :data:`DEFAULT_USER_CLAUDE_MD`,
    the real user-scope canon file — the correct real destination to
    report fill for; test callers override it, same idiom as every other
    ``_resolve_target`` call site).

    ``cache`` memoizes one ``(SectionResult, whole_file_word_count)`` pair
    per resolved target path — pass the SAME dict across every record in
    one CLI invocation so records sharing a target (e.g. every record in
    one skill bucket, or every user-scoped record) pay for the compile
    exactly once (08 §1 (e)). The `reference` read-rate verdict (U-cap
    §6.3) is memoized in the SAME dict under the key
    ``("refread", home.resolve())`` — a shape that cannot collide with a
    target path, mirroring the existing ``("cofire", rules_dir.resolve())``
    key — so it too is computed once per CLI invocation."""
    if cache is None:
        cache = {}
    from .report import TOKENS_PER_WORD_EST  # deferred: same-family reuse

    result: dict[str, dict] = {}
    for destination in SURFACE_FILL_PROBED_DESTINATIONS:
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
                section = compile_managed_text(text, _compile_set(home, spec))
                cache[key] = (section, len(text.split()))
        except (VerbError, CompileError, OSError, UnicodeDecodeError):
            continue
        section, file_words = cache[key]
        file_tokens_est = round(file_words * TOKENS_PER_WORD_EST)
        managed_share = (
            round(section.word_count / file_words, 3) if file_words else None
        )
        entry = {
            "entries": section.entry_count,
            "words": section.word_count,
            "load_class": (
                "unconditional" if destination == "claude-md" else "conditional"
            ),
            "file_words": file_words,
            "file_tokens_est": file_tokens_est,
            "managed_share": managed_share,
        }
        if destination == "claude-md":
            # A2 §8/P-A9 + U-glob §5.3/§5.4: `spec` here is the PLAIN
            # (variant=None) claude-md target (this probe never threads
            # a variant), so its rules dir is derived off that target's
            # own parent (§2.1) — a missing directory counts 0 (no
            # builder-side special case needed: a skill-root scope's
            # rules dir never exists, since skill-scope rules are
            # deferred, §9).
            if scope == "user":
                rules_dir = _user_rules_dir(target)
            else:
                # U-hostmode MODE9: host_path is never None — this used
                # to be the `is not None` branch-select; "skill-root"
                # never had one anyway (deferred, §9), so this stays the
                # unconditional project/skill-root leg.
                rules_dir = _project_rules_dir(spec.host_path)
            entry["rules_topic_count"] = (
                len(list(rules_dir.glob("*.md")))
                if rules_dir is not None and rules_dir.is_dir()
                else 0
            )
            # U-glob §6.7: memoized per RESOLVED rules directory in the
            # same cache dict surface_fill already threads, under a key
            # that cannot collide with a target path — otherwise
            # `list --json` recomputes the whole co-firing graph once
            # per record.
            cofire_key = (
                ("cofire", rules_dir.resolve()) if rules_dir is not None else None
            )
            if cofire_key is not None and cofire_key not in cache:
                cache[cofire_key] = _rules_cofire(rules_dir)
            cofire = cache[cofire_key] if cofire_key is not None else _rules_cofire(None)
            entry["rules_cofire"] = cofire
            # U-cap §4.6/§6.1: the escalation is now its own report-only
            # field, never an OR-in onto a cap that no longer exists.
            # NIT N3 (code gate r1): this used to be its OWN constant
            # (`_COFIRE_CROWDED_THRESHOLD`), duplicating report.py's
            # `_COFIRE_MAX_FANIN_ADVISORY` -- same number (5), two names,
            # a drift risk if only one were ever tuned. Deferred import,
            # same-family reuse convention as `reference_read_verdict`
            # a few lines below.
            from .report import _COFIRE_MAX_FANIN_ADVISORY

            entry["cofire_crowded"] = cofire["max_fanin"] > _COFIRE_MAX_FANIN_ADVISORY
        result[destination] = entry

    # U-cap §6.3: the `reference` key — the ONE place this probe widens,
    # and deliberately NOT a compile probe (08 §1 F1 stands verbatim).
    try:
        from .report import reference_read_verdict  # deferred: same-family reuse

        refread_key = ("refread", home.resolve())
        if refread_key not in cache:
            cache[refread_key] = reference_read_verdict(
                home, datetime.now(timezone.utc).date()
            )
        verdict = cache[refread_key]
        result["reference"] = {
            "read_rate_state": verdict["read_rate_state"],
            "safe_overflow": verdict["safe_overflow"],
            "why": verdict["why"],
            "targets_zero_read": verdict["targets_zero_read"],
            "targets_total": verdict["targets_total"],
            # additive (beyond §6.3's minimal field list): the UI's "ok"
            # state phrasing (§6.6) needs the read count; sourced straight
            # from the verdict, never recomputed.
            "reads_30d_total": verdict["reads_30d_total"],
        }
    except Exception:
        # F5 posture, generalized: ANY failure computing the verdict omits
        # the `reference` key entirely — never a zero, never a guess, and
        # never a crash of the whole `list --json` call.
        pass

    return result


@dataclass(frozen=True)
class _Retirement:
    """Pre-flighted host-side cleanup for a ROUTED record being retired
    (standalone supersede, supersede-completion-at-route, graduate, and
    Phase 2's ``reroute``): the doc target whose compiled entry must
    drop, the hook script to remove (M3-4), or the references FILE
    whose ``## <day> — <id>`` block must be removed (U-verbs S-54 /
    §3.5 / §4.5 — reference retirement made real; RER1-RER7). At most
    one of the THREE is set; all None means the record has no host
    presence to clean (pending, or a destination this build does not
    track)."""

    spec: TargetSpec | None = None
    removal: tuple[Path, Path, str, str] | None = None
    #: U-verbs: the resolved references FILE whose ``## <day> — <id>``
    #: block must be removed, plus the spec that resolved it (the host
    #: phase needs ``host_path``/``mode`` for ``gitops.host_lock`` and
    #: the compile record). Set ONLY for ``destination == "reference"``.
    reference: tuple[Path, TargetSpec] | None = None


def _retirement_preflight(
    home: Path,
    record: Record,
    bucket_dir: Path,
    warnings: list[str],
    *,
    user_claude_md: Path | str | None = None,
) -> _Retirement:
    """Resolve a retiring record's host-side cleanup BEFORE any commit
    (doc 13 §4 step c — the standalone supersede verb has always done
    this; route's ``teach --supersedes`` completion, graduate and
    ``reroute`` now share it, closing the stale-line gap found live
    2026-07-16: a cross-surface supersede left the old advisory in
    canon with no repair path). Raises (refusal, nothing committed)
    when the old record's host is unsound.

    U-verbs S-54 (RER6): the ``reference`` branch is the one this build
    used to skip entirely — a bare ``_Retirement()`` for every
    reference-routed record, "references are append-only". They are no
    longer append-only for their own lifetime (§3.5): a
    graduate/supersede/reroute now retires the record's own entry block
    through the SAME shared path every other destination already used,
    never a per-verb branch (the M46 mutation's own wrong shape)."""
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
    if destination == "reference":
        ref_spec = _resolve_target(
            home,
            bucket_dir,
            record.scope,
            "reference",
            routing.get("reference_file"),
            user_claude_md=user_claude_md,
            # Same A2 §4.4B note as the managed branch above:
            # variant/rules_topic only — never rules_paths.
            variant=routing.get("variant"),
            rules_topic=routing.get("rules_topic"),
        )
        # `TargetSpec.target` is None for a reference spec (the file is
        # resolved through `refs_dir`/`ref_name` — see `_resolve_target`'s
        # own reference branch); the retirement's own file identity comes
        # from `reference_target_path`, the ONE mapping the write leg,
        # recompile and the drift check all share (audit 2026-07-16
        # BLOCKER 2, quoted again here so this is not a second lookup).
        # `refs_dir` is `Path | None` generically (TargetSpec's other
        # destinations never set it), but `_resolve_target`'s OWN
        # `destination == "reference"` branch always resolves a concrete
        # dir before returning -- never None here. Same invariant
        # `assert spec.target is not None` documents nearby for the
        # managed branches; this documents the reference one.
        assert ref_spec.refs_dir is not None
        ref_path = reference_target_path(ref_spec.refs_dir, ref_spec.ref_name)
        return _Retirement(reference=(ref_path, ref_spec))
    return _Retirement()


def _predicted_retired_reference_region(ref_path: Path, record_id: str) -> bytes | None:
    """REC7's own discipline, applied to a reference RETIREMENT (RER5/
    RER7's same-commit prediction, mirroring `_expected_reference_region`'s
    write-side contract): predict :func:`compilers.retire_reference`'s
    final bytes for THIS removal, without writing, via the SAME pure
    text transform (:func:`compilers._retire_reference_text`) the real
    removal calls — prediction and the write cannot drift."""
    if not ref_path.is_file():
        return None
    text = ref_path.read_text(encoding="utf-8")
    new_text, _removed = _retire_reference_text(text, record_id)
    return new_text.encode("utf-8")


def _retire_reference_host_phase(
    home: Path,
    reference: tuple[Path, TargetSpec],
    record_id: str,
    *,
    note: str | None,
    warnings: list[str],
) -> str | None:
    """Host phase of a REFERENCE retirement (U-verbs S-54 / RER2):
    removes the record's own entry block from its references file
    (:func:`compilers.retire_reference` — the real write; the ledger
    commit already carried the SAME-commit compile-record prediction,
    same shape the hook-removal leg uses). Self-contained (REC12: takes
    its OWN host lock, like :func:`_remove_hook_script` — this call site
    is not lexically inside the caller's :func:`_ledger_write` block by
    the time it runs). git mode commits (pinned subject `... (reference
    retired)`); plain mode degrades to an uncommitted write, the same
    posture every other plain-host write takes (PLAIN11/H-j)."""
    ref_path, spec = reference
    # `refs_dir` is `Path | None` generically; this function only ever
    # receives a reference-destination `TargetSpec` (the caller's own
    # `_Retirement.reference` leg), so it is never None here -- same
    # invariant as `_retirement_preflight`'s own reference branch.
    assert spec.refs_dir is not None
    try:
        with gitops.host_lock(spec.host_path, spec.mode):
            result = retire_reference(spec.refs_dir, record_id, dest=spec.ref_name)
            if not result.applied or spec.mode != "git":
                return None
            gitops.stage(spec.host_path, [ref_path])
            rel = ref_path.relative_to(spec.host_path)
            return gitops.commit(
                spec.host_path,
                f"self-learn: apply {record_id} → {rel} (reference retired)",
                body=note,
                paths=[ref_path],
            )
    except (gitops.GitOpsError, OSError) as exc:
        warning = (
            f"REFERENCE RETIREMENT FAILED after the ledger commit ({exc}) "
            f"— {ref_path} is stale, never lost (H-2); run `self-learn "
            "recompile` to repair"
        )
        print(f"self-learn: {warning}", file=sys.stderr)
        warnings.append(warning)
        return None


def _retirement_host_phase(
    home: Path,
    retirement: _Retirement,
    record_id: str,
    *,
    note: str | None,
    message: str,
    warnings: list[str],
    post_notes: list[str],
    skip_target: Path | None = None,
    user_push: bool = True,
) -> tuple[str | None, Path | None]:
    """HOST phase of a retirement: recompile the doc target (the entry
    drops — the ledger already committed the resolution), ``git rm`` the
    hook script, or retire the record's entry from its references file
    (U-verbs S-54). ``skip_target`` short-circuits when the successor's
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
            message=message,
            warnings=warnings,
            user_push=user_push,
        )
        return host_sha, retirement.spec.host_path
    if retirement.removal is not None:
        host_sha = _remove_hook_script(
            home, retirement.removal, record_id, note, warnings, post_notes
        )
        return host_sha, retirement.removal[0]
    if retirement.reference is not None:
        host_sha = _retire_reference_host_phase(
            home, retirement.reference, record_id, note=note, warnings=warnings
        )
        return host_sha, retirement.reference[1].host_path
    return None, None


def _pointer_names_base(home: Path, spec: "TargetSpec") -> bool:
    """U-ancestry ANC8: does ``spec``'s pointer surface's host have a
    registered ancestor OR a registered descendant? Project scope only —
    skill scope has no path-ancestry relation to a project host. Read at
    APPLY time (never inside `_resolve_target`, which ANC4 pins
    byte-identical) — this influences only the pointer block's
    surrounding prose, never a write TARGET."""
    if spec.scope_kind != "project" or spec.pointer_surface is None:
        return False
    host = spec.pointer_surface.parent
    try:
        hosts = load_hosts(home)
    except HostsError:
        return False
    if ancestors_of(hosts, host):
        return True
    resolved_prefix = str(host.resolve()) + os.sep
    return any(str(Path(p).resolve()).startswith(resolved_prefix) for p in hosts.projects)


def _apply_target(
    home: Path,
    spec: TargetSpec,
    routed_record: Record | None,
    *,
    message: str | None = None,
    user_push: bool = True,
    notes: list[str] | None = None,
) -> tuple[object, list[Path]]:
    """HOST-phase compile (doc 13 §4 step e): write the target from the
    committed ledger state. Returns (compile_result, host paths to stage —
    empty for a plain host, which commits nothing there).

    U-pathed: for a ``rules`` variant, a ``paths:`` frontmatter pre-pass
    (:func:`compilers.apply_paths_frontmatter`) runs immediately before
    the section compile, over the SAME compile set (`_compile_set` bound
    once per branch — the register is read once, never twice). Its notes
    (absorption / widening / drift-repaired) append to ``notes`` when the
    caller passes a list; its `changed` flag folds into the returned
    result on the project branch only (user scope commits via
    ``UserScopeResult.committed``, which never gates on `changed`)."""
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
        if spec.pointer_surface is not None:
            # U-pointer §3.4/§3.5: the ALWAYS-surface write. `create` is
            # True only at project scope (an absent CLAUDE.md is already
            # created empty by this same posture for claude-md routes,
            # §6-D6); skill scope refuses missing SKILL.md at preflight
            # instead (§3.9 L2), so `apply_pointer` never needs to create
            # one. The pointer's target is `compile_result.path` — the
            # file `compile_reference` ACTUALLY wrote — never a
            # re-derived probe (§3.5).
            pointer = apply_pointer(
                spec.pointer_surface,
                compile_result.path,
                label=POINTER_LABELS[spec.scope_kind],
                create=spec.scope_kind == "project",
                names_base=_pointer_names_base(home, spec),
            )
            if pointer.changed:
                compile_result = replace(compile_result, pointer_changed=True)
                host_paths.append(spec.pointer_surface)
                if notes is not None:
                    notes.append(
                        f"reference pointer written to {spec.pointer_surface}"
                    )
    # U-hostmode §4.8.1: user scope is no longer a special branch here —
    # it is a first-class PLAIN host now, so it falls into the SAME
    # general branch below every other plain/git host uses
    # (`compile_managed_file`, the same as every other plain host —
    # USER2/CHEZ0). `host_paths` still ends up unused for it: `_host_phase`
    # only stages/commits when `spec.mode == "git"`, and user scope's mode
    # is always "plain".
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
        records = _compile_set(home, spec)
        paths_changed = False
        if spec.variant == "rules":
            paths_result = apply_paths_frontmatter(spec.target, records)
            if notes is not None:
                notes.extend(paths_result.notes)
            paths_changed = paths_result.changed
        compile_result = compile_managed_file(spec.target, records)
        if paths_changed and not compile_result.changed:
            # §3.3's "changed fold": the pre-pass wrote the frontmatter
            # but the managed section is byte-identical — without this,
            # the write happens but the caller's `changed is not False`
            # commit-gate never fires, so the repair sits UNCOMMITTED —
            # drift created by the drift repair. SectionResult is frozen;
            # this is one expression, no new field.
            compile_result = replace(compile_result, changed=True)
        # A2 §6/P-A3: a `local` target is GITIGNORED BY DESIGN (the
        # privacy guard already refused the route otherwise) — it must
        # never be staged/committed to the host repo (git itself refuses
        # `git add` on an ignored path, which is the point: the file
        # stays written on disk, outside git, forever). Every other
        # claude-md/skill-md/new-skill target stages as before.
        host_paths = [] if spec.variant == "local" else [spec.target]

    # surface-budget event (11 §4.3: compilers, inside verb flow) — the
    # attention-tax ledger. Spooled here, flushed by the calling verb.
    # U-cap §6.1: the `overflow` payload key is DROPPED — nothing here can
    # overflow any more; `spool_quiet` already omits `None` values, so passing
    # nothing is the whole change. Historical events retain `overflow`;
    # nothing in this unit reads it back.
    telemetry.spool_quiet(
        "surface-budget",
        target=spec.destination,
        words=getattr(compile_result, "word_count", None),
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
    #: U-cap §5.2: the word count of the description JUST minted by THIS
    #: scaffold — `None` on a route into an EXISTING skill (charges 0,
    #: §5.2's dedup rule; the description is never rewritten there).
    description_words: int | None = None

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
            f"no routed records resolve to {spec.target} — nothing to "
            "compile (the union may be empty even though records once "
            f"named new-skill:{spec.new_skill}, if every one retired)"
        )
    name = spec.new_skill
    root = spec.host_path
    target = spec.target
    plugin_dir = root / "plugins" / name
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    marketplace = root / ".claude-plugin" / "marketplace.json"
    # deterministic description: seeded from the FIRST routed lesson.
    # U-xscope §4.3/NIT 13: `records` is NOT sorted here -- `_eligible`
    # (compilers.py) owns the (routed_at, id) order and is applied only
    # inside `compile_managed_file` below; `_compile_set` returns
    # bucket-walk/glob order, so `records[0]` is whichever candidate this
    # target's union happened to enumerate first. Safe regardless: this
    # value is read only when plugin.json/SKILL.md do not yet exist (the
    # guarded block below), and `marketplace_with_entry` no-ops on an
    # existing name (skill_scaffold.py:117-120) -- confirmed by T15.
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
        path=target,
        changed=changed,
        scaffolded=scaffolded,
        section=section,
        # §5.2: charge the always-on budget ONLY on a scaffold (a fresh
        # description was just minted) — 0 on a route into an existing
        # skill, where the description is untouched and only the managed
        # BODY (Class B) grew.
        description_words=len(description.split()) if scaffolded else None,
    )
    # SKILL.md first: the pinned apply subject names host_paths[0].
    return result, [target, manifest, marketplace]


#: Host-phase failure classes: loud drift warning, never a rollback (H-2).
_HOST_PHASE_ERRORS = (
    CompileError,
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
    to ``host_paths``.

    U-hostmode §4.3/§4.5b: the lock is now :func:`gitops.host_lock` — a
    REAL lock in both modes, never a ``nullcontext()`` for a plain host
    (REC12/PLAIN5). Opened HERE as this function's first statement
    (REC12a); when a caller (``route``/``route_direct``/``supersede``/
    ``recompile``) already holds the SAME lock (keyed by the same
    resolved path), this is a re-entrant pass-through
    (``gitops._held_locks``)."""
    try:
        with gitops.host_lock(spec.host_path, spec.mode):
            compile_result, host_paths = _apply_target(
                home,
                spec,
                routed_record,
                message=message,
                user_push=user_push,
                notes=warnings,
            )
            host_sha = None
            if spec.mode == "git" and host_paths:
                changed = getattr(compile_result, "changed", None)
                applied = getattr(compile_result, "applied", None)
                # U-pointer §3.6: a reference route whose append is a
                # no-op (record id already present) but whose pointer was
                # JUST written must still commit — the pointer would
                # otherwise be written-but-uncommitted, the same "changed
                # fold" hazard `verbs.py:1940-1947` already names one
                # destination over. `pointer_changed` is False for every
                # other destination's compile-result type, so this leaves
                # every other gate byte-identical (criterion D2).
                pointer_changed = bool(
                    getattr(compile_result, "pointer_changed", False)
                )
                if pointer_changed or (changed is not False and applied is not False):
                    gitops.stage(spec.host_path, host_paths)
                    rel = host_paths[0].relative_to(spec.host_path)
                    host_sha = gitops.commit(
                        spec.host_path,
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


@dataclass(frozen=True)
class RouteDryRunResult:
    """U-verbs §4.3: the outcome of `route --dry-run` — writes nothing,
    takes no lock, holds no sentinel (`DRY3`). `would_refuse` is a LIST
    (`DRY4`) — every preflight failure found, not just the first."""

    id: str
    destination: str | None = None
    variant: str | None = None
    scope: str | None = None
    host: str | None = None
    mode: str | None = None
    target: str | None = None
    region: str | None = None
    already_present: bool | None = None
    added_lines: int = 0
    removed_lines: int = 0
    unified_diff: str = ""
    managed_share: float | None = None
    budget_flagged: bool = False
    would_refuse: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.would_refuse

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "verb": "route",
            "dry_run": True,
            "destination": self.destination,
            "variant": self.variant,
            "scope": self.scope,
            "host": self.host,
            "mode": self.mode,
            "target": self.target,
            "region": self.region,
            "already_present": self.already_present,
            "diff": {
                "added_lines": self.added_lines,
                "removed_lines": self.removed_lines,
                "unified": self.unified_diff,
            },
            "budget": {
                "managed_share": self.managed_share,
                "flagged": self.budget_flagged,
            },
            "would_refuse": list(self.would_refuse),
        }


def _unified_diff_stats(before: bytes, after: bytes) -> tuple[str, int, int]:
    """A small ``difflib`` unified diff plus its added/removed line
    counts — U-verbs §4.3's ``diff`` envelope. Decodes leniently
    (``errors="replace"``): a preview must never crash on bytes the
    compiler itself would have written cleanly as UTF-8; a genuine
    encoding problem surfaces at the REAL write, not here."""
    import difflib

    before_lines = before.decode("utf-8", errors="replace").splitlines(keepends=True)
    after_lines = after.decode("utf-8", errors="replace").splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(before_lines, after_lines, lineterm="", n=2)
    )
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    return "\n".join(diff), added, removed


def route_dry_run(
    home: Path | str,
    record_id: str,
    *,
    dest: str | None = None,
    by: str | None = None,
    user_claude_md: Path | str | None = None,
    allow_empty_glob: bool = False,
) -> RouteDryRunResult:
    """U-verbs §4.3: runs every preflight the real `route` runs, in the
    SAME order, and computes the bytes the compiler would write instead
    of writing them. Reuses U-hostmode's own `_expected_*_region`
    helpers verbatim (`DRY2`) — nothing here recomputes canon bytes a
    second way. Takes NO lock, holds NO sentinel, mutates nothing
    (`DRY3`) — every record touched is a fresh in-memory copy."""
    home = Path(home)
    path = find_record_path(home, record_id)  # unknown id: bare LedgerOpsError, 64

    # DRY4: every failed preflight is REPORTED, not just the first — so
    # none of the checks below early-return on its own failure. Each is
    # independent of the others' success (the scan reads raw bytes, the
    # status check reads frontmatter, destination/target resolution
    # reads hosts.yaml — none needs a PRIOR check to have passed), so a
    # record that both trips the secret scan and names an unregistered
    # host reports two entries.
    would_refuse: list[str] = []

    try:
        _scan_or_refuse([path], None)
    except VerbError as exc:
        would_refuse.append(str(exc))

    record: Record | None = None
    try:
        _, record = require_status(home, record_id, LIVE_STATUSES, verb="route")
    except LedgerOpsError as exc:
        would_refuse.append(str(exc))
        record = Record.from_path(path)  # still needed below (scope)

    bucket_dir = path.parent.parent
    resolved_dest: _Destination | None = None
    try:
        resolved_dest = _resolve_destination(bucket_dir, record_id, dest)
    except (VerbError, LedgerOpsError, ProposalError) as exc:
        would_refuse.append(str(exc))

    if resolved_dest is None:
        return RouteDryRunResult(
            id=record_id, scope=record.scope, would_refuse=would_refuse
        )
    destination = resolved_dest.destination
    ref_name = resolved_dest.ref_name

    if destination == "hook":
        # A hook route is a one-motion approval flow (M3: the whole
        # generated script IS the preview) — a dry run over the
        # registration gate that guards every OTHER destination has
        # nothing to add here; report the destination and any refusal
        # already collected (the ALWAYS gate still applies to a hook).
        return RouteDryRunResult(
            id=record_id, destination=destination, scope=record.scope,
            would_refuse=would_refuse,
        )

    spec: TargetSpec | None = None
    try:
        spec = _resolve_target(
            home,
            bucket_dir,
            record.scope,
            destination,
            ref_name,
            user_claude_md=user_claude_md,
            variant=resolved_dest.variant,
            rules_topic=resolved_dest.rules_topic,
            rules_paths=resolved_dest.rules_paths,
            allow_empty_glob=allow_empty_glob,
        )
    except VerbError as exc:
        would_refuse.append(str(exc))

    if spec is None:
        return RouteDryRunResult(
            id=record_id, destination=destination, scope=record.scope,
            would_refuse=would_refuse,
        )

    # The AS-IF-ROUTED record the byte prediction is computed from — a
    # fresh in-memory copy; the file on disk is never touched.
    simulated = Record.from_path(path)
    routed_at = _now_iso()
    resolved_by = by if by is not None else ("human" if dest is not None else "analyst")
    routing: dict = {
        "routed_at": routed_at,
        "destination": destination,
        "by": resolved_by,
    }
    if destination == "reference" and ref_name is not None:
        routing["reference_file"] = ref_name
    if resolved_dest.variant is not None:
        routing["variant"] = resolved_dest.variant
    simulated.set_routing(routing)
    simulated.set_status("routed")

    region_kind = _region_kind_for(spec)
    unified, added, removed = "", 0, 0
    already_present: bool | None = None

    if region_kind == "managed":
        current = (
            compiled.region_bytes(
                spec.target.read_text(encoding="utf-8"), "managed"
            )
            if spec.target is not None and spec.target.is_file()
            else None
        ) or b""
        expected = _expected_managed_region(home, spec, extra_record=simulated) or b""
        already_present = current == expected
        unified, added, removed = _unified_diff_stats(current, expected)
    elif destination == "reference":
        ref_path = (
            spec.target
            if spec.target is not None
            else reference_target_path(spec.refs_dir, ref_name)
            if spec.refs_dir is not None
            else None
        )
        if ref_path is not None:
            current = (
                ref_path.read_bytes() if ref_path.is_file() else b""
            )
            expected = _expected_reference_region(spec, simulated, ref_path) or current
            already_present = simulated.id in current.decode("utf-8", errors="replace")
            unified, added, removed = _unified_diff_stats(current, expected)
    # new-skill: scaffolds a directory, not a single region — no diff to
    # preview; destination/target/host are still reported below.

    return RouteDryRunResult(
        id=record_id,
        destination=destination,
        variant=resolved_dest.variant,
        scope=record.scope,
        host=str(spec.host_path),
        mode=spec.mode,
        target=str(spec.target) if spec.target is not None else None,
        region=region_kind,
        already_present=already_present,
        added_lines=added,
        removed_lines=removed,
        unified_diff=unified,
        would_refuse=would_refuse,
    )


def _show_bucket_of(home: Path, path: Path):
    """Reconstruct the :class:`Bucket` a record path lives under, without
    a second `discover_buckets` scan — `show` already has the path."""
    bucket_dir = path.parent.parent
    if bucket_dir == home / "user":
        return Bucket(path=bucket_dir, scope="user", name="user")
    if bucket_dir.parent == home / "skills":
        return Bucket(path=bucket_dir, scope="skill", name=bucket_dir.name)
    return Bucket(path=bucket_dir, scope="project", name=bucket_dir.name)


def _show_canon_info(home: Path, bucket, record: Record) -> dict:
    """`show`'s ``canon`` block (U-verbs §4.3) — resolved READ-ONLY off
    the record's stored ``routing`` block (never invents a target for an
    unrouted record). ``present`` is computed from the TARGET FILE'S
    ACTUAL CONTENT — never from ``routing`` (``SHOW1``'s own
    discriminator: a hand-deleted entry must read ``present: false``
    while ``routing.destination`` stays unchanged)."""
    info: dict = {
        "destination": None,
        "target": None,
        "host": None,
        "mode": None,
        "present": False,
    }
    routing = record.routing
    if routing is None:
        return info
    destination = routing.get("destination")
    info["destination"] = destination
    target: Path | None = None
    host: Path | None = None
    if destination in ("skill-md", "claude-md", "new-skill"):
        target = managed_target_for(home, bucket, record)
        try:
            if bucket.scope == "skill":
                root = load_hosts(home).skills_root
                host = Path(root) if root is not None else None
            elif record.scope == "project":
                h = bucket_project_path(bucket.path)
                host = Path(h) if h is not None else None
            else:
                host = DEFAULT_USER_CLAUDE_MD.expanduser().parent
        except HostsError:
            host = None
    elif destination == "reference":
        try:
            if bucket.scope == "skill":
                refs = skill_dir_for(load_hosts(home), bucket.name) / "references"
                root = load_hosts(home).skills_root
                host = Path(root) if root is not None else None
            elif record.scope == "project":
                h = bucket_project_path(bucket.path)
                refs = Path(h) / "references" if h is not None else None
                host = Path(h) if h is not None else None
            else:
                refs = None
        except HostsError:
            refs = None
        if refs is not None:
            target = reference_target_path(refs, routing.get("reference_file"))
    elif destination == "hook":
        hook_meta = routing.get("hook") or {}
        rel = hook_meta.get("path")
        if rel is not None and record.scope == "project":
            h = bucket_project_path(bucket.path)
            if h is not None:
                host = Path(h)
                target = Path(h) / rel
    if host is not None:
        info["host"] = str(host)
        try:
            info["mode"] = host_mode(home, host)
        except Exception:  # noqa: BLE001 — a resolution problem here must
            info["mode"] = None  # never break a read-only detail view
    if target is not None:
        info["target"] = str(target)
        if target.is_file():
            try:
                text = target.read_text(encoding="utf-8")
                info["present"] = record.id in text
            except (OSError, UnicodeDecodeError):
                info["present"] = False
    return info


def _show_lifecycle(home: Path, record_id: str) -> list[dict]:
    """The record's commit history — ``git -C <home> log --grep=<id>
    --oneline``, newest-first as git itself orders it. M-G: a LOCAL,
    read-only git call — bounded the same as every other one
    (``gitops.GIT_LOCAL_TIMEOUT``) via the shared primitive rather than a
    bare, unbounded ``subprocess.run``. A wedged git here is a detail-view
    surface, not a mutation: it degrades to an empty history rather than
    raising and taking the whole ``show`` verb down with it."""
    from .primitives import procs

    try:
        proc = procs.run_bounded(
            [
                "git", "-C", str(home), "log",
                f"--grep={record_id}", "--fixed-strings",
                "--pretty=format:%H%x09%ad%x09%s", "--date=short",
            ],
            timeout=gitops.GIT_LOCAL_TIMEOUT,
        )
    except procs.BoundedTimeout:
        return []
    out: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, date_str, subject = parts
        out.append({"sha": sha[:7], "date": date_str, "subject": subject})
    return out


def show(home: Path | str, record_id: str) -> dict:
    """Read-only record detail (U-verbs §4.3). Mutates nothing, takes no
    lock, holds no sentinel — every field is a read. ``canon.present`` is
    computed from the target file's ACTUAL content, never from
    ``routing`` (``SHOW1``)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    record = Record.from_path(path)
    bucket = _show_bucket_of(home, path)
    bucket_label = (
        "user" if bucket.scope == "user"
        else f"skills/{bucket.name}" if bucket.scope == "skill"
        else f"projects/{bucket.name}"
    )
    entry = QueueEntry(path=path, record=record)
    prop = proposal_info(entry)
    routing = record.routing
    return {
        "id": record.id,
        "status": record.status,
        "scope": record.scope,
        "kind": record.kind,
        "type": record.type,
        "bucket": bucket_label,
        "created_at": record.created_at,
        "sightings": record.sightings,
        "deferred_until": record.deferred_until,
        "deferred_count": record.deferred_count,
        "superseded_by": record.superseded_by,
        "resolution_note": record.resolution_note,
        "routing": (
            {
                "destination": routing.get("destination"),
                "routed_at": routing.get("routed_at"),
                "by": routing.get("by"),
                "variant": routing.get("variant"),
                "follow_up": routing.get("follow_up"),
            }
            if routing is not None
            else None
        ),
        "canon": _show_canon_info(home, bucket, record),
        "proposal": {
            "present": prop["has_proposal"],
            "fresh": prop["proposal_fresh"] if prop["has_proposal"] else None,
            "destination": prop["destination"],
            "already_canon": prop["already_canon"] if prop["has_proposal"] else None,
        },
        "recurrences": list(record.recurrences),
        "dismissed_suspects": list(record.dismissed_suspects),
        "last_confirmed": record.last_confirmed,
        "history": list(record.history),
        "notes": list(record.notes),
        "lifecycle": _show_lifecycle(home, record_id),
    }


@dataclass(frozen=True)
class _CollapseCtx:
    """Collapse's raw materials, resolved by :func:`_load_cluster` (disk-
    shape-specific — reads ``bucket_dir/proposals/<cluster_id>.yaml`` and
    every member's pending file — so it stays in the ``route`` adapter,
    never in :func:`_execute_route`). The core owns the MUTATIONS
    (M-W: collapse's transaction intent is recorded here); this struct is
    just the plumbing between them. ``route_direct`` has no cluster to
    read (no proposal, no pending siblings) and never constructs one —
    the core's ``collapse=None`` path is what ``route_direct`` always
    takes."""

    cluster_id: str
    pending_path: Path  # survivor's ON-DISK pending file (merge target)
    merge_path: Path  # the merge proposal, removed after a clean route
    losers: list[str]


def _complete_old_retirement(
    home: Path,
    spec: TargetSpec,
    old_retire: "_Retirement | None",
    old_id: str | None,
    old_record: Record | None,
    old_observed_hash: str | None,
    *,
    verb_label: str,
    record_id: str,
    intent: "intents.Intent | None" = None,
) -> list[Path]:
    """D-3 completion (code gate r1 fold, coordinator ruling 2026-08-28):
    a `teach --supersedes` completion's host-side cleanup is functionally
    the same retirement `supersede()` does standalone. Was a near-verbatim
    duplicate between `route` (verbs.py 4033-4085) and `route_direct`
    (4489-4539) before this move (census §2) — one copy now, called from
    inside :func:`_execute_route`'s lock for either adapter.

    Returns the touched-path addendum (a compile-record entry, or a hook
    script removal record) — empty when there is nothing to retire, or
    the successor's own compile already regenerated the same target
    (``_write_retirement_compile_record`` returning ``None`` for a reason
    OTHER than "no removal needed" is handled by its own return contract:
    see its docstring)."""
    if old_retire is None:
        return []
    touched: list[Path] = []
    old_record_path = _write_retirement_compile_record(
        home,
        old_retire,
        old_observed_hash,
        by=f"{verb_label} {record_id} (supersedes {old_id})",
        skip_target=spec.target,
        intent=intent,
    )
    if old_record_path is not None:
        touched.append(old_record_path)
    elif old_retire.removal is not None:
        if old_record is None:
            # D-3 (code gate r2 fold): an `assert` here is STRIPPED under
            # `python -O` — an explicit raise stays load-bearing
            # regardless of interpreter flags. Provably unreachable in
            # practice: `old_retire` is only ever set when `old_record is
            # not None` (M-R: `_execute_route`'s old-id preflight gates
            # this the same way for both adapters before calling this
            # helper) — pyright just cannot connect the two names'
            # narrowing across the call boundary on its own.
            raise VerbError(
                "internal invariant violated: old_retire is set but "
                f"old_record is None ({verb_label} {record_id} "
                f"supersedes {old_id})"
            )
        old_host_repo, old_script_abs, _old_rel, old_removal_mode = old_retire.removal
        old_removal_record_path = _resync_region_entry(
            home,
            host_path=old_host_repo,
            scope_kind=_hook_scope_kind(old_record),
            mode=old_removal_mode,
            target=old_script_abs,
            region_kind="script",
            expected=None,
            observed_hash=None,
            delete=True,
            by=f"{verb_label} {record_id} (supersedes {old_id})",
            intent=intent,
        )
        if old_removal_record_path is not None:
            touched.append(old_removal_record_path)
    return touched


def _resync_three_regions(
    home: Path,
    spec: TargetSpec,
    record_id: str,
    *,
    hook_route: "_HookRoute | None",
    routed_record: Record,
    verb_label: str,
    intent: "intents.Intent | None" = None,
) -> list[Path]:
    """REC7: the compile record covers the two region kinds
    ``_write_compile_record_entry`` never resolves — ``reference`` (which
    also writes a ``pointer``) and ``script`` (hook) — by name, rather
    than through that generic managed-region dispatch. Was a near-
    verbatim duplicate between `route` (verbs.py 4096-4159) and
    `route_direct` (4550-4607) before this move (census §2).

    ``routed_record`` is the record AS IT LOOKS after the first write —
    for the git-mv adapter this is a fresh ``Record.from_path`` re-read
    (the pre-lock ``record`` object's ``routing`` is stale, mutated only
    on disk by ``resolve_record``); for the direct-write adapter it is
    the SAME in-memory object the caller already mutated
    (``set_routing``/``set_status``) before the write. Passing the wrong
    one silently reads a stale/absent ``routing`` block for the
    ``reference`` region's expected-bytes computation — callers build
    this value explicitly, right after the first-write dispatch, rather
    than the core guessing which shape it is."""
    touched: list[Path] = []
    if spec.destination == "reference" and spec.refs_dir is not None:
        ref_path = reference_target_path(spec.refs_dir, spec.ref_name)
        if ref_path.name != FORBIDDEN_REFERENCE_BASENAME:
            ref_observed = _observe_region_hash_at(ref_path, "reference")
            ref_expected = _expected_reference_region(spec, routed_record, ref_path)
            ref_record_path = _resync_region_entry(
                home,
                host_path=spec.host_path,
                scope_kind=spec.scope_kind,
                mode=spec.mode,
                target=ref_path,
                region_kind="reference",
                expected=ref_expected,
                observed_hash=ref_observed,
                by=f"{verb_label} {record_id}",
                intent=intent,
            )
            if ref_record_path is not None:
                touched.append(ref_record_path)
            if spec.pointer_surface is not None:
                ptr_observed = _observe_region_hash_at(spec.pointer_surface, "pointer")
                ptr_expected = _expected_pointer_region(spec, ref_path)
                ptr_record_path = _resync_region_entry(
                    home,
                    host_path=spec.host_path,
                    scope_kind=spec.scope_kind,
                    mode=spec.mode,
                    target=spec.pointer_surface,
                    region_kind="pointer",
                    expected=ptr_expected,
                    observed_hash=ptr_observed,
                    by=f"{verb_label} {record_id}",
                    intent=intent,
                )
                if ptr_record_path is not None:
                    touched.append(ptr_record_path)
    elif (
        spec.destination == "hook"
        and hook_route is not None
        and spec.target is not None
    ):
        script_observed = _observe_region_hash_at(spec.target, "script")
        script_expected = hook_route.script.encode("utf-8")
        script_record_path = _resync_region_entry(
            home,
            host_path=spec.host_path,
            scope_kind=spec.scope_kind,
            mode=spec.mode,
            target=spec.target,
            region_kind="script",
            expected=script_expected,
            observed_hash=script_observed,
            by=f"{verb_label} {record_id}",
            intent=intent,
        )
        if script_record_path is not None:
            touched.append(script_record_path)
    return touched


def _execute_route(
    home: Path,
    record: Record,
    spec: TargetSpec,
    *,
    by: str,
    hook_route: "_HookRoute | None",
    note: str | None,
    no_push: bool,
    on_first_write: str,
    bucket_dir: Path,
    sentinel_owned: bool,
    old_id: str | None,
    old_record: "Record | None",
    old_path: "Path | None",
    verb_label: str = "route",
    project_path: Path | None = None,
    user_claude_md: Path | str | None = None,
    follow_up: dict | None = None,
    collapse: "_CollapseCtx | None" = None,
    capture_diff: bool = False,
) -> VerbResult:
    """THE pinned route sequence (M-R, lane L7): every step `route`
    (pending-file input, git-mv) and `route_direct` (in-memory record,
    direct write) share, in order — old-record retirement preflight
    (the supersede SCAN-and-status-check half stays adapter-side, pre-
    sentinel; see the ``old_id``/``old_record``/``old_path`` paragraph
    below), collapse's in-memory merge, the first write
    (``on_first_write``: ``"resolve"`` calls :func:`resolve_record`
    (git-mv pending→resolved + frontmatter rewrite) — ``"direct"`` writes
    *record* straight into ``resolved/``), old_id/losers supersession,
    the merge-proposal cleanup, the compile-record entry (REC9: same
    ledger commit), D-3 retirement completion
    (:func:`_complete_old_retirement`), the three-region resync
    (:func:`_resync_three_regions`), the pinned commit, `route` telemetry
    (spooled BEFORE the host phase — a host-phase failure must not
    undercount it), the host phase, the retirement host phase, and the
    push+:class:`VerbResult` assembly.

    ``on_first_write`` is a STRING flag, not a callable: `test_lock_
    invariant.py`'s call-graph walker only resolves same-module/imported
    ``ast.Name`` callees — a parameter-bound callable is invisible to it,
    which would misclassify ``resolve_record``/``Record.write`` as
    unreachable roots (no caller the walker can see) and flag them
    unlocked. An in-core ``if`` keeps both mutations statically,
    resolvably under this function's own `with _ledger_write(home),
    gitops.host_lock(...)` block.

    ``capture_diff`` is the ONE step that is genuinely present-or-absent
    rather than shaped-the-same: `route_direct`'s `VerbResult.diff` has
    always carried the staged ledger diff + host diff (+ the hook script,
    prefixed) — T8's invocation-is-approval contract needs it printed;
    `route`'s has always been the hook script alone, or `None` — the CLI
    verb's own diff story is separate (`route --dry-run`'s unified diff).
    Unifying the TEXT would silently change one adapter's printed output;
    parametrizing whether the extra pre-commit ``gitops.stage`` +
    ``gitops.staged_diff`` capture runs preserves both byte-for-byte.

    ``verb_label`` (``"route"`` | ``"route-direct"``) is the OTHER
    deliberate, adapter-owned divergence (census §2): it never appears in
    the commit SUBJECT (always literally ``"route"``, both adapters) —
    only in the compile-record's internal ``by=`` provenance trace, which
    has always told the two callers apart. `sentinel_owned` is threaded
    in rather than recomputed: the sentinel hold wraps this ENTIRE call
    (`try`/`finally: hold.release()`) in the adapter, which is the only
    place that knows whether it took ownership.

    ``old_id``/``old_record``/``old_path`` are threaded in, PRE-COMPUTED
    by the caller, rather than derived here from ``record.supersedes``:
    the module docstring pins "(a) scan, THEN (b) sentinel self-hold",
    and both predecessors ran the OLD record's own scan-and-status-check
    as part of that same pre-sentinel (a) step (`route` at the original
    verbs.py 3812-3821, `route_direct` at 4363-4372, both before their
    `hold = sentinel.hold()`). Computing it inside this function instead
    would run it AFTER the adapter's `sentinel.hold()` in both callers —
    harmless in practice (the hold is released in the adapter's `finally`
    regardless of where inside the `try` a refusal fires) but a real
    ordering deviation from a documented invariant; each adapter keeps
    doing this preflight itself, at the same pre-sentinel point it always
    did, and simply hands the three results through."""
    home = Path(home)
    record_id = record.id

    warnings: list[str] = []
    old_retire: _Retirement | None = None
    old_observed_hash: str | None = None
    if old_record is not None:
        # narrowing aid for pyright, not a runtime-load-bearing check:
        # `old_path` is set in the same `if old_id is not None:` branch
        # that produces `old_record` a few lines above, so `old_record
        # is not None` already implies `old_path is not None` — an
        # `assert` here is STRIPPED under `python -O` (D-3), but nothing
        # downstream can silently misbehave on a stale `None`: the next
        # line's `old_path.parent.parent` would raise `AttributeError`
        # regardless of interpreter flags.
        assert old_path is not None
        old_retire = _retirement_preflight(
            home,
            old_record,
            old_path.parent.parent,
            warnings,
            user_claude_md=user_claude_md,
        )
        old_observed_hash = _observe_retirement_region(old_retire)

    losers: list[str] = collapse.losers if collapse is not None else []
    if collapse is not None:
        superseded = losers + ([old_id] if old_id else [])
        suffix = f" (collapse {collapse.cluster_id}, supersedes {', '.join(superseded)})"
    else:
        suffix = f" (supersedes {old_id})" if old_id else ""
    message_target = (
        f"new-skill:{spec.new_skill}" if spec.destination == "new-skill" else spec.destination
    )
    message = f"self-learn: route {record_id} → {message_target}{suffix}"
    routed_at = _now_iso()

    merged: Record | None = None
    if collapse is not None:
        # Merge the losers into an IN-MEMORY survivor (route only —
        # `route_direct` never sets `collapse`): evidence gains their
        # provenance plus one merged_from marker per loser, sightings
        # becomes the cluster total. Nothing touches disk until preflight
        # has passed; the merged_from markers make a crash-window retry
        # idempotent (an already-folded loser is skipped).
        merged = Record.from_path(collapse.pending_path)
        already_folded = {
            e.get("merged_from") for e in merged.evidence if e.get("merged_from")
        }
        total_sightings = merged.sightings
        for rid in losers:
            if rid in already_folded:
                continue
            lr = Record.from_path(collapse.pending_path.parent / f"{rid}.md")
            for entry in lr.evidence:
                merged.append_evidence(entry)
            merged.append_evidence(
                {"merged_from": rid, "sightings": lr.sightings, "ts": routed_at}
            )
            total_sightings += lr.sightings
        merged.set_sightings(total_sightings)

    with _ledger_write(home), gitops.host_lock(spec.host_path, spec.mode):
        # Observe the region NOW — before anything below mutates the
        # ledger — so the compile record's `based_on_sha256` is the state
        # THIS write is based on, never a later re-read (U-hostmode
        # §4.5b/REC12/REC13).
        observed_hash = _observe_region_hash(spec)

        # M-W (D7): collapse folds several files (the survivor's merge
        # write, its git-mv into resolved/, a supersede-git-mv per
        # old_id/loser, the merge-proposal removal) into ONE commit — a
        # SIGKILL between any two of them leaves a staged rename or a
        # staged deletion, and `reconcile._BLOCKING_CODES` refuses to
        # touch either shape forever (a half-committed `git mv`/`git rm`
        # must never be completed one file at a time). The intent
        # brackets exactly that span: opened here, before the first
        # mutation, closed by `intents.finish` right after the ledger
        # commit below.
        #
        # Gate r1 MAJOR-1 (supersedes the original M-W design, which left
        # this section covering only the paths above): the compile-record
        # writes further down (`_write_compile_record_entry`,
        # `_complete_old_retirement`, `_resync_three_regions`) are now
        # covered TOO — not by listing them here (their host/slug is not
        # resolved yet at this point), but via `intents.add_step`, called
        # from inside each of those three right before its own write, at
        # the moment its target path (`home/compiled/<slug>.yaml`)
        # becomes known. `reconcile._RECONCILABLE_HOME` still heals a
        # LEFTOVER compile-record orphan on its own (path-shape + M-C
        # content validation) regardless of which operation orphaned it —
        # that redundancy is fine — but relying on it ALONE let a kill in
        # this specific window commit a compile record for a route the
        # SAME `reconcile()` call had just rolled back (gate r1 measured
        # this live: `compiled/<host>.yaml` ended up naming a route that
        # no longer existed). Every step this intent now covers lands in
        # ONE commit on roll-forward — the two-commit split the original
        # design accepted (a separate `reconcile()` orphan-scan commit
        # for the leftover compile records) no longer happens, because
        # there is nothing left uncovered for that scan to pick up. A
        # plain (non-collapse) route is out of D7's scope entirely:
        # `intent` stays `None` throughout, so every `add_step` call
        # above no-ops, exactly the pre-existing behavior.
        intent: intents.Intent | None = None
        if collapse is not None:
            intent_paths: list[Path] = [
                collapse.pending_path,
                bucket_dir / "resolved" / f"{record_id}.md",
            ]
            if old_id is not None:
                assert old_path is not None  # see the narrowing note above
                if old_path.parent.name == "pending":
                    intent_paths += [
                        old_path,
                        old_path.parent.parent / "resolved" / f"{old_id}.md",
                    ]
                else:
                    intent_paths.append(old_path)
            for loser_id in losers:
                intent_paths += [
                    collapse.pending_path.parent / f"{loser_id}.md",
                    bucket_dir / "resolved" / f"{loser_id}.md",
                ]
            if collapse.merge_path.exists():
                intent_paths.append(collapse.merge_path)
            intent = intents.begin(home, "collapse", intent_paths, message)

        if merged is not None:
            merged.write(collapse.pending_path)  # type: ignore[union-attr]

        if on_first_write == "resolve":
            touched = resolve_record(
                home,
                record_id,
                "routed",
                destination=spec.destination,
                by=by,
                routed_at=routed_at,
                note=note,
                follow_up=follow_up,
                reference_file=spec.ref_name if spec.destination == "reference" else None,
                hook=hook_route.meta if hook_route is not None else None,
                new_skill=spec.new_skill if spec.destination == "new-skill" else None,
                # persisted FROM the RESOLVED spec, not a pre-resolve
                # value — the one source that can never diverge from
                # what was actually written (A2 §4.3/§4.4).
                variant=spec.variant,
                rules_topic=spec.rules_topic,
                rules_paths=list(spec.rules_paths) if spec.rules_paths else None,
                allow_empty_glob=spec.glob_bypass,
                glob_bypass_reason=spec.glob_bypass_reason,
                verb="route",
            )
            routed_record = Record.from_path(
                bucket_dir / "resolved" / f"{record_id}.md"
            )
        elif on_first_write == "direct":
            resolved_path = bucket_dir / "resolved" / f"{record_id}.md"
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            record.write(resolved_path)
            touched = [resolved_path]
            if record.scope == "project":
                touched.append(ensure_project_meta(bucket_dir, project_path))
            routed_record = record
        else:
            raise ValueError(f"_execute_route: unknown on_first_write {on_first_write!r}")

        if old_id is not None:
            # teach --supersedes completion-at-route: SAME commit (08 §1
            # Corrective-supersession pin).
            touched = touched + supersede_record(home, old_id, record_id, verb="route")
        for loser_id in losers:
            # collapse: losers superseded by the survivor, SAME commit.
            touched = touched + supersede_record(home, loser_id, record_id, verb="route")
        if collapse is not None and collapse.merge_path.exists():
            # belt-and-braces: the sibling sweep removes it when it names
            # the survivor; an inconsistent leftover is removed here.
            from .ledger_ops import _remove_file

            try:
                if _remove_file(home, collapse.merge_path):
                    touched = touched + [collapse.merge_path]
            except gitops.GitOpsError as exc:
                raise gitops.HalfWrittenError.for_commit(
                    home, message, [*touched, collapse.merge_path], exc
                ) from exc

        # U-hostmode REC1/REC9: the compile record's EXPECTATION can only
        # be computed now — the record file rides THIS SAME ledger commit.
        # Gate r1 MAJOR-1: `intent=intent` threads through to every
        # compile-record write below (this call, `_complete_old_
        # retirement`, `_resync_three_regions`) so each one registers
        # its own path via `intents.add_step` right before its write —
        # closing the gap where a kill between any of these three and
        # `intents.complete` used to land a compile record for a route
        # that intent recovery then rolled BACK, and vice versa.
        record_path = _write_compile_record_entry(
            home, spec, observed_hash, by=f"{verb_label} {record_id}", intent=intent
        )
        if record_path is not None:
            touched = touched + [record_path]

        touched = touched + _complete_old_retirement(
            home,
            spec,
            old_retire,
            old_id,
            old_record,
            old_observed_hash,
            verb_label=verb_label,
            record_id=record_id,
            intent=intent,
        )
        touched = touched + _resync_three_regions(
            home,
            spec,
            record_id,
            hook_route=hook_route,
            routed_record=routed_record,
            verb_label=verb_label,
            intent=intent,
        )

        if intent is not None:
            # M-W (D7): every collapse mutation has now landed on disk —
            # record each step's REAL final state in one pass. A crash
            # before this line leaves every step's `new_sha` unrecorded
            # (`recover()` restores); a crash after it (commit included)
            # leaves every step verified (`recover()` rolls forward).
            intents.complete(intent)

        if capture_diff:
            try:
                staged = gitops.stage(home, touched)
                diff_text: str | None = gitops.staged_diff(home, staged)
            except gitops.GitOpsError as exc:
                raise gitops.HalfWrittenError.for_commit(
                    home, message, touched, exc
                ) from exc
            _, sha = _commit_ledger(home, touched, message, note)
        else:
            diff_text = None
            staged, sha = _commit_ledger(home, touched, message, note)

        if intent is not None:
            # The commit landed — this intent's job is done.
            intents.finish(intent)

        # `route` telemetry (11 §4.3, U-reach §2.2): placed immediately
        # after the ledger commit closes — the ledger commit IS the
        # routing (doc 13 §4.1) — so a host-phase failure below must
        # still leave this event spooled.
        telemetry.spool_quiet(
            "route",
            record=record_id,
            destination=spec.destination,
            scope=record.scope,
            by=by,
            variant=spec.variant,
        )

        # (e) HOST phase: compile from the committed ledger state + host
        # commit, still under the sentinel hold AND both locks — only the
        # push (below) sits outside.
        host_note = note
        if hook_route is not None:
            snippet_block = f"settings.json snippet:\n{hook_route.snippet}"
            host_note = f"{note}\n\n{snippet_block}" if note else snippet_block
        compile_result, host_sha = _host_phase(
            home,
            spec,
            record_id,
            routed_record=routed_record,
            note=host_note,
            message=message,
            warnings=warnings,
            user_push=not no_push,
        )

    # (e2) retirement HOST phase for the superseded old record.
    retire_notes: list[str] = []
    old_host_sha = None
    old_host_repo = None
    if old_retire is not None:
        old_host_sha, old_host_repo = _retirement_host_phase(
            home,
            old_retire,
            old_id,
            note=note,
            message=message,
            warnings=warnings,
            post_notes=retire_notes,
            skip_target=spec.target,
            user_push=not no_push,
        )

    if capture_diff and host_sha is not None and spec.mode == "git":
        host_diff = gitops._git(  # noqa: SLF001 — same module family
            spec.host_path, "show", "--format=", host_sha
        ).stdout
        diff_text = (diff_text or "") + host_diff
    if hook_route is not None:
        # The applied script bytes lead the printed diff, in full (08
        # §8.1 approval flow: visibility without a confirmation gate).
        if capture_diff:
            # always a `str` here: the `if capture_diff:` branch inside
            # the lock above always sets it — the assert is a narrowing
            # aid for pyright, not a runtime-load-bearing check (a stale
            # `None` would fail the `+` right below regardless).
            assert diff_text is not None
            diff_text = hook_route.script + "\n--- ledger ---\n" + diff_text
        else:
            diff_text = hook_route.script

    post_notes = (
        _hook_manual_steps(hook_route.snippet, spec.target.name)
        if hook_route is not None
        else [
            f"new skill scaffolded at plugins/{spec.new_skill} — run "
            "./install.sh to symlink it into ~/.claude/skills "
            "(M3-11); enrich the prose post-hoc whenever you like"
        ]
        if spec.destination == "new-skill" and getattr(compile_result, "scaffolded", False)
        else []
    ) + retire_notes

    # (f) push ledger, then push host (pinned retry, has_remote-guarded).
    push = None if no_push else gitops.push_if_remote(home)
    host_push = None
    if not no_push and host_sha is not None and spec.mode == "git":
        host_push = gitops.push_if_remote(spec.host_path)
    if not no_push and old_host_sha is not None and old_host_repo is not None:
        # possibly the same repo as the successor's — a second push is a
        # no-op, and skipping it would strand the retirement commit
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
        sentinel_owned=sentinel_owned,
        diff=diff_text,
        warnings=warnings,
        post_notes=post_notes,
        host_commit_sha=host_sha,
        host_push=host_push,
        target=spec.target,
        destination=spec.destination,
        variant=spec.variant,
        mode=spec.mode,
    )


def route(
    home: Path | str,
    record_id: str,
    *,
    dest: str | None = None,
    by: str | None = None,
    note: str | None = None,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
    follow_up: dict | None = None,
    collapse: str | None = None,
    allow_empty_glob: bool = False,
) -> VerbResult:
    """Route a pending record into canon. See the module docstring for the
    pinned sequence (M-R: the post-preflight half now lives once, in
    :func:`_execute_route`, shared with :func:`route_direct` — this
    function is the pending-file, git-mv ADAPTER: preflight the on-disk
    record + collapse cluster, resolve the destination/spec, then hand
    off); commit message ``self-learn: route lrn-… → <target>``
    (+ `` (supersedes lrn-…)`` when the record completes a
    ``teach --supersedes`` capture — old record superseded in the SAME
    commit). ``follow_up`` (11 §2.1: {action, unblocks_on?, note?}) rides
    the routing block — known-partial coverage, status stays terminal.
    ``allow_empty_glob`` (A2 §5.1 / U-glob) is the sanctioned escape past
    a rules route's zero-match or budget-exhausted glob refusal, EITHER
    scope — the write-the-rule-before-the-files case; the bypass and its
    reason are recorded in the routing block (§13 item 3, U-glob §6.5).

    ``by`` (FW-64, defaulted ``None``): names the actor that CHOSE THE
    DESTINATION, when the CALLER already knows and the ``dest``-is-not-
    None heuristic below would guess wrong — the review UI's own subprocess
    call is the one live case (it always sends an explicit ``--dest``, even
    on an unmodified approve-as-proposed, so the heuristic alone cannot
    distinguish "the analyst's proposal, displayed and accepted" from "the
    human cycled to a different one"). Terminal/bare-CLI callers leave this
    ``None`` and get the unchanged heuristic (an explicit ``--dest`` typed
    at a terminal IS the human's own choice)."""
    home = Path(home)
    if by is not None and by not in ROUTING_BY_VALUES:
        raise VerbError(
            f"by must be one of {sorted(ROUTING_BY_VALUES)}, got {by!r}"
        )
    if follow_up is not None:
        try:
            _validate_follow_up(follow_up)
        except RecordError as exc:
            raise VerbError(str(exc)) from exc
    # pending OR resolved (FW-51: no longer lies "not found" for a
    # resolved record whose status makes `route` illegal).
    path = find_record_path(home, record_id)

    # (a) scan the record file BEFORE trusting its contents — same order
    # as every other resolution verb: raw-bytes scan, THEN parse.
    _scan_or_refuse([path], note)
    try:
        _, record = require_status(home, record_id, LIVE_STATUSES, verb="route")
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc

    # Old-record supersede preflight stays pre-sentinel, HERE, matching
    # the module docstring's pinned "(a) scan, THEN (b) sentinel" order
    # (verbs.py 3812-3821 at 7d95705, the cut point) — `_execute_route`
    # takes the three results as parameters rather than re-deriving them
    # post-hold (see its own docstring for why that split is load-bearing,
    # not cosmetic).
    old_id = record.supersedes
    old_record: Record | None = None
    old_path: Path | None = None
    if old_id is not None:
        old_path = find_record_path(home, old_id)
        _scan_or_refuse([old_path], None)  # this call rewrites it too (P2-7)
        try:
            _, old_record = require_status(
                home, old_id, RESOLVABLE_STATUSES, verb="route"
            )
        except LedgerOpsError as exc:
            raise VerbError(str(exc)) from exc

    # Collapse preflight is disk-shape-specific (reads the proposal +
    # every member's pending file) and stays HERE — `route_direct` has no
    # cluster to read and never sets `collapse` (`_execute_route`'s
    # `collapse=None` path is what it always takes).
    collapse_ctx: _CollapseCtx | None = None
    if collapse is not None:
        merge_path, losers = _load_cluster(
            home, path.parent.parent, record_id, collapse
        )
        # every loser file is rewritten by this verb (P2-7)
        _scan_or_refuse([path.parent / f"{rid}.md" for rid in losers], None)
        collapse_ctx = _CollapseCtx(
            cluster_id=collapse, pending_path=path, merge_path=merge_path, losers=losers
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
        # dirty checks + the compile-record predicate for user scope
        # (§4.5a). Every refusal lands HERE — before any commit; the
        # record stays pending. Hook routes additionally pre-flight the
        # proposal-carried script: stamp presence, record_sha freshness
        # (M3-2), and the M3-12 example replay against the exact bytes.
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
                variant=resolved_dest.variant,
                rules_topic=resolved_dest.rules_topic,
                rules_paths=resolved_dest.rules_paths,
                allow_empty_glob=allow_empty_glob,
            )

        # §2.3, corrected by FW-64: `routing.by` names the actor that CHOSE
        # THE DESTINATION. The premise this comment used to state — "the
        # review UI's approve-as-proposed argv omits --dest entirely" —
        # was FALSE: driven end to end, the review UI's action bar always
        # carries an explicit `dest` hidden field (`destination_default`,
        # scope-corrected), so the old dest-is-not-None heuristic alone
        # read "human" on EVERY UI approval, including an unmodified
        # accept of the analyst's own proposal. The heuristic below is
        # still correct for a caller that genuinely has no better
        # knowledge (a bare terminal `route <id>` vs. `route <id> --dest
        # X` — an explicit --dest typed at a shell IS the human's own
        # choice); what changed is that a caller who DOES know better (the
        # review UI's own subprocess call, via `--by`) may now say so
        # explicitly instead of being guessed at.
        resolved_by = by if by is not None else ("human" if dest is not None else "analyst")

        return _execute_route(
            home,
            record,
            spec,
            by=resolved_by,
            hook_route=hook_route,
            note=note,
            no_push=no_push,
            on_first_write="resolve",
            bucket_dir=bucket_dir,
            sentinel_owned=hold.owned,
            old_id=old_id,
            old_record=old_record,
            old_path=old_path,
            verb_label="route",
            user_claude_md=user_claude_md,
            follow_up=follow_up,
            collapse=collapse_ctx,
            capture_diff=False,
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
    project_path: Path | None = None,
    hook_input: dict | None = None,
    follow_up: dict | None = None,
    allow_empty_glob: bool = False,
) -> VerbResult:
    """``teach --route``'s writer (02 §2 lifecycle note): the composed,
    not-yet-on-disk record is written DIRECTLY into its bucket's
    ``resolved/`` as ``status: routed`` — never transiting ``pending/``.

    Same pinned sequence as :func:`route` (:func:`_execute_route`; scan,
    sentinel self-hold + heartbeat, dirty-target abort, compile, targeted
    stage, pinned commit ``self-learn: route lrn-… → <target>``, per-verb
    push, release-iff-owned), same ``--supersedes`` completion in the SAME
    commit. The destination is required — the caller (structured
    ``--dest``, or the one-shot analyst) supplies it; there is no
    proposal sibling to read. ``VerbResult.diff`` carries the staged
    pre-commit diff (``git diff --cached`` of the touched paths) for T8
    to print — invocation is the approval, so the diff is informational,
    never a prompt.

    ``follow_up`` (M-R: previously absent — census §2 — `teach --route`
    had no way to open one) and ``allow_empty_glob`` (M-R: threaded into
    :func:`_resolve_target` for structural parity with `route`; a no-op
    in practice today — the analyst proposal never carries
    ``rules_paths``, P-A5, so the zero-match refusal this flag bypasses
    can only fire on `route`'s proposal-sourced path) follow the SAME
    validation/persistence shape `route` already gives them.

    ``by`` (§2.3, defaulted "human" — not required, so ``teach.py``'s
    existing call keeps working unmodified): names the actor that CHOSE
    THE DESTINATION. FW-64 completed the follow-up §6/§7 flagged: the
    bare-analyst ``teach --route`` path (destination from
    ``analyst.analyze()``) now threads ``by="analyst"`` explicitly at its
    call site (``teach.py``) — this default only still covers
    ``teach --route --dest X``, where an explicit --dest typed at the
    terminal genuinely is the human's own choice."""
    home = Path(home)
    if by not in ROUTING_BY_VALUES:
        raise VerbError(
            f"by must be one of {sorted(ROUTING_BY_VALUES)}, got {by!r}"
        )
    if follow_up is not None:
        try:
            _validate_follow_up(follow_up)
        except RecordError as exc:
            raise VerbError(str(exc)) from exc
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

    # Old-record supersede preflight stays pre-sentinel, HERE, matching
    # the module docstring's pinned "(a) scan, THEN (b) sentinel" order
    # (verbs.py 4363-4372 at 7d95705, the cut point) — `_execute_route`
    # takes the three results as parameters rather than re-deriving them
    # post-hold (see its own docstring for why that split is load-bearing,
    # not cosmetic).
    old_id = record.supersedes
    old_record: Record | None = None
    old_path: Path | None = None
    if old_id is not None:
        old_path = find_record_path(home, old_id)
        _scan_or_refuse([old_path], None)  # this call rewrites it too (P2-7)
        try:
            _, old_record = require_status(
                home, old_id, RESOLVABLE_STATUSES, verb="route"
            )
        except LedgerOpsError as exc:
            raise VerbError(str(exc)) from exc

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
                project_path=project_path,
                allow_empty_glob=allow_empty_glob,
            )

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
        if follow_up is not None:
            routing["follow_up"] = dict(follow_up)
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

        # nit-3 (gate r1): no `follow_up=` below, deliberately -- the
        # "direct" branch above already owns and sets its own routing
        # block (`record.set_routing(routing)`, `follow_up` included
        # when given), so the core's own `follow_up` parameter (which
        # `route` relies on to reach `resolve_record`) would be
        # redundant here, not omitted by oversight.
        return _execute_route(
            home,
            record,
            spec,
            by=by,
            hook_route=hook_route,
            note=note,
            no_push=no_push,
            on_first_write="direct",
            bucket_dir=bucket_dir,
            sentinel_owned=hold.owned,
            old_id=old_id,
            old_record=old_record,
            old_path=old_path,
            verb_label="route-direct",
            project_path=project_path,
            user_claude_md=user_claude_md,
            capture_diff=True,
        )
    finally:
        hold.release()  # (g) release iff owned


# --------------------------------------------------------- U20 commit-drift
#
# F5-5 guided commit-first (ruled 2026-07-19): the dirty-target refusal
# (DirtyTargetError above) stays fully intact — no override, no force, no
# bypass anywhere in this verb. This is the GUIDED path a human takes
# instead: commit the TARGET repo's OWN pending changes first (their
# commit, separate from ours, pinned subject below), then the UI retries
# the original route once. It serves the DIRTY case only, and only for a
# git-mode host (CD1: commit-drift refuses a plain host outright) — a
# plain host's equivalent is the compile-record predicate's own
# "edited"/"unknown provenance" refusal (§4.5a), which names
# `recompile --adopt` instead; a commit cannot repair that (it is a
# ledger-side record, not a git state).

#: Pinned commit subject (§2.1) — never a push, never the ledger, never
#: our own compile; the commit is theirs, in their repo, of their changes.
COMMIT_DRIFT_SUBJECT = "chore: commit drift before self-learn route"

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
        if spec.target is None:
            raise VerbError("commit-drift: new-skill target unresolved")
        marketplace = spec.host_path / ".claude-plugin" / "marketplace.json"
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
    dry_run: bool = False,
) -> CommitDriftResult:
    """``self-learn host commit-drift`` (§2.1): commit the compile
    target's OWN pending changes — the SAME target-resolution a failed
    ``route <record_id> [--dest dest]`` used (:func:`_resolve_target`,
    ``check_dirty=False`` — the E-17 read-only mode; never a second
    resolver), so this verb refuses any path outside a registered host by
    construction.

    U-hostmode §4.7 (CD1/CD2): mode-branched, not scope-branched. A
    **plain**-mode host — user scope included — REFUSES at exit 64: there
    is no commit to make, because self-learn commits nothing there and the
    human's own file is their own to manage. The dotfiles-management
    user leg this verb used to run is DELETED (not rewritten) — there is
    no such leg left to take, on ANY plain host.

    **git**-mode host (skill-md / claude-md project·skill-root /
    reference / new-skill), byte-unchanged: :func:`gitops.paths_dirty` is
    already target-path scoped, so the commit is too — ``git commit --
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
        check_dirty=False,
        variant=resolved_dest.variant,
        rules_topic=resolved_dest.rules_topic,
        rules_paths=resolved_dest.rules_paths,
    )

    hold = sentinel.hold() if not dry_run else None
    if hold is not None:
        sentinel.heartbeat()
    try:
        if spec.mode != "git":
            # U-hostmode CD1: a plain host (user scope included) has
            # nothing to commit — self-learn commits nothing there, and
            # the human's own file is their own to manage. Exit 64,
            # matching every other `host`-family refusal.
            raise VerbError(
                f"commit-drift: {spec.host_path} is a PLAIN host — "
                "self-learn commits nothing there, so there is nothing "
                "for this verb to commit; the file is yours to manage"
            )

        # git-mode host: target-path-scoped dirty check + scoped
        # commit, under the host's OWN commit lock (mirrors _host_phase:
        # the window between reading dirty state and committing it is
        # exactly what a racing self-learn producer's `pull --rebase
        # --autostash` could stash away mid-flight — doc 13 §4's
        # rebase-autostash race). `targets` may be more than one path
        # (new-skill: SKILL.md + marketplace.json, gate M2-fold-1) — the
        # commit's pathspec is scoped to exactly the DIRTY subset, never
        # the full candidate set (a clean sibling stays untouched).
        targets = _commit_drift_targets(spec)
        with gitops.commit_lock(spec.host_path):
            dirty_targets = [
                t for t in targets if gitops.paths_dirty(spec.host_path, t)
            ]
            if not dirty_targets:
                raise VerbError(NOTHING_TO_COMMIT)
            files = [
                f
                for t in dirty_targets
                for f in gitops.dirty_paths(spec.host_path, t)
            ]
            if dry_run:
                return CommitDriftResult(
                    repo=spec.host_path,
                    files=files,
                    commit_sha=None,
                    commit_message=COMMIT_DRIFT_SUBJECT,
                    dry_run=True,
                )
            sha = gitops.commit(
                spec.host_path, COMMIT_DRIFT_SUBJECT, paths=dirty_targets
            )
        return CommitDriftResult(
            repo=spec.host_path,
            files=files,
            commit_sha=sha,
            commit_message=COMMIT_DRIFT_SUBJECT,
            dry_run=False,
        )
    finally:
        if hold is not None:
            hold.release()


def reject(
    home: Path | str,
    record_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Reject a pending (or deferred) record. Commit: ``self-learn:
    reject lrn-…``. FW-51: refuses BEFORE any lock/mutation, naming the
    record's actual status, when it is already resolved — never the old
    lying "not found" (:func:`require_status`). A genuinely UNKNOWN id
    stays a bare :class:`LedgerOpsError` (exit 64, unwrapped) —
    `find_record_path` runs first, outside the wrap, exactly as
    `test_unknown_record_id_is_usage_error` pins."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    try:
        require_status(home, record_id, LIVE_STATUSES, verb="reject")
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: reject {record_id}"
        with _ledger_write(home):
            touched = resolve_record(home, record_id, "rejected", note=note, verb="reject")
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
    """Defer a pending (or already-deferred) record (default +30 d).
    Commit: ``self-learn: defer lrn-… until <date>``. The note rides the
    commit body only — ``resolution_note`` is reserved for resolutions
    (02 §2), and deferral is not one. FW-51: refuses BEFORE any
    lock/mutation, naming the record's actual status, when it is already
    resolved — never the old lying "not found" (:func:`require_status`).
    A genuinely UNKNOWN id stays a bare :class:`LedgerOpsError` (exit 64,
    unwrapped) — `find_record_path` runs first, outside the wrap, same
    contract `reject`/`route` pin."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    try:
        require_status(home, record_id, LIVE_STATUSES, verb="defer")
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with _ledger_write(home):
            try:
                touched = defer_record(home, record_id, until)
            except LedgerOpsError as exc:
                # U-verbs §4.2: a past `--until` is a REFUSAL (exit 1,
                # nothing written), never a usage error (64) — the flag
                # parsed fine and it is the record's target STATE that
                # makes it illegal (02 §2's own distinction). Nothing has
                # been written yet at this point.
                raise VerbError(str(exc)) from exc
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


def _resolve_move_target(home: Path, to: str) -> tuple[str, Path, Path | None]:
    """The ONE target resolver behind both ``rehome --to`` and ``rescope
    --to`` (U-verbs §4.1, ruling R1 — one grammar, one resolver, matched
    in this order, first match wins):

    | ``--to``                         | resolves to                                  |
    |-----------------------------------|-----------------------------------------------|
    | exactly ``user``                  | ``("user", home/"user", None)``                |
    | ``skill:<name>``, non-empty       | ``(f"skill:{name}", home/"skills"/name, None)`` |
    | ``project:<rest>``                | as the bare form below, over ``<rest>``        |
    | anything else                     | ``("project", home/"projects"/slug, resolved)`` |

    The reserved literals ``user`` and ``skill:...`` are matched as
    LITERALS before any path resolution, so a registered project host
    whose directory is literally named ``user`` is unreachable by the
    bare form — the escapes are ``project:user``, ``./user``, or the
    absolute path. Returns ``(target_scope, target_bucket,
    project_path)`` — ``project_path`` is the resolved host path, set
    IFF the target is a project bucket (§3.2b: only project scope
    carries a path a bucket cannot derive from its own name)."""
    if to == "user":
        return "user", home / "user", None
    if isinstance(to, str) and to.startswith("skill:") and len(to) > len("skill:"):
        name = to[len("skill:") :]
        try:
            skill_dir_for(load_hosts(home), name)  # validity gate only
        except HostsError as exc:
            raise VerbError(str(exc)) from exc
        return f"skill:{name}", home / "skills" / name, None
    rest = to[len("project:") :] if isinstance(to, str) and to.startswith("project:") else to
    project_path = _resolve_rehome_target(home, rest)
    slug = slug_for(project_path)
    return "project", home / "projects" / slug, project_path


def _bucket_scope_literal(home: Path, bucket: Path) -> str:
    """The scope LITERAL a bucket dir's own IDENTITY implies — never the
    record's ``scope:`` field (U-verbs §4.1 step 5: a record whose
    frontmatter disagrees with its bucket is what the move verbs repair,
    so the field cannot be trusted to answer "is this a move at all")."""
    if bucket == home / "user":
        return "user"
    if bucket.parent == home / "skills":
        return f"skill:{bucket.name}"
    return "project"


def _move_dest_label(target_scope: str, target_bucket: Path) -> str:
    """The commit-subject/disclosure-line spelling of a move target
    (U-verbs §4.1 — widens the predecessor ``_rescope_dest_label`` by one
    arm): ``projects/<slug>`` | ``skills/<name>`` | ``user`` — never the
    raw scope literal. The project arm is byte-identical to `rehome`'s
    pre-existing subject shape (``target_bucket.name`` IS the slug)."""
    if target_scope == "user":
        return "user"
    if target_scope.startswith("skill:"):
        return f"skills/{target_scope[len('skill:') :]}"
    return f"projects/{target_bucket.name}"


def _rescope_sweep_note(record_id: str, swept: list[Path], dest_label: str) -> str:
    """R-DISCLOSE-1 (u-rescope §5.5, widened to `rehome` too — U-verbs
    §3.2): one human-facing line naming the count of each swept
    component and the fact of re-analysis, e.g. ``swept 1 proposal + 2
    merge clusters — lrn-… will be re-analyzed in skills/bitwarden-cli``.
    Lists ONLY the non-zero components — a merge-cluster-only sweep must
    not print "swept 0 proposal". Called only when ``swept`` is
    non-empty (empty means no note at all — never "swept 0")."""
    has_proposal = any(
        p.name in (f"{record_id}.yaml", f"{record_id}.diff") for p in swept
    )
    n_merge = sum(1 for p in swept if p.name.startswith("merge-"))
    parts = []
    if has_proposal:
        parts.append("1 proposal")
    if n_merge:
        parts.append(f"{n_merge} merge cluster" + ("" if n_merge == 1 else "s"))
    counts = " + ".join(parts)
    return f"swept {counts} — {record_id} will be re-analyzed in {dest_label}"


def _rescope_commit_body(note: str | None, swept: list[Path]) -> str | None:
    """Compose the commit body: ``note`` (or nothing) followed, when
    ``swept`` is non-empty, by one ``swept: <relpath>`` line per swept
    file — R-DISCLOSE-2 (§5.5/§6.2 step 8). This is the ONLY body
    channel: :func:`_commit_ledger` passes it straight through to
    ``gitops.commit(..., body=note, ...)`` (`verbs.py:460`)."""
    parts: list[str] = []
    if note:
        parts.append(note)
    if swept:
        parts.append("\n".join(f"swept: {p}" for p in swept))
    return "\n\n".join(parts) if parts else None


def _move(
    home: Path | str,
    record_id: str,
    *,
    to: str,
    verb: str,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """The ONE verb body behind both ``rehome`` and ``rescope`` (U-verbs
    §4.1, ruling R1 / criterion ``MOVE10``): neither entry point may
    contain a file-op of its own — every byte reaches disk only through
    :func:`ledger_ops.move_record`, called from HERE. Step order is
    ``rescope``'s, the stricter of the two predecessor orderings.

    Refusals — each on STATUS, never mere existence (``find_record_path``
    also sees ``resolved/``), all BEFORE any commit or dir creation:
    unknown id (64, bare ``LedgerOpsError``) · not pending/deferred (1,
    :func:`require_status`) · ``--to`` unparseable / unregistered project
    / unknown skill (1, named repair) · same bucket (1) · id already
    present in the target bucket, ``pending/`` OR ``resolved/`` (1, the
    F4 create-record collision precedent)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved

    # (a) scan the record file BEFORE trusting its contents — plus the
    # note (P2-7): `rescope`/project legs genuinely rewrite the file
    # (`scope:` changes), so this is load-bearing, not a formality.
    _scan_or_refuse([path], note)

    try:
        require_status(home, record_id, LIVE_STATUSES, verb=verb)
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc

    target_scope, target_bucket, project_path = _resolve_move_target(home, to)

    # Source scope from the BUCKET, never the record's `scope:` field
    # (u-rescope §6.2 step 5 — a record whose frontmatter disagrees with
    # its bucket is what this verb repairs).
    source_bucket = path.parent.parent
    source_scope = _bucket_scope_literal(home, source_bucket)
    if source_scope == target_scope and target_bucket == source_bucket:
        raise VerbError(
            f"record {record_id} already lives in "
            f"{_move_dest_label(target_scope, target_bucket)} — nothing to move"
        )

    # Destination collision (F4 — the create_record precedent), checked
    # BEFORE any target-dir/meta.yaml creation — belt: the verb has
    # already refused before taking the lock; :func:`move_record` checks
    # again inside, since a duplicated id is corruption to surface,
    # never to merge into.
    for sub in ("pending", "resolved"):
        if (target_bucket / sub / f"{record_id}.md").exists():
            raise VerbError(
                f"record {record_id} already exists in {target_bucket} — "
                "a duplicated id is corruption to surface, never to merge "
                "into; inspect both files by hand"
            )

    dest_label = _move_dest_label(target_scope, target_bucket)

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: {verb} {record_id} → {dest_label}"
        with _ledger_write(home):
            touched, swept = move_record(
                home,
                record_id,
                target_scope=target_scope,
                target_bucket=target_bucket,
                project_path=project_path,
            )
            relswept = [
                p.relative_to(home) if p.is_relative_to(home) else p for p in swept
            ]
            body = _rescope_commit_body(note, relswept)  # R-DISCLOSE-2
            staged, sha = _commit_ledger(home, touched, message, body)
        push = _push_ledger(home, no_push)
        return VerbResult(
            action=verb,
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
            post_notes=(
                [_rescope_sweep_note(record_id, swept, dest_label)] if swept else []
            ),
        )
    finally:
        hold.release()


def rehome(
    home: Path | str,
    record_id: str,
    *,
    to: str,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Move a PENDING (or ``deferred``) record to any registered scope —
    ``user`` | ``skill:<name>`` | a registered project (02 §2 verb pin;
    09 §11 Y-18; widened U-verbs §3.2, ruling R1). ``--to`` accepts the
    UNION grammar :func:`_resolve_move_target` parses; a bare path/slug
    is byte-compatible with every existing project-only call. Ledger-only
    (one commit; ``--note`` rides the commit body only — rehome is not a
    resolution, ``resolution_note`` stays untouched). The record's bytes
    are otherwise untouched apart from ``scope:`` (§3.2b: a project→
    project move rewrites no ``scope:``, since both read the literal
    ``"project"`` — the ROUND-TRIP write is byte-identical there); a
    deferred record moves and stays deferred. Proposal siblings are
    swept and the sweep DISCLOSED (u-rescope's shape — `rehome`'s own
    sweep used to be silent; §3.2 closes that).

    All work is delegated to :func:`_move` — this function contains no
    file-op of its own (``MOVE10``)."""
    return _move(home, record_id, to=to, verb="rehome", note=note, no_push=no_push)


def rescope(
    home: Path | str,
    record_id: str,
    *,
    to: str,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Move a PENDING (or ``deferred``) record to any registered scope —
    ``user`` | ``skill:<name>`` | a registered project (u-rescope spec
    §6; widened U-verbs §3.2, ruling R1). Argv and commit-subject
    grammar are RETAINED unchanged from the shipped verb — ``--to``
    additionally accepts the project forms `rehome` always took.
    ``scope:`` is rewritten whenever the target scope literal differs
    from the source bucket's own (§3.2b); a project→project move
    rewrites no ``scope:`` (both read ``"project"``). Ledger-only (one
    commit; ``--note`` rides the commit body only — rescope is not a
    resolution, ``resolution_note`` stays untouched). A deferred record
    re-scopes and stays deferred. Proposal siblings are swept and the
    sweep DISCLOSED (R-DISCLOSE-1/2, u-rescope §5.5).

    All work is delegated to :func:`_move` — this function contains no
    file-op of its own (``MOVE10``)."""
    return _move(home, record_id, to=to, verb="rescope", note=note, no_push=no_push)


def undefer(
    home: Path | str,
    record_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Bring a deferred record back to the queue NOW (U-verbs §4.2) — the
    exact inverse of `defer`'s own write: `status: pending`, clears
    `deferred_until`, KEEPS `deferred_count` (the "at 2 the card
    suggests reject" signal is history, not state — `undefer` never
    clears it). The record already lives in `pending/` (deferred records
    never leave it), so this is a frontmatter rewrite in place, no
    `git mv`. Ledger-only, one commit `self-learn: undefer lrn-…`;
    `--note` rides the commit body only (`resolution_note` untouched —
    an un-defer is not a resolution). Re-running it refuses naming
    'pending' (GUARD3/GUARD4)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    try:
        require_status(home, record_id, DEFERRED_ONLY, verb="undefer")
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: undefer {record_id}"
        with _ledger_write(home):
            record = Record.from_path(path)
            record.set_status("pending")
            record.set_deferred_until(None)
            record.write(path)
            staged, sha = _commit_ledger(home, [path], message, note)
        push = _push_ledger(home, no_push)
        return VerbResult(
            action="undefer",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def reopen(
    home: Path | str,
    record_id: str,
    *,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Return a REJECTED record to the draft plane (U-verbs §4.2) — the
    inverse motion 02 §2's freeze-at-routing pin never had to give a
    rejected record: the old resolution is DISPLACED into `history`
    (never destroyed — :meth:`Record.clear_resolution_note` refuses
    unless the note is already there), the record moves resolved/ →
    pending/ (mv-first, §6.4), and any stale proposal sibling is swept
    and the sweep DISCLOSED, same shape as the move verbs. `--note`
    rides the commit body only.

    Refused, each naming the status AND the reason: `superseded` (a live
    successor, or a merge-collapse evidence merge, would be orphaned)
    and `routed` (un-writing canon is FW-133 — deliberately out of this
    unit's scope; correcting a wrong DESTINATION on an already-routed
    record is separate, dated work)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    try:
        require_status(home, record_id, REOPENABLE_STATUSES, verb="reopen")
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: reopen {record_id}"
        with _ledger_write(home):
            touched, swept = reopen_record(home, record_id)
            relswept = [
                p.relative_to(home) if p.is_relative_to(home) else p for p in swept
            ]
            body = _rescope_commit_body(note, relswept)
            staged, sha = _commit_ledger(home, touched, message, body)
        push = _push_ledger(home, no_push)
        post_notes = ["re-entering the queue — this record will be re-analyzed"]
        if swept:
            post_notes.append(_rescope_sweep_note(record_id, swept, "the queue"))
        return VerbResult(
            action="reopen",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
            post_notes=post_notes,
        )
    finally:
        hold.release()


def note(
    home: Path | str,
    record_id: str,
    *,
    append: str,
    key: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """Append one commentary entry to a record's `notes[]` (U-verbs
    §4.2) — ANY status, and NEVER touches `resolution_note`: `notes`
    records what was ADDED, `history` records what was DISPLACED.
    Secret-scanned like every other verb-written text.

    `--key` is the idempotency token `self-learn batch` stamps on a
    `note` item's entry (§3.3b row 10) — the sha256 of the sheet line
    that produced it. When a `notes[]` entry already carries `key`,
    NOTHING is appended: no lock taken, no commit, rc 0 — the
    already-applied state is a READ, never a parse of a refusal
    message. A human call at a terminal omits `key` and every call
    appends (two identical observations on two days are two facts)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], append)

    if key is not None and Record.from_path(path).note_has_key(key):
        # already-applied (§3.3b row 10): SKIPPED — nothing written, no
        # lock, no commit.
        return VerbResult(
            action="note",
            record_id=record_id,
            commit_message=f"self-learn: note {record_id} (already applied)",
            commit_sha=gitops.head_sha(home),
            staged=[],
            push=None,
            sentinel_owned=False,
        )

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: note {record_id}"
        with _ledger_write(home):
            record = Record.from_path(path)
            record.append_note(append, key=key)
            record.write(path)
            staged, sha = _commit_ledger(home, [path], message, append)
        push = _push_ledger(home, no_push)
        return VerbResult(
            action="note",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def _routing_dest_label(routing: dict) -> str:
    """A human label for a STORED routing block's destination —
    ``reference:LEARNINGS.md``, ``claude-md:rules:<topic>``,
    ``claude-md:local``, ``claude-md``, ``skill-md``, ``new-skill:<name>``,
    ``hook`` — the same vocabulary ``--dest`` accepts. Used only for
    ``reroute``'s same-destination refusal message (RER3); never a
    second destination grammar."""
    destination = routing.get("destination")
    if destination == "reference":
        ref_name = routing.get("reference_file") or DEFAULT_REFERENCE_BASENAME
        return f"reference:{ref_name}"
    if destination == "claude-md":
        variant = routing.get("variant")
        if variant == "local":
            return "claude-md:local"
        if variant == "rules":
            return f"claude-md:rules:{routing.get('rules_topic')}"
        return "claude-md"
    if destination == "new-skill":
        return f"new-skill:{routing.get('new_skill')}"
    return str(destination)


def reroute(
    home: Path | str,
    record_id: str,
    *,
    dest: str,
    by: str | None = None,
    note: str | None = None,
    no_push: bool = False,
    user_claude_md: Path | str | None = None,
) -> VerbResult:
    """Correct a wrong routing DESTINATION on an already-ROUTED record
    (U-verbs S-54 / §4.5, Phase 2) — the live-motivated half of what
    FW-133 leaves out (a true retraction, routed → pending, stays out of
    scope: 02 §2's freeze-at-routing pin forbids un-freezing substance).

    The OLD routing block is DISPLACED into ``history`` (``event:
    "routing"``, never destroyed — the same discipline ``reopen`` already
    gives ``resolution_note``), the new one is written, and BOTH
    host-side motions — retiring the OLD target's entry and compiling
    the NEW one — land in the SAME motion (RER2), through the shared
    retirement path (``_retirement_preflight``/``_retirement_host_phase``)
    so a reference-routed record's block drops exactly as
    ``graduate``/``supersede`` already do (RER6).

    Refuses (rc 1), each BEFORE any lock: the record is not ``routed``
    (``require_status``); the new destination resolves to the SAME file
    the record already targets — ``"already routed to X — nothing to
    change"`` (RER3, the idempotency refusal); ``--dest hook`` / ``--dest
    new-skill`` (RER4 — both are ``ONE_MOTION_UNROUTABLE``: rerouting
    INTO either is a fresh ``route`` decision on a fresh record, not a
    correction; rerouting AWAY FROM either is supported — the retirement
    half already exists for both)."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    try:
        _, record = require_status(home, record_id, ROUTED_ONLY, verb="reroute")
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
    bucket_dir = path.parent.parent
    old_routing = dict(record.routing or {})

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        warnings: list[str] = []
        # Both preflights run BEFORE the lock (§4.5): the OLD target's
        # retirement, and the NEW target's resolution.
        old_retire = _retirement_preflight(
            home, record, bucket_dir, warnings, user_claude_md=user_claude_md
        )
        resolved_dest = _resolve_destination(bucket_dir, record_id, dest)
        destination = resolved_dest.destination
        if destination in ONE_MOTION_UNROUTABLE:
            raise VerbError(
                f"reroute --dest {destination}: a one-motion destination — "
                "rerouting INTO it is a fresh `route` decision on a fresh "
                "record, not a correction (S-54)"
            )
        ref_name = resolved_dest.ref_name
        spec = _resolve_target(
            home,
            bucket_dir,
            record.scope,
            destination,
            ref_name,
            user_claude_md=user_claude_md,
            variant=resolved_dest.variant,
            rules_topic=resolved_dest.rules_topic,
            rules_paths=resolved_dest.rules_paths,
        )

        # RER3: the idempotency refusal, decided by resolved FILE
        # identity — the one comparison that cannot be fooled by two
        # differently-spelled `--dest` strings resolving to the same
        # target (a bare `claude-md` vs. an explicit qualifier-free one).
        old_target = (
            old_retire.spec.target if old_retire.spec is not None
            else old_retire.reference[0] if old_retire.reference is not None
            else None
        )
        new_target = (
            spec.target if spec.target is not None
            else reference_target_path(spec.refs_dir, spec.ref_name)
            if spec.destination == "reference" and spec.refs_dir is not None
            else None
        )
        if old_target is not None and old_target == new_target:
            raise VerbError(
                f"record {record_id} already routed to "
                f"{_routing_dest_label(old_routing)} — nothing to change"
            )

        by = by if by is not None else "human"
        # M-1 (U-verbs Phase 2 code gate r1): the commit subject used
        # to show the bare `destination` string, dropping any
        # qualifier (`claude-md:rules:<topic>`, `reference:<file>`) --
        # `_routing_dest_label` is the ONE place that vocabulary is
        # already spelled out (RER3's own same-destination refusal
        # message uses it for the OLD side; this is the NEW side).
        # `new-skill`/`hook` never reach here (ONE_MOTION_UNROUTABLE
        # already refused above), so only reference/claude-md carry a
        # qualifier worth naming.
        message_target = _routing_dest_label(
            {
                "destination": destination,
                "reference_file": spec.ref_name if destination == "reference" else None,
                "variant": spec.variant,
                "rules_topic": spec.rules_topic,
            }
        )
        message = f"self-learn: reroute {record_id} → {message_target}"
        routed_at = _now_iso()

        with _ledger_write(home), gitops.host_lock(spec.host_path, spec.mode):
            observed_hash = _observe_region_hash(spec)
            old_observed_hash = _observe_retirement_region(old_retire)

            touched = reroute_record(
                home,
                record_id,
                destination=destination,
                by=by,
                routed_at=routed_at,
                reference_file=ref_name if destination == "reference" else None,
                variant=spec.variant,
                rules_topic=spec.rules_topic,
                rules_paths=list(spec.rules_paths) if spec.rules_paths else None,
            )
            routed_record = Record.from_path(path)  # AS RESOLVED — routed_at now set

            # REC9: the compile record's SAME-commit prediction, same
            # shape route()'s own write leg uses — managed via the
            # generic helper, reference via the pure-transform predictor
            # (+ its pointer surface, when the scope carries one).
            if spec.destination in ("skill-md", "claude-md"):
                record_path = _write_compile_record_entry(
                    home, spec, observed_hash, by=message
                )
                if record_path is not None:
                    touched = touched + [record_path]
            elif spec.destination == "reference" and spec.refs_dir is not None:
                ref_path = reference_target_path(spec.refs_dir, spec.ref_name)
                if ref_path.name != FORBIDDEN_REFERENCE_BASENAME:
                    ref_observed = _observe_region_hash_at(ref_path, "reference")
                    ref_expected = _expected_reference_region(spec, routed_record, ref_path)
                    ref_record_path = _resync_region_entry(
                        home,
                        host_path=spec.host_path,
                        scope_kind=spec.scope_kind,
                        mode=spec.mode,
                        target=ref_path,
                        region_kind="reference",
                        expected=ref_expected,
                        observed_hash=ref_observed,
                        by=message,
                    )
                    if ref_record_path is not None:
                        touched = touched + [ref_record_path]
                    if spec.pointer_surface is not None:
                        ptr_observed = _observe_region_hash_at(spec.pointer_surface, "pointer")
                        ptr_expected = _expected_pointer_region(spec, ref_path)
                        ptr_record_path = _resync_region_entry(
                            home,
                            host_path=spec.host_path,
                            scope_kind=spec.scope_kind,
                            mode=spec.mode,
                            target=spec.pointer_surface,
                            region_kind="pointer",
                            expected=ptr_expected,
                            observed_hash=ptr_observed,
                            by=message,
                        )
                        if ptr_record_path is not None:
                            touched = touched + [ptr_record_path]

            # The OLD target's retirement, same-commit prediction — the
            # managed branch resyncs through the shared helper; the
            # reference branch through its own pure-transform predictor
            # (RER1/RER7).
            old_record_path = _write_retirement_compile_record(
                home, old_retire, old_observed_hash, by=message, skip_target=spec.target
            )
            if old_record_path is not None:
                touched = touched + [old_record_path]
            elif old_retire.reference is not None:
                old_ref_path, old_ref_spec = old_retire.reference
                old_ref_observed = _observe_region_hash_at(old_ref_path, "reference")
                old_ref_expected = _predicted_retired_reference_region(old_ref_path, record_id)
                old_ref_record_path = _resync_region_entry(
                    home,
                    host_path=old_ref_spec.host_path,
                    scope_kind=old_ref_spec.scope_kind,
                    mode=old_ref_spec.mode,
                    target=old_ref_path,
                    region_kind="reference",
                    expected=old_ref_expected,
                    observed_hash=old_ref_observed,
                    by=message,
                )
                if old_ref_record_path is not None:
                    touched = touched + [old_ref_record_path]

            staged, sha = _commit_ledger(home, touched, message, note)

            # M-1 (U-verbs Phase 2 code gate r1): `reroute` writes a
            # routing block via `ledger_ops.reroute_record` (its own
            # `set_routing` call) but, unlike `route`/`route_direct`,
            # never spooled a `route` event -- the AST guard
            # (test_route_observability.py, criterion 20) only walked
            # verbs.py, so it never saw `reroute_record`'s call in
            # ledger_ops.py either. Same placement pin as route()'s own
            # (criterion 19): immediately after the ledger commit
            # closes above, NOT at the end of the function, so a
            # host-phase failure below still leaves this event spooled
            # -- the ledger commit IS the routing (doc 13 §4.1).
            telemetry.spool_quiet(
                "route",
                record=record_id,
                destination=destination,
                scope=record.scope,
                by=by,
                variant=spec.variant,
            )

            post_notes: list[str] = []
            old_host_sha, old_host_repo = _retirement_host_phase(
                home,
                old_retire,
                record_id,
                note=note,
                message=message,
                warnings=warnings,
                post_notes=post_notes,
                skip_target=spec.target,
                user_push=not no_push,
            )
            compile_result, host_sha = _host_phase(
                home,
                spec,
                record_id,
                routed_record=routed_record,
                note=note,
                message=message,
                warnings=warnings,
                user_push=not no_push,
            )

        push = _push_ledger(home, no_push)
        host_push = None
        if not no_push and host_sha is not None and spec.mode == "git":
            host_push = gitops.push_if_remote(spec.host_path)
        if (
            not no_push
            and old_host_sha is not None
            and old_host_repo is not None
            and old_host_repo != spec.host_path
        ):
            gitops.push_if_remote(old_host_repo)
        return VerbResult(
            action="reroute",
            record_id=record_id,
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
            target=spec.target,
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
    # FW-51: refuses BEFORE any lock/mutation, naming the record's actual
    # status, when it is already terminal (rejected, or already
    # superseded/graduated) — the reject-then-graduate inversion this
    # unit closes.
    try:
        _, record = require_status(
            home, record_id, RESOLVABLE_STATUSES, verb="graduate"
        )
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
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
        )
        # U-hostmode M-3 (code gate r1 fold, REC12c): one lock discipline,
        # no exceptions — same shape as supersede()'s fix. The host lock
        # opens HERE, before the region hash is observed, and stays open
        # through the host write (only the push sits outside).
        # `_retirement_host_phase` (via `_host_phase`/`_remove_hook_script`)
        # re-acquires the SAME lock internally — a re-entrant pass-through
        # (`gitops._held_locks`), never a self-deadlock. A record with no
        # host presence to retire (pending, reference-routed) takes no
        # host lock at all.
        if retire.spec is not None:
            _graduate_host_lock = gitops.host_lock(retire.spec.host_path, retire.spec.mode)
        elif retire.removal is not None:
            _graduate_host_lock = gitops.host_lock(retire.removal[0], retire.removal[3])
        elif retire.reference is not None:
            _graduate_host_lock = gitops.host_lock(
                retire.reference[1].host_path, retire.reference[1].mode
            )
        else:
            _graduate_host_lock = contextlib.nullcontext()

        with _ledger_write(home), _graduate_host_lock:
            observed_hash = _observe_retirement_region(retire)

            message = f"self-learn: graduate {record_id}"
            touched = resolve_record(
                home,
                record_id,
                "superseded",
                superseded_by="canon",
                note=note,
                verb="graduate",
            )
            # U-hostmode REC1/REC9: the graduated record's own doc-target
            # entry drops out of the compile at the host phase below — the
            # compile record must be kept in sync with that rewrite (see
            # `_write_retirement_compile_record`'s docstring for the bug
            # this closes), inside this SAME ledger commit.
            record_path = _write_retirement_compile_record(
                home, retire, observed_hash, by=f"graduate {record_id}"
            )
            if record_path is not None:
                touched = touched + [record_path]
            elif retire.reference is not None:
                # U-verbs S-54 (RER6/RER7): same same-commit-prediction
                # shape as the managed branch above — `_write_retirement_
                # compile_record` only ever covers `retire.spec`, so a
                # reference retirement's compile-record entry is resynced
                # here, predicted via the SAME pure text transform the
                # real removal (host phase, below) applies.
                ref_path, ref_spec = retire.reference
                ref_observed = _observe_region_hash_at(ref_path, "reference")
                ref_expected = _predicted_retired_reference_region(ref_path, record_id)
                ref_record_path = _resync_region_entry(
                    home,
                    host_path=ref_spec.host_path,
                    scope_kind=ref_spec.scope_kind,
                    mode=ref_spec.mode,
                    target=ref_path,
                    region_kind="reference",
                    expected=ref_expected,
                    observed_hash=ref_observed,
                    by=f"graduate {record_id}",
                )
                if ref_record_path is not None:
                    touched = touched + [ref_record_path]
            elif retire.removal is not None:
                # D-3 completion (code gate r1 fold, coordinator
                # ruling 2026-08-28): same shape as `supersede`'s
                # own hook-removal leg — `_write_retirement_compile_
                # record` only ever covers `retire.spec` (a managed
                # drop); a hook-routed record's script disappearing
                # at the host phase below needs its record entry
                # predictively DELETED here too, or a stale WRITE
                # entry misreads the next legitimate route to this
                # same script path as `edited`.
                host_repo, script_abs, _rel, removal_mode = retire.removal
                removal_record_path = _resync_region_entry(
                    home,
                    host_path=host_repo,
                    scope_kind=_hook_scope_kind(record),
                    mode=removal_mode,
                    target=script_abs,
                    region_kind="script",
                    expected=None,
                    observed_hash=None,
                    delete=True,
                    by=f"graduate {record_id}",
                )
                if removal_record_path is not None:
                    touched = touched + [removal_record_path]
            staged, sha = _stage_and_commit(home, touched, message, note)

            post_notes: list[str] = []
            host_sha, host_repo = _retirement_host_phase(
                home,
                retire,
                record_id,
                note=note,
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
) -> VerbResult:
    """Corrective supersession (08 §1 pin): mark ``old`` superseded by
    ``new`` (which must exist). Commit: ``self-learn: supersede lrn-old →
    lrn-new``. When the old record was ROUTED to a managed target this
    verb is canon-touching (doc 13 §4): its entry must drop, so after the
    ledger commit the host phase recompiles the target and commits the
    host. A pending old record stays a single ledger commit. A
    reference-routed old record's entry drops too (U-verbs S-54 —
    references are no longer append-only for their own lifetime)."""
    home = Path(home)
    if old_id == new_id:
        raise VerbError("a record cannot supersede itself")
    old_path = find_record_path(home, old_id)  # pending OR routed flavor
    find_record_path(home, new_id)  # the replacement must exist
    _scan_or_refuse([old_path], note)
    warnings = _orphaned_followup_warning(old_path, old_id)
    # FW-51: status/cycle refusals — BEFORE any lock/mutation, naming the
    # record's actual status. Existence of both ids is already confirmed
    # above (a genuinely missing id stays LedgerOpsError/64, unwrapped —
    # test_replacement_must_exist pins this); from here the only failure
    # mode is a STATUS or CYCLE refusal, exit 1 like every other
    # resolution-verb refusal.
    try:
        _, old_record = require_status(
            home, old_id, RESOLVABLE_STATUSES, verb="supersede"
        )
        require_status(home, new_id, RESOLVABLE_STATUSES, verb="supersede")
        supersede_cycle_check(home, old_id, new_id)
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        # (c) PRE-FLIGHT the recompile target when this drops a live entry
        # — or the hook script this retires (M3-4).
        spec: TargetSpec | None = None
        removal: tuple[Path, Path, str, str] | None = None
        reference: tuple[Path, TargetSpec] | None = None
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
                    # A2 §4.4B note: variant/rules_topic only — see the
                    # matching comment in _retirement_preflight.
                    variant=routing.get("variant"),
                    rules_topic=routing.get("rules_topic"),
                )
            elif destination == "hook":
                removal = _hook_script_location(home, old_record, warnings)
            elif destination == "reference":
                # U-verbs S-54 (RER6): the same reference-retirement
                # preflight `_retirement_preflight` runs for `graduate` —
                # `supersede` pre-flights its own doc-target/hook cleanup
                # by hand rather than through that shared dataclass (a
                # pre-existing duplication this unit does not collapse),
                # so the third leg is added here in the SAME shape.
                ref_spec = _resolve_target(
                    home,
                    old_path.parent.parent,
                    old_record.scope,
                    "reference",
                    routing.get("reference_file"),
                    user_claude_md=user_claude_md,
                    variant=routing.get("variant"),
                    rules_topic=routing.get("rules_topic"),
                )
                # Same invariant as `_retirement_preflight`'s reference
                # branch: `_resolve_target`'s `destination == "reference"`
                # arm always resolves a concrete `refs_dir` before
                # returning -- never None here.
                assert ref_spec.refs_dir is not None
                reference = (
                    reference_target_path(ref_spec.refs_dir, ref_spec.ref_name),
                    ref_spec,
                )

        # U-hostmode M-3 (code gate r1 fold, REC12c): one lock discipline,
        # no exceptions — the host lock opens HERE, before the region
        # hash is observed, and stays open through the host write, the
        # same shape route()/route_direct() use (only the push sits
        # outside). `_host_phase`/`_remove_hook_script` re-acquire the
        # SAME lock internally; `gitops._held_locks` makes that a
        # re-entrant pass-through, never a self-deadlock. A record with
        # no host presence to retire (pending, reference-routed) takes
        # no host lock at all.
        if spec is not None:
            _supersede_host_lock = gitops.host_lock(spec.host_path, spec.mode)
        elif removal is not None:
            _supersede_host_lock = gitops.host_lock(removal[0], removal[3])
        elif reference is not None:
            _supersede_host_lock = gitops.host_lock(reference[1].host_path, reference[1].mode)
        else:
            _supersede_host_lock = contextlib.nullcontext()

        with _ledger_write(home), _supersede_host_lock:
            observed_hash = _observe_region_hash(spec) if spec is not None else None

            # (d) LEDGER phase (locked from the first mutation through the
            # commit — :func:`_ledger_write`).
            message = f"self-learn: supersede {old_id} → {new_id}"
            touched = supersede_record(home, old_id, new_id, note=note)
            # U-hostmode REC1/REC9: the superseded record's own doc-target
            # entry drops out of the compile at the host phase below — kept
            # in sync with that rewrite inside this SAME ledger commit (the
            # bug this closes: `_write_retirement_compile_record`'s
            # docstring).
            if spec is not None:
                record_path = _write_compile_record_entry(
                    home, spec, observed_hash, by=f"supersede {old_id} → {new_id}"
                )
                if record_path is not None:
                    touched = touched + [record_path]
            elif reference is not None:
                # U-verbs S-54 (RER6/RER7): same same-commit prediction
                # shape as `graduate`'s reference leg — predicted via the
                # SAME pure text transform the real removal (host phase,
                # below) applies.
                ref_path, ref_spec = reference
                ref_observed = _observe_region_hash_at(ref_path, "reference")
                ref_expected = _predicted_retired_reference_region(ref_path, old_id)
                ref_record_path = _resync_region_entry(
                    home,
                    host_path=ref_spec.host_path,
                    scope_kind=ref_spec.scope_kind,
                    mode=ref_spec.mode,
                    target=ref_path,
                    region_kind="reference",
                    expected=ref_expected,
                    observed_hash=ref_observed,
                    by=f"supersede {old_id} → {new_id}",
                )
                if ref_record_path is not None:
                    touched = touched + [ref_record_path]
            elif removal is not None:
                # D-3 completion (code gate r1 fold, coordinator
                # ruling 2026-08-28): a hook-routed record's script
                # is about to disappear at the host phase below —
                # predictively DELETE its record entry in this SAME
                # ledger commit (same shape the `spec is not None`
                # branch above already uses for a managed drop; H-2
                # already tolerates the host phase lagging the
                # ledger — a failed removal there is the pre-existing
                # "stale, never lost" gap `recompile` repairs, which
                # now ALSO resyncs this exact key, see its hook-
                # removal-repair leg). A stale WRITE entry left
                # behind here would misread the next legitimate
                # write to this same script path as `edited`.
                host_repo, script_abs, _rel, removal_mode = removal
                removal_record_path = _resync_region_entry(
                    home,
                    host_path=host_repo,
                    scope_kind=_hook_scope_kind(old_record),
                    mode=removal_mode,
                    target=script_abs,
                    region_kind="script",
                    expected=None,
                    observed_hash=None,
                    delete=True,
                    by=f"supersede {old_id} → {new_id}",
                )
                if removal_record_path is not None:
                    touched = touched + [removal_record_path]
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
                    message=message,
                    warnings=warnings,
                    user_push=not no_push,
                )
            elif removal is not None:
                host_sha = _remove_hook_script(
                    home, removal, old_id, note, warnings, post_notes
                )
            elif reference is not None:
                host_sha = _retire_reference_host_phase(
                    home, reference, old_id, note=note, warnings=warnings
                )

        # (f) push ledger, then host (both has_remote-guarded).
        push = None if no_push else gitops.push_if_remote(home)
        host_push = None
        host_repo = (
            spec.host_path if spec is not None
            else removal[0] if removal is not None
            else reference[1].host_path if reference is not None
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
    # FW-51 M-3 (code gate r1): followup_done's own docstring already
    # said "Clear a ROUTED record's follow-up" — but nothing enforced
    # it. Measured: route with a follow_up -> graduate (status
    # superseded, follow_up SURVIVES the transition, graduate only
    # warns) -> followup_done still succeeded and committed, clearing a
    # follow-up open_followups() had already stopped calling "open".
    # Gated on STATUS here, same as every other resolution-adjacent
    # verb — the "no open follow-up" check below stays SECOND, since a
    # routed record can still legitimately have no follow_up at all.
    try:
        _, record = require_status(
            home, record_id, ROUTED_ONLY, verb="followup-done"
        )
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
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
    if event.get("record") != record_id:
        raise VerbError(
            f"event {event_ref} was raised against {event.get('record')!r}, "
            f"not {record_id!r} — confirm it against the record it names"
        )
    path = find_record_path(home, record_id)
    _scan_or_refuse([path], note)
    try:
        _, record = require_status(
            home,
            record_id,
            ROUTED_ONLY,
            verb="confirm-recurrence",
            reason="recurrences confirm against LIVE routed coverage (11 §2.2)",
        )
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
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
    try:
        _, record = require_status(
            home,
            record_id,
            ROUTED_ONLY,
            verb="confirm-held",
            reason="only live routed rules can be confirmed as holding",
        )
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
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


#: U-dismiss §5: the closed ``--why`` enum for ``dismiss-suspect`` — the
#: analyst's x-axis (``basis × why`` contingency table, §2.4/§5 of the
#: spec). argparse ``choices=`` enforces this at the CLI layer (exit 2,
#: before anything is read); the record-layer validator
#: (``records._validate_dismissal``) requires only that ``why`` be
#: non-empty text, so a record written under an older/smaller enum never
#: retroactively fails validation if this list grows (the ``_BASIS_LABELS``
#: lesson, ``ui/models.py:858-863``, applied to the reason side).
DISMISS_REASONS = (
    "rule-followed",
    "unrelated",
    "duplicate",
    "misattributed",
    "other",
)


def dismiss_suspect(
    home: Path | str,
    record_id: str,
    *,
    event_ref: str,
    why: str,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """The third door out of ``recurrence_suspects`` (11 §2.2, U-dismiss
    §1): a human judged a recurrence-suspect telemetry claim to be a
    matcher false-positive, not a recurrence. Append to the record's
    append-only ``dismissed_suspects:`` list, copying the minimal facts
    (ts, origin, basis) OUT of the telemetry event named by ``event_ref``
    (the event's ``nonce``) — unlike ``recurrences[]``, ``ref`` is
    REQUIRED here (§4.3): without the nonce the entry clears nothing and
    means nothing. The suspect event itself is never touched — append-only
    telemetry, preserved as analyst fuel. Commit:
    ``self-learn: suspect dismissed on lrn-…``."""
    home = Path(home)
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
    if event.get("record") != record_id:
        raise VerbError(
            f"event {event_ref} was raised against {event.get('record')!r}, "
            f"not {record_id!r} — dismiss it against the record it names"
        )
    path = find_record_path(home, record_id)
    _scan_or_refuse([path], note)
    try:
        _, record = require_status(
            home,
            record_id,
            ROUTED_ONLY,
            verb="dismiss-suspect",
            reason="suspects only exist against LIVE routed coverage (11 §2.2)",
        )
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
    if any(r.get("ref") == event_ref for r in record.recurrences):
        raise VerbError(
            f"event {event_ref} is already confirmed on {record_id} — "
            "cannot dismiss a suspect that was confirmed as a real "
            "recurrence"
        )
    if any(d.get("ref") == event_ref for d in record.dismissed_suspects):
        raise VerbError(
            f"event {event_ref} is already dismissed on {record_id}"
        )
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        entry = {
            "ref": event_ref,
            "ts": event.get("ts"),
            "why": why,
            "origin": event.get("origin"),
            "basis": event.get("basis"),
            "dismissed_at": _now_iso()[:10],
        }
        if note is not None:
            entry["note"] = note
        try:
            record.append_dismissed_suspect(entry)
        except RecordError as exc:
            raise VerbError(str(exc)) from exc
        message = f"self-learn: suspect dismissed on {record_id}"
        with _ledger_write(home):
            record.write(path)
            staged, sha = _stage_and_commit(home, [path], message, note)
        push = _push_ledger(home, no_push)
        return VerbResult(
            action="dismiss-suspect",
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
        # U-hostmode M-5 (code gate r1 fold, PLAIN10): a plain host has no
        # `git status` to consult at all — `unpushed_commits` is a raw
        # git subprocess, so calling it against a plain host's directory
        # would either misfire against whatever repo happens to be an
        # ancestor of it, or fail outright. Skip SILENTLY (never a print
        # — a plain host publishing nothing to push is the expected,
        # every-run state, not an anomaly worth a line) and never touch
        # `unpushed_commits` for it.
        if host_mode(home, repo) == "plain":
            continue
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
    adopt: Path | str | None = None,
) -> RecompileResult:
    """The doc-13 drift repair (H-2: recompile is always safe and repairs
    any two-phase interruption). For every ROUTED record, recompute each
    managed target — skill-md files, project/skill-root claude-md files,
    AND the user-scope CLAUDE.md, which is a first-class PLAIN host now
    (§4.8.1) and goes through the SAME general repair as any other
    plain/git host, never a dotfiles-guarded flow (USER2/CHEZ0) — and
    RE-APPEND every reference-routed record to its references file, then
    commit any HOST whose file changed (pinned subject ``self-learn:
    recompile <relative target>``).

    ``adopt`` (REC11, U-hostmode §4.5a): when given, the ON-DISK managed
    region at that resolved target path is re-recorded as authoritative
    IN THE COMPILE RECORD before this run's own soundness check — the one
    human decision an ``edited``/``unknown provenance`` refusal names.
    Adopting writes and commits ONLY the record entry; it never changes
    the target's bytes. ``--force`` is deliberately not offered anywhere
    in this path.

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
    hook_work: list[tuple[Record, Path, Path, str, str]] = []  # record, host, abs, rel, mode
    hook_removals: list[tuple[Record, tuple[Path, Path, str, str]]] = []  # m-4
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
            # M-B: retired is the negation of domain.is_canon_live — the
            # SAME routed-and-not-superseded predicate compilers._eligible
            # and report's routed_live accumulation use, never a third
            # inline definition of "is this routing still live".
            retired = not domain.is_canon_live(record)
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
                    host_repo, script_abs, rel, hook_mode = removal
                    hook_work.append(
                        (record, host_repo, script_abs, rel, hook_mode)
                    )
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
                entry = ref_work.setdefault((spec.host_path, probe), (spec, []))
                entry[1].append(record)
                continue
            specs.setdefault((spec.host_path, spec.target), spec)

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        touched_hosts: list[Path] = []
        # N-6 (code gate r2 fold): every automatic drift-resync entry
        # written below (managed, reference, pointer, hook re-apply,
        # hook removal-repair) is ACCUMULATED here instead of committed
        # on the spot — one changed target used to mean one standalone
        # ledger commit, so a large repair run could emit many resync
        # commits in a single invocation. ONE combined commit fires at
        # the end of this function instead (right before the push loop),
        # covering everything this run touched. `--adopt`'s own commit
        # (just below) is a SEPARATE, deliberate single-target human
        # action — never batched in here.
        resync_touched: list[Path] = []
        # REC11: an --adopt target re-records the ON-DISK region as
        # authoritative before this run's own soundness check runs — the
        # write is mode-agnostic (REC4: the record covers git hosts too),
        # so it is resolved once, ahead of the mode split below.
        adopt_target = Path(adopt).resolve() if adopt is not None else None
        adopt_matched = False
        for (host_repo, target), spec in sorted(
            specs.items(), key=lambda kv: str(kv[0][1])
        ):
            region_kind = _region_kind_for(spec)
            if (
                adopt_target is not None
                and region_kind is not None
                and target.resolve() == adopt_target
            ):
                adopt_matched = True
                try:
                    text = target.read_text(encoding="utf-8")
                    region = compiled.region_bytes(text, region_kind)
                except (
                    OSError,
                    UnicodeDecodeError,
                    compiled.CompiledRecordError,
                ) as exc:
                    result.entries.append(
                        RecompileEntry(target=target, changed=False, skipped=str(exc))
                    )
                    result.warnings.append(f"{target}: --adopt: {exc}")
                    continue
                if region is None:
                    result.warnings.append(
                        f"{target}: --adopt: no {region_kind} region on disk "
                        "— nothing to adopt"
                    )
                else:
                    slug = host_slug(home, spec.host_path, scope_kind=spec.scope_kind)
                    host_label = (
                        "(user scope — ~/.claude)"
                        if spec.scope_kind == "user"
                        else str(spec.host_path)
                    )
                    key = compiled.region_key(spec.host_path, target)
                    with _ledger_write(home):
                        record_path = compiled.adopt_entry(
                            home,
                            slug,
                            key,
                            region=region_kind,
                            observed_hash=compiled.sha256_hex(region),
                            nbytes=len(region),
                            host=host_label,
                            mode=spec.mode,
                        )
                        _commit_ledger(
                            home,
                            [record_path],
                            f"self-learn: recompile --adopt {key}",
                        )
                    # target is non-None here: adopt_matched only sets
                    # when region_kind is not None, which _region_kind_for
                    # only returns for a spec carrying a real target.
                    assert target is not None
                    result.entries.append(
                        RecompileEntry(target=target, changed=True, commit_sha=None)
                    )
                    # REC11: adopting means the ON-DISK region — just
                    # re-recorded above as authoritative — IS the new
                    # reference; falling through into the render leg
                    # below would immediately re-derive canonical
                    # content from the ledger and overwrite the very
                    # bytes this block just adopted, leaving the
                    # compile record's `sha256` pointing at bytes the
                    # target no longer holds (a real bug this fix
                    # closes: confirmed by writing a hand edit, running
                    # `recompile --adopt`, and observing the entry's
                    # `sha256` no longer matched the post-call on-disk
                    # region before this `continue` was added). One
                    # `recompile --adopt <target>` call fully settles
                    # THAT target; other targets in the same run are
                    # untouched by this `continue` and still recompile
                    # normally below.
                    continue
            if spec.mode != "git":
                # U-hostmode §4.8.1: every plain host (user scope included)
                # repairs through the SAME general path — no
                # dotfiles-management leg, no
                # special-cased user branch (USER2/CHEZ0). The soundness
                # check `_resolve_target` skipped (`check_dirty=False`)
                # runs HERE instead: plain mode has no `git status` to
                # consult, so the compile record is the only instrument
                # that can see a committed-equivalent hand edit
                # (REC2/REC4), and recompile must never guess past one
                # (H-3) — `--adopt`, just above, is the named repair.
                if region_kind is not None:
                    try:
                        _abort_if_unsound(
                            home,
                            spec.host_path,
                            spec.mode,
                            target,
                            region_kind,
                            scope_kind=spec.scope_kind,
                            spec=spec,
                        )
                    except DirtyTargetError as exc:
                        result.entries.append(
                            RecompileEntry(target=target, changed=False, skipped=str(exc))
                        )
                        result.warnings.append(f"{target}: {exc}")
                        continue
                # RESIDUAL-DEFECT FIX (2026-08-28, coordinator ruling on
                # the U-hostmode Phase 1 build): observe the region hash
                # BEFORE the render, so a change CAN be re-synced below.
                # Bug this closes — a plain recompile past a "clean"
                # verdict (e.g. right after `--adopt`, or any target
                # whose record was never written by this leg to begin
                # with) rendered canonical content whenever it differed
                # from disk, same as always, but never told the compile
                # record about it: the record kept whatever `sha256` it
                # already held while the file moved on, so the NEXT
                # verdict computation compared a stale record against
                # fresh disk content and read `edited` — a false refusal
                # on content this very tool just wrote. Confirmed by
                # writing a hand edit, `recompile --adopt`ing it (which
                # settles the record to the hand-edited bytes), then
                # running a second, unadopted `recompile`: the render
                # correctly restored canonical content, but the record
                # still pointed at the adopted (now-overwritten) hash —
                # a THIRD `recompile` verdicted `edited` against content
                # that was, in fact, exactly canonical.
                observed_hash = (
                    _observe_region_hash(spec) if region_kind is not None else None
                )
                compile_result, host_sha = _host_phase(
                    home,
                    spec,
                    "recompile",
                    routed_record=None,
                    note=None,
                    message=f"self-learn: recompile {target}",
                    warnings=result.warnings,
                    user_push=not no_push,
                )
                changed = bool(getattr(compile_result, "changed", False))
                if changed and region_kind is not None:
                    # The render just made disk and the ledger's
                    # canonical content agree — re-sync the record to
                    # match in the SAME breath, under the ledger's own
                    # lock, so no verdict computed after this point can
                    # ever see the record and disk disagree because of
                    # a render THIS TOOL performed. A no-op render
                    # (`changed=False`, the common "already clean" case)
                    # skips this entirely — the record was already
                    # truthful, and writing a no-op ledger commit would
                    # be its own unwanted divergence from REC9's "the
                    # record rides its OWN resolution's commit" shape.
                    with _ledger_write(home):
                        record_path = _write_compile_record_entry(
                            home, spec, observed_hash, by=f"recompile {target}"
                        )
                        # U-hostmode M-10 (code gate r1 fold): §4.5/gate
                        # B-3 rejected a second ledger commit under the
                        # subject `self-learn: compile record …` — that
                        # shape stays rejected. N-6 (code gate r2 fold):
                        # this write's own commit is now BATCHED (see
                        # `resync_touched` above), not fired here.
                        if record_path is not None and record_path not in resync_touched:
                            resync_touched.append(record_path)
                result.entries.append(
                    RecompileEntry(
                        target=target,
                        changed=changed,
                        commit_sha=host_sha,
                    )
                )
                if host_sha is not None and host_repo not in touched_hosts:
                    touched_hosts.append(host_repo)
                continue
            if target.is_file() and gitops.paths_dirty(host_repo, target):
                result.entries.append(
                    RecompileEntry(target=target, changed=False, skipped="dirty")
                )
                result.warnings.append(
                    f"{target}: uncommitted changes — commit/stash, then re-run"
                )
                continue
            # D-2 (code gate r1 fold): observe the region hash BEFORE
            # the render, same as the plain leg below — the compile
            # record's own resync (after a successful commit) needs the
            # PRE-render observation, not a later re-read (REC13's own
            # reasoning, mode-agnostic: `_flock_lock`'s own docstring —
            # "the compile record's `based_on_sha256` is the state THIS
            # write is based on, never a later re-read").
            observed_hash = (
                _observe_region_hash(spec) if region_kind is not None else None
            )
            # compile→commit under the HOST's lock (see :func:`_host_phase`:
            # the compile writes the managed file into the host worktree, so
            # a racing autostash there would stash it away mid-flight).
            with gitops.commit_lock(host_repo):
                try:
                    compile_result, host_paths = _apply_target(
                        home, spec, None, notes=result.warnings
                    )
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
            # D-2 (code gate r1 fold): re-sync the compile record here
            # too — `edited` refuses in BOTH modes (REC2/REC4), so a
            # git-mode render leaving the record stale is the exact same
            # latent false-refusal channel the plain leg's own
            # RESIDUAL-DEFECT FIX (above) closed for plain hosts. A
            # SEPARATE standalone ledger commit (never riding the HOST's
            # own commit just made — that landed in a DIFFERENT repo),
            # same subject shape M-10 established for the plain leg.
            if region_kind is not None:
                with _ledger_write(home):
                    record_path = _write_compile_record_entry(
                        home, spec, observed_hash, by=f"recompile {target}"
                    )
                    # N-6 (code gate r2 fold): batched, not committed here
                    # — see `resync_touched` above.
                    if record_path is not None and record_path not in resync_touched:
                        resync_touched.append(record_path)
            result.entries.append(
                RecompileEntry(target=target, changed=True, commit_sha=sha)
            )
            if host_repo not in touched_hosts:
                touched_hosts.append(host_repo)

        if adopt_target is not None and not adopt_matched:
            result.warnings.append(
                f"{adopt_target}: --adopt: no routed managed target at this "
                "path — nothing adopted"
            )

        # Reference targets: re-append every routed record (idempotent per
        # record id), commit the file ONCE if anything landed; ALSO the
        # backfill mechanism (U-pointer §3.7): every host visited here
        # already resolved `spec.pointer_surface` for free, so the R14
        # shape — every entry already appended, `applied` False, the OLD
        # code `continue`d past the whole entry — is exactly where the
        # pointer write now happens instead of being silently skipped.
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
            # §3.7 step 1: a dirty pointer surface is skipped LOUDLY,
            # BEFORE the lock, but the record appends below still
            # proceed — the two repairs are independent, and a human's
            # uncommitted SKILL.md edit is no reason to withhold canon
            # from LEARNINGS.md.
            skip_pointer = False
            if (
                spec.pointer_surface is not None
                and spec.pointer_surface.is_file()
                and gitops.paths_dirty(host_repo, spec.pointer_surface)
            ):
                result.entries.append(
                    RecompileEntry(
                        target=spec.pointer_surface, changed=False, skipped="dirty"
                    )
                )
                result.warnings.append(
                    f"{spec.pointer_surface}: uncommitted changes — "
                    "commit/stash, then re-run"
                )
                skip_pointer = True
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
            # D-3 (code gate r1 fold): observe the region hashes BEFORE
            # this loop's first mutation of either file, same reasoning
            # as D-2 (REC13: `based_on_sha256` is the state THIS write
            # is based on, never a later re-read). `probe` is the
            # reference file; `spec.pointer_surface` may be absent.
            ref_observed_before = _observe_region_hash_at(probe, "reference")
            ptr_observed_before = (
                _observe_region_hash_at(spec.pointer_surface, "pointer")
                if spec.pointer_surface is not None
                else None
            )
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

                # §3.7 step 2: the pointer write — this IS the R14 backfill.
                # `UnicodeDecodeError` is a `ValueError`, not an `OSError`
                # (measured, §8-X13): omitting it here lets one undecodable
                # SKILL.md propagate out of this loop, out of `recompile()`
                # entirely, and abort the WHOLE nightly repair batch (r2
                # BLOCKER 2) — every host after the bad one silently
                # unrepaired. `create` is True only at project scope, same
                # posture as the route path.
                pointer_changed = False
                if spec.pointer_surface is not None and not skip_pointer:
                    try:
                        pointer = apply_pointer(
                            spec.pointer_surface,
                            probe,
                            label=POINTER_LABELS[spec.scope_kind],
                            create=spec.scope_kind == "project",
                            names_base=_pointer_names_base(home, spec),
                        )
                    except (CompileError, OSError, UnicodeDecodeError) as exc:
                        result.warnings.append(f"{spec.pointer_surface}: {exc}")
                    else:
                        pointer_changed = pointer.changed

                if not applied and not pointer_changed:
                    if not failed:
                        result.entries.append(
                            RecompileEntry(target=probe, changed=False)
                        )
                    continue

                # §3.7 step 3: the two files get ONE commit each, both
                # inside this same lock — the append commit is byte-for-
                # byte what it was before this unit; the pointer commit is
                # new. `touched_hosts` (the push loop's own iterable) gets
                # `host_repo` on EITHER commit — a leg that skips this
                # would leave the whole backfill committed and never
                # pushed (r2 NOTE 9, criterion E8).
                if applied:
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

                if pointer_changed:
                    pointer_surface = spec.pointer_surface
                    assert pointer_surface is not None
                    gitops.stage(host_repo, [pointer_surface])
                    prel = pointer_surface.relative_to(host_repo)
                    psha = gitops.commit(
                        host_repo,
                        f"self-learn: pointer {prel}",
                        paths=[pointer_surface],
                    )
                    result.entries.append(
                        RecompileEntry(
                            target=pointer_surface,
                            changed=True,
                            commit_sha=psha,
                        )
                    )
                    if host_repo not in touched_hosts:
                        touched_hosts.append(host_repo)

            # D-3 (code gate r1 fold): resync the compile record for the
            # `reference`/`pointer` region kinds too — mirrors D-2's fix
            # for `managed` targets, closing the same latent
            # false-`edited`-refusal channel (REC2/REC4) for these two
            # kinds. Unlike `route()` (fully predictive: one record, one
            # ledger commit, never-yet-written bytes), `recompile` here
            # writes for REAL, in a loop over MANY records, before any
            # resync happens — so this reads the ACTUAL post-write bytes
            # off disk rather than predicting them. Each resync is its
            # own standalone ledger commit (never riding the host's own
            # commit just made above — that landed in a DIFFERENT repo),
            # same subject convention M-10/D-2 established.
            if applied:
                try:
                    ref_expected = compiled.region_bytes(
                        probe.read_text(encoding="utf-8"), "reference"
                    )
                except (OSError, UnicodeDecodeError, compiled.CompiledRecordError):
                    ref_expected = None
                if ref_expected is not None:
                    with _ledger_write(home):
                        ref_record_path = _resync_region_entry(
                            home,
                            host_path=spec.host_path,
                            scope_kind=spec.scope_kind,
                            mode=spec.mode,
                            target=probe,
                            region_kind="reference",
                            expected=ref_expected,
                            observed_hash=ref_observed_before,
                            by=f"recompile {probe}",
                        )
                        # N-6 (code gate r2 fold): batched, see
                        # `resync_touched` above.
                        if ref_record_path is not None and ref_record_path not in resync_touched:
                            resync_touched.append(ref_record_path)
            if pointer_changed:
                pointer_surface = spec.pointer_surface
                assert pointer_surface is not None
                try:
                    ptr_expected = compiled.region_bytes(
                        pointer_surface.read_text(encoding="utf-8"), "pointer"
                    )
                except (OSError, UnicodeDecodeError, compiled.CompiledRecordError):
                    ptr_expected = None
                if ptr_expected is not None:
                    with _ledger_write(home):
                        ptr_record_path = _resync_region_entry(
                            home,
                            host_path=spec.host_path,
                            scope_kind=spec.scope_kind,
                            mode=spec.mode,
                            target=pointer_surface,
                            region_kind="pointer",
                            expected=ptr_expected,
                            observed_hash=ptr_observed_before,
                            by=f"recompile {probe}",
                        )
                        # N-6 (code gate r2 fold): batched, see
                        # `resync_touched` above.
                        if ptr_record_path is not None and ptr_record_path not in resync_touched:
                            resync_touched.append(ptr_record_path)

        # Hook scripts: re-apply the APPROVED bytes where missing, edited,
        # or stripped of the executable bit (a hook two-phase interruption
        # is exactly a missing script — H-2's repair must cover it).
        for record, host_repo, script_abs, rel, hook_mode in sorted(
            hook_work, key=lambda item: str(item[2])
        ):
            # U-hostmode: a plain host has no `git status` to consult —
            # the dirty gate is git-only, unchanged for git (UN2/UN3).
            if (
                hook_mode == "git"
                and script_abs.is_file()
                and gitops.paths_dirty(host_repo, script_abs)
            ):
                result.entries.append(
                    RecompileEntry(target=script_abs, changed=False, skipped="dirty")
                )
                result.warnings.append(
                    f"{script_abs}: uncommitted changes — commit/stash, then re-run"
                )
                continue
            sha = None
            # D-3 completion (code gate r1 fold, coordinator ruling
            # 2026-08-28): observe BEFORE the write, same reasoning as
            # every other resync in this function (REC13: `based_on_
            # sha256` is the state THIS write is based on).
            script_observed_before = _observe_region_hash_at(script_abs, "script")
            # `host_lock(path, "git")` is byte-identical to `commit_lock`'s
            # own path (UN8) — this widens to plain without moving the
            # git-mode lock at all.
            with gitops.host_lock(host_repo, hook_mode):  # ledger→host order
                apply_result = _write_hook_script(
                    script_abs, (record.routing or {})["hook"]["script"]
                )
                if not apply_result.changed:
                    result.entries.append(
                        RecompileEntry(target=script_abs, changed=False)
                    )
                    continue
                if hook_mode == "git":
                    gitops.stage(host_repo, [script_abs])
                    sha = gitops.commit(
                        host_repo,
                        f"self-learn: recompile {rel}",
                        paths=[script_abs],
                    )
            # D-3 completion: resync the record to the APPROVED bytes
            # this leg just (re-)applied — a standalone ledger commit,
            # same subject convention M-10/D-2/D-3 established, never
            # riding the host's own commit just made above (a DIFFERENT
            # repo).
            script_expected = (record.routing or {})["hook"]["script"].encode("utf-8")
            with _ledger_write(home):
                script_record_path = _resync_region_entry(
                    home,
                    host_path=host_repo,
                    scope_kind=_hook_scope_kind(record),
                    mode=hook_mode,
                    target=script_abs,
                    region_kind="script",
                    expected=script_expected,
                    observed_hash=script_observed_before,
                    by=f"recompile {script_abs}",
                )
                # N-6 (code gate r2 fold): batched, see `resync_touched`
                # above.
                if script_record_path is not None and script_record_path not in resync_touched:
                    resync_touched.append(script_record_path)
            result.entries.append(
                RecompileEntry(target=script_abs, changed=True, commit_sha=sha)
            )
            if sha is not None and host_repo not in touched_hosts:
                touched_hosts.append(host_repo)

        # m-4: RETIRED hook records whose script still exists — an
        # interrupted removal (or a pre-fix retirement) left the guard on
        # disk. Same removal flow as the verbs; the un-registration
        # reminder lands in warnings so a repair run is never silent.
        for record, removal in sorted(
            hook_removals, key=lambda item: str(item[1][1])
        ):
            host_repo, script_abs, rel, removal_mode = removal
            if removal_mode == "git" and gitops.paths_dirty(host_repo, script_abs):
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
            # D-3 completion (code gate r1 fold, coordinator ruling
            # 2026-08-28): `_remove_hook_script` returns `None` for
            # THREE different reasons (already absent, a successful
            # plain-mode unlink, and a genuine failure) — `sha is not
            # None` cannot distinguish "removed" from "removal failed".
            # `script_abs.is_file()` after the call is the reliable
            # signal: only clear the record entry when the script is
            # ACTUALLY gone, never on a failed removal that left it in
            # place (that would wrongly hide a still-present script
            # behind a deleted entry).
            if not script_abs.is_file():
                with _ledger_write(home):
                    removal_record_path = _resync_region_entry(
                        home,
                        host_path=host_repo,
                        scope_kind=_hook_scope_kind(record),
                        mode=removal_mode,
                        target=script_abs,
                        region_kind="script",
                        expected=None,
                        observed_hash=None,
                        delete=True,
                        by=f"recompile {script_abs}",
                    )
                    # N-6 (code gate r2 fold): batched, see
                    # `resync_touched` above.
                    if removal_record_path is not None and removal_record_path not in resync_touched:
                        resync_touched.append(removal_record_path)
            result.entries.append(
                RecompileEntry(
                    target=script_abs, changed=sha is not None, commit_sha=sha
                )
            )
            if sha is not None and host_repo not in touched_hosts:
                touched_hosts.append(host_repo)

        # N-6 (code gate r2 fold): the ONE combined resync commit for
        # this ENTIRE invocation — every write accumulated above
        # (managed, reference, pointer, hook re-apply, hook removal-
        # repair; `--adopt`'s own commit above is separate and already
        # landed). A no-op run (nothing drifted) commits nothing, same
        # as always. `compiled/*.yaml` is inside `_RECONCILABLE_HOME` (RCN1),
        # so a failure between one entry's write and this final commit
        # leaves an uncommitted record file the reconcile mechanism
        # sweeps — never a lost write, same failure-mode reasoning the
        # per-target commits already relied on.
        if resync_touched:
            with _ledger_write(home):
                _commit_ledger(
                    home,
                    resync_touched,
                    "self-learn: recompile resync record(s) "
                    f"({len(resync_touched)})",
                )

        if not no_push:
            # Outside every lock (a push touches no index); the rebase
            # fallback takes the HOST's own lock inside push_with_retry.
            for host_repo in touched_hosts:
                gitops.push_if_remote(host_repo)
    finally:
        hold.release()
    return result


@dataclass(frozen=True)
class BucketPruneResult:
    """Outcome of ``bucket prune`` (U-verbs S-54 / §4.6, HOST4). ``pruned``
    lists the removed (or, under ``dry_run``, WOULD-remove) bucket
    directories — ABSOLUTE paths (Minor, code gate r1: this docstring
    used to say "relative to *home*", which was simply wrong;
    :func:`ledger.discover_buckets` builds ``Bucket.path`` via
    ``home.glob(...)`` off an already-absolute ``home``, so every path
    here is absolute, matching what a caller would need to act on it
    directly without re-joining ``home``). ``dry_run=True`` writes
    nothing, takes no lock, holds no sentinel (DRY3's own discipline,
    reused here)."""

    pruned: list[Path]
    dry_run: bool
    commit_sha: str | None = None
    push: gitops.PushResult | None = None


def _bucket_is_empty(bucket_dir: Path) -> bool:
    """HOST4's own definition of empty: no ``lrn-*.md`` in ``pending/``
    or ``resolved/``, no FILE at all under ``proposals/``, and nothing
    else in the bucket but ``meta.yaml`` and empty directories. A bucket
    holding an orphan proposal (no record) is **not** empty — pruning it
    would lose that proposal (M51's own guard; §2.6 measured 2 such
    buckets live)."""
    for sub in ("pending", "resolved"):
        d = bucket_dir / sub
        if d.is_dir() and any(d.glob("lrn-*.md")):
            return False
    proposals = bucket_dir / "proposals"
    if proposals.is_dir() and any(f.is_file() for f in proposals.rglob("*")):
        return False
    for entry in bucket_dir.rglob("*"):
        if entry.is_file() and entry.name != "meta.yaml":
            return False
    return True


def bucket_prune(
    home: Path | str, *, dry_run: bool = False, no_push: bool = False
) -> BucketPruneResult:
    """``self-learn bucket prune`` (U-verbs S-54 / §4.6, HOST4): remove
    every record-less, proposal-less bucket directory under
    ``projects/``, ``skills/`` and ``user/`` — one ledger commit
    ``self-learn: bucket prune <n> empty bucket(s)``. ``--dry-run``
    reports the list and writes nothing, takes no lock, holds no
    sentinel. **Never prunes the ``user/`` bucket** (HOST4) — the one
    bucket that must always exist."""
    home = Path(home)
    candidates = [
        b for b in discover_buckets(home)
        if b.scope != "user" and _bucket_is_empty(b.path)
    ]
    if dry_run:
        return BucketPruneResult(pruned=[b.path for b in candidates], dry_run=True)
    if not candidates:
        return BucketPruneResult(pruned=[], dry_run=False)
    from .ledger_ops import _remove_file

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: bucket prune {len(candidates)} empty bucket(s)"
        with _ledger_write(home):
            touched: list[Path] = []
            for b in candidates:
                meta = b.path / "meta.yaml"
                try:
                    if _remove_file(home, meta):
                        touched.append(meta)
                except gitops.GitOpsError as exc:
                    # M-D fold r3 (MINOR): built HERE, not inside
                    # `_remove_file` — this loop is the only place that
                    # holds `touched`, the earlier buckets' removals
                    # already staged in this same sequence. Naming only
                    # `meta` (the FAILING path) would leave an operator
                    # who runs the repair literally with those earlier
                    # deletions still sitting uncommitted.
                    raise gitops.HalfWrittenError.for_commit(
                        home, message, [*touched, meta], exc
                    ) from exc
            staged, sha = _commit_ledger(home, touched, message, None)
            for b in candidates:
                if b.path.is_dir():
                    shutil.rmtree(b.path, ignore_errors=True)
        push = _push_ledger(home, no_push)
        return BucketPruneResult(
            pruned=[b.path for b in candidates], dry_run=False, commit_sha=sha, push=push
        )
    finally:
        hold.release()


def followup_add(
    home: Path | str,
    record_id: str,
    *,
    action: str,
    unblocks_on: str | None = None,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """``self-learn followup add`` (U-verbs S-54 / §4.7, Phase 2, META1-
    META2): open a follow-up on a ROUTED record — the verb `daad648`'s
    hand commit (2026-07-14) did by hand. ``require_status(...,
    ROUTED_ONLY, verb="followup-add")``; refuses (rc 1) when
    ``routing.follow_up`` is already open, naming the open action —
    ``followup done`` clears it first (META2). Validated through the
    SAME shipped :func:`records._validate_follow_up` `route`'s own
    ``--follow-up`` uses (META1 — never a second, hand-rolled shape
    check). Commit ``self-learn: follow-up add lrn-…`` (matching the
    existing ``self-learn: follow-up done lrn-…`` subject family).

    M-1 (U-verbs Phase 2 code gate r1): applies the follow-up through
    :meth:`Record.set_follow_up` — the SAME sibling method ``route
    --follow-up`` already uses — never :meth:`Record.set_routing`
    directly. This verb re-validates and rewrites the SAME routing
    block that already exists (status stays ``routed``, ``destination``
    is unchanged, no host write follows); it never ROUTES the record,
    so it must not be mistaken for a route site — the same reasoning
    :meth:`Record.complete_follow_up` already gives ``followup done``
    below."""
    home = Path(home)
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    try:
        _, record = require_status(home, record_id, ROUTED_ONLY, verb="followup-add")
    except LedgerOpsError as exc:
        raise VerbError(str(exc)) from exc
    existing = (record.routing or {}).get("follow_up")
    if existing:
        raise VerbError(
            f"lrn-{record_id[4:]} already has an open follow-up: "
            f"{existing.get('action')} — `followup done` clears it first"
        )
    follow_up: dict[str, object] = {"action": action}
    if unblocks_on is not None:
        follow_up["unblocks_on"] = unblocks_on
    if note is not None:
        follow_up["note"] = note
    try:
        _validate_follow_up(follow_up)
    except RecordError as exc:
        raise VerbError(str(exc)) from exc

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: follow-up add {record_id}"
        with _ledger_write(home):
            record = Record.from_path(path)  # fresh read under the lock
            try:
                record.set_follow_up(action, unblocks_on=unblocks_on, note=note)
            except records_mod.MutationError as exc:
                # gate r2 M-A: NOT a blanket `except RecordError`. The
                # pre-lock `_validate_follow_up(follow_up)` call above
                # already owns shape validation (META1: the SAME shipped
                # validator `Record.set_follow_up` calls again internally
                # -- twice on purpose, never a second implementation). A
                # `ValidationError` reaching this point would mean that
                # pre-lock check was bypassed or wrong, and must escape
                # rather than be relabelled -- a blanket catch here
                # silently absorbed spec mutation M53 (hand-roll the
                # pre-lock shape check instead of calling the shipped
                # validator) into an indistinguishable VerbError, which
                # hollowed out META1's own named mutation. `MutationError`
                # (record has no routing block; record is not `routed`)
                # is a genuine race between the pre-lock read and this
                # fresh one -- that, and only that, is what this catches.
                raise VerbError(str(exc)) from exc
            record.write(path)
            staged, sha = _commit_ledger(home, [path], message, note)
        push = _push_ledger(home, no_push)
        return VerbResult(
            action="followup-add",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()


def _reclassify_apply(record: Record, *, kind: str | None, type: str | None) -> None:
    """Apply ``reclassify --kind K --type T`` to ``record`` in the one
    order that can ever land on a pair :meth:`Record.validate` accepts
    (gate r2 B-1, three faces of one omission): clear ``kind`` FIRST
    whenever the resulting type will not be ``behavior`` -- ``kind`` is
    behavior-only by definition (:meth:`Record.set_kind`), and the CLI's
    own ``--kind`` has no way to name a clear (``choices=sorted(KINDS)``
    at ``cli.py``), so this auto-clear is the ONLY path that makes
    behavior -> knowledge reachable through this verb at all -- THEN
    change ``type`` (so ``set_type``'s own "clear kind first" guard never
    fires on a target this function already cleared for), THEN set the
    new ``kind`` if one was given (so ``set_kind``'s own
    behavior-only guard sees the ALREADY-updated type, not the stale
    one -- the exact ordering bug gate r2 found: the old code called
    ``set_kind`` before ``set_type``, so a legal ``--type behavior
    --kind X`` on a non-behavior record was refused though the verb's
    own pre-lock guard had just admitted it).

    Never writes to disk -- but gate r3 Minor 2: the guarantee this
    docstring used to state here ("every call below validates itself")
    does NOT hold for the first call. ``set_kind(None)`` performs NO
    check at all (gate r3's own primary-attack audit: it is the one
    setter weaker than :meth:`Record.validate`, by design -- clearing
    ``kind`` is legal on ANY type, so there is nothing for it to check
    in isolation); ``set_type`` and ``set_kind(kind)`` DO validate their
    own field against the type in front of them at that moment, never
    the full cross-field pair ``Record.validate`` checks. So a record
    can sit in a state ``Record.validate`` would reject BETWEEN the
    three calls below (immediately after ``set_kind(None)``, on a
    behavior-typed record with no kind, until ``set_type`` runs) --
    that window never reaches disk or an external observer only
    because this function is synchronous and its caller controls when
    ``record`` is read again. The guarantee this function DOES keep:
    the three calls run in the one order that can ever land the WHOLE
    sequence on a pair ``Record.validate`` accepts, and any call that
    itself rejects a step raises immediately, before any later step
    runs. Whether the RESULT is checked against ``Record.validate`` in
    full is the caller's job, not this function's: :func:`reclassify`
    does it twice on purpose (pre-lock simulation, then again under
    the lock via a fresh read) -- a caller that skips both gets no
    such check from calling this function alone. Callers decide
    whether ``record`` is a disposable simulation copy (pre-lock,
    fail-closed) or the real fresh-under-lock instance."""
    resulting_type = type if type is not None else record.type
    if resulting_type != "behavior":
        record.set_kind(None)
    if type is not None:
        record.set_type(type)
    if kind is not None:
        record.set_kind(kind)


def reclassify(
    home: Path | str,
    record_id: str,
    *,
    kind: str | None = None,
    type: str | None = None,
    note: str | None = None,
    no_push: bool = False,
) -> VerbResult:
    """``self-learn reclassify`` (U-verbs S-54 / §4.7, Phase 2, META3-
    META5): re-file a record's ``kind``/``type`` — at least one of the
    two required (else the CLI's own usage gate, 64).

    ``kind`` (``records.KINDS``): **every status** — 02 §2: *"scope/kind
    (triage may re-classify — the filing is never frozen)"*. ``type``
    (``records.TYPES``): refused (rc 1) outside ``LIVE_STATUSES`` — 02
    §2 freezes ``type`` at routing, the SAME paragraph, the OTHER half
    of its asymmetry. A ``type`` change RE-VALIDATES the required body
    sections (``records.REQUIRED_SECTIONS``) and refuses (rc 1) naming
    the missing headings — the record is never rewritten to fit (META4).
    One commit ``self-learn: reclassify lrn-…``; a ``kind``-only change
    on a routed record touches no host (kind is not compiled).

    gate r2 B-1: the RESULTING ``(type, kind)`` pair is validated —
    fail-closed, on a disposable in-memory copy, through
    :meth:`Record.validate` itself (never a second, hand-rolled pair
    check) — before any lock or write. Without this, ``--type behavior``
    on a record with no kind (given or existing) used to commit a
    ``kind: null`` behavior record that ``Record.from_path`` then refused
    to load; the same omission made a legal ``--type behavior --kind X``
    on a non-behavior record refusable-though-admitted; and made
    ``--type knowledge`` on any kinded behavior record unconditionally
    unreachable through this CLI (``--kind`` cannot name a clear). One
    gap, three faces, one fix — see :func:`_reclassify_apply`."""
    home = Path(home)
    if kind is None and type is None:
        raise VerbUsageError("reclassify needs --kind and/or --type")
    path = find_record_path(home, record_id)  # pending OR resolved
    _scan_or_refuse([path], note)
    record = Record.from_path(path)
    if kind is not None and kind not in records_mod.KINDS:
        raise VerbUsageError(
            f"--kind must be one of {sorted(records_mod.KINDS)}, got {kind!r}"
        )
    if kind is not None and (type or record.type) != "behavior":
        raise VerbError(
            f"--kind applies to behavior records only (02 §1) — "
            f"record {record_id} is {record.type!r}"
        )
    if type is not None:
        if type not in records_mod.TYPES:
            raise VerbUsageError(
                f"--type must be one of {sorted(records_mod.TYPES)}, got {type!r}"
            )
        try:
            require_status(home, record_id, LIVE_STATUSES, verb="reclassify --type")
        except LedgerOpsError as exc:
            raise VerbError(str(exc)) from exc
        # M-3 (gate r1), reached through the public surface now (gate r2
        # m-4 — reaching Record's own private body-shape staticmethod was the only
        # cross-module access to a Record-private member in either src
        # tree): an early, body-shape-specific refusal, through the ONE
        # shipped validator — the SAME one set_type calls again below,
        # inside _reclassify_apply (twice on purpose, never a second
        # implementation; and gate r2 measured the redundancy is not
        # vacuous — see test_reclassify_type_refuses_a_duplicate_heading_pre_lock).
        try:
            records_mod.validate_body(type, record.body)
        except RecordError as exc:
            raise VerbError(
                f"record {record_id} cannot reclassify to type {type!r}: "
                f"{exc} — the body is never rewritten to fit; edit it by "
                "hand first"
            ) from exc

    # gate r2 B-1: validate the RESULTING (kind, type) pair -- not just
    # the incoming flags -- on a disposable in-memory copy, fail-closed,
    # before any lock or write. `Record.validate()` is the ONE authority
    # for "does this pair make sense" (kind required for behavior,
    # forbidden otherwise) -- never a second, hand-rolled pair check.
    sim = records_mod.Record.from_text(record.to_text())
    try:
        _reclassify_apply(sim, kind=kind, type=type)
        sim.validate()
    except RecordError as exc:
        raise VerbError(
            f"record {record_id} cannot reclassify to kind={kind!r} "
            f"type={type!r}: {exc}"
        ) from exc

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        message = f"self-learn: reclassify {record_id}"
        with _ledger_write(home):
            record = Record.from_path(path)  # fresh read under the lock
            # gate r3 Minor 3: a --type change that lands outside
            # `behavior` silently clears `kind` (`_reclassify_apply`'s own
            # docstring names this the ONLY path that makes behavior ->
            # knowledge reachable) -- intended, recoverable from git
            # history, but a verb dropping a user's field with no visible
            # trace is a surprise a week later. Capture the value BEFORE
            # `_reclassify_apply` clears it, and leave a one-line `notes`
            # entry naming what was cleared -- `notes` (not `history`),
            # because this is commentary for the NEXT human reader, not a
            # write-once-field displacement (`Record.append_history`'s own
            # contract, `resolution_note`'s the only current user).
            resulting_type = type if type is not None else record.type
            cleared_kind = (
                record.kind
                if resulting_type != "behavior" and record.kind is not None
                else None
            )
            try:
                _reclassify_apply(record, kind=kind, type=type)
            except records_mod.MutationError as exc:
                # gate r2 M-A's lesson applied here too: NOT a blanket
                # `except RecordError`. `set_kind`/`set_type` never raise
                # `MutationError` today (only `_check_thawed`, reached
                # through `set_type`, can — a genuine race where the
                # record's status left LIVE_STATUSES between the pre-lock
                # check and this fresh read); every OTHER failure mode
                # is `ValidationError`, and the pre-lock simulation just
                # above already covers those on the SAME transform via
                # the SAME function. A `ValidationError` reaching this
                # point would mean that simulation was bypassed or wrong,
                # and must escape rather than be relabelled indistinguishably
                # from a fail-closed refusal — the exact mechanism that
                # hollowed out META1's own mutation (M-A) one verb over.
                raise VerbError(str(exc)) from exc
            if cleared_kind is not None:
                # criterion 25 (test_route_observability.py): no `by=`
                # string literal at a call site anywhere in verbs.py --
                # `append_note`'s own default (`by="human"`) applies; a
                # human genuinely did invoke reclassify, and the note
                # TEXT already names the mechanism ("reclassify cleared
                # kind=..."), so no separate actor literal is needed.
                record.append_note(
                    f"reclassify cleared kind={cleared_kind!r} (type -> "
                    f"{type!r}); recoverable from the ledger's git history"
                )
            record.write(path)
            staged, sha = _commit_ledger(home, [path], message, note)
        push = _push_ledger(home, no_push)
        return VerbResult(
            action="reclassify",
            record_id=record_id,
            commit_message=message,
            commit_sha=sha,
            staged=staged,
            push=push,
            sentinel_owned=hold.owned,
        )
    finally:
        hold.release()
