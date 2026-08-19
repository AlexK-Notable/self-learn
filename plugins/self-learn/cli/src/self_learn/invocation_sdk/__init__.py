"""U-sdk — the SDK backend. Re-exports only (`Loc-1`'s table): this
module is the package's public surface, and `registry.py`'s lazy `sdk`
branch (`Reg-2`) imports exactly this."""

from __future__ import annotations

from .backend import SdkBackend, SdkOutcome

__all__ = ["SdkBackend", "SdkOutcome"]
