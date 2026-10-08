"""2026-09-26 (agenda items 8 + 13): a bad case costs that case, and the
model gets to fix it.

1. The case writer's own rules (`cases.check_case_data`: its schema, its
   secret scan, its heading refusal) run on every staged case as part of
   the stage check that feeds the steward's one repair turn, so the model
   is told while it can still fix the case.
2. A case still in violation after the repair turn is refused ALONE; every
   other case of the packet applies. The same for a parked.yaml entry.

Full `steward.run` scenarios on sandbox ledgers under pytest's tmpdir (never
the real `~/.self-learn`) with fake session writers. Every secret is built
at test time; no literal here looks like a live credential.
"""

from __future__ import annotations

import pytest

from self_learn import cases, steward
from self_learn.invocation.contract import Outcome
from support import make_env
from test_heading_evidence import KEPT_ITEM, _case, _journal_rows, _ledger_files_with
from test_secret_evidence import _fake_github_token
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir
from test_steward_refusals import (
    _REPAIR_HEADER,
    _assert_parked_now_by_case_writer,
    _dispositions,
    _notifications,
    _seed,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_CASE_RULES = "The case checker would refuse these cases as written:"
_HEADING_BECAUSE = "the evidence settles it\n## an injected heading"


def _stage(spec, cases_by_rid: dict[str, dict], parked: list[dict] | None = None) -> Outcome:
    stage = _stage_dir(spec)
    for rid, case in cases_by_rid.items():
        _dump_yaml(stage / "cases" / f"{rid}.yaml", case)
        _dump_yaml(
            stage / "sheets" / f"{rid}.yaml",
            {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]},
        )
    if parked is not None:
        _dump_yaml(stage / "parked.yaml", {"entries": parked})
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


def _two_lessons(tmp_path, monkeypatch, tag: str):
    home = make_env(tmp_path).ledger
    bad = _seed(home, f"lrn-{tag}000001")
    good = _seed(home, f"lrn-{tag}000002")
    _enable_steward(home)
    _notifications(monkeypatch)
    return home, bad, good


def _run_with(monkeypatch, home, first: dict, repaired: dict, parked=None, repaired_parked=None):
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        if _REPAIR_HEADER in spec.prompt:
            return _stage(spec, repaired, repaired_parked)
        return _stage(spec, first, parked)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    return steward.run(home), prompts


def _repair_part(prompts: list[str]) -> str:
    assert len(prompts) == 2, "the repair turn was offered"
    assert _REPAIR_HEADER in prompts[1]
    return prompts[1].split(_REPAIR_HEADER, 1)[1]


# ------------------------------------------------------------- headings


def test_a_heading_in_because_goes_to_the_repair_turn_and_the_fix_applies(tmp_path, monkeypatch):
    home, bad, good = _two_lessons(tmp_path, monkeypatch, "a1")
    first = {bad: _case(bad, [KEPT_ITEM], because=_HEADING_BECAUSE), good: _case(good, [KEPT_ITEM])}
    fixed = {bad: _case(bad, [KEPT_ITEM]), good: _case(good, [KEPT_ITEM])}

    result, prompts = _run_with(monkeypatch, home, first, fixed)

    repair = _repair_part(prompts)
    assert _CASE_RULES in repair
    assert f"- cases/{bad}.yaml: case: a free-text field contains a '## ' heading-shaped line" in repair
    assert f"cases/{good}.yaml" not in repair
    rows = _dispositions(home, result.run_id)
    assert {rid: rows[rid]["state"] for rid in (bad, good)} == {bad: "applied", good: "applied"}


def test_a_heading_still_there_after_the_repair_refuses_only_that_case(tmp_path, monkeypatch):
    home, bad, good = _two_lessons(tmp_path, monkeypatch, "a2")
    first = {bad: _case(bad, [KEPT_ITEM], because=_HEADING_BECAUSE), good: _case(good, [KEPT_ITEM])}

    result, prompts = _run_with(monkeypatch, home, first, first)

    assert _CASE_RULES in _repair_part(prompts)
    rows = _dispositions(home, result.run_id)
    assert rows[good]["state"] == "applied", rows
    # 2026-10-07 (gate S1 R1): the refused case's lesson is parked now, not
    # left a kindless `refused` row (which stranded it for good)
    successor = _assert_parked_now_by_case_writer(home, bad, rows[bad])
    assert "heading injection" in rows[bad]["reason"]
    # the refused case was never recorded: the ledger holds the good
    # lesson's case and the bad lesson's park, nothing else
    assert sorted(
        (c["kind"], tuple(c["records"]), c.get("parked_reason")) for c in cases.list_cases(home)
    ) == [("parked", (bad,), "ledger-refused"), ("resolution", (good,), None)]
    assert {c["case"] for c in cases.list_cases(home, record_id=bad)} == {successor}
    assert result.decided == [good]


def test_a_dropped_heading_evidence_item_is_not_a_violation(tmp_path, monkeypatch):
    """The runner drops an evidence item quoting a heading line; that is
    not the model's to repair, so no repair turn is spent on it."""
    home, bad, good = _two_lessons(tmp_path, monkeypatch, "a3")
    heading_item = {"quote": "## a heading line", "ref": "transcript:0a0a0a0a#L3"}
    first = {bad: _case(bad, [KEPT_ITEM, heading_item]), good: _case(good, [KEPT_ITEM])}

    result, prompts = _run_with(monkeypatch, home, first, first)

    assert len(prompts) == 1
    rows = _dispositions(home, result.run_id)
    assert {rid: rows[rid]["state"] for rid in (bad, good)} == {bad: "applied", good: "applied"}


# --------------------------------------------------------------- secrets


def test_a_secret_in_because_goes_to_the_repair_turn_withheld(tmp_path, monkeypatch):
    token = _fake_github_token(41)
    home, bad, good = _two_lessons(tmp_path, monkeypatch, "b1")
    first = {bad: _case(bad, [KEPT_ITEM], because=f"it leaked {token}"), good: _case(good, [KEPT_ITEM])}
    fixed = {bad: _case(bad, [KEPT_ITEM]), good: _case(good, [KEPT_ITEM])}

    result, prompts = _run_with(monkeypatch, home, first, fixed)

    repair = _repair_part(prompts)
    assert f"- cases/{bad}.yaml: secret scan: 1 hit" in repair
    assert "[github-token]" in repair and "[withheld]" in repair
    assert token not in repair
    rows = _dispositions(home, result.run_id)
    assert {rid: rows[rid]["state"] for rid in (bad, good)} == {bad: "applied", good: "applied"}


def test_a_secret_still_there_after_the_repair_refuses_only_that_case(tmp_path, monkeypatch):
    token = _fake_github_token(42)
    home, bad, good = _two_lessons(tmp_path, monkeypatch, "b2")
    first = {bad: _case(bad, [KEPT_ITEM], because=f"it leaked {token}"), good: _case(good, [KEPT_ITEM])}

    result, prompts = _run_with(monkeypatch, home, first, first)

    assert token not in _repair_part(prompts)
    manifest = _head_manifest(home, result.run_id)
    packet = manifest["packets"][0]
    rows = packet["dispositions"]
    assert rows[good]["state"] == "applied", rows
    # Gate S1b F6: a hit in the steward's own text is `bad-line`, sent back
    # once (no longer a bare `refused` row, which decided the version).
    assert (rows[bad]["state"], rows[bad].get("kind")) == ("returned", "bad-line"), rows
    assert "case" not in rows[bad], rows
    assert "secret scan:" in rows[bad]["reason"] and "[withheld]" in rows[bad]["reason"]
    assert packet["phase"] == "complete"
    # ... its case frozen as a stub that holds no text, and never recorded
    (stub,) = [manifest["cases"][cid] for cid in packet["case_ids"]
               if manifest["cases"][cid].get("unrecorded_refusal")]
    assert (stub["case"], stub["sheet"], stub["phase"]) == ("", "", "refused")
    assert len(packet["case_ids"]) == 2
    assert [c["records"] for c in cases.list_cases(home)] == [[good]]
    # Positive control: the grep reaches the committed run record.
    assert any(p.endswith(f"cases/runs/{result.run_id}.json") for p in _ledger_files_with(home, bad))
    assert _ledger_files_with(home, token) == []
    refused = [r for r in _journal_rows(home) if r.get("status") == "refused"]
    assert [r["stage_file"] for r in refused] == [f"{bad}.yaml"]


def test_a_secret_in_a_parked_entry_refuses_that_entry_only(tmp_path, monkeypatch):
    token = _fake_github_token(43)
    home, bad, good = _two_lessons(tmp_path, monkeypatch, "b3")
    both = {bad: _case(bad, [KEPT_ITEM]), good: _case(good, [KEPT_ITEM])}
    entry = {
        key: value for key, value in _case(bad, [KEPT_ITEM], because=f"leak {token}").items()
        if key not in {"kind", "outcome"}
    }
    entry["parked_reason"] = "authority-unclear"
    assert entry["parked_reason"] in cases.PARKED_REASONS

    result, prompts = _run_with(monkeypatch, home, both, both, [entry], [entry])

    assert "- parked.yaml entry 1: secret scan: 1 hit" in _repair_part(prompts)
    packet = _head_manifest(home, result.run_id)["packets"][0]
    rows = packet["dispositions"]
    assert {rid: rows[rid]["state"] for rid in (bad, good)} == {bad: "applied", good: "applied"}
    (operation,) = packet["maintenance"]
    assert operation["state"] == "refused"
    assert operation["payload"] == {}
    assert "[withheld]" in operation["result"]["error"]
    assert _ledger_files_with(home, token) == []
    assert result.refused == 1


def test_a_case_the_model_parks_is_checked_as_the_runner_records_it(tmp_path, monkeypatch):
    """The runner sets a parked case's `outcome` and `parked_for` itself;
    a model's parked case that leaves them out (or writes another outcome)
    is not a violation, so no repair turn is spent on it."""
    home, parked_rid, good = _two_lessons(tmp_path, monkeypatch, "c1")
    parked = {**_case(parked_rid, [KEPT_ITEM]), "kind": "parked", "parked_reason": "authority-unclear"}
    assert "parked_for" not in parked and parked["outcome"] != "parked"
    with pytest.raises(cases.CaseError):  # positive control: record() alone refuses it
        cases.check_case_data(parked)
    first = {parked_rid: parked, good: _case(good, [KEPT_ITEM])}

    result, prompts = _run_with(monkeypatch, home, first, first)

    assert len(prompts) == 1
    rows = _dispositions(home, result.run_id)
    assert {rid: rows[rid]["state"] for rid in (parked_rid, good)} == {
        parked_rid: "parked", good: "applied",
    }


def test_a_format_error_and_a_case_violation_share_the_one_repair_turn(tmp_path, monkeypatch):
    home, bad, good = _two_lessons(tmp_path, monkeypatch, "c2")
    first = {bad: _case(bad, [KEPT_ITEM], because=_HEADING_BECAUSE), good: _case(good, [KEPT_ITEM])}
    fixed = {bad: _case(bad, [KEPT_ITEM]), good: _case(good, [KEPT_ITEM])}
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        if _REPAIR_HEADER in spec.prompt:
            return _stage(spec, fixed)
        outcome = _stage(spec, first)
        # 2026-09-27 (fail-state audit finding 3): an undeclared file is
        # quarantined now, never a format error; a sheet item with a key
        # its verb does not take is the format error of this test.
        sheet = _stage_dir(spec) / "sheets" / f"{good}.yaml"
        sheet.write_text(
            sheet.read_text(encoding="utf-8").replace("verb: reject", "verb: reject\n  zz_key: 1"),
            encoding="utf-8",
        )
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)

    repair = _repair_part(prompts)
    assert f"- cases/{good}.yaml: " in repair and "zz_key" in repair  # the format error
    assert f"- cases/{bad}.yaml: case: a free-text field contains a '## '" in repair
    assert result.run_id is not None


def test_the_briefs_own_examples_pass_the_case_pre_check(tmp_path):
    """Positive control for the pre-check's normalization: every worked
    example the brief shows the model (a parked one among them) passes, so
    a stage copied from the brief never spends the repair turn."""
    from self_learn import steward_prompt

    stage = tmp_path / "stage"
    for name, body in steward_prompt.STAGE_EXAMPLES.items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    assert len(list((stage / "cases").glob("*.yaml"))) >= 2  # the examples really landed
    assert steward._case_rule_message(stage) is None
