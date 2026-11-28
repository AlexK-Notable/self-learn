"""Original skill installation operations, called under the caller's lock."""
from __future__ import annotations

import os
from pathlib import Path

from . import fsops


def create(link: Path, target: Path, *, directory: bool) -> None:
    os.symlink(str(target), link)


def replace_staged(staged: Path, link: Path) -> None:
    fsops.replace_staged(staged, link)


def is_managed(link: Path) -> bool:
    return link.is_symlink()


def is_any_link(path: Path) -> bool:
    return path.is_symlink()


def read_target(link: Path) -> str:
    return os.readlink(link)


def remove(link: Path) -> None:
    link.unlink()
