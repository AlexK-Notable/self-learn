"""S-71 (`03-decisions.md`; `02-schema.md` §3a): every refusal the ledger
makes of a sheet item carries one KIND, decided by the exception type at the
raise site and never by the refusal's text. `batch.refusal_kind` is the one
place the table lives.

Each test below drives a REAL verb refusal through `batch.run` (or
`batch.dry_run`) on a scratch ledger — never a hand-made exception — and
checks the kind the item result carries. All ledger homes are throwaway
sandbox repos under pytest tmpdirs (`support.make_env`), never the real
`~/.self-learn`.
"""

from __future__ import annotations

import pytest

from self_learn import batch, compilers, verbs
from self_learn.hosts import host_add, MARKER_FILENAME
from self_learn.ledger_ops import create_record, write_proposal
from support import (
    commit_all,
    failing_git_shim,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


# --------------------------------------------------------------- helpers


def _env(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    return env


def _seed(home, rid, *, scope="skill:s", record=None, proposal=True, project_path=None):
    rec = record if record is not None else make_behavior(record_id=rid, scope=scope)
    create_record(home, rec, project_path=project_path)
    if proposal:
        write_proposal(home, rid, proposal_dict(scope=scope))
    commit_all(home, f"seed {rid}")
    return rid


def _sheet(tmp_path, body, name="sheet.yaml"):
    path = tmp_path / name
    path.write_text("version: 1\nitems:\n" + body, encoding="utf-8")
    return batch.load_sheet(path)


def _run(home, tmp_path, body):
    return batch.run(home, _sheet(tmp_path, body), no_push=True)


def _only(result):
    assert len(result.items) >= 1
    return result.items[0]


# ------------------------------------------------------ the closed set


def test_the_kind_set_is_closed_and_every_kind_is_reachable_in_precedence():
    assert batch.REFUSAL_KINDS == frozenset(
        {
            "git", "target-busy", "status", "destination-unavailable",
            "needs-person", "bad-line", "secret-record", "unclassified",
        }
    )
    # The precedence order names every kind exactly once.
    assert sorted(batch._KIND_PRECEDENCE) == sorted(batch.REFUSAL_KINDS)


# ------------------------------------------------------------- git


def test_git_a_commit_that_fails_is_a_stopped_item_of_kind_git(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000001")
    flag = failing_git_shim(tmp_path, monkeypatch, sub="commit")
    items = _sheet(tmp_path, f"  - id: {rid}\n    verb: reject\n")
    flag.touch()
    try:
        result = batch.run(env.ledger, items, no_push=True)
    finally:
        flag.unlink()
    item = _only(result)
    assert item.state == "stopped", (item.state, item.detail)
    assert item.rc in (6, 7)
    assert item.kind == "git"
    assert result.to_json()["items"][0]["kind"] == "git"


# ------------------------------------------------------ target-busy


def test_target_busy_uncommitted_edits_in_the_target_file(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000002")
    env.skill_md.write_text(
        env.skill_md.read_text(encoding="utf-8") + "\nan edit nobody committed\n",
        encoding="utf-8",
    )
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n    dest: skill-md\n"))
    assert item.state == "refused"
    assert verbs.GITOPS_DIRTY_MARKER in (item.detail or "")
    assert item.kind == "target-busy"


# ----------------------------------------------------------- status


def test_status_a_verb_the_lesson_status_does_not_fit(tmp_path, monkeypatch):
    """`undefer` needs a deferred lesson; this one is pending. The typed
    refusal is raised by `ledger_ops.require_status` and re-raised by the verb
    as a plain `VerbError` — the kind is read from the one underneath."""
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000003")
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: undefer\n"))
    assert item.state == "refused"
    assert "is 'pending'" in (item.detail or "")
    assert type(item.detail) is str
    assert item.kind == "status"


def test_status_a_record_that_no_longer_exists(tmp_path, monkeypatch):
    """`supersede` onto a replacement id that is not in the ledger: the
    record-not-found refusal, unwrapped (exit 64), is kind `status`."""
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000004")
    item = _only(_run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: supersede\n    new_id: lrn-affffff4\n",
    ))
    assert item.state == "refused"
    assert item.rc == 64
    assert "not found" in (item.detail or "")
    assert item.kind == "status"


# ------------------------------------------- destination-unavailable


def test_destination_unavailable_skill_has_no_skill_md(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000005")
    env.skill_md.unlink()
    commit_all(env.host, "the skill lost its SKILL.md")
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n    dest: skill-md\n"))
    assert item.state == "refused"
    assert "no SKILL.md at" in (item.detail or "")
    assert item.kind == "destination-unavailable"


def test_destination_unavailable_no_skills_root_registered(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000006")
    (env.ledger / "hosts.yaml").write_text(
        f"projects:\n  - path: {env.host}\n", encoding="utf-8"
    )
    commit_all(env.ledger, "no skills root")
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n    dest: skill-md\n"))
    assert item.state == "refused"
    assert "no skills root registered" in (item.detail or "")
    assert item.kind == "destination-unavailable"


def test_destination_unavailable_local_file_not_git_ignored(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(
        env.ledger, "lrn-a0000007", scope="project",
        record=make_behavior(record_id="lrn-a0000007", scope="project"),
        proposal=False, project_path=env.host,
    )
    item = _only(_run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: route\n    dest: claude-md:local\n",
    ))
    assert item.state == "refused"
    assert "is not gitignored" in (item.detail or "")
    assert item.kind == "destination-unavailable"


# ---------------------------------------------------- needs-person


def test_needs_person_plain_host_lost_its_marker(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    plain = tmp_path / "plain-host"
    plain.mkdir()
    host_add(env.ledger, plain, "project", mode="plain")
    rid = _seed(
        env.ledger, "lrn-a0000008", scope="project",
        record=make_behavior(record_id="lrn-a0000008", scope="project"),
        proposal=False, project_path=plain,
    )
    (plain / MARKER_FILENAME).unlink()
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n    dest: claude-md\n"))
    assert item.state == "refused"
    assert MARKER_FILENAME in (item.detail or "")
    assert item.kind == "needs-person"


def test_needs_person_project_host_not_registered(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    elsewhere = tmp_path / "never-registered"
    elsewhere.mkdir()
    rid = _seed(
        env.ledger, "lrn-a0000009", scope="project",
        record=make_behavior(record_id="lrn-a0000009", scope="project"),
        proposal=False, project_path=elsewhere,
    )
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n    dest: claude-md\n"))
    assert item.state == "refused"
    assert "host not registered" in (item.detail or "")
    assert item.kind == "needs-person"


def test_needs_person_managed_region_edited_outside_self_learn(tmp_path, monkeypatch):
    """A plain host whose CLAUDE.md already carries a managed region this
    ledger never wrote: the region predicate refuses (`DirtyTargetError`
    with the REGION marker) — a person decides, so `needs-person`, not the
    `target-busy` an uncommitted edit gets."""
    env = _env(tmp_path, monkeypatch)
    plain = tmp_path / "plain-region"
    plain.mkdir()
    host_add(env.ledger, plain, "project", mode="plain")
    (plain / "CLAUDE.md").write_text(
        f"# host\n\n{compilers.BEGIN_MARKER}\nforeign content\n{compilers.END_MARKER}\n",
        encoding="utf-8",
    )
    rid = _seed(
        env.ledger, "lrn-a000000a", scope="project",
        record=make_behavior(record_id="lrn-a000000a", scope="project"),
        proposal=False, project_path=plain,
    )
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n    dest: claude-md\n"))
    assert item.state == "refused"
    assert verbs.REGION_VERDICT_MARKER in (item.detail or "")
    assert item.kind == "needs-person"


# --------------------------------------------------------- bad-line


def test_bad_line_malformed_destination(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a000000b")
    item = _only(_run(
        env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n    dest: claude-md:bogus\n",
    ))
    assert item.state == "refused"
    assert "not recognized" in (item.detail or "")
    assert item.kind == "bad-line"


def test_bad_line_defer_date_in_the_past(tmp_path, monkeypatch):
    """Raised in `ledger_ops.defer_record` as a typed ledger refusal and
    re-raised by `verbs.defer` as a plain `VerbError`."""
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a000000c")
    item = _only(_run(
        env.ledger, tmp_path, f"  - id: {rid}\n    verb: defer\n    until: '2000-01-01'\n",
    ))
    assert item.state == "refused"
    assert "is in the past" in (item.detail or "")
    assert item.kind == "bad-line"


def test_bad_line_a_secret_only_in_the_line_own_note(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a000000d")
    item = _only(_run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: reject\n    note: 'key is ghp_{'a' * 36}'\n",
    ))
    assert item.state == "refused"
    assert "secret scan hit" in (item.detail or "")
    assert item.kind == "bad-line"


def test_bad_line_revise_names_a_section_the_record_does_not_have(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a000000e")
    item = _only(_run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: revise\n    section: Nonexistent\n"
        "    text: new words\n    because: clearer\n",
    ))
    assert item.state == "refused"
    assert "has no 'Nonexistent' section" in (item.detail or "")
    assert item.kind == "bad-line"


# ---------------------------------------------------- secret-record


def test_secret_record_a_secret_in_the_record_itself(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(
        env.ledger, "lrn-a000000f", scope="skill:s",
        record=make_knowledge(
            scope="skill:s", record_id="lrn-a000000f", fact="password = hunter2secret99",
        ),
        proposal=False,
    )
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: reject\n"))
    assert item.state == "refused"
    assert "secret scan hit" in (item.detail or "")
    assert item.kind == "secret-record"


def test_secret_record_wins_when_the_record_and_the_note_both_hit(tmp_path, monkeypatch):
    """A hit in the record makes it `secret-record` even when the line's
    note also hits — a record hit sent back would only recur."""
    env = _env(tmp_path, monkeypatch)
    rid = _seed(
        env.ledger, "lrn-a0000010", scope="skill:s",
        record=make_knowledge(
            scope="skill:s", record_id="lrn-a0000010", fact="password = hunter2secret99",
        ),
        proposal=False,
    )
    item = _only(_run(
        env.ledger, tmp_path,
        f"  - id: {rid}\n    verb: reject\n    note: 'key is ghp_{'b' * 36}'\n",
    ))
    assert item.kind == "secret-record"


# ----------------------------------------------------- unclassified


def test_unclassified_a_refusal_no_type_names(tmp_path, monkeypatch):
    """A route with no `dest` for a lesson with no proposal refuses with
    `NoProposalError`, a `VerbError` no S-71 type names — so it is
    `unclassified` (which parks; it is never silent)."""
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000011", proposal=False)
    item = _only(_run(env.ledger, tmp_path, f"  - id: {rid}\n    verb: route\n"))
    assert item.state == "refused"
    assert verbs.NO_PROPOSAL_MARKER in (item.detail or "")
    assert item.kind == "unclassified"


# ---------------------------------------------- where the kind rides


def test_an_applied_item_carries_no_kind_and_its_json_has_no_kind_key(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    ok = _seed(env.ledger, "lrn-a0000012")
    bad = _seed(env.ledger, "lrn-a0000013")
    result = _run(
        env.ledger, tmp_path,
        f"  - id: {ok}\n    verb: reject\n"
        f"  - id: {bad}\n    verb: undefer\n",
    )
    applied, refused = result.items
    assert applied.state == "applied" and applied.kind is None
    assert refused.state == "refused" and refused.kind == "status"
    rows = result.to_json()["items"]
    assert "kind" not in rows[0]
    assert rows[1]["kind"] == "status"


def test_the_preview_gives_a_would_refuse_item_the_same_kind(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch)
    rid = _seed(env.ledger, "lrn-a0000014")
    other = _seed(env.ledger, "lrn-a0000015")
    items = _sheet(
        tmp_path,
        f"  - id: {rid}\n    verb: route\n    dest: claude-md:bogus\n"
        f"  - id: {other}\n    verb: undefer\n",
    )
    preview = batch.dry_run(env.ledger, items)
    route_item, undefer_item = preview.items
    assert route_item.state == "would-refuse" and route_item.kind == "bad-line"
    assert undefer_item.state == "would-refuse" and undefer_item.kind == "status"
    rows = preview.to_json()["items"]
    assert rows[0]["kind"] == "bad-line" and rows[1]["kind"] == "status"
