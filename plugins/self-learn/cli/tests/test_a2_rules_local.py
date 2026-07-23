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

import os
import stat

import pytest

from self_learn import chezmoi, cli, selfcheck, verbs
from self_learn.compilers import BEGIN_MARKER
from self_learn.hosts import slug_for
from self_learn.ledger_ops import (
    ProposalError,
    create_record,
    write_proposal,
)
from self_learn.records import Record

from support import make_behavior, make_env, proposal_dict

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
            proposal_dict(
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
            proposal_dict(
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
            proposal_dict(
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
            proposal_dict(
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
            proposal_dict(
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
            proposal_dict(
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
            proposal_dict(
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
            proposal_dict(
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
                proposal_dict(
                    destination="claude-md", variant="rules",
                    rules_topic="Not_Kebab!",
                ),
            )
        msg = str(exc.value)
        assert "rules topic" in msg
        assert "new-skill name" not in msg
