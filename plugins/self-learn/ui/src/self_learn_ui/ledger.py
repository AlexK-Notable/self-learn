"""ledger.py — the ONE I/O module for the self-learn UI (09 §3 / 10 §1
"Screen-state derivation" pin: no route handler reads ledger files
directly or shells the CLI directly — everything funnels through here).

Two read paths, both pinned in 09 §3:

- ``self-learn <cmd> --json`` subprocess invocations for list/status/
  report/mine-status — the CLI's own computed shapes, never re-derived.
- Raw file reads for Detail (record markdown, proposal YAML + diff
  sibling) and Bucket cluster groups (``proposals/merge-*.yaml``) —
  structured YAML / the record's own frontmatter+body parser, never
  text-parsing.

Every function here is a thin, individually-testable wrapper: CLI failures
come back as an explicit :class:`self_learn_ui.models.CliRead` with
``error`` set (never a silently-empty success), and raw-file reads that
find nothing return ``None`` / ``[]`` rather than raising — a Detail page
for a record with no proposal yet is an ordinary state, not an error.

Also owns the refresh watcher (09 §3 "Refresh" bullet): ``watchfiles``
over every bucket's ``pending/`` + ``proposals/`` dirs and
``events.jsonl``, 300 ms debounced, plus the forced-refresh hook the verb
runner (U4) calls after every verb completes.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml as pyyaml
import watchfiles

from self_learn import sentinel as sl_sentinel
from self_learn import worker as sl_worker
from self_learn.ledger import Bucket, discover_buckets as _discover_buckets
from self_learn.ledger_ops import (
    LedgerOpsError,
    ProposalError,
    bucket_project_path,
    find_record_path,
    read_proposal as _read_proposal_dict,
    validate_merge_proposal,
)
from self_learn.records import Record, RecordError

from .models import CliRead

__all__ = [
    "DEBOUNCE_MS",
    "POLL_FALLBACK_SECONDS",
    "RecordLocation",
    "RefreshEvent",
    "RefreshHub",
    "discover_buckets",
    "list_items",
    "locate_record",
    "mine_status",
    "project_path_for",
    "read_clusters",
    "read_diff",
    "read_proposal_raw",
    "read_proposal_text",
    "read_record",
    "read_registry",
    "report",
    "sentinel_mtime",
    "status",
    "watch_ledger",
    "watch_paths",
]

#: 09 §3 refresh mechanics: 300 ms debounce, 10 s client poll fallback.
DEBOUNCE_MS = 300
POLL_FALLBACK_SECONDS = 10

_CLI_TIMEOUT_SECS = 60


# ------------------------------------------------------------- CLI reads


def _self_learn_bin() -> str:
    """Resolve the ``self-learn`` console script. Both packages
    (self-learn-ui, self-learn-cli) install into the SAME uv-managed
    venv (self-learn-cli is a path dependency), so it is normally on
    PATH; the ``sys.executable``-relative fallback covers environments
    where PATH was stripped before this process started."""
    exe = shutil.which("self-learn")
    if exe:
        return exe
    candidate = Path(sys.executable).parent / "self-learn"
    if candidate.exists():
        return str(candidate)
    return "self-learn"  # let subprocess raise a clear FileNotFoundError


def _invoke_json(
    args: list[str], *, home: Path, env: dict[str, str] | None = None
) -> CliRead:
    """Run ``self-learn <args>``, ``SELF_LEARN_HOME`` pinned to *home*.
    Never raises: every failure mode (spawn error, timeout, non-zero
    exit, unparseable stdout) becomes ``CliRead(data=None, error=...)``
    (task pin: CLI invocation failures are explicit model states)."""
    full_env = dict(env if env is not None else os.environ)
    full_env["SELF_LEARN_HOME"] = str(home)
    label = "self-learn " + " ".join(args)
    try:
        proc = subprocess.run(
            [_self_learn_bin(), *args],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=_CLI_TIMEOUT_SECS,
        )
    except OSError as exc:
        return CliRead(data=None, error=f"{label} failed to start: {exc}")
    except subprocess.TimeoutExpired:
        return CliRead(data=None, error=f"{label} timed out after {_CLI_TIMEOUT_SECS}s")
    if proc.returncode != 0:
        message = proc.stderr.strip() or f"{label} exited {proc.returncode}"
        return CliRead(data=None, error=message)
    try:
        return CliRead(data=json.loads(proc.stdout), error=None)
    except json.JSONDecodeError as exc:
        return CliRead(data=None, error=f"{label} produced invalid JSON: {exc}")


def list_items(
    home: Path,
    *,
    include_deferred: bool = False,
    env: dict[str, str] | None = None,
) -> CliRead:
    args = ["list", "--json"]
    if include_deferred:
        args.append("--include-deferred")
    return _invoke_json(args, home=home, env=env)


def status(home: Path, *, env: dict[str, str] | None = None) -> CliRead:
    return _invoke_json(["status", "--json"], home=home, env=env)


def report(home: Path, *, env: dict[str, str] | None = None) -> CliRead:
    return _invoke_json(["report", "--json"], home=home, env=env)


def mine_status(home: Path, *, env: dict[str, str] | None = None) -> CliRead:
    return _invoke_json(["mine", "status", "--json"], home=home, env=env)


# ------------------------------------------------------------ raw reads


def discover_buckets(home: Path) -> list[Bucket]:
    """Re-exported, never reimplemented (P2-4)."""
    return _discover_buckets(home)


@dataclass(frozen=True)
class RecordLocation:
    """Where one record's file lives, resolved across every bucket."""

    path: Path
    bucket_dir: Path
    bucket_name: str
    scope: str
    resolved: bool


def locate_record(home: Path, record_id: str) -> RecordLocation | None:
    try:
        path = find_record_path(home, record_id)
    except LedgerOpsError:
        return None
    bucket_dir = path.parent.parent
    if bucket_dir == home / "user":
        scope = "user"
    elif bucket_dir.parent.name == "skills":
        scope = "skill"
    elif bucket_dir.parent.name == "projects":
        scope = "project"
    else:
        scope = "unknown"
    return RecordLocation(
        path=path,
        bucket_dir=bucket_dir,
        bucket_name=bucket_dir.name,
        scope=scope,
        resolved=(path.parent.name == "resolved"),
    )


def read_record(path: Path) -> Record | None:
    try:
        return Record.from_path(path)
    except RecordError:
        return None


def read_proposal_raw(bucket_dir: Path, record_id: str) -> tuple[dict | None, str | None]:
    """Parsed proposal dict (no schema validation — Detail renders
    whatever exists) + an error string when the sibling exists but is
    unparseable. ``(None, None)`` means no proposal sibling at all."""
    path = bucket_dir / "proposals" / f"{record_id}.yaml"
    if not path.is_file():
        return None, None
    try:
        return _read_proposal_dict(path), None
    except ProposalError as exc:
        return None, str(exc)


def read_proposal_text(bucket_dir: Path, record_id: str) -> str | None:
    """The proposal sibling's raw file text (Pygments YAML-lexer render
    fallback per 09 §2.3 when no ``.diff`` sibling exists)."""
    path = bucket_dir / "proposals" / f"{record_id}.yaml"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_diff(bucket_dir: Path, record_id: str) -> str | None:
    path = bucket_dir / "proposals" / f"{record_id}.diff"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_clusters(bucket_dir: Path) -> list[dict]:
    """Every schema-valid ``merge-*.yaml`` in this bucket's proposals/
    dir (structured YAML — files-as-truth, never text-parsing, 09 §3).
    An unparseable or schema-invalid cluster file is skipped, not raised
    — the same "corruption never blocks the rest" posture as
    ``unparseable_pending``."""
    pdir = bucket_dir / "proposals"
    if not pdir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(pdir.glob("merge-*.yaml")):
        try:
            data = pyyaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, pyyaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            validate_merge_proposal(data)
        except ProposalError:
            continue
        out.append(data)
    return out


def project_path_for(bucket_dir: Path) -> str | None:
    """A project bucket's recorded absolute path (``meta.yaml``), for
    the Y-11 copyable ``host add`` command. ``None`` for non-project
    buckets or a bucket with no/unreadable ``meta.yaml``."""
    p = bucket_project_path(bucket_dir)
    return str(p) if p is not None else None


def read_registry() -> list[dict]:
    """The card-sections.yaml registry, resolved relative to the
    PACKAGE's own installed location (Y-2's third read root) — never via
    ``SELF_LEARN_HOME``. Reuses the CLI's own resolution function
    (:func:`self_learn.worker.package_skill_refs`) rather than
    re-deriving the path: both packages are collocated under the same
    product-repo ``plugins/self-learn/`` tree, so the CLI's own
    ``__file__``-relative math lands on the identical directory
    regardless of which package calls it."""
    path = sl_worker.package_skill_refs() / "card-sections.yaml"
    try:
        raw = pyyaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return []
    if not isinstance(raw, dict):
        return []
    out = []
    for key, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        out.append(
            {
                "key": key,
                "label": spec.get("label", key),
                "order": spec.get("order", 10**9),
                "required": spec.get("required", "optional"),
            }
        )
    return sorted(out, key=lambda r: r["order"])


def sentinel_mtime() -> float | None:
    """Raw mtime of the autosync-pause sentinel (path owned by
    :mod:`self_learn.sentinel`, never re-pinned here). Liveness (TTL
    comparison) is a pure computation in ``models.py`` — this function
    does the one bit of I/O, nothing else."""
    try:
        return sl_sentinel.sentinel_path().stat().st_mtime
    except OSError:
        return None


# ---------------------------------------------------------------- watch


def watch_paths(home: Path) -> list[Path]:
    """09 §3: every bucket's ``pending/`` + ``proposals/`` dirs, plus
    ``events.jsonl`` (a wake-up signal only — never read for content
    here or anywhere in this module)."""
    paths: list[Path] = []
    for bucket in discover_buckets(home):
        paths.append(bucket.path / "pending")
        paths.append(bucket.path / "proposals")
    paths.append(home / "events.jsonl")
    return paths


def _scope_for_path(home: Path, path: Path) -> str:
    """Best-effort scope tag for a changed path — 'front' as the safe
    default (a client re-requesting Front on ambiguity is harmless;
    U3 owns the actual per-scope htmx-partial routing)."""
    try:
        parts = Path(path).relative_to(Path(home)).parts
    except ValueError:
        return "front"
    head = parts[0] if parts else None
    if head in ("skills", "projects") and len(parts) >= 2:
        return f"bucket:{parts[1]}"
    if head == "user":
        return "bucket:user"
    return "front"


@dataclass(frozen=True)
class RefreshEvent:
    scope: str


class RefreshHub:
    """Async pub/sub the SSE endpoint (U3) subscribes to. The verb
    runner (U4) publishes a forced refresh through :meth:`force_refresh`
    after every verb completes (09 §3: "Any verb completion forces a
    push").

    Also the ONE staleness clock for 09 §11 Y-19 item 1's next-record
    prefetch cache (:mod:`self_learn_ui.prefetch`): :attr:`generation`
    increments on every event this hub ever publishes — a watchfiles-
    detected file change (:func:`watch_ledger`) AND a verb completion
    (:meth:`force_refresh`, called after every verb regardless of scope
    or outcome) both already funnel through here, so gating the cache on
    this single counter costs nothing new and is GLOBAL by construction:
    a verb resolving one record bumps the SAME counter a completely
    unrelated record's warmed entry is stamped against, invalidating it
    too. This is deliberate, not merely convenient — 09 §2.3's surface-
    fill budget datum (Y-20/U17) means routing record X can change what
    a warm copy of record Y would have rendered (X's target surface's
    fill level), so per-record invalidation would be unsound; the
    coarse everything-invalidates-on-any-signal rule is the only
    correct one here, matching the CRITICAL staleness rule item 1 is
    built to."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def subscribe(self) -> "asyncio.Queue[RefreshEvent]":
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[RefreshEvent]") -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        """Y-14 idle-predicate leg (09 §3): connected SSE clients."""
        return len(self._subscribers)

    async def publish(self, event: RefreshEvent) -> None:
        self._generation += 1
        for q in list(self._subscribers):
            await q.put(event)

    def force_refresh(self, scope: str = "front") -> None:
        """Sync entry point (callable from non-async verb-runner code)."""
        self._generation += 1
        event = RefreshEvent(scope=scope)
        for q in list(self._subscribers):
            q.put_nowait(event)


async def watch_ledger(
    home: Path,
    hub: RefreshHub,
    *,
    stop_event: asyncio.Event | None = None,
    debounce_ms: int = DEBOUNCE_MS,
) -> None:
    """The 09 §3 refresh watcher. Returns immediately if nothing exists
    yet to watch (a brand-new ledger with no buckets) — the
    :data:`POLL_FALLBACK_SECONDS` client poll is the documented catch-up
    for that case AND for a bucket that appears after the watcher
    started (bucket-set re-discovery happens on the next Front request,
    per 09 §3 — this coroutine does not re-scan mid-run)."""
    paths = [p for p in watch_paths(home) if p.exists()]
    if not paths:
        return
    async for changes in watchfiles.awatch(
        *paths, debounce=debounce_ms, stop_event=stop_event
    ):
        scopes = {_scope_for_path(home, Path(p)) for _change, p in changes}
        for scope in scopes:
            await hub.publish(RefreshEvent(scope=scope))
