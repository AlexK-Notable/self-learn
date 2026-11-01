"""Per-day counts for the UI's charts (w33-humane lane 0, S-NEXT-humane).

``report --json`` carries the result as ``series``. Every number is a
count read from the ledger, never a model or an estimate (04's "counted,
not modelled"), so a chart drawn from it only shows what happened:

- ``pending`` / ``deferred``: lesson files under a bucket's ``pending/``
  folder whose status is ``pending`` / ``deferred``, at the ledger's last
  commit on or before the end of that day (read from git history);
- ``captured``: ``capture`` telemetry events on that day (lessons written,
  by a session or by the overnight read);
- ``decided``: decision cases opened on that day, by outcome group, and
  ``decided_by`` / ``verbs``: the same cases by who decided and by verb.

Days are calendar days in the local time zone of the machine running the
CLI (each day with its own daylight-saving offset; ``tz`` in the result is
today's offset), the newest last. Read-only: it runs git reads
on the ledger and reads case files; it writes nothing.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path

__all__ = ["OUTCOME_GROUPS", "SERIES_DAYS", "day_series"]

#: The window, in days, ending today.
SERIES_DAYS = 28

#: A case's outcome verb -> the group a chart shows. ``use``: the lesson
#: went into effect (placed, replaced in place, moved, revised); ``no``:
#: turned down or retired; ``later``: deferred or parked for the weekly
#: check; ``kept``: looked at and left as it was. Every verb in
#: :data:`self_learn.cases.OUTCOMES` is in exactly one group (checked in
#: the tests); a verb outside them counts under ``verbs`` only.
OUTCOME_GROUPS: dict[str, tuple[str, ...]] = {
    "use": ("route", "replaced", "rehome", "revise"),
    "no": ("reject", "retire"),
    "later": ("defer", "parked"),
    "kept": ("no-action",),
}
_GROUP_OF = {verb: group for group, verbs in OUTCOME_GROUPS.items() for verb in verbs}

_PENDING_PATH_RE = re.compile(r"^(?:user|skills/[^/]+|projects/[^/]+)/pending/lrn-[0-9a-f]{8}\.md$")
_STATUS_RE = re.compile(r"^status:\s*['\"]?([a-z-]+)", re.MULTILINE)
_FM_RE = {
    "opened_at": re.compile(r"^opened_at:\s*['\"]?([^'\"\n]+)", re.MULTILINE),
    "actor": re.compile(r"^actor:\s*['\"]?([a-z-]+)", re.MULTILINE),
    "outcome": re.compile(r"^outcome:\s*['\"]?([a-z-]+)", re.MULTILINE),
}
_GIT_TIMEOUT = 20.0


def _to_local(dt: datetime, tz: tzinfo | None) -> datetime:
    """*dt* in *tz*, or in the machine's local zone with its own daylight
    saving offset for that instant when *tz* is None."""
    return dt.astimezone(tz) if tz is not None else dt.astimezone()


def _day_end(d: date, tz: tzinfo | None) -> datetime:
    naive = datetime.combine(d, time(23, 59, 59))
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


def _parse_ts(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _git(home: Path, *args: str, stdin: str | None = None) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(home), *args], input=stdin, capture_output=True,
            text=True, timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _queue_by_day(home: Path, day_ends: list[datetime]) -> tuple[list[tuple[int, int]] | None, str | None]:
    """``[(pending, deferred)]`` per day end, or ``(None, why)``."""
    start = int(day_ends[0].timestamp()) - 86400
    log = _git(home, "log", "--format=%H %ct", f"--since={start}", "HEAD")
    base = _git(home, "rev-list", "-1", f"--before={start}", "HEAD")
    if log is None or base is None:
        return None, "the ledger's git history could not be read"
    commits = [(int(ct), sha) for sha, ct in (ln.split() for ln in log.splitlines() if ln.strip())]
    if base.strip():
        commits.append((start, base.strip()))
    commits.sort()
    chosen: list[str | None] = []
    for end in day_ends:
        cut = end.timestamp()
        best = None
        for ct, sha in commits:
            if ct <= cut:
                best = sha
            else:
                break
        chosen.append(best)
    blobs_by_commit: dict[str, list[str]] = {}
    for sha in {c for c in chosen if c}:
        tree = _git(home, "ls-tree", "-r", sha)
        if tree is None:
            return None, "the ledger's git history could not be read"
        blobs = []
        for line in tree.splitlines():
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) == 3 and parts[1] == "blob" and _PENDING_PATH_RE.match(path):
                blobs.append(parts[2])
        blobs_by_commit[sha] = blobs
    wanted = sorted({b for blobs in blobs_by_commit.values() for b in blobs})
    status: dict[str, str] = {}
    if wanted:
        out = _git(home, "cat-file", "--batch", stdin="\n".join(wanted) + "\n")
        if out is None:
            return None, "the ledger's git history could not be read"
        status = _batch_statuses(out)
    rows = []
    for sha in chosen:
        if sha is None:
            rows.append((0, 0))
            continue
        states = Counter(status.get(b, "") for b in blobs_by_commit[sha])
        rows.append((states["pending"], states["deferred"]))
    return rows, None


def _batch_statuses(out: str) -> dict[str, str]:
    """``git cat-file --batch`` output -> ``{blob sha: frontmatter status}``.
    Sizes are in bytes and the text is decoded, so each object is found by
    its header line and read up to the next header, not by byte count."""
    result: dict[str, str] = {}
    header = re.compile(r"^([0-9a-f]{40}) blob \d+$", re.MULTILINE)
    marks = list(header.finditer(out))
    for i, m in enumerate(marks):
        body = out[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(out)]
        text = body.lstrip("\n")
        fm = text[3:].split("\n---", 1)[0] if text.startswith("---") else text[:2000]
        sm = _STATUS_RE.search(fm)
        result[m.group(1)] = sm.group(1) if sm else ""
    return result


def _cases(home: Path) -> list[tuple[datetime, str, str]]:
    """``(opened_at, actor, outcome)`` for every readable case file."""
    rows = []
    for path in sorted((home / "cases").glob("*/case-*.md")):
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        if not head.startswith("---"):
            continue
        fm = head.split("\n---", 2)[0]
        found = {k: rx.search(fm) for k, rx in _FM_RE.items()}
        if not all(found.values()):
            continue
        when = _parse_ts(found["opened_at"].group(1))  # type: ignore[union-attr]
        if when is None:
            continue
        rows.append((when, found["actor"].group(1), found["outcome"].group(1)))  # type: ignore[union-attr]
    return rows


def day_series(
    home: Path | str,
    *,
    today: date | None = None,
    events: list[dict] | None = None,
    days: int = SERIES_DAYS,
    tz: tzinfo | None = None,
) -> dict:
    """The ``series`` block: ``{"days", "tz", "rows", "error"}``.

    ``rows`` holds one entry per day, oldest first, ``days`` long, each
    ``{"date", "pending", "deferred", "captured", "decided", "decided_by",
    "verbs"}``. ``pending``/``deferred`` are ``None`` on every row when the
    git history could not be read, and ``error`` says why in words; the
    other fields are still counted."""
    from .telemetry import read_events  # deferred: keep import light

    home = Path(home)
    last = today if today is not None else _to_local(datetime.now(timezone.utc), tz).date()
    dates = [last - timedelta(days=days - 1 - i) for i in range(days)]
    day_ends = [_day_end(d, tz) for d in dates]
    index = {d: i for i, d in enumerate(dates)}

    captured = [0] * days
    for event in events if events is not None else read_events(home):
        if event.get("kind") != "capture" or not isinstance(event.get("ts"), str):
            continue
        when = _parse_ts(event["ts"])
        if when is not None and (i := index.get(_to_local(when, tz).date())) is not None:
            captured[i] += 1

    groups = [Counter() for _ in range(days)]
    actors = [Counter() for _ in range(days)]
    verbs = [Counter() for _ in range(days)]
    for when, actor, outcome in _cases(home):
        i = index.get(_to_local(when, tz).date())
        if i is None:
            continue
        verbs[i][outcome] += 1
        actors[i][actor] += 1
        if outcome in _GROUP_OF:
            groups[i][_GROUP_OF[outcome]] += 1

    queue, error = _queue_by_day(home, day_ends)
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "date": d.isoformat(),
            "pending": queue[i][0] if queue is not None else None,
            "deferred": queue[i][1] if queue is not None else None,
            "captured": captured[i],
            "decided": {g: groups[i][g] for g in OUTCOME_GROUPS},
            "decided_by": dict(sorted(actors[i].items())),
            "verbs": dict(sorted(verbs[i].items())),
        })
    offset = day_ends[-1].strftime("%z")
    return {
        "days": days,
        "tz": f"{offset[:3]}:{offset[3:]}" if offset else "+00:00",
        "rows": rows,
        "error": error,
    }
