"""2026-10-06 -- a filing move does not strand a lesson.

When the steward rehomes or rescopes a pending lesson, the lesson is still
pending afterwards, in its new bucket. A project->project move rewrites no
byte of the record (`verbs.rehome`, U-verbs §3.2b), so its version -- the
record's committed blob (U3a) -- is unchanged, and the move's `applied`
disposition used to mark that version decided: every later run skipped
the lesson and it waited for ever. Found read-only on the live ledger:
`case-1f29abaf` (run `run-56216707bd4f`) rehomed two lessons and
`case-ccbbeedb` a third, all three still pending and never selected.

Covers: a lesson the steward moved is selected again by the next run, in
its new bucket (the live shape, with a real `rehome`); a decision is about
the lesson where it was filed, so a parked lesson stays decided until
someone moves it and is then decided afresh (the overseer's own filing
moves); a lesson moved back where the steward filed it from is selected
there; and the bound -- a case that would move a lesson the steward has
already moved is parked for the overseer as `scope-conflict`, never
applied, whatever verb or wording it uses.

Two registered project hosts under ``tmp_path``; no real model call (the
fakes write the stage files), no embedding call.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from self_learn import cases, ledger_ops, steward, verbs
from self_learn.hosts import host_add, slug_for
from self_learn.invocation.contract import Outcome
from support import commit_all, git, init_repo, make_env, make_knowledge
from test_steward import _configure_steward, _dump_yaml, _head_manifest, _stage_dir


@pytest.fixture(autouse=True)
def _quiet(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    roots = tmp_path / "transcripts"
    roots.mkdir()
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPT_ROOTS", str(roots))


class Ledger:
    """Two registered project hosts, A and B -- the live stranding was a
    project->project move, the one move that leaves the record's bytes
    (its version) unchanged."""

    def __init__(self, tmp_path: Path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host_a = sandbox.host
        self.host_b = tmp_path / "repos" / "znote-owner"
        init_repo(self.host_b)
        (self.host_b / "README.md").write_text("b\n", encoding="utf-8")
        commit_all(self.host_b, "host-b seed")
        host_add(self.home, self.host_b, "project")
        self.bucket_a = f"projects/{slug_for(self.host_a)}"
        self.bucket_b = f"projects/{slug_for(self.host_b)}"

    def lesson(self, rid: str) -> None:
        ledger_ops.create_record(
            self.home, make_knowledge(scope="project", record_id=rid,
                                      fact=f"A fact for {rid}."),
            project_path=self.host_a,
        )
        commit_all(self.home, f"seed {rid}")

    def pending(self, bucket: str, rid: str) -> Path:
        return self.home / bucket / "pending" / f"{rid}.md"

    def blob(self, rid: str) -> str:
        rel = ledger_ops.find_record_path(self.home, rid).relative_to(self.home).as_posix()
        return git(self.home, "rev-parse", f"HEAD:{rel}").stdout.strip()

    def row(self, rid: str) -> dict:
        """The input row the steward selects the lesson with, now."""
        return next(row for entry, row in steward._eligible_lessons(self.home)
                    if entry.record.id == rid)

    def move(self, rid: str, host: Path, *, by: str) -> None:
        verbs.rehome(self.home, rid, to=str(host), by=by, no_push=True)


def _publish_run(home: Path, run_id: str, rows: list[tuple[dict, str, str, list[dict]]]) -> None:
    """A committed steward run record shaped like the live one: one packet
    per lesson, its input row, its disposition, and the case recipe's
    sheet items (``manifest["cases"][case]["items"]``)."""
    packets, recipes = [], {}
    for index, (row, state, case_id, items) in enumerate(rows, start=1):
        rid = row["record"]
        packets.append({
            "index": index, "inputs": [row], "records": [rid], "phase": "complete",
            "dispositions": {rid: {"state": state, "input_version": row["version"],
                                   "case": case_id}},
        })
        recipes[case_id] = {"phase": "complete", "packet": index, "items": items}
    steward._publish_manifest(home, {
        "version": 1, "actor": "steward", "run_id": run_id,
        "started_at": "2026-09-29T03:19:05Z", "status": "complete",
        "cases": recipes, "packets": packets,
    }, reason="a committed run, shaped like the live one")


def _selected(home: Path) -> list[str]:
    return [entry.record.id for entry, _row in steward._eligible_lessons(home)]


# ------------------------------------------- 1. eligibility after a move


def test_a_lesson_the_steward_rehomed_is_selected_again_in_its_new_bucket(tmp_path):
    """The live shape: `case-1f29abaf` rehomed a lesson project->project; the
    run record says `applied` at the version it selected; the lesson is
    pending in the new bucket at that same version."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100001"
    env.lesson(rid)
    row = env.row(rid)
    assert row["path"] == f"{env.bucket_a}/pending/{rid}.md"
    env.move(rid, env.host_b, by="steward")
    _publish_run(env.home, "run-f11000000001", [
        (row, "applied", "case-f1100001", [{"n": 1, "id": rid, "verb": "rehome"}]),
    ])

    # positive control: this is the stranding shape -- the move left the
    # record's bytes, and so its version, exactly as the run selected them
    assert env.pending(env.bucket_b, rid).is_file()
    assert not env.pending(env.bucket_a, rid).exists()
    assert env.blob(rid) == row["version"]

    assert _selected(env.home) == [rid]
    again = env.row(rid)
    assert again["version"] == row["version"]
    assert again["path"] == f"{env.bucket_b}/pending/{rid}.md"


def test_a_parked_lesson_stays_decided_until_someone_moves_it(tmp_path):
    """The overseer's own filing moves: it decides a parked case by moving
    the lesson (live: `case-64084ade` -> `case-7d83a07b` rehomed
    `lrn-56860b4a`). That one rewrote `scope:` (project->user), so its
    version changed and it was picked up; a project->project move would
    have stranded it exactly like the steward's."""
    env = Ledger(tmp_path)
    parked, untold = "lrn-f1100002", "lrn-f1100003"
    env.lesson(parked)
    env.lesson(untold)
    parked_row = env.row(parked)
    untold_row = env.row(untold)
    _publish_run(env.home, "run-f11000000002", [
        (parked_row, "parked", "case-f1100002", [{"n": 1, "id": parked, "verb": "route"}]),
    ])
    # A row from before input rows carried their path decides its version
    # wherever the lesson lives, as every row did before.
    _publish_run(env.home, "run-f11000000003", [
        ({"record": untold, "version": untold_row["version"]}, "parked", "case-f1100003",
         [{"n": 1, "id": untold, "verb": "route"}]),
    ])
    assert _selected(env.home) == [], "parked and unmoved: still decided"

    env.move(parked, env.host_b, by="overseer")
    env.move(untold, env.host_b, by="overseer")
    assert env.blob(parked) == parked_row["version"], "positive control: same version"

    assert _selected(env.home) == [parked]


def test_a_lesson_moved_back_where_the_steward_filed_it_from_is_decided_there(tmp_path):
    """A filing move decides nothing, not even in the bucket it moved the
    lesson out of. The steward moved A -> B and then parked it in B; the
    overseer decided that parked case by moving it back to A, for the
    steward to place. Were the move a decision in A, the lesson would be
    stranded there."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100004"
    env.lesson(rid)
    in_a = env.row(rid)
    env.move(rid, env.host_b, by="steward")
    in_b = env.row(rid)
    _publish_run(env.home, "run-f11000000004", [
        (in_a, "applied", "case-f1100004", [{"n": 1, "id": rid, "verb": "rehome"}]),
    ])
    _publish_run(env.home, "run-f11000000005", [
        (in_b, "parked", "case-f1100005", [{"n": 1, "id": rid, "verb": "route"}]),
    ])
    assert _selected(env.home) == [], "positive control: parked in B, decided there"

    env.move(rid, env.host_a, by="overseer")
    assert env.blob(rid) == in_a["version"]

    assert _selected(env.home) == [rid]
    assert env.row(rid)["path"] == f"{env.bucket_a}/pending/{rid}.md"


# ------------------------------------------------ 2. the bound, end to end


def _session(target: Path, *, verb: str = "rehome", revise: str | None = None,
             parked_reason: str | None = None, calls: list | None = None):
    """A fake steward session that files every lesson of its brief into
    *target* -- rewording it first to *revise* when given, and parking the
    case with *parked_reason* when given."""

    def write(spec):
        if calls is not None:
            calls.append(spec)
        stage = _stage_dir(spec)
        for rid in re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M):
            items: list[dict] = []
            if revise is not None:
                items.append({"id": rid, "verb": "revise", "section": "Fact",
                              "text": revise, "because": "closer to the user's words"})
            items.append({"id": rid, "verb": verb, "to": str(target),
                          "note": "moved to the project that owns the source"})
            case = {
                "kind": "resolution", "trigger": "nightly", "outcome": "rehome",
                "records": [rid], "scope": "project",
                "question": "where does this pending lesson belong?",
                "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
                "decision": {"verb": verb, "because": "the source lives in the other project",
                             "confidence": "provisional"},
                "dependencies": {"statements": [], "user_model": [], "conditions": [],
                                 "capabilities": []},
            }
            if parked_reason is not None:
                case.update(kind="parked", outcome="parked", parked_for="overseer",
                            parked_reason=parked_reason)
            _dump_yaml(stage / "cases" / f"{rid}.yaml", case)
            _dump_yaml(stage / "sheets" / f"{rid}.yaml",
                       {"version": 1, "case": "$CASE_ID", "items": items})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def _case_of(home: Path, run_id: str, rid: str) -> dict:
    """The frontmatter of the committed case this run's record names as
    *rid*'s disposition."""
    (packet,) = _head_manifest(home, run_id)["packets"]
    case_id = packet["dispositions"][rid]["case"]
    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter.get("run_id") == run_id
    return dict(view.frontmatter)


@pytest.mark.parametrize(
    ("verb", "revise"),
    [("rehome", False), ("rescope", False), ("rehome", True)],
    ids=["rehome", "rescope", "revise-then-rehome"],
)
def test_a_second_move_of_the_same_lesson_is_parked_for_the_overseer(
    verb, revise, tmp_path, monkeypatch
):
    # (each pass rewords the lesson differently, so each move is at a new
    # version -- the shape a per-version count would never stop)
    """Run 1 moves the lesson A -> B and does not decide it in the same run;
    the next run selects it in B. Run 2 tries to move it back: the case is
    parked as `scope-conflict` and its sheet is recorded, never applied, so
    the lesson stays pending in B for the overseer -- and is decided there.
    The count is per lesson, not per version, so rewording the lesson
    before each move does not start the count again."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100006"
    env.lesson(rid)
    _configure_steward(env.home)

    calls: list = []
    monkeypatch.setattr(steward.invocation, "write_session", _session(
        env.host_b, verb=verb, revise="Reworded once." if revise else None, calls=calls))
    selected = env.row(rid)
    first = steward.run(env.home)
    assert first.status == "applied" and len(calls) == 1
    assert env.pending(env.bucket_b, rid).is_file()
    assert _case_of(env.home, str(first.run_id), rid).get("kind") != "parked"
    # moved, not decided: still pending, and run 1 made no second case for it
    assert ledger_ops.read_record_or_refuse(env.pending(env.bucket_b, rid)).status == "pending"
    (packet,) = _head_manifest(env.home, str(first.run_id))["packets"]
    assert len(packet["case_ids"]) == 1
    assert (env.blob(rid) == selected["version"]) is (not revise)
    assert [rid] == _selected(env.home), "the next run selects it, in its new bucket"

    monkeypatch.setattr(steward.invocation, "write_session", _session(
        env.host_a, verb=verb, revise="Reworded twice." if revise else None, calls=calls))
    second = steward.run(env.home)
    assert second.status == "applied" and len(calls) == 2

    assert env.pending(env.bucket_b, rid).is_file(), "the second move was not applied"
    assert not env.pending(env.bucket_a, rid).exists()
    parked = _case_of(env.home, str(second.run_id), rid)
    assert parked.get("kind") == "parked"
    assert parked.get("parked_reason") == "scope-conflict"
    manifest = _head_manifest(env.home, str(second.run_id))
    (packet,) = manifest["packets"]
    assert packet["dispositions"][rid]["state"] == "parked"
    assert _selected(env.home) == [], "parked in B: decided there, the overseer's now"


def test_the_repair_turn_is_not_asked_to_fix_a_case_the_runner_will_park(tmp_path):
    """The repair turn hears about lines the ledger would refuse, so the
    model can fix them while it still can. A case that would move a lesson
    already moved is parked and none of its lines is applied, so its lines
    are not the model's to fix -- as for every other case the runner parks."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100008"
    env.lesson(rid)
    selected = env.row(rid)
    stage = tmp_path / "stage"
    _dump_yaml(stage / "cases" / f"{rid}.yaml", {
        "kind": "resolution", "trigger": "nightly", "outcome": "rehome", "records": [rid],
        "scope": "project", "question": "where does this pending lesson belong?",
        "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
        "decision": {"verb": "rehome", "because": "elsewhere", "confidence": "provisional"},
        "dependencies": {"statements": [], "user_model": [], "conditions": [], "capabilities": []},
    })
    _dump_yaml(stage / "sheets" / f"{rid}.yaml", {"version": 1, "case": "$CASE_ID", "items": [
        {"id": rid, "verb": "revise", "section": "No Such Section", "text": "x",
         "because": "clearer"},
        {"id": rid, "verb": "rehome", "to": str(env.host_b)},
    ]})
    status = {rid: "pending"}
    told = steward._ledger_repair_message(env.home, stage, status)
    assert told is not None and f"revise {rid}" in told, "positive control: a repairable line"

    _publish_run(env.home, "run-f11000000008", [
        (selected, "applied", "case-f1100008", [{"n": 1, "id": rid, "verb": "rehome"}]),
    ])
    assert steward._ledger_repair_message(env.home, stage, status) is None


def test_a_case_the_model_parked_keeps_its_own_reason(tmp_path, monkeypatch):
    """The runner's park only stops a move that would otherwise be applied;
    a case the model itself parked is already recorded and never applied,
    and keeps the reason the model named."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100007"
    env.lesson(rid)
    _configure_steward(env.home)
    monkeypatch.setattr(steward.invocation, "write_session", _session(env.host_b))
    assert steward.run(env.home).status == "applied"
    assert _selected(env.home) == [rid], "positive control: moved once, selected again"

    monkeypatch.setattr(steward.invocation, "write_session",
                        _session(env.host_a, parked_reason="authority-unclear"))
    second = steward.run(env.home)

    parked = _case_of(env.home, str(second.run_id), rid)
    assert parked.get("kind") == "parked"
    assert parked.get("parked_reason") == "authority-unclear"
    assert env.pending(env.bucket_b, rid).is_file()
