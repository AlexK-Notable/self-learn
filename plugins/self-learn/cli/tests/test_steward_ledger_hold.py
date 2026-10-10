"""S-81, the ledger-level round (2026-10-08): the ledger refuses the steward
any change to a lesson the overseer holds, whichever path reaches it.

The user's words, 2026-10-08 00:42: "if there's a lesson with something that
needs to be adjudicated by the overseer then it shouldn't be further meddled
with by the steward, excpet in a fact finding capacity. it can add notes for
the overseer if it wants to, but it can't transform the lesson in any way
until the overseer gives the metaphorical okay." And at 14:49, after three
rounds that checked the lesson ids a sheet line NAMES: "a, go ahead with the
ledger-level fix."

So the rule now sits on the EFFECT. While the steward acts (a scope its run
and its batch runner open, `ledger_ops.acting_as`), the two gates every write
to a lesson record passes before anything is written refuse a held lesson:
`ledger_ops.require_status` (each record a verb changes the status of, or
names as a replacement) and `verbs._scan_or_refuse` (P2-7: each record file a
verb rewrites). The case writer refuses the steward a case about a held
lesson, or one superseding a case about one (`cases.record`).

Section 1 is the walker: it derives the steward's write paths from the code
and drives every one against a held lesson -- the ledger refuses, nothing
changes -- after a positive control on a free lesson. Section 2 pins each
finding of the third blind review (gate S1c), each failing on 6a6b2ee.

Every scenario runs on a sandbox ledger (`support.make_env` under pytest's
tmpdir, never the real ``~/.self-learn``) with fake model sessions; ids and
texts are synthetic. No real model call.
"""

from __future__ import annotations

import ast
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import (
    batch,
    cases,
    gitops,
    ledger_ops,
    serve,
    statements,
    steward,
    steward_prompt,
    telemetry,
    verbs,
)
from self_learn.invocation.contract import Outcome
from self_learn.ledger_ops import create_record, find_record_path, write_proposal
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env, merge_proposal_text, proposal_dict
from test_steward import (
    SimulatedKill,
    _dump_yaml,
    _enable_steward,
    _head_manifest,
    _stage_dir,
    _transport_failure,
    _write_decision_stage,
)
from test_steward_overseer_hold import _eligible, _open_parked
from test_steward_refusals import _case, _dispatch_with, _notifications, _refused, _seed
from test_steward_repair_catches import _ids, _overseer_decides, _packet, _status
from test_u3b_steward_authority import HOOK_TRIGGER, _hook_input

SRC = Path(steward.__file__).parent

A = "lrn-f4a00001"
B = "lrn-f4a00002"
_NO_DEPS = {"statements": [], "user_model": [], "conditions": [], "capabilities": []}


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture(autouse=True)
def claude_dir(tmp_path, monkeypatch):
    """A hook route places its script here, never in the real ~/.claude."""
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    return claude


def _ok() -> Outcome:
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


def _future(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _pending(env, rid: str, *, record: Record | None = None) -> str:
    create_record(env.ledger, record or make_behavior(record_id=rid, scope="skill:s"))
    write_proposal(env.ledger, rid, proposal_dict(scope="skill:s"))
    commit_all(env.ledger, f"seed {rid}")
    return rid


def _routed(env, rid: str, **route_kwargs) -> str:
    _pending(env, rid)
    verbs.route(env.ledger, rid, dest=route_kwargs.pop("dest", "skill-md"), no_push=True,
                **route_kwargs)
    return rid


def _suspect(env, record: str) -> str:
    before = {e["nonce"] for e in telemetry.read_events(env.ledger)
              if e.get("kind") == "recurrence-suspect"}
    telemetry.spool_event("recurrence-suspect", record=record, origin="lrn-f4a000ee",
                          basis="miner-match")
    telemetry.flush(env.ledger)
    return next(e["nonce"] for e in telemetry.read_events(env.ledger)
                if e.get("kind") == "recurrence-suspect" and e["nonce"] not in before)


def _human_case(home: Path, tmp: Path, name: str, **fields) -> str:
    stage = tmp / f"{name}.yaml"
    case = _case(fields.pop("records"), fields.pop("outcome", "route"), "route")
    case.update(fields)
    _dump_yaml(stage, case)
    return cases.record(home, stage, actor="human")


def _person_parks(home: Path, rids: list[str], tmp: Path, reason: str = "authority-unclear") -> str:
    """A person parks *rids* for the overseer -- a lesson parked by anyone is
    held alike."""
    stage = tmp / f"person-parks-{'-'.join(rids)}.yaml"
    case = _case(list(rids), "parked", "defer")
    case.update(kind="parked", parked_for="overseer", parked_reason=reason)
    case["decision"]["confidence"] = "provisional"
    _dump_yaml(stage, case)
    return cases.record(home, stage, actor="human")


def _awaiting(home: Path) -> list[str]:
    return [row["case"] for row in cases.awaiting_overseer(home)]


def _snapshot(env, claude: Path) -> tuple:
    """Everything a write could touch: both repos' HEAD and working tree
    (untracked files and a left-over intent included), and the hook dir."""
    return (
        gitops.head_sha(env.ledger),
        git(env.ledger, "status", "--porcelain", "--untracked-files=all").stdout,
        gitops.head_sha(env.host),
        git(env.host, "status", "--porcelain", "--untracked-files=all").stdout,
        sorted(p.name for p in (claude / "hooks").iterdir()),
    )


def _drive(env, tmp: Path, line: dict, case: str | None = None) -> batch.ItemResult:
    """One sheet line through the steward's own batch runner."""
    sheet = tmp / "sheet.yaml"
    _dump_yaml(sheet, {"version": 1, **({"case": case} if case else {}), "items": [line]})
    items = batch.load_sheet(sheet, home=env.ledger)
    result = batch.run(env.ledger, items, no_push=True, actor="steward")
    (got,) = result.items
    return got


# ============================================== 1. the walker (every path)
#
# Each row builds the state its line needs and returns (line, the lesson the
# held run parks, the sheet's `case:`). A row's lesson is the one the line
# would WRITE -- the line's own id, or a lesson it reaches without naming it.


def _row_route(env, tmp):
    return {"id": _pending(env, A), "verb": "route", "dest": "skill-md"}, A, None


def _row_route_collapse_loser(env, tmp):
    _pending(env, A)
    _pending(env, B)
    cluster = "merge-f4a0f4a0"
    bucket = find_record_path(env.ledger, A).parent.parent
    (bucket / "proposals" / f"{cluster}.yaml").write_text(
        merge_proposal_text(cluster, [A, B], A), encoding="utf-8")
    commit_all(env.ledger, "cluster")
    return {"id": A, "verb": "route", "dest": "skill-md", "collapse": cluster}, B, None


def _row_route_completes_supersedes(env, tmp):
    _pending(env, A)
    newer = make_behavior(record_id=B, scope="skill:s", trigger="A newer wording of it.")
    newer.set_supersedes(A)
    _pending(env, B, record=newer)
    return {"id": B, "verb": "route", "dest": "skill-md"}, A, None


def _row_route_hook(env, tmp):
    _pending(env, A, record=make_behavior(record_id=A, scope="skill:s", trigger=HOOK_TRIGGER))
    return {"id": A, "verb": "route", "dest": "hook", "hook": _hook_input()}, A, None


def _row_reroute(env, tmp):
    """`route` under a `kind: reconsider` case: the reroute path."""
    _routed(env, A, dest="reference")
    prior = _human_case(env.ledger, tmp, "prior", records=[A])
    again = _human_case(env.ledger, tmp, "again", records=[A], kind="reconsider",
                        trigger="reconsider", supersedes=prior)
    return {"id": A, "verb": "route", "dest": "skill-md"}, A, again


def _row_reject(env, tmp):
    return {"id": _pending(env, A), "verb": "reject"}, A, None


def _row_defer(env, tmp):
    return {"id": _pending(env, A), "verb": "defer", "until": _future()}, A, None


def _row_undefer(env, tmp):
    _pending(env, A)
    verbs.defer(env.ledger, A, until=_future(), no_push=True)
    return {"id": A, "verb": "undefer"}, A, None


def _row_reopen(env, tmp):
    _pending(env, A)
    verbs.reject(env.ledger, A, no_push=True)
    return {"id": A, "verb": "reopen"}, A, None


def _row_retire(env, tmp):
    return {"id": _routed(env, A), "verb": "retire", "covered_by": "skill-md:s"}, A, None


def _row_graduate(env, tmp):
    return {"id": _routed(env, A), "verb": "graduate"}, A, None


def _row_supersede_old(env, tmp):
    _pending(env, A)
    _pending(env, B)
    return {"id": A, "verb": "supersede", "new_id": B}, A, None


def _row_supersede_new(env, tmp):
    """`supersede` in the other direction: the held lesson is named the
    replacement (its record is not rewritten; the ledger still refuses)."""
    _pending(env, A)
    _pending(env, B)
    return {"id": A, "verb": "supersede", "new_id": B}, B, None


def _row_rehome(env, tmp):
    return {"id": _pending(env, A), "verb": "rehome", "to": "user"}, A, None


def _row_rescope(env, tmp):
    return {"id": _pending(env, A), "verb": "rescope", "to": "user"}, A, None


def _row_note(env, tmp):
    return {"id": _pending(env, A), "verb": "note", "append": "seen again tonight"}, A, None


def _row_confirm_recurrence(env, tmp):
    _routed(env, A)
    return {"id": A, "verb": "confirm-recurrence", "event": _suspect(env, A)}, A, None


def _row_dismiss_suspect(env, tmp):
    _routed(env, A)
    return {"id": A, "verb": "dismiss-suspect", "event": _suspect(env, A),
            "why": "a different file"}, A, None


def _row_confirm_held(env, tmp):
    return {"id": _routed(env, A), "verb": "confirm-held"}, A, None


def _row_link_contradicts(env, tmp):
    _pending(env, A)
    _pending(env, B)
    return {"id": A, "verb": "link-contradicts", "target": B}, A, None


def _row_followup_done(env, tmp):
    _routed(env, A, follow_up={"action": "check the second host"})
    return {"id": A, "verb": "followup-done"}, A, None


def _row_revise(env, tmp):
    return {"id": _pending(env, A), "verb": "revise", "section": "Trigger",
            "text": "About to edit the store while it runs.", "because": "clearer"}, A, None


_ROWS = {
    "route": _row_route,
    "route-collapse-loser": _row_route_collapse_loser,
    "route-completes-supersedes": _row_route_completes_supersedes,
    "route-hook": _row_route_hook,
    "reroute": _row_reroute,
    "reject": _row_reject,
    "defer": _row_defer,
    "undefer": _row_undefer,
    "reopen": _row_reopen,
    "retire": _row_retire,
    "graduate": _row_graduate,
    "supersede-old": _row_supersede_old,
    "supersede-new": _row_supersede_new,
    "rehome": _row_rehome,
    "rescope": _row_rescope,
    "note": _row_note,
    "confirm-recurrence": _row_confirm_recurrence,
    "dismiss-suspect": _row_dismiss_suspect,
    "confirm-held": _row_confirm_held,
    "link-contradicts": _row_link_contradicts,
    "followup-done": _row_followup_done,
    "revise": _row_revise,
}

#: The `verbs` function behind each row the batch runner dispatches. Pinned,
#: and checked against what `batch._dispatch` actually calls (below).
_DISPATCH_FN_ROWS = {
    "route": ["route", "route-collapse-loser", "route-completes-supersedes", "route-hook"],
    "hook_activate": ["route-hook"],
    "reroute": ["reroute"],
    "reject": ["reject"],
    "defer": ["defer"],
    "undefer": ["undefer"],
    "reopen": ["reopen"],
    "retire": ["retire"],
    "graduate": ["graduate"],
    "supersede": ["supersede-old", "supersede-new"],
    "rehome": ["rehome"],
    "rescope": ["rescope"],
    "note": ["note"],
    "confirm_recurrence": ["confirm-recurrence"],
    "dismiss_suspect": ["dismiss-suspect"],
    "confirm_held": ["confirm-held"],
    "link_contradicts": ["link-contradicts"],
    "followup_done": ["followup-done"],
    "revise": ["revise"],
}

#: Every sheet key, by what it names. A key that names another lesson is
#: driven by a row of its own; a new key fails the walker until classified.
_SHEET_KEYS = {
    "id": "the line's own lesson (every row)",
    "new_id": "another lesson -- row supersede-new",
    "collapse": "a cluster whose losers are rewritten -- row route-collapse-loser",
    "target": "another lesson, read for its existence only (never written)",
    **{key: "no lesson" for key in (
        "dest", "by", "follow_up", "unblocks_on", "follow_up_note", "allow_empty_glob",
        "note", "hook", "rules_paths", "until", "covered_by", "to", "append", "key",
        "event", "tolerate", "why", "section", "text", "because",
    )},
}

#: The steward's own direct calls into `cases`, by what they do.
_STEWARD_CASES_CALLS = {
    "record": "writes a case -- driven in test 1c",
    "observe": "adds an observation: a note for the overseer, or the runner's own "
               "`abandoned` line on its own case -- driven in test 1c (allowed)",
    **{name: "read" for name in (
        "awaiting_overseer", "check_case_data", "held_lessons", "list_cases", "show",
        "split_runner_evidence", "tampered_parked",
    )},
}

#: The batch runner's and the verbs' own calls into `cases`. `receipt`
#: appends the Application section -- what each line did -- to the SHEET's
#: case, which on a steward sheet is always the case the runner has just
#: recorded for it (the runner overwrites the sheet's `case:` with that id),
#: never a parked case and never a lesson.
_BATCH_CASES_CALLS = {
    "receipt": "the sheet's own case's Application section (the steward's new case)",
    "require_reconsider_case": "read",
    "_case_path_for_id": "read",
}
_VERBS_CASES_CALLS = {"require_reconsider_case": "read"}


def _functions() -> dict[str, ast.FunctionDef]:
    return {
        f"{path.stem}.{node.name}": node
        for path in SRC.glob("*.py")
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }


#: The lesson-record writers, the leaves the reachability walk below looks
#: for (the same leaves `tests/test_lock_invariant.py` names as mutations of
#: a record: `Record.write` and the `ledger_ops` file operations).
_RECORD_WRITERS = {
    "ledger_ops.resolve_record", "ledger_ops.move_record", "ledger_ops.reopen_record",
    "ledger_ops.reroute_record", "ledger_ops.defer_record", "ledger_ops.supersede_record",
    "ledger_ops._git_mv",
}
_RECORD_NAMES = ("record", "merged")


def _reaches_record_write(funcs: dict[str, ast.FunctionDef], start: str) -> bool:
    """True when *start* reaches a lesson-record write through the static
    call graph (module-qualified calls, same-module and `ledger_ops` bare
    names)."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in funcs:
            continue
        seen.add(name)
        module = name.split(".")[0]
        for sub in ast.walk(funcs[name]):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if isinstance(func, ast.Attribute):
                if func.attr == "write" and isinstance(func.value, ast.Name) \
                        and func.value.id in _RECORD_NAMES:
                    return True
                if isinstance(func.value, ast.Name):
                    target = f"{func.value.id}.{func.attr}"
                    if target in _RECORD_WRITERS:
                        return True
                    stack.append(target)
            elif isinstance(func, ast.Name):
                for target in (f"{module}.{func.id}", f"ledger_ops.{func.id}"):
                    if target in _RECORD_WRITERS:
                        return True
                    stack.append(target)
    return False


def _called(funcs: dict[str, ast.FunctionDef], module: str, receiver: str,
            only: tuple[str, ...] | None = None) -> set[str]:
    """`<receiver>.<name>(` call names inside *module*'s functions (those
    whose name starts with one of *only*, when given)."""
    out: set[str] = set()
    for name, node in funcs.items():
        mod, fn = name.split(".", 1)
        if mod != module or (only is not None and not fn.startswith(only)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                    and isinstance(sub.func.value, ast.Name) and sub.func.value.id == receiver:
                out.add(sub.func.attr)
    return out


def test_the_walker_drives_every_steward_write_path_the_code_has():
    """The list the walker drives is derived from the code, so a new path
    fails here until it is driven:

    * every sheet verb (`batch.PERMITTED_VERBS`) has a row;
    * every `verbs` function `batch._dispatch` and its `_dispatch_*` helpers
      call that reaches a lesson-record write has a row, and no row names a
      function that is not called;
    * every sheet key is classified, and each one that names another lesson
      has a row of its own;
    * every `verbs` function the steward calls directly that reaches a
      lesson-record write is driven (today only `reconsider`, test 1b), and
      every `cases` function it, the batch runner or the verbs call is
      classified (test 1c drives the steward's case writes; the batch
      runner's one case write is the receipt on the sheet's own case).

    The reachability walk's own positive control: `verbs.reject` reaches a
    record write and `verbs.recompile` does not."""
    funcs = _functions()
    assert _reaches_record_write(funcs, "verbs.reject")  # positive control
    assert not _reaches_record_write(funcs, "verbs.recompile")  # negative control

    driven_verbs = {line_verb for line_verb in batch.PERMITTED_VERBS}
    row_verbs = {
        name.split("-")[0] if name.startswith(("route", "supersede")) else
        ("route" if name == "reroute" else name)
        for name in _ROWS
    }
    assert driven_verbs == row_verbs, (driven_verbs ^ row_verbs)

    dispatched = {
        fn for fn in _called(funcs, "batch", "verbs", only=("_dispatch",))
        if _reaches_record_write(funcs, f"verbs.{fn}")
    }
    assert dispatched == set(_DISPATCH_FN_ROWS), (dispatched ^ set(_DISPATCH_FN_ROWS))
    assert {row for rows in _DISPATCH_FN_ROWS.values() for row in rows} == set(_ROWS)

    keys = {key for allowed in batch.PERMITTED_KEYS.values() for key in allowed} | {"id"}
    assert keys == set(_SHEET_KEYS), (keys ^ set(_SHEET_KEYS))

    direct = {
        fn for fn in _called(funcs, "steward", "verbs")
        if _reaches_record_write(funcs, f"verbs.{fn}")
    }
    assert direct == {"reconsider"}, direct
    assert _called(funcs, "steward", "cases") == set(_STEWARD_CASES_CALLS)
    assert _called(funcs, "batch", "cases") == set(_BATCH_CASES_CALLS)
    assert _called(funcs, "verbs", "cases") == set(_VERBS_CASES_CALLS)

    # Gate S1d N3: and no direct call from the steward or its batch runner
    # into a `ledger_ops` record writer -- `move_record` and `reopen_record`
    # check no status, so such a call would pass both gates. Control: the
    # walk does see those two as writers.
    assert _reaches_record_write(funcs, "ledger_ops.move_record")
    assert _reaches_record_write(funcs, "ledger_ops.reopen_record")
    imported = {
        alias.name
        for module in ("steward", "batch")
        for node in ast.walk(ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module == "ledger_ops"
        for alias in node.names
    }
    to_ledger_ops = (
        _called(funcs, "steward", "ledger_ops") | _called(funcs, "batch", "ledger_ops") | imported
    )
    assert {"find_record_path", "require_status"} <= to_ledger_ops  # control: calls are seen
    direct_writers = {
        fn for fn in to_ledger_ops
        if f"ledger_ops.{fn}" in _RECORD_WRITERS or _reaches_record_write(funcs, f"ledger_ops.{fn}")
    }
    assert direct_writers == set(), direct_writers


@pytest.mark.parametrize("row", sorted(_ROWS))
def test_the_ledger_refuses_the_steward_every_write_to_a_held_lesson(
    tmp_path, row, claude_dir, monkeypatch
):
    """Positive control first: the row's line applies through the steward's
    batch runner when nothing holds its lesson. Then, on a fresh ledger in
    the same state, a person parks that lesson: the same line is refused
    by the ledger (`bad-line`, the hold's sentence naming the parked case)
    and nothing changed -- neither repo's HEAD or working tree, the hook
    directory, or the lesson's record -- and the parked case still waits."""
    setup = _ROWS[row]
    free_env = make_env(tmp_path / "free")
    line, _lesson, case = setup(free_env, tmp_path / "free")
    telemetry.flush(free_env.ledger)  # the setup's own verbs' events, not the line's
    before = _snapshot(free_env, claude_dir)
    got = _drive(free_env, tmp_path / "free", line, case)
    assert (got.state, got.rc) == ("applied", 0), got
    assert _snapshot(free_env, claude_dir) != before

    # The held ledger gets its own runtime directory, so the control's hook
    # script cannot stand in the way of the held run's.
    claude_dir = tmp_path / "claude-dir-held"
    (claude_dir / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude_dir))
    env = make_env(tmp_path / "held")
    line, lesson, case = setup(env, tmp_path / "held")
    parked = _person_parks(env.ledger, [lesson], tmp_path / "held")
    record_before = find_record_path(env.ledger, lesson).read_bytes()
    telemetry.flush(env.ledger)  # the setup's own verbs' events, not the line's
    before = _snapshot(env, claude_dir)

    got = _drive(env, tmp_path / "held", line, case)

    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert f"the overseer holds {lesson} (parked case {parked}" in str(got.detail), got.detail
    assert _snapshot(env, claude_dir) == before
    assert find_record_path(env.ledger, lesson).read_bytes() == record_before
    assert _awaiting(env.ledger) == [parked]


def test_a_person_and_the_overseer_are_never_refused_by_the_hold(tmp_path):
    """The hold binds the steward alone: the same `reject` of a held lesson
    applies for a person's batch and for the overseer's."""
    for actor in ("human", "overseer"):
        env = make_env(tmp_path / actor)
        _pending(env, A)
        _person_parks(env.ledger, [A], tmp_path / actor)
        sheet = tmp_path / actor / "sheet.yaml"
        _dump_yaml(sheet, {"version": 1, "items": [{"id": A, "verb": "reject"}]})
        result = batch.run(env.ledger, batch.load_sheet(sheet, home=env.ledger),
                           no_push=True, actor=actor)
        assert [(item.state, item.rc) for item in result.items] == [("applied", 0)], actor
        assert _status(env.ledger, A) == "rejected", actor


def test_1b_the_stewards_direct_reconsider_is_refused_for_a_held_lesson(tmp_path):
    """The one `verbs` call the steward makes outside a batch that writes a
    lesson record. Control first: on a free lesson it lands its history
    entry; on a held one, under the steward's scope, the ledger refuses it
    and nothing changes."""
    for label in ("free", "held"):
        env = make_env(tmp_path / label)
        tmp = tmp_path / label
        _routed(env, A)
        prior = _human_case(env.ledger, tmp, "prior", records=[A])
        again = _human_case(env.ledger, tmp, "again", records=[A], kind="reconsider",
                            trigger="reconsider", supersedes=prior)
        if label == "held":
            parked = _person_parks(env.ledger, [A], tmp)
        record_before = find_record_path(env.ledger, A).read_bytes()
        head = gitops.head_sha(env.ledger)
        with ledger_ops.acting_as("steward", env.ledger):
            if label == "free":
                verbs.reconsider(env.ledger, A, case=again, by="steward", no_push=True)
                assert gitops.head_sha(env.ledger) != head
                assert any(event.get("event") == "reconsidered" for event in
                           Record.from_path(find_record_path(env.ledger, A)).history)
                continue
            with pytest.raises(verbs.VerbError) as caught:
                verbs.reconsider(env.ledger, A, case=again, by="steward", no_push=True)
        assert f"the overseer holds {A} (parked case {parked}" in str(caught.value)
        assert batch.refusal_kind(caught.value, rc=1, state="refused") == "bad-line"
        assert gitops.head_sha(env.ledger) == head
        assert find_record_path(env.ledger, A).read_bytes() == record_before


def test_1d_the_batch_preview_refuses_the_steward_as_the_run_does(tmp_path):
    """`batch.dry_run` opens the same scope from its own actor, so a
    steward preview -- here called directly, outside any steward run --
    refuses a held lesson's line as the run would (`would-refuse`,
    `bad-line`, the hold's sentence), and a person's preview of the same
    line would apply. The preview writes nothing either way."""
    env = make_env(tmp_path)
    _pending(env, A)
    parked = _person_parks(env.ledger, [A], tmp_path)
    sheet = tmp_path / "sheet.yaml"
    _dump_yaml(sheet, {"version": 1, "items": [{"id": A, "verb": "reject"}]})
    items = batch.load_sheet(sheet, home=env.ledger)
    head = gitops.head_sha(env.ledger)

    person = batch.dry_run(env.ledger, items, actor="human")  # control
    assert [(item.state, item.kind) for item in person.items] == [("would-apply", None)]
    preview = batch.dry_run(env.ledger, items, actor="steward")

    (item,) = preview.items
    assert (item.state, item.kind) == ("would-refuse", "bad-line"), item
    assert f"the overseer holds {A} (parked case {parked}" in str(item.detail)
    assert gitops.head_sha(env.ledger) == head
    assert git(env.ledger, "status", "--porcelain").stdout == ""


def test_1e_the_whole_steward_run_acts_as_the_steward(tmp_path, monkeypatch):
    """`steward.run` opens the steward's scope around the whole run, so
    anything the run asks of the ledger outside a batch -- a model session,
    the case writer, `verbs.reconsider`, the post-run recompile -- is asked
    as the steward. Read from inside the model session and inside the case
    writer; control: no scope before or after the run."""
    home = make_env(tmp_path).ledger
    _seed(home, "lrn-f4e00001")
    _enable_steward(home)
    _notifications(monkeypatch)
    seen: list[object] = []

    def write(spec):
        seen.append(("session", ledger_ops.steward_acting_home()))
        return _write_decision_stage(spec)

    real_record = cases.record

    def record(*args, **kwargs):
        seen.append(("case writer", ledger_ops.steward_acting_home()))
        return real_record(*args, **kwargs)

    monkeypatch.setattr(steward.invocation, "write_session", write)
    monkeypatch.setattr(steward.cases, "record", record)
    assert ledger_ops.steward_acting_home() is None  # control

    assert steward.run(home).status == "applied"

    assert ledger_ops.steward_acting_home() is None
    assert seen == [("session", home), ("case writer", home)], seen


def _steward_case(home: Path, tmp: Path, name: str, **fields) -> str:
    stage = tmp / f"steward-{name}.yaml"
    case = _case(fields.pop("records"), fields.pop("outcome", "reject"), "reject")
    case.update(fields)
    _dump_yaml(stage, case)
    return cases.record(home, stage, actor="steward")


def test_1c_the_case_writer_refuses_the_steward_a_case_on_a_held_lesson(tmp_path):
    """Every way the steward's case can decide or close a held lesson, each
    refused before anything is written; the control beside each lands on a
    free lesson. A note for the overseer still lands on the parked case."""
    env = make_env(tmp_path)
    home = env.ledger
    _pending(env, A)
    _pending(env, B)
    about_a = _human_case(home, tmp_path, "about-a", records=[A], outcome="reject")
    about_b = _human_case(home, tmp_path, "about-b", records=[B], outcome="reject")
    parked = _person_parks(home, [A], tmp_path)

    def refused(name: str, **fields) -> str:
        head = gitops.head_sha(home)
        files = sorted(p.name for p in (home / "cases").glob("*/case-*.md"))
        with pytest.raises(cases.HeldCaseError) as caught:
            _steward_case(home, tmp_path, name, **fields)
        assert isinstance(caught.value.__cause__, ledger_ops.HeldLessonRefusal)
        assert batch.refusal_kind(caught.value, rc=1, state="refused") == "bad-line"
        assert gitops.head_sha(home) == head
        assert sorted(p.name for p in (home / "cases").glob("*/case-*.md")) == files
        assert git(home, "status", "--porcelain").stdout == ""
        return str(caught.value)

    # a decision about the held lesson; control: the same about a free one
    assert f"the overseer holds {A}" in refused("decides-a", records=[A])
    assert _steward_case(home, tmp_path, "decides-b", records=[B])
    # a second parked case for it (gate S1c R1)
    parked_again = {"kind": "parked", "outcome": "parked", "parked_for": "overseer",
                    "parked_reason": "authority-unclear"}
    assert f"the overseer holds {A}" in refused("parks-a", records=[A], **parked_again)
    # superseding the overseer's own parked case (gate S1c D1)
    assert "a parked case the overseer has yet to decide" in refused(
        "closes-parked", records=[B], supersedes=parked)
    # superseding a decision about the held lesson (D1's second shape, R2);
    # control: superseding the decision about the free one
    assert f"{about_a} is a case about {A}" in refused(
        "closes-about-a", records=[B], supersedes=about_a)
    assert _steward_case(home, tmp_path, "closes-about-b", records=[B], supersedes=about_b)

    assert _awaiting(home) == [parked]
    # the one thing it may do: a note for the overseer, on the parked case
    record_before = find_record_path(home, A).read_bytes()
    with ledger_ops.acting_as("steward", home):
        steward._add_overseer_note(home, {"case": parked, "text": "seen twice"}, "op-1")
    later = cases.show(home, parked, evidence_only=False).sections["Later observations"]
    assert "steward examined: seen twice" in later
    assert find_record_path(home, A).read_bytes() == record_before
    assert _awaiting(home) == [parked]


# ======================================= 2. the review's findings (gate S1c)


def _write_pair(stage: Path, name: str, case: dict, items: list[dict]) -> None:
    _dump_yaml(stage / "cases" / f"{name}.yaml", case)
    _dump_yaml(stage / "sheets" / f"{name}.yaml", {"version": 1, "case": "$CASE_ID", "items": items})


def _held_and_free(tmp_path: Path, prefix: str) -> tuple[Path, str, str, str]:
    home = make_env(tmp_path).ledger
    held = _seed(home, f"{prefix}0001")
    free = _seed(home, f"{prefix}0002")
    parked = _person_parks(home, [held], tmp_path)
    _enable_steward(home)
    return home, held, free, parked


def test_finding_1_the_steward_cannot_close_the_overseers_question_by_superseding_it(
    tmp_path, monkeypatch
):
    """Gate S1c D1: the steward's case on FREE named HELD's parked case in
    `supersedes` (the brief lists its id); the case writer recorded it, which
    superseded the parked case -- the overseer's question gone, HELD
    selected again the next night for the steward to decide. Now the case
    writer refuses it: the parked case still waits, HELD stays held, and
    FREE is sent back (`bad-line`) to be decided without the `supersedes`."""
    home, held, free, parked = _held_and_free(tmp_path, "lrn-f1b0")
    _notifications(monkeypatch)

    def write(spec):
        stage = _stage_dir(spec)
        case = _case([free], "reject", "reject")
        case["supersedes"] = parked
        _write_pair(stage, "free", case, [{"id": free, "verb": "reject"}])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    result = steward.run(home)

    row = _packet(home, result.run_id)["dispositions"][free]
    assert (row["state"], row.get("kind")) == ("returned", "bad-line"), row
    assert "a parked case the overseer has yet to decide" in row["reason"]
    assert _awaiting(home) == [parked]
    parked_row = next(r for r in cases.list_cases(home) if r["case"] == parked)
    assert parked_row.get("superseded_by") is None
    assert held not in _eligible(home)
    assert _status(home, held) == "pending" and _status(home, free) == "pending"


@pytest.mark.parametrize("shape", ["collapse-loser", "route-completes-supersedes"])
def test_finding_2_a_line_cannot_change_a_held_lesson_without_naming_it(
    tmp_path, monkeypatch, shape
):
    """Gate S1c D2: two lines that change a lesson they do not name -- a
    collapse's loser, and the old record a route supersedes when its lesson
    carries `supersedes:` -- left HELD superseded with its parked case still
    waiting. The ledger now refuses each line: HELD untouched, its parked
    case still waiting, FREE sent back (`bad-line`) with the hold's words."""
    home = make_env(tmp_path).ledger
    if shape == "collapse-loser":
        free = _seed(home, "lrn-f2a00001")
        held = _seed(home, "lrn-f2a00002")
        cluster = "merge-f2a0f2a0"
        bucket = find_record_path(home, free).parent.parent
        (bucket / "proposals" / f"{cluster}.yaml").write_text(
            merge_proposal_text(cluster, [free, held], free), encoding="utf-8")
        commit_all(home, "cluster")
        line = {"id": free, "verb": "route", "collapse": cluster}
    else:
        held = _seed(home, "lrn-f2b00001")
        newer = make_behavior(record_id="lrn-f2b00002", trigger="A newer wording of it.")
        newer.set_supersedes(held)
        free = _seed(home, "lrn-f2b00002", record=newer)
        line = {"id": free, "verb": "route"}
    parked = _person_parks(home, [held], tmp_path)
    _enable_steward(home)
    _notifications(monkeypatch)
    held_before = find_record_path(home, held).read_bytes()

    def write(spec):
        _write_pair(_stage_dir(spec), "free", _case([free], "route", "route"), [line])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    result = steward.run(home)

    row = _packet(home, result.run_id)["dispositions"][free]
    assert (row["state"], row.get("kind")) == ("returned", "bad-line"), row
    assert f"the overseer holds {held} (parked case {parked}" in row["reason"]
    assert _status(home, held) == "pending" and _status(home, free) == "pending"
    assert find_record_path(home, held).read_bytes() == held_before
    assert _awaiting(home) == [parked]


def test_finding_3a_a_redrive_never_applies_a_line_whose_lesson_a_person_parked(
    tmp_path, monkeypatch
):
    """Gate S1c D3 (person): one case on X and Y, both lines busy once, so
    the recorded case is re-driven; a person parks X between the runs. The
    re-drive used to apply X's line (the case's own lessons were exempt
    from the hold). Now X's line is skipped -- the case is not refused
    whole -- so X keeps its parked case, gets a `held` row and stays
    pending, while Y's line applies.

    Gate S1d N4: with X alone in the case the skip could not be told from
    the backstops behind it (the preview, then the ledger, refuse X's line
    and give X the same `held` row). Y is what tells them apart: without
    the skip the preview holds the WHOLE case back, so Y is sent back
    instead of applied."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-f3a00001")
    y = _seed(home, "lrn-f3a00002")
    _enable_steward(home)
    _notifications(monkeypatch)

    def write(spec):
        _write_pair(_stage_dir(spec), "both", _case([x, y], "reject", "reject"),
                    [{"id": x, "verb": "reject"}, {"id": y, "verb": "reject"}])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    _dispatch_with(monkeypatch, lambda item, count: (
        _refused(item, "target-busy", "simulated: uncommitted edits") if count == 1 else None))
    first = steward.run(home)
    rows = _packet(home, first.run_id)["dispositions"]
    assert {rows[x]["state"], rows[y]["state"]} == {"unfinished"}  # control
    parked = _person_parks(home, [x], tmp_path)
    monkeypatch.setattr(steward.invocation, "write_session",
                        lambda spec: pytest.fail("a re-drive never asks the model"))

    second = steward.run(home)

    assert second.run_id == first.run_id
    rows = _packet(home, first.run_id)["dispositions"]
    assert (rows[x]["state"], rows[x].get("held_by")) == ("held", [parked]), rows[x]
    assert _status(home, x) == "pending"
    assert rows[y]["state"] == "applied", rows[y]
    assert _status(home, y) == "rejected"
    assert _awaiting(home) == [parked]
    assert _head_manifest(home, first.run_id)["status"] == "complete"


def test_finding_3b_a_redrive_skips_the_line_of_a_lesson_it_parked_itself(
    tmp_path, monkeypatch
):
    """Gate S1c D3 (own park): one case on X and Y; X's line needs a person
    (parked now: its successor case holds it); Y's target is busy, so the
    case is re-driven. The person then fixes what X needed. The re-drive
    re-sent X's line and applied it while its parked case waited. Now X's
    line is skipped and X keeps its `abandoned` row and its one parked case;
    Y's line applies."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-f3b00001")
    y = _seed(home, "lrn-f3b00002")
    _enable_steward(home)
    _notifications(monkeypatch)

    def write(spec):
        _write_pair(_stage_dir(spec), "both", _case([x, y], "reject", "reject"),
                    [{"id": x, "verb": "reject"}, {"id": y, "verb": "reject"}])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    fixed: list[bool] = []
    _dispatch_with(monkeypatch, lambda item, count: (
        (_refused(item, "needs-person", "simulated: a person must fix this") if not fixed else None)
        if item.id == x
        else _refused(item, "target-busy", "simulated: uncommitted edits") if count == 1 else None))
    first = steward.run(home)
    rows = _packet(home, first.run_id)["dispositions"]
    successor = rows[x]["successor_case"]  # control: X parked now, by this run
    assert rows[y]["state"] == "unfinished"  # control: Y is why the case is re-driven
    fixed.append(True)
    monkeypatch.setattr(steward.invocation, "write_session",
                        lambda spec: pytest.fail("a re-drive never asks the model"))

    steward.run(home)

    rows = _packet(home, first.run_id)["dispositions"]
    assert rows[x]["state"] == "abandoned" and rows[x]["successor_case"] == successor
    assert rows[y]["state"] == "applied", rows[y]
    assert _status(home, x) == "pending" and _status(home, y) == "rejected"
    assert [row["case"] for row in _open_parked(home, x)] == [successor]


def test_finding_4_a_lesson_parked_during_a_run_leaves_its_inputs(tmp_path, monkeypatch):
    """Gate S1c D4: a person parks X while the model decides X and Y; the
    model obeys the hold and writes nothing for X. X stayed an input: the
    next attempts listed it (as an input AND as held), the obeying model
    covered it with no case, and the cap parked it a second time and told
    the user the run decided none of them. Now X gets a `held` row in the
    same run, the run completes, no further model call is made for X --
    not even a repair turn asking for a case on it -- and X has one parked
    case."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-f4b00001")
    y = _seed(home, "lrn-f4b00002")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    by_hand: list[str] = []
    briefs: list[list[str]] = []

    def write(spec):
        if not by_hand:
            by_hand.append(_person_parks(home, [x], tmp_path))
        ids = _ids(spec.prompt)
        briefs.append(ids)
        stage = _stage_dir(spec)
        for rid in ids:
            if rid not in cases.held_lessons(home):
                _write_pair(stage, rid, _case([rid], "reject", "reject"),
                            [{"id": rid, "verb": "reject"}])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    first = steward.run(home)
    later = [steward.run(home).status for _night in range(3)]

    rows = _packet(home, first.run_id)["dispositions"]
    assert (rows[x]["state"], rows[x].get("held_by")) == ("held", by_hand), rows[x]
    assert rows[y]["state"] == "applied"
    assert _head_manifest(home, first.run_id)["status"] == "complete"
    assert first.status == "applied", first
    assert later == ["idle", "idle", "idle"]
    # one model call: no repair turn asks the model to cover the lesson it
    # was told to leave alone, and no later attempt is made for it
    assert briefs == [[x, y]], briefs
    assert [row["case"] for row in _open_parked(home, x)] == by_hand
    assert sent == []
    assert _status(home, x) == "pending"


def test_finding_4_the_next_attempts_brief_no_longer_lists_a_held_input(tmp_path, monkeypatch):
    """Gate S1c D4 (night 2's brief): the first attempt writes nothing; a
    person parks X meanwhile. The next attempt's brief listed X both as an
    input and under LESSONS THE OVERSEER HOLDS. Now X is dropped before the
    attempt: only Y is an input; X appears under the held list only."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-f4c00001")
    y = _seed(home, "lrn-f4c00002")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []
    by_hand: list[str] = []

    def write(spec):
        prompts.append(spec.prompt)
        if not by_hand:
            by_hand.append(_person_parks(home, [x], tmp_path))
        return _ok()  # writes no case at all

    monkeypatch.setattr(steward.invocation, "write_session", write)
    first = steward.run(home)
    steward.run(home)

    assert _ids(prompts[0]) == [x, y]  # control: both were inputs at first
    last = prompts[-1]
    assert _ids(last) == [y], _ids(last)
    held_block = last.split(steward_prompt.HELD_TITLE, 1)[1][:600]
    assert f"- {x}: {by_hand[0]} (authority-unclear)" in held_block
    row = _packet(home, first.run_id)["dispositions"][x]
    assert row["state"] == "held", row


# Gate S1c R1: three paths that skipped the never-parked-twice check. Each
# lesson keeps exactly the person's parked case.


def test_risk_1a_a_parked_yaml_entry_on_a_held_lesson_is_refused(tmp_path, monkeypatch):
    """The model's `parked.yaml` naming a held lesson: the maintenance
    operation is refused (the case writer's hold), the lesson keeps its one
    parked case, and the run's own decision on the free lesson applies."""
    _notifications(monkeypatch)
    home, held, free, parked = _held_and_free(tmp_path, "lrn-f5a0")

    def parked_yaml(spec):
        stage = _stage_dir(spec)
        _write_pair(stage, "free", _case([free], "reject", "reject"),
                    [{"id": free, "verb": "reject"}])
        entry = _case([held], "defer", "defer")
        entry.pop("kind")
        entry.pop("outcome")
        entry["parked_reason"] = "authority-unclear"
        entry["decision"]["confidence"] = "provisional"
        _dump_yaml(stage / "parked.yaml", {"entries": [entry]})
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", parked_yaml)
    result = steward.run(home)
    (operation,) = [op for op in _packet(home, result.run_id)["maintenance"]
                    if op["kind"] == "parked-case"]
    assert operation["state"] == "refused", operation
    assert f"the overseer holds {held}" in operation["result"]["error"]
    assert [row["case"] for row in _open_parked(home, held)] == [parked]
    assert _status(home, free) == "rejected"  # control: the run did apply


def test_risk_1b_a_model_parked_case_on_a_lesson_parked_mid_run_is_not_recorded(
    tmp_path, monkeypatch
):
    """The model parks X (`kind: parked`) while a person parks it during
    the same session: the case writer refuses the model's case, X gets a
    `held` row, and X keeps the person's one parked case."""
    _notifications(monkeypatch)
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-f5b00001")
    _enable_steward(home)
    by_hand: list[str] = []

    def model_parks(spec):
        if not by_hand:
            by_hand.append(_person_parks(home, [x], tmp_path))
        case = _case([x], "defer", "defer")
        case.update(kind="parked", outcome="parked", parked_reason="authority-unclear")
        case["decision"]["confidence"] = "provisional"
        _write_pair(_stage_dir(spec), "x", case, [{"id": x, "verb": "reject"}])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", model_parks)
    result = steward.run(home)
    row = _packet(home, result.run_id)["dispositions"][x]
    assert (row["state"], row.get("held_by")) == ("held", by_hand), row
    assert [r["case"] for r in _open_parked(home, x)] == by_hand


def test_risk_1c_the_cap_close_out_does_not_park_a_held_lesson_again(tmp_path, monkeypatch):
    """Every model call fails; a person parks X during the attempt that
    reaches the cap, so the close-out at the end of that run is the first
    to see it held: X gets a `held` row, no `attempts-exhausted` case."""
    _notifications(monkeypatch)
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-f5c00001")
    _enable_steward(home)
    calls: list[int] = []
    person: list[str] = []

    def failing(spec):
        calls.append(1)
        if len(calls) == 3:
            person.append(_person_parks(home, [x], tmp_path))
        return _transport_failure(spec)

    monkeypatch.setattr(steward.invocation, "write_session", failing)
    runs = [steward.run(home) for _night in range(3)]
    assert len(calls) == 3 and person  # control: three attempts, the cap
    (run_id,) = {run.run_id for run in runs}
    manifest = _head_manifest(home, run_id)
    assert manifest["packets"][0]["phase"] == "abandoned"  # control: closed out
    row = manifest["packets"][0]["dispositions"][x]
    assert (row["state"], row.get("held_by")) == ("held", person), row
    assert [(r["case"], r.get("parked_reason")) for r in _open_parked(home, x)] == [
        (person[0], "authority-unclear")]
    assert cases.list_cases(home, record_id=x, parked_reason="attempts-exhausted") == []


def test_risk_2_a_held_lessons_observation_is_not_used_up_by_a_sibling(tmp_path, monkeypatch):
    """Gate S1c R2: case P routed A and moved B; a person parks A; a
    statement observation lands on P. B was proposed alone, its case took P
    as predecessor (superseding P) and the run consumed the observation, so
    once the overseer let A go nothing brought A back. Now P waits whole
    while A is held: B is not proposed from it, P is not superseded, the
    observation is not consumed -- and after the release both come back."""
    home = make_env(tmp_path).ledger
    a = _seed(home, "lrn-f6a00001")
    b = _seed(home, "lrn-f6a00002")
    st = statements.add(home, verbatim="Mixed.", source={"message_ref": "transcript:m#L1"},
                        recorded_by="human")
    stage = tmp_path / "prior.yaml"
    prior_case = _case([a, b], "route", "route")
    prior_case.update(evidence=[{"ref": st, "quote": "Mixed"}],
                      dependencies={**_NO_DEPS, "statements": [st]})
    _dump_yaml(stage, prior_case)
    prior = cases.record(home, stage, actor="steward")
    verbs.route(home, a, dest="skill-md", by="steward", no_push=True)
    verbs.rehome(home, b, to="user", by="steward", no_push=True)
    parked = _person_parks(home, [a], tmp_path)
    cases.observe(home, prior, "statement", text="more", ref=st, by="steward")
    _enable_steward(home)
    _notifications(monkeypatch)
    with pytest.MonkeyPatch.context() as no_hold:  # positive control
        no_hold.setattr(cases, "held_lessons", lambda home_: {})
        would = {e.record.id for e, _c in steward._reconsider_proposals(home)[0]}
    assert {a, b} <= would

    assert steward._reconsider_proposals(home)[0] == []
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    result = steward.run(home)

    assert _head_manifest(home, result.run_id).get("reconsider_observations") == []
    prior_row = next(r for r in cases.list_cases(home) if r["case"] == prior)
    assert prior_row.get("superseded_by") is None
    _overseer_decides(home, parked, [a], tmp_path)
    after = {e.record.id for e, _c in steward._reconsider_proposals(home)[0]}
    assert a in after, after


def test_risk_3_the_overseers_release_makes_the_steward_due(tmp_path, monkeypatch):
    """Gate S1c R3 (and the review's nit on the round-3 scheduler test,
    whose closing `is True` came from having no prior run at all): a held
    lesson's file is older than the steward's last run, so its release made
    nothing due -- it waited for an unrelated input. Now the release does,
    a week on, past the cooldown; and with nothing released it does not."""
    home = make_env(tmp_path).ledger
    held = _seed(home, "lrn-f7a00001")
    _seed(home, "lrn-f7a00002")
    parked = _person_parks(home, [held], tmp_path)
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    time.sleep(1.1)
    assert steward.run(home).status == "applied"  # the prior run decides the other lesson
    assert steward.last_run_iso(home) is not None  # control: there IS a prior run
    cache = tmp_path / "serve-cache"
    cache.mkdir()
    later = time.time() + 7 * 86400
    assert serve._steward_is_due(home, cache, later) is False  # still held: not due

    time.sleep(1.1)
    _overseer_decides(home, parked, [held], tmp_path)
    assert held in _eligible(home)  # control: released, still undecided
    assert serve._steward_is_due(home, cache, later) is True


def test_risk_4_a_tampered_parked_case_still_holds_its_lesson_and_says_so(
    tmp_path, monkeypatch
):
    """Gate S1c R4: a parked case whose file fails its freeze-hash check
    was left out of the overseer's queue AND of the hold, so the steward
    would decide its lesson as if it had never been parked. Now the lesson
    stays held (fail closed); the brief names the case and why; the user is
    told once, with the case ids, that a person must repair it."""
    home = make_env(tmp_path).ledger
    held = _seed(home, "lrn-f8a00001")
    other = _seed(home, "lrn-f8a00002")
    parked = _person_parks(home, [held], tmp_path)
    path = next((home / "cases").glob(f"*/{parked}.md"))
    path.write_text(path.read_text(encoding="utf-8").replace(
        "what should become of", "WHAT should become of", 1), encoding="utf-8")
    commit_all(home, "tamper")
    _enable_steward(home)
    sent = _notifications(monkeypatch)
    assert [r.get("frozen_ok") for r in cases.list_cases(home) if r["case"] == parked] == [False]
    assert _awaiting(home) == []  # the overseer cannot take it

    assert held in cases.held_lessons(home)
    assert held not in _eligible(home) and other in _eligible(home)
    prompts: list[str] = []

    def write(spec):
        prompts.append(spec.prompt)
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", write)
    steward.run(home)
    steward.run(home)

    assert _ids(prompts[0]) == [other]
    assert f"- {held}: {parked} (authority-unclear; its file fails its freeze-hash check)" \
        in prompts[0]
    told = [summary for _cue, summary, _ids_ in sent if "freeze-hash" in summary]
    assert len(told) == 1 and parked in told[0], sent  # once, not every run
    # gate S1d N1: the one repair that works, and only that -- deciding the
    # lesson does not lift the hold, and nobody can supersede the case
    assert "restores each case file from git history" in told[0], told[0]
    assert "by hand" not in told[0], told[0]
    assert _status(home, held) == "pending"


def test_nit_a_refused_note_does_not_make_the_run_partial(tmp_path, monkeypatch):
    """Gate S1c nit: a note on a case the overseer is not holding is refused
    -- journaled and on the run record -- but it is fact-finding that did not
    land, not a refusal of the run's work: the run that decided its lesson
    is `applied`, with nothing counted refused."""
    home, held, free, parked = _held_and_free(tmp_path, "lrn-f9a0")
    _notifications(monkeypatch)

    def write(spec):
        stage = _stage_dir(spec)
        _write_pair(stage, "free", _case([free], "reject", "reject"),
                    [{"id": free, "verb": "reject"}])
        _dump_yaml(stage / "overseer-notes.yaml",
                   {"entries": [{"case": "case-00000000", "text": "not a parked case"}]})
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    result = steward.run(home)

    (note,) = [op for op in _packet(home, result.run_id)["maintenance"] if op["kind"] == "note"]
    assert note["state"] == "refused"  # positive control: the note was refused
    assert (result.status, result.refused) == ("applied", 0), result
    assert _status(home, free) == "rejected"


# ================================ 3. the gate's findings on 0694eb0 (gate S1d)


def _two_lesson_case(x: str, y: str):
    def write(spec):
        _write_pair(_stage_dir(spec), "both", _case([x, y], "reject", "reject"),
                    [{"id": x, "verb": "reject"}, {"id": y, "verb": "reject"}])
        return _ok()

    return write


def _no_model(spec):
    pytest.fail("a re-drive never asks the model")


def test_s1d_d1_a_redrive_after_the_release_never_sends_the_pre_hold_line(
    tmp_path, monkeypatch
):
    """Gate S1d D1 (its probe P1): one case on X and Y, re-driven twice (X
    busy once, Y twice). A person parks X after run 1, so run 2 skips X's
    line and gives X `held`. The overseer then decides X's parked case,
    leaving X pending. Run 3 -- the same run, re-driven again -- used to
    send X's line from before the hold: X rejected by a decision no session
    made after the overseer's ruling, its `held` row overwritten. Now the
    line is never sent again, X keeps `held` and stays pending (the next
    run decides it afresh), and Y applies."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-fa100001")
    y = _seed(home, "lrn-fa100002")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(steward.invocation, "write_session", _two_lesson_case(x, y))
    seen = _dispatch_with(monkeypatch, lambda item, count: (
        _refused(item, "target-busy", "simulated: uncommitted edits")
        if (item.id == x and count == 1) or (item.id == y and count <= 2) else None))
    first = steward.run(home)
    parked = _person_parks(home, [x], tmp_path)
    monkeypatch.setattr(steward.invocation, "write_session", _no_model)
    steward.run(home)
    row = _packet(home, first.run_id)["dispositions"][x]
    assert (row["state"], row.get("held_by")) == ("held", [parked]), row  # control
    _overseer_decides(home, parked, [x], tmp_path)
    assert x in _eligible(home)  # control: released and undecided

    third = steward.run(home)

    assert third.run_id == first.run_id
    rows = _packet(home, first.run_id)["dispositions"]
    assert (rows[x]["state"], rows[x].get("held_by")) == ("held", [parked]), rows[x]
    assert _status(home, x) == "pending"
    assert rows[y]["state"] == "applied" and _status(home, y) == "rejected"
    assert seen[f"1:{x}"] == 1, seen  # X's line went out in run 1 only
    assert _head_manifest(home, first.run_id)["status"] == "complete"
    assert x in _eligible(home)  # the next run decides it, seeing the ruling


def test_s1d_d1_a_redrive_after_the_overseer_decides_an_own_park_never_sends_the_line(
    tmp_path, monkeypatch
):
    """Gate S1d D1 (its probe P1b): this run parked X itself (needs a
    person), Y was busy, so the case is re-driven. Before the re-drive the
    overseer decides X's successor case leaving X pending, and the person
    has fixed what X needed. The re-drive used to send X's line: X rejected
    while the run record still said `abandoned` with its successor -- the
    record and the ledger disagreed. Now X's line is not sent: X stays
    pending with its `abandoned` row, the two agree, and Y applies."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-fa1b0001")
    y = _seed(home, "lrn-fa1b0002")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(steward.invocation, "write_session", _two_lesson_case(x, y))
    fixed: list[bool] = []
    seen = _dispatch_with(monkeypatch, lambda item, count: (
        (_refused(item, "needs-person", "simulated: a person must fix this") if not fixed else None)
        if item.id == x
        else _refused(item, "target-busy", "simulated: uncommitted edits") if count == 1 else None))
    first = steward.run(home)
    successor = _packet(home, first.run_id)["dispositions"][x]["successor_case"]  # control
    _overseer_decides(home, successor, [x], tmp_path)
    fixed.append(True)
    monkeypatch.setattr(steward.invocation, "write_session", _no_model)

    steward.run(home)

    rows = _packet(home, first.run_id)["dispositions"]
    assert (rows[x]["state"], rows[x]["successor_case"]) == ("abandoned", successor), rows[x]
    assert _status(home, x) == "pending"  # the ledger agrees with the row
    assert rows[y]["state"] == "applied" and _status(home, y) == "rejected"
    assert seen[f"1:{x}"] == 1, seen


def test_s1d_r1_a_held_lesson_is_decided_after_the_overseer_lets_it_go(tmp_path, monkeypatch):
    """Gate S1d R1 (its probe P5): the central promise of `held` -- "the
    version undecided, so the next run selects it again". A person parks X
    while the model decides X and Y; X gets `held`. The overseer decides
    the parked case leaving X pending: X is eligible again, the scheduler is
    due, and the next run decides it. (Counting `held` as a decision would
    leave every lesson ever held unselected for good.)"""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-fa500001")
    _seed(home, "lrn-fa500002")
    _enable_steward(home)
    _notifications(monkeypatch)
    by_hand: list[str] = []

    def write(spec):
        if not by_hand:
            by_hand.append(_person_parks(home, [x], tmp_path))
        stage = _stage_dir(spec)
        for rid in _ids(spec.prompt):
            if rid not in cases.held_lessons(home):
                _write_pair(stage, rid, _case([rid], "reject", "reject"),
                            [{"id": rid, "verb": "reject"}])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    first = steward.run(home)
    assert _packet(home, first.run_id)["dispositions"][x]["state"] == "held"  # control
    assert x not in _eligible(home)  # control: held, not selectable
    time.sleep(1.1)
    _overseer_decides(home, by_hand[0], [x], tmp_path)

    assert x in _eligible(home)
    cache = tmp_path / "serve-cache"
    cache.mkdir()
    assert serve._steward_is_due(home, cache, time.time() + 7 * 86400) is True
    second = steward.run(home)
    assert second.run_id != first.run_id
    assert _status(home, x) == "rejected"


def test_s1d_r2_a_release_while_a_run_is_unfinished_makes_the_steward_due(
    tmp_path, monkeypatch
):
    """Gate S1d R2 (its probe P8): X is held; the run on Y is left
    unfinished (busy). The overseer lets X go while that run is unfinished;
    the next run resumes it (selecting nothing new), applies Y and writes
    the last-run marker. The due check measured from that END, after the
    release, so X waited for an unrelated input. Now it measures from the
    last run that SELECTED inputs: the steward is due for X."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-fa800001")
    _seed(home, "lrn-fa800002")
    parked = _person_parks(home, [x], tmp_path)
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    _dispatch_with(monkeypatch, lambda item, count: (
        _refused(item, "target-busy", "simulated: uncommitted edits") if count == 1 else None))
    time.sleep(1.1)
    first = steward.run(home)
    assert _head_manifest(home, first.run_id)["status"] != "complete"  # control: unfinished
    time.sleep(1.1)
    _overseer_decides(home, parked, [x], tmp_path)
    time.sleep(1.1)
    second = steward.run(home)
    assert second.run_id == first.run_id  # control: a resume, which selects nothing
    assert _head_manifest(home, first.run_id)["status"] == "complete"
    assert x in _eligible(home)
    cache = tmp_path / "serve-cache"
    cache.mkdir()

    assert serve._steward_is_due(home, cache, time.time() + 7 * 86400) is True


def test_s1d_r2_a_completed_run_with_nothing_new_is_not_due(tmp_path, monkeypatch):
    """The control for R2's change: measuring from the last selection must
    not make the steward due for work every run already saw. A run selects
    X and sends it back (a bad line); nothing else changes: not due, even a
    week later. And a lesson committed after that run started is new
    work."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-fa810001")
    _enable_steward(home)
    _notifications(monkeypatch)
    time.sleep(1.1)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)
    _dispatch_with(monkeypatch, lambda item, count: _refused(item, "bad-line", "simulated"))
    first = steward.run(home)
    assert _packet(home, first.run_id)["dispositions"][x]["state"] == "returned"  # control
    assert x in _eligible(home)  # still to decide, but already seen
    cache = tmp_path / "serve-cache"
    cache.mkdir()
    later = time.time() + 7 * 86400
    assert serve._steward_is_due(home, cache, later) is False

    time.sleep(1.1)
    _seed(home, "lrn-fa810002")
    assert serve._steward_is_due(home, cache, later) is True


def test_s1d_n5_release_epochs_read_only_the_eligible_lessons_cases(tmp_path, monkeypatch):
    """Gate S1d N5: the release times are computed for the eligible inputs'
    lessons only -- a released parked case about a lesson a person has
    since decided is never read on a tick. Control: the eligible lesson's
    released case is read."""
    home = make_env(tmp_path).ledger
    free = _seed(home, "lrn-fa5a0001")
    gone = _seed(home, "lrn-fa5a0002")
    p_free = _person_parks(home, [free], tmp_path)
    p_gone = _person_parks(home, [gone], tmp_path)
    _overseer_decides(home, p_free, [free], tmp_path)
    _overseer_decides(home, p_gone, [gone], tmp_path)
    verbs.reject(home, gone, no_push=True)
    assert free in _eligible(home) and gone not in _eligible(home)  # control
    read: list[str] = []
    real = serve._input_commit_epoch

    def recording(home_, path):
        read.append(path.name)
        return real(home_, path)

    monkeypatch.setattr(serve, "_input_commit_epoch", recording)

    epochs = serve._release_epochs(home, {free})

    assert f"{p_free}.md" in read  # control: the eligible lesson's case is read
    assert f"{p_gone}.md" not in read, read
    assert set(epochs) == {free}


def test_s1d_n4_a_line_applied_before_the_hold_stays_applied(tmp_path, monkeypatch):
    """Gate S1d N4 (its M19): X's line applies in run 1; Y's is busy, so the
    case is re-driven; a person then parks X (already rejected). The
    re-drive must keep X `applied` -- its line landed before any hold --
    not turn it into `held`."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-fa190001")
    y = _seed(home, "lrn-fa190002")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(steward.invocation, "write_session", _two_lesson_case(x, y))
    _dispatch_with(monkeypatch, lambda item, count: (
        _refused(item, "target-busy", "simulated: uncommitted edits")
        if item.id == y and count == 1 else None))
    first = steward.run(home)
    rows = _packet(home, first.run_id)["dispositions"]
    assert rows[x]["state"] == "applied" and rows[y]["state"] == "unfinished"  # control
    parked = _person_parks(home, [x], tmp_path)
    assert x in cases.held_lessons(home)  # control: X is held at the re-drive
    monkeypatch.setattr(steward.invocation, "write_session", _no_model)

    steward.run(home)

    rows = _packet(home, first.run_id)["dispositions"]
    assert rows[x]["state"] == "applied", rows[x]
    assert rows[y]["state"] == "applied"
    assert _status(home, x) == "rejected"
    assert _awaiting(home) == [parked]


def test_s1d_n4_the_repair_turn_names_a_case_the_case_writer_would_refuse(
    tmp_path, monkeypatch
):
    """Gate S1d N4 (its M22): the steward's case on FREE supersedes the
    overseer's parked case on HELD (finding 1's shape). Before the case
    writer refuses it at apply time, the repair turn tells the model why,
    under its own heading, so the model can drop the `supersedes`."""
    home, held, free, parked = _held_and_free(tmp_path, "lrn-fa22")
    _notifications(monkeypatch)
    prompts: list[str] = []

    def write(spec):
        prompts.append(spec.prompt)
        case = _case([free], "reject", "reject")
        case["supersedes"] = parked
        _write_pair(_stage_dir(spec), "free", case, [{"id": free, "verb": "reject"}])
        return _ok()

    monkeypatch.setattr(steward.invocation, "write_session", write)
    steward.run(home)

    assert len(prompts) == 2, len(prompts)  # control: a repair turn was asked for
    repair = prompts[1].split("=== repair ===", 1)[1]
    assert "The case writer would refuse these cases as written:" in repair
    assert f"supersedes {parked}, a case about {held}, which the overseer holds" in repair


def test_s1d_n4_a_redriven_reconsider_case_skips_the_held_lesson_and_applies_the_rest(
    tmp_path, monkeypatch
):
    """Gate S1d N4 (its M23): a `kind: reconsider` case on B and A is
    recorded, and the run is killed after B's reconsider entry landed and
    before A's. A person parks A; the run is resumed. The reconsider loop
    skips A -- it never asks the ledger to mark a held lesson reconsidered
    (the ledger would refuse, and with it the whole case) -- so B's lines
    apply and A's are skipped, A taking `held`."""
    home = make_env(tmp_path).ledger
    a = _seed(home, "lrn-fa230001")
    b = _seed(home, "lrn-fa230002")
    statement = statements.add(home, verbatim="Changed dependency.",
                               source={"message_ref": "transcript:reconsider#L1"},
                               recorded_by="human")
    stage = tmp_path / "prior.yaml"
    prior = _case([a, b], "reject", "reject")
    prior.update(trigger="human", evidence=[{"ref": statement, "quote": "old"}],
                 dependencies={**_NO_DEPS, "statements": [statement]})
    _dump_yaml(stage, prior)
    prior_id = cases.record(home, stage, actor="human")
    for rid in (a, b):
        verbs.reject(home, rid, by="human", no_push=True)
    cases.observe(home, prior_id, "statement", text="changed", ref=statement, by="steward")
    _enable_steward(home)
    _notifications(monkeypatch)

    def write(spec):
        case = _case([b, a], "defer", "defer")
        case.update(kind="reconsider", trigger="reconsider",
                    evidence=[{"ref": statement, "quote": "changed"}],
                    dependencies={**_NO_DEPS, "statements": [statement]})
        _write_pair(_stage_dir(spec), "both", case, [
            {"id": b, "verb": "reopen"}, {"id": b, "verb": "defer"},
            {"id": a, "verb": "reopen"}, {"id": a, "verb": "defer"},
        ])
        return _ok()

    real_reconsider = steward.verbs.reconsider
    marked: list[str] = []

    def kill_after_first(home_, rid, **kwargs):
        outcome = real_reconsider(home_, rid, **kwargs)
        marked.append(rid)
        if len(marked) == 1:
            raise SimulatedKill()
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", write)
    monkeypatch.setattr(steward.verbs, "reconsider", kill_after_first)
    with pytest.raises(SimulatedKill):
        steward.run(home)
    assert marked == [b]  # control: B marked, A not yet
    shutil.rmtree(steward.cache_dir(home))
    parked = _person_parks(home, [a], tmp_path)
    monkeypatch.setattr(steward.invocation, "write_session", _no_model)

    result = steward.run(home)

    assert _status(home, b) == "deferred", result
    assert _status(home, a) == "rejected"
    row = _packet(home, result.run_id)["dispositions"][a]
    assert (row["state"], row.get("held_by")) == ("held", [parked]), row
    history = Record.from_path(find_record_path(home, a)).history
    assert not any(event.get("event") == "reconsidered" for event in history)


def test_s1d_n4_a_lesson_sent_back_then_parked_does_not_hold_the_redrive_back(
    tmp_path, monkeypatch
):
    """The other half of the re-drive skip: a lesson held NOW whose row
    this run did not end. X's line is the steward's mistake (sent back,
    `returned`) and Y's target is busy, so the case is re-driven; a person
    then parks X. X's line is not sent again -- were it previewed, the
    ledger would refuse it as held and the preview would hold the whole
    case back, sending Y back with it. Y applies; X takes `held`."""
    home = make_env(tmp_path).ledger
    x = _seed(home, "lrn-fa3c0001")
    y = _seed(home, "lrn-fa3c0002")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(steward.invocation, "write_session", _two_lesson_case(x, y))
    _dispatch_with(monkeypatch, lambda item, count: (
        _refused(item, "bad-line", "simulated: the steward's own mistake") if item.id == x
        else _refused(item, "target-busy", "simulated: uncommitted edits") if count == 1
        else None))
    first = steward.run(home)
    rows = _packet(home, first.run_id)["dispositions"]
    assert (rows[x]["state"], rows[y]["state"]) == ("returned", "unfinished")  # control
    parked = _person_parks(home, [x], tmp_path)
    monkeypatch.setattr(steward.invocation, "write_session", _no_model)

    steward.run(home)

    rows = _packet(home, first.run_id)["dispositions"]
    assert rows[y]["state"] == "applied", rows[y]
    assert _status(home, y) == "rejected"
    assert (rows[x]["state"], rows[x].get("held_by")) == ("held", [parked]), rows[x]
    assert _status(home, x) == "pending"
