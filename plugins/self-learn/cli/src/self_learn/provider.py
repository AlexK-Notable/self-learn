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
from typing import Any

from . import config
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
    """`Prov-1`/`Pv-a`/`Pv-b`. Three rungs, first hit wins. An empty value
    falls through silently. An unknown value warns once and resolves to
    `DEFAULT_PROVIDER`, WITHOUT falling through to the next rung."""
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

    setting = config.provider_setting(home, "name")
    if setting is not None:
        key, cfg_value = setting
        if cfg_value:
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
    """`Rs-a` -- a SECOND, INDEPENDENT transcription of U-seam's five-rung
    backend precedence chain (env selector, env general, config per-
    surface, config general, default `"sdk"`). Re-derived rather than
    read from `registry.backend_for` because that function returns a
    `Backend` OBJECT and RAISES `BackendUnavailable` for both the
    not-yet-built-`sdk` case and the retired-`cli` case (`B-3`) -- it
    cannot report a name -- and `registry.py` is outside this unit's file
    surface.

    `Rs-b` -- SILENT: never prints, for any input. `registry.py` already
    warns on the same inputs at the same moment; a second copy would
    double-print on every invocation.

    `Rs-a1` -- the empty-value rule is ASYMMETRIC by design: the env
    rungs fall through on an empty value (read directly, tested for
    truthiness below); the config rungs do NOT, because
    `config.invocation_backend` returns the FIRST PRESENT key regardless
    of its value -- an empty `backend_<surface>` terminates the chain
    before the coarser `backend` key is ever consulted. This function
    inherits that asymmetry by construction, by calling
    `config.invocation_backend` exactly once and trusting its answer.

    U-cleanup `MAJOR-5` -- the THIRD return element is `None`, or the
    retirement message when the raw value AT THE RUNG THAT ANSWERED was
    literally `"cli"`. Without this, `registry._resolve` refuses a `cli`
    selection while this independent transcription folded it into an
    accepted `"sdk"` -- a retired selection reported as honoured, which is
    exactly the defect `SEL6`/`SEL7` exist to catch. A source string is
    for provenance and is not overloaded to carry this (ruled, §8.2): the
    refusal gets its own element so `SEL6`'s doctor row and `SEL7`'s
    registry/provider agreement can both read it directly."""
    selector = SELECTOR_FOR_SURFACE.get(surface, surface)

    selector_var = f"SELF_LEARN_BACKEND_{selector}"
    value = os.environ.get(selector_var)
    if value:
        return _fold_backend(value), f"env:{selector_var}", _refused_backend(value)

    value = os.environ.get("SELF_LEARN_BACKEND")
    if value:
        return _fold_backend(value), "env:SELF_LEARN_BACKEND", _refused_backend(value)

    result = config.invocation_backend(home, surface)
    if result is not None:
        key, cfg_value = result
        if cfg_value:
            return _fold_backend(cfg_value), f"config:{key}", _refused_backend(cfg_value)

    return DEFAULT_BACKEND_FOR_SURFACE.get(surface, "sdk"), "default", None


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


def _resolve_str_setting(
    home: Path | str, env_var: str, config_key: str | None
) -> tuple[str | None, str]:
    """Two rungs, matching `Prov-1`'s discipline: env, then (optionally) a
    `PROVIDER_KEYS` config leaf, then the built-in default `None`. An
    empty value at either rung is "no answer" and falls through, same as
    `Pv-a`."""
    value = os.environ.get(env_var)
    if value:
        return value, f"env:{env_var}"
    if config_key is not None:
        setting = config.provider_setting(home, config_key)
        if setting is not None:
            key, cfg_value = setting
            if cfg_value:
                return cfg_value, f"config:provider.{key}"
    return None, "default"


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
    region, region_source = _resolve_str_setting(home, "SELF_LEARN_BEDROCK_REGION", "bedrock.region")
    profile, profile_source = _resolve_str_setting(
        home, "SELF_LEARN_BEDROCK_PROFILE", "bedrock.profile"
    )
    cli_path, cli_path_source = _resolve_str_setting(home, "SELF_LEARN_SDK_CLI_PATH", None)

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


def model_for(surface: str, *, home: Path | str) -> str:
    """`Mod-1`/`Mod-2`/`Mod-3`. Three rungs, first hit wins: the per-
    surface env var (verbatim, under either provider); the bedrock-only
    config leaf; the surface's shipped default function, CALLED (never
    copied) so CLI-path identity holds by construction under
    `provider=anthropic`."""
    selector = SELECTOR_FOR_SURFACE[surface]
    env_var = f"SELF_LEARN_{selector}_MODEL"
    value = os.environ.get(env_var)
    if value:
        return value

    provider, _ = _resolve_provider(home)
    if provider == "bedrock":
        key = MODEL_KEY_FOR_SURFACE[surface]
        setting = config.provider_setting(home, f"bedrock.models.{key}")
        if setting is not None:
            _, cfg_value = setting
            if cfg_value:
                return cfg_value

    # `P-b` -- deferred: importing `worker`/`miner`/`analyst` at module
    # scope would close a cycle (`B-1`). This import lives HERE, inside
    # this function's body, and nowhere else in this module.
    from . import analyst, miner, worker

    if surface in ("worker", "worker-repair"):
        return worker.worker_model()
    if surface == "miner-reader":
        return miner.miner_model()
    if surface == "analyst":
        return analyst._model()
    raise ValueError(f"model_for: unknown surface {surface!r}")


def _model_source(surface: str, home: Path | str) -> str:
    """Reporting-only mirror of `model_for`'s rung logic — `model_for`'s
    signature returns just the id, so the doctor's `models` row needs a
    second, read-only function to name the rung that answered."""
    selector = SELECTOR_FOR_SURFACE[surface]
    env_var = f"SELF_LEARN_{selector}_MODEL"
    if os.environ.get(env_var):
        return f"env:{env_var}"
    provider, _ = _resolve_provider(home)
    if provider == "bedrock":
        key = MODEL_KEY_FOR_SURFACE[surface]
        setting = config.provider_setting(home, f"bedrock.models.{key}")
        if setting is not None:
            cfg_key, cfg_value = setting
            if cfg_value:
                return f"config:provider.{cfg_key}"
    return "default"


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

    small_fast = config.provider_setting(home, "bedrock.models.small_fast")
    if small_fast is not None:
        _, value = small_fast
        if value:
            env[SMALL_FAST_ENV_VAR] = value
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


def _host_cli_version() -> tuple[str | None, str]:
    """`Doc-a`'s ONE permitted subprocess: `[<resolved claude>,
    "--version"]`, argv byte-pinned to two elements, `timeout=10`, every
    failure leg -> SKIP (never FAIL, never a traceback)."""
    cli_path = os.environ.get("SELF_LEARN_SDK_CLI_PATH") or shutil.which("claude")
    if not cli_path:
        return None, "claude not found on PATH"
    argv = [cli_path, "--version"]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return None, "claude binary not found"
    except OSError as exc:
        return None, f"claude --version failed ({exc})"
    except subprocess.TimeoutExpired:
        return None, "claude --version timed out"
    if result.returncode != 0:
        return None, f"claude --version exited {result.returncode}"
    tokens = (result.stdout or "").split()
    if not tokens:
        return None, "claude --version produced no output"
    return tokens[0], ""


def _sdk_row(*, importer: Callable[[], Any] = _default_sdk_importer) -> Row:
    try:
        sdk_module = importer()
    except ImportError:
        return Row(name="sdk", verdict="SKIP", detail="claude_agent_sdk not importable")

    sdk_version = str(getattr(sdk_module, "__version__", "?"))
    bundled = _bundled_cli_version(sdk_module)
    host, skip_reason = _host_cli_version()
    if host is None:
        return Row(
            name="sdk",
            verdict="SKIP",
            detail=(
                f"sdk={sdk_version} bundled-cli={bundled} — host cli version not probed "
                f"({skip_reason})"
            ),
        )
    if host != bundled:
        return Row(
            name="sdk",
            verdict="WARN",
            detail=f"sdk={sdk_version} bundled-cli={bundled} host-cli={host} — versions differ",
        )
    return Row(
        name="sdk",
        verdict="PASS",
        detail=f"sdk={sdk_version} bundled-cli={bundled} host-cli={host} — versions match",
    )


# --------------------------------------------------------- Doc-e: orphans


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
    sdk_row = _sdk_row()
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
    setting = config.provider_setting(home, "bedrock.models.small_fast")
    if setting is None or not setting[1]:
        return Row(
            name="models",
            verdict="WARN",
            detail=(
                "small_fast: unset — set provider.bedrock.models.small_fast (unset falls back to "
                "the default Sonnet model on Bedrock, not fatal — R-3)"
            ),
        )
    key, value = setting
    verdict, note = _id_verdict(value)
    return Row(
        name="models", verdict=verdict, detail=f"small_fast: {value} (config:provider.{key}) — {note}"
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
    small_fast_setting = config.provider_setting(home, "bedrock.models.small_fast")
    fields.append(("model.small_fast", small_fast_setting[1] if small_fast_setting else "(unset)"))

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
