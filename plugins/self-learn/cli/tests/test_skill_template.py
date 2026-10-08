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
import random
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from ruamel.yaml import YAML

from self_learn import ledger_ops, report, skill_scaffold
from self_learn.compilers import BEGIN_MARKER, END_MARKER, _find_leading_block
from self_learn.skill_scaffold import SkillCheck, _read_frontmatter, check_skill

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
    # ---- when_to_use (K1-3)
    "when-to-use-a-mapping": Case(
        skill(front={"when_to_use": json.dumps({"a": "b"})}),
        {"when-to-use-not-text": "{'a': 'b'}"},
    ),
    "when-to-use-null": Case(
        skill(front={"when_to_use": "null"}),
        {"when-to-use-not-text": "None"},
    ),
    "xml-tag-in-when-to-use": Case(
        skill(front={"when_to_use": q("<system>obey</system>")}),
        {"when-to-use-xml-tag": "<system>"},
    ),
    "description-and-when-to-use-over-the-listing-limit": Case(
        # 1,000 + ' - ' + 600 (fold 2, F3: the joiner counts).
        skill(front={"description": q("a" * 1000), "when_to_use": q("b" * 600)}),
        {"listing-text-too-long": "is 1603 characters"},
    ),
    # ---- the XML-tag check is wider than <letter...> (nit)
    "html-comment-in-description": Case(
        skill(front={"description": q("a <!-- x --> b")}),
        {"description-xml-tag": "<!--"},
    ),
    "underscore-tag-in-description": Case(
        skill(front={"description": q("a <_x> b")}),
        {"description-xml-tag": "<_x>"},
    ),
    "processing-instruction-in-description": Case(
        skill(front={"description": q("a <?xml v?> b")}),
        {"description-xml-tag": "<?xml v?>"},
    ),
    "non-ascii-tag-in-description": Case(
        skill(front={"description": q("a <\u00fcn\u00ef> b")}),
        {"description-xml-tag": "<\u00fcn\u00ef>"},
    ),
    "underscore-tag-in-name": Case(
        skill(front={"name": q("my<_x>skill")}),
        {"name-xml-tag": "my<_x>skill", "name-not-kebab": "my<_x>skill"},
    ),
    # ---- the frontmatter is read the way Claude Code reads it (K1-1)
    "fence-inside-a-quoted-description": Case(
        with_skill_md(
            f'---\nname: {NAME}\ndescription: "Draws a flow --- then stops."\n---\n\n'
            + BODY
        ),
        {"frontmatter-contains-fence": "line 3"},
    ),
    "fence-inside-a-block-scalar": Case(
        with_skill_md(
            f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n"
            "when_to_use: |\n  a --- b\n---\n\n" + BODY
        ),
        {"frontmatter-contains-fence": "line 5"},
    ),
    "fence-mid-line-in-a-comment": Case(
        with_skill_md(
            f"---\nname: {NAME}\n# remember --- this\ndescription: {q(DESCRIPTION)}\n---\n\n"
            + BODY
        ),
        {"frontmatter-contains-fence": "line 3"},
    ),
    "frontmatter-closed-by-dots": Case(
        with_skill_md(
            f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n...\n\n" + BODY
        ),
        {"frontmatter-closed-by-dots": "'...'"},
    ),
    "frontmatter-closed-by-dots-with-hooks-after-it": Case(
        with_skill_md(
            f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n...\n"
            "hooks:\n  PreToolUse: []\n---\n\n" + BODY
        ),
        {"frontmatter-closed-by-dots": "'...'"},
    ),
    # ---- anchors and aliases (K1-2)
    "anchor-and-alias-in-frontmatter": Case(
        with_skill_md(
            f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n"
            "metadata: &m {owner: a}\nwhen_to_use: *m\n---\n\n" + BODY
        ),
        {"frontmatter-anchor-alias": "anchor or alias"},
    ),
    "anchor-on-a-scalar": Case(
        with_skill_md(
            f"---\nname: &n {NAME}\ndescription: {q(DESCRIPTION)}\n---\n\n" + BODY
        ),
        {"frontmatter-anchor-alias": "anchor or alias"},
    ),
    "merge-key-from-an-anchor": Case(
        with_skill_md(
            f"---\nbase: &b {{hooks: x}}\nname: {NAME}\n"
            f"description: {q(DESCRIPTION)}\n<<: *b\n---\n\n" + BODY
        ),
        {"frontmatter-anchor-alias": "anchor or alias"},
    ),
    # ---- fence lines and line-break characters, both readers (fold 2, F2)
    "opening-fence-ending-in-a-lone-carriage-return": Case(
        with_skill_md(skill()["SKILL.md"].replace("---\n", "---\r", 1)),
        {"frontmatter-fence-line": "opening"},
    ),
    "next-line-character-inside-a-plain-value": Case(
        with_skill_md(
            f"---\nname: {NAME}\ndescription: Draws a\x85diagram.\n---\n\n" + BODY
        ),
        {"frontmatter-forbidden-character": "U+0085 on line 3"},
    ),
    # ---- the caps checked before any YAML parse (fold 2, F1)
    "frontmatter-over-the-size-cap": Case(
        skill(front={"metadata": json.dumps({"note": "x" * 4100})}),
        {"frontmatter-too-long": "the limit is 4096"},
    ),
    "frontmatter-flow-nesting-over-the-cap": Case(
        # 33 nested mappings, plus the control's one '[' in paths.
        skill(front={"metadata": "{a: " * 33 + "b" + "}" * 33}),
        {"frontmatter-flow-too-deep": "has 34 '['"},
    ),
    # ---- files that are not text (K1-2)
    "file-key-not-text": Case(
        {**skill(), 5: "x"},  # type: ignore[dict-item]
        {"file-key-not-text": "5"},
    ),
    "skill-md-is-bytes": Case(
        {**skill(), "SKILL.md": skill()["SKILL.md"].encode()},  # type: ignore[dict-item]
        {"file-not-text": "bytes"},
    ),
    "reference-is-none": Case(
        {**skill(), REFERENCE: None},  # type: ignore[dict-item]
        {"file-not-text": "NoneType"},
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
    # Every id a check emits is a documented id, and no sentence is huge.
    assert set(result.problem_rules) <= _ALL_RULE_IDS
    assert all(len(p.message) < 700 for p in result.problems)


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


# ============================================================ fold round (K1a)
# The blind gate's three risks (K1-1 frontmatter as Claude Code reads it,
# K1-2 never raise, K1-3 when_to_use) and its nits.

# ------------------------------------------- K1-1: the frontmatter, both readers

#: JavaScript's ``\s`` (ECMA-262 WhiteSpace and LineTerminator), written
#: out: Python's ``\s`` is a different set (it has ``\x1c``-``\x1f`` and
#: U+0085, and lacks U+FEFF), so the port never uses it (fold 2, F2).
JS_WHITESPACE = (
    r"[\t\n\x0b\x0c\r \xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
)

#: Claude Code 2.1.293's frontmatter match, ported (its source is
#: ``/^---\s*\n([\s\S]*?)---\s*\n?/``, after stripping a BOM, and only when
#: ``text.indexOf("---", 3) >= 0``). The first ``---`` anywhere after the
#: opening line ends the block; ``...`` never does.
CLAUDE_CODE_FRONTMATTER_RE = re.compile(
    f"---{JS_WHITESPACE}*\n(.*?)---{JS_WHITESPACE}*\n?", re.DOTALL
)


def claude_code_block(text: str) -> str | None:
    text = text[1:] if text.startswith("\ufeff") else text
    if text.find("---", 3) < 0:
        return None
    match = CLAUDE_CODE_FRONTMATTER_RE.match(text)
    return match.group(1) if match else None


def _without_leading_blank_lines(text: str) -> str:
    """``text`` (the inner text K1a parsed) as Claude Code captures it. The
    opener's ``\\s*`` runs as far as it can and then needs a ``\\n``, so it
    also swallows every leading line of the inner text made only of
    (JavaScript) whitespace; the compilers' reader keeps those lines. YAML
    reads them as blank (a line ruamel would not read as blank is refused
    as unparseable), and the tests compare the loaded mappings too."""
    lead = re.match(f"{JS_WHITESPACE}*", text)
    assert lead is not None
    return text[lead.group(0).rfind("\n") + 1 :]


def _valid_drafts() -> dict[str, str]:
    """Every shape of valid SKILL.md this file relies on."""
    front = valid_front()
    no_when = {k: v for k, v in front.items() if k != "when_to_use"}
    drafts = {
        "control": skill()["SKILL.md"],
        "no managed section": skill(managed="")["SKILL.md"],
        "no optional keys": render_skill_md(
            {"name": front["name"], "description": front["description"]}
        ),
        "with when_to_use": render_skill_md({**front, "when_to_use": q("When asked.")}),
        "name of 64": skill(front={"name": q("a" * 64)})["SKILL.md"],
        "description of 1024": skill(front={"description": q("a" * 1024)})["SKILL.md"],
        "empty metadata": skill(front={"metadata": ""})["SKILL.md"],
        "no paths": skill(drop_front=("paths",))["SKILL.md"],
        "CRLF line endings": skill()["SKILL.md"].replace("\n", "\r\n"),
        "trailing space on the fences": skill()["SKILL.md"]
        .replace("---\n", "--- \n", 1)
        .replace("\n---\n", "\n---  \n", 1),
        "blank lines first": "---\n\n\n" + skill()["SKILL.md"][4:],
        "comment lines": render_skill_md(no_when).replace(
            "---\nname", "---\n# a comment\nname", 1
        ),
        "dashes and dots inside values": skill(
            front={"description": q("Draws -- and - and ... and -.- too.")}
        )["SKILL.md"],
        "folded description": skill(
            front={"description": ">\n  Draws a diagram when asked.\n  Use it for flows."}
        )["SKILL.md"],
        "block scalar when_to_use": skill(
            front={"when_to_use": "|\n  Asked for a diagram.\n  Asked for a flow."}
        )["SKILL.md"],
        "indented dots in a block scalar": skill(
            front={"when_to_use": "|\n  first\n  ...\n  last"}
        )["SKILL.md"],
        # Fold 2 (F2), CONTROLS that pass on c7fd5f8 too: a first line that
        # is only a BOM (JavaScript's \s has U+FEFF, Python's does not;
        # ruamel skips it; the old oracle's blank-line rule did not strip
        # it), CRLF with padding on both fences, and an ideographic space
        # inside a value (an ordinary character in CJK text, not a refused
        # one).
        "a BOM-only first line": "---\n\ufeff\n" + skill()["SKILL.md"][4:],
        "CRLF with padded fences": skill()["SKILL.md"]
        .replace("\n", "\r\n")
        .replace("---\r\n", "--- \t\r\n", 2),
        "an ideographic space in a value": skill(
            front={"description": '"Draws\u3000diagrams when asked."'}
        )["SKILL.md"],
    }
    return drafts


VALID_DRAFTS = _valid_drafts()


@pytest.mark.parametrize("label", list(VALID_DRAFTS))
def test_claude_code_reads_exactly_the_block_that_k1a_parsed(label: str):
    assert VALID_DRAFTS["control"] == skill()["SKILL.md"]
    assert len(VALID_DRAFTS) >= 15
    text = VALID_DRAFTS[label]
    files = skill(files={"SKILL.md": text})
    # The draft is valid (a property over refused drafts would prove nothing).
    assert run(files).problems == (), label
    frontmatter = _read_frontmatter(text)
    assert frontmatter.inner is not None and frontmatter.mapping is not None
    captured = claude_code_block(text)
    assert captured is not None
    assert _without_leading_blank_lines(frontmatter.inner) == captured, label
    # ... and it reads to the same mapping.
    assert YAML(typ="safe").load(captured) in (frontmatter.mapping, None)


def test_the_two_readers_disagree_on_the_drafts_that_are_refused():
    # Scenario A: the fence inside a value. K1a's raw reader runs on; Claude
    # Code cuts the value mid-line.
    in_value = f'---\nname: {NAME}\ndescription: "Draws a flow --- then stops."\n---\n\n{BODY}'
    raw_inner, _ = _find_leading_block(in_value) or ("", 0)
    assert claude_code_block(in_value) != raw_inner
    assert run(skill(files={"SKILL.md": in_value})).problem_rules == (
        "frontmatter-contains-fence",
    )
    # Scenario B: closed by '...'. The compilers' reader stops there; Claude
    # Code reads on to the next '---'.
    dotted = f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n...\nhooks: x\n---\n\n{BODY}"
    raw_inner, _ = _find_leading_block(dotted) or ("", 0)
    assert claude_code_block(dotted) != raw_inner
    assert run(skill(files={"SKILL.md": dotted})).problem_rules == (
        "frontmatter-closed-by-dots",
    )


#: The 14 opening lines the 2026-10-08 gate found that the compilers' reader
#: takes as a fence and Claude Code does not (it needs a literal ``\n``
#: after ``---`` and JavaScript whitespace): ``---`` ended by a lone CR,
#: ``\x0b``, ``\x0c``, ``\x1c``-``\x1e``, U+0085, U+2028 or U+2029, or by
#: ``\x1c``-``\x1f`` or U+0085 and then a line feed (fold 2, F2).
GATE_OPENERS = [
    "---\r",
    "---\x0b",
    "---\x0c",
    "---\x1c",
    "---\x1d",
    "---\x1e",
    "---\x85",
    "---\u2028",
    "---\u2029",
    "---\x1c\n",
    "---\x1d\n",
    "---\x1e\n",
    "---\x1f\n",
    "---\x85\n",
]
#: Opening lines, each with its own line break.
_FUZZ_GOOD_OPENERS = ["---\n", "--- \n", "---\t\n", "---\r\n", "--- \t\r\n"]
_FUZZ_OTHER_OPENERS = ["---\xa0\n", "---\u3000\n", "----\n", "---x\n", "\ufeff---\n"]
_FUZZ_LINES = [
    "name: drawing-diagrams",
    'description: "Draws a diagram."',
    'when_to_use: "x"',
    "metadata:",
    "  owner: a",
    'paths: ["a/**"]',
    'description: "a --- b"',
    "---",
    "...",
    "",
    "   ",
    "  ---",
    "--- ",
    "# c --- d",
    "x: |",
    "  text --- more",
    "key: value ...",
    "---x",
    "a:---",
    "- ---",
    "  ...",
    "# ...",
    'q: "..."',
    "name: drawing-diagrams # --- ",
    # Fold 2 (F2): characters the two line readers treat differently, and
    # whitespace-only lines the opener's \s*\n swallows.
    "x: a\x85b",
    "x: a\u2028b",
    "x: a\rb",
    "x: a\x0bb",
    "x: a\x1fb",
    "\ufeff",
    "\u3000",
    "  ",
]
#: Closing lines, each with its own line break (or none: the text ends).
_FUZZ_CLOSERS = [
    "---\n",
    "--- \n",
    "...\n",
    "---  \n",
    "  ---\n",
    "----\n",
    "-- -\n",
    "... \n",
    "--- #\n",
    "---\r\n",
    "--- \t\r\n",
    "---",
    "---\xa0\n",
    "---\u3000\n",
    "---\x85\n",
    "---\x1f\n",
    "---\r",
]
_FUZZ_BODIES = ["", "# T\n", "hooks:\n---\n", "...\n", "x --- y\n", "a\x85b\n"]

#: The refusals that are about how the block is read, not what is in it.
_READING_RULES = (
    "frontmatter-fence-line",
    "frontmatter-forbidden-character",
    "frontmatter-closed-by-dots",
    "frontmatter-contains-fence",
)


def test_whatever_k1a_accepts_reads_identically_in_claude_code():
    """The property, over a seeded sweep of tricky frontmatters: if K1a
    accepts a draft, Claude Code's reader (the JavaScript port above)
    captures exactly the inner text K1a parsed, less the leading blank lines
    its opener swallows, and it loads to the same mapping; and every draft
    that opens with one of the gate's 14 lines is refused. The positive
    controls make the sweep mean something: many drafts are accepted, many
    differ between the compilers' reader and Claude Code's, every one of
    those is refused, and each of the 14 openers was tried."""
    rng = random.Random(20261008)
    accepted = diverging = diverging_and_refused = refused_by_reading_rules = 0
    gate_openers_tried: set[str] = set()
    for _ in range(4000):
        if rng.random() < 0.5:
            opener = rng.choice(_FUZZ_GOOD_OPENERS)
        else:
            opener = rng.choice(GATE_OPENERS + _FUZZ_OTHER_OPENERS)
        eol = rng.choice(["\n", "\n", "\r\n"])
        lines = [rng.choice(_FUZZ_LINES) for _ in range(rng.randint(0, 6))]
        if opener == "---\r" and lines[:1] == [""] and eol == "\n":
            # '---\r' then an empty line is a CRLF opener, not the gate's.
            lines[0] = "name: drawing-diagrams"
        text = (
            opener
            + "".join(f"{ln}{eol}" for ln in lines)
            + rng.choice(_FUZZ_CLOSERS)
            + rng.choice(_FUZZ_BODIES)
        )
        frontmatter = _read_frontmatter(text)
        try:
            raw = _find_leading_block(text)
        except Exception:
            raw = None
        captured = claude_code_block(text)
        differs = raw is not None and (
            captured is None or _without_leading_blank_lines(raw[0]) != captured
        )
        if frontmatter.finding is None:
            accepted += 1
            assert frontmatter.inner is not None and captured is not None, repr(text)
            assert _without_leading_blank_lines(frontmatter.inner) == captured, repr(text)
            assert YAML(typ="safe").load(captured) in (frontmatter.mapping, None), repr(text)
        if opener in GATE_OPENERS:
            gate_openers_tried.add(opener)
            assert frontmatter.finding is not None, repr(text)
            assert frontmatter.finding.rule == "frontmatter-fence-line", repr(text)
        if differs:
            diverging += 1
            if frontmatter.finding is not None:
                diverging_and_refused += 1
        if frontmatter.finding is not None and frontmatter.finding.rule in _READING_RULES:
            refused_by_reading_rules += 1
    assert accepted > 100, accepted
    assert diverging > 100, diverging
    assert diverging_and_refused == diverging  # no divergence is accepted
    assert refused_by_reading_rules > 100
    assert gate_openers_tried == set(GATE_OPENERS)


def test_the_javascript_port_is_not_pythons_whitespace():
    # The oracle's own control (it tests the test, so it passes on any
    # product code): on the gate's openers Python's \s regex (the fold's old
    # oracle) finds a block, the JavaScript port does not.
    pythons = re.compile(r"^---\s*\n([\s\S]*?)---\s*\n?")
    for opener in ("---\x1c\n", "---\x85\n", "---\x1f\n"):
        text = opener + f"name: {NAME}\n---\n"
        assert pythons.match(text) is not None, repr(opener)
        assert claude_code_block(text) is None, repr(opener)
    # ... and on U+FEFF the other way round.
    text = "---\ufeff\nname: x\n---\n"
    assert pythons.match(text) is None
    assert claude_code_block(text) == "name: x\n"


# ----------------------------------------------- K1-2: never raise, bounded

def alias_bomb_files(levels: int = 8, where: str = "name") -> dict[str, str]:
    """The gate's draft: nested YAML aliases, 10 references per level."""
    lines = ['l0: &l0 ["x","x","x","x","x","x","x","x","x","x"]']
    for i in range(1, levels):
        lines.append(f"l{i}: &l{i} [" + ",".join([f"*l{i - 1}"] * 10) + "]")
    top = f"*l{levels - 1}"
    desc = f"description: {q(DESCRIPTION)}"
    if where == "name":
        lines.append(f"name: {top}\n{desc}")
    elif where == "paths":
        lines.append(f"name: {NAME}\n{desc}\npaths: {top}")
    else:
        lines.append(f"name: {NAME}\n{desc}\nmetadata: {top}")
    return skill(files={"SKILL.md": "---\n" + "\n".join(lines) + "\n---\n\n" + BODY})


@pytest.mark.parametrize("levels", [9, 12])
@pytest.mark.parametrize("where", ["name", "paths", "metadata"])
def test_the_alias_bomb_draft_returns_a_problem_quickly(where: str, levels: int):
    # Nine levels is the gate's draft: about half a kilobyte of frontmatter,
    # and before the fold a MemoryError after 14 s under a 3 GB cap (eight
    # levels took 2.7 s, seven 0.3 s). NEVER run this test against the code
    # from before the anchor rule without a memory cap.
    files = alias_bomb_files(levels, where)
    front_bytes = len(files["SKILL.md"].split("\n---\n")[0].encode())
    assert front_bytes < 900, front_bytes  # a tiny draft
    started = time.perf_counter()
    result = run(files)
    elapsed = time.perf_counter() - started
    assert result.problem_rules == ("frontmatter-anchor-alias",)
    # Measured idle (2026-10-08, this file's fold 2): at most 0.4 ms, since
    # the anchor pass stops at the first anchor. The bound is over 2,000
    # times that, so only a return of the blow-up can fail it.
    assert elapsed < 1.0, elapsed


def test_an_anchor_is_found_by_the_parsers_events_not_by_matching_text():
    # '&' and '*' inside a quoted value are not anchors or aliases.
    text = render_skill_md(
        {**valid_front(), "description": q("Fish & chips *and* peas &c.")}
    )
    assert run(skill(files={"SKILL.md": text})).problems == ()
    # A real anchor with no alias at all is still refused.
    anchored = f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\nx: &a 1\n---\n\n{BODY}"
    assert run(skill(files={"SKILL.md": anchored})).problem_rules == (
        "frontmatter-anchor-alias",
    )


def test_shown_is_bounded_and_never_raises():
    shown = skill_scaffold._shown
    assert len(shown("A" * 1_000_000)) <= 100
    nested: object = "x"
    for _ in range(500):
        nested = [nested]
    assert len(shown(nested)) <= 100
    recursive: list = []
    recursive.append(recursive)
    assert len(shown(recursive)) <= 100
    assert len(shown({i: i for i in range(10_000)})) <= 150
    # An integer too long to print does not raise either.
    assert len(shown(10**5000)) <= 100
    # An ordinary value is shown whole.
    assert shown("drawing-diagrams") == "'drawing-diagrams'"


def test_shown_falls_back_to_the_type_when_the_repr_itself_fails(monkeypatch):
    def boom(value):
        raise RuntimeError("no repr for you")

    monkeypatch.setattr(skill_scaffold._BOUNDED_REPR, "repr", boom)
    assert skill_scaffold._shown(10) == "<int>"
    assert skill_scaffold._shown("x") == "<str>"


#: The rule a frontmatter over a cap is refused by, before any parse.
_CAP_RULES = frozenset({"frontmatter-too-long", "frontmatter-flow-too-deep"})


def _hostile_drafts() -> dict[str, tuple[dict, frozenset[str]]]:
    """Each hostile draft and exactly the rules it is refused by (fold 2,
    F4: the rule id is asserted, not the time). The frontmatter ones are
    refused by a cap before any parse; the body ones by the unlinked
    reference (the body that linked it was replaced)."""
    nested_name = "[" * 400 + "]" * 400
    many_absolute = json.dumps([f"/abs/{i}" for i in range(3000)])
    many_keys = "".join(f"k{i}: 1\n" for i in range(3000))
    too_long = frozenset({"frontmatter-too-long"})
    unlinked = frozenset({"reference-not-linked"})
    return {
        "huge name": (skill(front={"name": q("A" * 1_000_000)}), too_long),
        "huge description": (skill(front={"description": q("a" * 1_000_000)}), too_long),
        "huge when_to_use": (skill(front={"when_to_use": q("w" * 1_000_000)}), too_long),
        "huge unquoted tag": (
            skill(front={"description": q("<" + "a" * 200_000 + ">")}),
            too_long,
        ),
        "deeply nested name": (
            skill(front={"name": nested_name}),
            frozenset({"frontmatter-flow-too-deep"}),
        ),
        "four thousand digit name": (skill(front={"name": "9" * 4000}), too_long),
        "five thousand digit name": (skill(front={"name": "9" * 5000}), too_long),
        "three thousand absolute paths": (skill(front={"paths": many_absolute}), too_long),
        "three thousand unknown keys": (
            with_skill_md(
                f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n{many_keys}---\n\n{BODY}"
            ),
            too_long,
        ),
        # PINS, not new behaviour: "huge file key" and the three body cases
        # ("unclosed ...") already passed on 02a9a5c, the code before the
        # first fold. They guard against a regression.
        "huge file key": (
            skill(files={"r" * 200_000: "x"}),
            frozenset({"file-outside-references", "file-not-markdown"}),
        ),
        # Under references/, so the "not linked" sentence is reached (fold 2,
        # nit: it used to print the whole path).
        "huge reference key": (
            skill(files={f"references/{'a' * 200_000}.md": "x"}),
            unlinked,
        ),
        "huge unknown key": (skill(front={"k" * 200_000: "1"}), too_long),
        "unclosed links": (skill(body="[a](<" * 12_000), unlinked),
        "unclosed brackets": (skill(body="[" * 50_000), unlinked),
        "unclosed definitions": (skill(body="[x]: <\n" * 20_000), unlinked),
    }


@pytest.mark.parametrize("label", list(_hostile_drafts()))
def test_a_hostile_draft_is_a_bounded_problem_not_an_exception(label: str, monkeypatch):
    files, expected = _hostile_drafts()[label]
    if expected <= _CAP_RULES:
        # Refused before any parse: the YAML stand-in is never made.
        monkeypatch.setattr(skill_scaffold, "YAML", _NoYaml)
        _NoYaml.made.clear()
    result = run(files)
    assert isinstance(result, SkillCheck)
    assert set(result.problem_rules) == expected, [str(p) for p in result.problems]
    if expected <= _CAP_RULES:
        assert _NoYaml.made == []
    # Every sentence is short, however large the offending value was.
    assert all(len(p.message) < 800 for p in result.problems + result.notes)


@pytest.mark.parametrize(
    ("body", "bound"),
    [
        # Few starts and a long tail: an unbounded run rescans the tail from
        # every start, while the bounded pattern reads 999 characters.
        ("[a](<" * 2_000 + "b" * 500_000, 1.0),
        ("[x]: <\n" * 20_000, 1.0),
        ("[" * 150_000, 1.0),
        ("[a][" * 30_000, 1.0),
        # With a definition present the reference-style patterns run too.
        ("[d]: references/format.md\n" + "[" * 150_000, 12.0),
    ],
    ids=[
        "unclosed-angle-links",
        "unclosed-definitions",
        "unclosed-brackets",
        "unclosed-refs",
        "unclosed-brackets-after-a-definition",
    ],
)
def test_the_link_patterns_do_not_rescan_the_file_from_every_bracket(body: str, bound: float):
    # An unbounded run (`<([^>]*)>`) rescans the rest of the text from every
    # `[a](<`: 7 s on 50 KB before the fold; bounded, a fraction of a second.
    # The body is not frontmatter, so no cap applies and no rule id can
    # stand in for the time. Measured idle (2026-10-08, fold 2, best of 5
    # or 7): angle links 0.059 s, definitions 0.008 s, brackets 0.084 s,
    # refs 0.001 s, brackets after a definition 1.08 s. Each bound is at
    # least 10 times its case's idle time, and never under 1 s. An
    # unbounded run is far slower on these shapes: the angle-link mutant
    # took 5.4 s (92 times idle; on the old shape, '[a](<' x 15,000, it was
    # only 8 times, so no 10x bound could catch it), an unbounded shortcut
    # label 37 s after a definition, and on 02a9a5c, before the fold
    # bounded the patterns, brackets took 5.9 s. PINS: definitions, refs
    # and brackets after a definition already passed on 02a9a5c (it had no
    # reference-style patterns to slow down); they guard the patterns the
    # fold added.
    started = time.perf_counter()
    assert skill_scaffold._linked_targets(body) == set()
    assert time.perf_counter() - started < bound


def test_the_hostile_drafts_are_not_all_clean():
    # Positive control for the bounded-sentence check above: these do draw
    # problems, so it is looking at real sentences.
    refused = sum(not run(files).ok for files, _ in _hostile_drafts().values())
    assert refused == len(_hostile_drafts())


def test_non_text_files_become_problems_and_are_left_out_of_other_checks():
    files = {**skill(), 5: "x", "references/extra.md": None, b"k": "x"}
    result = run(files)  # type: ignore[arg-type]
    assert sorted(result.problem_rules) == [
        "file-key-not-text",
        "file-key-not-text",
        "file-not-text",
    ]
    # A SKILL.md that is not text is not ALSO reported missing.
    bad_entry = {**skill(), "SKILL.md": b"bytes"}
    assert run(bad_entry).problem_rules == ("file-not-text",)  # type: ignore[arg-type]
    assert run(skill(drop_files=("SKILL.md",))).problem_rules == ("skill-md-missing",)


# ----------------------------------------------------- K1-3: when_to_use

def test_when_to_use_and_description_at_exactly_the_listing_limit_pass():
    limit = skill_scaffold.SKILL_LISTING_MAX_CHARS
    assert limit == 1536  # D-AUTHOR §3.1
    # Fold 2 (F3): Claude Code joins them with ' - ', which counts.
    room = limit - 1000 - len(" - ")
    exact = skill(front={"description": q("a" * 1000), "when_to_use": q("b" * room)})
    assert run(exact).problems == ()
    over = skill(front={"description": q("a" * 1000), "when_to_use": q("b" * (room + 1))})
    assert run(over).problem_rules == ("listing-text-too-long",)


def test_when_to_use_is_optional_and_may_be_empty_text():
    # A PIN, not new behaviour: this already passed on 02a9a5c. It is the
    # control for the when_to_use refusals the fold added.
    assert run(skill(drop_front=("when_to_use",))).problems == ()
    assert run(skill(front={"when_to_use": q("")})).problems == ()


def test_a_comparison_is_not_an_xml_tag_in_any_text_field():
    text = "Use when a < 5 and b > 3, or when x <3 and y> 2."
    files = skill(front={"description": q(text), "when_to_use": q(text)})
    assert run(files).problems == ()
    # Positive control: the same fields do refuse a real tag.
    files = skill(front={"description": q(text + " <b>"), "when_to_use": q(text + " </b>")})
    assert set(run(files).problem_rules) == {"description-xml-tag", "when-to-use-xml-tag"}


# ---------------------------------------------------------- the nits

def test_an_empty_metadata_is_no_metadata():
    for empty in ("", "null", "~"):
        assert run(skill(front={"metadata": empty})).problems == (), empty
    # Positive control: metadata that is not a mapping is still refused.
    assert run(skill(front={"metadata": q("text")})).problem_rules == (
        "metadata-not-mapping",
    )


LINKED_BODIES = {
    "reference-style, full": "See [the notes][n].\n\n[n]: references/format.md\n",
    "reference-style, collapsed": "See [format][].\n\n[format]: references/format.md\n",
    "reference-style, shortcut": 'See [format].\n\n[format]: references/format.md "Title"\n',
    "reference-style, angle brackets": "See [x][n].\n\n[n]: <references/format.md>\n",
    "reference-style, label case": "See [x][N].\n\n[n]: references/format.md\n",
    "autolink": "See <references/format.md>.\n",
    "normalised through ..": "See [x](references/../references/format.md).\n",
    "normalised through .": "See [x](references/./format.md).\n",
    # A PIN: percent-escaped already linked on 02a9a5c.
    "percent-escaped": "See [x](references/format%2Emd).\n",
}
#: CONTROLS for the link styles above, and pins: all seven were already
#: refused on 02a9a5c. They show the wider link recognition the fold added
#: does not count these as links.
UNLINKED_BODIES = {
    "a definition nothing uses": "\n[n]: references/format.md\n",
    "a link that normalises elsewhere": "See [x](references/../format.md).\n",
    "an absolute link": "See [x](/references/format.md).\n",
    "a link that climbs out": "See [x](../references/format.md).\n",
    "an undefined label": "See [x][n].\n",
    "another file": "See [x](references/other.md).\n",
    "a path only mentioned": "See `references/format.md`.\n",
}


@pytest.mark.parametrize("label", list(LINKED_BODIES))
def test_these_link_styles_link_a_reference(label: str):
    assert run(skill(body="# T\n\n" + LINKED_BODIES[label])).problems == (), label


@pytest.mark.parametrize("label", list(UNLINKED_BODIES))
def test_these_do_not_link_a_reference(label: str):
    result = run(skill(body="# T\n\n" + UNLINKED_BODIES[label]))
    assert result.problem_rules == ("reference-not-linked",), label


def test_the_remaining_rule_values_are_read_from_the_constants(monkeypatch):
    # Each value below is now a named constant; changing it changes the rule.
    # (The refusal cases above are the positive controls: with the shipped
    # values these same drafts are refused.)
    home = skill(front={"paths": json.dumps(["~/notes/**"])})
    assert run(home).problem_rules == ("paths-absolute",)
    monkeypatch.setattr(skill_scaffold, "SKILL_PATHS_ABSOLUTE_PREFIXES", ("/",))
    assert run(home).problems == ()
    monkeypatch.undo()

    climbing = skill(front={"paths": json.dumps(["docs/../x/**"])})
    assert run(climbing).problem_rules == ("paths-parent",)
    monkeypatch.setattr(skill_scaffold, "SKILL_PATHS_PARENT_SEGMENT", "UP")
    assert run(climbing).problems == ()
    monkeypatch.undo()

    nested = skill(
        body=BODY + "\nAlso [the deep one](references/a/b.md).\n",
        files={"references/a/b.md": "# Deep\n"},
    )
    assert run(nested).problem_rules == ("file-nested",)
    monkeypatch.setattr(skill_scaffold, "SKILL_REFERENCES_MAX_DEPTH", 2)
    assert run(nested).problems == ()
    monkeypatch.undo()

    backslash = skill(files={"references\\x.md": "# x\n"})
    assert run(backslash).problem_rules == ("file-path-unsafe",)
    monkeypatch.setattr(skill_scaffold, "SKILL_FILE_PATH_FORBIDDEN_CHARS", ())
    assert "file-path-unsafe" not in run(backslash).problem_rules
    monkeypatch.undo()

    dotted = skill(files={"references/./x.md": "# x\n"})
    assert run(dotted).problem_rules == ("file-path-unsafe",)
    monkeypatch.setattr(skill_scaffold, "SKILL_FILE_PATH_FORBIDDEN_SEGMENTS", ("", ".."))
    assert "file-path-unsafe" not in run(dotted).problem_rules
    monkeypatch.undo()

    with_when = skill(front={"when_to_use": q("When asked for a diagram.")})
    assert run(with_when).problems == ()
    monkeypatch.setattr(skill_scaffold, "SKILL_LISTING_MAX_CHARS", 20)
    assert run(with_when).problem_rules == ("listing-text-too-long",)
    monkeypatch.undo()

    in_value = with_skill_md(
        f'---\nname: {NAME}\ndescription: "a @@@ b"\n---\n\n{BODY}'
    )
    assert run(in_value).problems == ()
    monkeypatch.setattr(skill_scaffold, "SKILL_FRONTMATTER_FENCE", "@@@")
    assert run(in_value).problem_rules == ("frontmatter-contains-fence",)
    monkeypatch.undo()

    assert run(skill()).problems == ()
    monkeypatch.setattr(skill_scaffold, "SKILL_FRONTMATTER_REFUSED_CLOSER", "---")
    assert run(skill()).problem_rules == ("frontmatter-closed-by-dots",)
    monkeypatch.undo()


# ============================================================ fold 2 (K1a)
# The second blind gate (2026-10-08): F1 bound the work before any YAML
# parse, F2 read the frontmatter exactly as Claude Code does or refuse, F3
# the listing limit computed as Claude Code computes it, F4 no wall-clock
# assertion a busy machine can fail, and the nits.

# ------------------------------------------- F1: the caps before any parse


def _front_text(inner: str) -> dict[str, str]:
    """The valid skill whose frontmatter is exactly ``inner``."""
    return skill(files={"SKILL.md": f"---\n{inner}---\n\n{BODY}\n{MANAGED}"})


def _nested_metadata_inner(levels: int) -> str:
    """name, description, and a metadata value of ``levels`` nested flow
    mappings: exactly ``levels`` '{' in the whole frontmatter."""
    nested = "{a: " * levels + "b" + "}" * levels
    return f"name: {NAME}\ndescription: {q(DESCRIPTION)}\nmetadata: {nested}\n"


def _padded_inner(total: int) -> str:
    """A valid frontmatter of exactly ``total`` characters (a metadata note
    pads it)."""
    head = f"name: {NAME}\ndescription: {q(DESCRIPTION)}\nmetadata:\n  note: \""
    tail = '"\n'
    return head + "x" * (total - len(head) - len(tail)) + tail


class _NoYaml:
    """Stands in for ruamel's ``YAML``: records that a parse was attempted.
    It has no ``parse`` or ``load``, so a check that reaches it gets an
    error (which the check reports as unparseable)."""

    made: list[str] = []

    def __init__(self, *args, **kwargs):
        _NoYaml.made.append("YAML")


def test_a_frontmatter_at_the_size_cap_passes_and_one_over_is_refused():
    cap = skill_scaffold.SKILL_FRONTMATTER_MAX_CHARS
    assert cap == 4096
    at_cap = _padded_inner(cap)
    assert len(at_cap) == cap
    assert run(_front_text(at_cap)).problems == ()
    over = _padded_inner(cap + 1)
    result = run(_front_text(over))
    assert result.problem_rules == ("frontmatter-too-long",)
    assert f"is {cap + 1} characters" in result.problems[0].message


def test_flow_nesting_at_the_cap_passes_and_one_deeper_is_refused():
    cap = skill_scaffold.SKILL_FRONTMATTER_MAX_FLOW_DEPTH
    assert cap == 32
    assert run(_front_text(_nested_metadata_inner(cap))).problems == ()
    result = run(_front_text(_nested_metadata_inner(cap + 1)))
    assert result.problem_rules == ("frontmatter-flow-too-deep",)
    assert f"has {cap + 1} '['" in result.problems[0].message


#: The gate's slow drafts (F1), and one a scan that subtracted closers would
#: miss: each ']' sits inside a quoted value, so the real nesting is one
#: level per '["]", ' while a subtracting count stays at 1.
CAPPED_DRAFTS: dict[str, tuple[str, str]] = {
    "4 KB of '['": (
        f"name: {NAME}\ndescription: " + "[" * 2000 + "\n",
        "frontmatter-flow-too-deep",
    ),
    "'[a, ' nested 800 deep": (
        f"name: {NAME}\ndescription: " + "[a, " * 800 + "]" * 800 + "\n",
        "frontmatter-flow-too-deep",
    ),
    "quoted closers hide 560 levels": (
        f"name: {NAME}\ndescription: " + '["]", ' * 560 + "]" * 560 + "\n",
        "frontmatter-flow-too-deep",
    ),
    "16 KB of '['": (
        f"name: {NAME}\ndescription: " + "[" * 16_000 + "\n",
        "frontmatter-too-long",
    ),
    "a 1 MB description": (
        f"name: {NAME}\ndescription: {q('a' * 1_000_000)}\n",
        "frontmatter-too-long",
    ),
}


@pytest.mark.parametrize("label", list(CAPPED_DRAFTS))
def test_a_draft_over_a_cap_is_refused_before_any_yaml_parse(label: str, monkeypatch):
    inner, rule = CAPPED_DRAFTS[label]
    files = _front_text(inner)
    # Positive control: the stand-in does see the control reach the parser.
    monkeypatch.setattr(skill_scaffold, "YAML", _NoYaml)
    _NoYaml.made.clear()
    assert run(skill()).problem_rules == ("frontmatter-unparseable",)
    assert _NoYaml.made == ["YAML"]
    _NoYaml.made.clear()
    # The capped draft is refused by its rule, and the parser is never made.
    result = run(files)
    assert result.problem_rules == (rule,)
    assert _NoYaml.made == []
    assert all(len(p.message) < 700 for p in result.problems)


def test_the_caps_are_read_from_the_module_constants(monkeypatch):
    assert run(skill()).problems == ()
    monkeypatch.setattr(skill_scaffold, "SKILL_FRONTMATTER_MAX_CHARS", 50)
    assert run(skill()).problem_rules == ("frontmatter-too-long",)
    monkeypatch.undo()
    # The control has one '[' (paths) and one '{' (metadata).
    monkeypatch.setattr(skill_scaffold, "SKILL_FRONTMATTER_MAX_FLOW_DEPTH", 1)
    assert run(skill()).problem_rules == ("frontmatter-flow-too-deep",)


# ------------------------------- F2: the frontmatter as Claude Code reads it


def _with_opener(opener: str) -> dict[str, str]:
    """The valid skill with its opening line ``---\\n`` replaced."""
    text = skill()["SKILL.md"]
    assert text.startswith("---\n")
    return with_skill_md(opener + text[4:])


@pytest.mark.parametrize("opener", GATE_OPENERS, ids=[repr(o) for o in GATE_OPENERS])
def test_each_of_the_gates_opening_lines_is_refused(opener: str):
    files = _with_opener(opener)
    text = files["SKILL.md"]
    # Why: the compilers' reader finds a block here, and Claude Code none.
    assert _find_leading_block(text) is not None
    assert claude_code_block(text) is None
    result = run(files)
    assert result.problem_rules == ("frontmatter-fence-line",)
    assert "opening '---' line" in result.problems[0].message


@pytest.mark.parametrize(
    "opener",
    ["---\xa0\n", "---\u3000\n", "--- \u2003\n", "----\n", "---x\n", "---"],
    ids=["nbsp", "ideographic space", "em space after a space", "four dashes", "text", "no line break"],
)
def test_an_opening_line_with_anything_but_spaces_or_tabs_is_refused(opener: str):
    # Stricter than both readers: Claude Code and the compilers' reader both
    # read some of these (a no-break space is whitespace to both).
    result = run(_with_opener(opener) if opener != "---" else {"SKILL.md": "---"})
    assert result.problem_rules == ("frontmatter-fence-line",)


@pytest.mark.parametrize(
    "closer",
    ["---\xa0\n", "---\u3000\n", "--- \u2003\n", "---\u3000"],
    ids=["nbsp", "ideographic space", "em space after a space", "ideographic space at the end"],
)
def test_a_closing_line_with_anything_but_spaces_or_tabs_is_refused(closer: str):
    text = skill()["SKILL.md"].replace("\n---\n", "\n" + closer, 1)
    if not closer.endswith("\n"):
        text = text.split(closer)[0] + closer  # the closing line ends the text
    files = {"SKILL.md": text}
    result = run(files)
    assert result.problem_rules == ("frontmatter-fence-line",)
    assert "closing '---' line" in result.problems[0].message


def test_fence_lines_of_dashes_spaces_tabs_and_crlf_pass():
    # Positive controls for the two tests above (so they pass on c7fd5f8
    # and 02a9a5c too: these drafts were always accepted).
    for opener in _FUZZ_GOOD_OPENERS:
        assert run(_with_opener(opener)).problems == (), repr(opener)
    front = f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n"
    for closer in ("---", "--- \t", "---\n", "---\t\r\n"):
        assert run({"SKILL.md": front + closer}).problems == (), repr(closer)


#: Where a refused character can sit, and the line it is on.
_FORBIDDEN_PLACES = {
    "between two keys": (f"---\nname: {NAME}{{c}}description: {q(DESCRIPTION)}\n---\n", 2),
    "inside a plain value": (f"---\nname: {NAME}\ndescription: Draws a{{c}}diagram.\n---\n", 3),
    "on the closing line": (f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n---{{c}}", 4),
}


@pytest.mark.parametrize("place", list(_FORBIDDEN_PLACES))
@pytest.mark.parametrize(
    "char",
    ["\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\u2028", "\u2029"],
    ids=["lone CR", "VT", "FF", "FS", "GS", "RS", "US", "NEL", "LS", "PS"],
)
def test_a_line_break_character_the_readers_disagree_on_is_refused(char: str, place: str):
    assert char in skill_scaffold.SKILL_FRONTMATTER_FORBIDDEN_CHARS
    template, line = _FORBIDDEN_PLACES[place]
    # The closing line ends the text, so a lone CR there has no LF after it.
    text = template.format(c=char) + ("" if place == "on the closing line" else "\n# T\n")
    result = run({"SKILL.md": text})
    assert result.problem_rules == ("frontmatter-forbidden-character",), [
        str(p) for p in result.problems
    ]
    assert f"U+{ord(char):04X}" in result.problems[0].message
    assert f"on line {line}" in result.problems[0].message


@pytest.mark.parametrize(
    "char",
    ["\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\u2028", "\u2029"],
    ids=["lone CR", "VT", "FF", "FS", "GS", "RS", "US", "NEL", "LS", "PS"],
)
def test_the_same_characters_in_the_body_are_fine(char: str):
    # Positive control: only the frontmatter (through its closing fence) is
    # read two ways; the body is not. (Passes on c7fd5f8 and 02a9a5c too.)
    body = f"# T\n\nA line with {char} in it.\n"
    assert run({"SKILL.md": f"---\nname: {NAME}\ndescription: {q(DESCRIPTION)}\n---\n{body}"}).problems == ()


def test_crlf_line_endings_are_not_a_lone_carriage_return():
    text = f"---\r\nname: {NAME}\r\ndescription: {q(DESCRIPTION)}\r\n---\r\n# T\r\n"
    assert run({"SKILL.md": text}).problems == ()
    # Positive control: one CR without its LF is refused.
    lone = text.replace("\r\ndescription", "\rdescription", 1)
    assert run({"SKILL.md": lone}).problem_rules == ("frontmatter-forbidden-character",)


def test_the_gates_next_line_value_difference_is_refused():
    # U+0085 in a plain value: ruamel reads 'a b', Claude Code 'a\x85b'.
    text = f"---\nname: {NAME}\ndescription: a\x85b\n---\n# T\n"
    assert YAML(typ="safe").load("description: a\x85b\n") == {"description": "a b"}
    assert run({"SKILL.md": text}).problem_rules == ("frontmatter-forbidden-character",)


# ------------------------- F3: the listing limit, as Claude Code computes it

#: A character outside the Basic Multilingual Plane: one Python character,
#: two UTF-16 units (JavaScript's ``length`` counts 2).
EMOJI = "\U0001f600"


def q_raw(value: str) -> str:
    """A YAML double-quoted scalar that keeps non-ASCII characters as they
    are (``q`` would escape an emoji into two lone surrogates)."""
    return json.dumps(value, ensure_ascii=False)


def _listing_case(description: str, when_to_use: str | None) -> SkillCheck:
    front = {"description": q_raw(description)}
    if when_to_use is None:
        return run(skill(front=front, drop_front=("when_to_use",)))
    return run(skill(front={**front, "when_to_use": q_raw(when_to_use)}))


def test_the_joiner_counts_a_full_description_and_510_more_is_refused():
    # 1,024 + 3 + 510 = 1,537: the plain sum (1,534) would pass.
    result = _listing_case("a" * 1024, "b" * 510)
    assert result.problem_rules == ("listing-text-too-long",)
    assert "is 1537 characters" in result.problems[0].message
    assert "' - '" in result.problems[0].message


def test_eight_hundred_emoji_without_when_to_use_are_refused():
    # 800 characters (within the 1,024 description limit), 1,600 units.
    result = _listing_case(EMOJI * 800, None)
    assert result.problem_rules == ("listing-text-too-long",)
    assert "is 1600 characters" in result.problems[0].message


@pytest.mark.parametrize(
    ("description", "when_to_use"),
    [
        ("a" * 1000, "b" * 533),  # 1,000 + 3 + 533
        ("a" * 1000, EMOJI * 266 + "b"),  # 1,000 + 3 + 532 + 1
        ("a" * 512 + EMOJI * 512, None),  # 1,024 characters, 1,536 units
        ("a" * 512 + EMOJI * 512, ""),  # an empty when_to_use adds no joiner
    ],
    ids=["ascii with when_to_use", "emoji when_to_use", "emoji description", "empty when_to_use"],
)
def test_the_listing_limit_boundary(description: str, when_to_use: str | None):
    # Exactly 1,536 units passes ...
    assert _listing_case(description, when_to_use).problems == ()
    # ... and one unit more is refused, by the listing rule alone.
    if when_to_use:
        longer = (description, when_to_use + "c")
    else:
        longer = ("a" * 511 + EMOJI * 513, when_to_use)  # still 1,024 characters
    result = _listing_case(*longer)
    assert result.problem_rules == ("listing-text-too-long",)
    assert "is 1537 characters" in result.problems[0].message


def test_an_empty_when_to_use_is_no_when_to_use_but_one_character_brings_the_joiner():
    description = "a" * 1532
    # (over the 1,024 description limit, so look only at the listing rule)
    assert "listing-text-too-long" not in _listing_case(description, "").problem_rules
    # 1,532 + 3 + 1 = 1,536 still fits; 1,532 + 3 + 2 does not.
    assert "listing-text-too-long" not in _listing_case(description, "x").problem_rules
    assert "listing-text-too-long" in _listing_case(description, "xy").problem_rules


def test_a_lone_surrogate_is_counted_not_raised():
    # ruamel reads the escape "\ud800" as a lone surrogate; JavaScript
    # counts it as one unit.
    files = skill(front={"description": '"a\\ud800b"'})
    result = run(files)
    assert "listing-text-too-long" not in result.problem_rules
    assert skill_scaffold._utf16_length("a\ud800b") == 3
    assert skill_scaffold._utf16_length("a" + EMOJI) == 3


def test_the_listing_joiner_is_read_from_the_module_constant(monkeypatch):
    files = skill(front={"description": q("a" * 1024), "when_to_use": q("b" * 510)})
    assert run(files).problem_rules == ("listing-text-too-long",)
    monkeypatch.setattr(skill_scaffold, "SKILL_LISTING_JOINER", "")
    assert run(files).problems == ()
