"""Skill installation entry contracts against real filesystem objects."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from self_learn.primitives import links


posix = pytest.mark.skipif(os.name == "nt", reason="POSIX skill installation calls")
windows = pytest.mark.skipif(os.name != "nt", reason="Windows NTFS contracts")


def test_directory_publication_and_removal(tmp_path):
    first, second, stage, public = (tmp_path / n for n in ("first", "second", "stage", "public"))
    for target in (first, second):
        target.mkdir()
        (target / "sentinel").write_text(target.name)
    links.create(stage, first, directory=True)
    links.replace_staged(stage, public)
    assert not os.path.lexists(stage)
    assert links.is_managed(public) and links.is_any_link(public)
    assert links.read_target(public) == str(first)
    assert (public / "sentinel").read_text() == "first"
    links.create(stage, second, directory=True)
    links.replace_staged(stage, public)
    assert not os.path.lexists(stage)
    assert (public / "sentinel").read_text() == "second"
    links.remove(public)
    assert not os.path.lexists(public)
    assert [(p / "sentinel").read_text() for p in (first, second)] == ["first", "second"]


def test_dangling_directory(tmp_path):
    link, target = tmp_path / "link", tmp_path / "gone"
    target.mkdir()
    links.create(link, target, directory=True)
    target.rmdir()
    assert not link.exists()
    assert links.is_managed(link) and links.is_any_link(link)
    assert links.read_target(link) == str(target)
    links.remove(link)
    assert not os.path.lexists(link)


def test_file_link(tmp_path):
    link, target, stage = tmp_path / "entry", tmp_path / "payload", tmp_path / "stage"
    target.write_text("original")
    links.create(link, Path("payload"), directory=False)
    assert links.read_target(link) == "payload"
    assert links.is_managed(link) and links.is_any_link(link)
    assert link.read_text() == "original"
    links.create(stage, Path("missing"), directory=False)
    links.replace_staged(stage, link)
    assert not os.path.lexists(stage) and not link.exists()
    assert links.read_target(link) == "missing"
    links.remove(link)
    assert target.read_text() == "original"
    assert not os.path.lexists(link)


def test_occupied_directory(tmp_path):
    folder, stage = tmp_path / "ordinary", tmp_path / "stage"
    folder.mkdir()
    assert not links.is_any_link(folder) and not links.is_managed(folder)
    with pytest.raises(FileExistsError):
        links.create(folder, tmp_path, directory=True)
    links.create(stage, tmp_path, directory=True)
    with pytest.raises((ValueError, OSError)):
        links.replace_staged(stage, folder)
    with pytest.raises((ValueError, OSError)):
        links.remove(folder)
    assert folder.is_dir() and not links.is_any_link(folder)
    assert links.is_managed(stage)
    links.remove(stage)


@windows
def test_windows_native_facts(tmp_path):
    import ctypes

    assert ctypes.windll.shell32.IsUserAnAdmin(), "hosted runner privilege changed"
    target = tmp_path / "directory"
    target.mkdir()
    for kind in ("junction", "directory symlink"):
        path = tmp_path / kind
        if kind == "junction":
            links.create(path, target, directory=True)
        else:
            os.symlink(target, path, target_is_directory=True)
        symlink = kind == "directory symlink"
        tag = path.lstat().st_reparse_tag
        isjunction = getattr(os.path, "isjunction", None)
        facts = (path.is_symlink(), os.path.islink(path), isjunction(path) if isjunction else None,
                 hex(tag), os.readlink(path))
        print(sys.version.split()[0], kind, facts)
        assert facts == (symlink, symlink, (not symlink) if isjunction else None,
                         hex(stat.IO_REPARSE_TAG_SYMLINK if symlink else stat.IO_REPARSE_TAG_MOUNT_POINT),
                         "\\\\?\\" + str(target))
        assert links.is_any_link(path) and links.is_managed(path)
        links.remove(path)
        assert target.is_dir()


@windows
def test_windows_target_validation(tmp_path, monkeypatch):
    import win32con
    import win32file

    entry = tmp_path / "link"
    for path in (Path("relative"), Path(r"\\server\share\folder")):
        with pytest.raises(ValueError, match="absolute local drive"):
            links.create(entry, path, directory=True)
    monkeypatch.setattr(win32file, "GetDriveType", lambda root: win32con.DRIVE_REMOTE)
    with pytest.raises(ValueError, match="local NTFS"):
        links.create(entry, tmp_path, directory=True)
    assert not os.path.lexists(entry)


@windows
def test_windows_privilege_error(tmp_path, monkeypatch):
    link = tmp_path / "file-link"
    for code in (1314, 5):
        failure = OSError(0, "injected at CreateSymbolicLink wrapper", None, code)
        def deny(target, name, *, target_is_directory):
            assert (target, name, target_is_directory) == ("file", link, False)
            raise failure
        monkeypatch.setattr(os, "symlink", deny)
        with pytest.raises(OSError) as caught:
            links.create(link, Path("file"), directory=False)
        assert caught.value.winerror == code
        if code == 1314:
            assert isinstance(caught.value, links.FileLinkPrivilegeError)
            assert caught.value.__cause__ is failure
        else:
            assert caught.value is failure
        assert not os.path.lexists(link)


@windows
def test_windows_retarget_failure_preserves_entries(tmp_path, monkeypatch):
    import pywintypes
    import win32file

    stage, public = tmp_path / "stage", tmp_path / "public"
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    links.create(public, first, directory=True)
    links.create(stage, second, directory=True)
    failure = pywintypes.error(5, "DeviceIoControl", "injected failure")
    def refuse(*args):
        assert links.read_target(public) == str(first)
        raise failure
    monkeypatch.setattr(win32file, "DeviceIoControl", refuse)
    with pytest.raises(OSError) as caught:
        links.replace_staged(stage, public)
    assert caught.value.winerror == 5 and caught.value.__cause__ is failure
    assert links.read_target(public) == str(first)
    assert links.read_target(stage) == str(second)


@posix
def test_posix_writer_syscalls(tmp_path, monkeypatch):
    from self_learn import skill_writer

    link, target = tmp_path / "public", tmp_path / "target"
    target.mkdir()
    (target / "SKILL.md").touch()
    link.symlink_to("absent")
    calls = []
    def spy(owner, name):
        original = getattr(owner, name)
        def observed(*args, **kwargs):
            calls.append((name, args, kwargs))
            return original(*args, **kwargs)
        monkeypatch.setattr(owner, name, observed)

    for owner, name in ((Path, "is_symlink"), (os, "readlink"), (os, "symlink"),
                        (os, "replace"), (Path, "unlink")):
        spy(owner, name)
    assert skill_writer._place_link(link, target) == "replaced"
    assert skill_writer._drop_link(link, target)
    stage = next(args[1] for name, args, _ in calls if name == "symlink")
    assert stage.parent == link.parent and stage.name.startswith(".public.self-learn-")
    assert calls == [
        ("is_symlink", (link,), {}), ("readlink", (link,), {}),
        ("symlink", (str(target), stage), {}), ("replace", (stage, link), {}),
        ("is_symlink", (stage,), {}), ("is_symlink", (link,), {}),
        ("readlink", (link,), {}), ("unlink", (link,), {}),
    ]
    # Relative spelling reaches the comparison fallback in both helpers. A
    # working foreign link also resolves once more for the refusal message.
    spy(Path, "resolve")
    link.symlink_to(target.name)
    calls.clear()
    assert skill_writer._place_link(link, target) == "unchanged"
    assert skill_writer._drop_link(link, target)
    assert [args for name, args, _ in calls if name == "resolve"] == [(link,), (target,)] * 2
    link.symlink_to(tmp_path)
    calls.clear()
    with pytest.raises(skill_writer.SkillLinkError, match="a working link"):
        skill_writer._place_link(link, target)
    assert [args for name, args, _ in calls if name == "resolve"] == [(link,), (target,), (link,)]
    link.unlink()
    failure = PermissionError("replace denied")
    def fail_replace(*args):
        raise failure
    monkeypatch.setattr(os, "replace", fail_replace)
    calls.clear()
    with pytest.raises(PermissionError) as caught:
        skill_writer._place_link(link, target)
    assert caught.value is failure
    stage = next(args[1] for name, args, _ in calls if name == "symlink")
    assert calls[-2:] == [("is_symlink", (stage,), {}), ("unlink", (stage,), {})]
    assert not os.path.lexists(stage)


@posix
def test_posix_installation_name_checks(tmp_path, monkeypatch):
    import test_skill_write as sk1
    from self_learn import skill_cli, skill_registration, skill_writer

    env = sk1.Env(tmp_path, monkeypatch)
    name = sk1.NAME
    link = env.link()
    link.symlink_to("missing")
    real = Path.is_symlink
    calls = []
    def observe(path):
        if path == link:
            calls.append(path)
        return real(path)
    monkeypatch.setattr(Path, "is_symlink", observe)
    result = skill_writer.check(env.home, name, sk1.draft())
    assert not result.ok and any(str(link) in p for p in result.problems)
    assert calls
    calls.clear()
    plan = skill_writer._RenamePlan(old="old", new=name, root=env.root, stage="fresh")
    with pytest.raises(skill_writer._Refused):
        skill_writer._rename_name_check(env.home, plan, set())
    assert calls == [link]
    calls.clear()
    with pytest.raises(skill_registration.RegistrationError, match="runtime link already exists"):
        skill_registration._adopt(env.home, env.root, tmp_path / name, name, "description", "human")
    assert calls == [link]
    calls.clear()
    state = skill_cli._skill_state(env.home, name, dict(status="live", plugin="plugin", created={}, last_write={}))
    assert state["link"] == "broken"
    assert calls == [link]
