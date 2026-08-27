"""U-engine sdksession — `result.py` (spec §4.2, §2.2a's first
skeleton-identical (1.000) pair): the `ResultMessage` error-detail
reduction, and the `ClaudeAgentOptions` capability probe.

`reduce_result_error` is duck-typed over `is_error`/`errors`/`result`/
`subtype` attributes -- it does not import `claude_agent_sdk.ResultMessage`
(`LIB1`/`LIB3`: the library must stay driveable with the SDK absent).
`supported_option_fields` takes the options CLASS as a parameter for the
same reason -- the caller (which already imports `claude_agent_sdk`)
passes `ClaudeAgentOptions` in; this module never imports it itself.

Import-bounded: stdlib only.
"""

from __future__ import annotations

import dataclasses
from typing import Any

__all__ = ["reduce_result_error"]
#: `supported_option_fields` is deliberately NOT exported (gate r1
#: N-1/M-1): zero importers anywhere -- `backend.py` keeps its own
#: `_supported_option_fields()` because the armor-pinned
#: `test_op9_.../test_ou4_...` monkeypatch `backend_mod.
#: _dataclass_fields` directly and require that LOCAL name to be read
#: at call time; a delegation would bypass the patch and break both
#: tests. Kept as a private module function (`result.
#: supported_option_fields` still callable), no longer claimed public.


def reduce_result_error(result_message: Any) -> str:
    """The ONE mechanism found skeleton-identical (ratio 1.000, §2.2a)
    across both engines: on an errored result, `errors` joined by
    `"; "` when non-empty, else `result` when truthy, else `subtype`.
    Callers on both sides still decide what to DO with the string (log
    template vs `PaneEvent.error`) -- only the reduction itself moves."""
    errors = result_message.errors
    if errors:
        return "; ".join(errors)
    if result_message.result:
        return result_message.result
    return result_message.subtype


def supported_option_fields(options_cls: type) -> set[str]:
    """`O-1a`-style feature detection via `dataclasses.fields`, never
    `hasattr` on an instance -- ported verbatim from
    `backend._supported_option_fields`, generalised to take the class as
    a parameter so this module never imports `claude_agent_sdk` itself."""
    return {f.name for f in dataclasses.fields(options_cls)}
