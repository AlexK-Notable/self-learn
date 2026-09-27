"""Reciprocal Rank Fusion (Cormack et al. 2009).

Ported from the user's ``keys`` project, ``keys/search/rrf.py``
(2026-09-26). The single-scored-ranking input shape is dropped (nothing
here passes it); ties are broken by id so the fused order is deterministic.

RRF reads only *ranks*, never scores -- which is what lets it combine bm25
(negative, lower is better) with cosine ([-1, 1], higher is better)
without normalizing either.
"""

from __future__ import annotations

from typing import Sequence


def rrf_fuse(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[tuple[str, float]]:
    """Fuse rank-ordered id lists: ``score(d) = sum_i 1 / (k + rank_i(d))``
    with 1-based ranks; a doc absent from a ranking contributes nothing
    from it. Returns ``[(id, score), ...]``, best first, ties by id.
    ``k=60`` is Cormack et al.'s recommendation."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank_idx, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank_idx + 1)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
