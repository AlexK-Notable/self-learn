"""2026-10-06 -- a filing move does not strand a lesson (L8, redesigned).

When the steward rehomes or rescopes a pending lesson, the lesson is still
pending afterwards, in its new bucket. A project->project move used to
rewrite no byte of the record (`verbs.rehome`, U-verbs §3.2b), so its
version -- the record's committed blob (U3a) -- was unchanged, and the
move's `applied` row marked that version decided: every later run skipped
the lesson and it waited for ever. Found read-only on the live ledger:
`case-1f29abaf` (run `run-56216707bd4f`) rehomed two lessons and
`case-ccbbeedb` a third, all three still pending and never selected.

The design (the orchestrator's, after the gate on 61ec621 found that
scoping decisions to a bucket re-opens every decided lesson of a bucket
`host rebind` renames):
- every move writes one `moved` history entry into the record it moves,
  for every actor, so the moved lesson is a new version, selected again in
  its new bucket; a rebind writes nothing, so a decided lesson stays
  decided;
- an `applied` row whose case moved the lesson is not a decision, which is
  what brings back a lesson moved before this change (its blob never
  changed);
- the bound: the steward moves a lesson at most once, and never moves one
  a person or the overseer moved last -- such a case is parked for the
  overseer as `scope-conflict`, never applied.

Two registered project hosts under ``tmp_path``; no real model call (the
fakes write the stage files), no embedding call.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from self_learn import always_loaded, cases, execution_evidence, hosts, ledger_ops, steward, verbs
from self_learn.hosts import host_add, slug_for
from self_learn.invocation.contract import Outcome
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
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
    project->project move, the one move that used to leave the record's
    bytes (its version) unchanged."""

    def __init__(self, tmp_path: Path):
        sandbox = make_env(tmp_path)
        self.tmp_path = tmp_path
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

    def record(self, rid: str) -> Record:
        return Record.from_path(ledger_ops.find_record_path(self.home, rid))

    def blob(self, rid: str) -> str:
        rel = ledger_ops.find_record_path(self.home, rid).relative_to(self.home).as_posix()
        return git(self.home, "rev-parse", f"HEAD:{rel}").stdout.strip()

    def row(self, rid: str) -> dict:
        """The input row the steward selects the lesson with, now."""
        return next(row for entry, row in steward._eligible_lessons(self.home)
                    if entry.record.id == rid)

    def move(self, rid: str, host: Path, *, by: str | None) -> None:
        verbs.rehome(self.home, rid, to=str(host), by=by, no_push=True)

    def move_without_entry(self, rid: str) -> None:
        """A project->project move as it was before L8: the file renamed
        into B, not one byte of it changed."""
        bucket_b = self.home / self.bucket_b
        ledger_ops.ensure_project_meta(bucket_b, self.host_b)
        (bucket_b / "pending").mkdir(parents=True, exist_ok=True)
        git(self.home, "mv", f"{self.bucket_a}/pending/{rid}.md",
            f"{self.bucket_b}/pending/{rid}.md")
        commit_all(self.home, f"self-learn: rehome {rid} → {self.bucket_b}")


def _moves(record: Record) -> list[dict]:
    return [dict(e) for e in record.history or [] if e.get("event") == "moved"]


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


# ------------------------------------------------ 1. the move writes itself


@pytest.mark.parametrize(
    ("verb", "to", "by", "expected_by", "expected_to"),
    [
        ("rehome", "B", "steward", "steward", "B"),
        ("rescope", "B", "overseer", "overseer", "B"),
        ("rescope", "user", None, "human", "user"),
    ],
    ids=["rehome-steward", "rescope-overseer", "rescope-person"],
)
def test_rehome_and_rescope_append_exactly_one_moved_entry(
    verb, to, by, expected_by, expected_to, tmp_path
):
    env = Ledger(tmp_path)
    rid = "lrn-f1100010"
    env.lesson(rid)
    before = env.blob(rid)
    target = str(env.host_b) if to == "B" else "user"

    getattr(verbs, verb)(env.home, rid, to=target, by=by, no_push=True)

    record = env.record(rid)
    (entry,) = _moves(record)
    assert set(entry) == {"at", "event", "from", "to", "by"}
    assert entry["from"] == env.bucket_a
    assert entry["to"] == (env.bucket_b if expected_to == "B" else "user")
    assert entry["by"] == expected_by
    assert len(record.history) == 1
    assert env.blob(rid) != before, "the move is a new version of the lesson"


def test_a_delegated_move_names_its_runner_and_case(tmp_path):
    """Under a delegated sheet the runner's own identity is the actor (as
    for the commit's attribution, never a sheet field) and the case rides
    along."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100011"
    env.lesson(rid)
    ref = execution_evidence.ExecutionRef(
        run_id="run-f11000000011", case_id="case-f1100011", sheet_sha="0123abcd",
        sheet_digest="0" * 64, item=1, record_id=rid, verb="rehome", actor="overseer",
    )
    verbs.rehome(env.home, rid, to=str(env.host_b), by="human", no_push=True, execution=ref)

    (entry,) = _moves(env.record(rid))
    assert entry["by"] == "overseer"
    assert entry["case"] == "case-f1100011"


# ------------------------------------------- 2. eligibility after a move


def test_a_lesson_moved_before_the_move_entry_existed_is_selected_again(tmp_path):
    """The live shape: `case-1f29abaf` rehomed a lesson project->project
    before moves wrote into the record; the run record says `applied` at
    the version it selected; the lesson is pending in the new bucket at
    that same version, with no `moved` entry."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100001"
    env.lesson(rid)
    row = env.row(rid)
    env.move_without_entry(rid)
    _publish_run(env.home, "run-f11000000001", [
        (row, "applied", "case-f1100001", [{"n": 1, "id": rid, "verb": "rehome"}]),
    ])

    # positive control: this is the stranding shape
    assert env.pending(env.bucket_b, rid).is_file()
    assert env.blob(rid) == row["version"] and _moves(env.record(rid)) == []

    assert _selected(env.home) == [rid]
    assert env.row(rid)["path"] == f"{env.bucket_b}/pending/{rid}.md"


@pytest.mark.parametrize("by", ["overseer", None], ids=["overseer", "person"])
def test_a_parked_lesson_a_person_or_the_overseer_moves_is_selected_again(by, tmp_path):
    """The overseer decides a parked case by moving the lesson (live:
    `case-64084ade` -> `case-7d83a07b` rehomed `lrn-56860b4a`; that move
    was project->user and so changed the bytes by luck). A same-scope move
    now changes them too."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100002"
    env.lesson(rid)
    row = env.row(rid)
    _publish_run(env.home, "run-f11000000002", [
        (row, "parked", "case-f1100002", [{"n": 1, "id": rid, "verb": "route"}]),
    ])
    assert _selected(env.home) == [], "positive control: parked and unmoved, still decided"

    env.move(rid, env.host_b, by=by)

    assert _selected(env.home) == [rid]
    assert env.row(rid)["version"] != row["version"]


@pytest.mark.parametrize("state", ["parked", "refused", "abandoned", "overtaken"])
def test_host_rebind_leaves_a_decided_lesson_decided(state, tmp_path):
    """Gate F1 on 61ec621: `host rebind` renames a whole bucket and writes
    no record. A decision tied to the bucket made every decided lesson in
    it look undecided -- a second case beside the overseer's parked one, a
    secret-refused lesson retried. A decision is tied to the version, and a
    rebind does not change it."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100003"
    env.lesson(rid)
    row = env.row(rid)
    _publish_run(env.home, "run-f11000000003", [
        (row, state, "case-f1100003", [{"n": 1, "id": rid, "verb": "route"}]),
    ])
    moved_host = tmp_path / "repos" / "host-repo-moved"
    init_repo(moved_host)
    (moved_host / "README.md").write_text("moved\n", encoding="utf-8")
    commit_all(moved_host, "moved seed")

    new_bucket = hosts.host_rebind(env.home, slug_for(env.host_a), moved_host)

    # positive control: the bucket really was renamed, the record untouched
    rel = ledger_ops.find_record_path(env.home, rid).relative_to(env.home).as_posix()
    assert rel == f"projects/{new_bucket.name}/pending/{rid}.md" != row["path"]
    assert env.blob(rid) == row["version"]

    assert _selected(env.home) == []


# ------------------------------------------------ 3. the bound, end to end


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


def _case_id(home: Path, run_id: str, rid: str) -> str:
    (packet,) = _head_manifest(home, run_id)["packets"]
    return str(packet["dispositions"][rid]["case"])


def _case_of(home: Path, run_id: str, rid: str) -> dict:
    """The frontmatter of the committed case this run's record names as
    *rid*'s disposition."""
    view = cases.show(home, _case_id(home, run_id, rid), evidence_only=False)
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
    """Run 1 moves the lesson A -> B, writes the move into the record, and
    does not decide it in the same run; the next run selects it in B. Run 2
    tries to move it back: the case is parked as `scope-conflict` and its
    sheet is recorded, never applied, so the lesson stays pending in B for
    the overseer. The count is per lesson, not per version, so rewording
    the lesson before each move does not start it again."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100006"
    env.lesson(rid)
    _configure_steward(env.home)

    calls: list = []
    monkeypatch.setattr(steward.invocation, "write_session", _session(
        env.host_b, verb=verb, revise="Reworded once." if revise else None, calls=calls))
    first = steward.run(env.home)
    assert first.status == "applied" and len(calls) == 1
    assert env.pending(env.bucket_b, rid).is_file()
    assert _case_of(env.home, str(first.run_id), rid).get("kind") != "parked"
    (entry,) = _moves(env.record(rid))
    assert (entry["from"], entry["to"], entry["by"]) == (env.bucket_a, env.bucket_b, "steward")
    assert entry["case"] == _case_id(env.home, str(first.run_id), rid)
    # moved, not decided: still pending, and run 1 made no second case for it
    assert env.record(rid).status == "pending"
    (packet,) = _head_manifest(env.home, str(first.run_id))["packets"]
    assert len(packet["case_ids"]) == 1
    assert [rid] == _selected(env.home), "the next run selects it, in its new bucket"

    monkeypatch.setattr(steward.invocation, "write_session", _session(
        env.host_a, verb=verb, revise="Reworded twice." if revise else None, calls=calls))
    second = steward.run(env.home)
    assert second.status == "applied" and len(calls) == 2

    assert env.pending(env.bucket_b, rid).is_file(), "the second move was not applied"
    assert not env.pending(env.bucket_a, rid).exists()
    assert len(_moves(env.record(rid))) == 1
    parked = _case_of(env.home, str(second.run_id), rid)
    assert parked.get("kind") == "parked"
    assert parked.get("parked_reason") == "scope-conflict"
    (packet,) = _head_manifest(env.home, str(second.run_id))["packets"]
    assert packet["dispositions"][rid]["state"] == "parked"
    assert _selected(env.home) == [], "parked in B: decided there, the overseer's now"


@pytest.mark.parametrize("by", ["overseer", None], ids=["overseer", "person"])
def test_the_steward_never_moves_a_lesson_a_person_or_the_overseer_moved_last(
    by, tmp_path, monkeypatch
):
    """A person or the overseer filed the lesson into B. The steward has
    never moved it (its count is zero), yet a case that moves it is parked
    for the overseer: the steward does not override their filing."""
    env = Ledger(tmp_path)
    rid = "lrn-f1100009"
    env.lesson(rid)
    env.move(rid, env.host_b, by=by)
    _configure_steward(env.home)
    # positive control: no steward run exists, so no steward move is counted
    assert steward.committed_manifests(env.home) == []
    assert _selected(env.home) == [rid]

    monkeypatch.setattr(steward.invocation, "write_session", _session(env.host_a))
    result = steward.run(env.home)

    assert result.status == "applied"
    assert env.pending(env.bucket_b, rid).is_file(), "the steward's move was not applied"
    assert not env.pending(env.bucket_a, rid).exists()
    parked = _case_of(env.home, str(result.run_id), rid)
    assert parked.get("parked_reason") == "scope-conflict"


def _move_then_route(target: Path):
    """A fake steward session: one case per lesson, `[rehome to *target*,
    route claude-md]`, the route evidenced for an always-loaded line."""

    def write(spec):
        stage = _stage_dir(spec)
        for rid in re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M):
            _dump_yaml(stage / "cases" / f"{rid}.yaml", {
                "kind": "resolution", "trigger": "nightly", "outcome": "route",
                "records": [rid], "scope": "project",
                "question": "where does this pending lesson belong, and as what?",
                "evidence": [{"ref": "transcript:fake#L1", "quote": "status: pending"}],
                "decision": {
                    "verb": "route", "because": "it belongs to the other project",
                    "confidence": "provisional",
                    "always_loaded": {
                        key: {"because": "it is needed in every session there",
                              "refs": ["transcript:fake#L1"]}
                        for key in always_loaded.TEST_KEYS
                    },
                },
                "dependencies": {"statements": [], "user_model": [], "conditions": [],
                                 "capabilities": []},
            })
            _dump_yaml(stage / "sheets" / f"{rid}.yaml", {"version": 1, "case": "$CASE_ID",
                "items": [
                    {"id": rid, "verb": "rehome", "to": str(target), "note": "moved first"},
                    {"id": rid, "verb": "route", "dest": "claude-md", "note": "then placed"},
                ]})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return write


def test_a_move_inside_a_case_that_did_not_apply_is_still_counted(tmp_path, monkeypatch):
    """The 6f9a33f review: a `[rehome, route]` case whose rehome applies and
    whose route the ledger refuses ends `returned`, not `applied`, so its
    run record never counts the move. The lesson is a new version (its
    `moved` entry), the next night selects it again, the last mover is the
    steward -- and without the record's own count it was moved again,
    every night. The record's `moved` entries by the steward count it."""
    env = Ledger(tmp_path)
    rid = "lrn-f110000d"
    env.lesson(rid)
    _configure_steward(env.home)
    refused: list[str] = []

    def route_refused(home, record_id, **kwargs):
        refused.append(record_id)
        raise verbs.SheetLineError(f"simulated: the route line for {record_id} does not fit")

    monkeypatch.setattr(verbs, "route", route_refused)
    monkeypatch.setattr(steward.invocation, "write_session", _move_then_route(env.host_b))
    first = steward.run(env.home)

    # positive control: the move applied, the route was refused, and the
    # run record does not say `applied`
    assert refused == [rid]
    assert env.pending(env.bucket_b, rid).is_file()
    (packet,) = _head_manifest(env.home, str(first.run_id))["packets"]
    assert packet["dispositions"][rid]["state"] == "returned"
    assert [e["by"] for e in _moves(env.record(rid))] == ["steward"]
    assert _selected(env.home) == [rid], "a new version: selected again"

    monkeypatch.setattr(steward.invocation, "write_session", _move_then_route(env.host_a))
    second = steward.run(env.home)

    assert env.pending(env.bucket_b, rid).is_file(), "the second move was not applied"
    assert not env.pending(env.bucket_a, rid).exists()
    assert len(_moves(env.record(rid))) == 1
    assert refused == [rid], "the parked case dispatched nothing"
    parked = _case_of(env.home, str(second.run_id), rid)
    assert parked.get("parked_reason") == "scope-conflict"


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


# ------------------------------------- 4. a reconsider of the moving case


def test_a_reconsider_of_the_case_that_moved_a_lesson_passes_the_predecessor_check(
    tmp_path, monkeypatch
):
    """Writing the move into the record must not break a later reconsider
    of the case that moved it: the predecessor check reads the case's own
    freeze hash and its `records`, never the record's version."""
    env = Ledger(tmp_path)
    rid = "lrn-f110000c"
    env.lesson(rid)
    _configure_steward(env.home)
    monkeypatch.setattr(steward.invocation, "write_session", _session(env.host_b))
    run = steward.run(env.home)
    case_id = _case_id(env.home, str(run.run_id), rid)
    (entry,) = _moves(env.record(rid))
    assert entry["case"] == case_id, "positive control: the move is written into the record"

    assert overseer_run._reconsider_predecessor_problem(
        env.home, {"supersedes": case_id, "records": [rid]}, set()
    ) is None
