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

All ledger homes are throwaway sandbox repos under pytest tmpdirs
(`support.make_env`), never the real `~/.self-learn`.
"""

from __future__ import annotations

import pytest

from self_learn import batch
from self_learn.ledger_ops import create_record, find_record_path, write_proposal
from self_learn.records import Record
from support import commit_all, make_behavior, make_env, proposal_dict


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


def _env(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    return env


def _seed(home, rid, *, scope="skill:s", project_path=None):
    create_record(home, make_behavior(record_id=rid, scope=scope), project_path=project_path)
    if project_path is None:
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
