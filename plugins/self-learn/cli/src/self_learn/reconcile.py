"""Self-healing for orphaned ledger writes (audit 2026-07-16 round 7 MAJOR 4).

The ledger has **no watcher** (doc 13 H-5: every producer commits its own
writes), and every producer pathspec-commits ONLY its own paths (doc 08 §1
Resolution-verbs pin, BLOCKER 4 layer b). Those two rules compose into a
hole: a record whose producer wrote it and then failed to commit it is
committed by *nobody, ever*. It sits untracked until a ``git clone``
deletes it — and the miner's cursors have already advanced past its
origin, so it is never re-mined either (origin dedup reads landed records
off disk, and a file nobody committed still answers "already mined" to the
one process that could re-create it).

Probed shapes of the hole:

- ``mine``'s landing commit fails → ``_advance_cursors`` runs anyway. The
  ``landed-uncommitted`` status and the non-zero exit are HONEST, but
  honesty is not recovery: the records are lost on the next clone (MAJOR
  4).
- ``teach``'s capture commit fails → the record is on disk, and the CLI
  prints a repair command for a human to paste (BLOCKER B).

Reporting a data-loss window is not closing it. This module closes it: one
capability that finds orphaned ledger writes and commits them, under the
lock, by pathspec, with the pinned subject :data:`RECONCILE_SUBJECT`. It
is wired at three surfaces so the system heals without being asked:

1. ``self-learn reconcile`` — the human/agent-facing verb, and the command
   ``teach``'s capture-failure message now names as the repair.
2. ``miner.run`` calls it at run START — so a failed landing is committed
   by the NEXT nightly run, before it mines anything new. That is what
   turns "the records are lost on the next clone" into "the records are
   committed within a day, automatically".
3. ``self-learn push`` calls it first — publishing a ledger whose records
   are not even committed is the one moment the gap is most visible.

**Safety against a concurrent producer.** The scan runs INSIDE the commit
lock, not before it. That is load-bearing and only became true this round:
now that every producer takes the lock BEFORE its first mutation (the
round-7 invariant), a producer is never mid-write while we hold the lock,
so anything the scan sees uncommitted under the lock is orphaned BY
DEFINITION rather than merely in-flight. The commit is then pathspec-scoped
to exactly the paths the scan found (:func:`gitops.commit` with ``paths``),
so even a producer that starts the instant we release cannot have its work
absorbed into our commit.

**What it will NOT do.** It commits only files that EXIST and are
untracked-or-modified. It never commits a deletion and never touches a
staged rename: a half-committed ``git mv`` (the shape a resolution verb
leaves when its commit fails) must not be committed one half at a time —
that is the exact corruption :func:`gitops.known_paths` exists to prevent,
"the record in BOTH pending/ and resolved/, git status clean, exit 0".
Those entries are REPORTED as blocked, naming the verb's own printed
repair. Reconcile heals the shape it understands and refuses to guess at
the one it does not.

**M-C: content is validated too, all-or-nothing.** Deciding by PATH SHAPE
alone (what the module did through round 7) is not enough: a producer can
die after writing GARBAGE bytes just as easily as after writing good ones,
and a path-shape match commits either one identically. Probed as C09: a
``compiled/host.yaml`` whose entire content was ``host: [`` (unparseable
YAML) landed as a clean heal, because nothing ever looked inside the file.
Before staging anything, every orphan is now dispatched by asset kind to
the validator that already exists for that kind when writing it for real
— :meth:`records.Record.from_path` (which calls
:meth:`~records.Record.validate`) for a record, :func:`ledger_ops.
validate_proposal` (against its own record, the same way :func:`ledger_ops.
write_proposal` resolves one) for a proposal sibling, :func:`compiled.
load_record` plus a schema this module owns for a compile record, and a
schema this module owns for ``meta.yaml`` (see :func:`_validate_meta` /
:func:`_validate_compiled` for why those two live here and not beside
their writers). **Any single invalid member, or any blocked rename,
refuses the WHOLE batch** — nothing is staged, not even the other orphans
that were perfectly fine. That generalizes the pre-existing rename
refusal (a half-committed ``git mv`` beside an otherwise-clean orphan used
to still get that orphan committed — the "mixed" case now stays fully
uncommitted too) rather than adding a second, differently-scoped kind of
refusal next to it. Callers that must not block on this (the miner) log
every offender and carry on; see ``miner._run_locked``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml.error import YAMLError

from . import compiled, config, gitops, hosts, intents, ledger_ops
from .records import Record, RecordError

__all__ = [
    "RECONCILE_SUBJECT",
    "ReconcileResult",
    "find_orphans",
    "reconcile",
]

#: Every exception a per-kind validator below can raise for content that
#: is parseable-as-YAML/mapping but wrong, or not even parseable, or not
#: even READABLE. What each asset path can actually raise, by kind:
#:
#: - **record** (`Record.from_path` → `Record.from_text`): no guard at
#:   all — a malformed frontmatter raises `YAMLError` RAW, an undecodable
#:   byte raises `UnicodeDecodeError` RAW (probed: a corrupt
#:   `pending/lrn-*.md` orphan crashed the whole mine run with "'utf-8'
#:   codec can't decode ..." instead of being reported invalid, mirroring
#:   the exact skip `miner._find_record` already gives this same byte
#:   shape — its own `except (RecordError, UnicodeDecodeError): return
#:   None`), and — the fold's BLOCKER-1 — an UNREADABLE file (permission
#:   denied, EIO) raises `OSError` RAW too, since `Path.read_text` is
#:   called with no `try` at all. A validated record raises the wrapped
#:   `RecordError`.
#: - **proposal**/**meta**: already wrap unparseable YAML, bad UTF-8, AND
#:   an unreadable file into their own domain error
#:   (`ledger_ops._load_yaml_map`'s own `except (YAMLError, OSError,
#:   UnicodeDecodeError)`) before this module ever sees it.
#: - **compiled**: `_validate_compiled` reads *path* itself (see its own
#:   docstring for why, a fold NIT) and wraps the identical three classes
#:   the same way `compiled.load_record` would have.
#:
#: `OSError` is listed here regardless of which kind actually needs it,
#: so a record orphan's raw case and every other kind's already-wrapped
#: case are refused uniformly by the same tuple, not by kind-specific
#: reasoning at the call site.
#:
#: `records.py` is out of lane scope to fix at its source, so all three
#: raw classes are caught here instead. Caught BY NAME (never a bare
#: ``except Exception``) so a *bug* in a validator — a ``TypeError``, an
#: ``AttributeError`` — still surfaces as a crash, not a silently
#: "invalid" orphan.
_ASSET_ERRORS = (
    RecordError,
    ledger_ops.LedgerOpsError,
    compiled.CompiledRecordError,
    hosts.HostsError,
    config.ConfigWriteError,
    YAMLError,
    UnicodeDecodeError,
    OSError,
)

#: The pinned commit subject. ``{n}`` is the record count.
RECONCILE_SUBJECT = "self-learn: reconcile {n} uncommitted record(s)"

#: Bucket-relative shapes reconcile owns, each paired with the asset kind
#: M-C dispatches it to for content validation (`_classify`). A file
#: under a bucket that matches none of these (a stray note, an editor
#: swapfile) is NOT the ledger's truth and is left alone — reconcile
#: commits records, it does not sweep directories.
_RECONCILABLE_KINDS: tuple[tuple[str, str], ...] = (
    ("pending/lrn-*.md", "record"),
    ("resolved/lrn-*.md", "record"),
    ("proposals/*.yaml", "proposal"),
    ("meta.yaml", "meta"),
)

#: U-hostmode RCN1 (widened M-W/D7): HOME-relative ledger truth — never
#: inside a bucket, so each needs its own check rather than a
#: `_RECONCILABLE_KINDS` entry, which `_classify` matches bucket-
#: relatively. `hosts.yaml`/`config.yaml` close the M-W gap: neither had
#: ANY path-shape match here before (`hosts.save_hosts` writes
#: `hosts.yaml`, `config.dump_editable` writes `config.yaml`, and a crash
#: between either write and its commit was invisible to `find_orphans` —
#: not even reported `blocked`, just silently never healed).
_RECONCILABLE_HOME: tuple[tuple[str, str], ...] = (
    ("compiled/*.yaml", "compiled"),
    ("hosts.yaml", "hosts"),
    ("config.yaml", "config"),
)

#: Porcelain XY codes that mean "this path has a staged deletion or
#: rename" — the half-committed-``git mv`` shape reconcile must not touch.
_BLOCKING_CODES = ("R", "D")


@dataclass(frozen=True)
class ReconcileResult:
    """``committed`` — what landed (empty = nothing to do, the normal
    case, OR the batch was refused — see ``refused``). ``blocked`` —
    porcelain entries reconcile refused to guess at, verbatim, for a
    human (a half-committed ``git mv``). ``invalid`` (M-C) — orphans that
    parsed by path shape but failed their asset-kind content check, one
    ``"<path>: <reason>"`` string each. ``stopped`` (M-W/D7) — intent ids
    :func:`intents.recover` could not resolve (neither roll-forward nor
    restore verified), one ``"<intent-id>: <reason>"`` string each; the
    intent file is left in place for a human. ``rolled_forward`` /
    ``restored`` (M-W/D7) — intent ids :func:`intents.recover` resolved,
    by which of the two outcomes. ``push`` — None when nothing was
    committed or ``no_push``."""

    committed: list[Path] = field(default_factory=list)
    sha: str | None = None
    blocked: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    rolled_forward: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    push: gitops.PushResult | None = None

    @property
    def healed(self) -> bool:
        return bool(self.committed or self.rolled_forward or self.restored)

    @property
    def acted(self) -> bool:
        """True iff an intent recovery COMPLETED (rolled forward or
        restored) — the :func:`intents.RecoverResult.acted` mirror for
        this dataclass (gate r1 nit-2), so callers stop re-spelling
        ``rolled_forward or restored`` by hand. Deliberately excludes
        ``committed`` (that is ``healed``'s own job) and ``stopped``
        (nothing acted there — it is the one outcome that touches
        nothing, by design)."""
        return bool(self.rolled_forward or self.restored)

    @property
    def refused(self) -> bool:
        """M-C (widened M-W/D7): true iff the batch was refused whole, OR
        an intent recovery could not resolve — either way ``committed``
        is not the full picture and a caller must surface the offenders
        rather than treat this as a quiet no-op."""
        return bool(self.blocked or self.invalid or self.stopped)


def _porcelain(home: Path) -> list[tuple[str, Path]]:
    """``git status --porcelain -uall`` → [(XY, path)]. ``-uall`` so a
    wholly-untracked BUCKET reports its files rather than the directory
    (the miner's very first landing into a new project bucket is exactly
    that case, and a directory pathspec would over-commit)."""
    proc = gitops._git(  # noqa: SLF001 — same module family
        home, "status", "--porcelain", "-uall"
    )
    if proc.returncode != 0:
        raise gitops.GitOpsError(
            f"git status in {home} failed: {(proc.stderr or proc.stdout).strip()}"
        )
    out: list[tuple[str, Path]] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        xy, rest = line[:2], line[3:]
        if " -> " in rest:  # rename: both halves, kept whole for the report
            rest = rest.split(" -> ", 1)[1]
        out.append((xy, home / rest.strip('"')))
    return out


def _classify(home: Path, path: Path) -> str | None:
    """Which asset kind *path* is, for M-C's per-kind content dispatch —
    ``None`` when *path* is not one reconcile owns at all. Also the one
    place path-shape matching happens; `_is_reconcilable` is this
    compared to ``None``."""
    for pattern, kind in _RECONCILABLE_HOME:
        if path.parent == (home / pattern).parent and path.match(pattern):
            return kind
    from .ledger import discover_buckets

    for bucket in discover_buckets(home):
        for pattern, kind in _RECONCILABLE_KINDS:
            if path.parent == (bucket.path / pattern).parent and path.match(pattern):
                return kind
    return None


def _is_reconcilable(home: Path, path: Path) -> bool:
    """True iff *path* is a ledger record/proposal/meta inside a bucket,
    OR (U-hostmode RCN1) a compile record directly under *home*."""
    return _classify(home, path) is not None


def _validate_meta(path: Path) -> None:
    """``meta.yaml``'s schema (M-C) — there was none before this move:
    :func:`ledger_ops._load_yaml_map` (parse-plus-is-mapping only, same
    shape C09 exploited on the compile record) is all a ``meta.yaml``
    orphan was ever checked against. The writer, :func:`ledger_ops.
    ensure_project_meta`, always writes exactly ``{"path": <resolved
    project path>}``; this checks the one key its only reader,
    :func:`ledger_ops.bucket_project_path`, relies on."""
    data = ledger_ops._load_yaml_map(path)  # noqa: SLF001 — this check's only owner
    value = data.get("path")
    if not isinstance(value, str) or not value.strip():
        raise ledger_ops.ProposalError(
            f"meta.yaml needs a non-empty 'path' string (written by "
            f"ledger_ops.ensure_project_meta), got {value!r}"
        )


def _validate_compiled(path: Path) -> None:
    """The compile record's schema (M-C) — C09 itself: an unparseable
    file (``host: [``) is turned into :class:`compiled.CompiledRecordError`
    below, same as :func:`compiled.load_record` already does, but a
    PARSEABLE mapping missing its required keys sailed through uncaught.
    The writer, :func:`compiled.write_entry`, always sets ``host``,
    ``mode``, and a ``targets`` mapping at the top level; this checks
    those three.

    Reads *path* directly (`compiled._yaml()`, an existing function of
    that module, same as :func:`compiled.load_record` uses internally)
    rather than calling ``compiled.load_record(home, path.stem)`` — a
    fold NIT: that call RE-DERIVES ``<home>/compiled/<slug>.yaml`` from
    ``home``/``path.stem`` instead of using the exact ``path`` this
    function was handed, the same path `find_orphans` found orphaned;
    only ever the same file today, but a needless round-trip that could
    silently validate a different file than the one flagged.

    A second gap, the same crash class as the ``_ASSET_ERRORS`` widening
    above: ``load_record``'s own ``dict(data) if data else {}`` is
    unguarded against a PARSEABLE non-mapping top level — a compiled
    record whose entire content is ``- a`` (a sequence) or ``5`` (a
    scalar) parses fine, then ``dict(['a'])`` raises ``ValueError`` and
    ``dict(5)`` raises ``TypeError``. Caught here, by name, and wrapped
    into the same :class:`compiled.CompiledRecordError` the unparseable
    case already raises — never a bare ``except Exception``, so an
    actual bug still surfaces as a crash.

    No ``path.is_file()`` pre-check (fold NIT-3, r2): every caller only
    ever hands this an orphan `find_orphans` just found ON DISK, so a
    missing file here means the TOCTOU case — something removed it
    between the scan and this validation — not the ordinary "no record
    yet" case :func:`compiled.load_record` itself has to handle for its
    OWN, unrelated callers. A pre-check that silently treated "vanished"
    as ``{}`` reported that race as "missing required keys" — a false
    diagnosis (it reads as an incomplete file, not an absent one). Now
    ``path.read_text()`` raises the real ``FileNotFoundError`` (an
    ``OSError``), caught below and reported honestly."""
    try:
        raw = compiled._yaml().load(path.read_text(encoding="utf-8"))  # noqa: SLF001
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        raise compiled.CompiledRecordError(f"unparseable {path}: {exc}") from exc
    try:
        data = dict(raw) if raw else {}
    except (TypeError, ValueError) as exc:
        raise compiled.CompiledRecordError(
            f"{path.name} is not a YAML mapping (dict(): {exc})"
        ) from exc
    missing = [key for key in ("host", "mode", "targets") if key not in data]
    if missing:
        raise compiled.CompiledRecordError(
            f"{path.name} missing {missing} (written by compiled.write_entry)"
        )
    if not isinstance(data["targets"], dict):
        raise compiled.CompiledRecordError(
            f"{path.name} 'targets' must be a mapping, got {data['targets']!r}"
        )


def _validate_proposal(home: Path, path: Path) -> None:
    """A proposal sibling's schema (M-C): :func:`ledger_ops.
    validate_proposal`, resolved against ITS OWN record the same way
    :func:`ledger_ops.write_proposal` does (record text + scope), never
    the bare parse-plus-is-mapping :func:`ledger_ops.read_proposal` alone
    gives you. A ``merge-*.yaml`` sibling has no single record to resolve
    — it validates against :func:`ledger_ops.validate_merge_proposal`
    instead, the same 02 §1 family."""
    data = ledger_ops.read_proposal(path)
    if path.stem.startswith("merge-"):
        ledger_ops.validate_merge_proposal(data)
        return
    record_path = ledger_ops.find_record_path(home, path.stem)
    record = Record.from_path(record_path)
    ledger_ops.validate_proposal(
        data, record_text=record.to_text(), scope=record.scope, home=home
    )


def _validate_orphans(home: Path, orphans: list[Path]) -> list[str]:
    """Dispatch every *orphan* to its asset-kind validator (M-C), BEFORE
    staging anything. One ``"<path>: <reason>"`` string per orphan that
    fails; empty when every orphan validates — which is the only case
    the caller may go on to stage+commit the batch."""
    invalid: list[str] = []
    for path in orphans:
        kind = _classify(home, path)
        try:
            if kind == "record":
                Record.from_path(path)
            elif kind == "proposal":
                _validate_proposal(home, path)
            elif kind == "meta":
                _validate_meta(path)
            elif kind == "compiled":
                _validate_compiled(path)
            elif kind == "hosts":
                # M-W/D7: the writer's own parser IS the schema check
                # (`hosts.load_hosts` already raises `HostsError` on
                # unparseable/malformed content) — no second, reconcile-
                # owned validator to keep in sync with hosts.py's own.
                hosts.load_hosts(home)
            elif kind == "config":
                # Same reasoning as `hosts` above: `config.load_editable`
                # is config.py's own WRITE-time parser (raises
                # `ConfigWriteError` on unparseable/non-mapping content),
                # reused here rather than duplicated.
                config.load_editable(home)
            # kind is never None here: every `path` came from
            # `find_orphans`, which already filtered by `_is_reconcilable`.
        except _ASSET_ERRORS as exc:
            invalid.append(f"{path}: {exc}")
    return invalid


def find_orphans(home: Path) -> tuple[list[Path], list[str]]:
    """(paths to commit, blocked porcelain lines). Callers that intend to
    COMMIT the result must already hold :func:`gitops.commit_lock` — see
    the module docstring for why the scan belongs inside the lock."""
    orphans: list[Path] = []
    blocked: list[str] = []
    for xy, path in _porcelain(home):
        if not _is_reconcilable(home, path):
            continue
        if any(c in _BLOCKING_CODES for c in xy):
            blocked.append(f"{xy} {path}")
            continue
        if path.exists():
            orphans.append(path)
    return sorted(set(orphans)), blocked


def reconcile(home: Path, *, no_push: bool = False) -> ReconcileResult:
    """Commit every orphaned ledger write, under the lock, by pathspec —
    ALL of them, or none (M-C).

    Idempotent and cheap: on a clean ledger it takes the lock, runs one
    ``git status``, and returns an empty result — which is why the miner
    and ``push`` can call it unconditionally. When ``find_orphans`` did
    find something, every orphan is content-validated by asset kind
    BEFORE anything is staged; a single invalid member, or any blocked
    rename found alongside, refuses the WHOLE batch (``ReconcileResult.
    refused``) — see the module docstring for why a partial heal is not
    an option here. Callers that must never abort on a refusal (the
    miner) read ``result.blocked`` / ``result.invalid`` and carry on.

    M-W/D7: :func:`intents.recover` runs FIRST, BEFORE the
    ``with gitops.commit_lock(home):`` block below — not nested inside
    it (gate r1 nit-1 correction: an earlier revision of this docstring
    claimed nesting; there is none). ``intents.recover`` takes the lock
    itself, does its work, and releases it; THIS function then takes the
    lock again, separately, for its own orphan scan. There is a real gap
    between the two acquisitions in which another process could — in
    principle — take the lock; nothing here corrupts state if it does,
    because a lock is exactly what serializes the two producers against
    each other. The gap DEFERS this call's own orphan scan to the next
    ``reconcile()``, it never LOSES anything. Running recovery first (in
    either lock or not) is still what matters: an incomplete collapse/
    rebind leaves a staged rename, which ``find_orphans`` would otherwise
    report ``blocked`` forever (never reconcile's to complete one file at
    a time); recovering it first means the orphan scan below only ever
    sees a clean-or-ordinary tree.

    Gate r1 BLOCKER-1: a STOPped recovery — :func:`intents.recover`
    could resolve neither roll-forward nor restore for some intent —
    now refuses this call's WHOLE orphan batch too, the same
    all-or-nothing contract ``blocked``/``invalid`` already carry (see
    the guard just above the orphan commit below). Consequence: once
    anything has moved HEAD past a stuck intent's recorded ``old_sha``
    for any of its steps, that STOP is permanent by construction — it
    freezes ALL orphan healing under this ``home``, including the
    miner's own carried-over ``landed-uncommitted`` records from an
    unrelated earlier run, until a human clears it. Clearing it means:
    read the offender named in ``result.stopped``, decide by hand
    whether its current on-disk state is acceptable, then delete
    ``<home>/.intents/<id>.json`` and re-run ``reconcile``."""
    home = Path(home)
    recovered = intents.recover(home)
    with gitops.commit_lock(home):
        orphans, blocked = find_orphans(home)
        if not orphans:
            return ReconcileResult(
                blocked=blocked,
                stopped=recovered.stopped,
                rolled_forward=recovered.rolled_forward,
                restored=recovered.restored,
            )
        invalid = _validate_orphans(home, orphans)
        # Gate r1 BLOCKER-1: a STOPped intent must refuse this batch too,
        # not just `blocked`/`invalid` — the orphan scan above runs AFTER
        # `intents.recover()` and can see, and stage, the very files a
        # stuck transaction half-wrote (a merged survivor's `pending/`
        # copy, `hosts.yaml`'s half-written bytes once M-W/D7 widened
        # `_RECONCILABLE_HOME` to reach it). Committing those while
        # reporting `recovered.stopped` — an exit code documented
        # elsewhere as "nothing was written" — would corrupt the ledger
        # UNDER the exact promise meant to prevent that.
        if blocked or invalid or recovered.stopped:
            return ReconcileResult(
                blocked=blocked,
                invalid=invalid,
                stopped=recovered.stopped,
                rolled_forward=recovered.rolled_forward,
                restored=recovered.restored,
            )
        message = RECONCILE_SUBJECT.format(n=len(orphans))
        try:
            gitops.stage(home, orphans)
            sha = gitops.commit(home, message, paths=orphans)
        except gitops.GitOpsError as exc:
            # Post-mutation by construction (the paths are staged now).
            raise gitops.HalfWrittenError.for_commit(
                home, message, orphans, exc
            ) from exc
    # The push is OUTSIDE the lock (it touches no index — see the gitops
    # module docstring for the re-scope).
    push = None if no_push else gitops.push_if_remote(home)
    return ReconcileResult(
        committed=orphans,
        sha=sha,
        blocked=blocked,
        stopped=recovered.stopped,
        rolled_forward=recovered.rolled_forward,
        restored=recovered.restored,
        push=push,
    )
