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
    with pytest.raises(links.UnmanagedLinkError if os.name == "nt" else IsADirectoryError):
        links.replace_staged(stage, folder)
    with pytest.raises(links.UnmanagedLinkError if os.name == "nt" else IsADirectoryError):
        links.remove(folder)
    assert folder.is_dir() and not links.is_any_link(folder)
    assert links.is_managed(stage)
    links.remove(stage)
    with pytest.raises(FileNotFoundError):
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
        if sys.version_info >= (3, 12):
            assert callable(isjunction)
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
        with pytest.raises(links.LinkTargetUnsupported, match="absolute local drive"):
            links.create(entry, path, directory=True)
    with monkeypatch.context() as remote:
        remote.setattr(win32file, "GetDriveType", lambda root: win32con.DRIVE_REMOTE)
        with pytest.raises(links.LinkTargetUnsupported, match="local NTFS"):
            links.create(entry, tmp_path, directory=True)
    import win32api
    real_info = win32api.GetVolumeInformation
    monkeypatch.setattr(win32api, "GetVolumeInformation", lambda volume: (*real_info(volume)[:4], "FAT32"))
    with pytest.raises(links.LinkTargetUnsupported, match="local NTFS"):
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
    import winioctlcon
    real_ioctl = win32file.DeviceIoControl
    def refuse(handle, control, data, size):
        if control != winioctlcon.FSCTL_SET_REPARSE_POINT:
            return real_ioctl(handle, control, data, size)
        assert links.read_target(public) == str(first)
        raise failure
    with monkeypatch.context() as faults:
        faults.setattr(win32file, "DeviceIoControl", refuse)
        with pytest.raises(OSError) as caught:
            links.replace_staged(stage, public)
    assert caught.value.winerror == 5 and caught.value.__cause__ is failure
    assert links.read_target(public) == str(first)
    assert links.read_target(stage) == str(second)

    # Exchange the junction for an ordinary empty folder after classification
    # but before the no-follow open. The guard must inspect that same handle.
    displaced = tmp_path / "displaced"
    real_open = win32file.CreateFile
    def swap_before_open(name, *args):
        if name == str(public):
            public.rename(displaced)
            public.mkdir()
        return real_open(name, *args)
    with monkeypatch.context() as faults:
        faults.setattr(win32file, "CreateFile", swap_before_open)
        with pytest.raises(FileExistsError, match="installation entry changed"):
            links.replace_staged(stage, public)
    assert public.is_dir() and not links.is_any_link(public)
    assert links.read_target(displaced) == str(first)
    assert links.read_target(stage) == str(second)


@windows
def test_windows_volume_mount_is_unmanaged(tmp_path, monkeypatch):
    import struct
    import win32file
    import winioctlcon

    target, public, stage = (tmp_path / name for name in ("target", "public", "stage"))
    target.mkdir()
    links.create(public, target, directory=True)
    links.create(stage, target, directory=True)
    assert links.is_managed(public)
    # Simulate a volume mount's substitute name at both native read boundaries
    # on real junctions. No system volume is mounted or unmounted.
    volume = "Volume{00000000-0000-0000-0000-000000000000}\\"
    real_read = os.readlink
    monkeypatch.setattr(os, "readlink", lambda path: "\\\\?\\" + volume if path == public else real_read(path))
    assert links.is_any_link(public) and not links.is_managed(public)
    assert links.read_target(public) == "\\\\?\\" + volume
    raw = ("\\??\\" + volume).encode("utf-16-le")
    def get_mount(handle, control, data, size):
        assert control == winioctlcon.FSCTL_GET_REPARSE_POINT
        return struct.pack("<I6H", stat.IO_REPARSE_TAG_MOUNT_POINT, 10 + len(raw), 0,
                           0, len(raw), len(raw), 0) + raw + b"\0\0"
    monkeypatch.setattr(win32file, "DeviceIoControl", get_mount)
    with pytest.raises(links.UnmanagedLinkError):
        links.remove(public)
    with pytest.raises(links.UnmanagedLinkError):
        links.replace_staged(stage, public)
    with pytest.raises(links.UnmanagedLinkError):
        links.replace_staged(public, tmp_path / "new")
    assert public.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    assert links.is_managed(stage)


@windows
def test_windows_remove_deletes_checked_handle(tmp_path, monkeypatch):
    import win32file

    target, public, moved = (tmp_path / name for name in ("target", "entry", "moved"))
    target.write_text("sentinel")
    links.create(public, target, directory=False)
    dispose = win32file.SetFileInformationByHandle
    disposed = []
    def before_delete(handle, kind, value):
        assert kind == win32file.FileDispositionInfo and value
        assert win32file.GetFileInformationByHandleEx(handle, win32file.FileAttributeTagInfo)["ReparseTag"] == stat.IO_REPARSE_TAG_SYMLINK
        with pytest.raises(PermissionError) as busy:
            public.rename(moved)
        assert busy.value.winerror == 32
        disposed.append(handle)
        return dispose(handle, kind, value)
    monkeypatch.setattr(win32file, "SetFileInformationByHandle", before_delete)
    links.remove(public)
    assert len(disposed) == 1 and not os.path.lexists(public)
    assert target.read_text() == "sentinel"


@windows
def test_windows_dangling_directory_symlink_callers(tmp_path, monkeypatch):
    from self_learn import skill_writer

    public, gone, target = (tmp_path / name for name in ("public", "gone", "target"))
    os.symlink(gone, public, target_is_directory=True)
    assert links.read_target(public) == str(gone)
    with monkeypatch.context() as names:
        names.setattr(os, "readlink", lambda path: "\\??\\" + str(gone))
        assert links.read_target(public) == str(gone)
    assert skill_writer._drop_link(public, gone)
    os.symlink(gone, public, target_is_directory=True)
    target.mkdir()
    (target / "SKILL.md").write_text("new skill")
    assert skill_writer._place_link(public, target) == "replaced"
    assert public.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    assert (public / "SKILL.md").read_text() == "new skill"


@windows
def test_windows_published_with_busy_stage(tmp_path, monkeypatch, caplog):
    import pywintypes
    import win32file
    from self_learn import skill_writer

    public, gone, target = (tmp_path / name for name in ("public", "gone", "target"))
    target.mkdir()
    (target / "SKILL.md").write_text("published")
    links.create(public, gone, directory=True)
    def busy(*args):
        raise pywintypes.error(32, "SetFileInformationByHandle", "busy stage")
    with monkeypatch.context() as faults:
        faults.setattr(win32file, "SetFileInformationByHandle", busy)
        assert skill_writer._place_link(public, target) == "replaced"
    stage, = tmp_path.glob(".public.self-learn-*")
    assert str(stage) in caplog.text and "busy stage" in caplog.text
    assert (public / "SKILL.md").read_text() == "published"
    assert links.read_target(stage) == str(target)
    links.remove(stage)
    assert skill_writer._place_link(public, target) == "unchanged"


@windows
@pytest.mark.parametrize("position", ["root", "descendant"])
def test_windows_adoption_refuses_junction(tmp_path, position):
    from self_learn import skill_registration

    root, loose = tmp_path / "skills-root", tmp_path / "loose"
    loose.mkdir()
    skill = loose / "sample"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: sample\ndescription: A test skill.\n---\n")
    assert skill_registration._inspect(root, skill)[0] == "sample"
    other = tmp_path / "elsewhere"
    other.mkdir()
    if position == "root":
        entry = other / "sample"
        links.create(entry, skill, directory=True)
        reason = "loose real directory"
    else:
        entry = skill
        links.create(skill / "subdirectory", other, directory=True)
        reason = "contains symlinks"
    with pytest.raises(skill_registration.RegistrationError, match=reason):
        skill_registration._inspect(root, entry)


@windows
def test_windows_skill_write_and_relink_report_refused_volume(tmp_path, monkeypatch, capsys):
    import json
    import win32api
    import test_skill_write as skills
    from self_learn import cli, skill_writer
    from self_learn.primitives import capabilities

    # ``skill`` is refused in the Windows capture profile until the ledger and
    # canon capabilities are switched on; this test is about the link refusal
    # beneath that gate, so it opens the gate for itself.
    monkeypatch.setitem(capabilities.AVAILABLE, "ledger", True)
    monkeypatch.setitem(capabilities.AVAILABLE, "canon", True)
    env = skills.Env(tmp_path, monkeypatch)
    draft = tmp_path / "draft"
    for rel, contents in skills.draft().items():
        file = draft / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(contents, encoding="utf-8")
    real_info = win32api.GetVolumeInformation
    monkeypatch.setattr(win32api, "GetVolumeInformation", lambda volume: (*real_info(volume)[:4], "ReFS"))
    result = cli.main(["skill", "write", skills.NAME, "--from", str(draft), "--json", "--no-push"])
    assert result == 1
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == skill_writer.KIND_NEEDS_PERSON and not report["ok"]
    assert "could not be linked" in report["problems"][0] and "local NTFS" in report["problems"][0]
    assert env.skill_md().is_file() and not os.path.lexists(env.link())
    outcome, problem = skill_writer.relink(env.home, skills.NAME)
    assert outcome is None and "local NTFS" in problem and repr(str(env.skill_dir())) in problem


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


@posix
def test_posix_adoption_checks_call_path_is_symlink(tmp_path, monkeypatch):
    from self_learn import skill_registration

    loose = tmp_path / "sample"
    loose.mkdir()
    md = loose / "SKILL.md"
    md.write_text("---\nname: sample\ndescription: Local skill.\n---\n")
    original_predicate = links.is_any_link
    original_method = Path.is_symlink
    calls = []
    def check(path):
        with monkeypatch.context() as observing:
            def method(receiver):
                calls.append((path, receiver))
                return original_method(receiver)
            observing.setattr(Path, "is_symlink", method)
            return original_predicate(path)
    monkeypatch.setattr(links, "is_any_link", check)
    assert skill_registration._inspect(tmp_path / "root", loose)[0] == "sample"
    assert calls == [(loose, loose), (md, md)]
