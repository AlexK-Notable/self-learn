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
