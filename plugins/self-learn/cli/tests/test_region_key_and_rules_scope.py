"""Two live defects found on 2026-10-03, fixed together.

1. The compile record keyed an entry by FILE, but one host CLAUDE.md
   carries two marker pairs (managed, pointer). Whichever kind wrote last
   owned the hash, and the other kind's next route read ``edited`` -- a
   false "hand-edited" refusal. An entry now identifies (path, region
   kind); records written under the old path-only key read compatibly.
2. A rules route of a record with no globs rewrote the topic file's
   ``paths:`` frontmatter away, even when it superseded a path-scoped
   record. It now inherits the predecessor's globs, accepts explicit
   ``--rules-path`` globs, and refuses to unscope a path-scoped file
   unless told to.
"""

from __future__ import annotations

import pytest

from self_learn import cli, compiled, verbs
from self_learn.hosts import slug_for
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record

from support import make_behavior, make_env, proposal_dict

OLD = "lrn-0000aaaa"
NEW = "lrn-0000bbbb"
THIRD = "lrn-0000cccc"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def seed(env, record_id, *, supersedes=None, instruction="Stop the container first."):
    record = make_behavior(scope="project", record_id=record_id, instruction=instruction)
    if supersedes is not None:
        record.set_supersedes(supersedes)
    create_record(env.ledger, record, project_path=env.host)
    return record


def bucket(env):
    return env.ledger / "projects" / slug_for(env.host)


def routed(env, record_id):
    return Record.from_path(bucket(env) / "resolved" / f"{record_id}.md")


def rules_file(env, topic="t"):
    return env.host / ".claude" / "rules" / f"{topic}.md"


def host_slug_of(env):
    from self_learn.hosts import host_slug

    return host_slug(env.ledger, env.host, scope_kind="project")


def verdicts(env):
    """(managed, pointer) verdicts of the host CLAUDE.md against the record."""
    text = (env.host / "CLAUDE.md").read_text(encoding="utf-8")
    data = compiled.load_record(env.ledger, host_slug_of(env))
    out = []
    for kind in ("managed", "pointer"):
        region = compiled.region_bytes(text, kind)
        key = compiled.region_key(env.host, env.host / "CLAUDE.md", kind)
        entry = compiled.entry_for(data, key, region=kind)
        out.append(
            compiled.verdict_for(entry, None if region is None else compiled.sha256_hex(region))
        )
    return tuple(out)


# ======================================================================
# Bug 1 -- one entry per (path, region kind)
# ======================================================================


class TestRegionKeyIdentifiesTheRegionKind:
    def test_keys_differ_per_kind_for_one_file(self, tmp_path):
        host = tmp_path / "h"
        host.mkdir()
        target = host / "CLAUDE.md"
        assert compiled.region_key(host, target, "managed") == "CLAUDE.md"
        assert compiled.region_key(host, target, "pointer") == "CLAUDE.md#pointer"
        assert compiled.region_key(host, target) == "CLAUDE.md"  # default stays managed
        # whole-file kinds share with nothing, so they keep the bare path
        assert compiled.region_key(host, target, "reference") == "CLAUDE.md"

    def test_writing_one_kind_leaves_the_other_kinds_entry_alone(self, tmp_path):
        common = dict(based_on_sha256=None, nbytes=1, by="t", host="h", mode="plain")
        compiled.write_entry(tmp_path, "s", "CLAUDE.md#pointer", region="pointer", sha256="p1", **common)
        compiled.write_entry(tmp_path, "s", "CLAUDE.md", region="managed", sha256="m1", **common)
        data = compiled.load_record(tmp_path, "s")
        assert compiled.entry_for(data, "CLAUDE.md", region="managed")["sha256"] == "m1"
        assert compiled.entry_for(data, "CLAUDE.md#pointer", region="pointer")["sha256"] == "p1"


class TestLegacyPathOnlyRecordsReadCompatibly:
    def _legacy(self, tmp_path, region):
        # the pre-fix shape: ONE bare-path entry, tagged by its region field
        path = compiled.compiled_record_path(tmp_path, "s")
        path.parent.mkdir(parents=True)
        path.write_text(
            "host: /h\nmode: git\ntargets:\n  CLAUDE.md:\n"
            f"    region: {region}\n    sha256: aaa\n    based_on_sha256: aaa\n"
            "    bytes: 3\n    at: 2026-10-01T00:00:00Z\n    by: route lrn-x\n",
            encoding="utf-8",
        )
        return compiled.load_record(tmp_path, "s")

    def test_a_legacy_pointer_entry_is_the_pointer_entry_not_the_managed_one(self, tmp_path):
        data = self._legacy(tmp_path, "pointer")
        assert compiled.entry_for(data, "CLAUDE.md#pointer", region="pointer")["sha256"] == "aaa"
        assert compiled.entry_for(data, "CLAUDE.md", region="managed") is None
        assert compiled.verdict_for(compiled.entry_for(data, "CLAUDE.md", region="managed"), "bbb") == "unknown"
        assert compiled.verdict_for(compiled.entry_for(data, "CLAUDE.md#pointer", region="pointer"), "aaa") == "clean"

    def test_a_legacy_managed_entry_still_answers_the_managed_lookup(self, tmp_path):
        data = self._legacy(tmp_path, "managed")
        assert compiled.entry_for(data, "CLAUDE.md", region="managed")["sha256"] == "aaa"
        assert compiled.entry_for(data, "CLAUDE.md#pointer", region="pointer") is None

    def test_writing_managed_over_a_legacy_pointer_entry_moves_it_instead_of_losing_it(self, tmp_path):
        self._legacy(tmp_path, "pointer")
        compiled.write_entry(
            tmp_path, "s", "CLAUDE.md", region="managed", sha256="mmm",
            based_on_sha256=None, nbytes=1, by="t", host="/h", mode="git",
        )
        data = compiled.load_record(tmp_path, "s")
        assert sorted(data["targets"]) == ["CLAUDE.md", "CLAUDE.md#pointer"]
        assert data["targets"]["CLAUDE.md"]["sha256"] == "mmm"
        assert data["targets"]["CLAUDE.md#pointer"]["sha256"] == "aaa"
        assert data["targets"]["CLAUDE.md#pointer"]["region"] == "pointer"

    def test_writing_pointer_over_a_legacy_pointer_entry_drops_the_bare_one(self, tmp_path):
        self._legacy(tmp_path, "pointer")
        compiled.write_entry(
            tmp_path, "s", "CLAUDE.md#pointer", region="pointer", sha256="new",
            based_on_sha256="aaa", nbytes=1, by="t", host="/h", mode="git",
        )
        data = compiled.load_record(tmp_path, "s")
        assert list(data["targets"]) == ["CLAUDE.md#pointer"]
        assert data["targets"]["CLAUDE.md#pointer"]["sha256"] == "new"


class TestRoutingOneKindNeverRefusesTheOther:
    """The live failure: a pointer-owning entry made the next managed
    route read ``edited`` and refuse a file nobody had hand-edited."""

    def _route_pointer(self, env, rid="lrn-0000a001"):
        seed(env, rid)
        verbs.route(env.ledger, rid, dest="reference", no_push=True)

    def _route_managed(self, env, rid):
        seed(env, rid, instruction=f"Do the thing {rid}.")
        return verbs.route(env.ledger, rid, dest="claude-md", no_push=True)

    def test_pointer_entry_then_managed_route(self, env):
        self._route_pointer(env)
        assert verdicts(env)[1] == "clean"  # positive control: the pointer region exists and is recorded
        result = self._route_managed(env, "lrn-0000a002")
        assert result.commit_sha
        assert verdicts(env) == ("clean", "clean")

    def test_managed_entry_then_pointer_route(self, env):
        self._route_managed(env, "lrn-0000a002")
        assert verdicts(env)[0] == "clean"
        self._route_pointer(env)
        assert verdicts(env) == ("clean", "clean")

    def test_alternating_routes_keep_both_clean(self, env):
        self._route_pointer(env, "lrn-0000a001")
        self._route_managed(env, "lrn-0000a002")
        self._route_pointer_again(env, "lrn-0000a003")
        self._route_managed(env, "lrn-0000a004")
        assert verdicts(env) == ("clean", "clean")

    def _route_pointer_again(self, env, rid):
        seed(env, rid)
        verbs.route(env.ledger, rid, dest="reference", no_push=True)

    def test_a_real_hand_edit_inside_the_managed_markers_still_refuses(self, env):
        """Negative control: the fix must not have made the gate vacuous."""
        self._route_pointer(env)
        self._route_managed(env, "lrn-0000a002")
        claude = env.host / "CLAUDE.md"
        text = claude.read_text(encoding="utf-8")
        assert "do the thing lrn-0000a002" in text
        claude.write_text(text.replace("do the thing lrn-0000a002", "a hand-edited thing"), encoding="utf-8")
        import subprocess

        subprocess.run(["git", "-C", str(env.host), "commit", "-qam", "hand edit"], check=True)
        seed(env, "lrn-0000a003", instruction="Another.")
        with pytest.raises(verbs.VerbError, match="hand-edited|edited"):
            verbs.route(env.ledger, "lrn-0000a003", dest="claude-md", no_push=True)

    def test_legacy_pointer_only_record_does_not_block_the_first_managed_route(self, env):
        """The live shape: a pre-fix record holding ONE bare entry tagged
        pointer, the managed region on disk already self-learn-compiled."""
        self._route_pointer(env)
        slug = host_slug_of(env)
        data = compiled.load_record(env.ledger, slug)
        pointer = dict(data["targets"]["CLAUDE.md#pointer"])
        path = compiled.compiled_record_path(env.ledger, slug)
        path.write_text(
            f"host: {env.host}\nmode: git\ntargets:\n  CLAUDE.md:\n"
            + "".join(f"    {k}: {v if v is not None else 'null'}\n" for k, v in pointer.items()),
            encoding="utf-8",
        )
        legacy = compiled.load_record(env.ledger, slug)
        assert list(legacy["targets"]) == ["CLAUDE.md"]  # positive control: legacy shape in place
        result = self._route_managed(env, "lrn-0000a002")
        assert result.commit_sha
        assert verdicts(env) == ("clean", "clean")


# ======================================================================
# Bug 2 -- a rules route without globs
# ======================================================================

GLOBS = ["a/**", "b/*.css"]


def route_pathed(env, rid=OLD, topic="t", globs=GLOBS):
    (env.host / "a").mkdir(exist_ok=True)
    (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")
    (env.host / "b").mkdir(exist_ok=True)
    (env.host / "b" / "x.css").write_text("x", encoding="utf-8")
    seed(env, rid)
    write_proposal(
        env.ledger, rid,
        proposal_dict(scope="project", destination="claude-md", variant="rules",
                      rules_topic=topic, rules_paths=globs),
    )
    return verbs.route(env.ledger, rid, no_push=True)


def paths_on_disk(env, topic="t"):
    from self_learn.compilers import read_paths_frontmatter

    return list(read_paths_frontmatter(rules_file(env, topic).read_text(encoding="utf-8")))


class TestSupersedingRecordInheritsTheGlobs:
    def test_route_inherits_and_names_the_source(self, env):
        route_pathed(env)
        assert paths_on_disk(env) == sorted(GLOBS)  # positive control
        seed(env, NEW, supersedes=OLD)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:t", no_push=True)
        routing = routed(env, NEW).routing
        assert routing["rules_paths"] == GLOBS
        assert routing["rules_paths_from"] == OLD
        assert paths_on_disk(env) == sorted(GLOBS)

    def test_dead_inherited_globs_do_not_block_and_are_kept(self, env):
        route_pathed(env)
        (env.host / "a" / "f.txt").unlink()
        (env.host / "b" / "x.css").unlink()
        seed(env, NEW, supersedes=OLD)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:t", no_push=True)
        routing = routed(env, NEW).routing
        assert routing["rules_paths"] == GLOBS
        assert routing["allow_empty_glob"] is True
        assert routing["glob_bypass_reason"] == "zero-match"
        assert paths_on_disk(env) == sorted(GLOBS)

    def test_own_globs_win_over_inheritance(self, env):
        route_pathed(env)
        seed(env, NEW, supersedes=OLD)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:t", rules_paths=["a/**"], no_push=True)
        routing = routed(env, NEW).routing
        assert routing["rules_paths"] == ["a/**"]
        assert "rules_paths_from" not in routing

    def test_a_chain_carries_the_globs_forward(self, env):
        route_pathed(env)
        seed(env, NEW, supersedes=OLD)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:t", no_push=True)
        seed(env, THIRD, supersedes=NEW)
        verbs.route(env.ledger, THIRD, dest="claude-md:rules:t", no_push=True)
        assert routed(env, THIRD).routing["rules_paths"] == GLOBS
        assert routed(env, THIRD).routing["rules_paths_from"] == NEW

    def test_different_topic_does_not_inherit(self, env):
        route_pathed(env)
        seed(env, NEW, supersedes=OLD)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:other", no_push=True)
        routing = routed(env, NEW).routing
        assert "rules_paths" not in routing and "rules_paths_from" not in routing

    def test_a_non_rules_route_does_not_inherit(self, env):
        route_pathed(env)
        seed(env, NEW, supersedes=OLD)
        verbs.route(env.ledger, NEW, dest="claude-md", no_push=True)
        assert "rules_paths_from" not in (routed(env, NEW).routing or {})

    def test_dry_run_previews_the_inheritance_without_refusing(self, env):
        route_pathed(env)
        seed(env, NEW, supersedes=OLD)
        dr = verbs.route_dry_run(env.ledger, NEW, dest="claude-md:rules:t")
        assert dr.ok and not dr.would_refuse

    def test_teach_route_path_inherits_too(self, env):
        route_pathed(env)
        record = make_behavior(scope="project", record_id=NEW, instruction="Replacement.")
        record.set_supersedes(OLD)
        verbs.route_direct(env.ledger, record, dest="claude-md:rules:t", project_path=env.host, no_push=True)
        routing = routed(env, NEW).routing
        assert routing["rules_paths"] == GLOBS and routing["rules_paths_from"] == OLD
        assert paths_on_disk(env) == sorted(GLOBS)


class TestExplicitGlobs:
    def test_route_cli_flag_repeatable(self, env):
        (env.host / "a").mkdir()
        (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")
        (env.host / "b").mkdir()
        (env.host / "b" / "x.css").write_text("x", encoding="utf-8")
        seed(env, OLD)
        rc = cli.main(["route", OLD, "--dest", "claude-md:rules:t",
                       "--rules-path", "a/**", "--rules-path", "b/*.css", "--no-push"])
        assert rc == 0
        assert routed(env, OLD).routing["rules_paths"] == ["a/**", "b/*.css"]
        assert paths_on_disk(env) == ["a/**", "b/*.css"]

    def test_globs_are_reachability_checked_and_allow_empty_glob_bypasses(self, env):
        seed(env, OLD)
        rc = cli.main(["route", OLD, "--dest", "claude-md:rules:t", "--rules-path", "nope/**", "--no-push"])
        assert rc != 0
        assert (bucket(env) / "pending" / f"{OLD}.md").is_file()
        rc = cli.main(["route", OLD, "--dest", "claude-md:rules:t", "--rules-path", "nope/**",
                       "--allow-empty-glob", "--no-push"])
        assert rc == 0
        assert routed(env, OLD).routing["allow_empty_glob"] is True

    def test_shape_problems_are_refused_before_anything_is_written(self, env):
        seed(env, OLD)
        rc = cli.main(["route", OLD, "--dest", "claude-md:rules:t", "--rules-path", "/abs/**", "--no-push"])
        assert rc != 0
        rc = cli.main(["route", OLD, "--dest", "claude-md", "--rules-path", "a/**", "--no-push"])
        assert rc != 0  # globs only go with claude-md:rules:<topic>
        assert (bucket(env) / "pending" / f"{OLD}.md").is_file()
        assert not rules_file(env).exists()

    def test_teach_route_cli_flag(self, env, monkeypatch):
        (env.host / "a").mkdir()
        (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")
        monkeypatch.chdir(env.host)
        rc = cli.main([
            "teach", "--project", "--type", "behavior", "--kind", "anti-pattern",
            "--trigger", "About to edit the thing.", "--instruction", "Do not.",
            "--route", "--dest", "claude-md:rules:t", "--rules-path", "a/**", "--no-push",
        ])
        assert rc == 0
        assert paths_on_disk(env) == ["a/**"]

    def test_teach_rules_path_needs_route(self, env, monkeypatch):
        monkeypatch.chdir(env.host)
        rc = cli.main([
            "teach", "--project", "--type", "behavior", "--kind", "anti-pattern",
            "--trigger", "About to edit the thing.", "--instruction", "Do not.",
            "--rules-path", "a/**",
        ])
        assert rc != 0


class TestRerouteGivesAPathlessLessonItsGlobsBack:
    """The live repair shape: a lesson routed unpathed into a rules topic
    (the file lost its paths:) is given globs by a same-topic reroute."""

    def test_same_topic_reroute_with_new_globs_is_a_real_change(self, env):
        # force the pathless outcome: a record whose predecessor carries no globs
        seed(env, OLD)
        verbs.route(env.ledger, OLD, dest="claude-md:rules:t", no_push=True)
        assert paths_on_disk(env) == []  # positive control: unscoped
        (env.host / "a").mkdir()
        (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")
        verbs.reroute(env.ledger, OLD, dest="claude-md:rules:t", rules_paths=["a/**"], no_push=True)
        assert routed(env, OLD).routing["rules_paths"] == ["a/**"]
        assert paths_on_disk(env) == ["a/**"]

    def test_same_topic_reroute_with_the_same_globs_is_still_nothing_to_change(self, env):
        seed(env, OLD)
        verbs.route(env.ledger, OLD, dest="claude-md:rules:t", no_push=True)
        with pytest.raises(verbs.VerbError, match="nothing to change"):
            verbs.reroute(env.ledger, OLD, dest="claude-md:rules:t", no_push=True)

    def test_reroute_cli_flags(self, env):
        seed(env, OLD)
        verbs.route(env.ledger, OLD, dest="claude-md:rules:t", no_push=True)
        rc = cli.main(["reroute", OLD, "--dest", "claude-md:rules:t",
                       "--rules-path", "gone/**", "--allow-empty-glob", "--no-push"])
        assert rc == 0
        routing = routed(env, OLD).routing
        assert routing["rules_paths"] == ["gone/**"] and routing["allow_empty_glob"] is True
        assert paths_on_disk(env) == ["gone/**"]


class TestUnscopingAPathScopedFileIsRefused:
    def test_refuses_before_any_write_and_the_file_keeps_its_paths(self, env):
        route_pathed(env)
        before = rules_file(env).read_text(encoding="utf-8")
        seed(env, NEW)  # no predecessor, no globs
        with pytest.raises(verbs.VerbError, match="path-scoped"):
            verbs.route(env.ledger, NEW, dest="claude-md:rules:t", no_push=True)
        assert (bucket(env) / "pending" / f"{NEW}.md").is_file()
        assert rules_file(env).read_text(encoding="utf-8") == before

    def test_dry_run_reports_it(self, env):
        route_pathed(env)
        seed(env, NEW)
        dr = verbs.route_dry_run(env.ledger, NEW, dest="claude-md:rules:t")
        assert not dr.ok
        assert any("path-scoped" in r for r in dr.would_refuse)

    def test_allow_unpathed_is_the_deliberate_way_through(self, env):
        route_pathed(env)
        seed(env, NEW)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:t", allow_unpathed=True, no_push=True)
        assert paths_on_disk(env) == []

    def test_cli_refuses_then_flag_allows(self, env):
        route_pathed(env)
        seed(env, NEW)
        assert cli.main(["route", NEW, "--dest", "claude-md:rules:t", "--no-push"]) != 0
        assert paths_on_disk(env) == sorted(GLOBS)
        assert cli.main(["route", NEW, "--dest", "claude-md:rules:t", "--allow-unpathed", "--no-push"]) == 0
        assert paths_on_disk(env) == []

    def test_an_unpathed_topic_stays_routable_without_the_flag(self, env):
        """Negative control: the refusal keys on the file ALREADY being
        path-scoped, not on every globless rules route."""
        seed(env, NEW)
        result = verbs.route(env.ledger, NEW, dest="claude-md:rules:fresh", no_push=True)
        assert result.commit_sha

    def test_reroute_that_would_unscope_is_refused(self, env):
        route_pathed(env)
        seed(env, NEW)
        verbs.route(env.ledger, NEW, dest="claude-md", no_push=True)
        with pytest.raises(verbs.VerbError, match="path-scoped"):
            verbs.reroute(env.ledger, NEW, dest="claude-md:rules:t", no_push=True)


class TestGateFindings:
    """Blind-gate findings F1/F2: a reroute never swaps a record's own
    globs for its predecessor's; inheritance never crosses projects."""

    def test_same_topic_reroute_keeps_the_records_own_globs(self, env):
        route_pathed(env)  # OLD: GLOBS
        seed(env, NEW, supersedes=OLD)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:t", rules_paths=["a/**"], no_push=True)
        with pytest.raises(verbs.VerbError, match="nothing to change"):
            verbs.reroute(env.ledger, NEW, dest="claude-md:rules:t", no_push=True)
        assert routed(env, NEW).routing["rules_paths"] == ["a/**"]

    def test_inheritance_does_not_cross_projects(self, env, tmp_path):
        from self_learn.hosts import slug_for
        from support import init_repo, commit_all

        route_pathed(env)
        host2 = tmp_path / "host2"
        init_repo(host2)
        (host2 / "CLAUDE.md").write_text("# h2\n", encoding="utf-8")
        commit_all(host2, "seed")
        reg = env.ledger / "hosts.yaml"
        reg.write_text(reg.read_text(encoding="utf-8") + f"  - path: {host2}\n", encoding="utf-8")
        commit_all(env.ledger, "second host")
        rec = make_behavior(scope="project", record_id=NEW)
        rec.set_supersedes(OLD)
        create_record(env.ledger, rec, project_path=host2)
        verbs.route(env.ledger, NEW, dest="claude-md:rules:t", no_push=True)
        b2 = env.ledger / "projects" / slug_for(host2) / "resolved" / f"{NEW}.md"
        routing = Record.from_path(b2).routing
        assert "rules_paths" not in routing and "rules_paths_from" not in routing
