"""U20 — F5-5 guided commit-first: ``self-learn host commit-drift`` (08 §1
Commit-drift-verb pin; f5-round-spec.md §2.1).

The dirty-target refusal stays fully intact — this verb is the GUIDED
path a human takes instead of it: commit the TARGET repo's OWN pending
changes (their commit, separate from ours), so the caller can retry its
route. Dirty-vs-drift boundary (gate M2) is the load-bearing distinction:
DRIFT (the old dotfiles-management pre-existing-drift leg, retired along
with that module — U-hostmode Phase 2) was refused with a plain
explanation and NEVER committed; only DIRTY (uncommitted changes) is
served.

All git activity happens in sandbox repos under pytest tmpdirs.
Every plain host, user scope included, refuses this verb identically at
exit 64 (CD1), with no PATH shim left to simulate anything against; the
refusal is pinned once, by
``test_a_plain_host_refuses_with_the_whole_cd1_message`` below.
"""

from __future__ import annotations

import json

import pytest

from self_learn import cli, verbs
from self_learn.ledger_ops import create_record, write_proposal
from support import commit_all, git, init_repo, make_behavior, make_env, proposal_dict

RID = "lrn-0000cafe"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))



class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir
        self.skill_md = sandbox.skill_md
        self.bucket = self.home / "skills" / "s"

    def pending(self, rid):
        return self.bucket / "pending" / f"{rid}.md"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def seed(env, rid=RID, scope="skill:s", dest="skill-md"):
    record = make_behavior(scope=scope, record_id=rid)
    create_record(env.home, record)
    write_proposal(env.home, rid, proposal_dict(destination=dest))
    return record


# --------------------------------------------------------------- gitops leg


class TestGitopsLeg:
    def test_dirty_target_committed_scoped_unrelated_file_excluded(self, env):
        """gate m8: an unrelated dirty file in the SAME repo must NOT ride
        the pinned-subject commit — the add is target-path scoped, never
        ``-A``."""
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        unrelated = env.host / "README.md"
        unrelated.write_text("unrelated pending work\n", encoding="utf-8")

        result = verbs.commit_drift(env.home, RID)

        assert result.commit_sha is not None
        assert not result.dry_run
        assert result.repo == env.host
        assert str(env.skill_md.relative_to(env.host)) in "\n".join(result.files) or any(
            env.skill_md.name in f for f in result.files
        )
        committed = git(
            env.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()
        assert "plugins/s-plugin/skills/s/SKILL.md" in committed
        assert "README.md" not in committed  # unrelated dirty file excluded
        subject = git(env.host, "log", "-1", "--format=%s").stdout.strip()
        assert subject == verbs.COMMIT_DRIFT_SUBJECT
        # README.md is STILL dirty/untracked afterward — untouched
        status = git(env.host, "status", "--porcelain").stdout
        assert "README.md" in status

    def test_clean_repo_refused_no_commit(self, env):
        seed(env)
        before = git(env.host, "rev-parse", "HEAD").stdout.strip()

        with pytest.raises(verbs.VerbError, match="nothing to commit"):
            verbs.commit_drift(env.home, RID)

        assert git(env.host, "rev-parse", "HEAD").stdout.strip() == before

    def test_out_of_scope_path_refused(self, env, tmp_path):
        """A project bucket whose recorded host was never registered — the
        SAME resolution route's own failure would hit refuses too (no
        arbitrary-repo commit surface)."""
        proj = tmp_path / "unregistered-project"
        init_repo(proj)
        (proj / "README.md").write_text("x\n", encoding="utf-8")
        commit_all(proj, "seed")
        record = make_behavior(scope="project", record_id=RID)
        create_record(env.home, record, project_path=proj)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))

        with pytest.raises(verbs.VerbError, match="not registered"):
            verbs.commit_drift(env.home, RID)

    def test_dry_run_lists_files_writes_nothing(self, env):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        before = git(env.host, "rev-parse", "HEAD").stdout.strip()

        result = verbs.commit_drift(env.home, RID, dry_run=True)

        assert result.dry_run
        assert result.commit_sha is None
        assert any("SKILL.md" in f for f in result.files)
        assert git(env.host, "rev-parse", "HEAD").stdout.strip() == before
        status = git(env.host, "status", "--porcelain").stdout
        assert "SKILL.md" in status  # still dirty — nothing written

    def test_hook_destination_refused(self, env):
        seed(env, dest="skill-md")  # base seed unused; overwritten below
        write_proposal(env.home, RID, proposal_dict(destination="skill-md"))
        with pytest.raises(verbs.VerbError, match="commit-drift"):
            verbs.commit_drift(env.home, RID, dest="hook")


# ------------------------------------------------------- plain-host refusal


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_plain_host_refuses_with_the_whole_cd1_message(env, tmp_path, dry_run):
    """U-hostmode §4.7/CD1: user scope is a first-class PLAIN host, and
    EVERY plain host refuses this verb identically at exit 64, regardless
    of the on-disk state that used to distinguish dirty/drift/clean.
    Replaces five tests that made this one call on this one fixture and
    each matched a different fragment of the one message (test audit
    L6-43): all three fragments are asserted here, and `--dry-run` runs
    every precondition, this refusal included, so a plain host refuses
    BEFORE dry_run can matter."""
    target = tmp_path / "dot-claude" / "CLAUDE.md"
    target.parent.mkdir()
    target.write_text("# user conduct\n", encoding="utf-8")
    record = make_behavior(scope="user", record_id=RID)
    create_record(env.home, record)
    write_proposal(env.home, RID, proposal_dict(destination="claude-md"))

    with pytest.raises(verbs.VerbError) as excinfo:
        verbs.commit_drift(env.home, RID, user_claude_md=target, dry_run=dry_run)
    message = str(excinfo.value)
    assert "is a PLAIN host" in message
    assert "nothing for this verb to commit" in message
    assert "the file is yours to manage" in message
    # the target's own bytes are untouched
    assert target.read_text(encoding="utf-8") == "# user conduct\n"


# ------------------------------------------------------------- markers/gate


class TestMarkersLoadBearing:
    def test_gitops_dirty_message_carries_the_extracted_marker(self, env):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        with pytest.raises(verbs.DirtyTargetError) as excinfo:
            verbs.route(env.home, RID, dest="skill-md")
        assert verbs.GITOPS_DIRTY_MARKER in str(excinfo.value)


# -------------------------------------------------------------------- CLI


class TestCliDispatch:
    def test_commit_drift_success_exit_0(self, env, monkeypatch):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rc = cli.main(["host", "commit-drift", RID])
        assert rc == 0

    def test_commit_drift_clean_exit_64(self, env, monkeypatch, capsys):
        seed(env)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rc = cli.main(["host", "commit-drift", RID])
        assert rc == cli.EXIT_USAGE
        assert rc == 64
        assert "nothing to commit" in capsys.readouterr().err

    def test_commit_drift_dry_run_json(self, env, monkeypatch, capsys):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rc = cli.main(["host", "commit-drift", RID, "--dry-run", "--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["repo"] == str(env.host)
        assert any("SKILL.md" in f for f in out["files"])
        # nothing committed
        assert git(
            env.host, "status", "--porcelain"
        ).stdout.strip() != ""

    def test_commit_drift_drift_exit_64(
        self, env, tmp_path, monkeypatch, capsys
    ):
        """gate M2, strengthened: exit 64 alone is also what a CLEAN repo
        produces — the load-bearing fact is that the refusal names a
        REASON on stderr (never a bare exit code). U-hostmode §4.7/CD2
        (rewritten, name kept — §2.10b census): there is no chezmoi
        "drift" left to distinguish from "dirty"/"clean" on a plain
        host — self-learn commits nothing there under ANY on-disk state,
        so a single CD1 refusal text now covers every case this test
        used to need chezmoi's DIFF/STATUS shims to trigger separately.
        Asserts the real constant, never a hand-copied string."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))

        import self_learn.verbs as verbs_mod

        monkeypatch.setattr(verbs_mod, "DEFAULT_USER_CLAUDE_MD", target)
        rc = cli.main(["host", "commit-drift", RID])
        assert rc == 64
        err = capsys.readouterr().err
        assert "is a PLAIN host" in err
        assert "nothing for this verb to commit" in err
        # never committed — the target's own bytes are untouched
        assert target.read_text(encoding="utf-8") == "# user conduct\n"


# ------------------------------------------------ new-skill compound target


MARKETPLACE_SEED = {
    "name": "sandbox-skills",
    "plugins": [
        {
            "name": "s-plugin",
            "source": "./plugins/s-plugin",
            "description": "seeded plugin",
            "version": "1.0.0",
        }
    ],
}

SKILL_NAME = "mouse-firmware"
SEED_RID = "lrn-0000feed"


class TestNewSkillCompoundTarget:
    """Blind-gate fold 1: ``_resolve_target``'s new-skill branch
    dirty-checks BOTH the scaffolded SKILL.md AND ``marketplace.json``
    (``for probe in (target, marketplace)``, verbs.py) — so a route can
    be refused on marketplace dirt alone. ``commit_drift`` must cover the
    SAME compound target, never just the SKILL.md half (else
    marketplace-only dirt dead-ends as a false NOTHING_TO_COMMIT)."""

    def _scaffold(self, env) -> tuple:
        marketplace = env.host / ".claude-plugin" / "marketplace.json"
        marketplace.parent.mkdir(exist_ok=True)
        marketplace.write_text(
            json.dumps(MARKETPLACE_SEED, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "marketplace seed")
        seed_record = make_behavior(scope="skill:s", record_id=SEED_RID)
        create_record(env.home, seed_record)
        verbs.route(env.home, SEED_RID, dest=f"new-skill:{SKILL_NAME}")
        skill_md = (
            env.host / "plugins" / SKILL_NAME / "skills" / SKILL_NAME / "SKILL.md"
        )
        return marketplace, skill_md

    def _seed_target_record(self, env, rid: str = RID) -> None:
        record = make_behavior(
            scope="skill:s", record_id=rid, trigger="About to re-flash firmware."
        )
        create_record(env.home, record)

    def test_marketplace_only_dirt_listed_dry_run_committed_retry_proceeds(
        self, env
    ) -> None:
        marketplace, skill_md = self._scaffold(env)
        self._seed_target_record(env)
        marketplace.write_text(
            marketplace.read_text(encoding="utf-8").replace("1.0.0", "1.0.1"),
            encoding="utf-8",
        )

        dry = verbs.commit_drift(
            env.home, RID, dest=f"new-skill:{SKILL_NAME}", dry_run=True
        )
        assert any("marketplace.json" in f for f in dry.files)
        assert not any("SKILL.md" in f for f in dry.files)
        assert dry.commit_sha is None

        result = verbs.commit_drift(env.home, RID, dest=f"new-skill:{SKILL_NAME}")
        assert result.commit_sha is not None
        committed = git(
            env.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()
        assert ".claude-plugin/marketplace.json" in committed
        assert f"plugins/{SKILL_NAME}/skills/{SKILL_NAME}/SKILL.md" not in committed

        # the dirty-target refusal is gone — the retry proceeds.
        verbs.route(env.home, RID, dest=f"new-skill:{SKILL_NAME}")
        assert f"*({RID})*" in skill_md.read_text(encoding="utf-8")

    def test_both_dirty_both_committed(self, env) -> None:
        marketplace, skill_md = self._scaffold(env)
        self._seed_target_record(env)
        marketplace.write_text(
            marketplace.read_text(encoding="utf-8").replace("1.0.0", "2.0.0"),
            encoding="utf-8",
        )
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8") + "\nstray edit\n", encoding="utf-8"
        )

        result = verbs.commit_drift(env.home, RID, dest=f"new-skill:{SKILL_NAME}")

        committed = git(
            env.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()
        assert ".claude-plugin/marketplace.json" in committed
        assert f"plugins/{SKILL_NAME}/skills/{SKILL_NAME}/SKILL.md" in committed
        assert any("marketplace.json" in f for f in result.files)
        assert any("SKILL.md" in f for f in result.files)

    def test_unrelated_file_still_excluded_regression(self, env) -> None:
        marketplace, skill_md = self._scaffold(env)
        self._seed_target_record(env)
        marketplace.write_text(
            marketplace.read_text(encoding="utf-8").replace("1.0.0", "3.0.0"),
            encoding="utf-8",
        )
        unrelated = env.host / "README.md"
        unrelated.write_text("unrelated pending work\n", encoding="utf-8")

        verbs.commit_drift(env.home, RID, dest=f"new-skill:{SKILL_NAME}")

        committed = git(
            env.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()
        assert "README.md" not in committed
        status = git(env.host, "status", "--porcelain").stdout
        assert "README.md" in status  # still dirty, untouched
