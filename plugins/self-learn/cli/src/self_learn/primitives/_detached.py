"""The result types of :func:`procs.spawn_detached` and
:func:`procs.terminate_owned` (S-NEXT-w7-procs).

Ordinary module-level classes, so they pickle and compare like any other; the
facade imports this module only when one of them is first used, so importing
``procs`` does no more work than it did before they existed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetachedChild:
    """What :func:`procs.spawn_detached` started.

    ``broke_away``: Windows only, and a record of the launch attempt, not of
    where the child ended up. ``True``: started with
    ``CREATE_BREAKAWAY_FROM_JOB``, which leaves this process's job and every
    enclosing job that also allows breakaway, up to the first that does not
    (measured: a forbidding outer job keeps the child). ``False``: the attempt
    with the flag failed with error 5 and the child was started without it
    (a job that breaks children away silently can still have let it go).
    ``None``: this process is in no job, and always on POSIX.

    ``in_job``: Windows only. Whether the child was in any job when it was
    looked at, once, right after it started (``None``: that could not be
    read; the child runs regardless). Trust it over ``broke_away``. A child in
    a job outlives the launcher unless the job is terminated, or it kills on
    close and its last handle closes. Always ``False`` on POSIX."""

    pid: int
    broke_away: bool | None = None
    in_job: bool | None = False


class OutputTruncated(TimeoutError):
    """:func:`procs.terminate_owned` closed read pipes that had not reached
    end-of-file within the drain bound after the child's job was empty: a
    writer outside the job (a descendant that broke away) still held them,
    and whatever it writes from then on is lost to the reader. What was read
    before is kept in the stream. ``pipes`` is how many were closed."""

    def __init__(self, message: str, pipes: int = 0) -> None:
        super().__init__(message)
        self.pipes = pipes
