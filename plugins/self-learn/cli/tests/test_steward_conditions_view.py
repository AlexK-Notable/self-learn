"""2026-09-26 -- the steward's cut of the conditions feed (the "machine
description").

The user, 2026-09-26 17:46 PDT: "cut it down and let me know what we're
left with." The rows cut, the two per-lesson slices and the compact
rendering are the orchestrator's choices (build spec
`misc/steward-context-2026-09-26/SPEC.md`, Part A), grounded in the
2026-09-20 forensic count of which rows 26 real cases ever cited.

`conditions.feed` itself is unchanged: the overseer reads it whole
(`overseer/run.py`'s `health.yaml`) and filtered (`overseer/health.py`'s
conditions diff), and both need the rows the steward no longer sees."""

from __future__ import annotations

import pytest

from self_learn import conditions, report, steward_prompt
from self_learn.ledger_ops import create_record
from self_learn.overseer import health
from support import commit_all, make_behavior, make_home


def _keys(items) -> set[str]:
    return {item.key for item in items}


# ----------------------------------------------------------- A1: the cut


def test_the_steward_view_leaves_out_the_rows_no_case_ever_used(tmp_path):
    home = make_home(tmp_path)
    full = _keys(conditions.feed(home))
    # Positive control: the full feed carries every row the cut removes.
    for key in (
        "report.destinations", "report.open_followups", "report.recurrence_suspects",
        "models.worker", "models.overseer", "sdk.max_turns.steward",
        "status.total_pending", "steward.last_run_at", "overseer.last_run_at",
    ):
        assert key in full, key
    assert any(k.startswith("host.") and k.endswith(".head") for k in full)

    view = _keys(conditions.steward_feed(home, []))

    for key in view:
        assert not key.startswith(("status.", "sdk.max_turns.", "steward.", "overseer.")), key
        assert not (key.startswith("host.") and key.endswith(".head")), key
        assert not key.startswith("models.") or key == "models.steward", key
    assert not view & {
        "report.destinations", "report.open_followups", "report.recurrence_suspects",
    }
    # What stays: the rows the real cases cited.
    for key in (
        "models.steward", "ledger.head", "surface.output-style.active",
        "report.buckets", "report.deferred", "report.reference_shelf",
        "report.context_budget", "report.routed_live", "report.surface_reach",
    ):
        assert key in view, key
    assert any(k.startswith("host.") and k.endswith(".mode") for k in view)


def test_the_overseer_still_receives_every_row_the_steward_no_longer_sees(tmp_path):
    home = make_home(tmp_path)
    current = _keys(health._current_condition_items(home))
    assert any(k.startswith("host.") and k.endswith(".head") for k in current)
    assert {"models.worker", "status.total_pending", "report.destinations"} <= current


# ------------------------------------------------- A3: the per-lesson slices


def test_routed_live_keeps_the_lessons_buckets_by_scope_and_name_and_the_named_records():
    rows = [
        {"id": "lrn-00000001", "bucket": "foo", "routed_days_ago": 3},
        {"id": "lrn-00000002", "bucket": "foo", "routed_days_ago": 2},  # projects/foo, same NAME
        {"id": "lrn-00000003", "bucket": "user", "routed_days_ago": 1},
        {"id": "lrn-00000004", "bucket": "bar", "routed_days_ago": 9},  # named by a lesson
    ]
    bucket_of = {
        "lrn-00000001": "skills/foo",
        "lrn-00000002": "projects/foo",
        "lrn-00000003": "user",
        "lrn-00000004": "skills/bar",
    }
    kept = conditions.slice_routed_live(
        rows, buckets={"skills/foo"}, named={"lrn-00000004"}, bucket_of=bucket_of,
    )
    assert [row["id"] for row in kept] == ["lrn-00000001", "lrn-00000004"]
    assert kept[0] == rows[0], "a kept row is unchanged"


def test_surface_reach_keeps_the_counts_and_every_why_of_the_rows_it_keeps():
    value = {
        "checked": 4, "reachable": 3, "unreachable": 1,
        "by_destination": {"hook": {"reachable": 0, "unreachable": 1}},
        "rows": [
            {"record_id": "lrn-00000001", "bucket": "user", "state": "reachable",
             "detail": "the user CLAUDE.md the loader reads at session start"},
            {"record_id": "lrn-00000002", "bucket": "projects/a", "state": "reachable",
             "detail": "an ancestor host"},
            {"record_id": "lrn-00000003", "bucket": "projects/b", "state": "unreachable",
             "detail": "an unrelated host"},
            {"record_id": "lrn-00000004", "bucket": "skills/x", "state": "reachable",
             "detail": "named by a lesson"},
        ],
    }
    kept = conditions.slice_surface_reach(
        value, buckets={"user", "projects/a"}, named={"lrn-00000004"},
    )
    assert [row["record_id"] for row in kept["rows"]] == [
        "lrn-00000001", "lrn-00000002", "lrn-00000004",
    ]
    assert kept["rows"][0]["detail"] == "the user CLAUDE.md the loader reads at session start"
    for key in ("checked", "reachable", "unreachable", "by_destination"):
        assert kept[key] == value[key], key
    assert len(value["rows"]) == 4, "the input is not mutated"


def _seed(home, scope, record_id, *, project_path=None):
    create_record(home, make_behavior(scope=scope, record_id=record_id), project_path=project_path)


def test_run_lessons_resolves_buckets_ancestors_and_named_records_from_the_ledger(tmp_path):
    home = make_home(tmp_path)
    outer = tmp_path / "outer"
    inner = outer / "inner"
    other = tmp_path / "other"
    for path in (outer, inner, other):
        path.mkdir(parents=True, exist_ok=True)
    _seed(home, "project", "lrn-0000000a", project_path=inner)
    _seed(home, "project", "lrn-0000000b", project_path=outer)
    _seed(home, "project", "lrn-0000000c", project_path=other)
    _seed(home, "skill:s", "lrn-0000000d")
    commit_all(home, "seed")

    lessons = conditions.run_lessons(
        home, [("lrn-0000000a", {"advice": "overlaps lrn-0000000d, keep both"})],
    )

    inner_key = lessons.bucket_of["lrn-0000000a"]
    outer_key = lessons.bucket_of["lrn-0000000b"]
    other_key = lessons.bucket_of["lrn-0000000c"]
    assert inner_key.startswith("projects/") and inner_key != outer_key
    assert lessons.own_buckets == {inner_key}
    assert lessons.reach_buckets == {inner_key, outer_key, "user"}
    assert other_key not in lessons.reach_buckets
    assert "lrn-0000000d" in lessons.named


def test_the_steward_feed_slices_routed_live_to_this_runs_lessons(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed(home, "skill:s", "lrn-0000000a")
    _seed(home, "user", "lrn-0000000b")
    commit_all(home, "seed")
    real_gather = report.gather

    def gathered(home_, **kwargs):
        facts = real_gather(home_, **kwargs)
        facts["routed_live"] = [
            {"id": "lrn-0000000a", "bucket": "s"},
            {"id": "lrn-0000000b", "bucket": "user"},
        ]
        return facts

    monkeypatch.setattr(conditions.report_mod, "gather", gathered)
    full = {it.key: it for it in conditions.feed(home)}
    assert len(full["report.routed_live"].value) == 2, "positive control"

    view = {it.key: it for it in conditions.steward_feed(home, [("lrn-0000000a", {})])}

    assert [row["id"] for row in view["report.routed_live"].value] == ["lrn-0000000a"]
    assert conditions.SLICE_ROUTED_LIVE in view["report.routed_live"].source
    assert conditions.SLICE_SURFACE_REACH in view["report.surface_reach"].source


def test_a_slice_that_cannot_be_computed_sends_the_whole_section_and_says_so(tmp_path, monkeypatch):
    home = make_home(tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("walk failed on purpose")

    monkeypatch.setattr(conditions, "run_lessons", broken)
    view = {it.key: it for it in conditions.steward_feed(home, [("lrn-0000000a", {})])}
    assert "walk failed on purpose" in view["report.routed_live"].source
    assert "whole" in view["report.routed_live"].source


# ------------------------------------------------- A2: the compact rendering


def test_report_sections_render_as_cited_yaml_sub_blocks_not_python_repr(tmp_path):
    at = "2026-09-26T11:07:04Z"
    leaf_colon = "reads: the loader, at session start"
    leaf_quote = "it's \"quoted\" here"
    leaf_long = "word " * 60
    leaf_unicode = "doubling in ~110 days — über budget"
    items = [
        conditions.Item("ledger.head", "d286fad2", at, "gitops.head_sha(home)"),
        conditions.Item("models.steward", "claude-fable-5-1", at, "settings"),
        conditions.Item(
            "report.context_budget",
            {"zeta": 1, "alpha": {"why": leaf_colon, "q": leaf_quote},
             "rows": [{"long": leaf_long, "u": leaf_unicode, "none": None, "flag": True}]},
            at, "report.gather(home)",
        ),
    ]
    text = steward_prompt._render_conditions(items)

    table, _, sections = text.partition(f"cond:report.context_budget@{at}")
    assert sections, "the report section has its own sub-block, headed by its citation"
    assert "| ledger.head | d286fad2 |" in table
    assert "| models.steward | claude-fable-5-1 |" in table
    assert "report.context_budget" not in table.split("|---|", 1)[1]
    assert "{'" not in text and "None" not in text and "True" not in text
    # Every leaf is a contiguous substring: no line wrapping, no escaping.
    for leaf in (leaf_colon, leaf_quote, leaf_long.strip(), leaf_unicode):
        assert leaf in sections, leaf
    assert sections.index("alpha:") < sections.index("rows:") < sections.index("zeta:"), "sorted keys"
    assert steward_prompt._render_conditions(items) == text, "deterministic"


def test_the_conditions_block_says_how_to_cite_it(tmp_path):
    text = steward_prompt._render_conditions([])
    assert "cond:<key>@<observed_at>" in text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_the_run_slices_to_every_lesson_of_the_run_not_one_packets(tmp_path, monkeypatch):
    """A3: computed once per run, over the whole run's lessons, so every
    packet's conditions block is the same text."""
    from self_learn import steward
    from test_steward import _configure_steward, _seed_fresh_proposals, _write_decision_stage

    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _configure_steward(home, packet_size=1)  # two packets
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    seen: list[list[str]] = []
    real = conditions.steward_feed

    def spied(home_, lessons, cache_dir=None):
        lessons = list(lessons)
        seen.append([record_id for record_id, _ in lessons])
        return real(home_, lessons, cache_dir)

    monkeypatch.setattr(steward.conditions, "steward_feed", spied)

    result = steward.run(home)

    assert result.calls == 2, "positive control: two packets, two model calls"
    assert seen == [ids]
