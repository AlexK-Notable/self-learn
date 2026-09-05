"""U-hostmode Phase 1 — dedicated criterion tests for the MODE/REC/GATE/
PLAIN/RCN groups not already exercised by an existing or census-rewritten
test file (test_hosting.py, test_a2_rules_local.py, test_commit_drift.py,
test_resolution_evidence.py, test_verbs.py, test_lock_invariant.py, etc.
already cover UN/CD/USER/most of GATE/PLAIN).

U-hostmode Phase 2 (added at the end of this file, its own section
header): dedicated criterion tests for CHEZ1/CHEZ2/CHEZ3/CHEZ5/CHEZ6 —
the retired dotfiles-management module's wholesale deletion. The
UI-side criteria (UIC1-5) live in ui/tests/ (a separate venv this suite
cannot import).

Each test names the [A]/[B] criterion it satisfies in its docstring.
Where a criterion's own spec text names a mutation, this file's
docstring or an inline comment records the manual RED-then-restore check
performed against the source during the build (never left as an
automated self-mutating test — this codebase's discipline is a real
discriminator proven once at build time, not a mutation harness shipped
in CI).
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from self_learn import (
    cli, compiled, compilers, gitops, hosts as hosts_mod, reconcile, selfcheck, teach, verbs,
)
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
        silent preference for one flag over the other. Code gate r1
        M-4: the prior instrument named its fixture directory
        `would-be-plain`, so `match="plain.*--init|--init.*plain"`
        matched the FIXTURE NAME appearing in a completely different
        refusal (`_init_for_registration`'s own "does not exist on
        disk" error, since the directory was never created) — the
        mutation this was meant to catch was invisible. This version
        creates the directory FIRST (so that OTHER refusal cannot
        pre-empt this one), matches the LITERAL refusal text
        (`hosts.py`'s own `"--mode plain --init makes no sense"`), and
        asserts the refusal left NOTHING behind: no `.git`, no
        `.self-learn-host` marker, `hosts.yaml` byte-unchanged."""
        env = make_env(tmp_path)
        target = tmp_path / "would-be-plain"
        target.mkdir()
        hosts_yaml = env.ledger / "hosts.yaml"
        before_hosts_yaml = hosts_yaml.read_text(encoding="utf-8")
        with pytest.raises(HostsError, match="--mode plain --init makes no sense"):
            host_add(env.ledger, target, "project", mode="plain", init=True)
        assert not (target / ".git").exists()
        assert not (target / hosts_mod.MARKER_FILENAME).exists()
        assert hosts_yaml.read_text(encoding="utf-8") == before_hosts_yaml

    def test_mode_flip_reregistration_refused_git_to_plain(self, tmp_path):
        """MODE6: re-adding an already-registered host with a
        DIFFERENT mode refuses — the ruled 'set once' shape; the repair
        is `host remove` + `host add --mode`. Git-mode host flipping to
        plain: a plain target doesn't need to BE a git repo, so this
        direction alone cannot distinguish MODE6's own refusal from a
        different "not a git repo" refusal — see the git→plain
        parametrization below for that other direction, which code gate
        r1 M-11 found this file never covered."""
        env = make_env(tmp_path)
        git_host = tmp_path / "flip-host"
        init_repo(git_host)
        host_add(env.ledger, git_host, "project", mode="git")
        with pytest.raises(HostsError, match="host remove|host add.*--mode"):
            host_add(env.ledger, git_host, "project", mode="plain")
        # unchanged: still git
        assert host_mode(env.ledger, git_host) == "git"

    def test_mode_flip_reregistration_refused_plain_to_git(self, tmp_path):
        """MODE6, the other direction (code gate r1 M-11): a
        PLAIN-registered host re-added with `mode="git"` must ALSO
        refuse by naming MODE6's own repair (`host remove` + `host add
        --mode`) — never the separate "not a git repo" refusal, even
        though the plain target genuinely is not one. Pre-fold,
        `host_add` ran its git-repo-soundness check BEFORE the
        already-registered/mode-flip check, so this direction hit "is
        not a git repo" instead and never named the real repair; the
        fix reorders so the mode-flip refusal runs first, in BOTH
        directions."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "flip-host-2"
        plain_host.mkdir()  # never a git repo — the point of this case
        host_add(env.ledger, plain_host, "project", mode="plain")
        with pytest.raises(HostsError, match="host remove|host add.*--mode") as exc_info:
            host_add(env.ledger, plain_host, "project", mode="git")
        assert "not a git repo" not in str(exc_info.value)
        # unchanged: still plain
        assert host_mode(env.ledger, plain_host) == "plain"

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
        target. Code gate r1 M-1: the prior instrument computed BOTH
        sides via `compiled.region_bytes` — the record's own `sha256`
        (indirectly, through `verbs._expected_managed_region` at
        write time) AND the "read back off disk" comparison side — so a
        mutation to `region_bytes` itself (M10: hash EXCLUDING
        `END_MARKER`) moved both hashes together and stayed invisible.
        This version slices the region with a LITERAL marker pair,
        independent of `compiled.region_bytes` entirely — a real,
        from-scratch re-derivation of "what the managed region's bytes
        are", using nothing from the module under test."""
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-00000001")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-00000001", dest="skill-md", no_push=True)

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        data = compiled.load_record(env.ledger, slug)
        key = compiled.region_key(env.host, env.skill_md)
        entry = compiled.entry_for(data, key)
        assert entry is not None

        text = env.skill_md.read_text(encoding="utf-8")
        begin_marker = "<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->"
        end_marker = "<!-- self-learn:end -->"
        assert text.count(begin_marker) == 1
        assert text.count(end_marker) == 1
        begin_at = text.index(begin_marker)
        end_at = text.index(end_marker)
        # INCLUSIVE of both markers — independently re-derived, never
        # imported from `compiled.region_bytes`.
        region_bytes = text[begin_at : end_at + len(end_marker)].encode("utf-8")

        import hashlib as _hashlib

        expected_sha256 = _hashlib.sha256(region_bytes).hexdigest()
        assert entry["sha256"] == expected_sha256

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

    def test_rec8_foreign_keys_round_trip_through_ruamel(self, tmp_path):
        """REC8 (code gate r1 fold, D-4): the compile record round-trips
        foreign keys via `ruamel`'s `typ="rt"` mode -- a human
        annotation, or a future unit's own field, hand-added directly to
        the YAML file, survives being read (`load_record`) and
        re-written (`write_entry`, for a DIFFERENT target/field) without
        being lost. `write_entry` overwrites `targets[key]` as a whole
        dict for the key it is WRITING (never a merge -- REC8 makes no
        claim about a foreign sub-key surviving inside THAT SAME
        overwrite), so this proves the property at the two grains that
        DO hold: a foreign TOP-LEVEL key, and a foreign key inside a
        DIFFERENT target's entry this call never touches.

        Not mutation-tested -- the spec's own §6 exempts REC8: the
        round-trip guarantee is `ruamel`'s, not this codebase's custom
        logic, and is caught first by `records.py`'s own tests. D-4 is
        about REC8 having NO INSTRUMENT AT ALL for `compiled.py`'s own
        `write_entry`/`load_record`; this closes that gap."""
        import io

        from ruamel.yaml import YAML

        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-00000072")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-00000072", dest="skill-md", no_push=True)

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        record_path = compiled.compiled_record_path(env.ledger, slug)
        key = compiled.region_key(env.host, env.skill_md)

        y = YAML(typ="rt")
        data = y.load(record_path.read_text(encoding="utf-8"))
        assert key in data["targets"]

        # A foreign TOP-LEVEL key -- a human annotation self-learn never
        # writes and has no field name for.
        data["human_annotation"] = "hand-added note, never written by self-learn"
        # A foreign key WITHIN A DIFFERENT target's entry -- a future
        # unit's own field self-learn does not know about yet.
        other_key = "SOME/OTHER/PATH.md"
        data["targets"][other_key] = {
            "region": "managed",
            "sha256": "deadbeef",
            "based_on_sha256": None,
            "bytes": 0,
            "at": "2026-01-01T00:00:00Z",
            "by": "a future unit",
            "future_field": "unknown to this codebase",
        }
        buf = io.StringIO()
        y.dump(data, buf)
        record_path.write_text(buf.getvalue(), encoding="utf-8")

        # The round trip under test: `write_entry` for the ORIGINAL
        # target, a real field change (never a no-op).
        compiled.write_entry(
            env.ledger,
            slug,
            key,
            region="managed",
            sha256="cafebabe",
            based_on_sha256="cafebabe",
            nbytes=0,
            by="test: rec8 round-trip",
            host=str(env.host),
            mode="git",
        )

        reloaded = compiled.load_record(env.ledger, slug)
        assert (
            reloaded["human_annotation"]
            == "hand-added note, never written by self-learn"
        )
        assert (
            reloaded["targets"][other_key]["future_field"]
            == "unknown to this codebase"
        )
        # And the write actually did what it was asked -- proving this
        # is a REAL round trip, not a no-op that never touched the file.
        assert reloaded["targets"][key]["sha256"] == "cafebabe"


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
        assert ok is selfcheck.Verdict.PASS  # never gates the boolean
        assert "no compile record yet" in message
        assert "unknown provenance" in message

    def test_clean_renders_matches_its_compile_record(self, tmp_path):
        from self_learn import selfcheck

        env, plain_host = self._routed(tmp_path, "lrn-00000013")
        ok, message = selfcheck._check_drift(env.ledger)
        assert ok is selfcheck.Verdict.PASS
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
        assert ok is selfcheck.Verdict.PASS  # no OTHER check fires — isolated
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
        assert ok is selfcheck.Verdict.FAIL  # THE one verdict that gates the boolean
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
        dropped it (`report.py`'s two plain-host `continue`s, in
        `_unpathed_rules_rows` and `_rules_cofire_signal`). Check:
        register a plain host, route a `rules` record into it, assert
        the row is present in `report --json`.

        Code gate r1 M-8: the prior instrument asserted
        `str(plain_host) in json.dumps(report_json)` — but the plain
        host's path is ALREADY in the report from
        `_resolve_project_rows` (an unconditional row, per its own
        docstring: "never omitted... an omitted row is indistinguishable
        from a clean one") independent of the TWO `continue`s M45
        restores. So a whole-document substring check passed whether or
        not those two specific sites skipped the plain host. This
        version asserts on the SPECIFIC rows those two sites produce:
        an entry for the plain host in `conditional.rules_cofire.scopes`
        (`_rules_cofire_signal`'s own site), and confirms
        `_unpathed_rules_rows` (the sibling site) was consulted for it
        too — both keyed by the plain host's own project key, not by a
        path substring."""
        import json

        from self_learn import cli, report as report_mod

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

        plain_key = hosts_mod.slug_for(plain_host)[-8:]

        # (1) unit-level: both sites, called directly, must reach the
        # plain host's own project row rather than skipping it.
        user_internal = report_mod._resolve_user_claude_md_row(env.ledger)
        project_internal = report_mod._resolve_project_rows(env.ledger)
        plain_prow = next(
            (p for p in project_internal if p["key"] == plain_key), None
        )
        assert plain_prow is not None and plain_prow["spec"] is not None

        cofire_signal = report_mod._rules_cofire_signal(
            env.ledger, user_internal, project_internal
        )
        plain_scope = next(
            (s for s in cofire_signal["scopes"] if s["key"] == plain_key), None
        )
        assert plain_scope is not None, (
            "the plain host's project row never reached "
            "_rules_cofire_signal — its own `continue` (M45) skips it "
            "entirely, the exact regression this pins"
        )
        assert plain_scope["state"] == "ok"
        # a route with no `--paths` carries no `paths:` frontmatter, so
        # `_rules_cofire` files this stem under `unpathed`, not `topics`
        # (its own docstring: membership is the raw-key predicate).
        assert "infra" in plain_scope["unpathed"]

        unpathed_rows = report_mod._unpathed_rules_rows(user_internal, project_internal)
        plain_unpathed_row = next(
            (r for r in unpathed_rows if r["key"] == f"{plain_key}:infra"), None
        )
        assert plain_unpathed_row is not None, (
            "the plain host's own `unpathed-rules` row for its `infra` "
            "topic never appeared — _unpathed_rules_rows's `continue` "
            "(the sibling of M45's site) skips the plain host"
        )
        assert plain_unpathed_row["surface"] == "unpathed-rules"

        # (2) end-to-end: the full `report --json` CLI surface carries
        # the same signal through to its public JSON shape.
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["report", "--json"])
        out = buf.getvalue()
        assert rc == 0
        data = json.loads(out)
        json_scope = next(
            (
                s
                for s in data["context_budget"]["conditional"]["rules_cofire"]["scopes"]
                if s["key"] == plain_key
            ),
            None,
        )
        assert json_scope is not None
        assert json_scope["state"] == "ok"
        assert "infra" in json_scope["unpathed"]


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




class TestD3CompletionEveryVerbEveryKindResync:
    """D-3 completion (code gate r1 fold, coordinator ruling
    2026-08-28): "the compile record is a fact about bytes self-learn
    wrote, independent of both host mode and region kind — and
    independent of which verb wrote them." Six gaps closed, one test
    each: `route_direct` never resynced `reference`/`pointer` OR
    `hook`/`script` at all (not merely staleness — NO entry ever
    existed for a route landed through it); `supersede`/`graduate`
    never cleared a hook script's record entry when the script was
    removed (a stale WRITE entry surviving a legitimate removal); and
    `recompile`'s own two hook loops (re-apply, removal-repair) never
    resynced either. All six now funnel through the SAME
    `_resync_region_entry` helper every other region write already
    uses (`route`'s own reference/pointer/hook blocks, `recompile`'s
    managed and reference/pointer legs)."""

    def test_route_direct_reference_covers_reference_and_pointer(self, tmp_path):
        env = make_env(tmp_path)
        record = make_behavior(scope="skill:s", record_id="lrn-000000d0")
        result = verbs.route_direct(env.ledger, record, dest="reference", no_push=True)
        assert result is not None

        from self_learn.compilers import reference_target_path

        ref_path = reference_target_path(env.skill_dir / "references")
        assert ref_path.is_file()
        ref_text = ref_path.read_text(encoding="utf-8")
        assert "lrn-000000d0" in ref_text

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        data = compiled.load_record(env.ledger, slug)
        ref_key = compiled.region_key(env.host, ref_path)
        ref_entry = compiled.entry_for(data, ref_key)
        assert ref_entry is not None, "route_direct wrote NO reference record entry at all"
        assert ref_entry["region"] == "reference"
        ref_region = compiled.region_bytes(ref_text, "reference")
        assert ref_region is not None
        assert ref_entry["sha256"] == compiled.sha256_hex(ref_region)

        pointer_surface = env.skill_md
        pointer_text = pointer_surface.read_text(encoding="utf-8")
        pointer_key = compiled.region_key(env.host, pointer_surface)
        pointer_entry = compiled.entry_for(data, pointer_key)
        assert pointer_entry is not None, "route_direct wrote NO pointer record entry at all"
        assert pointer_entry["region"] == "pointer"
        pointer_region = compiled.region_bytes(pointer_text, "pointer")
        assert pointer_region is not None
        assert pointer_entry["sha256"] == compiled.sha256_hex(pointer_region)

    def test_route_direct_hook_covers_script(self, tmp_path):
        env = make_env(tmp_path)
        (env.ledger / "config.yaml").write_text(
            "one_motion_route:\n  hook: true\n", encoding="utf-8"
        )
        rid = "lrn-000000d1"
        record = make_behavior(scope="skill:s", record_id=rid)
        hook_input = {
            "rationale": "deterministic guard; over-block: denies stopped-container edits too",
            "alternates": ["skill-md"],
            "hook": {
                "tools": ["Edit", "Write"],
                "path_regex": r"\.storage/",
                "deny_message": "stop the container first",
            },
            "examples": {
                "allow": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/config.yaml"}},
                    {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
                ],
                "deny": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                    {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/b"}},
                ],
            },
        }
        result = verbs.route_direct(
            env.ledger, record, dest="hook", hook_input=hook_input, no_push=True
        )
        assert result is not None
        rel = record.routing["hook"]["script_path"]
        script = env.host / rel
        assert script.is_file()
        script_text = script.read_text(encoding="utf-8")

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        data = compiled.load_record(env.ledger, slug)
        key = compiled.region_key(env.host, script)
        entry = compiled.entry_for(data, key)
        assert entry is not None, "route_direct wrote NO script record entry at all"
        assert entry["region"] == "script"
        region = compiled.region_bytes(script_text, "script")
        assert region is not None
        assert entry["sha256"] == compiled.sha256_hex(region)

    def test_supersede_clears_the_script_record_entry(self, tmp_path):
        env = make_env(tmp_path)
        rid = "lrn-000000d2"
        trigger = "About to edit .storage while HA is running."
        record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
        create_record(env.ledger, record)
        write_proposal(
            env.ledger,
            rid,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.ledger, rid)
        verbs.route(env.ledger, rid, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = env.host / "plugins" / "s-plugin" / "hooks" / script_name(rid, trigger)
        assert script.is_file()

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, script)
        before_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert before_entry is not None
        assert before_entry["region"] == "script"

        new_id = "lrn-000000d3"
        new_record = make_behavior(scope="skill:s", record_id=new_id)
        create_record(env.ledger, new_record)
        verbs.supersede(env.ledger, rid, new_id)

        assert not script.exists()
        after_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after_entry is None, (
            "stale script record entry survives supersede's hook removal"
        )

    def test_graduate_clears_the_script_record_entry(self, tmp_path):
        env = make_env(tmp_path)
        rid = "lrn-000000d4"
        trigger = "About to edit .storage while HA is running."
        record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
        create_record(env.ledger, record)
        write_proposal(
            env.ledger,
            rid,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.ledger, rid)
        verbs.route(env.ledger, rid, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = env.host / "plugins" / "s-plugin" / "hooks" / script_name(rid, trigger)
        assert script.is_file()

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, script)
        before_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert before_entry is not None

        verbs.graduate(env.ledger, rid)

        assert not script.exists()
        after_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after_entry is None, (
            "stale script record entry survives graduate's hook removal"
        )

    def test_recompile_reapply_resyncs_the_script_record(self, tmp_path):
        env = make_env(tmp_path)
        rid = "lrn-000000d5"
        trigger = "About to edit .storage while HA is running."
        record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
        create_record(env.ledger, record)
        write_proposal(
            env.ledger,
            rid,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.ledger, rid)
        verbs.route(env.ledger, rid, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = env.host / "plugins" / "s-plugin" / "hooks" / script_name(rid, trigger)
        approved_bytes = script.read_bytes()
        assert script.is_file()

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, script)

        # Corrupt BOTH disk and the record to a WRONG, self-consistent
        # state -- the SAME discrimination requirement the reference/
        # pointer D-3 test needed: if the record already matched the
        # reconstructed (approved) bytes, this test would pass even
        # with the fix deleted.
        wrong_text = "#!/bin/sh\necho corrupted\n"
        script.write_text(wrong_text, encoding="utf-8")
        commit_all(env.host, "hand-edit script to corrupted content")
        wrong_region = wrong_text.encode("utf-8")
        compiled.write_entry(
            env.ledger,
            slug,
            key,
            region="script",
            sha256=compiled.sha256_hex(wrong_region),
            based_on_sha256=compiled.sha256_hex(wrong_region),
            nbytes=len(wrong_region),
            by="test setup: corrupt record",
            host=str(env.host),
            mode="git",
        )
        git(env.ledger, "add", "-A")
        git(env.ledger, "commit", "-m", "test setup: corrupt record")

        verbs.recompile(env.ledger, no_push=True)

        assert script.read_bytes() == approved_bytes
        approved_sha = compiled.sha256_hex(approved_bytes)
        after_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after_entry is not None
        assert after_entry["sha256"] == approved_sha, (
            "the compile record was not resynced after recompile's "
            "hook re-apply — it still points at stale/corrupted bytes"
        )
        assert compiled.verdict_for(after_entry, approved_sha) == "clean"

    def test_recompile_removal_repair_clears_the_script_record(self, tmp_path):
        env = make_env(tmp_path)
        rid = "lrn-000000d6"
        trigger = "About to edit .storage while HA is running."
        record = make_behavior(scope="skill:s", record_id=rid, trigger=trigger)
        create_record(env.ledger, record)
        write_proposal(
            env.ledger,
            rid,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.ledger, rid)
        verbs.route(env.ledger, rid, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = env.host / "plugins" / "s-plugin" / "hooks" / script_name(rid, trigger)
        approved_bytes = script.read_bytes()

        new_id = "lrn-000000d7"
        new_record = make_behavior(scope="skill:s", record_id=new_id)
        create_record(env.ledger, new_record)
        verbs.supersede(env.ledger, rid, new_id)
        assert not script.exists()

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, script)
        # supersede's own fix (this same D-3 completion) already
        # cleared the entry -- confirm the setup, then re-strand it so
        # THIS recompile call's own clear is what is actually verified.
        assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is None

        # "an interrupted removal (or a pre-fix retirement) left the
        # guard on disk" -- the loop's own docstring. Hand-recreate
        # BOTH the script and a stale-but-plausible record entry.
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_bytes(approved_bytes)
        script.chmod(script.stat().st_mode | 0o755)
        commit_all(env.host, "simulate an interrupted hook removal")
        compiled.write_entry(
            env.ledger,
            slug,
            key,
            region="script",
            sha256=compiled.sha256_hex(approved_bytes),
            based_on_sha256=compiled.sha256_hex(approved_bytes),
            nbytes=len(approved_bytes),
            by="test setup: simulate stranded entry",
            host=str(env.host),
            mode="git",
        )
        git(env.ledger, "add", "-A")
        git(env.ledger, "commit", "-m", "test setup: simulate stranded record entry")

        verbs.recompile(env.ledger, no_push=True)

        assert not script.exists()
        after_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after_entry is None, (
            "stale script record entry survives recompile's removal repair"
        )



class TestD3CompletionSupersedesCompletionClearsHookRecord:
    """D-3 completion, round 2 (found auditing the walker below): `route`
    and `route_direct`'s own `--supersedes` completion leg is
    functionally the SAME retirement `supersede()` does standalone —
    same gap (a hook-routed old record's script entry survived its own
    removal), same fix, at the `old_retire.removal is not None` branch
    right next to each verb's existing managed-retirement branch."""

    def test_route_supersedes_completion_clears_old_hook_script_record(
        self, tmp_path
    ):
        env = make_env(tmp_path)
        old_id = "lrn-000000d8"
        trigger = "About to edit .storage while HA is running."
        old_record = make_behavior(scope="skill:s", record_id=old_id, trigger=trigger)
        create_record(env.ledger, old_record)
        write_proposal(
            env.ledger,
            old_id,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.ledger, old_id)
        verbs.route(env.ledger, old_id, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = env.host / "plugins" / "s-plugin" / "hooks" / script_name(
            old_id, trigger
        )
        assert script.is_file()

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, script)
        before_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert before_entry is not None

        new_id = "lrn-000000d9"
        new_record = make_behavior(scope="skill:s", record_id=new_id)
        new_record.set_supersedes(old_id)
        create_record(env.ledger, new_record)
        verbs.route(env.ledger, new_id, dest="skill-md", no_push=True)

        assert not script.exists()
        after_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after_entry is None, (
            "stale script record entry survives route's --supersedes "
            "completion hook removal"
        )

    def test_route_direct_supersedes_completion_clears_old_hook_script_record(
        self, tmp_path
    ):
        env = make_env(tmp_path)
        old_id = "lrn-000000da"
        trigger = "About to edit .storage while HA is running."
        old_record = make_behavior(scope="skill:s", record_id=old_id, trigger=trigger)
        create_record(env.ledger, old_record)
        write_proposal(
            env.ledger,
            old_id,
            proposal_dict(
                scope="skill:s",
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.ledger, old_id)
        verbs.route(env.ledger, old_id, dest="hook", no_push=True)

        from self_learn.hook_compiler import script_name

        script = env.host / "plugins" / "s-plugin" / "hooks" / script_name(
            old_id, trigger
        )
        assert script.is_file()

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, script)
        before_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert before_entry is not None

        new_record = make_behavior(scope="skill:s", record_id="lrn-000000db")
        new_record.set_supersedes(old_id)
        result = verbs.route_direct(
            env.ledger, new_record, dest="skill-md", no_push=True
        )
        assert result is not None

        assert not script.exists()
        after_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after_entry is None, (
            "stale script record entry survives route_direct's "
            "--supersedes completion hook removal"
        )


class TestD3RegionResyncCoverageWalker:
    """D-3 completion's own structural backstop (coordinator's fold-2
    ruling): "a walker/AST check that every region-writing call site is
    followed by the re-sync (positive control: the shipped sites)".

    The 8 gap-closing tests above each mutation-verify ONE specific fix
    site and prove it is load-bearing — that is the strong claim. This
    class is the complementary, WEAKER-but-broader claim: parse verbs.py
    fresh (never `inspect`, so a stale `.pyc` cannot lie) and check, for
    every verb that can write a managed/reference/pointer/script region,
    that its own body carries a `_resync_region_entry` (or the managed-
    only convenience wrappers `_write_compile_record_entry` /
    `_write_retirement_compile_record`) call for every kind it can write
    — so a FUTURE regression that deletes a resync call without deleting
    the test file gets caught even if nobody writes a dedicated mutation
    test for it.

    Two legs:

    (a) kind coverage — per verb, the SET of region kinds reachable
        through its own write-delegating calls (`_host_phase`,
        `_retirement_host_phase`, `_apply_target`, `_remove_hook_script`,
        `compile_reference`, `apply_pointer`, `_write_hook_script`) must
        be a subset of the SET of kinds it resyncs.
    (b) multi-leg count — the three known TWO-LEG cases (route's and
        route_direct's own-hook-write leg + old-hook-retirement leg;
        recompile's hook-reapply leg + removal-repair leg) must show
        (at least) two separate `region_kind="script"` resync call
        sites, not one shared between both branches.

    Positive control: this class asserts the CURRENT shipped shape
    passes both legs for route, route_direct, supersede, graduate, and
    recompile — a walker that could not confirm the fixed code is not
    proof of anything.
    """

    @staticmethod
    def _verbs_tree() -> ast.Module:
        src = (
            Path(__file__).resolve().parents[1]
            / "src" / "self_learn" / "verbs.py"
        ).read_text(encoding="utf-8")
        return ast.parse(src)

    @staticmethod
    def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"verbs.py defines no function {name!r}")

    @staticmethod
    def _callee_name(call: ast.Call) -> str | None:
        f = call.func
        if isinstance(f, ast.Attribute):
            return f.attr
        if isinstance(f, ast.Name):
            return f.id
        return None

    @classmethod
    def _calls_named(cls, func: ast.FunctionDef, names: tuple[str, ...]) -> list[ast.Call]:
        return [
            n for n in ast.walk(func)
            if isinstance(n, ast.Call) and cls._callee_name(n) in names
        ]

    @classmethod
    def _resync_kinds(cls, func: ast.FunctionDef) -> set[str]:
        """Every region kind `func`'s OWN body resyncs — via a literal
        `region_kind="..."` keyword on a `_resync_region_entry` call, or
        implicitly "managed" via the two managed-only convenience
        wrappers that never took a `region_kind` param at all."""
        kinds: set[str] = set()
        for n in ast.walk(func):
            if not isinstance(n, ast.Call):
                continue
            name = cls._callee_name(n)
            if name == "_resync_region_entry":
                for kw in n.keywords:
                    if kw.arg == "region_kind" and isinstance(kw.value, ast.Constant):
                        kinds.add(kw.value.value)
            elif name in ("_write_compile_record_entry", "_write_retirement_compile_record"):
                kinds.add("managed")
        return kinds

    @classmethod
    def _resync_calls_of_kind(cls, func: ast.FunctionDef, kind: str) -> list[ast.Call]:
        hits: list[ast.Call] = []
        for n in ast.walk(func):
            if not isinstance(n, ast.Call) or cls._callee_name(n) != "_resync_region_entry":
                continue
            for kw in n.keywords:
                if kw.arg == "region_kind" and isinstance(kw.value, ast.Constant) and kw.value.value == kind:
                    hits.append(n)
        return hits

    # -- leg (a): kind coverage, per verb ------------------------------

    #: N-7 (code gate r2 fold): hand-written per-verb rows -- there is no
    #: mechanical way to derive "which kinds THIS verb can write" from
    #: `verbs.py`'s AST alone (that IS what the rest of this walker
    #: exists to check). What CAN be derived, and is (the test right
    #: below this table): the UNION of every row's `expected_kinds` must
    #: equal `compiled.REGION_KINDS` exactly, so a fifth region kind
    #: added to that enum without a matching row here reddens the table
    #: itself, not just silently under-covers it.
    _KIND_COVERAGE_TABLE = [
        (
            "route",
            ("_host_phase", "_retirement_host_phase"),
            frozenset({"managed", "reference", "pointer", "script"}),
        ),
        (
            "route_direct",
            ("_host_phase", "_retirement_host_phase"),
            frozenset({"managed", "reference", "pointer", "script"}),
        ),
        (
            "supersede",
            ("_host_phase", "_remove_hook_script"),
            frozenset({"managed", "script"}),
        ),
        (
            "graduate",
            ("_retirement_host_phase",),
            frozenset({"managed", "script"}),
        ),
        (
            "recompile",
            (
                "_host_phase", "_apply_target", "compile_reference",
                "apply_pointer", "_write_hook_script", "_remove_hook_script",
            ),
            frozenset({"managed", "reference", "pointer", "script"}),
        ),
    ]

    def test_kind_coverage_table_accounts_for_every_region_kind_the_code_defines(
        self,
    ):
        """N-7 (code gate r2): the control for `_KIND_COVERAGE_TABLE`
        above going STALE — a region kind added to (or removed from)
        `compiled.REGION_KINDS` without a matching update to the table's
        rows reddens THIS test, before it can silently under-cover the
        walker below."""
        covered: set[str] = set()
        for _verb_name, _delegates_to, expected_kinds in self._KIND_COVERAGE_TABLE:
            covered |= expected_kinds
        assert covered == set(compiled.REGION_KINDS), (
            f"_KIND_COVERAGE_TABLE's rows cover {sorted(covered)} but "
            f"compiled.REGION_KINDS is {sorted(compiled.REGION_KINDS)} — "
            "a region kind was added to (or removed from) the enum "
            "without updating every row that should now name it"
        )

    @pytest.mark.parametrize(
        ("verb_name", "delegates_to", "expected_kinds"), _KIND_COVERAGE_TABLE
    )
    def test_every_write_delegating_verb_resyncs_every_kind_it_can_write(
        self, verb_name, delegates_to, expected_kinds
    ):
        tree = self._verbs_tree()
        func = self._find_func(tree, verb_name)

        # positive control: the verb must actually call at least one of
        # its declared write-delegates, or this parametrization no
        # longer describes the shipped source and the check below would
        # be vacuous rather than a real coverage proof.
        called = {name for name in delegates_to if self._calls_named(func, (name,))}
        assert called, (
            f"{verb_name}: none of {delegates_to} are called anywhere in "
            f"its body — this test's delegate list is stale against the "
            "shipped source, fix the parametrization"
        )

        resynced = self._resync_kinds(func)
        missing = expected_kinds - resynced
        assert not missing, (
            f"{verb_name}: can write region kind(s) {sorted(missing)} "
            f"(via {sorted(called)}) but its own body resyncs only "
            f"{sorted(resynced)} — a `_resync_region_entry(..., "
            f"region_kind=...)` call for {sorted(missing)} is missing "
            "(D-3 completion: every verb writing a region kind must "
            "resync that region's record entry in its own body)"
        )

    # -- leg (b): multi-leg kinds get one resync call PER leg ----------

    @pytest.mark.parametrize(
        ("verb_name", "kind", "min_call_sites", "legs"),
        [
            ("route", "script", 2, "own hook write + old-hook-retirement (--supersedes)"),
            ("route_direct", "script", 2, "own hook write + old-hook-retirement (--supersedes)"),
            ("recompile", "script", 2, "hook re-apply + hook removal-repair"),
        ],
    )
    def test_multi_leg_kinds_have_a_separate_resync_call_per_leg(
        self, verb_name, kind, min_call_sites, legs
    ):
        tree = self._verbs_tree()
        func = self._find_func(tree, verb_name)
        calls = self._resync_calls_of_kind(func, kind)
        assert len(calls) >= min_call_sites, (
            f"{verb_name}: expected at least {min_call_sites} separate "
            f"`_resync_region_entry(..., region_kind={kind!r})` call "
            f"sites — one per write leg ({legs}) — but found only "
            f"{len(calls)} at line(s) {[c.lineno for c in calls]}"
        )


class TestD2ResyncExpectedNoneWithoutDeleteIsANoOp:
    """D-2 (code gate r2): `_resync_region_entry(expected=None)` used to
    delete any existing entry unconditionally. That conflated two
    different callers — a DELIBERATE removal (a hook script just
    disappeared) and a PREDICTIVE leg with genuinely nothing to predict
    YET (`_expected_reference_region`/`_expected_pointer_region`
    returning `None` for a named reference file that does not exist
    yet — a first route to it, before the file is ever written).
    Deletion is now an explicit `delete=True`; `expected=None` alone is
    a true no-op. Both rows tested directly against the helper — the
    smallest surface that actually discriminates the two."""

    @staticmethod
    def _seed_entry(env, host_path, scope_kind="project", mode="plain"):
        key = compiled.region_key(host_path, host_path / "REFERENCE.md")
        slug = verbs.host_slug(env.ledger, host_path, scope_kind=scope_kind)
        compiled.write_entry(
            env.ledger, slug, key,
            region="reference", sha256="a" * 64, based_on_sha256=None,
            nbytes=123, by="test-seed", host=str(host_path), mode=mode,
        )
        return key, slug

    def test_delete_true_removes_an_existing_entry(self, tmp_path):
        env = make_env(tmp_path)
        host_path = tmp_path / "d2-host"
        host_path.mkdir()
        host_add(env.ledger, host_path, "project", mode="plain")
        key, slug = self._seed_entry(env, host_path)
        assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is not None

        result = verbs._resync_region_entry(
            env.ledger,
            host_path=host_path,
            scope_kind="project",
            mode="plain",
            target=host_path / "REFERENCE.md",
            region_kind="reference",
            expected=None,
            observed_hash=None,
            by="test-delete",
            delete=True,
        )
        assert result is not None
        assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is None, (
            "delete=True must still remove an existing entry"
        )

    def test_expected_none_without_delete_leaves_an_existing_entry_untouched(
        self, tmp_path
    ):
        """The D-2 row: a NAMED reference file that does not exist YET
        computes `expected=None` (nothing to predict) — this must NOT
        erase an entry that (for whatever reason — a prior write, a
        hand-recovered record) already exists for that same key."""
        env = make_env(tmp_path)
        host_path = tmp_path / "d2-host-no-delete"
        host_path.mkdir()
        host_add(env.ledger, host_path, "project", mode="plain")
        key, slug = self._seed_entry(env, host_path)
        before = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert before is not None

        result = verbs._resync_region_entry(
            env.ledger,
            host_path=host_path,
            scope_kind="project",
            mode="plain",
            target=host_path / "REFERENCE.md",
            region_kind="reference",
            expected=None,  # "nothing to predict yet" -- NOT a removal
            observed_hash=None,
            by="test-no-delete",
        )
        assert result is None, (
            "expected=None without delete=True must be a true no-op — "
            "returning a path here would mean something was WRITTEN"
        )
        after = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert after == before, (
            "expected=None without delete=True erased an existing entry "
            "— D-2's exact defect: a predictive leg with nothing to "
            "predict yet must never be indistinguishable from a "
            "deliberate removal"
        )


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
        """REC13: two consecutive `_HOST_PHASE_ERRORS`, with the region
        ALREADY on disk from an earlier successful landing, still
        verdict `stale` — never `missing` (that is a DIFFERENT row of
        the six-case table: region absent) and never `edited` — and a
        plain `recompile` repairs once the host phase recovers.

        Code gate r1 M-2: the prior instrument's failures happened
        against a target that had NEVER successfully landed, so the
        region was ABSENT on disk throughout — `verdict_for(entry,
        None) == "missing"` (REC5's row 4), not REC13's `stale` row at
        all. M47 (redefining `based_on_sha256` as the PREVIOUS
        expectation, `verbs.py:588-590`, instead of the fresh pre-flight
        OBSERVED hash) is invisible against an absent region because
        `verdict_for` short-circuits to `"missing"` the instant
        `observed_hash is None`, before `based_on_sha256` is ever
        consulted. This version lands generation 1 for real FIRST (a
        second record's route into the SAME plain `claude-md` target —
        the accumulate-in-one-region shape), so BOTH failures below
        happen with a REAL region on disk the whole time, giving
        `based_on_sha256` something to matter against."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "rec13-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")

        # generation 1: a REAL, successful landing — the region exists
        # on disk from here on, for the rest of this test.
        rec1 = make_behavior(scope="project", record_id="lrn-00000006")
        create_record(env.ledger, rec1, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000006", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        gen1_text = target.read_text(encoding="utf-8")
        gen1_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert gen1_entry is not None

        import self_learn.verbs as verbs_mod

        def _boom(*a, **kw):
            raise verbs_mod.CompileError("simulated host-phase failure")

        monkeypatch.setattr(verbs_mod, "_apply_target", _boom)

        # failure #1: a SECOND record routes to the SAME target — the
        # ledger commits (entry updated: `sha256` := gen-2's EXPECTED
        # hash, `based_on_sha256` := the hash OBSERVED just now, i.e.
        # gen-1's still-on-disk bytes) — but the host phase fails, so
        # disk stays at gen 1.
        rec2 = make_behavior(scope="project", record_id="lrn-00000061")
        create_record(env.ledger, rec2, project_path=plain_host)
        result1 = verbs.route(env.ledger, "lrn-00000061", dest="claude-md", no_push=True)
        assert result1.commit_sha
        assert any("HOST PHASE FAILED" in w for w in result1.warnings)
        assert target.read_text(encoding="utf-8") == gen1_text  # write never landed

        # failure #2 (REC13's own "two consecutive" wording): a THIRD
        # record routes to the SAME target, host phase still down. This
        # is the discriminating step — M47's bug reads `based_on_sha256`
        # off the PREVIOUS entry's `sha256` (gen-2's never-landed
        # EXPECTED hash) instead of freshly observing disk (still gen 1)
        # again; only a SECOND failure exposes it, since the first
        # failure's `based_on_sha256` happens to equal the correct value
        # under BOTH the fix and the bug (both read it off gen 1).
        rec3 = make_behavior(scope="project", record_id="lrn-00000062")
        create_record(env.ledger, rec3, project_path=plain_host)
        result2 = verbs.route(env.ledger, "lrn-00000062", dest="claude-md", no_push=True)
        assert result2.commit_sha
        assert any("HOST PHASE FAILED" in w for w in result2.warnings)
        assert target.read_text(encoding="utf-8") == gen1_text  # still never landed

        entry_after_2_failures = compiled.entry_for(
            compiled.load_record(env.ledger, slug), key
        )
        assert entry_after_2_failures is not None
        observed_now = compiled.sha256_hex(
            compiled.region_bytes(target.read_text(encoding="utf-8"), "managed")
        )
        assert (
            compiled.verdict_for(entry_after_2_failures, observed_now) == "stale"
        ), (
            "expected `stale` (region on disk matches `based_on_sha256`, "
            "the last real observation) — got something else, which is "
            "exactly M47's false-refusal shape if it reads `edited`"
        )

        # now let the host phase succeed — recompile REPAIRS (a `stale`
        # verdict, unlike `edited`, never refuses).
        monkeypatch.undo()
        final = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in final.warnings)
        entry2 = next((e for e in final.entries if e.target == target), None)
        assert entry2 is not None and entry2.changed
        final_text = target.read_text(encoding="utf-8")
        assert "lrn-00000006" in final_text
        assert "lrn-00000061" in final_text
        assert "lrn-00000062" in final_text


class TestUser5CompileRecordSlugAndLabel:
    def test_user_scope_compile_record_keyed_user_slug_and_label(
        self, tmp_path, monkeypatch
    ):
        """USER5 (code gate r1 fold M-9): a user-scope route writes a
        compile record at `<home>/compiled/user.yaml` (the literal
        `"user"` slug, `hosts.host_slug`'s own dedicated branch — never
        `hosts.slug_for`'s path-derived shape, since `~/.claude` is not
        registered in `hosts.yaml` at all, §4.8/USER3), with a `host:`
        label reading the literal `"(user scope — ~/.claude)"` and
        `mode: plain`.

        Prior to this test, NOTHING asserted on either half: M43
        (deleting `host_slug`'s `if scope_kind == "user": return "user"`
        branch) and a supporting probe (replacing the literal label with
        `str(spec.host_path)`) both stayed GREEN across the whole suite
        — 162 passed either way."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", target)

        env = make_env(tmp_path)
        record = make_behavior(scope="user", record_id="lrn-00000063")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-00000063", dest="claude-md", no_push=True)

        record_path = compiled.compiled_record_path(env.ledger, "user")
        assert record_path.is_file(), (
            "no compile record at <home>/compiled/user.yaml — the "
            '"user" slug (hosts.host_slug\'s dedicated branch) was not '
            "used to key it"
        )

        data = compiled.load_record(env.ledger, "user")
        key = compiled.region_key(target.parent, target)
        entry = compiled.entry_for(data, key)
        assert entry is not None
        # `host`/`mode` are top-level fields on the WHOLE record file
        # (one host per slug), not per-target entry fields.
        assert data["host"] == "(user scope — ~/.claude)"
        assert data["mode"] == "plain"

    def test_deleting_the_user_slug_branch_breaks_the_record_path(
        self, tmp_path, monkeypatch
    ):
        """M43's own mutation (delete `hosts.host_slug`'s
        `scope_kind == "user"` branch, falling through to
        `slug_for(path)`), applied directly against `host_slug` here
        rather than restored-after-probe in `verbs.py` — confirms the
        `"user"` slug asserted in the test above is load-bearing, not
        incidental: under this mutation, NO record lands at the `"user"`
        slug path at all."""
        target = tmp_path / "dot-claude-2" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", target)

        env = make_env(tmp_path)
        record = make_behavior(scope="user", record_id="lrn-00000064")
        create_record(env.ledger, record)

        def _m43_host_slug(home, path, *, scope_kind=None):
            # the M43 shape: fall through to slug_for regardless of
            # scope_kind, as if the "user" branch had been deleted.
            del scope_kind
            return hosts_mod.slug_for(path)

        monkeypatch.setattr(verbs, "host_slug", _m43_host_slug)
        verbs.route(env.ledger, "lrn-00000064", dest="claude-md", no_push=True)

        user_record_path = compiled.compiled_record_path(env.ledger, "user")
        assert not user_record_path.is_file(), (
            f"expected no record at the 'user' slug under M43's mutation, "
            f"but found one at {user_record_path} — the mutation did not "
            "actually take effect against this call path"
        )


class TestN8SelfcheckHonoursUserClaudeMdOverride:
    def test_managed_host_for_honours_user_claude_md_override(self, tmp_path):
        """N-8 (code gate r1 fold): `selfcheck._managed_host_for` honours
        the SAME test/route-time `user_claude_md` override every other
        user-scope resolution site in this codebase threads
        (`verbs.managed_target_for`, `_resolve_target`). Pre-fold, this
        was the one site that hardcoded `DEFAULT_USER_CLAUDE_MD` with no
        way to override it — a caller sandboxing every OTHER user-scope
        resolution still had this one silently resolve against the
        operator's real `~/.claude/CLAUDE.md`."""
        from self_learn import selfcheck
        from self_learn.ledger import Bucket

        override = tmp_path / "sandboxed-claude-dir" / "CLAUDE.md"
        bucket = Bucket(path=tmp_path / "user", scope="user", name="user")
        record = make_behavior(scope="user", record_id="lrn-00000065")

        host = selfcheck._managed_host_for(
            tmp_path, bucket, record, user_claude_md=override
        )
        assert host == override.parent

        # default (no override) stays byte-identical to pre-fold: the
        # real DEFAULT_USER_CLAUDE_MD's own parent.
        host_default = selfcheck._managed_host_for(tmp_path, bucket, record)
        assert host_default == verbs.DEFAULT_USER_CLAUDE_MD.expanduser().parent

    def test_check_drift_threads_the_override_down_to_managed_host_for(
        self, tmp_path, monkeypatch
    ):
        """`_check_drift`'s own new keyword-only parameter reaches
        `_managed_host_for` — a PROJECT-scope record (not user-scope)
        is used here so the entry-marker check upstream of
        `_managed_host_for` succeeds normally (`_target_for`'s OWN
        resolution never depends on `user_claude_md`, unlike
        `_managed_host_for`'s), letting the override's actual VALUE be
        observed reaching the call, not merely its presence in a
        signature."""
        from self_learn import selfcheck

        env = make_env(tmp_path)
        override = tmp_path / "sandboxed-claude-dir-2" / "CLAUDE.md"
        record = make_behavior(scope="skill:s", record_id="lrn-00000066")
        create_record(env.ledger, record)
        verbs.route(env.ledger, "lrn-00000066", dest="skill-md", no_push=True)

        captured: list[Path | str | None] = []
        real = selfcheck._managed_host_for

        def spy(home, bucket, record, *, user_claude_md=None):
            captured.append(user_claude_md)
            return real(home, bucket, record, user_claude_md=user_claude_md)

        monkeypatch.setattr(selfcheck, "_managed_host_for", spy)
        ok, reason = selfcheck._check_drift(env.ledger, user_claude_md=override)
        assert ok is selfcheck.Verdict.PASS, reason
        assert captured, "the drift loop never reached _managed_host_for at all"
        assert all(c == override for c in captured), (
            f"_check_drift did not thread its own user_claude_md kwarg "
            f"down to _managed_host_for: captured {captured!r}"
        )


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

    def test_git_target_render_after_ledger_change_writes_and_resyncs(
        self, tmp_path
    ):
        """D-2 (code gate r1 fold): the SAME residual-defect fix as
        `test_clean_plain_target_render_after_ledger_change_writes_and_resyncs`
        above, but for a GIT-mode target. Pre-fold, `recompile`'s git
        leg committed the HOST's render but never touched the compile
        record at all — `edited` refuses in BOTH modes (REC2/REC4), so
        a stale record on a git host is the exact same latent
        false-refusal channel the plain leg's fix closed there."""
        env = make_env(tmp_path)
        rec1 = make_behavior(scope="skill:s", record_id="lrn-00000067")
        create_record(env.ledger, rec1)
        verbs.route(env.ledger, "lrn-00000067", dest="skill-md", no_push=True)

        target = env.skill_md
        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        key = compiled.region_key(env.host, target)
        before_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert before_entry is not None
        before_text = target.read_text(encoding="utf-8")

        rec2 = make_behavior(scope="skill:s", record_id="lrn-00000068")
        create_record(env.ledger, rec2)
        verbs.route(env.ledger, "lrn-00000068", dest="skill-md", no_push=True)
        after_route_entry = compiled.entry_for(
            compiled.load_record(env.ledger, slug), key
        )
        assert after_route_entry is not None
        assert after_route_entry["sha256"] != before_entry["sha256"]
        after_route_text = target.read_text(encoding="utf-8")
        assert after_route_text != before_text

        # hand-edit back to the STALE (rec1-only) content, `--adopt`
        # freezes the record to match it (mode-agnostic per REC4), then
        # a plain `recompile` call (no `--adopt`) must both rewrite the
        # git host's target AND resync the record — never leave them
        # disagreeing.
        target.write_text(before_text, encoding="utf-8")
        commit_all(env.host, "hand-edit back to stale content")
        adopt_result = verbs.recompile(env.ledger, no_push=True, adopt=target)
        assert not any("edited" in w for w in adopt_result.warnings)

        resync_result = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in resync_result.warnings)
        final_text = target.read_text(encoding="utf-8")
        assert final_text == after_route_text
        final_entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert final_entry is not None
        final_region = compiled.region_bytes(final_text, "managed")
        assert final_region is not None
        final_observed = compiled.sha256_hex(final_region)
        assert final_entry["sha256"] == final_observed, (
            "the compile record was not resynced after the git leg's "
            "render — it still points at stale bytes"
        )
        assert compiled.verdict_for(final_entry, final_observed) == "clean"

        # never-falsely-refuses-again invariant.
        third = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in third.warnings)
        assert target.read_text(encoding="utf-8") == final_text

    def test_resync_commit_subject_names_the_host_by_subject_name_never_a_path(
        self, tmp_path
    ):
        """M-10 (code gate r1 fold): §4.5/gate B-3 rejected a second
        ledger commit under the subject `self-learn: compile record …`
        — that shape must stay rejected even though the resync commit
        itself is legitimate (the render above happens OUTSIDE
        `route`'s own commit, so REC9's "the record rides its own
        resolution's commit" has nothing for a bare `recompile` resync
        to ride). Evidence this closes (probe run during the gate):
        `'self-learn: compile record /tmp/pytest-of-user/.../CLAUDE.md'`
        — the ONLY pinned subject anywhere in this codebase that
        embedded an absolute local path.

        N-8 (code gate r2 fold): the fix originally named the host by
        `hosts.slug_for`'s FULL shape (the resolved path, `/`→`-`, plus
        digest) — `/`-free as required, but very long, and on the real
        machine it writes the operator's whole home-directory structure
        into a ledger commit subject. A dedicated `hosts.host_subject_name`
        function fixed this AT THE FUNCTION level — the path's own
        BASENAME plus the same short digest, never the full path — but
        N-6 (below) supersedes it as the subject SOURCE for this
        specific commit: a batched run can span several different
        hosts, so naming any ONE of them would be arbitrary. The
        combined subject names a COUNT instead; no host path or name of
        any shape reaches it. N-1 (code gate r3 fold): with N-6 already
        the only caller-side use, `host_subject_name` was dead code —
        deleted along with its three direct unit tests; this paragraph's
        own history is kept because it explains why the subject looks
        the way it does.

        N-6 (code gate r2 fold): recompile used to emit ONE standalone
        ledger commit PER changed target (managed/reference/pointer/
        hook, potentially several per run) — see the dedicated
        `TestN6RecompileBatchesResyncIntoOneCommit` below for a run that
        actually drives more than one. Every automatic resync in a
        single `recompile()` invocation now lands in exactly ONE
        combined commit; this test's own single-target run still
        produces exactly one, unchanged in outcome, just no longer
        naming the host at all."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "resync-subject-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        rec1 = make_behavior(scope="project", record_id="lrn-00000013")
        create_record(env.ledger, rec1, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000013", dest="claude-md", no_push=True)

        target = plain_host / "CLAUDE.md"
        before_text = target.read_text(encoding="utf-8")

        rec2 = make_behavior(scope="project", record_id="lrn-00000014")
        create_record(env.ledger, rec2, project_path=plain_host)
        verbs.route(env.ledger, "lrn-00000014", dest="claude-md", no_push=True)
        after_route_text = target.read_text(encoding="utf-8")
        assert after_route_text != before_text

        # same shape as the sibling resync test above: hand-edit back to
        # the STALE (rec1-only) bytes, `--adopt` freezes the record to
        # match them exactly, THEN a plain (non-adopting) `recompile`
        # sees the ledger's true canonical content (both records) differ
        # from disk and both WRITES it and RESYNCS the record — that
        # resync's LEDGER commit is the one under test here.
        target.write_text(before_text, encoding="utf-8")
        adopt_result = verbs.recompile(env.ledger, no_push=True, adopt=target)
        assert not any("edited" in w for w in adopt_result.warnings)

        before_head = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        result = verbs.recompile(env.ledger, no_push=True)
        after_head = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        assert after_head != before_head, "expected a resync commit, saw none"
        assert any(e.changed for e in result.entries)

        subject = git(
            env.ledger, "log", "-1", "--format=%s"
        ).stdout.strip()
        assert "compile record" not in subject.lower(), (
            f"resync commit reused the §4.5/gate-B-3-rejected subject: {subject!r}"
        )
        assert "/" not in subject, (
            f"resync commit subject embeds a path (contains '/'): {subject!r}"
        )
        full_slug = hosts_mod.host_slug(env.ledger, plain_host, scope_kind="project")
        assert full_slug not in subject, (
            "resync commit subject reverted to the FULL slug shape "
            f"(embeds the whole resolved path) — N-8: {subject!r}"
        )
        assert subject == "self-learn: recompile resync record(s) (1)", (
            "N-6: the combined resync subject must name a COUNT, never "
            f"any host at all (a batched run can span several): {subject!r}"
        )

    def test_recompile_reference_and_pointer_render_resyncs_the_record(
        self, tmp_path
    ):
        """D-3 (code gate r1 fold): the SAME residual-defect fix as
        `test_git_target_render_after_ledger_change_writes_and_resyncs`,
        extended to the OTHER two region kinds `recompile()`'s own
        `ref_work` loop writes — `reference` and `pointer`. Unlike the
        managed-target loop, `ref_work` has no verdict/refusal gate at
        all (`compile_reference`/`apply_pointer` are unconditionally
        re-applied, relying on their OWN content-based idempotence) —
        pre-fold, a render that changed real bytes there left the
        compile record exactly as stale as the managed leg did, and
        `_abort_if_unsound`'s `"reference"`/`"pointer"` preflight checks
        (verbs.py ~1753/1776, run by the NEXT `route()` into the same
        skill) is the concrete false-refusal channel this closes: a
        stale record reads as `edited` and refuses a legitimate route.

        Mutation this would catch: wrap the two new resync blocks in
        `if False and ...:` — the final `route()` call below (rec3)
        raises `VerbError` with "edited" in it, instead of landing
        clean."""
        env = make_env(tmp_path)
        from self_learn.compilers import reference_target_path

        pointer_surface = env.skill_md
        before_any_pointer_text = pointer_surface.read_text(encoding="utf-8")

        rec1 = make_behavior(scope="skill:s", record_id="lrn-00000069")
        create_record(env.ledger, rec1)
        verbs.route(env.ledger, "lrn-00000069", dest="reference", no_push=True)

        ref_path = reference_target_path(env.skill_dir / "references")
        after_rec1_ref_text = ref_path.read_text(encoding="utf-8")
        after_rec1_pointer_text = pointer_surface.read_text(encoding="utf-8")
        assert after_rec1_pointer_text != before_any_pointer_text  # pointer written

        rec2 = make_behavior(scope="skill:s", record_id="lrn-0000006a")
        create_record(env.ledger, rec2)
        verbs.route(env.ledger, "lrn-0000006a", dest="reference", no_push=True)

        after_rec2_ref_text = ref_path.read_text(encoding="utf-8")
        after_rec2_pointer_text = pointer_surface.read_text(encoding="utf-8")
        assert "lrn-00000069" in after_rec2_ref_text
        assert "lrn-0000006a" in after_rec2_ref_text
        assert after_rec2_ref_text != after_rec1_ref_text

        slug = hosts_mod.host_slug(env.ledger, env.host, scope_kind="skill")
        ref_key = compiled.region_key(env.host, ref_path)
        pointer_key = compiled.region_key(env.host, pointer_surface)
        correct_ref_entry = compiled.entry_for(
            compiled.load_record(env.ledger, slug), ref_key
        )
        correct_pointer_entry = compiled.entry_for(
            compiled.load_record(env.ledger, slug), pointer_key
        )
        assert correct_ref_entry is not None
        assert correct_pointer_entry is not None

        # Simulate lost/reverted work (the H-2-flavored scenario): BOTH
        # the disk files AND the ledger's own compile record together
        # reverted to a self-consistent rec1-only state (never just
        # disk alone — a stale-but-self-consistent record is what makes
        # this discriminate at all: `compile_reference`/`apply_pointer`
        # deterministically reconstruct the SAME rec1+rec2 bytes either
        # way, so if the record already matched the reconstructed
        # bytes — e.g. because it still held rec2's own correct
        # resync — this recompile call's OWN resync would be a
        # no-op-equivalent and this test would pass even with the fix
        # deleted). Direct record surgery, not a second `route()` call,
        # is required to reach this state: any `route()` into this
        # skill re-syncs the record to match, by design.
        ref_region_rec1 = compiled.region_bytes(after_rec1_ref_text, "reference")
        pointer_region_rec1 = compiled.region_bytes(
            after_rec1_pointer_text, "pointer"
        )
        assert ref_region_rec1 is not None
        assert pointer_region_rec1 is not None
        compiled.write_entry(
            env.ledger,
            slug,
            ref_key,
            region="reference",
            sha256=compiled.sha256_hex(ref_region_rec1),
            based_on_sha256=compiled.sha256_hex(ref_region_rec1),
            nbytes=len(ref_region_rec1),
            by="test setup: revert record to rec1-only",
            host=str(env.host),
            mode="git",
        )
        compiled.write_entry(
            env.ledger,
            slug,
            pointer_key,
            region="pointer",
            sha256=compiled.sha256_hex(pointer_region_rec1),
            based_on_sha256=compiled.sha256_hex(pointer_region_rec1),
            nbytes=len(pointer_region_rec1),
            by="test setup: revert record to rec1-only",
            host=str(env.host),
            mode="git",
        )
        git(env.ledger, "add", "-A")
        git(env.ledger, "commit", "-m", "test setup: revert compile record")

        ref_path.write_text(after_rec1_ref_text, encoding="utf-8")
        pointer_surface.write_text(before_any_pointer_text, encoding="utf-8")
        commit_all(env.host, "revert reference+pointer to pre-recompile state")

        result = verbs.recompile(env.ledger, no_push=True)

        ref_targets = {e.target: e for e in result.entries}
        assert ref_targets[ref_path].changed is True
        assert ref_targets[pointer_surface].changed is True
        assert ref_path.read_text(encoding="utf-8") == after_rec2_ref_text
        assert pointer_surface.read_text(encoding="utf-8") == after_rec2_pointer_text

        data_after = compiled.load_record(env.ledger, slug)
        ref_entry_after = compiled.entry_for(data_after, ref_key)
        pointer_entry_after = compiled.entry_for(data_after, pointer_key)
        assert ref_entry_after is not None
        assert pointer_entry_after is not None

        ref_region = compiled.region_bytes(after_rec2_ref_text, "reference")
        assert ref_region is not None
        ref_observed = compiled.sha256_hex(ref_region)
        assert ref_entry_after["sha256"] == ref_observed, (
            "the compile record was not resynced after recompile's "
            "reference-append render — it still points at stale bytes"
        )
        assert compiled.verdict_for(ref_entry_after, ref_observed) == "clean"
        assert ref_entry_after["sha256"] == correct_ref_entry["sha256"]

        pointer_region = compiled.region_bytes(after_rec2_pointer_text, "pointer")
        assert pointer_region is not None
        pointer_observed = compiled.sha256_hex(pointer_region)
        assert pointer_entry_after["sha256"] == pointer_observed, (
            "the compile record was not resynced after recompile's "
            "pointer-write render — it still points at stale bytes"
        )
        assert compiled.verdict_for(pointer_entry_after, pointer_observed) == "clean"
        assert pointer_entry_after["sha256"] == correct_pointer_entry["sha256"]

        # The false-refusal closure itself: a THIRD record routed into
        # the same skill's reference destination must succeed — pre-fix,
        # `_abort_if_unsound`'s "reference"/"pointer" preflight checks
        # would see the stale record left behind by this recompile call
        # and refuse it as `edited`.
        rec3 = make_behavior(scope="skill:s", record_id="lrn-0000006b")
        create_record(env.ledger, rec3)
        verbs.route(env.ledger, "lrn-0000006b", dest="reference", no_push=True)
        assert "lrn-0000006b" in ref_path.read_text(encoding="utf-8")

        # never-falsely-refuses-again invariant.
        third = verbs.recompile(env.ledger, no_push=True)
        assert not any("edited" in w for w in third.warnings)

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


class TestN6RecompileBatchesResyncIntoOneCommit:
    """N-6 (code gate r2): recompile used to emit ONE standalone ledger
    commit PER changed target — a repair run touching several drifted
    targets in one invocation used to make several resync commits. This
    drives TWO independent plain hosts' managed targets into needing a
    resync in the SAME `recompile()` call and counts the commits that
    land — exactly one, not two."""

    @staticmethod
    def _drift(env, host, rec1_id, rec2_id):
        """Route rec1, snapshot, route rec2 (canonical now differs),
        hand-write the target back to the rec1-only bytes. No `--adopt`
        needed: rec2's own route observed those EXACT bytes pre-write
        (`based_on_sha256`), so writing back to them verdicts `stale`
        (matches `based_on_sha256`), never `edited` — `stale` does not
        refuse in either mode (`compiled.refuses`). A later bare
        `recompile()` sees real drift (canonical now includes rec2 too)
        and renders + resyncs exactly once for this host. (An earlier
        version of this helper called `recompile(adopt=...)` per host —
        wrong: recompile renders EVERY drifted host it finds, adopted
        target or not, so adopting host A as a side effect already
        fixed host A's drift before host B was even set up, leaving
        only ONE host actually drifted by the time the real,
        under-test `recompile()` call ran.)"""
        target = host / "CLAUDE.md"
        rec1 = make_behavior(scope="project", record_id=rec1_id)
        create_record(env.ledger, rec1, project_path=host)
        verbs.route(env.ledger, rec1_id, dest="claude-md", no_push=True)
        stale_bytes = target.read_text(encoding="utf-8")

        rec2 = make_behavior(scope="project", record_id=rec2_id)
        create_record(env.ledger, rec2, project_path=host)
        verbs.route(env.ledger, rec2_id, dest="claude-md", no_push=True)

        target.write_text(stale_bytes, encoding="utf-8")
        return target

    def test_two_drifted_hosts_in_one_run_produce_exactly_one_commit(
        self, tmp_path
    ):
        env = make_env(tmp_path)
        host_a = tmp_path / "n6-host-a"
        host_a.mkdir()
        host_add(env.ledger, host_a, "project", mode="plain")
        host_b = tmp_path / "n6-host-b"
        host_b.mkdir()
        host_add(env.ledger, host_b, "project", mode="plain")

        target_a = self._drift(env, host_a, "lrn-000000f8", "lrn-000000f9")
        target_b = self._drift(env, host_b, "lrn-000000fa", "lrn-000000fb")

        before_head = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        before_count = git(
            env.ledger, "rev-list", "--count", "HEAD"
        ).stdout.strip()
        result = verbs.recompile(env.ledger, no_push=True)
        after_head = git(env.ledger, "rev-parse", "HEAD").stdout.strip()
        after_count = git(
            env.ledger, "rev-list", "--count", "HEAD"
        ).stdout.strip()

        # both targets actually rendered (real drift, not a no-op run) --
        # the positive control this test needs to mean anything.
        changed_targets = {e.target for e in result.entries if e.changed}
        assert target_a in changed_targets
        assert target_b in changed_targets

        assert after_head != before_head, "expected at least one new commit"
        assert int(after_count) - int(before_count) == 1, (
            "two independently-drifted hosts in ONE recompile() call "
            f"produced {int(after_count) - int(before_count)} new "
            "commit(s), not exactly one — N-6's batching regressed"
        )
        subject = git(env.ledger, "log", "-1", "--format=%s").stdout.strip()
        assert subject == "self-learn: recompile resync record(s) (2)", (
            f"unexpected batched subject: {subject!r}"
        )


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


class TestM4NamedRepairActuallyRepairs:
    """M-4 (code gate r2): `host_path_problem`'s missing-marker refusal
    (hosts.py, "carries no {MARKER_FILENAME} marker") names
    `self-learn host add --mode plain` as the repair. This is the gate's
    own probe, pinned as a permanent test: delete the marker on an
    already-registered plain host, run the NAMED repair, and check the
    marker actually comes back — not just rc 0 and a success line.

    N-3 (code gate r3 fold): `host_add` no longer prints "marker
    restored" itself — it returns a `HostAddResult` carrying the
    `marker_restored` SIGNAL, and `cli.py::_cmd_host_inner` prints from
    it. `test_named_repair_restores_a_deleted_marker` now asserts BOTH:
    the library-level signal (`result.marker_restored`) via a direct
    `host_add` call, and the CLI-level text via `cli.main`."""

    def test_named_repair_restores_a_deleted_marker(self, tmp_path):
        env = make_env(tmp_path)
        plain_host = tmp_path / "m4-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        marker = plain_host / hosts_mod.MARKER_FILENAME
        assert marker.is_file()
        marker.unlink()
        assert not marker.is_file()

        # the exact repair `host_path_problem` names: re-add, same mode.
        result = host_add(env.ledger, plain_host, "project", mode="plain")

        assert result is not None  # rc OK — no HostsError raised
        assert result.marker_restored is True, (
            "the named repair (`host add --mode plain` on an already-"
            "registered same-mode plain host) returned successfully but "
            "its own result did not signal a marker repair — M-4's "
            "exact defect, now visible at the return-value level (N-3)"
        )
        assert marker.is_file(), (
            "the named repair (`host add --mode plain` on an already-"
            "registered same-mode plain host) returned successfully but "
            "did not restore the marker it owns — M-4's exact defect"
        )

    def test_named_repair_prints_marker_restored_from_the_cli_layer(
        self, tmp_path, monkeypatch, capsys
    ):
        """N-3 (code gate r3 fold): the print moved OUT of `host_add`
        (a library function) and INTO `cli.py::_cmd_host_inner` — this
        is the test that actually drives the CLI, the only place left
        that can observe the terminal text at all."""
        from self_learn import cli

        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        plain_host = tmp_path / "m4-plain-cli"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        marker = plain_host / hosts_mod.MARKER_FILENAME
        marker.unlink()
        capsys.readouterr()  # discard the first `host add`'s output

        rc = cli.main(["host", "add", "--mode", "plain", str(plain_host)])
        out = capsys.readouterr().out

        assert rc == 0
        assert marker.is_file()
        assert f"marker restored at {marker}" in out

    def test_named_repair_is_a_true_no_op_when_the_marker_is_already_present(
        self, tmp_path
    ):
        """The repair must not CHURN an intact marker on every re-add —
        only write when the marker is genuinely absent, so a script that
        re-registers the same host repeatedly does not re-timestamp it
        every time. N-3: also checks the returned signal stays False."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "m4-plain-intact"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        marker = plain_host / hosts_mod.MARKER_FILENAME
        before = marker.read_text(encoding="utf-8")

        result = host_add(env.ledger, plain_host, "project", mode="plain")

        assert result.marker_restored is False, (
            "an intact marker must not be reported as repaired"
        )
        after = marker.read_text(encoding="utf-8")
        assert after == before, (
            "re-adding an already-registered plain host with an INTACT "
            "marker rewrote it — the repair must be conditional on the "
            "marker being absent, not unconditional"
        )


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
        route — checked at BOTH layers this codebase can reach a git
        subprocess through. Positive control in the same test: the
        identical instrument over a git-mode route records a non-zero
        count at both layers.

        Code gate r1 M-6: the prior instrument patched only
        `gitops._git`, so a raw `subprocess.run(["git", ...], cwd=...)`
        call bypassing that wrapper entirely — the exact shape
        `hosts._is_git_repo` already uses live in this codebase, and
        M25b's mutation (a stray `subprocess.run(["git","status"],
        cwd=str(spec.host_path))` inserted into `_host_phase`'s plain
        branch) — was invisible to it. This version patches BOTH
        `gitops._git` AND raw `subprocess.run`, recording
        `(repo_arg_or_cwd, argv)` from each."""
        import subprocess as _subprocess_mod

        env = make_env(tmp_path)
        git_calls: list[tuple[str, ...]] = []
        real_git = gitops._git

        def git_spy(repo, *args, **kw):
            git_calls.append((str(repo), *args))
            return real_git(repo, *args, **kw)

        monkeypatch.setattr(gitops, "_git", git_spy)

        subprocess_calls: list[tuple[str, tuple]] = []
        real_run = _subprocess_mod.run

        def run_spy(*args, **kwargs):
            argv = args[0] if args else kwargs.get("args")
            cwd = kwargs.get("cwd")
            subprocess_calls.append((str(cwd) if cwd is not None else "", tuple(argv)))
            return real_run(*args, **kwargs)

        monkeypatch.setattr(_subprocess_mod, "run", run_spy)

        def _mentions(host: Path, call: tuple[str, tuple]) -> bool:
            # `gitops._git` never passes `cwd=` — it names the repo via
            # `git -C <repo> ...` in argv instead — so a call "against"
            # a host may show up either as the recorded `cwd`, or as a
            # literal argument in argv (`-C <repo>`, or a raw
            # `subprocess.run(["git", ...], cwd=str(host))` shape).
            cwd, argv = call
            return cwd == str(host) or str(host) in argv

        plain_host = tmp_path / "plain4-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-0000000a")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-0000000a", dest="claude-md", no_push=True)
        plain_git_calls = [c for c in git_calls if c[0] == str(plain_host)]
        assert plain_git_calls == []
        plain_subprocess_calls = [
            c for c in subprocess_calls if _mentions(plain_host, c)
        ]
        assert plain_subprocess_calls == [], (
            f"a raw subprocess.run reached the plain host directly, "
            f"bypassing gitops._git entirely: {plain_subprocess_calls!r}"
        )

        git_calls.clear()
        subprocess_calls.clear()
        record2 = make_behavior(scope="skill:s", record_id="lrn-0000000b")
        create_record(env.ledger, record2)
        verbs.route(env.ledger, "lrn-0000000b", dest="skill-md", no_push=True)
        host_git_calls = [c for c in git_calls if c[0] == str(env.host)]
        assert len(host_git_calls) > 0  # positive control: git mode DOES call git
        host_subprocess_calls = [
            c for c in subprocess_calls if _mentions(env.host, c)
        ]
        assert len(host_subprocess_calls) > 0  # same control, the raw-subprocess layer

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

    def test_plain10_push_skips_plain_hosts_silently(self, tmp_path, capsys, monkeypatch):
        """PLAIN10 (code gate r1 fold M-5): `self-learn push`
        (`verbs.push_pending`) skips plain hosts silently — no line on
        EITHER stream, stdout or stderr (the prior instrument asserted
        on stdout, but `push_pending`'s skip line, when a host IS
        printed, always goes to stderr — `verbs.py`'s
        ``print(..., file=sys.stderr)`` — so that assertion could never
        fail) — and never calls `gitops.unpushed_commits` on a plain
        host's directory at all (it has no `git status` to consult;
        calling it would be a raw git subprocess against a non-repo, or
        worse, an ancestor repo it happens to sit inside)."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "plain10-host"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        record = make_behavior(scope="project", record_id="lrn-0000000e")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-0000000e", dest="claude-md", no_push=True)

        calls: list[Path] = []
        real_unpushed = gitops.unpushed_commits

        def _tracking_unpushed(repo, *a, **kw):
            calls.append(Path(repo))
            return real_unpushed(repo, *a, **kw)

        monkeypatch.setattr(gitops, "unpushed_commits", _tracking_unpushed)
        capsys.readouterr()
        verbs.push_pending(env.ledger)
        captured = capsys.readouterr()
        assert f"skipping {plain_host}" not in captured.out
        assert f"skipping {plain_host}" not in captured.err
        assert plain_host.resolve() not in calls, (
            "unpushed_commits was called against the plain host — PLAIN10 "
            "requires it never be consulted for one"
        )

    def test_plain12_lock_paths(self, tmp_path):
        """PLAIN12: the plain-host lock path is
        `${XDG_CACHE_HOME}/self-learn/host-<slug>.commit.lock`, keyed by
        the HOST's own slug (never the ledger home's) — §4.3's whole
        reason for a GLOBAL, non-home-namespaced cache path: "a host
        can be registered by more than one ledger home and the
        contended resource is the HOST's file". The git-host lock path
        is byte-identical to `commit_lock_path`'s own (UN8).

        Code gate r1 M-7: the prior instrument checked only the path's
        SHAPE (`startswith("host-")`, `endswith(".commit.lock")`,
        parent named `self-learn`) — never the actual key inside it.
        M31 (keying the plain lock by `resolve_home()` instead of the
        host path, `gitops.py:505-507`) satisfied that shape too, since
        `resolve_home()`'s own string also starts with `host-` and ends
        with `.commit.lock` once formatted the same way — so the ONE
        property PLAIN12 exists to pin (two different ledger HOMES
        registering the SAME host resolve to the SAME lock path) went
        unchecked. This version asserts the FULL path equals
        `hosts.slug_for(host)`'s own construction, directly. Note
        `host_lock_path`'s own signature — `(path, mode)`, no `home`
        parameter at all — IS the cross-home property already: two
        different ledger homes registering the SAME physical host call
        the exact same function with the exact same arguments, so they
        can only ever resolve to the SAME lock path; there is no
        home-scoped input for them to diverge on."""
        env = make_env(tmp_path)
        assert gitops.host_lock_path(env.host, "git") == gitops.commit_lock_path(env.host)

        plain_host = tmp_path / "plain12-host"
        plain_host.mkdir()
        plain_path = gitops.host_lock_path(plain_host, "plain")
        expected = (
            Path(os.environ["XDG_CACHE_HOME"])
            / "self-learn"
            / f"host-{hosts_mod.slug_for(plain_host)}.commit.lock"
        )
        assert plain_path == expected



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

    @staticmethod
    def _bare_ledger(tmp_path: Path, name: str) -> Path:
        """A minimal doc-13 ledger home, independent of `make_env`'s own
        paired host — needed here because TWO ledgers must register the
        SAME physical plain host (PLAIN12/§4.3's own reasoning: the
        contended resource is the HOST's file, not any one home's view
        of it), and `make_env` always creates a fresh host of its own."""
        ledger = tmp_path / name
        ledger.mkdir()
        git(ledger, "init", "-q", "-b", "main")
        git(ledger, "config", "user.email", "test@example.com")
        git(ledger, "config", "user.name", "Test")
        for sub in ("skills", "projects", "user", "telemetry"):
            (ledger / sub).mkdir()
        # git tracks no empty directories, so there is nothing to commit
        # yet -- `host_add` (called next by the caller) makes the
        # ledger's real first commit, writing hosts.yaml.
        return ledger

    def test_two_processes_serialize_through_verbs_recompile_itself(self, tmp_path):
        """B-2 (code gate r1 fold): PLAIN5's REAL instrument. The prior
        version of this test drove `_host_phase` through `verbs.route`,
        but `route`/`route_direct` ALSO pre-acquire the SAME host lock
        one level up (`with _ledger_write(home), gitops.host_lock(...)`,
        opened before `_observe_region_hash` so REC13's staleness read
        is itself lock-protected) -- so through `route`, `_host_phase`'s
        OWN internal `gitops.host_lock` call is a re-entrant pass-through
        (`gitops._held_locks`) and mutating it to a plain-mode
        `nullcontext()` (M26) is externally INVISIBLE: proven empirically
        -- mutating BOTH call sites at once, `route`-driven, still
        blocked for the holder's full sleep window. `verbs.recompile`
        does not have this shielding: it calls `_observe_region_hash`
        and `_host_phase` back to back with no enclosing lock of its
        own (confirmed by reading `recompile`'s body — zero
        `gitops.host_lock` calls outside the one inside `_host_phase`
        itself), so `_host_phase`'s lock is the FIRST and ONLY guard on
        this path — the one M26 actually targets.

        TWO DIFFERENT ledger homes register the SAME plain host (isolates
        the HOST lock from the LEDGER lock, same reasoning as PLAIN12/
        §4.3: the contended resource is the HOST's file). Each ledger
        routes its OWN record to a DIFFERENT destination under that host
        (`claude-md` vs. `claude-md:rules:topic-b`) during sequential
        setup, so neither route call collides with content the other
        ledger already wrote (B-1 would correctly refuse a SECOND
        ledger's write into a region it never recorded — that is not
        this test's subject). The holder process then calls
        `verbs.recompile(ledger_a)` with `_apply_target` monkeypatched to
        mark entry and sleep, observably holding the host lock; THIS
        process concurrently calls `verbs.recompile(ledger_b)` — a
        DIFFERENT target file, same host lock — and must observably BLOCK
        until the holder's recompile (lock included) has completed.
        Verified empirically before being pinned here: elapsed ~1.5-1.7s
        against the real code, and ~0.005s once `_host_phase`'s internal
        lock alone is mutated to the M26 shape — i.e. this test goes RED
        exactly on M26, unlike its `route`-driven predecessor."""
        plain_host = tmp_path / "plain5c-host"
        plain_host.mkdir()
        (plain_host / "CLAUDE.md").write_text(
            "# plain host\n", encoding="utf-8"
        )

        ledger_a = self._bare_ledger(tmp_path, "ledger-a")
        ledger_b = self._bare_ledger(tmp_path, "ledger-b")
        host_add(ledger_a, plain_host, "project", mode="plain")
        host_add(ledger_b, plain_host, "project", mode="plain")

        record_a = make_behavior(scope="project", record_id="lrn-000000d1")
        record_b = make_behavior(scope="project", record_id="lrn-000000d2")
        create_record(ledger_a, record_a, project_path=plain_host)
        create_record(ledger_b, record_b, project_path=plain_host)

        # sequential setup -- each ledger routes into its OWN, previously
        # untouched destination under the shared host, so neither call
        # can trip B-1's refusal.
        verbs.route(ledger_a, "lrn-000000d1", dest="claude-md", no_push=True)
        verbs.route(
            ledger_b, "lrn-000000d2", dest="claude-md:rules:topic-b", no_push=True
        )

        marker = tmp_path / "holder-in-lock.txt"
        cli_src = str(Path(__file__).resolve().parents[1] / "src")
        holder_script = tmp_path / "holder_recompile.py"
        holder_script.write_text(
            "import sys, time\n"
            f"sys.path.insert(0, {cli_src!r})\n"
            "from pathlib import Path\n"
            "from self_learn import verbs\n"
            "_real_apply = verbs._apply_target\n"
            "def _slow_apply(*a, **kw):\n"
            f"    Path({str(marker)!r}).write_text('IN LOCK', encoding='utf-8')\n"
            "    time.sleep(1.5)\n"
            "    return _real_apply(*a, **kw)\n"
            "verbs._apply_target = _slow_apply\n"
            f"verbs.recompile({str(ledger_a)!r}, no_push=True)\n",
            encoding="utf-8",
        )
        proc = subprocess.Popen(["python3", str(holder_script)])
        try:
            deadline = time.monotonic() + 3.0
            while not marker.is_file() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert marker.is_file(), "holder process never entered its critical section"

            t0 = time.monotonic()
            verbs.recompile(ledger_b, no_push=True)
            elapsed = time.monotonic() - t0
            # ledger B's OWN ledger lock was free the whole time (its own
            # home, never touched by the holder) -- any blocking observed
            # here can ONLY come from the shared HOST lock inside
            # `_host_phase`, which is exactly what M26 removes.
            assert elapsed > 0.8, f"recompile did not block on the holder (elapsed={elapsed})"
        finally:
            proc.wait(timeout=5)

        topic_b_text = (plain_host / ".claude" / "rules" / "topic-b.md").read_text(
            encoding="utf-8"
        )
        assert "lrn-000000d2" in topic_b_text
        assert topic_b_text.count(compilers.BEGIN_MARKER) == 1
        assert topic_b_text.count(compilers.END_MARKER) == 1


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
    select a dotfiles-management/user branch. **Instrument (b):** any
    call to
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
        branching into dotfiles-management/user logic, and MODE9's own spec text
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
        the unmutated dispatch that script mutates.

        Code gate r1 fold N-9: the dispatch line itself gained a
        `target.is_file()` guard (master's own, dropped when the three
        original per-call-site guards were consolidated here) — updated
        to match; the property this control protects (git mode still
        calls `_abort_if_dirty`) is unchanged."""
        src_path = Path(verbs.__file__)
        text = src_path.read_text(encoding="utf-8")
        assert (
            "if mode == \"git\" and target.is_file():\n"
            "        _abort_if_dirty(host_path, target)"
        ) in text


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


# ------------------------------------------------------------- gate r1 fold


class TestB1Rec5RowTwoUnknownRefusesPlainMode:
    """B-1 (code gate r1): REC5 row 2 -- `entry absent + region present`
    -> REFUSE in plain mode. `compiled.refuses`'s `mode` parameter is now
    load-bearing (closes N-2). Git mode keeps the deliberate `unknown`
    scope reduction (provenance is git's own committed history)."""

    def test_refuses_unit_row(self):
        assert compiled.refuses("unknown", "plain") is True
        assert compiled.refuses("unknown", "git") is False
        assert compiled.refuses("edited", "plain") is True
        assert compiled.refuses("edited", "git") is True
        for verdict in ("fresh", "clean", "missing", "stale"):
            assert compiled.refuses(verdict, "plain") is False
            assert compiled.refuses(verdict, "git") is False

    def test_plain_route_refuses_and_leaves_bytes_unchanged_on_marker_bounded_content_the_ledger_never_wrote(
        self, tmp_path
    ):
        """The gate's own probe: a plain host's target already carries a
        marker-bounded managed section this ledger never wrote (no
        compile record yet) -- the route must REFUSE (`DirtyTargetError`,
        the CLI's exit-1 shape) and the file's bytes must be
        BYTE-UNCHANGED afterwards -- never silently overwritten."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "rec5row2-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        target = plain_host / "CLAUDE.md"
        foreign_section = (
            f"# host project\n\n{verbs.BEGIN_MARKER}\n"
            "Some other tool's content, never written by this ledger.\n"
            f"{compilers.END_MARKER}\n"
        )
        target.write_text(foreign_section, encoding="utf-8")
        before = target.read_bytes()

        record = make_behavior(scope="project", record_id="lrn-000000b1")
        create_record(env.ledger, record, project_path=plain_host)
        with pytest.raises(verbs.DirtyTargetError) as excinfo:
            verbs.route(env.ledger, "lrn-000000b1", dest="claude-md", no_push=True)
        assert verbs.REGION_VERDICT_MARKER in str(excinfo.value)
        assert "unknown" in str(excinfo.value)
        assert target.read_bytes() == before

    def test_git_mode_still_proceeds_on_unknown_unchanged(self, tmp_path):
        """The other half of the mode split: the SAME marker-bounded,
        record-less content on a GIT host must still PROCEED (S3/UN3's
        byte-unchanged migration promise) -- git's own commit history is
        the provenance source there, not the compile record."""
        env = make_env(tmp_path)
        foreign_section = (
            f"# host project\n\n{verbs.BEGIN_MARKER}\n"
            "Pre-existing content from before this unit shipped.\n"
            f"{compilers.END_MARKER}\n"
        )
        (env.host / "CLAUDE.md").write_text(foreign_section, encoding="utf-8")
        commit_all(env.host, "pre-existing managed section, no compile record")

        record = make_behavior(scope="project", record_id="lrn-000000b2")
        create_record(env.ledger, record, project_path=env.host)
        result = verbs.route(env.ledger, "lrn-000000b2", dest="claude-md", no_push=True)
        assert result.host_commit_sha is not None


class TestM3Rec5RowSevenSelfAdopt:
    """M-3 (code gate r2): REC5's seventh row — `entry absent + region
    present + region bytes == the compiler's expected render from the
    ledger's CURRENT records for that target` -> ADOPT (write the entry,
    print one notice, proceed) instead of refusing. Real hazard on THIS
    machine (the gate's own measured finding): every host routed to
    before this unit shipped compile records has exactly this shape on
    its first post-upgrade route, and B-1's fix alone would refuse ALL
    of them. Only a genuine BYTE MISMATCH (real foreign content) still
    refuses — H-3 is unweakened."""

    def test_self_adopt_row_adopts_matching_content_and_proceeds(
        self, tmp_path, capsys
    ):
        env = make_env(tmp_path)
        plain_host = tmp_path / "m3-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        target = plain_host / "CLAUDE.md"

        # record A: routed NORMALLY first -- this is the pre-existing
        # content a real host would already carry.
        record_a = make_behavior(scope="project", record_id="lrn-000000f1")
        create_record(env.ledger, record_a, project_path=plain_host)
        verbs.route(env.ledger, "lrn-000000f1", dest="claude-md", no_push=True)
        assert (env.ledger / "compiled").is_dir()

        # simulate "this unit never wrote a compile record for this
        # host" -- the gate's own measured real-machine state: markers
        # present, no `compiled/` dir AT ALL (not just a missing entry).
        shutil.rmtree(env.ledger / "compiled")
        assert not (env.ledger / "compiled").exists()
        before = target.read_bytes()

        # record B: a NEW route to the SAME target. Pre-flight sees
        # `unknown` (entry absent, region present) for A's own content
        # -- but at THIS moment B is not yet marked routed, so the
        # compiler's render of the ledger's CURRENT records (A alone)
        # is byte-identical to what's on disk. Must ADOPT, not refuse.
        record_b = make_behavior(scope="project", record_id="lrn-000000f2")
        create_record(env.ledger, record_b, project_path=plain_host)
        result = verbs.route(env.ledger, "lrn-000000f2", dest="claude-md", no_push=True)

        assert result is not None
        assert target.read_bytes() != before  # B's own content was added
        captured = capsys.readouterr()
        assert "adopting" in captured.err
        assert str(target) in captured.err

        # B's own normal REC9 resync (unconditional, unrelated to the
        # adopt path) writes the entry -- proving "proceed" really did
        # proceed all the way through, not just skip the refusal.
        slug = verbs.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        entry = compiled.entry_for(compiled.load_record(env.ledger, slug), key)
        assert entry is not None

    def test_still_refuses_when_on_disk_content_does_not_match(self, tmp_path):
        """The discriminating half: identical setup, but the on-disk
        content is hand-altered after A's route (real foreign content,
        not merely a missing receipt) -- must still REFUSE, byte-
        unchanged, H-3 unweakened."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "m3-plain-mismatch"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")
        target = plain_host / "CLAUDE.md"

        record_a = make_behavior(scope="project", record_id="lrn-000000f3")
        create_record(env.ledger, record_a, project_path=plain_host)
        verbs.route(env.ledger, "lrn-000000f3", dest="claude-md", no_push=True)
        shutil.rmtree(env.ledger / "compiled")

        # hand-edit INSIDE the managed markers -- a real divergence from
        # what self-learn's compiler would render, not a benign gap.
        text = target.read_text(encoding="utf-8")
        assert verbs.BEGIN_MARKER in text
        text = text.replace(
            verbs.BEGIN_MARKER, verbs.BEGIN_MARKER + "\nHAND-EDITED LINE\n"
        )
        target.write_text(text, encoding="utf-8")
        before = target.read_bytes()

        record_b = make_behavior(scope="project", record_id="lrn-000000f4")
        create_record(env.ledger, record_b, project_path=plain_host)
        with pytest.raises(verbs.DirtyTargetError) as excinfo:
            verbs.route(env.ledger, "lrn-000000f4", dest="claude-md", no_push=True)
        assert "unknown" in str(excinfo.value)
        assert "recompile --adopt" in str(excinfo.value)
        assert target.read_bytes() == before

    def test_probe_matches_the_gate_shape_user_scope_markers_no_compiled_dir(
        self, tmp_path, monkeypatch, capsys
    ):
        """The gate's OWN measured probe, reproduced: user scope
        specifically (`~/.claude/CLAUDE.md` on the real machine) with
        self-learn markers already present and NO `compiled/` directory
        at all -- "the one host GUARANTEED to be in that state" on
        first contact after this unit ships."""
        target = tmp_path / "dot-claude-m3" / "CLAUDE.md"
        target.parent.mkdir()
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", target)

        env = make_env(tmp_path)
        assert not (env.ledger / "compiled").exists()

        record_a = make_behavior(scope="user", record_id="lrn-000000f5")
        create_record(env.ledger, record_a)
        verbs.route(env.ledger, "lrn-000000f5", dest="claude-md", no_push=True)
        shutil.rmtree(env.ledger / "compiled")
        assert not (env.ledger / "compiled").exists()

        record_b = make_behavior(scope="user", record_id="lrn-000000f6")
        create_record(env.ledger, record_b)
        result = verbs.route(env.ledger, "lrn-000000f6", dest="claude-md", no_push=True)
        assert result is not None
        assert "adopting" in capsys.readouterr().err

    def test_doctor_summary_line_counts_unknown_provenance_targets(self, tmp_path):
        """M-3 (code gate r2): the SUMMARY doctor line doc 17's migration
        paragraph promises -- "N target(s) carry self-learn markers with
        no compile record -- run `recompile --adopt`" -- measured on a
        FIXTURE (never the real ledger). `_check_drift` must still
        report `ok=True` (unknown provenance is not itself drift; only
        `edited` is)."""
        env = make_env(tmp_path)
        plain_host = tmp_path / "m3-doctor-plain"
        plain_host.mkdir()
        host_add(env.ledger, plain_host, "project", mode="plain")

        record = make_behavior(scope="project", record_id="lrn-000000f7")
        create_record(env.ledger, record, project_path=plain_host)
        verbs.route(env.ledger, "lrn-000000f7", dest="claude-md", no_push=True)
        shutil.rmtree(env.ledger / "compiled")

        ok, reason = selfcheck._check_drift(env.ledger)
        assert ok is selfcheck.Verdict.PASS
        assert (
            "1 target(s) carry self-learn markers with no compile record"
            in reason
        )
        assert "recompile --adopt" in reason


# ---------------------------------------------------------------- REC12 group


class TestRec12HostLockDiscipline:
    """REC12 [A]: every host-writing verb takes the host lock before its
    first host-region READ or ledger mutation, holds it through the host
    write, and releases it before the push. Structural (AST), like
    `test_lock_invariant.py`'s own THE INVARIANT — but that walker only
    tracks FS/git *mutating* primitives, so it cannot see this unit's
    hazard: `_observe_region_hash`/`_observe_retirement_region` are
    READS, not mutations, and an unlocked read racing a later locked
    write is exactly the staleness hole REC13 exists to fence
    (`_flock_lock`'s own docstring: "the compile record's `based_on_sha256`
    is the state THIS write is based on, never a later re-read"). Code
    gate r1 M-3: this instrument did not exist, and the shipped code
    violated leg (c) in `supersede`/`graduate` (no host lock at all
    before their region read) — both are fixed in this same commit.

    Five legs, all checked by parsing `verbs.py` fresh (never `inspect`,
    so a stale `.pyc` cannot lie):

    (a) callee-at-entry — `_host_phase`'s lock is its own FIRST statement.
    (b) six call sites + `_remove_hook_script` — `route`, `route_direct`,
        `supersede`, `graduate` each open (or delegate through) the host
        lock; `_remove_hook_script` takes its own independently.
    (c) lock precedes the first mutating call — no sensitive read/write
        in a verb's body lies outside its host-lock-guarded `with`.
    (d) push outside — `push_if_remote`/`_push_ledger` never lies inside
        that same `with`.
    (e) ORDER — code gate r2 M-1: presence alone (legs b/c) is not
        enough. `_ledger_write(home)` must be one of the SAME `with`
        statement's OWN context managers as the host lock, at a LOWER
        index — `with _ledger_write(home), <host lock>:`, matching
        §4.5b's pinned "ledger first, host second" for every verb, no
        exceptions. The r1 fold gave `supersede`/`graduate` the host
        lock legs (b)/(c)/(d) demanded, but nested it OUTSIDE
        `_ledger_write` (host first) while `route`/`route_direct` open
        both in one combined `with` (ledger first) — two DIFFERENT
        orders that can deadlock two OS processes against each other
        until `gitops.COMMIT_LOCK_TIMEOUT` (150s). See
        `TestM1LockOrderRuntimeProbe` below for the live, real-process
        proof that this no longer happens.
    """

    @staticmethod
    def _verbs_tree() -> ast.Module:
        src = (
            Path(__file__).resolve().parents[1]
            / "src" / "self_learn" / "verbs.py"
        ).read_text(encoding="utf-8")
        return ast.parse(src)

    @staticmethod
    def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"verbs.py defines no function {name!r}")

    @staticmethod
    def _is_host_lock_call(expr: ast.AST) -> bool:
        """True if `expr` IS (or, walked, CONTAINS) a call to
        `gitops.host_lock(...)` — covers both the direct
        `with gitops.host_lock(...):` shape (route/route_direct) and a
        ternary/if-else expression that calls it in one branch
        (supersede/graduate's mode-optional shape)."""
        for n in ast.walk(expr):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "host_lock"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "gitops"
            ):
                return True
        return False

    @classmethod
    def _host_lock_with_nodes(cls, func: ast.FunctionDef) -> list[ast.With]:
        """Every `with` statement anywhere in `func` whose guard is
        host-lock-shaped — either directly (`with gitops.host_lock(...):`)
        or via a bare name bound, ANYWHERE in `func` (a flat scan — this
        codebase never shadows a `_x_host_lock` guard variable across
        nested scopes, so lexical precedence is not needed), to a
        host-lock-shaped expression (the `_x_host_lock = gitops.host_lock(
        ...) if ... else ...`; `with _x_host_lock:` shape — supersede's
        and graduate's assignment lives inside an `if`/`elif`/`else`,
        a SIBLING scope to the `with` that consumes it, which a
        preceding-statement-list walk cannot see; a flat name→shaped map
        over the whole function can)."""
        host_lock_names: set[str] = set()
        for n in ast.walk(func):
            if (
                isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and cls._is_host_lock_call(n.value)
            ):
                host_lock_names.add(n.targets[0].id)

        found: list[ast.With] = []
        for n in ast.walk(func):
            if not isinstance(n, ast.With):
                continue
            for item in n.items:
                ctx = item.context_expr
                guarded = cls._is_host_lock_call(ctx) or (
                    isinstance(ctx, ast.Name) and ctx.id in host_lock_names
                )
                if guarded:
                    found.append(n)
                    break
        return found

    @staticmethod
    def _calls_named(func: ast.FunctionDef, names: tuple[str, ...]) -> list[ast.Call]:
        """Every `Call` anywhere in `func` whose callee's own name (the
        final `.attr` of an `Attribute`, or a bare `Name`) is in `names`
        — line-numbered, for containment checks against a `with` node's
        own line span."""
        hits: list[ast.Call] = []
        for n in ast.walk(func):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            callee = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None
            )
            if callee in names:
                hits.append(n)
        return hits

    @staticmethod
    def _inside_any(call: ast.Call, withs: list[ast.With]) -> bool:
        return any(
            w.lineno <= call.lineno <= (w.end_lineno or w.lineno) for w in withs
        )

    # -- leg (a): callee-at-entry ------------------------------------

    def test_leg_a_host_phase_lock_is_its_own_first_statement(self):
        tree = self._verbs_tree()
        func = self._find_func(tree, "_host_phase")
        # `_host_phase`'s body is `try: with gitops.host_lock(...): ...`
        # (docstring, then the `try`) — the lock must be the FIRST
        # statement inside that `try`, before ANY other work.
        body = [s for s in func.body if not isinstance(s, ast.Expr)]
        assert body, "_host_phase has no non-docstring statements"
        try_stmt = body[0]
        assert isinstance(try_stmt, ast.Try), (
            f"_host_phase's first statement is {type(try_stmt).__name__}, expected Try"
        )
        first_in_try = try_stmt.body[0]
        assert isinstance(first_in_try, ast.With), (
            "_host_phase's try-block does not open with a `with` — "
            f"got {type(first_in_try).__name__}"
        )
        assert any(
            self._is_host_lock_call(item.context_expr)
            for item in first_in_try.items
        ), "_host_phase's first `with` does not guard on gitops.host_lock"

    # -- leg (b) + (c) + (d), per verb --------------------------------

    @pytest.mark.parametrize(
        ("verb_name", "sensitive_names", "push_names"),
        [
            (
                "route",
                ("_observe_region_hash", "resolve_record", "_host_phase"),
                ("push_if_remote", "_push_ledger"),
            ),
            (
                "route_direct",
                ("_observe_region_hash", "_host_phase"),
                ("push_if_remote", "_push_ledger"),
            ),
            (
                "supersede",
                (
                    "_observe_region_hash",
                    "supersede_record",
                    "_host_phase",
                    "_remove_hook_script",
                ),
                ("push_if_remote", "_push_ledger"),
            ),
            (
                "graduate",
                (
                    "_observe_retirement_region",
                    "resolve_record",
                    "_retirement_host_phase",
                ),
                ("push_if_remote", "_push_ledger"),
            ),
        ],
    )
    def test_legs_bcd_verb_holds_host_lock_before_its_reads_and_writes(
        self, verb_name, sensitive_names, push_names
    ):
        tree = self._verbs_tree()
        func = self._find_func(tree, verb_name)
        host_lock_withs = self._host_lock_with_nodes(func)
        # leg (b): the verb must open (or delegate through) the host lock
        # at least once — a verb with zero host-lock-guarded `with`
        # blocks has REC12c's obligation reaching an entrypoint with no
        # lock anywhere on it (the exact M-3 shape: supersede/graduate
        # pre-fold).
        assert host_lock_withs, (
            f"{verb_name} opens no host-lock-guarded `with` at all "
            "(REC12b/c violation)"
        )

        # leg (c): every sensitive read/mutation call in the verb's body
        # must lie inside ONE of those `with` blocks — never before, and
        # never in a sibling branch outside them.
        for call in self._calls_named(func, sensitive_names):
            assert self._inside_any(call, host_lock_withs), (
                f"{verb_name}: a call to a name in {sensitive_names} at "
                f"line {call.lineno} lies OUTSIDE every host-lock-guarded "
                "`with` (REC12c violation — the lock does not precede "
                "this read/mutation)"
            )

        # leg (d): the push must never be inside the host-lock `with` —
        # a push is has_remote-guarded network I/O, never something the
        # host lock should serialize other producers behind.
        for call in self._calls_named(func, push_names):
            assert not self._inside_any(call, host_lock_withs), (
                f"{verb_name}: a call to a name in {push_names} at line "
                f"{call.lineno} lies INSIDE a host-lock-guarded `with` "
                "(REC12d violation — the push must sit outside the lock)"
            )

    def test_leg_b_remove_hook_script_takes_its_own_host_lock(self):
        tree = self._verbs_tree()
        func = self._find_func(tree, "_remove_hook_script")
        host_lock_withs = self._host_lock_with_nodes(func)
        assert host_lock_withs, (
            "_remove_hook_script opens no host-lock-guarded `with` at all "
            "(REC12b violation — the '+ _remove_hook_script' call site "
            "the gate named separately from the six verb-level sites)"
        )
        # its two mutating shapes: `script.unlink()` and `gitops._git(...)`
        for call in self._calls_named(func, ("unlink", "_git")):
            assert self._inside_any(call, host_lock_withs), (
                f"_remove_hook_script: a call to {call.func.attr!r} at "
                f"line {call.lineno} lies outside its own host-lock "
                "`with` (REC12c violation)"
            )

    # -- leg (e): ORDER — ledger acquired before host, same `with` -----

    @staticmethod
    def _is_ledger_write_call(expr: ast.AST) -> bool:
        """True if `expr` is a direct call to `_ledger_write(...)` —
        every verb calls it inline as a `with` item, never through an
        aliased variable, so no name-indirection tracking is needed here
        the way host-lock's `_x_host_lock` variable needs
        `_host_lock_with_nodes` above."""
        return (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id == "_ledger_write"
        )

    @pytest.mark.parametrize(
        "verb_name", ["route", "route_direct", "supersede", "graduate"]
    )
    def test_leg_e_ledger_lock_is_acquired_before_the_host_lock(self, verb_name):
        """M-1 (code gate r2): §4.5b pins ONE order — ledger first, host
        second — for every host-writing verb, no exceptions. Legs (b)/(c)
        above only prove BOTH locks are held before the sensitive work;
        neither says anything about their relative order. The r1 fold
        gave `supersede`/`graduate` the host lock they were missing, but
        nested it OUTSIDE `_ledger_write` (host first, ledger second)
        while `route`/`route_direct` open both in ONE combined `with`
        (ledger first) — two DIFFERENT orders, which is exactly the
        shape that can deadlock two OS processes against each other
        until `gitops.COMMIT_LOCK_TIMEOUT` (150s): see
        `TestM1LockOrderRuntimeProbe` for the live proof.

        Every host-lock-guarded `with` in the verb must ALSO carry
        `_ledger_write(home)` as one of its OWN context managers
        (`with _ledger_write(home), <host lock>:`), at a LOWER index
        than the host-lock item — never a separate, differently-ordered
        `with` for either lock."""
        tree = self._verbs_tree()
        func = self._find_func(tree, verb_name)
        host_lock_withs = self._host_lock_with_nodes(func)
        assert host_lock_withs, (
            f"{verb_name} opens no host-lock-guarded `with` at all"
        )

        host_lock_names: set[str] = set()
        for n in ast.walk(func):
            if (
                isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and self._is_host_lock_call(n.value)
            ):
                host_lock_names.add(n.targets[0].id)

        for w in host_lock_withs:
            ledger_idx = None
            host_idx = None
            for idx, item in enumerate(w.items):
                ctx = item.context_expr
                if self._is_ledger_write_call(ctx):
                    ledger_idx = idx
                if self._is_host_lock_call(ctx) or (
                    isinstance(ctx, ast.Name) and ctx.id in host_lock_names
                ):
                    host_idx = idx

            assert ledger_idx is not None, (
                f"{verb_name}: the host-lock-guarded `with` at line "
                f"{w.lineno} does not ALSO carry `_ledger_write(home)` as "
                "one of its own context managers — the two locks are "
                "opened by SEPARATE `with` statements, so Python's own "
                "left-to-right `with A, B:` evaluation no longer pins "
                "their relative order (M-1, code gate r2)"
            )
            assert host_idx is not None
            assert ledger_idx < host_idx, (
                f"{verb_name}: `_ledger_write` is item {ledger_idx} and "
                f"the host lock is item {host_idx} in the SAME `with` at "
                f"line {w.lineno} — ledger must come FIRST (§4.5b: "
                "ledger→host, always; M-1, code gate r2). Two verbs "
                "disagreeing on this order can deadlock each other for "
                "the full gitops.COMMIT_LOCK_TIMEOUT (150s)."
            )


class TestM1LockOrderRuntimeProbe:
    """M-1 (code gate r2): the gate's own runtime deadlock proof, kept
    alive as a permanent regression test rather than a throwaway probe.

    Before this fold, `route`/`route_direct` opened `with _ledger_write(
    home), gitops.host_lock(...):` (ledger first) while `supersede`/
    `graduate` opened the host lock, THEN `_ledger_write` nested inside
    it (host first) — two OS processes running one of each, contending
    for the SAME ledger AND the SAME host, could each acquire their own
    FIRST lock and then block forever on the other's, until
    `gitops.COMMIT_LOCK_TIMEOUT` (150s) finally kills one of them.
    `serve` schedules producers exactly this way (the spec's own reason
    for REC12), so this was not hypothetical.

    Both sides patch `gitops.COMMIT_LOCK_TIMEOUT` down to a few seconds
    before acquiring anything — this process directly, the holder
    subprocess via an equivalent line in its own script — so a
    REGRESSION of this fix fails fast (a `GitOpsError` within single-
    digit seconds) instead of hanging the suite for 150s. A passing run
    means what it always meant: the two calls serialized cleanly on the
    shared ledger lock, exactly as `TestPlain5RealOsLock` already proves
    for the host lock alone.
    """

    def test_two_verbs_on_the_same_host_and_ledger_never_deadlock(self, tmp_path):
        plain_host = tmp_path / "m1-order-host"
        plain_host.mkdir()
        (plain_host / "CLAUDE.md").write_text("# plain host\n", encoding="utf-8")

        env = make_env(tmp_path)
        host_add(env.ledger, plain_host, "project", mode="plain")
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(gitops, "COMMIT_LOCK_TIMEOUT", 6.0)

        old_record = make_behavior(scope="project", record_id="lrn-000000e1")
        new_record = make_behavior(scope="project", record_id="lrn-000000e2")
        create_record(env.ledger, old_record, project_path=plain_host)
        create_record(env.ledger, new_record, project_path=plain_host)
        # e1 routed first (sequential, no contention yet) so `supersede`
        # below has a real host-side target to retire; e2 stays pending
        # -- `supersede`'s replacement need only EXIST (RESOLVABLE_STATUSES).
        verbs.route(env.ledger, "lrn-000000e1", dest="claude-md", no_push=True)

        marker = tmp_path / "m1-order-holder-in-lock.txt"
        cli_src = str(Path(__file__).resolve().parents[1] / "src")
        holder_script = tmp_path / "m1_order_holder.py"
        holder_record = make_behavior(scope="project", record_id="lrn-000000e3")
        create_record(env.ledger, holder_record, project_path=plain_host)
        holder_script.write_text(
            "import sys, time\n"
            f"sys.path.insert(0, {cli_src!r})\n"
            "from pathlib import Path\n"
            "from self_learn import verbs, gitops\n"
            "gitops.COMMIT_LOCK_TIMEOUT = 6.0\n"
            "_real_apply = verbs._apply_target\n"
            "def _slow_apply(*a, **kw):\n"
            f"    Path({str(marker)!r}).write_text('IN LOCK', encoding='utf-8')\n"
            "    time.sleep(1.2)\n"
            "    return _real_apply(*a, **kw)\n"
            "verbs._apply_target = _slow_apply\n"
            f"verbs.route({str(env.ledger)!r}, 'lrn-000000e3', "
            "dest='claude-md:rules:topic-m1-order', no_push=True)\n",
            encoding="utf-8",
        )
        proc = subprocess.Popen(["python3", str(holder_script)])
        try:
            deadline = time.monotonic() + 3.0
            while not marker.is_file() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert marker.is_file(), (
                "holder process never entered its critical section"
            )

            # `supersede` on the SAME ledger AND the SAME host, while the
            # holder (a `route`) still holds both locks: under the r1-fold
            # bug this would deadlock (each process holding its own first
            # lock, waiting on the other's) until the patched 6s timeout;
            # under the fix, this call simply waits behind the holder's
            # ~1.2s critical section on the shared ledger lock.
            t0 = time.monotonic()
            result = verbs.supersede(
                env.ledger, "lrn-000000e1", "lrn-000000e2", no_push=True
            )
            elapsed = time.monotonic() - t0
            assert result is not None
            assert elapsed < 4.0, (
                f"supersede took {elapsed:.2f}s against a concurrent "
                "route() on the same host+ledger -- expected ~1.2s "
                "(serialized behind the holder's own critical section), "
                "not a lock-order deadlock heading for the (patched) "
                "COMMIT_LOCK_TIMEOUT"
            )
            assert elapsed > 0.6, (
                "supersede completed suspiciously fast -- it should have "
                "had to wait for the holder's ~1.2s critical section, "
                "meaning it may not have actually contended for the SAME "
                "locks at all (a false pass this probe must not give)"
            )
        finally:
            proc.wait(timeout=8)
            monkeypatch.undo()


# ================================================================
# U-hostmode Phase 2 -- the retired-dotfiles-module-deleted-
# wholesale criteria (CHEZ1, CHEZ2, CHEZ3, CHEZ5, CHEZ6). One named
# test per [B] criterion, each discriminating -- run RED against a
# synthetic restore of the deleted surface where the criterion names
# a mutation, never "by construction". The UI-side criteria (UIC1-5)
# live in ui/tests/ (a separate venv this suite cannot import).
#
# CHEZ6 (below) sweeps `cli/src`/`ui/src`/`ui/templates`/`ui/tests`/
# `ui/static` for zero mentions of the retired module's name, and
# `cli/tests` for exactly the 37-hit accounted total -- EXCLUDING this
# file BY PATH (gate r1-N1, 2026-08-28): an earlier version instead
# built the name from `"chez" + "moi"` so its own grep could never see
# it, which also made the instrument structurally blind to the one
# file most likely to reintroduce a real dependency the same way. This
# file now spells the name plainly, like any other test file, and is
# simply not counted -- greppable, not evasive.
# ================================================================

_RETIRED_MODULE = "chezmoi"


class TestChez1AdoptVerbGone:
    def test_adopt_verb_is_an_unknown_command(self, capsys):
        """CHEZ1: the adopt verb no longer exists -- passing its old
        name as the CLI's first argument exits through argparse's own
        unknown-command path (exit 2, "invalid choice"), and the verb
        function itself is absent from the module entirely."""
        argv0 = f"{_RETIRED_MODULE}-adopt"
        rc = cli.main([argv0, "/x"])
        assert rc == 2  # argparse's own usage-error exit, caught and
        # returned by `_main` (never a raw SystemExit — cli.py:2024)
        err = capsys.readouterr().err
        assert f"invalid choice: {argv0!r}" in err
        verb_name = f"{_RETIRED_MODULE}_adopt"
        assert not hasattr(verbs, verb_name)
        assert verb_name not in verbs.__all__


class TestChez2ModuleGone:
    def test_import_raises_module_not_found(self):
        """CHEZ2: importing the retired module raises
        ``ModuleNotFoundError`` -- it is deleted, not merely
        unimported."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"self_learn.{_RETIRED_MODULE}")

    def test_verbs_has_zero_bin_parameters_for_the_retired_module(self):
        """CHEZ2: ``verbs.py`` contains zero occurrences of the retired
        module's ``_bin`` parameter, on any function. Positive control
        (measured during the build, against this same AST sweep re-run
        over 50fa815's verbs.py): 12 function signatures carried the
        parameter before this unit -- ``_resolve_rules_target``,
        ``_resolve_target``, ``_retirement_preflight``,
        ``_retirement_host_phase``, ``_apply_target``, ``_host_phase``,
        ``route``, ``route_direct``, ``commit_drift``, ``graduate``,
        ``supersede``, ``recompile`` (the adopt verb itself, a 13th, is
        deleted outright -- CHEZ1)."""
        tree = ast.parse(Path(verbs.__file__).read_text(encoding="utf-8"))
        param_name = f"{_RETIRED_MODULE}_bin"
        hits = [
            (node.name, node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            for arg in node.args.args + node.args.kwonlyargs
            if arg.arg == param_name
        ]
        assert hits == [], hits

    def test_census_two_hits_only_in_compilers_comments(self):
        """CHEZ2's own check instrument: a case-insensitive grep for
        the retired module's name over ``cli/src`` returns EXACTLY 2
        -- the two ``compilers.py:596``/``:605`` prose comments CHEZ6
        exempts -- and a grep for the bin-parameter name returns 0.
        Positive control at 50fa815 (§2.10a): 205 and 42."""
        src_root = Path(verbs.__file__).resolve().parent.parent  # .../cli/src
        out = subprocess.run(
            ["grep", "-rn", "-i", _RETIRED_MODULE, str(src_root)],
            capture_output=True, text=True,
        ).stdout
        hits = [ln for ln in out.splitlines() if ln]
        assert len(hits) == 2, hits
        assert all("compilers.py" in ln for ln in hits), hits

        bin_out = subprocess.run(
            ["grep", "-rn", f"{_RETIRED_MODULE}_bin", str(src_root)],
            capture_output=True, text=True,
        ).stdout
        assert [ln for ln in bin_out.splitlines() if ln] == []


class TestChez3NoAdoptHintChannel:
    def test_offer_adopt_and_adopt_hint_absent_from_source(self):
        """CHEZ3: the ``offer_adopt``/``adopt_hint`` channel is gone --
        neither literal appears anywhere in ``verbs.py`` (its only
        carrier was a result class defined only in, and deleted along
        with, the retired module)."""
        verbs_src = Path(verbs.__file__).read_text(encoding="utf-8")
        assert "offer_adopt" not in verbs_src
        assert "adopt_hint" not in verbs_src

    def test_user_scope_route_prints_no_adopt_hint(self, tmp_path):
        """CHEZ3: a real user-scope route through the plain-host path
        emits no adopt-shaped warning -- there is no channel left to
        fire one. Positive control (§2.10a's deleted Obligation 11, at
        50fa815): an UNMANAGED user-scope RULES route with
        ``offer_adopt=True`` DID carry an adopt hint in
        ``result.warnings``; a plain ``claude-md`` destination like
        this one never threaded ``offer_adopt`` even then, and now
        nothing in the codebase can set the field at all."""
        env = make_env(tmp_path)
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user")
        create_record(env.ledger, record)
        result = verbs.route(
            env.ledger, record.id, dest="claude-md", no_push=True,
            user_claude_md=target,
        )
        assert not any("adopt" in w.lower() for w in result.warnings)


class TestChez5ExceptTuplesShrink:
    def test_host_phase_errors_is_exactly_the_four_classes(self):
        """CHEZ5: ``verbs._HOST_PHASE_ERRORS`` (verbs.py:2561 at
        50fa815) shrinks to exactly ``CompileError``, ``GitOpsError``,
        ``VerbError``, ``OSError`` -- the two retired-module exception
        classes are gone."""
        from self_learn.compilers import CompileError

        assert verbs._HOST_PHASE_ERRORS == (
            CompileError, gitops.GitOpsError, verbs.VerbError, OSError,
        )

    def test_no_except_clause_anywhere_names_the_retired_module(self):
        """CHEZ5: no ``except`` clause in ``cli.py``, ``verbs.py``, or
        ``teach.py`` names either of the retired module's exception
        classes -- covers ``cli._cmd_verb``'s and ``cli._cmd_host``'s
        tuples directly, the two this criterion names besides
        ``_HOST_PHASE_ERRORS`` and ``teach.py:722-723``'s (all four
        shrink together)."""
        needle = _RETIRED_MODULE[0].upper() + _RETIRED_MODULE[1:]
        for mod in (cli, verbs, teach):
            tree = ast.parse(Path(str(mod.__file__)).read_text(encoding="utf-8"))
            hits = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is not None:
                    names = [n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)]
                    hits += [n for n in names if needle in n]
            assert hits == [], (mod.__name__, hits)

    def test_mutation_m51_shape_cannot_survive_cli_load(self):
        """CHEZ5, mutation M51's shape (leave ``teach.py:75``'s
        retired-module import line after deleting the module) verified
        structurally rather than by re-planting the mutation:
        ``self_learn.cli`` imports ``self_learn.teach``, and this whole
        test module already imported ``self_learn.cli`` at collection
        time (see the module-level import above) -- an unremoved
        import of the deleted module anywhere on that load path would
        have raised ``ModuleNotFoundError`` before any test in this
        file could run, exactly M51's predicted failure ("ImportError
        at CLI load; the whole CLI suite errors")."""
        assert cli.__name__ == "self_learn.cli"
        assert teach.__name__ == "self_learn.teach"


class TestChez6CensusZeroRetiredModuleLiterals:
    def test_census_by_tree(self):
        """CHEZ6 (gate r1-N1/N2, 2026-08-28): zero mentions of the
        retired module's name (case-insensitive) remain in ``cli/src``,
        ``ui/src``, ``ui/templates``, ``ui/tests``, ``ui/static`` --
        except the two ``compilers.py`` prose comments (``cli/src``).
        ``ui/static`` carries zero -- `ui/static/app.js:517,519`'s two
        dated retirement comments say "adopt", never the retired
        module's name, so `UIC5` (which sweeps that word) accounts for
        them instead. ``cli/tests``, EXCLUDING this file by path, carries
        exactly 37: the UN3-protected pre-existing test/class names in
        ``test_commit_drift.py`` (11), ``test_hosting.py`` (1), and
        ``test_verbs.py`` (10 -- two pre-existing class names, the
        module-name half of their identifiers, and the docstring prose
        naming them; see that file's own ``TestRouteUserScope*``
        classes) that UN3's name-set freeze forbids renaming in EITHER
        phase (§9: "Explicitly NOT touchable, either phase") -- an
        earlier build pass renamed four of those names and deleted a
        fifth test outright before this instrument caught the UN3
        violation; they are restored, literally, under their original
        names -- plus two files documenting an UNRELATED, real-world
        safety guard against the actual externally-installed dotfiles
        CLI tool's ``cd`` subcommand (``test_route_hook.py``, 12;
        ``test_hook_compiler.py``, 2) and one absence-assertion in
        ``test_composer.py`` (1) that already proves the analyst
        doctrine text does NOT mention it -- plus, as of U-armor
        (2026-08-28, ``test_armor.py``), two literal-text EXM1
        grammar-control example strings that cite the real
        ``chezmoi.py`` deletion this same file documents (one
        negative control isolating the date/anchor grammar halves,
        one worked-example reason string for the shipped
        ``test_wr7`` exemption) -- 11+1+10+12+2+1+2 = 39, the
        exact accounted total. THIS file (``test_hostmode.py``) is
        excluded from the ``cli/tests`` sweep BY PATH, not by evading
        its own grep (gate r1-N1) -- ``_RETIRED_MODULE`` above is a
        plain literal, and this docstring spells the protected names out
        directly, same as any other file. ``docs/`` is explicitly NOT
        swept (OUT-4). Positive control at 50fa815 (§2.10a): for the
        original five trees, 205/12/7/343/43; ``ui/static`` was not
        separately measured before this fold."""
        plugin_root = Path(__file__).resolve().parents[2]  # plugins/self-learn
        trees = {
            "cli/src": plugin_root / "cli" / "src",
            "cli/tests": plugin_root / "cli" / "tests",
            "ui/src": plugin_root / "ui" / "src",
            "ui/templates": plugin_root / "ui" / "templates",
            "ui/tests": plugin_root / "ui" / "tests",
            "ui/static": plugin_root / "ui" / "static",
        }
        excluded_by_path = {Path(__file__).resolve()}

        def _hits(path):
            out = subprocess.run(
                ["grep", "-rn", "-i", _RETIRED_MODULE, str(path)],
                capture_output=True, text=True,
            ).stdout
            hits = []
            for ln in out.splitlines():
                if not ln:
                    continue
                file_part = ln.split(":", 1)[0]
                if Path(file_part).resolve() in excluded_by_path:
                    continue
                hits.append(ln)
            return hits

        assert len(_hits(trees["cli/src"])) == 2
        assert len(_hits(trees["cli/tests"])) == 39
        assert _hits(trees["ui/src"]) == []
        assert _hits(trees["ui/templates"]) == []
        assert _hits(trees["ui/tests"]) == []
        assert _hits(trees["ui/static"]) == []  # zero chezmoi mentions; the 2 dated retirement comments say "adopt", not "chezmoi" (UIC5 sweeps that word)
