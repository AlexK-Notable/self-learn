"""Bounded synchronous child-process execution (T3/T7 M-G, sprint 1 plan
v2 §2 — "primitives.procs.run_bounded"; P3 timeout gate).

A bare ``subprocess.run(...)`` with no ``timeout=`` is why "blocking with
a sane timeout" was fiction across this codebase before this move
(``gitops.py``'s own module docstring names the same failure, probed
2026-07-16: 120s and counting on a wedged push). This module gives every
NEW bounded-child call site one function that cannot make that mistake:
``timeout`` is a required keyword, and on expiry the child's WHOLE
process group is killed — not just the immediate child — so a hang
cannot survive by handing its work to a grandchild the immediate `kill`
never touches.

Nothing here changes an ALREADY-bounded call (e.g. ``gitops._git``'s own
``GIT_LOCAL_TIMEOUT``); this is the seam new call sites route through,
and the one the P3 scanner (``tests/test_bounded_children.py``) checks
every ``subprocess.run``/``Popen``/``.communicate()`` site in ``src``
against.

S-165: this module is the facade. The operating-system code lives in a
backend selected on first use (``_procs_posix`` on Linux and macOS), so
importing a caller never loads a POSIX-only module.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class BoundedTimeout(subprocess.TimeoutExpired):
    """``argv`` exceeded ``timeout`` seconds and was killed — the WHOLE
    process group (``start_new_session=True`` + ``os.killpg``), not just
    the immediate child, so a hang cannot outlive the deadline by
    orphaning a descendant onto pytest/init as its new parent.

    Subclasses :class:`subprocess.TimeoutExpired` on purpose: an existing
    ``except subprocess.TimeoutExpired`` elsewhere in the codebase (e.g.
    ``hosts.py``'s already-bounded git probes) still catches this, and
    the stdlib class's own ``__str__`` already names the command and the
    timeout — nothing to reimplement."""


class OutputLimitExceeded(RuntimeError):
    """Combined stdout/stderr exceeded the caller's byte budget."""


def _backend():
    if os.name == "nt":
        from . import _procs_windows

        return _procs_windows
    from . import _procs_posix

    return _procs_posix


def run_bounded(
    argv: Sequence[str],
    *,
    timeout: float,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    input: str | bytes | None = None,
    check: bool = False,
    binary: bool = False,
    max_output_bytes: int | None = None,
) -> subprocess.CompletedProcess:
    """``subprocess.run(argv, ...)``, bounded. ``timeout`` is keyword-only
    and has no default — a caller must choose one, the whole point of
    this primitive existing.

    On timeout: the child's process group (it is started with
    ``start_new_session=True``, so it always has one of its own) is sent
    ``SIGKILL`` via :func:`os.killpg` — every descendant that never
    escaped into its OWN session dies with it — and
    :class:`BoundedTimeout` is raised naming ``argv``, never the bare
    :class:`subprocess.TimeoutExpired`.

    ``input``/``check`` mirror :func:`subprocess.run`'s own — ``check``
    raises :class:`subprocess.CalledProcessError` on a non-zero exit,
    same as there; a non-zero exit that is NOT ``check``ed is returned,
    not raised, same as there too.

    ``binary``: when true, ``stdout``/``stderr`` come back as ``bytes`` even
    when ``input`` is ``None`` — the default infers text-vs-bytes from
    ``input`` alone, which can never produce bytes output for a caller
    that passes no stdin. A byte-exact caller (e.g. ``intents._head_show``,
    comparing output against a recorded sha256) sets this instead of
    relying on that inference. ``input`` must then be ``bytes`` or
    ``None`` — a ``str`` under ``binary=True`` raises :class:`ValueError`
    (mixing a text ``input`` with a forced-bytes child is not a shape any
    caller wants; failing loudly beats a raw stdlib ``TypeError`` out of
    ``Popen``).

    ``max_output_bytes`` optionally bounds combined stdout/stderr capture.
    It requires ``binary=True`` and no stdin; exceeding it kills the whole
    process group just like timeout, then raises :class:`OutputLimitExceeded`.
    """
    return _backend().run_bounded(
        argv, timeout=timeout, cwd=cwd, env=env, input=input, check=check,
        binary=binary, max_output_bytes=max_output_bytes,
    )


def run_command(argv: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return _backend().run_command(argv, timeout=timeout)


def pid_alive(pid: int) -> bool:
    return _backend().pid_alive(pid)


@dataclass(frozen=True)
class ProcessIdentity:
    """Enough to tell, later, whether a PID still names the same process.

    Compare two identities with ``==``; never compare PIDs alone.

    ``image``: the program. POSIX: the first NUL-separated field of
    ``/proc/<pid>/cmdline`` decoded as UTF-8 with ``"replace"`` (exactly
    what ``sdksession/children.py`` reads today). Windows: the full image
    path from ``QueryFullProcessImageNameW``.

    ``created``: Windows: the creation time from ``GetProcessTimes`` as the
    raw FILETIME, 100-nanosecond ticks since 1601-01-01 UTC, read without
    pywin32 (whose conversion rounds to the millisecond). POSIX: ``None``
    (today's check reads no start time).

    Accepted limitation: the creation time is wall-clock time. Windows does
    not promise successive processes distinct or increasing stamps, so two
    processes with the same PID, image and creation time compare equal, and a
    clock set back can make a later process look older than an earlier one.
    No boot-scoped process sequence number is available to settle it. Rule
    for callers: a saved identity is trusted only if
    :func:`identity_predates_boot` is false for it; an identity from before
    the current boot is never used to decide a kill.

    ``cmdline``: POSIX: the raw ``/proc/<pid>/cmdline`` bytes, so a caller
    can keep today's exact parsing. Windows: ``None``.
    """

    image: str
    created: int | None
    cmdline: bytes | None = None


def process_identity(pid: int) -> ProcessIdentity | None:
    """The identity of *pid*, or ``None`` when no such process can be read
    (POSIX: the ``/proc`` read raised ``OSError``; Windows: the PID does not
    exist, the process cannot be opened for limited query, or it has
    exited). See :class:`ProcessIdentity` for what equality can and cannot
    prove, and :func:`identity_predates_boot` for when a saved identity may
    be trusted."""
    return _backend().process_identity(pid)


def identity_predates_boot(identity: ProcessIdentity) -> bool:
    """Whether *identity* was created before the current boot (Windows: its
    creation time is no later than boot time plus one second, boot time being
    the precise clock minus the uptime counter). Such an identity cannot be
    trusted: its PID, image and creation time can all recur after a reboot or
    a clock change. POSIX: always false (no creation time is recorded)."""
    return _backend().identity_predates_boot(identity)


def contain_child(pid: int, *, expect: ProcessIdentity | None = None) -> Any:
    """Contain an already-running child that someone else spawned.

    Windows: assign *pid* to a fresh kill-on-close job object (breakaway
    allowed, as a new session escapes ``killpg`` on POSIX), then adopt its
    descendants that were spawned before the assignment and can be proved
    to be its own (what the sweep sees and rejects is reported in the
    handle's ``left_out`` and ``uncovered``; an empty report does not prove
    every descendant was found). The returned handle keeps the job alive: dropping it,
    or this process dying, kills everything in the job. ``None`` when the
    process does not exist or has exited, or when *expect* is given and the
    process opened is not that identity (checked on the same open handle
    that is then assigned). If the call is interrupted after the child may be
    in the job, the exception that leaves this call carries the handle as
    ``contained_child`` (holding every member adopted so far); terminate it
    or keep it.

    Accepted limitations, and the caller rules that go with them. (1) A
    child started with ``CREATE_BREAKAWAY_FROM_JOB`` before the assignment,
    or while the assignment call runs, can be indistinguishable from an
    ordinary child and is then adopted and killed with the rest. So contain
    only the SDK's Claude Code child, never a process tree in which
    self-learn itself launched detached work. (2) Parentage is proved by
    creation times (see :class:`ProcessIdentity`); a clock set back can make
    an unrelated process look like a child. Pass *expect* only with an
    identity for which :func:`identity_predates_boot` is false.

    POSIX: returns a handle carrying *pid*, reading nothing but our own PID
    and process group (plus ``/proc`` when *expect* is given); the process
    group of *pid* is read with ``os.getpgid`` at kill time, exactly as
    ``sdksession/teardown.kill_child`` does today. ``None`` for a PID that
    is not positive, is this process, or is this process's group leader.
    """
    return _backend().contain_child(pid, expect=expect)


def terminate_contained(handle: Any) -> None:
    """Kill what *handle* contains.

    Windows: terminate the job, wait (bounded) until it is empty, then
    release it; acts on the job handle, never on a PID. Raises
    :class:`TimeoutError` if the job is still not empty at the bound.
    Calling it again is a no-op.

    POSIX: the ``getpgid``/``killpg``/``SIGKILL`` body of
    ``sdksession/teardown.kill_child``, copied exactly, swallowing the same
    ``ProcessLookupError`` and ``PermissionError``; a ``None`` handle or one
    whose PID ``contain_child`` would refuse does nothing.
    """
    _backend().terminate_contained(handle)


def contain_self() -> bool:
    """Make this process's descendants die with it, whatever kills it.

    Windows: put this process in a kill-on-close job with breakaway
    allowed (a child started with ``CREATE_BREAKAWAY_FROM_JOB`` still
    escapes). Call it at start-up, before anything spawns: children started
    earlier stay outside the job. Nests under a job the process is already
    in. The job handle is never closed by Python, so a normal exit keeps its
    exit status; the kernel closes it after the process ends. Safe to call
    again: later calls return ``True`` without a new job. Returns ``True``.

    POSIX: does nothing and returns ``False`` (descendants are handled by
    process groups there).
    """
    return _backend().contain_self()


# S-NEXT-w7-procs: background work that must outlive the command that started
# it, and asyncio children whose whole tree the caller owns.

#: The environment variable through which a child started by
#: :func:`async_owned_child` on Windows learns the name of its stop event (a
#: manual-reset event in the session's ``Local\`` namespace; the soft stop sets
#: it). POSIX never sets it: the soft stop there is ``SIGTERM``.
STOP_EVENT_ENV = "SELF_LEARN_STOP_EVENT"


@dataclass(frozen=True)
class DetachedChild:
    """What :func:`spawn_detached` started.

    ``broke_away``: Windows only. ``True`` when ``CREATE_BREAKAWAY_FROM_JOB``
    was accepted, which takes the child out of the launcher's own job only
    (measured: a job it is nested in keeps the child even when that outer job
    forbids breakaway); ``False`` when the launcher's job refused breakaway and
    the child was started inside it instead; ``None`` when the launcher is in
    no job, and always on POSIX.

    ``in_job``: Windows only. Whether the child, read on its own handle right
    after it started, is in any job. A child still in a job lives only as long
    as that job: a kill-on-close job kills it when the job's last handle
    closes, usually when the launcher or whatever made the job dies. Always
    ``False`` on POSIX."""

    pid: int
    broke_away: bool | None = None
    in_job: bool = False


def spawn_detached(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    log_path: Any = None,
) -> DetachedChild:
    """Start *argv* so that it outlives this process, and return at once.

    POSIX: the ``subprocess.Popen(..., start_new_session=True)`` the three
    background launch sites make today, copied argument for argument. With
    *log_path*: ``worker._spawn_window`` and ``miner._spawn_run`` (the log
    opened ``"a"`` as UTF-8 text, ``stdout`` to it, ``stderr=STDOUT``, stdin
    inherited); without it: ``overseer.notify.send`` (stdin, stdout and
    stderr all ``DEVNULL``).

    Windows: ``CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`` (the child gets a
    console of its own with no window, so the console programs it runs share
    that console instead of each opening a window), trying
    ``CREATE_BREAKAWAY_FROM_JOB`` first when this process is in a job and
    starting it without breakaway when the job refuses (error 5). Standard
    handles are explicit (stdin ``NUL``; stdout and stderr the log, opened for
    appending only, or ``NUL``) and they are the only handles the child
    inherits. A bare program name is looked up on ``PATH`` only; ``.bat`` and
    ``.cmd`` files are refused. See :class:`DetachedChild` for what
    ``broke_away`` and ``in_job`` report.
    """
    return _backend().spawn_detached(argv, cwd=cwd, env=env, log_path=log_path)


def breakaway_allowed() -> bool | None:
    """Whether a child started now with :func:`spawn_detached` would be in no
    job at all (for a ``doctor`` row).

    Windows: ``True`` when this process is in no job, or a trial child started
    suspended with ``CREATE_BREAKAWAY_FROM_JOB`` was accepted and is in no job
    (it is killed before it runs); ``False`` when the trial was refused with
    error 5, or was accepted but is still in a job this process's job is nested
    in; ``None`` when the answer could not be read. POSIX: ``None`` (there are
    no jobs to leave)."""
    return _backend().breakaway_allowed()


async def async_owned_child(
    *argv: str,
    env: Mapping[str, str] | None = None,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
) -> Any:
    """Start *argv* as an ``asyncio.subprocess.Process`` whose whole tree the
    caller owns, and return that process.

    POSIX: ``asyncio.create_subprocess_exec(*argv, env=..., stdin=...,
    stdout=..., stderr=..., start_new_session=True)``, the call the web UI's
    ``runner.RealRunner._spawn`` and ``ask_runner.RealAskRunner`` make today
    (``stdin=None`` is ``create_subprocess_exec``'s own default, which is what
    ``_spawn`` gets by not passing it).

    Windows: the child is started suspended in a new process group, put in a
    kill-on-close job of its own (breakaway allowed, the job ``contain_child``
    uses), and only then resumed, so every descendant it starts is in the job
    unless it breaks away on purpose. Its environment carries
    :data:`STOP_EVENT_ENV`. When this process has a console the child shares
    it; otherwise it gets a console of its own without a window. Needs the
    Proactor event loop (the default on Windows): under a Selector loop
    ``asyncio`` raises :class:`NotImplementedError` and nothing is started.
    Stop it with :func:`stop_owned` or :func:`terminate_owned`; release it
    with :func:`release_owned` (dropping the process object does the same).
    """
    return await _backend().async_owned_child(*argv, env=env, stdin=stdin, stdout=stdout, stderr=stderr)


def stop_owned(proc: Any, *, hard: bool) -> bool:
    """Send one stop to the tree *proc* leads. ``False`` when there was nothing
    left to stop.

    POSIX: the web UI's ``_signal_group`` copied: ``os.killpg`` with
    ``SIGTERM`` (soft) or ``SIGKILL`` (hard) when ``proc.pid`` leads its own
    process group, else ``os.kill`` of that one PID; ``False`` on
    ``ProcessLookupError``.

    Windows, for a child of :func:`async_owned_child`: ``False`` when its job is
    empty. Soft: set its stop event and, when it shares this process's console
    and is still running, send ``CTRL_BREAK_EVENT`` to its process group (a
    Python child sees ``SIGBREAK``; with no handler it exits with
    ``0xC000013A``). A child with a console of its own receives no console
    event; only the stop event reaches it. Hard: terminate the job (exit
    status 1 for every member). For any other process: terminate that one
    process, soft or hard, since no soft channel to it exists."""
    return _backend().stop_owned(proc, hard=hard)


async def terminate_owned(proc: Any, *, kill_grace: float, wait_after_lost_kill: bool = False) -> None:
    """Soft stop, wait up to *kill_grace* seconds, hard stop, wait up to
    *kill_grace* again. Never raises for a process that is already gone.

    POSIX: ``runner._terminate_then_kill`` copied: nothing when
    ``proc.returncode`` is set; return when the soft stop finds nothing; return
    when the wait succeeds; return when the hard stop finds nothing, unless
    *wait_after_lost_kill* is true, which makes it wait once more as
    ``ask_runner.RealAskRunner._terminate`` does.

    Windows: the same steps, and then, whether or not the child had already
    exited, whatever is left in its job is terminated and waited for (bounded
    by *kill_grace*), so a grandchild holding a pipe open cannot outlive it."""
    await _backend().terminate_owned(proc, kill_grace=kill_grace, wait_after_lost_kill=wait_after_lost_kill)


def release_owned(proc: Any) -> None:
    """Let go of *proc*'s tree. Windows: close its job, which kills whatever
    is still in it, and its stop event; calling it again does nothing. POSIX:
    does nothing (the process group needs no handle)."""
    _backend().release_owned(proc)
