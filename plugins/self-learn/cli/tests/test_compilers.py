"""compilers.py — managed-section regeneration + references append (T6).

Covers 02 §4's contract: golden-file regeneration, idempotency, trigger-first
entry format with ids, deterministic ordering, EOF bootstrap with exactly one
preceding blank line, byte-exact preservation outside markers, in-marker
hand-edits overwritten, the mechanical overflow cap (entries + words), and
the references compiler's append / create-if-absent / refusal / no-op rules.
"""

from pathlib import Path

import pytest

from self_learn.compilers import (
    BEGIN_MARKER,
    END_MARKER,
    CompileError,
    compile_managed_file,
    compile_managed_text,
    compile_reference,
    entry_line,
)
from self_learn.records import Record

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


# ------------------------------------------------------------------ builders


def routed(record, routed_at="2026-07-13T18:02:00Z", destination="skill-md"):
    record.set_routing({"routed_at": routed_at, "destination": destination, "by": "human"})
    record.set_status("routed")
    return record


def behavior(record_id, trigger, instruction, routed_at="2026-07-13T18:02:00Z"):
    return routed(
        Record.create(
            type="behavior",
            scope="skill:home-assistant",
            kind="anti-pattern",
            source="teach",
            trigger=trigger,
            instruction=instruction,
            record_id=record_id,
        ),
        routed_at=routed_at,
    )


def knowledge(record_id, fact, context=None, routed_at="2026-07-13T18:02:00Z"):
    return routed(
        Record.create(
            type="knowledge",
            scope="skill:home-assistant",
            source="teach",
            fact=fact,
            context=context,
            record_id=record_id,
        ),
        routed_at=routed_at,
    )


def golden_records():
    """The two records behind the golden fixtures (02 §1's example lesson +
    the fixture-C fact), with routed_at fixing the order."""
    return [
        behavior(
            "lrn-4c1e9a2f",
            "About to edit a `.storage/*.json` file while Home Assistant is running.",
            "Stop the HA container first. HA caches `.storage` in memory and "
            "rewrites it on shutdown, so a live edit is silently clobbered.",
            routed_at="2026-07-13T18:02:00Z",
        ),
        knowledge(
            "lrn-77ab01cd",
            "A config-entry reload does not re-read `data.host`.",
            routed_at="2026-07-13T19:00:00Z",
        ),
    ]


# --------------------------------------------------------------- entry format


class TestEntryFormat:
    def test_behavior_is_trigger_first_with_id(self):
        line = entry_line(golden_records()[0])
        assert line == (
            "- **When about to edit a `.storage/*.json` file while Home Assistant "
            "is running:** stop the HA container first. HA caches `.storage` in memory and rewrites it on shutdown, so a live edit is silently clobbered. *(lrn-4c1e9a2f)*"
        )

    def test_knowledge_is_fact_one_liner_with_id(self):
        line = entry_line(golden_records()[1])
        assert line == "- A config-entry reload does not re-read `data.host`. *(lrn-77ab01cd)*"

    def test_instruction_keeps_the_why(self):
        # Audit 2026-07-14: the first-sentence cut silently dropped the why;
        # the whole first line survives (doctrine §6), the word cap polices.
        line = entry_line(golden_records()[0])
        assert "caches" in line  # the why sentence survives

    def test_every_entry_is_one_line(self):
        for record in golden_records():
            assert "\n" not in entry_line(record)


# ---------------------------------------------------------------- golden file


class TestGoldenRegeneration:
    def test_regeneration_matches_golden(self):
        pre = (GOLDEN / "managed-pre.md").read_text(encoding="utf-8")
        result = compile_managed_text(pre, golden_records())
        assert result.text == (GOLDEN / "managed-expected.md").read_text(encoding="utf-8")
        assert result.changed and not result.bootstrapped and not result.over_cap

    def test_second_run_is_byte_stable(self):
        expected = (GOLDEN / "managed-expected.md").read_text(encoding="utf-8")
        result = compile_managed_text(expected, golden_records())
        assert result.text == expected
        assert not result.changed

    def test_hand_edit_inside_markers_is_overwritten(self):
        pre = (GOLDEN / "managed-pre.md").read_text(encoding="utf-8")
        assert "hand-edited garbage" in pre  # the fixture plants one
        result = compile_managed_text(pre, golden_records())
        assert "hand-edited garbage" not in result.text
        assert "lrn-deadbeef" not in result.text

    def test_text_outside_markers_preserved_byte_exact(self):
        pre = (GOLDEN / "managed-pre.md").read_text(encoding="utf-8")
        result = compile_managed_text(pre, golden_records())
        assert result.text[: pre.index(BEGIN_MARKER)] == pre[: pre.index(BEGIN_MARKER)]
        tail_pre = pre[pre.index(END_MARKER) + len(END_MARKER) :]
        tail_new = result.text[result.text.index(END_MARKER) + len(END_MARKER) :]
        assert tail_new == tail_pre

    def test_ordering_is_routed_at_then_id(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        records = [
            knowledge("lrn-bbbbbbbb", "Fact B.", routed_at="2026-07-13T10:00:00Z"),
            knowledge("lrn-aaaaaaaa", "Fact A.", routed_at="2026-07-14T10:00:00Z"),
            knowledge("lrn-cccccccc", "Fact C.", routed_at="2026-07-13T10:00:00Z"),
        ]
        text = compile_managed_text(pre, records).text
        # same routed_at: id breaks the tie; later routed_at sorts last
        assert (
            text.index("lrn-bbbbbbbb") < text.index("lrn-cccccccc") < text.index("lrn-aaaaaaaa")
        )
        # reversed input order compiles to the identical bytes
        assert compile_managed_text(pre, list(reversed(records))).text == text

    def test_non_routed_and_canon_superseded_records_drop_out(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        pending = Record.create(
            type="knowledge", scope="project", source="teach", fact="Still pending."
        )
        graduated = knowledge("lrn-0000000d", "Graduated fact.")
        graduated.set_superseded_by("canon")
        keeper = knowledge("lrn-0000000e", "Kept fact.")
        text = compile_managed_text(pre, [pending, graduated, keeper]).text
        assert "lrn-0000000e" in text
        assert "lrn-0000000d" not in text and "Still pending." not in text


# ------------------------------------------------------------------ bootstrap


class TestBootstrap:
    def test_markerless_target_matches_golden(self):
        pre = (GOLDEN / "bootstrap-pre.md").read_text(encoding="utf-8")
        result = compile_managed_text(pre, golden_records())
        assert result.text == (GOLDEN / "bootstrap-expected.md").read_text(encoding="utf-8")
        assert result.bootstrapped

    def test_exactly_one_blank_line_before_markers(self):
        for tail in ("", "\n", "\n\n\n"):
            result = compile_managed_text("# T\n\nProse." + tail, golden_records())
            assert f"Prose.\n\n{BEGIN_MARKER}\n" in result.text
            assert f"Prose.\n\n\n{BEGIN_MARKER}" not in result.text

    def test_empty_target_gets_bare_section(self):
        result = compile_managed_text("", [])
        assert result.text == f"{BEGIN_MARKER}\n{END_MARKER}\n"
        assert result.bootstrapped

    def test_second_run_after_bootstrap_is_stable(self):
        once = compile_managed_text("# T\n\nProse.\n", golden_records()).text
        again = compile_managed_text(once, golden_records())
        assert again.text == once and not again.changed and not again.bootstrapped


# ------------------------------------------------------------------- overflow


class TestOverflowCap:
    def test_eleventh_entry_still_applied_but_flagged(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        records = [knowledge(f"lrn-{i:08x}", f"Fact number {i}.") for i in range(11)]
        result = compile_managed_text(pre, records)
        assert result.entry_count == 11
        assert all(r.id in result.text for r in records)  # nothing dropped
        assert result.over_cap and result.cap_reason == "entries"

    def test_ten_entries_not_flagged(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        records = [knowledge(f"lrn-{i:08x}", f"Fact number {i}.") for i in range(10)]
        result = compile_managed_text(pre, records)
        assert result.entry_count == 10 and not result.over_cap

    def test_word_cap_variant(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        records = [
            knowledge(f"lrn-{i:08x}", "A fact that spends quite a few words saying it.")
            for i in range(3)
        ]
        result = compile_managed_text(pre, records, max_words=20)
        assert result.over_cap and result.cap_reason == "words"
        assert all(r.id in result.text for r in records)  # applied anyway

    def test_per_target_entry_override(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        records = [knowledge(f"lrn-{i:08x}", f"Fact {i}.") for i in range(3)]
        result = compile_managed_text(pre, records, max_entries=2)
        assert result.over_cap and result.cap_reason == "entries"


# --------------------------------------------------------------- broken input


class TestBrokenTargets:
    def test_begin_without_end_raises(self):
        with pytest.raises(CompileError):
            compile_managed_text(f"x\n{BEGIN_MARKER}\ny\n", [])

    def test_end_without_begin_raises(self):
        with pytest.raises(CompileError):
            compile_managed_text(f"x\n{END_MARKER}\ny\n", [])

    def test_end_before_begin_raises(self):
        with pytest.raises(CompileError):
            compile_managed_text(f"{END_MARKER}\n{BEGIN_MARKER}\n", [])

    def test_two_sections_raise(self):
        text = f"{BEGIN_MARKER}\n{END_MARKER}\n{BEGIN_MARKER}\n{END_MARKER}\n"
        with pytest.raises(CompileError):
            compile_managed_text(text, [])


# --------------------------------------------------------------- file wrapper


class TestManagedFile:
    def test_writes_only_when_changed(self, tmp_path):
        target = tmp_path / "SKILL.md"
        target.write_text((GOLDEN / "managed-pre.md").read_text(encoding="utf-8"))
        first = compile_managed_file(target, golden_records())
        assert first.changed
        assert target.read_text(encoding="utf-8") == (
            (GOLDEN / "managed-expected.md").read_text(encoding="utf-8")
        )
        second = compile_managed_file(target, golden_records())
        assert not second.changed
        assert target.read_text(encoding="utf-8") == first.text

    def test_missing_target_refused(self, tmp_path):
        with pytest.raises(CompileError):
            compile_managed_file(tmp_path / "nope" / "SKILL.md", golden_records())


# ----------------------------------------------------------------- references


class TestReferencesCompiler:
    def test_learnings_created_with_header_and_entry(self, tmp_path):
        refs = tmp_path / "references"
        record = golden_records()[0]
        result = compile_reference(refs, record)
        assert result.created and result.applied
        text = (refs / "LEARNINGS.md").read_text(encoding="utf-8")
        assert text.startswith("# Learnings\n")
        assert "## 2026-07-13 — lrn-4c1e9a2f" in text
        assert "**Trigger:**" in text and "**Instruction:**" in text

    def test_append_to_existing_learnings(self, tmp_path):
        refs = tmp_path / "references"
        compile_reference(refs, golden_records()[0])
        result = compile_reference(refs, golden_records()[1])
        assert result.applied and not result.created
        text = (refs / "LEARNINGS.md").read_text(encoding="utf-8")
        assert text.index("lrn-4c1e9a2f") < text.index("lrn-77ab01cd")
        assert "**Fact:** A config-entry reload does not re-read `data.host`." in text

    def test_reappend_same_record_is_noop(self, tmp_path):
        refs = tmp_path / "references"
        compile_reference(refs, golden_records()[0])
        before = (refs / "LEARNINGS.md").read_text(encoding="utf-8")
        result = compile_reference(refs, golden_records()[0])
        assert not result.applied and result.entry is None
        assert (refs / "LEARNINGS.md").read_text(encoding="utf-8") == before

    def test_named_existing_dest_is_used(self, tmp_path):
        refs = tmp_path / "references"
        refs.mkdir()
        other = refs / "network-facts.md"
        other.write_text("# Network facts\n", encoding="utf-8")
        result = compile_reference(refs, golden_records()[1], dest="network-facts.md")
        assert result.path == other and result.applied
        assert "lrn-77ab01cd" in other.read_text(encoding="utf-8")
        assert not (refs / "LEARNINGS.md").exists()

    def test_named_nonexistent_dest_refused(self, tmp_path):
        refs = tmp_path / "references"
        refs.mkdir()
        with pytest.raises(CompileError):
            compile_reference(refs, golden_records()[0], dest="not-there.md")
        assert not (refs / "not-there.md").exists()  # never created

    def test_gotchas_journal_refused_even_if_it_exists(self, tmp_path):
        refs = tmp_path / "references"
        refs.mkdir()
        journal = refs / "GOTCHAS.journal.md"
        journal.write_text("# ha-note's surface\n", encoding="utf-8")
        with pytest.raises(CompileError):
            compile_reference(refs, golden_records()[0], dest="GOTCHAS.journal.md")
        assert journal.read_text(encoding="utf-8") == "# ha-note's surface\n"

    def test_knowledge_context_included(self, tmp_path):
        refs = tmp_path / "references"
        record = knowledge(
            "lrn-00000c1e", "Reloads keep the old host.", context="Seen on the 2026-06 move."
        )
        compile_reference(refs, record)
        text = (refs / "LEARNINGS.md").read_text(encoding="utf-8")
        assert "**Context:** Seen on the 2026-06 move." in text


# --------------------------------------- episode-brief compiler exclusion (U18)


def _routed_record_with_brief(record_id: str, marker: str) -> Record:
    """A behavior record carrying a '## Episode brief' section (added while
    still pending, then routed) — the compiler-exclusion regression's
    fixture. ``marker`` is a distinctive string that must never surface in
    any compiled output (02 §1's "no compiler ever reads it" pin)."""
    record = Record.create(
        type="behavior",
        scope="skill:home-assistant",
        kind="anti-pattern",
        source="session",
        trigger="About to edit a `.storage/*.json` file while Home Assistant is running.",
        instruction="Stop the HA container first.",
        record_id=record_id,
    )
    record.set_body(
        record.body.rstrip("\n")
        + f"\n\n## Episode brief\n{marker} — the whole retelling of the episode.\n"
    )
    return routed(record)


class TestEpisodeBriefCompilerExclusion:
    """10 §3 U18 (b) / 02 §1's compiler-exclusion obligation: a record
    carrying a ``## Episode brief`` section compiles to a managed section
    (SKILL.md / CLAUDE.md — same ``compile_managed_text``, so one exercise
    covers both real targets) and a reference-journal entry whose outputs
    contain NONE of the brief text. Exclusion holds by construction
    (compilers.py never does ``sections.get("Episode brief")``); these
    tests are the do-not-regress guard."""

    MARKER = "ZZZ-EPISODE-BRIEF-MUST-NOT-LEAK-ZZZ"

    def test_excluded_from_managed_section(self):
        record = _routed_record_with_brief("lrn-eb000001", self.MARKER)
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        result = compile_managed_text(pre, [record])
        assert self.MARKER not in result.text
        assert "lrn-eb000001" in result.text  # the entry itself DID compile

    def test_excluded_on_recompile(self):
        """A second regeneration pass (the recompile path — e.g. after an
        unrelated record is added/routed) must stay leak-free too, not
        just the first pass."""
        record = _routed_record_with_brief("lrn-eb000002", self.MARKER)
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        first = compile_managed_text(pre, [record])
        second = compile_managed_text(first.text, [record, golden_records()[1]])
        assert self.MARKER not in second.text
        assert "lrn-eb000002" in second.text and "lrn-77ab01cd" in second.text

    def test_excluded_from_reference_journal(self, tmp_path):
        record = _routed_record_with_brief("lrn-eb000003", self.MARKER)
        refs = tmp_path / "references"
        result = compile_reference(refs, record)
        text = result.path.read_text(encoding="utf-8")
        assert self.MARKER not in text
        assert "lrn-eb000003" in text  # the entry itself DID compile

    def test_entry_line_excludes_brief(self):
        """entry_line is the primitive both the managed-section and
        (indirectly, via _body_sections) reference compilers build on —
        asserting it directly pins the exclusion at its source."""
        record = _routed_record_with_brief("lrn-eb000004", self.MARKER)
        assert self.MARKER not in entry_line(record)
