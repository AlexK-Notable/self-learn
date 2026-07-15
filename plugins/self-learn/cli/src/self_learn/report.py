"""``self-learn report`` — the facts layer, v1 (11 §5).

v1 walks record files and tracked telemetry directly; the SQLite index
becomes the engine at M2 (the one deliberate divergence from "report
always builds the index", pinned in 11 §5). Everything here is derived,
regenerated on every run, and committed nowhere.

Honesty pins carried from 11 §4.3/§5:

- **Capture rate is bounded, never measured.** The declined-offer count
  is model-emitted best-effort, so it is a LOWER bound on true declines —
  which makes the computed capture rate an optimistic CEILING. Both
  labels are printed; neither number is presented as a measurement.
- **No-observed-fires is a candidate list, not "dead weight"** — fire
  observation doesn't exist until the M2 miner, so v1 prints the routed
  rules with their ages and says observation hasn't started, rather than
  implying silence means uselessness.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from .ledger import discover_buckets
from .ledger_ops import open_followups
from .records import Record, RecordError
from .telemetry import read_events

__all__ = ["gather", "render_json", "render_text"]


def _days_since(value, today: date) -> int | None:
    if value is None:
        return None
    text = str(value)[:10]
    try:
        then = date.fromisoformat(text)
    except ValueError:
        return None
    return (today - then).days


def gather(home: Path | str, *, today: date | None = None) -> dict:
    """Walk every bucket + the tracked telemetry plane into one facts map."""
    home = Path(home)
    today = today if today is not None else datetime.now(timezone.utc).date()

    buckets: list[dict] = []
    destinations: Counter = Counter()
    routed_ever = 0  # any record that carries a routing block
    superseded_after_routing = 0
    graduated = 0
    rejected = 0
    routed_live = []  # currently-routed rules (the attention-tax payers)
    deferred: list[dict] = []

    for bucket in discover_buckets(home):
        counts = Counter()
        for sub in ("pending", "resolved"):
            directory = bucket.path / sub
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                except RecordError:
                    continue
                counts[record.status] += 1
                if record.routing is not None:
                    routed_ever += 1
                if record.status == "routed":
                    destinations[(record.routing or {}).get("destination")] += 1
                    routed_live.append(
                        {
                            "id": record.id,
                            "bucket": bucket.name,
                            "routed_days_ago": _days_since(
                                (record.routing or {}).get("routed_at"), today
                            ),
                            "last_confirmed": (
                                str(record.last_confirmed)
                                if record.last_confirmed is not None
                                else None
                            ),
                            "recurrences": len(record.recurrences),
                        }
                    )
                elif record.status == "rejected":
                    rejected += 1
                elif record.status == "superseded":
                    if record.superseded_by == "canon":
                        graduated += 1
                    elif record.routing is not None:
                        superseded_after_routing += 1
                elif record.status == "deferred":
                    deferred.append(
                        {
                            "id": record.id,
                            "bucket": bucket.name,
                            "until": str(record.deferred_until),
                            # positive = past due; filled below
                            "overdue_days": None,
                        }
                    )
        buckets.append(
            {"bucket": bucket.name, "scope": bucket.scope, "counts": dict(counts)}
        )

    for entry in deferred:  # positive = past due
        entry["overdue_days"] = _days_since(entry["until"], today)

    events = read_events(home)
    kinds: Counter = Counter(e.get("kind") for e in events)
    decline_reasons: Counter = Counter(
        e.get("reason", "unspecified")
        for e in events
        if e.get("kind") == "offer-declined"
    )
    captures = kinds.get("capture", 0)
    declined = kinds.get("offer-declined", 0)
    capture_ceiling = (
        captures / (captures + declined) if (captures + declined) else None
    )

    supersede_rate = (
        superseded_after_routing / routed_ever if routed_ever else None
    )

    return {
        "generated": str(today),
        "buckets": buckets,
        "destinations": dict(destinations),
        "routed_live": sorted(
            routed_live, key=lambda r: -(r["routed_days_ago"] or 0)
        ),
        "routed_ever": routed_ever,
        "superseded_after_routing": superseded_after_routing,
        "supersede_rate": supersede_rate,
        "graduated": graduated,
        "rejected": rejected,
        "open_followups": open_followups(home),
        "deferred": deferred,
        "telemetry": {
            "events_by_kind": dict(kinds),
            "decline_reasons": dict(decline_reasons),
            "captures": captures,
            "declined_logged": declined,
            "capture_rate_ceiling": capture_ceiling,
        },
    }


def render_json(facts: dict) -> str:
    return json.dumps(facts)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100)}%"


def render_text(facts: dict) -> str:
    lines: list[str] = [f"self-learn report — {facts['generated']}"]

    lines.append("")
    lines.append("Lessons by bucket:")
    for b in facts["buckets"]:
        counts = b["counts"]
        if not counts:
            continue
        parts = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
        lines.append(f"  {b['bucket']} ({b['scope']}): {parts}")
    if facts["destinations"]:
        parts = ", ".join(
            f"{n} → {dest}" for dest, n in sorted(facts["destinations"].items())
        )
        lines.append(f"  live routed rules by destination: {parts}")

    lines.append("")
    lines.append(
        f"Iteration: {facts['routed_ever']} routed ever · "
        f"{facts['superseded_after_routing']} later replaced "
        f"(supersede rate {_pct(facts['supersede_rate'])}) · "
        f"{facts['graduated']} graduated into authored canon · "
        f"{facts['rejected']} rejected"
    )

    followups = facts["open_followups"]
    lines.append("")
    if followups:
        lines.append(f"Open follow-ups ({len(followups)}) — planned upgrades:")
        for fu in followups:
            gate = f" (unblocks on {fu['unblocks_on']})" if fu["unblocks_on"] else ""
            lines.append(f"  {fu['id']} [{fu['bucket']}]: {fu['action']}{gate}")
    else:
        lines.append("Open follow-ups: none")

    deferred = facts["deferred"]
    if deferred:
        lines.append("")
        lines.append(f"Deferred ({len(deferred)}):")
        for d in deferred:
            overdue = d.get("overdue_days")
            when = (
                f"due {abs(overdue)}d ago — will resurface in review"
                if isinstance(overdue, int) and overdue > 0
                else f"until {d['until']}"
            )
            lines.append(f"  {d['id']} [{d['bucket']}]: {when}")

    t = facts["telemetry"]
    lines.append("")
    lines.append("Offer ledger (11 §4.3 — the declined count is a LOWER bound;")
    lines.append("logging a decline is model discipline, so the capture rate")
    lines.append("below is an optimistic CEILING, not a measurement):")
    lines.append(
        f"  {t['captures']} captured · ≥{t['declined_logged']} declined (logged)"
        f" · capture rate ≤ {_pct(t['capture_rate_ceiling'])}"
    )
    if t["decline_reasons"]:
        parts = ", ".join(
            f"{n}× {reason}" for reason, n in sorted(t["decline_reasons"].items())
        )
        lines.append(f"  decline reasons: {parts}")
    if t["events_by_kind"]:
        parts = ", ".join(
            f"{n} {kind}" for kind, n in sorted(t["events_by_kind"].items())
        )
        lines.append(f"  telemetry events on file: {parts}")
    else:
        lines.append("  no telemetry on file yet")

    routed_live = facts["routed_live"]
    if routed_live:
        lines.append("")
        lines.append(
            "Routed rules with no observed activity — NOT dead weight: fire"
        )
        lines.append(
            "observation starts with the M2 miner, and a silently-working"
        )
        lines.append("rule fires without a trace. Candidates for a human")
        lines.append("still-good? check (confirm-held lands at M2):")
        for r in routed_live:
            age = (
                f"routed {r['routed_days_ago']}d ago"
                if r["routed_days_ago"] is not None
                else "routing date unknown"
            )
            confirmed = (
                f", last confirmed {r['last_confirmed']}"
                if r["last_confirmed"]
                else ", never confirmed since"
            )
            lines.append(f"  {r['id']} [{r['bucket']}]: {age}{confirmed}")

    return "\n".join(lines)
