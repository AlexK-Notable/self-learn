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
    assert payload == {
        "buckets": [],
        "total_pending": 0,
        "open_followups": 0,
        "worker_last_run": None,
    }


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


# (teach stub removed at T5; verbs/push/sentinel at T8; import/proposal at
# T11 — all real now: test_teach.py, test_route_cli.py, test_import_cli.py,
# test_proposal_validate.py, test_selftest.py.)


def test_argparse_errors_return_2_not_systemexit(sandbox_home, capsys):
    # main() is an int-returning API: argparse-level failures (bad choice,
    # missing required group) come back as argparse's own 2, never as an
    # escaping SystemExit. (Deliberate CLI usage errors exit 64 — EX_USAGE —
    # so machine consumers never see them aliased onto pinned exit-2s.)
    assert cli.main(["sentinel", "bogus"]) == 2  # argparse choice error — argparse owns this exit
    assert cli.main(["import"]) == 2  # argparse missing-group error


def test_no_command_prints_help_is_usage_error(sandbox_home, capsys):
    rc = cli.main([])
    assert rc == 64
    assert "usage:" in capsys.readouterr().err
