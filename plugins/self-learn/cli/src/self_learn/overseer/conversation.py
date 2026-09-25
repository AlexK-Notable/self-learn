"""O-5: the overseer's report-question conversation surface.

The machine index identifies questions and affected cases; the report remains
the human-facing prose.  A presentation is recorded only after this module has
successfully written and flushed the complete display.

Two kinds of question since 2026-09-24 (the orchestrator recommended the
split; the user accepted it): a `reading` asks the user to confirm or
correct one of the overseer's readings of them (its id is a user-model
proposition), and an `ask` puts a decision or fact only the user has (its id
is `q-<slug>`, and the index carries its `text` and `why`). There is no
limit on how many are shown.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from ruamel.yaml import YAML

from .. import cases, gitops, intents, sentinel, statements, user_model
from ..primitives import fsops


class ConversationError(Exception):
    """The requested conversation operation could not be completed."""


class ConversationUsageError(ConversationError):
    """The caller supplied malformed conversation input."""


@dataclass(frozen=True)
class ResponseResult:
    statement_id: str | None
    observed_cases: tuple[str, ...] = ()


_PROPOSITION_RE = re.compile(r"^(um-[0-9a-f]{4})@r?(\d+)$")
_QUESTION_HEADING = "## Questions for you"
_OBS_LINE_RE = re.compile(
    r"^- (?P<id>obs-[0-9a-f]{8}) \S+ \S+ presented: (?P<text>.*)$",
    re.MULTILINE,
)


_INDEX_KEYS = frozenset({"id", "kind", "cases", "text", "why"})


def _load_questions(home: Path) -> list[dict]:
    """The committed index, in the model's order. A row written before
    2026-09-24 is `{id, cases}` and reads as `kind: reading`."""
    path = home / "overseer" / "open-questions.yaml"
    if not path.is_file():
        return []
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - one stable surface error
        raise ConversationError(f"overseer open: cannot read {path.name}: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"questions"} or not isinstance(data["questions"], list):
        raise ConversationError("overseer open: open-questions.yaml must contain only a questions list")
    rows: list[dict] = []
    for row in data["questions"]:
        if (
            not isinstance(row, dict)
            or not {"id", "cases"} <= set(row) <= _INDEX_KEYS
            or not isinstance(row.get("id"), str)
            or not isinstance(row.get("cases"), list)
            or not all(isinstance(case_id, str) for case_id in row["cases"])
        ):
            raise ConversationError(
                "overseer open: each indexed question needs id, kind and cases "
                "(and an ask its text and why)"
            )
        kind = row.get("kind", "reading")
        if kind == "reading":
            rows.append({"id": row["id"], "kind": "reading", "cases": list(row["cases"])})
        elif kind == "ask" and all(
            isinstance(row.get(key), str) and row[key].strip() for key in ("text", "why")
        ):
            rows.append({
                "id": row["id"], "kind": "ask", "cases": list(row["cases"]),
                "text": row["text"], "why": row["why"],
            })
        else:
            raise ConversationError(
                f"overseer open: indexed question {row['id']} has kind {kind!r}; "
                "a reading, or an ask with text and why, is required"
            )
    return rows


def open_question_count(home: Path | str) -> int | None:
    """Cheap status fact: absent index -> absent field; otherwise row count."""
    resolved = Path(home)
    if not (resolved / "overseer" / "open-questions.yaml").is_file():
        return None
    return len(_load_questions(resolved))


def _question_block(report: str) -> str:
    start = report.find(_QUESTION_HEADING)
    if start < 0:
        raise ConversationError("overseer open: latest report has no Questions for you section")
    after = report.find("\n## ", start + len(_QUESTION_HEADING))
    block = report[start:] if after < 0 else report[start:after]
    return block.rstrip() + "\n"


def _names(line: str, question_id: str) -> bool:
    """Whether *line* names *question_id* as a whole id (`q-a` is not named
    by a line about `q-a-b`)."""
    return re.search(
        rf"(?<![A-Za-z0-9@-]){re.escape(question_id)}(?![A-Za-z0-9-])", line
    ) is not None


def _ask_display(row: dict) -> list[str]:
    return [f"- {row['id']}: {row['text']}", f"  why: {row['why']}"]


def _ask_recorded_text(row: dict) -> str:
    """The displayed ask as ONE line: a case observation is one line."""
    return " ".join(f"- {row['id']}: {row['text']} (why: {row['why']})".split())


def _display_line(block: str, proposition: str, cases_for_question: list[str]) -> str:
    for line in block.splitlines():
        if proposition in line:
            return line.strip()
    joined = ", ".join(cases_for_question) if cases_for_question else "no cases"
    return f"- {proposition} (cases: {joined})"


def _entry_and_revision(home: Path, proposition: str) -> tuple[str, int, dict]:
    match = _PROPOSITION_RE.fullmatch(proposition)
    if match is None:
        raise ConversationUsageError(
            "overseer respond: --proposition must be um-<4 hex>@r<revision>"
        )
    entry_id, revision_text = match.groups()
    revision = int(revision_text)
    doc = user_model.show(home)
    for entries in doc.get("containers", {}).values():
        for entry in entries or []:
            if entry.get("id") == entry_id:
                if entry.get("r") != revision:
                    raise ConversationError(
                        f"overseer respond: {proposition} is not the current stored version"
                    )
                return entry_id, revision, entry
    raise ConversationError(f"overseer respond: unknown proposition {proposition}")


def open_questions(home: Path | str, *, out: TextIO | None = None) -> int:
    """Print the report block with EVERY indexed question (no count limit
    since 2026-09-24), then record only the indexed rows displayed.

    A reading displays as before: the report's own line, or a fallback line
    when the prose omitted it. An ask displays from the index -- its text,
    then its why -- in place of the report's short `- <id>: <a few words>`
    line, or after the block when the prose omitted it."""
    resolved = Path(home)
    report_path = resolved / "overseer" / "latest-report.md"
    if not report_path.is_file():
        raise ConversationError("overseer open: no latest report exists")
    block = _question_block(report_path.read_text(encoding="utf-8"))
    indexed = _load_questions(resolved)
    asks = [row for row in indexed if row["kind"] == "ask"]
    lines: list[str] = []
    shown_asks: set[str] = set()
    for line in block.rstrip().splitlines():
        named = next((row for row in asks if _names(line, row["id"])), None)
        if named is None:
            lines.append(line)
        elif named["id"] not in shown_asks:
            lines.extend(_ask_display(named))
            shown_asks.add(named["id"])
    for row in indexed:
        if row["kind"] == "ask":
            if row["id"] not in shown_asks:
                lines.extend(_ask_display(row))
                shown_asks.add(row["id"])
        elif row["id"] not in block:
            lines.append(_display_line(block, row["id"], row["cases"]))
    display = "\n".join(lines).rstrip() + "\n"

    if out is None:
        sys.stdout.write(display)
        sys.stdout.flush()
    else:
        out.write(display)
        out.flush()

    # The CLI entrypoint owns the whole post-display write span.  The nested
    # case verbs are deliberately re-entrant; the outer wrapper is what makes
    # the command's complete mutation path visible to the lock invariant.
    with intents.ledger_write(resolved) as recovered:
        intents.announce_recovered(recovered)
        for row in indexed:
            if row["kind"] == "ask":
                # An ask shows neither a case's decision nor a user-model
                # reading, so it names no `entries` (nothing to flip) and
                # covers `dependencies`: the only value in `cases.observe`'s
                # closed set that does not claim the case's decision was
                # shown (02-schema §3a.2 -- a case merely cited in a
                # question is not thereby presented). No new kind.
                ask_text = _ask_recorded_text(row)
                for case_id in row["cases"]:
                    cases.observe(
                        resolved,
                        case_id,
                        "presented",
                        text=ask_text,
                        by="overseer",
                        to="human",
                        covering="dependencies",
                        entries=[],
                        outcome="noted",
                        via="overseer-conversation",
                    )
                continue
            entry_id, _revision, _entry = _entry_and_revision(resolved, row["id"])
            text = _display_line(block, row["id"], row["cases"])
            for case_id in row["cases"]:
                cases.observe(
                    resolved,
                    case_id,
                    "presented",
                    text=text,
                    by="overseer",
                    to="human",
                    covering="decision",
                    entries=[entry_id],
                    outcome="noted",
                    via="overseer-conversation",
                )
    return len(indexed)


def _scope(value: str) -> dict[str, str | None]:
    if value == "user":
        return {"level": "user", "host": None}
    if value.startswith("project:") and value.removeprefix("project:").strip():
        return {"level": "project", "host": value.removeprefix("project:")}
    raise ConversationUsageError(
        "overseer respond: --scope is required and must be user or project:<host>"
    )


def _indexed_row(home: Path, proposition: str) -> dict:
    for row in _load_questions(home):
        if row["id"] == proposition:
            return row
    raise ConversationError(f"overseer respond: {proposition} is not an open question")


def _presentations(home: Path, row: dict) -> list[tuple[str, str, str]]:
    proposition, case_ids = row["id"], row["cases"]
    is_ask = row["kind"] == "ask"
    entry_id = None if is_ask else _entry_and_revision(home, proposition)[0]
    candidates: list[tuple[str, str, str]] = []
    for case_id in case_ids:
        view = cases.show(home, case_id, evidence_only=False)
        text_by_id = {
            match.group("id"): match.group("text")
            for match in _OBS_LINE_RE.finditer(view.sections.get("Later observations", ""))
        }
        for presentation in view.frontmatter.get("presented") or []:
            shown = text_by_id.get(presentation.get("id"))
            if (
                presentation.get("via") == "overseer-conversation"
                and shown is not None
                and (
                    shown.startswith(f"- {proposition}: ") if is_ask
                    else entry_id in (presentation.get("entries") or [])
                )
            ):
                candidates.append((case_id, presentation["id"], text_by_id[presentation["id"]]))
    if not candidates:
        raise ConversationError(
            f"overseer respond: {proposition} has not been displayed by overseer open"
        )
    return candidates


def _set_presentation_outcome(
    home: Path, presentations: list[tuple[str, str, str]], outcome: str
) -> None:
    """Update the mutable presentation metadata without touching sections 1-4."""
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            touched: list[Path] = []
            for case_id, observation_id, _displayed in presentations:
                path = cases._case_path_for_id(home, case_id)
                content = path.read_text(encoding="utf-8")
                frontmatter, body = cases._split_frontmatter(content)
                frozen, _rest = cases._split_frozen(body)
                if cases._hash_frozen(frozen) != frontmatter.get("decided_sha256"):
                    raise ConversationError(
                        f"overseer respond: {case_id} failed its freeze-hash check"
                    )
                frontmatter_presentations = list(frontmatter.get("presented") or [])
                changed = False
                for row in frontmatter_presentations:
                    if row.get("id") == observation_id:
                        row["outcome"] = outcome
                        changed = True
                if changed:
                    frontmatter = dict(frontmatter)
                    frontmatter["presented"] = frontmatter_presentations
                    fsops.atomic_write(path, cases._render_frontmatter(frontmatter) + body, fsync=True)
                    touched.append(path)
            if not touched:
                raise ConversationError(
                    "overseer respond: no indexed presentation could be updated"
                )
            message = f"self-learn: overseer presentation response {outcome}"
            sha = gitops.stage_and_commit(home, touched, message, None)
            if sha is None:
                raise ConversationError("overseer respond: presentation outcome produced no commit")
            for case_id, _observation_id, _displayed in presentations:
                cases._update_index(home, case_id)
    finally:
        hold.release()


def _dependent_cases(home: Path, proposition: str, statement_id: str) -> list[tuple[str, str]]:
    _entry_id, _revision, entry = _entry_and_revision(home, proposition)
    proposition_statement_refs = {
        ref for ref in (entry.get("statements") or []) if isinstance(ref, str)
    }
    matches: list[tuple[str, str]] = []
    for row in cases.list_cases(home, only_ok=True):
        refs = row.get("dependency_refs") or []
        ref = proposition if proposition in refs else None
        if ref is None:
            ref = next((candidate for candidate in refs if candidate in proposition_statement_refs), None)
        if ref is None and statement_id in refs:
            ref = statement_id
        if ref is not None:
            matches.append((row["case"], ref))
    return matches


def respond(
    home: Path | str,
    *,
    proposition: str,
    scope: str,
    text: str,
    as_asked: str | None = None,
) -> ResponseResult:
    resolved = Path(home)
    parsed_scope = _scope(scope)
    if not text or not text.strip():
        raise ConversationUsageError("overseer respond: --text is required")
    row = _indexed_row(resolved, proposition)
    presentations = _presentations(resolved, row)
    _case_id, observation_id, displayed = presentations[-1]
    answer_text = as_asked if as_asked and as_asked.strip() else displayed
    statement_id = statements.add(
        resolved,
        verbatim=text,
        source={"message_ref": f"conversation:{observation_id}", "surface": "conversation"},
        recorded_by="human",
        answers={
            "kind": "question" if row["kind"] == "ask" else "proposition",
            "ref": proposition,
            "text": answer_text,
        },
        scope=parsed_scope,
    )
    if row["kind"] == "ask":
        # An answer to an ask is not an agreement with, or a correction of,
        # anything the user was shown, so the presentation's outcome stays
        # `noted`; the answer itself is the statement. Each case the ask
        # cited is observed as `statement`, pointing at it.
        for case_id in row["cases"]:
            cases.observe(
                resolved,
                case_id,
                "statement",
                text=f"user answered {proposition}",
                by="overseer",
                ref=statement_id,
            )
        return ResponseResult(statement_id, tuple(row["cases"]))
    dependent = _dependent_cases(resolved, proposition, statement_id)
    for case_id, dependency_ref in dependent:
        cases.observe(
            resolved,
            case_id,
            "statement",
            text=f"user replied to {proposition}",
            by="overseer",
            ref=dependency_ref,
        )
    outcome = "agreed" if text.strip().casefold() in {"yes", "agreed", "correct"} else "corrected"
    _set_presentation_outcome(resolved, presentations, outcome)
    return ResponseResult(statement_id, tuple(case_id for case_id, _ in dependent))


def decline(home: Path | str, *, proposition: str) -> ResponseResult:
    resolved = Path(home)
    row = _indexed_row(resolved, proposition)
    presentations = _presentations(resolved, row)
    _set_presentation_outcome(resolved, presentations, "declined")
    return ResponseResult(None)
