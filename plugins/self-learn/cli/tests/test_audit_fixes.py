"""Regression tests for the 2026-07-15 post-build audit batch.

Blocker: --env/--session values escaped the secret scan (worst case:
teach --route committed and pushed the secret). Minors: non-atomic
multi-file flush refusal, duplicate events after a crash re-flush,
report crash on schema-less telemetry lines, flush crash on a vanished
spool file, follow-ups surviving graduation, uncounted fallback capture.
"""

import json
import subprocess
from datetime import datetime, timezone

import pytest

from self_learn import cli, telemetry
from self_learn.ledger_ops import create_record, open_followups, write_proposal
from self_learn.records import MutationError, Record
from support import commit_all, git, make_behavior, make_env, proposal_dict

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


class Env:
    """doc-13 pair: `home` is the LEDGER; `bucket` its skill:s bucket;
    `skill_dir` the paired HOST skill dir (canon target)."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir  # HOST skill dir
        self.bucket = self.home / "skills" / "s"  # LEDGER skill bucket
        self.bare = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.bare)],
            check=True,
        )
        git(self.home, "remote", "add", "origin", str(self.bare))
        git(self.home, "push", "-q", "-u", "origin", "main")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


TEACH_BASE = [
    "teach", "--skill", "s", "--type", "knowledge", "--fact", "A clean fact.",
]


# ------------------------------------------ blocker: metadata scan coverage


def test_teach_env_value_secret_refused_nothing_written(env, capsys):
    rc = cli.main(TEACH_BASE + ["--env", f"apikey={AWS_KEY}"])
    assert rc == 3
    assert "refusing this write" in capsys.readouterr().err
    pending = env.bucket / "pending"
    assert not pending.exists() or not list(pending.glob("*.md"))


def test_teach_session_secret_refused(env, capsys):
    rc = cli.main(
        TEACH_BASE + ["--quote", "clean quote", "--session", AWS_KEY]
    )
    assert rc == 3
    assert "aws-key" in capsys.readouterr().err


def test_teach_route_env_secret_refused_nothing_committed(env, capsys):
    before = git(env.home, "rev-parse", "HEAD").stdout
    rc = cli.main(
        TEACH_BASE
        + ["--route", "--dest", "reference", "--env", f"apikey={AWS_KEY}"]
    )
    assert rc == 3
    assert git(env.home, "rev-parse", "HEAD").stdout == before
    resolved = env.bucket / "resolved"
    assert not resolved.exists() or not list(resolved.glob("*.md"))


# ------------------------------------- flush: all-or-nothing + robustness


NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
JUNE = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def test_multi_file_flush_is_all_or_nothing(env):
    telemetry.spool_event("offer-made", now=JUNE)  # clean, earlier month
    telemetry.spool_event("offer-made", now=NOW)
    bad = telemetry.spool_dir() / "2026-07.testhost.jsonl"
    with open(bad, "a", encoding="utf-8") as fh:
        fh.write(f'{{"kind":"capture","note":"apikey = {AWS_KEY}"}}\n')
    with pytest.raises(telemetry.ScanRefusal, match="WHOLE"):
        telemetry.flush(env.home)
    # NOTHING moved — including the clean June file (the tracked
    # telemetry plane is <home>/telemetry/ now; the dir exists but must
    # hold no flushed lines).
    assert not list((env.home / "telemetry").glob("*.jsonl"))
    june = telemetry.spool_dir() / "2026-06.testhost.jsonl"
    assert len(june.read_text().splitlines()) == 1


def test_flush_skips_vanished_spool_file(env):
    telemetry.spool_event("offer-made", now=NOW)
    dangling = telemetry.spool_dir() / "2026-05.gone.jsonl"
    dangling.symlink_to(telemetry.spool_dir() / "no-such-target")
    report = telemetry.flush(env.home)  # must not raise
    assert report.events == 1


def test_flush_heals_torn_trailing_line(env):
    tdir = telemetry.telemetry_dir(env.home)
    tdir.mkdir(parents=True, exist_ok=True)
    # a crashed append left a torn line with no newline
    (tdir / "2026-07.testhost.jsonl").write_text(
        '{"ts":"2026-07-15T01:00:00Z","kind":"cap', encoding="utf-8"
    )
    telemetry.spool_event("offer-made", now=NOW)
    telemetry.flush(env.home)
    lines = (tdir / "2026-07.testhost.jsonl").read_text().splitlines()
    assert len(lines) == 2  # torn line isolated, new event on its own line
    assert json.loads(lines[1])["kind"] == "offer-made"


def test_read_events_dedupes_reflushed_lines(env):
    tdir = telemetry.telemetry_dir(env.home)
    tdir.mkdir(parents=True, exist_ok=True)
    line = '{"ts":"2026-07-15T01:00:00Z","kind":"offer-made","actor":"x"}'
    (tdir / "2026-07.x.jsonl").write_text(f"{line}\n{line}\n")
    assert len(telemetry.read_events(env.home)) == 1


def test_report_survives_schema_less_lines(env, capsys):
    tdir = telemetry.telemetry_dir(env.home)
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "2026-07.x.jsonl").write_text(
        "{}\n"
        '{"ts":"2026-07-15T01:00:00Z","kind":"offer-declined","reason":null}\n'
        '{"ts":"2026-07-15T02:00:00Z","kind":"offer-made"}\n'
    )
    rc = cli.main(["report", "--json"])
    assert rc == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts["telemetry"]["events_by_kind"] == {
        "offer-declined": 1,
        "offer-made": 1,
    }
    assert facts["telemetry"]["decline_reasons"] == {"unspecified": 1}


# ------------------------------------------- follow-up lifecycle honesty


def seed_routed_with_followup(env, rid="lrn-0000aaaa"):
    create_record(env.home, make_behavior(record_id=rid))
    write_proposal(env.home, rid, proposal_dict())
    commit_all(env.home, "pending")
    assert cli.main(["route", rid, "--follow-up", "upgrade-to-hook"]) == 0
    return rid


def test_graduation_retires_followup_from_open_list_with_warning(env, capsys):
    rid = seed_routed_with_followup(env)
    capsys.readouterr()
    assert cli.main(["graduate", rid]) == 0
    err = capsys.readouterr().err
    assert "open follow-up" in err and "successor" in err
    assert open_followups(env.home) == []


def test_set_follow_up_refuses_non_routed_status(env):
    rid = seed_routed_with_followup(env)
    assert cli.main(["graduate", rid]) == 0
    record = Record.from_path(
        env.bucket / "resolved" / f"{rid}.md"
    )
    with pytest.raises(MutationError, match="LIVE routed"):
        record.set_follow_up("another-upgrade")


# ------------------------------------------------ capture-event coverage


def test_fallback_capture_emits_event(env):
    from self_learn.teach import _capture_to_pending

    record = make_behavior(record_id="lrn-0000bbbb")
    # doc 13: the fallback now takes the capture's project_path (None for a
    # skill-scoped record) so a project-scoped fallback homes correctly.
    rc = _capture_to_pending(
        env.home, record.to_text(), "boom", "retry later", None
    )
    assert rc == 4
    spooled = [
        json.loads(ln)
        for p in telemetry.spool_dir().glob("*.jsonl")
        for ln in p.read_text().splitlines()
    ]
    assert any(
        e["kind"] == "capture" and e["record"] == "lrn-0000bbbb" for e in spooled
    )


def test_route_emits_surface_budget_event(env):
    seed_routed_with_followup(env)
    events = telemetry.read_events(env.home)  # route flushed the spool
    budget = [e for e in events if e["kind"] == "surface-budget"]
    assert len(budget) == 1
    assert budget[0]["target"] == "skill-md"
    # U-cap §6.1: the `overflow` payload key is DROPPED — there is
    # nothing left to overflow (T10.4).
    assert "overflow" not in budget[0]
