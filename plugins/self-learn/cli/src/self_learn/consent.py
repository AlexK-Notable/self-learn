"""A typed yes, tied to the question it answers (S-103 as amended by
S-NEXT-attribution; cures CU-1 part A).

The overseer's registration path lets an agent's shell carry out a
question's ``register`` on the person's typed yes. Proving that the person
typed a plain yes is not enough: they may have said yes to something else
the agent asked ("shall I run the tests?"). So the yes counts only when the
assistant's own visible message, written between the person's previous
typed row and the yes, names the question's id, the path and the mode, and
names no other open registration question.

What the person reads is the assistant's ``text``; a ``tool_use`` input or
a ``tool_result`` (the output of ``overseer open``) is not shown to them as
the question, so it never counts (:func:`statements.typed_turn`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import hosts, statements

__all__ = [
    "PLAIN_YES_RE",
    "Proof",
    "names_id",
    "names_mode",
    "names_path",
    "prove_typed_yes",
]

PLAIN_YES_RE = re.compile(r"\s*y(es)?\s*[.!]?\s*", re.IGNORECASE)


def names_path(text: str, path: str) -> bool:
    """True when *text* holds *path* as a whole path: not the front of a longer
    one (`/srv/app` inside `/srv/app-old` or `/srv/app/sub`), not the tail of
    one (`/home/user/srv/app`). A closing `?`, `,`, `.` or quote is fine."""
    return (
        re.search(rf"(?<![\w/.~-]){re.escape(path)}(?![\w/-])(?!\.\w)", text) is not None
    )


def names_mode(text: str, mode: str) -> bool:
    """True when *text* names the mode the way a person reads one: "git mode",
    "in git mode", "plain skills root", "plain host", "mode: plain". A bare
    "git repository", "in plain words", "in git history" or "a plain yes" does
    not name a mode, and a text that also names the OTHER mode names neither
    (a yes must not register a mode the text only mentioned in passing)."""
    others = [other for other in hosts.HOST_MODES if other != mode]
    return _says_mode(text, mode) and not any(_says_mode(text, other) for other in others)


def _says_mode(text: str, mode: str) -> bool:
    return (
        re.search(
            rf"\b{mode}[ -](?:mode|host|skills[ -]root|registration)\b"
            rf"|\bmode\s*[:=]?\s*{mode}\b",
            text,
            re.IGNORECASE,
        )
        is not None
    )


def names_id(text: str, question_id: str) -> bool:
    """Whether *text* names *question_id* as a whole id (`q-a` is not named
    by a text about `q-a-b`)."""
    return re.search(
        rf"(?<![A-Za-z0-9@-]){re.escape(question_id)}(?![A-Za-z0-9-])", text
    ) is not None


@dataclass(frozen=True)
class Proof:
    """``ok`` when proved; ``ref`` is the transcript line of the yes;
    ``problem`` says what is missing when not."""

    ok: bool
    ref: str | None
    problem: str | None


def prove_typed_yes(
    home: Path | str,
    session: str,
    *,
    must_name: Sequence[tuple[str, Callable[[str], bool]]],
    ambiguous: Sequence[str] = (),
) -> Proof:
    """Whether the person's last typed row in *session* is a plain yes to an
    assistant message that names everything in *must_name* (each a ``(what,
    predicate)`` pair, ``what`` used in the problem sentence) and none of the
    ids in *ambiguous* (other open questions the yes could answer)."""
    try:
        turn = statements.typed_turn(home, session)
    except statements.StatementError as exc:
        return Proof(False, None, f"the typing could not be checked ({exc})")
    if PLAIN_YES_RE.fullmatch(turn.text) is None:
        return Proof(
            False, None, f"the last thing the person typed in session {session} is not a plain yes"
        )
    if not turn.asked.strip():
        return Proof(
            False, None,
            "no message of yours stands between the person's yes and what they typed before "
            "it, so the yes answers nothing named; ask again, naming the question, the path "
            "and the mode",
        )
    missing = [what for what, holds in must_name if not holds(turn.asked)]
    if missing:
        return Proof(
            False, None,
            "the message you asked the yes with does not name "
            + ", ".join(missing)
            + "; restate the question in one message (its id, the path and the mode) and ask "
            "for the yes again",
        )
    others = [other for other in ambiguous if names_id(turn.asked, other)]
    if others:
        return Proof(
            False, None,
            "the message you asked the yes with also names "
            + ", ".join(others)
            + ", so the yes could answer either; ask one registration at a time",
        )
    return Proof(True, turn.ref, None)
