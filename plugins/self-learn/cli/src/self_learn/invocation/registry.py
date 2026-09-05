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
from .contract import (
    DEFAULT_BACKEND_FOR_SURFACE,
    LOG_TEMPLATES,
    SELECTOR_FOR_SURFACE,
    SURFACES,
    Backend,
    BackendUnavailable,
    Outcome,
    SessionSpec,
)

__all__ = [
    "KNOWN_BACKENDS",
    "backend_for",
    "resolve_backend_raw",
    "write_session",
    "text_session",
]

KNOWN_BACKENDS = ("sdk",)

#: §3.7.4 — byte-pinned.
_SDK_UNAVAILABLE_MESSAGE = (
    'the "sdk" invocation backend is not built yet — install it with:\n'
    "    pip install 'self-learn-cli[sdk]'"
)

#: U-cleanup §5 — the `cli` backend was retired; a selection of it at any
#: rung is a NAMED refusal, never folded into the generic unknown-value
#: path (whose whole design is "unknown means cli", which stops being
#: sayable once `cli` no longer exists).
_CLI_RETIRED_MESSAGE = (
    'the "cli" invocation backend was removed in U-cleanup — every surface '
    "now runs on the Agent SDK. Unset SELF_LEARN_BACKEND[_<SELECTOR>], or "
    "remove invocation.backend[_<surface>] from <ledger-home>/config.yaml."
)


def _resolve(surface: str, value: str, *, source: str, is_config: bool) -> Backend:
    """§3.7.2 — fail-closed on an unknown value: warns once on stderr and
    falls back to `sdk`. `R-c`: the config-flavored spelling is emitted
    THROUGH `config._warn`, never re-spelled as a local literal — one
    register, one owner for the operator-facing prefix. U-cleanup §5: a
    `cli` value is NOT an unknown value — it is a named, retired backend,
    and gets its own refusal rather than the generic fallback."""
    if value == "cli":
        raise BackendUnavailable(_CLI_RETIRED_MESSAGE)
    if value not in KNOWN_BACKENDS:
        if is_config:
            config._warn(
                f'invocation.{source} must be one of sdk; got {value!r} — using "sdk"'
            )
        else:
            print(
                f'self-learn: unknown invocation backend {value!r} in {source} — using "sdk"',
                file=sys.stderr,
            )
    try:
        from ..invocation_sdk import SdkBackend
    except ImportError as exc:
        raise BackendUnavailable(_SDK_UNAVAILABLE_MESSAGE) from exc
    return SdkBackend()


def resolve_backend_raw(home: Path | str | None, surface: str) -> tuple[str, str]:
    """M-S (U-settings' provider/backend-selection amendment, S-58,
    `03-decisions.md` row S-58, r3-M1/r3-M2) — a PURE resolver: emits
    NOTHING (no print, no warn, no fold, no raise), just the raw
    winning value and a PREFIXED source label (`env:…` / `config:…` /
    `override:…` / the bare word `default`). The two-rung override
    prefix ahead of today's five-rung chain, both specific-before-
    general (MAJOR-5): override(specific) -> override(general) ->
    env(specific) -> env(general) -> config (first-present-key,
    `Rs-a1`'s termination, unchanged) -> default. `home=None` skips the
    config rung entirely (matches `backend_for`'s own pre-existing
    optionality).

    `Rs-a1` (unchanged, now inherited by construction): an EMPTY
    per-surface config value terminates the chain at the default
    WITHOUT ever consulting the general config key -- delegated
    verbatim to :func:`config.invocation_backend`, which already
    returns the FIRST PRESENT key regardless of its value; an ABSENT
    per-surface key falls through to the general key.

    The override rungs use TRUTHINESS, matching every other rung in
    this cascade (`R-a`: an empty value is "no answer") -- NOT
    `resolve_setting`'s `is not None` presence rule, which exists there
    only to let a *registry* caller write a deliberate empty string via
    :func:`settings.override`; nothing here calls that API, so there is
    no programmatic empty-string case to preserve, and treating an
    empty `SELF_LEARN_OVERRIDE_INVOCATION_BACKEND[_<surface>]` as "no
    answer" keeps this cascade's own empty-is-absent rule uniform end
    to end."""
    selector = SELECTOR_FOR_SURFACE.get(surface, surface)
    selector_var = f"SELF_LEARN_BACKEND_{selector}"

    override_specific = config.override_env_var(f"invocation.backend_{surface}")
    value = os.environ.get(override_specific)
    if value:
        return value, f"override:invocation.backend_{surface}"

    override_general = config.override_env_var("invocation.backend")
    value = os.environ.get(override_general)
    if value:
        return value, "override:invocation.backend"

    value = os.environ.get(selector_var)
    if value:
        return value, f"env:{selector_var}"

    value = os.environ.get("SELF_LEARN_BACKEND")
    if value:
        return value, "env:SELF_LEARN_BACKEND"

    if home is not None:
        result = config.invocation_backend(home, surface)
        if result is not None:
            key, cfg_value = result
            if cfg_value:
                return cfg_value, f"config:{key}"

    return DEFAULT_BACKEND_FOR_SURFACE.get(surface, "sdk"), "default"


def backend_for(surface: str, *, home: Path | str | None = None) -> Backend:
    """§3.7.1 — resolves in order, first hit wins: an active
    `settings.override` on `invocation.backend[_<surface>]`,
    `SELF_LEARN_BACKEND_<SELECTOR>` env, `SELF_LEARN_BACKEND` env,
    `config.yaml`'s per-surface key, `config.yaml`'s general key, the
    built-in default `"sdk"` (M-S: the override rungs are new; every
    rung after them is unchanged).

    `R-a`: an EMPTY OR UNSET value at a rung is "no answer" and falls
    through silently — an empty string is not an unknown value.

    Fed by :func:`resolve_backend_raw` with ONE MECHANICAL TRANSLATION
    (r4-n1): that function returns a PREFIXED source label
    (`env:…`/`config:…`/`override:…`/`default`), while `_resolve`
    (this module's EXISTING emitter, unchanged, called exactly as
    before) wants the BARE name the pinned literals print with no
    prefix -- so the prefix is stripped here and `is_config` derived
    from it before calling `_resolve`."""
    raw_value, source = resolve_backend_raw(home, surface)
    if source == "default":
        return _resolve(surface, raw_value, source="the built-in default", is_config=False)
    if source.startswith("config:"):
        return _resolve(surface, raw_value, source=source[len("config:") :], is_config=True)
    if source.startswith("env:"):
        return _resolve(surface, raw_value, source=source[len("env:") :], is_config=False)
    assert source.startswith("override:"), f"unreachable resolve_backend_raw source: {source!r}"
    override_name = source[len("override:") :]
    return _resolve(surface, raw_value, source=config.override_env_var(override_name), is_config=False)


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
    (`T-c`) the analyst surface's bare `OSError` is let escape uncaught,
    and that surface never reaches `write_session`."""
    return _dispatch(spec, backend, "write_session")


def text_session(spec: SessionSpec, *, backend: Backend | None = None) -> Outcome:
    """§3.2 `S-a`/`S-b` — the analyst's operation; `S-b`'s one exception
    (a bare `OSError` propagating) lives here."""
    return _dispatch(spec, backend, "text_session")
