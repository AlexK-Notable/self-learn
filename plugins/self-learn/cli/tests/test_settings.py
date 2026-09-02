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
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import analyst, miner, serve, settings, telemetry, worker
from self_learn import cli as cli_mod
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import events as events_mod

from test_worker import env, sdk_fake_worker, seed_pending  # noqa: F401 -- fixtures resolved by name
from test_repair import _defect_script, _t4_missing_target  # noqa: F401


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
_ALL_NAMES = [s.name for s in settings.REGISTRY]


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


def test_by_name_raises_for_an_unknown_key():
    with pytest.raises(KeyError):
        settings.by_name("not-a-real-setting")


# ===================================================================== #
# The precedence chain, generically over every registry entry
# ===================================================================== #


@pytest.mark.parametrize("name", _ALL_NAMES)
def test_default_when_nothing_set(name, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    setting = settings.by_name(name)
    value, source = settings.resolve_setting(home, setting)
    assert value == _default_value(setting)
    assert source == "default"


@pytest.mark.parametrize("name", _ALL_NAMES)
def test_config_beats_default(name, tmp_path):
    home = tmp_path / "home"
    setting = settings.by_name(name)
    override = _valid_override(setting)
    _write_config(home, setting.config_section, setting.config_key, override)
    value, source = settings.resolve_setting(home, setting)
    assert value == override
    assert source == f"config:{setting.config_section}.{setting.config_key}"


@pytest.mark.parametrize("name", _ALL_NAMES)
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
    matches `provider.py`'s `_resolve_str_setting` precedent (`if
    value:`, not `if value is not None:`)."""
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
    `SELF_LEARN_REPAIR=0`."""
    rid = seed_pending(env)
    _write_config(env.home, "worker", "repair", False)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair round disabled (SELF_LEARN_REPAIR=0)" in log_text
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
