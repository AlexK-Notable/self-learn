"""primitives.chrono -- ONE clock, ONE timestamp parser, ONE age floor
(Sprint 1 M-B, plan v2 SS2 M-B/M-J). Every ``_now_iso``/``_to_dt``/age
computation in both trees converges here so a truncated-precision age
(A1: ``.days`` after subtracting from a date-truncated timestamp) cannot
recur module-by-module.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

#: Floor divisor for :func:`age_days` -- never ``.days`` on a bare
#: timedelta subtraction (that silently reintroduces A1 the moment either
#: operand loses its time-of-day component before the subtraction).
_SECONDS_PER_DAY = 86400


def now_iso() -> str:
    """UTC now, second precision, ``Z``-suffixed -- the one format every
    ``created_at``/``routed_at``/timestamp field in the ledger uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_dt(value: object) -> datetime | None:
    """Lenient timestamp coercion (moved from ``ledger_ops._to_dt``):
    ruamel hands back ``datetime``/``date`` for plain ISO scalars loaded
    from YAML, ``str`` otherwise (e.g. values that round-tripped through
    JSON). ``None`` / unparseable -> ``None`` -- never raises."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def age_days(then: datetime | None, now: datetime) -> int:
    """Age in whole days on the FULL-TIMESTAMP floor: ``then`` must
    already carry its true time-of-day (never a date-truncated
    midnight substitute -- that is exactly the A1 bug, measured live as
    the ``list --json``/``status --fast`` 40-vs-39 divergence). ``None``
    -> ``0`` (unparseable/absent timestamp, never a crash)."""
    if then is None:
        return 0
    return max(0, int((now - then).total_seconds() // _SECONDS_PER_DAY))
