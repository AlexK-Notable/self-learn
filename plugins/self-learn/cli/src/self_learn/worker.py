"""Background pre-analysis worker (T13/T14, 08 §7.1 pins; 11's M2 riders).

Kick-driven, never scheduled (E-5): `teach` (without --route) and
`import` end by calling :func:`kick`. Kick mechanics, pinned:

1. ``touch worker.dirty``;
2. under ``flock -n worker.spawn.lock`` (two racing kicks serialize; the
   loser exits absorbed): if ``worker.window`` names a LIVE pid → exit
   (the open window absorbs the kick); else ``setsid``-spawn
   ``self-learn worker run --coalesce`` and write the child pid to
   ``worker.window``. A dead pid in ``worker.window`` = closed window
   (reboot/kill safe).

``--coalesce`` sleeps ``SELF_LEARN_COALESCE_SECS`` (default 600; tests
set ~0), then takes ``worker.lock`` (blocking), removes ``worker.window``
and runs. ``worker.dirty`` is deleted AFTER enumeration, so a kick
landing mid-run re-marks it; at run end, if it exists again, ONE
follow-on window is spawned.

The run sequence and every file it touches are pinned in 08 §7.1
("Worker run sequence" row). The model pass writes PROPOSALS ONLY
(S-5/E-18): the ``--allowedTools`` value carries no Bash and no Edit —
with shell access the write restriction would be void. The CLI stamps
``record_sha`` into every valid proposal (models cannot compute hashes).

11's rider carried here: recurrence-SUSPECT detection is deterministic
CLI machinery (token overlap + origin match against resolved routed
records), spooled as telemetry events — the machine never writes a
record; confirmation is the human ``confirm-recurrence`` verb.

Test hook: ``SELF_LEARN_WORKER_AUTOKICK=0`` makes :func:`kick` a logged
no-op — the test suite sets it globally (conftest) so unrelated
teach/import tests never spawn detached processes; worker tests opt back
in or drive :func:`run` directly.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import sentinel, telemetry
from .hosts import HostsError, load_hosts, skill_dir_for
from .ledger import discover_buckets, resolve_home
from .ledger_ops import bucket_project_path
from .scan import scan as secret_scan
from .ledger_ops import (
    ProposalError,
    _dump_yaml,
    is_unanalyzed,
    queue,
    read_proposal,
    record_title,
    stamp_proposal,
    validate_merge_proposal,
    validate_proposal,
)
from .normalize import sha_anchor
from .records import Record, RecordError

__all__ = [
    "ALLOWED_TOOLS",
    "DEFAULT_COALESCE_SECS",
    "DEFAULT_WORKER_MODEL",
    "DISALLOWED_TOOLS",
    "RunResult",
    "batch_cap",
    "build_argv",
    "cache_dir",
    "kick",
    "package_skill_refs",
    "run",
    "write_permission_rules",
    "write_settings_file",
]

DEFAULT_COALESCE_SECS = 600
DEFAULT_WORKER_MODEL = "claude-sonnet-5"
BATCH_CAP = 15
INVOKE_TIMEOUT_SECS = 15 * 60
EVENTS_CAP_BYTES = 1_000_000
LOG_CAP_BYTES = 1_000_000

#: Escalation thresholds (08 §7.1 — v1 constants; changing them is an edit
#: to the pin, not a config file).
ESCALATE_PENDING = 5
ESCALATE_OLDEST_DAYS = 7
ESCALATE_DEBOUNCE_SECS = 24 * 60 * 60

#: Recurrence-suspect similarity threshold (11 §2.2 rider; deterministic).
SUSPECT_JACCARD = 0.6


def package_skill_refs() -> Path:
    """The skill's references dir, resolved relative to THIS package
    (doc 13 T-H3: doctrine/rubric/registry ship with the product beside
    the skill — never via any home; this also pre-clears the step-2
    product-repo extraction). src/self_learn/worker.py → parents[3] is
    ``plugins/self-learn``."""
    return Path(__file__).resolve().parents[3] / "skills" / "self-learn" / "references"


def cache_dir() -> Path:
    """Per-ledger-home cache namespace (doc 13 §6, H-4):
    ``${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(home)[:8]>/`` —
    a future second home (06's team ledger) is a config away. Resolves
    the home itself via :func:`ledger.resolve_home` (cheap env read).

    Migration shim from the OLD un-namespaced path
    (``…/claude-skills/self-learn`` — the name embeds the host the cache
    no longer belongs to): see :func:`_migrate_cache`."""
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    digest = hashlib.sha256(str(resolve_home()).encode("utf-8")).hexdigest()[:8]
    new = base / "self-learn" / f"home-{digest}"
    new.mkdir(parents=True, exist_ok=True)
    _migrate_cache(base / "claude-skills" / "self-learn", new)
    return new


#: Written only after a COMPLETE migration — its absence means "retry".
MIGRATION_MARKER = ".migrated-from-claude-skills"

#: Live processes hold these (flock / pid window); moving them out from
#: under a running worker or miner is how you get two of them. They are
#: regenerable per-machine state, so they are left behind deliberately.
_MIGRATION_SKIP = ("worker.lock", "worker.spawn.lock", "worker.window")


def _migrate_cache(old: Path, new: Path) -> None:
    """Move the pre-doc-13 cache state into the home-namespaced dir
    (doc 13 §6). Idempotent and RETRIED until it completes: the marker is
    written only after a full clean pass, so a partial move (disk full,
    permissions, a file vanishing mid-move) is re-attempted on the next
    call instead of leaving the rest orphaned in the old path forever
    (audit 2026-07-16 MINOR 9: the shim ran once, only when the new dir
    did not exist, and swallowed every failure with `except: pass`).

    Lock/window files are deliberately NOT moved (:data:`_MIGRATION_SKIP`)
    — a LIVE worker or miner may hold them, and moving a flock'd file out
    from under it lets a second run start; they are regenerable. Every
    move and every failure is logged; nothing here is ever fatal (cache
    state is never load-bearing truth).

    Logging goes through :func:`_log_to` rather than :func:`log`: this
    runs INSIDE :func:`cache_dir`, and ``log`` resolves the cache dir —
    which would recurse until the marker exists.
    """
    if (new / MIGRATION_MARKER).exists() or not old.is_dir():
        return
    moved: list[str] = []
    failed: list[str] = []
    left: list[str] = []
    for entry in sorted(old.iterdir()):
        if entry.name in _MIGRATION_SKIP:
            left.append(entry.name)
            continue
        target = new / entry.name
        if target.exists():
            left.append(entry.name)  # newer state already here — never clobber
            continue
        try:
            shutil.move(str(entry), str(target))
            moved.append(entry.name)
        except (OSError, shutil.Error) as exc:
            failed.append(f"{entry.name} ({exc})")
    if moved or failed:
        _log_to(
            new / "worker.log",
            f"cache migration {old} → {new}: moved {moved or 'nothing'}; "
            f"left {left or 'nothing'}; FAILED {failed or 'nothing'}",
        )
    if failed:
        _log_to(
            new / "worker.log",
            "cache migration incomplete — will retry on the next run",
        )
        return
    try:
        (new / MIGRATION_MARKER).write_text(
            f"{_now_iso()} migrated from {old}\n", encoding="utf-8"
        )
    except OSError as exc:
        _log_to(
            new / "worker.log",
            f"cache migration: marker write failed ({exc}) — will retry",
        )


def _p(name: str) -> Path:
    return cache_dir() / name


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_to(path: Path, message: str) -> None:
    """Append one timestamped line to an EXPLICIT log path (capped ~1 MB).
    The migration shim needs this: it runs inside :func:`cache_dir`, so it
    cannot use :func:`log`, which resolves the cache dir to find its."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_now_iso()} {message}\n")
    except OSError:
        return  # a log we cannot write is never worth failing a run over
    _truncate_oldest(path, LOG_CAP_BYTES)


def log(message: str) -> None:
    """Append one timestamped line to worker.log (capped ~1 MB)."""
    _log_to(_p("worker.log"), message)


def _truncate_oldest(path: Path, cap: int) -> None:
    try:
        if path.stat().st_size <= cap:
            return
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        keep: list[str] = []
        size = 0
        for line in reversed(lines):
            size += len(line.encode("utf-8"))
            if size > cap:
                break
            keep.append(line)
        path.write_text("".join(reversed(keep)), encoding="utf-8")
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def coalesce_secs() -> float:
    raw = os.environ.get("SELF_LEARN_COALESCE_SECS")
    if not raw:
        return float(DEFAULT_COALESCE_SECS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_COALESCE_SECS)


def worker_model() -> str:
    return os.environ.get("SELF_LEARN_WORKER_MODEL") or DEFAULT_WORKER_MODEL


def batch_cap() -> int:
    return BATCH_CAP


#: Read-only tool grant — Write is deliberately ABSENT here: path-scoped
#: Write rules ride the settings file (write_permission_rules); the live
#: CLI's --allowedTools cannot express path scopes (verified at T13 per
#: the pin's own instruction: the flag syntax was adjusted, the PROPERTY
#: is unchanged — no Bash, no Edit, Write only under proposals/).
ALLOWED_TOOLS = "Read,Grep,Glob"
DISALLOWED_TOOLS = "Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch"


def write_permission_rules(home: Path) -> list[str]:
    """The pinned Write scopes on the doc-13 ledger layout, in
    settings-file rule syntax — verified against the LIVE CLI (T13-start
    check, 2026-07-15): file-write scoping rides the ``Edit(...)`` rule
    FAMILY (it governs Write too); ``Write(path)`` rules match nothing.
    `//` = filesystem-absolute, gitignore ** semantics. The Edit TOOL
    itself stays in DISALLOWED_TOOLS. The scopes point at LEDGER
    proposals dirs ONLY — never at any host repo (H-3: no autonomous
    process writes canon)."""
    home = Path(home)
    return [
        f"Edit(/{home}/skills/**/proposals/**)",
        f"Edit(/{home}/projects/**/proposals/**)",
        f"Edit(/{home}/user/proposals/**)",
    ]


def write_settings_file(home: Path) -> Path:
    """Per-run settings file carrying the Write scope (E-18: this file +
    DISALLOWED_TOOLS IS the append-only guarantee)."""
    path = _p("worker.settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"permissions": {"allow": write_permission_rules(home)}},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def build_argv(home: Path, settings_path: Path) -> list[str]:
    """The prompt is deliberately NOT in argv (audit 2026-07-15, shared
    with the miner's B1): Linux caps one argv element at 128 KiB, and a
    full batch — 15 records × (record + canon excerpt) + doctrine +
    registry — plausibly exceeds it. The prompt rides stdin instead."""
    return [
        "claude",
        "-p",
        "--model",
        worker_model(),
        "--allowedTools",
        ALLOWED_TOOLS,
        "--disallowedTools",
        DISALLOWED_TOOLS,
        "--settings",
        str(settings_path),
    ]


# ------------------------------------------------------------------- kick


#: Env var carrying an invoking verb's ``--no-push`` to the worker it
#: spawns (audit 2026-07-16 BLOCKER 3).
NO_PUSH_ENV = "SELF_LEARN_NO_PUSH"


def no_push_requested() -> bool:
    """True iff this process was told not to push.

    THE PROCESS-BOUNDARY READER, and nothing else. A spawn is detached, so
    a parent's flag can only reach a child as inherited environment; the
    child reads it ONCE here, at its dispatch surface, and from there it
    travels as an ordinary parameter (audit 2026-07-16 BLOCKER D: when
    no-push lived only in the ambient environment, `reject --no-push`
    spawned a miner that never had the var set and published the whole
    branch — an ambient policy that simply was not there).

    SEMANTICS, deliberately narrow: ``--no-push`` means *this invocation
    and anything it spawns* does not push. It is "not now", NOT "never" — a
    later independent worker, miner, or timer run may still publish the
    commit; ``--no-push`` keeps a record local for the moment, and nothing
    in the ledger promises permanence. To keep something out of the remote
    for good, it must not be committed to a pushed branch at all."""
    return os.environ.get(NO_PUSH_ENV) == "1"


def _spawn_window(home: Path, *, no_push: bool = False) -> int:
    """setsid-spawn a coalescing run; returns the child pid. Split out so
    tests can monkeypatch spawning without faking flocks.

    ``no_push`` rides the child's ENV (BLOCKER 3): the spawn is detached
    (``start_new_session=True``), so the parent's flag reaches it only as
    inherited environment — and without it, ``teach --no-push`` published
    the very record the user said keep local, via the worker teach itself
    kicked (worker run-end ``git push`` publishes the WHOLE branch)."""
    log_path = _p("worker.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if no_push:
        env[NO_PUSH_ENV] = "1"
    with open(log_path, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "self_learn.cli", "worker", "run", "--coalesce"],
            cwd=str(home),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    return proc.pid


def _open_window(home: Path, *, no_push: bool = False) -> str:
    """Lock-guarded window opener, shared by :func:`kick` and the
    run-end follow-on (audit 2026-07-15: the follow-on previously
    bypassed the spawn lock and could double-spawn against a mid-run
    kick). Returns ``spawned`` | ``absorbed-window`` | ``absorbed-race``.

    ``no_push`` propagates to a spawned child (BLOCKER 3). An ABSORBED kick
    inherits the already-running window's policy — correct: absorption
    means an existing run already covers this work, and a run that was
    allowed to push is not retroactively muzzled."""
    with open(_p("worker.spawn.lock"), "w", encoding="utf-8") as lock_fh:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "absorbed-race"  # the racing opener's spawn covers us
        try:
            window = _p("worker.window")
            if window.is_file():
                try:
                    pid = int(window.read_text(encoding="utf-8").strip())
                except ValueError:
                    pid = -1
                if pid > 0 and _pid_alive(pid):
                    return "absorbed-window"
            pid = _spawn_window(home, no_push=no_push)
            window.write_text(str(pid), encoding="utf-8")
            log(f"window opened (pid {pid})")
            return "spawned"
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def kick(home: Path | str, *, no_push: bool = False) -> str:
    """The pinned kick. Returns the outcome (for logs/tests):
    ``spawned`` | ``absorbed-window`` | ``absorbed-race`` | ``disabled``.

    ``no_push`` binds the spawned worker to the caller's ``--no-push``
    (BLOCKER 3) — see :func:`no_push_requested` for the exact semantics."""
    if os.environ.get("SELF_LEARN_WORKER_AUTOKICK") == "0":
        return "disabled"
    home = Path(home)
    cache_dir().mkdir(parents=True, exist_ok=True)
    _p("worker.dirty").touch()
    return _open_window(home, no_push=no_push)


# -------------------------------------------------------------------- run


@dataclass
class RunResult:
    status: str  # "ok" | "idle" | "failed"
    proposed: list[str] = field(default_factory=list)
    merge_proposed: list[str] = field(default_factory=list)
    invalid_deleted: list[str] = field(default_factory=list)
    orphans_swept: list[str] = field(default_factory=list)
    buckets: list[str] = field(default_factory=list)  # received proposals
    valid_landed: int = 0  # step-6 success basis, BEFORE step-5 filtering
    eligible: int = 0
    leftovers: int = 0  # eligible beyond the batch cap (follow-on covers)
    suspects: int = 0
    escalated: bool = False
    followon: bool = False
    #: Every ledger path this run wrote or deleted — the surgical staging
    #: set for the run-end commit (H-5: producers commit their own writes).
    touched: list[Path] = field(default_factory=list)
    commit_sha: str | None = None
    #: True iff this run's commit landed — the push's gate. Distinct from
    #: ``commit_sha is not None`` only in intent: it answers "is there
    #: anything to publish?", which is the question the caller asks OUTSIDE
    #: the lock (round 7: the commit moved inside `_harvest`'s lock, the
    #: push must not follow it in).
    committed: bool = False


def _enumerate(home: Path) -> tuple[list, int, int, list[dict]]:
    """(batch, leftovers, total pending, per-bucket counts). Same queue
    computation as `list` — deferred hidden; oldest first with the SAME
    sort key as `list` (audit 2026-07-15: str-sort diverged on mixed
    timestamp representations); batch cap 15 — leftovers keep
    ``worker.dirty`` set for a follow-on window (pinned)."""
    from .ledger_ops import _sort_key  # THE shared ordering

    needing = []
    total_pending = 0
    per_bucket: list[dict] = []
    for bucket in discover_buckets(home):
        entries = queue(bucket)
        if entries:
            per_bucket.append({"bucket": bucket.name, "pending": len(entries)})
        total_pending += len(entries)
        for entry in entries:
            if is_unanalyzed(entry):
                needing.append(entry)
    needing.sort(key=_sort_key)
    batch = needing[: batch_cap()]
    return batch, len(needing) - len(batch), total_pending, per_bucket


def _digest(home: Path, limit: int = 20) -> str:
    """Rejected-proposal digest — CLI-built negative exemplars (pinned):
    last `limit` rejected records ordered by resolving-commit AUTHOR
    DATE, newest first (audit 2026-07-15: topo order diverges from
    author-date order under rebase-based autosync, so the rows are
    sorted explicitly; the grep is line-anchored so a Revert subject
    quoting the message does not re-list an undone rejection)."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(home),
            "log",
            "--grep",
            "^self-learn: reject ",
            "--format=%ad%x09%s",
            "--date=iso-strict",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return "(no rejected-proposal history available)"
    rows = sorted(
        (row.split("\t", 1) for row in proc.stdout.splitlines() if "\t" in row),
        key=lambda pair: pair[0],
        reverse=True,  # author date, newest first (pinned)
    )
    lines: list[str] = []
    seen: set[str] = set()
    for _ad, subject in rows:
        parts = subject.split()
        rid = next((p for p in parts if p.startswith("lrn-")), None)
        if rid is None or rid in seen:
            continue
        seen.add(rid)
        title, note = None, None
        for bucket in discover_buckets(home):
            path = bucket.path / "resolved" / f"{rid}.md"
            if path.is_file():
                try:
                    record = Record.from_path(path)
                    title = record_title(record)
                    note = record.resolution_note
                except RecordError:
                    pass
                break
        if title is None:
            continue  # not a resolvable reject here — never inject noise
        entry = f"- {rid}: {title}"
        if note:
            entry += f" — rejected because: {note}"
        entry += f" [{subject}]"
        lines.append(entry)
        if len(lines) >= limit:
            break
    if not lines:
        return "(no rejected proposals yet)"
    return "\n".join(lines)


def _canon_excerpt(home: Path, entry) -> str:
    """The candidate target's managed section ± 20 lines, or the whole
    file when < 200 lines (pinned prompt ingredient). Targets resolve
    through the hosts registry now (doc 13): skill scope → the skills
    root's SKILL.md; project scope → the bucket's meta-recorded host
    CLAUDE.md; user scope → the real user CLAUDE.md."""
    scope = entry.record.scope
    target: Path | None = None
    if scope.startswith("skill:"):
        try:
            target = skill_dir_for(
                load_hosts(home), scope.partition(":")[2]
            ) / "SKILL.md"
        except HostsError:
            return "(skill target unresolvable — no registered skills root)"
    elif scope == "project":
        host = bucket_project_path(entry.bucket_dir)
        if host is None:
            return "(project target unresolvable — bucket has no meta.yaml)"
        target = Path(host) / "CLAUDE.md"
    else:  # user
        target = Path("~/.claude/CLAUDE.md").expanduser()
    if not target.is_file():
        return f"(target {target.name} does not exist yet)"
    lines = target.read_text(encoding="utf-8").splitlines()
    if len(lines) < 200:
        return "\n".join(lines)
    begin = next(
        (i for i, ln in enumerate(lines) if "SELF-LEARN:BEGIN" in ln), None
    )
    end = next((i for i, ln in enumerate(lines) if "SELF-LEARN:END" in ln), None)
    if begin is None or end is None:
        return "\n".join(lines[:60]) + "\n… (truncated)"
    lo, hi = max(0, begin - 20), min(len(lines), end + 21)
    return "\n".join(lines[lo:hi])


_PROMPT_TEMPLATE = """You are the self-learn routing analyst worker. For EACH pending record
below, write one proposal file at
<bucket>/proposals/lrn-<id>.yaml (the bucket path is given
per record). Follow the routing doctrine exactly — including §5 (the
proposal schema; NEVER emit record_sha) and §8 (write every card section
the registry requires; the registry follows the doctrine below). You may
also propose an optional `contradicts:` list (record ids or canon
anchors) when a lesson conflicts with existing canon.

After the per-record pass: if two or more of THESE pending records in the
SAME bucket are the same lesson, additionally write ONE merge proposal at
<bucket>/proposals/merge-<8 lowercase hex>.yaml with keys:
cluster_id, records (the lrn ids), suggested_survivor, rationale, model,
analyzed_at. Do not emit record_shas — the CLI stamps them.
cluster_id MUST equal the merge-<8 hex> token of the filename itself
(file merge-a1b2c3d4.yaml → cluster_id: merge-a1b2c3d4) — never a
descriptive slug; the validator fail-closed deletes anything else.

Never re-propose the classes below (recently rejected):
{digest}

=== ROUTING DOCTRINE ===
{doctrine}

=== CARD SECTION REGISTRY ===
{registry}

=== PENDING RECORDS ===
{records}
"""


def _compose_prompt(home: Path, batch: list) -> str:
    # PACKAGE-relative (doc 13 T-H3): doctrine + registry ship with the
    # product beside the skill — never resolved through any home.
    doctrine_path = package_skill_refs() / "routing-doctrine.md"
    registry_path = package_skill_refs() / "card-sections.yaml"
    doctrine = (
        doctrine_path.read_text(encoding="utf-8")
        if doctrine_path.is_file()
        else "(doctrine missing — propose conservatively)"
    )
    registry = (
        registry_path.read_text(encoding="utf-8")
        if registry_path.is_file()
        else "(registry missing — headline/impact/discuss)"
    )
    blocks = []
    for entry in batch:
        blocks.append(
            f"--- record {entry.record.id} ---\n"
            f"bucket: {entry.bucket_dir}\n"
            f"record file: {entry.path}\n"
            f"{entry.path.read_text(encoding='utf-8')}\n"
            f"--- candidate target canon excerpt ---\n"
            f"{_canon_excerpt(home, entry)}\n"
        )
    return _PROMPT_TEMPLATE.format(
        digest=_digest(home),
        doctrine=doctrine,
        registry=registry,
        records="\n".join(blocks),
    )


def _proposal_snapshot(home: Path) -> dict[Path, str]:
    """Recursive over proposals/ (audit 2026-07-15: the Write glob is
    recursive, so a model writing proposals/sub/x.yml must be SEEN — an
    unseen file would be silently autosync-published)."""
    snap: dict[Path, str] = {}
    for bucket in discover_buckets(home):
        pdir = bucket.path / "proposals"
        if not pdir.is_dir():
            continue
        for path in pdir.rglob("*"):
            if not path.is_file():
                continue
            try:
                snap[path] = sha_anchor(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                snap[path] = "unreadable"
    return snap


def _written_since(home: Path, snap: dict[Path, str]) -> list[Path]:
    out = []
    for path, digest in _proposal_snapshot(home).items():
        if snap.get(path) != digest:
            out.append(path)
    return sorted(out)


def _git_rm_or_unlink(home: Path, path: Path, result: "RunResult | None" = None) -> None:
    """Unlink now; the deletion is STAGED AND COMMITTED at run end by
    :func:`_commit_run`, never here.

    The 2026-07-15 letter-adjustment to the §7.1 orphan-sweep row was
    right that a background process must not park a deletion in the index
    for a racing verb's whole-index commit to swallow — but its second
    half ("autosync's `add -A` commits the deletion on its next cycle")
    died with the watcher (doc 13 H-5; audit 2026-07-16 MAJOR 3), leaving
    the worker's deletions committed by nobody. Both concerns hold at
    once: delete during the run, then stage surgically and commit ONCE at
    run end — the index carries this run's paths only for the moment it
    takes to commit them."""
    path.unlink(missing_ok=True)
    if result is not None:
        result.touched.append(path)


def _tracked(home: Path, path: Path) -> bool:
    from . import gitops

    return (
        gitops._git(  # noqa: SLF001 — same module family
            home, "ls-files", "--error-unmatch", "--", str(path)
        ).returncode
        == 0
    )


def _commit_run(home: Path, result: RunResult, *, no_push: bool = False) -> None:
    """H-5 (doc 13 §5): the worker commits its OWN writes at run end —
    validated proposals, and its deletions (invalid model output, orphan
    and invalidated-merge sweeps) — with the pinned subject
    ``self-learn: worker <n> proposal(s)``, then a best-effort push behind
    the has_remote guard.

    Audit 2026-07-16 MAJOR 3: nobody committed the worker's proposals once
    H-5 removed the watcher, so machine B re-analyzed every record from
    scratch and a re-clone destroyed the analysis. Staging stays SURGICAL
    (this run's paths only — never ``add -A``): a deleted path is staged
    only when git tracks it, an existing path only when it is one this run
    wrote. Git trouble is logged, never fatal — proposals are regenerable.

    BLOCKER 4 (2026-07-16): this is one of the two BACKGROUND committers M3
    added to the ledger — Popen-detached, kicked by every teach/import, so
    it fires while foreground verbs are mid-``git mv``. The stage→commit
    runs inside the repo's commit lock, and the commit carries its own
    pathspec.

    Round 7: the lock is taken by :func:`_commit_locked`, and ``run`` takes
    it EARLIER still (in :func:`_harvest`, before ``_validate_written``
    deletes anything) — re-entrantly, so this entry point keeps working
    standalone. The push stays outside every lock.

    BLOCKER 3: the push honors :func:`no_push_requested` — the invoking
    verb's ``--no-push`` binds the worker IT spawned, or ``teach --no-push``
    keeps a record local only until the worker it kicked publishes the whole
    branch a second later."""
    if not _commit_locked(home, result):
        return
    _push_run(home, no_push=no_push)


def _commit_locked(home: Path, result: RunResult) -> bool:
    """Stage → commit this run's paths. Takes the lock (re-entrant: `run`
    already holds it). True iff a commit landed.

    Staging stays SURGICAL (this run's paths only — never ``add -A``): a
    deleted path is staged only when git tracks it, an existing path only
    when it is one this run wrote. Audit 2026-07-16 MAJOR 3: nobody
    committed the worker's proposals once H-5 removed the watcher, so
    machine B re-analyzed every record from scratch and a re-clone
    destroyed the analysis. Git trouble is logged, never fatal — proposals
    are regenerable."""
    from . import gitops

    if not result.touched:
        return False
    stage: list[str] = []
    for path in dict.fromkeys(result.touched):  # de-dup, order-stable
        if path.exists() or _tracked(home, path):
            stage.append(str(path))
    if not stage:
        return False
    # BLOCKER B: EVERY GitOpsError is caught, including the one raised by
    # ACQUIRING the lock (a timeout) and by a git call that blew its own
    # timeout. This is a detached, Popen'd process: an escaping exception
    # is a stack dump into worker.log and a dead run, for a condition —
    # "another producer is committing right now" — that is not even an
    # error. Proposals are regenerable; the next run redoes this.
    try:
        with gitops.commit_lock(home):
            proc = gitops._git(home, "add", "--", *stage)  # noqa: SLF001
            if proc.returncode != 0:
                log(f"run: staging failed ({(proc.stderr or proc.stdout).strip()})")
                return False
            # Scoped to THIS run's paths: an index-wide --quiet would answer
            # about someone else's staged work (pathspec discipline).
            if (
                gitops._git(  # noqa: SLF001
                    home, "diff", "--cached", "--quiet", "--", *stage
                ).returncode
                == 0
            ):
                return False  # nothing changed (byte-identical re-stamp)
            n = result.valid_landed
            result.commit_sha = gitops.commit(
                home,
                f"self-learn: worker {n} proposal{'s' if n != 1 else ''}",
                paths=stage,
            )
    except gitops.GitOpsError as exc:
        log(f"run: commit failed ({exc}) — proposals left uncommitted")
        return False
    return True


def _push_run(home: Path, *, no_push: bool) -> None:
    """The push — OUTSIDE every lock (it touches no index — see the gitops
    module docstring for the re-scope) and outside the commit's try: a push
    failure must never look like a commit failure."""
    from . import gitops

    if no_push:
        log("run: push skipped — --no-push in effect")
        return
    try:
        push = gitops.push_if_remote(home)
    except gitops.GitOpsError as exc:
        # BLOCKER B: this is a DETACHED process. A traceback here goes to
        # worker.log and kills the run; the proposals are committed and a
        # later run republishes them.
        log(f"run: push errored ({exc}) — commit kept locally")
        return
    if not push.ok:
        log(f"run: push failed ({push.detail}) — commit kept locally")


def _cache_clear(name: str) -> None:
    """Delete one of the worker's CACHE flag files.

    A one-line helper for a one-line operation, and it earns that: the
    lock-invariant check (tests/test_lock_invariant.py) reads a bare
    ``.unlink()`` in ``run`` as a repo mutation and cannot tell
    ``$XDG_CACHE_HOME/.../worker.window`` from a ledger record — and it is
    right not to guess. Naming the cache writes makes ``run``'s remaining
    filesystem mutations exactly the ones that touch the LEDGER, which is
    what the invariant is about. The code now says which files it means."""
    _p(name).unlink(missing_ok=True)


def _harvest(home: Path, written: list[Path]) -> RunResult:
    """Validate + sweep + commit, as ONE locked section (audit 2026-07-16
    round 7 — the invariant: no ledger mutation may precede its lock).

    A lock failure is LOGGED, never raised: this runs in a Popen-detached
    process where an escaping exception is a stack dump into worker.log and
    a dead run (BLOCKER B), for a condition — "another producer is
    committing right now" — that is not an error. Because the lock is taken
    BEFORE the first mutation, refusing here costs nothing: the model's
    output stays on disk untouched and the next run validates it."""
    from . import gitops

    try:
        with gitops.commit_lock(home):
            result = _validate_written(home, written)
            _still_pending(home, result)
            result.committed = _commit_locked(home, result)
            return result
    except gitops.GitOpsError as exc:
        log(f"run: could not take the ledger lock ({exc}) — nothing swept")
        return RunResult(status="failed")


def _bucket_name(home: Path, path: Path) -> str | None:
    for bucket in discover_buckets(home):
        try:
            path.relative_to(bucket.path)
        except ValueError:
            continue
        return bucket.name
    return None


def _validate_written(home: Path, written: list[Path]) -> RunResult:
    """Run-sequence step 4: schema-invalid worker output is DELETED and
    logged (unattended policy — the attended `proposal validate` verb
    reports-never-deletes); valid proposals get record_sha stamped by the
    CLI, overwriting anything the model wrote. Audit 2026-07-15 riders:
    (1) merge proposals are STAMPED BEFORE validation — the model is
    correctly told never to emit record_shas, so validate-first deleted
    every spec-compliant merge; (2) every surviving file is secret-
    scanned (model-authored rationale is otherwise the one tracked write
    autosync would publish unscanned) — a hit deletes, same unattended
    policy; (3) anything under proposals/ that is not a top-level
    lrn-*.yaml / merge-*.yaml is model litter: deleted + logged, never
    silently published."""
    result = RunResult(status="failed")
    for path in written:
        name = path.stem
        expected_shape = (
            path.parent.name == "proposals"
            and path.suffix == ".yaml"
            and (name.startswith("lrn-") or name.startswith("merge-"))
        )
        try:
            if not expected_shape:
                raise ProposalError(
                    "unexpected artifact outside the proposal naming contract"
                )
            hits = secret_scan(path.read_text(encoding="utf-8"))
            if hits:
                raise ProposalError(
                    f"secret scan hit ({hits[0].rule}) — never published"
                )
            data = read_proposal(path)
            if name.startswith("merge-"):
                # STAMP FIRST (M2-21: models cannot compute hashes), then
                # validate the completed document.
                shas = {}
                for rid in data.get("records") or []:
                    rpath = path.parent.parent / "pending" / f"{rid}.md"
                    if not rpath.is_file():
                        raise ProposalError(f"merge member {rid} not pending")
                    shas[rid] = sha_anchor(Record.from_path(rpath).body)
                data["record_shas"] = shas
                validate_merge_proposal(data)
                _dump_yaml(data, path)  # same writer as stamping
                result.merge_proposed.append(data["cluster_id"])
                result.touched.append(path)
            else:
                validate_proposal(data)
                rpath = path.parent.parent / "pending" / f"{name}.md"
                if not rpath.is_file():
                    raise ProposalError(f"no pending record for {name}")
                stamp_proposal(home, name)
                result.proposed.append(name)
                result.touched.append(path)
            bucket = _bucket_name(home, path)
            if bucket and bucket not in result.buckets:
                result.buckets.append(bucket)
        except Exception as exc:  # noqa: BLE001 — unattended: delete + log
            log(f"run: invalid worker output {path.name} deleted ({exc})")
            result.invalid_deleted.append(path.name)
            _git_rm_or_unlink(home, path, result)
    result.valid_landed = len(result.proposed) + len(result.merge_proposed)
    return result


def _still_pending(home: Path, result: RunResult) -> None:
    """Run-sequence step 5: drop resolved-mid-run ids from the event and
    sweep orphan proposals (no matching pending record → git rm)."""
    result.proposed = [
        rid
        for rid in result.proposed
        if any(
            (b.path / "pending" / f"{rid}.md").is_file()
            for b in discover_buckets(home)
        )
    ]
    for bucket in discover_buckets(home):
        pdir = bucket.path / "proposals"
        if not pdir.is_dir():
            continue
        for path in sorted(pdir.glob("lrn-*.yaml")):
            if not (bucket.path / "pending" / f"{path.stem}.md").is_file():
                log(f"run: orphan proposal {path.name} swept")
                result.orphans_swept.append(path.name)
                _git_rm_or_unlink(home, path, result)
        for path in sorted(pdir.glob("merge-*.yaml")):
            try:
                members = read_proposal(path).get("records", [])
            except Exception:  # noqa: BLE001
                members = []
            if not members or not all(
                (bucket.path / "pending" / f"{rid}.md").is_file()
                for rid in members
            ):
                log(f"run: invalidated merge proposal {path.name} swept")
                result.orphans_swept.append(path.name)
                _git_rm_or_unlink(home, path, result)


# ------------------------------------------- recurrence suspects (11 §2.2)


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(
        c.lower() if c.isalnum() else " " for c in text
    ).split() if len(t) > 2}


def _recurrence_suspects(home: Path, batch: list) -> int:
    """Deterministic detection: a NEW pending capture that matches an
    already-ROUTED lesson (token overlap on the title line, or a shared
    evidence origin). Suspects are telemetry events — the machine never
    writes the record; `confirm-recurrence` is the human's."""
    already = {
        (e.get("record"), e.get("origin"))
        for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    }
    count = 0
    for entry in batch:
        pending = entry.record
        p_tokens = _tokens(record_title(pending))
        p_origins = {
            ev.get("origin") for ev in pending.evidence if ev.get("origin")
        }
        resolved_dir = entry.bucket_dir / "resolved"
        if not resolved_dir.is_dir():
            continue
        for path in sorted(resolved_dir.glob("lrn-*.md")):
            try:
                routed = Record.from_path(path)
            except RecordError:
                continue
            if routed.status != "routed":
                continue
            basis = None
            r_origins = {
                ev.get("origin") for ev in routed.evidence if ev.get("origin")
            }
            if p_origins & r_origins:
                basis = "origin-match"
            else:
                r_tokens = _tokens(record_title(routed))
                union = p_tokens | r_tokens
                if union and len(p_tokens & r_tokens) / len(union) >= SUSPECT_JACCARD:
                    basis = "title-token-overlap"
            if basis is None or (routed.id, pending.id) in already:
                continue
            telemetry.spool_quiet(
                "recurrence-suspect",
                record=routed.id,
                origin=pending.id,
                basis=basis,
            )
            count += 1
    return count


# ------------------------------------------------- events + notifications


def append_event(event: str, record_ids: list[str], aggregate: dict) -> None:
    path = _p("events.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "ts": _now_iso(),
            "event": event,
            "record_ids": record_ids,
            "aggregate": aggregate,
        },
        separators=(",", ":"),
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    _truncate_oldest(path, EVENTS_CAP_BYTES)


def render_notification(n: int, buckets: list[str], total: int, scopes: int) -> str:
    """THE pinned template (08 §7.1 Notification-rendering row)."""
    s1 = "s" if n != 1 else ""
    s2 = "s" if scopes != 1 else ""
    return (
        f"self-learn: {n} new proposal{s1} for {', '.join(buckets)}. "
        f"{total} pending across {scopes} scope{s2} — /self-learn:review"
    )


def _notify(message: str) -> None:
    """notify-send when available, stderr otherwise — failure never fails
    a run (headless/SSH has no DBus). No -A/action flags anywhere, so no
    wait to bound (user CLAUDE.md swaync rule applies to -A only)."""
    try:
        if shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", "self-learn", message],
                capture_output=True,
                timeout=10,
            )
            return
    except Exception:  # noqa: BLE001
        pass
    print(message, file=sys.stderr)


def _oldest_pending_days(home: Path) -> int:
    oldest = 0
    now = datetime.now(timezone.utc)
    for bucket in discover_buckets(home):
        for entry in queue(bucket):
            created = str(entry.record.created_at)[:10]
            try:
                then = datetime.fromisoformat(created).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            oldest = max(oldest, (now - then).days)
    return oldest


def _maybe_escalate(home: Path, total_pending: int, per_bucket: list[dict]) -> bool:
    """Worker-run-end-only escalation, debounced 24 h (pinned)."""
    oldest = _oldest_pending_days(home)
    if total_pending < ESCALATE_PENDING and oldest <= ESCALATE_OLDEST_DAYS:
        return False
    marker = _p("worker.last-escalated")
    try:
        if time.time() - marker.stat().st_mtime < ESCALATE_DEBOUNCE_SECS:
            return False
    except FileNotFoundError:
        pass
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    append_event(
        "escalation", [], {"pending": total_pending, "buckets": per_bucket}
    )
    _notify(
        f"self-learn: backlog needs attention — {total_pending} pending, "
        f"oldest {oldest}d — /self-learn:review"
    )
    log(f"escalation: pending={total_pending} oldest={oldest}d")
    return True


# ------------------------------------------------ fast status (T15 pin)

#: Staleness predicate constant (08 §7.1): last-run older than this (or
#: missing = infinitely old) with un-analyzed supply present ⇒ alarm.
STALE_AFTER_SECS = 3 * 24 * 60 * 60


def last_run_iso() -> str | None:
    """`status --json` amendment (08 §7.1): iso8601 | null (never ran on
    this machine)."""
    try:
        mtime = _p("worker.last-run").stat().st_mtime
    except FileNotFoundError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def fast_status(home: Path | str) -> dict:
    """`status --json --fast` (08 §7.1 SessionStart pin): a pending/-only
    frontmatter scan — no git, no network, no resolved/ walk (follow-up
    counts deliberately excluded), <500 ms warm on 100 records. Queue
    semantics are THE same rules as `list` (deferred hidden), computed
    here once so the bash hook never reimplements them."""
    from ruamel.yaml import YAML  # local: keep module import cost flat

    yaml = YAML(typ="safe")
    home = Path(home)
    now = datetime.now(timezone.utc)
    buckets_out: list[dict] = []
    total = 0
    unanalyzed_total = 0
    oldest_all = 0

    for bucket in discover_buckets(home):
        pending = 0
        unanalyzed = 0
        oldest = None
        for path in bucket.pending_files():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            lines = text.split("\n")
            if not lines or lines[0] != "---":
                continue
            try:
                close = lines[1:].index("---") + 1
                fm = yaml.load("\n".join(lines[1:close]))
            except Exception:  # noqa: BLE001 — unparseable: not queued
                continue
            if not isinstance(fm, dict):
                continue
            until = fm.get("deferred_until")
            if until is not None:
                try:
                    until_d = datetime.fromisoformat(str(until)[:10]).replace(
                        tzinfo=timezone.utc
                    )
                    if until_d > now:
                        continue  # hidden — same rule as the queue
                except ValueError:
                    pass
            pending += 1
            created = str(fm.get("created_at", ""))[:10]
            try:
                age = (
                    now
                    - datetime.fromisoformat(created).replace(tzinfo=timezone.utc)
                ).days
                oldest = age if oldest is None else max(oldest, age)
            except ValueError:
                age = None
            body = "\n".join(lines[close + 1 :])
            ppath = bucket.path / "proposals" / f"{fm.get('id')}.yaml"
            fresh = False
            if ppath.is_file():
                try:
                    pdata = yaml.load(ppath.read_text(encoding="utf-8"))
                    # SAME predicate as is_unanalyzed: hash match AND
                    # schema validity (audit 2026-07-15: a sha-intact but
                    # schema-broken proposal must not suppress the alarm).
                    if (
                        isinstance(pdata, dict)
                        and pdata.get("record_sha") == sha_anchor(body)
                    ):
                        validate_proposal(dict(pdata))
                        fresh = True
                except Exception:  # noqa: BLE001
                    fresh = False
            if not fresh:
                unanalyzed += 1
        if pending:
            buckets_out.append(
                {
                    "bucket": bucket.name,
                    "scope": bucket.scope,
                    "pending": pending,
                    "unanalyzed": unanalyzed,
                    "oldest_days": oldest,
                }
            )
        total += pending
        unanalyzed_total += unanalyzed
        if oldest is not None:
            oldest_all = max(oldest_all, oldest)

    last_run = last_run_iso()
    stale = False
    if unanalyzed_total >= 1:
        try:
            age_secs = time.time() - _p("worker.last-run").stat().st_mtime
        except FileNotFoundError:
            age_secs = float("inf")  # missing = infinitely old (pinned)
        stale = age_secs > STALE_AFTER_SECS
    return {
        "buckets": buckets_out,
        "total_pending": total,
        "unanalyzed_total": unanalyzed_total,
        "oldest_days": oldest_all,
        "worker_last_run": last_run,
        "staleness_alarm": stale,
        "escalate": total >= ESCALATE_PENDING
        or oldest_all > ESCALATE_OLDEST_DAYS,
    }


# --------------------------------------------------------------- the run


def run(
    home: Path | str, *, coalesce: bool = False, no_push: bool | None = None
) -> RunResult:
    """``no_push=None`` reads the process boundary once
    (:func:`no_push_requested`) and then threads the answer as a parameter
    — BLOCKER D: the policy is data, not ambience."""
    home = Path(home)
    if no_push is None:
        no_push = no_push_requested()
    cache_dir().mkdir(parents=True, exist_ok=True)
    if coalesce:
        time.sleep(coalesce_secs())

    with open(_p("worker.lock"), "w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)  # blocking (pinned)
        # Self-hold the sentinel for the rest of the run. There is no
        # sync-first step any more (audit 2026-07-16 MINOR 10): it looked
        # for `<home>/bin/claude-skills-sync`, which the LEDGER home will
        # never contain — doc 13 H-5 gives the ledger no watcher at all,
        # so every run logged "skipped" forever. The sentinel hold remains
        # (it pauses the HOST repos' autosync during the canon-adjacent
        # window) with the same discipline as the verbs:
        # skip-if-held-by-other, release iff owned; a crashed run goes
        # stale at the 2 h TTL.
        _cache_clear("worker.window")
        hold = sentinel.hold()
        sentinel.heartbeat()
        try:
            batch, leftovers, total_pending, per_bucket = _enumerate(home)
            if leftovers == 0:
                _cache_clear("worker.dirty")  # AFTER enumeration
            else:
                # pinned: leftovers keep worker.dirty set → follow-on window
                _p("worker.dirty").touch()
                log(f"run: {leftovers} eligible beyond the batch cap — "
                    "dirty kept for a follow-on window")

            suspects = _recurrence_suspects(home, batch)

            if not batch:
                _p("worker.last-run").touch()
                log(f"run: idle (0 eligible, {total_pending} pending)")
                result = RunResult(status="idle", eligible=0, suspects=suspects)
            else:
                prompt = _compose_prompt(home, batch)
                snap = _proposal_snapshot(home)
                argv = build_argv(home, write_settings_file(home))
                try:
                    proc = subprocess.run(
                        argv,
                        cwd=str(home),
                        input=prompt,  # stdin — argv caps at 128 KiB (audit)
                        capture_output=True,
                        text=True,
                        timeout=INVOKE_TIMEOUT_SECS,
                    )
                    if proc.returncode != 0:
                        log(
                            f"run: claude exited {proc.returncode}: "
                            f"{(proc.stderr or proc.stdout)[:400]}"
                        )
                except FileNotFoundError:
                    log("run: claude CLI not found on PATH")
                except subprocess.TimeoutExpired:
                    log(f"run: claude timed out after {INVOKE_TIMEOUT_SECS}s")
                except OSError as exc:
                    log(f"run: claude invocation failed ({exc})")
                # The invocation may have taken 15 min — and a CONCURRENT
                # short holder (e.g. the miner's landing phase) may have
                # created-then-RELEASED the sentinel we joined, deleting
                # autosync cover mid-run (audit 2026-07-15: owner/joiner
                # race). heartbeat() returns False on a missing file and
                # never resurrects: re-assert the hold before validation.
                if not sentinel.heartbeat():
                    hold = sentinel.hold()
                    sentinel.heartbeat()

                written = _written_since(home, snap)
                # [first mutation → commit] under ONE lock (audit
                # 2026-07-16 round 7, THE invariant). `_validate_written`
                # DELETES schema-invalid model output and sweeps orphaned
                # and invalidated-merge proposals — deletions of TRACKED
                # files, i.e. exactly the worktree mutation a racing `pull
                # --rebase --autostash` stashes and restores into a
                # conflict. They used to run here, unlocked, and be
                # committed by `_commit_run`'s separate lock later; the
                # window between the two was the hazard. The model
                # invocation above stays OUTSIDE the lock — it takes
                # minutes and writes only its own new (untracked) files.
                #
                # The lock is taken here rather than inside `_commit_run`
                # so the section is CONTINUOUS; `_commit_run` takes it
                # again re-entrantly, which is why it can still be called
                # on its own (the miner's and the tests' path).
                result = _harvest(home, written)
                result.eligible = len(batch)
                result.leftovers = leftovers
                result.suspects = suspects

                # Step 6 (audit fix): success is decided on what LANDED
                # valid, not on what survived step-5's mid-run-resolution
                # filter — a run whose every proposal got resolved by a
                # racing human still did its job.
                if result.valid_landed:
                    result.status = "ok"
                    _p("worker.last-run").touch()
                    # Merge proposals COUNT as proposals for the event +
                    # notification (a merge card is a reviewable
                    # proposal); cluster ids ride record_ids so the
                    # deep-link contract has a target.
                    ids = result.proposed + result.merge_proposed
                    n = len(result.proposed) + len(result.merge_proposed)
                    aggregate = {"pending": total_pending, "buckets": per_bucket}
                    if ids:
                        append_event("proposals", ids, aggregate)
                        _notify(
                            render_notification(
                                n,
                                sorted(result.buckets) or ["(unknown)"],
                                total_pending,
                                len(per_bucket),
                            )
                        )
                    log(
                        f"run: ok — {len(result.proposed)} proposal(s), "
                        f"{len(result.merge_proposed)} merge, "
                        f"{len(result.invalid_deleted)} invalid deleted"
                    )
                else:
                    result.status = "failed"
                    log(
                        f"run: FAILED — {len(batch)} eligible, 0 valid "
                        "proposals (last-run not touched; staleness alarm "
                        "is the detector)"
                    )

            # H-5: the producer commits its own writes (proposals +
            # sweeps) — done inside `_harvest`'s lock above, because the
            # sweeps are mutations and the lock must precede them (round
            # 7). The PUSH is what is left to do, and it belongs out here:
            # outside the lock, because it touches no index.
            if result.committed:
                _push_run(home, no_push=no_push)

            result.escalated = _maybe_escalate(home, total_pending, per_bucket)

            # Worker runs are kick-chained from teach/import — still the
            # human-triggered class (11 §4.2): flush the spool.
            # push=not no_push_requested() (BLOCKER 3): flush defaults to
            # push=True, so a --no-push teach's own kicked worker published
            # the whole branch here — including the record the user asked to
            # keep local. The flush still COMMITS (H-5); only the push waits.
            try:
                telemetry.flush(home, push=not no_push)
            except telemetry.TelemetryError as exc:
                log(f"run: telemetry flush refused ({exc})")
        finally:
            hold.release()
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    # Follow-on OUTSIDE the run lock and through the spawn lock (audit
    # 2026-07-15: the old direct spawn bypassed kick's serialization and
    # could double-spawn against a mid-run kick).
    if _p("worker.dirty").is_file():
        # The follow-on inherits THIS run's no-push policy (BLOCKER 3):
        # otherwise the muzzled worker's own successor would push instead.
        outcome = _open_window(home, no_push=no_push)
        log(f"run: follow-on window: {outcome}")
        result.followon = outcome == "spawned"
    return result
