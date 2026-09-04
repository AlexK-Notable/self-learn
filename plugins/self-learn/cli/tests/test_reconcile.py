"""M-C (Sprint 1 lane L5): reconcile validates content, all-or-nothing.

``self_learn.reconcile`` decided what to commit by PATH SHAPE alone
through round 7 — ``compiled/<slug>.yaml`` looked right, so it got
committed, whatever bytes were actually inside it. Probed as C09: a
``compiled/host.yaml`` whose entire content was ``host: [`` (unparseable
YAML) landed as a clean heal. This file pins the fix: every orphan is now
dispatched by asset kind to a real content check BEFORE anything is
staged, and a single invalid member — or a blocked half-``git mv``
sitting alongside otherwise-fine orphans — refuses the WHOLE batch rather
than committing the fine ones and leaving the bad one behind.

Design pin, inherited from round 3/7 (see ``test_round7_fixes.py``):
**no mocks**. Real git sandboxes, real files written to disk exactly the
way each asset's own writer would leave them uncommitted.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from self_learn import cli, compiled, gitops, ledger_ops, miner, reconcile as reconcile_mod
from self_learn.ledger_ops import create_record
from support import (
    commit_all,
    git,
    make_behavior,
    make_env,
    proposal_dict,
)


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


# ======================================================= positive controls
#
# One per asset kind: a genuinely valid orphan of that kind must still be
# committed after M-C wires in content validation — the new gate must not
# reject content its own writer would have produced.


class TestPositiveControlPerAssetKind:
    def test_record(self, home):
        orphan = home / "skills" / "s" / "pending" / "lrn-90000001.md"
        create_record(home, make_behavior(record_id="lrn-90000001"))
        assert orphan.is_file()

        result = reconcile_mod.reconcile(home, no_push=True)

        assert result.healed
        assert not result.refused
        assert orphan in result.committed
        assert "skills/s/pending/lrn-90000001.md" in head_files(home)

    def test_proposal(self, home):
        create_record(home, make_behavior(record_id="lrn-90000002"))
        commit_all(home, "seed record")  # only the proposal is left orphaned
        ledger_ops.write_proposal(
            home, "lrn-90000002", proposal_dict(scope="skill:s")
        )
        orphan = home / "skills" / "s" / "proposals" / "lrn-90000002.yaml"
        assert orphan.is_file()

        result = reconcile_mod.reconcile(home, no_push=True)

        assert result.healed
        assert not result.refused
        assert orphan in result.committed
        assert "skills/s/proposals/lrn-90000002.yaml" in head_files(home)

    def test_meta(self, home, tmp_path):
        project_path = tmp_path / "some-project"
        bucket_dir = ledger_ops.bucket_dir_for_scope(
            home, "project", project_path=project_path
        )
        ledger_ops.ensure_project_meta(bucket_dir, project_path)
        orphan = bucket_dir / "meta.yaml"
        assert orphan.is_file()
        rel = str(orphan.relative_to(home))

        result = reconcile_mod.reconcile(home, no_push=True)

        assert result.healed
        assert not result.refused
        assert orphan in result.committed
        assert rel in head_files(home)

    def test_compiled(self, home):
        compiled.write_entry(
            home,
            "myhost",
            "CLAUDE.md",
            region="managed",
            sha256="a" * 64,
            based_on_sha256=None,
            nbytes=42,
            by="test",
            host=str(home),
            mode="plain",
        )
        orphan = home / "compiled" / "myhost.yaml"
        assert orphan.is_file()

        result = reconcile_mod.reconcile(home, no_push=True)

        assert result.healed
        assert not result.refused
        assert orphan in result.committed
        assert "compiled/myhost.yaml" in head_files(home)


# ============================================================ refusal cases


def test_reconcile_refuses_the_whole_batch_beside_a_blocked_rename(home):
    """The behaviour M-C changes: today, a valid orphan gets committed
    beside a blocked rename (a partial heal). After M-C, the presence of
    the blocked rename refuses the WHOLE batch — the otherwise-perfectly-
    valid sibling orphan stays uncommitted too."""
    create_record(home, make_behavior(record_id="lrn-90000005"))
    (home / "skills" / "s" / "resolved").mkdir(parents=True, exist_ok=True)
    commit_all(home, "seed")
    git(
        home,
        "mv",
        "skills/s/pending/lrn-90000005.md",
        "skills/s/resolved/lrn-90000005.md",
    )

    # a second, unrelated, perfectly valid orphan record
    create_record(home, make_behavior(record_id="lrn-90000006"))
    orphan = home / "skills" / "s" / "pending" / "lrn-90000006.md"
    assert orphan.is_file()

    before = git(home, "rev-parse", "HEAD").stdout

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed, "a valid orphan was committed beside a blocked rename"
    assert result.refused
    assert result.committed == []
    assert any("lrn-90000005" in line for line in result.blocked)
    assert git(home, "rev-parse", "HEAD").stdout == before, (
        "the batch was refused, so nothing should have been staged/committed"
    )
    assert "skills/s/pending/lrn-90000006.md" not in head_files(home)


def test_reconcile_refuses_the_c09_broken_compiled_record(home):
    """The probed defect itself: a `compiled/<slug>.yaml` whose entire
    content is unparseable YAML must not heal as a clean commit just
    because its path looks right."""
    compiled_dir = home / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    broken = compiled_dir / "host.yaml"
    broken.write_text("host: [\n", encoding="utf-8")

    before = git(home, "rev-parse", "HEAD").stdout

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed
    assert result.refused
    assert any("host.yaml" in line for line in result.invalid), result.invalid
    assert git(home, "rev-parse", "HEAD").stdout == before
    assert "compiled/host.yaml" not in head_files(home)


def test_reconcile_refuses_a_compiled_record_missing_required_keys(home):
    """A parseable mapping that is simply incomplete (no schema violation
    the old parse-plus-is-mapping check would ever catch) is invalid too
    — `compiled.write_entry` always sets `host`/`mode`/`targets`."""
    compiled_dir = home / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    (compiled_dir / "incomplete.yaml").write_text("host: /x\n", encoding="utf-8")

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed
    assert result.refused
    assert any("incomplete.yaml" in line for line in result.invalid), result.invalid


def test_reconcile_refuses_a_compiled_record_whose_top_level_is_not_a_mapping(home):
    """A second gap in the same C09 family, found while probing the
    fix above: `compiled.load_record` PARSES a top-level YAML sequence
    or scalar fine (``- a`` and ``5`` are both valid YAML), then its own
    ``dict(data) if data else {}`` crashes uncaught — ``dict(['a'])``
    raises ``ValueError``, ``dict(5)`` raises ``TypeError``. Neither is
    a `compiled.CompiledRecordError`, so unguarded this reaches the
    miner's `except gitops.GitOpsError` (which catches neither) and
    crashes the whole mine run, the identical failure shape the
    unparseable-YAML and bad-UTF-8 fixes above already exist to
    prevent."""
    compiled_dir = home / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    (compiled_dir / "seq.yaml").write_text("- a\n", encoding="utf-8")
    (compiled_dir / "scalar.yaml").write_text("5\n", encoding="utf-8")

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed
    assert result.refused
    assert any("seq.yaml" in line for line in result.invalid), result.invalid
    assert any("scalar.yaml" in line for line in result.invalid), result.invalid


def test_reconcile_refuses_a_record_with_invalid_utf8_bytes(home):
    """The M-C dispatch must catch what `Record.from_path` can ACTUALLY
    raise for a corrupt record — not just the wrapped `RecordError` every
    other validator's failures come as. `records.Record.from_text` lets a
    bad byte's `UnicodeDecodeError` (and a malformed frontmatter's raw
    `ruamel.yaml.error.YAMLError`) through unwrapped; probed live: this
    exact byte shape crashed the whole mine run ("'utf-8' codec can't
    decode...") instead of being reported invalid, the same corrupt-bytes
    shape `test_miner.py`'s undecodable-record fixtures already exercise
    for the miner's OWN (separate) record reader."""
    bad = home / "skills" / "s" / "pending" / "lrn-90000009.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"---\ntype: behavior\nid: lrn-90000009\n---\n\xff\xfe garbage")

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed
    assert result.refused
    assert any("lrn-90000009" in line for line in result.invalid), result.invalid


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses file permissions — chmod 000 is a no-op"
)
def test_reconcile_refuses_an_unreadable_record_orphan(home, monkeypatch, tmp_path):
    """BLOCKER-1 (fold r1): `Record.from_path` calls `Path.read_text`
    with NO guard at all — an unreadable record orphan (permission
    denied, EIO) raises `OSError` RAW, which was not in `_ASSET_ERRORS`
    before this fold. Uncaught, it would propagate straight through
    `reconcile()` into the miner's `except gitops.GitOpsError` (which
    catches neither), crashing the whole mine run — the identical
    "silent crash instead of a reported refusal" shape as the two gaps
    already pinned above, this time for a plain permission error on the
    FIRST kind M-C dispatches to."""
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    transcripts = tmp_path / "transcripts"
    (transcripts / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(transcripts))

    create_record(home, make_behavior(record_id="lrn-90000010"))
    orphan = home / "skills" / "s" / "pending" / "lrn-90000010.md"
    assert orphan.is_file()
    before = git(home, "rev-parse", "HEAD").stdout
    orphan.chmod(0o000)
    try:
        result = reconcile_mod.reconcile(home, no_push=True)

        assert not result.healed
        assert result.refused
        assert any("lrn-90000010" in line for line in result.invalid), result.invalid
        assert git(home, "rev-parse", "HEAD").stdout == before, (
            "the batch was refused, so HEAD must not have moved"
        )
        assert "skills/s/pending/lrn-90000010.md" not in head_files(home)

        # the miner path: never fatal, logs the offender, still mines.
        mine_result = miner.run(home, trigger="timer", no_push=True)
        assert mine_result.status != "failed", (
            "an unreadable orphan must not crash the whole mine run"
        )
        log_text = (miner.miner_dir() / "miner.log").read_text(encoding="utf-8")
        assert "lrn-90000010" in log_text, (
            f"the miner did not log the reconcile refusal's offender:\n{log_text}"
        )
    finally:
        orphan.chmod(0o644)


def test_reconcile_refuses_a_meta_yaml_without_a_path(home, tmp_path):
    """`meta.yaml`'s own schema (M-C writes it, no schema existed
    before): `ledger_ops.ensure_project_meta` always writes a non-empty
    `path`; anything else is invalid, not merely unusual."""
    project_path = tmp_path / "another-project"
    bucket_dir = ledger_ops.bucket_dir_for_scope(
        home, "project", project_path=project_path
    )
    bucket_dir.mkdir(parents=True, exist_ok=True)
    (bucket_dir / "meta.yaml").write_text("path: null\n", encoding="utf-8")

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed
    assert result.refused
    assert any("meta.yaml" in line for line in result.invalid), result.invalid


def test_reconcile_refuses_a_proposal_with_an_invalid_destination(home):
    """MAJOR-2 (fold r1): the `kind == "proposal"` dispatch branch
    (`_validate_proposal`) is what this test protects — the gate found
    the branch itself could be DELETED with the whole suite still green.
    A proposal sibling with a `destination` outside
    `ledger_ops.PROPOSAL_DESTINATIONS` must refuse, not commit — and
    (NIT-1, fold r2) the assertion checks `validate_proposal`'s OWN
    error text ("destination must be one of"), not merely the filename,
    the same discipline the merge-sibling test below already uses, so
    this cannot be satisfied by an unrelated failure that happens to
    also name the file."""
    create_record(home, make_behavior(record_id="lrn-90000011"))
    commit_all(home, "seed record")  # only the proposal orphan is left
    bucket_dir = home / "skills" / "s"
    (bucket_dir / "proposals").mkdir(parents=True, exist_ok=True)
    ledger_ops._dump_yaml(  # noqa: SLF001 — same module family as read_proposal
        proposal_dict(scope="skill:s", destination="not-a-real-destination"),
        bucket_dir / "proposals" / "lrn-90000011.yaml",
    )
    orphan = bucket_dir / "proposals" / "lrn-90000011.yaml"
    assert orphan.is_file()
    before = git(home, "rev-parse", "HEAD").stdout

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed
    assert result.refused
    assert any("lrn-90000011" in line for line in result.invalid), result.invalid
    assert any(
        "destination must be one of" in line for line in result.invalid
    ), result.invalid
    assert git(home, "rev-parse", "HEAD").stdout == before
    assert "skills/s/proposals/lrn-90000011.yaml" not in head_files(home)


def test_reconcile_refuses_an_invalid_merge_proposal_sibling(home):
    """MAJOR-2 (fold r1): the `merge-*.yaml` branch inside
    `_validate_proposal` (``if path.stem.startswith("merge-"):
    ledger_ops.validate_merge_proposal(data); return``) is equally
    unprotected by the suite — the gate found it too could be deleted
    with everything still green. A `merge-<8hex>.yaml` orphan missing
    its required fields must refuse, not commit — and the assertion
    checks for `validate_merge_proposal`'s OWN error text ("records must
    list"), not merely the filename, so this test cannot be satisfied by
    the sibling falling through to the single-record path instead (which
    would fail for the unrelated reason that "merge-deadbeef" is not a
    record id — still caught, but proof of the wrong branch firing)."""
    bucket_dir = home / "skills" / "s"
    (bucket_dir / "proposals").mkdir(parents=True, exist_ok=True)
    orphan = bucket_dir / "proposals" / "merge-deadbeef.yaml"
    orphan.write_text("cluster_id: merge-deadbeef\n", encoding="utf-8")
    before = git(home, "rev-parse", "HEAD").stdout

    result = reconcile_mod.reconcile(home, no_push=True)

    assert not result.healed
    assert result.refused
    assert any("records must list" in line for line in result.invalid), result.invalid
    assert git(home, "rev-parse", "HEAD").stdout == before
    assert "skills/s/proposals/merge-deadbeef.yaml" not in head_files(home)


# ==================================================== the miner must proceed


def test_the_miner_logs_a_refusal_and_still_mines(home, monkeypatch, tmp_path):
    """`miner.py:1930`'s pinned decision: a refusal is logged with the
    offender list, and the mine run proceeds — reconcile's refusal must
    never be treated as a reason to abort mining."""
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    transcripts = tmp_path / "transcripts"
    (transcripts / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(transcripts))

    # the wreckage: an invalid orphan compiled record left behind by a
    # previous, half-finished producer.
    compiled_dir = home / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    (compiled_dir / "broken.yaml").write_text("host: [\n", encoding="utf-8")

    result = miner.run(home, trigger="timer", no_push=True)

    assert result.status != "failed", (
        "the mine run must proceed past a reconcile refusal, not crash"
    )
    assert "compiled/broken.yaml" not in head_files(home), (
        "the invalid orphan must still be uncommitted — the miner logs "
        "the refusal, it does not silently heal (or silently drop) it"
    )
    log_path = miner.miner_dir() / "miner.log"
    assert log_path.is_file()
    log_text = log_path.read_text(encoding="utf-8")
    assert "broken.yaml" in log_text, (
        f"the miner did not log the reconcile refusal's offender:\n{log_text}"
    )


# ============================== the CLI surfaces a refusal, not a false all-clear


def test_cli_reconcile_exits_git_failed_and_names_the_offender_on_a_refusal(
    home, capsys
):
    """MAJOR-1 (fold r1): the gate found `_cmd_reconcile`'s own
    `if result.refused: return EXIT_GIT_FAILED` unprotected — replacing
    it with `pass` left all 24 tests green, and `self-learn reconcile`
    then exited 0 printing "the ledger is whole" over the C09 fixture
    itself. This drives the real CLI entrypoint, not `reconcile()`
    directly, so a regression in `_cmd_reconcile`'s own wiring (as
    opposed to `reconcile()`'s return value) cannot hide behind a green
    suite again."""
    compiled_dir = home / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    (compiled_dir / "host.yaml").write_text("host: [\n", encoding="utf-8")

    code = cli.main(["reconcile", "--no-push"])
    captured = capsys.readouterr()

    assert code == gitops.EXIT_GIT_FAILED
    assert "host.yaml" in captured.err
    assert "the ledger is whole" not in captured.out
    assert "compiled/host.yaml" not in head_files(home)


def test_cli_push_prints_the_offender_and_never_commits_it(home, capsys):
    """MAJOR-1 (fold r1): `_cmd_push`'s offender-printing loop (added by
    this same move — before it, `push` never looked at a blocked/invalid
    orphan at all) is likewise unprotected by any existing test. Push's
    OWN exit code is unaffected by a refusal (decision 3: push still
    republishes whatever IS already committed) — what this test protects
    is that the offender is actually named on stderr, and that it never
    slips into what gets committed (and so never reaches "published")."""
    compiled_dir = home / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    (compiled_dir / "host.yaml").write_text("host: [\n", encoding="utf-8")

    cli.main(["push"])
    captured = capsys.readouterr()

    assert "host.yaml" in captured.err
    assert "compiled/host.yaml" not in head_files(home), (
        "the invalid orphan must never be committed — push must not "
        "proceed with publishing it"
    )
