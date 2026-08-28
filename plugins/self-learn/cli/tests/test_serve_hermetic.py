"""U-servehermetic -- `serve.unit_dir()`'s resolution order, guarded
directly (not merely through `SUP2`/`SUP4`'s `SELF_LEARN_SERVE_UNIT_DIR`-
prefixed legs in `test_serve.py`, which never exercised the fallback that
actually broke).

THE DEFECT (measured 2026-08-27): `serve.unit_dir()` fell back straight
from `SELF_LEARN_SERVE_UNIT_DIR` to the REAL `~/.config/systemd/user`,
skipping `$XDG_CONFIG_HOME` -- while the heartbeat it is compared against
came from the hermetic cache (`XDG_CACHE_HOME`, redirected by every test
via `conftest.py`'s autouse `_worker_test_defaults`). Once a real host
unit was linked (`self-learn-host.service`, 2026-08-27), any test that
did not remember to set `SELF_LEARN_SERVE_UNIT_DIR` itself started
reading that REAL unit as "configured", with no heartbeat ever written
into the (correctly hermetic) cache -- 18 tests across six files failed,
all sharing the same underlying assumption: `self-learn doctor
invocation` exits 0 with no FAIL row on a pristine home.

THE FIX: `serve.unit_dir()` now resolves the way systemd itself resolves
the user unit search path -- `SELF_LEARN_SERVE_UNIT_DIR` (explicit
override) -> else `$XDG_CONFIG_HOME/systemd/user` if `XDG_CONFIG_HOME`
is set -> else the real `~/.config/systemd/user` -- and `conftest.py`
sets `XDG_CONFIG_HOME` to a fresh `tmp_path` subdir for EVERY test,
mirroring the pre-existing `XDG_CACHE_HOME` line right above it.

Tests (a)-(c) below assert the resolver directly and are host-
independent by construction (they pin `serve.unit_dir()` itself against
a fixture path, never against "whatever is linked on the real host").
Test (d) is the end-to-end regression pin: it exercises exactly the
`self-learn doctor invocation` call the six previously-failing files
each made, under nothing but the DEFAULT (autouse) conftest fixture --
no manual `SELF_LEARN_SERVE_UNIT_DIR` prefix -- on THIS host, where
`self-learn-host.service` really is linked.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from self_learn import cli as cli_mod
from self_learn import provider, serve, worker


def _home(tmp_path, monkeypatch, *, xdg_cache: str | None = None) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", xdg_cache or str(tmp_path / "cache"))
    return home


def test_hm_a_positive_control_xdg_config_home_governs_unit_dir_resolution(tmp_path, monkeypatch):
    """(a) POSITIVE CONTROL. Point `XDG_CONFIG_HOME` at a tmp dir, prove
    `serve.unit_dir()` resolves under it (not under the real
    `~/.config`), drop a fake unit file there, write a fresh heartbeat
    into the (already-hermetic) cache, and confirm the doctor row reads
    PASS -- proving the resolver genuinely reads the fixture dir end to
    end, not merely that a path equality happens to hold.

    MUTATION that turns this red: revert `serve.unit_dir()` to
    `Path.home() / ".config" / "systemd" / "user"` (drop the
    `XDG_CONFIG_HOME` fallback leg entirely) -- red EVERYWHERE this test
    runs, not just on a host with the reference unit linked, because the
    `serve.unit_dir() == expected_unit_dir` assertion below never depends
    on what the real host happens to have."""
    home = _home(tmp_path, monkeypatch)
    monkeypatch.delenv("SELF_LEARN_SERVE_UNIT_DIR", raising=False)
    xdg_config_home = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))

    expected_unit_dir = xdg_config_home / "systemd" / "user"
    assert serve.unit_dir() == expected_unit_dir

    expected_unit_dir.mkdir(parents=True, exist_ok=True)
    (expected_unit_dir / "self-learn-host.service").write_text("x")
    assert serve.is_configured() is True

    cache_dir = worker.cache_dir()
    serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)

    rows = provider.preflight(home)
    row = next(r for r in rows if r.name == "serve")
    assert row.verdict == "PASS", row.detail


def test_hm_b_empty_fixture_dir_reads_unconfigured_regardless_of_the_real_host(tmp_path, monkeypatch):
    """(b) NEGATIVE CONTROL. `XDG_CONFIG_HOME` points at a tmp dir that
    stays EMPTY -- no unit file dropped anywhere under it. This asserts
    NOTHING about the real host's `~/.config/systemd/user/self-learn-
    host.service` (which really is linked on this host, 2026-08-27, per
    the defect this unit fixes); it only proves the fixture dir governs
    resolution independent of that fact.

    MUTATION that turns this red: the same `Path.home()`-only revert as
    (a) -- but THIS test only goes red on a host where the real unit is
    actually linked (this host, right now). That asymmetry is exactly
    why the defect was invisible to the U-engine Phase 2 gate: that gate
    ran before any host had linked the unit, so `unit_dir()` reading the
    real (then-empty) `~/.config/systemd/user` looked identical to
    reading a hermetic fixture."""
    home = _home(tmp_path, monkeypatch)
    monkeypatch.delenv("SELF_LEARN_SERVE_UNIT_DIR", raising=False)
    xdg_config_home = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    # Deliberately create nothing under xdg_config_home.

    assert serve.is_configured() is False

    rows = provider.preflight(home)
    row = next(r for r in rows if r.name == "serve")
    assert row.verdict == "SKIP", row.detail


def test_hm_c_self_learn_serve_unit_dir_override_still_wins_over_xdg_config_home(tmp_path, monkeypatch):
    """(c) `SELF_LEARN_SERVE_UNIT_DIR` (explicit override, kept from
    before this fix) must still win over the new `XDG_CONFIG_HOME`
    fallback leg. A decoy, "configured-looking" unit file sits under
    `XDG_CONFIG_HOME`'s `systemd/user` -- if the resolver consulted it at
    all, `is_configured()` would read True. It must not: the override
    points at a genuinely empty dir, so `unit_dir()` resolves there and
    `is_configured()` reads False, proving the decoy is never even
    looked at.

    MUTATION that turns this red: check `XDG_CONFIG_HOME` before
    `SELF_LEARN_SERVE_UNIT_DIR` (swap the two branches' priority) -- red
    everywhere, since the decoy would then be found."""
    _home(tmp_path, monkeypatch)

    xdg_config_home = tmp_path / "xdg-config"
    decoy_unit_dir = xdg_config_home / "systemd" / "user"
    decoy_unit_dir.mkdir(parents=True)
    (decoy_unit_dir / "self-learn-host.service").write_text("decoy")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))

    override_dir = tmp_path / "override-unitdir"
    override_dir.mkdir()
    monkeypatch.setenv("SELF_LEARN_SERVE_UNIT_DIR", str(override_dir))

    assert serve.unit_dir() == override_dir
    assert serve.is_configured() is False


def test_hm_d_default_conftest_now_matches_the_previously_failing_files_shared_assumption(capsys):
    """(d) END-TO-END REGRESSION PIN. `test_doctor_invocation.py::test_
    dc1_pristine_home_zero_fail_all_rows_once` (and five sibling files --
    `test_selftest.py`, `test_hosting.py`, `test_lifecycle_cli.py`,
    `test_new_skill.py`, `test_selftest_hooks.py`) each share one
    assumption: `self-learn doctor invocation` on a pristine home exits 0
    with no FAIL row. This test exercises exactly that call under
    nothing but the DEFAULT (autouse) `conftest.py` fixture -- no
    `SELF_LEARN_SERVE_UNIT_DIR` prefix, no per-test override of any kind
    -- on THIS host, where `self-learn-host.service` really is linked
    (2026-08-27).

    MUTATION that turns this red: delete the `XDG_CONFIG_HOME` line
    added to `conftest.py`'s `_worker_test_defaults` (next to the
    pre-existing `XDG_CACHE_HOME` line). Red ONLY on a host with the
    reference unit linked (this one) -- a clean host without the unit
    would still read SKIP and this test would not catch the regression
    there; (a)/(b)/(c) above cover the resolver itself host-
    independently for that reason."""
    rc = cli_mod.main(["doctor", "invocation"])
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("doctor: ") and "---" not in ln and "handoff" not in ln]
    assert rc == 0, out
    for ln in lines:
        assert " FAIL " not in ln, ln
