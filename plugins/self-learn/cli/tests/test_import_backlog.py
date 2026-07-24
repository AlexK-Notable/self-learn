"""T9 backlog importer tests — fixture journal corpus, never the real files.

Fixture map (tests/fixtures/gotchas-journal-excerpt.md, 7 entries):

- e1 2026-06-02 "…must contain a hyphen…"   knowledge, date anchor (first of date)
- e2 2026-06-02 "…don't hit on-disk…"       knowledge, sha anchor (dup date)
- e3 2026-06-08 "Re-enabling a disabled…"   knowledge, IN canon → flagged
- e4 2026-06-14 "Beacon DHCP IP change…"    knowledge, not in canon
- e5 2026-06-15 "Never edit `.storage`…"    behavior (title-initial Never),
                                            IN canon but NEVER bulk-flagged
- e6 (dateless) "Follow-up — tree floor…"   sha anchor
- e7 2026-07-03 "AL sleep mode gotcha"      knowledge, phrase IS in canon but
                                            normalized title < 24 chars →
                                            borderline → unflagged
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from self_learn.import_backlog import import_backlog, parse_journal
from self_learn.import_common import ImporterError
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import queue, read_proposal, resolve_record
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import make_env

FIXTURES = Path(__file__).parent / "fixtures"
JOURNAL_FIXTURE = FIXTURES / "gotchas-journal-excerpt.md"
CANON_FIXTURE = FIXTURES / "gotchas-canon-excerpt.md"

SKILL = "home-assistant"
SHA_ORIGIN_RE = re.compile(r"^GOTCHAS\.journal\.md#sha256:[0-9a-f]{12}$")
DATE_ORIGINS = {
    "GOTCHAS.journal.md#2026-06-02",
    "GOTCHAS.journal.md#2026-06-08",
    "GOTCHAS.journal.md#2026-06-14",
    "GOTCHAS.journal.md#2026-06-15",
    "GOTCHAS.journal.md#2026-07-03",
}


def setup_home(tmp_path: Path, with_canon: bool = True) -> tuple[Path, Path]:
    # doc 13 §2: the GOTCHAS journal is source material living in the HOST
    # skill dir; the ledger bucket holds records only. import_backlog
    # resolves references/ from the registered skills-root host.
    env = make_env(tmp_path, skills=(SKILL,))
    refs = env.skill_dir / "references"
    refs.mkdir(parents=True)
    shutil.copy(JOURNAL_FIXTURE, refs / "GOTCHAS.journal.md")
    if with_canon:
        shutil.copy(CANON_FIXTURE, refs / "GOTCHAS.md")
    return env.ledger, refs


def bucket_of(home: Path):
    (b,) = [b for b in discover_buckets(home) if b.scope == "skill"]
    return b


def records_by_origin(home: Path, report) -> dict[str, Record]:
    out = {}
    for entry in queue(bucket_of(home)):
        out[report.origins[entry.record.id]] = entry.record
    return out


def id_for(report, origin: str) -> str:
    for rid, o in report.origins.items():
        if o == origin:
            return rid
    raise AssertionError(f"no created record for origin {origin}")


# ------------------------------------------------------------------ parsing


def test_parse_journal_counts_and_boundaries():
    entries = parse_journal(JOURNAL_FIXTURE.read_text(encoding="utf-8"))
    assert len(entries) == 7
    dates = [e.date for e in entries]
    assert dates == [
        "2026-06-02",
        "2026-06-02",
        "2026-06-08",
        "2026-06-14",
        "2026-06-15",
        None,  # the anchor-less follow-up entry
        "2026-07-03",
    ]
    # bullet fields parse: every entry carries a Fix
    assert all("Fix" in e.fields for e in entries)


# ------------------------------------------------------------- import basics


def test_import_creates_records_with_pinned_origins(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    assert len(report.created) == 7
    origins = set(report.origins.values())
    assert DATE_ORIGINS <= origins
    sha_origins = origins - DATE_ORIGINS
    assert len(sha_origins) == 2  # dup-date second entry + dateless entry
    assert all(SHA_ORIGIN_RE.match(o) for o in sha_origins)
    assert report.skipped_dup == [] and report.scan_refused == []


def test_imported_records_are_triage_visible_with_origin_preserved(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    entries = queue(bucket_of(home))  # THE queue computation sees them
    assert {e.record.id for e in entries} == set(report.created)
    for entry in entries:
        assert entry.record.source == "backlog"
        assert entry.record.scope == f"skill:{SKILL}"
        origins = [ev.get("origin") for ev in entry.record.evidence]
        assert origins == [report.origins[entry.record.id]]


def test_type_inference_title_initial_imperative_only(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    by_origin = records_by_origin(home, report)
    storage = by_origin["GOTCHAS.journal.md#2026-06-15"]
    assert storage.type == "behavior"
    assert storage.kind == "anti-pattern"
    assert "## Trigger" in storage.body and "## Instruction" in storage.body
    # mid-sentence "must" / "don't" stay knowledge (under-classify bias)
    assert by_origin["GOTCHAS.journal.md#2026-06-02"].type == "knowledge"
    others = [r for o, r in by_origin.items() if o != "GOTCHAS.journal.md#2026-06-15"]
    assert all(r.type == "knowledge" for r in others)


def test_missing_journal_raises(tmp_path):
    # host skill dir exists (via make_env) but has no references/ journal
    home = make_env(tmp_path, skills=(SKILL,)).ledger
    with pytest.raises(ImporterError):
        import_backlog(home, SKILL)


# --------------------------------------------------------- origin stability


def test_origins_stable_across_reflow(tmp_path):
    home_a, _ = setup_home(tmp_path / "a")
    report_a = import_backlog(home_a, SKILL)

    home_b, refs_b = setup_home(tmp_path / "b")
    journal = refs_b / "GOTCHAS.journal.md"
    text = journal.read_text(encoding="utf-8")
    reflowed = text.replace("\n### ", "\n\n\n\n### ") + "\n\n\n"
    journal.write_text(reflowed, encoding="utf-8")
    report_b = import_backlog(home_b, SKILL)

    assert set(report_a.origins.values()) == set(report_b.origins.values())


def test_idempotent_reimport_creates_zero(tmp_path):
    home, _ = setup_home(tmp_path)
    first = import_backlog(home, SKILL)
    second = import_backlog(home, SKILL)
    assert second.created == []
    assert set(second.skipped_dup) == set(first.origins.values())


def test_rejected_origin_never_reimports(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    rid = id_for(report, "GOTCHAS.journal.md#2026-06-14")
    resolve_record(home, rid, "rejected")  # record now lives in resolved/
    again = import_backlog(home, SKILL)
    assert again.created == []
    assert "GOTCHAS.journal.md#2026-06-14" in again.skipped_dup


# ------------------------------------------------------ already-canon flag


def test_canon_flagged_entry_gets_proposal_sibling(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    assert len(report.flagged_canon) == 1
    rid = report.flagged_canon[0]
    assert report.origins[rid] == "GOTCHAS.journal.md#2026-06-08"

    bucket = bucket_of(home)
    record = Record.from_path(bucket.path / "pending" / f"{rid}.md")
    proposal = read_proposal(bucket.path / "proposals" / f"{rid}.yaml")
    assert proposal["already_canon"] is True
    assert proposal["already_canon_reason"].strip()
    assert proposal["destination"] == "reference"
    assert proposal["record_sha"] == sha_anchor(record.body)  # CLI-stamped
    # the record itself stays clean: flag lives only in the sibling
    assert "already_canon" not in record.to_text()


def test_behavioral_entry_never_bulk_flagged(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    # e5's title appears verbatim in canon, but it is behavior-type
    rid = id_for(report, "GOTCHAS.journal.md#2026-06-15")
    assert rid not in report.flagged_canon
    assert not (bucket_of(home).path / "proposals" / f"{rid}.yaml").exists()


def test_borderline_short_title_stays_unflagged(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    # e7's phrase is in canon but its normalized title is < 24 chars
    rid = id_for(report, "GOTCHAS.journal.md#2026-07-03")
    assert rid not in report.flagged_canon
    assert rid in report.behavioral_minority


def test_card_set_partition_is_exhaustive(tmp_path):
    home, _ = setup_home(tmp_path)
    report = import_backlog(home, SKILL)
    # exit (b) precondition: flagged majority vs card set, no overlap, no gap
    assert set(report.flagged_canon) | set(report.behavioral_minority) == set(
        report.created
    )
    assert set(report.flagged_canon) & set(report.behavioral_minority) == set()
    assert len(report.behavioral_minority) == 6


def test_no_canon_file_means_nothing_flagged(tmp_path):
    home, _ = setup_home(tmp_path, with_canon=False)
    report = import_backlog(home, SKILL)
    assert report.flagged_canon == []
    assert len(report.created) == 7


# ------------------------------------------------------------- secret scan


SECRET_ENTRY = """
### 2026-07-09 — printer bridge API key placement
- **Status:** unverified
- **Fix:** set api_key = hunter2secret99 in the bridge conf and restart
"""


def test_scan_refused_entry_is_skipped_not_fatal(tmp_path):
    home, refs = setup_home(tmp_path)
    journal = refs / "GOTCHAS.journal.md"
    journal.write_text(
        journal.read_text(encoding="utf-8") + SECRET_ENTRY, encoding="utf-8"
    )
    report = import_backlog(home, SKILL)
    assert len(report.created) == 7  # the other entries still import
    assert report.scan_refused == ["GOTCHAS.journal.md#2026-07-09"]
    pending = bucket_of(home).path / "pending"
    for path in pending.glob("*.md"):
        assert "hunter2secret99" not in path.read_text(encoding="utf-8")
