"""The overseer's catalogue-health row for always-loaded lines that have
gone quiet, and the population module's zero-fire nudge for the same
lessons: both count the right records, and the row names its window.

Two defects, measured 2026-10-05 against the live ledger (the overseer
reported 44 "always-loaded entries that have never fired"):

1. ``_always_loaded_ids`` returned EVERY routed user-scope record, so
   lessons routed to a reference shelf, a path-scoped rule, a skill or a
   hook were counted as if they were lines in the always-loaded
   ``CLAUDE.md`` (31 of the 44 were real ones).
2. ``gather`` looked at fires since ``now - 7 days`` and the row was named
   "never fired".

``population._always_loaded_zero_fire_nudges`` had the first defect too (every
routed user-scope record got an ``always-loaded-zero-fire`` nudge); it now asks
the same helper ``health`` uses. Its own window (fires since the week's start)
is a per-week nudge, not the health count, and stays as it was.

These tests drive ``health.gather`` and ``population.nudges`` over a scratch
ledger. Each absence assertion has a positive control checked first: the record
that SHOULD be listed is listed, and the fire that SHOULD be read is read.
"""

from __future__ import annotations

import json
from pathlib import Path

from self_learn import telemetry
from self_learn.overseer import health, population
from self_learn.records import Record
from support import days_ago, make_home


def _write_routed(
    home: Path, record_id: str, *, destination: str, variant: str | None = None
) -> None:
    """A user-scope record routed to *destination*, written straight into
    ``user/resolved`` (the pattern ``test_context_budget`` uses). The
    routing block stores the destination and, for a ``claude-md`` route,
    an optional ``variant`` (``rules`` / ``local``)."""
    record = Record.create(
        type="behavior",
        scope="user",
        source="teach",
        kind="anti-pattern",
        trigger=f"About to do the thing {record_id} guards.",
        instruction="Do the corrective thing.",
        record_id=record_id,
    )
    routing: dict = {"routed_at": days_ago(60), "destination": destination, "by": "human"}
    if variant is not None:
        routing["variant"] = variant
    record.set_routing(routing)
    record.set_status("routed")
    resolved = home / "user" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record.write(resolved / f"{record_id}.md")


def _write_fire(home: Path, record_id: str, *, days: int) -> None:
    """One ``fire`` telemetry event for *record_id*, *days* days old."""
    line = json.dumps(
        {
            "ts": days_ago(days),
            "kind": "fire",
            "record": record_id,
            "outcome": "suspected-compliance",
        }
    )
    tdir = home / "telemetry"
    tdir.mkdir(parents=True, exist_ok=True)
    with (tdir / "fires.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _health_row(home: Path) -> dict:
    """The always-loaded row of the health packet. It is found by a
    substring of its kind that does not depend on how the row is named
    ("never fired" or "no fire in 30 days"), so a failure here is a wrong
    answer and never a missing row. Exactly one row must match."""
    rows = [row for row in health.gather(home) if "always-loaded" in str(row.get("kind"))]
    assert len(rows) == 1, f"expected exactly one always-loaded row, got {rows!r}"
    return rows[0]


def test_only_always_loaded_destinations_are_counted(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    # Always-loaded: a claude-md route with no variant, and the project-local
    # CLAUDE.local.md route (`local`), per always_loaded.is_always_loaded.
    _write_routed(home, "lrn-00000001", destination="claude-md")
    _write_routed(home, "lrn-00000002", destination="claude-md", variant="local")
    # Not always-loaded: a reference shelf, a path-scoped rule (claude-md with
    # the `rules` variant), a skill and a hook each load some other way.
    _write_routed(home, "lrn-00000003", destination="reference")
    _write_routed(home, "lrn-00000004", destination="claude-md", variant="rules")
    _write_routed(home, "lrn-00000005", destination="skill")
    _write_routed(home, "lrn-00000006", destination="hook")

    value = _health_row(home)["value"]

    # Positive control first: the always-loaded routes ARE listed, so the
    # absence assertions below are about the filter, not an empty row.
    assert "lrn-00000001" in value
    assert "lrn-00000002" in value
    assert value == ["lrn-00000001", "lrn-00000002"], (
        "the row counted lessons that are not always-loaded lines"
    )


def test_a_fire_inside_thirty_days_keeps_the_record_out_of_the_count(
    tmp_path: Path,
) -> None:
    home = make_home(tmp_path)
    _write_routed(home, "lrn-0000000a", destination="claude-md")  # fired 20 days ago
    _write_routed(home, "lrn-0000000b", destination="claude-md")  # fired 40 days ago
    _write_routed(home, "lrn-0000000c", destination="claude-md")  # never fired
    _write_fire(home, "lrn-0000000a", days=20)
    _write_fire(home, "lrn-0000000b", days=40)

    # Positive control for the fixture: both fires are on disk and readable,
    # so a record's absence from the row is the window at work.
    fired = {
        str(event["record"])
        for event in telemetry.read_events(home)
        if event.get("kind") == "fire"
    }
    assert fired == {"lrn-0000000a", "lrn-0000000b"}

    value = _health_row(home)["value"]

    # The 40-day fire is outside any window this row could use, and a record
    # that never fired is outside all of them: both must be listed.
    assert "lrn-0000000b" in value
    assert "lrn-0000000c" in value
    # A fire 20 days ago is inside 30 days, outside 7: the record is not quiet.
    assert "lrn-0000000a" not in value, "a 20-day-old fire was not counted as a fire"
    assert value == ["lrn-0000000b", "lrn-0000000c"]


def test_the_row_names_its_window_instead_of_saying_never(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    _write_routed(home, "lrn-000000d1", destination="claude-md")

    row = _health_row(home)

    # Positive control: the row is the populated one the other tests read.
    assert row["value"] == ["lrn-000000d1"]
    assert row.get("window_days") == 30
    assert "30 days" in str(row.get("label"))
    # The label says what the number measures: no recorded fire in a window.
    for text in (str(row["kind"]), str(row.get("label"))):
        assert "never" not in text.lower(), f"{text!r} still claims 'never'"
    assert "Silence is not retirement evidence" in row["caution"]


# ------------------------------------------------ the zero-fire nudge (twin)

#: An old week start: no fire the tests write is older than it, so a record
#: gets the nudge exactly when it has no fire at all.
_OLD_WEEK = "2020-01-01T00:00:00Z"


def _zero_fire_ids(home: Path, week: str = _OLD_WEEK) -> list[str]:
    """Ids carrying an ``always-loaded-zero-fire`` nudge, through the public
    ``population.nudges`` entry point the overseer's runner calls."""
    offered = population.nudges(home, population._empty_coverage(), week)
    return [n["id"] for n in offered if n["kind"] == "always-loaded-zero-fire"]


def test_zero_fire_nudge_goes_to_always_loaded_lines_only(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    _write_routed(home, "lrn-00000001", destination="claude-md")
    _write_routed(home, "lrn-00000002", destination="claude-md", variant="local")
    _write_routed(home, "lrn-00000003", destination="reference")
    _write_routed(home, "lrn-00000004", destination="claude-md", variant="rules")
    _write_routed(home, "lrn-00000005", destination="skill")
    _write_routed(home, "lrn-00000006", destination="hook")

    ids = _zero_fire_ids(home)

    # Positive control first: the always-loaded routes DO get the nudge, so
    # the absence assertions below are about the filter, not a nudge that
    # never fires.
    assert "lrn-00000001" in ids
    assert "lrn-00000002" in ids
    assert ids == ["lrn-00000001", "lrn-00000002"], (
        "a lesson that is not an always-loaded line was nudged as one"
    )
    # One definition: the health row (no fires, so its window is moot) names
    # the same lessons as the nudge.
    assert _health_row(home)["value"] == ids


def test_zero_fire_nudge_keeps_its_own_week_window(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    _write_routed(home, "lrn-000000e1", destination="claude-md")  # fired 3 days ago
    _write_routed(home, "lrn-000000e2", destination="claude-md")  # fired 20 days ago
    _write_routed(home, "lrn-000000e3", destination="claude-md")  # never fired
    _write_fire(home, "lrn-000000e1", days=3)
    _write_fire(home, "lrn-000000e2", days=20)

    ids = _zero_fire_ids(home, week=days_ago(7))

    # Positive control: the record with no fire at all is nudged.
    assert "lrn-000000e3" in ids
    # A fire inside the week silences the nudge...
    assert "lrn-000000e1" not in ids
    # ...and a fire before the week does not: this is a per-week nudge, not
    # the 30-day health count.
    assert ids == ["lrn-000000e2", "lrn-000000e3"]
