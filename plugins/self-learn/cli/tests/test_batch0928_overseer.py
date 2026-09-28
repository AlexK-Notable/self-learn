"""Batch 2026-09-28: the overseer's units after the workspace (B, and the
overseer-side parts of G).

The user's standing rule (2026-09-27 06:58): "Make the fix. Look for any
other similarly outlandish fail states." A bad item costs that item;
nothing crashes uncounted; nothing is silently lost.

Every scenario runs on a pytest sandbox ledger with fake model sessions.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from self_learn.overseer import run as overseer_run
from test_failstate_overseer import (
    _ok, _phase_a, _stage_two_successors, _status, _successor, _timed_out, _two_parked,
)
from support import make_home
from test_overseer_run import _enabled


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _append(path, text):
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


# ------------------------------------------------------------------ unit B


def test_a_reused_phase_a_brings_its_journal_entries_into_the_new_run(tmp_path, monkeypatch):
    """Unit B. Phase A of attempt 1 logs an entry, phase B times out, and
    attempt 2 reuses the kept phase A without a phase-A call. Before: the
    reused phase A's journal entries were lost, so attempt 2's committed
    journal had no record of the work its decisions rest on. Now they are
    carried in, marked as from attempt 1; attempt 1's phase-B entry is not
    (it was committed with attempt 1's failure note)."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    rid_a, parked_a, rid_b, parked_b = _two_parked(home, tmp_path)
    labels = []

    def invoke(spec):
        labels.append(spec.label)
        journal = spec.cwd / overseer_run.MODEL_JOURNAL_NAME
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
            _append(journal, "\n## phase A · population read\nkept-phase-a-entry\n")
            return _ok()
        if labels.count("phase-b") == 1:
            _append(journal, "\n## phase B · first try\nfirst-attempt-phase-b-entry\n")
            return _timed_out()
        _append(journal, "\n## phase B · second try\nsecond-attempt-phase-b-entry\n")
        _stage_two_successors(
            spec.cwd, rid_a, _successor(rid_a, parked_a), rid_b, _successor(rid_b, parked_b),
        )
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    first = overseer_run.run(home, no_push=True)
    assert first.status == "timed-out"
    second = overseer_run.run(home, no_push=True)
    assert labels == ["phase-a", "phase-b", "phase-b"]  # phase A was reused
    assert second.status in {"applied", "partial"}
    committed = overseer_run.model_journal_ledger_path(home, _today(), second.run)
    text = committed.read_text(encoding="utf-8")
    # Positive control: the new run's own phase-B entry is there.
    assert "second-attempt-phase-b-entry" in text
    assert "kept-phase-a-entry" in text
    assert f"attempt {first.run}" in text
    assert text.index("kept-phase-a-entry") < text.index("second-attempt-phase-b-entry")
    assert "first-attempt-phase-b-entry" not in text
    assert _status(home, rid_b) != "pending"
