"""Find situations where routed rules may apply (12 §13.2).

Synchronous planning API: R2 runs this before invoking the model. The returned
mode/note must be recorded even when there are no flags. No ledger writes.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .. import hosts, refs
from ..index import fts5
from ..index.protocol import EmbedProvider
from ..index.registry import load_provider
from ..index.rrf import rrf_fuse
from ..index.store import FROM_ENV, HYBRID, LEXICAL_ONLY, LessonIndex, _sections
from ..index.textquery import embed_documents
from ..index.vectors import cosine
from ..ledger import Bucket
from ..scan import redact
from .tools import Stretch, blocks, load_records, raw

LEXICAL_BAR = 0.30
COSINE_BAR = 0.75
MAX_PER_RULE = 2
MAX_FLAGS = 8


@dataclass(frozen=True)
class Flag:
    record: str
    after_turn: int
    start_line: int
    end_line: int
    lexical: float
    cosine: float | None
    score: float
    rule: str


@dataclass(frozen=True)
class FlagResult:
    flags: tuple[Flag, ...]
    mode: str
    note: str


def _in_scope(bucket: Bucket, cwd: Path, projects: list[Path], entries: Sequence[dict | None]) -> bool:
    if bucket.scope == "project":
        paths = [p.resolve() for p in projects if hosts.slug_for(p) == bucket.name]
        return not paths or any(cwd.resolve().is_relative_to(p) for p in paths)
    if bucket.scope == "skill":
        for entry in entries:
            if not entry:
                continue
            if f"skills/{bucket.name}/" in raw(entry):
                return True
            if refs.role_of(entry) in ("assistant", "subagent"):
                for b in blocks(entry):
                    if b.get("type") == "tool_use" and b.get("name") == "Skill":
                        value = (b.get("input") or {}).get("skill")
                        if value == bucket.name:
                            return True
        return False
    return bucket.scope == "user"


def flag_rules(index: LessonIndex, stretches: Sequence[Stretch], *, cwd: Path,
               entries: Sequence[dict | None] = (),
               provider: EmbedProvider | None = FROM_ENV) -> FlagResult:
    """Rank work stretches against routed rules; no masking in production."""
    records = load_records(index.home)
    projects = hosts.load_hosts(index.home).projects
    candidates = [(rid, record) for rid, (bucket, record) in records.items()
                  if record.status == "routed" and not record.superseded_by
                  and _in_scope(bucket, cwd, projects, entries)]
    mode, note = index.mode()
    vectors = index.current_vectors()
    documents = [redact(s.text)[0] for s in stretches]
    embedded: list[list[float]] = []
    if mode == HYBRID and candidates and documents:
        if provider is FROM_ENV:
            provider, note = load_provider()
        if provider is None:
            mode, note = LEXICAL_ONLY, note or "no embedding provider given"
        elif provider.model_id != index.model_id():
            mode, note = LEXICAL_ONLY, "embedding model differs from the index"
        elif any(rid not in vectors for rid, _ in candidates):
            mode, note = LEXICAL_ONLY, "routed rule vectors missing"
        else:
            try:
                embedded = embed_documents(provider, documents, interactive=True)
                # Validate against stored dimensions before ranking ANY rule.
                if any(len(v) != len(embedded[0]) for v in vectors.values()):
                    raise ValueError("dimension mismatch")
            except Exception as exc:
                mode = LEXICAL_ONLY
                note = "embedding timed out" if isinstance(exc, TimeoutError) else "embedding failed"
                embedded = []
    conn = sqlite3.connect(":memory:")
    flags: list[Flag] = []
    try:
        conn.execute(fts5.FTS_DDL)
        conn.executemany("INSERT INTO lessons_fts VALUES (?, ?)",
                         [(str(n), text) for n, text in enumerate(documents)])
        for rid, record in candidates:
            sections = _sections(record.body)
            names = ("Trigger",) if record.type == "behavior" else ("Fact", "Context")
            query = redact("\n".join(sections.get(name, "") for name in names))[0]
            conn.execute("INSERT INTO lessons_fts VALUES ('query', ?)", (query,))
            scores = dict(fts5.search(conn, query))
            conn.execute("DELETE FROM lessons_fts WHERE id = 'query'")
            own = scores.pop("query", 0)
            lexical = {i: min(1.0, s / own) for i, s in scores.items()} if own < 0 else {}
            lex_ids = sorted(lexical, key=lambda i: (-lexical[i], i))
            cosines = {str(n): cosine(vectors[rid], v) for n, v in enumerate(embedded)}
            sem_ids = sorted(cosines, key=lambda i: (-cosines[i], i))
            ranking = rrf_fuse([lex_ids, sem_ids] if embedded else [lex_ids])
            kept = 0
            for i, score in ranking:
                lex, cos = lexical.get(i, 0.0), cosines.get(i)
                if lex < LEXICAL_BAR and (cos is None or cos < COSINE_BAR):
                    continue
                s = stretches[int(i)]
                flags.append(Flag(rid, s.after_turn, s.start_line, s.end_line, lex, cos, score, query))
                kept += 1
                if kept == MAX_PER_RULE:
                    break
    finally:
        conn.close()
    flags.sort(key=lambda f: (-f.score, -f.lexical, -(f.cosine or 0), f.record, f.after_turn))
    return FlagResult(tuple(flags[:MAX_FLAGS]), mode, redact(note)[0])
