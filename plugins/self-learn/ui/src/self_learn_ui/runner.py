"""runner.py — the verb-EXECUTION seam (task U3 brief: "build against a
RUNNER SEAM — define a minimal async runner interface (run(verb_argv) ->
exit/status/stderr) with a fake for tests; U4 replaces the fake with the
real serialized subprocess queue. Do NOT build the real runner (that's
U4); wire everything through the seam.").

:class:`VerbRunner` is the seam both implementations satisfy. Routes (U3)
import ONLY this module — never `subprocess` directly — so swapping in
U4's serialized async subprocess queue is a wiring change at the app
factory, not a routes.py change.

``argv`` is the CLI verb's OWN argument list, e.g. ``["route",
"lrn-aa000001", "--dest", "skill-md"]`` — never including the
``self-learn`` binary name or ``SELF_LEARN_HOME`` (a real runner resolves
both itself, exactly the way :mod:`self_learn_ui.ledger` resolves the CLI
binary for read-only ``--json`` calls).

U4 adds :class:`RealRunner` — the serialized async subprocess queue named
in 10 §1's "Verb runner" row and built at task U4. It owns three things
09 §3 pins as view-layer-independent: (1) ONE verb subprocess at a time
server-wide, so concurrent tabs never race the git index; (2) the
interrupt-first dispatch check (P1-4) — a session under active pane
iteration on the record a verb is about to touch gets interrupted BEFORE
the verb spawns, never concurrently; (3) a forced ledger refresh after
every verb, from the exit status alone — never by parsing stdout (07 §4
contract 2, restated at 09 §3).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from abc import ABC, abstractmethod
from asyncio import (
    CancelledError,
    Lock,
    create_subprocess_exec,
    subprocess as asyncio_subprocess,
    wait_for,
)
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from re import compile as re_compile

__all__ = [
    "FakeRunner",
    "NotWiredRunner",
    "RealRunner",
    "RunResult",
    "VerbRunner",
    "communicate_bounded",
    "extract_record_id",
    "resolve_self_learn_argv_prefix",
]


@dataclass(frozen=True)
class RunResult:
    """A completed verb invocation's outcome — exit status + stderr,
    never parsed stdout (07 §4 contract 2, carried into 09 §3: "never by
    parsing human-formatted stdout"). ``ok`` reads ``exit_code`` alone,
    always — that invariant is unchanged by ``evidence`` below.

    ``evidence`` (resolution-evidence unit, §3.1): the parsed ``--json``
    envelope route/reject/defer/graduate print on stdout, or ``None``.
    This is NOT the exception §3.1's own doctrine forbids — a JSON
    envelope is machine structure, not "human-formatted stdout", so no
    carve-out is needed for it to coexist with the rule above. Populated
    in ``__post_init__`` so both :class:`RealRunner` (a real subprocess's
    stdout) and :class:`FakeRunner` (a test's scripted ``stdout=``) get
    it for free from the SAME parse — a test may also pass ``evidence=``
    directly (e.g. to inject a state with no real fixture behind it,
    §5's render-layer drift test), which this leaves untouched. A
    missing, truncated, or unparseable envelope — or a non-zero exit —
    leaves ``evidence`` `None`: the action still succeeded or failed
    exactly as ``exit_code`` says; only the DETAIL rendering degrades."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    evidence: dict | None = None

    def __post_init__(self) -> None:
        if self.evidence is not None or self.exit_code != 0:
            return
        try:
            parsed = json.loads(self.stdout)
        except (json.JSONDecodeError, ValueError):
            return
        if isinstance(parsed, dict):
            object.__setattr__(self, "evidence", parsed)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class VerbRunner(ABC):
    """The seam. A real implementation (U4) serializes every call
    server-wide (one verb subprocess at a time); this ABC carries no
    serialization itself — that discipline lives in the concrete
    implementation, per the task brief."""

    @property
    def busy(self) -> bool:
        """Y-14 idle-predicate leg (09 §3): is a verb subprocess in
        flight right now? Base answer is False — only
        :class:`RealRunner` actually serializes and therefore actually
        knows; fakes stay non-busy unless a test says otherwise."""
        return False

    @abstractmethod
    async def run(self, argv: list[str]) -> RunResult:
        """Run ``self-learn <argv...>`` and return its outcome. Never
        raises for a non-zero exit — that is an ordinary :class:`RunResult`
        (task pin: verb failures are explicit states, never exceptions
        routes.py must catch ad hoc)."""
        raise NotImplementedError


class NotWiredRunner(VerbRunner):
    """The production default before U4 landed (kept for any caller that
    deliberately wants "no runner wired" to fail loudly rather than
    silently no-op — :func:`self_learn_ui.app.create_app` no longer
    defaults to this; it defaults to :class:`RealRunner`, below): any
    call is a programming error, surfaced loudly."""

    async def run(self, argv: list[str]) -> RunResult:
        raise RuntimeError(
            "self-learn-ui: no VerbRunner wired — U4's serialized subprocess "
            "queue is not built yet; inject a FakeRunner in tests or wait "
            "for U4 in production"
        )


class FakeRunner(VerbRunner):
    """Scripted-playback runner for downstream route tests (mirrors
    :class:`self_learn_ui.engine.base.FakeEngine`'s shape). Records every
    call's argv so a test can assert exact CLI invocations; returns a
    queued :class:`RunResult` per call (FIFO), falling back to ``default``
    once the queue drains."""

    def __init__(self, default: RunResult | None = None) -> None:
        self.calls: list[list[str]] = []
        self._queue: list[RunResult] = []
        self._default = default if default is not None else RunResult(0)

    def queue_result(self, result: RunResult) -> None:
        self._queue.append(result)

    async def run(self, argv: list[str]) -> RunResult:
        self.calls.append(list(argv))
        if self._queue:
            return self._queue.pop(0)
        return self._default


# ------------------------------------------------------------- RealRunner


#: The CLI's own id pattern (``self_learn.records.RECORD_ID_RE``, mirrored
#: rather than imported — this module has no dependency on the cli
#: package's internals, only on the shape of the id it hands the CLI on
#: argv, which 08 §1 pins as ``lrn-`` + 8 lowercase hex chars). Scanning
#: argv for this shape is how the runner learns WHICH record a verb call
#: is about — genuinely verb-grammar-agnostic (some verbs put the id at
#: argv[1], ``link contradicts <id> <target>`` and ``followup done <id>``
#: put it later) without hardcoding per-verb argv positions here.
_RECORD_ID_RE = re_compile(r"lrn-[0-9a-f]{8}")

#: Env var override for :func:`resolve_self_learn_argv_prefix` (10 §1
#: Verb runner row: "resolves via PATH with an env override for tests").
#: Space-separated (``shlex.split``) so a test can point at an
#: interpreter + script (e.g. ``"python3 /path/to/fake_self_learn.py"``)
#: without needing the fake to be independently executable/on PATH.
SELF_LEARN_BIN_ENV = "SELF_LEARN_UI_CLI_BIN"


def extract_record_id(argv: list[str]) -> str | None:
    """The record id a verb call is *about*, or ``None`` for an id-less
    verb (``push``, ``mine run``). The FIRST ``lrn-xxxxxxxx`` TOKEN
    (exact match, not substring — a ``--note`` value is never mistaken
    for an id unless it IS one verbatim) in argv order — every pinned
    verb's own record id appears before any second id it might also
    carry (``link contradicts <record-id> <target-id>``: the record
    being linked always precedes the target it's linked to)."""
    for token in argv:
        if _RECORD_ID_RE.fullmatch(token):
            return token
    return None


def resolve_self_learn_argv_prefix(environ: dict[str, str] | None = None) -> list[str]:
    """The argv PREFIX for invoking the ``self-learn`` CLI — a list (not
    a single path) so :data:`SELF_LEARN_BIN_ENV` can name an interpreter
    + script pair. Resolution order: the env override, then PATH (scoped
    to *environ*'s own ``PATH`` — never the real process PATH when an
    explicit ``environ`` is given, so a hermetic test env can shim this
    without touching ``os.environ``), then the ``sys.executable``-relative
    fallback :func:`self_learn_ui.ledger._self_learn_bin` also uses (same
    reasoning: both packages install into the same uv-managed venv)."""
    env = environ if environ is not None else os.environ
    override = env.get(SELF_LEARN_BIN_ENV)
    if override:
        return shlex.split(override)
    exe = shutil.which("self-learn", path=env.get("PATH"))
    if exe:
        return [exe]
    candidate = Path(sys.executable).parent / "self-learn"
    if candidate.exists():
        return [str(candidate)]
    return ["self-learn"]  # let subprocess raise a clear FileNotFoundError


#: The pane track's (U6) session-interrupt hook: given the record id a
#: verb is about to touch, interrupt that record's active pane session if
#: one exists — the hook's OWN job is the "if under active iteration"
#: check (09 §3/P1-4); the runner always awaits it before spawning a verb
#: for any id-bearing argv, unconditionally, so U6 never has to coordinate
#: a second "is it active" callback with this module.
InterruptHook = Callable[[str], Awaitable[object]]


async def _default_interrupt_hook(record_id: str) -> None:
    """Default no-op (task brief point 4: "the pane side supplies it
    later; default no-op"). Every dispatch still calls this — it is the
    hook's job to no-op when nothing is active, never the runner's."""
    return None


# ------------------------------------------------------- bounded communicate
#
# C05 (M-H): ``RealRunner.run`` used to hold its server-wide lock across a
# BARE ``await proc.communicate()`` — a hung verb (a wedged git index, a
# network fs stall, a child that never exits) blocked every later UI verb
# forever, and a cancelled request (HTTP disconnect, server shutdown) left
# the child running with nobody left to reap it. Everything below fixes
# that: a verb subprocess is always bounded, and on EITHER a timeout or a
# task cancellation the child is escalated terminate -> grace -> kill ->
# reap, never left running (leaked) or left a zombie (un-reaped).

#: Ceiling on a verb subprocess's `communicate()` — generous by design:
#: `mine run` drives the SDK-backed analyst and can legitimately run for
#: minutes. This is a backstop against a HANG, never a normal-operation
#: budget, so it errs long.
DEFAULT_VERB_TIMEOUT_SECS = 600.0

#: Ceiling on the injected interrupt hook (U6's pane-session interrupt,
#: task brief point 4: "the injected interrupt hook is bounded") — a
#: wedged pane engine must not hold the lock, and every OTHER tab's verb
#: dispatch behind it, forever.
DEFAULT_INTERRUPT_TIMEOUT_SECS = 30.0

#: SIGTERM -> SIGKILL grace window when a subprocess must be forced to
#: exit. Long enough for an ordinary child to clean up after SIGTERM;
#: short enough that a TERM-ignoring child (test_runner_real.py's own
#: worst case: ``bash -c 'trap "" TERM; sleep 60'``) doesn't hold the
#: lock for long once the timeout above has already fired.
DEFAULT_KILL_GRACE_SECS = 5.0


def _exit_code_of(proc: asyncio_subprocess.Process) -> int:
    return proc.returncode if proc.returncode is not None else 1


async def _terminate_then_kill(
    proc: asyncio_subprocess.Process, *, kill_grace: float
) -> None:
    """terminate -> grace -> kill -> reap. Never raises: a process that
    exits between our own check and the signal is not an error —
    ``ProcessLookupError`` is exactly that race, caught and ignored.
    Every wait here is itself bounded by ``kill_grace``, so a child that
    ignores BOTH signals (not a real scenario — SIGKILL cannot be
    blocked or ignored — but kept bounded defensively) still returns
    control to the caller rather than hanging this function forever."""
    if proc.returncode is not None:
        return  # already exited — nothing to escalate
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await wait_for(proc.wait(), timeout=kill_grace)
        return
    except TimeoutError:
        pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await wait_for(proc.wait(), timeout=kill_grace)
        except TimeoutError:
            pass  # best-effort reap; SIGKILL cannot be ignored, so the
            # process is dying regardless — a later ``proc.wait()`` still
            # reaps it cleanly (asyncio's child watcher owns that).


async def communicate_bounded(
    proc: asyncio_subprocess.Process,
    *,
    timeout: float,
    kill_grace: float = DEFAULT_KILL_GRACE_SECS,
) -> tuple[bytes, bytes, int]:
    """Bounded replacement for a bare ``await proc.communicate()`` — the
    C05 defect this move closes. Returns ``(stdout, stderr, returncode)``
    on a clean completion OR on a timeout (the caller turns a timeout
    into an ordinary failed :class:`RunResult`, never an exception — the
    same contract as ``self-learn`` failing on its own). On the awaiting
    task itself being CANCELLED (an HTTP client disconnect, a server
    shutdown — ``CancelledError`` raised through the ``await`` below),
    the child is still terminate -> grace -> kill -> reaped before the
    ``CancelledError`` is RE-RAISED: this function's only job is the
    CHILD's lifecycle, never swallowing the caller's own cancellation."""
    try:
        stdout_b, stderr_b = await wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        await _terminate_then_kill(proc, kill_grace=kill_grace)
        message = f"self-learn-ui: verb exceeded {timeout}s and was terminated\n"
        return b"", message.encode("utf-8"), _exit_code_of(proc)
    except CancelledError:
        await _terminate_then_kill(proc, kill_grace=kill_grace)
        raise
    return stdout_b, stderr_b, _exit_code_of(proc)


class RealRunner(VerbRunner):
    """The serialized async subprocess queue (10 §1 Verb runner row; 09
    §3 "Verb invocation"). ONE ``self-learn <argv>`` subprocess at a time
    server-wide: an :class:`asyncio.Lock` means every concurrent caller —
    multiple browser tabs share ONE :class:`RealRunner` instance via
    ``app.state.runner`` — waits its turn rather than racing the git
    index. Reject-during-run is realized by this serialization itself
    plus the SSE ``applying`` envelopes routes.py already publishes
    around each call (preserved, not reimplemented here): a second
    submission's HTTP request simply waits behind the lock while its
    "applying…" state is visible to every connected tab.

    Outcome is ALWAYS the subprocess's exit status + stderr — never
    parsed HUMAN-FORMATTED stdout (07 §4 contract 2; 09 §3's own wording,
    restored here — this docstring had dropped the qualifier, which
    read as a blanket "stdout is never parsed" and would have forbidden
    the resolution-evidence unit's ``--json`` envelope outright. A JSON
    envelope is machine structure, not human-formatted text, so
    :attr:`RunResult.evidence` parsing it is not a carve-out from this
    rule — ``ok``/exit-status handling below is completely unchanged by
    it). A forced ledger refresh fires after every completed verb,
    scoped to the touched record when one is identifiable
    (:func:`extract_record_id`), else ``front`` (``push``, ``mine
    run``).
    """

    def __init__(
        self,
        *,
        home: Path,
        refresh_callback: Callable[[str], None] | None = None,
        argv_prefix: list[str] | None = None,
        env: dict[str, str] | None = None,
        interrupt_active_session: InterruptHook | None = None,
        verb_timeout: float = DEFAULT_VERB_TIMEOUT_SECS,
        interrupt_timeout: float = DEFAULT_INTERRUPT_TIMEOUT_SECS,
        kill_grace: float = DEFAULT_KILL_GRACE_SECS,
    ) -> None:
        """``home`` is pinned onto ``SELF_LEARN_HOME`` for every spawned
        subprocess (exactly :mod:`self_learn_ui.ledger`'s own pattern for
        read-only ``--json`` calls). ``refresh_callback`` is normally
        :meth:`self_learn_ui.ledger.RefreshHub.force_refresh` — accepted
        as a plain callable rather than the concrete hub type so this
        module stays independent of ``ledger.py``'s import graph.
        ``argv_prefix`` injects the CLI invocation directly (bypassing
        :func:`resolve_self_learn_argv_prefix` entirely — the cleanest
        override for tests); when omitted, resolution runs once at
        construction time against ``env`` (or real ``os.environ`` if
        ``env`` is also omitted — the production path). ``verb_timeout``/
        ``interrupt_timeout``/``kill_grace`` are M-H's bounds (C05) —
        tests shrink them; production keeps the generous defaults."""
        self._home = home
        self._refresh_callback = refresh_callback
        self._argv_prefix = (
            list(argv_prefix)
            if argv_prefix is not None
            else resolve_self_learn_argv_prefix(env)
        )
        self._env = env
        self._lock = Lock()
        self._interrupt_active_session: InterruptHook = (
            interrupt_active_session or _default_interrupt_hook
        )
        self._verb_timeout = verb_timeout
        self._interrupt_timeout = interrupt_timeout
        self._kill_grace = kill_grace

    @property
    def busy(self) -> bool:
        """True while a verb subprocess (or its interrupt-first hook)
        holds the serialization lock — the Y-14 idle predicate's
        "runner between verbs" leg reads this (09 §3)."""
        return self._lock.locked()

    def set_interrupt_hook(self, hook: InterruptHook | None) -> None:
        """Plug in (or clear) the pane track's session-interrupt hook
        post-construction — task brief point 4: "Expose the hook so the
        concurrent U6 agent can plug its session manager in without
        editing runner.py (a setter or constructor arg on the runner)".
        ``None`` restores the default no-op."""
        self._interrupt_active_session = hook or _default_interrupt_hook

    async def run(self, argv: list[str]) -> RunResult:
        record_id = extract_record_id(argv)
        # `async with` is Python's own try/finally for a context manager
        # (M-H pin: "the lock is released on every path") — it releases
        # on a normal return, on an ordinary exception, AND on this
        # coroutine's own task being cancelled, so a hand-rolled
        # acquire()/release() pair would add risk (a forgotten release on
        # some path) without adding any guarantee this doesn't already
        # have.
        async with self._lock:
            if record_id is not None:
                # Interrupt-first (P1-4): awaited BEFORE the verb spawns,
                # never concurrently with it — the pane agent could
                # otherwise still hold live write permission on the exact
                # files the verb is about to git mv/git rm. BOUNDED
                # (M-H): a wedged pane engine must not hold this lock —
                # and every OTHER tab's verb dispatch behind it — forever;
                # on timeout the verb still proceeds (best-effort
                # courtesy, never a gate on whether the verb may run).
                try:
                    await wait_for(
                        self._interrupt_active_session(record_id),
                        timeout=self._interrupt_timeout,
                    )
                except TimeoutError:
                    pass
            result = await self._spawn(argv)
        if self._refresh_callback is not None:
            scope = f"record:{record_id}" if record_id is not None else "front"
            self._refresh_callback(scope)
        return result

    async def _spawn(self, argv: list[str]) -> RunResult:
        full_env = dict(self._env if self._env is not None else os.environ)
        full_env["SELF_LEARN_HOME"] = str(self._home)
        cmd = [*self._argv_prefix, *argv]
        label = "self-learn " + " ".join(argv)
        try:
            proc = await create_subprocess_exec(
                *cmd,
                env=full_env,
                stdout=asyncio_subprocess.PIPE,
                stderr=asyncio_subprocess.PIPE,
            )
        except OSError as exc:
            return RunResult(1, stderr=f"{label} failed to start: {exc}")
        # BOUNDED (M-H / C05): never a bare `await proc.communicate()` —
        # see `communicate_bounded` for the terminate -> grace -> kill ->
        # reap contract on timeout AND on this task being cancelled.
        stdout_b, stderr_b, exit_code = await communicate_bounded(
            proc, timeout=self._verb_timeout, kill_grace=self._kill_grace
        )
        return RunResult(
            exit_code=exit_code,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )
