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
    "claude-md:local": "Local instructions file",
    "claude-md:rules": "Rules file",
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

#: Why a sighting was dismissed (``verbs.DISMISS_REASONS``), in words.
DISMISS_WORDS: dict[str, str] = {
    "rule-followed": "The rule was followed",
    "unrelated": "Not about this rule",
    "duplicate": "Already counted",
    "misattributed": "Matched to the wrong rule",
    "other": "Another reason",
}

#: What a bucket's lesson counts are called (``report --json`` ``buckets[].counts``
#: keys are lesson statuses). Unknown statuses show as recorded.
STATUS_WORDS: dict[str, str] = {
    "pending": "waiting for a decision",
    "deferred": "put off",
    "routed": "in use",
    "superseded": "replaced by a better rule",
    "graduated": "retired",
    "rejected": "turned down",
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
    if scope == "user":
        # a user-level hook, skill or rule applies to all your work; the
        # user bucket's label ("Your instructions") would misread as "the
        # hook lives in the instructions file"
        return kind, "For all your work"
    return kind, label


def _fmt_number(name: str, value: float) -> str:
    if name.endswith(("_rate", "_ceiling")):
        pct = round(value * 100, 1)
        return f"{int(pct)}%" if pct == int(pct) else f"{pct}%"
    if name.endswith("_pct"):
        return f"{value:g}%"
    return f"{round(value, 2):g}"


def _entries(n: int) -> str:
    return "1 entry" if n == 1 else f"{n} entries"


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]], depth: int = 0) -> None:
    """Counters as ``(CLI name, value in words)``. Dicts open up (up to
    four levels); a list becomes a count of entries; booleans become
    yes/no."""
    if isinstance(value, dict) and depth < 4:
        for key, inner in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), inner, out, depth + 1)
    elif isinstance(value, bool):
        out.append((prefix, "yes" if value else "no"))
    elif isinstance(value, (int, float)):
        out.append((prefix, _fmt_number(prefix.rsplit(".", 1)[-1], value) if isinstance(value, float) else str(value)))
    elif isinstance(value, (list, tuple)):
        out.append((prefix, _entries(len(value))))
    elif isinstance(value, dict):
        out.append((prefix, _entries(len(value))))
    elif value is None:
        out.append((prefix, "none"))
    else:
        out.append((prefix, str(value)))


def _counters(report: dict, metrics: Any, supply_mix: Any) -> list[tuple[str, str]]:
    """Every key of ``report --json`` (in its own order), then ``status
    --json``'s ``metrics`` and ``supply_mix``, under their CLI names. A
    list of rows (the rule tables, the per-rule reach rows) shows as its
    entry count here; the readable versions sit in the sections above."""
    out: list[tuple[str, str]] = []
    for name, value in report.items():
        _flatten(str(name), value, out)
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
    if not metrics:  # status could not be read: say so, never "no lesson decided yet"
        wait_value, wait_note = NOT_KNOWN, ""
    elif isinstance(wait, (int, float)) and not isinstance(wait, bool):
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
        seen = _int(r.get("recurrences"))  # None when the CLI sent none: "not known", never 0
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
                "seen_words": NOT_KNOWN if seen is None else str(seen),
            }
        )
    rows.sort(
        key=lambda x: (
            -(x["seen"] if x["seen"] is not None else -1),
            -(x["age"] if x["age"] is not None else -1),
            x["title"],
        )
    )
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


def _place_names(report: dict) -> list[dict]:
    return [b for b in _list(report.get("buckets"))]


def _place_label(report: dict, bucket: str) -> str:
    """A place's name in words. ``deferred`` and the context budget name a
    place by its bucket name or by the short key its name ends in; look the
    label up in ``buckets`` (an ambiguous or unknown name shows as sent)."""
    if not bucket:
        return ""
    exact = [b for b in _place_names(report) if b.get("bucket") == bucket]
    if len(exact) == 1:
        return _text(exact[0].get("label")) or bucket
    ends = [b for b in _place_names(report) if _text(b.get("bucket")).endswith(f"-{bucket}")]
    if len(ends) == 1:
        return _text(ends[0].get("label")) or bucket
    return bucket


def _destinations_line(report: dict) -> str:
    d = report.get("destinations")
    if not isinstance(d, dict):
        return ""
    pairs = [(str(k), _int(v)) for k, v in d.items()]
    pairs = sorted(((k, n) for k, n in pairs if n is not None), key=lambda p: -p[1])
    if not pairs:
        return ""
    return "By kind: " + ", ".join(f"{n} {KIND_WORDS.get(k, k).lower()}" for k, n in pairs) + "."


def _due_words(overdue: Any) -> str:
    n = _int(overdue)
    if n is None:
        return ""
    if n > 0:
        return f"{n} day overdue" if n == 1 else f"{n} days overdue"
    if n == 0:
        return "due today"
    return "due tomorrow" if n == -1 else f"due in {-n} days"


def _deferred_rows(report: dict) -> list[dict]:
    rows = []
    for r in _list(report.get("deferred")):
        rows.append(
            {
                "id": _text(r.get("id")),
                "where": _place_label(report, _text(r.get("bucket"))),
                "until": r.get("until") or "",
                "due": _due_words(r.get("overdue_days")),
                "overdue": (_int(r.get("overdue_days")) or 0) > 0,
            }
        )
    # most overdue first
    rows.sort(key=lambda x: x["overdue"], reverse=True)
    return rows


def _dismissed_rows(report: dict) -> list[dict]:
    titles = {_text(r.get("id")): _text(r.get("title")) for r in _list(report.get("routed_live"))}
    rows = []
    for r in _list(report.get("suspects_dismissed")):
        rid = _text(r.get("id"))
        basis = _text(r.get("basis"))
        why = _text(r.get("why"))
        rows.append(
            {
                "id": rid,
                "title": titles.get(rid) or "A rule that is no longer in use",
                "linked": bool(titles.get(rid)),
                "on": r.get("dismissed_at") or "",
                "why": DISMISS_WORDS.get(why, why),
                "basis": BASIS_WORDS.get(basis, basis),
            }
        )
    rows.sort(key=lambda x: str(x["on"]), reverse=True)
    return rows


def _reach(report: dict) -> dict | None:
    """``surface_reach``: whether a placed rule lands where the assistant
    reads it. The headline counts and the per-kind table; the per-rule rows
    stay in the CLI (they show as an entry count in the counters fold)."""
    sr = report.get("surface_reach")
    if not isinstance(sr, dict):
        return None
    by = sr.get("by_destination")
    by = by if isinstance(by, dict) else {}
    kinds = []
    for key, v in by.items():
        if not isinstance(v, dict):
            continue
        kinds.append(
            {
                "what": KIND_WORDS.get(str(key), str(key)),
                "reachable": _int(v.get("reachable")),
                "unreachable": _int(v.get("unreachable")),
                "unmeasurable": _int(v.get("unmeasurable")),
            }
        )
    return {
        "checked": _int(sr.get("checked")),
        "reachable": _int(sr.get("reachable")),
        "unreachable": _int(sr.get("unreachable")),
        "unmeasurable": _int(sr.get("unmeasurable")),
        "kinds": kinds,
    }


def _budget_rows(report: dict) -> list[dict]:
    cb = report.get("context_budget")
    budget = cb.get("budget") if isinstance(cb, dict) else None
    surfaces = budget.get("surfaces") if isinstance(budget, dict) else None
    rows = []
    for sfc in _list(surfaces):
        key = _text(sfc.get("key"))
        kind = _text(sfc.get("surface"))
        if kind == "user-claude-md":
            name = "Your instructions"
        else:
            name = _place_label(report, key) or key
        share = sfc.get("managed_share")
        rows.append(
            {
                "name": name,
                "state": _text(sfc.get("state")),
                "words": _int(sfc.get("file_words")),
                "written": _int(sfc.get("managed_words")),
                "share": f"{round(share * 100)}%" if isinstance(share, (int, float)) and not isinstance(share, bool) else "",
                "flagged": bool(sfc.get("flagged")),
            }
        )
    return rows


def _bucket_counts(report: dict) -> list[dict]:
    rows = []
    for b in _place_names(report):
        counts = b.get("counts")
        counts = counts if isinstance(counts, dict) else {}
        pairs = [(str(k), _int(v)) for k, v in counts.items()]
        pairs = [(k, n) for k, n in pairs if n]
        if not pairs:
            continue
        rows.append(
            {
                "name": _text(b.get("label")) or _text(b.get("bucket")),
                "path": _text(b.get("path")),
                "total": sum(n for _k, n in pairs),
                "words": ", ".join(f"{n} {STATUS_WORDS.get(k, k)}" for k, n in sorted(pairs, key=lambda p: -p[1])),
            }
        )
    rows.sort(key=lambda r: -r["total"])
    return rows


def _reference_note(report: dict) -> str:
    rs = report.get("reference_shelf")
    if not isinstance(rs, dict):
        return ""
    total = _int(rs.get("targets_total"))
    tracked = "" if total is None else f"{total} reference files are tracked. "
    if rs.get("instrumented") is False:
        state = _text(rs.get("instrument_state"))
        return tracked + "Reads of them are not being counted yet" + (f" ({state})." if state else ".")
    return tracked.strip()


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
        "limit": DEFAULT_LIMIT,
        "generated": _text(report.get("generated")),
        "destinations_line": _destinations_line(report),
        "deferred": _deferred_rows(report),
        "dismissed": _dismissed_rows(report),
        "reach": _reach(report),
        "budget": _budget_rows(report),
        "bucket_counts": _bucket_counts(report),
        "reference_note": _reference_note(report),
    }
