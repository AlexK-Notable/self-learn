"""T7 resolution verbs: route / reject / defer / graduate / supersede +
sentinel wiring + commit/push (08 §1 Resolution-verbs, Secret-scan P2-7,
Sentinel-scoping, Push, Corrective-supersession, Managed-section-bootstrap
pins; 02 §2 pinned commit formats).

All git activity happens in sandbox repos under tmpdirs with bare remotes;
the sentinel is XDG-redirected; chezmoi is a PATH shim.
"""

import os
import stat
import subprocess
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from self_learn import gitops, sentinel, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.ledger_ops import LedgerOpsError, create_record, write_proposal
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_home, proposal_dict

OLD = "lrn-0000aaaa"
NEW = "lrn-0000bbbb"

SKILL_MD = "# s skill\n\nAuthored prose stays put.\n"

CHEZMOI_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CHEZMOI_SHIM_LOG"
case "$1" in
  diff) printf '%s' "${CHEZMOI_SHIM_DIFF-}" ;;
  git) if [ "$3" = "status" ]; then printf '%s' "${CHEZMOI_SHIM_STATUS-}"; fi ;;
esac
exit "${CHEZMOI_SHIM_EXIT-0}"
"""


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel goes to a per-test XDG cache, never the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


class Env:
    def __init__(self, tmp_path):
        self.home = make_home(tmp_path)
        self.skill_dir = self.home / "plugins" / "s-plugin" / "skills" / "s"
        self.skill_md = self.skill_dir / "SKILL.md"
        self.skill_md.write_text(SKILL_MD, encoding="utf-8")
        self.bare = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.bare)],
            check=True,
        )
        git(self.home, "remote", "add", "origin", str(self.bare))
        commit_all(self.home, "seed")
        git(self.home, "push", "-q", "-u", "origin", "main")

    # -- inspection helpers ------------------------------------------------

    def local_subject(self):
        return git(self.home, "log", "-1", "--format=%s").stdout.strip()

    def local_body(self):
        return git(self.home, "log", "-1", "--format=%B").stdout

    def remote_subject(self):
        return git(self.bare, "log", "-1", "--format=%s").stdout.strip()

    def remote_files(self):
        return git(self.bare, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()

    def remote_show(self, relpath):
        return git(self.bare, "show", f"HEAD:{relpath}").stdout

    def committed_files(self):
        return git(
            self.home, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()

    def pending(self, rid):
        return self.skill_dir / ".self-learn" / "pending" / f"{rid}.md"

    def resolved(self, rid):
        return self.skill_dir / ".self-learn" / "resolved" / f"{rid}.md"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def seed(env, rid=OLD, scope="skill:s", supersedes=None):
    record = make_behavior(scope=scope, record_id=rid)
    if supersedes:
        record.set_supersedes(supersedes)
    return create_record(env.home, record)


@pytest.fixture
def chezmoi_shim(tmp_path, monkeypatch):
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    fake = bindir / "chezmoi"
    fake.write_text(CHEZMOI_SHIM, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "chezmoi-argv.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CHEZMOI_SHIM_LOG", str(log))

    def calls():
        return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]

    return calls


# ------------------------------------------------------------------- route


class TestRouteDoD:
    def test_create_route_push_round_trip(self, env):
        """T7 DoD: the sandbox remote ends with the record in resolved/,
        the compiled section, and one pinned-message commit."""
        seed(env)
        result = verbs.route(env.home, OLD, dest="skill-md")

        message = f"self-learn: route {OLD} → skill-md"
        assert result.commit_message == message
        assert result.push is not None and result.push.ok
        assert env.remote_subject() == message
        rel = f"plugins/s-plugin/skills/s/.self-learn/resolved/{OLD}.md"
        assert rel in env.remote_files()
        remote_skill = env.remote_show("plugins/s-plugin/skills/s/SKILL.md")
        assert BEGIN_MARKER in remote_skill and END_MARKER in remote_skill
        assert OLD in remote_skill
        # local ledger agrees
        assert not env.pending(OLD).exists()
        record = Record.from_path(env.resolved(OLD))
        assert record.status == "routed"
        assert record.routing["destination"] == "skill-md"
        assert record.routing["by"] == "human"
        assert record.routing["routed_at"] is not None

    def test_first_route_bootstraps_markerless_skill_md(self, env):
        seed(env)
        result = verbs.route(env.home, OLD, dest="skill-md")
        text = env.skill_md.read_text(encoding="utf-8")
        assert text.startswith(SKILL_MD.rstrip("\n"))  # authored text preserved
        assert text.index(BEGIN_MARKER) < text.index(END_MARKER)
        assert result.compile_result.bootstrapped


class TestRouteDestination:
    def test_proposal_destination_honored(self, env):
        seed(env)
        write_proposal(env.home, OLD, proposal_dict(destination="reference"))

        result = verbs.route(env.home, OLD)

        assert result.commit_message == f"self-learn: route {OLD} → reference"
        learnings = env.skill_dir / "references" / "LEARNINGS.md"
        assert learnings.is_file() and OLD in learnings.read_text(encoding="utf-8")
        # proposal sibling removed at resolution, and the commit carries it
        assert not (env.skill_dir / ".self-learn" / "proposals" / f"{OLD}.yaml").exists()

    def test_dest_overrides_proposal(self, env):
        seed(env)
        write_proposal(env.home, OLD, proposal_dict(destination="reference"))

        result = verbs.route(env.home, OLD, dest="skill-md")

        assert result.commit_message == f"self-learn: route {OLD} → skill-md"
        assert OLD in env.skill_md.read_text(encoding="utf-8")
        assert not (env.skill_dir / "references" / "LEARNINGS.md").exists()

    def test_no_proposal_no_dest_errors(self, env):
        seed(env)
        with pytest.raises(verbs.NoProposalError, match="no proposal"):
            verbs.route(env.home, OLD)
        assert env.pending(OLD).exists()
        assert env.local_subject() == "seed"  # nothing committed

    @pytest.mark.parametrize("dest", ["new-skill", "hook"])
    def test_m3_destinations_exit_2(self, env, dest):
        seed(env)
        with pytest.raises(verbs.DestinationNotBuilt) as exc:
            verbs.route(env.home, OLD, dest=dest)
        assert exc.value.exit_code == 2
        assert env.pending(OLD).exists()

    def test_bogus_dest_rejected(self, env):
        seed(env)
        with pytest.raises(verbs.VerbError, match="--dest must be one of"):
            verbs.route(env.home, OLD, dest="banana")

    def test_project_scope_claude_md_created_on_first_route(self, env):
        """Judgment call under test: a repo with no CLAUDE.md gets one
        created + bootstrapped on the first claude-md route."""
        record = make_behavior(scope="project", record_id=OLD)
        create_record(env.home, record)

        result = verbs.route(env.home, OLD, dest="claude-md")

        target = env.home / "CLAUDE.md"
        assert target.is_file()
        text = target.read_text(encoding="utf-8")
        assert BEGIN_MARKER in text and OLD in text
        assert "CLAUDE.md" in env.committed_files()
        assert result.commit_message == f"self-learn: route {OLD} → claude-md"


class TestRouteGuards:
    def test_dirty_target_abort(self, env):
        seed(env)
        env.skill_md.write_text(SKILL_MD + "\nuncommitted edit\n", encoding="utf-8")

        with pytest.raises(verbs.DirtyTargetError, match="commit/stash first"):
            verbs.route(env.home, OLD, dest="skill-md")

        assert env.pending(OLD).exists()  # record untouched
        assert env.local_subject() == "seed"
        # the dirty edit is still there, unclobbered
        assert "uncommitted edit" in env.skill_md.read_text(encoding="utf-8")

    def test_p2_7_secret_refusal_full_record_file(self, env):
        """Seed a secret into the pending record body (a write that
        bypassed CLI verbs): route must refuse, file byte-unchanged."""
        path = seed(env)
        text = path.read_text(encoding="utf-8")
        poisoned = text.replace(
            "Stop the container first.",
            "Stop the container first. password = hunter2secret99",
        )
        path.write_text(poisoned, encoding="utf-8")

        with pytest.raises(verbs.SecretRefusal) as exc:
            verbs.route(env.home, OLD, dest="skill-md")

        assert "credential-assignment" in str(exc.value)
        assert "password = hunter2secret99" in str(exc.value)
        assert path.read_text(encoding="utf-8") == poisoned  # nothing written
        assert env.pending(OLD).exists()
        assert env.local_subject() == "seed"
        assert BEGIN_MARKER not in env.skill_md.read_text(encoding="utf-8")

    def test_note_is_scanned_too(self, env):
        seed(env)
        with pytest.raises(verbs.SecretRefusal):
            verbs.route(
                env.home, OLD, dest="skill-md", note="key is ghp_" + "a" * 36
            )
        assert env.pending(OLD).exists()


class TestRouteCommit:
    def test_note_lands_in_commit_body_and_record(self, env):
        seed(env)
        verbs.route(env.home, OLD, dest="skill-md", note="the why")

        assert env.local_body().startswith(
            f"self-learn: route {OLD} → skill-md\n\nthe why"
        )
        assert Record.from_path(env.resolved(OLD)).resolution_note == "the why"

    def test_targeted_staging_leaves_unrelated_dirt(self, env):
        notes = env.home / "notes.md"
        notes.write_text("original\n", encoding="utf-8")
        commit_all(env.home, "add notes")
        git(env.home, "push", "-q")
        notes.write_text("dirty edit\n", encoding="utf-8")  # unrelated dirt
        seed(env)

        verbs.route(env.home, OLD, dest="skill-md")

        assert "notes.md" not in env.committed_files()
        status = git(env.home, "status", "--porcelain", "--", "notes.md").stdout
        assert status.strip().startswith("M")  # still dirty in the worktree

    def test_no_push_leaves_commit_local_and_bare_push_publishes(self, env):
        seed(env)
        result = verbs.route(env.home, OLD, dest="skill-md", no_push=True)

        assert result.push is None
        message = f"self-learn: route {OLD} → skill-md"
        assert env.local_subject() == message
        assert env.remote_subject() == "seed"  # not published yet

        push = verbs.push_pending(env.home)
        assert push.ok
        assert env.remote_subject() == message

    def test_push_retry_after_non_ff(self, tmp_path, env):
        other = tmp_path / "clone2"
        subprocess.run(["git", "clone", "-q", str(env.bare), str(other)], check=True)
        git(other, "config", "user.email", "o@example.com")
        git(other, "config", "user.name", "O")
        (other / "elsewhere.md").write_text("x\n", encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "remote work")
        git(other, "push", "-q")

        seed(env)
        result = verbs.route(env.home, OLD, dest="skill-md")

        assert result.push.ok and result.push.retried
        subjects = git(env.bare, "log", "--format=%s").stdout
        assert f"self-learn: route {OLD} → skill-md" in subjects
        assert "remote work" in subjects


class TestRouteSupersedes:
    def test_completion_at_route_same_commit(self, env):
        seed(env, rid=OLD)
        verbs.route(env.home, OLD, dest="skill-md")
        seed(env, rid=NEW, supersedes=OLD)

        result = verbs.route(env.home, NEW, dest="skill-md")

        message = f"self-learn: route {NEW} → skill-md (supersedes {OLD})"
        assert result.commit_message == message
        assert env.local_subject() == message
        # both record files ride the SAME commit
        committed = env.committed_files()
        assert f"plugins/s-plugin/skills/s/.self-learn/resolved/{NEW}.md" in committed
        assert f"plugins/s-plugin/skills/s/.self-learn/resolved/{OLD}.md" in committed
        # old record: superseded_by + still in resolved/
        old = Record.from_path(env.resolved(OLD))
        assert old.status == "superseded"
        assert old.superseded_by == NEW
        # the compiled section carries the new lesson, not the old one
        skill = env.skill_md.read_text(encoding="utf-8")
        assert NEW in skill and OLD not in skill


class TestRouteUserScope:
    def test_user_claude_md_goes_through_chezmoi_flow(self, tmp_path, env, chezmoi_shim):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=OLD)
        create_record(env.home, record)

        message = f"self-learn: route {OLD} → claude-md"
        result = verbs.route(
            env.home, OLD, dest="claude-md", user_claude_md=target
        )

        # chezmoi guarded sequence ran, with the pinned message
        calls = chezmoi_shim()
        assert f"diff {target}" in calls
        assert f"re-add {target}" in calls
        assert f"git -- commit -m {message}" in calls
        assert "git -- push" in calls
        # the real target got the section
        text = target.read_text(encoding="utf-8")
        assert BEGIN_MARKER in text and OLD in text
        # ledger commit in the home repo, same pinned message; the target
        # itself lives in the dotfiles repo, so it is NOT in this commit
        assert env.local_subject() == message
        assert (env.home / ".self-learn" / "resolved" / f"{OLD}.md").is_file()
        assert result.compile_result.committed


# ------------------------------------------------------- non-routing verbs


class TestReject:
    def test_pinned_message_and_move(self, env):
        seed(env)
        result = verbs.reject(env.home, OLD, note="not a real lesson")

        message = f"self-learn: reject {OLD}"
        assert result.commit_message == message
        assert env.local_body().startswith(f"{message}\n\nnot a real lesson")
        record = Record.from_path(env.resolved(OLD))
        assert record.status == "rejected"
        assert record.resolution_note == "not a real lesson"
        assert env.remote_subject() == message


class TestDefer:
    def test_explicit_until_pinned_message(self, env):
        seed(env)
        result = verbs.defer(env.home, OLD, until="2026-12-01", note="revisit later")

        assert result.commit_message == f"self-learn: defer {OLD} until 2026-12-01"
        assert env.local_body().startswith(
            f"self-learn: defer {OLD} until 2026-12-01\n\nrevisit later"
        )
        # deferral is not a resolution: the record STAYS in pending/
        record = Record.from_path(env.pending(OLD))
        assert record.status == "deferred"
        assert str(record.deferred_until) == "2026-12-01"
        assert record.deferred_count == 1
        assert record.resolution_note is None  # note rides the commit only

    def test_default_is_plus_30_days(self, env):
        seed(env)
        result = verbs.defer(env.home, OLD)

        record = Record.from_path(env.pending(OLD))
        until = date.fromisoformat(str(record.deferred_until))
        expected = (datetime.now(timezone.utc) + timedelta(days=30)).date()
        assert abs((until - expected).days) <= 1
        assert result.commit_message == f"self-learn: defer {OLD} until {until}"


class TestGraduate:
    def test_pending_already_canon_flavor(self, env):
        seed(env)
        result = verbs.graduate(env.home, OLD, note="already covered by canon")

        assert result.commit_message == f"self-learn: graduate {OLD}"
        record = Record.from_path(env.resolved(OLD))
        assert record.status == "superseded"
        assert record.superseded_by == "canon"
        assert record.resolution_note == "already covered by canon"

    def test_routed_hand_weave_flavor(self, env):
        seed(env)
        verbs.route(env.home, OLD, dest="skill-md")

        result = verbs.graduate(env.home, OLD)

        record = Record.from_path(env.resolved(OLD))
        assert record.status == "superseded"
        assert record.superseded_by == "canon"
        assert env.remote_subject() == f"self-learn: graduate {OLD}"
        assert result.push.ok


class TestSupersedeVerb:
    def test_pending_old(self, env):
        seed(env, rid=OLD)
        seed(env, rid=NEW)

        result = verbs.supersede(env.home, OLD, NEW)

        assert result.commit_message == f"self-learn: supersede {OLD} → {NEW}"
        old = Record.from_path(env.resolved(OLD))
        assert old.status == "superseded" and old.superseded_by == NEW
        assert env.pending(NEW).exists()  # metadata-only: new untouched

    def test_routed_old(self, env):
        seed(env, rid=OLD)
        verbs.route(env.home, OLD, dest="skill-md")
        seed(env, rid=NEW)

        verbs.supersede(env.home, OLD, NEW, note="lesson was wrong")

        old = Record.from_path(env.resolved(OLD))
        assert old.status == "superseded" and old.superseded_by == NEW
        assert old.resolution_note == "lesson was wrong"

    def test_replacement_must_exist(self, env):
        seed(env, rid=OLD)
        with pytest.raises(LedgerOpsError, match="not found"):
            verbs.supersede(env.home, OLD, "lrn-0000dead")

    def test_self_supersession_refused(self, env):
        seed(env, rid=OLD)
        with pytest.raises(verbs.VerbError, match="itself"):
            verbs.supersede(env.home, OLD, OLD)


# ------------------------------------------------------------- sentinel use


class TestVerbSentinel:
    def test_self_hold_created_and_released(self, env):
        seed(env)
        assert not sentinel.sentinel_path().exists()

        result = verbs.reject(env.home, OLD)

        assert result.sentinel_owned
        assert not sentinel.sentinel_path().exists()  # released after

    def test_preexisting_live_hold_heartbeated_not_released(self, env):
        path = sentinel.sentinel_path()
        path.parent.mkdir(parents=True)
        content = "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n"
        path.write_text(content, encoding="utf-8")
        past = time.time() - 600
        os.utime(path, (past, past))
        seed(env)

        result = verbs.reject(env.home, OLD)

        assert not result.sentinel_owned
        assert path.exists()  # another holder's sentinel survives the verb
        assert path.read_text(encoding="utf-8") == content
        assert path.stat().st_mtime > past + 1  # every mutating verb re-touches

    def test_stale_sentinel_taken_over_and_released(self, env):
        path = sentinel.sentinel_path()
        path.parent.mkdir(parents=True)
        path.write_text(
            "pid=99999 host=elsewhere started=2026-07-13T00:00:00Z\n",
            encoding="utf-8",
        )
        past = time.time() - (sentinel.SENTINEL_TTL_SECONDS + 60)
        os.utime(path, (past, past))
        seed(env)

        result = verbs.reject(env.home, OLD)

        assert result.sentinel_owned  # stale = ignorable, we took it
        assert not path.exists()  # and released our own hold

    def test_released_even_when_verb_aborts(self, env):
        seed(env)
        env.skill_md.write_text(SKILL_MD + "dirt\n", encoding="utf-8")
        with pytest.raises(verbs.DirtyTargetError):
            verbs.route(env.home, OLD, dest="skill-md")
        assert not sentinel.sentinel_path().exists()


# ------------------------------------------------------------ push failure


class TestVerbPushFailure:
    def test_loud_failure_keeps_commit_then_push_pending_recovers(
        self, tmp_path, env, capsys
    ):
        git(env.home, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        seed(env)

        result = verbs.route(env.home, OLD, dest="skill-md")

        assert not result.push.ok
        assert result.push.exit_code == gitops.EXIT_PUSH_FAILED
        assert "PUSH FAILED" in capsys.readouterr().err
        message = f"self-learn: route {OLD} → skill-md"
        assert env.local_subject() == message  # commit kept

        git(env.home, "remote", "set-url", "origin", str(env.bare))
        assert verbs.push_pending(env.home).ok
        assert env.remote_subject() == message
