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
import selectors
import signal
import subprocess
import time
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


class OutputLimitExceeded(RuntimeError):
    """Combined stdout/stderr exceeded the caller's byte budget."""


def _limited_output(proc, argv, timeout: float, limit: int) -> tuple[bytes, bytes]:
    """Drain both pipes without letting a fast producer outrun the byte cap."""
    deadline = time.monotonic() + timeout
    buffers = [bytearray(), bytearray()]
    size = 0
    with selectors.DefaultSelector() as selector:
        for index, stream in enumerate((proc.stdout, proc.stderr)):
            selector.register(stream, selectors.EVENT_READ, index)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fd, min(65536, limit - size + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                size += len(chunk)
                if size > limit:
                    raise OutputLimitExceeded(f"child output exceeded {limit} bytes")
                buffers[key.data].extend(chunk)
    proc.wait(timeout=max(0, deadline - time.monotonic()))
    proc.stdout.close()
    proc.stderr.close()
    return bytes(buffers[0]), bytes(buffers[1])


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
    if binary and isinstance(input, str):
        raise ValueError("run_bounded: binary=True requires input to be bytes or None, not str")
    if max_output_bytes is not None and (
        max_output_bytes <= 0 or not binary or input is not None
    ):
        raise ValueError("run_bounded: output limit requires a positive budget, binary=True and no input")
    argv = list(argv)
    text_mode = not binary and not isinstance(input, (bytes, bytearray))
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
        if max_output_bytes is None:
            stdout, stderr = proc.communicate(input=input, timeout=timeout)
        else:
            stdout, stderr = _limited_output(proc, argv, timeout, max_output_bytes)
    except (subprocess.TimeoutExpired, OutputLimitExceeded) as exc:
        # start_new_session makes pid the group id. The leader may have
        # already exited while a descendant still owns a pipe: getpgid(pid)
        # would lose that group precisely when we still need to kill it.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
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
        if isinstance(exc, subprocess.TimeoutExpired):
            raise BoundedTimeout(argv, timeout) from None
        raise

    result = subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, argv, output=stdout, stderr=stderr
        )
    return result
