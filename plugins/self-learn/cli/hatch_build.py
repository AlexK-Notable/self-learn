"""Build hook: the CLI's package data (Windows port, 8K).

A wheel has no checkout around it, so it carries the skill's references
(doctrine, rubric, methods, the card-sections registry, the lesson-writing
passage) under ``self_learn/_data/references``. They are found in one of two
places, and included from there (no copy is kept in the repository):

- built from the checkout: ``../skills/self-learn/references`` beside the
  project;
- built from an sdist: the copy the sdist target staged inside the package at
  ``src/self_learn/_data/references``, which the wheel's ``packages`` setting
  picks up by itself.

Neither place present is a build error. An editable install gets nothing: it
reads the checkout itself.
"""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PACKAGE = "self_learn"

#: (source relative to the project, folder inside the wheel's package).
MAPPINGS = (
    ("../skills/self-learn/references", "_data/references"),
)


class PackageDataHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        root = Path(self.root)
        for source, inside in MAPPINGS:
            found = root / source
            staged = root / "src" / PACKAGE / inside
            if found.is_dir():
                build_data["force_include"][str(found)] = f"{PACKAGE}/{inside}"
            elif not staged.is_dir():
                raise FileNotFoundError(
                    f"package data {PACKAGE}/{inside}: neither {found} nor {staged} exists"
                )
