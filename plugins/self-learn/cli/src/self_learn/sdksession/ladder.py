"""U-engine sdksession — `ladder.py` (spec §4.2): the two tuned timing
constants shared by both engines' teardown ladders, defined exactly
once. Both `invocation_sdk/lifecycle.py` and `ui engine/sdk.py` bind
their own module-level names to THESE objects (`LAD2`/`LAD3` — identity,
not a copied value), so a test that reads either module's name is
reading this one.

Import-bounded: stdlib only, no imports at all beyond `__future__`.
"""

from __future__ import annotations

__all__ = ["INTERRUPT_GRACE_SECS", "KILL_SECS"]

#: Ported verbatim from `invocation_sdk/lifecycle.py`'s / `ui engine/
#: sdk.py`'s tuned 2026-07-18 defaults. Both engines' own module-level
#: constants (`lifecycle.INTERRUPT_GRACE_SECS`/`KILL_SECS`,
#: `sdk.DEFAULT_INTERRUPT_GRACE_SECS`/`DEFAULT_INTERRUPT_KILL_SECS`) are
#: bound to these exact float objects.
INTERRUPT_GRACE_SECS = 1.0
KILL_SECS = 2.5
