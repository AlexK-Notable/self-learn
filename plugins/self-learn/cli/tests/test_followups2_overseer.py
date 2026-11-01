"""Follow-ups 2 of the attention round (2026-11-01; S-129),
item 4: the overseer-asks gate r3 NITs.

- A `because` the model wrote on a `system: true` ask without `needs` is
  kept when it is one of the closed list; only a missing or invalid one is
  inferred (NIT 2a).
- The note on a kept ask whose wording names ledger ids is published under
  "Questions for you", beside the question, never under "Refused / could
  not do" (NIT 2b); S-117's stead path names it too (NIT 1, pinned in
  `test_overseer_asks_needs.test_a_question_naming_ledger_ids_is_kept_and_named`).

Each test names the mutation it was checked against.
"""

from __future__ import annotations

from datetime import datetime, timezone

from self_learn.overseer import conversation
from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_answered_questions import _deferred_case
from test_overseer_asks_needs import (  # noqa: F401 -- `redirect` is an autouse fixture
    SUDO_OPTIONS,
    _choice,
    _ids,
    _plan,
    _row,
    _system_ask,
    _write_jsonl,
    _phases,
    _refused_block,
    _run,
    _user_ask,
    _validate,
    redirect,
)


def test_a_valid_because_the_model_wrote_is_kept_when_needs_is_inferred(tmp_path):
    """Mutation: the inference always writes `system-change` (the old
    rule) -> red (the ask is dropped for a missing plan)."""
    case_id = "case-12345678"
    sudo = {k: v for k, v in _user_ask("q-sudo", [case_id]).items() if k != "needs"}
    sudo["system"] = True
    invalid = {**sudo, "id": "q-invalid", "because": "credentials"}

    index, dropped = _validate(tmp_path, [sudo, invalid], {case_id})

    assert _ids(index) == ["q-sudo"]
    row = index["questions"][0]
    assert (row["needs"], row["because"]) == ("user", "sudo")
    assert row["default"] == conversation.NEEDS_USER_DEFAULTS["sudo"]
    assert [o["id"] for o in row["options"]] == [o["id"] for o in SUDO_OPTIONS]
    # Control: an invalid `because` is still inferred as system-change, and
    # then held to that kind's rules (a plan).
    assert "question q-invalid: dropped — a system-change ask needs a plan" in dropped


def test_a_kept_asks_wording_note_is_published_beside_the_questions(tmp_path, monkeypatch):
    """Mutations: the run passes no `notes_out` to `_questions` -> red (the
    note lands under "Refused / could not do"); the finalize drops
    `question_notes` -> red (the note is nowhere)."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [
        _user_ask("q-ids", [case_id], text=f"Should {case_id} be read again? Yes reads it; no leaves it."),
    ]

    _run(home, first=True)

    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    questions = report.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert f"- question q-ids (kept, and asked as written): its question names {case_id}" in questions
    assert "q-ids" not in _refused_block(home)
    assert [row["id"] for row in conversation._load_questions(home)] == ["q-ids"]  # noqa: SLF001


def test_finalize_puts_question_notes_last_under_questions_for_you(tmp_path):
    path = tmp_path / "report.md"
    headings = ["Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do"]
    body = {h: "- none" for h in headings}
    body["Questions for you"] = "- q-a: a question"
    path.write_text("# draft\n" + "\n".join(f"## {h}\n{body[h]}\n" for h in headings),
                    encoding="utf-8")

    text = overseer_run._finalize_model_report(  # noqa: SLF001
        path, date="2026-11-01", run_id="12345678", model="m", selected=(),
        population_count=0, excluded=0, model_calls=1, guard=50, refusals=[],
        question_notes=["question q-a (kept, and asked as written): its question names lrn-1a2b3c4d"],
    )

    questions = text.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert questions.splitlines()[:2] == [
        "- q-a: a question",
        "- question q-a (kept, and asked as written): its question names lrn-1a2b3c4d",
    ]
    assert "lrn-1a2b3c4d" not in text.split("## Refused / could not do\n", 1)[1]


def test_no_kept_note_for_an_ask_dropped_at_publish(tmp_path, monkeypatch):
    """Gate r1 F4: an ask whose wording names an id but which the finalize
    drops at publish (here: the user approved its plan while the run was
    in progress) gets no "(kept, and asked as written)" line, only its
    drop. Mutation: the finalize publishes every wording note unfiltered
    -> red."""
    home = make_home(tmp_path)
    _rid, case_id = _deferred_case(home, tmp_path)
    state = _phases(monkeypatch)
    state["questions"] = [_system_ask("q-net", [case_id])]
    _run(home, first=True)
    text = f"Bind the daemon per {case_id}? Yes adds a drop-in; no keeps the note."
    state["questions"] = [
        _system_ask("q-net", [case_id], text=text, plan={**_plan(), "summary": "Another plan."}),
        _system_ask("q-other", [case_id], text=text),
    ]
    real = overseer_run._record_defaults
    clicked: list[str] = []

    def approve_mid_run(given_home, manifest):
        if not clicked:
            _write_jsonl(given_home, "choices.jsonl", [
                _choice("q-net", "opt-yes", "approve", datetime.now(timezone.utc), label="Yes"),
            ])
            clicked.append("q-net")
        return real(given_home, manifest)

    monkeypatch.setattr(overseer_run, "_record_defaults", approve_mid_run)
    _run(home)

    assert "question q-net: dropped at publish" in _refused_block(home)  # control
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    questions = report.split("## Questions for you\n", 1)[1].split("\n## ", 1)[0]
    assert "- question q-other (kept, and asked as written)" in questions  # control: notes publish
    assert "question q-net (kept" not in report
    assert _row(home, "q-other") is not None


def test_published_question_notes_keep_only_indexed_asks():
    lines = ["question q-a (kept, and asked as written): x", "question q-b (kept, and asked as written): y"]
    assert overseer_run._published_question_notes(lines, published=True, dropped={"q-b"}) == [lines[0]]
    assert overseer_run._published_question_notes(lines, published=True, dropped=set()) == lines
    assert overseer_run._published_question_notes(lines, published=False, dropped=set()) == []


def test_no_kept_note_on_a_run_that_halted(tmp_path, monkeypatch):
    """Gate r2 R2-3, N11: a run that halts unfinished indexes none of its
    asks, so its report carries no "(kept, and asked as written)" line,
    although the note was made (the manifest keeps it for a resume).
    Mutation: the finalize call site passes `published=True` -> red."""
    from self_learn import execution_evidence
    from test_overseer_run import (
        _dispatch_scripted,
        _dump,
        _enabled,
        _fake_hook_phases,
        _seed_parked_hook,
        _silence_notifications,
    )

    home = make_home(tmp_path)
    rid, parked = _seed_parked_hook(home, tmp_path)
    _enabled(monkeypatch)
    _fake_hook_phases(monkeypatch, rid, parked, extra_apply_refusal=True)
    _silence_notifications(monkeypatch)
    inner = overseer_run.invocation.write_session

    def with_a_question(spec):
        outcome = inner(spec)
        if (spec.cwd / "sheet-hook.yaml").exists():  # phase B's stage
            _dump(spec.cwd / "questions.yaml", {"questions": [
                _user_ask("q-ids", [parked], text=f"Should {parked} be read again? Yes reads it."),
            ]})
        return outcome

    monkeypatch.setattr(overseer_run.invocation, "write_session", with_a_question)
    _dispatch_scripted(monkeypatch, {1: (1, "target-busy"), 2: (6, None)})

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status == "partial"  # control: the run halted
    manifest = execution_evidence.read_manifest(home, result.run)
    assert any(line.startswith("question q-ids (kept") for line in manifest["question_notes"])  # control
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "## Questions for you" in report  # control: the report was published
    assert "(kept, and asked as written)" not in report
    assert [row["id"] for row in conversation._load_questions(home)] == []  # noqa: SLF001
