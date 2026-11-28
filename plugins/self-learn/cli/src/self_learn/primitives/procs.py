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

from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from ._detached import DetachedChild, OutputTruncated  # noqa: F401


def __getattr__(name: str) -> Any:
    # The result types live in a small module imported on first use, so
    # importing this module does no more work than it did before they existed;
    # the import lock publishes exactly one class.
    if name in ("DetachedChild", "OutputTruncated"):
        from . import _detached

        value = globals()[name] = getattr(_detached, name)
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def spawn_detached(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    log_path: Any = None,
) -> DetachedChild:
    """Start *argv* so that it outlives this process, and return at once a
    ``DetachedChild``.

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
    starting it without breakaway when that attempt fails with error 5 (a
    second failure carries the first as a note). Standard handles are explicit
    (stdin ``NUL``; stdout and stderr the log, opened for appending only, or
    ``NUL``) and they are the only handles the child inherits; the launch holds
    the lock every spawn of this backend shares, so no concurrent launch here
    inherits them either. A bare program name is looked up on ``PATH`` only;
    ``.bat`` and ``.cmd`` files are refused. Once the child exists this call
    does not raise. See ``DetachedChild`` for what it reports.
    """
    return _backend().spawn_detached(argv, cwd=cwd, env=env, log_path=log_path)


def breakaway_allowed() -> bool | None:
    """Whether a child started now with :func:`spawn_detached` would be in no
    job at all (for a ``doctor`` row).

    Windows: ``True`` when this process is in no job, or a trial child started
    suspended with ``CREATE_BREAKAWAY_FROM_JOB`` is in no job; ``False`` when
    that trial is still in a job, or when it is refused with error 5 twice,
    with a trial without the flag starting inside a job in between; ``None``
    when the answer cannot be supported (any other failure or combination, or
    a trial whose end could not be confirmed). Trial children never run: each
    is put in a kill-on-close job of its own as soon as its membership is
    read, so it dies with this process if killing it fails. POSIX: ``None``
    (there are no jobs).
    """
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

    Windows: needs an event loop that can run subprocesses (the Proactor loop,
    the default); any other raises :class:`NotImplementedError` before
    anything is changed. Then it puts this process in its kill-on-close self
    job (:func:`contain_self`; a side effect callers must know: from then on,
    this process's children die with it unless they break away, as
    :func:`spawn_detached` does), and checks that this process really is in
    it. The child is started suspended in a new process group, inside that
    self job (so a child suspended at the moment this process dies dies too),
    put in a kill-on-close job of its own (breakaway allowed, the job
    ``contain_child`` uses), and only then is its first thread resumed, once:
    every thread listed for it must be readable, the earliest created must be
    the only one with that creation time, and its previous suspend count must
    be 1, or the child is killed and reaped and the call raises. Every
    descendant it starts is in the job unless it breaks away on purpose. When
    this process has a console the child shares it; otherwise it gets one of
    its own without a window. Creating the process (where CPython makes the
    standard handles inheritable, calls CreateProcess and closes them again)
    holds the lock every spawn of this backend shares, on every Python
    version, so no concurrent launch inherits this child's pipe ends.
    Creation and the hand-over happen in the caller's own task with nothing
    awaited between them: a cancellation either lands inside the creation,
    which then kills and reaps the child, or after the resumed child has been
    handed over. Stop it with :func:`stop_owned` or :func:`terminate_owned`;
    release it with :func:`release_owned` (dropping the process object does
    the same).
    """
    return await _backend().async_owned_child(*argv, env=env, stdin=stdin, stdout=stdout, stderr=stderr)


def stop_owned(proc: Any, *, hard: bool, soft_request: Any = None) -> bool:
    """Send one stop to the tree *proc* leads. ``False`` when there was nothing
    left to stop.

    POSIX: the web UI's ``_signal_group`` copied: ``os.killpg`` with
    ``SIGTERM`` (soft) or ``SIGKILL`` (hard) when ``proc.pid`` leads its own
    process group, else ``os.kill`` of that one PID; ``False`` on
    ``ProcessLookupError``. *soft_request* is ignored.

    Windows, for a child of :func:`async_owned_child`: ``False`` when its job is
    empty. Soft: the only soft stop is *soft_request*: when given, it is
    called as ``soft_request(proc.pid)`` on a thread of its own, so it can
    neither block nor delay anything (its result and errors are ignored, and
    the child's process handle is held until it returns, so the PID names the
    child for as long as it runs). Callers pass ``stop_request.request_stop``,
    which writes the stop file ``ask`` and ``summarise`` watch for. This call
    itself sends no console control event and sets nothing else; without
    *soft_request* a soft stop delivers nothing, and :func:`terminate_owned`'s
    stop is the hard one after the grace. Hard: terminate the job (exit status
    1 for every member). For any other process: terminate that one process,
    soft or hard, since no soft channel to it exists."""
    return _backend().stop_owned(proc, hard=hard, soft_request=soft_request)


async def terminate_owned(
    proc: Any, *, kill_grace: float, wait_after_lost_kill: bool = False, soft_request: Any = None,
) -> None:
    """Soft stop, wait up to *kill_grace* seconds, hard stop, wait up to
    *kill_grace* again.

    POSIX: ``runner._terminate_then_kill`` copied: nothing when
    ``proc.returncode`` is set; return when the soft stop finds nothing; return
    when the wait succeeds; return when the hard stop finds nothing, unless
    *wait_after_lost_kill* is true, which makes it wait once more as
    ``ask_runner.RealAskRunner._terminate`` does. Never raises for a process
    that is already gone. *soft_request* is ignored.

    Windows, for a child of :func:`async_owned_child`: the same steps, with
    the soft stop as :func:`stop_owned` describes (only *soft_request*, on its
    own thread; the grace starts when it is started, and the hard stop follows
    the grace whether or not it has returned; without it the stop is hard
    after the grace). Then, however the steps ended (also when cancelled, or
    when a stop raised), the job is terminated before anything else is
    awaited, and a bounded settle (up to *kill_grace*) waits until the job is
    empty and the child's handle is signalled. No read pipe is closed while a
    member of the job lives. Once the job is empty, what is left in each pipe
    is read to its end (into the stream, a paused reader included) for up to
    *kill_grace* more; a pipe still open then is held by a writer outside the
    job, and is closed so its reader sees end-of-file. The settle is shielded:
    a further cancellation does not stop it. An exception that was already
    leaving is re-raised, with every report and any error of the teardown
    itself as a note. Otherwise :class:`TimeoutError` says that processes were
    still in the job or the child had not exited at the end, and
    ``OutputTruncated`` (a ``TimeoutError``) that pipes had to be closed."""
    await _backend().terminate_owned(proc, kill_grace=kill_grace, wait_after_lost_kill=wait_after_lost_kill,
                                     soft_request=soft_request)


def release_owned(proc: Any) -> None:
    """Let go of *proc*'s tree. Windows: terminate its job (whatever is still
    in it dies now, even while a teardown holds its own handle to the job),
    then close the job and the child's handle; calling it again does nothing.
    POSIX: does nothing (the process group needs no handle)."""
    _backend().release_owned(proc)
