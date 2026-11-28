"""File publishing on local NTFS. Ordinary and private files inherit their folder's ACL."""

from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from time import monotonic, sleep
from typing import IO, Any, Literal

from . import fsops

if sys.platform != "win32":
    raise ImportError("native file operations require Windows")

import msvcrt
import ntsecuritycon
import pywintypes
import win32api
import win32con
import win32file
import win32security as security


_SHARE_ALL = win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE
_INHERIT = security.OBJECT_INHERIT_ACE | security.CONTAINER_INHERIT_ACE


def _attributes(path: Path) -> int:
    # GetFileAttributes also sees reparse tags that Python lstat may traverse.
    try:
        return win32file.GetFileAttributes(str(path))
    except pywintypes.error as exc:
        if exc.winerror in (2, 3):
            return 0
        raise OSError(0, exc.strerror, str(path), exc.winerror) from exc


def _refuse_links(path: Path) -> None:
    path = path.absolute()
    for component in (*reversed(path.parents), path):
        if _attributes(component) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise fsops.SymlinkRefused(component)


def replace_staged(src: Path | str, dst: Path | str, *, method: Literal["os", "path"] = "os") -> None:
    source, target = Path(src), Path(dst)
    deadline = monotonic() + 0.250
    while True:
        try:
            if method == "path":
                source.replace(dst)
            else:
                os.replace(src, dst)
            return
        except OSError as exc:
            if exc.winerror not in (5, 32):
                raise
            # MoveFileEx usually reports missing entries/volumes distinctly.
            # If access was denied, retry only while the entries permit it.
            try:
                retry = (_attributes(source) != 0 and target.parent.is_dir()
                         and not _attributes(target) & stat.FILE_ATTRIBUTE_READONLY)
            except OSError:
                retry = False
            remaining = deadline - monotonic()
            if not retry or remaining <= 0:
                raise
            sleep(min(0.010, remaining))
            if monotonic() >= deadline:
                raise


def atomic_write(path: Path | str, data: bytes | str, *, mode: int | None = None,
                 preserve_mode: bool = True, fsync: bool = True, follow_symlinks: bool = False,
                 encoding: str = "utf-8") -> None:
    target = Path(path)
    _refuse_links(target.parent)
    if _attributes(target) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        if not follow_symlinks:
            raise fsops.SymlinkRefused(target)
        target = target.resolve()
    payload = data if isinstance(data, bytes) else data.encode(encoding)
    try:
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    except OSError as exc:
        if exc.filename is not None:
            exc.filename = str(target)
        raise
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            if fsync:
                stream.flush()
                flush_file(stream.fileno())
        replace_staged(name, target)
    except BaseException as exc:
        Path(name).unlink(missing_ok=True)
        if isinstance(exc, OSError) and exc.filename == name:
            exc.filename = str(target)
        raise


def private_write(path: Path | str, data: bytes | str) -> None:
    # Legacy ledger/cache destinations stay at the caller's chosen path.
    atomic_write(path, data)


def flush_file(fd: int) -> None:
    os.fsync(fd)


def sync_parent(path: Path) -> None:
    """Windows provides no corresponding directory fsync."""


def sync_file_and_parent(path: Path) -> None:
    try:
        with closing(win32file.CreateFile(str(path), win32con.GENERIC_WRITE, _SHARE_ALL, None,
                                  win32con.OPEN_EXISTING, 0, None)) as handle:
            win32file.FlushFileBuffers(handle)
    except pywintypes.error as exc:
        raise OSError(0, exc.strerror, str(path), exc.winerror) from exc


def _principals():
    with closing(security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)) as token:
        user = security.GetTokenInformation(token, security.TokenUser)[0]
    return (user, security.CreateWellKnownSid(security.WinLocalSystemSid),
            security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid))


def _verify_private(path: Path, principals) -> None:
    _refuse_links(path)
    if not path.is_dir():
        raise NotADirectoryError(errno.ENOTDIR, "private parent must be a directory", str(path))
    sd = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
                                       security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
    acl = sd.GetSecurityDescriptorDacl()
    protected = sd.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED
    if sd.GetSecurityDescriptorOwner() == principals[0] and protected and acl is not None:
        expected = {str(sid) for sid in principals}
        actual = set()
        for index in range(acl.GetAceCount()):
            ace = acl.GetAce(index)
            if ace[:2] != ((security.ACCESS_ALLOWED_ACE_TYPE, _INHERIT), ntsecuritycon.FILE_ALL_ACCESS):
                break
            actual.add(str(ace[2]))
        else:
            if actual == expected and acl.GetAceCount() == len(expected):
                return
    raise PermissionError(errno.EACCES, "unsafe owner or permissions on private directory", str(path))


def ensure_private_parent(path: Path) -> None:
    _refuse_links(path)
    try:
        principals = _principals()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            acl = security.ACL()
            for sid in principals:
                acl.AddAccessAllowedAceEx(security.ACL_REVISION, _INHERIT, ntsecuritycon.FILE_ALL_ACCESS, sid)
            attributes = security.SECURITY_ATTRIBUTES()
            sd = attributes.SECURITY_DESCRIPTOR
            sd.SetSecurityDescriptorOwner(principals[0], False)
            sd.SetSecurityDescriptorDacl(True, acl, False)
            control = security.SE_DACL_PROTECTED | security.SE_DACL_AUTO_INHERITED
            sd.SetSecurityDescriptorControl(control, control)
            # Supply the DACL at creation, before another process can open a child.
            try:
                win32file.CreateDirectory(str(path), attributes)
            except pywintypes.error as exc:
                if exc.winerror != 183:  # ERROR_ALREADY_EXISTS: verify the winner.
                    raise
        _verify_private(path, principals)
    except pywintypes.error as exc:
        raise OSError(0, exc.strerror, str(path), exc.winerror) from exc


def open_private_new(path: Path) -> int:
    ensure_private_parent(path.parent)
    return os.open(path, os.O_WRONLY | os.O_BINARY | os.O_CREAT | os.O_EXCL)


def private_temp(parent: Path, *, prefix: str, suffix: str) -> tuple[int, str]:
    ensure_private_parent(parent)
    _check_name(prefix + "_" + suffix)
    return tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=parent)


@contextmanager
def reopenable_text(text: str, *, prefix: str, suffix: str) -> Iterator[Path]:
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    path = Path(name)
    identity = os.fstat(fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(text.encode("utf-8"))
        yield path
    finally:
        try:
            if os.path.samestat(identity, path.lstat()):
                path.unlink()
        except FileNotFoundError:
            pass


def open_for_mode(path: Path, kind: Literal["x", "xb", "a"], *,
                  mode: int | None = None, encoding: str | None = None) -> IO[Any]:
    return path.open(kind, encoding=encoding, newline=None if kind == "xb" else "\n")


def finish_mode(path: Path, mode: int, *, method: Literal["path", "os"] = "path") -> None:
    path.chmod(stat.S_IWRITE if mode & stat.S_IWUSR else stat.S_IREAD)


def open_regular(path: Path | str, *, policy: Literal["premise", "provenance"]) -> int:
    if policy == "provenance":
        return os.open(path, os.O_RDONLY | os.O_BINARY)
    # Open the entry itself. Inspect the handle we actually return, so a swap
    # after inspection cannot redirect the reader to a different file.
    try:
        handle = win32file.CreateFile(str(path), win32con.GENERIC_READ, _SHARE_ALL, None,
                                      win32con.OPEN_EXISTING, win32con.FILE_FLAG_OPEN_REPARSE_POINT |
                                      win32con.FILE_FLAG_BACKUP_SEMANTICS, None)
        with closing(handle):
            attrs = win32file.GetFileInformationByHandle(handle)[0]
            if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError(errno.ELOOP, "refusing reparse point", str(path))
            if attrs & stat.FILE_ATTRIBUTE_DIRECTORY:
                raise IsADirectoryError(errno.EISDIR, "expected a file", str(path))
            fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
            handle.Detach()  # the CRT descriptor now owns the handle
            return fd
    except pywintypes.error as exc:
        raise OSError(0, exc.strerror, str(path), exc.winerror) from exc


def _check_name(name: str) -> None:
    if not name or Path(name).name != name or name in (".", "..") or ":" in name:
        raise ValueError("expected one directory entry name")


class _Directory:
    def __init__(self, path: Path):
        self.path = path.absolute()
        _refuse_links(self.path)
        if not self.path.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, "expected a directory", str(path))

    def entries(self):
        _refuse_links(self.path)
        return os.scandir(self.path)

    def unlink(self, name: str) -> None:
        _check_name(name)
        _refuse_links(self.path)
        (self.path / name).unlink()


def safe_directory(path: Path):
    directory = _Directory(path)
    return nullcontext(directory)
