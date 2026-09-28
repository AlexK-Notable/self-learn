"""Sweep 2, R2 (2026-09-27): crash recovery in the steward and the overseer
establishes a recovered route's host result from THAT record's own target.

Before the fix both called a ledger-wide `verbs.recompile` while checking
one item: it rewrote and committed every other stale host target, and ANY
skipped target anywhere (a user's uncommitted edit to another skill's
SKILL.md) became the recovered item's `unresolved-host`, which halts that
case and every later one, on every attempt.

The evidence lookups a crashed attempt would satisfy are stubbed (as the
audit probe did); `recompile` and the host classification are real.
"""

from __future__ import annotations

import pytest

from self_learn import batch, execution_evidence, gitops, steward, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.overseer import run as overseer_run
from support import commit_all, git, make_behavior, make_env, proposal_dict


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")


RID = "lrn-9b000001"


def _seed_routed(home, rid, skill):
    create_record(home, make_behavior(record_id=rid, scope=f"skill:{skill}"))
    write_proposal(home, rid, proposal_dict(scope=f"skill:{skill}"))
    commit_all(home, f"seed {rid}")
    verbs.route(home, rid, dest="skill-md", no_push=True)


def _skill_md(env, skill):
    return env.host / "plugins" / f"{skill}-plugin" / "skills" / skill / "SKILL.md"


def _three_skill_ledger(tmp_path, monkeypatch):
    """`s` holds the recovered route; `t` has a user's uncommitted edit;
    `u` drifted (committed) and is owed an ordinary recompile."""
    env = make_env(tmp_path, skills=("s", "t", "u"))
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    _seed_routed(env.ledger, RID, "s")
    _seed_routed(env.ledger, "lrn-9b000002", "t")
    _seed_routed(env.ledger, "lrn-9b000003", "u")
    u_md = _skill_md(env, "u")
    text = u_md.read_text()
    u_md.write_text(text[: text.index(BEGIN_MARKER)] + BEGIN_MARKER + "\n" + END_MARKER + "\n")
    commit_all(env.host, "u drifted")
    return env


def _dirty(path):
    path.write_text(path.read_text() + "\nwork in progress\n")


def _steward_recover(env, monkeypatch, tmp_path):
    home = env.ledger
    sheet_path = tmp_path / "sheet.yaml"
    sheet_path.write_text(
        f"version: 1\nitems:\n  - id: {RID}\n    verb: route\n    dest: skill-md\n",
        encoding="utf-8",
    )
    sheet = batch.load_sheet(sheet_path)
    head = gitops.head_sha(home)
    monkeypatch.setattr(steward, "_committed_receipts", lambda *a, **k: {})
    monkeypatch.setattr(execution_evidence, "validate_manifest_ref", lambda *a, **k: None)
    monkeypatch.setattr(execution_evidence, "find_mutation_commit", lambda *a, **k: head)
    monkeypatch.setattr(steward, "_verify_mutation_commit", lambda *a, **k: True)
    manifest = {"run_id": "run-0000test", "start_head": head}
    recipe = {"sheet_sha": "a" * 8, "sheet_digest": "b" * 64}
    return steward._recovered_items(home, manifest, "case-0000abcd", recipe, sheet)


def test_steward_an_unrelated_dirty_target_does_not_block_recovery(tmp_path, monkeypatch):
    env = _three_skill_ledger(tmp_path, monkeypatch)
    t_md, u_md = _skill_md(env, "t"), _skill_md(env, "u")
    _dirty(t_md)
    t_before, u_before = t_md.read_bytes(), u_md.read_bytes()
    host_head = git(env.host, "rev-parse", "HEAD").stdout.strip()

    done = _steward_recover(env, monkeypatch, tmp_path)

    assert done[1].state == "applied", (done[1].state, done[1].detail)
    # every other target is left alone: the user's edit, and the drifted one
    assert t_md.read_bytes() == t_before
    assert u_md.read_bytes() == u_before
    assert git(env.host, "rev-parse", "HEAD").stdout.strip() == host_head
    assert git(env.host, "status", "--porcelain").stdout.strip() == (
        "M plugins/t-plugin/skills/t/SKILL.md"
    )


def test_steward_the_items_own_dirty_target_still_blocks(tmp_path, monkeypatch):
    """Positive control: the host check still bites where it should."""
    env = _three_skill_ledger(tmp_path, monkeypatch)
    _dirty(_skill_md(env, "s"))
    done = _steward_recover(env, monkeypatch, tmp_path)
    assert done[1].state == "unresolved-host"
    assert "s-plugin" in (done[1].detail or "")


def _overseer_recover(env, monkeypatch):
    home = env.ledger
    sha = git(home, "log", "-1", "--format=%H", f"--grep={RID}").stdout.strip()
    assert sha
    monkeypatch.setattr(overseer_run, "_manifest_introduction", lambda *a, **k: sha + "~1")
    monkeypatch.setattr(execution_evidence, "find_mutation_commit", lambda *a, **k: sha)
    sheet = f"version: 1\nitems:\n  - id: {RID}\n    verb: route\n    dest: skill-md\n"
    recipe = {
        "sheet_sha": "a" * 8, "sheet_digest": "b" * 64, "sheet": sheet,
        "items": [{"n": 1, "id": RID, "verb": "route"}],
    }
    manifest = {"run_id": "run-0000test"}
    return overseer_run._mutation_proven_completed(home, manifest, "case-0000abcd", recipe, {})


def test_overseer_an_unrelated_dirty_target_does_not_block_recovery(tmp_path, monkeypatch):
    env = _three_skill_ledger(tmp_path, monkeypatch)
    t_md, u_md = _skill_md(env, "t"), _skill_md(env, "u")
    _dirty(t_md)
    u_before = u_md.read_bytes()
    done = _overseer_recover(env, monkeypatch)
    assert done[1].state == "applied", (done[1].state, done[1].detail)
    assert u_md.read_bytes() == u_before


def test_overseer_the_items_own_dirty_target_still_blocks(tmp_path, monkeypatch):
    env = _three_skill_ledger(tmp_path, monkeypatch)
    _dirty(_skill_md(env, "s"))
    done = _overseer_recover(env, monkeypatch)
    assert done[1].state == "unresolved-host"
    assert "s-plugin" in (done[1].detail or "")


def test_narrow_recompile_repairs_only_the_named_records_target(tmp_path, monkeypatch):
    env = _three_skill_ledger(tmp_path, monkeypatch)
    s_md, u_md = _skill_md(env, "s"), _skill_md(env, "u")
    text = s_md.read_text()
    s_md.write_text(text[: text.index(BEGIN_MARKER)] + BEGIN_MARKER + "\n" + END_MARKER + "\n")
    commit_all(env.host, "s drifted too")

    result = verbs.recompile(env.ledger, no_push=True, only_records=[RID])

    assert RID in s_md.read_text()  # its own target: repaired
    assert "lrn-9b000003" not in u_md.read_text()  # not its target: untouched
    assert [e.target for e in result.entries] == [s_md]
    assert verbs.recompile_refusals(result, RID) == []
    # an ordinary recompile still repairs the rest
    verbs.recompile(env.ledger, no_push=True)
    assert "lrn-9b000003" in u_md.read_text()


def test_refusals_name_the_records_own_warning():
    """An empty narrowed run whose record could not be resolved or read is
    not an established host result."""
    result = verbs.RecompileResult(
        warnings=[
            f"{RID}: no SKILL.md at /x — the compiler never creates target files",
            "lrn-9b0000ff: an unrelated record's warning",
            f"/ledger/skills/s/resolved/{RID}.md: not readable as a record (x)",
        ]
    )
    refused = verbs.recompile_refusals(result, RID)
    assert len(refused) == 2
    assert all(RID in line for line in refused)
