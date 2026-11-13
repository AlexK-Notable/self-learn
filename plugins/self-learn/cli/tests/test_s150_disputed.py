"""S-150 (2026-11-12): a placed lesson an open lesson contradicts comes to the steward.

Live 2026-11-02 to 11-07: a new lesson contradicted a placed rule. The steward
may not rewrite a placed lesson it was not given, so it parked the new lesson
for the weekly overseer; the old rule kept loading for six days until an agent
replaced it by hand. Pinned here:

* the sweep derives a failing `@disputed` for a placed lesson that a pending
  or deferred lesson names in `links.contradicts`, and for no other;
* a decided (rejected) disputing lesson no longer counts;
* the value names the disputing lessons, so a second one is a new version;
* the brief shows the disputing lesson's words and how to decide.

Synthetic ids and texts; sandbox ledgers; no model call.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import ledger_ops, premise_sweep, premises, steward_inputs
from self_learn.ledger import Bucket
from self_learn.records import Record
from support import commit_all, make_env

P = "lrn-d0000001"
X = "lrn-d0000002"
Y = "lrn-d0000003"


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")


def _open(home: Path, rid: str, target: str | None, text: str = "The panel is excessive.") -> None:
    record = Record.create(
        type="knowledge", scope="user", source="teach", fact=f"{text} ({rid})",
        context="An invented example.", record_id=rid,
    )
    if target is not None:
        record.append_contradicts(target)
    ledger_ops.create_record(home, record)
    commit_all(home, f"open lesson {rid}")


def _placed(tmp_path: Path, *ids: str):
    bucket = Bucket(tmp_path / "user", "user", "user")
    return [(bucket, SimpleNamespace(id=rid)) for rid in ids]


def test_an_open_lesson_that_contradicts_a_placed_one_fails_disputed(tmp_path):
    home = make_env(tmp_path).ledger
    _open(home, X, P)
    _open(home, Y, None)  # an open lesson that disputes nothing
    (fact,) = premise_sweep._disputed_facts(home, _placed(tmp_path, P, "lrn-d0000009"))
    assert (fact.record_id, fact.premise_id, fact.state) == (P, "@disputed", "failing")
    assert fact.value == f"disputed-by:{X}" and X in fact.shown
    assert "@disputed" in premises.PLACEMENT_PREMISE_IDS
    # a target that is not a placed lesson gives nothing
    assert premise_sweep._disputed_facts(home, _placed(tmp_path, "lrn-d0000009")) == []


def test_a_second_disputing_lesson_is_a_new_value_and_a_rejected_one_stops_counting(tmp_path):
    home = make_env(tmp_path).ledger
    _open(home, X, P)
    (one,) = premise_sweep._disputed_facts(home, _placed(tmp_path, P))
    _open(home, Y, P)
    (two,) = premise_sweep._disputed_facts(home, _placed(tmp_path, P))
    assert two.value == f"disputed-by:{X},{Y}" and two.value != one.value
    from self_learn import verbs

    verbs.reject(home, X, note="an invented reason", no_push=True)
    verbs.reject(home, Y, note="an invented reason", no_push=True)
    assert premise_sweep._disputed_facts(home, _placed(tmp_path, P)) == []


def test_the_brief_shows_the_disputing_lesson_and_how_to_decide(tmp_path):
    home = make_env(tmp_path).ledger
    _open(home, X, P, text="A dozen blind rankings is too much for a format choice.")
    item = {"premise": "@disputed", "now": f"contradicted by {X}", "claim": "c",
            "since": "s", "now_at": "n"}
    lines = "\n".join(
        steward_inputs._placement_item_lines(home, SimpleNamespace(id=P), item)
    )
    assert f"{X} (pending) says:" in lines and "A dozen blind rankings" in lines
    decide = "\n".join(steward_inputs._placement_decide_lines(None, ["@disputed"]))
    assert "most recently win" in decide and "`also`" in decide
    assert "most recently win" not in "\n".join(
        steward_inputs._placement_decide_lines(None, ["@reach"])
    )
