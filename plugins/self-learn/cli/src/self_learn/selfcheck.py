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
    (e) sentinel writability — hold + release a probe at the real
        cache-path resolution; a pre-existing LIVE sentinel (another
        flow's hold) is heartbeated, never deleted;
    (f) worker check — stubbed M2-conditional: prints
        ``worker: M2 — not checked``.
"""

from __future__ import annotations

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
from .verbs import DEFAULT_USER_CLAUDE_MD

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
        Record.from_path(record_path)  # an unparseable record cannot be stamped
        validate_proposal(read_proposal(yaml_sibling))
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
    if destination == "claude-md":
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
            except RecordError:
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
            except RecordError:
                continue
            if record.status != "routed" or record.superseded_by is not None:
                continue
            destination = (record.routing or {}).get("destination")
            if destination not in ("skill-md", "claude-md", "reference"):
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
                elif record.id not in ref_target.read_text(encoding="utf-8"):
                    failures.append(
                        f"{record.id}: entry missing from {ref_target} — run "
                        "`self-learn recompile`"
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
            text = target.read_text(encoding="utf-8")
            begin = text.find(BEGIN_MARKER)
            end = text.find(END_MARKER)
            section = text[begin:end] if 0 <= begin < end else ""
            if f"({record.id})" not in section:
                failures.append(
                    f"{record.id}: entry marker missing from {target} — "
                    "run `self-learn recompile`"
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
    """(b) In-memory regeneration for every routed-to target; no writes."""
    if not targets:
        return True, "no routed records — nothing to compile"
    for target, records in targets.items():
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        try:
            compile_managed_text(text, records)
        except CompileError as exc:
            return False, f"{target}: {exc}"
    n = len(targets)
    return True, f"regenerated {n} managed section{'s' if n != 1 else ''} in-memory"


def _check_markers(targets: dict[Path, list[Record]]) -> tuple[bool, str]:
    """(c) 02 §4: flag ONLY targets that should have a section but have a
    missing/broken marker pair."""
    failures: list[str] = []
    for target, records in sorted(targets.items()):
        n = len(records)
        why = f"{n} routed record{'s' if n != 1 else ''}"
        if not target.is_file():
            failures.append(f"{target} ({why}): file missing")
            continue
        text = target.read_text(encoding="utf-8")
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
