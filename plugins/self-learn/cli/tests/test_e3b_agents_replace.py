"""E3b (2026-10-11): the steward and the overseer may use `replace`.

Design: D-AUTHOR §2.8 ("Who may do what") and §2.13; build plan E3b. What
is pinned here:

* the E1 gate's gaps that opening the verb makes live:
  - D2: a refusal under the lock (a hold that appears after the pre-lock
    checks) leaves nothing on disk, on the routed and the pending path;
  - R1 item 3: a `replace` line whose id or `also` id is not among its
    case's `records` is refused by name, in both runners;
  - each `also` leg's `supersede` commit carries the execution trailers, so
    a re-drive's `execution_evidence` proves it;
* "rewrite required": a case whose sheet has a `replace` item needs
  `decision.rewrite`, in both runners;
* the steward's limits (§2.8): `also` counts as coverage; a placed lesson
  is replaced only under a `kind: reconsider` case and never merged; a
  placed lesson that is not an input of its run, or one the overseer
  holds, is refused;
* end to end on a scratch ledger with the REAL batch: the steward replaces
  a pending lesson; the overseer, through named maintenance pairs, replaces
  a placed lesson and merges two placed lessons.

Every scenario runs on pytest sandbox ledgers and hosts (`support.make_env`),
with HOME pointed at the sandbox; ids and texts are synthetic. No model call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import batch, cases, execution_evidence, gitops, ledger_ops, verbs
from self_learn.ledger_ops import find_record_path
from self_learn.records import Record
from support import git
from test_replace import (
    NEW_INSTRUCTION,
    NEW_TRIGGER,
    Env,
    _hold,
    _place,
    _rec,
    _seed,
    _sheet,
    _subjects,
    _tree,
)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    # A user-scope lesson compiles into ~/.claude/CLAUDE.md: never the real one.
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _porcelain(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all").stdout


def _lesson_files(home: Path) -> set[str]:
    return {p.name for p in home.rglob("lrn-*.md") if ".git" not in p.parts}


# ============================================================== D2


@pytest.mark.parametrize("path", ["routed", "pending"])
def test_a_hold_that_appears_under_the_lock_leaves_nothing_on_disk(env, tmp_path, monkeypatch, path):
    """E1 gate D2 (probes P4, P9, P11): the hold is checked before the
    pre-lock checks pass and again by `supersede_record` under the lock --
    but that second check used to run AFTER the new record was written, so
    a hold appearing in between left an uncommitted, live record in
    `resolved/` (or `pending/`) that every reader then treated as real.
    Now the predecessor's status and hold are read under the lock before
    the first write: the line is refused by name and the ledger is clean.
    The same line with no late hold applies (the control)."""
    first = _seed(env.home, f"lrn-e3b0d2{'01' if path == 'routed' else '02'}")
    if path == "routed":
        _place(env.home, first, "skill-md")
    target = "_execute_route" if path == "routed" else "_replace_pending"
    real = getattr(verbs, target)
    injected: list[str] = []

    def late_hold(*args, **kwargs):
        # After `_preflight_replace` passed, before the lock: the gate's
        # injection point. A person parks the lesson for the overseer.
        injected.append(_hold(env.home, tmp_path, first))
        return real(*args, **kwargs)

    monkeypatch.setattr(verbs, target, late_hold)
    sheet = _sheet(tmp_path, [{"id": first, "verb": "replace", "trigger": NEW_TRIGGER,
                               "instruction": NEW_INSTRUCTION, "because": "b"}])
    before = _lesson_files(env.home)
    host_tree = _tree(env.host)

    (item,) = batch.run(env.home, sheet, no_push=True, actor="steward").items

    assert injected, "the late hold was injected"  # positive control
    assert (item.state, item.kind) == ("refused", "bad-line"), item.detail
    assert f"the overseer holds {first}" in (item.detail or "")
    assert _porcelain(env.home) == ""
    assert _lesson_files(env.home) == before
    assert _tree(env.host) == host_tree
    assert not any(s.startswith("self-learn: replace") for s in _subjects(env.home, 5))
    assert _rec(env.home, first).status == ("routed" if path == "routed" else "pending")

    # control: the same line, nothing held, applies
    monkeypatch.setattr(verbs, target, real)
    other = _seed(env.home, f"lrn-e3b0d2{'11' if path == 'routed' else '12'}")
    if path == "routed":
        _place(env.home, other, "skill-md")
    again = _sheet(tmp_path, [{"id": other, "verb": "replace", "trigger": NEW_TRIGGER,
                               "instruction": NEW_INSTRUCTION, "because": "b"}], name="again")
    (ok,) = batch.run(env.home, again, no_push=True, actor="steward").items
    assert ok.state == "applied", ok.detail
    assert _porcelain(env.home) == ""


# ======================================================= also trailers


def test_each_also_leg_carries_the_execution_trailers_and_a_re_drive_proves_it(env):
    """E1 gate R1 item 3, last half: `replace_lesson` passes `execution=` to
    each `also` leg's `supersede`, so its commit carries the line's trailer
    block. A re-drive proves the leg by its own subject (`self-learn:
    supersede <also> ...`) and the shared trailers; the primary's proof
    (`self-learn: replace <first> ...`) is still the ONE match for its own
    ref, though every commit of the line now carries the same identity."""
    a, b, c = (_seed(env.home, rid) for rid in ("lrn-e3b0a001", "lrn-e3b0a002", "lrn-e3b0a003"))
    for rid in (a, b, c):
        _place(env.home, rid, "skill-md")
    start = gitops.head_sha(env.home)
    ref = execution_evidence.ExecutionRef(
        run_id="run-e3b", case_id="case-0000e3b0", sheet_sha="0123abcd",
        sheet_digest="0" * 64, item=1, record_id=a, verb="replace", actor="steward",
    )
    verbs.replace_lesson(env.home, a, also=[b, c], trigger=NEW_TRIGGER,
                         instruction=NEW_INSTRUCTION, because="merge", no_push=True,
                         execution=ref, actor="steward")
    new = _rec(env.home, a).superseded_by

    primary = execution_evidence.find_mutation_commit(env.home, ref, after=start)
    assert primary is not None
    assert git(env.home, "log", "-1", "--format=%s", primary).stdout.strip().startswith(
        f"self-learn: replace {a} → {new}")
    for rid in (b, c):
        leg = execution_evidence.ExecutionRef(
            run_id="run-e3b", case_id="case-0000e3b0", sheet_sha="0123abcd",
            sheet_digest="0" * 64, item=1, record_id=rid, verb="supersede", actor="steward",
        )
        sha = execution_evidence.find_mutation_commit(env.home, leg, after=start)
        assert sha is not None, rid
        assert git(env.home, "log", "-1", "--format=%s", sha).stdout.strip() == (
            f"self-learn: supersede {rid} → {new}")
        body = git(env.home, "log", "-1", "--format=%B", sha).stdout
        assert execution_evidence.parse_trailers(body) == ref.trailer_identity()
        # the steward's own effect check accepts the leg: the commit
        # supersedes this lesson by the new one
        from self_learn import steward

        line = batch.SheetItem(n=1, id=rid, verb="supersede", fields={"new_id": new})
        assert steward._verify_mutation_commit(env.home, sha, leg, line) is True
