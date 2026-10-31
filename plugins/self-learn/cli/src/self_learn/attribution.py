"""Who made a ledger commit (cures CU-4, S-NEXT-attribution).

One actor per running piece of work, read at commit time:

* the **process actor**, set once by :func:`self_learn.cli.main` for a
  command line (``human`` in a person's terminal, ``agent`` when
  :func:`settings.agent_caller` detects an agent's shell), and by
  :func:`self_learn.serve.run_forever` for the daemon (``serve``);
* a **job actor**, set for the span of one job by :func:`job`: the serve
  scheduler's jobs (``miner``, ``worker``, ``sweep``, ``steward``,
  ``overseer``) and the miner's and worker's own entry points, so a worker
  auto-kicked from an agent's command line still commits as ``worker``.

The job actor wins over the process actor. Both live in
:mod:`contextvars`, so :func:`self_learn.cli.main` runs each command in a
copy of the context and nothing one in-process call sets leaks into the
next (the test suite calls ``main`` hundreds of times in one process).

:func:`stamp` is what :func:`gitops.commit` applies to every **ledger**
commit (``ledger=True``; host-repo commits are never stamped): it appends a
final ``By: <actor>`` paragraph unless the body already ends in a trailer
paragraph that says who did it (a verb's own ``By:`` block, a sheet runner's
execution block). With no actor set at all (a library call from a test) the
body is left exactly as it was.

An agent's call to a person-only command runs only under an
:class:`Authority`: the user's standing grant (:mod:`self_learn.grants`) or a
typed yes proved for one overseer question (:mod:`self_learn.consent`).
:func:`acting` puts it in force for the commits it wraps; :func:`stamp` then
writes ``By: agent`` and ``Grant: <statement id>`` (or ``Proof:
<transcript ref>``), with the reason as the body's own paragraph. Never
``human``: an agent's act is the agent's, whoever allowed it.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")

__all__ = [
    "ACTORS",
    "Authority",
    "acting",
    "as_job",
    "authority",
    "current_actor",
    "job",
    "process",
    "refuse_unless_authorized",
    "stamp",
]

#: Every value a stamped ``By:`` trailer may carry. ``human``/``agent`` are
#: the two shells; the rest are the jobs (``sweep`` is the premise sweep,
#: ``serve`` the daemon outside any job); ``analyst`` stays for the verbs'
#: own ``routing.by`` trailers written before this module.
ACTORS = frozenset(
    {"human", "agent", "miner", "worker", "sweep", "steward", "overseer", "serve", "analyst"}
)
#: The actors that are a shell someone typed into, not a job.
SHELL_ACTORS = frozenset({"human", "agent"})

_PROCESS: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "self_learn_process_actor", default=None
)
_JOB: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "self_learn_job_actor", default=None
)


@dataclass(frozen=True)
class Authority:
    """What lets an agent's shell run a person-only command.

    ``kind`` is ``grant`` (the user's recorded standing grant; ``ref`` is its
    statement id) or ``typed-yes`` (a plain yes the person typed to the
    message that named this act; ``ref`` is that transcript line). ``reason``
    is the agent's ``--note`` (for a typed yes, what it answered)."""

    kind: str
    ref: str
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in ("grant", "typed-yes"):
            raise ValueError(f"authority kind must be grant or typed-yes, got {self.kind!r}")
        if not self.ref.strip():
            raise ValueError("authority ref is required")
        if not self.reason.strip():
            raise ValueError("authority reason is required")

    def trailer(self) -> str:
        key = "Grant" if self.kind == "grant" else "Proof"
        return f"By: agent\n{key}: {self.ref}"


_AUTHORITY: contextvars.ContextVar[Authority | None] = contextvars.ContextVar(
    "self_learn_authority", default=None
)


def current_actor() -> str | None:
    """The job actor when a job is running, else the process actor, else
    ``None`` (nothing set: a library call)."""
    return _JOB.get() or _PROCESS.get()


def authority() -> Authority | None:
    return _AUTHORITY.get()


def _check(actor: str) -> str:
    if actor not in ACTORS:
        raise ValueError(f"actor must be one of {sorted(ACTORS)}, got {actor!r}")
    return actor


@contextlib.contextmanager
def process(actor: str) -> Iterator[None]:
    """The process actor for the span (``cli.main``, ``serve``)."""
    token = _PROCESS.set(_check(actor))
    try:
        yield
    finally:
        _PROCESS.reset(token)


@contextlib.contextmanager
def job(actor: str) -> Iterator[None]:
    """A job's actor for the span; wins over the process actor."""
    token = _JOB.set(_check(actor))
    try:
        yield
    finally:
        _JOB.reset(token)


def as_job(actor: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Decorate a job's entry point (``worker.run``, ``miner.run``, ...) so
    every commit it makes is the job's, whoever started it."""
    _check(actor)

    def wrap(fn: Callable[_P, _R]) -> Callable[_P, _R]:
        @functools.wraps(fn)
        def inner(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with job(actor):
                return fn(*args, **kwargs)

        return inner

    return wrap


@contextlib.contextmanager
def acting(granted: Authority | None) -> Iterator[None]:
    """Put *granted* in force for the commits inside the span. ``None`` (a
    person's own terminal, where no authority is needed) changes nothing."""
    if granted is None:
        yield
        return
    token = _AUTHORITY.set(granted)
    try:
        yield
    finally:
        _AUTHORITY.reset(token)


def refuse_unless_authorized(surface: str, refusal: Callable[[str], Exception]) -> None:
    """The library-side half of the person-only rule: from an agent's shell
    with no :class:`Authority` in force, raise *refusal*. The command line
    puts one in force through :func:`self_learn.grants.authorize` (or the
    overseer through a proved typed yes) before it calls the library, so
    this fires only for a caller that skipped that step. *refusal* builds
    the exception from the message (an exception class taking one message
    argument will do)."""
    from . import settings  # lazy: settings imports ledger, which imports hosts

    if settings.agent_caller() and _AUTHORITY.get() is None:
        raise refusal(
            f"{surface} is a person-only command; from an agent's shell it runs "
            "under the user's standing grant: pass --note saying why "
            "(`self-learn grant list` shows the grant) "
            f"(agent shell detected: {', '.join(settings.agent_caller_markers())})"
        )


_TRAILER_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z-]*: \S")


def _final_block(body: str) -> tuple[str, dict[str, str]]:
    """``(head, pairs)``: *body* without its final paragraph when that
    paragraph is a trailer block holding ``By:`` (every line ``Key: value``),
    and that block's pairs; ``(body, {})`` otherwise. The same reading
    :func:`self_learn.report._split_trailers` makes."""
    text = body.strip()
    head, _sep, tail = text.rpartition("\n\n")
    lines = [line for line in tail.splitlines() if line.strip()]
    if not lines or not all(_TRAILER_LINE_RE.match(line) for line in lines):
        return text, {}
    pairs = dict(line.split(": ", 1) for line in lines)
    if "By" not in pairs:
        return text, {}
    return head, pairs


def _with_paragraph(body: str | None, paragraph: str) -> str:
    if body is None or not body.strip():
        return paragraph
    return f"{body.rstrip()}\n\n{paragraph}"


def stamp(body: str | None) -> str | None:
    """*body* with the who-did-it trailer a ledger commit needs.

    * An :class:`Authority` in force: ``By: agent`` plus ``Grant:``/``Proof:``,
      and the reason as its own paragraph when the body does not already hold
      it. A ``By:`` block the body already ends in (a verb stamped ``By:
      agent`` itself) gains the ``Grant:``/``Proof:`` line instead of a second
      block.
    * Otherwise the current actor, as ``By: <actor>``, unless the body already
      ends in a ``By:`` block. One exception keeps a shell honest: in a
      shell (``human``/``agent``) a final ``By:`` block naming someone else that
      is not a sheet runner's execution block (``Case:`` line) gets this
      shell's own block after it, so a note ending ``By: steward`` typed into
      an agent's shell cannot pass for the steward.
    * No actor: *body* unchanged."""
    granted = _AUTHORITY.get()
    text = body if body is not None else ""
    pairs = _final_block(text)[1] if text.strip() else {}
    if granted is not None:
        if pairs.get("By") == "agent" and "Grant" not in pairs and "Proof" not in pairs:
            key = "Grant" if granted.kind == "grant" else "Proof"
            return f"{text.rstrip()}\n{key}: {granted.ref}"
        if pairs and ("Grant" in pairs or "Proof" in pairs):
            return body
        reason = " ".join(granted.reason.split())
        out = text if reason in " ".join(text.split()) else _with_paragraph(text, granted.reason.strip())
        return _with_paragraph(out, granted.trailer())
    actor = current_actor()
    if actor is None:
        return body
    if pairs:
        if pairs["By"] == actor or "Case" in pairs or actor not in SHELL_ACTORS:
            return body
    return _with_paragraph(text, f"By: {actor}")
