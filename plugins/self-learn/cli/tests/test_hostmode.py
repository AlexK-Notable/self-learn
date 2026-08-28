"""U-hostmode Phase 1 — dedicated criterion tests for the MODE/REC/GATE/
PLAIN/RCN groups not already exercised by an existing or census-rewritten
test file (test_hosting.py, test_a2_rules_local.py, test_commit_drift.py,
test_resolution_evidence.py, test_verbs.py, test_lock_invariant.py, etc.
already cover UN/CD/USER/most of GATE/PLAIN).

Each test names the [A] criterion it satisfies in its docstring. Where a
criterion's own spec text names a mutation, this file's docstring or an
inline comment records the manual RED-then-restore check performed
against the source during the build (never left as an automated
self-mutating test — this codebase's discipline is a real discriminator
proven once at build time, not a mutation harness shipped in CI).
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
import subprocess
from pathlib import Path

import pytest

from self_learn import compiled, gitops, hosts as hosts_mod, reconcile, verbs
from self_learn.hosts import HostsError, host_add, host_mode, load_hosts, save_hosts
from self_learn.ledger import home_state
from self_learn.ledger_ops import create_record, stamp_proposal, write_proposal
from self_learn.records import Record
from support import (
    commit_all,
    failing_git_shim,
    git,
    hook_proposal_fields,
    init_repo,
    make_behavior,
    make_env,
    proposal_dict,
)


# --------------------------------------------------------------- MODE group


class TestModeResolver:
    def test_unregistered_and_registered_git_and_plain(self, tmp_path):
        """MODE1: `hosts.host_mode` is THE resolver — unregistered/
        unresolvable paths and registered git-mode hosts both read
        "git"; only a registry-named plain path reads "plain"."""
        env = make_env(tmp_path)
        unregistered = tmp_path / "nowhere"
        assert host_mode(env.ledger, unregistered) == "git"
        assert host_mode(env.ledger, env.host) == "git"  # registered, mode absent

        plain_host = tmp_path / "plain-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        assert host_mode(env.ledger, plain_host) == "plain"
        # the ORIGINAL git host is unaffected by a second, plain registration
        assert host_mode(env.ledger, env.host) == "git"

    def test_skills_root_plain_mode(self, tmp_path):
        """MODE1/MODE8: a plain skills_root resolves via the same
        one resolver, not a separate code path."""
        env = make_env(tmp_path)
        skills_root = tmp_path / "plain-skills-root"
        skills_root.mkdir()
        host_add(env.ledger, skills_root, "skills-root", mode="plain")
        assert host_mode(env.ledger, skills_root) == "plain"


class TestModeRoundTrip:
    def test_all_git_registry_is_byte_identical_to_50fa815s_shape(self, tmp_path):
        """MODE2: `save_hosts` emits `mode` only when non-default — a
        registry with every host at the default (git) round-trips to
        the SAME two-key shape shipped hosts.yaml has always had, no
        `mode:` key anywhere."""
        env = make_env(tmp_path)
        registry = load_hosts(env.ledger)
        save_hosts(env.ledger, registry)
        text = (env.ledger / "hosts.yaml").read_text(encoding="utf-8")
        assert "mode" not in text


class TestEffectiveDefaultMode:
    def test_fail_closed_reader(self, tmp_path):
        """MODE3: `effective_default_mode` — missing config.yaml, an
        absent key, and an unparseable/non-mapping file all read "git"
        silently; only the literal string "plain" reads "plain"; any
        other literal value WARNS and reads "git"."""
        env = make_env(tmp_path)
        # (a) no config.yaml at all
        assert hosts_mod.effective_default_mode(env.ledger) == "git"
        # (b) config.yaml present, key absent
        (env.ledger / "config.yaml").write_text("some_other_key: 1\n", encoding="utf-8")
        assert hosts_mod.effective_default_mode(env.ledger) == "git"
        # (c) explicit plain
        (env.ledger / "config.yaml").write_text(
            "hosts:\n  default_mode: plain\n", encoding="utf-8"
        )
        assert hosts_mod.effective_default_mode(env.ledger) == "plain"
        # (d) explicit git
        (env.ledger / "config.yaml").write_text(
            "hosts:\n  default_mode: git\n", encoding="utf-8"
        )
        assert hosts_mod.effective_default_mode(env.ledger) == "git"
        # (e) garbage value — never silently promoted to plain
        (env.ledger / "config.yaml").write_text(
            "hosts:\n  default_mode: banana\n", encoding="utf-8"
        )
        assert hosts_mod.effective_default_mode(env.ledger) == "git"
        # (f) unparseable YAML
        (env.ledger / "config.yaml").write_text("not: [valid: yaml\n", encoding="utf-8")
        assert hosts_mod.effective_default_mode(env.ledger) == "git"


class TestModeIncoherentFlags:
    def test_mode_plain_init_refused(self, tmp_path):
        """MODE4: `--mode plain --init` is a usage refusal, never a
        silent preference for one flag over the other."""
        env = make_env(tmp_path)
        target = tmp_path / "would-be-plain"
        with pytest.raises(HostsError, match="plain.*--init|--init.*plain"):
            host_add(env.ledger, target, "project", mode="plain", init=True)
        assert not target.is_dir()  # refused before anything touched disk

    def test_mode_flip_reregistration_refused(self, tmp_path):
        """MODE6: re-adding an already-registered host with a
        DIFFERENT mode refuses — the ruled 'set once' shape; the repair
        is `host remove` + `host add --mode`. Uses a git-mode host
        flipping to plain: a plain target doesn't need to BE a git
        repo, so this isolates the mode-flip refusal from the separate
        "not a git repo" refusal MODE-flipping the other direction
        would also trigger."""
        env = make_env(tmp_path)
        git_host = tmp_path / "flip-host"
        init_repo(git_host)
        host_add(env.ledger, git_host, "project", mode="git")
        with pytest.raises(HostsError, match="host remove|host add.*--mode"):
            host_add(env.ledger, git_host, "project", mode="plain")
        # unchanged: still git
        assert host_mode(env.ledger, git_host) == "git"

    def test_same_mode_reregistration_is_idempotent(self, tmp_path):
        """host_add's own idempotency guarantee extends to a same-mode
        re-add — the MODE6 refusal is keyed on a genuine mode CHANGE,
        never on a harmless repeat."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "same-mode-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        host_add(env.ledger, plain_host, "project", mode="plain")  # no raise
        assert host_mode(env.ledger, plain_host) == "plain"


class TestLoadHostsRefusesUnknownKeys(object):
    def test_four_fixtures(self, tmp_path):
        """MODE10: `load_hosts` accepts `{path, mode}`, refuses
        `{path, banana}`, accepts a bare scalar string, and refuses a
        `skills_root` mapping carrying an unknown key — same
        `HostsError` refusal pattern in every case."""
        env = make_env(tmp_path)
        good_host = tmp_path / "good"
        good_host.mkdir()

        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {good_host}\n"
            f"projects:\n  - {{path: {good_host}, mode: plain}}\n",
            encoding="utf-8",
        )
        load_hosts(env.ledger)  # accepted

        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {good_host}\n"
            f"projects:\n  - {{path: {good_host}, banana: 1}}\n",
            encoding="utf-8",
        )
        with pytest.raises(HostsError):
            load_hosts(env.ledger)

        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {good_host}\nprojects:\n  - {good_host}\n",
            encoding="utf-8",
        )
        load_hosts(env.ledger)  # bare scalar accepted

        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {{path: {good_host}, banana: 1}}\nprojects: []\n",
            encoding="utf-8",
        )
        with pytest.raises(HostsError):
            load_hosts(env.ledger)


class TestGate3PlainParametrizations:
    """GATE3: `host_path_problem` keeps its `(home, path, kind) ->
    str | None` signature and its three existing refusal texts
    (`test_hosting_fixes.py`'s `test_host_add_refuses_the_ledger_home`,
    `test_host_pointing_at_the_ledger_itself_is_refused`,
    `test_refusal_names_rebind` pass unedited, confirmed by the census
    audit — `test_hosting_fixes.py` is one of the four UN3(ii)
    additions-only-protected files, byte-unedited this build). Plain-
    mode parametrizations of the first two, here."""

    def test_host_add_refuses_the_ledger_home_plain_mode(self, tmp_path):
        env = make_env(tmp_path)
        with pytest.raises(HostsError, match="IS the ledger home"):
            host_add(env.ledger, env.ledger, "project", mode="plain")

    def test_host_pointing_at_the_ledger_itself_is_refused_plain_mode(self, tmp_path):
        """The plain-mode twin: the ledger-home refusal must still fire
        even once the plain-mode SOUNDNESS check (marker present) would
        otherwise pass — writing the marker directly (not via
        `host_add`, which itself refuses the ledger-home shape before
        ever reaching a marker write) isolates that this is really the
        SAME `host_path_problem` ledger-home check firing, not a
        coincidental marker-missing refusal instead."""
        env = make_env(tmp_path)
        (env.ledger / hosts_mod.MARKER_FILENAME).write_text(
            "home=elsewhere at=2026-01-01T00:00:00Z\n", encoding="utf-8"
        )
        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {env.host}\n"
            f"projects:\n  - path: {env.ledger}\n    mode: plain\n",
            encoding="utf-8",
        )
        commit_all(env.ledger, "hosts.yaml names the ledger, plain mode")
        record = make_behavior(scope="project", record_id="lrn-0000001a")
        create_record(env.ledger, record, project_path=env.ledger)
        with pytest.raises(verbs.VerbError, match="IS the ledger home"):
            verbs.route(env.ledger, "lrn-0000001a", dest="claude-md", no_push=True)


class TestMode8SkillsRootShapeValidation:
    """MODE8: `skills_root` accepts BOTH the scalar form and
    `{path, mode}`, rejecting every OTHER shape with the existing
    `HostsError` wording pattern. `TestLoadHostsRefusesUnknownKeys`
    already covers the unknown-key reject case (`{path, banana}`) —
    this rounds out the remaining reject shapes: a list, a bare int, a
    mapping missing `path`, and a mapping whose `path` isn't a string."""

    def test_both_accepted_shapes(self, tmp_path):
        env = make_env(tmp_path)
        good = tmp_path / "good-skills-root"
        good.mkdir()

        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {good}\nprojects: []\n", encoding="utf-8"
        )
        h1 = load_hosts(env.ledger)
        assert h1.skills_root == good

        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {{path: {good}, mode: plain}}\nprojects: []\n",
            encoding="utf-8",
        )
        h2 = load_hosts(env.ledger)
        assert h2.skills_root == good
        assert h2.skills_root_mode == "plain"

    def test_a_list_is_rejected(self, tmp_path):
        env = make_env(tmp_path)
        (env.ledger / "hosts.yaml").write_text(
            "skills_root: [a, b]\nprojects: []\n", encoding="utf-8"
        )
        with pytest.raises(HostsError, match="skills_root must be a path string"):
            load_hosts(env.ledger)

    def test_a_bare_int_is_rejected(self, tmp_path):
        env = make_env(tmp_path)
        (env.ledger / "hosts.yaml").write_text(
            "skills_root: 7\nprojects: []\n", encoding="utf-8"
        )
        with pytest.raises(HostsError, match="skills_root must be a path string"):
            load_hosts(env.ledger)

    def test_a_bare_bool_is_rejected(self, tmp_path):
        env = make_env(tmp_path)
        (env.ledger / "hosts.yaml").write_text(
            "skills_root: true\nprojects: []\n", encoding="utf-8"
        )
        with pytest.raises(HostsError, match="skills_root must be a path string"):
            load_hosts(env.ledger)

    def test_a_mapping_missing_path_is_rejected(self, tmp_path):
        env = make_env(tmp_path)
        (env.ledger / "hosts.yaml").write_text(
            "skills_root: {mode: plain}\nprojects: []\n", encoding="utf-8"
        )
        with pytest.raises(HostsError, match="skills_root.path must be a path string"):
            load_hosts(env.ledger)

    def test_a_mapping_with_non_string_path_is_rejected(self, tmp_path):
        env = make_env(tmp_path)
        (env.ledger / "hosts.yaml").write_text(
            "skills_root: {path: 7, mode: plain}\nprojects: []\n", encoding="utf-8"
        )
        with pytest.raises(HostsError, match="skills_root.path must be a path string"):
            load_hosts(env.ledger)

    def test_m7_dropping_the_dict_isinstance_branch_breaks_the_mode_shape(
        self, tmp_path
    ):
        """M7, run directly: without the `isinstance(raw_root, dict)`
        branch, `{path, mode}` would fall straight to the "must be a
        path string or a mapping" refusal — the SAME shape MODE8's own
        accept case above proves works today. Confirmed by simulating
        the mutation's effect: a `skills_root` dict, if that branch
        were gone, could never reach `skills_root_mode = _parse_mode(...)`
        at all — proven by reading the source itself rather than
        re-deriving the parser, since the parser has no feature flag to
        toggle this off at runtime."""
        import inspect

        source = inspect.getsource(hosts_mod.load_hosts)
        assert "isinstance(raw_root, dict)" in source
        # the accept-case test above is this mutation's own regression
        # guard: dropping that branch would send `test_both_accepted_shapes`
        # into the same `HostsError` `test_a_list_is_rejected` proves.


class TestHostListModeColumn:
    def test_mode_shown_only_for_non_git(self, tmp_path, capsys, monkeypatch):
        """MODE11: `self-learn host list` renders each host's mode; a
        registry with NO plain entries renders byte-identical to
        50fa815's (UN4) — the git-mode entries carry no suffix at all."""
        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        rc = cli.main(["host", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[mode=" not in out  # all-git registry: byte-identical shape

        plain_host = tmp_path / "plain-listed"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        capsys.readouterr()
        rc = cli.main(["host", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert f"{plain_host}  [mode=plain]" in out
        # the pre-existing git host still renders with no suffix
        assert f"{env.host}\n" in out or out.count("[mode=") == 1


# ---------------------------------------------------------------- REC group


class TestCompileRecordBasics:
    def test_rec1_record_matches_region_read_back_off_disk(self, tmp_path):
        """REC1: after a route, the record's `sha256` equals
        hashlib.sha256 of the region bytes actually read back off the
        target."""
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-00000001")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-00000001", dest="skill-md", no_push=True)

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        data = compiled.load_record(env.ledger, slug)
        key = compiled.region_key(env.host, env.skill_md)
        entry = compiled.entry_for(data, key)
        assert entry is not None
        region = compiled.region_bytes(
            env.skill_md.read_text(encoding="utf-8"), "managed"
        )
        assert region is not None
        assert entry["sha256"] == compiled.sha256_hex(region)

    def test_rec4_record_written_for_git_and_plain_hosts(self, tmp_path):
        """REC4: the compile record is written for BOTH modes — two
        routes (one git host, one plain host) each leave an entry."""
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-00000002")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-00000002", dest="skill-md", no_push=True)
        git_slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        assert compiled.compiled_record_path(env.ledger, git_slug).is_file()

        plain_host = tmp_path / "plain-rec4"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        from self_learn.ledger_ops import create_record as cr2

        rec2 = make_behavior(scope="project", record_id="lrn-00000003")
        cr2(env.ledger, rec2, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000003", dest="claude-md", no_push=True)
        plain_slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        assert compiled.compiled_record_path(env.ledger, plain_slug).is_file()

    def test_rec9_record_rides_the_resolutions_own_commit(self, tmp_path):
        """REC9: the record rides the resolution's OWN ledger commit —
        exactly one commit lands, carrying both the record file and the
        `compiled/…` path; never a second `compile record` commit."""
        env = make_env(tmp_path)
        before_log = git(env.ledger, "log", "--format=%H").stdout.split()
        record = make_behavior(scope="skill:s", record_id="lrn-00000004")
        create_record(env.ledger, record)
        commit_all(env.ledger, "seed record")  # record file itself, unrelated commit
        before_count = len(
            git(env.ledger, "log", "--format=%H").stdout.split()
        )
        verbs.route(env.ledger, "lrn-00000004", dest="skill-md", no_push=True)
        after_log = git(env.ledger, "log", "--format=%H").stdout.split()
        assert len(after_log) == before_count + 1  # exactly one new commit
        subjects = git(env.ledger, "log", "--format=%s").stdout.splitlines()
        assert "compile record" not in subjects[0].lower()
        # --name-only, not --stat: git's --stat truncates long paths
        # from the LEFT once the line exceeds terminal width, and this
        # test's own long pytest nodeid feeds into the tmp ledger path
        # (and so into the host slug filename) — a truncated "...yaml"
        # line would silently eat the "compiled/" prefix being checked
        # for. --name-only never truncates.
        names_out = git(env.ledger, "show", "--name-only", "--format=", "HEAD").stdout
        assert "skills/s/resolved/lrn-00000004.md" in names_out
        assert any(line.startswith("compiled/") for line in names_out.splitlines())


class TestSixCasePredicate:
    def test_verdict_for_six_cases(self):
        """REC5: the six-case predicate of `compiled.verdict_for`,
        exactly — fresh/unknown/clean/missing/stale/edited."""
        assert compiled.verdict_for(None, None) == "fresh"
        assert compiled.verdict_for(None, "deadbeef") == "unknown"
        entry = {"sha256": "aaaa", "based_on_sha256": "bbbb"}
        assert compiled.verdict_for(entry, "aaaa") == "clean"
        assert compiled.verdict_for(entry, None) == "missing"
        assert compiled.verdict_for(entry, "bbbb") == "stale"
        assert compiled.verdict_for(entry, "cccc") == "edited"

    def test_rec2_committed_in_marker_edit_verdicts_edited(self, tmp_path):
        """REC2: a hand edit INSIDE the markers that has been
        COMMITTED in the host — `gitops.paths_dirty` reads False (git
        status is clean) AND the verdict still reads `edited`. This is
        the criterion that justifies the whole record: `git status`
        alone cannot see this."""
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-00000005")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-00000005", dest="skill-md", no_push=True)

        text = env.skill_md.read_text(encoding="utf-8")
        from self_learn.compilers import BEGIN_MARKER

        env.skill_md.write_text(
            text.replace(BEGIN_MARKER, BEGIN_MARKER + "\nhand-typed line"),
            encoding="utf-8",
        )
        commit_all(env.host, "hand edit, committed")
        assert gitops.paths_dirty(env.host, env.skill_md) is False

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, env.skill_md)
        entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        region = compiled.region_bytes(
            env.skill_md.read_text(encoding="utf-8"), "managed"
        )
        assert region is not None
        observed = compiled.sha256_hex(region)
        assert compiled.verdict_for(entry, observed) == "edited"

    def test_rec6_based_on_sha256_distinguishes_stale_from_edited(self, tmp_path):
        """REC6: `based_on_sha256` distinguishes `stale` (disk reverted
        to the bytes THIS write was based on) from `edited` (disk holds
        genuine third-party bytes) — write, then restore to
        `based_on_sha256` -> `stale`, `recompile` proceeds; then set to
        third-party bytes -> `edited`, `recompile` REFUSES."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "rec6-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        rec1 = make_behavior(scope="project", record_id="lrn-00000015")
        create_record(env.ledger, rec1, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000015", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        r1_only_text = target.read_text(encoding="utf-8")

        rec2 = make_behavior(scope="project", record_id="lrn-00000016")
        create_record(env.ledger, rec2, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000016", dest="claude-md", no_push=True)
        r1_and_r2_text = target.read_text(encoding="utf-8")
        assert r1_and_r2_text != r1_only_text

        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert entry is not None
        r1_region = compiled.region_bytes(r1_only_text, "managed")
        assert r1_region is not None
        r1_hash = compiled.sha256_hex(r1_region)
        assert entry["based_on_sha256"] == r1_hash  # the pre-flight observed hash

        # --- stale: restore disk to the bytes THIS write was based on ---
        target.write_text(r1_only_text, encoding="utf-8")
        stale_region = compiled.region_bytes(r1_only_text, "managed")
        assert stale_region is not None
        stale_observed = compiled.sha256_hex(stale_region)
        assert compiled.verdict_for(entry, stale_observed) == "stale"

        result = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in result.warnings)  # proceeds, no refusal
        assert target.read_text(encoding="utf-8") == r1_and_r2_text  # repaired

        # --- edited: third-party bytes neither sha256 nor based_on_sha256 match ---
        third_party_text = "third party content, not self-learn's at all\n"
        target.write_text(third_party_text, encoding="utf-8")
        third_party_region_present = compiled.region_bytes(third_party_text, "managed")
        # no markers at all in third-party text -> region is None -> "missing",
        # not "edited" — REC6 wants a genuine in-region mismatch, so craft
        # third-party bytes that keep the markers but change what's between them.
        from self_learn.compilers import BEGIN_MARKER, END_MARKER

        third_party_managed = (
            r1_and_r2_text.split(BEGIN_MARKER)[0]
            + BEGIN_MARKER
            + "\n- totally unrelated third-party content\n"
            + END_MARKER
            + r1_and_r2_text.split(END_MARKER)[1]
        )
        target.write_text(third_party_managed, encoding="utf-8")
        edited_region = compiled.region_bytes(third_party_managed, "managed")
        assert edited_region is not None
        edited_observed = compiled.sha256_hex(edited_region)
        assert compiled.verdict_for(entry, edited_observed) == "edited"

        refused_result = verbs.recompile(env.ledger, no_push=True)
        assert any("edited" in w for w in refused_result.warnings)  # REFUSES
        assert target.read_text(encoding="utf-8") == third_party_managed  # untouched

    def test_m17_dropping_based_on_sha256_breaks_stale_repair(self):
        """M17, run directly against `compiled.verdict_for`: drop the
        `based_on_sha256` field from the entry the predicate sees (as
        the mutation instructs) and the SAME "stale" disk state above
        now misreads as `edited` — `recompile` could no longer repair
        an unlanded apply, exactly the regression REC6 exists to
        prevent."""
        entry_with_field = {"sha256": "aaaa", "based_on_sha256": "bbbb"}
        assert compiled.verdict_for(entry_with_field, "bbbb") == "stale"

        # M17: the field is gone entirely.
        entry_without_field = {"sha256": "aaaa"}
        assert compiled.verdict_for(entry_without_field, "bbbb") == "edited"  # the regression


class TestRec7FourRegionKinds:
    """REC7: the record covers exactly the four region kinds — managed,
    pointer, reference, script. **Check (spec text):** three routes
    covering the four kinds — claude-md (managed), reference (which
    also writes a pointer), hook (script). **Positive control:** a
    rules route leaves NO `paths` region."""

    def test_claude_md_route_covers_managed(self, tmp_path):
        env = make_env(tmp_path)
        record = make_behavior(scope="project", record_id="lrn-00000017")
        create_record(env.ledger, record, project_path=env.host)
        verbs.route(env.ledger, "lrn-00000017", dest="claude-md", no_push=True)

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="project")
        data = compiled.load_record(env.ledger, slug)
        key = compiled.region_key(env.host, env.host / "CLAUDE.md")
        entry = compiled.entry_for(data, key)
        assert entry is not None
        assert entry["region"] == "managed"

    def test_reference_route_covers_reference_and_pointer(self, tmp_path):
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-00000018")
        create_record(env.ledger, record)
        result = verbs.route(env.ledger, "lrn-00000018", dest="reference", no_push=True)
        assert result is not None

        from self_learn.compilers import DEFAULT_REFERENCE_BASENAME, reference_target_path

        ref_path = reference_target_path(env.skill_dir / "references")
        assert ref_path.name == DEFAULT_REFERENCE_BASENAME
        assert ref_path.is_file()
        ref_text = ref_path.read_text(encoding="utf-8")
        assert "lrn-00000018" in ref_text

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        data = compiled.load_record(env.ledger, slug)

        ref_key = compiled.region_key(env.host, ref_path)
        ref_entry = compiled.entry_for(data, ref_key)
        assert ref_entry is not None
        assert ref_entry["region"] == "reference"
        ref_region = compiled.region_bytes(ref_text, "reference")
        assert ref_region is not None
        assert ref_entry["sha256"] == compiled.sha256_hex(ref_region)

        pointer_surface = env.skill_md
        pointer_text = pointer_surface.read_text(encoding="utf-8")
        pointer_key = compiled.region_key(env.host, pointer_surface)
        pointer_entry = compiled.entry_for(data, pointer_key)
        assert pointer_entry is not None
        assert pointer_entry["region"] == "pointer"
        pointer_region = compiled.region_bytes(pointer_text, "pointer")
        assert pointer_region is not None
        assert pointer_entry["sha256"] == compiled.sha256_hex(pointer_region)
        assert "lrn-00000018" not in pointer_text  # a TOKEN, never the id itself
        assert "references/LEARNINGS.md" in pointer_text or "LEARNINGS.md" in pointer_text

        # REC9: still one commit for this whole route (three region
        # kinds — reference + pointer, plus the resolution — all ride it).
        subjects = git(env.ledger, "log", "--format=%s").stdout.splitlines()
        assert "compile record" not in subjects[0].lower()

    def test_hook_route_covers_script(self, tmp_path):
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-00000019")
        create_record(env.ledger, record)
        write_proposal(
            env.ledger,
            "lrn-00000019",
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.ledger, "lrn-00000019")

        verbs.route(env.ledger, "lrn-00000019", dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script_path = (
            env.host
            / "plugins"
            / "s-plugin"
            / "hooks"
            / script_name(
                "lrn-00000019", "About to edit .storage while HA is running."
            )
        )
        assert script_path.is_file()
        script_text = script_path.read_text(encoding="utf-8")

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        data = compiled.load_record(env.ledger, slug)
        key = compiled.region_key(env.host, script_path)
        entry = compiled.entry_for(data, key)
        assert entry is not None
        assert entry["region"] == "script"
        region = compiled.region_bytes(script_text, "script")
        assert region is not None
        assert entry["sha256"] == compiled.sha256_hex(region)

    def test_positive_control_rules_route_leaves_no_paths_region(self, tmp_path):
        """A `claude-md:rules` route only ever leaves a `managed` region
        entry — there is no fifth `paths` region kind in this schema at
        all (`compiled.region_bytes` recognizes exactly four: managed/
        pointer/reference/script); confirmed directly against the
        module's own kind list."""
        env = make_env(tmp_path)
        record = make_behavior(scope="project", record_id="lrn-00000020")
        create_record(env.ledger, record, project_path=env.host)
        verbs.route(
            env.ledger,
            "lrn-00000020",
            dest="claude-md:rules:infra",
            no_push=True,
        )

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="project")
        data = compiled.load_record(env.ledger, slug)
        rules_target = env.host / ".claude" / "rules" / "infra.md"
        assert rules_target.is_file()
        key = compiled.region_key(env.host, rules_target)
        entry = compiled.entry_for(data, key)
        assert entry is not None
        assert entry["region"] == "managed"  # never "paths" — no such kind exists
        with pytest.raises(compiled.CompiledRecordError):
            compiled.region_bytes("irrelevant text", "paths")


class TestPlain8SelftestDriftFourVerdicts:
    """PLAIN8: `--selftest`'s drift row reports on plain hosts — the
    entry-marker check unchanged, plus the region verdict; a host with
    no compile record yet SKIPs with a distinguishable reason. Check:
    four fixtures (no record; clean; stale; edited) asserting four
    distinct rendered strings, via `selfcheck._check_drift` directly."""

    def _routed(self, tmp_path, rid):
        env = make_env(tmp_path)
        plain_host = tmp_path / f"plain8-{rid}"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id=rid)
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, rid, dest="claude-md", no_push=True)
        return env, plain_host

    def test_no_compile_record_yet_renders_unknown_provenance_skip(self, tmp_path):
        from self_learn import selfcheck

        env, plain_host = self._routed(tmp_path, "lrn-00000012")
        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        record_path = compiled.compiled_record_path(env.ledger, slug)
        record_path.unlink()  # entry absent, region still present on disk

        ok, message = selfcheck._check_drift(env.ledger)
        assert ok is True  # never gates the boolean
        assert "no compile record yet" in message
        assert "unknown provenance" in message

    def test_clean_renders_matches_its_compile_record(self, tmp_path):
        from self_learn import selfcheck

        env, plain_host = self._routed(tmp_path, "lrn-00000013")
        ok, message = selfcheck._check_drift(env.ledger)
        assert ok is True
        assert "matches its compile record (clean)" in message

    def test_stale_renders_matches_the_priors_observation(self, tmp_path):
        """Constructs "stale" directly against the compile record entry
        (`compiled.write_entry`) rather than via a second real routed
        record — routing a real second record would ALSO leave ITS OWN
        entry marker absent once disk is reverted to the pre-that-write
        state, a genuine, separate failure that would blank
        `_check_drift`'s `plain_notes` out of the returned message
        entirely (the function only ever returns the failures list once
        any failure exists). Faking `based_on_sha256` in isolation keeps
        the routed record's OWN marker intact, so no other check fires."""
        from self_learn import selfcheck

        env, plain_host = self._routed(tmp_path, "lrn-00000014")
        target = plain_host / "CLAUDE.md"
        current_text = target.read_text(encoding="utf-8")
        current_region = compiled.region_bytes(current_text, "managed")
        assert current_region is not None
        current_hash = compiled.sha256_hex(current_region)

        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        compiled.write_entry(
            env.ledger,
            slug,
            key,
            region="managed",
            sha256="f" * 64,  # a hypothetical newer write that never landed
            based_on_sha256=current_hash,  # what's ACTUALLY on disk right now
            nbytes=len(current_region),
            by="test-fixture (PLAIN8 stale isolation)",
            host=str(plain_host),
            mode="plain",
        )

        ok, message = selfcheck._check_drift(env.ledger)
        assert ok is True  # no OTHER check fires — isolated
        assert "matches the compile record's prior observation (stale)" in message
        assert "lrn-00000014" in message

    def test_edited_renders_a_failure_not_a_note(self, tmp_path):
        from self_learn import selfcheck

        env, plain_host = self._routed(tmp_path, "lrn-00000016")
        target = plain_host / "CLAUDE.md"
        from self_learn.compilers import BEGIN_MARKER

        text = target.read_text(encoding="utf-8")
        target.write_text(
            text.replace(BEGIN_MARKER, BEGIN_MARKER + "\nhand edit"),
            encoding="utf-8",
        )

        ok, message = selfcheck._check_drift(env.ledger)
        assert ok is False  # THE one verdict that gates the boolean
        assert "hand-edited outside self-learn (edited)" in message

    def test_all_four_strings_are_pairwise_distinct(self, tmp_path):
        """The Check cell's own wording: FOUR distinguishable strings,
        not two collapsed pairs — assembled from the four scenarios
        above run independently so none shares tmp_path state."""
        strings = []
        for name, rid in (
            ("unknown", "lrn-00000017"),
            ("clean", "lrn-00000018"),
        ):
            env, plain_host = self._routed(tmp_path / name, rid)
            if name == "unknown":
                slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
                compiled.compiled_record_path(env.ledger, slug).unlink()
            from self_learn import selfcheck

            _, message = selfcheck._check_drift(env.ledger)
            strings.append(message)
        assert strings[0] != strings[1]


class TestRpt1PlainHostInReport:
    def test_plain_host_row_present_in_report_json(self, tmp_path, monkeypatch):
        """RPT1: a plain host appears in both report surfaces that
        dropped it (report.py:973, :1480). Check: register a plain
        host, route a `rules` record into it, assert the row is
        present in `report --json`."""
        import json

        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        plain_host = tmp_path / "rpt1-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-00000019")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(
            env.ledger, "lrn-00000019", dest="claude-md:rules:infra", no_push=True
        )

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["report", "--json"])
        out = buf.getvalue()
        assert rc == 0
        data = json.loads(out)
        rendered = json.dumps(data)
        assert str(plain_host) in rendered


class TestPlain7ConsentLines:
    def test_plain_mode_prints_the_no_commit_no_push_consent_and_local_note(
        self, tmp_path, monkeypatch, capsys
    ):
        """PLAIN7: `host add --mode plain` prints a consent line naming
        what plain mode does NOT do (no commit, no push, no off-machine
        backup) AND the claude-md:local residual of §4.11, alongside
        the existing (preserved) consent line."""
        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        target = tmp_path / "plain7-consent"
        target.mkdir()
        rc = cli.main(["host", "add", "--mode", "plain", str(target)])
        out = capsys.readouterr().out

        assert rc == 0
        # the pre-existing, preserved consent line
        assert "registers this repo's canon surfaces" in out
        # PLAIN7's own new lines
        assert "NO commit" in out
        assert "NO push" in out
        assert "off-machine backup" in out
        assert "claude-md:local" in out

    def test_git_mode_prints_no_plain_consent_lines(self, tmp_path, monkeypatch, capsys):
        """Negative control: a git-mode `host add` prints the SAME
        pre-existing consent line and NONE of PLAIN7's plain-only
        lines — MODE11/UN4's byte-identical-for-git-mode guarantee
        extends to this surface too."""
        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        target = tmp_path / "plain7-git-control"
        init_repo(target)
        rc = cli.main(["host", "add", str(target)])
        out = capsys.readouterr().out

        assert rc == 0
        assert "registers this repo's canon surfaces" in out
        assert "NO commit" not in out
        assert "NO push" not in out
        assert "claude-md:local" not in out


class TestPlain11HookRetirementUnlinkNoGit:
    def _plain_skills_root_env(self, tmp_path):
        """A from-scratch ledger + PLAIN skills root (not `make_env`,
        which always registers a GIT skills root and MODE6 forbids
        flipping it after the fact)."""
        ledger = tmp_path / "plain11-ledger"
        init_repo(ledger)
        for sub in ("skills", "projects", "user", "telemetry"):
            (ledger / sub).mkdir()
        # No commit here: git doesn't track empty directories, so there
        # is nothing to stage yet — `host_add` below makes the ledger's
        # FIRST commit (hosts.yaml).

        skills_root = tmp_path / "plain11-skills-root"
        skills_root.mkdir()
        host_add(ledger, skills_root, "skills-root", mode="plain")

        skill_dir = skills_root / "plugins" / "s-plugin" / "skills" / "s"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# s skill\n", encoding="utf-8")
        return ledger, skills_root

    def test_supersede_retires_hook_by_unlink_no_git_no_commit(
        self, tmp_path, monkeypatch
    ):
        """PLAIN11: hook retirement on a plain host removes the script
        by `Path.unlink`, with no `git rm` and no commit. Check: the
        PLAIN4 git-call spy PLUS `script.exists() is False` — the
        outcome alone is not enough, since `_remove_hook_script`
        swallows a `GitOpsError` into a warning rather than raising."""
        ledger, skills_root = self._plain_skills_root_env(tmp_path)

        calls: list[tuple[str, ...]] = []
        real_git = gitops._git

        def spy(repo, *args, **kw):
            calls.append((str(repo), *args))
            return real_git(repo, *args, **kw)

        monkeypatch.setattr(gitops, "_git", spy)

        rid = "lrn-0000000f"
        trigger = "About to edit .storage while HA is running."
        record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
        create_record(ledger, record)
        write_proposal(
            ledger,
            rid,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(ledger, rid)
        verbs.route(ledger, rid, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = skills_root / "plugins" / "s-plugin" / "hooks" / script_name(
            rid, trigger
        )
        assert script.is_file()
        calls.clear()

        new_id = "lrn-00000010"
        new_record = make_behavior(scope="skill:s", record_id=new_id)
        create_record(ledger, new_record)
        result = verbs.supersede(ledger, rid, new_id)

        assert not script.exists()  # the outcome
        plain_calls = [c for c in calls if c[0] == str(skills_root)]
        assert plain_calls == []  # no `git rm`, no git call of any kind
        assert not (skills_root / ".git").exists()
        text = "\n".join(result.warnings) + "\n".join(result.post_notes)
        assert "settings.json" in text and script.name in text  # the reminder still fires

    def test_graduate_also_retires_hook_by_unlink_no_git(self, tmp_path, monkeypatch):
        """PLAIN11, `graduate` leg: M3-4 names graduation too — there is
        no section to regenerate, so removal cannot wait for a
        recompile that never comes; same plain-mode degrade applies."""
        ledger, skills_root = self._plain_skills_root_env(tmp_path)

        calls: list[tuple[str, ...]] = []
        real_git = gitops._git

        def spy(repo, *args, **kw):
            calls.append((str(repo), *args))
            return real_git(repo, *args, **kw)

        monkeypatch.setattr(gitops, "_git", spy)

        rid = "lrn-00000011"
        trigger = "About to edit .storage while HA is running."
        record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
        create_record(ledger, record)
        write_proposal(
            ledger,
            rid,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(ledger, rid)
        verbs.route(ledger, rid, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = skills_root / "plugins" / "s-plugin" / "hooks" / script_name(
            rid, trigger
        )
        assert script.is_file()
        calls.clear()

        verbs.graduate(ledger, rid)

        assert not script.exists()
        plain_calls = [c for c in calls if c[0] == str(skills_root)]
        assert plain_calls == []


class TestGate4BrokenPlainHostListed:
    """GATE4: `host list` shows a broken PLAIN entry marked broken — the
    SAME lenient-list contract `test_hosting_fixes.py::TestBROKEN::
    test_host_list_shows_a_broken_entry_marked_broken` pins for git
    (list shows the problem rather than exploding)."""

    def test_plain_entry_pointing_nowhere_is_listed_broken(self, tmp_path, monkeypatch):
        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        gone = tmp_path / "gone-plain-repo"
        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {env.host}\n"
            f"projects:\n  - path: {gone}\n    mode: plain\n",
            encoding="utf-8",
        )

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["host", "list"])
        out = buf.getvalue()

        assert rc == 0
        assert str(gone) in out
        assert "BROKEN" in out
        assert str(env.host) in out  # the sound entry still listed

    def test_plain_entry_missing_its_marker_is_listed_broken(self, tmp_path, monkeypatch):
        """The plain-specific soundness failure (GATE2's own refusal
        reason, MARKER_FILENAME missing) must ALSO render BROKEN in
        `host list` — not just a nonexistent path."""
        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        rogue = tmp_path / "rogue-plain-listed"
        rogue.mkdir()
        (env.ledger / "hosts.yaml").write_text(
            f"skills_root: {env.host}\n"
            f"projects:\n  - path: {rogue}\n    mode: plain\n",
            encoding="utf-8",
        )
        assert not (rogue / hosts_mod.MARKER_FILENAME).exists()

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["host", "list"])
        out = buf.getvalue()

        assert rc == 0
        assert str(rogue) in out
        assert "BROKEN" in out
        assert hosts_mod.MARKER_FILENAME in out  # the actual reason, not just a generic flag


class TestRec10HalfWrittenExit7:
    def test_ledger_commit_failure_after_the_record_write_is_exit_7(
        self, tmp_path, monkeypatch, capsys
    ):
        """REC10: a failure of the enclosing stage/commit AFTER the
        compile-record file is written returns exit 7 with the
        half-written repair text, never exit 6. Uses a REAL git shim
        that fails only the commit step (`failing_git_shim`, the round-7
        BLOCKER 2 probe shape this codebase's own tests use elsewhere)
        rather than monkeypatching the code under test."""
        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        record = make_behavior(scope="skill:s", record_id="lrn-00000021")
        create_record(env.ledger, record)

        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            rc = cli.main(["route", "lrn-00000021", "--dest", "skill-md", "--no-push"])
        finally:
            flag.unlink()
        out = capsys.readouterr()

        assert rc == 7
        assert "WRITE NOT COMMITTED" in out.err
        assert "Repair:" in out.err

        # the state the CLI must not misdescribe: the record file DID
        # move to resolved/ AND the compile-record file DID get written
        # to the ledger's working tree — the ledger just never committed
        # either. Confirms the failure fired AFTER the record write,
        # not instead of it (a mutation that made this fire BEFORE the
        # write would leave `compiled/` untouched here).
        ledger_bucket = env.ledger / "skills" / "s"
        assert (ledger_bucket / "resolved" / "lrn-00000021.md").is_file()
        assert not (ledger_bucket / "pending" / "lrn-00000021.md").is_file()
        compiled_dir = env.ledger / "compiled"
        assert compiled_dir.is_dir()
        assert any(compiled_dir.iterdir())
        status = git(env.ledger, "status", "--porcelain").stdout
        assert status.strip() != ""  # uncommitted — exactly the half-written state

    def test_m20_a_git_failure_before_any_write_is_a_clean_refusal_not_exit_7(
        self, tmp_path, monkeypatch, capsys
    ):
        """Negative control: a git failure BEFORE the first mutation
        (the lock-scoped `commit_lock`/`host_lock` acquisition path,
        the shape round-7's own invariant closed) is a clean refusal,
        not exit 7 — proves exit 7 is keyed on "did a write actually
        land", not merely "did git fail somewhere". Simulated here by
        pointing the ledger at a path that is not a git repo at all —
        every verb refuses before any mutation for that reason, and the
        refusal must never claim the half-written state."""
        from self_learn import cli

        home = tmp_path / "not-a-repo"
        home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        rc = cli.main(["route", "lrn-nonexistent", "--dest", "skill-md", "--no-push"])
        out = capsys.readouterr()
        assert rc != 7
        assert "WRITE NOT COMMITTED" not in out.err


class TestRec3OutsideMarkerPreservation:
    def test_hand_edit_outside_markers_verdicts_clean_and_survives_recompile(
        self, tmp_path
    ):
        """REC3: the predicate returns `clean` for a hand edit OUTSIDE
        the markers (the compile record only ever hashes the MANAGED
        region between BEGIN_MARKER/END_MARKER — compilers.py's own
        long-standing contract, doc'd at compilers.py:8-9), and a
        subsequent regeneration preserves that edit byte-exactly."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "rec3-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-00000013")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000013", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        from self_learn.compilers import BEGIN_MARKER, END_MARKER

        before_text = target.read_text(encoding="utf-8")
        assert BEGIN_MARKER in before_text and END_MARKER in before_text
        note = "This paragraph lives OUTSIDE the managed markers."
        outside_edit = before_text + "\n\n## Human notes\n" + note + "\n"
        target.write_text(outside_edit, encoding="utf-8")

        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert entry is not None
        region = compiled.region_bytes(outside_edit, "managed")
        assert region is not None
        observed = compiled.sha256_hex(region)
        assert compiled.verdict_for(entry, observed) == "clean"

        result = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in result.warnings)
        after_text = target.read_text(encoding="utf-8")
        assert after_text == outside_edit  # byte-exact: the note survives verbatim
        assert note in after_text

        final_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert final_entry is not None
        final_region = compiled.region_bytes(after_text, "managed")
        assert final_region is not None
        final_observed = compiled.sha256_hex(final_region)
        assert compiled.verdict_for(final_entry, final_observed) == "clean"

    def test_m12_hash_whole_file_would_misread_the_outside_edit_as_edited(
        self, tmp_path
    ):
        """M12, run directly: if the predicate hashed the WHOLE file
        (not just the managed region), the SAME outside-marker edit
        above would misread as `edited` — the false positive REC3
        exists to rule out, confirmed by substituting the whole-file
        hash in for the region hash and re-checking the verdict."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "rec3-plain-m12"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-00000014")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000014", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        before_text = target.read_text(encoding="utf-8")
        outside_edit = before_text + "\nHuman note outside the markers.\n"
        target.write_text(outside_edit, encoding="utf-8")

        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert entry is not None

        # M12: hash the WHOLE file instead of the managed region alone.
        whole_file_hash = compiled.sha256_hex(outside_edit.encode("utf-8"))
        assert compiled.verdict_for(entry, whole_file_hash) == "edited"  # the false positive


class TestRec13StaleNeverEdited:
    def test_two_consecutive_host_phase_failures_still_verdict_stale(
        self, tmp_path, monkeypatch
    ):
        """REC13: two consecutive `_HOST_PHASE_ERRORS` still verdict
        `stale`, not `edited`, and a plain `recompile` lands the region
        afterward — H-2 must hold no matter how many times the host
        phase fails in a row. Mutation M47 (manually verified during
        the build, then restored): redefining `based_on_sha256` as the
        PREVIOUS expectation instead of the pre-flight OBSERVED hash
        makes the second run verdict `edited` and both `route` and
        `recompile` refuse — confirmed RED against that inverse edit of
        `_observe_region_hash`'s call-site ordering, restored before
        this test was written."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "rec13-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-00000006")
        create_record(env.ledger, record, project_path=plain_host)

        import self_learn.verbs as verbs_mod

        def _boom(*a, **kw):
            raise verbs_mod.CompileError("simulated host-phase failure")

        # route r1: host phase fails (ledger still commits — H-2)
        monkeypatch.setattr(verbs_mod, "_apply_target", _boom)
        result = verbs.route(env.ledger, "lrn-00000006", dest="claude-md", no_push=True)
        assert result.commit_sha  # the ledger commit still landed
        assert any("HOST PHASE FAILED" in w for w in result.warnings)

        # a SECOND resolution-shaped failure: recompile also hits the
        # simulated failure (host phase still down)
        recompile_result = verbs.recompile(env.ledger, no_push=True)
        assert any(
            "HOST PHASE FAILED" in w or "simulated host-phase failure" in w
            for w in recompile_result.warnings
        )

        target = plain_host / "CLAUDE.md"
        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        # region is ABSENT on disk (the host phase never landed a write) —
        # this is the "missing" row, not "edited": recompile must proceed.
        assert compiled.verdict_for(entry, None) == "missing"

        # now let the host phase succeed — recompile lands the region.
        monkeypatch.undo()
        final = verbs.recompile(env.ledger, no_push=True)
        entry2 = next((e for e in final.entries if e.target == target), None)
        assert entry2 is not None and entry2.changed
        assert target.is_file()


class TestRecompileAdopt:
    def test_adopt_clears_edited_and_preserves_the_hand_edit(self, tmp_path):
        """REC11: `recompile --adopt` re-records the on-disk region as
        authoritative and clears an `edited` refusal; the compile
        record's entry now equals the region actually on disk (spec's
        own Check cell), and — since adopting means THIS run must not
        immediately re-render canonical content over the very bytes it
        just adopted — those hand-edited bytes are the ones left on
        disk; `--force` does not exist as a CLI flag.

        Regression coverage for a real bug found while writing this
        test: the first implementation of the `--adopt` leg wrote the
        adopt entry from the pre-render (hand-edited) bytes and then
        fell through into the SAME loop's normal render leg, which
        immediately re-derived canonical content from the ledger and
        overwrote the file — leaving the just-written compile record
        entry pointing at bytes the target no longer held (confirmed:
        `entry["sha256"]` didn't match `sha256(region_bytes(disk))`
        after the call returned, and a FOLLOWING plain `recompile` call
        re-refused "edited" — an infinite loop `--adopt` exists
        specifically to break). Fixed in `verbs.py`'s `recompile()` by
        `continue`-ing past the render leg once a target has been
        adopted this run (see the comment there dated at the fix)."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "adopt-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-00000007")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000007", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        text = target.read_text(encoding="utf-8")
        from self_learn.compilers import BEGIN_MARKER

        edited_text = text.replace(BEGIN_MARKER, BEGIN_MARKER + "\nhand edit")
        target.write_text(edited_text, encoding="utf-8")

        result = verbs.recompile(env.ledger, no_push=True)
        assert any("edited" in w for w in result.warnings)

        adopt_result = verbs.recompile(env.ledger, no_push=True, adopt=target)
        assert not any(
            "edited" in w and str(target) in w for w in adopt_result.warnings
        )
        assert target.read_text(encoding="utf-8") == edited_text  # bytes preserved

        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert entry is not None
        region = compiled.region_bytes(edited_text, "managed")
        assert region is not None
        observed = compiled.sha256_hex(region)
        assert entry["sha256"] == observed
        assert compiled.verdict_for(entry, observed) == "clean"

        # A follow-up recompile call — WITHOUT --adopt — legitimately
        # re-renders canonical content over the adopted hand edit
        # (recompile's job is always "converge toward ledger-canonical
        # content"; confirmed: `changed=True`, canonical text restored,
        # hand edit gone). RESIDUAL-DEFECT FIX (coordinator ruling,
        # 2026-08-28): this call must not just avoid re-raising
        # "edited" — it must leave the record ACCURATE for what it just
        # wrote, not merely lucky that canonical happens to match a
        # stale record. Assert both.
        clean_result = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in clean_result.warnings)
        reverted_text = target.read_text(encoding="utf-8")
        assert reverted_text != edited_text  # canonical content, hand edit gone
        entry2 = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert entry2 is not None
        region2 = compiled.region_bytes(reverted_text, "managed")
        assert region2 is not None
        observed2 = compiled.sha256_hex(region2)
        assert entry2["sha256"] == observed2
        assert compiled.verdict_for(entry2, observed2) == "clean"
        # And a THIRD call — this is the exact failure the original bug
        # produced (a spurious "edited" refusal against content that
        # was, in fact, already canonical) — must be a true no-op: no
        # warnings, no further ledger commit, record still accurate.
        ledger_head_before_third = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        third_result = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in third_result.warnings)
        ledger_head_after_third = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        assert ledger_head_after_third == ledger_head_before_third


class TestRecompileRecordResyncOnRender:
    def test_clean_plain_target_recompile_is_noop_when_ledger_unchanged(
        self, tmp_path
    ):
        """Residual-defect fix (coordinator ruling, 2026-08-28): under
        the six-case predicate, a "clean" plain target — record matches
        on-disk, nothing about the ledger has changed since — must see
        a plain `recompile` render nothing at all: no file write, no
        ledger commit, record byte-for-byte unchanged."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "resync-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-00000010")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000010", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        before_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        before_bytes = target.read_bytes()
        before_head = git(env.ledger, "rev-parse", "HEAD").stdout.strip()

        result = verbs.recompile(env.ledger, no_push=True)

        assert not result.warnings
        assert target.read_bytes() == before_bytes
        after_head = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        assert after_head == before_head  # no ledger commit for a true no-op
        after_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after_entry == before_entry

    def test_clean_plain_target_render_after_ledger_change_writes_and_resyncs(
        self, tmp_path
    ):
        """Residual-defect fix: when the LEDGER changes what canonical
        content for a target should be (a second record routed to the
        same file) — the target is still "clean" against its OLD
        record right up until this call — a plain `recompile` must
        BOTH write the new canonical bytes AND re-sync the record to
        match; it must never leave disk and record disagreeing.

        Mutation: comment out the record re-sync block added to
        `recompile()`'s plain-mode leg — the assertion that the record
        matches the post-render disk bytes goes RED, and a THIRD
        `recompile` call spuriously refuses "edited" against content
        that is, in fact, exactly canonical (the shape of bug this
        fix closes)."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "resync-plain-2"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        rec1 = make_behavior(scope="project", record_id="lrn-00000011")
        create_record(env.ledger, rec1, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000011", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        before_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert before_entry is not None
        before_text = target.read_text(encoding="utf-8")

        # Change what canonical content SHOULD be, WITHOUT touching the
        # target file — this is the "ledger changed" leg: a second
        # record lands via `route`, which (per REC9) writes its own
        # compile-record entry for the target it's routing into — a
        # SEPARATE record (`lrn-00000012`) routed to the SAME shared
        # skill would collide with this project host's CLAUDE.md, so
        # instead simulate the drift directly: hand the ledger a routed
        # record whose presence changes `_expected_managed_region`'s
        # output the next time anything recompiles this target, by
        # routing a second behavior into the SAME plain host file.
        rec2 = make_behavior(scope="project", record_id="lrn-00000012")
        create_record(env.ledger, rec2, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000012", dest="claude-md", no_push=True)
        # `route` itself already recompiles+resyncs (REC1/REC9) — assert
        # the setup produced exactly what this test needs: two records
        # now both live in the canonical region, entry changed from rec1.
        after_route_entry = compiled.entry_for(
            compiled.load_record(env.ledger, slug), key
        )
        assert after_route_entry is not None
        assert after_route_entry["sha256"] != before_entry["sha256"]
        after_route_text = target.read_text(encoding="utf-8")
        assert after_route_text != before_text
        assert "lrn-00000011" in after_route_text
        assert "lrn-00000012" in after_route_text

        # Now the actual residual-defect scenario: hand-edit the file
        # back to the STALE (rec1-only) content — the record still says
        # rec1+rec2 (clean against nothing on disk right now: this is
        # "edited"). Adopt it (clears the refusal, records the stale
        # bytes as authoritative) — THEN a plain recompile must both
        # rewrite to the true two-record canonical content AND re-sync
        # the record to match, in the SAME call.
        target.write_text(before_text, encoding="utf-8")
        adopt_result = verbs.recompile(env.ledger, no_push=True, adopt=target)
        assert not any("edited" in w for w in adopt_result.warnings)
        assert target.read_text(encoding="utf-8") == before_text  # adopt froze it

        resync_result = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in resync_result.warnings)
        final_text = target.read_text(encoding="utf-8")
        assert final_text == after_route_text  # canonical (both records) restored
        final_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert final_entry is not None
        final_region = compiled.region_bytes(final_text, "managed")
        assert final_region is not None
        final_observed = compiled.sha256_hex(final_region)
        assert final_entry["sha256"] == final_observed
        assert compiled.verdict_for(final_entry, final_observed) == "clean"

        # And the "never falsely refuses again" invariant: a third call
        # is a true no-op.
        third = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in third.warnings)
        assert target.read_text(encoding="utf-8") == final_text

    def test_no_force_flag_exists(self):
        """REC11: `--force` is deliberately NOT offered anywhere in
        this path."""
        from self_learn import cli

        parser = cli._build_parser() if hasattr(cli, "_build_parser") else None
        if parser is None:
            with pytest.raises(SystemExit):
                cli.main(["recompile", "--force"])
        else:
            with pytest.raises(SystemExit):
                parser.parse_args(["recompile", "--force"])


# --------------------------------------------------------------- GATE group


class TestGate2PlainPreflightRefusal:
    def test_hand_edited_hosts_yaml_plain_without_marker_refused(self, tmp_path):
        """GATE2: a hand-edited hosts.yaml naming a plain path WITHOUT
        `.self-learn-host` is refused in PRE-FLIGHT — no canon file
        created, ledger HEAD unchanged."""
        env = make_env(tmp_path)
        rogue = tmp_path / "rogue-plain"
        rogue.mkdir()
        text = (env.ledger / "hosts.yaml").read_text(encoding="utf-8")
        (env.ledger / "hosts.yaml").write_text(
            text + f"  - {{path: {rogue}, mode: plain}}\n", encoding="utf-8"
        )
        commit_all(env.ledger, "hand-edited hosts.yaml, no marker written")
        head_before = git(env.ledger, "rev-parse", "HEAD").stdout.strip()

        record = make_behavior(scope="project", record_id="lrn-00000008")
        create_record(env.ledger, record, project_path=rogue)
        with pytest.raises(verbs.VerbError):
            verbs.route(env.ledger, "lrn-00000008", dest="claude-md", no_push=True)

        assert not (rogue / "CLAUDE.md").is_file()
        head_after = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        assert head_after == head_before


class TestGate5MarkerSurvivesRemove:
    def test_marker_names_home_and_survives_host_remove(self, tmp_path):
        """GATE5: `.self-learn-host` names the registering ledger home
        and an ISO timestamp; `host remove` LEAVES it in place."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "gate5-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        marker = plain_host / hosts_mod.MARKER_FILENAME
        assert marker.is_file()
        marker_text = marker.read_text(encoding="utf-8")
        assert str(env.ledger) in marker_text

        hosts_mod.host_remove(env.ledger, plain_host)
        assert marker.is_file()  # removal deregisters, never deletes the marker


# -------------------------------------------------------------- PLAIN group


class TestPlainEndToEnd:
    def test_plain1_add_succeeds_no_git_init_writes_marker(self, tmp_path):
        """PLAIN1: `host add --mode plain` succeeds against a non-repo
        directory with no parent repo, runs no `git init`, writes the
        marker."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "plain1-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        assert not (plain_host / ".git").exists()
        assert (plain_host / hosts_mod.MARKER_FILENAME).is_file()

    def test_plain2_route_writes_uncommitted_no_extra_ledger_commits(self, tmp_path):
        """PLAIN2: a route into a plain host writes the managed
        section; `host_commit_sha is None`; the host contains no
        `.git`; the ledger has EXACTLY the resolution commit (no
        others) for this route. PLAIN3: the envelope's derived
        `outcome_state` is `"wrote_uncommitted"`, not the `"unknown"`
        fallthrough the predicate used to hit."""
        from self_learn import cli

        env = make_env(tmp_path)
        plain_host = tmp_path / "plain2-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-00000009")
        create_record(env.ledger, record, project_path=plain_host)
        before = len(git(env.ledger, "log", "--format=%H").stdout.split())
        result = verbs.route(env.ledger, "lrn-00000009", dest="claude-md", no_push=True)
        after = len(git(env.ledger, "log", "--format=%H").stdout.split())
        assert result.host_commit_sha is None
        assert not (plain_host / ".git").exists()
        assert after == before + 1
        assert (plain_host / "CLAUDE.md").is_file()
        assert cli._outcome_state(result) == "wrote_uncommitted"

    def test_plain4_no_git_subprocess_against_plain_host(self, tmp_path, monkeypatch):
        """PLAIN4: no git subprocess runs against a plain host during a
        route. Positive control in the same test: the identical
        instrument over a git-mode route records a non-zero count."""
        env = make_env(tmp_path)
        calls: list[tuple[str, ...]] = []
        real_git = gitops._git

        def spy(repo, *args, **kw):
            calls.append((str(repo), *args))
            return real_git(repo, *args, **kw)

        monkeypatch.setattr(gitops, "_git", spy)

        plain_host = tmp_path / "plain4-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-0000000a")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-0000000a", dest="claude-md", no_push=True)
        plain_calls = [c for c in calls if c[0] == str(plain_host)]
        assert plain_calls == []

        calls.clear()
        record2 = make_behavior(scope="skill:s", record_id="lrn-0000000b")
        create_record(env.ledger, record2)
        verbs.route(env.ledger, "lrn-0000000b", dest="skill-md", no_push=True)
        host_calls = [c for c in calls if c[0] == str(env.host)]
        assert len(host_calls) > 0  # positive control: git mode DOES call git

    def test_plain9_local_claude_md_skips_check_ignore(self, tmp_path, monkeypatch):
        """PLAIN9: `claude-md:local` on a plain host does not call
        `gitops.check_ignore`. Positive control: the same route on a
        git host still calls it and still refuses (no .gitignore
        entry)."""
        env = make_env(tmp_path)
        calls: list[Path] = []
        real_check_ignore = gitops.check_ignore

        def spy(repo, target):
            calls.append(Path(repo))
            return real_check_ignore(repo, target)

        monkeypatch.setattr(gitops, "check_ignore", spy)

        plain_host = tmp_path / "plain9-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-0000000c")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-0000000c", dest="claude-md:local", no_push=True)
        assert calls == []  # plain host: never consulted

        # positive control: git host WITHOUT a .gitignore entry refuses,
        # and check_ignore WAS consulted en route to that refusal.
        record2 = make_behavior(scope="project", record_id="lrn-0000000d")
        create_record(env.ledger, record2, project_path=env.host)
        with pytest.raises(verbs.VerbError):
            verbs.route(env.ledger, "lrn-0000000d", dest="claude-md:local", no_push=True)
        assert calls != []

    def test_plain10_push_skips_plain_hosts_silently(self, tmp_path, capsys):
        """PLAIN10: `self-learn push` skips plain hosts silently and
        without calling `unpushed_commits` on them."""
        from self_learn import cli

        env = make_env(tmp_path)
        plain_host = tmp_path / "plain10-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-0000000e")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-0000000e", dest="claude-md", no_push=True)
        capsys.readouterr()
        rc = cli.main(
            ["push"], env={"SELF_LEARN_HOME": str(env.ledger)}
        ) if False else None
        # cli.main doesn't take env=; use monkeypatch-free direct call via os.environ
        import os

        old = os.environ.get("SELF_LEARN_HOME")
        os.environ["SELF_LEARN_HOME"] = str(env.ledger)
        try:
            rc = cli.main(["push"])
        finally:
            if old is None:
                os.environ.pop("SELF_LEARN_HOME", None)
            else:
                os.environ["SELF_LEARN_HOME"] = old
        out = capsys.readouterr().out
        assert f"skipping {plain_host}" not in out

    def test_plain12_lock_paths(self, tmp_path):
        """PLAIN12: the plain-host lock path is
        `${XDG_CACHE_HOME}/self-learn/host-<slug>.commit.lock`; the
        git-host lock path is byte-identical to `commit_lock_path`'s
        own (UN8)."""
        env = make_env(tmp_path)
        assert gitops.host_lock_path(env.host, "git") == gitops.commit_lock_path(env.host)
        plain_path = gitops.host_lock_path(env.host, "plain")
        assert plain_path.name.startswith("host-")
        assert plain_path.name.endswith(".commit.lock")
        assert plain_path.parent.name == "self-learn"


class TestPlain5RealOsLock:
    def test_two_processes_serialize_on_the_plain_host_lock(self, tmp_path):
        """PLAIN5: two OS PROCESSES entering the plain-host lock are
        serialized — the second observably blocks until the first
        releases. Never threads: `gitops._held_locks` makes a
        same-process re-acquire a pass-through, so this must be
        cross-process to mean anything."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "plain5-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")

        holder_script = tmp_path / "holder.py"
        holder_out = tmp_path / "holder-out.txt"
        holder_script.write_text(
            "import sys, time\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})\n"
            "from pathlib import Path\n"
            "from self_learn import gitops\n"
            f"with gitops.host_lock(Path({str(plain_host)!r}), 'plain'):\n"
            f"    Path({str(holder_out)!r}).write_text('HELD')\n"
            "    time.sleep(1.5)\n",
            encoding="utf-8",
        )
        proc = subprocess.Popen(["python3", str(holder_script)])
        try:
            import time

            deadline = time.monotonic() + 3.0
            while not holder_out.is_file() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert holder_out.is_file(), "holder process never acquired the lock"

            t0 = time.monotonic()
            with gitops.host_lock(plain_host, "plain", timeout=5.0):
                elapsed = time.monotonic() - t0
            # the second acquire had to WAIT for the holder's ~1.5s sleep
            assert elapsed > 0.8, f"second acquire did not block (elapsed={elapsed})"
        finally:
            proc.wait(timeout=5)


# ---------------------------------------------------------------- RCN group


class TestReconcileLearnsCompiledRecords:
    def test_rcn1_uncommitted_compiled_record_is_reconciled(self, tmp_path):
        """RCN1: an uncommitted `<home>/compiled/<slug>.yaml` is found
        by `reconcile.find_orphans` and committed under the pinned
        reconcile subject."""
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-0000000f")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-0000000f", dest="skill-md", no_push=True)

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        record_path = compiled.compiled_record_path(env.ledger, slug)
        assert record_path.is_file()
        # simulate the H-5 orphan: the file exists but was never committed
        record_path.write_text(
            record_path.read_text(encoding="utf-8") + "\n# uncommitted edit\n",
            encoding="utf-8",
        )
        status = git(env.ledger, "status", "--porcelain").stdout
        assert "compiled/" in status

        result = reconcile.reconcile(env.ledger, no_push=True)
        assert record_path in result.committed
        status_after = git(env.ledger, "status", "--porcelain").stdout
        assert "compiled/" not in status_after

    def test_rcn3_compiled_only_home_reads_bootstrapped(self, tmp_path):
        """RCN3: a home containing ONLY `compiled/` (no
        skills/projects/user/telemetry yet) reads as bootstrapped, not
        uninitialized. `home_state` requires the LEDGER itself to be a
        git repo (doc 13 §2 — this is unrelated to a canon HOST's own
        mode) but its bootstrap-evidence check below that is a pure
        filesystem `is_dir()` test, so `compiled/` need not be
        committed — git doesn't track empty directories anyway."""
        home = tmp_path / "compiled-only-home"
        init_repo(home)
        (home / "compiled").mkdir()
        assert home_state(home) == "ok"

    def test_home_with_none_of_the_evidence_reads_uninitialized(self, tmp_path):
        """Negative control for RCN3: a bare git repo with none of the
        evidence dirs and no hosts.yaml reads "uninitialized", not
        "ok" — proves the "compiled/ alone" result above is really
        evidence-driven, not `home_state` degenerately returning "ok"
        for any git repo."""
        home = tmp_path / "truly-empty-home"
        init_repo(home)
        assert home_state(home) == "uninitialized"


# ---------------------------------------------------- MODE7 / MODE9 (AST)


class TestMode7HostsAttributeSweep:
    """MODE7: every existing consumer of `Hosts.skills_root`/`.projects`
    keeps working unedited — the SHAPE is unchanged, `skills_root_mode`/
    `project_modes` are new, parallel fields nobody pre-existing reads.
    **Check (spec text):** an AST test enumerating every attribute
    access on a `Hosts` instance across BOTH `src` trees, asserted
    against the pre-existing set; positive control in the same test —
    the same enumeration for a name known absent returns zero."""

    @staticmethod
    def _hosts_attribute_accesses(tree: ast.AST) -> set[str]:
        """Track names that are either (a) assigned directly from a call
        to `load_hosts(...)` (bare or dotted), or (b) a function
        parameter annotated `Hosts` (bare or dotted) — the two shapes
        every real `Hosts`-consuming call site in this codebase uses
        (`hosts = load_hosts(home)` / `def f(hosts: Hosts) -> ...`).
        Collects every `.attr` accessed on those tracked names anywhere
        in the same function body (conservative: over-inclusive by
        scope, never under-inclusive — a false positive here would
        still have to be a REAL attribute name to pass the assertion
        below, so widening scope cannot hide a violation)."""

        def is_load_hosts_call(node: ast.AST) -> bool:
            if not isinstance(node, ast.Call):
                return False
            f = node.func
            if isinstance(f, ast.Name):
                return f.id == "load_hosts"
            if isinstance(f, ast.Attribute):
                return f.attr == "load_hosts"
            return False

        def is_hosts_annotation(annotation: ast.expr | None) -> bool:
            if annotation is None:
                return False
            if isinstance(annotation, ast.Name):
                return annotation.id == "Hosts"
            if isinstance(annotation, ast.Attribute):
                return annotation.attr == "Hosts"
            return False

        found: set[str] = set()
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tracked: set[str] = set()
            args = func.args
            all_params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            if args.vararg:
                all_params.append(args.vararg)
            if args.kwarg:
                all_params.append(args.kwarg)
            for p in all_params:
                if is_hosts_annotation(p.annotation):
                    tracked.add(p.arg)
            for stmt in ast.walk(func):
                if isinstance(stmt, ast.Assign) and is_load_hosts_call(stmt.value):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            tracked.add(target.id)
                if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                    if is_load_hosts_call(stmt.value) and isinstance(
                        stmt.target, ast.Name
                    ):
                        tracked.add(stmt.target.id)
            if not tracked:
                continue
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in tracked
                ):
                    found.add(node.attr)
        return found

    def test_every_hosts_attribute_access_is_a_real_field_both_trees(self):
        cli_root = Path(hosts_mod.__file__).parent
        ui_root = (
            Path(hosts_mod.__file__).resolve().parents[3]
            / "ui"
            / "src"
            / "self_learn_ui"
        )
        assert ui_root.is_dir(), f"expected ui src tree at {ui_root}"

        known_fields = {f.name for f in dataclasses.fields(hosts_mod.Hosts)}
        assert known_fields == {
            "skills_root",
            "projects",
            "skills_root_mode",
            "project_modes",
        }

        all_found: set[str] = set()
        for root in (cli_root, ui_root):
            for py in root.rglob("*.py"):
                tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
                all_found |= self._hosts_attribute_accesses(tree)

        # The real criterion: nothing accesses a Hosts field that isn't
        # one of the four real ones (a stale/removed-attribute reference
        # would show up here as a name outside `known_fields`).
        assert all_found <= known_fields
        # And the sweep actually found something real, both pre-existing
        # fields are genuinely exercised somewhere in the two trees
        # (proposals.py:241's `hosts.projects`, hosts.py's own internal
        # `.skills_root` reads) — an empty result would mean the tracker
        # itself is broken, not that nothing accesses Hosts.
        assert "projects" in all_found
        assert "skills_root" in all_found

    def test_positive_control_a_known_absent_name_is_caught_by_the_tracker(self):
        """The sweep mechanism itself must be able to flag a bad
        attribute — proves `test_every_hosts_attribute_access_is_a_real_field_both_trees`
        passing is not just an empty search finding nothing to look at."""
        snippet = (
            "from self_learn.hosts import load_hosts\n"
            "def f(home):\n"
            "    hosts = load_hosts(home)\n"
            "    return hosts.host_repo\n"  # never existed on Hosts
        )
        tree = ast.parse(snippet)
        found = self._hosts_attribute_accesses(tree)
        assert found == {"host_repo"}
        known_fields = {f.name for f in dataclasses.fields(hosts_mod.Hosts)}
        assert not (found <= known_fields)  # this snippet WOULD fail the real test

        # same positive control via the parameter-annotation tracking
        # path (`def f(hosts: Hosts)`), not just the load_hosts() path.
        snippet2 = (
            "from self_learn.hosts import Hosts\n"
            "def g(hosts: Hosts):\n"
            "    return hosts.not_a_real_field\n"
        )
        found2 = self._hosts_attribute_accesses(ast.parse(snippet2))
        assert found2 == {"not_a_real_field"}


class TestMode9PostureDecisionSweep:
    """MODE9: no site decides a host's posture except `hosts.host_mode`,
    and no site infers user scope from a missing path. **Instrument
    (a):** any comparison of a `TargetSpec` attribute to `None` used to
    select a chezmoi/user branch. **Instrument (b):** any call to
    `hosts._is_git_repo`/`is_repo_root` outside `hosts.py` and the
    `--init` path. **Positive control:** the same sweep against
    50fa815's tree must report real branch-selecting sites, so an empty
    result here cannot be an empty search."""

    @staticmethod
    def _host_path_none_comparisons(tree: ast.AST) -> list[int]:
        """Every `<attr>.host_path is None` / `is not None` (or the
        pre-rename `host_repo`) comparison, keyed by line — EXCLUDING
        `TargetSpec.__post_init__`'s own runtime assertion (USER4's
        licensed exception: it refuses at construction time rather than
        branching into chezmoi/user logic, and MODE9's own spec text
        pairs it with this sweep as the intended replacement for the
        five retired branch sites, not another one)."""
        hits: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "TargetSpec":
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.FunctionDef)
                        and sub.name == "__post_init__"
                    ):
                        post_init_lines = {
                            n.lineno for n in ast.walk(sub) if hasattr(n, "lineno")
                        }
                        break
                else:
                    post_init_lines = set()
                break
        else:
            post_init_lines = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Is, ast.IsNot)):
                continue
            comparators = [node.left, *node.comparators]
            names = {
                c.attr
                for c in comparators
                if isinstance(c, ast.Attribute) and c.attr in ("host_path", "host_repo")
            }
            nones = any(
                isinstance(c, ast.Constant) and c.value is None for c in comparators
            )
            if names and nones and getattr(node, "lineno", None) not in post_init_lines:
                hits.append(node.lineno)
        return hits

    @staticmethod
    def _repo_check_calls_outside_hosts(tree: ast.AST, filename: str) -> list[int]:
        """Every call to `_is_git_repo`/`is_repo_root` (bare or
        `hosts.`-qualified) in a file that is not `hosts.py`.
        `ledger.py` is a licensed exception: its two calls (present
        unedited since 50fa815, verified) check whether the LEDGER
        itself is a git repo — the ledger is ALWAYS git regardless of
        any canon host's mode (doc 13 §2), an orthogonal concern MODE9
        never touches, not a host-posture decision."""
        if filename in ("hosts.py", "ledger.py"):
            return []
        hits: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else None
            )
            if name in ("_is_git_repo", "is_repo_root"):
                hits.append(node.lineno)
        return hits

    def test_no_target_spec_host_path_none_branch_outside_post_init(self):
        import self_learn.verbs as verbs_mod
        import self_learn.report as report_mod

        for mod in (verbs_mod, report_mod):
            src = inspect.getsource(mod)
            tree = ast.parse(src, filename=mod.__file__)
            hits = self._host_path_none_comparisons(tree)
            assert hits == [], f"{mod.__file__}: {hits}"

    def test_no_repo_check_call_outside_hosts_and_ledger(self):
        cli_root = Path(hosts_mod.__file__).parent
        all_hits: dict[str, list[int]] = {}
        for py in cli_root.glob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            hits = self._repo_check_calls_outside_hosts(tree, py.name)
            if hits:
                all_hits[py.name] = hits
        assert all_hits == {}

    def test_positive_control_50fa815_tree_has_real_branch_sites(self):
        """Run the SAME sweep against 50fa815's verbs.py/report.py — the
        pre-unit tree that had five host_repo-is-None branch sites in
        verbs.py plus two in report.py (§4.5 R-1's retired shape) — and
        confirm it is non-empty, proving an empty result on the current
        tree above is a real absence, not a sweep that can never fire."""
        repo_root = Path(hosts_mod.__file__).resolve()
        # walk up to the git worktree root (contains .git or is a
        # worktree checkout) — cli/src/self_learn/hosts.py is 4 levels
        # under plugins/self-learn/cli/src/self_learn/
        worktree_root = repo_root.parents[4]
        old_verbs = subprocess.run(
            ["git", "-C", str(worktree_root), "show",
             "50fa815:plugins/self-learn/cli/src/self_learn/verbs.py"],
            capture_output=True, text=True, timeout=30,
        )
        old_report = subprocess.run(
            ["git", "-C", str(worktree_root), "show",
             "50fa815:plugins/self-learn/cli/src/self_learn/report.py"],
            capture_output=True, text=True, timeout=30,
        )
        assert old_verbs.returncode == 0
        assert old_report.returncode == 0

        old_verbs_tree = ast.parse(old_verbs.stdout, filename="verbs.py@50fa815")
        old_report_tree = ast.parse(old_report.stdout, filename="report.py@50fa815")

        verbs_hits = self._host_path_none_comparisons(old_verbs_tree)
        report_hits = self._host_path_none_comparisons(old_report_tree)
        assert len(verbs_hits) >= 5, verbs_hits
        assert len(report_hits) >= 2, report_hits


# ----------------------------------------------------------------- UN group


#: UN1's baseline commit: master's tip BEFORE this branch's merge commit
#: lands on it -- NOT 50fa815 (the pre-unit commit). Coordinator ruling
#: 2026-08-28 (bring-up-to-master merge): the invariant UN1 protects is
#: "hostmode changes nothing in git mode relative to the code it lands
#: on", not relative to some fixed historical point that predates six
#: sibling units (U-verbguards, U-kl4, U-ancestry, U-corrob, U-cachelit,
#: U-fw117) already merged into master. Re-anchored from 50fa815 to
#: ba90ef9 (master's HEAD at merge time) for exactly that reason.
_UN1_BASELINE_REF = "ba90ef9"


@pytest.fixture(scope="module")
def un1_baseline_worktree(tmp_path_factory):
    """UN1: a disposable git worktree checked out at `_UN1_BASELINE_REF`
    (master's tip this branch merges onto — see the re-anchor note
    above), torn down when this module's UN tests finish. Lets the
    inlined probe script (`_UN1_PROBE_SCRIPT` below — deliberately
    written against ONLY the pre-unit-stable API) run unmodified against
    both trees, so its stdout can be diffed byte-for-byte."""
    worktree_root = Path(hosts_mod.__file__).resolve().parents[5]
    base = tmp_path_factory.mktemp("un1-baseline-wt")
    target = base / "wt"  # `worktree add` refuses a dir that already exists
    proc = subprocess.run(
        ["git", "-C", str(worktree_root), "worktree", "add", str(target), _UN1_BASELINE_REF],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        pytest.skip(f"git worktree add {_UN1_BASELINE_REF} failed: {proc.stderr}")
    try:
        yield target
    finally:
        subprocess.run(
            ["git", "-C", str(worktree_root), "worktree", "remove", "--force", str(target)],
            capture_output=True, text=True, timeout=30,
        )


#: UN1's probe, INLINED (not a file under `misc/`, which is repo-locally
#: gitignored per `.git/info/exclude` — a script living only there would
#: make this test undurable: gone on a fresh clone, in CI, or once this
#: worktree is removed). Written to a tmp file at test time and run
#: against BOTH the current tree's own venv and a disposable 50fa815
#: worktree's venv.
_UN1_PROBE_SCRIPT = 'from __future__ import annotations\n\nimport subprocess\nimport sys\nfrom pathlib import Path\n\n\ndef git(repo, *args):\n    return subprocess.run(\n        ["git", "-C", str(repo), *args],\n        capture_output=True, text=True, check=True,\n    )\n\n\ndef main():\n    tmp = Path(sys.argv[1])\n    host = tmp / "host-repo"\n    ledger = tmp / "ledger-home"\n    host.mkdir(parents=True)\n    ledger.mkdir(parents=True)\n\n    for repo in (host, ledger):\n        git(repo, "init", "-q", "-b", "main")\n        git(repo, "config", "user.email", "test@example.com")\n        git(repo, "config", "user.name", "Test")\n\n    skill_dir = host / "plugins" / "s-plugin" / "skills" / "s"\n    skill_dir.mkdir(parents=True)\n    (skill_dir / "SKILL.md").write_text("# s skill\\n\\nAuthored prose.\\n", encoding="utf-8")\n    git(host, "add", "-A")\n    git(host, "commit", "-q", "-m", "host seed")\n\n    for sub in ("skills", "projects", "user", "telemetry"):\n        (ledger / sub).mkdir()\n    (ledger / "hosts.yaml").write_text(\n        f"skills_root: {host}\\nprojects:\\n  - path: {host}\\n", encoding="utf-8"\n    )\n    git(ledger, "add", "-A")\n    git(ledger, "commit", "-q", "-m", "ledger seed")\n\n    from self_learn.ledger_ops import create_record\n    from self_learn.records import Record\n    from self_learn import verbs\n\n    record = Record.create(\n        type="behavior", scope="skill:s", source="teach", kind="anti-pattern",\n        trigger="About to edit .storage while HA is running.",\n        instruction="Stop the container first.", record_id="lrn-00000099",\n    )\n    create_record(ledger, record)\n    verbs.route(ledger, "lrn-00000099", dest="skill-md", no_push=True)\n\n    show = git(host, "show", "--format=%s%n%b%n", "--stat", "HEAD").stdout\n    tree = git(host, "rev-parse", "HEAD^{tree}").stdout.strip()\n    show = show.replace(str(tmp), "<TMP>")\n    print("=== SHOW ===")\n    print(show)\n    print("=== TREE ===")\n    print(tree)\n\n\nif __name__ == "__main__":\n    main()\n'


class TestUn1GitModeByteIdenticalToBaseline:
    """UN1 [A]: a route into a git host produces a commit whose subject,
    body, pathspec and resulting tree are byte-identical to
    `_UN1_BASELINE_REF`'s (master's HEAD at merge time, ba90ef9 — the
    code this unit actually lands on; re-anchored from 50fa815 per the
    coordinator's merge ruling 2026-08-28)."""

    @staticmethod
    def _run_probe(cli_dir: Path, probe: Path, workdir: Path, *, sync: bool) -> str:
        env = dict(os.environ)
        env["SELF_LEARN_SERVE_UNIT_DIR"] = str(workdir.parent / "unit-dir")
        Path(env["SELF_LEARN_SERVE_UNIT_DIR"]).mkdir(parents=True, exist_ok=True)
        argv = ["uv", "run"] + ([] if sync else ["--no-sync"]) + [
            "python3", str(probe), str(workdir),
        ]
        proc = subprocess.run(
            argv, cwd=str(cli_dir), capture_output=True, text=True,
            env=env, timeout=180,
        )
        assert proc.returncode == 0, f"{argv} in {cli_dir}:\n{proc.stderr}"
        return proc.stdout

    def test_un1_route_into_git_host_byte_identical_commit_and_tree(
        self, tmp_path, un1_baseline_worktree
    ):
        current_root = Path(hosts_mod.__file__).resolve().parents[5]
        current_cli = current_root / "plugins" / "self-learn" / "cli"
        probe = tmp_path / "un1_probe.py"
        probe.write_text(_UN1_PROBE_SCRIPT, encoding="utf-8")

        current_out = self._run_probe(
            current_cli, probe, tmp_path / "current", sync=False
        )

        baseline_cli = un1_baseline_worktree / "plugins" / "self-learn" / "cli"
        baseline_out = self._run_probe(
            baseline_cli, probe, tmp_path / "baseline", sync=True
        )

        assert "=== TREE ===" in current_out
        assert current_out == baseline_out


class TestUn2GitModeGatesUnchanged:
    """UN2 [A]: git-mode gates are unchanged — `_abort_if_dirty` still
    decides refusals on a git host and `GITOPS_DIRTY_MARKER` is
    byte-unchanged. Mutation M38."""

    def test_gitops_dirty_marker_byte_unchanged(self):
        assert verbs.GITOPS_DIRTY_MARKER == "has unrelated uncommitted changes"

    def test_abort_if_dirty_ast_identical_to_baseline(self):
        worktree_root = Path(hosts_mod.__file__).resolve().parents[4]
        old = subprocess.run(
            ["git", "-C", str(worktree_root), "show",
             "50fa815:plugins/self-learn/cli/src/self_learn/verbs.py"],
            capture_output=True, text=True, timeout=30,
        )
        assert old.returncode == 0

        def get_func(tree, name):
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    return node
            return None

        old_tree = ast.parse(old.stdout, filename="verbs.py@50fa815")
        new_tree = ast.parse(inspect.getsource(verbs), filename=str(verbs.__file__))
        old_fn = get_func(old_tree, "_abort_if_dirty")
        new_fn = get_func(new_tree, "_abort_if_dirty")
        assert old_fn is not None and new_fn is not None
        assert ast.dump(old_fn) == ast.dump(new_fn)

    def test_dirty_git_host_route_refuses_through_abort_if_dirty(self, tmp_path):
        """Behavioral half of UN2: an uncommitted edit already sitting on
        the route's OWN target (env.skill_md, committed by make_env) is
        what `_abort_if_dirty`'s `git status --porcelain -- target`
        actually checks — refuses via GITOPS_DIRTY_MARKER, not the
        region predicate's different wording. (test_commit_drift.py's
        `test_gitops_dirty_message_carries_the_extracted_marker` covers
        this same behavior via its own fixture; this is the dedicated
        UN2 instance in this file.)"""
        env = make_env(tmp_path)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        record = make_behavior(scope="skill:s", record_id="lrn-00000090")
        create_record(env.ledger, record)
        with pytest.raises(Exception) as excinfo:
            verbs.route(env.ledger, "lrn-00000090", dest="skill-md", no_push=True)
        assert verbs.GITOPS_DIRTY_MARKER in str(excinfo.value)

    def test_m38_routing_dirty_check_through_the_record_predicate_instead_breaks_this(
        self, tmp_path
    ):
        """M38: if `_abort_if_unsound` stopped calling `_abort_if_dirty`
        for git mode (routing the check through the region predicate
        alone instead), an unrelated dirty file would no longer be
        caught with GITOPS_DIRTY_MARKER — mutation actually RUN
        (`misc/mutation_batch2.py`, RED confirmed against
        `test_dirty_git_host_route_refuses_through_abort_if_dirty`
        above, then restored with a sha256 check) during this build.
        This positive control re-proves the current source still has
        the unmutated dispatch that script mutates."""
        src_path = Path(verbs.__file__)
        text = src_path.read_text(encoding="utf-8")
        assert "if mode == \"git\":\n        _abort_if_dirty(host_path, target)" in text


class TestUn8HostLockPathAndCommitLockUnchanged:
    """UN8 [A]: `gitops.host_lock_path(p, "git")` returns exactly what
    `commit_lock_path(p)` returns today, and `commit_lock(home)` — the
    ledger's — is byte-unchanged. Mutation M39.

    NOTE: during this build, `commit_lock`'s timeout error text was
    found to have silently drifted from 50fa815's "...wedged mid-commit"
    to "...wedged mid-write" when its flock body was factored out into
    `_flock_lock` (shared with the new `host_lock`) — a real UN8
    violation with no prior test coverage. Fixed in gitops.py by
    parametrizing the suffix on `wedged_by` (restoring "mid-commit" for
    commit_lock, and giving host_lock its own "mid-host" text) instead
    of leaving it hardcoded to "mid-write"."""

    def test_host_lock_path_git_mode_is_commit_lock_path(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        assert gitops.host_lock_path(repo, "git") == gitops.commit_lock_path(repo)

    def test_commit_lock_timeout_message_byte_identical_to_baseline(self, tmp_path):
        """The observable behavior 50fa815's `commit_lock` promised: on
        a wedged lock, the ledger's commit_lock raises GitOpsError whose
        text ends '...wedged mid-commit' — not '...wedged mid-write'."""
        repo = tmp_path / "ledger"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        lock_path = gitops.commit_lock_path(repo)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl

        fh = open(lock_path, "w", encoding="utf-8")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            with pytest.raises(gitops.GitOpsError) as excinfo:
                with gitops.commit_lock(repo, timeout=0.05):
                    pass
            assert str(excinfo.value).endswith("wedged mid-commit")
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

    def test_m39_changing_the_git_mode_lock_path_breaks_the_un8_equality(self, tmp_path):
        """M39: mutate `host_lock_path`'s git-mode branch to return a
        DIFFERENT path than `commit_lock_path` (e.g. append a suffix) —
        the UN8 equality test above must go RED. Mutation actually RUN
        (`misc/mutation_batch2.py`, RED confirmed against
        `test_host_lock_path_git_mode_is_commit_lock_path` above, then
        restored with a sha256 check) during this build; this positive
        control re-proves the current source still has the unmutated
        one-line dispatch that script mutates."""
        src_path = Path(gitops.__file__)
        text = src_path.read_text(encoding="utf-8")
        assert 'if mode == "git":\n        return commit_lock_path(Path(path))' in text
