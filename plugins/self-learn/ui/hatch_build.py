"""Build hook: the UI's package data (Windows port, 8K).

A wheel has no checkout around it, so it carries the pages, the static files
and the pane's doctrine sources under ``self_learn_ui/_data/``. Each one is
found in one of two places, and included from there (no copy is kept in the
repository):

- built from the checkout: ``templates/`` and ``static/`` beside ``src/``, and
  ``../skills/self-learn/references`` beside the project;
- built from an sdist: the same ``templates/`` and ``static/`` at the sdist's
  root, and the references the sdist target staged inside the package at
  ``src/self_learn_ui/_data/references``, which the wheel's ``packages`` setting
  picks up by itself.

Neither place present is a build error. An editable install gets nothing: it
reads the checkout itself.
"""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PACKAGE = "self_learn_ui"

#: (source relative to the project, folder inside the wheel's package).
MAPPINGS = (
    ("templates", "_data/templates"),
    ("static", "_data/static"),
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
