"""S-NEXT-steward (2026-10-30): a lesson the steward deferred is the
steward's again once its deferral comes due -- no manual `undefer`.

Live evidence: `lrn-f55e9e47` and `lrn-e92861b2` (user scope) were deferred
by the steward's run `run-3dfa8bebd36b` on 2026-09-22, before U3a, so that
run recorded each disposition under the PROPOSAL blob. A deferral never
touches the proposal, so `_eligible_lessons`' legacy bridge kept both
"decided" for ever: when the deferral came due they went to human review
instead of back to the steward, and after the orchestrator undeferred them
by hand (ledger commits 5e34fa8, f5555ea) `_eligible_lessons` still
returned nothing for them.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real ``~/.self-learn``). No model call; ids are synthetic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import ledger_ops, steward, verbs
from self_learn.records import Record
from support import commit_all, git, make_env, proposal_dict

#: A date far enough ahead that the queue keeps the lesson out until then.
_FAR = "2099-01-01"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _selected(home: Path) -> list[str]:
    return [entry.record.id for entry, _row in steward._eligible_lessons(home)]


def _blob(home: Path, path: Path) -> str:
    return git(home, "rev-parse", f"HEAD:{path.relative_to(home).as_posix()}").stdout.strip()


def _lesson_with_proposal(home: Path, rid: str) -> str:
    """A pending lesson with an analyst proposal, committed; returns the
    PROPOSAL's blob -- the version a pre-U3a run keyed its rows by."""
    ledger_ops.create_record(home, Record.create(
        type="behavior", scope="skill:s", source="session", kind="anti-pattern",
        trigger=f"About to edit storage for case {rid}.",
        instruction=f"Stop the container first ({rid}).", record_id=rid,
    ))
    ledger_ops.write_proposal(home, rid, proposal_dict())
    commit_all(home, f"lesson {rid} with a proposal")
    record_path = ledger_ops.find_record_path(home, rid)
    return _blob(home, record_path.parent.parent / "proposals" / f"{rid}.yaml")


def _publish_legacy_row(home: Path, rid: str, proposal_blob: str, verb: str, run_id: str) -> None:
    """A committed steward run, written the way a run before U3a wrote it:
    the disposition is `applied`, keyed by the proposal blob, and the case
    recipe's sheet holds one line with *verb* for the lesson."""
    case_id = "case-0000beef"
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": run_id,
        "started_at": "2026-09-22T06:00:00Z", "completed_at": "2026-09-22T06:23:53Z",
        "status": "complete",
        "cases": {case_id: {"items": [{"id": rid, "n": 1, "verb": verb}]}},
        "packets": [{
            "index": 1, "inputs": [{"record": rid, "version": proposal_blob}], "records": [rid],
            "dispositions": {rid: {"case": case_id, "input_version": proposal_blob,
                                   "state": "applied"}},
        }],
    }, reason=f"a legacy applied {verb} row")


def test_a_lesson_a_legacy_run_deferred_is_selected_again_once_due(tmp_path):
    home = make_env(tmp_path).ledger
    decided = "lrn-d0e00001"
    deferred = "lrn-d0e00002"
    decided_blob = _lesson_with_proposal(home, decided)
    deferred_blob = _lesson_with_proposal(home, deferred)
    # positive control: both are queued and nothing has decided either yet
    assert _selected(home) == [decided, deferred]

    # the bridge still works for a lesson a legacy run really decided ...
    _publish_legacy_row(home, decided, decided_blob, "reject", "run-aaaaaaaa1001")
    assert _selected(home) == [deferred]
    # ... and a legacy run that DEFERRED the other lesson decides nothing
    # about it: it is due the moment it is queued again
    _publish_legacy_row(home, deferred, deferred_blob, "defer", "run-aaaaaaaa1002")
    assert _selected(home) == [deferred]


def test_a_legacy_deferral_waits_for_its_date_then_returns_without_an_undefer(tmp_path):
    home = make_env(tmp_path).ledger
    rid = "lrn-d0e00003"
    proposal_blob = _lesson_with_proposal(home, rid)
    _publish_legacy_row(home, rid, proposal_blob, "defer", "run-aaaaaaaa1003")

    # the run's own deferral: pending in the directory, kept out of the queue
    verbs.defer(home, rid, until=_FAR, by="steward", no_push=True)
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert record.status == "deferred"  # positive control: the defer landed
    assert _selected(home) == []

    # the date comes due (membership is computed from `deferred_until`):
    # no `undefer`, and the steward is offered it
    verbs.defer(home, rid, until=_today(), by="steward", no_push=True)
    assert _selected(home) == [rid]
    (_entry, row), = steward._eligible_lessons(home)
    assert row["legacy_version"] == proposal_blob
    assert row["record_status"] == "deferred"


def test_a_decision_at_the_new_identity_is_still_decided_and_defers_are_not(tmp_path):
    """The record-blob identity: a `reject` row at the lesson's current blob
    keeps it out, and the same row for a `defer` case does not (it is the
    steward's again), while the default `_terminal_versions` -- what the
    suspected-violation inputs read -- still counts the deferral."""
    home = make_env(tmp_path).ledger
    kept, back = "lrn-d0e00004", "lrn-d0e00005"
    _lesson_with_proposal(home, kept)
    _lesson_with_proposal(home, back)
    kept_version = _blob(home, ledger_ops.find_record_path(home, kept))
    back_version = _blob(home, ledger_ops.find_record_path(home, back))

    _publish_legacy_row(home, kept, kept_version, "reject", "run-aaaaaaaa1004")
    _publish_legacy_row(home, back, back_version, "defer", "run-aaaaaaaa1005")

    assert _selected(home) == [back]
    assert (back, back_version) in steward._terminal_versions(home)
    assert (back, back_version) not in steward._terminal_versions(home, defers_decide=False)
    assert (kept, kept_version) in steward._terminal_versions(home, defers_decide=False)
