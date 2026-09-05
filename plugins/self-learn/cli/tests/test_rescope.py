"""u-rescope: the `rescope` verb (docs/specs/self-learn/drafts/
u-rescope-user-to-skill-spec.md) — moving a PENDING (or `deferred`)
record between the `user` bucket and a `skills/<name>` bucket, rewriting
`scope:` in the same motion.

Covers: the move itself (one ledger commit, pinned subject, scope
rewritten, --note → commit body only, body/lifecycle fields survive), a
deferred record moving and staying deferred, target bucket dirs created
when absent, no meta.yaml for user/skill targets, the proposal-sibling
sweep (never left behind, never carried) with its disclosure
(R-DISCLOSE-1 in `post_notes`/stdout, R-DISCLOSE-2 in the commit body),
the merge-cluster sweep, the rescoped record reading as unanalyzed in
its new bucket, every refusal's exit code and trigger (unknown id · not
pending/deferred · project-scoped source · project target · unknown /
ambiguous / unregistered skill name · bare `skill`/`skill:` · same
scope · skill→skill · destination collision · secret scan · missing
home), the bucket-vs-frontmatter authority test (§4.1/§6.2 step 5),
the CLI arg surface (`self-learn rescope <id> --to <scope>`), ledger
discipline (exactly one commit, half-written exit 7, --no-push, no
telemetry event spooled), the mv-first crash-window ordering (§6.4 — a
kill between `git mv` and `record.write` leaves a `reconcile`-blocked
staged rename, never a silently-committable modified file; a second
test witnesses the call order directly, independent of which step is
made to raise), and the disclosure line's non-zero-only rule
(R-DISCLOSE-1 — a merge-only sweep never claims a proposal, a
proposal-only sweep never claims a merge cluster).

Sandbox git repos under tmpdirs; the sentinel is XDG-redirected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import cli, ledger_ops, telemetry, verbs
from self_learn import reconcile as reconcile_mod
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import (
    LedgerOpsError,
    create_record,
    defer_record,
    is_unanalyzed,
    proposal_info,
    queue,
    write_proposal,
)
from self_learn.records import Record
from support import (
    commit_all,
    failing_git_shim,
    git,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
    verb_files,
    verb_subject,
)


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel (and telemetry's spool) go to a per-test XDG cache, never
    the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


def head_files(repo: Path) -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()


def spool_lines() -> list[str]:
    sd = telemetry.spool_dir()
    if not sd.is_dir():
        return []
    out: list[str] = []
    for path in sorted(sd.glob("*.jsonl")):
        out.extend(path.read_text(encoding="utf-8").splitlines())
    return out


class Env:
    """A ledger with TWO registered skills (``s``, ``t``) under a
    registered skills root, plus the `user` bucket — the doc-13 sandbox
    fixture surface (`support.make_env`)."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path, skills=("s", "t"))
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.bucket_user = self.home / "user"
        self.bucket_s = self.home / "skills" / "s"
        self.bucket_t = self.home / "skills" / "t"

    def seed_user_record(self, record=None) -> Record:
        record = record if record is not None else make_knowledge(scope="user")
        create_record(self.home, record)
        commit_all(self.home, "record seed")
        return record

    def seed_skill_record(self, name="s", record=None) -> Record:
        record = (
            record if record is not None else make_behavior(scope=f"skill:{name}")
        )
        create_record(self.home, record)
        commit_all(self.home, "record seed")
        return record

    def pending_user(self, rid) -> Path:
        return self.bucket_user / "pending" / f"{rid}.md"

    def pending_s(self, rid) -> Path:
        return self.bucket_s / "pending" / f"{rid}.md"

    def pending_t(self, rid) -> Path:
        return self.bucket_t / "pending" / f"{rid}.md"

    def body(self) -> str:
        return git(self.home, "log", "-1", "--format=%B").stdout


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ------------------------------------------------------------------ moves


class TestRescopeMove:
    def test_user_to_skill_moves_and_rewrites_scope_in_one_commit(self, env):
        rec = env.seed_user_record()

        result = verbs.rescope(env.home, rec.id, to="skill:s")

        assert result.action == "rescope"
        assert not env.pending_user(rec.id).exists()
        assert env.pending_s(rec.id).is_file()
        assert Record.from_path(env.pending_s(rec.id)).scope == "skill:s"
        subject = f"self-learn: rescope {rec.id} → skills/s"
        assert result.commit_message == subject
        assert verb_subject(env.home) == subject
        files = verb_files(env.home)
        assert f"user/pending/{rec.id}.md" in files
        assert f"skills/s/pending/{rec.id}.md" in files

    def test_skill_to_user_moves_and_rewrites_scope(self, env):
        rec = env.seed_skill_record("s")

        result = verbs.rescope(env.home, rec.id, to="user")

        assert not env.pending_s(rec.id).exists()
        assert env.pending_user(rec.id).is_file()
        assert Record.from_path(env.pending_user(rec.id)).scope == "user"
        subject = f"self-learn: rescope {rec.id} → user"
        assert result.commit_message == subject
        assert verb_subject(env.home) == subject

    def test_body_and_lifecycle_fields_survive_the_rescope(self, env):
        rec = env.seed_user_record()
        before = Record.from_path(env.pending_user(rec.id))

        verbs.rescope(env.home, rec.id, to="skill:s")

        after = Record.from_path(env.pending_s(rec.id))
        assert after.body == before.body
        assert after.status == before.status
        assert after.sightings == before.sightings
        assert after.evidence == before.evidence
        assert after.created_at == before.created_at
        assert after.routing == before.routing
        assert after.resolution_note == before.resolution_note
        # Positive control: scope DID change — a no-op cannot pass this.
        assert before.scope == "user"
        assert after.scope == "skill:s"

    def test_deferred_record_rescopes_and_stays_deferred(self, env):
        rec = env.seed_user_record()
        defer_record(env.home, rec.id, "2027-01-01")
        commit_all(env.home, "defer seed")

        verbs.rescope(env.home, rec.id, to="skill:s")

        moved = Record.from_path(env.pending_s(rec.id))
        assert moved.status == "deferred"
        assert str(moved.deferred_until) == "2027-01-01"
        assert moved.deferred_count == 1

    def test_creates_target_bucket_dirs_when_absent(self, env):
        rec = env.seed_user_record()
        assert not env.bucket_t.exists()

        verbs.rescope(env.home, rec.id, to="skill:t")

        for sub in ("pending", "resolved", "proposals"):
            assert (env.bucket_t / sub).is_dir()

    def test_no_meta_yaml_is_written_for_user_or_skill_targets(self, env):
        rec = env.seed_user_record()
        verbs.rescope(env.home, rec.id, to="skill:s")
        assert not (env.bucket_s / "meta.yaml").exists()

        rec2 = env.seed_skill_record("t", make_behavior(scope="skill:t"))
        verbs.rescope(env.home, rec2.id, to="user")
        assert not (env.bucket_user / "meta.yaml").exists()

    def test_note_rides_the_commit_body_not_resolution_note(self, env):
        rec = env.seed_user_record()
        verbs.rescope(env.home, rec.id, to="skill:s", note="umbrella")
        assert "umbrella" in env.body()
        assert Record.from_path(env.pending_s(rec.id)).resolution_note is None

    def test_bucket_not_frontmatter_decides_the_source_scope(self, env):
        """MAJOR-3's pin (§6.2 step 5 / §4.1). A record hand-written with
        `scope: user` into `skills/s/pending/` disagrees with its own
        bucket. The BUCKET decides: `--to user` reads this as a legal
        `skill:s -> user` move and SUCCEEDS; `--to skill:s` reads it as
        already-at-target and refuses. A record-derived implementation
        gives the opposite answer on both."""
        rec = Record.create(
            type="knowledge",
            scope="user",
            source="teach",
            fact="scope/bucket disagreement.",
            record_id="lrn-d15a9ee1",
        )
        for sub in ("pending", "resolved", "proposals"):
            (env.bucket_s / sub).mkdir(parents=True, exist_ok=True)
        rec.write(env.bucket_s / "pending" / f"{rec.id}.md")
        commit_all(env.home, "disagreement seed")

        # Leg 1 — SUCCEEDS: the bucket (skills/s) makes this skill->user.
        result = verbs.rescope(env.home, rec.id, to="user")
        assert result.action == "rescope"
        dest = env.pending_user(rec.id)
        assert dest.is_file()
        assert Record.from_path(dest).scope == "user"

        # Leg 2 — fresh fixture, same disagreement, --to skill:s refuses
        # "already lives in" (the bucket says it's already there).
        rec2 = Record.create(
            type="knowledge",
            scope="user",
            source="teach",
            fact="scope/bucket disagreement two.",
            record_id="lrn-d15a9ee2",
        )
        rec2.write(env.bucket_s / "pending" / f"{rec2.id}.md")
        commit_all(env.home, "disagreement seed 2")
        with pytest.raises(verbs.VerbError, match="already lives in"):
            verbs.rescope(env.home, rec2.id, to="skill:s")


# --------------------------------------------------------- proposal sibling


class TestRescopeProposalSweep:
    def test_proposal_is_swept_never_left_behind_and_never_carried(self, env):
        rec = env.seed_user_record()
        write_proposal(
            env.home, rec.id, proposal_dict(scope="user", destination="claude-md")
        )
        diff = env.bucket_user / "proposals" / f"{rec.id}.diff"
        diff.write_text("--- a\n+++ b\n", encoding="utf-8")
        commit_all(env.home, "proposal seed")

        # Positive control FIRST.
        assert (env.bucket_user / "proposals" / f"{rec.id}.yaml").is_file()

        verbs.rescope(env.home, rec.id, to="skill:s")

        assert not (env.bucket_user / "proposals" / f"{rec.id}.yaml").exists()
        assert not diff.exists()
        assert not (env.bucket_s / "proposals" / f"{rec.id}.yaml").exists()
        files = verb_files(env.home)
        assert f"user/proposals/{rec.id}.yaml" in files
        assert f"user/proposals/{rec.id}.diff" in files

    def test_merge_cluster_naming_the_record_is_swept_strangers_survive(self, env):
        rec = env.seed_user_record()
        other = env.seed_user_record(make_knowledge(scope="user", fact="Other."))
        pdir = env.bucket_user / "proposals"
        pdir.mkdir(parents=True, exist_ok=True)
        naming = pdir / "merge-aaaa1111.yaml"
        naming.write_text(
            f"cluster_id: merge-aaaa1111\nrecords: [{rec.id}, {other.id}]\n",
            encoding="utf-8",
        )
        unrelated = pdir / "merge-bbbb2222.yaml"
        unrelated.write_text(
            f"cluster_id: merge-bbbb2222\nrecords: [{other.id}, lrn-00009999]\n",
            encoding="utf-8",
        )
        commit_all(env.home, "merge seed")
        assert naming.is_file()
        assert unrelated.is_file()

        result = verbs.rescope(env.home, rec.id, to="skill:s")

        assert not naming.exists()
        assert unrelated.is_file()
        assert f"user/proposals/merge-aaaa1111.yaml" in verb_files(env.home)

        # MAJOR-2 (code gate finding, 2026-08-23): this fixture sweeps a
        # merge cluster and NOTHING else — no lrn-<id>.yaml/.diff for
        # this record exists. The disclosure line must name the merge
        # cluster and must NOT claim a proposal was swept too — a
        # mutation that always names both components (e.g. hardcoding
        # "0 proposal" or "1 proposal" regardless of what actually
        # swept) is caught here, not by T11 alone.
        assert result.post_notes != []
        note = result.post_notes[0]
        assert "merge cluster" in note
        assert "proposal" not in note, note

    def test_rescoped_record_reads_as_unanalyzed_in_the_new_bucket(self, env):
        rec = env.seed_user_record()
        write_proposal(
            env.home, rec.id, proposal_dict(scope="user", destination="claude-md")
        )
        from self_learn.ledger_ops import stamp_proposal

        stamp_proposal(env.home, rec.id)
        commit_all(env.home, "proposal seed")

        (source_bucket,) = [b for b in discover_buckets(env.home) if b.name == "user"]
        (entry_before,) = queue(source_bucket)
        assert entry_before.record.id == rec.id
        # Positive control: fresh proposal reads as ANALYZED before the move.
        assert is_unanalyzed(entry_before) is False

        verbs.rescope(env.home, rec.id, to="skill:s")

        (dest_bucket,) = [b for b in discover_buckets(env.home) if b.name == "s"]
        (entry_after,) = [e for e in queue(dest_bucket) if e.record.id == rec.id]
        assert proposal_info(entry_after)["has_proposal"] is False
        assert is_unanalyzed(entry_after) is True

    def test_sweep_is_disclosed_in_post_notes_and_commit_body(self, env, monkeypatch, capsys):
        # --- positive leg: a proposal present ---
        rec = env.seed_user_record()
        write_proposal(
            env.home, rec.id, proposal_dict(scope="user", destination="claude-md")
        )
        commit_all(env.home, "proposal seed")

        result = verbs.rescope(env.home, rec.id, to="skill:s")

        assert result.post_notes != []
        assert rec.id in result.post_notes[0]
        assert "skills/s" in result.post_notes[0]
        body = git(env.home, "log", "-1", "--format=%B").stdout
        assert f"swept: user/proposals/{rec.id}.yaml" in body
        # MAJOR-2 (code gate finding, 2026-08-23): this leg sweeps a
        # proposal and NOTHING else — no merge-*.yaml exists. The count
        # must be exact (1 proposal) and the line must NOT claim a merge
        # cluster was swept too, the T9-mirroring half of the same
        # non-zero-only rule.
        assert "1 proposal" in result.post_notes[0]
        assert "merge cluster" not in result.post_notes[0]

        # Drive the CLI once too — post_notes reaches stdout.
        rec_cli = env.seed_user_record(make_knowledge(scope="user", fact="cli leg."))
        write_proposal(
            env.home,
            rec_cli.id,
            proposal_dict(scope="user", destination="claude-md"),
        )
        commit_all(env.home, "proposal seed cli")
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rc = cli.main(["rescope", rec_cli.id, "--to", "skill:s"])
        assert rc == 0
        out = capsys.readouterr().out
        assert rec_cli.id in out
        assert "swept" in out

        # --- negative leg: no proposal present ---
        rec2 = env.seed_user_record(make_knowledge(scope="user", fact="none swept."))
        result2 = verbs.rescope(env.home, rec2.id, to="skill:s")
        assert result2.post_notes == []
        body2 = git(env.home, "log", "-1", "--format=%B").stdout
        assert "swept:" not in body2
        assert "swept 0" not in body2


# --------------------------------------------------------------- refusals


class TestRescopeRefusals:
    def test_refuses_resolved_record(self, env):
        """S-54 / GUARD1 (U-verbs): `rescope` now refuses through the ONE
        guard vocabulary, `ledger_ops.require_status` — replacing the
        hand-rolled status check this test used to pin the message of.
        Refuse-on-status intent is unchanged; the wording moved."""
        rec = env.seed_user_record()
        verbs.reject(env.home, rec.id, no_push=True)
        with pytest.raises(verbs.VerbError, match="needs status pending/deferred"):
            verbs.rescope(env.home, rec.id, to="skill:s")

    def test_project_scoped_source_now_succeeds(self, env):
        """S-54 / MOVE1 (U-verbs): `rescope` widens beyond user<->skill —
        a project-scoped source now moves to `user` instead of refusing.
        `test_u_verbs.py::test_move_matrix` covers the full 8-cell
        matrix; this is the direct regression guard on THIS verb's own
        suite against the OLD "rehome's territory" restriction."""
        rec = make_knowledge(scope="project")
        create_record(env.home, rec, project_path=env.host)
        commit_all(env.home, "project record seed")
        verbs.rescope(env.home, rec.id, to="user")
        moved = env.pending_user(rec.id)
        assert moved.is_file()
        assert Record.from_path(moved).scope == "user"

    def test_refuses_project_target(self, env):
        rec = env.seed_user_record()
        with pytest.raises(verbs.VerbError):
            verbs.rescope(env.home, rec.id, to="project")
        assert env.pending_user(rec.id).is_file()

    def test_refuses_unknown_skill_name(self, env):
        rec = env.seed_user_record()
        with pytest.raises(verbs.VerbError):
            verbs.rescope(env.home, rec.id, to="skill:nope")
        assert not (env.home / "skills" / "nope").exists()
        assert env.pending_user(rec.id).is_file()

    def test_refuses_ambiguous_skill_name(self, env):
        rec = env.seed_user_record()
        dup_dir = env.host / "plugins" / "s-plugin-2" / "skills" / "s"
        dup_dir.mkdir(parents=True)
        (dup_dir / "SKILL.md").write_text("dup\n", encoding="utf-8")
        commit_all(env.host, "duplicate skill dir")
        first_dir = env.host / "plugins" / "s-plugin" / "skills" / "s"
        with pytest.raises(verbs.VerbError) as exc:
            verbs.rescope(env.home, rec.id, to="skill:s")
        assert str(first_dir) in str(exc.value)
        assert str(dup_dir) in str(exc.value)

    def test_refuses_when_no_skills_root_is_registered(self, env):
        rec = env.seed_user_record()
        (env.home / "hosts.yaml").write_text(
            f"skills_root: null\nprojects:\n  - path: {env.host}\n",
            encoding="utf-8",
        )
        commit_all(env.home, "unregister skills root")
        with pytest.raises(verbs.VerbError, match="host add .* --skills-root"):
            verbs.rescope(env.home, rec.id, to="skill:s")

    def test_refuses_bare_skill_without_name(self, env):
        rec = env.seed_user_record()
        with pytest.raises(verbs.VerbError):
            verbs.rescope(env.home, rec.id, to="skill")
        with pytest.raises(verbs.VerbError):
            verbs.rescope(env.home, rec.id, to="skill:")

    def test_refuses_same_scope(self, env):
        rec = env.seed_user_record()
        with pytest.raises(verbs.VerbError, match="already lives in"):
            verbs.rescope(env.home, rec.id, to="user")

    def test_skill_to_skill_now_succeeds(self, env):
        """S-54 / MOVE1 leg / §3.2c (U-verbs, ruling R2): skill→skill is
        ruled IN — FW-114's blocker (a carried proposal's judgment
        drift) is moot because u-rescope §5 decided SWEEP, so nothing is
        ever carried across a bucket boundary. Regression guard against
        the OLD "dated future work" refusal resurfacing."""
        rec = env.seed_skill_record("s")
        verbs.rescope(env.home, rec.id, to="skill:t")
        moved = env.pending_t(rec.id)
        assert moved.is_file()
        assert Record.from_path(moved).scope == "skill:t"

    def test_refuses_destination_collision_before_creating_anything(self, env):
        # Direction chosen deliberately: `find_record_path` searches
        # skill buckets before `user/` (`discover_buckets`'s own order),
        # so a `user`-source record with a same-id imposter placed in a
        # SKILL target bucket would have the imposter found FIRST — an
        # artifact of the id-collision fixture, not of `rescope` (record
        # ids are random and never collide in production). Using a
        # skill-source / user-target collision keeps the fixture honest:
        # the real source record is found first either way.
        rec = env.seed_skill_record("s")
        clash = env.pending_user(rec.id)
        clash.parent.mkdir(parents=True, exist_ok=True)
        clash.write_text("imposter\n", encoding="utf-8")
        with pytest.raises(verbs.VerbError, match="duplicated id is corruption to surface"):
            verbs.rescope(env.home, rec.id, to="user")
        assert env.pending_s(rec.id).is_file()

        rec2 = env.seed_skill_record("s", make_behavior(scope="skill:s", trigger="Second clash trigger."))
        clash2 = env.bucket_user / "resolved" / f"{rec2.id}.md"
        clash2.parent.mkdir(parents=True, exist_ok=True)
        clash2.write_text("resolved imposter\n", encoding="utf-8")
        with pytest.raises(verbs.VerbError, match="duplicated id is corruption to surface"):
            verbs.rescope(env.home, rec2.id, to="user")
        assert env.pending_s(rec2.id).is_file()

    def test_secret_in_record_or_note_refuses_before_any_write(self, env):
        rec = env.seed_user_record(
            make_knowledge(scope="user", fact="password = hunter2secret99")
        )
        with pytest.raises(verbs.SecretRefusal):
            verbs.rescope(env.home, rec.id, to="skill:s")
        assert env.pending_user(rec.id).is_file()
        assert not env.bucket_s.exists() or not env.pending_s(rec.id).exists()

        rec2 = env.seed_user_record(make_knowledge(scope="user", fact="clean fact."))
        with pytest.raises(verbs.SecretRefusal):
            verbs.rescope(
                env.home, rec2.id, to="skill:s", note="key is ghp_" + "a" * 36
            )
        assert env.pending_user(rec2.id).is_file()

    def test_unknown_id_exits_64(self, env, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        assert cli.main(["rescope", "lrn-00000000", "--to", "skill:s"]) == 64

    def test_missing_home_exits_5(self, env, tmp_path, monkeypatch, capsys):
        home = tmp_path / "not-a-repo"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli.main(["rescope", "lrn-00000000", "--to", "skill:s"])
        out = capsys.readouterr()
        assert rc == 5
        assert "ledger home" in out.err
        assert "not found under" not in out.err


# ------------------------------------------------------------ CLI surface


class TestRescopeCli:
    def test_cli_rescope_happy_path(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rec = env.seed_user_record()
        rc = cli.main(["rescope", rec.id, "--to", "skill:s"])
        assert rc == 0
        assert env.pending_s(rec.id).is_file()
        out = capsys.readouterr().out
        assert "skills/s" in out

    def test_cli_rescope_requires_to(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rec = env.seed_user_record()
        rc = cli.main(["rescope", rec.id])
        assert rc == 2
        assert "--to" in capsys.readouterr().err

    def test_cli_rescope_refusal_exits_1(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rec = env.seed_user_record()
        rc = cli.main(["rescope", rec.id, "--to", "user"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "self-learn rescope:" in err

    # T26 (`test_rescope_is_not_in_the_pane_proposable_verb_list`) is NOT
    # here — per spec §10.4 it lives in the UI test suite
    # (`plugins/self-learn/ui/tests/test_proposals.py`), because that is
    # where `self_learn_ui.proposals.PROPOSABLE_VERBS` is defined. Run it
    # with `uv run --project plugins/self-learn/ui pytest`.


# --------------------------------------------------- mv-first crash-window ordering


class TestRescopeMvFirstOrdering:
    """MAJOR-1 (code gate finding, 2026-08-23): §6.4's mv-first ordering
    shipped with no test that would go red under a write-then-mv swap —
    the full suite stayed green while the counterfactual crash probe
    silently committed a scope/bucket mismatch via `reconcile`. Two
    tests close the gap: the first exercises the crash window itself
    (mv succeeds, the rewrite is what raises); the second is a call-order
    witness independent of which step is made to raise, so a swap reds
    it even when nothing crashes at all."""

    def test_kill_between_mv_and_write_leaves_a_blocked_staged_rename(
        self, env, monkeypatch
    ):
        """The crash window §6.4 names: `git mv` lands, then
        `record.write` raises before the rewrite reaches disk. Asserts
        the S1 state exactly: porcelain `R ` (a staged rename, no
        working-tree modification — the write never landed), the
        destination file still carrying the STALE source scope, and
        `reconcile()` refusing to auto-commit it — reporting it
        `blocked`, never `committed`. A build that swapped to
        write-then-mv would either crash before any mv (leaving no
        staged rename to assert on) or, worse, leave a plain modified
        file reconcile WOULD silently commit — this test reds either
        way."""
        rec = env.seed_user_record()

        def boom(self, path):
            raise RuntimeError("simulated kill between git mv and record.write")

        monkeypatch.setattr(Record, "write", boom)
        with pytest.raises(RuntimeError):
            # U-verbs §3.2a (ruling R1): `rescope_record` is replaced by
            # `move_record`, the ONE file-op behind both `rehome` and
            # `rescope` — same mv-then-write ordering discipline this
            # test pins, called through the new keyword grammar.
            ledger_ops.move_record(
                env.home,
                rec.id,
                target_scope="skill:s",
                target_bucket=env.bucket_s,
            )

        status = git(env.home, "status", "--porcelain").stdout
        assert status.strip().startswith("R "), status
        dest = env.pending_s(rec.id)
        assert dest.is_file()
        # The rewrite never landed — the destination still reads the
        # SOURCE scope (mv is a pure file move; only `record.write`
        # changes bytes, and it never ran to completion).
        assert Record.from_path(dest).scope == "user"

        result = reconcile_mod.reconcile(env.home)
        assert result.committed == []
        assert any(entry.startswith("R") for entry in result.blocked), result.blocked

    def test_git_mv_runs_before_record_write_not_after(self, env, monkeypatch):
        """An ordering witness independent of the crash-simulation
        mechanism above: instruments both the `git mv` call and
        `Record.write` to record when each actually ran, and asserts
        the observed order is mv-then-write. A build that swapped the
        order (write-then-mv) reds this directly, regardless of whether
        anything raises — this is the leg that catches a swap mutation
        the first test's assertions alone might not distinguish
        cleanly."""
        rec = env.seed_user_record()
        order: list[str] = []

        # M-G (sprint 1 lane L1 ledger-git): `_git_ok` is deleted --
        # `move_record`'s `git mv` now runs through `ledger_ops._git_mv`
        # (bounded via `primitives.procs.run_bounded`), its one and only
        # remaining private git seam. Retargeted the spy there; the
        # property this test asserts (mv strictly before the record
        # rewrite) is unchanged.
        orig_git_mv = ledger_ops._git_mv

        def spy_git_mv(home, src, dest):
            order.append("mv")
            return orig_git_mv(home, src, dest)

        monkeypatch.setattr(ledger_ops, "_git_mv", spy_git_mv)

        orig_write = Record.write

        def spy_write(self, path):
            order.append("write")
            return orig_write(self, path)

        monkeypatch.setattr(Record, "write", spy_write)

        # U-verbs §3.2a (ruling R1): the file-op is `move_record` now —
        # same ordering discipline, new keyword call shape.
        ledger_ops.move_record(
            env.home, rec.id, target_scope="skill:s", target_bucket=env.bucket_s
        )

        assert order == ["mv", "write"], (
            "move_record must git-mv BEFORE rewriting the record at "
            "the destination (§6.4) — a write-then-mv order turns a "
            f"kill into a silently-committable corruption; observed: {order}"
        )


# ------------------------------------------------------------ ledger discipline


class TestRescopeLedgerDiscipline:
    def test_exactly_one_commit_is_created(self, env):
        rec = env.seed_user_record()
        before = int(git(env.home, "rev-list", "--count", "HEAD").stdout.strip())
        verbs.rescope(env.home, rec.id, to="skill:s")
        after = int(git(env.home, "rev-list", "--count", "HEAD").stdout.strip())
        assert after - before == 1

    def test_half_written_exits_7(self, env, tmp_path, monkeypatch, capsys):
        rec = env.seed_user_record()
        flag = failing_git_shim(tmp_path, monkeypatch)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        flag.touch()
        try:
            code = cli.main(["rescope", rec.id, "--to", "skill:s"])
        finally:
            flag.unlink()

        assert code == 7
        assert env.pending_s(rec.id).is_file()
        assert f"skills/s/pending/{rec.id}.md" not in head_files(env.home)

    def test_no_push_skips_the_push(self, env):
        rec = env.seed_user_record()
        result = verbs.rescope(env.home, rec.id, to="skill:s", no_push=True)
        assert result.push is None

        # Positive control: without --no-push, a remote-less ledger
        # returns push.skipped True — NOT None.
        rec2 = env.seed_user_record(make_knowledge(scope="user", fact="second."))
        result2 = verbs.rescope(env.home, rec2.id, to="skill:s")
        assert result2.push is not None
        assert result2.push.skipped is True
        assert result2.push.ok is True

    def test_no_telemetry_event_is_spooled(self, env):
        rec = env.seed_user_record()
        before = spool_lines()

        verbs.rescope(env.home, rec.id, to="skill:s", no_push=True)

        after = spool_lines()
        assert after == before

        # Positive control: `route` DOES spool a line there.
        rec2 = env.seed_skill_record("t")
        verbs.route(env.home, rec2.id, dest="skill-md", no_push=True)
        after_route = spool_lines()
        assert len(after_route) > len(after)
