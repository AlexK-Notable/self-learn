"""Who made a ledger commit (cures CU-4, S-109).

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

:func:`stamp` is applied to every **ledger** commit's body: by
:func:`gitops.stage_and_commit`, and by each direct ``gitops.commit(home,
...)`` call site (host-repo commits are never stamped). It appends a final
``By: <actor>`` paragraph unless the body already ends in a trailer block
that is provably the current writer's own (a verb's own ``By:`` block naming
it, or, inside a job, a sheet runner's execution block). With no actor set
at all (a library call from a test) the body is left exactly as it was.

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
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from .grant_uses import GrantUse

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
    "SHEET_RUNNERS",
    "stamp",
]

#: Every value a stamped ``By:`` trailer may carry. ``human``/``agent`` are
#: the two shells; the rest are the jobs (``sweep`` is the premise sweep,
#: ``serve`` the daemon outside any job, ``policy`` the daily host policy,
#: S-112, ``maintenance`` the daily maintenance recompile,
#: S-119); ``analyst`` stays for the verbs' own ``routing.by``
#: trailers written before this module.
ACTORS = frozenset(
    {
        "human", "agent", "miner", "worker", "sweep", "steward", "overseer", "serve", "policy",
        "maintenance", "analyst",
    }
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
    is the agent's ``--note`` (for a typed yes, what it answered).
    ``words`` (a grant only) are the user's own words the grant was recorded
    from, copied into every commit made under it so the grant can be read
    where it is used (gate r1 finding 6)."""

    kind: str
    ref: str
    reason: str
    words: str = ""

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

    def paragraphs(self) -> list[str]:
        """The body paragraphs a commit made under this authority carries
        before its trailer: the reason, and for a grant the user's words.
        Either may be trailer-shaped (a typed yes's reason is ``Answers:
        q-…``), which is harmless: :func:`stamp` always writes them before
        its own ``By: agent`` block, so that block stays the final one, the
        only block a reader of who made the commit takes."""
        out = [self.reason.strip()]
        if self.words.strip():
            words = " ".join(self.words.split())
            out.append(f'Under the user\'s standing grant ({self.ref}): "{words}"')
        return out

    def held_by(self, text: str) -> bool:
        """Whether *text* already holds every one of :meth:`paragraphs`."""
        flat = " ".join(text.split())
        return all(" ".join(p.split()) in flat for p in self.paragraphs())


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
    """Decorate a job's entry point (``steward.run``, ``overseer.run.run``,
    ``premise_sweep.run``) so every commit it makes is the job's, whoever
    started it. ``worker.run`` and ``miner.run`` open :func:`job` in their
    own body instead: this wrapper's ``(*args, **kwargs)`` would hide their
    ``no_push`` parameter from their own signature."""
    _check(actor)

    def wrap(fn: Callable[_P, _R]) -> Callable[_P, _R]:
        @functools.wraps(fn)
        def inner(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with job(actor):
                return fn(*args, **kwargs)

        return inner

    return wrap


@contextlib.contextmanager
def acting(granted: Authority | None, *, use: "GrantUse | None" = None) -> Iterator[None]:
    """Put *granted* in force for the commits inside the span. ``None`` (a
    person's own terminal, where no authority is needed) changes nothing.

    *use* (attention round, design r2 §3.4.6): what the wrapped person-only
    verb does, read by its call site before it acts. With an authority in
    force and *use* given, on a normal exit (no exception, ``use.applies``
    still true) one ``grant-uses.jsonl`` row is appended as its own commit
    right after the verb, while the authority is still in force, so that
    commit is stamped ``By: agent`` with the authority's trailer.
    :func:`grant_uses.append` takes :func:`intents.ledger_write` itself.

    The verb itself does NOT run under an outer ledger lock here (gate r1
    MINOR 1): the skill verbs push inside their span, and
    ``gitops.commit_lock`` is documented never to cover a push; and an
    outer acquisition would swallow the recovery announcement that each
    verb's own ``ledger_write`` makes. Nothing needs the verb and its row
    to be one atomic step: a failed append is reported on stderr and never
    fails the verb -- the act happened, and its commit trailers still hold
    it."""
    if granted is None:
        yield
        return
    token = _AUTHORITY.set(granted)
    try:
        yield
        if use is not None and use.applies:
            from . import grant_uses  # lazy: keep this module import-light

            try:
                grant_uses.append(
                    use.home,
                    grant_uses.row_for(granted.kind, granted.ref, granted.reason, use),
                )
            except Exception as exc:  # noqa: BLE001 -- the verb already succeeded
                import sys

                print(
                    f"self-learn: {use.verb}: done, but its grant-use record was not "
                    f"written ({exc}); the commit's trailers still record the act",
                    file=sys.stderr,
                )
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


#: The actors that run a sheet and write its execution block (``By:``,
#: ``Case:``, ``Sheet:``, ``Item:``, :mod:`self_learn.execution_evidence`).
SHEET_RUNNERS = frozenset({"steward", "overseer"})

#: A job whose own verbs write another actor's ``By:`` trailer as theirs:
#: the worker (and the miner, which runs it) route with ``by="analyst"``.
_JOB_OWN_TRAILERS: dict[str, frozenset[str]] = {
    "worker": frozenset({"analyst"}),
    "miner": frozenset({"analyst"}),
}


def _is_execution_block(text: str) -> bool:
    from . import execution_evidence  # lazy: keep this module import-light

    return execution_evidence.parse_trailers(text) is not None


def _owns(actor: str, pairs: dict[str, str], text: str) -> bool:
    """Whether the final ``By:`` block *pairs* is provably *actor*'s own
    (gate r1 finding 2): it names *actor* (or a trailer *actor*'s own verbs
    write, such as the worker's ``analyst``), or, outside a shell, it is a
    sheet runner's execution block. In a shell nothing else is: a note
    typed there may end in any block it likes."""
    by = pairs["By"]
    if "Grant" in pairs or "Proof" in pairs:
        return False  # only an authority in force writes those (stamp's first branch)
    if by == actor or by in _JOB_OWN_TRAILERS.get(actor, frozenset()):
        return True
    return actor not in SHELL_ACTORS and by in SHEET_RUNNERS and _is_execution_block(text)


def _missing(text: str, granted: Authority) -> str:
    """*text* with each of *granted*'s paragraphs it does not hold yet."""
    out = text
    for paragraph in granted.paragraphs():
        if " ".join(paragraph.split()) not in " ".join(out.split()):
            out = _with_paragraph(out, paragraph)
    return out


def stamp(body: str | None) -> str | None:
    """*body* with the who-did-it trailer a ledger commit needs.

    The body's own final ``By:`` block is kept only when it is provably the
    current writer's (gate r1 finding 2; text a note or a model wrote may end
    in any block it likes, so a block naming someone else is never trusted):

    * An :class:`Authority` in force: ``By: agent`` plus ``Grant:``/``Proof:``,
      and the reason (and, for the grant, the user's words) as their own
      paragraphs when the body does not already hold them. A final ``By:
      agent`` block with no ``Grant:``/``Proof:`` (a verb stamped ``By:
      agent`` itself) gains this authority's line instead of a second block;
      one already naming this very authority is kept. Any other final block
      gets this one after it.
    * Otherwise the current actor, as ``By: <actor>``, unless the body
      already ends in that actor's own block (:func:`_owns`).
    * No actor: *body* unchanged."""
    granted = _AUTHORITY.get()
    text = body if body is not None else ""
    pairs = _final_block(text)[1] if text.strip() else {}
    if granted is not None:
        key = "Grant" if granted.kind == "grant" else "Proof"
        if pairs.get("By") == "agent" and set(pairs) <= {"By", key}:
            head, _pairs = _final_block(text)
            block = text.strip()[len(head):].strip()
            if key not in pairs:
                return _with_paragraph(_missing(head, granted), f"{block}\n{key}: {granted.ref}")
            if pairs[key] == granted.ref and granted.held_by(head):
                return body
        return _with_paragraph(_missing(text, granted), granted.trailer())
    actor = current_actor()
    if actor is None:
        return body
    if pairs and _owns(actor, pairs, text):
        return body
    return _with_paragraph(text, f"By: {actor}")
