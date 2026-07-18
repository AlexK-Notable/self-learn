"""records.py — schema, round-trip fidelity, and mutation rules (02 §1–§2)."""

import re
from pathlib import Path

import pytest

from self_learn.records import (
    MutationError,
    Record,
    ValidationError,
    generate_id,
    parse_record,
)

FIXTURE = Path(__file__).parent / "fixtures" / "record-02s1-example.md"


def make_behavior(**overrides):
    kwargs = dict(
        type="behavior",
        scope="skill:home-assistant",
        kind="anti-pattern",
        source="teach",
        trigger="About to edit `.storage` while HA runs.",
        instruction="Stop the container first.",
    )
    kwargs.update(overrides)
    return Record.create(**kwargs)


def make_knowledge(**overrides):
    kwargs = dict(
        type="knowledge",
        scope="project",
        source="teach",
        fact="A config-entry reload does not re-read data.host.",
    )
    kwargs.update(overrides)
    return Record.create(**kwargs)


def route(record):
    """Drive a record into the frozen state via the public lifecycle API."""
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": "hook", "by": "human"}
    )
    record.set_status("routed")


# ------------------------------------------------------------------ round-trip


class TestRoundTrip:
    def test_02s1_example_reemits_byte_identical(self):
        """T2 DoD: the 02 §1 example (comments and all) parses and re-emits
        unchanged."""
        text = FIXTURE.read_text(encoding="utf-8")
        assert parse_record(text).to_text() == text

    def test_02s1_example_fields_parse(self):
        record = Record.from_path(FIXTURE)
        assert record.id == "lrn-4c1e9a2f"
        assert record.type == "behavior"
        assert record.scope == "skill:home-assistant"
        assert record.kind == "anti-pattern"
        assert record.source == "teach"
        assert record.status == "pending"
        assert record.sightings == 2
        assert len(record.evidence) == 2
        assert record.evidence[0]["quote"] == "never edit .storage while HA is running"
        assert record.evidence[1]["origin"] == "GOTCHAS.journal.md#2026-06-08"
        assert record.routing["destination"] == "hook"
        assert record.supersedes is None
        assert record.superseded_by is None
        assert record.resolution_note is None
        assert "## Trigger" in record.body and "## Instruction" in record.body

    def test_created_record_round_trips(self):
        record = make_behavior()
        text = record.to_text()
        reparsed = parse_record(text)
        assert reparsed.to_text() == text
        assert reparsed.id == record.id

    def test_write_and_from_path(self, tmp_path):
        record = make_knowledge()
        path = tmp_path / f"{record.id}.md"
        record.write(path)
        assert Record.from_path(path).to_text() == record.to_text()


# ------------------------------------------------------------------- parsing


class TestParsing:
    def test_missing_opening_delimiter_rejected(self):
        with pytest.raises(ValidationError, match="frontmatter"):
            parse_record("id: lrn-00000000\n")

    def test_unterminated_frontmatter_rejected(self):
        with pytest.raises(ValidationError, match="closing"):
            parse_record("---\nid: lrn-00000000\n")

    def test_non_mapping_frontmatter_rejected(self):
        with pytest.raises(ValidationError, match="mapping"):
            parse_record("---\n- a\n- b\n---\n\n## Fact\nx\n")


# ---------------------------------------------------------------- id generation


class TestIdGeneration:
    def test_format_over_many_generations(self):
        pattern = re.compile(r"^lrn-[0-9a-f]{8}$")
        ids = [generate_id() for _ in range(500)]
        assert all(pattern.match(i) for i in ids)

    def test_ids_are_random_not_sequential(self):
        ids = [generate_id() for _ in range(500)]
        assert len(set(ids)) == len(ids)  # 500 draws from 2^32: collision ~ never

    def test_create_uses_conforming_id(self):
        assert re.match(r"^lrn-[0-9a-f]{8}$", make_behavior().id)


# ------------------------------------------------------------------ validation


class TestValidation:
    def test_bad_id_rejected(self):
        with pytest.raises(ValidationError, match="id"):
            make_behavior(record_id="lrn-XYZ")

    def test_bad_type_rejected(self):
        with pytest.raises(ValidationError, match="type"):
            Record.create(type="habit", scope="user", source="teach", fact="x")

    def test_bad_scope_rejected(self):
        with pytest.raises(ValidationError, match="scope"):
            make_behavior(scope="global")

    def test_empty_skill_scope_rejected(self):
        with pytest.raises(ValidationError, match="scope"):
            make_behavior(scope="skill:")

    def test_bad_kind_rejected(self):
        with pytest.raises(ValidationError, match="kind"):
            make_behavior(kind="bad-habit")

    def test_kind_on_knowledge_rejected(self):
        with pytest.raises(ValidationError, match="behavior"):
            make_knowledge(kind="anti-pattern")

    def test_bad_source_rejected(self):
        with pytest.raises(ValidationError, match="source"):
            make_behavior(source="osmosis")

    def test_behavior_missing_instruction_invalid(self):
        record = make_behavior()
        text = record.to_text().replace("## Instruction", "## Instructions")
        with pytest.raises(ValidationError, match="Instruction"):
            parse_record(text)

    def test_knowledge_with_fact_valid(self):
        record = make_knowledge()
        assert record.type == "knowledge"
        assert "## Fact" in record.body

    def test_knowledge_with_fact_and_context_valid(self):
        record = make_knowledge(context="Seen while moving HA to a new IP.")
        assert "## Context" in record.body

    def test_knowledge_missing_fact_invalid(self):
        record = make_knowledge()
        text = record.to_text().replace("## Fact", "## Factoid")
        with pytest.raises(ValidationError, match="Fact"):
            parse_record(text)


class TestEpisodeBriefSection:
    """02 §1 amendment (10 §3 U18): '## Episode brief' registers as an
    OPTIONAL body section for both types — no ``required`` weight, and
    duplicate-guarded like any other registered optional section once it
    is known to ``_validate_body``."""

    def test_optional_on_behavior_and_round_trips(self):
        record = make_behavior()
        record.set_body(
            record.body.rstrip("\n") + "\n\n## Episode brief\nThe retold story.\n"
        )
        text = record.to_text()
        reparsed = parse_record(text)
        assert reparsed.to_text() == text
        assert "## Episode brief" in reparsed.body
        assert "The retold story." in reparsed.body

    def test_optional_on_knowledge_and_round_trips(self):
        record = make_knowledge()
        record.set_body(
            record.body.rstrip("\n") + "\n\n## Episode brief\nThe retold story.\n"
        )
        text = record.to_text()
        reparsed = parse_record(text)
        assert reparsed.to_text() == text
        assert "## Episode brief" in reparsed.body

    def test_absent_is_valid_no_backfill(self):
        # A mined record without a brief is valid — no required weight,
        # and pre-amendment records have no brief and stay valid too.
        record = make_behavior()
        assert "## Episode brief" not in record.body  # never raises

    def test_duplicate_episode_brief_rejected(self):
        record = make_behavior()
        body = (
            record.body.rstrip("\n")
            + "\n\n## Episode brief\nFirst telling.\n"
            + "\n## Episode brief\nSecond telling.\n"
        )
        with pytest.raises(ValidationError, match="duplicate optional"):
            record.set_body(body)


class TestTwoLessonRejection:
    def test_two_triggers_rejected(self):
        record = make_behavior()
        body = record.body + "\n## Trigger\nA second lesson's firing condition.\n"
        with pytest.raises(ValidationError, match="two-lesson"):
            record.set_body(body)

    def test_two_facts_rejected(self):
        record = make_knowledge()
        body = record.body + "\n## Fact\nA second unrelated fact.\n"
        with pytest.raises(ValidationError, match="two-lesson"):
            record.set_body(body)

    def test_two_instructions_rejected_at_parse(self):
        record = make_behavior()
        text = record.to_text() + "\n## Instruction\nAlso do this other thing.\n"
        with pytest.raises(ValidationError, match="two-lesson"):
            parse_record(text)


# ------------------------------------------------------------- mutation rules


class TestFreezeAtRouting:
    def test_pending_body_edits_freely(self):
        record = make_behavior()
        record.set_body("\n## Trigger\nNew trigger.\n\n## Instruction\nNew instruction.\n")
        assert "New trigger." in record.body

    def test_pending_substance_fields_edit_freely(self):
        record = make_behavior()
        record.set_source("backlog")
        record.set_created_at("2026-01-01T00:00:00Z")
        assert record.source == "backlog"

    def test_deferred_still_editable(self):
        record = make_behavior()
        record.set_status("deferred")
        record.set_body("\n## Trigger\nStill a draft.\n\n## Instruction\nEdit away.\n")
        assert not record.substance_frozen

    @pytest.mark.parametrize("status", ["routed", "rejected", "superseded"])
    def test_body_frozen_after_resolution(self, status):
        record = make_behavior()
        record.set_status(status)
        with pytest.raises(MutationError, match="frozen"):
            record.set_body("\n## Trigger\nT.\n\n## Instruction\nI.\n")

    def test_type_source_created_at_frozen_after_routing(self):
        record = make_behavior()
        route(record)
        with pytest.raises(MutationError):
            record.set_type("knowledge")
        with pytest.raises(MutationError):
            record.set_source("backlog")
        with pytest.raises(MutationError):
            record.set_created_at("2020-01-01T00:00:00Z")

    def test_supersedes_frozen_after_routing(self):
        record = make_behavior()
        route(record)
        with pytest.raises(MutationError):
            record.set_supersedes("lrn-77ab01cd")

    def test_lifecycle_fields_stay_mutable_after_routing(self):
        record = make_behavior()
        route(record)
        record.set_scope("project")  # triage may re-classify: filing never frozen
        record.set_kind("surface-rule")
        record.set_sightings(2)
        record.set_status("superseded")
        record.set_deferred_until("2026-08-12")
        record.set_deferred_count(1)
        assert record.scope == "project"
        assert record.kind == "surface-rule"


class TestEvidenceAppendOnly:
    def test_append_works_while_pending(self):
        record = make_behavior()
        record.append_evidence({"session": "f687d7ce", "ts": "2026-07-13T00:00:00Z", "quote": "q"})
        assert len(record.evidence) == 1

    def test_append_works_after_routing(self):
        """Merge collapses add loser provenance post-routing (02 §2)."""
        record = make_behavior()
        route(record)
        record.append_evidence({"origin": "GOTCHAS.journal.md#2026-06-08", "note": "merge"})
        assert record.evidence[-1]["note"] == "merge"

    def test_set_evidence_raises(self):
        record = make_behavior()
        with pytest.raises(MutationError, match="append-only"):
            record.set_evidence([{"origin": "x", "note": "rewrite attempt"}])

    def test_remove_evidence_raises(self):
        record = make_behavior()
        record.append_evidence({"origin": "x#a", "note": "n"})
        with pytest.raises(MutationError, match="append-only"):
            record.remove_evidence(0)

    def test_rewrite_evidence_raises(self):
        record = make_behavior()
        record.append_evidence({"origin": "x#a", "note": "n"})
        with pytest.raises(MutationError, match="append-only"):
            record.rewrite_evidence(0, {"origin": "x#a", "note": "edited"})

    def test_evidence_view_is_copies(self):
        record = make_behavior()
        record.append_evidence({"origin": "x#a", "note": "n"})
        record.evidence[0]["note"] = "poked"
        assert record.evidence[0]["note"] == "n"

    def test_bad_entry_rejected(self):
        record = make_behavior()
        with pytest.raises(ValidationError):
            record.append_evidence("not a mapping")
        with pytest.raises(ValidationError):
            record.append_evidence({})


class TestResolutionNoteWriteOnce:
    def test_first_write_ok(self):
        record = make_behavior()
        record.set_resolution_note("deterministic guard beats advisory text")
        assert record.resolution_note == "deterministic guard beats advisory text"

    def test_second_write_raises(self):
        record = make_behavior()
        record.set_resolution_note("the why")
        with pytest.raises(MutationError, match="write-once"):
            record.set_resolution_note("a different why")

    def test_empty_note_rejected(self):
        record = make_behavior()
        with pytest.raises(ValidationError):
            record.set_resolution_note("   ")


class TestSupersededByDomain:
    def test_accepts_none_record_id_and_canon(self):
        record = make_behavior()
        record.set_superseded_by("lrn-77ab01cd")
        assert record.superseded_by == "lrn-77ab01cd"
        record.set_superseded_by("canon")
        assert record.superseded_by == "canon"
        record.set_superseded_by(None)
        assert record.superseded_by is None

    @pytest.mark.parametrize(
        "bad", ["CANON", "lrn-XYZ12345", "lrn-77ab01c", "lrn-77AB01CD", "hook", ""]
    )
    def test_rejects_everything_else(self, bad):
        record = make_behavior()
        with pytest.raises(ValidationError, match="superseded_by"):
            record.set_superseded_by(bad)

    def test_settable_on_routed_record(self):
        """Corrective supersession targets already-routed records."""
        record = make_behavior()
        route(record)
        record.set_superseded_by("lrn-77ab01cd")
        record.set_status("superseded")
        assert record.status == "superseded"


class TestOtherSetterDomains:
    def test_routing_shape_enforced(self):
        record = make_behavior()
        with pytest.raises(ValidationError, match="routing"):
            record.set_routing({"destination": "hook"})

    def test_routing_clearable(self):
        record = make_behavior()
        route(record)
        record.set_routing(None)
        assert record.routing is None

    def test_status_domain(self):
        record = make_behavior()
        with pytest.raises(ValidationError, match="status"):
            record.set_status("quarantined")  # dropped with the gen-1 machine

    def test_sightings_domain(self):
        record = make_behavior()
        with pytest.raises(ValidationError):
            record.set_sightings(0)

    def test_kind_only_on_behavior(self):
        record = make_knowledge()
        with pytest.raises(ValidationError, match="behavior"):
            record.set_kind("anti-pattern")

    def test_retype_ordering(self):
        record = make_behavior()
        # switching to knowledge with kind still set is an explicit error
        with pytest.raises(ValidationError, match="kind"):
            record.set_type("knowledge")
        record.set_kind(None)
        with pytest.raises(ValidationError, match="Fact"):
            record.set_type("knowledge")  # body still behavior-shaped
