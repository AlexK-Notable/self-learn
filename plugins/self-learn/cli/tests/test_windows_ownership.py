"""Native owner and link decisions, and syscall oracles for their POSIX counterparts."""

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
@pytest.mark.parametrize("deny_only", [False, True], ids=["requires-elevation", "requires-membership"])
def test_windows_admin_owner_requires_elevation_and_enabled_membership(tmp_path, monkeypatch, deny_only):
    import win32api
    import win32con
    import win32security as security

    group_owned = tmp_path / "group-owned"
    group_owned.mkdir()
    administrators = security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid)
    security.SetNamedSecurityInfo(str(group_owned), security.SE_FILE_OBJECT,
                                  security.OWNER_SECURITY_INFORMATION, administrators, None, None, None)
    assert _windows_owner(group_owned) == administrators
    assert fsops.owned_by_current_user(group_owned)
    real_info = security.GetTokenInformation
    elevated = False

    with closing(security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY | win32con.TOKEN_DUPLICATE
    )) as runner:
        with closing(security.CreateRestrictedToken(runner, 0, [(administrators, 0)], None, None)) as restricted:
            token = restricted if deny_only else runner
            with closing(security.DuplicateToken(token, security.SecurityIdentification)) as membership:
                assert security.CheckTokenMembership(membership, administrators) == (not deny_only)
            if deny_only:
                groups = dict((str(sid), attributes) for sid, attributes in real_info(token, security.TokenGroups))
                assert groups[str(administrators)] & win32con.SE_GROUP_USE_FOR_DENY_ONLY

            def process_token(process, access):
                return security.DuplicateTokenEx(
                    token, security.SecurityImpersonation, access, security.TokenPrimary, None
                )

            def token_info(handle, kind):
                if kind == security.TokenElevation:
                    return int(elevated)
                return real_info(handle, kind)

            monkeypatch.setattr(security, "OpenProcessToken", process_token)
            monkeypatch.setattr(security, "GetTokenInformation", token_info)
            # The restricted token models an unelevated administrator with a deny-only SID.
            assert not fsops.owned_by_current_user(group_owned)
            # Hold the other condition true to test each requirement independently.
            elevated = True
            assert fsops.owned_by_current_user(group_owned) == (not deny_only)


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
def test_windows_settings_ignores_owner_access_denied(tmp_path, monkeypatch):
    import pywintypes
    import win32security as security

    denied, allowed = tmp_path / "denied", tmp_path / "allowed"
    denied.mkdir()
    allowed.mkdir()
    assert denied.is_dir()
    (tmp_path / "config.yaml").write_text(
        "hosts:\n  extra_roots: " + json.dumps(os.pathsep.join(map(str, (denied, allowed)))) + "\n",
        encoding="utf-8",
    )
    real_info = security.GetNamedSecurityInfo
    owner_queries = []

    def read_security(name, kind, flags):
        owner_queries.append((Path(name), kind, flags))
        if Path(name) == denied.resolve():
            raise pywintypes.error(5, "GetNamedSecurityInfo", "Access is denied")
        return real_info(name, kind, flags)

    monkeypatch.setattr(security, "GetNamedSecurityInfo", read_security)
    good, bad = settings.host_extra_roots(tmp_path)
    assert good == [allowed.resolve()]
    assert (denied.resolve(), security.SE_FILE_OBJECT, security.OWNER_SECURITY_INFORMATION) in owner_queries
    assert bad == [f"{denied} is not owned by the current user"]


def _orphan(cache, former_home):
    directory = cache / ("home-" + cache_gc.home_digest(former_home))
    directory.mkdir()
    cache_gc.record_home(directory, former_home)
    assert cache_gc.read_home_pointer(directory) == former_home
    return directory


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
    assert ordinary.name in result.removed_homes and not ordinary.exists()
    assert not result.errors
    assert junction.is_junction() and result.removed_homes == [ordinary.name]
    assert keep.read_bytes() == b"untouched"
    assert old_witness.read_bytes() == b"outside witness"
    assert result.removed_glob_witnesses == []


@windows
@pytest.mark.parametrize("link_type", ["junction", "symlink"])
def test_windows_cache_follows_configured_root(tmp_path, link_type):
    import _winapi

    cache, alias = tmp_path / "cache", tmp_path / "cache-alias"
    cache.mkdir()
    home = _orphan(cache, tmp_path / "former")
    witnesses = cache / cache_gc.GLOB_WITNESS_DIR
    witnesses.mkdir()
    witness = witnesses / ("a" * 64 + ".json")
    witness.write_bytes(b"old")
    if link_type == "junction":
        _winapi.CreateJunction(str(cache), str(alias))
        assert alias.is_junction()
    else:
        alias.symlink_to(cache, target_is_directory=True)
        assert alias.is_symlink()
    assert alias.samefile(cache)

    result = cache_gc.prune(root=alias, now=time.time() + cache_gc.GLOB_WITNESS_MAX_AGE_SECS + 60)
    assert result.removed_homes == [home.name] and not home.exists()
    assert result.removed_glob_witnesses == [witness.name] and not witness.exists()
    assert alias.samefile(cache) and not result.errors


@windows
def test_windows_cache_age_walk_excludes_nested_junction(tmp_path):
    import _winapi

    cache, outside = tmp_path / "cache", tmp_path / "outside"
    cache.mkdir()
    outside.mkdir()
    recent = outside / "recent"
    recent.write_bytes(b"outside")
    home = _orphan(cache, tmp_path / "former")
    junction = home / "redirect"
    _winapi.CreateJunction(str(outside), str(junction))
    assert junction.is_junction() and junction.samefile(outside)
    assert junction.name in next(os.walk(home, followlinks=False))[1]
    now = time.time()
    old = now - cache_gc.HOME_MIN_IDLE_SECS - 60
    for entry in (home / cache_gc.HOME_POINTER, home):
        os.utime(entry, (old, old))
    assert recent.stat().st_mtime > old

    result = cache_gc.prune(root=cache, now=now)
    assert result.removed_homes == [home.name] and not home.exists()
    assert recent.read_bytes() == b"outside"
    assert not result.errors


@windows
def test_windows_cache_skips_symlinked_home_pointer(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    ordinary = _orphan(cache, tmp_path / "former")
    foreign, missing = tmp_path / "outside-pointer", tmp_path / "other-former"
    foreign.write_text(str(missing), encoding="utf-8")
    redirected = cache / ("home-" + cache_gc.home_digest(missing))
    redirected.mkdir()
    pointer = redirected / cache_gc.HOME_POINTER
    pointer.symlink_to(foreign)
    assert pointer.is_symlink() and pointer.samefile(foreign)
    assert cache_gc.read_home_pointer(redirected) == missing

    result = cache_gc.prune(root=cache, now=time.time() + cache_gc.HOME_MIN_IDLE_SECS + 60)
    assert ordinary.name in result.removed_homes and not ordinary.exists()
    assert result.removed_homes == [ordinary.name] and result.unattributed == 1
    assert pointer.is_symlink() and foreign.read_text(encoding="utf-8") == str(missing)
    assert not result.errors


@windows
def test_windows_cache_skips_application_execution_alias_witness(tmp_path, monkeypatch):
    import win32api
    import win32file

    witnesses = tmp_path / cache_gc.GLOB_WITNESS_DIR
    witnesses.mkdir()
    alias = witnesses / ("a" * 64 + ".json")
    ordinary = witnesses / ("b" * 64 + ".json")
    alias.write_bytes(b"alias witness")
    ordinary.write_bytes(b"ordinary witness")
    real_attributes = win32api.GetFileAttributes
    real_tag = win32file.GetFileInformationByHandleEx
    tags_read = []

    def attributes(name):
        value = real_attributes(name)
        return value | stat.FILE_ATTRIBUTE_REPARSE_POINT if Path(name) == alias else value

    def tag(handle, kind):
        value = real_tag(handle, kind)
        assert kind == win32file.FileAttributeTagInfo
        tags_read.append(kind)
        return {**value, "ReparseTag": stat.IO_REPARSE_TAG_APPEXECLINK}

    monkeypatch.setattr(win32api, "GetFileAttributes", attributes)
    monkeypatch.setattr(win32file, "GetFileInformationByHandleEx", tag)
    result = cache_gc.prune(root=tmp_path, now=time.time() + cache_gc.GLOB_WITNESS_MAX_AGE_SECS + 60)
    assert result.removed_glob_witnesses == [ordinary.name] and not ordinary.exists()
    assert tags_read and alias.read_bytes() == b"alias witness"
    assert not result.errors


@windows
@pytest.mark.parametrize("site", ["home", "quarantine", "nested", "pointer", "witness"])
def test_windows_cache_skips_uninspectable_entry(tmp_path, monkeypatch, site):
    import pywintypes
    import win32api

    ordinary = _orphan(tmp_path, tmp_path / "former")
    uncertain = _orphan(tmp_path, tmp_path / "other-former")
    nested = uncertain / "nested"
    nested.mkdir()
    witnesses = tmp_path / cache_gc.GLOB_WITNESS_DIR
    witnesses.mkdir()
    witness, other = (witnesses / (letter * 64 + ".json") for letter in "ab")
    witness.write_bytes(b"uncertain")
    other.write_bytes(b"ordinary")
    denied = {
        "home": uncertain,
        "quarantine": uncertain / "script-quarantine",
        "nested": nested,
        "pointer": uncertain / cache_gc.HOME_POINTER,
        "witness": witness,
    }[site]
    real_attributes = win32api.GetFileAttributes
    faults = []

    def attributes(name):
        if Path(name) == denied:
            faults.append(name)
            raise pywintypes.error(5, "GetFileAttributes", "Access is denied")
        return real_attributes(name)

    monkeypatch.setattr(win32api, "GetFileAttributes", attributes)
    result = cache_gc.prune(root=tmp_path, now=time.time() + cache_gc.GLOB_WITNESS_MAX_AGE_SECS + 60)
    assert ordinary.name in result.removed_homes and not ordinary.exists()
    assert other.name in result.removed_glob_witnesses and not other.exists()
    assert faults and not result.errors
    if site == "witness":
        assert witness.read_bytes() == b"uncertain"
    else:
        assert uncertain.is_dir() and nested.is_dir()


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
    with os.fdopen(fsops.open_regular(file, policy="premise"), "rb") as stream:
        assert stream.read() == b"hydrated"
    assert len(tags_read) == 2


@windows
def test_windows_provenance_reads_regular_and_symlinked_briefs(tmp_path, monkeypatch):
    regular, link = tmp_path / "brief", tmp_path / "redirect"
    regular.write_text("source text", encoding="utf-8")
    link.symlink_to(regular)
    assert link.is_symlink() and link.samefile(regular)
    send = provenance.Send(time.time() + 60, "session", "send", "send")
    monkeypatch.setattr(provenance, "_brief_paths", lambda _: [regular, link])
    unread = []
    found = provenance._expand_files([send], {}, unread)
    assert found and found[0].raw == "source text"
    assert [brief.raw for brief in found] == ["source text", "source text"]
    assert unread == []


@windows
def test_windows_owner_preserves_native_error_and_cause(tmp_path):
    import pywintypes

    missing = tmp_path / "missing"
    with pytest.raises(OSError) as caught:
        fsops.owned_by_current_user(missing)
    assert isinstance(caught.value.__cause__, pywintypes.error)
    assert caught.value.winerror == caught.value.__cause__.winerror in (2, 3)
    assert caught.value.filename == str(missing)
