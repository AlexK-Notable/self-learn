"""M-N -- the doctor `ui` row (`provider._ui_row`), `self-learn-ui.
service`'s sibling to `_serve_row`'s host-unit check (`Doc-g`), minus
the heartbeat legs: the UI service writes no heartbeat (10 §1; U7), so
this row can only report linked/enabled state, and says so.

Template: `test_serve.py`'s `test_sup4_*` / `test_serve_hermetic.py`'s
`test_hm_*` -- the same `SELF_LEARN_SERVE_UNIT_DIR` + `unit_dir()`
fixture pattern (a fake unit file, optionally a `<target>.wants/` entry
for `is_enabled`), just without any heartbeat setup, since this row
never reads one.

Also covers `serve.is_configured(unit_name)` (M-N: generalized from a
hardcoded `self-learn-host.service` to take any unit name) directly,
for both the host and UI units.
"""

from __future__ import annotations

import subprocess

from self_learn import provider, serve


def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    unit_dir = tmp_path / "unitdir"
    monkeypatch.setenv("SELF_LEARN_SERVE_UNIT_DIR", str(unit_dir))
    return home


def _ui_row(home):
    rows = provider.preflight(home)
    return next(r for r in rows if r.name == "ui")


def test_ui_row_not_linked_skips(tmp_path, monkeypatch):
    """No `self-learn-ui.service` file anywhere under `unit_dir()` ->
    SKIP, mirroring `_serve_row`'s unconfigured leg.

    MUTATION that turns this red: have `_ui_row` call
    `serve.is_configured()` (the bare host-unit default) instead of
    `serve.is_configured("self-learn-ui.service")` -- this test's
    unit_dir is genuinely empty either way, so this particular test
    would not itself catch that swap; see
    `test_ui_row_linked_but_not_enabled_warns` and
    `test_ui_row_linked_and_enabled_passes` below for the mutations that
    do. (Gate r1 NIT: this docstring previously named
    `test_is_configured_distinguishes_host_and_ui_units` instead -- that
    test exercises `serve.is_configured` directly and never calls
    `_ui_row`, so it passes untouched under this mutation.)"""
    home = _home(tmp_path, monkeypatch)
    # Deliberately create nothing under unit_dir.
    row = _ui_row(home)
    assert row.verdict == "SKIP", row.detail
    assert "self-learn-ui.service" in row.detail


def test_ui_row_linked_but_not_enabled_warns(tmp_path, monkeypatch):
    """Unit file present but no `default.target.wants/` entry -> WARN,
    never PASS/FAIL/SKIP.

    MUTATION that turns this red: swap the WARN/PASS branches in
    `_ui_row` (report PASS when not enabled) -- this test would then
    see verdict == "PASS" and fail."""
    home = _home(tmp_path, monkeypatch)
    unit_dir = serve.unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "self-learn-ui.service").write_text("x")

    assert serve.is_configured("self-learn-ui.service") is True
    row = _ui_row(home)
    assert row.verdict == "WARN", row.detail
    assert "no heartbeat" in row.detail.lower()


def test_ui_row_linked_and_enabled_passes(tmp_path, monkeypatch):
    """Unit file present AND a `default.target.wants/` symlink-
    equivalent -> PASS, and the detail says plainly that this is a
    state-only check (no heartbeat is written by this unit).

    MUTATION that turns this red: drop the `enabled` check entirely and
    always PASS once `is_configured` is true -- `test_ui_row_linked_
    but_not_enabled_warns` above would then also read PASS, but to pin
    THIS test's own direction: swap PASS<->WARN in `_ui_row` and this
    verdict becomes "WARN"."""
    home = _home(tmp_path, monkeypatch)
    unit_dir = serve.unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "self-learn-ui.service").write_text("x")
    (unit_dir / "default.target.wants").mkdir(parents=True, exist_ok=True)
    (unit_dir / "default.target.wants" / "self-learn-ui.service").write_text("x")

    row = _ui_row(home)
    assert row.verdict == "PASS", row.detail
    assert "no heartbeat" in row.detail.lower()


def test_is_configured_distinguishes_host_and_ui_units(tmp_path, monkeypatch):
    """`serve.is_configured` (M-N) takes a unit name -- was hardcoded to
    `self-learn-host.service`. Only the host unit file is dropped; the
    UI unit must independently read as unconfigured, and the bare
    default-argument call must keep pointing at the host unit (every
    pre-existing caller relies on that default unchanged).

    MUTATION that turns this red: revert `is_configured` to ignore its
    argument and always check `self-learn-host.service` -- the second
    assertion (`is_configured("self-learn-ui.service") is False`) would
    then read True instead, since the host unit file the test drops
    would satisfy the hardcoded check regardless of the name asked
    for."""
    _home(tmp_path, monkeypatch)
    unit_dir = serve.unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "self-learn-host.service").write_text("x")

    assert serve.is_configured("self-learn-host.service") is True
    assert serve.is_configured("self-learn-ui.service") is False
    assert serve.is_configured() is True  # default keeps pointing at the host unit
