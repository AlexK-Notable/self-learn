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
    pending = sandbox_home / "plugins" / "ha" / "skills" / "home-assistant" / ".self-learn" / "pending"
    pending.mkdir(parents=True)
    (pending / "lrn-0a1b2c3d.md").write_text("stub record\n")

    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pending"] == 1
    assert payload["worker_last_run"] is None
    assert payload["buckets"] == [
        {"bucket": "home-assistant", "scope": "skill", "pending": 1, "oldest_days": 0}
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
        ("teach", "T5"),
        ("route", "T7"),
        ("reject", "T7"),
        ("defer", "T7"),
        ("graduate", "T7"),
        ("supersede", "T7"),
        ("push", "T7"),
        ("sentinel", "T7"),
        ("import", "T9"),
        ("proposal", "T13"),
        ("list", "T3"),
    ],
)
def test_stub_subcommands_exit_2(sandbox_home, capsys, command, task):
    rc = cli.main([command])
    assert rc == 2
    assert f"not built until {task}" in capsys.readouterr().err


def test_stub_subcommand_tolerates_extra_args(sandbox_home, capsys):
    rc = cli.main(["teach", "some lesson", "--skill", "home-assistant"])
    assert rc == 2
    assert "not built until T5" in capsys.readouterr().err


def test_selftest_stub_exits_0(sandbox_home, capsys):
    rc = cli.main(["--selftest"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "selftest: not built until T11"


def test_no_command_prints_help_exits_2(sandbox_home, capsys):
    rc = cli.main([])
    assert rc == 2
    assert "usage:" in capsys.readouterr().err
