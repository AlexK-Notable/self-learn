"""Native owner and link decisions, and syscall oracles for their POSIX counterparts."""

import errno
import json
import os
import stat
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import cache_gc, provenance, settings
from self_learn.primitives import fsops

windows = pytest.mark.skipif(os.name != "nt", reason="Windows owner and link contract")
linux = pytest.mark.skipif(os.name == "nt", reason="POSIX owner and link contract")


@linux
def test_posix_owner_uses_path_stat_then_real_uid(tmp_path, monkeypatch):
    calls = []

    def path_stat(path):
        calls.append(("stat", path))
        return SimpleNamespace(st_uid=41)

    def real_uid():
        calls.append(("getuid",))
        return 41

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", path_stat)
        patch.setattr(os, "getuid", real_uid)
        owned = fsops.owned_by_current_user(tmp_path)
    assert owned
    assert calls == [("stat", tmp_path), ("getuid",)]


@linux
def test_posix_link_uses_path_is_symlink(tmp_path, monkeypatch):
    calls = []

    def is_symlink(path):
        calls.append(path)
        return True

    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_symlink", is_symlink)
        linked = fsops.is_link(tmp_path)
    assert linked
    assert calls == [tmp_path]


@linux
def test_posix_cache_and_provenance_keep_their_open_flags(tmp_path, monkeypatch):
    witness = tmp_path / cache_gc.GLOB_WITNESS_DIR
    witness.mkdir()
    file = tmp_path / "brief"
    file.write_bytes(b"brief")
    original_open = os.open
    calls = []

    def observed_open(*args, **kwargs):
        calls.append((args, kwargs))
        return original_open(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", observed_open)
        result = cache_gc.PruneResult()
        cache_gc._prune_glob_witnesses(tmp_path, 0, False, result)
        with os.fdopen(fsops.open_regular(file, policy="provenance"), "rb") as stream:
            assert stream.read() == b"brief"
    assert not result.errors
    assert calls == [
        ((witness, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW), {}),
        ((file, os.O_RDONLY | os.O_NONBLOCK), {}),
    ]


def _windows_owner(path):
    import win32security as security

    return security.GetNamedSecurityInfo(
        str(path), security.SE_FILE_OBJECT, security.OWNER_SECURITY_INFORMATION
    ).GetSecurityDescriptorOwner()


@pytest.fixture(scope="module")
def ordinary_account(tmp_path_factory):
    import secrets

    import ntsecuritycon
    import win32con
    import win32net
    import win32netcon
    import win32security as security

    parent = tmp_path_factory.mktemp("ownership")
    name = "sl-owner-" + secrets.token_hex(4)
    password = "aA2!" + secrets.token_hex(16)
    win32net.NetUserAdd(None, 1, {
        "name": name,
        "password": password,
        "priv": win32netcon.USER_PRIV_USER,
        "flags": win32netcon.UF_SCRIPT | win32netcon.UF_NORMAL_ACCOUNT,
    })
    try:
        with closing(security.LogonUser(
            name, ".", password, win32con.LOGON32_LOGON_INTERACTIVE, win32con.LOGON32_PROVIDER_DEFAULT
        )) as token:
            user = security.GetTokenInformation(token, security.TokenUser)[0]
            assert not security.GetTokenInformation(token, security.TokenElevation)
            acl = security.GetNamedSecurityInfo(
                str(parent), security.SE_FILE_OBJECT, security.DACL_SECURITY_INFORMATION
            ).GetSecurityDescriptorDacl()
            acl.AddAccessAllowedAce(security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user)
            security.SetNamedSecurityInfo(str(parent), security.SE_FILE_OBJECT,
                                          security.DACL_SECURITY_INFORMATION, None, None, acl, None)
            owned = parent / "ordinary-owned"
            security.ImpersonateLoggedOnUser(token)
            try:
                owned.mkdir()
            finally:
                security.RevertToSelf()
            assert _windows_owner(owned) == user
            yield token, owned
    finally:
        win32net.NetUserDel(None, name)


@windows
def test_windows_runner_and_administrators_group_own_roots(tmp_path):
    import win32api
    import win32con
    import win32security as security

    created, group_owned = tmp_path / "created", tmp_path / "group-owned"
    created.mkdir()
    group_owned.mkdir()
    administrators = security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid)
    with closing(security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)) as token:
        user = security.GetTokenInformation(token, security.TokenUser)[0]
        assert security.GetTokenInformation(token, security.TokenElevation)
    assert _windows_owner(created) in (user, administrators)
    assert fsops.owned_by_current_user(created)
    security.SetNamedSecurityInfo(str(group_owned), security.SE_FILE_OBJECT,
                                  security.OWNER_SECURITY_INFORMATION, administrators, None, None, None)
    assert _windows_owner(group_owned) == administrators
    assert fsops.owned_by_current_user(group_owned)


@windows
def test_windows_ordinary_account_owns_its_root_only(tmp_path, monkeypatch, ordinary_account):
    import win32security as security

    ordinary_token, ordinary_owned = ordinary_account
    administrator_owned = tmp_path / "administrator-owned"
    administrator_owned.mkdir()
    administrators = security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid)
    security.SetNamedSecurityInfo(str(administrator_owned), security.SE_FILE_OBJECT,
                                  security.OWNER_SECURITY_INFORMATION, administrators, None, None, None)
    assert _windows_owner(administrator_owned) == administrators
    assert fsops.owned_by_current_user(administrator_owned)
    assert not fsops.owned_by_current_user(ordinary_owned)

    # Use the genuine standard-user logon token at the process-token lookup.
    # The runner process continues to make the filesystem metadata queries.
    def ordinary_process_token(process, access):
        return security.DuplicateTokenEx(
            ordinary_token, security.SecurityImpersonation, access, security.TokenPrimary, None
        )

    monkeypatch.setattr(security, "OpenProcessToken", ordinary_process_token)
    assert fsops.owned_by_current_user(ordinary_owned)
    assert not fsops.owned_by_current_user(administrator_owned)


@windows
def test_windows_settings_accepts_only_owned_root(tmp_path, ordinary_account):
    _, other = ordinary_account
    owned = tmp_path / "owned"
    owned.mkdir()
    (tmp_path / "config.yaml").write_text(
        "hosts:\n  extra_roots: " + json.dumps(os.pathsep.join(map(str, (owned, other)))) + "\n",
        encoding="utf-8",
    )
    good, bad = settings.host_extra_roots(tmp_path)
    assert good == [owned.resolve()]
    assert bad == [f"{other} is not owned by the current user"]


@windows
def test_windows_cache_skips_junction_after_scanning_ordinary_sibling(tmp_path):
    import _winapi

    cache, outside = tmp_path / "cache", tmp_path / "outside"
    cache.mkdir()
    outside.mkdir()
    missing = [tmp_path / name for name in ("former-home", "other-former-home")]
    ordinary = cache / ("home-" + cache_gc.home_digest(missing[0]))
    junction = cache / ("home-" + cache_gc.home_digest(missing[1]))
    ordinary.mkdir()
    cache_gc.record_home(ordinary, missing[0])
    cache_gc.record_home(outside, missing[1])
    keep = outside / "sentinel"
    keep.write_bytes(b"untouched")
    _winapi.CreateJunction(str(outside), str(junction))
    assert junction.is_junction() and junction.samefile(outside)
    assert cache_gc.read_home_pointer(junction) == missing[1]
    witnesses = cache / cache_gc.GLOB_WITNESS_DIR
    _winapi.CreateJunction(str(outside), str(witnesses))
    old_witness = outside / ("a" * 64 + ".json")
    old_witness.write_bytes(b"outside witness")

    now = time.time() + cache_gc.GLOB_WITNESS_MAX_AGE_SECS + 60
    result = cache_gc.prune(root=cache, now=now)
    assert not result.errors
    assert ordinary.name in result.removed_homes and not ordinary.exists()
    assert junction.is_junction() and result.removed_homes == [ordinary.name]
    assert keep.read_bytes() == b"untouched"
    assert old_witness.read_bytes() == b"outside witness"
    assert result.removed_glob_witnesses == []


@windows
def test_windows_cloud_tag_remains_an_ordinary_readable_file(tmp_path, monkeypatch):
    import win32api
    import win32file

    file = tmp_path / "cloud"
    file.write_bytes(b"hydrated")
    real_attributes = win32api.GetFileAttributes
    real_info = win32file.GetFileInformationByHandleEx
    tags_read = []

    def cloud_attributes(path):
        return real_attributes(path) | stat.FILE_ATTRIBUTE_REPARSE_POINT

    def cloud_info(handle, kind):
        assert kind == win32file.FileAttributeTagInfo
        info = real_info(handle, kind)
        tags_read.append(handle)
        return {**info, "ReparseTag": 0x9000001A,
                "FileAttributes": info["FileAttributes"] | stat.FILE_ATTRIBUTE_REPARSE_POINT}

    monkeypatch.setattr(win32api, "GetFileAttributes", cloud_attributes)
    monkeypatch.setattr(win32file, "GetFileInformationByHandleEx", cloud_info)
    assert not fsops.is_link(file)
    with os.fdopen(fsops.open_regular(file, policy="provenance"), "rb") as stream:
        assert stream.read() == b"hydrated"
    assert len(tags_read) == 2


@windows
def test_windows_provenance_reads_regular_brief_and_refuses_link(tmp_path, monkeypatch):
    regular, link = tmp_path / "brief", tmp_path / "redirect"
    regular.write_text("source text", encoding="utf-8")
    link.symlink_to(regular)
    assert link.is_symlink() and link.samefile(regular)
    send = provenance.Send(time.time() + 60, "session", "send", "send")
    monkeypatch.setattr(provenance, "_brief_paths", lambda _: [regular, link])
    unread = []
    found = provenance._expand_files([send], {}, unread)
    assert found and found[0].raw == "source text"
    assert len(found) == 1 and unread == [link]
    with pytest.raises(OSError) as refusal:
        fsops.open_regular(link, policy="provenance")
    assert refusal.value.errno == errno.ELOOP


@windows
def test_windows_owner_preserves_native_error_and_cause(tmp_path):
    import pywintypes

    missing = tmp_path / "missing"
    with pytest.raises(OSError) as caught:
        fsops.owned_by_current_user(missing)
    assert isinstance(caught.value.__cause__, pywintypes.error)
    assert caught.value.winerror == caught.value.__cause__.winerror in (2, 3)
    assert caught.value.filename == str(missing)
