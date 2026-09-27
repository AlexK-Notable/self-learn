"""Related lessons, and the batches the steward reads them in.

Spec 02-schema.md §3a.7. The user's words (2026-09-26 18:13): "yes, lessons
from the same project but different sessions count as related. maybe this
is where we leverage embeddings to get real semantic similarity between
lessons." Their batching rule (2026-09-20): "3-4 lessons that all trace
back to the same session log can and maybe should be batched together for
1 steward. the absolute maximum should be 10 ... the maximum number of
unrelated lessons a given agent should parse is 5."

**related(a, b)** is true when

1. **same session** -- the two records' evidence names a session id in
   common, or a transcript entry uuid in common (a resumed or forked
   session file copies entries with their uuid: the same uuid is one
   moment, 02-schema.md §3a.6); or
2. **same bucket and close in meaning** -- the same bucket ``(scope,
   name)`` (never the name alone: skill ``x`` and project ``x`` are
   different buckets) AND similarity at or above the threshold. Similarity
   is the cosine of the two stored embeddings when the index is ``hybrid``
   and a threshold has been measured for its model; otherwise the lexical
   similarity -- the mean, over both directions, of how well one record's
   text retrieves the other by BM25, relative to how well it retrieves
   itself (``LessonIndex.lexical_profile``). One basis per call to
   :func:`group_for_steward`; two scales are never mixed.

**group_for_steward(ids)**: groups of at most 10 records, in each of which
at most 5 records are related to no other member. Connected pieces of the
relatedness graph stay together (a piece over 10 is split greedily along
its edges), then pieces are packed first-fit largest first, then the
unrelated records fill groups up to the caps. Same input, same output: ids
are de-duplicated and sorted, every tie breaks on record id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .store import HYBRID, LessonDoc, LessonIndex
from .vectors import cosine

MAX_GROUP = 10
MAX_UNRELATED = 5

#: Cosine threshold per embedding model id. A model without an entry has
#: no measured meaning for its cosine, so relatedness uses the lexical basis
#: for it and says so.
#:
#: MEASURED 2026-09-26 over the live ledger (212 records, 22,366 pairs, one
#: embedding pass): same-bucket pairs that share no session and are not a
#: replacement pair sit at median 0.641, p95 0.743, p99 0.795 (user bucket
#: p95 0.723; skill buckets run higher, median 0.722, being one topic by
#: construction); the 13 replacement pairs (``supersedes``/``superseded_by``
#: -- the same lesson rewritten) sit at 0.760-0.985, median 0.899. 0.75 is
#: just above the same-bucket p95, keeps all 13 replacement pairs, and marks
#: 282 of 7,058 same-bucket pairs (4.0%) related; pairs read at the boundary
#: (0.75-0.80) shared a concrete subject (Bash-tool shell behaviour, a
#: concurrent writer to one file, Govee lights), pairs at 0.70-0.715 only a
#: genre ("agent behaviour"). Same-session pairs are NOT close in meaning
#: (median 0.658, near the background), which is why session is its own rule.
COSINE_THRESHOLDS: dict[str, float] = {"gemini-embedding-2@3072/i1": 0.75}

#: Lexical-similarity threshold (normalized BM25, both directions averaged).
#: MEASURED 2026-09-26 on the same pass: the same same-bucket background
#: sits at median 0.050, p95 0.141, p99 0.225; replacement pairs 0.207-0.905. 0.16 is the
#: value that best reproduces the cosine >= 0.75 decision on same-bucket
#: pairs (F1 0.66: precision 0.70, recall 0.64) and keeps all 13
#: replacement pairs. Word overlap is a weaker signal than meaning; it is
#: the floor the host runs on until a key is configured.
LEXICAL_THRESHOLD = 0.16

SESSION = "session"
BUCKET_SIMILAR = "bucket+similar"


@dataclass(frozen=True)
class Relation:
    a: str
    b: str
    related: bool
    reasons: tuple[str, ...]  # SESSION and/or BUCKET_SIMILAR
    same_bucket: bool
    shared_sessions: tuple[str, ...]
    shared_uuids: tuple[str, ...]
    similarity: float | None
    basis: str  # "cosine" | "lexical"

    def to_json(self) -> dict:
        return {
            "a": self.a,
            "b": self.b,
            "related": self.related,
            "reasons": list(self.reasons),
            "same_bucket": self.same_bucket,
            "shared_sessions": list(self.shared_sessions),
            "shared_uuids": list(self.shared_uuids),
            "similarity": None if self.similarity is None else round(self.similarity, 4),
            "basis": self.basis,
        }


class Relatedness:
    """Pairwise relatedness over one open index, with one fixed basis."""

    def __init__(
        self,
        index: LessonIndex,
        *,
        cosine_threshold: float | None = None,
        lexical_threshold: float | None = None,
    ) -> None:
        self.index = index
        self.docs: dict[str, LessonDoc] = index.docs()
        mode, mode_reason = index.mode()
        model = index.model_id()
        threshold = cosine_threshold
        if threshold is None and model is not None:
            threshold = COSINE_THRESHOLDS.get(model)
        if mode == HYBRID and threshold is not None:
            self.basis = "cosine"
            self.threshold = threshold
            self.basis_reason = f"cosine over {model} embeddings"
            self._vectors = index.current_vectors()
        else:
            self.basis = "lexical"
            self.threshold = LEXICAL_THRESHOLD if lexical_threshold is None else lexical_threshold
            if mode != HYBRID:
                self.basis_reason = f"lexical: index is lexical-only ({mode_reason})"
            else:
                self.basis_reason = f"lexical: no measured cosine threshold for {model}"
            self._vectors = {}

    def similarity(self, a: str, b: str) -> float | None:
        if a not in self.docs or b not in self.docs:
            return None
        if self.basis == "cosine":
            va, vb = self._vectors.get(a), self._vectors.get(b)
            if va is None or vb is None:
                return None
            return cosine(va, vb)
        ab = self.index.lexical_profile(a).get(b, 0.0)
        ba = self.index.lexical_profile(b).get(a, 0.0)
        return (ab + ba) / 2.0

    def relation(self, a: str, b: str) -> Relation:
        da, db = self.docs.get(a), self.docs.get(b)
        if da is None or db is None:
            return Relation(a, b, False, (), False, (), (), None, self.basis)
        sessions = tuple(sorted(set(da.sessions) & set(db.sessions)))
        uuids = tuple(sorted(set(da.uuids) & set(db.uuids)))
        same_bucket = da.bucket == db.bucket
        sim = self.similarity(a, b) if same_bucket else None
        reasons: list[str] = []
        if sessions or uuids:
            reasons.append(SESSION)
        if same_bucket and sim is not None and sim >= self.threshold:
            reasons.append(BUCKET_SIMILAR)
        return Relation(
            a, b, bool(reasons), tuple(reasons), same_bucket, sessions, uuids, sim, self.basis
        )


def related(
    index: LessonIndex,
    a: str,
    b: str,
    *,
    cosine_threshold: float | None = None,
    lexical_threshold: float | None = None,
) -> Relation:
    """Is ``a`` related to ``b``? (module docstring). ``related`` on the
    result is the answer; ``reasons`` says which rule held."""
    return Relatedness(
        index, cosine_threshold=cosine_threshold, lexical_threshold=lexical_threshold
    ).relation(a, b)


@dataclass(frozen=True)
class Group:
    members: tuple[str, ...]
    unrelated: tuple[str, ...]
    links: tuple[Relation, ...]

    def to_json(self) -> dict:
        return {
            "members": list(self.members),
            "unrelated": list(self.unrelated),
            "links": [r.to_json() for r in self.links],
        }


@dataclass
class Grouping:
    groups: list[Group]
    basis: str
    basis_reason: str
    threshold: float
    not_indexed: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "basis": self.basis,
            "basis_reason": self.basis_reason,
            "threshold": self.threshold,
            "not_indexed": list(self.not_indexed),
            "groups": [g.to_json() for g in self.groups],
        }


def _split(component: list[str], adj: dict[str, set[str]], max_size: int) -> list[list[str]]:
    """Cut a connected piece larger than ``max_size`` into chunks that
    follow its edges: seed each chunk with the lowest remaining id, then
    add the remaining member with the most edges into the chunk (ties by
    id) until the chunk is full or nothing left touches it."""
    remaining = sorted(component)
    chunks: list[list[str]] = []
    while remaining:
        chunk = [remaining[0]]
        left = set(remaining[1:])
        while len(chunk) < max_size:
            best: tuple[int, str] | None = None
            for cand in sorted(left):
                edges = len(adj[cand] & set(chunk))
                if edges and (best is None or edges > best[0]):
                    best = (edges, cand)
            if best is None:
                break
            chunk.append(best[1])
            left.discard(best[1])
        chunks.append(chunk)
        remaining = sorted(left)
    return chunks


def group_for_steward(
    record_ids: Iterable[str],
    *,
    index: LessonIndex,
    max_size: int = MAX_GROUP,
    max_unrelated: int = MAX_UNRELATED,
    cosine_threshold: float | None = None,
    lexical_threshold: float | None = None,
) -> Grouping:
    """Batch ``record_ids`` for the steward (module docstring). Ids the
    index does not hold are grouped as unrelated and listed in
    ``not_indexed``."""
    if max_size < 1 or max_unrelated < 0:
        raise ValueError("max_size must be >= 1 and max_unrelated >= 0")
    rel = Relatedness(index, cosine_threshold=cosine_threshold, lexical_threshold=lexical_threshold)
    ids = sorted(set(record_ids))
    relations: dict[tuple[str, str], Relation] = {}
    adj: dict[str, set[str]] = {i: set() for i in ids}
    for x, a in enumerate(ids):
        for b in ids[x + 1:]:
            r = rel.relation(a, b)
            if r.related:
                relations[(a, b)] = r
                adj[a].add(b)
                adj[b].add(a)

    # Connected pieces, each found from its lowest id.
    seen: set[str] = set()
    pieces: list[list[str]] = []
    for start in ids:
        if start in seen:
            continue
        piece: list[str] = []
        stack = [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            piece.append(node)
            for nxt in sorted(adj[node], reverse=True):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        pieces.append(sorted(piece))

    blocks: list[list[str]] = []
    singles: list[str] = []
    for piece in pieces:
        chunks = [piece] if len(piece) <= max_size else _split(piece, adj, max_size)
        for chunk in chunks:
            if len(chunk) == 1:
                singles.append(chunk[0])
            else:
                blocks.append(chunk)
    blocks.sort(key=lambda b: (-len(b), b[0]))
    singles.sort()

    def unrelated_in(members: list[str]) -> list[str]:
        return [m for m in members if not (adj[m] & set(members))]

    groups: list[list[str]] = []
    for block in blocks:
        for g in groups:
            if len(g) + len(block) <= max_size:
                g.extend(block)
                break
        else:
            groups.append(list(block))
    for single in singles:
        for g in groups:
            if len(g) < max_size and len(unrelated_in(g + [single])) <= max_unrelated:
                g.append(single)
                break
        else:
            groups.append([single])

    out: list[Group] = []
    for g in groups:
        members = tuple(g)
        links = tuple(
            relations[(a, b)]
            for x, a in enumerate(sorted(members))
            for b in sorted(members)[x + 1:]
            if (a, b) in relations
        )
        out.append(Group(members=members, unrelated=tuple(unrelated_in(g)), links=links))
    return Grouping(
        groups=out,
        basis=rel.basis,
        basis_reason=rel.basis_reason,
        threshold=rel.threshold,
        not_indexed=[i for i in ids if i not in rel.docs],
    )
