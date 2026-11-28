"""Native Windows spellings for stored components, folders and Git operands."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

if sys.platform != "win32":
    raise NotImplementedError("native Windows names require Windows")


def path_fingerprint(text: str, *, length: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


# Mirrors the DOS aliases on supported NTFS, including their extension forms.
_DEVICE = re.compile(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³]", re.ASCII | re.I)
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]')


def _check_component(name: str) -> None:
    stem = name.partition(".")[0].rstrip(" ")
    if (not name or name.endswith((" ", ".")) or _FORBIDDEN.search(name)
            or _DEVICE.fullmatch(stem) or len(name.encode("utf-16-le")) > 2 * 255):
        raise ValueError(f"invalid Windows component: {name!r}")


def _ordinary_path(raw: Path | str) -> Path:
    spelling = os.fspath(raw).replace("/", "\\")
    path = Path(spelling)
    if (not spelling or spelling.startswith(("\\\\?\\", "\\\\.\\"))
            or (path.anchor and not path.is_absolute())):
        raise ValueError(f"ambiguous or device path: {raw!r}")
    if spelling.startswith("\\\\"):
        # A UNC drive contains the server and share. Validate those too.
        if not path.drive.startswith("\\\\"):
            raise ValueError(f"incomplete UNC path: {raw!r}")
        for part in path.drive[2:].split("\\"):
            _check_component(part)
    elif path.drive and not re.fullmatch("[a-zA-Z]:", path.drive):
        raise ValueError(f"invalid drive: {raw!r}")
    for part in path.parts[1:] if path.anchor else path.parts:
        if part != "..":
            _check_component(part)
    return path


def _canonical(path: Path | str, *, strict: bool = False) -> str:
    return os.path.normcase(str(_ordinary_path(path).resolve(strict=strict)))


def project_slug(path: Path | str) -> str:
    key = _canonical(path, strict=True)
    hint = re.sub("[^a-z0-9]+", "-", Path(key).name.lower()).strip("-")[:31] or "project"
    return f"w1-{hint}-{path_fingerprint(key, length=32)}"


def project_digest(path: Path | str) -> str:
    return path_fingerprint(_canonical(path, strict=True), length=8)


def registration_key(resolved: Path | str) -> str:
    return str(resolved)


def home_spelling(home: Path | str) -> str:
    return _canonical(Path(home).expanduser())


def home_digest(home: Path | str) -> str:
    return path_fingerprint(home_spelling(home), length=8)


def component_path(root: Path, name: str, *, suffix: str = "") -> Path:
    _check_component(name)
    component = name + suffix
    candidate = root / component
    absolute = candidate.absolute()
    for entry in (*reversed(absolute.parents), absolute):
        try:
            attributes = entry.lstat().st_file_attributes
        except FileNotFoundError:
            continue
        if entry == absolute and attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"reparse point in component path: {entry}")
    candidate.resolve().relative_to(root.resolve())
    return candidate


def ledger_home(env: Mapping[str, str] | None = None, *, default: str = "~/.self-learn") -> Path:
    env = os.environ if env is None else env
    return Path(env.get("SELF_LEARN_HOME") or default).expanduser()


def cache_root(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if raw := env.get("XDG_CACHE_HOME"):
        return Path(raw).expanduser() / "self-learn"
    from platformdirs import user_cache_path

    return user_cache_path("self-learn", appauthor=False, ensure_exists=False) / "self-learn"


def user_home() -> Path:
    return Path.home()


def home_cache_for(app_root: Path, expanded_home: Path) -> Path:
    return app_root / f"home-{home_digest(expanded_home)}"


def home_cache(home: Path | str | None = None) -> Path:
    return home_cache_for(cache_root(), ledger_home() if home is None else Path(home))


def runtime_root(home: Path | str | None = None, *, fallback: Callable[[], Path] | None = None) -> Path:
    if runtime := os.environ.get("XDG_RUNTIME_DIR"):
        return Path(runtime) / "self-learn"
    return fallback() if fallback is not None else home_cache(home)


def claude_root(*, use: Literal["default", "runtime", "transcripts", "reference"],
                env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("SELF_LEARN_CLAUDE_DIR")
    return Path(override).expanduser() if override else user_home() / ".claude"


def user_claude_file(default: Path) -> Path:
    if default == Path("~/.claude/CLAUDE.md"):
        return claude_root(use="default") / "CLAUDE.md"
    return default.expanduser()


def git_arg(repo: Path, path: Path | str) -> str:
    operand = _ordinary_path(path)
    root = _ordinary_path(repo).resolve(strict=True)
    if operand.drive and operand.drive.lower() != root.drive.lower():
        raise ValueError(f"Git operand on another drive: {path}")
    anchored = operand.absolute()
    # Resolve the parent to detect junction escapes. The last entry may itself
    # be a tracked link: Git names that entry, not its target.
    if anchored == root or anchored.name == "..":
        entry = anchored.resolve()
    else:
        entry = anchored.parent.resolve() / anchored.name
    return entry.relative_to(root).as_posix()


def relative_key(root: Path, path: Path, *, method: Literal["relative_to", "relpath"] = "relative_to") -> str:
    if method == "relpath":
        return Path(os.path.relpath(path, root)).as_posix()
    return path.relative_to(root).as_posix()


def pointer_token(surface: Path, target: Path) -> str:
    try:
        rel = os.path.relpath(target, surface.parent)
    except ValueError:  # different drives
        pass
    else:
        if not rel.startswith(".."):
            return Path(rel).as_posix()
    try:
        return "~/" + target.relative_to(user_home()).as_posix()
    except ValueError:
        return str(target)


def worktree_label_path(path: Path) -> str:
    return path.as_posix()


def claude_folder_hint(path: Path | str, *, style: Literal["transcript", "miner"]) -> str:
    pattern = r"[^A-Za-z0-9]" if style == "transcript" else r"[^A-Za-z0-9-]"
    return re.sub(pattern, "-", str(path))


def porcelain_paths(repo: Path, data: bytes) -> list[tuple[str, Path]]:
    """Parse porcelain v1 -z. R/C records carry destination then source."""
    if data and not data.endswith(b"\0"):
        raise ValueError("unterminated porcelain path")
    fields = iter(data.split(b"\0")[:-1])
    rows = []
    for record in fields:
        if len(record) < 4 or record[2:3] != b" ":
            raise ValueError("malformed porcelain record")
        status = record[:2].decode("ascii")
        path = record[3:].decode("utf-8")
        if "R" in status or "C" in status:
            source = next(fields, None)
            if not source:
                raise ValueError("missing porcelain rename/copy source")
            source.decode("utf-8", errors="replace")
        rows.append((status, repo / path))
    return rows
