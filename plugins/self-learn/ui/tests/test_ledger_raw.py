"""ledger.py's raw-file read half: record/proposal/diff/cluster/registry
readers + the sentinel mtime read. All against real throwaway repos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn_ui import ledger

from support import (
    make_behavior,
    make_env,
    merge_proposal_text,
    seed_proposal,
    seed_record,
)


@pytest.fixture
def sandbox(tmp_path):
    return make_env(tmp_path, skills=("s",))


class TestLocateRecord:
    def test_finds_pending_skill_record(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000001"))
        loc = ledger.locate_record(sandbox.ledger, "lrn-aa000001")
        assert loc is not None
        assert loc.scope == "skill"
        assert loc.bucket_name == "s"
        assert loc.resolved is False
        assert loc.path.name == "lrn-aa000001.md"

    def test_unknown_id_returns_none(self, sandbox):
        assert ledger.locate_record(sandbox.ledger, "lrn-ffffffff") is None

    def test_malformed_id_returns_none_never_raises(self, sandbox):
        assert ledger.locate_record(sandbox.ledger, "not-an-id") is None


class TestReadRecord:
    def test_reads_frontmatter_and_body(self, sandbox):
        path = seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000002"))
        record = ledger.read_record(path)
        assert record is not None
        assert record.id == "lrn-aa000002"
        assert record.type == "behavior"
        assert "Stop the container first." in record.body

    def test_unparseable_file_returns_none(self, tmp_path):
        bad = tmp_path / "bad.md"
        bad.write_text("not a record at all", encoding="utf-8")
        assert ledger.read_record(bad) is None


class TestReadProposal:
    def test_no_sibling_is_none_none(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000003"))
        data, error = ledger.read_proposal_raw(
            sandbox.ledger / "skills" / "s", "lrn-aa000003"
        )
        assert data is None
        assert error is None
        assert ledger.read_proposal_text(sandbox.ledger / "skills" / "s", "lrn-aa000003") is None

    def test_valid_sibling_parses(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000004"))
        seed_proposal(sandbox.ledger, "lrn-aa000004", destination="skill-md")
        data, error = ledger.read_proposal_raw(
            sandbox.ledger / "skills" / "s", "lrn-aa000004"
        )
        assert error is None
        assert data is not None
        assert data["destination"] == "skill-md"
        raw_text = ledger.read_proposal_text(sandbox.ledger / "skills" / "s", "lrn-aa000004")
        assert raw_text is not None
        assert "destination: skill-md" in raw_text

    def test_unparseable_sibling_surfaces_error_not_a_crash(self, sandbox):
        seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000005"))
        bucket_dir = sandbox.ledger / "skills" / "s"
        (bucket_dir / "proposals").mkdir(parents=True, exist_ok=True)
        (bucket_dir / "proposals" / "lrn-aa000005.yaml").write_text(
            "{{{not yaml", encoding="utf-8"
        )
        data, error = ledger.read_proposal_raw(bucket_dir, "lrn-aa000005")
        assert data is None
        assert error is not None


class TestReadDiff:
    def test_no_diff_sibling(self, sandbox):
        assert ledger.read_diff(sandbox.ledger / "skills" / "s", "lrn-nope") is None

    def test_diff_sibling_read_verbatim(self, sandbox):
        bucket_dir = sandbox.ledger / "skills" / "s"
        (bucket_dir / "proposals").mkdir(parents=True, exist_ok=True)
        text = "--- a/SKILL.md\n+++ b/SKILL.md\n+new line\n"
        (bucket_dir / "proposals" / "lrn-aa000006.diff").write_text(text, encoding="utf-8")
        assert ledger.read_diff(bucket_dir, "lrn-aa000006") == text


class TestReadClusters:
    def test_no_proposals_dir(self, sandbox):
        assert ledger.read_clusters(sandbox.ledger / "skills" / "s") == []

    def test_valid_cluster_parses(self, sandbox):
        r1 = seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000007"))
        r2 = seed_record(sandbox.ledger, make_behavior(record_id="lrn-aa000008"))
        bucket_dir = sandbox.ledger / "skills" / "s"
        (bucket_dir / "proposals").mkdir(parents=True, exist_ok=True)
        (bucket_dir / "proposals" / "merge-deadbeef.yaml").write_text(
            merge_proposal_text(
                "merge-deadbeef", ["lrn-aa000007", "lrn-aa000008"], "lrn-aa000007"
            ),
            encoding="utf-8",
        )
        clusters = ledger.read_clusters(bucket_dir)
        assert len(clusters) == 1
        assert clusters[0]["cluster_id"] == "merge-deadbeef"
        assert clusters[0]["suggested_survivor"] == "lrn-aa000007"

    def test_schema_invalid_cluster_is_skipped_not_raised(self, sandbox):
        bucket_dir = sandbox.ledger / "skills" / "s"
        (bucket_dir / "proposals").mkdir(parents=True, exist_ok=True)
        (bucket_dir / "proposals" / "merge-baadf00d.yaml").write_text(
            "cluster_id: merge-baadf00d\nrecords: [lrn-aa000009]\n",  # <2 records: invalid
            encoding="utf-8",
        )
        assert ledger.read_clusters(bucket_dir) == []

    def test_unparseable_cluster_file_is_skipped_not_raised(self, sandbox):
        bucket_dir = sandbox.ledger / "skills" / "s"
        (bucket_dir / "proposals").mkdir(parents=True, exist_ok=True)
        (bucket_dir / "proposals" / "merge-c0ffee00.yaml").write_text(
            "{{{not yaml", encoding="utf-8"
        )
        assert ledger.read_clusters(bucket_dir) == []


class TestProjectPathFor:
    def test_project_bucket_meta(self, sandbox):
        record = make_behavior(scope="project", record_id="lrn-aa00000a")
        seed_record(sandbox.ledger, record, project_path=sandbox.host)
        from self_learn.hosts import slug_for

        bucket_dir = sandbox.ledger / "projects" / slug_for(sandbox.host)
        assert ledger.project_path_for(bucket_dir) == str(sandbox.host.resolve())

    def test_skill_bucket_has_no_project_path(self, sandbox):
        assert ledger.project_path_for(sandbox.ledger / "skills" / "s") is None


class TestReadRegistry:
    def test_parses_the_real_card_sections_registry(self):
        registry = ledger.read_registry()
        keys = {r["key"] for r in registry}
        assert {"headline", "provenance", "impact", "discuss"} <= keys
        headline = next(r for r in registry if r["key"] == "headline")
        assert headline["label"] == "What this is about"
        assert headline["order"] == 10
        # ascending order — the registry's own render contract
        assert [r["order"] for r in registry] == sorted(r["order"] for r in registry)


class TestSentinelMtime:
    def test_no_sentinel_file_is_none(self, sandbox, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", sandbox.env["XDG_CACHE_HOME"])
        assert ledger.sentinel_mtime() is None

    def test_existing_sentinel_returns_its_mtime(self, sandbox, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", sandbox.env["XDG_CACHE_HOME"])
        from self_learn import sentinel as sl_sentinel

        path = sl_sentinel.sentinel_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sl_sentinel.sentinel_line(), encoding="utf-8")
        mtime = ledger.sentinel_mtime()
        assert mtime is not None
        assert mtime == pytest.approx(path.stat().st_mtime)
