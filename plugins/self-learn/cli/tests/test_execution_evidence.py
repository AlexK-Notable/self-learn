"""U14: committed execution references and trusted batch continuation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from self_learn import batch, cases, execution_evidence, gitops, intents, verbs
from self_learn.ledger_ops import create_record, find_record_path, write_proposal
from self_learn.records import Record
from support import commit_all, make_behavior, make_home, proposal_dict


_CASE_PUBLICATION_CHILD = r"""
import json, os, signal
from pathlib import Path
from self_learn import cases

op = os.environ["OP"]
kill_after = os.environ["KILL_AFTER"]
barrier = Path(os.environ["BARRIER"])

def die(point):
    barrier.write_text(point, encoding="utf-8")
    os.kill(os.getpid(), signal.SIGKILL)

original_write = cases.fsops.atomic_write
def atomic_write(path, *args, **kwargs):
    result = original_write(path, *args, **kwargs)
    if kill_after == "before-complete" and Path(path).suffix == ".md":
        die(kill_after)
    return result
cases.fsops.atomic_write = atomic_write

original_complete = cases.intents.complete
def complete(intent):
    original_complete(intent)
    if kill_after == "after-complete":
        die(kill_after)
cases.intents.complete = complete

original_commit = cases.gitops.stage_and_commit
def commit(home, paths, subject, *args, **kwargs):
    result = original_commit(home, paths, subject, *args, **kwargs)
    if kill_after == "after-commit" and subject.startswith("self-learn: case "):
        die(kill_after)
    return result
cases.gitops.stage_and_commit = commit

home = os.environ["SELF_LEARN_HOME"]
if op == "record":
    cases.record(home, os.environ["STAGE"], actor="steward", reserved_id="case-acde1234")
elif op == "receipt":
    cases.receipt(home, "case-acde1234", json.loads(os.environ["PAYLOAD"]))
else:
    cases.observe(home, "case-acde1234", "abandoned", text="unsafe legacy recipe",
                  by="steward", reserved_id="obs-acde1234")
"""


def _seed_pending(home, rid: str) -> None:
    create_record(home, make_behavior(record_id=rid, scope="skill:s"))
    write_proposal(home, rid, proposal_dict(scope="skill:s"))
    commit_all(home, "seed pending")


def _case_stage(tmp_path, *, run_id: str = "run-u14-01"):
    stage = tmp_path / "case-stage.yaml"
    stage.write_text(
        "kind: resolution\n"
        "trigger: nightly\n"
        "outcome: reject\n"
        "records: [lrn-acde1234]\n"
        "scope: skill:s\n"
        "question: Should this be rejected?\n"
        "evidence:\n"
        "  - ref: transcript:u14#L1\n"
        "    quote: observed evidence\n"
        "decision:\n"
        "  verb: reject\n"
        "  because: the evidence is conclusive\n"
        "  confidence: settled\n"
        f"run_id: {run_id}\n",
        encoding="utf-8",
    )
    return stage


def _ref(*, item: int = 1, verb: str = "reject") -> execution_evidence.ExecutionRef:
    return execution_evidence.ExecutionRef(
        run_id="run-u14-01",
        case_id="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
        item=item,
        record_id="lrn-acde1234",
        verb=verb,
        actor="steward",
    )


def test_execution_trailers_are_canonical_and_only_parse_at_the_end():
    ref = _ref()
    body = execution_evidence.append_trailers("operator note", ref)
    assert body == (
        "operator note\n\n"
        "By: steward\nCase: case-acde1234\nSheet: 12ab34cd\nItem: 1"
    )
    assert execution_evidence.parse_trailers(body) == ref.trailer_identity()
    assert execution_evidence.parse_trailers(
        "Case: case-acde1234\nSheet: 12ab34cd\nItem: 1\n\nordinary prose"
    ) is None


def test_non_opted_route_commit_body_is_byte_identical_to_legacy_shape(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)

    verbs.route(home, rid, dest="skill-md", no_push=True)

    body = gitops._git(home, "show", "-s", "--format=%B", "HEAD").stdout.rstrip()
    assert body == f"self-learn: route {rid} → skill-md"
    assert "Case:" not in body
    assert "Sheet:" not in body
    assert "Item:" not in body


def test_exact_trailer_match_rejects_wrong_values_and_duplicate_matches(tmp_path):
    home = make_home(tmp_path)
    ref = _ref()
    marker = home / "marker.txt"
    marker.write_text("one\n", encoding="utf-8")
    gitops.stage_and_commit(
        home,
        [marker],
        "self-learn: reject lrn-acde1234",
        execution_evidence.append_trailers(None, ref),
    )
    assert execution_evidence.find_mutation_commit(home, ref) == gitops.head_sha(home)
    wrong = execution_evidence.ExecutionRef(
        **{**ref.__dict__, "case_id": "case-deadbeef"}
    )
    assert execution_evidence.find_mutation_commit(home, wrong) is None

    marker.write_text("two\n", encoding="utf-8")
    gitops.stage_and_commit(
        home,
        [marker],
        "self-learn: reject lrn-acde1234",
        execution_evidence.append_trailers(None, ref),
    )
    with pytest.raises(execution_evidence.ExecutionEvidenceError, match="more than one"):
        execution_evidence.find_mutation_commit(home, ref)


def test_manifest_binding_is_read_from_the_pinned_git_object_not_worktree(tmp_path):
    home = make_home(tmp_path)
    ref = _ref()
    path = execution_evidence.manifest_path(home, ref.run_id)
    path.parent.mkdir(parents=True)
    manifest = {
        "version": 1,
        "run_id": ref.run_id,
        "cases": {
            ref.case_id: {
                "sheet_sha": ref.sheet_sha,
                "sheet_digest": ref.sheet_digest,
                "items": [{"n": 1, "id": ref.record_id, "verb": ref.verb}],
            }
        },
        "ledger_effects": [],
    }
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    commit_all(home, "prepared run")
    pinned = gitops.head_sha(home)
    path.write_text("{}\n", encoding="utf-8")

    assert execution_evidence.read_manifest(home, ref.run_id, at=pinned) == manifest
    execution_evidence.validate_manifest_ref(
        execution_evidence.read_manifest(home, ref.run_id, at=pinned), ref
    )


@pytest.mark.parametrize("run_id", ["../escape", "x/y", "", "."])
def test_manifest_path_refuses_arbitrary_destinations(tmp_path, run_id):
    with pytest.raises(execution_evidence.ExecutionEvidenceError):
        execution_evidence.manifest_path(tmp_path, run_id)


def test_dry_run_and_invalid_execution_reference_publish_no_evidence(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    case_id = cases.record(
        home,
        _case_stage(tmp_path),
        actor="steward",
        reserved_id="case-acde1234",
    )
    before = gitops.head_sha(home)
    items = batch.Sheet(
        [batch.SheetItem(n=1, id=rid, verb="reject", fields={})],
        case=case_id,
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )

    preview = batch.dry_run(home, items, actor="steward")

    assert preview.ok
    assert gitops.head_sha(home) == before
    assert not (home / "cases/runs").exists()
    assert cases.show(home, case_id, evidence_only=False).sections[
        "Application"
    ] == "(none)"
    with pytest.raises(execution_evidence.ExecutionEvidenceError):
        execution_evidence.ExecutionRef(
            **{**_ref().__dict__, "run_id": "../untrusted-destination"}
        )
    assert gitops.head_sha(home) == before
    assert not (home / "cases/runs").exists()


def test_compound_proof_is_registered_and_written_into_the_existing_intent(tmp_path):
    home = make_home(tmp_path)
    ref = _ref()
    path = execution_evidence.manifest_path(home, ref.run_id)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": ref.run_id,
                "cases": {
                    ref.case_id: {
                        "sheet_sha": ref.sheet_sha,
                        "sheet_digest": ref.sheet_digest,
                        "items": [
                            {"n": ref.item, "id": ref.record_id, "verb": ref.verb}
                        ],
                    }
                },
                "ledger_effects": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    commit_all(home, "prepared run")
    marker = home / "marker"
    intent = intents.begin(home, "collapse", [marker], "collapse")

    returned = execution_evidence.write_compound_proof(intent, ref)

    assert returned == path
    assert str(path.relative_to(home)) in {step["path"] for step in intent.steps}
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ledger_effects"] == [ref.to_proof()]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_id", "case-deadbeef"),
        ("sheet_digest", "b" * 64),
        ("item", 2),
        ("record_id", "lrn-deadbeef"),
        ("verb", "defer"),
    ],
)
def test_manifest_binding_refuses_every_wrong_execution_identity(
    tmp_path, field, value
):
    home = make_home(tmp_path)
    ref = _ref()
    manifest = {
        "version": 1,
        "run_id": ref.run_id,
        "cases": {
            ref.case_id: {
                "sheet_sha": ref.sheet_sha,
                "sheet_digest": ref.sheet_digest,
                "items": [{"n": ref.item, "id": ref.record_id, "verb": ref.verb}],
            }
        },
        "ledger_effects": [],
    }
    wrong = execution_evidence.ExecutionRef(
        **{**ref.__dict__, field: value}
    )

    with pytest.raises(execution_evidence.ExecutionEvidenceError):
        execution_evidence.validate_manifest_ref(manifest, wrong)
    assert not (home / "cases/runs").exists()


def test_compound_proof_history_refuses_removal_and_duplicate_dispatch(tmp_path):
    home = make_home(tmp_path)
    ref = _ref(verb="route")
    path = execution_evidence.manifest_path(home, ref.run_id)
    path.parent.mkdir(parents=True)
    manifest = {
        "version": 1,
        "run_id": ref.run_id,
        "cases": {
            ref.case_id: {
                "sheet_sha": ref.sheet_sha,
                "sheet_digest": ref.sheet_digest,
                "items": [{"n": ref.item, "id": ref.record_id, "verb": ref.verb}],
            }
        },
        "ledger_effects": [],
    }
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    commit_all(home, "prepared run")
    prepared = gitops.head_sha(home)
    manifest["ledger_effects"] = [ref.to_proof()]
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    commit_all(home, "compound mutation")
    manifest["ledger_effects"] = []
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    commit_all(home, "incompatible manifest rewrite")

    with pytest.raises(
        execution_evidence.ExecutionEvidenceError, match="removed"
    ):
        execution_evidence.find_compound_proof_commit(home, ref, after=prepared)

    manifest["ledger_effects"] = [ref.to_proof()]
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    commit_all(home, "restore exact proof")
    marker = home / "duplicate-marker"
    intent = intents.begin(home, "collapse", [marker], "duplicate")
    with pytest.raises(
        execution_evidence.ExecutionEvidenceError, match="duplicate compound"
    ):
        execution_evidence.write_compound_proof(intent, ref)
    intents.finish(intent)


def test_trusted_continuation_skips_original_ordinal_and_preserves_sheet_identity(
    tmp_path,
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    items = batch.Sheet(
        [
            batch.SheetItem(n=1, id=rid, verb="reopen", fields={}),
            batch.SheetItem(n=2, id=rid, verb="reject", fields={}),
        ],
        case="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    completed = batch.ItemResult(
        n=1, id=rid, verb="reopen", rc=0, state="already-applied"
    )
    continuation = batch.BatchContinuation(
        run_id="run-u14-01",
        case_id="case-acde1234",
        sheet_digest="a" * 64,
        completed={1: completed},
    )

    result = batch.run(
        home,
        items,
        no_push=True,
        actor="steward",
        continuation=continuation,
        checkpoint=lambda _partial: {"state": "ok"},
    )

    assert [(item.n, item.state) for item in result.items] == [
        (1, "already-applied"),
        (2, "applied"),
    ]
    assert Record.from_path(find_record_path(home, rid)).status == "rejected"
    body = gitops._git(home, "show", "-s", "--format=%B", "HEAD").stdout.rstrip()
    assert body.endswith(
        "By: steward\nCase: case-acde1234\nSheet: 12ab34cd\nItem: 2"
    )


def test_reopen_then_defer_continuation_skips_the_proven_reopen(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    verbs.reject(home, rid, no_push=True)
    reopen_ref = _ref(item=1, verb="reopen")
    reopen = verbs.reopen(
        home,
        rid,
        by="steward",
        no_push=True,
        execution=reopen_ref,
    )
    items = batch.Sheet(
        [
            batch.SheetItem(n=1, id=rid, verb="reopen", fields={}),
            batch.SheetItem(n=2, id=rid, verb="defer", fields={}),
        ],
        case=reopen_ref.case_id,
        sheet_sha=reopen_ref.sheet_sha,
        sheet_digest=reopen_ref.sheet_digest,
    )

    result = batch.run(
        home,
        items,
        no_push=True,
        actor="steward",
        continuation=batch.BatchContinuation(
            run_id=reopen_ref.run_id,
            case_id=reopen_ref.case_id,
            sheet_digest=reopen_ref.sheet_digest,
            completed={
                1: batch.ItemResult(
                    n=1,
                    id=rid,
                    verb="reopen",
                    rc=0,
                    sha=reopen.commit_sha,
                    state="applied",
                )
            },
        ),
        checkpoint=lambda _partial: {"state": "ok"},
    )

    assert [(item.n, item.state) for item in result.items] == [
        (1, "applied"),
        (2, "applied"),
    ]
    assert Record.from_path(find_record_path(home, rid)).status == "deferred"
    reopen_commits = gitops._git(
        home,
        "log",
        "--format=%H",
        "--grep",
        f"self-learn: reopen {rid}",
        "--fixed-strings",
    ).stdout.splitlines()
    assert reopen_commits == [reopen.commit_sha]


def test_revise_then_route_continuation_skips_the_proven_revision(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    revise_ref = _ref(item=1, verb="revise")
    revised = verbs.revise(
        home,
        rid,
        section="Trigger",
        text="Reworded before routing.",
        because="tighten wording before route",
        by="steward",
        no_push=True,
        execution=revise_ref,
    )
    items = batch.Sheet(
        [
            batch.SheetItem(
                n=1,
                id=rid,
                verb="revise",
                fields={
                    "section": "Trigger",
                    "text": "Reworded before routing.",
                    "because": "tighten wording before route",
                },
            ),
            batch.SheetItem(
                n=2, id=rid, verb="route", fields={"dest": "skill-md"}
            ),
        ],
        case=revise_ref.case_id,
        sheet_sha=revise_ref.sheet_sha,
        sheet_digest=revise_ref.sheet_digest,
    )

    result = batch.run(
        home,
        items,
        no_push=True,
        actor="steward",
        continuation=batch.BatchContinuation(
            run_id=revise_ref.run_id,
            case_id=revise_ref.case_id,
            sheet_digest=revise_ref.sheet_digest,
            completed={
                1: batch.ItemResult(
                    n=1,
                    id=rid,
                    verb="revise",
                    rc=0,
                    sha=revised.commit_sha,
                    state="applied",
                )
            },
        ),
        checkpoint=lambda _partial: {"state": "ok"},
    )

    assert [(item.n, item.state) for item in result.items] == [
        (1, "applied"),
        (2, "applied"),
    ]
    assert Record.from_path(find_record_path(home, rid)).status == "routed"
    revise_commits = gitops._git(
        home,
        "log",
        "--format=%H",
        "--grep",
        f"self-learn: revise {rid}",
        "--fixed-strings",
    ).stdout.splitlines()
    assert revise_commits == [revised.commit_sha]


def test_continuation_binding_mismatch_refuses_before_item_one(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    before = gitops.head_sha(home)
    items = batch.Sheet(
        [batch.SheetItem(n=1, id=rid, verb="reject", fields={})],
        case="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    continuation = batch.BatchContinuation(
        run_id="run-u14-01",
        case_id="case-acde1234",
        sheet_digest="b" * 64,
        completed={},
    )
    with pytest.raises(batch.BatchError, match="full sheet digest"):
        batch.run(home, items, no_push=True, actor="steward", continuation=continuation)
    assert gitops.head_sha(home) == before


def test_failed_ordered_checkpoint_halts_with_partial_result_and_untouched_tail(
    tmp_path,
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    record = Record.from_path(find_record_path(home, rid))
    record.set_status("rejected")
    record.set_resolution_note("prior rejection")
    record.write(find_record_path(home, rid))
    commit_all(home, "seed rejected")
    # Item 1 is a real present-state no-op after classification. Its
    # durability checkpoint must succeed before item 2 may dispatch.
    items = batch.Sheet(
        [
            batch.SheetItem(n=1, id=rid, verb="reject", fields={}),
            batch.SheetItem(n=2, id=rid, verb="reopen", fields={}),
        ],
        case="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    continuation = batch.BatchContinuation(
        run_id="run-u14-01",
        case_id="case-acde1234",
        sheet_digest="a" * 64,
        completed={},
    )

    def failed_checkpoint(_partial):
        return None

    with pytest.raises(batch.BookkeepingHalt) as raised:
        batch.run(
            home,
            items,
            no_push=True,
            actor="steward",
            continuation=continuation,
            checkpoint=failed_checkpoint,
        )
    assert [(i.n, i.state) for i in raised.value.result.items] == [
        (1, "already-applied")
    ]
    assert [i.n for i in raised.value.untouched_tail] == [2]
    assert Record.from_path(find_record_path(home, rid)).status == "rejected"


def test_noop_classification_refuses_an_intervening_dirty_record(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    verbs.reject(home, rid, no_push=True)
    path = find_record_path(home, rid)
    path.write_text(
        path.read_text(encoding="utf-8") + "\nmanual incompatible change\n",
        encoding="utf-8",
    )
    dirty_bytes = path.read_bytes()
    items = batch.Sheet(
        [batch.SheetItem(n=1, id=rid, verb="reject", fields={})],
        case="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    checkpoints = []

    with pytest.raises(batch.BookkeepingHalt, match="uncommitted") as raised:
        batch.run(
            home,
            items,
            no_push=True,
            actor="steward",
            continuation=batch.BatchContinuation(
                run_id="run-u14-01",
                case_id="case-acde1234",
                sheet_digest="a" * 64,
                completed={},
            ),
            checkpoint=lambda partial: checkpoints.append(partial) or {"state": "ok"},
        )

    assert raised.value.result.items == []
    assert [item.n for item in raised.value.untouched_tail] == [1]
    assert checkpoints == []
    assert path.read_bytes() == dirty_bytes


def test_keyed_note_head_return_is_detected_as_no_mutation_before_next_item(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    verbs.note(
        home, rid, append="first observation", key="stable-key", no_push=True
    )
    before = gitops.head_sha(home)
    items = batch.Sheet(
        [
            batch.SheetItem(
                n=1,
                id=rid,
                verb="note",
                fields={"append": "first observation", "key": "stable-key"},
            ),
            batch.SheetItem(n=2, id=rid, verb="reject", fields={}),
        ],
        case="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    continuation = batch.BatchContinuation(
        run_id="run-u14-01",
        case_id="case-acde1234",
        sheet_digest="a" * 64,
        completed={},
    )
    # Force the real verb-level keyed-note no-op instead of the outer
    # classifier's equivalent shortcut. The returned sha is HEAD, so only a
    # before/after commit comparison can identify that no mutation landed.
    monkeypatch.setattr(batch, "classify", lambda *_args, **_kwargs: False)

    with pytest.raises(batch.BookkeepingHalt) as raised:
        batch.run(
            home,
            items,
            no_push=True,
            actor="steward",
            continuation=continuation,
            checkpoint=lambda _partial: None,
        )

    assert [item.n for item in raised.value.result.items] == [1]
    assert raised.value.result.items[0].sha == before
    assert [item.n for item in raised.value.untouched_tail] == [2]
    assert gitops.head_sha(home) == before
    assert Record.from_path(find_record_path(home, rid)).status == "pending"


def test_host_failure_is_receipted_then_halts_before_dependent_item(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    items = batch.Sheet(
        [
            batch.SheetItem(
                n=1, id=rid, verb="route", fields={"dest": "skill-md"}
            ),
            batch.SheetItem(
                n=2, id=rid, verb="note", fields={"append": "must not run"}
            ),
        ],
        case="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    continuation = batch.BatchContinuation(
        run_id="run-u14-01",
        case_id="case-acde1234",
        sheet_digest="a" * 64,
        completed={},
    )
    checkpoints = []

    def fail_after_ledger_commit(*_args, **_kwargs):
        raise batch.CompileError("simulated host failure")

    monkeypatch.setattr(verbs, "_host_phase", fail_after_ledger_commit)
    with pytest.raises(batch.BookkeepingHalt, match="host outcome failed") as raised:
        batch.run(
            home,
            items,
            no_push=True,
            actor="steward",
            continuation=continuation,
            checkpoint=lambda partial: checkpoints.append(partial.to_json())
            or {"state": "ok"},
        )

    assert [item.n for item in raised.value.result.items] == [1]
    assert [item.n for item in raised.value.untouched_tail] == [2]
    assert raised.value.result.items[0].rc == 1
    assert raised.value.result.items[0].evidence == "host failure returned by route"
    assert len(checkpoints) == 1
    routed = Record.from_path(find_record_path(home, rid))
    assert routed.status == "routed"
    assert all(note.get("text") != "must not run" for note in routed.notes)


def test_recompile_establishes_unreceipted_route_without_rerunning_ledger_leg(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    case_id = cases.record(
        home,
        _case_stage(tmp_path),
        actor="steward",
        reserved_id="case-acde1234",
    )
    ref = _ref(verb="route")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            verbs,
            "_host_phase",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                batch.CompileError("killed between ledger and host")
            ),
        )
        with pytest.raises(batch.CompileError, match="between ledger and host"):
            verbs.route(
                home,
                rid,
                dest="skill-md",
                by="steward",
                no_push=True,
                execution=ref,
            )

    route_sha = gitops.head_sha(home)
    skill_md = tmp_path / "host-repo/plugins/s-plugin/skills/s/SKILL.md"
    assert rid not in skill_md.read_text(encoding="utf-8")
    repair = verbs.recompile(home, no_push=True)
    assert rid in skill_md.read_text(encoding="utf-8")
    assert not [warning for warning in repair.warnings if rid in warning]

    completed = batch.ItemResult(
        n=1,
        id=rid,
        verb="route",
        rc=0,
        sha=route_sha,
        state="applied",
        evidence="host result established by recompile",
    )
    items = batch.Sheet(
        [
            batch.SheetItem(
                n=1, id=rid, verb="route", fields={"dest": "skill-md"}
            ),
            batch.SheetItem(
                n=2, id=rid, verb="note", fields={"append": "after repair"}
            ),
        ],
        case=case_id,
        sheet_sha=ref.sheet_sha,
        sheet_digest=ref.sheet_digest,
    )
    result = batch.run(
        home,
        items,
        no_push=True,
        actor="steward",
        continuation=batch.BatchContinuation(
            run_id=ref.run_id,
            case_id=case_id,
            sheet_digest=ref.sheet_digest,
            completed={1: completed},
        ),
        checkpoint=lambda partial: batch.write_receipt(
            home, partial, "u14.yaml", no_push=True, prefix=True
        ),
    )

    assert [item.n for item in result.items] == [1, 2]
    route_commits = gitops._git(
        home,
        "log",
        "--format=%H",
        "--grep",
        f"self-learn: route {rid}",
        "--fixed-strings",
    ).stdout.splitlines()
    assert route_commits == [route_sha]
    application = cases.show(home, case_id, evidence_only=False).sections["Application"]
    assert "item=1" in application
    assert "evidence: host result established by recompile" in application


def test_noop_then_mutation_resume_never_reopens_the_rejected_record(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    verbs.reject(home, rid, note="first resolution", no_push=True)
    verbs.reopen(home, rid, note="correction", no_push=True)
    case_id = cases.record(
        home,
        _case_stage(tmp_path),
        actor="steward",
        reserved_id="case-acde1234",
    )
    items = batch.Sheet(
        [
            batch.SheetItem(n=1, id=rid, verb="reopen", fields={}),
            batch.SheetItem(n=2, id=rid, verb="reject", fields={}),
        ],
        case=case_id,
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    continuation = batch.BatchContinuation(
        run_id="run-u14-01",
        case_id=case_id,
        sheet_digest="a" * 64,
        completed={},
    )

    def kill_before_second_receipt(partial):
        if len(partial.items) == 2:
            raise RuntimeError("simulated death before second receipt")
        return batch.write_receipt(
            home, partial, "u14.yaml", no_push=True, prefix=True
        )

    with pytest.raises(batch.BookkeepingHalt) as halted:
        batch.run(
            home,
            items,
            no_push=True,
            actor="steward",
            continuation=continuation,
            checkpoint=kill_before_second_receipt,
        )
    assert [item.n for item in halted.value.result.items] == [1, 2]
    assert Record.from_path(find_record_path(home, rid)).status == "rejected"

    completed = {1: halted.value.result.items[0]}
    resumed = batch.run(
        home,
        items,
        no_push=True,
        actor="steward",
        continuation=batch.BatchContinuation(
            run_id="run-u14-01",
            case_id=case_id,
            sheet_digest="a" * 64,
            completed=completed,
        ),
        checkpoint=lambda partial: batch.write_receipt(
            home, partial, "u14.yaml", no_push=True, prefix=True
        ),
    )
    assert [(item.n, item.state) for item in resumed.items] == [
        (1, "already-applied"),
        (2, "already-applied"),
    ]
    assert Record.from_path(find_record_path(home, rid)).status == "rejected"
    application = cases.show(home, case_id, evidence_only=False).sections["Application"]
    assert application.count("item=1") == 1
    assert application.count("item=2") == 1


def test_prefix_receipt_preserves_previously_committed_lines_byte_for_byte(tmp_path):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    _seed_pending(home, rid)
    case_id = cases.record(
        home,
        _case_stage(tmp_path),
        actor="steward",
        reserved_id="case-acde1234",
    )
    cases.receipt(
        home,
        case_id,
        {
            "sheet": "u14.yaml",
            "sheet_sha": "12ab34cd",
            "at": "2026-09-14T01:02:03Z",
            "stopped_at": None,
            "code": 0,
            "items": [
                {
                    "n": 1,
                    "id": rid,
                    "verb": "reopen",
                    "state": "applied",
                    "rc": 0,
                }
            ],
        },
    )
    before_line = next(
        line
        for line in cases.show(
            home, case_id, evidence_only=False
        ).sections["Application"].splitlines()
        if "item=1" in line
    )
    items = batch.Sheet(
        [
            batch.SheetItem(n=1, id=rid, verb="reopen", fields={}),
            batch.SheetItem(n=2, id=rid, verb="reject", fields={}),
        ],
        case=case_id,
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )

    batch.run(
        home,
        items,
        no_push=True,
        actor="steward",
        continuation=batch.BatchContinuation(
            run_id="run-u14-01",
            case_id=case_id,
            sheet_digest="a" * 64,
            completed={
                1: batch.ItemResult(
                    n=1,
                    id=rid,
                    verb="reopen",
                    rc=0,
                    state="applied",
                )
            },
        ),
        checkpoint=lambda partial: batch.write_receipt(
            home, partial, "u14.yaml", no_push=True, prefix=True
        ),
    )

    lines = cases.show(home, case_id, evidence_only=False).sections[
        "Application"
    ].splitlines()
    assert before_line in lines
    assert sum("item=1" in line for line in lines) == 1
    assert sum("item=2" in line for line in lines) == 1


@pytest.mark.parametrize("operation", ["record", "receipt", "observe"])
@pytest.mark.parametrize(
    "kill_after", ["before-complete", "after-complete", "after-commit"]
)
def test_case_publications_survive_real_kill_and_retry_repeat_safely(
    tmp_path, operation, kill_after
):
    home = make_home(tmp_path)
    stage = _case_stage(tmp_path)
    payload = {
        "sheet": "u14.yaml",
        "sheet_sha": "12ab34cd",
        "at": "2026-09-14T13:00:00Z",
        "stopped_at": None,
        "code": 0,
        "items": [
            {
                "n": 1,
                "id": "lrn-acde1234",
                "verb": "reject",
                "state": "applied",
                "rc": 0,
            }
        ],
    }
    if operation != "record":
        cases.record(
            home, stage, actor="steward", reserved_id="case-acde1234"
        )
        frozen_before = cases.show(
            home, "case-acde1234", evidence_only=False
        ).frontmatter["decided_sha256"]
    else:
        frozen_before = None
    before_count = int(
        gitops._git(home, "rev-list", "--count", "HEAD").stdout.strip()
    )
    barrier = tmp_path / f"barrier-{operation}-{kill_after}"
    cache = tmp_path / "entire-cache"
    child_env = dict(os.environ)
    child_env.pop("SELF_LEARN_ANALYST_MODEL", None)
    child_env.pop("SELF_LEARN_ANALYST_TIMEOUT", None)
    child_env.update(
        {
            "SELF_LEARN_HOME": str(home),
            "XDG_CACHE_HOME": str(cache),
            "SELF_LEARN_CLAUDE_DIR": str(tmp_path / "claude"),
            "OP": operation,
            "KILL_AFTER": kill_after,
            "BARRIER": str(barrier),
            "STAGE": str(stage),
            "PAYLOAD": json.dumps(payload),
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", _CASE_PUBLICATION_CHILD],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == -9, (proc.stdout, proc.stderr)
    assert barrier.read_text(encoding="utf-8") == kill_after
    shutil.rmtree(cache, ignore_errors=True)

    recovered = intents.recover(home)
    assert recovered.stopped == []
    assert not list((home / ".intents").glob("*.json"))
    recovered_text = None
    if kill_after in {"after-complete", "after-commit"}:
        recovered_path = next((home / "cases").glob("*/case-acde1234.md"))
        recovered_text = recovered_path.read_text(encoding="utf-8")

    if operation == "record":
        cases.record(
            home, stage, actor="steward", reserved_id="case-acde1234"
        )
    elif operation == "receipt":
        cases.receipt(home, "case-acde1234", payload)
    else:
        cases.observe(
            home,
            "case-acde1234",
            "abandoned",
            text="unsafe legacy recipe",
            by="steward",
            reserved_id="obs-acde1234",
        )
    case_path = next((home / "cases").glob("*/case-acde1234.md"))
    text = case_path.read_text(encoding="utf-8")
    if operation == "receipt":
        assert text.count("sheet=u14.yaml#12ab34cd item=1") == 1
    elif operation == "observe":
        assert text.count("obs-acde1234") == 1
    else:
        assert "case: case-acde1234" in text
    if frozen_before is not None:
        assert cases.show(
            home, "case-acde1234", evidence_only=False
        ).frontmatter["decided_sha256"] == frozen_before
    if recovered_text is not None:
        assert text == recovered_text
    after_retry = int(
        gitops._git(home, "rev-list", "--count", "HEAD").stdout.strip()
    )
    # Before-complete restores and the retry publishes once. The two
    # roll-forward shapes publish during recovery; retry is a no-op.
    assert after_retry == before_count + 1
