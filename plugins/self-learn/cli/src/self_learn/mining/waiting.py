"""Waiting answers: a session's checked output, saved before any of it lands
(new-miner R2, fix round 4; the user's design).

When a session's answer passes the checker, the engine writes it here
before landing anything: one JSON file per session answer, in
``<miner dir>/pending/``, never inside a run folder (run folders are pruned
to the newest 30; a waiting answer is kept until every item in it has
landed or been dropped on purpose). Once the file is on disk, the session's
cursor moves and the judged-uuid store learns from it: the model is never
asked about those lines again, whatever happens to the landing.

Every run that is not a preview lands the waiting answers under the ledger
lock, oldest first, one item at a time. An item's state is written back to
its file (a whole-file atomic rewrite) after its write completes, so a crash
between the two replays the item, and its landing's own deduplication
(known origin, the target record's evidence, spooled and tracked events)
makes the replay a no-op. A file whose items have all landed or been
dropped is removed.

A file holds: ``contract``, ``session``, ``transcript`` (the file's path),
``run_id`` (the run that saved it), ``method_version``, ``saved_ns`` (the
order answers drain in), ``saved_at``, ``halted``, ``cwd``, ``cursor`` (the
entry the session's cursor takes at save), ``learn`` (what the judged-uuid
store learns from it), ``checked`` (the ``miner-output/1`` document,
verbatim) and ``items``: one per lesson, sighting and rule check of
``checked``, in that order, each ``{kind, index, state, failures}`` plus,
once it has one, ``outcome``, ``reason`` and ``error``. Files are mode 0600:
they hold redacted transcript text, as run folders do.

This module only reads and writes those files; ``miner.py`` lands the
items.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, TypeGuard

from ..primitives import chrono, fsops
from . import contract

__all__ = [
    "ITEM_KINDS",
    "ITEM_STATES",
    "PENDING_DIR",
    "Row",
    "STUCK_AFTER",
    "WAITING_CONTRACT",
    "Answer",
    "Stuck",
    "fsync_file_and_folder",
    "item_origin",
    "load_all",
    "pending_dir",
    "preflight",
    "save",
    "stuck_items",
]

WAITING_CONTRACT = "miner-waiting/1"
PENDING_DIR = "pending"
#: The kinds of item a checked output holds, in the order they land.
ITEM_KINDS: tuple[str, ...] = contract.WAITING_ITEM_KINDS
#: ``waiting`` until it lands (``landed``) or is dropped on purpose
#: (``dropped``: a duplicate, a stale target, a scan refusal, ...);
#: ``writing`` once what it is about to write is recorded on it, until
#: that output's mark (fix round 5).
ITEM_STATES: tuple[str, ...] = ("waiting", "writing", "landed", "dropped")
#: What a ``writing`` item's intent writes.
INTENT_OUTPUTS: tuple[str, ...] = ("lesson", "resurface", "fold", "recurrence-suspect", "fire")
#: The intent outputs each item kind can record (fix round 6): a lesson
#: writes a lesson; a sighting resurfaces, folds or spools a recurrence;
#: a rule check spools a fire.
INTENT_OUTPUTS_BY_KIND: dict[str, tuple[str, ...]] = {
    "lessons": ("lesson",),
    "sightings": ("resurface", "fold", "recurrence-suspect"),
    "rule_checks": ("fire",),
}
#: The shape of a transcript origin (``miner._ref_origin``).
ORIGIN_RE = re.compile(r"transcript:[^\s#]+#L[1-9][0-9]*")
#: An item whose write failed on this many runs is *stuck*: shown by
#: ``self-learn doctor miner`` and in ``run.json``. It keeps retrying.
STUCK_AFTER = contract.STUCK_AFTER

_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def pending_dir(miner_dir: Path) -> Path:
    return Path(miner_dir) / PENDING_DIR


@dataclass
class Answer:
    """One waiting answer, as loaded or as just saved."""

    path: Path
    doc: dict[str, Any]
    #: True once its ``learn`` set is in the judged-uuid store: at its
    #: save, or re-learned by a later run. Until then a finished answer
    #: is kept (fix round 5).
    learned: bool = field(default=False, compare=False)

    @property
    def session(self) -> str:
        return str(self.doc["session"])

    @property
    def run_id(self) -> str:
        return str(self.doc["run_id"])

    @property
    def items(self) -> list[dict[str, Any]]:
        return self.doc["items"]

    @property
    def cwd(self) -> str | None:
        cwd = self.doc.get("cwd")
        return cwd if isinstance(cwd, str) and cwd else None

    @property
    def learn(self) -> frozenset[str]:
        return frozenset(u for u in self.doc.get("learn", []) if isinstance(u, str) and u)

    def item(self, entry: dict[str, Any]) -> dict[str, Any]:
        """The checked item ``entry`` (one of :attr:`items`) stands for."""
        return self.doc["checked"][entry["kind"]][entry["index"]]

    def waiting(self) -> list[dict[str, Any]]:
        """The items not finished: ``waiting``, or ``writing`` (not yet
        marked ``landed``)."""
        return [e for e in self.items if e["state"] in ("waiting", "writing")]

    def done(self) -> bool:
        return not self.waiting()

    def mark(self) -> None:
        """Write the items' states back: one whole-file atomic rewrite
        (temp file, fsync, rename)."""
        fsops.private_write(self.path, _dumps(self.doc))

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)


def _dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def save(
    miner_dir: Path,
    *,
    session: str,
    transcript: str,
    run_id: str,
    method_version: str,
    halted: bool,
    cwd: str | None,
    cursor: dict[str, Any],
    learn: Iterable[str],
    checked: dict[str, Any],
) -> Answer:
    """Write one session's checked output as a waiting answer, atomically
    and fsync'd, before anything of it lands; raises ``OSError`` when it
    cannot (nothing is saved, and the caller moves nothing)."""
    ns = time.time_ns()
    items = [
        {"kind": kind, "index": i, "state": "waiting", "failures": 0}
        for kind in ITEM_KINDS
        for i in range(len(checked.get(kind, [])))
    ]
    doc = {
        "contract": WAITING_CONTRACT,
        "session": session,
        "transcript": transcript,
        "run_id": run_id,
        "method_version": method_version,
        "saved_ns": ns,
        "saved_at": chrono.now_iso(),
        "halted": bool(halted),
        "cwd": cwd,
        "cursor": cursor,
        "learn": sorted(set(learn)),
        "checked": checked,
        "items": items,
    }
    folder = pending_dir(miner_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ns:020d}-{_SLUG_RE.sub('_', session)[:80]}.json"
    fsops.private_write(path, _dumps(doc))
    return Answer(path, doc)


def _int(value: object, *, low: int = 0) -> TypeGuard[int]:
    """An int that is not a bool, at least ``low``."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _valid_intent(kind: str, intent: object) -> bool:
    """A ``writing`` item's intent, as the replay reads it (fix round 6):
    an output its kind can record, a target record id for every output
    but a lesson (which has none), and a transcript origin."""
    if not isinstance(intent, dict) or intent.get("output") not in INTENT_OUTPUTS_BY_KIND[kind]:
        return False
    record = intent.get("record")
    if intent["output"] == "lesson":
        if record is not None:
            return False
    elif not isinstance(record, str) or not record:
        return False
    origin = intent.get("origin")
    return isinstance(origin, str) and ORIGIN_RE.fullmatch(origin) is not None


def _valid(doc: object) -> bool:
    """A file this code reads as a waiting answer: the contract it
    writes, a ``checked`` part that passes ``miner-output/1``, its
    ``cursor`` and ``learn``, and exactly one item per checked lesson,
    sighting and rule check -- none missing, none twice (fix round 5: an
    answer that lists fewer items would land less than it saved). Every
    field is checked as the code that consumes it reads it -- cursor
    settlement, learning and the replay (fix round 6): ``lines`` and
    ``size`` non-negative ints, ``halt`` a bool, indexes and counts ints
    and never bools, and a ``writing`` item's intent fit for its kind."""
    if not isinstance(doc, dict) or doc.get("contract") != WAITING_CONTRACT:
        return False
    if not all(isinstance(doc.get(k), str) and doc[k] for k in ("session", "run_id", "transcript")):
        return False
    if not _int(doc.get("saved_ns")) or not isinstance(doc.get("items"), list):
        return False
    cursor = doc.get("cursor")
    if (not isinstance(cursor, dict) or not all(_int(cursor.get(k)) for k in ("lines", "size"))
            or not isinstance(cursor.get("halt"), bool)):
        return False
    learn = doc.get("learn")
    if not isinstance(learn, list) or not all(isinstance(u, str) and u for u in learn):
        return False
    checked = doc.get("checked")
    if contract.validate_checked_output(checked):
        return False
    assert isinstance(checked, dict)
    expected = {(kind, i) for kind in ITEM_KINDS for i in range(len(checked[kind]))}
    seen: set[tuple[str, int]] = set()
    for e in doc["items"]:
        if not isinstance(e, dict) or e.get("kind") not in ITEM_KINDS or e.get("state") not in ITEM_STATES:
            return False
        i = e.get("index")
        if not _int(i) or (e["kind"], i) not in expected or (e["kind"], i) in seen:
            return False
        seen.add((e["kind"], i))
        if not _int(e.get("failures")):
            return False
        if e["state"] == "writing" and not _valid_intent(e["kind"], e.get("intent")):
            return False
    return seen == expected


def load_all(miner_dir: Path) -> tuple[list[Answer], list[str]]:
    """Every waiting answer, oldest first; and the names of the files that
    do not read as one (they are left where they are, and reported)."""
    folder = pending_dir(miner_dir)
    if not folder.is_dir():
        return [], []
    answers: list[Answer] = []
    broken: list[str] = []
    for path in sorted(folder.glob("*.json")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            broken.append(path.name)
            continue
        if not _valid(doc):
            broken.append(path.name)
            continue
        answers.append(Answer(path, doc))
    answers.sort(key=lambda a: (a.doc["saved_ns"], a.path.name))
    return answers, broken


def fsync_file_and_folder(path: Path) -> None:
    """Make an appended file durable: fsync it, then its folder (which
    holds its name when the append created it)."""
    for target, flags in ((Path(path), os.O_RDONLY), (Path(path).parent, os.O_RDONLY)):
        fd = os.open(target, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@dataclass(frozen=True)
class Stuck:
    """An item whose write failed on :data:`STUCK_AFTER` runs or more."""

    session: str
    kind: str
    origin: str
    failures: int
    error: str

    def as_dict(self) -> dict[str, Any]:
        return {"session": self.session, "kind": self.kind, "origin": self.origin,
                "failures": self.failures, "error": self.error}


def item_origin(item: dict[str, Any], kind: str) -> str:
    """The transcript origin an item is known by (its first pointer)."""
    pointer = item["situation"] if kind == "rule_checks" else item["evidence"][0]
    ref = pointer["ref"]
    sub = ref.get("subagent_file")
    where = f"{ref['session']}/{sub}" if sub else str(ref["session"])
    return f"transcript:{where}#L{ref['line']}"


def stuck_items(answers: Iterable[Answer]) -> list[Stuck]:
    return [
        Stuck(a.session, e["kind"], item_origin(a.item(e), e["kind"]), e["failures"], str(e.get("error") or "")[:200])
        for a in answers
        for e in a.waiting()
        if e["failures"] >= STUCK_AFTER
    ]


@dataclass(frozen=True)
class Row:
    """One line of ``self-learn doctor miner``: ``OK`` or ``WARN``."""

    verdict: str
    name: str
    detail: str


def preflight(miner_dir: Path, *, engine: str = "session") -> list[Row]:
    """``self-learn doctor miner``: how many answers and items wait, each
    stuck item (it keeps retrying; nothing drops it), and each file in
    ``pending/`` that does not read as a waiting answer. ``engine`` is
    ``miner.engine``: under ``digest`` (a rollback) nothing drains, so
    waiting answers are a WARN of their own. Reads only."""
    answers, broken = load_all(miner_dir)
    items = sum(len(a.waiting()) for a in answers)
    rows = [Row("OK", "waiting-answers", f"{len(answers)} waiting answer(s), {items} item(s) still to land")]
    if answers and engine != "session":
        rows.append(Row(
            "WARN", "waiting-answers-stranded",
            f"{len(answers)} waiting answer(s) ({items} item(s)) and miner.engine is {engine}: they land only "
            "when the session engine runs",
        ))
    for name in broken:
        rows.append(Row("WARN", "waiting-answer-unreadable",
                        f"{PENDING_DIR}/{name} does not read as a waiting answer; it is left in place"))
    for st in stuck_items(answers):
        rows.append(Row(
            "WARN", "waiting-item-stuck",
            f"{st.kind} item {st.origin} (session {st.session}) failed to land on {st.failures} runs; "
            f"it is tried again every run — last error: {st.error or 'none recorded'}",
        ))
    return rows
