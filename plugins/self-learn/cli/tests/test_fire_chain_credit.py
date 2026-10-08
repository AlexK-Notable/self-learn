"""A replaced lesson keeps its fire credit.

The overseer's zero-fire nudge (``population._always_loaded_zero_fire_nudges``)
and its no-fire health row (``health.gather``) counted fires by record id. A
lesson replaced by ``supersede`` or by ``teach --supersedes`` starts at zero
fires under its new id, so the week after a shortening it drew a "never fired"
nudge and the health row listed it as quiet. That invites a wrong retirement.

The fix: a fire on any lesson in a replacement chain counts toward the live
lesson at the end of the chain. The chain is followed forward through the OLD
record's ``superseded_by`` while it names a record id (``lrn-...``). A
retirement (``covered_by:<kind>:<name>``, or the legacy ``canon``) is not a
replacement and earns no credit.

Three things shape these tests:

* ``_always_loaded_zero_fire_nudges`` swallows every exception and returns
  ``[]``. A "does not crash" assertion against it passes trivially when the
  code under test raised. Every test that reads the nudge list therefore also
  asserts that an unrelated, never-fired, always-loaded lesson IS still listed.
* A claim that something earns NO credit is true on a build that credits
  nobody, so it cannot fail on master by itself. Those tests carry a replacement
  chain in the same ledger whose credit master does not give, and say so; the
  negative half is checked by a mutation that makes the code credit what it
  must not (see the report that came with this file).
* A chain with a cycle must not hang the suite: an autouse alarm turns a hang
  into a plain failure.
"""

from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from self_learn.overseer import health, population
from self_learn.records import Record
from support import days_ago, make_home

#: An old week start: no fire these tests write is older than it, so for a
#: nudge test "a fire exists" and "the fire is inside the window" coincide.
_OLD_WEEK = "2020-01-01T00:00:00Z"


class _ChainWalkHung(BaseException):
    """Not an ``Exception`` on purpose: the nudge under test wraps its body in
    ``except Exception: return []``, which would swallow a plain error and
    leave the second call in the same test free to hang for good."""


@pytest.fixture(autouse=True)
def _no_hang():
    """Fail, never hang, if a chain walk loops. SIGALRM raises in the main
    thread, which is where these pure-Python walks run."""

    def _boom(signum, frame):
        raise _ChainWalkHung("fire-credit chain walk did not finish in 20s (loop?)")

    previous = signal.signal(signal.SIGALRM, _boom)
    signal.alarm(20)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


# ----------------------------------------------------------------- fixtures


def _write_lesson(
    home: Path,
    record_id: str,
    *,
    status: str = "routed",
    destination: str = "claude-md",
    superseded_by: str | None = None,
    supersedes: str | None = None,
    bucket: str = "user",
) -> None:
    """One record in ``<bucket>/resolved``. Every lesson here was routed once
    (an old lesson carries its routing block after it is replaced), so a
    lesson is "live" only through ``status: routed``."""
    record = Record.create(
        type="behavior",
        scope="user",
        source="teach",
        kind="anti-pattern",
        trigger=f"About to do the thing {record_id} guards.",
        instruction="Do the corrective thing.",
        record_id=record_id,
    )
    record.set_routing({"routed_at": days_ago(60), "destination": destination, "by": "human"})
    if supersedes is not None:
        record.set_supersedes(supersedes)
    record.set_status(status)
    if superseded_by is not None:
        record.set_superseded_by(superseded_by)
    resolved = home / bucket / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record.write(resolved / f"{record_id}.md")


def _replaced(home: Path, old_id: str, new_id: str, **kwargs) -> None:
    """*old_id* replaced by *new_id*, as ``supersede`` leaves it."""
    _write_lesson(home, old_id, status="superseded", superseded_by=new_id, **kwargs)


def _write_fire(home: Path, record_id: str, *, days: int) -> None:
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


def _health_value(home: Path) -> list[str]:
    """The ids on the no-fire health row (30-day window), exactly one row."""
    rows = [r for r in health.gather(home) if r.get("kind") == "no-fire-always-loaded"]
    assert len(rows) == 1, f"expected exactly one no-fire row, got {rows!r}"
    return rows[0]["value"]


def _nudged(home: Path, week: str = _OLD_WEEK) -> list[str]:
    """Ids carrying an ``always-loaded-zero-fire`` nudge, through the public
    ``population.nudges`` entry point the overseer's runner calls."""
    offered = population.nudges(home, population._empty_coverage(), week)
    return [n["id"] for n in offered if n["kind"] == "always-loaded-zero-fire"]


# ------------------------------------------------------ one step: the nudge


def test_fire_on_replaced_lesson_clears_the_successors_zero_fire_nudge(
    tmp_path: Path,
) -> None:
    home = make_home(tmp_path)
    # The credited pair: the old line fired, the new line (a shorter rewrite)
    # has not fired under its own id.
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_fire(home, "lrn-0000a001", days=3)
    # Control 1: a replaced pair where nothing fired. The successor MUST be
    # nudged, so "b001 absent" below is the fire credit and not a nudge that
    # never runs.
    _replaced(home, "lrn-0000a002", "lrn-0000b002")
    _write_lesson(home, "lrn-0000b002")
    # Control 2: an unrelated live lesson that never fired keeps its nudge, so
    # the credit does not leak past the chain.
    _write_lesson(home, "lrn-0000c001")

    ids = _nudged(home, week=days_ago(7))

    assert "lrn-0000b002" in ids and "lrn-0000c001" in ids, (
        "positive control: live lessons with no fire must be nudged"
    )
    assert "lrn-0000b001" not in ids, (
        "a fire on the replaced lesson was not credited to its successor"
    )
    assert ids == ["lrn-0000b002", "lrn-0000c001"]
    # The replaced lesson is no longer a live line and is never nudged itself.
    assert "lrn-0000a001" not in ids and "lrn-0000a002" not in ids


# ---------------------------------------------------- one step: the health row


def test_fire_on_replaced_lesson_clears_the_successor_on_the_health_row(
    tmp_path: Path,
) -> None:
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_fire(home, "lrn-0000a001", days=10)  # inside the 30-day window
    _replaced(home, "lrn-0000a002", "lrn-0000b002")
    _write_lesson(home, "lrn-0000b002")  # control: no fire anywhere in its chain
    _write_lesson(home, "lrn-0000c001")  # control: unrelated, never fired

    listed = _health_value(home)

    assert "lrn-0000b002" in listed and "lrn-0000c001" in listed, (
        "positive control: live lessons with no fire must be on the row"
    )
    assert "lrn-0000b001" not in listed, (
        "a fire on the replaced lesson was not credited to its successor"
    )
    assert listed == ["lrn-0000b002", "lrn-0000c001"]


# ------------------------------------------------------------ a two-step chain


@pytest.mark.parametrize("fired", ["lrn-0000a001", "lrn-0000b001"])
def test_two_step_chain_credits_the_live_end(tmp_path: Path, fired: str) -> None:
    """A -> B -> C, only C live. A fire on A, or on the middle B, reaches C on
    both surfaces. C is a rewrite of a rewrite."""
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _replaced(home, "lrn-0000b001", "lrn-0000c001")
    _write_lesson(home, "lrn-0000c001")
    _write_lesson(home, "lrn-0000d001")  # control: unrelated, never fired
    _write_fire(home, fired, days=2)

    nudged = _nudged(home, week=days_ago(7))
    listed = _health_value(home)

    assert "lrn-0000d001" in nudged and "lrn-0000d001" in listed, (
        "positive control: the unrelated live lesson is still reported"
    )
    assert nudged == ["lrn-0000d001"], f"chain end still nudged after a fire on {fired}"
    assert listed == ["lrn-0000d001"], f"chain end still on the row after a fire on {fired}"


def test_a_fire_on_the_end_of_the_chain_still_counts_and_credit_stays_in_its_chain(
    tmp_path: Path,
) -> None:
    """A fire on the live successor clears it, as it always did; a fire on one
    chain's old id clears that chain's successor and nothing else."""
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _replaced(home, "lrn-0000a002", "lrn-0000b002")
    _write_lesson(home, "lrn-0000b002")
    _replaced(home, "lrn-0000a003", "lrn-0000b003")
    _write_lesson(home, "lrn-0000b003")
    _write_fire(home, "lrn-0000b001", days=2)  # the successor itself fired
    _write_fire(home, "lrn-0000a002", days=2)  # only chain 2's OLD id fired
    # chain 3 never fired: its successor must stay reported (positive control)

    assert _nudged(home, week=days_ago(7)) == ["lrn-0000b003"]
    assert _health_value(home) == ["lrn-0000b003"]


# ----------------------------------------------------------------- the windows


def test_credit_keeps_each_surfaces_own_window(tmp_path: Path) -> None:
    """Credit is applied to the fires each surface already counts. A fire on
    the old id that is outside the window credits nothing."""
    home = make_home(tmp_path)
    # In-window chain (control; master does not credit it).
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_fire(home, "lrn-0000a001", days=3)
    # Out-of-window chain: the old id fired 40 days ago, before both windows.
    _replaced(home, "lrn-0000a002", "lrn-0000b002")
    _write_lesson(home, "lrn-0000b002")
    _write_fire(home, "lrn-0000a002", days=40)

    nudged = _nudged(home, week=days_ago(7))
    listed = _health_value(home)

    assert "lrn-0000b001" not in nudged and "lrn-0000b001" not in listed, (
        "the in-window fire on the old id was not credited"
    )
    assert nudged == ["lrn-0000b002"], "a fire before the week credited its successor"
    assert listed == ["lrn-0000b002"], "a fire before the 30-day window credited its successor"


# ------------------------------------------------------ a retirement is no chain


def test_a_retirement_earns_no_credit(tmp_path: Path) -> None:
    """``covered_by:<kind>:<name>`` and the legacy ``canon`` are retirements.
    The covering surface is not a successor lesson, whatever its name looks
    like. Master credits nobody, so the file's contrast is the replacement chain
    below: its credit is what fails on master.
    """
    home = make_home(tmp_path)
    # Contrast: a real replacement. This is the assertion master fails.
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_fire(home, "lrn-0000a001", days=2)

    # A retirement whose surface NAME is a live lesson's id. A walker that
    # reads the id out of the covered_by value would clear lrn-0000c001.
    _write_lesson(home, "lrn-0000c001")
    _write_lesson(
        home,
        "lrn-0000a002",
        status="superseded",
        superseded_by="covered_by:claude-md:lrn-0000c001",
    )
    _write_fire(home, "lrn-0000a002", days=2)

    # A retirement beside a live lesson that CLAIMS to supersede it
    # (`teach --supersedes` was captured, then the old lesson was retired
    # instead). A walker that follows `supersedes` backwards would clear it.
    _write_lesson(
        home, "lrn-0000a003", status="superseded", superseded_by="covered_by:reference:notes"
    )
    _write_lesson(home, "lrn-0000d001", supersedes="lrn-0000a003")
    _write_fire(home, "lrn-0000a003", days=2)

    # The legacy retirement literal.
    _write_lesson(home, "lrn-0000a004", status="superseded", superseded_by="canon")
    _write_lesson(home, "lrn-0000e001")
    _write_fire(home, "lrn-0000a004", days=2)

    nudged = _nudged(home, week=days_ago(7))
    listed = _health_value(home)

    # Positive control: the replacement credited, and the live lessons below
    # it are present on both surfaces, so the absences are about retirements.
    assert "lrn-0000b001" not in nudged and "lrn-0000b001" not in listed
    expected = ["lrn-0000c001", "lrn-0000d001", "lrn-0000e001"]
    assert nudged == expected, "a retirement's fire was credited to a live lesson"
    assert listed == expected, "a retirement's fire was credited to a live lesson"


# ------------------------------------------------------- cycles and dangling ids


def test_cycles_do_not_loop_or_crash(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    # A two-cycle and a self-reference: states no verb writes, so a hand-edited
    # or merge-damaged ledger is the only way to meet them.
    _replaced(home, "lrn-0000a001", "lrn-0000a002")
    _replaced(home, "lrn-0000a002", "lrn-0000a001")
    _replaced(home, "lrn-0000a003", "lrn-0000a003")
    _write_fire(home, "lrn-0000a001", days=2)
    _write_fire(home, "lrn-0000a003", days=2)
    # A cycle that runs through a live lesson: the live one still earns the
    # credit from the fire that reached it, and the walk ends.
    _replaced(home, "lrn-0000a004", "lrn-0000b004")
    _write_lesson(home, "lrn-0000b004", superseded_by="lrn-0000a004")
    _write_fire(home, "lrn-0000a004", days=2)
    # Controls: an ordinary credited chain and an unrelated live lesson. The
    # nudge swallows exceptions, so only these prove the code ran to the end.
    _replaced(home, "lrn-0000a005", "lrn-0000b005")
    _write_lesson(home, "lrn-0000b005")
    _write_fire(home, "lrn-0000a005", days=2)
    _write_lesson(home, "lrn-0000c001")

    nudged = _nudged(home, week=days_ago(7))
    listed = _health_value(home)

    assert nudged == ["lrn-0000c001"], f"nudge list after cycles: {nudged!r}"
    assert listed == ["lrn-0000c001"], f"health row after cycles: {listed!r}"


def test_a_dangling_successor_id_does_not_crash(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    # The old lesson names a successor whose file does not exist (a lost or
    # not-yet-synced record).
    _replaced(home, "lrn-0000a001", "lrn-0000dead")
    _write_fire(home, "lrn-0000a001", days=2)
    # A chain that breaks half-way: A -> B -> (missing). B is not live.
    _replaced(home, "lrn-0000a002", "lrn-0000b002")
    _replaced(home, "lrn-0000b002", "lrn-0000dea1")
    _write_fire(home, "lrn-0000a002", days=2)
    # Controls, as above.
    _replaced(home, "lrn-0000a005", "lrn-0000b005")
    _write_lesson(home, "lrn-0000b005")
    _write_fire(home, "lrn-0000a005", days=2)
    _write_lesson(home, "lrn-0000c001")

    nudged = _nudged(home, week=days_ago(7))
    listed = _health_value(home)

    assert nudged == ["lrn-0000c001"], f"nudge list with dangling ids: {nudged!r}"
    assert listed == ["lrn-0000c001"], f"health row with dangling ids: {listed!r}"


def test_an_unreadable_record_file_does_not_stop_the_credit(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_fire(home, "lrn-0000a001", days=2)
    _write_lesson(home, "lrn-0000c001")
    (home / "user" / "resolved" / "lrn-0000bad0.md").write_text(
        "not a record: no frontmatter at all\n", encoding="utf-8"
    )

    assert _nudged(home, week=days_ago(7)) == ["lrn-0000c001"]
    assert _health_value(home) == ["lrn-0000c001"]


# --------------------------------------------------------------------- buckets


def test_the_old_lesson_may_sit_in_another_bucket(tmp_path: Path) -> None:
    """``find_record_path`` locates a record across every bucket, so a chain
    can cross buckets: the replaced lesson here is a project-bucket record."""
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001", bucket="projects/-proj-12345678")
    _write_lesson(home, "lrn-0000b001")
    _write_lesson(home, "lrn-0000c001")
    _write_fire(home, "lrn-0000a001", days=2)

    assert _nudged(home, week=days_ago(7)) == ["lrn-0000c001"]
    assert _health_value(home) == ["lrn-0000c001"]


# -------------------------------------------------------------------- merges


@pytest.mark.parametrize("fired", ["lrn-0000a001", "lrn-0000a002"])
def test_a_merge_credits_the_successor_from_either_predecessor(
    tmp_path: Path, fired: str
) -> None:
    """Two old lessons replaced by ONE successor (a merge). A fire on either
    predecessor reaches it, including the later one in file order: a walk that
    keeps only the first predecessor of each successor loses the second."""
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _replaced(home, "lrn-0000a002", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_lesson(home, "lrn-0000c001")  # control: unrelated, never fired
    _write_fire(home, fired, days=2)

    nudged = _nudged(home, week=days_ago(7))
    listed = _health_value(home)

    assert "lrn-0000c001" in nudged and "lrn-0000c001" in listed, (
        "positive control: the unrelated live lesson is still reported"
    )
    assert nudged == ["lrn-0000c001"], f"merge successor nudged after a fire on {fired}"
    assert listed == ["lrn-0000c001"], f"merge successor on the row after a fire on {fired}"


# ------------------------------------------------- files that do not read back


def _write_non_utf8(home: Path, bucket: str, name: str) -> None:
    resolved = home / bucket / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    (resolved / name).write_bytes(b"\xff\xfe\x00 not utf-8")


def test_non_utf8_record_files_do_not_stop_the_credit_on_the_nudge(
    tmp_path: Path,
) -> None:
    """A record file that is not UTF-8, in the user bucket and in a project
    bucket, is skipped by the chain walk; the chain beside it is still
    credited.

    Not covered here: ``health.gather``. It raises on such a file BEFORE the
    credit runs, in ``report.gather`` -> ``ledger_ops.open_followups``
    (``Record.from_path`` with no ``UnicodeDecodeError`` catch). That is
    existing behaviour outside this change, and a test would pin a defect. The
    health row's own share of the work, ``health.credit_replacement_chains``,
    is checked directly in the next test."""
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_lesson(home, "lrn-0000c001")  # control: unrelated, never fired
    _write_fire(home, "lrn-0000a001", days=2)
    _write_non_utf8(home, "user", "lrn-0000bad1.md")
    _write_non_utf8(home, "projects/-proj-12345678", "lrn-0000bad2.md")
    # Positive control: the bad files are on disk and are not valid UTF-8, so
    # the walk really meets them.
    for bucket, name in (
        ("user", "lrn-0000bad1.md"),
        ("projects/-proj-12345678", "lrn-0000bad2.md"),
    ):
        with pytest.raises(UnicodeDecodeError):
            (home / bucket / "resolved" / name).read_text(encoding="utf-8")

    assert _nudged(home, week=days_ago(7)) == ["lrn-0000c001"]


def test_non_utf8_record_files_do_not_stop_the_health_helper(tmp_path: Path) -> None:
    """The health row's part of the credit, called directly because
    ``health.gather`` cannot get past a non-UTF-8 file for an unrelated reason
    (see the test above)."""
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _replaced(home, "lrn-0000b001", "lrn-0000c001")
    _write_lesson(home, "lrn-0000c001")
    _write_non_utf8(home, "user", "lrn-0000bad1.md")
    _write_non_utf8(home, "projects/-proj-12345678", "lrn-0000bad2.md")

    credited = health.credit_replacement_chains(home, {"lrn-0000a001"})

    assert credited == {"lrn-0000a001", "lrn-0000b001", "lrn-0000c001"}
    # Positive control that the result is not simply "everything": with no
    # fire there is nothing to credit.
    assert health.credit_replacement_chains(home, set()) == set()


# ------------------------------------------------- the two windows differ in width


def test_a_fire_between_the_two_windows_credits_the_row_but_not_the_nudge(
    tmp_path: Path,
) -> None:
    """The health row looks back 30 days; the nudge looks back to the start of
    the week. A predecessor fire 15 days ago is inside the first and outside
    the second, so the same fire clears the successor on the row and leaves the
    nudge standing."""
    home = make_home(tmp_path)
    _replaced(home, "lrn-0000a001", "lrn-0000b001")
    _write_lesson(home, "lrn-0000b001")
    _write_fire(home, "lrn-0000a001", days=15)
    # Control: a predecessor fire inside BOTH windows clears both surfaces.
    _replaced(home, "lrn-0000a002", "lrn-0000b002")
    _write_lesson(home, "lrn-0000b002")
    _write_fire(home, "lrn-0000a002", days=3)
    _write_lesson(home, "lrn-0000c001")  # control: unrelated, never fired

    nudged = _nudged(home, week=days_ago(7))
    listed = _health_value(home)

    assert "lrn-0000c001" in nudged and "lrn-0000c001" in listed
    assert "lrn-0000b002" not in nudged and "lrn-0000b002" not in listed, (
        "a fire inside both windows was not credited"
    )
    assert nudged == ["lrn-0000b001", "lrn-0000c001"], (
        "the nudge credited a fire from before the week"
    )
    assert listed == ["lrn-0000c001"], "the 30-day row did not credit a 15-day-old fire"


# ----------------------------------------------------------------------- label


def test_the_row_label_says_a_replaced_lessons_fires_count(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    _write_lesson(home, "lrn-0000c001")  # a populated row, not an absent one

    rows = [r for r in health.gather(home) if r.get("kind") == "no-fire-always-loaded"]

    assert len(rows) == 1 and rows[0]["value"] == ["lrn-0000c001"]
    label = str(rows[0]["label"])
    assert "30 days" in label
    assert "replaced lesson's fires count" in label
