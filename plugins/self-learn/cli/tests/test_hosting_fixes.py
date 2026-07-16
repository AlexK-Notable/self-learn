"""Regression tests for the 2026-07-16 hosting audit (doc 13).

One class per confirmed finding; each test reproduces the auditor's live
probe and fails without its fix. Same idioms as test_hosting.py: real git
sandboxes under pytest tmpdirs (support.make_env), no mocks, no contact
with the real ~/.self-learn, ~/repos/claude-skills, or ~/.claude.
"""

import json
import os
import stat
import subprocess

import pytest

from self_learn import cli, gitops, telemetry, verbs, worker
from self_learn.hosts import (
    HostsError,
    host_add,
    host_rebind,
    host_remove,
    load_hosts,
    slug_for,
)
from self_learn.ledger import home_state
from self_learn.ledger_ops import (
    LedgerOpsError,
    bucket_dir_for_scope,
    create_record,
    ensure_project_meta,
)
from self_learn.records import Record
from self_learn.selfcheck import _check_drift
from support import (
    commit_all,
    git,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
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
    repo = tmp_path / "proj-repo"
    init_repo(repo)
    (repo / "README.md").write_text("proj\n", encoding="utf-8")
    commit_all(repo, "proj seed")
    return repo


def bare_remote(tmp_path, repo, name="remote.git"):
    """Give a sandbox repo a bare origin so pushes are real."""
    bare = tmp_path / name
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
    )
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


# ------------------------------------------------------------- BLOCKER 1


class TestSlugCollision:
    """`/w/a-b` and `/w/a/b` both rendered `-w-a-b`, so project B's records
    landed in project A's bucket and compiled into A's CLAUDE.md."""

    def test_ambiguous_paths_get_distinct_slugs(self, tmp_path):
        flat = tmp_path / "a-b"
        nested = tmp_path / "a" / "b"
        flat.mkdir(parents=True)
        nested.mkdir(parents=True)
        # the readable shape still collides — the slug must not
        assert str(flat).replace("/", "-") == str(nested).replace("/", "-")
        assert slug_for(flat) != slug_for(nested)

    def test_slug_is_stable_across_calls(self, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        assert slug_for(d) == slug_for(str(d)) == slug_for(d.resolve())

    def test_colliding_projects_get_separate_buckets(self, env, tmp_path):
        flat = tmp_path / "a-b"
        nested = tmp_path / "a" / "b"
        for d in (flat, nested):
            init_repo(d)
            (d / "README.md").write_text("x\n", encoding="utf-8")
            commit_all(d, "seed")

        a = bucket_dir_for_scope(env.ledger, "project", project_path=flat)
        b = bucket_dir_for_scope(env.ledger, "project", project_path=nested)
        assert a != b

        create_record(env.ledger, make_knowledge(record_id="lrn-0000aaaa"),
                      project_path=flat)
        create_record(env.ledger, make_knowledge(record_id="lrn-0000bbbb"),
                      project_path=nested)
        # each project's record is in its OWN bucket — never cross-homed
        assert (a / "pending" / "lrn-0000aaaa.md").is_file()
        assert not (a / "pending" / "lrn-0000bbbb.md").exists()
        assert (b / "pending" / "lrn-0000bbbb.md").is_file()


class TestEnsureProjectMeta:
    """A bucket whose meta names another project is never silently
    accepted — that is how records compile into the wrong repo's canon."""

    def test_mismatched_meta_raises(self, tmp_path):
        bucket = tmp_path / "bucket"
        ensure_project_meta(bucket, tmp_path / "project-a")
        with pytest.raises(LedgerOpsError, match="belongs to"):
            ensure_project_meta(bucket, tmp_path / "project-b")

    def test_mismatch_message_names_rebind(self, tmp_path):
        bucket = tmp_path / "bucket"
        ensure_project_meta(bucket, tmp_path / "project-a")
        with pytest.raises(LedgerOpsError, match="host rebind"):
            ensure_project_meta(bucket, tmp_path / "project-b")

    def test_matching_meta_is_a_no_op(self, tmp_path):
        bucket = tmp_path / "bucket"
        meta = ensure_project_meta(bucket, tmp_path / "p")
        before = meta.read_text(encoding="utf-8")
        assert ensure_project_meta(bucket, tmp_path / "p") == meta
        assert meta.read_text(encoding="utf-8") == before

    def test_unreadable_meta_raises(self, tmp_path):
        bucket = tmp_path / "bucket"
        bucket.mkdir()
        (bucket / "meta.yaml").write_text("path: \n", encoding="utf-8")
        with pytest.raises(LedgerOpsError, match="unreadable|no path"):
            ensure_project_meta(bucket, tmp_path / "p")


# ------------------------------------------------------------- BLOCKER 2


def _interrupt_reference_route(env, record):
    """The auditor's scenario: a `reference` route that committed the
    ledger and died before the host apply — no canon entry anywhere."""
    verbs.route(env.ledger, record.id, dest="reference", no_push=True)
    learnings = env.skill_dir / "references" / "LEARNINGS.md"
    learnings.unlink()
    if git(env.host, "status", "--porcelain").stdout.strip():
        commit_all(env.host, "canon lost mid-route")
    return learnings


class TestReferenceRecompile:
    def test_recompile_reappends_interrupted_reference_route(self, env):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        learnings = _interrupt_reference_route(env, record)
        assert not learnings.exists()

        result = verbs.recompile(env.ledger, no_push=True)

        assert learnings.is_file()
        assert record.id in learnings.read_text(encoding="utf-8")
        assert result.committed == 1
        assert subjects(env.host)[0] == (
            "self-learn: recompile plugins/s-plugin/skills/s/references/"
            "LEARNINGS.md"
        )

    def test_reference_recompile_is_idempotent(self, env):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        verbs.route(env.ledger, record.id, dest="reference", no_push=True)
        host_head = head(env.host)

        first = verbs.recompile(env.ledger, no_push=True)
        assert first.committed == 0  # the route already appended it
        assert head(env.host) == host_head
        text = (env.skill_dir / "references" / "LEARNINGS.md").read_text(
            encoding="utf-8"
        )
        assert text.count(record.id) == 1  # never double-appended

    def test_named_reference_file_survives_on_the_record(self, env):
        """recompile/drift cannot repair a file they cannot name."""
        refs = env.skill_dir / "references"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "CUSTOM.md").write_text("# Custom\n", encoding="utf-8")
        commit_all(env.host, "custom refs file")

        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        verbs.route(env.ledger, record.id, dest="reference:CUSTOM.md", no_push=True)

        routed = Record.from_path(
            env.ledger / "skills" / "s" / "resolved" / f"{record.id}.md"
        )
        assert routed.routing["reference_file"] == "CUSTOM.md"
        assert record.id in (refs / "CUSTOM.md").read_text(encoding="utf-8")

        # and the drift check follows the record to THAT file
        (refs / "CUSTOM.md").write_text("# Custom\n", encoding="utf-8")
        commit_all(env.host, "entry lost")
        ok, reason = _check_drift(env.ledger)
        assert not ok
        assert "CUSTOM.md" in reason


class TestReferenceDrift:
    def test_drift_fails_for_interrupted_reference_route(self, env):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        _interrupt_reference_route(env, record)

        ok, reason = _check_drift(env.ledger)

        assert not ok  # was: "no routed managed-destination records"
        assert record.id in reason
        assert "self-learn recompile" in reason

    def test_drift_fails_when_reference_entry_is_hand_deleted(self, env):
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        verbs.route(env.ledger, record.id, dest="reference", no_push=True)
        learnings = env.skill_dir / "references" / "LEARNINGS.md"
        learnings.write_text("# Learnings\n", encoding="utf-8")
        commit_all(env.host, "hand-deleted entry")

        ok, reason = _check_drift(env.ledger)
        assert not ok
        assert "entry missing" in reason

    def test_drift_green_path_has_routed_records(self, env):
        """The old green-path test asserted PASS drift on an env with ZERO
        routed records — a vacuous branch that would pass with the check
        deleted. Assert green against records that ARE routed."""
        managed = make_behavior(scope="skill:s", record_id="lrn-0000aaaa")
        create_record(env.ledger, managed)
        verbs.route(env.ledger, managed.id, dest="skill-md", no_push=True)
        referenced = make_behavior(
            scope="skill:s",
            record_id="lrn-0000bbbb",
            trigger="About to hand-edit a references file.",
            instruction="Append via the compiler.",
        )
        create_record(env.ledger, referenced)
        verbs.route(env.ledger, referenced.id, dest="reference", no_push=True)

        ok, reason = _check_drift(env.ledger)

        assert ok
        assert "2 routed record(s) present" in reason  # both, actually checked


# --------------------------------------------------------------- MAJOR 3


class TestTelemetryCommits:
    def test_flush_commits_the_tracked_plane(self, env, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
        telemetry.spool_event("offer-made")

        report = telemetry.flush(env.ledger)

        assert report.events == 1
        # was: `?? telemetry/` — untracked, unpushed, lost on re-clone
        assert git(env.ledger, "status", "--porcelain").stdout.strip() == ""
        assert subjects(env.ledger)[0] == "self-learn: telemetry flush 1 event"
        files = git(
            env.ledger, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()
        assert files == ["telemetry/2026-07.testhost.jsonl"] or all(
            f.startswith("telemetry/") for f in files
        )

    def test_flush_pushes_when_a_remote_exists(self, env, tmp_path, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
        bare = bare_remote(tmp_path, env.ledger)
        telemetry.spool_event("offer-made")

        telemetry.flush(env.ledger)

        assert git(bare, "log", "-1", "--format=%s").stdout.strip() == (
            "self-learn: telemetry flush 1 event"
        )

    def test_flush_with_push_false_commits_but_stays_local(
        self, env, tmp_path, monkeypatch
    ):
        """--no-push means "keep this local" — a flush that pushed anyway
        would publish the very commit the verb was told to hold."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
        bare = bare_remote(tmp_path, env.ledger)
        seed = git(bare, "log", "-1", "--format=%s").stdout.strip()
        telemetry.spool_event("offer-made")

        telemetry.flush(env.ledger, push=False)

        assert subjects(env.ledger)[0] == "self-learn: telemetry flush 1 event"
        assert git(bare, "log", "-1", "--format=%s").stdout.strip() == seed

    def test_empty_flush_commits_nothing(self, env, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        before = head(env.ledger)
        assert telemetry.flush(env.ledger).events == 0
        assert head(env.ledger) == before


#: A shim-written, schema-valid proposal (same idiom as test_worker.py).
PROPOSAL_YAML = """destination: skill-md
alternates: [reference]
rationale: "shim-written proposal"
already_canon: false
model: claude-sonnet-5
analyzed_at: "2026-07-15T00:00:00Z"
card:
  headline: "A test headline."
  impact: "Next time Claude does X it will Y."
  discuss: "Nothing contentious."
"""


@pytest.fixture
def worker_env(env, tmp_path, monkeypatch):
    """A ledger whose `claude` is a PATH shim running $CLAUDE_SHIM_SCRIPT."""
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    shim = bindir / "claude"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "cat > /dev/null || true\n"
        'if [ -n "${CLAUDE_SHIM_SCRIPT-}" ]; then bash -c "$CLAUDE_SHIM_SCRIPT"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return env


class TestWorkerCommits:
    def _seed(self, env, rid="lrn-0000aaaa"):
        record = make_behavior(scope="skill:s", record_id=rid)
        create_record(env.ledger, record)
        commit_all(env.ledger, "seed record")
        return record

    def _shim_writes_proposal(self, env, monkeypatch, rid):
        proposals = env.ledger / "skills" / "s" / "proposals"
        path = proposals / f"{rid}.yaml"
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT",
            f"mkdir -p {proposals} && cat > {path} <<'YAML'\n{PROPOSAL_YAML}YAML",
        )
        return path

    def test_run_commits_validated_proposals(self, worker_env, monkeypatch):
        env = worker_env
        record = self._seed(env)
        proposal = self._shim_writes_proposal(env, monkeypatch, record.id)

        result = worker.run(env.ledger)

        assert result.status == "ok"
        assert proposal.is_file()
        # was: `?? skills/s/proposals/` — never committed, never pushed;
        # machine B re-analyzed from scratch and a re-clone destroyed it
        assert git(env.ledger, "status", "--porcelain").stdout.strip() == ""
        assert result.commit_sha is not None
        assert verb_subject(env.ledger) == "self-learn: worker 1 proposal"
        assert "skills/s/proposals/lrn-0000aaaa.yaml" in git(
            env.ledger, "ls-files"
        ).stdout

    def test_run_pushes_its_proposals(self, worker_env, tmp_path, monkeypatch):
        env = worker_env
        bare = bare_remote(tmp_path, env.ledger, "worker-remote.git")
        record = self._seed(env)
        self._shim_writes_proposal(env, monkeypatch, record.id)

        worker.run(env.ledger)

        assert "self-learn: worker 1 proposal" in git(
            bare, "log", "--format=%s"
        ).stdout

    def test_run_commits_its_orphan_sweeps(self, worker_env, monkeypatch):
        env = worker_env
        # one live pending record (so the run does real work) …
        record = self._seed(env)
        self._shim_writes_proposal(env, monkeypatch, record.id)
        # … plus a TRACKED orphan proposal whose record is gone
        proposals = env.ledger / "skills" / "s" / "proposals"
        proposals.mkdir(parents=True, exist_ok=True)
        orphan = proposals / "lrn-0000dead.yaml"
        orphan.write_text(PROPOSAL_YAML, encoding="utf-8")
        commit_all(env.ledger, "seed orphan proposal")
        assert "lrn-0000dead.yaml" in git(env.ledger, "ls-files").stdout

        result = worker.run(env.ledger)

        assert "lrn-0000dead.yaml" in result.orphans_swept

        assert not orphan.exists()
        # the deletion is COMMITTED, not left for a watcher that no longer
        # exists (H-5): `?? `/` D ` in git status was the old outcome
        assert git(env.ledger, "status", "--porcelain").stdout.strip() == ""
        assert "lrn-0000dead.yaml" not in git(env.ledger, "ls-files").stdout

    def test_run_staging_stays_surgical(self, worker_env, monkeypatch):
        """Never `add -A`: unrelated dirt stays out of the worker's commit."""
        env = worker_env
        record = self._seed(env)
        self._shim_writes_proposal(env, monkeypatch, record.id)
        dirt = env.ledger / "unrelated.md"
        dirt.write_text("not the worker's business\n", encoding="utf-8")

        worker.run(env.ledger)

        assert "unrelated.md" not in git(env.ledger, "ls-files").stdout
        assert "unrelated.md" in git(env.ledger, "status", "--porcelain").stdout


# --------------------------------------------------------------- MAJOR 4


class TestHostPushReporting:
    def _routed_with_broken_host_remote(self, env, tmp_path):
        """Host has a remote that cannot be pushed to — the auditor's
        "reports (pushed), exits 0" case."""
        bare_remote(tmp_path, env.ledger, "ledger-remote.git")
        git(env.host, "remote", "add", "origin", str(tmp_path / "nonexistent.git"))
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        return record

    def test_failed_host_push_is_rendered_and_non_zero(
        self, env, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        record = self._routed_with_broken_host_remote(env, tmp_path)

        rc = cli.main(["route", record.id, "--dest", "skill-md"])
        out = capsys.readouterr().out

        assert rc == gitops.EXIT_PUSH_FAILED  # was: 0
        assert "(pushed)" not in out  # was: "(pushed)" — a lie
        assert "host PUSH FAILED" in out
        assert "ledger pushed" in out

    def test_clean_two_phase_push_still_reads_pushed(
        self, env, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        bare_remote(tmp_path, env.ledger, "ledger-remote.git")
        bare_remote(tmp_path, env.host, "host-remote.git")
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)

        rc = cli.main(["route", record.id, "--dest", "skill-md"])

        assert rc == 0
        assert "(pushed)" in capsys.readouterr().out

    def test_push_verb_publishes_the_host_too(self, env, tmp_path, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        ledger_bare = bare_remote(tmp_path, env.ledger, "ledger-remote.git")
        host_bare = bare_remote(tmp_path, env.host, "host-remote.git")
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        assert cli.main(["route", record.id, "--dest", "skill-md", "--no-push"]) == 0
        host_seed = git(host_bare, "log", "-1", "--format=%s").stdout.strip()
        assert host_seed == "host seed"  # nothing published yet

        assert cli.main(["push"]) == 0

        # both repos published by the ONE command the failure message names
        assert f"self-learn: route {record.id} → skill-md" in git(
            ledger_bare, "log", "--format=%s"
        ).stdout
        assert git(host_bare, "log", "-1", "--format=%s").stdout.strip() == (
            f"self-learn: apply {record.id} → "
            "plugins/s-plugin/skills/s/SKILL.md (skill-md)"
        )

    def test_push_verb_skips_a_broken_host_but_still_pushes_the_ledger(
        self, env, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        ledger_bare = bare_remote(tmp_path, env.ledger, "ledger-remote.git")
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        commit_all(env.ledger, "seed record")
        # the host repo vanishes after registration
        subprocess.run(["rm", "-rf", str(env.host)], check=True)

        rc = cli.main(["push"])

        assert rc == 0
        assert "skipping" in capsys.readouterr().err
        assert git(ledger_bare, "log", "-1", "--format=%s").stdout.strip() == (
            "seed record"
        )


# --------------------------------------------------------------- MAJOR 5


class TestHostRebind:
    def test_moved_project_strands_bucket_behind_impossible_command(
        self, env, tmp_path, project_repo
    ):
        """The auditor's trap: the refusal named `host add /old/path`, and
        host add then refused because /old/path no longer exists."""
        host_add(env.ledger, project_repo, "project")
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=project_repo)
        moved = tmp_path / "proj-moved"
        project_repo.rename(moved)

        # `host add <old>` is impossible — the path is gone
        with pytest.raises(HostsError, match="does not exist"):
            host_add(env.ledger, project_repo, "project")

        # rebind is the way out
        bucket = host_rebind(env.ledger, str(project_repo), moved)

        assert bucket == env.ledger / "projects" / slug_for(moved)
        assert (bucket / "pending" / f"{record.id}.md").is_file()  # records kept
        from self_learn.ledger_ops import bucket_project_path

        assert bucket_project_path(bucket) == moved.resolve()
        projects = load_hosts(env.ledger).projects
        assert moved.resolve() in projects  # re-pointed…
        assert project_repo.resolve() not in projects  # …and the old one gone
        assert subjects(env.ledger)[0] == (
            f"self-learn: host rebind {project_repo.resolve()} → {moved.resolve()}"
        )

    def test_rebind_then_route_compiles_into_the_new_host(
        self, env, tmp_path, project_repo
    ):
        host_add(env.ledger, project_repo, "project")
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=project_repo)
        moved = tmp_path / "proj-moved"
        project_repo.rename(moved)
        host_rebind(env.ledger, str(project_repo), moved)

        verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)

        assert f"({record.id})" in (moved / "CLAUDE.md").read_text(encoding="utf-8")

    def test_rebind_moves_a_tracked_bucket_with_git_mv(
        self, env, tmp_path, project_repo
    ):
        """The bucket is usually TRACKED (producers commit their captures,
        H-5) — the rename must go through git, not behind its back."""
        host_add(env.ledger, project_repo, "project")
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=project_repo)
        commit_all(env.ledger, "capture")
        old_slug = slug_for(project_repo)
        assert f"projects/{old_slug}/pending/{record.id}.md" in git(
            env.ledger, "ls-files"
        ).stdout
        moved = tmp_path / "proj-moved"
        project_repo.rename(moved)

        bucket = host_rebind(env.ledger, str(project_repo), moved)

        tracked = git(env.ledger, "ls-files").stdout
        assert f"projects/{slug_for(moved)}/pending/{record.id}.md" in tracked
        assert old_slug not in tracked  # moved in git, not orphaned
        assert git(env.ledger, "status", "--porcelain").stdout.strip() == ""
        assert (bucket / "pending" / f"{record.id}.md").is_file()

    def test_rebind_by_slug(self, env, tmp_path, project_repo):
        host_add(env.ledger, project_repo, "project")
        create_record(env.ledger, make_knowledge(scope="project"),
                      project_path=project_repo)
        slug = slug_for(project_repo)
        moved = tmp_path / "proj-moved"
        project_repo.rename(moved)

        bucket = host_rebind(env.ledger, slug, moved)

        assert bucket.name == slug_for(moved)

    def test_rebind_validates_the_new_path(self, env, tmp_path, project_repo):
        host_add(env.ledger, project_repo, "project")
        create_record(env.ledger, make_knowledge(scope="project"),
                      project_path=project_repo)
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        with pytest.raises(HostsError, match="not a git repo"):
            host_rebind(env.ledger, str(project_repo), plain)
        with pytest.raises(HostsError, match="does not exist"):
            host_rebind(env.ledger, str(project_repo), tmp_path / "nope")
        with pytest.raises(HostsError, match="IS the ledger home"):
            host_rebind(env.ledger, str(project_repo), env.ledger)

    def test_rebind_refuses_to_fuse_two_buckets(self, env, tmp_path, project_repo):
        other = tmp_path / "other-repo"
        init_repo(other)
        (other / "README.md").write_text("o\n", encoding="utf-8")
        commit_all(other, "seed")
        for repo in (project_repo, other):
            create_record(
                env.ledger,
                make_knowledge(scope="project", record_id=None),
                project_path=repo,
            )
        with pytest.raises(HostsError, match="already exists"):
            host_rebind(env.ledger, str(project_repo), other)

    def test_rebind_cli(self, env, tmp_path, project_repo, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        host_add(env.ledger, project_repo, "project")
        create_record(env.ledger, make_knowledge(scope="project"),
                      project_path=project_repo)
        moved = tmp_path / "proj-moved"
        project_repo.rename(moved)

        rc = cli.main(["host", "rebind", str(project_repo), str(moved)])

        assert rc == 0
        assert "host rebind" in capsys.readouterr().out
        assert moved.resolve() in load_hosts(env.ledger).projects


class TestVanishedHostPreflight:
    def test_route_refuses_before_committing_the_ledger(
        self, env, tmp_path, project_repo
    ):
        """The dangerous shape: a stale hosts.yaml entry whose repo is gone
        passed preflight (target.is_file() False ⇒ dirty check skipped),
        the LEDGER COMMITTED, then write_text failed — drift, no repair."""
        host_add(env.ledger, project_repo, "project")
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=project_repo)
        commit_all(env.ledger, "seed record")
        before = head(env.ledger)
        subprocess.run(["rm", "-rf", str(project_repo)], check=True)

        with pytest.raises(verbs.VerbError, match="does not exist on disk"):
            verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)

        assert head(env.ledger) == before  # nothing committed
        assert (
            env.ledger / "projects" / slug_for(project_repo) / "pending"
            / f"{record.id}.md"
        ).is_file()  # the record stays pending

    def test_refusal_names_rebind(self, env, tmp_path, project_repo):
        host_add(env.ledger, project_repo, "project")
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=project_repo)
        subprocess.run(["rm", "-rf", str(project_repo)], check=True)
        with pytest.raises(verbs.VerbError, match="host rebind"):
            verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)


class TestHostRemove:
    def test_remove_deregisters_but_keeps_records(self, env, project_repo):
        host_add(env.ledger, project_repo, "project")
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=project_repo)

        hosts = host_remove(env.ledger, project_repo)

        assert project_repo.resolve() not in hosts.projects
        assert project_repo.resolve() not in load_hosts(env.ledger).projects
        assert subjects(env.ledger)[0] == (
            f"self-learn: host remove {project_repo.resolve()}"
        )
        # truth is untouched; only the compile gate closed (H-3)
        bucket = env.ledger / "projects" / slug_for(project_repo)
        assert (bucket / "pending" / f"{record.id}.md").is_file()
        with pytest.raises(verbs.VerbError, match="host not registered"):
            verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)

    def test_remove_works_for_a_vanished_repo(self, env, project_repo):
        host_add(env.ledger, project_repo, "project")
        subprocess.run(["rm", "-rf", str(project_repo)], check=True)
        assert project_repo.resolve() not in host_remove(
            env.ledger, project_repo
        ).projects

    def test_remove_unknown_host_refuses(self, env, tmp_path):
        with pytest.raises(HostsError, match="not a registered host"):
            host_remove(env.ledger, tmp_path / "never-registered")

    def test_remove_cli(self, env, project_repo, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        host_add(env.ledger, project_repo, "project")
        assert cli.main(["host", "remove", str(project_repo)]) == 0
        assert "host remove" in capsys.readouterr().out
        assert project_repo.resolve() not in load_hosts(env.ledger).projects


# --------------------------------------------------------------- MAJOR 6


class TestHostsYamlTrust:
    def test_typod_skills_root_never_writes_canon_outside_a_repo(
        self, env, tmp_path
    ):
        """`skills_root: /home/komi/repos` (a plain dir) used to CREATE
        /home/komi/repos/CLAUDE.md and only then fail its git commit."""
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)
        commit_all(env.ledger, "seed record")
        # the hand edit lands AFTER capture: a typo'd root that still has a
        # plugins/*/skills/s tree is the dangerous shape — the compiler
        # resolves a target and writes canon outside any repo.
        typo = tmp_path / "repos"
        (typo / "plugins" / "s-plugin" / "skills" / "s").mkdir(parents=True)
        (typo / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md").write_text(
            "# s skill\n", encoding="utf-8"
        )
        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {typo}\nprojects:\n  - path: {env.host}\n",
            encoding="utf-8",
        )
        commit_all(env.ledger, "hand-edited hosts.yaml")
        before = head(env.ledger)

        with pytest.raises(verbs.VerbError, match="not a git repo"):
            verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)

        assert not (typo / "CLAUDE.md").exists()  # canon never written
        assert head(env.ledger) == before

    def test_host_pointing_at_the_ledger_itself_is_refused(self, env):
        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {env.host}\nprojects:\n  - path: {env.ledger}\n",
            encoding="utf-8",
        )
        commit_all(env.ledger, "hosts.yaml names the ledger")
        record = make_knowledge(scope="project")
        create_record(env.ledger, record, project_path=env.ledger)
        with pytest.raises(verbs.VerbError, match="IS the ledger home"):
            verbs.route(env.ledger, record.id, dest="claude-md", no_push=True)

    def test_host_add_refuses_the_ledger_home(self, env):
        with pytest.raises(HostsError, match="IS the ledger home"):
            host_add(env.ledger, env.ledger, "project")

    def test_host_list_shows_a_broken_entry_marked_broken(
        self, env, tmp_path, monkeypatch, capsys
    ):
        """`list` must SHOW the problem, not explode — exploding hides the
        very thing you ran it to find."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        gone = tmp_path / "gone-repo"
        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {env.host}\nprojects:\n  - path: {gone}\n",
            encoding="utf-8",
        )

        rc = cli.main(["host", "list"])
        out = capsys.readouterr().out

        assert rc == 0
        assert str(gone) in out
        assert "BROKEN" in out
        assert str(env.host) in out  # the sound entry still listed


# --------------------------------------------------------------- MINOR 7


class TestPushGuard:
    def test_route_on_a_remoteless_ledger_exits_zero(
        self, env, monkeypatch, capsys
    ):
        """No remote is not a failure: perfect commits used to exit 3 with
        a loud PUSH FAILED."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        assert not gitops.has_remote(env.ledger)
        record = make_behavior(scope="skill:s")
        create_record(env.ledger, record)

        rc = cli.main(["route", record.id, "--dest", "skill-md"])
        captured = capsys.readouterr()

        assert rc == 0
        assert "PUSH FAILED" not in captured.err
        assert "no remote configured" in captured.out

    def test_teach_route_on_a_remoteless_ledger_exits_zero(
        self, env, monkeypatch, capsys
    ):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        rc = cli.main(
            [
                "teach", "--skill", "s", "--type", "behavior",
                "--kind", "anti-pattern",
                "--trigger", "About to push without a remote.",
                "--instruction", "Guard the push.",
                "--route", "--dest", "skill-md",
            ]
        )
        assert rc == 0
        assert "PUSH FAILED" not in capsys.readouterr().err

    def test_supersede_on_a_remoteless_ledger_exits_zero(self, env, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        old = make_behavior(scope="skill:s", record_id="lrn-0000aaaa")
        new = make_behavior(
            scope="skill:s",
            record_id="lrn-0000bbbb",
            trigger="About to edit .storage anywhere.",
            instruction="Snapshot first.",
        )
        create_record(env.ledger, old)
        create_record(env.ledger, new)
        verbs.route(env.ledger, old.id, dest="skill-md", no_push=True)
        verbs.route(env.ledger, new.id, dest="skill-md", no_push=True)

        assert cli.main(["supersede", old.id, new.id]) == 0


# --------------------------------------------------------------- MINOR 9


class TestCacheMigration:
    def _old_state(self, xdg):
        old = xdg / "claude-skills" / "self-learn"
        (old / "miner").mkdir(parents=True)
        (old / "events.jsonl").write_text("{}\n", encoding="utf-8")
        (old / "miner" / "journal.jsonl").write_text("{}\n", encoding="utf-8")
        return old

    def test_partial_move_is_retried_and_marked_only_when_complete(
        self, tmp_path, monkeypatch
    ):
        """A mid-move failure used to orphan the rest silently, forever:
        the shim only ran when the new dir did not exist."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-a"))
        old = self._old_state(xdg)
        # a directory that cannot be moved: unreadable (chmod 000)
        blocked = old / "spool"
        blocked.mkdir()
        (blocked / "2026-07.host.jsonl").write_text("{}\n", encoding="utf-8")
        blocked.chmod(0o000)
        try:
            new = worker.cache_dir()
            # the movable state DID move; the marker is withheld
            assert (new / "events.jsonl").is_file()
            assert not (new / worker.MIGRATION_MARKER).exists()
            log = (new / "worker.log").read_text(encoding="utf-8")
            assert "FAILED" in log  # never silently swallowed
            assert "will retry" in log
        finally:
            blocked.chmod(0o755)

        # the retry completes the move and marks it done
        new = worker.cache_dir()
        assert (new / "spool" / "2026-07.host.jsonl").is_file()
        assert (new / worker.MIGRATION_MARKER).is_file()

    def test_completed_migration_is_not_repeated(self, tmp_path, monkeypatch):
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-a"))
        old = self._old_state(xdg)

        new = worker.cache_dir()
        assert (new / worker.MIGRATION_MARKER).is_file()

        # new state appears in the OLD path (a stale process); a marked
        # migration never touches it again
        (old / "events.jsonl").write_text("stale\n", encoding="utf-8")
        assert worker.cache_dir() == new
        assert (old / "events.jsonl").read_text(encoding="utf-8") == "stale\n"

    def test_live_lock_and_window_files_are_left_behind(
        self, tmp_path, monkeypatch
    ):
        """A live worker/miner may hold these; moving them out from under
        it is how you get two of them running."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-a"))
        old = self._old_state(xdg)
        (old / "worker.lock").write_text("", encoding="utf-8")
        (old / "worker.window").write_text("4242\n", encoding="utf-8")

        new = worker.cache_dir()

        assert not (new / "worker.window").exists()
        assert (old / "worker.window").is_file()  # left for its holder
        assert (new / worker.MIGRATION_MARKER).is_file()  # still complete

    def test_existing_target_is_never_clobbered(self, tmp_path, monkeypatch):
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-a"))
        old = self._old_state(xdg)
        # newer state already in the namespaced dir
        import hashlib

        digest = hashlib.sha256(
            str((tmp_path / "home-a")).encode("utf-8")
        ).hexdigest()[:8]
        new_dir = xdg / "self-learn" / f"home-{digest}"
        new_dir.mkdir(parents=True)
        (new_dir / "events.jsonl").write_text("newer\n", encoding="utf-8")

        new = worker.cache_dir()

        assert (new / "events.jsonl").read_text(encoding="utf-8") == "newer\n"
        assert (old / "events.jsonl").is_file()  # the old one is left, not lost


# -------------------------------------------------------------- BLOCKER 11


class TestHomeState:
    def test_home_state_classifies(self, tmp_path):
        assert home_state(tmp_path / "nope") == "missing"
        plain = tmp_path / "plain"
        plain.mkdir()
        assert home_state(plain) == "not-a-repo"
        fresh = tmp_path / "fresh"
        init_repo(fresh)
        assert home_state(fresh) == "uninitialized"
        (fresh / "hosts.yaml").write_text("projects: []\n", encoding="utf-8")
        assert home_state(fresh) == "ok"

    def test_initialized_empty_home_is_ok(self, tmp_path):
        home = tmp_path / "home"
        init_repo(home)
        for sub in ("skills", "projects", "user", "telemetry"):
            (home / sub).mkdir()
        assert home_state(home) == "ok"

    @pytest.mark.parametrize("command", (["status"], ["status", "--json"],
                                         ["list"], ["report"]))
    def test_missing_home_is_loud_and_non_zero(
        self, command, tmp_path, monkeypatch, capsys
    ):
        """Was: {"buckets": [], "total_pending": 0}, rc=0 — a wrong
        SELF_LEARN_HOME made every record invisible with no error."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "does-not-exist"))
        rc = cli.main(command)
        err = capsys.readouterr().err
        assert rc == cli.EXIT_NO_HOME
        assert "does not exist" in err
        assert "SELF_LEARN_HOME" in err

    @pytest.mark.parametrize("command", (["status"], ["list"], ["report"]))
    def test_not_a_repo_home_is_loud_and_non_zero(
        self, command, tmp_path, monkeypatch, capsys
    ):
        plain = tmp_path / "plain"
        plain.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(plain))
        rc = cli.main(command)
        assert rc == cli.EXIT_NO_HOME
        assert "not a git repo" in capsys.readouterr().err

    def test_initialized_empty_home_still_reports_all_clear(
        self, tmp_path, monkeypatch, capsys
    ):
        """The legitimate zero state keeps exit 0 — the two must not be
        conflated in EITHER direction."""
        home = tmp_path / "home"
        init_repo(home)
        (home / "hosts.yaml").write_text("projects: []\n", encoding="utf-8")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        rc = cli.main(["status", "--json"])

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["total_pending"] == 0

    def test_status_fast_keeps_json_and_carries_home_state(
        self, tmp_path, monkeypatch, capsys
    ):
        """The bash hook jq-parses stdout: it must stay valid JSON even
        for a broken home, with the state in the payload."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "does-not-exist"))
        rc = cli.main(["status", "--fast"])
        out = capsys.readouterr().out

        assert rc == cli.EXIT_NO_HOME
        payload = json.loads(out)  # valid JSON, not a traceback
        assert payload["home_state"] == "missing"
        assert payload["total_pending"] == 0

    def test_status_fast_ok_home_carries_home_state(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        assert cli.main(["status", "--fast"]) == 0
        assert json.loads(capsys.readouterr().out)["home_state"] == "ok"

    def test_teach_into_a_missing_home_writes_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        """Was: created the dirs, wrote the record, THEN failed the commit —
        an untracked record in a non-repo dir nobody will ever push."""
        home = tmp_path / "does-not-exist"
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        rc = cli.main(
            [
                "teach", "--type", "knowledge",
                "--fact", "The router reserves .232 for the Nova.",
                "--user",
            ]
        )

        assert rc != 0
        assert not home.exists()  # nothing created, nothing written
        assert "does not exist" in capsys.readouterr().err

    def test_teach_into_a_non_repo_home_writes_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "plain"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        rc = cli.main(
            [
                "teach", "--type", "knowledge",
                "--fact", "The router reserves .232 for the Nova.",
                "--user",
            ]
        )

        assert rc != 0
        assert list(home.iterdir()) == []  # not even a bucket dir
        assert "not a git repo" in capsys.readouterr().err

    def test_valid_home_still_auto_creates_a_missing_bucket(self, env, monkeypatch):
        """The gate must not break the ordinary case: a bucket dir that
        does not exist yet is created on demand."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        assert not (env.ledger / "user" / "pending").exists()
        record = make_knowledge(scope="user")
        path = create_record(env.ledger, record)
        assert path.is_file()

    def test_miner_refuses_a_missing_home(self, tmp_path, monkeypatch):
        from self_learn import miner

        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        home = tmp_path / "does-not-exist"
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        result = miner.run(home)

        assert result.status == "failed"  # never mines into the void
        assert not home.exists()
        entries = [
            json.loads(line)
            for line in (
                miner.miner_dir() / "journal.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert entries[-1]["status"] == "failed"
        assert "does not exist" in entries[-1]["reason"]
