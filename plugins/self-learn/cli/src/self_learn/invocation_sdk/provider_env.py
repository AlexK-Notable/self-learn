"""U-sdk §3.9 `PS-1` — the ONE provider environment extension point.

`provider_env(spec) -> dict[str, str]` is the single place a provider
extension (`U-bedrock`) may grow environment variables for an SDK
session. The anthropic leg -- this file, as shipped by `U-sdk` -- always
returns `{}`; `backend.py` assigns the return value straight to
`options.env` with no merge (`PS-a`), so an empty dict here contributes
nothing (`PS-b`'s leak test).

Import-bounded to stdlib only (§3.1's table): the `SessionSpec` type
named in the signature below is imported only under `TYPE_CHECKING`, so
this module never actually imports anything from `..invocation` at
runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..invocation.contract import SessionSpec

__all__ = ["provider_env"]


def provider_env(spec: "SessionSpec") -> dict[str, str]:
    """The ONE point where provider environment variables enter an SDK
    session. The anthropic leg contributes nothing. `U-bedrock` owns this
    function's body; no other module in `invocation_sdk/` may grow
    provider logic."""
    del spec
    return {}
