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
import hashlib
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from self_learn import batch, cases, cli, gitops, sentinel, telemetry, verbs
from self_learn.hosts import HostsError, host_add, skill_dir_for, slug_for
from self_learn.ledger_ops import (
    DEFERRED_ONLY,
    LIVE_STATUSES,
    LedgerOpsError,
    RECONSIDERABLE_STATUSES,
    REOPENABLE_STATUSES,
    RESOLVABLE_STATUSES,
    ROUTED_ONLY,
    bucket_project_path,
    create_record,
    defer_record,
    find_record_path,
    move_record,
    read_proposal,
    write_proposal,
)
from self_learn.records import RECORD_ID_RE, MutationError, Record, ValidationError
from support import (
    commit_all,
    force_past_deferred,
    git,
    hook_proposal_fields,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    merge_proposal_text,
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


def _host_snapshot(host_dir: Path) -> dict[str, tuple[str, int]]:
    """PH2's own instrument: a (sha256, mtime_ns) pair per tracked file
    under *host_dir*. ``tree_hash`` (below) fingerprints CONTENT only via
    ``git write-tree`` — a write that rewrote a file with byte-identical
    content (touch, or a compile-then-restore) would pass tree_hash
    unnoticed; mtime closes exactly that gap, which is why PH2 names
    both in the same snapshot."""
    snap: dict[str, tuple[str, int]] = {}
    for f in sorted(host_dir.rglob("*")):
        if not f.is_file() or ".git" in f.relative_to(host_dir).parts:
            continue
        rel = str(f.relative_to(host_dir))
        snap[rel] = (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_mtime_ns)
    return snap


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
    """PH1 (S-54, U-verbs Phase 2 build) lived here as a skip-marked
    tombstone through the code gate r1 round; deleted per the
    orchestrator's landing ruling (gate-confirmed safe: nothing
    references it by name, no test asserts a suite total, and armor's
    UN3 is hermetic post-landing so this working-tree deletion cannot
    move it). PH1 asserted the ABSENCE of six Phase-2 symbols
    (`reroute`, `retire_reference`, `records_targeting`, `bucket_prune`,
    `followup_add`, `reclassify`) from the Phase-1 tree -- true only
    while Phase 1 stood alone (spec S5.0's own verification window);
    once Phase 2 landed in the SAME tree those symbols exist BY DESIGN
    (RER/HOST/META), making the criterion genuinely obsolete rather
    than merely unneeded. It is not renamed or repurposed to check
    anything else -- it checked one thing, that thing stopped being
    true on purpose, and no successor criterion needs the same shape."""

    def test_ph2_batch_module_is_phase1_only(self):
        """Supporting check, NOT the PH2 discriminator (code gate r1,
        MAJ-1): batch.py's own PERMITTED_VERBS is exactly the 15 Phase-1
        verbs -- no Phase-2 verb name appears in it, and it is not a
        superset that would let a sheet name one. PH2's own criterion --
        Phase 1 writes to NO HOST -- is proven by
        ``test_phase1_touches_no_host`` below.

        gate r2 m-2: the hyphenated ``"followup-add"`` spelling below
        (matching the established sibling ``"followup-done"`` this
        module already uses at PERMITTED_KEYS/verbs.py/routes.py) is
        invisible to its OWN edit -- reverting it to the old
        ``"followup add"`` leaves the overlap assertion green either
        way, because NEITHER spelling is in PERMITTED_VERBS today. The
        explicit membership pin just below makes the correct spelling
        self-verifying: it fails directly if the literal reverts.

        U4 (2026-09-13, S-54 as amended, steward/overseer build): the
        literal 15 grows to 16 here -- `revise` is not a U-verbs
        Phase-2 verb (the `phase2_verbs` set below is unchanged and
        still excluded), it is the ONE new sheet verb a LATER,
        different unit adds to the sheet grammar on purpose
        ("PERMITTED_KEYS gains it together with the by: key",
        03-decisions.md S-54). A membership pin for it sits right below
        the count, the same discipline `followup-add` gets above, so
        the growth is self-verifying rather than a silent widening.

        S-67 (2026-09-14, U13): 16 grows to 17 -- `retire` joins as its
        own sheet verb (`graduate` stays too, the hidden alias for one
        release; PERMITTED_KEYS carries both). Not a Phase-2 verb
        either (`phase2_verbs` below is unchanged) -- the SAME
        self-verifying membership-pin discipline the two additions
        above already established."""
        phase2_verbs = {"reroute", "followup-add", "reclassify", "host remove", "bucket prune"}
        assert "followup-add" in phase2_verbs  # gate r2 m-2: pins the spelling itself
        assert not (batch.PERMITTED_VERBS & phase2_verbs)
        assert "revise" in batch.PERMITTED_VERBS  # U4: the one deliberate addition
        assert "retire" in batch.PERMITTED_VERBS  # S-67: the other deliberate addition
        assert len(batch.PERMITTED_VERBS) == 17

    def test_phase1_touches_no_host(self, tmp_path, monkeypatch):
        """PH2: a fixture with a registered host (env's ``host_a``) runs
        undefer, reopen, note, rehome, rescope, show, route --dry-run,
        and a one-item `batch` sheet (item: undefer) -- then the HOST
        tree's sha256+mtime snapshot is unchanged. Positive control
        FIRST, same fixture: a real `route` DOES change it. `batch` is
        the discriminating leg -- a `batch` that reached `_host_phase`
        for a non-route item would redden here and nowhere else."""
        e = TwoProjectEnv(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
        home = e.home

        # --- positive control: a REAL route DOES touch the host tree ---
        rid_route_real = "lrn-face0000"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_route_real))
        commit_all(home, "seed control")
        write_proposal(home, rid_route_real, proposal_dict(scope="skill:a"))
        host_before_control = _host_snapshot(e.host_a)
        verbs.route(home, rid_route_real, dest="skill-md", no_push=True)
        host_after_control = _host_snapshot(e.host_a)
        assert host_after_control != host_before_control, (
            "control is broken: a real route must change the host tree"
        )

        # baseline for the "unchanged" assertion is taken AFTER the
        # control's own write, so the eight verbs below are measured
        # against a host tree already known to be sensitive to writes.
        host_baseline = host_after_control

        # --- the eight PH2 verbs, none of which may touch the host ---
        rid_undefer = "lrn-face0001"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_undefer))
        commit_all(home, "seed undefer")
        defer_record(home, rid_undefer)
        verbs.undefer(home, rid_undefer, no_push=True)

        rid_reopen = "lrn-face0002"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_reopen))
        commit_all(home, "seed reopen")
        verbs.reject(home, rid_reopen, no_push=True)
        verbs.reopen(home, rid_reopen, no_push=True)

        rid_note = "lrn-face0003"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_note))
        commit_all(home, "seed note")
        verbs.note(home, rid_note, append="a commentary note", no_push=True)

        rid_rehome = "lrn-face0004"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_rehome))
        commit_all(home, "seed rehome")
        verbs.rehome(home, rid_rehome, to="user", no_push=True)

        rid_rescope = "lrn-face0005"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_rescope))
        commit_all(home, "seed rescope")
        verbs.rescope(home, rid_rescope, to="skill:b", no_push=True)

        rid_show = "lrn-face0006"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_show))
        commit_all(home, "seed show")
        verbs.show(home, rid_show)

        rid_dry = "lrn-face0007"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_dry))
        commit_all(home, "seed dry-run")
        write_proposal(home, rid_dry, proposal_dict(scope="skill:a"))
        verbs.route_dry_run(home, rid_dry, dest="skill-md")

        # batch: one-line sheet whose SINGLE item is `undefer` -- the
        # criterion's own discriminating leg.
        rid_batch = "lrn-face0008"
        create_record(home, make_knowledge(scope="skill:a", record_id=rid_batch))
        commit_all(home, "seed batch undefer")
        defer_record(home, rid_batch)
        items = batch.load_sheet(_write_sheet(home.parent, [
            {"id": rid_batch, "verb": "undefer"},
        ]))
        result = batch.run(home, items, no_push=True)
        assert result.items[0].state == "applied"

        host_after = _host_snapshot(e.host_a)
        assert host_after == host_baseline, (
            "Phase 1 verb touched the host tree — PH2 violation"
        )


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
            ("rehome", "rejected", "rejected"),
            ("rescope", "rejected", "rejected"),
        ],
    )
    def test_guard3_new_verbs_refuse_on_status(self, tmp_path, monkeypatch, verb, setup, expect_status):
        """GUARD3 (code gate r1, N3 -- now all FIVE named verbs, not 2):
        refuse on STATUS, never mere existence -- naming both the record
        and its actual status; an unknown id still hits 64. `rehome`/
        `rescope` were previously covered only incidentally by MOVE7 --
        this is GUARD3's own assertion of ITS OWN property (the status
        gate) for those two verbs, in the criterion's own shape."""
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

        if setup == "rejected":
            create_record(e.home, make_knowledge(scope="skill:a", record_id=rid))
            commit_all(e.home, "seed")
            verbs.reject(e.home, rid, no_push=True)

        fn = {
            "undefer": verbs.undefer, "reopen": verbs.reopen,
            "rehome": verbs.rehome, "rescope": verbs.rescope,
        }[verb]
        kwargs = {"to": "user"} if verb in ("rehome", "rescope") else {}
        with pytest.raises(verbs.VerbError) as exc:
            fn(e.home, rid, no_push=True, **kwargs)
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

    def test_move1_subjects(self, env2):
        """N1 (code gate r1): MOVE1's own criterion wants each leg's
        commit subject asserted too, via `git log -1 --format=%s` -- the
        `move_record` matrix above never commits (it is the file-op
        alone, MOVE10's own concern). This drives the VERB for all
        THREE dest-label arms `_move_dest_label` can produce -- only the
        project arm was pinned before (by MOVE5); `skills/<name>` and
        `user` were not."""
        rec_project = env2.seed(scope="skill:a")
        result_project = verbs.rehome(env2.home, rec_project.id, to=str(env2.host_b), no_push=True)
        assert result_project.commit_message == (
            f"self-learn: rehome {rec_project.id} → projects/{env2.slug_b}"
        )
        assert verb_subject(env2.home) == result_project.commit_message

        rec_skill = env2.seed(scope="user")
        result_skill = verbs.rescope(env2.home, rec_skill.id, to="skill:b", no_push=True)
        assert result_skill.commit_message == f"self-learn: rescope {rec_skill.id} → skills/b"
        assert verb_subject(env2.home) == result_skill.commit_message

        rec_user = env2.seed(scope="skill:a")
        result_user = verbs.rescope(env2.home, rec_user.id, to="user", no_push=True)
        assert result_user.commit_message == f"self-learn: rescope {rec_user.id} → user"
        assert verb_subject(env2.home) == result_user.commit_message

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

        # MAJ-3 (code gate r1): the chdir MUST be in effect for leg 1 too
        # -- _resolve_move_target falls a bare --to through to
        # Path(to).expanduser().resolve(), which is cwd-relative; from
        # the pytest rootdir Path("user").resolve() never reaches this
        # fixture's host, so a path-first (buggy) resolver would fall
        # through to the literal and pass anyway. Only with cwd already
        # at the host's own parent does leg 1 actually exercise "the
        # reserved literal wins over a same-named path" (M9's probe).
        monkeypatch.chdir(host_named_user.parent)

        scope, bucket, project_path = verbs._resolve_move_target(home, "user")
        assert scope == "user"
        assert bucket == home / "user"
        assert project_path is None

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
        defer_record(env2.home, record.id, until=(datetime.now(timezone.utc).date() + timedelta(days=30)))
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
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        with pytest.raises(LedgerOpsError) as exc:
            defer_record(env2.home, record.id, until=yesterday)
        assert datetime.now(timezone.utc).date().isoformat() in str(exc.value)
        assert "undefer" in str(exc.value)
        assert tree_hash(env2.home) == before

        # positive state at b206800: no date comparison existed at all
        pre = b206800_text("plugins/self-learn/cli/src/self_learn/ledger_ops.py")
        body = pre.split("def defer_record")[1].split("\ndef ")[0]
        assert "today" not in body

    def test_state1b_defer_clock_is_one_utc_clock(self, env2):
        """One clock, injectable: at 23:30 UTC on day D, ``--until D`` is
        accepted and ``--until D-1`` refuses naming ``D UTC`` — whatever the
        host's local date is (the 2026-08-28 17:00 PDT red: two clocks)."""
        d = date(2026, 8, 29)
        clock = datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc)
        rec_ok = env2.seed(scope="skill:a")
        [p_ok] = defer_record(env2.home, rec_ok.id, until=d.isoformat(), now=clock)
        assert Record.from_path(p_ok).deferred_until == "2026-08-29"
        rec_no = env2.seed(scope="skill:a")
        before = tree_hash(env2.home)
        with pytest.raises(LedgerOpsError) as exc:
            defer_record(env2.home, rec_no.id, until=(d - timedelta(days=1)).isoformat(), now=clock)
        assert "(today is 2026-08-29 UTC)" in str(exc.value)
        assert tree_hash(env2.home) == before
        # the default +30 d counts from the SAME clock
        rec_def = env2.seed(scope="skill:a")
        [p_def] = defer_record(env2.home, rec_def.id, now=clock)
        assert Record.from_path(p_def).deferred_until == "2026-09-28"

    def test_state2_defer_today_is_accepted(self, env2, capsys, monkeypatch):
        record = env2.seed(scope="skill:a")
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        today = datetime.now(timezone.utc).date().isoformat()
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
        defer_record(env2.home, record.id, until=(datetime.now(timezone.utc).date() + timedelta(days=10)))
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

        # N4 (code gate r1): the old leg 2 grepped the WHOLE package for
        # `resolution_note.*= None` and asserted `>= 1` -- a tautology
        # that cannot detect an added SECOND clearer anywhere else in the
        # file, since it never scopes to `clear_resolution_note` itself.
        # Extract JUST that method's source (AST) and assert an EXACT
        # count -- it must write `resolution_note = None` precisely
        # ONCE, and nowhere else in it.
        records_source = (CLI_SRC / "self_learn" / "records.py").read_text(encoding="utf-8")
        tree = ast.parse(records_source)
        method_node = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "clear_resolution_note"
        )
        method_source = ast.get_source_segment(records_source, method_node)
        assert method_source is not None
        hits = len(re.findall(r"resolution_note.*= None", method_source))
        assert hits == 1, method_source

        # N-r2-3 (code gate r2, optional hardening): the method-scoped
        # count above cannot see a SECOND clearer added elsewhere in the
        # package. One package-wide grep closes that: today there are
        # exactly 2 hits total -- this method's own write, and
        # `Record.create`'s field default (a creation default, not a
        # clearer) -- so "the only writer that may clear it" holds.
        proc = subprocess.run(
            ["grep", "-rc", r"resolution_note.*= None", str(CLI_SRC / "self_learn")],
            capture_output=True, text=True,
        )
        package_hits = sum(
            int(line.rsplit(":", 1)[1]) for line in proc.stdout.splitlines()
            if line.rsplit(":", 1)[1] != "0"
        )
        assert package_hits == 2, proc.stdout

    @pytest.mark.parametrize("verb", ["supersede", "route"])
    def test_state6_reopen_refuses_terminal(self, env2, verb):
        # S-67: `graduate`'s own terminal state (legacy `superseded_by:
        # canon`, a RETIREMENT) is no longer refused here -- `reopen`
        # now admits it (test_rename_retire.py's own
        # `TestReopenWidening` covers that positive case + its mutation).
        # `supersede` (a REPLACEMENT, a live-successor record id) is
        # this test's new terminal case for the same status,
        # `superseded` -- still refused, `route` unchanged.
        record = env2.seed(scope="skill:a")
        if verb == "supersede":
            successor = env2.seed(scope="skill:a")
            verbs.supersede(env2.home, record.id, successor.id, no_push=True)
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

    def test_dry3b_cli_surface_never_flushes_or_moves_head(self, env2, monkeypatch):
        """B1 (code gate r1): the CLI surface `self-learn route --dry-run`
        must be exactly as inert as the library call test_dry3 already
        proves — SHOW3's fixture shape (a seeded, unflushed spool) applied
        to `route --dry-run` instead of `show`. Before the fix, `route` was
        dispatched through VERB_COMMANDS even under --dry-run, so `_main`
        ran `_mutating_epilogue` on the way out and the epilogue's flush
        COMMITS (and, without --no-push, pushes)."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        record = env2.seed(scope="skill:a")
        telemetry.spool_event("offer-declined", reason="later")
        head_before = git(env2.home, "rev-parse", "HEAD").stdout.strip()

        rc = cli.main(["route", record.id, "--dest", "skill-md", "--dry-run", "--no-push"])
        assert rc == 0
        head_after = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        assert head_after == head_before, (
            "route --dry-run must not commit the telemetry flush"
        )

        # positive control: the same fixture WITHOUT --dry-run DOES flush
        # (mirrors PROBE2 epilogue-alone from the gate finding)
        rc = cli.main(["route", record.id, "--dest", "skill-md", "--no-push"])
        assert rc == 0
        head_after_real = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        assert head_after_real != head_before

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
        """SHOW3. N5 (code gate r1): the positive control must isolate
        the FLUSH itself as the thing that moves HEAD, not a verb's own
        (unrelated) resolution commit -- the old control ran `reject`
        after `show` and compared HEAD, but `reject` commits its OWN
        resolution regardless of any spool, so a passing assertion there
        proves nothing about the flush specifically. The isolated
        control here calls `_mutating_epilogue` ALONE, with no verb run
        at all, against the SAME seeded spool, and asserts both that
        HEAD moves AND that the new commit IS the flush (its own pinned
        subject) -- PROBE2's shape from the gate finding."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        record = env2.seed(scope="skill:a")
        telemetry.spool_event("offer-declined", reason="later")
        head_before = git(env2.home, "rev-parse", "HEAD").stdout.strip()

        assert "show" not in cli.VERB_COMMANDS

        rc = cli.main(["show", record.id])
        assert rc == 0
        head_after_show = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        assert head_after_show == head_before

        # positive control: the epilogue ALONE (no verb) DOES flush+commit,
        # and the commit IS the flush, not something else's write.
        cli._mutating_epilogue(env2.home, no_push=True)
        head_after_epilogue = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        assert head_after_epilogue != head_before
        subject = git(env2.home, "log", "-1", "--format=%s").stdout.strip()
        assert subject == "self-learn: telemetry flush 1 event"


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
        defer_record(home, ids["undefer"], until=(datetime.now(timezone.utc).date() + timedelta(days=5)))

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
        lines.append(f"  - {{id: {ids['route']}, verb: route, dest: skill-md}}")
        lines.append(f"  - {{id: {ids['reject']}, verb: reject}}")
        lines.append(f"  - {{id: {ids['defer']}, verb: defer, until: \"{(datetime.now(timezone.utc).date() + timedelta(days=20)).isoformat()}\"}}")
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
            # S-62 (13 §5, amending this row's own rule 3, 2026-09-11):
            # a mid-sheet 6 AFTER a landed commit is 8, never 6 — the
            # OLD rule (worst of {3,4,6,7}) returned 6 here, claiming
            # "nothing was written" over a sheet that plainly wrote one.
            ([0, 6], 8),
        ]
        for rcs, expected in legs:
            results = [fake(rc, state="applied" if rc == 0 else "refused") for rc in rcs]
            assert batch.decision_code(results) == expected, rcs

        # the two discriminating legs: raw max() gives the WRONG answer
        assert max(3, 6) != 3
        assert max(4, 6) != 4
        # S-62's own discriminating leg: raw max() over {0, 6} is 6, the
        # OLD (wrong, pre-S-62) answer this fix replaces with 8.
        assert max(0, 6) != 8

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
        # U3 (S-54 as amended, 02-schema.md §3a.1 rule 5): the result
        # carries the WHOLE sheet, not just what ran before the stop --
        # item 2 is now a `not-attempted` entry rather than absent.
        assert len(result.items) == 2
        assert result.items[0].rc == gitops.EXIT_GIT_FAILED
        assert result.items[1].state == "not-attempted"
        assert result.items[1].rc == -1

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
        """B2 (code gate r1): S-29 must actually bite. The old fixture had
        NO hook proposal, so the guard being removed (M34) left the test
        GREEN — `route`'s own unrelated preflight ('no proposal for this
        id') satisfied the same 3 assertions. Seed a REAL hook proposal
        (hook_proposal_fields — tools/path_regex/deny_message + replay
        examples, the same shape a compiling `route --dest hook` needs) so
        the only thing that can refuse this item is the batch-level S-29
        guard itself, and assert on the refusal's own text."""
        record = env2.seed(scope="skill:a")
        write_proposal(
            env2.home, record.id,
            proposal_dict(scope="skill:a", destination="hook",
                          alternates=["skill-md"], **hook_proposal_fields()),
        )
        commit_all(env2.home, "hook proposal")
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": record.id, "verb": "route", "dest": "hook"},
        ]))
        result = batch.run(env2.home, items, no_push=True)
        assert result.items[0].state == "refused"
        assert result.items[0].rc == 1
        detail = result.items[0].detail or ""
        assert "refused inside a batch" in detail
        assert "S-29" in detail
        # nothing ran — record is still pending
        assert Record.from_path(env2.bucket_skill_a / "pending" / f"{record.id}.md").status == "pending"

        # BAT6's second half: --dry-run names it as a SHEET-LEVEL blocker,
        # not just a per-item refusal.
        dr = batch.dry_run(env2.home, items)
        assert dr.hook_items == [record.id]

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
        """BAT8 leg 2 (code gate r1, MAJ-2): §3.3b requires classify() to
        be a STATE READ, never a trigger-and-catch of a refusal message.
        The old ``gibberish`` stub was dead code — this leg replaces it
        with the real probe: monkeypatch every function whose refusal (or
        success) TEXT could stand in for a state read -- every verbs.*
        dispatch function AND Record.append_contradicts, whose
        ValidationError text is literally "already contradicts" (the
        exact string M36 found a re-implementation reading instead of
        `target in record.contradicts`) -- to raise unrelated gibberish.
        If classify() ever calls (trigger) instead of reads (state) any
        of these, the gibberish exception propagates and this fails."""
        fixture = AllVerbsSheetEnv(tmp_path)
        home = fixture.e.home
        sheet_path = fixture.sheet_path(tmp_path)
        batch.run(home, batch.load_sheet(sheet_path), no_push=True)

        def gibberish(*a, **kw):
            raise AssertionError(
                "classify() must be a pure state read — it must never call "
                "a verb dispatch function or a message-constructing method "
                "(gibberish probe, code gate r1 MAJ-2 / M36)"
            )

        for fn_name in (
            "route", "reject", "defer", "undefer", "reopen", "graduate",
            "supersede", "rehome", "rescope", "note", "confirm_recurrence",
            "dismiss_suspect", "confirm_held", "link_contradicts",
            "followup_done",
        ):
            monkeypatch.setattr(verbs, fn_name, gibberish)
        monkeypatch.setattr(Record, "append_contradicts", gibberish)

        items_again = batch.load_sheet(sheet_path)
        assert len(items_again) == 15
        for item in items_again:
            assert batch.classify(home, item) is True, (
                f"{item.id}/{item.verb} did not classify as already-applied "
                "under the gibberish probe"
            )

    def test_bat9_dry_run_writes_nothing(self, env2, tmp_path):
        route_rec = env2.seed(scope="skill:a")
        write_proposal(env2.home, route_rec.id, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal")
        reject_rec = env2.seed(scope="skill:a")

        ledger_before = tree_hash(env2.home)
        host_before = tree_hash(env2.host_a)
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": route_rec.id, "verb": "route", "dest": "skill-md"},
            {"id": reject_rec.id, "verb": "reject"},
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

    def test_bat9b_route_dest_optional_never_a_silent_skip(self, env2, tmp_path):
        """N7 (code gate r1) then MAJ-r2-1 (code gate r2, over-correction
        fixed): `batch.classify`'s `route` arm used to accept ANY routed
        status as already-applied when the sheet gave no `dest` --
        unable to tell 'this is my own prior work, re-run' from 'this id
        happened to get routed by something else entirely' (the
        proposal that would resolve an implicit dest is swept the
        moment the first route lands). r1 closed the gap by making
        `dest` REQUIRED on every route sheet item -- but that refused
        the spec's OWN §4.4 example sheet line (`{verb: route,
        collapse: merge-...}`, no `dest`) at load time, exit 64.
        `classify`'s own `if f.get("dest") is None: return False`
        already closes the gap by itself (see
        `test_bat9c_spec_example_route_with_collapse_loads_and_applies`
        for the load-and-apply leg) -- so `REQUIRED_KEYS` no longer
        names `route` at all. This test is leg 2 of N7's original pair:
        a route item with an explicit `dest` against a record in a
        DIFFERENT resolved status (here, already `rejected`) is NEVER
        already-applied -- it reaches the verb at dispatch and comes
        back REFUSED, naming the actual state, never a silent
        already-applied skip."""
        rejected_rec = env2.seed(scope="skill:a")
        verbs.reject(env2.home, rejected_rec.id, no_push=True)
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": rejected_rec.id, "verb": "route", "dest": "skill-md"},
        ]))
        assert batch.classify(env2.home, items[0]) is False
        result = batch.run(env2.home, items, no_push=True)
        assert result.items[0].state == "refused"
        assert "rejected" in (result.items[0].detail or "")

    def test_bat9c_spec_example_route_with_collapse_loads_and_applies(self, env2):
        """MAJ-r2-1 (code gate r2): the spec's own §4.4 example sheet is
        quoted verbatim with a THIRD line that has no `dest` at all --
        `{id: lrn-4e95b3a6, verb: route, collapse: merge-1a2b3c4d}` --
        because a merge-collapse route's destination comes from the
        SURVIVOR's own proposal, never a literal the sheet author would
        type. r1's `REQUIRED_KEYS["route"] = {"dest"}` refused this
        exact shape at load time (exit 64, nothing runs) -- a contract
        §4.4 pins ('a permitted key is exactly a key that verb's CLI
        accepts'; the CLI's `--dest` is optional). Reproduces the gate's
        own probe: the example-shaped item LOADS, `classify` reads it
        as not-yet-applied (the record is still pending, not routed),
        and `batch.run` APPLIES it -- resolving the destination from
        the proposal sibling via `_resolved_route_dest`/
        `_resolve_destination`, exactly as `route` itself would without
        `--dest` on the command line."""
        survivor_id = "lrn-c0110001"
        loser_id = "lrn-c0110002"
        cluster = "merge-c0110000"
        survivor = make_behavior(
            record_id=survivor_id, scope="skill:a",
            trigger="Editing .storage live via the r2 collapse probe.",
        )
        loser = make_behavior(
            record_id=loser_id, scope="skill:a",
            trigger="Editing .storage while HA runs, r2 collapse probe.",
        )
        create_record(env2.home, survivor)
        create_record(env2.home, loser)
        lpath = env2.bucket_skill_a / "pending" / f"{loser_id}.md"
        lrec = Record.from_path(lpath)
        lrec.append_evidence({"session": "sess-b", "ts": "2026-07-14T00:00:00Z"})
        lrec.write(lpath)
        write_proposal(env2.home, survivor_id, proposal_dict(scope="skill:a"))
        write_proposal(env2.home, loser_id, proposal_dict(scope="skill:a"))
        (env2.bucket_skill_a / "proposals" / f"{cluster}.yaml").write_text(
            merge_proposal_text(cluster, [survivor_id, loser_id], survivor_id),
            encoding="utf-8",
        )
        commit_all(env2.home, "cluster seeded")

        # the spec's own example line shape: verb: route, collapse
        # given, dest OMITTED entirely.
        items = batch.load_sheet(_write_sheet(env2.home.parent, [
            {"id": survivor_id, "verb": "route", "collapse": cluster},
        ]))
        assert batch.classify(env2.home, items[0]) is False  # not yet routed

        result = batch.run(env2.home, items, no_push=True)
        assert result.items[0].state == "applied", result.items[0].detail

        survivor_rec = Record.from_path(env2.bucket_skill_a / "resolved" / f"{survivor_id}.md")
        assert survivor_rec.status == "routed"
        loser_rec = Record.from_path(env2.bucket_skill_a / "resolved" / f"{loser_id}.md")
        assert loser_rec.status == "superseded"
        assert loser_rec.superseded_by == survivor_id

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
        # U3: `summary` gained `not_attempted` (0 here -- a refusal
        # that is not a STOP code never truncates the sheet). Fold r1:
        # `summary` also gained `stopped` (0 here too -- the refusal is
        # rc=1, not a STOP code (5/6/7), so no item is `stopped`).
        assert result.summary == {
            "applied": 3, "already_applied": 0, "refused": 1,
            "stopped": 0, "not_attempted": 0, "total": 4,
        }
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
        # S-66 / 13 §7.4 (the overseer build, O-2a): `_main`'s dispatch
        # gained an EIGHTH call site (`hook activate`/`hook deactivate`,
        # the human path) alongside the pre-existing seven -- one more
        # `("cli", "_main")` entry, bumping that arm's own count below
        # from 5 to 6.
        EXPECTED_EPILOGUE_SITES = [
            ("cli", "_cmd_report"),
            ("cli", "_main"), ("cli", "_main"), ("cli", "_main"), ("cli", "_main"), ("cli", "_main"),
            ("cli", "_main"),
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
        assert len(sites) == len(EXPECTED_EPILOGUE_SITES) == 8
        assert sorted(sites) == sorted(EXPECTED_EPILOGUE_SITES)
        assert sites.count(("cli", "_main")) == 6

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
        "outcome,expect_rc",
        [
            ("spawned", 0),
            ("absorbed-window", cli.EXIT_HELD),
            ("absorbed-race", cli.EXIT_HELD),
            ("disabled", cli.EXIT_HELD),
            ("depth-limited", cli.EXIT_HELD),
        ],
    )
    def test_prod1_worker_kick_json(self, env2, monkeypatch, capsys, outcome, expect_rc):
        """PROD1: `worker kick --json` passes the library's own outcome
        string through UNCHANGED, for all five outcomes -- never a
        re-derived label -- and `ok` stays True for every outcome (none
        of the five is a failure). FW-85 (U0) SUPERSEDES this test's own
        prior PROD3 assertion ("kick's own exit is unconditionally 0",
        which FW-134 (`14-forward-work-map.md`) explicitly named this
        test as pinning against a later "improvement"): the exit code
        is no longer byte-unchanged across outcomes -- only `spawned`
        actually started a child, so only `spawned` returns `EXIT_OK`;
        the other four -- no child spawned, for a reason short of
        failure -- return the new `EXIT_HELD` (`commands/review.md`'s
        exit-code table)."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        monkeypatch.setattr(cli.worker, "kick", lambda home: outcome)
        rc = cli.main(["worker", "kick", "--json"])
        assert rc == expect_rc
        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == outcome
        assert data["ok"] is True

    @pytest.mark.parametrize(
        "status,expect_ok,expect_rc",
        [
            ("ok", True, 0),
            ("idle", True, cli.EXIT_HELD),
            ("failed", False, 1),
            ("stopped", False, gitops.EXIT_GIT_FAILED),
        ],
    )
    def test_prod2_and_prod3_worker_run_json(self, env2, monkeypatch, capsys, status, expect_ok, expect_rc):
        """PROD2 (ok flag correctness, unchanged by FW-85) and PROD3
        (the exit code) in one table -- worker run's four statuses
        (`worker.py`'s own `RunResult.status` docstring: `ok | idle |
        failed | stopped`; `stopped` was missing from this table before
        FW-85 -- added here for full discrimination). FW-85 (U0): `idle`
        (0 eligible -- nothing due) now returns the new `EXIT_HELD`
        rather than `0` -- `commands/review.md`'s exit-code table:
        "the new EXIT_HELD (10) means the run found nothing due and
        held ... before FW-85 it was indistinguishable from 0". `ok`
        stays True for `idle` (not a failure); only the exit code
        changed."""
        import types
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        stub = types.SimpleNamespace(
            status=status, proposed=[], merge_proposed=[], eligible=0, suspects=0
        )
        monkeypatch.setattr(cli.worker, "run", lambda home, **kw: stub)
        rc = cli.main(["worker", "run", "--json"])
        assert rc == expect_rc
        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == status
        assert data["ok"] is expect_ok

    @pytest.mark.parametrize(
        "status,expect_ok,expect_rc",
        [
            ("ok", True, 0),
            ("initialized", True, 0),
            ("idle", True, cli.EXIT_HELD),
            ("busy", True, cli.EXIT_HELD),
            ("held-gate", True, cli.EXIT_HELD),
            ("disabled", True, cli.EXIT_HELD),
            ("failed", False, 1),
            ("landed-uncommitted", False, gitops.EXIT_HALF_WRITTEN),
            ("stopped", False, gitops.EXIT_GIT_FAILED),
        ],
    )
    def test_prod2_and_prod3_mine_run_json(self, env2, monkeypatch, capsys, status, expect_ok, expect_rc):
        """PROD2 (ok flag correctness, unchanged by FW-85) + PROD3 (the
        exit code) for mine run's nine statuses (`stopped` was missing
        from this table before FW-85 -- added here for full
        discrimination). FW-85 (U0) SUPERSEDES this test's own prior
        PROD3 assertion (FW-134, `14-forward-work-map.md`, named this
        test's table as the "negative criterion" pinning `busy`/
        `held-gate`/`disabled`/`idle` at `0` "so a later builder cannot
        'improve' it silently" -- FW-85's own dated disposition on that
        same row is the authorization to do exactly that, for this
        SEPARATE run-command contract, not the verb/batch one FW-134's
        `EXIT_BATCH_PARTIAL` guards): `idle`/`held-gate`/`busy`/
        `disabled` are all "the run found nothing due and held" per
        `commands/review.md`'s exit-code table and now return the new
        `EXIT_HELD`, never `0`. `ok`/`landed-uncommitted`/`failed` are
        untouched; `initialized` performs a real one-time action
        (cursor seeding) and stays `EXIT_OK`."""
        import types
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        stub = types.SimpleNamespace(
            status=status, landed=[], folded=[], recurrences=[], fires=0, run_id="run-1"
        )
        monkeypatch.setattr(cli.miner, "run", lambda home, **kw: stub)
        rc = cli.main(["mine", "run", "--json"])
        assert rc == expect_rc
        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == status
        assert data["ok"] is expect_ok

    def test_prod4_mine_run_unmapped_status_raises(self, env2, monkeypatch):
        """S3 (code gate r1 fold, U0): the unmapped-status guard at
        `cli.py:1220-1226` is the mechanism that keeps PROD2/PROD3's
        table exhaustive as `MineResult.status` grows a value later --
        unpinned, a future builder could silently restore FW-85's own
        fail-open bug (an unmapped status returning `0`). A status
        absent from `_MINE_RUN_EXIT` must raise, not exit 0."""
        import types
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        stub = types.SimpleNamespace(
            status="quokka", landed=[], folded=[], recurrences=[], fires=0, run_id="run-1"
        )
        monkeypatch.setattr(cli.miner, "run", lambda home, **kw: stub)
        with pytest.raises(ValueError, match="unmapped MineResult.status"):
            cli.main(["mine", "run"])

    def test_prod5_worker_run_unmapped_status_raises(self, env2, monkeypatch):
        """S3 (code gate r1 fold, U0): the same guard's `worker run`
        twin, `cli.py:1373-1378` against `_WORKER_RUN_EXIT`. A status
        absent from that map must raise, not exit 0."""
        import types
        monkeypatch.setenv("SELF_LEARN_HOME", str(env2.home))
        stub = types.SimpleNamespace(
            status="quokka", proposed=[], merge_proposed=[], eligible=0, suspects=0
        )
        monkeypatch.setattr(cli.worker, "run", lambda home, **kw: stub)
        with pytest.raises(ValueError, match="unmapped RunResult.status"):
            cli.main(["worker", "run"])


# =================================================================== UN


class TestUnaffected:
    def test_un1_shipped_verbs_byte_identical(self, env2, monkeypatch):
        """UN1: route/reject/defer(future)/graduate/supersede -- a
        scripted sequence whose commit subjects match the well-known
        pinned formats (asserted elsewhere too, e.g. test_rehome.py's
        own pinned-subject test) and whose records carry NO `history`/
        `notes` key -- the exact mutation this criterion's cell names
        ('add an unconditional history: [] key to every written
        record').

        N6 (code gate r1, disclosed deviation, accepted): the spec's own
        shape for UN1 is a `baseline.json` generated once against a
        `b206800` worktree and diffed against commit BODIES and target
        FILE BYTES, not just subjects. This build asserts the pinned
        subjects and the history/notes-key absence directly instead --
        narrower (commit bodies and target file bytes are not compared),
        but it still catches the named mutation: `M63` (an unconditional
        `history: []` / `notes: []` write) is RED on both this test and
        `test_un2_no_empty_history_or_notes_key` below, via the same
        `"\nhistory:" not in raw` check UN2 makes explicit."""
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
        until = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
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

    @staticmethod
    def _method_names(source: str) -> set[str]:
        tree = ast.parse(source)
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name.startswith("test_")
                    ):
                        out.add(f"{node.name}::{item.name}")
        return out

    def test_un3_diff_scoped_nothing_lost(self):
        """N2 (code gate r1): the criterion's own diff leg -- test_rehome.py
        + test_rescope.py collect the SAME 53 tests before (`b206800`) and
        after this build, by NAME, not just by count (a same-count swap
        could still hide a silent deletion). Every name difference is one
        of the three DECLARED widened-behavior renames (§3.2/§3.2c:
        `rehome`'s non-project-source refusal, `rescope`'s project-scoped-
        source refusal, and `rescope`'s skill to skill refusal all became
        `_now_succeeds` tests) -- nothing else was deleted or renamed."""
        base = (
            self._method_names(b206800_text("plugins/self-learn/cli/tests/test_rehome.py"))
            | self._method_names(b206800_text("plugins/self-learn/cli/tests/test_rescope.py"))
        )
        cur = (
            self._method_names((Path(__file__).parent / "test_rehome.py").read_text())
            | self._method_names((Path(__file__).parent / "test_rescope.py").read_text())
        )
        assert len(base) == 53
        assert len(cur) == 53

        removed = base - cur
        added = cur - base
        expected_removed = {
            "TestRehomeRefusals::test_non_project_source_refuses",
            "TestRescopeRefusals::test_refuses_project_scoped_source",
            "TestRescopeRefusals::test_refuses_skill_to_skill",
        }
        expected_added = {
            "TestRehomeRefusals::test_non_project_source_now_succeeds",
            "TestRescopeRefusals::test_project_scoped_source_now_succeeds",
            "TestRescopeRefusals::test_skill_to_skill_now_succeeds",
        }
        assert removed == expected_removed, removed
        assert added == expected_added, added
        # every OTHER name survives untouched, proving nothing else lost
        assert (base - expected_removed) <= cur

    def test_un4_argv_for_gains_exactly_two_rows(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from test_lock_invariant import _ARGV_FOR, _cmd_functions, _LOCKS

        # S-62: `ledger_write` (the shared wrapper `_ledger_write` now
        # delegates to) joined `_LOCKS` alongside it -- a callee's lock
        # never discharges a caller's obligation, so both names stay
        # recognised by the walker.
        assert _LOCKS == ("commit_lock", "_ledger_write", "ledger_write", "host_lock")
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
        """2026-08-28: retargeted from `test_worker_contract.py -k armor`
        when U-armor's own DEL1/DEL2 retired `_ARMOR_SHAS` and its
        `test_su4a_*`/`test_su4b_*` tests -- `-k armor` now matches
        nothing there (exit 5), not 0. The property this guard exists
        to protect -- "this unit moved no armor pins" -- survives
        intact: it now lives in `test_armor.py`'s own byte-identity
        check, `test_fix1_fixtures_are_byte_identical`, which this
        guard runs instead."""
        proc = subprocess.run(
            [
                "env", "-u", "SELF_LEARN_ANALYST_MODEL", "-u", "SELF_LEARN_ANALYST_TIMEOUT",
                "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q",
                "test_armor.py", "-k", "fix1",
            ],
            cwd=str(Path(__file__).parent), capture_output=True, text=True,
        )
        assert proc.returncode == 0, (
            "test_armor.py::test_fix1_fixtures_are_byte_identical (this unit's own "
            "armor-pin guard) failed:\n" + proc.stdout[-4000:] + proc.stderr[-2000:]
        )


# =============================================================== U4 revise


def _seed_pending_behavior(
    env2,
    rid="lrn-90000001",
    scope="skill:a",
    trigger="About to edit .storage while HA is running.",
    instruction="Stop the container first.",
):
    create_record(
        env2.home,
        make_behavior(
            record_id=rid, scope=scope, trigger=trigger, instruction=instruction
        ),
    )
    commit_all(env2.home, "pending seed")
    return rid


def _tail_from(body: str, heading: str) -> str:
    """Everything from ``## <heading>`` to the end of *body* — the
    positive control :func:`test_revise_...` tests use to prove every
    OTHER section stayed byte-for-byte identical: for a two-section
    behavior record (Trigger, Instruction), revising Trigger must leave
    this exact tail untouched."""
    idx = body.index(f"## {heading}")
    return body[idx:]


class TestU4Revise:
    """U4 (build-u4.md): `self-learn revise` — the one new sheet verb
    this build adds (S-54 as amended, S-65). Covers build-u4.md's
    Tests section named cases (a routed record refused; a pending
    record changes exactly the named section; a deferred record
    allowed; a secret in ``text`` refused; the proposal survives with
    ``revised_at``; an unknown section name refused) plus one mutation
    of this builder's own choosing (heading-smuggling through
    ``--text``)."""

    def test_revise_refused_on_routed_record(self, env2):
        rid = seed_routed(env2.home, rid="lrn-90000010", scope="skill:a")
        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.revise(
                env2.home, rid, section="Trigger", text="New trigger wording.",
                because="tighten wording", no_push=True,
            )
        message = str(exc_info.value)
        assert "routed" in message
        assert "pending/deferred" in message  # require_status's own phrasing (02 §2)

    def test_revise_pending_changes_named_section_only(self, env2):
        rid = _seed_pending_behavior(env2, rid="lrn-90000011")
        before_body = Record.from_path(find_record_path(env2.home, rid)).body
        before_tail = _tail_from(before_body, "Instruction")

        result = verbs.revise(
            env2.home, rid, section="Trigger",
            text="About to edit .storage while HA is running (reworded).",
            because="tightened the trigger wording", no_push=True,
        )
        assert result.action == "revise"

        after = Record.from_path(find_record_path(env2.home, rid))
        assert "reworded" in after.body
        # positive control: the Instruction section (and everything
        # from its heading onward) is byte-for-byte identical.
        assert _tail_from(after.body, "Instruction") == before_tail

    def test_revise_deferred_allowed(self, env2):
        rid = _seed_pending_behavior(env2, rid="lrn-90000012")
        verbs.defer(env2.home, rid, no_push=True)
        assert Record.from_path(find_record_path(env2.home, rid)).status == "deferred"

        result = verbs.revise(
            env2.home, rid, section="Trigger", text="Reworded while deferred.",
            because="clarify", no_push=True,
        )
        assert result.action == "revise"
        after = Record.from_path(find_record_path(env2.home, rid))
        assert after.status == "deferred"  # revise never touches status
        assert "Reworded while deferred." in after.body

    def test_revise_secret_in_text_refused(self, env2):
        rid = _seed_pending_behavior(env2, rid="lrn-90000013")
        before = find_record_path(env2.home, rid).read_bytes()
        with pytest.raises(verbs.SecretRefusal):
            verbs.revise(
                env2.home, rid, section="Trigger",
                text="key AKIAABCDEFGHIJKLMNOP leaked here",
                because="oops", no_push=True,
            )
        # nothing written on refusal (P2-7: scan runs before any lock)
        assert find_record_path(env2.home, rid).read_bytes() == before

    def test_revise_keeps_proposal_and_stamps_revised_at(self, env2):
        rid = _seed_pending_behavior(env2, rid="lrn-90000014")
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal seed")
        proposal_path = (
            find_record_path(env2.home, rid).parent.parent
            / "proposals" / f"{rid}.yaml"
        )
        assert proposal_path.is_file()
        before_data = read_proposal(proposal_path)
        assert "revised_at" not in before_data

        result = verbs.revise(
            env2.home, rid, section="Trigger", text="Retitled trigger wording.",
            because="polish", by="steward", no_push=True,
        )
        assert result.action == "revise"

        # proposal file KEPT (never swept -- the record never left
        # pending/, so worker._still_pending's orphan sweep, keyed on
        # "no matching pending record", cannot reach it) and stamped.
        assert proposal_path.is_file()
        after_data = read_proposal(proposal_path)
        assert "revised_at" in after_data
        assert after_data["revised_by"] == "steward"
        # record_sha is deliberately left untouched (the analyst never
        # saw the new wording) -- still the fixture's original stub.
        assert after_data["record_sha"] == before_data["record_sha"]

    def test_revise_unknown_section_refused(self, env2):
        rid = _seed_pending_behavior(env2, rid="lrn-90000015")
        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.revise(
                env2.home, rid, section="Bogus", text="whatever",
                because="oops", no_push=True,
            )
        assert "Bogus" in str(exc_info.value)

    def test_revise_permitted_and_required_keys_in_batch(self):
        """Not the sheet-dispatch behaviour (U3/so-batch's own scope --
        see the builder's report for the spec-vs-plan note) — just the
        two dict entries this build actually adds."""
        assert batch.PERMITTED_KEYS["revise"] == frozenset(
            {"section", "text", "because", "by"}
        )
        assert batch.REQUIRED_KEYS["revise"] == frozenset(
            {"section", "text", "because"}
        )

    # U3 (build-u3.md, lane so-batch) landed `_dispatch`/`classify`/
    # `_STATUS_GATE` wiring for `revise` -- carried from the U4 gate
    # (gate-u4-r1.md F5): un-skipped, now passes for real.
    def test_revise_then_route_sheet_applies_both(self, env2):
        rid = _seed_pending_behavior(env2, rid="lrn-90000016")
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "proposal seed")
        sheet = env2.home / "sheet.yaml"
        sheet.write_text(
            "version: 1\n"
            "items:\n"
            f"  - id: {rid}\n"
            "    verb: revise\n"
            "    section: Trigger\n"
            "    text: Reworded before routing.\n"
            "    because: tighten wording before route\n"
            f"  - id: {rid}\n"
            "    verb: route\n"
            "    dest: skill-md\n",
            encoding="utf-8",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(env2.home, items, no_push=True)
        assert result.summary["applied"] == 2
        after = Record.from_path(find_record_path(env2.home, rid))
        assert after.status == "routed"
        assert "Reworded before routing." in after.body

    # ------------------------------------------------- builder's own mutation

    def test_revise_text_heading_smuggling_refused(self, env2):
        """Least-protected edge :func:`records.validate_body` cannot
        catch on its own: it only counts KNOWN headings, so a --text
        value carrying its own '## ' line would sail through set_body
        and grow the body a whole section through a verb whose entire
        contract is 'never a substance change' (02 §2 as amended)."""
        rid = _seed_pending_behavior(env2, rid="lrn-90000017")
        before = find_record_path(env2.home, rid).read_bytes()
        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.revise(
                env2.home, rid, section="Trigger",
                text="Fixed wording.\n\n## Sneaky\nSmuggled section.",
                because="oops", no_push=True,
            )
        assert "heading" in str(exc_info.value).lower()
        # nothing written on refusal
        assert find_record_path(env2.home, rid).read_bytes() == before

    @pytest.mark.parametrize("lead", [" ", "\t", "\n\n"])
    def test_revise_text_heading_smuggling_refused_with_leading_whitespace(
        self, env2, lead
    ):
        """Gate r1 F1: the guard is line-anchored and the splice strips,
        so a heading behind one leading space or tab was checked as a
        non-heading and then spliced back to the start of a line."""
        rid = _seed_pending_behavior(env2, rid="lrn-90000019")
        before = find_record_path(env2.home, rid).read_bytes()
        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.revise(
                env2.home, rid, section="Trigger",
                text=lead + "## Episode brief\nsmuggled section body.",
                because="probe", no_push=True,
            )
        assert "heading" in str(exc_info.value).lower()
        assert find_record_path(env2.home, rid).read_bytes() == before

    def test_revise_secret_in_because_refused(self, env2):
        """Gate r1 F2: `because` becomes the commit body, a tracked and
        autosynced artefact, so its scan is a non-bypassable rail (S-29)
        and needs its own red."""
        rid = _seed_pending_behavior(env2, rid="lrn-9000001b")
        before = find_record_path(env2.home, rid).read_bytes()
        with pytest.raises(verbs.SecretRefusal):
            verbs.revise(
                env2.home, rid, section="Trigger",
                text="A harmless rewording.",
                because="key AKIAABCDEFGHIJKLMNOP leaked in the reason",
                no_push=True,
            )
        assert find_record_path(env2.home, rid).read_bytes() == before

    def test_revise_identical_text_refused(self, env2):
        """Probed empirically (not assumed): `gitops.stage_and_commit`
        without `allow_empty=True` turns a byte-identical rewrite into
        `HalfWrittenError` ("nothing to commit"), which would be a
        confusing failure mode for a genuine no-op re-apply -- refused
        early instead, before any lock."""
        rid = _seed_pending_behavior(env2, rid="lrn-90000018")
        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.revise(
                env2.home, rid, section="Trigger",
                text="About to edit .storage while HA is running.",
                because="noop", no_push=True,
            )
        assert "nothing to revise" in str(exc_info.value)


# ================================================================== U5


def _u5_case(
    tmp_path, home, *, records, kind="resolution", outcome="route",
    supersedes=None, actor="steward", n=[0],
) -> str:
    """U5's own case-stage builder — same shape as `test_cases.py`'s
    `_write_stage`/`_record` and `test_batch.py`'s `_seed_case`,
    purpose-built here so this file needs no cross-import (both of
    those build against a different home fixture)."""
    n[0] += 1
    data = {
        "kind": kind,
        "trigger": "reconsider" if kind == "reconsider" else "nightly",
        "outcome": outcome,
        "records": list(records),
        "scope": "skill:a",
        "question": "U5 test case",
        "evidence": [{"ref": "transcript:u5test#L1", "quote": "u5 quote"}],
        "decision": {"verb": outcome, "because": "u5 test", "confidence": "settled"},
    }
    if supersedes is not None:
        data["supersedes"] = supersedes
    stage = tmp_path / f"u5-stage-{n[0]}.yaml"
    from ruamel.yaml import YAML
    import io

    y = YAML(typ="safe")
    y.default_flow_style = False
    buf = io.StringIO()
    y.dump(data, buf)
    stage.write_text(buf.getvalue(), encoding="utf-8")
    return cases.record(home, stage, actor=actor)


class TestU5Reconsider:
    """U5 (`build-u5.md`): `reconsider` records a successor decision
    against a routed/rejected/deferred record; it never itself changes
    the record's status or writes `superseded_by` on the old case —
    `cases.record` already wrote that link atomically when the
    reconsider case was created (naming the predecessor in
    `supersedes`)."""

    def test_1_no_reconsider_case_refuses(self, env2, tmp_path):
        """(a) a `resolution`-kind case over the SAME record: wrong
        kind. (b) a `reconsider`-kind case whose predecessor covers a
        DIFFERENT record: wrong record. Both refused, nothing written."""
        rid = seed_routed(env2.home, "lrn-95000001", scope="skill:a")
        before = find_record_path(env2.home, rid).read_bytes()

        wrong_kind = _u5_case(tmp_path, env2.home, records=[rid], kind="resolution")
        with pytest.raises(verbs.VerbError) as exc_a:
            verbs.reconsider(env2.home, rid, case=wrong_kind, no_push=True)
        assert "reconsider" in str(exc_a.value).lower()
        assert find_record_path(env2.home, rid).read_bytes() == before

        other_rid = seed_routed(env2.home, "lrn-95000002", scope="skill:a")
        other_before = find_record_path(env2.home, other_rid).read_bytes()
        other_case = _u5_case(tmp_path, env2.home, records=[other_rid], kind="resolution")
        reconsider_for_other = _u5_case(
            tmp_path, env2.home, records=[other_rid], kind="reconsider",
            outcome="reject", supersedes=other_case,
        )
        with pytest.raises(verbs.VerbError) as exc_b:
            verbs.reconsider(env2.home, rid, case=reconsider_for_other, no_push=True)
        assert "record" in str(exc_b.value).lower()
        assert find_record_path(env2.home, rid).read_bytes() == before
        assert find_record_path(env2.home, other_rid).read_bytes() == other_before

    def test_2_valid_case_appends_history_status_unchanged(self, env2, tmp_path):
        rid = seed_routed(env2.home, "lrn-95000003", scope="skill:a")
        old_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="resolution", outcome="route"
        )
        reconsider_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="reconsider",
            outcome="reject", supersedes=old_case,
        )
        # `cases.record` itself already flipped the predecessor's
        # `superseded_by` at CASE-CREATION time (`test_cases.py::
        # test_supersedes_sets_superseded_by_on_the_target` pins that
        # mechanism directly) — asserted here as the FIXTURE's own
        # state, not evidence of what `reconsider` itself writes.
        old_view = cases.show(env2.home, old_case, evidence_only=False)
        assert old_view.frontmatter["superseded_by"] == reconsider_case

        result = verbs.reconsider(
            env2.home, rid, case=reconsider_case, by="steward", no_push=True
        )
        assert result.action == "reconsider"

        record = Record.from_path(find_record_path(env2.home, rid))
        assert record.status == "routed"  # unchanged — reconsider never flips it
        assert record.history[-1]["event"] == "reconsidered"
        assert record.history[-1]["case"] == reconsider_case
        assert record.history[-1]["supersedes"] == old_case

    def test_4_reopen_still_refused_for_replaced_record(self, env2):
        """Regression guard (distinct from `test_state6_reopen_refuses_
        terminal`'s graduate/route parametrization, which never exercises
        a record-to-record `supersede`): a RECORD-id supersession
        ("replaced") stays refused for `reopen`, same as before U5 —
        `REOPENABLE_STATUSES` is untouched by this build."""
        old_id = seed_routed(env2.home, "lrn-95000004", scope="skill:a")
        new_record = env2.seed(scope="skill:a")
        verbs.supersede(env2.home, old_id, new_record.id, no_push=True)
        replaced_path = env2.bucket_skill_a / "resolved" / f"{old_id}.md"
        assert Record.from_path(replaced_path).status == "superseded"
        with pytest.raises(verbs.VerbError) as exc:
            verbs.reopen(env2.home, old_id, no_push=True)
        assert "superseded" in str(exc.value)

    def test_5_outcome_not_applicable_to_status_refuses(self, env2, tmp_path):
        """U5's own least-protected surface (not named in `build-u5.md`'s
        test list): `_OUTCOME_APPLICABLE_STATUSES` refuses a reconsider
        case whose `outcome` cannot correct the record's CURRENT status
        even though the case itself is otherwise perfectly valid (right
        kind, right record) — `outcome: route` never widens `route`'s
        own admitted statuses, so it applies only to a `deferred`
        record, never an already-`routed` one."""
        rid = seed_routed(env2.home, "lrn-95000005", scope="skill:a")
        old_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="resolution", outcome="route"
        )
        reconsider_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="reconsider",
            outcome="route", supersedes=old_case,
        )
        with pytest.raises(verbs.VerbError) as exc:
            verbs.reconsider(env2.home, rid, case=reconsider_case, no_push=True)
        assert "route" in str(exc.value) and "routed" in str(exc.value)

    def test_6_outcome_applicable_to_rejected_record_for_the_reopen_shape(
        self, env2, tmp_path
    ):
        """Fold r1 (F3, the orchestrator's ruling): `reconsider` itself
        must accept an outcome that corrects a WRONG REJECT while the
        record is STILL `rejected` — the corrective verb only runs
        afterward, in a sheet whose first item is `reopen`
        (`test_batch.py::TestU5ReconsiderReopenShape` covers that full
        flow). Before this fix,
        `_OUTCOME_APPLICABLE_STATUSES["route"]` excluded `rejected`
        entirely and this call refused."""
        rid = "lrn-95000006"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending seed")
        verbs.reject(env2.home, rid, no_push=True)
        assert (
            Record.from_path(find_record_path(env2.home, rid)).status == "rejected"
        )

        old_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="resolution", outcome="reject"
        )
        reconsider_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="reconsider",
            outcome="route", supersedes=old_case,
        )
        result = verbs.reconsider(env2.home, rid, case=reconsider_case, no_push=True)
        assert result.action == "reconsider"
        record = Record.from_path(find_record_path(env2.home, rid))
        assert record.status == "rejected"  # reconsider itself never flips it
        assert record.history[-1]["event"] == "reconsidered"
        assert record.history[-1]["case"] == reconsider_case


class TestU5ReconsiderCLI:
    """Fold r1 (F4, F5): CLI-level checks on `self-learn reconsider`
    that `build-u5.md`'s own test list did not cover (verb/batch-level
    only) -- the gate's own probes (P9, R2) were run by hand, never
    committed."""

    def test_json_outcome_state_is_landed_not_drift(self, env2, tmp_path, capsys):
        """Fold r1 (F4): `reconsider` never attempts a host write --
        the ledger resolution (a `reconsidered` history entry) IS the
        whole verb, same shape `reject`/`defer` already have. Before
        this fix `_outcome_state` fell through to route's 4-state
        predicate and reported `drift` (`compile_result is None`) on a
        fully successful call."""
        rid = seed_routed(env2.home, "lrn-95000007", scope="skill:a")
        old_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="resolution", outcome="route"
        )
        reconsider_case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="reconsider",
            outcome="reject", supersedes=old_case,
        )
        rc = cli.main(
            ["reconsider", rid, "--case", reconsider_case, "--no-push", "--json"]
        )
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "reconsider"
        assert out["outcome_state"] == "landed"

    def test_unknown_case_exits_64_not_1(self, env2):
        """Fold r1 (F5): an unknown/malformed CASE id must exit 64
        (EX_USAGE), the same discipline every other surface's
        unknown-id refusal already gets (`commands/review.md`: "An
        unknown record id is 64 (usage), not 1") — before this fix,
        both `_reconsider_case_check` and `reconsider`'s own wrap
        discarded `cases.CaseUsageError.exit_code` and substituted
        `VerbError`'s default of 1."""
        rid = seed_routed(env2.home, "lrn-95000008", scope="skill:a")
        rc = cli.main(
            ["reconsider", rid, "--case", "case-deadbeef", "--no-push"]
        )
        assert rc == 64
