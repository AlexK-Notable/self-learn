"""canon_watch.py — what the user writes by hand, read against placed lessons (S-148).

The user, 2026-10-31: "manual maintenance isn't something you should ever
take care of directly." The overseer's census of 2026-11-08 traced five of
the week's nine hand edits of lessons to one gap: the user adds or changes a
rule in their own instruction file, and nothing re-reads the placed lessons
it now covers, narrows or contradicts. An agent noticed each time and
replaced or retired the lesson by hand.

This module is the missing notice. It never calls a model and never writes
the ledger or any instruction file:

* :func:`observe` keeps, in the cache, the hand-written text of the user's
  own always-loaded files (the user's `CLAUDE.md` outside self-learn's
  markers, and the files under the user's `rules/`), and records as a
  *change* the lines a file gained since the last look. The first look of
  all only takes the snapshots.
* :func:`resembling` names the placed lessons whose words overlap a change
  the most (:func:`similar`: shared uncommon words, weighted by how rare
  each is among the lessons). It is a word match, deliberately cheap and
  deterministic; it proposes, and a model decides.
* The daily premise sweep turns each into a failing ``@canon`` placement
  premise (`premise_sweep._canon_facts`), which after two sweeps is an input
  of the nightly steward: it reads the lesson against the user's new words
  and retires it as covered, rewrites it to agree, or leaves it.

The user's own words are kept only in the cache (never in the ledger's
run records, which hold the change's short hash).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

__all__ = [
    "ACTIVE_DAYS",
    "Change",
    "MAX_LESSONS_PER_CHANGE",
    "PREMISE_ID",
    "change_by_sha",
    "hand_text",
    "observe",
    "resembling",
    "similar",
    "watch_dir",
    "watched_files",
]

#: The placement premise the sweep derives (`premises.PLACEMENT_PREMISE_IDS`).
PREMISE_ID = "@canon"
#: How long a change keeps being read against the lessons. Long enough for
#: two daily sweeps and a week of the steward's nightly cap.
ACTIVE_DAYS = 21
#: At most this many lessons are offered for one change, best match first.
MAX_LESSONS_PER_CHANGE = 6
#: A lesson resembles a change when they share at least this many uncommon
#: words and those words carry at least this share of the lesson's weight.
MIN_SHARED = 5
MIN_SCORE = 0.22
#: Added lines shorter than this many words are not a rule (a heading, a
#: date); a change needs this many words in all.
_MIN_LINE_WORDS = 5
_MIN_CHANGE_WORDS = 12
_KEEP_CHARS = 6_000

_BEGIN_RE = re.compile(r"<!-- self-learn:(?:pointers:)?begin\b[^>]*-->")
_END_RE = re.compile(r"<!-- self-learn:(?:pointers:)?end -->")
_WORD_RE = re.compile(r"[a-z][a-z0-9_'-]{3,}")
_STOP = frozenset(
    "about above after again against also always another because been before being below "
    "between both cannot could does doing done down during each either else even every from "
    "further have having here into itself just least less like many more most much must "
    "never none once only onto other otherwise over rather same should since some such than "
    "that their them then there these they this those through under until upon very want "
    "were what when where whether which while will with within without would your yours "
    "make makes made take takes taken need needs used using uses still thing things".split()
)


@dataclass(frozen=True)
class Change:
    """Lines one of the user's own files gained. ``sha`` is the short hash of
    ``text`` (the lines, joined); ``at`` is when the sweep first saw them."""

    path: str
    at: str
    sha: str
    text: str


def watch_dir(cache_dir: Path) -> Path:
    return Path(cache_dir) / "canon-watch"


def hand_text(text: str) -> str:
    """*text* without what self-learn manages: everything between a begin
    and an end marker (the lesson block and the pointer block), markers
    included. An unclosed begin marker hides the rest of the file, so a
    damaged block is never read as the user's words."""
    out: list[str] = []
    hidden = False
    for line in text.splitlines():
        if not hidden and _BEGIN_RE.search(line):
            hidden = True
            continue
        if hidden:
            if _END_RE.search(line):
                hidden = False
            continue
        out.append(line)
    return "\n".join(out)


def watched_files(claude_dir: Path) -> list[Path]:
    """The user's own always-loaded files: `CLAUDE.md` and `rules/*.md`."""
    claude_dir = Path(claude_dir)
    files = [claude_dir / "CLAUDE.md"]
    rules = claude_dir / "rules"
    if rules.is_dir():
        files += sorted(p for p in rules.glob("*.md") if p.is_file())
    return [p for p in files if p.is_file()]


def _snap_path(root: Path, path: Path) -> Path:
    return root / (hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16] + ".txt")


def _write(path: Path, text: str) -> None:
    from .primitives import fsops  # late

    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, text, fsync=False, preserve_mode=False)


def _load_changes(root: Path) -> list[Change]:
    try:
        rows = json.loads((root / "changes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[Change] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ("path", "at", "sha", "text")):
            out.append(Change(row["path"], row["at"], row["sha"], row["text"]))
    return out


def _added_lines(old: str, new: str) -> list[str]:
    """Lines of *new* that *old* does not hold anywhere (so a moved section
    is not a change), long enough to be a sentence."""
    seen = {line.strip() for line in old.splitlines()}
    out: list[str] = []
    for line in new.splitlines():
        stripped = line.strip()
        if stripped and stripped not in seen and len(stripped.split()) >= _MIN_LINE_WORDS:
            out.append(stripped)
    return out


def observe(cache_dir: Path, claude_dir: Path, *, now: datetime | None = None) -> list[Change]:
    """Look at the watched files once: record a change for each file that
    gained lines since its snapshot, refresh the snapshots, forget changes
    older than :data:`ACTIVE_DAYS`, and return the changes still active,
    oldest first. The first look of all (no snapshot directory) records no
    change. Never raises for an unreadable file: it is skipped this time."""
    moment = now or datetime.now(timezone.utc)
    root = watch_dir(cache_dir)
    first_look = not (root / "initialized").exists()
    changes = _load_changes(root)
    known = {change.sha for change in changes}
    for path in watched_files(claude_dir):
        try:
            hand = hand_text(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        snap = _snap_path(root, path)
        try:
            old: str | None = snap.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            old = None
        if old == hand:
            continue
        if not first_look:
            added = _added_lines(old or "", hand)
            text = "\n".join(added)[:_KEEP_CHARS]
            if len(text.split()) >= _MIN_CHANGE_WORDS:
                sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
                if sha not in known:
                    known.add(sha)
                    changes.append(Change(
                        str(path), moment.isoformat(timespec="seconds"), sha, text
                    ))
        _write(snap, hand)
    cutoff = (moment - timedelta(days=ACTIVE_DAYS)).isoformat(timespec="seconds")
    changes = sorted((c for c in changes if c.at >= cutoff), key=lambda c: (c.at, c.sha))
    _write(root / "changes.json", json.dumps(
        [{"path": c.path, "at": c.at, "sha": c.sha, "text": c.text} for c in changes],
        indent=1,
    ) + "\n")
    if first_look:
        _write(root / "initialized", moment.isoformat(timespec="seconds") + "\n")
    return changes


def change_by_sha(cache_dir: Path, sha: str) -> Change | None:
    """The kept change with this short hash, for the steward's brief."""
    return next((c for c in _load_changes(watch_dir(cache_dir)) if c.sha == sha), None)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


def similar(
    change_text: str, lessons: Mapping[str, str]
) -> list[tuple[str, float, int]]:
    """``[(lesson id, score, shared words)]`` for the lessons that resemble
    *change_text*, best first. A word's weight is how rare it is among the
    lessons; the score is the weight of the words a lesson shares with the
    change over the weight of all the lesson's words."""
    bags = {rid: _tokens(text) for rid, text in lessons.items()}
    count = len(bags)
    df: dict[str, int] = {}
    for bag in bags.values():
        for word in bag:
            df[word] = df.get(word, 0) + 1

    def weight(word: str) -> float:
        return math.log((count + 1) / (df.get(word, 0) + 1)) + 1.0

    wanted = _tokens(change_text)
    out: list[tuple[str, float, int]] = []
    for rid, bag in bags.items():
        shared = bag & wanted
        if len(shared) < MIN_SHARED or not bag:
            continue
        score = sum(weight(w) for w in shared) / sum(weight(w) for w in bag)
        if score >= MIN_SCORE:
            out.append((rid, round(score, 3), len(shared)))
    out.sort(key=lambda row: (-row[1], row[0]))
    return out


def resembling(
    changes: Iterable[Change], lessons: Mapping[str, str]
) -> dict[str, tuple[Change, float]]:
    """``lesson id -> (the change it resembles most, score)``, at most
    :data:`MAX_LESSONS_PER_CHANGE` lessons for one change."""
    best: dict[str, tuple[Change, float]] = {}
    for change in changes:
        for rid, score, _shared in similar(change.text, lessons)[:MAX_LESSONS_PER_CHANGE]:
            if rid not in best or score > best[rid][1]:
                best[rid] = (change, score)
    return best
