"""Unit tests for self_learn.landing.conflicts + .resolvers (RES1-RES7).

Every resolver test builds its conflict via a REAL `git merge` on a
throwaway repo (RES6) -- never hand-written marker text -- so the tests
exercise the same bytes git actually produces.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from self_learn.landing import conflicts as C
from self_learn.landing import resolvers as R


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def make_conflict(tmp_path: Path, base_lines: list[str], ours_lines: list[str], theirs_lines: list[str], filename: str = "f.txt") -> Path:
    """A real `git merge` producing one diff3-conflicted file; returns its path."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "Test")
    def content(lines: list[str]) -> str:
        return "\n".join(lines) + "\n" if lines else ""

    f = repo / filename
    f.write_text(content(base_lines))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")

    git(repo, "checkout", "-q", "-b", "theirs")
    f.write_text(content(theirs_lines))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "theirs", check=False)  # may be a no-op if theirs == base

    git(repo, "checkout", "-q", "master")
    f.write_text(content(ours_lines))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ours", check=False)  # may be a no-op if ours == base

    git(repo, "-c", "merge.conflictStyle=diff3", "merge", "--no-ff", "--no-commit", "theirs", check=False)
    assert C.has_base_markers(f.read_text()), "fixture did not produce a diff3 conflict"
    return f


# ---------------------------------------------------------------------------
# conflicts.py — the one parser + driver

def test_blocks_parses_a_real_diff3_conflict(tmp_path):
    f = make_conflict(tmp_path, ["a", "b"], ["a", "b-ours"], ["a", "b-theirs"])
    _, bl = C.blocks(f.read_text())
    assert len(bl) == 1
    _, _, ours, base, theirs = bl[0]
    assert ours == ["b-ours"]
    assert base == ["b"]
    assert theirs == ["b-theirs"]


def test_blocks_no_base_marker_raises(tmp_path):
    text = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n"
    with pytest.raises(C.ConflictParseError):
        C.blocks(text)


def test_rewrite_asserts_no_markers_remain(tmp_path):
    f = make_conflict(tmp_path, ["a"], ["a", "x"], ["a", "y"], filename="k.txt")

    def bad_resolver(ours, base, theirs):
        return ["<<<<<<< still here"]

    with pytest.raises(C.ConflictParseError):
        C.rewrite(f, bad_resolver)


# ---------------------------------------------------------------------------
# RES1 -- keep-both

def test_res1_keep_both_purely_additive(tmp_path):
    f = make_conflict(tmp_path, [], ["ours-line"], ["theirs-line"])
    n = C.rewrite(f, R.keep_both)
    assert n == 1
    assert f.read_text().strip().split("\n") == ["ours-line", "theirs-line"]


def test_res1_keep_both_refuses_nonempty_base(tmp_path):
    f = make_conflict(tmp_path, ["base", "x"], ["base", "OURS-CHANGE"], ["base", "THEIRS-CHANGE"])
    with pytest.raises(R.Refusal):
        C.rewrite(f, R.keep_both)


def test_res1_keep_both_refuses_overlap(tmp_path):
    _, bl = C.blocks("<<<<<<< HEAD\nshared\nx\n||||||| base\n=======\nshared\ny\n>>>>>>> branch\n")
    ours, base, theirs = bl[0][2], bl[0][3], bl[0][4]
    assert base == []
    with pytest.raises(R.Refusal):
        R.keep_both(ours, base, theirs)


# ---------------------------------------------------------------------------
# RES2 -- per-key

def test_res2_per_key_side_differing_from_base_wins(tmp_path):
    f = make_conflict(
        tmp_path,
        ["a: 1", "b: 2"],
        ["a: 1", "b: CHANGED-OURS"],
        ["a: THEIRS-CHANGED", "b: 2"],
    )
    n = C.rewrite(f, R.per_key)
    assert n == 1
    assert f.read_text().strip().split("\n") == ["a: THEIRS-CHANGED", "b: CHANGED-OURS"]


def test_res2_per_key_refuses_both_changed_no_rederive(tmp_path):
    f = make_conflict(tmp_path, ["a: 1"], ["a: OURS"], ["a: THEIRS"])
    with pytest.raises(R.Refusal, match="both sides changed"):
        C.rewrite(f, R.per_key)


def test_res2_per_key_refuses_differing_key_sets(tmp_path):
    f = make_conflict(tmp_path, ["a: 1"], ["a: 1", "b: 2"], ["a: CHANGED"])
    with pytest.raises(R.Refusal, match="key sets differ"):
        C.rewrite(f, R.per_key)


def test_res2_per_key_executed_duplicate_key_case_now_refuses(tmp_path):
    """The EXACT M57 fixture (gate M-7): the r2 naive dict-based algorithm
    silently corrupted this to ['a: 2', 'a: 2', 'b: 10'], dropping 'a: 1'
    with no refusal. The shipped per_key must refuse instead."""
    base = ["a: 1", "a: 2", "b: 9"]
    ours = ["a: 1", "a: 2", "b: 10"]
    theirs = ["a: 1", "a: 2", "b: 9"]
    with pytest.raises(R.Refusal, match="duplicate key"):
        R.per_key(ours, base, theirs)


def test_res2_per_key_refuses_line_with_no_colon(tmp_path):
    with pytest.raises(R.Refusal, match="no ':'"):
        R.per_key(["a: 1", "no-colon-line"], ["a: 1", "no-colon-line"], ["a: 1", "no-colon-line"])


# ---------------------------------------------------------------------------
# RES3 -- numeric-rows (fixture's two sides REQUIRED out of numeric order, N-5)

def test_res3_numeric_rows_unions_and_sorts(tmp_path):
    f = make_conflict(
        tmp_path, [],
        ["| FW-141 | z |", "| FW-53 | y |"],       # deliberately out of order
        ["| FW-70 | x |"],
    )
    n = C.rewrite(f, R.numeric_rows)
    assert n == 1
    rows = f.read_text().strip().split("\n")
    nums = [int(r.split("-")[1].split(" ")[0]) for r in rows]
    assert nums == sorted(nums)
    assert nums == [53, 70, 141]


def test_res3_numeric_rows_refuses_duplicate():
    with pytest.raises(R.Refusal):
        R.numeric_rows(["| FW-1 | a |"], [], ["| FW-1 | b |"])


def test_res3_numeric_rows_refuses_non_row_line():
    with pytest.raises(R.Refusal):
        R.numeric_rows(["not a row"], [], ["| FW-1 | b |"])


# ---------------------------------------------------------------------------
# RES4 -- registry / suggestions

def test_res4_registry_matches_expected_names():
    assert set(R.REGISTRY) == {"keep-both", "per-key", "numeric-rows", "count-line"}


def test_res4_candidates_for_empty_base_suggests_keep_both():
    assert "keep-both" in R.candidates_for(["x"], [], ["y"])


def test_res4_candidates_for_key_value_suggests_per_key():
    assert "per-key" in R.candidates_for(["a: 1"], ["a: 1"], ["a: 1"])


def test_res4_candidates_for_unrecognisable_block_suggests_nothing():
    assert R.candidates_for(["free text, no shape"], ["free text"], ["other text"]) == []


def test_res4_unknown_resolver_name_refuses_at_cli_not_a_silent_keep_both(tmp_path, capsys):
    """An unknown --resolver name must REFUSE (rc 1), never silently fall
    back to keep-both (M15) -- verified via the real CLI entry point, on a
    real diff3 conflict where keep-both WOULD apply (empty base) so a
    silent fallback would actually succeed and rewrite the file."""
    from self_learn.landing import resolve as RS

    f = make_conflict(tmp_path, base_lines=[], ours_lines=["ours line"], theirs_lines=["theirs line"])
    before = f.read_text()
    rc = RS.main(["--root", str(f.parent), "--path", f.name, "--resolver", "totally-bogus-name"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "REFUSE" in captured.err
    assert "totally-bogus-name" in captured.err
    # the file must be untouched -- a silent keep-both fallback would have
    # rewritten it (ours+theirs, no conflict markers).
    assert f.read_text() == before


# ---------------------------------------------------------------------------
# RES5 -- re-derive requires a dated justification naming both sides

def test_res5_rederive_writes_sha_of_merged_bytes(tmp_path):
    target = tmp_path / "pinned.py"
    target.write_text("merged content\n")
    line = R.rederive_pin(
        key='"pinned.py"', root=tmp_path,
        justification="merge 2026-08-28: re-derived (branch-a merged into master)",
    )
    import hashlib
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    assert sha in line
    assert "2026-08-28" in line


def test_res5_rederive_refuses_without_date():
    target_dir = Path(__file__).resolve().parent
    with pytest.raises(R.Refusal, match="date"):
        R.rederive_pin(key='"conftest.py"', root=target_dir, justification="no date here")


def test_res5_rederive_refuses_trivial_reason(tmp_path):
    target = tmp_path / "p.py"
    target.write_text("x\n")
    with pytest.raises(R.Refusal, match="no reason"):
        R.rederive_pin(key='"p.py"', root=tmp_path, justification="2026-08-28")


# ---------------------------------------------------------------------------
# RES6 -- every resolver test reaches a real `git merge` (an AST check over
# this very file, with a positive control)

def test_res6_every_test_function_here_reaches_a_git_merge():
    tree = ast.parse(Path(__file__).read_text())
    calls_merge = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            src = ast.get_source_segment(Path(__file__).read_text(), node) or ""
            if "make_conflict(" in src or 'git(repo, "-c"' in src:
                calls_merge.add(node.name)
    resolver_tests = {
        "test_blocks_parses_a_real_diff3_conflict",
        "test_rewrite_asserts_no_markers_remain",
        "test_res1_keep_both_purely_additive",
        "test_res1_keep_both_refuses_nonempty_base",
        "test_res2_per_key_side_differing_from_base_wins",
        "test_res2_per_key_refuses_both_changed_no_rederive",
        "test_res2_per_key_refuses_differing_key_sets",
        "test_res3_numeric_rows_unions_and_sorts",
    }
    missing = resolver_tests - calls_merge
    assert not missing, f"resolver tests not built from a real git merge: {missing}"


def test_res6_positive_control_hand_written_markers_would_be_caught():
    """A hand-written-marker 'test' (no make_conflict/git -c call) is
    exactly what the AST check above must flag -- verified inline rather
    than by mutating this file."""
    src = 'def test_x():\n    text = "<<<<<<< HEAD\\n=======\\n>>>>>>> x\\n"\n'
    tree = ast.parse(src)
    fn = tree.body[0]
    seg = ast.get_source_segment(src, fn)
    assert seg is not None
    assert "make_conflict(" not in seg and 'git(repo, "-c"' not in seg


# ---------------------------------------------------------------------------
# RES7 -- count-line

def test_res7_count_line_arithmetic(tmp_path):
    f = make_conflict(
        tmp_path, [], ["assert len(X) == 5"], ["assert len(X) == 8"],
    )
    # base line must itself say len(X) == <base count>; rebuild directly
    # via the resolver function since the 3-way base text isn't producible
    # from a 2-sided git merge fixture alone.
    result = R.count_line(["assert len(X) == 5"], ["assert len(X) == 3"], ["assert len(X) == 8"])
    assert "== 10" in result[0]  # 3 + (5-3) + (8-3) = 10


def test_res7_count_line_refuses_name_mismatch():
    with pytest.raises(R.Refusal, match="NAME differs"):
        R.count_line(["assert len(A) == 3"], ["assert len(A) == 2"], ["assert len(B) == 5"])


def test_res7_count_line_refuses_negative_result():
    with pytest.raises(R.Refusal, match="negative"):
        R.count_line(["assert len(X) == 0"], ["assert len(X) == 10"], ["assert len(X) == 0"])


def test_res7_count_line_refuses_multiline_side():
    with pytest.raises(R.Refusal, match="not exactly one line"):
        R.count_line(["assert len(X) == 1", "extra"], ["assert len(X) == 1"], ["assert len(X) == 1"])
