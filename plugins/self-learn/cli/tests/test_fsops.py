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
out letter-by-letter. Every negative test that injects a failure on a
call taking a PATH argument is scoped to the one target path under test
(never a global monkeypatch of ``os.replace`` for the whole process) --
the sprint-1 lesson this move was explicitly warned to not repeat: a
global fake breaks every OTHER atomic write in the same test process.

Fold r1, Finding 3 (corrected claim): the one exception is ``test_a2``,
which monkeypatches the GLOBAL ``os.fsync`` -- unavoidable, since
``fsync`` takes a file descriptor, not a path, so there is no per-path
scoping available to it the way there is for ``os.replace``/``open``.
Harmless in this suite (one write per test, undone by ``monkeypatch``'s
own teardown before the next test runs), but do not extend the "always
scoped" claim above to that one test when adding a fifth fault case.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from self_learn import config, worker
from self_learn.hosts import Hosts, load_hosts, save_hosts
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


def test_e2_explicit_mode_lands_exactly_regardless_of_umask(tmp_path):
    """Fold r2 (r2-2): Finding 6's fix created the temp via `os.open(...,
    mode)`, whose `mode` argument the process umask masks -- so under
    umask 0o077, `mode=0o755` landed as 0o700, silently narrower than
    D6's pinned policy and the module docstring's own "regardless of
    umask" claim. `os.fchmod` after the `os.open` (bypasses umask, same
    as `os.chmod`) is the fix -- this pins it under a tighter-than-
    ambient umask than `test_e`/the rest of the suite ever exercises.
    Mutation this catches: deleting the `os.fchmod` call reintroduces
    the umask-stripped 0o700/0o600-narrowed-further failure this test
    would then see instead of 0o755/0o600."""
    old_umask = os.umask(0o077)
    try:
        target = tmp_path / "f.txt"
        fsops.atomic_write(target, "new", mode=0o755)
        assert stat.S_IMODE(target.stat().st_mode) == 0o755

        secret = tmp_path / "token"
        fsops.private_write(secret, "s")
        # private_write's 0o600 has no group/other bits for ANY umask to
        # strip -- included as a companion assertion, not the load-
        # bearing half of this test (0o755 is, since 0o077 has bits
        # that overlap 0o755's group/other bits and 0o600 has none).
        assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    finally:
        os.umask(old_umask)


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


# ============================================== fold r1, Finding 7: D6's
# `follow_symlinks=True` call sites (hosts.yaml / config.yaml) had ZERO
# test coverage -- the one deliberate inversion of this primitive's safe
# default. Mutation witness for both: dropping `follow_symlinks=True`
# from the migrated call turns this into `SymlinkRefused`, reddening.


def test_save_hosts_follows_a_symlinked_hosts_yaml(tmp_path):
    """D6: hosts.yaml is a config-file class (people symlink config
    files into dotfile repos) -- `save_hosts` must FOLLOW the link, not
    refuse it. Mutation this catches: dropping `follow_symlinks=True`
    from `save_hosts`'s `fsops.atomic_write` call raises
    `fsops.SymlinkRefused` here instead of returning."""
    home = tmp_path / "ledger"
    home.mkdir()
    real_dir = tmp_path / "dotfiles"
    real_dir.mkdir()
    real = real_dir / "hosts.yaml"
    real.write_text("skills_root: null\nprojects: []\n", encoding="utf-8")
    link = home / "hosts.yaml"
    link.symlink_to(real)

    marker_root = tmp_path / "skills-root-marker"
    save_hosts(home, Hosts(skills_root=marker_root, projects=[]))

    # the link survives, unretargeted...
    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    # ...and the REAL file was rewritten (not the link replaced with a
    # plain file, and not a no-op against stale content).
    assert load_hosts(home).skills_root == marker_root
    assert "skills-root-marker" in real.read_text(encoding="utf-8")
    # the write's temp file landed beside the REAL target's directory,
    # per `fsops._resolve_target`'s `follow_symlinks=True` contract --
    # never beside the link.
    assert list(home.glob(".hosts.yaml.*.tmp")) == []
    assert list(real_dir.glob(".hosts.yaml.*.tmp")) == []  # already replaced


def test_dump_editable_follows_a_symlinked_config_yaml(tmp_path):
    """D6: config.yaml is the same config-file class as hosts.yaml --
    `dump_editable` must FOLLOW the link. Mutation this catches:
    dropping `follow_symlinks=True` from `dump_editable`'s
    `fsops.atomic_write` call raises `fsops.SymlinkRefused` here instead
    of returning."""
    home = tmp_path / "ledger"
    home.mkdir()
    real_dir = tmp_path / "dotfiles"
    real_dir.mkdir()
    real = real_dir / "config.yaml"
    real.write_text("some_key: old-value\n", encoding="utf-8")
    link = home / "config.yaml"
    link.symlink_to(real)

    data = config.load_editable(home)  # reads THROUGH the link
    data["some_key"] = "new-value"
    config.dump_editable(home, data)

    assert link.is_symlink()
    assert Path(os.readlink(link)) == real
    assert "new-value" in real.read_text(encoding="utf-8")
    assert "old-value" not in real.read_text(encoding="utf-8")


# ============================================== fold r2, r2-1: a ratchet
# against re-nesting `_dump_yaml` (now `fsops.atomic_write`) inside
# `worker._install_staged`'s merge branch -- fold r1's Finding 10 closure
# had only a one-time probe as evidence, not a standing test. This drives
# the REAL `_install_staged` on a merge verdict with a `fsops._temp_path`
# spy and asserts fsops is never called for the DEST's own
# `.install-<rid>.tmp` write specifically (`_write_install_journal` --
# unrelated, a DIFFERENT file -- legitimately calls `fsops.atomic_write`
# too, and its own `.worker.install-journal.*.tmp` name is expected and
# excluded below by construction: it never contains "install-merged").
# Mutation this catches: reverting the merge branch to `_dump_yaml
# (verdict.merge_data, tmp)` (the exact wave-2 shape fold r1 removed)
# makes `_temp_path` fire an EXTRA time for a name containing
# "install-merged" and starting with the double-dot `..install-` shape
# -- caught by the assertion below, not by any existing test (r2's own
# gate measured 159 passed across test_attrib.py/test_worker.py/
# test_repair.py/test_raw_write_gate.py with the re-nesting
# reintroduced).
def test_install_staged_merge_branch_never_nests_an_inner_fsops_temp(tmp_path):
    dest_dir = tmp_path / "proposals"
    dest_dir.mkdir()
    dest = dest_dir / "merged.yaml"

    temp_names: list[str] = []
    real_temp_path = fsops._temp_path

    def spy_temp_path(target):
        out = real_temp_path(target)
        temp_names.append(out.name)
        return out

    verdict = worker._Verdict(
        error=None,
        phi=True,
        record_sha_matches=True,
        is_hook=False,
        is_merge=True,
        name="merged",
        bucket=None,
        dest=dest,
        merge_data={"cluster_id": "c1", "record_shas": {}},
    )

    fsops._temp_path = spy_temp_path
    try:
        worker._install_staged(tmp_path, verdict, dest_dir / "unused.yaml", {})
    finally:
        fsops._temp_path = real_temp_path

    inner = [n for n in temp_names if "install-merged" in n]
    assert inner == [], (
        "fsops._temp_path was called for the merge install's own temp -- "
        f"the merge branch re-nested an atomic_write inside itself: {inner} "
        f"(all fsops temps this call handed out: {temp_names})"
    )
    assert dest.is_file()
    assert "c1" in dest.read_text(encoding="utf-8")
    # the SWEEPABLE `.install-*` outer name never lingers after a clean run
    assert list(dest_dir.glob(".install-*")) == []
