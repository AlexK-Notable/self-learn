"""2026-10-07: two mistakes the steward's one repair turn never heard of.

1. A ``kind: reconsider`` case naming a PENDING lesson. Live run
   `run-9858d321b158`: two lessons an earlier steward case had moved were
   brought back by an observation on that case, still pending; the model
   wrote a ``kind: reconsider`` case for them, and `verbs.reconsider`
   refused it at apply time ("reconsider needs status
   deferred/routed/rejected"). Nothing had shown the model that mistake
   while it could fix it, and the refusal was recorded as a bare
   ``refused`` row with no kind and no case, outside every S-71 rule.
   Now the repair turn names it (the status a reconsider needs is known
   at selection time), and a refusal left after the repair carries its
   S-71 kind, so it is sent back, parked or retried like any other.

2. A ``[reopen X, <verb> X]`` pair hid EVERY refusal of its second line
   from the repair turn, not only the expected ``status`` one (the
   preview cannot see the reopen land). A ``bad-line`` there was never
   shown, and at apply the reopen landed alone. Gate-l10 probe P3.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real ``~/.self-learn``) with fake model sessions that
write the stage files; the runner does the rest for real. No real model
call; ids and texts are synthetic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from self_learn import batch, cases, ledger_ops, statements, steward, steward_prompt, verbs, worker
from self_learn.invocation.contract import Outcome
from self_learn.records import Record
from support import make_env
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir
from test_steward_refusals import _REPAIR_HEADER, _case, _notifications, _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_NO_DEPS = {"statements": [], "user_model": [], "conditions": [], "capabilities": []}


def _status(home: Path, rid: str) -> str:
    return Record.from_path(ledger_ops.find_record_path(home, rid)).status


def _repair_part(prompt: str) -> str:
    assert _REPAIR_HEADER in prompt
    return prompt.split(_REPAIR_HEADER, 1)[1]


def _ids(prompt: str) -> list[str]:
    return re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", prompt, re.M)


def _packet(home: Path, run_id: str | None) -> dict:
    assert run_id is not None
    return _head_manifest(home, run_id)["packets"][0]


# ------------------------------------------- 1. the live shape, set up


class MovedPair:
    """Two pending lessons an earlier STEWARD case moved (`rehome` to the
    user scope): the live `case-1f29abaf` shape. With ``observed`` the
    case's dependency changes afterwards, so the next run brings both back
    as RECONSIDER inputs (`observation:<id>` versions) -- what happened in
    `run-9858d321b158`; without it they come as ordinary LESSON inputs,
    the shape the next night offers them in."""

    def __init__(self, tmp_path: Path, *, observed: bool, prefix: str = "lrn-c1d0"):
        self.home = make_env(tmp_path).ledger
        self.ids = [_seed(self.home, f"{prefix}{n:04x}") for n in (1, 2)]
        self.statement = statements.add(
            self.home, verbatim="Keep these near the code they describe.",
            source={"message_ref": "transcript:moved-pair#L7"}, recorded_by="human",
        )
        stage = tmp_path / "moving-case.yaml"
        _dump_yaml(stage, {
            "kind": "resolution", "trigger": "nightly", "outcome": "rehome",
            "records": list(self.ids), "scope": "skill:s",
            "question": "do these two lessons belong to the user rather than this skill?",
            "evidence": [{"ref": self.statement, "quote": "near the code"}],
            "decision": {"verb": "rehome", "because": "the user's words", "confidence": "settled"},
            "dependencies": {**_NO_DEPS, "statements": [self.statement]},
        })
        self.moving_case = cases.record(self.home, stage, actor="steward")
        for rid in self.ids:
            verbs.rehome(self.home, rid, to="user", by="steward", no_push=True)
        if observed:
            cases.observe(self.home, self.moving_case, "statement",
                          text="the user said more", ref=self.statement, by="steward")
        _enable_steward(self.home)


def _decide_pair(pair: MovedPair, *, kind: str, verb: str = "reject") -> dict:
    """The case the model writes for the pair: one decision covering both."""
    case = _case(list(pair.ids), verb, verb, scope="user")
    case["kind"] = kind
    case["question"] = "the user said more about these two moved lessons; decide them again?"
    case["evidence"] = [{"ref": pair.statement, "quote": "near the code"}]
    case["dependencies"] = {**_NO_DEPS, "statements": [pair.statement]}
    if kind == "reconsider":
        # what the live model wrote: a successor of the case that moved them
        case["trigger"] = "reconsider"
        case["supersedes"] = pair.moving_case
    return case


def _pair_session(pair: MovedPair, first_kind: str, repair_kind: str, prompts: list[str]):
    def write(spec):
        prompts.append(spec.prompt)
        repair = _REPAIR_HEADER in spec.prompt
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / "moved-pair.yaml",
                   _decide_pair(pair, kind=repair_kind if repair else first_kind))
        _dump_yaml(stage / "sheets" / "moved-pair.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "reject"} for rid in pair.ids],
        })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


# --------------------------------- 1.1 the repair turn catches the mistake


@pytest.mark.parametrize("observed", [True, False], ids=["reconsider-inputs", "lesson-inputs"])
def test_a_reconsider_case_naming_pending_lessons_reaches_the_repair_turn(
    tmp_path, monkeypatch, observed
):
    """The live shape. The first pass writes a ``kind: reconsider`` case
    for two pending lessons; its format is fine, so before this change the
    repair turn was never offered and apply time refused the case. Now the
    repair turn names the case and both lessons with the ledger's words
    and says what to write instead; the repaired ``kind: resolution`` case
    applies and both lessons are decided in the same run."""
    pair = MovedPair(tmp_path, observed=observed)
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session",
                        _pair_session(pair, "reconsider", "resolution", prompts))

    result = steward.run(pair.home)

    # positive controls: the inputs are the shape this test is about
    inputs = {row["record"]: row for row in _packet(pair.home, result.run_id)["inputs"]}
    assert set(inputs) == set(pair.ids)
    expected_kind = "reconsider" if observed else "lesson"
    assert {row["kind"] for row in inputs.values()} == {expected_kind}
    assert {row["record_status"] for row in inputs.values()} == {"pending"}
    assert sorted(_ids(prompts[0])) == sorted(pair.ids)

    assert len(prompts) == 2, "the repair turn was offered"
    repair = _repair_part(prompts[1])
    for rid in pair.ids:
        assert (
            f"- cases/moved-pair.yaml: record {rid} is 'pending' — reconsider needs status"
            in repair
        ), repair
    assert "kind: resolution" in repair
    assert sorted(result.decided) == sorted(pair.ids)
    assert {_status(pair.home, rid) for rid in pair.ids} == {"rejected"}
    rows = _packet(pair.home, result.run_id)["dispositions"]
    assert {rows[rid]["state"] for rid in pair.ids} == {"applied"}
    decided_by = [row for row in cases.list_cases(pair.home, record_id=pair.ids[0])
                  if row["case"] != pair.moving_case]
    assert [row["kind"] for row in decided_by] == ["resolution"]


def _reconsider_stage(stage: Path, rid: str) -> None:
    case = _case([rid], "reject", "reject")
    case.update(kind="reconsider", trigger="reconsider", supersedes="case-0000aaaa")
    _dump_yaml(stage / "cases" / "again.yaml", case)
    _dump_yaml(stage / "sheets" / "again.yaml",
               {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]})


def test_the_check_flags_only_a_lesson_a_reconsider_cannot_take(tmp_path):
    """The repair feed's new check, directly. A ``kind: reconsider`` case
    over a lesson an earlier case PLACED is what the kind is for: nothing
    is said. The same case over a lesson selected PENDING is flagged, with
    the verb's own words. A lesson that moved on since selection (rejected
    then, reopened to pending by a person since) is left to apply time, as
    every `status` refusal of a lesson that moved on is."""
    home = make_env(tmp_path).ledger
    placed = _seed(home, "lrn-c1d00009")
    verbs.route(home, placed, dest="skill-md", by="steward", no_push=True)
    pending = _seed(home, "lrn-c1d0000a")
    assert (_status(home, placed), _status(home, pending)) == ("routed", "pending")  # control
    _reconsider_stage(tmp_path / "placed", placed)
    _reconsider_stage(tmp_path / "pending", pending)

    assert steward._ledger_repair_message(home, tmp_path / "placed", {placed: "routed"}) is None
    message = steward._ledger_repair_message(home, tmp_path / "pending", {pending: "pending"})
    assert message is not None
    assert f"- cases/again.yaml: record {pending} is 'pending' — reconsider needs status" in message
    # moved on: selected rejected, pending by the time the preview runs
    assert steward._ledger_repair_message(home, tmp_path / "pending", {pending: "rejected"}) is None


def test_the_brief_and_the_method_say_a_pending_lesson_takes_a_resolution_case():
    """1.3: the output contract and the method say which kind of case
    decides a pending lesson, with the statuses the reconsider verb itself
    takes (`ledger_ops.RECONSIDERABLE_STATUSES`)."""
    contract = steward_prompt._render_output_contract()
    statuses = " | ".join(sorted(ledger_ops.RECONSIDERABLE_STATUSES))
    assert f"every lesson a `kind: reconsider` case names:  {statuses}" in contract
    flat = " ".join(contract.split())
    assert (
        "`reconsider` is only for a lesson an earlier case placed, rejected or deferred "
        f"(its status is {statuses}). A lesson that is pending is decided with `resolution`, "
        "even one an earlier case moved"
    ) in flat
    method = " ".join(
        (worker.package_skill_refs() / "steward-method.md").read_text(encoding="utf-8").split()
    )
    assert (
        "A lesson that is pending is decided with a `kind: resolution` case, even when an "
        "earlier case moved it"
    ) in method


# ------------------------------------------- 1.2 a refusal carries a kind


@pytest.mark.parametrize(
    "observed, state",
    [(False, "returned"), (True, "abandoned")],
    ids=["lesson-inputs-sent-back", "reconsider-inputs-parked-now"],
)
def test_a_reconsider_refusal_left_after_the_repair_carries_its_kind(
    tmp_path, monkeypatch, observed, state
):
    """The model insists: its repair writes the same ``kind: reconsider``
    case. Apply time still refuses it -- and the refusal is no longer a bare
    ``refused`` row. It carries kind ``status`` (resolved to the steward's
    own line: the lessons did not move since selection) and the case, so
    S-71 §4.2 applies: a lesson input is sent back to the next run, which
    selects it again; a reconsider input, which is never selected again
    under its observation, is parked now for the overseer."""
    pair = MovedPair(tmp_path, observed=observed, prefix="lrn-c2d0")
    sent = _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session",
                        _pair_session(pair, "reconsider", "reconsider", prompts))

    result = steward.run(pair.home)

    rows = _packet(pair.home, result.run_id)["dispositions"]
    case_id = next(iter(_packet(pair.home, result.run_id)["case_ids"]))
    for rid in pair.ids:
        row = rows[rid]
        # positive control: the reconsider case reached apply and was refused
        assert "reconsider needs status" in str(row.get("reason")), row
        assert row["state"] == state, row
        assert row["kind"] == "status", row
        assert row["case"] == case_id, row
        assert _status(pair.home, rid) == "pending"
    assert result.decided == []
    assert len(prompts) == 2, "the repair turn was offered (and the model kept its case)"
    selected_again = {entry.record.id for entry, _row in steward._eligible_lessons(pair.home)}
    if observed:
        for rid in pair.ids:
            assert rows[rid]["successor_case"], rows[rid]
            (parked,) = cases.list_cases(pair.home, record_id=rid, parked_for="overseer",
                                         parked_reason="ledger-refused")
            assert parked["case"] == rows[rid]["successor_case"]
        assert sent, "the user is told about a park-now"
    else:
        assert set(pair.ids) <= selected_again, "a lesson sent back is decided again"
        assert not cases.list_cases(pair.home, record_id=pair.ids[0], parked_for="overseer")


def test_a_reconsider_refusal_of_another_shape_carries_its_kind_too(tmp_path, monkeypatch):
    """The same apply-time branch refuses a reconsider case whose outcome
    does not fit the lesson (audit finding 10's shape: `rehome` on a
    rejected lesson). Its raise site names no refusal type, so its kind is
    ``unclassified`` -- parked now for the overseer, never a bare row."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c3d00001")
    statement = statements.add(home, verbatim="The answer changed.",
                               source={"message_ref": "transcript:f10#L7"}, recorded_by="human")
    deps = {**_NO_DEPS, "statements": [statement]}
    stage = tmp_path / "rejecting-case.yaml"
    rejecting = _case([rid], "reject", "reject")
    rejecting.update(trigger="human", dependencies=deps)
    _dump_yaml(stage, rejecting)
    prior = cases.record(home, stage, actor="human")
    verbs.reject(home, rid, by="human", no_push=True)
    cases.observe(home, prior, "statement", text="the answer changed", ref=statement, by="steward")
    _enable_steward(home)
    _notifications(monkeypatch)

    def write(spec):
        out = _stage_dir(spec)
        case = _case([rid], "rehome", "rehome")
        case.update(kind="reconsider", trigger="reconsider", dependencies=deps)
        _dump_yaml(out / "cases" / f"{rid}.yaml", case)
        _dump_yaml(out / "sheets" / f"{rid}.yaml", {
            "version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "rehome", "to": "user"}],
        })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", write)

    result = steward.run(home)

    row = _packet(home, result.run_id)["dispositions"][rid]
    assert "does not apply to a 'rejected' record" in row["reason"]  # positive control
    assert row["kind"] == "unclassified", row
    assert row["state"] == "abandoned" and row["successor_case"], row
    assert row["case"] in _packet(home, result.run_id)["case_ids"]
    assert _status(home, rid) == "rejected"


# ------------------------------------- 2. a reopen pair hides no bad line


def _rejected(home: Path, rid: str) -> str:
    _seed(home, rid)
    verbs.reject(home, rid, by="human", no_push=True)
    assert _status(home, rid) == "rejected"  # control
    return rid


def _reopen_pair_stage(stage: Path, rid: str, dest: str) -> list[dict]:
    items = [{"id": rid, "verb": "reopen"}, {"id": rid, "verb": "route", "dest": dest}]
    _dump_yaml(stage / "cases" / "again.yaml", _case([rid], "route", "route"))
    _dump_yaml(stage / "sheets" / "again.yaml", {"version": 1, "case": "$CASE_ID", "items": items})
    return items


def _sheet(tmp_path: Path, items: list[dict]) -> batch.Sheet:
    path = tmp_path / "pair-sheet.yaml"
    _dump_yaml(path, {"version": 1, "items": items})
    return batch.load_sheet(path)


def _pair_verdicts(tmp_path: Path, rid: str, dest: str):
    base = tmp_path / dest.replace(":", "-")
    home = make_env(base).ledger
    _rejected(home, rid)
    stage = base / "stage"
    items = _reopen_pair_stage(stage, rid, dest)
    sheet = _sheet(base, items)
    preview = batch.dry_run(home, sheet, actor="steward")
    assert [item.state for item in preview.items] == ["would-apply", "would-refuse"]  # control
    return (
        preview.items[1].kind,
        steward._ledger_repair_message(home, stage, {rid: "rejected"}),
        steward._held_refusals(preview, sheet),
        steward._preview_is_clean_for_sequence(preview, sheet),
    )


def test_only_the_expected_status_refusal_after_a_reopen_is_excused(tmp_path):
    """Gate-l10 probe P3. In ``[reopen X, route X]`` the preview cannot see
    the reopen land, so the route previews against the REJECTED lesson
    and is refused ``status`` -- expected, and still excused (the control,
    a good destination). A ``bad-line`` on that line (a destination
    qualifier that does not exist) is the model's own mistake: it reaches
    the repair turn, and at apply time the case is held rather than
    letting the reopen land alone."""
    rid = "lrn-c4d00001"
    kind, message, held, clean = _pair_verdicts(tmp_path, rid, "skill-md")
    assert kind == "status"  # control: the expected refusal, and only it
    assert (message, held, clean) == (None, [], True)

    kind, message, held, clean = _pair_verdicts(tmp_path, rid, "claude-md:bogus")
    assert kind == "bad-line"  # control: the preview carries the line's own kind
    assert message is not None and f"- sheets/again.yaml: item 2 (route {rid}): " in message
    assert "not recognized" in message
    assert [(row["n"], row["kind"]) for row in held] == [(2, "bad-line")]
    assert clean is False


def _rejected_and_observed(tmp_path: Path, rid: str) -> tuple[Path, str]:
    """A rejected lesson whose rejecting case's dependency then changed,
    so the steward is handed it as a reconsider input."""
    home = make_env(tmp_path).ledger
    _seed(home, rid)
    statement = statements.add(home, verbatim="Route it after all.",
                               source={"message_ref": "transcript:p3#L7"}, recorded_by="human")
    stage = tmp_path / "rejecting-case.yaml"
    rejecting = _case([rid], "reject", "reject")
    rejecting.update(trigger="human", dependencies={**_NO_DEPS, "statements": [statement]})
    _dump_yaml(stage, rejecting)
    prior = cases.record(home, stage, actor="human")
    verbs.reject(home, rid, by="human", no_push=True)
    cases.observe(home, prior, "statement", text="route it after all", ref=statement, by="steward")
    _enable_steward(home)
    return home, statement


def _reopen_session(rid: str, statement: str, first: str, repair: str, prompts: list[str]):
    def write(spec):
        prompts.append(spec.prompt)
        dest = repair if _REPAIR_HEADER in spec.prompt else first
        out = _stage_dir(spec)
        case = _case([rid], "route", "route")
        case.update(kind="reconsider", trigger="reconsider",
                    dependencies={**_NO_DEPS, "statements": [statement]})
        _dump_yaml(out / "cases" / f"{rid}.yaml", case)
        _dump_yaml(out / "sheets" / f"{rid}.yaml", {"version": 1, "case": "$CASE_ID", "items": [
            {"id": rid, "verb": "reopen"}, {"id": rid, "verb": "route", "dest": dest},
        ]})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def _reopen_run(tmp_path: Path, monkeypatch, rid: str, first: str, repair: str):
    home, statement = _rejected_and_observed(tmp_path / rid, rid)
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session",
                        _reopen_session(rid, statement, first, repair, prompts))
    result = steward.run(home)
    inputs = _packet(home, result.run_id)["inputs"]
    assert [(row["kind"], row["record_status"]) for row in inputs] == [("reconsider", "rejected")]
    return home, result, prompts


def test_a_reopen_pair_with_a_bad_second_line_is_repaired_in_the_same_run(tmp_path, monkeypatch):
    """End to end. A rejected lesson comes back as a reconsider input; the
    model writes ``[reopen, route]``. The control pair (a good destination,
    whose route previews only the expected ``status`` refusal) spends no
    repair turn and applies. The bad pair names a destination qualifier
    that does not exist: before, no repair turn, and at apply the reopen
    landed alone -- the lesson went back to pending without its
    re-decision. Now the repair turn names the line, and the fixed pair
    applies."""
    home, result, prompts = _reopen_run(tmp_path, monkeypatch, "lrn-c5d00001",
                                        "skill-md", "skill-md")
    assert len(prompts) == 1  # control: no repair turn spent on the clean pair
    assert result.decided == ["lrn-c5d00001"] and _status(home, "lrn-c5d00001") == "routed"

    rid = "lrn-c5d00003"
    home, result, prompts = _reopen_run(tmp_path, monkeypatch, rid, "claude-md:bogus", "skill-md")
    assert _status(home, rid) == "routed", "the repaired pair applied"
    assert result.decided == [rid]
    assert len(prompts) == 2
    assert f"- sheets/{rid}.yaml: item 2 (route {rid}): " in _repair_part(prompts[1])


def test_a_reopen_pair_whose_second_line_stays_bad_does_not_reopen_alone(tmp_path, monkeypatch):
    """The model insists on the bad destination in its repair. Apply time
    holds the whole case, as the repair preview did: the lesson is not
    reopened without its re-decision (before, it went back to pending and
    the route was refused)."""
    rid = "lrn-c5d00002"
    home, statement = _rejected_and_observed(tmp_path, rid)
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session",
                        _reopen_session(rid, statement, "claude-md:bogus", "claude-md:bogus", prompts))

    result = steward.run(home)

    row = _packet(home, result.run_id)["dispositions"][rid]
    assert "not recognized" in str(row.get("reason")), row  # positive control
    assert _status(home, rid) == "rejected", "the reopen did not land alone"
    assert row["kind"] == "bad-line", row
    assert len(prompts) == 2, "the line reached the repair turn"
