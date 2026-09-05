"""M-S (S-58) code-gate fold r1 — witnesses the gate's own findings named:

BLOCKER-1 (empty ambient override splits the two faces), MAJOR-1/MAJOR-4
(the registry face used to report "default" where a general rung actually
answered; a shared six-rung cascade fixes both this module's paired
registry entries AND `invocation.registry.resolve_backend_raw`), and
MAJOR-2/MAJOR-3 (`direction`/`enabled_when` had no witness because the
prior test parameter lists derived FROM `settings.REGISTRY` itself, making
a mutation to either field untestable by census alone).

Kept as a SEPARATE file from `test_settings.py` (which already has its own
name-set fixtures derived from REGISTRY for other purposes) so these
witnesses' literal, hand-typed name sets are never confused with — or
silently fall back to — a REGISTRY-derived list.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import provider, settings
from self_learn.invocation import registry


def _write_config(home: Path, section: str, dotted_key: str, value: object) -> None:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.yaml"
    yaml = YAML(typ="safe")
    data: dict = {}
    if path.is_file():
        loaded = yaml.load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    node = data.setdefault(section, {})
    segments = dotted_key.split(".")
    for segment in segments[:-1]:
        node = node.setdefault(segment, {})
    node[segments[-1]] = value
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)


@pytest.fixture(autouse=True)
def _clear_registry_env(monkeypatch):
    """Same discipline as `test_settings.py`'s own fixture — every
    registry env var cleared before each test, so the SUITE's ambient
    env (conftest.py's worker-test defaults) cannot leak into these
    from-scratch resolutions."""
    for setting in settings.REGISTRY:
        if setting.env_var is not None:
            monkeypatch.delenv(setting.env_var, raising=False)


# ===================================================================== #
# BLOCKER-1 — an EMPTY ambient override reads as "no answer" on BOTH
# faces; a DELIBERATE `override(name, "")` still round-trips.
# ===================================================================== #


@pytest.mark.parametrize("state", ["absent", "empty", "unknown", "valid"])
def test_blocker1_provider_name_four_states_agree_across_both_faces(tmp_path, monkeypatch, state):
    home = tmp_path / "home"
    _write_config(home, "provider", "name", "bedrock")
    var = "SELF_LEARN_OVERRIDE_PROVIDER_NAME"
    if state == "absent":
        monkeypatch.delenv(var, raising=False)
    elif state == "empty":
        monkeypatch.setenv(var, "")
    elif state == "unknown":
        monkeypatch.setenv(var, "not-a-real-provider")
    else:
        monkeypatch.setenv(var, "bedrock")

    runtime = provider._resolve_provider(home)
    reg = settings.resolve_setting(home, settings.by_name("provider.name"))
    assert runtime == reg, f"state={state}: runtime={runtime!r} registry={reg!r}"

    if state in ("absent", "empty"):
        # BLOCKER-1's exact bug: an ambient empty override used to brick
        # a valid bedrock ledger to "anthropic" on the registry face
        # only. Both faces must still see the config rung's bedrock.
        assert runtime == ("bedrock", "config:provider.name")
    elif state == "unknown":
        assert runtime == (provider.DEFAULT_PROVIDER, "override:provider.name")
    else:
        assert runtime == ("bedrock", "override:provider.name")


@pytest.mark.parametrize("state", ["absent", "empty", "unknown", "valid"])
def test_blocker1_invocation_backend_worker_four_states_agree_across_both_faces(
    tmp_path, monkeypatch, state
):
    home = tmp_path / "home"
    _write_config(home, "invocation", "backend_worker", "sdk")
    var = "SELF_LEARN_OVERRIDE_INVOCATION_BACKEND_WORKER"
    if state == "absent":
        monkeypatch.delenv(var, raising=False)
    elif state == "empty":
        monkeypatch.setenv(var, "")
    elif state == "unknown":
        monkeypatch.setenv(var, "not-a-real-backend")
    else:
        monkeypatch.setenv(var, "sdk")

    runtime = registry.resolve_backend_raw(home, "worker")
    reg = settings.resolve_setting(home, settings.by_name("invocation.backend_worker"))

    if state == "unknown":
        # `resolve_backend_raw` is deliberately PURE -- it never clamps
        # an unknown value itself (that judgement, and its warning,
        # belong to `_resolve`/`backend_for`, downstream of this raw
        # tuple); `resolve_setting`'s `validate` DOES clamp inline. Both
        # faces still agree on WHICH RUNG answered and the raw string it
        # was given -- only the (deliberately later) clamp differs.
        assert runtime == ("not-a-real-backend", "override:invocation.backend_worker")
        assert reg == ("sdk", "override:invocation.backend_worker")
        from self_learn.invocation_sdk.backend import SdkBackend

        assert isinstance(registry.backend_for("worker", home=home), SdkBackend)
        return

    assert runtime == reg, f"state={state}: runtime={runtime!r} registry={reg!r}"
    if state in ("absent", "empty"):
        assert runtime == ("sdk", "config:invocation.backend_worker")


def test_blocker1_case_b_valid_bedrock_ledger_survives_empty_override_var(tmp_path, monkeypatch):
    """The gate's own case [B]: a valid, fully-configured bedrock ledger
    plus an AMBIENT empty override var must resolve bedrock end to end,
    with NO refusal, and `model_for('worker')` must be the bedrock id --
    not silently fall back to anthropic's default model."""
    home = tmp_path / "home"
    _write_config(home, "provider", "name", "bedrock")
    _write_config(home, "provider", "bedrock.region", "us-east-1")
    _write_config(home, "provider", "bedrock.models.worker", "BEDROCK-WORKER-ID")
    _write_config(home, "provider", "bedrock.models.small_fast", "BEDROCK-HAIKU-ID")
    monkeypatch.setenv("SELF_LEARN_OVERRIDE_PROVIDER_NAME", "")

    res = provider.resolve(home, "worker")
    assert res.provider == "bedrock"
    assert res.refusal is None
    assert provider.model_for("worker", home=home) == "BEDROCK-WORKER-ID"
    env = provider.session_env(res, home=home)
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert env["AWS_REGION"] == "us-east-1"


def test_blocker1_deliberate_empty_override_still_round_trips_for_a_paired_entry(tmp_path):
    """The OTHER half of BLOCKER-1's fix: a DELIBERATE `override(name,
    "")` (settings' own programmatic escape hatch, `config.
    OVERRIDE_EMPTY_MARKER`) must still be preserved -- distinct from the
    ambient-empty case above, which reads as no-answer instead."""
    home = tmp_path / "home"
    setting = settings.by_name("miner.transcripts_dir")
    with settings.override("miner.transcripts_dir", ""):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == ("", "override:miner.transcripts_dir")


# ===================================================================== #
# MAJOR-1 / MAJOR-4 — the shared six-rung cascade: identical (value,
# source) on the registry face and the runtime face, at every rung, with
# Rs-a1 termination unchanged (an EMPTY per-surface config value
# terminates at default, an ABSENT one falls through to the general key).
# ===================================================================== #


def test_major1_four_case_table_registry_and_runtime_agree(tmp_path, monkeypatch):
    home = tmp_path / "home"

    def both(surface="worker"):
        reg = settings.resolve_setting(home, settings.by_name(f"invocation.backend_{surface}"))
        run = registry.resolve_backend_raw(home, surface)
        assert reg == run, f"registry={reg!r} runtime={run!r}"
        return reg

    # [1] only the GENERAL env var set.
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    assert both() == ("sdk", "env:SELF_LEARN_BACKEND")
    monkeypatch.delenv("SELF_LEARN_BACKEND")

    # [2] only the GENERAL config key set.
    _write_config(home, "invocation", "backend", "sdk")
    assert both() == ("sdk", "config:invocation.backend")

    # [3] general config key + a GENERAL override.
    monkeypatch.setenv("SELF_LEARN_OVERRIDE_INVOCATION_BACKEND", "sdk")
    assert both() == ("sdk", "override:invocation.backend")
    monkeypatch.delenv("SELF_LEARN_OVERRIDE_INVOCATION_BACKEND")

    # [4] Rs-a1: an EMPTY per-surface config key beside a present
    # general key terminates at DEFAULT -- never consults the general
    # key at all.
    _write_config(home, "invocation", "backend_worker", "")
    assert both() == ("sdk", "default")


def test_major4_six_rung_full_tuple_table(tmp_path, monkeypatch):
    """Every rung of `resolve_backend_raw`'s six-rung cascade, reachable
    on its own, asserting the FULL `(value, source)` tuple at each --
    the gate's MAJOR-4 finding: a census that only checks rung COUNT or
    ORDER, not the full tuple each rung actually returns, would miss a
    rung silently returning the wrong value alongside the right label
    (or vice versa)."""
    home = tmp_path / "home"
    surface = "worker"
    name = f"invocation.backend_{surface}"

    def resolved():
        reg = settings.resolve_setting(home, settings.by_name(name))
        run = registry.resolve_backend_raw(home, surface)
        assert reg == run
        return reg

    # default -- nothing set anywhere.
    assert resolved() == ("sdk", "default")

    # config-general.
    _write_config(home, "invocation", "backend", "sdk")
    assert resolved() == ("sdk", "config:invocation.backend")

    # config-specific beats config-general.
    _write_config(home, "invocation", "backend_worker", "sdk")
    assert resolved() == ("sdk", "config:invocation.backend_worker")

    # env-general beats config (both specific and general config keys).
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    assert resolved() == ("sdk", "env:SELF_LEARN_BACKEND")

    # env-specific beats env-general.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    assert resolved() == ("sdk", "env:SELF_LEARN_BACKEND_WORKER")

    # override-general beats every env/config rung.
    monkeypatch.setenv("SELF_LEARN_OVERRIDE_INVOCATION_BACKEND", "sdk")
    assert resolved() == ("sdk", "override:invocation.backend")

    # override-specific beats override-general.
    monkeypatch.setenv("SELF_LEARN_OVERRIDE_INVOCATION_BACKEND_WORKER", "sdk")
    assert resolved() == ("sdk", "override:invocation.backend_worker")


def test_major1_mutation_a1_a2_stay_killed_rs_a1_termination(tmp_path):
    """The gate's own mutations (a1)/(a2): an EMPTY per-surface config
    key must terminate at default (never fall through to a present
    general key) -- (a1) an ABSENT per-surface key must still consult
    the general key (a2). Both faces, both cases."""
    home = tmp_path / "home"
    _write_config(home, "invocation", "backend", "sdk")
    _write_config(home, "invocation", "backend_worker", "")
    reg = settings.resolve_setting(home, settings.by_name("invocation.backend_worker"))
    run = registry.resolve_backend_raw(home, "worker")
    assert reg == run == ("sdk", "default")  # (a1): empty specific terminates

    home2 = tmp_path / "home2"
    _write_config(home2, "invocation", "backend", "sdk")
    reg2 = settings.resolve_setting(home2, settings.by_name("invocation.backend_worker"))
    run2 = registry.resolve_backend_raw(home2, "worker")
    assert reg2 == run2 == ("sdk", "config:invocation.backend")  # (a2): absent falls through


def test_doctor_settings_backend_worker_row_under_general_env_var(tmp_path, monkeypatch):
    """The coordinator's own expected result: `doctor settings` under
    `SELF_LEARN_BACKEND=sdk` names `invocation.backend_worker`'s row
    with the GENERAL env var in the source label -- not `"default"`."""
    home = tmp_path / "home"
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    rows = {row.name: row.detail for row in settings.preflight(home)}
    assert "invocation.backend_worker = 'sdk' (env:SELF_LEARN_BACKEND)" in rows["invocation.backend_worker"]


# ===================================================================== #
# MAJOR-2 / MAJOR-3 — literal, hand-typed name sets, never derived from
# `settings.REGISTRY` itself (a derived list makes a mutation to
# `direction`/`enabled_when` invisible: the mutated entry just moves to
# whichever generic test parametrizes the OTHER bucket, and both stay
# green).
# ===================================================================== #

_LITERAL_ENV_FIRST_NAMES = frozenset(
    [
        "provider.name",
        "provider.bedrock.region",
        "provider.bedrock.profile",
        "provider.bedrock.models.worker",
        "provider.bedrock.models.miner",
        "provider.bedrock.models.analyst",
        "provider.bedrock.models.small_fast",
        "invocation.backend",
        "invocation.backend_worker",
        "invocation.backend_worker-repair",
        "invocation.backend_miner-reader",
        "invocation.backend_analyst",
        "sdk.cli_path",
        "models.worker",
        "models.miner",
        "models.analyst",
    ]
)

_LITERAL_CONFIG_FIRST_NAMES = frozenset(
    [
        "worker.coalesce_secs",
        "worker.invoke_timeout_secs",
        "worker.repair_timeout_secs",
        "worker.repair",
        "worker.autokick",
        "worker.no_notify",
        "miner.cap_max",
        "miner.cap_per_session",
        "miner.pending_gate",
        "miner.enabled",
        "miner.autokick",
        "miner.transcripts_dir",
        "analyst.timeout_secs",
        "sdk.max_budget_usd",
        "sdk.event_logs",
        "sdk.max_turns.worker",
        "sdk.max_turns.miner",
        "sdk.max_turns.analyst",
        "serve.tick_secs",
        "ledger.actor",
        "ledger.glob_probe_budget_s",
    ]
)

_LITERAL_ENABLED_WHEN_NAMES = frozenset(
    [
        "provider.bedrock.region",
        "provider.bedrock.profile",
        "provider.bedrock.models.worker",
        "provider.bedrock.models.miner",
        "provider.bedrock.models.analyst",
        "provider.bedrock.models.small_fast",
    ]
)


def test_major2_env_first_literal_16_names_match_the_registry_exactly():
    actual = frozenset(s.name for s in settings.REGISTRY if s.direction == "env-first")
    assert actual == _LITERAL_ENV_FIRST_NAMES
    assert len(_LITERAL_ENV_FIRST_NAMES) == 16


def test_major2_config_first_literal_complement_21_names_match_the_registry_exactly():
    """The complement gives the COUNT too -- a mutation that silently
    reclassifies one entry's `direction` changes which of these two
    frozensets it belongs to, and this test (unlike a derived list)
    still knows the ORIGINAL 16/21 split to compare against."""
    actual = frozenset(s.name for s in settings.REGISTRY if s.direction == "config-first")
    assert actual == _LITERAL_CONFIG_FIRST_NAMES
    assert len(_LITERAL_CONFIG_FIRST_NAMES) == 21
    assert _LITERAL_ENV_FIRST_NAMES | _LITERAL_CONFIG_FIRST_NAMES == frozenset(
        s.name for s in settings.REGISTRY
    )
    assert not (_LITERAL_ENV_FIRST_NAMES & _LITERAL_CONFIG_FIRST_NAMES)


def test_major3_enabled_when_literal_6_names_match_the_registry_exactly():
    actual = frozenset(s.name for s in settings.REGISTRY if s.enabled_when is not None)
    assert actual == _LITERAL_ENABLED_WHEN_NAMES
    assert len(_LITERAL_ENABLED_WHEN_NAMES) == 6


@pytest.mark.parametrize("name", sorted(_LITERAL_ENV_FIRST_NAMES))
def test_major2_behavioral_env_beats_config_for_every_literal_env_first_name(tmp_path, monkeypatch, name):
    """MAJOR-2's behavioral witness: parametrized over the LITERAL set
    (not `settings.REGISTRY`'s own `direction` field), so a mutation
    that silently flips one entry's `direction` to `"config-first"`
    makes IT, specifically, fail here -- not just vanish from a
    derived census."""
    setting = settings.by_name(name)
    if setting.enabled_when is not None:
        pytest.skip(f"{name} is gated by enabled_when -- covered by the enabled_when tests instead")
    if setting.env_var is None:
        pytest.skip(f"{name} has no env rung (env_var=None) -- config-vs-env has no meaning here")
    home = tmp_path / "home"
    if setting.config_section is not None:
        assert setting.config_key is not None
        _write_config(home, setting.config_section, setting.config_key, "config-value")
    monkeypatch.setenv(setting.env_var, "env-value")
    value, source = settings.resolve_setting(home, setting)
    assert source.startswith("env:"), f"{name}: env must beat config under env-first, got {source!r}"


@pytest.mark.parametrize("name", sorted(_LITERAL_ENABLED_WHEN_NAMES))
def test_major3_behavioral_enabled_when_gates_every_literal_name(tmp_path, name):
    """MAJOR-3's behavioral witness: under `provider=anthropic` (never
    written to config.yaml here, so the registry's own default), every
    LITERALLY-named `enabled_when` entry resolves to its OWN default
    with the `inactive (provider=...)` label -- parametrized over the
    literal set, not `settings.REGISTRY`'s own `enabled_when` field, so
    a mutation clearing one entry's gate fails HERE."""
    home = tmp_path / "home"
    setting = settings.by_name(name)
    value, source = settings.resolve_setting(home, setting)
    assert source == "inactive (provider=anthropic)"
    assert value == setting.default


def test_major3_model_for_ignores_bedrock_models_under_anthropic_provider(tmp_path):
    """The required behavioral test: `model_for(<surface>)` under
    `provider=anthropic` must ignore a SET `provider.bedrock.models.
    <surface>` config value entirely -- the gate's probe_f.py scenario,
    promoted to a real test."""
    home = tmp_path / "home"
    _write_config(home, "provider", "bedrock.models.worker", "BEDROCK-ONLY-ID")
    assert provider._resolve_provider(home) == (provider.DEFAULT_PROVIDER, "default")
    assert provider.model_for("worker", home=home) != "BEDROCK-ONLY-ID"
    value, source = settings.resolve_setting(
        home, settings.by_name("provider.bedrock.models.worker")
    )
    assert source == "inactive (provider=anthropic)"
    assert value is None
