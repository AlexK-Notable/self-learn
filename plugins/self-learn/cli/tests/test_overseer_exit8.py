"""Exit 8 from a sheet is not, by itself, a halt (found live 2026-10-11).

`batch.decision_code` returns 8 (`EXIT_BATCH_PARTIAL`) in two different
situations:

* a ledger STOP after something in the sheet already committed -- the sheet
  did not finish, and `BatchResult.stopped_at` names the item it stopped at;
* a refusal ON ITS MERITS beside an applied item -- the sheet finished with
  a known result, and `stopped_at` stays None.

Overseer run `854639e4` met the second shape (a `revise` applied, a `route`
refused `bad-line`) and was left `unfinished` with the case in `remaining`;
its maintenance, observations and finalization ran only at the resume two
hours later. The first test below drives that shape through the REAL
`batch.run` and expects the run to finish on its first attempt; the second
is the control -- the first shape still halts.

Sandbox ledgers under pytest's tmpdir only (`support.make_home`).
"""

from __future__ import annotations

import subprocess
import time

import pytest

from self_learn import batch, execution_evidence, user_model
from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_run import (
    _dispatch_scripted,
    _dump,
    _enabled,
    _fake_hook_phases,
    _git,
    _refused_block,
    _seed_decided_case,
    _seed_parked_hook,
    _silence_notifications,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_MODEL_ENTRY = "Prefers a finished sheet to be finished the same night"


def _spy_on_batch_run(monkeypatch):
    """Record every real `batch.run` result; the batch itself still runs."""
    real = batch.run
    results: list[batch.BatchResult] = []

    def spied(*args, **kwargs):
        result = real(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(batch, "run", spied)
    return results


def _with_post_sheet_work(monkeypatch, decided_case):
    """`_fake_hook_phases` (a two-item hook sheet), plus the post-sheet work
    an attempt does only once its sheets are through: phase A selects one
    already-decided case, and phase B writes an `examined` finding for it
    (an observation) and one user-model `add` (maintenance)."""
    phases = overseer_run.invocation.write_session

    def invoke(spec):
        outcome = phases(spec)
        stage = spec.cwd
        if (stage / "sheet-hook.yaml").exists():
            _dump(stage / "findings.yaml", {"findings": [
                {"case": decided_case, "kind": "examined", "text": "decision held"},
            ]})
            _dump(stage / "user-model-delta.yaml", {"updates": [{
                "action": "add", "container": "D", "title": _MODEL_ENTRY,
                "because": "The resume two hours later did work the first attempt owed",
                "source": "system-reading", "ref": "record:lrn-0a0b0c0d",
            }]})
        else:
            _dump(stage / "selection.yaml", {
                "cases": [{"id": decided_case}],
                "why_these": "parked intake and one decided case",
                "why_stopped": "one was clear",
            })
            _dump(stage / "initial-views.yaml", {"cases": [{
                "id": decided_case, "what_i_would_do": "reject", "why": "narrow",
                "what_evidence_decides_it": "record evidence", "confidence": "clear",
            }]})
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def _no_model(monkeypatch):
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a resume must not invoke the model"),
    )


def test_a_sheet_that_applied_and_refused_on_the_merits_finishes_on_its_first_attempt(
    tmp_path, monkeypatch
):
    """Item 1 (`route` to the hook) really applies; item 2 is refused on its
    merits with a FINAL kind (`bad-line`, not `git`/`target-busy`). The
    batch exits 8 without a stop, so nothing of the sheet is left to do:
    the run's post-sheet work happens on this attempt and the run record is
    complete after it, with nothing remaining."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _decided_rid, decided_case = _seed_decided_case(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_apply_refusal=True)
    _with_post_sheet_work(monkeypatch, decided_case)
    _silence_notifications(monkeypatch)
    batches = _spy_on_batch_run(monkeypatch)
    dispatched = _dispatch_scripted(monkeypatch, {2: (1, "bad-line")})
    assert "bad-line" not in batch.RETRIED_REFUSAL_KINDS

    first = overseer_run.run(home, dry_run=False, no_push=True)

    # The shape under test, read off the real batch: exit 8, not a stop.
    assert dispatched == [1, 2], dispatched
    (sheet,) = batches
    states = {item.n: (item.state, item.kind) for item in sheet.items}
    assert states == {1: ("applied", None), 2: ("refused", "bad-line")}, states
    assert sheet.process_code == 8, sheet.process_code
    assert sheet.stopped_at is None and sheet.stop_message is None, (
        sheet.stopped_at, sheet.stop_message,
    )

    record = execution_evidence.read_manifest(home, first.run)
    assert record["status"] == "complete", (record["status"], record.get("remaining"))
    assert record["remaining"] == [], record["remaining"]
    assert record["attempt_count"] == 1, record["attempt_count"]
    assert not overseer_run.has_unfinished_work(home)
    # The run's own exit still says "the ledger changed, something was
    # refused" -- a finished partial result, not a halt.
    assert (first.code, first.status, first.applied, first.refused) == (8, "partial", 2, 1), (
        first.code, first.status, first.applied, first.refused,
    )

    # Post-sheet work ran on THIS attempt. Maintenance: the user-model add.
    maintenance = record.get("maintenance") or []
    assert [row.get("state") for row in maintenance] == ["applied"], maintenance
    titles = [
        row.get("title")
        for rows in user_model.show(home)["containers"].values()
        for row in rows
    ]
    assert _MODEL_ENTRY in titles, titles
    # Observations: the finding on the selected case landed in its file.
    obs_id = overseer_run._observation_id(first.run, 1)
    landed = _committed_case_files_containing(home, obs_id)
    assert landed, f"observation {obs_id} not committed"
    # Finalization: the report names the refusal, the open questions file
    # is published (only a complete run writes it), and the week is done.
    assert "simulated bad-line refusal of item 2 [bad-line]" in _refused_block(home)
    assert "overseer/open-questions.yaml" in _git(
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "overseer",
    )
    assert overseer_run.week_done(home, overseer_run.week_boundary(time.time()))

    # Nothing is left for a resume: it dispatches nothing and holds.
    _no_model(monkeypatch)
    second = overseer_run.run(home, dry_run=False, no_push=True)
    assert second.status == "held-week-done", second.status
    assert dispatched == [1, 2], dispatched
    assert execution_evidence.read_manifest(home, first.run)["attempt_count"] == 1


def _committed_case_files_containing(home, needle):
    """Paths under `cases/` at HEAD whose committed text contains *needle*."""
    found = subprocess.run(
        ["git", "-C", str(home), "grep", "-l", needle, "HEAD", "--", "cases"],
        capture_output=True, text=True,
    )
    return found.stdout.strip()


def test_a_ledger_stop_after_a_commit_still_halts_and_names_the_sheet(tmp_path, monkeypatch):
    """The control. Item 1 really applies; item 2 meets a ledger stop (exit
    6, "nothing written, safe to retry"). The batch also exits 8 -- something
    committed -- but this time it STOPPED (`stopped_at` is set), so the
    sheet is not finished: the run stays unfinished and names the case."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_apply_refusal=True)
    _silence_notifications(monkeypatch)
    batches = _spy_on_batch_run(monkeypatch)
    dispatched = _dispatch_scripted(monkeypatch, {2: (6, None)})

    first = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 2], dispatched
    (sheet,) = batches
    states = {item.n: item.state for item in sheet.items}
    assert states == {1: "applied", 2: "stopped"}, states
    assert sheet.process_code == 8, sheet.process_code
    assert sheet.stopped_at is not None, "positive control: this sheet really stopped"

    assert first.status == "partial", first.status
    record = execution_evidence.read_manifest(home, first.run)
    assert record["status"] == "unfinished", record["status"]
    (case_id,) = record["cases"]
    assert record["remaining"] == [case_id], record["remaining"]
    assert record["halt_code"] == 8, record.get("halt_code")
    assert overseer_run.has_unfinished_work(home)
