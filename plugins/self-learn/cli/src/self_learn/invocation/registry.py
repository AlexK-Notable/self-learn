"""U-seam §3.7 — `backend_for`, the five-rung precedence chain, the lazy
`sdk` branch, and the two seam-level operations `write_session` /
`text_session`.

`I-b`: importing `..config` is the single permitted upward import in this
package, and only for the ledger-config rungs of the precedence chain.
`config.py` imports nothing from `self_learn`, so no cycle is created.
"""

from __future__ import annotations

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
    `override:…` / the bare word `default`). Six rungs, override
    (specific then general) before env (specific then general) before
    config (`Rs-a1`'s termination, unchanged) before default.
    `home=None` skips the config rung entirely (matches `backend_for`'s
    own pre-existing optionality).

    Code-gate fold r1 (MAJOR-1/MAJOR-4): now calls the SAME pure
    cascade `settings.resolve_setting` calls for a paired entry,
    `config.paired_cascade` -- previously this function hand-rolled
    all six rungs independently, and `resolve_setting`'s single-key
    sequence never looked at the general sibling at all (MAJOR-1: the
    registry face reported `"default"` even when the general key
    answered). The config rung still delegates verbatim to
    :func:`config.invocation_backend` (minor-2: that function SURVIVES,
    unchanged, as the Rs-a1 termination delegate this cascade uses
    internally via `paired_leaf`), so `Rs-a1` (an EMPTY per-surface
    config value terminates at the default WITHOUT consulting the
    general config key; an ABSENT per-surface key falls through to the
    general key) is unchanged.

    The source label's CONFIG half now matches the registry face's own
    vocabulary (`config:invocation.backend_<surface>` / `config:
    invocation.backend`, not the old bare `config:backend_<surface>` /
    `config:backend`) -- MAJOR-1's witness requires the two faces to
    report an IDENTICAL `(value, source)`, which a bare-vs-dotted label
    mismatch would otherwise still fail on the config rungs even after
    the cascade itself was shared. `backend_for` below strips the
    section prefix before handing the bare key to `_resolve`'s existing
    (pinned) warn text, so that text is unaffected."""
    selector = SELECTOR_FOR_SURFACE.get(surface, surface)
    selector_var = f"SELF_LEARN_BACKEND_{selector}"
    specific_name = f"invocation.backend_{surface}"

    found = config.paired_cascade(
        home,
        specific_name=specific_name,
        general_name="invocation.backend",
        specific_env_var=selector_var,
        general_env_var="SELF_LEARN_BACKEND",
        section="invocation",
        specific_config_key=f"backend_{surface}",
        general_config_key="backend",
        label=config.INVOCATION_BACKEND_LABEL,
    )
    if found is None:
        return DEFAULT_BACKEND_FOR_SURFACE.get(surface, "sdk"), "default"
    value, rung, matched = found
    if rung.startswith("override"):
        return value, f"override:{matched}"
    if rung.startswith("env"):
        return value, f"env:{matched}"
    return value, f"config:{matched}"


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
    from it before calling `_resolve`. Code-gate fold r1 (MAJOR-1): the
    config label is now `config:invocation.<key>` (matching the
    registry face's own `config:<section>.<key>` vocabulary, not the
    old bare `config:<key>`), so the STRIPPED prefix here is
    `"config:invocation."` (not just `"config:"`) -- `_resolve`'s own
    pinned message still builds `f'invocation.{source} must be one of
    sdk...'` from the bare key, unaffected by this label's own vocabulary
    change."""
    raw_value, source = resolve_backend_raw(home, surface)
    if source == "default":
        return _resolve(surface, raw_value, source="the built-in default", is_config=False)
    if source.startswith("config:"):
        bare_key = source[len("config:invocation.") :]
        return _resolve(surface, raw_value, source=bare_key, is_config=True)
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
