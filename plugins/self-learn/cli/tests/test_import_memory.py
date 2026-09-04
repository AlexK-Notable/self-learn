"""T9 auto-memory importer + S-13 prune-sweep tests — fixture memory dir.

Fixture map (tests/fixtures/memory/): MEMORY.md index + 3 topic files —
research-archive.md (metadata.type: project → scope project),
review-doctrine.md (metadata.type: feedback → scope user),
beacon-host.md (no frontmatter → scope project).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from self_learn.import_common import ImporterError
from self_learn.import_memory import import_memory, prune_memory
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import queue, resolve_record
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import init_repo, make_env

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "memory"
TOPIC_FILES = ("beacon-host.md", "research-archive.md", "review-doctrine.md")
ORIGIN_RE = re.compile(r"^memory/[a-z-]+\.md#sha256:[0-9a-f]{12}$")


def setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    # doc 13 §3: project-scoped memories bind to a per-project bucket keyed
    # by the project's path; import_memory takes it via ``project_path``
    # (default: git toplevel of cwd). Tests pass one explicit sandbox repo
    # through :func:`_import` so no real cwd/project leaks in.
    home = make_env(tmp_path).ledger
    memory_dir = tmp_path / "memory"
    shutil.copytree(FIXTURE_DIR, memory_dir)
    project = tmp_path / "proj-repo"
    init_repo(project)
    return home, memory_dir, project


def _import(home, memory_dir, project, **kw):
    return import_memory(home, memory_dir, project_path=project, **kw)


def all_entries(home: Path):
    """Every queue entry across the project AND user buckets — the memory
    import now splits records across separate scopes (doc 13 §3)."""
    entries = []
    for b in discover_buckets(home):
        if b.scope in ("project", "user"):
            entries.extend(queue(b))
    return entries


def id_for(report, filename: str) -> str:
    for rid, origin in report.origins.items():
        if origin.startswith(f"memory/{filename}#"):
            return rid
    raise AssertionError(f"no created record for {filename}")


def record_of(home: Path, rid: str) -> Record:
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            path = bucket.path / sub / f"{rid}.md"
            if path.is_file():
                return Record.from_path(path)
    raise AssertionError(f"record {rid} not found")


# ----------------------------------------------------------------- import


def test_one_record_per_topic_file_index_excluded(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    assert len(report.created) == 3  # MEMORY.md is the index, never a record
    files = {origin.split("/", 1)[1].split("#", 1)[0] for origin in report.origins.values()}
    assert files == set(TOPIC_FILES)
    assert all(ORIGIN_RE.match(o) for o in report.origins.values())


def test_origin_is_hash_of_file_content(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    for fname in TOPIC_FILES:
        expected = f"memory/{fname}#{sha_anchor((memory_dir / fname).read_text())}"
        assert report.origins[id_for(report, fname)] == expected


def test_scope_mapping_and_source(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    assert record_of(home, id_for(report, "review-doctrine.md")).scope == "user"
    assert record_of(home, id_for(report, "research-archive.md")).scope == "project"
    assert record_of(home, id_for(report, "beacon-host.md")).scope == "project"
    for rid in report.created:
        record = record_of(home, rid)
        assert record.source == "auto-memory"
        assert record.type == "knowledge"


def test_fact_comes_from_description_frontmatter(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    record = record_of(home, id_for(report, "review-doctrine.md"))
    assert "sourced ≠ true" in record.body
    # triage-visible with origin preserved (exit e) — across BOTH the
    # project and user buckets the import now writes into (doc 13 §3).
    entries = all_entries(home)
    assert {e.record.id for e in entries} == set(report.created)


def test_idempotent_reimport_zero(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    first = _import(home, memory_dir, project)
    second = _import(home, memory_dir, project)
    assert second.created == []
    assert set(second.skipped_dup) == set(first.origins.values())


def test_rejected_memory_never_resurrects(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    rid = id_for(report, "beacon-host.md")
    resolve_record(home, rid, "rejected")
    again = _import(home, memory_dir, project)
    assert again.created == []
    assert report.origins[rid] in again.skipped_dup


def test_scan_refused_memory_file_skipped(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    (memory_dir / "creds.md").write_text(
        "The bridge uses token: abcdefgh12345678 for auth.\n", encoding="utf-8"
    )
    report = _import(home, memory_dir, project)
    assert len(report.created) == 3
    assert len(report.scan_refused) == 1
    assert report.scan_refused[0].startswith("memory/creds.md#")
    for bucket in discover_buckets(home):
        for path in (bucket.path / "pending").glob("*.md"):
            assert "abcdefgh12345678" not in path.read_text(encoding="utf-8")


def test_missing_memory_dir_raises(tmp_path):
    home = make_env(tmp_path).ledger
    with pytest.raises(ImporterError):
        import_memory(home, tmp_path / "nope")


# ------------------------------------------------------------ prune sweep


def test_prune_terminal_only_removes_file_and_index_line(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    routed = id_for(report, "research-archive.md")
    resolve_record(home, routed, "routed", destination="reference")

    prune = prune_memory(home, memory_dir)
    assert [(rid, f) for rid, f, _ in prune.pruned] == [
        (routed, "research-archive.md")
    ]
    assert not (memory_dir / "research-archive.md").exists()
    index = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "research-archive.md" not in index
    assert "review-doctrine.md" in index  # untouched neighbors survive
    # in-flight records refused, files intact
    refused_ids = {rid for rid, _, _ in prune.refused_in_flight}
    assert refused_ids == set(report.created) - {routed}
    assert (memory_dir / "review-doctrine.md").exists()
    assert (memory_dir / "beacon-host.md").exists()
    # visible confirmation names what it pruned
    assert "research-archive.md" in prune.summary()


def test_prune_rejected_and_superseded_also_prune(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    rejected = id_for(report, "beacon-host.md")
    graduated = id_for(report, "review-doctrine.md")
    resolve_record(home, rejected, "rejected")
    resolve_record(home, graduated, "superseded", superseded_by="canon")

    prune = prune_memory(home, memory_dir)
    assert {f for _, f, _ in prune.pruned} == {"beacon-host.md", "review-doctrine.md"}
    assert not (memory_dir / "beacon-host.md").exists()
    assert not (memory_dir / "review-doctrine.md").exists()


def test_prune_dry_run_touches_nothing(tmp_path):
    """M-Q code-gate r1 fold, MAJOR (must fold): the missing-target
    branch's `if not dry_run:` guard was untested -- deleting it left the
    suite fully green while a dry run rewrote MEMORY.md. `rejected` puts
    that branch LIVE during this same dry run (its file is gone before
    the snapshot below, so a dry-run index-drop would show up as a
    changed `MEMORY.md` in `after`), so `assert after == before` now
    covers both branches: the routed/pruned path AND the
    already-missing path."""
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    routed = id_for(report, "research-archive.md")
    resolve_record(home, routed, "routed", destination="reference")
    rejected = id_for(report, "beacon-host.md")
    resolve_record(home, rejected, "rejected")
    (memory_dir / "beacon-host.md").unlink()

    before = {p.name: p.read_text(encoding="utf-8") for p in memory_dir.glob("*.md")}
    prune = prune_memory(home, memory_dir, dry_run=True)
    assert prune.dry_run is True
    assert [(rid, f) for rid, f, _ in prune.pruned] == [
        (routed, "research-archive.md")
    ]
    assert [(rid, f) for rid, f, _ in prune.missing] == [
        (rejected, "beacon-host.md")
    ]
    after = {p.name: p.read_text(encoding="utf-8") for p in memory_dir.glob("*.md")}
    assert after == before  # nothing deleted, nothing rewritten -- either branch
    assert "would prune" in prune.summary()


def test_prune_leaves_drifted_files_alone(tmp_path):
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    rid = id_for(report, "beacon-host.md")
    resolve_record(home, rid, "rejected")
    target = memory_dir / "beacon-host.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nEdited after import.\n",
        encoding="utf-8",
    )

    prune = prune_memory(home, memory_dir)
    assert [(r, f) for r, f, _ in prune.drifted] == [(rid, "beacon-host.md")]
    assert prune.pruned == []
    assert target.exists()
    index = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "beacon-host.md" in index


def test_prune_reports_already_missing_files(tmp_path):
    """M-Q / plan v2 §2 (C14): constructs the HALF-PRUNED state directly
    -- the index line still present, the target file already gone (a
    hand-deletion outside `prune_memory`, standing in for anything that
    can remove the file without going through the sweep) -- and proves
    one `prune_memory` run heals it. Before M-Q this pinned the
    non-self-healing behaviour: the missing-target branch reported the
    record as missing but never touched the index, so a dangling
    `(beacon-host.md)` link would have survived every future sweep
    forever. The mutation this proves is the `if not dry_run:
    _drop_index_line(...)` call added to the missing-target branch --
    remove it and `index_after` below reverts to containing
    "beacon-host.md" and this test fails."""
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    rid = id_for(report, "beacon-host.md")
    resolve_record(home, rid, "rejected")

    # Half-pruned state: the target vanishes WITHOUT going through
    # prune_memory, so its index line is never touched -- unlike a normal
    # prune, which drops file and index line together.
    (memory_dir / "beacon-host.md").unlink()
    index_before = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "beacon-host.md" in index_before  # sanity: half-pruned, not clean

    first = prune_memory(home, memory_dir)
    assert first.pruned == []
    assert [(r, f) for r, f, _ in first.missing] == [(rid, "beacon-host.md")]
    index_after = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "beacon-host.md" not in index_after  # healed in the SAME run

    second = prune_memory(home, memory_dir)  # sweep is re-runnable
    assert second.pruned == []
    assert [(r, f) for r, f, _ in second.missing] == [(rid, "beacon-host.md")]


def test_prune_drops_index_line_before_unlink(tmp_path, monkeypatch):
    """M-Q / plan v2 §2 (C14): `_drop_index_line` runs BEFORE `unlink` in
    the success branch (idempotent-first ordering), so a crash between
    the two calls leaves at worst a dangling FILE with its index entry
    already gone -- never a dangling INDEX LINK pointing at a file
    that's already gone (the failure mode the missing-target self-heal
    above exists to recover from). Proven by making `unlink()` raise:
    with the new order the index line is already dropped by the time the
    exception propagates; reverting to `unlink()` then `_drop_index_line`
    would still show the index line intact here, and this test fails."""
    home, memory_dir, project = setup(tmp_path)
    report = _import(home, memory_dir, project)
    routed = id_for(report, "research-archive.md")
    resolve_record(home, routed, "routed", destination="reference")

    real_unlink = Path.unlink

    def boom(self, *a, **kw):
        if self.name == "research-archive.md":
            raise OSError("simulated crash between index-drop and unlink")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", boom)
    with pytest.raises(OSError):
        prune_memory(home, memory_dir)

    index = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "research-archive.md" not in index  # dropped before the raise
    assert (memory_dir / "research-archive.md").exists()  # unlink never ran
