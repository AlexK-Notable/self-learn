"""Sweep 2, R1 (2026-09-27): one invalid uncommitted file holds back itself
and what depends on it — never every other orphan `reconcile` would commit.

M-C as first built refused the WHOLE batch, so a single leftover
`compiled/<slug>.yaml` holding `host: [` kept every record the miner had
landed but could not commit uncommitted, run after run. The orchestrator
recommended narrowing it; the user accepted ("yes", 2026-09-27 18:54). A
blocked (half-committed) rename holds back only its own record; a STOPped
intent still refuses everything (`test_reconcile.py` keeps that test).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import cli, gitops, ledger_ops, reconcile as reconcile_mod
from self_learn.ledger_ops import create_record
from support import commit_all, git, make_behavior, make_env, merge_proposal_text, proposal_dict

BAD_HEADER = "---\nid: [unclosed\n---\n\nbody\n"


def head_files(repo: Path) -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return env.ledger


def _three_landed_records(home):
    """What a `landed-uncommitted` mine leaves behind."""
    ids = ("lrn-9a000002", "lrn-9a000003", "lrn-9a000004")
    for rid in ids:
        create_record(home, make_behavior(record_id=rid))
    return [f"skills/s/pending/{rid}.md" for rid in ids]


def test_one_invalid_orphan_no_longer_blocks_the_valid_ones(home):
    landed = _three_landed_records(home)
    (home / "compiled").mkdir(exist_ok=True)
    bad = home / "compiled" / "other-host.yaml"
    bad.write_text("host: [\n", encoding="utf-8")

    first = reconcile_mod.reconcile(home, no_push=True)

    head = head_files(home)
    assert all(p in head for p in landed)  # the good ones landed
    assert sorted(first.committed) == sorted(home / p for p in landed)
    assert "compiled/other-host.yaml" not in head  # the bad one did not
    assert first.refused
    assert len(first.invalid) == 1 and "other-host.yaml" in first.invalid[0]
    # the next heal: nothing new to commit, the bad file still named
    second = reconcile_mod.reconcile(home, no_push=True)
    assert second.committed == [] and second.refused
    assert "other-host.yaml" in second.invalid[0]


def test_a_blocked_rename_holds_back_its_own_proposal_too(home):
    rid = "lrn-90000005"
    create_record(home, make_behavior(record_id=rid))
    (home / "skills" / "s" / "resolved").mkdir(parents=True, exist_ok=True)
    commit_all(home, "seed")
    git(home, "mv", f"skills/s/pending/{rid}.md", f"skills/s/resolved/{rid}.md")
    ledger_ops.write_proposal(home, rid, proposal_dict(scope="skill:s"))
    proposal = home / "skills" / "s" / "proposals" / f"{rid}.yaml"
    assert proposal.is_file()
    create_record(home, make_behavior(record_id="lrn-90000006"))  # unrelated

    result = reconcile_mod.reconcile(home, no_push=True)

    head = head_files(home)
    assert "skills/s/pending/lrn-90000006.md" in head
    assert f"skills/s/proposals/{rid}.yaml" not in head
    assert any(rid in line for line in result.blocked)
    assert result.held == [
        f"{proposal}: held back — depends on the half-committed rename of {rid}"
    ]


def test_a_merge_proposal_naming_an_invalid_record_is_held(home):
    bucket = home / "skills" / "s"
    create_record(home, make_behavior(record_id="lrn-9a00000d"))  # valid member
    (bucket / "pending" / "lrn-9a00000c.md").write_text(BAD_HEADER, encoding="utf-8")
    (bucket / "proposals").mkdir(exist_ok=True)
    merge = bucket / "proposals" / "merge-9a00000c.yaml"
    merge.write_text(
        merge_proposal_text("merge-9a00000c", ["lrn-9a00000c", "lrn-9a00000d"], "lrn-9a00000d"),
        encoding="utf-8",
    )

    result = reconcile_mod.reconcile(home, no_push=True)

    head = head_files(home)
    assert "skills/s/pending/lrn-9a00000d.md" in head  # does not depend on either
    assert "skills/s/pending/lrn-9a00000c.md" not in head
    assert "skills/s/proposals/merge-9a00000c.yaml" not in head
    assert any("lrn-9a00000c" in line for line in result.invalid)
    assert any(str(merge) in line and "lrn-9a00000c.md" in line for line in result.held)


def test_an_invalid_new_meta_holds_back_its_whole_bucket(home, tmp_path):
    project = tmp_path / "another-project"
    project.mkdir()
    record = make_behavior(scope="project", record_id="lrn-9a00000e")
    create_record(home, record, project_path=project)
    bucket_dir = ledger_ops.bucket_dir_for_scope(home, "project", project_path=project)
    meta = bucket_dir / "meta.yaml"
    assert meta.is_file()
    meta.write_text("path: null\n", encoding="utf-8")
    create_record(home, make_behavior(record_id="lrn-9a00000f"))  # another bucket

    result = reconcile_mod.reconcile(home, no_push=True)

    head = head_files(home)
    assert "skills/s/pending/lrn-9a00000f.md" in head
    rel_bucket = bucket_dir.relative_to(home)
    assert not any(p.startswith(str(rel_bucket)) for p in head)
    assert any("meta.yaml" in line for line in result.invalid)
    assert any("lrn-9a00000e" in line and "meta.yaml" in line for line in result.held)


def test_cli_reconcile_exits_partial_when_the_rest_was_committed(home, capsys):
    landed = _three_landed_records(home)
    (home / "compiled").mkdir(exist_ok=True)
    (home / "compiled" / "other-host.yaml").write_text("host: [\n", encoding="utf-8")

    code = cli.main(["reconcile", "--no-push"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_BATCH_PARTIAL
    assert code != gitops.EXIT_GIT_FAILED  # 6 would claim nothing was written
    assert "other-host.yaml" in captured.err
    assert "committed 3 orphaned path(s)" in captured.out
    assert all(p in head_files(home) for p in landed)
