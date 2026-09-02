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
``"default"`` -- plus one new label this module adds,
``"override:NAME"`` (below).

**Two precedence directions, on purpose (ruling: user, 2026-09-01,
confirming their own 2026-07-19 ruling recorded in
``docs/specs/self-learn/drafts/settings-surface-spec.md`` §1.2; see
``docs/specs/self-learn/03-decisions.md`` S-58).** This registry's 20
settings resolve **``config.yaml > explicit env var > code
default``**: the committed config is the single source of truth, and
an env var only fills a gap config.yaml leaves silent -- it never
overrides a saved policy. This is the OPPOSITE direction from
``provider.py``'s ``model_for()``/``_resolve_provider()`` and
``invocation/registry.py``'s backend-selection chain, which stay
**``env > config.yaml > default``** and are explicitly OUT OF SCOPE
for this flip -- untouched, not an oversight. That second mechanism
governs provider/model/backend selection: those are emergency rollback
switches, and an operator must be able to override one from a live
shell without waiting on a commit+sync round-trip. This registry's 20
settings are ordinary operating policy, where the opposite trade holds:
a synced ``config.yaml`` should beat a machine-local env pin, and a
machine that needs a local exception expresses it in config or unsets
the key. The two directions coexist on purpose -- do not "fix" the
discrepancy by unifying them.

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
import socket
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from . import config, gitops

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


def _warn(message: str) -> None:
    print(f"self-learn: settings — {message}", file=sys.stderr)


@dataclass(frozen=True)
class Setting:
    #: The dotted registry key, e.g. ``"worker.coalesce_secs"`` -- also
    #: the `doctor settings` row label and the ``config:`` source's
    #: ``section.key`` suffix (identical to ``config_section``.
    #: ``config_key`` by construction, checked at import time below).
    name: str
    env_var: str
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
    #: number (E4's asymmetry, carried over from `worker._timeout_secs`).
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
    #: U-settings Phase 2 (the settings page) — the exposure tier the
    #: page's editor honors (dispatch's ruling, carrying the ratified
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
    `SELF_LEARN_OVERRIDE_<NAME>`, dots to underscores, uppercased --
    e.g. `worker.autokick` -> `SELF_LEARN_OVERRIDE_WORKER_AUTOKICK`.
    Namespaced (not the setting's own `env_var`) so an operator's
    ordinary env pin can never collide with a process's override of
    itself -- the two channels stay distinguishable on sight."""
    return "SELF_LEARN_OVERRIDE_" + name.upper().replace(".", "_")


#: A reserved marker distinguishing "the override IS the value `None`"
#: from "no override is set" (env-var absence, tested `is not None`
#: below) and from every ordinary encoded value (`_encode_override_
#: value`'s other branches never produce this exact string -- no `str`-
#: kind setting's `str(value)` can equal it either, short of an
#: operator deliberately typing this literal token). Needed because
#: `None` is semantically overloaded THROUGHOUT this module: it is
#: `sdk.max_budget_usd`'s own default (meaning "unlimited"), and it is
#: also every parse function's "this value did not parse" signal --
#: two different meanings that must never be confused on the wire
#: (MINOR-4, review r2 2026-09-01).
_OVERRIDE_NONE_MARKER = "\x01SELF_LEARN_OVERRIDE_NONE\x01"


def _encode_override_value(value: SettingValue, kind: Kind) -> str:
    """:func:`override`'s WRITER side -- the exact string spellings
    `_parse_env_value` reads back (`1`/`0` for bool; `str()` for
    numeric/str; `_OVERRIDE_NONE_MARKER` for `None`), so a round trip
    through the override channel can never drift from the ambient-env
    rung's own parsing vocabulary (and never collide with it either,
    for `None`)."""
    if value is None:
        return _OVERRIDE_NONE_MARKER
    if kind == "bool":
        return "1" if value else "0"
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


def resolve_setting(home: Path | str, setting: Setting) -> tuple[SettingValue, str]:
    """The registry's ONE resolution function (U-settings Phase 1 §2;
    flipped 2026-09-01, S-58; override channel added same day, a
    Blocker fix -- module docstring's "Three rungs, on purpose"):
    **override channel, then config.yaml, then env, then the built-in
    default** -- ``provider.py``'s exact source-string vocabulary
    (plus the new `"override:<name>"` label), a different rung ORDER
    from that mechanism, and now a rung ABOVE both.

    Fail-closed PER RUNG, not per resolution (the spec's §1.2 boundary
    pin, carried through the flip and the override addition): a value
    that is present at a rung but does not parse as `setting.kind`, or
    that `validate` rejects, warns on stderr naming the key and the
    offending raw value and FALLS THROUGH to the next rung -- it does
    not dead-end at the default. A typo in config.yaml must never
    brick a role the env var (or the default) would have served; a
    malformed env value still falls through to the default, same as
    before the flip since env is the last LIVE rung.

    No caching of config.yaml/env: every call re-reads ``os.environ``
    and ``config.yaml`` fresh (module docstring) -- necessary but, per
    the Blocker review, NOT by itself sufficient to keep
    :func:`serve._worker_autokick_disabled`'s mechanism working under
    config-wins; see :func:`override` for why a THIRD rung was needed."""
    override_var = _override_env_var(setting.name)
    override_raw = os.environ.get(override_var)
    # MINOR-4 (review r2 2026-09-01): presence is `is not None`, NOT
    # truthiness -- `override("miner.transcripts_dir", "")` writes the
    # literal empty string, and a truthy check would read that as
    # "nothing set" and silently fall through to config/env/default,
    # losing the override the caller explicitly asked for. This is a
    # DIFFERENT rule from the config/env rungs below, on purpose: an
    # empty CONFIG.YAML string or empty ENV VAR is ambient and
    # ambiguous ("did the operator mean this, or leave it blank by
    # accident?" -- M-4's own call was "no answer"); a programmatic
    # `override(name, "")` is neither ambient nor accidental -- the
    # caller named the exact value.
    if override_raw is not None:
        if override_raw == _OVERRIDE_NONE_MARKER:
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
        else:
            final, rejected = _apply_validate(parsed, setting.validate)
            if final is not None:
                return final, f"override:{setting.name}"
            if rejected:
                _warn(
                    f"{override_var}={override_raw!r} is out of range for "
                    f"{setting.name} — falling through to config/env/default"
                )
            # `rejected` is only ever True here (validate ran on a value
            # that already parsed) -- the `if final is not None` above
            # already returned on any other outcome.

    if setting.config_section is not None:
        assert setting.config_key is not None  # invariant: paired at registration
        found = config.settings_leaf(home, setting.config_section, setting.config_key)
        if found is not None and setting.kind == "str" and found[1] == "":
            # M-4 fold (review 2026-09-01): an empty config.yaml string is
            # "no answer", exactly like the env rung's own `if raw:` — not
            # a malformed value (no warn), just silently not-present here.
            # Before this, `transcripts_dir: ""` parsed as a VALID empty
            # string and resolved to `Path('.')`, while the identically
            # empty env var fell through silently -- asymmetric.
            found = None
        if found is not None:
            key, value = found
            parsed = _parse_config_value(value, setting.kind)
            if parsed is None:
                _warn(
                    f"config.yaml {setting.config_section}.{key}={value!r} is not a "
                    f"valid {setting.kind} for {setting.name} — falling through to env/default"
                )
                # NOT a return: falls through to the env rung below, per
                # the spec's §1.2 boundary pin -- a malformed config
                # value must not dead-end a role the env var (or
                # default) would serve.
            else:
                final, rejected = _apply_validate(parsed, setting.validate)
                if final is not None:
                    return final, f"config:{setting.config_section}.{key}"
                if rejected:
                    _warn(
                        f"config.yaml {setting.config_section}.{key}={value!r} is out "
                        f"of range for {setting.name} — falling through to env/default"
                    )

    raw = os.environ.get(setting.env_var)
    if raw:
        parsed = _parse_env_value(raw, setting.kind)
        if parsed is None:
            _warn(
                f"{setting.env_var}={raw!r} is not a valid {setting.kind} for "
                f"{setting.name} — using the default"
            )
        else:
            final, rejected = _apply_validate(parsed, setting.validate)
            if final is not None:
                return final, f"env:{setting.env_var}"
            if rejected:
                _warn(
                    f"{setting.env_var}={raw!r} is out of range for "
                    f"{setting.name} — using the default"
                )

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
    # NOTE: `SELF_LEARN_READER_TIMEOUT_SECS` (the miner reader's own
    # timeout) is deliberately NOT registered here. `miner.reader_
    # timeout_secs()` calls `worker._timeout_secs(env_var, default)`
    # directly, and `test_u_fw100.py::test_shares_worker_helper_not_a_
    # reimplementation` monkeypatches `worker._timeout_secs` itself to
    # PROVE that sharing (a prior unit's "guard the build decision, do
    # not re-open" test). Routing this setting through the registry
    # instead would break that guard for no operator-facing gain over
    # `worker.invoke_timeout_secs`/`repair_timeout_secs` (already
    # registered below) sharing the exact same parsing/validation. Left
    # as a known Phase 1 gap — see the build report.
    Setting(
        name="miner.transcripts_dir",
        env_var="SELF_LEARN_TRANSCRIPTS_DIR",
        config_section="miner",
        config_key="transcripts_dir",
        kind="str",
        default="~/.claude/projects",
        description="root directory the miner scans for Claude Code session transcripts",
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
    # (`.` and `_` both fold to `_` -- `a.b_c` and `a_b.c` collide). 21
    # entries give 21 distinct vars today; this catches the day a 22nd
    # entry's name silently steals another entry's override channel,
    # the same invariant-at-registration-time discipline as the
    # `name == section.key` assert above.
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
    itself; `doctor settings` renders one WARN row per hit."""
    legal = frozenset(_override_env_var(s.name) for s in REGISTRY)
    return sorted(
        k for k in os.environ
        if k.startswith("SELF_LEARN_OVERRIDE_") and k not in legal
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
        value, source = resolve_setting(home, setting)
        if source.startswith("override:"):
            rows.append(
                SettingRow(
                    name=setting.name,
                    verdict="WARN",
                    detail=f"{setting.name} = {value!r} ({source}) -- {_override_warn_text(setting)}",
                )
            )
        else:
            rows.append(
                SettingRow(name=setting.name, verdict="INFO", detail=f"{setting.name} = {value!r} ({source})")
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
    return rows


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
    failure -- `hosts.py`'s own `_commit_or_half_written`, ported
    rather than imported (hosts.py does not export it, and importing a
    private name across modules is worse than the few duplicated
    lines). **Callers must already hold** `gitops.commit_lock(home)`."""
    try:
        gitops.stage(home, touched)
        gitops.commit(home, message, body=body, paths=touched)
    except gitops.HalfWrittenError:
        raise
    except gitops.GitOpsError as exc:
        raise gitops.HalfWrittenError.for_commit(home, message, touched, exc) from exc


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
    with gitops.commit_lock(home):
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
        raise UnknownSettingError(name) from None
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
    with gitops.commit_lock(home):
        removed = config.unset_leaf(home, setting.config_section, setting.config_key)
        if not removed:
            # Raced away between the pre-flight read and the lock (another
            # process unset it first) -- still a no-op, not a failure.
            return setting, False
        _commit_or_half_written(home, [config.config_path(home)], message, note)
    return setting, True
