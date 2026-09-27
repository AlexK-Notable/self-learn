"""The lesson index: one SQLite file in the cache, one row per record.

Spec 02-schema.md §3a.7. Location: ``<cache_dir(home)>/index/lessons.sqlite``
-- the cache, never the ledger; deleting it loses nothing a rebuild cannot
recreate.

Tables:

- ``lessons`` -- one row per ledger record, every status: id, bucket
  ``(scope, name)``, status, the sha256 of its index text, the session ids
  and entry uuids its evidence names (``related.py`` reads these).
- ``lessons_fts`` -- FTS5 over the index text (``fts5.py``).
- ``lesson_vectors`` -- embeddings keyed by ``(id, model_id)`` with the
  text hash they were made from (``vectors.py``).
- ``meta`` -- last build time, the index's embedding model, the last
  build's counts and why embedding sat out if it did.

**Index text** = the record's ``Trigger`` + ``Instruction`` (behavior) or
``Fact`` + ``Context`` (knowledge) sections, then each evidence quote, one
per line, passed through the secret scan's ``redact`` (the text goes to an
outside API).

**Incremental.** A build re-embeds only records whose text hash changed or
that have no vector from the current model, and drops every row -- FTS,
vectors -- of a record that no longer exists. A model change re-embeds
everything; vectors of the old model are deleted only once the new model
covers every record, and no read ever mixes two models.

**Degradation.** No key, a provider switched off, or the API failing never
raises out of :meth:`LessonIndex.build`: the index is ``lexical-only`` and
``mode_reason`` says why.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..ledger import discover_buckets, resolve_home
from ..primitives import chrono
from ..records import Record
from ..refs import Ref
from ..scan import redact
from . import fts5
from .gemini import key_present
from .protocol import EmbedProvider
from .registry import load_provider
from .vectors import VectorStore

INDEX_SUBDIR = "index"
INDEX_FILE = "lessons.sqlite"

HYBRID = "hybrid"
LEXICAL_ONLY = "lexical-only"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS lessons ("
    " id TEXT PRIMARY KEY, bucket_scope TEXT NOT NULL, bucket_name TEXT NOT NULL,"
    " status TEXT NOT NULL, text_hash TEXT NOT NULL, sessions TEXT NOT NULL,"
    " uuids TEXT NOT NULL, supersedes TEXT, superseded_by TEXT, indexed_at TEXT NOT NULL)",
    fts5.FTS_DDL,
)

_TEXT_SECTIONS = {
    "behavior": ("Trigger", "Instruction"),
    "knowledge": ("Fact", "Context"),
}
_HEADING = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
_ORIGIN = re.compile(r"^transcript:([^#\s]+)#L\d+$")

#: Sentinel: "choose the provider from the environment" (registry).
FROM_ENV: Any = object()


def _now_iso() -> str:
    return chrono.now_iso()


def index_path(home: Path | str | None = None, *, create: bool = False) -> Path:
    """The index file. ``create=False`` resolves the path without making
    the cache directory (a status read must not create it)."""
    from .. import worker  # late: worker and serve import far more than the index needs
    from ..serve import cache_dir_readonly

    home = Path(home).expanduser() if home is not None else resolve_home()
    base = worker.cache_dir(home) if create else cache_dir_readonly(home)
    return base / INDEX_SUBDIR / INDEX_FILE


# ------------------------------------------------------------ the records


def _sections(body: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(body))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.setdefault(m.group(1).strip(), body[m.end():end].strip())
    return out


def lesson_text(record: Record) -> str:
    """The index text of one record (module docstring), redacted."""
    sections = _sections(record.body)
    parts = [sections[name] for name in _TEXT_SECTIONS.get(record.type, ()) if sections.get(name)]
    quotes = [
        str(e["quote"]).strip()
        for e in record.evidence
        if isinstance(e, dict) and isinstance(e.get("quote"), str) and e["quote"].strip()
    ]
    if quotes:
        parts.append("\n".join(quotes))
    text, _hits = redact("\n\n".join(parts))
    return text


def evidence_moments(evidence) -> tuple[set[str], set[str]]:
    """``(session ids, entry uuids)`` named by a record's evidence.

    Session ids come from a U1 ref (``ref:`` as a mapping in the
    02-schema.md §3a.6 shape), from ``session:``, and from a legacy
    ``origin: transcript:<session>#L<n>``. Uuids come from refs only. An
    older ``ref:`` that is a plain string (a recurrence handle) is not a
    transcript ref and is ignored.
    """
    sessions: set[str] = set()
    uuids: set[str] = set()
    for item in evidence or ():
        if not isinstance(item, dict):
            continue
        raw_ref = item.get("ref")
        if isinstance(raw_ref, dict):
            try:
                ref = Ref.from_dict(raw_ref)
            except (KeyError, TypeError, ValueError):
                ref = None
            if ref is not None:
                sessions.add(ref.session)
                if ref.uuid:
                    uuids.add(ref.uuid)
        session = item.get("session")
        if isinstance(session, str) and session.strip():
            sessions.add(session.strip())
        origin = item.get("origin")
        if isinstance(origin, str):
            m = _ORIGIN.match(origin.strip())
            if m:
                sessions.add(m.group(1))
    return sessions, uuids


@dataclass(frozen=True)
class LessonDoc:
    """One record as the index sees it."""

    id: str
    bucket_scope: str
    bucket_name: str
    status: str
    text: str
    text_hash: str
    sessions: tuple[str, ...]
    uuids: tuple[str, ...]
    supersedes: str | None = None
    superseded_by: str | None = None

    @property
    def bucket(self) -> tuple[str, str]:
        """Bucket identity is ``(scope, name)``, never the name alone."""
        return (self.bucket_scope, self.bucket_name)


def _plain(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def collect(home: Path | str) -> tuple[list[LessonDoc], list[str]]:
    """Every record under every bucket (``pending/`` and ``resolved/``),
    sorted by id, plus the ledger-relative paths of files that would not
    parse. Read-only."""
    home = Path(home).expanduser()
    docs: dict[str, LessonDoc] = {}
    unreadable: list[str] = []
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            folder = bucket.path / sub
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                except Exception:  # noqa: BLE001 -- one broken file costs that file
                    unreadable.append(str(path.relative_to(home)))
                    continue
                text = lesson_text(record)
                sessions, uuids = evidence_moments(record.evidence)
                docs[record.id] = LessonDoc(
                    id=record.id,
                    bucket_scope=bucket.scope,
                    bucket_name=bucket.name,
                    status=record.status,
                    text=text,
                    text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    sessions=tuple(sorted(sessions)),
                    uuids=tuple(sorted(uuids)),
                    supersedes=_plain(record.supersedes),
                    superseded_by=_plain(record.superseded_by),
                )
    return [docs[k] for k in sorted(docs)], unreadable


# -------------------------------------------------------------- the index


@dataclass
class BuildReport:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    embedded: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    model: str | None = None
    embed_error: str = ""
    mode: str = LEXICAL_ONLY
    mode_reason: str = ""

    def to_json(self) -> dict:
        return {
            "added": len(self.added),
            "changed": len(self.changed),
            "removed": len(self.removed),
            "embedded": len(self.embedded),
            "unreadable": list(self.unreadable),
            "model": self.model,
            "embed_error": self.embed_error or None,
            "mode": self.mode,
            "mode_reason": self.mode_reason,
        }


class LessonIndex:
    """An open lesson index. Use :meth:`open` (creates) or
    :meth:`open_existing` (``None`` when never built)."""

    def __init__(self, conn: sqlite3.Connection, path: Path, home: Path) -> None:
        self.conn = conn
        self.path = path
        self.home = home
        self.vectors = VectorStore(conn)
        self._lexical_cache: dict[str, dict[str, float]] = {}
        self._vector_cache: dict[str, list[float]] | None = None

    @classmethod
    def open(cls, home: Path | str | None = None) -> "LessonIndex":
        home = Path(home).expanduser() if home is not None else resolve_home()
        path = index_path(home, create=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        for ddl in _SCHEMA:
            conn.execute(ddl)
        index = cls(conn, path, home)
        conn.commit()
        return index

    @classmethod
    def open_existing(cls, home: Path | str | None = None) -> "LessonIndex | None":
        home = Path(home).expanduser() if home is not None else resolve_home()
        path = index_path(home, create=False)
        if not path.is_file():
            return None
        return cls.open(home)

    def close(self) -> None:
        self.conn.close()

    # -- meta ----------------------------------------------------------------

    def meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str | None) -> None:
        if value is None:
            self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        else:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # -- reads ---------------------------------------------------------------

    def docs(self) -> dict[str, LessonDoc]:
        """Every indexed record by id (text read back from FTS)."""
        texts = dict(self.conn.execute("SELECT id, text FROM lessons_fts").fetchall())
        out: dict[str, LessonDoc] = {}
        for row in self.conn.execute(
            "SELECT id, bucket_scope, bucket_name, status, text_hash, sessions, uuids,"
            " supersedes, superseded_by FROM lessons ORDER BY id"
        ):
            out[row[0]] = LessonDoc(
                id=row[0], bucket_scope=row[1], bucket_name=row[2], status=row[3],
                text=texts.get(row[0], ""), text_hash=row[4],
                sessions=tuple(json.loads(row[5])), uuids=tuple(json.loads(row[6])),
                supersedes=row[7], superseded_by=row[8],
            )
        return out

    def model_id(self) -> str | None:
        """The model the index embeds with (the last build that had one)."""
        return self.meta("model_id")

    def _hashes(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT id, text_hash FROM lessons").fetchall())

    def mode(self) -> tuple[str, str]:
        """``(mode, reason)``. ``hybrid`` only when every indexed record has
        a current vector from the index's model; otherwise ``lexical-only``
        and the reason."""
        hashes = self._hashes()
        total = len(hashes)
        model = self.model_id()
        last_error = self.meta("embed_error") or ""
        embedder_reason = self.meta("embedder_reason") or ""
        if total == 0:
            return LEXICAL_ONLY, "the index holds no records"
        if model is None:
            return LEXICAL_ONLY, embedder_reason or last_error or "no embeddings built yet"
        have = len(self.vectors.current_ids(model, hashes))
        if have == total:
            return HYBRID, ""
        why = f"vectors from {model} cover {have} of {total} records"
        extra = last_error or embedder_reason
        return LEXICAL_ONLY, f"{why}; {extra}" if extra else why

    def record_vectors(self) -> dict[str, list[float]]:
        """Every record's CURRENT vector from the index's model (made from
        the record's present text), by id -- whether or not every record
        has one. Relatedness decides per pair from these."""
        model = self.model_id()
        if model is None:
            return {}
        current = self.vectors.current_ids(model, self._hashes())
        return {i: v for i, v in self.vectors.vectors(model).items() if i in current}

    def current_vectors(self) -> dict[str, list[float]]:
        """Current-model vectors by id ({} unless the index is hybrid)."""
        if self._vector_cache is None:
            mode, _ = self.mode()
            model = self.model_id()
            self._vector_cache = (
                self.vectors.vectors(model) if mode == HYBRID and model else {}
            )
        return self._vector_cache

    def lexical_profile(self, record_id: str) -> dict[str, float]:
        """``{other id: bm25(this -> other) / bm25(this -> this)}`` over
        every record the record's own text matches: how well each other
        record answers this record's words, relative to the record itself
        (1.0 = as well; clamped to 1.0). Cached per open index."""
        cached = self._lexical_cache.get(record_id)
        if cached is not None:
            return cached
        row = self.conn.execute(
            "SELECT text FROM lessons_fts WHERE id = ?", (record_id,)
        ).fetchone()
        profile: dict[str, float] = {}
        if row:
            hits = fts5.search(self.conn, row[0])
            scores = dict(hits)
            self_score = scores.get(record_id)
            if self_score is not None and self_score < 0:
                for other, score in hits:
                    if other != record_id:
                        profile[other] = min(1.0, score / self_score)
        self._lexical_cache[record_id] = profile
        return profile

    # -- build ---------------------------------------------------------------

    def build(self, provider: EmbedProvider | None = FROM_ENV) -> BuildReport:
        """Bring the index up to date with the ledger (incremental; module
        docstring). ``provider`` defaults to the environment's choice
        (``registry.load_provider``); ``None`` means lexical-only. Never
        raises for a missing key or a failing API."""
        report = BuildReport()
        embedder_reason = ""
        if provider is FROM_ENV:
            provider, embedder_reason = load_provider()
        elif provider is None:
            embedder_reason = "no embedding provider given"

        docs, report.unreadable = collect(self.home)
        now = _now_iso()
        existing = self._hashes()
        current = {d.id: d for d in docs}

        report.removed = sorted(set(existing) - set(current))
        for i in report.removed:
            self.conn.execute("DELETE FROM lessons WHERE id = ?", (i,))
            self.conn.execute("DELETE FROM lessons_fts WHERE id = ?", (i,))
        self.vectors.remove_ids(report.removed)

        for d in docs:
            old = existing.get(d.id)
            if old is None:
                report.added.append(d.id)
            elif old != d.text_hash:
                report.changed.append(d.id)
            if old != d.text_hash:
                self.conn.execute("DELETE FROM lessons_fts WHERE id = ?", (d.id,))
                self.conn.execute("INSERT INTO lessons_fts(id, text) VALUES (?, ?)", (d.id, d.text))
            self.conn.execute(
                "INSERT INTO lessons(id, bucket_scope, bucket_name, status, text_hash, sessions,"
                " uuids, supersedes, superseded_by, indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET bucket_scope=excluded.bucket_scope,"
                " bucket_name=excluded.bucket_name, status=excluded.status,"
                " text_hash=excluded.text_hash, sessions=excluded.sessions,"
                " uuids=excluded.uuids, supersedes=excluded.supersedes,"
                " superseded_by=excluded.superseded_by, indexed_at=excluded.indexed_at",
                (d.id, d.bucket_scope, d.bucket_name, d.status, d.text_hash,
                 json.dumps(list(d.sessions)), json.dumps(list(d.uuids)),
                 d.supersedes, d.superseded_by, now),
            )
        # A changed text's old vectors (every model) describe text that no
        # longer exists.
        self.vectors.remove_ids(report.changed)
        self.conn.commit()

        hashes = {d.id: d.text_hash for d in docs}
        self._set_meta("embed_error", None)
        if provider is not None:
            model = provider.model_id
            report.model = model
            have = self.vectors.current_ids(model, hashes)
            need = [d for d in docs if d.id not in have and d.text.strip()]
            try:
                vecs = provider.embed([d.text for d in need]) if need else []
                if len(vecs) != len(need):
                    raise RuntimeError(f"provider returned {len(vecs)} vectors for {len(need)} texts")
                self.vectors.upsert_many(
                    [(d.id, d.text_hash, v) for d, v in zip(need, vecs)], model, now
                )
                report.embedded = [d.id for d in need]
                self._set_meta("model_id", model)
                if len(self.vectors.current_ids(model, hashes)) == len(docs):
                    self.vectors.remove_other_models(model)
            except Exception as exc:  # noqa: BLE001 -- a broken API never stops a caller
                report.embed_error = f"embedding failed: {type(exc).__name__}: {exc}"[:500]
                self._set_meta("embed_error", report.embed_error)
        self._set_meta("embedder_reason", embedder_reason or None)
        self._set_meta("last_build_at", now)
        self._set_meta("last_build", json.dumps(report.to_json(), sort_keys=True))
        self.conn.commit()
        self._lexical_cache.clear()
        self._vector_cache = None
        report.mode, report.mode_reason = self.mode()
        self._set_meta("last_build", json.dumps(report.to_json(), sort_keys=True))
        self.conn.commit()
        return report

    # -- status --------------------------------------------------------------

    def status(self, *, ledger_docs: list[LessonDoc] | None = None) -> dict:
        """The data points a future dashboard reads (``index status --json``)."""
        hashes = self._hashes()
        by_status: dict[str, int] = {}
        buckets: set[tuple[str, str]] = set()
        for s, scope, name in self.conn.execute(
            "SELECT status, bucket_scope, bucket_name FROM lessons"
        ):
            by_status[s] = by_status.get(s, 0) + 1
            buckets.add((scope, name))
        model = self.model_id()
        have = len(self.vectors.current_ids(model, hashes)) if model else 0
        mode, reason = self.mode()
        last_build = self.meta("last_build")
        stale = None
        if ledger_docs is not None:
            live = {d.id: d.text_hash for d in ledger_docs}
            stale = {
                "not_indexed": sum(1 for i in live if i not in hashes),
                "changed": sum(1 for i, h in live.items() if i in hashes and hashes[i] != h),
                "gone": sum(1 for i in hashes if i not in live),
            }
        return {
            "built": True,
            "path": str(self.path),
            "records": len(hashes),
            "by_status": dict(sorted(by_status.items())),
            "buckets": len(buckets),
            "mode": mode,
            "mode_reason": reason,
            "model": model,
            "vectors": {"current": have, "missing": len(hashes) - have if model else len(hashes)},
            "last_build_at": self.meta("last_build_at"),
            "last_build": json.loads(last_build) if last_build else None,
            "stale": stale,
            "key_present": key_present(),
        }
