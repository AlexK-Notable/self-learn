"""health.py -- the Health page's view model (humane lane 2, S-NEXT-humane-l2).

``/report`` used to print ``report --json`` field by field and then the raw
JSON. The Health page shows the same facts in a person's words. This module
only ARRANGES what the CLI computed (09 §3: the UI derives no numbers):

* the tiles quote CLI numbers (``status --json`` ``metrics``, ``report
  --json`` counters). The only counting done here is the length of a list
  the CLI sent ("rules in use" is ``len(routed_live)``, "in N places" is the
  number of distinct buckets in that list), which is what the old page did
  too;
* every lesson is listed by its own words (``title``), never by its id; the
  id survives only as the target of the link to the lesson's page;
* the counters keep their CLI names, in a fold, so a number on this page can
  be checked against ``self-learn report`` and ``self-learn status``;
* no raw JSON is built or shown.

A value that is missing or the wrong type shows as "not known", never as a
zero and never as a crash: a half-working CLI still draws a page.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "BASIS_WORDS",
    "DEFAULT_LIMIT",
    "KIND_WORDS",
    "build_health",
    "days_in_words",
    "place_words",
]

#: How many rules the table shows before "Show all".
DEFAULT_LIMIT = 25

#: A routing destination in words. An unknown destination shows as it was
#: recorded (contract.md §2), never as nothing.
KIND_WORDS: dict[str, str] = {
    "claude-md": "Instructions file",
    "skill-md": "Skill",
    "hook": "Warning hook",
    "rules": "Rules file",
    "reference": "Reference file",
    "new-skill": "New skill",
}

#: Why a rule was flagged as seen again, in words. Unknown values show raw.
BASIS_WORDS: dict[str, str] = {
    "miner-match": "A transcript matched the rule's text",
    "origin-match": "A transcript matched the rule's text",
    "title-token-overlap": "A transcript used words close to the rule",
    "fire-violated": "A session broke the rule",
    "fire-suspected-violation": "A session may have broken the rule",
}

NO_TEXT = "A rule with no recorded text"
NOT_KNOWN = "not known"


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list(value: Any) -> list[dict]:
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def days_in_words(n: Any) -> str:
    """``0`` -> ``today``, ``1`` -> ``1 day``, ``99`` -> ``99 days``."""
    d = _int(n)
    if d is None:
        return NOT_KNOWN
    if d <= 0:
        return "today"
    return "1 day" if d == 1 else f"{d} days"


def place_words(destination: Any, scope: Any, bucket_label: Any) -> tuple[str, str]:
    """``(what, where)`` for a placed rule: ``("Warning hook", "self-learn")``.
    The user's own instructions file reads as one line."""
    dest = _text(destination)
    label = _text(bucket_label)
    if dest == "claude-md" and scope == "user":
        return "Your instructions", ""
    kind = KIND_WORDS.get(dest, dest or "Placed")
    return kind, label


def _fmt_number(name: str, value: float) -> str:
    if name.endswith(("_rate", "_ceiling")):
        pct = round(value * 100, 1)
        return f"{int(pct)}%" if pct == int(pct) else f"{pct}%"
    if name.endswith("_pct"):
        return f"{value:g}%"
    return f"{round(value, 2):g}"


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]], depth: int = 0) -> None:
    """Counters as ``(CLI name, value in words)``. Dicts open up (up to
    three levels); a list becomes a count; booleans become yes/no."""
    if isinstance(value, dict) and depth < 3:
        for key, inner in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), inner, out, depth + 1)
    elif isinstance(value, bool):
        out.append((prefix, "yes" if value else "no"))
    elif isinstance(value, (int, float)):
        out.append((prefix, _fmt_number(prefix.rsplit(".", 1)[-1], value) if isinstance(value, float) else str(value)))
    elif isinstance(value, (list, tuple)):
        out.append((prefix, f"{len(value)} entries"))
    elif isinstance(value, dict):
        out.append((prefix, f"{len(value)} entries"))
    elif value is None:
        out.append((prefix, "none"))
    else:
        out.append((prefix, str(value)))


def _counters(report: dict, metrics: Any, supply_mix: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in ("routed_ever", "superseded_after_routing", "supersede_rate", "graduated", "rejected"):
        if name in report:
            _flatten(name, report[name], out)
    for name in ("mined", "telemetry"):
        if name in report:
            _flatten(name, report[name], out)
    if isinstance(metrics, dict):
        _flatten("metrics", metrics, out)
    if isinstance(supply_mix, dict):
        _flatten("supply_mix", supply_mix, out)
    return out


def _tiles(report: dict, metrics: Any, status_buckets: Any) -> list[dict]:
    live = _list(report.get("routed_live"))
    places = {(r.get("scope"), r.get("bucket")) for r in live}
    metrics = metrics if isinstance(metrics, dict) else {}

    pending = _int(metrics.get("pending_total"))
    oldest = None
    for b in _list(status_buckets):
        age = _int(b.get("oldest_days"))
        if age is not None and (oldest is None or age > oldest):
            oldest = age
    if pending is None:
        waiting_note = NOT_KNOWN
    elif pending == 0:
        waiting_note = "nothing is waiting"
    elif oldest is None:
        waiting_note = "waiting to be looked at"
    else:
        waiting_note = f"the oldest has waited {days_in_words(oldest)}" if oldest else "the oldest arrived today"

    wait = metrics.get("time_to_triage_median_days")
    if isinstance(wait, (int, float)) and not isinstance(wait, bool):
        if wait < 1:
            wait_value = "under a day"
        elif wait == int(wait):
            wait_value = days_in_words(int(wait))
        else:
            wait_value = f"{round(wait, 1):g} days"
        wait_note = "half are decided within this long"
    else:
        wait_value, wait_note = "none yet", "no lesson has been decided yet"

    ever = _int(report.get("routed_ever"))
    fixed = _int(report.get("superseded_after_routing"))
    rate = report.get("supersede_rate")
    if fixed is None or ever is None:
        corrected_value, corrected_note = NOT_KNOWN, ""
    else:
        corrected_value = f"{fixed}"
        pct = f"{round(rate * 100)}%: " if isinstance(rate, (int, float)) and not isinstance(rate, bool) else ""
        corrected_note = f"of {ever} put to use, {pct}replaced later by a better rule"

    return [
        {
            "label": "Rules in use",
            "value": str(len(live)),
            "note": f"in {len(places)} {'place' if len(places) == 1 else 'places'}" if live else "none yet",
        },
        {
            "label": "Waiting for a decision",
            "value": NOT_KNOWN if pending is None else str(pending),
            "note": waiting_note,
        },
        {"label": "Typical wait", "value": wait_value, "note": wait_note},
        {"label": "Rules later corrected", "value": corrected_value, "note": corrected_note},
    ]


def _rule_rows(report: dict) -> list[dict]:
    rows = []
    for r in _list(report.get("routed_live")):
        what, where = place_words(r.get("destination"), r.get("scope"), r.get("bucket_label") or r.get("bucket"))
        seen = _int(r.get("recurrences")) or 0
        age = _int(r.get("routed_days_ago"))
        rows.append(
            {
                "id": _text(r.get("id")),
                "title": _text(r.get("title")) or NO_TEXT,
                "what": what,
                "where": where,
                "age": age,
                "age_words": days_in_words(age),
                "seen": seen,
            }
        )
    rows.sort(key=lambda x: (-x["seen"], -(x["age"] if x["age"] is not None else -1), x["title"]))
    return rows


def _seen_again(report: dict) -> list[dict]:
    """One row per rule, however many times it was sighted (the sightings
    arrive one row each; ``id`` groups them, as the front page does)."""
    groups: dict[str, dict] = {}
    for s in _list(report.get("recurrence_suspects")):
        rid = _text(s.get("id"))
        g = groups.setdefault(
            rid,
            {
                "id": rid,
                "title": _text(s.get("title")) or NO_TEXT,
                "where": _text(s.get("bucket_label")),
                "count": 0,
                "last": "",
                "basis": [],
            },
        )
        g["count"] += 1
        seen_at = _text(s.get("seen_at"))
        if seen_at > g["last"]:
            g["last"] = seen_at
        basis = _text(s.get("basis"))
        words = BASIS_WORDS.get(basis, basis)
        if words and words not in g["basis"]:
            g["basis"].append(words)
    ordered = sorted(groups.values(), key=lambda g: g["last"], reverse=True)  # newest first
    return sorted(ordered, key=lambda g: -g["count"])  # then most-seen first (stable)


def _followups(report: dict) -> list[dict]:
    return [
        {
            "id": _text(f.get("id")),
            "action": _text(f.get("action")),
            "unblocks_on": f.get("unblocks_on") or "",
            "routed_at": f.get("routed_at") or "",
        }
        for f in _list(report.get("open_followups"))
    ]


def build_health(
    report: Any,
    metrics: Any,
    supply_mix: Any,
    status_buckets: Any,
    *,
    query: str = "",
    show_all: bool = False,
) -> dict:
    """Everything ``report.html`` shows, ready to print. *report* ``None``
    (the CLI failed) gives an empty page model; the route shows the CLI's
    error above it."""
    report = report if isinstance(report, dict) else {}
    series = report.get("series") if isinstance(report.get("series"), dict) else None
    rules = _rule_rows(report)
    total = len(rules)
    q = query.strip().lower()
    if q:
        rules = [r for r in rules if q in f"{r['title']} {r['what']} {r['where']}".lower()]
    matched = len(rules)
    shown = rules if show_all else rules[:DEFAULT_LIMIT]
    return {
        "tiles": _tiles(report, metrics, status_buckets),
        "series": series,
        "supply_mix": supply_mix if isinstance(supply_mix, dict) else None,
        "rules": shown,
        "rules_total": total,
        "rules_matched": matched,
        "rules_hidden": matched - len(shown),
        "query": query.strip(),
        "show_all": show_all,
        "seen_again": _seen_again(report),
        "followups": _followups(report),
        "counters": _counters(report, metrics, supply_mix),
        "has_report": bool(report),
    }
