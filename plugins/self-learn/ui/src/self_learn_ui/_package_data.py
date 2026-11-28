"""Where the UI's non-Python files are (Windows port, 8K).

In a self-learn checkout the pages and static files sit beside ``src/`` in
``plugins/self-learn/ui/``, and the pane's doctrine sources in
``plugins/self-learn/skills/self-learn/references``. A wheel has no checkout
around it, so it carries copies as package data under
``self_learn_ui/_data/{templates,static,references}`` (put there by
``hatch_build.py``).

The layout is decided from this module's own location first, by the same
rule as the CLI's (:func:`self_learn._package_data.detect_checkout`, reused,
since it is a pure function of a path): the checkout folders are used only
when the package provably sits at ``plugins/self-learn/ui/src/self_learn_ui/``
of a checkout. The decision itself is this package's own, from its own file;
nothing here depends on where the CLI package is installed.
"""

from __future__ import annotations

import functools
from pathlib import Path

from self_learn._package_data import detect_checkout

#: The UI's uv project name, as its ``pyproject.toml`` declares it.
PROJECT_NAME = "self-learn-ui"


@functools.cache
def checkout_project() -> Path | None:
    """This package's checkout project folder (``plugins/self-learn/ui``),
    or ``None`` for an installed copy. Decided once per process."""
    return detect_checkout(Path(__file__).resolve(), PROJECT_NAME)


def packaged(*parts: str) -> Path:
    """A path inside the wheel's package data, ``self_learn_ui/_data/<parts>``.
    Only an unpacked install is supported: an import from a zip archive is
    refused here, loudly, rather than failing later on a missing file."""
    from importlib import resources

    root = resources.files("self_learn_ui")
    if not isinstance(root, Path):
        raise RuntimeError(
            f"self-learn's UI needs an unpacked install; self_learn_ui was imported from {root!r}"
        )
    return root.joinpath("_data", *parts)
