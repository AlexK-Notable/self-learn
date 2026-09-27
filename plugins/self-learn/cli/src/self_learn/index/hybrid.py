"""Hybrid ranking: the lessons nearest one lesson, word search and
embeddings fused with RRF.

Adapted from the user's ``keys`` project, ``keys/search/hybrid.py``
(2026-09-26). Kept: the two rankers fused by rank only (bm25 and cosine
are not comparable), each leg pulled deeper than the final cut so fusion
can promote, and **total degradation**: with no vectors, or vectors from
another model, or partial coverage, the result is the lexical ranking
alone and ``mode`` says so -- a silent fallback must never read as
semantic search that found nothing. Changed: the query is a lesson already
in the index, so its stored vector is the query vector (no API call at
read time), and the lesson itself is excluded from its own ranking.
Dropped: ``keys``' synonym expansion and tier scoping.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rrf import rrf_fuse
from .store import HYBRID, LEXICAL_ONLY, LessonIndex
from .vectors import cosine

CANDIDATE_MULTIPLIER = 3
MIN_CANDIDATES = 20


@dataclass(frozen=True)
class Ranked:
    id: str
    rrf: float
    lexical: float | None  # normalized bm25 (see LessonIndex.lexical_profile)
    cosine: float | None


@dataclass(frozen=True)
class HybridResult:
    hits: list[Ranked]
    mode: str  # "hybrid" | "lexical-only"
    note: str = ""


def nearest(index: LessonIndex, record_id: str, *, limit: int = 10) -> HybridResult:
    """The ``limit`` lessons nearest ``record_id``, best first."""
    depth = max(MIN_CANDIDATES, limit * CANDIDATE_MULTIPLIER)
    profile = index.lexical_profile(record_id)
    lexical_ids = [i for i, _ in sorted(profile.items(), key=lambda kv: (-kv[1], kv[0]))][:depth]

    mode, note = index.mode()
    vectors = index.current_vectors()
    cosines: dict[str, float] = {}
    semantic_ids: list[str] = []
    if mode == HYBRID and record_id in vectors:
        query = vectors[record_id]
        cosines = {i: cosine(query, v) for i, v in vectors.items() if i != record_id}
        semantic_ids = [i for i, _ in sorted(cosines.items(), key=lambda kv: (-kv[1], kv[0]))][:depth]
    else:
        mode = LEXICAL_ONLY

    rankings = [lexical_ids, semantic_ids] if semantic_ids else [lexical_ids]
    fused = rrf_fuse(rankings)
    hits = [
        Ranked(id=i, rrf=score, lexical=profile.get(i), cosine=cosines.get(i))
        for i, score in fused[:limit]
    ]
    return HybridResult(hits=hits, mode=mode, note=note)
