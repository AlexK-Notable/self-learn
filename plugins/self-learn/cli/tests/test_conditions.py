"""U9 (code half) — `conditions.py`: the conditions feed (interface §4;
`02-schema.md` §3a.5; plan-steward §4.4).

Every test here relies on the suite-wide autouse fixture in
`conftest.py` (`_worker_test_defaults`) that already points
`SELF_LEARN_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, and
`SELF_LEARN_CLAUDE_DIR` at per-test tmp paths — no test here needs to set
those itself unless it wants a DIFFERENT specific path (the real-``~/.
claude``-never-touched control below is the one that does)."""

from __future__ import annotations

import json

import pytest

from self_learn import conditions, gitops, hosts, user_model, worker
from self_learn.ledger_ops import create_record
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


def test_mutation_hosts_yaml_exception_propagates_when_not_caught(tmp_path, monkeypatch):
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


def test_mutation_including_a_body_in_the_feed_is_caught(tmp_path, monkeypatch):
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


def test_mutation_declared_prefix_stripping_matters(tmp_path, monkeypatch):
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
