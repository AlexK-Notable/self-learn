"""Provider selection -- one place that decides which embedder the lesson
index uses.

Adapted from the user's ``keys`` project, ``keys/embed/registry.py``
(2026-09-26). ``keys`` has a local model2vec default and raises when an
explicitly requested provider cannot be built; self-learn has one hosted
provider and a different contract: **no key, or no provider, is never an
error that stops a caller** -- the index is lexical-only and says why
(spec 02-schema.md §3a.7). So :func:`load_provider` returns
``(provider | None, reason)`` and never raises.

Indexing and every similarity read must agree on the model, because a
vector is only comparable to vectors from the same model; the index
records the model id beside every vector and reads only its own model's.

``SELF_LEARN_EMBED_PROVIDER``: ``gemini`` (the default) or ``none`` (force
lexical-only, e.g. to rebuild without spending API calls).
"""

from __future__ import annotations

import os

from .gemini import DEFAULT_DIM, GeminiEmbedError, build_gemini_embedder, key_present
from .protocol import EmbedProvider

PROVIDER_ENV = "SELF_LEARN_EMBED_PROVIDER"
PROVIDERS = ("gemini", "none")


def load_provider(name: str | None = None, *, dim: int | None = None) -> tuple[EmbedProvider | None, str]:
    """Return ``(provider, "")`` or ``(None, reason)``. Never raises."""
    resolved = (name or os.environ.get(PROVIDER_ENV) or "gemini").lower()
    if resolved not in PROVIDERS:
        return None, (
            f"unknown embedding provider {resolved!r} in {PROVIDER_ENV} "
            f"(known: {', '.join(PROVIDERS)})"
        )
    if resolved == "none":
        return None, f"embedding switched off ({PROVIDER_ENV}=none)"
    if not key_present():
        return None, (
            "no Gemini API key in the environment "
            "(SELF_LEARN_GEMINI_API_KEY or GEMINI_API_KEY)"
        )
    try:
        return build_gemini_embedder(dim=dim or DEFAULT_DIM), ""
    except GeminiEmbedError as exc:
        return None, f"gemini provider unavailable: {exc}"
