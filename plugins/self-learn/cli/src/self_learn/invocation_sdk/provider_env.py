"""U-sdk §3.9 `PS-1` — the ONE provider environment extension point.

`provider_env(spec) -> dict[str, str]` is the single place a provider
extension (`U-bedrock`) may grow environment variables for an SDK
session. `backend.py` assigns the return value straight to `options.env`
with no merge (`PS-a`), so an empty dict here contributes nothing
(`PS-b`'s leak test).

**`U-bedrock`'s `cwd=home` invariant (NORMATIVE, `Int-1`).** This
extension point receives only a `SessionSpec`, which has no `home`
field (`invocation/contract.py`). The one channel into `provider.py`'s
resolution is `spec.cwd`: every shipped `SessionSpec` producer
constructs it with `cwd=home` --- `worker.py:3127`, `miner.py:777`,
`analyst.py:247` are the three call sites, verified at this unit's
build. **A new `SessionSpec` producer that stops passing the ledger
home as `cwd` breaks provider resolution at this extension point**;
there is no other channel here to reach it.

`ProviderRefused` (raised by `provider.session_env` on a refusing
resolution) is deliberately NOT caught here --- it propagates out of
this function into `backend.py`'s `_drive`, where the guarded call
(`In-d`) converts it into the seam's `Outcome` before any transport is
reached. This module performs the WIRING only; the conversion owns a
home one level up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import provider

if TYPE_CHECKING:
    from ..invocation.contract import SessionSpec

__all__ = ["provider_env"]


def provider_env(spec: "SessionSpec") -> dict[str, str]:
    """The ONE point where provider environment variables enter an SDK
    session. `U-bedrock` owns this function's body; no other module in
    `invocation_sdk/` may grow provider logic. Resolves the provider
    using `spec.cwd` as the ledger home (see the module docstring's
    invariant) and delegates the total A-0 rule to `session_env` --- the
    anthropic leg and every non-sdk backend still return `{}` exactly,
    unchanged from the stub this file shipped as."""
    resolution = provider.resolve(spec.cwd, spec.surface)
    return provider.session_env(resolution, home=spec.cwd)
