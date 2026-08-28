"""U-xscope: the enumeration contract for managed-section compiles (spec
`docs/specs/self-learn/drafts/u-xscope-cross-scope-recompile-spec.md`,
committed cf97571).

A skill-md route and a new-skill route can name the SAME physical
SKILL.md: every live plugin under a registered skills root lays out
``plugins/<name>/skills/<name>/``, so :func:`~self_learn.hosts.
skill_dir_for`'s glob (the skill-md leg) and the new-skill formula
``<skills_root>/plugins/<name>/skills/<name>/SKILL.md`` (the new-skill
leg) resolve to the SAME file for every one of them. Pre-fix, each
destination's compile set was built independently and
``compile_managed_text`` regenerates the WHOLE managed section from that
set — so a route on one destination DELETED the other destination's
entries (the ff45510 defect: testing-methodology went 5 lines -> 1).

``support.make_env``'s default fixture seeds ``plugins/<n>-plugin/skills/
<n>/`` — the "-plugin" suffix means the DEFAULT sandbox never collides
(§7.1's own hazard). Every fixture in this file that needs the collision
builds it THROUGH THE VERBS, per §7.1's recipe: route N `user`-scope
records `--dest new-skill:<name>` (scaffolds `plugins/<name>/skills/
<name>/SKILL.md`, no "-plugin" suffix), then a `skill:<name>`-scope
record `--dest skill-md` (`skill_dir_for`'s glob resolves to the SAME
scaffolded directory).

``verbs.managed_target_for`` is the single resolver both
``selfcheck._target_for`` (read-only enumeration) and ``verbs._compile_set``
(compile-set gathering) consume — this file exercises both consumers.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

import pytest

from self_learn import selfcheck, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.hosts import host_add, load_hosts, skill_dir_for
from self_learn.ledger import Bucket, discover_buckets
from self_learn.ledger_ops import create_record, stamp_proposal, write_proposal
from self_learn.records import Record
from support import (
    commit_all,
    git,
    init_repo,
    make_behavior,
    make_env,
    proposal_dict,
)

NEW_SKILL_NAME = "tm"  # mirrors the spec's own worked example name

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

#: §2.7/§6.1's anchored entry-id scan — a bare `lrn-` substring scan
#: invents EXTRAs from prose mentions inside other entries' text (§2.7's
#: own measured example). NIT 9: `re.MULTILINE` is mandatory, or `^…$`
#: matches nothing and every target reads as empty.
_ENTRY_ID_RE = re.compile(r"^- .*\*\((lrn-[0-9a-f]{8})\)\*\s*$", re.MULTILINE)


def entry_ids(text: str) -> list[str]:
    """The anchored entry-id list, in file order, WITHIN the managed
    section only."""
    begin = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER)
    return _ENTRY_ID_RE.findall(text[begin:end])


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    """Sentinel goes to a per-test XDG cache, never the real ~/.cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)  # seeds skills=("s",) -> plugins/s-plugin/skills/s
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.marketplace = self.host / ".claude-plugin" / "marketplace.json"
        self.marketplace.parent.mkdir()
        self.marketplace.write_text(
            json.dumps(MARKETPLACE_SEED, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        git(self.host, "add", "-A")
        git(self.host, "commit", "-q", "-m", "marketplace seed")

    def marketplace_text(self) -> str:
        return self.marketplace.read_text(encoding="utf-8")

    def marketplace_names(self) -> list[str]:
        return [p["name"] for p in json.loads(self.marketplace_text())["plugins"]]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def seed(env, rid, scope, trigger):
    record = make_behavior(scope=scope, record_id=rid, trigger=trigger)
    create_record(env.home, record)
    return record


def skill_md_path(env, name=NEW_SKILL_NAME):
    return env.host / "plugins" / name / "skills" / name / "SKILL.md"


def build_fixture(env, *, new_skill_ids, skill_md_id, name=NEW_SKILL_NAME):
    """§7.1's recipe: route ``len(new_skill_ids)`` `user`-scope records
    via ``--dest new-skill:<name>`` (scaffolds ``plugins/<name>/skills/
    <name>/SKILL.md`` — NO "-plugin" suffix, the live claude-skills
    layout), then ONE `skill:<name>`-scope record via ``--dest
    skill-md`` (`skill_dir_for`'s glob resolves to the SAME scaffolded
    directory — this is route 9's actual history). Returns the shared
    SKILL.md path."""
    for rid in new_skill_ids:
        seed(env, rid, "user", f"new-skill trigger for {rid}")
        verbs.route(env.home, rid, dest=f"new-skill:{name}", no_push=True)
    seed(env, skill_md_id, f"skill:{name}", "skill-md trigger, routed last")
    verbs.route(env.home, skill_md_id, dest="skill-md", no_push=True)
    return skill_md_path(env, name)


def build_reverse_fixture(env, *, skill_md_id, new_skill_ids, name="tm-reverse"):
    """T2's reverse-order variant: `skill-md` FIRST. `_resolve_target`'s
    skill-md leg requires the target to already exist as a FILE, so this
    manually seeds an unmanaged `SKILL.md` (the scaffold only creates one
    on a fresh `new-skill` route) — the skill-md route then bootstraps
    the managed section into it, which is what lets the SECOND
    (`new-skill`) route pass M3-9's foreign-plugin collision check."""
    skill_dir = env.host / "plugins" / name / "skills" / name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(f"# {name} skill\n\nAuthored prose.\n", encoding="utf-8")
    commit_all(env.host, f"seed {name} SKILL.md for the reverse-order fixture")

    seed(env, skill_md_id, f"skill:{name}", "skill-md trigger, routed first")
    verbs.route(env.home, skill_md_id, dest="skill-md", no_push=True)
    for rid in new_skill_ids:
        seed(env, rid, "user", f"new-skill trigger for {rid}, routed second")
        verbs.route(env.home, rid, dest=f"new-skill:{name}", no_push=True)
    return skill_md


def _resolved_record_path(env, rid: str) -> Path:
    """Locate a ROUTED record's resolved file across every bucket (delta-r3
    T1 fix). This file's fixtures span the user bucket (new-skill routes)
    and a skill bucket (the skill-md route), so no single fixed location
    works — walk `discover_buckets` the same way `_target_matched_records`
    does and match on the resolved filename."""
    for bucket in discover_buckets(env.home):
        candidate = bucket.path / "resolved" / f"{rid}.md"
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no resolved record found for {rid}")


def _stamp_routed_at(env, rid: str, routed_at: str) -> None:
    """Overwrite ONE resolved record's `routing.routed_at` in place,
    preserving every other routing key (delta-r3 T1 fix, spec §7.2
    mechanism (a) as corrected by NIT C). `_eligible` sorts on
    `(routed_at, id)` with SECOND-granular timestamps — five routes
    landing in one wall-clock second is a coin flip, not a guarantee (the
    gate measured 10/30 failures), so the tiebreak this test exists to
    prove must be forced by an explicit stamp, never left to timing."""
    path = _resolved_record_path(env, rid)
    record = Record.from_path(path)
    routing = record.routing
    routing["routed_at"] = routed_at
    record.set_routing(routing)
    record.write(path)


# ============================================================== §7.1 / T0


class TestT0FixtureControl:
    """T0 (§7.1): MUST run first, and must be an EXPLICIT assertion, not
    a comment — the `skill-md` spec's target and the `new-skill` spec's
    target `resolve()` to the SAME path. If they do not, every test below
    is vacuous."""

    def test_skill_md_and_new_skill_specs_resolve_to_the_same_path(self, env):
        build_fixture(env, new_skill_ids=["lrn-00010001"], skill_md_id="lrn-00010002")

        skill_bucket_dir = env.home / "skills" / NEW_SKILL_NAME
        skill_spec = verbs._resolve_target(
            env.home, skill_bucket_dir, f"skill:{NEW_SKILL_NAME}", "skill-md", None,
        )
        user_bucket_dir = env.home / "user"
        newskill_spec = verbs._resolve_target(
            env.home, user_bucket_dir, "user", "new-skill", NEW_SKILL_NAME,
        )
        assert skill_spec.target.resolve() == newskill_spec.target.resolve()

    def test_mutation_3_the_default_noncolliding_skill_does_not_collide(self, tmp_path):
        # §7.6 mutation 3: the SAME question, pointed at a make_env-seeded
        # skill ("plugins/s-plugin/skills/s") instead of the scaffolded
        # one -- must come out FALSE, proving T0's assertion is a real,
        # failing-capable check, not a green-by-construction tautology.
        # (Raw path arithmetic, not `_resolve_target`: the default
        # fixture has no marketplace.json, so a `new-skill` route would
        # refuse at preflight before ever reaching target computation —
        # the collision question is pure path arithmetic and does not
        # need routing preflight to answer.)
        sandbox = make_env(tmp_path)  # plugins/s-plugin/skills/s
        hosts = load_hosts(sandbox.ledger)
        skill_md_target = (skill_dir_for(hosts, "s") / "SKILL.md").resolve()
        new_skill_target = (
            hosts.skills_root / "plugins" / "s" / "skills" / "s" / "SKILL.md"
        ).resolve()
        assert skill_md_target != new_skill_target


# ======================================================== §7.2 / T1 - T5


class TestT1FiveEntriesPinnedOrder:
    """T1 (§7.2): with the §7.1 fixture, the section contains exactly 5
    entries, in `(routed_at, id)` order. `_eligible` ties on `routed_at`
    (second-granular) and falls through to the id tiebreak — ids are
    PINNED via `make_behavior(record_id=…)` and chosen so the skill-md id
    (always routed LAST by the §7.1 recipe) sorts into the MIDDLE of the
    id order, not the end — a route-order-preserving bug would put it
    last regardless.

    Delta-r3 fix (gate MAJOR, spec §7.2 mechanism (a) as corrected by
    NIT C): the FIRST version of this test trusted wall-clock route
    timing to land all 5 routes inside one second, letting the id
    tiebreak decide. That is a coin flip, not a guarantee — the gate
    measured 10 failures in 30 isolated runs and reproduced the second
    boundary straddle deterministically. `_stamp_routed_at` now pins
    `routed_at` explicitly on all 5 resolved records BEFORE an explicit
    `recompile`, so the tie (and therefore the id tiebreak this test
    exists to prove) is forced, never left to timing. A second test below
    proves the OTHER half of `_eligible`'s key: `routed_at` still governs
    over id when the two differ."""

    def test_five_entries_in_id_sorted_order(self, env):
        ns_ids = ["lrn-500000dd", "lrn-500000bb", "lrn-500000cc", "lrn-500000aa"]
        skill_md_id = "lrn-500000c5"  # sorts between "bb" and "cc"
        skill_md = build_fixture(env, new_skill_ids=ns_ids, skill_md_id=skill_md_id)

        # Force the tie: all 5 land at the IDENTICAL routed_at, so only
        # the id tiebreak can decide the order (delta-r3, NIT C).
        for rid in ns_ids + [skill_md_id]:
            _stamp_routed_at(env, rid, "2026-08-23T12:00:00Z")
        verbs.recompile(env.home, no_push=True)

        ids = entry_ids(skill_md.read_text(encoding="utf-8"))
        assert len(ids) == 5
        assert ids == sorted(ns_ids + [skill_md_id])

    def test_routed_at_still_governs_over_id_when_it_differs(self, env):
        # Straddle case (delta-r3): deliberately give the id-sorted-LAST
        # record the id-sorted-FIRST id, or vice versa, mismatching id
        # order and routed_at order, and assert the ROUTED_AT order wins
        # — proving the primary key of `(routed_at, id)` is still routed_at,
        # not a test artifact of always tying it.
        ns_ids = ["lrn-500001dd", "lrn-500001bb", "lrn-500001cc", "lrn-500001aa"]
        skill_md_id = "lrn-500001c5"
        skill_md = build_fixture(env, new_skill_ids=ns_ids, skill_md_id=skill_md_id)
        all_ids = ns_ids + [skill_md_id]

        # Stamp routed_at in the REVERSE of id-sorted order: the
        # id-sorted-last id gets the earliest routed_at, and so on.
        id_sorted = sorted(all_ids)
        reversed_order = list(reversed(id_sorted))
        for position, rid in enumerate(reversed_order):
            _stamp_routed_at(env, rid, f"2026-08-23T12:00:{position:02d}Z")
        verbs.recompile(env.home, no_push=True)

        ids = entry_ids(skill_md.read_text(encoding="utf-8"))
        assert ids == reversed_order, (
            f"routed_at must govern over id when they differ: "
            f"expected {reversed_order} (routed_at order), got {ids}"
        )
        assert ids != id_sorted, "the straddle stimulus must actually invert id order"


class TestT2DirectionSymmetry:
    """T2 (§7.2): the REVERSE route order — `skill-md` first, then a
    `new-skill` record into the same name. Pre-fix, THIS direction fails
    first: `_apply_new_skill`'s regenerate-the-section compile drops the
    `skill-md` line the moment the `new-skill` route lands."""

    def test_skill_md_first_then_new_skill_both_survive(self, env):
        skill_md_id = "lrn-51000001"
        new_id = "lrn-51000002"
        skill_md = build_reverse_fixture(
            env, skill_md_id=skill_md_id, new_skill_ids=[new_id],
        )
        assert set(entry_ids(skill_md.read_text(encoding="utf-8"))) == {
            skill_md_id, new_id,
        }


class TestT3RecompileRestores:
    """T3 (§7.2): from the T1 state, delete the four `new-skill` lines by
    hand (mirroring `ff45510`), commit the host, run `recompile`, and
    assert the five entries are back AND the entry reports
    `changed=True` — the §5 repair, in-sandbox."""

    def test_recompile_restores_and_reports_changed(self, env):
        ns_ids = ["lrn-52000001", "lrn-52000002", "lrn-52000003", "lrn-52000004"]
        skill_md_id = "lrn-52000005"
        skill_md = build_fixture(env, new_skill_ids=ns_ids, skill_md_id=skill_md_id)

        text = skill_md.read_text(encoding="utf-8")
        for rid in ns_ids:
            text = re.sub(
                rf"^- .*\*\({re.escape(rid)}\)\*\s*\n?", "", text, flags=re.MULTILINE,
            )
        skill_md.write_text(text, encoding="utf-8")
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "simulate ff45510-shaped drift")
        assert entry_ids(skill_md.read_text(encoding="utf-8")) == [skill_md_id]

        result = verbs.recompile(env.home, no_push=True)

        after_ids = set(entry_ids(skill_md.read_text(encoding="utf-8")))
        assert after_ids == set(ns_ids) | {skill_md_id}
        matching = [e for e in result.entries if e.target == skill_md.resolve()
                    or e.target == skill_md]
        assert matching, f"no recompile entry for {skill_md}: {result.entries}"
        assert any(e.changed for e in matching), (
            "recompile must report changed=True for the repaired target"
        )


class TestT4RecompileIdempotent:
    """T4 (§7.2): a second, immediate `recompile` reports NO change for
    any target — mirrors `TestSharedClaudeMdUnion::
    test_recompile_preserves_union_and_is_idempotent`."""

    def test_second_recompile_reports_no_change(self, env):
        ns_ids = ["lrn-53000001", "lrn-53000002", "lrn-53000003", "lrn-53000004"]
        skill_md_id = "lrn-53000005"
        build_fixture(env, new_skill_ids=ns_ids, skill_md_id=skill_md_id)

        result = verbs.recompile(env.home, no_push=True)
        assert not any(e.changed for e in result.entries)


class TestT5RetirementCrossesTheBoundary:
    """T5 (§7.2): proves the union did NOT become an append-only
    accumulator. Graduating a `new-skill` record drops ONLY its line;
    superseding the `skill-md` record drops ONLY its line — each in the
    OTHER destination's direction, crossing the boundary the union
    spans."""

    def test_graduate_a_new_skill_record_drops_only_its_line(self, env):
        ns_ids = ["lrn-54000001", "lrn-54000002"]
        skill_md_id = "lrn-54000003"
        skill_md = build_fixture(env, new_skill_ids=ns_ids, skill_md_id=skill_md_id)

        verbs.graduate(env.home, ns_ids[0], no_push=True)

        ids = set(entry_ids(skill_md.read_text(encoding="utf-8")))
        assert ns_ids[0] not in ids
        assert ns_ids[1] in ids and skill_md_id in ids

    def test_supersede_the_skill_md_record_drops_only_its_line(self, env):
        ns_ids = ["lrn-54100001", "lrn-54100002"]
        skill_md_id = "lrn-54100003"
        skill_md = build_fixture(env, new_skill_ids=ns_ids, skill_md_id=skill_md_id)

        replacement = make_behavior(
            scope=f"skill:{NEW_SKILL_NAME}", record_id="lrn-54100099",
            trigger="replacement trigger",
        )
        create_record(env.home, replacement)
        verbs.supersede(env.home, skill_md_id, "lrn-54100099", no_push=True)

        ids = set(entry_ids(skill_md.read_text(encoding="utf-8")))
        assert skill_md_id not in ids
        assert set(ns_ids) <= ids


# ================================================== §7.3 positive controls


class TestT6NonCollidingSkillKeepsExactIds:
    """T6 (§7.3): a skill whose only records are `skill-md` in its OWN
    bucket (the hypr-doctor shape, no collision) keeps EXACTLY those ids
    — the direct guard against 'the obvious equality fix blanks every
    skill bucket' (§3.4's bucket-identity hazard, ids named not just
    counted)."""

    def test_non_colliding_skill_section_has_exactly_its_own_ids(self, env):
        ids = ["lrn-55000001", "lrn-55000002"]
        for rid in ids:
            seed(env, rid, "skill:s", f"trigger for {rid}")
            verbs.route(env.home, rid, dest="skill-md", no_push=True)
        s_skill_md = env.host / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md"
        assert set(entry_ids(s_skill_md.read_text(encoding="utf-8"))) == set(ids)


class TestT7NewSkillOnlySkillNoLedgerBucket:
    """T7 (§7.3): a skill with ONLY `new-skill` records and NO ledger
    bucket at all (every record filed in `user/`, never a `skill:`
    scope) keeps exactly those ids — guards against a fix that
    enumerates from `discover_buckets`' NAMES instead of from records."""

    def test_new_skill_only_skill_keeps_its_ids_with_no_ledger_bucket(self, env):
        name = "orphan-skill"
        ids = ["lrn-56000001", "lrn-56000002"]
        for rid in ids:
            seed(env, rid, "user", f"trigger for {rid}")
            verbs.route(env.home, rid, dest=f"new-skill:{name}", no_push=True)
        assert not (env.home / "skills" / name).exists()
        assert set(entry_ids(skill_md_path(env, name).read_text(encoding="utf-8"))) == set(ids)


class TestT8UserOverrideBlockerOneGuard:
    """T8 (§7.3, the BLOCKER-1 guard): user `CLAUDE.md` routed through an
    explicit `user_claude_md` OVERRIDE. Asserts (1) ids land in the
    override file, (2) the real `~/.claude/CLAUDE.md` is never read or
    written, (3) a second route preserves the first line, (4) no
    cross-scope leak — for BOTH the plain leg and the `rules` variant.

    Verified hermetically: `verbs.DEFAULT_USER_CLAUDE_MD` is monkeypatched
    to a DECOY sentinel this test owns — this suite must never touch the
    operator's real file, even to prove it was untouched. Dropping the
    override-threading (mutation §7.6(4)) makes the code fall back to
    `DEFAULT_USER_CLAUDE_MD` — the decoy — so 'the decoy stays untouched'
    goes RED exactly when it should. This is the test that would have
    caught the resolver-parameterization blanking (§3.4(4))."""

    def _decoy(self, tmp_path, monkeypatch):
        decoy = tmp_path / "decoy-real-claude-md" / "CLAUDE.md"
        decoy.parent.mkdir()
        decoy.write_text("# decoy — must never be touched\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", decoy)
        return decoy, decoy.read_text(encoding="utf-8")

    def test_managed_target_for_override_parameter_direct(self, tmp_path, monkeypatch):
        """Direct unit coverage of the `user_claude_md` keyword on
        `managed_target_for` itself (mutation §7.6(4): drop the
        parameter -> TypeError here, immediately). Also proves the RULES
        leg uses the override DIRECTLY as the `_user_rules_dir` base —
        never re-derived from `spec.target` (the forbidden shortcut,
        which would misresolve for the rules leg specifically)."""
        decoy, decoy_before = self._decoy(tmp_path, monkeypatch)
        override = tmp_path / "direct-override" / "CLAUDE.md"
        override.parent.mkdir()
        bucket = Bucket(path=tmp_path / "unused-user-bucket", scope="user", name="user")

        plain = make_behavior(scope="user", record_id="lrn-60000001")
        plain.set_routing({
            "destination": "claude-md", "by": "human",
            "routed_at": "2026-08-23T00:00:00Z",
        })
        plain.set_status("routed")

        assert (
            verbs.managed_target_for(tmp_path, bucket, plain, user_claude_md=override)
            == override.resolve()
        )
        assert verbs.managed_target_for(tmp_path, bucket, plain) == decoy.resolve()

        rules = make_behavior(scope="user", record_id="lrn-60000002")
        rules.set_routing({
            "destination": "claude-md", "by": "human", "variant": "rules",
            "rules_topic": "direct-topic", "routed_at": "2026-08-23T00:00:00Z",
        })
        rules.set_status("routed")

        expected_rules_target = (
            override.parent / "rules" / "direct-topic.md"
        ).resolve()
        assert (
            verbs.managed_target_for(tmp_path, bucket, rules, user_claude_md=override)
            == expected_rules_target
        )
        assert verbs.managed_target_for(tmp_path, bucket, rules) == (
            decoy.parent / "rules" / "direct-topic.md"
        ).resolve()
        assert decoy.read_text(encoding="utf-8") == decoy_before

    def test_plain_user_claude_md_override_round_trip(self, tmp_path, env, monkeypatch):
        decoy, decoy_before = self._decoy(tmp_path, monkeypatch)
        override = tmp_path / "override-claude-md" / "CLAUDE.md"
        override.parent.mkdir()
        override.write_text("# user conduct\n", encoding="utf-8")

        RID1, RID2 = "lrn-10000001", "lrn-10000002"
        seed(env, RID1, "user", "trigger one for the plain user leg")
        verbs.route(
            env.home, RID1, dest="claude-md", user_claude_md=override,
            no_push=True,
        )

        text = override.read_text(encoding="utf-8")
        assert set(entry_ids(text)) == {RID1}
        assert decoy.read_text(encoding="utf-8") == decoy_before
        first_line = text.splitlines()[0]

        seed(env, RID2, "user", "trigger two for the plain user leg")
        verbs.route(
            env.home, RID2, dest="claude-md", user_claude_md=override,
            no_push=True,
        )
        text2 = override.read_text(encoding="utf-8")
        assert text2.splitlines()[0] == first_line
        assert set(entry_ids(text2)) == {RID1, RID2}
        assert decoy.read_text(encoding="utf-8") == decoy_before

        PROJ = "lrn-10000003"
        proj_record = make_behavior(
            scope="project", record_id=PROJ, trigger="project-scope trigger",
        )
        create_record(env.home, proj_record, project_path=env.host)
        verbs.route(env.home, PROJ, dest="claude-md", no_push=True)
        assert PROJ not in override.read_text(encoding="utf-8")
        host_claude_md = env.host / "CLAUDE.md"
        assert PROJ in host_claude_md.read_text(encoding="utf-8")
        assert RID1 not in host_claude_md.read_text(encoding="utf-8")

    def test_user_rules_variant_override_round_trip(self, tmp_path, env, monkeypatch):
        decoy, decoy_before = self._decoy(tmp_path, monkeypatch)
        override = tmp_path / "override-claude-md" / "CLAUDE.md"
        override.parent.mkdir()
        override.write_text("# user conduct\n", encoding="utf-8")
        rules_target = override.parent / "rules" / "xscope-topic.md"

        RID1, RID2 = "lrn-20000001", "lrn-20000002"
        seed(env, RID1, "user", "rules trigger one")
        verbs.route(
            env.home, RID1, dest="claude-md:rules:xscope-topic",
            user_claude_md=override, no_push=True,
        )

        text = rules_target.read_text(encoding="utf-8")
        assert set(entry_ids(text)) == {RID1}
        assert decoy.read_text(encoding="utf-8") == decoy_before
        assert not (decoy.parent / "rules").exists()
        first_line = text.splitlines()[0]

        seed(env, RID2, "user", "rules trigger two")
        verbs.route(
            env.home, RID2, dest="claude-md:rules:xscope-topic",
            user_claude_md=override, no_push=True,
        )
        text2 = rules_target.read_text(encoding="utf-8")
        assert text2.splitlines()[0] == first_line
        assert set(entry_ids(text2)) == {RID1, RID2}
        assert decoy.read_text(encoding="utf-8") == decoy_before

        PLAIN = "lrn-20000003"
        seed(env, PLAIN, "user", "plain trigger")
        verbs.route(
            env.home, PLAIN, dest="claude-md", user_claude_md=override,
            no_push=True,
        )
        assert PLAIN not in rules_target.read_text(encoding="utf-8")
        assert PLAIN in override.read_text(encoding="utf-8")
        assert RID1 not in override.read_text(encoding="utf-8")


class TestT9ProjectClaudeMdPositiveControl:
    """T9 (§7.3): project-scope `claude-md` keeps exactly its own ids.
    The dual-role union's own coverage
    (`test_retirement_cleanup.py::TestSharedClaudeMdUnion`) is NOT
    duplicated or edited here — §3.5/AC#6 require it pass unmodified,
    verified by the full suite run, not by this file."""

    def test_project_scope_claude_md_keeps_exactly_its_ids(self, env, tmp_path):
        proj = tmp_path / "t9-proj-repo"
        init_repo(proj)
        (proj / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(proj, "proj seed")
        host_add(env.home, proj, "project")

        ids = ["lrn-57000001", "lrn-57000002"]
        for rid in ids:
            record = make_behavior(scope="project", record_id=rid, trigger=f"trigger {rid}")
            create_record(env.home, record, project_path=proj)
            verbs.route(env.home, rid, dest="claude-md", no_push=True)

        text = (proj / "CLAUDE.md").read_text(encoding="utf-8")
        assert set(entry_ids(text)) == set(ids)


class TestT10RulesLocalPartitionWithCollision:
    """T10 (§7.3): a `rules:<topic>` record, a project `local` record,
    and a plain user `claude-md` record stay in THREE distinct,
    non-overlapping sections — exercised alongside a LIVE skill-md/
    new-skill collision (§7.1's fixture) in the SAME sandbox, the
    combination `test_a2_rules_local.py`'s existing coverage does not."""

    def test_three_claude_md_variants_stay_isolated_alongside_a_collision(
        self, env, tmp_path
    ):
        build_fixture(env, new_skill_ids=["lrn-58000001"], skill_md_id="lrn-58000002")

        override = tmp_path / "t10-user-claude-md" / "CLAUDE.md"
        override.parent.mkdir()
        override.write_text("# user\n", encoding="utf-8")

        plain_id = "lrn-58000003"
        seed(env, plain_id, "user", "plain trigger")
        verbs.route(
            env.home, plain_id, dest="claude-md", user_claude_md=override,
            no_push=True,
        )

        rules_id = "lrn-58000004"
        seed(env, rules_id, "user", "rules trigger")
        verbs.route(
            env.home, rules_id, dest="claude-md:rules:t10-topic",
            user_claude_md=override, no_push=True,
        )

        proj = tmp_path / "t10-proj"
        init_repo(proj)
        (proj / "README.md").write_text("x\n", encoding="utf-8")
        (proj / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")
        commit_all(proj, "seed + gitignore CLAUDE.local.md")
        host_add(env.home, proj, "project")
        local_id = "lrn-58000005"
        local_record = make_behavior(
            scope="project", record_id=local_id, trigger="local trigger",
        )
        create_record(env.home, local_record, project_path=proj)
        verbs.route(env.home, local_id, dest="claude-md:local", no_push=True)

        plain_ids = set(entry_ids(override.read_text(encoding="utf-8")))
        rules_ids = set(
            entry_ids((override.parent / "rules" / "t10-topic.md").read_text(encoding="utf-8"))
        )
        local_ids = set(entry_ids((proj / "CLAUDE.local.md").read_text(encoding="utf-8")))

        assert plain_ids == {plain_id}
        assert rules_ids == {rules_id}
        assert local_ids == {local_id}
        assert plain_ids.isdisjoint(rules_ids)
        assert plain_ids.isdisjoint(local_ids)
        assert rules_ids.isdisjoint(local_ids)


class TestT11EmptyIsStillEmpty:
    """T11 (§7.3): a skill whose only record is SUPERSEDED compiles to a
    ZERO-entry section — the fix must not resurrect
    retired entries. Critically (§7.6(2)'s own warning): asserting
    emptiness ALONE would also pass under a mutation that blindly forces
    `_compile_set` to return `[]` for skill targets, testing nothing.
    (An attempt to prove this by inspecting `_compile_set`'s RAW,
    pre-`_eligible` output does not work here: `verbs.supersede`/
    `verbs.graduate` both set the retired record's `status` itself to
    `"superseded"` — via `resolve_record(home, id, "superseded", …)` —
    so `_compile_set`'s own `status == "routed"` filter, unchanged since
    before this unit, already excludes it upstream of `_eligible`; the
    raw set is legitimately empty too.) Instead this proves the SAME
    target is reachable — not universally blind — by routing the
    (until-now pending) replacement into it immediately after and
    asserting the section recovers to exactly that one id. A blanking
    mutation (§7.6(2): force `_compile_set` to return `[]` for skill
    targets, unconditionally) fails at THAT second assertion."""

    def test_superseded_only_skill_is_empty_then_the_same_target_recovers(self, env):
        old_id = "lrn-59000001"
        new_id = "lrn-59000002"
        seed(env, old_id, "skill:s", "old trigger")
        verbs.route(env.home, old_id, dest="skill-md", no_push=True)
        replacement = make_behavior(
            scope="skill:s", record_id=new_id, trigger="new trigger",
        )
        create_record(env.home, replacement)
        verbs.supersede(env.home, old_id, new_id, no_push=True)

        s_skill_md = env.host / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md"
        text = s_skill_md.read_text(encoding="utf-8")
        assert entry_ids(text) == []
        assert old_id not in text

        # POSITIVE CONTROL, same target: the replacement (pending until
        # now) routes cleanly into the SAME SKILL.md -- proving the
        # emptiness above is because everything retired, never because
        # `_compile_set` is blind to this target altogether.
        verbs.route(env.home, new_id, dest="skill-md", no_push=True)
        text2 = s_skill_md.read_text(encoding="utf-8")
        assert entry_ids(text2) == [new_id]


# ============================================ §7.4 negative controls / T13b


class TestT12ReferencesUntouched:
    """T12 (§7.4): a `reference`-routed record in a skill that ALSO has a
    section: its id appears in `references/LEARNINGS.md` and NOT as an
    entry line in the section; the section's id set is unchanged.

    A `reference` route never itself triggers a compile — so without a
    forced `recompile` afterward, this test's final assertion only ever
    re-reads the section text the EARLIER `skill-md` route already wrote,
    never exercising the (possibly mutated) target-derivation path for
    this target a second time. The explicit `recompile` call below closes
    that gap (delta-r2 NIT 2): it forces a fresh compile through the same
    `managed_target_for`/`_target_matched_records`/`_compile_set` path,
    so a defect there would show up here even though `reference` itself
    never calls compile."""

    def test_reference_record_never_enters_the_section(self, env):
        skill_md_id = "lrn-60000001"
        seed(env, skill_md_id, "skill:s", "skill-md trigger")
        verbs.route(env.home, skill_md_id, dest="skill-md", no_push=True)

        ref_id = "lrn-60000002"
        seed(env, ref_id, "skill:s", "reference trigger")
        verbs.route(env.home, ref_id, dest="reference", no_push=True)

        verbs.recompile(env.home, no_push=True)  # force a fresh compile (NIT 2)

        s_skill_md = env.host / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md"
        assert set(entry_ids(s_skill_md.read_text(encoding="utf-8"))) == {skill_md_id}
        learnings = (
            env.host / "plugins" / "s-plugin" / "skills" / "s" / "references" / "LEARNINGS.md"
        )
        assert ref_id in learnings.read_text(encoding="utf-8")


class TestT13HooksUntouched:
    """T13 (§7.4): a `hook`-routed record never appears in any managed
    section (a hook target is a script file under `hooks/`, not a
    SKILL.md/CLAUDE.md — this also guards against a future
    destination-set widening pulling hook records into `C(T)`). Like
    T12, a `hook` route never itself triggers a compile, so the explicit
    `recompile` call below (delta-r2 NIT 2) forces a fresh pass through
    the target-derivation path before the final assertion, rather than
    trusting section text left over from the earlier `skill-md` route."""

    def test_hook_record_never_enters_a_section(self, env):
        skill_md_id = "lrn-61000001"
        seed(env, skill_md_id, "skill:s", "skill-md trigger")
        verbs.route(env.home, skill_md_id, dest="skill-md", no_push=True)

        hook_id = "lrn-61000002"
        record = make_behavior(
            scope="skill:s", record_id=hook_id,
            trigger="About to edit .storage/ while HA is running.",
        )
        create_record(env.home, record)
        write_proposal(env.home, hook_id, proposal_dict(
            scope="skill:s", destination="hook", alternates=["skill-md"],
            hook={
                "tools": ["Edit", "Write"],
                "path_regex": r"\.storage/",
                "deny_message": "stop the HA container first",
            },
            examples={
                "allow": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/configuration.yaml"}},
                    {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
                ],
                "deny": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/core.config"}},
                    {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/auth"}},
                ],
            },
        ))
        stamp_proposal(env.home, hook_id)
        verbs.route(env.home, hook_id, no_push=True)

        verbs.recompile(env.home, no_push=True)  # force a fresh compile (NIT 2)

        s_skill_md = env.host / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md"
        text = s_skill_md.read_text(encoding="utf-8")
        assert set(entry_ids(text)) == {skill_md_id}
        assert hook_id not in text


class TestT13bSelfcheckResolvedParity:
    """T13b (§7.4, MAJOR 2 fold): selfcheck's target set must be resolved
    — proven with a stimulus `resolve()` ACTUALLY changes (a SYMLINKED
    skills root), not merely `key == key.resolve()` against an ordinary
    tmp_path (which is never a symlink, so that assertion is vacuous
    under §7.6(5)'s exact mutation — this is the round-1 gap, MAJOR 2)."""

    def test_target_set_survives_a_symlinked_skills_root(self, tmp_path, env):
        skill_md = build_fixture(
            env, new_skill_ids=["lrn-40000001"], skill_md_id="lrn-40000002",
        )
        assert skill_md.is_file()

        alias = tmp_path / "host-alias"
        alias.symlink_to(env.host)
        (env.home / "hosts.yaml").write_text(
            f"skills_root: {alias}\nprojects:\n  - path: {env.host}\n",
            encoding="utf-8",
        )
        commit_all(env.home, "repoint skills_root through a symlink")

        hosts = load_hosts(env.home)
        unresolved = skill_dir_for(hosts, NEW_SKILL_NAME) / "SKILL.md"
        # POSITIVE CONTROL: resolve() is demonstrably NOT identity here —
        # unlike a bare tmp_path, this fixture actually exercises §3.2.1.
        assert unresolved != unresolved.resolve()

        targets = selfcheck._section_targets(env.home)
        matching = [t for t in targets if t == unresolved.resolve()]
        assert matching, f"no resolved target matches; got {list(targets)}"
        assert unresolved not in targets, (
            "an UNresolved (symlink-bearing) path leaked into the target "
            "set — §3.2.1's single normalization point was bypassed"
        )
        assert selfcheck._check_compiler(targets)[0] is True
        assert selfcheck._check_markers(targets)[0] is True
        ok, reason = selfcheck._check_drift(env.home)
        assert ok is True, reason


# ================================================== §7.5 apply-path parity


class TestT14P3Parity:
    """T14 (§7.5, P3 of §4.1): two `TargetSpec`s resolving to the SAME
    target must produce the IDENTICAL compile set — same ids, same
    ORDER, compared as a LIST, not merely as a set."""

    def test_both_specs_produce_the_identical_id_list(self, env):
        ns_ids = ["lrn-62000001", "lrn-62000002"]
        skill_md_id = "lrn-62000003"
        build_fixture(env, new_skill_ids=ns_ids, skill_md_id=skill_md_id)

        skill_bucket_dir = env.home / "skills" / NEW_SKILL_NAME
        skill_spec = verbs._resolve_target(
            env.home, skill_bucket_dir, f"skill:{NEW_SKILL_NAME}", "skill-md", None,
        )
        user_bucket_dir = env.home / "user"
        newskill_spec = verbs._resolve_target(
            env.home, user_bucket_dir, "user", "new-skill", NEW_SKILL_NAME,
        )
        ids_from_skill_md = [r.id for r in verbs._compile_set(env.home, skill_spec)]
        ids_from_new_skill = [r.id for r in verbs._compile_set(env.home, newskill_spec)]
        assert ids_from_skill_md == ids_from_new_skill
        assert set(ids_from_skill_md) == set(ns_ids) | {skill_md_id}


class TestT15ScaffoldNotReseeded:
    """T15 (§7.5, §4.3, MAJOR 4): after the FIRST `new-skill` route
    scaffolds `plugin.json`/`marketplace.json`, every LATER route into
    the same target — including a `skill-md` route from an ENTIRELY
    DIFFERENT bucket, which changes `records[0]` (`_compile_set`'s output
    is bucket-walk order, and `discover_buckets` walks `skills/*` BEFORE
    `user/`, so a skill-md record sorts ahead of an earlier-routed
    new-skill record even though it is routed LAST) — must leave BOTH
    files byte-identical to what the first route wrote."""

    def test_plugin_json_and_marketplace_survive_a_later_cross_bucket_route(self, env):
        first_id = "lrn-63000001"
        seed(env, first_id, "user", "first new-skill trigger")
        verbs.route(env.home, first_id, dest=f"new-skill:{NEW_SKILL_NAME}", no_push=True)

        manifest = env.host / "plugins" / NEW_SKILL_NAME / ".claude-plugin" / "plugin.json"
        manifest_before = manifest.read_text(encoding="utf-8")
        marketplace_before = env.marketplace_text()

        second_id = "lrn-63000002"
        seed(env, second_id, "user", "second new-skill trigger")
        verbs.route(env.home, second_id, dest=f"new-skill:{NEW_SKILL_NAME}", no_push=True)
        assert manifest.read_text(encoding="utf-8") == manifest_before
        assert env.marketplace_text() == marketplace_before

        skill_md_id = "lrn-63000003"
        seed(env, skill_md_id, f"skill:{NEW_SKILL_NAME}", "skill-md trigger, routed last")
        verbs.route(env.home, skill_md_id, dest="skill-md", no_push=True)

        bucket_dir = env.home / "skills" / NEW_SKILL_NAME
        spec = verbs._resolve_target(
            env.home, bucket_dir, f"skill:{NEW_SKILL_NAME}", "skill-md", None,
        )
        records = verbs._compile_set(env.home, spec)
        assert records[0].id == skill_md_id, (
            f"premise unmet — records[0] is {records[0].id!r}, not the "
            "cross-bucket skill-md record; T15 would be vacuous"
        )

        assert manifest.read_text(encoding="utf-8") == manifest_before
        assert env.marketplace_text() == marketplace_before


class TestT15bStagedPathSetUnchanged:
    """T15b (§7.5, §4.2, MAJOR 6, AC#7): the union changes the COMPILE
    SET a host apply writes FROM, never the staged-PATH set it writes
    TO — a `skill-md` spec still stages exactly `[spec.target]`, and a
    `new-skill` spec still stages exactly `[target, manifest,
    marketplace]`, even once the compile set spans both destinations."""

    def _dual_route(self, env):
        skill_rid = "lrn-64000001"
        newsk_rid = "lrn-64000002"
        build_fixture(env, new_skill_ids=[newsk_rid], skill_md_id=skill_rid)
        return skill_rid, newsk_rid

    def test_skill_md_leg_stages_only_its_target(self, env):
        skill_rid, newsk_rid = self._dual_route(env)
        bucket_dir = env.home / "skills" / NEW_SKILL_NAME
        spec = verbs._resolve_target(
            env.home, bucket_dir, f"skill:{NEW_SKILL_NAME}", "skill-md", None,
        )
        records = verbs._compile_set(env.home, spec)
        assert {r.id for r in records} == {skill_rid, newsk_rid}

        _, host_paths = verbs._apply_target(env.home, spec, None)
        assert host_paths == [spec.target]

    def test_new_skill_leg_stages_the_scaffold_triple(self, env):
        skill_rid, newsk_rid = self._dual_route(env)
        bucket_dir = env.home / "user"
        spec = verbs._resolve_target(
            env.home, bucket_dir, "user", "new-skill", NEW_SKILL_NAME,
        )
        records = verbs._compile_set(env.home, spec)
        assert {r.id for r in records} == {skill_rid, newsk_rid}

        _, host_paths = verbs._apply_target(env.home, spec, None)
        manifest = (
            env.host / "plugins" / NEW_SKILL_NAME / ".claude-plugin" / "plugin.json"
        )
        assert host_paths == [spec.target, manifest, env.marketplace]


class TestT16StructuralGuard:
    """T16 (§7.5, BLOCKER 1): an AST-based guard over the
    target-derivation path (`managed_target_for` + `_target_matched_records`
    + `_compile_set` — the last delegates its per-record comparison to the
    middle one, so all three must be scanned for the guard to cover the
    delegated call, not just the two callers) that
    forbids comparing a record's `scope` frontmatter against ANOTHER
    alphabet-bearing value (another `.scope`/`.name` attribute access, or
    an f-string built from one) — never against a bare string literal,
    which is what the three whitelisted, mandated-to-survive sites all
    do. A regex requiring a string-literal RHS is structurally BLIND to
    `record.scope == bucket.scope` / `record.scope == f"skill:{bucket.
    name}"` — alphabet-vs-alphabet, not alphabet-vs-literal, and exactly
    the forbidden class §3.4(1) names. This guard walks the AST instead
    of matching text, so it sees the RHS's SHAPE, not its spelling — no
    whitelist of literal strings is needed at all (closing NIT 3's
    'widened whitelist' concern by construction: there is no whitelist
    to widen)."""

    @staticmethod
    def _violations(source: str) -> list[str]:
        tree = ast.parse(source)
        found: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            if not any(
                isinstance(o, ast.Attribute) and o.attr == "scope" for o in operands
            ):
                continue  # must involve at least one `<x>.scope` to be in-domain
            non_literal = [
                o for o in operands
                if not (isinstance(o, ast.Constant) and isinstance(o.value, str))
            ]
            if len(non_literal) >= 2:
                found.append(ast.unparse(node))
        return found

    def test_no_alphabet_vs_alphabet_scope_comparison(self):
        found: list[str] = []
        for fn in (
            verbs.managed_target_for,
            verbs._target_matched_records,
            verbs._compile_set,
        ):
            found.extend(self._violations(inspect.getsource(fn)))
        assert not found, (
            f"alphabet-vs-alphabet scope comparison(s) on the "
            f"target-derivation path: {found}"
        )

    def test_guard_reddens_on_the_gate_probed_mutants(self):
        # §7.5's own mandate: verify the guard by REPRODUCING the defect.
        # Both are the round-1 gate's exact probes (BLOCKER 1).
        mutant_1 = "if record.scope == bucket.scope:\n    return None\n"
        mutant_2 = 'if record.scope == f"skill:{bucket.name}":\n    return None\n'
        assert self._violations(mutant_1), "guard is blind to record.scope == bucket.scope"
        assert self._violations(mutant_2), (
            "guard is blind to record.scope == f-string(bucket.name)"
        )

    def test_guard_stays_green_on_the_three_whitelisted_forms(self):
        # the exact three forms §3.4(1) whitelists: a bucket's kind (or a
        # record's scope) against a LITERAL — never one alphabet against
        # the other. (`verbs.py:1662`'s `b.scope == "skill"`,
        # `selfcheck.py:215`'s migrated `bucket.scope == "skill"`, and
        # the resolver's own `record.scope == "user"` / `"project"`
        # legs all reduce to this ONE shape.)
        whitelisted = [
            'if bucket.scope == "skill":\n    pass\n',
            'if b.scope == "skill":\n    pass\n',
            'if record.scope == "user":\n    pass\n',
            'if record.scope == "project":\n    pass\n',
        ]
        for src in whitelisted:
            assert not self._violations(src), f"false positive on whitelisted form: {src!r}"
