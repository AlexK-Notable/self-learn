"""Windows profile isolation for both package-root conftests."""

import atexit
import ntpath
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def home_floor(*, platform=os.name, environ=os.environ, path_module=ntpath, dir=None):
    if platform != "nt":
        yield None
        return

    with tempfile.TemporaryDirectory(
        prefix="self-learn-test-profile-", dir=dir, ignore_cleanup_errors=True
    ) as scratch, pytest.MonkeyPatch.context() as patch:
        drive, homepath = path_module.splitdrive(scratch)
        patch.setitem(environ, "USERPROFILE", scratch)
        patch.setitem(environ, "HOMEDRIVE", drive)
        patch.setitem(environ, "HOMEPATH", homepath)
        patch.setitem(environ, "HOME", scratch)

        original_expanduser = path_module.expanduser

        def expanduser(path):
            path = os.fspath(path)
            home = environ.get("HOME") or scratch
            if isinstance(path, bytes):
                if path == b"~" or path.startswith((b"~/", b"~\\")):
                    return os.fsencode(home) + path[1:]
            elif path == "~" or path.startswith(("~/", "~\\")):
                return home + path[1:]
            return original_expanduser(path)

        # On Windows, os.path and pathlib use ntpath. Children inherit the
        # session USERPROFILE and drive/path, so native Python expands ~ there
        # even if they inherit a per-test HOME too. Both locations are scratch.
        patch.setattr(path_module, "expanduser", expanduser)
        yield Path(scratch)


def start_session_home_floor():
    floor = home_floor()
    profile = floor.__enter__()
    # Early conftest import failures can occur before pytest_configure runs.
    atexit.register(floor.__exit__, None, None, None)

    def close():
        atexit.unregister(floor.__exit__)
        floor.__exit__(None, None, None)

    return profile, close
