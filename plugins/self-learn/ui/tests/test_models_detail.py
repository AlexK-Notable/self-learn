"""Pure model tests: build_detail_model. Records are built via
self_learn.records.Record.create (a pure in-memory constructor — no I/O),
everything else is hand-constructed dicts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from self_learn.records import Record
from self_learn.verbs import DEFAULT_USER_CLAUDE_MD
from self_learn_ui import models as models_module
from self_learn_ui.models import (
    HOOK_VERBATIM_CAPTION,
    NO_ANALYSIS_MESSAGE,
    PARAMETER_FREE_DESTINATIONS,
    PREVIEW_HONESTY_CAPTION,
    build_detail_model,
    correct_destination,
    destination_label,
    destination_path,
    destinations_for_scope,
    parse_variant_qualifier,
    rules_firing_note,
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


def _build(item, proposal=None, diff_text=None, proposal_raw_text=None, record=None, **kw):
    kwargs: dict[str, Any] = dict(
        bucket="s", scope="skill", host_registered=True, host_add_command=None, now=NOW
    )
    kwargs.update(kw)
    return build_detail_model(
        item, record or _record(), proposal, diff_text, proposal_raw_text, REGISTRY, **kwargs
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


class TestEpisodeBrief:
    """09 §2.3 Y-21 / 10 §3 U18: the finding model splits '## Episode
    brief' out of the record body — decision content renders exactly as
    it did before the brief existed, and the brief exposes separately."""

    def test_absent_brief_is_none_and_body_unchanged(self):
        model = _build(_item())
        assert model.finding.episode_brief is None
        assert "Stop the container first." in model.finding.body

    def test_brief_present_is_split_out_of_body(self):
        with_brief = _record()
        with_brief.set_body(
            with_brief.body.rstrip("\n")
            + "\n\n## Episode brief\nTried the quick fix, it broke, so we did it properly.\n"
        )
        model = _build(_item(), record=with_brief)
        assert model.finding.episode_brief == (
            "Tried the quick fix, it broke, so we did it properly."
        )
        # decision content is byte-identical to the no-brief case
        without_brief = _build(_item())
        assert model.finding.body == without_brief.finding.body
        assert "Episode brief" not in model.finding.body
        assert "Tried the quick fix" not in model.finding.body


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

    def test_no_variant_fields_default_to_none_and_empty_p_a6(self):
        # P-A6-style no-migration: a pre-A2 (or non-rules) proposal never
        # sets these — the Why region must not invent placeholder values.
        proposal = {"destination": "skill-md", "rationale": "why"}
        model = _build(
            _item(has_proposal=True, destination="skill-md"), proposal=proposal
        )
        assert model.why.variant is None
        assert model.why.rules_topic is None
        assert model.why.rules_paths == ()

    def test_rules_variant_fields_thread_through_from_the_proposal(self):
        # A2 §11/§15 item 9: the SUGGESTED destination's own variant
        # fields, read straight off the proposal dict — never `item`.
        proposal = {
            "destination": "claude-md",
            "rationale": "why",
            "variant": "rules",
            "rules_topic": "subagents",
            "rules_paths": ["src/**/*.ts"],
        }
        model = _build(
            _item(has_proposal=True, destination="claude-md", scope="user"),
            proposal=proposal, scope="user",
        )
        assert model.why.variant == "rules"
        assert model.why.rules_topic == "subagents"
        assert model.why.rules_paths == ("src/**/*.ts",)

    def test_local_variant_field_threads_through_with_no_topic_or_paths(self):
        proposal = {"destination": "claude-md", "rationale": "why", "variant": "local"}
        model = _build(
            _item(has_proposal=True, destination="claude-md", scope="project"),
            proposal=proposal, scope="project",
        )
        assert model.why.variant == "local"
        assert model.why.rules_topic is None
        assert model.why.rules_paths == ()


#: A no-op claude-md fill fragment (§6.3 shape) for tests that just need
#: SOME valid claude-md datum and don't care about its numbers.
_QUIET_CLAUDE_MD_FILL = {
    "entries": 0, "words": 0, "load_class": "unconditional",
    "file_words": None, "file_tokens_est": None, "managed_share": None,
    "rules_topic_count": 0,
    "rules_cofire": {"topics": [], "unpathed": [], "pairs": [], "max_fanin": 0},
    "cofire_crowded": False,
}

_QUIET_REFERENCE_FILL = {
    "read_rate_state": "not-instrumented", "safe_overflow": None,
    "why": "read rate UNKNOWN.", "targets_zero_read": None,
    "targets_total": 0, "reads_30d_total": None,
}


class TestSurfaceBudgets:
    """09 §11 Y-20 / 08 §1 `surface_fill` -> `model.why.budgets`, rewritten
    by U-cap §6.6: there is no cap, so every row is a CLI-datum row —
    including `reference`, now sourced from the read-rate verdict rather
    than a static line. Template-truth: the sentence is built once in
    models.py off the CLI's datum, never re-derived per render."""

    def test_t12_6_reference_no_cap_line_is_gone(self):
        assert not hasattr(models_module, "REFERENCE_NO_CAP_LINE")

    def test_no_surface_fill_key_yields_no_rows(self):
        # skill scope, no `surface_fill` in the item at all (as if the
        # caller forgot --surface-fill, or the CLI omitted every key) ->
        # EVERY row is simply absent now — U-cap retires the static
        # reference line, so there is nothing left to render unconditionally.
        model = _build(_item(), scope="skill")
        assert model.why.budgets == ()

    def test_all_scope_valid_destinations_render_their_datum(self):
        fill = {
            "skill-md": {
                "entries": 8, "words": 40, "load_class": "conditional",
                "file_words": None, "file_tokens_est": None,
                "managed_share": None,
            },
            "claude-md": {
                "entries": 0, "words": 0, "load_class": "unconditional",
                "file_words": 200, "file_tokens_est": 266,
                "managed_share": 0.0, "rules_topic_count": 0,
                "rules_cofire": {
                    "topics": [], "unpathed": [], "pairs": [], "max_fanin": 0,
                },
                "cofire_crowded": False,
            },
            "reference": {
                "read_rate_state": "ok", "safe_overflow": True,
                "why": "every known reference target has been read at "
                "least once.",
                "targets_zero_read": 0, "targets_total": 2,
                "reads_30d_total": 5,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        assert set(by_dest) == {"skill-md", "claude-md", "reference"}
        # skill-md is Class B (conditional) — no cap, so no file/share
        # datum at all, and the on-invoke phrasing:
        assert by_dest["skill-md"].text == (
            "this skill-md section holds 8 entries / 40 words — on-invoke "
            "content, not always-on"
        )
        # claude-md is Class A (unconditional) — the file/share datum is
        # part of the sentence:
        assert by_dest["claude-md"].text == (
            "this claude-md section holds 0 entries / 0 words — 0% of a "
            "200-word always-on file"
        )
        assert by_dest["reference"].text == (
            "every reference target has been read at least once "
            "(5 reads/30d)."
        )

    def test_reference_missing_key_renders_no_row(self):
        # T12.3: the `reference` key ABSENT (a verdict failure, F5) ->
        # the row is simply omitted, never a placeholder.
        fill = {"claude-md": dict(_QUIET_CLAUDE_MD_FILL)}
        model = _build(_item(surface_fill=fill), scope="skill")
        destinations = [b.destination for b in model.why.budgets]
        assert "reference" not in destinations

    @pytest.mark.parametrize(
        "state, expect_word",
        [
            ("not-instrumented", "UNKNOWN"),
            ("none-enumerable", "UNKNOWN"),
            ("no-reads-observed", "never"),
            ("partly-cold", "never"),
        ],
    )
    def test_reference_row_text_by_state(self, state, expect_word):
        fill = {
            "reference": {
                "read_rate_state": state,
                "safe_overflow": None if "instrument" in state or "enumerable" in state else False,
                "why": "x", "targets_zero_read": 1, "targets_total": 2,
                "reads_30d_total": 0,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        assert expect_word in by_dest["reference"].text

    def test_missing_key_renders_nothing_for_that_destination(self):
        # skill-md omitted (as a VerbError leg would leave it, F5) —
        # no row at all for it, never a zero, never a placeholder.
        fill = {"claude-md": dict(_QUIET_CLAUDE_MD_FILL)}
        model = _build(_item(surface_fill=fill), scope="skill")
        destinations = [b.destination for b in model.why.budgets]
        assert "skill-md" not in destinations
        assert "claude-md" in destinations
        assert "reference" not in destinations  # T12.3: absent key -> no row

    def test_flagged_flag_passes_through_without_extra_markup(self):
        # U-cap §6.6: `flagged` is a NEUTRAL EMPHASIS cue — there is no
        # cap, so nothing here is a warning; the fill fact only, no
        # escalation text is ever appended into the sentence.
        fill = {
            "claude-md": {
                "entries": 3, "words": 33, "load_class": "unconditional",
                "file_words": None, "file_tokens_est": None,
                "managed_share": None, "rules_topic_count": 6,
                "rules_cofire": {
                    "topics": ["a", "b", "c", "d", "e", "f"], "unpathed": [],
                    "pairs": [["a", "b"]], "max_fanin": 6,
                },
                "cofire_crowded": True,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        assert by_dest["claude-md"].flagged is True
        assert "holds 3 entries / 33 words" in by_dest["claude-md"].text
        assert "WARNING" not in by_dest["claude-md"].text

    def test_flagged_defaults_false(self):
        fill = {"skill-md": {
            "entries": 1, "words": 3, "load_class": "conditional",
            "file_words": None, "file_tokens_est": None, "managed_share": None,
        }}
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        assert by_dest["skill-md"].flagged is False

    def test_user_scope_never_offers_reference(self):
        # destinations_for_scope("user") == ("claude-md",) — reference is
        # not a scope-valid candidate at all, regardless of the key's
        # presence in the fill.
        fill = {
            "claude-md": dict(_QUIET_CLAUDE_MD_FILL),
            "reference": dict(_QUIET_REFERENCE_FILL),
        }
        model = _build(_item(surface_fill=fill), scope="user")
        assert [b.destination for b in model.why.budgets] == ["claude-md"]

    def test_project_scope_never_offers_skill_md(self):
        fill = {
            "claude-md": dict(_QUIET_CLAUDE_MD_FILL),
            "reference": dict(_QUIET_REFERENCE_FILL),
        }
        model = _build(_item(surface_fill=fill), scope="project")
        destinations = [b.destination for b in model.why.budgets]
        assert "skill-md" not in destinations
        assert destinations == ["claude-md", "reference"]


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
    def test_skill_scope_cycle_is_the_full_parameter_free_set(self):
        # Regression pin (feedback round 2 item 3): scope-filtering must
        # not change what a skill-scoped record offers.
        model = _build(_item())
        assert model.destination_cycle == PARAMETER_FREE_DESTINATIONS
        assert "hook" not in model.destination_cycle
        assert "new-skill" not in model.destination_cycle

    def test_project_scope_cycle_never_offers_skill_md(self):
        model = _build(_item(scope="project"), scope="project")
        assert model.destination_cycle == ("claude-md", "reference")

    def test_user_scope_cycle_is_claude_md_only(self):
        model = _build(_item(scope="user"), scope="user")
        assert model.destination_cycle == ("claude-md",)


class TestDestinationsForScope:
    def test_cli_scope_rules_projected_onto_the_parameter_free_set(self):
        # Ground truth: the route verb's target resolver — skill-md needs
        # skill:<name> scope; reference needs skill or project; claude-md
        # is valid everywhere.
        assert destinations_for_scope("skill") == PARAMETER_FREE_DESTINATIONS
        assert destinations_for_scope("project") == ("claude-md", "reference")
        assert destinations_for_scope("user") == ("claude-md",)

    def test_unknown_scope_degrades_to_the_everywhere_valid_singleton(self):
        assert destinations_for_scope("unknown") == ("claude-md",)


class TestDestinationDefault:
    """09 §2.3 as amended 2026-07-18 (feedback round 2 item 3): the armed
    default is always a destination the record's scope can accept, and a
    correction is explained in plain words."""

    def test_scope_valid_suggestion_passes_through_without_note(self):
        proposal = {"destination": "skill-md", "rationale": "x"}
        model = _build(
            _item(has_proposal=True, destination="skill-md"), proposal=proposal
        )
        assert model.destination_default == "skill-md"
        assert model.destination_note is None

    def test_skill_md_on_project_corrects_to_claude_md_with_note(self):
        # The live 2026-07-17 stranding: skill-md proposed on a project
        # record armed, then the CLI refused after the human's confirm.
        proposal = {"destination": "skill-md", "rationale": "x"}
        model = _build(
            _item(scope="project", has_proposal=True, destination="skill-md"),
            proposal=proposal,
            scope="project",
        )
        assert model.destination_default == "claude-md"
        assert model.destination_note is not None
        assert "skill-md" in model.destination_note
        assert "corrected to claude-md" in model.destination_note
        # Y-9 register: human words — no scope slugs, no CLI jargon.
        assert "scope" not in model.destination_note

    def test_reference_on_user_corrects_to_claude_md_with_note(self):
        proposal = {"destination": "reference", "rationale": "x"}
        model = _build(
            _item(scope="user", has_proposal=True, destination="reference"),
            proposal=proposal,
            scope="user",
        )
        assert model.destination_default == "claude-md"
        assert model.destination_note is not None
        assert "reference" in model.destination_note

    def test_hook_and_new_skill_stay_the_verbs_to_enforce(self):
        # No dest armed at all — route reads the proposal's own
        # destination and remains the enforcer of structural validity.
        for dest in ("hook", "new-skill"):
            proposal = {"destination": dest, "rationale": "x"}
            model = _build(
                _item(scope="project", has_proposal=True, destination=dest),
                proposal=proposal,
                scope="project",
            )
            assert model.destination_default is None, dest
            assert model.destination_note is None, dest

    def test_no_analysis_no_default_no_note(self):
        model = _build(_item())
        assert model.destination_default is None
        assert model.destination_note is None

    def test_correct_destination_is_the_one_shared_rule(self):
        # The bucket rows and Detail thread the same function — displayed
        # == armed == executed on both surfaces.
        assert correct_destination("project", "skill-md") == (
            "claude-md",
            "the analyst suggested skill-md, which only exists for a "
            "skill's own lessons — corrected to claude-md",
        )
        assert correct_destination("skill", "skill-md") == ("skill-md", None)
        assert correct_destination("user", None) == (None, None)

    def test_qualified_rules_suggestion_outside_rules_scopes_falls_through(self):
        # Blind code-gate NOTE 6 (round 1): the qualified-passthrough leg
        # is gated on `scope in RULES_SCOPES` — skill scope is outside
        # it (P-A13, rules are unavailable there), so an already-qualified
        # suggestion must fall through to the unrecognized-value path
        # exactly as it did before that leg existed, never survive as a
        # skill-scope destination. Dropping the guard entirely would
        # otherwise survive this whole suite unnoticed.
        assert correct_destination("skill", "claude-md:rules:t") == (None, None)


class TestDestinationLabelScopeAware:
    """A1 (spec: docs/specs/self-learn/drafts/a1-labels-spec.md) O-1: the
    widened resolver — claude-md alone resolves to three different files
    by scope (verbs.py's route verb), so the label must be scope-aware;
    every other destination and every un-recognized/absent scope stays
    byte-identical to the pre-A1 gloss (test obligations 1/2)."""

    @pytest.mark.parametrize(
        "scope,label",
        [
            ("user", "User instructions"),
            ("project", "Project instructions"),
            ("skill", "Skills repo instructions"),
        ],
    )
    def test_claude_md_labels_by_scope(self, scope: str, label: str) -> None:
        assert destination_label("claude-md", scope) == label

    def test_fallback_preserved_for_no_scope_and_unknown_scope(self) -> None:
        # scope=None (the default), and any unrecognized scope, degrade
        # to today's gloss byte-for-byte — an un-updated caller never
        # crashes.
        assert destination_label("claude-md") == "Project instructions"
        assert destination_label("claude-md", None) == "Project instructions"
        assert destination_label("claude-md", "bogus-scope") == "Project instructions"

    @pytest.mark.parametrize("scope", ["user", "project", "skill", None, "bogus"])
    def test_non_claude_md_values_unaffected_by_scope(self, scope: str | None) -> None:
        # The resolver only specializes claude-md — every other
        # destination-enum value returns _GROUP_LABELS.get(value, value)
        # at EVERY scope.
        assert destination_label("skill-md", scope) == "Skill doc"
        assert destination_label("reference", scope) == "Reference file"
        assert destination_label("new-skill", scope) == "New skill"
        assert destination_label("hook", scope) == "Guard hook"

    def test_none_value_is_still_empty_string_regardless_of_scope(self) -> None:
        assert destination_label(None) == ""
        assert destination_label(None, "user") == ""


class TestDestinationPath:
    """A1 O-3 / P-A12: the resolved-path counterpart to
    destination_label, exposed for the two identity/decision surfaces
    (Detail Suggested-destination, the action-bar cycle button)."""

    def test_user_path_is_string_equal_to_the_routers_default(self) -> None:
        # F-1's own ground truth: the CLI's DEFAULT_USER_CLAUDE_MD
        # (verbs.py:158) is the compile-time constant this string names.
        assert destination_path("user") == str(DEFAULT_USER_CLAUDE_MD)
        assert destination_path("user") == "~/.claude/CLAUDE.md"

    def test_project_and_skill_are_the_schematic_tokens(self) -> None:
        assert destination_path("project") == "<repo>/CLAUDE.md"
        assert destination_path("skill") == "<skills root>/CLAUDE.md"

    def test_none_or_unknown_scope_is_empty_not_a_placeholder(self) -> None:
        assert destination_path(None) == ""
        assert destination_path("bogus-scope") == ""


class TestNoSecondLabelMap:
    """P-A11 (grep-level, test obligation 6): _GROUP_LABELS must remain
    the ONLY module-level dict keyed by destination-enum values. This
    scans the live module namespace (stronger than a textual grep — it
    survives reformatting) for any OTHER dict whose keys are (a superset
    of) the seven destination-enum values; the A1 scope specialization
    (_CLAUDE_MD_SCOPE_LABELS, keyed by user/project/skill) must NOT
    collide with this set."""

    _DESTINATION_ENUM_VALUES = frozenset(
        {"skill-md", "claude-md", "reference", "new-skill", "hook", "malformed", "no-analysis"}
    )

    def test_exactly_one_destination_enum_keyed_dict_exists(self) -> None:
        matches = [
            name
            for name, value in vars(models_module).items()
            if isinstance(value, dict)
            and self._DESTINATION_ENUM_VALUES.issubset(value.keys())
        ]
        assert matches == ["_GROUP_LABELS"]

    def test_claude_md_scope_specialization_is_scope_keyed_not_enum_keyed(self) -> None:
        # The sanctioned "extension" (spec §3 O-1): keys are scopes, not
        # any destination-enum value.
        assert set(models_module._CLAUDE_MD_SCOPE_LABELS) == {"user", "project", "skill"}
        assert set(models_module._CLAUDE_MD_SCOPE_PATHS) == {"user", "project", "skill"}
        assert self._DESTINATION_ENUM_VALUES.isdisjoint(models_module._CLAUDE_MD_SCOPE_LABELS)
        assert self._DESTINATION_ENUM_VALUES.isdisjoint(models_module._CLAUDE_MD_SCOPE_PATHS)

    def test_a2_rules_local_dicts_are_also_not_enum_keyed(self) -> None:
        """A2 §11 widening: the NEW variant-scope dicts
        (``_RULES_SCOPE_LABELS`` / ``_RULES_SCOPE_PATHS``) must be
        exactly as safe as A1's — scope-keyed, never a second
        destination-enum-keyed map."""
        matches = [
            name
            for name, value in vars(models_module).items()
            if isinstance(value, dict)
            and self._DESTINATION_ENUM_VALUES.issubset(value.keys())
        ]
        assert matches == ["_GROUP_LABELS"]
        assert set(models_module._RULES_SCOPE_LABELS) == {"user", "project"}
        assert set(models_module._RULES_SCOPE_PATHS) == {"user", "project"}
        assert self._DESTINATION_ENUM_VALUES.isdisjoint(models_module._RULES_SCOPE_LABELS)
        assert self._DESTINATION_ENUM_VALUES.isdisjoint(models_module._RULES_SCOPE_PATHS)


class TestObligation5And6VariantAwareLabels:
    """A2 §11 test obligations 5/6: label resolution is scope-AND-variant
    aware (P-A11: still off the single ``_GROUP_LABELS`` map — see
    :class:`TestNoSecondLabelMap` above), and the resolved path renders
    beside every variant label (P-A12)."""

    def test_variant_none_is_byte_identical_to_a1(self) -> None:
        # P-A6-style no-migration for the label surface: an un-updated
        # caller (variant=None, the default) sees EXACTLY A1's behavior.
        assert destination_label("claude-md", "user") == "User instructions"
        assert destination_label("claude-md", "project") == "Project instructions"
        assert destination_path("user") == "~/.claude/CLAUDE.md"

    @pytest.mark.parametrize(
        "scope,topic,label,path",
        [
            (
                "user", "subagents", "User rule — subagents",
                "~/.claude/rules/subagents.md",
            ),
            (
                "project", "subagents", "Project rule — subagents",
                "<repo>/.claude/rules/subagents.md",
            ),
        ],
    )
    def test_rules_variant_labels_and_paths(self, scope, topic, label, path) -> None:
        assert (
            destination_label("claude-md", scope, variant="rules", rules_topic=topic)
            == label
        )
        assert destination_path(scope, variant="rules", rules_topic=topic) == path

    def test_rules_variant_without_topic_omits_the_dash(self) -> None:
        # A record with a proposal but no yet-known topic still renders a
        # sane (if generic) label — never a placeholder-shaped string.
        assert destination_label("claude-md", "user", variant="rules") == "User rule"

    def test_local_variant_is_project_only(self) -> None:
        assert (
            destination_label("claude-md", "project", variant="local")
            == "Personal project notes"
        )
        assert destination_path("project", variant="local") == "<repo>/CLAUDE.local.md"
        # local at any other scope falls through to A1's plain gloss —
        # never claims a personal-notes label for a scope it cannot have
        # (§6: local is project-scope only).
        assert (
            destination_label("claude-md", "user", variant="local")
            == "User instructions"
        )

    def test_path_always_renders_beside_the_label_p_a12(self) -> None:
        for scope, topic in (("user", "keyboards"), ("project", "keyboards")):
            label = destination_label(
                "claude-md", scope, variant="rules", rules_topic=topic
            )
            path = destination_path(scope, variant="rules", rules_topic=topic)
            assert label and path
            assert topic in path


class TestParseVariantQualifier:
    """A2 §11: the pane's own decode of its ONE variant signal —
    ``VerbProposal.dest``'s colon-qualified string (``proposals.py``'s
    ``_DEST_RE`` grammar) — into the ``(variant, rules_topic)`` pair
    :func:`destination_label`/:func:`destination_path` take."""

    def test_rules_with_topic(self) -> None:
        assert parse_variant_qualifier("claude-md:rules:subagents") == (
            "rules", "subagents",
        )

    def test_local(self) -> None:
        assert parse_variant_qualifier("claude-md:local") == ("local", None)

    def test_plain_claude_md_is_none_none(self) -> None:
        assert parse_variant_qualifier("claude-md") == (None, None)

    def test_none_is_none_none(self) -> None:
        assert parse_variant_qualifier(None) == (None, None)

    def test_non_claude_md_qualified_dest_is_none_none(self) -> None:
        # new-skill:<name> / reference:<file> are colon-qualified too,
        # but never carry a rules/local variant — must not misparse.
        assert parse_variant_qualifier("new-skill:foo") == (None, None)
        assert parse_variant_qualifier("reference:notes.md") == (None, None)


class TestRulesFiringNote:
    """A2 §11 prose: the plain-words firing condition beside a variant
    label — P-A1's honest statement at the point of decision."""

    def test_pathed_names_the_globs(self) -> None:
        note = rules_firing_note("rules", "project", ["src/**/*.ts"])
        assert "src/**/*.ts" in note
        assert "touch" in note

    def test_unpathed_says_every_session(self) -> None:
        assert rules_firing_note("rules", "project", None) == "loads every session"

    def test_unpathed_user_scope_says_every_session_no_caveat(self) -> None:
        """U-hostmode Phase 2 (2026-08-28): the `adopted` parameter and
        its "(this machine)" caveat branch are gone — a plain host
        (user scope, since Phase 1) never distinguishes an "adopted"
        state, so this now reads exactly like project scope's
        unpathed note (UIC4). The real template call site
        (detail.html:147) never passed `adopted` even before this unit
        — it always defaulted `True` — so the return-value assertion
        alone does not discriminate a mutant that leaves the parameter
        in place (M54): the signature check below is load-bearing."""
        assert rules_firing_note("rules", "user", None) == "loads every session"
        with pytest.raises(TypeError):
            rules_firing_note("rules", "user", None, adopted=False)  # type: ignore[call-arg]

    def test_local_names_project_and_personal(self) -> None:
        note = rules_firing_note("local", "project", None)
        assert "project" in note
        assert "you only" in note

    def test_plain_claude_md_yields_no_note(self) -> None:
        assert rules_firing_note(None, "user", None) == ""


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


# =====================================================================
# U-demand-user — the pathed tier becomes pickable at user scope (S-23
# (2)): RULES_SCOPES / rules_dest / destination_cycle_for (§3.3(c)),
# proposed_destination (§3.3(d), §8A.2 H5), the user-scope firing note
# (§3.3(e)), and _DEST_CORRECTION_REASONS' honest reference wording
# (§8A.2(3)).
# =====================================================================


class TestA12RulesScopesAgreesWithTheCli:
    """A12 — models.RULES_SCOPES mirrors verbs.py::_resolve_rules_target's
    own guard (`if scope not in ("user", "project")`) — a NAMED
    agreement so a future widening of the CLI's guard has a place to
    fail. An equality-to-a-literal test cannot detect CLI drift on its
    own (stated honestly, not dressed up) — what it provides is a named
    tripwire the CLI-side change collides with."""

    def test_rules_scopes_is_exactly_user_and_project(self):
        # Source of truth: cli/src/self_learn/verbs.py::_resolve_rules_target
        # — "if scope not in ("user", "project"): raise VerbError(...)".
        # Skill scope is the P-A13 rules deferral.
        assert models_module.RULES_SCOPES == frozenset({"user", "project"})


class TestA7DestinationCycleForFunction:
    """A7 (function legs) — the pathed tier reaches the cycle and comes
    back; the no-topic leg is the anti-regression control."""

    def test_user_scope_with_topic_is_two_element_cycle(self):
        assert models_module.destination_cycle_for("user", "t") == (
            "claude-md", "claude-md:rules:t",
        )

    def test_user_scope_no_topic_is_unchanged_singleton(self):
        # Positive control: without a topic the cycle is byte-identical
        # to destinations_for_scope("user") — a build that appends
        # unconditionally fails THIS leg.
        assert models_module.destination_cycle_for("user", None) == ("claude-md",)

    def test_repeated_cycle_destination_walks_and_returns(self):
        from self_learn_ui.routes import cycle_destination

        current = None
        seen = []
        for _ in range(4):
            current = cycle_destination(current, "user", "t")
            seen.append(current)
        assert seen[:3] == ["claude-md", "claude-md:rules:t", "claude-md"]


class TestA8ProjectAndSkillScopeCycles:
    """A8 — the cycle is offered at project scope too, without disturbing
    cycle[0] or the existing order; skill scope never offers what the
    CLI refuses (P-A13)."""

    def test_project_scope_appends_after_the_existing_order(self):
        assert models_module.destination_cycle_for("project", "t") == (
            "claude-md", "reference", "claude-md:rules:t",
        )

    def test_skill_scope_never_offers_rules_even_with_a_topic(self):
        # A build that ignores RULES_SCOPES would offer the CLI-refused
        # skill-scope rules dest here.
        assert models_module.destination_cycle_for("skill", "t") == (
            PARAMETER_FREE_DESTINATIONS
        )


class TestA10UserScopeFiringNote:
    """A10 — the user-scope firing note states the cwd-relative truth
    (S-23's measurement 2) and invites no repo-targeting; project scope
    is the no-regression control.

    Blind code-gate BLOCKER (round 1): the first cut of this test only
    asserted the glob's presence plus the absence of a few banned
    substrings — every one of those assertions was ALREADY satisfied by
    the byte-identical, untouched pre-unit code (M14, "return today's
    project wording at user scope", was a semantic no-op that survived).
    This version asserts the EXACT string, both scopes, so a build that
    never adds the rider fails on equality, not on a substring gap."""

    def test_user_scope_note_states_the_rider_exactly(self):
        assert rules_firing_note("rules", "user", ("**/*.py",)) == (
            "loads when you touch `**/*.py` — matches relative to "
            "wherever the session is running, in any project"
        )

    def test_project_scope_note_is_unchanged(self):
        # The control: without it, a build that added the rider at
        # EVERY scope (not just user) would still pass the leg above.
        assert rules_firing_note("rules", "project", ("src/**",)) == (
            "loads when you touch `src/**`"
        )


class TestA19ReferenceCorrectionNoteIsScopeSpecific:
    """A19 — the user-scope `reference` correction note states the tier
    fact and does not read as a routine scope correction; project and
    skill scope are UNCHANGED — the control without which a build that
    rewrote the reason for every scope would still pass."""

    def test_user_scope_names_the_tier_fact(self):
        dest, note = correct_destination("user", "reference")
        assert dest == "claude-md"
        assert note is not None
        assert "S-23" in note or "cheap" in note
        # Must not read as a routine "wrong scope, use X instead" note —
        # the CLI-side wording (verbs.py's refusal) is the same distinct
        # register.
        assert "no cheap surface" in note or "cheap tier" in note

    def test_project_and_skill_scope_are_byte_identical_to_before(self):
        assert correct_destination("project", "reference") == ("reference", None)
        assert correct_destination("skill", "reference") == ("reference", None)


class TestA4ProposedDestinationModelLegs:
    """A4 — the UI arms the qualified dest for a rules proposal, and the
    plain one otherwise, against build_detail_model (build_bucket_model's
    own leg lives in test_models_bucket.py — separate call site)."""

    def test_rules_proposal_arms_the_qualified_dest_no_note(self):
        proposal = {
            "destination": "claude-md", "rationale": "x",
            "variant": "rules", "rules_topic": "py-conventions",
        }
        model = _build(
            _item(has_proposal=True, destination="claude-md", scope="user"),
            proposal=proposal, scope="user",
        )
        assert model.destination_default == "claude-md:rules:py-conventions"
        assert model.destination_note is None

    def test_same_item_no_variant_is_byte_identical_to_before(self):
        # Positive control — the OTHER leg. Without it a build that
        # qualifies EVERY claude-md dest (turning every plain lesson
        # into a rules route to a nonexistent topic) would still pass
        # the leg above alone.
        proposal = {"destination": "claude-md", "rationale": "x"}
        model = _build(
            _item(has_proposal=True, destination="claude-md", scope="user"),
            proposal=proposal, scope="user",
        )
        assert model.destination_default == "claude-md"
        assert model.destination_note is None


class TestH5A16RecommendationAndFlagsReachTheCard:
    """A16 — recommendation/flags reach WhyRegion, and their ABSENCE
    renders nothing (this is the model half; the rendered-page half —
    including the "no stray punctuation" leg — lives in test_routes.py,
    since a model-only assertion cannot see the template)."""

    def test_recommendation_and_flags_present_on_the_proposal(self):
        proposal = {
            "destination": "reference", "rationale": "x",
            "recommendation": "defer", "flags": ["no-cheap-surface"],
        }
        model = _build(
            _item(has_proposal=True, destination="reference", scope="user"),
            proposal=proposal, scope="user",
        )
        assert model.why.recommendation == "defer"
        assert model.why.flags == ("no-cheap-surface",)

    def test_absent_recommendation_and_flags_default_none_and_empty(self):
        # P-A6 no-migration: every pre-U-composer proposal never sets
        # these — the model must not invent placeholder values.
        proposal = {"destination": "reference", "rationale": "x"}
        model = _build(
            _item(has_proposal=True, destination="reference", scope="user"),
            proposal=proposal, scope="user",
        )
        assert model.why.recommendation is None
        assert model.why.flags == ()


class TestH5A17DeferRecommendationArmsNothing:
    """A17 — a `defer` recommendation arms NO destination, at every
    scope — the rule is about the recommendation, not about the scope
    that happens to expose it (user-scope reference vs. project-scope
    claude-md, which is otherwise perfectly scope-valid).

    Blind code-gate round 1 findings folded in:
    - FOLD (production) §8A.2(3): the note used to reuse
      correct_destination's own note, which always claims "— corrected
      to <X>" — a lie here, since a defer leg corrects nothing. Both
      legs below now assert the EXACT note text from the new
      _defer_note composer.
    - FOLD (test), gate-invented G4: swapping proposed_destination's two
      legs (checking the rules leg before the defer leg) passed the
      whole suite, because no test covered a proposal that is BOTH a
      rules proposal AND recommendation: defer. §8A.2(2) pins defer
      checked FIRST — test_rules_proposal_with_defer_still_arms_nothing
      below is that leg."""

    def test_user_scope_reference_defer_arms_nothing(self):
        proposal = {
            "destination": "reference", "rationale": "x",
            "recommendation": "defer", "flags": ["no-cheap-surface"],
        }
        dest, note = models_module.proposed_destination("user", "reference", proposal)
        assert dest is None
        assert note == (
            "the analyst suggested reference, which has no cheap surface "
            "at user scope — S-23's cheap tier here is pathed rules, not "
            "a reference file — deferred, no destination armed"
        )

    def test_project_scope_defer_arms_nothing_even_for_a_valid_destination(self):
        # M27's target: firing the defer leg on destination=="reference"
        # instead of on the recommendation. claude-md is scope-VALID at
        # project scope — only the recommendation should block it.
        proposal = {
            "destination": "claude-md", "rationale": "x",
            "recommendation": "defer",
        }
        dest, note = models_module.proposed_destination("project", "claude-md", proposal)
        assert dest is None
        assert note == "the analyst recommends deferring this lesson — no destination armed"

    def test_rules_proposal_with_defer_still_arms_nothing(self):
        # Gate-invented G4 (round 1): a proposal that is BOTH a rules
        # proposal (variant: rules, rules_topic: t) AND
        # recommendation: defer. §8A.2(2) pins the check order — defer
        # wins, unconditionally. A build that checks the rules leg
        # FIRST would instead arm "claude-md:rules:t" here.
        proposal = {
            "destination": "claude-md", "rationale": "x",
            "variant": "rules", "rules_topic": "t",
            "recommendation": "defer",
        }
        dest, note = models_module.proposed_destination("user", "claude-md", proposal)
        assert dest is None
        assert note == "the analyst recommends deferring this lesson — no destination armed"

    def test_build_argv_omits_dest_when_none(self):
        from self_learn_ui.routes import build_argv

        argv = build_argv("route", "lrn-aa000001", dest=None, by="analyst")
        assert "--dest" not in argv


class TestH5A18DeferredRecommendationEndToEnd:
    """A18 lives in test_routes.py (it needs the CLI's own refusal, end
    to end through the real ASGI app) — this is the model-level sibling
    check that a defer-armed record's hidden dest input is empty via
    build_detail_model, the piece a route-level test cannot isolate
    from the surrounding HTTP machinery."""

    def test_defer_armed_detail_model_hidden_dest_is_empty(self):
        proposal = {
            "destination": "reference", "rationale": "x",
            "recommendation": "defer", "flags": ["no-cheap-surface"],
        }
        model = _build(
            _item(has_proposal=True, destination="reference", scope="user"),
            proposal=proposal, scope="user",
        )
        assert model.destination_default is None
