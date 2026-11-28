"""File publishing on local NTFS. Ordinary and private files inherit their folder's ACL."""

from __future__ import annotations

import errno
import os
import secrets
import stat
import sys
import tempfile
from collections.abc import Callable, Iterator
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


_OPEN_ENTRY = win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS


@contextmanager
def _winerrors(path: Path | str) -> Iterator[None]:
    try:
        yield
    except pywintypes.error as exc:
        raise OSError(0, exc.strerror, str(path), exc.winerror) from exc


def _attributes(path: Path) -> int:
    with _winerrors(path):
        try:
            return win32api.GetFileAttributes(str(path))
        except pywintypes.error as exc:
            if exc.winerror in (2, 3):
                return 0
            raise


def _link_tag(tag: int) -> bool:
    # IsReparseTagNameSurrogate, plus Windows application execution aliases.
    return bool(tag & 0x20000000) or tag == 0x8000001B


def _is_link(path: Path) -> bool:
    if not _attributes(path) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    with _winerrors(path):
        with closing(win32file.CreateFile(str(path), 0, _SHARE_ALL, None,
                                          win32con.OPEN_EXISTING, _OPEN_ENTRY, None)) as handle:
            info = win32file.GetFileInformationByHandleEx(handle, win32file.FileAttributeTagInfo)
            return _link_tag(info["ReparseTag"])


def _refuse_link(path: Path) -> None:
    if _is_link(path):
        raise fsops.SymlinkRefused(path)


def _refuse_links(path: Path) -> None:
    _refuse_link(path.parent)
    _refuse_link(path)


def _take_fd(handle, flags: int) -> int:
    fd = msvcrt.open_osfhandle(int(handle), flags | os.O_BINARY)
    handle.Detach()  # close(fd) now owns the native handle
    return fd


def _exclusive_fd(path: Path | str, *, delete_access: bool = False) -> int:
    access = win32con.GENERIC_WRITE
    if delete_access:
        access |= win32con.DELETE
    with _winerrors(path):
        with closing(win32file.CreateFile(str(path), access, _SHARE_ALL, None, win32con.CREATE_NEW,
                                          win32file.FILE_FLAG_OPEN_REPARSE_POINT, None)) as handle:
            return _take_fd(handle, os.O_WRONLY)


def _new_temp(candidate: Callable[[], Path], *, delete_access: bool = False) -> tuple[int, str]:
    for _ in range(100):
        path = candidate()
        try:
            return _exclusive_fd(path, delete_access=delete_access), str(path)
        except FileExistsError:
            continue
    raise FileExistsError(errno.EEXIST, "could not allocate a unique temporary name", str(path))


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
                source_info = source.lstat()
                parent_info = target.parent.stat()
                retry = (stat.S_ISDIR(parent_info.st_mode) and source_info.st_dev == parent_info.st_dev
                         and not _attributes(target) & stat.FILE_ATTRIBUTE_READONLY)
            except OSError:
                retry = False
            remaining = deadline - monotonic()
            if not retry or remaining <= 0.010:
                raise
            sleep(0.010)
            if monotonic() >= deadline:
                raise


def atomic_write(path: Path | str, data: bytes | str, *, mode: int | None = None,
                 preserve_mode: bool = True, fsync: bool = True, follow_symlinks: bool = False,
                 encoding: str = "utf-8") -> None:
    target = Path(path)
    if follow_symlinks:
        if _is_link(target):
            target = target.resolve()
    else:
        _refuse_links(target)
    payload = data if isinstance(data, bytes) else data.encode(encoding)
    try:
        fd, name = _new_temp(lambda: fsops._temp_path(target))
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
        try:
            Path(name).unlink(missing_ok=True)
        except OSError as cleanup:
            exc.add_note(f"could not remove temporary file: {cleanup}")
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
    identities = (user, security.CreateWellKnownSid(security.WinLocalSystemSid),
                  security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid))
    return tuple({str(sid): sid for sid in identities}.values())


def _verify_private(path: Path, principals) -> None:
    """An inherited ACL must lead back to a user-owned, protected private root."""
    expected = {str(sid) for sid in principals}
    current = path.absolute()
    while True:
        _refuse_link(current)
        if not stat.S_ISDIR(current.stat().st_mode):
            raise NotADirectoryError(errno.ENOTDIR, "expected a private directory", str(current))
        sd = security.GetNamedSecurityInfo(str(current), security.SE_FILE_OBJECT,
                                           security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        protected = sd.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED
        owner = sd.GetSecurityDescriptorOwner()
        acl = sd.GetSecurityDescriptorDacl()
        if str(owner) not in expected or acl is None or acl.GetAceCount() != len(expected):
            break
        flags = _INHERIT if protected else _INHERIT | security.INHERITED_ACE
        expected_ace = ((security.ACCESS_ALLOWED_ACE_TYPE, flags), ntsecuritycon.FILE_ALL_ACCESS)
        aces = [acl.GetAce(i) for i in range(acl.GetAceCount())]
        if any(ace[:2] != expected_ace for ace in aces) or {str(ace[2]) for ace in aces} != expected:
            break
        if protected:
            if owner == principals[0]:
                return
            break
        if current == current.parent:
            break
        current = current.parent
    raise PermissionError(errno.EACCES, "unsafe owner or permissions on private directory", str(current))


def _existing_private_parent(path: Path) -> None:
    with _winerrors(path):
        _verify_private(path, _principals())


def ensure_private_parent(path: Path) -> None:
    _refuse_links(path)
    try:
        principals = _principals()
        attributes = _attributes(path)
        if attributes and not attributes & stat.FILE_ATTRIBUTE_DIRECTORY:
            raise FileExistsError(errno.EEXIST, "private directory name is occupied", str(path))
        if not attributes:
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
    _existing_private_parent(path.parent)
    return _exclusive_fd(path)


def private_temp(parent: Path, *, prefix: str, suffix: str) -> tuple[int, str]:
    _existing_private_parent(parent)
    _check_name(prefix + "_" + suffix)
    return _new_temp(lambda: parent / (prefix + secrets.token_hex(8) + suffix))


def _file_id(handle) -> tuple[int, int, int]:
    info = win32file.GetFileInformationByHandle(handle)
    return info[4], info[8], info[9]  # volume serial, high and low halves of the file index


def _remove_owned_temp(path: Path, identity: tuple[int, int, int]) -> None:
    try:
        handle = win32file.CreateFile(str(path), win32con.DELETE, _SHARE_ALL, None,
                                      win32con.OPEN_EXISTING, win32file.FILE_FLAG_OPEN_REPARSE_POINT, None)
        with closing(handle):
            if _file_id(handle) == identity:
                # Delete the entry we inspected even if another process swaps the name.
                win32file.SetFileInformationByHandle(handle, win32file.FileDispositionInfo, True)
    except pywintypes.error as exc:
        if exc.winerror not in (2, 3):
            raise OSError(0, exc.strerror, str(path), exc.winerror) from exc


@contextmanager
def reopenable_text(text: str, *, prefix: str, suffix: str) -> Iterator[Path]:
    folder = Path(tempfile.gettempdir())
    _check_name(prefix + "_" + suffix)
    fd, name = _new_temp(lambda: folder / (prefix + secrets.token_hex(8) + suffix), delete_access=True)
    path = Path(name)
    identity = None
    try:
        with os.fdopen(fd, "wb") as stream:
            handle = msvcrt.get_osfhandle(fd)
            with _winerrors(path):
                try:
                    identity = _file_id(handle)
                except pywintypes.error:
                    # Delete via the still-owned handle even when its ID could not be read.
                    win32file.SetFileInformationByHandle(handle, win32file.FileDispositionInfo, True)
                    raise
            stream.write(text.encode("utf-8"))
        yield path
    finally:
        if identity is not None:
            _remove_owned_temp(path, identity)


def open_for_mode(path: Path, kind: Literal["x", "xb", "a"], *,
                  mode: int | None = None, encoding: str | None = None) -> IO[Any]:
    opener = None if kind == "a" else lambda name, flags: _exclusive_fd(name)
    if kind == "xb":
        return open(path, kind, encoding=encoding, opener=opener)
    return open(path, kind, encoding="utf-8" if encoding is None else encoding, newline="\n", opener=opener)


def finish_mode(path: Path, mode: int, *, method: Literal["path", "os"] = "path") -> None:
    mapped = stat.S_IWRITE if mode & stat.S_IWUSR else stat.S_IREAD
    if method == "os":
        os.chmod(path, mapped)
    else:
        Path(path).chmod(mapped)


def open_regular(path: Path | str, *, policy: Literal["premise", "provenance"]) -> int:
    # Open the entry itself. Inspect the handle we actually return, so a swap
    # after inspection cannot redirect the reader to a different file.
    try:
        flags = _OPEN_ENTRY if policy == "premise" else win32con.FILE_FLAG_BACKUP_SEMANTICS
        handle = win32file.CreateFile(str(path), win32con.GENERIC_READ, _SHARE_ALL, None,
                                      win32con.OPEN_EXISTING, flags, None)
        with closing(handle):
            if policy == "provenance":
                return _take_fd(handle, os.O_RDONLY)
            info = win32file.GetFileInformationByHandleEx(handle, win32file.FileAttributeTagInfo)
            if _link_tag(info["ReparseTag"]):
                raise OSError(errno.ELOOP, "refusing link", str(path))
            if info["ReparseTag"]:
                # Give a cloud/storage provider normal data-open processing on this file.
                with closing(win32file.ReOpenFile(handle, win32con.GENERIC_READ, _SHARE_ALL, 0)) as data:
                    return _take_fd(data, os.O_RDONLY)
            return _take_fd(handle, os.O_RDONLY)
    except pywintypes.error as exc:
        raise OSError(0, exc.strerror, str(path), exc.winerror) from exc


def _check_name(name: str) -> None:
    if not name or Path(name).name != name or name in (".", "..") or ":" in name:
        raise ValueError("expected one directory entry name")


class _Directory:
    def __init__(self, path: Path):
        self.path = path.absolute()
        _refuse_links(self.path)
        if not stat.S_ISDIR(self.path.stat().st_mode):
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
