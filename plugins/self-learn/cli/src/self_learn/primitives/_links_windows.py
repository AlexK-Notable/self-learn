"""Managed installation entries on local NTFS. The caller holds the installation lock."""
from __future__ import annotations

import errno
import os
import stat
import struct
import sys
from contextlib import closing
from pathlib import Path

if sys.platform != "win32":
    raise ImportError("native link operations require Windows")

import win32api
import win32con
import win32file
import winioctlcon

from ._fsops_windows import _is_link, _winerrors
from .links import FileLinkPrivilegeError


def _local_ntfs(path: Path) -> None:
    if not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":":
        raise ValueError(f"junction requires an absolute local drive path: {path}")
    with _winerrors(path):
        volume = win32file.GetVolumePathName(str(path))
        if (win32file.GetDriveType(volume) not in (win32con.DRIVE_FIXED, win32con.DRIVE_REMOVABLE)
                or win32api.GetVolumeInformation(volume)[4].upper() != "NTFS"):
            raise ValueError(f"junction requires a local NTFS volume: {path}")


def _junction_data(target: Path) -> bytes:
    # REPARSE_DATA_BUFFER.MountPointReparseBuffer offsets and lengths are bytes.
    name = os.path.normpath(str(target))
    substitute = ("\\??\\" + name).encode("utf-16-le")
    display = name.encode("utf-16-le")
    names = substitute + b"\0\0" + display + b"\0\0"
    if len(names) + 16 > 16 * 1024:
        raise ValueError(f"junction target exceeds the NTFS reparse buffer: {target}")
    return (struct.pack("<I6H", stat.IO_REPARSE_TAG_MOUNT_POINT, 8 + len(names), 0,
                        0, len(substitute), len(substitute) + 2, len(display)) + names)


def _set_junction(link: Path, data: bytes, *, expected_tag: int) -> None:
    with _winerrors(link), closing(win32file.CreateFile(
        str(link), win32con.GENERIC_WRITE, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        None, win32con.OPEN_EXISTING,
        win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS, None,
    )) as handle:
        info = win32file.GetFileInformationByHandleEx(handle.handle, win32file.FileAttributeTagInfo)
        if info["ReparseTag"] != expected_tag:
            raise FileExistsError(errno.EEXIST, "installation entry changed", str(link))
        win32file.DeviceIoControl(handle.handle, winioctlcon.FSCTL_SET_REPARSE_POINT, data, 0)


def create(link: Path, target: Path, *, directory: bool) -> None:
    if directory:
        _local_ntfs(target)
        _local_ntfs(link.absolute().parent)
        data = _junction_data(target)
        link.mkdir()
        try:
            _set_junction(link, data, expected_tag=0)
        except BaseException:
            link.rmdir()
            raise
    else:
        try:
            os.symlink(str(target), link, target_is_directory=False)
        except OSError as exc:
            if exc.winerror != 1314:
                raise
            raise FileLinkPrivilegeError(exc.errno, exc.strerror, str(link), exc.winerror) from exc


def _tag(path: Path) -> int:
    try:
        return path.lstat().st_reparse_tag
    except (FileNotFoundError, NotADirectoryError):
        return 0


def is_any_link(path: Path) -> bool:
    # Non-name-surrogates can be followed even by Windows lstat. Query the
    # actual entry to include AppExecLink and distinguish cloud placeholders.
    return _is_link(path)


def is_managed(link: Path) -> bool:
    tag = _tag(link)
    if tag == stat.IO_REPARSE_TAG_MOUNT_POINT:
        # A mounted volume (Volume{GUID}) shares the junction tag but is not
        # an installation entry. Only manage drive-letter directory targets.
        target = os.readlink(link).removeprefix("\\\\?\\")
        return len(Path(target).drive) == 2 and Path(target).is_absolute()
    return tag == stat.IO_REPARSE_TAG_SYMLINK


def read_target(link: Path) -> str:
    raw = os.readlink(link)
    if _tag(link) == stat.IO_REPARSE_TAG_MOUNT_POINT:
        return raw.removeprefix("\\\\?\\")
    return raw


def remove(link: Path) -> None:
    if not is_managed(link):
        raise ValueError(f"refusing to remove an unmanaged entry: {link}")
    if link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY:
        link.rmdir()
    else:
        link.unlink()


def replace_staged(staged: Path, link: Path) -> None:
    if not is_managed(staged):
        raise ValueError(f"expected a staged installation link: {staged}")
    try:
        os.rename(staged, link)  # Windows never overwrites an existing name.
        return
    except FileExistsError:
        pass
    if not is_managed(link):
        raise FileExistsError(errno.EEXIST, "refusing to replace an unmanaged entry", str(link))
    if os.path.samestat(staged.lstat(), link.lstat()):
        return
    if _tag(staged) == _tag(link) == stat.IO_REPARSE_TAG_MOUNT_POINT:
        # The public name stays in place. A single filesystem request changes
        # its substitute name. Consuming the staged entry is a separate step.
        target = Path(read_target(staged))
        _local_ntfs(target)
        _set_junction(link, _junction_data(target), expected_tag=stat.IO_REPARSE_TAG_MOUNT_POINT)
        remove(staged)
    else:
        # File symlinks use a rename. Incompatible directory/tag replacements
        # surface the native error without first removing the public name.
        os.replace(staged, link)
