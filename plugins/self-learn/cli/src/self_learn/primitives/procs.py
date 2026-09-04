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
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Mapping, Sequence


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


def run_bounded(
    argv: Sequence[str],
    *,
    timeout: float,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    input: str | bytes | None = None,
    check: bool = False,
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
    not raised, same as there too."""
    argv = list(argv)
    text_mode = not isinstance(input, (bytes, bytearray))
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text_mode,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            pgid = None
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            # the group kill above should make this unreachable in
            # practice; a last-resort direct kill + one more bounded
            # drain rather than a bare (unbounded) communicate().
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        raise BoundedTimeout(argv, timeout) from None

    result = subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, argv, output=stdout, stderr=stderr
        )
    return result
