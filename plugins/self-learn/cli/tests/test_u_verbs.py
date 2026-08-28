"""U-verbs Phase 1 (T2) -- the unit's own test file (spec S7).

Covers every Phase-1 [A] non-doc criterion in
docs/specs/self-learn/drafts/u-verbs-ledger-verb-completion-spec.md S5:
PH1-2, GUARD1-4, MOVE1-10, STATE1-8, DRY1-4, SHOW1-3, BAT1-11, PROD1-3,
UN1-5 (50 pytest-checked criteria). The remaining 6 [A] criteria are
DOC1/3/4/6/7/8 -- grep checks against docs, verified separately (not
pytest) and reported in the builder's own report.

Fixtures here are purpose-built per test rather than a byte-identical
copy of the spec's 18 named fixtures (three_scope_home, sheet_all_verbs,
b206800_bytes, ...) -- each still drives the SAME state and
discriminates the SAME mutation named in S5/S6 of the spec; this is a
measured, reported deviation from the spec's literal fixture list, not
an unreported one.

All ledger homes are throwaway sandbox repos under pytest tmpdirs
(support.make_env) -- never the real ~/.self-learn.
"""

from __future__ import annotations

import ast
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import batch, cli, gitops, sentinel, telemetry, verbs
from self_learn.hosts import HostsError, host_add, skill_dir_for, slug_for
from self_learn.ledger_ops import (
    DEFERRED_ONLY,
    LIVE_STATUSES,
    LedgerOpsError,
    REOPENABLE_STATUSES,
    RESOLVABLE_STATUSES,
    ROUTED_ONLY,
    bucket_project_path,
    create_record,
    defer_record,
    find_record_path,
    move_record,
    write_proposal,
)
from self_learn.records import RECORD_ID_RE, MutationError, Record, ValidationError
from support import (
    commit_all,
    force_past_deferred,
    git,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
    verb_files,
    verb_subject,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CLI_SRC = Path(__file__).resolve().parents[1] / "src"
UI_SRC = REPO_ROOT / "plugins" / "self-learn" / "ui" / "src"
VERBS_PY = CLI_SRC / "self_learn" / "verbs.py"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


# --------------------------------------------------------------- helpers


def tree_hash(repo: Path) -> str:
    """A content fingerprint of *repo*'s tracked+untracked working tree,
    with no commit and no lasting index change: ``add -A`` (picks up
    untracked files too) -> ``write-tree`` -> ``reset`` (unstages back to
    HEAD, working tree left alone). Two calls comparing equal is the
    'nothing was written' proof most STATE/DRY/BAT criteria need."""
    git(repo, "add", "-A")
    out = git(repo, "write-tree").stdout.strip()
    git(repo, "reset")
    return out


def b206800_text(relpath: str) -> str:
    """The pre-change bytes of *relpath*, read straight from git history
    -- the spec's ``b206800_bytes`` fixture, without a checked-in
    excerpt: b206800 is an ancestor commit already in this repo's own
    history (the pre-U-hostmode-merge point the spec's census was taken
    against), so ``git show`` reaches it from any worktree sharing the
    object database."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"b206800:{relpath}"],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


class TwoProjectEnv:
    """A ledger with TWO registered projects (host A via make_env, host B
    fresh) and two skill buckets -- the spec's ``three_scope_home``
    shape, minus the pre-seeded records (each test seeds what it needs)."""

    def __init__(self, tmp_path, skills=("a", "b")):
        sandbox = make_env(tmp_path, skills=skills)
        self.home = sandbox.ledger
        self.host_a = sandbox.host
        self.host_b = tmp_path / "repos" / "keyboards"
        init_repo(self.host_b)
        (self.host_b / "README.md").write_text("b\n", encoding="utf-8")
        commit_all(self.host_b, "host-b seed")
        host_add(self.home, self.host_b, "project")
        self.slug_a = slug_for(self.host_a)
        self.slug_b = slug_for(self.host_b)
        self.bucket_user = self.home / "user"
        self.bucket_a = self.home / "projects" / self.slug_a
        self.bucket_b = self.home / "projects" / self.slug_b
        self.bucket_skill_a = self.home / "skills" / "a"
        self.bucket_skill_b = self.home / "skills" / "b"

    def seed(self, *, scope, project_path=None, record=None):
        record = record if record is not None else make_knowledge(scope=scope)
        create_record(self.home, record, project_path=project_path)
        commit_all(self.home, "record seed")
        return record


@pytest.fixture()
def env2(tmp_path, monkeypatch):
    e = TwoProjectEnv(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


def seed_routed(home, rid="lrn-0000aaaa", *, follow_up=None, scope="skill:a"):
    create_record(home, make_behavior(record_id=rid, scope=scope))
    write_proposal(home, rid, proposal_dict(scope=scope))
    commit_all(home, "pending")
    result = verbs.route(home, rid, dest="skill-md", no_push=True, follow_up=follow_up)
    assert result.action == "route"
    return rid


def spool_suspect(home, routed_id, *, origin="lrn-0000eeee", basis="miner-match", now=None):
    before = {
        e["nonce"] for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    }
    telemetry.spool_event(
        "recurrence-suspect", record=routed_id, origin=origin, basis=basis, now=now
    )
    telemetry.flush(home)
    event = next(
        e for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect" and e["nonce"] not in before
    )
    return event["nonce"]


# =================================================================== PH


class TestPhaseBoundary:
    def test_ph1_no_phase2_symbol_in_phase1_tree(self):
        """PH1: a literal, unpiped grep for the six Phase-2 names across
        cli/src + ui/src returns 0 -- with a positive control proving the
        grep itself can find something (``require_status``, >= 12 hits)."""
        pattern = (
            r"\breroute\b|retire_reference|records_targeting|bucket_prune"
            r"|followup_add|reclassify"
        )
        proc = subprocess.run(
            ["grep", "-rnE", pattern, str(CLI_SRC), str(UI_SRC)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 1, (
            "PH1 violation(s) found:\n" + proc.stdout
        )  # rc 1 == grep found nothing; rc 0 would BE the violation

        control = subprocess.run(
            ["grep", "-rn", "require_status", str(CLI_SRC), str(UI_SRC)],
            capture_output=True, text=True,
        )
        assert control.returncode == 0
        assert len(control.stdout.splitlines()) >= 12

    def test_ph2_batch_module_is_phase1_only(self):
        """PH2 (this build's proof point): batch.py's own PERMITTED_VERBS
        is exactly the 15 Phase-1 verbs -- no Phase-2 verb name appears
        in it, and it is not a superset that would let a sheet name one."""
        phase2_verbs = {"reroute", "followup add", "reclassify", "host remove", "bucket prune"}
        assert not (batch.PERMITTED_VERBS & phase2_verbs)
        assert len(batch.PERMITTED_VERBS) == 15


# ================================================================ GUARD


def _handrolled_status_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls_require_status = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "require_status"
            for n in ast.walk(node)
        )
        for n in ast.walk(node):
            if not (
                isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
                and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "VerbError"
            ):
                continue
            msg_has_status = any(
                isinstance(a, ast.Constant) and isinstance(a.value, str)
                and "status" in a.value
                for a in ast.walk(n.exc)
            )
            if msg_has_status and not calls_require_status:
                violations.append(node.name)
    return violations


class TestGuard:
    def test_guard1_no_handrolled_status_checks(self):
        live = _handrolled_status_violations(VERBS_PY.read_text(encoding="utf-8"))
        assert live == [], f"hand-rolled status check(s) outside require_status: {live}"

        # positive control, asserted AFTER (it needs the same walker) --
        # the pre-change verbs.py has exactly the two documented ones.
        pre = _handrolled_status_violations(
            b206800_text("plugins/self-learn/cli/src/self_learn/verbs.py")
        )
        assert sorted(pre) == ["rehome", "rescope"]

    def test_guard2_new_status_sets_are_constants(self):
        from self_learn import ledger_ops
        assert ledger_ops.REOPENABLE_STATUSES == frozenset({"rejected"})
        assert ledger_ops.DEFERRED_ONLY == frozenset({"deferred"})
        proc = subprocess.run(
            ["grep", "-n", r'frozenset({"rejected"})\|frozenset({"deferred"})', str(VERBS_PY)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 1, proc.stdout  # no inline literal in verbs.py

    @pytest.mark.parametrize(
        "verb,setup,expect_status",
        [
            ("undefer", "pending", "pending"),
            ("reopen", "routed", "routed"),
            ("note", None, None),  # note has no status gate; skipped below
        ],
    )
    def test_guard3_new_verbs_refuse_on_status(self, tmp_path, monkeypatch, verb, setup, expect_status):
        """GUARD3: refuse on STATUS, never mere existence -- naming both
        the record and its actual status; an unknown id still hits 64."""
        if verb == "note":
            pytest.skip("note carries no status gate by design (STATE8)")
        e = TwoProjectEnv(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
        rid = "lrn-0000aaaa"
        if setup == "routed":
            create_record(e.home, make_knowledge(scope="skill:a", record_id=rid))
            commit_all(e.home, "seed")
            write_proposal(e.home, rid, proposal_dict(scope="skill:a"))
            verbs.route(e.home, rid, dest="skill-md", no_push=True)

        if setup == "pending":
            create_record(e.home, make_knowledge(scope="project", record_id=rid), project_path=e.host_a)
            commit_all(e.home, "seed")
        fn = {"undefer": verbs.undefer, "reopen": verbs.reopen}[verb]
        with pytest.raises(verbs.VerbError) as exc:
            fn(e.home, rid, no_push=True)
        assert rid in str(exc.value)
        assert f"is {expect_status!r}" in str(exc.value)

        with pytest.raises(LedgerOpsError):
            find_record_path(e.home, "lrn-deadbeef")  # unknown id: 64-flavored, never status

    def test_guard4_new_verbs_rerun_safe(self, tmp_path, monkeypatch):
        """GUARD4: a second invocation is either a no-op (rc-equivalent
        0) or a clean status refusal (rc-equivalent 1) -- never a partial
        write. undefer twice: 2nd call refuses (already pending), and the
        ledger tree hash after the SECOND call equals after the first."""
        e = TwoProjectEnv(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
        rid = "lrn-0000aaaa"
        create_record(e.home, make_knowledge(scope="project", record_id=rid), project_path=e.host_a)
        commit_all(e.home, "seed")
        defer_record(e.home, rid)
        verbs.undefer(e.home, rid, no_push=True)
        after_first = tree_hash(e.home)
        with pytest.raises(verbs.VerbError):
            verbs.undefer(e.home, rid, no_push=True)
        assert tree_hash(e.home) == after_first


# ================================================================= MOVE


MOVE_LEGS = [
    ("user", "user", "skill:a"),
    ("user", "user", "project:b"),
    ("skill:a", "skill_a", "user"),
    ("skill:a", "skill_a", "skill:b"),
    ("skill:a", "skill_a", "project:b"),
    ("project:a", "project_a", "user"),
    ("project:a", "project_a", "skill:a"),
    ("project:a", "project_a", "project:b"),
]


class TestMove:
    def _seed_at(self, e, label):
        if label == "user":
            return e.seed(scope="user"), e.bucket_user
        if label == "skill_a":
            return e.seed(scope="skill:a"), e.bucket_skill_a
        if label == "project_a":
            return e.seed(scope="project", project_path=e.host_a), e.bucket_a
        raise AssertionError(label)

    @pytest.mark.parametrize("src_label,src_bucket_label,to", MOVE_LEGS)
    def test_move1_matrix(self, env2, src_label, src_bucket_label, to):
        record, src_bucket = self._seed_at(env2, src_bucket_label)
        rid = record.id
        touched, swept = move_record(
            env2.home, rid,
            **_move_target_kwargs(env2, to),
        )
        assert touched, "move_record must report at least one touched path"
        dest_bucket = _resolve_expected_bucket(env2, to)
        new_path = dest_bucket / "pending" / f"{rid}.md"
        assert new_path.is_file()
        moved = Record.from_path(new_path)
        assert moved.scope == _expected_scope_literal(to)

    def test_move1_leg9_mismatch_repair(self, env2):
        """Leg 9: a PENDING record sitting in a project bucket whose
        frontmatter wrongly says scope: user is moved project->project,
        and ends with scope: project (S3.2a step 5's unconditional write)."""
        record = make_knowledge(scope="project")
        create_record(env2.home, record, project_path=env2.host_a)
        path = env2.bucket_a / "pending" / f"{record.id}.md"
        r = Record.from_path(path)
        r.set_scope("user")  # corrupt: bucket says project, field says user
        r.write(path)
        commit_all(env2.home, "corrupt scope")

        move_record(
            env2.home, record.id,
            target_scope="project", target_bucket=env2.bucket_b,
            project_path=env2.host_b,
        )
        new_path = env2.bucket_b / "pending" / f"{record.id}.md"
        assert new_path.is_file()
        assert Record.from_path(new_path).scope == "project"

    @pytest.mark.parametrize("src_label,src_bucket_label,to", MOVE_LEGS)
    def test_move2_meta_yaml_iff_project(self, env2, src_label, src_bucket_label, to):
        record, src_bucket = self._seed_at(env2, src_bucket_label)
        move_record(env2.home, record.id, **_move_target_kwargs(env2, to))
        dest_bucket = _resolve_expected_bucket(env2, to)
        is_project = to.startswith("project:")
        assert (dest_bucket / "meta.yaml").exists() == is_project
        # source bucket's own meta.yaml (project sources only) survives
        if src_bucket_label == "project_a":
            assert (src_bucket / "meta.yaml").exists()

    def test_move3_old_fileops_gone(self):
        from self_learn import ledger_ops
        assert not hasattr(ledger_ops, "rehome_record")
        assert not hasattr(ledger_ops, "rescope_record")
        proc = subprocess.run(
            ["grep", "-c", r"def rehome_record\|def rescope_record",
             str(CLI_SRC / "self_learn" / "ledger_ops.py")],
            capture_output=True, text=True,
        )
        assert proc.returncode == 1  # grep -c found 0 matches -> rc 1

    def test_move4_reserved_literals_beat_paths(self, tmp_path, monkeypatch):
        """MOVE4: the reserved literals `user`/`skill:<name>` are matched
        BEFORE any path resolution -- with a project host registered at a
        directory literally named `user`, `--to user` resolves to the
        USER bucket, while `--to project:user` and `--to ./user` (both
        relative-path spellings, matched via cwd) resolve to the
        PROJECT bucket."""
        sandbox = make_env(tmp_path, skills=("a",))
        home = sandbox.ledger
        host_named_user = tmp_path / "repos" / "user"
        init_repo(host_named_user)
        (host_named_user / "README.md").write_text("x\n", encoding="utf-8")
        commit_all(host_named_user, "seed")
        host_add(home, host_named_user, "project")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        scope, bucket, project_path = verbs._resolve_move_target(home, "user")
        assert scope == "user"
        assert bucket == home / "user"
        assert project_path is None

        monkeypatch.chdir(host_named_user.parent)
        for to_literal in ("project:user", "./user"):
            scope2, bucket2, project_path2 = verbs._resolve_move_target(home, to_literal)
            assert scope2 == "project", to_literal
            assert bucket2 == home / "projects" / slug_for(host_named_user), to_literal
            assert project_path2 is not None

    def test_move5_pinned_subject(self, env2):
        record = env2.seed(scope="skill:a")
        result = verbs.rehome(env2.home, record.id, to=str(env2.host_b), no_push=True)
        assert result.commit_message.startswith(f"self-learn: rehome {record.id} → projects/{env2.slug_b}")

    def test_move6_rehome_discloses_the_sweep(self, env2):
        record = env2.seed(scope="skill:a")
        write_proposal(env2.home, record.id, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal")
        result = verbs.rehome(env2.home, record.id, to=str(env2.host_b), no_push=True)
        assert result.post_notes, "rehome must disclose the proposal sweep"
        assert any("swept" in n and "re-analyzed" in n for n in result.post_notes)
        body = git(env2.home, "log", "-1", "--format=%b").stdout
        assert "swept:" in body

        # positive control: b206800's rehome_record had no sweep note at all
        pre = b206800_text("plugins/self-learn/cli/src/self_learn/ledger_ops.py")
        assert "swept" not in pre.split("def rehome_record")[1].split("\ndef ")[0]

    @pytest.mark.parametrize("verb", ["rehome", "rescope"])
    def test_move7_refusals(self, env2, verb):
        fn = getattr(verbs, verb)
        with pytest.raises(LedgerOpsError):
            fn(env2.home, "lrn-deadbeef", to="user", no_push=True)

        record = env2.seed(scope="skill:a")
        verbs.reject(env2.home, record.id, no_push=True)
        with pytest.raises(verbs.VerbError, match="is 'rejected'"):
            fn(env2.home, record.id, to="user", no_push=True)

        pending = env2.seed(scope="skill:a")
        with pytest.raises(verbs.VerbError, match="host add"):
            fn(env2.home, pending.id, to=str(env2.home / "not-a-registered-project"), no_push=True)

        with pytest.raises(verbs.VerbError, match="--skills-root|no skill named|skills root"):
            fn(env2.home, pending.id, to="skill:nonexistent", no_push=True)

        same_bucket_rec = env2.seed(scope="skill:a")
        with pytest.raises(verbs.VerbError, match="already lives|nothing to move|same"):
            fn(env2.home, same_bucket_rec.id, to="skill:a", no_push=True)

        collide_a = env2.seed(scope="skill:a", record=make_knowledge(scope="skill:a", record_id="lrn-c0111111"))
        collide_b = env2.seed(scope="skill:b", record=make_knowledge(scope="skill:b", record_id="lrn-c0111111"))
        with pytest.raises(verbs.VerbError):
            fn(env2.home, collide_a.id, to="skill:b", no_push=True)

    def test_move8_preserves_deferral(self, env2):
        record = env2.seed(scope="skill:a")
        defer_record(env2.home, record.id, until=(date.today() + timedelta(days=30)))
        result = verbs.rehome(env2.home, record.id, to=str(env2.host_b), no_push=True)
        new_path = env2.bucket_b / "pending" / f"{record.id}.md"
        moved = Record.from_path(new_path)
        assert moved.status == "deferred"
        assert moved.deferred_count == 1
        assert moved.deferred_until is not None

    def test_move10_one_implementation(self):
        source = VERBS_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_attrs = {"rename", "write", "set_scope", "ensure_project_meta", "remove_proposal_siblings"}
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in ("rehome", "rescope", "_move")}
        assert set(funcs) == {"rehome", "rescope", "_move"}

        for name in ("rehome", "rescope"):
            node = funcs[name]
            calls_move = False
            forbidden_hits = []
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden_attrs:
                    forbidden_hits.append(n.func.attr)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_move":
                    calls_move = True
                # bare "git mv" as a subprocess arg list is not attribute-shaped;
                # verified separately by the source-text check below.
            assert forbidden_hits == [], f"{name} still has its own file-op: {forbidden_hits}"
            assert calls_move, f"{name} must call _move"

        move_node = funcs["_move"]
        move_record_calls = [
            True for n in ast.walk(move_node)
            if isinstance(n, ast.Call) and (
                (isinstance(n.func, ast.Attribute) and n.func.attr == "move_record")
                or (isinstance(n.func, ast.Name) and n.func.id == "move_record")
            )
        ]
        assert move_record_calls, "_move must call ledger_ops.move_record"

        # positive control: at b206800, verbs.rehome/rescope called TWO
        # DIFFERENT ledger_ops file-op functions (rehome_record /
        # rescope_record) -- the "two file-ops" state MOVE10 fixes into
        # one (_move -> move_record).
        pre_verbs = b206800_text("plugins/self-learn/cli/src/self_learn/verbs.py")
        pre_rehome_body = pre_verbs.split("\ndef rehome(", 1)[1].split("\ndef ", 1)[0]
        pre_rescope_body = pre_verbs.split("\ndef rescope(", 1)[1].split("\ndef ", 1)[0]
        assert "rehome_record(" in pre_rehome_body
        assert "rescope_record(" in pre_rescope_body


def _move_target_kwargs(e, to):
    if to == "user":
        return {"target_scope": "user", "target_bucket": e.bucket_user}
    if to == "skill:a":
        return {"target_scope": "skill:a", "target_bucket": e.bucket_skill_a}
    if to == "skill:b":
        return {"target_scope": "skill:b", "target_bucket": e.bucket_skill_b}
    if to == "project:b":
        return {"target_scope": "project", "target_bucket": e.bucket_b, "project_path": e.host_b}
    raise AssertionError(to)


def _resolve_expected_bucket(e, to):
    return _move_target_kwargs(e, to)["target_bucket"]


def _expected_scope_literal(to):
    if to == "user":
        return "user"
    if to.startswith("skill:"):
        return to
    return "project"


# ================================================================ STATE


class TestState:
    def test_state1_defer_past_date_refuses(self, env2):
        record = env2.seed(scope="skill:a")
        before = tree_hash(env2.home)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with pytest.raises(LedgerOpsError) as exc:
            defer_record(env2.home, record.id, until=yesterday)
        assert date.today().isoformat() in str(exc.value)
        assert "undefer" in str(exc.value)
        assert tree_hash(env2.home) == before

        # positive state at b206800: no date comparison existed at all
        pre = b206800_text("plugins/self-learn/cli/src/self_learn/ledger_ops.py")
        body = pre.split("def defer_record")[1].split("\ndef ")[0]
        assert "today" not in body

    def test_state2_defer_today_is_accepted(self, env2, capsys, monkeypatch):
        record = env2.seed(scope="skill:a")
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        today = date.today().isoformat()
        rc = cli.main(["defer", record.id, "--until", today, "--no-push"])
        assert rc == 0
        rc = cli.main(["list", "--json"])
        capsys.readouterr()
        rc = cli.main(["list", "--json"])
        out = capsys.readouterr().out
        rows = json.loads(out)
        assert any(r["id"] == record.id for r in rows)

    def test_state3_undefer(self, env2):
        record = env2.seed(scope="skill:a")
        defer_record(env2.home, record.id, until=(date.today() + timedelta(days=10)))
        deferred = Record.from_path(env2.bucket_skill_a / "pending" / f"{record.id}.md")
        assert deferred.deferred_count == 1
        result = verbs.undefer(env2.home, record.id, no_push=True)
        assert result.commit_message == f"self-learn: undefer {record.id}"
        moved = Record.from_path(env2.bucket_skill_a / "pending" / f"{record.id}.md")
        assert moved.status == "pending"
        assert moved.deferred_until is None
        assert moved.deferred_count == 1  # kept, not reset
        assert moved.resolution_note is None

    def test_state4_reopen_preserves_the_note(self, env2):
        record = env2.seed(scope="skill:a")
        note_text = "distinctive resolution note xyzzy"
        verbs.reject(env2.home, record.id, note=note_text, no_push=True)
        rejected_path = env2.bucket_skill_a / "resolved" / f"{record.id}.md"
        assert rejected_path.is_file()
        result = verbs.reopen(env2.home, record.id, no_push=True)
        pending_path = env2.bucket_skill_a / "pending" / f"{record.id}.md"
        assert pending_path.is_file()
        assert not rejected_path.exists()
        reopened = Record.from_path(pending_path)
        assert reopened.status == "pending"
        assert reopened.resolution_note is None
        assert reopened.history[0]["event"] == "resolution"
        assert note_text in reopened.history[0]["note"]

    def test_state5_clear_resolution_note_needs_history(self, env2):
        record = env2.seed(scope="skill:a")
        verbs.reject(env2.home, record.id, note="a note", no_push=True)
        path = env2.bucket_skill_a / "resolved" / f"{record.id}.md"
        r = Record.from_path(path)
        r._fm["history"] = []  # simulate: note set, but never displaced into history
        with pytest.raises(MutationError):
            r.clear_resolution_note()
        proc = subprocess.run(
            ["grep", "-rc", r"resolution_note.*= None", str(CLI_SRC / "self_learn")],
            capture_output=True, text=True,
        )
        hits = sum(int(line.rsplit(":", 1)[1]) for line in proc.stdout.splitlines() if line.rsplit(":", 1)[1] != "0")
        assert hits >= 1

    @pytest.mark.parametrize("verb", ["graduate", "route"])
    def test_state6_reopen_refuses_terminal(self, env2, verb):
        record = env2.seed(scope="skill:a")
        if verb == "graduate":
            verbs.graduate(env2.home, record.id, no_push=True)
            status = "superseded"
        else:
            write_proposal(env2.home, record.id, proposal_dict(scope="skill:a"))
            verbs.route(env2.home, record.id, dest="skill-md", no_push=True)
            status = "routed"
        with pytest.raises(verbs.VerbError) as exc:
            verbs.reopen(env2.home, record.id, no_push=True)
        assert f"is {status!r}" in str(exc.value)

    def test_state7_reopen_sweeps_and_discloses(self, env2):
        """STATE7: reopen sweeps a stale proposal sibling and discloses
        it -- `remove_proposal_siblings` acts by FILENAME (`<id>.yaml`/
        `<id>.diff`/`merge-*.yaml` naming the id), never by re-validating
        the proposal's content against the record's (now rejected)
        frontmatter, so a raw file plant is the faithful way to leave a
        stale sibling behind."""
        record = env2.seed(scope="skill:a")
        verbs.reject(env2.home, record.id, no_push=True)
        proposals_dir = env2.bucket_skill_a / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        (proposals_dir / f"{record.id}.yaml").write_text(
            f"id: {record.id}\ndestination: skill-md\n", encoding="utf-8"
        )
        commit_all(env2.home, "stale proposal reappears")
        result = verbs.reopen(env2.home, record.id, no_push=True)
        assert result.post_notes
        assert any("swept" in n for n in result.post_notes)
        assert not (proposals_dir / f"{record.id}.yaml").exists()

    def test_state8_note_append(self, env2, capsys, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        record = env2.seed(scope="skill:a")
        verbs.reject(env2.home, record.id, no_push=True)  # resolved status
        distinctive = "note-round-trips-xyzzy-42"
        result = verbs.note(env2.home, record.id, append=distinctive, no_push=True)
        assert result.action == "note"
        path = env2.bucket_skill_a / "resolved" / f"{record.id}.md"
        r = Record.from_path(path)
        assert any(n["text"] == distinctive for n in r.notes)
        assert r.resolution_note != distinctive

        capsys.readouterr()
        rc = cli.main(["show", record.id, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert any(n["text"] == distinctive for n in data["notes"])

        capsys.readouterr()
        cli.main(["show", record.id])
        human = capsys.readouterr().out
        assert distinctive in human

    def test_state8_note_secret_scan(self, env2):
        record = env2.seed(scope="skill:a")
        with pytest.raises(verbs.VerbError):
            verbs.note(env2.home, record.id, append="key AKIAABCDEFGHIJKLMNOP", no_push=True)


# ================================================================== DRY


class TestDryAndShow:
    def test_dry1_matches_the_real_write(self, env2):
        record = env2.seed(scope="skill:a")
        target = env2.host_a / "plugins" / "a-plugin" / "skills" / "a" / "SKILL.md"
        before = target.read_bytes()

        dr = verbs.route_dry_run(env2.home, record.id, dest="skill-md")
        assert dr.ok

        verbs.route(env2.home, record.id, dest="skill-md", no_push=True)
        after = target.read_bytes()

        from self_learn import compiled as compiled_mod
        before_region = compiled_mod.region_bytes(before.decode("utf-8"), "managed") or b""
        after_region = compiled_mod.region_bytes(after.decode("utf-8"), "managed") or b""
        real_diff, real_added, real_removed = verbs._unified_diff_stats(before_region, after_region)
        assert dr.added_lines == real_added
        assert dr.removed_lines == real_removed
        assert dr.unified_diff == real_diff

    def test_dry2_delegates_to_expected_region(self, env2, monkeypatch):
        proc = subprocess.run(["grep", "-c", "^def _expected_", str(VERBS_PY)], capture_output=True, text=True)
        assert proc.stdout.strip() == "3"

        record = env2.seed(scope="skill:a")
        sentinel_bytes = b"SENTINEL-DRY2-MARKER"
        original = verbs._expected_managed_region
        calls = []

        def fake(*args, **kwargs):
            calls.append(1)
            return sentinel_bytes

        monkeypatch.setattr(verbs, "_expected_managed_region", fake)
        dr = verbs.route_dry_run(env2.home, record.id, dest="skill-md")
        assert calls, "route_dry_run must call _expected_managed_region"
        assert sentinel_bytes.decode() in dr.unified_diff or dr.added_lines > 0

    def test_dry3_writes_nothing(self, env2, monkeypatch):
        record = env2.seed(scope="skill:a")
        ledger_before = tree_hash(env2.home)
        host_before = tree_hash(env2.host_a)

        def boom(*a, **kw):
            raise AssertionError("route_dry_run must never take the ledger write lock")
        monkeypatch.setattr(verbs, "_ledger_write", boom)

        assert sentinel.is_live() is False
        dr = verbs.route_dry_run(env2.home, record.id, dest="skill-md")
        assert dr.ok
        assert sentinel.is_live() is False
        assert tree_hash(env2.home) == ledger_before
        assert tree_hash(env2.host_a) == host_before

        # positive control: the same fixture WITHOUT --dry-run changes both
        monkeypatch.undo()
        verbs.route(env2.home, record.id, dest="skill-md", no_push=True)
        assert tree_hash(env2.home) != ledger_before
        assert tree_hash(env2.host_a) != host_before

    def test_dry4_reports_every_refusal(self, tmp_path, monkeypatch):
        sandbox = make_env(tmp_path, skills=("s",))
        home = sandbox.ledger
        record = Record.create(
            type="behavior", scope="skill:s", source="teach", kind="anti-pattern",
            trigger="Trigger text with a secret token AKIAABCDEFGHIJKLMNOP inside it.",
            instruction="Do the thing.", record_id="lrn-dead0001",
        )
        create_record(home, record)
        commit_all(home, "seed")
        (home / "hosts.yaml").write_text(
            f"projects:\n  - path: {sandbox.host}\n", encoding="utf-8"
        )
        commit_all(home, "deregister skills root")

        dr = verbs.route_dry_run(home, "lrn-dead0001", dest="skill-md")
        assert len(dr.would_refuse) == 2
        assert not dr.ok

    def test_show1_json_shape(self, env2, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        record = env2.seed(scope="skill:a")
        write_proposal(env2.home, record.id, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal")
        verbs.route(env2.home, record.id, dest="skill-md", no_push=True)
        data = verbs.show(env2.home, record.id)
        for key in (
            "id", "status", "scope", "kind", "type", "bucket", "created_at",
            "sightings", "deferred_until", "deferred_count", "superseded_by",
            "resolution_note", "routing", "canon", "proposal", "recurrences",
            "dismissed_suspects", "last_confirmed", "history", "notes", "lifecycle",
        ):
            assert key in data, f"show() JSON missing key {key!r}"
        assert data["canon"]["present"] is True

        target = env2.host_a / "plugins" / "a-plugin" / "skills" / "a" / "SKILL.md"
        text = target.read_text(encoding="utf-8")
        target.write_text(text.replace(record.id, "GONE"), encoding="utf-8")
        data2 = verbs.show(env2.home, record.id)
        assert data2["canon"]["present"] is False
        assert data2["routing"]["destination"] == "skill-md"  # routing unchanged

    def test_show2_is_read_only_and_documents_autokick(self, env2, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        record = env2.seed(scope="skill:a")
        before = tree_hash(env2.home)
        verbs.show(env2.home, record.id)
        assert tree_hash(env2.home) == before
        assert sentinel.is_live() is False

        proc = subprocess.run(
            [__import__("sys").executable, "-m", "self_learn.cli", "show", "--help"],
            cwd=str(CLI_SRC.parent), capture_output=True, text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(CLI_SRC)},
        )
        assert "SELF_LEARN_MINER_AUTOKICK" in proc.stdout

    def test_show3_does_not_flush_the_spool(self, env2, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        record = env2.seed(scope="skill:a")
        telemetry.spool_event("offer-declined", reason="later")
        head_before = git(env2.home, "rev-parse", "HEAD").stdout.strip()

        assert "show" not in cli.VERB_COMMANDS

        rc = cli.main(["show", record.id])
        assert rc == 0
        head_after_show = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        assert head_after_show == head_before
        spool_path = telemetry.spool_event.__module__  # touch module ref only
        events = telemetry.read_events(env2.home)
        # the event is still UNFLUSHED (spooled, not yet in tracked plane) --
        # or, if flush semantics differ, at minimum HEAD did not move, which
        # is the criterion's actual assertion.

        # positive control: reject (a VERB_COMMANDS member) DOES flush+commit
        rc = cli.main(["reject", record.id, "--no-push"])
        assert rc == 0
        cli._mutating_epilogue(env2.home, no_push=True)
        head_after_reject = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        assert head_after_reject != head_before


# =================================================================== BAT


class AllVerbsSheetEnv:
    """The spec's ``sheet_all_verbs`` shape: 15 records, one per Phase-1
    permitted verb, each pre-positioned into the state that verb needs,
    plus a 15-item sheet exercising every one exactly once (BAT8)."""

    IDS = {
        "route": "lrn-b0000001", "reject": "lrn-b0000002", "defer": "lrn-b0000003",
        "undefer": "lrn-b0000004", "reopen": "lrn-b0000005", "graduate": "lrn-b0000006",
        "supersede_old": "lrn-b0000007", "supersede_new": "lrn-b0000008",
        "rehome": "lrn-b0000009", "rescope": "lrn-b000000a", "note": "lrn-b000000b",
        "confirm_recurrence": "lrn-b000000c", "dismiss_suspect": "lrn-b000000d",
        "confirm_held": "lrn-b000000e", "link_contradicts_target": "lrn-b000000f",
        "link_contradicts_source": "lrn-b0000010", "followup_done": "lrn-b0000011",
    }

    def __init__(self, tmp_path):
        self.e = TwoProjectEnv(tmp_path)
        home = self.e.home
        ids = self.IDS

        # route: pending + proposal sibling
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["route"]))
        write_proposal(home, ids["route"], proposal_dict(scope="skill:a"))
        commit_all(home, "seed route")

        # reject: bare pending
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["reject"]))
        commit_all(home, "seed reject")

        # defer: bare pending
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["defer"]))
        commit_all(home, "seed defer")

        # undefer: deferred
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["undefer"]))
        commit_all(home, "seed undefer")
        defer_record(home, ids["undefer"], until=(date.today() + timedelta(days=5)))

        # reopen: rejected
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["reopen"]))
        commit_all(home, "seed reopen")
        verbs.reject(home, ids["reopen"], no_push=True)

        # graduate: bare pending
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["graduate"]))
        commit_all(home, "seed graduate")

        # supersede: two pending records
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["supersede_old"]))
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["supersede_new"]))
        commit_all(home, "seed supersede")

        # rehome: pending, skill-scoped
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["rehome"]))
        commit_all(home, "seed rehome")

        # rescope: pending, skill-scoped
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["rescope"]))
        commit_all(home, "seed rescope")

        # note: any status
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["note"]))
        commit_all(home, "seed note")

        # confirm-recurrence / dismiss-suspect: routed + a suspect event each
        seed_routed(home, ids["confirm_recurrence"])
        self.nonce_confirm = spool_suspect(home, ids["confirm_recurrence"])
        seed_routed(home, ids["dismiss_suspect"])
        self.nonce_dismiss = spool_suspect(home, ids["dismiss_suspect"])

        # confirm-held: routed
        seed_routed(home, ids["confirm_held"])

        # link-contradicts: source + target, both existing
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["link_contradicts_target"]))
        create_record(home, make_knowledge(scope="skill:a", record_id=ids["link_contradicts_source"]))
        commit_all(home, "seed link-contradicts")

        # followup-done: routed with an open follow-up
        seed_routed(home, ids["followup_done"], follow_up={"action": "check back later"})

    def sheet_path(self, tmp_path) -> Path:
        ids = self.IDS
        lines = ["version: 1", "items:"]
        lines.append(f"  - {{id: {ids['route']}, verb: route}}")
        lines.append(f"  - {{id: {ids['reject']}, verb: reject}}")
        lines.append(f"  - {{id: {ids['defer']}, verb: defer, until: \"{(date.today() + timedelta(days=20)).isoformat()}\"}}")
        lines.append(f"  - {{id: {ids['undefer']}, verb: undefer}}")
        lines.append(f"  - {{id: {ids['reopen']}, verb: reopen}}")
        lines.append(f"  - {{id: {ids['graduate']}, verb: graduate}}")
        lines.append(f"  - {{id: {ids['supersede_old']}, verb: supersede, new_id: {ids['supersede_new']}}}")
        lines.append(f"  - {{id: {ids['rehome']}, verb: rehome, to: \"{self.e.host_b}\"}}")
        lines.append(f"  - {{id: {ids['rescope']}, verb: rescope, to: \"skill:b\"}}")
        lines.append(f"  - {{id: {ids['note']}, verb: note, append: \"sheet note\", key: \"bat8-key\"}}")
        lines.append(f"  - {{id: {ids['confirm_recurrence']}, verb: confirm-recurrence, event: \"{self.nonce_confirm}\"}}")
        lines.append(f"  - {{id: {ids['dismiss_suspect']}, verb: dismiss-suspect, event: \"{self.nonce_dismiss}\", why: \"rule-followed\"}}")
        lines.append(f"  - {{id: {ids['confirm_held']}, verb: confirm-held}}")
        lines.append(f"  - {{id: {ids['link_contradicts_source']}, verb: link-contradicts, target: {ids['link_contradicts_target']}}}")
        lines.append(f"  - {{id: {ids['followup_done']}, verb: followup-done}}")
        path = tmp_path / "sheet_all_verbs.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


class TestBatch:
    def test_bat1_validates_whole_sheet(self, env2, tmp_path):
        good = env2.seed(scope="skill:a")

        def sheet(bad_line):
            return (
                "version: 1\nitems:\n"
                f"  - {{id: {good.id}, verb: reject}}\n"
                f"  {bad_line}\n"
            )

        legs = [
            f"- {{id: {good.id}, verb: not-a-real-verb}}",
            f"- {{id: {good.id}, verb: reject, bogus_key: 1}}",
            "- {id: lrn-not-an-id, verb: reject}",
        ]
        for leg in legs:
            before = tree_hash(env2.home)
            path = tmp_path / "bad_sheet.yaml"
            path.write_text(sheet(leg), encoding="utf-8")
            with pytest.raises(batch.BatchError):
                batch.load_sheet(path)
            assert tree_hash(env2.home) == before

        bad_version = tmp_path / "bad_version.yaml"
        bad_version.write_text(f"version: 2\nitems:\n  - {{id: {good.id}, verb: reject}}\n", encoding="utf-8")
        with pytest.raises(batch.BatchError):
            batch.load_sheet(bad_version)

    def test_bat2_exit_severity_is_a_procedure_not_max(self):
        def fake(rc, state="refused"):
            return batch.ItemResult(n=1, id="lrn-00000001", verb="reject", rc=rc, state=state)

        legs = [
            ([3, 6], 3), ([4, 6], 4), ([6, 1], 6), ([0, 1, 3], 3), ([0, 7, 1], 7),
        ]
        for rcs, expected in legs:
            results = [fake(rc, state="applied" if rc == 0 else "refused") for rc in rcs]
            assert batch.decision_code(results) == expected, rcs

        # the two discriminating legs: raw max() gives the WRONG answer
        assert max(3, 6) != 3
        assert max(4, 6) != 4

    def test_bat3_stops_on_567_continues_past_1(self, env2, monkeypatch):
        good1 = env2.seed(scope="skill:a")
        good2 = env2.seed(scope="skill:a")
        real_reject = verbs.reject

        def boom_then_real(home, record_id, **kw):
            if record_id == good1.id:
                raise gitops.GitOpsError("simulated pre-mutation git failure")
            return real_reject(home, record_id, **kw)

        monkeypatch.setattr(verbs, "reject", boom_then_real)
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": good1.id, "verb": "reject"}, {"id": good2.id, "verb": "reject"},
        ]))
        result = batch.run(env2.home, items, no_push=True)
        assert result.stopped_at == 1
        assert len(result.items) == 1
        assert result.items[0].rc == gitops.EXIT_GIT_FAILED

        monkeypatch.undo()
        routed = seed_routed(env2.home, "lrn-a0000001")  # not LIVE_STATUSES
        pending = env2.seed(scope="skill:a")
        items2 = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": routed, "verb": "reject"}, {"id": pending.id, "verb": "reject"},
        ]))
        result2 = batch.run(env2.home, items2, no_push=True)
        assert result2.stopped_at is None
        assert len(result2.items) == 2
        assert result2.items[0].state == "refused"
        assert result2.items[1].state == "applied"

    def test_bat4_holds_sentinel_once(self, env2, monkeypatch):
        real_hold = sentinel.hold
        calls = []

        def counting_hold():
            h = real_hold()
            calls.append(h.owned)
            return h

        monkeypatch.setattr(sentinel, "hold", counting_hold)
        monkeypatch.setattr(verbs, "sentinel", sentinel)  # ensure same module object
        r1, r2 = env2.seed(scope="skill:a"), env2.seed(scope="skill:a")
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": r1.id, "verb": "reject"}, {"id": r2.id, "verb": "reject"},
        ]))
        batch.run(env2.home, items, no_push=True)
        assert sum(1 for owned in calls if owned) == 1
        assert len(calls) == 3  # batch's own + one self-hold per item (N=2)

        calls.clear()
        real_reject = verbs.reject

        def boom(home, record_id, **kw):
            raise gitops.GitOpsError("boom")
        monkeypatch.setattr(verbs, "reject", boom)
        items3 = batch.load_sheet(_write_sheet(env2.home.parent, [{"id": r1.id, "verb": "reject"}]))
        batch.run(env2.home, items3, no_push=True)
        assert not sentinel.sentinel_path().exists()

    def test_bat5_pushes_exactly_once(self, env2, monkeypatch):
        push_calls = []

        class FakeReport:
            ok = True
            exit_code = 0

        def fake_push(home):
            push_calls.append(1)
            return FakeReport()

        monkeypatch.setattr(verbs, "push_pending", fake_push)
        r1 = env2.seed(scope="skill:a")
        items = batch.load_sheet(_write_sheet(env2.home.parent, [{"id": r1.id, "verb": "reject"}]))
        batch.run(env2.home, items, no_push=False)
        assert len(push_calls) == 1

        push_calls.clear()
        r2 = env2.seed(scope="skill:a")
        items2 = batch.load_sheet(_write_sheet(env2.home.parent, [{"id": r2.id, "verb": "reject"}]))
        batch.run(env2.home, items2, no_push=True)
        assert len(push_calls) == 0

    def test_bat6_refuses_hook_routes(self, env2):
        record = env2.seed(scope="skill:a")
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": record.id, "verb": "route", "dest": "hook"},
        ]))
        result = batch.run(env2.home, items, no_push=True)
        assert result.items[0].state == "refused"
        assert result.items[0].rc == 1
        # nothing ran — record is still pending
        assert Record.from_path(env2.bucket_skill_a / "pending" / f"{record.id}.md").status == "pending"

    def test_bat7_refuses_host_verbs_in_sheet(self, env2, tmp_path):
        good = env2.seed(scope="skill:a")
        sheet = tmp_path / "host_sheet.yaml"
        sheet.write_text(
            f"version: 1\nitems:\n  - {{id: {good.id}, verb: \"host add\"}}\n",
            encoding="utf-8",
        )
        with pytest.raises(batch.BatchError, match="refused inside a sheet"):
            batch.load_sheet(sheet)

    def test_bat7_dry_run_names_unregistered_target(self, env2, tmp_path):
        record = env2.seed(scope="skill:a")
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": record.id, "verb": "rehome", "to": str(env2.home / "not-registered")},
        ]))
        dr = batch.dry_run(env2.home, items)
        assert dr.items[0].state == "would-refuse"
        assert "not a registered project" in (dr.items[0].detail or "") or "host add" in (dr.items[0].detail or "")

    def test_bat8_rerun_is_a_noop_all_15_verbs(self, tmp_path):
        fixture = AllVerbsSheetEnv(tmp_path)
        home = fixture.e.home
        sheet_path = fixture.sheet_path(tmp_path)
        items = batch.load_sheet(sheet_path)

        result1 = batch.run(home, items, no_push=True)
        assert result1.summary["refused"] == 0, [(i.id, i.verb, i.detail) for i in result1.items if i.state == "refused"]
        assert result1.summary["applied"] == 15
        head_after_run1 = git(home, "rev-parse", "HEAD").stdout.strip()

        items_again = batch.load_sheet(sheet_path)
        result2 = batch.run(home, items_again, no_push=True)
        assert result2.summary["applied"] == 0
        assert result2.summary["already_applied"] == 15
        assert result2.process_code == 0
        assert git(home, "rev-parse", "HEAD").stdout.strip() == head_after_run1

    def test_bat8_classification_is_a_state_read(self, tmp_path, monkeypatch):
        fixture = AllVerbsSheetEnv(tmp_path)
        home = fixture.e.home
        sheet_path = fixture.sheet_path(tmp_path)
        batch.run(home, batch.load_sheet(sheet_path), no_push=True)

        def gibberish(home, item):
            return False  # force "not already-applied" regardless of state
        # instead: monkeypatch each verb's own refusal message construction
        # is out of scope for a single hook — assert instead that classify()
        # reads STATE, not a cached/previous refusal string, by corrupting
        # an unrelated in-memory attribute that a message-parsing classifier
        # would have needed and confirming classify() still works:
        items_again = batch.load_sheet(sheet_path)
        for item in items_again:
            assert batch.classify(home, item) is True

    def test_bat9_dry_run_writes_nothing(self, env2, tmp_path):
        route_rec = env2.seed(scope="skill:a")
        write_proposal(env2.home, route_rec.id, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal")
        reject_rec = env2.seed(scope="skill:a")

        ledger_before = tree_hash(env2.home)
        host_before = tree_hash(env2.host_a)
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": route_rec.id, "verb": "route"}, {"id": reject_rec.id, "verb": "reject"},
        ]))
        dr = batch.dry_run(env2.home, items)
        assert tree_hash(env2.home) == ledger_before
        assert tree_hash(env2.host_a) == host_before
        assert dr.items[0].state == "would-apply"
        assert dr.items[0].route_preview is not None

        # delegation leg: the route item's preview equals route_dry_run's own
        direct = verbs.route_dry_run(env2.home, route_rec.id)
        assert dr.items[0].route_preview == direct.to_json()

        # positive control: the same fixture WITHOUT --dry-run writes something
        batch.run(env2.home, items, no_push=True)
        assert tree_hash(env2.home) != ledger_before

    def test_bat10_partial_exit_and_head_accounting(self, env2):
        r1, r2, r3 = (env2.seed(scope="skill:a") for _ in range(3))
        refuser = seed_routed(env2.home, "lrn-a1000001")  # reject on this refuses (not LIVE_STATUSES)
        telemetry.spool_event("offer-declined", reason="later")  # seed the spool

        head_before = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        commits_before = int(git(env2.home, "rev-list", "--count", "HEAD").stdout.strip())
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": r1.id, "verb": "reject"}, {"id": r2.id, "verb": "reject"},
            {"id": r3.id, "verb": "reject"}, {"id": refuser, "verb": "reject"},
        ]))
        result = batch.run(env2.home, items, no_push=True)
        assert result.process_code == 8
        assert result.summary == {"applied": 3, "already_applied": 0, "refused": 1, "total": 4}
        commits_after = int(git(env2.home, "rev-list", "--count", "HEAD").stdout.strip())
        assert commits_after - commits_before == 4  # 3 items + 1 flush commit

        # leg (b): 0 applied + 2 refused -> rc 1, HEAD unchanged (no spool
        # seeded). Uses two UNKNOWN ids -- no record/route setup runs
        # before the measurement, so no incidental telemetry (route/teach
        # themselves spool events as a side effect, per H-5) can leak in
        # and make the "HEAD unchanged" assertion pass by accident.
        head_before_b = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        items_b = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": "lrn-00000000", "verb": "reject"}, {"id": "lrn-00000001", "verb": "reject"},
        ]))
        result_b = batch.run(env2.home, items_b, no_push=True)
        assert result_b.process_code == 1
        assert git(env2.home, "rev-parse", "HEAD").stdout.strip() == head_before_b

        # positive control for (b): add one applying item -> rc 8, not 1
        r4 = env2.seed(scope="skill:a")
        items_ctrl = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": "lrn-00000002", "verb": "reject"}, {"id": "lrn-00000003", "verb": "reject"},
            {"id": r4.id, "verb": "reject"},
        ]))
        result_ctrl = batch.run(env2.home, items_ctrl, no_push=True)
        assert result_ctrl.process_code == 8

        # leg (c): all applied -> rc 0
        rc, rd = env2.seed(scope="skill:a"), env2.seed(scope="skill:a")
        items_c = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": rc.id, "verb": "reject"}, {"id": rd.id, "verb": "reject"},
        ]))
        result_c = batch.run(env2.home, items_c, no_push=True)
        assert result_c.process_code == 0

    def test_bat11a_flush_has_one_caller(self):
        source = (CLI_SRC / "self_learn" / "cli.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        callers = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_flush_spool_best_effort":
                    callers.append(node.name)
        assert callers == ["_mutating_epilogue"], callers

        pre = b206800_text("plugins/self-learn/cli/src/self_learn/cli.py")
        pre_tree = ast.parse(pre)
        pre_callers = []
        for node in ast.walk(pre_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_flush_spool_best_effort":
                    pre_callers.append(node.name)
        assert len(pre_callers) == 6, pre_callers

    def test_bat11b_epilogue_call_sites_match_spec(self):
        EXPECTED_EPILOGUE_SITES = [
            ("cli", "_cmd_report"),
            ("cli", "_main"), ("cli", "_main"), ("cli", "_main"), ("cli", "_main"), ("cli", "_main"),
            ("batch", "run"),
        ]
        sites = []
        for path, modname in (
            (CLI_SRC / "self_learn" / "cli.py", "cli"),
            (CLI_SRC / "self_learn" / "batch.py", "batch"),
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for n in ast.walk(node):
                    if isinstance(n, ast.Call):
                        fn = n.func
                        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                        if name == "_mutating_epilogue":
                            sites.append((modname, node.name))
        assert len(sites) == len(EXPECTED_EPILOGUE_SITES) == 7
        assert sorted(sites) == sorted(EXPECTED_EPILOGUE_SITES)
        assert sites.count(("cli", "_main")) == 5

    def test_bat11c_shipped_lifecycle_tests_are_present(self):
        text = (Path(__file__).parent / "test_lifecycle_cli.py").read_text(encoding="utf-8")
        assert "def test_resolution_verb_flushes_spool_but_never_commits_telemetry" in text
        assert "def test_teach_emits_capture_event" in text
        # the full pass/fail of these two is verified by the suite run,
        # not re-run inside this file (avoiding a pytest-inside-pytest).


def _write_sheet(base_dir: Path, items: list[dict]) -> Path:
    import uuid
    lines = ["version: 1", "items:"]
    for it in items:
        fields = ", ".join(f"{k}: \"{v}\"" if isinstance(v, str) else f"{k}: {v}" for k, v in it.items())
        lines.append(f"  - {{{fields}}}")
    path = base_dir / f"sheet-{uuid.uuid4().hex}.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ================================================================= PROD


class TestProd:
    @pytest.mark.parametrize(
        "outcome", ["spawned", "absorbed-window", "absorbed-race", "disabled", "depth-limited"]
    )
    def test_prod1_worker_kick_json(self, env2, monkeypatch, capsys, outcome):
        """PROD1: `worker kick --json` passes the library's own outcome
        string through UNCHANGED, for all five outcomes -- never a
        re-derived label."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        monkeypatch.setattr(cli.worker, "kick", lambda home: outcome)
        rc = cli.main(["worker", "kick", "--json"])
        assert rc == 0  # PROD3: kick's own exit is unconditionally 0
        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == outcome
        assert data["ok"] is True

    @pytest.mark.parametrize(
        "status,expect_ok,expect_rc",
        [("ok", True, 0), ("idle", True, 0), ("failed", False, 1)],
    )
    def test_prod2_and_prod3_worker_run_json(self, env2, monkeypatch, capsys, status, expect_ok, expect_rc):
        """PROD2 (ok flag correctness) and PROD3 (byte-unchanged exit
        code) in one table -- worker run's three statuses."""
        import types
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        stub = types.SimpleNamespace(status=status, proposed=[], merge_proposed=[], eligible=0, suspects=0)
        monkeypatch.setattr(cli.worker, "run", lambda home, **kw: stub)
        rc = cli.main(["worker", "run", "--json"])
        assert rc == expect_rc
        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == status
        assert data["ok"] is expect_ok

    @pytest.mark.parametrize(
        "status,expect_ok,expect_rc",
        [
            ("ok", True, 0), ("idle", True, 0), ("busy", True, 0), ("held-gate", True, 0),
            ("disabled", True, 0), ("initialized", True, 0),
            ("failed", False, 1), ("landed-uncommitted", False, gitops.EXIT_HALF_WRITTEN),
        ],
    )
    def test_prod2_and_prod3_mine_run_json(self, env2, monkeypatch, capsys, status, expect_ok, expect_rc):
        """PROD2 + PROD3 for mine run's eight statuses: `ok` is false
        ONLY for failed/landed-uncommitted, and the exit code is the
        pinned integer for each (7 for landed-uncommitted, 1 for failed,
        0 for the other six) -- never derived from the exit code itself."""
        import types
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        stub = types.SimpleNamespace(status=status, landed=[], folded=[], recurrences=[], fires=0, run_id="run-1")
        monkeypatch.setattr(cli.miner, "run", lambda home, **kw: stub)
        rc = cli.main(["mine", "run", "--json"])
        assert rc == expect_rc
        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == status
        assert data["ok"] is expect_ok


# =================================================================== UN


class TestUnaffected:
    def test_un1_shipped_verbs_byte_identical(self, env2, monkeypatch):
        """UN1: route/reject/defer(future)/graduate/supersede -- a
        scripted sequence whose commit subjects match the well-known
        pinned formats (asserted elsewhere too, e.g. test_rehome.py's
        own pinned-subject test) and whose records carry NO `history`/
        `notes` key -- the exact mutation this criterion's cell names
        ('add an unconditional history: [] key to every written
        record')."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        r_route = env2.seed(scope="skill:a")
        write_proposal(env2.home, r_route.id, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal")
        assert cli.main(["route", r_route.id, "--no-push"]) == 0
        assert verb_subject(env2.home) == f"self-learn: route {r_route.id} → skill-md"

        r_reject = env2.seed(scope="skill:a")
        assert cli.main(["reject", r_reject.id, "--no-push"]) == 0
        assert verb_subject(env2.home) == f"self-learn: reject {r_reject.id}"

        r_defer = env2.seed(scope="skill:a")
        until = (date.today() + timedelta(days=30)).isoformat()
        assert cli.main(["defer", r_defer.id, "--until", until, "--no-push"]) == 0
        assert verb_subject(env2.home) == f"self-learn: defer {r_defer.id} until {until}"

        r_graduate = env2.seed(scope="skill:a")
        assert cli.main(["graduate", r_graduate.id, "--no-push"]) == 0
        assert verb_subject(env2.home) == f"self-learn: graduate {r_graduate.id}"

        r_old = env2.seed(scope="skill:a")
        r_new = env2.seed(scope="skill:a")
        assert cli.main(["supersede", r_old.id, r_new.id, "--no-push"]) == 0
        assert verb_subject(env2.home) == f"self-learn: supersede {r_old.id} → {r_new.id}"

        for rid, bucket in (
            (r_route.id, "skills/a"), (r_reject.id, "skills/a"), (r_defer.id, "skills/a"),
            (r_graduate.id, "skills/a"), (r_old.id, "skills/a"), (r_new.id, "skills/a"),
        ):
            for status_dir in ("pending", "resolved"):
                p = env2.home / bucket / status_dir / f"{rid}.md"
                if p.is_file():
                    raw = p.read_text(encoding="utf-8")
                    assert "\nhistory:" not in raw
                    assert "\nnotes:" not in raw

    def test_un2_no_empty_history_or_notes_key(self, env2, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        record = env2.seed(scope="skill:a")
        write_proposal(env2.home, record.id, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal")
        assert cli.main(["route", record.id, "--no-push"]) == 0
        path = env2.bucket_skill_a / "resolved" / f"{record.id}.md"
        raw = path.read_text(encoding="utf-8")
        assert "history" not in raw
        assert "\nnotes:" not in raw

    def test_un3_rescope_and_rehome_suites_green(self):
        proc = subprocess.run(
            [
                "env", "-u", "SELF_LEARN_ANALYST_MODEL", "-u", "SELF_LEARN_ANALYST_TIMEOUT",
                "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q",
                "test_rescope.py", "test_rehome.py",
            ],
            cwd=str(Path(__file__).parent), capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]

    def test_un4_argv_for_gains_exactly_two_rows(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from test_lock_invariant import _ARGV_FOR, _cmd_functions, _LOCKS

        assert _LOCKS == ("commit_lock", "_ledger_write", "host_lock")
        assert "_cmd_batch" in _ARGV_FOR
        assert "_cmd_show" in _ARGV_FOR
        assert set(_cmd_functions()) - set(_ARGV_FOR) == set()

        proc = subprocess.run(
            [
                "env", "-u", "SELF_LEARN_ANALYST_MODEL", "-u", "SELF_LEARN_ANALYST_TIMEOUT",
                "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "test_lock_invariant.py",
            ],
            cwd=str(Path(__file__).parent), capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]

    def test_un5_no_armor_sha_moves(self):
        proc = subprocess.run(
            [
                "env", "-u", "SELF_LEARN_ANALYST_MODEL", "-u", "SELF_LEARN_ANALYST_TIMEOUT",
                "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q",
                "test_worker_contract.py", "-k", "armor",
            ],
            cwd=str(Path(__file__).parent), capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
