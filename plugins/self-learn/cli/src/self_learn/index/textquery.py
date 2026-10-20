"""Free-text lesson lookup, with document embeddings and explicit degradation."""
from __future__ import annotations

import copy
import math
import queue
import threading

from ..scan import redact
from . import fts5
from .gemini import GeminiEmbedder
from .hybrid import CANDIDATE_MULTIPLIER, MIN_CANDIDATES, HybridResult, Ranked
from .protocol import EmbedProvider
from .registry import load_provider
from .rrf import rrf_fuse
from .store import FROM_ENV, HYBRID, LEXICAL_ONLY, LessonIndex
from .vectors import cosine

EMBED_TIMEOUT = 20.0


def embed_documents(provider: EmbedProvider, texts: list[str], *, interactive: bool = False) -> list[list[float]]:
    """Bound the wait without handing SQLite to another thread.

    A timed-out provider cannot be forcibly stopped in Python. The daemon owns
    only its request and queue; its eventual answer is discarded, not cached.
    """
    if interactive and isinstance(provider, GeminiEmbedder):
        # Preserve document templates/model identity without mutating the shared
        # provider's bulk policy (the index/flags may be using it concurrently).
        provider = copy.copy(provider)
        provider.bulk = copy.copy(provider.interactive)
        provider.bulk.timeout = min(5.0, EMBED_TIMEOUT)
        provider.bulk.max_attempts = 1
        provider.bulk.paced = False
    answers: queue.Queue = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            answers.put((provider.embed(texts), None))
        except Exception as exc:
            answers.put((None, exc))

    threading.Thread(target=run, daemon=True).start()
    try:
        vectors, error = answers.get(timeout=EMBED_TIMEOUT)
    except queue.Empty:
        raise TimeoutError("embedding timed out") from None
    if error is not None:
        raise ValueError("embedding failed") from None
    if (not isinstance(vectors, list) or len(vectors) != len(texts)
            or any(len(v) != provider.dim or not all(math.isfinite(x) for x in v)
                   for v in vectors)):
        raise ValueError("invalid embedding response")
    return vectors


def nearest_text(
    index: LessonIndex, text: str, *, limit: int = 5,
    exclude_ids: frozenset[str] = frozenset(), provider: EmbedProvider | None = FROM_ENV,
) -> HybridResult:
    """Closest indexed lessons; callers resolve supersession before displaying.

    No writes to the index. Exclusions are applied before cutting either leg.
    A draft is a document, symmetric with the stored lesson text.
    """
    text = redact(text)[0]
    depth = max(MIN_CANDIDATES, limit * CANDIDATE_MULTIPLIER)
    lexical = [(i, s) for i, s in fts5.search(index.conn, text)
               if i not in exclude_ids][:depth]
    lexical_ids = [i for i, _ in lexical]
    mode, note = index.mode()
    cosines: dict[str, float] = {}
    semantic_ids: list[str] = []
    if mode == HYBRID:
        if provider is FROM_ENV:
            provider, note = load_provider()
        if provider is None:
            mode, note = LEXICAL_ONLY, note or "no embedding provider given"
        elif provider.model_id != index.model_id():
            mode, note = LEXICAL_ONLY, "embedding model differs from the index"
        else:
            try:
                query = embed_documents(provider, [text], interactive=True)[0]
                cosines = {i: cosine(query, v) for i, v in index.current_vectors().items()
                           if i not in exclude_ids}
                semantic_ids = sorted(cosines, key=lambda i: (-cosines[i], i))[:depth]
            except Exception as exc:
                mode = LEXICAL_ONLY
                note = "embedding timed out" if isinstance(exc, TimeoutError) else "embedding failed"
                cosines = {}
    rankings = [lexical_ids, semantic_ids] if mode == HYBRID else [lexical_ids]
    # Raw BM25 is intentionally not called a normalized lexical score.
    hits = [Ranked(i, score, None, cosines.get(i))
            for i, score in rrf_fuse(rankings)[:max(0, limit)]]
    return HybridResult(hits, mode, redact(note)[0])
