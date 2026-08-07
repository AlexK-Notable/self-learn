"""A2 — `claude-md` rules, local, and glob validation (spec:
docs/specs/self-learn/drafts/a2-rules-local-spec.md). Test obligations
§13 items 1-19 (a few of the label/UI-side ones live in the UI suite —
see plugins/self-learn/ui/tests/test_proposals.py and
test_models_detail.py for obligations 5/6/19).

Sandboxes: :func:`support.make_env` pairs an independent LEDGER home
with a HOST repo registered as BOTH skills-root and project host.
Chezmoi is a PATH-shimmed fake (never real ``~/.claude`` or real chezmoi
source) — the same pattern ``chezmoi.py``'s own module docstring and
``test_verbs.py``/``test_chezmoi.py`` already use.
"""

from __future__ import annotations

import json
import os
import stat

import pytest
from ruamel.yaml import YAML

from self_learn import chezmoi, cli, selfcheck, verbs
from self_learn.compilers import BEGIN_MARKER
from self_learn.hosts import slug_for
from self_learn.ledger_ops import (
    ProposalError,
    create_record,
    write_proposal,
)
from self_learn.records import Record

from support import commit_all, git, make_behavior, make_env, proposal_dict, verb_files

OLD = "lrn-0000aaaa"

#: The PATH-shimmed fake chezmoi (extends test_verbs.py's shape with a
#: top-level ``add`` case for ``chezmoi add <target>`` — the one
#: genuinely new primitive §10.3 adds — and per-subcommand RC controls
#: for ``git -- commit`` / ``git -- push`` so the H-2 degradation path
#: (obligation 12) is reachable without also breaking the capability
#: probe, exactly like ``CHEZMOI_SHIM_SOURCE_RC``'s existing isolation).
CHEZMOI_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CHEZMOI_SHIM_LOG"
case "$1" in
  source-path)
    printf '%s' "${2:-}"
    exit "${CHEZMOI_SHIM_SOURCE_RC-0}"
    ;;
  diff) printf '%s' "${CHEZMOI_SHIM_DIFF-}" ;;
  add)
    if [ -n "${CHEZMOI_SHIM_ADD_RC-}" ]; then exit "$CHEZMOI_SHIM_ADD_RC"; fi
    ;;
  re-add)
    if [ -n "${CHEZMOI_SHIM_READD_RC-}" ]; then exit "$CHEZMOI_SHIM_READD_RC"; fi
    ;;
  git)
    case "$3" in
      status) printf '%s' "${CHEZMOI_SHIM_STATUS-}" ;;
      commit)
        if [ -n "${CHEZMOI_SHIM_COMMIT_RC-}" ]; then exit "$CHEZMOI_SHIM_COMMIT_RC"; fi
        ;;
      push)
        if [ -n "${CHEZMOI_SHIM_PUSH_RC-}" ]; then exit "$CHEZMOI_SHIM_PUSH_RC"; fi
        ;;
      rev-parse) printf 'deadbeefcafe' ;;
    esac
    ;;
esac
exit "${CHEZMOI_SHIM_EXIT-0}"
"""


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    cache = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir
        self.skill_md = sandbox.skill_md


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def chezmoi_shim(tmp_path, monkeypatch):
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    fake = bindir / "chezmoi"
    fake.write_text(CHEZMOI_SHIM, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "chezmoi-argv.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CHEZMOI_SHIM_LOG", str(log))
    monkeypatch.delenv("CHEZMOI_SHIM_SOURCE_RC", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_ADD_RC", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_COMMIT_RC", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_PUSH_RC", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_READD_RC", raising=False)

    def calls():
        return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]

    return calls


def seed_user_record(env, record_id=OLD, **kw):
    record = make_behavior(scope="user", record_id=record_id, **kw)
    create_record(env.home, record)
    return record


def seed_project_record(env, record_id=OLD, **kw):
    record = make_behavior(scope="project", record_id=record_id, **kw)
    create_record(env.home, record, project_path=env.host)
    return record


def project_bucket_dir(env):
    return env.home / "projects" / slug_for(env.host)


def seed_skill_record(env, record_id=OLD, **kw):
    record = make_behavior(scope="skill:s", record_id=record_id, **kw)
    create_record(env.home, record)
    return record


def read_frontmatter(text):
    """U-pathed A1/A2: re-parse a rules file's leading `---` block with
    `ruamel.yaml.YAML(typ="safe")` — hand-split, never through
    `self_learn.compilers`'s own reader, so this is a genuinely separate
    parse of the emitted bytes (the whole point of A1/A16: bytes on disk,
    checked by a loader that isn't the one that wrote them)."""
    lines = text.split("\n")
    assert lines[0] == "---", f"no leading '---' fence in: {text!r}"
    close = lines[1:].index("---") + 1
    inner = "\n".join(lines[1:close])
    return YAML(typ="safe").load(inner)


# =====================================================================
# Obligation 1 — variant absent routes byte-identically (P-A6),
# across ABSENT / UNMANAGED / MANAGED.
# =====================================================================


class TestObligation1VariantAbsentByteIdentical:
    def test_absent_carries_no_variant_key(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        verbs.route(
            env.home, OLD, dest="claude-md", user_claude_md=target,
            chezmoi_bin="chezmoi-definitely-absent",
        )
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert "variant" not in routed.routing

    def test_unmanaged_carries_no_variant_key(self, tmp_path, env, chezmoi_shim, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        verbs.route(env.home, OLD, dest="claude-md", user_claude_md=target)
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert "variant" not in routed.routing

    def test_managed_carries_no_variant_key(self, tmp_path, env, chezmoi_shim):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        verbs.route(env.home, OLD, dest="claude-md", user_claude_md=target)
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert "variant" not in routed.routing


# =====================================================================
# Obligations 2/3 — project-scope glob zero-match refusal (per pattern,
# partial-failure case) and the --allow-empty-glob escape.
# =====================================================================


class TestObligation2And3ProjectGlobValidation:
    def test_dead_pattern_refuses_naming_it(self, env):
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["src/**/*.ts"],
            ),
        )
        with pytest.raises(verbs.VerbError, match="src/\\*\\*/\\*\\.ts"):
            verbs.route(env.home, OLD)
        # nothing committed — the record stays pending
        assert (project_bucket_dir(env) / "pending" / f"{OLD}.md").is_file()

    def test_partial_failure_one_of_three_dead(self, env):
        (env.host / "src").mkdir()
        (env.host / "src" / "a.ts").write_text("x", encoding="utf-8")
        (env.host / "lib").mkdir()
        (env.host / "lib" / "b.ts").write_text("x", encoding="utf-8")
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["src/*.ts", "lib/*.ts", "dead/*.ts"],
            ),
        )
        with pytest.raises(verbs.VerbError) as exc:
            verbs.route(env.home, OLD)
        msg = str(exc.value)
        assert "dead/*.ts" in msg
        assert "src/*.ts" not in msg
        assert "lib/*.ts" not in msg

    def test_allow_empty_glob_bypasses_and_records(self, env):
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["src/**/*.ts"],
            ),
        )
        result = verbs.route(env.home, OLD, allow_empty_glob=True)
        assert result.commit_sha
        routed = Record.from_path(
            project_bucket_dir(env) / "resolved" / f"{OLD}.md"
        )
        assert routed.routing["allow_empty_glob"] is True
        assert routed.routing["rules_topic"] == "ts-rules"

    def test_cli_dash_dash_allow_empty_glob_reaches_the_verb(self, env, monkeypatch, capsys):
        """argparse-level wiring: ``self-learn route <id> --allow-empty-
        glob`` must actually thread the flag through to
        :func:`verbs.route` — a smoke test for the subparser/dispatch
        code, not just the verb function ``test_allow_empty_glob_bypasses_
        and_records`` above already covers directly."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["src/**/*.ts"],
            ),
        )
        # without the flag, the CLI-level call must still refuse (usage
        # error, not a crash) — proves the flag is load-bearing, not a
        # no-op default that always bypasses.
        rc = cli.main(["route", OLD])
        assert rc != 0
        assert (project_bucket_dir(env) / "pending" / f"{OLD}.md").is_file()

        rc = cli.main(["route", OLD, "--allow-empty-glob"])
        assert rc == 0
        routed = Record.from_path(
            project_bucket_dir(env) / "resolved" / f"{OLD}.md"
        )
        assert routed.routing["allow_empty_glob"] is True

    def test_user_scope_glob_is_parse_only_never_zero_match(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["this/matches/nothing/**/*.ts"],
            ),
        )
        # No canonical tree for a user-scope glob (U-A2-glob-tree) — this
        # must NOT raise, unlike the project-scope case above.
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        target_rules = target.parent / "rules" / "ts-rules.md"
        assert target_rules.is_file()
        assert OLD in target_rules.read_text(encoding="utf-8")


# =====================================================================
# Obligation 4 — `local` / CLAUDE.local.md + the gitignore privacy
# refusal + the positive user/skill-scope guard.
# =====================================================================


class TestObligation4LocalPrivacyAndScopeGuard:
    def test_refuses_when_not_gitignored(self, env):
        seed_project_record(env)
        with pytest.raises(verbs.VerbError, match="gitignore"):
            verbs.route(env.home, OLD, dest="claude-md:local")

    def test_succeeds_when_gitignored(self, env):
        (env.host / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")
        seed_project_record(env)
        result = verbs.route(env.home, OLD, dest="claude-md:local")
        assert result.commit_sha
        target = env.host / "CLAUDE.local.md"
        assert target.is_file()
        assert OLD in target.read_text(encoding="utf-8")
        routed = Record.from_path(
            project_bucket_dir(env) / "resolved" / f"{OLD}.md"
        )
        assert routed.routing["variant"] == "local"
        assert "rules_topic" not in routed.routing

    def test_user_scope_local_refuses_via_positive_guard(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        with pytest.raises(verbs.VerbError, match="exists only per project"):
            verbs.route(
                env.home, OLD, dest="claude-md:local", user_claude_md=target,
                chezmoi_bin="chezmoi-definitely-absent",
            )
        # never silently fell through to plain CLAUDE.md
        assert not target.is_file() or "CLAUDE.local" not in target.read_text(
            encoding="utf-8"
        )

    def test_skill_scope_local_refuses_via_positive_guard(self, env):
        seed_skill_record(env)
        with pytest.raises(verbs.VerbError, match="exists only per project"):
            verbs.route(env.home, OLD, dest="claude-md:local")


# =====================================================================
# Obligation 8 — the >5-topics-per-scope churn signal on surface_fill.
# =====================================================================


class TestObligation8RulesTopicCount:
    def test_over_five_topics_sets_over_cap(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        rules_dir.mkdir()
        for i in range(6):
            (rules_dir / f"topic{i}.md").write_text("x", encoding="utf-8")
        result = verbs.surface_fill(env.home, env.home / "user", "user", user_claude_md=target)
        assert result["claude-md"]["rules_topic_count"] == 6
        assert result["claude-md"]["over_cap"] is True
        assert result["claude-md"]["cap_reason"] == "rules-topics"

    def test_five_or_fewer_leaves_per_file_over_cap_untouched(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        rules_dir.mkdir()
        for i in range(5):
            (rules_dir / f"topic{i}.md").write_text("x", encoding="utf-8")
        result = verbs.surface_fill(env.home, env.home / "user", "user", user_claude_md=target)
        assert result["claude-md"]["rules_topic_count"] == 5
        assert result["claude-md"]["over_cap"] is False


# =====================================================================
# Obligation 9 — skill-scope `rules` raises the P-A13 deferral via a
# POSITIVE guard, never the silent claude-md-branch fallthrough.
# =====================================================================


class TestObligation9SkillScopeDeferral:
    def test_skill_scope_rules_raises_deferral_not_fallthrough(self, env):
        seed_skill_record(env)
        with pytest.raises(verbs.VerbError, match="P-A13"):
            verbs.route(env.home, OLD, dest="claude-md:rules:subagents")
        # never silently landed at <skills root>/CLAUDE.md — env.host IS
        # the registered skills root (make_env registers it as both).
        text = (env.host / "CLAUDE.md").read_text(encoding="utf-8")
        assert "subagents" not in text
        assert OLD not in text
        assert BEGIN_MARKER not in text


# =====================================================================
# Obligation 10 — selfcheck re-asserts a PROJECT-scope pathed rule's
# globs (drift); a user-scope rule's presence is checked but its globs
# are never re-asserted.
# =====================================================================


class TestObligation10SelfcheckGlobDrift:
    def test_project_scope_stale_glob_fails_drift(self, env):
        src = env.host / "src"
        src.mkdir()
        (src / "foo.ts").write_text("x", encoding="utf-8")
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["src/foo.ts"],
            ),
        )
        verbs.route(env.home, OLD)
        (src / "foo.ts").unlink()  # the file moved — the glob is now stale

        ok, reason = selfcheck._check_drift(env.home)
        assert ok is False
        assert "src/foo.ts" in reason
        assert "stale" in reason

    def test_user_scope_glob_not_reasserted_but_presence_still_checked(
        self, tmp_path, env, monkeypatch
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        # selfcheck's own _target_for hardcodes DEFAULT_USER_CLAUDE_MD for
        # user scope (pre-A2 behavior, unchanged) — monkeypatch the SAME
        # binding _resolve_target uses via user_claude_md, so this test's
        # route and its drift check agree on one target, never the real
        # ~/.claude/CLAUDE.md.
        monkeypatch.setattr(selfcheck, "DEFAULT_USER_CLAUDE_MD", target)
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["never/matches/anything/**"],
            ),
        )
        verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        # drift is clean despite the eternally-dead glob — never re-asserted
        ok, reason = selfcheck._check_drift(env.home)
        assert ok is True

        # presence-in-file IS still checked: strip the entry and re-check.
        rules_target = target.parent / "rules" / "ts-rules.md"
        rules_target.write_text("no marker here\n", encoding="utf-8")
        ok2, reason2 = selfcheck._check_drift(env.home)
        assert ok2 is False
        assert OLD in reason2


# =====================================================================
# Obligation 11 — the chezmoi-adopt offer fires EXACTLY on
# UNMANAGED + variant==rules + user scope.
# =====================================================================


class TestObligation11OfferFiringMatrix:
    def test_unmanaged_rules_offer_adopt_true_gets_hint(self, tmp_path, env, chezmoi_shim, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        result = chezmoi.compile_user_scope(
            target, [], offer_adopt=True,
        )
        assert result.adopt_hint is not None
        assert str(target) in result.adopt_hint
        assert "chezmoi-adopt" in result.adopt_hint

    def test_absent_never_offers_even_with_offer_adopt_true(self, tmp_path, env):
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        result = chezmoi.compile_user_scope(
            target, [], offer_adopt=True, chezmoi="chezmoi-definitely-absent",
        )
        assert result.adopt_hint is None

    def test_managed_never_offers_even_with_offer_adopt_true(self, tmp_path, env, chezmoi_shim):
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        result = chezmoi.compile_user_scope(target, [], offer_adopt=True)
        assert result.adopt_hint is None

    def test_unmanaged_plain_claude_md_never_offers(self, tmp_path, env, chezmoi_shim, monkeypatch):
        """§10.1: plain CLAUDE.md's unmanaged state is the user's prior
        choice — the route verb never threads offer_adopt=True for it
        (verbs._apply_target gates on spec.variant == "rules"); this
        proves the primitive itself also respects offer_adopt=False."""
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        result = chezmoi.compile_user_scope(target, [], offer_adopt=False)
        assert result.adopt_hint is None

    def test_route_only_threads_offer_adopt_for_rules_variant(
        self, tmp_path, env, chezmoi_shim, monkeypatch
    ):
        """End to end through the verb: a plain-claude-md user route
        NEVER carries an adopt hint even when UNMANAGED, but a rules
        route to a fresh UNMANAGED file does."""
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env, record_id="lrn-00000001")
        result = verbs.route(
            env.home, "lrn-00000001", dest="claude-md", user_claude_md=target,
        )
        assert not any("chezmoi-adopt" in w for w in result.warnings)

        seed_user_record(env, record_id="lrn-00000002")
        result2 = verbs.route(
            env.home, "lrn-00000002", dest="claude-md:rules:subagents",
            user_claude_md=target,
        )
        assert any("chezmoi-adopt" in w for w in result2.warnings)


# =====================================================================
# Obligation 12 — adopt_user_scope: porcelain-guard -> chezmoi add ->
# commit(+push); H-2 degradation; self-extinguishing.
# =====================================================================


class TestObligation12AdoptAcceptPath:
    def test_accept_path_argv_order_and_self_extinguishing(
        self, tmp_path, env, chezmoi_shim
    ):
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")

        result = chezmoi.adopt_user_scope(target, message="self-learn: adopt")
        assert result.tracked is True
        assert result.synced is True
        assert result.warning is None

        calls = chezmoi_shim()
        assert calls[0] == "git -- status --porcelain"
        assert f"add {target}" in calls
        assert calls.index(f"add {target}") < calls.index("git -- add -A")
        assert "git -- commit -m self-learn: adopt" in calls
        assert "git -- push" in calls

    def test_never_uses_target_diff_before_add(self, tmp_path, env, chezmoi_shim):
        """The porcelain-ONLY guard (never _drift_dirty_guard's target
        diff, which errors on an unmanaged target)."""
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        chezmoi.adopt_user_scope(target, message="self-learn: adopt")
        calls = chezmoi_shim()
        assert f"diff {target}" not in calls

    def test_dirty_dotfiles_repo_aborts_before_add(self, tmp_path, env, chezmoi_shim, monkeypatch):
        monkeypatch.setenv("CHEZMOI_SHIM_STATUS", " M some-other-file\n")
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        with pytest.raises(chezmoi.ChezmoiAbort):
            chezmoi.adopt_user_scope(target, message="self-learn: adopt")
        calls = chezmoi_shim()
        assert f"add {target}" not in calls

    def test_commit_failure_after_add_degrades_never_rolls_back(
        self, tmp_path, env, chezmoi_shim, monkeypatch
    ):
        monkeypatch.setenv("CHEZMOI_SHIM_COMMIT_RC", "1")
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        result = chezmoi.adopt_user_scope(target, message="self-learn: adopt")
        assert result.tracked is True  # `chezmoi add` already landed
        assert result.synced is False
        assert result.warning is not None
        calls = chezmoi_shim()
        assert f"add {target}" in calls  # never rolled back


# =====================================================================
# Obligation 13 — the bare-CLI hint rides the sync-warning channel;
# the UI-accept and the hint name the SAME entrypoint.
# =====================================================================


class TestObligation13SingleCommandString:
    def test_no_second_hardcoded_adopt_command_string(self):
        """Grep-level: the INVOCATION string 'self-learn chezmoi-adopt
        <path>' — the command a human would actually run — is built from
        exactly one literal, ``chezmoi.ADOPT_COMMAND_PREFIX`` (whose own
        value IS the needle below), defined once in ``chezmoi.py`` and
        referenced everywhere else only as the imported name — never
        hand-copied. Distinguished from the
        ``f"self-learn chezmoi-adopt: {exc}"`` ERROR-prefix idiom
        ``cli.py`` uses (the same ``f"self-learn {args.command}: ..."``
        shape every OTHER ``_cmd_*`` handler uses for its own refusals)
        by the character right after "adopt": a SPACE (interpolating a
        path — an invocation) vs. a COLON (labeling an error) never
        collide as source text."""
        import self_learn.chezmoi as chezmoi_mod
        import self_learn.verbs as verbs_mod
        import self_learn.cli as cli_mod

        invocation_needle = chezmoi.ADOPT_COMMAND_PREFIX  # "self-learn chezmoi-adopt "
        chezmoi_src = open(chezmoi_mod.__file__, encoding="utf-8").read()
        verbs_src = open(verbs_mod.__file__, encoding="utf-8").read()
        cli_src = open(cli_mod.__file__, encoding="utf-8").read()
        assert chezmoi_src.count(invocation_needle) == 1  # its own definition only
        assert invocation_needle not in verbs_src
        assert invocation_needle not in cli_src
        # the UI package's own equivalent check lives in
        # plugins/self-learn/ui/tests/test_proposals.py (a separate venv
        # — this suite cannot import self_learn_ui).

    def test_bare_cli_hint_text_equals_adopt_command_output(self, tmp_path):
        target = tmp_path / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        hint = chezmoi.adopt_command(target)
        assert hint == f"self-learn chezmoi-adopt {target}"

    def test_cli_chezmoi_adopt_subcommand_dispatches(
        self, tmp_path, env, chezmoi_shim, monkeypatch, capsys
    ):
        """argparse-level wiring for the accepted §10 offer: ``self-learn
        chezmoi-adopt <path>`` must reach :func:`verbs.chezmoi_adopt` ->
        :func:`chezmoi.adopt_user_scope`, not just be a registered-but-
        dead subparser. No ledger home-gate on this surface (see
        ``_cmd_chezmoi_adopt``'s docstring) — SELF_LEARN_HOME is set
        anyway, matching how the real CLI is always invoked."""
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        target = tmp_path / "dot-claude" / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("# subagents\n", encoding="utf-8")

        rc = cli.main(["chezmoi-adopt", str(target)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "tracked + synced" in out
        calls = chezmoi_shim()
        assert any(c.startswith("add ") and str(target) in c for c in calls)
        assert any("commit" in c for c in calls)
        # exact subcommand match, never a bare "push" substring — the
        # target path lives under pytest's per-test tmp_path, whose
        # directory name is derived from the test's own name and can
        # itself contain "push" (as the sibling --no-push test's tmp_path
        # does), which would false-positive a substring check.
        assert any(c == "git -- push" for c in calls)

    def test_cli_chezmoi_adopt_no_push_flag_skips_only_the_push(
        self, tmp_path, env, chezmoi_shim, monkeypatch, capsys
    ):
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        target = tmp_path / "dot-claude" / "rules" / "subagents.md"
        target.parent.mkdir(parents=True)
        target.write_text("# subagents\n", encoding="utf-8")

        rc = cli.main(["chezmoi-adopt", str(target), "--no-push"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "tracked + synced" in out  # commit alone still counts as synced
        calls = chezmoi_shim()
        assert any("commit" in c for c in calls)
        assert not any(c == "git -- push" for c in calls)


# =====================================================================
# Obligation 14 — compile-set partitions on (variant, rules_topic): two
# topics + one plain record at the same scope never cross-contaminate,
# in EITHER direction.
# =====================================================================


class TestObligation14CompileSetPartition:
    def test_three_records_land_in_three_distinct_files(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")

        seed_user_record(env, record_id="lrn-1a1a1a1a")
        verbs.route(
            env.home, "lrn-1a1a1a1a", dest="claude-md:rules:topic-a",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        seed_user_record(env, record_id="lrn-2b2b2b2b")
        verbs.route(
            env.home, "lrn-2b2b2b2b", dest="claude-md:rules:topic-b",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        seed_user_record(env, record_id="lrn-3c3c3c3c")
        verbs.route(
            env.home, "lrn-3c3c3c3c", dest="claude-md",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )

        plain = target.read_text(encoding="utf-8")
        topic_a = (target.parent / "rules" / "topic-a.md").read_text(encoding="utf-8")
        topic_b = (target.parent / "rules" / "topic-b.md").read_text(encoding="utf-8")

        assert "lrn-3c3c3c3c" in plain
        assert "lrn-1a1a1a1a" not in plain and "lrn-2b2b2b2b" not in plain

        assert "lrn-1a1a1a1a" in topic_a
        assert "lrn-2b2b2b2b" not in topic_a and "lrn-3c3c3c3c" not in topic_a

        assert "lrn-2b2b2b2b" in topic_b
        assert "lrn-1a1a1a1a" not in topic_b and "lrn-3c3c3c3c" not in topic_b


# =====================================================================
# Obligation 15 — first route to a never-seen topic mkdir -p's the
# rules/ parent and creates the file, both legs.
# =====================================================================


class TestObligation15FirstRouteBootstrap:
    def test_user_leg_creates_dir_and_file(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        assert not (target.parent / "rules").exists()
        seed_user_record(env)
        result = verbs.route(
            env.home, OLD, dest="claude-md:rules:subagents",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        topic_file = target.parent / "rules" / "subagents.md"
        assert topic_file.is_file()
        assert OLD in topic_file.read_text(encoding="utf-8")

    def test_project_leg_creates_dir_and_file(self, env):
        assert not (env.host / ".claude").exists()
        seed_project_record(env)
        result = verbs.route(env.home, OLD, dest="claude-md:rules:subagents")
        assert result.commit_sha
        topic_file = env.host / ".claude" / "rules" / "subagents.md"
        assert topic_file.is_file()
        assert OLD in topic_file.read_text(encoding="utf-8")


# =====================================================================
# Obligation 16 — bare `--dest claude-md:rules:<topic>` (route_direct /
# the one-motion path) resolves to the UNPATHED rules file, not plain
# CLAUDE.md.
# =====================================================================


class TestObligation16BareDestOneMotion:
    def test_route_direct_lands_in_unpathed_rules_file_user_scope(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=OLD)
        result = verbs.route_direct(
            env.home, record, dest="claude-md:rules:subagents",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        topic_file = target.parent / "rules" / "subagents.md"
        assert topic_file.is_file()
        assert OLD in topic_file.read_text(encoding="utf-8")
        # plain CLAUDE.md untouched — no marker landed there
        assert BEGIN_MARKER not in target.read_text(encoding="utf-8")
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert routed.routing["variant"] == "rules"
        assert routed.routing["rules_topic"] == "subagents"
        assert "rules_paths" not in routed.routing  # bare --dest: unpathed

    def test_route_direct_lands_in_unpathed_rules_file_project_scope(self, env):
        record = make_behavior(scope="project", record_id=OLD)
        result = verbs.route_direct(
            env.home, record, dest="claude-md:rules:subagents",
            project_path=env.host,
        )
        assert result.commit_sha
        topic_file = env.host / ".claude" / "rules" / "subagents.md"
        assert topic_file.is_file()
        assert OLD in topic_file.read_text(encoding="utf-8")
        assert BEGIN_MARKER not in (env.host / "CLAUDE.md").read_text(encoding="utf-8")


# =====================================================================
# Obligation 17 — the proposal's variant survives the input seam
# (_resolve_destination never None-drops it): a dead glob still refuses.
# =====================================================================


class TestObligation17ProposalVariantSurvivesInputSeam:
    def test_proposal_dead_glob_still_refuses_via_no_dest_route(self, env):
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["definitely/dead/**"],
            ),
        )
        # no --dest at all: proves _resolve_destination's proposal branch
        # threaded rules_paths through to glob validation, not None-dropped.
        with pytest.raises(verbs.VerbError, match="definitely/dead"):
            verbs.route(env.home, OLD)


# =====================================================================
# Obligation 18 — a bad rules-topic slug reports a "rules topic" error,
# never "new-skill name … must be kebab-case".
# =====================================================================


class TestObligation18TopicSlugErrorWording:
    def test_bad_slug_names_rules_topic(self):
        with pytest.raises(verbs.VerbError) as exc:
            verbs._parse_dest("claude-md:rules:Not_Kebab!")
        msg = str(exc.value)
        assert "rules topic" in msg
        assert "new-skill name" not in msg

    def test_empty_topic_refuses(self):
        with pytest.raises(verbs.VerbError, match="topic"):
            verbs._parse_dest("claude-md:rules:")

    def test_proposal_schema_bad_slug_also_names_rules_topic(self, env):
        seed_project_record(env)
        # validate_proposal (invoked by write_proposal itself) is the
        # schema-validation seam (§4.3 obligation 2) — it must ALSO name
        # "rules topic", not "new-skill name", for the same reason as the
        # --dest parser.
        with pytest.raises(ProposalError) as exc:
            write_proposal(
                env.home, OLD,
                proposal_dict(scope='project', 
                    destination="claude-md", variant="rules",
                    rules_topic="Not_Kebab!",
                ),
            )
        msg = str(exc.value)
        assert "rules topic" in msg
        assert "new-skill name" not in msg


# =====================================================================
# U-pathed (r2) — `paths:` frontmatter emission, drift, refusals
# (docs/specs/self-learn/drafts/u-pathed-emission-spec.md). Obligations
# 19+ continue this file's numbering; the pure compiler primitives
# (expected_paths / read_paths_frontmatter / paths_frontmatter_drift) are
# tested directly in test_compilers.py instead.
# =====================================================================


# =====================================================================
# Obligation 19 — A1/A2: project- and user-scope pathed routes emit
# `paths:` to disk, independently (the user leg takes a different write
# path — compile_user_scope, not compile_managed_file).
# =====================================================================


class TestObligation19PathsEmitToDisk:
    def test_project_scope_emits_paths_frontmatter_A1(self, env):
        src = env.host / "src"
        src.mkdir()
        (src / "foo.ts").write_text("x", encoding="utf-8")
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["src/**/*.ts"],
            ),
        )
        result = verbs.route(env.home, OLD)
        assert result.commit_sha
        target = env.host / ".claude" / "rules" / "ts-rules.md"
        assert target.is_file()
        text = target.read_text(encoding="utf-8")
        assert read_frontmatter(text) == {"paths": ["src/**/*.ts"]}
        assert OLD in text
        assert BEGIN_MARKER in text
        assert text.index("paths:") < text.index(BEGIN_MARKER)  # marker is IN the section, below

    def test_user_scope_emits_paths_frontmatter_A2(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="ts-rules",
                rules_paths=["src/**/*.ts"],
            ),
        )
        result = verbs.route(
            env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        rules_target = target.parent / "rules" / "ts-rules.md"
        assert rules_target.is_file()
        text = rules_target.read_text(encoding="utf-8")
        assert read_frontmatter(text) == {"paths": ["src/**/*.ts"]}
        assert OLD in text
        assert text.index("paths:") < text.index(BEGIN_MARKER)


# =====================================================================
# Obligation 20 — A3: the union is deduped and sorted, and widening is
# reported on the second record's own route.
# =====================================================================


class TestObligation20UnionDedupedSortedWidened:
    def test_union_and_widening_reported_A3(self, env):
        for d in ("a", "b", "c"):
            (env.host / d).mkdir()
            (env.host / d / "f.txt").write_text("x", encoding="utf-8")
        seed_project_record(env, record_id="lrn-1a1a1a1a")
        write_proposal(
            env.home, "lrn-1a1a1a1a",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="shared",
                rules_paths=["b/**", "a/**"],
            ),
        )
        verbs.route(env.home, "lrn-1a1a1a1a")

        seed_project_record(env, record_id="lrn-2b2b2b2b")
        write_proposal(
            env.home, "lrn-2b2b2b2b",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="shared",
                rules_paths=["a/**", "c/**"],
            ),
        )
        result2 = verbs.route(env.home, "lrn-2b2b2b2b")

        target = env.host / ".claude" / "rules" / "shared.md"
        text = target.read_text(encoding="utf-8")
        assert read_frontmatter(text) == {"paths": ["a/**", "b/**", "c/**"]}
        assert "lrn-1a1a1a1a" in text and "lrn-2b2b2b2b" in text

        assert any(
            "union of 2 routed lessons" in w for w in result2.warnings
        ), result2.warnings


# =====================================================================
# Obligation 21 — A4: absorption deletes the paths: key and warns naming
# the globless record, with a same-test fail-open control: a SECOND topic
# that kept its globs still carries its own paths: on disk.
# =====================================================================


class TestObligation21AbsorptionAndFailOpenControl:
    def test_absorption_with_second_topic_control_A4(self, env):
        (env.host / "a").mkdir()
        (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")

        # topic "kept": stays pathed throughout — the fail-open control.
        seed_project_record(env, record_id="lrn-1a1a1a1a")
        write_proposal(
            env.home, "lrn-1a1a1a1a",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="kept",
                rules_paths=["a/**"],
            ),
        )
        verbs.route(env.home, "lrn-1a1a1a1a")

        # topic "absorbed": a pathed record, then a globless one.
        seed_project_record(env, record_id="lrn-2b2b2b2b")
        write_proposal(
            env.home, "lrn-2b2b2b2b",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="absorbed",
                rules_paths=["a/**"],
            ),
        )
        verbs.route(env.home, "lrn-2b2b2b2b")

        seed_project_record(env, record_id="lrn-3c3c3c3c")
        write_proposal(
            env.home, "lrn-3c3c3c3c",
            proposal_dict(scope='project', destination="claude-md", variant="rules", rules_topic="absorbed"),
        )
        result = verbs.route(env.home, "lrn-3c3c3c3c")

        absorbed = (env.host / ".claude" / "rules" / "absorbed.md").read_text(encoding="utf-8")
        assert "paths:" not in absorbed
        assert "lrn-2b2b2b2b" in absorbed and "lrn-3c3c3c3c" in absorbed

        kept = (env.host / ".claude" / "rules" / "kept.md").read_text(encoding="utf-8")
        assert read_frontmatter(kept) == {"paths": ["a/**"]}

        assert any(
            "UNPATHED" in w and "lrn-3c3c3c3c" in w for w in result.warnings
        ), result.warnings


# =====================================================================
# Obligation 22 — A5: retirement (supersede) narrows the union to the
# survivor's own globs — proves emission reads C(T), not
# TargetSpec.rules_paths.
# =====================================================================


class TestObligation22RetirementNarrowsUnion:
    def test_supersede_narrows_paths_to_survivor_A5(self, env):
        for d in ("a", "b"):
            (env.host / d).mkdir()
            (env.host / d / "f.txt").write_text("x", encoding="utf-8")
        seed_project_record(env, record_id="lrn-1a1a1a1a")
        write_proposal(
            env.home, "lrn-1a1a1a1a",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="topic",
                rules_paths=["a/**"],
            ),
        )
        verbs.route(env.home, "lrn-1a1a1a1a")

        seed_project_record(env, record_id="lrn-2b2b2b2b")
        write_proposal(
            env.home, "lrn-2b2b2b2b",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="topic",
                rules_paths=["b/**"],
            ),
        )
        verbs.route(env.home, "lrn-2b2b2b2b")

        target = env.host / ".claude" / "rules" / "topic.md"
        assert read_frontmatter(target.read_text(encoding="utf-8")) == {
            "paths": ["a/**", "b/**"]
        }

        verbs.supersede(env.home, "lrn-1a1a1a1a", "lrn-2b2b2b2b")
        text = target.read_text(encoding="utf-8")
        assert read_frontmatter(text) == {"paths": ["b/**"]}
        assert "lrn-1a1a1a1a" not in text
        assert "lrn-2b2b2b2b" in text


# =====================================================================
# Obligation 23 — A6/A13: recompile repairs a COMMITTED hand-edited
# paths:, commits the repair, and reports the drift-repaired note; a
# second recompile is a no-op.
# =====================================================================


class TestObligation23RecompileRepairsHandEdit:
    def _route_pathed(self, env):
        (env.host / "a").mkdir()
        (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="topic",
                rules_paths=["a/**"],
            ),
        )
        verbs.route(env.home, OLD)
        target = env.host / ".claude" / "rules" / "topic.md"
        text = target.read_text(encoding="utf-8")
        target.write_text(text.replace("a/**", "z/**"), encoding="utf-8")
        # A6: the edit must be COMMITTED — an uncommitted edit makes the
        # target dirty and `recompile` refuses it before ever reaching
        # `_apply_target` (this is the ONLY reachable form of this case).
        commit_all(env.host, "hand edit paths")
        return target

    def test_recompile_repairs_committed_hand_edit_A6(self, env):
        target = self._route_pathed(env)
        result = verbs.recompile(env.home)
        text2 = target.read_text(encoding="utf-8")
        assert read_frontmatter(text2) == {"paths": ["a/**"]}

        entry = next(e for e in result.entries if e.target.name == "topic.md")
        assert entry.changed is True
        assert entry.commit_sha is not None
        assert any(f.endswith("topic.md") for f in verb_files(env.host))
        assert any(
            "rewrote the compiler-owned" in w for w in result.warnings
        ), result.warnings

    def test_second_recompile_is_a_noop_A13(self, env):
        target = self._route_pathed(env)
        verbs.recompile(env.home)
        before = target.read_text(encoding="utf-8")

        result2 = verbs.recompile(env.home)
        entry2 = next(e for e in result2.entries if e.target.name == "topic.md")
        assert entry2.changed is False
        assert entry2.commit_sha is None
        assert target.read_text(encoding="utf-8") == before

    def test_route_into_corrupt_leading_block_surfaces_host_phase_failure_A8(
        self, env
    ):
        """A8's route-time clause: an already-committed, corrupt leading
        block (unterminated ``---``) makes the compile step raise
        CompileError. `_host_phase` catches it (H-2: the ledger stays
        truth, never rolled back) and surfaces a HOST PHASE FAILED
        warning naming `recompile` — the record still moves to
        resolved/, exactly like the skill-md host-phase-failure case
        (test_hosting.py::test_host_phase_failure_warns_then_recompile_repairs)."""
        (env.host / "a").mkdir()
        (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")
        target = env.host / ".claude" / "rules" / "topic.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nno terminator\n", encoding="utf-8")
        commit_all(env.host, "corrupt leading block")
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="topic",
                rules_paths=["a/**"],
            ),
        )
        result = verbs.route(env.home, OLD)
        assert any("HOST PHASE FAILED" in w for w in result.warnings), result.warnings
        assert any("recompile" in w for w in result.warnings)
        assert (project_bucket_dir(env) / "resolved" / f"{OLD}.md").is_file()
        assert not (project_bucket_dir(env) / "pending" / f"{OLD}.md").is_file()


# =====================================================================
# Obligation 24 — A9: the dead-glob positive control — refuses (nothing
# created) without the flag; with it, the dead glob lands on disk in
# paths: verbatim and routing.allow_empty_glob is recorded True.
# =====================================================================


class TestObligation24DeadGlobPositiveControl:
    def test_refuses_and_creates_nothing_without_flag_A9(self, env):
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="dead-topic",
                rules_paths=["nope/**"],
            ),
        )
        with pytest.raises(verbs.VerbError):
            verbs.route(env.home, OLD)
        assert (project_bucket_dir(env) / "pending" / f"{OLD}.md").is_file()
        assert not (env.host / ".claude" / "rules" / "dead-topic.md").exists()

    def test_flag_lands_dead_glob_verbatim_on_disk_A9(self, env):
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="dead-topic",
                rules_paths=["nope/**"],
            ),
        )
        result = verbs.route(env.home, OLD, allow_empty_glob=True)
        assert result.commit_sha
        target = env.host / ".claude" / "rules" / "dead-topic.md"
        text = target.read_text(encoding="utf-8")
        assert read_frontmatter(text) == {"paths": ["nope/**"]}
        routed = Record.from_path(project_bucket_dir(env) / "resolved" / f"{OLD}.md")
        assert routed.routing["allow_empty_glob"] is True


# =====================================================================
# Obligation 25 — A10: absolute and `~` globs refuse pre-ledger at both
# scopes; the same pattern made relative succeeds and emits.
# =====================================================================


class TestObligation25AbsoluteAndHomeGlobRefusal:
    def test_absolute_glob_refused_project_scope_A10(self, env):
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="abs-topic",
                rules_paths=["/etc/hosts"],
            ),
        )
        with pytest.raises(verbs.VerbError, match="absolute"):
            verbs.route(env.home, OLD)
        assert (project_bucket_dir(env) / "pending" / f"{OLD}.md").is_file()

    def test_home_glob_refused_user_scope_A10(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="home-topic",
                rules_paths=["~/foo/**"],
            ),
        )
        with pytest.raises(verbs.VerbError):
            verbs.route(
                env.home, OLD, user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
            )
        assert (env.home / "user" / "pending" / f"{OLD}.md").is_file()

    def test_positive_control_relative_pattern_succeeds_A10(self, env):
        (env.host / "etc-like").mkdir()
        (env.host / "etc-like" / "hosts").write_text("x", encoding="utf-8")
        seed_project_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="abs-topic",
                rules_paths=["etc-like/hosts"],
            ),
        )
        result = verbs.route(env.home, OLD)
        assert result.commit_sha
        target = env.host / ".claude" / "rules" / "abs-topic.md"
        assert read_frontmatter(target.read_text(encoding="utf-8")) == {
            "paths": ["etc-like/hosts"]
        }


# =====================================================================
# Obligation 26 — A11: chezmoi MANAGED, both legs of the refusal, plus
# the unpathed-into-unpathed success leg with an unchanged call count.
# =====================================================================


class TestObligation26ChezmoiManagedRefusal:
    def test_pathed_route_refuses_pre_ledger_on_managed_A11a(self, tmp_path, env, chezmoi_shim):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="managed-topic",
                rules_paths=["a/**"],
            ),
        )
        with pytest.raises(verbs.VerbError, match="chezmoi"):
            verbs.route(env.home, OLD, user_claude_md=target)
        assert (env.home / "user" / "pending" / f"{OLD}.md").is_file()

    def test_globless_into_already_pathed_topic_refuses_on_managed_A11b(
        self, tmp_path, env, chezmoi_shim
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        rules_dir.mkdir()
        (rules_dir / "already-pathed.md").write_text(
            "---\npaths:\n  - a/**\n---\n", encoding="utf-8"
        )
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="already-pathed",
            ),
        )
        with pytest.raises(verbs.VerbError, match="chezmoi"):
            verbs.route(env.home, OLD, user_claude_md=target)
        assert (env.home / "user" / "pending" / f"{OLD}.md").is_file()

    def test_globless_into_topic_with_empty_list_paths_refuses_on_managed_A11b_F1(
        self, tmp_path, env, chezmoi_shim
    ):
        """F1: `paths: []` is EXACTLY the value `read_paths_frontmatter`
        would normalize down to `()` (same as "no key at all"), but the
        pre-pass's own agreement predicate treats it as disagreement and
        rewrites it — so a refusal keyed on the reader would silently let
        this one through, defeating the exact guard §3.4(2)/F8 exists to
        provide. Reproduces F1's own table: without the fix this route
        does NOT raise here; it lands in resolved/, and the pre-pass's
        later write is read by chezmoi's OWN drift check as pre-existing
        drift — an unrecoverable post-ledger abort."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        rules_dir.mkdir()
        (rules_dir / "empty-list-topic.md").write_text(
            "---\npaths: []\n---\n", encoding="utf-8"
        )
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="empty-list-topic",
            ),
        )
        with pytest.raises(verbs.VerbError, match="chezmoi"):
            verbs.route(env.home, OLD, user_claude_md=target)
        assert (env.home / "user" / "pending" / f"{OLD}.md").is_file()
        assert not (env.home / "user" / "resolved" / f"{OLD}.md").is_file()

    def test_globless_into_topic_with_scalar_paths_refuses_on_managed_A11b_F1(
        self, tmp_path, env, chezmoi_shim
    ):
        """F1's third table row: a scalar `paths: src/**` is the OTHER
        value the reader normalizes away but the agreement predicate
        rewrites — same reproduction, different malformed shape."""
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        rules_dir = target.parent / "rules"
        rules_dir.mkdir()
        (rules_dir / "scalar-topic.md").write_text(
            "---\npaths: src/**\n---\n", encoding="utf-8"
        )
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="scalar-topic",
            ),
        )
        with pytest.raises(verbs.VerbError, match="chezmoi"):
            verbs.route(env.home, OLD, user_claude_md=target)
        assert (env.home / "user" / "pending" / f"{OLD}.md").is_file()
        assert not (env.home / "user" / "resolved" / f"{OLD}.md").is_file()

    def test_unpathed_route_into_unpathed_file_succeeds_unchanged_calls_A11c(
        self, tmp_path, env, chezmoi_shim
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(scope='user', 
                destination="claude-md", variant="rules", rules_topic="fresh-topic",
            ),
        )
        result = verbs.route(env.home, OLD, user_claude_md=target)
        assert result.commit_sha
        rules_target = target.parent / "rules" / "fresh-topic.md"
        assert OLD in rules_target.read_text(encoding="utf-8")
        calls = chezmoi_shim()
        # unchanged call sequence: `preflight_user_scope` probes capability
        # once, `compile_user_scope` re-derives it once more on its own
        # (pre-existing, unrelated to this unit) — TWO `source-path` calls
        # total. The new §3.4(2) check short-circuits BEFORE ever calling
        # `user_scope_capability` a THIRD time when neither leg of its own
        # condition holds — proving it added no extra chezmoi traffic here.
        assert len([c for c in calls if c.startswith("source-path")]) == 2


# =====================================================================
# Obligation 27 — A14: caps (word_count/over_cap) are unaffected by
# frontmatter, on a file that provably HAS it.
# =====================================================================


class TestObligation27CapsUnaffectedByFrontmatter:
    def test_word_count_and_over_cap_equal_with_and_without_frontmatter_A14(self, env):
        (env.host / "a").mkdir()
        (env.host / "a" / "f.txt").write_text("x", encoding="utf-8")

        seed_project_record(env, record_id="lrn-1a1a1a1a")
        write_proposal(
            env.home, "lrn-1a1a1a1a",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="pathed-topic",
                rules_paths=["a/**"],
            ),
        )
        pathed_result = verbs.route(env.home, "lrn-1a1a1a1a")

        seed_project_record(env, record_id="lrn-2b2b2b2b")
        write_proposal(
            env.home, "lrn-2b2b2b2b",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="unpathed-topic",
            ),
        )
        unpathed_result = verbs.route(env.home, "lrn-2b2b2b2b")

        pathed_section = pathed_result.compile_result
        unpathed_section = unpathed_result.compile_result
        assert pathed_section.word_count == unpathed_section.word_count
        assert pathed_section.over_cap == unpathed_section.over_cap

        # And: the pathed file's paths: really IS on disk — otherwise this
        # criterion is satisfied by a build that emits nothing at all.
        pathed_target = env.host / ".claude" / "rules" / "pathed-topic.md"
        assert read_frontmatter(pathed_target.read_text(encoding="utf-8")) == {
            "paths": ["a/**"]
        }


# =====================================================================
# Obligation 28 — A12: every non-rules target is byte-identical,
# INCLUDING its own frontmatter — the `variant == "rules"` guard (M21) is
# load-bearing. SKILL.md's own name:/description: frontmatter survives a
# skill-md route byte-for-byte; a second SKILL.md whose leading block is
# NOT mapping-shaped routes WITHOUT raising (an ungated pre-pass would
# round-trip the first and CompileError on the second). A rules route in
# the SAME fixture is the positive control: "no frontmatter anywhere"
# cannot pass.
# =====================================================================


_OBLIGATION28_MARKETPLACE = {
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


class TestObligation28NonRulesTargetsByteIdentical:
    def test_non_rules_targets_untouched_M21(self, tmp_path):
        sandbox = make_env(tmp_path, skills=("s", "t"))
        home, host = sandbox.ledger, sandbox.host

        # --- fixture: SKILL.md WITH real name:/description: frontmatter ---
        skill_s = host / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md"
        skill_s_frontmatter = "---\nname: s\ndescription: A skill about s things.\n---\n\n"
        skill_s.write_text(
            skill_s_frontmatter + "# s skill\n\nAuthored prose stays put.\n",
            encoding="utf-8",
        )

        # --- fixture: SKILL.md whose leading block is NOT mapping-shaped ---
        skill_t = host / "plugins" / "t-plugin" / "skills" / "t" / "SKILL.md"
        skill_t_block = "---\n- a\n- b\n---\n\n"
        skill_t.write_text(
            skill_t_block + "# t skill\n\nAuthored prose stays put.\n",
            encoding="utf-8",
        )

        # --- fixture: marketplace.json for the new-skill leg ---
        marketplace = host / ".claude-plugin" / "marketplace.json"
        marketplace.parent.mkdir()
        marketplace.write_text(
            json.dumps(_OBLIGATION28_MARKETPLACE, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # --- fixture: .gitignore for the CLAUDE.local.md leg ---
        (host / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")

        git(host, "add", "-A")
        git(host, "commit", "-q", "-m", "obligation-28 fixtures")

        def seed(scope, record_id):
            record = make_behavior(scope=scope, record_id=record_id)
            create_record(
                home, record, project_path=host if scope == "project" else None
            )
            return record

        # 1. plain user CLAUDE.md — no paths: anywhere.
        user_target = tmp_path / "dot-claude" / "CLAUDE.md"
        user_target.parent.mkdir()
        user_target.write_text("# user conduct\n", encoding="utf-8")
        seed("user", "lrn-00000001")
        r1 = verbs.route(
            home, "lrn-00000001", dest="claude-md", user_claude_md=user_target,
            chezmoi_bin="chezmoi-definitely-absent",
        )
        assert r1.commit_sha
        assert "paths:" not in user_target.read_text(encoding="utf-8")

        # 2. plain project CLAUDE.md — no paths: anywhere.
        seed("project", "lrn-00000002")
        r2 = verbs.route(home, "lrn-00000002", dest="claude-md")
        assert r2.commit_sha
        assert "paths:" not in (host / "CLAUDE.md").read_text(encoding="utf-8")

        # 3. SKILL.md with real frontmatter — byte-identical after the route.
        seed("skill:s", "lrn-00000003")
        r3 = verbs.route(home, "lrn-00000003", dest="skill-md")
        assert r3.commit_sha
        text3 = skill_s.read_text(encoding="utf-8")
        assert text3.startswith(skill_s_frontmatter)  # untouched, byte-for-byte
        assert "paths:" not in text3
        assert "lrn-00000003" in text3

        # 4. SKILL.md whose leading block is NOT mapping-shaped — routes
        #    WITHOUT raising, and the bogus fence survives untouched. An
        #    ungated pre-pass CompileError's here (M21's own target).
        seed("skill:t", "lrn-00000004")
        r4 = verbs.route(home, "lrn-00000004", dest="skill-md")
        assert r4.commit_sha
        text4 = skill_t.read_text(encoding="utf-8")
        assert text4.startswith(skill_t_block)
        assert "lrn-00000004" in text4

        # 5. CLAUDE.local.md — no paths: anywhere.
        seed("project", "lrn-00000005")
        r5 = verbs.route(home, "lrn-00000005", dest="claude-md:local")
        assert r5.commit_sha
        local_target = host / "CLAUDE.local.md"
        assert "paths:" not in local_target.read_text(encoding="utf-8")

        # 6. new-skill — no paths: anywhere, in the new SKILL.md.
        seed("skill:s", "lrn-00000006")
        r6 = verbs.route(home, "lrn-00000006", dest="new-skill:mouse-firmware")
        assert r6.commit_sha
        new_skill_md = (
            host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware" / "SKILL.md"
        )
        assert "paths:" not in new_skill_md.read_text(encoding="utf-8")

        # 7. Positive control, in the SAME fixture: a rules route DOES
        #    carry frontmatter — "no frontmatter anywhere" cannot pass.
        (host / "z").mkdir()
        (host / "z" / "f.txt").write_text("x", encoding="utf-8")
        seed("project", "lrn-00000007")
        write_proposal(
            home, "lrn-00000007",
            proposal_dict(scope='project', 
                destination="claude-md", variant="rules", rules_topic="control-topic",
                rules_paths=["z/**"],
            ),
        )
        r7 = verbs.route(home, "lrn-00000007")
        assert r7.commit_sha
        control_target = host / ".claude" / "rules" / "control-topic.md"
        assert "paths:" in control_target.read_text(encoding="utf-8")


# =====================================================================
# U-demand-user §3.2 / A1-A3/A6/A14 — an explicit `--dest
# claude-md:rules:<topic>` inherits the proposal sibling's rules_paths,
# scoped to an EXACT destination/variant/topic match; guarded, never
# trusted, and never widened to a bare claude-md dest. Obligations
# start at 29 (builder decision 3 — the last existing class is
# TestObligation28NonRulesTargetsByteIdentical). The reference-refusal
# criterion (A9) lives in test_verbs.py beside TestRouteDestination.
# =====================================================================


class TestObligation29TwoRoadsProduceIdenticalBytes:
    """A1 — the headline criterion. Two independent sandboxes, the SAME
    rules proposal; sandbox 1 routes bare (`route <id>`), sandbox 2
    routes with the review UI's own shape (`--dest
    claude-md:rules:<topic> --by analyst`). Both must write
    byte-identical rules files, byte-identical frontmatter (re-parsed
    with an INDEPENDENT ruamel loader, never compilers.py's own reader),
    and equal routing blocks."""

    def test_bare_and_explicit_dest_produce_identical_output(self, tmp_path):
        sandbox1 = make_env(tmp_path / "s1")
        sandbox2 = make_env(tmp_path / "s2")
        rid = "lrn-00000001"
        for sandbox in (sandbox1, sandbox2):
            record = make_behavior(scope="user", record_id=rid)
            create_record(sandbox.ledger, record)
            write_proposal(
                sandbox.ledger, rid,
                proposal_dict(
                    scope="user",
                    destination="claude-md", variant="rules", rules_topic="t",
                    rules_paths=["**/*.py"],
                ),
            )
        target1 = tmp_path / "s1-dot-claude" / "CLAUDE.md"
        target1.parent.mkdir()
        target1.write_text("# user conduct\n", encoding="utf-8")
        target2 = tmp_path / "s2-dot-claude" / "CLAUDE.md"
        target2.parent.mkdir()
        target2.write_text("# user conduct\n", encoding="utf-8")

        r1 = verbs.route(
            sandbox1.ledger, rid,
            user_claude_md=target1, chezmoi_bin="chezmoi-definitely-absent",
        )
        r2 = verbs.route(
            sandbox2.ledger, rid, dest="claude-md:rules:t", by="analyst",
            user_claude_md=target2, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert r1.commit_sha and r2.commit_sha

        file1 = target1.parent / "rules" / "t.md"
        file2 = target2.parent / "rules" / "t.md"
        text1 = file1.read_text(encoding="utf-8")
        text2 = file2.read_text(encoding="utf-8")
        assert text1 == text2

        assert read_frontmatter(text1) == {"paths": ["**/*.py"]}
        assert read_frontmatter(text2) == {"paths": ["**/*.py"]}

        routed1 = Record.from_path(sandbox1.ledger / "user" / "resolved" / f"{rid}.md")
        routed2 = Record.from_path(sandbox2.ledger / "user" / "resolved" / f"{rid}.md")
        for key in ("variant", "rules_topic", "rules_paths"):
            assert routed1.routing.get(key) == routed2.routing.get(key)
        assert routed1.routing["by"] == "analyst"
        assert routed2.routing["by"] == "analyst"


class TestObligation30BareClaudeMdNeverInherits:
    """A2 — a bare `--dest claude-md` still routes to the always-loaded
    file, even when the proposal IS a rules proposal (M2's target: an
    over-widened predicate that adopts variant/rules_topic/rules_paths
    wholesale on ANY claude-md dest)."""

    def test_bare_claude_md_ignores_rules_proposal(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(
                scope="user",
                destination="claude-md", variant="rules", rules_topic="t",
                rules_paths=["**/*.py"],
            ),
        )
        result = verbs.route(
            env.home, OLD, dest="claude-md",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        assert OLD in target.read_text(encoding="utf-8")
        assert not (target.parent / "rules" / "t.md").exists()
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert "variant" not in routed.routing
        assert "rules_topic" not in routed.routing
        assert "rules_paths" not in routed.routing


class TestObligation31MismatchedTopicNeverInherits:
    """A3 — a proposal naming topic `t` with globs never leaks them onto
    a DIFFERENT topic the human explicitly named via --dest (M3's
    target: dropping the topic comparison)."""

    def test_different_topic_gets_no_paths(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        write_proposal(
            env.home, OLD,
            proposal_dict(
                scope="user",
                destination="claude-md", variant="rules", rules_topic="t",
                rules_paths=["**/*.py"],
            ),
        )
        result = verbs.route(
            env.home, OLD, dest="claude-md:rules:other",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        other_file = target.parent / "rules" / "other.md"
        assert other_file.is_file()
        assert "paths:" not in other_file.read_text(encoding="utf-8")
        routed = Record.from_path(env.home / "user" / "resolved" / f"{OLD}.md")
        assert routed.routing["rules_topic"] == "other"
        assert "rules_paths" not in routed.routing


class TestObligation32InheritanceNeverRaises:
    """A6 — a --dest claude-md:rules:<topic> route succeeds (unpathed)
    whether the sibling is (a) absent, (b) unparseable YAML, or (c)
    schema-invalid — the sibling read is guarded, never trusted; none
    of the three turns a working route into a refusal."""

    def _assert_unpathed_route_succeeds(self, env, target):
        result = verbs.route(
            env.home, OLD, dest="claude-md:rules:t",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert result.commit_sha
        topic_file = target.parent / "rules" / "t.md"
        assert topic_file.is_file()
        assert OLD in topic_file.read_text(encoding="utf-8")
        assert "paths:" not in topic_file.read_text(encoding="utf-8")

    def test_no_sibling_still_routes_unpathed(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        self._assert_unpathed_route_succeeds(env, target)

    def test_unparseable_yaml_sibling_still_routes_unpathed(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        sibling = env.home / "user" / "proposals" / f"{OLD}.yaml"
        sibling.parent.mkdir(parents=True, exist_ok=True)
        sibling.write_text("{ this is not valid yaml\n", encoding="utf-8")
        self._assert_unpathed_route_succeeds(env, target)

    def test_schema_invalid_sibling_still_routes_unpathed(self, tmp_path, env):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        seed_user_record(env)
        sibling = env.home / "user" / "proposals" / f"{OLD}.yaml"
        sibling.parent.mkdir(parents=True, exist_ok=True)
        # variant: rules with NO rules_topic — _validate_rules_fields
        # refuses this (schema-invalid), never a parse error.
        sibling.write_text(
            "destination: claude-md\n"
            "variant: rules\n"
            "rationale: x\n"
            "model: claude\n"
            "analyzed_at: '2026-07-13T00:00:00Z'\n",
            encoding="utf-8",
        )
        self._assert_unpathed_route_succeeds(env, target)


class TestObligation33NonRulesDestByteIdentical:
    """A14 — routing to a NON-rules destination via an explicit --dest
    is unaffected by §3.2's inheritance (M1-M4 over-reaching would show
    up here first — the blast-radius net for this unit's own change).
    Positive control in the SAME fixture: one rules route DOES pick up
    frontmatter — "nothing changed anywhere" cannot pass this test."""

    def test_every_non_rules_dest_byte_identical_plus_rules_control(self, tmp_path, env):
        marketplace = env.host / ".claude-plugin" / "marketplace.json"
        marketplace.parent.mkdir(parents=True, exist_ok=True)
        marketplace.write_text(
            json.dumps(_OBLIGATION28_MARKETPLACE, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (env.host / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "obligation-33 marketplace fixture")

        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")

        # 1. plain user CLAUDE.md — no paths:, no variant.
        seed_user_record(env, record_id="lrn-00000001")
        r1 = verbs.route(
            env.home, "lrn-00000001", dest="claude-md",
            user_claude_md=target, chezmoi_bin="chezmoi-definitely-absent",
        )
        assert r1.commit_sha
        assert "paths:" not in target.read_text(encoding="utf-8")

        # 2. plain project CLAUDE.md.
        seed_project_record(env, record_id="lrn-00000002")
        r2 = verbs.route(env.home, "lrn-00000002", dest="claude-md")
        assert r2.commit_sha
        assert "paths:" not in (env.host / "CLAUDE.md").read_text(encoding="utf-8")

        # 3. SKILL.md.
        seed_skill_record(env, record_id="lrn-00000003")
        r3 = verbs.route(env.home, "lrn-00000003", dest="skill-md")
        assert r3.commit_sha
        assert "lrn-00000003" in env.skill_md.read_text(encoding="utf-8")

        # 4. CLAUDE.local.md.
        seed_project_record(env, record_id="lrn-00000004")
        r4 = verbs.route(env.home, "lrn-00000004", dest="claude-md:local")
        assert r4.commit_sha
        assert "lrn-00000004" in (env.host / "CLAUDE.local.md").read_text(encoding="utf-8")

        # 5. reference, skill scope.
        seed_skill_record(env, record_id="lrn-00000005")
        r5 = verbs.route(env.home, "lrn-00000005", dest="reference")
        assert r5.commit_sha
        learnings = env.skill_dir / "references" / "LEARNINGS.md"
        assert "lrn-00000005" in learnings.read_text(encoding="utf-8")

        # 6. new-skill.
        seed_skill_record(env, record_id="lrn-00000006")
        r6 = verbs.route(env.home, "lrn-00000006", dest="new-skill:mouse-firmware")
        assert r6.commit_sha
        new_skill_md = (
            env.host / "plugins" / "mouse-firmware" / "skills" / "mouse-firmware" / "SKILL.md"
        )
        assert "lrn-00000006" in new_skill_md.read_text(encoding="utf-8")

        # 7. Positive control — a rules route in the SAME fixture DOES
        #    produce a pathed file.
        (env.host / "control.py").write_text("x = 1\n", encoding="utf-8")
        seed_project_record(env, record_id="lrn-00000007")
        write_proposal(
            env.home, "lrn-00000007",
            proposal_dict(
                scope="project",
                destination="claude-md", variant="rules", rules_topic="control",
                rules_paths=["*.py"],
            ),
        )
        r7 = verbs.route(env.home, "lrn-00000007", dest="claude-md:rules:control")
        assert r7.commit_sha
        control_file = env.host / ".claude" / "rules" / "control.md"
        assert "paths:" in control_file.read_text(encoding="utf-8")
