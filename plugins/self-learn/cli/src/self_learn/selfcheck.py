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
    (f) sentinel writability — hold + release a probe at the real
        cache-path resolution; a pre-existing LIVE sentinel (another
        flow's hold) is heartbeated, never deleted;
    (g) worker check — stubbed M2-conditional: prints
        ``worker: M2 — not checked``.
"""

from __future__ import annotations

import glob as glob_mod
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from . import gitops
from . import scan as scan_mod
from . import sentinel
from .compilers import (
    BEGIN_MARKER,
    END_MARKER,
    CompileError,
    compile_managed_text,
    reference_target_path,
)
from .hosts import HostsError, hosts_path, load_hosts, skill_dir_for
from .ledger import Bucket, discover_buckets, home_state, home_state_message
from .ledger_ops import (
    ProposalError,
    bucket_project_path,
    find_record_path,
    read_proposal,
    stamp_proposal,
    validate_proposal,
)
from .records import Record, RecordError
from .verbs import DEFAULT_USER_CLAUDE_MD, _project_rules_dir, _user_rules_dir

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
            read_proposal(yaml_sibling), record_text=record.to_text(), scope=record.scope
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
    """The compiled canon file for one skill-md/claude-md record, resolved
    through the hosts registry — the SAME resolution the verbs use
    (doc 13 §4). None = unresolvable (unregistered/missing host)."""
    destination = (record.routing or {}).get("destination")
    if destination == "skill-md" and bucket.scope == "skill":
        try:
            return skill_dir_for(load_hosts(home), bucket.name) / "SKILL.md"
        except HostsError:
            return None
    if destination == "new-skill":
        # T18: the scaffolded skill's SKILL.md is an ordinary managed
        # target from the first route on — routing.new_skill names it.
        name = (record.routing or {}).get("new_skill")
        try:
            root = load_hosts(home).skills_root
        except HostsError:
            return None
        if not name or root is None:
            return None
        return root / "plugins" / name / "skills" / name / "SKILL.md"
    if destination == "claude-md":
        # A2 §5.2/§2.1: variant-aware resolution — a rules/local target
        # is NOT the plain claude-md file. Keyed off routing.get(
        # "variant")/"rules_topic", the SAME stored-routing data the
        # verbs' own retirement/recompile sites read (§4.4B).
        routing = record.routing or {}
        variant = routing.get("variant")
        if variant == "local":
            host = bucket_project_path(bucket.path)
            return None if host is None else Path(host) / "CLAUDE.local.md"
        if variant == "rules":
            topic = routing.get("rules_topic")
            if not topic:
                return None
            if record.scope == "user":
                return _user_rules_dir(DEFAULT_USER_CLAUDE_MD.expanduser()) / f"{topic}.md"
            if record.scope == "project":
                host = bucket_project_path(bucket.path)
                return None if host is None else _project_rules_dir(Path(host)) / f"{topic}.md"
            return None  # skill-scope rules: deferred (§9), never routed
        if record.scope == "user":
            return DEFAULT_USER_CLAUDE_MD.expanduser()
        if record.scope == "project":
            host = bucket_project_path(bucket.path)
            return None if host is None else Path(host) / "CLAUDE.md"
        root = load_hosts(home).skills_root  # skill-scoped claude-md
        return None if root is None else root / "CLAUDE.md"
    return None  # reference/new-skill/hook: no managed markers


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
        return [] if host is None else [Path(host) / "CLAUDE.md"]
    if record.scope == "user":
        return [DEFAULT_USER_CLAUDE_MD.expanduser()]
    return []


#: §2.1 step 2: a token is delimited by whitespace or by any of these
#: bracket/quote characters — never consumed into the match.
_TOKEN_DELIMS = r"\s()\[\]<>\"'`"


def _surface_names_target(surface: Path, target: Path) -> bool:
    """The reachability predicate (§2.1): does ``surface`` contain a path
    TOKEN that RESOLVES to ``target``? Pure text + path arithmetic, no
    globbing — the whole file is searched, not just a managed section (the
    home-assistant ``SKILL.md`` this unit exists for has no managed
    section at all).

    Step 2 is LEFT-MAXIMAL and anchored on the basename: for every
    occurrence of ``target.name`` in the text, the token extends
    LEFTWARD ONLY over non-delimiter characters and ENDS at the basename —
    nothing to its right is ever consumed. This is normative, and the two
    readings differ: a both-directions-maximal tokenizer rejects
    ``see references/LEARNINGS.md.`` (a sentence-final period, the
    commonest hand-written pointer shape); the anchored reading here
    accepts it, and adds no false positives (``myLEARNINGS.md`` still
    yields a token that fails the resolve-and-compare below).

    Steps 3-4 are the half that matters: a bare basename match would pass
    on some OTHER same-named file. Each candidate token is expanduser'd;
    an absolute token is used as-is, else resolved against
    ``surface.parent`` (the token is read as the AUTHOR meant it — a
    relative pointer written in the surface file, relative to that file);
    a match requires the resolved candidate to equal ``target.resolve()``
    exactly (criterion 8b: comparing against an UNRESOLVED target breaks
    the moment the registered skills root is reached through a symlink)."""
    if not surface.is_file():
        return False
    text = surface.read_text(encoding="utf-8")
    pattern = re.compile(f"[^{_TOKEN_DELIMS}]*" + re.escape(target.name))
    resolved_target = target.resolve()
    for match in pattern.finditer(text):
        token = Path(match.group(0)).expanduser()
        candidate = token if token.is_absolute() else surface.parent / token
        if candidate.resolve() == resolved_target:
            return True
    return False


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


def _check_drift(home: Path) -> tuple[bool, str]:
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
    has no canon to have drifted from: that is a true, quiet skip."""
    state = home_state(home)
    if state in ("missing", "not-a-repo"):
        return False, home_state_message(state, home)
    if not hosts_path(home).is_file():
        return True, "hosts.yaml absent — drift not checked"
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
            # A2 §5.2 item 3: for a PROJECT-scope pathed rule ONLY,
            # re-assert every recorded glob still matches ≥1 file — the
            # same drift class as a stale marker (files moved out from
            # under the pattern since routing), the same repair
            # (`recompile` surfaces it; the human retargets). User-scope
            # pathed globs are NOT re-asserted here (no canonical tree,
            # U-A2-glob-tree) — their presence-in-file check above still
            # ran.
            routing = record.routing or {}
            if routing.get("variant") == "rules" and record.scope == "project":
                paths = routing.get("rules_paths") or []
                host = bucket_project_path(bucket.path)
                if host is not None:
                    stale = [
                        p
                        for p in paths
                        if not glob_mod.glob(p, root_dir=host, recursive=True)
                    ]
                    if stale:
                        listed = ", ".join(repr(p) for p in stale)
                        failures.append(
                            f"{record.id}: glob pattern(s) now match nothing "
                            f"in {host}: {listed} — the rule has gone stale "
                            "(files moved); no automated repair, the human "
                            "retargets the pattern"
                        )
    if failures:
        return False, "; ".join(failures)
    if not checked:
        return True, "no routed managed-destination records — no drift possible"
    return True, f"{checked} routed record(s) present in their compiled targets"


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
        ("sentinel", *_check_sentinel()),
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
