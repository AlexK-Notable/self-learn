"""What the steward and the overseer do with a failed model call, by its
class (2026-09-27, fail-state audit finding 4; the classes are
`invocation.failure_class`'s).

* ``transient`` -- one retry within the same attempt, after a short backoff.
* ``environment`` -- a hold: the attempt is not counted, the user is told
  once per distinct cause, and the runner's journal says so.
* ``safeguard``, ``content``, ``unclassified`` -- counted as before; the
  class and the API's detail tag ride the run record and the failure note.
  The user will accept a fallback model only as a last resort (2026-09-27
  13:30), so a safeguard flag is never retried on another model.

The miner and the analyst are not changed: they only see the class on the
outcome.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .invocation.failure_class import detail_tag, outcome_class

__all__ = [
    "TRANSIENT_BACKOFF_SECS",
    "HELD_ENVIRONMENT",
    "should_retry",
    "backoff",
    "failure_fields",
    "hold_cause",
    "last_hold_cause",
    "strip_ids",
    "told_causes",
]

#: How long a runner waits before its one retry of a transient failure.
#: Long enough for a 529 or a rate-limit window to pass, short enough that
#: the attempt it belongs to is still the same attempt.
TRANSIENT_BACKOFF_SECS = 30.0

#: The journal status of an environment hold, in both runners' journals.
HELD_ENVIRONMENT = "held-environment"

_sleep = time.sleep


def should_retry(outcome: Any) -> bool:
    """True when a failed call is ``transient``: the runner waits
    (:func:`backoff`) and makes that call once more, within the same
    attempt. Written flat at each call site, never as a callback, so no
    closure of a runner becomes its own node for the lock invariant."""
    return outcome_class(outcome) == "transient"


def backoff() -> None:
    """The wait before the one retry of a transient failure."""
    _sleep(TRANSIENT_BACKOFF_SECS)


def failure_fields(outcome: Any) -> dict[str, str]:
    """The class of a failed call and the API's detail tag, for a run
    record, an attempt row or a journal line; empty for a call that did not
    fail."""
    klass = outcome_class(outcome)
    if klass is None:
        return {}
    fields = {"failure_class": klass}
    detail = getattr(outcome, "detail", None)
    tag = detail_tag(detail if isinstance(detail, str) else None)
    if tag is not None:
        fields["failure_tag"] = tag
    return fields


_IDS = re.compile(r"\b(?:request|message) id:?\s*\S+", re.I)


def strip_ids(text: str) -> str:
    """*text* with request and message ids removed and whitespace folded:
    the same cause reads the same on the next attempt."""
    return " ".join(_IDS.sub("", text).split())


def told_causes(journal: Path, status: str, key: str = "cause") -> set[str]:
    """Every *key* value of a runner's JSONL journal rows whose status is
    *status* (2026-09-28, follow-up 2): what the user has already been told,
    so each distinct cause is told once."""
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    told: set[str] = set()
    for line in lines:
        if status not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("status") == status:
            value = row.get(key)
            if isinstance(value, str):
                told.add(value)
    return told


def hold_cause(outcome: Any) -> str:
    """A short, stable statement of why an environment hold happened: the
    message's first sentence with request and message ids removed, so the
    same cause is recognised on the next attempt and told once."""
    detail = getattr(outcome, "detail", None)
    text = _IDS.sub("", detail if isinstance(detail, str) else "")
    text = " ".join(text.split())
    if not text:
        return str(getattr(outcome, "failure", None) or "invocation")
    first = re.split(r"(?<=[.;])\s", text, maxsplit=1)[0]
    return first[:200]


def last_hold_cause(journal: Path, key: str = "cause") -> str | None:
    """The cause of the most recent environment hold in a runner's JSONL
    journal, or ``None``: the runner tells the user only when the cause
    differs from it."""
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if HELD_ENVIRONMENT not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("status") == HELD_ENVIRONMENT:
            value = row.get(key)
            return value if isinstance(value, str) else None
    return None
