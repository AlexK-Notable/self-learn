"""A stand-in for the miner's model pass, for tests that only need to see what
the miner would have sent: the session engine's seam (`invocation.registry.
backend_for`) is replaced by a backend that answers every call with an empty,
valid output.

``shim_reader(monkeypatch)`` returns a list with one string per ``miner.run``
made after it: every session prompt that run sent, joined. Tests read
``prompts[0]`` as "what the first run was shown", as they did when one reader
call carried the whole night.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from self_learn import invocation, miner
from self_learn.mining import contract


@dataclass
class _Outcome:
    ok: bool = True
    stdout: str = ""
    detail: str = ""
    failure: str | None = None
    rc: int | None = 0
    cost_usd: float | None = None
    turns: int | None = 3
    session_id: str | None = None
    usage_first_response: dict | None = None
    usage_session: dict | None = None
    denials: tuple = ()
    failure_class: str | None = None
    transcript: dict | None = None


EMPTY_OUTPUT = json.dumps({"contract": contract.MODEL_CONTRACT, "lessons": [], "sightings": [], "rule_checks": []})


def shim_reader(monkeypatch) -> list[str]:
    runs: list[str] = []

    class _Backend:
        def text_session(self, spec):
            runs[-1] += "\n" + spec.prompt
            return _Outcome(stdout=EMPTY_OUTPUT)

        def write_session(self, spec):  # pragma: no cover - never reached
            raise AssertionError("the session engine calls text_session only")

    backend = _Backend()
    monkeypatch.setattr(invocation.registry, "backend_for", lambda *a, **k: backend)
    real_run = miner.run

    def run(*args, **kwargs):
        runs.append("")
        kwargs.setdefault("no_push", True)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(miner, "run", run)
    return runs
