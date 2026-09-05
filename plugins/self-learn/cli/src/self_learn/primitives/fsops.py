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
first) -- so ``mode=0o755`` (the hook script's class, D6) and
``private_write``'s fixed ``mode=0o600`` land with exactly those bits
regardless of umask or of whatever the PREVIOUS file on disk was
mode-bearing. Fold r1, Finding 6: an explicit ``mode=`` is applied by
CREATING the temp file directly at that mode (``os.open``'s own mode
argument), not by ``os.chmod``-ing it afterward -- so there is no
window where the temp file is briefly readable at the umask default
before narrowing (measured: ``private_write``'s temp file was 0o644,
briefly, under its unpredictable random name, before this fix; the
RENAMED target was never observable at anything but 0o600 either way,
since the mode was always applied before ``os.replace``). A
``preserve_mode``-derived mode keeps the original create-then-``chmod``
shape instead, because that value can carry bits (e.g. group-write) the
umask would silently strip at creation time, which ``chmod`` (run
after creation, bypassing umask) does not.

**A new precondition this move adds (fold r1, Finding 8).** Every
migrated write now needs write permission on the parent DIRECTORY, not
just the file -- inherent to any temp-file-plus-rename design (the temp
file is a new directory entry), and NOT true of the bare
``Path.write_text`` every ledger content writer used before this move
(which only needs write permission on an EXISTING file, and can
succeed with a read-only-by-owner-write parent directory, ``0o500``,
because it never creates a new directory entry). A hardened
``$SELF_LEARN_HOME`` or host layout that relied on that -- a writable
file inside a non-writable directory -- worked at ``3fd2279`` and fails
after this landing, with ``PermissionError`` on the temp file's own
path (see Finding 9 just above for what that message now names).

**Hard links (fold r1, Finding 11).** ``os.replace`` retargets the
directory entry to a NEW inode; it does not update any OTHER hard link
to the file being replaced. Every migrated site therefore loses inode
identity across a write, where the old bare ``Path.write_text`` (same-
inode overwrite) preserved it, and a pre-existing hard link to a
migrated file keeps pointing at the OLD content forever after the next
write. D6's ``config.yaml``/``hosts.yaml`` row is justified by "people
symlink config files into dotfile repos" -- the same practice done with
a hard link instead of a symlink is silently broken by this move and is
not a case ``follow_symlinks`` (which is specifically about symlinks)
does anything for. No code change follows from this: preserving inode
identity and being atomic are mutually exclusive by construction, and
`SymlinkRefused`'s whole purpose is to make the symlink case loud, not
silent -- this paragraph exists so the hardlink case is not confused
for being covered by the same guard.

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
during wave 2 and CLOSED in fold r1 (Finding 10).** For a MERGE
install, `_install_staged` writes its own `.install-<rid>.tmp`. Wave 2
briefly did this via `_dump_yaml(verdict.merge_data, tmp)` -- and
`_dump_yaml` itself now calls `atomic_write`. So writing
`.install-<rid>.tmp` itself went through an INNER temp file
(`_temp_path` on a target already named `.install-<rid>.tmp` produces
`..install-<rid>.tmp.<pid>.<token>.tmp` -- two leading dots). Under an
ordinary Python exception that inner temp is unlinked by
`atomic_write`'s own contract, which was STRICTLY SAFER than the old
bare `write_text` (no window where `.install-<rid>.tmp` itself could
appear half-written). But under a SIGKILL landing between the inner
temp's write and its `os.replace` into `.install-<rid>.tmp`, no
exception handler runs, and the orphaned double-dot inner temp did NOT
match `_clean_stale_install_temps`'s `.install-*.tmp` glob (a single
leading dot followed immediately by `install-`; the inner temp's second
character is `.`, not `i`) -- so it would have survived the next run's
pass-1 sweep, a narrower race than before (an uncatchable signal, not
just any crash) but a real regression on the merge-install path (IN8's
own armor-pinned crash point is the outer `os.replace(tmp, dest)` in
`_install_staged`, non-merge, and was never affected).

Fixed, not merely documented: `worker._install_staged`'s merge branch
now serializes via `ledger_ops._dumps_yaml` (the pure-string half of
`_dump_yaml`, split out for exactly this) and writes it with
`tmp.write_text`, the same ONE-STEP shape its non-merge branch two
lines below already uses -- no inner temp file, no second glob pattern
to sweep, no escape hatch added to this primitive's shared contract.
`_dump_yaml` itself (and its one other caller, `worker._run_stage0`,
which writes a merge verdict straight to its own live proposal path,
never to a swept temp name) is unchanged.
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
        if mode is not None:
            # Fold r1, Finding 6: an explicit `mode` (`private_write`'s
            # fixed 0o600, or a caller's own `mode=0o755`) is created on
            # the temp file DIRECTLY, via `os.open`'s own mode argument
            # -- no window where the temp exists at the process umask
            # default before a later `os.chmod` narrows it (measured:
            # `private_write`'s temp was 0o644 before this fix, for the
            # random-named temp file only -- the renamed TARGET was
            # already never observable at anything but 0o600, since the
            # chmod always preceded `os.replace`). This branch is NOT
            # used for a `preserve_mode`-derived `resolved_mode`: that
            # value can carry bits (e.g. group-write) the umask would
            # silently strip at `os.open`-time, which the `os.chmod`
            # below (run after creation, bypassing umask) does not --
            # so the general preserve_mode path keeps the create-then-
            # chmod shape.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            # Fold r2 (r2-2): `os.open`'s own `mode` argument is masked
            # by the process umask (the SAME stripping the comment above
            # already names as the reason `preserve_mode` keeps the
            # create-then-`os.chmod` shape) -- so under umask 0o027 or
            # 0o077, `mode=0o755` landed as 0o750 or 0o700, silently
            # narrower than the pinned D6 policy promises, and the
            # module docstring's "regardless of umask" claim was false
            # for exactly this branch. `os.fchmod` (bypasses umask, same
            # as `os.chmod`) sets the EXACT bits immediately after
            # creation, before any content is written -- keeping
            # Finding 6's no-window property (umask can only REMOVE
            # bits, never add, so the instant between `os.open` and this
            # `fchmod` is never WIDER than `mode`, only ever narrower or
            # equal) while restoring exact-bits-at-any-umask.
            os.fchmod(fd, mode)
            # Fold r2 (r2-3, nit): this branch's `O_EXCL` makes a
            # colliding temp name (same pid AND same `secrets.
            # token_hex(4)` -- unreachable in practice) fail loudly with
            # `FileExistsError`, caught below and re-raised naming
            # `target`. The `else` branch's plain `open(tmp, "wb")`
            # would instead silently TRUNCATE a colliding temp. Neither
            # is wrong (both are equally unreachable), but this is the
            # SAFER of the two -- refuse rather than clobber -- and it
            # is deliberate, not a reason to drop `O_EXCL` from this
            # branch or add it to the other.
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                if fsync:
                    fh.flush()
                    os.fsync(fh.fileno())
        else:
            with open(tmp, "wb") as fh:
                fh.write(payload)
                if fsync:
                    fh.flush()
                    os.fsync(fh.fileno())
            if resolved_mode is not None:
                os.chmod(tmp, resolved_mode)
        os.replace(tmp, target)  # same filesystem -- atomic
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        # Fold r1, Finding 9: an `OSError` raised anywhere in the block
        # above (a permission error opening the temp file, a missing
        # parent directory) carries `.filename == str(tmp)` -- and by
        # the time the caller's `except OSError` handler reads `{exc}`,
        # `tmp` has already been unlinked two lines up, so the message
        # names a path that never existed as far as any caller could
        # observe and cannot `ls`. Retarget `.filename` to `target`
        # (mutating the SAME exception object -- same type, same
        # errno/strerror, same traceback, `raise` bare re-raises it) so
        # the message names the file the caller actually asked to
        # write. Deliberately narrow: only when `.filename` IS the temp
        # path -- a manually-raised `OSError("msg")` in a test has
        # `.filename is None` and is left untouched (`str(exc)` stays
        # exactly "msg"). Fold r2 (r2-4): for an `os.replace(tmp,
        # target)` failure specifically, `.filename` (src) IS the temp
        # path and gets retargeted here same as any other case, while
        # `.filename2` (dst) already read `target` before this handler
        # ever ran -- so BOTH end up naming `target`, and `str(exc)`
        # collapses to ``'<target>' -> '<target>'`` (measured, an
        # `IsADirectoryError` from `os.replace`: `"[Errno 21] Is a
        # directory: '<target>' -> '<target>'"`). Still net-correct (the
        # vanished temp is gone from the message, which is what this
        # finding asked for) -- just a doubled path a reader should not
        # mistake for two different files.
        if exc.filename == str(tmp):
            exc.filename = str(target)
        raise
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
    path: Path | str,
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
    already prove correct). *path* accepts ``str`` too (fold r1, Finding
    5) -- both bodies already do ``Path(path)`` first, and sibling APIs
    in this tree (``compiled.write_entry``, ``config.dump_editable``)
    already type their path parameter ``Path | str``."""
    target = _resolve_target(Path(path), follow_symlinks=follow_symlinks)
    _write_and_replace(
        target,
        data,
        mode=mode,
        preserve_mode=preserve_mode,
        fsync=fsync,
        encoding=encoding,
    )


def private_write(path: Path | str, data: bytes | str) -> None:
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
