"""S-71 §4: what the steward does with a line the ledger refused, by the
refusal's kind.

Every scenario is a full `steward.run` against a sandbox ledger
(`support.make_env` under pytest's tmpdir, never the real `~/.self-learn`),
with the fake session writer the other steward tests use: the "model" writes
its stage files, the runner does the rest for real. Where a verb is
monkeypatched to refuse, that is said at the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from self_learn import (
    batch, cases, execution_evidence, gitops, ledger_ops, steward, steward_prompt, verbs,
)
from self_learn.hosts import MARKER_FILENAME, host_add
from self_learn.invocation.contract import Outcome
from self_learn.ledger_ops import create_record
from self_learn.overseer import notify as overseer_notify
from support import (
    commit_all,
    git,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
)
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


# --------------------------------------------------------------- helpers


def _seed(home: Path, rid: str, *, record=None, scope: str = "skill:s",
          project_path: Path | None = None) -> str:
    create_record(
        home, record if record is not None else make_behavior(record_id=rid, scope=scope),
        project_path=project_path,
    )
    fields = {"destination": "claude-md"} if scope == "project" else {}
    ledger_ops.write_proposal(home, rid, proposal_dict(scope=scope, **fields))
    ledger_ops.stamp_proposal(home, rid)
    commit_all(home, f"seed {rid}")
    return rid


def _case(records: list[str], outcome: str, verb: str, scope: str = "skill:s") -> dict:
    return {
        "kind": "resolution",
        "trigger": "nightly",
        "outcome": outcome,
        "records": records,
        "scope": scope,
        "question": "what should become of this pending lesson?",
        "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
        "decision": {
            "verb": verb,
            "because": "the evidence settles it",
            "confidence": "settled",
        },
        "dependencies": {
            "statements": [], "user_model": [], "conditions": [], "capabilities": [],
        },
    }


_REPAIR_HEADER = "=== repair ==="


def _writer(groups, *, before=None, calls=None, prompts=None):
    """A fake session. `groups(ids)` returns `(name, records, items,
    outcome, verb)` tuples, one case/sheet pair each; `before(ids)` runs
    first, between the run's selection and its apply (a person acting on
    the ledger while the steward decides). A REPAIR session (the prompt
    carries the repair section) writes the same files again -- the model
    insisting on its lines -- and does not act as the person again.
    `calls` gets the lesson ids of each decision session; `prompts` gets
    every session's prompt, repair sessions included."""

    def write(spec):
        ids = re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M)
        repair = _REPAIR_HEADER in spec.prompt
        if prompts is not None:
            prompts.append(spec.prompt)
        if calls is not None and not repair:
            calls.append(list(ids))
        if before is not None and not repair:
            before(ids)
        stage = _stage_dir(spec)
        for name, records, items, outcome, verb in groups(ids):
            _dump_yaml(stage / "cases" / f"{name}.yaml", _case(records, outcome, verb))
            _dump_yaml(
                stage / "sheets" / f"{name}.yaml",
                {"version": 1, "case": "$CASE_ID", "items": items},
            )
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def _one_line_each(verb: str, outcome: str, **fields):
    return lambda ids: [
        (rid, [rid], [{"id": rid, "verb": verb, **fields}], outcome, verb) for rid in ids
    ]


def _notifications(monkeypatch) -> list:
    sent: list = []
    monkeypatch.setattr(
        overseer_notify, "send",
        lambda home_, cue, summary, ids: sent.append((cue, summary, list(ids))),
    )
    return sent


def _dispositions(home: Path, run_id: str | None) -> dict:
    assert run_id is not None
    return _head_manifest(home, run_id)["packets"][0]["dispositions"]


def _parked_now_cases(home: Path, rid: str) -> list[dict]:
    return cases.list_cases(
        home, record_id=rid, parked_for="overseer", parked_reason="ledger-refused"
    )


def _all_parked_for(home: Path, rid: str) -> list[dict]:
    return cases.list_cases(home, record_id=rid, parked_for="overseer")


# ----------------------------------------------------------- overtaken


def test_a_lesson_decided_by_hand_between_selection_and_apply_is_overtaken(
    tmp_path, monkeypatch
):
    """A person rejects the lesson while the steward is deciding to defer
    it. At apply time the steward's `defer` meets a lesson that is no
    longer pending: the lesson moved on, there is nothing left to decide. Closed
    as `overtaken` -- no successor case, no notification -- and the run
    completes."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b0000001")
    _enable_steward(home)
    sent = _notifications(monkeypatch)

    def by_hand(ids):
        verbs.reject(home, rid, no_push=True)

    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("defer", "defer", until="2099-01-01"), before=by_hand),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "overtaken", row
    assert row["reason"] == "record is now rejected"
    assert row["kind"] == "status"
    assert row["case"] and row["input_version"]
    # positive control: the run really ran to its end
    assert _head_manifest(home, result.run_id)["status"] == "complete"
    assert result.unfinished == [] and result.abandoned == []
    assert _all_parked_for(home, rid) == []
    assert sent == []


def test_a_status_refusal_the_steward_own_earlier_line_caused_is_not_overtaken(
    tmp_path, monkeypatch
):
    """A `reject` line, then a `defer` line for the same lesson: the first
    applies, the second finds it rejected. The status moved -- but by the
    steward's own line, so this is the steward's mistake (sent back), never
    `overtaken`."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b0000002")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            (rid, [rid],
             [{"id": rid, "verb": "reject"}, {"id": rid, "verb": "defer", "until": "2099-01-01"}],
             "reject", "reject"),
        ]),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    # positive control: the first line really applied
    assert ledger_ops.find_record_path(home, rid).parent.name == "resolved"
    assert row["state"] == "returned", row
    assert row["kind"] == "status"


def test_a_status_an_earlier_case_of_the_packet_moved_is_the_steward_own_doing(
    tmp_path, monkeypatch
):
    """The first case's sheet also rejects the second case's lesson; the
    second case's own `defer` then finds it rejected. An earlier case of
    the same packet moved it, so it is the steward's mistake (sent back),
    never `overtaken`."""
    env = make_env(tmp_path)
    home = env.ledger
    first = _seed(home, "lrn-b0000003")
    second = _seed(home, "lrn-b0000004")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            ("a-first", [first],
             [{"id": first, "verb": "reject"}, {"id": second, "verb": "reject"}],
             "reject", "reject"),
            ("b-second", [second], [{"id": second, "verb": "defer", "until": "2099-01-01"}],
             "defer", "defer"),
        ]),
    )

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[first]["state"] == "applied"
    assert rows[second]["state"] == "returned", rows[second]
    assert rows[second]["kind"] == "status"


# -------------------------------------------------- own mistake: returned


def test_an_own_mistake_is_sent_back_once_then_parked_ledger_refused(
    tmp_path, monkeypatch
):
    """`undefer` on a pending lesson: the lesson's status is the one it was
    selected with, so the line is the steward's own mistake. The repair turn
    shows it to the model (§5), which writes the same line again. Run 1 then
    sends it back (`returned`); run 2 selects it again WITH a model call and
    a brief naming what the ledger said (§4.6); the same input version
    refused a second time is parked `ledger-refused` at once, with one
    notification."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b0000005")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    calls: list = []
    prompts: list = []
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("undefer", "defer"), calls=calls, prompts=prompts),
    )

    first = steward.run(home)

    assert len(prompts) == 2 and _REPAIR_HEADER in prompts[1], "one repair turn"
    repair = prompts[1].split(_REPAIR_HEADER, 1)[1]
    assert "The ledger would refuse these lines of your sheets as written:" in repair
    assert f"- sheets/{rid}.yaml: item 1 (undefer {rid}): " in repair
    assert "'pending'" in repair
    # The block, not its title: steward-method.md §12 (in every brief's method
    # block) names the title so the model knows what the block is.
    assert "=== sent_back ===" not in prompts[0], "nothing was sent back yet"
    assert "=== open_cases ===" in prompts[0], "positive control: the brief rendered"
    row = _dispositions(home, first.run_id)[rid]
    assert row["state"] == "returned", row
    assert row["kind"] == "status"
    assert f"undefer {rid}:" in row["reason"] and "'pending'" in row["reason"]
    assert _head_manifest(home, first.run_id)["status"] == "complete"
    assert first.unfinished == [] and first.abandoned == []
    # a lesson sent back is a refusal the run reports, never "applied"
    assert first.status == "refused" and first.refused == 1
    assert _all_parked_for(home, rid) == []
    assert sent == []

    second = steward.run(home)

    assert second.run_id != first.run_id
    assert calls == [[rid], [rid]], "the next run decided the lesson again"
    brief = prompts[2]
    assert _REPAIR_HEADER not in brief
    sent_back = brief.split("=== sent_back ===", 1)[1].split("=== open_cases ===", 1)[0]
    assert sent_back.lstrip().startswith(steward_prompt.SENT_BACK_TITLE)
    assert f"- {rid} (earlier case {row['case']}):" in sent_back
    assert f"the ledger said: {row['reason']}" in sent_back
    assert sent_back.rstrip().endswith(steward_prompt.SENT_BACK_INSTRUCTION)
    again = _dispositions(home, second.run_id)[rid]
    assert again["state"] == "abandoned", again
    assert again["kind"] == "status"
    rows = _parked_now_cases(home, rid)
    assert len(rows) == 1 and again["successor_case"] == rows[0]["case"]
    view = cases.show(home, rows[0]["case"], evidence_only=False)
    assert "the ledger refused the decision's line" in view.sections["Identity and scope"]
    evidence = view.sections["Evidence"]
    assert f"undefer {rid}:" in evidence
    # the evidence reference points at a span that really holds the words
    ref = re.search(r"ledger@([0-9a-f]{40}):(cases/runs/\S+\.json)#L(\d+)-(\d+)", evidence)
    assert ref is not None
    sha, path, a, b = ref.groups()
    quoted = git(home, "show", f"{sha}:{path}").stdout.splitlines()[int(a) - 1 : int(b)]
    assert any(f"undefer {rid}:" in line for line in quoted)
    assert len(sent) == 1
    cue, summary, ids = sent[0]
    assert cue == "routine" and ids == [rid]
    assert "1 lesson(s) parked for the overseer" in summary
    assert "the ledger refused a line a person must fix (status)" in summary
    # the steward's own case names its successor, and says why
    own = cases.show(home, again["case"], evidence_only=False)
    later = own.sections.get("Later observations", "")
    assert rows[0]["case"] in later
    assert f"the ledger refused this case's line for {rid} (status)" in later

    assert steward.run(home).status == "idle", "a parked lesson is not decided again"


# ------------------------------------------- destination-unavailable


def test_a_destination_this_machine_cannot_take_is_sent_back(tmp_path, monkeypatch):
    """The steward routes to the skill's SKILL.md; the skill has none. Another
    destination might take the lesson, so it goes back to the steward."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b0000006")
    _enable_steward(home)
    sent = _notifications(monkeypatch)

    def lose_skill_md(ids):
        env.skill_md.unlink()
        commit_all(env.host, "the skill lost its SKILL.md")

    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("route", "route", dest="skill-md"), before=lose_skill_md),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "returned", row
    assert row["kind"] == "destination-unavailable"
    assert "no SKILL.md at" in row["reason"]
    assert _head_manifest(home, result.run_id)["status"] == "complete"
    assert _all_parked_for(home, rid) == [] and sent == []


# ------------------------------------------------------ needs-person


def test_a_host_only_a_person_can_fix_parks_the_lesson_in_the_same_run(
    tmp_path, monkeypatch
):
    """The plain host the lesson routes to lost its marker file. Neither a
    retry nor a fresh decision can fix that: parked `ledger-refused` in the
    same run, with a successor case and one notification; the run completes."""
    env = make_env(tmp_path)
    home = env.ledger
    plain = tmp_path / "plain-host"
    plain.mkdir()
    host_add(home, plain, "project", mode="plain")
    rid = _seed(
        home, "lrn-b0000007", scope="project",
        record=make_behavior(record_id="lrn-b0000007", scope="project"),
        project_path=plain,
    )
    _enable_steward(home)
    sent = _notifications(monkeypatch)

    def lose_marker(ids):
        (plain / MARKER_FILENAME).unlink()

    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("route", "route", dest="claude-md"), before=lose_marker),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "abandoned", row
    assert row["kind"] == "needs-person"
    assert MARKER_FILENAME in row["reason"]
    rows = _parked_now_cases(home, rid)
    assert len(rows) == 1 and row["successor_case"] == rows[0]["case"]
    assert result.abandoned == [rid]
    assert _head_manifest(home, result.run_id)["status"] == "complete"
    assert len(sent) == 1
    assert "the ledger refused a line a person must fix (needs-person)" in sent[0][1]
    assert sent[0][2] == [rid]


def test_a_park_now_that_cannot_write_its_case_is_retried_not_lost(
    tmp_path, monkeypatch
):
    """Two lessons of one case both need a person. Lesson A's successor case
    cannot be written tonight; lesson B's can. A stays `unfinished` and the
    case stays open, so the next run re-drives it and parks A; B, parked
    already, keeps its row and is not parked or told about twice.
    (`_close_out_record` is monkeypatched to fail for A in the first run.)"""
    env = make_env(tmp_path)
    home = env.ledger
    plain = tmp_path / "plain-host"
    plain.mkdir()
    host_add(home, plain, "project", mode="plain")
    a, b = (
        _seed(
            home, rid, scope="project",
            record=make_behavior(record_id=rid, scope="project"),
            project_path=plain,
        )
        for rid in ("lrn-b0000008", "lrn-b0000021")
    )
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(
            lambda ids: [(
                "both", [a, b],
                [{"id": a, "verb": "route", "dest": "claude-md"},
                 {"id": b, "verb": "route", "dest": "claude-md"}],
                "route", "route",
            )],
            before=lambda ids: (plain / MARKER_FILENAME).unlink(),
        ),
    )
    real_record = steward._close_out_record

    def cannot_write_a(home_, run_dir, run_id, packet, packet_index, record_id, **kwargs):
        if record_id == a:
            raise cases.CaseError("simulated: the successor case cannot be written")
        return real_record(home_, run_dir, run_id, packet, packet_index, record_id, **kwargs)

    monkeypatch.setattr(steward, "_close_out_record", cannot_write_a)

    first = steward.run(home)

    manifest = _head_manifest(home, first.run_id)
    rows = manifest["packets"][0]["dispositions"]
    assert rows[a]["state"] == "unfinished", rows[a]
    assert rows[a]["kind"] == "needs-person"
    assert rows[b]["state"] == "abandoned", rows[b]
    assert manifest["cases"][rows[a]["case"]]["phase"] == "unfinished"
    assert first.unfinished == [a]
    assert _all_parked_for(home, a) == []
    b_successor = rows[b]["successor_case"]
    assert [call[2] for call in sent] == [[b]]

    monkeypatch.setattr(steward, "_close_out_record", real_record)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        lambda spec: pytest.fail("a re-drive never asks the model again"),
    )
    second = steward.run(home)

    assert second.run_id == first.run_id
    rows = _dispositions(home, first.run_id)
    assert rows[a]["state"] == "abandoned" and rows[b]["state"] == "abandoned"
    assert rows[b]["successor_case"] == b_successor
    assert len(_parked_now_cases(home, a)) == 1 and len(_parked_now_cases(home, b)) == 1
    assert [call[2] for call in sent] == [[b], [a]], "each lesson told about once"
    assert _head_manifest(home, first.run_id)["status"] == "complete"


def test_a_lesson_already_parked_keeps_its_row_when_a_re_drive_cannot_write_its_receipt(
    tmp_path, monkeypatch
):
    """As above, lesson B is parked and lesson A's successor write failed.
    The re-drive's receipt write then fails too: nothing about A's line is
    final, so A is retried -- but B, parked already, keeps its row.
    (`_close_out_record` fails for A in run 1; `batch.write_receipt` fails
    in run 2.)"""
    env = make_env(tmp_path)
    home = env.ledger
    plain = tmp_path / "plain-host"
    plain.mkdir()
    host_add(home, plain, "project", mode="plain")
    a, b = (
        _seed(
            home, rid, scope="project",
            record=make_behavior(record_id=rid, scope="project"),
            project_path=plain,
        )
        for rid in ("lrn-b0000023", "lrn-b0000024")
    )
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(
            lambda ids: [(
                "both", [a, b],
                [{"id": a, "verb": "route", "dest": "claude-md"},
                 {"id": b, "verb": "route", "dest": "claude-md"}],
                "route", "route",
            )],
            before=lambda ids: (plain / MARKER_FILENAME).unlink(),
        ),
    )
    real_record = steward._close_out_record

    def cannot_write_a(home_, run_dir, run_id, packet, packet_index, record_id, **kwargs):
        if record_id == a:
            raise cases.CaseError("simulated: the successor case cannot be written")
        return real_record(home_, run_dir, run_id, packet, packet_index, record_id, **kwargs)

    monkeypatch.setattr(steward, "_close_out_record", cannot_write_a)
    first = steward.run(home)
    parked_b = _dispositions(home, first.run_id)[b]
    assert parked_b["state"] == "abandoned", "positive control: B was parked in run 1"

    monkeypatch.setattr(steward, "_close_out_record", real_record)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        lambda spec: pytest.fail("a re-drive never asks the model again"),
    )
    receipts: list[str] = []

    def failing_receipt(*args, **kwargs):
        receipts.append("failed")
        return {"state": "failed", "pushed": None}

    monkeypatch.setattr(steward.batch, "write_receipt", failing_receipt)
    steward.run(home)

    assert receipts, "positive control: the re-drive's receipt write failed"
    rows = _dispositions(home, first.run_id)
    assert rows[a]["state"] == "unfinished", rows[a]
    assert rows[b] == parked_b
    assert [call[2] for call in sent] == [[b]]


# ------------------------------------------------------ unclassified


def test_a_refusal_no_type_names_parks_the_lesson_at_once(tmp_path, monkeypatch):
    """`verbs.reject` is monkeypatched to refuse with a plain `VerbError` --
    a raise site S-71 names no kind for. That is `unclassified`, and it
    parks at once: it is never retried blindly, and never silent."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b0000009")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session", _writer(_one_line_each("reject", "reject"))
    )
    dispatched: list[str] = []

    def refuse(home_, record_id, **kwargs):
        dispatched.append(record_id)
        raise verbs.VerbError("simulated: a refusal no S-71 type names")

    monkeypatch.setattr(verbs, "reject", refuse)

    result = steward.run(home)

    assert dispatched == [rid], "positive control: the line was dispatched"
    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "abandoned", row
    assert row["kind"] == "unclassified"
    assert "simulated: a refusal no S-71 type names" in row["reason"]
    assert len(_parked_now_cases(home, rid)) == 1
    assert len(sent) == 1 and "(unclassified)" in sent[0][1]


# ----------------------------------------------------- secret-record


def test_a_secret_in_the_record_itself_is_refused_never_parked_or_retried(
    tmp_path, monkeypatch
):
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(
        home, "lrn-b000000a",
        record=make_knowledge(
            scope="skill:s", record_id="lrn-b000000a", fact="password = hunter2secret99",
        ),
    )
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    calls: list = []
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("reject", "reject"), calls=calls),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "refused", row
    assert row["kind"] == "secret-record"
    assert _head_manifest(home, result.run_id)["status"] == "complete"
    assert _all_parked_for(home, rid) == [] and sent == []
    assert steward.run(home).status == "idle", "refused is final: no retry, no new decision"
    assert len(calls) == 1


# ------------------------------------------------- one case, two lessons


def test_a_held_back_two_lesson_case_sends_both_lessons_back(tmp_path, monkeypatch):
    """One case decides two lessons; the preview says the ledger would
    refuse the second lesson's line. The case is one decision, so nothing
    is dispatched and BOTH lessons go back."""
    env = make_env(tmp_path)
    home = env.ledger
    a = _seed(home, "lrn-b000000b")
    b = _seed(home, "lrn-b000000c")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            ("both", [a, b],
             [{"id": a, "verb": "reject"}, {"id": b, "verb": "undefer"}],
             "reject", "reject"),
        ]),
    )

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[a]["state"] == "returned" and rows[b]["state"] == "returned", rows
    assert rows[a]["case"] == rows[b]["case"]
    # the lesson whose own line was fine carries the case's refusal
    assert f"undefer {b}:" in rows[a]["reason"]
    assert [row["id"] for row in ledger_ops.list_items(home)] == [a, b], "nothing dispatched"


def test_a_partly_applied_case_keeps_what_applied_and_parks_the_rest(
    tmp_path, monkeypatch
):
    """`verbs.defer` is monkeypatched to refuse with the typed `NeedsPerson`
    at dispatch (the preview passes). Lesson A's `reject` applied; lesson
    B's `defer` needs a person. A stays `applied`, B is parked now."""
    env = make_env(tmp_path)
    home = env.ledger
    a = _seed(home, "lrn-b000000d")
    b = _seed(home, "lrn-b000000e")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            ("both", [a, b],
             [{"id": a, "verb": "reject"}, {"id": b, "verb": "defer", "until": "2099-01-01"}],
             "reject", "reject"),
        ]),
    )

    def needs_a_person(home_, record_id, **kwargs):
        raise verbs.NeedsPerson("simulated: only a person can fix this")

    monkeypatch.setattr(verbs, "defer", needs_a_person)

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[a]["state"] == "applied", rows[a]
    assert rows[b]["state"] == "abandoned", rows[b]
    assert rows[b]["kind"] == "needs-person"
    assert result.decided == [a] and result.abandoned == [b]
    assert len(_parked_now_cases(home, b)) == 1
    assert _all_parked_for(home, a) == []
    assert len(sent) == 1 and sent[0][2] == [b]


# -------------------------------------------------------- eligibility


def _publish_row(home: Path, rid: str, state: str) -> None:
    """Commit a steward run record holding one disposition for `rid`'s
    CURRENT input version, the way a finished run would."""
    entry = next(e for bucket in steward.discover_buckets(home)
                 for e in ledger_ops.queue(bucket) if e.record.id == rid)
    identity = steward._input_identity(home, entry.proposal_path, rid, {"id": rid})
    run_id = "run-" + state.ljust(12, "0")[:12]
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": run_id,
        "started_at": "2026-09-23T00:00:00Z", "status": "complete",
        "packets": [{
            "index": 1, "inputs": [identity], "records": [rid],
            "dispositions": {rid: {
                "state": state, "input_version": identity["version"],
                "case": "case-0000beef",
            }},
        }],
    }, reason=f"a {state} row")
    assert execution_evidence.read_manifest(home, run_id, at="HEAD")["run_id"] == run_id


@pytest.mark.parametrize(
    ("state", "selected"),
    [("returned", True), ("overtaken", False), ("applied", False)],
)
def test_a_returned_lesson_is_selected_again_and_an_overtaken_one_is_not(
    state, selected, tmp_path
):
    """The lesson is still pending with the same input version in every
    row, so the queue alone would select it: only the disposition set
    decides. `returned` needs a new decision; `overtaken` needs none."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b000000f")
    other = _seed(home, "lrn-b0000010")
    before = [entry.record.id for entry, _ in steward._eligible_proposals(home)]
    assert before == [rid, other], "positive control: both are eligible first"

    _publish_row(home, rid, state)

    after = [entry.record.id for entry, _ in steward._eligible_proposals(home)]
    assert (rid in after) is selected
    assert other in after


# ------------------------------------------------ more of §4.2 and §4.4


def test_a_lesson_whose_record_is_gone_by_apply_time_is_overtaken(tmp_path, monkeypatch):
    """The record file is removed while the steward decides: record-not-found
    is kind `status`, and a lesson that no longer exists moved on."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b0000011")
    _enable_steward(home)
    sent = _notifications(monkeypatch)

    def remove(ids):
        path = ledger_ops.find_record_path(home, rid)
        git(home, "rm", "-q", str(path))
        git(home, "commit", "-q", "-m", f"remove {rid} by hand")

    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("defer", "defer", until="2099-01-01"), before=remove),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "overtaken", row
    assert row["reason"] == "record no longer exists"
    assert _head_manifest(home, result.run_id)["status"] == "complete"
    assert sent == []


def test_a_held_case_where_one_lesson_moved_on_closes_it_and_sends_the_other_back(
    tmp_path, monkeypatch
):
    """A two-lesson case, held back because a person rejected lesson A by
    hand. A moved on (`overtaken`); lesson B did not, and its decision was
    part of a case that could not run, so it goes back rather than being
    called overtaken."""
    env = make_env(tmp_path)
    home = env.ledger
    a = _seed(home, "lrn-b0000012")
    b = _seed(home, "lrn-b0000013")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(
            lambda ids: [(
                "both", [a, b],
                [{"id": a, "verb": "defer", "until": "2099-01-01"},
                 {"id": b, "verb": "defer", "until": "2099-01-01"}],
                "defer", "defer",
            )],
            before=lambda ids: verbs.reject(home, a, no_push=True),
        ),
    )

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[a]["state"] == "overtaken" and rows[a]["reason"] == "record is now rejected"
    assert rows[b]["state"] == "returned", rows[b]
    assert f"defer {a}:" in rows[b]["reason"]


def test_the_most_severe_action_of_a_held_case_wins_for_every_lesson(
    tmp_path, monkeypatch
):
    """One lesson's line needs a person (its host lost its marker), the
    other's is the steward's own mistake. Parking beats sending back, so
    BOTH lessons of the case are parked now, each with its own successor."""
    env = make_env(tmp_path)
    home = env.ledger
    plain = tmp_path / "plain-host"
    plain.mkdir()
    host_add(home, plain, "project", mode="plain")
    a = _seed(
        home, "lrn-b0000014", scope="project",
        record=make_behavior(record_id="lrn-b0000014", scope="project"),
        project_path=plain,
    )
    b = _seed(home, "lrn-b0000015")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(
            lambda ids: [(
                "both", [a, b],
                [{"id": a, "verb": "route", "dest": "claude-md"},
                 {"id": b, "verb": "undefer"}],
                "route", "route",
            )],
            before=lambda ids: (plain / MARKER_FILENAME).unlink(),
        ),
    )

    result = steward.run(home)

    rows = _dispositions(home, result.run_id)
    assert rows[a]["state"] == "abandoned" and rows[b]["state"] == "abandoned", rows
    assert rows[a]["kind"] == "needs-person" and rows[b]["kind"] == "needs-person"
    assert len(_parked_now_cases(home, a)) == 1 and len(_parked_now_cases(home, b)) == 1
    assert len(sent) == 1 and sorted(sent[0][2]) == sorted([a, b])


def test_the_model_may_never_park_a_lesson_as_ledger_refused(tmp_path):
    """`ledger-refused` is written by the runner. A staged case that parks
    with it fails the steward's own validation (the one repair turn's
    remedy), and the brief lists it among the reasons never to write."""
    stage = tmp_path / "stage"
    rid = "lrn-b0000022"
    case = _case([rid], "parked", "reject")
    case.update(kind="parked", parked_for="overseer", parked_reason="ledger-refused")
    _dump_yaml(stage / "cases" / "one.yaml", case)
    _dump_yaml(stage / "sheets" / "one.yaml",
               {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]})

    with pytest.raises(ValueError, match="'ledger-refused' is written by the runner"):
        steward._validate_declared_stage(stage)
    assert "ledger-refused" in steward.steward_prompt.RUNNER_ONLY_PARKED_REASONS
    assert "ledger-refused" in cases.PARKED_REASONS


_ACTIONS_IN_ORDER = ("refused", "retry", "park", "return", "close")


def test_the_action_precedence_is_the_spec_table():
    """§4.2 step 2: refused, then retry, then park, then send back, then
    close -- whichever pair of kinds a record carries."""
    effective = sorted(steward._KIND_ACTIONS)
    for first in effective:
        for second in effective:
            one = steward._KIND_ACTIONS[first]
            other = steward._KIND_ACTIONS[second]
            if _ACTIONS_IN_ORDER.index(one) >= _ACTIONS_IN_ORDER.index(other):
                continue
            for pair in ([first, second], [second, first]):
                refusals = [steward._Refusal(kind, kind) for kind in pair]
                assert steward._deciding(refusals).effective == first, pair


def test_a_reconsider_input_is_parked_rather_than_sent_back(tmp_path):
    """A reconsider input (`observation:<id>`) is never selected again once
    its run consumed the observation, so sending it back would leave it
    decided by no one: it is parked now instead."""
    home = make_env(tmp_path).ledger
    rid = "lrn-b0000016"
    packet = {
        "inputs": [{"record": rid, "version": "observation:obs-0000abcd",
                    "record_status": "routed"}],
        "case_ids": ["case-0000aaaa"],
    }
    items = [{"n": 1, "id": rid, "verb": "reject", "state": "refused", "rc": 1,
              "detail": "simulated: the line is wrong", "kind": "bad-line"}]

    settled = steward._case_dispositions(
        home, {"cases": {}}, packet, "case-0000aaaa", [rid], items, held=True,
    )

    assert settled.park_now == {rid: "bad-line"}
    assert settled.rows[rid]["state"] == "unfinished"


def test_held_refusals_leave_out_a_sanctioned_reopen_pair():
    """The preview does not replay the sheet, so a `[reopen, verb]` pair's
    second line always previews as refused; the runner treats that pair as
    clean, and so must the refusals a held case is judged on."""
    sheet = batch.Sheet([
        batch.SheetItem(1, "lrn-b0000017", "reopen", {}),
        batch.SheetItem(2, "lrn-b0000017", "reject", {}),
        batch.SheetItem(3, "lrn-b0000018", "undefer", {}),
    ])
    preview = batch.DryRunResult(items=[
        batch.DryRunItem(1, "lrn-b0000017", "reopen", "would-apply"),
        batch.DryRunItem(2, "lrn-b0000017", "reject", "would-refuse",
                         detail="is 'routed'", kind="status"),
        batch.DryRunItem(3, "lrn-b0000018", "undefer", "would-refuse",
                         detail="is 'pending'", kind="status"),
    ])

    held = steward._held_refusals(preview, sheet)

    assert [(row["n"], row["id"], row["kind"]) for row in held] == [
        (3, "lrn-b0000018", "status")
    ]


def _dispatch_with(monkeypatch, plan):
    """Monkeypatch `batch._dispatch`: `plan(item, count)` returns an
    `ItemResult` to use, or None to dispatch for real."""
    real = steward.batch._dispatch
    seen: dict[str, int] = {}

    def dispatch(actual_home, item, **kwargs):
        key = f"{item.n}:{item.id}"
        seen[key] = seen.get(key, 0) + 1
        fake = plan(item, seen[key])
        return fake if fake is not None else real(actual_home, item, **kwargs)

    monkeypatch.setattr(steward.batch, "_dispatch", dispatch)
    return seen


def _refused(item, kind, detail):
    return steward.batch.ItemResult(
        n=item.n, id=item.id, verb=item.verb, rc=1, state="refused",
        detail=detail, kind=kind,
    )


def test_a_re_driven_case_does_not_count_its_own_earlier_return_as_a_second(
    tmp_path, monkeypatch
):
    """Lesson A's line is refused as the steward's mistake (sent back);
    lesson B's target is busy (retried), so the case is re-driven. The
    re-drive is the SAME decision refused again, not a fresh one refused a
    second time: A stays sent back and is not parked. (`batch._dispatch` is
    monkeypatched: A is refused every time, B once.)"""
    env = make_env(tmp_path)
    home = env.ledger
    a = _seed(home, "lrn-b0000019")
    b = _seed(home, "lrn-b000001a")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [(
            "both", [a, b], [{"id": a, "verb": "reject"}, {"id": b, "verb": "reject"}],
            "reject", "reject",
        )]),
    )
    _dispatch_with(monkeypatch, lambda item, count: (
        _refused(item, "bad-line", "simulated: the line is wrong") if item.id == a
        else _refused(item, "target-busy", "simulated: uncommitted edits") if count == 1
        else None
    ))

    first = steward.run(home)

    rows = _dispositions(home, first.run_id)
    assert rows[a]["state"] == "returned" and rows[b]["state"] == "unfinished", rows
    monkeypatch.setattr(
        steward.invocation, "write_session",
        lambda spec: pytest.fail("a re-drive never asks the model again"),
    )

    second = steward.run(home)

    assert second.run_id == first.run_id
    rows = _dispositions(home, first.run_id)
    assert rows[b]["state"] == "applied", rows[b]
    assert rows[a]["state"] == "returned", rows[a]
    assert _all_parked_for(home, a) == []


def test_a_park_now_whose_row_write_failed_reuses_its_successor_case(
    tmp_path, monkeypatch
):
    """The successor case lands, the manifest row saying so does not. The
    next run re-drives the case and REUSES that successor: one parked case,
    one notification."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b000001b")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session", _writer(_one_line_each("reject", "reject"))
    )
    _dispatch_with(monkeypatch, lambda item, count: _refused(
        item, "needs-person", "simulated: only a person can fix this"
    ))
    real_update = steward._update_manifest
    failed: list[str] = []

    def update_once_failing(home_, run_id, *, reason, update):
        if "lesson(s) now" in reason and not failed:
            failed.append(reason)
            raise gitops.GitOpsError("simulated: the row write failed")
        return real_update(home_, run_id, reason=reason, update=update)

    monkeypatch.setattr(steward, "_update_manifest", update_once_failing)

    first = steward.run(home)

    assert failed, "positive control: the row write really failed"
    assert _dispositions(home, first.run_id)[rid]["state"] == "unfinished"
    assert len(_parked_now_cases(home, rid)) == 1, "the successor itself landed"
    assert sent == [], "nobody is told before the row says so"
    monkeypatch.setattr(
        steward.invocation, "write_session",
        lambda spec: pytest.fail("a re-drive never asks the model again"),
    )

    steward.run(home)

    row = _dispositions(home, first.run_id)[rid]
    assert row["state"] == "abandoned", row
    rows = _parked_now_cases(home, rid)
    assert len(rows) == 1 and row["successor_case"] == rows[0]["case"]
    assert len(sent) == 1


def test_a_stop_leaves_the_rest_of_the_case_undone_and_all_of_it_is_retried(
    tmp_path, monkeypatch
):
    """A ledger STOP on the first line leaves the second `not-attempted`.
    Neither is the line's fault: both lessons are retried (never parked),
    and the next run applies them. (`batch._dispatch` is monkeypatched to
    stop once.)"""
    env = make_env(tmp_path)
    home = env.ledger
    a = _seed(home, "lrn-b000001c")
    b = _seed(home, "lrn-b000001d")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [(
            "both", [a, b], [{"id": a, "verb": "reject"}, {"id": b, "verb": "reject"}],
            "reject", "reject",
        )]),
    )
    _dispatch_with(monkeypatch, lambda item, count: steward.batch.ItemResult(
        n=item.n, id=item.id, verb=item.verb, rc=6, state="stopped",
        detail="simulated one-off ledger stop",
    ) if item.id == a and count == 1 else None)

    first = steward.run(home)

    rows = _dispositions(home, first.run_id)
    assert rows[a]["state"] == "unfinished" and rows[a]["kind"] == "git", rows[a]
    assert rows[b]["state"] == "unfinished" and rows[b]["kind"] == "git", rows[b]
    assert _all_parked_for(home, b) == [] and sent == []

    second = steward.run(home)

    assert sorted(second.decided) == sorted([a, b])
    assert _head_manifest(home, first.run_id)["status"] == "complete"


def test_a_retry_for_a_lesson_outside_the_case_keeps_the_case_open(
    tmp_path, monkeypatch
):
    """The first case's sheet also carries a line for the second case's
    lesson, and that line's target is busy. No row of the first case says
    so, but the case must still be re-driven: it stays `unfinished`.
    (`batch._dispatch` is monkeypatched to refuse that one line once.)"""
    env = make_env(tmp_path)
    home = env.ledger
    first = _seed(home, "lrn-b000001e")
    second = _seed(home, "lrn-b000001f")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            ("a-first", [first],
             [{"id": first, "verb": "reject"}, {"id": second, "verb": "reject"}],
             "reject", "reject"),
            ("b-second", [second], [{"id": second, "verb": "reject"}], "reject", "reject"),
        ]),
    )
    _dispatch_with(monkeypatch, lambda item, count: _refused(
        item, "target-busy", "simulated: uncommitted edits"
    ) if item.n == 2 and item.id == second and count == 1 else None)

    result = steward.run(home)

    manifest = _head_manifest(home, result.run_id)
    rows = manifest["packets"][0]["dispositions"]
    first_case = rows[first]["case"]
    assert rows[first]["state"] == "applied" and rows[second]["state"] == "applied"
    assert manifest["cases"][first_case]["phase"] == "unfinished"


def test_a_held_case_whose_receipt_did_not_land_is_re_driven(tmp_path, monkeypatch):
    """The preview holds the case back, and the receipt write fails: nothing
    about the lines is final yet, so the lesson is retried, not sent back."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-b0000020")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session", _writer(_one_line_each("undefer", "defer"))
    )
    receipts: list[str] = []

    def failing_receipt(*args, **kwargs):
        receipts.append("failed")
        return {"state": "failed", "pushed": None}

    monkeypatch.setattr(steward.batch, "write_receipt", failing_receipt)

    result = steward.run(home)

    assert receipts, "positive control: the receipt write was attempted"
    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "unfinished", row
    assert result.unfinished == [rid]
