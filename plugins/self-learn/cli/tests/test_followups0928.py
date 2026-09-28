"""Batch 2026-09-28, part 4: follow-ups the user delegated.

The user, 2026-09-28 15:17 PDT: "i trust you to deal with the questions."
The questions were raised by the builders of batch-0928 (merge 9940b03);
the orchestrator decided them under that delegation. One test group per
follow-up:

1. A moved lesson updates both files.

Sandbox ledger and host repos under pytest's tmpdir; fake model sessions.
"""

from __future__ import annotations

import pytest

from self_learn import ledger_ops, steward, verbs
from support import commit_all, git, make_env
from test_batch0928_post_run_recompile import _journal_rows
from test_steward import _enable_steward
from test_steward_refusals import _dispositions, _notifications, _seed, _writer


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")


# ------------------------------------------------ 1. a moved lesson's old file


def _stale_line_in_s(tmp_path, rid):
    """A lesson routed into skill s, then reopened with its host write
    left undone (a refused host commit, R3): it is pending again, keeps its
    routing block, and s's SKILL.md still carries its line."""
    env = make_env(tmp_path, skills=("s", "t"))
    home = env.ledger
    _seed(home, rid)
    verbs.route(home, rid, dest="skill-md", no_push=True)
    ledger_ops.reopen_record(home, rid)
    commit_all(home, f"reopen {rid}, host write left undone")
    return env, home


def test_a_rehomed_lesson_leaves_the_file_it_moved_out_of(tmp_path, monkeypatch):
    rid = "lrn-f1000001"
    env, home = _stale_line_in_s(tmp_path, rid)
    s_md = env.host / "plugins/s-plugin/skills/s/SKILL.md"
    assert rid in s_md.read_text()  # positive control: the stale line is there
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            (rid, [rid], [{"id": rid, "verb": "rehome", "to": "skill:t"}], "rehome", "rehome"),
        ]),
    )

    result = steward.run(home)

    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"
    assert (home / "skills/t/pending" / f"{rid}.md").is_file()
    assert rid not in s_md.read_text()
    assert git(env.host, "status", "--porcelain", "-uall").stdout.strip() == ""
    (row,) = _journal_rows(home, "recompile")
    assert row["changed"] == [str(s_md)]
    assert result.recompile_skipped == []


def test_move_origins_names_the_bucket_before_the_move(tmp_path):
    rid = "lrn-f1000002"
    env, home = _stale_line_in_s(tmp_path, rid)

    class Item:
        def __init__(self, verb):
            self.id, self.verb = rid, verb

    assert verbs.move_origins(home, [Item("rehome"), Item("rescope"), Item("reject")]) == [
        (rid, home / "skills" / "s"), (rid, home / "skills" / "s"),
    ]


def test_the_overseer_also_clears_the_file_a_rehomed_lesson_left(tmp_path, monkeypatch):
    from self_learn import cases
    from self_learn.overseer import run as overseer_run
    from test_failstate_overseer import _ok, _phase_a, _phase_b_common
    from test_overseer_run import _dump, _enabled

    rid = "lrn-f1000003"
    env, home = _stale_line_in_s(tmp_path, rid)
    s_md = env.host / "plugins/s-plugin/skills/s/SKILL.md"
    assert rid in s_md.read_text()  # positive control
    _enabled(monkeypatch)
    parked_path = tmp_path / "parked.yaml"
    _dump(parked_path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "where does this belong?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_path, actor="steward")

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _phase_b_common(stage)
            _dump(stage / "case-r.yaml", {
                "kind": "resolution", "trigger": "weekly", "outcome": "rehome",
                "records": [rid], "scope": "skill:s", "question": "where?",
                "supersedes": parked,
                "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
                "decision": {"verb": "rehome", "because": "it is about t", "confidence": "settled"},
            })
            _dump(stage / "sheet-r.yaml", {
                "version": 1, "items": [{"id": rid, "verb": "rehome", "to": "skill:t"}],
            })
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)

    result = overseer_run.run(home, no_push=True)

    assert (home / "skills/t/pending" / f"{rid}.md").is_file()
    assert rid not in s_md.read_text()
    assert result.recompile_skipped == ()
