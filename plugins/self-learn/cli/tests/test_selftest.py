"""T11: `self-learn --selftest` — loud PASS/FAIL installation checks.

Checks (08 §3 T11 row; marker check per 02 §4; drift per doc 13 §4.2):
(a) capture path via a scratch record, (b) compiler dry-run (in-memory,
no writes), (c) marker check — only targets that SHOULD have a section
(≥1 routed record) are flagged, (d) hosts-aware drift check, (e) sentinel
writability (real cache path resolution, XDG-redirected here), (f) worker
check stubbed M2-conditional.

Targets resolve via hosts.yaml (doc 13): resolved records live in the
LEDGER home, the compiled SKILL.md lives in the registered HOST repo.

DoD: green on a healthy sandbox; loud + non-zero on a sabotaged marker;
clean refusal on a missing home.
"""

from __future__ import annotations

import pytest

from self_learn import cli, sentinel
from self_learn.compilers import BEGIN_MARKER, END_MARKER, compile_managed_file

from support import SKILL_MD_SEED, make_behavior, make_env

SKILL_MD = SKILL_MD_SEED.format(name="s")


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel probes go to a per-test XDG cache, never the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def routed_record(record_id: str = "lrn-0a1b2c3d", destination: str = "skill-md"):
    record = make_behavior(scope="skill:s", record_id=record_id)
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": destination, "by": "human"}
    )
    record.set_status("routed")
    return record


def seed_routed_skill_target(env):
    """A resolved routed record in the LEDGER + its compiled SKILL.md in
    the HOST (markers present). Returns the host-side SKILL.md path."""
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True)
    record = routed_record()
    record.write(resolved / f"{record.id}.md")
    compile_managed_file(env.skill_md, [record])  # bootstraps the marker pair
    return env.skill_md


# ----------------------------------------------------------------- healthy


def test_selftest_green_on_healthy_sandbox(env, capsys):
    skill_md = seed_routed_skill_target(env)
    assert BEGIN_MARKER in skill_md.read_text(encoding="utf-8")

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "FAIL" not in out
    for check in ("capture", "compiler", "markers", "drift", "sentinel"):
        assert f"PASS {check}" in out
    assert "worker: M2 — not checked" in out


def test_selftest_green_on_empty_home(env, capsys):
    # No routed records: nothing should have a section yet.
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert "FAIL" not in capsys.readouterr().out


def test_selftest_leaves_no_scratch_litter(env, capsys):
    seed_routed_skill_target(env)
    assert cli.main(["--selftest"]) == 0
    leftovers = [
        p for p in env.ledger.rglob("*") if "selftest" in p.name.lower()
    ]
    assert leftovers == []


def test_selftest_compiler_dry_run_writes_nothing(env, capsys):
    skill_md = seed_routed_skill_target(env)
    before = skill_md.read_bytes()
    assert cli.main(["--selftest"]) == 0
    assert skill_md.read_bytes() == before


# --------------------------------------------------------------- sabotage


def test_sabotaged_marker_fails_loud_naming_the_file(env, capsys):
    skill_md = seed_routed_skill_target(env)
    text = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(text.replace(END_MARKER + "\n", ""), encoding="utf-8")

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_target_missing_markers_entirely_fails(env, capsys):
    skill_md = seed_routed_skill_target(env)
    skill_md.write_text(SKILL_MD, encoding="utf-8")  # markers gone

    rc = cli.main(["--selftest"])

    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_target_file_missing_fails(env, capsys):
    skill_md = seed_routed_skill_target(env)
    skill_md.unlink()
    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "FAIL markers" in out
    assert str(skill_md) in out


def test_unrouted_targets_are_not_flagged(env, capsys):
    # A markerless host SKILL.md with NO routed records must not fail:
    # 02 §4's bootstrap rule covers first-route targets. (The seed
    # SKILL.md in the host is already markerless.)
    (env.ledger / "skills" / "s" / "pending").mkdir(parents=True)
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert "FAIL" not in capsys.readouterr().out


# ---------------------------------------------------------------- sentinel


def test_selftest_leaves_a_live_foreign_sentinel_in_place(env, capsys):
    hold = sentinel.hold()  # another flow's live hold (e.g. slash review)
    assert hold.owned

    rc = cli.main(["--selftest"])

    assert rc == 0
    assert sentinel.sentinel_path().exists()  # never deleted a live hold
    assert "PASS sentinel" in capsys.readouterr().out


def test_selftest_probe_sentinel_is_released(env, capsys):
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
