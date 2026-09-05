"""primitives.fsops -- ONE atomic-write primitive (Sprint 2 M-I, lane L1
fsops).

Before this move, "temp file + `os.replace`" was reimplemented five
times with five different levels of care (measured at 3fd2279):
``sentinel.hold``'s inline publish (temp + replace + cleanup-on-
exception, no fsync); ``worker._write_window_durable`` (the only one
that fsync'd -- file then directory); ``worker._install_staged`` (temp +
replace, no fsync, and a DELIBERATELY different cleanup contract -- see
"``_install_staged`` is not migrated" below); ``serve.write_heartbeat``
(temp + replace, no fsync, no cleanup); and the UI's
``PaneTranscriptStore._write_meta`` (temp + replace, no fsync, swallows
the error instead of raising). Meanwhile the ledger's actual content
writers -- ``Record.write``, ``ledger_ops._dump_yaml`` (proposals,
project meta), ``hosts.save_hosts``/``_dump_meta``, ``compiled.
write_entry``/``delete_entry``, ``config.dump_editable`` -- used a bare
``Path.write_text``: NOT atomic at all, so a reader (another process, a
crash mid-write, `git status` racing a save) could observe a truncated
or half-written ledger record. This module is the one place both
disciplines (atomicity AND durability) live, so a new writer inherits
the correct behavior by calling in, not by copying a temp-file dance
correctly from memory a sixth time.

**The two entry points.**

``atomic_write(path, data, *, mode=None, preserve_mode=True, fsync=True,
follow_symlinks=False, encoding="utf-8")`` -- the general-purpose writer.
Temp file in the SAME directory as the (possibly symlink-resolved)
target, named ``.<name>.<pid>.<random token>.tmp`` (unique per call, so
two processes racing the same path never collide on the temp name);
write; fsync the file's own fd (when ``fsync``); ``os.replace`` (atomic
on the same filesystem); fsync the PARENT DIRECTORY's fd (when
``fsync`` -- the rename itself is a directory-entry change, and that
change can still be sitting in the page cache, not on disk, until the
directory's own fd is fsync'd; skipping this half is the mistake
``worker._write_window_durable``'s own docstring already named before
this move existed to fix it everywhere at once). ANY exception between
opening the temp file and completing the replace unlinks the temp file
before re-raising -- a crash must never leave ``.foo.1234.a1b2c3d4.tmp``
litter for a later run to trip over, and the pre-existing content at
*path* is untouched (the OLD file is never opened for writing at all;
only ``os.replace`` ever touches it, and that call either fully
succeeds or doesn't touch it).

``private_write(path, data)`` -- ``atomic_write`` fixed to
``mode=0o600``, symlinks refused, always fsync'd: the shape every
secret-bearing file (today: the UI's bearer token) needs and nothing
else needs, so a future secret writer cannot forget the 0600 or the
symlink refusal by calling the general primitive with the wrong
defaults.

**Symlinks.** ``follow_symlinks=False`` (``atomic_write``'s default,
and ``private_write``'s only mode) means a symlink AT ``path`` is
refused outright -- :class:`SymlinkRefused`, naming the path -- before
anything is written; the pre-existing link is left exactly as it was.
``follow_symlinks=True`` resolves the link (:meth:`Path.resolve`) and
writes THROUGH it: the temp file lands beside the link's REAL target,
`os.replace` retargets that real file's inode, and the symlink itself
is never touched (still points at the same path afterward). D6 below
picks per class; the module default is refuse, because a caller that
never thought about symlinks should get a loud, typed failure instead
of an attacker- or accident-controlled write escaping the ledger tree
through a dangling or redirected link. No call site in this ledger
resolves a MULTI-level symlink chain specially -- ``Path.resolve``'s
usual chase-to-the-end semantics apply.

**Mode.** ``preserve_mode=True`` (the default) reads the EXISTING
file's permission bits (``stat().st_mode & 0o777`` -- the standard nine
rwx bits only; setuid/setgid/sticky, ACLs, and extended attributes are
NEVER read, copied, or otherwise handled by this module -- a caller
that needs those must handle them itself) and applies them to the temp
file with an explicit ``os.chmod`` before the rename, so an existing
file's permissions survive a rewrite bit-for-bit regardless of the
process umask. A file that does not exist yet has nothing to preserve,
so the temp file keeps whatever the platform's normal ``open(path,
"wb")`` would have produced (umask-masked 0o666) -- unchanged from what
every migrated call site already did via bare ``Path.write_text``, so a
brand-new record/proposal/meta file's permissions do not change. An
explicit ``mode=`` always wins over ``preserve_mode`` (it is checked
first) and is applied the same way, via ``os.chmod`` on the temp file
before the rename -- so ``mode=0o755`` (the hook script's class, D6)
lands with exactly those bits regardless of umask or of whatever the
PREVIOUS script on disk was mode-bearing.

**D6 -- the per-class write policy** (pinned; every call site's choice
below, not a per-caller judgment call):

    | class                                    | call                                          |
    |-------------------------------------------|----------------------------------------------|
    | UI bearer token                            | ``private_write``                             |
    | ledger records / proposals / meta / compiled | ``atomic_write(preserve_mode=True, fsync=True)``, symlinks refused |
    | ``config.yaml`` / ``hosts.yaml``           | ``atomic_write(..., follow_symlinks=True)`` -- people symlink config files into dotfile repos |
    | hook script                                | ``atomic_write(..., mode=0o755)``             |

    uid/gid are never touched by this module (POSIX rename preserves
    the destination directory's ownership semantics on its own; this
    module has no `os.chown` call anywhere). No xattr handling anywhere
    in this module, for any class -- said once here rather than at
    every call site.

**Why ``_install_staged`` is the one of the five pre-existing temp+
rename helpers this move does NOT migrate.** `worker._install_staged`'s
crash contract is the OPPOSITE of this primitive's: `tests/test_attrib.
py`'s armor-pinned `test_in8_interrupted_install_is_recovered_not_
stalled_forever` part (e) crashes `os.replace` mid-copy and then
asserts the temp file (`.install-<rid>.tmp`) `.exists()` -- it is
supposed to survive, so the NEXT run's pass-1 cleanup
(`_clean_stale_install_temps`) can sweep it, because the install
journal entry for that destination was already durably written (via
`_write_install_journal`, which DOES migrate onto `atomic_write` below)
BEFORE the copy -- the temp file is corroborating evidence for recovery,
not litter. `atomic_write`'s unlink-on-any-exception contract exists
for the opposite reason (a half-written file must never be mistaken for
a real one) and would delete exactly the evidence IN8 requires to
survive. Rather than add an escape hatch to the one shared primitive to
carve out a single caller's inverted contract, `_install_staged` keeps
its own temp file (name UNCHANGED: `.install-<rid>.tmp`, still literal
`os.replace` in `worker.py`, still visible to `tests/test_lock_
invariant.py`'s walker exactly as before) untouched by this move --
documented here, and in `tests/test_raw_write_gate.py`'s allowlist,
rather than silently left off both lists.

**Second-order consequence of migrating `ledger_ops._dump_yaml`, found
while writing the above paragraph, NOT covered by any test.** For a
MERGE install, `_install_staged` writes its own `.install-<rid>.tmp`
via `_dump_yaml(verdict.merge_data, tmp)` rather than `tmp.write_text`
-- and `_dump_yaml` itself now calls `atomic_write` (wave 2, below).
So writing `.install-<rid>.tmp` now itself goes through an INNER
temp file (`_temp_path` on a target already named `.install-<rid>.tmp`
produces `..install-<rid>.tmp.<pid>.<token>.tmp` -- two leading dots).
Under ordinary Python exceptions this inner temp is unlinked by
`atomic_write`'s own contract and `.install-<rid>.tmp` never appears
half-written, which is STRICTLY SAFER than the old bare `write_text`
(which could leave a truncated `.install-<rid>.tmp` on a mid-write
crash). But under a SIGKILL landing between the inner temp's write and
its `os.replace` into `.install-<rid>.tmp`, no exception handler runs,
and the orphaned double-dot inner temp does NOT match `_clean_stale_
install_temps`'s `.install-*.tmp` glob (a single leading dot followed
immediately by `install-`; the inner temp's second character is `.`,
not `i`) -- so it survives the next run's pass-1 sweep. This is a
narrower race than before (it requires a signal an exception handler
cannot catch, not just any crash), on a class of file
(`_clean_stale_install_temps` already treats as disposable, non-git-
tracked scratch), for the merge-install path only (IN8's own armor-
pinned crash point is the outer `os.replace(tmp, dest)` in `_install_
staged`, non-merge, and is unaffected -- confirmed by `test_attrib.py`
staying 47/47). Left as a known, documented gap rather than a fix in
this move: closing it would mean either giving `_dump_yaml` an
`atomic_write` escape hatch for a caller-supplied temp name, or having
`_install_staged` glob-sweep two patterns instead of one -- both are
scope beyond "migrate the two waves without behaviour change beyond
D6's policy."
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


class SymlinkRefused(OSError):
    """*path* is a symlink and the call was not given
    ``follow_symlinks=True``. The pre-existing link is untouched --
    raised before anything is opened for writing."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"refusing to write through a symlink: {path}")
        self.path = path


def _temp_path(target: Path) -> Path:
    """``.<name>.<pid>.<random token>.tmp``, same directory as
    *target* -- same filesystem, so the eventual ``os.replace`` is
    atomic, and unique per call (the random token, `secrets.token_hex`
    -- same generator `sentinel._new_token` already uses) so two
    processes racing the same *target* never collide on the temp
    name."""
    return target.parent / f".{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"


def _resolve_target(path: Path, *, follow_symlinks: bool) -> Path:
    """*path* itself, unless it is a symlink: refused
    (:class:`SymlinkRefused`) when ``follow_symlinks`` is False (the
    default), or resolved to the link's real target when True -- the
    write then lands on that real file, in ITS directory, and the link
    itself is never opened for writing."""
    if path.is_symlink():
        if not follow_symlinks:
            raise SymlinkRefused(path)
        return path.resolve()
    return path


def _write_and_replace(
    target: Path,
    data: bytes | str,
    *,
    mode: int | None,
    preserve_mode: bool,
    fsync: bool,
    encoding: str,
) -> None:
    payload = data if isinstance(data, bytes) else data.encode(encoding)
    resolved_mode = mode
    if resolved_mode is None and preserve_mode:
        try:
            resolved_mode = target.stat().st_mode & 0o777
        except FileNotFoundError:
            resolved_mode = None
    tmp = _temp_path(target)
    try:
        with open(tmp, "wb") as fh:
            fh.write(payload)
            if fsync:
                fh.flush()
                os.fsync(fh.fileno())
        if resolved_mode is not None:
            os.chmod(tmp, resolved_mode)
        os.replace(tmp, target)  # same filesystem -- atomic
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if fsync:
        dir_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)  # the rename itself, durable too
        finally:
            os.close(dir_fd)


def atomic_write(
    path: Path,
    data: bytes | str,
    *,
    mode: int | None = None,
    preserve_mode: bool = True,
    fsync: bool = True,
    follow_symlinks: bool = False,
    encoding: str = "utf-8",
) -> None:
    """Write *data* to *path* atomically (temp file + ``os.replace``)
    and, when ``fsync`` (the default), durably. See the module
    docstring for the full symlink/mode/D6 policy. The caller is
    responsible for the parent directory existing -- this function
    never calls ``mkdir`` (every migrated call site already did its own
    ``parent.mkdir(parents=True, exist_ok=True)``, and a silent mkdir
    here would be one more divergence from what those call sites
    already prove correct)."""
    target = _resolve_target(Path(path), follow_symlinks=follow_symlinks)
    _write_and_replace(
        target,
        data,
        mode=mode,
        preserve_mode=preserve_mode,
        fsync=fsync,
        encoding=encoding,
    )


def private_write(path: Path, data: bytes | str) -> None:
    """``atomic_write`` fixed to the secret-file shape: mode ``0o600``
    always (never preserved from an existing file -- a secret's mode
    must never accidentally widen because the file already existed
    world-unreadable-but-not-0600), symlinks always refused, always
    fsync'd."""
    target = _resolve_target(Path(path), follow_symlinks=False)
    _write_and_replace(
        target,
        data,
        mode=0o600,
        preserve_mode=False,
        fsync=True,
        encoding="utf-8",
    )
