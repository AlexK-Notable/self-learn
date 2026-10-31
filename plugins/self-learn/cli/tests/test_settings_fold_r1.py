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




# ===================================================================== #
# MAJOR-1 / MAJOR-4 — the shared six-rung cascade: identical (value,
# source) on the registry face and the runtime face, at every rung, with
# Rs-a1 termination unchanged (an EMPTY per-surface config value
# terminates at default, an ABSENT one falls through to the general key).
# ===================================================================== #


















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
        "provider.bedrock.models.steward",  # U8 (17-invocation-runbook.md §1)
        "provider.bedrock.models.overseer",  # U8
        "provider.bedrock.models.small_fast",
        "sdk.cli_path",
        "models.worker",
        "models.miner",
        "models.analyst",
        "models.steward",  # U8
        "models.overseer",  # U8
    ]
)

_LITERAL_CONFIG_FIRST_NAMES = frozenset(
    [
        "worker.coalesce_secs",
        "worker.invoke_timeout_secs",
        "worker.repair_timeout_secs",
        "worker.batch_cap",
        "worker.repair",
        "worker.autokick",
        "worker.no_notify",
        "miner.cap_max",
        "miner.cap_per_session",
        "miner.pending_gate",
        "miner.message_chars",
        "miner.session_chars",
        "miner.run_chars",
        "miner.reader_timeout_secs",
        "miner.enabled",
        "miner.autokick",
        "miner.transcripts_dir",
        "miner.mined_scheduled_jobs",  # 2026-10-07: scheduled jobs the miner reads anyway
        "miner.skip_sessions",  # 2026-10-11: session ids the miner never reads
        "miner.engine",  # new miner R2: the runner switch between the two engines
        "miner.parallel",  # new miner R2
        "miner.spine_tokens",  # new miner R2
        "miner.max_sessions_per_run",  # new miner R2
        "miner.max_run_usd",  # new miner R2
        "refs.transcript_roots",  # U1 (checked pointer), 2026-09-26
        "analyst.timeout_secs",
        "steward.timeout_secs",  # U8
        "steward.packet_size",  # U10
        "steward.turns_per_lesson",  # 2026-09-20: the batch-sized turn limit
        "steward.cooldown_secs",  # U10
        "steward.enabled",  # U10, config-only rollback switch
        "runs.attempt_cap",  # U1 (S-68), shared by both delegated runners
        "overseer.timeout_secs",  # U8
        "overseer.max_model_calls",  # U8
        "overseer.enabled",  # O-3
        "overseer.broad_removal_threshold",  # O-6
        "premises.enabled",  # S-NEXT-u2-sweep, tier C switch, default true
        "premises.backfill_per_night",  # S-NEXT-u6-backfill, tier C, default 10
        "sdk.max_budget_usd",
        "sdk.model_cli_floors",  # U4 (S-69): the per-model Claude Code floor
        "sdk.prefer_installed_cli",  # U4c (S-70): the installed-binary opt-out
        "sdk.capture_sessions",  # 2026-09-28: session copies + summarized thinking
        "sdk.event_logs",
        "sdk.max_turns.worker",
        "sdk.max_turns.miner",
        "sdk.max_turns.analyst",
        "sdk.max_turns.steward",  # U8
        "sdk.max_turns.overseer",  # U8
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
        "provider.bedrock.models.steward",  # U8
        "provider.bedrock.models.overseer",  # U8
        "provider.bedrock.models.small_fast",
    ]
)


def test_major2_env_first_literal_names_match_the_registry_exactly():
    actual = frozenset(s.name for s in settings.REGISTRY if s.direction == "env-first")
    assert actual == _LITERAL_ENV_FIRST_NAMES


def test_major2_config_first_literal_complement_names_match_the_registry_exactly():
    """The complement covers the whole registry -- a mutation that
    silently reclassifies one entry's `direction` changes which of these
    two frozensets it belongs to, and this test (unlike a derived list)
    still knows the ORIGINAL split to compare against. The set equality
    fixes the counts; the old `len(literal) == N` lines only counted a
    literal against itself (test audit L2-27)."""
    actual = frozenset(s.name for s in settings.REGISTRY if s.direction == "config-first")
    assert actual == _LITERAL_CONFIG_FIRST_NAMES
    assert _LITERAL_ENV_FIRST_NAMES | _LITERAL_CONFIG_FIRST_NAMES == frozenset(
        s.name for s in settings.REGISTRY
    )
    assert not (_LITERAL_ENV_FIRST_NAMES & _LITERAL_CONFIG_FIRST_NAMES)


def test_major3_enabled_when_literal_names_match_the_registry_exactly():
    actual = frozenset(s.name for s in settings.REGISTRY if s.enabled_when is not None)
    assert actual == _LITERAL_ENABLED_WHEN_NAMES


@pytest.mark.parametrize("name", sorted(_LITERAL_ENV_FIRST_NAMES))
def test_major2_behavioral_env_beats_config_for_every_literal_env_first_name(tmp_path, monkeypatch, name):
    """MAJOR-2's behavioral witness: parametrized over the LITERAL set
    (not `settings.REGISTRY`'s own `direction` field), so a mutation
    that silently flips one entry's `direction` to `"config-first"`
    makes IT, specifically, fail here -- not just vanish from a
    derived census.

    Fold r2 (gap-3): no `enabled_when` skip. `provider.bedrock.region`
    and `provider.bedrock.profile` are the only two `enabled_when`
    members of this literal set that also carry a real `env_var` (the
    four `provider.bedrock.models.*` entries all have `env_var=None` --
    MAJOR-4's move to the always-active `models.<surface>` siblings --
    so they still legitimately hit the "no env rung" skip below,
    unaffected by this fix). For those two, `provider.name: bedrock` is
    written to config FIRST so the gate is genuinely active before the
    env-vs-config race runs -- a `direction` mutation on either now
    fails here instead of hiding behind an unconditional skip."""
    setting = settings.by_name(name)
    if setting.env_var is None:
        pytest.skip(f"{name} has no env rung (env_var=None) -- config-vs-env has no meaning here")
    home = tmp_path / "home"
    if setting.enabled_when is not None:
        _write_config(home, "provider", "name", "bedrock")
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
