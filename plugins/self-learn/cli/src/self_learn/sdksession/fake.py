"""U-engine sdksession — `fake.py` (spec §4.5 item 3): `FakeSdkClient`,
a stub satisfying the duck-typed client contract every other module in
this package drives (`connect`, `query`, `receive_response`,
`interrupt`, `disconnect`, and the private `_transport._process.pid`
chain `children.child_pid_of` walks).

This is what makes `LIB3` runnable at all: a test can drive a full
session against this library with `claude_agent_sdk` absent from
`sys.modules`, because nothing here or anywhere else in the package
imports it.

Import-bounded: stdlib only.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

__all__ = ["FakeSdkClient"]


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class _FakeTransport:
    def __init__(self, pid: int) -> None:
        self._process = _FakeProcess(pid)


class FakeSdkClient:
    """Scripted playback, no subprocess, no network. Construct with the
    messages `receive_response()` should yield; `interrupt()`/
    `disconnect()` can be made to hang (`hang_interrupt_secs`/
    `hang_disconnect_secs`) or raise (`interrupt_raises`/
    `disconnect_raises`) to drive the ladder's escalation paths."""

    def __init__(
        self,
        *,
        pid: int | None = 4242,
        messages: list[Any] | None = None,
        hang_interrupt_secs: float | None = None,
        hang_disconnect_secs: float | None = None,
        interrupt_raises: BaseException | None = None,
        disconnect_raises: BaseException | None = None,
        on_disconnect: "Callable[[], Awaitable[None]] | None" = None,
    ) -> None:
        self._transport = _FakeTransport(pid) if pid is not None else None
        self._messages = list(messages or [])
        self._hang_interrupt_secs = hang_interrupt_secs
        self._hang_disconnect_secs = hang_disconnect_secs
        self._interrupt_raises = interrupt_raises
        self._disconnect_raises = disconnect_raises
        self._on_disconnect = on_disconnect

        self.connect_calls = 0
        self.query_calls: list[str] = []
        self.interrupt_calls = 0
        self.disconnect_calls = 0
        self.disconnect_completed = False

    async def connect(self) -> None:
        self.connect_calls += 1

    async def query(self, prompt: str) -> None:
        self.query_calls.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        for message in self._messages:
            yield message

    async def interrupt(self) -> None:
        self.interrupt_calls += 1
        if self._hang_interrupt_secs is not None:
            await asyncio.sleep(self._hang_interrupt_secs)
        if self._interrupt_raises is not None:
            raise self._interrupt_raises

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self._hang_disconnect_secs is not None:
            await asyncio.sleep(self._hang_disconnect_secs)
        if self._disconnect_raises is not None:
            raise self._disconnect_raises
        if self._on_disconnect is not None:
            await self._on_disconnect()
        self.disconnect_completed = True
