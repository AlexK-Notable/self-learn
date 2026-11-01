"""S-NEXT-steward (2026-11-01): the steward's one repair turn catches a
`confirm-held` line on a lesson that is not a placed (routed) rule, and its
brief says which status `confirm-held` needs.

Live run `run-14405f3da1fe` (2026-10-29): two rejected lessons
(`lrn-d7b10ea8`, `lrn-c46ed258`) came back as reconsider inputs. The model
kept each rejection in a `kind: reconsider` case, `outcome: no-action`,
with a `confirm-held` line -- a verb for a placed rule seen working. The
repair preview DID refuse that line ("record ... is 'rejected' -- only live
routed rules can be confirmed as holding"), but the repair turn dropped
every `status` refusal of a lesson a staged reconsider case covers, a rule
written when that preview could not see the reconsider widening (S-71,
2026-09-24). Since S-73 item 6 (2026-09-28) the preview applies the
widening itself, so the refusal was real: it reached apply time, the ledger
refused it, and both lessons were parked `ledger-refused` for the overseer
(`case-15867de9`, `case-1787c364`; overseer notice `ntc-46408944`).

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real ``~/.self-learn``) with fake model sessions that
write the stage files; the runner does the rest for real. No model call;
ids and texts are synthetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import batch, cases, ledger_ops, statements, steward, steward_prompt, verbs
from self_learn.invocation.contract import Outcome
from self_learn.records import Record
from support import make_env
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir
from test_steward_refusals import _REPAIR_HEADER, _case, _notifications, _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_LEDGER_REPAIR = "The ledger would refuse these lines of your sheets as written:"
_CONFIRM_REFUSAL = "only live routed rules can be confirmed as holding"


def _status(home: Path, rid: str) -> str:
    return Record.from_path(ledger_ops.find_record_path(home, rid)).status


class Rejected:
    """A lesson an earlier case REJECTED, whose case depends on a statement
    a later observation says changed: the steward's reconsider input."""

    def __init__(self, tmp_path: Path, rid: str, *, observed: bool = True):
        self.home = make_env(tmp_path).ledger
        self.rid = _seed(self.home, rid)
        self.statement = statements.add(
            self.home, verbatim="Nobody needs a standing line for this.",
            source={"message_ref": "transcript:rejected#L3"}, recorded_by="human",
        )
        stage = tmp_path / "rejecting-case.yaml"
        rejecting = _case([self.rid], "reject", "reject")
        rejecting["dependencies"]["statements"] = [self.statement]
        _dump_yaml(stage, rejecting)
        self.prior = cases.record(self.home, stage, actor="steward")
        verbs.reject(self.home, self.rid, by="steward", no_push=True)
        if observed:
            cases.observe(
                self.home, self.prior, "statement", text="re-observed",
                ref=self.statement, by="steward",
            )
        _enable_steward(self.home)


def _keep_case(rid: str, verb: str, supersedes: str | None = None) -> dict:
    case = _case([rid], "no-action", verb)
    case["kind"] = "reconsider"
    case["trigger"] = "reconsider"
    case["question"] = "a dependency of the rejection was re-observed; does it still hold?"
    case["decision"]["because"] = "nothing the rejection rested on has changed"
    if supersedes is not None:
        case["supersedes"] = supersedes
    return case


def _keep_line(rid: str, verb: str) -> dict:
    words = "the rejection holds; nothing it rested on changed"
    # `note` appends a line to the record (`append`); `confirm-held` takes a `note`
    return {"id": rid, "verb": verb, ("append" if verb == "note" else "note"): words}


def _stage(stage: Path, rid: str, verb: str, supersedes: str) -> Path:
    _dump_yaml(stage / "cases" / "keep.yaml", _keep_case(rid, verb, supersedes))
    _dump_yaml(stage / "sheets" / "keep.yaml",
               {"version": 1, "case": "$CASE_ID", "items": [_keep_line(rid, verb)]})
    return stage


# ------------------------------------------- the repair feed, directly


def test_a_confirm_held_on_a_rejected_lesson_under_a_reconsider_case_is_collected(tmp_path):
    """The live shape: a staged `kind: reconsider` case keeps a REJECTED
    lesson's rejection with a `confirm-held` line. Control first: the same
    case with a `note` line is clean (its predecessor is real, so nothing
    else is flagged). Then the `confirm-held` line is collected, in the
    ledger's own words, while the status is the one the run selected."""
    rejected = Rejected(tmp_path / "ledger", "lrn-c0de0001", observed=False)
    home, rid = rejected.home, rejected.rid
    selected = {rid: "rejected"}

    assert steward._ledger_repair_message(
        home, _stage(tmp_path / "note", rid, "note", rejected.prior), selected
    ) is None, "control: a note line keeps a rejection and the ledger takes it"

    message = steward._ledger_repair_message(
        home, _stage(tmp_path / "held", rid, "confirm-held", rejected.prior), selected
    )
    assert message is not None
    assert _LEDGER_REPAIR in message
    assert f"(confirm-held {rid})" in message
    assert "'rejected'" in message and _CONFIRM_REFUSAL in message
    # a lesson that moved on since selection is still left to apply time
    assert steward._ledger_repair_message(
        home, _stage(tmp_path / "moved", rid, "confirm-held", rejected.prior), {rid: "routed"}
    ) is None


def test_the_widened_preview_still_lets_a_reconsider_reject_a_routed_lesson(tmp_path):
    """What the dropped rule protected, still protected by the preview's
    own widening (S-73 item 6): a `reject` of a ROUTED lesson under a staged
    `kind: reconsider` case previews as apply time will run it with the
    real case, so no `status` refusal reaches the repair turn. Control: the
    same line under a `kind: resolution` case is a status refusal and is
    collected."""
    home = make_env(tmp_path / "ledger").ledger
    rid = _seed(home, "lrn-c0de0002")
    stage_path = tmp_path / "routing-case.yaml"
    _dump_yaml(stage_path, _case([rid], "route", "route"))
    prior = cases.record(home, stage_path, actor="steward")
    sheet = tmp_path / "route.yaml"
    sheet.write_text(
        f"version: 1\ncase: {prior}\nitems:\n  - id: {rid}\n    verb: route\n    dest: skill-md\n",
        encoding="utf-8",
    )
    assert batch.run(home, batch.load_sheet(sheet), no_push=True).items[0].state == "applied"
    selected = {rid: "routed"}

    def staged(name: str, kind: str) -> Path:
        stage = tmp_path / name
        case = _case([rid], "reject", "reject")
        case["kind"] = kind
        if kind == "reconsider":
            case["supersedes"] = prior
        _dump_yaml(stage / "cases" / "one.yaml", case)
        _dump_yaml(stage / "sheets" / "one.yaml",
                   {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]})
        return stage

    plain = steward._ledger_repair_message(home, staged("plain", "resolution"), selected)
    assert plain is not None and f"(reject {rid})" in plain and "'routed'" in plain
    assert steward._ledger_repair_message(home, staged("again", "reconsider"), selected) is None


# ------------------------------------------- end to end, the live chain


def _session(rid: str, prompts: list[str], first: str, repair: str):
    def write(spec):
        prompts.append(spec.prompt)
        verb = repair if _REPAIR_HEADER in spec.prompt else first
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / f"{rid}.yaml", _keep_case(rid, verb))
        _dump_yaml(stage / "sheets" / f"{rid}.yaml",
                   {"version": 1, "case": "$CASE_ID", "items": [_keep_line(rid, verb)]})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def test_a_rejection_kept_with_confirm_held_is_repaired_to_a_note_and_never_parked(
    tmp_path, monkeypatch
):
    """The live chain of run-14405f3da1fe: a rejected lesson returns as a
    reconsider input and the first session keeps the rejection with a
    `confirm-held` line. The repair turn names that line in the ledger's
    words; the repaired `note` line applies; the lesson stays rejected and
    no `ledger-refused` case is parked for the overseer."""
    rejected = Rejected(tmp_path, "lrn-c0de0003")
    home, rid = rejected.home, rejected.rid
    reconsider, _predecessors = steward._reconsider_proposals(home)
    assert rid in {entry.record.id for entry, _row in reconsider}, "control: a reconsider input"
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(
        steward.invocation, "write_session", _session(rid, prompts, "confirm-held", "note")
    )

    result = steward.run(home)

    assert len(prompts) == 2, "the repair turn is spent on the confirm-held line"
    repair = prompts[1].split(_REPAIR_HEADER, 1)[1]
    assert f"(confirm-held {rid})" in repair and _CONFIRM_REFUSAL in repair
    disposition = _head_manifest(home, result.run_id)["packets"][0]["dispositions"][rid]
    assert disposition["state"] == "applied", disposition
    assert _status(home, rid) == "rejected"
    rows = cases.list_cases(home, record_id=rid)
    assert not [row for row in rows if row.get("parked_reason") == "ledger-refused"], rows
    (successor,) = [row for row in rows if row["case"] != rejected.prior]
    assert successor["kind"] == "reconsider" and successor["supersedes"] == rejected.prior


# ------------------------------------------- the brief


def test_the_brief_says_confirm_held_needs_a_placed_rule_and_a_kept_rejection_takes_a_note():
    """The output contract's status table names `confirm-held` with the
    status its own check reads (`ledger_ops.ROUTED_ONLY`), and says a
    reconsider case that keeps a rejected or deferred lesson's decision
    writes a `note`."""
    text = steward_prompt._render_output_contract()
    table = text.split("WHAT EACH VERB NEEDS THE LESSON'S STATUS TO BE", 1)[1]
    flat = " ".join(table.split())
    held = f"confirm-held: {' | '.join(sorted(ledger_ops.ROUTED_ONLY))}"
    assert held in flat, flat[:600]
    assert "note: any status" in flat
    assert (
        "A `kind: reconsider` case that keeps a rejected or deferred lesson's decision "
        "(`outcome: no-action`) records why with a `note` line, never `confirm-held`"
    ) in flat
