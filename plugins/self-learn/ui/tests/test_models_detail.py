"""Pure model tests: build_detail_model. Records are built via
self_learn.records.Record.create (a pure in-memory constructor — no I/O),
everything else is hand-constructed dicts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from self_learn.records import Record
from self_learn_ui.models import (
    HOOK_VERBATIM_CAPTION,
    NO_ANALYSIS_MESSAGE,
    PARAMETER_FREE_DESTINATIONS,
    PREVIEW_HONESTY_CAPTION,
    build_detail_model,
)

NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)

REGISTRY = [
    {"key": "headline", "label": "What this is about", "order": 10, "required": "always"},
    {"key": "impact", "label": "What changes if you keep it", "order": 30, "required": "routing"},
]


def _record(**overrides) -> Record:
    kwargs: dict[str, Any] = dict(
        type="behavior",
        scope="skill:s",
        source="teach",
        kind="anti-pattern",
        trigger="About to edit .storage while HA is running.",
        instruction="Stop the container first.",
        record_id="lrn-aa000001",
        created_at="2026-07-01T00:00:00Z",
    )
    kwargs.update(overrides)
    return Record.create(**kwargs)


def _item(**overrides):
    base = {
        "id": "lrn-aa000001",
        "type": "behavior",
        "scope": "skill:s",
        "status": "pending",
        "created_at": "2026-07-01T00:00:00Z",
        "age_days": 16,
        "deferred_until": None,
        "sightings": 1,
        "has_proposal": False,
        "title": "Stop the container first.",
        "proposal_fresh": False,
        "destination": None,
        "already_canon": False,
        "bucket": "s",
        "host_registered": True,
        "source": "teach",
    }
    base.update(overrides)
    return base


def _build(item, proposal=None, diff_text=None, proposal_raw_text=None, **kw):
    kwargs: dict[str, Any] = dict(
        bucket="s", scope="skill", host_registered=True, host_add_command=None, now=NOW
    )
    kwargs.update(kw)
    return build_detail_model(
        item, _record(), proposal, diff_text, proposal_raw_text, REGISTRY, **kwargs
    )


class TestIdentity:
    def test_basic_fields(self):
        model = _build(_item())
        assert model.id == "lrn-aa000001"
        assert model.bucket == "s"
        assert model.scope == "skill"
        assert model.status == "pending"


class TestCardSections:
    def test_cards_render_from_proposal(self):
        proposal = {"destination": "skill-md", "card": {"headline": "the story"}}
        model = _build(_item(has_proposal=True, destination="skill-md"), proposal=proposal)
        assert [c.key for c in model.cards] == ["headline"]

    def test_no_proposal_no_cards(self):
        model = _build(_item())
        assert model.cards == ()


class TestFinding:
    def test_finding_pulls_from_the_record(self):
        model = _build(_item())
        assert model.finding.record_type == "behavior"
        assert "Stop the container first." in model.finding.body
        assert model.finding.source == "teach"
        assert model.finding.sightings == 1
        assert "teach" in model.finding.provenance_text

    def test_title_falls_back_to_untitled_never_blank_silently(self):
        model = _build(_item(title=""))
        assert model.finding.title == "(untitled)"


class TestChangeRegionNoProposal:
    def test_no_proposal_message(self):
        model = _build(_item())
        assert model.change.kind == "none"
        assert model.change.content is None
        assert model.change.message == NO_ANALYSIS_MESSAGE


class TestChangeRegionDiff:
    def test_diff_present_renders_with_preview_honesty_caption(self):
        proposal = {"destination": "skill-md", "rationale": "x"}
        model = _build(
            _item(has_proposal=True, destination="skill-md"),
            proposal=proposal,
            diff_text="--- a\n+++ b\n",
        )
        assert model.change.kind == "diff"
        assert model.change.content == "--- a\n+++ b\n"
        assert model.change.caption == PREVIEW_HONESTY_CAPTION


class TestChangeRegionProposalYamlFallback:
    def test_proposal_without_diff_renders_raw_yaml_text(self):
        proposal = {"destination": "skill-md", "rationale": "x"}
        raw_text = "destination: skill-md\nrationale: x\n"
        model = _build(
            _item(has_proposal=True, destination="skill-md"),
            proposal=proposal,
            diff_text=None,
            proposal_raw_text=raw_text,
        )
        assert model.change.kind == "proposal-yaml"
        assert model.change.content == raw_text
        assert model.change.caption == PREVIEW_HONESTY_CAPTION


class TestChangeRegionHook:
    def test_hook_destination_renders_full_script_and_replay_examples_with_m3_caption(self):
        proposal = {
            "destination": "hook",
            "script": "#!/usr/bin/env bash\necho guard\n",
            "examples": {
                "allow": [{"tool_name": "Edit", "tool_input": {"file_path": "/x"}}],
                "deny": [{"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}}],
            },
        }
        model = _build(
            _item(has_proposal=True, destination="hook"),
            proposal=proposal,
            diff_text=None,
        )
        assert model.change.kind == "hook"
        assert model.change.content == proposal["script"]
        assert model.change.caption == HOOK_VERBATIM_CAPTION
        assert model.change.replay_examples == proposal["examples"]
        # the M3 caption is textually DIFFERENT from the standard
        # regenerate-at-apply caption — never both at once
        assert model.change.caption != PREVIEW_HONESTY_CAPTION

    def test_hook_wins_over_a_diff_sibling_if_somehow_both_exist(self):
        proposal = {"destination": "hook", "script": "#!/usr/bin/env bash\n", "examples": {}}
        model = _build(
            _item(has_proposal=True, destination="hook"),
            proposal=proposal,
            diff_text="--- a\n+++ b\n",
        )
        assert model.change.kind == "hook"


class TestChangeRegionNewSkill:
    def test_new_skill_scaffold_preview_with_name(self):
        proposal = {"destination": "new-skill", "new_skill": "mouse-firmware"}
        model = _build(
            _item(has_proposal=True, destination="new-skill"), proposal=proposal
        )
        assert model.change.kind == "new-skill"
        assert model.change.scaffold_name == "mouse-firmware"
        assert model.change.content is not None
        assert "mouse-firmware" in model.change.content

    def test_new_skill_without_a_name_yet_renders_generic_preview(self):
        proposal = {"destination": "new-skill"}
        model = _build(
            _item(has_proposal=True, destination="new-skill"), proposal=proposal
        )
        assert model.change.kind == "new-skill"
        assert model.change.scaffold_name is None
        assert model.change.content  # never blank


class TestWhyRegion:
    def test_no_proposal_freshness_is_none(self):
        model = _build(_item())
        assert model.why.freshness == "none"
        assert model.why.freshness_label == "no analysis yet"

    def test_fresh_proposal(self):
        proposal = {"destination": "skill-md", "rationale": "why", "alternates": ["claude-md"]}
        model = _build(
            _item(has_proposal=True, destination="skill-md", proposal_fresh=True),
            proposal=proposal,
        )
        assert model.why.freshness == "fresh"
        assert model.why.rationale == "why"
        assert model.why.alternates == ("claude-md",)

    def test_stale_proposal_freshness_comes_from_the_cli_field_never_recomputed(self):
        # the item says proposal_fresh=False even though a proposal
        # dict is present — the model must trust the CLI field, not
        # infer freshness itself.
        proposal = {"destination": "skill-md", "rationale": "why"}
        model = _build(
            _item(has_proposal=True, destination="skill-md", proposal_fresh=False),
            proposal=proposal,
        )
        assert model.why.freshness == "stale"
        assert "Iterate to regenerate" in model.why.freshness_label

    def test_already_canon_and_reason_pass_through(self):
        proposal = {
            "destination": "skill-md",
            "rationale": "why",
            "already_canon": True,
            "already_canon_reason": "SKILL.md already covers this",
        }
        model = _build(
            _item(has_proposal=True, destination="skill-md", already_canon=True),
            proposal=proposal,
        )
        assert model.why.already_canon is True
        assert model.why.already_canon_reason == "SKILL.md already covers this"


class TestContradicts:
    def test_no_proposal_no_contradicts(self):
        model = _build(_item())
        assert model.contradicts == ()

    def test_proposal_contradicts_list_passes_through(self):
        proposal = {"destination": "skill-md", "rationale": "x", "contradicts": ["lrn-bb000002"]}
        model = _build(
            _item(has_proposal=True, destination="skill-md"), proposal=proposal
        )
        assert model.contradicts == ("lrn-bb000002",)


class TestDestinationCycle:
    def test_cycle_is_always_the_parameter_free_set(self):
        model = _build(_item())
        assert model.destination_cycle == PARAMETER_FREE_DESTINATIONS
        assert "hook" not in model.destination_cycle
        assert "new-skill" not in model.destination_cycle


class TestBadges:
    def test_mined_badge(self):
        model = _build(_item(source="session"))
        assert any(b.kind == "mined" for b in model.badges)

    def test_deferred_badge(self):
        future = (NOW + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        model = _build(_item(deferred_until=future))
        assert any(b.kind == "deferred" for b in model.badges)

    def test_already_canon_badge(self):
        model = _build(_item(already_canon=True))
        assert any(b.kind == "already-canon" for b in model.badges)

    def test_stale_badge(self):
        model = _build(
            _item(has_proposal=True, destination="skill-md", proposal_fresh=False)
        )
        assert any(b.kind == "stale" for b in model.badges)

    def test_unregistered_host_badge(self):
        model = _build(_item(), host_registered=False, host_add_command="self-learn host add /x")
        assert any(b.kind == "unregistered-host" for b in model.badges)
        assert model.host_add_command == "self-learn host add /x"

    def test_registered_host_no_badge(self):
        model = _build(_item(), host_registered=True)
        assert not any(b.kind == "unregistered-host" for b in model.badges)

    def test_every_badge_carries_non_empty_text(self):
        # Y-10: hue is never the sole carrier.
        proposal = {"destination": "skill-md", "rationale": "x"}
        model = _build(
            _item(
                has_proposal=True, destination="skill-md", proposal_fresh=False,
                already_canon=True, source="session",
                deferred_until=(NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
            proposal=proposal,
            host_registered=False,
            host_add_command=None,
        )
        assert len(model.badges) >= 4
        assert all(b.text.strip() for b in model.badges)
