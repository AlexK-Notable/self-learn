"""U-fw100 — FW-100's env-override half: the miner reader's session
timeout (`miner.INVOKE_TIMEOUT_SECS`, historically a bare module
constant with no override) gains `miner.reader_timeout_secs()`,
env-overridable via `SELF_LEARN_READER_TIMEOUT_SECS` with parsing,
validation, and fallback semantics IDENTICAL to the worker's own
`worker.invoke_timeout_secs()` / `worker.repair_timeout_secs()`. Since
2026-09-20 all three are settings-registry entries resolved by the one
`settings.resolve_setting` (before that they shared an env-only helper,
`worker._timeout_secs`, now removed). The `max_turns=60` reconciliation
half of FW-100 is untouched here (out of scope).

Every test below fails against the pre-change code; each docstring
names the specific line of the change it depends on. `test_reader_
contract.py`'s `reader_leg` fixture and its capture helpers are reused
for the wiring tests (`d`), same precedent as that file importing
`sdk_absent` from `test_invocation_sdk` rather than redefining it.
"""

from __future__ import annotations

from self_learn import miner, worker

from test_reader_contract import (  # noqa: F401 -- fixtures/helpers resolved by name
    _log_lines_added,
    _log_text,
    reader_leg,
)


# ===================================================================== #
# (a)-(c) -- the bare function: parsing, validation, fallback
# ===================================================================== #


def test_unset_env_uses_default_900(monkeypatch):
    """(a) Unset -> default 900.0 (15 * 60, miner.py's `INVOKE_TIMEOUT_
    SECS`). Fails pre-change: `miner.reader_timeout_secs` does not
    exist yet (AttributeError) -- depends on the new function
    definition in miner.py."""
    monkeypatch.delenv("SELF_LEARN_READER_TIMEOUT_SECS", raising=False)
    assert miner.reader_timeout_secs() == 900.0


def test_valid_override_parses(monkeypatch):
    """(b) A valid override parses. Fails pre-change the same way as
    (a) -- depends on `reader_timeout_secs()` existing and routing
    `SELF_LEARN_READER_TIMEOUT_SECS` through a real float() parse."""
    monkeypatch.setenv("SELF_LEARN_READER_TIMEOUT_SECS", "120")
    assert miner.reader_timeout_secs() == 120.0


def test_invalid_values_fall_back_to_default(monkeypatch):
    """(c) Mirrors `test_repair.py::test_e4_zero_or_garbage_timeout_
    falls_back` EXACTLY (same three raw values, same fallback -- never
    clamped to 0): 0, -5, and 'banana' each yield the default. Fails
    pre-change (AttributeError) -- depends on `reader_timeout_secs()`
    rejecting a value that is not above zero the way the worker's
    timeouts do, rather than a from-scratch (and possibly weaker) parse."""
    for raw in ("0", "-5", "banana"):
        monkeypatch.setenv("SELF_LEARN_READER_TIMEOUT_SECS", raw)
        assert miner.reader_timeout_secs() == miner.INVOKE_TIMEOUT_SECS, raw


def test_resolves_the_way_the_worker_timeouts_do(tmp_path, monkeypatch):
    """The point of the test this replaces (`test_shares_worker_helper_
    not_a_reimplementation`) was that the reader's timeout must not be
    parsed by a parallel copy that could drift from the worker's. It
    proved that by patching `worker._timeout_secs`, an env-only helper.
    On 2026-09-20 the timeout became the registry setting `miner.
    reader_timeout_secs` (the user's instruction: sizing parameters
    "can't be constants we just leave hardcoded in the code"), so all
    three timeouts now go through `settings.resolve_setting` and the
    helper is gone. What is checked here is the same property, stated
    for the new arrangement: the reader's timeout and the worker's two
    behave identically on every rung -- default, env, config.yaml over
    env, and a bad config value falling through to env."""
    from self_learn import settings

    home = tmp_path / "home.d"
    home.mkdir()
    readers = {
        "miner.reader_timeout_secs": miner.reader_timeout_secs,
        "worker.invoke_timeout_secs": worker.invoke_timeout_secs,
        "worker.repair_timeout_secs": worker.repair_timeout_secs,
    }
    for name, read in readers.items():
        setting = settings.by_name(name)
        section, key = setting.config_section, setting.config_key
        monkeypatch.delenv(setting.env_var, raising=False)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")
        assert read(home) == float(setting.default), name
        monkeypatch.setenv(setting.env_var, "41")
        assert read(home) == 41.0, name
        (home / "config.yaml").write_text(f"{section}:\n  {key}: 77\n", encoding="utf-8")
        assert read(home) == 77.0, name  # config.yaml outranks env (S-58)
        (home / "config.yaml").write_text(f"{section}:\n  {key}: -3\n", encoding="utf-8")
        assert read(home) == 41.0, name  # a bad config value falls through to env
        monkeypatch.setenv(setting.env_var, "banana")
        assert read(home) == float(setting.default), name


# ===================================================================== #
# (d) -- wiring: the override reaches the reader's real SessionSpec
# ===================================================================== #


def test_env_override_wires_into_reader_session_spec(reader_leg, monkeypatch):
    """(d), fast half: with `SELF_LEARN_READER_TIMEOUT_SECS` set, the
    reader's real `SessionSpec` (built by `miner._invoke_reader`)
    carries the overridden timeout. Uses a normal (non-hanging) drive
    so this stays fast -- the log-line half below, which needs a real
    timeout to actually fire, is the one that pays real wall-clock
    time. Fails pre-change: miner.py's `timeout=INVOKE_TIMEOUT_SECS`
    call site (hardcoded to the bare module constant) ignores this env
    var entirely, so `run.spec.timeout` would read 900 (the constant),
    not 37.0 -- depends on that call site now reading `reader_timeout_
    secs()` instead."""
    monkeypatch.setenv("SELF_LEARN_READER_TIMEOUT_SECS", "37")
    run = reader_leg.drive()
    assert run.spec.timeout == 37.0


def test_env_override_wires_into_reader_timeout_log_line(reader_leg, monkeypatch):
    """(d), log half: the rendered timeout-log line carries the SAME
    overridden value as the enforced timeout -- the two numbers cannot
    silently diverge. A small override (2s) keeps the real wait this
    test pays short (the `hang` scenario genuinely does not return
    until the real kill ladder fires at `spec.timeout` seconds).
    Mirrors `test_reader_contract.py`'s `test_to2`/`test_to3`,
    substituting an env override for their `monkeypatch.setattr(miner,
    "INVOKE_TIMEOUT_SECS", ...)`. Fails pre-change: `timeout_display=
    INVOKE_TIMEOUT_SECS` ignores the env var, so the rendered line
    would say '900.0s' -- and since `timeout=` is equally hardcoded
    pre-change, reaching that assertion at all would cost a real 900s
    wait, not the 2s this test actually pays post-change (verified by
    static inspection of the pre-change call sites, not a live 900s
    run -- see the build report)."""
    monkeypatch.setenv("SELF_LEARN_READER_TIMEOUT_SECS", "2")
    before = _log_text(reader_leg.home)
    reader_leg.arm_timeout()
    run = reader_leg.invoke()
    assert run.spec.timeout == 2.0
    assert run.outcome.failure == "timeout"
    added = _log_lines_added(before, _log_text(reader_leg.home))
    expected = "run: claude timed out after 2.0s"
    assert any(line.endswith(expected) for line in added), added


def test_env_unset_wiring_positive_control(reader_leg, monkeypatch):
    """Positive control for the wiring test above: with the env var
    unset, the real `SessionSpec` still carries the module default
    (900.0s) end to end -- proves the override test above is measuring
    the env var's effect specifically, not some fixture artifact that
    would report 37.0 regardless of what is set. (Passes on both sides
    of the change, by design -- unlike the override test, which fails
    pre-change.)"""
    monkeypatch.delenv("SELF_LEARN_READER_TIMEOUT_SECS", raising=False)
    run = reader_leg.drive()
    assert run.spec.timeout == 900.0
