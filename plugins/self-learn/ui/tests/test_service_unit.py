"""Unit-file tests for ``systemd/self-learn-ui.service`` (10 §1
"Service" row; task U7). Static content assertions only — parsing the
file textually (no ``systemd-analyze``/systemctl dependency, so this
suite runs the same on a non-systemd host) — mirroring
``test_wrapper.py``'s "static checks only" posture in this same package.

Also asserts PARITY with ``systemd/self-learn-miner.service`` on the
conventions 10 §1 explicitly pins this unit to mirror: %h-relative
paths, the B-1 explicit env pin (systemd user managers don't inherit
the shell's env), and the registration-block comment style.
"""

from __future__ import annotations

from pathlib import Path

UI_UNIT = (
    Path(__file__).resolve().parents[4] / "systemd" / "self-learn-ui.service"
)
MINER_UNIT = (
    Path(__file__).resolve().parents[4] / "systemd" / "self-learn-miner.service"
)


def _section(text: str, name: str) -> str:
    """Extract one INI-style [Section] block's raw body."""
    marker = f"[{name}]"
    start = text.index(marker) + len(marker)
    rest = text[start:]
    end = len(rest)
    for other in ("[Unit]", "[Service]", "[Timer]", "[Install]"):
        if other == marker:
            continue
        idx = rest.find(f"\n{other}")
        if idx != -1:
            end = min(end, idx)
    return rest[:end]


def test_unit_file_exists() -> None:
    assert UI_UNIT.is_file(), f"missing unit at {UI_UNIT}"


def test_miner_unit_exists_for_parity_checks() -> None:
    # Sanity guard: if this ever goes missing, the parity tests below
    # would silently pass on an empty comparison — fail loudly instead.
    assert MINER_UNIT.is_file(), f"missing precedent unit at {MINER_UNIT}"


# --- pinned fields (10 §1 "Service" row) --------------------------------


def test_exec_start_is_pinned() -> None:
    content = UI_UNIT.read_text(encoding="utf-8")
    service = _section(content, "Service")
    assert "ExecStart=%h/bin/self-learn-ui serve" in service


def test_restart_on_failure_is_pinned() -> None:
    content = UI_UNIT.read_text(encoding="utf-8")
    service = _section(content, "Service")
    assert "Restart=on-failure" in service


def test_description_present_in_unit_section() -> None:
    content = UI_UNIT.read_text(encoding="utf-8")
    unit = _section(content, "Unit")
    assert "Description=" in unit


def test_install_section_present_for_direct_enable() -> None:
    """09 §3/10 §1: "enable stays a documented manual line
    (systemctl --user enable --now self-learn-ui.service)" — unlike the
    miner (enabled only via its .timer), THIS unit is enabled directly,
    so it needs a [Install] WantedBy= target for `enable` to do
    anything."""
    content = UI_UNIT.read_text(encoding="utf-8")
    assert "[Install]" in content
    install = _section(content, "Install")
    assert "WantedBy=" in install


def test_registration_documented_in_a_comment() -> None:
    content = UI_UNIT.read_text(encoding="utf-8")
    header = content.split("[Unit]")[0]
    assert "systemctl --user enable --now self-learn-ui.service" in header


# --- parity with self-learn-miner.service (10 §1: "conventions
# mirroring self-learn-miner.service") -----------------------------------


def test_execstart_is_h_relative_like_the_miner_unit() -> None:
    ui_service = _section(UI_UNIT.read_text(encoding="utf-8"), "Service")
    miner_service = _section(MINER_UNIT.read_text(encoding="utf-8"), "Service")
    assert "%h/bin/" in ui_service
    assert "%h/bin/" in miner_service


def test_carries_the_same_b1_env_pin_as_the_miner_unit() -> None:
    """B-1 (doc 13 §7.1), carried: the systemd user manager does not
    inherit the shell's env — both units pin SELF_LEARN_HOME
    explicitly rather than relying on ambient environment."""
    ui_service = _section(UI_UNIT.read_text(encoding="utf-8"), "Service")
    miner_service = _section(MINER_UNIT.read_text(encoding="utf-8"), "Service")
    assert "Environment=SELF_LEARN_HOME=%h/.self-learn" in ui_service
    assert "Environment=SELF_LEARN_HOME=%h/.self-learn" in miner_service


def test_both_units_document_manual_registration_via_symlink() -> None:
    ui_header = UI_UNIT.read_text(encoding="utf-8").split("[Unit]")[0]
    miner_header = MINER_UNIT.read_text(encoding="utf-8").split("[Unit]")[0]
    for header in (ui_header, miner_header):
        assert "ln -sf" in header
        assert "daemon-reload" in header


def test_both_units_have_a_description() -> None:
    for unit_path in (UI_UNIT, MINER_UNIT):
        section = _section(unit_path.read_text(encoding="utf-8"), "Unit")
        assert "Description=" in section
