"""S-88 (2026-10-16): the steward settles a deferred lesson no case covers.

Live run `run-85e1b89015c0` (2026-10-12): a lesson deferred twice by a
bare `self-learn defer` -- which writes no case -- came due and reached the
steward as an ordinary queued lesson. The brief said `kind: reconsider` is
for "a lesson an earlier case ... deferred", so the model staged a
`kind: reconsider` case with `supersedes` unset and a `reject` line. It
passed every check, was recorded, and `verbs.reconsider` refused it at
apply time ("names no predecessor case (supersedes is unset) -- no case"),
kind `unclassified`: the runner parked the lesson for the overseer
(`ledger-refused`) and the steward's decision was never applied.

Now:

1. the repair turn refuses a staged `kind: reconsider` case whose
   `supersedes` -- after the runner's own fill from a reconsider input's
   predecessor -- is unset, or names a case a reconsider cannot supersede
   for that lesson (`cases.require_reconsider_predecessor`, and not
   superseded already), and says to decide it with `kind: resolution`;
2. a queued deferred lesson no such case covers carries a card line that
   says so;
3. the brief and the method say the same.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real ``~/.self-learn``) with fake model sessions that
write the stage files; the runner does the rest for real. No real model
call; ids and texts are synthetic.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import cases, gitops, ledger_ops, statements, steward, steward_prompt, verbs, worker
from self_learn.invocation.contract import Outcome
from self_learn.records import Record
from support import git, make_env
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir
from test_steward_refusals import _REPAIR_HEADER, _case, _notifications, _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_NO_DEPS = {"statements": [], "user_model": [], "conditions": [], "capabilities": []}

#: The words of the repair turn's new check and of the card line.
_NO_EARLIER_CASE = "no earlier case covers it"
_CARD_LINE = (
    "This lesson was deferred without a case: there is no earlier case to reconsider."
)


def _status(home: Path, rid: str) -> str:
    return Record.from_path(ledger_ops.find_record_path(home, rid)).status


def _repair_part(prompt: str) -> str:
    assert _REPAIR_HEADER in prompt
    return prompt.split(_REPAIR_HEADER, 1)[1]


def _brief_of(prompt: str, rid: str) -> str:
    """One lesson's brief in a steward prompt: from its heading to the next."""
    match = re.search(rf"^### brief: {rid}$(.*?)(?=^### brief: |\Z)", prompt, re.M | re.S)
    assert match is not None, prompt
    return match.group(1)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _deferred_without_case(home: Path, rid: str) -> str:
    """The live shape: two bare defers and no case. The second one makes
    the deferral due today (`until == today` is accepted, and the queue
    admits `deferred_until <= now`)."""
    _seed(home, rid)
    verbs.defer(home, rid, by="human", no_push=True)
    verbs.defer(home, rid, until=_today(), by="human", no_push=True)
    return rid


def _reject_case(rid: str, *, kind: str, supersedes: str | None = None) -> dict:
    case = _case([rid], "reject", "reject")
    case["kind"] = kind
    case["question"] = "this deferred lesson came due; settle it now?"
    if kind == "reconsider":
        case["trigger"] = "reconsider"
    if supersedes is not None:
        case["supersedes"] = supersedes
    return case


def _session(rid: str, first: dict, repair: dict, prompts: list[str]):
    def write(spec):
        prompts.append(spec.prompt)
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / f"{rid}.yaml", repair if _REPAIR_HEADER in spec.prompt else first)
        _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
            "version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}],
        })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def _packet(home: Path, run_id: str | None) -> dict:
    assert run_id is not None
    return _head_manifest(home, run_id)["packets"][0]


# ------------------------------------------------- scenario A, the live bug


def test_a_reconsider_case_for_a_deferred_lesson_no_case_covers_is_repaired_and_settles(
    tmp_path, monkeypatch
):
    """Scenario A. The first pass stages the live case: `kind: reconsider`,
    `supersedes` unset, outcome `reject`, a `reject` line. The repair turn
    names the lesson and says no earlier case covers it; the repaired
    `kind: resolution` case with the same line applies. The lesson ends
    `rejected`, with no `ledger-refused` parked case and no `unclassified`
    refusal in the run record."""
    home = make_env(tmp_path).ledger
    rid = _deferred_without_case(home, "lrn-d0f00001")
    _enable_steward(home)
    # positive controls: deferred, due, and no case names it at all
    assert _status(home, rid) == "deferred"
    assert rid in {entry.record.id for entry, _row in steward._eligible_lessons(home)}
    assert cases.list_cases(home, record_id=rid) == []
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session", _session(
        rid, _reject_case(rid, kind="reconsider"), _reject_case(rid, kind="resolution"), prompts,
    ))

    result = steward.run(home)

    packet = _packet(home, result.run_id)
    (row,) = packet["inputs"]
    assert (row["record"], row["kind"], row["record_status"]) == (rid, "lesson", "deferred")
    # the card line reached the first prompt, on this lesson's brief
    assert _CARD_LINE in _brief_of(prompts[0], rid), prompts[0]
    assert len(prompts) == 2, "the repair turn was offered"
    repair = _repair_part(prompts[1])
    assert f"- cases/{rid}.yaml: record {rid}: {_NO_EARLIER_CASE}" in repair, repair
    assert "`kind: resolution`" in repair
    assert _status(home, rid) == "rejected"
    assert result.decided == [rid]
    disposition = packet["dispositions"][rid]
    assert disposition["state"] == "applied", disposition
    assert disposition.get("kind") != "unclassified"
    assert not cases.list_cases(home, parked_reason="ledger-refused")
    decided_by = cases.list_cases(home, record_id=rid)
    assert [(c["kind"], c.get("supersedes")) for c in decided_by] == [("resolution", None)]
    run_text = git(home, "show", f"HEAD:cases/runs/{result.run_id}.json").stdout
    assert "unclassified" not in run_text and "no predecessor case" not in run_text


def test_the_dry_run_reports_the_same_refusal_and_writes_nothing(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    rid = _deferred_without_case(home, "lrn-d0f00002")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session", _session(
        rid, _reject_case(rid, kind="reconsider"), _reject_case(rid, kind="resolution"), prompts,
    ))
    head = gitops.head_sha(home)

    result = steward.run(home, dry_run=True)

    assert result.status == "dry-run"
    assert len(prompts) == 2, "the repair turn was offered"
    assert f"- cases/{rid}.yaml: record {rid}: {_NO_EARLIER_CASE}" in _repair_part(prompts[1])
    assert gitops.head_sha(home) == head
    assert git(home, "status", "--porcelain").stdout == ""
    assert _status(home, rid) == "deferred"


# ------------------------------------- the positive control: a real chain


class Covered:
    """A lesson an earlier case DEFERRED (a case-backed defer), so a
    `kind: reconsider` case naming that case is what the kind is for."""

    def __init__(self, tmp_path: Path, rid: str):
        self.home = make_env(tmp_path).ledger
        self.rid = _seed(self.home, rid)
        self.statement = statements.add(
            self.home, verbatim="Wait for the next release before deciding.",
            source={"message_ref": "transcript:covered#L3"}, recorded_by="human",
        )
        stage = tmp_path / "deferring-case.yaml"
        deferring = _case([self.rid], "defer", "defer")
        deferring["dependencies"] = {**_NO_DEPS, "statements": [self.statement]}
        _dump_yaml(stage, deferring)
        self.prior = cases.record(self.home, stage, actor="steward")
        verbs.defer(self.home, self.rid, by="steward", no_push=True)
        verbs.defer(self.home, self.rid, until=_today(), by="steward", no_push=True)
        _enable_steward(self.home)


def test_a_reconsider_case_naming_a_real_predecessor_still_passes_and_applies(
    tmp_path, monkeypatch
):
    """The kind's own use is untouched: a `kind: reconsider` case whose
    `supersedes` names the applied, unsuperseded case that deferred the
    lesson is not flagged, spends no repair turn, records as the
    predecessor's successor and applies. The card line is absent: the
    lesson IS covered (control first: the lesson is selected)."""
    covered = Covered(tmp_path, "lrn-d0f00003")
    home, rid = covered.home, covered.rid
    assert rid in {entry.record.id for entry, _row in steward._eligible_lessons(home)}
    _notifications(monkeypatch)
    prompts: list[str] = []
    case = _reject_case(rid, kind="reconsider", supersedes=covered.prior)
    monkeypatch.setattr(steward.invocation, "write_session", _session(rid, case, case, prompts))

    result = steward.run(home)

    brief = _brief_of(prompts[0], rid)
    assert "[lesson]" in brief and "status deferred" in brief  # positive control: the card
    assert _CARD_LINE not in brief
    assert len(prompts) == 1, "no repair turn"
    assert _status(home, rid) == "rejected"
    assert _packet(home, result.run_id)["dispositions"][rid]["state"] == "applied"
    (prior,) = [row for row in cases.list_cases(home) if row["case"] == covered.prior]
    (successor,) = [row for row in cases.list_cases(home, record_id=rid)
                    if row["case"] != covered.prior]
    assert successor["kind"] == "reconsider"
    assert successor["supersedes"] == covered.prior
    assert prior["superseded_by"] == successor["case"]


# ------------------------------------------- the check itself, directly


def _stage(stage: Path, rid: str, *, supersedes: str | None) -> Path:
    _dump_yaml(stage / "cases" / "again.yaml",
               _reject_case(rid, kind="reconsider", supersedes=supersedes))
    _dump_yaml(stage / "sheets" / "again.yaml",
               {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]})
    return stage


def test_covered_is_the_apply_time_predecessor_check_not_a_mention(tmp_path):
    """"Covers" is what apply time checks (`cases.require_reconsider_predecessor`)
    plus "not superseded already" (`cases.record` refuses a second
    successor) -- never "some case names this lesson". Control first: the
    real predecessor passes. Then each shape a mention-based test would
    take as covering is flagged, at the repair turn and on the card:

    * the predecessor case was superseded already;
    * the named case exists and names the lesson only in its text (it is
      about another lesson);
    * the named case does not exist."""
    covered = Covered(tmp_path / "a", "lrn-d0f00004")
    home, rid = covered.home, covered.rid
    selected = {rid: "deferred"}
    assert steward._ledger_repair_message(
        home, _stage(tmp_path / "ok", rid, supersedes=covered.prior), selected
    ) is None
    assert steward._deferred_unresolved(home, Record.from_path(
        ledger_ops.find_record_path(home, rid))) is None

    # supersede the prior case with a resolution case that does nothing to the lesson
    successor_stage = tmp_path / "successor.yaml"
    successor = _case([rid], "defer", "defer")
    successor["supersedes"] = covered.prior
    successor["question"] = f"does {rid} still wait for the release?"
    _dump_yaml(successor_stage, successor)
    newer = cases.record(home, successor_stage, actor="human")
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    # the lesson is named by two cases, but `newer` covers it: still no card line
    assert steward._deferred_unresolved(home, record) is None
    message = steward._ledger_repair_message(
        home, _stage(tmp_path / "superseded", rid, supersedes=covered.prior), selected
    )
    assert message is not None
    assert (
        f"record {rid}: this `kind: reconsider` case cannot supersede {covered.prior} for it "
        f"({covered.prior} is already superseded by {newer}); the case that covers it is {newer}"
    ) in message
    assert _NO_EARLIER_CASE not in message, "a case does cover it: the line names it"
    assert steward._ledger_repair_message(
        home, _stage(tmp_path / "newer", rid, supersedes=newer), selected
    ) is None

    other = _seed(home, "lrn-d0f0000f")
    mention_stage = tmp_path / "mention.yaml"
    mention = _case([other], "defer", "defer")
    mention["question"] = f"is {other} the same lesson as {rid}?"
    _dump_yaml(mention_stage, mention)
    about_other = cases.record(home, mention_stage, actor="human")
    message = steward._ledger_repair_message(
        home, _stage(tmp_path / "mention", rid, supersedes=about_other), selected
    )
    assert message is not None and f"{about_other} does not cover {rid}" in message
    assert f"the case that covers it is {newer}" in message

    message = steward._ledger_repair_message(
        home, _stage(tmp_path / "missing", rid, supersedes="case-0000aaaa"), selected
    )
    assert message is not None and "no such case case-0000aaaa" in message


def test_a_lesson_named_only_by_a_superseded_case_carries_the_card_line(tmp_path):
    """The card's "covers" is the repair turn's: a deferred lesson whose
    only case was superseded by a case about ANOTHER lesson is named by a
    case file, yet no case a reconsider could supersede covers it."""
    covered = Covered(tmp_path, "lrn-d0f00005")
    home, rid = covered.home, covered.rid
    record = Record.from_path(ledger_ops.find_record_path(home, rid))
    assert steward._deferred_unresolved(home, record) is None  # control: covered

    other = _seed(home, "lrn-d0f0000e")
    stage = tmp_path / "taking-over.yaml"
    taking_over = _case([other], "defer", "defer")
    taking_over["supersedes"] = covered.prior
    _dump_yaml(stage, taking_over)
    cases.record(home, stage, actor="human")
    assert [row["case"] for row in cases.list_cases(home, record_id=rid)] == [covered.prior]

    line = steward._deferred_unresolved(home, record)
    assert line is not None and line.startswith(_CARD_LINE)
    assert "`kind: resolution`" in line
    # the repair turn reads "covers" the same way: naming the superseded case
    # is refused, and the line says no earlier case covers the lesson
    message = steward._ledger_repair_message(
        home, _stage(tmp_path / "stage", rid, supersedes=covered.prior), {rid: "deferred"}
    )
    assert message is not None
    assert f"record {rid}: {_NO_EARLIER_CASE} -- this `kind: reconsider` case cannot supersede " \
        f"{covered.prior} for it ({covered.prior} is already superseded by " in message


def test_the_card_line_is_only_on_a_deferred_lesson(tmp_path):
    """A pending lesson with no case is decided with a resolution case
    anyway and its card says nothing new; a deferred one is told."""
    home = make_env(tmp_path).ledger
    pending = _seed(home, "lrn-d0f00006")
    deferred = _deferred_without_case(home, "lrn-d0f00007")
    rows = {entry.record.id: row for entry, row in steward._eligible_lessons(home)}
    assert set(rows) == {pending, deferred}  # control: both selected
    assert "reason" not in rows[pending]
    assert rows[deferred]["reason"].startswith(_CARD_LINE)


def test_a_reconsider_input_whose_predecessor_the_runner_fills_in_is_not_flagged(tmp_path):
    """`supersedes` left unset is not by itself the mistake: for a
    reconsider input the runner fills it in from the input's predecessor
    (`_predecessor_fill`) before the case is recorded, so the check reads
    the case as it will be recorded. Without the predecessor it is
    flagged, and the line names the case that covers the lesson."""
    covered = Covered(tmp_path, "lrn-d0f00008")
    home, rid = covered.home, covered.rid
    stage = _stage(tmp_path / "unset", rid, supersedes=None)
    selected = {rid: "deferred"}
    assert steward._ledger_repair_message(
        home, stage, selected, predecessors={rid: covered.prior}
    ) is None
    message = steward._ledger_repair_message(home, stage, selected)
    assert message is not None
    assert (
        f"record {rid}: this `kind: reconsider` case names no case in `supersedes`, and the "
        f"runner has none to fill in; the case that covers it is {covered.prior}"
    ) in message


# -------------------------------------------------- the brief and method


def test_the_brief_and_the_method_say_a_deferred_lesson_no_case_covers_takes_a_resolution_case():
    contract = " ".join(steward_prompt._render_output_contract().split())
    assert (
        "A reconsider case names that earlier case in `supersedes` (the runner fills it in "
        "for a reconsider input). A lesson deferred without a case (a bare `defer`) has no "
        "earlier case to name: it is decided with `resolution` too."
    ) in contract
    assert (
        "and an earlier case that covers it, named in `supersedes` (a pending lesson -- even "
        "one an earlier case moved -- and a deferred lesson no case covers take "
        "`kind: resolution`)"
    ) in contract
    method = " ".join(
        (worker.package_skill_refs() / "steward-method.md").read_text(encoding="utf-8").split()
    )
    assert (
        "A lesson deferred without a case — by a bare `defer` — has no earlier case to name, "
        "so it is decided with a `kind: resolution` case too"
    ) in method
    advice = " ".join(" ".join(steward._RECONSIDER_REPAIR_ADVICE).split())
    assert "names that case in `supersedes`" in advice
    assert "deferred without a case" in advice
