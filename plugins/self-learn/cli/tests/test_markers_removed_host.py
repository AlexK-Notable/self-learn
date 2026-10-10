"""Selftest `markers` stops counting lessons of a removed host.

The live sequence: a project-scope ``claude-md`` (rules variant) lesson is
routed in host A, superseded from host B, then host A is deregistered and
its clone deleted. The bucket keeps its resolved records, and
``verbs.managed_target_for`` resolves a project record through the
bucket's own ``meta.yaml`` path, so `markers` used to report
``file missing`` forever, with no verb that could clear the bucket.
"""

from __future__ import annotations

import shutil

import pytest

from self_learn import hosts as hosts_mod
from self_learn import selfcheck
from self_learn.compilers import compile_managed_file
from self_learn.hosts import slug_for
from self_learn.selfcheck import Verdict

from support import commit_all, init_repo, make_behavior, make_env

ROUTING = {
    "routed_at": "2026-07-13T18:02:00Z",
    "destination": "claude-md",
    "variant": "rules",
    "rules_topic": "closure",
    "by": "human",
}


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _bucket(home, host):
    bucket = home / "projects" / slug_for(host)
    (bucket / "resolved").mkdir(parents=True)
    (bucket / "meta.yaml").write_text(f"path: {host}\n", encoding="utf-8")
    return bucket


def _seed(home, host, record_id, *, status, superseded_by=None, write_target=True):
    record = make_behavior(scope="project", record_id=record_id)
    record.set_routing(dict(ROUTING))
    record.set_status(status)
    if superseded_by:
        record.set_superseded_by(superseded_by)
    record.write(_bucket(home, host) / "resolved" / f"{record_id}.md")
    target = host / ".claude" / "rules" / "closure.md"
    if write_target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# rules\n", encoding="utf-8")
        compile_managed_file(target, [record])
    return record, target


@pytest.fixture
def two_hosts(tmp_path):
    env = make_env(tmp_path)
    host_a = tmp_path / "host-a"
    init_repo(host_a)
    (host_a / "README").write_text("a\n", encoding="utf-8")
    commit_all(host_a, "seed")
    host_b = env.host
    (env.ledger / "hosts.yaml").write_text(
        f"projects:\n  - path: {host_a}\n  - path: {host_b}\n", encoding="utf-8"
    )
    commit_all(env.ledger, "two project hosts")
    return env.ledger, host_a, host_b


def _markers(home):
    skipped: list[str] = []
    targets = selfcheck._section_targets(home, skipped)
    return selfcheck._check_markers(targets, skipped), targets, skipped


def test_removed_host_bucket_is_skipped_and_named(two_hosts):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="superseded", superseded_by="lrn-b0000001")
    _seed(home, host_b, "lrn-b0000001", status="routed")
    # Positive control: before removal the superseded record is owed a section.
    (verdict, reason), targets, skipped = _markers(home)
    assert verdict is Verdict.PASS, reason
    assert len(targets) == 2 and skipped == []

    hosts_mod.host_remove(home, host_a)
    shutil.rmtree(host_a)

    (verdict, reason), targets, skipped = _markers(home)
    assert verdict is Verdict.PASS, reason
    assert skipped == [slug_for(host_a)]
    assert len(targets) == 1  # host B's record is still checked
    assert "1 project bucket of an unregistered host not checked" in reason
    assert slug_for(host_a) in reason


def test_registered_host_with_deleted_target_still_fails(two_hosts):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="routed", write_target=False)
    (verdict, reason), targets, skipped = _markers(home)
    assert skipped == []
    assert len(targets) == 1
    assert verdict is Verdict.FAIL
    assert "file missing" in reason and "closure.md" in reason


def test_superseded_record_on_registered_host_still_counts(two_hosts):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="superseded", superseded_by="lrn-b0000001")
    (verdict, reason), targets, skipped = _markers(home)
    assert verdict is Verdict.PASS, reason
    assert skipped == []
    assert [r.id for rs in targets.values() for r in rs] == ["lrn-4c75079e"]
    assert "marker pairs intact on 1 target(s)" in reason
    assert "not checked" not in reason


def test_run_selftest_row_carries_the_skip_notice(two_hosts, monkeypatch, capsys):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="superseded", superseded_by="lrn-b0000001")
    hosts_mod.host_remove(home, host_a)
    shutil.rmtree(host_a)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(home.parent / "claude-dir"))
    selfcheck.run_selftest(home)
    row = next(
        line for line in capsys.readouterr().out.splitlines() if " markers — " in line
    )
    assert row.startswith("selftest: PASS markers")
    assert "unregistered host not checked" in row
