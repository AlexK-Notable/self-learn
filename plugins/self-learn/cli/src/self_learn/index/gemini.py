"""Gemini embedding provider (``gemini-embedding-2``), stdlib only.

Ported from the user's ``keys`` project, ``keys/embed/gemini.py``
(2026-09-26), which was itself ported from znote-mcp's
``services/gemini_provider.py``. Changes here: the key and pacing variables
are self-learn's (``SELF_LEARN_GEMINI_API_KEY`` is read first, then
``GEMINI_API_KEY``; ``SELF_LEARN_GEMINI_RPM``); the missing-key message
names the environment variables and the host unit's environment file and
nothing else (self-learn never calls a secrets manager -- the user,
2026-09-26 19:32: "don't wire bws into the project itself"); and the real
network seam refuses to run under pytest (below).

Everything asserted here was measured against the live API -- by the
znote-mcp probe (``scripts/probe_gemini_embed.py``, artifacts in
``benchmarks/gemini_probe_*.json``, 2026-08-15) or by ``keys``' own:

- **``taskType`` is accepted and SILENTLY IGNORED by this model.** Cosine
  measured at exactly 1.000000 between bare / ``RETRIEVAL_QUERY`` /
  ``RETRIEVAL_DOCUMENT`` variants of the same text. Asymmetry comes from
  PROMPT INSTRUCTIONS instead (the templates below).
- **Batches cap at 100 requests** -- 250 returns HTTP 400 "at most 100
  requests can be in one batch".
- **Multiple parts in ONE request AGGREGATE into a single vector.** Every
  text therefore gets its own request inside ``batchEmbedContents``.
- **Outputs are unit-normalized at 3072 and at MRL 1536/768** (norm 1.0
  measured at each). L2 normalization is kept anyway: cheap, and a
  regression on Google's side would otherwise distort every ranking.
- **Inputs past 8,192 tokens are silently truncated, but
  ``usageMetadata.promptTokenCount`` reports the PRE-truncation count** --
  so truncation is detectable per response, and is logged and counted.

Two retry profiles, because one policy cannot serve both call shapes:

- ``interactive`` (``embed_query``): short timeout, 2 attempts, no pacing.
- ``bulk`` (``embed``): 8 attempts, 2s doubling to 60s with jitter,
  ``Retry-After`` honored, RPM pacing.

**No test reaches Google.** :meth:`GeminiEmbedder._http_post` -- the only
code that opens a connection -- refuses while ``PYTEST_CURRENT_TEST`` is
set. A test fakes the API by passing ``transport=``, which never touches
``_http_post``; that is what "explicitly faked" means here.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Sequence

_log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-embedding-2"
DEFAULT_DIM = 3072

# Hard API limit, not a tuning knob: 250 is rejected outright.
MAX_BATCH = 100

# The model's input window -- 4x the 2,048 of gemini-embedding-001.
MAX_INPUT_TOKENS = 8192

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:{action}"

#: Checked in order; an empty value counts as absent. The first lets
#: self-learn be pointed at a different key than the rest of the machine.
KEY_ENV_VARS: tuple[str, ...] = ("SELF_LEARN_GEMINI_API_KEY", "GEMINI_API_KEY")

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

RPM_ENV = "SELF_LEARN_GEMINI_RPM"
DEFAULT_RPM = 20

# Retrieval-asymmetry prompt templates -- Google's recommended configuration
# for gemini-embedding-2, and the ONLY asymmetry mechanism since taskType is
# ignored. INSTRUCTION_VERSION is part of model_id so a template change
# invalidates stored vectors through the model-identity check.
INSTRUCTION_VERSION = "i1"
QUERY_TEMPLATE = "task: search result | query: {text}"
DOCUMENT_TEMPLATE = "title: {title} | text: {text}"

_MAX_TITLE_CHARS = 200

#: The environment variable pytest sets for the duration of every test.
PYTEST_MARKER = "PYTEST_CURRENT_TEST"


def format_query_text(text: str) -> str:
    """Wrap a search query in the recommended retrieval instruction."""
    return QUERY_TEMPLATE.format(text=text)


def format_document_text(text: str, title: str | None = None) -> str:
    """Wrap a document in the recommended document instruction."""
    clean = (title or "").strip() or "none"
    return DOCUMENT_TEMPLATE.format(title=clean[:_MAX_TITLE_CHARS], text=text)


class GeminiEmbedError(RuntimeError):
    """The API cannot be used at all (missing/bad key, exhausted retries,
    or a real call attempted under pytest)."""


class _RateLimiter:
    """Minimum-interval throttle shared across bulk worker threads."""

    def __init__(self, rpm: int) -> None:
        self._interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_at)
            self._next_at = start + self._interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


class _Profile:
    """One retry/timeout policy. Two instances exist; see module docstring."""

    def __init__(
        self,
        *,
        timeout: float,
        max_attempts: int,
        base_delay: float,
        max_delay: float,
        paced: bool,
    ) -> None:
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.paced = paced


def key_present() -> bool:
    """True when any of :data:`KEY_ENV_VARS` holds a non-empty value.
    Never returns or logs the value."""
    return any(os.environ.get(var) for var in KEY_ENV_VARS)


def _resolve_key(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for var in KEY_ENV_VARS:
        value = os.environ.get(var)
        if value:  # empty string counts as absent
            return value
    raise GeminiEmbedError(
        "no Gemini API key: set SELF_LEARN_GEMINI_API_KEY or GEMINI_API_KEY "
        "in the environment (for the host service, in its optional "
        "environment file ~/.config/self-learn/env)"
    )


def _l2_normalize(vector: list[float]) -> list[float]:
    """Scale to unit length; leave an all-zero vector alone."""
    norm = sum(v * v for v in vector) ** 0.5
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


class GeminiEmbedder:
    """``EmbedProvider`` backed by the hosted gemini-embedding-2 model."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        dim: int = DEFAULT_DIM,
        api_key: str | None = None,
        rpm: int | None = None,
        max_workers: int = 3,
        transport: Callable[..., dict] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._key = _resolve_key(api_key)
        self._model = model
        self.dim = dim
        self._max_workers = max_workers
        self._transport = transport or self._http_post
        # Late-bound on purpose: `sleep=time.sleep` as a default argument
        # binds at import time and defeats monkeypatching `time.sleep`.
        self._sleep = sleep if sleep is not None else (lambda d: time.sleep(d))

        if rpm is None:
            try:
                rpm = int(os.environ.get(RPM_ENV, DEFAULT_RPM))
            except ValueError:
                rpm = DEFAULT_RPM
        self.rpm = rpm
        self._limiter = _RateLimiter(rpm)

        # Width AND instruction template are part of vector identity.
        self.model_id = f"{model}@{dim}/{INSTRUCTION_VERSION}"
        self.max_input_tokens = MAX_INPUT_TOKENS

        self.interactive = _Profile(
            timeout=5.0, max_attempts=2, base_delay=0.5, max_delay=1.0, paced=False
        )
        self.bulk = _Profile(
            timeout=120.0, max_attempts=8, base_delay=2.0, max_delay=60.0, paced=True
        )

        self._stats_lock = threading.Lock()
        self.stats: dict[str, int] = {
            "requests": 0,
            "retries": 0,
            "http_429": 0,
            "prompt_tokens": 0,
            "truncated_inputs": 0,
        }

    # -- Protocol surface -------------------------------------------------

    def embed(self, texts: list[str] | Sequence[str]) -> list[list[float]]:
        """Embed documents (bulk profile, paced, batched)."""
        self._require_nonempty(texts)
        items = [format_document_text(t) for t in texts]
        return self._embed_all(items, profile=self.bulk)

    def embed_query(self, texts: list[str] | Sequence[str]) -> list[list[float]]:
        """Embed search queries with the recommended query instruction."""
        self._require_nonempty(texts)
        items = [format_query_text(t) for t in texts]
        return self._embed_all(items, profile=self.interactive)

    # -- Internals ----------------------------------------------------------

    def _embed_all(self, items: list[str], *, profile: _Profile) -> list[list[float]]:
        if not items:
            return []
        # Emptiness was validated on the caller's RAW texts before
        # templating: a templated string is never empty.
        chunks = [items[i : i + MAX_BATCH] for i in range(0, len(items), MAX_BATCH)]
        if len(chunks) == 1:
            results = [self._embed_requests(chunks[0], profile=profile)]
        else:
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                # pool.map preserves submission order.
                results = list(
                    pool.map(lambda c: self._embed_requests(c, profile=profile), chunks)
                )
        flat = [vec for chunk in results for vec in chunk]
        if len(flat) != len(items):
            raise GeminiEmbedError(
                f"embedding count mismatch: sent {len(items)}, got {len(flat)}"
            )
        return flat

    @staticmethod
    def _require_nonempty(texts: Sequence[str]) -> None:
        for i, t in enumerate(texts):
            if not t or not t.strip():
                raise ValueError(
                    f"cannot embed empty/whitespace text (index {i}) -- an "
                    "empty input would produce a garbage vector silently"
                )

    def _http_post(self, action: str, body: dict, timeout: float) -> dict:
        # The one place a connection opens. Under pytest it refuses: a test
        # that wants the API faked passes `transport=` and never gets here.
        if os.environ.get(PYTEST_MARKER):
            raise GeminiEmbedError(
                "refusing a real Gemini API call under pytest -- pass "
                "transport= to fake the API"
            )
        request = urllib.request.Request(
            _ENDPOINT.format(model=self._model, action=action),
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._key,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError) -> float | None:
        """Server-mandated wait, if present -- beats any local guess."""
        try:
            value = exc.headers.get("Retry-After")
        except AttributeError:
            return None
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None  # HTTP-date form; fall back to our own backoff

    def _post(self, action: str, body: dict, profile: _Profile) -> dict:
        delay = profile.base_delay
        last: Exception | None = None

        for attempt in range(1, profile.max_attempts + 1):
            if profile.paced:
                # Pace retries too -- an unpaced retry is another way to hit
                # the quota wall.
                self._limiter.wait()
            with self._stats_lock:
                self.stats["requests"] += 1
            try:
                return self._transport(action, body, timeout=profile.timeout)
            except GeminiEmbedError:
                raise
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code == 429:
                    with self._stats_lock:
                        self.stats["http_429"] += 1
                server_delay = self._retry_after(exc)
                if server_delay is not None:
                    delay = min(max(server_delay, profile.base_delay), profile.max_delay)
                if exc.code == 400:
                    detail = exc.read()[:300].decode(errors="replace")
                    raise GeminiEmbedError(f"Gemini rejected the request: {detail}")
                if exc.code in (401, 403):
                    raise GeminiEmbedError(
                        f"Gemini auth failed (HTTP {exc.code}) -- check the API key"
                    )
                if exc.code not in _RETRY_STATUS:
                    raise GeminiEmbedError(f"Gemini returned HTTP {exc.code}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc

            if attempt < profile.max_attempts:
                with self._stats_lock:
                    self.stats["retries"] += 1
                # Jitter so throttled workers don't retry on the same tick.
                wait = delay * (1.0 + random.random() * 0.25)
                _log.warning(
                    "gemini embed attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt, profile.max_attempts, type(last).__name__, wait,
                )
                self._sleep(wait)
                delay = min(delay * 2, profile.max_delay)

        raise GeminiEmbedError(
            f"Gemini embedding failed after {profile.max_attempts} attempts: "
            f"{type(last).__name__}. Embedding is incremental -- a re-run "
            "resumes where it stopped."
        )

    def _account_usage(self, payload: dict, n_inputs: int) -> None:
        """Track promptTokenCount and flag truncation.

        PRE-truncation counts are reported (measured), so a count above the
        cap means that input WAS silently cut. Per-item usageMetadata is per
        input; the top-level entry is an AGGREGATE, only comparable to the
        cap for a single-input request and never counted on top of per-item
        entries. Coverage is judged by usable counts, not by the presence of
        a usageMetadata dict.
        """
        top = payload.get("usageMetadata")
        aggregate = top if isinstance(top, dict) else None
        per_item = [
            item["usageMetadata"]
            for item in (payload.get("embeddings") or [])
            if isinstance(item, dict) and isinstance(item.get("usageMetadata"), dict)
        ]
        counts = [
            u.get("promptTokenCount")
            for u in per_item
            if isinstance(u.get("promptTokenCount"), int)
        ]
        if counts and len(counts) < n_inputs and aggregate is not None:
            counts = []  # partial per-item coverage: prefer the aggregate

        if counts:
            truncated = sum(1 for c in counts if c > MAX_INPUT_TOKENS)
            with self._stats_lock:
                self.stats["prompt_tokens"] += sum(counts)
                self.stats["truncated_inputs"] += truncated
            if truncated:
                _log.warning(
                    "gemini SILENTLY TRUNCATED %d of %d inputs (> %d-token cap)",
                    truncated, n_inputs, MAX_INPUT_TOKENS,
                )
        elif aggregate is not None:
            count = aggregate.get("promptTokenCount")
            if isinstance(count, int):
                with self._stats_lock:
                    self.stats["prompt_tokens"] += count
                if count > MAX_INPUT_TOKENS and n_inputs == 1:
                    with self._stats_lock:
                        self.stats["truncated_inputs"] += 1
                    _log.warning(
                        "gemini input SILENTLY TRUNCATED: %d tokens > %d cap",
                        count, MAX_INPUT_TOKENS,
                    )

    def _embed_requests(self, texts: list[str], *, profile: _Profile) -> list[list[float]]:
        """One request PER TEXT via batchEmbedContents (never multiple parts
        in one content: that aggregates into a single vector). No
        ``taskType`` -- this model ignores it."""
        body = {
            "requests": [
                {
                    "model": f"models/{self._model}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": self.dim,
                }
                for text in texts
            ]
        }
        payload = self._post("batchEmbedContents", body, profile)
        embeddings = payload.get("embeddings") or []
        if len(embeddings) != len(texts):
            raise GeminiEmbedError(f"asked for {len(texts)} embeddings, got {len(embeddings)}")
        self._account_usage(payload, len(texts))

        out: list[list[float]] = []
        for i, item in enumerate(embeddings):
            values = item.get("values") or []
            if len(values) != self.dim:
                raise GeminiEmbedError(f"embedding {i} has dim {len(values)}, expected {self.dim}")
            out.append(_l2_normalize([float(v) for v in values]))
        return out

    def __repr__(self) -> str:  # never include the key
        return (
            f"GeminiEmbedder(model_id={self.model_id!r}, "
            f"dim={self.dim}, workers={self._max_workers})"
        )


def build_gemini_embedder(*, dim: int = DEFAULT_DIM, model: str = DEFAULT_MODEL) -> GeminiEmbedder:
    """Build the provider or raise :class:`GeminiEmbedError` with the reason."""
    try:
        return GeminiEmbedder(model, dim=dim)
    except GeminiEmbedError:
        raise
    except Exception as exc:
        raise GeminiEmbedError(f"could not build gemini embedder: {type(exc).__name__}") from exc
