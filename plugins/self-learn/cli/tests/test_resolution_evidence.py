"""Resolution-evidence unit (docs/specs/self-learn/drafts/
resolution-evidence-spec.md) — CLI-side (§2.1/§3.1/§3.3): the `--json`
envelope on route/reject/defer/graduate.

Per §5's test plan: one envelope test per verb (route-append,
route-create, defer, reject, graduate) plus one per destination shape
that differs (reference, user-scope, `claude-md:local`, hook,
new-skill); `--json` changes neither exit status nor what lands on
disk; stdout parses as JSON and contains nothing else for hook/
new-skill routes (which otherwise print a script / post_notes prose);
the drift state (§3.3 state 4) reached via a REAL fixture, no
monkeypatching, per §5's own warning against constructing a
``VerbResult`` directly; and stderr byte-identical under ``--json``.

Sandboxes follow this suite's existing convention (support.make_env +
bare remotes, XDG-redirected cache) — never the operator's real
``~/.claude``/``~/.self-learn``.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from self_learn import cli, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER, entry_line
from self_learn.ledger_ops import create_record, stamp_proposal, write_proposal
from self_learn.records import Record

from support import (
    commit_all,
    git,
    hook_proposal_fields,
    make_behavior,
    make_env,
    make_knowledge,
    proposal_dict,
)

RID = "lrn-0000aaaa"
RID2 = "lrn-0000bbbb"

#: Same PATH-shimmed fake chezmoi test_a2_rules_local.py uses — never
#: the real chezmoi, never the real ~/.claude. `CHEZMOI_SHIM_SOURCE_RC=1`
#: makes `source-path` fail, which `user_scope_capability` reads as
#: UNMANAGED (rc 0 = managed, nonzero = unmanaged).
CHEZMOI_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CHEZMOI_SHIM_LOG"
case "$1" in
  source-path) exit "${CHEZMOI_SHIM_SOURCE_RC-0}" ;;
  diff) printf '%s' "${CHEZMOI_SHIM_DIFF-}" ;;
esac
exit "${CHEZMOI_SHIM_EXIT-0}"
"""


class Env:
    """The doc-13 sandbox pair, WITH bare remotes (both repos) so
    `pushed`/`host_pushed` read "pushed" rather than "no remote
    configured" — matches test_route_cli.py's `Env`."""

    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir
        self.skill_md = sandbox.skill_md
        self.bare = tmp_path / "ledger-remote.git"
        self.host_bare = tmp_path / "host-remote.git"
        for repo, bare in ((self.home, self.bare), (self.host, self.host_bare)):
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
            )
            git(repo, "remote", "add", "origin", str(bare))
            git(repo, "push", "-q", "-u", "origin", "main")


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    return e


def seed_skill_record(env, rid=RID, **kw):
    record = make_behavior(scope="skill:s", record_id=rid, **kw)
    create_record(env.home, record)
    return record


def run_json(argv, capsys) -> tuple[int, dict]:
    """`cli.main(argv)`, asserting stdout parses as JSON and — per §4's
    "stdout is the envelope and NOTHING else" — contains nothing else."""
    code = cli.main(argv)
    out = capsys.readouterr().out
    envelope = json.loads(out)  # raises if anything else shares stdout
    return code, envelope


# ===================================================================== #
# Per-verb envelope tests
# ===================================================================== #


class TestRouteEnvelope:
    def test_route_create_bootstraps_a_fresh_section(self, env, capsys):
        """First route to skill-md: markers are absent, so `created`
        (SectionResult.bootstrapped) is True."""
        seed_skill_record(env)
        code, envelope = run_json(
            ["route", RID, "--dest", "skill-md", "--json"], capsys
        )
        assert code == 0
        assert envelope["action"] == "route"
        assert envelope["record_id"] == RID
        # target, NEVER staged — the single most important thing (spec
        # §0's own framing): staged is the LEDGER path, canon_path must
        # be the HOST path the human actually cares about.
        assert envelope["canon_path"] == str(env.skill_md)
        assert envelope["host_commit_sha"]
        assert isinstance(envelope["ledger_paths"], list) and envelope["ledger_paths"]
        assert envelope["commit_message"] == f"self-learn: route {RID} → skill-md"
        assert envelope["destination"] == "skill-md"
        assert envelope["variant"] is None
        assert envelope["deferred_until"] is None
        assert envelope["warnings"] == []
        assert envelope["created"] is True
        assert envelope["outcome_state"] == "landed"
        # U-cap §6.2: the envelope key is renamed `over_cap` -> `budget`,
        # carrying the post-route budget FACT (never null when there is a
        # managed-section compile result to describe, as here).
        assert envelope["budget"] is not None
        assert envelope["budget"].startswith("budget: ")
        assert envelope["pushed"] == "pushed"
        assert envelope["host_pushed"] == "pushed"

    def test_route_append_does_not_reclaim_bootstrapped(self, env, capsys):
        """Second route to the SAME already-managed target: markers
        already exist, so `created` is False — an appended entry, not a
        fresh section."""
        seed_skill_record(env, rid=RID)
        assert cli.main(["route", RID, "--dest", "skill-md"]) == 0
        capsys.readouterr()  # discard the first (non-json) route's stdout

        seed_skill_record(env, rid=RID2)
        code, envelope = run_json(
            ["route", RID2, "--dest", "skill-md", "--json"], capsys
        )
        assert code == 0
        assert envelope["created"] is False
        assert envelope["outcome_state"] == "landed"
        assert envelope["canon_path"] == str(env.skill_md)

    def test_json_changes_neither_exit_status_nor_disk_state(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        """DoD #1/§5: "assert --json changes neither exit status nor what
        lands on disk". Two independent sandboxes, the identical route,
        one plain and one `--json` — the compiled SKILL.md content and
        the resolved record's bytes must match exactly (commit shas are
        allowed to differ — they are not "what lands on disk" in the
        sense this rule means; the FILE CONTENT is)."""
        plain = Env(tmp_path / "plain")
        as_json = Env(tmp_path / "as-json")
        for e in (plain, as_json):
            record = make_behavior(scope="skill:s", record_id=RID)
            create_record(e.home, record)

        monkeypatch.setenv("SELF_LEARN_HOME", str(plain.home))
        code_plain = cli.main(["route", RID, "--dest", "skill-md"])
        capsys.readouterr()

        monkeypatch.setenv("SELF_LEARN_HOME", str(as_json.home))
        code_json = cli.main(["route", RID, "--dest", "skill-md", "--json"])
        capsys.readouterr()

        assert code_plain == code_json == 0
        assert plain.skill_md.read_text(encoding="utf-8") == as_json.skill_md.read_text(
            encoding="utf-8"
        )
        resolved_plain = plain.home / "skills" / "s" / "resolved" / f"{RID}.md"
        resolved_json = as_json.home / "skills" / "s" / "resolved" / f"{RID}.md"
        assert resolved_plain.is_file() and resolved_json.is_file()
        # routing metadata (destination/variant/routed_at shape) matches
        # byte-for-byte modulo the timestamp field, which genuinely
        # differs between two separate invocations.
        rec_plain = Record.from_path(resolved_plain)
        rec_json = Record.from_path(resolved_json)
        assert rec_plain.routing.get("destination") == rec_json.routing.get("destination")
        assert rec_plain.status == rec_json.status == "routed"


class TestBudgetEnvelopeKey:
    def test_t11_1_envelope_carries_budget_never_over_cap(self, env, capsys):
        """T11.1: `_verb_envelope` has the key `"budget"` and no key
        `"over_cap"` at all (the retired name must not survive as a
        second, redundant key)."""
        seed_skill_record(env)
        code, envelope = run_json(
            ["route", RID, "--dest", "skill-md", "--json"], capsys
        )
        assert code == 0
        assert "budget" in envelope
        assert "over_cap" not in envelope

    def test_t11_3_unreadable_whole_file_still_reports_entry_word_counts(
        self, env
    ):
        """T11.3 (?): the SECTION already compiled successfully (the
        route landed) but a subsequent whole-file read of the target
        fails (permissions changed after the route) — `budget_note()`
        degrades the file-size clause to "surface size unavailable"
        while the entry/word counts, sourced from the already-computed
        `SectionResult`, still render. Real fixture (chmod on the actual
        target), never a hand-constructed `VerbResult`."""
        seed_skill_record(env)
        result = verbs.route(env.home, RID, dest="skill-md")
        assert result.compile_result is not None

        os.chmod(env.skill_md, 0o000)
        try:
            note = result.budget_note()
        finally:
            os.chmod(env.skill_md, 0o644)

        assert note is not None
        assert "surface size unavailable" in note
        assert "entries" in note and "words" in note

    def test_hook_route_stdout_is_json_and_nothing_else(self, env, capsys):
        """§4: a hook route otherwise prints the ENTIRE generated script
        as `diff` — under `--json` that must NOT leak onto stdout beside
        the envelope."""
        trigger = "About to edit `.storage/*.json` while HA is running."
        record = make_behavior(scope="skill:s", record_id=RID, trigger=trigger)
        create_record(env.home, record)
        write_proposal(
            env.home,
            RID,
            proposal_dict(
                destination="hook",
                alternates=["skill-md"],
                **hook_proposal_fields(),
            ),
        )
        stamp_proposal(env.home, RID)
        code, envelope = run_json(["route", RID, "--json"], capsys)
        assert code == 0
        assert envelope["destination"] == "hook"
        assert envelope["outcome_state"] == "landed"
        assert envelope["host_commit_sha"]
        # The mutation this guards (§8): "print anything else to stdout
        # (result.diff, a post_notes line) -> hook-route ... envelope
        # tests [must fail]". `run_json` already raised on a stdout that
        # wasn't pure JSON; reaching here IS the proof.

    def test_new_skill_route_stdout_is_json_and_nothing_else(self, env, capsys):
        marketplace = env.host / ".claude-plugin" / "marketplace.json"
        marketplace.parent.mkdir()
        marketplace.write_text(
            json.dumps(
                {
                    "name": "sandbox-skills",
                    "plugins": [
                        {
                            "name": "s-plugin",
                            "source": "./plugins/s-plugin",
                            "description": "seeded",
                            "version": "1.0.0",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "marketplace seed")
        record = make_behavior(
            scope="skill:s", record_id=RID, trigger="About to flash firmware."
        )
        create_record(env.home, record)
        code, envelope = run_json(
            ["route", RID, "--dest", "new-skill:mouse-firmware", "--json"], capsys
        )
        assert code == 0
        assert envelope["destination"] == "new-skill"
        assert envelope["outcome_state"] == "landed"
        assert envelope["created"] is True  # NewSkillApplyResult.scaffolded
        # Same proof as the hook case: run_json already validated stdout
        # was pure JSON — a leaked "new skill scaffolded..." post_notes
        # line would have broken json.loads above.


class TestDeferEnvelope:
    def test_defer_envelope(self, env, capsys):
        seed_skill_record(env)
        code, envelope = run_json(["defer", RID, "--json"], capsys)
        assert code == 0
        assert envelope["action"] == "defer"
        assert envelope["record_id"] == RID
        assert envelope["canon_path"] is None
        assert envelope["host_commit_sha"] is None
        assert envelope["destination"] is None
        assert envelope["variant"] is None
        assert envelope["deferred_until"]  # a YYYY-MM-DD string
        assert envelope["outcome_state"] == "landed"
        assert envelope["created"] is None
        assert envelope["budget"] is None

    def test_defer_until_explicit_date_rides_the_envelope(self, env, capsys):
        seed_skill_record(env)
        code, envelope = run_json(
            ["defer", RID, "--until", "2027-01-15", "--json"], capsys
        )
        assert code == 0
        assert envelope["deferred_until"] == "2027-01-15"


class TestRejectEnvelope:
    def test_reject_envelope(self, env, capsys):
        seed_skill_record(env)
        code, envelope = run_json(["reject", RID, "--json"], capsys)
        assert code == 0
        assert envelope["action"] == "reject"
        assert envelope["canon_path"] is None
        assert envelope["host_commit_sha"] is None
        assert envelope["destination"] is None
        assert envelope["variant"] is None
        assert envelope["deferred_until"] is None
        assert envelope["outcome_state"] == "landed"
        # §3.2: reject's content is sourced from ledger_paths (the
        # moved-to-resolved/ path) — NEVER canon_path/staged confusion.
        assert envelope["ledger_paths"]
        assert any(str(RID) in p and "resolved" in p for p in envelope["ledger_paths"])


class TestGraduateEnvelope:
    def test_graduate_a_routed_record_lands_a_host_commit(self, env, capsys):
        seed_skill_record(env)
        assert cli.main(["route", RID, "--dest", "skill-md"]) == 0
        capsys.readouterr()
        code, envelope = run_json(["graduate", RID, "--json"], capsys)
        assert code == 0
        assert envelope["action"] == "graduate"
        assert envelope["canon_path"] is None  # §3.2: graduate carries no target
        assert envelope["destination"] is None
        assert envelope["variant"] is None
        assert envelope["host_commit_sha"]
        assert envelope["outcome_state"] == "landed"

    def test_graduate_a_never_routed_pending_record_is_no_op(self, env, capsys):
        """The "bulk-acknowledge door" (verbs.py's graduate docstring):
        a PENDING record that was never routed carries no compile
        result at all — `_retirement_preflight` returns an empty
        `_Retirement()` for `status != "routed"`. Builder's verb-aware
        `outcome_state` split: this must read `no_op`, never `drift` —
        applying route's literal predicate here would tell the user to
        `recompile` canon that was never written in the first place."""
        seed_skill_record(env)
        code, envelope = run_json(["graduate", RID, "--json"], capsys)
        assert code == 0
        assert envelope["host_commit_sha"] is None
        assert envelope["outcome_state"] == "no_op"
        assert envelope["warnings"] == []


# ===================================================================== #
# Destination-shape tests (§5: "plus one per destination shape that
# differs")
# ===================================================================== #


class TestReferenceShape:
    def test_reference_route_envelope(self, env, capsys):
        record = make_knowledge(scope="skill:s", record_id=RID)
        create_record(env.home, record)
        code, envelope = run_json(["route", RID, "--dest", "reference", "--json"], capsys)
        assert code == 0
        assert envelope["destination"] == "reference"
        assert envelope["outcome_state"] == "landed"
        assert envelope["created"] is True  # ReferenceResult.created (fresh LEARNINGS.md)
        # Code-gate finding 1 (BLOCKER): a reference route's
        # TargetSpec.target is `None` by construction (verbs.py's
        # reference branch of _resolve_target never sets one — the
        # references file is discovered per-record at COMPILE time).
        # `_verb_envelope`'s `_canon_path` falls back to
        # `ReferenceResult.path` for exactly this case — canon_path
        # must be the REAL path on a landed success, never `None`
        # (a `None` here rendered as literal "in `None`" on the success
        # leg before the fix).
        assert envelope["canon_path"] is not None
        assert envelope["canon_path"].endswith("LEARNINGS.md")


class TestUserScopeShape:
    def test_user_scope_route_is_wrote_uncommitted(self, env, tmp_path, monkeypatch, capsys):
        """§3.3 state 3: UserScopeResult is keyed EXPLICITLY
        (isinstance check), never inferred — host_commit_sha is always
        None for user scope (host_paths=[] unconditionally, verbs.py
        ~1648), so without the explicit key this would misread as
        drift."""
        bindir = tmp_path / "shim-bin"
        bindir.mkdir()
        fake = bindir / "chezmoi"
        fake.write_text(CHEZMOI_SHIM, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("CHEZMOI_SHIM_LOG", str(tmp_path / "chezmoi.log"))
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")  # UNMANAGED

        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", target)

        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        code, envelope = run_json(["route", RID, "--dest", "claude-md", "--json"], capsys)
        assert code == 0
        assert envelope["destination"] == "claude-md"
        assert envelope["variant"] is None
        assert envelope["host_commit_sha"] is None
        assert envelope["outcome_state"] == "wrote_uncommitted"


class TestClaudeMdLocalShape:
    def test_local_variant_route_is_wrote_uncommitted(self, env, capsys):
        """`claude-md:local` — a PROJECT-scope, gitignored-by-design
        target (verbs.py's `_resolve_local_target`, A2 §6). Keyed by
        `variant == "local"`, the other half of state 3's explicit key —
        nothing else on VerbResult distinguishes it from an ordinary
        managed claude-md route."""
        (env.host / ".gitignore").write_text("CLAUDE.local.md\n", encoding="utf-8")
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "gitignore CLAUDE.local.md")
        record = make_behavior(scope="project", record_id=RID)
        create_record(env.home, record, project_path=env.host)
        code, envelope = run_json(
            ["route", RID, "--dest", "claude-md:local", "--json"], capsys
        )
        assert code == 0
        assert envelope["destination"] == "claude-md"
        assert envelope["variant"] == "local"
        assert envelope["host_commit_sha"] is None
        assert envelope["outcome_state"] == "wrote_uncommitted"
        assert (env.host / "CLAUDE.local.md").is_file()


# ===================================================================== #
# The drift state (§3.3 state 4) — CLI layer, REAL fixture, no
# monkeypatching (§5's own warning: constructing a VerbResult directly
# is the round-1 failure shape).
# ===================================================================== #


class TestDriftStateRealFixture:
    def test_unbalanced_marker_pair_reaches_drift_not_a_refusal(self, env, capsys):
        """A real user reaches this by hand-editing inside the managed
        section. The broken markers must be COMMITTED into the host
        repo first — an UNCOMMITTED edit would make `_abort_if_dirty`
        refuse (exit 1) before the host phase ever runs, never reaching
        `compile_managed_file`'s CompileError at all."""
        env.skill_md.write_text(
            f"# s skill\n\n{BEGIN_MARKER}\n{BEGIN_MARKER}\n{END_MARKER}\n",
            encoding="utf-8",
        )
        commit_all(env.host, "hand-edit: duplicate begin marker")
        git(env.host, "push", "-q")

        seed_skill_record(env)
        code, envelope = run_json(["route", RID, "--dest", "skill-md", "--json"], capsys)

        assert code == 0  # §3.3 state 4: "This state exits 0."
        assert envelope["outcome_state"] == "drift"
        assert envelope["host_commit_sha"] is None
        assert envelope["warnings"], "the H-2 repair instruction must ride the envelope"
        assert any("recompile" in w for w in envelope["warnings"])
        # The target must still be NAMED (as the file to check) even
        # though it was NOT written by this run — DoD #4.
        assert envelope["canon_path"] == str(env.skill_md)


# ===================================================================== #
# The no_op state (§3.3 state 2) — CLI layer, REAL fixture, no
# monkeypatching. Code-gate finding 3 (MAJOR): replacing the whole of
# `_reports_no_change` with `return False` left the CLI suite fully
# green — §8 row 7 had no covering test at any layer.
# ===================================================================== #


class TestNoOpStateRealFixture:
    def test_pre_populated_section_reaches_no_op_not_landed(self, env, capsys):
        """Pre-seed the target with EXACTLY the managed section that
        routing this record would produce — computed via the real
        `compilers.entry_line` (never hand-typed/guessed, so it cannot
        silently drift from the compiler's own format) — so when
        `route` recompiles, the new text is byte-identical to what is
        already on disk and `SectionResult.changed` is False
        (`_host_phase`, verbs.py: `changed is not False` gates the host
        commit, so `host_commit_sha` stays None here too). A real user
        reaches this by hand-writing the section ahead of time, or by a
        prior compile that landed on disk but whose ledger-side commit
        never completed."""
        record = seed_skill_record(env)
        base = "# s skill\n\nAuthored prose stays put."
        section = f"{BEGIN_MARKER}\n{entry_line(record)}\n{END_MARKER}"
        env.skill_md.write_text(f"{base}\n\n{section}\n", encoding="utf-8")
        commit_all(env.host, "pre-write: the exact section route would produce")
        git(env.host, "push", "-q")

        code, envelope = run_json(["route", RID, "--dest", "skill-md", "--json"], capsys)

        assert code == 0
        assert envelope["outcome_state"] == "no_op"
        assert envelope["host_commit_sha"] is None  # nothing to commit
        # Still named — the state-2 render reads this file, per §3.3.
        assert envelope["canon_path"] == str(env.skill_md)
        # The file itself is genuinely untouched (compile_managed_file
        # only writes when result.changed — confirms the fixture reached
        # the no-op branch for the RIGHT reason, not merely that the
        # envelope claims it).
        assert env.skill_md.read_text(encoding="utf-8") == f"{base}\n\n{section}\n"


# ===================================================================== #
# stderr byte-identical under --json (§5)
# ===================================================================== #


class TestStderrByteIdentical:
    def test_stderr_unchanged_with_and_without_json(self, tmp_path, monkeypatch, capsys):
        """§5: `--json` must not touch stderr — `_extract_adopt_path`
        (routes.py) and `_commit_drift_eligible` both key off it. Proven
        by an ACTUAL byte diff between two otherwise-identical runs, not
        by re-asserting "the adopt hint is still there" (advisor
        guidance: the weaker assertion would pass even if warnings moved
        entirely into the envelope, silently killing the adopt offer)."""
        bindir = tmp_path / "shim-bin"
        bindir.mkdir()
        fake = bindir / "chezmoi"
        fake.write_text(CHEZMOI_SHIM, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("CHEZMOI_SHIM_LOG", str(tmp_path / "chezmoi.log"))
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE_RC", "1")  # UNMANAGED -> adopt_hint fires
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))

        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        monkeypatch.setattr(verbs, "DEFAULT_USER_CLAUDE_MD", target)

        plain_env = Env(tmp_path / "plain")
        json_env = Env(tmp_path / "as-json")

        record = make_behavior(scope="user", record_id=RID)
        create_record(plain_env.home, record)
        record2 = make_behavior(scope="user", record_id=RID)
        create_record(json_env.home, record2)

        monkeypatch.setenv("SELF_LEARN_HOME", str(plain_env.home))
        code_plain = cli.main(["route", RID, "--dest", "claude-md:rules:subagents"])
        stderr_plain = capsys.readouterr().err

        monkeypatch.setenv("SELF_LEARN_HOME", str(json_env.home))
        code_json = cli.main(
            ["route", RID, "--dest", "claude-md:rules:subagents", "--json"]
        )
        stderr_json = capsys.readouterr().err

        assert code_plain == code_json == 0
        assert "chezmoi-adopt" in stderr_plain  # the offer fires in the base case
        assert stderr_plain == stderr_json  # byte-identical, per §5
