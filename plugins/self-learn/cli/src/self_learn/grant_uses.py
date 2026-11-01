"""The grant-use record (attention round, design r2 §3.4.6; critique 7).

``<ledger>/grant-uses.jsonl`` holds one row each time an agent's shell ran
a person-only verb under an :class:`attribution.Authority` (the user's
standing grant, or a typed yes proved for one question). Before this file
such an act existed only as commit trailers, which the attention reader may
not read (it runs no git). The inbox shows each row as a
``decided.grant-use`` item with its undo.

Append-only JSON Lines, committed. The one writer is :func:`append`, which
takes :func:`intents.ledger_write` itself and commits the row as its own
commit. :func:`attribution.acting` calls it on a normal exit of the verb it
wraps, inside the same ``ledger_write`` span, so the commit carries the same
``By: agent`` and ``Grant:``/``Proof:`` trailers as the verb's own.

    {"id": "gu-1a2b3c4d", "at": "...", "verb": "config set",
     "args": ["attention.terminal", "alacritty -e"],
     "statement": "stmt-...|null", "proof": "transcript:...#L...|null",
     "note": "...", "prior": <the prior value or registration>|null}
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import gitops, intents
from .primitives import chrono, fsops

__all__ = ["FILENAME", "GU_ID_RE", "GrantUse", "append", "path", "read", "row_for"]

FILENAME = "grant-uses.jsonl"
GU_ID_RE = re.compile(r"^gu-[0-9a-f]{8}$")


@dataclass
class GrantUse:
    """What a person-only verb run under an authority did, handed to
    :func:`attribution.acting` by its call site. ``prior`` is read by the
    call site BEFORE the verb acts (the prior setting value, the prior
    registration), so the inbox can offer the exact inverse. ``applies`` is
    set False by a call site whose verb returned a refusal code without
    raising, so a refused act records nothing."""

    home: Path
    verb: str
    args: list[str]
    prior: Any = None
    applies: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def path(home: Path | str) -> Path:
    return Path(home) / FILENAME


def read(home: Path | str) -> list[dict]:
    """Every row, oldest first. A malformed line is skipped, never raised
    (a reader must not break on one bad row)."""
    try:
        text = path(home).read_text(encoding="utf-8")
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
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            out.append(row)
    return out


def row_for(kind: str, ref: str, reason: str, use: GrantUse) -> dict:
    """The row for *use* run under an authority of *kind* (``grant`` or
    ``typed-yes``) whose ref is *ref*. A grant cites its statement, a typed
    yes its transcript line."""
    return {
        "verb": use.verb,
        "args": [str(a) for a in use.args],
        "statement": ref if kind == "grant" else None,
        "proof": ref if kind != "grant" else None,
        "note": reason,
        "prior": use.prior,
    }


def _new_id(existing: list[dict]) -> str:
    seen = {row.get("id") for row in existing}
    for _ in range(64):
        candidate = "gu-" + uuid.uuid4().hex[:8]
        if candidate not in seen:
            return candidate
    raise RuntimeError("grant-uses: could not allocate a unique id")  # pragma: no cover


def append(home: Path | str, row: dict) -> str:
    """Append one grant-use *row* (without ``id``/``at``) and commit it as
    its own commit, under :func:`intents.ledger_write`. Returns the new id.
    The commit is stamped by :func:`attribution.stamp` like every ledger
    commit, so inside :func:`attribution.acting` it reads ``By: agent`` and
    the authority's trailer."""
    home = Path(home)
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        existing = read(home)
        record = {"id": _new_id(existing), "at": chrono.now_iso(), **row}
        target = path(home)
        prior = target.read_text(encoding="utf-8") if target.exists() else ""
        if prior and not prior.endswith("\n"):
            prior += "\n"
        fsops.atomic_write(target, prior + json.dumps(record, sort_keys=True) + "\n", fsync=True)
        gitops.stage_and_commit(
            home, [target], f"self-learn: grant use {record['id']} ({row.get('verb')})", None
        )
    return record["id"]
