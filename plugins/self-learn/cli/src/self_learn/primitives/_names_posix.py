"""POSIX spellings used in the ledger, cache and Git arguments."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal


def path_fingerprint(text: str, *, length: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def project_slug(path: Path | str) -> str:
    resolved = str(Path(path).resolve())
    digest = path_fingerprint(resolved, length=8)
    return f"{resolved.replace('/', '-')}-{digest}"


def project_digest(path: Path | str) -> str:
    return path_fingerprint(str(Path(path).resolve()), length=8)


def home_spelling(home: Path | str) -> str:
    return str(Path(home).expanduser())


def home_digest(home: Path | str) -> str:
    return path_fingerprint(home_spelling(home), length=8)


def registration_key(resolved: Path | str) -> str:
    return str(resolved)


def component_path(root: Path, name: str, *, suffix: str = "") -> Path:
    if suffix:
        return root / f"{name}{suffix}"
    return root / name


def ledger_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("SELF_LEARN_HOME") or "~/.self-learn").expanduser()


def cache_root(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get("XDG_CACHE_HOME")
    base = Path(raw).expanduser() if raw else Path("~/.cache").expanduser()
    return base / "self-learn"


def user_home() -> Path:
    return Path.home()


def home_cache(home: Path | str | None = None) -> Path:
    app_root = cache_root()
    expanded_home = Path(home).expanduser() if home is not None else ledger_home()
    return home_cache_for(app_root, expanded_home)


def home_cache_for(app_root: Path, expanded_home: Path) -> Path:
    digest = path_fingerprint(str(expanded_home), length=8)
    return app_root / f"home-{digest}"


def runtime_root(home: Path | str | None = None, *, fallback: Callable[[], Path] | None = None) -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "self-learn"
    return fallback() if fallback is not None else home_cache(home)


def claude_root(*, use: Literal["default", "runtime", "transcripts", "reference"],
                env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if use == "reference":
        return Path(env.get("SELF_LEARN_CLAUDE_DIR", str(Path.home() / ".claude")))
    if use != "default":
        raw = env.get("SELF_LEARN_CLAUDE_DIR")
        if use == "transcripts":
            raw = raw or env.get("CLAUDE_CONFIG_DIR")
        if raw:
            return Path(raw)
    return Path("~/.claude").expanduser()


def user_claude_file(default: Path) -> Path:
    return default.expanduser()


def git_arg(repo: Path, path: Path | str) -> str:
    return str(path)


def relative_key(root: Path, path: Path, *, method: Literal["relative_to", "relpath"] = "relative_to") -> str:
    if method == "relpath":
        return os.path.relpath(path, root)
    return str(path.relative_to(root))


def pointer_token(surface: Path, target: Path) -> str:
    rel = os.path.relpath(target, surface.parent)
    if not rel.startswith(".."):
        return Path(rel).as_posix()
    try:
        return "~/" + Path(target).relative_to(Path.home()).as_posix()
    except ValueError:  # target is not under $HOME
        return str(target)


def worktree_label_path(path: Path) -> str:
    return str(path)


def claude_folder_hint(path: Path | str, *, style: Literal["transcript", "miner"]) -> str:
    pattern = r"[^A-Za-z0-9]" if style == "transcript" else r"[^A-Za-z0-9-]"
    return re.sub(pattern, "-", str(path))
