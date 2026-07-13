"""T11: `self-learn --selftest` — loud PASS/FAIL installation checks.

Checks (08 §3 T11 row; marker check per 02 §4): (a) capture path via a
scratch record, (b) compiler dry-run (in-memory, no writes), (c) marker
check — only targets that SHOULD have a section (≥1 routed record) are
flagged, (d) sentinel writability (real cache path resolution, XDG-
redirected here), (e) worker check stubbed M2-conditional.

DoD: green on a healthy sandbox; loud + non-zero on a sabotaged marker;
clean refusal on a missing home.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import cli, sentinel
from self_learn.compilers import BEGIN_MARKER, END_MARKER, compile_managed_file

from support import make_behavior, make_home

SKILL_MD = "# s skill\n\nAuthored prose stays put.\n"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel probes go to a per-test XDG cache, never the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    return h


def routed_record(record_id: str = "lrn-0a1b2c3d", destination: str = "skill-md"):
    record = make_behavior(scope="skill:s", record_id=record_id)
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": destination, "by": "human"}
    )
    record.set_status("routed")
    return record


def seed_routed_skill_target(home: Path) -> Path:
    """A resolved routed record + its compiled SKILL.md (markers present)."""
    skill_dir = home / "plugins" / "s-plugin" / "skills" / "s"
    resolved = skill_dir / ".self-learn" / "resolved"
    resolved.mkdir(parents=True)
    record = routed_record()
    record.write(resolved / f"{record.id}.md")
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(SKILL_MD, encoding="utf-8")
    compile_managed_file(skill_md, [record])  # bootstraps the marker pair
    return skill_md


# ----------------------------------------------------------------- healthy


def test_selftest_green_on_healthy_sandbox(home, capsys):
    skill_md = seed_routed_skill_target(home)
    assert BEGIN_MARKER in skill_md.read_text(encoding="utf-8")

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "FAIL" not in out
    for check in ("capture", "compiler", "markers", "sentinel"):
        assert f"PASS {check}" in out
    assert "worker: M2 — not checked" in out


def test_selftest_green_on_empty_home(home, capsys):
    # No buckets, no routed records: nothing should have a section yet.
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert "FAIL" not in capsys.readouterr().out


def test_selftest_leaves_no_scratch_litter(home, capsys):
    seed_routed_skill_target(home)
    assert cli.main(["--selftest"]) == 0
    leftovers = [p for p in home.rglob("*") if "selftest" in p.name.lower()]
    assert leftovers == []


def test_selftest_compiler_dry_run_writes_nothing(home, capsys):
    skill_md = seed_routed_skill_target(home)
    before = skill_md.read_bytes()
    assert cli.main(["--selftest"]) == 0
    assert skill_md.read_bytes() == before


# --------------------------------------------------------------- sabotage


def test_sabotaged_marker_fails_loud_naming_the_file(home, capsys):
    skill_md = seed_routed_skill_target(home)
    text = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(text.replace(END_MARKER + "\n", ""), encoding="utf-8")

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_target_missing_markers_entirely_fails(home, capsys):
    skill_md = seed_routed_skill_target(home)
    skill_md.write_text(SKILL_MD, encoding="utf-8")  # markers gone

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_target_file_missing_fails(home, capsys):
    skill_md = seed_routed_skill_target(home)
    skill_md.unlink()
    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_unrouted_targets_are_not_flagged(home, capsys):
    # A markerless SKILL.md with NO routed records must not fail: 02 §4's
    # bootstrap rule covers first-route targets.
    skill_dir = home / "plugins" / "s-plugin" / "skills" / "s"
    skill_dir.joinpath("SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (skill_dir / ".self-learn" / "pending").mkdir(parents=True)
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert "FAIL" not in capsys.readouterr().out


# ---------------------------------------------------------------- sentinel


def test_selftest_leaves_a_live_foreign_sentinel_in_place(home, capsys):
    hold = sentinel.hold()  # another flow's live hold (e.g. slash review)
    assert hold.owned

    rc = cli.main(["--selftest"])

    assert rc == 0
    assert sentinel.sentinel_path().exists()  # never deleted a live hold
    assert "PASS sentinel" in capsys.readouterr().out


def test_selftest_probe_sentinel_is_released(home, capsys):
    assert not sentinel.sentinel_path().exists()
    assert cli.main(["--selftest"]) == 0
    assert not sentinel.sentinel_path().exists()


# ------------------------------------------------------------ missing home


def test_missing_home_refuses_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "nowhere"))
    rc = cli.main(["--selftest"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "SELF_LEARN_HOME" in err or "nowhere" in err
