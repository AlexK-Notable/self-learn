"""U-glob — user-scope rules glob reachability + co-firing (spec:
docs/specs/self-learn/drafts/u-glob-reachability-spec.md). Covers §9's
T2-T13 (T0/T1 live as reversed/updated tests in test_a2_rules_local.py,
per the spec's own instruction that T1 IS T0's case-1 rewrite; T9's
`cofire_crowded` replacement (U-cap §6.1 retired the `over_cap`/
`cap_reason` OR-in this used to name) and T12's full-suite criterion are
likewise covered there / by the suite run itself).

DEVIATION NOTE (T8): §5.3 states TWICE, unambiguously, that membership
of `unpathed` is decided by `compilers.has_paths_key(text)` returning
False — a topic that DOES carry a (possibly malformed/empty) `paths:`
key belongs in `topics`, never `unpathed`. §11's mutation M-8 ("key
unpathed on read_paths_frontmatter instead of has_paths_key") is only a
REAL mutation — one that can make a test fail — if the baseline uses
has_paths_key; if the baseline used read_paths_frontmatter instead (as a
literal reading of T8's English "assert it lands in unpathed" would
require for a `paths: []` topic), M-8 would be a no-op and could never
fail T8. This test file therefore follows §5.3 + M-8 (the algorithmic,
twice-stated, mutation-load-bearing definition): the `paths: []` topic
asserted below lands in `topics` with an empty pattern set, not in
`unpathed`. Flagged here rather than silently resolved.
"""

from __future__ import annotations

import pytest

from self_learn import cli, selfcheck, verbs
from self_learn.ledger_ops import (
    create_record,
    glob_reaches,
    globs_may_intersect,
    write_proposal,
)
from self_learn.records import Record

from support import make_behavior, make_env, proposal_dict

OLD = "lrn-0000aaaa"


class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def seed_user_record(env, record_id=OLD, **kw):
    record = make_behavior(scope="user", record_id=record_id, **kw)
    create_record(env.home, record)
    return record


# =========================================================================
# T2 — positive control for T1 (§9.0): the SAME fixture shape as T1, but
# with a matching file present, routes successfully and records neither
# allow_empty_glob nor glob_bypass_reason.
# =========================================================================


class TestT2PositiveControlForT1:
    def test_matching_user_glob_routes_with_no_bypass_recorded(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        fixture_dir = tmp_path / "u-glob-t2-fixture"
        fixture_dir.mkdir()
        (fixture_dir / "x.ts").write_text("x", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["u-glob-t2-fixture/**/*.ts"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        rules_target = target.parent / "rules" / "ts-rules.md"
        assert rules_target.is_file()
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert "allow_empty_glob" not in routed.routing
        assert "glob_bypass_reason" not in routed.routing


# =========================================================================
# T3 — --allow-empty-glob at USER scope routes and records "zero-match",
# at both the verb level and the CLI level.
# =========================================================================


class TestT3AllowEmptyGlobUserScope:
    def test_verb_level_bypass_records_zero_match(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["u-glob-t3-nowhere/**/*.ts"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
            allow_empty_glob=True,
        )
        assert result.commit_sha
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert routed.routing["allow_empty_glob"] is True
        assert routed.routing["glob_bypass_reason"] == "zero-match"

    def test_cli_level_bypass_reaches_the_verb(self, tmp_path, env, monkeypatch):
        """No CLI flag overrides ``user_claude_md``/``chezmoi_bin`` (they
        are internal, programmatic-only overrides — same precedent as
        ``verbs.surface_fill``'s own docstring and
        ``test_resolution_evidence.py``'s CLI-level user-scope route
        test): monkeypatch ``verbs.DEFAULT_USER_CLAUDE_MD`` instead, the
        same binding ``cli.main`` reaches through unmodified."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", target)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["u-glob-t3-nowhere/**/*.ts"],
            ),
        )
        rc = cli.main(["route", OLD, "--allow-empty-glob"])
        assert rc == 0
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert routed.routing["allow_empty_glob"] is True
        assert routed.routing["glob_bypass_reason"] == "zero-match"


# =========================================================================
# T4 — budget exhaustion refuses (its own message), and its bypass reason
# differs from zero-match.
# =========================================================================


class TestT4BudgetExhaustion:
    def test_refuses_naming_the_budget_without_flag(self, tmp_path, env, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_GLOB_PROBE_BUDGET_S", "0")
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["u-glob-t4-budget/**/*.ts"],
            ),
        )
        with pytest.raises(verbs.VerbError) as exc:
            verbs.route(
                env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
            )
        msg = str(exc.value)
        assert "could not be checked within the 0s reachability budget" in msg
        assert "SELF_LEARN_GLOB_PROBE_BUDGET_S" in msg

    def test_flag_bypasses_and_records_budget_reason(self, tmp_path, env, monkeypatch):
        monkeypatch.setenv("SELF_LEARN_GLOB_PROBE_BUDGET_S", "0")
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["u-glob-t4-budget/**/*.ts"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
            allow_empty_glob=True,
        )
        assert result.commit_sha
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert routed.routing["allow_empty_glob"] is True
        assert routed.routing["glob_bypass_reason"] == "budget"


# =========================================================================
# T5 — a matching user glob is accepted, including the live idiom and a
# match placed EIGHT directories deep (M9 regression guard: no depth
# bound may reject it).
# =========================================================================


class TestT5MatchingUserGlobAccepted:
    def test_live_idiom_matches(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        proj = tmp_path / ".claude" / "projects" / "slug"
        proj.mkdir(parents=True)
        (proj / "x.jsonl").write_text("{}", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="transcripts",
                rules_paths=["**/.claude/projects/**/*.jsonl"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha

    def test_eight_directories_deep_still_matches_no_depth_bound(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        deep = tmp_path
        for seg in ("d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"):
            deep = deep / seg
        deep.mkdir(parents=True)
        (deep / "u-glob-t5-deep-marker").mkdir()
        (deep / "u-glob-t5-deep-marker" / "f.md").write_text("f", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="deep-topic",
                rules_paths=["**/u-glob-t5-deep-marker/*.md"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha


# =========================================================================
# gate NIT-3: `_user_reachability_roots`'s outside-$HOME host branch.
# §4.1/§6.3: every T1/T2/T5 fixture above nests the sandbox host-repo
# UNDER the derived $HOME root (both sit under the same `tmp_path`, and
# `user_claude_md_target.parent.parent` is `tmp_path` itself), so that
# branch — a registered host that is genuinely OUTSIDE $HOME getting
# appended to `remainder` — has never fired in the green suite. Here the
# user's `$HOME` is pinned one level deeper (`tmp_path/home-root`), a
# sibling of the sandbox host-repo (`tmp_path/host-repo`) rather than its
# ancestor, so the host is outside $HOME and must be added.
# =========================================================================


class TestUserReachabilityRootsOutsideHomeHost:
    def test_host_outside_home_is_added_to_roots(self, tmp_path, env):
        home_root = tmp_path / "home-root"
        target = home_root / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir(parents=True)
        target.write_text("# user conduct\n", encoding="utf-8")
        roots = verbs._user_reachability_roots(env.home, target)
        assert roots[0] == home_root
        assert env.host.resolve() in roots
        # negative control: the sandbox host does sit UNDER $HOME in every
        # other fixture in this file (all use `tmp_path` itself as the
        # user_claude_md's grandparent) — confirm that shape does NOT
        # add the host, so this test's differently-shaped fixture is what
        # is actually exercising the branch.
        nested_target = tmp_path / "dot-claude" / "CLAUDE.md"
        nested_roots = verbs._user_reachability_roots(env.home, nested_target)
        assert nested_roots == (tmp_path,)

    def test_route_succeeds_via_outside_home_host_root(self, tmp_path, env):
        home_root = tmp_path / "home-root"
        target = home_root / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir(parents=True)
        target.write_text("# user conduct\n", encoding="utf-8")
        # the marker lives ONLY inside the sandbox host-repo, which is
        # outside `home_root` by construction — a route that succeeds
        # here can only be reaching it via the outside-$HOME host branch.
        marker = env.host / "u-glob-nit3-marker"
        marker.mkdir()
        (marker / "f.md").write_text("f", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="outside-home",
                rules_paths=["**/u-glob-nit3-marker/*.md"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha


# =========================================================================
# T6 — glob_reaches unit behaviour, one case per §4.3 branch.
# =========================================================================


class TestT6GlobReachesUnitBehaviour:
    def test_floating_matches_at_zero_directory_expansion(self, tmp_path):
        (tmp_path / "x").mkdir()
        (tmp_path / "x" / "f.md").write_text("f", encoding="utf-8")
        assert glob_reaches((tmp_path,), "**/x/*.md") == "match"

    def test_floating_matches_only_via_dfs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "x"
        nested.mkdir(parents=True)
        (nested / "f.md").write_text("f", encoding="utf-8")
        assert glob_reaches((tmp_path,), "**/x/*.md") == "match"

    def test_non_floating_pattern(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "f.md").write_text("f", encoding="utf-8")
        assert glob_reaches((tmp_path,), "docs/*.md") == "match"
        assert glob_reaches((tmp_path,), "nope/*.md") == "none"

    def test_empty_literal_pattern(self, tmp_path):
        (tmp_path / "f.ext").write_text("f", encoding="utf-8")
        assert glob_reaches((tmp_path,), "**/*.ext") == "match"

    def test_match_inside_hidden_directory(self, tmp_path):
        """§2.2's include_hidden fix. NOTE (gate BLOCKER-1): this alone
        does NOT exercise `include_hidden` at `_first_hit`'s own
        `glob.iglob` call — `.hidden` is a LITERAL segment, consumed by
        the DFS's own `os.scandir` (which sees dotfiles regardless of
        any glob flag), and the matched file `f.md` is not itself
        hidden, so the delegated iglob never needed the flag. Dropping
        `include_hidden=True` (M-4) leaves this case green. See the two
        cases below, where the hidden component sits INSIDE `rem` (the
        part `_first_hit`'s own iglob call decides), for the real
        positive control."""
        hidden = tmp_path / "a" / ".hidden"
        hidden.mkdir(parents=True)
        (hidden / "f.md").write_text("f", encoding="utf-8")
        assert glob_reaches((tmp_path,), "**/.hidden/*.md") == "match"

    def test_hidden_file_matched_by_the_delegated_iglob(self, tmp_path):
        """Gate BLOCKER-1's real positive control: `y` is a literal
        segment (consumed by the DFS), but the MATCHED FILE itself is
        hidden (`.hiddenfile.md`) and is found only by `_first_hit`'s
        own `glob.iglob(rem, ..., include_hidden=True)` call against
        `rem="*.md"`. Dropping `include_hidden=True` turns this into
        `"none"` (verified: `glob.iglob("*.md", include_hidden=False)`
        on this exact fixture returns no hit) — a REAL red for M-4."""
        (tmp_path / "y").mkdir()
        (tmp_path / "y" / ".hiddenfile.md").write_text("f", encoding="utf-8")
        assert glob_reaches((tmp_path,), "**/y/*.md") == "match"

    def test_hidden_subpath_matched_by_a_double_star_in_rem(self, tmp_path):
        """Second positive control for M-4 (belt and braces): the
        hidden component is a DIRECTORY, but one that `rem`'s own `**`
        must traverse (`marker` is the literal segment consumed by the
        DFS; `.d/f.md` is found only via the delegated
        `glob.iglob("**/*.md", ...)` inside `_first_hit`)."""
        (tmp_path / "marker" / ".d").mkdir(parents=True)
        (tmp_path / "marker" / ".d" / "f.md").write_text("f", encoding="utf-8")
        assert glob_reaches((tmp_path,), "**/marker/**/*.md") == "match"

    def test_symlinked_directory_not_followed_by_dfs(self, tmp_path):
        (tmp_path / "somedir").mkdir()
        real = tmp_path / "realtarget"
        real.mkdir()
        (real / "f.md").write_text("f", encoding="utf-8")
        import os
        os.symlink(real, tmp_path / "somedir" / "target", target_is_directory=True)
        # only reachable through the symlink -> refused
        assert glob_reaches((tmp_path,), "**/target/*.md") == "none"
        # positive control: a REAL "target" dir reached via the DFS matches
        (tmp_path / "somedir2" / "target").mkdir(parents=True)
        (tmp_path / "somedir2" / "target" / "g.md").write_text("g", encoding="utf-8")
        assert glob_reaches((tmp_path,), "**/target/*.md") == "match"

    def test_multiple_roots_only_second_matches(self, tmp_path):
        r1 = tmp_path / "r1"
        r2 = tmp_path / "r2"
        r1.mkdir()
        (r2 / "onlyhere").mkdir(parents=True)
        (r2 / "onlyhere" / "f.md").write_text("f", encoding="utf-8")
        assert glob_reaches((r1, r2), "**/onlyhere/*.md") == "match"

    def test_budget_exhaustion_returns_budget_not_none(self, tmp_path):
        assert glob_reaches((tmp_path,), "**/anything/*.md", budget_s=0) == "budget"


# =========================================================================
# T7 — globs_may_intersect on fixtures: M7's 16 pairs + 3 class/? rows +
# 1 malformed-pattern case, asserted in BOTH argument orders.
# =========================================================================


T7_PAIRS = [
    ("**/.claude/hooks/*.sh", "**/.claude/projects/**/*.jsonl", False),
    ("**/*.py", "**/test_*", True),
    ("src/**/*.py", "**/*.py", True),
    ("docs/*.md", "src/*.md", False),
    ("**/*.md", "**/*.py", False),
    ("a/b/c.txt", "a/*/c.txt", True),
    ("**/x/**", "**/y/**", True),
    ("*.sh", "*.jsonl", False),
    ("**/*.jsonl", "**/.claude/projects/**/*.jsonl", True),
    ("**/*.sh", "**/.claude/hooks/*.sh", True),
    ("plugins/**/*.py", "docs/**/*.py", False),
    ("**/[abc]*.md", "**/b*.md", True),
    ("**/*.md", "**/*.md", True),
    ("a/**", "a/b/c", True),
    ("**/CLAUDE.md", "**/*.md", True),
    ("**/CLAUDE.md", "**/*.py", False),
    ("**/?.md", "**/a.md", True),
    ("**/[!a]b.md", "**/ab.md", True),
    ("**/[]x]y.md", "**/]y.md", True),
]


class TestT7GlobsMayIntersect:
    @pytest.mark.parametrize("a,b,expected", T7_PAIRS)
    def test_pair_both_orders(self, a, b, expected):
        assert globs_may_intersect(a, b) is expected
        assert globs_may_intersect(b, a) is expected

    def test_malformed_unclosed_class_no_exception(self):
        """An unbalanced `[` degrades to a LITERAL `[`, matching
        `_translate_glob_segment`'s own rule — never raises, and compares
        as the literal character it degrades to (never as "matches
        anything", gate NIT-1). The self-pair proves no exception; the
        second pair is the gate's own measured DISCRIMINATING case —
        `"**/other.md"` does NOT discriminate (its False falls out of a
        LATER 'u' != 't' mismatch either way, bug or no bug); this pair's
        overall answer flips on the '[' comparison alone: after the
        first-token mismatch ('[' literal vs 'x'), the two remaining
        suffixes ("unclosed*.md" vs "unclosedq.md") DO share a common
        string (`*` absorbs "q", both end ".md") — so a build that
        treats '[' as matching-anything (advancing past it) reaches that
        shared suffix and wrongly returns True."""
        result = globs_may_intersect("**/[unclosed*.md", "**/[unclosed*.md")
        assert result is True
        result2 = globs_may_intersect("**/[unclosed*.md", "**/xunclosedq.md")
        assert result2 is False


# =========================================================================
# T8 — the co-firing set computed on a fixture rules directory.
# =========================================================================


class TestT8CofireOnFixtureRulesDir:
    def _write_topics(self, rules_dir):
        rules_dir.mkdir()
        (rules_dir / "alpha.md").write_text(
            "---\npaths:\n  - '**/*.py'\n---\n", encoding="utf-8"
        )
        (rules_dir / "beta.md").write_text(
            "---\npaths:\n  - '**/test_*'\n---\n", encoding="utf-8"
        )
        (rules_dir / "gamma.md").write_text(
            "---\npaths:\n  - '**/*.md'\n---\n", encoding="utf-8"
        )
        (rules_dir / "delta.md").write_text(
            "---\npaths:\n  - '**/*.jsonl'\n---\n", encoding="utf-8"
        )
        (rules_dir / "epsilon.md").write_text(
            "no paths key at all\n", encoding="utf-8"
        )

    def test_five_topic_fixture(self, tmp_path, env):
        """DEVIATION NOTE (see module docstring): the spec's own §9 T8
        prose asserts `pairs == [["alpha","beta"],["beta","gamma"]]` and
        `max_fanin == 4`, claiming delta (`**/*.jsonl`) "intersects
        nothing". That claim is FALSE under §5.2's own algorithm — e.g.
        the string "test_.jsonl" satisfies BOTH `**/test_*` (beta) and
        `**/*.jsonl` (delta), so `globs_may_intersect` correctly returns
        True for that pair (verified independently: neither pattern is
        one of T7's 16+3 rows, so the spec's own gate-verified table
        never actually re-checked this specific claim). Implementing
        §5.2 FAITHFULLY (mandatory — T7 pins the algorithm exactly, and
        M7 measures "16/16 correct") makes the spec's literal T8 dict
        arithmetically wrong, the same class of error the r1->r2 fold
        already caught once in this exact paragraph (max_fanin 3 vs 4).
        This test asserts the value §5.2's algorithm actually produces."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        self._write_topics(rules_dir)
        result = verbs.surface_fill(env.home, env.home / "user", "user", user_claude_md=target)
        cofire = result["claude-md"]["rules_cofire"]
        assert cofire == {
            "topics": ["alpha", "beta", "delta", "gamma"],
            "unpathed": ["epsilon"],
            "pairs": [["alpha", "beta"], ["beta", "delta"], ["beta", "gamma"]],
            "max_fanin": 5,
        }

    def test_empty_list_paths_topic(self, tmp_path, env):
        """§5.3's has_paths_key vs read_paths_frontmatter distinction —
        see the module docstring's DEVIATION NOTE. A topic carrying a
        `paths: []` key HAS a paths key (has_paths_key is True), so it
        lands in `topics` with an empty pattern set, never `unpathed`."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        self._write_topics(rules_dir)
        (rules_dir / "zeta.md").write_text("---\npaths: []\n---\n", encoding="utf-8")
        result = verbs.surface_fill(env.home, env.home / "user", "user", user_claude_md=target)
        cofire = result["claude-md"]["rules_cofire"]
        assert "zeta" in cofire["topics"]
        assert "zeta" not in cofire["unpathed"]
        assert cofire["unpathed"] == ["epsilon"]
        # zeta's empty pattern set contributes to no pair and does not
        # change the argmax already set by beta (5 — see the
        # DEVIATION NOTE on test_five_topic_fixture above).
        assert cofire["max_fanin"] == 5


# =========================================================================
# T10 — selfcheck reports a user-scope glob that has gone dead; the
# companion cases pin the §6.6 exemption matrix.
# =========================================================================


class TestT10SelfcheckUserScopeGlobDrift:
    def _route_pathed(self, tmp_path, env, monkeypatch, *, pattern, fixture=True,
                       allow_empty_glob=False, budget_s=None):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        # U-xscope: selfcheck._target_for now delegates to
        # verbs.managed_target_for, which reads verbs' OWN
        # DEFAULT_USER_CLAUDE_MD binding, not selfcheck's re-exported
        # copy — patch both, or _check_drift's target resolution (used
        # for presence/staleness) silently falls back to the real
        # ~/.claude/CLAUDE.md while routing still goes through `target`.
        monkeypatch.setattr(selfcheck, "DEFAULT_USER_CLAUDE_MD", target)
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", target)
        if fixture:
            fixture_dir = tmp_path / "u-glob-t10-fixture"
            fixture_dir.mkdir()
            (fixture_dir / "x.md").write_text("x", encoding="utf-8")
        if budget_s is not None:
            monkeypatch.setenv("SELF_LEARN_GLOB_PROBE_BUDGET_S", str(budget_s))
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=[pattern],
            ),
        )
        verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
            allow_empty_glob=allow_empty_glob,
        )
        return target

    def test_zero_match_bypass_is_not_reported(self, tmp_path, env, monkeypatch):
        self._route_pathed(
            tmp_path, env, monkeypatch,
            pattern="u-glob-t10-fixture/*.nomatch", fixture=False,
            allow_empty_glob=True,
        )
        ok, _reason = selfcheck._check_drift(env.home)
        assert ok is True

    def test_legacy_record_with_no_reason_key_is_not_reported(self, tmp_path, env, monkeypatch):
        target = self._route_pathed(
            tmp_path, env, monkeypatch,
            pattern="u-glob-t10-fixture/*.md",
        )
        # simulate a LEGACY record: allow_empty_glob=True, no reason key
        # at all (written before this unit existed).
        routed_path = env.home / "user" / "resolved" / f"{OLD}.md"
        routed = Record.from_path(routed_path)
        routing = dict(routed.routing)
        routing["allow_empty_glob"] = True
        routing.pop("glob_bypass_reason", None)
        routed.set_routing(routing)
        routed.write(routed_path)
        # the glob is now dead
        (tmp_path / "u-glob-t10-fixture" / "x.md").unlink()
        ok, _reason = selfcheck._check_drift(env.home)
        assert ok is True

    def test_budget_bypass_is_reported_when_probe_now_returns_none(
        self, tmp_path, env, monkeypatch
    ):
        """M-2's finding: a transient timeout must not buy a permanent
        exemption — a "budget" bypass is RE-PROBED on every audit."""
        self._route_pathed(
            tmp_path, env, monkeypatch,
            pattern="u-glob-t10-fixture/*.md", fixture=False,
            allow_empty_glob=True, budget_s=0,
        )
        # the SELF_LEARN_GLOB_PROBE_BUDGET_S=0 monkeypatch stays applied
        # from setenv above unless we restore it — restore a real budget
        # for the audit probe itself, so it decides "none" (not another
        # "budget"), which is what T10's assertion needs.
        monkeypatch.setenv("SELF_LEARN_GLOB_PROBE_BUDGET_S", "30")
        ok, reason = selfcheck._check_drift(env.home)
        assert ok is False
        assert "u-glob-t10-fixture/*.md" in reason

    def test_live_budget_verdict_during_audit_not_reported(self, tmp_path, env, monkeypatch):
        """The §6.6 gate/audit asymmetry: the GATE refuses on "could not
        tell"; the AUDIT does not — only a positive "none" is drift."""
        self._route_pathed(
            tmp_path, env, monkeypatch,
            pattern="u-glob-t10-fixture/*.md",
        )
        # now force the AUDIT's own probe to hit budget (not zero-match)
        monkeypatch.setenv("SELF_LEARN_GLOB_PROBE_BUDGET_S", "0")
        ok, _reason = selfcheck._check_drift(env.home)
        assert ok is True


# =========================================================================
# T11 — the read-only path never probes.
# =========================================================================


class TestT11ReadOnlyNeverProbes:
    def test_surface_fill_and_check_dirty_false_never_call_glob_reaches(
        self, tmp_path, env, monkeypatch
    ):
        def _boom(*_a, **_kw):
            raise AssertionError("glob_reaches must not be called read-only")

        monkeypatch.setattr(verbs, "glob_reaches", _boom)
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        rules_dir.mkdir()
        (rules_dir / "topic.md").write_text(
            "---\npaths:\n  - 'never/matches/**'\n---\n", encoding="utf-8"
        )
        # surface_fill must not raise
        verbs.surface_fill(env.home, env.home / "user", "user", user_claude_md=target)
        # a read-only resolve must not raise either
        verbs._resolve_target(
            env.home, env.home / "user", "user", "claude-md", None,
            user_claude_md=target, check_dirty=False,
            variant="rules", rules_topic="topic", rules_paths=["never/matches/**"],
        )


# =========================================================================
# T13 — mixed failures refuse and name both lists; the more actionable
# reason ("zero-match") wins when both kinds are present.
# =========================================================================


def _fake_dead_or_budget(roots, pattern, *, budget_s=None):
    """T13's mix, deterministic: one pattern comes back a positive
    "none" (dead), the other a "budget" (undecided) — isolating
    ``_validate_rules_globs``'s composition/precedence logic (§7.5) from
    ``glob_reaches``'s real filesystem timing, which is T6's job."""
    return "none" if pattern == "u-glob-t13-dead/**" else "budget"


class TestT13MixedFailures:
    def test_mixed_dead_and_budget_refuses_naming_both(self, tmp_path, env, monkeypatch):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "glob_reaches", _fake_dead_or_budget)
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["u-glob-t13-dead/**", "u-glob-t13-slow/**"],
            ),
        )
        with pytest.raises(verbs.VerbError) as exc:
            verbs.route(
                env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
            )
        msg = str(exc.value)
        assert "match nothing under" in msg
        assert "could not be checked within" in msg
        assert "u-glob-t13-dead/**" in msg
        assert "u-glob-t13-slow/**" in msg

    def test_mixed_with_flag_records_zero_match_the_stricter_exemption(
        self, tmp_path, env, monkeypatch
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "glob_reaches", _fake_dead_or_budget)
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope="user",
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["u-glob-t13-dead/**", "u-glob-t13-slow/**"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
            allow_empty_glob=True,
        )
        assert result.commit_sha
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert routed.routing["glob_bypass_reason"] == "zero-match"
