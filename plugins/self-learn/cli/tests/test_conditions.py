"""U9 (code half) — `conditions.py`: the conditions feed (interface §4;
`02-schema.md` §3a.5; plan-steward §4.4).

Every test here relies on the suite-wide autouse fixture in
`conftest.py` (`_worker_test_defaults`) that already points
`SELF_LEARN_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, and
`SELF_LEARN_CLAUDE_DIR` at per-test tmp paths — no test here needs to set
those itself unless it wants a DIFFERENT specific path (the real-``~/.
claude``-never-touched control below is the one that does).

N5 (fold r1): the `test_negative_control_*` functions below monkeypatch
a BROKEN implementation and assert the mutated, wrong behaviour -- they
permanently document a defect shape for a future reader, they do not
guard against a regression the way every other test here does. Do not
read a green `test_negative_control_*` as coverage of the real code
path; the real guard is the un-prefixed test right above each one."""

from __future__ import annotations

import json

import pytest

from self_learn import conditions, gitops, hosts, user_model, worker
from self_learn.ledger_ops import create_record
from self_learn.overseer import population
from support import make_behavior, make_home

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
        "steward.cases_since_overseer", "overseer.last_run_at",
        "overseer.last_examined_at",
    ):
        assert by_key[key].value == "unavailable", key


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


def test_negative_control_hosts_yaml_exception_propagates_when_not_caught(tmp_path, monkeypatch):
    """Mutation for test 5 (build-u9.md): remove the fail-closed
    try/except around `hosts.load_hosts` and confirm `feed()` then
    RAISES instead of degrading — proves the try/except is load-bearing,
    not decorative. Patches a COPY of `_host_items` in place of the
    module's own (never edits the source file), so this test is the
    negative control by construction and needs no restore step."""
    home = make_home(tmp_path)
    (home / "hosts.yaml").write_text("not: [valid, yaml: :::", encoding="utf-8")

    def _unguarded_host_items(home, observed_at):
        parsed = hosts.load_hosts(home)  # no try/except: raises on garbage
        return []

    monkeypatch.setattr(conditions, "_host_items", _unguarded_host_items)
    with pytest.raises(hosts.HostsError):
        conditions.feed(home)


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


def test_negative_control_including_a_body_in_the_feed_is_caught(tmp_path, monkeypatch):
    """Mutation for test 6: monkeypatch `_report_items` to smuggle the
    record's own trigger text into an item value, proving the previous
    test's assertion actually fires red on a real leak."""
    home = make_home(tmp_path)
    marker = "PLANTED-BODY-TEXT-LEAK-CHECK"
    record = make_behavior(
        record_id="lrn-aa00feac",
        trigger=f"trigger mentioning {marker}",
    )
    path = create_record(home, record)

    real_report_items = conditions._report_items

    def _leaky_report_items(home, observed_at):
        out = real_report_items(home, observed_at)
        body_text = path.read_text(encoding="utf-8")
        out.append(
            conditions.Item("report.leak", body_text, observed_at, "test-mutation")
        )
        return out

    monkeypatch.setattr(conditions, "_report_items", _leaky_report_items)
    items = conditions.feed(home)
    rendered = "\n".join(f"{it.key}={it.value}" for it in items)
    assert marker in rendered  # RED under the mutation: the leak is visible


# ---------------------------------------- own extra mutation (declared.*)


def test_negative_control_declared_prefix_stripping_matters(tmp_path, monkeypatch):
    """Own mutation (brief: 'at least one of your own choosing'): if
    `_declared_items` stopped stripping a leading 'declared.' from the
    title before re-adding the prefix, the key would double up
    ('declared.declared.host...'). Prove the CURRENT code does not do
    that (green), then monkeypatch a version that skips the strip and
    show the key changes shape (red-equivalent: the un-stripped key is
    what a regression would produce, and it is absent from the real
    feed)."""
    home = make_home(tmp_path)
    user_model.add_entry(
        home, container="E", title="declared.some.key: value",
        because="fixture", source="own-words", by="human", ref="stmt-x",
    )
    by_key = _item_map(conditions.feed(home))
    assert "declared.some.key" in by_key
    assert "declared.declared.some.key" not in by_key  # regression shape, must be absent

    def _unstripped_declared_items(home, observed_at):
        containers = user_model.show(home)["containers"]
        out = []
        for entry in containers.get("E", []):
            title = (entry.get("title") or "").strip()
            key_part, sep, value_part = title.partition(": ")
            key = f"declared.{key_part.strip()}"  # BUG: no strip of existing prefix
            value = value_part.strip() if sep else "true"
            out.append(conditions.Item(key, value, observed_at, "mutated"))
        return out

    monkeypatch.setattr(conditions, "_declared_items", _unstripped_declared_items)
    mutated_by_key = _item_map(conditions.feed(home))
    assert "declared.declared.some.key" in mutated_by_key  # the bug shape, now present
    assert "declared.some.key" not in mutated_by_key  # RED: the correct key vanished


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


def test_negative_control_overseer_dates_derived_from_strata_are_caught(tmp_path, monkeypatch):
    """A reader deriving dates from strata reports different facts."""
    home = make_home(tmp_path)
    _write_coverage_with_two_stamped_strata(home)

    def _min_instead_of_max(home, observed_at):
        path = home / "overseer" / "coverage.yaml"
        data = population.load_coverage(path)
        oldest = None
        for entry in data["strata"].values():
            value = entry.get("last_examined_at")
            if isinstance(value, str) and (oldest is None or value < oldest):  # BUG: min
                oldest = value
        return [
            conditions.Item("overseer.last_run_at", "unavailable", observed_at, "mutated"),
            conditions.Item(
                "overseer.last_examined_at",
                oldest if oldest is not None else "unavailable",
                observed_at,
                "mutated",
            ),
        ]

    monkeypatch.setattr(conditions, "_overseer_run_items", _min_instead_of_max)
    by_key = _item_map(conditions.feed(home))
    assert by_key["overseer.last_examined_at"].value == "2026-09-01T00:00:00Z"  # RED: derived, not top-level


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


def test_steward_run_record_present_yields_real_timestamp_and_outcome(tmp_path):
    """S8's third fail-closed group: `steward.*` only has an
    absent-leg test (`test_steward_and_overseer_run_records_absent_are_
    unavailable`). Write a real `run.json` and confirm the newest one
    (by mtime) supplies real values, not "unavailable"."""
    home = make_home(tmp_path)
    cache_dir = tmp_path / "cache"
    runs_dir = cache_dir / "steward" / "runs" / "run-s8"
    runs_dir.mkdir(parents=True)
    (runs_dir / "run.json").write_text(
        json.dumps(
            {
                "last_run_at": "2026-09-12T03:30:00Z",
                "last_run_outcome": "completed",
                "cases_since_overseer": 3,
            }
        ),
        encoding="utf-8",
    )
    by_key = _item_map(conditions.feed(home, cache_dir))
    assert by_key["steward.last_run_at"].value == "2026-09-12T03:30:00Z"
    assert by_key["steward.last_run_outcome"].value == "completed"
    assert by_key["steward.cases_since_overseer"].value == 3


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


def test_negative_control_shared_try_blanks_the_other_producer_too(tmp_path, monkeypatch):
    """Mutation for N1: restore the pre-fold shared-`try` shape and
    confirm one producer's failure now blanks the OTHER producer's keys
    too -- the defect the split-`try` fix above closes."""
    home = make_home(tmp_path)
    keys = (
        "status.total_pending", "status.unanalyzed_total",
        "status.intents_probe", "status.intents_stopped_count",
    )

    def _shared_try_status_items(home, observed_at):
        try:
            fast = worker.fast_status(home)  # BUG: raises, below never runs
            from self_learn import intents as intents_mod

            cls = intents_mod.classify_status(home)
            values = (
                fast.get("total_pending", "unavailable"),
                fast.get("unanalyzed_total", "unavailable"),
                cls.probe,
                len(cls.stopped),
            )
            return [
                conditions.Item(k, v, observed_at, "mutated") for k, v in zip(keys, values)
            ]
        except Exception as exc:  # noqa: BLE001
            return [
                conditions.Item(k, "unavailable", observed_at, f"mutated: {exc}")
                for k in keys
            ]

    def _broken_fast_status(home):
        raise RuntimeError("fold r1 N1 negative-control fixture")

    monkeypatch.setattr(worker, "fast_status", _broken_fast_status)
    monkeypatch.setattr(conditions, "_status_items", _shared_try_status_items)
    by_key = _item_map(conditions.feed(home))
    assert by_key["status.intents_probe"].value == "unavailable"  # RED: collateral damage


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
    assert by_key["steward.last_run_at"].value == "unavailable"
    # a group with no cache_dir/output-style dependency stays real.
    assert by_key["ledger.head"].value != "unavailable"


def test_negative_control_unguarded_output_style_raises_through_feed(tmp_path, monkeypatch):
    """Mutation for N2: remove the guard around `_output_style_item`
    (call it bare, as pre-fold code did) and confirm `feed()` now
    RAISES instead of degrading."""
    home = make_home(tmp_path)

    def _broken_output_style_item(observed_at):
        raise RuntimeError("fold r1 N2 negative-control fixture")

    def _unguarded_feed(home, cache_dir=None):
        items = [conditions.Item("probe.before", "ok", "now", "src")]
        items.append(conditions._output_style_item("now"))  # BUG: no try/except
        return items

    monkeypatch.setattr(conditions, "_output_style_item", _broken_output_style_item)
    with pytest.raises(RuntimeError):
        _unguarded_feed(home)  # RED: proves the guard, not the plumbing, is what saves feed()
