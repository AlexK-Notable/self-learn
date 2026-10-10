"""S-81 (2026-10-08): a lesson the overseer holds is the overseer's alone.

The user's words, 2026-10-08: "if there's a lesson with something that
needs to be adjudicated by the overseer then it shouldn't be further meddled
with by the steward, excpet in a fact finding capacity. it can add notes for
the overseer if it wants to, but it can't transform the lesson in any way
until the overseer gives the metaphorical okay."

Two blind reviews found one defect along many paths: a lesson parked for the
overseer at its reconsider input's `observation:` version stayed selectable
at its record's version, so the steward decided it again the next night
while its parked case waited for the overseer (gate S1 D1; gate S1b F1, F2,
F4, F5). The fix is at selection: a lesson an open parked case names
(`cases.held_lessons`, the overseer's own queue) is selected for no
decision, and a sheet line on one is refused, until the overseer's decision
supersedes the case. The steward may add a note to the case.

Also pinned here: the prepare-stage secret scan's refusal carries its S-71
kind (gate S1b F6), the runner's `supersedes` fill (F2, F3), and the parked
case's text when the steward's case never reached the ledger (nit c).

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real ``~/.self-learn``) with fake model sessions that
write the stage files; the runner does the rest for real. No real model
call; ids and texts are synthetic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import cases, ledger_ops, serve, statements, steward, steward_prompt, verbs
from self_learn.invocation.contract import Outcome
from support import make_env
from test_steward import (
    _dump_yaml,
    _enable_steward,
    _head_manifest,
    _stage_dir,
    _transport_failure,
    _write_decision_stage,
)
from test_steward_refusals import _REPAIR_HEADER, _case, _notifications, _seed
from test_steward_repair_catches import (
    MovedPair,
    _decide_pair,
    _ids,
    _overseer_decides,
    _packet,
    _pair_session,
    _status,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_NO_DEPS = {"statements": [], "user_model": [], "conditions": [], "capabilities": []}
_HEADING_BECAUSE = "fine first line\n## Decision\n- verb: reject"


def _ok() -> Outcome:
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


def _open_parked(home: Path, rid: str) -> list[dict]:
    return [row for row in cases.list_cases(home, record_id=rid, parked_for="overseer")
            if not row.get("superseded_by")]


def _eligible(home: Path) -> dict[str, str]:
    return {entry.record.id: row["version"] for entry, row in steward._eligible_lessons(home)}


def _parked_by_hand(home: Path, rids: list[str], tmp: Path, reason: str = "authority-unclear") -> str:
    """A parked case for *rids*, written straight through the case writer --
    a lesson parked by anyone is held alike."""
    stage = tmp / f"parked-{'-'.join(rids)}.yaml"
    case = _case(list(rids), "parked", "defer")
    case.update(kind="parked", parked_for="overseer", parked_reason=reason)
    case["decision"]["confidence"] = "provisional"
    _dump_yaml(stage, case)
    return cases.record(home, stage, actor="steward")


# ------------------------------------- 1. every parking path holds the lesson


def _path_f1_case_writer_refusal(tmp_path, monkeypatch):
    """Gate S1b F1: the case writer refuses the case over two pending
    reconsider inputs (a heading line in `because`, kept through the
    repair): `unclassified`, parked now at the `observation:` version."""
    pair = MovedPair(tmp_path, observed=True, prefix="lrn-d1a0")

    def write(spec):
        stage = _stage_dir(spec)
        case = _decide_pair(pair, kind="resolution")
        case["decision"]["because"] = _HEADING_BECAUSE
        _dump_yaml(stage / "cases" / "moved-pair.yaml", case)
        _dump_yaml(stage / "sheets" / "moved-pair.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "reject"} for rid in pair.ids],
        })
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    steward.run(pair.home)
    return pair.home, list(pair.ids), pair


def _path_f2_superseded_predecessor(tmp_path, monkeypatch):
    """Gate S1b F2's refusal: attempt 1 decides X alone (its case takes the
    predecessor); attempt 2's case for Y names the same predecessor -- the
    runner no longer fills it in (pinned below), so the model writes it --
    and the case writer refuses it: already superseded. Y is parked now at
    its `observation:` version."""
    pair = MovedPair(tmp_path, observed=True, prefix="lrn-d2a0")
    x, y = pair.ids
    calls: list[list[str]] = []

    def write(spec):
        brief = _ids(spec.prompt)
        calls.append(brief)
        target = y if len(calls) > 2 else x
        stage = _stage_dir(spec)
        case = _case([target], "reject", "reject", scope="user")
        case["evidence"] = [{"ref": pair.statement, "quote": "near the code"}]
        case["dependencies"] = {**_NO_DEPS, "statements": [pair.statement]}
        if target == y:
            case["supersedes"] = pair.moving_case
        _dump_yaml(stage / "cases" / f"one-{target}.yaml", case)
        _dump_yaml(stage / "sheets" / f"one-{target}.yaml", {
            "version": 1, "case": "$CASE_ID", "items": [{"id": target, "verb": "reject"}],
        })
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    first = steward.run(pair.home)
    assert _packet(pair.home, first.run_id)["dispositions"][x]["state"] == "applied"  # control
    steward.run(pair.home)
    assert len(calls) == 3 and calls[2] == [y]  # control: attempt 2 decided Y alone
    return pair.home, [y], pair


def _path_f4_deferred(tmp_path, monkeypatch):
    """Gate S1b F4: a DEFERRED lesson back as a reconsider input, its line
    bad (`bad-line`): sent back would be decided by no one -- the queue
    hides it until its date -- so it is parked now. The date then passes."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-d4a00001")
    st = statements.add(home, verbatim="Later.", source={"message_ref": "transcript:defer#L1"},
                        recorded_by="human")
    stage = tmp_path / "deferring-case.yaml"
    deferring = _case([rid], "defer", "defer")
    deferring.update(dependencies={**_NO_DEPS, "statements": [st]},
                     evidence=[{"ref": st, "quote": "Later"}])
    _dump_yaml(stage, deferring)
    prior = cases.record(home, stage, actor="steward")
    until = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    verbs.defer(home, rid, until=until, by="steward", no_push=True)
    cases.observe(home, prior, "statement", text="more on deferral", ref=st, by="steward")
    _enable_steward(home)

    def write(spec):
        out = _stage_dir(spec)
        case = _case([rid], "route", "route")
        case.update(kind="reconsider", trigger="reconsider",
                    dependencies={**_NO_DEPS, "statements": [st]},
                    evidence=[{"ref": st, "quote": "Later"}])
        _dump_yaml(out / "cases" / f"{rid}.yaml", case)
        _dump_yaml(out / "sheets" / f"{rid}.yaml", {"version": 1, "case": "$CASE_ID", "items": [
            {"id": rid, "verb": "route", "dest": "claude-md:bogus"}]})
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    steward.run(home)
    lapse = datetime.now(timezone.utc) + timedelta(days=60)
    monkeypatch.setattr(ledger_ops, "_now", lambda now=None: now if now is not None else lapse)
    return home, [rid], None


def _path_f5_park_kind(tmp_path, monkeypatch):
    """Gate S1b F5 (probe p2): a line whose preview kind parks
    (`route dest: new-skill`, `unclassified`) on two pending reconsider
    inputs: parked now at their `observation:` version."""
    pair = MovedPair(tmp_path, observed=True, prefix="lrn-d5a0")

    def write(spec):
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / "moved-pair.yaml",
                   _decide_pair(pair, kind="resolution", verb="route"))
        _dump_yaml(stage / "sheets" / "moved-pair.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "route", "dest": "new-skill"} for rid in pair.ids],
        })
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    steward.run(pair.home)
    return pair.home, list(pair.ids), pair


def _path_f5_attempt_cap(tmp_path, monkeypatch):
    """Gate S1b F5 (probe n5): the model call fails three nights running;
    the close-out parks both pending reconsider inputs `attempts-exhausted`
    at their `observation:` version."""
    pair = MovedPair(tmp_path, observed=True, prefix="lrn-d6a0")
    monkeypatch.setattr(steward.invocation, "write_session", _transport_failure)
    for _night in range(3):
        steward.run(pair.home)
    return pair.home, list(pair.ids), pair


def _path_d1_reconsider_refusal(tmp_path, monkeypatch):
    """Round 1's D1: a `kind: reconsider` case over two pending reconsider
    inputs, kept through the repair, refused (`status`, the steward's own
    line). Since bf6c8d1 such a lesson is sent back when the next run
    selects it; this drives the park-now that 484653f did for it (and does
    still for one the next run would not select), by answering "not
    selected again" here -- the rule must hold whichever way it parks."""
    pair = MovedPair(tmp_path, observed=True, prefix="lrn-d7a0")
    monkeypatch.setattr(steward.invocation, "write_session",
                        _pair_session(pair, "reconsider", "reconsider", []))
    real = steward._selected_again
    monkeypatch.setattr(steward, "_selected_again", lambda home, rid: False)
    steward.run(pair.home)
    monkeypatch.setattr(steward, "_selected_again", real)
    return pair.home, list(pair.ids), pair


_PATHS = {
    "f1-case-writer-refusal": _path_f1_case_writer_refusal,
    "f2-superseded-predecessor": _path_f2_superseded_predecessor,
    "f4-deferred-then-due": _path_f4_deferred,
    "f5-park-kind": _path_f5_park_kind,
    "f5-attempt-cap": _path_f5_attempt_cap,
    "d1-reconsider-refusal": _path_d1_reconsider_refusal,
}


@pytest.mark.parametrize("path", sorted(_PATHS))
def test_every_parking_path_holds_the_lesson_until_the_overseer_decides(
    tmp_path, monkeypatch, path
):
    """Each known path parks a pending lesson at its reconsider input's
    `observation:` version, which leaves the lesson's own version
    undecided -- the shape that gave a lesson two deciders. For each:
    while its parked case is open the lesson is not selected (as a lesson,
    a reconsider input after a fresh observation, or by a steward run that
    would decide everything it is handed); once the overseer's decision
    supersedes the case, it is selected again."""
    _notifications(monkeypatch)
    home, subjects, pair = _PATHS[path](tmp_path, monkeypatch)

    parked: dict[str, str] = {}
    for rid in subjects:
        (open_case,) = _open_parked(home, rid)  # positive control: the path parked it
        parked[rid] = open_case["case"]
        rows = [
            packet["dispositions"][rid]
            for manifest in steward.committed_manifests(home)
            for packet in manifest.get("packets") or []
            if rid in (packet.get("dispositions") or {})
        ]
        assert any(
            row.get("state") == "abandoned" and row.get("successor_case") == open_case["case"]
            and str(row.get("input_version")).startswith("observation:")
            for row in rows
        ), rows  # positive control: parked at the observation, its version undecided
    status_before = {rid: _status(home, rid) for rid in subjects}
    assert set(subjects).isdisjoint(_eligible(home)), "a held lesson is not selected"

    if pair is not None and not any(
        row.get("superseded_by") for row in cases.list_cases(home) if row["case"] == pair.moving_case
    ):
        # The case that moved the pair is still open: a fresh observation on
        # it would bring its lessons back as reconsider inputs -- not while
        # the overseer holds them.
        cases.observe(home, pair.moving_case, "statement", text="the user said more again",
                      ref=pair.statement, by="steward")
        with pytest.MonkeyPatch.context() as no_hold:
            no_hold.setattr(cases, "held_lessons", lambda home_: {})
            would = {entry.record.id for entry, _card in steward._reconsider_proposals(home)[0]}
        assert set(subjects) <= would  # positive control: the observation would bring them
        proposed = {entry.record.id for entry, _card in steward._reconsider_proposals(home)[0]}
        assert set(subjects).isdisjoint(proposed), proposed

    seen: list[list[str]] = []

    def decide_everything(spec):
        seen.append(_ids(spec.prompt))
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", decide_everything)
    result = steward.run(home)
    if result.run_id is not None:
        inputs = [row["record"] for packet in _head_manifest(home, result.run_id)["packets"]
                  for row in packet["inputs"]]
        assert set(subjects).isdisjoint(inputs), inputs
    assert set(subjects).isdisjoint(rid for brief in seen for rid in brief)
    assert {rid: _status(home, rid) for rid in subjects} == status_before
    for rid in subjects:
        assert [row["case"] for row in _open_parked(home, rid)] == [parked[rid]]

    for rid in subjects:
        _overseer_decides(home, parked[rid], [rid], tmp_path)
    eligible = _eligible(home)
    for rid in subjects:
        assert rid in eligible, "selected again once the overseer has decided"
        assert not eligible[rid].startswith("observation:")


# ------------------------------- 2. a held lesson's line is refused by name


def _held_and_free(tmp_path: Path, prefix: str) -> tuple[Path, str, str, str]:
    """A pending lesson H parked for the overseer (by hand: whoever parks a
    lesson, it is held alike) and a pending lesson P the steward decides."""
    home = make_env(tmp_path).ledger
    held = _seed(home, f"{prefix}0001")
    free = _seed(home, f"{prefix}0002")
    parked = _parked_by_hand(home, [held], tmp_path)
    _enable_steward(home)
    return home, held, free, parked


def _extra_line_session(free: str, held: str, prompts: list[str]):
    """The model decides P, and its sheet also rejects H as P's duplicate --
    first pass and repair alike."""
    def write(spec):
        prompts.append(spec.prompt)
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / "dupe.yaml", _case([free], "reject", "reject"))
        _dump_yaml(stage / "sheets" / "dupe.yaml", {"version": 1, "case": "$CASE_ID", "items": [
            {"id": free, "verb": "reject"},
            {"id": held, "verb": "reject", "note": "the same lesson as the other"},
        ]})
        return _ok()

    return write


def test_a_line_on_a_held_lesson_is_refused_at_preview_and_at_run(tmp_path, monkeypatch):
    """The brief lists H under LESSONS THE OVERSEER HOLDS with its parked
    case and reason. The model's sheet still rejects H beside P: the repair
    turn names that line and says the overseer holds H. The model keeps it:
    apply time refuses the whole case before anything applies -- not
    recorded, H untouched and parked once, P sent back (`bad-line`) with the
    held sentence as its reason, to be decided again without the line."""
    home, held, free, parked = _held_and_free(tmp_path, "lrn-d8a0")
    sent = _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session",
                        _extra_line_session(free, held, prompts))
    held_bytes = ledger_ops.find_record_path(home, held).read_bytes()

    result = steward.run(home)

    packet = _packet(home, result.run_id)
    assert [row["record"] for row in packet["inputs"]] == [free]  # H is not an input
    brief = prompts[0]
    assert steward_prompt.HELD_TITLE in brief
    assert f"- {held}: {parked} (authority-unclear)" in brief
    assert len(prompts) == 2, "the repair turn was offered"
    repair = prompts[1].split(_REPAIR_HEADER, 1)[1]
    assert f"- sheets/dupe.yaml: item 2 (reject {held}): the overseer holds {held}" in repair
    assert f"(parked case {parked} (authority-unclear))" in repair
    row = packet["dispositions"][free]
    assert (row["state"], row.get("kind")) == ("returned", "bad-line"), row
    assert f"reject {held}: the overseer holds {held} (parked case {parked}" in row["reason"]
    assert f"{held}: {held}:" not in row["reason"], "gate S1c nit: the id is not repeated"
    assert "case" not in row, "the case was refused before it was recorded"
    (case_id,) = packet["case_ids"]
    assert case_id not in {row["case"] for row in cases.list_cases(home)}
    assert _head_manifest(home, result.run_id)["cases"][case_id]["phase"] == "refused"
    assert _status(home, free) == "pending" and _status(home, held) == "pending"
    assert ledger_ops.find_record_path(home, held).read_bytes() == held_bytes
    assert [row["case"] for row in _open_parked(home, held)] == [parked]
    assert sent == []
    assert free in _eligible(home), "P is decided again"


def test_the_held_check_names_a_supersede_successor_too(tmp_path):
    """`_held_lines` reads a line's `id` and a `supersede`'s `new_id`. Control
    first: lines on free lessons are not flagged."""
    home, held, free, parked = _held_and_free(tmp_path, "lrn-d9a0")
    other = _seed(home, "lrn-d9a00003")
    held_lines = getattr(steward, "_held_lines", None)
    assert held_lines is not None, "the runner has a check for lines on held lessons"
    assert held_lines(home, [{"id": free, "verb": "supersede", "new_id": other}]) == []
    (line,) = held_lines(home, [{"id": free, "verb": "supersede", "new_id": held}])
    assert (line["n"], line["id"], line["kind"]) == (1, held, "bad-line")
    assert parked in line["detail"]


def test_a_lesson_held_after_selection_is_left_to_the_overseer_never_parked_twice(
    tmp_path, monkeypatch
):
    """A person parks one of the pair (X) while the steward is deciding it.
    At apply the line on X is refused by the hold, so the case is refused
    whole. X -- a reconsider input that, held, no run selects -- is not
    parked a second time, nor sent back: since the ledger-level round it
    gets a `held` row naming the person's case (gate S1c D4), its one open
    case. Y, the case's other lesson, is sent back to be decided again."""
    pair = MovedPair(tmp_path, observed=True, prefix="lrn-daa0")
    x, y = pair.ids
    _notifications(monkeypatch)
    by_hand: list[str] = []

    def write(spec):
        if not by_hand:
            by_hand.append(_parked_by_hand(pair.home, [x], tmp_path))
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / "moved-pair.yaml", _decide_pair(pair, kind="resolution"))
        _dump_yaml(stage / "sheets" / "moved-pair.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "reject"} for rid in pair.ids],
        })
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)

    result = steward.run(pair.home)

    rows = _packet(pair.home, result.run_id)["dispositions"]
    assert rows[x]["input_version"].startswith("observation:")  # control: the park-prone shape
    assert (rows[x]["state"], rows[x].get("held_by")) == ("held", by_hand), rows[x]
    assert [row["case"] for row in _open_parked(pair.home, x)] == by_hand
    assert rows[y]["state"] == "returned", rows[y]
    assert {_status(pair.home, rid) for rid in pair.ids} == {"pending"}


# ----------------------------------------------- 3. a note for the overseer


def test_a_steward_note_lands_on_the_parked_case_and_changes_nothing_else(tmp_path, monkeypatch):
    """The model decides P and writes two notes: one on H's parked case, one
    on a case that is not parked. The first is an `examined` observation by
    the steward on that case; the case stays open and H's record untouched.
    The second is refused, with the reason, and lands nowhere."""
    home, held, free, parked = _held_and_free(tmp_path, "lrn-dba0")
    other_stage = tmp_path / "decided.yaml"
    _dump_yaml(other_stage, _case([free], "reject", "reject"))
    not_parked = cases.record(home, other_stage, actor="human")
    _notifications(monkeypatch)
    note = "the lesson's transcript shows the same fix applied twice"

    def write(spec):
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / "p.yaml", _case([free], "reject", "reject"))
        _dump_yaml(stage / "sheets" / "p.yaml",
                   {"version": 1, "case": "$CASE_ID", "items": [{"id": free, "verb": "reject"}]})
        _dump_yaml(stage / "overseer-notes.yaml", {"entries": [
            {"case": parked, "text": note},
            {"case": not_parked, "text": "not for this one"},
        ]})
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    held_bytes = ledger_ops.find_record_path(home, held).read_bytes()
    frozen_before = cases.show(home, parked, evidence_only=False).frontmatter["decided_sha256"]

    result = steward.run(home)

    assert _status(home, free) == "rejected"  # control: the run applied its decision
    later = cases.show(home, parked, evidence_only=False).sections["Later observations"]
    assert f"steward examined: {note}" in later, later
    assert [row["case"] for row in _open_parked(home, held)] == [parked]
    assert cases.show(home, parked, evidence_only=False).frontmatter["decided_sha256"] == frozen_before
    assert ledger_ops.find_record_path(home, held).read_bytes() == held_bytes
    assert held not in _eligible(home)
    operations = _packet(home, result.run_id)["maintenance"]
    states = {op["payload"].get("case"): op for op in operations if op["kind"] == "note"}
    assert states[parked]["state"] == "applied"
    assert states[not_parked]["state"] == "refused"
    assert "not a parked case the overseer has yet to decide" in states[not_parked]["result"]["error"]
    assert "not for this one" not in cases.show(home, not_parked, evidence_only=False).to_text()


def test_the_brief_says_what_the_steward_may_do_with_a_held_lesson():
    """The output contract names the notes file and the refusal; the method
    says the same, briefly."""
    from self_learn import worker

    contract = " ".join(steward_prompt._render_output_contract().split())
    assert "overseer-notes.yaml" in steward_prompt.OUTPUT_CONTRACT
    assert "A sheet line that names it (`id`, or a `supersede`'s `new_id`) is refused" in contract
    assert "as an `examined` observation by the steward" in contract
    method = " ".join(
        (worker.package_skill_refs() / "steward-method.md").read_text(encoding="utf-8").split()
    )
    assert "**A lesson the overseer holds.**" in method
    assert "add a note to its parked case in `overseer-notes.yaml`. Nothing else" in method


def test_the_overseer_and_the_steward_read_one_definition_of_what_is_held(tmp_path, monkeypatch):
    """The brief: "Put the predicate in ONE function both sides call". The overseer's
    parked queue is `cases.awaiting_overseer`, and the steward's hold is
    built from that same function. Whatever it returns, the overseer is
    handed exactly those cases and the steward holds exactly their
    lessons."""
    from test_overseer_run import _enabled, _fake_two_phase
    from self_learn.overseer import run as overseer_run

    assert hasattr(cases, "awaiting_overseer"), "one definition of the overseer's queue"
    home = make_env(tmp_path).ledger
    queue = [{"case": "case-0f0f0f0f", "records": ["lrn-0f0f0f01", "lrn-0f0f0f02"],
              "parked_reason": "ledger-refused", "superseded_by": None}]
    monkeypatch.setattr(cases, "awaiting_overseer", lambda home_: list(queue))
    assert cases.held_lessons(home) == {"lrn-0f0f0f01": queue, "lrn-0f0f0f02": queue}

    _fake_two_phase(monkeypatch)
    _enabled(monkeypatch)
    captured: list[dict] = []
    monkeypatch.setattr(overseer_run, "_full_inputs",
                        lambda home_, stage, selected, parked_rows: captured.extend(parked_rows) or {})
    result = overseer_run.run(home, dry_run=False, no_push=True)
    assert result.status == "applied"  # control: the run reached its parked intake
    assert captured == queue


# ----------------------------------------------------------- 4. the scheduler


def test_the_scheduler_is_not_due_for_a_lesson_the_overseer_holds(tmp_path, monkeypatch):
    """`serve._steward_is_due` reads the steward's own selection, so a held
    lesson -- pending, or routed with a suspected rule violation -- never
    makes the steward due. Control: the same ledger is due before the park,
    and again once the overseer has decided."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-dca00001")
    _enable_steward(home)
    cache = tmp_path / "serve-cache"
    cache.mkdir()
    assert serve._steward_is_due(home, cache, 10_000.0) is True  # control
    parked = _parked_by_hand(home, [rid], tmp_path)
    assert serve._steward_is_due(home, cache, 10_000.0) is False
    assert steward._eligible_lessons(home) == []

    event = {"nonce": "a1b2c3d4", "ts": "2026-10-08T00:00:00Z", "outcome": "suspected-violation",
             "origin": "transcript:s#L1", "record": rid}
    with pytest.MonkeyPatch.context() as fired:
        fired.setattr(steward.steward_inputs, "suspected_violations",
                      lambda home_, find: {rid: [event]})
        with pytest.MonkeyPatch.context() as no_hold:  # positive control
            no_hold.setattr(cases, "held_lessons", lambda home_: {})
            assert [row["record"] for row in steward._suspected_violation_inputs(home)] == [rid]
        assert steward._suspected_violation_inputs(home) == []
        assert serve._steward_is_due(home, cache, 10_000.0) is False

    _overseer_decides(home, parked, [rid], tmp_path)
    # Gate S1c nit: with no run before, this `True` comes from "no prior
    # run" alone. That the release ITSELF makes the steward due after a
    # prior run is pinned by test_steward_ledger_hold.py::
    # test_risk_3_the_overseers_release_makes_the_steward_due.
    assert steward.last_run_iso(home) is None
    assert serve._steward_is_due(home, cache, 10_000.0) is True


# --------------------------------------- 5. the smaller items (F6, F2, F3, c)


def _secret_session(pair: MovedPair, prompts: list[str]):
    """A decision whose case text the secret scan refuses at prepare time,
    first pass and repair alike (the token is built at runtime)."""
    def write(spec):
        prompts.append(spec.prompt)
        stage = _stage_dir(spec)
        case = _decide_pair(pair, kind="resolution")
        case["decision"]["because"] = "token ghp_" + "Ab1" * 12
        _dump_yaml(stage / "cases" / "moved-pair.yaml", case)
        _dump_yaml(stage / "sheets" / "moved-pair.yaml", {
            "version": 1, "case": "$CASE_ID",
            "items": [{"id": rid, "verb": "reject"} for rid in pair.ids],
        })
        return _ok()

    return write


def test_a_secret_in_the_stewards_text_sends_the_lesson_back_once_then_parks_it(
    tmp_path, monkeypatch
):
    """Gate S1b F6. The prepare-stage secret scan wrote a bare `refused` row
    -- no kind -- which decided the lesson's version: a lesson input was
    stranded for good. A hit in the steward's own text is S-71's `bad-line`,
    and its action is the one every `bad-line` takes: night 1 sends the
    lesson back (selected again); night 2, the same version refused a second
    time, parks it now for the overseer; night 3 is idle. The parked case
    says the steward's case is not on record (nit c)."""
    pair = MovedPair(tmp_path, observed=False, prefix="lrn-dda0")
    sent = _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session", _secret_session(pair, prompts))

    first = steward.run(pair.home)
    packet = _packet(pair.home, first.run_id)
    for rid in pair.ids:
        row = packet["dispositions"][rid]
        assert "secret scan: 1 hit" in row["reason"], row  # positive control: the scan
        assert "[withheld]" in row["reason"], row
        assert "Ab1Ab1" not in row["reason"], "the matched span is withheld"
        assert (row["state"], row.get("kind")) == ("returned", "bad-line"), row
        assert "case" not in row, row
    assert set(pair.ids) <= set(_eligible(pair.home)), "sent back, selected again"
    (case_id,) = packet["case_ids"]
    assert _head_manifest(pair.home, first.run_id)["cases"][case_id]["phase"] == "refused"
    assert sent == []

    second = steward.run(pair.home)
    packet = _packet(pair.home, second.run_id)
    for rid in pair.ids:
        row = packet["dispositions"][rid]
        assert (row["state"], row.get("kind")) == ("abandoned", "bad-line"), row
        (open_case,) = _open_parked(pair.home, rid)
        assert open_case["case"] == row["successor_case"]
        text = " ".join(cases.show(pair.home, open_case["case"], evidence_only=False).to_text().split())
        assert "the steward's case and sheet are not on record" in text
        assert "on record beside it" not in text
    assert sorted(i for _cue, _summary, ids in sent for i in ids) == sorted(pair.ids)

    prompts.clear()
    assert steward.run(pair.home).status == "idle"
    assert prompts == []


def test_a_case_writer_refusals_parked_case_says_the_case_is_not_on_record(tmp_path, monkeypatch):
    """Gate S1b nit c, the case-writer path: the parked case said the
    steward's case and sheet were "on record beside it" -- false, the case
    writer had refused the case. Control: a park-now of a line the ledger
    refused in a RECORDED case still says they are."""
    home, rids, _pair = _path_f1_case_writer_refusal(tmp_path, monkeypatch)
    (open_case,) = _open_parked(home, rids[0])
    text = " ".join(cases.show(home, open_case["case"], evidence_only=False).to_text().split())
    assert "its case was refused before it was recorded" in text
    assert "the steward's case and sheet are not on record" in text
    assert "on record beside it" not in text
    recorded, _because = steward._park_now_texts("lrn-00000001", "needs-person")
    assert "the steward's own case and sheet are on record beside it" in recorded


def test_a_predecessor_an_earlier_attempt_superseded_is_not_filled_in_again(tmp_path, monkeypatch):
    """Gate S1b F2. Attempt 1 decides X alone; the runner names the pair's
    predecessor on X's case. Attempt 2 decides Y with a case of its own: the
    ledger shows the predecessor superseded already, so the runner leaves
    it out, and Y's case records and applies (before, it was filled in
    again, the case writer refused it, and Y was parked)."""
    pair = MovedPair(tmp_path, observed=True, prefix="lrn-dea0")
    x, y = pair.ids
    _notifications(monkeypatch)
    calls: list[list[str]] = []

    def write(spec):
        calls.append(_ids(spec.prompt))
        target = y if len(calls) > 2 else x
        stage = _stage_dir(spec)
        case = _case([target], "reject", "reject", scope="user")
        case["evidence"] = [{"ref": pair.statement, "quote": "near the code"}]
        case["dependencies"] = {**_NO_DEPS, "statements": [pair.statement]}
        _dump_yaml(stage / "cases" / f"one-{target}.yaml", case)
        _dump_yaml(stage / "sheets" / f"one-{target}.yaml", {
            "version": 1, "case": "$CASE_ID", "items": [{"id": target, "verb": "reject"}],
        })
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    first = steward.run(pair.home)
    second = steward.run(pair.home)

    assert second.run_id == first.run_id and calls[2] == [y]  # control: attempt 2, Y alone
    packet = _packet(pair.home, first.run_id)
    assert {packet["dispositions"][rid]["state"] for rid in pair.ids} == {"applied"}
    assert {_status(pair.home, rid) for rid in pair.ids} == {"rejected"}
    deciding = {row["records"][0]: row for row in cases.list_cases(pair.home)
                if row["case"] in packet["case_ids"]}
    assert deciding[x]["supersedes"] == pair.moving_case
    assert deciding[y].get("supersedes") is None
    assert _open_parked(pair.home, y) == []


def _split_decision(tmp_path: Path, monkeypatch, names: tuple[str, str], prefix: str) -> dict:
    """The F3 shape under one pair of file names: one earlier case routed A
    and moved B; both come back as reconsider inputs with that case as
    predecessor; the model writes `kind: reconsider` for routed A and
    `kind: resolution` for pending B, naming no `supersedes`. Returns what
    each lesson and its deciding case became."""
    resolution_name, reconsider_name = names
    home = make_env(tmp_path).ledger
    a = _seed(home, f"{prefix}0001")
    b = _seed(home, f"{prefix}0002")
    st = statements.add(home, verbatim="Mixed.", source={"message_ref": "transcript:mixed#L1"},
                        recorded_by="human")
    stage = tmp_path / "mixed-case.yaml"
    prior_case = _case([a, b], "route", "route")
    prior_case.update(evidence=[{"ref": st, "quote": "Mixed"}],
                      dependencies={**_NO_DEPS, "statements": [st]})
    _dump_yaml(stage, prior_case)
    prior = cases.record(home, stage, actor="steward")
    verbs.route(home, a, dest="skill-md", by="steward", no_push=True)
    verbs.rehome(home, b, to="user", by="steward", no_push=True)
    cases.observe(home, prior, "statement", text="more", ref=st, by="steward")
    _enable_steward(home)

    def write(spec):
        out = _stage_dir(spec)
        rec = _case([a], "reject", "reject")
        rec.update(kind="reconsider", trigger="reconsider", evidence=[{"ref": st, "quote": "Mixed"}],
                   dependencies={**_NO_DEPS, "statements": [st]})
        res = _case([b], "reject", "reject", scope="user")
        res.update(evidence=[{"ref": st, "quote": "Mixed"}],
                   dependencies={**_NO_DEPS, "statements": [st]})
        for name, case, rid in ((reconsider_name, rec, a), (resolution_name, res, b)):
            _dump_yaml(out / "cases" / f"{name}.yaml", case)
            _dump_yaml(out / "sheets" / f"{name}.yaml",
                       {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]})
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    result = steward.run(home)
    packet = _packet(home, result.run_id)
    assert {(row["record"], row.get("predecessor")) for row in packet["inputs"]} == {
        (a, prior), (b, prior)}  # control: both carry the one predecessor
    deciding = {row["records"][0]: row for row in cases.list_cases(home)
                if row["case"] in packet["case_ids"]}
    return {
        "states": {rid: packet["dispositions"][rid]["state"] for rid in (a, b)},
        "statuses": {rid: _status(home, rid) for rid in (a, b)},
        "a_case": (deciding.get(a, {}).get("kind"), deciding.get(a, {}).get("supersedes")),
        "b_supersedes": deciding.get(b, {}).get("supersedes", "no case"),
        "prior": prior, "a": a, "b": b,
    }


def test_the_reconsider_case_takes_the_predecessor_whatever_the_file_names(tmp_path, monkeypatch):
    """Gate S1b F3. The reconsider case cannot record without the
    predecessor, so it takes it; the resolution case records without.
    Before, the file that sorted first took it: with the resolution case
    first, the reconsider case was refused ("names no predecessor case")
    and its lesson parked. Both orders are run; the order that already
    worked is the control."""
    _notifications(monkeypatch)
    for label, names, prefix in (
        ("reconsider-sorts-first", ("b-resolution", "a-reconsider"), "lrn-dfb0"),
        ("resolution-sorts-first", ("a-resolution", "b-reconsider"), "lrn-dfa0"),
    ):
        got = _split_decision(tmp_path / label, monkeypatch, names, prefix)
        a, b = got["a"], got["b"]
        assert got["states"] == {a: "applied", b: "applied"}, (label, got)
        assert got["statuses"] == {a: "rejected", b: "rejected"}, (label, got)
        assert got["a_case"] == ("reconsider", got["prior"]), (label, got)
        assert got["b_supersedes"] is None, (label, got)
