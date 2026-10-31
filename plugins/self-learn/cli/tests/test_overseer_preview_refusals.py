"""The overseer believes its own preview, and phase B can read lessons
(S-NEXT-overseer-run, 2026-10-30).

(a) A sheet item whose preview says `would-refuse` is not applied: it is
    left off the staged sheet and named in "Refused / could not do" with the
    preview's reason, and the rest of the sheet goes ahead. A maintenance
    pair with such a line is not recorded and is named the same way.
    Before, the runner counted `would-refuse` items for the dry-run line and
    applied the whole sheet anyway.
(b) Phase B's stage holds every lesson record as `lessons/<id>.md` (phase A's
    does not), so the overseer can read the loaded text and status of a
    lesson it names. The 2026-10-18 and 2026-10-25 reports say it could not.
    A record the secret scan matches is replaced by a stub, because a hit
    in any input file refuses the whole run.

The preview is made to say `would-refuse` by wrapping the real
`batch.dry_run` (the control: the test asserts the wrapper fired); apply
time runs the real batch. Sandbox ledgers, fake model sessions, no model call.
"""

from __future__ import annotations

import pytest

from self_learn import cases
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.overseer import run as overseer_run
from support import commit_all, make_behavior, make_home
from test_failstate_overseer import _dump, _status, _successor
from test_overseer_named_maintenance import (
    NEW_A, NEW_B, _maintenance, _refused_section, _replace_sheet, _rewrite, _run,
)
from test_overseer_run import _enabled, _fake_two_phase, _wrap_phases
from test_replace import Env, _place, _rec, _seed


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _preview_refuses(monkeypatch, ids, kind="bad-line", detail="simulated preview refusal"):
    """Make the preview of every item naming one of *ids* say `would-refuse`;
    answers the ids it flagged, so a test can assert the wrapper fired."""
    real = overseer_run.batch.dry_run
    flagged: list[str] = []

    def preview(*args, **kwargs):
        result = real(*args, **kwargs)
        for item in result.items:
            if item.id in ids:
                item.state, item.kind, item.detail = "would-refuse", kind, detail
                flagged.append(item.id)
        return result

    monkeypatch.setattr(overseer_run.batch, "dry_run", preview)
    return flagged


def test_a_resolution_line_whose_preview_refuses_is_not_applied_and_the_rest_is(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, rid_b = "lrn-0c000001", "lrn-0c000002"
    for rid in (rid_a, rid_b):
        create_record(home, make_behavior(record_id=rid))
    commit_all(home, "seed")
    parked_path = tmp_path / "parked.yaml"
    _dump(parked_path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid_a, rid_b], "scope": "skill:s", "question": "decide these?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"} for rid in (rid_a, rid_b)],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_path, actor="steward")
    case = _successor(rid_a, parked)
    case["records"] = [rid_b, rid_a]
    case["evidence"] = [{"ref": f"record:{rid}", "quote": "status: pending"} for rid in (rid_b, rid_a)]
    flagged = _preview_refuses(monkeypatch, {rid_a})

    # rid_a is the SECOND line: the report names it by its place in the sheet
    _run(home, monkeypatch, {"decide": (case, {"version": 1, "items": [
        {"id": rid_b, "verb": "reject"}, {"id": rid_a, "verb": "reject"},
    ]})})

    assert flagged == [rid_a]  # control: the preview really said would-refuse
    assert _status(home, rid_b) == "rejected"  # the rest of the sheet went ahead
    assert _status(home, rid_a) == "pending"  # the refused line was not applied
    refused = _refused_section(home)
    assert (
        f"item 2 (reject {rid_a}): not applied — its preview said it would be refused "
        "[bad-line]: simulated preview refusal"
    ) in refused, refused
    assert rid_b not in refused, refused
    # the dropped line is neither a refusal at apply nor a dropped pair, so
    # the report's "Decided" section and the journal say it
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "1 line(s) of kept sheets were not applied" in report, report
    dropped = [row for row in overseer_run.read_journal(home, limit=200)
               if row.get("status") == "line-dropped"]
    assert len(dropped) == 1 and f"item 2 (reject {rid_a})" in dropped[0]["reason"], dropped


def test_a_maintenance_pair_whose_preview_refuses_its_line_is_not_recorded(env, tmp_path, monkeypatch):
    _enabled(monkeypatch)
    a, b = _seed(env.home, "lrn-e3b0c001"), _seed(env.home, "lrn-e3b0c002")
    for rid in (a, b):
        _place(env.home, rid, "skill-md")
    flagged = _preview_refuses(monkeypatch, {a})
    before = {row["case"] for row in cases.list_cases(env.home, only_ok=True)}

    _run(env.home, monkeypatch, {
        "refused": (_maintenance([a], rewrite=_rewrite("stop when the yield is flat")),
                    _replace_sheet(a, NEW_A)),
        "fine": (_maintenance([b], rewrite=_rewrite("rerun a timing failure first")),
                 _replace_sheet(b, NEW_B)),
    })

    assert flagged == [a]  # control: the preview really said would-refuse
    assert _rec(env.home, b).superseded_by, "control: the other pair applied"
    assert _rec(env.home, a).superseded_by is None and _rec(env.home, a).status == "routed"
    after = {row["case"] for row in cases.list_cases(env.home, only_ok=True)}
    assert len(after - before) == 1, "only the pair that applied was recorded"
    refused = _refused_section(env.home)
    assert "case-refused.yaml: dropped with sheet-refused.yaml" in refused, refused
    assert "a catalogue change whose preview refuses a line is not recorded" in refused, refused
    assert "simulated preview refusal" in refused, refused
    assert "case-fine.yaml" not in refused, refused


def test_phase_b_reads_every_lesson_record_and_phase_a_none(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = "lrn-0d000001"
    create_record(home, make_behavior(record_id=rid, instruction="Stop the container first."))
    commit_all(home, "seed")
    _fake_two_phase(monkeypatch)
    seen = _wrap_phases(monkeypatch)

    overseer_run.run(home, dry_run=True, no_push=True)

    staged = seen["b_stage"][f"{overseer_run.LESSONS_DIR}/{rid}.md"]  # type: ignore[index]
    assert f"id: {rid}" in staged and "status: pending" in staged
    assert "## Instruction" in staged and "Stop the container first." in staged
    assert not [name for name in seen["a_stage"] if name.startswith("lessons/")]  # type: ignore[attr-defined]
    assert "lessons/lrn-<id>.md" in str(seen["b_prompt"])
    assert "lessons/" not in str(seen["a_prompt"])


def test_a_lesson_record_the_secret_scan_matches_is_staged_as_a_stub(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid = "lrn-0d000002"
    create_record(home, make_behavior(record_id=rid))
    path = find_record_path(home, rid)
    path.write_text(
        path.read_text(encoding="utf-8") + "\ntoken = ghp_abcdefghijklmnopqrstuvwxyz123456\n",
        encoding="utf-8",
    )
    commit_all(home, "seed")
    _fake_two_phase(monkeypatch)
    seen = _wrap_phases(monkeypatch)

    result = overseer_run.run(home, dry_run=True, no_push=True)

    staged = seen["b_stage"][f"{overseer_run.LESSONS_DIR}/{rid}.md"]  # type: ignore[index]
    assert "withheld: the secret scan matched" in staged
    assert "ghp_" not in staged
    assert result.status == "dry-run", result  # a hit in an input file would have refused the run


def test_a_line_after_an_earlier_non_revise_line_on_its_lesson_is_not_dropped():
    """The preview overlays only `revise`, so a later line on a lesson an
    earlier `route` already acts on can preview a refusal it would not meet
    at apply; it goes ahead. A line on an untouched lesson is still dropped
    (the positive control)."""
    from self_learn import batch

    preview = batch.DryRunResult(items=[
        batch.DryRunItem(n=1, id="lrn-a", verb="route", state="would-apply"),
        batch.DryRunItem(n=2, id="lrn-a", verb="rehome", state="would-refuse", detail="not routed"),
        batch.DryRunItem(n=3, id="lrn-b", verb="reject", state="would-refuse", detail="no"),
    ])
    assert [item.n for item in overseer_run._preview_refusals(preview)] == [3]

    revised = batch.DryRunResult(items=[
        batch.DryRunItem(n=1, id="lrn-a", verb="revise", state="would-apply"),
        batch.DryRunItem(n=2, id="lrn-a", verb="rehome", state="would-refuse", detail="no"),
    ])
    assert [item.n for item in overseer_run._preview_refusals(revised)] == [2]
