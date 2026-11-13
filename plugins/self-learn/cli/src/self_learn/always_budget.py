"""always_budget.py — the word budget of the user's always-loaded lessons (S-147).

The user's rule (2026-08-19): "user scope surfaces should only contain lessons
that address high value issues that recur frequently across many sessions and
many projects." The combined test (`always_loaded.py`) judges one lesson at a
time, and one at a time nearly everything passes: by 2026-11-12 the user's
`CLAUDE.md` carried 47 lesson lines, about 4,700 words, read into every
session. A report-only signal (`report.context_budget`) said so and changed
nothing.

This module makes the size a limit the system keeps itself:

* ``always_loaded.user_word_budget`` (default :data:`DEFAULT_WORDS`; 0 turns
  it off) is the most words the lesson lines of the user's `CLAUDE.md` may
  hold together. Hand-written sections of that file are not counted and are
  never touched.
* **Over the budget, lines leave.** The daily premise sweep derives a fourth
  placement premise, ``@budget``, for every lesson placed there
  (:func:`standings`): the lines are ranked by how often sessions were seen
  meeting them, the best-ranked fill the budget, and every line past it fails
  ``@budget``. A failing placement premise is an input of the nightly steward
  (`steward_inputs.placement_moves`), which moves the lesson somewhere cheaper
  (a warning hook, a path-scoped rule, a project, a skill), retires it, or
  keeps it by evidencing the combined test again.
* **At the budget, no line enters.** A steward case that would put a lesson
  into the user's `CLAUDE.md` past the budget is refused at the stage check
  (:func:`route_problem`); the brief says to choose a cheaper destination.
  The overseer and a person are not gated: they are told the numbers.

Nothing here calls a model or writes the ledger. Lesson text is never kept:
only ids, counts and dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "DEFAULT_WORDS",
    "FIRE_WINDOW_DAYS",
    "GRACE_DAYS",
    "PREMISE_ID",
    "SETTING",
    "Line",
    "Standing",
    "budget_words",
    "entry_words",
    "failing_value",
    "fire_stats",
    "route_problem",
    "standings",
    "summary",
    "user_lines",
]

#: The setting's name in the registry (`settings.py`).
SETTING = "always_loaded.user_word_budget"
#: Words of lesson lines the user's CLAUDE.md may hold. About fifteen lessons
#: at their usual length; the orchestrator's choice of 2026-11-12 under the
#: user's instruction to enforce a budget, theirs to change.
DEFAULT_WORDS = 1500
#: A line placed fewer days ago than this is not asked to leave yet: nothing
#: could have been seen meeting it. It still counts against the budget.
GRACE_DAYS = 14
#: How far back a recorded fire counts toward a line's rank.
FIRE_WINDOW_DAYS = 90
#: The placement premise the sweep derives (`premises.PLACEMENT_PREMISE_IDS`).
PREMISE_ID = "@budget"

_ID_RE = re.compile(r"\((lrn-[0-9a-f]{8})\)")
_SESSION_RE = re.compile(r"^transcript:([^#\s]+)")


@dataclass(frozen=True)
class Line:
    """One lesson line of the user's always-loaded file, as counted."""

    record_id: str
    words: int
    fires: int = 0
    sessions: int = 0
    recurrences: int = 0
    placed_at: datetime | None = None


@dataclass(frozen=True)
class Standing:
    """Where one line stands against the budget. ``over`` is the failing
    state of ``@budget``; ``rank`` counts from 1, best kept first."""

    record_id: str
    over: bool
    grace: bool
    rank: int
    of: int
    words: int
    fires: int
    sessions: int
    total_words: int
    budget: int

    def shown(self) -> str:
        return (
            f"{self.total_words} of {self.budget} words; this line {self.words} words, "
            f"rank {self.rank} of {self.of}"
        )

    def detail(self) -> str:
        return (
            f"the lesson lines of the user's CLAUDE.md hold {self.total_words} words against a "
            f"budget of {self.budget}; this one is {self.words} words, seen met "
            f"{self.fires} time(s) in {self.sessions} session(s) in {FIRE_WINDOW_DAYS} days"
        )


def budget_words(home: Path | str) -> int:
    """``always_loaded.user_word_budget`` (0 = no budget). A registry that
    does not know the name, or a value that is not a number, reads as the
    default."""
    from . import settings  # late: a registry module

    try:
        value, _source = settings.resolve_setting(Path(home), settings.by_name(SETTING))
        return max(int(value), 0)  # type: ignore[call-overload]
    except (KeyError, TypeError, ValueError):
        return DEFAULT_WORDS


def entry_words(region_text: str) -> dict[str, int]:
    """Words of each lesson's entry in a managed region, by the lesson id the
    entry's line ends with (the last ``(lrn-…)`` on a line is its own). Lines
    that name no lesson (a heading) are not counted."""
    out: dict[str, int] = {}
    for line in region_text.splitlines():
        ids = _ID_RE.findall(line)
        if ids:
            out[ids[-1]] = out.get(ids[-1], 0) + len(line.split())
    return out


def fire_stats(
    events: Iterable[Mapping[str, Any]], *, now: datetime, window_days: int = FIRE_WINDOW_DAYS
) -> dict[str, tuple[int, int]]:
    """``record id -> (fires, distinct sessions)`` over the `fire` events of
    the last *window_days*. A fire is a moment the miner saw a session meet
    the lesson, kept or broken; it is a suspected match, good enough to rank
    by and never proof on its own."""
    since = (now - timedelta(days=window_days)).isoformat()
    fires: dict[str, int] = {}
    sessions: dict[str, set[str]] = {}
    for event in events:
        if event.get("kind") != "fire" or not isinstance(event.get("record"), str):
            continue
        if str(event.get("ts", "")) < since[:19]:
            continue
        rid = str(event["record"])
        fires[rid] = fires.get(rid, 0) + 1
        for key in ("action", "origin"):
            match = _SESSION_RE.match(str(event.get(key) or ""))
            if match:
                sessions.setdefault(rid, set()).add(match.group(1))
    return {rid: (count, len(sessions.get(rid, ()))) for rid, count in fires.items()}


def _keep_key(line: Line) -> tuple:
    """Best kept first: met in more sessions, met more often, came back more
    often after being placed, then the cheaper line, then the id (stable)."""
    return (-line.sessions, -line.fires, -line.recurrences, line.words, line.record_id)


def standings(lines: Iterable[Line], budget: int, today: date) -> dict[str, Standing]:
    """Every line's standing. With no budget (0) nothing is over. Lines in
    their first :data:`GRACE_DAYS` days are charged first and never over; the
    rest fill what is left in rank order, and a line that does not fit, and
    every line ranked after it, is over."""
    ordered = sorted(lines, key=_keep_key)
    total = sum(line.words for line in ordered)
    out: dict[str, Standing] = {}

    def in_grace(line: Line) -> bool:
        return line.placed_at is not None and (today - line.placed_at.date()).days < GRACE_DAYS

    used = sum(line.words for line in ordered if in_grace(line))
    full = False
    for position, line in enumerate(ordered, start=1):
        grace = in_grace(line)
        over = False
        if budget > 0 and not grace:
            if full or used + line.words > budget:
                over, full = True, True
            else:
                used += line.words
        out[line.record_id] = Standing(
            line.record_id, over, grace, position, len(ordered), line.words,
            line.fires, line.sessions, total, budget,
        )
    return out


def failing_value(budget: int, today: date) -> str:
    """What a failing ``@budget`` is observed as. The same for every night of
    a month, so the sweep's two-in-a-row count holds; a new month, or a
    changed budget, is a new value, so a line the steward chose to keep while
    the file stayed over the budget is asked about again."""
    return f"over:{budget}:{today.year:04d}-{today.month:02d}"


def user_lines(
    home: Path | str,
    region_text: str,
    records: Mapping[str, Any],
    *,
    now: datetime | None = None,
    events: Iterable[Mapping[str, Any]] | None = None,
) -> list[Line]:
    """The lines of the user's managed region as :class:`Line` rows.
    *records*: ``record id -> Record`` for the lessons placed there (for the
    placement date and recurrences); an entry whose lesson is not among them
    is still counted, with nothing known about it."""
    from . import telemetry  # late
    from .primitives import chrono

    moment = now or datetime.now(timezone.utc)
    if events is None:
        try:
            events = telemetry.read_events(Path(home))
        except Exception:  # noqa: BLE001 -- no telemetry: everything ranks as unseen
            events = []
    stats = fire_stats(events, now=moment)
    lines: list[Line] = []
    for rid, words in entry_words(region_text).items():
        record = records.get(rid)
        routing = getattr(record, "routing", None) or {}
        fires, sessions = stats.get(rid, (0, 0))
        lines.append(Line(
            rid, words, fires, sessions,
            len(getattr(record, "recurrences", None) or []),
            chrono.to_dt(routing.get("routed_at")) if isinstance(routing, Mapping) else None,
        ))
    return lines


def _user_region_text(claude_dir: Path) -> str | None:
    from . import compiled  # late

    path = claude_dir / "CLAUDE.md"
    try:
        region = compiled.region_bytes(path.read_text(encoding="utf-8"), "managed")
    except (OSError, UnicodeDecodeError, compiled.CompiledRecordError):
        return None
    return region.decode("utf-8", errors="replace") if region is not None else ""


def summary(home: Path | str, claude_dir: Path | None = None) -> dict[str, Any]:
    """The numbers, for a report or a brief: the budget, the words and lines
    the user's CLAUDE.md holds now, and how far over it is. ``state`` is
    ``off`` (no budget), ``unreadable``, ``within`` or ``over``."""
    budget = budget_words(home)
    if claude_dir is None:
        from .selfcheck import claude_runtime_dir  # late

        claude_dir = claude_runtime_dir()
    text = _user_region_text(Path(claude_dir))
    if text is None:
        return {"budget": budget, "state": "unreadable"}
    words = entry_words(text)
    total = sum(words.values())
    state = "off" if budget <= 0 else ("over" if total > budget else "within")
    return {
        "budget": budget, "state": state, "words": total, "lines": len(words),
        "over_by": max(total - budget, 0) if budget > 0 else 0,
    }


def _record_words(record: Any) -> int:
    """About what a lesson's line will cost: the words of its body, less the
    section headings."""
    body = str(getattr(record, "body", "") or "")
    return len(" ".join(
        line for line in body.splitlines() if not line.startswith("## ")
    ).split())


def route_problem(
    home: Path | str,
    case_data: Mapping[str, Any],
    items: Iterable[Any],
    *,
    label: str = "case",
    claude_dir: Path | None = None,
) -> str | None:
    """Why the steward's runner refuses this case, or ``None`` (S-147): a
    decided case whose sheet puts a lesson into the user's `CLAUDE.md` when
    the lesson lines there would then pass the budget. Counted for a `route`
    or `replace` line whose `dest` is `claude-md` on a lesson of the user
    bucket (or sent there with `to: user`) that is not already a line of
    that file. A parked case is never applied, so it is never refused; a
    lesson that cannot be read is left to the verb's own refusal."""
    if case_data.get("kind") == "parked":
        return None
    budget = budget_words(home)
    if budget <= 0:
        return None
    from . import ledger_ops  # late

    home = Path(home)
    entering: dict[str, int] = {}
    for item in items:
        if not isinstance(item, Mapping) or item.get("verb") not in ("route", "replace"):
            continue
        if item.get("dest") != "claude-md":
            continue
        rid = str(item.get("id"))
        try:
            path = ledger_ops.find_record_path(home, rid)
            record = ledger_ops.read_record_or_refuse(path)
        except Exception:  # noqa: BLE001 -- unreadable: the verb refuses it by name
            continue
        to = item.get("to")
        in_user = (to == "user") if to is not None else (path.parent.parent.name == "user")
        if not in_user:
            continue
        routing = record.routing or {}
        if (
            item.get("verb") == "route" and record.status == "routed"
            and routing.get("destination") == "claude-md" and routing.get("variant") is None
            and path.parent.parent.name == "user"
        ):
            continue  # already a line of that file
        if item.get("verb") == "replace":
            words = len(" ".join(
                str(item.get(key) or "") for key in ("trigger", "instruction", "fact", "context")
            ).split()) or _record_words(record)
            if (
                record.status == "routed" and routing.get("destination") == "claude-md"
                and routing.get("variant") is None and path.parent.parent.name == "user"
            ):
                words = max(words - _record_words(record), 0)  # it replaces its own line
        else:
            words = _record_words(record)
        if words:
            entering[rid] = words
    if not entering:
        return None
    now = summary(home, claude_dir)
    if now.get("state") not in ("within", "over"):
        return None
    after = int(now["words"]) + sum(entering.values())
    if after <= budget:
        return None
    return (
        f"{label}: {sorted(entering)} would enter the user's CLAUDE.md, which every session "
        f"loads: its lesson lines hold {now['words']} words now and would hold about {after} "
        f"against a budget of {budget} (`{SETTING}`). The budget is a hard limit for you. "
        "Choose a cheaper destination (a warning hook for a rule about one call, "
        "`claude-md:rules:<topic>` with `rules_paths` for one tied to files, the project it "
        "belongs to, an existing skill), or park the case (always-loaded-user-scope) when "
        "nothing cheaper can reach the moment: the overseer weighs it against the lines "
        "already there"
    )
