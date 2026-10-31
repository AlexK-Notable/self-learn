"""S-NEXT-cures-f (2026-10-31, lane F of the hand-maintenance cures: C4 and C8).

The user's agreement (2026-10-30, "i reviewed checkpoint 90. i agree with the
decisions."): the overseer may write a corrected lesson as a PENDING record for
the steward to decide like a mined one, and may NOT reopen a lesson a person
rejected (it asks a question naming the reject instead); and two defects in the
overseer's own bookkeeping are fixed (crash recovery cannot find project- and
user-scope lessons; its reconsider leaves no `reconsidered` history entry).

What is pinned here:

(1) `restate`, the sheet verb the overseer writes a corrected lesson with:
    a new pending lesson (`source: rewrite`, the old lesson's evidence, a note
    by the actor), the closed lesson left exactly as it is except for one note
    back; idempotent by a state read; refused for an open, placed or replaced
    lesson, for the steward, and for a line with no reason; the preview
    refuses what the run refuses; the steward's brief shows the note; the
    overseer's formats carry an example pair that validates.
(2) `reopen` is refused for the overseer when a person rejected the lesson
    (the newest open `reject` case is a person's, or there is no open reject
    case, as after a hand reject; a case of another outcome says nothing), in
    the run and in the preview, and stays allowed for a person and for a lesson the
    steward or the overseer rejected. The case behind a rejection is read through
    an overseer's reconsider case that superseded it (the S-76 [reopen, route]
    correction of a steward's reject still applies), and a case opened before
    the lesson's latest displaced rejection is not behind the current one.
(3) Crash recovery (`overseer.run._record_at_commit`) finds a lesson in a
    project or the user bucket, not only a skill bucket.
(4) The overseer's reconsider case stamps a `reconsidered` history entry on
    each lesson it covers, even a lesson still pending, once.

Each test says what it fails on without the change. The builder wrote these
without running them (the user's rule of 2026-10-30: tests run once, at
landing); the landing run is their first execution.

Every scenario runs on pytest sandbox ledgers and hosts (`support.make_env`),
with HOME pointed at the sandbox; ids and texts are synthetic. No model call.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from self_learn import batch, cases, steward_inputs, steward_prompt, verbs
from self_learn.ledger_ops import find_record_path
from self_learn.overseer import formats
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
from test_replace import (
    OLD_INSTRUCTION, OLD_TRIGGER, Env, _head, _place, _rec, _seed, _sheet, _subjects,
)
from support import git
from test_steward import _dump_yaml
from test_steward_refusals import _case

A = "lrn-c0f00001"
B = "lrn-c0f00002"
NEW_TRIGGER = "About to delete a build cache to fix a failing build."
NEW_INSTRUCTION = "Look for a stale object file named in the error before touching the cache."
BECAUSE = "the rejected line named the wrong cause"


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ------------------------------------------------------------------ helpers


def _line(rid: str, **extra) -> dict:
    return {
        "id": rid, "verb": "restate", "because": BECAUSE,
        "trigger": NEW_TRIGGER, "instruction": NEW_INSTRUCTION, **extra,
    }


def _run(env: Env, items: list[dict], *, actor: str = "overseer", name: str = "sheet"):
    return batch.run(env.home, _sheet(env.tmp, items, name=name), no_push=True, actor=actor)


def _preview(env: Env, items: list[dict], *, actor: str = "overseer", name: str = "sheet"):
    return batch.dry_run(env.home, _sheet(env.tmp, items, name=name), actor=actor)


def _made(item: batch.ItemResult) -> str:
    match = re.search(r"made (lrn-[0-9a-f]{8})", item.detail or "")
    assert match is not None, item
    return match.group(1)


def _rejected(env: Env, rid: str, **seed) -> str:
    _seed(env.home, rid, **seed)
    verbs.reject(env.home, rid, no_push=True)
    return rid


def _record_case(env: Env, name: str, records: list[str], outcome: str, actor: str, **extra) -> str:
    stage = env.tmp / f"{name}.yaml"
    data = _case(records, outcome, outcome)
    data.update(extra)
    _dump_yaml(stage, data)
    return cases.record(env.home, stage, actor=actor)


def _pending_files(env: Env, rid: str) -> list[str]:
    bucket = find_record_path(env.home, rid).parent.parent
    return sorted(path.name for path in (bucket / "pending").glob("*.md"))


# ===================================================== (1) restate, the verb


def test_a_restate_writes_a_pending_lesson_and_leaves_the_rejection_alone(env):
    """Without the verb a sheet naming `restate` is refused at load (an unknown
    verb); the rest pins the shape of what it writes."""
    _rejected(env, A, evidence=[{"session": "s-1", "quote": "flat yield"}])
    before = _rec(env.home, A)

    result = _run(env, [_line(A)])

    (item,) = result.items
    assert (item.state, item.rc) == ("applied", 0), item
    new_id = _made(item)
    new, after = _rec(env.home, new_id), _rec(env.home, A)
    assert (new.status, new.source, new.supersedes) == ("pending", "rewrite", None)
    assert new.type == "behavior" and new.kind == before.kind
    assert NEW_TRIGGER in new.body and NEW_INSTRUCTION in new.body
    assert list(new.evidence) == list(before.evidence)  # the steward's pack has real material
    (new_note,) = new.notes
    assert new_note["by"] == "overseer"
    assert new_note["text"] == f"restates {A} (rejected): {BECAUSE}"
    assert new_note["key"].startswith("restate-")
    # The rejection stands, byte for byte, but for the one note back.
    assert (after.status, after.body, after.resolution_note, after.superseded_by) == (
        before.status, before.body, before.resolution_note, before.superseded_by,
    )
    (back,) = after.notes
    assert back["by"] == "overseer" and back["key"] == new_note["key"]
    assert back["text"] == f"restated as {new_id}: {BECAUSE}"
    assert _subjects(env.home, 1) == [f"self-learn: restate {A} → {new_id} (pending)"]
    assert find_record_path(env.home, new_id).parent.name == "pending"
    assert find_record_path(env.home, A).parent.name == "resolved"


def test_a_restate_applied_twice_writes_one_lesson(env):
    """Idempotence by a state read (the closed lesson's note key): a second run
    is `already-applied`, writes nothing, and makes no second lesson. Without
    the `classify` branch the second run would make a second pending lesson."""
    _rejected(env, A)
    _run(env, [_line(A)])
    head, files = _head(env.home), _pending_files(env, A)
    assert len(files) == 1  # control: the first run made exactly one

    again = _run(env, [_line(A)])

    (item,) = again.items
    assert item.state == "already-applied", item
    assert _head(env.home) == head
    assert _pending_files(env, A) == files


def test_a_different_text_for_the_same_lesson_is_a_new_restatement(env):
    _rejected(env, A)
    _run(env, [_line(A)])
    other = _line(A, instruction="Read the first error line, then act on it.")

    (item,) = _run(env, [other], name="second").items

    assert item.state == "applied", item
    assert len(_pending_files(env, A)) == 2


@pytest.mark.parametrize(
    "setup, fragment",
    [
        ("pending", "not closed"),
        ("routed", "not closed"),
        ("replaced", "was replaced by"),
    ],
)
def test_a_restate_of_an_open_placed_or_replaced_lesson_is_refused_by_name(env, setup, fragment):
    """`replace` takes over from an open or placed lesson; a replaced lesson's
    successor is the one to restate. Each is `bad-line` with nothing written,
    and the preview says the same words and kind."""
    _seed(env.home, A)
    if setup == "routed":
        _place(env.home, A, "skill-md")
    if setup == "replaced":
        _seed(env.home, B)
        verbs.supersede(env.home, A, B, no_push=True)
    head = _head(env.home)

    preview = _preview(env, [_line(A)])
    (got,) = _run(env, [_line(A)]).items

    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert fragment in (got.detail or ""), got.detail
    # Nothing written. The run flushes the telemetry the `route` above left
    # buffered, so a telemetry flush may ride on top (as in test_replace);
    # integration 2026-10-31: the bare HEAD comparison failed on that flush.
    made = git(env.home, "log", "--format=%s", f"{head}..HEAD").stdout.splitlines()
    assert all(s.startswith("self-learn: telemetry flush") for s in made), made
    assert git(env.home, "diff", "--name-only", head, "HEAD", "--", ".", ":!telemetry").stdout == ""
    (shown,) = preview.items
    assert (shown.state, shown.kind) == ("would-refuse", "bad-line"), shown
    assert fragment in (shown.detail or ""), shown.detail


def test_a_retired_lesson_may_be_restated(env):
    _seed(env.home, A)
    _place(env.home, A, "skill-md")
    verbs.retire(env.home, A, covered_by="skill-md:s", no_push=True)
    assert _rec(env.home, A).status == "superseded"  # control: it is retired, not replaced

    (item,) = _run(env, [_line(A)]).items

    assert item.state == "applied", item
    assert _rec(env.home, _made(item)).status == "pending"


def test_a_restate_preview_applies_for_a_closed_lesson_and_writes_nothing(env):
    _rejected(env, A)
    head = _head(env.home)

    (shown,) = _preview(env, [_line(A)]).items

    assert (shown.state, shown.kind) == ("would-apply", None), shown
    assert _head(env.home) == head
    assert _pending_files(env, A) == []


def test_the_steward_is_refused_a_restate_by_name_and_the_overseer_is_not(env):
    """No actor both writes and decides the lesson. Positive control: the same
    line through the overseer's runner applies."""
    assert batch.agent_refused_verbs("steward") == frozenset({"restate"})
    assert "restate" not in batch.agent_refused_verbs("overseer")
    _rejected(env, A)
    head = _head(env.home)

    (refused,) = _run(env, [_line(A)], actor="steward").items
    (shown,) = _preview(env, [_line(A)], actor="steward").items

    assert (refused.state, refused.kind) == ("refused", "bad-line"), refused
    assert "`restate` is refused for the steward" in (refused.detail or "")
    assert (shown.state, shown.kind, shown.detail) == ("would-refuse", "bad-line", refused.detail)
    assert _head(env.home) == head
    (ok,) = _run(env, [_line(A)], actor="overseer").items  # control
    assert ok.state == "applied", ok


def test_the_contracts_list_restate_for_the_overseer_and_not_for_the_steward():
    sheet_verbs = formats.closed_sets()["sheet"]["verbs"]
    assert sheet_verbs["restate"]["required"] == ["because"]
    assert "replace" in sheet_verbs  # control: the table is read, not empty
    listed = [line.split()[0] for line in steward_prompt._sheet_verb_lines()]
    assert "replace" in listed and "restate" not in listed


def test_a_restate_line_needs_its_reason_and_takes_no_destination(env):
    _rejected(env, A)
    no_reason = _line(A)
    del no_reason["because"]
    with pytest.raises(batch.BatchError, match="missing required"):
        _sheet(env.tmp, [no_reason], name="no-reason")
    with pytest.raises(batch.BatchError, match="unknown key"):
        _sheet(env.tmp, [_line(A, dest="skill-md")], name="with-dest")  # the steward places it


def test_a_restate_names_its_own_verb_in_a_text_refusal_and_replace_keeps_its_own(env):
    _rejected(env, A)
    (got,) = _run(env, [_line(A, fact="A fact as well.")]).items
    assert got.kind == "bad-line"
    assert "restate: a lesson is behavior" in (got.detail or ""), got.detail
    _seed(env.home, B)  # control: the replace wording is unchanged
    (replaced,) = _run(
        env, [{"id": B, "verb": "replace", "because": "x", "trigger": "t", "fact": "f"}],
        name="replace",
    ).items
    assert "replace: a lesson is behavior" in (replaced.detail or ""), replaced.detail


def test_the_steward_brief_shows_the_overseers_note_on_a_restated_lesson(env):
    _rejected(env, A)
    (item,) = _run(env, [_line(A)]).items
    new = _rec(env.home, _made(item))

    text = steward_inputs.render_record(new, path=None, head=None, bucket="skill:s")

    assert f"[restated by the overseer] restates {A} (rejected): {BECAUSE}" in text
    ordinary = steward_inputs.render_record(
        _rec(env.home, A), path=None, head=None, bucket="skill:s"
    )  # control: the closed lesson's note back is not shown as a restatement
    assert "[restated by the overseer]" not in ordinary


def test_the_overseers_restate_example_pair_validates_and_the_readme_names_it(tmp_path):
    root = formats.write(tmp_path / "ws", "B")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "case-restate-example.yaml" in readme and "`restate`" in readme
    case_file, sheet_file = root / "case-restate-example.yaml", root / "sheet-restate-example.yaml"
    assert overseer_run._is_maintenance_pair(case_file)
    overseer_run._validate_maintenance_case(case_file)
    assert overseer_run._case_rule_problem(case_file, "abcd1234") is None
    sheet = overseer_run._yaml_mapping(sheet_file)
    (item,) = sheet["items"]
    assert item["verb"] == "restate" and item["id"] in overseer_run._yaml_mapping(case_file)["records"]
    for key in ("trigger", "instruction"):
        assert "\n" not in str(item[key])  # one physical line


def test_a_restate_with_the_words_of_the_closed_lesson_is_refused_in_run_and_preview(env):
    """Without the check, the same words come back as a pending lesson: a
    reopen by another route, which the overseer is refused for a person's
    reject. White space and the context do not make a new version; a changed
    instruction does (control)."""
    _rejected(env, A)
    head = _head(env.home)
    same = _line(
        A, trigger=f"  {OLD_TRIGGER}  ", instruction=OLD_INSTRUCTION.replace(" ", "  ", 1),
        context="A new context.",
    )

    (got,) = _run(env, [same]).items
    (shown,) = _preview(env, [same], name="preview").items

    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert "same as the lesson's own" in (got.detail or ""), got.detail
    assert (shown.state, shown.kind) == ("would-refuse", "bad-line"), shown
    assert _head(env.home) == head and len(_pending_files(env, A)) == 0
    changed = _line(A, trigger=OLD_TRIGGER, instruction=NEW_INSTRUCTION)  # control
    (ok,) = _run(env, [changed], name="changed").items
    assert (ok.state, ok.rc) == ("applied", 0), ok


def test_a_restate_pair_whose_case_does_not_name_the_lesson_is_dropped(env):
    """The case is the account of the correction: a restate line's lesson must
    be one of its records (the same first rule `replace` has)."""
    line = {"id": A, "verb": "restate"}
    unrelated = {"records": [B], "kind": "maintenance"}
    covering = {"records": [A, B], "kind": "maintenance"}

    problem = overseer_run._restate_items_problem(unrelated, [line], label="case.yaml")

    assert problem is not None and A in problem and "case.yaml" in problem
    assert overseer_run._restate_items_problem(covering, [line], label="case.yaml") is None
    other = {"id": A, "verb": "reject"}  # control: only a restate line is held to it
    assert overseer_run._restate_items_problem(unrelated, [other], label="case.yaml") is None


# ======================================= (2) the overseer never reopens a
#                                           person's rejection


def _reopen(rid: str) -> dict:
    return {"id": rid, "verb": "reopen"}


def test_the_overseer_cannot_reopen_a_lesson_a_person_rejected(env):
    """Without the guard this applies (the overseer's reopen had no actor
    check). The refusal is `needs-person`, names the case and the two other
    ways (`restate`, a question), and the preview says the same."""
    _rejected(env, A)
    case = _record_case(env, "person-reject", [A], "reject", actor="human")
    head = _head(env.home)

    (got,) = _run(env, [_reopen(A)]).items
    (shown,) = _preview(env, [_reopen(A)]).items

    assert (got.state, got.kind) == ("refused", "needs-person"), got
    assert case in (got.detail or "") and "restate" in (got.detail or ""), got.detail
    assert "question" in (got.detail or "")
    assert (shown.state, shown.kind, shown.detail) == ("would-refuse", "needs-person", got.detail)
    assert _head(env.home) == head
    assert _rec(env.home, A).status == "rejected"


def test_a_lesson_rejected_with_no_case_an_agent_recorded_counts_as_a_persons(env):
    """The ledger does not store who rejected a lesson. A hand reject with no
    case cannot be shown to be an agent's, so the overseer leaves it."""
    _rejected(env, A)

    (got,) = _run(env, [_reopen(A)]).items

    assert (got.state, got.kind) == ("refused", "needs-person"), got
    assert "rejected by hand" in (got.detail or ""), got.detail


def test_the_overseer_may_reopen_a_lesson_an_agent_rejected(env):
    """Control for the guard: it protects a person's rejection, not every one.
    A lesson the steward rejected in an open case of its own is the overseer's
    to reopen, as before."""
    _rejected(env, A)
    _record_case(env, "steward-reject", [A], "reject", actor="steward")

    (got,) = _run(env, [_reopen(A)]).items

    assert (got.state, got.rc) == ("applied", 0), got
    assert _rec(env.home, A).status == "pending"


def test_a_person_may_still_reopen_what_a_person_rejected(env):
    """The guard is keyed on the runner's actor: a person's own sheet (and the
    CLI) reopen as ever. Without this the guard would be a lock on people."""
    _rejected(env, A)
    _record_case(env, "person-reject", [A], "reject", actor="human")

    (got,) = _run(env, [_reopen(A)], actor="human").items

    assert (got.state, got.rc) == ("applied", 0), got
    assert _rec(env.home, A).status == "pending"


def test_a_sheet_line_cannot_name_itself_a_person_to_pass_the_guard(env):
    """`by: human` on the line is the line's own text; the actor is the
    runner's."""
    _rejected(env, A)
    _record_case(env, "person-reject", [A], "reject", actor="human")

    (got,) = _run(env, [{**_reopen(A), "by": "human"}]).items

    assert (got.state, got.kind) == ("refused", "needs-person"), got


def test_a_superseded_person_case_does_not_protect_a_lesson_an_agent_then_rejected(env):
    """Only an OPEN case counts: a person's case an agent's reconsider has
    superseded no longer speaks for the lesson."""
    _rejected(env, A)
    prior = _record_case(env, "person-reject", [A], "reject", actor="human")
    # A steward reconsider case supersedes the person's. `cases.record` marks
    # the person's case superseded; the open case is now the steward's.
    _record_case(
        env, "steward-reconsider", [A], "reject", actor="steward",
        kind="reconsider", trigger="reconsider", supersedes=prior,
    )
    assert verbs.person_reject_case(env.home, A) == ""  # the reading the guard makes

    (got,) = _run(env, [_reopen(A)]).items

    assert (got.state, got.rc) == ("applied", 0), got


def _maintenance_case(env: Env, name: str, rid: str, actor: str = "overseer") -> str:
    """The case an overseer's `restate` pair carries: maintenance, `no-action`
    (the closed lesson is not decided again), naming the lesson in its records."""
    data = _case([rid], "no-action", "no-action")
    data.update(kind="maintenance", trigger="weekly")
    data["decision"] = {"because": "the correction leaves the reject in place", "confidence": "provisional"}
    stage = env.tmp / f"{name}.yaml"
    _dump_yaml(stage, data)
    return cases.record(env.home, stage, actor=actor)


def test_an_overseer_restate_case_does_not_turn_a_persons_reject_into_the_overseers(env):
    """The overseer's own `restate` writes a no-action case that names the
    lesson. A hand reject plus that case (week N) must still refuse the
    overseer's reopen (week N+1): only a case whose outcome is `reject` speaks
    for who rejected the lesson. Before the fix any open agent case did, so
    this reopen applied."""
    _rejected(env, A)  # a hand reject: no case
    _run(env, [_line(A)])  # week N: the overseer's restate
    case = _maintenance_case(env, "restate-case", A)
    assert [r["outcome"] for r in cases.list_cases(env.home, record_id=A)] == ["no-action"]  # control
    head = _head(env.home)

    (got,) = _run(env, [_reopen(A)], name="week-n1").items
    (shown,) = _preview(env, [_reopen(A)], name="week-n1-preview").items

    assert (got.state, got.kind) == ("refused", "needs-person"), got
    assert "rejected by hand" in (got.detail or ""), (case, got.detail)
    assert (shown.state, shown.kind) == ("would-refuse", "needs-person"), shown
    assert _head(env.home) == head and _rec(env.home, A).status == "rejected"


def test_a_steward_case_of_another_outcome_does_not_hand_a_persons_reject_to_the_overseer(env):
    """A steward `defer` case came first; a person rejected the lesson by hand
    afterwards. The defer case does not say who rejected it."""
    _seed(env.home, A)
    _record_case(env, "steward-defer", [A], "defer", actor="steward")
    verbs.reject(env.home, A, no_push=True)  # a hand reject, no case

    (got,) = _run(env, [_reopen(A)]).items

    assert (got.state, got.kind) == ("refused", "needs-person"), got
    assert verbs.person_reject_case(env.home, A) != ""


def test_a_persons_reject_case_is_not_displaced_by_a_later_case_of_another_outcome(env):
    """A person's reject case followed by a no-action agent case: still the
    person's, because only reject cases are read."""
    _rejected(env, A)
    _record_case(env, "person-reject", [A], "reject", actor="human")
    _maintenance_case(env, "later-note", A)

    why = verbs.person_reject_case(env.home, A)

    assert "which a person recorded" in why, why


def test_the_overseers_reconsider_of_a_stewards_reject_can_reopen_it(env):
    """S-76, the way the overseer corrects a steward's wrong reject: a
    `kind: reconsider` case (outcome `route`) supersedes the steward's reject
    case, and its sheet is [reopen, route]. The reconsider case is recorded
    BEFORE the sheet applies, so at the reopen the steward's case is already
    superseded and no open case has outcome `reject`. The fix-round-1 reading
    (open reject cases only) called that a hand reject and refused the reopen
    as `needs-person`, finally; the preview, taken first, agreed with the run
    only because the case did not exist yet. The reading now follows the
    supersede chain through a reconsider case."""
    _rejected(env, A)
    prior = _record_case(env, "steward-reject", [A], "reject", actor="steward")
    assert verbs.person_reject_case(env.home, A) == ""  # control: the steward's case is read
    stage = env.tmp / "overseer-reconsider.yaml"
    data = _case([A], "route", "route")
    data.update(kind="reconsider", trigger="reconsider", supersedes=prior)
    _dump_yaml(stage, data)
    successor = cases.record(env.home, stage, actor="overseer")
    # Positive control: the steward's case is superseded and no open case rejects.
    rows = {r["case"]: r for r in cases.list_cases(env.home, record_id=A)}
    assert rows[prior]["superseded_by"] == successor and rows[successor]["outcome"] == "route"
    assert verbs.person_reject_case(env.home, A) == ""
    items = [_reopen(A), {"id": A, "verb": "route", "dest": "skill-md"}]

    shown = _preview(env, items[:1], name="reconsider-preview")
    got = batch.run(
        env.home, _sheet(env.tmp, items, case=successor, name="reconsider-run"),
        no_push=True, actor="overseer",
    )

    assert [(i.state, i.kind) for i in shown.items] == [("would-apply", None)], shown.items
    assert [(i.state, i.rc) for i in got.items] == [("applied", 0), ("applied", 0)], got.items
    assert _rec(env.home, A).status == "routed"


def test_the_overseers_reconsider_of_a_persons_reject_still_cannot_reopen_it(env):
    """The chain is followed to the case behind the rejection and its actor
    decides: a reconsider that supersedes a PERSON's reject case does not
    hand the lesson to the overseer."""
    _rejected(env, A)
    prior = _record_case(env, "person-reject", [A], "reject", actor="human")
    stage = env.tmp / "overseer-reconsider.yaml"
    data = _case([A], "route", "route")
    data.update(kind="reconsider", trigger="reconsider", supersedes=prior)
    _dump_yaml(stage, data)
    successor = cases.record(env.home, stage, actor="overseer")

    got = batch.run(
        env.home, _sheet(env.tmp, [_reopen(A)], case=successor, name="reconsider-run"),
        no_push=True, actor="overseer",
    )

    (item,) = got.items
    assert (item.state, item.kind) == ("refused", "needs-person"), item
    assert prior in (item.detail or ""), item.detail
    assert _rec(env.home, A).status == "rejected"


def test_an_agents_old_reject_case_does_not_cover_a_later_hand_reject(env):
    """The steward rejected the lesson, it was reopened, and a person then
    rejected it by hand (no case). The steward's case is still open and still
    has outcome `reject`, but the reopen displaced the rejection it covered
    (a `resolution` history entry with status `rejected`), so the case is not
    behind the current one and the overseer may not reopen it. Without the
    displacement filter this reopen applies."""
    _rejected(env, A)
    _record_case(env, "steward-reject", [A], "reject", actor="steward")
    assert verbs.person_reject_case(env.home, A) == ""  # control: it covers the first reject
    verbs.reopen(env.home, A, no_push=True)
    verbs.reject(env.home, A, no_push=True)  # a person's hand reject, no case
    assert any(
        e.get("event") == "resolution" and e.get("status") == "rejected"
        for e in _rec(env.home, A).history
    )  # control: the displacement the filter reads is there

    (got,) = _run(env, [_reopen(A)]).items
    (shown,) = _preview(env, [_reopen(A)], name="hand-reject-preview").items

    assert (got.state, got.kind) == ("refused", "needs-person"), got
    assert "rejected by hand" in (got.detail or ""), got.detail
    assert (shown.state, shown.kind) == ("would-refuse", "needs-person"), shown
    assert _rec(env.home, A).status == "rejected"


def test_a_line_cannot_sign_an_overseers_restatement_as_a_person(env):
    """`by: human` on an overseer's restate line is the line's own text: the
    note on the new lesson (which the steward's brief reads for the
    `[restated by the overseer]` line) and the trailer name the runner's
    actor. Without the change the note reads `human`."""
    _rejected(env, A)

    (item,) = _run(env, [_line(A, by="human")]).items

    assert (item.state, item.rc) == ("applied", 0), item
    (note,) = _rec(env.home, _made(item)).notes
    assert note["by"] == "overseer", note
    assert "By: human" not in git(env.home, "log", "-1", "--format=%B").stdout


# ================================ (3) crash recovery finds every scope's lessons


@pytest.mark.parametrize("scope", ["skill:s", "project", "user"])
def test_crash_recovery_finds_a_lesson_in_any_bucket_root(env, scope):
    """`_record_at_commit` listed `skills` alone: a project or user lesson was
    never found at its proof commit, so every verb but a move was reported as
    not establishing the original item. The skill case is the control."""
    rid = _seed(env.home, A, scope=scope, project_path=env.host if scope == "project" else None)

    found = overseer_run._record_at_commit(env.home, "HEAD", rid)

    assert found is not None, scope
    path, record = found
    assert record.id == rid and path.name == f"{rid}.md"
    assert path.parts[0] == {"skill:s": "skills", "project": "projects", "user": "user"}[scope]


@pytest.mark.parametrize("scope", ["project", "user"])
def test_a_reject_in_a_project_or_user_bucket_is_established_by_its_proof_commit(env, scope):
    rid = _seed(env.home, A, scope=scope, project_path=env.host if scope == "project" else None)
    verbs.reject(env.home, rid, no_push=True)
    item = {"id": rid, "verb": "reject"}

    committed = overseer_run._record_at_commit(env.home, "HEAD", rid)

    assert committed is not None
    assert overseer_run._candidate_establishes(env.home, committed, item) is True
    other = {"id": rid, "verb": "defer", "until": "2999-01-01"}  # control: a wrong verb is not
    assert overseer_run._candidate_establishes(env.home, committed, other) is False


def test_a_restate_is_established_by_the_note_it_left_on_the_closed_lesson(env):
    _rejected(env, A)
    item = _line(A)
    _run(env, [item])
    committed = overseer_run._record_at_commit(env.home, "HEAD", A)
    assert committed is not None

    assert overseer_run._candidate_establishes(env.home, committed, item) is True
    different = _line(A, instruction="Something else entirely.")  # control: another line is not
    assert overseer_run._candidate_establishes(env.home, committed, different) is False


# ============================ (4) the overseer's reconsider leaves its trace


def _reconsider_case(env: Env, rid: str, *, outcome: str = "route") -> tuple[Path, str]:
    """A steward case on *rid* and an overseer `kind: reconsider` successor of
    it; returns the staged successor file and its id."""
    prior = _record_case(env, "prior", [rid], outcome, actor="steward")
    stage = env.tmp / "again.yaml"
    data = _case([rid], outcome, outcome)
    data.update(kind="reconsider", trigger="reconsider", supersedes=prior)
    _dump_yaml(stage, data)
    return stage, cases.record(env.home, stage, actor="overseer")


def _reconsidered(env: Env, rid: str) -> list[dict]:
    return [dict(e) for e in _rec(env.home, rid).history if e.get("event") == "reconsidered"]


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_an_overseer_reconsider_stamps_each_lesson_it_covers_once(env, status):
    """Before, only `verbs.reconsider` (the steward's apply and a person's CLI)
    wrote the entry; the overseer applied its reconsider's sheet and left the
    lesson's history silent. A pending lesson is the case `verbs.reconsider`'s
    own status check refuses (a decision whose line never applied), which the
    overseer's stamp must still cover; a second call writes nothing."""
    _seed(env.home, A)
    if status == "rejected":
        verbs.reject(env.home, A, no_push=True)
    stage, case_id = _reconsider_case(env, A)
    assert _reconsidered(env, A) == []  # control: nothing before

    overseer_run._stamp_reconsidered(env.home, stage, case_id)

    (entry,) = _reconsidered(env, A)
    assert entry["case"] == case_id and entry["supersedes"]
    assert _subjects(env.home, 1) == [f"self-learn: reconsider {A} (case {case_id})"]
    head = _head(env.home)
    overseer_run._stamp_reconsidered(env.home, stage, case_id)
    assert _head(env.home) == head and len(_reconsidered(env, A)) == 1


def test_a_case_that_is_not_a_reconsider_stamps_nothing(env):
    _seed(env.home, A)
    stage = env.tmp / "plain.yaml"
    data = _case([A], "reject", "reject")
    _dump_yaml(stage, data)
    case_id = cases.record(env.home, stage, actor="overseer")
    head = _head(env.home)

    overseer_run._stamp_reconsidered(env.home, stage, case_id)

    assert _head(env.home) == head and _reconsidered(env, A) == []


def test_the_stamp_and_the_reconsider_sheet_compose_in_the_runners_order(env):
    """The order `_run_manifest_sheet` uses: the case is recorded, the stamp is
    written, then the sheet applies under that case. The stamp does not stand
    in the way of the line (a reject of a placed lesson under its reconsider
    case), and the lesson ends rejected with exactly one entry."""
    _seed(env.home, A)
    _place(env.home, A, "skill-md")
    stage, case_id = _reconsider_case(env, A, outcome="reject")

    overseer_run._stamp_reconsidered(env.home, stage, case_id)
    sheet = _sheet(env.tmp, [{"id": A, "verb": "reject"}], case=case_id, name="reject-sheet")
    result = batch.run(env.home, sheet, no_push=True, actor="overseer")

    (item,) = result.items
    assert (item.state, item.rc) == ("applied", 0), item
    after: Record = _rec(env.home, A)
    assert after.status == "rejected"
    assert [e["case"] for e in after.history if e.get("event") == "reconsidered"] == [case_id]


def test_the_runner_stamps_the_reconsider_it_has_just_recorded(env, monkeypatch):
    """`_stamp_reconsidered` is exercised directly above; this pins its wiring
    in `_run_manifest_sheet`: the case is recorded first, then the stamp is
    called with that case. Deleting the call lets this fall through (no
    sentinel raised)."""
    _seed(env.home, A)
    prior = _record_case(env, "prior", [A], "route", actor="steward")
    case = _case([A], "reject", "reject")
    case.update(kind="reconsider", trigger="reconsider", supersedes=prior)
    stage = env.tmp / "stage"
    case_file, sheet_file = env.tmp / "case-src.yaml", env.tmp / "sheet-src.yaml"
    _dump_yaml(case_file, case)
    _dump_yaml(sheet_file, {"version": 1, "items": [{"id": A, "verb": "reject"}]})
    recipe = {
        "case_name": "case-reconsider.yaml", "case_text": case_file.read_text(encoding="utf-8"),
        "sheet_name": "sheet-reconsider.yaml", "sheet": sheet_file.read_text(encoding="utf-8"),
    }
    calls: list[tuple] = []

    def spy(home, case_path, case_id):
        calls.append((home, case_path.name, case_id))
        raise RuntimeError("stamp-called")

    monkeypatch.setattr(overseer_run, "_stamp_reconsidered", spy)
    case_id = "case-0ddba11e"

    with pytest.raises(RuntimeError, match="stamp-called"):
        overseer_run._run_manifest_sheet(env.home, stage, {}, case_id, recipe, gate=False)

    assert calls == [(env.home, "case-reconsider.yaml", case_id)]
    shown = cases.show(env.home, case_id, evidence_only=False).frontmatter
    assert shown["supersedes"] == prior  # the case was recorded before the stamp
    assert cases.show(env.home, prior, evidence_only=False).frontmatter["superseded_by"] == case_id


def test_a_failed_stamp_does_not_refuse_the_case_it_follows(env, monkeypatch):
    """The stamp runs after the case is recorded and its predecessor
    superseded, so its failure is not a case refusal (which would drop the
    sheet for good): it propagates, and the resume drives the stamp again."""
    _seed(env.home, A)
    stage_file, case_id = _reconsider_case(env, A)

    def broken(*args, **kwargs):
        raise verbs.VerbError("the ledger is not what it was a moment ago")

    monkeypatch.setattr(overseer_run.verbs, "reconsider", broken)

    with pytest.raises(verbs.VerbError):
        overseer_run._stamp_reconsidered(env.home, stage_file, case_id)
