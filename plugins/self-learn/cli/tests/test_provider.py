"""U-bedrock — the provider surface: `PR`, `BK`, `MD`, `EV`, `NS`, `RT`,
`IN`, `HY` criteria (see `docs/specs/self-learn/drafts/
u-bedrock-provider-spec.md`). `DC` criteria (the doctor) live in
`test_doctor_invocation.py`.

Fixtures never carry a real Bedrock model id, a real AWS account id, or
anything credential-shaped (`D-6`, `SEC-1`): placeholders are
`us.anthropic.claude-example-v0:0` / `us.anthropic.example-model-v0:0`,
account `000000000000`, profile `sandbox-profile`, credential value
`not-a-real-key-DO-NOT-USE`.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import os
import re
import textwrap
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeSDKClient

from self_learn import analyst, config, miner, provider, worker
from self_learn.invocation import contract as invocation_contract
from self_learn.invocation import registry as invocation_registry
from self_learn.invocation_sdk import backend as sdk_backend_mod
from self_learn.records import Record

# `IN`/`RT3`-`RT5` drive a REAL `SdkBackend` (transport faked) and a REAL
# `teach --route` (analyst leg) — resolved BY NAME from the U-sdk and
# doc-13 test modules that already build this machinery, matching the
# established cross-file fixture-import convention in this suite (e.g.
# `test_invocation_sdk.py`'s own `from test_worker import (...)`).
from test_invocation_sdk import (  # noqa: F401 -- fixtures/helpers resolved by name
    FAKE_CLI,
    _run as _sdk_run,
    _spec as _sdk_spec,
    sdk_cli_path,
)
from test_route_cli import TEACH_ARGS, env, sole  # noqa: F401 -- fixtures resolved by name

# ===================================================================== #
# Shared helpers
# ===================================================================== #

_PROVIDER_ENV_VARS = (
    "SELF_LEARN_PROVIDER",
    "SELF_LEARN_BEDROCK_REGION",
    "SELF_LEARN_BEDROCK_PROFILE",
    "SELF_LEARN_SDK_CLI_PATH",
    "SELF_LEARN_WORKER_MODEL",
    "SELF_LEARN_MINER_MODEL",
    "SELF_LEARN_ANALYST_MODEL",
    "SELF_LEARN_BACKEND",
    "SELF_LEARN_BACKEND_WORKER",
    "SELF_LEARN_BACKEND_MINER",
    "SELF_LEARN_BACKEND_ANALYST",
)


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _write_yaml(home: Path, text: str) -> None:
    (home / "config.yaml").write_text(textwrap.dedent(text), encoding="utf-8")


def _write_provider_yaml(home: Path, *, name: str | None = None, bedrock: dict | None = None) -> None:
    lines = ["provider:"]
    if name is not None:
        lines.append(f'  name: "{name}"')
    if bedrock:
        lines.append("  bedrock:")
        region = bedrock.get("region")
        profile = bedrock.get("profile")
        if region is not None:
            lines.append(f"    region: {region}")
        if profile is not None:
            lines.append(f"    profile: {profile}")
        models = bedrock.get("models")
        if models:
            lines.append("    models:")
            for key, value in models.items():
                lines.append(f"      {key}: {value}")
    (home / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


ALIAS = "claude-sonnet-5"
BEDROCK_ID = "us.anthropic.claude-example-v0:0"
BEDROCK_ID_2 = "us.anthropic.example-model-v0:0"
BEDROCK_ARN = "arn:aws:bedrock:us-east-1:000000000000:inference-profile/example-profile"
SANDBOX_PROFILE = "sandbox-profile"
FAKE_SECRET = "not-a-real-key-DO-NOT-USE"


def _sdk_resolution(
    home: Path,
    surface: str = "analyst",
    *,
    region: str = "us-east-1",
    model_env: str | None = None,
) -> provider.ProviderResolution:
    """A genuinely non-refusing `provider=bedrock, backend=sdk` resolution."""
    key = provider.MODEL_KEY_FOR_SURFACE[surface]
    _write_provider_yaml(
        home,
        name="bedrock",
        bedrock={"region": region, "models": {key: model_env or BEDROCK_ID}},
    )
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        return provider.resolve(home, surface)
    finally:
        del os.environ["SELF_LEARN_BACKEND"]


# ===================================================================== #
# SU — the suite and the bounded edits (`SU1`/`SU2`/`SU5` are instrument
# criteria, verified via the build report's commands, not pytest — only
# `SU3` needs a direct assertion here; `SU4` is covered by
# `test_selftest.py`'s own two byte-pinned-count tests passing.)
# ===================================================================== #


def test_su3_cmd_doctor_registered_in_the_held_lock_census():
    import test_lock_invariant as tli

    # 1: the command really is a _cmd_* dispatch surface
    assert "_cmd_doctor" in tli._cmd_functions()

    # 2: really parametrized, with a real argv rather than a None exemption
    assert "_cmd_doctor" in tli._ARGV_FOR
    assert tli._ARGV_FOR["_cmd_doctor"] == [["doctor", "invocation"]]

    # 3: TestEveryCommandSurvivesAHeldLock actually drives that argv --
    # confirmed by construction: _cases() builds its parametrize list from
    # _cmd_functions() x _ARGV_FOR, so (1) and (2) together guarantee
    # "_cmd_doctor:doctor invocation" is one of its collected cases.
    case_ids = {p.id for p in tli._cases()}
    assert "_cmd_doctor:doctor invocation" in case_ids


# ===================================================================== #
# PR — provider resolution and the config reader
# ===================================================================== #


def test_pr1_config_module_exports(tmp_path):
    """M-S (S-58, requirement 7): `config.provider_setting` is DELETED
    (every former call site now resolves through `settings.
    resolve_setting`/`config.settings_leaf` directly) -- its malformed-
    value coverage is superseded by `settings_leaf`'s own generic tests
    in `test_settings.py` (`test_malformed_config_*`), so nothing here
    re-derives it. `config.override_env_var` (M-S, minor-1's shared
    hyphen-aware helper) is the one new export."""
    assert not hasattr(config, "provider_setting")
    assert config.__all__ == [
        "CONFIG_BASENAME",
        "PROVIDER_KEYS",
        # U-settings Phase 2: the settings PAGE's write path -- round-trip
        # load/dump + the two generic, section-agnostic mutators (`set_leaf`/
        # `unset_leaf`) that `settings.config_set`/`config_unset` call into,
        # mirroring `settings_leaf`/`settings_unknown_keys`'s own read-side
        # generalization above rather than growing hosts.py-style special
        # casing per section.
        "ConfigWriteError",
        "config_path",
        "dump_editable",
        # U-hostmode MODE3: hosts.default_mode's fail-closed reader, added
        # alongside the other config.yaml accessors this module already
        # exports (kept out of the §2.10b census — this is the one-line
        # consequence of MODE3 existing at all).
        "effective_default_mode",
        "invocation_backend",
        "load_editable",
        "one_motion_enabled",
        # M-S (S-58): the shared override-var-name helper both
        # `settings.py` and `invocation/registry.py` call, so a
        # runtime-dispatch override and its registry-reporting
        # counterpart always compute the identical env-var name
        # without `invocation/registry.py` importing `settings.py`.
        "override_env_var",
        # MINOR-2 (code-gate review r1 2026-09-01): a validated,
        # NON-mutating "is section.key set" read against the SAME
        # round-trip write-path load `set_leaf`/`unset_leaf` use --
        # `settings_leaf` above is deliberately lenient (fail-closed-
        # silent on a malformed file); `present` raises `ConfigWriteError`
        # on that same malformed shape instead, so `config_unset`'s
        # pre-lock existence check refuses IDENTICALLY to `config_set`'s
        # own write attempt rather than reporting "already unset"
        # against a file `set` would refuse outright.
        "present",
        "provider_unknown_keys",
        "set_leaf",
        # U-settings Phase 1: the settings registry's two generic,
        # section-agnostic primitives (generalizing `provider_setting`/
        # `provider_unknown_keys`'s pattern rather than a second one —
        # `config.py`'s own module docstring, "U-settings Phase 1" note).
        "settings_leaf",
        "settings_unknown_keys",
        "unset_leaf",
    ]


def test_pr1b_override_env_var_folds_dots_and_hyphens(tmp_path):
    """minor-1 (code-gate review 2026-09-04): a bare `.`-only
    substitution would produce
    `SELF_LEARN_OVERRIDE_INVOCATION_BACKEND_WORKER-REPAIR`, not a legal
    POSIX env-var name -- `invocation.backend_worker-repair` embeds a
    hyphen verbatim, so this is not a hypothetical."""
    assert config.override_env_var("worker.autokick") == "SELF_LEARN_OVERRIDE_WORKER_AUTOKICK"
    assert (
        config.override_env_var("invocation.backend_worker-repair")
        == "SELF_LEARN_OVERRIDE_INVOCATION_BACKEND_WORKER_REPAIR"
    )


def test_pr2_provider_unknown_keys(tmp_path):
    assert config.provider_unknown_keys(tmp_path) == []  # missing file

    _write_yaml(
        tmp_path,
        """\
        provider:
          name: bedrock
          bedrock:
            regoin: us-east-1
            region: us-east-1
          bedrok:
            region: us-east-1
        """,
    )
    assert config.provider_unknown_keys(tmp_path) == ["bedrock.regoin", "bedrok.region"]

    _write_provider_yaml(
        tmp_path,
        name="bedrock",
        bedrock={"region": "us-east-1", "profile": SANDBOX_PROFILE, "models": {"worker": BEDROCK_ID}},
    )
    assert config.provider_unknown_keys(tmp_path) == []


def test_pr3_three_rung_chain_and_empty_falls_through(tmp_path, monkeypatch, capsys):
    # rung 3: built-in default
    assert provider.resolve(tmp_path, "worker").provider == "anthropic"

    # rung 2: config
    _write_provider_yaml(tmp_path, name="bedrock")
    assert provider.resolve(tmp_path, "worker").provider == "bedrock"

    # rung 1 shadows rung 2
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "anthropic")
    assert provider.resolve(tmp_path, "worker").provider == "anthropic"
    monkeypatch.delenv("SELF_LEARN_PROVIDER")

    # empty env value falls through silently to config
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "")
    res = provider.resolve(tmp_path, "worker")
    assert res.provider == "bedrock"
    assert capsys.readouterr().err == ""
    monkeypatch.delenv("SELF_LEARN_PROVIDER")

    # empty config value falls through silently to default
    _write_provider_yaml(tmp_path, name="")
    res = provider.resolve(tmp_path, "worker")
    assert res.provider == "anthropic"
    assert capsys.readouterr().err == ""


def test_pr4_unknown_provider_warns_and_stops_at_anthropic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "bogus")
    _write_provider_yaml(tmp_path, name="bedrock")
    res = provider.resolve(tmp_path, "worker")
    assert res.provider == "anthropic"  # does NOT fall through to the config rung
    err = capsys.readouterr().err
    assert err == 'self-learn: unknown provider \'bogus\' in SELF_LEARN_PROVIDER — using "anthropic"\n'
    monkeypatch.delenv("SELF_LEARN_PROVIDER")

    calls = []
    monkeypatch.setattr(config, "_warn", lambda message: calls.append(message))
    _write_provider_yaml(tmp_path, name="bogus")
    res = provider.resolve(tmp_path, "worker")
    assert res.provider == "anthropic"
    assert calls, "the config-flavored spelling must be emitted through config._warn"
    assert "provider.name must be one of anthropic, bedrock" in calls[0]
    assert "'bogus'" in calls[0]


def test_pr5_source_fields_name_the_answering_rung(tmp_path, monkeypatch):
    _write_provider_yaml(
        tmp_path,
        name="bedrock",
        bedrock={"region": "us-east-1", "profile": SANDBOX_PROFILE},
    )
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        res = provider.resolve(tmp_path, "worker")
    finally:
        del os.environ["SELF_LEARN_BACKEND"]
    assert res.provider_source == "config:provider.name"
    assert res.backend_source == "env:SELF_LEARN_BACKEND"
    assert res.region_source == "config:provider.bedrock.region"
    assert res.profile_source == "config:provider.bedrock.profile"
    assert res.cli_path_source == "default"

    monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_PROFILE", "other-profile")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/opt/claude")
    res2 = provider.resolve(tmp_path, "worker")
    assert res2.provider_source == "env:SELF_LEARN_PROVIDER"
    assert res2.region_source == "env:SELF_LEARN_BEDROCK_REGION"
    assert res2.profile_source == "env:SELF_LEARN_BEDROCK_PROFILE"
    assert res2.cli_path_source == "env:SELF_LEARN_SDK_CLI_PATH"

    monkeypatch.delenv("SELF_LEARN_PROVIDER")
    monkeypatch.delenv("SELF_LEARN_BEDROCK_REGION")
    monkeypatch.delenv("SELF_LEARN_BEDROCK_PROFILE")
    monkeypatch.delenv("SELF_LEARN_SDK_CLI_PATH")
    res3 = provider.resolve(tmp_path / "nowhere-else", "worker")
    # M-S (S-58): `provider.bedrock.region`/`.profile` are `enabled_when`
    # gated on `provider=="bedrock"` now -- under `provider=anthropic`
    # (the default, restored above), they resolve to their OWN default
    # with the `inactive` source label, never "default" (which would
    # mean "active, but nothing set at any rung").
    assert res3.region_source == "inactive (provider=anthropic)"
    assert res3.profile_source == "inactive (provider=anthropic)"


def test_pr6_bedrock_env_overrides_and_cli_path_not_in_session_env(tmp_path, monkeypatch):
    _write_provider_yaml(
        tmp_path,
        name="bedrock",
        bedrock={"region": "us-east-1", "profile": "cfg-profile", "models": {"analyst": BEDROCK_ID}},
    )
    monkeypatch.setenv("SELF_LEARN_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_PROFILE", "env-profile")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/opt/claude")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    res = provider.resolve(tmp_path, "analyst")
    assert res.region == "us-west-2"
    assert res.profile == "env-profile"
    assert res.cli_path == "/opt/claude"

    env = provider.session_env(res, home=tmp_path)
    assert "SELF_LEARN_SDK_CLI_PATH" not in env
    assert set(env) <= set(provider.BEDROCK_ENV_KEYS)


# ===================================================================== #
# BK — the re-derived backend name
# ===================================================================== #


def _backend_for_expectation(surface: str, home: Path):
    """U-cleanup: `CliBackend` is deleted and `KNOWN_BACKENDS` has one
    member now, so `registry.backend_for` either raises
    `BackendUnavailable` (the `sdk` extra missing, OR the selection was
    a retired `cli` pin -- `resolve_backend_name`'s fold already treats
    both as "sdk" intention) or returns a real `SdkBackend`. Either way
    the name is "sdk" -- there is no other backend left to name. Kept
    as a function (not a bare constant) so a genuinely UNEXPECTED
    exception from `backend_for` still propagates and fails the test
    loudly, matching the original's defensive shape."""
    try:
        invocation_registry.backend_for(surface, home=home)
    except invocation_contract.BackendUnavailable:
        return "sdk"
    return "sdk"


def _bk1_matrix(tmp_path, monkeypatch):
    cases = []
    for surface in invocation_contract.SURFACES:
        selector = invocation_contract.SELECTOR_FOR_SURFACE[surface]
        home = tmp_path / f"bk-{surface}"
        home.mkdir()

        monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "sdk")
        cases.append((home, surface))
        monkeypatch.delenv(f"SELF_LEARN_BACKEND_{selector}")

        monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
        cases.append((home, surface))
        monkeypatch.delenv("SELF_LEARN_BACKEND")

        (home / "config.yaml").write_text(
            f"invocation:\n  backend_{surface}: sdk\n", encoding="utf-8"
        )
        cases.append((home, surface))

        (home / "config.yaml").write_text("invocation:\n  backend: sdk\n", encoding="utf-8")
        cases.append((home, surface))

        (home / "config.yaml").unlink()
        cases.append((home, surface))  # default

    return cases


def test_bk1_agrees_with_registry_over_matrix(tmp_path, monkeypatch):
    cases = _bk1_matrix(tmp_path, monkeypatch)
    assert len(cases) >= 14
    for home, surface in cases:
        derived, _source, _refused = provider.resolve_backend_name(home, surface)
        expected = _backend_for_expectation(surface, home)
        assert derived == expected, (home, surface, derived, expected)

    # unknown value -- U-cleanup: unknown values now fold to "sdk" (was
    # "cli" pre-cleanup, when KNOWN_BACKENDS had two members and "cli"
    # was the safe fallback; SEL5's discriminator is the current rule).
    unk_home = tmp_path / "bk-unknown"
    unk_home.mkdir()
    monkeypatch.setenv("SELF_LEARN_BACKEND", "bogus")
    assert provider.resolve_backend_name(unk_home, "worker")[0] == "sdk"
    assert _backend_for_expectation("worker", unk_home) == "sdk"
    monkeypatch.delenv("SELF_LEARN_BACKEND")

    # empty value -- falls through to the default rung, which U-flip
    # flipped to "sdk" for "worker". NOT comparable to the `bogus` case
    # above: an unknown value folds to "cli" regardless of the default,
    # but an empty value falls THROUGH to the default rung instead.
    empty_home = tmp_path / "bk-empty"
    empty_home.mkdir()
    monkeypatch.setenv("SELF_LEARN_BACKEND", "")
    assert provider.resolve_backend_name(empty_home, "worker")[0] == "sdk"
    assert _backend_for_expectation("worker", empty_home) == "sdk"
    monkeypatch.delenv("SELF_LEARN_BACKEND")

    # Rs-a1's two mandated cells, plus the positive control (E11)
    shadow_home = tmp_path / "bk-shadow"
    shadow_home.mkdir()
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    assert provider.resolve_backend_name(shadow_home, "worker")[0] == "sdk"
    assert _backend_for_expectation("worker", shadow_home) == "sdk"
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER")
    monkeypatch.delenv("SELF_LEARN_BACKEND")

    # U-flip inverted this cell's coarse "backend:" value to "cli" (was
    # "sdk"): the default for "worker" is now "sdk" too, so leaving the
    # coarse value at "sdk" would make "chain terminated at the empty
    # per-surface key, fell to the default" and "chain leaked through to
    # the coarser key" indistinguishable -- both would resolve "sdk".
    # With "cli" here, a leak reads "cli" and the correct (terminated)
    # behavior still reads "sdk" (the default).
    cfg_shadow_home = tmp_path / "bk-cfg-shadow"
    cfg_shadow_home.mkdir()
    (cfg_shadow_home / "config.yaml").write_text(
        'invocation:\n  backend_worker: ""\n  backend: cli\n', encoding="utf-8"
    )
    assert provider.resolve_backend_name(cfg_shadow_home, "worker")[0] == "sdk"
    assert _backend_for_expectation("worker", cfg_shadow_home) == "sdk"

    positive_control_home = tmp_path / "bk-positive"
    positive_control_home.mkdir()
    (positive_control_home / "config.yaml").write_text(
        "invocation:\n  backend: sdk\n", encoding="utf-8"
    )
    assert provider.resolve_backend_name(positive_control_home, "worker")[0] == "sdk"
    assert _backend_for_expectation("worker", positive_control_home) == "sdk"


def test_bk1b_rs_a1_discriminates_by_the_full_tuple_not_just_name(tmp_path):
    """M-S (S-58, dispatch requirement 1): `test_bk1_agrees_with_
    registry_over_matrix`'s `cfg_shadow_home` cell above asserts only
    `[0] == "sdk"` -- and since U-cleanup folded `KNOWN_BACKENDS` down
    to one member, `_fold_backend("cli")` ALSO equals `"sdk"`, so that
    assertion alone can no longer tell "terminated at the default"
    apart from "leaked through to the coarser key and got folded" --
    both produce `name == "sdk"`. This test asserts the FULL 3-tuple
    for both of Rs-a1's cells, which DOES still discriminate them via
    `source`/`refused`:

    - empty per-surface key + present general "cli" -> terminates at
      the default WITHOUT ever consulting the general key: `source`
      is `"default"`, `refused` is `None` (the general "cli" value was
      never even read, let alone refused).
    - ABSENT per-surface key + present general "cli" -> falls through
      and consults the general key, which IS "cli": `source` is
      `"config:backend"`, `refused` names the retirement message --
      the positive control proving the chain CAN reach and refuse the
      general key when the per-surface key is genuinely absent (not
      just empty), so the case above is a real termination, not an
      accidental non-discovery."""
    terminated_home = tmp_path / "bk-rs-a1-terminated"
    terminated_home.mkdir()
    (terminated_home / "config.yaml").write_text(
        'invocation:\n  backend_worker: ""\n  backend: cli\n', encoding="utf-8"
    )
    assert provider.resolve_backend_name(terminated_home, "worker") == ("sdk", "default", None)

    leaked_home = tmp_path / "bk-rs-a1-leaked"
    leaked_home.mkdir()
    (leaked_home / "config.yaml").write_text("invocation:\n  backend: cli\n", encoding="utf-8")
    name, source, refused = provider.resolve_backend_name(leaked_home, "worker")
    assert name == "sdk"  # folded, same as the terminated case -- NOT the discriminator
    assert source == "config:backend"
    assert refused is not None and "cli" in refused


def test_bk2_selector_mapping_holds(tmp_path, monkeypatch):
    # U-cleanup-B (CL8, M-15 grep widening): `KNOWN_BACKENDS = ("sdk",)`
    # makes `_fold_backend` return `"sdk"` for EVERY input (§8.1) -- a
    # bare `[0] == "sdk"` assertion is therefore tautological now,
    # regardless of whether WORKER's pin was actually READ or the
    # resolution merely fell through to the surface's own default (which
    # is also `"sdk"`, U-flip). `source` (index 1) is what still
    # distinguishes "pin was read" (`env:SELF_LEARN_BACKEND_WORKER`) from
    # "fell through to default" (`"default"`) post-collapse.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    backend, source, refused = provider.resolve_backend_name(tmp_path, "worker-repair")
    assert backend == "sdk"
    assert source == "env:SELF_LEARN_BACKEND_WORKER"
    assert refused is None
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER")

    # U-flip: "worker-repair"'s own default is now "sdk", so a MINER-leak
    # stimulus of "sdk" would be tautological with the correct (scoped)
    # answer. Inverted to "cli" -- a leak would read "cli", the correct
    # (non-leaked) answer is "worker-repair"'s own default, "sdk".
    #
    # Same tautology as above applies to `backend` alone post-collapse: a
    # leaked "cli" pin and a correct fall-through to default both fold to
    # `backend == "sdk"`. `source`/`refused` are what still discriminate
    # them -- a leak would read `source == "env:SELF_LEARN_BACKEND_MINER"`
    # and `refused is not None` (CL8: this "cli" stimulus now asserts the
    # refusal it would trigger, were the leak real); the correct,
    # non-leaked answer is `source == "default"`, `refused is None`.
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    backend, source, refused = provider.resolve_backend_name(tmp_path, "worker-repair")
    assert backend == "sdk"
    assert source == "default", "MINER's pin leaked into worker-repair's own resolution"
    assert refused is None


def test_bk3_resolve_backend_name_never_warns(tmp_path, monkeypatch, capsys):
    cases = _bk1_matrix(tmp_path, monkeypatch)
    for home, surface in cases:
        provider.resolve_backend_name(home, surface)
    assert capsys.readouterr().err == ""

    unk_home = tmp_path / "bk3-unknown"
    unk_home.mkdir()
    monkeypatch.setenv("SELF_LEARN_BACKEND", "bogus")
    provider.resolve_backend_name(unk_home, "worker")
    assert capsys.readouterr().err == ""
    # the registry DOES warn on the same input
    invocation_registry.backend_for("worker", home=unk_home)
    assert "unknown invocation backend" in capsys.readouterr().err


def test_bk4_source_names_exact_config_key(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "invocation:\n  backend_worker: sdk\n  backend: cli\n", encoding="utf-8"
    )
    name, source, refused = provider.resolve_backend_name(tmp_path, "worker")
    assert name == "sdk"
    assert source == "config:backend_worker"
    assert refused is None

    home2 = tmp_path / "bk4-general"
    home2.mkdir()
    (home2 / "config.yaml").write_text("invocation:\n  backend: sdk\n", encoding="utf-8")
    name2, source2, refused2 = provider.resolve_backend_name(home2, "worker")
    assert name2 == "sdk"
    assert source2 == "config:backend"
    assert refused2 is None


# ===================================================================== #
# MD — model_for
# ===================================================================== #


def test_md1_model_for_delegates(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "worker_model", lambda: "SENTINEL-WORKER")
    monkeypatch.setattr(miner, "miner_model", lambda: "SENTINEL-MINER")
    monkeypatch.setattr(analyst, "_model", lambda: "SENTINEL-ANALYST")
    assert provider.model_for("worker", home=tmp_path) == "SENTINEL-WORKER"
    assert provider.model_for("worker-repair", home=tmp_path) == "SENTINEL-WORKER"
    assert provider.model_for("miner-reader", home=tmp_path) == "SENTINEL-MINER"
    assert provider.model_for("analyst", home=tmp_path) == "SENTINEL-ANALYST"


def test_md2_env_wins_verbatim_under_both_providers(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_WORKER_MODEL", ALIAS)
    assert provider.model_for("worker", home=tmp_path) == ALIAS
    _write_provider_yaml(tmp_path, name="bedrock")
    assert provider.model_for("worker", home=tmp_path) == ALIAS


def test_md3_bedrock_config_rung_shadowed_by_env(tmp_path, monkeypatch):
    _write_provider_yaml(
        tmp_path,
        name="bedrock",
        bedrock={"models": {"worker": BEDROCK_ID, "miner": BEDROCK_ID_2, "analyst": BEDROCK_ARN}},
    )
    assert provider.model_for("worker", home=tmp_path) == BEDROCK_ID
    assert provider.model_for("miner-reader", home=tmp_path) == BEDROCK_ID_2
    assert provider.model_for("analyst", home=tmp_path) == BEDROCK_ARN

    monkeypatch.setenv("SELF_LEARN_WORKER_MODEL", "env-wins")
    assert provider.model_for("worker", home=tmp_path) == "env-wins"


def test_md4_bedrock_unset_returns_delegate_alias(tmp_path):
    _write_provider_yaml(tmp_path, name="bedrock")
    result = provider.model_for("worker", home=tmp_path)
    assert result == worker.DEFAULT_WORKER_MODEL
    assert result is not None
    assert provider.BEDROCK_ALIAS_RE.match(result)


def test_md5_worker_repair_shares_worker_model_and_selector_identity(tmp_path, monkeypatch):
    for rung_setup in (
        lambda: monkeypatch.setenv("SELF_LEARN_WORKER_MODEL", "rung1"),
        lambda: _write_provider_yaml(tmp_path, name="bedrock", bedrock={"models": {"worker": BEDROCK_ID}}),
    ):
        monkeypatch.delenv("SELF_LEARN_WORKER_MODEL", raising=False)
        (tmp_path / "config.yaml").unlink(missing_ok=True)
        rung_setup()
        assert provider.model_for("worker-repair", home=tmp_path) == provider.model_for(
            "worker", home=tmp_path
        )
    monkeypatch.delenv("SELF_LEARN_WORKER_MODEL", raising=False)
    (tmp_path / "config.yaml").unlink(missing_ok=True)
    assert provider.model_for("worker-repair", home=tmp_path) == provider.model_for(
        "worker", home=tmp_path
    )

    assert provider.SELECTOR_FOR_SURFACE is invocation_contract.SELECTOR_FOR_SURFACE
    assert set(provider.MODEL_KEY_FOR_SURFACE) == set(invocation_contract.SURFACES)


def test_md6_no_claude_literal_in_provider_module_and_no_real_id_in_tests():
    provider_src = Path(provider.__file__).read_text(encoding="utf-8")
    # the pattern object's own source is the one permitted occurrence
    literal_re = re.compile(r'"claude-[^"]*"|\'claude-[^\']*\'')
    offenders = [
        m.group(0)
        for m in literal_re.finditer(provider_src)
        if "BEDROCK_ALIAS_RE" not in provider_src[max(0, m.start() - 40) : m.start()]
    ]
    assert not offenders, f"D-6: real-looking claude- literal(s) in provider.py: {offenders}"

    this_file = Path(__file__).read_text(encoding="utf-8")
    doctor_file = (Path(__file__).parent / "test_doctor_invocation.py").read_text(encoding="utf-8")
    # NOTE (code gate, 2026-08-19): the old `us\.anthropic\.` prefix
    # anchor missed any id-shaped literal that dropped that exact
    # regional prefix -- a bare vendor-dot-model id, or one carrying a
    # DIFFERENT region's prefix, are both documented Bedrock id shapes
    # (`VB-5`). Widen to any `[region.]anthropic.<rest>` literal, with a
    # negative lookbehind so it does not also match `res_anthropic.provider`-
    # style Python attribute access (an identifier, not an id literal).
    id_re = re.compile(r"(?<![A-Za-z0-9_])(?:[a-z]{2,6}\.)?anthropic\.[a-zA-Z0-9.:_-]+")
    for text, name in ((this_file, "test_provider.py"), (doctor_file, "test_doctor_invocation.py")):
        for m in id_re.finditer(text):
            literal = m.group(0)
            assert "example" in literal, f"D-6: non-placeholder Bedrock id {literal!r} in {name}"


# ===================================================================== #
# EV — environment assembly
# ===================================================================== #


def test_ev1_three_legs_disjoint_empty_and_populated(tmp_path, monkeypatch):
    anthropic_res = provider.resolve(tmp_path, "worker")
    assert anthropic_res.provider == "anthropic"
    anthropic_env = provider.session_env(anthropic_res, home=tmp_path)
    assert set(anthropic_env) & set(provider.BEDROCK_ENV_KEYS) == set()

    # bedrock + non-sdk: {} exactly, region None AND region set. U-flip
    # flipped "worker"'s default to sdk, so the "non-sdk" leg is now
    # CONSTRUCTED by an explicit pin rather than relying on the default.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    _write_provider_yaml(tmp_path, name="bedrock")
    cli_res_no_region = provider.resolve(tmp_path, "worker")
    # U-cleanup MAJOR-5: `.backend` folds to "sdk" unconditionally now
    # (KNOWN_BACKENDS has one member) -- `backend_refused` is what
    # actually distinguishes this cli-pinned, non-live resolution.
    assert cli_res_no_region.backend_refused is not None
    assert cli_res_no_region.region is None
    assert provider.session_env(cli_res_no_region, home=tmp_path) == {}

    _write_provider_yaml(tmp_path, name="bedrock", bedrock={"region": "us-east-1"})
    cli_res_with_region = provider.resolve(tmp_path, "worker")
    assert cli_res_with_region.backend_refused is not None
    assert cli_res_with_region.region == "us-east-1"
    assert provider.session_env(cli_res_with_region, home=tmp_path) == {}
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER")

    # bedrock + sdk: non-empty, the vacuity guard
    sdk_res = _sdk_resolution(tmp_path, "worker")
    sdk_env = provider.session_env(sdk_res, home=tmp_path)
    assert {"CLAUDE_CODE_USE_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION"} <= set(sdk_env)


def test_ev2_both_region_vars_same_value(tmp_path):
    res = _sdk_resolution(tmp_path, "worker", region="us-west-2")
    env = provider.session_env(res, home=tmp_path)
    assert env["AWS_REGION"] == "us-west-2"
    assert env["AWS_DEFAULT_REGION"] == "us-west-2"


def test_ev3_profile_and_small_fast_present_iff_resolved(tmp_path):
    res_no_profile = _sdk_resolution(tmp_path, "worker")
    env_no_profile = provider.session_env(res_no_profile, home=tmp_path)
    assert "AWS_PROFILE" not in env_no_profile
    assert provider.SMALL_FAST_ENV_VAR not in env_no_profile

    _write_provider_yaml(
        tmp_path,
        name="bedrock",
        bedrock={
            "region": "us-east-1",
            "profile": SANDBOX_PROFILE,
            "models": {"worker": BEDROCK_ID, "small_fast": BEDROCK_ID_2},
        },
    )
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        res_with = provider.resolve(tmp_path, "worker")
    finally:
        del os.environ["SELF_LEARN_BACKEND"]
    env_with = provider.session_env(res_with, home=tmp_path)
    assert env_with["AWS_PROFILE"] == SANDBOX_PROFILE
    assert env_with[provider.SMALL_FAST_ENV_VAR] == BEDROCK_ID_2

    src_dir = Path(provider.__file__).parent
    occurrences = 0
    for py_file in src_dir.rglob("*.py"):
        occurrences += py_file.read_text(encoding="utf-8").count(f'"{provider.SMALL_FAST_ENV_VAR}"')
    assert occurrences == 1, "SMALL_FAST_ENV_VAR literal must occur exactly once across src/self_learn/"


def test_ev4_key_set_subset_and_no_secret_shaped_keys(tmp_path):
    res = _sdk_resolution(tmp_path, "worker")
    env = provider.session_env(res, home=tmp_path)
    assert set(env) <= set(provider.BEDROCK_ENV_KEYS)
    forbidden = {
        "ANTHROPIC_MODEL",
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
    }
    assert not (set(env) & forbidden)


def test_ev5_os_environ_byte_identical(tmp_path, monkeypatch):
    from self_learn import cli as cli_mod

    monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_PROFILE", SANDBOX_PROFILE)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    monkeypatch.setenv("SELF_LEARN_WORKER_MODEL", BEDROCK_ID)
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path))

    # MAJOR-2: without this, an earlier test in file order (`test_ev3`)
    # that already called `session_env` with this SAME key/value set can
    # leave `BEDROCK_ENV_KEYS` sitting in the real `os.environ` -- the
    # before-snapshot would then already contain them, and a mutation
    # that aliases `os.environ` and writes into it (`os.environ.update`,
    # or `_sink = os.environ; _sink.update(env)`, which evades `HY2`'s
    # AST scan) would no-op against an unchanged `after` snapshot. Start
    # from a KNOWN-clean slate on every run, independent of test order or
    # the ambient shell.
    for key in provider.BEDROCK_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv(provider.SMALL_FAST_ENV_VAR, raising=False)

    before = dict(os.environ)
    res = provider.resolve(tmp_path, "worker")
    provider.model_for("worker", home=tmp_path)
    provider.session_env(res, home=tmp_path)
    provider.preflight(tmp_path)
    cli_mod.main(["doctor", "invocation"])
    after = dict(os.environ)
    assert before == after


def test_ev6_provider_refused_str_is_refusal(tmp_path):
    _write_provider_yaml(tmp_path, name="bedrock")
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        res = provider.resolve(tmp_path, "analyst")
    finally:
        del os.environ["SELF_LEARN_BACKEND"]
    assert res.refusal is not None
    with pytest.raises(provider.ProviderRefused) as exc_info:
        provider.session_env(res, home=tmp_path)
    assert str(exc_info.value) == res.refusal


# ===================================================================== #
# NS — no secret, ever
# ===================================================================== #


def test_ns1_provider_keys_exact():
    assert config.PROVIDER_KEYS == (
        "name",
        "bedrock.region",
        "bedrock.profile",
        "bedrock.models.worker",
        "bedrock.models.miner",
        "bedrock.models.analyst",
        "bedrock.models.small_fast",
    )


def test_ns2_profile_probe_boolean_only(tmp_path, monkeypatch):
    creds = tmp_path / "credentials"
    creds.write_text(
        f"[{SANDBOX_PROFILE}]\naws_secret_access_key = {FAKE_SECRET}\n", encoding="utf-8"
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-such-config"))
    mechanisms = provider._credential_mechanisms(tmp_path, SANDBOX_PROFILE)
    assert "profile-file" in mechanisms
    assert FAKE_SECRET not in repr(mechanisms)
    assert FAKE_SECRET not in "".join(mechanisms)

    # M19's re-aimed target: the probe itself must return a BOOLEAN, never
    # the matched section's contents (which would carry the secret line).
    result = provider._profile_section_present(creds, SANDBOX_PROFILE, config_style=False)
    assert result is True
    assert FAKE_SECRET not in repr(result)

    # MAJOR-4 (code gate, 2026-08-19): `_credential_mechanisms` has THREE
    # structurally identical profile-file branches -- both files present
    # (`NS3`), credentials-file only (the two legs above), and CONFIG-file
    # only. The third was reached by no fixture: an AWS config file
    # legitimately carries key material for config-defined profiles
    # (`aws_access_key_id`/`aws_secret_access_key` under `[profile ...]`),
    # so a future edit to that branch could leak with nothing failing.
    # Seed a config-file-ONLY scenario -- no credentials file at all -- so
    # this branch genuinely executes under the same per-value assertions.
    cfg_only = tmp_path / "aws-config-only"
    cfg_only.write_text(
        f"[profile {SANDBOX_PROFILE}]\naws_secret_access_key = {FAKE_SECRET}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-such-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg_only))
    mechanisms_cfg_only = provider._credential_mechanisms(tmp_path, SANDBOX_PROFILE)
    assert "profile-file" in mechanisms_cfg_only
    assert FAKE_SECRET not in repr(mechanisms_cfg_only)
    assert FAKE_SECRET not in "".join(mechanisms_cfg_only)

    result_cfg_only = provider._profile_section_present(cfg_only, SANDBOX_PROFILE, config_style=True)
    assert result_cfg_only is True
    assert FAKE_SECRET not in repr(result_cfg_only)


def test_ns3_doctor_output_never_leaks_seeded_credentials(tmp_path, monkeypatch, capsys):
    from self_learn import cli as cli_mod

    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path))
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    monkeypatch.setenv("SELF_LEARN_BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", FAKE_SECRET)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", FAKE_SECRET)
    monkeypatch.setenv("AWS_SESSION_TOKEN", FAKE_SECRET)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", FAKE_SECRET)

    creds = tmp_path / "credentials"
    creds.write_text(f"[{SANDBOX_PROFILE}]\naws_secret_access_key = {FAKE_SECRET}\n", encoding="utf-8")
    cfgfile = tmp_path / "aws-config"
    cfgfile.write_text(f"[profile {SANDBOX_PROFILE}]\nregion = us-east-1\n", encoding="utf-8")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfgfile))
    sso_cache = tmp_path / "sso-cache"
    sso_cache.mkdir()
    (sso_cache / "token.json").write_text(f'{{"secret": "{FAKE_SECRET}"}}', encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    web_identity = tmp_path / "web-identity-token"
    web_identity.write_text(FAKE_SECRET, encoding="utf-8")
    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", str(web_identity))
    monkeypatch.setenv("SELF_LEARN_BEDROCK_PROFILE", SANDBOX_PROFILE)
    monkeypatch.setenv(
        "SELF_LEARN_WORKER_MODEL", BEDROCK_ID
    )
    monkeypatch.setenv("SELF_LEARN_ANALYST_MODEL", BEDROCK_ID)
    monkeypatch.setenv("SELF_LEARN_MINER_MODEL", BEDROCK_ID)

    cli_mod.main(["doctor", "invocation"])
    out = capsys.readouterr().out
    assert FAKE_SECRET not in out
    # positive control: a doctor that printed nothing could not pass this
    assert SANDBOX_PROFILE in out
    assert "us-east-1" in out


def test_ns4_sso_cache_counted_never_opened(tmp_path, monkeypatch):
    """`NS4` names TWO entry points (`Path.read_text` / `open`) and BOTH
    credential paths (the sso-cache dir AND the profile-file dir) --
    covering only the sso-cache leg with only one of the two entry points
    left the profile-file leg's claim untested (code-gate NOTE,
    2026-08-19). Seed a real credentials file so `_credential_mechanisms`
    genuinely exercises both legs under this fixture."""
    sso_cache = tmp_path / ".aws" / "sso" / "cache"
    sso_cache.mkdir(parents=True)
    for i in range(3):
        (sso_cache / f"entry{i}.json").write_text(FAKE_SECRET, encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    creds = tmp_path / "credentials"
    creds.write_text(
        f"[{SANDBOX_PROFILE}]\naws_secret_access_key = {FAKE_SECRET}\n", encoding="utf-8"
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-such-config"))

    sso_opened_read_text: list[Path] = []
    any_builtin_open: list[str] = []
    real_read_text = Path.read_text
    real_open = open

    def _tracking_read_text(self, *a, **kw):
        if self.parent == sso_cache:
            sso_opened_read_text.append(self)
        return real_read_text(self, *a, **kw)

    def _tracking_open(file, *a, **kw):
        any_builtin_open.append(str(file))
        return real_open(file, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _tracking_read_text)
    monkeypatch.setattr("builtins.open", _tracking_open)
    mechanisms = provider._credential_mechanisms(tmp_path, SANDBOX_PROFILE)
    # both legs genuinely fired
    assert "sso-cache" in mechanisms
    assert "profile-file" in mechanisms
    # the sso-cache leg is counted (`.glob`), never opened -- by either entry point.
    assert sso_opened_read_text == []
    # NEITHER leg ever reaches the builtin `open` -- every presence probe
    # in this function goes through `Path`'s own methods
    # (`.is_file`/`.glob`/`.read_text`), never a raw `open()` call.
    assert any_builtin_open == []


def test_ns5_doctor_writes_nothing(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_dir))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))

    def _snapshot(root: Path) -> list[tuple[str, bytes | None]]:
        out = []
        for p in sorted(root.rglob("*")):
            out.append((str(p.relative_to(root)), p.read_bytes() if p.is_file() else None))
        return out

    before = (_snapshot(home_dir), _snapshot(cache_dir), _snapshot(runtime_dir))

    from self_learn import cli as cli_mod

    cli_mod.main(["doctor", "invocation"])

    after = (_snapshot(home_dir), _snapshot(cache_dir), _snapshot(runtime_dir))
    assert before == after


# ===================================================================== #
# RT — the runtime refusal path. RT1/RT2 are `resolve()`-level; RT3-RT5
# are driven against the REAL `SdkBackend` with the TRANSPORT faked
# (`In-b`) — never a `FakeBackend` double that constructs the refusal
# `Outcome` itself. See §3.9.
# ===================================================================== #

_RT_KEY = provider.MODEL_KEY_FOR_SURFACE["worker"]


def _refusing_bedrock_worker_config(home: Path) -> None:
    """Cause 1 (region missing) — `provider=bedrock`, a real Bedrock
    model id set, region omitted."""
    _write_provider_yaml(home, name="bedrock", bedrock={"models": {_RT_KEY: BEDROCK_ID}})


class _TransportSpy:
    """Records every `ClaudeSDKClient(options=...)` construction, so a
    test can assert the transport was never invoked (`RT3`)."""

    def __init__(self):
        self.constructed: list[object] = []
        self._real = ClaudeSDKClient

    def install(self, monkeypatch):
        outer = self

        class _Spy(outer._real):
            def __init__(self, *, options):
                outer.constructed.append(options)
                super().__init__(options=options)

        monkeypatch.setattr(sdk_backend_mod, "ClaudeSDKClient", _Spy)


def test_rt1_gating_and_both_causes(tmp_path):
    # cause 1: region missing
    _write_provider_yaml(tmp_path, name="bedrock", bedrock={"models": {"analyst": BEDROCK_ID}})
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        res = provider.resolve(tmp_path, "analyst")
    finally:
        del os.environ["SELF_LEARN_BACKEND"]
    assert res.refusal is not None
    assert "resolved no region" in res.refusal  # cause 1's shape

    # cause 2: model is alias, region present
    _write_provider_yaml(tmp_path, name="bedrock", bedrock={"region": "us-east-1"})
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        res2 = provider.resolve(tmp_path, "analyst")
    finally:
        del os.environ["SELF_LEARN_BACKEND"]
    assert res2.refusal is not None
    assert "Anthropic alias" in res2.refusal

    # refusal is None under anthropic at any backend, and under bedrock at
    # any non-sdk backend -- matrix over region x model
    for region_set in (True, False):
        for model_is_alias in (True, False):
            home = tmp_path / f"rt1-{region_set}-{model_is_alias}"
            home.mkdir()
            bedrock_cfg = {}
            if region_set:
                bedrock_cfg["region"] = "us-east-1"
            if not model_is_alias:
                bedrock_cfg["models"] = {"worker": BEDROCK_ID}
            _write_provider_yaml(home, name="bedrock", bedrock=bedrock_cfg or None)
            # U-flip flipped "worker"'s default to sdk; pin it back to
            # cli explicitly to construct the mixed-rollout state this
            # leg is about (no env, no config, used to be enough).
            os.environ["SELF_LEARN_BACKEND_WORKER"] = "cli"
            try:
                res_mixed = provider.resolve(home, "worker")
            finally:
                del os.environ["SELF_LEARN_BACKEND_WORKER"]
            assert res_mixed.backend_refused is not None
            assert res_mixed.refusal is None, (region_set, model_is_alias, res_mixed.refusal)

            anthropic_home = tmp_path / f"rt1-anthropic-{region_set}-{model_is_alias}"
            anthropic_home.mkdir()
            os.environ["SELF_LEARN_BACKEND"] = "sdk"
            try:
                res_anthropic = provider.resolve(anthropic_home, "worker")
            finally:
                del os.environ["SELF_LEARN_BACKEND"]
            assert res_anthropic.provider == "anthropic"
            assert res_anthropic.refusal is None


def test_rt2_refusal_pinned_tokens(tmp_path):
    _write_provider_yaml(tmp_path, name="bedrock", bedrock={"models": {"worker": BEDROCK_ID}})
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        res_region = provider.resolve(tmp_path, "worker")
    finally:
        del os.environ["SELF_LEARN_BACKEND"]
    assert res_region.refusal.startswith("refused-config: ")
    assert "self-learn doctor invocation" in res_region.refusal

    _write_provider_yaml(tmp_path, name="bedrock", bedrock={"region": "us-east-1"})
    os.environ["SELF_LEARN_BACKEND"] = "sdk"
    try:
        res_alias = provider.resolve(tmp_path, "worker")
    finally:
        del os.environ["SELF_LEARN_BACKEND"]
    assert res_alias.refusal.startswith("refused-config: ")
    assert "self-learn doctor invocation" in res_alias.refusal


def test_rt3_refusing_config_never_reaches_transport(tmp_path, sdk_cli_path, monkeypatch):
    spy = _TransportSpy()
    spy.install(monkeypatch)

    home = tmp_path / "rt3-home"
    home.mkdir()
    _refusing_bedrock_worker_config(home)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")

    outcome = _sdk_run(_sdk_spec("worker", home=home))

    assert outcome.ok is False
    assert outcome.rc is None
    assert outcome.stdout == ""
    assert outcome.failure == "unavailable"
    assert outcome.detail.startswith("refused-config: ")
    assert "self-learn doctor invocation" in outcome.detail
    # the leg that proves the refusal short-circuits: no `ClaudeSDKClient`
    # was ever constructed, so no session started and no process would
    # have been spawned.
    assert spy.constructed == []


def test_rt4_analyst_never_lost_through_teach_route(env, monkeypatch):
    """`RT4` -- driven through `analyst.analyze` via `teach --route`
    (`env`/`TEACH_ARGS` from `test_route_cli.py`, doc-13's own sandbox):
    the refusing configuration produces `AnalystError`, whose message
    (via `LOG_TEMPLATES["analyst"].unavailable`) carries the refusal
    text; `_route_now`'s `AnalystError` branch (`_capture_to_pending`,
    already covered generically by
    `test_teach_route_analyst_failure_captures_to_pending`) captures the
    composed record to `pending/`, exit code `4`
    (`teach.EXIT_ANALYST`), and the record file exists on disk after."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(env.home.parent / "rt4-xdg"))
    _refusing_bedrock_worker_config(env.home)  # cause 1 (region missing)
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")

    from self_learn import cli as cli_mod

    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        rc = cli_mod.main(TEACH_ARGS + ["--route"])
    err = err_buf.getvalue()

    assert rc == 4  # `teach.EXIT_ANALYST`
    assert env.resolved_files() == []
    record_path = sole(env.pending_files())
    assert record_path.exists()  # the record file exists on disk afterwards
    record = Record.from_path(record_path)
    assert record.status == "pending"
    assert "refused-config: " in err
    assert "self-learn doctor invocation" in err
    assert "captured to pending" in err


def test_rt5_worker_continues_and_miner_stray_file_survives(tmp_path, monkeypatch):
    # -- worker leg: `_invoke_claude` never raises; the run continues.
    worker_home = tmp_path / "rt5-worker-home"
    worker_home.mkdir()
    _refusing_bedrock_worker_config(worker_home)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    assert (
        worker._invoke_claude(
            "p", 20.0, worker_home, label=""
        )
        is None
    )
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER", raising=False)

    # -- miner-reader leg: early return precedes the stray sweep.
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "rt5-miner-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "rt5-miner-xdg"))
    miner_home = tmp_path / "rt5-miner-home"
    miner_home.mkdir()
    key = provider.MODEL_KEY_FOR_SURFACE["miner-reader"]
    _write_provider_yaml(miner_home, name="bedrock", bedrock={"models": {key: BEDROCK_ID}})
    spool = miner.spool_dir()
    stray = spool / "litter.txt"
    stray.write_text("litter", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    out = miner._invoke_reader(miner_home, "PROMPT")
    assert out is None
    assert stray.exists(), "unavailable: stray sweep ran despite an early return"


# ===================================================================== #
# IN — the U-sdk integration (`Int-1`/`In-d`). Driven against the REAL
# `SdkBackend` with the TRANSPORT faked (`In-b`) -- never a source grep
# for `session_env(`, never a double that constructs the refusal
# `Outcome` itself.
# ===================================================================== #


def test_in1_in2_in4_options_env_matches_recomputed_and_leak_disjoint(
    tmp_path, sdk_cli_path, monkeypatch
):
    spy = _TransportSpy()
    spy.install(monkeypatch)

    # `IN1` -- bedrock, backend=sdk, every switch set (region + profile +
    # model + small_fast).
    home = tmp_path / "in1-home"
    home.mkdir()
    key = provider.MODEL_KEY_FOR_SURFACE["worker"]
    _write_provider_yaml(
        home,
        name="bedrock",
        bedrock={
            "region": "us-east-1",
            "profile": SANDBOX_PROFILE,
            "models": {key: BEDROCK_ID, "small_fast": BEDROCK_ID_2},
        },
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    outcome = _sdk_run(_sdk_spec("worker", home=home))
    assert outcome.ok is True
    assert len(spy.constructed) == 1
    options = spy.constructed[0]
    # recomputed in the test, not captured from the same call (`IN1`).
    expected_env = provider.session_env(provider.resolve(home, "worker"), home=home)
    assert options.env == expected_env
    assert options.env  # `IN4`: exercised, not empty -- and `IN2`'s vacuity guard target

    # `IN2` -- anthropic (default posture): leak-disjoint from
    # `BEDROCK_ENV_KEYS`.
    spy.constructed.clear()
    monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)
    home2 = tmp_path / "in2-home"
    home2.mkdir()
    outcome2 = _sdk_run(_sdk_spec("worker", home=home2))
    assert outcome2.ok is True
    options2 = spy.constructed[0]
    assert set(options2.env) & set(provider.BEDROCK_ENV_KEYS) == set()


def test_in3_options_model_and_cli_path_match_provider(tmp_path, monkeypatch):
    home = tmp_path / "in3-home"
    home.mkdir()
    key = provider.MODEL_KEY_FOR_SURFACE["worker"]
    _write_provider_yaml(
        home, name="bedrock", bedrock={"region": "us-east-1", "models": {key: BEDROCK_ID}}
    )
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    kwargs = sdk_backend_mod.options_kwargs(_sdk_spec("worker", home=home))
    assert kwargs["model"] == provider.model_for("worker", home=home)
    assert kwargs["model"] == BEDROCK_ID  # the wiring is real, not coincidental

    monkeypatch.delenv("SELF_LEARN_SDK_CLI_PATH", raising=False)
    kwargs_unset = sdk_backend_mod.options_kwargs(
        _sdk_spec("worker", home=home)
    )
    assert kwargs_unset["cli_path"] is None  # untouched when the env var is not set

    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    kwargs_set = sdk_backend_mod.options_kwargs(_sdk_spec("worker", home=home))
    assert kwargs_set["cli_path"] == provider.resolve(home, "worker").cli_path


def test_in5_guarded_call_is_real_product_code_and_narrow(tmp_path, sdk_cli_path, monkeypatch):
    spy = _TransportSpy()
    spy.install(monkeypatch)

    home = tmp_path / "in5-home"
    home.mkdir()
    _refusing_bedrock_worker_config(home)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")

    outcome = _sdk_run(_sdk_spec("worker", home=home))
    assert outcome.failure == "unavailable"
    assert outcome.detail.startswith("refused-config: ")
    assert "self-learn doctor invocation" in outcome.detail
    assert isinstance(outcome.exc, provider.ProviderRefused)
    assert spy.constructed == []  # transport never invoked

    # Narrowness (`IN5`): a DIFFERENT exception raised from `session_env`
    # in the same position is NOT converted, and DOES propagate -- a bare
    # `except Exception` in `_drive` would fail this leg.
    def _boom(resolution, *, home):
        raise RuntimeError("not a ProviderRefused")

    monkeypatch.setattr(provider, "session_env", _boom)
    with pytest.raises(RuntimeError, match="not a ProviderRefused"):
        _sdk_run(_sdk_spec("worker", home=home))


# ===================================================================== #
# HY — hygiene
# ===================================================================== #


def _module_ast() -> ast.Module:
    src = Path(provider.__file__).read_text(encoding="utf-8")
    return ast.parse(src)


def test_hy1_deferred_delegation_imports():
    tree = _module_ast()
    # AST leg: no module-scope import of worker/miner/analyst
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            names = {a.name for a in node.names}
            assert not (names & {"worker", "miner", "analyst"}), "module-scope delegation import found"
        if isinstance(node, ast.Import):
            names = {a.name.split(".")[0] for a in node.names}
            assert not (names & {"worker", "miner", "analyst"})

    # M-S (S-58): `model_for` no longer imports worker/miner/analyst at
    # all -- it delegates entirely to `settings.resolve_setting` for
    # `models.<surface>`, whose own `default` is a deferred-import
    # WRAPPER (`settings._default_worker_model` et al.) that carries
    # `P-b`'s "deferred, never module-scope" discipline now. The AST
    # leg above (no module-scope import in THIS module) still holds;
    # this checks the discipline moved, not that it vanished.
    settings_src = (Path(provider.__file__).parent / "settings.py").read_text(encoding="utf-8")
    settings_tree = ast.parse(settings_src)
    for wrapper_name in ("_default_worker_model", "_default_miner_model", "_default_analyst_model"):
        wrapper_node = next(
            n for n in ast.walk(settings_tree) if isinstance(n, ast.FunctionDef) and n.name == wrapper_name
        )
        found = False
        for node in ast.walk(wrapper_node):
            if isinstance(node, ast.ImportFrom):
                names = {a.name for a in node.names}
                if names & {"worker", "miner", "analyst"}:
                    found = True
        assert found, f"settings.{wrapper_name} must import worker/miner/analyst, deferred"

    # live leg: three fresh-interpreter entry points
    import subprocess
    import sys

    src_root = str(Path(provider.__file__).parent.parent)
    live_branch_closed = None
    for first_module in ("self_learn.provider", "self_learn.invocation", "self_learn.worker"):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {first_module}"],
            cwd=src_root,
            env={**os.environ, "PYTHONPATH": src_root},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if first_module == "self_learn.provider":
            live_branch_closed = proc.returncode != 0
        assert proc.returncode == 0, (first_module, proc.stdout, proc.stderr)
    # Recorded per HY1 (code gate, second correction, 2026-08-19): this
    # unit's continuation DID wire into U-sdk's extension point --
    # `invocation_sdk/provider_env.py` and `invocation_sdk/backend.py`
    # both import `provider` at MODULE scope now, not deferred. The
    # gate's own test of the causal claim: with `M20` applied AND
    # `invocation/registry.py`'s lazy `invocation_sdk` import HOISTED to
    # module scope too, `import self_learn.provider` STILL succeeds. The
    # true mechanism: every cross-import here is `from package import
    # module`, which binds the partially-initialized module object from
    # `sys.modules`, and nothing is USED at import time -- no arrangement
    # of these three imports closes a start-up cycle. (The lazy import
    # itself lives inside `registry.py`'s `_resolve()`, line 41 -- not
    # `backend_for()`, which calls it -- but that placement is not what
    # keeps this leg green; the binding-without-using discipline is.)
    # `HY1`'s AST leg (above, in this same test) is the unconditional
    # killer regardless: it fails on a module-scope delegation import
    # whether or not this live leg would happen to survive one.
    assert live_branch_closed is False


def test_hy2_no_os_environ_mutation():
    tree = _module_ast()
    forbidden_attrs = {"putenv", "unsetenv"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "environ"
                and isinstance(node.ctx, ast.Store)
            ):
                pytest.fail("os.environ[...] = ... found in provider.py")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"update", "setdefault", "pop"} and isinstance(
                node.func.value, ast.Attribute
            ):
                if node.func.value.attr == "environ":
                    pytest.fail(f"os.environ.{node.func.attr}(...) found in provider.py")
            if node.func.attr in forbidden_attrs and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "os":
                    pytest.fail(f"os.{node.func.attr}(...) found in provider.py")

    from self_learn import selfcheck

    check_src = inspect.getsource(selfcheck._check_invocation)
    for token in ("os.environ[", "os.environ.update(", "os.environ.setdefault(", "os.putenv(", "os.unsetenv("):
        assert token not in check_src

    from self_learn import cli as cli_mod

    doctor_src = inspect.getsource(cli_mod._cmd_doctor)
    for token in ("os.environ[", "os.environ.update(", "os.environ.setdefault(", "os.putenv(", "os.unsetenv("):
        assert token not in doctor_src


def test_hy3_no_write_primitives():
    tree = _module_ast()
    src = Path(provider.__file__).read_text(encoding="utf-8")
    banned_calls = {
        "mkdir",
        "unlink",
        "touch",
        "rmdir",
        "rename",
        "replace",
        "rmtree",
        "copy",
        "copytree",
        "move",
        "remove",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in banned_calls, node.func.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    assert not any(c in kw.value.value for c in "wax+")
    assert ".write_text(" not in src
    assert ".write_bytes(" not in src
