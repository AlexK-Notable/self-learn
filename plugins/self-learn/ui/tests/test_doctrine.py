"""The doctrine compiler (10 §1's "Doctrine compile" row; 10 §3 task U5
bullet 4): recompile-on-mtime, byte-stable between no-op recompiles, and
that :func:`plugin_references_dir` resolves to the real tracked skill
references dir (proving the real ``routing-doctrine.md`` +
``pane-charter.md`` this branch ships are found where the pin says).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

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
