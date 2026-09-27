"""Embedding provider Protocol.

Ported from the user's ``keys`` project, ``keys/embed/protocol.py``
(2026-09-26). Dropped: ``EmbeddingResult`` and ``embed_item``, which carry
``keys``' corpus item type; the model2vec note (that provider is not
ported).

Design notes (kept from the source):
- The Protocol exposes ``embed(texts) -> list[list[float]]`` (batch-first;
  callers wanting one vector pass a single-element list).
- ``dim`` and ``model_id`` are required attributes -- the vector store
  records ``model_id`` beside every vector, and vectors from a different
  model are treated as missing rather than ranked across two incomparable
  spaces.
- Vectors are ``list[float]``, never numpy arrays: the return type is what
  gets serialized to SQLite, and keeping it stdlib means the store never
  needs numpy to read a row back.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbedProvider(Protocol):
    """Embedding backend contract: ``model_id``, ``dim``, batch ``embed``."""

    model_id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one unit-norm vector per input text, in order."""
        ...


def embed_query(provider: EmbedProvider, texts: list[str]) -> list[list[float]]:
    """Embed search queries, using the provider's query mode if it has one.

    Retrieval can be asymmetric: Gemini expects a short question and the
    passage that answers it to be wrapped differently. Symmetric providers
    (the test fake) do not define ``embed_query`` and fall through to
    ``embed``. The lesson index compares lesson to lesson, which is
    symmetric, so it embeds everything as documents; this stays for a
    free-text search over the index.
    """
    method = getattr(provider, "embed_query", None)
    if callable(method):
        return method(texts)  # type: ignore[no-any-return]
    return provider.embed(texts)
