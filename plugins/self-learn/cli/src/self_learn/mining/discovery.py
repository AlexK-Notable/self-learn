"""Finding Claude Code's session transcripts on native Windows.

Claude Code keeps a session's transcript at
``<claude dir>/projects/<folder>/<session id>.jsonl``, where ``<folder>`` is
named after the session's working directory. On Linux the rule that names it
is known and self-learn relies on it; on Windows it is not documented (drive
letters, backslashes), and two different working directories can share one
folder name. So on Windows nothing here trusts a folder name:

- every ordinary folder of the projects directory is enumerated, and a
  folder or file that is a link (symbolic link, junction or mount point, app
  execution alias: :func:`fsops.is_link`) is left out, so a reader never
  leaves the tree it was given; the projects directory itself is followed
  as configured, and nothing above it is read;
- a file counts as the transcript of session ``S`` only when one of its rows
  records ``"sessionId": S`` (:func:`proof`);
- a working directory read from a transcript is compared with any other
  path through :func:`names.registration_key` of the resolved path, the
  comparison registered project paths use (``hosts.is_project_host``), so
  case, slash direction, a trailing separator and a ``\\\\?\\`` prefix make
  no difference.

Every function here is called only when ``os.name == "nt"``; Linux keeps its
own discovery unchanged. Read-only: nothing here writes anywhere.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .. import transcript_lines
from ..primitives import fsops, names

__all__ = [
    "backfill_files",
    "family_key",
    "find_session",
    "in_project_scope",
    "later_session_files",
    "named_session_files",
    "ordinary_below",
    "place_key",
    "project_folders",
    "proof",
    "read_proof",
    "same_place",
    "session_files",
    "subagent_files",
    "transcripts_root",
    "under",
]

#: Claude Code's own worktree placement, ``<repo>/.claude/worktrees/<name>``,
#: as :func:`names.registration_key` spells it (lower case).
_WORKTREES = (".claude", "worktrees")


def _ordinary(path: Path) -> bool:
    """True when ``path`` is not a link. A path that cannot be examined is
    treated as a link: it is left out, never followed."""
    try:
        return not fsops.is_link(path)
    except OSError:
        return False


def _plain(spelling: str) -> str:
    """``spelling`` without an extended-length prefix: ``\\\\?\\UNC\\`` becomes
    ``\\\\``, ``\\\\?\\`` is dropped (either case)."""
    if spelling[:8].upper() == "\\\\?\\UNC\\":
        return "\\\\" + spelling[8:]
    if spelling.startswith("\\\\?\\"):
        return spelling[4:]
    return spelling


def transcripts_root(raw: str, source: str, env: Mapping[str, str] | None = None) -> Path:
    """The projects directory the miner scans. The built-in default (the
    literal ``~/.claude/projects``) becomes ``projects`` under
    :func:`names.claude_root` with ``use="transcripts"``, which honours
    ``SELF_LEARN_CLAUDE_DIR`` and ``CLAUDE_CONFIG_DIR``; a configured value is
    used as given. Either way the result is resolved, without an
    extended-length prefix, so the cursor file's keys keep one spelling
    however the directory was written."""
    if source == "default":
        root = names.claude_root(use="transcripts", env=env) / "projects"
    else:
        root = Path(raw).expanduser()
    root = Path(_plain(str(root)))
    try:
        return Path(_plain(str(root.resolve())))
    except OSError:
        return root


def project_folders(root: Path) -> list[Path]:
    """Every folder directly inside ``root`` that is not a link, sorted."""
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    return [p for p in entries if _ordinary(p) and p.is_dir()]


def session_files(root: Path) -> list[Path]:
    """The files ``sorted(root.glob("*/*.jsonl"))`` lists, without linked
    folders and without linked files."""
    out: list[Path] = []
    for folder in project_folders(root):
        try:
            children = list(folder.glob("*.jsonl"))
        except OSError:
            continue
        out.extend(p for p in children if _ordinary(p) and p.is_file())
    return sorted(out)


def named_session_files(root: Path, session_id: str) -> list[Path]:
    """Each ordinary ``<folder>/<session id>.jsonl`` whose rows record that
    session, probed folder by folder (Claude Code names a transcript file
    after its session id), never by listing every file."""
    name = f"{session_id}.jsonl"
    found: list[Path] = []
    for folder in project_folders(root):
        candidate = folder / name
        try:
            if _ordinary(candidate) and candidate.is_file() and read_proof(candidate, session_id)[0]:
                found.append(candidate)
        except OSError:
            continue
    return found


def ordinary_below(base: Path, path: Path) -> bool:
    """True when ``path`` lies lexically inside ``base`` and no entry from
    just below ``base`` down to ``path`` is a link. A ``.`` or ``..``
    segment is refused, so nothing at or above ``base`` is examined."""
    try:
        rel = path.relative_to(base)
    except ValueError:
        return False
    if not rel.parts:
        return False
    current = base
    for part in rel.parts:
        if part in (".", ".."):
            return False
        current = current / part
        if not _ordinary(current):
            return False
    return True


def subagent_files(folder: Path, session_id: str) -> list[Path]:
    """The ``agent-*.jsonl`` logs of a session whose transcript sits in
    ``folder``: checked for links from ``folder`` down BEFORE the
    ``<session id>/subagents`` folder is listed or any entry is examined."""
    sub = folder / session_id / "subagents"
    try:
        if not ordinary_below(folder, sub) or not sub.is_dir():
            return []
        children = list(sub.glob("agent-*.jsonl"))
    except OSError:
        return []
    return sorted(p for p in children if _ordinary(p) and p.is_file())


def proof(rows: Iterable[str], session_id: str) -> tuple[bool, str | None]:
    """Whether a row records ``session_id`` as its session, and the first
    working directory a row of that session records. A row that does not
    parse (a torn tail still being written, a damaged or absurdly nested
    line) proves nothing."""
    proven = False
    for raw in rows:
        if '"sessionId"' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        if not isinstance(entry, dict) or entry.get("sessionId") != session_id:
            continue
        proven = True
        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd:
            return True, cwd
    return proven, None


def read_proof(path: Path, session_id: str | None = None) -> tuple[bool, str | None]:
    """:func:`proof` over the file's rows, for the session its name gives
    unless ``session_id`` says otherwise. Read as UTF-8, whatever the
    system's code page; a byte that is not UTF-8 is replaced, never fatal."""
    try:
        return proof(transcript_lines.iter_file(path, errors="replace"), session_id or path.stem)
    except OSError:
        return False, None


def place_key(path: Path | str | None) -> str | None:
    """The spelling registered project paths are compared by
    (:func:`names.registration_key`, which resolves the path itself), without
    an extended-length prefix; None for a path that has none. A path that is
    not absolute (``.``, ``src``, ``C:sub``, ``\\nonexistent``) names no place:
    it would otherwise resolve against self-learn's own current folder."""
    if not path:
        return None
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            return None
        return _plain(names.registration_key(candidate))
    except (OSError, ValueError):
        return None


def same_place(a: Path | str, b: Path | str) -> bool:
    key = place_key(a)
    return key is not None and key == place_key(b)


def under(path: Path | str, root: Path | str) -> bool:
    """True when ``path`` is ``root`` or lies inside it."""
    inner, outer = place_key(path), place_key(root)
    return inner is not None and outer is not None and Path(inner).is_relative_to(Path(outer))


def _maybe_own(cwd_key: str | None, own_key: str) -> bool:
    """Whether a session may be self-learn's own: its recorded working
    directory lies under ``own_key``, or either is unknown (fail closed: a
    session that cannot be placed is never taken for someone else's)."""
    return cwd_key is None or not own_key or Path(cwd_key).is_relative_to(Path(own_key))


def _family_of_key(key: str | None) -> str | None:
    if key is None:
        return None
    parts = Path(key).parts
    for i in range(1, len(parts) - len(_WORKTREES)):
        if parts[i : i + len(_WORKTREES)] == _WORKTREES:
            return str(Path(*parts[:i]))
    return key


def family_key(cwd: Path | str | None) -> str | None:
    """The repository a working directory belongs to: the directory itself,
    or, inside ``<repo>/.claude/worktrees/<name>``, the repository (the
    outermost such segment, as the Linux folder-name rule takes the first)."""
    return _family_of_key(place_key(cwd))


def find_session(projects: Path, session_id: str, cwd: Path | str | None) -> Path | None:
    """The top-level transcript of ``session_id``: a ``<session id>.jsonl``
    in an ordinary folder whose rows record that session and, when ``cwd`` is
    given, a working directory that is the same place. Of several, the
    largest."""
    name = f"{session_id}.jsonl"
    found: list[tuple[int, str, Path]] = []
    for folder in project_folders(projects):
        candidate = folder / name
        try:
            if not _ordinary(candidate) or not candidate.is_file():
                continue
            proven, recorded = read_proof(candidate, session_id)
            if not proven:
                continue
            if cwd is not None and (recorded is None or not same_place(recorded, cwd)):
                continue
            found.append((candidate.stat().st_size, str(candidate), candidate))
        except OSError:
            continue
    if not found:
        return None
    return max(found)[2]


def backfill_files(root: Path, *, cutoff: float, skipped: Iterable[str], own_key: str,
                   session_re: re.Pattern[str]) -> list[tuple[float, Path]]:
    """``mine backfill-tasks``' candidates: each proven session file changed
    since ``cutoff``, not skipped, whose recorded working directory is known
    and not under ``own_key`` (self-learn's own sessions run under its cache
    root; a session that cannot be placed is left out)."""
    listed = set(skipped)
    found: list[tuple[float, Path]] = []
    for f in session_files(root):
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff or not session_re.match(f.stem) or f.stem in listed:
            continue
        proven, cwd = read_proof(f)
        if not proven or _maybe_own(place_key(cwd), own_key):
            continue
        found.append((mtime, f))
    return found


#: What :func:`later_session_files` learnt about a file, by ``(path,
#: mtime_ns, size)``: ``(proven, place key of its cwd, family key)``. A
#: changed file has a new key; the cache is emptied when it grows past
#: :data:`_FACTS_MAX` entries.
_FACTS: dict[tuple[str, int, int], tuple[bool, str | None, str | None]] = {}
_FACTS_MAX = 4096


def _facts(f: Path, st: Any) -> tuple[bool, str | None, str | None]:
    key = (str(f), st.st_mtime_ns, st.st_size)
    hit = _FACTS.get(key)
    if hit is None:
        proven, cwd = read_proof(f)
        cwd_key = place_key(cwd)
        hit = (proven, cwd_key, _family_of_key(cwd_key))
        if len(_FACTS) >= _FACTS_MAX:
            _FACTS.clear()
        _FACTS[key] = hit
    return hit


def later_session_files(root: Path, item: Mapping[str, Any], *, after_epoch: float,
                        all_folders: bool, own_key: str) -> list[Path]:
    """The files the unfinished-work check searches for an item: sessions of
    the item's repository (its worktrees included), judged by each file's
    recorded working directory, never by its folder; with ``all_folders``,
    every session that is surely not self-learn's own (under ``own_key``),
    the item's own file always included. Unchanged files are read once per
    process (:data:`_FACTS`)."""
    own = Path(str(item.get("transcript") or ""))
    item_cwd = item.get("cwd")
    if (not isinstance(item_cwd, str) or not item_cwd) and own.name and ordinary_below(root, own):
        _proven, item_cwd = read_proof(own, str(item.get("session") or "") or None)
    family = family_key(item_cwd if isinstance(item_cwd, str) else None)
    files: list[Path] = []
    for f in session_files(root):
        try:
            st = f.stat()
        except OSError:
            continue
        if st.st_mtime < after_epoch - 60:
            continue
        proven, cwd_key, file_family = _facts(f, st)
        if not proven:
            continue
        mine = f == own or (family is not None and file_family == family)
        if not mine and (not all_folders or _maybe_own(cwd_key, own_key)):
            continue
        files.append(f)
    return files


def in_project_scope(cwd: Path, paths: Iterable[Path]) -> bool:
    """A project bucket's rule applies to a session whose working directory
    lies in one of the bucket's registered paths (or when none is
    registered). A working directory that names no place is in no project."""
    paths = list(paths)
    return not paths or any(under(cwd, p) for p in paths)
