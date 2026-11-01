"""S-117: the overseer never waits on the user.

Decision 4 of the 2026-10-31b round (the orchestrator's, under the user's
words of 15:13, "unless sudo is involved, you should never have to tell me,
'X is waiting on you'"): every question carries a stated default and the
overseer acts on it in the same run, reports it as a decision, and releases
the waiting lessons; the user can overturn any in a later reply. Questions
that only ask the user to confirm the overseer's reading of them are
dropped. For anything that changes the user's system outside self-learn's
own surfaces, the default is "change nothing".

Each test names the mutation it was checked against in its docstring.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, statements, steward, verbs
from self_learn.overseer import conversation
from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_answered_questions import _deferred_case
from test_overseer_conversation import _case, _report_and_index
from test_overseer_run import (
    _dispatch_scripted,
    _enabled,
    _fake_hook_phases,
    _fake_phases_by_label,
    _fake_two_phase,
    _index,
    _refused_block,
    _seed_parked_hook,
    _silence_notifications,
    _wrap_phases,
)
from test_steward import _dump_yaml
from test_steward_refusals import _case as _steward_case
from test_steward_refusals import _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


DEFAULT = "I kept the lesson where it is and did not build the skill."


def _ask(qid: str, case_ids: list[str], **extra) -> dict:
    row = {
        "id": qid, "kind": "ask", "cases": case_ids,
        "text": "Should the diagram skill be built? Yes builds it; no leaves the lesson where it is.",
        "why": "decides whether the lesson moves into a new skill",
        "default": DEFAULT,
    }
    row.update(extra)
    return row


def _needs_shape(*, register: bool = False) -> dict:
    """What a `system: true` or `register` ask written without `needs`
    carries since S-122 fix round 2 (gate r2 MAJOR 2): it is
    read as `needs: user` and held to those rules -- options and a
    recommendation, and for a system change a plan with a check."""
    if register:
        return {
            "options": [{"id": "opt-register", "label": "Register it", "effect": "register"},
                        {"id": "opt-no", "label": "No", "effect": "decline"}],
            "recommend": {"option": "opt-no", "reasoning": "nothing routes there yet"},
        }
    return {
        "options": [{"id": "opt-yes", "label": "Yes, restart it", "effect": "approve"},
                    {"id": "opt-no", "label": "No", "effect": "decline"}],
        "recommend": {"option": "opt-no", "reasoning": "it recovered on its own"},
        "plan": {
            "summary": "Restart the daemon.",
            "checks": [{"say": "It is running", "command": "systemctl --user is-active d"}],
            "steps": [{"say": "Restart it", "command": "systemctl --user restart d",
                       "sudo": False}],
            "files": [],
        },
    }


def _validate(tmp_path: Path, entries: list[dict], known: set[str]):
    path = tmp_path / "questions.yaml"
    with path.open("w", encoding="utf-8") as fh:
        YAML().dump({"questions": entries}, fh)
    return overseer_run._questions(path, {}, known)


def _observations(home: Path, case_id: str) -> str:
    return cases.show(home, case_id, evidence_only=False).sections.get("Later observations", "")


# ---------------------------------------------------- 1. what an ask must carry


def test_a_reading_is_dropped_and_named_and_an_ask_beside_it_is_kept(tmp_path):
    """Mutation checked: indexing a `kind: reading` entry again (the drop
    branch in `_questions` removed) fails this test."""
    case_id = "case-12345678"
    index, dropped = _validate(tmp_path, [
        {"id": "um-1a2b@r1", "kind": "reading", "cases": [case_id]},
        {"id": "um-3c4d@r2", "cases": [case_id]},  # a legacy entry: no kind
        _ask("q-diagram-skill", [case_id]),
    ], {case_id})

    assert [row["id"] for row in index["questions"]] == ["q-diagram-skill"]  # control: the ask stays
    assert dropped == [
        f"question um-1a2b@r1: dropped — {overseer_run._READING_DROPPED}",
        f"question um-3c4d@r2: dropped — {overseer_run._READING_DROPPED}",
    ]


def test_an_ask_without_a_default_is_dropped(tmp_path):
    """Mutation checked: making `default` optional (`_default_problem`
    answering None when it is missing) fails this test."""
    case_id = "case-12345678"
    bare = _ask("q-no-default", [case_id])
    del bare["default"]
    blank = _ask("q-blank-default", [case_id], default="   ")
    index, dropped = _validate(tmp_path, [bare, blank, _ask("q-kept", [case_id])], {case_id})

    assert [row["id"] for row in index["questions"]] == ["q-kept"]  # control
    assert index["questions"][0]["default"] == DEFAULT
    assert len(dropped) == 2
    assert all("an ask needs a default" in line for line in dropped), dropped
    assert dropped[0].startswith("question q-no-default:")


def test_an_ask_about_the_users_system_defaults_to_changing_nothing(tmp_path):
    """A `system: true` ask takes the runner's change-nothing default; one
    that writes its own default is dropped, because that default could
    change the user's system. Mutation checked: letting a system ask keep
    its own default (the `system` branch of `_default_problem` and
    `_ask_default` removed) fails this test."""
    case_id = "case-12345678"
    system_ask = _ask("q-restart-daemon", [case_id], system=True, **_needs_shape())
    del system_ask["default"]
    overreach = _ask("q-edit-dotfile", [case_id], system=True, default="I edited your dotfile.",
                     **_needs_shape())
    index, dropped = _validate(tmp_path, [system_ask, overreach], {case_id})

    assert [row["id"] for row in index["questions"]] == ["q-restart-daemon"]
    row = index["questions"][0]
    assert (row["default"], row["system"]) == (conversation.SYSTEM_DEFAULT, True)
    assert dropped == [
        "question q-edit-dotfile: dropped — an ask with system: true takes no default: "
        "its default is always to change nothing"
    ]


def test_a_registration_ask_registers_nothing_by_default(tmp_path):
    case_id = "case-12345678"
    register = {
        "id": "q-register-app", "kind": "ask", "cases": [case_id],
        "text": "Register /srv/app as a canon host in git mode? Yes registers it; no does not.",
        "why": "decides whether its lessons can be routed there",
        "register": {"path": "/srv/app", "mode": "git"},
        **_needs_shape(register=True),
    }
    with_default = {**register, "id": "q-register-other", "default": "I registered it."}
    index, dropped = _validate(tmp_path, [register, with_default], {case_id})

    assert [row["id"] for row in index["questions"]] == ["q-register-app"]
    assert index["questions"][0]["default"] == conversation.REGISTER_DEFAULT
    assert "system" not in index["questions"][0]
    assert dropped == [
        "question q-register-other: dropped — an ask with register takes no default: "
        "its default is always to change nothing"
    ]


def test_a_default_holding_a_secret_drops_that_ask(tmp_path):
    case_id = "case-12345678"
    leaky = _ask("q-leaky", [case_id], default="I rotated " + "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789.")
    index, dropped = _validate(tmp_path, [leaky, _ask("q-clean", [case_id])], {case_id})
    assert [row["id"] for row in index["questions"]] == ["q-clean"]
    assert dropped == ["question q-leaky: dropped — default matched the secret scan (github-token)"]


# --------------------------------- 2. the run applies every default and says so


def test_a_completed_run_applies_the_default_and_hands_the_deferred_lesson_back(tmp_path, monkeypatch):
    """The whole path: the run indexes the ask with its default, records
    `ask defaulted` on the deferred case it cites, says so under "Decided in
    the user's stead", counts nothing as waiting on the user, and the
    steward's next run takes the lesson back with the default as context.
    Mutation checked: removing the `_record_defaults(home, manifest)` call
    in `_execute_manifest` fails this test (no observation, no reconsider)."""
    home = make_home(tmp_path)
    rid, case_id = _deferred_case(home, tmp_path)
    assert steward._reconsider_proposals(home)[0] == []  # control: nothing brings it back yet
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_two_phase(monkeypatch)
    _wrap_phases(monkeypatch, questions=[_ask("q-diagram-skill", [case_id])])

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code) == ("applied", 0), result
    assert _index(home) == [{**_ask("q-diagram-skill", [case_id])}]
    observed = _observations(home, case_id)
    assert (
        f"overseer statement: ask defaulted q-diagram-skill; default applied: {DEFAULT} "
        f"(ref: overseer-run:{result.run})"
    ) in observed, observed
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    decided = report.split("## Decided in the user's stead\n", 1)[1].split("\n## ", 1)[0]
    assert f"- q-diagram-skill asked and not waited for; applied its default: {DEFAULT}" in decided
    assert conversation.open_question_count(home) == 0  # nothing waits on the user

    ((entry, card),) = steward._reconsider_proposals(home)[0]
    assert (entry.record.id, entry.predecessor) == (rid, case_id)
    assert "did not wait" in card["card"]["unresolved"]
    assert DEFAULT in card["card"]["unresolved"]


def test_the_report_lists_asks_that_changed_nothing_apart(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_two_phase(monkeypatch)
    system_ask = _ask("q-restart-daemon", [case_id], system=True, **_needs_shape())
    del system_ask["default"]
    _wrap_phases(monkeypatch, questions=[system_ask, _ask("q-diagram-skill", [case_id])])

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied", result
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    decided = report.split("## Decided in the user's stead\n", 1)[1].split("\n## ", 1)[0]
    lines = decided.splitlines()
    applied = lines.index(f"- q-diagram-skill asked and not waited for; applied its default: {DEFAULT}")
    unchanged = lines.index(
        f"- q-restart-daemon would change your system: {conversation.SYSTEM_DEFAULT}"
    )
    assert applied < unchanged  # the change-nothing asks come after, apart
    user_model = report.split("## User model\n", 1)[1].split("\n## ", 1)[0]
    assert f"- {overseer_run.READING_CORRECTION_LINE}" in user_model


def test_a_resumed_publish_records_each_default_once(tmp_path):
    """Mutation checked: passing `reserved_id=None` in `_record_defaults`
    (a fresh observation id every call) fails this test."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    manifest = {
        "run_id": "abcd1234",
        "questions": {"questions": [_ask("q-diagram-skill", [case_id])]},
    }

    assert overseer_run._record_defaults(home, manifest) == [case_id]
    overseer_run._record_defaults(home, manifest)  # the resume

    assert _observations(home, case_id).count("ask defaulted q-diagram-skill") == 1


def _supersede(home: Path, tmp_path: Path, predecessor: str, rid: str, outcome: str) -> str:
    successor = _steward_case([rid], outcome, outcome, scope="user")
    successor.update(kind="reconsider", trigger="weekly", supersedes=predecessor)
    stage = tmp_path / f"successor-of-{predecessor}.yaml"
    _dump_yaml(stage, successor)
    return cases.record(home, stage, actor="overseer")


def test_a_default_reaches_the_case_that_superseded_the_cited_one(tmp_path):
    """The model cites the case it read; when a successor has since decided
    the lesson (this run's own, say), the observation goes on that
    successor. Mutation checked: observing the cited case itself (no
    `current_case` step) fails this test."""
    home = make_home(tmp_path)
    rid, cited = _deferred_case(home, tmp_path)
    successor = _supersede(home, tmp_path, cited, rid, "defer")
    manifest = {"run_id": "abcd1234", "questions": {"questions": [_ask("q-diagram-skill", [cited])]}}

    assert overseer_run._record_defaults(home, manifest) == [successor]

    assert "ask defaulted q-diagram-skill" in _observations(home, successor)
    assert "ask defaulted" not in _observations(home, cited)
    ((entry, _card),) = steward._reconsider_proposals(home)[0]
    assert entry.predecessor == successor


def test_a_default_does_not_bring_back_a_case_that_did_not_defer(tmp_path):
    """As with an answer (S-96): a case that decided something else is not
    re-decided because a question cited it."""
    home = make_home(tmp_path)
    rid = _seed(home, "lrn-d0a00003")
    stage = tmp_path / "reject-case.yaml"
    _dump_yaml(stage, _steward_case([rid], "reject", "reject", scope="user"))
    case_id = cases.record(home, stage, actor="overseer")
    verbs.reject(home, rid, by="steward", no_push=True)
    manifest = {"run_id": "abcd1234", "questions": {"questions": [_ask("q-diagram-skill", [case_id])]}}

    overseer_run._record_defaults(home, manifest)

    assert "ask defaulted q-diagram-skill" in _observations(home, case_id)  # control: recorded
    assert steward._reconsider_proposals(home)[0] == []


# ------------------------------------ 3. what the user sees, and overturning


def test_a_defaulted_ask_is_shown_with_its_default_and_does_not_wait(tmp_path):
    """Mutation checked: `waits_on_the_user` answering True for every row
    fails the count; dropping the default line from `_ask_display` fails
    the display."""
    home = make_home(tmp_path)
    defaulted_case = _case(home, tmp_path, "1", {})
    legacy_case = _case(home, tmp_path, "2", {})
    legacy = _ask("q-legacy-ask", [legacy_case])
    del legacy["default"]  # an index written before defaults
    _report_and_index(
        home,
        [_ask("q-diagram-skill", [defaulted_case]), legacy],
        ["- q-diagram-skill: build the skill?", "- q-legacy-ask: an older ask"],
    )

    assert conversation.open_question_count(home) == 1  # only the legacy ask waits
    out = io.StringIO()
    conversation.open_questions(home, out=out)
    shown = out.getvalue()
    assert f"  {conversation.DEFAULT_LABEL}: {DEFAULT}\n" in shown
    assert "q-legacy-ask" in shown  # control: the legacy ask is shown too
    presented = _observations(home, defaulted_case)
    assert f"({conversation.DEFAULT_LABEL}: {DEFAULT})" in presented


def test_an_answer_overturns_the_default_on_the_case_that_now_decides(tmp_path):
    """The user answers after the default was applied and a successor
    decided the lesson: the answer is observed on that successor, and the
    steward takes it back although it did not defer, quoting the answer.
    Mutation checked: recording the S-96 form on the cited case (the
    `row.get("default")` branch of `respond` removed) fails this test."""
    home = make_home(tmp_path)
    rid, cited = _deferred_case(home, tmp_path)
    successor = _supersede(home, tmp_path, cited, rid, "reject")
    _report_and_index(home, [_ask("q-diagram-skill", [cited])], ["- q-diagram-skill: build it?"])
    conversation.open_questions(home, out=io.StringIO())
    assert steward._reconsider_proposals(home)[0] == []  # control: nothing to re-decide yet

    result = conversation.respond(
        home, proposition="q-diagram-skill", scope="user", text="Yes, build the skill after all.",
    )

    assert result.observed_cases == (successor,)
    assert (
        f"overseer statement: user answered q-diagram-skill after its default was applied "
        f"(ref: {result.statement_id})"
    ) in _observations(home, successor)
    ((entry, card),) = steward._reconsider_proposals(home)[0]
    assert (entry.record.id, entry.predecessor) == (rid, successor)
    assert "Yes, build the skill after all." in card["card"]["unresolved"]


def test_an_answer_to_an_ask_without_a_default_is_unchanged(tmp_path):
    """S-96's form, on the cited case, for an index written before
    defaults."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    legacy = _ask("q-diagram-skill", [case_id])
    del legacy["default"]
    _report_and_index(home, [legacy], ["- q-diagram-skill: build it?"])
    conversation.open_questions(home, out=io.StringIO())

    result = conversation.respond(home, proposition="q-diagram-skill", scope="user", text="Yes.")

    observed = _observations(home, case_id)
    assert f"user answered q-diagram-skill (ref: {result.statement_id})" in observed
    assert "after its default was applied" not in observed


def test_a_correction_of_a_reading_reaches_phase_b_and_a_stray_statement_does_not(tmp_path):
    """Readings are no longer asked; a correction the user chooses to make
    is recorded with `statement add` and phase B reads it."""
    home = make_home(tmp_path)
    statements.add(
        home, verbatim="That reading is wrong for this repo.", recorded_by="human",
        source={"message_ref": "conversation:obs-0000abcd", "surface": "conversation"},
        answers={"kind": "proposition", "ref": "um-1a2b@r1", "text": None},
    )
    statements.add(
        home, verbatim="Some lesson words.", recorded_by="human",
        source={"message_ref": "conversation:obs-0000abce", "surface": "conversation"},
    )
    rows = overseer_run._question_answers(home, since=None)
    assert [(row["kind"], row["ref"]) for row in rows] == [("proposition", "um-1a2b@r1")]


# ------------------------------------------------------------- fix round 1


def _decided_block(home: Path) -> str:
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    return report.split("## Decided in the user's stead\n", 1)[1].split("\n## ", 1)[0]


def _awaiting(home: Path) -> set[str]:
    return {row["case"] for row in cases.awaiting_overseer(home)}


def test_a_default_on_a_still_parked_case_is_not_reported_applied(tmp_path, monkeypatch):
    """Gate r1 MAJOR 1: an ask citing a case parked for the overseer, with no
    successor staged this run, decided none of that case's lessons -- the
    hold keeps them. The report must not say the default was applied; it
    names the case under "Refused / could not do", and the parked case is
    not observed. Mutation checked: `_parked_cited` answering {} (every ask
    reported applied) fails this test."""
    home = make_home(tmp_path)
    _rid, deferred = _deferred_case(home, tmp_path)
    _hook_rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_two_phase(monkeypatch)
    _wrap_phases(monkeypatch, questions=[
        _ask("q-diagram-skill", [deferred]),
        _ask("q-parked-hook", [parked], default="I left the hook unbuilt."),
    ])

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied", result
    decided = _decided_block(home)
    # Positive control: the ask beside it is reported applied.
    assert f"- q-diagram-skill asked and not waited for; applied its default: {DEFAULT}" in decided
    assert "q-parked-hook" not in decided, decided
    assert (
        f"- q-parked-hook: default not applied to {parked} — still parked for the overseer; "
        "its lessons stay held until a successor decides it"
    ) in _refused_block(home)
    assert parked in _awaiting(home)
    assert "ask defaulted" not in _observations(home, parked)
    assert "ask defaulted q-diagram-skill" in _observations(home, deferred)  # control


def test_a_default_on_an_ask_citing_parked_and_deferred_cases_names_both(tmp_path):
    """The refusal line names the case the default did reach. Mutation
    checked: `_record_defaults` observing a parked case (its `case_id in
    parked` skip removed) fails this test."""
    home = make_home(tmp_path)
    _rid, deferred = _deferred_case(home, tmp_path)
    _hook_rid, parked = _seed_parked_hook(home, tmp_path)
    manifest = {"run_id": "abcd1234", "questions": {"questions": [
        _ask("q-both", [deferred, parked]),
    ]}}

    assert overseer_run._record_defaults(home, manifest) == [deferred]
    held = overseer_run._parked_cited(home, manifest)

    assert held == {"q-both": {"held": [parked], "reached": [deferred]}}
    assert overseer_run._default_lines(manifest, held) == []
    assert overseer_run._default_refusals(manifest, held) == [
        f"q-both: default not applied to {parked} — still parked for the overseer; its "
        f"lessons stay held until a successor decides it (it was applied to {deferred})"
    ]


def test_an_attempt_held_for_a_retry_records_no_default_and_the_resume_does(tmp_path, monkeypatch):
    """Gate r1 MINOR 2: an attempt whose only failure is a refusal that is
    dispatched again (`target-busy`) publishes no asks (A14), so it records
    no default and reports none; the resume that completes records it, on
    the successor that decided the cited parked case. Mutation checked:
    recording defaults whatever `retry_pending` says (the `if not
    retry_pending:` guard removed) fails this test."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    _wrap_phases(monkeypatch, questions=[_ask("q-hook-now", [parked])])
    _silence_notifications(monkeypatch)
    dispatched = _dispatch_scripted(monkeypatch, {1: (1, "target-busy")})

    first = overseer_run.run(home, dry_run=False, no_push=True)

    assert first.status == "partial", first  # control: held for the retry
    assert dispatched == [1]
    (successor,) = [
        row["case"] for row in cases.list_cases(home, only_ok=True)
        if row.get("supersedes") == parked
    ]
    assert "ask defaulted" not in _observations(home, successor)
    assert "ask defaulted" not in _observations(home, parked)
    assert "q-hook-now" not in _decided_block(home)

    second = overseer_run.run(home, dry_run=False, no_push=True)

    assert second.run == first.run and dispatched == [1, 1]
    assert second.status == "applied", second
    assert _observations(home, successor).count("ask defaulted q-hook-now") == 1
    assert f"- q-hook-now asked and not waited for; applied its default: {DEFAULT}" in _decided_block(home)


def test_the_close_out_question_states_its_default():
    """Gate r1 MINOR 3: the runner's own question, when a week closes at
    the attempt cap, says what happens if the user says nothing."""
    (line,) = overseer_run._close_out_questions(
        week="2026-10-25", attempts=3, kind="no-progress", detail="stuck", unfinished=[],
    )
    assert "was closed after 3 failed attempts" in line  # control: the question
    assert line.endswith(
        "Unless you say otherwise, next week's run takes these up; nothing waits on you."
    )


def test_a_correction_of_a_reading_reaches_phase_b_only_once(tmp_path):
    """Gate r1 MINOR 5: a correction recorded before the last completed run
    was already in front of a phase B (or applied by the old `respond`),
    so it is not offered again; an answer to an ask is offered as before.
    The stamp is the caller's (gate r2 MAJOR 1); the full-run test below
    covers which stamp `run()` passes. Mutation checked: `_fresh` answering
    True always fails this test."""
    home = make_home(tmp_path)
    statements.add(
        home, verbatim="That reading is wrong for this repo.", recorded_by="human",
        source={"message_ref": "conversation:obs-0000abcd", "surface": "conversation"},
        answers={"kind": "proposition", "ref": "um-1a2b@r1", "text": None},
    )
    statements.add(
        home, verbatim="Yes, build it.", recorded_by="human",
        source={"message_ref": "conversation:obs-0000abcf", "surface": "conversation"},
        answers={"kind": "question", "ref": "q-diagram-skill", "text": None},
    )

    # the correction came after the last completed run
    assert sorted(
        row["kind"] for row in overseer_run._question_answers(home, since="2000-01-01T00:00:00Z")
    ) == ["proposition", "question"]
    # the correction came before it
    assert [
        row["kind"] for row in overseer_run._question_answers(home, since="2999-01-01T00:00:00Z")
    ] == ["question"]


def test_a_proposition_answer_whose_ref_is_not_a_reading_is_left_out(tmp_path):
    """Gate r1 NIT 7: a `str` ref that is not `um-<4 hex>@r<n>`. Mutation
    checked: replacing the `_PROPOSITION_RE` test with `isinstance(ref,
    str)` alone fails this test."""
    home = make_home(tmp_path)
    statements.add(
        home, verbatim="About something else.", recorded_by="human",
        source={"message_ref": "conversation:obs-0000abcd", "surface": "conversation"},
        answers={"kind": "proposition", "ref": "not-a-reading", "text": None},
    )
    statements.add(
        home, verbatim="That reading is wrong.", recorded_by="human",
        source={"message_ref": "conversation:obs-0000abce", "surface": "conversation"},
        answers={"kind": "proposition", "ref": "um-1a2b@r1", "text": None},
    )
    assert [row["ref"] for row in overseer_run._question_answers(home, since=None)] == ["um-1a2b@r1"]


def test_current_case_stops_where_a_cycle_closes(tmp_path):
    """Gate r1 NIT 7: a corrupt successor cycle cannot loop for ever."""
    home = make_home(tmp_path)
    links = {"case-aaaaaaaa": "case-bbbbbbbb", "case-bbbbbbbb": "case-aaaaaaaa"}
    assert conversation.current_case(home, "case-aaaaaaaa", links) == "case-bbbbbbbb"
    assert conversation.current_case(home, "case-cccccccc", links) == "case-cccccccc"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("default", "  ", "has an empty default"),
        ("system", "yes", "has a system flag that is not true or false"),
    ],
)
def test_an_index_row_with_a_bad_default_or_system_flag_is_refused(tmp_path, field, value, message):
    """Gate r1 NIT 7: `overseer open` refuses an index row it cannot trust."""
    home = make_home(tmp_path)
    case_id = _case(home, tmp_path, "1", {})
    row = {**_ask("q-diagram-skill", [case_id]), field: value}
    _report_and_index(home, [row], ["- q-diagram-skill: build it?"])
    with pytest.raises(conversation.ConversationError, match=message):
        conversation.open_questions(home, out=io.StringIO())


# ------------------------------------------------------------- fix round 2


def _correction(home: Path, at: str, words: str, ref: str) -> None:
    """Record a correction of a reading stamped *at* (the clock is pinned
    for this one write only, so the test never depends on two writes
    landing in different seconds)."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(statements.chrono, "now_iso", lambda *_a, **_k: at)
        statements.add(
            home, verbatim=words, recorded_by="human",
            source={"message_ref": f"conversation:obs-{ref[3:7]}abcd", "surface": "conversation"},
            answers={"kind": "proposition", "ref": ref, "text": None},
        )


def _staged_refs(seen: dict) -> list[str]:
    rows = YAML(typ="safe").load(seen["b_stage"]["answers.yaml"])["answers"]
    return sorted(row["ref"] for row in rows if row["kind"] == "proposition")


def test_a_real_run_offers_a_correction_once_and_the_next_run_does_not(tmp_path, monkeypatch):
    """Gate r2 MAJOR 1: a real run writes THIS run's coverage (its own
    `last_run_at`) before it stages phase B, so reading the stamp from
    `coverage.yaml` at staging time filtered out every correction recorded
    since the previous run. The stamp is the one the run found. Run 1
    (real, scheduled, no earlier run) must offer the correction recorded
    before it; run 2 (real, manual -- never held by a done week) must not
    offer it again, and must offer one recorded after run 1 (its positive
    control). Mutations checked: reading the stamp from `coverage.yaml`
    again (`_question_answers(home, since=_coverage_last_run_at(home))` in
    `_full_inputs`) fails run 1; `_fresh` answering True always fails
    run 2."""
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_phases_by_label(monkeypatch)  # keyed on the label: two runs in one test
    _correction(home, "2000-01-01T00:00:00Z", "That reading is wrong.", "um-1a2b@r1")
    seen = _wrap_phases(monkeypatch)

    first = overseer_run.run(home, dry_run=False, no_push=True)

    assert first.status == "applied", first
    stamp = overseer_run._coverage_last_run_at(home)
    assert stamp is not None and stamp > "2000-01-01T00:00:00Z"  # control: run 1 moved it
    assert _staged_refs(seen) == ["um-1a2b@r1"]

    _correction(home, "2999-01-01T00:00:00Z", "This one is wrong too.", "um-3c4d@r1")
    second = overseer_run.run(home, dry_run=False, no_push=True, manual=True)

    assert second.status == "applied", second
    assert _staged_refs(seen) == ["um-3c4d@r1"]
