"""T-H3 hosting refactor (doc 13): independent ledger home, hosts.yaml
registry, per-project buckets, two-phase routing, recompile drift repair,
producer commits (H-5), global sentinel, home-namespaced cache.

All git activity happens in sandbox repos under pytest tmpdirs (the
support.make_env ledger/host pair); chezmoi is a PATH shim; the cache is
XDG-redirected per test by conftest.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from self_learn import cli, gitops, miner, sentinel, verbs, worker
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.hosts import (
    Hosts,
    HostsError,
    host_add,
    hosts_path,
    is_project_host,
    load_hosts,
    slug_for,
)
from self_learn.import_backlog import import_backlog
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import (
    LedgerOpsError,
    bucket_dir_for_scope,
    bucket_project_path,
    create_record,
    status_infos,
)
from self_learn.selfcheck import _check_drift, run_selftest
from support import (
    SKILL_MD_SEED,
    commit_all,
    git,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    verb_files,
    verb_subject,
)


def subjects(repo):
    return git(repo, "log", "--format=%s").stdout.strip().splitlines()


def head(repo):
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


@pytest.fixture
def project_repo(tmp_path):
    """A separate sandbox project host (git repo, NOT registered yet)."""
    repo = tmp_path / "proj-repo"
    init_repo(repo)
    (repo / "README.md").write_text("proj\n", encoding="utf-8")
    commit_all(repo, "proj seed")
    return repo


CHEZMOI_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CHEZMOI_SHIM_LOG"
case "$1" in
  diff) printf '%s' "${CHEZMOI_SHIM_DIFF-}" ;;
  git) if [ "$3" = "status" ]; then printf '%s' "${CHEZMOI_SHIM_STATUS-}"; fi ;;
esac
exit "${CHEZMOI_SHIM_EXIT-0}"
"""


@pytest.fixture
def chezmoi_shim(tmp_path, monkeypatch):
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    fake = bindir / "chezmoi"
    fake.write_text(CHEZMOI_SHIM, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "chezmoi-argv.log"
    monkeypatch.setenv("CHEZMOI_SHIM_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return lambda: log.read_text(encoding="utf-8").splitlines() if log.is_file() else []


# ------------------------------------------------------- layout + discovery


class TestDiscovery:
    def test_discover_buckets_new_layout(self, env, project_repo):
        create_record(env.ledger, make_behavior(scope="skill:s"))
        create_record(
            env.ledger, make_knowledge(scope="project"), project_path=project_repo
        )
        create_record(env.ledger, make_knowledge(scope="user"))
        buckets = {b.name: b for b in discover_buckets(env.ledger)}
        assert buckets["s"].scope == "skill"
        assert buckets["s"].path == env.ledger / "skills" / "s"
        slug = slug_for(project_repo)
        assert buckets[slug].scope == "project"
        assert buckets[slug].path == env.ledger / "projects" / slug
        assert buckets["user"].scope == "user"
        assert buckets["user"].path == env.ledger / "user"

    def test_discover_buckets_empty_home(self, tmp_path):
        empty = tmp_path / "empty-home"
        empty.mkdir()
        assert discover_buckets(empty) == []

    def test_scope_strings_surface_in_status(self, env, project_repo):
        create_record(env.ledger, make_behavior(scope="skill:s"))
        create_record(
            env.ledger, make_knowledge(scope="project"), project_path=project_repo
        )
        create_record(env.ledger, make_knowledge(scope="user"))
        scopes = {row["scope"] for row in status_infos(env.ledger)}
        assert scopes == {"skill", "project", "user"}  # "project+user" is dead

    def test_slug_for_keeps_readable_shape_and_disambiguates(self):
        # Claude Code's readable projects-dir shape is still the PREFIX,
        # but the slug now carries a digest of the resolved path: the
        # readable form alone is many-to-one, which cross-homed one
        # project's lessons into another's canon (audit 2026-07-16
        # BLOCKER 1). See TestSlugCollision in test_hosting_fixes.py.
        slug = slug_for("/home/komi/repos/x")
        assert slug.startswith("-home-komi-repos-x-")
        assert len(slug) == len("-home-komi-repos-x-") + 8


class TestBucketDirForScope:
    def test_skill_scope(self, env):
        assert (
            bucket_dir_for_scope(env.ledger, "skill:s") == env.ledger / "skills" / "s"
        )

    def test_unknown_skill_refused(self, env):
        with pytest.raises(LedgerOpsError, match="no skill named 'nope'"):
            bucket_dir_for_scope(env.ledger, "skill:nope")

    def test_skill_scope_without_skills_root_refused(self, tmp_path):
        bare = tmp_path / "bare-ledger"
        init_repo(bare)  # no hosts.yaml at all
        with pytest.raises(LedgerOpsError, match="no skills root registered"):
            bucket_dir_for_scope(bare, "skill:s")

    def test_user_scope(self, env):
        assert bucket_dir_for_scope(env.ledger, "user") == env.ledger / "user"

    def test_project_scope_needs_path(self, env):
        with pytest.raises(LedgerOpsError, match="project_path"):
            bucket_dir_for_scope(env.ledger, "project")

    def test_project_scope_slugs(self, env, project_repo):
        expected = env.ledger / "projects" / slug_for(project_repo)
        assert (
            bucket_dir_for_scope(env.ledger, "project", project_path=project_repo)
            == expected
        )

    def test_create_record_writes_project_meta(self, env, project_repo):
        record = make_knowledge(scope="project")
        path = create_record(env.ledger, record, project_path=project_repo)
        bucket_dir = path.parent.parent
        assert bucket_dir == env.ledger / "projects" / slug_for(project_repo)
        assert (bucket_dir / "meta.yaml").is_file()
        assert bucket_project_path(bucket_dir) == project_repo.resolve()


# --------------------------------------------------------- hosts registry


class TestHostsRegistry:
    def test_load_hosts_missing_file_is_empty(self, tmp_path):
        assert load_hosts(tmp_path) == Hosts()

    def test_load_hosts_parses_env_seed(self, env):
        hosts = load_hosts(env.ledger)
        assert hosts.skills_root == env.host
        assert is_project_host(hosts, env.host)

    def test_load_hosts_malformed_refused(self, tmp_path):
        (tmp_path / "hosts.yaml").write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(HostsError, match="must be a YAML mapping"):
            load_hosts(tmp_path)
        (tmp_path / "hosts.yaml").write_text(
            "projects:\n  - {nope: 1}\n", encoding="utf-8"
        )
        with pytest.raises(HostsError, match=r"projects\[0\]"):
            load_hosts(tmp_path)

    def test_host_add_validates_path(self, env, tmp_path):
        with pytest.raises(HostsError, match="does not exist"):
            host_add(env.ledger, tmp_path / "missing", "project")
        plain = tmp_path / "plain-dir"
        plain.mkdir()
        with pytest.raises(HostsError, match="not a git repo"):
            host_add(env.ledger, plain, "project")
        with pytest.raises(HostsError, match="kind must be one of"):
            host_add(env.ledger, env.host, "banana")

    def test_host_add_project_rewrites_and_commits(self, env, project_repo):
        hosts = host_add(env.ledger, project_repo, "project")
        assert is_project_host(hosts, project_repo)
        assert is_project_host(load_hosts(env.ledger), project_repo)  # persisted
        assert (
            subjects(env.ledger)[0]
            == f"self-learn: host add project {project_repo.resolve()}"
        )

    def test_host_add_skills_root(self, env, project_repo):
        hosts = host_add(env.ledger, project_repo, "skills-root")
        assert hosts.skills_root == project_repo.resolve()
        assert (
            subjects(env.ledger)[0]
            == f"self-learn: host add skills-root {project_repo.resolve()}"
        )

    def test_host_add_idempotent_no_second_commit(self, env, project_repo):
        host_add(env.ledger, project_repo, "project")
        before = head(env.ledger)
        host_add(env.ledger, project_repo, "project")
        assert head(env.ledger) == before


# --------------------------------------------------- producers commit (H-5)


class TestProducerCommits:
    def test_teach_capture_commits_in_ledger(self, env, project_repo, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        monkeypatch.chdir(project_repo)
        assert cli.main(["teach", "--type", "knowledge", "--fact", "A fact."]) == 0
        bucket = env.ledger / "projects" / slug_for(project_repo)
        pending = list((bucket / "pending").glob("lrn-*.md"))
        assert len(pending) == 1
        rid = pending[0].stem
        # H-5: the capture commit is the newest NON-telemetry commit —
        # telemetry now commits itself on top (audit 2026-07-16 MAJOR 3).
        assert verb_subject(env.ledger) == f"self-learn: capture {rid} (project)"
        # the capture commit carries the record AND the bucket meta
        files = verb_files(env.ledger)
        assert f"projects/{slug_for(project_repo)}/pending/{rid}.md" in files
        assert f"projects/{slug_for(project_repo)}/meta.yaml" in files

    def test_import_backlog_one_commit_per_run(self, env):
        refs = env.skill_dir / "references"
        refs.mkdir()
        (refs / "GOTCHAS.journal.md").write_text(
            "### 2026-06-01 — Never edit .storage live\n- **Fix:** stop first\n\n"
            "### 2026-06-02 — The registry lags restarts\n- **Cause:** cache\n",
            encoding="utf-8",
        )
        report = import_backlog(env.ledger, "s")
        assert len(report.created) == 2
        assert (
            subjects(env.ledger)[0] == "self-learn: import 2 record(s) --backlog"
        )
        # created records live in the ledger skill bucket, not the host
        for rid in report.created:
            assert (env.ledger / "skills" / "s" / "pending" / f"{rid}.md").is_file()

    def test_miner_lands_project_candidate_with_cwd(self, env, project_repo):
        result = miner.MineResult(status="ok")
        parsed = {
            "candidates": [
                {
                    "scope": "project",
                    "type": "knowledge",
                    "fact": "The proxy strips trailing slashes.",
                    "session": "sess-0001",
                    "line": 7,
                    "quote": "",
                }
            ]
        }
        miner._reconcile_and_land(
            env.ledger, parsed, result, 5, {"sess-0001": str(project_repo)}
        )
        assert len(result.landed) == 1
        bucket = env.ledger / "projects" / slug_for(project_repo)
        assert list((bucket / "pending").glob("lrn-*.md"))
        assert bucket_project_path(bucket) == project_repo.resolve()
        assert result.touched  # the landing-commit staging set is tracked

    def test_miner_drops_project_candidate_without_cwd(self, env):
        result = miner.MineResult(status="ok")
        parsed = {
            "candidates": [
                {
                    "scope": "project",
                    "type": "knowledge",
                    "fact": "The proxy strips trailing slashes.",
                    "session": "sess-0002",
                    "line": 3,
                }
            ]
        }
        miner._reconcile_and_land(env.ledger, parsed, result, 5, {})
        assert result.landed == []
        assert any(
            o["outcome"] == "dropped-invalid"
            and o.get("reason") == "no cwd for project scope"
            for o in result.outcomes
        )


# ------------------------------------------------------- two-phase routing


class TestTwoPhaseRoute:
    def test_route_skill_md_commits_ledger_then_host(self, env):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        result = verbs.route(env.ledger, record.id, dest="skill-md", no_push=True)

        # LEDGER commit: pinned route subject, record moved to resolved/.
        assert (
            subjects(env.ledger)[0]
            == f"self-learn: route {record.id} → skill-md"
        )
        assert (
            env.ledger / "skills" / "s" / "resolved" / f"{record.id}.md"
        ).is_file()
        # HOST commit: pinned apply subject; SKILL.md updated in the HOST.
        assert (
            subjects(env.host)[0]
            == f"self-learn: apply {record.id} → "
            "plugins/s-plugin/skills/s/SKILL.md (skill-md)"
        )
        text = env.skill_md.read_text(encoding="utf-8")
        assert BEGIN_MARKER in text and END_MARKER in text
        assert f"({record.id})" in text
        assert "Authored prose stays put." in text
        assert result.host_commit_sha == head(env.host)
        assert result.warnings == []

    def test_route_reference_lands_in_host_references(self, env):
        record = make_knowledge(scope="skill:s")
        create_record(env.ledger, record)
        verbs.route(env.ledger, record.id, dest="reference", no_push=True)
        learnings = env.skill_dir / "references" / "LEARNINGS.md"
        assert learnings.is_file()
        assert record.id in learnings.read_text(encoding="utf-8")
        assert (
            subjects(env.host)[0]
            == f"self-learn: apply {record.id} → "
            "plugins/s-plugin/skills/s/references/LEARNINGS.md (reference)"
        )

    def test_reject_stays_single_ledger_commit(self, env):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        host_before = head(env.host)
        verbs.reject(env.ledger, record.id, no_push=True)
        assert subjects(env.ledger)[0] == f"self-learn: reject {record.id}"
        assert head(env.host) == host_before  # no host phase for ledger-only verbs

    def test_project_route_gated_on_host_registration(self, env, project_repo):
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=project_repo)
        ledger_before = head(env.ledger)
        with pytest.raises(
            verbs.VerbError,
            match=f"host not registered — self-learn host add {project_repo}",
        ):
            verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)
        # the refusal fired in PRE-FLIGHT: nothing committed, record pending
        assert head(env.ledger) == ledger_before
        slug = slug_for(project_repo)
        assert (
            env.ledger / "projects" / slug / "pending" / f"{record.id}.md"
        ).is_file()

        # register, then the same route succeeds two-phase
        host_add(env.ledger, project_repo, "project")
        verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)
        assert (
            subjects(project_repo)[0]
            == f"self-learn: apply {record.id} → CLAUDE.md (claude-md)"
        )
        claude_md = (project_repo / "CLAUDE.md").read_text(encoding="utf-8")
        assert f"({record.id})" in claude_md

    def test_user_scope_chezmoi_flow_unchanged(self, env, tmp_path, chezmoi_shim):
        record = make_knowledge(scope="user")
        create_record(env.ledger, record)
        user_md = tmp_path / "user-claude.md"
        user_md.write_text("# user canon\n", encoding="utf-8")
        host_before = head(env.host)
        result = verbs.route(
            env.ledger,
            record.id,
            dest="claude-md",
            no_push=True,
            user_claude_md=user_md,
        )
        # the guarded chezmoi sequence ran: diff, status, re-add, add/commit/push
        calls = chezmoi_shim()
        assert any(c.startswith("diff ") for c in calls)
        assert any("status --porcelain" in c for c in calls)
        assert any(c.startswith("re-add ") for c in calls)
        assert any("commit -m self-learn: route" in c for c in calls)
        # the dotfiles repo commits itself — no host commit here
        assert result.host_commit_sha is None
        assert head(env.host) == host_before
        assert f"({record.id})" in user_md.read_text(encoding="utf-8")

    def test_supersede_of_routed_record_recompiles_host(self, env):
        old = make_behavior(scope="skill:s", record_id="lrn-0000aaaa")
        create_record(env.ledger, old)
        verbs.route(env.ledger, old.id, dest="skill-md", no_push=True)
        new = make_behavior(
            scope="skill:s",
            record_id="lrn-0000bbbb",
            trigger="About to edit .storage anywhere.",
            instruction="Snapshot first, then stop the container.",
        )
        create_record(env.ledger, new)
        verbs.route(env.ledger, new.id, dest="skill-md", no_push=True)
        assert f"({old.id})" in env.skill_md.read_text(encoding="utf-8")

        result = verbs.supersede(env.ledger, old.id, new.id, no_push=True)
        assert (
            subjects(env.ledger)[0]
            == f"self-learn: supersede {old.id} → {new.id}"
        )
        # host phase dropped the superseded entry via recompile-of-target
        text = env.skill_md.read_text(encoding="utf-8")
        assert f"({old.id})" not in text
        assert f"({new.id})" in text
        assert result.host_commit_sha == head(env.host)


# ------------------------------------------- drift, selfcheck, recompile


class TestDriftAndRecompile:
    def _corrupt_skill_md(self, env):
        env.skill_md.write_text(
            SKILL_MD_SEED.format(name="s") + f"\n{BEGIN_MARKER}\n{BEGIN_MARKER}\n",
            encoding="utf-8",
        )
        commit_all(env.host, "corrupt markers")

    def test_host_phase_failure_warns_then_recompile_repairs(self, env, capsys):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        self._corrupt_skill_md(env)  # committed → passes the dirty preflight
        host_before = head(env.host)

        result = verbs.route(env.ledger, record.id, dest="skill-md", no_push=True)
        # ledger committed; host did not
        assert (
            subjects(env.ledger)[0] == f"self-learn: route {record.id} → skill-md"
        )
        assert head(env.host) == host_before
        assert any("recompile" in w for w in result.warnings)
        assert "HOST PHASE FAILED" in capsys.readouterr().err

        # drift check FAILS, naming the repair
        ok, reason = _check_drift(env.ledger)
        assert not ok
        assert "self-learn recompile" in reason

        # repair the target, then recompile closes the drift
        env.skill_md.write_text(SKILL_MD_SEED.format(name="s"), encoding="utf-8")
        commit_all(env.host, "fix markers")
        rec = verbs.recompile(env.ledger, no_push=True)
        assert rec.committed == 1
        assert subjects(env.host)[0] == (
            "self-learn: recompile plugins/s-plugin/skills/s/SKILL.md"
        )
        assert f"({record.id})" in env.skill_md.read_text(encoding="utf-8")
        ok, _reason = _check_drift(env.ledger)
        assert ok

    def test_recompile_is_idempotent(self, env):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        verbs.route(env.ledger, record.id, dest="skill-md", no_push=True)
        first = verbs.recompile(env.ledger, no_push=True)
        assert first.committed == 0  # route already applied the section
        host_head = head(env.host)
        second = verbs.recompile(env.ledger, no_push=True)
        assert second.committed == 0
        assert head(env.host) == host_head  # no commit on a no-change run

    def test_drift_check_skips_without_hosts_yaml(self, tmp_path):
        bare = tmp_path / "bare-ledger"
        init_repo(bare)
        ok, reason = _check_drift(bare)
        assert ok
        assert "hosts.yaml absent" in reason

    def test_selftest_green_on_fresh_env(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        assert run_selftest(env.ledger) == 0
        out = capsys.readouterr().out
        assert "PASS drift" in out


# ---------------------------------------------- cache, sentinel, worker


class TestCacheAndSentinel:
    def test_cache_dir_is_home_namespaced(self, tmp_path, monkeypatch):
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-a"))
        a = worker.cache_dir()
        assert a.parent == xdg / "self-learn"
        assert a.name.startswith("home-") and len(a.name) == len("home-") + 8
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-b"))
        assert worker.cache_dir() != a  # H-4: namespaced per ledger home

    def test_cache_migration_shim_moves_old_state(self, tmp_path, monkeypatch):
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-a"))
        old = xdg / "claude-skills" / "self-learn"
        (old / "miner").mkdir(parents=True)
        (old / "spool").mkdir()
        (old / "worker.log").write_text("log line\n", encoding="utf-8")
        (old / "events.jsonl").write_text("{}\n", encoding="utf-8")
        (old / "miner" / "journal.jsonl").write_text("{}\n", encoding="utf-8")
        (old / "spool" / "2026-07.host.jsonl").write_text("{}\n", encoding="utf-8")

        new = worker.cache_dir()
        # the old log is carried over intact; the shim APPENDS its own
        # audit line (2026-07-16 MINOR 9: it must never move state
        # silently), so the old content is a prefix, not the whole file.
        log = (new / "worker.log").read_text(encoding="utf-8")
        assert log.startswith("log line\n")
        assert "cache migration" in log
        assert (new / "events.jsonl").is_file()
        assert (new / "miner" / "journal.jsonl").is_file()
        assert (new / "spool" / "2026-07.host.jsonl").is_file()
        # one-time: a second call must not disturb the migrated state
        assert worker.cache_dir() == new
        assert (new / "worker.log").read_text(encoding="utf-8") == log

    def test_sentinel_path_is_global(self, tmp_path, monkeypatch):
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        path = sentinel.sentinel_path()
        assert path == xdg / "self-learn" / "autosync-pause"
        assert "home-" not in str(path)  # deliberately NOT home-namespaced

    def test_sync_script_checks_the_global_sentinel_path(self):
        # The sentinel contract's OTHER half lives in the HOST's autosync
        # sync script (claude-skills bin/claude-skills-sync) — a repo this
        # product was extracted FROM (13 §7.3), so the script is only
        # present on machines with that host checked out at its usual
        # path. Absent → skip loudly; the live half of the contract is
        # still exercised every run by the selftest sentinel check.
        script = (
            Path.home() / "repos" / "claude-skills" / "bin" / "claude-skills-sync"
        )
        if not script.is_file():
            pytest.skip(
                "host sync script not on this machine (product repo is "
                "standalone since 13 §7.3) — sentinel contract covered "
                "by selftest"
            )
        text = script.read_text(encoding="utf-8")
        assert "/self-learn/autosync-pause" in text
        assert "claude-skills/self-learn/autosync-pause" not in text


class TestWorkerContainment:
    def test_write_permission_rules_new_layout_only(self, env):
        rules = worker.write_permission_rules(env.ledger)
        assert rules == [
            f"Edit(/{env.ledger}/skills/**/proposals/**)",
            f"Edit(/{env.ledger}/projects/**/proposals/**)",
            f"Edit(/{env.ledger}/user/proposals/**)",
        ]
        # H-3: no rule may open any HOST path to the worker
        assert all(str(env.host) not in rule for rule in rules)
        assert all(".self-learn" not in rule for rule in rules)

    def test_package_skill_refs_resolves_to_shipped_references(self):
        refs = worker.package_skill_refs()
        assert refs.is_dir()
        assert (refs / "routing-doctrine.md").is_file()
        assert (refs / "card-sections.yaml").is_file()
        assert (refs / "mining-rubric.md").is_file()

    def test_settings_file_carries_the_new_rules(self, env, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg2"))
        settings = worker.write_settings_file(env.ledger)
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["permissions"]["allow"] == worker.write_permission_rules(
            env.ledger
        )
