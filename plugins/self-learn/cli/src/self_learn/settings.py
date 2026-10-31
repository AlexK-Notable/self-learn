"""U-settings Phase 1 -- the settings registry (docs/specs/self-learn/
drafts/settings-surface-spec.md's reframe, 2026-09-01): the operator's
real steering wheel is ~46 ``SELF_LEARN_*`` env vars, invisible and
undiscoverable, while ``config.py`` today knows only four sections
(``one_motion_route``, ``hosts``, ``provider``, ``invocation``) and
every other setting is env-only with no config fallback and no
``doctor`` visibility.

This module generalizes the ONE pattern that already works --
``provider.py``'s per-resolved-value source string (``Prov-1``,
``A-0``) -- rather than inventing a second mechanism.
:func:`resolve_setting` reuses ``provider.py``'s exact source
vocabulary verbatim: ``"env:NAME"`` / ``"config:section.key"`` /
``"default"`` -- plus the ``"override:NAME"`` label (below) and, for a
gated entry, ``"inactive (provider=<name>)"``.

**Two precedence DIRECTIONS, ONE mechanism (M-S, ``docs/specs/
self-learn/03-decisions.md`` S-58's amendment, superseding this
docstring's own earlier "two directions, two mechanisms" framing).**
:class:`Setting` carries a ``direction``: ``"config-first"`` (every
entry that predates this amendment) resolves **override > config.yaml
> env > default** -- the committed config is the single source of
truth, and an env var only fills a gap config.yaml leaves silent.
``"env-first"`` (the provider/backend-selection entries below --
``provider.name``, ``provider.bedrock.*``, ``sdk.cli_path``, ``models.*``)
resolves **override > env > config.yaml > default** -- these are
emergency-rollback switches, and an operator must be able to override
one from a live shell without waiting on a commit+sync round-trip. The
two DIRECTIONS still coexist on purpose, matching each key's own
operational trade -- but where this module used to say a SECOND,
independent mechanism governed the env-first keys (``provider.py``'s
own hand-rolled resolvers, ``invocation/registry.py``'s own backend
cascade), that second mechanism is now RETIRED: every one of those
keys resolves through THIS registry's ONE :func:`resolve_setting`,
with its own ``direction`` field choosing the rung order. The one
exception is the runtime provider-name resolver (:func:`provider._resolve_provider`),
which preserves its stderr warnings for unknown live values. Backend selectors
were removed on 2026-10-24: runtime dispatch always uses SDK, and diagnostics
name retired keys without reading their values as choices.

**``enabled_when`` (M-S).** An optional predicate over the resolved
``provider.name``, evaluated BEFORE even the override rung: ``False``
skips every rung and resolves straight to the entry's own default,
source label ``f"inactive (provider={value})"`` -- the six
``provider.bedrock.*`` entries use this to stay silently inert under
``provider=anthropic``, expressed in the registry instead of a raw
``if provider == "bedrock":`` gate. Never set on ``provider.name``
itself (self-referential).

**``accepts``/``accepts_hint`` (M-S).** A separate WRITE-path refusal
gate, checked by :func:`config_set` on the PARSED value, BEFORE
``validate`` runs -- ``validate`` stays the READ-path clamp it always
was (folds an already-committed off-whitelist value in place, exactly
like every other clamping entry); ``accepts`` refuses the write
outright, so a clamping ``validate`` can never launder a refused write
into an accepted, silently different one. Only ``provider.name`` and
the ``invocation.backend`` family use this.

**A third rung, above both (Blocker fix, review 2026-09-01): process
overrides via** :func:`override`. **The flip conflated two different
things that both happened to travel through ``os.environ``:** (1) an
operator's AMBIENT environment -- a preference, correctly demoted below
config.yaml by the flip above -- and (2) a PROCESS asserting a value on
ITSELF for a span -- not a preference, a runtime invariant that must
hold no matter what any file says. Before the flip both worked,
accidentally, because env beat config; after it, (2) broke, because it
was smuggled through the same channel as (1).
:func:`serve._worker_autokick_disabled` is the motivating case: it
must be able to neutralise the worker-autokick kill switch for a span
regardless of what ``config.yaml`` says, in EVERY process that
inherits the span (parent and any detached child alike -- see
:func:`override`'s own docstring for why this has to be a real,
namespaced env var, not an in-process dict). Precedence is now
**override channel ``>`` config.yaml ``>`` env ``>`` default**, with
source label ``"override:NAME"`` so ``doctor settings`` shows when a
running process is asserting one.

**Scope discipline (Phase 1, root-cause fix, not a display layer).** A
setting only gets a :class:`Setting` row here if some real call site was
rewired to resolve THROUGH it -- see each registry entry's home module.
A registry that ``doctor`` renders but the actual consumer function
ignores would report a config.yaml fallback that does not take effect:
exactly the loud-success-on-a-broken-mechanism shape this codebase's own
history warns against (U-glob/U-armor's canaries). Settings that are
internal/test-only (kill switches for debugging containment itself, or
env vars tests use purely to avoid a real timeout/real host path) are
NOT registered here -- ``config.yaml`` is the OPERATOR's policy surface
(``config.py``'s own module docstring), not a place to expose developer
escape hatches. The full classification (which of the ~46 audited env
vars landed in which bucket, and why) is recorded in the U-settings
Phase 1 build report, not duplicated here.

**No caching, anywhere in this module (load-bearing, not style --
necessary, but on its own no longer SUFFICIENT).**
:func:`resolve_setting` re-reads ``os.environ`` and ``config.yaml`` on
every call, the same discipline ``config.py`` already holds for every
reader in it; without that, no mid-process mutation of ANY rung could
ever be seen. But under config-wins, no-caching alone stopped being
enough to keep ``serve._worker_autokick_disabled()``'s mechanism
working: that helper used to mutate ``os.environ`` at the ENV rung,
and once config.yaml could outrank env, a saved ``worker.autokick:
true`` would be re-read fresh on every call too -- and WIN, silently
defeating the mutation. Fresh reads guarantee a mutation is SEEN; they
say nothing about which rung's mutation wins. That is what the third
rung above (:func:`override`) is for -- it sits where no config.yaml
value can outrank it, so freshness and precedence are both satisfied.

**UI settings (``SELF_LEARN_PANE_*``, ``SELF_LEARN_UI_*``) are OUT OF
SCOPE for Phase 1.** They live in the separate ``self_learn_ui``
package with their own eagerly-validated env loader
(``self_learn_ui.env.load_env``, which already raises a typed
``EnvError`` on a malformed value -- not silently invisible the way the
CLI-side gap vars are). Wiring them through this registry is Phase 2's
job (the UI settings page), alongside the UI itself; duplicating their
defaults into this table now would let the two drift.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import socket
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from . import config, gitops, intents, ledger

__all__ = [
    "Kind",
    "SettingValue",
    "Setting",
    "SettingRow",
    "REGISTRY",
    "resolve_setting",
    "by_name",
    "unknown_keys",
    "unknown_override_vars",
    "preflight",
    "override",
    # U-settings Phase 2 -- the `config get`/`set`/`unset` verb group.
    "SettingsError",
    "UnknownSettingError",
    "InvalidSettingValueError",
    "NoConfigRungError",
    "setting_row",
    "config_set",
    "config_unset",
]

Kind = Literal["str", "int", "float", "bool"]

#: Every value this registry can ever resolve to -- REPLACES the bare
#: `object` the review's M-1 flagged (24 pyright errors against a
#: 1-error baseline, root-caused to `resolve_setting`'s old `-> tuple
#: [object, str]`). `object` is unbounded (any Python value); this is
#: the actual closed set `_parse_env_value`/`_parse_config_value` can
#: ever produce. A registry entry's OWN `kind` narrows this further
#: still (a "float" entry only ever resolves to `float`, never `str`),
#: but that per-entry precision is not statically knowable through
#: `by_name`'s string-keyed lookup without per-name `@overload`
#: boilerplate this Phase doesn't warrant -- so each numeric `validate`
#: lambda below `cast`s to its OWN entry's `kind`, a narrow, auditable
#: assertion of a fact the registry's own dispatch already guarantees
#: at that exact point (`validate` only ever runs on a value that just
#: parsed AS that `kind`).
SettingValue = str | int | float | bool | None

#: `miner.engine`'s two values (new-miner plan §3.8): the digest engine
#: (one reader call over every session's digest) and the session engine
#: (one call per session). `miner.run` reads the setting.
MINER_ENGINES: tuple[str, ...] = ("digest", "session")

#: `overseer.skill_writing`'s three values (S-107 part 6, SK3):
#: ``auto`` (the default: the first overseer run to complete keeps every
#: skill it builds as a checked draft, every later run writes), ``on`` and
#: ``off`` (drafts only). The runner reads the setting through
#: `overseer.skills.writing_mode`, never through `resolve_setting`: any
#: other value in config.yaml, a YAML boolean included, must read as
#: ``off`` (a mistyped rollback fails closed), and the generic resolver
#: would read a boolean as the default.
SKILL_WRITING_MODES: tuple[str, ...] = ("auto", "on", "off")


def _warn(message: str) -> None:
    print(f"self-learn: settings — {message}", file=sys.stderr)


@dataclass(frozen=True)
class Setting:
    #: The dotted registry key, e.g. ``"worker.coalesce_secs"`` -- also
    #: the `doctor settings` row label and the ``config:`` source's
    #: ``section.key`` suffix (identical to ``config_section``.
    #: ``config_key`` by construction, checked at import time below).
    name: str
    #: ``None`` => no env rung at all (M-S, S-58: `provider.bedrock.
    #: models.*`'s entries (six after U8) -- `worker`/`miner`/`analyst` because
    #: their env var moved to a different, always-active `models.*`
    #: entry; `small_fast` because it never had one -- its value feeds
    #: the CHILD session's own `ANTHROPIC_DEFAULT_HAIKU_MODEL`, so a
    #: same-shaped env INPUT would read the child's own output back).
    #: Every reader of this field -- `resolve_setting`, `unknown_
    #: override_vars`, `doctor settings` -- is audited for the `None`
    #: case; widened from mandatory `str` for exactly these four.
    env_var: str | None
    #: ``None`` => a bootstrap var with no config.yaml rung at all
    #: (mirrors ``provider._resolve_str_setting``'s ``config_key=None``
    #: shape). NO current registry entry uses this -- every var this
    #: Phase registered has a real config.yaml rung; a var that can't
    #: (e.g. `SELF_LEARN_HOME`, which locates `config.yaml` itself and
    #: so cannot be governed BY it) is simply never registered here at
    #: all, not registered with `config_section=None`. This field exists
    #: for a FUTURE bootstrap-shaped var that still wants `doctor
    #: settings` visibility without a config.yaml rung; until one is
    #: added, the `config_section is None` branches below are reachable
    #: only by a test exercising this field directly.
    config_section: str | None
    config_key: str | None
    kind: Kind
    #: A literal, or a zero-arg callable evaluated lazily ONLY when every
    #: rung above misses (mirrors ``provider.model_for``'s "the surface's
    #: shipped default function, CALLED, never copied").
    default: SettingValue | Callable[[], SettingValue]
    description: str
    operator_facing: bool = True
    #: Optional post-parse adjustment/gate, applied to a value that
    #: already parsed as `kind`. Returning `None` marks the value
    #: malformed (same fallback-to-default path as a parse failure);
    #: returning anything else is the value actually used -- this is how
    #: `worker.coalesce_secs`'s "clamp to 0, never fall back" and
    #: `worker.invoke_timeout_secs`'s "fall back below or at 0" both ride
    #: the one resolver despite opposite policies for an out-of-range
    #: number (E4's asymmetry, carried over from the env-only timeout reader
    #: the worker had before the registry).
    validate: Callable[[SettingValue], SettingValue | None] | None = None
    #: U-settings Phase 2 (code-gate MAJOR/NIT fold, review r1 2026-09-01
    #: NIT-1): a human-readable description of `validate`'s own bound,
    #: e.g. ``"must be > 0"`` -- consulted ONLY when `validate` actually
    #: rejects a value (`config_set`'s "out of range" refusal), so the
    #: message names the bound instead of just the type. Left `None` on
    #: every CLAMPING `validate` (`max(0, v)`-shaped -- those never
    #: reject, so the hint is never read); set explicitly on the three
    #: entries whose `validate` CAN reject (`worker.invoke_timeout_secs`,
    #: `worker.repair_timeout_secs`, `serve.tick_secs` — all ``v if v >
    #: 0 else None``). A registry-time invariant below (`_setting` loop)
    #: does not enforce this pairing -- the field is display-only and a
    #: missing hint degrades to the old, less-specific message, never a
    #: crash.
    validate_hint: str | None = None
    #: M-S (U-settings Phase 2's provider/backend-selection amendment,
    #: S-58): which rung order `resolve_setting` uses. `"config-first"`
    #: (the default -- every entry above this comment is unchanged) is
    #: **override > config.yaml > env > default**; `"env-first"` is
    #: **override > env > config.yaml > default** -- the direction
    #: `provider.py`/`invocation/registry.py`'s selection keys always
    #: used, now expressed as a registry field instead of a second,
    #: hand-rolled mechanism.
    direction: Literal["config-first", "env-first"] = "config-first"
    #: M-S: a predicate over the resolved `provider.name`, evaluated
    #: BEFORE even the override rung -- `None` means always active.
    #: `False` skips every rung and resolves straight to this entry's
    #: OWN default, with source label `f"inactive (provider={value})"`
    #: (S-36's "silently inert by design" shape, now expressed in the
    #: registry instead of a raw `if provider == "bedrock":` gate).
    #: NEVER set on `provider.name` itself -- gating a predicate on its
    #: own resolved value would be self-referential.
    enabled_when: Callable[[str], bool] | None = None
    #: M-S: the WRITE-path refusal gate, checked in `config_set` against
    #: the PARSED value, BEFORE `validate` -- a separate concern from
    #: `validate` (the READ-path clamp): `validate` folds an
    #: already-committed value in place at resolve time; `accepts`
    #: refuses a `config set` outright, before anything is ever written,
    #: so an off-whitelist write can never launder itself into an
    #: accepted, silently different one via a clamping `validate`. Only
    #: `provider.name` and the `invocation.backend` family use this
    #: (both also carry a `validate` that clamps on read, unchanged
    #: behaviour for a hand-edited config.yaml) -- every other entry
    #: leaves this `None`.
    accepts: Callable[[SettingValue], bool] | None = None
    #: The allowed-set text `config_set` names when `accepts` refuses --
    #: this registry's write-refusal counterpart to `validate_hint`
    #: (which is reserved for a REJECTING `validate` and stays `None` on
    #: every CLAMPING entry, `accepts` included, by that field's own
    #: docstring). `None` whenever `accepts` is `None`.
    accepts_hint: str | None = None
    #: U-settings Phase 2 (the settings page) — the exposure tier the
    #: page's editor and agent-shell write refusal honor (carrying the ratified
    #: `settings-surface-spec.md` §3 table's CATEGORIES onto THIS
    #: registry's actual keys): throughput knobs, cost ceilings, and
    #: timeouts are ``"A"`` (editable inline); the two spawn-containment
    #: kill switches tied to the 2026-08-09 incident (`worker.autokick`,
    #: `miner.autokick`) are ``"C"`` — a boundary, not a preference — so
    #: the page renders them read-only with a pointer to the CLI verb.
    #: Defaults to ``"A"`` so every other entry needs no change; ``"C"``
    #: is set explicitly, by name, on the two entries below. The page
    #: reads THIS field rather than hardcoding a name list (dispatch
    #: pin) — a future registry entry is tier A unless a reviewer
    #: deliberately marks it otherwise.
    tier: Literal["A", "C"] = "A"
    #: False: the process override channel (`SELF_LEARN_OVERRIDE_<NAME>`,
    #: :func:`override`) does not apply to this entry -- its rung is
    #: skipped as if unset. For a switch only the user flips
    #: (`miner.engine`, new-miner R2 fix round): agents here export
    #: `SELF_LEARN_OVERRIDE_*` for read verbs routinely, and an exported
    #: override would otherwise switch the engine with no flip of the
    #: user's. :func:`override` refuses such an entry outright.
    override_channel: bool = True


def sizing_knob(
    name: str,
    *,
    default: int | float,
    description: str,
    env_var: str | None = None,
) -> Setting:
    """One tuning knob that says HOW MUCH one step takes on -- a batch
    size, an input budget, a time limit. Adding one is this call in
    `REGISTRY` plus `resolve_int`/`resolve_float` at the use site; nothing
    else has to be written.

    Everything a knob of this family shares is decided here, once:

    - `section.key` in `config.yaml` IS the dotted name (`miner.digest_chars`
      -> `miner:` / `digest_chars:`), and the env var is derived from it
      (`SELF_LEARN_MINER_DIGEST_CHARS`) unless an older name must be kept;
    - an int default makes an int knob, a float default a float knob;
    - config.yaml outranks the env var (S-58), like every throughput knob;
    - it must be greater than zero. A zero or negative value is refused
      by `config set` and, hand-edited into `config.yaml`, falls back to
      the default: a batch of zero or a zero-second limit stops the step.

    The user's instruction, 2026-09-20: the numbers that size a step
    "can't be constants we just leave hardcoded in the code"."""
    section, _, key = name.partition(".")
    if not section or not key:
        raise ValueError(f"sizing_knob: {name!r} must be <section>.<key>")
    if isinstance(default, bool) or default <= 0:
        raise ValueError(f"sizing_knob: {name!r} needs a default greater than zero")
    return Setting(
        name=name,
        env_var=env_var or "SELF_LEARN_" + name.upper().replace(".", "_").replace("-", "_"),
        config_section=section,
        config_key=key,
        kind="int" if isinstance(default, int) else "float",
        default=default,
        description=description,
        validate=lambda v: v if cast("int | float", v) > 0 else None,
        validate_hint="must be > 0",
    )


def _default_value(setting: Setting) -> SettingValue:
    return setting.default() if callable(setting.default) else setting.default


def _parse_env_value(raw: str, kind: Kind) -> SettingValue:
    if kind == "str":
        return raw
    if kind == "int":
        try:
            return int(raw)
        except ValueError:
            return None
    if kind == "float":
        try:
            return float(raw)
        except ValueError:
            return None
    if kind == "bool":
        # `1`/`0` only -- matches this codebase's existing env-boolean
        # convention (`SELF_LEARN_NO_NOTIFY=1`, `SELF_LEARN_MINER=0`,
        # ...) rather than YAML's `true`/`false`, which is reserved for
        # the config.yaml rung below (`config.one_motion_enabled`'s own
        # precedent: only the native boolean, no string spelling).
        if raw == "1":
            return True
        if raw == "0":
            return False
        return None
    raise ValueError(f"resolve_setting: unknown kind {kind!r}")  # pragma: no cover - closed Kind


def _parse_config_value(value: object, kind: Kind) -> SettingValue:
    if kind == "str":
        return value if isinstance(value, str) else None
    if kind == "int":
        # `bool` is an `int` subclass in Python -- `worker.cap_max: true`
        # must not silently parse as `1`.
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if kind == "float":
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None
    if kind == "bool":
        return value if isinstance(value, bool) else None
    raise ValueError(f"resolve_setting: unknown kind {kind!r}")  # pragma: no cover - closed Kind


def _override_env_var(name: str) -> str:
    """The override channel's env-var name for registry entry `name`:
    `SELF_LEARN_OVERRIDE_<NAME>`, dots AND hyphens to underscores,
    uppercased -- e.g. `worker.autokick` -> `SELF_LEARN_OVERRIDE_
    WORKER_AUTOKICK`. Namespaced (not the setting's own `env_var`) so
    an operator's ordinary env pin can never collide with a process's
    override of itself -- the two channels stay distinguishable on
    sight. A thin call-through to `config.override_env_var` (M-S,
    S-58, minor-1's hyphen fix) -- moved there so `invocation/
    registry.py`'s own runtime-dispatch override rungs compute the
    IDENTICAL var name without importing this module at all."""
    return config.override_env_var(name)


#: M-S (S-58 BLOCKER-1, code-gate fold r1): relocated to `config.py` --
#: both markers now live there (`config.OVERRIDE_NONE_MARKER`,
#: `config.OVERRIDE_EMPTY_MARKER`) so `provider.py`'s runtime override
#: rung and `invocation/registry.py`'s can decode the SAME escape
#: hatches through `config.read_override` without importing this
#: module (a cycle). Aliased here, unchanged name, so every existing
#: reference in this file needs no further edit.
_OVERRIDE_NONE_MARKER = config.OVERRIDE_NONE_MARKER


def _encode_override_value(value: SettingValue, kind: Kind) -> str:
    """:func:`override`'s WRITER side -- the exact string spellings
    `_parse_env_value` reads back (`1`/`0` for bool; `str()` for
    numeric/str; `_OVERRIDE_NONE_MARKER` for `None`; M-S BLOCKER-1 fold:
    `config.OVERRIDE_EMPTY_MARKER` for a DELIBERATE empty string, so
    `config.read_override` can tell it apart from an ambient blank var
    -- `test_override_round_trips_str_including_empty`'s
    `override(name, "")` must keep reading back as `""`, not as "no
    answer"), so a round trip through the override channel can never
    drift from the ambient-env rung's own parsing vocabulary (and never
    collide with it either, for `None` or `""`)."""
    if value is None:
        return _OVERRIDE_NONE_MARKER
    if kind == "bool":
        return "1" if value else "0"
    if value == "":
        return config.OVERRIDE_EMPTY_MARKER
    return str(value)


def _apply_validate(
    parsed: SettingValue, validate: Callable[[SettingValue], SettingValue | None] | None
) -> tuple[SettingValue, bool]:
    """Runs `validate` (if present) on a value that ALREADY parsed as
    `kind`. Returns `(final, rejected)` -- `rejected` is True only when
    `validate` itself said no, which each rung below words differently
    from a parse failure (nit fold, review 2026-09-01): a value
    `validate` rejects as out-of-range DID parse fine as `kind` -- it
    is not "not a valid {kind}", the message a genuine parse failure
    gets; it is "out of range", a distinct claim about a distinct
    failure."""
    if validate is None:
        return parsed, False
    result = validate(parsed)
    return result, result is None


def _try_override(home: Path | str, setting: Setting) -> tuple[SettingValue, str] | None:
    """The override rung, factored out of `resolve_setting` unchanged
    (M-S, S-58) so both `direction`s share ONE copy -- this rung's
    position (always first, before `enabled_when` even runs it) is
    direction-independent.

    M-S BLOCKER-1 (code-gate fold r1): reads through `config.
    read_override` -- the SAME reader `provider._resolve_provider`'s
    own override rung now uses -- rather than a private `os.environ.
    get` + presence check. This closes the gate's two-link bug: an
    AMBIENT empty `SELF_LEARN_OVERRIDE_<NAME>` now reads as "no
    answer" on BOTH faces (matching `_try_env`'s own `if not raw`),
    while a DELIBERATE `override(name, "")` still round-trips as the
    real empty string (`config.OVERRIDE_EMPTY_MARKER`, decoded by the
    shared reader) -- `test_override_round_trips_str_including_empty`
    is the witness this preserves. `is_none=True` still bypasses
    parse/validate entirely, exactly as the old `_OVERRIDE_NONE_MARKER`
    branch did."""
    if not setting.override_channel:
        return None
    override_var = _override_env_var(setting.name)
    result = config.read_override(setting.name)
    if result is None:
        return None
    override_raw, is_none = result
    if is_none:
        # The override IS `None` -- bypasses parse/validate entirely
        # (both are for TYPED values; `None` here is `override()`'s
        # own refusal-guarded escape hatch, not a `kind`-shaped
        # answer to range-check).
        return None, f"override:{setting.name}"
    parsed = _parse_env_value(override_raw, setting.kind)
    if parsed is None:
        _warn(
            f"{override_var}={override_raw!r} is not a valid {setting.kind} for "
            f"{setting.name} — falling through to config/env/default"
        )
        return None
    final, rejected = _apply_validate(parsed, setting.validate)
    if final is not None:
        return final, f"override:{setting.name}"
    if rejected:
        _warn(
            f"{override_var}={override_raw!r} is out of range for "
            f"{setting.name} — falling through to config/env/default"
        )
    # `rejected` is only ever True here (validate ran on a value that
    # already parsed) -- the `if final is not None` above already
    # returned on any other outcome.
    return None


def _try_config(
    home: Path | str, setting: Setting, *, fallthrough_rung: str
) -> tuple[SettingValue, str] | None:
    """The config.yaml rung, factored out unchanged. `fallthrough_rung`
    only names which rung the warn text says a malformed value falls
    through TO -- `"env-first"` still falls through to env exactly as
    `"config-first"` does; only the WORDING of an already-existing warn
    message needs to name the right next rung for each direction."""
    if setting.config_section is None:
        return None
    assert setting.config_key is not None  # invariant: paired at registration
    found = config.settings_leaf(home, setting.config_section, setting.config_key)
    if found is not None and setting.kind == "str" and found[1] == "":
        # M-4 fold (review 2026-09-01): an empty config.yaml string is
        # "no answer", exactly like the env rung's own `if raw:` — not
        # a malformed value (no warn), just silently not-present here.
        found = None
    if found is None:
        return None
    key, value = found
    parsed = _parse_config_value(value, setting.kind)
    if parsed is None:
        _warn(
            f"config.yaml {setting.config_section}.{key}={value!r} is not a "
            f"valid {setting.kind} for {setting.name} — falling through to {fallthrough_rung}"
        )
        # NOT a return: the caller falls through to the next live rung,
        # per the spec's §1.2 boundary pin -- a malformed config value
        # must not dead-end a role another rung (or the default) would
        # serve.
        return None
    final, rejected = _apply_validate(parsed, setting.validate)
    if final is not None:
        return final, f"config:{setting.config_section}.{key}"
    if rejected:
        _warn(
            f"config.yaml {setting.config_section}.{key}={value!r} is out "
            f"of range for {setting.name} — falling through to {fallthrough_rung}"
        )
    return None


def _try_env(setting: Setting, *, next_rung: str | None) -> tuple[SettingValue, str] | None:
    """The env rung, factored out unchanged. `env_var=None` (M-S: the
    `provider.bedrock.models.*` entries) means no env rung at all
    -- skipped, exactly like `config_section=None` skips the config
    rung above. `next_rung=None` means env is the LAST live rung
    (`"config-first"`, unchanged from before this amendment) -- warn
    text says "using the default", byte-identical to before; a real
    `next_rung` (`"config-first"`'s config, for `"env-first"` entries)
    says "falling through to {next_rung}" instead, since the default is
    no longer the very next thing tried."""
    if setting.env_var is None:
        return None
    raw = os.environ.get(setting.env_var)
    if not raw:
        return None
    tail = "using the default" if next_rung is None else f"falling through to {next_rung}"
    parsed = _parse_env_value(raw, setting.kind)
    if parsed is None:
        _warn(f"{setting.env_var}={raw!r} is not a valid {setting.kind} for {setting.name} — {tail}")
        return None
    final, rejected = _apply_validate(parsed, setting.validate)
    if final is not None:
        return final, f"env:{setting.env_var}"
    if rejected:
        _warn(f"{setting.env_var}={raw!r} is out of range for {setting.name} — {tail}")
    return None






def resolve_setting(home: Path | str, setting: Setting) -> tuple[SettingValue, str]:
    """The registry's ONE resolution function (U-settings Phase 1 §2;
    flipped 2026-09-01, S-58; override channel added same day, a
    Blocker fix -- module docstring's "Three rungs, on purpose"; M-S,
    S-58's amendment, adds `direction` and `enabled_when`):

    `enabled_when`, when present, is evaluated FIRST -- before even the
    override rung (03-decisions.md row S-58): a `False` result resolves
    straight to this entry's own default with source label
    `f"inactive (provider={value})"`, consulting `provider.name`'s OWN
    resolution (which never itself carries an `enabled_when`, so this
    recursion is exactly one level deep, never circular).

    Then, by `direction`: **`"config-first"`** (every entry that
    existed before this amendment, unchanged) is **override channel,
    then config.yaml, then env, then the built-in default** --
    ``provider.py``'s exact source-string vocabulary (plus the
    `"override:<name>"` label). **`"env-first"`** (the amendment's new
    provider/backend-selection-style entries) is **override, then env,
    then config.yaml, then default** -- the SAME three helpers, config
    and env rungs simply swapped, so a future direction bug cannot
    silently diverge the two orderings' shared logic.

    Fail-closed PER RUNG, not per resolution (the spec's §1.2 boundary
    pin, carried through the flip and the override addition): a value
    that is present at a rung but does not parse as `setting.kind`, or
    that `validate` rejects, warns on stderr naming the key and the
    offending raw value and FALLS THROUGH to the next rung -- it does
    not dead-end at the default. A typo in config.yaml must never
    brick a role the env var (or the default) would have served; a
    malformed env value still falls through to the default, same as
    before the flip since env is the last LIVE rung in either
    direction.

    No caching of config.yaml/env: every call re-reads ``os.environ``
    and ``config.yaml`` fresh (module docstring) -- necessary but, per
    the Blocker review, NOT by itself sufficient to keep
    :func:`serve._worker_autokick_disabled`'s mechanism working under
    config-wins; see :func:`override` for why a THIRD rung was needed."""
    if setting.enabled_when is not None:
        provider_value, _ = resolve_setting(home, by_name("provider.name"))
        if not setting.enabled_when(cast(str, provider_value)):
            return _default_value(setting), f"inactive (provider={provider_value})"

    hit = _try_override(home, setting)
    if hit is not None:
        return hit

    if setting.direction == "env-first":
        hit = _try_env(setting, next_rung="config/default")
        if hit is not None:
            return hit
        hit = _try_config(home, setting, fallthrough_rung="default")
        if hit is not None:
            return hit
    else:
        hit = _try_config(home, setting, fallthrough_rung="env/default")
        if hit is not None:
            return hit
        hit = _try_env(setting, next_rung=None)
        if hit is not None:
            return hit

    return _default_value(setting), "default"


# ===================================================================== #
# The registry. One entry per rewired consumer (module docstring's scope
# discipline). Default LITERALS are duplicated from each home module's
# own constant rather than imported (importing worker/miner/analyst/
# serve/invocation_sdk at this module's top level would close an import
# cycle the moment any of them imports `settings` back, exactly the
# hazard `provider.py`'s `P-b` defers around for `model_for`) --
# `test_settings.py::test_registry_defaults_match_their_source_constants`
# pins every duplicate against its source so the two cannot silently
# drift apart.
# ===================================================================== #

#: M-S (S-58, BLOCKER-1): duplicated from `provider.PROVIDERS`/
#: `provider.DEFAULT_PROVIDER` rather than imported -- `provider.py`
#: now imports THIS module (for `model_for`'s registry-backed rungs,
#: among others), so a `settings.py -> provider.py` edge would close a
#: real cycle. `test_registry_defaults_match_their_source_constants`
#: pins both against their source, same discipline as every other
#: duplicated default literal in this file.
_PROVIDERS = ("anthropic", "bedrock")
_DEFAULT_PROVIDER = "anthropic"


def _default_worker_model() -> str:
    from . import worker

    return worker.worker_model()


def _default_miner_model() -> str:
    from . import miner

    return miner.miner_model()


def _default_analyst_model() -> str:
    from . import analyst

    return analyst._model()


#: U8 (17-invocation-runbook.md §1, S-18 as amended: "the steward and
#: overseer are a fourth, standing tier -- Fable 5.1"). Unlike
#: `_default_worker_model`/`_default_miner_model`/`_default_analyst_
#: model` above, there is no `steward.py`/`overseer.py` runner module
#: yet to delegate to -- those are built by a later unit, out of this
#: one's scope -- so the literal lives here, directly, until one does.
_DEFAULT_STEWARD_MODEL = "claude-fable-5-1"
_DEFAULT_OVERSEER_MODEL = "claude-fable-5-1"

#: U4 (S-68): the minimum Claude Code version each model needs, as
#: comma-separated ``<model id>=<version>`` pairs -- the registry's `kind`
#: vocabulary is `str`/`int`/`float`/`bool`, so a map is encoded as one
#: string rather than given a sixth kind for a single entry. Seeded with
#: exactly one pair, and editable in `config.yaml` (`sdk:` /
#: `model_cli_floors:`) without a code change.
#:
#: **Where 2.1.251 comes from, and where it does NOT.** The ONLY source
#: for this number is the API error string the steward's first real run
#: received on 2026-09-14 -- `API Error: 400 Claude Code 2.1.226 does not
#: support this model...` -- read together with the operative version
#: that later worked. It is NOT from vendor documentation, there is no
#: published table of per-model Claude Code minimums, and nothing
#: re-verifies it: if the real floor is lower, this over-reports; if the
#: vendor raises it, this under-reports until a human edits it.
_DEFAULT_MODEL_CLI_FLOORS = "claude-fable-5-1=2.1.251"


def _default_steward_model() -> str:
    return _DEFAULT_STEWARD_MODEL


def _default_overseer_model() -> str:
    return _DEFAULT_OVERSEER_MODEL


def _bedrock_active(provider_value: str) -> bool:
    return provider_value == "bedrock"


REGISTRY: tuple[Setting, ...] = (
    # ------------------------------------------------------- worker
    Setting(
        name="worker.coalesce_secs",
        env_var="SELF_LEARN_COALESCE_SECS",
        config_section="worker",
        config_key="coalesce_secs",
        kind="float",
        default=600.0,  # worker.DEFAULT_COALESCE_SECS
        description="seconds the worker sleeps to coalesce a run before invoking",
        validate=lambda v: max(0.0, cast(float, v)),  # a zero coalesce is meaningful; never falls back
    ),
    Setting(
        name="worker.invoke_timeout_secs",
        env_var="SELF_LEARN_INVOKE_TIMEOUT_SECS",
        config_section="worker",
        config_key="invoke_timeout_secs",
        kind="float",
        default=1800.0,  # worker.INVOKE_TIMEOUT_SECS
        description="subprocess timeout (seconds) for the worker's batch invocation",
        validate=lambda v: v if cast(float, v) > 0 else None,  # a <=0 timeout kills every run instantly (E4)
        validate_hint="must be > 0",
    ),
    Setting(
        name="worker.repair_timeout_secs",
        env_var="SELF_LEARN_REPAIR_TIMEOUT_SECS",
        config_section="worker",
        config_key="repair_timeout_secs",
        kind="float",
        default=600.0,  # worker.REPAIR_TIMEOUT_SECS
        description="subprocess timeout (seconds) for the worker's repair round",
        validate=lambda v: v if cast(float, v) > 0 else None,
        validate_hint="must be > 0",
    ),
    sizing_knob(
        "worker.batch_cap",
        default=15,  # worker.BATCH_CAP; 857 s measured at 15 (worker.py, U-repair section 3.9)
        description="lessons the worker prepares in one model call",
    ),
    Setting(
        name="worker.repair",
        env_var="SELF_LEARN_REPAIR",
        config_section="worker",
        config_key="repair",
        kind="bool",
        default=True,
        description="run the repair round after a failed batch invocation",
    ),
    Setting(
        name="worker.autokick",
        env_var="SELF_LEARN_WORKER_AUTOKICK",
        config_section="worker",
        config_key="autokick",
        kind="bool",
        default=True,
        description="allow the worker to auto-spawn a detached follow-on run",
        # U-settings Phase 2, tier C: a spawn-containment kill switch
        # tied to the 2026-08-09 incident (6,508 shells, 39.3 hours) —
        # a boundary, not a preference. The settings page shows it and
        # its source read-only; setting it stays a deliberate CLI act.
        tier="C",
    ),
    Setting(
        name="worker.no_notify",
        env_var="SELF_LEARN_NO_NOTIFY",
        config_section="worker",
        config_key="no_notify",
        kind="bool",
        default=False,
        description="suppress the desktop notifications the worker would otherwise send",
    ),
    # -------------------------------------------------------- miner
    Setting(
        name="miner.cap_max",
        env_var="SELF_LEARN_MINE_CAP_MAX",
        config_section="miner",
        config_key="cap_max",
        kind="int",
        default=15,  # miner.DEFAULT_CAP_MAX
        description="hard cap on records mined in one run",
        validate=lambda v: max(0, cast(int, v)),
    ),
    Setting(
        name="miner.cap_per_session",
        env_var="SELF_LEARN_MINE_CAP_PER_SESSION",
        config_section="miner",
        config_key="cap_per_session",
        kind="int",
        default=2,  # miner.DEFAULT_CAP_PER_SESSION
        description="cap on records mined per scanned session, before the run-wide cap",
        validate=lambda v: max(0, cast(int, v)),
    ),
    Setting(
        name="miner.pending_gate",
        env_var="SELF_LEARN_MINE_PENDING_GATE",
        config_section="miner",
        config_key="pending_gate",
        kind="int",
        default=25,  # miner.DEFAULT_PENDING_GATE
        description="pending-queue size that gates a mining run",
        validate=lambda v: max(0, cast(int, v)),
    ),
    # The miner reader's input budget (`miner.DigestLimits`) and its time
    # limit. All four were constants or env-only until 2026-09-20. The
    # three budgets are counted in CHARACTERS because that is what the
    # code counted when they were moved here, unchanged; the unit itself
    # is an open question with the user, and `miner.DigestLimits` is the
    # one place a different measure would be introduced.
    sizing_knob(
        "miner.message_chars",
        default=2_000,  # miner.MAX_TEXT_CHARS reads this
        description="characters kept from one message of a scanned session (the digest engine only)",
    ),
    sizing_knob(
        "miner.session_chars",
        default=60_000,  # miner.MAX_DIGEST_CHARS reads this
        description="characters kept from one scanned session; the rest of that session is clipped (the digest engine only)",
    ),
    sizing_knob(
        "miner.run_chars",
        default=400_000,  # miner.MAX_PROMPT_DIGESTS_CHARS reads this
        description="characters of session digests in one mining run's model call; sessions over it wait for the next run (the digest engine only)",
    ),
    sizing_knob(
        "miner.reader_timeout_secs",
        default=900.0,  # miner.INVOKE_TIMEOUT_SECS reads this
        description="subprocess timeout (seconds) for the miner's one reader model call",
        env_var="SELF_LEARN_READER_TIMEOUT_SECS",  # the name it already had
    ),
    # The session engine (new-miner plan §3.8, unit R2, 2026-10-19): one
    # model call per session, with its own tools, landing checked output.
    # `miner.engine` is the runner switch between the two engines. It is
    # the user's to flip (tier C, no env var, like `steward.enabled`);
    # `self-learn mine run --engine session` without `--preview` is refused,
    # so nothing but this setting makes the session engine land.
    Setting(
        name="miner.engine",
        env_var=None,
        config_section="miner",
        config_key="engine",
        kind="str",
        default="digest",
        description=(
            "which engine a mining run uses: digest (one call over every session's digest) or "
            "session (one call per session, with its own tools); the user flips it"
        ),
        # an unknown value hand-edited into config.yaml reads as the default
        validate=lambda v: v if v in MINER_ENGINES else "digest",
        accepts=lambda v: v in MINER_ENGINES,
        accepts_hint="digest or session",
        tier="C",
        override_channel=False,
    ),
    # Both are clamped where they are read (`mining.engine.EngineSettings`),
    # not here: the registry's numeric knobs only refuse a value <= 0.
    sizing_knob(
        "miner.parallel",
        default=4,
        description="session-engine calls at once (at most 8 are used); the first call of a run always runs alone",
    ),
    sizing_knob(
        "miner.spine_tokens",
        default=20_000,
        description=(
            "estimated tokens of one session's spine (chars / 2.5) before the session engine "
            "shortens agent messages (at least 2,000 are used); typed turns are never shortened"
        ),
    ),
    sizing_knob(
        "miner.max_sessions_per_run",
        default=30,
        description="sessions the session engine calls in one run; the rest wait behind their cursors for the next run",
    ),
    sizing_knob(
        "miner.max_run_usd",
        default=8.0,
        description=(
            "the session engine's runaway guard (notional dollars under the Max plan): no call starts "
            "once spent + 0.60 per call in flight reaches it; the sessions not started wait for the next run"
        ),
    ),
    Setting(
        name="miner.enabled",
        env_var="SELF_LEARN_MINER",
        config_section="miner",
        config_key="enabled",
        kind="bool",
        default=True,
        description="enable mining runs entirely (a hard kill switch)",
    ),
    Setting(
        name="miner.autokick",
        env_var="SELF_LEARN_MINER_AUTOKICK",
        config_section="miner",
        config_key="autokick",
        kind="bool",
        default=True,
        description="allow the miner's verb watchdog to auto-spawn a run",
        # U-settings Phase 2, tier C — same reasoning as worker.autokick
        # immediately above.
        tier="C",
    ),
    Setting(
        name="miner.transcripts_dir",
        env_var="SELF_LEARN_TRANSCRIPTS_DIR",
        config_section="miner",
        config_key="transcripts_dir",
        kind="str",
        default="~/.claude/projects",
        description="root directory the miner scans for Claude Code session transcripts",
    ),
    # M-5, 2026-10-07 (the user: "scheduled jobs maybe not unless i
    # explicitly ask for coverage. background jobs yes."): a scheduled
    # job's sessions are halted unless the job is named here. Parsed by
    # `miner.mined_scheduled_jobs`.
    Setting(
        name="miner.mined_scheduled_jobs",
        env_var="SELF_LEARN_MINER_MINED_SCHEDULED_JOBS",
        config_section="miner",
        config_key="mined_scheduled_jobs",
        kind="str",
        default="",
        description=(
            "scheduled jobs whose sessions the miner reads anyway, comma-separated, each named as its "
            "scheduled-task tag names it; every other scheduled job's session is skipped"
        ),
    ),
    # 2026-10-11 (the user: "add the ability to create a blacklist of
    # session id's for the miner"): a listed session's transcript is never
    # read by the miner's walk, `--since` backfill included. Parsed by
    # `miner.skip_sessions`.
    Setting(
        name="miner.skip_sessions",
        env_var="SELF_LEARN_MINER_SKIP_SESSIONS",
        config_section="miner",
        config_key="skip_sessions",
        kind="str",
        default="",
        description=(
            "session ids the miner never reads, comma-separated, each the transcript's file name "
            "without .jsonl; applies to --since backfills too"
        ),
    ),
    # ------------------------------------------------------- refs (U1, 2026-09-26)
    Setting(
        name="refs.transcript_roots",
        env_var="SELF_LEARN_TRANSCRIPT_ROOTS",
        config_section="refs",
        config_key="transcript_roots",
        kind="str",
        # os.pathsep-joined; each entry `~`-expanded at run time by
        # refs.transcript_roots(). The archive holds hardlinked copies of
        # top-level session files that outlive Claude Code's cleanup.
        default=os.pathsep.join(("~/.claude/projects", "~/.claude/archive/sessions")),
        description="transcript roots the checked-pointer resolver searches, in order (os.pathsep-separated)",
    ),
    # ------------------------------------------------------- analyst
    Setting(
        name="analyst.timeout_secs",
        env_var="SELF_LEARN_ANALYST_TIMEOUT",
        config_section="analyst",
        config_key="timeout_secs",
        kind="float",
        default=120.0,  # analyst.DEFAULT_ANALYST_TIMEOUT
        description="subprocess timeout (seconds) for the one-shot routing analyst",
        # No positivity validate: analyst._timeout() has never clamped a
        # <=0 value (unlike the worker/miner timeouts above) -- preserved
        # byte-for-byte rather than tightened as a side effect of Phase 1.
    ),
    # ------------------------------------------------------- steward
    # U8 (17-invocation-runbook.md §1; plan-steward-2026-09-12.md §5.4
    # "wall clock per call" row): the steward's own runner (a later
    # unit, out of this one's scope) is the only intended consumer --
    # registered here now so it resolves through this registry from its
    # first commit, per this module's own scope-discipline docstring.
    Setting(
        name="steward.timeout_secs",
        env_var="SELF_LEARN_STEWARD_TIMEOUT",
        config_section="steward",
        config_key="timeout_secs",
        kind="float",
        default=1800.0,  # plan-steward-2026-09-12.md §5.4
        validate=lambda v: v if cast(float, v) > 0 else None,  # a <=0 timeout kills every run instantly (E4; U8 fold r1 gate N5)
        validate_hint="must be > 0",
        description="subprocess timeout (seconds) for one steward model call",
    ),
    Setting(
        name="steward.packet_size",
        env_var="SELF_LEARN_STEWARD_PACKET_SIZE",
        config_section="steward",
        config_key="packet_size",
        kind="int",
        default=10,
        validate=lambda v: v if cast(int, v) > 0 else None,
        validate_hint="must be > 0",
        description="briefs in one steward model call (the run itself has no record cap)",
    ),
    Setting(
        name="steward.turns_per_lesson",
        env_var="SELF_LEARN_STEWARD_TURNS_PER_LESSON",
        config_section="steward",
        config_key="turns_per_lesson",
        kind="int",
        # The user's number. 2026-09-19: "200 per lesson", chosen when a turn was
        # believed to be one tool call; 2026-09-20, once it was measured that the
        # limit counts model RESPONSES: "bring the number down to 100 for now. still
        # maybe a bit too generous, but definitely more sane than 200." A steward
        # session's turn limit is this times the lessons in its batch. Crash
        # protection against a runaway session, not a ration (S-29): the three real
        # sessions of 2026-09-19 used 51-61 model responses for 9-10 lessons each.
        default=100,
        validate=lambda v: v if cast(int, v) > 0 else None,
        validate_hint="must be > 0",
        description=(
            "turn limit per lesson for a steward session: the session's limit "
            "is this times the lessons in its batch"
        ),
    ),
    Setting(
        name="steward.cooldown_secs",
        env_var="SELF_LEARN_STEWARD_COOLDOWN_SECS",
        config_section="steward",
        config_key="cooldown_secs",
        kind="int",
        default=72000,
        validate=lambda v: max(cast(int, v), 0),
        validate_hint="must be >= 0",
        description="minimum seconds between scheduled steward runs",
    ),
    Setting(
        name="steward.enabled",
        env_var=None,
        config_section="steward",
        config_key="enabled",
        kind="bool",
        default=False,
        description="enable the steward's applying runner after its watched maiden run",
        tier="C",
    ),
    # ------------------------------------------------------ premises
    # The premise check (S-104, premise-check design D12 as the user
    # changed it on 2026-10-30): the daily sweep and the steward's two input
    # kinds run from landing with no step by a person, so the DEFAULT is true
    # and setting it false is the person's rollback. Tier C like every switch
    # that is the person's (agents never set it; S-92 refuses `config set` from
    # an agent's shell), with no process-override rung: an exported
    # `SELF_LEARN_OVERRIDE_*` must not be able to switch it.
    Setting(
        name="premises.enabled",
        env_var=None,
        config_section="premises",
        config_key="enabled",
        kind="bool",
        default=True,
        description=(
            "whether the daily premise sweep and the steward's premise inputs run "
            "(on unless set false; the person's switch)"
        ),
        tier="C",
        override_channel=False,
    ),
    # S-104 (premise-check design D10, D14): how many placed
    # lessons with no `premises` field the steward is offered each night to
    # write them (the backfill, `premise-extract`). The design's 10 is the
    # default; 0 pauses the backfill while the rest of the premise check
    # runs. Tier C like `premises.enabled`: the pace of the steward's
    # unattended work on placed lessons is the person's (agents never set
    # it; S-92 refuses `config set` from an agent's shell), with no
    # process-override rung, so an exported `SELF_LEARN_OVERRIDE_*` cannot
    # change it either.
    Setting(
        name="premises.backfill_per_night",
        env_var=None,
        config_section="premises",
        config_key="backfill_per_night",
        kind="int",
        default=10,
        validate=lambda v: max(cast(int, v), 0),
        validate_hint="must be >= 0",
        description=(
            "how many placed lessons with no premises the steward is offered each "
            "night to write them (the backfill); 0 pauses it"
        ),
        tier="C",
        override_channel=False,
    ),
    # ---------------------------------------------------------- runs
    # U1 (S-68, `03-decisions.md`): ONE cap shared by both delegated
    # runners and by the overseer's week -- a run left unfinished either
    # makes progress on its next attempt or is closed out after this many.
    # Registered here now, consumed by U2 (the steward's close-out) and U3
    # (the overseer's), per this module's own scope-discipline docstring.
    Setting(
        name="runs.attempt_cap",
        env_var="SELF_LEARN_RUNS_ATTEMPT_CAP",
        config_section="runs",
        config_key="attempt_cap",
        kind="int",
        default=3,  # S-68 rule 2: after 3 failed attempts the run is closed (decided 2026-09-19)
        validate=lambda v: v if cast(int, v) > 0 else None,  # a cap of 0 would close every run before its first attempt
        validate_hint="must be > 0",
        description="failed attempts on one unit of delegated work before the run is closed out",
    ),
    # ------------------------------------------------------ overseer
    # U8 (17-invocation-runbook.md §1; plan-overseer-2026-09-12.md §5.4
    # "overseer.timeout_secs per invocation (default 900 s)"; §5.4/O-3
    # "overseer.max_model_calls, default 50 per run: the runaway guard").
    # Same not-yet-consumed note as `steward.timeout_secs` above -- the
    # overseer runner is a later unit.
    Setting(
        name="overseer.enabled",
        env_var=None,
        config_section="overseer",
        config_key="enabled",
        kind="bool",
        default=False,
        description="whether the scheduled overseer may run (config-only opt-in)",
    ),
    Setting(
        name="overseer.timeout_secs",
        env_var="SELF_LEARN_OVERSEER_TIMEOUT",
        config_section="overseer",
        config_key="timeout_secs",
        kind="float",
        default=900.0,  # plan-overseer-2026-09-12.md §5.4
        validate=lambda v: v if cast(float, v) > 0 else None,  # a <=0 timeout kills every run instantly (E4; U8 fold r1 gate N5)
        validate_hint="must be > 0",
        description=(
            "the floor of one overseer phase's time limit (seconds); the limit is "
            "max(this, 30 s x the cases that phase reads)"
        ),
    ),
    Setting(
        name="overseer.max_model_calls",
        env_var="SELF_LEARN_OVERSEER_MAX_MODEL_CALLS",
        config_section="overseer",
        config_key="max_model_calls",
        kind="int",
        default=50,  # S-66 / plan-overseer-2026-09-12.md §5.4 -- a runaway guard, not a ration
        description="cross-invocation runaway guard for one overseer run (a loop stop, not a ration)",
        validate=lambda v: max(cast(int, v), 0),
    ),
    Setting(
        name="overseer.broad_removal_threshold",
        env_var=None,
        config_section="overseer",
        config_key="broad_removal_threshold",
        kind="int",
        default=3,
        description="removal actions above this count raise the overseer notification cue",
        validate=lambda v: max(cast(int, v), 0),
    ),
    # SK3 (S-107 part 6): whether the overseer deploys the skills it
    # writes. Tier C, config.yaml only (no env var, no override channel),
    # like `miner.engine`: agents never set it (`CLAUDE.md`). The runner
    # reads it with `overseer.skills.writing_mode`, which reads an unknown
    # value -- a YAML boolean included -- as `off`; `validate` folds an
    # unknown string to `off` here too, so `doctor settings` agrees for
    # every string value.
    Setting(
        name="overseer.skill_writing",
        env_var=None,
        config_section="overseer",
        config_key="skill_writing",
        kind="str",
        default="auto",
        description=(
            "whether the overseer deploys the skills it writes: auto (its first completed run "
            "keeps them as drafts, every later run writes), on, or off (drafts only); the "
            "user's switch"
        ),
        validate=lambda v: v if v in SKILL_WRITING_MODES else "off",
        accepts=lambda v: v in SKILL_WRITING_MODES,
        accepts_hint="auto, on or off",
        tier="C",
        override_channel=False,
    ),
    # SK4 (S-107; S-107 part 6): whether the overseer
    # makes its skill-discovery call (phase S) and phase B gives dispositions.
    # On by default; off, a run makes two model calls and the steward's
    # skill proposals wait parked. Tier C, config.yaml only (no env var, no
    # override channel), like `overseer.skill_writing`: agents never set it
    # (`CLAUDE.md`). `config set` takes 1 or 0, as for every bool setting.
    Setting(
        name="overseer.skill_discovery",
        env_var=None,
        config_section="overseer",
        config_key="skill_discovery",
        kind="bool",
        default=True,
        description=(
            "whether the overseer's weekly run looks for skills (phase S, one more model call) "
            "and decides every skill candidate and skill proposal; the user's switch"
        ),
        tier="C",
        override_channel=False,
    ),
    # ----------------------------------------------------------- sdk
    Setting(
        name="sdk.max_budget_usd",
        env_var="SELF_LEARN_SDK_MAX_BUDGET_USD",
        config_section="sdk",
        config_key="max_budget_usd",
        kind="float",
        default=None,
        description="USD cap on a single SDK invocation; unset means unlimited",
    ),
    Setting(
        # 2026-09-28 (the user's words: "go ahead and just capture
        # everything"): after every model session, a copy of Claude Code's
        # own transcript file is kept in this cache under `sessions/`
        # (`session_copies.py`), and every session asks the SDK for
        # summarized thinking. One switch for both; off, neither happens.
        name="sdk.capture_sessions",
        env_var="SELF_LEARN_SDK_CAPTURE_SESSIONS",
        config_section="sdk",
        config_key="capture_sessions",
        kind="bool",
        default=True,
        description="keep a copy of each model session's transcript in the cache and ask for summarized thinking",
    ),
    Setting(
        name="sdk.event_logs",
        env_var="SELF_LEARN_SDK_EVENT_LOGS",
        config_section="sdk",
        config_key="event_logs",
        kind="int",
        default=20,  # invocation_sdk.events._DEFAULT_EVENT_LOGS
        description="count of tool-event log files retained per surface",
        validate=lambda v: max(cast(int, v), 0),
    ),
    Setting(
        name="sdk.max_turns.worker",
        env_var="SELF_LEARN_SDK_MAX_TURNS_WORKER",
        config_section="sdk",
        config_key="max_turns.worker",
        kind="int",
        default=120,  # invocation_sdk.backend._DEFAULT_MAX_TURNS["WORKER"]
        description="max agentic turns for a worker SDK session",
    ),
    Setting(
        name="sdk.max_turns.miner",
        env_var="SELF_LEARN_SDK_MAX_TURNS_MINER",
        config_section="sdk",
        config_key="max_turns.miner",
        kind="int",
        default=60,  # invocation_sdk.backend._DEFAULT_MAX_TURNS["MINER"]
        description="max agentic turns for a miner-reader SDK session",
    ),
    Setting(
        name="sdk.max_turns.analyst",
        env_var="SELF_LEARN_SDK_MAX_TURNS_ANALYST",
        config_section="sdk",
        config_key="max_turns.analyst",
        kind="int",
        default=30,  # invocation_sdk.backend._DEFAULT_MAX_TURNS["ANALYST"]
        description="max agentic turns for an analyst SDK session",
    ),
    Setting(
        name="sdk.max_turns.steward",
        env_var="SELF_LEARN_SDK_MAX_TURNS_STEWARD",
        config_section="sdk",
        config_key="max_turns.steward",
        kind="int",
        default=80,  # invocation_sdk.backend._DEFAULT_MAX_TURNS["STEWARD"]; plan-steward-2026-09-12.md §5.4 "SDK turns per call"
        description=(
            "max agentic turns for a steward SDK session that names no limit of "
            "its own; the steward's runs size theirs from steward.turns_per_lesson"
        ),
    ),
    Setting(
        name="sdk.max_turns.overseer",
        env_var="SELF_LEARN_SDK_MAX_TURNS_OVERSEER",
        config_section="sdk",
        config_key="max_turns.overseer",
        kind="int",
        # No sourced number: neither `build-u8.md` nor plan-overseer-
        # 2026-09-12.md §5.4 gives a per-invocation max_turns default for
        # this surface -- only `overseer.max_model_calls` (50, a
        # cross-invocation runaway guard the overseer's own runner
        # divides across both its calls, §5.4) is sourced. Builder's
        # judgment call, flagged in the U8 build report: matches
        # `sdk.max_turns.steward` (80) as the nearest comparable
        # single-invocation Fable-tier budget.
        default=80,  # invocation_sdk.backend._DEFAULT_MAX_TURNS["OVERSEER"]
        description="max agentic turns for an overseer SDK session",
    ),
    # --------------------------------------------------------- serve
    Setting(
        name="serve.tick_secs",
        env_var="SELF_LEARN_SERVE_TICK_SECS",
        config_section="serve",
        config_key="tick_secs",
        kind="float",
        default=60.0,  # serve.DEFAULT_TICK_SECS
        description="seconds between the daemon's scheduler ticks",
        validate=lambda v: v if cast(float, v) > 0 else None,
        validate_hint="must be > 0",
    ),
    # -------------------------------------------------------- ledger
    Setting(
        name="ledger.actor",
        env_var="SELF_LEARN_ACTOR",
        config_section="ledger",
        config_key="actor",
        kind="str",
        default=socket.gethostname,  # telemetry.actor()'s own fallback, called lazily
        description="machine/user identity recorded on telemetry writes",
    ),
    # M-5 (review 2026-09-01): reclassified from internal to operator-
    # facing -- `ledger_ops.py`'s own refusal text (`verbs.py`'s
    # `_validate_rules_globs`) already tells a human operator to "raise
    # SELF_LEARN_GLOB_PROBE_BUDGET_S". A setting a shipped message tells
    # a human to set is operator-facing by definition, regardless of how
    # it was first classified.
    Setting(
        name="ledger.glob_probe_budget_s",
        env_var="SELF_LEARN_GLOB_PROBE_BUDGET_S",
        config_section="ledger",
        config_key="glob_probe_budget_s",
        kind="float",
        default=30.0,  # ledger_ops.DEFAULT_GLOB_PROBE_BUDGET_S
        description="per-pattern reachability probe budget (seconds) for rules_paths globs",
        # No positivity validate, deliberately: the ORIGINAL
        # `_glob_probe_budget_s()` accepted any parseable float verbatim,
        # including `0` -- and `test_u_glob.py`'s own `TestT4BudgetExhaustion`
        # / `TestT10SelfcheckUserScopeGlobDrift` rely on `BUDGET_S=0` to
        # deterministically force an exhausted-budget probe outcome without
        # a real slow filesystem. A worker/serve TIMEOUT clamps `<=0`
        # because it would kill a run instantly (E4); a probe BUDGET of
        # exactly 0 is the opposite: a legitimate, meaningful "probe with
        # no time at all" the test suite exercises on purpose (M-5's
        # discovery, review 2026-09-01 -- caught by the pre-existing suite,
        # not guessed).
    ),
    # ------------------------------------------------------- provider
    # M-S (S-58): provider/backend-selection keys, folded into this ONE
    # mechanism with `direction="env-first"` -- the emergency-rollback
    # trade `provider.py`/`invocation/registry.py` always implemented
    # by hand, now expressed as registry fields instead of a second,
    # independent transcription. `provider.name`'s own RUNTIME
    # resolution (`provider._resolve_provider`) stays a separate,
    # hand-written cascade that still emits its own warnings -- this
    # entry is the read-only reporting/write face `doctor settings`/
    # `config get|set` use (03-decisions.md row S-58's MAJOR-2 text).
    Setting(
        name="provider.name",
        env_var="SELF_LEARN_PROVIDER",
        config_section="provider",
        config_key="name",
        kind="str",
        default=_DEFAULT_PROVIDER,
        description="which model provider backs the SDK session (anthropic or bedrock)",
        direction="env-first",
        validate=lambda v: cast(str, v) if cast(str, v) in _PROVIDERS else _DEFAULT_PROVIDER,
        accepts=lambda v: cast(str, v) in _PROVIDERS,
        accepts_hint=f"must be one of {', '.join(_PROVIDERS)}",
        # nit-4 (code-gate fold r1, orchestrator ruling): an emergency-
        # rollback lever, same character as `worker.autokick`/`miner.
        # autokick`'s tier "C" -- a boundary the page renders read-only
        # with a pointer to the CLI verb, not a preference.
        tier="C",
    ),
    Setting(
        name="provider.bedrock.region",
        env_var="SELF_LEARN_BEDROCK_REGION",
        config_section="provider",
        config_key="bedrock.region",
        kind="str",
        default=None,
        description="AWS region for a Bedrock-backed session",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    Setting(
        name="provider.bedrock.profile",
        env_var="SELF_LEARN_BEDROCK_PROFILE",
        config_section="provider",
        config_key="bedrock.profile",
        kind="str",
        default=None,
        description="AWS credential profile for a Bedrock-backed session",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    Setting(
        name="provider.bedrock.models.worker",
        env_var=None,  # MAJOR-4: moved to the always-active `models.worker` below
        config_section="provider",
        config_key="bedrock.models.worker",
        kind="str",
        default=None,
        description="Bedrock model id for the worker surface (overrides models.worker)",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    Setting(
        name="provider.bedrock.models.miner",
        env_var=None,
        config_section="provider",
        config_key="bedrock.models.miner",
        kind="str",
        default=None,
        description="Bedrock model id for the miner-reader surface (overrides models.miner)",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    Setting(
        name="provider.bedrock.models.analyst",
        env_var=None,
        config_section="provider",
        config_key="bedrock.models.analyst",
        kind="str",
        default=None,
        description="Bedrock model id for the analyst surface (overrides models.analyst)",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    # U8: `provider.model_for` reads `provider.bedrock.models.<surface>`
    # UNCONDITIONALLY (via `_bedrock_models_setting_name`, not gated on
    # the active provider) whenever the primary `models.<surface>` rung
    # did not itself resolve at "env:"/"override:" -- an unregistered
    # name here is a `settings.by_name` `KeyError` in `model_for` on
    # EVERY such call, not only under `provider=bedrock` (17-invocation-
    # runbook.md §1; build-u8.md).
    Setting(
        name="provider.bedrock.models.steward",
        env_var=None,
        config_section="provider",
        config_key="bedrock.models.steward",
        kind="str",
        default=None,
        description="Bedrock model id for the steward surface (overrides models.steward)",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    Setting(
        name="provider.bedrock.models.overseer",
        env_var=None,
        config_section="provider",
        config_key="bedrock.models.overseer",
        kind="str",
        default=None,
        description="Bedrock model id for the overseer surface (overrides models.overseer)",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    Setting(
        name="provider.bedrock.models.small_fast",
        # MAJOR-4: never had an env var -- its value feeds the CHILD
        # session's own ANTHROPIC_DEFAULT_HAIKU_MODEL (`session_env`),
        # so a same-shaped env INPUT would read the child's own output
        # back.
        env_var=None,
        config_section="provider",
        config_key="bedrock.models.small_fast",
        kind="str",
        default=None,
        description="Bedrock model id for the SDK's small/fast (haiku-class) child model",
        direction="env-first",
        enabled_when=_bedrock_active,
    ),
    # ----------------------------------------------------------- sdk
    Setting(
        name="sdk.cli_path",
        env_var="SELF_LEARN_SDK_CLI_PATH",
        config_section="sdk",
        config_key="cli_path",
        kind="str",
        default=None,
        description="the CLI path `SELF_LEARN_SDK_CLI_PATH` used to set directly, bypassing config",
        direction="env-first",
    ),
    # U4 (S-68): the per-model Claude Code floor the `sdk` doctor row
    # checks the OPERATIVE binary against. `direction` is left at the
    # default `config-first` -- unlike `sdk.cli_path` right above, which
    # is `env-first` only because `SELF_LEARN_SDK_CLI_PATH` predates the
    # registry and callers already relied on the env var outranking
    # config.yaml. This entry has no such history: a floor is a fact
    # about the installed software that belongs in the ledger's own
    # config, with the env var reserved for a one-off probe.
    # U4c (S-70): the opt-out for "use the Claude Code this machine has
    # installed when `sdk.cli_path` is unset". Default TRUE, so a default
    # install runs the binary the person keeps up to date rather than the
    # one the wheel happened to bundle -- which on 2026-09-14 was 2.1.226,
    # too old for `claude-fable-5-1`, so the steward and the overseer
    # could not run at all. `false` restores the SDK's own order (bundled
    # copy first). The reason to keep an off switch: an installed binary
    # UPDATES ITSELF, while the SDK was built and tested against the
    # bundled one, so a Claude Code update can change behaviour with no
    # self-learn change at all. `doctor invocation`'s `sdk` row prints
    # both versions and names the rule that chose the binary, so the
    # trade is visible rather than silent. `direction` is left at the
    # default `config-first` for the same reason `sdk.model_cli_floors`
    # is: this key has no pre-registry history of callers relying on an
    # environment variable (unlike `sdk.cli_path`, which is `env-first`
    # only because `SELF_LEARN_SDK_CLI_PATH` predates the registry).
    Setting(
        name="sdk.prefer_installed_cli",
        env_var="SELF_LEARN_SDK_PREFER_INSTALLED_CLI",
        config_section="sdk",
        config_key="prefer_installed_cli",
        kind="bool",
        default=True,
        description=(
            "when `sdk.cli_path` is unset, use the Claude Code installed on this machine "
            "(PATH, then the SDK's own install locations) instead of the SDK's bundled copy"
        ),
    ),
    Setting(
        name="sdk.model_cli_floors",
        env_var="SELF_LEARN_SDK_MODEL_CLI_FLOORS",
        config_section="sdk",
        config_key="model_cli_floors",
        kind="str",
        default=_DEFAULT_MODEL_CLI_FLOORS,  # see that constant for the 2.1.251 source caveat
        description=(
            "minimum Claude Code version per model id, comma-separated <model>=<version> pairs"
        ),
    ),
    # -------------------------------------------------------- models
    # M-S (BLOCKER-1): corrects `settings-surface-spec.md` §1.2's
    # config-first ruling for exactly these three keys, which never
    # took effect in code -- `models.pane` (UI-scope) is unaffected and
    # stays out of this registry entirely.
    Setting(
        name="models.worker",
        env_var="SELF_LEARN_WORKER_MODEL",
        config_section="models",
        config_key="worker",
        kind="str",
        default=_default_worker_model,
        description="model id for the worker surface, under either provider",
        direction="env-first",
    ),
    Setting(
        name="models.miner",
        env_var="SELF_LEARN_MINER_MODEL",
        config_section="models",
        config_key="miner",
        kind="str",
        default=_default_miner_model,
        description="model id for the miner-reader surface, under either provider",
        direction="env-first",
    ),
    Setting(
        name="models.analyst",
        env_var="SELF_LEARN_ANALYST_MODEL",
        config_section="models",
        config_key="analyst",
        kind="str",
        default=_default_analyst_model,
        description="model id for the analyst surface, under either provider",
        direction="env-first",
    ),
    Setting(
        name="models.steward",
        env_var="SELF_LEARN_STEWARD_MODEL",
        config_section="models",
        config_key="steward",
        kind="str",
        default=_default_steward_model,
        description="model id for the steward surface, under either provider",
        direction="env-first",
    ),
    Setting(
        name="models.overseer",
        env_var="SELF_LEARN_OVERSEER_MODEL",
        config_section="models",
        config_key="overseer",
        kind="str",
        default=_default_overseer_model,
        description="model id for the overseer surface, under either provider",
        direction="env-first",
    ),
)

#: Registration-time invariant: `name` is always `f"{config_section}.
#: {config_key}"` (or bare, for a bootstrap var with no config rung) --
#: relied on by `preflight`'s row labels and by callers building a
#: `by_name` lookup. Checked once at import time, not per-call.
_override_vars_seen: set[str] = set()
for _setting in REGISTRY:
    if _setting.config_section is not None:
        assert _setting.name == f"{_setting.config_section}.{_setting.config_key}", _setting.name
    else:
        # U-settings Phase 2 code-gate MINOR-4 (review r1 2026-09-01):
        # a `config_section=None` entry (the shape this dataclass's own
        # `config_section` docstring reserves for a FUTURE bootstrap
        # var with no config.yaml rung at all) has nothing `config set`
        # could ever write -- `tier="A"` on one would render a LIVE,
        # POSTing editor for a row `config_set`/`config_unset` can only
        # ever refuse (their own `config_section is None` guard raises
        # `NoConfigRungError`, never silently no-ops). Make that
        # combination impossible to register rather than trusting every
        # future entry to remember the pairing by hand -- exactly the
        # "hand-maintained list" class this repo has been burned by
        # this week (NIT-3, same review, on `_SETTINGS_SECTION_ORDER`).
        assert _setting.tier == "C", (
            f"{_setting.name}: a config_section=None (bootstrap) entry "
            "has no config.yaml rung to edit -- it must be tier C"
        )
    # NIT-3 (review r2 2026-09-01): `_override_env_var` is NOT injective
    # (`.` and `-` and `_` all fold to `_` -- `a.b_c` and `a_b.c`
    # collide, and M-S's amendment adds the same risk for hyphenated
    # surface names). 37 entries give 37 distinct vars today (21
    # original + 16 from M-S/S-58: provider.name, provider.bedrock.
    # region/profile/models.worker|miner|analyst|small_fast,
    # invocation.backend + one invocation.backend_<surface> per
    # surface, sdk.cli_path, models.worker|miner|analyst); this catches
    # the day a 38th entry's name silently steals another entry's
    # override channel, the same invariant-at-registration-time
    # discipline as the `name == section.key` assert above.
    _override_var = _override_env_var(_setting.name)
    assert _override_var not in _override_vars_seen, (
        f"override env var collision: {_override_var!r} (from {_setting.name!r})"
    )
    _override_vars_seen.add(_override_var)
# No `del _setting` (pyright M-1 fold, review 2026-09-01): pyright cannot
# prove a `for` loop over a non-empty tuple LITERAL always binds its
# target (it does not reason about literal length here), so a `del`
# right after reads as "possibly unbound" -- `assert REGISTRY` first does
# not help either (a non-empty tuple literal makes that assert itself
# "always true", a second warning). Leaving the loop-scratch name bound
# (already `_`-prefixed, never read again) is the smaller wart.

_BY_NAME: dict[str, Setting] = {s.name: s for s in REGISTRY}


def by_name(name: str) -> Setting:
    """The one registry entry named `name`. Raises `KeyError` for a name
    outside `REGISTRY` (a programming error, never operator input)."""
    return _BY_NAME[name]


def resolve_int(home: Path | str, name: str) -> int:
    """The resolved value of the int setting `name` -- the whole use site
    of an int knob. Raises `KeyError` for an unregistered name and
    `TypeError` for a setting of another kind (both programming errors)."""
    setting = by_name(name)
    if setting.kind != "int":
        raise TypeError(f"settings.resolve_int: {name} is a {setting.kind} setting")
    value, _source = resolve_setting(home, setting)
    return int(cast(int, value))


def resolve_float(home: Path | str, name: str) -> float:
    """The resolved value of the float (or int) setting `name`, as a float."""
    setting = by_name(name)
    if setting.kind not in ("float", "int"):
        raise TypeError(f"settings.resolve_float: {name} is a {setting.kind} setting")
    value, _source = resolve_setting(home, setting)
    return float(cast("int | float", value))


@contextlib.contextmanager
def override(name: str, value: SettingValue) -> Iterator[None]:
    """A process-local override, resolved ABOVE both config.yaml and
    env (Blocker fix, review 2026-09-01) -- for the one case S-58's
    config-wins ruling was never meant to cover: a PROCESS asserting a
    runtime invariant about ITSELF for a span, not an operator's
    ambient preference. `serve._worker_autokick_disabled` is the
    motivating case: it neutralises the worker-autokick kill switch
    for as long as `serve` is already driving jobs in-process, so
    neither producer double-spawns a detached follow-on (gate r1 M-2,
    the 2026-08-09 incident -- 6,508 shells, 39.3 hours, a dead desktop
    session). Under config-wins, an ordinary env write can no longer
    guarantee that: a saved `worker.autokick: true` would silently
    outrank it.

    THIS IS NOT A PYTHON-LOCAL MECHANISM (an earlier draft of this fix
    was, and was wrong -- caught before landing). `worker.py:1103-1115`
    documents this codebase's own convention: a detached spawn is
    `start_new_session=True`, so a parent's flag reaches a CHILD only
    as inherited environment -- and the 2026-08-09 incident was
    exactly a self-respawning detached CHAIN, where containment is a
    property of the whole process tree, not one process's memory. So
    :func:`override` writes a REAL, namespaced env var
    (:func:`_override_env_var`: `SELF_LEARN_OVERRIDE_<NAME>`) rather
    than an in-process dict -- any child spawned while this is set
    inherits it, and `resolve_setting` checks this channel BEFORE
    config.yaml in every process that inherits it, parent or child
    alike -- beating a config.yaml value that says the opposite, not
    just the ambient env var beside it. NIT-2 (review r2 2026-09-01),
    the real invariant, stated correctly: every detached spawn in this
    codebase copies the FULL environment explicitly (`env = dict(
    os.environ)`, then passes `env=env`) -- worker.py:1138,
    miner.py:1744-1749, the UI's `runner.py:318` and `ledger.py:117`,
    all four. None of them relies on `Popen`'s bare-inheritance default;
    the conclusion above (a child sees this override) holds BECAUSE
    every spawn site does that copy, not because any of them omits
    `env=`. `miner.py`'s copy additionally POPS `worker.NO_PUSH_ENV`
    (a DIFFERENT, unrelated kill switch) before spawning -- that pop is
    key-scoped on purpose and must stay that way; a blanket-cleared env
    would drop this override (and every other real env var) too.

    Restored to whatever `SELF_LEARN_OVERRIDE_<NAME>` held when the
    span STARTED (nests correctly) -- the exact restore-on-exit
    contract the pre-fix `os.environ["SELF_LEARN_WORKER_AUTOKICK"]`
    write held, preserved byte-for-byte: `_run_tick` holds this open
    across BOTH the mine job and the worker job that may follow it in
    the same tick, and restoring it BETWEEN them (rather than after
    both) reopens exactly the window M-2 measured.

    Side effect worth naming (not a design goal): this gives an
    operator a documented shell-level escape hatch --
    `SELF_LEARN_OVERRIDE_<NAME>=<value>` beats a synced config.yaml on
    whatever machine sets it -- which is an emergency override S-58's
    §1.2 trade said operators would not have. It exists here only
    because a PROCESS needed to out-rank config for its own runtime
    invariant; a human using the same channel for the same reason
    (a live emergency) is a reasonable use of the same mechanism, not
    a hole in the ruling -- but it is a consequence, not something
    this fix set out to add."""
    setting = by_name(name)  # raises KeyError on a typo -- fail loudly, never silently
    if not setting.override_channel:
        raise ValueError(f"settings.override: {name} takes no process override (only the user flips it)")
    if value is None and setting.default is not None:
        # MINOR-4 (review r2 2026-09-01): `None` is a legitimate
        # RESOLVED value for exactly one thing in this registry today
        # -- a setting whose own `default` IS `None`
        # (`sdk.max_budget_usd`, meaning "unlimited"). For every other
        # setting, `None` means only "this rung's parse failed"
        # internally -- it is not a `kind`-shaped answer `validate` (or
        # a typed consumer) can hold. Writing it anyway would either
        # crash downstream (`cast(float, None)` used by a caller that
        # assumes a real float) or silently misbehave (`_apply_
        # validate` skipped, an untyped `None` handed to code that
        # never expected one) -- refuse loudly here instead, at the
        # one place that knows which outcome it would be.
        raise ValueError(
            f"settings.override({name!r}, None): None is not a valid "
            f"resolved value for {name!r} (its own default is "
            f"{setting.default!r}, not None) -- refusing rather than "
            f"writing an override this span cannot safely hold. Only a "
            f"setting whose OWN default is None accepts None here."
        )
    env_var = _override_env_var(name)
    prior = os.environ.get(env_var)
    os.environ[env_var] = _encode_override_value(value, setting.kind)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = prior


def retired_keys(home: Path | str) -> list[str]:
    """Present retired backend selectors, by name only; never expose values."""
    from ruamel.yaml import YAML, YAMLError

    try:
        data = YAML(typ="safe").load(config.config_path(home).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, YAMLError):
        data = None
    section = data.get("invocation") if isinstance(data, dict) else None
    found = [
        f"invocation.{key}" for key in section
        if isinstance(key, str) and (key == "backend" or key.startswith("backend_"))
    ] if isinstance(section, dict) else []
    found.extend(
        key for key in os.environ
        if key == "SELF_LEARN_BACKEND" or key.startswith("SELF_LEARN_BACKEND_")
        or key == "SELF_LEARN_OVERRIDE_INVOCATION_BACKEND"
        or key.startswith("SELF_LEARN_OVERRIDE_INVOCATION_BACKEND_")
    )
    return sorted(found)


def retired_key_detail(key: str) -> str:
    action = (f"self-learn config unset {shlex.quote(key)}"
              if key.startswith("invocation.") else f"unset {shlex.quote(key)}")
    return f"{key} is retired and has no effect; every invocation uses sdk; remove it with `{action}`"


def unknown_keys(home: Path | str) -> list[str]:
    """`K-c` parity for the settings registry (`config.provider_
    unknown_keys`'s template): every dotted `section.key` present under
    a registry-owned config.yaml section that names no registry entry,
    across every section the registry touches. Never warns by itself;
    `doctor settings` renders one WARN row per hit."""
    by_section: dict[str, set[str]] = {}
    for setting in REGISTRY:
        if setting.config_section is None:
            continue
        assert setting.config_key is not None  # invariant: paired at registration
        by_section.setdefault(setting.config_section, set()).add(setting.config_key)
    found: list[str] = []
    for section in sorted(by_section):
        known = frozenset(by_section[section])
        for key in config.settings_unknown_keys(home, section, known):
            found.append(f"{section}.{key}")
    return found


def unknown_override_vars() -> list[str]:
    """MINOR-3(a) (review r2 2026-09-01): the override-channel mirror
    of `unknown_keys` -- every `SELF_LEARN_OVERRIDE_*` env var PRESENT
    that names no registry entry. Before this, a typo'd or miscased
    override (`SELF_LEARN_OVERIDE_WORKER_AUTOKICK`,
    `SELF_LEARN_OVERRIDE_WORKER_Autokick`) did NOTHING -- zero warns,
    zero rows, `doctor settings` rc 0 -- while the identically-shaped
    mistake in config.yaml already got a WARN row. Never warns by
    itself; `doctor settings` renders one WARN row per hit. An entry that
    takes no override (``override_channel`` False) is named here too: its
    var is set and does nothing."""
    legal = frozenset(_override_env_var(s.name) for s in REGISTRY if s.override_channel)
    return sorted(
        k for k in os.environ
        if k.startswith("SELF_LEARN_OVERRIDE_") and k not in legal
        and not (k == "SELF_LEARN_OVERRIDE_INVOCATION_BACKEND"
                 or k.startswith("SELF_LEARN_OVERRIDE_INVOCATION_BACKEND_"))
    )


def _override_warn_text(setting: Setting) -> str:
    """The ACTIVE OVERRIDE explanation -- the ONE copy of this sentence
    (U-settings Phase 2 fold: previously inlined once, in `preflight`
    below). :func:`preflight`'s WARN `detail` and `config get --json`'s
    per-row `warn` field (`setting_row`) both build FROM this string
    rather than each spelling it out, so a human reading the CLI table
    and a human reading the settings page's WARN banner see byte-
    identical words -- never two copies that can quietly drift apart.
    The settings-page dispatch is explicit that this text must be
    REUSED, not paraphrased, because it names the one boundary
    (`self-learn-host.service` not seeing a shell-exported override)
    that a paraphrase could get subtly wrong."""
    return (
        "ACTIVE OVERRIDE, outranks config.yaml. This is ambient (exported in the "
        "calling shell, not set by `doctor` itself): it applies to "
        "this shell and everything it spawns, but NOT to "
        "self-learn-host.service (its unit sets only explicit "
        "Environment= lines, no PassEnvironment -- a systemd-run "
        "`serve` never sees it). Unset "
        f"{_override_env_var(setting.name)} to stop overriding."
    )


@dataclass(frozen=True)
class SettingRow:
    name: str
    verdict: str  # "INFO" | "WARN" -- this surface is introspection-only, never FAIL (nothing here gates)
    detail: str


def _fold_note(home: Path | str, setting: Setting, source: str) -> str | None:
    """M-S (S-58, r5-m1(b)/r6-m1(b)): RE-DERIVES whether the raw value
    AT THE RUNG NAMED BY `source` was folded by `setting.validate`, for
    `setting_row`/`preflight`'s `note` field -- a second, redundant call
    given `resolve_setting`'s own 2-tuple stays a thin wrapper rather
    than widening (measured: `resolve_setting(` has 20 call sites, 18 of
    them unpacking a plain 2-tuple wanting nothing else, against exactly
    2 display call sites that would use a 3rd element). `None` for
    every source this can't (or need not) re-derive: no `validate` at
    all, an override written as the `_OVERRIDE_NONE_MARKER` escape
    hatch, `"default"`, and `f"inactive (provider=...)"` (`enabled_when`
    gating never reaches a rung to re-read).

    Override markers are decoded through config.read_override."""
    entry = setting
    if entry.validate is None:
        return None
    if source.startswith("override:"):
        result = config.read_override(entry.name)
        if result is None:
            return None
        raw, is_none = result
        if is_none:
            return None
        parsed = _parse_env_value(raw, entry.kind)
    elif source.startswith("config:"):
        if entry.config_section is None:
            return None
        assert entry.config_key is not None
        found = config.settings_leaf(home, entry.config_section, entry.config_key)
        if found is None:
            return None
        parsed = _parse_config_value(found[1], entry.kind)
    elif source.startswith("env:"):
        if entry.env_var is None:
            return None
        raw = os.environ.get(entry.env_var)
        if not raw:
            return None
        parsed = _parse_env_value(raw, entry.kind)
    else:
        # "default" or "inactive (provider=...)" -- nothing to re-read.
        return None
    if parsed is None:
        return None
    final, rejected = _apply_validate(parsed, entry.validate)
    if rejected or final is None or final == parsed:
        return None
    return f"{parsed!r} folded to {final!r}"


def preflight(home: Path | str) -> list[SettingRow]:
    """`doctor settings`'s single source of truth (mirrors `provider.
    preflight`'s `Doc-0`: computes every row, prints nothing).

    Per registry entry: an INFO row (name, resolved value, source) --
    UNLESS the source is an active override, which renders WARN instead
    (MINOR-3(b), review r2 2026-09-01: the old severity ordering had
    this backwards -- a harmless stray config key already got a WARN,
    while a LIVE rung sitting above every saved policy rendered as
    ordinary INFO, no different from a boring default). The WARN names
    the split brain this channel creates: `doctor` runs interactively,
    never sets an override itself, so any override it sees here is
    AMBIENT -- exported in the calling shell. That export reaches this
    shell and everything IT spawns (§`override`'s own docstring), but
    NOT `self-learn-host.service`: that unit's `[Service]` block sets
    only explicit `Environment=` lines, no `PassEnvironment=` (measured
    against every shipped unit file), so a systemd-launched `serve`
    never sees a shell-exported override at all. The practical hazard:
    autokick can read "off" for a human at the terminal and "on" inside
    `serve` at the same moment, on the same machine.

    Then one WARN row per unknown config.yaml key (`unknown_keys`), and
    one WARN row per unrecognised `SELF_LEARN_OVERRIDE_*` env var
    (`unknown_override_vars`, MINOR-3(a))."""
    rows: list[SettingRow] = []
    for setting in REGISTRY:
        if setting.name == "overseer.skill_writing":
            # SK3 fix round 2 (gate r2 MINOR; S-107 part 6): a
            # value the overseer reads as `off` while `resolve_setting`
            # falls through to the default is named, with what is obeyed.
            misread = _skill_writing_misread(home)
            if misread is not None:
                rows.append(SettingRow(name=setting.name, verdict="WARN", detail=misread))
                continue
        value, source = resolve_setting(home, setting)
        note = _fold_note(home, setting, source)
        note_suffix = f" [{note}]" if note else ""
        if source.startswith("override:"):
            # M-S (code-gate fold r1): a PAIRED entry's `source` may
            # name the GENERAL sibling's own override var -- the "Unset
            # <VAR>" text must name THAT var, not `setting`'s own
            # (which the operator never exported).
            rows.append(
                SettingRow(
                    name=setting.name,
                    verdict="WARN",
                    detail=(
                        f"{setting.name} = {value!r} ({source}){note_suffix} -- "
                        f"{_override_warn_text(setting)}"
                    ),
                )
            )
        else:
            rows.append(
                SettingRow(
                    name=setting.name,
                    verdict="INFO",
                    detail=f"{setting.name} = {value!r} ({source}){note_suffix}",
                )
            )
    for key in unknown_keys(home):
        rows.append(
            SettingRow(name="unknown", verdict="WARN", detail=f"unknown settings config key: {key}")
        )
    for var in unknown_override_vars():
        rows.append(
            SettingRow(
                name="unknown",
                verdict="WARN",
                detail=f"unrecognized override env var (typo or wrong case?): {var}",
            )
        )
    rows.extend(SettingRow(name="retired", verdict="WARN", detail=retired_key_detail(key))
                for key in retired_keys(home))
    rows.extend(_intents_preflight_rows(home))
    return rows


def _skill_writing_misread(home: Path | str) -> str | None:
    """`doctor settings`' WARN for an ``overseer.skill_writing`` value in
    config.yaml that is not ``auto``, ``on`` or ``off`` -- a YAML boolean,
    ``null``, an empty string, a typo -- or ``None`` (SK3 fix round 2, gate
    r2 MINOR; S-107 part 6). The overseer reads such a value as
    ``off`` (`overseer.skills.writing_mode`), while :func:`resolve_setting`
    would show the default, ``auto``, for a boolean, ``null`` or an empty
    string; this row says what the overseer obeys. Mirrors
    ``writing_mode``'s rule; it cannot call it (that module imports this
    one)."""
    found = config.settings_leaf(home, "overseer", "skill_writing")
    if found is None:
        return None
    raw = found[1]
    if isinstance(raw, str) and raw in SKILL_WRITING_MODES:
        return None
    return (
        f"overseer.skill_writing = 'off' (config:overseer.skill_writing) -- config.yaml holds "
        f"{raw!r}, which is not auto, on or off, so the overseer reads it as off and keeps "
        "every skill it builds or changes as a draft; a person sets it with `self-learn "
        "config set overseer.skill_writing auto|on|off`"
    )


def _intents_preflight_rows(home: Path | str) -> list[SettingRow]:
    """Gate r1 MAJOR-3 (§7.2a.7, REQUIRED): "`doctor` carries a row
    that reads the ledger's `.intents/` and reports 'N stopped
    intent(s) — last recovery failure at <at, or "unknown" for an
    unreadable file>; ledger writes refuse; run …'." The machinery
    already exists (:func:`intents.classify_status`) -- this is a
    printer, not a design. Silent on `"ok"` with nothing stopped
    (the ordinary case) and on `"busy"` (transient contention, not an
    outage this interactive, on-demand surface need alarm about) --
    but NEVER silent on a probe failure, matching the pending hook's
    own "never as free" discipline for the identical fact.

    Gated on :func:`ledger.home_state` == ``"ok"`` first: `doctor` must
    work on a pristine home with no config.yaml at all (Doc-c), and a
    home that is missing, not a repo, or never bootstrapped has no
    `.intents/` to probe -- calling `classify_status` there would just
    surface `gitops`'s "not a git repository" as a spurious probe-error
    WARN on the ordinary, silent, no-ledger-yet state."""
    if ledger.home_state(home) != "ok":
        return []
    status = intents.classify_status(home)
    if status.probe == "error":
        return [
            SettingRow(
                name=".intents",
                verdict="WARN",
                detail=(
                    f"could not probe the ledger lock ({status.error}) -- a "
                    "STOPPED intent may be hidden; run `self-learn status` "
                    "and re-run doctor"
                ),
            )
        ]
    if status.busy or not status.stopped:
        return []
    ats = [s.at for s in status.stopped if s.at]
    last_at = max(ats) if ats else "unknown"
    n = len(status.stopped)
    return [
        SettingRow(
            name=".intents",
            verdict="WARN",
            detail=(
                f"{n} stopped intent(s) -- last recovery failure at {last_at}; "
                "ledger writes refuse; run `self-learn reconcile "
                f"--clear-intent {status.stopped[0].id}` after inspecting the "
                "offender" + (" (each in turn)" if n > 1 else "")
            ),
        )
    ]


# ===================================================================== #
# U-settings Phase 2 -- the settings PAGE's write path: `self-learn
# config get|set|unset`. Phase 1 above is read-only (`preflight`,
# `resolve_setting`, `override`); this section adds the one sanctioned
# mutation door onto config.yaml this registry's keys use, mirroring
# `hosts.py`'s `host_add` shape (validate -> take the lock -> write ->
# commit) rather than inventing a second write discipline.
# ===================================================================== #


class SettingsError(Exception):
    """A `config get`/`set`/`unset` verb refused before writing, or its
    write itself failed. The settings-registry analogue of `hosts.
    HostsError` -- NOT a `verbs.VerbError` subclass: `verbs.py` already
    imports `ledger_ops.py` and `telemetry.py`, and BOTH of those import
    THIS module (`settings.py`) at their own top level -- a module-level
    `settings.py -> verbs.py` edge would close a real import cycle
    (`settings -> verbs -> ledger_ops -> settings`). `cli.py`'s dispatch
    catches this family directly, exactly as it already catches `hosts.
    HostsError` beside `verbs.VerbError` in `_cmd_host`."""


class UnknownSettingError(SettingsError):
    """`name` is not a `REGISTRY` entry. The CLI maps this to
    `EXIT_USAGE` (64) -- the same code an unknown/malformed record id
    gets everywhere else in this CLI."""

    def __init__(self, name: str) -> None:
        super().__init__(f"unknown setting {name!r}")
        self.name = name


class InvalidSettingValueError(SettingsError):
    """`value` did not parse as `name`'s `kind`, or `validate` rejected
    it as out of range. The CLI maps this to exit 1 -- a well-formed
    invocation refused on a business rule, never a usage error."""


# Presence, including an empty value, identifies an agent shell. These are
# harness session markers, not terminal-manager markers (HERDR_ENV also
# appears in the human's terminals). No override flag: an agent could pass it.
AGENT_CALLER_MARKERS = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT",
    "CODEX_THREAD_ID", "CODEX_SESSION_ID", "HERMES_SESSION_ID",
)


def agent_caller_markers() -> tuple[str, ...]:
    """Detected names only, in stable registry order; never expose env values."""
    return tuple(marker for marker in AGENT_CALLER_MARKERS if marker in os.environ)


def agent_caller() -> bool:
    """Best-effort shell detection, not a security boundary: env can be unset."""
    return bool(agent_caller_markers())


class AgentSettingRefusal(SettingsError):
    """A tier-C write from an agent shell; CLI business-rule refusal (exit 1)."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name} is the human's switch; run the same command in your own "
            "terminal (not through an agent) "
            f"(agent shell detected: {', '.join(agent_caller_markers())})"
        )


class NoConfigRungError(SettingsError):
    """`name` resolves through `REGISTRY` but has no `config.yaml` rung
    to write to (`config_section is None` -- currently reserved for a
    future bootstrap-var shape; see the `Setting.config_section`
    docstring). `config set`/`unset` raise this instead of the bare
    `assert` it replaces (code-gate MINOR-4, review r1 2026-09-01): an
    `assert` is stripped under `python -O` and, before this fix, was
    reachable at all only because nothing enforced its own premise --
    the registry-time invariant added alongside this class
    (`_setting.tier == "C"` whenever `config_section is None`) now
    makes the case unreachable from a real registry entry, but
    `config_set`/`config_unset` still refuse it explicitly rather than
    trust that invariant never regresses. The CLI maps this to exit 1,
    same family as `InvalidSettingValueError`."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name}: no config.yaml rung to write -- this setting cannot be set/unset"
        )
        self.name = name


def setting_row(home: Path | str, setting: Setting) -> dict[str, object]:
    """The ONE row shape `config get --json` and `config set --json`
    both emit (dispatch pin: "set --json should emit the same row
    object get --json emits") -- built from a single fresh
    :func:`resolve_setting` call, never cached, matching this module's
    own no-caching discipline. `warn` is the exact
    :func:`_override_warn_text` sentence when `source` is an active
    override, else `None` -- the settings page renders it VERBATIM as
    its WARN banner (dispatch: "reuse that text, do not paraphrase
    it"), and this is the one place that text is computed for JSON
    consumers, so the CLI table (`preflight`) and the page can never
    drift apart."""
    value, source = resolve_setting(home, setting)
    return {
        "name": setting.name,
        "value": value,
        "source": source,
        "kind": setting.kind,
        "default": _default_value(setting),
        "description": setting.description,
        "tier": setting.tier,
        "warn": _override_warn_text(setting) if source.startswith("override:") else None,
        # M-S (S-58, r5-m1(c)): the fold detail, named `note` outright
        # (not hedged as "e.g.") -- `None` unless the answering rung's
        # raw value was actually folded by `validate`.
        "note": _fold_note(home, setting, source),
    }


def _dirty_config_check(home: Path) -> None:
    """The dirty-target refusal `config set`/`unset` share with every
    other compile-target verb (dispatch pin: "find the helper they
    share rather than writing a new check") -- `gitops.paths_dirty` is
    that shared primitive; `verbs.DirtyTargetError`/`GITOPS_DIRTY_
    MARKER` are its message vocabulary, imported HERE, lazily, inside
    the function body rather than at module level -- see
    :class:`SettingsError`'s docstring for why a module-level import
    would close a cycle. Runs BEFORE the commit lock opens (hosts.py's
    own `host_add` ordering: a pre-flight refusal must never touch the
    lock at all), against `config.yaml` itself -- the compile TARGET
    here is the ledger's own policy file, not a host repo file, but the
    discipline (uncommitted changes to the exact file about to be
    rewritten refuse the write) is the same one `_abort_if_dirty`
    already enforces elsewhere."""
    from .verbs import DirtyTargetError, GITOPS_DIRTY_MARKER

    if gitops.paths_dirty(home, config.config_path(home)):
        raise DirtyTargetError(
            f"config.yaml {GITOPS_DIRTY_MARKER} -- commit/stash first, then re-run"
        )


def _commit_or_half_written(home: Path, touched: list[Path], message: str, body: str | None) -> None:
    """stage -> pinned commit, with the state fact attached to a
    failure -- now the thin `settings` face of :func:`gitops.stage_and_
    commit` (audit 2026-09-02 sprint-1 M-O), which replaces the ported
    copy of `hosts.py`'s own `_commit_or_half_written` this docstring
    used to describe (hosts.py does not export it, and importing a
    private name across modules was worse than the duplication -- moot
    now that both delegate to the same seam instead). **Callers must
    already hold** `gitops.commit_lock(home)`."""
    gitops.stage_and_commit(home, touched, message, body)


def _scan_config_write_or_refuse(name: str, note: str | None, value: str | None) -> None:
    """MAJOR-2 (code-gate review r1 2026-09-01): `config set --note`
    was the one note-bearing verb that skipped the secret scan every
    OTHER verb runs (`verbs._scan_or_refuse`) -- measured live: `reject
    --note "...ghp_..."` refused rc 1, `config set --note "...ghp_..."`
    committed rc 0. Coordinator's ruling (same review): skipping the
    scan on a typed int/float/bool VALUE is right (a number cannot
    carry a token) -- but `note` is free prose landing in a committed
    (and eventually PUSHED) commit BODY regardless of `kind`, and a
    `kind == "str"` VALUE can itself be a token (`ledger.actor` lands
    in the commit SUBJECT itself, not just the body). Scans `note`
    unconditionally and `value` only when the caller passes one
    (callers pass `None` for every non-`str` kind) -- both BEFORE the
    ledger's commit lock opens, the same pre-flight tier as
    `_dirty_config_check`. `verbs.SecretRefusal`/`scan.scan`/`scan.
    format_refusal` are imported HERE, lazily, for the same
    import-cycle reason `_dirty_config_check` already documents (only
    `verbs` closes a cycle; `scan.py` itself has zero internal package
    imports, but importing everything from one place keeps this
    function's dependency story in one paragraph)."""
    from .scan import format_refusal, scan as secret_scan
    from .verbs import SecretRefusal

    findings: list[tuple[str, list]] = []
    if note:
        hits = secret_scan(note)
        if hits:
            findings.append(("--note", hits))
    if value:
        hits = secret_scan(value)
        if hits:
            findings.append((f"{name} value", hits))
    if not findings:
        return
    parts = [f"{label}:\n{format_refusal(hits)}" for label, hits in findings]
    all_hits = [h for _, hits in findings for h in hits]
    raise SecretRefusal(
        "secret scan hit -- refusing this verb (P2-7; no bypass):\n" + "\n".join(parts),
        all_hits,
    )


def _plain_scalar(value: object) -> object:
    """Unwrap a `config.present` (round-trip `load_editable`) scalar
    down to the plain builtin type `_parse_env_value` would have
    produced for the SAME value, so `config_set`'s idempotent check
    below can compare like to like via `type(...) is type(...)`.

    Round-trip mode wraps some scalars in a format-preserving subtype
    -- confirmed empirically (not just for specially-formatted values):
    a plain `6.5` in `config.yaml` round-trips as `ScalarFloat`, NEVER
    bare `float`. Left unnormalized, `type(...) is type(...)` would
    NEVER match for a float setting whose value already matches (`
    ScalarFloat is not float`), so a byte-identical re-`set` of ANY
    float setting would always look like a change -- reach `set_leaf`,
    write byte-identical content, and `git commit` would refuse
    "nothing to commit", which `_commit_or_half_written` misreports as
    a false HALF-WRITTEN state. Exactly the bug the idempotent check
    exists to prevent (this function's own docstring, above), just
    reintroduced through the read side instead of the write side.

    `bool` is checked FIRST because it is itself an `int` subclass in
    Python -- `1 == True` must keep comparing as DIFFERENT (a
    hand-written `1` where a `bool` setting expects `true` is still a
    real change), so a `bool` value is returned as-is, never coerced
    through the `int` branch below it."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value


def config_set(
    home: Path | str, name: str, raw_value: str, *, note: str | None = None
) -> Setting:
    """`self-learn config set <name> <value>`'s backing function:
    validate `raw_value` THROUGH the registry's own parser and
    `validate` -- the same two functions :func:`resolve_setting` uses,
    so a value the resolver would reject can never be written in the
    first place (dispatch pin) -- then write + commit `config.yaml`
    (`self-learn: config set <name>=<value>`, `note` as the commit
    body) under the ledger's commit lock, mirroring `hosts.host_add`'s
    shape byte-for-byte: pre-flight refusals first (unknown name,
    unparseable/out-of-range value, a dirty config.yaml), THEN the
    lock, THEN the write, THEN the commit.

    `raw_value` is parsed with :func:`_parse_env_value` -- the
    registry's OWN string-to-`kind` parser (the same one the env RUNG
    uses): a `bool` setting takes literal `"1"`/`"0"`, matching this
    codebase's env-boolean convention, NOT the YAML spellings
    `config.yaml` itself is written in -- `_parse_config_value`, a
    different function, is what reads the file back. Returns the
    `Setting` that was written; callers re-resolve
    (:func:`setting_row`) for the post-write value/source rather than
    trusting the value just parsed, because an active override can
    mask what was just committed (dispatch: "if an active override or
    anything else masks the new value, the operator sees it")."""
    try:
        setting = by_name(name)
    except KeyError:
        raise UnknownSettingError(name) from None

    if setting.tier == "C" and agent_caller():
        raise AgentSettingRefusal(name)

    # MINOR-4 (review r1 2026-09-01): this used to be a bare `assert`
    # AFTER value-parsing -- checked first now, both because "can this
    # setting even be written" is more fundamental than "is this value
    # valid for it", and because an `assert` is not a refusal a caller
    # (the CLI, the UI route) can catch and print cleanly.
    if setting.config_section is None or setting.config_key is None:
        raise NoConfigRungError(name)

    parsed = _parse_env_value(raw_value, setting.kind)
    if parsed is None:
        # MINOR-3 (review r1 2026-09-01): the "(bool settings take 1 or
        # 0)" hint used to be appended UNCONDITIONALLY -- an int/float/
        # str parse failure showed a hint about a completely different
        # kind. Only a `bool` setting takes that literal-1-or-0 shape.
        hint = " (bool settings take 1 or 0)" if setting.kind == "bool" else ""
        raise InvalidSettingValueError(f"{name}={raw_value!r} is not a valid {setting.kind}{hint}")

    # M-S (S-58, MAJOR-3/r4-M1/r5-M1): `accepts` runs on the PARSED
    # value, BEFORE `validate` -- placed after `validate` it would see
    # `validate`'s own CLAMPED output (an off-whitelist write already
    # folded to the in-place default) and let a clamping `validate`
    # launder every refused write into an accepted, silently different
    # one, the exact inverse of "REJECTED outright ... never committed".
    if setting.accepts is not None and not setting.accepts(parsed):
        hint = f" ({setting.accepts_hint})" if setting.accepts_hint else ""
        raise InvalidSettingValueError(f"{name}={raw_value!r} is not accepted{hint}")

    final, rejected = _apply_validate(parsed, setting.validate)
    if final is None:
        assert rejected  # _apply_validate only returns None via a validate rejection here
        # NIT-1 (review r1 2026-09-01): "is out of range for float"
        # names the TYPE, not the bound -- append the entry's own
        # `validate_hint` (e.g. "must be > 0") when it has one, so the
        # refusal says what would have been accepted.
        hint = f" ({setting.validate_hint})" if setting.validate_hint else ""
        raise InvalidSettingValueError(f"{name}={raw_value!r} is out of range for {setting.kind}{hint}")

    home = Path(home)

    # MAJOR-2 (review r1 2026-09-01): scan `note` always, and the
    # parsed VALUE too when this is a `str`-kind setting (`_parse_env_
    # value` only ever returns `str | None` for that kind -- `cast` is
    # a type-checker fact, not a runtime branch). Pre-lock, beside the
    # dirty check below -- see `_scan_config_write_or_refuse`'s own
    # docstring for the full "why".
    _scan_config_write_or_refuse(
        name, note, cast(str, final) if setting.kind == "str" else None
    )

    # MINOR-1 (review r1 2026-09-01): the dirty-check used to run AFTER
    # the idempotent short-circuit below, so a no-op `set` (the value
    # already matches) printed success against an uncommitted config.
    # yaml without ever looking at it. Dirty check first; the
    # short-circuit only fires against a tree already known clean.
    _dirty_config_check(home)

    # Idempotent leg (`host_add`'s own precedent: an unchanged re-
    # registration commits nothing) -- against the RAW stored value
    # (never the resolved one -- an active override must not make this
    # look like a no-op write when the file itself would genuinely
    # change). Without this, `git commit` on a byte-identical write
    # fails "nothing to commit", which the write-already-happened
    # wrapper below would misreport as a HALF-WRITTEN state -- caught
    # live: setting a key to the value it already holds a second time
    # crashed with exactly that false "WRITE NOT COMMITTED" before this
    # fix. `type(...) is type(...)` guards the one gap plain `==`
    # leaves open in Python (`1 == True`) -- a hand-written `1` where
    # this registry's `bool` kind expects `true` must still be treated
    # as a real change worth writing/normalizing, not silently left in
    # place because it happens to compare equal.
    #
    # MINOR-1 (review r2 2026-09-02): this used to read via the LENIENT
    # `config.settings_leaf` (silent `None` on a malformed config.yaml),
    # so a malformed committed file fell all the way through to
    # `gitops.commit_lock` below before anything noticed -- if another
    # producer already held that lock, `set` sat out the full 150s
    # `COMMIT_LOCK_TIMEOUT` and reported "another self-learn producer is
    # wedged mid-commit", sending the operator hunting a producer that
    # does not exist. `config.present` -- the SAME strict, pre-lock
    # check `config_unset` already used (MINOR-2, review r1) -- raises
    # `ConfigWriteError` HERE instead, before the lock is ever
    # requested, so the real problem (the malformed file) is what the
    # operator sees, fast, lock contention or not. `_plain_scalar`
    # (right above this function) unwraps `present`'s round-trip
    # scalar type before the `type(...) is type(...)` compare below --
    # see its own docstring for why that is NOT optional (a plain
    # `ScalarFloat is not float` regression this switch would
    # otherwise reintroduce for every float-kind setting).
    is_set, current_value = config.present(home, setting.config_section, setting.config_key)
    current_value = _plain_scalar(current_value)
    if is_set and type(current_value) is type(final) and current_value == final:
        return setting

    message = f"self-learn: config set {name}={final!r}"
    with intents.ledger_write(home) as recovered:  # S-62: checks for a pre-existing STOP first
        intents.announce_recovered(recovered)
        path = config.set_leaf(home, setting.config_section, setting.config_key, final)
        _commit_or_half_written(home, [path], message, note)
    return setting


def config_unset(home: Path | str, name: str, *, note: str | None = None) -> tuple[Setting, bool]:
    """`self-learn config unset <name>`'s backing function -- removes
    `name`'s config.yaml key (pruning now-empty nested maps upward,
    including the section itself), commits `self-learn: config unset
    <name>`. Idempotent, `host_add`-style: an ALREADY-absent key is a
    no-op that opens no lock and commits nothing (checked via
    `config.present`, BEFORE the lock -- a pre-flight fact, not a
    mutation). Returns `(setting, removed)`.

    Uses `config.present` here, NOT `config.settings_leaf` (MINOR-2,
    review r1 2026-09-01): `settings_leaf` is the LENIENT read path
    `resolve_setting` uses -- it warns-and-returns-`None` on a
    malformed `config.yaml`, which made THIS function report "already
    unset, nothing to remove" against the exact same broken file
    `config set` refuses outright. `config.present` raises
    :class:`config.ConfigWriteError` on that same malformed shape --
    same file, same refusal, matching `set`'s own posture."""
    try:
        setting = by_name(name)
    except KeyError:
        # Removal-only descriptor: never re-register an obsolete setting or
        # let config set resurrect it. Share all ordinary unset safeguards.
        if re.fullmatch(r"invocation\.backend(?:_[A-Za-z0-9_-]+)?", name) is None:
            raise UnknownSettingError(name) from None
        setting = Setting(
            name=name, env_var=None, config_section="invocation",
            config_key=name.partition(".")[2], kind="str", default="",
            description="retired backend selector", operator_facing=False,
        )
    if setting.tier == "C" and agent_caller():
        raise AgentSettingRefusal(name)

    if setting.config_section is None or setting.config_key is None:
        raise NoConfigRungError(name)  # MINOR-4, same fix as config_set

    home = Path(home)

    # MAJOR-2 (review r1 2026-09-01): `unset` takes a `--note` too --
    # it lands in the unset commit's body exactly like `set`'s does,
    # so it gets the same pre-lock scan (no VALUE to scan here, only
    # `note`).
    _scan_config_write_or_refuse(name, note, None)

    # MINOR-1's ordering fix applies here too, for the same reason the
    # review gave for `set`: an existence pre-check reachable BEFORE
    # the dirty-check would let a no-op `unset` succeed silently
    # against an uncommitted config.yaml. Dirty check runs first; the
    # short-circuit only fires against a tree already known clean.
    _dirty_config_check(home)

    is_set, _current_value = config.present(home, setting.config_section, setting.config_key)
    if not is_set:
        return setting, False  # nothing to remove -- no lock, no commit

    message = f"self-learn: config unset {name}"
    with intents.ledger_write(home) as recovered:  # S-62: checks for a pre-existing STOP first
        intents.announce_recovered(recovered)
        removed = config.unset_leaf(home, setting.config_section, setting.config_key)
        if not removed:
            # Raced away between the pre-flight read and the lock (another
            # process unset it first) -- still a no-op, not a failure.
            return setting, False
        _commit_or_half_written(home, [config.config_path(home)], message, note)
    return setting, True
