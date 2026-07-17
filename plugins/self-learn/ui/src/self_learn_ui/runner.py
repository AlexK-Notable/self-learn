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
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = ["FakeRunner", "NotWiredRunner", "RunResult", "VerbRunner"]


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

    @abstractmethod
    async def run(self, argv: list[str]) -> RunResult:
        """Run ``self-learn <argv...>`` and return its outcome. Never
        raises for a non-zero exit — that is an ordinary :class:`RunResult`
        (task pin: verb failures are explicit states, never exceptions
        routes.py must catch ad hoc)."""
        raise NotImplementedError


class NotWiredRunner(VerbRunner):
    """The production default until U4 lands: any call is a programming
    error (a mutating route was reached with no real runner injected),
    surfaced loudly rather than silently no-op'd."""

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
