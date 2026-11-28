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

    ``created``: Windows: the creation time from ``GetProcessTimes``, as
    whole microseconds since the Unix epoch (pywin32 reports it to the
    millisecond). POSIX: ``None`` (today's check reads no start time).

    ``cmdline``: POSIX: the raw ``/proc/<pid>/cmdline`` bytes, so a caller
    can keep today's exact parsing. Windows: ``None``.
    """

    image: str
    created: int | None
    cmdline: bytes | None = None


def process_identity(pid: int) -> ProcessIdentity | None:
    """The identity of *pid*, or ``None`` when no such process can be read
    (POSIX: the ``/proc`` read raised ``OSError``; Windows: the PID does not
    exist or the process cannot be opened for limited query)."""
    return _backend().process_identity(pid)


def contain_child(pid: int, *, expect: ProcessIdentity | None = None) -> Any:
    """Contain an already-running child that someone else spawned.

    Windows: assign *pid* to a fresh kill-on-close job object (breakaway
    allowed, as a new session escapes ``killpg`` on POSIX), then adopt its
    descendants that were spawned before the assignment. The returned handle
    keeps the job alive: dropping it, or this process dying, kills
    everything in the job. ``None`` when the process no longer exists, or
    when *expect* is given and the process opened is not that identity (the
    check runs on the same open handle as the assignment, so a reused PID is
    never assigned).

    POSIX: makes no system call (unless *expect* is given, which reads
    ``/proc``) and returns a handle carrying *pid*; the process group is
    read with ``os.getpgid`` at kill time, exactly as
    ``sdksession/teardown.kill_child`` does today.
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
    ``ProcessLookupError`` and ``PermissionError``.
    """
    _backend().terminate_contained(handle)


def contain_self() -> bool:
    """Make this process's descendants die with it, whatever kills it.

    Windows: put this process in a kill-on-close job with breakaway
    allowed (a child started with ``CREATE_BREAKAWAY_FROM_JOB`` still
    escapes). Nests under a job the process is already in. Safe to call
    again: later calls return ``True`` without a new job. Returns ``True``.

    POSIX: does nothing and returns ``False`` (descendants are handled by
    process groups there).
    """
    return _backend().contain_self()
