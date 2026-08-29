"""Unit tests for self_learn.landing.checks + .sanitize + .state.

Positive controls come first in each group (§0's habit): a clean fixture
must pass before a seeded one is shown to fail, so a vacuous check (one
that always passes) cannot hide behind a single-direction test.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from self_learn.landing import checks as CH
from self_learn.landing import sanitize as SAN
from self_learn.landing import state as ST


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def make_min_repo(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "docs/specs/self-learn/drafts").mkdir(parents=True)
    (root / "plugins/self-learn/cli/tests").mkdir(parents=True)
    (root / "docs/specs/self-learn/03-decisions.md").write_text(
        "| S-1 | a | r |\n| S-2 | b | r |\n"
    )
    (root / "docs/specs/self-learn/14-forward-work-map.md").write_text(
        "| FW-1 | a | | |\n| FW-2 | b | | |\n"
    )
    return root


# ---------------------------------------------------------------------------
# CHK1 -- conflict markers over an explicit path list

def test_chk1_positive_control_clean_files_pass(tmp_path):
    root = make_min_repo(tmp_path)
    clean = root / "clean.md"
    clean.write_text("nothing wrong here\n")
    CH.check_no_markers([clean])  # must not raise


def test_chk1_finds_markers_outside_the_hardcoded_three_docs(tmp_path):
    """Today's ad-hoc landing-checks.py only scans three hardcoded docs; a
    marker in a FOURTH file (this is the case it can't see)."""
    root = make_min_repo(tmp_path)
    fourth = root / "plugins/self-learn/cli/tests/some_other_file.md"
    fourth.write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> b\n")
    with pytest.raises(CH.CheckFailure):
        CH.check_no_markers([fourth])


# ---------------------------------------------------------------------------
# CHK2 -- pins vs live bytes, N >= 1 floor

def test_chk2_positive_control_matching_pins_pass(tmp_path):
    root = make_min_repo(tmp_path)
    pinned = root / "plugins/self-learn/cli/tests/backends.py"
    pinned.write_text("content\n")
    sha = hashlib.sha256(pinned.read_bytes()).hexdigest()
    wc = root / "plugins/self-learn/cli/tests/test_worker_contract.py"
    wc.write_text(f'_ARMOR_SHAS = {{\n    "plugins/self-learn/cli/tests/backends.py": "{sha}",\n}}\n')
    n = CH.check_pins_or_raise(root)
    assert n == 1


def test_chk2_refuses_on_mismatch(tmp_path):
    root = make_min_repo(tmp_path)
    pinned = root / "plugins/self-learn/cli/tests/backends.py"
    pinned.write_text("content\n")
    wc = root / "plugins/self-learn/cli/tests/test_worker_contract.py"
    wc.write_text('_ARMOR_SHAS = {\n    "plugins/self-learn/cli/tests/backends.py": "' + "0" * 64 + '",\n}\n')
    with pytest.raises(CH.CheckFailure, match="mismatches"):
        CH.check_pins_or_raise(root)


def test_chk2_refuses_when_zero_pins_checked_gate_m6(tmp_path):
    """§0: absence is never asserted by a bare zero -- 0 pins must REFUSE,
    not print a pass. This is incident 2's class arriving via _ARMOR_SHAS
    being emptied (e.g. by U-armor's own DEL1)."""
    root = make_min_repo(tmp_path)
    wc = root / "plugins/self-learn/cli/tests/test_worker_contract.py"
    wc.write_text("_ARMOR_SHAS = {\n}\n")
    with pytest.raises(CH.CheckFailure, match="N < 1"):
        CH.check_pins_or_raise(root)


# ---------------------------------------------------------------------------
# CHK3 -- row order, per contiguous run

def test_chk3_positive_control_monotonic_passes(tmp_path):
    root = make_min_repo(tmp_path)
    CH.check_row_order_or_raise(root)  # must not raise


def test_chk3_real_history_duplicate_fw130_is_a_genuine_red_green_pair():
    """CHK3's MEASURED control: master's own history has a real duplicate
    FW-130 row at one commit, collapsed at its child."""
    dup_text = "| FW-129 | a | | |\n| FW-130 | b | | |\n| FW-130 | c | | |\n| FW-131 | d | | |\n"
    fixed_text = "| FW-129 | a | | |\n| FW-130 | b | | |\n| FW-131 | d | | |\n"
    assert CH.check_row_order(dup_text, "FW") == [(130, 130)]
    assert CH.check_row_order(fixed_text, "FW") == []


def test_chk3_separate_tables_do_not_collide(tmp_path):
    """§4.5's own finding: the real FW file holds SEVERAL tables, so the
    raw sequence is not globally monotonic -- the check is per contiguous
    run (rows with no non-row line between them), not one global sequence.
    A header/prose LINE between two tables breaks the run; two directly
    adjacent rows from different tables (no separator at all) are
    indistinguishable from one run and correctly still checked together --
    §12 item 5 records this as an open question about the real file, not
    a defect in this check."""
    text = "| FW-141 | a | | |\n\n## a new section\n\n| FW-30 | new table start | | |\n"
    assert CH.check_row_order(text, "FW") == []  # a real gap (blank + heading) breaks the run


def test_chk3_refuses_within_one_contiguous_run(tmp_path):
    text = "| FW-10 | a | | |\n| FW-5 | b | | |\n"
    assert CH.check_row_order(text, "FW") == [(10, 5)]


# ---------------------------------------------------------------------------
# CHK4 -- landing-state prose, quoted-pattern exemption

def test_chk4_positive_control_clean_docs_pass(tmp_path):
    root = make_min_repo(tmp_path)
    assert CH.check_prose(root) == []


def test_chk4_finds_a_live_hit(tmp_path):
    root = make_min_repo(tmp_path)
    (root / "docs/specs/self-learn/drafts/u-x.md").write_text("worktree left uncommitted\n")
    hits = CH.check_prose(root)
    assert hits


def test_chk4_quoted_pattern_table_is_exempt(tmp_path):
    root = make_min_repo(tmp_path)
    (root / "docs/specs/self-learn/drafts/u-x.md").write_text("still uncommitted 6 0\n")
    assert CH.check_prose(root) == []


# ---------------------------------------------------------------------------
# CHK6 -- verdict shape

def test_chk6_positive_control_normal_verdict_passes():
    CH.check_verdict_or_raise("blind Opus code gate CLEAN r3")


def test_chk6_refuses_empty():
    with pytest.raises(CH.CheckFailure):
        CH.check_verdict_or_raise("")


def test_chk6_refuses_newline():
    with pytest.raises(CH.CheckFailure):
        CH.check_verdict_or_raise("line1\nline2")


def test_chk6_refuses_over_budget():
    with pytest.raises(CH.CheckFailure):
        CH.check_verdict_or_raise("x" * 201)


def test_chk6_158_chars_is_within_budget():
    CH.check_verdict_or_raise("x" * 158)  # must not raise (N-6's measured max)


# ---------------------------------------------------------------------------
# WLD1/WLD2 -- world detection

def test_world_pre_armor_detects_armor_shas(tmp_path):
    root = make_min_repo(tmp_path)
    (root / "plugins/self-learn/cli/tests/test_worker_contract.py").write_text(
        '_ARMOR_SHAS = {\n    "plugins/x.py": "' + "a" * 64 + '",\n}\n'
    )
    assert CH.detect_world(root) == CH.WORLD_ARMOR_SHAS


def test_world_post_armor_detects_remeasure(tmp_path):
    root = make_min_repo(tmp_path)
    (root / "plugins/self-learn/cli/tests/test_armor.py").write_text("# stub\n")
    (root / "plugins/self-learn/cli/tests/test_worker_contract.py").write_text("# no pins here\n")
    assert CH.detect_world(root) == CH.WORLD_REMEASURE


def test_world_refuses_when_both_present_gate_m6():
    """The U-armor build IS this case: DEL1 requires _ARMOR_SHAS gone once
    test_armor.py exists; catching BOTH present is the ambiguity guard."""


def test_world_refuses_both_present(tmp_path):
    root = make_min_repo(tmp_path)
    (root / "plugins/self-learn/cli/tests/test_armor.py").write_text("# stub\n")
    (root / "plugins/self-learn/cli/tests/test_worker_contract.py").write_text(
        '_ARMOR_SHAS = {\n    "plugins/x.py": "' + "a" * 64 + '",\n}\n'
    )
    with pytest.raises(CH.CheckFailure, match="BOTH"):
        CH.detect_world(root)


def test_world_refuses_neither_present(tmp_path):
    root = make_min_repo(tmp_path)
    (root / "plugins/self-learn/cli/tests/test_worker_contract.py").write_text("# no pins\n")
    with pytest.raises(CH.CheckFailure, match="NEITHER"):
        CH.detect_world(root)


# ---------------------------------------------------------------------------
# sanitize.py -- added-lines-only parser, exact ack coverage

def make_diff_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def test_san_added_lines_only_scans_added_content(tmp_path):
    repo = make_diff_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "docs.md").write_text("clean line\nSEEDED password here\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add")
    lines = SAN.added_lines(repo, "master..feature")
    texts = [t for _, _, t in lines]
    assert "SEEDED password here" in texts
    assert not any(t.startswith("+++") for t in texts)  # headers excluded by construction


def test_san3_modifying_a_file_does_not_rescan_its_unchanged_lines(tmp_path):
    """M20: SAN3 must scan ADDED lines only, never the whole file --
    appending one new line to an existing file must not resurface the
    file's pre-existing (unchanged) lines as 'added'."""
    repo = make_diff_repo(tmp_path)
    (repo / "README.md").write_text("base\nPRE-EXISTING-UNCHANGED-CONTENT\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed pre-existing content")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "README.md").write_text("base\nPRE-EXISTING-UNCHANGED-CONTENT\nNEWLY ADDED LINE\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "append")
    lines = SAN.added_lines(repo, "master..feature")
    texts = [t for _, _, t in lines]
    assert "NEWLY ADDED LINE" in texts
    assert "PRE-EXISTING-UNCHANGED-CONTENT" not in texts
    assert "base" not in texts


def test_san_secret_named_file_is_not_a_hit_via_the_parser(tmp_path):
    """The header-vs-content discriminator (gate M-14): a file literally
    NAMED secret_fixture.md, contents 'clean', is 0 hits via the parser
    (the +++ HEADER line, which contains the word 'secret', is excluded)."""
    repo = make_diff_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "docs").mkdir()
    (repo / "docs/secret_fixture.md").write_text("clean\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add")
    fragments = Path(__file__).resolve().parent.parent / "src/self_learn/landing/sanitize_fragments.txt"
    hits = SAN.hits(repo, "master..feature", fragments)
    assert hits == []


def test_san_assembled_pattern_matches_claude_local_set(tmp_path):
    fragments = Path(__file__).resolve().parent.parent / "src/self_learn/landing/sanitize_fragments.txt"
    pattern = SAN.assemble_pattern(fragments, "/home/nobody")
    for word in ("secret", "password", "PRIVATE KEY", "ghp_deadbeef", "bearer abcdefgh12", "apikey", "api_key", "/home/nobody"):
        assert pattern.search(word), f"{word!r} should match"
    assert not pattern.search("ordinary text with no pattern words")


def test_san5_pattern_is_read_from_the_given_fragments_file_not_hardcoded(tmp_path):
    """SAN5 legs (a)/(b) (M51): the pattern set must be SOURCED from
    whatever fragments file is passed in, never inlined/hardcoded in
    Python -- a custom fragments file with a distinctive alternative not
    present in the shipped set must show up in the assembled pattern."""
    custom = tmp_path / "custom_fragments.txt"
    custom.write_text("UNIQUEMARKERXYZ123\n")
    pattern = SAN.assemble_pattern(custom, "/home/nobody")
    assert pattern.search("UNIQUEMARKERXYZ123")
    assert not pattern.search("secret")  # NOT the shipped set's words


def test_san_collision_line_that_looks_like_a_header_is_still_content(tmp_path):
    """M76 (SAN3's collision leg): a genuine ADDED content line that
    happens to read exactly like a '+++ b/...' header must stay
    attributed to the REAL file it lives in -- the header/content
    discriminator is gated on 'diff --git', never on '+++ b/' text
    appearing anywhere in the stream."""
    repo = make_diff_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "feature")
    # the file's OWN content line is "++ b/evil-path" (two literal plus
    # signs) -- git diff's own leading '+' marker makes the RAW diff line
    # read "+++ b/evil-path" (three), the exact shape a header-anywhere
    # heuristic would mistake for a new file's header.
    (repo / "real.md").write_text("clean line\n++ b/evil-path\nSEEDED password here\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add")
    lines = SAN.added_lines(repo, "master..feature")
    files = {f for f, _, _ in lines}
    assert "real.md" in files
    assert "evil-path" not in files


def test_san_fragment_file_scores_zero_self_hits():
    """SAN5 leg (c): the shipped fragments file, presented as ADDED lines
    to its own gate, must score 0 -- unlike a verbatim form (4, per M54)."""
    fragments = Path(__file__).resolve().parent.parent / "src/self_learn/landing/sanitize_fragments.txt"
    pattern = SAN.assemble_pattern(fragments, "/home/nobody")
    added = [l for l in fragments.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    self_hits = sum(1 for l in added if pattern.search(l))
    assert self_hits == 0


def test_san_ack_exact_coverage_all_matched_passes():
    hits = [("f.md", 1, "SEEDED password")]
    sha = SAN.line_sha("SEEDED password")
    result = SAN.check_coverage(hits, [f"f.md:1:{sha}=verified fixture literal"])
    assert result.ok


def test_san_ack_leaves_one_hit_unacked_refuses():
    """The N-1-of-N-acks fail-open r2 could not see: partial coverage
    that validates the acks it WAS given, and proceeds anyway."""
    hits = [("f.md", 1, "SEEDED password"), ("f.md", 2, "ghp_deadbeef")]
    sha1 = SAN.line_sha("SEEDED password")
    result = SAN.check_coverage(hits, [f"f.md:1:{sha1}=verified"])
    assert not result.ok
    assert len(result.unacked) == 1


def test_san_ack_stale_ack_refuses():
    result = SAN.check_coverage([], [f"f.md:1:{'a' * 64}=stale"])
    assert not result.ok
    assert result.stale


def test_san_ack_empty_reason_refuses():
    hits = [("f.md", 1, "SEEDED password")]
    sha = SAN.line_sha("SEEDED password")
    result = SAN.check_coverage(hits, [f"f.md:1:{sha}="])
    assert not result.ok
    assert result.empty_reason


def test_san_ack_two_identical_lines_need_two_acks():
    hits = [("f.md", 1, "SEEDED password"), ("f.md", 5, "SEEDED password")]
    sha = SAN.line_sha("SEEDED password")
    result = SAN.check_coverage(hits, [f"f.md:1:{sha}=one"])
    assert not result.ok
    assert len(result.unacked) == 1
    assert result.unacked[0][1] == 5


def test_san_ack_split_at_first_equals_after_hash():
    sha = "a" * 64
    f, n, s, reason = SAN.parse_ack(f"file.md:3:{sha}=reason with an = sign in it")
    assert reason == "reason with an = sign in it"
    assert s == sha
    assert n == 3


def test_san_no_home_literal_in_shipped_script():
    land = Path(__file__).resolve().parent.parent / "scripts/land"
    text = land.read_text()
    import os
    home = os.environ.get("HOME", "")
    assert home, "HOME must be set for this control to mean anything"
    assert home not in text


# ---------------------------------------------------------------------------
# state.py -- CNT1/CNT2

def test_state_write_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    ST.write_state("u-test", base_sha="abc", merge_sha="def", parent_shas=["a", "b"])
    st = ST.read_state("u-test")
    assert st["base_sha"] == "abc"
    assert st["merge_sha"] == "def"
    ST.clear_state("u-test")
    assert ST.read_state("u-test") is None
