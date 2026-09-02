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
``"default"``.

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

**No caching, anywhere in this module (load-bearing, not style).**
``serve._worker_autokick_disabled()`` mutates ``os.environ`` mid-process
as a real API (temporarily neutralizing the SAME kill switch a human
has); :func:`resolve_setting` must re-read ``os.environ`` and
``config.yaml`` on every call for that mechanism to keep working, the
same discipline ``config.py`` already holds for every reader in it.

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

import os
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import config

__all__ = [
    "Kind",
    "Setting",
    "SettingRow",
    "REGISTRY",
    "resolve_setting",
    "by_name",
    "unknown_keys",
    "preflight",
]

Kind = Literal["str", "int", "float", "bool"]


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
    #: ``None`` => a bootstrap var with no config.yaml rung (mirrors
    #: ``provider._resolve_str_setting``'s ``config_key=None`` shape --
    #: `SELF_LEARN_HOME` is the one entry that needs this: resolving the
    #: ledger home FROM a file inside that same home is circular).
    config_section: str | None
    config_key: str | None
    kind: Kind
    #: A literal, or a zero-arg callable evaluated lazily ONLY when every
    #: rung above misses (mirrors ``provider.model_for``'s "the surface's
    #: shipped default function, CALLED, never copied").
    default: object
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
    validate: Callable[[object], object | None] | None = None


def _default_value(setting: Setting) -> object:
    return setting.default() if callable(setting.default) else setting.default


def _parse_env_value(raw: str, kind: Kind) -> object | None:
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


def _parse_config_value(value: object, kind: Kind) -> object | None:
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


def resolve_setting(home: Path | str, setting: Setting) -> tuple[object, str]:
    """The registry's ONE resolution function (U-settings Phase 1 §2,
    flipped 2026-09-01 -- module docstring's "Two precedence
    directions, on purpose"): config.yaml, then env, then the built-in
    default -- ``provider.py``'s exact source-string vocabulary, just
    the opposite rung ORDER from that mechanism.

    Fail-closed PER RUNG, not per resolution (the spec's §1.2 boundary
    pin, carried through the flip): a value that is present at a rung
    but does not parse as `setting.kind`, or that `validate` rejects,
    warns on stderr naming the key and the offending raw value and
    FALLS THROUGH to the next rung -- it does not dead-end at the
    default. A typo in config.yaml must never brick a role the env var
    (or the default) would have served; a malformed env value still
    falls through to the default, same as before the flip since env is
    now the last LIVE rung.

    No caching: every call re-reads ``os.environ`` and ``config.yaml``
    fresh (module docstring)."""
    if setting.config_section is not None:
        assert setting.config_key is not None  # invariant: paired at registration
        found = config.settings_leaf(home, setting.config_section, setting.config_key)
        if found is not None:
            key, value = found
            parsed = _parse_config_value(value, setting.kind)
            if parsed is not None and setting.validate is not None:
                parsed = setting.validate(parsed)
            if parsed is not None:
                return parsed, f"config:{setting.config_section}.{key}"
            _warn(
                f"config.yaml {setting.config_section}.{key}={value!r} is not a "
                f"valid {setting.kind} for {setting.name} — falling through to env/default"
            )
            # NOT a return: falls through to the env rung below, per the
            # spec's §1.2 boundary pin -- a malformed config value must
            # not dead-end a role the env var (or default) would serve.

    raw = os.environ.get(setting.env_var)
    if raw:
        parsed = _parse_env_value(raw, setting.kind)
        if parsed is not None and setting.validate is not None:
            parsed = setting.validate(parsed)
        if parsed is not None:
            return parsed, f"env:{setting.env_var}"
        _warn(
            f"{setting.env_var}={raw!r} is not a valid {setting.kind} for "
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
        validate=lambda v: max(0.0, v),  # a zero coalesce is meaningful; never falls back
    ),
    Setting(
        name="worker.invoke_timeout_secs",
        env_var="SELF_LEARN_INVOKE_TIMEOUT_SECS",
        config_section="worker",
        config_key="invoke_timeout_secs",
        kind="float",
        default=1800.0,  # worker.INVOKE_TIMEOUT_SECS
        description="subprocess timeout (seconds) for the worker's batch invocation",
        validate=lambda v: v if v > 0 else None,  # a <=0 timeout kills every run instantly (E4)
    ),
    Setting(
        name="worker.repair_timeout_secs",
        env_var="SELF_LEARN_REPAIR_TIMEOUT_SECS",
        config_section="worker",
        config_key="repair_timeout_secs",
        kind="float",
        default=600.0,  # worker.REPAIR_TIMEOUT_SECS
        description="subprocess timeout (seconds) for the worker's repair round",
        validate=lambda v: v if v > 0 else None,
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
        validate=lambda v: max(0, v),
    ),
    Setting(
        name="miner.cap_per_session",
        env_var="SELF_LEARN_MINE_CAP_PER_SESSION",
        config_section="miner",
        config_key="cap_per_session",
        kind="int",
        default=2,  # miner.DEFAULT_CAP_PER_SESSION
        description="cap on records mined per scanned session, before the run-wide cap",
        validate=lambda v: max(0, v),
    ),
    Setting(
        name="miner.pending_gate",
        env_var="SELF_LEARN_MINE_PENDING_GATE",
        config_section="miner",
        config_key="pending_gate",
        kind="int",
        default=25,  # miner.DEFAULT_PENDING_GATE
        description="pending-queue size that gates a mining run",
        validate=lambda v: max(0, v),
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
        validate=lambda v: max(v, 0),
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
        validate=lambda v: v if v > 0 else None,
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
)

#: Registration-time invariant: `name` is always `f"{config_section}.
#: {config_key}"` (or bare, for a bootstrap var with no config rung) --
#: relied on by `preflight`'s row labels and by callers building a
#: `by_name` lookup. Checked once at import time, not per-call.
for _setting in REGISTRY:
    if _setting.config_section is not None:
        assert _setting.name == f"{_setting.config_section}.{_setting.config_key}", _setting.name
del _setting

_BY_NAME: dict[str, Setting] = {s.name: s for s in REGISTRY}


def by_name(name: str) -> Setting:
    """The one registry entry named `name`. Raises `KeyError` for a name
    outside `REGISTRY` (a programming error, never operator input)."""
    return _BY_NAME[name]


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
        by_section.setdefault(setting.config_section, set()).add(setting.config_key)
    found: list[str] = []
    for section in sorted(by_section):
        known = frozenset(by_section[section])
        for key in config.settings_unknown_keys(home, section, known):
            found.append(f"{section}.{key}")
    return found


@dataclass(frozen=True)
class SettingRow:
    name: str
    verdict: str  # "INFO" | "WARN" -- this surface is introspection-only, never FAIL (nothing here gates)
    detail: str


def preflight(home: Path | str) -> list[SettingRow]:
    """`doctor settings`'s single source of truth (mirrors `provider.
    preflight`'s `Doc-0`: computes every row, prints nothing). One INFO
    row per registry entry (name, resolved value, source), then one WARN
    row per unknown config.yaml key (`unknown_keys`)."""
    rows: list[SettingRow] = []
    for setting in REGISTRY:
        value, source = resolve_setting(home, setting)
        rows.append(
            SettingRow(name=setting.name, verdict="INFO", detail=f"{setting.name} = {value!r} ({source})")
        )
    for key in unknown_keys(home):
        rows.append(
            SettingRow(name="unknown", verdict="WARN", detail=f"unknown settings config key: {key}")
        )
    return rows
