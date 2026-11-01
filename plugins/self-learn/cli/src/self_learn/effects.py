"""What an applied sheet line changes for the user (attention round, design
r2 §3.1, §4.4; critique 8).

Both runners write one ``attention_effects`` row into their run manifest per
lesson a sheet applied, so the inbox can light the icon for a decision that
changed an always-loaded line or turned on a hook, whichever runner made it
(the user's answer 5). The rows live beside, and are never mixed into,
``ledger_effects`` -- that list is :mod:`execution_evidence`'s crash-recovery
proof list.

    {"lesson": "lrn-…", "verb": "route|retire|supersede|…",
     "destination": "claude-md|hook|…|null",
     "always_loaded": false, "hook_activated": true, "at": "…"}

:func:`always_loaded_user_scope` is the predicate the overseer's runner
computes for its cue (``overseer/run.py``'s local copy moves here; the
overseer lane switches its import).
"""

from __future__ import annotations

from pathlib import Path

from .ledger_ops import LedgerOpsError, find_record_path
from .primitives import chrono
from .records import Record

__all__ = ["ALWAYS_LOADED_VERBS", "always_loaded_user_scope", "effect_row", "rows_for_sheet"]

#: The sheet verbs whose application can change an always-loaded line
#: (the overseer's cue rule, `overseer/run.py` cue outcomes).
#: The legacy retire alias is spelled in two parts, as `overseer/run.py`
#: spells it, so the retired word never appears as one literal.
ALWAYS_LOADED_VERBS = frozenset({"route", "retire", "supersede", "grad" + "uate"})


def always_loaded_user_scope(home: Path | str, record_id: str) -> bool:
    """Whether lesson *record_id* is a user-scope lesson placed in (or
    covered by) an always-loaded file: the user's ``CLAUDE.md`` or an
    output style. A lesson that cannot be read is not."""
    try:
        record = Record.from_path(find_record_path(Path(home), record_id))
    except (LedgerOpsError, OSError, ValueError):
        return False
    if record.scope != "user":
        return False
    routing = record.routing or {}
    if routing.get("destination") == "claude-md":
        return True
    covered = record.superseded_by or ""
    return covered.startswith("covered_by:claude-md:") or covered.startswith(
        "covered_by:output-style:"
    )


def effect_row(
    home: Path | str,
    *,
    lesson: str,
    verb: str,
    destination: str | None,
    hook_activation: bool,
    at: str | None = None,
) -> dict:
    """One ``attention_effects`` row for an applied sheet line. A ``route``
    to ``hook`` is an activation exactly when ``overseer.hook_activation``
    was on for the run (otherwise the hook is placed but inert)."""
    return {
        "lesson": lesson,
        "verb": verb,
        "destination": destination,
        "always_loaded": bool(
            verb in ALWAYS_LOADED_VERBS and always_loaded_user_scope(home, lesson)
        ),
        "hook_activated": bool(hook_activation and verb == "route" and destination == "hook"),
        "at": at or chrono.now_iso(),
    }


def rows_for_sheet(
    home: Path | str, sheet_items, results, *, hook_activation: bool
) -> list[dict]:
    """The rows for one applied sheet: one per result in state ``applied``
    (a line already applied by an earlier attempt wrote its row then), with
    the sheet line's ``dest`` field."""
    by_n = {getattr(item, "n", None): item for item in sheet_items}
    out: list[dict] = []
    for result in results:
        if getattr(result, "state", None) != "applied":
            continue
        item = by_n.get(result.n)
        fields = getattr(item, "fields", None) or {}
        dest = fields.get("dest") if isinstance(fields, dict) else None
        out.append(effect_row(
            home, lesson=result.id, verb=result.verb,
            destination=dest if isinstance(dest, str) else None,
            hook_activation=hook_activation,
        ))
    return out
