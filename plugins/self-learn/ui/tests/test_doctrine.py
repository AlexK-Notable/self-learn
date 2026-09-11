"""The doctrine compiler (10 §1's "Doctrine compile" row; 10 §3 task U5
bullet 4): recompile-on-mtime, byte-stable between no-op recompiles, and
that :func:`plugin_references_dir` resolves to the real tracked skill
references dir (proving the real ``routing-doctrine.md`` +
``pane-charter.md`` this branch ships are found where the pin says).
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

from self_learn.primitives import fsops
from self_learn_ui.doctrine import (
    compile_doctrine,
    pane_charter_path,
    pane_surface_model_path,
    plugin_references_dir,
    read_doctrine,
    routing_doctrine_path,
)


def _sources(
    tmp_path: Path,
    routing: str = "ROUTING\n",
    charter: str = "CHARTER\n",
    surface: str = "SURFACE\n",
) -> dict[str, Path]:
    routing_path = tmp_path / "routing-doctrine.md"
    charter_path = tmp_path / "pane-charter.md"
    surface_path = tmp_path / "pane-surface-model.md"
    routing_path.write_text(routing, encoding="utf-8")
    charter_path.write_text(charter, encoding="utf-8")
    surface_path.write_text(surface, encoding="utf-8")
    return {
        "routing_path": routing_path,
        "charter_path": charter_path,
        "surface_model_path": surface_path,
        "compiled_path": tmp_path / "out" / "pane-doctrine.md",
    }


def test_compiles_all_three_sources_into_one_file(tmp_path: Path) -> None:
    paths = _sources(
        tmp_path, routing="ROUTING TEXT\n", charter="CHARTER TEXT\n", surface="SURFACE TEXT\n"
    )
    compiled = compile_doctrine(**paths)
    text = compiled.read_text(encoding="utf-8")
    assert "ROUTING TEXT" in text
    assert "SURFACE TEXT" in text
    assert "CHARTER TEXT" in text
    # Pinned order (Y-13 amendment of the doctrine-compile row): doctrine,
    # then the surface model, then the charter — the hard rules read
    # last, closest to the task.
    assert text.index("ROUTING TEXT") < text.index("SURFACE TEXT") < text.index("CHARTER TEXT")


def test_read_doctrine_returns_the_compiled_text(tmp_path: Path) -> None:
    paths = _sources(tmp_path)
    text = read_doctrine(**paths)
    assert "ROUTING" in text
    assert "CHARTER" in text


def test_no_recompile_when_sources_unchanged(tmp_path: Path) -> None:
    paths = _sources(tmp_path)
    first = compile_doctrine(**paths)
    first_mtime = first.stat().st_mtime_ns
    first_bytes = first.read_bytes()

    time.sleep(0.01)
    second = compile_doctrine(**paths)

    assert second == first
    assert second.stat().st_mtime_ns == first_mtime  # untouched — no rewrite happened
    assert second.read_bytes() == first_bytes


def test_recompiles_when_routing_source_mtime_advances(tmp_path: Path) -> None:
    paths = _sources(tmp_path, routing="ROUTING V1\n")
    compile_doctrine(**paths)

    time.sleep(0.01)
    paths["routing_path"].write_text("ROUTING V2\n", encoding="utf-8")
    # Make sure the new mtime is observably newer on filesystems with
    # coarse mtime resolution.
    newer = time.time() + 1
    os.utime(paths["routing_path"], (newer, newer))

    compiled = compile_doctrine(**paths)
    assert "ROUTING V2" in compiled.read_text(encoding="utf-8")
    assert "ROUTING V1" not in compiled.read_text(encoding="utf-8")


def test_recompiles_when_charter_source_mtime_advances(tmp_path: Path) -> None:
    paths = _sources(tmp_path, charter="CHARTER V1\n")
    compile_doctrine(**paths)

    time.sleep(0.01)
    paths["charter_path"].write_text("CHARTER V2\n", encoding="utf-8")
    newer = time.time() + 1
    os.utime(paths["charter_path"], (newer, newer))

    compiled = compile_doctrine(**paths)
    assert "CHARTER V2" in compiled.read_text(encoding="utf-8")


def test_recompiles_when_surface_model_mtime_advances(tmp_path: Path) -> None:
    paths = _sources(tmp_path, surface="SURFACE V1\n")
    compile_doctrine(**paths)

    time.sleep(0.01)
    paths["surface_model_path"].write_text("SURFACE V2\n", encoding="utf-8")
    newer = time.time() + 1
    os.utime(paths["surface_model_path"], (newer, newer))

    compiled = compile_doctrine(**paths)
    assert "SURFACE V2" in compiled.read_text(encoding="utf-8")


def test_byte_stable_across_repeated_recompiles_with_unchanged_sources(tmp_path: Path) -> None:
    """09 §4.2: "byte-stable across sessions by construction" — plain
    concatenation carries no timestamps or compile metadata, so forcing a
    recompile (by deleting the compiled artifact) with unchanged sources
    reproduces identical bytes."""
    paths = _sources(tmp_path)
    first = compile_doctrine(**paths)
    first_bytes = first.read_bytes()

    first.unlink()  # force an actual recompile, not the mtime-skip path
    second = compile_doctrine(**paths)
    assert second.read_bytes() == first_bytes


def test_compiled_path_created_under_its_parent_directory(tmp_path: Path) -> None:
    paths = _sources(tmp_path)
    assert not paths["compiled_path"].parent.is_dir()
    compile_doctrine(**paths)
    assert paths["compiled_path"].is_file()


def test_plugin_references_dir_resolves_to_the_real_tracked_skill_dir() -> None:
    """No override — proves the real (default-argument) path resolution
    lands on the actual references dir this branch ships, where
    routing-doctrine.md and pane-charter.md really live."""
    refs = plugin_references_dir()
    assert refs.name == "references"
    assert refs.parent.name == "self-learn"
    assert (refs / "routing-doctrine.md").is_file()
    assert (refs / "pane-charter.md").is_file()
    assert (refs / "pane-surface-model.md").is_file()
    assert routing_doctrine_path() == refs / "routing-doctrine.md"
    assert pane_charter_path() == refs / "pane-charter.md"
    assert pane_surface_model_path() == refs / "pane-surface-model.md"


def test_compile_doctrine_against_the_real_tracked_sources(tmp_path: Path) -> None:
    """Compiles the ACTUAL routing-doctrine.md + pane-surface-model.md +
    pane-charter.md this branch ships (only the compiled OUTPUT path is
    redirected to a tmp_path — 10 §0 rule 7/8 never touches the real
    cache)."""
    compiled_path = tmp_path / "pane-doctrine.md"
    text = read_doctrine(compiled_path=compiled_path)
    assert "routing analyst" in text.lower()  # from routing-doctrine.md §-lead
    assert "surface model" in text.lower()  # from pane-surface-model.md's title
    assert "pane charter" in text.lower()  # from pane-charter.md's own title


# --------------------- Sprint 3 M-I wave 4: `compile_doctrine` on `fsops`


def test_compile_doctrine_crash_after_temp_write_leaves_old_bytes_no_orphan_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`compile_doctrine` now writes the compiled artifact through
    `fsops.atomic_write`. A failing `os.replace`, scoped to the compiled
    path only, must leave the OLD compiled bytes untouched and no orphan
    temp file behind -- same fault-matrix item (a) as `test_fsops.py`'s
    crash tests, proven here against the real call site. Mutation this
    catches: reverting to the bare `compiled_path.write_text(...)` this
    replaced -- that call has no temp file at all, so a crash mid-write
    would leave the compiled cache truncated instead of untouched."""
    paths = _sources(tmp_path)
    compiled_path = paths["compiled_path"]
    first = compile_doctrine(**paths)
    old_bytes = first.read_bytes()

    # Force a recompile: advance a source's mtime past the compiled file's.
    time.sleep(0.01)
    os.utime(paths["routing_path"], None)

    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == compiled_path:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        compile_doctrine(**paths)

    assert compiled_path.read_bytes() == old_bytes
    assert list(compiled_path.parent.glob(".pane-doctrine.md.*.tmp")) == []


def test_compile_doctrine_symlink_at_compiled_path_is_refused_and_untouched(
    tmp_path: Path,
) -> None:
    """D6 (Sprint 3 wave 4): the compiled doctrine cache is regenerable
    content -- `atomic_write`'s plain defaults, symlinks refused (not
    followed). Mutation this catches: passing `follow_symlinks=True` in
    `compile_doctrine` -- the write would then silently retarget the
    REAL file's inode and this test's `real_target.read_text()`
    assertion would see the new content instead of the old."""
    paths = _sources(tmp_path)
    real_target = tmp_path / "real-compiled.md"
    real_target.write_text("STALE COMPILED\n", encoding="utf-8")
    link_path = paths["compiled_path"]
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(real_target)

    # force `needs_compile` True: the symlinked compiled path's mtime
    # (== real_target's, just written) must read OLDER than the sources'.
    time.sleep(0.01)
    os.utime(paths["routing_path"], None)

    with pytest.raises(fsops.SymlinkRefused):
        compile_doctrine(**paths)

    assert link_path.is_symlink()
    assert link_path.resolve() == real_target
    assert real_target.read_text(encoding="utf-8") == "STALE COMPILED\n"


def test_compile_doctrine_preserves_mode_under_restrictive_umask(
    tmp_path: Path,
) -> None:
    """`preserve_mode=True` (the default): a pre-existing compiled file's
    permission bits survive a recompile bit-for-bit regardless of the
    process umask. Mutation this catches: passing an explicit `mode=` or
    `preserve_mode=False` in `compile_doctrine` -- the rewritten file
    would then land at the umask-masked default (0o600 under this
    test's `os.umask(0o077)`) instead of the original 0o640.

    Fold r1, MINOR-1: "mode unchanged" is also what you observe when the
    recompile never happens at all -- `needs_compile` deciding False and
    skipping the write entirely would leave the ORIGINAL 0o640 file
    untouched, passing this test for the wrong reason. The mtime check
    below is the positive control that the second write actually landed,
    checked BEFORE the mode assertion is allowed to mean anything."""
    paths = _sources(tmp_path)
    first = compile_doctrine(**paths)
    first.chmod(0o640)
    pre_recompile_mtime_ns = first.stat().st_mtime_ns

    time.sleep(0.01)
    os.utime(paths["routing_path"], None)  # force a real recompile

    old_umask = os.umask(0o077)
    try:
        compile_doctrine(**paths)
    finally:
        os.umask(old_umask)

    # positive control (fold r1, MINOR-1): the recompile actually wrote --
    # a skipped recompile would leave the ORIGINAL file, same mtime.
    assert first.stat().st_mtime_ns > pre_recompile_mtime_ns
    assert stat.S_IMODE(first.stat().st_mode) == 0o640
