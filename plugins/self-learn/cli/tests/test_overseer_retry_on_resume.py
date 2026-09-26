"""2026-09-26 (agenda item 16 = Q19): the overseer retries a retryable
refusal without waiting for an unrelated resume.

An ordinary refusal never halts a sheet, so a run whose ONLY failure was a
`git` / `target-busy` refusal used to complete that night and drop the item
for the week. Now such a refusal keeps the run unfinished: the ordinary
resume dispatches it again, bounded by `runs.attempt_cap`, and the cap's
close-out names it. A FINAL refusal behaves exactly as before.

Sandbox ledgers under pytest's tmpdir only (`support.make_home`).
"""

from __future__ import annotations

import pytest

from self_learn import batch, execution_evidence
from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_run import (
    _dispatch_scripted,
    _enabled,
    _fake_hook_phases,
    _refused_block,
    _seed_parked_hook,
    _silence_notifications,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _one_item_run(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    _silence_notifications(monkeypatch)
    return home, rid


def _no_model(monkeypatch):
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: pytest.fail("a resume must not invoke the model"),
    )


def test_a_target_busy_only_run_stays_unfinished_retries_and_completes(tmp_path, monkeypatch):
    home, rid = _one_item_run(tmp_path, monkeypatch)
    dispatched = _dispatch_scripted(monkeypatch, {1: (1, "target-busy")})

    first = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1]
    assert first.status == "partial", first
    assert overseer_run.has_unfinished_work(home)
    assert execution_evidence.read_manifest(home, first.run)["status"] == "unfinished"
    assert "simulated target-busy refusal of item 1 [target-busy]" in _refused_block(home)
    _no_model(monkeypatch)

    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 1], "the target-busy refusal is dispatched again"
    assert (second.run, second.status) == (first.run, "applied")
    assert not overseer_run.has_unfinished_work(home)
    assert execution_evidence.read_manifest(home, first.run)["status"] == "complete"


def test_a_target_busy_refusal_at_the_cap_is_closed_out_and_named(tmp_path, monkeypatch):
    home, rid = _one_item_run(tmp_path, monkeypatch)
    dispatched: list[int] = []

    def always_busy(given_home, item, **kwargs):
        dispatched.append(item.n)
        return batch.ItemResult(
            n=item.n, id=item.id, verb=item.verb, rc=1, state="refused",
            detail="the target file has edits self-learn did not make", kind="target-busy",
        )

    monkeypatch.setattr(batch, "_dispatch", always_busy)
    first = overseer_run.run(home, dry_run=False, no_push=True)
    _no_model(monkeypatch)
    overseer_run.run(home, dry_run=False, no_push=True)
    overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1, 1, 1], "every attempt dispatched it again"
    record = execution_evidence.read_manifest(home, first.run)
    assert (record["status"], record["outcome"]) == ("closed", "attempts-exhausted")
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    questions = report.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert f"Unfinished: sheet-hook.yaml item 1 (route {rid}) [target-busy]." in questions, questions
    assert "the target file has edits self-learn did not make [target-busy]" in _refused_block(home)


def test_a_final_refusal_alone_still_completes_that_night(tmp_path, monkeypatch):
    home, rid = _one_item_run(tmp_path, monkeypatch)
    dispatched = _dispatch_scripted(monkeypatch, {1: (1, "bad-line")})

    first = overseer_run.run(home, dry_run=False, no_push=True)

    assert dispatched == [1]
    assert first.status == "refused", first
    assert not overseer_run.has_unfinished_work(home)
    assert execution_evidence.read_manifest(home, first.run)["status"] == "complete"
