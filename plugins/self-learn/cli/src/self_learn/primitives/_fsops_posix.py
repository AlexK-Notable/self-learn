"""POSIX implementation of the file publishing and private-file interface."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal

from . import fsops


def _resolve_target(path: Path, *, follow_symlinks: bool) -> Path:
    """*path* itself, unless it is a symlink: refused
    (:class:`SymlinkRefused`) when ``follow_symlinks`` is False (the
    default), or resolved to the link's real target when True -- the
    write then lands on that real file, in ITS directory, and the link
    itself is never opened for writing."""
    if path.is_symlink():
        if not follow_symlinks:
            raise fsops.SymlinkRefused(path)
        return path.resolve()
    return path


def _write_and_replace(
    target: Path,
    data: bytes | str,
    *,
    mode: int | None,
    preserve_mode: bool,
    fsync: bool,
    encoding: str,
) -> None:
    payload = data if isinstance(data, bytes) else data.encode(encoding)
    resolved_mode = mode
    if resolved_mode is None and preserve_mode:
        try:
            resolved_mode = target.stat().st_mode & 0o777
        except FileNotFoundError:
            resolved_mode = None
    tmp = fsops._temp_path(target)
    # Fold r3, nit 2: tracks whether THIS call actually created `tmp` --
    # set True the instant either branch's create call succeeds, checked
    # by the exception handler below before unlinking. `os.open`'s
    # `O_EXCL` (explicit-mode branch) can fail with `FileExistsError`
    # naming a FOREIGN file this call did not create (a collision --
    # unreachable in practice, see the branch's own comment below); such
    # a call must never unlink a file it didn't make.
    tmp_created = False
    try:
        if mode is not None:
            # Fold r1, Finding 6: an explicit `mode` (`private_write`'s
            # fixed 0o600, or a caller's own `mode=0o755`) is created on
            # the temp file DIRECTLY, via `os.open`'s own mode argument
            # -- no window where the temp exists at the process umask
            # default before a later `os.chmod` narrows it. This branch
            # is NOT used for a `preserve_mode`-derived `resolved_mode`:
            # that value can carry bits (e.g. group-write) the umask
            # would silently strip at `os.open`-time, which the
            # `os.chmod` below (run after creation, bypassing umask)
            # does not -- so the general preserve_mode path keeps the
            # create-then-chmod shape. Fold r2 (r2-3, nit): `O_EXCL`
            # makes a colliding temp name (same pid AND same `secrets.
            # token_hex(4)` -- unreachable in practice) fail loudly with
            # `FileExistsError` instead of the `else` branch's plain
            # `open(tmp, "wb")`, which would silently TRUNCATE a
            # colliding temp. Neither is wrong (both are unreachable),
            # but `O_EXCL` is the deliberate, safer choice here -- not a
            # reason to drop it or add it to the other branch.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            tmp_created = True
            with os.fdopen(fd, "wb") as fh:
                # Fold r3, nit 1: `os.fchmod` moved INSIDE the `with` --
                # fold r2's version ran it on the bare `fd` before
                # `os.fdopen` took ownership, so a raising `fchmod`
                # (unlikely, but possible) would leak the fd with no
                # `with`/`finally` to close it. `fh.fileno()` is the
                # SAME fd; wrapping it first means the `with` block's
                # own cleanup closes it on ANY exception, `fchmod`
                # included. Restores exact bits regardless of umask
                # (fold r2, r2-2): umask can only REMOVE bits at
                # `os.open`-time, never add, so the instant before this
                # `fchmod` runs is never WIDER than `mode`, only
                # narrower or equal -- Finding 6's no-window property
                # stays intact.
                os.fchmod(fh.fileno(), mode)
                fh.write(payload)
                if fsync:
                    fh.flush()
                    os.fsync(fh.fileno())
        else:
            with open(tmp, "wb") as fh:
                tmp_created = True
                fh.write(payload)
                if fsync:
                    fh.flush()
                    os.fsync(fh.fileno())
            if resolved_mode is not None:
                os.chmod(tmp, resolved_mode)
        os.replace(tmp, target)  # same filesystem -- atomic
    except OSError as exc:
        if tmp_created:
            tmp.unlink(missing_ok=True)
        # Fold r1, Finding 9: an `OSError` raised anywhere in the block
        # above (a permission error opening the temp file, a missing
        # parent directory) carries `.filename == str(tmp)` -- and by
        # the time the caller's `except OSError` handler reads `{exc}`,
        # `tmp` has usually already been unlinked two lines up (the
        # `FileExistsError`-collision case above is the one exception --
        # `tmp_created` is False there, so nothing is unlinked, but
        # `tmp` was never THIS call's file to begin with), so the
        # message names a path that never existed as far as any caller
        # could observe and cannot `ls`. Retarget `.filename` to `target`
        # (mutating the SAME exception object -- same type, same
        # errno/strerror, same traceback, `raise` bare re-raises it) so
        # the message names the file the caller actually asked to
        # write. Deliberately narrow: only when `.filename` IS the temp
        # path -- a manually-raised `OSError("msg")` in a test has
        # `.filename is None` and is left untouched (`str(exc)` stays
        # exactly "msg"). Fold r2 (r2-4): for an `os.replace(tmp,
        # target)` failure specifically, `.filename` (src) IS the temp
        # path and gets retargeted here same as any other case, while
        # `.filename2` (dst) already read `target` before this handler
        # ever ran -- so BOTH end up naming `target`, and `str(exc)`
        # collapses to ``'<target>' -> '<target>'`` (measured, an
        # `IsADirectoryError` from `os.replace`: `"[Errno 21] Is a
        # directory: '<target>' -> '<target>'"`). Still net-correct (the
        # vanished temp is gone from the message, which is what this
        # finding asked for) -- just a doubled path a reader should not
        # mistake for two different files.
        if exc.filename == str(tmp):
            exc.filename = str(target)
        raise
    except BaseException:
        if tmp_created:
            tmp.unlink(missing_ok=True)
        raise
    if fsync:
        dir_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)  # the rename itself, durable too
        finally:
            os.close(dir_fd)


def atomic_write(
    path: Path | str,
    data: bytes | str,
    *,
    mode: int | None = None,
    preserve_mode: bool = True,
    fsync: bool = True,
    follow_symlinks: bool = False,
    encoding: str = "utf-8",
) -> None:
    """Write *data* to *path* atomically (temp file + ``os.replace``)
    and, when ``fsync`` (the default), durably. See the module
    docstring for the full symlink/mode/D6 policy. The caller is
    responsible for the parent directory existing -- this function
    never calls ``mkdir`` (every migrated call site already did its own
    ``parent.mkdir(parents=True, exist_ok=True)``, and a silent mkdir
    here would be one more divergence from what those call sites
    already prove correct). *path* accepts ``str`` too (fold r1, Finding
    5) -- both bodies already do ``Path(path)`` first, and sibling APIs
    in this tree (``compiled.write_entry``, ``config.dump_editable``)
    already type their path parameter ``Path | str``."""
    target = _resolve_target(Path(path), follow_symlinks=follow_symlinks)
    _write_and_replace(
        target,
        data,
        mode=mode,
        preserve_mode=preserve_mode,
        fsync=fsync,
        encoding=encoding,
    )


def private_write(path: Path | str, data: bytes | str) -> None:
    """``atomic_write`` fixed to the secret-file shape: mode ``0o600``
    always (never preserved from an existing file -- a secret's mode
    must never accidentally widen because the file already existed
    world-unreadable-but-not-0600), symlinks always refused, always
    fsync'd."""
    target = _resolve_target(Path(path), follow_symlinks=False)
    _write_and_replace(
        target,
        data,
        mode=0o600,
        preserve_mode=False,
        fsync=True,
        encoding="utf-8",
    )


def replace_staged(src: Path | str, dst: Path | str, *, method: Literal["os", "path"] = "os") -> None:
    if method == "path":
        receiver = Path(src) if isinstance(src, str) else src
        receiver.replace(dst)
    else:
        os.replace(src, dst)


def flush_file(fd: int) -> None:
    os.fsync(fd)


def sync_parent(path: Path) -> None:
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_file_and_parent(path: Path) -> None:
    for target, flags in ((Path(path), os.O_RDONLY), (Path(path).parent, os.O_RDONLY)):
        fd = os.open(target, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def ensure_private_parent(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def open_private_new(path: Path) -> int:
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)


def private_temp(parent: Path, *, prefix: str, suffix: str) -> tuple[int, str]:
    return tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=parent)


@contextmanager
def reopenable_text(text: str, *, prefix: str, suffix: str) -> Iterator[Path]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=prefix, suffix=suffix) as fh:
        fh.write(text)
        fh.flush()
        yield Path(fh.name)


def open_for_mode(path: Path, kind: Literal["x", "xb", "a"], *,
                  mode: int | None = None, encoding: str | None = None) -> IO[Any]:
    if kind == "a":
        if encoding is None:
            return open(path, "a")
        return open(path, "a", encoding=encoding)
    if encoding is None:
        return path.open(kind)
    return path.open(kind, encoding=encoding)


def finish_mode(path: Path, mode: int, *, method: Literal["path", "os"] = "path") -> None:
    if method == "os":
        os.chmod(path, mode)
    else:
        path.chmod(mode)


def open_regular(path: Path | str, *, policy: Literal["premise", "provenance"]) -> int:
    if policy == "premise":
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC | os.O_NOFOLLOW
    else:
        flags = os.O_RDONLY | os.O_NONBLOCK
    return os.open(path, flags)


class _Directory:
    def __init__(self, path: Path) -> None:
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def __enter__(self) -> _Directory:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        os.close(self.fd)

    def entries(self) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        return os.scandir(self.fd)

    def unlink(self, name: str) -> None:
        os.unlink(name, dir_fd=self.fd)


def safe_directory(path: Path) -> AbstractContextManager[fsops.Directory]:
    return _Directory(path)
