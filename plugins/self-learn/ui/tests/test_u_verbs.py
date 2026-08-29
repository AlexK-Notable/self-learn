"""U-verbs Phase 1 (T2) -- the unit's own UI-side test file (spec S7).

MOVE9 is the ONLY Phase-1 [A] criterion that touches the UI package
(UIP1-5 are Phase 2, out of scope for this build). Leg (b) -- a
user/skill-scoped record CAN now be proposed to a registered project
target -- already has its own test in test_proposals.py
(TestValidateRehome::test_non_project_source_now_succeeds, the rewrite
of the pre-existing test_non_project_record_refuses this build made).
This file adds the other two legs named by MOVE9's check column, plus a
positive-control leg proving leg (b)'s pre-state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn_ui.proposals import VerbProposal, validate_proposal

from support import make_behavior, seed_record

from test_proposals import _record_scope, _seed_two_projects


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
