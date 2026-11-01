"""S-NEXT-humane (w33-humane lane 0): the CLI shapes the humane UI reads.

- ``config get --json`` rows carry ``group``/``label``/``plain`` from
  ``settings_plain``, and every registry entry has them;
- ``status --json`` / ``report --json`` buckets carry ``label``/``path``/
  ``path_exists`` (``places.bucket_places``);
- ``report --json`` ``routed_live`` rows carry ``title``/``scope``/
  ``bucket_label``/``destination``;
- ``report --json`` ``series``: per-day counts (``series.day_series``).
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, timezone
from pathlib import Path

import pytest

from self_learn import cases, cli, settings, settings_plain
from self_learn.ledger import Bucket
from self_learn.places import USER_LABEL, bucket_places
from self_learn.report import gather
from self_learn.series import OUTCOME_GROUPS, day_series
from self_learn.ledger_ops import create_record, write_proposal
from support import (
    commit_all,
    init_repo,
    make_behavior,
    make_env,
    proposal_dict,
)


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


# ------------------------------------------------------------ settings words


def test_every_registry_entry_has_plain_words_in_a_known_group():
    ids = [g.id for g in settings_plain.GROUPS]
    assert len(ids) == len(set(ids))
    for setting in settings.REGISTRY:
        words = settings_plain.plain_for(setting.name)
        assert words.group in ids, setting.name
        assert words.label.strip() and words.plain.strip(), setting.name


def test_the_import_check_refuses_a_registry_entry_without_words(monkeypatch):
    """Positive control for the import-time check: a registry entry with
    no plain words must stop the import, not reach the page as a blank."""
    fake = settings.Setting(
        name="worker.not_a_real_key", env_var=None, config_section="worker",
        config_key="not_a_real_key", kind="int", default=1, description="x",
    )
    monkeypatch.setattr(settings, "REGISTRY", settings.REGISTRY + (fake,))
    with pytest.raises(AssertionError, match="worker.not_a_real_key"):
        settings_plain._check()


def test_config_get_json_rows_carry_group_label_plain(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    assert cli.main(["config", "get", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["name"] for r in rows} == {s.name for s in settings.REGISTRY}
    by_name = {r["name"]: r for r in rows}
    miner = by_name["miner.enabled"]
    assert miner["group"] == "runs"
    assert miner["label"] == "Read my sessions overnight"
    assert miner["plain"].startswith("Each night, read")
    # the technical note stays
    assert miner["description"] == settings.by_name("miner.enabled").description
    for row in rows:
        assert row["group"] and row["label"] and row["plain"], row["name"]


# ----------------------------------------------------------------- places


def _project_bucket(home: Path, slug: str, path: str | None) -> Bucket:
    bucket_dir = home / "projects" / slug
    bucket_dir.mkdir(parents=True)
    if path is not None:
        (bucket_dir / "meta.yaml").write_text(f"path: {path}\n", encoding="utf-8")
    return Bucket(path=bucket_dir, scope="project", name=slug)


def test_bucket_places_names_each_kind_of_bucket(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    home = tmp_path / "ledger"
    real = tmp_path / "home" / "repos" / "self-learn"
    real.mkdir(parents=True)
    buckets = [
        Bucket(path=home / "user", scope="user", name="user"),
        Bucket(path=home / "skills" / "herdr", scope="skill", name="herdr"),
        _project_bucket(home, "p-real", str(real)),
        _project_bucket(home, "p-wt", str(real / ".claude" / "worktrees" / "s3-run")),
        _project_bucket(home, "p-a", str(tmp_path / "home" / "a" / "tools")),
        _project_bucket(home, "p-b", str(tmp_path / "home" / "b" / "tools")),
        _project_bucket(home, "p-nometa", None),
    ]
    places = bucket_places(buckets)
    assert places[("user", "user")] == {"label": USER_LABEL, "path": "~/.claude", "path_exists": True}
    assert places[("skill", "herdr")] == {"label": "herdr", "path": None, "path_exists": None}
    assert places[("project", "p-real")] == {
        "label": "self-learn", "path": "~/repos/self-learn", "path_exists": True}
    # a worktree names its repo and the worktree, and a gone folder says so
    assert places[("project", "p-wt")] == {
        "label": "self-learn (worktree s3-run)",
        "path": "~/repos/self-learn/.claude/worktrees/s3-run", "path_exists": False}
    # two projects sharing a folder name fall back to their paths
    assert places[("project", "p-a")]["label"] == "~/a/tools"
    assert places[("project", "p-b")]["label"] == "~/b/tools"
    assert places[("project", "p-nometa")] == {"label": "p-nometa", "path": None, "path_exists": False}


def test_status_json_buckets_carry_their_place(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path, skills=("home-assistant",))
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    create_record(env.ledger, make_behavior(scope="skill:home-assistant", record_id="lrn-0a1b2c3d"))
    assert cli.main(["status", "--json"]) == 0
    rows = {(r["scope"], r["bucket"]): r for r in json.loads(capsys.readouterr().out)["buckets"]}
    assert rows[("skill", "home-assistant")]["label"] == "home-assistant"
    assert rows[("user", "user")]["label"] == USER_LABEL


# ----------------------------------------------------------- report rows


def test_report_routed_live_rows_carry_title_and_place(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    rid = "lrn-0000aaaa"
    create_record(env.ledger, make_behavior(scope="skill:s", record_id=rid,
                                            trigger="About to restart the printer mid-print."))
    write_proposal(env.ledger, rid, proposal_dict())
    commit_all(env.ledger, "pending")
    assert cli.main(["route", rid, "--no-push"]) == 0
    facts = gather(env.ledger)
    row = next(r for r in facts["routed_live"] if r["id"] == rid)
    assert row["title"] == "About to restart the printer mid-print."
    assert row["scope"] == "skill"
    assert row["bucket"] == "s"
    assert row["bucket_label"] == "s"
    assert row["destination"] == proposal_dict()["destination"]
    bucket = next(b for b in facts["buckets"] if (b["scope"], b["bucket"]) == ("skill", "s"))
    assert bucket["label"] == "s" and "counts" in bucket


# ----------------------------------------------------------------- series


def _git(repo: Path, *args: str, when: str | None = None) -> None:
    env = dict(os.environ)
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                   capture_output=True, text=True)


def _pending_file(home: Path, rel: str, status: str) -> None:
    path = home / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {path.stem}\nstatus: {status}\n---\n## Trigger\nx\n", encoding="utf-8")


def _case(home: Path, case_id: str, opened_at: str, actor: str, outcome: str) -> None:
    path = home / "cases" / opened_at[:7] / f"{case_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ncase: {case_id}\nopened_at: '{opened_at}'\nactor: {actor}\n"
        f"outcome: {outcome}\n---\n## Decision\n- verb: {outcome}\n",
        encoding="utf-8",
    )


def _series_ledger(tmp_path: Path) -> Path:
    home = tmp_path / "ledger"
    init_repo(home)
    (home / "README").write_text("x\n", encoding="utf-8")
    _git(home, "add", "-A")
    _git(home, "commit", "-q", "-m", "seed", when="2026-10-01T12:00:00Z")
    # Oct 6: two pending (user + skill), one deferred (project)
    _pending_file(home, "user/pending/lrn-00000001.md", "pending")
    _pending_file(home, "skills/s/pending/lrn-00000002.md", "pending")
    _pending_file(home, "projects/p-1/pending/lrn-00000003.md", "deferred")
    # a resolved file never counts, wherever it sits
    _pending_file(home, "user/resolved/lrn-00000004.md", "routed")
    _git(home, "add", "-A")
    _git(home, "commit", "-q", "-m", "day 6", when="2026-10-06T09:00:00Z")
    # Oct 8: one pending decided (file moved out of pending/)
    _git(home, "mv", "user/pending/lrn-00000001.md", "user/resolved/lrn-00000001.md")
    _git(home, "commit", "-q", "-m", "day 8", when="2026-10-08T22:00:00Z")
    # cases: two on Oct 8 (steward), one on Oct 9 (overseer), one outside
    _case(home, "case-0000000a", "2026-10-08T03:00:00Z", "steward", "route")
    _case(home, "case-0000000b", "2026-10-08T04:00:00Z", "steward", "no-action")
    _case(home, "case-0000000c", "2026-10-09T15:00:00Z", "overseer", "reject")
    _case(home, "case-0000000d", "2026-09-01T15:00:00Z", "steward", "defer")
    return home


def test_day_series_counts_the_queue_cases_and_captures_per_day(tmp_path):
    home = _series_ledger(tmp_path)
    events = [
        {"kind": "capture", "ts": "2026-10-06T08:00:00Z"},
        {"kind": "capture", "ts": "2026-10-06T23:30:00Z"},
        {"kind": "route", "ts": "2026-10-06T08:00:00Z"},  # not a capture
        {"kind": "capture", "ts": "2026-09-01T08:00:00Z"},  # outside the window
    ]
    out = day_series(home, today=date(2026, 10, 9), events=events, days=5, tz=timezone.utc)
    assert out["days"] == 5 and out["tz"] == "+00:00" and out["error"] is None
    rows = {r["date"]: r for r in out["rows"]}
    assert list(rows) == ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    assert (rows["2026-10-05"]["pending"], rows["2026-10-05"]["deferred"]) == (0, 0)
    assert (rows["2026-10-06"]["pending"], rows["2026-10-06"]["deferred"]) == (2, 1)
    assert (rows["2026-10-07"]["pending"], rows["2026-10-07"]["deferred"]) == (2, 1)  # carried
    assert (rows["2026-10-08"]["pending"], rows["2026-10-08"]["deferred"]) == (1, 1)
    assert rows["2026-10-06"]["captured"] == 2
    assert rows["2026-10-08"]["decided"] == {"use": 1, "no": 0, "later": 0, "kept": 1}
    assert rows["2026-10-08"]["decided_by"] == {"steward": 2}
    assert rows["2026-10-08"]["verbs"] == {"no-action": 1, "route": 1}
    assert rows["2026-10-09"]["decided"] == {"use": 0, "no": 1, "later": 0, "kept": 0}
    assert rows["2026-10-09"]["decided_by"] == {"overseer": 1}
    assert rows["2026-10-05"]["decided"] == {"use": 0, "no": 0, "later": 0, "kept": 0}


def test_day_series_bins_by_the_given_time_zone(tmp_path):
    """A capture at 03:00Z on Oct 7 is still Oct 6 eight hours west."""
    from datetime import timedelta
    home = _series_ledger(tmp_path)
    west = timezone(timedelta(hours=-8))
    events = [{"kind": "capture", "ts": "2026-10-07T03:00:00Z"}]
    out = day_series(home, today=date(2026, 10, 9), events=events, days=5, tz=west)
    rows = {r["date"]: r for r in out["rows"]}
    assert rows["2026-10-06"]["captured"] == 1 and rows["2026-10-07"]["captured"] == 0
    assert out["tz"] == "-08:00"


def test_day_series_without_git_history_says_so_and_still_counts(tmp_path):
    home = tmp_path / "not-a-repo"
    _case(home, "case-0000000a", "2026-10-08T03:00:00Z", "steward", "route")
    out = day_series(home, today=date(2026, 10, 9), events=[], days=3, tz=timezone.utc)
    assert out["error"]
    assert all(r["pending"] is None and r["deferred"] is None for r in out["rows"])
    assert out["rows"][1]["decided"]["use"] == 1


def test_every_case_outcome_is_in_exactly_one_group():
    grouped = [v for verbs in OUTCOME_GROUPS.values() for v in verbs]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == set(cases.OUTCOMES)


def test_report_json_carries_the_series(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    assert cli.main(["report", "--json"]) == 0
    series = json.loads(capsys.readouterr().out)["series"]
    assert series["days"] == 28 and len(series["rows"]) == 28
    assert series["error"] is None
    assert set(series["rows"][-1]) == {
        "date", "pending", "deferred", "captured", "decided", "decided_by", "verbs"}
