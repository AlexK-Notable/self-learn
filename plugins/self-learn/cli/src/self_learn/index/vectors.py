"""Vector storage for the lesson index: float32 blobs keyed by
``(id, model_id)``.

Ported from the user's ``keys`` project, ``keys/storage/vectors.py``
(2026-09-26) -- the blob layer only. Dropped: the optional sqlite-vec KNN
table (``corpus_vec``) and the numpy scan. The ledger holds hundreds of
records, so a pure-Python scan over the blobs answers in milliseconds, and
neither extra would come without a new dependency. Added: ``text_hash`` on
every row, so a vector of text that has since changed is never read as
current.

Keyed by ``(id, model_id)``, not id alone (kept from the source): every
read filters by model id, so vectors from two models can never be ranked
in one space -- a model change re-embeds, it never mixes.
"""

from __future__ import annotations

import sqlite3
import struct

VECTORS_DDL = """
CREATE TABLE IF NOT EXISTS lesson_vectors (
    id         TEXT    NOT NULL,
    model_id   TEXT    NOT NULL,
    text_hash  TEXT    NOT NULL,
    dim        INTEGER NOT NULL,
    vector     BLOB    NOT NULL,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (id, model_id)
)
"""


def serialize(vector: list[float]) -> bytes:
    """Pack a vector as little-endian float32 bytes."""
    return struct.pack(f"<{len(vector)}f", *vector)


def deserialize(blob: bytes) -> list[float]:
    """Unpack little-endian float32 bytes back into a list of floats."""
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity, guarding the zero-vector case.

    Providers return unit-norm vectors, which would make this a plain dot
    product -- but the norms are recomputed rather than assumed, so a
    provider that forgets degrades to a slower correct answer instead of a
    silently wrong one (kept from the source).
    """
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


class VectorStore:
    """Read/write the ``lesson_vectors`` table. Callers own commits."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        conn.execute(VECTORS_DDL)

    def upsert_many(self, rows: list[tuple[str, str, list[float]]], model_id: str, now: str) -> int:
        """``rows`` = ``[(id, text_hash, vector), ...]``. Returns rows written."""
        payload = [(i, model_id, h, len(v), serialize(v), now) for i, h, v in rows]
        self.conn.executemany(
            "INSERT INTO lesson_vectors(id, model_id, text_hash, dim, vector, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id, model_id) DO UPDATE SET text_hash=excluded.text_hash, "
            "dim=excluded.dim, vector=excluded.vector, updated_at=excluded.updated_at",
            payload,
        )
        return len(payload)

    def remove_ids(self, ids: list[str]) -> None:
        """Drop every model's vector for these ids: a vector of text that no
        longer exists must not keep answering (kept from the source)."""
        self.conn.executemany("DELETE FROM lesson_vectors WHERE id = ?", [(i,) for i in ids])

    def remove_other_models(self, model_id: str) -> int:
        cur = self.conn.execute("DELETE FROM lesson_vectors WHERE model_id != ?", (model_id,))
        return cur.rowcount or 0

    def current_ids(self, model_id: str, hashes: dict[str, str]) -> set[str]:
        """Ids whose stored vector for ``model_id`` was made from the text
        with the given hash. A vector from another model, or of older text,
        is not current."""
        rows = self.conn.execute(
            "SELECT id, text_hash FROM lesson_vectors WHERE model_id = ?", (model_id,)
        ).fetchall()
        return {i for i, h in rows if hashes.get(i) == h}

    def stored_model_ids(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT DISTINCT model_id FROM lesson_vectors")}

    def vectors(self, model_id: str) -> dict[str, list[float]]:
        """Every stored vector for ``model_id``, by id."""
        return {
            i: deserialize(blob)
            for i, blob in self.conn.execute(
                "SELECT id, vector FROM lesson_vectors WHERE model_id = ?", (model_id,)
            )
        }
