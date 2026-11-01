"""U-seam Sec 3.8 -- `FakeBackend`: records and simulates, scripted per
call with a list of `FakeStep`s. Ships in this unit because Sec 4's
criteria need it, and because the SDK unit will need exactly the same
recorder.

`F-c` -- NOT reachable from `backend_for`. There is no
`SELF_LEARN_BACKEND=fake`; tests inject it explicitly via
`write_session(spec, backend=FakeBackend([...]))`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .contract import LOG_TEMPLATES, Outcome, SessionSpec

__all__ = [
    "Writes", "Text", "Exits", "TimesOut", "NotFound", "Fails", "Streams", "ToolCall",
    "SessionOutcome", "FakeStep", "FakeBackend",
]


@dataclass(frozen=True)
class Writes:
    files: dict[Path, str]


@dataclass(frozen=True)
class Text:
    s: str


@dataclass(frozen=True)
class Exits:
    rc: int
    detail: str


@dataclass(frozen=True)
class TimesOut:
    pass


@dataclass(frozen=True)
class NotFound:
    pass


@dataclass(frozen=True)
class Fails:
    exc: OSError


@dataclass(frozen=True)
class ToolCall:
    """2026-10-31 (the ask agent): one call of the session's OWN tool
    `name` (`SessionSpec.mcp_toolset`) with `args`, made inside a
    `Streams` step; its reply lands in `FakeBackend.tool_replies`."""

    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class SessionOutcome(Outcome):
    """An `Outcome` that names its Claude Code session, as `SdkOutcome`
    does (2026-10-31): what a `Streams` step with a `session_id` returns."""

    session_id: str | None = None


@dataclass(frozen=True)
class Streams:
    """2026-10-31 (the ask agent, design r2 §3.3): a scripted turn that
    streams. Each entry of `events` is either a dict handed to
    `spec.on_event` (when the spec has one) or a `ToolCall` run through
    the session's own tools, in order; then `then` is performed as its own
    step. A `session_id` makes the outcome a `SessionOutcome`."""

    events: tuple[dict[str, Any] | ToolCall, ...]
    then: "FakeStep"
    session_id: str | None = None


FakeStep = Writes | Text | Exits | TimesOut | NotFound | Fails | Streams


class FakeBackend:
    """`F-a` -- records, in call order: every `SessionSpec` (`.specs`),
    every prompt (`.prompts`), and every doctrine (`.doctrines`, U-cleanup
    §7 -- the SDK's system-prompt append, replacing the CLI-flavoured
    `.argvs` this recorder carried before the closures were deleted)."""

    def __init__(self, steps: list[FakeStep]) -> None:
        self._steps = list(steps)
        self._index = 0
        self.specs: list[SessionSpec] = []
        self.prompts: list[str] = []
        self.doctrines: list[str | None] = []
        self.tool_replies: list[Any] = []

    def write_session(self, spec: SessionSpec) -> Outcome:
        return self._step(spec)

    def text_session(self, spec: SessionSpec) -> Outcome:
        return self._step(spec)

    # ----------------------------------------------------------- internals

    def _step(self, spec: SessionSpec) -> Outcome:
        self.specs.append(spec)
        self.prompts.append(spec.prompt)
        self.doctrines.append(spec.doctrine)

        step = self._steps[self._index]
        self._index += 1
        return self._perform(spec, step)

    def _perform(self, spec: SessionSpec, step: "FakeStep") -> Outcome:
        templates = LOG_TEMPLATES[spec.surface]

        if isinstance(step, Streams):
            for entry in step.events:
                if isinstance(entry, ToolCall):
                    toolset = spec.mcp_toolset
                    tool = next((t for t in toolset.tools if t.name == entry.name), None) \
                        if toolset is not None else None
                    if tool is None:
                        raise LookupError(f"FakeBackend: the session has no tool {entry.name!r}")
                    self.tool_replies.append(asyncio.run(tool.handler(dict(entry.args))))
                elif spec.on_event is not None:
                    spec.on_event(dict(entry))
            outcome = self._perform(spec, step.then)
            if step.session_id is None:
                return outcome
            return SessionOutcome(
                **{f.name: getattr(outcome, f.name) for f in fields(Outcome)},
                session_id=step.session_id,
            )

        if isinstance(step, Writes):
            for path, content in step.files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

        if isinstance(step, Text):
            return Outcome(ok=True, rc=0, stdout=step.s, detail="", failure=None)

        if isinstance(step, Exits):
            assert templates.exited is not None
            rendered = step.detail
            if templates.detail_strip:
                rendered = rendered.strip()
            if templates.detail_cap is not None:
                rendered = rendered[: templates.detail_cap]
            spec.log(templates.exited.format(label=spec.label, rc=step.rc, detail=rendered))
            return Outcome(
                ok=False, rc=step.rc, stdout="", detail=step.detail, failure="exit"
            )

        if isinstance(step, TimesOut):
            assert templates.timed_out is not None
            timeout_value = (
                spec.timeout_display if spec.timeout_display is not None else spec.timeout
            )
            spec.log(templates.timed_out.format(label=spec.label, timeout=timeout_value))
            return Outcome(ok=False, rc=None, stdout="", detail="", failure="timeout")

        if isinstance(step, NotFound):
            assert templates.not_found is not None
            spec.log(templates.not_found.format(label=spec.label))
            return Outcome(ok=False, rc=None, stdout="", detail="", failure="not-found")

        if isinstance(step, Fails):
            assert templates.os_error is not None
            spec.log(templates.os_error.format(label=spec.label, exc=step.exc))
            return Outcome(
                ok=False,
                rc=None,
                stdout="",
                detail=str(step.exc),
                failure="os-error",
                exc=step.exc,
            )

        raise TypeError(f"unknown FakeStep: {step!r}")
