"""Home-floor checks for this package.

On Windows, run from the package root with
`uv run python -m pytest --noconftest -p conftest tests/test_home_floor.py -q`.
This loads the package-root floor while the nested conftest still needs fcntl.
"""

import json
import ntpath
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_windows_floor_follows_home(home_floor_installer, tmp_path):
    original_env = {
        "HOME": "original-home",
        "USERPROFILE": "original-profile",
        "HOMEDRIVE": "Z:",
        "HOMEPATH": "\\original-profile",
    }
    env = original_env.copy()
    original_expanduser = ntpath.expanduser

    with home_floor_installer(
        platform="nt", environ=env, path_module=ntpath, dir=tmp_path
    ) as profile:
        assert profile.is_dir()
        assert profile.parent == tmp_path
        assert Path(env["USERPROFILE"]) == profile
        assert Path(env["HOME"]) == profile
        assert Path(env["HOMEDRIVE"] + env["HOMEPATH"]) == profile
        assert (env["HOMEDRIVE"], env["HOMEPATH"]) == ntpath.splitdrive(str(profile))
        assert ntpath.expanduser("~") == str(profile)

        fake_home = tmp_path / "per-test"
        env["HOME"] = str(fake_home)
        assert ntpath.expanduser("~") == str(fake_home)
        assert ntpath.expanduser("~/child") == str(fake_home) + "/child"
        assert ntpath.expanduser(b"~\\child") == os.fsencode(fake_home) + b"\\child"
        assert ntpath.expanduser(Path("relative")) == "relative"
        env.pop("HOME")
        assert ntpath.expanduser("~") == str(profile)

        marker = profile / "fixture.txt"
        marker.write_text("fixture", encoding="utf-8")
        assert marker.is_file()

    assert env == original_env
    assert ntpath.expanduser is original_expanduser
    assert not profile.exists()


@pytest.mark.parametrize("platform", ["posix", "darwin"])
def test_non_windows_floor_is_a_noop(home_floor_installer, tmp_path, platform):
    env = {"HOME": "original-home", "USERPROFILE": "original-profile"}
    original_env = env.copy()
    original_expanduser = ntpath.expanduser
    marker = tmp_path / "fixture.txt"
    marker.touch()
    assert marker.is_file()

    with home_floor_installer(
        platform=platform, environ=env, path_module=ntpath, dir=tmp_path
    ) as profile:
        assert profile is None
        assert env == original_env
        assert ntpath.expanduser is original_expanduser
        assert set(tmp_path.iterdir()) == {marker}


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows home expansion")
def test_windows_session_home_and_child(windows_session_profile, monkeypatch, tmp_path):
    profile = windows_session_profile
    assert profile is not None and profile.is_dir()
    assert Path.home() == profile
    assert Path(os.path.expanduser("~")) == profile
    target = Path("~/.claude/CLAUDE.md")
    assert target.expanduser() == profile / ".claude" / "CLAUDE.md"

    monkeypatch.setenv("HOME", str(tmp_path))
    assert Path.home() == tmp_path
    assert Path(os.path.expanduser("~")) == tmp_path
    assert Path(ntpath.expanduser("~")) == tmp_path
    assert target.expanduser() == tmp_path / ".claude" / "CLAUDE.md"

    child_home = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import json; from pathlib import Path; print(json.dumps(str(Path.home())))",
        ]
    )
    assert Path(json.loads(child_home)) == profile
