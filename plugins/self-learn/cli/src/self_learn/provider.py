"""U-bedrock — the provider surface: Bedrock as CONFIGURATION AND CONTRACT
ONLY. No AWS credentials exist on this host, and no live Bedrock call is
ever made from this module (`Doc-a`).

`P-a` (NORMATIVE): this module lives at ROOT, a sibling of `worker.py`,
NOT inside `invocation/`. Three forces: `model_for` must delegate into
`worker`/`miner`/`analyst`, which U-seam's `HY2` forbids `invocation/**`
from doing; U-sdk's backend (inside `invocation_sdk/`) imports this
module, so root placement crosses OUT of a package rather than reaching
into one; and root modules are inside the fail-closed write census
(`test_lock_invariant.py`'s `NOT_REPO_TRUTH`), which is the better side
of that trade for a module that must never write.

`P-b` (NORMATIVE): the `worker`/`miner`/`analyst` delegation imports are
DEFERRED — they live inside `model_for`'s own body, never at module
scope. `worker`/`miner`/`analyst` all import `invocation` at module
scope (`B-1`); a module-scope import here would close
`worker -> invocation -> (U-sdk) -> provider -> worker` into a cycle at
interpreter start.

Every credential check in this module is PRESENCE-ONLY (`SEC-1`): the
code learns THAT a mechanism exists, never WHAT it contains. Nothing
this module reads from `config.yaml` or writes to any file may be a
credential, and nothing here ever writes a file (`HY3`).
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import config, settings
from .invocation import registry
from .invocation.contract import DEFAULT_BACKEND_FOR_SURFACE, SELECTOR_FOR_SURFACE, SURFACES
from .invocation.registry import KNOWN_BACKENDS, _CLI_RETIRED_MESSAGE

__all__ = [
    "PROVIDERS",
    "DEFAULT_PROVIDER",
    "ProviderResolution",
    "ProviderRefused",
    "Row",
    "resolve",
    "resolve_backend_name",
    "resolve_backend",
    "model_for",
    "MODEL_KEY_FOR_SURFACE",
    "session_env",
    "BEDROCK_ENV_KEYS",
    "SMALL_FAST_ENV_VAR",
    "BEDROCK_ALIAS_RE",
    "preflight",
    "DOCTOR_ROWS",
    "VERDICTS",
]

# ===================================================================== #
# `Prov-1` -- the provider switch (SS 3.2)
# ===================================================================== #

PROVIDERS = ("anthropic", "bedrock")
DEFAULT_PROVIDER = "anthropic"


def _resolve_provider(home: Path | str) -> tuple[str, str]:
    """`Prov-1`/`Pv-a`/`Pv-b`, plus M-S's new override rung (S-58): FOUR
    rungs, first hit wins. An empty value falls through silently. An
    unknown value warns once and resolves to `DEFAULT_PROVIDER`,
    WITHOUT falling through to the next rung.

    `provider.name`'s own runtime resolution stays a SEPARATE,
    hand-written cascade from `settings.REGISTRY`'s `provider.name`
    entry (03-decisions.md row S-58, MAJOR-2's text: "`provider.name`'s
    own runtime resolution follows the same split" the backend family
    uses) -- this function's two `print`/`config._warn` calls stay the
    ONLY emitter for a live, unknown provider value, exactly as today;
    the registry entry's OWN `validate` clamps the SAME kind of value
    silently, for `doctor settings`/`config get`, via the `note` field
    instead. `config.settings_leaf` (the generic dotted-key reader
    `resolve_setting` itself uses) replaces the deleted `config.
    provider_setting` at the config rung -- a direct, behavior-
    preserving substitution (`provider_setting`'s own `PROVIDER_KEYS`
    membership check was never load-bearing for `key="name"`, which is
    always a member)."""
    override_var = config.override_env_var("provider.name")
    override_value = os.environ.get(override_var)
    if override_value:  # truthy, matching every rung below -- R-a's "empty is no answer"
        if override_value not in PROVIDERS:
            print(
                f"self-learn: unknown provider {override_value!r} in {override_var}"
                ' — using "anthropic"',
                file=sys.stderr,
            )
            return DEFAULT_PROVIDER, "override:provider.name"
        return override_value, "override:provider.name"

    value = os.environ.get("SELF_LEARN_PROVIDER")
    if value:
        if value not in PROVIDERS:
            print(
                f'self-learn: unknown provider {value!r} in SELF_LEARN_PROVIDER'
                ' — using "anthropic"',
                file=sys.stderr,
            )
            return DEFAULT_PROVIDER, "env:SELF_LEARN_PROVIDER"
        return value, "env:SELF_LEARN_PROVIDER"

    setting = config.settings_leaf(home, "provider", "name")
    if setting is not None:
        key, cfg_value = setting
        if isinstance(cfg_value, str) and cfg_value:
            if cfg_value not in PROVIDERS:
                config._warn(
                    "provider.name must be one of anthropic, bedrock; "
                    f'got {cfg_value!r} — using "anthropic"'
                )
                return DEFAULT_PROVIDER, f"config:provider.{key}"
            return cfg_value, f"config:provider.{key}"

    return DEFAULT_PROVIDER, "default"


# ===================================================================== #
# `Res-1` -- resolution, and the re-derived backend name (SS 3.5)
# ===================================================================== #


def resolve_backend_name(home: Path | str, surface: str) -> tuple[str, str, str | None]:
    """`Rs-a` -- a SECOND, INDEPENDENT transcription of U-seam's backend
    precedence chain, now delegated to :func:`invocation.registry.
    resolve_backend_raw` (M-S, S-58, r3-M1) for the cascade itself
    (override x2, env x2, config, default) so the RUNGS are no longer
    duplicated here -- only the fold/refuse judgement is. Not read from
    `registry.backend_for` directly because that function returns a
    `Backend` OBJECT and RAISES `BackendUnavailable` for both the
    not-yet-built-`sdk` case and the retired-`cli` case (`B-3`) -- it
    cannot report a name.

    `Rs-b` -- SILENT: never prints, for any input. `resolve_backend_raw`
    itself emits nothing (pure); `registry.backend_for` already warns on
    the same inputs at the same moment through its own, unchanged
    `_resolve` call -- a second copy here would double-print on every
    invocation.

    `Rs-a1` -- the empty-value rule is ASYMMETRIC by design, preserved
    by construction inside `resolve_backend_raw` (see its own
    docstring): the env/override rungs fall through on an empty value;
    the config rung does NOT, because `config.invocation_backend`
    returns the FIRST PRESENT key regardless of its value.

    U-cleanup `MAJOR-5` -- the THIRD return element is `None`, or the
    retirement message when the raw value AT THE RUNG THAT ANSWERED was
    literally `"cli"`, computed here from ONE call to `resolve_backend_
    raw`: `refused = _refused_backend(raw_value)`, `name = _fold_
    backend(raw_value)` -- no second read, no re-entry into `registry.
    _resolve` (that stays on `registry.backend_for`'s path only)."""
    raw_value, source = registry.resolve_backend_raw(home, surface)
    return _fold_backend(raw_value), source, _refused_backend(raw_value)


#: The row's own illustrative name for this function (03-decisions.md
#: S-58); `resolve_backend_name` is the name the pinned witness
#: `test_bk3_resolve_backend_name_never_warns` requires and stays the
#: canonical definition -- this is a plain alias, not a second body.
resolve_backend = resolve_backend_name


def _fold_backend(value: str) -> str:
    return value if value in KNOWN_BACKENDS else "sdk"


def _refused_backend(value: str) -> str | None:
    """U-cleanup `MAJOR-5` -- `"cli"` is a NAMED refusal, never an unknown
    value (`SEL5`'s discriminator: `"banana"` is unknown and folds to
    `"sdk"` silently; `"cli"` is retired and refuses, loudly, everywhere)."""
    return _CLI_RETIRED_MESSAGE if value == "cli" else None


@dataclass(frozen=True)
class ProviderResolution:
    surface: str
    provider: str  # a member of PROVIDERS
    provider_source: str  # "env:SELF_LEARN_PROVIDER" | "config:provider.name" | "default"
    backend: str  # a member of registry.KNOWN_BACKENDS
    backend_source: str
    backend_refused: str | None  # U-cleanup MAJOR-5 -- non-None => a "cli" selection was refused
    region: str | None
    region_source: str | None
    profile: str | None
    profile_source: str | None
    cli_path: str | None
    cli_path_source: str | None
    refusal: str | None  # non-None => every consumer must refuse


def _resolve_registry_str(home: Path | str, setting_name: str) -> tuple[str | None, str]:
    """M-S (S-58): a thin, `cast`-only call-through to `settings.
    resolve_setting`, replacing the retired `_resolve_str_setting`
    (which hand-rolled the same env-then-config-then-default cascade
    `provider.bedrock.region`/`.profile`/`sdk.cli_path` now resolve
    through the registry instead, gaining an override rung and, for the
    two bedrock-scoped entries, `enabled_when` gating for free). Callers
    keep receiving `str | None` -- every entry this is used for has
    `kind="str"` and a `default=None`, so `resolve_setting`'s
    `SettingValue` is always one of those two types here."""
    value, source = settings.resolve_setting(home, settings.by_name(setting_name))
    return cast(str | None, value), source


_DOCTOR_POINTER = "then run `self-learn doctor invocation`"


def _cause1_message(surface: str) -> str:
    return (
        f'refused-config: provider=bedrock resolved no region — surface "{surface}", '
        f"backend \"sdk\"; set provider.bedrock.region or SELF_LEARN_BEDROCK_REGION, "
        f"{_DOCTOR_POINTER}"
    )


def _cause2_message(surface: str, model: str) -> str:
    key = MODEL_KEY_FOR_SURFACE[surface]
    selector = SELECTOR_FOR_SURFACE[surface]
    return (
        f"refused-config: provider=bedrock model {model!r} is an Anthropic alias, not a "
        f'Bedrock id — surface "{surface}", backend "sdk"; set provider.bedrock.models.{key} '
        f"or SELF_LEARN_{selector}_MODEL, {_DOCTOR_POINTER}"
    )


def _causes_for(region: str | None, model: str, surface: str) -> list[tuple[str, str]]:
    """`Rs-c`'s two causes, evaluated in fixed order. Callers gate this to
    `provider == "bedrock" and backend == "sdk"` — this helper itself does
    not re-check that gate, so it can be reused by both `resolve` (first
    cause only) and `preflight`'s `consistency` row (every firing cause)."""
    causes: list[tuple[str, str]] = []
    if region is None:
        causes.append(("bedrock-needs-region", _cause1_message(surface)))
    if BEDROCK_ALIAS_RE.match(model):
        causes.append(("bedrock-model-is-alias", _cause2_message(surface, model)))
    return causes


def resolve(home: Path | str, surface: str) -> ProviderResolution:
    """`Res-1`. Total: every field always has a value. `Rs-c`: refusals
    are evaluated ONLY when `provider == "bedrock"` and `backend ==
    "sdk"` — under every other combination `refusal` is unconditionally
    `None`. `resolve` carries the FIRST applicable cause; `preflight`
    reports all that fire.

    U-cleanup `MAJOR-5`: also gated on `backend_refused is None`. A
    `cli` pin folds `backend` to `"sdk"` byte-for-byte (`KNOWN_BACKENDS`
    has one member now), so without this a REFUSED surface would still
    get its Bedrock model/region checked for consistency and could set
    `refusal` from a model/region mismatch it will never actually reach
    -- the wrong cause reported for the right (refused) row."""
    provider, provider_source = _resolve_provider(home)
    backend, backend_source, backend_refused = resolve_backend_name(home, surface)
    region, region_source = _resolve_registry_str(home, "provider.bedrock.region")
    profile, profile_source = _resolve_registry_str(home, "provider.bedrock.profile")
    cli_path, cli_path_source = _resolve_registry_str(home, "sdk.cli_path")

    refusal: str | None = None
    if provider == "bedrock" and backend == "sdk" and backend_refused is None:
        model = model_for(surface, home=home)
        causes = _causes_for(region, model, surface)
        if causes:
            refusal = causes[0][1]

    return ProviderResolution(
        surface=surface,
        provider=provider,
        provider_source=provider_source,
        backend=backend,
        backend_source=backend_source,
        backend_refused=backend_refused,
        region=region,
        region_source=region_source,
        profile=profile,
        profile_source=profile_source,
        cli_path=cli_path,
        cli_path_source=cli_path_source,
        refusal=refusal,
    )


# ===================================================================== #
# `Mod-1` -- model_for, and delegation as construction (SS 3.6)
# ===================================================================== #

MODEL_KEY_FOR_SURFACE = {
    "worker": "worker",
    "worker-repair": "worker",
    "miner-reader": "miner",
    "analyst": "analyst",
}


def _models_setting_name(surface: str) -> str:
    key = MODEL_KEY_FOR_SURFACE[surface]
    return f"models.{key}"


def _bedrock_models_setting_name(surface: str) -> str:
    key = MODEL_KEY_FOR_SURFACE[surface]
    return f"provider.bedrock.models.{key}"


def model_for(surface: str, *, home: Path | str) -> str:
    """`Mod-1`/`Mod-2`/`Mod-3`, corrected by BLOCKER-1/BLOCKER-2 (S-58):
    `models.<surface>` (env-first, override -> env -> its OWN config
    leaf -> the surface's shipped default function, CALLED, never
    copied, so CLI-path identity holds by construction under
    `provider=anthropic`) resolves FIRST; if its own source starts with
    `override:` or `env:`, that value is FINAL -- the bedrock leg below
    is never consulted. Otherwise `provider.bedrock.models.<surface>`
    (active only under `provider=bedrock`, via `enabled_when`) is
    checked: if IT resolves to a real config value (its own source
    starts with `config:`, which can only happen when active and set),
    that value wins, preserving today's exact bedrock behaviour;
    otherwise the `models.<surface>` result already in hand is used.
    Not a flat five-rung sequence -- a two-call, source-label-
    discriminated composition (r2-m3's correction of a naive reading)."""
    value, source = settings.resolve_setting(home, settings.by_name(_models_setting_name(surface)))
    if source.startswith("override:") or source.startswith("env:"):
        return cast(str, value)

    bedrock_value, bedrock_source = settings.resolve_setting(
        home, settings.by_name(_bedrock_models_setting_name(surface))
    )
    if bedrock_source.startswith("config:"):
        return cast(str, bedrock_value)

    return cast(str, value)


def _model_source(surface: str, home: Path | str) -> str:
    """Reporting-only mirror of `model_for`'s rung logic — `model_for`'s
    signature returns just the id, so the doctor's `models` row needs a
    second, read-only function to name the rung that answered."""
    _, source = settings.resolve_setting(home, settings.by_name(_models_setting_name(surface)))
    if source.startswith("override:") or source.startswith("env:"):
        return source

    _, bedrock_source = settings.resolve_setting(
        home, settings.by_name(_bedrock_models_setting_name(surface))
    )
    if bedrock_source.startswith("config:"):
        return bedrock_source

    return source


# ===================================================================== #
# `Asm-1` -- environment assembly (SS 3.7)
# ===================================================================== #

#: `VB-1` -- the current, non-deprecated name (confirmed against live
#: docs at build time; see the build report). `ANTHROPIC_SMALL_FAST_MODEL`
#: is documented as deprecated.
SMALL_FAST_ENV_VAR = "ANTHROPIC_DEFAULT_HAIKU_MODEL"

BEDROCK_ENV_KEYS: tuple[str, ...] = (
    "CLAUDE_CODE_USE_BEDROCK",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    SMALL_FAST_ENV_VAR,
)


class ProviderRefused(RuntimeError):
    """`EV6` -- `str(exc)` IS `resolution.refusal`, verbatim."""


def session_env(resolution: ProviderResolution, *, home: Path | str) -> dict[str, str]:
    """`A-0` -- the total rule, in this order:

    1. `provider != "bedrock"` -> `{}` exactly.
    2. `backend != "sdk"` (or the backend selection was REFUSED,
       U-cleanup `MAJOR-5`: a `cli` pin now folds `backend` to `"sdk"`
       byte-for-byte, so `backend_refused is not None` is what actually
       distinguishes it) -> `{}` exactly (provider vars do not apply to
       a surface that will never reach a live sdk session — this is what
       makes the function total; before this row a `region=None`
       resolution reached the assembly branch below and produced a
       non-`str` value in a `dict[str, str]`).
    3. `refusal is not None` -> raises `ProviderRefused`.
    4. otherwise, the assembled dict.
    """
    if resolution.provider != "bedrock":
        return {}
    if resolution.backend != "sdk" or resolution.backend_refused is not None:
        return {}
    if resolution.refusal is not None:
        raise ProviderRefused(resolution.refusal)

    assert resolution.region is not None  # row 3 already refused bedrock-needs-region
    env: dict[str, str] = {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_REGION": resolution.region,
        "AWS_DEFAULT_REGION": resolution.region,
    }
    if resolution.profile is not None:
        env["AWS_PROFILE"] = resolution.profile

    small_fast, _ = settings.resolve_setting(home, settings.by_name("provider.bedrock.models.small_fast"))
    if small_fast:
        env[SMALL_FAST_ENV_VAR] = cast(str, small_fast)
    return env


# ===================================================================== #
# `Doc-1` -- the doctor (SS 3.8)
# ===================================================================== #

DOCTOR_ROWS = (
    "switches",
    "provider",
    "config",
    "sdk",
    "rollout",
    "consistency",
    "region",
    "credentials",
    "models",
    "env",
    "orphans",
    "serve",
    "ui",
)
VERDICTS = ("PASS", "WARN", "FAIL", "SKIP", "INFO")


@dataclass(frozen=True)
class Row:
    name: str  # a member of DOCTOR_ROWS
    verdict: str  # a member of VERDICTS
    detail: str
    surface: str | None = None  # set iff the row is per-surface (Doc-b)
    cause: str | None = None  # set iff the row is per-cause (Doc-b)


#: `Id-1` -- the one FAIL guard.
BEDROCK_ALIAS_RE = re.compile(r"^claude-")

#: `Id-1a` -- advisory hints (never FAIL). Confirmed against live docs at
#: build time (`VB-5`): the five cross-region inference-profile prefixes
#: are exactly `us-gov.`, `us.`, `eu.`, `apac.`, `global.`.
_BEDROCK_ARN_RE = re.compile(r"^arn:aws[a-z-]*:bedrock:")
_BEDROCK_PROFILE_RE = re.compile(r"^(us|eu|apac|us-gov|global)\.[a-z0-9-]+\.")
_BEDROCK_MODEL_RE = re.compile(r"^[a-z0-9-]+\.[a-z0-9-]+")


def _id_verdict(model: str) -> tuple[str, str]:
    if BEDROCK_ALIAS_RE.match(model):
        return "FAIL", "Anthropic alias, not a Bedrock id"
    if (
        _BEDROCK_ARN_RE.match(model)
        or _BEDROCK_PROFILE_RE.match(model)
        or _BEDROCK_MODEL_RE.match(model)
    ):
        return "PASS", "recognized Bedrock id shape"
    return "WARN", "unrecognized Bedrock id shape"


# --------------------------------------------------------- Cred-1


def _profile_section_present(path: Path, profile: str, *, config_style: bool) -> bool:
    """`NS2`/`M19` -- a BOOLEAN only: does a line equal to `[<profile>]`
    (or `[profile <profile>]` in the AWS config-file style) exist.
    Nothing after the closing bracket, and nothing else in the file, is
    examined, matched, stored or returned."""
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    header = f"[profile {profile}]" if config_style else f"[{profile}]"
    return any(line.strip() == header for line in text.splitlines())


def _sso_cache_count(path: Path) -> int:
    """Counted, never opened (`NS4`)."""
    if not path.is_dir():
        return 0
    try:
        return sum(1 for _ in path.glob("*.json"))
    except OSError:
        return 0


def _credential_mechanisms(home: Path | str, profile: str | None) -> list[str]:
    """`Cred-1` -- presence-only. No probe reads a credential VALUE; the
    profile-section probe (the one that touches a credential file's
    bytes) is bounded to a boolean (`_profile_section_present`)."""
    del home  # not needed: every path here comes from AWS_* env or ~/.aws
    found: list[str] = []
    if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_SECRET_ACCESS_KEY"):
        found.append("env-static")
    if os.environ.get("AWS_SESSION_TOKEN"):
        found.append("env-session")
    if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        found.append("env-bedrock-key")

    resolved_profile = profile or os.environ.get("AWS_PROFILE") or "default"
    creds_path = Path(
        os.environ.get("AWS_SHARED_CREDENTIALS_FILE") or (Path.home() / ".aws" / "credentials")
    )
    cfg_path = Path(os.environ.get("AWS_CONFIG_FILE") or (Path.home() / ".aws" / "config"))
    if creds_path.is_file() and cfg_path.is_file():
        if _profile_section_present(
            creds_path, resolved_profile, config_style=False
        ) or _profile_section_present(cfg_path, resolved_profile, config_style=True):
            found.append("profile-file")
    elif creds_path.is_file() and _profile_section_present(
        creds_path, resolved_profile, config_style=False
    ):
        found.append("profile-file")
    elif cfg_path.is_file() and _profile_section_present(
        cfg_path, resolved_profile, config_style=True
    ):
        found.append("profile-file")

    sso_cache = Path.home() / ".aws" / "sso" / "cache"
    if _sso_cache_count(sso_cache) > 0:
        found.append("sso-cache")

    if os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI") or os.environ.get(
        "AWS_CONTAINER_CREDENTIALS_FULL_URI"
    ):
        found.append("container")

    web_identity = os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")
    if web_identity and Path(web_identity).is_file():
        found.append("web-identity")

    return found


# --------------------------------------------------------- Doc-a: the sdk row


def _default_sdk_importer() -> Any:
    return importlib.import_module("claude_agent_sdk")


def _bundled_cli_version(sdk_module: Any) -> str:
    cli_version_ns = getattr(sdk_module, "_cli_version", None)
    if cli_version_ns is None:
        module_name = getattr(sdk_module, "__name__", "claude_agent_sdk")
        try:
            cli_version_ns = importlib.import_module(f"{module_name}._cli_version")
        except ImportError:
            return "?"
    return str(getattr(cli_version_ns, "__cli_version__", "?"))


def _resolve_sdk_cli_path() -> tuple[str | None, str]:
    """The CLI path `claude_agent_sdk` itself would invoke, absent a
    `SELF_LEARN_SDK_CLI_PATH` override: constructs the SDK's own
    transport and calls its own `_find_cli` (bundled binary first, then
    PATH and the SDK's hardcoded fallback locations) -- the SAME
    resolution a real SDK invocation performs. No subprocess is spawned
    here (`_find_cli` is pure filesystem/`shutil.which` checks); every
    failure leg -> `(None, reason)`, never a traceback. Gate r1 NIT
    (recorded, not changed): narrowing this to `_find_cli`'s own
    `CLINotFoundError` was considered and rejected -- a future SDK
    release that asserts or raises something else inside `_find_cli`
    would then surface as an uncaught traceback out of `doctor
    invocation`, exactly what this docstring promises never to happen,
    which is worse than folding it into a SKIP row."""
    try:
        from claude_agent_sdk._internal.transport.subprocess_cli import (
            SubprocessCLITransport,
        )
        from claude_agent_sdk.types import ClaudeAgentOptions
    except ImportError:
        return None, "claude_agent_sdk transport not importable"
    try:
        transport = SubprocessCLITransport(prompt="", options=ClaudeAgentOptions())
        return transport._find_cli(), ""
    except Exception as exc:  # noqa: BLE001 - CLINotFoundError et al., never a traceback
        return None, f"sdk could not resolve a cli path ({exc})"


def _operative_cli_version(home: Path | str | None = None) -> tuple[str | None, str]:
    """`Doc-a`'s ONE permitted subprocess: `[<operative claude>,
    "--version"]`, argv byte-pinned to two elements, `timeout=10`, every
    failure leg -> SKIP (never FAIL, never a traceback).

    `B-5`: the OPERATIVE cli path is `sdk.cli_path` (the registry entry
    `SELF_LEARN_SDK_CLI_PATH` now resolves through, M-S minor-2: this
    used to read the env var directly, a SECOND, independent reader of
    the same var the registry ALSO governs -- `doctor invocation`'s own
    probe would otherwise report a version for a different binary than
    `ProviderResolution.cli_path` actually uses) if set, else whatever
    `_find_cli` itself would resolve (`_resolve_sdk_cli_path`) -- NOT
    whatever `claude` happens to be on PATH. That PATH lookup is a
    different, unrelated tool most of the time (this SDK ships its own
    bundled binary, found first by `_find_cli`), so comparing IT against
    the declared bundled-cli requirement produced false WARNs; see
    `_host_cli_context` below for where that PATH lookup now lives
    (context only, never compared).

    `home=None` (this function's own tests, and any caller with no
    ledger home in hand) falls back to a bare env-var read, matching
    this function's behaviour before the registry existed -- the
    registry's config rung has nothing to add without a real ledger
    home to read `config.yaml` from, and `settings.resolve_setting`
    itself is not `None`-home-safe."""
    if home is not None:
        override, _ = _resolve_registry_str(home, "sdk.cli_path")
    else:
        override = os.environ.get("SELF_LEARN_SDK_CLI_PATH")
    if override:
        cli_path: str | None = override
        skip_reason = ""
    else:
        cli_path, skip_reason = _resolve_sdk_cli_path()
    if not cli_path:
        return None, skip_reason or "sdk cli path not resolved"
    argv = [cli_path, "--version"]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return None, "resolved cli binary not found"
    except OSError as exc:
        return None, f"resolved cli --version failed ({exc})"
    except subprocess.TimeoutExpired:
        return None, "resolved cli --version timed out"
    if result.returncode != 0:
        return None, f"resolved cli --version exited {result.returncode}"
    tokens = (result.stdout or "").split()
    if not tokens:
        return None, "resolved cli --version produced no output"
    return tokens[0], ""


def _host_cli_context() -> str:
    """`B-5`: the `claude` on PATH is NEVER part of the operative pair --
    a labeled context line only (no subprocess: path only, never
    executed, never a WARN source)."""
    return shutil.which("claude") or "not found on PATH"


def _sdk_row(
    home: Path | str | None = None, *, importer: Callable[[], Any] = _default_sdk_importer
) -> Row:
    try:
        sdk_module = importer()
    except ImportError:
        return Row(name="sdk", verdict="SKIP", detail="claude_agent_sdk not importable")

    sdk_version = str(getattr(sdk_module, "__version__", "?"))
    bundled = _bundled_cli_version(sdk_module)
    resolved, skip_reason = _operative_cli_version(home)
    # Gate r1 NIT: this field carries a PATH now (`_host_cli_context`
    # returns `shutil.which("claude")` or a not-found label), not a
    # version string the way the old `host-cli=` name implied. Renamed
    # to `host-cli-path=` rather than restored to a version -- probing a
    # version would mean running `--version` on the host binary, a
    # second subprocess spawn this row deliberately never makes (B-5;
    # `test_dc10_no_network_no_extra_spawn`'s "ONE permitted spawn"
    # invariant).
    host_context = f"host-cli-path={_host_cli_context()} (context, not compared)"
    if resolved is None:
        return Row(
            name="sdk",
            verdict="SKIP",
            detail=(
                f"sdk={sdk_version} bundled-cli={bundled} — operative cli version not probed "
                f"({skip_reason}); {host_context}"
            ),
        )
    if resolved != bundled:
        return Row(
            name="sdk",
            verdict="WARN",
            detail=(
                f"sdk={sdk_version} bundled-cli={bundled} operative-cli={resolved} — versions "
                f"differ; {host_context}"
            ),
        )
    return Row(
        name="sdk",
        verdict="PASS",
        detail=(
            f"sdk={sdk_version} bundled-cli={bundled} operative-cli={resolved} — versions match; "
            f"{host_context}"
        ),
    )


# --------------------------------------------------------- Doc-e: orphans


def _serve_row() -> Row:
    """`Doc-g` / U-engine Phase 2 (spec Sec 5.6) -- the staleness alarm
    lives OUTSIDE the daemon: this row is what makes a dead `serve` LOUD
    even when nothing else is watching (`SUP2`/`SUP3`). Local imports of
    `serve`/`worker` (the pattern `_orphan_report_row` right below
    already uses for `invocation_sdk`) -- `provider.py` stays import-light
    at module load, and neither `serve` nor `worker` import `provider`,
    so there is no cycle either way.

    Four verdicts (`SUP2`): heartbeat fresh -> PASS naming the next job;
    heartbeat present but stale (older than the daemon's own tick
    interval) -> FAIL naming the age; no heartbeat and `serve` not
    configured -> SKIP (this machine does not use it); no heartbeat but
    `serve` IS configured -> FAIL. `SUP4`: when BOTH `self-learn-
    host.service` and `self-learn-miner.timer` are systemd-enabled, a
    PASS is downgraded to WARN naming the deliberate belt-and-braces poke
    configuration (Sec 5.7) -- never FAIL, because that pairing is
    supported, not broken."""
    from . import serve as serve_mod

    # `Doc-0`'s own contract: `preflight` "computes no verdict... and
    # PRINTS NOTHING" -- and, pinned by `test_ns5_doctor_writes_nothing`,
    # WRITES nothing either. `worker.cache_dir()` creates the cache
    # directory as a side effect (`mkdir(parents=True, exist_ok=True)`
    # plus a migration shim); `cache_dir_readonly()` resolves the SAME
    # path without ever touching the filesystem.
    cache_dir = serve_mod.cache_dir_readonly()
    both_enabled = serve_mod.is_enabled(
        "self-learn-host.service", "default.target"
    ) and serve_mod.is_enabled("self-learn-miner.timer", "timers.target")

    record = serve_mod.read_heartbeat(cache_dir)
    if record is None:
        if serve_mod.is_configured():
            # Gate r2 N-6': `read_heartbeat` returns `None` for TWO
            # different facts -- the file is genuinely absent, or it
            # exists but failed to parse (`OSError`/`ValueError`,
            # e.g. a write caught mid-flight before N-2's atomic
            # rename, or a corrupted file). The verdict is FAIL either
            # way, but the diagnosis must not claim "never seen" when
            # the file is sitting right there, unreadable.
            heartbeat_exists = serve_mod.heartbeat_path(cache_dir).is_file()
            detail = (
                "self-learn-host.service is linked but its heartbeat file "
                "exists and could not be parsed -- is `self-learn serve` "
                "writing a valid one?"
                if heartbeat_exists
                else (
                    "self-learn-host.service is linked but no heartbeat was "
                    "ever seen -- is `self-learn serve` running?"
                )
            )
            return Row(name="serve", verdict="FAIL", detail=detail)
        return Row(
            name="serve", verdict="SKIP", detail="serve is not configured on this machine"
        )

    age = serve_mod.heartbeat_age_secs(cache_dir)
    tick_secs = record.get("tick_secs")
    tick_secs = tick_secs if isinstance(tick_secs, (int, float)) and tick_secs > 0 else serve_mod.DEFAULT_TICK_SECS
    if age is None or age > tick_secs:
        age_detail = "unknown" if age is None else f"{age:.0f}s"
        return Row(
            name="serve",
            verdict="FAIL",
            detail=f"heartbeat is stale (age={age_detail}, tick={tick_secs:.0f}s) -- serve may have died",
        )

    next_job = record.get("next_job") or "idle"
    if both_enabled:
        return Row(
            name="serve",
            verdict="WARN",
            detail=(
                f"heartbeat fresh (age={age:.1f}s) -- next: {next_job}; "
                "self-learn-miner.timer is ALSO enabled -- deliberate "
                "belt-and-braces poke configuration (Sec 5.7), not a fault"
            ),
        )
    return Row(
        name="serve", verdict="PASS", detail=f"heartbeat fresh (age={age:.1f}s) -- next: {next_job}"
    )


def _orphan_report_row() -> Row:
    """`Doc-e` -- consumes an OPTIONAL hook U-sdk may export, and never
    acts on it. This build of U-sdk exports no such symbol (`R-6`), so
    this row SKIPs unconditionally today; a future U-sdk revision that
    exports `invocation_sdk.orphan_report` will be rendered here without
    a further change to this function."""
    try:
        module = importlib.import_module("self_learn.invocation_sdk")
    except ImportError:
        return Row(name="orphans", verdict="SKIP", detail="sdk backend package not importable")
    hook = getattr(module, "orphan_report", None)
    if hook is None or not callable(hook):
        return Row(
            name="orphans", verdict="SKIP", detail="no orphan report hook exported by the sdk backend"
        )
    try:
        report = hook()
    except Exception as exc:  # noqa: BLE001 - a broken hook must not crash the doctor
        return Row(name="orphans", verdict="SKIP", detail=f"orphan report hook raised: {exc}")
    return Row(name="orphans", verdict="INFO", detail=str(report))


def _ui_row() -> Row:
    """M-N -- `self-learn-ui.service`'s sibling to `_serve_row` above,
    minus the heartbeat legs: the UI service writes no heartbeat (10
    §1; U7), so this row can only report the unit's linked/enabled
    state, and says so plainly rather than implying a liveness check it
    cannot make. Local import of `serve` -- same reasoning as
    `_serve_row`: `provider.py` stays import-light at module load, and
    `serve` does not import `provider`, so there is no cycle either
    way.

    Three verdicts: not linked -> SKIP (this machine does not use it,
    same posture as `_serve_row`'s unconfigured leg); linked but not
    enabled -> WARN (a stopped/never-started convenience, not a fault);
    linked and enabled -> PASS."""
    from . import serve as serve_mod

    unit_name = "self-learn-ui.service"
    if not serve_mod.is_configured(unit_name):
        return Row(name="ui", verdict="SKIP", detail=f"{unit_name} is not linked on this machine")
    if serve_mod.is_enabled(unit_name, "default.target"):
        return Row(
            name="ui",
            verdict="PASS",
            detail=f"{unit_name} is linked and enabled — state only, it writes no heartbeat",
        )
    return Row(
        name="ui",
        verdict="WARN",
        detail=f"{unit_name} is linked but not enabled — state only, it writes no heartbeat",
    )


# --------------------------------------------------------- preflight


def preflight(home: Path | str) -> list[Row]:
    """`Doc-0` -- computes the COMPLETE list of rows and PRINTS NOTHING.
    The single source of every verdict this unit renders; `_cmd_doctor`
    is a thin printer over this function's return value alone."""
    resolutions = {surface: resolve(home, surface) for surface in SURFACES}
    # install-wide facts: identical across every surface's resolution.
    any_res = resolutions[SURFACES[0]]
    provider, provider_source = any_res.provider, any_res.provider_source
    region, region_source = any_res.region, any_res.region_source

    rows: list[Row] = []

    # switches — U-cleanup SEL6: a "cli" selection is reported as REFUSED,
    # never folded into an accepted "sdk" the way an unknown value is.
    switches_detail = "; ".join(
        f"{s}: backend=REFUSED (cli retired) ({resolutions[s].backend_source})"
        if resolutions[s].backend_refused is not None
        else f"{s}: backend={resolutions[s].backend} ({resolutions[s].backend_source})"
        for s in SURFACES
    )
    rows.append(Row(name="switches", verdict="INFO", detail=switches_detail))

    # provider
    rows.append(
        Row(name="provider", verdict="INFO", detail=f"provider={provider} ({provider_source})")
    )

    # config
    unknown_keys = config.provider_unknown_keys(home)
    if unknown_keys:
        rows.append(
            Row(
                name="config",
                verdict="WARN",
                detail="unknown provider config key(s): " + ", ".join(unknown_keys),
            )
        )
    else:
        rows.append(Row(name="config", verdict="PASS", detail="no unknown provider config keys"))

    # sdk
    sdk_row = _sdk_row(home)
    rows.append(sdk_row)

    # rollout
    rows.extend(_rollout_rows(resolutions, home))

    # consistency (per-cause, sdk surfaces only)
    for surface in SURFACES:
        res = resolutions[surface]
        if res.provider != "bedrock" or res.backend != "sdk" or res.backend_refused is not None:
            continue
        model = model_for(surface, home=home)
        for cause_name, message in _causes_for(res.region, model, surface):
            rows.append(
                Row(name="consistency", verdict="FAIL", detail=message, surface=surface, cause=cause_name)
            )

    # region
    if provider != "bedrock":
        rows.append(Row(name="region", verdict="SKIP", detail="provider=anthropic — region not applicable"))
    elif region is None:
        rows.append(
            Row(
                name="region",
                verdict="FAIL",
                detail="no region resolved — set provider.bedrock.region or SELF_LEARN_BEDROCK_REGION",
            )
        )
    else:
        rows.append(
            Row(
                name="region",
                verdict="PASS",
                detail=f"region={region} ({region_source}) — becomes AWS_REGION, AWS_DEFAULT_REGION",
            )
        )

    # credentials
    rows.append(_credentials_row(home, provider, resolutions))

    # models (per-surface, plus one small_fast line)
    rows.extend(_models_rows(resolutions, home))
    rows.append(_small_fast_row(home, provider))

    # env (per-surface)
    env_rows, env_details = _env_rows(resolutions, home)
    rows.extend(env_rows)

    # orphans
    rows.append(_orphan_report_row())

    # serve (U-engine Phase 2, Doc-g)
    rows.append(_serve_row())

    # ui (M-N) — self-learn-ui.service's linked/enabled state
    rows.append(_ui_row())

    return rows


def _rollout_rows(resolutions: dict[str, ProviderResolution], home: Path | str) -> list[Row]:
    """`Doc-f`. FAILs only the wholly-inert config; every mixed state
    renders per-surface INFO naming that surface's own check verdicts
    (`DC12`); the all-sdk state PASSes; `provider=anthropic` SKIPs.

    U-cleanup `MAJOR-5`: `backends[s]` is now `"sdk"` unconditionally
    (`_fold_backend` folds every non-`"sdk"` value, `KNOWN_BACKENDS`
    having shrunk to one member) -- a `cli` pin no longer shows up as a
    distinct backend NAME, only as `backend_refused is not None`. The
    four-state bucketing below is keyed on that field, not on
    `backends[s] == "sdk"` alone, so a refused surface still counts as
    "not really sdk" here exactly as it did before the retirement."""
    provider = resolutions[SURFACES[0]].provider
    if provider != "bedrock":
        return [
            Row(name="rollout", verdict="SKIP", detail="provider=anthropic — rollout state not applicable")
        ]
    backends = {s: resolutions[s].backend for s in SURFACES}
    sdk_surfaces = [
        s for s in SURFACES if backends[s] == "sdk" and resolutions[s].backend_refused is None
    ]
    if not sdk_surfaces:
        return [
            Row(
                name="rollout",
                verdict="FAIL",
                detail=(
                    # U-cleanup-B (§8.1, extending MAJOR-5's fix to a call
                    # site the original fix missed): `backends[s]` is now
                    # unconditionally "sdk" (KNOWN_BACKENDS collapse) --
                    # "every surface resolves backend=cli" can no longer
                    # be literally true. The correct SEL6-pattern spelling
                    # (matching the switches row) is REFUSED, not cli.
                    "provider=bedrock but every surface is REFUSED (cli retired) — the "
                    "provider configuration does nothing. Remove the cli pin from at "
                    "least one surface, or set provider=anthropic."
                ),
            )
        ]
    if len(sdk_surfaces) == len(SURFACES):
        return [
            Row(
                name="rollout",
                verdict="PASS",
                detail="all four surfaces resolve backend=sdk: " + ", ".join(SURFACES),
            )
        ]
    rows: list[Row] = []
    for s in SURFACES:
        if s not in sdk_surfaces:
            # U-cleanup-B (§8.1, same MAJOR-5 extension as above): a
            # non-sdk_surfaces membership here means `backend_refused is
            # not None` (refused), never a literal `backend == "cli"`.
            rows.append(
                Row(
                    name="rollout", verdict="INFO",
                    detail=f"{s}: backend=REFUSED (cli retired) — provider does not apply", surface=s,
                )
            )
            continue
        res = resolutions[s]
        region_v = "FAIL" if res.region is None else "PASS"
        model = model_for(s, home=home)
        models_v = _id_verdict(model)[0]
        try:
            env = session_env(res, home=home)
            env_v = "PASS" if env else "SKIP"
        except ProviderRefused:
            env_v = "FAIL"
        rows.append(
            Row(
                name="rollout",
                verdict="INFO",
                detail=(
                    f"{s}: backend=sdk provider=bedrock — region={region_v} models={models_v} "
                    f"env={env_v}"
                ),
                surface=s,
            )
        )
    return rows


def _credentials_row(
    home: Path | str, provider: str, resolutions: dict[str, ProviderResolution]
) -> Row:
    if provider != "bedrock":
        return Row(name="credentials", verdict="SKIP", detail="provider=anthropic — credentials not applicable")
    # U-cleanup MAJOR-5: a refused (cli-pinned) surface folds to
    # backend=="sdk" but never reaches a live sdk session -- exclude it
    # from the pool a profile is picked from, same as `_rollout_rows`.
    sdk_surfaces = [
        s for s in SURFACES if resolutions[s].backend == "sdk" and resolutions[s].backend_refused is None
    ]
    if not sdk_surfaces:
        return Row(
            name="credentials",
            verdict="SKIP",
            detail="no surface resolves backend=sdk — credentials not applicable",
        )
    profile = resolutions[sdk_surfaces[0]].profile
    mechanisms = _credential_mechanisms(home, profile)
    if mechanisms:
        return Row(name="credentials", verdict="PASS", detail="mechanism(s) found: " + ", ".join(mechanisms))
    return Row(
        name="credentials",
        verdict="WARN",
        detail="no mechanism found (IMDS not probed — see R-4)",
    )


def _models_rows(resolutions: dict[str, ProviderResolution], home: Path | str) -> list[Row]:
    rows: list[Row] = []
    for surface in SURFACES:
        res = resolutions[surface]
        model = model_for(surface, home=home)
        source = _model_source(surface, home)
        if res.provider != "bedrock":
            rows.append(
                Row(
                    name="models",
                    verdict="SKIP",
                    detail=(
                        f"{surface}: {model} ({source}) — provider=anthropic — Bedrock id shapes "
                        "not applicable"
                    ),
                    surface=surface,
                )
            )
            continue
        # U-cleanup MAJOR-5: `res.backend` alone can no longer distinguish
        # a refused (cli-pinned) surface from a live sdk one -- it folds
        # to "sdk" either way. `backend_refused` is what actually says
        # this surface's Bedrock model id will never be checked for real.
        if res.backend != "sdk" or res.backend_refused is not None:
            # U-cleanup-B (§8.1, MAJOR-5 extension, same class as the
            # `_rollout_rows` fix above): "backend=cli" can no longer be
            # a literal resolved value; corrected to the SEL6 pattern.
            rows.append(
                Row(
                    name="models",
                    verdict="INFO",
                    detail=(
                        f"{surface}: {model} ({source}) — backend=REFUSED (cli retired) — "
                        "Anthropic alias is correct here; provider does not apply"
                    ),
                    surface=surface,
                )
            )
            continue
        verdict, note = _id_verdict(model)
        rows.append(
            Row(
                name="models",
                verdict=verdict,
                detail=f"{surface}: {model} ({source}) — {note}",
                surface=surface,
            )
        )
    return rows


def _small_fast_row(home: Path | str, provider: str) -> Row:
    if provider != "bedrock":
        return Row(name="models", verdict="SKIP", detail="small_fast: provider=anthropic — not applicable")
    value, source = settings.resolve_setting(home, settings.by_name("provider.bedrock.models.small_fast"))
    if not value:
        return Row(
            name="models",
            verdict="WARN",
            detail=(
                "small_fast: unset — set provider.bedrock.models.small_fast (unset falls back to "
                "the default Sonnet model on Bedrock, not fatal — R-3)"
            ),
        )
    verdict, note = _id_verdict(cast(str, value))
    return Row(
        name="models", verdict=verdict, detail=f"small_fast: {value} ({source}) — {note}"
    )


def _env_rows(
    resolutions: dict[str, ProviderResolution], home: Path | str
) -> tuple[list[Row], dict[str, str]]:
    """`Doc-h`. Returns the rows AND a surface->detail map, so the
    handoff block (`Doc-d1`) can reuse the exact same strings rather than
    re-deriving them."""
    rows: list[Row] = []
    details: dict[str, str] = {}
    for surface in SURFACES:
        res = resolutions[surface]
        try:
            env = session_env(res, home=home)
        except ProviderRefused as exc:
            # `Doc-h`'s FAIL line IS the refusal string, verbatim (`Rs-d`
            # already embeds `surface "{surface}"` in it) — no prefix added.
            detail = str(exc)
            rows.append(Row(name="env", verdict="FAIL", detail=detail, surface=surface))
            details[surface] = detail
            continue
        if env:
            detail = f"{surface}: " + ", ".join(f"{k}=<redacted>" for k in sorted(env))
            rows.append(Row(name="env", verdict="PASS", detail=detail, surface=surface))
        elif res.provider == "bedrock":
            # U-cleanup-B (§8.1, MAJOR-5 extension): same "backend=cli"
            # -> "backend=REFUSED (cli retired)" correction as above.
            detail = f"{surface}: backend=REFUSED (cli retired) — provider does not apply"
            rows.append(Row(name="env", verdict="SKIP", detail=detail, surface=surface))
        else:
            # `A-0` row 1 (provider=anthropic): `DC7`/`A-f` -- an ambient
            # BEDROCK_ENV_KEYS member in the operator's shell reaches the
            # child on the anthropic leg too and `options.env={}` cannot
            # prevent it. Reported, never neutralized (`D-9`).
            ambient = sorted(k for k in BEDROCK_ENV_KEYS if os.environ.get(k))
            if ambient:
                detail = f"{surface}: ambient " + ", ".join(ambient) + " set (not neutralized — provider=anthropic)"
                rows.append(Row(name="env", verdict="WARN", detail=detail, surface=surface))
            else:
                detail = f"{surface}: provider=anthropic"
                rows.append(Row(name="env", verdict="PASS", detail=detail, surface=surface))
        details[surface] = detail
    return rows, details


# ===================================================================== #
# `Doc-d` -- the handoff block (built by `cli.py`'s `_cmd_doctor`, not by
# `preflight` itself -- `DC15`'s monkeypatch leg requires the handoff
# block to render independently of whatever `preflight` returned).
# ===================================================================== #


def _parse_sdk_prefix(detail: str) -> dict[str, str]:
    """The `sdk` row's `detail` always leads with `key=value` tokens
    (`sdk=`, `bundled-cli=`, `host-cli=`) before a `" — "` separator, or
    carries none of them at all (`"claude_agent_sdk not importable"`).
    Parsed rather than recomputed so the handoff block never triggers a
    SECOND `Doc-a` subprocess call (`DC10`'s exactly-once count)."""
    prefix = detail.split(" — ", 1)[0]
    fields: dict[str, str] = {}
    for token in prefix.split():
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key] = value
    return fields


def _handoff_sdk_fields(rows: list[Row]) -> tuple[str, str, str]:
    """`Doc-d0` -- `(sdk_version, cli_bundled, cli_host)`, with the
    documented placeholders whenever the `sdk` row is absent (e.g.
    `DC15`'s synthetic single-row `preflight`) or SKIPped."""
    sdk_rows = [r for r in rows if r.name == "sdk"]
    if not sdk_rows:
        return (
            "(not probed — sdk not installed)",
            "(not probed — sdk not installed)",
            "(not probed — sdk row skipped)",
        )
    fields = _parse_sdk_prefix(sdk_rows[0].detail)
    sdk_version = fields.get("sdk", "(not probed — sdk not installed)")
    bundled = fields.get("bundled-cli", "(not probed — sdk not installed)")
    host = fields.get("host-cli", "(not probed — sdk row skipped)")
    return sdk_version, bundled, host


def _handoff_fields(home: Path | str, rows: list[Row]) -> list[tuple[str, str]]:
    """`Doc-d`. The fixed field set, one value each, always defined
    (`Doc-d0`). `env-keys.<surface>` is read from the `env` rows already
    in `rows` when present (`Doc-d1` — byte-identical by construction,
    not by re-derivation); every other field is a fresh call to the same
    pure resolution functions the rows above were built from, which is
    safe to repeat (no subprocess involved) and produces identical
    values by construction."""
    resolutions = {s: resolve(home, s) for s in SURFACES}
    any_res = resolutions[SURFACES[0]]

    fields: list[tuple[str, str]] = [("provider", any_res.provider)]
    for s in SURFACES:
        fields.append((f"backend.{s}", resolutions[s].backend))
    fields.append(("region", any_res.region or "(unset)"))
    fields.append(("profile", any_res.profile or "(unset)"))

    mechanisms = (
        _credential_mechanisms(home, any_res.profile) if any_res.provider == "bedrock" else []
    )
    fields.append(("credential-mechanisms", ", ".join(mechanisms) if mechanisms else "(none found)"))

    for s in SURFACES:
        fields.append((f"model.{s}", model_for(s, home=home)))
    small_fast_value, _ = settings.resolve_setting(
        home, settings.by_name("provider.bedrock.models.small_fast")
    )
    fields.append(("model.small_fast", cast(str, small_fast_value) if small_fast_value else "(unset)"))

    env_by_surface = {r.surface: r.detail for r in rows if r.name == "env" and r.surface is not None}
    for s in SURFACES:
        if s in env_by_surface:
            fields.append((f"env-keys.{s}", env_by_surface[s]))
            continue
        try:
            env = session_env(resolutions[s], home=home)
        except ProviderRefused as exc:
            fields.append((f"env-keys.{s}", str(exc)))
            continue
        if env:
            fields.append((f"env-keys.{s}", ", ".join(f"{k}=<redacted>" for k in sorted(env))))
        else:
            # U-cleanup-B (§8.1, MAJOR-5 extension): same correction.
            detail = (
                "backend=REFUSED (cli retired) — provider does not apply"
                if resolutions[s].provider == "bedrock"
                else "provider=anthropic"
            )
            fields.append((f"env-keys.{s}", detail))

    sdk_version, cli_bundled, cli_host = _handoff_sdk_fields(rows)
    fields.append(("sdk-version", sdk_version))
    fields.append(("cli-version.bundled", cli_bundled))
    fields.append(("cli-version.host", cli_host))
    return fields
