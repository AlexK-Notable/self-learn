"""The checked pointer (U1, 2026-09-26; spec 02-schema.md §"Transcript refs").

A :class:`Ref` names ONE entry of one Claude Code session transcript:
which session, which project folder the file lives in, which line, the
entry's own ``uuid``/``timestamp``/``cwd``, and who spoke (:data:`ROLES`).
Everything here is code -- no model call -- and every text this module
hands a caller has passed :func:`scan.redact` first.

Five services, each built on the ones above it:

1. :class:`Ref` -- the shape, serialisable to/from a plain dict.
2. :func:`resolve` -- (session, line and/or uuid) -> the REAL file and a
   filled Ref. The same session id can exist under several project
   folders (a 1-line stub beside the real file; hardlinked archive
   copies); the file that actually holds the line/uuid wins, then the
   largest, then the earlier root, then the path.
3. :func:`check_quote` -- is a quoted string really in the ref's entry?
   Seven outcomes (:data:`VERDICTS`), with a corrected Ref where the text
   was found somewhere else.
4. :func:`same_moment` / :func:`dedupe` -- a resumed or forked session
   file copies entries with their ``uuid``; the same uuid is one moment.
5. :func:`excerpt` -- the entries around a ref, with roles, bounded.

**Entry text** (:func:`entry_text`, defined once, used everywhere): the
text a person or a model reads for that entry --

- ``message.content`` as a string, or its ``text`` blocks;
- each ``tool_result`` block's content (a string, or its ``text`` items)
  -- the miner's own ``_result_text`` (``miner.py``), reused;
- each ``tool_use`` block as its tool name and the string values of its
  input, one per line (what the model wrote, without JSON escapes);
- an ``attachment`` entry's text-bearing fields (:data:`_ATTACHMENT_TEXT_KEYS`);
- a ``system`` entry's ``content`` string.

``thinking`` blocks, images, and bookkeeping rows (``last-prompt``,
``ai-title``, ``file-history-snapshot``, ...) carry no entry text.

**Roles** (:func:`role_of`). The structural split -- a ``user`` row is a
turn when it carries text and a tool result when it carries a
``tool_result`` block -- is the miner's (``miner.digest_transcript``,
``_blocks``). The miner does NOT read Claude Code's typed-turn marker
(design note d3inc38bbdON5I__mPgXz); this module does, and every rule
names the field it reads, first match wins:

1. file under ``<session>/subagents/`` (``Ref.subagent_file`` set) or the
   entry's ``isSidechain`` is true -> ``subagent``;
2. ``type == "assistant"`` -> ``assistant``;
3. ``type == "user"`` with any ``tool_result`` content block -> ``tool_result``;
4. ``type == "user"`` with ``isMeta`` or ``isCompactSummary`` true -> ``relay``
   (skill text, reminders, the summary written after a compaction);
5. ``type == "user"`` with an ``origin`` object: ``origin.kind == "human"``
   -> ``user``; any other kind (``task-notification``, ``peer``,
   ``coordinator``, ``channel``, ...) -> ``relay``;
6. ``type == "user"`` with no ``origin`` and ``promptSource`` of
   ``"system"`` or ``"sdk"`` -> ``relay`` (a program, or a client
   through the SDK, sent it; the transcript does not say a person typed
   it);
7. ``type == "user"`` with no ``origin`` whose text starts with a harness
   envelope (:data:`_HARNESS_ENVELOPES`: local-command / bash output,
   task notifications, system reminders, the interrupt notice) -> ``relay``;
8. any other ``type == "user"`` text row -> ``user`` (the miner's
   structural rule; older transcripts carry no marker, and slash
   commands / ``!`` bash inputs the person typed land here);
9. ``type == "attachment"`` whose ``attachment.type == "queued_command"``
   with ``attachment.origin.kind == "human"`` -> ``user`` (typed while
   the agent was busy); every other attachment, ``system`` row and
   bookkeeping row -> ``relay``.

Known limit (measured 2026-09-26): text another agent types into a
session's terminal (e.g. a coordinating agent driving the pane) is
recorded with ``origin.kind == "human"``, ``promptSource == "typed"`` --
field-for-field identical to the person typing. No transcript field
separates the two, so such turns resolve as ``user``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence, cast

from . import settings
from .ledger import resolve_home
from .scan import redact

__all__ = [
    "ROLES",
    "VERDICTS",
    "NEARBY_LINES",
    "OTHER_SESSION_CAP",
    "Ref",
    "RefError",
    "Verdict",
    "check_quote",
    "dedupe",
    "entry_text",
    "excerpt",
    "fold",
    "locate",
    "resolve",
    "role_of",
    "same_moment",
    "transcript_roots",
]

#: Who spoke (module docstring, "Roles").
ROLES: tuple[str, ...] = ("user", "assistant", "tool_result", "relay", "subagent")

#: :func:`check_quote` outcomes, in the order they are tried.
VERDICTS: tuple[str, ...] = (
    "exact",
    "normalised",
    "nearby",
    "elsewhere_in_file",
    "stitched",
    "other_session",
    "not_found",
)

#: ``nearby`` window, lines either side of the ref (the 2026-09-26 audit's).
NEARBY_LINES = 40
#: At most this many OTHER session files are searched for ``other_session``.
OTHER_SESSION_CAP = 200
#: A git worktree's project folder is ``<repo folder>--claude-worktrees-<name>``.
_WORKTREE_MARK = "--claude-worktrees-"

_HARNESS_ENVELOPES: tuple[str, ...] = (
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<task-notification>",
    "<system-reminder>",
    "[Request interrupted",
)
_ATTACHMENT_TEXT_KEYS: tuple[str, ...] = ("prompt", "content", "stdout", "stderr", "snippet", "text")
_ELLIPSES = re.compile(r"\s*(?:…|\.\.\.)\s*")

# ------------------------------------------------------------ the shape


class RefError(Exception):
    """A session, line or uuid that resolves to no transcript entry."""


@dataclass(frozen=True)
class Ref:
    """One transcript entry. ``line`` is 1-based in the session file (or
    in ``subagent_file`` when set, a path relative to the session's
    folder: ``subagents/agent-<id>.jsonl``). ``entry_ts`` is the entry's
    own ``timestamp`` -- never the time a tool read it."""

    session: str
    project_dir: str
    line: int
    uuid: str | None
    entry_ts: str | None
    cwd: str | None
    role: str
    subagent_file: str | None = None

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, got {self.role!r}")
        if not isinstance(self.line, int) or self.line < 1:
            raise ValueError(f"line must be a positive int, got {self.line!r}")

    def to_dict(self) -> dict:
        d = {
            "session": self.session,
            "project_dir": self.project_dir,
            "line": self.line,
            "uuid": self.uuid,
            "entry_ts": self.entry_ts,
            "cwd": self.cwd,
            "role": self.role,
        }
        if self.subagent_file is not None:
            d["subagent_file"] = self.subagent_file
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Ref":
        return cls(
            session=str(d["session"]),
            project_dir=str(d["project_dir"]),
            line=int(d["line"]),
            uuid=d.get("uuid"),
            entry_ts=d.get("entry_ts"),
            cwd=d.get("cwd"),
            role=str(d["role"]),
            subagent_file=d.get("subagent_file"),
        )

    @property
    def origin(self) -> str:
        """The legacy evidence origin string, ``transcript:<session>#L<n>``."""
        return f"transcript:{self.session}#L{self.line}"


@dataclass(frozen=True)
class Verdict:
    """:func:`check_quote`'s answer. ``ref`` is where the quote was found
    (the input ref for ``exact``/``normalised``, a corrected ref for
    ``nearby``/``elsewhere_in_file``/``other_session``, the input ref for
    ``stitched``/``not_found``). ``pieces`` holds, for ``stitched``, the
    ref of each piece's occurrence nearest the cited line. ``detail`` never carries
    transcript or quote text."""

    outcome: str
    ref: Ref
    detail: str = ""
    pieces: tuple[Ref, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------- roots


def transcript_roots(home: Path | str | None = None) -> list[Path]:
    """The registry's ``refs.transcript_roots`` (``os.pathsep``-joined),
    each ``~``-expanded at run time, in order."""
    resolved = Path(home).expanduser() if home is not None else resolve_home()
    raw, _src = settings.resolve_setting(resolved, settings.by_name("refs.transcript_roots"))
    return [Path(p).expanduser() for p in cast(str, raw).split(os.pathsep) if p.strip()]


def _roots(roots: Sequence[Path | str] | None) -> list[Path]:
    return [Path(r).expanduser() for r in roots] if roots is not None else transcript_roots()


# ------------------------------------------------------ reading a file


@lru_cache(maxsize=16)
def _lines_cached(path: str, _mtime_ns: int, _size: int) -> tuple[str, ...]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return tuple(fh.read().splitlines())


def _lines(path: Path) -> tuple[str, ...]:
    st = path.stat()
    return _lines_cached(str(path), st.st_mtime_ns, st.st_size)


def _entry(raw: str) -> dict | None:
    try:
        e = json.loads(raw)
    except ValueError:
        return None
    return e if isinstance(e, dict) else None


def _blocks(entry: dict) -> list[dict]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _result_text(block: dict) -> str:
    # miner._result_text, reused rather than imported: miner.py imports
    # the invocation stack; this module stays import-light for the steward.
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []


def _raw_text(entry: dict) -> str:
    """Entry text (module docstring), UNREDACTED -- internal only."""
    etype = entry.get("type")
    parts: list[str] = []
    if etype in ("user", "assistant"):
        for b in _blocks(entry):
            bt = b.get("type")
            if bt == "text":
                parts.append(str(b.get("text", "")))
            elif bt == "tool_result":
                parts.append(_result_text(b))
            elif bt == "tool_use":
                parts.append(str(b.get("name", "")))
                parts.extend(_strings(b.get("input")))
    elif etype == "attachment":
        att = entry.get("attachment")
        if isinstance(att, dict):
            for k in _ATTACHMENT_TEXT_KEYS:
                parts.extend(_strings(att.get(k)))
    elif etype == "system":
        c = entry.get("content")
        if isinstance(c, str):
            parts.append(c)
    return "\n".join(p for p in parts if p)


def entry_text(ref: Ref, *, roots: Sequence[Path | str] | None = None) -> str:
    """The ref's entry text (module docstring), redacted."""
    path = locate(ref, roots=roots)
    e = _entry(_lines(path)[ref.line - 1])
    return redact(_raw_text(e))[0] if e else ""


def role_of(entry: dict, *, in_subagent_file: bool = False) -> str:
    """The entry's role, by the numbered rules in the module docstring."""
    if in_subagent_file or entry.get("isSidechain") is True:  # rule 1
        return "subagent"
    etype = entry.get("type")
    if etype == "assistant":  # rule 2
        return "assistant"
    if etype == "user":
        blocks = _blocks(entry)
        if any(b.get("type") == "tool_result" for b in blocks):  # rule 3
            return "tool_result"
        if entry.get("isMeta") is True or entry.get("isCompactSummary") is True:  # rule 4
            return "relay"
        origin = entry.get("origin")
        if isinstance(origin, dict):  # rule 5
            return "user" if origin.get("kind") == "human" else "relay"
        if entry.get("promptSource") in ("system", "sdk"):  # rule 6
            return "relay"
        text = "\n".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text").lstrip()
        if text.startswith(_HARNESS_ENVELOPES):  # rule 7
            return "relay"
        return "user"  # rule 8
    if etype == "attachment":  # rule 9
        att = entry.get("attachment")
        if isinstance(att, dict) and att.get("type") == "queued_command":
            origin = att.get("origin")
            if isinstance(origin, dict) and origin.get("kind") == "human":
                return "user"
    return "relay"


# --------------------------------------------------------- the resolver


def _session_files(session: str, roots: list[Path]) -> list[tuple[int, Path]]:
    """(root index, path) of every top-level ``<session>.jsonl`` under any root."""
    out: list[tuple[int, Path]] = []
    name = f"{session}.jsonl"
    for i, root in enumerate(roots):
        if not root.is_dir():
            continue
        for proj in sorted(root.iterdir()):
            f = proj / name
            if f.is_file():
                out.append((i, f))
    return out


def _subagent_files(session: str, roots: list[Path], only: str | None) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for i, root in enumerate(roots):
        if not root.is_dir():
            continue
        for proj in sorted(root.iterdir()):
            d = proj / session
            if only is not None:
                f = d / only
                if f.is_file():
                    out.append((i, f))
            elif (d / "subagents").is_dir():
                out.extend((i, f) for f in sorted((d / "subagents").glob("agent-*.jsonl")))
    return out


def _uuid_line(lines: Sequence[str], uuid: str) -> int | None:
    needle = f'"{uuid}"'
    for i, raw in enumerate(lines, 1):
        if needle in raw:
            e = _entry(raw)
            if e is not None and e.get("uuid") == uuid:
                return i
    return None


def _ref_at(path: Path, line: int, *, session: str, subagent_file: str | None) -> Ref:
    lines = _lines(path)
    if not 1 <= line <= len(lines):
        raise RefError(f"{session}: line {line} is past the end of the file ({len(lines)} lines)")
    e = _entry(lines[line - 1])
    if e is None:
        raise RefError(f"{session}#L{line}: not a JSON object")
    project_dir = path.parent.name if subagent_file is None else path.parents[2].name
    ts, cwd, uid = e.get("timestamp"), e.get("cwd"), e.get("uuid")
    if ts is None and isinstance(e.get("attachment"), dict):
        ts = e["attachment"].get("timestamp")
    return Ref(
        session=session,
        project_dir=project_dir,
        line=line,
        uuid=uid if isinstance(uid, str) else None,
        entry_ts=ts if isinstance(ts, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        role=role_of(e, in_subagent_file=subagent_file is not None),
        subagent_file=subagent_file,
    )


def resolve(
    session: str,
    line: int | None = None,
    uuid: str | None = None,
    *,
    subagent_file: str | None = None,
    roots: Sequence[Path | str] | None = None,
) -> Ref:
    """Find the real file for ``session`` and fill a :class:`Ref`.

    Every project folder under every root is searched. Candidates are
    ranked: holds ``uuid`` at ``line`` > holds ``uuid`` > has ``line``
    (a stub shorter than ``line`` is never chosen) > larger file >
    earlier root > path. With a ``uuid`` the ref is the entry carrying
    it (its line may differ from ``line``); otherwise the entry at
    ``line``; with neither, line 1 of the largest copy. A uuid missing
    from every top-level copy is looked for in the session's subagent
    files. Raises :class:`RefError` when nothing matches."""
    if line is None and uuid is None:
        line = 1
    rs = _roots(roots)
    pools = (
        [_subagent_files(session, rs, subagent_file)]
        if subagent_file is not None
        else [_session_files(session, rs), _subagent_files(session, rs, None)]
    )
    for pool in pools:
        best: tuple | None = None
        for ri, path in pool:
            lines = _lines(path)
            at = _uuid_line(lines, uuid) if uuid is not None else None
            if uuid is not None and at is None:
                continue
            if uuid is None and line is not None and line > len(lines):
                continue
            key = (
                at is not None and at == line,
                at is not None,
                len(lines),
                path.stat().st_size,
                -ri,
            )
            if best is None or key > best[0] or (key == best[0] and str(path) < str(best[1])):
                best = (key, path, at if at is not None else line)
        if best is not None:
            _key, path, found_line = best
            sub = None
            if pool is not pools[0] or subagent_file is not None:
                sub = str(Path(path).relative_to(path.parents[1]))
            return _ref_at(path, found_line, session=session, subagent_file=sub)
    raise RefError(f"no transcript holds session {session} (line={line}, uuid={uuid})")


def locate(ref: Ref, *, roots: Sequence[Path | str] | None = None) -> Path:
    """The file a ref points into: ``<root>/<project_dir>/<session>.jsonl``
    (or the subagent file) under any root. Among the copies that have
    ``ref.line``, ranked as :func:`resolve` ranks: the entry at that line
    carries ``ref.uuid`` > more lines > larger file > earlier root. A
    shorter stub copy in an earlier root therefore never wins, with or
    without a uuid."""
    rs = _roots(roots)
    rel = Path(ref.project_dir) / (
        Path(ref.session) / ref.subagent_file if ref.subagent_file else f"{ref.session}.jsonl"
    )
    best: tuple[tuple, Path] | None = None
    for ri, root in enumerate(rs):
        p = root / rel
        if not p.is_file():
            continue
        lines = _lines(p)
        if ref.line > len(lines):
            continue
        e = _entry(lines[ref.line - 1])
        holds = ref.uuid is not None and e is not None and e.get("uuid") == ref.uuid
        key = (holds, len(lines), p.stat().st_size, -ri)
        if best is None or key > best[0]:
            best = (key, p)
    if best is not None:
        return best[1]
    raise RefError(f"no file for {ref.origin} under project folder {ref.project_dir}")


# ---------------------------------------------------------- quote check


_QUOTES = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
        "―": "-", "−": "-",
    }
)
_WS = re.compile(r"\s+")
_MARKUP = re.compile(r"[`*]")


def fold(text: str) -> str:
    """The ``normalised`` comparison form: curly single quotes and primes
    (U+2018 U+2019 U+201A U+201B U+2032) -> ``'``; curly double quotes
    (U+201C U+201D U+201E U+201F U+2033) -> ``"``; the dash family
    (U+2010-U+2015, U+2212) -> ``-``; markdown code and emphasis marks
    (every backtick and asterisk) deleted; every whitespace run -> one
    space; stripped; case folded (:meth:`str.casefold`). Nothing else:
    punctuation, digits and words are kept, so a quote that changes a
    word never matches. (Measured 2026-09-26: the seven quotes the audit
    matched only after normalising differ from their source solely by
    dropped backticks / ``**``; a stitched quote's piece taken from
    mid-sentence differs by its first letter's case.)"""
    return _WS.sub(" ", _MARKUP.sub("", text.translate(_QUOTES))).strip().casefold()


def _match(quote: str, text: str) -> str | None:
    if quote in text:
        return "exact"
    if fold(quote) and fold(quote) in fold(text):
        return "normalised"
    return None


def _anchor(quote: str) -> str:
    """The longest run of letters/digits in ``quote``: a cheap raw-line
    prefilter -- folding never changes such a run, so a line whose raw
    JSON lacks it cannot match."""
    runs = re.findall(r"[A-Za-z0-9]+", quote)
    return max(runs, key=len) if runs else ""


def _find_in(lines: Sequence[str], quote: str, roles: tuple[str, ...] | None = None) -> list[int]:
    """1-based lines whose entry text contains ``quote`` (exactly or
    folded), limited to entries whose :func:`role_of` is in ``roles``
    when given."""
    anchor = _anchor(quote)
    hits: list[int] = []
    for i, raw in enumerate(lines, 1):
        if anchor and anchor not in raw:
            continue
        e = _entry(raw)
        if e is None or (roles is not None and role_of(e) not in roles):
            continue
        if _match(quote, _raw_text(e)):
            hits.append(i)
    return hits


def _family(project_dir: str) -> str:
    return project_dir.split(_WORKTREE_MARK, 1)[0]


def _ts_epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _other_sessions(ref: Ref, rs: list[Path], cap: int) -> list[Path]:
    """Top-level session files in the ref's project FAMILY (its folder
    and every ``<folder>--claude-worktrees-*`` sibling, or the repo
    folder a worktree folder belongs to), other than the ref's own
    session, one copy per (folder, session) with the earlier root
    winning, nearest in modification time to ``ref.entry_ts`` first,
    at most ``cap``."""
    fam = _family(ref.project_dir)
    seen: dict[tuple[str, str], Path] = {}
    for root in rs:
        if not root.is_dir():
            continue
        for proj in sorted(root.iterdir()):
            if not proj.is_dir() or _family(proj.name) != fam:
                continue
            for f in sorted(proj.glob("*.jsonl")):
                if f.stem == ref.session:
                    continue
                seen.setdefault((proj.name, f.stem), f)
    at = _ts_epoch(ref.entry_ts)
    files = list(seen.values())
    if at is not None:
        files.sort(key=lambda p: abs(p.stat().st_mtime - at))
    return files[:cap]


def check_quote(
    ref: Ref,
    quote: str,
    *,
    roots: Sequence[Path | str] | None = None,
    nearby_lines: int = NEARBY_LINES,
    other_session_cap: int = OTHER_SESSION_CAP,
) -> Verdict:
    """Where is ``quote`` relative to ``ref``? Tried in :data:`VERDICTS`
    order: ``exact`` (verbatim substring of the ref's entry text),
    ``normalised`` (substring after :func:`fold`), ``nearby`` (in another
    entry within ``nearby_lines`` of the ref, closest first),
    ``elsewhere_in_file``, ``stitched`` (the quote holds ``…`` or ``...``
    and every piece between them occurs, exactly or folded, somewhere in
    the ref's file -- no single entry holds the whole), ``other_session``
    (whole quote in a ``user`` or ``assistant`` entry of another session
    file of the ref's project family, searched per :func:`_other_sessions`,
    at most ``other_session_cap`` files), else ``not_found``.

    ``other_session`` ignores tool results and relays: a later session
    that reads a ledger record or a transcript back echoes the quote as a
    tool result (measured 2026-09-26: a mined quote that silently fixed
    the user's typo matched only a later session's listing of the
    pending queue). Within the ref's own file every role counts."""
    rs = _roots(roots)
    path = locate(ref, roots=rs)
    lines = _lines(path)
    e = _entry(lines[ref.line - 1])
    how = _match(quote, _raw_text(e)) if e else None
    if how:
        return Verdict(how, ref)

    def at(line: int) -> Ref:
        return _ref_at(path, line, session=ref.session, subagent_file=ref.subagent_file)

    hits = [h for h in _find_in(lines, quote) if h != ref.line]
    if hits:
        best = min(hits, key=lambda h: (abs(h - ref.line), h))
        kind = "nearby" if abs(best - ref.line) <= nearby_lines else "elsewhere_in_file"
        return Verdict(kind, at(best), detail=f"offset {best - ref.line:+d}")

    # a piece with no letter or digit (e.g. the ")" after "f(x=...)")
    # carries no claim and would match almost anywhere
    pieces = [p for p in _ELLIPSES.split(quote) if _anchor(p)]
    unfound_piece = 0  # 1-based index of the first piece found nowhere in the file
    if len(pieces) >= 2:
        found: list[Ref] = []
        for p in pieces:
            ph = _find_in(lines, p)
            if not ph:
                unfound_piece = len(found) + 1
                break
            found.append(at(min(ph, key=lambda h: (abs(h - ref.line), h))))
        else:
            return Verdict(
                "stitched", ref, detail=f"{len(pieces)} pieces, each found separately", pieces=tuple(found)
            )

    searched = 0
    for f in _other_sessions(ref, rs, other_session_cap):
        searched += 1
        fh = _find_in(_lines(f), quote, roles=("user", "assistant"))
        if fh:
            return Verdict(
                "other_session",
                _ref_at(f, fh[0], session=f.stem, subagent_file=None),
                detail=f"found in another session of the project family ({searched} files searched)",
            )
    note = f"; {len(pieces)} ellipsis-joined pieces, piece {unfound_piece} not in the file" if unfound_piece else ""
    return Verdict("not_found", ref, detail=f"{searched} other session files searched{note}")


# ------------------------------------------------------------ duplicates


def same_moment(a: Ref, b: Ref) -> bool:
    """True when both refs carry the same entry ``uuid`` -- a resumed or
    forked session file copies entries with their uuid, so two files'
    lines can be one moment. Refs without a uuid are never the same."""
    return a.uuid is not None and a.uuid == b.uuid


def dedupe(refs: Iterable[Ref]) -> list[Ref]:
    """``refs`` with every later :func:`same_moment` copy dropped, order kept."""
    seen: set[str] = set()
    out: list[Ref] = []
    for r in refs:
        if r.uuid is not None:
            if r.uuid in seen:
                continue
            seen.add(r.uuid)
        out.append(r)
    return out


# --------------------------------------------------------------- excerpt


def excerpt(
    ref: Ref,
    before: int = 3,
    after: int = 3,
    *,
    entry_chars: int = 2_000,
    total_chars: int = 12_000,
    roots: Sequence[Path | str] | None = None,
) -> list[tuple[Ref, str]]:
    """The ref's entry plus up to ``before`` entries before it and
    ``after`` after it, counting only entries with non-empty entry text,
    in file order, each paired with its Ref (role included). Each text is
    redacted, then clipped to ``entry_chars`` (head and tail kept, the
    middle marked ``…[clipped]…``); entries farthest from the ref are
    dropped first until the texts total at most ``total_chars``. The
    ref's own entry is always kept."""
    path = locate(ref, roots=roots)
    lines = _lines(path)

    def text_at(i: int) -> str:
        e = _entry(lines[i - 1])
        return _raw_text(e) if e else ""

    def collect(rng: Iterable[int], n: int) -> list[int]:
        got: list[int] = []
        for i in rng:
            if len(got) >= n:
                break
            if text_at(i).strip():
                got.append(i)
        return got

    picked = sorted(
        collect(range(ref.line - 1, 0, -1), before)
        + [ref.line]
        + collect(range(ref.line + 1, len(lines) + 1), after)
    )

    def clip(t: str) -> str:
        if len(t) <= entry_chars:
            return t
        half = max(0, (entry_chars - 13) // 2)
        return t[:half] + " …[clipped]… " + t[len(t) - half :]

    texts = {i: clip(redact(text_at(i))[0]) for i in picked}
    for i in sorted(picked, key=lambda i: -abs(i - ref.line)):
        if sum(len(t) for t in texts.values()) <= total_chars or i == ref.line:
            break
        del texts[i]
    if len(texts[ref.line]) > total_chars:
        texts[ref.line] = texts[ref.line][:total_chars]
    return [
        (ref if i == ref.line else _ref_at(path, i, session=ref.session, subagent_file=ref.subagent_file), texts[i])
        for i in sorted(texts)
    ]
