"""09 §5 unreadable-record row (FW-18): the degraded Detail view + the
Front/Bucket skip-and-count line.

Matrix — each 09 §5 failure class (YAML parse error, undecodable bytes,
schema/section ValidationError, OSError) against the surfaces it must
degrade on:

- Detail renders a DEGRADED view (never a 500, never a silent redirect):
  id + path always, frontmatter fields only when the mapping parses, the
  raw body verbatim, a plain-words notice, and the action bar (the verbs
  remain the enforcers).
- Front/Bucket lists SKIP the unreadable record and show a one-line
  count sourced from `status --json`'s `unreadable`/`total_unreadable`.

All homes are throwaway with XDG redirects (10 §0 rules 7/8); the count
tests go through the REAL CLI subprocess (the worktree self-learn), so
they also prove the CLI half produces the field end to end.
"""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from self_learn_ui import ledger
from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.runner import FakeRunner

from support import make_behavior, make_env, seed_record

TOKEN = "test-token"


def make_client(sb, *, port: int = 7357) -> TestClient:
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    c = TestClient(app, base_url=f"http://127.0.0.1:{port}")
    c.cookies.set("slu_token", TOKEN)
    return c


def _seed_bucket_with_valid(sb):
    """Seed one VALID skill:s record so the bucket exists on disk; return
    its pending/ directory (where corrupt siblings are written)."""
    rec = make_behavior(scope="skill:s")
    path = seed_record(sb.ledger, rec)
    return rec, path.parent


def _write_yaml_error(pending_dir, rid="lrn-deadbe01"):
    p = pending_dir / f"{rid}.md"
    p.write_text("---\nfoo: [unclosed\n---\nBODY-VISIBLE-YAML\n", encoding="utf-8")
    return rid, p


def _write_undecodable(pending_dir, rid="lrn-deadbe02"):
    p = pending_dir / f"{rid}.md"
    p.write_bytes(b"---\nid: \xff\xfe not utf-8\n---\nbody\n")
    return rid, p


def _write_schema_invalid(pending_dir, rid="lrn-deadbe03"):
    # Valid YAML mapping frontmatter (so the salvage layer CAN show fields)
    # that nonetheless fails schema validation (type not in the enum).
    p = pending_dir / f"{rid}.md"
    p.write_text(
        f"---\nid: {rid}\ntype: BOGUSTYPE\nscope: user\n---\nbody\n",
        encoding="utf-8",
    )
    return rid, p


# --------------------------------------------------- Detail degraded render


class TestDetailDegradedRender:
    """Every failure class renders the degraded Detail view, never a 500,
    never a redirect-as-not-found. Kill: revert read_record's catch set to
    `except RecordError:` and the decode/YAML/OSError navigations 500;
    revert the detail_page degraded branch and they redirect (303) to
    Front, dropping the salvage view — either way these redden."""

    def test_yaml_parse_error_renders_degraded_with_body_and_action_bar(
        self, tmp_path
    ):
        sb = make_env(tmp_path)
        _rec, pending = _seed_bucket_with_valid(sb)
        rid, path = _write_yaml_error(pending)
        c = make_client(sb)
        r = c.get(f"/record/{rid}")
        assert r.status_code == 200
        assert "could not be fully read" in r.text
        assert rid in r.text  # id salvage layer, always
        assert path.name in r.text  # path salvage layer, always
        assert "BODY-VISIBLE-YAML" in r.text  # raw body verbatim
        assert 'data-key-action="route"' in r.text  # action bar stays

    def test_undecodable_bytes_renders_degraded_not_500(self, tmp_path):
        sb = make_env(tmp_path)
        _rec, pending = _seed_bucket_with_valid(sb)
        rid, path = _write_undecodable(pending)
        c = make_client(sb)
        r = c.get(f"/record/{rid}")
        assert r.status_code == 200
        assert "could not be fully read" in r.text
        assert rid in r.text
        assert path.name in r.text
        assert 'data-key-action="route"' in r.text

    def test_schema_invalid_renders_degraded_and_shows_frontmatter_fields(
        self, tmp_path
    ):
        sb = make_env(tmp_path)
        _rec, pending = _seed_bucket_with_valid(sb)
        rid, path = _write_schema_invalid(pending)
        c = make_client(sb)
        r = c.get(f"/record/{rid}")
        assert r.status_code == 200
        assert "could not be fully read" in r.text
        assert rid in r.text
        # frontmatter parsed to a mapping → its fields are salvaged/shown,
        # but decision content is NEVER section-parsed.
        assert "BOGUSTYPE" in r.text
        assert 'data-key-action="route"' in r.text

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="chmod 000 does not deny read to root",
    )
    def test_oserror_unreadable_renders_degraded_id_and_path_only(self, tmp_path):
        sb = make_env(tmp_path)
        _rec, pending = _seed_bucket_with_valid(sb)
        rid = "lrn-deadbe04"
        path = pending / f"{rid}.md"
        path.write_text(f"---\nid: {rid}\n---\nbody\n", encoding="utf-8")
        path.chmod(0o000)
        try:
            c = make_client(sb)
            r = c.get(f"/record/{rid}")
            assert r.status_code == 200
            assert "could not be fully read" in r.text
            assert rid in r.text
            assert path.name in r.text
            assert 'data-key-action="route"' in r.text
        finally:
            path.chmod(0o644)

    def test_genuinely_unknown_id_still_redirects_to_front_not_found(self, tmp_path):
        # The degraded branch must NOT swallow a real miss: an id with no
        # file on disk redirects to Front (303), unchanged behavior.
        sb = make_env(tmp_path)
        _seed_bucket_with_valid(sb)
        c = make_client(sb)
        r = c.get("/record/lrn-00000000", follow_redirects=False)
        assert r.status_code == 303
        assert "notice=not-found" in r.headers["location"]


# ---------------------------------------------- Front / Bucket skip + count


class TestFrontBucketSkipAndCount:
    """The list surfaces skip the unreadable record (it never appears as a
    normal row) and show a one-line count from `status --json`. These go
    through the real CLI subprocess. Kill: drop the count line from the
    template, or the field from status_infos, and the assertion reddens."""

    def test_front_shows_total_unreadable_count_line(self, tmp_path):
        sb = make_env(tmp_path)
        _rec, pending = _seed_bucket_with_valid(sb)
        _write_yaml_error(pending, rid="lrn-deadbe01")
        _write_undecodable(pending, rid="lrn-deadbe02")
        c = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200
        assert "could not be read" in r.text
        assert "2 records could not be read" in r.text

    def test_bucket_shows_its_own_unreadable_count_line_and_skips_the_record(
        self, tmp_path
    ):
        sb = make_env(tmp_path)
        rec, pending = _seed_bucket_with_valid(sb)
        bad_rid, _ = _write_yaml_error(pending, rid="lrn-deadbe01")
        c = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert "1 record could not be read" in r.text
        # the valid record still lists; the corrupt one is skipped, never a
        # normal row.
        assert rec.id in r.text
        assert f'href="/record/{bad_rid}"' not in r.text

    def test_clean_bucket_shows_no_count_line(self, tmp_path):
        sb = make_env(tmp_path)
        _seed_bucket_with_valid(sb)
        c = make_client(sb)
        r = c.get("/bucket/skill/s")
        assert r.status_code == 200
        assert "could not be read" not in r.text


# ------------------------------------------------- salvage_record layers


class TestSalvageRecordLayers:
    """The pinned 09 §5 salvage layers, unit-tested against
    :func:`ledger.salvage_record` directly (no subprocess): id + path
    always; frontmatter ONLY when the block parses to a mapping; body
    verbatim; NEVER section-parsed."""

    def test_yaml_error_yields_body_but_no_frontmatter(self, tmp_path):
        p = tmp_path / "lrn-deadbe01.md"
        p.write_text("---\nfoo: [unclosed\n---\nBODY-TEXT\n", encoding="utf-8")
        sr = ledger.salvage_record(p, "lrn-deadbe01")
        assert sr.record_id == "lrn-deadbe01"
        assert sr.path == p
        assert sr.frontmatter is None  # unparseable block → no fields shown
        assert sr.raw_body == "BODY-TEXT\n"

    def test_schema_invalid_yields_parsed_frontmatter_mapping(self, tmp_path):
        p = tmp_path / "lrn-deadbe03.md"
        p.write_text(
            "---\nid: lrn-deadbe03\ntype: BOGUSTYPE\n---\nBODY\n", encoding="utf-8"
        )
        sr = ledger.salvage_record(p, "lrn-deadbe03")
        assert sr.frontmatter == {"id": "lrn-deadbe03", "type": "BOGUSTYPE"}
        assert sr.raw_body == "BODY\n"

    def test_undecodable_bytes_yields_no_frontmatter_never_raises(self, tmp_path):
        p = tmp_path / "lrn-deadbe02.md"
        p.write_bytes(b"---\nid: \xff\xfe\n---\nbody\n")
        sr = ledger.salvage_record(p, "lrn-deadbe02")
        assert sr.record_id == "lrn-deadbe02"
        assert sr.frontmatter is None

    def test_missing_file_yields_id_and_path_only(self, tmp_path):
        p = tmp_path / "lrn-deadbe05.md"  # never created
        sr = ledger.salvage_record(p, "lrn-deadbe05")
        assert sr.record_id == "lrn-deadbe05"
        assert sr.path == p
        assert sr.frontmatter is None
        assert sr.raw_body is None

    def test_read_record_returns_none_on_every_failure_class(self, tmp_path):
        yaml_bad = tmp_path / "lrn-deadbe01.md"
        yaml_bad.write_text("---\nfoo: [unclosed\n---\nb\n", encoding="utf-8")
        decode_bad = tmp_path / "lrn-deadbe02.md"
        decode_bad.write_bytes(b"---\n\xff\xfe\n---\nb\n")
        schema_bad = tmp_path / "lrn-deadbe03.md"
        schema_bad.write_text("---\nid: lrn-deadbe03\ntype: X\n---\nb\n", encoding="utf-8")
        for bad in (yaml_bad, decode_bad, schema_bad):
            assert ledger.read_record(bad) is None
