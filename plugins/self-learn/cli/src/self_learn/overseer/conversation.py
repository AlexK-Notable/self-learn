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

Skills (S-NEXT-sk7-veto, skill-writing plan SK7 / decision D15). After the
questions, ``open`` prints a "Skills this week" section: every skill
self-learn built, changed or retired since the latest report began, every
skill kept as a draft that week, and the skills still waiting on the user's
word (a vetoed name with no new name yet, a retirement the user asked for).
The user can then veto a skill's NAME or ask for its RETIREMENT with
``respond --veto-skill`` / ``--retire-skill``. Both go through the same
answer path as a question (the typed words are a statement, S-94 holds, and
the statement is anchored to a presentation ``open`` recorded): a veto adds
the name to the registry's ``vetoed`` list, so every later ``skill write``
refuses it; a retirement request is only recorded, as a statement
(``answers.kind: instruction``, ``answers.ref: retire-skill:<name>``), and
:func:`pending_retire_requests` is how the overseer's runner reads it back.
Only a skill self-learn owns (a live registry row) can be named.
"""

from __future__ import annotations

import functools
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

from ruamel.yaml import YAML

from .. import cases, gitops, intents, sentinel, skill_registry, statements, user_model
from ..primitives import chrono, fsops
from ..skill_scaffold import SKILL_NAME_MAX_CHARS, SKILL_NAME_RE


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


#: The `answers.kind` values `respond` writes: an ask is answered as a
#: `question`, a reading as a `proposition`.
_ANSWER_KINDS = frozenset({"question", "proposition"})


def _answered_ids(home: Path, ids: set[str]) -> set[str]:
    """Which of the indexed question *ids* the user has answered since the
    index was written.

    The index (`open-questions.yaml`) is rewritten only by a complete weekly
    run, so before 2026-10-30 a question stayed listed, and counted by the
    session-start hook, for the rest of the week after `overseer respond`
    recorded its answer. A question is answered when a statement whose
    `answers.ref` is its id was recorded at or after the index file's last
    write (second precision). The floor is what lets a later run ask the same
    id again: its new index is newer than the old answer, so the question is
    open once more. The statement store is only read, so the next weekly run
    still sees the answer (`run._question_answers`). A store or index that
    cannot be read answers nothing: the question stays listed."""
    if not ids:
        return set()
    try:
        floor = datetime.fromtimestamp(
            int((home / "overseer" / "open-questions.yaml").stat().st_mtime),
            tz=timezone.utc,
        )
        rows = statements.list_statements(home)
    except (OSError, ValueError):
        return set()
    answered: set[str] = set()
    for row in rows:
        answers = row.get("answers")
        if not isinstance(answers, dict) or answers.get("kind") not in _ANSWER_KINDS:
            continue
        ref = answers.get("ref")
        at = chrono.to_dt(row.get("at"))
        if isinstance(ref, str) and ref in ids and at is not None and at >= floor:
            answered.add(ref)
    return answered


def _unanswered(home: Path, rows: list[dict]) -> tuple[list[dict], set[str]]:
    """*rows* without the questions already answered, and the answered ids."""
    answered = _answered_ids(home, {row["id"] for row in rows})
    return [row for row in rows if row["id"] not in answered], answered


def open_question_count(home: Path | str) -> int | None:
    """Cheap status fact: absent index -> absent field; otherwise the number
    of indexed questions not yet answered."""
    resolved = Path(home)
    if not (resolved / "overseer" / "open-questions.yaml").is_file():
        return None
    return len(_unanswered(resolved, _load_questions(resolved))[0])


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


# ---------------------------------------------------------------- skills view

#: `answers.ref` prefixes of a skill instruction in the statement store.
SKILL_VETO_REF = "veto-skill:"
SKILL_RETIRE_REF = "retire-skill:"

_SKILLS_HEADING = "## Skills this week"
#: A report's first line carries its run's UTC start date (`run._report_text`).
_REPORT_DATE_RE = re.compile(r"^#[^\n]*?(\d{4}-\d{2}-\d{2})")
_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DRAFT_DESCRIPTION_MAX = 160
#: `overseer/skills/<week>/drafts/` belongs to the report's week when the week
#: key (the local date of the Sunday boundary) is less than a week before the
#: report's UTC date, or at most a day after it (a host east of UTC reports a
#: run on the boundary's own morning under the day before).
_DRAFT_WEEK_SPAN = timedelta(days=7)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _report_floor(report_path: Path, report_text: str) -> datetime:
    """When the latest report's run began, to the day: the UTC date in the
    report's first line, else the day the file was last written."""
    first = report_text.splitlines()[0] if report_text else ""
    found = _REPORT_DATE_RE.match(first)
    if found is not None:
        stamp = chrono.to_dt(found.group(1))
        if stamp is not None:
            return stamp
    written = datetime.fromtimestamp(int(report_path.stat().st_mtime), tz=timezone.utc)
    return written.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_event(row: dict, floor: datetime) -> tuple[str, str, dict] | None:
    """The one thing a registry row did since *floor*, as (label, verb,
    stamp): a retirement; else the build; else a later rewrite. ``None``
    when it did nothing in the window."""
    if row.get("status") == skill_registry.STATUS_RETIRED:
        candidates = [("[skill retired]", "retired", row["retired"])]
    else:
        candidates = [("[new skill]", "built", row["created"]),
                      ("[skill changed]", "changed", row["last_write"])]
    for label, verb, stamp in candidates:
        when = chrono.to_dt(stamp["at"])
        if when is not None and when >= floor:
            return label, verb, stamp
    return None


def _draft_folders(home: Path, floor: datetime) -> list[Path]:
    """The skills the overseer kept as drafts for the report's week."""
    root = home / "overseer" / "skills"
    report_day = floor.date()
    found: list[Path] = []
    try:
        week_dirs = sorted(p for p in root.iterdir() if p.is_dir() and _DATE_DIR_RE.fullmatch(p.name))
    except OSError:
        return []
    for week_dir in week_dirs:
        try:
            week = date.fromisoformat(week_dir.name)
        except ValueError:
            continue
        if not (report_day - _DRAFT_WEEK_SPAN < week <= report_day + timedelta(days=1)):
            continue
        try:
            found.extend(sorted(p for p in (week_dir / "drafts").iterdir() if p.is_dir()))
        except OSError:
            continue
    return found


def _draft_description(folder: Path) -> str:
    """The draft's frontmatter description, on one line and bounded; empty
    when the file or the key cannot be read (the draft is still listed)."""
    try:
        lines = (folder / "SKILL.md").read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            return ""
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        data = YAML(typ="safe").load("\n".join(lines[1:end]))
    except Exception:  # noqa: BLE001 - a draft that cannot be read is listed without its words
        return ""
    value = data.get("description") if isinstance(data, dict) else None
    return _one_line(value)[:_DRAFT_DESCRIPTION_MAX] if isinstance(value, str) else ""


def pending_renames(home: Path | str) -> list[dict]:
    """Live skills whose name the user vetoed and that have no new name yet,
    by name: ``{name, statement, at}``. The overseer's next run must rename
    each (or ask). A skill renamed since has a new key, so it drops out."""
    registry = skill_registry.load(home)
    vetoes = {entry["name"].casefold(): entry for entry in registry.vetoed}
    return [
        {"name": name, "statement": vetoes[name.casefold()]["statement"],
         "at": vetoes[name.casefold()]["at"]}
        for name in registry.live() if name.casefold() in vetoes
    ]


def pending_retire_requests(home: Path | str) -> list[dict]:
    """The user's retirement requests the overseer has not acted on: for each
    LIVE skill, its newest ``retire-skill:<name>`` statement made at or after
    the skill's creation (an older one belongs to an earlier skill of that
    name). ``{name, statement, at, verbatim, scope}``, by name. A store that
    cannot be read raises; the overseer's runner decides what that means."""
    registry = skill_registry.load(home)
    newest: dict[str, tuple[datetime, dict]] = {}
    for row in statements.list_statements(home):
        answers = row.get("answers")
        if not isinstance(answers, dict) or answers.get("kind") != "instruction":
            continue
        ref = answers.get("ref")
        if not isinstance(ref, str) or not ref.startswith(SKILL_RETIRE_REF):
            continue
        name = ref[len(SKILL_RETIRE_REF):]
        skill = registry.row(name)
        if skill is None or skill["status"] != skill_registry.STATUS_LIVE:
            continue
        at = chrono.to_dt(row.get("at"))
        created = chrono.to_dt(skill["created"]["at"])
        if at is None or created is None or at < created:
            continue
        if name not in newest or at >= newest[name][0]:
            newest[name] = (at, row)
    return [
        {"name": name, "statement": row.get("id"), "at": row.get("at"),
         "verbatim": row.get("verbatim"), "scope": row.get("scope")}
        for name, (_at, row) in sorted(newest.items())
    ]


def _skills_view(
    home: Path, report_path: Path, report_text: str
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """The "Skills this week" section as lines, and the presentations to
    record once it is shown, as (case id, skill name, displayed line).

    Every line is ``- skill <name>: <what>`` so that the line shown is the
    line recorded and the line a veto or retirement is anchored to. Only a
    live skill built or changed this week is recorded as shown, against the
    case that made that change: it is the only kind of line the user can act
    on. A registry that cannot be read is one line saying so, never a failure
    of the questions above it. Nothing is printed when there is nothing to
    say, so a ledger without skills sees the same output as before."""
    floor = _report_floor(report_path, report_text)
    try:
        registry = skill_registry.load(home)
    except skill_registry.SkillRegistryError as exc:
        return [_SKILLS_HEADING, f"- skills not shown: {_one_line(str(exc))}"], []
    lines: list[str] = []
    marks: list[tuple[str, str, str]] = []
    for name in sorted(registry.skills):
        row = registry.skills[name]
        event = _week_event(row, floor)
        if event is None:
            continue
        label, verb, stamp = event
        text = (
            f"- skill {name}: {label} {verb} {str(stamp['at'])[:10]} "
            f"by {stamp['by']} (case {stamp['case']})"
        )
        lines.append(text)
        if row["status"] == skill_registry.STATUS_LIVE:
            marks.append((stamp["case"], name, text))
    for folder in _draft_folders(home, floor):
        label = "[skill change draft]" if registry.is_owned(folder.name) else "[new skill draft]"
        text = f"- skill {folder.name}: {label} kept as a draft, nothing deployed"
        description = _draft_description(folder)
        lines.append(f"{text}; description: {description}" if description else text)
    for waiting in pending_renames(home):
        lines.append(
            f"- skill {waiting['name']}: [name vetoed] waits for the next overseer run to give "
            f"it a new name (your words {waiting['statement']})"
        )
    try:
        requests = pending_retire_requests(home)
    except (OSError, ValueError):
        requests = []  # an unreadable store: the line is missing, the questions are not
    for request in requests:
        lines.append(
            f"- skill {request['name']}: [retirement requested] waits for the next overseer run "
            f"(your words {request['statement']})"
        )
    if not lines:
        return [], []
    if registry.live():
        lines.append(
            "To veto a built skill's name: self-learn overseer respond --veto-skill <name> "
            "--scope user --text \"<your words>\"; to ask for its retirement: --retire-skill <name>."
        )
    return [_SKILLS_HEADING, *lines], marks


def _present_skill(home: Path, case_id: str, name: str, text: str) -> None:
    """Record that *text* was shown to the human, against the case that made
    the skill change it describes (a presentation observation, as an ask
    gets: it claims only that the dependencies were shown, never the
    case's decision). Once per distinct line: showing the same line again
    adds nothing. A case that cannot be observed is named on stderr, and the
    skill then cannot be vetoed or retired from the conversation until it
    can."""
    try:
        seen = cases.show(home, case_id, evidence_only=False).sections.get("Later observations", "")
        if any(line.endswith(f" presented: {text}") for line in seen.splitlines()):
            return
        cases.observe(
            home, case_id, "presented", text=text, by="overseer", to="human",
            covering="dependencies", entries=[], outcome="noted", via="overseer-conversation",
        )
    except (cases.CaseError, OSError) as exc:
        print(
            f"self-learn: skill {name}: not recorded as shown ({_one_line(str(exc))}); "
            "it cannot be vetoed or retired from the conversation until it is",
            file=sys.stderr,
        )


def open_questions(home: Path | str, *, out: TextIO | None = None) -> int:
    """Print the report block with EVERY indexed question not yet answered
    (no count limit since 2026-09-24; an answered one is left out, with its
    line in the report block, from the moment its answer is recorded --
    :func:`_answered_ids`), then record only the indexed rows displayed.

    A reading displays as before: the report's own line, or a fallback line
    when the prose omitted it. An ask displays from the index -- its text,
    then its why -- in place of the report's short `- <id>: <a few words>`
    line, or after the block when the prose omitted it."""
    resolved = Path(home)
    report_path = resolved / "overseer" / "latest-report.md"
    if not report_path.is_file():
        raise ConversationError("overseer open: no latest report exists")
    report_text = report_path.read_text(encoding="utf-8")
    block = _question_block(report_text)
    indexed, answered = _unanswered(resolved, _load_questions(resolved))
    asks = [row for row in indexed if row["kind"] == "ask"]
    lines: list[str] = []
    shown_asks: set[str] = set()
    for line in block.rstrip().splitlines():
        if any(_names(line, question_id) for question_id in answered):
            continue
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
    if answered and not any(line.startswith("- ") for line in lines):
        # Every question the report listed has been answered.
        lines.append("- none")
    display = "\n".join(lines).rstrip() + "\n"
    # After the questions: the skills the user may veto or ask to retire.
    skill_lines, skill_marks = _skills_view(resolved, report_path, report_text)
    if skill_lines:
        display += "\n" + "\n".join(skill_lines) + "\n"

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
        for case_id, skill_name, skill_text in skill_marks:
            _present_skill(resolved, case_id, skill_name, skill_text)
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


# ------------------------------------------------- a veto or a retirement request


def _skill_name(value: str, flag: str) -> str:
    if (
        not isinstance(value, str)
        or SKILL_NAME_RE.fullmatch(value) is None
        or len(value) > SKILL_NAME_MAX_CHARS
    ):
        raise ConversationUsageError(
            f"overseer respond: {flag} needs a skill name (kebab-case, at most "
            f"{SKILL_NAME_MAX_CHARS} characters), got {value!r}"
        )
    return value


def _owned_skill_row(home: Path, name: str) -> dict:
    """The registry row of a skill self-learn owns (a live row). Any other
    name -- unknown, retired, a skill someone else wrote -- is refused by
    name, with the skills that could have been meant."""
    try:
        registry = skill_registry.load(home)
    except skill_registry.SkillRegistryError as exc:
        raise ConversationError(f"overseer respond: {_one_line(str(exc))}") from exc
    row = registry.row(name) if registry.is_owned(name) else None
    if row is None:
        live = ", ".join(registry.live()[:20]) or "none"
        raise ConversationError(
            f"overseer respond: {name} is not a skill self-learn owns (live skills: {live})"
        )
    return row


def _skill_presentations(home: Path, name: str, row: dict) -> list[tuple[str, str, str]]:
    """What ``overseer open`` has shown about skill *name*, oldest first, as
    (case id, observation id, displayed line). The line is looked for on each
    case the registry row names, because the line was recorded against the
    case that made the change it describes."""
    prefix = f"- skill {name}: "
    case_ids: list[str] = []
    for key in ("created", "last_write", "retired"):
        stamp = row.get(key)
        if isinstance(stamp, dict) and stamp.get("case") not in case_ids:
            case_ids.append(stamp["case"])
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    found: list[tuple[datetime, str, str, str]] = []
    for case_id in case_ids:
        try:
            view = cases.show(home, case_id, evidence_only=False)
        except (cases.CaseError, OSError):
            continue
        text_by_id = {
            match.group("id"): match.group("text")
            for match in _OBS_LINE_RE.finditer(view.sections.get("Later observations", ""))
        }
        for presentation in view.frontmatter.get("presented") or []:
            shown = text_by_id.get(presentation.get("id"))
            if (
                presentation.get("via") == "overseer-conversation"
                and shown is not None
                and shown.startswith(prefix)
            ):
                at = chrono.to_dt(presentation.get("at")) or oldest
                found.append((at, case_id, presentation["id"], shown))
    found.sort(key=lambda item: item[0])
    return [(case_id, obs_id, shown) for _at, case_id, obs_id, shown in found]


def _add_skill_veto(
    registry: skill_registry.Registry, *, name: str, at: str, statement: str
) -> None:
    registry.add_veto(name, at=at, statement=statement)


def respond_skill(
    home: Path | str,
    *,
    action: str,
    name: str,
    scope: str,
    text: str,
    as_asked: str | None = None,
) -> ResponseResult:
    """The user's reply about a skill ``overseer open`` showed: ``action``
    ``veto`` bans the skill's name for ever, ``retire`` asks for the skill to
    be retired by the next overseer run.

    Refused by name, with nothing recorded, when the skill is not one
    self-learn owns, when ``open`` never showed it, or when the words or the
    scope are missing. The words are recorded as typed (a statement,
    ``answers.kind: instruction``, ``answers.ref: veto-skill:<name>`` or
    ``retire-skill:<name>``), anchored to the presentation ``open`` recorded,
    exactly as an answer to an ask is. A veto then adds the name to the
    registry's ``vetoed`` list (one ledger commit) and the case that made the
    skill gets a ``statement`` observation; a retirement request only gets
    the observation (the overseer reads it with
    :func:`pending_retire_requests`). Every step is idempotent, so a reply
    that stopped half-way is finished by saying it again."""
    if action not in ("veto", "retire"):
        raise ConversationUsageError(f"overseer respond: unknown skill action {action!r}")
    flag = "--veto-skill" if action == "veto" else "--retire-skill"
    resolved = Path(home)
    parsed_scope = _scope(scope)
    if not text or not text.strip():
        raise ConversationUsageError("overseer respond: --text is required")
    name = _skill_name(name, flag)
    row = _owned_skill_row(resolved, name)
    presentations = _skill_presentations(resolved, name, row)
    if not presentations:
        raise ConversationError(
            f"overseer respond: {flag} {name}: overseer open has not shown that skill "
            "(it lists the skills built or changed since the latest report)"
        )
    case_id, observation_id, displayed = presentations[-1]
    ref = (SKILL_VETO_REF if action == "veto" else SKILL_RETIRE_REF) + name
    statement_id = statements.add(
        resolved,
        verbatim=text,
        source={"message_ref": f"conversation:{observation_id}", "surface": "conversation"},
        recorded_by="human",
        answers={
            "kind": "instruction",
            "ref": ref,
            "text": as_asked if as_asked and as_asked.strip() else displayed,
        },
        scope=parsed_scope,
    )
    if statement_id not in {
        stored["id"] for stored in statements.list_statements(resolved, answers_ref=ref)
    }:
        # `statements.add` dedupes on (message_ref, words): the same words
        # said about the same displayed line for the other action come back
        # as that statement, which is not this instruction.
        raise ConversationError(
            f"overseer respond: those exact words are already recorded as {statement_id} for a "
            f"different reply about {name}; say it in other words so {flag} {name} is its own statement"
        )
    if action == "veto":
        try:
            skill_registry.with_update(
                resolved,
                functools.partial(
                    _add_skill_veto, name=name, at=chrono.now_iso(), statement=statement_id
                ),
                subject=f"veto skill name {name}",
            )
        except skill_registry.SkillRegistryError as exc:
            raise ConversationError(f"overseer respond: {_one_line(str(exc))}") from exc
    if f"(ref: {statement_id})" not in cases.show(
        resolved, case_id, evidence_only=False
    ).sections.get("Later observations", ""):
        cases.observe(
            resolved,
            case_id,
            "statement",
            text=(
                f"user vetoed the name of skill {name}"
                if action == "veto"
                else f"user asked for skill {name} to be retired"
            ),
            by="overseer",
            ref=statement_id,
        )
    return ResponseResult(statement_id, (case_id,))
