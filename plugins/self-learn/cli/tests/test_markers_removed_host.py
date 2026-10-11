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
from self_learn.compilers import BEGIN_MARKER, compile_managed_file
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
    (bucket / "resolved").mkdir(parents=True, exist_ok=True)
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


# ---------------------------------------------------------------- fold r1


def _project_hosts_yaml(home, *hosts):
    (home / "hosts.yaml").write_text(
        "projects:\n" + "".join(f"  - path: {h}\n" for h in hosts), encoding="utf-8"
    )


@pytest.fixture
def skills_root_and_project(tmp_path):
    """Skills root S (with a proj-skill SKILL.md that has a managed section
    owed by a lesson of project P's bucket, routed new-skill) + project P."""
    env = make_env(tmp_path)
    root = tmp_path / "skills-root"
    init_repo(root)
    proj = tmp_path / "proj-p"
    init_repo(proj)
    (proj / "README").write_text("p\n", encoding="utf-8")
    commit_all(proj, "seed")
    skill_md = root / "plugins" / "proj-skill" / "skills" / "proj-skill" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text("# proj-skill\n", encoding="utf-8")
    record = make_behavior(scope="project", record_id="lrn-5e000001")
    record.set_routing(
        {
            "routed_at": "2026-07-13T18:02:00Z",
            "destination": "new-skill",
            "new_skill": "proj-skill",
            "by": "human",
        }
    )
    record.set_status("routed")
    record.write(_bucket(env.ledger, proj) / "resolved" / f"{record.id}.md")
    compile_managed_file(skill_md, [record])
    # project P is deregistered (its clone deleted); the skills root stays
    (env.ledger / "hosts.yaml").write_text(f"skills_root: {root}\n", encoding="utf-8")
    shutil.rmtree(proj)
    return env.ledger, skill_md


def test_new_skill_target_of_a_removed_host_bucket_stays_checked_intact(
    skills_root_and_project,
):
    home, skill_md = skills_root_and_project
    (verdict, reason), targets, skipped = _markers(home)
    assert verdict is Verdict.PASS, reason
    assert list(targets) == [skill_md.resolve()]  # counted, not skipped
    assert skipped == []
    assert "marker pairs intact on 1 target(s)" in reason


def test_new_skill_target_of_a_removed_host_bucket_fails_when_marker_broken(
    skills_root_and_project,
):
    home, skill_md = skills_root_and_project
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace(BEGIN_MARKER, ""), encoding="utf-8"
    )
    (verdict, reason), targets, skipped = _markers(home)
    assert verdict is Verdict.FAIL
    assert "SKILL.md" in reason and "broken markers" in reason


def test_missing_hosts_yaml_skips_nothing(two_hosts):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="routed", write_target=False)
    (home / "hosts.yaml").unlink()
    (verdict, reason), targets, skipped = _markers(home)
    assert skipped == []
    assert verdict is Verdict.FAIL and "file missing" in reason


def test_unparseable_hosts_yaml_skips_nothing(two_hosts):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="routed", write_target=False)
    (home / "hosts.yaml").write_text("projects: [unclosed\n", encoding="utf-8")
    (verdict, reason), targets, skipped = _markers(home)
    assert skipped == []
    assert verdict is Verdict.FAIL and "file missing" in reason


def test_registration_through_a_symlink_is_not_skipped(two_hosts, tmp_path):
    home, host_a, host_b = two_hosts
    link = tmp_path / "link-to-a"
    link.symlink_to(host_a, target_is_directory=True)
    assert link != link.resolve()  # positive control: resolve() changes it
    _seed(home, host_a, "lrn-4c75079e", status="routed", write_target=False)
    _project_hosts_yaml(home, link, host_b)
    (verdict, reason), targets, skipped = _markers(home)
    assert skipped == []
    assert verdict is Verdict.FAIL and "file missing" in reason


def test_registration_with_dotdot_segment_is_not_skipped(two_hosts):
    home, host_a, host_b = two_hosts
    dotted = f"{host_a}/../{host_a.name}"
    assert dotted != str(host_a)
    _seed(home, host_a, "lrn-4c75079e", status="routed", write_target=False)
    _project_hosts_yaml(home, dotted, host_b)
    (verdict, reason), targets, skipped = _markers(home)
    assert skipped == []
    assert verdict is Verdict.FAIL and "file missing" in reason


def test_unregistered_bucket_that_resolves_no_target_is_not_listed(two_hosts):
    home, host_a, host_b = two_hosts
    record = make_behavior(scope="project", record_id="lrn-4c75079e")
    routing = dict(ROUTING)
    del routing["rules_topic"]  # rules variant without a topic: no target
    record.set_routing(routing)
    record.set_status("routed")
    record.write(_bucket(home, host_a) / "resolved" / "lrn-4c75079e.md")
    _project_hosts_yaml(home, host_b)  # A unregistered
    (verdict, reason), targets, skipped = _markers(home)
    assert targets == {} and skipped == []
    assert "not checked" not in reason
    # positive control: the same bucket WITH a resolvable target is listed
    _seed(home, host_a, "lrn-4c75079f", status="routed")
    _, _, skipped = _markers(home)
    assert skipped == [slug_for(host_a)]


def test_skip_note_rides_a_fail_verdict(two_hosts):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="routed")  # A: will be unregistered
    _seed(home, host_b, "lrn-b0000001", status="routed", write_target=False)
    _project_hosts_yaml(home, host_b)
    (verdict, reason), targets, skipped = _markers(home)
    assert verdict is Verdict.FAIL and "file missing" in reason
    assert "1 project bucket of an unregistered host not checked" in reason


def test_nothing_owed_but_a_skip_does_not_claim_no_routed_records(two_hosts):
    home, host_a, host_b = two_hosts
    _seed(home, host_a, "lrn-4c75079e", status="routed")
    _project_hosts_yaml(home, host_b)
    (verdict, reason), targets, skipped = _markers(home)
    assert verdict is Verdict.PASS and targets == {}
    assert reason.startswith("no section owed on a registered host")
    assert "not checked" in reason
