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
    | host canon (Sprint 3 M-I wave 3: CLAUDE.md paths-block/pointer-line/managed-section/reference-block writes, the plain-host marker, and the new-skill scaffold's plugin.json/SKILL.md/marketplace.json) | ``atomic_write(..., follow_symlinks=True)`` -- the read side already resolves symlinks (`compilers.surface_names_target` compares `resolve()` to `resolve()`) and `install.sh` itself symlinks skills into `~/.claude/skills`; a writer that refused what the reader accepts would break real hosts. Subject to the parent-directory-write precondition above (fold r1, Finding 8) same as every other class: a host repo with a writable file inside a non-writable directory could rely on the old bare ``write_text`` and will now fail with ``PermissionError`` |
    | external tool's file (Claude Code's own auto-memory index) | ``atomic_write(..., follow_symlinks=False, preserve_mode=True, fsync=True)`` -- REFUSE a symlink loudly; the file is not ours to write through a link (a DANGLING symlink there is skipped by the caller's own pre-existing ``is_file()`` guard before this call is ever reached -- ``SymlinkRefused`` fires only for a symlink to an EXISTING file) |
    | UI derived/regenerable cache (compiled doctrine) | ``atomic_write(path, data)`` -- defaults; regenerable content, no special case |

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
its own temp file (name UNCHANGED: `.install-<rid>.tmp`, still one
`os.replace` through `fsops.replace_staged`, still visible to `tests/test_lock_
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
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import IO, Any, Literal, Protocol


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


class Directory(Protocol):
    """Operations relative to the directory held by safe_directory."""

    def entries(self) -> AbstractContextManager[Iterator[os.DirEntry[str]]]: ...

    def unlink(self, name: str) -> None: ...


def _backend():
    if os.name == "nt":
        # A foreign interpreter cannot load the native Win32 extension modules.
        import sys
        if sys.platform != "win32":
            raise NotImplementedError("native Windows file operations require Windows")
        from . import _fsops_windows

        return _fsops_windows
    from . import _fsops_posix

    return _fsops_posix


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
    _backend().atomic_write(path, data, mode=mode, preserve_mode=preserve_mode, fsync=fsync,
                            follow_symlinks=follow_symlinks, encoding=encoding)


def private_write(path: Path | str, data: bytes | str) -> None:
    """``atomic_write`` fixed to the secret-file shape: mode ``0o600``
    always (never preserved from an existing file -- a secret's mode
    must never accidentally widen because the file already existed
    world-unreadable-but-not-0600), symlinks always refused, always
    fsync'd."""
    _backend().private_write(path, data)


def replace_staged(src: Path | str, dst: Path | str, *, method: Literal["os", "path"] = "os") -> None:
    _backend().replace_staged(src, dst, method=method)


def flush_file(fd: int) -> None:
    _backend().flush_file(fd)


def sync_parent(path: Path) -> None:
    _backend().sync_parent(path)


def sync_file_and_parent(path: Path) -> None:
    _backend().sync_file_and_parent(path)


def ensure_private_parent(path: Path) -> None:
    _backend().ensure_private_parent(path)


def open_private_new(path: Path) -> int:
    return _backend().open_private_new(path)


def private_temp(parent: Path, *, prefix: str, suffix: str) -> tuple[int, str]:
    return _backend().private_temp(parent, prefix=prefix, suffix=suffix)


def reopenable_text(text: str, *, prefix: str, suffix: str) -> AbstractContextManager[Path]:
    return _backend().reopenable_text(text, prefix=prefix, suffix=suffix)


def open_for_mode(path: Path, kind: Literal["x", "xb", "a"], *,
                  mode: int | None = None, encoding: str | None = None) -> IO[Any]:
    return _backend().open_for_mode(path, kind, mode=mode, encoding=encoding)


def finish_mode(path: Path, mode: int, *, method: Literal["path", "os"] = "path") -> None:
    _backend().finish_mode(path, mode, method=method)


def open_regular(path: Path | str, *, policy: Literal["premise", "provenance"]) -> int:
    return _backend().open_regular(path, policy=policy)


def safe_directory(path: Path) -> AbstractContextManager[Directory]:
    return _backend().safe_directory(path)
