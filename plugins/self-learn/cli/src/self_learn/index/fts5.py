"""FTS5 word search over the lesson index -- OR semantics, porter stemming,
stopword filter, BM25 ranking.

Ported from the user's ``keys`` project, ``keys/search/fts5.py``
(2026-09-26). Kept: OR semantics (the FTS5 default AND collapses a
multi-word natural-language query -- measured there at ~12% top-1 vs ~56%
for OR), the shared tokenizer applied once, and the rule that only a QUERY
problem may read as "no matches" while a structural one (dropped table,
renamed column) propagates. Dropped: ``keys``' tier scoping and its
key/desc columns. Changed: the table is ``lessons_fts(id UNINDEXED,
text)``, and results are ``(id, bm25)`` pairs.

BM25 from sqlite is **lower is better** (negative magnitudes).
"""

from __future__ import annotations

import logging
import sqlite3

from .tokenize import tokenize

_log = logging.getLogger(__name__)

FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts "
    "USING fts5(id UNINDEXED, text, tokenize='porter unicode61')"
)


def build_or_match(tokens: list[str]) -> str:
    """Join de-duplicated tokens with `` OR `` (duplicates would inflate
    BM25 weight). Every token is word characters only, so nothing can
    escape into FTS5 syntax."""
    seen: set[str] = set()
    unique: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return " OR ".join(unique)


def search(conn: sqlite3.Connection, text: str, *, limit: int | None = None) -> list[tuple[str, float]]:
    """``[(id, bm25), ...]`` best first (ties by id) for an OR query built
    from ``text``. An empty or all-stopword query returns ``[]``."""
    tokens = [t.lower() for t in tokenize(text)]
    if not tokens:
        return []
    expr = build_or_match(tokens)
    sql = (
        "SELECT id, bm25(lessons_fts) AS s FROM lessons_fts "
        "WHERE lessons_fts MATCH ? ORDER BY s ASC, id ASC"
    )
    params: tuple = (expr,)
    if limit is not None:
        sql += " LIMIT ?"
        params = (expr, limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "syntax error" in msg or "malformed match" in msg or "fts5" in msg:
            _log.warning("FTS5 rejected a query: %s", exc)
            return []
        raise
    return [(str(r[0]), float(r[1])) for r in rows]
