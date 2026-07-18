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

import os
import shlex
import shutil
import sys
from abc import ABC, abstractmethod
from asyncio import Lock, create_subprocess_exec, subprocess as asyncio_subprocess
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
    "extract_record_id",
    "resolve_self_learn_argv_prefix",
]


@dataclass(frozen=True)
class RunResult:
    """A completed verb invocation's outcome — exit status + stderr,
    never parsed stdout (07 §4 contract 2, carried into 09 §3: "never by
    parsing human-formatted stdout")."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""

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
    parsed stdout (07 §4 contract 2). A forced ledger refresh fires after
    every completed verb, scoped to the touched record when one is
    identifiable (:func:`extract_record_id`), else ``front`` (``push``,
    ``mine run``).
    """

    def __init__(
        self,
        *,
        home: Path,
        refresh_callback: Callable[[str], None] | None = None,
        argv_prefix: list[str] | None = None,
        env: dict[str, str] | None = None,
        interrupt_active_session: InterruptHook | None = None,
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
        ``env`` is also omitted — the production path)."""
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
        async with self._lock:
            if record_id is not None:
                # Interrupt-first (P1-4): awaited BEFORE the verb spawns,
                # never concurrently with it — the pane agent could
                # otherwise still hold live write permission on the exact
                # files the verb is about to git mv/git rm.
                await self._interrupt_active_session(record_id)
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
        stdout_b, stderr_b = await proc.communicate()
        exit_code = proc.returncode if proc.returncode is not None else 1
        return RunResult(
            exit_code=exit_code,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )
