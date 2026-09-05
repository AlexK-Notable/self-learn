"""Fault matrix for ``self_learn.primitives.fsops`` (Sprint 2 M-I, lane
L1 fsops).

Written FIRST, against a module that does not exist yet (measured: this
file failed collection with ``ModuleNotFoundError`` before ``fsops.py``
was written) -- the discipline ``test_bounded_children.py``'s own
docstring names for ``primitives.procs``, applied here.

Each letter below is the fault-matrix item named in the build brief, one
test each, plus a handful of bonus tests (temp-name shape, a plain
success round trip, a crash during the file's own fsync rather than at
``os.replace``) that pin details the matrix implies but does not spell
out letter-by-letter. Every negative test that injects a failure is
SCOPED to the one target path under test (never a global monkeypatch of
``os.replace``/``os.fsync`` for the whole process) -- the sprint-1
lesson this move was explicitly warned to not repeat: a global fake
breaks every OTHER atomic write in the same test process.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from self_learn.primitives import fsops


# --------------------------------------------------------- (a) crash / replace


def test_a_crash_after_temp_write_leaves_no_temp_and_old_content_intact(
    tmp_path, monkeypatch
):
    """A failing ``os.replace``, scoped to THIS target only, must not
    touch the pre-existing file and must not leave the temp file
    behind. Mutation this catches: removing the ``except BaseException:
    tmp.unlink(missing_ok=True); raise`` wrapper -- the glob below would
    then find the leftover temp file."""
    target = tmp_path / "f.txt"
    target.write_text("old content", encoding="utf-8")
    real_replace = os.replace

    def scoped_boom(src, dst):
        if Path(dst) == target:
            raise OSError("simulated crash mid-replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", scoped_boom)
    with pytest.raises(OSError, match="simulated crash mid-replace"):
        fsops.atomic_write(target, "new content", fsync=False)

    assert target.read_text(encoding="utf-8") == "old content"
    assert list(tmp_path.glob(".f.txt.*.tmp")) == []


def test_a2_crash_during_the_files_own_fsync_also_leaves_no_temp_file(
    tmp_path, monkeypatch
):
    """The same cleanup contract, one step earlier: a failure inside the
    file's own ``fsync`` (disk full, a permission error mid-write --
    ``worker._write_window_durable``'s own fold-r1 test uses exactly
    this shape) must be caught by the SAME wrapper, before ``os.replace``
    is ever reached."""
    target = tmp_path / "g.txt"
    target.write_text("old", encoding="utf-8")

    def boom(fd):
        raise OSError("simulated disk-full mid-write")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError, match="simulated disk-full"):
        fsops.atomic_write(target, "new", fsync=True)

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".g.txt.*.tmp")) == []


def test_plain_success_round_trip_leaves_no_temp_file(tmp_path):
    """Positive control for (a)/(a2): the un-faked path actually writes
    the new content and cleans up after itself."""
    target = tmp_path / "h.txt"
    fsops.atomic_write(target, "hello", fsync=True)
    assert target.read_text(encoding="utf-8") == "hello"
    assert list(tmp_path.glob(".h.txt.*.tmp")) == []


# ------------------------------------------------------------- (b)/(c) symlinks


def test_b_symlink_at_path_is_refused_and_link_untouched(tmp_path):
    """Mutation this catches: dropping the ``is_symlink()`` check in
    ``_resolve_target`` -- the write would then silently follow the
    link and this test's ``real.read_text()`` assertion would see the
    new content instead of the old."""
    real = tmp_path / "real.txt"
    real.write_text("real content", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)

    with pytest.raises(fsops.SymlinkRefused) as excinfo:
        fsops.atomic_write(link, "new content")

    assert excinfo.value.path == link
    assert link.is_symlink()
    assert link.resolve() == real
    assert real.read_text(encoding="utf-8") == "real content"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_c_follow_symlinks_true_writes_the_target_and_leaves_the_link(tmp_path):
    """The opposite policy: the REAL file's content changes, the link
    itself (its own inode, what it points at) does not."""
    real = tmp_path / "real.txt"
    real.write_text("old", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)

    fsops.atomic_write(link, "new content", follow_symlinks=True)

    assert link.is_symlink()
    assert link.resolve() == real
    assert real.read_text(encoding="utf-8") == "new content"


# ------------------------------------------------------------------- (d)/(e) mode


def test_d_mode_preserved_from_the_existing_file(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)

    fsops.atomic_write(target, "new", preserve_mode=True)

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_d2_no_existing_file_means_nothing_to_preserve_default_mode_applies(
    tmp_path
):
    """A brand-new file has no prior mode to preserve -- the temp file
    keeps whatever the platform's normal ``open(path, "wb")`` produces
    (umask-masked 0o666), not some fabricated fallback."""
    target = tmp_path / "fresh.txt"
    fsops.atomic_write(target, "new", preserve_mode=True)

    expected = 0o666 & ~_umask()
    assert stat.S_IMODE(target.stat().st_mode) == expected


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


def test_e_explicit_mode_overrides_preserve_mode(tmp_path):
    """Mutation this catches: checking ``preserve_mode`` before the
    explicit ``mode=`` argument -- the assertion below would then see
    0o640 (preserved) instead of 0o755 (explicit)."""
    target = tmp_path / "f.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)

    fsops.atomic_write(target, "new", mode=0o755)

    assert stat.S_IMODE(target.stat().st_mode) == 0o755


# --------------------------------------------------------------- (f) fsync witness


def test_f_fsync_witness_sees_file_fd_then_directory_fd(tmp_path, monkeypatch):
    """Mutation this catches: dropping either fsync call, or swapping
    their order -- the recorded sequence below would then be ``[]``,
    ``[False]``, or ``[True, False]`` instead of ``[False, True]``
    (``False`` = a regular-file fd, ``True`` = a directory fd, checked
    via ``S_ISDIR`` on the live fd rather than trusting call order
    alone)."""
    target = tmp_path / "f.txt"
    calls: list[bool] = []
    real_fsync = os.fsync

    def spy(fd):
        calls.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    fsops.atomic_write(target, "hello", fsync=True)

    assert calls == [False, True], calls


def test_f2_fsync_false_makes_zero_fsync_calls(tmp_path, monkeypatch):
    target = tmp_path / "g.txt"
    calls: list[int] = []
    real_fsync = os.fsync

    def spy(fd):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    fsops.atomic_write(target, "hello", fsync=False)

    assert calls == []
    assert target.read_text(encoding="utf-8") == "hello"


# ------------------------------------------------------------- (g) private_write


def test_g_private_write_yields_0600_and_refuses_symlink(tmp_path):
    target = tmp_path / "token"
    fsops.private_write(target, "secret-token")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text(encoding="utf-8") == "secret-token"

    real = tmp_path / "real-token"
    real.write_text("old-secret", encoding="utf-8")
    real.chmod(0o640)
    link = tmp_path / "link-token"
    link.symlink_to(real)

    with pytest.raises(fsops.SymlinkRefused):
        fsops.private_write(link, "new-secret")
    assert real.read_text(encoding="utf-8") == "old-secret"


def test_g2_private_write_never_preserves_a_widened_existing_mode(tmp_path):
    """A secret's mode must never accidentally widen because the file
    already existed at some other mode (e.g. 0o644 from a pre-migration
    write) -- ``private_write`` always forces 0o600, it never reads the
    existing file's mode the way ``atomic_write(preserve_mode=True)``
    does."""
    target = tmp_path / "token"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)

    fsops.private_write(target, "new-secret")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


# ------------------------------------------------------ (h) str/bytes + encoding


def test_h_str_and_bytes_round_trip_with_encoding(tmp_path):
    utf8_target = tmp_path / "utf8.txt"
    fsops.atomic_write(utf8_target, "héllo", encoding="utf-8")
    assert utf8_target.read_bytes() == "héllo".encode("utf-8")

    bytes_target = tmp_path / "raw.bin"
    fsops.atomic_write(bytes_target, b"\x00\x01\x02\xff")
    assert bytes_target.read_bytes() == b"\x00\x01\x02\xff"

    latin1_target = tmp_path / "latin1.txt"
    fsops.atomic_write(latin1_target, "café", encoding="latin-1")
    assert latin1_target.read_bytes() == "café".encode("latin-1")
    assert latin1_target.read_text(encoding="latin-1") == "café"


# ------------------------------------------------------------ bonus: temp naming


def test_temp_file_name_matches_dot_name_pid_token_tmp_shape(tmp_path, monkeypatch):
    """Pins the exact temp-name shape the build brief specifies --
    ``.<name>.<pid>.<random token>.tmp`` -- since
    ``worker._write_window_durable``'s own glob
    (``f".{window.name}.*.tmp"``) and the sentinel's crash-cleanup test
    both depend on temp names starting ``.<name>.`` and ending
    ``.tmp``, and this proves the MIDDLE segment (pid + token) is what
    the brief pins, not an accident of implementation."""
    target = tmp_path / "f.txt"
    captured: dict[str, str] = {}
    real_replace = os.replace

    def spy(src, dst):
        captured["tmp_name"] = Path(src).name
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    fsops.atomic_write(target, "x")

    assert re.fullmatch(
        rf"\.f\.txt\.{os.getpid()}\.[0-9a-f]{{8}}\.tmp", captured["tmp_name"]
    ), captured["tmp_name"]
