"""U-sdk §3.9 `PS-1` — the ONE provider environment extension point.

`provider_env(spec) -> dict[str, str]` is the single place a provider
extension (`U-bedrock`) may grow environment variables for an SDK
session. `backend.py` assigns the return value straight to `options.env`
with no merge (`PS-a`), so an empty dict here contributes nothing
(`PS-b`'s leak test).

**The ledger-home rule (NORMATIVE, `Int-1`, restated 2026-09-19 by
U4b).** Provider resolution here reads `spec.settings_home` --- the
`SessionSpec.ledger_home` its producer named, falling back to
`spec.cwd` when it named none. `cwd` is where the session RUNS;
`settings_home` is the ledger its settings come from. A producer whose
session runs somewhere other than the ledger **must** pass
`ledger_home=`; the steward and the overseer do, because their sessions
run inside a cache stage directory.

This paragraph used to state the opposite rule --- that `spec.cwd` IS
the ledger home, because every shipped producer passed `cwd=home` ---
and warned that a producer which stopped doing so would break
resolution here. That warning was correct and was not heeded: the
steward and overseer surfaces, added 2026-09-14, pass a stage directory
as `cwd`, and from 2026-09-14 until 2026-09-19 every ledger setting on
those two surfaces silently resolved to its default. `cwd=home` is now
a FALLBACK for the three producers it still describes
(`worker.py`/`miner.py`/`analyst.py`), not an invariant.

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
    against `spec.settings_home` --- the ledger, not the working
    directory (see the module docstring's rule) --- and delegates the
    total A-0 rule to `session_env`; the anthropic leg and every non-sdk
    backend still return `{}` exactly, unchanged from the stub this file
    shipped as."""
    home = spec.settings_home
    resolution = provider.resolve(home, spec.surface)
    return provider.session_env(resolution, home=home)
