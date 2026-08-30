"""U-verbs Phase 2 (T2) -- the unit's own test file for the CLI-touching
[B] criteria RER1-7, HOST1-5, META1-5 (17 pytest-checked criteria).

Phase 1's own file (test_u_verbs.py) covers every Phase-1 [A] criterion
and stays untouched here except for the two shipped-test fixes recorded
in this build's report (PH1's own claim retired by
@pytest.mark.skip, and test_route_observability.py's _DRY_RUN_EXEMPT
gaining "followup_add"). This file imports TwoProjectEnv/env2/
seed_routed/b206800_text from that file rather than duplicating them --
the same cross-file reuse pattern the UI side's test_u_verbs.py already
uses against test_proposals.py.

Every test here is the ONE named, discriminating check the spec's
S6 table names for its criterion -- never "by construction". Fixtures
are purpose-built per test, matching Phase 1's own declared deviation
from the spec's literal 18-fixture list (still driving the SAME state,
discriminating the SAME mutation).

All ledger homes are throwaway sandbox repos under pytest tmpdirs
(support.make_env / test_u_verbs.TwoProjectEnv) -- never the real
~/.self-learn.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from self_learn import cli, records as records_mod, verbs
from self_learn.hosts import (
    HostRemoveRefused,
    host_add,
    records_targeting,
    slug_for,
)
from self_learn.ledger_ops import (
    create_record,
    find_record_path,
    stamp_proposal,
    write_proposal,
)
from self_learn.records import Record

from support import (
    commit_all,
    git,
    hook_proposal_fields,
    init_repo,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
)

from test_u_verbs import env2, seed_routed

REPO_ROOT = Path(__file__).resolve().parents[4]


def _call_name(func: ast.expr) -> str | None:
    """gate r2 m-1: the SAME name-of-a-call-target helper
    `test_route_observability.py` already uses for its own AST guards --
    a plain `name(...)` or a `module.name(...)`/`self.name(...)`
    attribute call, never a string match."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


# =================================================================== RER


class TestRER1RewritesRoutingAndHistory:
    def test_reroute_rewrites_routing(self, env2):
        rid = seed_routed(env2.home, scope="skill:a")
        result = verbs.reroute(
            env2.home, rid, dest="claude-md", by="human", no_push=True
        )
        assert result.commit_message == f"self-learn: reroute {rid} → claude-md"
        path = find_record_path(env2.home, rid)
        record = Record.from_path(path)
        assert record.routing["destination"] == "claude-md"
        assert record.routing["by"] == "human"
        # the OLD block is DISPLACED into history, event "routing" --
        # never destroyed (RER1's own wording).
        assert len(record.history) == 1
        entry = record.history[0]
        assert entry["event"] == "routing"
        assert entry["routing"]["destination"] == "skill-md"

    def test_reroute_commit_message_names_the_destination_qualifier(self, env2):
        """Minor (U-verbs Phase 2 code gate r1): the commit subject must
        NAME any destination qualifier -- claude-md:rules:<topic>,
        reference:<file> -- not just the bare destination word. The old
        `message = f"self-learn: reroute {record_id} \u2192 {destination}"`
        line dropped it; `_routing_dest_label` is the ONE place this
        vocabulary is already spelled out (RER3's own same-destination
        refusal message uses it for the OLD side; this pins the NEW
        side too)."""
        rid = seed_routed(env2.home, scope="skill:a")
        result = verbs.reroute(
            env2.home, rid, dest="reference:CustomFile.md", no_push=True
        )
        assert (
            result.commit_message
            == f"self-learn: reroute {rid} \u2192 reference:CustomFile.md"
        )


class TestRER2RetiresAndCompilesOneMotion:
    def test_reroute_retires_and_compiles_claude_md_to_skill_md(self, env2):
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        r1 = verbs.route(env2.home, rid, dest="claude-md", no_push=True)
        old_target = r1.target  # <host>/CLAUDE.md
        old_text_before = old_target.read_text(encoding="utf-8")
        assert f"*({rid})*" in old_text_before  # positive control

        result = verbs.reroute(env2.home, rid, dest="skill-md", no_push=True)
        new_target = result.target  # .../skills/a/SKILL.md
        assert new_target != old_target
        assert f"*({rid})*" in new_target.read_text(encoding="utf-8")
        # old target's managed section no longer carries the entry line.
        assert f"*({rid})*" not in old_target.read_text(encoding="utf-8")

    def test_reroute_retires_and_compiles_reference_to_claude_md(self, env2):
        rid = "lrn-0000bbbb"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        r1 = verbs.route(env2.home, rid, dest="reference", no_push=True)
        ref_path = r1.compile_result.path
        assert f"— {rid}" in ref_path.read_text(encoding="utf-8")  # positive control

        result = verbs.reroute(env2.home, rid, dest="claude-md", no_push=True)
        new_target = result.target
        assert f"*({rid})*" in new_target.read_text(encoding="utf-8")
        # the reference's heading block for this record is gone.
        assert f"— {rid}" not in ref_path.read_text(encoding="utf-8")


class TestRER3SameDestinationRefuses:
    def test_reroute_same_dest_refuses(self, env2):
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        verbs.route(env2.home, rid, dest="claude-md", no_push=True)
        before = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        target_path = find_record_path(env2.home, rid)
        before_bytes = target_path.read_bytes()

        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.reroute(env2.home, rid, dest="claude-md", no_push=True)
        message = str(exc_info.value)
        assert "already routed to claude-md" in message
        assert "nothing to change" in message
        assert exc_info.value.exit_code == 1

        # nothing written: same ledger HEAD, record bytes unchanged.
        after = git(env2.home, "rev-parse", "HEAD").stdout.strip()
        assert after == before
        assert target_path.read_bytes() == before_bytes


class TestRER4OneMotionDestinations:
    def test_reroute_one_motion_destinations(self, env2):
        # INTO refusal legs -- reroute never lands a fresh route/new-skill.
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        verbs.route(env2.home, rid, dest="claude-md", no_push=True)
        for bad_dest in ("hook", "new-skill"):
            with pytest.raises(verbs.VerbError) as exc_info:
                verbs.reroute(env2.home, rid, dest=bad_dest, by="human", no_push=True)
            message = str(exc_info.value)
            assert f"reroute --dest {bad_dest}" in message
            assert "one-motion destination" in message
            assert exc_info.value.exit_code == 1

        # AWAY-FROM leg -- rerouting off an ALREADY-hook-routed record
        # to a plain destination works (the retirement half already
        # exists for both one-motion destinations).
        rid2 = "lrn-0000bbbb"
        create_record(env2.home, make_behavior(record_id=rid2, scope="skill:a"))
        write_proposal(
            env2.home, rid2,
            proposal_dict(scope="skill:a", destination="hook", **hook_proposal_fields()),
        )
        stamp_proposal(env2.home, rid2)
        commit_all(env2.home, "pending2")
        r_hook = verbs.route(env2.home, rid2, dest="hook", no_push=True)
        assert r_hook.diff  # positive control -- the hook route actually landed
        r_away = verbs.reroute(env2.home, rid2, dest="claude-md", by="human", no_push=True)
        assert r_away.target is not None
        assert f"*({rid2})*" in r_away.target.read_text(encoding="utf-8")


class TestRER5RetireReference:
    def test_retire_reference(self, tmp_path):
        from self_learn import compilers

        refs_dir = tmp_path / "refdir"
        refs_dir.mkdir()
        ref_path = refs_dir / "LEARNINGS.md"
        header = compilers._LEARNINGS_HEADER
        e1 = "## 2026-08-01 — lrn-00000001\n\n**Trigger:** t1.\n\n**Instruction:** i1."
        e2 = (
            "## 2026-08-02 — lrn-00000002\n\n**Trigger:** t2 line one.\n"
            "t2 line two.\n\n**Instruction:** i2 para one.\n\ni2 para two."
        )
        e3 = "## 2026-08-03 — lrn-00000003\n\n**Trigger:** t3.\n\n**Instruction:** i3."
        ref_path.write_text(
            header + "\n" + e1 + "\n\n" + e2 + "\n\n" + e3 + "\n", encoding="utf-8"
        )
        result = compilers.retire_reference(refs_dir, "lrn-00000002")
        assert result.applied is True
        text = ref_path.read_text(encoding="utf-8")
        assert "lrn-00000002" not in text  # the removed block, gone entirely
        # the OTHER two entries are byte-identical, exactly one blank
        # line apart (no multi-paragraph tail survives the removal).
        assert header + "\n" + e1 + "\n\n" + e3 + "\n" == text

        # idempotent: calling again with nothing left to remove reports
        # applied=False, and changes nothing further.
        result2 = compilers.retire_reference(refs_dir, "lrn-00000002")
        assert result2.applied is False
        assert ref_path.read_text(encoding="utf-8") == text

    def test_retire_reference_never_touches_bytes_outside_the_removed_block(
        self, tmp_path
    ):
        """M-2 (U-verbs Phase 2 code gate r1): a SURVIVING entry's own
        internal blank-line run is not the removal's business -- the old
        `re.sub(r"\n{3,}", "\n\n", new_text)` was GLOBAL (whole-file),
        so it silently collapsed a human's own 3+-blank-line gap anywhere
        in the file, not just at the removal seam. e1's body carries a
        deliberate 4-newline gap that has nothing to do with e2's
        removal; it must survive byte-for-byte."""
        from self_learn import compilers

        refs_dir = tmp_path / "refdir"
        refs_dir.mkdir()
        ref_path = refs_dir / "LEARNINGS.md"
        header = compilers._LEARNINGS_HEADER
        e1 = (
            "## 2026-08-01 \u2014 lrn-00000001\n\n**Trigger:** t1.\n\n\n\n"
            "**Instruction:** i1."
        )
        e2 = "## 2026-08-02 \u2014 lrn-00000002\n\n**Trigger:** t2.\n\n**Instruction:** i2."
        e3 = "## 2026-08-03 \u2014 lrn-00000003\n\n**Trigger:** t3.\n\n**Instruction:** i3."
        ref_path.write_text(
            header + "\n" + e1 + "\n\n" + e2 + "\n\n" + e3 + "\n", encoding="utf-8"
        )
        result = compilers.retire_reference(refs_dir, "lrn-00000002")
        assert result.applied is True
        text = ref_path.read_text(encoding="utf-8")
        assert "lrn-00000002" not in text
        # e1's own internal 4-newline gap survives byte-for-byte -- the
        # old global collapse would have shrunk it to exactly "\n\n" here.
        assert "**Trigger:** t1.\n\n\n\n**Instruction:** i1." in text
        assert header + "\n" + e1 + "\n\n" + e3 + "\n" == text


class TestRER6GraduateAndSupersedeRetireReference:
    def test_graduate_retires_reference(self, env2):
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        r1 = verbs.route(env2.home, rid, dest="reference", no_push=True)
        ref_path = r1.compile_result.path
        assert f"— {rid}" in ref_path.read_text(encoding="utf-8")  # positive control

        verbs.graduate(env2.home, rid, no_push=True)
        assert f"— {rid}" not in ref_path.read_text(encoding="utf-8")

    def test_supersede_retires_reference(self, env2):
        old_id, new_id = "lrn-0000bbbb", "lrn-0000cccc"
        create_record(env2.home, make_behavior(record_id=old_id, scope="skill:a"))
        write_proposal(env2.home, old_id, proposal_dict(scope="skill:a"))
        create_record(env2.home, make_behavior(record_id=new_id, scope="skill:a"))
        commit_all(env2.home, "pending")
        r1 = verbs.route(env2.home, old_id, dest="reference", no_push=True)
        ref_path = r1.compile_result.path
        assert f"— {old_id}" in ref_path.read_text(encoding="utf-8")  # positive control

        verbs.supersede(env2.home, old_id, new_id, no_push=True)
        assert f"— {old_id}" not in ref_path.read_text(encoding="utf-8")


class TestRER7ReferenceRetirementWritesCompileRecord:
    def test_reference_retirement_writes_compile_record(self, env2):
        import hashlib

        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        r1 = verbs.route(env2.home, rid, dest="reference", no_push=True)
        ref_path = r1.compile_result.path

        verbs.graduate(env2.home, rid, no_push=True)
        post_removal_bytes = ref_path.read_bytes()
        post_removal_sha = hashlib.sha256(post_removal_bytes).hexdigest()

        compiled_dir = env2.home / "compiled"
        matches = []
        for f in compiled_dir.glob("*.yaml"):
            text = f.read_text(encoding="utf-8")
            if "region: reference" in text and post_removal_sha in text:
                matches.append(f)
        assert matches, (
            "no compiled/<slug>.yaml entry carries the post-removal "
            f"sha256 {post_removal_sha}"
        )


# ================================================================== HOST


class TestHOST1RemoveRefusesWithRoutedRecords:
    def test_host_remove_refuses_with_routed_records(self, env2):
        host_c = env2.home.parent / "repos" / "host-c"
        init_repo(host_c)
        (host_c / "README.md").write_text("c\n", encoding="utf-8")
        commit_all(host_c, "seed")
        host_add(env2.home, host_c, "project")

        for i in range(4):
            rid = f"lrn-c000000{i}"
            create_record(env2.home, make_behavior(record_id=rid, scope="project"), project_path=host_c)
            commit_all(env2.home, f"pending {rid}")
            verbs.route(env2.home, rid, dest="claude-md", no_push=True)
        for i in range(2):
            rid = f"lrn-c100000{i}"
            create_record(env2.home, make_behavior(record_id=rid, scope="project"), project_path=host_c)
        commit_all(env2.home, "pending records")

        # positive control: records_targeting itself finds the 4 routed ids
        # (never the 2 pending ones -- HOST1's own M48 discriminator).
        ids = records_targeting(env2.home, host_c)
        assert set(ids) == {f"lrn-c000000{i}" for i in range(4)}

        from self_learn import hosts as hosts_mod

        before = hosts_mod.load_hosts(env2.home)
        from self_learn.hosts import host_remove

        with pytest.raises(HostRemoveRefused) as exc_info:
            host_remove(env2.home, host_c)
        message = str(exc_info.value)
        assert "4 routed record(s)" in message
        assert all(f"lrn-c000000{i}" in message for i in range(4))
        assert "--gate-only" in message
        assert "rehome" in message
        after = hosts_mod.load_hosts(env2.home)
        assert set(after.projects) == set(before.projects)

    def test_host_pending_only_removes_cleanly(self, env2):
        """The property M48 breaks: a host with only PENDING records (no
        routed ones) still deregisters with no flag at all -- pending
        records compile into nothing."""
        from self_learn.hosts import host_remove

        host_d = env2.home.parent / "repos" / "host-d"
        init_repo(host_d)
        (host_d / "README.md").write_text("d\n", encoding="utf-8")
        commit_all(host_d, "seed")
        host_add(env2.home, host_d, "project")
        for i in range(2):
            rid = f"lrn-d000000{i}"
            create_record(env2.home, make_behavior(record_id=rid, scope="project"), project_path=host_d)
        commit_all(env2.home, "pending records d")

        assert records_targeting(env2.home, host_d) == []
        registry = host_remove(env2.home, host_d)
        assert host_d not in set(registry.projects)


class TestHOST2GateOnlyResidual:
    def test_host_remove_gate_only(self, env2, capsys):
        from self_learn.hosts import host_remove

        host_c = env2.home.parent / "repos" / "host-c"
        init_repo(host_c)
        (host_c / "README.md").write_text("c\n", encoding="utf-8")
        commit_all(host_c, "seed")
        host_add(env2.home, host_c, "project")
        rid = "lrn-c0000001"
        create_record(env2.home, make_behavior(record_id=rid, scope="project"), project_path=host_c)
        commit_all(env2.home, "pending")
        verbs.route(env2.home, rid, dest="claude-md", no_push=True)

        # drive it through the CLI end-to-end (SELF_LEARN_HOME already
        # set by the env2 fixture's monkeypatch).
        rc = cli.main(["host", "remove", str(host_c), "--gate-only"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "1 routed record(s)" in out
        assert "recompile" in out
        assert "WARN" in out or "unmanaged" in out

        # the recompile side actually emits the WARN line this promises.
        result = verbs.recompile(env2.home, no_push=True)
        assert any(
            "host not registered" in w and rid in w for w in result.warnings
        )


class TestHOST3NoBulkRetirement:
    def test_host_remove_help_offers_only_gate_only(self, capsys):
        # in-process, against the REAL argparse parser -- the same
        # object `self-learn host remove --help` builds its usage text
        # from, so this never drifts from the console-script's own
        # output regardless of whether that script is on PATH here.
        with pytest.raises(SystemExit) as exc_info:
            cli._build_parser().parse_args(["host", "remove", "--help"])
        assert exc_info.value.code == 0
        help_text = capsys.readouterr().out
        assert "--gate-only" in help_text
        assert "--retire" not in help_text
        assert "--force" not in help_text

    def test_hosts_py_never_calls_graduate_or_supersede(self):
        r"""HOST3's leg. The spec's own literal command (§7,
        `grep -c 'graduate\|supersede' cli/src/self_learn/hosts.py` = 0)
        is a SELF-MATCHING search: MEASURED, it returns 2, both hits
        landing inside `host_remove`'s own docstring -- prose EXPLAINING
        why no bulk retirement exists ("`graduate` ("canon already
        covers it") and `supersede` ("another record replaces it")
        are both FALSE statements...") legitimately contains both bare
        words, with no call anywhere near them. Asserted here as its
        own positive control, so a future docstring edit that happens
        to remove those two words cannot silently turn this into a
        vacuous check without the control itself going red first.

        gate r2 m-1: a NARROWED grep (`\bgraduate\(|\bsupersede\(`,
        an open-paren after a word boundary) still stops the FALSE-GREEN
        direction (a real call never satisfies it into passing) but is
        measurably NOT prose-immune the other way -- a `hosts.py`
        docstring containing the literal text `graduate(record)` (no
        call anywhere) makes that pattern match too, turning a harmless
        prose edit into a false red. Any TEXT pattern over the file's
        bytes has this failure mode by construction; the fix this unit
        already uses elsewhere for exactly this problem
        (`test_route_observability.py`'s own words: "AST, not regex -- a
        docstring naming `set_routing()` must not turn this red") is to
        stop reading bytes and read the parse tree: a docstring is a
        `Constant` string node, never an `ast.Call`, so no prose --
        forbidden words, real code quoted in a comment, anything -- can
        ever satisfy or defeat this leg either way. That is the claim
        the docstring makes now, and unlike the grep it is true."""
        hosts_py = (
            REPO_ROOT / "plugins" / "self-learn" / "cli" / "src" / "self_learn" / "hosts.py"
        )
        literal = subprocess.run(
            ["grep", "-c", r"graduate\|supersede", str(hosts_py)],
            capture_output=True, text=True,
        )
        literal_count = int(literal.stdout.strip() or "0")
        assert literal_count == 2, (
            "positive control: the spec's own literal pattern is EXPECTED "
            "to self-match host_remove's docstring prose right now -- if "
            f"this is no longer {2}, re-measure before touching the "
            "AST check below"
        )

        tree = ast.parse(hosts_py.read_text(encoding="utf-8"), filename=str(hosts_py))
        # gate r2 fold, pyright re-measure: a plain set-comprehension
        # calling `_call_name` twice (once in the value, once in the
        # `in` guard) left `called` typed `set[str | None]` -- `_call_name`
        # returns `str | None`, and pyright cannot narrow a value it never
        # bound to a name. Bind it once and narrow through the `in` check
        # instead -- same runtime set, `set[str]`.
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in ("graduate", "supersede"):
                    called.add(name)
        assert called == set(), (
            f"hosts.py CALLS {sorted(called)} -- HOST3 forbids bulk "
            "retirement through host-side code, not just its own prose"
        )

    def test_hosts_py_graduate_call_reddens_the_ast_leg(self, tmp_path, monkeypatch):
        """gate r2 m-1's own positive control for the AST leg itself,
        matching M50's spirit but proving the NEW check (not the grep)
        is what fires: a docstring-only occurrence of `graduate(record)`
        must NOT redden the AST leg (prose is inert to it), while an
        ACTUAL call parses as a real `ast.Call` and does."""
        src_with_prose_only = (
            'def host_remove():\n'
            '    """Explains why not: calling graduate(record) here '
            'would be bulk retirement."""\n'
            '    pass\n'
        )
        tree = ast.parse(src_with_prose_only)
        called = {
            _call_name(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node.func) in ("graduate", "supersede")
        }
        assert called == set(), "a docstring mentioning the call must stay clean"

        src_with_real_call = (
            'def host_remove():\n'
            '    for r in targets:\n'
            '        graduate(r)\n'
        )
        tree2 = ast.parse(src_with_real_call)
        called2 = {
            _call_name(node.func)
            for node in ast.walk(tree2)
            if isinstance(node, ast.Call)
            and _call_name(node.func) in ("graduate", "supersede")
        }
        assert called2 == {"graduate"}


class TestHOST4BucketPrune:
    def test_bucket_prune(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
        sb = make_env(tmp_path, skills=("keep", "doomed"))
        monkeypatch.setenv("SELF_LEARN_HOME", str(sb.ledger))

        # 2 empty project buckets, via rehome moving the only record away.
        empty_hosts = []
        for name in ("empty1", "empty2"):
            host = tmp_path / "repos" / name
            init_repo(host)
            (host / "README.md").write_text(f"{name}\n", encoding="utf-8")
            commit_all(host, "seed")
            host_add(sb.ledger, host, "project")
            rid = f"lrn-{name[0]}000000{name[-1]}"
            create_record(sb.ledger, make_knowledge(record_id=rid, scope="project"), project_path=host)
            commit_all(sb.ledger, f"seed {name}")
            verbs.rehome(sb.ledger, rid, to="user", no_push=True)
            empty_hosts.append(host)

        # 1 empty skill bucket, via rehome to a different skill.
        rid_b = "lrn-b0000001"
        create_record(sb.ledger, make_knowledge(record_id=rid_b, scope="skill:doomed"))
        commit_all(sb.ledger, "seed doomed skill")
        verbs.rehome(sb.ledger, rid_b, to="skill:keep", no_push=True)
        empty_skill = sb.ledger / "skills" / "doomed"

        # 1 non-empty project bucket (never pruned).
        host_full = tmp_path / "repos" / "full"
        init_repo(host_full)
        (host_full / "README.md").write_text("full\n", encoding="utf-8")
        commit_all(host_full, "seed")
        host_add(sb.ledger, host_full, "project")
        rid_full = "lrn-f0000001"
        create_record(sb.ledger, make_knowledge(record_id=rid_full, scope="project"), project_path=host_full)
        commit_all(sb.ledger, "seed full")
        bucket_full = sb.ledger / "projects" / slug_for(host_full)

        # An orphan-proposal bucket -- holds no record but DOES hold a
        # proposal file (M51's own guard): must NOT be pruned.
        host_orphan = tmp_path / "repos" / "orphan"
        init_repo(host_orphan)
        (host_orphan / "README.md").write_text("orphan\n", encoding="utf-8")
        commit_all(host_orphan, "seed")
        host_add(sb.ledger, host_orphan, "project")
        rid_o = "lrn-0a000001"
        create_record(sb.ledger, make_knowledge(record_id=rid_o, scope="project"), project_path=host_orphan)
        write_proposal(sb.ledger, rid_o, proposal_dict(scope="project", destination="claude-md"))
        commit_all(sb.ledger, "seed orphan + proposal")
        bucket_orphan = sb.ledger / "projects" / slug_for(host_orphan)
        (bucket_orphan / "pending" / f"{rid_o}.md").unlink()
        commit_all(sb.ledger, "manual delete leaves an orphan proposal")
        assert (bucket_orphan / "proposals" / f"{rid_o}.yaml").is_file()  # positive control

        user_bucket = sb.ledger / "user"
        assert user_bucket.is_dir()  # positive control -- exists before prune too

        dry = verbs.bucket_prune(sb.ledger, dry_run=True)
        # Minor (code gate r1): BucketPruneResult.pruned is ABSOLUTE, not
        # home-relative (the docstring used to claim the opposite).
        assert all(p.is_absolute() for p in dry.pruned)
        dry_names = {p.name for p in dry.pruned}
        assert dry_names == {slug_for(empty_hosts[0]), slug_for(empty_hosts[1]), "doomed"}
        # --dry-run writes nothing.
        for host in empty_hosts:
            assert (sb.ledger / "projects" / slug_for(host)).is_dir()
        assert empty_skill.is_dir()

        result = verbs.bucket_prune(sb.ledger, no_push=True)
        pruned_names = {p.name for p in result.pruned}
        assert pruned_names == dry_names
        for host in empty_hosts:
            assert not (sb.ledger / "projects" / slug_for(host)).exists()
        assert not empty_skill.exists()
        assert bucket_full.is_dir()
        assert bucket_orphan.is_dir()  # NEVER pruned -- the orphan proposal survives
        assert user_bucket.is_dir()  # NEVER pruned -- the one bucket that always exists


class TestHOST5RecordsTargetingResolvesViaMetaYaml:
    def test_records_targeting_resolves_through_symlink(self, env2, tmp_path):
        host_c = env2.home.parent / "repos" / "host-c"
        init_repo(host_c)
        (host_c / "README.md").write_text("c\n", encoding="utf-8")
        commit_all(host_c, "seed")
        host_add(env2.home, host_c, "project")
        rid = "lrn-c0000001"
        create_record(env2.home, make_behavior(record_id=rid, scope="project"), project_path=host_c)
        commit_all(env2.home, "pending")
        verbs.route(env2.home, rid, dest="claude-md", no_push=True)

        # the host path and the SAME real path reached through a
        # symlink differ byte-for-byte as strings; resolving both sides
        # (never comparing str(path) directly) is what HOST5 pins.
        link = tmp_path / "host-c-link"
        link.symlink_to(host_c)
        assert str(link) != str(host_c)  # positive control -- genuinely different strings

        ids = records_targeting(env2.home, link)
        assert ids == [rid]


# ================================================================== META


class TestMETA1FollowupAdd:
    def test_followup_add(self, env2):
        rid = seed_routed(env2.home, scope="skill:a")
        result = verbs.followup_add(
            env2.home, rid, action="upgrade to strong form",
            unblocks_on="M3", no_push=True,
        )
        assert result.commit_message == f"self-learn: follow-up add {rid}"
        path = find_record_path(env2.home, rid)
        record = Record.from_path(path)
        assert record.routing["follow_up"] == {
            "action": "upgrade to strong form", "unblocks_on": "M3",
        }

    def test_followup_add_malformed_unblocks_on_refuses(self, env2):
        """The shipped validator (records._validate_follow_up) is the
        ONLY gate -- a hand-rolled second check would accept something
        it refuses. `unblocks_on` must be a non-empty string; feeding a
        non-string value is the malformed leg (M-…): if `followup_add`
        stopped calling `_validate_follow_up`, this leg goes green for
        the wrong reason and this assertion catches it."""
        rid = seed_routed(env2.home, scope="skill:a")
        with pytest.raises(verbs.VerbError):
            verbs.followup_add(
                env2.home, rid, action="x", unblocks_on=123, no_push=True  # type: ignore[arg-type]
            )


class TestMETA2FollowupAddRefusesWhenOpen:
    def test_followup_add_refuses_when_open(self, env2):
        rid = seed_routed(env2.home, scope="skill:a")
        verbs.followup_add(env2.home, rid, action="first upgrade", no_push=True)
        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.followup_add(env2.home, rid, action="second upgrade", no_push=True)
        message = str(exc_info.value)
        assert "already has an open follow-up" in message
        assert "first upgrade" in message

        verbs.followup_done(env2.home, rid, no_push=True)
        # succeeds now that the open one is cleared.
        result = verbs.followup_add(env2.home, rid, action="second upgrade", no_push=True)
        assert result.action == "followup-add"


class TestMETA3ReclassifyStatusAsymmetry:
    def _seeded_by_status(self, env2):
        """One behavior record per status (pending/deferred/routed/
        rejected/superseded) -- five distinct records, five distinct
        ids, all skill:a scoped."""
        ids: dict[str, str] = {}

        rid_p = "lrn-50000001"
        create_record(env2.home, make_behavior(record_id=rid_p, scope="skill:a"))
        commit_all(env2.home, "pending seed")
        ids["pending"] = rid_p

        rid_d = "lrn-50000002"
        create_record(env2.home, make_behavior(record_id=rid_d, scope="skill:a"))
        commit_all(env2.home, "deferred seed")
        verbs.defer(env2.home, rid_d, no_push=True)
        ids["deferred"] = rid_d

        rid_routed = seed_routed(env2.home, rid="lrn-50000003", scope="skill:a")
        ids["routed"] = rid_routed

        rid_rej = "lrn-50000004"
        create_record(env2.home, make_behavior(record_id=rid_rej, scope="skill:a"))
        commit_all(env2.home, "rejected seed")
        verbs.reject(env2.home, rid_rej, no_push=True)
        ids["rejected"] = rid_rej

        old_id, new_id = "lrn-50000005", "lrn-50000006"
        create_record(env2.home, make_behavior(record_id=old_id, scope="skill:a"))
        create_record(env2.home, make_behavior(record_id=new_id, scope="skill:a"))
        commit_all(env2.home, "supersede seed")
        verbs.supersede(env2.home, old_id, new_id, no_push=True)
        ids["superseded"] = old_id

        return ids

    def test_reclassify_status_asymmetry(self, env2):
        ids = self._seeded_by_status(env2)

        # --kind works in EVERY one of the 5 statuses.
        for status, rid in ids.items():
            result = verbs.reclassify(env2.home, rid, kind="surface-rule", no_push=True)
            assert result.action == "reclassify", status
            path = find_record_path(env2.home, rid)
            record = Record.from_path(path)
            assert record.kind == "surface-rule", status

        # --type is refused OUTSIDE LIVE_STATUSES (pending/deferred),
        # naming 02 §2's freeze; pending/deferred are NOT refused for
        # that reason (they may still fail MET'S own required-section
        # check -- a DIFFERENT message, proving this is a status gate,
        # not a blanket refusal).
        for status, rid in ids.items():
            if status in ("pending", "deferred"):
                try:
                    verbs.reclassify(env2.home, rid, type="knowledge", no_push=True)
                except verbs.VerbError as exc:
                    assert "02 §2" not in str(exc), (status, str(exc))
            else:
                with pytest.raises(verbs.VerbError) as exc_info:
                    verbs.reclassify(env2.home, rid, type="knowledge", no_push=True)
                message = str(exc_info.value)
                assert "02 §2" in message, (status, message)
                assert status in message


class TestMETA4ReclassifyTypeRevalidates:
    def test_reclassify_type_revalidates(self, env2):
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_knowledge(record_id=rid, scope="skill:a"))
        commit_all(env2.home, "pending knowledge")
        before = find_record_path(env2.home, rid).read_bytes()

        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.reclassify(env2.home, rid, type="behavior", no_push=True)
        message = str(exc_info.value)
        # M-3 (code gate r1): names the missing heading through the ONE
        # shipped validator, Record._validate_body -- which reports the
        # FIRST missing required section it finds ("Trigger" precedes
        # "Instruction" in REQUIRED_SECTIONS["behavior"]), not a
        # hand-collected list of every missing one at once. That is the
        # real, single-validator shape; a knowledge record's body (only
        # "## Fact") is missing both, so asserting just the first is
        # what a genuine call to the shipped validator can promise.
        assert "must contain a '## Trigger' section" in message
        # the record is never rewritten to fit.
        after = find_record_path(env2.home, rid).read_bytes()
        assert after == before

    def test_reclassify_type_accepts_a_present_but_empty_section(self, env2):
        """M-3 (code gate r1), disagreement direction 1: present-but-
        EMPTY '## Trigger'/'## Instruction' headings must be ACCEPTED
        -- Record._validate_body counts HEADINGS, not content (the
        verb's own docstring: "the body is never rewritten to fit" --
        content is never this verb's business). The retired hand-rolled
        check refused this. `--type behavior` on an already-behavior
        record still runs the SAME pre-lock section check any `--type`
        call runs; paired with a REAL `--kind` change (kind and type
        both stay "behavior" throughout, so the unrelated set_kind-
        before-set_type ordering constraint elsewhere in this verb
        never triggers) so the write is not a no-op git refuses to
        commit."""
        rid = "lrn-0000bbbb"
        record = make_behavior(record_id=rid, scope="skill:a")
        record.set_body("## Trigger\n\n## Instruction\n")
        create_record(env2.home, record)
        commit_all(env2.home, "pending behavior, empty trigger/instruction")

        result = verbs.reclassify(
            env2.home, rid, type="behavior", kind="surface-rule", no_push=True
        )
        assert result.action == "reclassify"
        after = Record.from_path(find_record_path(env2.home, rid))
        assert after.type == "behavior"
        assert after.kind == "surface-rule"

    def test_reclassify_type_refuses_a_duplicate_heading_pre_lock(self, env2):
        """M-3 (code gate r1), disagreement direction 2: a DUPLICATE
        '## Fact' heading must refuse BEFORE any lock/mutation, once
        the reclassify TARGET (knowledge) requires it -- the retired
        hand-rolled check (a dict-shaped `_body_sections`) could not
        represent a count > 1 at all, so it silently passed a duplicate
        through pre-lock, only for `set_type`'s OWN `_validate_body`
        call to catch it later, under the lock. Source type is behavior
        (Trigger/Instruction unique -- valid at creation on its own
        terms); '## Fact' rides along duplicated, unchecked by
        behavior's own validation (Fact is neither required nor
        optional for behavior), and only starts mattering once the
        reclassify TARGET (knowledge) is checked.

        gate r2 m-6: this docstring used to claim the duplicate
        "surfaced only later, under the lock, when set_type's OWN
        _validate_body call caught it for real" -- measured FALSE even
        before B-1's fix (deleting the pre-lock check made the mutated
        code hit `set_kind`-before-`set_type`'s ordering bug and refuse
        with "clear kind first", never reaching `_validate_body` at
        all). After B-1's fix the true account is simpler and does not
        depend on that bug: `reclassify` now validates the duplicate in
        TWO places on the SAME pre-lock path -- the early
        `records_mod.validate_body(type, record.body)` call above, and
        (redundantly, on purpose) `_reclassify_apply`'s own
        `set_type(...)` call inside the pre-lock simulation just below
        it -- so the duplicate is refused before any lock or write
        EITHER WAY, never surfacing under the lock. MU12 (delete the
        early check only) does NOT silence this test -- MEASURED
        (not hand-traced): re-run with just the early check disabled
        still gives `1 passed` -- the simulation's own `set_type`
        call catches the duplicate instead, through the identical
        validator, before the lock opens.
        """
        rid = "lrn-0000cccc"
        record = make_behavior(record_id=rid, scope="skill:a")
        record.set_body(
            "## Trigger\nt1.\n\n## Instruction\ni1.\n\n## Fact\nf1.\n\n## Fact\nf2."
        )
        create_record(env2.home, record)
        commit_all(env2.home, "pending behavior, duplicate Fact")
        before = find_record_path(env2.home, rid).read_bytes()

        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.reclassify(env2.home, rid, type="knowledge", no_push=True)
        assert "duplicate" in str(exc_info.value)
        after = find_record_path(env2.home, rid).read_bytes()
        assert after == before


class TestB1ReclassifyResultingPairValidated:
    """gate r2 B-1 (Blocker) regression coverage: `reclassify` never
    checked that the RESULTING `(type, kind)` pair was one
    `Record.validate()` would accept -- only the incoming flags in
    isolation. One omission, three faces (all fixed by
    `verbs._reclassify_apply` + the pre-lock simulate-and-validate
    step): (1) `--type behavior` with no kind, given or existing, used
    to commit a `kind: null` behavior record `Record.from_path` then
    refused to load; (2) a legal `--type behavior --kind X` on a
    non-behavior record was refused though the verb's own pre-lock
    guard had just admitted it (the `set_kind`-before-`set_type`
    ordering bug); (3) `--type knowledge` on ANY kinded behavior record
    was unconditionally unreachable through the CLI (no way to clear
    `kind` -- `--kind` uses `choices=sorted(KINDS)`)."""

    def test_face1_type_behavior_with_no_kind_refuses_before_writing(self, env2):
        """Face 1 -- B-1's exact corruption scenario, now refused
        instead of committed. A knowledge record hand-edited to carry
        Trigger/Instruction (exactly what META4's own refusal message
        instructs: "edit it by hand first"), no kind anywhere."""
        rid = "lrn-0000d001"
        record = make_knowledge(record_id=rid, scope="skill:a")
        record.set_body("## Trigger\nt1.\n\n## Instruction\ni1.\n\n## Fact\nf1.")
        create_record(env2.home, record)
        commit_all(env2.home, "pending knowledge, behavior-shaped body")
        before = find_record_path(env2.home, rid).read_bytes()

        with pytest.raises(verbs.VerbError) as exc_info:
            verbs.reclassify(env2.home, rid, type="behavior", no_push=True)
        message = str(exc_info.value)
        assert "kind" in message

        after_path = find_record_path(env2.home, rid)
        assert after_path.read_bytes() == before
        # the record must still be loadable -- the refusal did not
        # commit anything a later verb would choke on.
        reloaded = Record.from_path(after_path)
        assert reloaded.type == "knowledge"

    def test_face2_type_behavior_with_kind_on_nonbehavior_now_succeeds(self, env2):
        """Face 2 -- the ordering bug: `--type behavior --kind X` on a
        knowledge record whose body already satisfies behavior's
        sections used to be refused ("kind applies to behavior records
        only") even though the verb's own pre-lock guard had just
        admitted the combination as legal. Now succeeds, and the
        written record survives a fresh `Record.from_path` (the same
        check B-1's own corruption would have failed)."""
        rid = "lrn-0000d002"
        record = make_knowledge(record_id=rid, scope="skill:a")
        record.set_body("## Trigger\nt1.\n\n## Instruction\ni1.\n\n## Fact\nf1.")
        create_record(env2.home, record)
        commit_all(env2.home, "pending knowledge, behavior-shaped body")

        result = verbs.reclassify(
            env2.home, rid, type="behavior", kind="surface-rule", no_push=True
        )
        assert result.action == "reclassify"
        reloaded = Record.from_path(find_record_path(env2.home, rid))
        assert reloaded.type == "behavior"
        assert reloaded.kind == "surface-rule"

    def test_face3_type_knowledge_clears_kind_and_is_reachable(self, env2):
        """Face 3 -- reachability: `--type knowledge` on a KINDED
        behavior record used to be unconditionally refused ("clear kind
        first (set_kind(None))") with no CLI-level way to satisfy that
        instruction (`--kind` only accepts `records.KINDS` values).
        `_reclassify_apply` auto-clears `kind` as PART OF a type change
        away from behavior -- the only path that makes this transition
        reachable at all -- so this must now succeed, with `kind`
        actually gone from the written record, not merely unchecked."""
        rid = "lrn-0000d003"
        record = make_behavior(record_id=rid, scope="skill:a")  # kind="anti-pattern"
        record.set_body("## Trigger\nt1.\n\n## Instruction\ni1.\n\n## Fact\nf1.")
        create_record(env2.home, record)
        commit_all(env2.home, "pending behavior, knowledge-shaped body too")
        assert record.kind == "anti-pattern"

        result = verbs.reclassify(env2.home, rid, type="knowledge", no_push=True)
        assert result.action == "reclassify"
        reloaded = Record.from_path(find_record_path(env2.home, rid))
        assert reloaded.type == "knowledge"
        assert reloaded.kind is None
        assert "kind" not in reloaded._fm

    def test_face1_end_to_end_through_cli_main(self, env2, capsys):
        """gate r2's own probe ran end to end through `cli.main`, not
        just the verb layer -- this pins the SAME shape there: rc != 0,
        nothing committed, the record still loadable by a later verb
        (`show`) instead of raising an uncaught `ValidationError`."""
        rid = "lrn-0000d004"
        record = make_knowledge(record_id=rid, scope="skill:a")
        record.set_body("## Trigger\nt1.\n\n## Instruction\ni1.\n\n## Fact\nf1.")
        create_record(env2.home, record)
        commit_all(env2.home, "pending knowledge, behavior-shaped body")
        before_log = git(env2.home, "log", "--oneline").stdout

        rc = cli.main(["reclassify", rid, "--type", "behavior", "--no-push"])
        assert rc != 0

        after_log = git(env2.home, "log", "--oneline").stdout
        assert after_log == before_log  # nothing committed

        capsys.readouterr()  # drain the refusal message
        rc_show = cli.main(["show", rid])
        assert rc_show == 0  # never raises -- the record is still sane


class TestMETA5ReclassifyUsage:
    def test_reclassify_usage(self, env2):
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        commit_all(env2.home, "pending")

        with pytest.raises(verbs.VerbUsageError) as exc_info:
            verbs.reclassify(env2.home, rid, no_push=True)
        assert exc_info.value.exit_code == 64

        with pytest.raises(verbs.VerbUsageError) as exc_info:
            verbs.reclassify(env2.home, rid, kind="not-a-real-kind", no_push=True)
        message = str(exc_info.value)
        assert exc_info.value.exit_code == 64
        for kind in sorted(records_mod.KINDS):
            assert kind in message

        with pytest.raises(verbs.VerbUsageError) as exc_info:
            verbs.reclassify(env2.home, rid, type="not-a-real-type", no_push=True)
        message = str(exc_info.value)
        assert exc_info.value.exit_code == 64
        for type_ in sorted(records_mod.TYPES):
            assert type_ in message
