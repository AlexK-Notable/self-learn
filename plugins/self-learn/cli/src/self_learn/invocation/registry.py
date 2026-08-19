"""U-seam §3.7 — `backend_for`, the five-rung precedence chain, the lazy
`sdk` branch, and the two seam-level operations `write_session` /
`text_session`.

`I-b`: importing `..config` is the single permitted upward import in this
package, and only for the ledger-config rungs of the precedence chain.
`config.py` imports nothing from `self_learn`, so no cycle is created.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import config
from .cli import CliBackend
from .contract import (
    LOG_TEMPLATES,
    SELECTOR_FOR_SURFACE,
    SURFACES,
    Backend,
    BackendUnavailable,
    Outcome,
    SessionSpec,
)

__all__ = ["KNOWN_BACKENDS", "backend_for", "write_session", "text_session"]

KNOWN_BACKENDS = ("cli", "sdk")

_CLI_BACKEND = CliBackend()

#: §3.7.4 — byte-pinned.
_SDK_UNAVAILABLE_MESSAGE = (
    'the "sdk" invocation backend is not built yet — install it with:\n'
    "    pip install 'self-learn-cli[sdk]'"
)


def _resolve(surface: str, value: str, *, source: str, is_config: bool) -> Backend:
    """§3.7.2 — fail-closed on an unknown value: warns once on stderr and
    falls back to `cli`. `R-c`: the config-flavored spelling is emitted
    THROUGH `config._warn`, never re-spelled as a local literal — one
    register, one owner for the operator-facing prefix."""
    if value not in KNOWN_BACKENDS:
        if is_config:
            config._warn(
                f'invocation.{source} must be one of cli, sdk; got {value!r} — using "cli"'
            )
        else:
            print(
                f'self-learn: unknown invocation backend {value!r} in {source} — using "cli"',
                file=sys.stderr,
            )
        return _CLI_BACKEND
    if value == "sdk":
        try:
            from ..invocation_sdk import SdkBackend
        except ImportError as exc:
            raise BackendUnavailable(_SDK_UNAVAILABLE_MESSAGE) from exc
        return SdkBackend()
    return _CLI_BACKEND


def backend_for(surface: str, *, home: Path | str | None = None) -> Backend:
    """§3.7.1 — resolves in order, first hit wins: `SELF_LEARN_BACKEND_
    <SELECTOR>` env, `SELF_LEARN_BACKEND` env, `config.yaml`'s per-surface
    key, `config.yaml`'s general key, the built-in default `"cli"`.

    `R-a`: an EMPTY OR UNSET value at a rung is "no answer" and falls
    through silently — an empty string is not an unknown value."""
    selector = SELECTOR_FOR_SURFACE.get(surface, surface)

    selector_var = f"SELF_LEARN_BACKEND_{selector}"
    value = os.environ.get(selector_var)
    if value:
        return _resolve(surface, value, source=selector_var, is_config=False)

    value = os.environ.get("SELF_LEARN_BACKEND")
    if value:
        return _resolve(surface, value, source="SELF_LEARN_BACKEND", is_config=False)

    if home is not None:
        result = config.invocation_backend(home, surface)
        if result is not None:
            key, value = result
            if value:
                return _resolve(surface, value, source=key, is_config=True)

    return _CLI_BACKEND


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
            backend = backend_for(spec.surface, home=spec.cwd)
        except BackendUnavailable as exc:
            templates = LOG_TEMPLATES[spec.surface]
            spec.log(templates.unavailable.format(label=spec.label, exc=exc))
            return Outcome(
                ok=False, rc=None, stdout="", detail=str(exc), failure="unavailable", exc=exc
            )
    return getattr(backend, method)(spec)


def write_session(spec: SessionSpec, *, backend: Backend | None = None) -> Outcome:
    """§3.2 `S-a`/`S-b` — never raises, except the one deliberate leg
    (`T-c`) a `CliBackend` on the analyst surface lets an `OSError`
    escape, and that surface never reaches `write_session`."""
    return _dispatch(spec, backend, "write_session")


def text_session(spec: SessionSpec, *, backend: Backend | None = None) -> Outcome:
    """§3.2 `S-a`/`S-b` — the analyst's operation; `S-b`'s one exception
    (a bare `OSError` propagating) lives here."""
    return _dispatch(spec, backend, "text_session")
