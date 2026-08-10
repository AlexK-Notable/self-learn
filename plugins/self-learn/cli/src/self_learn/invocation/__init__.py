"""U-seam §3.1 — the invocation seam. Re-exports only; this module is
the package's public surface. Every `claude` process spawn in the CLI
lives behind this package (§1)."""

from __future__ import annotations

from .cli import CliBackend
from .contract import (
    FAILURE_KINDS,
    LOG_TEMPLATES,
    SELECTOR_FOR_SURFACE,
    SURFACES,
    TRANSPORT,
    Backend,
    BackendUnavailable,
    Containment,
    LogTemplates,
    Outcome,
    SessionSpec,
    Surface,
    TransportSpec,
    containment_for,
    containment_permissions,
    containment_rules,
    DEGRADED_WORKER_CONTAINMENT,
)
from .fake import Exits, Fails, FakeBackend, FakeStep, NotFound, Text, TimesOut, Writes
from .registry import KNOWN_BACKENDS, backend_for, text_session, write_session

__all__ = [
    "Backend",
    "BackendUnavailable",
    "Containment",
    "containment_for",
    "containment_permissions",
    "containment_rules",
    "DEGRADED_WORKER_CONTAINMENT",
    "FAILURE_KINDS",
    "LOG_TEMPLATES",
    "LogTemplates",
    "Outcome",
    "SELECTOR_FOR_SURFACE",
    "SURFACES",
    "SessionSpec",
    "Surface",
    "TRANSPORT",
    "TransportSpec",
    "CliBackend",
    "FakeBackend",
    "FakeStep",
    "Writes",
    "Text",
    "Exits",
    "TimesOut",
    "NotFound",
    "Fails",
    "KNOWN_BACKENDS",
    "backend_for",
    "write_session",
    "text_session",
]
