"""S-NEXT-cures-a -- honest output and attribution (the 2026-10-30
hand-maintenance cures, lane A).

Written by reading, not run: the user's 2026-10-30 rule (tests run only for a
significant change; the orchestrator runs the suite once over the landing).
Each section names the defect it pins and, where it applies, what the test
does on master (a test that stays green on master for a defect it names is
itself a defect).

  M2.1  a hook route's "two manual steps remain" text is false after an
        activation did the steps (batch hook tests carry the batch-level legs);
  M2.2  `outcome_state` reads `landed`, not `drift`, for verbs that never
        attempt a host write;
  M2.3  the selftest's unknown-provenance advice names each target;
  M2.4  a plain `recompile` that changes nothing still records an unrecorded
        region that already equals the ledger's render;
  M5.1  `reroute` carries the runner's `By:`/execution trailers, and crash
        recovery's subject check recognises it;
  M5.2  in an agent shell a ledger-writing verb records `By: agent` and
        refuses to run without a stated reason;
  teach `--statement` (documented by the teach command, missing in the CLI).

Every test models a PERSON's terminal unless it says otherwise: the agent
markers are cleared first (`tests/test_agent_config.py` needs the same).
"""

from __future__ import annotations

import json
import shutil

import pytest

from self_learn import (
    cli,
    compiled,
    execution_evidence,
    refs,
    selfcheck,
    settings,
    statements,
    teach,
    verbs,
)
from self_learn import batch
from self_learn.hosts import host_add
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record
from support import (
    commit_all,
    git,
    make_behavior,
    make_env,
    make_home,
    proposal_dict,
)

from test_statement_roles import transcript
from test_u_verbs import _seed_pending_behavior, _u5_case, env2, seed_routed  # noqa: F401

SNIPPET = (
    '"PreToolUse": [{"matcher": "Edit|Write", "hooks": '
    '[{"type": "command", "command": "/h/hooks/guard.sh"}]}]'
)


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    """A person's terminal: no agent marker, scratch cache, scratch actor."""
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


def _as_agent(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert settings.agent_caller()  # positive control: the shell now reads as an agent's


def _body(home, sha):
    return git(home, "show", "-s", "--format=%B", sha).stdout


def _head(home):
    return git(home, "rev-parse", "HEAD").stdout.strip()


# ------------------------------------------------------------------ M2.1


class TestHookManualStepsText:
    def test_a_human_route_still_prints_both_steps(self):
        """Positive control for every absence assertion below: the text a
        person gets after a plain hook route is unchanged."""
        steps = verbs._hook_manual_steps(SNIPPET, "guard.sh")
        text = "\n".join(steps)
        assert len(steps) == 3
        assert "two manual steps remain" in text
        assert "./install.sh" in text and "~/.claude/hooks/guard.sh" in text
        assert SNIPPET in text

    def test_activation_drops_exactly_the_routes_manual_lines(self):
        steps = verbs._hook_manual_steps(SNIPPET, "guard.sh")
        kept = verbs.without_hook_manual_steps(["preview line", *steps, "other note"])
        assert kept == ["preview line", "other note"]

    def test_the_placed_only_text_says_one_step_and_never_install(self):
        steps = verbs._hook_manual_steps(SNIPPET, "guard.sh", placed=True)
        text = "\n".join(steps)
        assert "one manual step remains" in text
        assert "two manual" not in text and "install.sh" not in text
        assert SNIPPET in text  # the one step still carries its snippet
        # the placed-only text is the delegated receipt's, not the route's:
        # the filter above must not eat it
        assert verbs.without_hook_manual_steps(steps) == steps


# ------------------------------------------------------------------ M2.2


def _result(action, **kw):
    return verbs.VerbResult(
        action=action, record_id="lrn-00000001", commit_message="m",
        commit_sha="abc1234", **kw,
    )


class TestOutcomeState:
    @pytest.mark.parametrize(
        "action",
        [
            "hook-activate", "hook-deactivate", "rehome", "rescope", "undefer",
            "reopen", "note", "reclassify", "revise", "followup-add",
            "followup-done", "confirm-recurrence", "confirm-held",
            "dismiss-suspect", "link-contradicts",
        ],
    )
    def test_ledger_only_verbs_read_landed_not_drift(self, action):
        # on master each of these fell through to route's predicate and read
        # "drift" ("run `recompile`")
        assert cli._outcome_state(_result(action)) == "landed"

    def test_the_route_predicate_is_unchanged(self):
        """Control: a route that has neither a compile result nor a host
        commit is still a failed host phase."""
        assert cli._outcome_state(_result("route")) == "drift"

    def test_a_pending_replace_reads_landed_a_routed_replace_keeps_the_predicate(self):
        assert cli._outcome_state(_result("replace")) == "landed"
        routed = _result("replace", destination="claude-md")
        assert cli._outcome_state(routed) == "drift"  # host write attempted, none seen


# ------------------------------------------------------------- M2.3 / M2.4


def _routed_plain_without_a_record(tmp_path, rid="lrn-0000c0a1"):
    """A plain host whose CLAUDE.md carries self-learn's own region but whose
    compile record is gone: the state every host had before compile records
    existed (verdict `unknown`)."""
    env = make_env(tmp_path)
    plain_host = tmp_path / "cures-plain"
    plain_host.mkdir()
    host_add(env.ledger, plain_host, "project", mode="plain")
    create_record(env.ledger, make_behavior(scope="project", record_id=rid),
                  project_path=plain_host)
    verbs.route(env.ledger, rid, dest="claude-md", no_push=True)
    shutil.rmtree(env.ledger / "compiled")
    return env, plain_host


class TestSelftestAdviceNamesTheTarget:
    def test_unknown_provenance_advice_carries_the_target_path(self, tmp_path):
        env, plain_host = _routed_plain_without_a_record(tmp_path)
        verdict, reason = selfcheck._check_drift(env.ledger)
        assert verdict is selfcheck.Verdict.PASS
        assert "1 target(s) carry self-learn markers with no compile record" in reason
        # `recompile --adopt` takes a TARGET: the bare form failed with
        # "expected one argument"
        assert f"recompile --adopt {plain_host}" in reason
        assert "recompile --adopt`" not in reason


class TestPlainRecompileRecordsAnUnrecordedCurrentRegion:
    def test_a_no_op_recompile_writes_the_missing_record_once(self, tmp_path):
        env, plain_host = _routed_plain_without_a_record(tmp_path)
        target = plain_host / "CLAUDE.md"
        slug = verbs.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        before_bytes = target.read_bytes()
        head = _head(env.ledger)
        # controls: no entry, and the region on disk is self-learn's own text
        assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is None
        assert verbs.BEGIN_MARKER in before_bytes.decode("utf-8")

        verbs.recompile(env.ledger, no_push=True)

        assert target.read_bytes() == before_bytes  # nothing was rewritten
        assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is not None
        assert _head(env.ledger) != head
        subject = git(env.ledger, "log", "-1", "--format=%s").stdout
        assert "recompile resync record" in subject
        verdict, reason = selfcheck._check_drift(env.ledger)
        assert verdict is selfcheck.Verdict.PASS
        assert "no compile record" not in reason and "(clean)" in reason

        # a second plain recompile finds the record and commits nothing
        head = _head(env.ledger)
        verbs.recompile(env.ledger, no_push=True)
        assert _head(env.ledger) == head

    def test_a_hand_edited_unknown_region_is_not_recorded(self, tmp_path):
        """The discriminating half: self-learn must not bless bytes it did not
        write (H-3). The refusal path is unchanged, and nothing is recorded."""
        env, plain_host = _routed_plain_without_a_record(tmp_path, rid="lrn-0000c0a2")
        target = plain_host / "CLAUDE.md"
        text = target.read_text(encoding="utf-8")
        assert verbs.BEGIN_MARKER in text
        target.write_text(
            text.replace(verbs.BEGIN_MARKER, verbs.BEGIN_MARKER + "\nHAND-EDITED LINE\n"),
            encoding="utf-8",
        )
        slug = verbs.host_slug(env.ledger, plain_host, scope_kind="project")
        key = compiled.region_key(plain_host, target)
        head = _head(env.ledger)

        result = verbs.recompile(env.ledger, no_push=True)

        assert "HAND-EDITED LINE" in target.read_text(encoding="utf-8")
        assert compiled.entry_for(compiled.load_record(env.ledger, slug), key) is None
        assert _head(env.ledger) == head
        assert any(e.skipped for e in result.entries)  # positive control: it refused


# ------------------------------------------------------------------ M5.1


class TestRerouteAttribution:
    def test_a_sheet_runners_execution_trailers_ride_the_reroute_commit(self, env2):
        rid = seed_routed(env2.home)  # routed to skill-md
        ref = execution_evidence.ExecutionRef(
            run_id="run-cures-a", case_id="case-0000c0a1", sheet_sha="12ab34cd",
            sheet_digest="a" * 64, item=1, record_id=rid, verb="route", actor="steward",
        )
        result = verbs.reroute(
            env2.home, rid, dest="claude-md", by="steward", note="moved", no_push=True,
            execution=ref,
        )
        body = _body(env2.home, result.commit_sha)
        assert body.startswith("moved")
        # on master the body was just the note: no `By:`, `Case:`, `Sheet:`, `Item:`
        assert execution_evidence.parse_trailers(body) == ref.trailer_identity()
        # crash recovery proves a mutation by its trailers AND a subject the
        # verb can write: a `route` item run as a reroute must be recognised
        assert execution_evidence.find_mutation_commit(env2.home, ref) == result.commit_sha

    def test_the_subject_check_accepts_a_reroute_only_for_a_route_item(self):
        rid = "lrn-0000c0a1"

        def ref(verb):
            return execution_evidence.ExecutionRef(
                run_id="run-cures-a", case_id="case-0000c0a1", sheet_sha="12ab34cd",
                sheet_digest="a" * 64, item=1, record_id=rid, verb=verb, actor="steward",
            )

        subject = f"self-learn: reroute {rid} → claude-md"
        assert execution_evidence._subject_matches(ref("route"), subject)
        assert not execution_evidence._subject_matches(ref("reject"), subject)
        # and a neighbouring record's reroute is not this one's
        other = "self-learn: reroute lrn-0000c0a2 → claude-md"
        assert not execution_evidence._subject_matches(ref("route"), other)

    def test_by_names_who_chose_the_destination_and_never_becomes_the_trailer(self, env2):
        """`by` on a reroute is the ROUTING field, as on `route`: the review
        UI's Re-route click sends `--by analyst` for a destination the person
        did not cycle. It must not be written as the commit's `By:` (that
        would credit the analyst for a person's click, and an agent shell that
        passes `--by` would not be stamped as an agent)."""
        rid = seed_routed(env2.home)
        result = verbs.reroute(
            env2.home, rid, dest="claude-md", by="analyst", note="why", no_push=True
        )
        assert "By:" not in _body(env2.home, result.commit_sha)
        # positive control: `by` did reach the routing block it is meant for
        record = Record.from_path(next(env2.home.glob(f"skills/a/resolved/{rid}.md")))
        assert record.routing["by"] == "analyst"

    def test_stamp_by_is_the_trailer_and_by_is_left_alone(self, env2):
        rid = seed_routed(env2.home)
        stamped = verbs.reroute(
            env2.home, rid, dest="claude-md", by="analyst", note="why", no_push=True,
            stamp_by="agent",
        )
        assert _body(env2.home, stamped.commit_sha).rstrip().endswith("By: agent")
        record = Record.from_path(next(env2.home.glob(f"skills/a/resolved/{rid}.md")))
        assert record.routing["by"] == "analyst"  # who chose it, unchanged
        rid2 = seed_routed(env2.home, rid="lrn-0000aaab")
        bare = verbs.reroute(env2.home, rid2, dest="claude-md", note="why", no_push=True)
        assert "By:" not in _body(env2.home, bare.commit_sha)
        rid3 = seed_routed(env2.home, rid="lrn-0000aaac")
        head = _head(env2.home)
        with pytest.raises(verbs.VerbError, match="by must be one of"):
            verbs.reroute(env2.home, rid3, dest="claude-md", no_push=True, stamp_by="nobody")
        assert _head(env2.home) == head

    def test_the_batch_dispatch_hands_the_runners_execution_to_the_verb(self, env2, tmp_path):
        """The wiring the verb-level test above cannot see: a steward's route
        line over a routed lesson under a reconsider case goes through
        `batch._dispatch` -> `_dispatch_reroute` -> `verbs.reroute`. Dropping
        `execution=` at either hop leaves the verb test green and the
        commit without its trailers."""
        rid = seed_routed(env2.home, "lrn-0000c0c1")
        old_case = _u5_case(tmp_path, env2.home, records=[rid], kind="resolution", outcome="route")
        case = _u5_case(
            tmp_path, env2.home, records=[rid], kind="reconsider", outcome="route",
            supersedes=old_case,
        )
        ref = execution_evidence.ExecutionRef(
            run_id="run-cures-a", case_id=case, sheet_sha="12ab34cd",
            sheet_digest="a" * 64, item=1, record_id=rid, verb="route", actor="steward",
        )
        item = batch.SheetItem(n=1, id=rid, verb="route", fields={"dest": "claude-md"})
        result = batch._dispatch(
            env2.home, item, case=case, actor="steward", hook_activation=False,
            execution=ref,
        )
        assert result.state == "applied", result.detail  # positive control: it rerouted
        assert "reroute" in git(env2.home, "log", "-1", "--format=%s").stdout
        body = git(env2.home, "log", "-1", "--format=%B").stdout
        assert execution_evidence.parse_trailers(body) == ref.trailer_identity()

    def test_a_bad_by_refuses_before_any_write(self, env2):
        rid = seed_routed(env2.home)
        head = _head(env2.home)
        with pytest.raises(verbs.VerbError, match="by must be one of"):
            verbs.reroute(env2.home, rid, dest="claude-md", by="nobody", no_push=True)
        assert _head(env2.home) == head


# ------------------------------------------------------------------ M5.2


def _seed_pending(home, rid="lrn-0000c0b1"):
    create_record(home, make_behavior(scope="skill:s", record_id=rid))
    commit_all(home, "pending")
    return rid


class TestAgentShellAttribution:
    def test_an_agent_shell_verb_without_a_note_is_refused_before_any_write(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        rid = _seed_pending(home)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _as_agent(monkeypatch)
        head = _head(home)
        capsys.readouterr()
        assert cli.main(["reject", rid]) == cli.EXIT_USAGE
        err = capsys.readouterr().err
        assert "needs --note" in err and "By: agent" in err
        assert "CLAUDECODE" in err  # names the marker it saw, never a value
        assert _head(home) == head
        assert list(home.glob(f"skills/s/pending/{rid}.md"))  # untouched

    @pytest.mark.parametrize(
        "argv",
        [
            ["reject", "lrn-0000c0b1"],
            ["defer", "lrn-0000c0b1"],
            ["undefer", "lrn-0000c0b1"],
            ["retire", "lrn-0000c0b1", "--covered-by", "claude-md:CLAUDE.md"],
            ["rehome", "lrn-0000c0b1", "--to", "user"],
            ["confirm-held", "lrn-0000c0b1"],
            ["supersede", "lrn-0000c0b1", "lrn-0000c0b2"],
            ["link", "contradicts", "lrn-0000c0b1", "lrn-0000c0b2"],
            ["followup", "done", "lrn-0000c0b1"],
        ],
        ids=lambda argv: " ".join(argv[:2]),
    )
    def test_every_resolution_surface_asks_for_a_reason(
        self, argv, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        capsys.readouterr()
        cli.main(argv)  # a person: whatever it answers, it is not this refusal
        assert "needs --note" not in capsys.readouterr().err
        _as_agent(monkeypatch)
        assert cli.main(argv) == cli.EXIT_USAGE
        assert "needs --note" in capsys.readouterr().err

    def test_an_agent_shell_verb_with_a_note_records_by_agent(
        self, tmp_path, monkeypatch
    ):
        home = make_home(tmp_path)
        rid = _seed_pending(home)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _as_agent(monkeypatch)
        assert cli.main(["reject", rid, "--note", "the user said it was wrong"]) == 0
        body = git(home, "log", "-1", "--format=%B").stdout
        assert "the user said it was wrong" in body
        assert body.rstrip().endswith("By: agent")
        assert list(home.glob(f"skills/s/resolved/{rid}.md"))

    def test_a_persons_terminal_is_unchanged(self, tmp_path, monkeypatch):
        home = make_home(tmp_path)
        rid = _seed_pending(home)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        assert not settings.agent_caller()
        assert cli.main(["reject", rid]) == 0  # no --note needed
        assert "By:" not in git(home, "log", "-1", "--format=%B").stdout

    def test_a_verb_whose_own_text_is_the_reason_needs_no_extra_note(
        self, tmp_path, monkeypatch
    ):
        """`note --append TEXT` is itself the stated reason, and the commit
        records who ran it."""
        home = make_home(tmp_path)
        rid = _seed_pending(home)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        _as_agent(monkeypatch)
        assert cli.main(["note", rid, "--append", "seen again on the 29th"]) == 0
        assert git(home, "log", "-1", "--format=%B").stdout.rstrip().endswith("By: agent")

    def test_an_agent_shell_route_and_reroute_are_stamped(self, env2, monkeypatch):
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        _as_agent(monkeypatch)
        assert cli.main(["route", rid, "--dest", "skill-md", "--note", "approved"]) == 0
        route_body = git(
            env2.home, "log", "-1", "--grep=self-learn: route", "--format=%B"
        ).stdout
        assert route_body.rstrip().endswith("By: agent")
        record = Record.from_path(next(env2.home.glob(f"skills/a/resolved/{rid}.md")))
        assert record.routing["by"] == "agent"  # the default for an agent shell

        assert cli.main(["reroute", rid, "--dest", "claude-md", "--note", "moved"]) == 0
        reroute_body = git(
            env2.home, "log", "-1", "--grep=self-learn: reroute", "--format=%B"
        ).stdout
        assert "moved" in reroute_body and reroute_body.rstrip().endswith("By: agent")

    def test_route_stamps_the_runner_apart_from_who_chose_the_destination(self, env2):
        """`by` on a route is who CHOSE the destination (the review UI sends
        `analyst` while a person clicks approve); `stamp_by` is who ran it.
        Passing only `by` leaves the body alone, as before."""
        rid = "lrn-0000aaaa"
        create_record(env2.home, make_behavior(record_id=rid, scope="skill:a"))
        write_proposal(env2.home, rid, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending")
        result = verbs.route(env2.home, rid, dest="skill-md", by="analyst", no_push=True)
        assert "By:" not in _body(env2.home, result.commit_sha)
        rid2 = "lrn-0000aaab"
        create_record(env2.home, make_behavior(record_id=rid2, scope="skill:a"))
        write_proposal(env2.home, rid2, proposal_dict(scope="skill:a"))
        commit_all(env2.home, "pending2")
        stamped = verbs.route(
            env2.home, rid2, dest="skill-md", by="analyst", no_push=True, stamp_by="agent"
        )
        assert _body(env2.home, stamped.commit_sha).rstrip().endswith("By: agent")
        with pytest.raises(verbs.VerbError, match="by must be one of"):
            verbs.route(env2.home, rid2, dest="skill-md", no_push=True, stamp_by="nobody")


    def test_revise_stamps_the_runner_apart_from_the_proposals_revised_by(self, env2):
        """`revise`'s `by` rides the proposal's `revised_by`; the trailer is
        `stamp_by`, so naming a reviser never changes who ran the verb."""
        rid = _seed_pending_behavior(env2, rid="lrn-0000c0d1")
        plain = verbs.revise(
            env2.home, rid, section="Trigger", text="Reworded once.", because="b",
            by="analyst", no_push=True,
        )
        assert "By:" not in git(env2.home, "log", "-1", "--format=%B").stdout
        assert plain.action == "revise"  # positive control: the revise landed
        verbs.revise(
            env2.home, rid, section="Trigger", text="Reworded twice.", because="b",
            by="analyst", no_push=True, stamp_by="agent",
        )
        assert git(env2.home, "log", "-1", "--format=%B").stdout.rstrip().endswith("By: agent")


# ---------------------------------------------------------- teach --statement


def _teach(home, monkeypatch, *argv):
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    return cli.main(["teach", "--user", "--type", "knowledge", "--fact",
                     "Smaller changes land faster.", *argv])


class TestTeachStatement:
    def test_the_words_are_cited_from_the_row_the_user_typed(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        transcript(home, tmp_path)
        capsys.readouterr()
        rc = _teach(home, monkeypatch, "--session", "synthetic-stmt",
                    "--statement", "Keep it small.")
        assert rc == 0, capsys.readouterr().err
        rows = statements.list_statements(home)
        assert len(rows) == 1
        assert rows[0]["verbatim"] == "Keep it small."
        assert rows[0]["recorded_by"] == "human"
        assert rows[0]["source"]["message_ref"] == "transcript:synthetic-stmt#L1"
        assert list(home.glob("user/pending/lrn-*.md"))  # and the lesson landed

    @pytest.mark.parametrize(
        "words", ["Build this.", "words nobody said"],
        ids=["only-an-agent-row-holds-them", "no-row-holds-them"],
    )
    def test_words_no_user_row_holds_refuse_the_whole_command(
        self, words, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        transcript(home, tmp_path)
        # positive control: the transcript resolves and a user row is found
        assert statements.user_message_ref(home, "synthetic-stmt", "Keep it small.") == (
            "transcript:synthetic-stmt#L1"
        )
        head = _head(home)
        capsys.readouterr()
        rc = _teach(home, monkeypatch, "--session", "synthetic-stmt", "--statement", words)
        assert rc == cli.EXIT_USAGE
        assert "statement" in capsys.readouterr().err
        assert _head(home) == head  # nothing was written, lesson included
        assert statements.list_statements(home) == []
        assert not list(home.glob("user/pending/lrn-*.md"))

    def test_statement_needs_a_session(self, tmp_path, monkeypatch, capsys):
        home = make_home(tmp_path)
        capsys.readouterr()
        rc = _teach(home, monkeypatch, "--statement", "Keep it small.")
        assert rc == cli.EXIT_USAGE
        assert "--statement needs --session" in capsys.readouterr().err

    def test_a_lesson_that_does_not_land_records_no_statement(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        transcript(home, tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        capsys.readouterr()
        rc = cli.main(["teach", "--user", "--session", "synthetic-stmt",
                       "--statement", "Keep it small."])  # no lesson text at all
        assert rc == cli.EXIT_USAGE
        assert statements.list_statements(home) == []

    def test_the_latest_matching_row_wins(self, tmp_path):
        home = make_home(tmp_path)
        _, root = transcript(home, tmp_path)
        path = root / "project" / "synthetic-stmt.jsonl"
        with path.open("a") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "Keep it small."}}) + "\n")
        assert statements.user_message_ref(home, "synthetic-stmt", "Keep it small.") == (
            "transcript:synthetic-stmt#L7"
        )
        assert refs.resolve("synthetic-stmt", line=7, roots=[root]).role == "user"


class TestTeachStatementFollowUps:
    """What `--statement` does around the lesson (fix round 1)."""

    def test_the_precheck_uses_the_write_time_check_and_falls_back_to_an_earlier_row(
        self, tmp_path, monkeypatch
    ):
        """The raw role is a prefilter only: each candidate row, latest first,
        goes through `statements._check_evidence` (what `add` runs at write
        time). A latest row `add` would refuse must not be cited while an
        earlier valid one exists, and must not let the lesson land only to
        have its statement refused."""
        home = make_home(tmp_path)
        _, root = transcript(home, tmp_path)
        path = root / "project" / "synthetic-stmt.jsonl"
        with path.open("a") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "Keep it small."}}) + "\n")
        assert statements.user_message_ref(home, "synthetic-stmt", "Keep it small.") == (
            "transcript:synthetic-stmt#L7"
        )  # positive control: with nothing refusing, the latest wins
        real = statements._check_evidence

        def refuse_line_7(home_, ref, verbatim, **kw):
            if ref.endswith("#L7"):
                raise statements.StatementUsageError("statement add: refused for this test")
            return real(home_, ref, verbatim, **kw)

        monkeypatch.setattr(statements, "_check_evidence", refuse_line_7)
        assert statements.user_message_ref(home, "synthetic-stmt", "Keep it small.") == (
            "transcript:synthetic-stmt#L1"
        )

        def refuse_all(home_, ref, verbatim, **kw):
            raise statements.StatementUsageError("statement add: refused for this test")

        monkeypatch.setattr(statements, "_check_evidence", refuse_all)
        with pytest.raises(statements.StatementUsageError, match="refused for this test"):
            statements.user_message_ref(home, "synthetic-stmt", "Keep it small.")

    def test_exit_4_means_the_lesson_was_captured_so_the_statement_is_recorded(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        transcript(home, tmp_path)
        monkeypatch.setattr(teach, "_run_teach_lesson", lambda args: teach.EXIT_ANALYST)
        monkeypatch.setattr(cli, "_kick_after_capture", lambda **kw: None)
        capsys.readouterr()
        rc = _teach(home, monkeypatch, "--session", "synthetic-stmt",
                    "--statement", "Keep it small.")
        assert rc == teach.EXIT_ANALYST
        assert "did not land" not in capsys.readouterr().err
        assert [r["verbatim"] for r in statements.list_statements(home)] == ["Keep it small."]

    def test_a_lesson_that_failed_outright_records_no_statement(
        self, tmp_path, monkeypatch, capsys
    ):
        home = make_home(tmp_path)
        transcript(home, tmp_path)
        monkeypatch.setattr(teach, "_run_teach_lesson", lambda args: teach.EXIT_GIT_FAILED)
        monkeypatch.setattr(cli, "_kick_after_capture", lambda **kw: None)
        capsys.readouterr()
        rc = _teach(home, monkeypatch, "--session", "synthetic-stmt",
                    "--statement", "Keep it small.")
        assert rc == teach.EXIT_GIT_FAILED
        assert "did not land" in capsys.readouterr().err
        assert statements.list_statements(home) == []

    def test_a_statement_failure_after_the_lesson_landed_keeps_the_lessons_exit_code(
        self, tmp_path, monkeypatch, capsys
    ):
        """A non-zero exit here would skip the worker kick and invite a second
        `teach` (a duplicate lesson); the failure is printed with the command
        that retries only the statement."""
        home = make_home(tmp_path)
        transcript(home, tmp_path)
        kicked: list[bool] = []
        monkeypatch.setattr(cli, "_kick_after_capture", lambda **kw: kicked.append(True))

        def boom(*a, **kw):
            raise statements.StatementUsageError("statement add: boom")

        monkeypatch.setattr(statements, "add", boom)
        capsys.readouterr()
        rc = _teach(home, monkeypatch, "--session", "synthetic-stmt",
                    "--statement", "Keep it small.")
        err = capsys.readouterr().err
        assert list(home.glob("user/pending/lrn-*.md"))  # positive control: the lesson landed
        assert rc == 0 and kicked == [True]
        assert "--statement failed" in err and "boom" in err
        assert "Do not run teach again" in err
        assert "statement add --verbatim 'Keep it small.'" in err
        assert "--ref transcript:synthetic-stmt#L1 --recorded-by human" in err
