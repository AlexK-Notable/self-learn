"""U-verbs (T2) -- the unit's own UI-side test file (spec S7).

Phase 1 landed MOVE9, the only Phase-1 [A] criterion touching the UI
package. This build (Phase 2) adds UIP1-5, all five [B] criteria naming
the UI package -- G10 parity/exhaustiveness (UIP1), build_argv's argv
round-trip through the real CLI parser (UIP2), the holding/resolved
card's two new buttons (UIP3), the keymap's free-letter ledger (UIP4),
and the bucket-staleness notice generalized past project-to-project
(UIP5). MOVE9's own tests are unchanged below -- leg (b) -- a
user/skill-scoped record CAN now be proposed to a registered project
target -- already has its own test in test_proposals.py
(TestValidateRehome::test_non_project_source_now_succeeds, the rewrite
of the pre-existing test_non_project_record_refuses this build made).
This file adds the other two legs named by MOVE9's check column, plus a
positive-control leg proving leg (b)'s pre-state.
"""

from __future__ import annotations

import string
from pathlib import Path

import pytest

from self_learn import cli, verbs
from self_learn.hosts import slug_for
from self_learn_ui import routes
from self_learn_ui.keymap import KEYMAP
from self_learn_ui.proposals import VerbProposal, validate_proposal
from self_learn_ui.routes import NOTICE_PROPOSAL_MOVED, build_argv

from support import make_behavior, resolve_record_directly, seed_record

from test_proposals import _record_scope, _seed_two_projects
from test_proposals import make_client as make_client_with_pane
from test_routes import make_client


class TestMove9ProposalIntake:
    def test_proposal_to_refuses_scope_literals(self, tmp_path: Path) -> None:
        """MOVE9 leg (a) (code gate r1, MAJ-4): the rehome branch still
        refuses `to: user` and `to: skill:<name>` -- but §4.1 is explicit
        this is its OWN literal-arm refusal, not the generic
        not-a-registered-project message a project-scoped record also
        gets: a scope change is a human decision, and the agent is told
        to say it in `rationale` and let the human type it. The old
        assertion here ("not a registered project") discriminated
        NOTHING this unit changed -- pre-change code emitted that same
        generic string for a project-scoped `to` too."""
        sb, host_b, rec = _seed_two_projects(tmp_path)
        for literal in ("user", "skill:s"):
            result = validate_proposal(
                sb.ledger,
                _record_scope(rec),
                {"verb": "rehome", "record_id": rec.id, "to": literal},
            )
            assert isinstance(result, str), literal
            assert "a scope change is a human verb" in result, literal
            assert "rationale" in result, literal

    def test_proposal_unregistered_and_same_bucket_refusals_unchanged(self, tmp_path: Path) -> None:
        """MOVE9 leg (c): the unregistered-target and same-bucket
        refusals are byte-unchanged by this build."""
        sb, host_b, rec = _seed_two_projects(tmp_path)
        stranger = tmp_path / "repos" / "stranger"
        result = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "rehome", "record_id": rec.id, "to": str(stranger)},
        )
        assert isinstance(result, str)
        assert "not a registered project" in result
        assert "Register control" in result
        assert "self-learn host add <path>" in result

        result2 = validate_proposal(
            sb.ledger,
            _record_scope(rec),
            {"verb": "rehome", "record_id": rec.id, "to": str(sb.host)},
        )
        assert isinstance(result2, str)
        assert "nothing to move" in result2

    def test_proposal_accepts_user_scoped_record_for_project_target(self, tmp_path: Path) -> None:
        """MOVE9 leg (b), restated in this file (the fuller assertion
        lives in test_proposals.py's TestValidateRehome, the declared
        rewrite of its pre-existing project-only-source test): a
        USER-scoped pending record can now be proposed to a registered
        project target -- the source-scope refusal that used to sit at
        proposals.py's rehome branch is gone; the verb's own
        `require_status` is the one guard left."""
        sb, host_b, _ = _seed_two_projects(tmp_path)
        user_rec = make_behavior(scope="user")
        seed_record(sb.ledger, user_rec)
        result = validate_proposal(
            sb.ledger,
            _record_scope(user_rec),
            {"verb": "rehome", "record_id": user_rec.id, "to": str(host_b)},
        )
        assert isinstance(result, VerbProposal)
        assert result.verb == "rehome"
        assert result.to == str(host_b)


# --------------------------------------------------------------- UIP1


class TestUIP1Parity:
    """UIP1: UI_PARITY_VERBS (normative, 17 names) is asserted two
    ways -- parity against _KNOWN_VERBS (leg a) and exhaustiveness
    against the real closed set cli.VERB_COMMANDS (leg b), never a
    positional-name heuristic (r2's form swept in proposal validate /
    host commit-drift and missed supersede entirely -- M-3)."""

    def test_ui_knows_every_record_verb(self) -> None:
        # leg (a): every normative verb the UI is supposed to know about
        # is actually a KNOWN verb the action-bar routes will accept.
        assert routes.UI_PARITY_VERBS <= routes._KNOWN_VERBS

        # leg (b): the normative set is EXACTLY derivable from the real
        # closed set VERB_COMMANDS (cli.py's own dispatch table) plus the
        # two pre-existing non-VERB_COMMANDS verbs (link-contradicts,
        # followup-done) and this unit's followup-add (a "followup"
        # subcommand, never a VERB_COMMANDS member -- same shape as
        # followup-done) -- minus rehome (09 S11 Y-18 decision 3: no
        # human-side control, proposal-bar label only).
        derived = (
            set(cli.VERB_COMMANDS)
            | {"link-contradicts", "followup-done", "followup-add"}
        ) - {"rehome"}
        assert derived == routes.UI_PARITY_VERBS
        assert len(routes.UI_PARITY_VERBS) == 17


# --------------------------------------------------------------- UIP2


class TestUIP2BuildArgvRoundTrip:
    """UIP2: build_argv emits the exact argv cli.py's parser
    accepts, for every verb this unit newly wired into build_argv --
    the G10 four, this unit's Phase-1 additions, and its Phase-2
    additions -- proved by parsing the produced argv through the REAL
    parser (cli._build_parser()), never by re-deriving the shape
    here. M59's danger zone (appending --json at the shared
    --note/--no-push tail) is exercised by reroute, the one verb
    below that both takes --json and runs through that shared tail."""

    def test_build_argv_round_trips(self) -> None:
        parser = cli._build_parser()
        cases: list[tuple[list[str], dict[str, object]]] = [
            (
                build_argv("dismiss-suspect", "lrn-x", event="ev1", why="unrelated"),
                {"command": "dismiss-suspect", "id": "lrn-x", "event": "ev1", "why": "unrelated"},
            ),
            (
                build_argv("rescope", "lrn-x", to="user"),
                {"command": "rescope", "id": "lrn-x", "to": "user"},
            ),
            (
                build_argv("supersede", "lrn-x", target="lrn-y"),
                {"command": "supersede", "old_id": "lrn-x", "new_id": "lrn-y"},
            ),
            (
                build_argv("confirm-held", "lrn-x"),
                {"command": "confirm-held", "id": "lrn-x"},
            ),
            (
                build_argv("undefer", "lrn-x"),
                {"command": "undefer", "id": "lrn-x"},
            ),
            (
                build_argv("reopen", "lrn-x"),
                {"command": "reopen", "id": "lrn-x"},
            ),
            (
                build_argv("note", "lrn-x", note="hello", no_push=True),
                {"command": "note", "id": "lrn-x", "append": "hello", "no_push": True},
            ),
            (
                build_argv("reroute", "lrn-x", dest="reference", by="human", as_json=True, note="why"),
                {
                    "command": "reroute", "id": "lrn-x", "dest": "reference", "by": "human",
                    "as_json": True, "note": "why",
                },
            ),
            (
                build_argv("followup-add", "lrn-x", action="upgrade", unblocks_on="M3"),
                {
                    "command": "followup", "followup_command": "add", "id": "lrn-x",
                    "action": "upgrade", "unblocks_on": "M3",
                },
            ),
            (
                build_argv("reclassify", "lrn-x", kind="surface-rule", record_type="behavior"),
                {"command": "reclassify", "id": "lrn-x", "kind": "surface-rule", "type": "behavior"},
            ),
        ]
        for argv, expected in cases:
            ns = parser.parse_args(argv)
            for field, value in expected.items():
                assert getattr(ns, field) == value, (argv, field, getattr(ns, field, "<absent>"))


# --------------------------------------------------------------- UIP3


class TestUIP3ActionBarButtons:
    """UIP3: the holding card renders Dismiss (k) (arms
    dismiss-suspect with the card's event nonce) and the resolved
    card renders Still holding (m) (arms confirm-held). Both are
    read straight off the real GET-rendered page -- / for holding
    (per this file's own ledger.report monkeypatch pattern, matching
    test_routes.py::test_holding_section_heading_is_defined -- the
    FakeRunner carries no page reads), /record/<id> for resolved."""

    def test_holding_card_offers_dismiss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from self_learn_ui import ledger as ledger_mod
        from self_learn_ui.models import CliRead

        sb = make_behavior_env(tmp_path)
        report_data = {
            "recurrence_suspects": [
                {
                    "id": "lrn-aaaaaaa1",
                    "nonce": "n1",
                    "seen_at": "2026-08-01T00:00:00Z",
                    "basis": "fire-violated",
                }
            ],
            "routed_live": [{"id": "lrn-aaaaaaa1", "bucket": "s", "routed_days_ago": 3}],
        }
        monkeypatch.setattr(ledger_mod, "report", lambda home, **kw: CliRead(data=report_data))
        c, _runner = make_client(sb)
        r = c.get("/")
        assert "Is it holding?" in r.text  # positive control -- the card renders at all
        assert "Dismiss (k)" in r.text
        assert "hx-vals='{\"verb\":\"dismiss-suspect\",\"kind\":\"holding\"}'" in r.text
        # the shared event hidden field the dismiss button relies on
        # (same nonce confirm-recurrence/graduate already reuse).
        assert "<input type=\"hidden\" name=\"event\" value=\"n1\">" in r.text

    def test_resolved_card_offers_confirm_held(self, tmp_path: Path) -> None:
        from support import make_env

        sb = make_env(tmp_path)
        rec = make_behavior(scope="skill:s")
        seed_record(sb.ledger, rec)
        resolve_record_directly(sb.ledger, sb.ledger / "skills" / "s", rec)
        c, _runner = make_client(sb)
        r = c.get(f"/record/{rec.id}", follow_redirects=False)
        assert r.status_code == 200
        assert "data-page=\"resolved\"" in r.text  # positive control -- the resolved view rendered
        assert "Still holding (m)" in r.text
        assert "hx-vals='{\"verb\":\"confirm-held\",\"kind\":\"resolved\"}'" in r.text


def make_behavior_env(tmp_path: Path):
    """A plain make_env() -- named to keep TestUIP3's call sites
    self-documenting next to test_routes.py's own sb = make_env(...)
    idiom without a second top-level import at module scope."""
    from support import make_env

    return make_env(tmp_path)


# --------------------------------------------------------------- UIP4


def test_free_keys_remaining() -> None:
    """UIP4: l and z stay free (FW-136) after this unit spends k
    and m of the four-letter free pool (hklmz, measured S2.8) --
    computed from the LIVE table, never hand-listed, so a future bind
    (e.g. M61's mutant: l -> reroute) is caught here rather than by
    inspection."""
    used = {key for entry in KEYMAP for key in entry.keys if len(key) == 1}
    free = set(string.ascii_lowercase) - used
    assert {"l", "z"} <= free


# --------------------------------------------------------------- UIP5


class TestUIP5NoticeGeneralizedPastProjectLegs:
    """UIP5: NOTICE_PROPOSAL_MOVED fires for EVERY new move leg, not
    only project-to-project (test_proposals.py's own
    TestBucketStalenessLeg only ever exercises a raw-rename
    project-to-project move). This leg drives a REAL rehome --to user
    through the verb layer -- a project-to-USER move, whose target is
    not even a project bucket -- and the discriminator M62 names
    directly: a mutant keying the notice on "target is a project
    bucket" would leave a stale waiting bar here instead of clearing
    it, since the new bucket is user, not a project."""

    def test_proposal_moved_notice_all_legs(self, tmp_path: Path) -> None:
        sb, _host_b, rec = _seed_two_projects(tmp_path)
        c, runner, manager = make_client_with_pane(sb)
        prop = VerbProposal(
            verb="reject",
            record_id=rec.id,
            bucket_scope="project",
            bucket_name=slug_for(sb.host),
            session_key=rec.id,
        )
        assert manager.proposal_slot.occupy(prop)

        verbs.rehome(sb.ledger, rec.id, to="user", no_push=True)

        out = c.post(
            "/proposal/arm",
            data={"record_id": rec.id, "kind": "detail", "nonce": prop.nonce},
            headers={"HX-Request": "true"},
        ).text
        assert NOTICE_PROPOSAL_MOVED in out
        assert manager.proposal_slot.current is None
        assert 'data-armed="true"' not in out
        assert 'data-proposal="waiting"' not in out
        assert runner.calls == []
