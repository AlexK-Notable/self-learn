"""S-NEXT-u7c: the overseer's phase-B facts about the premise check (premise
design D11, unit U7) and the weekly report's "Hand steps this week" section
(hand-maintenance cures, lane C).

Facts: ``health.premise_facts`` / ``health.premise_refreshes`` /
``health.hand_steps_row`` / ``health.gather``. Report: ``HAND_STEPS_SECTION``,
``_validate_model_report``, ``_repair_report_headings``,
``_finalize_model_report(hand_steps=...)``, ``_staged_hand_steps``, the phase B
prompt, the workspace formats, and one whole run through the fake model.

No real model, no real ledger: a throwaway ledger and a fake session backend.
"""

from __future__ import annotations


import pytest
from ruamel.yaml import YAML

from self_learn import execution_evidence, premise_sweep, premises
from self_learn.overseer import formats, health
from self_learn.overseer import run as overseer_run
from support import commit_all, make_behavior, make_env, make_home
from test_hand_steps import NOW, _commit
from test_overseer_run import _enabled, _fake_two_phase, _silence_notifications

A, B, C = "lrn-0000a001", "lrn-0000a002", "lrn-0000a003"
SWEEP_1, SWEEP_2, SWEEP_3 = "2026-10-29T03:30:00Z", "2026-10-30T03:30:00Z", "2026-10-31T03:30:00Z"
WATCHED = {"id": "p1", "claim": "the watched file exists", "probe": {"kind": "path", "path": "/opt/example/watched"}}


# ============================================================ the facts


def _seed(env, rid, premise_list=None):
    """A live routed skill-md lesson in the throwaway ledger (committed)."""
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record = make_behavior(scope="skill:s", record_id=rid)
    record.set_routing({"routed_at": "2026-09-22T06:24:50Z", "destination": "skill-md", "by": "human"})
    record.set_status("routed")
    if premise_list is not None:
        record.set_premises(premise_list)
    record.write(resolved / f"{rid}.md")
    commit_all(env.ledger, f"seed {rid}")


def _write_config(env, text):
    (env.ledger / "config.yaml").write_text(text, encoding="utf-8")
    commit_all(env.ledger, "config")


def _probe_row(rid, sweep, state, premise=WATCHED, reason="no such file"):
    return {
        "sweep": sweep, "id": rid, "premise": premise["id"], "kind": "probe",
        "psha": premise_sweep._premise_sig(premises.normalize_premises([premise], record_id=rid)[0]),
        "state": state, "value_sha": None, "shown": "", "claim": "unjudged", "reason": reason,
        "at": sweep, "failing": None, "detail": "", "group": None,
    }


def _placement_row(rid, pid, sweep, *, failing=True):
    return {
        "sweep": sweep, "id": rid, "premise": pid, "kind": "placement", "psha": "",
        "state": "ok", "value_sha": "feedface", "shown": "unreachable", "claim": "unjudged",
        "reason": "", "at": sweep, "failing": failing, "detail": "", "group": None,
    }


def _store(cache, rows):
    history: dict = {}
    for row in rows:
        history.setdefault((row["id"], row["premise"]), []).append(row)
    premise_sweep._store_history(cache, history)


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def test_a_switched_off_check_claims_nothing(env, tmp_path):
    _seed(env, A)
    cache = tmp_path / "cache"
    on = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    assert on["enabled"] is True and on["placed_lessons"] == 1  # control: on, the counts are there
    _write_config(env, "premises:\n  enabled: false\n")
    off = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    assert off["state"] == "off" and off["enabled"] is False
    for key in ("placed_lessons", "without_premises", "broken_probes", "failing_placements"):
        assert key not in off, key


def test_a_sweep_that_started_and_never_finished_does_not_read_as_finished(env, tmp_path):
    _seed(env, A, [WATCHED])
    cache = tmp_path / "cache"
    premise_sweep._store_state(cache, {"last_attempt_at": SWEEP_3, "last_status": "running"})
    row = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    assert row["sweep"]["last_attempt_at"] == SWEEP_3  # control: the state was read
    assert row["sweep"]["last_finished_at"] is None
    premise_sweep._store_state(
        cache, {"last_attempt_at": SWEEP_3, "last_finished_at": SWEEP_2, "last_status": "ok"}
    )
    done = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    assert done["sweep"]["last_finished_at"] == SWEEP_2


def test_it_counts_the_lessons_that_record_no_premises(env, tmp_path):
    _seed(env, A)  # no premises field: counted
    _seed(env, B, [])  # decided-none: not counted
    _seed(env, C, [WATCHED])
    row = health.premise_facts(env.ledger, cache_dir=tmp_path / "cache", now=NOW)
    assert row["state"] == "ok"
    assert (row["placed_lessons"], row["without_premises"]) == (3, 1)


def test_a_sweep_that_never_ran_says_so_beside_its_empty_lists(env, tmp_path):
    """An empty list is read as good news only when the sweep ran; the row
    says it did not (lrn-6d21607e: an unread target must not read as clean)."""
    _seed(env, A, [WATCHED])
    row = health.premise_facts(env.ledger, cache_dir=tmp_path / "cache", now=NOW)
    assert row["sweep"]["last_finished_at"] is None
    assert row["broken_probes"] == [] and row["failing_placements"] == []
    assert "sweep.last_finished_at" in row["caution"]


def test_a_probe_unavailable_on_three_sweeps_in_a_row_is_broken(env, tmp_path):
    _seed(env, A, [WATCHED])
    cache = tmp_path / "cache"
    _store(cache, [_probe_row(A, s, premises.OBS_UNAVAILABLE) for s in (SWEEP_1, SWEEP_2, SWEEP_3)])
    row = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    assert row["broken_probes"] == [{"lesson": A, "premise": "p1", "reason": "no such file"}]


def test_two_unavailable_sweeps_or_one_good_reading_in_the_run_is_not_broken(env, tmp_path):
    _seed(env, A, [WATCHED])
    cache = tmp_path / "cache"
    _store(cache, [_probe_row(A, s, premises.OBS_UNAVAILABLE) for s in (SWEEP_2, SWEEP_3)])
    assert health.premise_facts(env.ledger, cache_dir=cache, now=NOW)["broken_probes"] == []
    _store(cache, [
        _probe_row(A, SWEEP_1, premises.OBS_UNAVAILABLE),
        _probe_row(A, SWEEP_2, premises.OBS_OK),
        _probe_row(A, SWEEP_3, premises.OBS_UNAVAILABLE),
    ])
    assert health.premise_facts(env.ledger, cache_dir=cache, now=NOW)["broken_probes"] == []


def test_a_placement_failing_on_two_sweeps_is_named_and_one_is_not(env, tmp_path):
    _seed(env, A)
    _seed(env, B)
    cache = tmp_path / "cache"
    _store(cache, [
        _placement_row(A, "@reach", SWEEP_2), _placement_row(A, "@reach", SWEEP_3),
        _placement_row(B, "@reach", SWEEP_3),
    ])
    row = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    assert row["failing_placements"] == [f"{A}@reach"]


def test_a_probe_reason_that_trips_the_secret_scan_is_withheld(env, tmp_path):
    token = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
    _seed(env, A, [WATCHED])
    cache = tmp_path / "cache"
    _store(cache, [_probe_row(A, s, premises.OBS_UNAVAILABLE, reason="read failed") for s in (SWEEP_1, SWEEP_2)]
           + [_probe_row(A, SWEEP_3, premises.OBS_UNAVAILABLE, reason=f"token = {token}")])
    row = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    (broken,) = row["broken_probes"]  # control: the probe is named
    assert broken["reason"].startswith("(withheld: the secret scan matched")
    assert token not in repr(row)


def test_placements_that_could_not_be_measured_are_counted_not_dropped(env, tmp_path):
    _seed(env, A)
    _seed(env, B)
    cache = tmp_path / "cache"
    unread = {**_placement_row(A, "@reach", SWEEP_3), "state": premises.OBS_UNAVAILABLE, "value_sha": None}
    _store(cache, [unread, _placement_row(B, "@reach", SWEEP_3, failing=False)])
    row = health.premise_facts(env.ledger, cache_dir=cache, now=NOW)
    assert row["unmeasurable_placements"] == 1
    assert row["failing_placements"] == []  # an unread placement is not a failing one


def test_a_refresh_whose_changes_trip_the_secret_scan_is_withheld(env):
    token = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
    _seed(env, A, [WATCHED])
    _commit(env.ledger, f"self-learn: premises refresh {A} p1", days_ago=2,
            note=f"Re-baselined by the premise sweep.\np1: old -> {token}")
    _commit(env.ledger, f"self-learn: premises refresh {B} p1", days_ago=1,
            note="Re-baselined by the premise sweep.\np1: 1 -> 2")
    commits = {c["lesson"]: c for c in health.premise_refreshes(env.ledger, now=NOW)["commits"]}
    assert commits[B]["changes"] == ["p1: 1 -> 2"]  # control: the rows are read
    assert commits[A]["changes"][0].startswith("(withheld: the secret scan matched")
    assert token not in repr(commits)


def test_the_weeks_code_only_refreshes_are_listed_and_older_ones_are_not(env, tmp_path):
    _seed(env, A, [WATCHED])
    _commit(
        env.ledger, f"self-learn: premises refresh {A} p1", days_ago=2,
        note="Re-baselined by the premise sweep (code only, no model call): these premises "
             "are marked on_change: refresh.\np1: 1.4 -> 1.5",
    )
    _commit(env.ledger, f"self-learn: premises refresh {B} p1", days_ago=9, note="old\np1: 1 -> 2")
    _commit(env.ledger, f"self-learn: reject {C}", days_ago=1)  # not a refresh
    refreshes = health.premise_refreshes(env.ledger, now=NOW)
    assert refreshes["state"] == "ok" and refreshes["total"] == 1
    (commit,) = refreshes["commits"]
    assert commit["lesson"] == A and commit["premises"] == ["p1"]
    assert commit["changes"] == ["p1: 1.4 -> 1.5"]
    row = health.premise_facts(env.ledger, cache_dir=tmp_path / "cache", now=NOW)
    assert row["refreshed_this_week"]["total"] == 1


def test_an_unreadable_history_is_unavailable_for_the_refreshes_too(tmp_path):
    plain = tmp_path / "plain-folder"
    plain.mkdir()
    refreshes = health.premise_refreshes(plain, now=NOW)
    assert refreshes["state"] == "unavailable" and refreshes["reason"]


def test_gather_carries_both_rows(tmp_path):
    home = make_home(tmp_path)
    kinds = [row["kind"] for row in health.gather(home)]
    assert "premise-check" in kinds and "hand-steps-this-week" in kinds
    census = next(row for row in health.gather(home) if row["kind"] == "hand-steps-this-week")
    assert census["state"] == "ok" and census["window_days"] == 7
    assert "by: none" in census["caution"]


# ===================================================== the report section


HEADINGS = (
    "Examined", "Decided in the user's stead", "Hooks", "User model",
    "Catalogue health", "Questions for you", "Refused / could not do",
)


def _model_report(path, *, hand_steps_body=None):
    lines = ["# model draft"]
    for heading in HEADINGS:
        lines.extend([f"## {heading}", "- none"])
        if heading == "Catalogue health" and hand_steps_body is not None:
            lines.extend([f"## {overseer_run.HAND_STEPS_SECTION}", *hand_steps_body])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _step(commit, subject="self-learn: reject lrn-0000a001", by="none", note="(no reason recorded)"):
    return {"commit": commit, "at": "2026-10-30 19:49Z", "subject": subject, "by": by, "note": note}


def _census(*steps, total=None, state="ok", reason=None):
    return {"window_days": 7, "since": "2026-10-24T12:00Z", "state": state, "reason": reason,
            "total": len(steps) if total is None else total, "steps": list(steps)}


def _finalize(path, **kw):
    return overseer_run._finalize_model_report(
        path, date="2026-10-31", run_id="12345678", model="m", selected=(),
        population_count=0, excluded=0, model_calls=2, guard=50, refusals=[], **kw,
    )


def _section(text):
    return text.split(f"## {overseer_run.HAND_STEPS_SECTION}\n", 1)[1].split("\n## ", 1)[0]


def _headings_of(text):
    return [line[3:] for line in text.splitlines() if line.startswith("## ")]


def test_without_a_census_the_report_is_left_as_the_model_wrote_it(tmp_path):
    path = tmp_path / "report.md"
    _model_report(path)
    text = _finalize(path)
    assert overseer_run.HAND_STEPS_SECTION not in text  # an older run record, resumed after landing
    assert _headings_of(text) == list(HEADINGS)  # control: the other seven are there


def test_the_runner_adds_the_section_after_catalogue_health_with_one_line_per_step(tmp_path):
    path = tmp_path / "report.md"
    _model_report(path)
    text = _finalize(path, hand_steps=_census(
        _step("abc1234", by="agent", note="shelf moved by hand"), _step("def5678", subject="self-learn: undefer lrn-0000a002"),
    ))
    assert _headings_of(text) == [
        "Examined", "Decided in the user's stead", "Hooks", "User model", "Catalogue health",
        "Hand steps this week", "Questions for you", "Refused / could not do",
    ]
    body = _section(text)
    assert "- abc1234 2026-10-30 19:49Z by agent: self-learn: reject lrn-0000a001 (shelf moved by hand)" in body
    assert "def5678" in body and body.count("the overseer did not name the gap") == 2
    assert "self-learn: undefer lrn-0000a002 (no reason recorded) —" in body  # not doubly parenthesised


def test_a_gap_the_overseer_named_is_kept_and_only_a_missing_step_is_added(tmp_path):
    path = tmp_path / "report.md"
    named = "- abc1234 rejected lrn-0000a001 by hand: reject has no reason prompt"
    _model_report(path, hand_steps_body=[named])
    text = _finalize(path, hand_steps=_census(_step("abc1234"), _step("def5678")))
    body = _section(text)
    assert body.count("abc1234") == 1 and named in body.splitlines()
    assert "- def5678" in body and "the overseer did not name the gap" in body
    assert body.count("the overseer did not name the gap") == 1


def test_an_empty_week_reads_none_and_an_unreadable_one_says_it_could_not_be_read(tmp_path):
    path = tmp_path / "report.md"
    _model_report(path)
    assert _section(_finalize(path, hand_steps=_census())).strip() == "- none"
    _model_report(path)
    unreadable = _section(_finalize(path, hand_steps=_census(state="unavailable", reason="git failed")))
    assert "could not be read (git failed)" in unreadable
    assert "- none" not in unreadable  # an unread week is never an empty one


def test_steps_beyond_the_packet_are_counted_in_a_line(tmp_path):
    path = tmp_path / "report.md"
    _model_report(path)
    body = _section(_finalize(path, hand_steps=_census(_step("abc1234"), total=5)))
    assert "4 more hand step(s) this week were not in the packet" in body


def test_the_models_bare_none_gives_way_to_the_steps(tmp_path):
    path = tmp_path / "report.md"
    _model_report(path, hand_steps_body=["- none"])
    body = _section(_finalize(path, hand_steps=_census(_step("abc1234"))))
    assert "- none" not in body.splitlines() and "abc1234" in body


def test_the_length_guide_does_not_count_the_runners_section(tmp_path):
    """The model's own line count decides the guide's note; the runner's census
    lines are added after it was taken."""
    path = tmp_path / "report.md"
    _model_report(path)
    steps = [_step(f"abc{n:04d}") for n in range(60)]
    text = _finalize(path, hand_steps=_census(*steps))
    assert "ran to" not in text and "guide is" not in text


def test_the_optional_heading_is_valid_only_directly_after_catalogue_health(tmp_path):
    path = tmp_path / "report.md"
    _model_report(path, hand_steps_body=["- none"])
    overseer_run._validate_model_report(path)  # accepted in place
    wrong = "\n".join(
        ["# draft", "## Examined", "- none", f"## {overseer_run.HAND_STEPS_SECTION}", "- none",
         *[line for h in HEADINGS[1:] for line in (f"## {h}", "- none")]]
    ) + "\n"
    path.write_text(wrong, encoding="utf-8")
    with pytest.raises(overseer_run.OverseerError):
        overseer_run._validate_model_report(path)


def test_repair_keeps_the_optional_heading_and_never_calls_it_missing(tmp_path):
    path = tmp_path / "report.md"
    _model_report(path)
    assert overseer_run._repair_report_headings(path) == []  # seven headings, none missing
    _model_report(path, hand_steps_body=["- a step"])
    assert overseer_run._repair_report_headings(path) == []  # eight, in place
    # Out of order: the optional section moves back after Catalogue health.
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"## {overseer_run.HAND_STEPS_SECTION}")
    moved = [*lines[:start], *lines[start + 2:], *lines[start:start + 2]]
    path.write_text("\n".join(moved) + "\n", encoding="utf-8")
    notes = overseer_run._repair_report_headings(path)
    assert notes == ["report: the headings were out of order; the runner put them back in order"]
    assert _headings_of(path.read_text(encoding="utf-8")).index("Hand steps this week") == 5
    assert "- a step" in path.read_text(encoding="utf-8")
    # A required heading is still reported missing.
    path.write_text("# r\n## Examined\n- none\n", encoding="utf-8")
    assert any("was missing" in note for note in overseer_run._repair_report_headings(path))


def test_the_staged_census_is_the_row_phase_b_was_given(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    missing = overseer_run._staged_hand_steps(stage)  # no health.yaml at all
    assert missing["state"] == "unavailable" and missing["steps"] == []
    (stage / "health.yaml").write_text(
        "catalogue_health:\n- kind: premise-check\n", encoding="utf-8"
    )
    assert overseer_run._staged_hand_steps(stage)["state"] == "unavailable"  # no census row
    row = {"kind": "hand-steps-this-week", "state": "ok", "total": 1, "window_days": 7,
           "since": "2026-10-24T12:00Z", "reason": None, "steps": [_step("abc1234")],
           "caution": "not carried"}
    (stage / "health.yaml").write_text(
        _yaml_dump({"facts": [], "catalogue_health": [{"kind": "premise-check"}, row]}), encoding="utf-8"
    )
    got = overseer_run._staged_hand_steps(stage)
    assert got["state"] == "ok" and got["steps"][0]["commit"] == "abc1234"
    assert "caution" not in got and "kind" not in got


def _yaml_dump(data):
    import io

    stream = io.StringIO()
    YAML().dump(data, stream)
    return stream.getvalue()


def test_the_phase_b_prompt_names_both_rows_and_the_new_heading(tmp_path):
    flat = " ".join(overseer_run._phase_b_prompt(tmp_path, (), ()).split())
    assert "premise-check:" in flat and "hand-steps-this-week:" in flat
    assert "Catalogue health; Hand steps this week; Questions for you" in flat
    assert "the gap in self-learn that made the hand step necessary" in flat
    assert "sweep.last_finished_at" in flat


def test_the_workspace_formats_carry_the_heading(tmp_path):
    sets = formats.closed_sets()
    assert sets["report_headings_in_order"] == list(overseer_run._REPORT_SECTIONS)  # unchanged
    assert sets["report_hand_steps_heading"] == "Hand steps this week"
    example = formats.phase_b_examples()["report.md"]
    assert _headings_of(example)[4:6] == ["Catalogue health", "Hand steps this week"]
    path = tmp_path / "report.md"
    path.write_text(example, encoding="utf-8")
    assert overseer_run._repair_report_headings(path) == []


# ================================================ a whole run, fake model


def test_a_whole_run_publishes_the_census_and_keeps_it_in_the_run_record(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_two_phase(monkeypatch)
    row = {"kind": "hand-steps-this-week", **_census(
        _step("abc1234", by="agent", note="registered the host by hand"),
        _step("def5678", subject="self-learn: config set overseer.enabled", note="the switch"),
    )}
    monkeypatch.setattr(health, "hand_steps_row", lambda _home, now=None: row)

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code) == ("applied", 0), result
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert report.index("## Catalogue health") < report.index("## Hand steps this week") < report.index("## Questions for you")
    body = _section(report)
    assert "abc1234" in body and "def5678" in body and "registered the host by hand" in body
    record = execution_evidence.read_manifest(home, result.run)
    assert [step["commit"] for step in record["hand_steps"]["steps"]] == ["abc1234", "def5678"]
    assert record["hand_steps"]["state"] == "ok"


def test_a_run_whose_census_could_not_be_read_says_so_in_its_report(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_two_phase(monkeypatch)
    monkeypatch.setattr(
        health, "hand_steps_row",
        lambda _home, now=None: {"kind": "hand-steps-this-week", **_census(state="unavailable", reason="git failed")},
    )

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code) == ("applied", 0), result
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "could not be read (git failed)" in _section(report)


def test_a_resumed_run_publishes_the_census_phase_b_was_given(tmp_path, monkeypatch):
    """The run record carries the census because a resumed run's rebuilt stage
    has no health.yaml. Run 2 is handed a DIFFERENT census and no model; its
    report must still list run 1's steps, read from the run record."""
    from test_overseer_run import (
        _dispatch_returning, _fake_hook_phases, _seed_parked_hook, _wrap_phases,
    )

    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    _wrap_phases(monkeypatch)
    _silence_notifications(monkeypatch)
    _dispatch_returning(monkeypatch, 6, only_first=True)
    first_row = {"kind": "hand-steps-this-week", **_census(_step("abc1234", note="the first run's step"))}
    monkeypatch.setattr(health, "hand_steps_row", lambda _home, now=None: first_row)

    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert first.status == "partial", "positive control: run 1 really did stall"

    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a resume must not invoke the model"),
    )
    other_row = {"kind": "hand-steps-this-week", **_census(_step("fff9999", note="a later census"))}
    monkeypatch.setattr(health, "hand_steps_row", lambda _home, now=None: other_row)
    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert (second.run, second.status) == (first.run, "applied")
    body = _section((home / "overseer" / "latest-report.md").read_text(encoding="utf-8"))
    assert "abc1234" in body and "the first run's step" in body
    assert "fff9999" not in body and "could not be read" not in body
