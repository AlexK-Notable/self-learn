"""`self-learn status` behavior + subcommand stubs (T1 DoD)."""

import json

import pytest

from self_learn import cli


@pytest.fixture
def sandbox_home(monkeypatch, tmp_path):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    return home


def test_status_zero_state_human(sandbox_home, capsys):
    rc = cli.main(["status"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "self-learn: no buckets, 0 pending"


def test_status_zero_state_json_exact_shape(sandbox_home, capsys):
    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"buckets": [], "total_pending": 0, "worker_last_run": None}


def test_status_counts_seeded_pending_record(sandbox_home, capsys):
    from support import make_behavior

    pending = sandbox_home / "plugins" / "ha" / "skills" / "home-assistant" / ".self-learn" / "pending"
    pending.mkdir(parents=True)
    rec = make_behavior(scope="skill:home-assistant", record_id="lrn-0a1b2c3d")
    rec.write(pending / "lrn-0a1b2c3d.md")

    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pending"] == 1
    assert payload["worker_last_run"] is None
    assert payload["buckets"] == [
        {
            "bucket": "home-assistant",
            "scope": "skill",
            "pending": 1,
            "oldest_days": 0,
            "unanalyzed": 1,  # no proposal sibling → eligible (08 §7.1 step 2)
        }
    ]


def test_status_human_line_with_buckets(sandbox_home, capsys):
    (sandbox_home / ".self-learn" / "pending").mkdir(parents=True)
    rc = cli.main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "self-learn: 0 pending across 1 bucket" in out
    assert "project (project+user)" in out


@pytest.mark.parametrize(
    ("command", "task"),
    [
        # ("teach", …) removed at T5 — teach is real now (tests/test_teach.py)
        # (verbs / push / sentinel removed at T8 — real now, test_route_cli.py)
        ("import", "T9"),
        ("proposal", "T13"),
    ],
)
def test_stub_subcommands_exit_2(sandbox_home, capsys, command, task):
    rc = cli.main([command])
    assert rc == 2
    assert f"not built until {task}" in capsys.readouterr().err


def test_stub_subcommand_tolerates_extra_args(sandbox_home, capsys):
    rc = cli.main(["import", "--backlog", "home-assistant"])
    assert rc == 2
    assert "not built until T9" in capsys.readouterr().err


def test_selftest_stub_exits_0(sandbox_home, capsys):
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "selftest: not built until T11"


def test_no_command_prints_help_exits_2(sandbox_home, capsys):
    rc = cli.main([])
    assert rc == 2
    assert "usage:" in capsys.readouterr().err
