"""K1a -- the skill template's checks, as pure functions
(``skill_scaffold.check_skill``; design: D-AUTHOR §3.2 "The template
baseline" and §3.4 "Naming").

One valid skill is the CONTROL, asserted first: it carries a reference file,
a managed section, ``paths`` and ``metadata``, and passes with no problems and
no notes. Every other case is that same skill with ONE thing broken, and must
refuse by exactly the rule id the case names (the whole set of ids is
compared, so a check that fires too much fails as surely as one that fires
too little). A "no problems" assertion is only worth anything beside cases
that show the same checker reporting the fault, so every refusal case is built
from the control and differs from it.

The checks are pure, so nothing here needs a ledger, a cache or the network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from self_learn import ledger_ops, report, skill_scaffold
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.skill_scaffold import SkillCheck, check_skill

NAME = "drawing-diagrams"
DESCRIPTION = (
    "Draws a diagram when the user asks for one. Use when asked to show, "
    "visualise or sketch a flow or a design."
)
REFERENCE = "references/format.md"
MANAGED = f"{BEGIN_MARKER}\n- a lesson routed here\n{END_MARKER}\n"
BODY = (
    "# Drawing diagrams\n"
    "\n"
    "Draw the diagram as a mermaid flowchart. The details are in "
    f"[the format notes]({REFERENCE}).\n"
)


def q(value: str) -> str:
    """A YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(value)


def valid_front() -> dict[str, str]:
    return {
        "name": q(NAME),
        "description": q(DESCRIPTION),
        "when_to_use": q("The user asks for a diagram."),
        "paths": json.dumps(["docs/**/*.md"]),
        "metadata": json.dumps({"owner": "someone"}),
    }


def render_skill_md(
    front: dict[str, str], body: str = BODY, managed: str = MANAGED
) -> str:
    lines = ["---", *(f"{k}: {v}" for k, v in front.items()), "---", ""]
    return "\n".join(lines) + f"\n{body}\n{managed}"


def skill(
    *,
    front: dict[str, str] | None = None,
    drop_front: tuple[str, ...] = (),
    body: str = BODY,
    managed: str = MANAGED,
    files: dict[str, str] | None = None,
    drop_files: tuple[str, ...] = (),
) -> dict[str, str]:
    """The valid skill, with the given changes."""
    merged = {**valid_front(), **(front or {})}
    for key in drop_front:
        del merged[key]
    out = {
        "SKILL.md": render_skill_md(merged, body, managed),
        REFERENCE: "# Format notes\n\nUse mermaid flowcharts.\n",
    }
    out.update(files or {})
    for path in drop_files:
        del out[path]
    return out


def with_skill_md(text: str) -> dict[str, str]:
    return skill(files={"SKILL.md": text})


def run(files: dict[str, str], **kwargs) -> SkillCheck:
    kwargs.setdefault("loaded_names", ())
    kwargs.setdefault("vetoed_names", ())
    return check_skill(files, **kwargs)


# ----------------------------------------------------------------- the control


def test_control_valid_skill_passes_with_no_problems_and_no_notes():
    files = skill()
    # The control is not hollow: it carries each thing the cases below break.
    assert set(files) == {"SKILL.md", REFERENCE}
    assert BEGIN_MARKER in files["SKILL.md"] and END_MARKER in files["SKILL.md"]
    assert f"]({REFERENCE})" in files["SKILL.md"]
    assert "paths:" in files["SKILL.md"] and "metadata:" in files["SKILL.md"]
    result = run(files)
    assert isinstance(result, SkillCheck)
    assert result.problems == ()
    assert result.notes == ()
    assert result.ok


def test_control_passes_with_unrelated_loaded_and_vetoed_names():
    result = run(
        skill(), loaded_names=["other-skill"], vetoed_names=["vetoed-name"]
    )
    assert result.problems == () and result.notes == ()


def test_a_skill_with_no_managed_section_and_no_references_passes():
    # The runner adds the managed section; a draft may carry none.
    files = skill(managed="", drop_files=(REFERENCE,), body="# Short\n")
    result = run(files)
    assert result.problems == () and result.notes == ()


# ---------------------------------------------------------------- the refusals


@dataclass
class Case:
    """One thing broken. ``expect`` maps each rule id the case must report to
    a substring that rule's sentence must contain (the offending value)."""

    files: dict[str, str]
    expect: dict[str, str]
    kwargs: dict = field(default_factory=dict)


def _managed_twice() -> str:
    return MANAGED + "\n" + MANAGED


CASES: dict[str, Case] = {
    # ---- name
    "name-over-64-characters": Case(
        skill(front={"name": q("a" * 65)}),
        {"name-too-long": "65 characters"},
    ),
    "name-containing-claude": Case(
        skill(front={"name": q("claude-helper")}),
        {"name-reserved-word": "claude-helper"},
    ),
    "name-containing-Anthropic": Case(
        skill(front={"name": q("Anthropic-helper")}),
        {
            "name-reserved-word": "Anthropic-helper",
            "name-not-kebab": "Anthropic-helper",
        },
    ),
    "name-containing-anthropic-lowercase": Case(
        skill(front={"name": q("anthropic-tools")}),
        {"name-reserved-word": "anthropic-tools"},
    ),
    "xml-tag-in-name": Case(
        skill(front={"name": q("my<b>skill")}),
        {"name-xml-tag": "my<b>skill", "name-not-kebab": "my<b>skill"},
    ),
    "name-not-kebab": Case(
        skill(front={"name": q("Drawing Diagrams")}),
        {"name-not-kebab": "Drawing Diagrams"},
    ),
    "name-with-trailing-newline": Case(
        skill(front={"name": q(NAME + "\n")}),
        {"name-not-kebab": "drawing-diagrams"},
    ),
    "name-missing": Case(
        skill(drop_front=("name",)),
        {"name-missing": "missing"},
    ),
    "name-not-text": Case(
        skill(front={"name": "123"}),
        {"name-missing": "must be text"},
    ),
    "name-in-loaded-names": Case(
        skill(),
        {"name-collision": NAME},
        {"loaded_names": ["something-else", NAME]},
    ),
    "name-in-loaded-names-other-case": Case(
        skill(),
        {"name-collision": NAME},
        {"loaded_names": ["Drawing-Diagrams"]},
    ),
    "name-vetoed": Case(
        skill(),
        {"name-vetoed": NAME},
        {"vetoed_names": [NAME]},
    ),
    "name-differs-from-directory-name": Case(
        skill(),
        {"name-dir-mismatch": "other-name"},
        {"expected_name": "other-name"},
    ),
    # ---- description
    "empty-description": Case(
        skill(front={"description": q("")}),
        {"description-empty": "empty"},
    ),
    "blank-description": Case(
        skill(front={"description": q("   ")}),
        {"description-empty": "empty"},
    ),
    "description-missing": Case(
        skill(drop_front=("description",)),
        {"description-empty": "missing"},
    ),
    "description-not-text": Case(
        skill(front={"description": "5"}),
        {"description-empty": "must be text"},
    ),
    "description-over-1024-characters": Case(
        skill(front={"description": q("a" * 1025)}),
        {"description-too-long": "1025 characters"},
    ),
    "xml-tag-in-description": Case(
        skill(front={"description": q("Use <b>bold</b> when needed.")}),
        {"description-xml-tag": "<b>"},
    ),
    # ---- frontmatter keys
    "hooks-key": Case(
        skill(front={"hooks": json.dumps({"PreToolUse": []})}),
        {"frontmatter-key-refused": "hooks"},
    ),
    "allowed-tools-key": Case(
        skill(front={"allowed-tools": q("Bash")}),
        {"frontmatter-key-refused": "allowed-tools"},
    ),
    "unknown-key": Case(
        skill(front={"color": q("red")}),
        {"frontmatter-key-unknown": "color"},
    ),
    "key-with-different-case-is-unknown": Case(
        skill(front={"Name": q("x")}),
        {"frontmatter-key-unknown": "Name"},
    ),
    # ---- metadata
    "metadata-self-learn": Case(
        skill(
            front={
                "metadata": json.dumps(
                    {"owner": "someone", "self-learn": {"authored_by": "model"}}
                )
            }
        ),
        {"metadata-self-learn": "metadata.self-learn"},
    ),
    "metadata-not-a-mapping": Case(
        skill(front={"metadata": q("just text")}),
        {"metadata-not-mapping": "just text"},
    ),
    # ---- paths
    "absolute-paths-entry": Case(
        skill(front={"paths": json.dumps(["/etc/**/*.md"])}),
        {"paths-absolute": "/etc/**/*.md"},
    ),
    "home-relative-paths-entry": Case(
        skill(front={"paths": json.dumps(["~/notes/**"])}),
        {"paths-absolute": "~/notes/**"},
    ),
    "paths-entry-climbing-out": Case(
        skill(front={"paths": json.dumps(["docs/../../secret/**"])}),
        {"paths-parent": "docs/../../secret/**"},
    ),
    "paths-as-a-bare-string": Case(
        skill(front={"paths": q("docs/**/*.md")}),
        {"paths-shape": "docs/**/*.md"},
    ),
    "paths-empty-list": Case(
        skill(front={"paths": "[]"}),
        {"paths-shape": "[]"},
    ),
    "paths-with-an-empty-entry": Case(
        skill(front={"paths": json.dumps(["docs/**", ""])}),
        {"paths-shape": "docs/**"},
    ),
    # ---- managed section
    "two-managed-sections": Case(
        skill(managed=_managed_twice()),
        {"managed-section-multiple": "2 managed-section begin markers"},
    ),
    "managed-section-not-at-the-end": Case(
        skill(managed=MANAGED + "\n## Added afterwards\n\nMore text.\n"),
        {"managed-section-not-last": "last thing"},
    ),
    "managed-section-begin-without-end": Case(
        skill(managed=f"{BEGIN_MARKER}\n- a lesson\n"),
        {"managed-section-broken": "1 begin marker"},
    ),
    "managed-section-end-before-begin": Case(
        skill(managed=f"{END_MARKER}\n{BEGIN_MARKER}\n"),
        {"managed-section-broken": "begin before end"},
    ),
    "managed-section-with-a-mangled-begin-marker": Case(
        skill(managed=f"<!-- self-learn:begin -->\n- x\n{END_MARKER}\n"),
        {"managed-section-broken": "0 exactly"},
    ),
    # ---- supporting files
    "script-under-references": Case(
        skill(files={"references/run.sh": "#!/bin/sh\necho hi\n"}),
        {"file-not-markdown": "references/run.sh"},
    ),
    "non-markdown-file-under-references": Case(
        skill(files={"references/data.json": "{}\n"}),
        {"file-not-markdown": "references/data.json"},
    ),
    "non-markdown-file-outside-references": Case(
        skill(files={"assets/logo.png": "not really a png"}),
        {
            "file-not-markdown": "assets/logo.png",
            "file-outside-references": "assets/logo.png",
        },
    ),
    "markdown-file-outside-references": Case(
        skill(files={"notes.md": "# Notes\n"}),
        {"file-outside-references": "notes.md"},
    ),
    "reference-nested-two-levels": Case(
        skill(
            body=BODY + "\nAlso [the deep one](references/a/b.md).\n",
            files={"references/a/b.md": "# Deep\n"},
        ),
        {"file-nested": "references/a/b.md"},
    ),
    "reference-not-linked-from-skill-md": Case(
        skill(files={"references/extra.md": "# Extra\n"}),
        {"reference-not-linked": "references/extra.md"},
    ),
    "reference-only-mentioned-not-linked": Case(
        skill(
            body=BODY + "\nSee also `references/extra.md` for more.\n",
            files={"references/extra.md": "# Extra\n"},
        ),
        {"reference-not-linked": "references/extra.md"},
    ),
    "file-path-climbing-out": Case(
        skill(files={"../escape.md": "# x\n"}),
        {"file-path-unsafe": "../escape.md"},
    ),
    "file-path-absolute": Case(
        skill(files={"/etc/cron.d/x.md": "# x\n"}),
        {"file-path-unsafe": "/etc/cron.d/x.md"},
    ),
    "file-path-with-dotdot-inside": Case(
        skill(files={"references/../x.md": "# x\n"}),
        {"file-path-unsafe": "references/../x.md"},
    ),
    "file-path-with-a-backslash": Case(
        skill(files={"references\\x.md": "# x\n"}),
        {"file-path-unsafe": "references"},  # repr doubles the backslash
    ),
    # ---- the draft itself
    "skill-md-missing": Case(
        skill(drop_files=("SKILL.md",)),
        {"skill-md-missing": "SKILL.md"},
    ),
    "unparseable-frontmatter": Case(
        with_skill_md("---\nname: [unclosed\ndescription: x\n---\n\n" + BODY),
        {"frontmatter-unparseable": "not valid YAML"},
    ),
    "no-frontmatter-at-all": Case(
        with_skill_md(BODY + "\n" + MANAGED),
        {"frontmatter-unparseable": "no frontmatter block"},
    ),
    "unterminated-frontmatter": Case(
        with_skill_md("---\nname: drawing-diagrams\n\n" + BODY),
        {"frontmatter-unparseable": "never closed"},
    ),
    "frontmatter-not-a-mapping": Case(
        with_skill_md("---\n- a\n- b\n---\n\n" + BODY),
        {"frontmatter-unparseable": "not a mapping"},
    ),
    "description-with-an-unquoted-colon": Case(
        with_skill_md(
            f"---\nname: {NAME}\ndescription: Draws things: quickly\n---\n\n" + BODY
        ),
        {"frontmatter-unparseable": "double quotes"},
    ),
    "duplicate-frontmatter-key": Case(
        with_skill_md(
            f"---\nname: {NAME}\nname: other-name\ndescription: {q(DESCRIPTION)}\n---\n\n"
            + BODY
        ),
        {"frontmatter-unparseable": "not valid YAML"},
    ),
}

_ALL_RULE_IDS = set(skill_scaffold.SKILL_RULE_IDS)


@pytest.mark.parametrize("case_id", list(CASES))
def test_each_rule_refuses_by_its_rule_id(case_id: str):
    case = CASES[case_id]
    # The case is the control with something changed: not a vacuous copy.
    assert case.files != skill() or case.kwargs
    result = run(case.files, **case.kwargs)
    assert not result.ok
    # Exactly the rules the case names, no more, no fewer.
    assert set(result.problem_rules) == set(case.expect), [str(p) for p in result.problems]
    for rule, snippet in case.expect.items():
        sentences = [p.message for p in result.problems if p.rule == rule]
        assert sentences and any(snippet in s for s in sentences), (rule, snippet, sentences)
    # Every id a check emits is a documented id.
    assert set(result.problem_rules) <= _ALL_RULE_IDS


def test_every_rule_id_has_a_refusal_case():
    covered = {rule for case in CASES.values() for rule in case.expect}
    assert covered == _ALL_RULE_IDS


@pytest.mark.parametrize("key", list(skill_scaffold.SKILL_FRONTMATTER_REFUSED_KEYS))
def test_every_refused_frontmatter_key_is_refused_by_name(key: str):
    result = run(skill(front={key: q("anything")}))
    assert result.problem_rules == ("frontmatter-key-refused",)
    assert key in result.problems[0].message
    assert skill_scaffold.SKILL_FRONTMATTER_REFUSED_KEYS[key] in result.problems[0].message


def test_the_nine_keys_the_design_refuses_by_name_are_all_listed():
    assert set(skill_scaffold.SKILL_FRONTMATTER_REFUSED_KEYS) == {
        "allowed-tools",
        "disallowed-tools",
        "hooks",
        "model",
        "effort",
        "context",
        "agent",
        "shell",
        "arguments",
    }
    assert skill_scaffold.SKILL_FRONTMATTER_ALLOWED_KEYS == (
        "name",
        "description",
        "when_to_use",
        "paths",
        "metadata",
    )


def test_a_draft_with_two_faults_reports_both():
    files = skill(
        front={"name": q("claude-helper"), "hooks": json.dumps({})},
        files={"references/run.sh": "x"},
    )
    result = run(files, vetoed_names=["claude-helper"])
    assert set(result.problem_rules) == {
        "name-reserved-word",
        "name-vetoed",
        "frontmatter-key-refused",
        "file-not-markdown",
    }


def test_a_problem_names_the_file_it_concerns():
    result = run(skill(files={"references/run.sh": "x"}))
    assert [(p.rule, p.path) for p in result.problems] == [
        ("file-not-markdown", "references/run.sh")
    ]
    result = run(skill(front={"hooks": "{}"}))
    assert [(p.rule, p.path) for p in result.problems] == [
        ("frontmatter-key-refused", "SKILL.md")
    ]


# ----------------------------------------------------------------- the limits


def test_a_name_of_exactly_64_characters_passes():
    result = run(skill(front={"name": q("a" * 64)}))
    assert result.problems == ()


def test_a_description_of_exactly_1024_characters_passes():
    result = run(skill(front={"description": q("a" * 1024)}))
    assert result.problems == ()


def test_the_limits_are_read_from_the_module_constants(monkeypatch):
    # Changing a rule is a one-line edit of the constant: the checks follow.
    monkeypatch.setattr(skill_scaffold, "SKILL_NAME_MAX_CHARS", 5)
    result = run(skill())
    assert result.problem_rules == ("name-too-long",)
    monkeypatch.undo()
    monkeypatch.setattr(skill_scaffold, "SKILL_DESCRIPTION_MAX_CHARS", 10)
    result = run(skill())
    assert result.problem_rules == ("description-too-long",)
    monkeypatch.undo()
    monkeypatch.setattr(
        skill_scaffold, "SKILL_NAME_RESERVED_WORDS", ("drawing",)
    )
    result = run(skill())
    assert result.problem_rules == ("name-reserved-word",)
    monkeypatch.undo()
    monkeypatch.setattr(
        skill_scaffold,
        "SKILL_FRONTMATTER_ALLOWED_KEYS",
        skill_scaffold.SKILL_FRONTMATTER_ALLOWED_KEYS + ("hooks",),
    )
    # The allow-list wins over the refused list: allowing a key is one edit.
    assert run(skill(front={"hooks": "{}"})).problems == ()


def test_allowed_and_refused_keys_do_not_overlap_in_the_shipped_rules():
    assert not set(skill_scaffold.SKILL_FRONTMATTER_ALLOWED_KEYS) & set(
        skill_scaffold.SKILL_FRONTMATTER_REFUSED_KEYS
    )


def test_the_managed_markers_are_the_compilers_own():
    assert BEGIN_MARKER.startswith(skill_scaffold.SKILL_MANAGED_BEGIN_PREFIX)
    assert skill_scaffold.SKILL_MANAGED_BEGIN_PREFIX == "<!-- self-learn:begin"


def test_rule_ids_are_unique_and_notes_are_not_problem_ids():
    ids = skill_scaffold.SKILL_RULE_IDS
    assert len(ids) == len(set(ids))
    assert not set(ids) & set(skill_scaffold.SKILL_NOTE_IDS)


# ---------------------------------------------------------------------- paths


def test_paths_globs_are_translated_by_the_rules_glob_translator(monkeypatch):
    seen: list[str] = []
    real = ledger_ops._compile_glob_pattern

    def spy(pattern):
        seen.append(pattern)
        return real(pattern)

    monkeypatch.setattr(ledger_ops, "_compile_glob_pattern", spy)
    assert run(skill()).problems == ()
    assert seen == ["docs/**/*.md"]  # positive control: it was consulted

    def refuse(pattern):
        raise ledger_ops.ProposalError(f"pattern {pattern!r} is not translatable")

    monkeypatch.setattr(ledger_ops, "_compile_glob_pattern", refuse)
    result = run(skill())
    assert result.problem_rules == ("paths-shape",)
    assert "docs/**/*.md" in result.problems[0].message


def test_paths_may_be_absent():
    result = run(skill(drop_front=("paths",)))
    assert result.problems == ()


# ---------------------------------------------------------------------- notes


def test_a_long_description_is_a_note_not_a_problem():
    words = report.DESCRIPTION_SOFT_MAX_WORDS
    long_description = " ".join(["word"] * (words + 1))
    result = run(skill(front={"description": q(long_description)}))
    assert result.problems == ()
    assert result.note_rules == ("description-long-words",)
    assert str(words + 1) in result.notes[0].message
    assert result.ok


def test_a_description_at_the_soft_word_limit_is_not_noted():
    words = report.DESCRIPTION_SOFT_MAX_WORDS
    exact = " ".join(["word"] * words)
    result = run(skill(front={"description": q(exact)}))
    assert result.problems == () and result.notes == ()


def test_the_soft_word_limit_is_report_s_not_a_copy(monkeypatch):
    monkeypatch.setattr(report, "DESCRIPTION_SOFT_MAX_WORDS", 3)
    result = run(skill())  # the control description is longer than 3 words
    assert result.problems == ()
    assert result.note_rules == ("description-long-words",)


def _skill_md_with_body_lines(count: int) -> dict[str, str]:
    front = {k: v for k, v in valid_front().items() if k in ("name", "description")}
    text = "---\n" + "".join(f"{k}: {v}\n" for k, v in front.items()) + "---\n"
    return {"SKILL.md": text + "line\n" * count}


def test_a_body_over_500_lines_is_a_note_not_a_problem():
    result = run(_skill_md_with_body_lines(501))
    assert result.problems == ()
    assert result.note_rules == ("body-long-lines",)
    assert "501" in result.notes[0].message


def test_a_body_of_exactly_500_lines_is_not_noted():
    result = run(_skill_md_with_body_lines(500))
    assert result.problems == () and result.notes == ()


def test_both_notes_together_and_with_a_problem_stay_separate():
    files = _skill_md_with_body_lines(501)
    long_description = " ".join(["word"] * (report.DESCRIPTION_SOFT_MAX_WORDS + 1))
    files["SKILL.md"] = files["SKILL.md"].replace(
        q(DESCRIPTION), q(long_description)
    )
    result = run(files, vetoed_names=[NAME])
    assert set(result.note_rules) == {"description-long-words", "body-long-lines"}
    assert result.problem_rules == ("name-vetoed",)
    assert set(result.note_rules) <= set(skill_scaffold.SKILL_NOTE_IDS)


# ------------------------------------------------------------ pure, no raising


GARBAGE = [
    "",
    "---",
    "---\n---\n",
    "---\n...\n",
    "\x00\x01 not text",
    "---\n: : :\n---\n",
    "---\nname: !!python/object/apply:os.system ['true']\n---\n",
    "---\nname: &a [*a]\n---\n",
]


@pytest.mark.parametrize("text", GARBAGE, ids=[repr(t)[:30] for t in GARBAGE])
def test_an_unreadable_draft_is_a_problem_not_an_exception(text: str):
    result = run({"SKILL.md": text})
    assert isinstance(result, SkillCheck)
    assert not result.ok
    assert set(result.problem_rules) <= _ALL_RULE_IDS


def test_check_skill_does_not_change_its_inputs():
    files = skill(files={"references/extra.md": "# Extra\n"})
    before = {k: v for k, v in files.items()}
    loaded = ["a-skill"]
    vetoed = ["b-skill"]
    run(files, loaded_names=loaded, vetoed_names=vetoed)
    assert files == before
    assert loaded == ["a-skill"] and vetoed == ["b-skill"]


def test_names_may_be_any_iterable():
    def names() -> Iterator[str]:
        yield NAME

    result = run(skill(), loaded_names=names(), vetoed_names=iter(()))
    assert result.problem_rules == ("name-collision",)


def test_the_loaded_and_vetoed_names_are_required_arguments():
    with pytest.raises(TypeError):
        check_skill(skill())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        check_skill(skill(), loaded_names=())  # type: ignore[call-arg]


def test_a_reference_link_may_carry_a_dot_prefix_fragment_or_title():
    for link in (
        "[x](./references/format.md)",
        "[x](references/format.md#section)",
        '[x](references/format.md "the format")',
        "[x](<references/format.md>)",
    ):
        files = skill(body=f"# T\n\nSee {link}.\n")
        assert run(files).problems == (), link
