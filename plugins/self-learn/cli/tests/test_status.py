"""`self-learn status` behavior + subcommand stubs (T1 DoD)."""

import json

import pytest

from self_learn import cli


@pytest.fixture
def sandbox_home(monkeypatch, tmp_path):
    """An INITIALIZED but record-less ledger home — the legitimate zero
    state, and exactly what a fresh CLONE looks like: a git repo with
    hosts.yaml and no bucket dirs (git stores no empty dirs).

    A bare mkdir is NOT this: it is a broken home, and since the audit
    2026-07-16 BLOCKER 11 fix the read surfaces say so loudly rather than
    reporting a confident "0 pending" for a ledger nobody can see (see
    TestHomeState in test_hosting_fixes.py)."""
    from support import init_repo

    home = tmp_path / "ledger-home"
    init_repo(home)
    (home / "hosts.yaml").write_text("skills_root: null\nprojects: []\n", encoding="utf-8")
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
        "total_unreadable": 0,
        "open_followups": 0,
        "worker_last_run": None,
        # T19: supply mix + 04 success-metrics counters ride full status;
        # zero-state is honest — empty mix, null medians, never fake zeros.
        "supply_mix": {},
        "metrics": {
            "time_to_triage_median_days": None,
            "pending_total": 0,
            "pending_over_30d_pct": None,
            "routed_and_corrected": 0,
        },
    }


def test_status_counts_seeded_pending_record(monkeypatch, tmp_path, capsys):
    from self_learn.ledger_ops import create_record
    from support import make_behavior, make_env

    env = make_env(tmp_path, skills=("home-assistant",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    rec = make_behavior(scope="skill:home-assistant", record_id="lrn-0a1b2c3d")
    create_record(env.ledger, rec)

    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pending"] == 1
    assert payload["worker_last_run"] is None
    # make_env pre-creates the (empty) user/ bucket alongside the seeded one
    rows = {row["bucket"]: row for row in payload["buckets"]}
    assert set(rows) == {"home-assistant", "user"}
    assert rows["home-assistant"] == {
        "bucket": "home-assistant",
        "scope": "skill",
        "pending": 1,
        "oldest_days": 0,
        "unanalyzed": 1,  # no proposal sibling → eligible (08 §7.1 step 2)
        "unreadable": 0,
    }
    assert rows["user"]["pending"] == 0


# ---- 09 §5 FW-18: `status --json` unreadable count (full path only).


def _seed_valid_plus_corrupt(monkeypatch, tmp_path):
    """A home-assistant bucket with one VALID pending record plus two
    unreadable ones (a YAML-parse error and undecodable bytes). Returns
    the ledger home; SELF_LEARN_HOME is pointed at it."""
    from self_learn.ledger_ops import create_record
    from support import make_behavior, make_env

    env = make_env(tmp_path, skills=("home-assistant",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    path = create_record(
        env.ledger,
        make_behavior(scope="skill:home-assistant", record_id="lrn-0a1b2c3d"),
    )
    pending = path.parent
    (pending / "lrn-badya111.md").write_text(
        "---\nfoo: [unclosed\n---\nbody\n", encoding="utf-8"
    )
    (pending / "lrn-badby222.md").write_bytes(b"---\nid: \xff\xfe\n---\nbody\n")
    return env.ledger


def test_status_json_counts_unreadable_per_bucket_and_total(
    monkeypatch, tmp_path, capsys
):
    """Kill: drop `unreadable` from status_infos (or mis-sum the top-level
    total) and this reddens. The valid record still counts as pending; the
    two corrupt ones count ONLY as unreadable, never as pending."""
    _seed_valid_plus_corrupt(monkeypatch, tmp_path)
    rc = cli.main(["status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    rows = {r["bucket"]: r for r in payload["buckets"]}
    assert rows["home-assistant"]["pending"] == 1
    assert rows["home-assistant"]["unreadable"] == 2
    assert rows["user"]["unreadable"] == 0
    assert payload["total_unreadable"] == 2


def test_status_fast_omits_the_unreadable_field(monkeypatch, tmp_path, capsys):
    """08 §1 FW-18: `--fast` OMITS the field entirely — its frontmatter-only
    scan cannot detect the schema/section class, and absence ('unknown')
    beats a possibly-wrong zero. Kill: leak `unreadable`/`total_unreadable`
    into the fast payload and this reddens."""
    _seed_valid_plus_corrupt(monkeypatch, tmp_path)
    rc = cli.main(["status", "--json", "--fast"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "total_unreadable" not in payload
    for b in payload.get("buckets", []):
        assert "unreadable" not in b


def test_status_fast_does_not_crash_on_undecodable_bytes(
    monkeypatch, tmp_path, capsys
):
    """worker.fast_status's read_text catch widened to include
    UnicodeDecodeError (FW-18 crash-prevention). Kill: narrow it back to
    `except OSError:` and the decode error propagates → the fast scan
    crashes (rc != 0), reddening this. The valid record is still counted."""
    _seed_valid_plus_corrupt(monkeypatch, tmp_path)
    rc = cli.main(["status", "--json", "--fast"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pending"] == 1


def test_status_human_line_with_buckets(sandbox_home, capsys):
    # doc 13 §3: per-project bucket under projects/<slug>; scope renders as
    # plain "project" — the combined "project+user" scope is dead.
    (sandbox_home / "projects" / "-home-user-repos-x" / "pending").mkdir(
        parents=True
    )
    rc = cli.main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "self-learn: 0 pending across 1 bucket" in out
    assert "-home-user-repos-x (project)" in out


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
