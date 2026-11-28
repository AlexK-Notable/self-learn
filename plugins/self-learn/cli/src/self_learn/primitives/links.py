"""Operations on the installation entry itself. Callers own the installation lock."""
from __future__ import annotations

import os
from pathlib import Path


class FileLinkPrivilegeError(OSError):
    """Windows denied permission to create a file symlink (winerror 1314)."""


def _backend():
    if os.name == "nt":
        from . import _links_windows
        return _links_windows
    from . import _links_posix
    return _links_posix


def create(link: Path, target: Path, *, directory: bool) -> None:
    """Create a new entry, refusing collisions. A Windows junction target must be absolute."""
    _backend().create(link, target, directory=directory)


def replace_staged(staged: Path, link: Path) -> None:
    """Publish a staged link to an absent name or a previously checked managed link."""
    _backend().replace_staged(staged, link)


def is_managed(link: Path) -> bool:
    """Whether the entry has a supported installation link type, even when dangling."""
    return _backend().is_managed(link)


def is_any_link(path: Path) -> bool:
    """Recognize redirects at this entry, including ones we cannot manage."""
    return _backend().is_any_link(path)


def read_target(link: Path) -> str:
    """Read the stored target path without resolving it or requiring it to exist."""
    return _backend().read_target(link)


def resolve_target(link: Path) -> Path:
    """Follow the installed entry for a comparison or diagnostic on either platform."""
    return link.resolve()


def remove(link: Path) -> None:
    """Remove a previously checked managed entry without following its target."""
    _backend().remove(link)
