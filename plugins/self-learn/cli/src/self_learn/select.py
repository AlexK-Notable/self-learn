"""Task-scoped lesson selection (S-161); no persistent writes or watchdogs."""
from __future__ import annotations

import argparse
import contextlib
from collections import Counter
import glob
import hashlib
import json
import math
import os
import sqlite3
import sys
from pathlib import Path

from . import domain, gitops
from .compilers import _reference_block, entry_line, loaded_text_problem
from .hosts import ancestors_of, capture_host_path, load_hosts
from .index import fts5
from .index.protocol import EmbedProvider
from .index.related import COSINE_THRESHOLDS, LEXICAL_THRESHOLD
from .index.rrf import rrf_fuse
from .index.tokenize import tokenize
from .index.store import FROM_ENV, index_path, lesson_text
from .index.textquery import embed_documents, embedding_failure_note
from .index.registry import load_provider
from .index.vectors import cosine, deserialize
from .ledger import EXIT_NO_HOME, discover_buckets, home_state, home_state_message, resolve_home
from .ledger_ops import ProposalError, _compile_glob_pattern, _glob_match, bucket_project_path, globs_may_intersect
from .primitives import procs
from .records import Record
from .scan import redact


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("select", help="read-only lessons for a task; never kicks background work")
    p.add_argument("--query", required=True, help="task description")
    p.add_argument("--path", action="append", default=[], help="file or glob, relative to project (repeatable); globs expand existing files")
    p.add_argument("--literal-path", action="append", default=[], help="literal file name, including brackets or planned files (repeatable)")
    p.add_argument("--project", type=Path, help="project directory (includes its lessons plus user lessons)")
    p.add_argument("--skill", action="append", default=[], help="also include this skill's lessons (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="ID")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--no-embed", action="store_true", help="lexical only; make no embedding request")
    p.add_argument("--json", action="store_true", help="one result object; stdout contains no prose")


PATH_SCAN_LIMIT = 10_000
PATH_SCAN_BYTES = 4_000_000


class PathScanError(ValueError):
    """Incomplete glob evidence; keep ungated selection available."""


def _git_files(root: Path):
    # Git owns ignore semantics; the shared runner bounds bytes and lifetime
    # and reaps the entire child process group on either limit.
    try:
        result = procs.run_bounded(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=str(root), timeout=gitops.GIT_LOCAL_TIMEOUT, binary=True,
            max_output_bytes=PATH_SCAN_BYTES,
        )
    except procs.OutputLimitExceeded as exc:
        raise PathScanError("path glob inventory byte budget exhausted") from exc
    except procs.BoundedTimeout as exc:
        raise PathScanError("Git path inventory did not finish") from exc
    if result.returncode != 0:
        raise PathScanError("Git path inventory failed")
    names = result.stdout.split(b"\0")
    if names and not names[-1]:
        names.pop()
    if len(names) > PATH_SCAN_LIMIT:
        raise PathScanError("path glob scan budget exhausted")
    for name in names:
        yield os.fsdecode(name)


def task_paths(paths: list[str], root: Path, *, literal_paths: list[str] | None = None,
               notes: list[str] | None = None) -> list[str]:
    """Preserve caller spelling; glob witnesses respect Git ignore rules.

    A deterministic entry/byte budget bounds enumeration. Git also uses the
    shared local-process deadline; callers discard incomplete glob evidence rather than ungated hits.
    """
    out: set[str] = set()
    patterns = []
    raw_patterns: list[str] = []
    roots: set[Path] = set()
    for raw, explicit in [(p, False) for p in paths] + [(p, True) for p in literal_paths or []]:
        absolute = Path(raw).expanduser()
        if not absolute.is_absolute():
            absolute = root / absolute
        # Normalize .. without following symlinks: gates match the name the
        # agent edits, not the target's spelling. Resolve only for containment.
        absolute = Path(os.path.abspath(absolute))
        relative = absolute.relative_to(root).as_posix()
        if not absolute.resolve().is_relative_to(root):
            if notes is not None:
                notes.append(f"path outside project ignored: {relative}")
            continue
        if explicit or absolute.is_file() or not glob.has_magic(relative):
            out.add(relative)
            continue
        try:
            pattern = _compile_glob_pattern(relative)
        except ProposalError as exc:
            raise ValueError(str(exc)) from exc
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
    if not patterns:
        return sorted(out)
    if gitops.toplevel(root) is not None:
        for name in _git_files(root):
            path = root / name
            if (not path.is_symlink() and path.is_file()
                    and path.resolve().is_relative_to(root)
                    and any(p.match(name) for p in patterns)):
                out.add(name)
        return sorted(out)
    pending = [p for p in sorted(roots) if not any(parent in roots for parent in p.parents)]
    visited = 0
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name == ".git" or entry.is_symlink():
                        continue
                    visited += 1
                    if visited > PATH_SCAN_LIMIT:
                        raise PathScanError("path glob scan budget exhausted")
                    name = Path(entry.path).relative_to(root).as_posix()
                    if entry.is_dir(follow_symlinks=False):
                        depth = len(name.split("/"))
                        if any(("**" in p.split("/") or depth < len(p.split("/")))
                               and globs_may_intersect(p, name + "/**") for p in raw_patterns):
                            pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and any(p.match(name) for p in patterns):
                        out.add(name)
        except OSError as exc:
            raise PathScanError(f"path glob scan failed: {type(exc).__name__}") from exc
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


# Generic task vocabulary may rank a hit, but cannot corroborate its topic.
# Stemmed by the same FTS tokenizer below; calibrated in test_provider_review.
_TASK_FILLER = "add after before check config configuration during file launch run test unit while write"
LEXICAL_MIN_TERMS = 2


def _lexical(texts: dict[str, str], query: str) -> dict[str, float]:
    """Symmetric BM25 ratios over a stable, query-free corpus.

    Porter/unicode61 supplies terms. Positive IDF log(1 + odds) avoids FTS5's
    near-zero clamp for ubiquitous terms in small ledgers. Query self weights
    use the corpus statistics without inserting the query into that corpus.
    """
    if not texts:
        return {}
    with contextlib.closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(fts5.FTS_DDL)
        conn.executemany("INSERT INTO lessons_fts(id, text) VALUES (?, ?)",
                         [(rid, " ".join(tokenize(text))) for rid, text in texts.items()])
        conn.execute("CREATE VIRTUAL TABLE terms USING fts5vocab(lessons_fts, instance)")
        ids = dict(conn.execute("SELECT rowid, id FROM lessons_fts"))
        docs: dict[str, Counter[str]] = {rid: Counter() for rid in texts}
        for term, rowid in conn.execute("SELECT term, doc FROM terms"):
            docs[ids[rowid]][term] += 1
        # A separate table tokenizes the query/fillers, never enters doc stats.
        conn.execute("CREATE VIRTUAL TABLE query_fts USING fts5(text, tokenize='porter unicode61')")
        conn.execute("INSERT INTO query_fts(rowid, text) VALUES (1, ?)", (" ".join(tokenize(query)),))
        conn.execute("INSERT INTO query_fts(rowid, text) VALUES (2, ?)", (_TASK_FILLER,))
        conn.execute("CREATE VIRTUAL TABLE query_terms USING fts5vocab(query_fts, instance)")
        query_terms = Counter(row[0] for row in conn.execute("SELECT term FROM query_terms WHERE doc=1"))
        fillers = {row[0] for row in conn.execute("SELECT term FROM query_terms WHERE doc=2")}
    corroborating = set(query_terms) - fillers
    if len(corroborating) < LEXICAL_MIN_TERMS:
        return {}
    frequencies: Counter[str] = Counter()
    for terms in docs.values():
        frequencies.update(terms.keys())
    total = len(docs)
    avg_length = sum(sum(t.values()) for t in docs.values()) / total or 1
    weights = {t: math.log1p((total - frequencies[t] + .5) / (frequencies[t] + .5))
               for t in set(frequencies) | set(query_terms)}

    def score(terms: Counter[str], wanted) -> float:
        norm = 1.2 * (.25 + .75 * sum(terms.values()) / avg_length)
        return sum(weights[t] * terms[t] * 2.2 / (terms[t] + norm)
                   for t in wanted if terms[t])

    query_self = score(query_terms, query_terms)
    scores = {}
    for rid, terms in docs.items():
        if len(corroborating & terms.keys()) < LEXICAL_MIN_TERMS:
            continue
        own = score(terms, terms)
        forward = min(1.0, score(terms, query_terms) / query_self) if query_self else 0
        reverse = min(1.0, score(query_terms, terms) / own) if own else 0
        scores[rid] = (forward + reverse) / 2
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
                   paths: list[str] | None = None, literal_paths: list[str] | None = None,
                   skills: list[str] | None = None,
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
    ancestor_paths = set(ancestors_of(load_hosts(home), project_key)) if project_key else set()
    selected_skills = set(skills or [])
    excluded = set(exclude or [])
    records: dict[str, tuple[Record, str, list[str], str, Path | None]] = {}
    texts: dict[str, str] = {}
    unreadable: list[str] = []
    for bucket in discover_buckets(home):
        recorded_path = bucket_project_path(bucket.path) if bucket.scope == "project" else None
        recorded_path = recorded_path.resolve() if recorded_path else None
        relation = ("ancestor-project" if recorded_path in ancestor_paths else bucket.scope)
        bucket_eligible = (bucket.scope == "user"
                           or (bucket.scope == "skill" and bucket.name in selected_skills)
                           or (bucket.scope == "project" and project_key is not None
                               and recorded_path in {project_key, *ancestor_paths}))
        for folder in ("pending", "resolved"):
            for path in sorted((bucket.path / folder).glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                    # Stable corpus: exclusions, scope and gates never change IDF.
                    texts[record.id] = lesson_text(record)
                    if not bucket_eligible or record.id in excluded or not domain.is_canon_live(record):
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
                    records[record.id] = (record, bucket.name, [], relation, recorded_path)
                except Exception:
                    unreadable.append(str(path.relative_to(home)))
    path_notes: list[str] = []
    if records and limit:
        try:
            concrete_paths = task_paths(paths or [], root, literal_paths=literal_paths, notes=path_notes)
        except PathScanError as exc:
            concrete_paths = []
            path_notes.append(f"{exc}; path-gated lessons omitted")
        for rid, (record, bucket, _, relation, recorded_path) in list(records.items()):
            gates = (record.routing or {}).get("rules_paths") or []
            gate_paths = concrete_paths
            if relation == "ancestor-project" and project_key is not None and recorded_path is not None:
                prefix = project_key.relative_to(recorded_path)
                gate_paths = [(prefix / p).as_posix() for p in concrete_paths]
            matches = [p for p in gate_paths if any(_glob_match(p, g) for g in gates)]
            if gates and not matches:
                del records[rid]
            else:
                records[rid] = (record, bucket, matches, relation, recorded_path)
    lexical = {rid: value for rid, value in _lexical(texts, query).items() if rid in records} if records and limit else {}
    eligible_texts = {rid: texts[rid] for rid in records}
    semantic, threshold, note = _semantic(home, eligible_texts, query, provider) if records and limit else ({}, None, "no eligible lessons" if not records else "limit is zero")
    note = "; ".join([note, *path_notes]).strip("; ")
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
        record, bucket, matches, relation, _ = records[rid]
        why = (["semantic"] if sem_ok else []) + (["lexical"] if lex_ok else [])
        why += ["ancestor project scope" if relation == "ancestor-project" else
                "project scope" if record.scope == "project" else "skill scope" if record.scope.startswith("skill:") else "user scope"]
        if matches:
            why.append("path gate")
        lessons.append({"id": rid, "text": agent_text(record), "type": record.type,
                        "kind": record.kind, "scope": record.scope, "scope_relation": relation, "bucket": bucket,
                        "status": record.status, "routing": record.routing,
                        "score": {"value": sem if sem_ok else lex, "basis": "cosine" if sem_ok else "lexical",
                                  "rrf": rrf, "cosine": sem, "lexical": lex},
                        "why": why, "matched_paths": matches})
        if len(lessons) >= limit:
            break
    return {"command": "select", "mode": "hybrid" if semantic else "lexical-only", "note": note,
            "thresholds": {"cosine": threshold, "lexical": LEXICAL_THRESHOLD, "lexical_min_terms": LEXICAL_MIN_TERMS},
            "lessons": lessons, "unreadable": unreadable}


def dispatch(args) -> int:
    home = resolve_home()
    state = home_state(home)
    if state != "ok":
        print(home_state_message(state, home), file=sys.stderr)
        return EXIT_NO_HOME
    try:
        result = select_lessons(home, args.query, project=args.project, paths=args.path, literal_paths=args.literal_path,
                                skills=args.skill, exclude=args.exclude, limit=args.limit,
                                provider=None if args.no_embed else FROM_ENV)
    except ValueError as exc:
        print(f"self-learn select: {exc}", file=sys.stderr)
        from .cli import EXIT_USAGE
        return EXIT_USAGE
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
