"""S-NEXT-overseer-asks: the overseer's asks say who they need.

The attention round (`misc/build-2026-10-31c/attention-design-r2.md` r2.1
§1.3, §3.8, §4.4, §4.5, §5.2). The user's answers of 2026-10-31 20:45, in
`decisions.md`: answer 2 (the closed needs-you list), answer 3 (system-change
ideas are raised as needs-you, nothing changed meanwhile), answer 4 ("until i
answer or it stops mattering, indefinitely. it become part of the overseer's
weekly 'is this shit still relevant' checks."), answer 6 (a conflict: the
newer statement wins meanwhile), answer 7 (feedback clicks are evidence for
overseer asks); the orchestrator's C2.

Each test names the mutation it was checked against in its docstring.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import attention, statements
from self_learn.overseer import conversation, formats
from self_learn.overseer import run as overseer_run
from support import commit_all, make_home
from test_overseer_answered_questions import _deferred_case
from test_overseer_conversation import _report_and_index
from test_overseer_run import (
    _dump,
    _enabled,
    _fake_hook_phases,
    _fake_phases_by_label,
    _index,
    _refused_block,
    _seed_parked_hook,
    _silence_notifications,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


DEFAULT = "I left the lesson where it is this week."
TEXT = "Will you run the one sudo step that installs the udev rule? Yes means you run it; no leaves it."


SUDO_OPTIONS = [
    {"id": "opt-ran", "label": "I'll run it", "effect": "approve"},
    {"id": "opt-not-now", "label": "No", "effect": "decline"},
]


def _user_ask(qid: str, cases: list[str], because: str = "sudo", **extra) -> dict:
    """A needs-user ask with the options and recommendation every such ask
    carries (fix round 1, gate r1 MAJOR 2); *extra* overrides any key, and
    a given `options` without a `recommend` recommends its first option."""
    row = {
        "id": qid, "kind": "ask", "cases": cases, "text": TEXT,
        "why": "only you can run sudo", "needs": "user", "because": because,
        "options": [dict(o) for o in SUDO_OPTIONS],
    }
    row.update(extra)
    if "recommend" not in extra and isinstance(row.get("options"), list) and row["options"]:
        row["recommend"] = {"option": row["options"][0]["id"], "reasoning": "it is the safe one"}
    return row


def _plan(*, sudo_order=(False, False), checks=True) -> dict:
    return {
        "summary": "Add a systemd drop-in binding the daemon to the bus.",
        "checks": [{"say": "No drop-in binds it yet", "command": "systemctl --user cat d.service"}]
        if checks else [],
        "steps": [
            {"say": f"step {n}", "command": f"true {n}", "sudo": sudo}
            for n, sudo in enumerate(sudo_order, start=1)
        ],
        "files": [{"path": "~/.config/systemd/user/d.service.d/bind.conf", "content": "[Unit]\n"}],
    }


OPTIONS = [
    {"id": "opt-yes", "label": "Yes, add it", "effect": "approve"},
    {"id": "opt-no", "label": "No, leave it", "effect": "decline"},
]


def _system_ask(qid: str, cases: list[str], **extra) -> dict:
    row = _user_ask(
        qid, cases, because="system-change", options=[dict(o) for o in OPTIONS],
        recommend={"option": "opt-yes", "reasoning": "the lesson recorded it three times"},
        plan=_plan(),
    )
    row["text"] = "Bind the daemon to the session bus? Yes adds a drop-in; no keeps the manual note."
    row.update(extra)
    return row


def _validate(tmp_path: Path, entries: list[dict], known: set[str], **kw):
    path = tmp_path / "questions.yaml"
    with path.open("w", encoding="utf-8") as fh:
        YAML().dump({"questions": entries}, fh)
    return overseer_run._questions(path, {}, known, **kw)


def _ids(index: dict) -> list[str]:
    return [row["id"] for row in index["questions"]]


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime.now(timezone.utc)


def _choice(q_id: str, option: str | None, effect: str | None, at: datetime, *,
            how: str = "clicked", label: str | None = None, cid: str = "chc-0000aaaa") -> dict:
    return {
        "id": cid, "at": _iso(at), "item": attention.item_id("ask.system-change", q_id),
        "item_kind": "ask.system-change", "subject": q_id, "how": how, "option": option,
        "label": label, "effect": effect, "text": None, "draft_id": None, "draft_text": None,
        "offered_by": "overseer", "answers": {"kind": "question", "ref": q_id},
        "source": {"message_ref": "workspace:att-000000000000#T1"}, "statement": None,
        "proof": None, "recorded_by": "human", "note": None,
    }


def _write_jsonl(home: Path, name: str, rows: list[dict]) -> None:
    path = home / "attention" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    commit_all(home, f"fixture {name}")


def _decided_block(home: Path) -> str:
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    return report.split("## Decided in the user's stead\n", 1)[1].split("\n## ", 1)[0]


def _withdrawn(home: Path) -> list[dict]:
    path = home / "overseer" / "withdrawn.yaml"
    if not path.is_file():
        return []
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))["withdrawn"]


def _phases(monkeypatch) -> dict:
    """The label-keyed fake (several runs in one test) whose phase B writes
    `state["questions"]` and `state["withdraw"]`, recording phase B's stage."""
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _fake_phases_by_label(monkeypatch)
    inner = overseer_run.invocation.write_session
    state: dict = {"questions": [], "withdraw": None, "hook": None}

    def invoke(spec):
        outcome = inner(spec)
        if spec.label == "phase-b":
            state["b_stage"] = {
                path.relative_to(spec.cwd).as_posix(): path.read_text(encoding="utf-8")
                for path in sorted(spec.cwd.rglob("*.yaml")) if path.is_file()
            }
            data: dict = {"questions": state["questions"]}
            if state["withdraw"] is not None:
                data["withdraw"] = state["withdraw"]
            _dump(spec.cwd / "questions.yaml", data)
            if state["hook"] is not None:
                state["hook"](spec.cwd)
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    return state


def _run(home: Path, *, first: bool = False):
    result = overseer_run.run(home, dry_run=False, no_push=True, manual=not first)
    assert result.status == "applied", result
    return result


def _row(home: Path, q_id: str) -> dict | None:
    return next((row for row in _index(home) if row["id"] == q_id), None)


# ------------------------------------------------ 1. needs, because, refile


def test_needs_user_without_a_valid_because_is_filed_in_the_users_stead_and_named(tmp_path):
    """Mutation checked: keeping such an ask as `needs: user` (the refile
    branch of `_r2_ask` removed) fails this test."""
    case_id = "case-12345678"
    index, dropped = _validate(tmp_path, [
        _user_ask("q-good", [case_id]),
        _user_ask("q-no-key", [case_id], because="credentials", default=DEFAULT),
        _user_ask("q-no-key-no-default", [case_id], because=None),
    ], {case_id}, now="2026-10-31T12:00:00Z")

    assert _ids(index) == ["q-good", "q-no-key"]
    good, refiled = index["questions"]
    # Positive control: a valid needs-user ask keeps needs: user and gets the
    # runner's meanwhile sentence and its first-asked stamp.
    assert (good["needs"], good["because"]) == ("user", "sudo")
    assert good["default"] == conversation.NEEDS_USER_DEFAULTS["sudo"]
    assert good["asked_at"] == "2026-10-31T12:00:00Z"
    assert (refiled["needs"], refiled["default"]) == ("stead", DEFAULT)
    assert "because" not in refiled and "asked_at" not in refiled
    assert any(
        line.startswith("question q-no-key: filed as decided in your stead — needs: user "
                        "requires because")
        for line in dropped
    ), dropped
    assert any(line.startswith("question q-no-key-no-default: dropped — needs: user requires "
                               "because") for line in dropped), dropped
    assert conversation.waits_on_the_user(good)
    assert not conversation.waits_on_the_user(refiled)


# ------------------------------------------------- 2. waits_on_the_user


def test_waits_on_the_user_reads_needs_not_default():
    """Mutation checked: `waits_on_the_user` answering `not default` again
    (S-117's rule) fails the needs-user and the legacy system rows."""
    user = {"kind": "ask", "needs": "user", "because": "sudo", "default": "Nothing was run."}
    legacy_system = {"kind": "ask", "system": True, "default": conversation.SYSTEM_DEFAULT}
    legacy_register = {"kind": "ask", "register": {"path": "/x", "mode": "git"},
                       "default": conversation.REGISTER_DEFAULT}
    stead = {"kind": "ask", "needs": "stead", "default": DEFAULT}
    old_stead = {"kind": "ask", "default": DEFAULT}
    before_defaults = {"kind": "ask"}
    assert conversation.waits_on_the_user(user)
    assert conversation.waits_on_the_user(legacy_system)
    assert conversation.waits_on_the_user(legacy_register)
    assert not conversation.waits_on_the_user(stead)  # control
    assert not conversation.waits_on_the_user(old_stead)
    assert conversation.waits_on_the_user(before_defaults)
    assert conversation.waits_on_the_user({"kind": "reading"})


# ------------------------------------------------- 3. carry-forward


def test_an_unanswered_needs_user_ask_is_carried_forward_and_an_answered_one_is_not(
    tmp_path, monkeypatch,
):
    """Mutation checked: writing the index from the model's asks only
    (`_carry_forward` answering `{"questions": new_rows}` at once) fails the
    second run's assertions."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [
        _user_ask("q-run-sudo", [case_id]),
        _user_ask("q-clicked", [case_id], because="foreign-history",
                  text="Push the fix to the upstream repository? Yes pushes; no keeps it local."),
        _user_ask("q-said", [case_id], because="money",
                  text="Pay for the larger plan? Yes pays; no keeps the current one.",
                  options=[dict(o) for o in OPTIONS],
                  plan={**_plan(), "summary": "Upgrade the plan."}),
    ]
    _run(home, first=True)
    first = {row["id"]: row for row in _index(home)}
    assert set(first) == {"q-run-sudo", "q-clicked", "q-said"}
    asked = first["q-run-sudo"]["asked_at"]

    # q-clicked is answered by a click (the choices store, §4.4); q-said
    # (with a plan) gets only words, which do not answer it.
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-clicked", None, "other", datetime.now(timezone.utc) + timedelta(seconds=1),
                label="Not now"),
    ])
    statements.add(
        home, verbatim="Not this month.", recorded_by="human",
        source={"message_ref": "conversation:obs-0000abcd", "surface": "conversation"},
        answers={"kind": "question", "ref": "q-said", "text": None},
    )
    state["questions"] = []
    _run(home)

    second = {row["id"]: row for row in _index(home)}
    assert set(second) == {"q-run-sudo", "q-said"}
    assert second["q-run-sudo"]["asked_at"] == asked  # its first asked_at
    assert second["q-run-sudo"]["needs"] == "user"
    out = io.StringIO()
    conversation.open_questions(home, out=out)
    assert "q-run-sudo" in out.getvalue()
    result = conversation.respond(home, proposition="q-run-sudo", scope="user", text="I ran it.")
    assert result.statement_id
    assert conversation.open_question_count(home) == 1  # q-said still waits

    _run(home)
    assert [row["id"] for row in _index(home)] == ["q-said"]


# ------------------------------------------------- 4. withdraw and the backstop


def test_a_withdrawn_ask_leaves_the_index_and_is_never_asked_again_in_other_words(
    tmp_path, monkeypatch,
):
    """Mutation checked: skipping the backstop (`_backstop_problem`
    answering None) fails the third run."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [_user_ask("q-moot", [case_id])]
    _run(home, first=True)
    assert _row(home, "q-moot") is not None  # control
    open_asks = YAML(typ="safe").load(state["b_stage"]["open-asks.yaml"])
    assert open_asks["asks"] == []  # nothing was open before run 1

    state["questions"] = []
    state["withdraw"] = [{"id": "q-moot", "why": "the device it was about was returned."}]
    second = _run(home)

    assert YAML(typ="safe").load(state["b_stage"]["open-asks.yaml"])["asks"][0]["id"] == "q-moot"
    assert _row(home, "q-moot") is None
    (gone,) = _withdrawn(home)
    assert (gone["id"], gone["why"], gone["because"], gone["run"]) == (
        "q-moot", "the device it was about was returned.", "sudo", second.run,
    )
    assert gone["row"]["text"] == TEXT  # the whole row, for a reopen
    assert "- q-moot withdrawn: I stopped asking because the device it was about was returned." \
        in _decided_block(home)

    state["withdraw"] = None
    state["questions"] = [
        _user_ask("q-same-again", [case_id]),  # same because, same cases
        _user_ask("q-moot", [case_id]),  # the same id
        _user_ask("q-other-reason", [case_id], because="foreign-history",
                  text="Push the fix upstream? Yes pushes; no keeps it local."),
    ]
    _run(home)
    assert [row["id"] for row in _index(home)] == ["q-other-reason"]  # control: a new reason is asked
    refused = _refused_block(home)
    assert "q-same-again: dropped — it asks again, in other words, what q-moot asked" in refused
    assert "q-moot: dropped — it was withdrawn as moot" in refused


# ------------------------------------------------- 5. no age close


def test_an_unanswered_ask_is_still_indexed_after_ten_weekly_runs(tmp_path, monkeypatch):
    """Answer 4: no close for age. Mutation checked: closing an ask once
    three run records exist (`_carry_forward` carrying nothing when
    `len(_committed_overseer_manifests(home)) > 3`) fails at run 4."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [_user_ask("q-forever", [case_id])]
    _run(home, first=True)
    asked = _row(home, "q-forever")["asked_at"]  # positive control: indexed after run 1
    state["questions"] = []
    for n in range(2, 11):
        _run(home)
        row = _row(home, "q-forever")
        assert row is not None, f"closed at run {n}"
        assert row["asked_at"] == asked


# ------------------------------------------------- 6. conflict asks


def _statement(home: Path, words: str, n: int) -> str:
    return statements.add(
        home, verbatim=words, recorded_by="human",
        source={"message_ref": f"conversation:obs-0000ab{n:02d}", "surface": "conversation"},
    )


def test_a_conflict_ask_names_two_existing_statements_or_is_dropped(tmp_path):
    home = make_home(tmp_path)
    a = _statement(home, "Never tell me X is waiting on you.", 1)
    b = _statement(home, "Legit things that need my attention are fine.", 2)
    known = {a, b}
    case_id = "case-12345678"
    conflict = {"because": "conflict", "text": "Which of your two statements wins? Pick one."}
    index, dropped = _validate(tmp_path, [
        _user_ask("q-one", [case_id], statements=[a], **conflict),
        _user_ask("q-unknown", [case_id], statements=[a, "stmt-deadbeef"], **conflict),
        _user_ask("q-same", [case_id], statements=[a, a], **conflict),
        _user_ask("q-two", [case_id], statements=[a, b], **conflict),
    ], {case_id}, known_statements=known)

    assert _ids(index) == ["q-two"]  # control
    assert index["questions"][0]["statements"] == [a, b]
    assert index["questions"][0]["default"] == "The newer statement holds until you say otherwise."
    assert "question q-one: dropped — a conflict ask names exactly two distinct statements" in dropped
    assert "question q-unknown: dropped — names unknown statement(s) stmt-deadbeef" in dropped
    assert "question q-same: dropped — a conflict ask names exactly two distinct statements" in dropped


# ------------------------------------------------- 7. options and plan


def test_options_recommend_and_plan_are_validated(tmp_path):
    """Mutations checked: dropping the plan requirement (the
    `PLAN_REQUIRED_BECAUSE` branch of `_r2_ask`) fails q-no-plan and
    q-money-no-plan; dropping the sudo-order check in `_plan_problem` fails
    q-sudo-late."""
    case_id = "case-12345678"
    three = [*OPTIONS, {"id": "opt-later", "label": "Ask me later", "effect": "other"}]
    entries = [
        _system_ask("q-good", [case_id], options=three),
        _system_ask("q-one-option", [case_id], options=[OPTIONS[0]]),
        _system_ask("q-five-options", [case_id], options=[
            {"id": f"opt-{n}", "label": f"choice {n}", "effect": "other"} for n in range(5)
        ]),
        _system_ask("q-dup", [case_id], options=[OPTIONS[0], dict(OPTIONS[0])]),
        _system_ask("q-bad-recommend", [case_id], recommend={"option": "opt-x", "reasoning": "r"}),
        _system_ask("q-no-plan", [case_id], plan=None),
        _user_ask("q-money-no-plan", [case_id], because="money", options=OPTIONS),
        _system_ask("q-approve-only", [case_id], options=[
            OPTIONS[0], {"id": "opt-also", "label": "Also yes", "effect": "approve"},
        ]),
        _system_ask("q-no-checks", [case_id], plan=_plan(checks=False)),
        _system_ask("q-sudo-late", [case_id], plan=_plan(sudo_order=(False, True)), default=DEFAULT),
        _system_ask("q-sudo-late-bare", [case_id], plan=_plan(sudo_order=(False, True))),
        _system_ask("q-sudo-first", [case_id], plan={**_plan(sudo_order=(True, False)), "sudo": False}),
    ]
    index, dropped = _validate(tmp_path, entries, {case_id})

    assert _ids(index) == ["q-good", "q-sudo-late", "q-sudo-first"]
    good, late, first = index["questions"]
    assert (good["needs"], good["because"], good["system"]) == ("user", "system-change", True)
    assert [o["id"] for o in good["options"]] == ["opt-yes", "opt-no", "opt-later"]
    assert good["recommend"]["option"] == "opt-yes"
    assert good["plan"]["sudo"] is False
    assert good["default"] == conversation.SYSTEM_DEFAULT
    # A sudo step after a plain one: filed in the user's stead, with no plan.
    assert (late["needs"], late["default"]) == ("stead", DEFAULT)
    assert "plan" not in late
    assert any(line.startswith("question q-sudo-late: filed as decided in your stead — its plan "
                               "has a sudo step after a step without sudo") for line in dropped)
    assert any(line.startswith("question q-sudo-late-bare: dropped — its plan has a sudo step")
               for line in dropped), dropped
    # plan.sudo is derived; the model's `sudo: false` is ignored.
    assert first["plan"]["sudo"] is True
    assert first["plan"]["steps"][0]["sudo"] is True
    wanted = {
        "q-one-option": "options must be a list of 2 to 4 entries",
        "q-five-options": "options must be a list of 2 to 4 entries",
        "q-dup": "duplicate option id opt-yes",
        "q-bad-recommend": "recommend must be {option, reasoning} naming one of the ask's options",
        "q-no-plan": "a system-change ask needs a plan",
        "q-money-no-plan": "a money ask needs a plan",
        "q-approve-only": "an ask with a plan needs at least one approve and one decline option",
        "q-no-checks": "a system-change plan needs at least one check",
    }
    for q_id, why in wanted.items():
        assert any(line.startswith(f"question {q_id}: dropped — {why}") for line in dropped), (
            q_id, dropped,
        )


# ------------------------------------------------- 8. phase B's inputs


def _hand_index(home: Path, rows: list[dict]) -> None:
    _report_and_index(home, rows, [f"- {row['id']}: …" for row in rows])


def test_phase_b_sees_open_asks_choices_feedback_and_stale_approvals(tmp_path, monkeypatch):
    """Mutations checked: leaving the choices out of answers.yaml (an empty
    `_choice_answers`) fails the choices assertion; leaving approved items
    out (`_open_asks` never appending `kind: approved`) fails the approved
    assertion and the withdrawal."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    three_weeks = _iso(NOW - timedelta(days=22))
    open_ask = _user_ask("q-open", [case_id], default=conversation.NEEDS_USER_DEFAULTS["sudo"],
                         asked_at=three_weeks)
    approved = _system_ask("q-approved", [case_id], default=conversation.SYSTEM_DEFAULT,
                           asked_at=_iso(NOW - timedelta(days=20)), system=True)
    approved["plan"]["sudo"] = False
    fresh = _system_ask("q-fresh-approval", [case_id], default=conversation.SYSTEM_DEFAULT,
                        asked_at=_iso(NOW - timedelta(days=5)), system=True)
    _hand_index(home, [open_ask, approved, fresh])
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-approved", "opt-yes", "approve", NOW - timedelta(days=10), label="Yes, add it"),
        _choice("q-fresh-approval", "opt-yes", "approve", NOW - timedelta(days=2),
                label="Yes, add it", cid="chc-0000bbbb"),
    ])
    _write_jsonl(home, "feedback.jsonl", [{
        "id": "fb-00000001", "at": _iso(NOW - timedelta(days=1)),
        "item": attention.item_id("ask.sudo", "q-open"), "kind": "ask.sudo",
        "class_shown": "needs-you", "class_wanted": "decided", "by": "human", "note": None,
    }])
    state = _phases(monkeypatch)
    item = attention.item_id("approved.pending", "q-approved")
    state["withdraw"] = [{"id": item, "why": "the daemon was replaced and needs no binding."}]

    _run(home, first=True)

    staged = YAML(typ="safe").load(state["b_stage"]["open-asks.yaml"])
    by_id = {entry["id"]: entry for entry in staged["asks"]}
    assert set(by_id) == {"q-open", "q-approved"}  # the 2-day approval is not stale yet
    assert (by_id["q-open"]["kind"], by_id["q-open"]["weeks_open"]) == ("ask", 3)
    assert by_id["q-open"]["cases"][0]["case"] == case_id
    assert by_id["q-open"]["feedback"][0]["the_user_wanted"] == "decided"
    stale = by_id["q-approved"]
    assert (stale["kind"], stale["item"], stale["days_since_approved"]) == ("approved", item, 10)
    assert stale["plan"]["checks"][0]["say"] == "No drop-in binds it yet"
    answers = YAML(typ="safe").load(state["b_stage"]["answers.yaml"])
    chose = [row for row in answers["choices"] if row["ref"] == "q-approved"]
    assert chose and chose[0]["chose"] == "Yes, add it"
    assert all("said" not in row and "verbatim" not in row for row in answers["choices"])
    assert answers["feedback"][0]["ask"] == "q-open"

    # The withdrawal of the stale approval, named by its inbox item id.
    assert _row(home, "q-approved") is None
    assert [row["id"] for row in _withdrawn(home)] == ["q-approved"]
    assert _row(home, "q-open") is not None and _row(home, "q-fresh-approval") is not None


# ------------------------------------------------- 9. the formats contract


def test_the_formats_contract_and_the_prompt_carry_the_r2_rules(tmp_path):
    sets = formats.closed_sets()["questions"]
    for key in ("needs", "because", "options", "recommend", "plan", "look_at", "statements"):
        assert key in sets["ask_keys"], key
    assert sets["needs"] == ["user", "stead"]
    assert sets["because"] == ["system-change", "foreign-history", "conflict", "money", "sudo"]
    assert sets["option_effects"] == ["approve", "decline", "other", "register"]
    assert sets["withdraw_keys"] == ["id", "why"]
    assert sets["needs_user_requires"] == ["because", "options", "recommend"]
    flat = " ".join(overseer_run._phase_b_prompt(tmp_path, (), ()).split())
    assert " ".join(overseer_run.ORDERED_CHECK.split()) in flat
    assert "Never ask a withdrawn question again in other words" in flat
    assert "checks are read-only commands" in flat
    assert "for a conflict, the newer statement wins meanwhile" in flat
    assert "never re-asked" in flat and "ask under a new id" in flat
    # Fix round 1 (gate r1 MAJOR 3): no real ledger ids in the product prompt.
    assert __import__("re").findall(r"stmt-[0-9a-f]{8}", overseer_run.ORDERED_CHECK) == [
        "stmt-0123abcd"
    ]
    assert "`q-example-models`" in overseer_run.ORDERED_CHECK
    readme = " ".join((formats.write(tmp_path / "ws", "B") / "README.md").read_text("utf-8").split())
    assert "checks are read-only commands" in readme
    example = YAML(typ="safe").load(formats.phase_b_examples()["questions.yaml"])
    index, dropped = _validate(tmp_path, example["questions"], {formats.EXAMPLE_CASE})
    assert dropped == [] and len(index["questions"]) == 2  # the examples are valid


# ------------------------------------------------- 10. what answers a plan ask


def test_an_ask_with_a_plan_is_answered_only_by_a_choice_naming_one_of_its_options(tmp_path):
    """Mutation checked: counting statements for a plan ask (the
    `has_plan` branch of `_answered_ids` removed) fails the words-only
    assertions."""
    home = make_home(tmp_path)
    case_id = "case-12345678"
    asked = _iso(NOW - timedelta(days=1))
    plan_ask = _system_ask("q-plan", [case_id], default=conversation.SYSTEM_DEFAULT,
                           asked_at=asked, system=True)
    plain = _user_ask("q-plain", [case_id], default=conversation.NEEDS_USER_DEFAULTS["sudo"],
                      asked_at=asked)
    _hand_index(home, [plan_ask, plain])
    for q_id, n in (("q-plan", 1), ("q-plain", 2)):
        statements.add(
            home, verbatim="No, not now.", recorded_by="human",
            source={"message_ref": f"conversation:obs-0000cd{n:02d}", "surface": "conversation"},
            answers={"kind": "question", "ref": q_id, "text": None},
        )
    ids = {"q-plan", "q-plain"}
    assert conversation._answered_ids(home, ids) == {"q-plain"}  # words answer the plain ask only
    carried = overseer_run._carry_forward(home, {"questions": []}, [], run_id="abcd1234")
    assert [row["id"] for row in carried.index["questions"]] == ["q-plan"]

    _write_jsonl(home, "choices.jsonl", [
        _choice("q-plan", "opt-no", "decline", NOW, label="No, leave it"),
    ])
    assert conversation._answered_ids(home, ids) == ids
    carried = overseer_run._carry_forward(home, {"questions": []}, [], run_id="abcd1234")
    assert carried.index["questions"] == []


# ------------------------------------------------- 11. reopen


def test_reopen_puts_a_withdrawn_ask_back_with_its_first_asked_at(tmp_path):
    home = make_home(tmp_path)
    case_id = "case-12345678"
    asked = "2026-09-01T00:00:00Z"
    row = _user_ask("q-back", [case_id], default=conversation.NEEDS_USER_DEFAULTS["sudo"],
                    asked_at=asked)
    _hand_index(home, [])
    (home / "overseer" / "withdrawn.yaml").write_text(
        overseer_run._yaml_text({"withdrawn": [{
            "id": "q-back", "text": TEXT, "because": "sudo", "cases": [case_id],
            "asked_at": asked, "withdrawn_at": "2026-10-01T00:00:00Z", "run": "abcd1234",
            "why": "moot", "row": row,
        }]}),
        encoding="utf-8",
    )
    commit_all(home, "fixture withdrawn")

    back = conversation.reopen(home, "q-back")

    assert (back["needs"], back["because"], back["asked_at"]) == ("user", "sudo", asked)
    assert _row(home, "q-back")["asked_at"] == asked
    assert _withdrawn(home) == []
    assert conversation.open_question_count(home) == 1
    status = __import__("subprocess").run(
        ["git", "-C", str(home), "status", "--porcelain"], capture_output=True, text=True, check=True,
    ).stdout
    assert status == ""  # committed
    with pytest.raises(conversation.ConversationError, match="not a withdrawn question"):
        conversation.reopen(home, "q-back")


def test_a_reopen_made_while_a_run_is_in_progress_survives_its_finalize(tmp_path, monkeypatch):
    """Critique 32. Mutation checked: reading the previous index when the
    run starts (a snapshot taken in `_prepare_manifest` and used by
    `_carry_forward`) fails this test: the reopened ask is lost."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [_user_ask("q-moot", [case_id])]
    _run(home, first=True)
    state["questions"] = []
    state["withdraw"] = [{"id": "q-moot", "why": "it stopped mattering."}]
    _run(home)
    assert _row(home, "q-moot") is None  # control: withdrawn
    state["withdraw"] = None

    real = overseer_run._record_defaults
    reopened: list[str] = []

    def reopen_mid_run(given_home, manifest):
        if not reopened:
            conversation.reopen(given_home, "q-moot")
            reopened.append("q-moot")
        return real(given_home, manifest)

    monkeypatch.setattr(overseer_run, "_record_defaults", reopen_mid_run)
    _run(home)

    assert reopened == ["q-moot"]
    assert _row(home, "q-moot") is not None
    assert _row(home, "q-moot")["needs"] == "user"


# ------------------------------------------------- 12. attention_effects


def test_the_overseer_manifest_records_an_attention_effect_for_a_hook_it_turned_on(
    tmp_path, monkeypatch,
):
    """Mutation checked: writing `hook_activated: false` always (the
    `hook_activation=gate` argument replaced by False) fails this test."""
    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked)
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_bytes(b'{"existing": true}\n')
    _silence_notifications(monkeypatch)
    (home / "config.yaml").write_text("overseer:\n  hook_activation: true\n", encoding="utf-8")
    commit_all(home, "enable hook activation")

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "applied", result
    manifest = json.loads((home / "cases" / "runs" / f"{result.run}.json").read_text("utf-8"))
    (row,) = manifest["attention_effects"]
    assert (row["lesson"], row["verb"], row["destination"]) == (rid, "route", "hook")
    assert row["hook_activated"] is True
    assert row["always_loaded"] is False
    assert manifest["ledger_effects"] == [] or all(
        "lesson" not in effect for effect in manifest["ledger_effects"]
    )  # never mixed into the crash-recovery proof list
    assert not hasattr(overseer_run, "_always_loaded_user_scope")
    kinds = {item["kind"] for item in attention.read(home)["items"]}
    assert "decided.hook-activated" in kinds


# ------------------------------------------------- 13. the reading correction line


def test_the_reading_correction_line_points_at_the_inbox_and_an_agents_relay():
    line = overseer_run.READING_CORRECTION_LINE
    assert "open it in your inbox (the tray icon)" in line
    assert "--recorded-by agent" in line
    assert "--recorded-by human" not in line


# ------------------------------------------------- fix round 1 (gate r1)


def _outcome(q_id: str, result: str, at: datetime) -> dict:
    return {
        "id": "out-0000aaaa", "at": _iso(at), "item": attention.item_id("approved.pending", q_id),
        "subject": q_id, "result": result, "note": "done by the agent", "session": None,
        "by": "agent",
    }


def test_an_approved_or_click_answered_id_is_never_asked_again(tmp_path, monkeypatch):
    """Gate r1 BLOCKER 1: re-asking an approved ask's id must not move the
    user's approval onto a plan they never saw. Mutation checked: passing
    no `reask` to `_questions` in `_run` fails the "dropped —" lines (the
    finalize's own check still keeps the index, with its other wording)."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    asked = _iso(NOW - timedelta(days=20))
    approved = _system_ask("q-appr", [case_id], default=conversation.SYSTEM_DEFAULT,
                           asked_at=asked, system=True)
    approved["plan"]["sudo"] = False
    done = _system_ask("q-done", [case_id], default=conversation.SYSTEM_DEFAULT,
                       asked_at=asked, system=True)
    done["plan"]["sudo"] = False
    declined = _user_ask("q-declined", [case_id], default=conversation.NEEDS_USER_DEFAULTS["sudo"],
                         asked_at=asked)
    still_open = _user_ask("q-open", [case_id], default=conversation.NEEDS_USER_DEFAULTS["sudo"],
                           asked_at=asked)
    _hand_index(home, [approved, done, declined, still_open])
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-appr", "opt-yes", "approve", NOW - timedelta(days=10), label="Yes, add it"),
        _choice("q-done", "opt-yes", "approve", NOW - timedelta(days=9), label="Yes, add it",
                cid="chc-0000bbbb"),
        _choice("q-declined", "opt-not-now", "decline", NOW - timedelta(days=8), label="No",
                cid="chc-0000cccc"),
    ])
    _write_jsonl(home, "outcomes.jsonl", [_outcome("q-done", "done", NOW - timedelta(days=3))])
    state = _phases(monkeypatch)
    rewritten = {**_plan(), "summary": "DELETE the user's dotfiles instead."}
    state["questions"] = [
        _system_ask("q-appr", [case_id], plan=dict(rewritten)),
        _system_ask("q-done", [case_id], plan=dict(rewritten)),
        _user_ask("q-declined", [case_id], text="Run the sudo step after all? Yes runs it."),
        _user_ask("q-open", [case_id], text="Will you run the udev step this week? Yes runs it."),
    ]

    _run(home, first=True)

    index = {row["id"]: row for row in _index(home)}
    # Control: a still-open ask re-asked takes the new words, keeps asked_at.
    assert index["q-open"]["text"] == "Will you run the udev step this week? Yes runs it."
    assert index["q-open"]["asked_at"] == asked
    # The approved and the done asks are kept exactly as they were.
    for q_id in ("q-appr", "q-done"):
        assert index[q_id]["plan"]["summary"] == _plan()["summary"], q_id
        assert index[q_id]["asked_at"] == asked
    assert "q-declined" not in index
    refused = _refused_block(home)
    assert f"question q-appr: dropped — {overseer_run.REASK_APPROVED}" in refused
    assert f"question q-done: dropped — {overseer_run.REASK_DONE}" in refused
    assert f"question q-declined: dropped — {overseer_run.REASK_CHOSEN}" in refused
    assert "question q-open: dropped" not in refused


def test_an_approval_clicked_while_a_run_is_in_progress_keeps_its_plan(tmp_path, monkeypatch):
    """Gate r1 BLOCKER 1, the finalize's own check under its lock. Mutation
    checked: removing the `reask` drop in `_carry_forward` fails this test
    (the re-emitted row's plan replaces the approved one)."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [_system_ask("q-net", [case_id])]
    _run(home, first=True)
    original = _row(home, "q-net")["plan"]["summary"]  # control
    state["questions"] = [
        _system_ask("q-net", [case_id], plan={**_plan(), "summary": "A different plan."}),
    ]
    real = overseer_run._record_defaults
    clicked: list[str] = []

    def approve_mid_run(given_home, manifest):
        if not clicked:
            _write_jsonl(given_home, "choices.jsonl", [
                _choice("q-net", "opt-yes", "approve", datetime.now(timezone.utc),
                        label="Yes, add it"),
            ])
            clicked.append("q-net")
        return real(given_home, manifest)

    monkeypatch.setattr(overseer_run, "_record_defaults", approve_mid_run)
    _run(home)

    assert clicked == ["q-net"]
    assert _row(home, "q-net")["plan"]["summary"] == original
    assert (
        f"question q-net: dropped at publish -- {overseer_run.REASK_APPROVED}"
        in _refused_block(home)
    )


def test_a_needs_user_ask_offers_options_and_a_recommendation(tmp_path):
    """Gate r1 MAJOR 2 (answer 10). Mutation checked: making options
    optional again (the `not options` check in `_r2_ask` removed) fails the
    conflict and sudo assertions."""
    home = make_home(tmp_path)
    a = _statement(home, "Never tell me X is waiting on you.", 1)
    b = _statement(home, "Legit things that need my attention are fine.", 2)
    case_id = "case-12345678"
    host = str(tmp_path / "newhost")
    register_text = (
        f"Register {host} as a canon host in git mode? Yes registers it; no leaves it unregistered."
    )
    conflict = {"because": "conflict", "text": "Which of your two statements wins? Pick one.",
                "statements": [a, b]}
    keep = [{"id": "opt-newer", "label": "Keep the newer one", "effect": "other"},
            {"id": "opt-older", "label": "Keep the older one", "effect": "other"}]
    register_options = [{"id": "opt-register", "label": "Register it", "effect": "register"},
                        {"id": "opt-no", "label": "No", "effect": "decline"}]
    index, dropped = _validate(tmp_path, [
        _user_ask("q-conflict-bare", [case_id], options=None, **conflict),
        _user_ask("q-sudo-no-recommend", [case_id], recommend=None),
        _user_ask("q-conflict", [case_id], options=keep, **conflict),
        _user_ask("q-register-no-register", [case_id], because="foreign-history",
                  text=register_text, register={"path": host, "mode": "git"}),
        _user_ask("q-register", [case_id], because="foreign-history", text=register_text,
                  register={"path": host, "mode": "git"}, options=register_options),
        _user_ask("q-stead-bare", [case_id], needs="stead", because=None, options=None,
                  default=DEFAULT),
    ], {case_id}, known_statements={a, b})

    assert _ids(index) == ["q-conflict", "q-register", "q-stead-bare"]  # controls
    assert index["questions"][0]["recommend"]["option"] == "opt-newer"
    wanted = {
        "q-conflict-bare": "a needs: user ask offers 2 to 4 options",
        "q-sudo-no-recommend": "a needs: user ask recommends one of its options",
        "q-register-no-register": "an ask with register offers at least one register and one "
                                  "decline option",
    }
    for q_id, why in wanted.items():
        assert any(line.startswith(f"question {q_id}: dropped — {why}") for line in dropped), (
            q_id, dropped,
        )


def test_reopening_a_withdrawn_approval_brings_back_a_question(tmp_path):
    """Gate r1 MINOR 4: "Ask me anyway" on a withdrawn approval asks again;
    the old approve click no longer stands. Mutation checked:
    `_answer_floor` ignoring `reopened_at` fails this test."""
    home = make_home(tmp_path)
    case_id = "case-12345678"
    asked = _iso(NOW - timedelta(days=20))
    row = _system_ask("q-appr", [case_id], default=conversation.SYSTEM_DEFAULT,
                      asked_at=asked, system=True)
    row["plan"]["sudo"] = False
    _hand_index(home, [])
    (home / "overseer" / "withdrawn.yaml").write_text(
        overseer_run._yaml_text({"withdrawn": [{
            "id": "q-appr", "text": row["text"], "because": "system-change", "cases": [case_id],
            "asked_at": asked, "withdrawn_at": _iso(NOW - timedelta(days=2)), "run": "abcd1234",
            "why": "moot", "row": row,
        }]}),
        encoding="utf-8",
    )
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-appr", "opt-yes", "approve", NOW - timedelta(days=10), label="Yes, add it"),
    ])

    back = conversation.reopen(home, "q-appr")

    assert back["asked_at"] == asked and back.get("reopened_at")
    indexed = _row(home, "q-appr")
    assert indexed["reopened_at"] == back["reopened_at"]
    assert conversation._answered_ids(home, {"q-appr"}) == set()
    assert conversation.open_question_count(home) == 1
    floor = conversation._answer_floor(conversation._load_questions(home)[0], None)
    track = conversation.approval_track(
        indexed, conversation.choice_rows(home), [], since=floor,
    )
    assert track.state == "open"
    # A new approve click after the reopen is a new approval.
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-appr", "opt-yes", "approve", NOW - timedelta(days=10), label="Yes, add it"),
        _choice("q-appr", "opt-yes", "approve", datetime.now(timezone.utc) + timedelta(seconds=2),
                label="Yes, add it", cid="chc-0000dddd"),
    ])
    assert conversation._answered_ids(home, {"q-appr"}) == {"q-appr"}


def test_the_report_names_only_the_withdrawals_the_finalize_applied(tmp_path, monkeypatch):
    """Gate r1 MINOR 6. Mutation checked: `_default_lines` reading the
    model's `manifest["withdraw"]` again fails this test."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [_user_ask("q-answered-meanwhile", [case_id]), _user_ask(
        "q-moot-upstream", [case_id], because="foreign-history",
        text="Push the fix upstream? Yes pushes; no keeps it local.",
    )]
    _run(home, first=True)
    state["questions"] = []
    state["withdraw"] = [{"id": "q-answered-meanwhile", "why": "it stopped mattering."},
                         {"id": "q-moot-upstream", "why": "the upstream was archived."}]
    real = overseer_run._record_defaults
    answered: list[str] = []

    def answer_mid_run(given_home, manifest):
        if not answered:
            statements.add(
                given_home, verbatim="I ran it.", recorded_by="human",
                source={"message_ref": "conversation:obs-0000ef01", "surface": "conversation"},
                answers={"kind": "question", "ref": "q-answered-meanwhile", "text": None},
            )
            answered.append("q-answered-meanwhile")
        return real(given_home, manifest)

    monkeypatch.setattr(overseer_run, "_record_defaults", answer_mid_run)
    _run(home)

    decided = _decided_block(home)
    assert "q-moot-upstream withdrawn: I stopped asking because the upstream was archived." in decided  # control
    assert "q-answered-meanwhile withdrawn" not in decided
    assert "withdraw q-answered-meanwhile: not applied" in _refused_block(home)
    assert [row["id"] for row in _withdrawn(home)] == ["q-moot-upstream"]


def test_the_backstop_spares_an_ask_withdrawn_more_than_90_days_ago(tmp_path):
    """Gate r1 NIT 9. Mutation checked: the backstop ignoring its window
    (`WITHDRAWN_BACKSTOP_DAYS` never consulted) fails the 91-day case."""
    case_id = "case-12345678"
    now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)

    def gone(days: int) -> list[dict]:
        return [{"id": "q-before", "because": "sudo", "cases": [case_id],
                 "withdrawn_at": _iso(now - timedelta(days=days))}]

    index, dropped = _validate(tmp_path, [_user_ask("q-again", [case_id])], {case_id},
                               withdrawn=gone(89), now=_iso(now))
    assert _ids(index) == [] and any("asks again, in other words" in d for d in dropped)  # control
    index, dropped = _validate(tmp_path, [_user_ask("q-again", [case_id])], {case_id},
                               withdrawn=gone(91), now=_iso(now))
    assert _ids(index) == ["q-again"], dropped


def test_choices_left_out_of_phase_b_for_a_secret_are_named(tmp_path, monkeypatch):
    """Gate r1 NIT 8. Mutation checked: removing the note in
    `_full_inputs` fails this test."""
    home = make_home(tmp_path)
    _rid, _case_id = _deferred_case(home, tmp_path)
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-gone", "opt-yes", "approve", NOW - timedelta(days=1), label=f"use {token}"),
    ])
    state = _phases(monkeypatch)
    _run(home, first=True)
    answers = YAML(typ="safe").load(state["b_stage"]["answers.yaml"])
    assert "choices" not in answers  # the fallback ran
    assert "answers.yaml: the user's option choices and feedback clicks were left out" in (
        _refused_block(home)
    )


# ------------------------------------------------- fix round 2 (gate r2)


def _withdraw_by_hand(home: Path, row: dict, case_id: str, *, because: str) -> None:
    """*row* withdrawn two days ago, as the finalize writes it."""
    _hand_index(home, [])
    (home / "overseer" / "withdrawn.yaml").write_text(
        overseer_run._yaml_text({"withdrawn": [{
            "id": row["id"], "text": row["text"], "because": because, "cases": [case_id],
            "asked_at": row["asked_at"], "withdrawn_at": _iso(NOW - timedelta(days=2)),
            "run": "abcd1234", "why": "moot", "row": row,
        }]}),
        encoding="utf-8",
    )
    commit_all(home, "fixture withdrawn")


def test_a_reopened_approval_is_never_re_asked_with_a_new_plan(tmp_path, monkeypatch):
    """Gate r2 BLOCKER 1: after "Ask me anyway" on a withdrawn approval, the
    inbox (which counts every click on the id) still shows the old approve
    click, so the same id re-asked with a new plan would put that click
    behind the new plan. Mutation checked: removing the unfloored
    `approval_track` check in `_reask_problems` (the reopened ask goes to
    `still_open` again) fails this test: the new plan is indexed."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    row = _system_ask("q-appr", [case_id], default=conversation.SYSTEM_DEFAULT,
                      asked_at=_iso(NOW - timedelta(days=20)), system=True)
    row["plan"]["sudo"] = False
    _withdraw_by_hand(home, row, case_id, because="system-change")
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-appr", "opt-yes", "approve", NOW - timedelta(days=10), label="Yes, add it"),
    ])
    back = conversation.reopen(home, "q-appr")
    # Control: the reopen made it a question again on this lane's walk.
    assert conversation._answered_ids(home, {"q-appr"}) == set()
    state = _phases(monkeypatch)
    state["questions"] = [_system_ask(
        "q-appr", [case_id], plan={**_plan(), "summary": "DELETE the user's dotfiles instead."},
    )]

    _run(home, first=True)

    kept = _row(home, "q-appr")
    assert kept is not None and kept["plan"]["summary"] == _plan()["summary"]
    assert kept["reopened_at"] == back["reopened_at"]
    assert f"question q-appr: dropped — {overseer_run.REASK_REOPENED}" in _refused_block(home)
    # Phase B was told the ask is fixed, with why.
    staged = YAML(typ="safe").load(state["b_stage"]["open-asks.yaml"])
    entry = next(entry for entry in staged["asks"] if entry["id"] == "q-appr")
    assert (entry["kind"], entry["fixed"]) == ("ask", overseer_run.REASK_REOPENED)


def test_a_system_or_register_ask_without_needs_is_held_to_the_needs_user_rules(tmp_path):
    """Gate r2 MAJOR 2 (answer 10): an ask the model wrote with `system:
    true` or `register` but no `needs` is read as `needs: user` (§3.8) and
    validated as one, so it never reaches the user as a page with nothing
    to click. Mutation checked: restoring the legacy fall-through (the
    inference block in `_questions` removed) fails this test: the bare
    asks are indexed with no options."""
    case_id = "case-12345678"
    host = str(tmp_path / "newhost")
    register_text = (
        f"Register {host} as a canon host in git mode? Yes registers it; no leaves it unregistered."
    )
    bare_system = {
        "id": "q-bare-system", "kind": "ask", "cases": [case_id], "system": True,
        "text": "Bind the daemon to the bus? Yes adds a drop-in; no keeps the note.",
        "why": "it changes your desktop",
    }
    bare_register = {
        "id": "q-bare-register", "kind": "ask", "cases": [case_id], "text": register_text,
        "why": "decides whether its lessons can be routed there",
        "register": {"path": host, "mode": "git"},
    }
    full_system = {
        **bare_system, "id": "q-full-system", "options": [dict(o) for o in OPTIONS],
        "recommend": {"option": "opt-no", "reasoning": "the note works"}, "plan": _plan(),
    }
    index, dropped = _validate(tmp_path, [bare_system, bare_register, full_system], {case_id})

    assert _ids(index) == ["q-full-system"]  # control: a complete one is kept
    row = index["questions"][0]
    assert (row["needs"], row["because"], row["system"]) == ("user", "system-change", True)
    assert row["default"] == conversation.SYSTEM_DEFAULT and row["options"] and row["plan"]
    assert "question q-bare-system: dropped — a system-change ask needs a plan" in dropped
    assert any(
        line.startswith("question q-bare-register: dropped — a needs: user ask offers 2 to 4 options")
        for line in dropped
    ), dropped


def test_a_re_emitted_reopened_ask_keeps_its_reopen_floor(tmp_path, monkeypatch):
    """Gate r2 MINOR 3. An ask without a plan, answered by a choice before it
    was withdrawn, is reopened and then asked again in new words: the
    re-emitted row keeps `reopened_at`, so the old choice still does not
    answer it. Mutation checked: not carrying `reopened_at` onto the
    re-emitted row in `_carry_forward` fails this test."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    asked = _iso(NOW - timedelta(days=20))
    row = _user_ask("q-word", [case_id], default=conversation.NEEDS_USER_DEFAULTS["sudo"],
                    asked_at=asked)
    _withdraw_by_hand(home, row, case_id, because="sudo")
    _write_jsonl(home, "choices.jsonl", [
        _choice("q-word", "opt-ran", "approve", NOW - timedelta(days=10), label="I'll run it"),
    ])
    back = conversation.reopen(home, "q-word")
    assert conversation._answered_ids(home, {"q-word"}) == set()  # control
    state = _phases(monkeypatch)
    new_text = "Will you run the udev step this week? Yes runs it; no leaves it."
    state["questions"] = [_user_ask("q-word", [case_id], text=new_text)]

    _run(home, first=True)

    indexed = _row(home, "q-word")
    assert indexed is not None and indexed["text"] == new_text
    assert (indexed["asked_at"], indexed["reopened_at"]) == (asked, back["reopened_at"])
    assert conversation._answered_ids(home, {"q-word"}) == set()
    assert conversation.open_question_count(home) == 1


def test_a_re_ask_dropped_at_publish_is_not_reported_as_needing_the_user(tmp_path, monkeypatch):
    """Gate r2 NIT 4. Mutation checked: `_default_lines` ignoring
    `dropped` fails this test (the dropped re-ask keeps its line)."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [_system_ask("q-net", [case_id])]
    _run(home, first=True)
    line = f"- q-net would change your system: {conversation.SYSTEM_DEFAULT}"
    assert line in _decided_block(home).splitlines()  # control: the first run lists it
    state["questions"] = [
        _system_ask("q-net", [case_id], plan={**_plan(), "summary": "A different plan."}),
    ]
    real = overseer_run._record_defaults
    clicked: list[str] = []

    def approve_mid_run(given_home, manifest):
        if not clicked:
            _write_jsonl(given_home, "choices.jsonl", [
                _choice("q-net", "opt-yes", "approve", datetime.now(timezone.utc),
                        label="Yes, add it"),
            ])
            clicked.append("q-net")
        return real(given_home, manifest)

    monkeypatch.setattr(overseer_run, "_record_defaults", approve_mid_run)
    _run(home)

    assert "question q-net: dropped at publish" in _refused_block(home)  # control
    assert line not in _decided_block(home).splitlines()


def test_a_question_naming_ledger_ids_is_kept_and_named(tmp_path):
    """Gate r2 NIT 5 (§2.1 item 2: "one sentence, with no ids in it").
    Mutation checked: `_ids_in_text_note` answering nothing fails this
    test."""
    case_id = "case-12345678"
    index, dropped = _validate(tmp_path, [
        _user_ask("q-clean", [case_id]),
        _user_ask("q-ids", [case_id], text="Should lrn-1a2b3c4d move per case-12345678? Yes moves it."),
    ], {case_id})

    assert _ids(index) == ["q-clean", "q-ids"]  # both kept
    assert dropped == [
        "question q-ids: its question names case-12345678, lrn-1a2b3c4d -- a question is one "
        "plain sentence; the ids belong in its cases and statements, which the inbox shows "
        "beside it"
    ]
