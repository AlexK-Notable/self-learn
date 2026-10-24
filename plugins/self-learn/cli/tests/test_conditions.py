"""U9 (code half) — `conditions.py`: the conditions feed (interface §4;
`02-schema.md` §3a.5; plan-steward §4.4).

Every test here relies on the suite-wide autouse fixture in
`conftest.py` (`_worker_test_defaults`) that already points
`SELF_LEARN_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, and
`SELF_LEARN_CLAUDE_DIR` at per-test tmp paths — no test here needs to set
those itself unless it wants a DIFFERENT specific path (the real-``~/.
claude``-never-touched control below is the one that does).
"""

from __future__ import annotations

import json


from self_learn import cases, conditions, gitops, hosts, user_model, worker
from self_learn.ledger_ops import create_record
from self_learn.overseer import population
from support import commit_all, make_behavior, make_home

# The real-~/.claude positive control (fold r1, D-h) — reused verbatim
# from test_hook_activation.py rather than re-derived, same convention
# that module itself uses to import from test_route_hook.
from test_hook_activation import (  # noqa: F401  (fixture + helper reused)
    _real_claude_dir_never_touched,
    _snapshot_claude_dir,
)


def _item_map(items) -> dict:
    return {it.key: it for it in items}


# --------------------------------------------------------- basic shape


def test_every_item_has_nonempty_observed_at_and_source(tmp_path):
    home = make_home(tmp_path)
    items = conditions.feed(home)
    assert items, "feed() returned nothing"
    for it in items:
        assert it.observed_at, f"{it.key} has empty observed_at"
        assert it.source, f"{it.key} has empty source"


def test_report_keys_all_present(tmp_path):
    home = make_home(tmp_path)
    by_key = _item_map(conditions.feed(home))
    for suffix in (
        "buckets", "destinations", "routed_live", "open_followups",
        "recurrence_suspects", "deferred", "reference_shelf",
        "context_budget", "surface_reach",
    ):
        assert f"report.{suffix}" in by_key


def test_status_keys_all_present(tmp_path):
    home = make_home(tmp_path)
    by_key = _item_map(conditions.feed(home))
    for key in (
        "status.total_pending", "status.unanalyzed_total",
        "status.intents_probe", "status.intents_stopped_count",
    ):
        assert key in by_key
    assert by_key["status.intents_probe"].value == "ok"
    assert by_key["status.intents_stopped_count"].value == 0


def test_ledger_head_matches_gitops(tmp_path):
    home = make_home(tmp_path)
    by_key = _item_map(conditions.feed(home))
    assert by_key["ledger.head"].value == gitops.head_sha(home)


def test_host_items_present_for_registered_git_host(tmp_path):
    # make_home() registers the paired host-repo as BOTH skills_root and
    # a project (support.py's make_env) — both default (no `mode:`) to
    # "git", and the host repo IS git-initialized.
    home = make_home(tmp_path)
    parsed = hosts.load_hosts(home)
    resolved = str(parsed.skills_root.resolve())
    by_key = _item_map(conditions.feed(home))
    assert by_key[f"host.{resolved}.mode"].value == "git"
    assert by_key[f"host.{resolved}.head"].value == gitops.head_sha(parsed.skills_root)


def test_steward_and_overseer_run_records_absent_are_unavailable(tmp_path):
    home = make_home(tmp_path)
    by_key = _item_map(conditions.feed(home))
    for key in (
        "steward.last_run_at", "steward.last_run_outcome",
        "overseer.last_run_at", "overseer.last_examined_at",
    ):
        assert by_key[key].value == "unavailable", key
    # the count is a real reading from the first case on, never a placeholder
    assert by_key["steward.cases_since_overseer"].value == 0


def test_declared_items_split_key_and_value_from_title(tmp_path):
    home = make_home(tmp_path)
    user_model.add_entry(
        home, container="E",
        title="declared.host.self-learn.claude-md: local",
        because="test fixture", source="own-words", by="human",
        ref="stmt-test1",
    )
    user_model.add_entry(
        home, container="E",
        title="declared.config-outer-repo-has-no-remote",
        because="test fixture", source="own-words", by="human",
        ref="stmt-test2",
    )
    by_key = _item_map(conditions.feed(home))
    assert by_key["declared.host.self-learn.claude-md"].value == "local"
    assert by_key["declared.config-outer-repo-has-no-remote"].value == "true"


def test_models_and_max_turns_settings_present(tmp_path):
    home = make_home(tmp_path)
    by_key = _item_map(conditions.feed(home))
    for name in (
        "models.worker", "models.miner", "models.analyst",
        "models.steward", "models.overseer",
    ):
        assert name in by_key
    max_turns_keys = [k for k in by_key if k.startswith("sdk.max_turns.")]
    assert max_turns_keys, "no sdk.max_turns.* items emitted"


# ------------------------------------------ test 5: fail-closed visibility


def test_unreadable_hosts_yaml_yields_unavailable_host_star_items(tmp_path):
    home = make_home(tmp_path)
    (home / "hosts.yaml").write_text("not: [valid, yaml: :::", encoding="utf-8")
    items = conditions.feed(home)
    by_key = _item_map(items)
    assert by_key["host.*.mode"].value == "unavailable"
    assert by_key["host.*.head"].value == "unavailable"
    # never a missing key: no item may silently vanish because a source
    # failed — every other group's keys must still be present.
    assert "ledger.head" in by_key
    assert "status.total_pending" in by_key


def test_missing_settings_json_yields_unavailable_output_style(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    claude_dir = tmp_path / "claude-no-settings"
    claude_dir.mkdir()
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
    by_key = _item_map(conditions.feed(home))
    assert by_key["surface.output-style.active"].value == "unavailable"


# --------------------------------------------------- test 6: withholding


def test_feed_never_leaks_a_lesson_body_or_telemetry_text(tmp_path):
    home = make_home(tmp_path)
    marker = "PLANTED-BODY-TEXT-U9-do-not-leak"
    record = make_behavior(
        record_id="lrn-aa00fead",
        trigger=f"About to do something involving {marker}.",
        instruction=f"Never do the thing with {marker} again.",
    )
    path = create_record(home, record)
    from self_learn.records import Record

    written = Record.from_path(path)
    written.set_status("routed")
    written.set_routing(
        {"routed_at": "2026-01-01T00:00:00Z", "destination": "skill-md", "by": "test"}
    )
    written.write(path)

    items = conditions.feed(home)
    rendered = "\n".join(f"{it.key}={it.value}|{it.source}" for it in items)
    assert marker not in rendered

    # Positive control: the record's id DOES surface (a count/identity,
    # never its body) — report.routed_live carries it.
    by_key = _item_map(items)
    routed_ids = [row.get("id") for row in by_key["report.routed_live"].value]
    assert "lrn-aa00fead" in routed_ids


# ---------------------------------------- own extra mutation (declared.*)


# ------------------------------------------- O-3: overseer run timestamps


def _write_coverage_with_two_stamped_strata(home) -> tuple[list[str], dict]:
    coverage_path = home / "overseer" / "coverage.yaml"
    data = population.load_coverage(coverage_path)
    keys = sorted(data["strata"])
    assert len(keys) >= 2, "O-1's fixed strata set is smaller than expected"
    data["strata"][keys[0]]["last_examined_at"] = "2026-09-01T00:00:00Z"
    data["strata"][keys[1]]["last_examined_at"] = "2026-09-08T00:00:00Z"
    data["last_run_at"] = "2026-09-14T00:00:00Z"
    data["last_examined_at"] = "2026-09-12T00:00:00Z"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.write_text(population.render_coverage(data), encoding="utf-8")
    return keys, data


def test_overseer_run_dates_are_direct_top_level_coverage_facts(tmp_path):
    home = make_home(tmp_path)
    _write_coverage_with_two_stamped_strata(home)
    by_key = _item_map(conditions.feed(home))
    assert by_key["overseer.last_examined_at"].value == "2026-09-12T00:00:00Z"
    assert by_key["overseer.last_run_at"].value == "2026-09-14T00:00:00Z"


# ---------------------------------------- fold r1: S8 (happy-path values)


def test_report_models_and_output_style_values_are_not_unavailable_on_a_healthy_home(
    tmp_path, monkeypatch
):
    """S8: `test_report_keys_all_present` and
    `test_models_and_max_turns_settings_present` assert key PRESENCE
    only; a feed that always answered "unavailable" would still pass
    them. This is the positive-value control the gate's probe P6 used:
    a healthy home plus a real `settings.json`, none of report.*/
    models.*/sdk.max_turns.* may read "unavailable", and the output
    style must equal the real configured value."""
    home = make_home(tmp_path)
    claude_dir = tmp_path / "claude-with-settings"
    claude_dir.mkdir()
    claude_dir.joinpath("settings.json").write_text(
        json.dumps({"outputStyle": "fold-r1-happy-path-style"}), encoding="utf-8"
    )
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))

    by_key = _item_map(conditions.feed(home))
    for key in by_key:
        if key.startswith("report.") or key.startswith("models.") or key.startswith(
            "sdk.max_turns."
        ):
            assert by_key[key].value != "unavailable", (key, by_key[key].source)
    assert by_key["surface.output-style.active"].value == "fold-r1-happy-path-style"


def test_a_cache_run_projection_no_longer_feeds_the_steward_rows(tmp_path):
    """Until 2026-09-22 the steward rows read the newest
    `<cache_dir>/steward/runs/<run_id>/run.json`, expecting keys the
    projection never carried. That file is now ignored entirely: the rows
    read the committed run records (see the tests at the end of this
    file), so a cache file spelling the old keys changes nothing."""
    home = make_home(tmp_path)
    cache_dir = tmp_path / "cache"
    runs_dir = cache_dir / "steward" / "runs" / "run-s8"
    runs_dir.mkdir(parents=True)
    (runs_dir / "run.json").write_text(
        json.dumps({
            "last_run_at": "2026-09-12T03:30:00Z",
            "last_run_outcome": "completed",
            "cases_since_overseer": 3,
        }),
        encoding="utf-8",
    )
    by_key = _item_map(conditions.feed(home, cache_dir))
    assert by_key["steward.last_run_at"].value == "unavailable"
    assert by_key["steward.last_run_outcome"].value == "unavailable"
    assert by_key["steward.cases_since_overseer"].value == 0


# --------------------------------------------------------- fold r1: N1


def test_status_items_producers_fail_independently(tmp_path, monkeypatch):
    """N1: `worker.fast_status` and `intents.classify_status` used to
    share one `try`, so either producer's failure blanked all four
    `status.*` keys. Break only `worker.fast_status` and confirm the
    OTHER producer's two keys still carry real values."""
    home = make_home(tmp_path)

    def _broken_fast_status(home):
        raise RuntimeError("fold r1 N1 fixture: fast_status broken on purpose")

    monkeypatch.setattr(worker, "fast_status", _broken_fast_status)
    by_key = _item_map(conditions.feed(home))
    assert by_key["status.total_pending"].value == "unavailable"
    assert by_key["status.unanalyzed_total"].value == "unavailable"
    # the OTHER producer never touched -- still real values.
    assert by_key["status.intents_probe"].value == "ok"
    assert by_key["status.intents_stopped_count"].value == 0


# --------------------------------------------------------- fold r1: N2


def test_feed_survives_output_style_and_cache_dir_producer_failures(tmp_path, monkeypatch):
    """N2: `_output_style_item` and the `cache_dir` fallback used to sit
    outside any try/except in `feed()`, so the docstring's "never raises"
    claim was broader than the guards. Break both and confirm `feed()`
    still returns (with the affected keys "unavailable"), not raise.
    `worker.cache_dir` is also called INSIDE `worker.fast_status`
    (`_status_items`'s own producer), so breaking it globally correctly
    cascades into `status.*` too, via that producer's OWN (N1) guard --
    this test only pins the group with no such dependency (`ledger.head`)
    as the untouched control."""
    home = make_home(tmp_path)

    def _broken_output_style_item(observed_at):
        raise RuntimeError("fold r1 N2 fixture: output style broken on purpose")

    def _broken_cache_dir(home=None):
        raise RuntimeError("fold r1 N2 fixture: cache_dir broken on purpose")

    monkeypatch.setattr(conditions, "_output_style_item", _broken_output_style_item)
    monkeypatch.setattr(worker, "cache_dir", _broken_cache_dir)

    items = conditions.feed(home)  # must not raise -- this is the whole point
    by_key = _item_map(items)
    assert by_key["surface.output-style.active"].value == "unavailable"
    # (the steward rows used to be asserted here too; since 2026-09-22 they
    # read the committed run records, not the cache, and have their own
    # broken-source test at the end of this file.)
    # a group with no cache_dir/output-style dependency stays real.
    assert by_key["ledger.head"].value != "unavailable"


# ------------------------ 2026-09-22: the steward rows read the committed run


def _commit_completed_steward_run(home, run_id: str, completed_at: str, outcome: str) -> None:
    runs = home / "cases" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "actor": "steward", "status": "complete", "outcome": outcome,
        "started_at": completed_at, "completed_at": completed_at, "packets": [], "cases": {},
    }, indent=2) + "\n", encoding="utf-8")
    commit_all(home, f"steward manifest {run_id} (complete)")


def test_steward_rows_read_the_newest_completed_committed_run(tmp_path):
    """Until 2026-09-22 these three rows read a cache projection whose keys
    never carried their names, so every real run's brief said
    "unavailable" for the steward's own last run. They now read the
    committed run records: the newest COMPLETED run's `completed_at` and
    `outcome`, and the live count of steward cases since the overseer."""
    home = make_home(tmp_path)
    _commit_completed_steward_run(home, "run-0000000a", "2026-09-12T03:30:00Z", "applied")
    _commit_completed_steward_run(home, "run-0000000b", "2026-09-20T03:30:00Z", "partial")
    # an UNFINISHED run, newer still: never the "last run"
    (home / "cases" / "runs" / "run-0000000c.json").write_text(json.dumps({
        "run_id": "run-0000000c", "actor": "steward", "status": "unfinished", "outcome": None,
        "started_at": "2026-09-21T03:30:00Z", "completed_at": None, "packets": [], "cases": {},
    }) + "\n", encoding="utf-8")
    commit_all(home, "steward manifest run-0000000c (unfinished)")
    rid = "lrn-0c0d0e0f"
    create_record(home, make_behavior(record_id=rid))
    commit_all(home, "record seed")
    stage = tmp_path / "steward-case.yaml"
    stage.write_text(json.dumps({
        "kind": "resolution", "trigger": "nightly", "outcome": "reject", "records": [rid],
        "scope": "skill:s", "question": "keep this lesson?",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "reject", "because": "too narrow", "confidence": "settled"},
    }), encoding="utf-8")
    cases.record(home, stage, actor="steward")

    by_key = _item_map(conditions.feed(home))

    assert by_key["steward.last_run_at"].value == "2026-09-20T03:30:00Z"
    assert by_key["steward.last_run_outcome"].value == "partial"
    assert "run-0000000b" in by_key["steward.last_run_at"].source
    assert by_key["steward.cases_since_overseer"].value == 1


def test_steward_rows_are_unavailable_when_the_run_records_cannot_be_read(tmp_path, monkeypatch):
    from self_learn import steward

    home = make_home(tmp_path)

    def _broken(home_):
        raise RuntimeError("run records broken on purpose")

    monkeypatch.setattr(steward, "committed_manifests", _broken)

    by_key = _item_map(conditions.feed(home))  # must not raise

    for key in ("steward.last_run_at", "steward.last_run_outcome", "steward.cases_since_overseer"):
        assert by_key[key].value == "unavailable", key
        assert "broken on purpose" in by_key[key].source
    assert by_key["ledger.head"].value != "unavailable"


def test_host_rows_are_not_doubled_when_the_skills_root_is_also_a_project(tmp_path):
    """make_home() registers the paired host repo as BOTH the skills root
    and a project, exactly the live ledger's shape; the feed used to emit
    that host's mode and head rows twice."""
    home = make_home(tmp_path)
    parsed = hosts.load_hosts(home)
    resolved = str(parsed.skills_root.resolve())
    assert any(str(p.resolve()) == resolved for p in parsed.projects), "positive control: doubled registration"

    items = conditions.feed(home)

    assert [it.key for it in items].count(f"host.{resolved}.mode") == 1
    assert [it.key for it in items].count(f"host.{resolved}.head") == 1
