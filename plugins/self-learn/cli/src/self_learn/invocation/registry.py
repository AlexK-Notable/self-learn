"""SDK-only invocation dispatch and seam-level session operations.

Backend selectors were retired on 2026-10-24; diagnostics report old keys.
"""

from __future__ import annotations

from pathlib import Path

from .contract import (
    LOG_TEMPLATES,
    SURFACES,
    Backend,
    BackendUnavailable,
    Outcome,
    SessionSpec,
)

__all__ = [
    "KNOWN_BACKENDS",
    "backend_for",
    "write_session",
    "text_session",
]

KNOWN_BACKENDS = ("sdk",)

#: §3.7.4 — byte-pinned.
_SDK_UNAVAILABLE_MESSAGE = (
    'the "sdk" invocation backend is not built yet — install it with:\n'
    "    pip install 'self-learn-cli[sdk]'"
)

def backend_for(surface: str, *, home: Path | str | None = None) -> Backend:
    """Every invocation uses the SDK; retired selection keys have no effect."""
    try:
        from ..invocation_sdk import SdkBackend
    except ImportError as exc:
        raise BackendUnavailable(_SDK_UNAVAILABLE_MESSAGE) from exc
    return SdkBackend()


def _dispatch(spec: SessionSpec, backend: Backend | None, method: str) -> Outcome:
    """`S-c`: an unknown `spec.surface` is validated BEFORE any table
    lookup and returns an `Outcome` — never a `KeyError` from
    `LOG_TEMPLATES[...]`. Nothing is logged on this path (no template set
    can be selected for an unknown surface)."""
    if spec.surface not in SURFACES:
        return Outcome(
            ok=False,
            rc=None,
            stdout="",
            detail=f"unknown invocation surface {spec.surface!r}",
            failure="unavailable",
        )
    if backend is None:
        try:
            # U4b (2026-09-19): the ledger the settings come from, not
            # the directory the session runs in -- `spec.settings_home`
            # falls back to `cwd` for the three producers that pass
            # `cwd=home`, and is the stage-free ledger path for the
            # steward and the overseer, whose `cwd` holds no config.yaml.
            backend = backend_for(spec.surface, home=spec.settings_home)
        except BackendUnavailable as exc:
            templates = LOG_TEMPLATES[spec.surface]
            spec.log(templates.unavailable.format(label=spec.label, exc=exc))
            return Outcome(
                ok=False, rc=None, stdout="", detail=str(exc), failure="unavailable", exc=exc
            )
    return getattr(backend, method)(spec)


def write_session(spec: SessionSpec, *, backend: Backend | None = None) -> Outcome:
    """§3.2 `S-a`/`S-b` — never raises, except the one deliberate leg
    (`T-c`) the analyst surface's bare `OSError` is let escape uncaught,
    and that surface never reaches `write_session`."""
    return _dispatch(spec, backend, "write_session")


def text_session(spec: SessionSpec, *, backend: Backend | None = None) -> Outcome:
    """§3.2 `S-a`/`S-b` — the analyst's operation; `S-b`'s one exception
    (a bare `OSError` propagating) lives here."""
    return _dispatch(spec, backend, "text_session")
