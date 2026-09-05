"""store.py — the pane transcript persistence store (task U22; 09 §11
Y-28, 10 §3 U22 row). Owns Tier 1 (render-resume) and provides the Tier 2
SDK-session mirror adapter (:class:`CacheSdkSessionStore`).

**Two separate on-disk artifacts, never conflated (Y-28 §0/§2):**

- :class:`PaneTranscriptStore` — the render-event mirror
  (``cache_dir()/panes/<slug>.jsonl`` + a ``.meta.json`` sidecar). ONE
  line per finalized :class:`~self_learn_ui.pane.TranscriptBlock`
  (``{"t":"block",...}``) or terminal ``Result`` (``{"t":"result",...}``),
  written at exactly the three pinned append points in ``pane.py``
  (``_finalize_current``, the ``ToolUse`` leg, the ``Result`` leg) and
  ``flush()``ed at write — durability is per-block append, never
  buffer-and-flush-at-teardown (Y-28 §0). This is what powers Tier-1
  render-resume: a fresh :class:`PaneManager` reconstructs a read-only
  transcript from this file alone, with no engine/session state at all.
- :class:`CacheSdkSessionStore` — the ``claude_agent_sdk.types.SessionStore``
  duck-typed adapter (``cache_dir()/panes/sdk-sessions/``) that mirrors the
  CLI's own opaque transcript entries for Tier-2 ``resume=``. Its ``append``/
  ``load`` pass entries through unexamined (the SDK's own contract,
  ``types.py:1440-1484``) — this module never parses SDK-internal shape.

**Degradation (Y-28 §7 "fail-open to a working pane, never a 500"):** every
public write method on :class:`PaneTranscriptStore` swallows ``OSError``
(logged to ``uilog``, never raised) — an unwritable cache dir disables
persistence for the process, and the live pane keeps working in-memory
exactly as it did before this task. ``read_snapshot`` parses what is
valid up to the first bad line and reports the rest via
``StoredSnapshot.corrupt``/``truncated`` — never raises into a caller.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import SessionStore
from claude_agent_sdk.types import SessionKey, SessionStoreEntry

import self_learn.primitives.chrono as chrono

from . import uilog

__all__ = [
    "CacheSdkSessionStore",
    "PaneTranscriptStore",
    "RETENTION_AGE_DAYS",
    "RETENTION_BYTE_BOUND",
    "SCHEMA_VERSION",
    "SIZE_CAP_BYTES",
    "StoredBlock",
    "StoredResult",
    "StoredSnapshot",
    "slug_for_session_key",
]

#: Y-28 §2's leading header line pin — a future shape change is
#: detectable, never silently misparsed.
SCHEMA_VERSION = 1

#: Y-28 §2's per-file soft cap — refuse-not-corrupt (a terminal marker,
#: never mid-file clipping).
SIZE_CAP_BYTES = 2 * 1024 * 1024

#: Y-28 §6's rolling retention — two bounds, no timer (opportunistic at
#: manager construction + every close/teardown flush).
RETENTION_AGE_DAYS = 30
RETENTION_BYTE_BOUND = 64 * 1024 * 1024

_BUCKET_KEY_PREFIX = "bucket:"

_TERMINAL_STATUSES = frozenset({"error", "cap-hit"})


def slug_for_session_key(session_key: str) -> str:
    """The URL/filesystem-safe encoding of a ``PaneManager`` session key
    (Y-28 §2): a bare record id passes through; a bucket key
    (``bucket:<scope>/<name>``) becomes ``bucket__<scope>__<name>``."""
    if session_key.startswith(_BUCKET_KEY_PREFIX):
        rest = session_key[len(_BUCKET_KEY_PREFIX) :]
        return "bucket__" + rest.replace("/", "__")
    return session_key


def _now_iso() -> str:
    """Adopts the shared ``%Y-%m-%dT%H:%M:%SZ`` format (M-J, plan v2
    SS2): this module's own copy previously called ``.isoformat()``
    (microseconds + a ``+00:00`` offset) -- a drift from every other
    ``_now_iso`` in the codebase, and the bug this migration closes, not
    a behavior this call site's readers depend on (``StoredBlock``'s
    ``created_at``/``updated_at`` are opaque display strings here, never
    re-parsed by this module; no test byte-pins the old shape)."""
    return chrono.now_iso()


@dataclass(frozen=True)
class StoredBlock:
    """One persisted render event — mirrors
    :class:`self_learn_ui.pane.TranscriptBlock` field-for-field (this
    module never imports ``pane.py``, to keep the dependency direction
    one-way; the shapes are kept in lockstep by ``pane.py``'s own
    conversion at the read site)."""

    kind: str
    html: str | None = None
    tool_name: str | None = None
    tool_target: str | None = None


@dataclass(frozen=True)
class StoredResult:
    status: str | None
    cost_usd: float | None
    turns: int | None
    error: str | None
    cap_hit: bool
    session_id: str | None = None


@dataclass(frozen=True)
class StoredSnapshot:
    """A read-only reconstruction of one session's persisted transcript
    (Y-28 §1 Tier 1). ``result`` is the LAST terminal Result line seen
    (a session usually has at most one meaningful terminal Result — the
    one from its last completed turn); ``None`` when the transcript has
    blocks but never reached a Result (parked mid-conversation)."""

    session_key: str
    blocks: tuple[StoredBlock, ...]
    result: StoredResult | None
    bucket_dir: str | None
    record_id_or_bucket: str | None
    sdk_session_id: str | None
    updated_at: str | None
    #: ``None`` | ``"error"`` | ``"cap-hit"`` — Y-28 §4e's third resumable
    #: clause reads this directly (survives a restart, unlike the live
    #: ``send()`` guard it backstops).
    terminal_status: str | None
    truncated: bool
    #: A bad/unparseable line was hit — ``blocks``/``result`` are the
    #: valid PREFIX up to that point, never a raise (Y-28 §7 degradation).
    corrupt: bool


class PaneTranscriptStore:
    """The Tier-1 render-event store. One JSONL file + one ``.meta.json``
    sidecar per session key, under ``panes_dir`` (the caller passes
    ``self_learn.worker.cache_dir() / "panes"`` in production —
    :func:`self_learn_ui.pane.build_pane_manager` does that, LAZILY: see
    below; this class itself never imports ``self_learn`` or touches
    env, so it is fully unit-testable against a bare ``tmp_path``).

    **Lazy directory creation (matches ``uilog``/``doctrine``'s existing
    pattern — 09/13's established laziness, not new for U22):**
    ``panes_dir`` may be a bare :class:`Path` OR a zero-arg callable
    returning one. Either way, the directory is created ON FIRST REAL
    TOUCH (a write, or a read that finds nothing — a pure ``is_file()``
    check needs no ``mkdir``), never at construction. This matters
    because ``build_pane_manager()`` (hence ``create_app()``) constructs
    a store for EVERY app instance, including every test's; eagerly
    resolving ``cache_dir()`` (which itself unconditionally ``mkdir``s
    its home-namespaced base dir, a pinned CLI-package behavior this
    module cannot change) at that point would touch the real cache dir
    for every ``create_app()`` call, not only the ones that actually
    open a pane — a regression against 10 §0 rules 7/8's "tests never
    touch the real cache" for any test that doesn't otherwise redirect
    ``XDG_CACHE_HOME``."""

    def __init__(self, panes_dir: "Path | Callable[[], Path]") -> None:
        self._panes_dir_source = panes_dir
        self._resolved_dir: Path | None = None
        self._dir_ready = False
        #: Optimistic until the first real filesystem touch proves
        #: otherwise (mirrors the lazy-resolution posture above — there
        #: is no meaningful "enabled" answer before anything was tried).
        self.enabled = True

    @property
    def _dir(self) -> Path:
        if self._resolved_dir is None:
            source = self._panes_dir_source
            self._resolved_dir = source() if callable(source) else source
        return self._resolved_dir

    @property
    def _archive_dir(self) -> Path:
        return self._dir / "archive"

    def _ensure_dir(self) -> bool:
        """Lazily ``mkdir`` the resolved dir on first real write —
        cached so a persistently-unwritable dir is not retried on every
        call. Read paths never call this (see class docstring)."""
        if self._dir_ready:
            return self.enabled
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            uilog.log(f"pane transcript store: cache dir unwritable, persistence disabled: {exc}")
            self.enabled = False
        self._dir_ready = True
        return self.enabled

    # ------------------------------------------------------------ paths

    def _path(self, session_key: str) -> Path:
        return self._dir / f"{slug_for_session_key(session_key)}.jsonl"

    def _meta_path(self, session_key: str) -> Path:
        return self._dir / f"{slug_for_session_key(session_key)}.meta.json"

    # ------------------------------------------------------------ writer

    def start_new(self, session_key: str, *, record_id_or_bucket: str, bucket_dir: str) -> None:
        """Begin a fresh transcript for *session_key* — Y-28 §6
        start-fresh: any existing file is archived first (never silently
        destroyed), then a new header line is written."""
        if not self._ensure_dir():
            return
        try:
            self._archive_existing(session_key)
            path = self._path(session_key)
            with path.open("w", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "t": "header",
                            "schema": SCHEMA_VERSION,
                            "session_key": session_key,
                            "record_id_or_bucket": record_id_or_bucket,
                            "bucket_dir": bucket_dir,
                            "created_at": _now_iso(),
                        }
                    )
                    + "\n"
                )
                f.flush()
            self._write_meta(
                session_key,
                {
                    "schema": SCHEMA_VERSION,
                    "session_key": session_key,
                    "record_id_or_bucket": record_id_or_bucket,
                    "bucket_dir": bucket_dir,
                    "sdk_session_id": None,
                    "updated_at": _now_iso(),
                    "block_count": 0,
                    "terminal_status": None,
                    "truncated": False,
                },
            )
        except OSError as exc:
            uilog.log(f"pane transcript store: start_new failed for {session_key!r}: {exc}")

    def continue_existing(self, session_key: str) -> None:
        """Y-28 Resume: keep appending to the SAME file (never
        archive-and-restart) — a no-op if the file already exists; a
        defensive ``start_new`` fallback if it somehow does not (a
        resume attempted against a store with no meta yet should still
        produce a valid, if empty-history, transcript rather than
        silently writing nothing)."""
        if not self._ensure_dir():
            return
        if not self._path(session_key).is_file():
            self.start_new(session_key, record_id_or_bucket=session_key, bucket_dir="")

    def append_block(
        self,
        session_key: str,
        *,
        kind: str,
        html: str | None = None,
        tool_name: str | None = None,
        tool_target: str | None = None,
    ) -> None:
        self._append_line(
            session_key,
            {"t": "block", "kind": kind, "html": html, "tool_name": tool_name, "tool_target": tool_target},
            bump_block_count=True,
        )

    def append_result(
        self,
        session_key: str,
        *,
        status: str | None,
        cost_usd: float | None,
        turns: int | None,
        error: str | None,
        cap_hit: bool,
        session_id: str | None,
    ) -> None:
        terminal_status = "cap-hit" if cap_hit else ("error" if error else None)
        self._append_line(
            session_key,
            {
                "t": "result",
                "status": status,
                "cost_usd": cost_usd,
                "turns": turns,
                "error": error,
                "cap_hit": cap_hit,
                "session_id": session_id,
            },
            bump_block_count=False,
            sdk_session_id=session_id,
            terminal_status=terminal_status,
        )

    _UNSET: Any = object()

    def _append_line(
        self,
        session_key: str,
        payload: dict[str, Any],
        *,
        bump_block_count: bool,
        sdk_session_id: str | None = None,
        terminal_status: Any = _UNSET,
    ) -> None:
        if not self._ensure_dir():
            return
        path = self._path(session_key)
        if not path.is_file():
            # No header ever written for this session key — a caller
            # invariant (start_new/continue_existing always precede
            # this), but degrade silently rather than raise (Y-28 §7).
            return
        try:
            meta = self._read_meta(session_key) or {}
            if meta.get("truncated"):
                return  # already capped — the live session is unaffected
            line = json.dumps(payload) + "\n"
            size = path.stat().st_size
            if size + len(line.encode("utf-8")) > SIZE_CAP_BYTES:
                self._write_truncated_marker(path)
                meta["truncated"] = True
                meta["updated_at"] = _now_iso()
                self._write_meta(session_key, meta)
                return
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
            if bump_block_count:
                meta["block_count"] = int(meta.get("block_count") or 0) + 1
            if sdk_session_id is not None:
                meta["sdk_session_id"] = sdk_session_id
            if terminal_status is not self._UNSET:
                meta["terminal_status"] = terminal_status
            meta["updated_at"] = _now_iso()
            self._write_meta(session_key, meta)
        except OSError as exc:
            uilog.log(f"pane transcript store: append failed for {session_key!r}: {exc}")

    def _write_truncated_marker(self, path: Path) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": "truncated", "reason": "size-cap", "at": _now_iso()}) + "\n")
            f.flush()

    # ------------------------------------------------------------ reader

    def read_snapshot(self, session_key: str) -> StoredSnapshot | None:
        """Reconstructs a :class:`StoredSnapshot`, or ``None`` when
        nothing persisted (missing file — identical to "never opened
        this session," Y-28 §7's first degradation row). A pure read —
        never ``mkdir``s (see class docstring's laziness note); a
        not-yet-created dir simply has no matching file."""
        path = self._path(session_key)
        try:
            exists = path.is_file()
        except OSError:
            # An unreadable/untraversable dir (e.g. a permission-denied
            # parent) — degrade exactly like "nothing persisted," never
            # raise into a route (Y-28 §7).
            return None
        if not exists:
            return None
        blocks: list[StoredBlock] = []
        result: StoredResult | None = None
        header_seen = False
        corrupt = False
        truncated = False
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except json.JSONDecodeError:
                        corrupt = True
                        break
                    kind = obj.get("t")
                    if kind == "header":
                        if obj.get("schema") != SCHEMA_VERSION:
                            corrupt = True
                            break
                        header_seen = True
                    elif kind == "block":
                        if not header_seen:
                            corrupt = True
                            break
                        blocks.append(
                            StoredBlock(
                                kind=obj.get("kind", ""),
                                html=obj.get("html"),
                                tool_name=obj.get("tool_name"),
                                tool_target=obj.get("tool_target"),
                            )
                        )
                    elif kind == "result":
                        if not header_seen:
                            corrupt = True
                            break
                        result = StoredResult(
                            status=obj.get("status"),
                            cost_usd=obj.get("cost_usd"),
                            turns=obj.get("turns"),
                            error=obj.get("error"),
                            cap_hit=bool(obj.get("cap_hit")),
                            session_id=obj.get("session_id"),
                        )
                    elif kind == "truncated":
                        truncated = True
                    # else: an unknown/future line type — forward-compat skip.
        except OSError as exc:
            uilog.log(f"pane transcript store: read failed for {session_key!r}: {exc}")
            return None
        if not header_seen:
            # Nothing readable at all (empty file, or corrupt from line 1)
            # — Y-28 §7: "if nothing parses, treat as no history."
            return None
        meta = self._read_meta(session_key) or {}
        return StoredSnapshot(
            session_key=session_key,
            blocks=tuple(blocks),
            result=result,
            bucket_dir=meta.get("bucket_dir") or None,
            record_id_or_bucket=meta.get("record_id_or_bucket"),
            sdk_session_id=meta.get("sdk_session_id"),
            updated_at=meta.get("updated_at"),
            terminal_status=meta.get("terminal_status"),
            truncated=truncated or bool(meta.get("truncated")),
            corrupt=corrupt,
        )

    # ------------------------------------------------------------- meta

    def _read_meta(self, session_key: str) -> dict[str, Any] | None:
        path = self._meta_path(session_key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_meta(self, session_key: str, meta: dict[str, Any]) -> None:
        path = self._meta_path(session_key)
        tmp = Path(str(path) + ".tmp")
        try:
            tmp.write_text(json.dumps(meta), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            uilog.log(f"pane transcript store: meta write failed for {session_key!r}: {exc}")

    # --------------------------------------------------------- archiving

    def _archive_existing(self, session_key: str) -> None:
        path = self._path(session_key)
        if not path.is_file():
            return
        try:
            self._archive_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            dest = self._archive_dir / f"{slug_for_session_key(session_key)}.{ts}.jsonl"
            path.replace(dest)
        except OSError as exc:
            uilog.log(f"pane transcript store: archive failed for {session_key!r}: {exc}")
        meta_path = self._meta_path(session_key)
        if meta_path.is_file():
            try:
                meta_path.unlink()
            except OSError:
                pass

    # --------------------------------------------------------- retention

    def prune(self) -> None:
        """Y-28 §6: opportunistic rolling prune — an age bound and a byte
        bound, no timer. Called at manager construction and at every
        close/teardown flush (never a scheduled job — keeps this
        UI-package-only). A no-op (no ``mkdir``) when the dir was never
        created — nothing to prune."""
        if not self._dir.is_dir():
            return
        try:
            self._prune_by_age()
            self._prune_by_bytes()
        except OSError as exc:
            uilog.log(f"pane transcript store: prune failed: {exc}")

    def _live_files(self) -> list[Path]:
        return list(self._dir.glob("*.jsonl")) if self._dir.is_dir() else []

    def _archive_files(self) -> list[Path]:
        return list(self._archive_dir.glob("*.jsonl")) if self._archive_dir.is_dir() else []

    def _unlink_with_meta(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return
        meta = path.parent / f"{path.stem}.meta.json"
        if meta.is_file():
            try:
                meta.unlink()
            except OSError:
                pass

    def _prune_by_age(self) -> None:
        cutoff = time.time() - RETENTION_AGE_DAYS * 86400
        for f in self._live_files() + self._archive_files():
            try:
                if f.stat().st_mtime < cutoff:
                    self._unlink_with_meta(f)
            except OSError:
                continue

    def _prune_by_bytes(self) -> None:
        files = [f for f in self._live_files() + self._archive_files() if f.is_file()]
        try:
            total = sum(f.stat().st_size for f in files)
        except OSError:
            return
        if total <= RETENTION_BYTE_BOUND:
            return
        files.sort(key=lambda f: f.stat().st_mtime)
        for f in files:
            if total <= RETENTION_BYTE_BOUND:
                break
            try:
                size = f.stat().st_size
                self._unlink_with_meta(f)
                total -= size
            except OSError:
                continue


# ------------------------------------------------- Tier-2 SDK session store

_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_-]")


class CacheSdkSessionStore(SessionStore):
    """``claude_agent_sdk.types.SessionStore`` adapter (Y-28 §1 Tier 2):
    mirrors the CLI's own opaque transcript entries to ``root`` so a
    later engine can ``resume=<session_id>``. Entries are treated as
    pass-through blobs (the Protocol's own contract,
    ``types.py:1440-1484``) — this class never interprets their shape,
    only round-trips ``json.dumps``/``json.loads`` (the documented
    invariant).

    **SUBCLASSES ``SessionStore`` and overrides ONLY ``append``/``load``
    — the four OPTIONAL methods (``list_sessions``/
    ``list_session_summaries``/``delete``/``list_subkeys``) are left
    UNDEFINED here, inherited verbatim from the Protocol (2026-07-19
    U22-fix, live-DoD-caught BLOCKER; see git history for the prior,
    WRONG shape).** This is load-bearing, not stylistic: the SDK's own
    ``_store_implements()`` probe
    (``claude_agent_sdk/_internal/session_store_validation.py:8-14``)
    decides whether a method is "implemented" by comparing
    ``getattr(type(store), method, None)`` against
    ``getattr(SessionStore, method, None)`` BY IDENTITY — it does NOT
    call the method and catch ``NotImplementedError``. A prior version
    of this class defined stub bodies for all four
    (``async def list_subkeys(self, key): raise NotImplementedError``)
    to satisfy pyright's structural-Protocol check without subclassing;
    that made every stub a DISTINCT function object from
    ``SessionStore``'s own, so ``_store_implements()`` reported ``True``
    for all four — and ``materialize_resume_session()``
    (``session_resume.py:172-175``) then unconditionally called
    ``list_subkeys()`` on every Tier-2 Resume, which raised
    ``NotImplementedError``, surfacing to the human as "SessionStore.
    list_subkeys() for session <id> failed during resume materialization:"
    (the exact live-trial failure, reproduced verbatim by a unit test
    that imports and drives the SDK's REAL ``materialize_resume_session``
    against this store). Leaving the four methods undefined makes
    ``type(store).list_subkeys is SessionStore.list_subkeys`` hold
    (same object, inherited), so ``_store_implements()`` correctly
    reports ``False`` — ``materialize_resume_session`` skips
    ``_materialize_subkeys`` entirely, exactly like the raw-SDK
    build-trial probe (which never defined the four either — a plain
    duck-typed class with no subclassing at all, which is why THAT
    probe never hit this path). ``PaneManager`` never calls
    ``list_sessions``/``list_session_summaries``/``delete``/
    ``list_subkeys`` itself either way. Failures on the required two
    degrade silently (logged) — the SDK itself already retries/backs
    off per its own docstring; a store-side raise here would only make
    things worse."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _key_path(self, key: SessionKey) -> Path:
        project = _SAFE_KEY_RE.sub("_", str(key.get("project_key", "default")))[:80]
        session_id = str(key["session_id"])
        subpath = key.get("subpath")
        name = f"{session_id}__{subpath.replace('/', '_')}" if subpath else session_id
        d = self._root / project
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{name}.jsonl"

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        try:
            path = self._key_path(key)
            with path.open("a", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")
                f.flush()
        except OSError as exc:
            uilog.log(f"sdk session store: append failed: {exc}")

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        try:
            path = self._key_path(key)
        except OSError as exc:
            uilog.log(f"sdk session store: load path resolution failed: {exc}")
            return None
        if not path.is_file():
            return None
        out: list[SessionStoreEntry] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            uilog.log(f"sdk session store: load failed: {exc}")
            return None
        return out or None

    # The four OPTIONAL SessionStore methods (list_sessions/
    # list_session_summaries/delete/list_subkeys) are DELIBERATELY left
    # undefined — see the class docstring's load-bearing explanation.
    # Do not add stub overrides here, even ones that just
    # ``raise NotImplementedError`` — that flips the SDK's own
    # ``_store_implements()`` probe from False to True and reintroduces
    # the live-DoD BLOCKER this class exists to avoid.
