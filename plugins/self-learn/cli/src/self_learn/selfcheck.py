"""Attended validation + installation self-checks (T11).

Two entry points, both printed loud and returning process exit codes:

``proposal validate <id>`` (08 §7.1 Proposal-validate-verb row — pulled
forward from T13 because every ingredient already exists in ledger_ops
and scan):
    For one record: (1) run the §1 secret scan over the record file and
    ALL proposal siblings (``lrn-<id>.{yaml,diff}`` raw text — covering
    ``rationale`` / ``already_canon_reason`` free text); (2) validate the
    proposal sibling against the 02 §1 schema; (3) on success stamp
    ``record_sha`` via :func:`ledger_ops.stamp_proposal` — the same code
    path as the worker's run-sequence step (4); the model-emitted value is
    never trusted. Divergence from unattended-worker policy, pinned: on
    schema-invalid input it REPORTS and NEVER DELETES — this verb serves
    attended iteration and the file is work-in-progress, not litter. A
    scan hit reports span + rule and never deletes / never auto-redacts
    (redaction is the human's move). Commits nothing — proposals/records
    are working files pre-resolution; resolution verbs own commits.

    Exit codes (P2-8, the TUI parses these, never prose):
    0 = valid + scan-clean (stamped) · 1 = schema-invalid · 2 = scan hit
    (2 wins when both apply).

``--selftest`` (04 exit (c); 08 §3 T11 row): loud PASS/FAIL per check,
non-zero exit on any FAIL:
    (a) capture path — create + parse + delete a scratch record in a temp
        bucket under SELF_LEARN_HOME (clean refusal when the home is
        missing);
    (b) compiler dry-run — regenerate every routed-to managed section
        in-memory from resolved/ records; no writes;
    (c) marker check per 02 §4 — every target that SHOULD have a section
        (≥1 resolved record routed to it) has an intact marker pair;
        missing/broken markers FAIL naming the file. Targets with zero
        routed records are never flagged (the bootstrap rule covers
        first-route targets);
    (d) drift check (doc 13 §4.2) — every ROUTED record must be present
        in its canon: a skill-md/claude-md record's ``(lrn-…)`` marker
        inside its compiled target's managed section, a ``reference``
        record's id inside its references file (targets resolved via
        hosts.yaml, the same logic the verbs use); missing target, marker,
        or entry FAILs naming ``self-learn recompile``; skipped cleanly
        when hosts.yaml is absent;
    (d2) reach check (U-reach §2.1) — every LIVE ``reference``-routed
        record must be REACHABLE from its scope's loaded surface (SKILL.md
        / CLAUDE.md / the user CLAUDE.md), never merely present in its
        target file — drift answers "did the write land?"; reach answers
        "can anything get to it?", the question nothing else asks. FAILs
        name the record; skipped cleanly when hosts.yaml is absent. An
        independent row from (d): one check masking the other's failure
        would turn a two-fact check back into one;
    (e) hook check (M3 — 08 §8.1 Hook-selftest pin): every currently-
        routed hook record's script exists, is executable, and matches
        the approved bytes; superseded records with a surviving script
        are flagged as incomplete supersessions; settings.json
        registrations naming a ``self-learn-*`` hook must resolve through
        ``~/.claude/hooks/`` (missing/dangling = the silent-no-op drift);
    (e2) surface check (U-pointer, the reachability emitter) — every LIVE
        ``skill-md``/``claude-md``/``new-skill``/``hook``-routed record's
        compiled surface is REACHABLE, UNREACHABLE, or (a first-class,
        never-conviction-by-default) UNMEASURABLE — the question neither
        drift nor (d2)'s reach check asks for these four destinations
        (``reference`` stays wholly owned by (d2)). A `settings.json` that
        will not parse FAILs the row through the settings-dependent
        records only, never blanket; an absent ``~/.claude`` PASSes with
        an UNMEASURABLE count and a note line, never a silent skip;
    (f) sentinel writability — hold + release a probe at the real
        cache-path resolution; a pre-existing LIVE sentinel (another
        flow's hold) is heartbeated, never deleted;
    (g) worker check — stubbed M2-conditional: prints
        ``worker: M2 — not checked``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from . import compiled
from . import gitops
from . import provider
from . import scan as scan_mod
from . import sentinel
from .compilers import (
    BEGIN_MARKER,
    END_MARKER,
    CompileError,
    compile_managed_text,
    reference_target_path,
)
from .compilers import surface_names_target as _surface_names_target
from .hosts import HostsError, ancestors_of, host_mode, host_slug, hosts_path, load_hosts, skill_dir_for
from .ledger import Bucket, discover_buckets, home_state, home_state_message
from .ledger_ops import (
    ProposalError,
    bucket_project_path,
    find_record_path,
    glob_reaches,
    read_proposal,
    stamp_proposal,
    validate_proposal,
)
from .reachability import reachability_rows
from .records import Record, RecordError
from .verbs import DEFAULT_USER_CLAUDE_MD, _user_reachability_roots, managed_target_for

__all__ = ["proposal_validate", "run_selftest"]

EXIT_VALID = 0
EXIT_SCHEMA_INVALID = 1
EXIT_SCAN_HIT = 2


# ------------------------------------------------------- proposal validate


def _proposal_siblings(record_path: Path, record_id: str) -> list[Path]:
    pdir = record_path.parent.parent / "proposals"
    return [
        p for p in (pdir / f"{record_id}.yaml", pdir / f"{record_id}.diff") if p.is_file()
    ]


def proposal_validate(home: Path, record_id: str) -> int:
    """Scan + schema-validate + stamp one record's proposal. See module
    docstring for the pinned semantics; raises :class:`LedgerOpsError`
    only for an unknown/malformed record id (a usage error, not one of
    the three pinned outcomes)."""
    record_path = find_record_path(home, record_id)
    siblings = _proposal_siblings(record_path, record_id)

    # (1) Secret scan first — a hit wins over schema-invalid (P2-8). Full
    # file text on both sides: the record file (S-8 rider — same scope as
    # the resolution verbs' full-file rescan) and every sibling's raw text
    # (covers rationale / already_canon_reason and any diff content).
    scanned_hit = False
    for path in (record_path, *siblings):
        hits = scan_mod.scan(path.read_text(encoding="utf-8"))
        if hits:
            scanned_hit = True
            print(
                f"proposal validate: secret scan hit in {path} — "
                "refusing to stamp; redact via Iterate or a --redact-bearing "
                "surface, never by this verb",
                file=sys.stderr,
            )
            for h in hits:
                print(f"  - [{h.rule}] at {h.start}..{h.end}: {h.span}", file=sys.stderr)
    if scanned_hit:
        return EXIT_SCAN_HIT

    # (2) Schema. Report-never-delete: the file stays byte-intact.
    yaml_sibling = record_path.parent.parent / "proposals" / f"{record_id}.yaml"
    if not yaml_sibling.is_file():
        print(
            f"proposal validate: no proposal sibling for {record_id} "
            f"at {yaml_sibling}",
            file=sys.stderr,
        )
        return EXIT_SCHEMA_INVALID
    try:
        # FW-62: record_text= must be supplied so RECORD-sourced trace
        # quotes (gates.*.evidence) get the SAME containment check
        # write_proposal/proposal_info run (ledger_ops.py) — omitting it
        # here silently skipped containment on this verb alone (08 §7.1's
        # honesty surface), while the machine paths stayed strict. The
        # record is already parsed on the line above for the
        # unparseable-record check, so this is free; .to_text() matches
        # the text form (frontmatter + body, not just body — E4) both
        # other call sites pass. `scope=record.scope` is the same
        # obligation one field over (u-table §3.5, §6-BD8): this is the
        # human's hand-edit path, and leaving it unscoped would rebuild
        # FW-62's exact shape — a validator whose machine path is strict
        # and whose human path is lenient.
        record = Record.from_path(record_path)  # an unparseable record cannot be stamped
        validate_proposal(
            read_proposal(yaml_sibling),
            record_text=record.to_text(),
            scope=record.scope,
            home=home,
        )
    except (ProposalError, RecordError) as exc:
        print(
            f"proposal validate: {record_id} schema-invalid — {exc} "
            "(file left intact)",
            file=sys.stderr,
        )
        return EXIT_SCHEMA_INVALID

    # (3) Stamp in place — same code path as worker step (4); overwrites
    # any model-emitted record_sha. No commit: working files pre-resolution
    # (the worker's run-end commit carries them; a resolution deletes them).
    #
    # Locked anyway (audit 2026-07-16 round 7 — surfaced by the invariant
    # check, which had no idea this verb existed; that is the point of
    # enumerating surfaces from the code). The rewrite targets a TRACKED
    # file, so a racing producer's `pull --rebase --autostash` can stash it
    # mid-write and restore it into a conflict — and the "no commit" pin
    # makes that WORSE, not better: nobody here would notice. The lock is
    # local and measured in milliseconds. Its absence would have been a
    # judgement nobody made.
    try:
        with gitops.commit_lock(home):
            stamp_proposal(home, record_id)
    except gitops.GitOpsError as exc:
        print(
            f"proposal validate: {record_id} is valid, but the stamp was "
            f"not written ({exc}) — nothing was changed; retry once the "
            "other producer finishes",
            file=sys.stderr,
        )
        return gitops.EXIT_GIT_FAILED
    print(f"proposal validate: {record_id} valid — record_sha stamped in place")
    return EXIT_VALID


# ----------------------------------------------------------------- selftest


def _target_for(home: Path, bucket: Bucket, record: Record) -> Path | None:
    """The compiled canon file for one skill-md/claude-md/new-skill
    record, resolved through the hosts registry — the SAME resolution the
    verbs use (doc 13 §4). None = unresolvable (unregistered/missing
    host). U-xscope §3.1: delegates to :func:`self_learn.verbs.
    managed_target_for`, the single implementation this and
    :func:`self_learn.verbs._compile_set` both consume — selfcheck never
    threads a ``user_claude_md`` override, so this always resolves
    against the operator's real ``~/.claude/CLAUDE.md`` (byte-identical
    to the pre-delegation behavior)."""
    return managed_target_for(home, bucket, record)


def _managed_host_for(
    home: Path,
    bucket: Bucket,
    record: Record,
    *,
    user_claude_md: Path | str | None = None,
) -> Path | None:
    """U-hostmode PLAIN8: the HOST root a managed-destination record's
    target lives under — ``host_mode`` needs the resolved ROOT, never a
    file somewhere inside it (exact-match only, MODE9). Mirrors the same
    per-scope resolution `_reference_target_for`/`_check_drift` already
    use; ``None`` when unresolvable (the entry-marker check above already
    reported that as "target unresolvable" — this is never reached then).

    ``user_claude_md`` (N-8, code gate r1 fold): honours the SAME
    test/route-time override every other user-scope resolution site in
    this codebase threads (``verbs.managed_target_for``,
    ``_resolve_target``) — pre-fold, this was the one site that
    hardcoded ``DEFAULT_USER_CLAUDE_MD`` with no way to override it even
    for a test, silently aiming a user-scope drift/PLAIN8 check at the
    OPERATOR'S REAL ``~/.claude/CLAUDE.md`` from inside a sandboxed
    caller that overrode it everywhere else. ``None`` (the default)
    keeps existing behavior byte-identical."""
    if bucket.scope == "skill":
        try:
            root = load_hosts(home).skills_root
        except HostsError:
            return None
        return Path(root) if root is not None else None
    if record.scope == "project":
        host = bucket_project_path(bucket.path)
        return Path(host) if host is not None else None
    resolved_user_claude_md = (
        Path(user_claude_md) if user_claude_md is not None else DEFAULT_USER_CLAUDE_MD
    )
    return resolved_user_claude_md.expanduser().parent


def _reference_target_for(home: Path, bucket: Bucket, record: Record) -> Path | None:
    """The references FILE one reference-routed record landed in — the
    same resolution the verbs use: the record's own
    ``routing.reference_file`` (absent ⇒ the default LEARNINGS.md) under
    the host's references dir. None = unresolvable (unregistered/missing
    host, or a scope with no references dir)."""
    routing = record.routing or {}
    if routing.get("destination") != "reference":
        return None
    try:
        if bucket.scope == "skill":
            refs = skill_dir_for(load_hosts(home), bucket.name) / "references"
        elif record.scope == "project":
            host = bucket_project_path(bucket.path)
            if host is None:
                return None
            refs = Path(host) / "references"
        else:
            return None
    except HostsError:
        return None
    return reference_target_path(refs, routing.get("reference_file"))


# ------------------------------------------------------------- U-reach §2.1


def _loaded_surface(home: Path, bucket: Bucket, record: Record) -> list[Path]:
    """LS(bucket, record) — the files a session LOADS for a record's
    scope, resolved exactly as the verbs resolve them (§2.1's table). A
    list from day one, one member per scope in v1: ``CLAUDE.local.md`` and
    ``.claude/rules/*.md`` are deliberately NOT members (§6 — a pointer
    must be at least as durable as the thing it points at, and ``local``
    is git-excluded by design). The list shape exists so a future Model B
    remap adds a member instead of editing a predicate.

    Empty ``[]`` means "nothing loaded for this record" — the caller must
    treat that as a FAILURE, never a skip (criterion 8): an unresolvable
    host is exactly the state the R14 defect lived in.

    The ``user`` row is dead code end-to-end **permanently, per S-23 (2)**
    (`03-decisions.md`) — not pending on ``U-demand-user``. At write time
    this said "until ``U-demand-user``", as if the refusal were temporary;
    S-23 (2026-08-02) instead ruled that user scope's cheap surface is
    PATHED rules only, explicitly NOT a user-level reference file, and
    re-scoped ``U-demand-user`` away from ever opening it. ``_reference_
    target_for`` returns ``None`` for user scope BEFORE this function is
    ever consulted (``reference`` is refused at user scope by design, not
    by omission), so no end-to-end fixture can reach it — it is
    unit-tested directly instead (criterion 9a). The row stays regardless:
    dropping it would put ``user/`` silently outside RR's domain, which is
    F1, the exact silent narrowing criterion 13 forbids."""
    if bucket.scope == "skill":
        try:
            return [skill_dir_for(load_hosts(home), bucket.name) / "SKILL.md"]
        except HostsError:
            return []
    if record.scope == "project":
        host = bucket_project_path(bucket.path)
        if host is None:
            return []
        # U-ancestry ANC7: a registered ancestor's CLAUDE.md loads in
        # every session under this host too (§2.3, measured) — appended,
        # nearest-first, after the own-host member. Appending can only
        # turn an unreachable record reachable, never the reverse (§6.4),
        # so a no-ancestor host's LS stays exactly one member (UN3).
        try:
            hosts = load_hosts(home)
        except HostsError:
            return [Path(host) / "CLAUDE.md"]
        members = [Path(host) / "CLAUDE.md"]
        members.extend(a / "CLAUDE.md" for a in ancestors_of(hosts, Path(host)))
        return members
    if record.scope == "user":
        return [DEFAULT_USER_CLAUDE_MD.expanduser()]
    return []


def _check_reach(home: Path) -> tuple[bool, str]:
    """U-reach §2.1: every LIVE reference-routed record must be reachable
    from its scope's loaded surface — mirrors :func:`_check_drift`'s
    posture exactly, so the two checks read the same, but stays an
    INDEPENDENT row with an independent loop (§3: folding it into drift
    would let one check mask the other's failure — a two-fact check
    collapsing back into one).

    RR (the domain): every bucket :func:`~self_learn.ledger.discover_buckets`
    returns — ``skills/*``, ``projects/*``, AND the single one-level
    ``user/`` bucket — never a ``<home>/*/*/resolved/`` glob, which would
    silently miss ``user/resolved/`` while reporting success (criterion
    9a; the exact failure class this unit exists to detect). Every record
    in ``<bucket>/resolved/lrn-*.md`` with ``status == "routed"``,
    ``superseded_by is None``, and ``routing.destination == "reference"``.

    A record FAILS when its reference target is unresolvable via
    hosts.yaml, when its loaded surface is empty, or when no member of
    that surface names the target — never skipped, never softened
    (criteria 7, 8). The failing count LEADS the message (criterion 3) so
    Checkpoint B's number is greppable from one line; the PASS message
    carries its count too (criterion 1) — a countless PASS is exactly the
    fail-open shape this half of the gate exists to exclude.

    FW-66: a resolved record file that fails to even PARSE — malformed
    YAML/frontmatter (``RecordError``) or bytes that are not valid UTF-8
    (``UnicodeDecodeError``) — is skipped exactly like any other
    unparseable resolved file (T3's problem, not this check's — the
    record's routing/destination/scope are unknown, so it cannot be
    placed in or out of RR). A LOADED SURFACE that fails to decode is
    different: by the time it is read the record is already confirmed
    in-scope (live, reference-routed), so an undecodable surface is a
    DISTINCT un-checkable condition, reported and counted as a FAILURE —
    never a silent skip, which would pass while seeing nothing (the
    surface is a file self-learn does not own and cannot constrain:
    SKILL.md / CLAUDE.md / the user CLAUDE.md)."""
    state = home_state(home)
    if state in ("missing", "not-a-repo"):
        return False, home_state_message(state, home)
    if not hosts_path(home).is_file():
        return True, "hosts.yaml absent — reachability not checked"
    failures: list[str] = []
    checked = 0
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, UnicodeDecodeError):
                continue
            if record.status != "routed" or record.superseded_by is not None:
                continue
            if (record.routing or {}).get("destination") != "reference":
                continue
            checked += 1
            target = _reference_target_for(home, bucket, record)
            if target is None:
                failures.append(
                    f"{record.id}: reference target unresolvable via "
                    "hosts.yaml — register the host, then "
                    "`self-learn recompile`"
                )
                continue
            surfaces = _loaded_surface(home, bucket, record)
            if not surfaces:
                failures.append(
                    f"{record.id}: no loaded surface for scope "
                    f"{record.scope!r} — nothing to reach it from"
                )
                continue
            found = False
            unreadable: list[str] = []
            for surface in surfaces:
                try:
                    if _surface_names_target(surface, target):
                        found = True
                        break
                except UnicodeDecodeError as exc:
                    unreadable.append(f"{surface} ({exc})")
            if found:
                continue
            if unreadable:
                failures.append(
                    f"{record.id}: loaded surface not readable as UTF-8, "
                    "reachability cannot be verified: " + "; ".join(unreadable)
                )
                continue
            named = ", ".join(str(s) for s in surfaces)
            failures.append(
                f"{record.id}: not named by its loaded surface "
                f"({named}) — write a resolving pointer to {target}"
            )
    if failures:
        return False, (
            f"{len(failures)} of {checked} reference-routed record(s) "
            "unreachable: " + "; ".join(failures)
        )
    if not checked:
        return True, "no reference-routed records — nothing to reach"
    return True, (
        f"{checked} reference-routed record(s) reachable from their "
        "scope's loaded surface"
    )


def _section_targets(home: Path) -> dict[Path, list[Record]]:
    """Managed-section targets that SHOULD have a section: target file →
    the resolved records routed to it (any record whose routing names the
    destination — graduated entries keep their markers, so presence still
    counts). Targets resolve via hosts.yaml; unresolvable records are
    skipped here (the drift check reports them)."""
    targets: dict[Path, list[Record]] = {}
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, UnicodeDecodeError):
                continue  # unparseable resolved files are T3's problem, not (c)'s
            target = _target_for(home, bucket, record)
            if target is not None:
                targets.setdefault(target, []).append(record)
    return targets


def _check_drift(
    home: Path, *, user_claude_md: Path | str | None = None
) -> tuple[bool, str]:
    """Doc 13 §4.2 drift check: every ROUTED record must be PRESENT in the
    canon it was routed into — a managed destination's ``(lrn-…)`` entry
    marker inside its target's managed section, and a ``reference``
    destination's id somewhere in its references file. A two-phase
    interruption leaves the ledger routed and the canon stale, and
    ``self-learn recompile`` is the one-command repair.

    References are checked here (audit 2026-07-16 BLOCKER 2): they used to
    be filtered out alongside new-skill/hook, so an interrupted reference
    route — the case where the entry is silently ABSENT rather than stale
    — was the one kind of drift this check swore was impossible.

    Skips cleanly when hosts.yaml is absent (nothing registered → nothing
    compiled anywhere) — but only once the home is one we can actually
    read. A missing / not-a-repo home has no hosts.yaml either, so "not
    checked" rendered exactly like "checked, clean" (audit 2026-07-16
    MAJOR 5): the B-11 silent all-clear wearing a PASS. A ledger nobody
    can see cannot certify canon.

    The refusal set mirrors :func:`cli._home_gate` EXACTLY — missing and
    not-a-repo only. ``uninitialized`` is deliberately NOT a failure there
    (it is a real repo that simply was never bootstrapped, and the first
    capture bootstraps it), and a ledger with no layout and no hosts.yaml
    has no canon to have drifted from: that is a true, quiet skip.

    ``user_claude_md`` (N-8, code gate r1 fold): threaded straight
    through to :func:`_managed_host_for`'s PLAIN8 user-scope leg, the
    same override every other user-scope resolution site in this
    codebase accepts (``verbs.managed_target_for``, ``_resolve_target``)
    — ``None`` (the default; no current caller passes otherwise) keeps
    every existing behavior byte-identical, resolving against the
    operator's real ``~/.claude/CLAUDE.md``."""
    state = home_state(home)
    if state in ("missing", "not-a-repo"):
        return False, home_state_message(state, home)
    if not hosts_path(home).is_file():
        return True, "hosts.yaml absent — drift not checked"
    failures: list[str] = []
    checked = 0
    # U-hostmode PLAIN8: non-failing region-verdict notes (unknown/stale/
    # clean) for PLAIN-mode managed targets — never gate the boolean, but
    # DO ride the rendered string so the four verdicts stay distinguishable.
    plain_notes: list[str] = []
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, UnicodeDecodeError):
                continue
            if record.status != "routed" or record.superseded_by is not None:
                continue
            destination = (record.routing or {}).get("destination")
            if destination not in (
                "skill-md", "claude-md", "reference", "new-skill"
            ):
                continue
            checked += 1

            if destination == "reference":
                ref_target = _reference_target_for(home, bucket, record)
                if ref_target is None:
                    failures.append(
                        f"{record.id}: references target unresolvable via "
                        "hosts.yaml — register the host, then "
                        "`self-learn recompile`"
                    )
                elif not ref_target.is_file():
                    failures.append(
                        f"{record.id}: references file {ref_target} missing "
                        "— run `self-learn recompile`"
                    )
                else:
                    try:
                        ref_text = ref_target.read_text(encoding="utf-8")
                    except UnicodeDecodeError as exc:
                        # FW-66 (same treatment as reach): a compiler-owned
                        # target that fails to decode cannot be searched for
                        # the entry — FAIL naming the file, never a silent
                        # skip that reads as "present."
                        failures.append(
                            f"{record.id}: references file {ref_target} not "
                            f"readable as UTF-8 ({exc}) — presence cannot be "
                            "verified"
                        )
                    else:
                        if record.id not in ref_text:
                            failures.append(
                                f"{record.id}: entry missing from {ref_target} "
                                "— run `self-learn recompile`"
                            )
                continue

            target = _target_for(home, bucket, record)
            if target is None:
                failures.append(
                    f"{record.id}: target unresolvable via hosts.yaml — "
                    "register the host, then `self-learn recompile`"
                )
                continue
            if not target.is_file():
                failures.append(
                    f"{record.id}: target {target} missing — run "
                    "`self-learn recompile`"
                )
                continue
            try:
                text = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                failures.append(
                    f"{record.id}: target {target} not readable as UTF-8 "
                    f"({exc}) — entry marker cannot be verified"
                )
                continue
            begin = text.find(BEGIN_MARKER)
            end = text.find(END_MARKER)
            section = text[begin:end] if 0 <= begin < end else ""
            if f"({record.id})" not in section:
                failures.append(
                    f"{record.id}: entry marker missing from {target} — "
                    "run `self-learn recompile`"
                )
                continue
            # U-hostmode PLAIN8: the entry-marker check above is the ONLY
            # signal a git host needs (`gitops.paths_dirty` covers the
            # rest); a PLAIN host has no `git status` at all, so the
            # compile record's own region verdict is the one instrument
            # that can see a hand edit here — rendered as one of four
            # distinguishable strings (no compile record yet / clean /
            # stale / edited), only "edited" counted as drift.
            host_path = _managed_host_for(
                home, bucket, record, user_claude_md=user_claude_md
            )
            if host_path is not None and host_mode(home, host_path) != "git":
                try:
                    region = compiled.region_bytes(text, "managed")
                except compiled.CompiledRecordError:
                    region = None
                if region is not None:
                    scope_kind = "user" if bucket.scope == "user" else (
                        "skill" if bucket.scope == "skill" else "project"
                    )
                    slug = host_slug(home, host_path, scope_kind=scope_kind)
                    entry = compiled.entry_for(
                        compiled.load_record(home, slug),
                        compiled.region_key(host_path, target),
                    )
                    observed = compiled.sha256_hex(region)
                    verdict = compiled.verdict_for(entry, observed)
                    if verdict == "edited":
                        # the ONE verdict that is drift — GATE2/REC2's own
                        # refusal semantics, mirrored here as a FAILURE.
                        failures.append(
                            f"{record.id}: {target} was hand-edited outside "
                            f"self-learn (edited) — run `self-learn "
                            f"recompile --adopt {target}`"
                        )
                        continue
                    if verdict == "unknown":
                        plain_notes.append(
                            f"{record.id}: {target} has no compile record "
                            "yet (unknown provenance) — SKIP, tracking "
                            "begins at the next route/recompile"
                        )
                    elif verdict == "stale":
                        plain_notes.append(
                            f"{record.id}: {target} matches the compile "
                            "record's prior observation (stale) — an "
                            "unlanded apply; `self-learn recompile` repairs it"
                        )
                    else:  # "clean" — the ordinary, quiet case
                        plain_notes.append(
                            f"{record.id}: {target} matches its compile "
                            "record (clean)"
                        )
            # U-glob §6.6: for a pathed rule, EITHER scope, re-assert
            # every recorded glob still matches ≥1 file via the same
            # anchored probe route time uses (`glob_reaches`) — the same
            # drift class as a stale marker (files moved out from under
            # the pattern since routing), the same repair (`recompile`
            # surfaces it; the human retargets). A record whose bypass
            # was a deliberate "write-the-rule-first" zero-match (or a
            # legacy record carrying no reason at all) is exempt; a
            # "budget" bypass is NOT exempt — it is re-probed on every
            # audit, because a transient timeout must never buy a
            # permanent exemption (M10: 17.95s cold vs 3.7s warm — a
            # single cold-cache run can produce one). A LIVE "budget"
            # verdict during THIS audit is skipped silently, never
            # reported as drift — only a positive "none" determination
            # is (the gate refuses on "could not tell"; the audit does
            # not, §6.6's asymmetry).
            routing = record.routing or {}
            if routing.get("variant") == "rules":
                paths = routing.get("rules_paths") or []
                reason = routing.get("glob_bypass_reason")
                legacy_bypass = (
                    routing.get("allow_empty_glob") is True
                    and "glob_bypass_reason" not in routing
                )
                exempt = reason == "zero-match" or legacy_bypass
                if paths and not exempt:
                    if record.scope == "project":
                        host = bucket_project_path(bucket.path)
                        roots = (host,) if host is not None else None
                    else:
                        roots = _user_reachability_roots(
                            home, DEFAULT_USER_CLAUDE_MD.expanduser()
                        )
                    if roots is not None:
                        stale = [
                            p for p in paths if glob_reaches(roots, p) == "none"
                        ]
                        if stale:
                            listed = ", ".join(repr(p) for p in stale)
                            roots_str = ", ".join(str(r) for r in roots)
                            failures.append(
                                f"{record.id}: glob pattern(s) now match "
                                f"nothing under {roots_str}: {listed} — the "
                                "rule has gone stale (files moved); no "
                                "automated repair, the human retargets the "
                                "pattern"
                            )
    if failures:
        return False, "; ".join(failures)
    if not checked:
        return True, "no routed managed-destination records — no drift possible"
    ok_message = f"{checked} routed record(s) present in their compiled targets"
    if plain_notes:
        ok_message = ok_message + " — " + "; ".join(plain_notes)
    return True, ok_message


def _check_capture(home: Path) -> tuple[bool, str]:
    """(a) Round-trip a scratch record in a temp bucket under the home."""
    try:
        with tempfile.TemporaryDirectory(dir=home, prefix=".selftest-") as scratch:
            pending = Path(scratch) / "pending"
            pending.mkdir()
            record = Record.create(
                type="knowledge",
                scope="project",
                source="teach",
                fact="selftest scratch record — created and deleted in place.",
            )
            path = pending / f"{record.id}.md"
            record.write(path)
            Record.from_path(path).validate()
            path.unlink()
    except OSError as exc:
        return False, f"cannot write under {home}: {exc}"
    except RecordError as exc:
        return False, f"scratch record failed round-trip: {exc}"
    return True, f"scratch record round-tripped under {home}"


def _check_compiler(targets: dict[Path, list[Record]]) -> tuple[bool, str]:
    """(b) In-memory regeneration for every routed-to target; no writes.

    FW-66: the same class of gap as reach/drift — a target that exists
    but is not valid UTF-8 (hand edit, bad merge) must FAIL naming the
    file, never traceback (this check runs FIRST among the seven, so an
    unguarded read here crashed `--selftest` before any row printed)."""
    if not targets:
        return True, "no routed records — nothing to compile"
    for target, records in targets.items():
        try:
            text = target.read_text(encoding="utf-8") if target.is_file() else ""
        except UnicodeDecodeError as exc:
            return False, f"{target}: not readable as UTF-8 ({exc})"
        try:
            compile_managed_text(text, records)
        except CompileError as exc:
            return False, f"{target}: {exc}"
    n = len(targets)
    return True, f"regenerated {n} managed section{'s' if n != 1 else ''} in-memory"


def _check_markers(targets: dict[Path, list[Record]]) -> tuple[bool, str]:
    """(c) 02 §4: flag ONLY targets that should have a section but have a
    missing/broken marker pair.

    FW-66: an undecodable target FAILs naming the file (same treatment as
    the missing-file branch just above it), never a raw traceback."""
    failures: list[str] = []
    for target, records in sorted(targets.items()):
        n = len(records)
        why = f"{n} routed record{'s' if n != 1 else ''}"
        if not target.is_file():
            failures.append(f"{target} ({why}): file missing")
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{target} ({why}): not readable as UTF-8 ({exc})")
            continue
        begins, ends = text.count(BEGIN_MARKER), text.count(END_MARKER)
        if begins == 0 and ends == 0:
            failures.append(f"{target} ({why}): marker pair missing")
        elif (begins, ends) != (1, 1):
            failures.append(
                f"{target} ({why}): broken markers ({begins} begin / {ends} end)"
            )
        elif text.index(END_MARKER) < text.index(BEGIN_MARKER):
            failures.append(f"{target} ({why}): end marker precedes begin marker")
    if failures:
        return False, "; ".join(failures)
    if not targets:
        return True, "no routed records — no section owed anywhere"
    return True, f"marker pairs intact on {len(targets)} target(s)"


def claude_runtime_dir() -> Path:
    """Where hook symlinks + settings.json live: ``SELF_LEARN_CLAUDE_DIR``
    (tests) or ``~/.claude``. Read-only for every check here."""
    env = os.environ.get("SELF_LEARN_CLAUDE_DIR")
    return Path(env) if env else Path("~/.claude").expanduser()


def _registered_hook_commands(settings_path: Path) -> tuple[list[str], str | None]:
    """Every hook command string registered in settings.json (all events).
    Returns (commands, problem) — problem is set when the file exists but
    cannot be parsed (a broken settings.json must FAIL loudly, not read as
    'nothing registered')."""
    if not settings_path.is_file():
        return [], None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"unparseable {settings_path}: {exc}"
    commands: list[str] = []
    hooks_cfg = data.get("hooks")
    if not isinstance(hooks_cfg, dict):
        return [], None
    for entries in hooks_cfg.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks") or []:
                cmd = hook.get("command") if isinstance(hook, dict) else None
                if isinstance(cmd, str):
                    commands.append(cmd)
    return commands, None


def _check_hooks(home: Path, claude_dir: Path) -> tuple[bool, str]:
    """M3 selftest extension (08 §8.1 Hook-selftest pin), read-only:

    - every CURRENTLY-ROUTED hook record's script exists, is executable,
      and carries the APPROVED bytes (``routing.hook.script``) — anything
      else FAILs naming ``self-learn recompile``;
    - a superseded/graduated hook record whose script still exists is an
      incomplete supersession (the M3-4 removal did not finish);
    - any settings.json registration referencing a ``self-learn-*`` hook
      whose ``~/.claude/hooks`` symlink is missing or dangling is flagged
      (the exact drift that silently no-ops a guard — repo doctrine).

    Loud, never mutating. Ledger-side checks skip cleanly when hosts.yaml
    is absent (nothing registered → nothing compiled anywhere), same rule
    as the drift check."""
    failures: list[str] = []
    checked = 0
    stale = 0

    hosts_known = hosts_path(home).is_file()
    root = None
    if hosts_known:
        try:
            root = load_hosts(home).skills_root
        except HostsError as exc:
            failures.append(f"hosts.yaml unreadable: {exc}")

    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except (RecordError, UnicodeDecodeError):
                continue
            routing = record.routing or {}
            if routing.get("destination") != "hook":
                continue
            meta = routing.get("hook") or {}
            rel = meta.get("script_path")
            live = record.status == "routed" and record.superseded_by is None
            if not hosts_known:
                continue  # skip cleanly — mirrored on the summary below
            if rel is None or root is None:
                if live:
                    failures.append(
                        f"{record.id}: hook-routed but its script is "
                        "unresolvable (no routing.hook.script_path or no "
                        "skills root) — supersede + re-route"
                    )
                continue
            script = root / rel
            if live:
                checked += 1
                if not script.is_file():
                    failures.append(
                        f"{record.id}: hook script {script} missing — run "
                        "`self-learn recompile`"
                    )
                elif not script.stat().st_mode & 0o100:
                    failures.append(
                        f"{record.id}: hook script {script} is not "
                        "executable — run `self-learn recompile`"
                    )
                elif script.read_text(encoding="utf-8") != meta.get("script"):
                    failures.append(
                        f"{record.id}: hook script {script} drifted from "
                        "the approved bytes — never hand-edit a generated "
                        "guard; run `self-learn recompile` (durable change "
                        "= supersede)"
                    )
            elif script.is_file():
                stale += 1
                failures.append(
                    f"{record.id}: INCOMPLETE SUPERSESSION — record is "
                    f"{record.status} but its script {script} still "
                    "exists; remove it and retire its settings.json entry"
                )

    settings_path = claude_dir / "settings.json"
    commands, problem = _registered_hook_commands(settings_path)
    if problem is not None:
        failures.append(problem)
    registrations = 0
    for cmd in commands:
        name = Path(cmd).name
        if not name.startswith("self-learn-"):
            continue
        registrations += 1
        link = claude_dir / "hooks" / name
        # exists() follows symlinks: a dangling symlink reads as missing —
        # exactly the silently-no-op'd-guard failure this check exists for.
        if not link.exists():
            failures.append(
                f"settings.json registers {cmd} but {link} is missing or "
                "dangling — run ./install.sh (or retire the entry)"
            )

    if failures:
        return False, "; ".join(failures)
    if not hosts_known and checked == 0 and registrations == 0:
        return True, "hosts.yaml absent — hook scripts not checked"
    if checked == 0 and registrations == 0:
        return True, "no hook-routed records and no self-learn registrations"
    return True, (
        f"{checked} live hook script(s) intact; {registrations} "
        "registration(s) resolvable"
    )


def _check_surface(home: Path, claude_dir: Path) -> tuple[bool, str]:
    """U-pointer §4/§5: the reachability-emitter row. Read-only render of
    :func:`reachability.reachability_rows` — every per-record verdict is
    computed there; this function only counts and formats (§4.3's "one
    predicate, two renderers" rule).

    Refusal posture FIRST (r1 M-E), byte-identical in shape to
    :func:`_check_reach`'s opening: a `missing`/`not-a-repo` home FAILs
    loud rather than certifying a ledger nobody can see; an absent
    `hosts.yaml` is a clean, unmeasured PASS (nothing is registered, so
    nothing is compiled anywhere to check).

    The row's message grammar is NORMATIVE (§4.4): the head is present on
    every run, `; <U> UNMEASURABLE` / `; <X> UNREACHABLE` are present iff
    their count is nonzero, and the parenthetical names the DISTINCT
    unmeasurable reasons actually present — the resolved `claude_dir` is
    appended to it only when `claude-dir-absent` or `settings-unparseable`
    is among them (never unconditionally, r2 MAJOR 2)."""
    state = home_state(home)
    if state in ("missing", "not-a-repo"):
        return False, home_state_message(state, home)
    if not hosts_path(home).is_file():
        return True, "hosts.yaml absent — reachability not checked"

    rows = reachability_rows(home, claude_dir)
    total = len(rows)
    if not total:
        return True, "no records in the reachability domain"

    reachable = [r for r in rows if r.state == "reachable"]
    unreachable = [r for r in rows if r.state == "unreachable"]
    unmeasurable = [r for r in rows if r.state == "unmeasurable"]

    # §4.4a: the one reason-specific override — `settings-unparseable`
    # fails the row (the instrument is present and broken), everything
    # else `unmeasurable` merely counts (the instrument is absent, not
    # the canon broken).
    fails_on_settings = any(r.reason == "settings-unparseable" for r in unmeasurable)
    ok = not unreachable and not fails_on_settings

    msg = f"{len(reachable)} of {total} verified reachable"
    if unmeasurable:
        msg += f"; {len(unmeasurable)} UNMEASURABLE"
    if unreachable:
        msg += f"; {len(unreachable)} UNREACHABLE"
    if unmeasurable:
        reasons = sorted({r.reason for r in unmeasurable})
        note = ", ".join(reasons)
        if "claude-dir-absent" in reasons or "settings-unparseable" in reasons:
            note += f" — {claude_dir}"
        msg += f" (unmeasurable: {note})"
    return ok, msg


def _check_sentinel() -> tuple[bool, str]:
    """(d) Hold + release a probe at the real cache-path resolution. A
    pre-existing LIVE sentinel belongs to another flow: heartbeat it as
    proof of writability, never delete it."""
    path = sentinel.sentinel_path()
    try:
        hold = sentinel.hold()
        if hold.owned:
            hold.release()
            return True, f"probe held and released at {path}"
        if sentinel.heartbeat():
            return True, f"live sentinel at {path} (another flow) — heartbeat ok"
        return False, f"live sentinel at {path} vanished mid-probe"
    except OSError as exc:
        return False, f"cannot write sentinel at {path}: {exc}"


def _check_invocation(home: Path) -> tuple[bool, str]:
    """`Doc-0`/`DC11` -- computed PROGRAMMATICALLY from
    :func:`provider.preflight`, never by parsing `doctor invocation`'s
    printed text. `ok` is `False` iff the doctor produced at least one
    FAIL row."""
    rows = provider.preflight(home)
    ok = not any(row.verdict == "FAIL" for row in rows)
    if ok:
        return True, "run `self-learn doctor invocation` for details"
    failing = ", ".join(sorted({row.name for row in rows if row.verdict == "FAIL"}))
    return False, f"FAIL row(s): {failing} — run `self-learn doctor invocation` for details"


def run_selftest(home: Path) -> int:
    """All checks, each loud; non-zero on any FAIL."""
    if not home.is_dir():
        print(
            f"selftest: SELF_LEARN_HOME {home} does not exist — nothing to "
            "check (set SELF_LEARN_HOME or clone the ledger repo first)",
            file=sys.stderr,
        )
        return 1

    targets = _section_targets(home)
    results = [
        ("capture", *_check_capture(home)),
        ("compiler", *_check_compiler(targets)),
        ("markers", *_check_markers(targets)),
        ("drift", *_check_drift(home)),
        ("reach", *_check_reach(home)),
        ("hooks", *_check_hooks(home, claude_runtime_dir())),
        ("surface", *_check_surface(home, claude_runtime_dir())),
        ("sentinel", *_check_sentinel()),
        ("invocation", *_check_invocation(home)),
    ]

    failed = 0
    for name, ok, reason in results:
        verdict = "PASS" if ok else "FAIL"
        failed += 0 if ok else 1
        print(f"selftest: {verdict} {name} — {reason}")
    print("selftest: worker: M2 — not checked")

    if failed:
        print(f"selftest: {failed} of {len(results)} checks FAILED", file=sys.stderr)
        return 1
    print(f"selftest: all {len(results)} checks green")
    return 0
