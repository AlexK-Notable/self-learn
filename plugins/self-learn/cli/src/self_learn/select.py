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
import time
from pathlib import Path

from . import domain, gitops
from .compilers import _reference_block, entry_line, loaded_text_problem
from .hosts import HostsError, ancestors_of, capture_host_path, load_hosts
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
from .primitives import names, procs
from .records import Record
from .scan import redact


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("select", help="read-only lessons for a task; never kicks background work")
    p.epilog = "Task evidence is required. Retrieval context uses only caller text: at most 20 paths and 2048 UTF-8 bytes; glob expansion is gating only."
    p.add_argument("--query", required=True, help="task description")
    p.add_argument("--path", action="append", default=[], help="absolute or project-relative file/glob (repeatable); supplies task context; globs expand existing files")
    p.add_argument("--literal-path", action="append", default=[], help="literal file name, including brackets or planned files (repeatable)")
    p.add_argument("--project", type=Path, help="project directory and task context (includes its lessons plus ancestors and user lessons)")
    p.add_argument("--skill", action="append", default=[], help="also include this skill's lessons (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="ID")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--tier", choices=("confident", "all"), default="confident", help="all also returns lower-confidence possible matches")
    p.add_argument("--no-embed", action="store_true", help="lexical only; make no embedding request")
    p.add_argument("--json", action="store_true", help="one result object; stdout contains no prose")


PATH_SCAN_LIMIT = 10_000
PATH_SCAN_BYTES = 4_000_000


class PathScanError(ValueError):
    """Incomplete glob evidence; keep ungated selection available."""


def _remaining(deadline: float | None) -> float:
    remaining = gitops.GIT_LOCAL_TIMEOUT if deadline is None else deadline - time.monotonic()
    if remaining <= 0:
        raise PathScanError("path inventory time budget exhausted")
    return remaining


def _read_git(root: Path, args: list[str], *, byte_limit: int, deadline: float | None = None):
    # Read-only means no fsmonitor hook/daemon and no optional index refresh.
    return procs.run_bounded(
        ["git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false", *args],
        cwd=str(root), env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        timeout=_remaining(deadline), binary=True, max_output_bytes=byte_limit,
    )


def _git_toplevel(root: Path, notes: list[str] | None = None, *, deadline: float | None = None) -> Path | None:
    try:
        result = _read_git(root, ["rev-parse", "--show-toplevel"], byte_limit=PATH_SCAN_BYTES, deadline=deadline)
    except (OSError, procs.BoundedTimeout, procs.OutputLimitExceeded):
        if notes is not None:
            notes.append("Git unavailable; using filesystem project path")
        return None
    return Path(os.fsdecode(result.stdout).strip()) if result.returncode == 0 else None


def _git_files(root: Path, prefixes: set[str], budget: list[int], *, deadline: float):
    # Literal Git pathspecs keep brackets/colons in directory names literal.
    pathspecs = [":(literal)" + p + "/" for p in sorted(prefixes) if p]
    if "" in prefixes:
        pathspecs = []
    try:
        result = _read_git(root,
            ["ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *pathspecs],
            byte_limit=max(1, PATH_SCAN_BYTES - budget[1]), deadline=deadline)
    except procs.OutputLimitExceeded as exc:
        raise PathScanError("path glob inventory byte budget exhausted") from exc
    except procs.BoundedTimeout as exc:
        raise PathScanError("Git path inventory did not finish") from exc
    except OSError as exc:
        raise PathScanError("Git path inventory unavailable") from exc
    if result.returncode != 0:
        raise PathScanError("Git path inventory failed")
    budget[1] += len(result.stdout) + len(result.stderr)
    names = result.stdout.split(b"\0")
    if names and not names[-1]:
        names.pop()
    budget[0] += len(names)
    if budget[0] > PATH_SCAN_LIMIT or budget[1] > PATH_SCAN_BYTES:
        raise PathScanError("path glob scan budget exhausted")
    for name in names:
        yield os.fsdecode(name)


def task_paths(paths: list[str], root: Path, *, literal_paths: list[str] | None = None,
               notes: list[str] | None = None, deadline: float | None = None,
               budget: list[int] | None = None) -> list[str]:
    """Preserve caller spelling; glob witnesses respect Git ignore rules.

    A deterministic entry/byte budget bounds enumeration. Git also uses the
    shared local-process deadline; callers discard incomplete glob evidence rather than ungated hits.
    """
    deadline = deadline if deadline is not None else time.monotonic() + gitops.GIT_LOCAL_TIMEOUT
    budget = budget if budget is not None else [0, 0]
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
    anchors = [p for p in sorted(roots) if not any(parent in roots for parent in p.parents)]
    if _git_toplevel(root, deadline=deadline) is not None:
        jobs: dict[Path, set[str]] = {}
        for anchor in anchors:
            repo = _git_toplevel(anchor, deadline=deadline) or root
            prefix = anchor.relative_to(repo).as_posix()
            jobs.setdefault(repo, set()).add("" if prefix == "." else prefix)
        seen: set[Path] = set()
        while jobs:
            repo, prefixes = jobs.popitem()
            if repo in seen:
                continue
            seen.add(repo)
            for local_name in _git_files(repo, prefixes, budget, deadline=deadline):
                _remaining(deadline)
                path = repo / local_name
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    continue
                name = path.relative_to(root).as_posix()
                if path.is_dir() and (path / ".git").exists():
                    if any(globs_may_intersect(p, name + "/**") for p in raw_patterns):
                        jobs.setdefault(path, set()).add("")
                elif path.is_file() and any(p.match(name) for p in patterns):
                    out.add(name)
        return sorted(out)
    pending = anchors
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    _remaining(deadline)
                    if entry.name == ".git" or entry.is_symlink():
                        continue
                    budget[0] += 1
                    if budget[0] > PATH_SCAN_LIMIT:
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


def _absolute_task_paths(paths: list[str], root: Path, literals: list[str], notes: list[str]) -> list[Path]:
    deadline = time.monotonic() + gitops.GIT_LOCAL_TIMEOUT
    budget = [0, 0]
    groups: dict[Path, tuple[list[str], list[str]]] = {}
    user_root = names.user_home().resolve()
    for raw, literal in [(p, False) for p in paths] + [(p, True) for p in literals]:
        path = Path(raw).expanduser()
        base = root
        if path.is_absolute() and not path.is_relative_to(root):
            base = user_root if path.is_relative_to(user_root) else Path(path.anchor)
        group = groups.setdefault(base, ([], []))
        group[int(literal)].append(raw)
    out: set[Path] = set()
    for base, (patterns, explicit) in groups.items():
        out.update(base / name for name in task_paths(patterns, base, literal_paths=explicit, notes=notes, deadline=deadline, budget=budget))
    return sorted(out)


CONTEXT_PATH_LIMIT = 20
CONTEXT_BYTE_LIMIT = 2048


def _task_context(project: Path | None, paths: list[str], root: Path,
                  notes: list[str] | None = None) -> str:
    """Only caller-typed context; never filesystem expansion witnesses.

    Keep at most 20 path fields and 2048 UTF-8 bytes, including the project.
    Redaction and newline folding precede the byte cap. No canonicalized path
    or file inventory can disclose names the caller did not supply.
    """
    lines = ["Project: " + str(project)] if project is not None else []
    lines.extend("File: " + p for p in paths[:CONTEXT_PATH_LIMIT])
    context = redact("\n".join(" ".join(line.splitlines()) for line in lines))[0]
    encoded = context.encode()
    if len(paths) > CONTEXT_PATH_LIMIT or len(encoded) > CONTEXT_BYTE_LIMIT:
        if notes is not None:
            notes.append("task context truncated (20 paths / 2048 UTF-8 bytes)")
    return encoded[:CONTEXT_BYTE_LIMIT].decode("utf-8", errors="ignore")


def agent_text(record: Record) -> str:
    """Keep reference/hook sections whole, including their Context.

    Managed-line destinations already refuse multiline substance at routing.
    Older records can predate that gate: never truncate those either.
    """
    destination = (record.routing or {}).get("destination", "").split(":", 1)[0]
    if destination in {"reference", "hook"} or loaded_text_problem(record, "claude-md"):
        return _reference_block(record)
    return entry_line(record)


# Short lookups require their complete distinctive phrase. Natural-language
# tasks may contain a coherent pair of informative anchors amid extra prose.
LEXICAL_MIN_TERMS = 2
LEXICAL_QUERY_SPECIFICITY = .85
LEXICAL_LOOKUP_SPECIFICITY = .75
LEXICAL_STRONG_OVERLAP = .65
LEXICAL_ANCHOR_INFORMATION = 1.5
LEXICAL_WINDOW_TOKENS = 10
LEXICAL_CONTEXT_WEIGHT = .5
TASK_COSINE_THRESHOLDS = {"gemini-embedding-2@3072/i1": .70}
# Only measured models receive weaker tiers or incomplete-scope admissions.
TASK_TIER_PROFILES = {"gemini-embedding-2@3072/i1": {
    "strong": .75,
    "context_and_lexical": .675,
    "possible_lexical": .65,
    "possible_context_task": .60,
    "possible_context": .675,
    "possible_balanced": .65,
    "unnamed_skill": .725,
    "missing_user_path": .75,
}}


def _lexical(texts: dict[str, str], query: str, *, context: str = "") -> dict[str, float]:
    """Stable-corpus BM25 with local, gapped high-information evidence.

    Long task prose must not dilute a distinctive local phrase. Informative stems
    qualify only in bounded windows in BOTH the task and lesson; merely
    sharing scattered generic words or numeric fragments is insufficient.
    Explicit context is a separate, weaker field, never a substitute scope.
    """
    if not texts:
        return {}
    context_lines = context.splitlines()
    field_texts = [query, *(line.partition(": ")[2] if line.startswith(("Project: ", "File: "))
                           else line for line in context_lines)]
    with contextlib.closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(fts5.FTS_DDL)
        conn.executemany("INSERT INTO lessons_fts(id, text) VALUES (?, ?)",
                         [(rid, " ".join(tokenize(text))) for rid, text in texts.items()])
        conn.execute("CREATE VIRTUAL TABLE terms USING fts5vocab(lessons_fts, instance)")
        ids = dict(conn.execute("SELECT rowid, id FROM lessons_fts"))
        sequences: dict[str, list[str]] = {rid: [] for rid in texts}
        for term, rowid in conn.execute("SELECT term, doc FROM terms ORDER BY doc, offset"):
            sequences[ids[rowid]].append(term)
        conn.execute("CREATE VIRTUAL TABLE query_fts USING fts5(text, tokenize='porter unicode61')")
        conn.executemany("INSERT INTO query_fts(rowid, text) VALUES (?, ?)",
                         [(i, " ".join(tokenize(text))) for i, text in enumerate(field_texts, 1)])
        conn.execute("CREATE VIRTUAL TABLE query_terms USING fts5vocab(query_fts, instance)")
        fields = [list(row[0] for row in conn.execute(
            "SELECT term FROM query_terms WHERE doc=? ORDER BY offset", (i,))) for i in range(1, len(field_texts) + 1)]
    docs = {rid: Counter(seq) for rid, seq in sequences.items()}
    frequencies: Counter[str] = Counter()
    for terms in docs.values():
        frequencies.update(terms.keys())
    if not frequencies:
        return {}
    total = len(docs)
    avg_length = sum(sum(t.values()) for t in docs.values()) / total or 1
    vocabulary = set(frequencies).union(*map(set, fields))
    weights = {t: math.log1p((total - frequencies[t] + .5) / (frequencies[t] + .5))
               for t in vocabulary}
    peak = max(weights[t] for t in frequencies)

    def score(terms: Counter[str], wanted) -> float:
        norm = 1.2 * (.25 + .75 * sum(terms.values()) / avg_length)
        return sum(weights[t] * terms[t] * 2.2 / (terms[t] + norm)
                   for t in wanted if terms[t])

    def ordered_core(left: tuple[str, ...], right: tuple[str, ...]) -> frozenset[str]:
        # Weighted common subsequence: tolerate intervening words and regular
        # inflection without treating arbitrary topic-word permutations as a
        # shared phrase. Window positions still bound the original text span.
        row: list[tuple[float, tuple[str, ...]]] = [(0., ())] * (len(right) + 1)
        for term in left:
            new: list[tuple[float, tuple[str, ...]]] = [(0., ())]
            for j, other in enumerate(right):
                options = [row[j + 1], new[-1]]
                if term == other:
                    options.append((row[j][0] + weights[term], row[j][1] + (term,)))
                new.append(max(options))
            row = new
        return frozenset(row[-1][1])

    def anchors(sequence: list[str], other: list[str]) -> set[frozenset[str]]:
        # Only shared alphabetic stems count. Preserve their original positions:
        # removing nonmatching words must not collapse a long span into a phrase.
        overlap = {t for t in set(sequence) & set(other) if any(c.isalpha() for c in t)}
        if len(overlap) < LEXICAL_MIN_TERMS or sum(weights[t] for t in overlap) / peak < LEXICAL_ANCHOR_INFORMATION:
            return set()
        windows = [tuple(dict.fromkeys(t for t in other[i:i + LEXICAL_WINDOW_TOKENS] if t in overlap))
                   for i in range(len(other))]
        found: set[frozenset[str]] = set()
        for start in range(len(sequence)):
            local = tuple(dict.fromkeys(t for t in sequence[start:start + LEXICAL_WINDOW_TOKENS] if t in overlap))
            for window in windows:
                core = ordered_core(local, window)
                information = sorted(weights[t] for t in core)
                if (len(core) >= LEXICAL_MIN_TERMS
                        and sum(information) / peak >= LEXICAL_ANCHOR_INFORMATION
                        and sum(information[:-1]) / peak >= LEXICAL_LOOKUP_SPECIFICITY):
                    found.add(core)
        return found

    scores: dict[str, float] = {}
    for sequence, field_weight in zip(fields, [1.0] + [LEXICAL_CONTEXT_WEIGHT] * (len(fields) - 1)):
        terms = Counter(sequence)
        if not terms:
            continue
        query_self = score(terms, terms)
        specificity = sum(weights[t] for t in terms) / len(terms) / peak
        minimum = LEXICAL_LOOKUP_SPECIFICITY if len(terms) == 1 else LEXICAL_QUERY_SPECIFICITY
        for rid, document in docs.items():
            if field_weight < 1 and rid not in scores:
                continue  # Context cannot create task evidence.
            overlap = terms.keys() & document.keys()
            if len(overlap) < min(LEXICAL_MIN_TERMS, len(terms)):
                continue
            own = score(document, document)
            forward = min(1.0, score(document, terms) / query_self) if query_self else 0
            reverse = min(1.0, score(terms, document) / own) if own else 0
            value = (forward + reverse) / 2
            shared_anchors = anchors(sequence, sequences[rid])
            evidence = (len(overlap) == len(terms) and specificity >= minimum
                        if len(terms) <= 3 else bool(shared_anchors))
            if shared_anchors and (len(terms) > 3 or field_weight < 1):
                # Score the best supported local core, so unrelated task prose
                # cannot dilute evidence already present in both passages.
                for pair in shared_anchors:
                    core = Counter(sorted(pair))
                    core_self = score(core, core)
                    core_forward = min(1.0, score(document, core) / core_self)
                    core_reverse = min(1.0, score(core, document) / own) if own else 0
                    value = max(value, (core_forward + core_reverse) / 2)
            if evidence or value >= LEXICAL_STRONG_OVERLAP:
                scores[rid] = max(scores.get(rid, 0), value * field_weight)
    return scores


class SemanticScores(dict[str, float]):
    """Task-only scores, with separately measured bounded-context support."""
    def __init__(self, task: dict[str, float], context: dict[str, float], model_id: str | None = None):
        super().__init__(task)
        self.context = context
        self.model_id = model_id


def _semantic(home: Path, texts: dict[str, str], query: str, provider=FROM_ENV, *, context: str = "") -> tuple[dict[str, float], float | None, str]:
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
            threshold = TASK_COSINE_THRESHOLDS.get(model, COSINE_THRESHOLDS.get(model)) if isinstance(model, str) else None
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
        queries = [query] + ([query + "\nTask context:\n" + context] if context else [])
        query_vectors = embed_documents(provider, queries, interactive=True, query=True)
        def similarities(vector):
            return {rid: cosine(vector, v) for rid, v in vectors.items()
                    if len(v) == len(vector) and all(math.isfinite(x) for x in v)}
        scores = SemanticScores(similarities(query_vectors[0]),
                                similarities(query_vectors[1]) if context else {}, model)
        note = "" if len(scores) == len(texts) else "partial current vectors; lexical fallback for other lessons"
        return scores, threshold, note
    except (sqlite3.Error, ValueError, OSError) as exc:
        return {}, None, f"index unavailable: {type(exc).__name__}; lexical fallback"
    except Exception as exc:
        return {}, None, embedding_failure_note(exc)


def select_lessons(home: Path, query: str, *, project: Path | None = None,
                   paths: list[str] | None = None, literal_paths: list[str] | None = None,
                   skills: list[str] | None = None,
                   exclude: list[str] | None = None, limit: int = 10, tier: str = "confident",
                   provider: EmbedProvider | None = FROM_ENV) -> dict:
    """Read authoritative records; stale index rows cannot resurrect lessons."""
    if not query.strip() or limit < 0:
        raise ValueError("query must be nonempty and limit must be nonnegative")
    if tier not in {"confident", "all"}:
        raise ValueError("tier must be confident or all")
    query = redact(query)[0]
    root = (project or Path.cwd()).expanduser().resolve()
    if project is not None and not root.is_dir():
        raise ValueError("project must be an existing directory")
    path_notes: list[str] = []
    root = _git_toplevel(root, path_notes) or root
    project_key = capture_host_path(home, root).resolve() if project is not None else None
    try:
        ancestor_paths = set(ancestors_of(load_hosts(home), project_key)) if project_key else set()
    except HostsError:
        ancestor_paths = set()
        path_notes.append("hosts.yaml unreadable; ancestor lessons omitted")
    selected_skills = set(skills or [])
    excluded = set(exclude or [])
    records: dict[str, tuple[Record, str, list[str], str, Path | None]] = {}
    texts: dict[str, str] = {}
    unreadable: list[str] = []
    relaxed: dict[str, list[str]] = {}
    for bucket in discover_buckets(home):
        recorded_path = bucket_project_path(bucket.path) if bucket.scope == "project" else None
        recorded_path = recorded_path.resolve() if recorded_path else None
        relation = ("ancestor-project" if recorded_path in ancestor_paths else bucket.scope)
        bucket_eligible = (bucket.scope == "user"
                           or (bucket.scope == "skill" and bucket.name in selected_skills)
                           or (bucket.scope == "project" and project_key is not None
                               and recorded_path in {project_key, *ancestor_paths}))
        unnamed_skill = (tier == "all" and not selected_skills and bucket.scope == "skill")
        for folder in ("pending", "resolved"):
            for path in sorted((bucket.path / folder).glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                    # Stable corpus: exclusions, scope and gates never change IDF.
                    texts[record.id] = lesson_text(record)
                    if not (bucket_eligible or unnamed_skill) or record.id in excluded or not domain.is_canon_live(record):
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
                    if unnamed_skill:
                        relaxed[record.id] = ["skill not requested"]
                except Exception:
                    unreadable.append(str(path.relative_to(home)))
    from .verbs import DEFAULT_USER_CLAUDE_MD, _user_reachability_roots
    user_roots = _user_reachability_roots(home, names.user_claude_file(DEFAULT_USER_CLAUDE_MD))
    concrete_paths: list[Path] = []
    if records and limit:
        try:
            concrete_paths = _absolute_task_paths(paths or [], root, literal_paths or [], path_notes)
        except PathScanError as exc:
            concrete_paths = []
            path_notes.append(f"{exc}; path-gated lessons omitted")
        for rid, (record, bucket, _, relation, recorded_path) in list(records.items()):
            gates = (record.routing or {}).get("rules_paths") or []
            gate_paths = []
            gate_roots = user_roots if record.scope == "user" else (recorded_path or root,)
            for path in concrete_paths:
                canonical = (project_key / path.relative_to(root)
                             if record.scope == "project" and project_key is not None and path.is_relative_to(root)
                             else path)
                for gate_root in gate_roots:
                    if canonical.is_relative_to(gate_root):
                        gate_paths.append(canonical.relative_to(gate_root).as_posix())
            matches = [p for p in gate_paths if any(_glob_match(p, g) for g in gates)]
            if gates and not matches:
                if tier == "all" and record.scope == "user" and not paths and not literal_paths:
                    relaxed.setdefault(rid, []).append("path not supplied")
                else:
                    del records[rid]
            else:
                records[rid] = (record, bucket, matches, relation, recorded_path)
    context = _task_context(project, [*(paths or []), *(literal_paths or [])], root, path_notes)
    lexical = {rid: value for rid, value in _lexical(texts, query, context=context).items() if rid in records} if records and limit else {}
    eligible_texts = {rid: texts[rid] for rid in records}
    semantic, threshold, note = _semantic(home, eligible_texts, query, provider, context=context) if records and limit else ({}, None, "no eligible lessons" if not records else "limit is zero")
    model_id = getattr(semantic, "model_id", None)
    profile = TASK_TIER_PROFILES.get(model_id) if isinstance(model_id, str) else None
    contextual = getattr(semantic, "context", {})
    note = "; ".join([note, *path_notes]).strip("; ")
    lexical_ids = sorted(lexical, key=lambda rid: (-lexical[rid], rid))
    semantic_ids = sorted(semantic, key=lambda rid: (-semantic[rid], rid))
    rankings = [lexical_ids, semantic_ids] if semantic else [lexical_ids]
    ranked = rrf_fuse(rankings)
    # Preserve default ranks, including its unqualified candidates. All-only
    # scope exceptions must not change confident scores or limited membership.
    confident_rrf = dict(rrf_fuse([[rid for rid in ranking if rid not in relaxed]
                                  for ranking in rankings])) if relaxed else dict(ranked)
    lessons = []
    for rid, rrf in ranked:
        lex, sem = lexical.get(rid, 0.0), semantic.get(rid)
        lex_ok = lex >= LEXICAL_THRESHOLD
        sem_ok = sem is not None and threshold is not None and sem >= threshold
        context_score = contextual.get(rid)
        context_evidence = False
        confident = sem_ok if sem is not None else lex_ok
        possible = False
        if sem is not None and threshold is not None and profile is not None:
            context_evidence = (context_score is not None and context_score >= threshold
                                and sem >= profile["context_and_lexical"] and lex_ok)
            confident = sem >= profile["strong"] or (sem_ok and lex_ok) or context_evidence
            gate_supported = bool(records[rid][2])
            possible_context = (gate_supported and context_score is not None and (
                (sem >= profile["possible_context_task"] and context_score >= profile["possible_context"])
                or min(sem, context_score) >= profile["possible_balanced"]))
            possible = sem_ok or (sem >= profile["possible_lexical"] and lex_ok) or possible_context
            context_evidence |= possible_context
        if rid in relaxed:
            confident = False
            key = "unnamed_skill" if "skill not requested" in relaxed[rid] else "missing_user_path"
            possible = (sem is not None and profile is not None and (
                sem >= profile[key] or (key == "missing_user_path" and sem_ok and lex_ok)))
        if not confident and not (tier == "all" and possible):
            continue
        record, bucket, matches, relation, _ = records[rid]
        if confident:
            rrf = confident_rrf[rid]
        why = (["current vector"] if sem is not None else [])
        why += (["semantic floor"] if sem_ok else []) + (["lexical"] if lex_ok else [])
        why += ["ancestor project scope" if relation == "ancestor-project" else
                "project scope" if record.scope == "project" else "skill scope" if record.scope.startswith("skill:") else "user scope"]
        if matches:
            why.append("path gate")
        if context_evidence:
            why.append("task/context corroboration")
        why.extend(relaxed.get(rid, []))
        lessons.append({"id": rid, "text": agent_text(record), "type": record.type,
                        "kind": record.kind, "confidence": "confident" if confident else "possible", "scope": record.scope, "scope_relation": relation, "bucket": bucket,
                        "status": record.status, "routing": record.routing,
                        "score": {"value": sem if sem is not None else lex, "basis": "cosine" if sem is not None else "lexical",
                                  "rrf": rrf, "cosine": sem, "context_cosine": getattr(semantic, "context", {}).get(rid), "lexical": lex},
                        "why": why, "matched_paths": matches})
    lessons.sort(key=lambda lesson: (lesson["confidence"] != "confident", -lesson["score"]["rrf"], lesson["id"]))
    lessons = lessons[:limit]
    return {"command": "select", "tier": tier, "mode": "hybrid" if semantic else "lexical-only", "note": note,
            "thresholds": {"cosine": threshold, "confidence": dict(profile) if profile else None, "lexical": LEXICAL_THRESHOLD, "lexical_min_terms": LEXICAL_MIN_TERMS,
                           "lexical_anchor_information": LEXICAL_ANCHOR_INFORMATION,
                           "lexical_window_tokens": LEXICAL_WINDOW_TOKENS,
                           "lexical_context_weight": LEXICAL_CONTEXT_WEIGHT,
                           "lexical_query_specificity": LEXICAL_QUERY_SPECIFICITY,
                           "lexical_lookup_specificity": LEXICAL_LOOKUP_SPECIFICITY,
                           "lexical_strong_overlap": LEXICAL_STRONG_OVERLAP},
            "lessons": lessons, "unreadable": unreadable}


def dispatch(args) -> int:
    home = resolve_home()
    try:
        state = home_state(home)
    except OSError:
        print("self-learn select: Git unavailable; cannot validate ledger home", file=sys.stderr)
        return EXIT_NO_HOME
    if state != "ok":
        print(home_state_message(state, home), file=sys.stderr)
        return EXIT_NO_HOME
    try:
        result = select_lessons(home, args.query, project=args.project, paths=args.path, literal_paths=args.literal_path,
                                skills=args.skill, exclude=args.exclude, limit=args.limit, tier=args.tier,
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
            print(f"  {lesson['confidence']}; {', '.join(lesson['why'])}; {lesson['score']['basis']} {lesson['score']['value']:.4f}")
        for path in result["unreadable"]:
            print(f"  unreadable: {path}", file=sys.stderr)
    return 0
