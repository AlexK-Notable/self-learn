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

#: THE one timestamp format -- second precision, ``Z``-suffixed, no
#: microseconds, no ``+00:00`` offset. Every ``_now_iso`` this leaf
#: replaces (12 sites, M-J) rendered exactly this string; UI
#: ``store.py``'s own copy instead called ``.isoformat()`` (microseconds
#: + ``+00:00``) -- that drift, not this constant, was the bug the
#: migration closes. Exported (not just embedded in :func:`now_iso`) so
#: :func:`self_learn.telemetry._now_iso`'s thin ``now:``-parameterized
#: wrapper can format explicitly without duplicating the literal itself
#: (a duplicate literal would itself trip the M-J P1 body scan).
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_iso(now: datetime | None = None) -> str:
    """UTC now (or *now*, for a caller that already has a clock reading
    it must not re-sample -- ``telemetry``'s test-injected clock is the
    one caller that needs this), second precision, ``Z``-suffixed -- the
    one format every ``created_at``/``routed_at``/timestamp field in the
    ledger uses."""
    return (now if now is not None else datetime.now(timezone.utc)).strftime(
        ISO_FORMAT
    )


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
