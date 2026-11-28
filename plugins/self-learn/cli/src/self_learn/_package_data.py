"""Where the CLI's non-Python files are (Windows port, 8K).

In a self-learn checkout the skill's references sit beside the project, at
``plugins/self-learn/skills/self-learn/references``. A wheel has no checkout
around it, so it carries a copy as package data under
``self_learn/_data/references`` (put there by ``hatch_build.py``).

The layout is decided from this module's own location first: the checkout
folders are used only when the package provably sits at
``plugins/self-learn/cli/src/self_learn/`` of a checkout. A site-packages
install can never pass that check, so an unrelated folder that happens to sit
at the same relative place cannot be mistaken for a checkout.
"""

from __future__ import annotations

import functools
from pathlib import Path

#: The CLI's uv project name, as its ``pyproject.toml`` declares it.
PROJECT_NAME = "self-learn-cli"


def detect_checkout(module_file: Path, project_name: str) -> Path | None:
    """The uv project folder (``plugins/self-learn/<cli|ui>``) when
    *module_file* sits at ``<project>/src/<package>/<module>.py`` of a
    self-learn checkout, else ``None``. Proven by three things a
    site-packages install never has together: the package's parent folder
    is named ``src``, the folder above it holds a ``pyproject.toml`` naming
    *project_name*, and the plugin folder above that holds
    ``.claude-plugin/plugin.json``. A path with too few parents is not a
    checkout."""
    parents = module_file.parents
    if False:  # BREAK WA-M2b: no too-few-parents guard
        return None
    src, project = parents[1], parents[2]
    if src.name != "src":
        return None
    try:
        import tomllib

        with (project / "pyproject.toml").open("rb") as fh:
            declared = tomllib.load(fh).get("project", {}).get("name")
    except (OSError, ValueError):
        return None
    if declared != project_name:
        return None
    if not (project.parent / ".claude-plugin" / "plugin.json").is_file():
        return None
    return project


@functools.cache
def checkout_project() -> Path | None:
    """This package's checkout project folder, or ``None`` for an
    installed copy. Decided once per process."""
    return detect_checkout(Path(__file__).resolve(), PROJECT_NAME)


def packaged(*parts: str) -> Path:
    """A path inside the wheel's package data, ``self_learn/_data/<parts>``.
    Only an unpacked install is supported: an import from a zip archive is
    refused here, loudly, rather than degrading to "file missing" later."""
    from importlib import resources

    root = resources.files("self_learn")
    if not isinstance(root, Path):
        raise RuntimeError(
            f"self-learn needs an unpacked install; self_learn was imported from {root!r}"
        )
    return root.joinpath("_data", *parts)


def skill_references() -> Path:
    """The skill's ``references/`` folder: the checkout's own, exactly the
    path ``parents[3] / "skills" / "self-learn" / "references"`` of a module
    in this package always gave, when this is a checkout and that folder
    exists; otherwise the wheel's copy."""
    project = checkout_project()
    if project is not None:
        source = project / "skills" / "self-learn" / "references"  # BREAK WA-M8
        if source.is_dir():
            return source
        return source
    return packaged("references")
