"""2026-09-26 (agenda item 17 = N11, Q20; N14): in the overseer,

1. a `stopped` item that shares a sheet with a FINAL receipted refusal is
   dispatched again when the run resumes (a derived sheet without the final
   refusal, same identity and item numbers), and every item that did not
   apply is listed in "Refused / could not do" with its state and kind --
   including one whose outcome was only receipted, which carries no detail;
2. the cap close-out lists a refusal of a RETRIED kind (`git`,
   `target-busy`) that is still refused as unfinished;
3. the steward and the overseer read one definition of the retried kinds.

Sandbox ledgers under pytest's tmpdir only (`support.make_home`).
"""

from __future__ import annotations

import pytest

from ruamel.yaml import YAML

from self_learn import batch, execution_evidence, steward
from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_run import (
    _dispatch_scripted,
    _dump,
    _enabled,
    _fake_hook_phases,
    _halted_run_with_item_1_refused,
    _refused_block,
    _seed_parked_hook,
    _silence_notifications,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _no_model(monkeypatch):
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a resume must not invoke the model"),
    )


def test_a_stopped_item_beside_a_final_refusal_is_retried_and_both_are_reported(
    tmp_path, monkeypatch
):
    """N11: item 1 refused (bad-line, final), item 2 stopped. The resume
    dispatches item 2 again and never item 1, and the report names both."""
    home, first, dispatched = _halted_run_with_item_1_refused(tmp_path, monkeypatch, "bad-line")

    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 2, 2], "item 2 is dispatched again; item 1 never is"
    assert second.run == first.run
    manifest = execution_evidence.read_manifest(home, first.run)
    (recipe,) = manifest["cases"].values()
    rows = {row["n"]: row for row in recipe["dispositions"]}
    assert rows[1]["state"] == "refused" and rows[1]["kind"] == "bad-line", rows
    # Item 2 really ran again: its detail is the ledger's, not the script's.
    assert rows[2]["state"] == "refused", rows
    assert "simulated" not in rows[2].get("detail", ""), rows
    block = _refused_block(home)
    assert block.strip() and "- none" not in block, block
    assert "simulated bad-line refusal of item 1 [bad-line]" in block, block
    assert rows[2]["detail"] in block, block
    assert manifest["status"] == "complete"


def test_a_receipted_final_refusal_is_reported_when_nothing_is_run_again(
    tmp_path, monkeypatch
):
    """Item 1 applies and item 2 is refused (bad-line), so run 1 ends with
    exit 8 and stays unfinished (N12). The resume dispatches nothing, and
    its report -- the week's last -- still names item 2's refusal (before,
    a receipted item carried no detail and the section said none)."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_refusal=True)
    _silence_notifications(monkeypatch)
    dispatched = _dispatch_scripted(monkeypatch, {2: (1, "bad-line")})
    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert dispatched == [1, 2]
    assert overseer_run.has_unfinished_work(home), "positive control: exit 8 halts (N12)"
    _no_model(monkeypatch)

    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 2], "nothing is dispatched again"
    assert second.run == first.run
    assert execution_evidence.read_manifest(home, first.run)["status"] == "complete"
    block = _refused_block(home)
    assert "simulated bad-line refusal of item 2 [bad-line]" in block, block


def test_the_cap_close_out_lists_a_retried_kind_refusal_as_unfinished(tmp_path, monkeypatch):
    """N14: item 1 is refused `target-busy` on every attempt, item 2 stops
    every attempt. At the cap, the close-out's unfinished list names both."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_refusal=True)
    _silence_notifications(monkeypatch)
    dispatched: list[int] = []

    def always(given_home, item, **kwargs):
        dispatched.append(item.n)
        rc, kind = (1, "target-busy") if item.n == 1 else (6, None)
        return batch.ItemResult(
            n=item.n, id=item.id, verb=item.verb, rc=rc, state="refused",
            detail=f"simulated {kind or 'stop'} of item {item.n}", kind=kind,
        )

    monkeypatch.setattr(batch, "_dispatch", always)
    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert first.status == "partial"
    _no_model(monkeypatch)
    overseer_run.run(home, dry_run=False, no_push=True)
    overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 2, 1, 2, 1, 2], "every attempt re-drove both items"
    record = execution_evidence.read_manifest(home, first.run)
    assert record["status"] == "closed", record["status"]
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    questions = report.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert "Unfinished:" in questions, questions
    assert f"sheet-hook.yaml item 2 (undefer {rid})" in questions, questions
    assert f"sheet-hook.yaml item 1 (route {rid})" in questions, questions


def test_the_steward_and_the_overseer_retry_the_same_kinds():
    steward_retried = {kind for kind, action in steward._KIND_ACTIONS.items() if action == "retry"}
    assert steward_retried == set(overseer_run._RETRIED_REFUSAL_KINDS) == {"git", "target-busy"}
    assert overseer_run._RETRIED_REFUSAL_KINDS is batch.RETRIED_REFUSAL_KINDS


def test_the_tail_a_stop_left_behind_a_final_refusal_is_dispatched_too(tmp_path, monkeypatch):
    """Item 1 refused (bad-line, final), item 2 stopped, item 3 never
    dispatched because of the stop. The resume dispatches 2 and 3 (a STOP
    left 3 behind, not a half-state), never 1."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_refusal=True)
    phases = overseer_run.invocation.write_session

    def with_a_third_item(spec):
        outcome = phases(spec)
        sheet = spec.cwd / "sheet-hook.yaml"
        if sheet.exists():
            data = YAML(typ="safe").load(sheet.read_text(encoding="utf-8"))
            data["items"].append({"id": rid, "verb": "note", "append": "a tail line"})
            _dump(sheet, data)
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", with_a_third_item)
    _silence_notifications(monkeypatch)
    dispatched = _dispatch_scripted(monkeypatch, {1: (1, "bad-line"), 2: (6, None)})
    first = overseer_run.run(home, dry_run=False, no_push=True)
    assert dispatched == [1, 2], "positive control: the stop left item 3 undispatched"
    _no_model(monkeypatch)

    overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 2, 2, 3]
    (recipe,) = execution_evidence.read_manifest(home, first.run)["cases"].values()
    states = {row["n"]: row["state"] for row in recipe["dispositions"]}
    assert states[1] == "refused" and states[3] == "applied", recipe["dispositions"]


def test_a_refusal_line_names_state_and_kind_even_without_detail():
    bare = batch.ItemResult(n=2, id="lrn-0a0b0c0d", verb="undefer", rc=6, state="stopped", kind="git")
    assert overseer_run._refusal_line("s.yaml", bare) == "s.yaml item 2 (undefer lrn-0a0b0c0d): stopped [git]"
    told = batch.ItemResult(n=2, id="lrn-0a0b0c0d", verb="undefer", rc=6, state="stopped",
                            kind="git", detail="the ledger stopped")
    assert overseer_run._refusal_line("s.yaml", told) == "the ledger stopped [git] (stopped)"
    refused = batch.ItemResult(n=1, id="lrn-0a0b0c0d", verb="route", rc=1, state="refused",
                               kind="bad-line", detail="no such thing")
    assert overseer_run._refusal_line("s.yaml", refused) == "no such thing [bad-line]"


def test_a_refusal_with_no_detail_is_still_listed(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    _silence_notifications(monkeypatch)

    def wordless(given_home, item, **kwargs):
        return batch.ItemResult(n=item.n, id=item.id, verb=item.verb, rc=1,
                                state="refused", kind="bad-line")

    monkeypatch.setattr(batch, "_dispatch", wordless)
    overseer_run.run(home, dry_run=False, no_push=True)

    block = _refused_block(home)
    assert f"sheet-hook.yaml item 1 (route {rid}): refused [bad-line]" in block, block
