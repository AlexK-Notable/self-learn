"""Task-scoped lesson selection (S-161); no persistent writes or watchdogs."""
from __future__ import annotations

import argparse
import contextlib
import glob
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

from . import domain, gitops
from .compilers import _reference_block, entry_line, loaded_text_problem
from .hosts import capture_host_path
from .index import fts5
from .index.protocol import EmbedProvider
from .index.related import COSINE_THRESHOLDS, LEXICAL_THRESHOLD
from .index.rrf import rrf_fuse
from .index.store import FROM_ENV, index_path, lesson_text
from .index.textquery import embed_documents, embedding_failure_note
from .index.registry import load_provider
from .index.vectors import cosine, deserialize
from .ledger import EXIT_NO_HOME, discover_buckets, home_state, home_state_message, resolve_home
from .ledger_ops import ProposalError, _compile_glob_pattern, _glob_match, bucket_project_path, globs_may_intersect
from .records import Record
from .scan import redact


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("select", help="read-only lessons for a task; never kicks background work")
    p.add_argument("--query", required=True, help="task description")
    p.add_argument("--path", action="append", default=[], help="file or glob, relative to project (repeatable); globs expand existing files")
    p.add_argument("--project", type=Path, help="project directory (includes its lessons plus user lessons)")
    p.add_argument("--skill", action="append", default=[], help="also include this skill's lessons (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="ID")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--no-embed", action="store_true", help="lexical only; make no embedding request")
    p.add_argument("--json", action="store_true", help="one result object; stdout contains no prose")


PATH_SCAN_LIMIT = 10_000
PATH_SCAN_SECONDS = 1.0


def task_paths(paths: list[str], root: Path) -> list[str]:
    """Root-relative literals or bounded glob witnesses, with no symlink descent.

    Missing literal files are allowed. A budget refusal is explicit so a
    partial filesystem view cannot silently omit an applicable gated lesson.
    """
    out: set[str] = set()
    patterns = []
    raw_patterns: list[str] = []
    roots: set[Path] = set()
    for raw in paths:
        absolute = Path(raw).expanduser()
        if not absolute.is_absolute():
            absolute = root / absolute
        relative = absolute.resolve().relative_to(root).as_posix()
        try:
            pattern = _compile_glob_pattern(relative)
        except ProposalError as exc:
            raise ValueError(str(exc)) from exc
        if glob.has_magic(relative):
            patterns.append(pattern)
            raw_patterns.append(relative)
            prefix = []
            for part in relative.split("/"):
                if glob.has_magic(part):
                    break
                prefix.append(part)
            anchor = root.joinpath(*prefix)
            if anchor.is_dir():
                roots.add(anchor)
        else:
            out.add(relative)
    if patterns:
        deadline = time.monotonic() + PATH_SCAN_SECONDS
        pending = [p for p in sorted(roots) if not any(parent in roots for parent in p.parents)]
        visited = 0
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        visited += 1
                        if visited > PATH_SCAN_LIMIT or time.monotonic() > deadline:
                            raise ValueError("path glob scan budget exhausted; supply narrower globs or literal paths")
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            name = Path(entry.path).relative_to(root).as_posix()
                            depth = len(name.split("/"))
                            if any(("**" in p.split("/") or depth < len(p.split("/")))
                                   and globs_may_intersect(p, name + "/**") for p in raw_patterns):
                                pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            name = Path(entry.path).relative_to(root).as_posix()
                            if any(p.match(name) for p in patterns):
                                out.add(name)
            except OSError as exc:
                raise ValueError(f"path glob scan failed: {type(exc).__name__}") from exc
    return sorted(out)


def agent_text(record: Record) -> str:
    """Keep reference/hook sections whole, including their Context.

    Managed-line destinations already refuse multiline substance at routing.
    Older records can predate that gate: never truncate those either.
    """
    destination = (record.routing or {}).get("destination", "").split(":", 1)[0]
    if destination in {"reference", "hook"} or loaded_text_problem(record, "claude-md"):
        return _reference_block(record)
    return entry_line(record)


def _lexical(texts: dict[str, str], query: str) -> dict[str, float]:
    """Same symmetric normalized BM25 scale as Relatedness, in RAM only.

    The synthetic query is a document so both directions have a self score.
    Never normalize against the best hit: that makes unrelated noise score 1.
    """
    with contextlib.closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(fts5.FTS_DDL)
        conn.executemany("INSERT INTO lessons_fts(id, text) VALUES (?, ?)", texts.items())
        conn.execute("INSERT INTO lessons_fts(id, text) VALUES (?, ?)", ("query", query))
        forward = dict(fts5.search(conn, query))
        self_score = forward.get("query", 0.0)
        if self_score >= 0:
            return {}
        scores = {}
        for rid, score in forward.items():
            if rid == "query":
                continue
            reverse = dict(fts5.search(conn, texts[rid]))
            reverse_self = reverse.get(rid, 0.0)
            back = min(1.0, reverse.get("query", 0.0) / reverse_self) if reverse_self < 0 else 0.0
            scores[rid] = (min(1.0, score / self_score) + back) / 2
        return scores


def _semantic(home: Path, texts: dict[str, str], query: str, provider=FROM_ENV) -> tuple[dict[str, float], float | None, str]:
    if provider is None:
        return {}, None, "embedding disabled for this selection"
    path = index_path(home)
    if not path.is_file():
        return {}, None, "index not built; current ledger text searched lexically"
    try:
        # Do not call open_existing: it calls open(), creates schema/cache dirs.
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            row = conn.execute("SELECT value FROM meta WHERE key='model_id'").fetchone()
            model = row[0] if row else None
            threshold = COSINE_THRESHOLDS.get(model) if isinstance(model, str) else None
            if threshold is None:
                return {}, None, "index model has no measured cosine threshold"
            rows = conn.execute("SELECT id, text_hash, vector FROM lesson_vectors WHERE model_id=?", (model,)).fetchall()
        finally:
            conn.close()
        vectors = {rid: deserialize(blob) for rid, digest, blob in rows
                   if rid in texts and hashlib.sha256(texts[rid].encode()).hexdigest() == digest}
        if not vectors:
            return {}, threshold, "no current vectors for eligible lessons"
        if provider is FROM_ENV:
            provider, reason = load_provider()
            if provider is None:
                return {}, threshold, reason
        if provider.model_id != model:
            return {}, threshold, "embedding model differs from the index"
        query_vector = embed_documents(provider, [query], interactive=True)[0]
        scores = {rid: cosine(query_vector, v) for rid, v in vectors.items()
                  if len(v) == len(query_vector) and all(math.isfinite(x) for x in v)}
        note = "" if len(scores) == len(texts) else "partial current vectors; lexical fallback for other lessons"
        return scores, threshold, note
    except (sqlite3.Error, ValueError, OSError) as exc:
        return {}, None, f"index unavailable: {type(exc).__name__}; lexical fallback"
    except Exception as exc:
        return {}, None, embedding_failure_note(exc)


def select_lessons(home: Path, query: str, *, project: Path | None = None,
                   paths: list[str] | None = None, skills: list[str] | None = None,
                   exclude: list[str] | None = None, limit: int = 10,
                   provider: EmbedProvider | None = FROM_ENV) -> dict:
    """Read authoritative records; stale index rows cannot resurrect lessons."""
    if not query.strip() or limit < 0:
        raise ValueError("query must be nonempty and limit must be nonnegative")
    query = redact(query)[0]
    root = (project or Path.cwd()).expanduser().resolve()
    if project is not None and not root.is_dir():
        raise ValueError("project must be an existing directory")
    root = gitops.toplevel(root) or root
    project_key = capture_host_path(home, root).resolve() if project is not None else None
    selected_skills = set(skills or [])
    excluded = set(exclude or [])
    records: dict[str, tuple[Record, str, list[str]]] = {}
    unreadable: list[str] = []
    for bucket in discover_buckets(home):
        if bucket.scope == "skill" and bucket.name not in selected_skills:
            continue
        if bucket.scope == "project":
            recorded_path = bucket_project_path(bucket.path)
            if project_key is None or recorded_path is None or recorded_path.resolve() != project_key:
                continue
        for folder in ("pending", "resolved"):
            for path in sorted((bucket.path / folder).glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                    if record.id in excluded or not domain.is_canon_live(record):
                        continue
                    routing = record.routing or {}
                    destination = routing.get("destination")
                    if not isinstance(destination, str) or not destination:
                        continue
                    gates = routing.get("rules_paths") or []
                    if not isinstance(gates, list) or any(not isinstance(g, str) for g in gates):
                        raise ValueError("invalid rules_paths")
                    for gate in gates:
                        _compile_glob_pattern(gate)
                    records[record.id] = (record, bucket.name, [])
                except Exception:
                    unreadable.append(str(path.relative_to(home)))
    if records and limit:
        concrete_paths = task_paths(paths or [], root)
        for rid, (record, bucket, _) in list(records.items()):
            gates = (record.routing or {}).get("rules_paths") or []
            matches = [p for p in concrete_paths if any(_glob_match(p, g) for g in gates)]
            if gates and not matches:
                del records[rid]
            else:
                records[rid] = (record, bucket, matches)
    texts = {rid: lesson_text(r) for rid, (r, _, _) in records.items()}
    lexical = _lexical(texts, query) if texts and limit else {}
    semantic, threshold, note = _semantic(home, texts, query, provider) if texts and limit else ({}, None, "no eligible lessons" if not texts else "limit is zero")
    lexical_ids = sorted(lexical, key=lambda rid: (-lexical[rid], rid))
    semantic_ids = sorted(semantic, key=lambda rid: (-semantic[rid], rid))
    rankings = [lexical_ids, semantic_ids] if semantic else [lexical_ids]
    lessons = []
    for rid, rrf in rrf_fuse(rankings):
        lex, sem = lexical.get(rid, 0.0), semantic.get(rid)
        lex_ok = lex >= LEXICAL_THRESHOLD
        sem_ok = sem is not None and threshold is not None and sem >= threshold
        if not (lex_ok or sem_ok):
            continue
        record, bucket, matches = records[rid]
        why = (["semantic"] if sem_ok else []) + (["lexical"] if lex_ok else [])
        why += ["project scope" if record.scope == "project" else "skill scope" if record.scope.startswith("skill:") else "user scope"]
        if matches:
            why.append("path gate")
        lessons.append({"id": rid, "text": agent_text(record), "type": record.type,
                        "kind": record.kind, "scope": record.scope, "bucket": bucket,
                        "status": record.status, "routing": record.routing,
                        "score": {"value": sem if sem_ok else lex, "basis": "cosine" if sem_ok else "lexical",
                                  "rrf": rrf, "cosine": sem, "lexical": lex},
                        "why": why, "matched_paths": matches})
        if len(lessons) >= limit:
            break
    return {"command": "select", "mode": "hybrid" if semantic else "lexical-only", "note": note,
            "thresholds": {"cosine": threshold, "lexical": LEXICAL_THRESHOLD},
            "lessons": lessons, "unreadable": unreadable}


def dispatch(args) -> int:
    home = resolve_home()
    state = home_state(home)
    if state != "ok":
        print(home_state_message(state, home), file=sys.stderr)
        return EXIT_NO_HOME
    try:
        result = select_lessons(home, args.query, project=args.project, paths=args.path,
                                skills=args.skill, exclude=args.exclude, limit=args.limit,
                                provider=None if args.no_embed else FROM_ENV)
    except ValueError as exc:
        print(f"self-learn select: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True, default=str))
    else:
        print(f"self-learn select: {len(result['lessons'])} lesson(s) ({result['mode']})")
        if result["note"]:
            print(result["note"])
        for lesson in result["lessons"]:
            print(lesson["text"])
            print(f"  {', '.join(lesson['why'])}; {lesson['score']['basis']} {lesson['score']['value']:.4f}")
        for path in result["unreadable"]:
            print(f"  unreadable: {path}", file=sys.stderr)
    return 0
