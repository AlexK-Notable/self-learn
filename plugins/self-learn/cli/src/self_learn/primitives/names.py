"""Platform interface for stored names, app-owned paths and path tokens."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal


def _backend():
    if os.name == "nt":
        from . import _names_windows

        return _names_windows
    from . import _names_posix

    return _names_posix


def path_fingerprint(text: str, *, length: int) -> str:
    return _backend().path_fingerprint(text, length=length)


def project_slug(path: Path | str) -> str:
    return _backend().project_slug(path)


def project_digest(path: Path | str) -> str:
    return _backend().project_digest(path)


def home_spelling(home: Path | str) -> str:
    return _backend().home_spelling(home)


def home_digest(home: Path | str) -> str:
    return _backend().home_digest(home)


def registration_key(resolved: Path | str) -> str:
    return _backend().registration_key(resolved)


def component_path(root: Path, name: str, *, suffix: str = "") -> Path:
    return _backend().component_path(root, name, suffix=suffix)


def ledger_home(env: Mapping[str, str] | None = None, *, default: str = "~/.self-learn") -> Path:
    return _backend().ledger_home(env, default=default)


def cache_root(env: Mapping[str, str] | None = None) -> Path:
    return _backend().cache_root(env)


def user_home() -> Path:
    return _backend().user_home()


def home_cache(home: Path | str | None = None) -> Path:
    return _backend().home_cache(home)


def home_cache_for(app_root: Path, expanded_home: Path) -> Path:
    return _backend().home_cache_for(app_root, expanded_home)


def runtime_root(home: Path | str | None = None, *, fallback: Callable[[], Path] | None = None) -> Path:
    return _backend().runtime_root(home, fallback=fallback)


def claude_root(*, use: Literal["default", "runtime", "transcripts", "reference"],
                env: Mapping[str, str] | None = None) -> Path:
    return _backend().claude_root(use=use, env=env)


def user_claude_file(default: Path) -> Path:
    return _backend().user_claude_file(default)


def git_arg(repo: Path, path: Path | str) -> str:
    return _backend().git_arg(repo, path)


def relative_key(root: Path, path: Path, *, method: Literal["relative_to", "relpath"] = "relative_to") -> str:
    return _backend().relative_key(root, path, method=method)


def pointer_token(surface: Path, target: Path) -> str:
    return _backend().pointer_token(surface, target)


def worktree_label_path(path: Path) -> str:
    return _backend().worktree_label_path(path)


def claude_folder_hint(path: Path | str, *, style: Literal["transcript", "miner"]) -> str:
    return _backend().claude_folder_hint(path, style=style)
