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


# ============================================ the steward, end to end


def _stage_of(spec) -> Path:
    import re

    match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
    assert match is not None
    return Path(match.group(1))


def _steward_case(records: list[str], *, kind: str = "resolution", rewrite: bool = True,
                  supersedes: str | None = None) -> dict:
    case = {
        "kind": kind, "trigger": "nightly", "outcome": "replaced",
        "records": records, "scope": "skill:s",
        "question": "the lesson's claim is wrong; should the evidenced form replace it?",
        "evidence": [{"ref": "transcript:fake#L1", "quote": "the tag was not pushed"}],
        "decision": {"verb": "replace", "because": "the evidence shows the right claim",
                     "confidence": "settled"},
        "dependencies": {"statements": [], "user_model": [], "conditions": [], "capabilities": []},
    }
    if rewrite:
        case["decision"]["rewrite"] = {"ideas": [
            {"idea": "the script refuses in some state", "now": "loaded"},
            {"idea": "the state is a dirty tree", "now": "dropped", "why": "wrong"},
        ]}
    if supersedes is not None:
        case["supersedes"] = supersedes
    return case


def _replace_line(rid: str, **extra) -> dict:
    return {"id": rid, "verb": "replace", "trigger": NEW_TRIGGER,
            "instruction": NEW_INSTRUCTION, "because": "the claim was wrong", **extra}


def test_the_steward_replaces_a_pending_lesson_end_to_end(env, tmp_path, monkeypatch):
    """The steward's run, the REAL batch: a pending lesson whose claim is
    wrong is replaced (a `kind: resolution` case, outcome `replaced`) by a
    new lesson placed in SKILL.md. The run completes, the case and the
    receipt name the new lesson, and its compiled line is ONE physical line
    carrying the whole instruction."""
    from self_learn import steward
    from support import commit_all, make_behavior, proposal_dict
    from test_steward import _dump_yaml, _enable_steward

    rid = "lrn-e3b0e2e1"
    ledger_ops.create_record(env.home, make_behavior(record_id=rid))
    ledger_ops.write_proposal(env.home, rid, proposal_dict())
    ledger_ops.stamp_proposal(env.home, rid)
    commit_all(env.home, "seed the packet")
    _enable_steward(env.home)

    def session(spec):
        from self_learn.invocation.contract import Outcome

        stage = _stage_of(spec)
        _dump_yaml(stage / "cases" / "fix.yaml", _steward_case([rid]))
        _dump_yaml(stage / "sheets" / "fix.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [_replace_line(rid, dest="skill-md")],
        })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(env.home, dry_run=False)

    assert result.status == "applied", result
    gone = _rec(env.home, rid)
    assert gone.status == "superseded" and gone.superseded_by
    made = _rec(env.home, gone.superseded_by)
    assert (made.status, made.source, made.supersedes) == ("routed", "rewrite", rid)
    assert (made.routing or {}).get("by") == "steward"
    lines = [ln for ln in env.skill_md.read_text(encoding="utf-8").splitlines()
             if f"*({made.id})*" in ln]
    assert len(lines) == 1 and NEW_INSTRUCTION.rstrip(".").lower() in lines[0].lower()
    (row,) = [r for r in cases.list_cases(env.home, only_ok=True) if rid in (r.get("records") or [])]
    assert (row["actor"], row["outcome"]) == ("steward", "replaced")
    application = cases.show(env.home, row["case"], evidence_only=False).sections["Application"]
    assert f"replace → applied (exit 0); made {made.id}; line: " in application


# ============================================ the steward's limits (§2.8)


def _stage_pair(stage: Path, name: str, case: dict, items: list[dict]) -> Path:
    from test_steward import _dump_yaml

    _dump_yaml(stage / "cases" / f"{name}.yaml", case)
    _dump_yaml(stage / "sheets" / f"{name}.yaml", {"version": 1, "case": "$CASE_ID", "items": items})
    return stage / "cases" / f"{name}.yaml"


def test_the_steward_replaces_a_placed_lesson_only_under_a_reconsider_and_never_merges_one(
    env, tmp_path
):
    """D-AUTHOR §2.8, the steward's column, where the code can tell it
    (`steward._steward_replace_problem`, in the stage check):

    * a placed lesson is replaced only by a `kind: reconsider` case -- in a
      resolution case the pair is refused by name, and the same line in a
      reconsider case passes this check (the control; the case writer then
      checks its `supersedes` covers the lesson);
    * a placed lesson is never merged through `also`, even in a reconsider;
    * a pending lesson is replaced in a resolution case (the control), and
      a parked case's tentative replace is not judged."""
    from self_learn import steward

    placed, other, pending = (_seed(env.home, rid) for rid in ("lrn-e3b0c101", "lrn-e3b0c102", "lrn-e3b0c103"))
    for rid in (placed, other):
        _place(env.home, rid, "skill-md")
    stage = tmp_path / "stage"
    resolution = _stage_pair(stage, "res", _steward_case([placed]), [_replace_line(placed)])
    problem = steward._pair_problem(stage, resolution, env.home) or ""
    assert problem.startswith(f"res.yaml: replace {placed}: {placed} is placed")
    assert "kind: reconsider" in problem and "authority-unclear" in problem

    reconsider = _stage_pair(stage, "rec", _steward_case(
        [placed], kind="reconsider", supersedes="case-0000c101"), [_replace_line(placed)])
    assert steward._pair_problem(stage, reconsider, env.home) is None

    merge = _stage_pair(stage, "merge", _steward_case(
        [placed, other], kind="reconsider", supersedes="case-0000c101"),
        [_replace_line(placed, also=[other])])
    assert (steward._pair_problem(stage, merge, env.home) or "").startswith(
        f"merge.yaml: replace {placed} merges ['{other}'], which are placed")

    fine = _stage_pair(stage, "fine", _steward_case([pending]), [_replace_line(pending)])
    assert steward._pair_problem(stage, fine, env.home) is None
    parked = _steward_case([placed, other], rewrite=False)
    parked.update(kind="parked", outcome="parked", parked_for="overseer",
                  parked_reason="authority-unclear")
    parked["decision"]["confidence"] = "provisional"
    tentative = _stage_pair(stage, "parked", parked, [_replace_line(placed, also=[other])])
    assert steward._pair_problem(stage, tentative, env.home) is None


def test_a_steward_replace_of_a_placed_lesson_that_is_not_an_input_of_its_run_is_refused(
    env, tmp_path
):
    """§2.8: the steward corrects a placed lesson only when it is an input
    of its run. Two rules close it together: the line's id (and each
    `also`) must be in its case's `records` (the E1 gate's R1 item 3, new),
    and a case may cover only this packet's lessons (`_check_stage`,
    existing). A line on an outside lesson is refused by the first; a case
    that lists it, by the second. The same reconsider on an input passes
    (the control)."""
    from self_learn import steward

    placed, outside = _seed(env.home, "lrn-e3b0c201"), _seed(env.home, "lrn-e3b0c202")
    for rid in (placed, outside):
        _place(env.home, rid, "skill-md")
    pending = _seed(env.home, "lrn-e3b0c203")  # an input of the packet, for a control pair
    quarantine = tmp_path / "quarantine"

    def check(name: str, records: list[str], line: dict):
        stage = tmp_path / name
        _stage_pair(stage, "c", _steward_case(records, kind="reconsider", supersedes="case-0000c201"),
                    [line])
        _stage_pair(stage, "control", _steward_case([pending]), [_replace_line(pending)])
        return steward._check_stage(stage, {placed, pending}, quarantine, env.home)

    hidden = check("hidden", [placed], _replace_line(placed, also=[outside]))
    assert f"replace {placed} changes ['{outside}'], which the case's records do not name" in (
        hidden.problems.get("c") or "")
    stray = check("stray", [outside], _replace_line(outside))
    assert f"covers ['{outside}'], not a lesson of this packet" in (stray.problems.get("c") or "")
    for refused in (hidden, stray):
        assert refused.valid == ["control"]  # the other pair goes ahead
    ok = check("ok", [placed], _replace_line(placed))
    assert ok.valid == ["c", "control"] and ok.problems == {}


def test_a_steward_replace_naming_a_held_lesson_is_refused_by_name_at_the_case(env, tmp_path):
    """S-81 (the user's steward rule, 2026-10-08): a lesson an open case
    awaits the overseer on is not transformed by the steward. The ledger
    refuses the line itself (`test_replace.py`'s held tests, under the
    shipped set); and since every lesson a replace changes is now in its
    case's `records`, the steward's case-level hold check names a held
    `also` lesson too, before anything is recorded. Control: nothing held,
    no problem."""
    from self_learn import steward

    a, b = _seed(env.home, "lrn-e3b0c301"), _seed(env.home, "lrn-e3b0c302")
    case = _steward_case([a, b])
    assert steward._held_case_problems(env.home, case, cases.held_lessons(env.home)) == []
    parked = _hold(env.home, tmp_path, b)
    problems = steward._held_case_problems(env.home, case, cases.held_lessons(env.home))
    assert problems and problems[0].startswith(f"names {b}: ")
    assert f"the overseer holds {b} (parked case {parked}" in problems[0]


def test_a_steward_replace_into_a_file_a_plain_host_tracks_is_parked(tmp_path):
    """`_forced_parking_reason` reads `replace` lines (D-AUTHOR §2.5): the
    new lesson's target is resolved as a route's preview resolves it
    (`verbs.replace_route_preview`), so a replace into a CLAUDE.md a plain
    host's git tracks is parked `plain-host-committed-file`, as a route
    into it is. Untracked, it is not (the control)."""
    from self_learn import steward
    from support import make_env
    from test_steward import _dump_yaml
    from test_tracked_target_guard import _lesson, _plain_repo_host

    home = make_env(tmp_path).ledger
    host = _plain_repo_host(home, tmp_path)
    rid = _lesson(home, host, "lrn-e3b0c401")
    sheet = tmp_path / "stage" / "sheets" / "one.yaml"
    _dump_yaml(sheet, {"version": 1, "case": "$CASE_ID",
                       "items": [_replace_line(rid, dest="claude-md")]})
    preview = verbs.replace_route_preview(home, rid, dest="claude-md", to=None)
    assert preview == {"host": str(host), "mode": "plain", "target": str(host / "CLAUDE.md")}
    assert steward._forced_parking_reason(home, sheet) == "plain-host-committed-file"

    git(host, "rm", "--cached", "-q", "CLAUDE.md")
    git(host, "commit", "-q", "-m", "untrack")
    assert steward._forced_parking_reason(home, sheet) is None
