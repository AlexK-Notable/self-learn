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
    REFERENCE_NO_CAP_LINE,
    build_detail_model,
    correct_destination,
    destination_label,
    destination_path,
    destinations_for_scope,
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


class TestSurfaceBudgets:
    """09 §11 Y-20 / 08 §1 `surface_fill` -> `model.why.budgets`: the Why
    region's single budget surface. Template-truth: the sentence is built
    once in models.py off the CLI's datum, never re-derived per render."""

    def test_no_surface_fill_key_yields_only_the_static_reference_line(self):
        # skill scope, no `surface_fill` in the item at all (as if the
        # caller forgot --surface-fill, or the CLI omitted every capped
        # key) -> skill-md/claude-md rows are simply absent; reference
        # is unconditional for a scope where it's a valid candidate.
        model = _build(_item(), scope="skill")
        assert [b.destination for b in model.why.budgets] == ["reference"]
        assert model.why.budgets[0].text == REFERENCE_NO_CAP_LINE

    def test_both_capped_destinations_render_their_datum(self):
        fill = {
            "skill-md": {
                "entries": 8, "entries_cap": 10, "words": 10, "words_cap": 150,
                "over_cap": False,
            },
            "claude-md": {
                "entries": 0, "entries_cap": 10, "words": 0, "words_cap": 150,
                "over_cap": False,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        assert set(by_dest) == {"skill-md", "claude-md", "reference"}
        # the spec's own illustrative sentence, verbatim (09 §11 Y-20 / §2.3)
        # — 8 of 10 is near the cap (2 entries of headroom), so it earns
        # the nearness clause:
        assert by_dest["skill-md"].text == (
            "this skill-md section already holds 8 of its 10 entries — a "
            "route here lands near the cap"
        )
        # 0 of 10 is the EMPTIEST possible surface — the best route
        # target, not a "near the cap" one (blind-review F1: the clause
        # must be gated on actual nearness, never appended
        # unconditionally on the entries branch) — bare fill fact only:
        assert by_dest["claude-md"].text == (
            "this claude-md section already holds 0 of its 10 entries"
        )
        assert by_dest["reference"].text == REFERENCE_NO_CAP_LINE

    @pytest.mark.parametrize(
        "entries, expect_clause",
        [
            (0, False),
            (3, False),
            (8, True),
            (9, True),
            (10, True),
        ],
    )
    def test_nearness_clause_gated_on_actual_proximity(self, entries, expect_clause):
        """Blind-review F1: an empty or lightly-loaded surface (0/10,
        3/10 — 7+ entries of headroom) must render the bare fill fact
        ALONE, never "lands near the cap" — that phrasing on an empty
        surface is not just uninformative, it inverts the feature's
        point (the emptiest surface is the BEST route target). Only
        within _NEAR_ENTRIES_HEADROOM (8/10, 9/10, 10/10 here) does the
        clause earn its place."""
        fill = {
            "skill-md": {
                "entries": entries, "entries_cap": 10, "words": 5,
                "words_cap": 150, "over_cap": False,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        text = by_dest["skill-md"].text
        assert text.startswith(
            f"this skill-md section already holds {entries} of its 10 entries"
        )
        if expect_clause:
            assert "lands near the cap" in text
        else:
            assert text == (
                f"this skill-md section already holds {entries} of its 10 entries"
            )

    def test_words_binding_constraint_gets_the_word_cap_phrasing(self):
        fill = {
            "skill-md": {
                "entries": 2, "entries_cap": 10, "words": 140, "words_cap": 150,
                "over_cap": False,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        assert "near its word budget" in by_dest["skill-md"].text
        assert "lands near the cap" not in by_dest["skill-md"].text

    def test_missing_key_renders_nothing_for_that_destination(self):
        # skill-md omitted (as a VerbError leg would leave it, F5) —
        # no row at all for it, never a zero, never a placeholder.
        fill = {
            "claude-md": {
                "entries": 3, "entries_cap": 10, "words": 12, "words_cap": 150,
                "over_cap": False,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        destinations = [b.destination for b in model.why.budgets]
        assert "skill-md" not in destinations
        assert "claude-md" in destinations
        assert "reference" in destinations

    def test_over_cap_flag_passes_through_without_extra_markup(self):
        # 09 §11 Y-20(5): the fill fact only — the escalation itself is
        # the EXISTING 02 §4 warning (surfaced elsewhere, at route time),
        # never duplicated into this sentence.
        fill = {
            "skill-md": {
                "entries": 11, "entries_cap": 10, "words": 33, "words_cap": 150,
                "over_cap": True,
            },
        }
        model = _build(_item(surface_fill=fill), scope="skill")
        by_dest = {b.destination: b for b in model.why.budgets}
        assert by_dest["skill-md"].over_cap is True
        assert "holds 11 of its 10 entries" in by_dest["skill-md"].text
        assert "WARNING" not in by_dest["skill-md"].text

    def test_user_scope_never_offers_reference(self):
        # destinations_for_scope("user") == ("claude-md",) — reference is
        # not a scope-valid candidate at all, so no static line either.
        fill = {
            "claude-md": {
                "entries": 0, "entries_cap": 10, "words": 0, "words_cap": 150,
                "over_cap": False,
            },
        }
        model = _build(_item(surface_fill=fill), scope="user")
        assert [b.destination for b in model.why.budgets] == ["claude-md"]

    def test_project_scope_never_offers_skill_md(self):
        fill = {
            "claude-md": {
                "entries": 1, "entries_cap": 10, "words": 4, "words_cap": 150,
                "over_cap": False,
            },
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
