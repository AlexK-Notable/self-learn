"""U-settings Phase 1 — the settings registry (``settings.py``): the
registry's own resolution mechanics (config.yaml > env > default —
flipped 2026-09-01, S-58; see `settings.py`'s module docstring "Two
precedence directions, on purpose" — fail-closed PER RUNG with
fall-through on a malformed value, no caching), the registry-wide
structural invariants, the `doctor settings` verb, and one consumer-
level test per rewired call site proving the config.yaml rung actually
reaches real production code, not just `resolve_setting` in isolation.

Fixtures reused by NAME from `test_worker.py`/`test_repair.py` (this
suite's own convention — see `test_repair.py`'s module docstring for the
precedent): `env`, `sdk_fake_worker`, `seed_pending`, `_defect_script`,
`_t4_missing_target`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import analyst, miner, provider, serve, settings, telemetry, worker
from self_learn import cli as cli_mod
from self_learn import ledger_ops as ledger_ops_mod
from self_learn import verbs as verbs_mod
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import events as events_mod

from test_worker import env, sdk_fake_worker, seed_pending  # noqa: F401 -- fixtures resolved by name
from test_repair import _defect_script, _t4_missing_target  # noqa: F401
from test_miner import a as miner_a, candidate as miner_candidate, shim_reader, u as miner_u, write_transcript
from support import make_home


# ===================================================================== #
# Shared helpers
# ===================================================================== #


def _write_config(home: Path, section: str, dotted_key: str, value: object) -> None:
    """Writes `home/config.yaml` with `value` at `section.dotted_key`,
    merging into whatever is already there. Uses `ruamel.yaml` (not
    hand-built strings, unlike `test_provider.py`'s
    `_write_provider_yaml`) because the registry's dotted keys nest
    arbitrarily deep (`sdk.max_turns.worker`)."""
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
    for seg in segments[:-1]:
        node = node.setdefault(seg, {})
    node[segments[-1]] = value
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh)


def _default_value(setting: settings.Setting) -> object:
    return setting.default() if callable(setting.default) else setting.default


def _valid_override(setting: settings.Setting) -> object:
    """A value guaranteed to satisfy every registry entry's own
    `validate` (every numeric `validate` in the registry either clamps
    to >= 0 or rejects only <= 0 — 999/999.0 survives both), and
    guaranteed to differ from the entry's own default."""
    if setting.kind == "bool":
        return not _default_value(setting)
    if setting.kind == "int":
        return 999
    if setting.kind == "float":
        return 999.0
    if setting.kind == "str":
        return "settings-test-override"
    raise AssertionError(setting.kind)  # pragma: no cover - closed Kind


def _env_string(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


_NUMERIC_OR_BOOL_NAMES = [s.name for s in settings.REGISTRY if s.kind != "str"]
_STR_NAMES = [s.name for s in settings.REGISTRY if s.kind == "str"]
_ALL_NAMES = [s.name for s in settings.REGISTRY]

# M-S (S-58): three registry mechanics the generic precedence tests
# below were never written against, each exercised by its OWN
# dedicated test instead (further down this file) rather than forcing
# a placeholder value/provider through them:
#   - `enabled_when` (the six `provider.bedrock.*` entries): under
#     `provider=anthropic` (every generic test's ambient default) they
#     resolve to `f"inactive (provider=anthropic)"`, never "default"
#     nor a config/env value, no matter what config.yaml/env holds.
#   - `accepts` (`provider.name`, `invocation.backend` + its four
#     per-surface siblings): `_valid_override`'s generic placeholder
#     string is never a member of the whitelist, so `validate` clamps
#     it back to the in-place default instead of "winning".
#   - `direction="env-first"` (every M-S entry): env outranks config,
#     the opposite of every pre-amendment entry's `config-first`.
_ENABLED_WHEN_NAMES = [s.name for s in settings.REGISTRY if s.enabled_when is not None]
_ACCEPTS_NAMES = [s.name for s in settings.REGISTRY if s.accepts is not None]
_ENV_FIRST_NAMES = [s.name for s in settings.REGISTRY if s.direction == "env-first"]

_GENERIC_DEFAULT_NAMES = [n for n in _ALL_NAMES if n not in _ENABLED_WHEN_NAMES]
_GENERIC_CONFIG_BEATS_DEFAULT_NAMES = [
    n for n in _ALL_NAMES if n not in _ENABLED_WHEN_NAMES and n not in _ACCEPTS_NAMES
]
_GENERIC_CONFIG_BEATS_ENV_NAMES = [n for n in _ALL_NAMES if n not in _ENV_FIRST_NAMES]
_GENERIC_STR_NAMES = [n for n in _STR_NAMES if n not in _ENABLED_WHEN_NAMES]


@pytest.fixture(autouse=True)
def _clear_registry_env(monkeypatch):
    """Every registry env var, cleared before each test in this file —
    the suite-wide `_worker_test_defaults` fixture (conftest.py)
    ambiently sets several of them (`SELF_LEARN_WORKER_AUTOKICK=0`,
    `SELF_LEARN_COALESCE_SECS=0`, `SELF_LEARN_NO_NOTIFY=1`,
    `SELF_LEARN_MINER_AUTOKICK=0`, `SELF_LEARN_TRANSCRIPTS_DIR=<tmp>`)
    for the SUITE's own isolation reasons, which would otherwise make
    every "default" / "config beats default" assertion below false on
    THIS machine's env alone."""
    for setting in settings.REGISTRY:
        # M-S (S-58): `env_var` is `str | None` now (the four
        # `provider.bedrock.models.*` entries with no env rung at all)
        # -- nothing to clear for those.
        if setting.env_var is not None:
            monkeypatch.delenv(setting.env_var, raising=False)


# ===================================================================== #
# Registry structural invariants
# ===================================================================== #


def test_registry_names_are_unique():
    names = [s.name for s in settings.REGISTRY]
    assert len(names) == len(set(names))


def test_registry_name_matches_its_config_path():
    for s in settings.REGISTRY:
        if s.config_section is not None:
            assert s.name == f"{s.config_section}.{s.config_key}", s.name


def test_registry_defaults_match_their_source_constants():
    """The duplicated-literal risk `settings.py`'s own module comment
    names, pinned: every default in the registry must equal the real
    constant it was copied from. A future edit to one of these constants
    without a matching registry edit turns this red instead of silently
    drifting."""
    by_name = {s.name: s for s in settings.REGISTRY}
    assert by_name["worker.coalesce_secs"].default == float(worker.DEFAULT_COALESCE_SECS)
    assert by_name["worker.invoke_timeout_secs"].default == float(worker.INVOKE_TIMEOUT_SECS)
    assert by_name["worker.repair_timeout_secs"].default == float(worker.REPAIR_TIMEOUT_SECS)
    assert by_name["miner.cap_max"].default == miner.DEFAULT_CAP_MAX
    assert by_name["miner.cap_per_session"].default == miner.DEFAULT_CAP_PER_SESSION
    assert by_name["miner.pending_gate"].default == miner.DEFAULT_PENDING_GATE
    assert by_name["analyst.timeout_secs"].default == float(analyst.DEFAULT_ANALYST_TIMEOUT)
    assert by_name["sdk.event_logs"].default == events_mod._DEFAULT_EVENT_LOGS
    assert by_name["sdk.max_turns.worker"].default == backend_mod._DEFAULT_MAX_TURNS["WORKER"]
    assert by_name["sdk.max_turns.miner"].default == backend_mod._DEFAULT_MAX_TURNS["MINER"]
    assert by_name["sdk.max_turns.analyst"].default == backend_mod._DEFAULT_MAX_TURNS["ANALYST"]
    assert by_name["serve.tick_secs"].default == serve.DEFAULT_TICK_SECS
    assert by_name["ledger.glob_probe_budget_s"].default == ledger_ops_mod.DEFAULT_GLOB_PROBE_BUDGET_S
    # M-S (S-58, BLOCKER-1): `settings._PROVIDERS`/`_DEFAULT_PROVIDER`
    # are duplicated from `provider.PROVIDERS`/`provider.DEFAULT_
    # PROVIDER` for the same reason every literal above is duplicated
    # (`settings.py` cannot import `provider.py` -- `provider.py` now
    # imports `settings.py`, so the reverse edge would close a cycle).
    assert settings._PROVIDERS == provider.PROVIDERS
    assert settings._DEFAULT_PROVIDER == provider.DEFAULT_PROVIDER
    assert by_name["provider.name"].default == provider.DEFAULT_PROVIDER


def test_models_star_defaults_are_the_called_shipped_functions_never_copied():
    """`models.worker`/`.miner`/`.analyst`'s `default` is a CALLABLE
    (unlike every literal pinned above) -- each entry's own module
    docstring precedent (`P-b`: "the surface's shipped default
    function, CALLED, never copied") means there is no static literal
    to pin here; instead this proves the wrapper CALLS the real
    function rather than caching or reimplementing it, by making the
    real function's answer change and observing the registry default
    change with it."""
    by_name = {s.name: s for s in settings.REGISTRY}
    assert by_name["models.worker"].default() == worker.worker_model()
    assert by_name["models.miner"].default() == miner.miner_model()
    assert by_name["models.analyst"].default() == analyst._model()

    os.environ["SELF_LEARN_WORKER_MODEL"] = "mutation-witness-model"
    try:
        assert by_name["models.worker"].default() == "mutation-witness-model"
    finally:
        del os.environ["SELF_LEARN_WORKER_MODEL"]


def test_by_name_raises_for_an_unknown_key():
    with pytest.raises(KeyError):
        settings.by_name("not-a-real-setting")


# ===================================================================== #
# The precedence chain, generically over every registry entry
# ===================================================================== #


@pytest.mark.parametrize("name", _GENERIC_DEFAULT_NAMES)
def test_default_when_nothing_set(name, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name(name)
    value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == "default"


@pytest.mark.parametrize("name", _GENERIC_CONFIG_BEATS_DEFAULT_NAMES)
def test_config_beats_default(name, tmp_path):
    home = tmp_path / "home"
    setting = settings.by_name(name)
    override = _valid_override(setting)
    _write_config(home, setting.config_section, setting.config_key, override)
    value, source = settings.resolve_setting(home, setting)
    assert value == override
    assert source == f"config:{setting.config_section}.{setting.config_key}"


@pytest.mark.parametrize("name", _GENERIC_CONFIG_BEATS_ENV_NAMES)
def test_config_beats_env(name, tmp_path, monkeypatch):
    """U-flip (2026-09-01, S-58): config.yaml now outranks an explicit
    env var for every registry entry — the opposite of `provider.py`'s
    own env-first chain (deliberately; see `settings.py`'s module
    docstring). The env value and the config value are chosen to be
    DIFFERENT (opposite booleans; 111 vs 999 for numerics; distinct
    strings) so a build that silently read env instead of config would
    fail this, not pass it by coincidence."""
    home = tmp_path / "home"
    setting = settings.by_name(name)
    default = _default_value(setting)
    if setting.kind == "bool":
        config_value, env_value = (not default), default
    elif setting.kind == "int":
        config_value, env_value = 111, 999
    elif setting.kind == "float":
        config_value, env_value = 111.0, 999.0
    else:
        config_value, env_value = "config-value", "env-value"
    _write_config(home, setting.config_section, setting.config_key, config_value)
    monkeypatch.setenv(setting.env_var, _env_string(env_value))
    value, source = settings.resolve_setting(home, setting)
    assert value == config_value
    assert source == f"config:{setting.config_section}.{setting.config_key}"


@pytest.mark.parametrize("name", _NUMERIC_OR_BOOL_NAMES)
def test_malformed_env_warns_and_falls_back(name, tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name(name)
    monkeypatch.setenv(setting.env_var, "not-a-real-value")
    value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == "default"
    err = capsys.readouterr().err
    assert setting.env_var in err
    assert "not-a-real-value" in err
    assert setting.name in err


@pytest.mark.parametrize("name", _NUMERIC_OR_BOOL_NAMES)
def test_malformed_config_warns_and_falls_back(name, tmp_path, capsys):
    """No env var set — the malformed config value falls through the
    (absent) env rung straight to the default. See
    `test_malformed_config_falls_through_to_env` below for the leg
    where a valid env var IS there to catch the fall-through."""
    home = tmp_path / "home"
    setting = settings.by_name(name)
    _write_config(home, setting.config_section, setting.config_key, "not-a-real-value")
    value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == "default"
    err = capsys.readouterr().err
    assert setting.config_section in err
    assert setting.name in err


@pytest.mark.parametrize("name", _NUMERIC_OR_BOOL_NAMES)
def test_malformed_config_falls_through_to_env(name, tmp_path, monkeypatch, capsys):
    """The new leg the U-flip adds (S-58, spec §1.2's boundary pin: "a
    typo in config.yaml can never brick a role a unit's env var...
    would have served"). A malformed config value must NOT dead-end at
    the default while a perfectly valid env var sits one rung down —
    resolution continues past the bad rung to the good one, still
    warning exactly once (for the config rung only; the env rung never
    fails, so it never warns)."""
    home = tmp_path / "home"
    setting = settings.by_name(name)
    env_value = _valid_override(setting)
    _write_config(home, setting.config_section, setting.config_key, "not-a-real-value")
    monkeypatch.setenv(setting.env_var, _env_string(env_value))
    value, source = settings.resolve_setting(home, setting)
    assert value == env_value
    assert source == f"env:{setting.env_var}"
    err = capsys.readouterr().err
    assert setting.config_section in err  # the config-rung warn still fires
    assert setting.name in err
    assert setting.env_var not in err  # the env rung resolved cleanly -- no second warn


@pytest.mark.parametrize("name", _NUMERIC_OR_BOOL_NAMES)
def test_malformed_config_and_malformed_env_both_warn_then_default(name, tmp_path, monkeypatch, capsys):
    """Fail-closed is PER LAYER, not per resolution (spec §1.2): when
    BOTH rungs are malformed, each warns independently and the final
    answer is still the default — two warn lines, one per bad rung,
    never a swallowed second failure."""
    home = tmp_path / "home"
    setting = settings.by_name(name)
    _write_config(home, setting.config_section, setting.config_key, "not-a-real-config-value")
    monkeypatch.setenv(setting.env_var, "not-a-real-env-value")
    value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == "default"
    err = capsys.readouterr().err
    assert "not-a-real-config-value" in err
    assert "not-a-real-env-value" in err
    assert setting.config_section in err  # the config-rung warn fired
    assert setting.env_var in err  # the env-rung warn ALSO fired -- not swallowed
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 2  # one warn line per malformed rung, no more, no fewer


def test_empty_env_value_falls_through_not_treated_as_present(tmp_path):
    """An empty string env var is "no answer", not a malformed value —
    matches every env-first entry's OWN `if value:` truthiness rule
    (not `if value is not None:`; `_resolve_registry_str`'s callers
    inherit this from `resolve_setting`/`_try_env` directly now, the
    same behavior `provider.py`'s retired `_resolve_str_setting` used
    to hand-roll)."""
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name("worker.coalesce_secs")
    os.environ[setting.env_var] = ""
    try:
        value, source = settings.resolve_setting(home, setting)
    finally:
        del os.environ[setting.env_var]
    assert source == "default"
    assert value == _default_value(setting)


@pytest.mark.parametrize("name", _GENERIC_STR_NAMES)
def test_empty_config_str_value_falls_through_silently(name, tmp_path, capsys):
    """M-4 (review 2026-09-01): the config.yaml mirror of the test
    above — before this fix, `transcripts_dir: ""` was accepted as a
    VALID (empty) string and resolved to `Path('.')`, while the
    identically-empty ENV var already fell through silently (no warn).
    An empty config string must now match: "no answer", not a
    malformed one — no warn, straight through to the default (no env
    set in this test)."""
    home = tmp_path / "home"
    setting = settings.by_name(name)
    _write_config(home, setting.config_section, setting.config_key, "")
    value, source = settings.resolve_setting(home, setting)
    assert source == "default"
    assert value == _default_value(setting)
    assert capsys.readouterr().err == ""  # silent -- NOT the "not a valid str" warn path


@pytest.mark.parametrize("name", _GENERIC_STR_NAMES)
def test_malformed_config_str_value_warns_and_falls_back(name, tmp_path, capsys):
    """M-4's other half: `str` was the one kind excluded from every
    malformed-value test above (any actual string always "parses" as a
    str, so `"not-a-real-value"` can't exercise this kind) — a
    NON-scalar YAML value (a list) is what a str-kind config leaf can
    actually fail to parse as, and it must warn + fall through exactly
    like every other kind's malformed case, not be silently accepted."""
    home = tmp_path / "home"
    setting = settings.by_name(name)
    _write_config(home, setting.config_section, setting.config_key, ["not", "a", "string"])
    value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == "default"
    err = capsys.readouterr().err
    assert setting.config_section in err
    assert setting.name in err


# ===================================================================== #
# M-S (S-58): direction, enabled_when, accepts -- the three mechanics
# the generic precedence tests above deliberately exclude by name.
# ===================================================================== #


@pytest.mark.parametrize("name", _ENV_FIRST_NAMES)
def test_env_first_env_beats_config(name, tmp_path, monkeypatch):
    """The mirror of `test_config_beats_env` for the OTHER direction:
    every `direction="env-first"` entry resolves env OVER config -- the
    opposite of every pre-amendment entry (proven above). Entries with
    no `env_var` at all (the four gated `provider.bedrock.models.*`)
    are excluded here for the obvious reason (nothing to set); entries
    with `accepts` use a value from their own whitelist so this test
    exercises precedence, not the separate `accepts`/`validate` fold
    already covered below."""
    setting = settings.by_name(name)
    if setting.env_var is None:
        pytest.skip(f"{name}: no env rung to race against config")
    home = tmp_path / "home"
    if name in _ACCEPTS_NAMES:
        env_value, config_value = "sdk", "sdk"  # only member of KNOWN_BACKENDS today
        if name == "provider.name":
            env_value, config_value = "bedrock", "anthropic"
    else:
        env_value, config_value = "env-wins", "config-loses"
    if setting.enabled_when is not None:
        monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    _write_config(home, setting.config_section, setting.config_key, config_value)
    monkeypatch.setenv(setting.env_var, env_value)
    value, source = settings.resolve_setting(home, setting)
    assert value == env_value
    assert source == f"env:{setting.env_var}"


@pytest.mark.parametrize("name", _ENABLED_WHEN_NAMES)
def test_enabled_when_gates_every_rung_including_override(name, tmp_path, monkeypatch):
    """`enabled_when` is evaluated BEFORE even the override rung
    (03-decisions.md row S-58) -- under `provider=anthropic` (never set
    here, so the ambient default), NOTHING at ANY rung reaches this
    entry: not an active override, not env, not config. Every rung is
    armed simultaneously so a build that only gated, say, the config
    rung would still fail this."""
    setting = settings.by_name(name)
    home = tmp_path / "home"
    if setting.env_var is not None:
        monkeypatch.setenv(setting.env_var, "armed-env-value")
    _write_config(home, setting.config_section, setting.config_key, "armed-config-value")
    with settings.override(name, "armed-override-value"):
        value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == "inactive (provider=anthropic)"


@pytest.mark.parametrize("name", _ENABLED_WHEN_NAMES)
def test_enabled_when_true_reaches_every_rung_normally(name, tmp_path, monkeypatch):
    """The positive control for the test above: under `provider=
    bedrock`, these SAME six entries resolve exactly like an ordinary
    env-first entry -- config beats nothing else set, matching
    `test_config_beats_default`'s own assertion shape for every OTHER
    entry (proving `enabled_when=True` is not itself silently
    inert)."""
    setting = settings.by_name(name)
    home = tmp_path / "home"
    monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    override = _valid_override(setting)
    _write_config(home, setting.config_section, setting.config_key, override)
    value, source = settings.resolve_setting(home, setting)
    assert value == override
    assert source == f"config:{setting.config_section}.{setting.config_key}"


@pytest.mark.parametrize("name", _ACCEPTS_NAMES)
def test_accepts_entries_clamp_on_read_exactly_like_any_other_validate(name, tmp_path, monkeypatch):
    """`validate` (the READ-path clamp) is UNCHANGED for `provider.name`/
    `invocation.backend*` -- an off-whitelist config.yaml value folds
    in place to the entry's own default, same mechanism every other
    clamping entry in this registry already uses, `accepts` notwith-
    standing (that field governs `config_set`, not `resolve_setting`,
    proven separately below)."""
    setting = settings.by_name(name)
    home = tmp_path / "home"
    if setting.enabled_when is not None:
        monkeypatch.setenv("SELF_LEARN_PROVIDER", "bedrock")
    _write_config(home, setting.config_section, setting.config_key, "off-whitelist-value")
    value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == f"config:{setting.config_section}.{setting.config_key}"


@pytest.mark.parametrize("name", _ACCEPTS_NAMES)
def test_accepts_refuses_the_write_and_leaves_config_yaml_untouched(name, tmp_path):
    """The laundering-prevention gate (MAJOR-3/r4-M1/r5-M1, dispatch
    requirement 3): `config set` on an off-whitelist value is REFUSED
    outright -- and, the mutation this test actually exists to catch,
    the refusal happens BEFORE any write, not after a clamping
    `validate` quietly launders it into the in-place default. Moving
    the `accepts` check to AFTER `_apply_validate` in `config_set`
    (the bug this guards against) would make this test's `pytest.raises`
    fail to fire AND commit `anthropic`/`sdk` to config.yaml instead of
    refusing -- both assertions below are load-bearing, not redundant."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=home, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=home, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=home, check=True)
    config_path = home / "config.yaml"
    config_path.write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "config.yaml"], cwd=home, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=home, check=True)

    before = config_path.read_bytes()
    with pytest.raises(settings.InvalidSettingValueError, match="not accepted"):
        settings.config_set(home, name, "off-whitelist-value")
    after = config_path.read_bytes()
    assert after == before  # the file was never touched, not even a half-write


def test_note_field_names_the_fold_when_provider_name_config_value_is_off_whitelist(tmp_path):
    """`setting_row`'s `note` field (r5-m1(c)/r6-m1(a)): `None` on an
    ordinary resolution, populated with the raw-vs-folded pair whenever
    the answering rung's raw value was actually folded by `validate`."""
    home = tmp_path / "home"
    row_clean = settings.setting_row(home, settings.by_name("provider.name"))
    assert row_clean["note"] is None  # nothing set at all -- no fold to report

    _write_config(home, "provider", "name", "off-whitelist-value")
    row_folded = settings.setting_row(home, settings.by_name("provider.name"))
    assert row_folded["value"] == "anthropic"
    assert row_folded["note"] == "'off-whitelist-value' folded to 'anthropic'"


def test_preflight_detail_carries_note_in_both_info_and_warn_branches(tmp_path, monkeypatch):
    """r6-m1(b) (dispatch requirement 4): BOTH of `preflight`'s two
    branches -- the ordinary INFO row AND the WARN/override row -- must
    carry `note` when the answering rung's raw value was folded, not
    just one of the two."""
    home = tmp_path / "home"
    _write_config(home, "provider", "name", "off-whitelist-value")
    rows = {r.name: r for r in settings.preflight(home)}
    assert "folded to 'anthropic'" in rows["provider.name"].detail  # INFO branch

    monkeypatch.setenv("SELF_LEARN_OVERRIDE_PROVIDER_NAME", "another-off-whitelist-value")
    rows2 = {r.name: r for r in settings.preflight(home)}
    assert rows2["provider.name"].verdict == "WARN"
    assert "folded to 'anthropic'" in rows2["provider.name"].detail  # WARN branch


# ===================================================================== #
# Positive controls: no caching, and the resolver reads PER-SETTING data
# ===================================================================== #


def test_no_cache_a_mid_process_env_mutation_is_seen_immediately(tmp_path, monkeypatch):
    """Load-bearing per `settings.py`'s own module docstring:
    `serve._worker_autokick_disabled()` mutates `os.environ` mid-process
    as an API. If `resolve_setting` ever cached, THIS test goes red while
    every precedence test above stays green (each of those only calls
    `resolve_setting` once)."""
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name("worker.autokick")
    monkeypatch.setenv(setting.env_var, "0")
    value1, source1 = settings.resolve_setting(home, setting)
    assert (value1, source1) == (False, "env:SELF_LEARN_WORKER_AUTOKICK")
    monkeypatch.delenv(setting.env_var)
    value2, source2 = settings.resolve_setting(home, setting)
    assert (value2, source2) == (True, "default")


def test_resolver_is_not_a_stub_two_settings_resolve_independently(tmp_path):
    """A build that hardcoded `resolve_setting` to always return one
    setting's default (or one literal) would pass any SINGLE-setting
    test above by accident; this cross-checks two registry entries with
    DIFFERENT defaults in the same call."""
    home = tmp_path / "home"
    home.mkdir()
    v1, _s1 = settings.resolve_setting(home, settings.by_name("miner.cap_max"))
    v2, _s2 = settings.resolve_setting(home, settings.by_name("serve.tick_secs"))
    assert v1 == 15
    assert v2 == 60.0
    assert v1 != v2


# ===================================================================== #
# The override channel (Blocker fix, review 2026-09-01) -- a rung ABOVE
# config.yaml, for a process asserting a runtime invariant about itself,
# distinct from S-58's operator-preference precedence entirely.
# ===================================================================== #


def test_override_beats_config_and_env_in_process(tmp_path, monkeypatch):
    """Both the config.yaml rung AND the env rung say `True` -- if
    `override` merely matched whichever of those already won, this
    would pass by coincidence. It must win over BOTH at once."""
    home = tmp_path / "home"
    _write_config(home, "worker", "autokick", True)
    monkeypatch.setenv("SELF_LEARN_WORKER_AUTOKICK", "1")
    setting = settings.by_name("worker.autokick")
    with settings.override("worker.autokick", False):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == (False, "override:worker.autokick")
    # restored: config (not env, not override) wins again, S-58 intact
    value, source = settings.resolve_setting(home, setting)
    assert (value, source) == (True, "config:worker.autokick")


def test_override_nests_and_restores_to_the_prior_override(tmp_path):
    """Mirrors `serve._worker_autokick_disabled`'s own restore-on-exit
    contract, preserved byte-for-byte from its pre-fix `os.environ`
    version: a NESTED override restores to the OUTER override on exit,
    never past it to config/env/default -- `_run_tick` depends on this
    exact nesting to hold the switch open across both the mine job and
    the worker job in one tick."""
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name("worker.autokick")
    with settings.override("worker.autokick", False):
        value1, source1 = settings.resolve_setting(home, setting)
        assert (value1, source1) == (False, "override:worker.autokick")
        with settings.override("worker.autokick", True):
            value2, source2 = settings.resolve_setting(home, setting)
            assert (value2, source2) == (True, "override:worker.autokick")
        # back to the OUTER override, not past it
        value3, source3 = settings.resolve_setting(home, setting)
        assert (value3, source3) == (False, "override:worker.autokick")
    # both exited: ordinary default
    value4, source4 = settings.resolve_setting(home, setting)
    assert (value4, source4) == (True, "default")


def test_override_unknown_name_raises():
    with pytest.raises(KeyError):
        with settings.override("not-a-real-setting", True):
            pass  # pragma: no cover -- must never be reached


def test_override_channel_propagates_to_a_real_child_process(tmp_path):
    """THE leg no other test covers, and the one that matters (review
    2026-09-01): an earlier draft of this fix used an in-process dict,
    which would pass every test above and STILL be wrong, because a
    detached spawn started with `start_new_session=True` (this
    codebase's own convention, `worker.py:1103-1115`) inherits a flag
    only as ENVIRONMENT, never Python state. `config.yaml` names
    `worker.autokick: true` here on purpose, disagreeing with the
    override, so a build that let the child fall through to config
    (env-inherited but not override-recognised, or override recognised
    but losing to config in the CHILD too) fails this exactly where it
    would matter in production. Mutation check performed by hand: with
    `override`'s env write removed, the child sees no
    `SELF_LEARN_OVERRIDE_WORKER_AUTOKICK` at all and this test goes red
    (`True|config:worker.autokick`, not `False|override:...`)."""
    home = tmp_path / "home"
    _write_config(home, "worker", "autokick", True)
    script = (
        "from self_learn import settings\n"
        "value, source = settings.resolve_setting(\n"
        f"    {str(home)!r}, settings.by_name('worker.autokick')\n"
        ")\n"
        "print(f'{value}|{source}')\n"
    )
    with settings.override("worker.autokick", False):
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
        )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False|override:worker.autokick"


# ===================================================================== #
# MINOR-4 (review r2 2026-09-01): override() must either round-trip
# every SettingValue member (str, int, float, bool, None) or REFUSE
# loudly at call time for the ones it cannot safely hold -- one test
# per member.
# ===================================================================== #


def test_override_round_trips_str_including_empty(tmp_path):
    """The exact regression named in the review: `override(name, "")`
    used to be read back as "nothing set" (`if override_raw:`) and
    silently dropped -- an empty string IS a real, present override
    value, not an absent one."""
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name("miner.transcripts_dir")
    with settings.override("miner.transcripts_dir", ""):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == ("", "override:miner.transcripts_dir")
    with settings.override("miner.transcripts_dir", "/custom/path"):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == ("/custom/path", "override:miner.transcripts_dir")


def test_override_round_trips_int(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name("miner.cap_max")
    with settings.override("miner.cap_max", 7):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == (7, "override:miner.cap_max")


def test_override_round_trips_float(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name("serve.tick_secs")
    with settings.override("serve.tick_secs", 12.5):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == (12.5, "override:serve.tick_secs")


def test_override_round_trips_bool(tmp_path):
    """Bool coverage already exists above (`worker.autokick` throughout
    this section) -- this one is here only so the union-member list is
    complete and explicit, not implied."""
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name("worker.repair")
    with settings.override("worker.repair", False):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == (False, "override:worker.repair")


def test_override_round_trips_none_for_the_one_setting_that_allows_it(tmp_path):
    """`None` is `sdk.max_budget_usd`'s OWN default (meaning
    "unlimited") -- the one setting in the registry where `None` is a
    real resolved value, not a parse-failure signal. Config.yaml is
    deliberately set to a REAL budget here, so a build that silently
    fell through to config instead of honouring the override would
    fail this, not pass it by coincidence."""
    home = tmp_path / "home"
    _write_config(home, "sdk", "max_budget_usd", 5.0)
    setting = settings.by_name("sdk.max_budget_usd")
    with settings.override("sdk.max_budget_usd", None):
        value, source = settings.resolve_setting(home, setting)
        assert (value, source) == (None, "override:sdk.max_budget_usd")
    # restored: config wins again
    value, source = settings.resolve_setting(home, setting)
    assert (value, source) == (5.0, "config:sdk.max_budget_usd")


def test_override_none_refuses_for_a_setting_whose_default_is_not_none():
    """Every OTHER setting's `None` would mean "this rung's parse
    failed" internally, not a real resolved value -- `override()` must
    refuse loudly (a programming error, never operator input) rather
    than write something a typed consumer (or `validate`) cannot hold."""
    with pytest.raises(ValueError, match="None is not a valid resolved value"):
        with settings.override("worker.autokick", None):
            pass  # pragma: no cover -- must never be reached


# ===================================================================== #
# The unknown-key sweep
# ===================================================================== #


def test_unknown_keys_flags_a_typo(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("worker:\n  coalesc_secs: 5\n", encoding="utf-8")  # typo
    assert settings.unknown_keys(home) == ["worker.coalesc_secs"]


def test_unknown_keys_silent_on_a_real_config_file_with_only_known_keys(tmp_path):
    """Positive control for the sweep above: a config.yaml carrying only
    REAL registry keys (never a typo of one) must report nothing unknown
    — proves the sweep does not over-flag legitimate keys."""
    home = tmp_path / "home"
    home.mkdir()
    _write_config(home, "worker", "coalesce_secs", 5)
    _write_config(home, "sdk", "max_turns.worker", 150)
    assert settings.unknown_keys(home) == []


# ===================================================================== #
# doctor settings
# ===================================================================== #


def test_preflight_renders_one_info_row_per_registry_entry(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    rows = settings.preflight(home)
    info_names = {r.name for r in rows if r.verdict == "INFO"}
    assert info_names == {s.name for s in settings.REGISTRY}


def test_preflight_renders_a_warn_row_for_an_unknown_config_key(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("sdk:\n  bogus_key: 1\n", encoding="utf-8")
    rows = settings.preflight(home)
    warn_details = [r.detail for r in rows if r.verdict == "WARN"]
    assert any("sdk.bogus_key" in d for d in warn_details)


def test_cli_doctor_settings_prints_every_registry_entry(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    rc = cli_mod.main(["doctor", "settings"])
    out = capsys.readouterr().out
    assert rc == 0
    for s in settings.REGISTRY:
        assert f"doctor: INFO {s.name} — {s.name} = " in out


def test_cli_doctor_settings_reflects_a_config_yaml_override(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    _write_config(home, "miner", "cap_max", 7)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    rc = cli_mod.main(["doctor", "settings"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "doctor: INFO miner.cap_max — miner.cap_max = 7 (config:miner.cap_max)" in out


def test_cli_doctor_invocation_output_unaffected_by_the_settings_verb(tmp_path, monkeypatch, capsys):
    """Constraint check (not a new behaviour): adding `doctor settings`
    must not perturb `doctor invocation`'s own output — the exhaustive
    byte-level pins for THAT verb live in `test_doctor_invocation.py`;
    this is a narrow smoke check that the shared dispatcher still routes
    correctly."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    rc = cli_mod.main(["doctor", "invocation"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("doctor: INFO switches") or "doctor: " in out
    assert "worker.coalesce_secs" not in out  # the settings rows must not leak in


def test_cli_doctor_unknown_verb_still_rejected(monkeypatch):
    rc = cli_mod.main(["doctor", "bogus"])
    assert rc == 2


# ===================================================================== #
# Consumer rewires: one direct test per rewired public function,
# proving config.yaml actually reaches the REAL call site (not just
# resolve_setting in isolation).
# ===================================================================== #


def test_worker_coalesce_secs_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "worker", "coalesce_secs", 42.0)
    assert worker.coalesce_secs(home) == 42.0


def test_worker_invoke_timeout_secs_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "worker", "invoke_timeout_secs", 111.0)
    assert worker.invoke_timeout_secs(home) == 111.0


def test_worker_repair_timeout_secs_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "worker", "repair_timeout_secs", 55.0)
    assert worker.repair_timeout_secs(home) == 55.0


def test_worker_autokick_disabled_reads_config(tmp_path):
    home = tmp_path / "home"
    assert worker._autokick_disabled(home) is False  # default: enabled
    _write_config(home, "worker", "autokick", False)
    assert worker._autokick_disabled(home) is True


def test_worker_notifications_suppressed_reads_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    assert worker._notifications_suppressed() is False  # default
    _write_config(home, "worker", "no_notify", True)
    assert worker._notifications_suppressed() is True


def test_worker_run_repair_kill_switch_reads_config(env, sdk_fake_worker, monkeypatch):
    """The ONE inline rewire (`worker.run`'s `repairs_enabled` line) that
    has no standalone public function to call directly — driven through
    a REAL `worker.run()`, mirroring `test_repair.py::test_b9_kill_
    switch_disables_composition`'s env-driven shape byte for byte,
    substituting `worker.repair: false` in config.yaml for
    `SELF_LEARN_REPAIR=0`.

    M-3 (review 2026-09-01): the disabled-round log line now names the
    ACTUAL source that resolved to False — this test's own config-only
    setup must see `config:worker.repair`, never the hardcoded env
    spelling the pre-fix log line always printed regardless of source
    (which this exact test, pinning that wrong text, used to hide)."""
    rid = seed_pending(env)
    _write_config(env.home, "worker", "repair", False)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair round disabled (config:worker.repair)" in log_text
    assert sdk_fake_worker["count"]() == 1  # one invocation only — the repair round never ran


def test_miner_cap_for_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "miner", "cap_per_session", 3)
    _write_config(home, "miner", "cap_max", 100)
    assert miner.cap_for(10, home=home) == 30  # 3 * 10, well under the 100 ceiling


def test_miner_pending_gate_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "miner", "pending_gate", 9)
    assert miner.pending_gate(home=home) == 9


def test_miner_run_threads_its_own_home_to_pending_gate_and_cap_for(tmp_path, monkeypatch):
    """MINOR-1 (review r2 2026-09-01): `miner.run(home)`'s internal
    `pending_gate()`/`cap_for()` calls must resolve against THIS run's
    `home`, not `resolve_home()`'s ambient `SELF_LEARN_HOME` -- the two
    tests above both pass `home=` explicitly and so can never observe a
    regression here; this drives the DEFAULT path (no `home=` at either
    call site) through a REAL `miner.run()`, spying on what `home` each
    one actually received. `other_home` (via `SELF_LEARN_HOME`) and
    `real_home` (passed to `run()`) are deliberately DIFFERENT
    directories, so a build that read the wrong one is caught by
    identity, not by a coincidentally-matching value."""
    real_home = make_home(tmp_path / "real")
    other_home = tmp_path / "other"
    other_home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(other_home))
    transcripts_root = tmp_path / "transcripts"
    (transcripts_root / "-home-u-proj").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(transcripts_root))
    miner._save_cursors({"__initialized__": "test-fixture"})
    write_transcript(transcripts_root, "sess-e2e", [miner_u("work"), miner_a("found the cause")])
    shim_reader(monkeypatch, {"candidates": [miner_candidate()], "fires": []})
    monkeypatch.setattr(miner.worker, "kick", lambda h, **kw: "spawned")

    captured: dict[str, object] = {}
    orig_gate = miner.pending_gate
    orig_cap = miner.cap_for

    def spy_gate(*, home=None):
        captured["gate_home"] = home
        return orig_gate(home=home)

    def spy_cap(n, *, home=None):
        captured["cap_home"] = home
        return orig_cap(n, home=home)

    monkeypatch.setattr(miner, "pending_gate", spy_gate)
    monkeypatch.setattr(miner, "cap_for", spy_cap)
    miner.run(real_home, trigger="timer")
    assert captured["gate_home"] == real_home
    assert captured["cap_home"] == real_home
    assert captured["gate_home"] != other_home
    assert captured["cap_home"] != other_home


def test_miner_transcripts_root_reads_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    custom = tmp_path / "custom-transcripts"
    _write_config(home, "miner", "transcripts_dir", str(custom))
    assert miner.transcripts_root() == custom


def test_miner_run_enabled_kill_switch_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "miner", "enabled", False)
    result = miner.run(home)
    assert result.status == "disabled"


def test_miner_maybe_kick_autokick_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "miner", "autokick", False)
    assert miner.maybe_kick(home) == "disabled"


def test_miner_stale_enabled_kill_switch_reads_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    # No `miner.last-run` marker anywhere in this fresh cache -> "infinitely
    # old" -> stale() would be True if mining were enabled; the config
    # kill switch must still force False.
    _write_config(home, "miner", "enabled", False)
    assert miner.stale() is False


def test_analyst_timeout_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "analyst", "timeout_secs", 77.0)
    assert analyst._timeout(home) == 77.0


def test_backend_max_turns_for_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "sdk", "max_turns.worker", 150)
    assert backend_mod._max_turns_for("WORKER", home=home) == 150


def test_backend_max_budget_usd_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "sdk", "max_budget_usd", 12.5)
    assert backend_mod._max_budget_usd(home=home) == 12.5


def test_events_prune_event_logs_reads_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _write_config(home, "sdk", "event_logs", 1)
    cache = worker.cache_dir()
    for i in range(3):
        p = cache / f"worker.tool-events.run-{i}.jsonl"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (i, i))
    events_mod.prune_event_logs("worker")
    remaining = sorted(cache.glob("worker.tool-events.*.jsonl"))
    assert len(remaining) == 1
    assert remaining[0].name == "worker.tool-events.run-2.jsonl"  # newest kept


def test_serve_tick_secs_from_env_reads_config(tmp_path):
    home = tmp_path / "home"
    _write_config(home, "serve", "tick_secs", 15.0)
    assert serve.tick_secs_from_env(home=home) == 15.0


def test_serve_tick_secs_from_env_custom_default_still_honoured(tmp_path):
    """`default=` stays a real override when neither env nor config.yaml
    answers — proving the `dataclasses.replace` path, not just the
    registry's own baked-in default."""
    home = tmp_path / "home"
    home.mkdir()
    assert serve.tick_secs_from_env(123.0, home=home) == 123.0


def test_telemetry_actor_reads_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _write_config(home, "ledger", "actor", "config-actor")
    assert telemetry.actor() == "config-actor"


def test_ledger_ops_glob_probe_budget_s_reads_config(tmp_path):
    """M-5 (review 2026-09-01): `SELF_LEARN_GLOB_PROBE_BUDGET_S` was
    reclassified operator-facing because the shipped refusal message
    already tells a human to raise it."""
    home = tmp_path / "home"
    _write_config(home, "ledger", "glob_probe_budget_s", 5.0)
    assert ledger_ops_mod._glob_probe_budget_s(home) == 5.0


def test_verbs_glob_probe_budget_display_agrees_with_the_probe(tmp_path):
    """The invariant `_glob_probe_budget_display`'s own docstring names:
    the refusal text must never disagree with the probe that produced
    it. Both must read the SAME registry entry, so a config.yaml value
    changes both together."""
    home = tmp_path / "home"
    _write_config(home, "ledger", "glob_probe_budget_s", 5.0)
    assert verbs_mod._glob_probe_budget_display(home) == "5"
    assert ledger_ops_mod._glob_probe_budget_s(home) == 5.0
