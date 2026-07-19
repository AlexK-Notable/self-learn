"""Pure model tests: build_bucket_model / build_card_sections /
leading_text. No filesystem, no subprocess — items/proposals/clusters are
hand-constructed dicts matching the real CLI/YAML shapes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from self_learn_ui.models import build_bucket_model, build_card_sections, leading_text

NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)

REGISTRY = [
    {"key": "headline", "label": "What this is about", "order": 10, "required": "always"},
    {"key": "provenance", "label": "Where this came from", "order": 20, "required": "optional"},
    {"key": "impact", "label": "What changes if you keep it", "order": 30, "required": "routing"},
    {"key": "discuss", "label": "Worth discussing", "order": 40, "required": "routing"},
    {
        "key": "lint",
        "label": "Would a fresh session catch this?",
        "order": 50,
        "required": "optional",
    },
    {
        "key": "conflict",
        "label": "May clash with a rule you already kept",
        "order": 55,
        "required": "optional",
    },
]


def _item(id="lrn-aa000001", **overrides):
    base = {
        "id": id,
        "type": "behavior",
        "scope": "skill:s",
        "kind": "anti-pattern",
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


class TestCardSections:
    def test_empty_card_yields_no_sections(self):
        assert build_card_sections(None, REGISTRY) == ()
        assert build_card_sections({}, REGISTRY) == ()

    def test_ascending_order_present_keys_only(self):
        card = {"discuss": "the tension", "headline": "the story"}
        sections = build_card_sections(card, REGISTRY)
        assert [s.key for s in sections] == ["headline", "discuss"]
        assert sections[0].label == "What this is about"
        assert sections[0].text == "the story"

    def test_absent_keys_skipped(self):
        card = {"headline": "only this"}
        sections = build_card_sections(card, REGISTRY)
        assert len(sections) == 1

    def test_unknown_keys_render_last_with_raw_key_as_label(self):
        card = {"headline": "known", "mystery_field": "unknown text"}
        sections = build_card_sections(card, REGISTRY)
        assert [s.key for s in sections] == ["headline", "mystery_field"]
        assert sections[-1].label == "mystery_field"

    def test_empty_string_value_treated_as_absent(self):
        # a falsy (empty-string) value reads as "key not really present"
        # — never rendered as a real, blank section.
        sections = build_card_sections({"headline": ""}, REGISTRY)
        assert sections == ()

    def test_lint_and_conflict_render_after_discuss_in_registry_order(self):
        """FW-31/FW-32 (analyst-riders-spec §8 card-render obligation): a
        proposal carrying both riders' sections renders both, in registry
        order, strictly after `discuss` — build_card_sections is generic
        (no hardcoded section names), so this proves the two new registry
        rows compose correctly with the existing four, not that any
        section-specific code exists."""
        card = {
            "headline": "the story",
            "discuss": "the tension",
            "lint": "A fresh session might not catch this.",
            "conflict": "May clash with a rule you already kept.",
        }
        sections = build_card_sections(card, REGISTRY)
        assert [s.key for s in sections] == ["headline", "discuss", "lint", "conflict"]
        assert sections[2].label == "Would a fresh session catch this?"
        assert sections[3].label == "May clash with a rule you already kept"

    def test_leading_text_unaffected_by_lint_and_conflict(self):
        """Y-9 leading line is still `cards[0]` in registry order —
        adding lint (50) and conflict (55) after discuss (40) must never
        change which section leads."""
        proposal = {
            "card": {
                "headline": "human sentence",
                "lint": "would not be recognized cold",
                "conflict": "clashes with another rule",
            }
        }
        assert leading_text(proposal, REGISTRY, "ignored title") == "human sentence"


class TestLeadingText:
    def test_no_proposal_falls_back_to_title(self):
        assert leading_text(None, REGISTRY, "the real title") == "the real title"

    def test_proposal_with_card_uses_leading_card_section(self):
        proposal = {"card": {"headline": "human sentence", "discuss": "tension"}}
        assert leading_text(proposal, REGISTRY, "ignored title") == "human sentence"

    def test_proposal_without_card_falls_back_to_title(self):
        proposal = {"destination": "skill-md", "rationale": "x"}
        assert leading_text(proposal, REGISTRY, "the title") == "the title"

    def test_empty_title_never_becomes_a_raw_id(self):
        # the caller must never pass the id as "title" — this asserts
        # the fallback text is never literally an id-shaped string.
        text = leading_text(None, REGISTRY, "")
        assert not text.startswith("lrn-")
        assert text == "(untitled)"

    def test_a_record_whose_title_would_lead_with_lrn_still_isnt_the_id(self):
        # pathological title content containing "lrn-" text is rendered
        # verbatim (it's not literally the id) — the invariant is about
        # the SOURCE of the string, not a text-content ban.
        weird_title = "lrn-looking text but it's really the trigger line"
        assert leading_text(None, REGISTRY, weird_title) == weird_title


class TestRowDestinationDefault:
    """09 §2.3 as amended 2026-07-18 (feedback round 2 item 3): a row's
    armable dest is the scope-corrected default; `destination` stays the
    analyst's raw suggestion for grouping."""

    def test_project_bucket_row_corrects_skill_md(self):
        items = [_item(scope="project", has_proposal=True, destination="skill-md")]
        model = build_bucket_model(
            "p", "project", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        row = group.rows[0]
        assert row.destination == "skill-md"  # grouping keeps the suggestion
        assert row.destination_default == "claude-md"
        assert row.destination_note is not None
        assert "corrected to claude-md" in row.destination_note

    def test_skill_bucket_row_passes_through_unchanged(self):
        items = [_item(has_proposal=True, destination="skill-md")]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        row = group.rows[0]
        assert row.destination_default == "skill-md"
        assert row.destination_note is None


class TestBucketDestinationCycle:
    """F5-1 (feedback round 5, U19 §1.2 gate M1): one bucket = one scope,
    so the cycle is computed once and shared by every row's action bar —
    the server-signaled no-op the `o` key hint reads."""

    def test_skill_bucket_full_parameter_free_cycle(self):
        model = build_bucket_model(
            "s", "skill", [], {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        assert model.destination_cycle == ("skill-md", "claude-md", "reference")

    def test_user_bucket_is_the_singleton_cycle(self):
        model = build_bucket_model(
            "u", "user", [], {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        assert model.destination_cycle == ("claude-md",)


class TestGroupPrecedence:
    def test_no_proposal_goes_to_no_analysis(self):
        items = [_item(has_proposal=False, destination=None)]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        assert group.key == "no-analysis"
        assert group.label == "No analysis yet"

    def test_has_proposal_routes_to_its_destination_even_if_stale(self):
        items = [_item(has_proposal=True, destination="skill-md", proposal_fresh=False)]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        assert group.key == "skill-md"
        badge_texts = [b.text for b in group.rows[0].badges]
        assert any("stale" in t for t in badge_texts)

    def test_has_proposal_but_unparseable_destination_goes_to_malformed(self):
        items = [_item(has_proposal=True, destination=None)]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        assert group.key == "malformed"

    def test_group_display_label_is_never_the_word_unanalyzed(self):
        # W-6: "no analysis yet" must be textually distinct from the
        # Front page's "unanalyzed" eligibility count.
        items = [_item(has_proposal=False)]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        assert "unanalyzed" not in model.groups[0].label.lower()

    def test_five_destinations_each_get_their_own_group(self):
        items = [
            _item(id=f"lrn-a{i:07d}", has_proposal=True, destination=dest)
            for i, dest in enumerate(
                ["skill-md", "claude-md", "reference", "new-skill", "hook"]
            )
        ]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        assert [g.key for g in model.groups] == [
            "skill-md", "claude-md", "reference", "new-skill", "hook",
        ]


class TestRowRendering:
    def test_leading_text_prefers_proposal_card(self):
        items = [_item(has_proposal=True, destination="skill-md", title="fallback")]
        proposals: dict[str, dict | None] = {
            "lrn-aa000001": {"destination": "skill-md", "card": {"headline": "the real story"}}
        }
        model = build_bucket_model(
            "s", "skill", items, proposals, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        assert model.groups[0].rows[0].leading_text == "the real story"

    def test_mined_badge_from_session_source(self):
        items = [_item(source="session")]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        badges = model.groups[0].rows[0].badges
        assert any(b.kind == "mined" and b.text for b in badges)

    def test_non_mined_source_has_no_mined_badge(self):
        items = [_item(source="teach")]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        badges = model.groups[0].rows[0].badges
        assert not any(b.kind == "mined" for b in badges)

    def test_id_never_appears_as_the_leading_text(self):
        items = [_item(id="lrn-cafebabe", title="")]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        row = model.groups[0].rows[0]
        assert row.leading_text != row.id
        assert row.leading_text == "(untitled)"


class TestDeferredOrdering:
    def test_deferred_rows_sink_to_the_bottom_dimmed(self):
        future = (NOW + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = [
            _item(id="lrn-a0000001", deferred_until=future, age_days=1),
            _item(id="lrn-a0000002", deferred_until=None, age_days=20),
            _item(id="lrn-a0000003", deferred_until=None, age_days=5),
        ]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        rows = model.groups[0].rows
        assert [r.id for r in rows] == ["lrn-a0000002", "lrn-a0000003", "lrn-a0000001"]
        assert rows[-1].deferred is True
        assert any(b.kind == "deferred" for b in rows[-1].badges)

    def test_deferred_until_in_the_past_is_not_treated_as_deferred(self):
        past = (NOW - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = [_item(deferred_until=past)]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        assert model.groups[0].rows[0].deferred is False


class TestBulkCollapse:
    def test_homogeneous_already_canon_group_collapses(self):
        items = [
            _item(id="lrn-a0000001", has_proposal=True, destination="skill-md", already_canon=True),
            _item(id="lrn-a0000002", has_proposal=True, destination="skill-md", already_canon=True),
        ]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        assert group.rows == ()
        assert group.bulk_collapse is not None
        assert group.bulk_collapse.count == 2
        assert set(group.bulk_collapse.ids) == {"lrn-a0000001", "lrn-a0000002"}
        assert "already-canon" in group.bulk_collapse.text
        assert "2" in group.bulk_collapse.text

    def test_mixed_already_canon_group_does_not_collapse(self):
        items = [
            _item(id="lrn-a0000001", has_proposal=True, destination="skill-md", already_canon=True),
            _item(id="lrn-a0000002", has_proposal=True, destination="skill-md", already_canon=False),
        ]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        assert group.bulk_collapse is None
        assert len(group.rows) == 2

    def test_no_analysis_group_never_bulk_collapses(self):
        # already_canon is a proposal-derived field — a no-proposal group
        # is never eligible for bulk collapse regardless of the flag.
        items = [_item(has_proposal=False, already_canon=True)]
        model = build_bucket_model(
            "s", "skill", items, {}, [], REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (group,) = model.groups
        assert group.key == "no-analysis"
        assert group.bulk_collapse is None


class TestClusters:
    def test_cluster_row_fields(self):
        clusters_raw = [
            {
                "cluster_id": "merge-deadbeef",
                "records": ["lrn-a0000001", "lrn-a0000002"],
                "suggested_survivor": "lrn-a0000001",
                "rationale": "same lesson twice",
            }
        ]
        model = build_bucket_model(
            "s", "skill", [], {}, clusters_raw, REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        (cluster,) = model.clusters
        assert cluster.cluster_id == "merge-deadbeef"
        assert cluster.member_count == 2
        assert cluster.suggested_survivor == "lrn-a0000001"

    def test_clustered_records_are_excluded_from_destination_groups(self):
        items = [
            _item(id="lrn-a0000001", has_proposal=True, destination="skill-md"),
            _item(id="lrn-a0000002", has_proposal=True, destination="skill-md"),
        ]
        clusters_raw = [
            {
                "cluster_id": "merge-deadbeef",
                "records": ["lrn-a0000001", "lrn-a0000002"],
                "suggested_survivor": "lrn-a0000001",
                "rationale": "dup",
            }
        ]
        model = build_bucket_model(
            "s", "skill", items, {}, clusters_raw, REGISTRY,
            host_registered=True, host_add_command=None, now=NOW,
        )
        assert model.groups == ()
        assert len(model.clusters) == 1


class TestUnregisteredHost:
    def test_host_registered_and_command_pass_through(self):
        model = build_bucket_model(
            "some-project", "project", [], {}, [], REGISTRY,
            host_registered=False, host_add_command="self-learn host add /x", now=NOW,
        )
        assert model.host_registered is False
        assert model.host_add_command == "self-learn host add /x"
