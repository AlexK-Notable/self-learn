"""The one shared passage on writing a lesson (E3a, S-1.4 of the build plan).

The canonical text is ``skills/self-learn/references/lesson-writing.md``.
Each lesson writer carries its own INLINED copy between the two markers
below, never a pointer to the file: a pointer an agent must choose to open
is the shelf failure again. The steward's brief and the overseer's
workspace README read the file at build time through :func:`inlined`, so
they cannot drift from it. ``commands/teach.md`` is a static markdown file
a harness loads as-is, so its copy is written out and
``tests/test_lesson_writing_copies.py`` checks it byte for byte.
"""

from __future__ import annotations

from pathlib import Path

BEGIN = "<!-- lesson-writing:begin (a copy of skills/self-learn/references/lesson-writing.md) -->"
END = "<!-- lesson-writing:end -->"


#: Said right after the passage, OUTSIDE the markers (the copy stays
#: byte-identical), to the two writers that write sheets: the steward and
#: the overseer. E3b (2026-10-11) replaced S-84's interim sentence (that
#: `revise` cannot add a `## Context` section, false since S-85) with two
#: paragraphs true for BOTH agents under D-AUTHOR §2.8:
#:
#: * where background goes, in sheet terms -- a `revise` line's `section:
#:   Context` writes the section (adding it when the lesson lacks one), a
#:   `replace` line's `context:` carries it -- leaving WHICH line an agent
#:   may write for a given lesson to its own method or README (the steward
#:   may not replace a placed lesson outside a reconsider, so a shared "use
#:   `replace` for a placed lesson" would be false for it);
#: * the backlog's rule: a loaded value is ONE physical line, never
#:   hard-wrapped (run 854639e4's overseer wrapped a revise onto 5 lines and
#:   the route was refused `bad-line`). Teach does not get it: it writes no
#:   YAML, and the canonical passage already says each loaded section is one
#:   line.
AGENT_SHEET_NOTE = (
    "On a sheet, a lesson's background goes under `## Context`: a `revise` line with "
    "`section: Context` writes that section (and adds it when the lesson has none), and a "
    "`replace` line carries it as `context:`. Which of the two you may write for a given "
    "lesson, your method says.\n\n"
    "Each loaded value on a sheet line -- `trigger`, `instruction` and `fact`, and a "
    "`revise` line's `text` for one of those sections -- is ONE physical line. Write it as "
    "a single quoted line: never wrap it across lines, and never as a `|` block, which "
    "keeps every line break. A lesson whose loaded value spans lines is refused "
    "(`bad-line`) when it is placed; what does not fit on one line goes in Context."
)


def path() -> Path:
    # src/self_learn/lesson_writing.py -> parents[3] is plugins/self-learn
    return (
        Path(__file__).resolve().parents[3]
        / "skills" / "self-learn" / "references" / "lesson-writing.md"
    )


def text() -> str:
    """The canonical passage, exactly as the file holds it."""
    return path().read_bytes().decode("utf-8")


def inlined() -> str:
    """The passage between its markers, each on a line of its own."""
    return f"{BEGIN}\n{text()}{END}"


def extract(document: str) -> str | None:
    """The text between the markers of *document*, or ``None`` when a marker
    is missing. The inverse of :func:`inlined`."""
    start = document.find(BEGIN + "\n")
    if start < 0:
        return None
    start += len(BEGIN) + 1
    stop = document.find(END, start)
    if stop < 0:
        return None
    return document[start:stop]
