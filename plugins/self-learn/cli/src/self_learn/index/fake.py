"""Deterministic fake embedding provider for tests.

Ported from the user's ``keys`` project, ``keys/embed/fake.py``
(2026-09-26), unchanged in behaviour.

Same input text -> same output vector (run-to-run, machine-to-machine).
Vectors are unit-norm so cosine similarity reduces to a dot product.
Determinism is the point: the tests rank against this rather than the real
model, so they need no network and give identical results everywhere.

Stdlib only -- ``hashlib.sha256`` derives deterministic bytes, every two
bytes map to a float in ``[-1, 1)``, then the vector is L2-normalized. The
seed is folded into the hash input so different ``seed`` values yield
different vectors (and a different ``model_id``) for the same text.
"""

from __future__ import annotations

import hashlib
import math


class FakeEmbeddingProvider:
    """Deterministic, unit-norm embedding provider (an ``EmbedProvider``).

    ``calls`` counts the texts embedded, so tests can assert what an
    incremental build re-embedded.
    """

    model_id: str
    dim: int

    def __init__(self, dim: int = 64, seed: int = 0) -> None:
        self.dim = dim
        self.seed = seed
        self.model_id = f"fake-deterministic-v1[dim={dim},seed={seed}]"
        self.calls: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one unit-norm vector per input text."""
        self.calls.extend(texts)
        return [self._vec_from_text(t) for t in texts]

    def _vec_from_text(self, text: str) -> list[float]:
        """Chain sha256 from ``f"{seed}:{text}"`` to 2 bytes per float, map
        each uint16 to ``[-1, 1)``, L2-normalize (an all-zero vector falls
        back to norm 1.0)."""
        needed_bytes = self.dim * 2
        buf = bytearray()
        digest = hashlib.sha256(f"{self.seed}:{text}".encode("utf-8")).digest()
        buf.extend(digest)
        while len(buf) < needed_bytes:
            digest = hashlib.sha256(digest).digest()
            buf.extend(digest)
        vec = [
            (int.from_bytes(buf[i : i + 2], "big") / 32768.0) - 1.0
            for i in range(0, needed_bytes, 2)
        ]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
