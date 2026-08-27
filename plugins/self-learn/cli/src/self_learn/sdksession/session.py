"""U-engine sdksession — `session.py` (spec §4.2): `SdkSession` --
connect, query, drive one turn, yield raw SDK messages. The transport
loop, not the vocabulary: every message-to-EVENT mapping (CLI
`Outcome`/`EventLog` bookkeeping, UI `PaneEvent`s) stays with its
client (§4.4) -- this class does nothing except call the same three
`client` methods each engine already calls directly, so wrapping a
client in it changes no observable behaviour.

`client` is typed `Any` throughout -- this module never imports
`claude_agent_sdk` (`LIB1`/`LIB3`).

Import-bounded: stdlib only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

__all__ = ["SdkSession"]


class SdkSession:
    """Wraps one `client` (a `claude_agent_sdk.ClaudeSDKClient`, or
    :class:`~self_learn.sdksession.fake.FakeSdkClient` in a test) for
    exactly one connect/query/drive cycle. Holds no policy, no
    vocabulary, no retry logic -- callers that want a kill ladder use
    `teardown.py`; callers that want sidecars/sweeps use `children.py`.
    """

    def __init__(self, client: Any) -> None:
        self.client = client

    async def connect(self) -> None:
        await self.client.connect()

    async def query(self, prompt: str) -> None:
        await self.client.query(prompt)

    async def drive(self) -> AsyncIterator[Any]:
        """Yield every raw message from `client.receive_response()`,
        unmapped. Tolerates nothing itself -- an exception here is the
        caller's to catch, exactly as today (each engine's own
        exception handling around its drain loop is untouched)."""
        async for message in self.client.receive_response():
            yield message
