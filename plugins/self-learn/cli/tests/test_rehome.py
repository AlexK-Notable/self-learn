"""U15: the `rehome` verb (02 §2 verb pin; 09 §11 Y-18) — project→project
record re-home on a constructed two-project ledger.

Covers: the move itself (one ledger commit, pinned subject, --note →
commit body only, bytes untouched), --to by path AND by slug, a deferred
record moving and staying deferred, target bucket dirs + meta.yaml
created from hosts.yaml when absent, the proposal-sibling sweep
(lrn-<id>.{yaml,diff}) plus a merge-cluster member's rehome sweeping the
naming merge-*.yaml, the destination-collision refusal (checked before
any dir/meta creation), every refusal string verbatim, the P2-7 secret
scan (record file AND note), re-run refusing on target==current, and the
CLI arg surface (`self-learn rehome <id> --to …`).

Sandbox git repos under tmpdirs; the sentinel is XDG-redirected.
"""

import pytest

from self_learn import cli, verbs
from self_learn.hosts import host_add, slug_for
from self_learn.ledger_ops import (
    LedgerOpsError,
    bucket_project_path,
    create_record,
    defer_record,
    write_proposal,
)
from self_learn.records import Record
from support import (
    commit_all,
    git,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
    verb_files,
    verb_subject,
)


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel goes to a per-test XDG cache, never the real ~/.cache."""
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


class Env:
    """A TWO-project ledger: host A (make_env's combined skills-root +
    project host) and host B — a second registered project repo with a
    distinctive basename, NO bucket yet (the bucket-creation leg)."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host_a = sandbox.host
        self.host_b = tmp_path / "repos" / "keyboards"
        init_repo(self.host_b)
        (self.host_b / "README.md").write_text("b\n", encoding="utf-8")
        commit_all(self.host_b, "host-b seed")
        host_add(self.home, self.host_b, "project")
        self.slug_a = slug_for(self.host_a)
        self.slug_b = slug_for(self.host_b)
        self.bucket_a = self.home / "projects" / self.slug_a
        self.bucket_b = self.home / "projects" / self.slug_b

    def seed_project_record(self, record=None) -> Record:
        record = record if record is not None else make_knowledge(scope="project")
        create_record(self.home, record, project_path=self.host_a)
        commit_all(self.home, "record seed")
        return record

    def pending_a(self, rid):
        return self.bucket_a / "pending" / f"{rid}.md"

    def pending_b(self, rid):
        return self.bucket_b / "pending" / f"{rid}.md"

    def body(self):
        return git(self.home, "log", "-1", "--format=%B").stdout


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ------------------------------------------------------------------ moves


class TestRehomeMove:
    def test_moves_record_in_one_commit_with_pinned_subject(self, env):
        rec = env.seed_project_record()
        before = env.pending_a(rec.id).read_text(encoding="utf-8")

        result = verbs.rehome(env.home, rec.id, to=str(env.host_b), note="umbrella")

        assert result.action == "rehome"
        assert not env.pending_a(rec.id).exists()
        assert env.pending_b(rec.id).is_file()
        # 02 §2: the record file is byte-untouched — a filing move, never
        # a substance edit.
        assert env.pending_b(rec.id).read_text(encoding="utf-8") == before
        subject = f"self-learn: rehome {rec.id} → projects/{env.slug_b}"
        assert result.commit_message == subject
        assert verb_subject(env.home) == subject
        # --note rides the commit body ONLY (rehome is not a resolution;
        # the byte-identity assertion above proves resolution_note — and
        # everything else in the file — stayed untouched).
        assert "umbrella" in env.body()
        # ONE commit carries the whole move: rename halves + meta.yaml.
        files = verb_files(env.home)
        assert f"projects/{env.slug_a}/pending/{rec.id}.md" in files
        assert f"projects/{env.slug_b}/pending/{rec.id}.md" in files
        assert f"projects/{env.slug_b}/meta.yaml" in files

    def test_to_accepts_the_bucket_slug(self, env):
        rec = env.seed_project_record()
        verbs.rehome(env.home, rec.id, to=env.slug_b)
        assert env.pending_b(rec.id).is_file()

    def test_creates_target_dirs_and_meta_from_hosts_yaml(self, env):
        rec = env.seed_project_record()
        assert not env.bucket_b.exists()
        verbs.rehome(env.home, rec.id, to=str(env.host_b))
        for sub in ("pending", "resolved", "proposals"):
            assert (env.bucket_b / sub).is_dir()
        # meta.yaml stamped from the registered path (13 §3); hosts.yaml
        # stays the only registration authority — nothing new registered.
        assert bucket_project_path(env.bucket_b) == env.host_b.resolve()

    def test_deferred_record_moves_and_stays_deferred(self, env):
        rec = env.seed_project_record()
        defer_record(env.home, rec.id, "2027-01-01")
        commit_all(env.home, "defer seed")
        verbs.rehome(env.home, rec.id, to=str(env.host_b))
        moved = Record.from_path(env.pending_b(rec.id))
        assert moved.status == "deferred"
        assert str(moved.deferred_until) == "2027-01-01"
        assert moved.deferred_count == 1

    def test_sweeps_proposal_siblings_never_moves_them(self, env):
        rec = env.seed_project_record()
        write_proposal(env.home, rec.id, proposal_dict(destination="claude-md"))
        diff = env.bucket_a / "proposals" / f"{rec.id}.diff"
        diff.write_text("--- a\n+++ b\n", encoding="utf-8")
        commit_all(env.home, "proposal seed")

        verbs.rehome(env.home, rec.id, to=str(env.host_b))

        assert not (env.bucket_a / "proposals" / f"{rec.id}.yaml").exists()
        assert not diff.exists()
        assert not (env.bucket_b / "proposals" / f"{rec.id}.yaml").exists()
        files = verb_files(env.home)
        assert f"projects/{env.slug_a}/proposals/{rec.id}.yaml" in files
        assert f"projects/{env.slug_a}/proposals/{rec.id}.diff" in files

    def test_merge_member_rehome_sweeps_the_naming_merge_yaml(self, env):
        rec = env.seed_project_record()
        other = env.seed_project_record(make_knowledge(scope="project", fact="Other."))
        pdir = env.bucket_a / "proposals"
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

        verbs.rehome(env.home, rec.id, to=str(env.host_b))

        # F3: a partial cluster is invalid — the SAME commit sweeps the
        # source-bucket merge file naming the record; strangers survive.
        assert not naming.exists()
        assert unrelated.is_file()
        assert f"projects/{env.slug_a}/proposals/merge-aaaa1111.yaml" in verb_files(env.home)


# --------------------------------------------------------------- refusals


class TestRehomeRefusals:
    def test_unknown_id_refuses(self, env):
        with pytest.raises(LedgerOpsError, match="not found"):
            verbs.rehome(env.home, "lrn-deadbeef", to=str(env.host_b))

    def test_resolved_record_refuses_on_status_never_existence(self, env):
        rec = env.seed_project_record()
        verbs.reject(env.home, rec.id, no_push=True)
        with pytest.raises(verbs.VerbError) as exc:
            verbs.rehome(env.home, rec.id, to=str(env.host_b))
        assert str(exc.value) == (
            f"record {rec.id} is not pending (status 'rejected') — a "
            "resolved lesson does not move; supersede is the correction "
            "machinery (02 §2)"
        )

    def test_unregistered_target_names_host_add_as_repair(self, env):
        rec = env.seed_project_record()
        stranger = env.home.parent / "stranger-repo"
        with pytest.raises(verbs.VerbError) as exc:
            verbs.rehome(env.home, rec.id, to=str(stranger))
        assert str(exc.value) == (
            f"target {str(stranger)!r} is not a registered project — "
            "self-learn host add <path> is the human's repair"
        )
        assert env.pending_a(rec.id).is_file()

    def test_target_equals_current_bucket_refuses(self, env):
        rec = env.seed_project_record()
        with pytest.raises(verbs.VerbError) as exc:
            verbs.rehome(env.home, rec.id, to=str(env.host_a))
        assert str(exc.value) == (
            f"record {rec.id} already lives in projects/{env.slug_a} — "
            "nothing to move"
        )

    def test_rerun_refuses_on_target_equals_current(self, env):
        rec = env.seed_project_record()
        verbs.rehome(env.home, rec.id, to=str(env.host_b))
        with pytest.raises(verbs.VerbError, match="nothing to move"):
            verbs.rehome(env.home, rec.id, to=str(env.host_b))

    def test_non_project_source_refuses(self, env):
        rec = make_behavior(scope="skill:s")
        create_record(env.home, rec)
        commit_all(env.home, "skill record seed")
        with pytest.raises(verbs.VerbError) as exc:
            verbs.rehome(env.home, rec.id, to=str(env.host_b))
        assert str(exc.value) == (
            f"record {rec.id} lives in a non-project bucket (s) — rehome "
            "is project→project only (M1); self-learn rescope is the "
            "repair for a user<->skill:<name> move — project↔user/skill "
            "moves remain dated future work, not silent extensions"
        )

    def test_destination_collision_refuses_before_any_creation(self, env):
        rec = env.seed_project_record()
        # a same-id file already in the target bucket's pending/ —
        # corruption to surface, never to merge into (F4).
        clash = env.pending_b(rec.id)
        clash.parent.mkdir(parents=True)
        clash.write_text("imposter\n", encoding="utf-8")
        with pytest.raises(verbs.VerbError, match="already exists in"):
            verbs.rehome(env.home, rec.id, to=str(env.host_b))
        # checked BEFORE any dir/meta.yaml creation
        assert not (env.bucket_b / "meta.yaml").exists()
        assert env.pending_a(rec.id).is_file()
        assert clash.read_text(encoding="utf-8") == "imposter\n"

    def test_destination_collision_sees_resolved_too(self, env):
        rec = env.seed_project_record()
        clash = env.bucket_b / "resolved" / f"{rec.id}.md"
        clash.parent.mkdir(parents=True)
        clash.write_text("resolved imposter\n", encoding="utf-8")
        with pytest.raises(verbs.VerbError, match="already exists in"):
            verbs.rehome(env.home, rec.id, to=str(env.host_b))
        assert not (env.bucket_b / "meta.yaml").exists()
        assert env.pending_a(rec.id).is_file()

    def test_secret_scan_refuses_record_file(self, env):
        rec = env.seed_project_record(
            make_knowledge(scope="project", fact="password = hunter2secret99")
        )
        with pytest.raises(verbs.SecretRefusal):
            verbs.rehome(env.home, rec.id, to=str(env.host_b))
        assert env.pending_a(rec.id).is_file()

    def test_secret_scan_refuses_note(self, env):
        rec = env.seed_project_record()
        with pytest.raises(verbs.SecretRefusal):
            verbs.rehome(
                env.home, rec.id, to=str(env.host_b), note="key is ghp_" + "a" * 36
            )
        assert env.pending_a(rec.id).is_file()


# ------------------------------------------------------------ CLI surface


class TestRehomeCli:
    def test_cli_rehome_happy_path(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rec = env.seed_project_record()
        rc = cli.main(["rehome", rec.id, "--to", str(env.host_b), "--note", "n"])
        assert rc == 0
        assert env.pending_b(rec.id).is_file()
        out = capsys.readouterr().out
        assert f"rehome {rec.id} → projects/{env.slug_b}" in out

    def test_cli_rehome_requires_to(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rec = env.seed_project_record()
        # argparse's SystemExit is mapped to a return code by main()
        rc = cli.main(["rehome", rec.id])
        assert rc != 0
        assert "--to" in capsys.readouterr().err

    def test_cli_rehome_refusal_exits_nonzero(self, env, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rec = env.seed_project_record()
        rc = cli.main(["rehome", rec.id, "--to", str(env.host_a)])
        assert rc == 1
        assert "nothing to move" in capsys.readouterr().err
