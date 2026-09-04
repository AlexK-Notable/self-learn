"""self_learn.domain -- THE queue/liveness/age predicates (Sprint 1 M-B,
plan v2 SS2). Every consumer that used to re-derive one of these three
questions -- "is this record queued", "is this record's routing still
live", "how old is this record" -- imports this leaf instead:
``ledger_ops.queue``/``is_unanalyzed``, ``report.ledger_metrics``,
``report``'s ``routed_live`` accumulation, ``worker.fast_status`` (mapping
form), ``worker._oldest_pending_days``, ``compilers._eligible``,
``verbs.recompile``'s ``retired``, UI ``models._is_deferred``.

Depends on nothing but :mod:`self_learn.records` (the schema) and
:mod:`self_learn.primitives.chrono` (the clock) -- NOT ``ledger_ops``,
NOT ``compilers``, NOT ``report``. Those three modules import records
AND each other's private helpers today; if this leaf reached back into
any of them the cycle it exists to break would simply reappear one
module lower (plan v2 SS2's own framing for this move).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Union

from .primitives import chrono
from .records import DRAFT_STATUSES, Record

#: A full :class:`~self_learn.records.Record` OR a plain frontmatter
#: mapping (``worker.fast_status``'s ``--fast`` scan never loads a full
#: Record -- it reads the YAML frontmatter dict directly, S4).
RecordLike = Union[Record, Mapping]


def _field(rec: RecordLike, name: str, default: object = None) -> object:
    if isinstance(rec, Mapping):
        return rec.get(name, default)
    return getattr(rec, name, default)


def is_queued(record_or_mapping: RecordLike, now: datetime) -> bool:
    """THE queue-membership predicate (02 SS2, 08 SS7.1 step 2): a
    draft-status record (``pending``/``deferred``) whose
    ``deferred_until`` is not in the future. A record whose deferral has
    LAPSED (``deferred_until`` in the past, status may still say
    ``deferred`` -- membership is computed, never read off ``status``)
    counts as queued -- this is the deferral half of what used to be
    ``ledger_ops._deferred_hidden``, folded in here so every caller asks
    ONE question instead of two.

    No status key (mapping form) is NOT the same as ``status: pending``:
    a status-less mapping is excluded, same as an unparseable/corrupt
    frontmatter dict would be everywhere else in this codebase (fail
    closed, never silently "probably pending")."""
    status = _field(record_or_mapping, "status")
    if status not in DRAFT_STATUSES:
        return False
    until = chrono.to_dt(_field(record_or_mapping, "deferred_until"))
    return until is None or until <= now


def is_canon_live(record: Record) -> bool:
    """THE routed-and-not-superseded predicate: a record whose routing is
    still the CURRENT canon for its destination -- ``routed`` status AND
    no ``superseded_by`` (a corrective supersede or a graduation moves a
    record to ``superseded`` with ``superseded_by`` set, but the
    ``and`` here is defence-in-depth against any record whose two fields
    ever drift, not just the common case)."""
    return record.status == "routed" and record.superseded_by is None


def record_age_days(record_or_mapping: RecordLike, now: datetime) -> int:
    """Age in days on the full-timestamp floor (never ``.days`` after a
    subtraction against a date-truncated ``created_at`` -- see
    :func:`self_learn.primitives.chrono.age_days`'s docstring for the A1
    bug this closes)."""
    dt = chrono.to_dt(_field(record_or_mapping, "created_at"))
    return chrono.age_days(dt, now)
