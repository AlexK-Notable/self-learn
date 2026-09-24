"""The two defects S-71's refusal catalogue found (the refusal-kinds unit,
§8), each driven through `batch.run` on a scratch ledger:

1. A routed lesson carries the route line's `note:` as its
   `resolution_note`. A later `retire` or `supersede` written with a `note:`
   of its own (the steward writes one on every line) used to be refused by
   the write-once field every time. Now the earlier note moves into
   `history` (`event: "resolution"`, with the status it was written under)
   and the new note is stored.
2. A malformed `hosts.yaml`, or a record file that no longer reads back,
   used to raise straight out of `batch.run` and end the whole sheet. Now
   that item is refused with kind `needs-person` and the sheet goes on.
3. The fold after the phase 1-4 review: the same for every other
   `hosts.yaml` read a sheet verb reaches first (retiring or superseding a
   hook-routed lesson, a project-scope hook route, rehome/rescope targets),
   for a SECOND record a verb reads (supersede's replacement and the records
   down its `superseded_by` chain, route's predecessor), and for the
   continuation run the steward and the overseer use.

All ledger homes are throwaway sandbox repos under pytest tmpdirs
(`support.make_env`), never the real `~/.self-learn`.
"""

from __future__ import annotations

import pytest

from self_learn import batch, verbs
from self_learn.ledger_ops import (
    create_record,
    find_record_path,
    stamp_proposal,
    write_proposal,
)
from self_learn.records import Record
from support import commit_all, make_behavior, make_env, proposal_dict

from test_route_hook import TRIGGER, hook_proposal


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


def _env(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    return env


def _seed(home, rid, *, scope="skill:s", project_path=None, proposal=True):
    create_record(home, make_behavior(record_id=rid, scope=scope), project_path=project_path)
    if project_path is None and proposal:
        write_proposal(home, rid, proposal_dict(scope=scope))
    commit_all(home, f"seed {rid}")
    return rid


def _run(home, tmp_path, body, name="sheet.yaml"):
    path = tmp_path / name
    path.write_text("version: 1\nitems:\n" + body, encoding="utf-8")
    return batch.run(home, batch.load_sheet(path), no_push=True)


def _record(home, rid):
    return Record.from_path(find_record_path(home, rid))


def _route_with_note(env, tmp_path, rid, note):
    result = _run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: route\n    dest: skill-md\n    note: {note}\n",
        name="route.yaml",
    )
    item = result.items[0]
    assert item.state == "applied", (item.state, item.detail)
    assert _record(env.ledger, rid).resolution_note == note


# ------------------------------------- 1. write-once resolution_note


def _assert_first_note_displaced(record, first, second):
    assert record.resolution_note == second
    displaced = [
        h for h in record.history
        if h.get("event") == "resolution" and h.get("note") == first
    ]
    assert len(displaced) == 1, record.history
    assert displaced[0].get("status") == "routed"


def test_a_routed_lesson_retired_with_a_note_keeps_both_notes(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-d0000001")
    _route_with_note(env, tmp_path, rid, "routed by the first run")

    result = _run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: retire\n    covered_by: skill-md:s\n"
        "    note: retired by a later run\n",
        name="retire.yaml",
    )
    item = result.items[0]
    assert item.state == "applied", (item.state, item.detail)
    record = _record(env.ledger, rid)
    assert record.status == "superseded"
    _assert_first_note_displaced(
        record, "routed by the first run", "retired by a later run"
    )


def test_a_routed_lesson_superseded_with_a_note_keeps_both_notes(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    old = _seed(env.ledger, "lrn-d0000002")
    new = _seed(env.ledger, "lrn-d0000003")
    _route_with_note(env, tmp_path, old, "routed by the first run")

    result = _run(
        env.ledger, tmp_path,
        f"  - id: {old}\n    verb: supersede\n    new_id: {new}\n"
        "    note: superseded by a later run\n",
        name="supersede.yaml",
    )
    item = result.items[0]
    assert item.state == "applied", (item.state, item.detail)
    record = _record(env.ledger, old)
    assert record.status == "superseded"
    assert record.superseded_by == new
    _assert_first_note_displaced(
        record, "routed by the first run", "superseded by a later run"
    )


def test_a_resolution_without_a_note_leaves_the_route_note_in_place(tmp_path, monkeypatch):
    """The displacement happens only when a NEW note arrives: a retire with
    no `note:` keeps the route's note where it was, as before."""
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-d0000004")
    _route_with_note(env, tmp_path, rid, "routed by the first run")

    result = _run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: retire\n    covered_by: skill-md:s\n",
        name="retire.yaml",
    )
    assert result.items[0].state == "applied", result.items[0].detail
    record = _record(env.ledger, rid)
    assert record.resolution_note == "routed by the first run"
    assert not [h for h in record.history if h.get("event") == "resolution"]


# ------------------------------- 2. a bad hosts.yaml / a corrupt record


#: One row per `load_hosts` call the unit wraps: the route destination that
#: reaches it first, and whether the lesson is project-scoped.
_HOSTS_SITES = [
    pytest.param("skill-md", False, id="skill-md-skill-dir"),
    pytest.param("claude-md", False, id="claude-md-skills-root"),
    pytest.param("new-skill:fresh", False, id="new-skill-skills-root"),
    pytest.param("claude-md", True, id="claude-md-project-host-registered"),
]


@pytest.mark.parametrize("dest, project", _HOSTS_SITES)
def test_a_malformed_hosts_yaml_refuses_only_the_item_that_needs_it(
    tmp_path, monkeypatch, dest, project
):
    env = _env(tmp_path, monkeypatch)
    if project:
        needs_hosts = _seed(
            env.ledger, "lrn-d0000005", scope="project", project_path=env.host
        )
    else:
        needs_hosts = _seed(env.ledger, "lrn-d0000005")
    plain = _seed(env.ledger, "lrn-d0000006")
    (env.ledger / "hosts.yaml").write_text("skills_root: [unclosed\n", encoding="utf-8")

    result = _run(
        env.ledger, tmp_path,
        f"  - id: {needs_hosts}\n    verb: route\n    dest: {dest}\n"
        f"  - id: {plain}\n    verb: reject\n",
    )
    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert "hosts.yaml" in (first.detail or "")
    assert first.kind == "needs-person"
    assert second.state == "applied", (second.state, second.detail)
    assert _record(env.ledger, plain).status == "rejected"


def test_a_record_file_that_no_longer_reads_back_refuses_that_item_only(
    tmp_path, monkeypatch
):
    env = _env(tmp_path, monkeypatch)
    broken = _seed(env.ledger, "lrn-d0000007")
    fine = _seed(env.ledger, "lrn-d0000008")
    path = find_record_path(env.ledger, broken)
    path.write_text(
        path.read_text(encoding="utf-8").replace("status: pending", "status: nonsense", 1),
        encoding="utf-8",
    )
    commit_all(env.ledger, "a hand edit that breaks the record")

    result = _run(
        env.ledger, tmp_path,
        f"  - id: {broken}\n    verb: reject\n  - id: {fine}\n    verb: reject\n",
    )
    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert str(path) in (first.detail or "")
    assert first.kind == "needs-person"
    assert second.state == "applied", (second.state, second.detail)

    # The preview says the same thing and also goes on.
    preview = batch.dry_run(
        env.ledger,
        batch.load_sheet(tmp_path / "sheet.yaml"),
    )
    p_first, p_second = preview.items
    assert p_first.state == "would-refuse"
    assert p_first.kind == "needs-person"
    assert str(path) in (p_first.detail or "")
    assert p_second.state == "already-applied"


# ------------------- 3. the fold: every first read of a bad file refuses


MALFORMED_HOSTS = "skills_root: [unclosed\n"


def _corrupt(home, rid):
    path = find_record_path(home, rid)
    path.write_text(
        path.read_text(encoding="utf-8").replace("status: ", "status: nonsense-", 1),
        encoding="utf-8",
    )
    commit_all(home, f"a hand edit that breaks {rid}")
    return path


def _hook_routed(env, rid, *, scope="skill:s", project=False):
    record = make_behavior(scope=scope, record_id=rid, trigger=TRIGGER)
    create_record(env.ledger, record, project_path=env.host if project else None)
    write_proposal(
        env.ledger, rid,
        hook_proposal(scope=scope, alternates=["claude-md"]) if project
        else hook_proposal(scope=scope),
    )
    stamp_proposal(env.ledger, rid)
    commit_all(env.ledger, f"seed hook {rid}")
    return rid


def _preview_and_run(env, tmp_path, body, **run_kw):
    path = tmp_path / "sheet.yaml"
    path.write_text("version: 1\nitems:\n" + body, encoding="utf-8")
    items = batch.load_sheet(path)
    preview = batch.dry_run(env.ledger, items, **run_kw)
    result = batch.run(env.ledger, items, no_push=True, **run_kw)
    return preview, result


@pytest.mark.parametrize("verb", ["retire", "supersede"])
def test_retiring_a_hook_routed_lesson_with_a_malformed_hosts_yaml(
    tmp_path, monkeypatch, verb
):
    env = _env(tmp_path, monkeypatch)
    hooked = _hook_routed(env, "lrn-d0000010")
    verbs.route(env.ledger, hooked, no_push=True)
    replacement = _seed(env.ledger, "lrn-d0000011")
    other = _seed(env.ledger, "lrn-d0000012")
    (env.ledger / "hosts.yaml").write_text(MALFORMED_HOSTS, encoding="utf-8")
    line = (
        f"  - id: {hooked}\n    verb: retire\n    covered_by: skill-md:s\n"
        if verb == "retire"
        else f"  - id: {hooked}\n    verb: supersede\n    new_id: {replacement}\n"
    )

    preview, result = _preview_and_run(
        env, tmp_path, line + f"  - id: {other}\n    verb: reject\n"
    )

    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert "hosts.yaml" in (first.detail or "")
    assert first.kind == "needs-person"
    assert second.state == "applied", (second.state, second.detail)
    assert _record(env.ledger, hooked).status == "routed"
    p_first = preview.items[0]
    assert (p_first.state, p_first.kind) == ("would-refuse", "needs-person")
    assert "hosts.yaml" in (p_first.detail or "")


def test_a_project_scope_hook_route_with_a_malformed_hosts_yaml(tmp_path, monkeypatch):
    """The overseer is the one actor whose hook route reaches the verb; a
    project-scope hook's first registry read is in `_hooks_dir_for`."""
    env = _env(tmp_path, monkeypatch)
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    hooked = _hook_routed(env, "lrn-d0000013", scope="project", project=True)
    other = _seed(env.ledger, "lrn-d0000014")
    (env.ledger / "hosts.yaml").write_text(MALFORMED_HOSTS, encoding="utf-8")

    path = tmp_path / "sheet.yaml"
    path.write_text(
        "version: 1\nitems:\n"
        f"  - id: {hooked}\n    verb: route\n    dest: hook\n"
        f"  - id: {other}\n    verb: reject\n",
        encoding="utf-8",
    )
    result = batch.run(env.ledger, batch.load_sheet(path), no_push=True, actor="overseer")

    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert "hosts.yaml" in (first.detail or "")
    assert first.kind == "needs-person"
    assert second.state == "applied", (second.state, second.detail)
    assert not list((claude / "hooks").iterdir())  # nothing activated


@pytest.mark.parametrize("verb, to", [("rehome", "HOST"), ("rescope", "skill:s")])
def test_a_move_with_a_malformed_hosts_yaml(tmp_path, monkeypatch, verb, to):
    env = _env(tmp_path, monkeypatch)
    moving = _seed(
        env.ledger, "lrn-d0000015", scope="skill:s" if verb == "rehome" else "user",
        proposal=verb == "rehome",
    )
    other = _seed(env.ledger, "lrn-d0000016")
    (env.ledger / "hosts.yaml").write_text(MALFORMED_HOSTS, encoding="utf-8")
    target = str(env.host) if to == "HOST" else to

    preview, result = _preview_and_run(
        env, tmp_path,
        f"  - id: {moving}\n    verb: {verb}\n    to: '{target}'\n"
        f"  - id: {other}\n    verb: reject\n",
    )

    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert "hosts.yaml" in (first.detail or "")
    assert first.kind == "needs-person"
    assert second.state == "applied", (second.state, second.detail)
    assert (preview.items[0].state, preview.items[0].kind) == (
        "would-refuse", "needs-person",
    )


def test_supersede_onto_a_replacement_whose_file_does_not_read_back(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    old = _seed(env.ledger, "lrn-d0000017")
    new = _seed(env.ledger, "lrn-d0000018")
    other = _seed(env.ledger, "lrn-d0000019")
    broken = _corrupt(env.ledger, new)

    preview, result = _preview_and_run(
        env, tmp_path,
        f"  - id: {old}\n    verb: supersede\n    new_id: {new}\n"
        f"  - id: {other}\n    verb: reject\n",
    )

    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert str(broken) in (first.detail or "")
    assert first.kind == "needs-person"
    assert second.state == "applied", (second.state, second.detail)
    assert _record(env.ledger, old).status == "pending"
    p_first = preview.items[0]
    assert (p_first.state, p_first.kind) == ("would-refuse", "needs-person")
    assert str(broken) in (p_first.detail or "")


def test_supersede_whose_replacement_chain_holds_a_file_that_does_not_read_back(
    tmp_path, monkeypatch
):
    """The cycle walk reads the replacement's own `superseded_by` chain; a
    live replacement carrying a stale pointer (a hand edit) sends it to a
    third record, and that file is corrupt."""
    env = _env(tmp_path, monkeypatch)
    old = _seed(env.ledger, "lrn-d0000020")
    third = _seed(env.ledger, "lrn-d0000021")
    rec = make_behavior(record_id="lrn-d0000022", scope="skill:s")
    rec.set_superseded_by(third)
    create_record(env.ledger, rec)
    write_proposal(env.ledger, rec.id, proposal_dict(scope="skill:s"))
    commit_all(env.ledger, "a live replacement with a stale pointer")
    broken = _corrupt(env.ledger, third)

    preview, result = _preview_and_run(
        env, tmp_path, f"  - id: {old}\n    verb: supersede\n    new_id: {rec.id}\n"
    )

    (item,) = result.items
    assert item.state == "refused", (item.state, item.detail)
    assert str(broken) in (item.detail or "")
    assert item.kind == "needs-person"
    assert (preview.items[0].state, preview.items[0].kind) == (
        "would-refuse", "needs-person",
    )


def test_a_route_whose_predecessor_file_does_not_read_back(tmp_path, monkeypatch):
    """A lesson written with `supersedes:` retires its predecessor when it
    is routed; the predecessor is a second record the route reads."""
    env = _env(tmp_path, monkeypatch)
    predecessor = _seed(env.ledger, "lrn-d0000023")
    rec = make_behavior(record_id="lrn-d0000024", scope="skill:s")
    rec.set_supersedes(predecessor)
    create_record(env.ledger, rec)
    write_proposal(env.ledger, rec.id, proposal_dict(scope="skill:s"))
    commit_all(env.ledger, "a lesson that supersedes another")
    other = _seed(env.ledger, "lrn-d0000025")
    broken = _corrupt(env.ledger, predecessor)

    preview, result = _preview_and_run(
        env, tmp_path,
        f"  - id: {rec.id}\n    verb: route\n    dest: skill-md\n"
        f"  - id: {other}\n    verb: reject\n",
    )

    first, second = result.items
    assert first.state == "refused", (first.state, first.detail)
    assert str(broken) in (first.detail or "")
    assert first.kind == "needs-person"
    assert second.state == "applied", (second.state, second.detail)
    p_first = preview.items[0]
    assert (p_first.state, p_first.kind) == ("would-refuse", "needs-person")
    assert str(broken) in (p_first.detail or "")


def test_a_continuation_run_receipts_an_unreadable_record_and_goes_on(
    tmp_path, monkeypatch
):
    """The steward and the overseer drive `batch.run` with a continuation and
    a checkpoint that writes each receipt line before the next item starts."""
    env = _env(tmp_path, monkeypatch)
    broken_id = _seed(env.ledger, "lrn-d0000026")
    sound = _seed(env.ledger, "lrn-d0000027")
    broken = _corrupt(env.ledger, broken_id)
    items = batch.Sheet(
        [
            batch.SheetItem(n=1, id=broken_id, verb="reject", fields={}),
            batch.SheetItem(n=2, id=sound, verb="reject", fields={}),
        ],
        case="case-d0000026",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )
    receipts: list[list[tuple]] = []

    def checkpoint(partial):
        receipts.append([(i.n, i.state, i.kind) for i in partial.items])
        return {"state": "ok"}

    result = batch.run(
        env.ledger,
        items,
        no_push=True,
        actor="steward",
        continuation=batch.BatchContinuation(
            run_id="run-d0000026",
            case_id="case-d0000026",
            sheet_digest="a" * 64,
            completed={},
        ),
        checkpoint=checkpoint,
    )

    assert [(i.n, i.state, i.kind) for i in result.items] == [
        (1, "refused", "needs-person"),
        (2, "applied", None),
    ]
    assert str(broken) in (result.items[0].detail or "")
    # item 1's receipt line was written before item 2 started, and the last
    # receipt holds both
    assert receipts[0] == [(1, "refused", "needs-person")]
    assert receipts[-1] == [(1, "refused", "needs-person"), (2, "applied", None)]
    assert _record(env.ledger, sound).status == "rejected"


def test_a_record_file_whose_yaml_does_not_parse_refuses_that_item_only(
    tmp_path, monkeypatch
):
    """The other shape of a broken file: frontmatter that is not YAML at all
    raises the YAML parser's own error, not a record validation error."""
    env = _env(tmp_path, monkeypatch)
    broken_id = _seed(env.ledger, "lrn-d0000028")
    fine = _seed(env.ledger, "lrn-d0000029")
    path = find_record_path(env.ledger, broken_id)
    path.write_text(
        path.read_text(encoding="utf-8").replace("status: pending", "status: [unclosed", 1),
        encoding="utf-8",
    )
    commit_all(env.ledger, "frontmatter that is not YAML")

    preview, result = _preview_and_run(
        env, tmp_path,
        f"  - id: {broken_id}\n    verb: reject\n  - id: {fine}\n    verb: reject\n",
    )

    first, second = result.items
    assert (first.state, first.kind) == ("refused", "needs-person"), first.detail
    assert str(path) in (first.detail or "")
    assert second.state == "applied", (second.state, second.detail)
    assert (preview.items[0].state, preview.items[0].kind) == (
        "would-refuse", "needs-person",
    )
