"""Managed installation entries on local NTFS. The caller holds the installation lock."""
from __future__ import annotations

import errno
import logging
import os
import stat
import struct
import sys
from contextlib import closing
from pathlib import Path

if sys.platform != "win32":
    raise ImportError("native link operations require Windows")

import ntsecuritycon
import win32api
import win32con
import win32file
import winioctlcon

from ._fsops_windows import _is_link, _winerrors
from .links import FileLinkPrivilegeError, LinkTargetUnsupported, UnmanagedLinkError


def _local_ntfs(path: Path) -> None:
    if not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":":
        raise LinkTargetUnsupported(errno.EINVAL, "junction requires an absolute local drive path", str(path))
    with _winerrors(path):
        volume = win32file.GetVolumePathName(str(path))
        if (win32file.GetDriveType(volume) not in (win32con.DRIVE_FIXED, win32con.DRIVE_REMOVABLE)
                or win32api.GetVolumeInformation(volume)[4].upper() != "NTFS"):
            raise LinkTargetUnsupported(errno.ENOTSUP, "junction requires a local NTFS volume", str(path))


def _junction_data(target: Path) -> bytes:
    # REPARSE_DATA_BUFFER.MountPointReparseBuffer offsets and lengths are bytes.
    name = os.path.normpath(str(target))
    substitute = ("\\??\\" + name).encode("utf-16-le")
    display = name.encode("utf-16-le")
    names = substitute + b"\0\0" + display + b"\0\0"
    if len(names) + 16 > 16 * 1024:
        raise LinkTargetUnsupported(errno.ENAMETOOLONG, "junction target exceeds the NTFS reparse buffer", str(target))
    return (struct.pack("<I6H", stat.IO_REPARSE_TAG_MOUNT_POINT, 8 + len(names), 0,
                        0, len(substitute), len(substitute) + 2, len(display)) + names)


def _stored_target(raw: str) -> str:
    # Only drive paths have an equivalent spelling without the namespace.
    for prefix in ("\\\\?\\", "\\??\\"):
        if raw.startswith(prefix):
            candidate = raw[len(prefix):]
            if _drive_target(candidate):
                return candidate
    return raw


def _drive_target(name: str) -> bool:
    path = Path(name)
    return len(path.drive) == 2 and path.drive[1] == ":" and path.is_absolute()


def _managed_handle(handle: int, tag: int) -> bool:
    if tag != stat.IO_REPARSE_TAG_MOUNT_POINT:
        return tag == stat.IO_REPARSE_TAG_SYMLINK
    # Volume mount points share the junction tag. Read the substitute name
    # on the same no-follow handle that will receive the update or deletion.
    data = win32file.DeviceIoControl(handle, winioctlcon.FSCTL_GET_REPARSE_POINT, None, 16 * 1024)
    offset, length = struct.unpack_from("<HH", data, 8)
    start = 16 + offset
    name = data[start:start + length].decode("utf-16-le", errors="surrogatepass")
    return True


def _open_entry(link: Path, access: int):
    # Deny other opens for write/delete while validating and changing this entry.
    return win32file.CreateFile(
        str(link), access, win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING,
        win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS, None,
    )


def _set_junction(link: Path, data: bytes, *, expected_tag: int) -> None:
    with _winerrors(link), closing(_open_entry(link, win32con.GENERIC_WRITE)) as handle:
        info = win32file.GetFileInformationByHandleEx(handle.handle, win32file.FileAttributeTagInfo)
        tag = info["ReparseTag"]
        if tag != expected_tag or (tag and not _managed_handle(handle.handle, tag)):
            raise UnmanagedLinkError(errno.EEXIST, "installation entry changed or is unmanaged", str(link))
        if tag == stat.IO_REPARSE_TAG_SYMLINK:
            if not info["FileAttributes"] & stat.FILE_ATTRIBUTE_DIRECTORY:
                raise UnmanagedLinkError(errno.EEXIST, "expected a directory link", str(link))
            # Windows SDK FSCTL_SET_REPARSE_POINT_EX, function 259. Supply the
            # current tag and the zero GUID/reserved fields of REPARSE_DATA_BUFFER_EX.
            control = winioctlcon.CTL_CODE(winioctlcon.FILE_DEVICE_FILE_SYSTEM, 259,
                                           winioctlcon.METHOD_BUFFERED, 0)
            control = winioctlcon.FSCTL_SET_REPARSE_POINT  # round control
        else:
            control = winioctlcon.FSCTL_SET_REPARSE_POINT
        win32file.DeviceIoControl(handle.handle, control, data, 0)


def create(link: Path, target: Path, *, directory: bool) -> None:
    if directory:
        _local_ntfs(target)
        _local_ntfs(link.absolute().parent)
        data = _junction_data(target)
        try:
            link.mkdir()
        except FileExistsError as exc:
            raise UnmanagedLinkError(exc.errno, exc.strerror, str(link), exc.winerror) from exc
        try:
            _set_junction(link, data, expected_tag=0)
        except BaseException:
            link.rmdir()
            raise
    else:
        try:
            os.symlink(str(target), link, target_is_directory=False)
        except FileExistsError as exc:
            raise UnmanagedLinkError(exc.errno, exc.strerror, str(link), exc.winerror) from exc
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
        return _drive_target(read_target(link))
    return tag == stat.IO_REPARSE_TAG_SYMLINK


def read_target(link: Path) -> str:
    return _stored_target(os.readlink(link))


def remove(link: Path) -> None:
    with _winerrors(link), closing(_open_entry(link, win32con.DELETE | ntsecuritycon.FILE_READ_ATTRIBUTES)) as handle:
        info = win32file.GetFileInformationByHandleEx(handle.handle, win32file.FileAttributeTagInfo)
        if not _managed_handle(handle.handle, info["ReparseTag"]):
            raise UnmanagedLinkError(errno.EEXIST, "refusing to remove an unmanaged entry", str(link))
        win32file.SetFileInformationByHandle(handle.handle, win32file.FileDispositionInfo, True)


def replace_staged(staged: Path, link: Path) -> None:
    if not is_managed(staged):
        raise UnmanagedLinkError(errno.EINVAL, "expected a staged installation link", str(staged))
    try:
        os.rename(staged, link)  # Windows never overwrites an existing name.
        return
    except FileExistsError:
        pass
    if not is_managed(link):
        raise UnmanagedLinkError(errno.EEXIST, "refusing to replace an unmanaged entry", str(link))
    if os.path.samestat(staged.lstat(), link.lstat()):
        return
    if _tag(staged) == stat.IO_REPARSE_TAG_MOUNT_POINT:
        # The public name stays in place. A single filesystem request changes
        # its substitute name. Consuming the staged entry is a separate step.
        target = Path(read_target(staged))
        _local_ntfs(target)
        current_tag = _tag(link)
        if current_tag not in (stat.IO_REPARSE_TAG_MOUNT_POINT, stat.IO_REPARSE_TAG_SYMLINK):
            raise UnmanagedLinkError(errno.EEXIST, "installation entry changed", str(link))
        _set_junction(link, _junction_data(target), expected_tag=current_tag)
        try:
            remove(staged)
        except OSError as exc:
            logging.getLogger(__name__).warning("Published %s; could not remove stage %s: %s", link, staged, exc)
    else:
        # File symlinks use a rename. Incompatible directory/tag replacements
        # surface the native error without first removing the public name.
        os.replace(staged, link)
