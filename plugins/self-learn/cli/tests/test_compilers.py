"""compilers.py — managed-section regeneration + references append (T6).

Covers 02 §4's contract: golden-file regeneration, idempotency, trigger-first
entry format with ids, deterministic ordering, EOF bootstrap with exactly one
preceding blank line, byte-exact preservation outside markers, in-marker
hand-edits overwritten, unconditional entry/word counting (U-cap retired
the mechanical cap — see test_context_budget.py for the report-only
signals built on these counts), and the references compiler's append /
create-if-absent / refusal / no-op rules.
"""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn.compilers import (
    BEGIN_MARKER,
    END_MARKER,
    CompileError,
    apply_paths_frontmatter,
    compile_managed_file,
    compile_managed_text,
    compile_reference,
    entry_line,
    expected_paths,
    paths_frontmatter_drift,
    read_paths_frontmatter,
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
        assert result.changed and not result.bootstrapped

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


# ------------------------------------------------------------------- counting


class TestSectionCounts:
    """U-cap §6.1: the mechanical cap is retired — the compiler counts
    entries/words unconditionally and applies every entry regardless of
    count, with no threshold anywhere in this function."""

    def test_eleven_entries_all_applied_and_counted(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        records = [knowledge(f"lrn-{i:08x}", f"Fact number {i}.") for i in range(11)]
        result = compile_managed_text(pre, records)
        assert result.entry_count == 11
        assert all(r.id in result.text for r in records)  # nothing dropped

    def test_word_count_matches_the_entry_lines(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        records = [
            knowledge(f"lrn-{i:08x}", "A fact that spends quite a few words saying it.")
            for i in range(3)
        ]
        result = compile_managed_text(pre, records)
        entries = result.text.split(BEGIN_MARKER)[1].split(END_MARKER)[0].strip().splitlines()
        assert result.word_count == sum(len(e.split()) for e in entries)
        assert all(r.id in result.text for r in records)

    def test_section_result_has_no_cap_fields(self):
        pre = f"{BEGIN_MARKER}\n{END_MARKER}\n"
        result = compile_managed_text(pre, [knowledge("lrn-00000001", "Fact.")])
        fields = set(result.__dataclass_fields__)
        assert "over_cap" not in fields
        assert "cap_reason" not in fields

    def test_no_per_target_override_params_exist(self):
        import inspect

        params = inspect.signature(compile_managed_text).parameters
        assert "max_entries" not in params
        assert "max_words" not in params


class TestCapRetirementIrreversible:
    """U-cap §7 T1 -- the retirement is complete AND irreversible-by-
    accident. T1.3 and half of T1.4 live above in TestSectionCounts;
    this class is the rest of T1 (u-cap code gate r1, MAJOR 2): T1.1/
    T1.2 (module-level absence), the remaining T1.4 leg
    (`compile_managed_file` -- its old dotfiles-wrapper sibling was
    deleted outright by U-hostmode Phase 2, not merely re-checked), T1.5
    (`verbs.VerbResult`), and T1.6 (the source-grep guard WITH its
    positive control -- without the positive control, a mis-rooted path
    search passes vacuously, `lrn-ca690038` / `lrn-ea833a5b`)."""

    def test_t1_1_no_default_max_constants_on_compilers_module(self):
        from self_learn import compilers as compilers_module

        assert not hasattr(compilers_module, "DEFAULT_MAX_ENTRIES")
        assert not hasattr(compilers_module, "DEFAULT_MAX_WORDS")

    def test_t1_2_no_default_max_constants_in_dunder_all(self):
        from self_learn import compilers as compilers_module

        assert "DEFAULT_MAX_ENTRIES" not in compilers_module.__all__
        assert "DEFAULT_MAX_WORDS" not in compilers_module.__all__

    def test_t1_4_compile_managed_file_has_no_override_params(self):
        import inspect

        params = inspect.signature(compile_managed_file).parameters
        assert "max_entries" not in params
        assert "max_words" not in params

    def test_t1_5_verb_result_has_no_over_cap_note(self):
        from self_learn import verbs

        assert not hasattr(verbs.VerbResult, "over_cap_note")

    def test_t1_6_source_grep_guard_with_positive_control(self, tmp_path):
        forbidden = [
            "over_cap", "cap_reason", "entries_cap", "words_cap",
            "DEFAULT_MAX_ENTRIES", "DEFAULT_MAX_WORDS",
            "REFERENCE_NO_CAP_LINE", "cap-free", "no cap",
        ]

        def _hits(root: Path, tokens: list[str]) -> list[tuple[Path, str]]:
            found: list[tuple[Path, str]] = []
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for token in tokens:
                    if token in text:
                        found.append((path, token))
            return found

        cli_src = Path(__file__).resolve().parent.parent / "src"
        ui_src = Path(__file__).resolve().parent.parent.parent / "ui" / "src"
        assert cli_src.is_dir(), cli_src
        assert ui_src.is_dir(), ui_src

        hits = _hits(cli_src, forbidden) + _hits(ui_src, forbidden)
        assert hits == [], f"retired cap tokens still present: {hits}"

        # Positive control for the grep helper ITSELF: run it against a
        # planted decoy that DOES contain a forbidden token. If this
        # fails, the helper (or its path roots) is broken in a way that
        # would make the assertion above pass vacuously.
        decoy_root = tmp_path / "decoy"
        decoy_root.mkdir()
        (decoy_root / "still_capped.py").write_text(
            "over_cap = True  # not actually retired\n", encoding="utf-8"
        )
        control_hits = _hits(decoy_root, forbidden)
        assert control_hits, "grep helper failed to find a planted forbidden token"


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


# ============================================================ U-pathed (r2)
#
# `paths:` frontmatter emission (docs/specs/self-learn/drafts/
# u-pathed-emission-spec.md, r2). This block covers the pure primitives
# (§2's register: expected_paths / read_paths_frontmatter /
# paths_frontmatter_drift) plus apply_paths_frontmatter's own file-level
# mechanics (§3.2's ownership rule, A7/A8/A13/A16/A17). The route/verb-
# level criteria (A1, A2, A5, A9-A12) live in test_a2_rules_local.py's
# "Obligation 19" block, matching that file's existing obligation-numbered
# layout and Env fixture.


def _load_leading_frontmatter(text):
    """A16's "different loader": split the file's OWN two `---` fences by
    hand (never through `compilers._find_leading_block`, which is the
    module under test) and safe-load only the inner span — a bare
    `YAML().load()` over the whole file text sees TWO yaml documents (a
    second `---` starts a new document, it does not end one) and raises."""
    lines = text.split("\n")
    assert lines[0] == "---"
    close = lines[1:].index("---") + 1
    inner = "\n".join(lines[1:close])
    return YAML(typ="safe").load(inner)


def rules_record(
    record_id, rules_paths=None, rules_topic="t", routed_at="2026-07-13T18:02:00Z",
    scope="project",
):
    """A routed rules-variant record: carries `routing.rules_paths` only
    when given (a bare route omits the key entirely — the globless/
    absorbing case, §2 rule 2 — never an empty list, matching how a real
    proposal/route omits it, `verbs.py` obligation 16)."""
    routing = {
        "routed_at": routed_at,
        "destination": "claude-md",
        "variant": "rules",
        "rules_topic": rules_topic,
        "by": "human",
    }
    if rules_paths is not None:
        routing["rules_paths"] = list(rules_paths)
    record = Record.create(
        type="behavior",
        scope=scope,
        kind="anti-pattern",
        source="teach",
        trigger="About to touch a file this topic's globs name.",
        instruction="Follow the pinned convention for this file type.",
        record_id=record_id,
    )
    record.set_routing(routing)
    record.set_status("routed")
    return record


class TestExpectedPaths:
    """§2's U(T) register — the ONE place the three union rules live."""

    def test_empty_compile_set_is_unpathed(self):
        assert expected_paths([]) == ()

    def test_single_record_globs_pass_through_sorted(self):
        r = rules_record("lrn-aaaaaaa1", rules_paths=["b/**", "a/**"])
        assert expected_paths([r]) == ("a/**", "b/**")

    def test_union_is_deduped_and_sorted_M2(self):
        """M2: an unsorted, undeduped tuple must NOT pass — this is the
        mutation's owner (A3)."""
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["b/**", "a/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["a/**", "c/**"])
        result = expected_paths([r1, r2])
        assert result == ("a/**", "b/**", "c/**")
        assert result == tuple(sorted(set(result)))  # byte-stable: no dupes, sorted

    def test_reversed_input_order_is_byte_stable(self):
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["b/**", "a/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["a/**", "c/**"])
        assert expected_paths([r1, r2]) == expected_paths([r2, r1])

    def test_absorbing_rule_any_globless_record_empties_union_M1(self):
        """M1: deleting the absorbing rule (§2 rule 2) and returning the
        union anyway must NOT pass — this mutation's owner (A4)."""
        pathed = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        globless = rules_record("lrn-bbbbbbb2", rules_paths=None)
        assert expected_paths([pathed, globless]) == ()
        assert expected_paths([globless, pathed]) == ()  # order-independent

    def test_non_routed_and_superseded_drop_out(self):
        """The SAME `_eligible` filter the managed section uses — a
        pending or graduated record never counts toward C(T)."""
        pending = Record.create(
            type="behavior", scope="project", kind="anti-pattern", source="teach",
            trigger="X.", instruction="Y.",
        )
        graduated = rules_record("lrn-0000000d", rules_paths=["dead/**"])
        graduated.set_superseded_by("canon")
        keeper = rules_record("lrn-0000000e", rules_paths=["a/**"])
        assert expected_paths([pending, graduated, keeper]) == ("a/**",)

    def test_str_comparison_no_normalization(self):
        """Builder decision §6.11: globs are compared/stored verbatim —
        `src/**` and `./src/**` are two different globs in the union."""
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["src/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["./src/**"])
        assert expected_paths([r1, r2]) == ("./src/**", "src/**")


class TestReadPathsFrontmatter:
    """The direct-reader legs of A15 — never through the drift path, which
    deliberately does not use this function (M14's target)."""

    def test_absent_frontmatter_is_unpathed(self):
        assert read_paths_frontmatter("no frontmatter here\n") == ()

    def test_empty_text_is_unpathed(self):
        assert read_paths_frontmatter("") == ()

    def test_absent_paths_key_is_unpathed(self):
        assert read_paths_frontmatter("---\nfoo: bar\n---\n") == ()

    def test_scalar_paths_value_is_unpathed(self):
        assert read_paths_frontmatter("---\npaths: src/**\n---\n") == ()

    def test_empty_list_paths_value_is_unpathed(self):
        assert read_paths_frontmatter("---\npaths: []\n---\n") == ()

    def test_well_formed_list_returns_exact_tuple(self):
        text = "---\npaths:\n  - a/**\n  - b/**\n---\n"
        assert read_paths_frontmatter(text) == ("a/**", "b/**")

    def test_null_paths_value_is_unpathed(self):
        """Nit from the F1 gate round: `paths: null` is a third malformed
        shape (alongside the scalar and `[]` legs above) that the reader
        normalizes down to the same falsy `()` — has_paths_key, not this
        function, is what the F1 refusal keys on."""
        assert read_paths_frontmatter("---\npaths: null\n---\n") == ()
        assert read_paths_frontmatter("---\npaths:\n---\n") == ()

    def test_non_string_list_paths_value_is_unpathed(self):
        """A list whose items aren't all strings (e.g. a stray mapping or
        number in the sequence) is not a well-formed U(T) — read as
        unpathed rather than raising or coercing."""
        assert read_paths_frontmatter("---\npaths:\n  - 1\n  - true\n---\n") == ()

    def test_unterminated_block_never_raises_reads_as_unpathed(self):
        """The reader is used broadly and must never raise — an
        unterminated block reads as absent, unlike the drift/apply path,
        which refuses loudly (A8)."""
        assert read_paths_frontmatter("---\nno terminator\n") == ()


class TestPathsFrontmatterDrift:
    """§2's *agreement* predicate — A15's raw-value legs. M15's target: a
    build comparing `read_paths_frontmatter(text) == expected` instead of
    the raw value calls a stale scalar / `[]` clean whenever `U(T) == ()`
    — the scalar and `[]` legs below are what catch that."""

    def test_hand_edited_list_is_drift(self):
        r = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        text = "---\npaths:\n  - z/**\n---\n"
        assert paths_frontmatter_drift(text, [r]) is not None

    def test_absent_frontmatter_with_globs_expected_is_drift(self):
        """The positive control: a reader that always returns () must not
        read as clean when records carry globs."""
        r = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        assert paths_frontmatter_drift("no frontmatter\n", [r]) is not None

    def test_scalar_paths_is_drift_when_union_is_empty_M15(self):
        r = rules_record("lrn-aaaaaaa1", rules_paths=None)  # U(T) == ()
        text = "---\npaths: src/**\n---\n"
        assert paths_frontmatter_drift(text, [r]) is not None

    def test_empty_list_paths_is_drift_when_union_is_empty_M15(self):
        r = rules_record("lrn-aaaaaaa1", rules_paths=None)
        text = "---\npaths: []\n---\n"
        assert paths_frontmatter_drift(text, [r]) is not None

    def test_different_order_is_drift(self):
        """§2 pins the SORTED order as the agreement, not the set."""
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["b/**"])
        text = "---\npaths:\n  - b/**\n  - a/**\n---\n"
        assert paths_frontmatter_drift(text, [r1, r2]) is not None

    def test_agreement_after_repair_is_none(self):
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["b/**"])
        text = "---\npaths:\n  - a/**\n  - b/**\n---\n"
        assert paths_frontmatter_drift(text, [r1, r2]) is None

    def test_absent_paths_key_agrees_when_union_empty(self):
        r = rules_record("lrn-aaaaaaa1", rules_paths=None)
        assert paths_frontmatter_drift("no frontmatter\n", [r]) is None
        assert paths_frontmatter_drift("---\nfoo: bar\n---\n", [r]) is None

    def test_unterminated_block_raises(self):
        r = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        with pytest.raises(CompileError):
            paths_frontmatter_drift("---\nno terminator\n", [r])

    def test_non_mapping_block_raises(self):
        r = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        with pytest.raises(CompileError):
            paths_frontmatter_drift("---\n- a\n- b\n---\n", [r])


class TestApplyPathsFrontmatter:
    """File-level mechanics: A1/A4/A6's disk-write shape (the route-level
    wiring lives in test_a2_rules_local.py), plus A7/A8/A13/A16/A17, which
    are properties of the primitive itself and are pinned here directly."""

    def test_creates_frontmatter_on_disk(self, tmp_path):
        """The 'validated but never written' control (M3): the file
        actually changes on disk, re-parseable by an independent loader."""
        target = tmp_path / "t.md"
        target.write_text("", encoding="utf-8")
        r = rules_record("lrn-aaaaaaa1", rules_paths=["src/**/*.ts"])
        result = apply_paths_frontmatter(target, [r])
        assert result.changed is True
        assert result.paths == ("src/**/*.ts",)
        text = target.read_text(encoding="utf-8")
        loaded = _load_leading_frontmatter(text)
        assert loaded == {"paths": ["src/**/*.ts"]}

    def test_second_call_is_a_noop_A13(self, tmp_path):
        target = tmp_path / "t.md"
        target.write_text("", encoding="utf-8")
        r = rules_record("lrn-aaaaaaa1", rules_paths=["src/**"])
        first = apply_paths_frontmatter(target, [r])
        assert first.changed
        before = target.read_text(encoding="utf-8")
        second = apply_paths_frontmatter(target, [r])
        assert second.changed is False
        assert second.drift is None
        assert target.read_text(encoding="utf-8") == before

    def test_absorption_removes_existing_key_on_the_route_that_causes_it(self, tmp_path):
        target = tmp_path / "topic-a.md"
        target.write_text(
            "---\npaths:\n  - a/**\n---\nBODY\n", encoding="utf-8"
        )
        globless = rules_record("lrn-9eee0001", rules_paths=None, rules_topic="topic-a")
        result = apply_paths_frontmatter(target, [globless])
        text = target.read_text(encoding="utf-8")
        assert "paths:" not in text
        assert "BODY" in text
        assert result.paths == ()
        assert result.unpathed_by == ("lrn-9eee0001",)

    def test_plainly_unpathed_topic_never_emits_a_note(self, tmp_path):
        """Absorption's own fail-open control: 'a plainly unpathed rules
        file is normal and stays silent' (§3.3) — a topic where NO record
        ever carried globs must never claim absorption happened. Without
        the 'at least one record carries globs' half of the condition,
        this bare-globless case would ALSO warn, drowning the real signal
        in noise on every ordinary unpathed topic."""
        target = tmp_path / "topic-c.md"
        target.write_text("", encoding="utf-8")
        globless = rules_record("lrn-9eee0001", rules_paths=None, rules_topic="topic-c")
        result = apply_paths_frontmatter(target, [globless])
        assert result.changed is False  # no pre-existing block; already agrees
        assert result.paths == ()
        assert result.unpathed_by == ("lrn-9eee0001",)  # the derived value IS non-empty
        assert result.notes == ()  # but nothing is worth surfacing

    def test_absorption_warns_when_a_sibling_record_carries_globs_A4(self, tmp_path):
        """Without this, 'no paths: key' passes on a build that never
        emits anything anywhere (A4's own warning about itself)."""
        target = tmp_path / "topic-b.md"
        target.write_text(
            "---\npaths:\n  - a/**\n---\nBODY\n", encoding="utf-8"
        )
        pathed = rules_record("lrn-9eee0002", rules_paths=["a/**"], rules_topic="topic-b")
        globless = rules_record("lrn-9eee0001", rules_paths=None, rules_topic="topic-b")
        result = apply_paths_frontmatter(target, [pathed, globless])
        assert result.paths == ()
        assert any(
            "UNPATHED" in n and "lrn-9eee0001" in n for n in result.notes
        ), result.notes

    def test_widening_note_and_flag_A3(self, tmp_path):
        target = tmp_path / "t.md"
        target.write_text("---\npaths:\n  - a/**\n---\n", encoding="utf-8")
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["b/**"])
        result = apply_paths_frontmatter(target, [r1, r2])
        assert result.paths == ("a/**", "b/**")
        assert result.widened is True
        assert any("union of 2 routed lessons" in n for n in result.notes)

    def test_no_widening_when_every_record_matches_the_union(self, tmp_path):
        target = tmp_path / "t.md"
        target.write_text("", encoding="utf-8")
        r = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        result = apply_paths_frontmatter(target, [r])
        assert result.widened is False
        assert not any("union of" in n for n in result.notes)

    def test_no_widening_on_order_only_difference_F4(self, tmp_path):
        """F4: a single record whose own ``rules_paths`` lists its globs in
        a different order than the emitted union (nobody hand-sorts a
        proposal) fires on exactly the files it named — comparing the raw
        tuples (instead of sets) called this widened, which degrades the
        channel that carries A4's absorption alarm."""
        target = tmp_path / "t.md"
        target.write_text("", encoding="utf-8")
        r = rules_record("lrn-aaaaaaa1", rules_paths=["b/**", "a/**"])
        result = apply_paths_frontmatter(target, [r])
        assert result.paths == ("a/**", "b/**")  # U(T) is sorted
        assert result.widened is False
        assert not any("union of" in n for n in result.notes)

    def test_drift_repaired_note_only_when_block_pre_existed_A6(self, tmp_path):
        target = tmp_path / "t.md"
        target.write_text(
            "---\npaths:\n  - stale/**\n---\nBODY\n", encoding="utf-8"
        )
        r = rules_record("lrn-aaaaaaa1", rules_paths=["fresh/**"])
        result = apply_paths_frontmatter(target, [r])
        assert result.drift is not None
        assert any("rewrote the compiler-owned" in n for n in result.notes)

    def test_no_drift_repaired_note_on_fresh_bootstrap(self, tmp_path):
        """A block that did not exist before is not a 'repair' of a hand
        edit — nothing was hand-edited."""
        target = tmp_path / "t.md"
        target.write_text("", encoding="utf-8")
        r = rules_record("lrn-aaaaaaa1", rules_paths=["fresh/**"])
        result = apply_paths_frontmatter(target, [r])
        assert result.drift is not None  # disagreement (no key vs expected)
        assert not any("rewrote the compiler-owned" in n for n in result.notes)

    def test_foreign_frontmatter_survives_exactly_one_block_A7(self, tmp_path):
        """M20's target: a build that PREPENDS a fresh block instead of
        rewriting the loaded one leaves a duplicate stale block below it —
        caught here by pinning the file's FULL leading block against an
        expected literal, and asserting fence position/count."""
        target = tmp_path / "t.md"
        target.write_text(
            "---\n# do not hand-edit\nfoo: bar\npaths:\n  - old/**\n---\nBODY\n",
            encoding="utf-8",
        )
        r = rules_record("lrn-aaaaaaa1", rules_paths=["new/**"])
        apply_paths_frontmatter(target, [r])
        text = target.read_text(encoding="utf-8")
        assert text == (
            "---\n# do not hand-edit\nfoo: bar\npaths:\n  - new/**\n---\nBODY\n"
        )
        lines = text.split("\n")
        assert lines[0] == "---"
        # exactly one more '---' fence above BODY, and none after it
        fence_indices = [i for i, ln in enumerate(lines) if ln == "---"]
        assert len(fence_indices) == 2
        assert lines[fence_indices[1] + 1] == "BODY"

    def test_comment_below_paths_list_survives_widen_A7_F3(self, tmp_path):
        """F3: a comment below the ``paths:`` list (before the next key)
        used to be discarded on a WIDEN because the old code replaced the
        whole node (``mapping["paths"] = list(u)``) — a plain reassignment
        drops the CommentedSeq the comment was attached to. The fix mutates
        the existing CommentedSeq in place (pop/index-assign/append), which
        keeps the comment. Note the comment's ATTACHMENT POINT does not
        migrate to the end of the (now longer) list — ruamel keys it to the
        index it was attached to at parse time, so it renders between the
        original last item and the newly appended one. That's a property of
        the fix, pinned here rather than asserted away."""
        target = tmp_path / "t.md"
        target.write_text(
            "---\npaths:\n  - a/**\n  # trailing note below list\nfoo: bar\n---\nBODY\n",
            encoding="utf-8",
        )
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["b/**"])
        apply_paths_frontmatter(target, [r1, r2])
        text = target.read_text(encoding="utf-8")
        assert text == (
            "---\npaths:\n  - a/**\n  # trailing note below list\n  - b/**\n"
            "foo: bar\n---\nBODY\n"
        )
        assert "# trailing note below list" in text  # comment not lost (F3)

    def test_comment_below_paths_list_survives_narrow_A7_F3(self, tmp_path):
        """F3, the other direction: a comment attached below the LAST item
        of a two-item list must survive a NARROW (in-place ``pop()`` down
        to one item), not just a widen."""
        target = tmp_path / "t.md"
        target.write_text(
            "---\npaths:\n  - a/**\n  - b/**\n  # trailing note below list\n"
            "foo: bar\n---\nBODY\n",
            encoding="utf-8",
        )
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        apply_paths_frontmatter(target, [r1])
        text = target.read_text(encoding="utf-8")
        assert text == (
            "---\npaths:\n  - a/**\n  # trailing note below list\n"
            "foo: bar\n---\nBODY\n"
        )
        assert "# trailing note below list" in text  # comment not lost (F3)

    def test_trailing_space_on_opening_fence_is_still_a_fence_A7_F2(self, tmp_path):
        """F2: ``rstrip("\\r\\n")`` left a trailing space on the OPENING
        ``--- `` line unstripped, so it read as "no leading block" and the
        emitter PREPENDED a fresh block on top of the real one — two
        ``paths:`` blocks on disk, route reported success. The fix moved
        BOTH fence checks to ``rstrip()`` together; the closing check was
        not already tolerant, and a trailing space on it raised
        ``CompileError``. The opening fence with a trailing space must now
        be recognized as the SAME block and rewritten in place — exactly
        one block on disk, no duplication."""
        target = tmp_path / "t.md"
        target.write_text(
            "--- \npaths:\n  - old/**\n---\nBODY\n", encoding="utf-8"
        )
        r = rules_record("lrn-aaaaaaa1", rules_paths=["new/**"])
        apply_paths_frontmatter(target, [r])
        text = target.read_text(encoding="utf-8")
        assert text == "---\npaths:\n  - new/**\n---\nBODY\n"
        lines = text.split("\n")
        fence_indices = [i for i, ln in enumerate(lines) if ln == "---"]
        assert len(fence_indices) == 2  # not four — no duplicate block

    def test_corrupt_leading_block_raises_A8(self, tmp_path):
        target = tmp_path / "t.md"
        target.write_text("---\nno terminator\n", encoding="utf-8")
        r = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        with pytest.raises(CompileError):
            apply_paths_frontmatter(target, [r])

    def test_missing_file_raises(self, tmp_path):
        r = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        with pytest.raises(CompileError):
            apply_paths_frontmatter(tmp_path / "nope.md", [r])

    def test_leading_star_glob_round_trips_through_independent_loader_A16(
        self, tmp_path
    ):
        """Asserting a substring of the file text would pass on an
        unquoted, alias-broken emission — this loads it back."""
        target = tmp_path / "t.md"
        target.write_text("", encoding="utf-8")
        r = rules_record("lrn-aaaaaaa1", rules_paths=["**/*.py"])
        apply_paths_frontmatter(target, [r])
        text = target.read_text(encoding="utf-8")
        assert "'**/*.py'" in text  # quoted on disk — a bare '*' is a YAML alias
        loaded = _load_leading_frontmatter(text)
        assert loaded == {"paths": ["**/*.py"]}

    def test_comment_only_block_survives_last_key_removal_A17(self, tmp_path):
        target = tmp_path / "t.md"
        target.write_text(
            "---\n# do not hand-edit\npaths:\n  - a/**\n---\nBODY\n",
            encoding="utf-8",
        )
        globless = rules_record("lrn-9eee0001", rules_paths=None)
        apply_paths_frontmatter(target, [globless])
        text = target.read_text(encoding="utf-8")
        assert "paths:" not in text
        assert "{}" not in text
        assert "# do not hand-edit" in text
        assert "BODY" in text

    def test_block_with_no_comment_is_removed_entirely_A17_contrast(self, tmp_path):
        target = tmp_path / "t.md"
        target.write_text("---\npaths:\n  - a/**\n---\n\nBODY\n", encoding="utf-8")
        globless = rules_record("lrn-9eee0001", rules_paths=None)
        apply_paths_frontmatter(target, [globless])
        text = target.read_text(encoding="utf-8")
        assert text == "BODY\n"
        assert "{}" not in text
        assert "---" not in text

    @pytest.mark.parametrize(
        "placement,source",
        [
            ("above", "---\n# do not hand-edit\npaths:\n  - a/**\n---\nBODY\n"),
            ("below", "---\npaths:\n  - a/**\n# do not hand-edit\n---\nBODY\n"),
            ("below-indented",
             "---\npaths:\n  - a/**\n  # do not hand-edit\n---\nBODY\n"),
            ("between-items",
             "---\npaths:\n  - a/**\n  # do not hand-edit\n  - b/**\n---\nBODY\n"),
        ],
    )
    def test_comment_survives_last_key_removal_at_any_placement_A17_F5(
        self, placement, source, tmp_path
    ):
        """A17 asserted that a comment survives the removal of the last key,
        but its fixture put the comment ABOVE ``paths:`` — the one placement
        ruamel keeps for free, because it attaches to the MAPPING. Every
        other placement attaches to the ``CommentedSeq`` that ``del`` throws
        away, so the block was judged empty and deleted, comment and all:
        ``'---\\npaths:\\n  - a/**\\n# do not hand-edit\\n---\\nBODY\\n'``
        compiled to ``'BODY\\n'``. A17 passed for the wrong reason — it
        tested the placement that could not fail. This runs the same
        assertion at all four placements."""
        target = tmp_path / "t.md"
        target.write_text(source, encoding="utf-8")
        globless = rules_record("lrn-9eee0001", rules_paths=None)
        apply_paths_frontmatter(target, [globless])
        text = target.read_text(encoding="utf-8")
        assert "# do not hand-edit" in text, f"comment destroyed at {placement}"
        assert "paths:" not in text
        assert "{}" not in text
        assert "BODY" in text
        # The block it survives in must still be well-formed YAML carrying no
        # keys. A comments-only document loads as None, not {} — asserting
        # `== {}` here would be asserting the `{}` form §3.2 prohibits.
        assert _load_leading_frontmatter(text) is None

    def test_comment_survives_paths_removal_when_another_key_remains_F5(
        self, tmp_path
    ):
        """The sibling branch of the same defect, and the likelier one in a
        real rules file: ``paths:`` is deleted but ``foo:`` keeps the block
        alive, so the "no keys left" recovery never runs — and the comment
        keyed to the discarded sequence was silently dropped while the block
        itself survived."""
        target = tmp_path / "t.md"
        target.write_text(
            "---\npaths:\n  - a/**\n  # do not hand-edit\nfoo: bar\n---\nBODY\n",
            encoding="utf-8",
        )
        globless = rules_record("lrn-9eee0001", rules_paths=None)
        apply_paths_frontmatter(target, [globless])
        text = target.read_text(encoding="utf-8")
        assert "# do not hand-edit" in text
        assert "paths:" not in text
        assert _load_leading_frontmatter(text) == {"foo": "bar"}

    def test_comment_keyed_to_a_popped_glob_survives_narrow_F5(self, tmp_path):
        """In-place ``pop()`` keeps a comment only when the item it is keyed
        to outlives the narrow; 4 of 8 measured configurations lose it
        otherwise. Here the comment is keyed to ``b/**``, which the narrow
        removes. The text must still be in the file — appended to the block,
        since its anchor no longer exists — rather than deleted with the
        glob it annotated."""
        target = tmp_path / "t.md"
        target.write_text(
            "---\npaths:\n  - a/**\n  # keyed to b\n  - b/**\n---\nBODY\n",
            encoding="utf-8",
        )
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        apply_paths_frontmatter(target, [r1])
        text = target.read_text(encoding="utf-8")
        assert "# keyed to b" in text
        assert _load_leading_frontmatter(text) == {"paths": ["a/**"]}

    def test_comment_recovery_does_not_accumulate_across_rewrites_F5(
        self, tmp_path
    ):
        """A recovered comment is itself a standalone line on the next read,
        so a later rewrite must MATCH it rather than append a second copy —
        otherwise the block grows by one duplicate line per compile.

        This drives narrow → widen → narrow, so every call has real
        ``paths:`` drift and actually reaches the rewrite. Calling apply
        twice with the SAME records would not test this: the second call
        finds no drift and returns without writing, so the file is trivially
        unchanged and the assertion passes without the recovery path ever
        running a second time."""
        target = tmp_path / "t.md"
        target.write_text(
            "---\npaths:\n  - a/**\n  # keyed to b\n  - b/**\n---\nBODY\n",
            encoding="utf-8",
        )
        r1 = rules_record("lrn-aaaaaaa1", rules_paths=["a/**"])
        r2 = rules_record("lrn-bbbbbbb2", rules_paths=["b/**"])

        apply_paths_frontmatter(target, [r1])  # narrow: b/** popped
        narrowed = target.read_text(encoding="utf-8")
        assert narrowed.count("# keyed to b") == 1

        apply_paths_frontmatter(target, [r1, r2])  # widen back
        assert target.read_text(encoding="utf-8").count("# keyed to b") == 1

        apply_paths_frontmatter(target, [r1])  # narrow again
        assert target.read_text(encoding="utf-8").count("# keyed to b") == 1
        # and the file has settled — same globs, same bytes as the first narrow
        assert target.read_text(encoding="utf-8") == narrowed

    def test_inline_comment_on_a_glob_leaves_with_that_glob_F5(self, tmp_path):
        """The deliberate boundary of the recovery: an INLINE trailer
        annotates the item it rides on, so it is not recovered when that
        item goes. Only whole-line comments are. Pinned so the boundary is a
        decision rather than an accident."""
        target = tmp_path / "t.md"
        target.write_text(
            "---\npaths:\n  - a/** # why a\n---\nBODY\n", encoding="utf-8"
        )
        globless = rules_record("lrn-9eee0001", rules_paths=None)
        apply_paths_frontmatter(target, [globless])
        text = target.read_text(encoding="utf-8")
        assert text == "BODY\n"
        assert "why a" not in text
