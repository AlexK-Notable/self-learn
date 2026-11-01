"""What self-learn puts in front of the user: the inbox's items (attention
round, design r2 §1, §3.1, §3.5; contracts §4.1, §4.2, §4.4).

Every way self-learn reaches the user is one **item** in one of three
classes: NEEDS YOU (only the user can supply it: a login, sudo, money, a
change to their system, another repo's history, a conflict between two of
their statements, self-learn broken past its own repair -- the user's
answer 2, closed), DECIDED FOR YOU (self-learn acted; look when you like,
undo where an undo exists), or SILENT (machinery, never shown). An
**approved** item is a needs-you change the user approved that is not done
yet.

Code classifies every fixed event kind from one table, :data:`KINDS`. The
overseer classifies its own asks (``needs``/``because``, §3.8); this module
only reads them. ``attention.class.<kind-key>`` (tier A, set by a "didn't
need me" click, answer 7) moves a code kind to another class.

:func:`read` builds the ``self-learn attention --json`` document from file
reads only: no git, no model call, no ledger write. Its only subprocess is
one bounded ``systemctl --user is-active``, and only when the host unit is
installed and its heartbeat is stale. Its only writes are cache files
(:func:`mark_seen`'s ``seen.json``, the registration snapshot).

Item ids are ``att-`` plus 12 hex of ``sha256(kind + "\\0" + subject)``
(:func:`item_id`). The subject never holds text the overseer may reword, so
an id is stable across reads and across an ask's text changes; hold and
broken subjects carry the episode start, so a new episode is a new item.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import settings
from .invocation import failure_class
from .primitives import chrono, fsops

__all__ = [
    "ASK_KEYS",
    "CLASSES",
    "KEY_ORDER",
    "KINDS",
    "KindRow",
    "VERSION",
    "cache_dir",
    "classify",
    "collect",
    "find",
    "item_id",
    "mark_seen",
    "read",
    "seen_path",
]

VERSION = 2
CLASSES = ("needs-you", "decided", "approved")
#: The needs-you keys in the order the inbox lists them (§2.1 item 1).
KEY_ORDER = (
    "credentials", "broken", "money", "sudo", "conflict", "system-change", "foreign-history",
)
#: The keys the overseer may give its own asks (`credentials` and `broken`
#: are code's, §3.8).
ASK_KEYS = ("system-change", "foreign-history", "conflict", "money", "sudo")
#: The key in words, for the tooltip and the packet's `why_you`.
KEY_WORDS = {
    "credentials": "log in",
    "broken": "self-learn is broken",
    "money": "spending money",
    "sudo": "a sudo step",
    "conflict": "two of your statements disagree",
    "system-change": "a change to your system",
    "foreign-history": "another repository's history",
}
#: Why each key needs the user, in plain words (the packet's `why_you`).
KEY_WHY = {
    "credentials": "Only you can log in to Claude.",
    "broken": "self-learn stopped and its own repair has not fixed it.",
    "money": "It would spend real money, and you decide every spend.",
    "sudo": "It needs root, and only you run sudo.",
    "conflict": "Two of your own recorded statements disagree, and choosing silently would "
    "overrule you with your own words.",
    "system-change": "It changes how your computer or tools behave, outside self-learn.",
    "foreign-history": "It writes into another repository's git history, which is hard to "
    "undo and visible to others.",
}

DECIDED_WINDOW_DAYS = 30
SOURCE_BUDGET_SECS = 0.5
SYSTEMCTL_TIMEOUT_SECS = 1.0
HEARTBEAT_BROKEN_SECS = 15 * 60
STOPPED_BROKEN_SECS = 24 * 60 * 60
JOB_BROKEN_SECS = 72 * 60 * 60
CLAIM_TTL_SECS = 2 * 60 * 60
_TAIL_BYTES = 262144
HOST_UNIT = "self-learn-host.service"


# ------------------------------------------------------------------ the table


def _option(
    id_: str, label: str, effect: str, *, via: str, recommended: bool = False,
    confirm: bool = False, note: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id_, "label": label, "effect": effect, "confirm": confirm, "note": note,
        "recommended": recommended, "via": via,
    }


#: §3.4.8: the code-written plan a `broken.stopped` "Have an agent look at
#: it" click carries out in a session the user can see.
PLAN_BROKEN_STOPPED: dict[str, Any] = {
    "summary": "Look at the stopped ledger transaction, decide from what it shows, and clear "
    "it only after inspecting it.",
    "cwd": None,
    "checks": [
        {"say": "The intent is still STOPPED (self-learn reconcile lists it)",
         "command": "self-learn reconcile"},
    ],
    "steps": [
        {"say": "Read what self-learn reconcile prints for the intent, and the files it names; "
         "decide from that whether its writes should stand", "command": "self-learn reconcile",
         "sudo": False},
        {"say": "Only after inspecting it, clear the intent",
         "command": "self-learn reconcile --clear-intent <intent id>", "sudo": False},
        {"say": "Report what you found and what you did", "command": None, "sudo": False},
    ],
    "files": [],
    "sudo": False,
    "money": False,
    "conditions": None,
    "written_at": None,
    "by": "code",
}

#: §3.4.8: the code-written plan for `broken.job`.
PLAN_BROKEN_JOB: dict[str, Any] = {
    "summary": "Find why the job keeps failing and cure the cause inside self-learn.",
    "cwd": None,
    "checks": [
        {"say": "The job still has no completed run since the failures began",
         "command": "self-learn status --json --fast"},
    ],
    "steps": [
        {"say": "Read the job's journal and its last failure (self-learn doctor invocation, "
         "the journal under self-learn's cache)", "command": "self-learn doctor invocation",
         "sudo": False},
        {"say": "Cure the cause inside self-learn's code or configuration; never by "
         "hand-maintaining the ledger (fix self-learn so it does it unaided)", "command": None,
         "sudo": False},
        {"say": "Report what the cause was and what you changed", "command": None, "sudo": False},
    ],
    "files": [],
    "sudo": False,
    "money": False,
    "conditions": None,
    "written_at": None,
    "by": "code",
}

_AGENT_OPTION = _option(
    "opt-agent", "Have an agent look at it", "approve", via="answer", recommended=True,
)


@dataclass(frozen=True)
class KindRow:
    """One row of the kind table (contract §4.2)."""

    klass: str
    because: str | None
    flagged: bool = False
    popup: bool = False
    subject: str = ""
    ends: str = "–"
    undo: dict[str, Any] | None = None
    options: tuple[dict[str, Any], ...] = ()
    plan: dict[str, Any] | None = field(default=None, hash=False, compare=False)


_ASK_ENDS = "answered (§3.8's rule) or withdrawn"
KINDS: dict[str, KindRow] = {
    "hold.credentials": KindRow(
        "needs-you", "credentials", popup=True, subject="credentials@<episode start>",
        ends="a later model call on any surface succeeded, or login-ok.json is newer than the hold",
        options=(
            _option("opt-login", "Open a login terminal", "other", via="run --login",
                    recommended=True),
            _option("opt-check", "Check now", "other", via="check-login"),
        ),
    ),
    "hold.money": KindRow(
        "needs-you", "money", subject="money@<episode start>", ends="the same",
        options=(_option("opt-check", "Check now", "other", via="check-login"),),
    ),
    "broken.host": KindRow(
        "needs-you", "broken", subject="host@<episode start>", ends="heartbeat fresh again",
        options=(_option("opt-restart", "Restart self-learn", "other", via="fix",
                         recommended=True),),
    ),
    "broken.stopped": KindRow(
        "needs-you", "broken", subject="intent id", ends="intent cleared",
        options=(_AGENT_OPTION,), plan=PLAN_BROKEN_STOPPED,
    ),
    "broken.job": KindRow(
        "needs-you", "broken", subject="job:<steward|overseer|miner>@<episode start>",
        ends="a completed run", options=(_AGENT_OPTION,), plan=PLAN_BROKEN_JOB,
    ),
    "conflict.case-tampered": KindRow(
        "needs-you", "conflict", subject="case id",
        ends="case refreeze ran, or the case was superseded",
        options=(
            _option("opt-keep", "I edited it on purpose: keep my edit", "other",
                    via="refreeze --keep"),
            _option("opt-restore", "I didn't: restore it", "other", via="refreeze --restore"),
        ),
    ),
    **{
        f"ask.{key}": KindRow("needs-you", key, subject="question id", ends=_ASK_ENDS)
        for key in ASK_KEYS
    },
    "approved.pending": KindRow(
        "approved", None, subject="the ask's subject", ends="outcome row, or withdrawal",
    ),
    "decided.overseer-run": KindRow("decided", None, flagged=True, subject="run id"),
    "decided.steward-run": KindRow("decided", None, subject="run id"),
    "decided.always-loaded": KindRow("decided", None, flagged=True, subject="case id"),
    "decided.hook-activated": KindRow(
        "decided", None, flagged=True, subject="record id + activation time",
        undo={"label": "Turn it off", "redo_label": "Turn it back on"},
    ),
    "decided.ask-default": KindRow("decided", None, subject="question id + run id"),
    "decided.reading": KindRow("decided", None, subject="um-…@r<n>"),
    "decided.grant-use": KindRow(
        "decided", None, subject="the grant-use row id (gu-…)",
        undo={"label": "Undo it", "redo_label": "Do it again"},
    ),
    "decided.registration": KindRow(
        "decided", None, subject="path + at",
        undo={"label": "Remove the registration", "redo_label": "Register it again (plain)"},
    ),
    "decided.skill": KindRow(
        "decided", None, subject="skill + action + at",
        undo={"label": "Undo it", "redo_label": None},
    ),
    "decided.notice": KindRow("decided", None, subject="notice id"),
    "decided.withdrawn": KindRow(
        "decided", None, subject="question id",
        undo={"label": "Ask me anyway", "redo_label": None},
    ),
    "decided.approved-done": KindRow("decided", None, flagged=True, subject="the ask's subject"),
    "decided.ledger-paths": KindRow(
        "decided", None, subject="sorted path set hash", ends="paths committed",
    ),
}


def item_id(kind: str, subject: str) -> str:
    """``att-`` plus the first 12 hex of ``sha256(kind + "\\0" + subject)``."""
    digest = hashlib.sha256(f"{kind}\0{subject}".encode("utf-8")).hexdigest()
    return f"att-{digest[:12]}"


def classify(row: dict) -> tuple[str, str | None]:
    """The kind and key of one overseer ask row (§3.8, legacy inference
    included): ``needs: user`` with a valid ``because`` is ``ask.<because>``;
    with none, ``system: true`` reads as ``system-change`` and ``register``
    as ``foreign-history``; anything else (``needs: stead``, or a ``user``
    ask whose ``because`` is not one of :data:`ASK_KEYS`) is decided in the
    user's stead: ``decided.ask-default``."""
    needs = row.get("needs")
    because = row.get("because")
    if needs is None:
        if row.get("system"):
            needs, because = "user", "system-change"
        elif row.get("register"):
            needs, because = "user", "foreign-history"
        else:
            needs = "stead"
    if needs == "user" and because in ASK_KEYS:
        return f"ask.{because}", because
    return "decided.ask-default", None


# ------------------------------------------------------------------ the cache


def cache_dir(home: Path | str) -> Path:
    """The per-home cache directory, without creating it."""
    from . import serve  # lazy: serve imports most of the package

    return serve.cache_dir_readonly(Path(home))


def seen_path(home: Path | str) -> Path:
    return cache_dir(home) / "attention" / "seen.json"


def _read_seen(home: Path | str) -> dict[str, str]:
    """``{item id: the updated_at seen}``; empty when the file is missing or
    corrupt (a lost cache only shows items once more)."""
    try:
        data = json.loads(seen_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    seen = data.get("seen") if isinstance(data, dict) else None
    if not isinstance(seen, dict):
        return {}
    return {str(k): str(v) for k, v in seen.items() if isinstance(v, str)}


def _write_seen(home: Path | str, seen: dict[str, str]) -> None:
    """``<cache>/attention/seen.json``: cache only, never ledger truth."""
    target = seen_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(target, json.dumps({"seen": seen}, sort_keys=True) + "\n", fsync=False)


def mark_seen(
    home: Path | str, ids: list[str] | None = None, *, all_decided: bool = False
) -> tuple[list[str], list[str]]:
    """Mark items seen at their current ``updated_at``. Returns ``(marked,
    unknown)``. Seen only clears the "new" dot; it never takes a needs-you
    item out of the count (§3.5)."""
    items = {item["id"]: item for item in collect(home, all_items=True)}
    seen = _read_seen(home)
    marked: list[str] = []
    unknown: list[str] = []
    wanted = list(ids or [])
    if all_decided:
        wanted += [i for i, item in items.items() if item["class"] == "decided"]
    for wanted_id in dict.fromkeys(wanted):
        item = items.get(wanted_id)
        if item is None:
            unknown.append(wanted_id)
            continue
        seen[wanted_id] = str(item.get("updated_at") or "")
        marked.append(wanted_id)
    if marked:
        _write_seen(home, seen)
    return marked, unknown


# ------------------------------------------------------------------ small readers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return chrono.now_iso(value)


def _dt(value: object) -> datetime | None:
    return chrono.to_dt(value)


def _tail_jsonl(path: Path, limit: int = _TAIL_BYTES) -> list[dict]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _jsonl(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _yaml(path: Path) -> Any:
    from ruamel.yaml import YAML

    try:
        return YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- an unreadable file is no items, never a crash
        return None


def _mtime_iso(path: Path) -> str | None:
    try:
        return _iso(datetime.fromtimestamp(int(path.stat().st_mtime), tz=timezone.utc))
    except OSError:
        return None


def _first_line(text: object, limit: int = 140) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _within(at: object, days: int, now: datetime) -> bool:
    when = _dt(at)
    return when is not None and now - when <= timedelta(days=days)


# ------------------------------------------------------------------ item builder


def _new_item(
    kind: str,
    subject: str,
    *,
    title: str,
    since: str | None,
    updated_at: str | None = None,
    by: str = "code",
    run: str | None = None,
    report: str | None = None,
    refs: list[str] | None = None,
    meanwhile: str | None = None,
    state: str | None = None,
    because: str | None = None,
    options: list[dict] | None = None,
    **private: Any,
) -> dict[str, Any]:
    """One item: the §4.1 fields, plus private ``_``-prefixed fields the
    packet builder reads (never printed by :func:`read`). A decided item's
    state is ``done`` (``withdrawn`` for a withdrawal), a needs-you item's
    ``open``, unless given."""
    row = KINDS[kind]
    if state is None:
        state = (
            "withdrawn" if kind == "decided.withdrawn"
            else "done" if row.klass == "decided" else "open"
        )
    item: dict[str, Any] = {
        "id": item_id(kind, subject),
        "class": row.klass,
        "kind": kind,
        "because": because if because is not None else row.because,
        "subject": subject,
        "title": title,
        "meanwhile": meanwhile,
        "state": state,
        "flagged": row.flagged,
        "seen": False,
        "partial": False,
        "since": since,
        "updated_at": updated_at or since,
        "source": {"by": by, "run": run, "report": report},
        "refs": list(refs or []),
        "options": [dict(o) for o in (options if options is not None else row.options)],
        "undo": (
            {"label": row.undo["label"], "redo_label": row.undo.get("redo_label"), "redo": False}
            if row.undo else None
        ),
        "conversation": {"turns": 0, "last_at": None},
        "answer": None,
        "run": None,
    }
    for key, value in private.items():
        item[f"_{key}"] = value
    return item


# ------------------------------------------------------------------ sources


def _load_questions(home: Path) -> list[dict]:
    """The overseer's committed index of open questions, through the
    overseer's own loader (which validates every row). Monkeypatched by
    tests with r2 §4.5 rows."""
    from .overseer import conversation

    return conversation._load_questions(home)  # noqa: SLF001


def _withdrawn(home: Path) -> list[dict]:
    data = _yaml(home / "overseer" / "withdrawn.yaml")
    rows = data.get("withdrawn") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)] if isinstance(
        rows, list) else []


def _statements(home: Path) -> list[dict]:
    from . import statements

    try:
        return statements.list_statements(home)
    except (OSError, ValueError):
        return []


def _choices(home: Path) -> list[dict]:
    return _jsonl(home / "attention" / "choices.jsonl")


def _outcomes(home: Path) -> list[dict]:
    return _jsonl(home / "attention" / "outcomes.jsonl")


def _plan_has_sudo(plan: object) -> bool:
    steps = plan.get("steps") if isinstance(plan, dict) else None
    return isinstance(steps, list) and any(
        isinstance(step, dict) and step.get("sudo") is True for step in steps
    )


def _answer_of(statement: dict | None, choice: dict | None) -> dict | None:
    """The §4.1 ``answer`` object for the latest statement and/or choice."""
    if statement is None and choice is None:
        return None
    latest = max(
        [r for r in (statement, choice) if r is not None], key=lambda r: str(r.get("at") or "")
    )
    if latest is choice and choice is not None:
        how = str(choice.get("how") or "clicked")
        label = choice.get("label") or choice.get("option")
        summary = (
            f"chose «{label}»" if how == "clicked" and label
            else f"the agent's draft, {'accepted' if how == 'draft-accepted' else 'edited and sent'} by you"
            if how.startswith("draft-") else how
        )
        return {
            "at": choice.get("at"), "how": how, "summary": summary,
            "statement": choice.get("statement"), "choice": choice.get("id"),
        }
    assert statement is not None
    # Gate r1 MINOR 4: a statement an agent recorded (with a `transcript:`
    # ref, design r2 §3.4.1) is the person's words relayed by the agent,
    # never "typed" here.
    return {
        "at": statement.get("at"),
        "how": "relayed" if statement.get("recorded_by") == "agent" else "typed",
        "summary": _first_line(statement.get("verbatim"), 200),
        "statement": statement.get("id"), "choice": None,
    }


def _matches(row: dict, refs: set[str]) -> bool:
    answers = row.get("answers")
    return isinstance(answers, dict) and answers.get("ref") in refs


def _claim(home: Path, approved_id: str, now: datetime) -> dict | None:
    try:
        data = json.loads(
            (cache_dir(home) / "attention" / "claims" / f"{approved_id}.json").read_text("utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    at = _dt(data.get("at"))
    if at is None or (now - at).total_seconds() > CLAIM_TTL_SECS:
        return None
    return data


def _run_record(home: Path, approved_id: str) -> dict | None:
    try:
        data = json.loads(
            (cache_dir(home) / "attention" / "runs" / f"{approved_id}.json").read_text("utf-8")
        )
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _counts_from(row: dict, since: datetime | None) -> bool:
    """Whether the choice or outcome *row* counts against the floor *since*
    (``None``: every row counts). A row with no readable time counts only
    when there is no floor."""
    if since is None:
        return True
    when = _dt(row.get("at"))
    return when is not None and when >= since


def _ask_answer_floor(row: dict, index_floor: str | None) -> datetime | None:
    """From when an answer, a choice or an outcome counts for the ask *row*:
    its `reopened_at` when "Ask me anyway" put it back, else its `asked_at`,
    else the index's last write. The same floor as the overseer's own walk
    (`overseer.conversation._answer_floor`), so the inbox and the runner
    agree on a reopened ask (integration of the 2026-10-31c round, the
    overseer-asks gate r3 cross-lane item): a withdrawn approval comes back
    as a question, not as "Being carried out", and a click made before the
    reopen is no longer shown as its answer."""
    for key in ("reopened_at", "asked_at"):
        when = _dt(row.get(key)) if isinstance(row.get(key), str) else None
        if when is not None:
            return when
    return _dt(index_floor)


def _approval_track(
    home: Path, base: dict, plan: dict | None, choices: list[dict], outcomes: list[dict],
    now: datetime, *, since: datetime | None = None,
) -> list[dict]:
    """The needs-you item *base* (an ask with a plan, or a code item with an
    agent option) after its choices and outcomes (§1.3, §3.4.7): the item
    as it stands (open, awaiting-sudo), or the approved item that replaced
    it, or the done item, or nothing (declined). Events are matched by the
    item's subject and taken in time order; a failed outcome returns the item
    to open and the approval no longer stands. With *since* (an ask's
    :func:`_ask_answer_floor`), only events at or after it count."""
    subject = base["subject"]
    events: list[tuple[str, str, dict]] = []
    for choice in choices:
        if (choice.get("subject") == subject or choice.get("item") == base["id"]) and _counts_from(
            choice, since
        ):
            events.append((str(choice.get("at") or ""), "choice", choice))
    for outcome in outcomes:
        if outcome.get("subject") == subject and _counts_from(outcome, since):
            events.append((str(outcome.get("at") or ""), "outcome", outcome))
    events.sort(key=lambda e: e[0])
    state = "open"
    approved_at: str | None = None
    conditions: str | None = None
    failed: dict | None = None
    done: dict | None = None
    last_choice: dict | None = None
    for _at, what, row in events:
        if what == "choice":
            last_choice = row
            how = row.get("how")
            effect = row.get("effect")
            if how == "ran-sudo":
                if state == "awaiting-sudo":
                    state = "approved"
                continue
            if effect == "approve":
                state = "awaiting-sudo" if _plan_has_sudo(plan) else "approved"
                approved_at = str(row.get("at") or "")
                conditions = row.get("text") if isinstance(row.get("text"), str) else None
                done = None
            elif effect in ("decline", "other", "register") and state in (
                "open", "awaiting-sudo", "approved",
            ):
                # answers lane, fix round 1 (gate r1 MAJOR 1): an approval
                # stays changeable until carried out (§0 call 3, §1.3); the
                # answer verb refuses a new answer while a live claim holds it.
                state = "answered"
        else:
            if row.get("result") == "done" and state == "approved":
                state, done = "done", row
            elif row.get("result") == "failed" and state == "approved":
                state, failed = "open", row
    answer = _answer_of(None, last_choice) if last_choice is not None else None
    if state == "answered":
        return []
    if state == "open" or state == "awaiting-sudo":
        out = dict(base)
        out["state"] = state
        if state == "awaiting-sudo":
            out["because"] = "sudo"
        if answer is not None:
            out["answer"] = answer
        if failed is not None:
            out["_failed"] = failed
            out["updated_at"] = failed.get("at") or out["updated_at"]
        return [out]
    title = base["title"]
    if state == "done":
        assert done is not None
        item = _new_item(
            "decided.approved-done", subject,
            title=f"Done by an agent: {_first_line(done.get('note') or title, 120)}",
            since=approved_at, updated_at=str(done.get("at") or approved_at), by="agent",
            refs=base["refs"], decided={
                "what": _first_line(done.get("note") or title, 400), "by": "agent",
                "at": done.get("at"), "because": "you approved it in the inbox",
                "changes_now": None,
            },
            plan=plan, question=base.get("_question"), source_item=base["id"],
        )
        item["answer"] = answer
        return [item]
    item = _new_item(
        "approved.pending", subject, title=title, since=approved_at or base["since"],
        updated_at=approved_at, by=base["source"]["by"], refs=base["refs"],
        meanwhile="You approved it; an agent carries it out in a terminal you can see.",
        state="approved", plan=plan, conditions=conditions, question=base.get("_question"),
        source_item=base["id"], why=base.get("_why"), evidence=base.get("_evidence", []),
    )
    item["answer"] = answer
    record = _run_record(home, item["id"])
    claim = _claim(home, item["id"], now)
    # Follow-ups 2 (gap 2): a launch the person stopped from the page
    # (`attention stop`) no longer counts as running.
    launched = (record is not None and str(record.get("at") or "") >= str(approved_at or "")
                and not record.get("stopped_at"))
    if launched or claim is not None:
        item["state"] = "running"
        item["run"] = {
            "unit": (record or {}).get("unit"), "at": (record or {}).get("at"),
            "claimed_by": (claim or {}).get("session"),
        }
    item["options"] = change_options(base.get("options") or [], record, claim)
    return [item]


#: Follow-ups 2 (gap 2): the page's "Stop it" on approved work a session
#: claimed in a terminal this page opened (`attention stop`).
STOP_OPTION_ID = "opt-stop"
STOP_LABEL = "Stop it"


def stoppable(record: dict | None, claim: dict | None) -> bool:
    """Whether ``attention stop`` may act on approved work: a live *claim*
    made at or after the page's own launch (*record*, not already
    stopped). A claim older than the launch, or one with no launch, is a
    session the page did not open (an agent the person approved it in);
    the page cannot stop that one."""
    if claim is None or record is None or record.get("stopped_at"):
        return False
    launched_at = _dt(record.get("at"))
    claimed_at = _dt(claim.get("at"))
    return launched_at is not None and claimed_at is not None and claimed_at >= launched_at


def change_options(options: list[dict], record: dict | None, claim: dict | None) -> list[dict]:
    """Follow-ups 2 (gap 2): the one-click changes of mind on approved
    work. The originally offered options other than an approval (decline,
    other), each answered by ``attention answer`` like the first click;
    while a session holds a live claim they are off (``disabled``, in
    words), since the answer verb refuses a new answer then, and ``Stop
    it`` is offered when the claiming session runs in the terminal this
    page opened (:func:`stoppable`). An approval is not repeated here:
    "Run it now" is the page's relaunch."""
    out = [dict(o) for o in options
           if isinstance(o, dict) and o.get("id") and o.get("effect") != "approve"]
    if claim is not None:
        session = claim.get("session")
        if stoppable(record, claim):
            reason = (f"a session ({session}) is carrying it out now and a different answer "
                      "cannot reach it; Stop it first")
        else:
            reason = (f"a session ({session}) that this page did not open is carrying it out "
                      "now; tell it in its own terminal")
        for option in out:
            option["disabled"] = reason
        if stoppable(record, claim):
            out.append(_option(STOP_OPTION_ID, STOP_LABEL, "other", via="stop", confirm=True))
    return out


def _src_asks(home: Path, ctx: "_Ctx") -> list[dict]:
    """Open questions from the overseer's index (§3.1), with their answers,
    approvals and withdrawals."""
    rows = _load_questions(home)
    index = home / "overseer" / "open-questions.yaml"
    floor = _mtime_iso(index)
    withdrawn = {row["id"] for row in ctx.withdrawn}
    statements = ctx.statements
    choices = ctx.choices
    out: list[dict] = []
    for row in rows:
        q_id = row.get("id")
        if not isinstance(q_id, str) or q_id in withdrawn:
            continue
        if row.get("kind") == "reading":
            out.extend(_reading_item(home, row, floor))
            continue
        if row.get("kind") != "ask":
            continue
        kind, key = classify(row)
        asked_at = row.get("asked_at") if isinstance(row.get("asked_at"), str) else floor
        refs_answering = {q_id}
        if key == "conflict" and isinstance(row.get("statements"), list) and len(row["statements"]) == 2:
            refs_answering.add(f"conflict:{row['statements'][0]}+{row['statements'][1]}")
        floor_dt = _ask_answer_floor(row, floor)
        said = [
            s for s in statements if _matches(s, refs_answering)
            and (floor_dt is None or (_dt(s.get("at")) or floor_dt) >= floor_dt)
        ]
        chose = [
            c for c in choices
            if (_matches(c, refs_answering) or c.get("subject") == q_id) and _counts_from(c, floor_dt)
        ]
        latest_said = max(said, key=lambda r: str(r.get("at") or ""), default=None)
        latest_chose = max(chose, key=lambda r: str(r.get("at") or ""), default=None)
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else None
        options = [
            {
                "id": o.get("id"), "label": o.get("label"), "effect": o.get("effect", "other"),
                "confirm": bool(o.get("confirm", False)),
                "note": "required" if o.get("note") == "required" else None,
                "recommended": bool(
                    isinstance(row.get("recommend"), dict)
                    and row["recommend"].get("option") == o.get("id")
                ),
                "via": "answer",
            }
            for o in (row.get("options") or []) if isinstance(o, dict) and o.get("id")
        ]
        cases = [c for c in row.get("cases") or [] if isinstance(c, str)]
        stmt_refs = [s for s in row.get("statements") or [] if isinstance(s, str)]
        common: dict[str, Any] = dict(
            title=_first_line(row.get("text"), 200), since=asked_at, by="overseer",
            refs=[q_id, *cases, *stmt_refs], options=options,
            question=row.get("text"), why=row.get("why"), plan=plan,
            recommend=row.get("recommend"), look_at=row.get("look_at") or [],
            ask=row,
        )
        if kind == "decided.ask-default":
            default = row.get("default")
            item = _new_item(
                kind, q_id, meanwhile=default if isinstance(default, str) else
                "No default was recorded; the overseer reads your answer on its next run.",
                decided={
                    "what": default or "nothing was decided yet", "by": "overseer",
                    "at": asked_at, "because": row.get("why"), "changes_now": default,
                },
                **common,
            )
            item["answer"] = _answer_of(latest_said, latest_chose)
            # An ask in the current index is current: with no date of its
            # own it is as new as this read.
            item["updated_at"] = (item["answer"] or {}).get("at") or asked_at or _iso(ctx.now)
            out.append(item)
            continue
        default = row.get("default")
        meanwhile = default if isinstance(default, str) and default.strip() else (
            "The newer statement holds until you say otherwise." if key == "conflict"
            else "Nothing is done until you answer."
        )
        item = _new_item(kind, q_id, meanwhile=meanwhile, **common)
        has_plan = plan is not None
        if has_plan:
            # Only an option click decides an item with a plan (§1.3).
            produced = _approval_track(
                home, item, plan, choices, ctx.outcomes, ctx.now, since=floor_dt,
            )
            for still_open in produced:
                if still_open.get("kind") == kind and still_open.get("answer") is None and latest_said:
                    # Words alone are recorded, and the item stays open.
                    still_open["answer"] = _answer_of(latest_said, None)
            out.extend(produced)
            continue
        if latest_said is not None or latest_chose is not None:
            continue  # answered: closed
        out.append(item)
    return out


def _reading_item(home: Path, row: dict, floor: str | None) -> list[dict]:
    reading = str(row.get("id"))
    title = f"A reading of you: {reading}"
    try:
        from . import user_model

        entry_id = reading.split("@", 1)[0]
        _fm, containers = user_model._load(home)  # noqa: SLF001
        entry = next(
            (e for rows in containers.values() for e in rows if e.get("id") == entry_id), None
        )
        if isinstance(entry, dict) and entry.get("title"):
            title = f"A reading of you: {_first_line(entry['title'], 160)}"
    except Exception:  # noqa: BLE001 -- a title is a courtesy
        pass
    return [_new_item(
        "decided.reading", reading, title=title, since=floor, by="overseer",
        refs=[reading, *[c for c in row.get("cases") or [] if isinstance(c, str)]],
        meanwhile="The overseer acts on this reading; correct it in your own words if it is wrong.",
        decided={"what": title, "by": "overseer", "at": floor, "because": None,
                 "changes_now": None},
    )]


def _src_withdrawn(home: Path, ctx: "_Ctx") -> list[dict]:
    out: list[dict] = []
    for row in ctx.withdrawn:
        at = row.get("withdrawn_at") or row.get("asked_at")
        if not ctx.all_items and not _within(at, DECIDED_WINDOW_DAYS, ctx.now):
            continue
        out.append(_new_item(
            "decided.withdrawn", row["id"],
            title=f"I stopped asking: {_first_line(row.get('text'), 160)}",
            since=row.get("asked_at"), updated_at=at, by="overseer", run=row.get("run"),
            refs=[row["id"], *[c for c in row.get("cases") or [] if isinstance(c, str)]],
            meanwhile=_first_line(row.get("why"), 300) or None,
            decided={"what": f"withdrew the question: {row.get('text')}", "by": "overseer",
                     "at": at, "because": row.get("why"), "changes_now": None},
            question=row.get("text"),
        ))
    return out


# -- holds and broken


def _hold_events(home: Path, cache: Path) -> list[tuple[str, str, str, str]]:
    """``(at, surface, "held"|"ok", cause)`` from the runners' journals and
    ``login-ok.json``."""
    events: list[tuple[str, str, str, str]] = []
    for row in _tail_jsonl(cache / "steward" / "journal.jsonl"):
        if row.get("dry_run"):
            continue
        at = str(row.get("ts") or "")
        status = row.get("status")
        if status == "held-environment":
            events.append((at, "steward", "held", str(row.get("cause") or "")))
        elif status in ("applied", "partial", "refused", "stopped") and "decided" in row and not row.get("held"):
            events.append((at, "steward", "ok", ""))
    for row in _tail_jsonl(cache / "overseer.journal"):
        if row.get("dry_run"):
            continue
        at = str(row.get("at") or "")
        status = str(row.get("status") or "")
        if status == "held-environment":
            events.append((at, "overseer", "held", str(row.get("cause") or "")))
        elif status.endswith("-returned") and row.get("ok") is True:
            events.append((at, "overseer", "ok", ""))
    for row in _tail_jsonl(cache / "miner" / "journal.jsonl"):
        at = str(row.get("ts") or "")
        status = row.get("status")
        if status == "failed" and failure_class.hold_fix(str(row.get("reason") or "")):
            events.append((at, "miner", "held", str(row.get("reason") or "")))
        elif status == "ok" and (row.get("sessions_called") or row.get("sessions_scanned")):
            events.append((at, "miner", "ok", ""))
    try:
        login = json.loads((cache / "attention" / "login-ok.json").read_text("utf-8"))
        if isinstance(login, dict) and isinstance(login.get("at"), str):
            events.append((login["at"], "ask", "ok", ""))
    except (OSError, ValueError):
        pass
    events.sort(key=lambda e: e[0])
    return events


def _hold_key(cause: str) -> str | None:
    fix = failure_class.hold_fix(cause)
    if fix in (failure_class.LOGIN_FIX, failure_class.API_KEY_FIX):
        return "credentials"
    if fix is not None and "credit" in fix:
        return "money"
    return None


def _src_holds(home: Path, ctx: "_Ctx") -> list[dict]:
    """``hold.credentials`` / ``hold.money``: the current episode, if any.
    An episode starts at the first held row of its key after the last
    success on any surface, and ends at the next success (§4.2)."""
    episodes: dict[str, dict[str, Any]] = {}
    for at, surface, what, cause in _hold_events(home, ctx.cache):
        if what == "ok":
            episodes.clear()
            continue
        key = _hold_key(cause)
        if key is None:
            continue
        episode = episodes.setdefault(key, {"start": at, "surfaces": [], "cause": cause, "at": at})
        if surface not in episode["surfaces"]:
            episode["surfaces"].append(surface)
        episode["cause"], episode["at"] = cause, at
    out: list[dict] = []
    for key, episode in episodes.items():
        kind = f"hold.{key}"
        fix = failure_class.hold_fix(episode["cause"])
        held = ", ".join(episode["surfaces"])
        title = (
            "Log in to Claude: self-learn can't use the model" if key == "credentials"
            else "self-learn's model calls are held: the account needs credit"
        )
        options = [dict(o) for o in KINDS[kind].options]
        if key == "money":
            reason = _billing_reason()
            for option in options:
                option["disabled"] = reason
        out.append(_new_item(
            kind, f"{key}@{episode['start']}", title=title, since=episode["start"],
            updated_at=episode["at"], options=options,
            meanwhile=f"Held: the {held} job(s). Each retries on its schedule; nothing is lost.",
            hold={"surfaces": episode["surfaces"], "cause": episode["cause"], "fix": fix,
                  "since": episode["start"], "held": f"the {held} job(s) wait for this"},
            why=episode["cause"],
        ))
    return out


def _billing_reason() -> str | None:
    """The ask lane's ``ask.billing_route`` over this process's environment,
    when that module is present: why "Check now" would bill money."""
    import importlib

    try:
        module = importlib.import_module("self_learn.ask")
    except ImportError:
        return None
    route = getattr(module, "billing_route", None)
    if not callable(route):
        return None
    try:
        result = route(dict(os.environ))
    except Exception:  # noqa: BLE001 -- a disabled-reason is a courtesy
        return None
    return result if isinstance(result, str) else None


def _systemctl_active(unit: str) -> bool | None:
    """``systemctl --user is-active <unit>``, bounded; ``None`` when it
    cannot be asked."""
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit], capture_output=True, text=True,
            timeout=SYSTEMCTL_TIMEOUT_SECS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() == "active"


def _src_broken(home: Path, ctx: "_Ctx") -> list[dict]:
    from . import serve

    out: list[dict] = []
    # broken.host: the heartbeat stale past the bound while the unit is not
    # active (systemd gave up). Asked only when the unit is installed.
    if serve.is_configured(HOST_UNIT):
        record = serve.read_heartbeat(ctx.cache)
        age = serve.heartbeat_age_secs(ctx.cache)
        if age is None or age > HEARTBEAT_BROKEN_SECS:
            active = _systemctl_active(HOST_UNIT)
            if active is False:
                ts = (record or {}).get("ts")
                start = (
                    _iso(datetime.fromtimestamp(float(ts), tz=timezone.utc))
                    if isinstance(ts, (int, float)) else "never"
                )
                out.append(_new_item(
                    "broken.host", f"host@{start}",
                    title="self-learn's host service has stopped",
                    since=None if start == "never" else start,
                    meanwhile="No nightly job runs until it is back; nothing is lost.",
                    why=f"{HOST_UNIT} is not active and its heartbeat is "
                    + ("missing" if age is None else f"{int(age // 60)} minutes old"),
                    facts=[{"label": "heartbeat age (s)", "value": None if age is None else int(age)}],
                ))
    # broken.stopped: a STOPPED intent older than the bound. Read straight
    # from `.intents/` (intents.classify_status runs git for the lock path).
    intents_dir = home / ".intents"
    try:
        files = sorted(intents_dir.glob("*.json")) if intents_dir.is_dir() else []
    except OSError:
        files = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stopped = data.get("stopped") if isinstance(data, dict) else None
        if not isinstance(stopped, dict):
            continue
        started = _dt(data.get("started"))
        if started is not None and (ctx.now - started).total_seconds() < STOPPED_BROKEN_SECS:
            continue
        intent_id = str(data.get("id") or path.stem)
        base = _new_item(
            "broken.stopped", intent_id,
            title="A ledger write stopped half-way and self-learn could not repair it",
            since=data.get("started"), updated_at=stopped.get("at"),
            meanwhile="Every ledger write waits until the intent is cleared; nothing is lost.",
            why=_first_line(stopped.get("reason"), 400),
            plan=_plan_for(PLAN_BROKEN_STOPPED, intent_id),
            facts=[{"label": "intent", "value": intent_id},
                   {"label": "operation", "value": data.get("op")},
                   {"label": "commit", "value": data.get("commit_subject")}],
        )
        out.extend(_approval_track(home, base, base["_plan"], ctx.choices, ctx.outcomes, ctx.now))
    out.extend(_broken_jobs(home, ctx, {i["kind"] for i in ctx.holds}))
    return out


def _plan_for(plan: dict, subject: str) -> dict:
    out = json.loads(json.dumps(plan))
    for step in out.get("steps", []):
        if isinstance(step.get("command"), str):
            step["command"] = step["command"].replace("<intent id>", subject)
    return out


_JOB_FAILURES = frozenset({
    "due-check-error", "crashed", "failed", "stopped", "dirty-refused", "partial-handler-error",
    "a-incomplete", "phase-s-failed",
})


def _broken_jobs(home: Path, ctx: "_Ctx", hold_kinds: set[str]) -> list[dict]:
    """``broken.job``: a job with no completed run for the bound and failures
    since its last one, and no hold cause (a hold is `credentials`/`money`
    instead)."""
    if hold_kinds:
        return []
    journals = {
        "steward": (ctx.cache / "steward" / "journal.jsonl", "ts"),
        "overseer": (ctx.cache / "overseer.journal", "at"),
        "miner": (ctx.cache / "miner" / "journal.jsonl", "ts"),
    }
    out: list[dict] = []
    for job, (path, key) in journals.items():
        rows = [r for r in _tail_jsonl(path) if not r.get("dry_run")]
        if not rows:
            continue
        last_done: str | None = None
        for row in rows:
            status = row.get("status")
            done = (
                (job == "steward" and "decided" in row and status != "held-environment")
                or (job == "overseer" and status in ("complete", "closed"))
                or (job == "miner" and status == "ok")
            )
            if done:
                last_done = str(row.get(key) or "")
        failures = [
            r for r in rows if r.get("status") in _JOB_FAILURES
            and str(r.get(key) or "") > (last_done or "")
        ]
        if not failures:
            continue
        last_dt = _dt(last_done)
        if last_dt is not None and (ctx.now - last_dt).total_seconds() < JOB_BROKEN_SECS:
            continue
        first = str(failures[0].get(key) or "")
        last = failures[-1]
        reason = last.get("reason") or last.get("error") or last.get("status")
        subject = f"job:{job}@{first}"
        base = _new_item(
            "broken.job", subject, title=f"The {job} job keeps failing",
            since=first, updated_at=str(last.get(key) or first),
            meanwhile="It retries on its schedule; lessons wait meanwhile, nothing is lost.",
            why=_first_line(reason, 400), plan=_plan_for(PLAN_BROKEN_JOB, subject),
            facts=[{"label": "last completed run", "value": last_done},
                   {"label": "failures since", "value": len(failures)},
                   {"label": "journal", "value": str(path)}],
        )
        out.extend(_approval_track(home, base, base["_plan"], ctx.choices, ctx.outcomes, ctx.now))
    return out


def _src_tampered(home: Path, ctx: "_Ctx") -> list[dict]:
    from . import cases

    out: list[dict] = []
    for row in cases.tampered_parked(home):
        case_id = str(row.get("case"))
        out.append(_new_item(
            "conflict.case-tampered", case_id,
            title="A parked case file was edited by hand after it was decided",
            since=row.get("opened_at"), refs=[case_id, *(row.get("records") or [])],
            meanwhile="Its lessons are held: nobody decides them until you say whether the edit was meant.",
            why="Only the person who edited the file knows whether the edit was meant.",
            facts=[{"label": "case", "value": case_id}],
        ))
    return out


# -- run manifests


def _case_for_lesson(manifest: dict, lesson: str) -> str | None:
    cases = manifest.get("cases")
    if not isinstance(cases, dict):
        return None
    for case_id, data in cases.items():
        text = json.dumps(data) if not isinstance(data, str) else data
        if lesson in text:
            return str(case_id)
    return None


def _src_runs(home: Path, ctx: "_Ctx") -> list[dict]:
    """Decided items from the committed run manifests (``cases/runs/*.json``)
    completed in the window: one digest per run, and one item per
    ``attention_effects`` row that changed an always-loaded line or turned
    on a hook, whichever runner wrote it (answer 5)."""
    out: list[dict] = []
    runs_dir = home / "cases" / "runs"
    try:
        paths = sorted(runs_dir.glob("*.json"))
    except OSError:
        return out
    for path in paths:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        actor = manifest.get("actor")
        run_id = str(manifest.get("run_id") or path.stem)
        if actor == "steward":
            done_at = manifest.get("completed_at")
            if not done_at:
                continue
        elif actor == "overseer":
            if manifest.get("status") not in ("complete", "closed"):
                continue
            done_at = (
                manifest.get("progress_at") or manifest.get("last_attempt_at")
                or manifest.get("started")
            )
        else:
            continue
        if not ctx.all_items and not _within(done_at, DECIDED_WINDOW_DAYS, ctx.now):
            continue
        day = str(done_at)[:10]
        raw_decided = manifest.get("decided")
        decided: list[Any] = raw_decided if isinstance(raw_decided, list) else []
        if actor == "steward":
            title = f"Steward, {day}: decided {len(decided)} lesson(s)"
            kind = "decided.steward-run"
        else:
            title = f"The overseer's weekly run, {manifest.get('week') or day}"
            kind = "decided.overseer-run"
        # Gate r1 MAJOR 1: the run's cases hold the reasoning ("why was this
        # decided?"), so they lead; the packet expands each case into its
        # lessons and statements, and the decided lessons follow, deduped.
        recipes = manifest.get("cases")
        run_cases = [
            str(c) for c in (recipes if isinstance(recipes, dict) else {})
            if isinstance(c, str) and c.startswith("case-")
        ]
        refs = list(dict.fromkeys([*run_cases, *(str(d) for d in decided)]))
        out.append(_new_item(
            kind, run_id, title=title, since=manifest.get("started_at") or manifest.get("started"),
            updated_at=str(done_at), by=str(actor), run=run_id,
            report=str(manifest.get("date") or manifest.get("week") or "") or None,
            refs=refs[:50],
            decided={"what": title, "by": actor, "at": done_at,
                     "because": None, "changes_now": None},
            manifest_path=str(path),
        ))
        effects = manifest.get("attention_effects")
        for effect in effects if isinstance(effects, list) else []:
            if not isinstance(effect, dict) or not isinstance(effect.get("lesson"), str):
                continue
            lesson = effect["lesson"]
            at = str(effect.get("at") or done_at)
            case_id = _case_for_lesson(manifest, lesson)
            if effect.get("hook_activated"):
                out.append(_new_item(
                    "decided.hook-activated", f"{lesson}@{at}",
                    title=f"The {actor} turned on a hook for {lesson}", since=at, by=str(actor),
                    run=run_id, refs=[lesson, *([case_id] if case_id else [])],
                    meanwhile="The hook is active in every new Claude Code session.",
                    decided={"what": f"turned on the hook compiled from {lesson}", "by": actor,
                             "at": at, "because": None, "changes_now": "the hook runs on matching tool calls"},
                    lesson=lesson, case=case_id,
                ))
            if effect.get("always_loaded"):
                subject = case_id or lesson
                out.append(_new_item(
                    "decided.always-loaded", subject,
                    title=f"The {actor} changed a line every session loads ({lesson})",
                    since=at, by=str(actor), run=run_id,
                    refs=[lesson, *([case_id] if case_id else [])],
                    meanwhile="The line is in effect in every new session.",
                    decided={"what": f"{effect.get('verb')} {lesson}", "by": actor, "at": at,
                             "because": None, "changes_now": "every new session loads it"},
                    lesson=lesson, case=case_id,
                ))
    return out


def _src_grant_uses(home: Path, ctx: "_Ctx") -> list[dict]:
    from . import grant_uses

    out: list[dict] = []
    for row in grant_uses.read(home):
        at = row.get("at")
        if not ctx.all_items and not _within(at, DECIDED_WINDOW_DAYS, ctx.now):
            continue
        verb = str(row.get("verb") or "")
        args = [str(a) for a in row.get("args") or []]
        undo = _grant_use_undo(row)
        item = _new_item(
            "decided.grant-use", str(row["id"]),
            title=f"An agent ran `self-learn {verb} {' '.join(args)}`".rstrip() + " in your name",
            since=at, by="agent", refs=[r for r in (row.get("statement"), row.get("proof")) if r],
            meanwhile=_first_line(row.get("note"), 300) or None,
            decided={"what": f"self-learn {verb} {' '.join(args)}".strip(), "by": "agent",
                     "at": at, "because": row.get("note"), "changes_now": None},
            grant_use=row, undo_verb=undo,
        )
        if undo is None:
            item["undo"] = None
        out.append(item)
    return out


def _grant_use_undo(row: dict) -> list[str] | None:
    """The inverse verb of a grant use (§3.4.6), as argv after
    ``self-learn``; ``None`` when it has none."""
    verb = row.get("verb")
    args = [str(a) for a in row.get("args") or []]
    prior = row.get("prior")
    if verb == "host add" and args:
        return ["host", "remove", args[0], *(["--skills-root"] if "--skills-root" in args else
                                              ["--project"])]
    if verb == "host set-mode" and args and isinstance(prior, dict) and prior.get("mode"):
        return ["host", "set-mode", args[0], str(prior["mode"]),
                f"--{prior.get('kind') or 'project'}"]
    if verb in ("config set", "config unset") and args:
        if prior is None:
            return ["config", "unset", args[0]]
        return ["config", "set", args[0], "--", str(prior)]
    if verb == "skill write" and args:
        return ["skill", "retire", args[0]]
    return None


def _registration_snapshot_path(home: Path) -> Path:
    return cache_dir(home) / "attention" / "registrations.json"


def _write_registration_snapshot(home: Path, known: dict[str, str | None]) -> None:
    """``<cache>/attention/registrations.json``: the plain registrations
    seen before and when each first appeared (hosts.yaml has no times, and
    this reader runs no git). Cache only, never ledger truth."""
    target = _registration_snapshot_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(target, json.dumps({"known": known}, sort_keys=True) + "\n", fsync=False)


def _src_registrations(home: Path, ctx: "_Ctx") -> list[dict]:
    """``decided.registration``: a plain registration that appeared since
    the inbox last looked. The first read only learns what is there."""
    from . import hosts

    try:
        registry = hosts.load_hosts(home)
    except Exception:  # noqa: BLE001 -- an unreadable registry is no items here
        return []
    current: list[tuple[str, str]] = []
    for path in registry.projects:
        try:
            if hosts.host_mode(home, path, registration="project") == "plain":
                current.append(("project", str(path)))
        except Exception:  # noqa: BLE001
            continue
    if registry.skills_root is not None:
        try:
            if hosts.host_mode(home, registry.skills_root, registration="skills-root") == "plain":
                current.append(("skills-root", str(registry.skills_root)))
        except Exception:  # noqa: BLE001
            pass
    try:
        data = json.loads(_registration_snapshot_path(home).read_text("utf-8"))
        known = data.get("known") if isinstance(data, dict) else None
        known = dict(known) if isinstance(known, dict) else None
    except (OSError, ValueError):
        known = None
    first_read = known is None
    known = known or {}
    changed = False
    now = _iso(ctx.now)
    for kind, path in current:
        key = f"{kind}:{path}"
        if key not in known:
            known[key] = None if first_read else now
            changed = True
    # Fix round 1: the first read records that it has looked even when it
    # found no plain registration, or the first one made after it would be
    # "learned" by the next read instead of shown.
    if changed or first_read:
        try:
            _write_registration_snapshot(home, known)
        except OSError:
            pass
    agent_added = {
        str((row.get("args") or [""])[0]) for row in ctx.grant_uses if row.get("verb") == "host add"
    }
    out: list[dict] = []
    for kind, path in current:
        at = known.get(f"{kind}:{path}")
        if at is None or path in agent_added:
            continue
        if not ctx.all_items and not _within(at, DECIDED_WINDOW_DAYS, ctx.now):
            continue
        # Gate r1 MINOR 5: who made the registration is unknown here (no
        # grant-use row names it; hosts.yaml keeps no actor and the reader
        # runs no git), and it may well be the person's own `host add` in
        # their terminal. So the item names no actor: the source is the
        # code that noticed it, never "the overseer decided it for you".
        out.append(_new_item(
            "decided.registration", f"{path}@{at}",
            title=f"{path} is now registered as a plain {kind} host", since=at, by="code",
            meanwhile="self-learn writes its lines there uncommitted and never commits or pushes.",
            decided={"what": f"{path} became a plain {kind} host", "by": "code", "at": at,
                     "because": ("self-learn noticed the new registration; no record says who "
                                 "made it (an agent's registration under your grant shows as "
                                 "its own item), so it may have been you, in your own terminal"),
                     "changes_now": "lessons can compile into it"},
            registration={"kind": kind, "path": path},
        ))
    return out


def _src_skills(home: Path, ctx: "_Ctx") -> list[dict]:
    from . import skill_registry

    try:
        registry = skill_registry.load(home)
    except Exception:  # noqa: BLE001
        return []
    skills = getattr(registry, "skills", None)
    out: list[dict] = []
    for name, row in (skills or {}).items():
        if not isinstance(row, dict):
            continue
        events: list[tuple[str, dict]] = []
        created = row.get("created")
        if isinstance(created, dict):
            events.append(("written", created))
        last = row.get("last_write")
        if isinstance(last, dict) and isinstance(created, dict) and last.get("at") != created.get("at"):
            events.append(("updated", last))
        if isinstance(row.get("retired"), dict):
            events.append(("retired", row["retired"]))
        if row.get("renamed_from") and isinstance(last, dict):
            events.append(("renamed", {**last, "from": row["renamed_from"][-1]}))
        for action, stamp in events:
            by = stamp.get("by")
            at = stamp.get("at")
            if by not in ("overseer", "agent"):
                continue
            if not ctx.all_items and not _within(at, DECIDED_WINDOW_DAYS, ctx.now):
                continue
            undo_verb = (
                ["skill", "retire", str(name)] if action == "written" and row.get("status") == "live"
                else ["skill", "rename", str(name), str(stamp["from"])] if action == "renamed"
                else None
            )
            item = _new_item(
                "decided.skill", f"{name}:{action}@{at}",
                title=f"The {by} {action} the skill {name}", since=at, by=str(by),
                refs=[r for r in (stamp.get("case"),) if isinstance(r, str)],
                decided={"what": f"{action} the skill {name}", "by": by, "at": at,
                         "because": None, "changes_now": None},
                undo_verb=undo_verb,
            )
            if undo_verb is None:
                item["undo"] = None
            out.append(item)
    return out


def _src_notices(home: Path, ctx: "_Ctx") -> list[dict]:
    from . import notices

    out: list[dict] = []
    for notice in notices.all_notices(home):
        if not notices.is_live(notice, ctx.now):
            continue
        out.append(_new_item(
            "decided.notice", notice.id,
            title=f"Handed to the next agent in {Path(notice.project).name}: "
            f"{_first_line(notice.text, 120)}",
            since=notice.created_at, by="overseer" if notice.source == "overseer" else "code",
            run=notice.run, refs=[r for r in (notice.case,) if r],
            meanwhile="An agent working in that project carries it out; you need do nothing.",
            decided={"what": notice.text, "by": notice.source, "at": notice.created_at,
                     "because": None, "changes_now": None},
        ))
    return out


def _src_ledger_paths(home: Path, ctx: "_Ctx") -> list[dict]:
    """``decided.ledger-paths``: the steward's latest dispatch refused over
    unexplained ledger paths, and no later run completed."""
    rows = [r for r in _tail_jsonl(ctx.cache / "steward" / "journal.jsonl") if not r.get("dry_run")]
    latest: dict | None = None
    for row in rows:
        if row.get("status") == "dirty-refused" and isinstance(row.get("paths"), list):
            latest = row
        elif "decided" in row and latest is not None and str(row.get("ts") or "") > str(latest.get("ts") or ""):
            latest = None
    if latest is None:
        return []
    paths = sorted(str(p) for p in latest["paths"])
    digest = hashlib.sha256("\n".join(paths).encode("utf-8")).hexdigest()[:12]
    return [_new_item(
        "decided.ledger-paths", digest,
        title=f"{len(paths)} ledger file(s) changed outside self-learn; the steward waited",
        since=latest.get("ts"), by="steward",
        meanwhile="The steward skips the affected lessons until the paths are committed or "
        "removed; an agent can inspect them.",
        decided={"what": "held the dispatch over unexplained ledger paths", "by": "steward",
                 "at": latest.get("ts"), "because": _first_line(latest.get("error"), 300),
                 "changes_now": None},
        facts=[{"label": "paths", "value": paths}],
    )]


# ------------------------------------------------------------------ assembly


@dataclass
class _Ctx:
    home: Path
    cache: Path
    now: datetime
    all_items: bool
    statements: list[dict]
    choices: list[dict]
    outcomes: list[dict]
    withdrawn: list[dict]
    grant_uses: list[dict]
    holds: list[dict] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)


def _timed(ctx: _Ctx, name: str, fn: Callable[[Path, _Ctx], list[dict]]) -> list[dict]:
    """One source, timed: a source slower than its budget keeps its items
    but marks them ``partial: true`` and is named in ``ctx.partial``."""
    started = time.monotonic()
    items = fn(ctx.home, ctx)
    if time.monotonic() - started > SOURCE_BUDGET_SECS:
        ctx.partial.append(name)
        for item in items:
            item["partial"] = True
    return items


def _class_overrides(home: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind in settings.ATTENTION_CODE_KINDS:
        name = f"attention.class.{settings.attention_kind_key(kind)}"
        try:
            value, _source = settings.resolve_setting(home, settings.by_name(name))
        except Exception:  # noqa: BLE001 -- an unreadable config keeps the table's class
            continue
        if isinstance(value, str) and value != "table":
            out[kind] = value
    return out


def _apply_override(item: dict, wanted: str) -> dict | None:
    """``attention.class.<kind-key>`` on one item (§4.2): ``silent`` hides
    it; ``needs-you`` on a decided kind shows it under needs-you with
    ``because: null``; ``decided`` on a needs-you kind makes it decided and
    unflagged."""
    if wanted == "silent":
        return None
    if wanted == item["class"] or item["class"] == "approved":
        return item
    out = dict(item)
    if wanted == "needs-you":
        out["class"] = "needs-you"
        out["because"] = None
    elif wanted == "decided":
        out["class"] = "decided"
        out["flagged"] = False
    return out


def _conversation(home: Path, item_id_: str) -> tuple[dict, bool]:
    """The item's conversation summary (§4.1 `conversation`) and whether a
    redo is what its undo offers next: its transcript's last undo/redo row
    is an undo (§4.1 `undo.redo`; the same rule as
    `attention_answers.redo_offered`, read from the rows already loaded).
    Before the integration of 2026-10-31c `undo.redo` was always false."""
    from . import workspace

    try:
        rows = workspace.rows(home, item_id_)
    except Exception:  # noqa: BLE001
        return {"turns": 0, "last_at": None}, False
    turns = sum(1 for r in rows if r.get("role") == "user" and r.get("kind") == "question")
    last = max((str(r.get("at") or "") for r in rows if r.get("kind") != "header"), default="")
    acts = [r.get("kind") for r in rows if r.get("kind") in ("undo", "redo")]
    return {"turns": turns, "last_at": last or None}, bool(acts) and acts[-1] == "undo"


def collect(home: Path | str, *, all_items: bool = False) -> list[dict]:
    """Every item, with its private ``_`` fields, unsorted and with ``seen``
    filled. Raises on a source that fails outright (the reader's error)."""
    from . import grant_uses

    home = Path(home)
    now = _now()
    ctx = _Ctx(
        home=home, cache=cache_dir(home), now=now, all_items=all_items,
        statements=_statements(home), choices=_choices(home), outcomes=_outcomes(home),
        withdrawn=_withdrawn(home), grant_uses=grant_uses.read(home),
    )
    items: list[dict] = []
    ctx.holds = _timed(ctx, "holds", _src_holds)
    items += ctx.holds
    for name, fn in (
        ("broken", _src_broken), ("asks", _src_asks), ("withdrawn", _src_withdrawn),
        ("tampered", _src_tampered), ("runs", _src_runs), ("grant-uses", _src_grant_uses),
        ("registrations", _src_registrations), ("skills", _src_skills),
        ("notices", _src_notices), ("ledger-paths", _src_ledger_paths),
    ):
        items += _timed(ctx, name, fn)
    overrides = _class_overrides(home)
    seen = _read_seen(home)
    out: list[dict] = []
    ids: set[str] = set()
    for item in items:
        if item["id"] in ids:
            continue
        wanted = overrides.get(item["kind"])
        if wanted is not None and not item["kind"].startswith("ask."):
            changed = _apply_override(item, wanted)
            if changed is None:
                continue
            item = changed
        ids.add(item["id"])
        seen_at = seen.get(item["id"])
        item["seen"] = seen_at is not None and seen_at >= str(item.get("updated_at") or "")
        item["conversation"], redo = _conversation(home, item["id"])
        if isinstance(item.get("undo"), dict):
            item["undo"] = {**item["undo"], "redo": redo}
        out.append(item)
    return out


def _sort_key(item: dict) -> tuple:
    klass = item["class"]
    since = str(item.get("since") or "")
    if klass == "needs-you":
        because = item.get("because")
        rank = KEY_ORDER.index(because) if because in KEY_ORDER else len(KEY_ORDER)
        return (0, rank, since)
    if klass == "approved":
        return (1, 0, since)
    group = 2 if (not item["seen"] and item["flagged"]) else 3 if not item["seen"] else 4
    # Newest first within a decided group: invert the timestamp's order.
    updated = str(item.get("updated_at") or "")
    return (group, 0, "".join(chr(0x10FFFF - ord(c)) for c in updated))


def _tooltip(items: list[dict], counts: dict[str, int]) -> str:
    needs = [i for i in items if i["class"] == "needs-you"]
    parts: list[str] = []
    if needs:
        words = list(dict.fromkeys(
            KEY_WORDS.get(str(i.get("because")), "something only you can do") for i in needs
        ))
        parts.append(f"{len(needs)} need{'s' if len(needs) == 1 else ''} you ({'; '.join(words)})")
    if counts["new"]:
        parts.append(f"{counts['new']} new")
    if counts["approved"]:
        parts.append(f"{counts['approved']} being carried out")
    return "self-learn: " + (" · ".join(parts) if parts else "nothing needs you")


def public(item: dict) -> dict:
    """*item* without its private fields: the §4.1 object."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def read(home: Path | str, *, all_items: bool = False) -> dict:
    """The ``self-learn attention --json`` document (contract §4.1). Never
    raises: a failed reader gives ``state: broken``, ``error`` set and no
    items."""
    home = Path(home)
    generated = _iso(_now())
    try:
        directory = str(cache_dir(home))
    except Exception:  # noqa: BLE001
        directory = None
    try:
        items = collect(home, all_items=all_items)
    except Exception as exc:  # noqa: BLE001 -- the reader's failure is the broken state
        return {
            "version": VERSION, "generated_at": generated, "cache_dir": directory,
            "state": "broken",
            "counts": {"needs_you": 0, "new": 0, "decided_unseen": 0, "approved": 0},
            "tooltip": f"self-learn: the inbox could not be read ({type(exc).__name__})",
            "error": f"{type(exc).__name__}: {exc}", "items": [],
        }
    now = _now()
    if not all_items:
        items = [
            i for i in items
            if i["class"] != "decided" or _within(i.get("updated_at"), DECIDED_WINDOW_DAYS, now)
        ]
    items.sort(key=_sort_key)
    counts = {
        "needs_you": sum(1 for i in items if i["class"] == "needs-you"),
        "new": sum(1 for i in items if i["class"] == "decided" and i["flagged"] and not i["seen"]),
        "decided_unseen": sum(1 for i in items if i["class"] == "decided" and not i["seen"]),
        "approved": sum(1 for i in items if i["class"] == "approved"),
    }
    if any(i["kind"].startswith("broken.") and i["class"] == "needs-you" for i in items):
        state = "broken"
    elif counts["needs_you"]:
        state = "needs-you"
    elif counts["new"]:
        state = "new"
    else:
        state = "idle"
    return {
        "version": VERSION, "generated_at": generated, "cache_dir": directory,
        "state": state, "counts": counts, "tooltip": _tooltip(items, counts), "error": None,
        "items": [public(i) for i in items],
    }


def find(home: Path | str, wanted: str) -> dict | None:
    """The item *wanted* (any class, any age) with its private fields, or
    ``None``."""
    for item in collect(home, all_items=True):
        if item["id"] == wanted:
            return item
    return None
