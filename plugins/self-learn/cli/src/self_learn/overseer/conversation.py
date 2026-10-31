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

An ask may carry `register: {path, mode, kind?}` (S-NEXT-cures-b): the user's
typed plain "yes" to it registers that repository as a canon host in the same
command (`respond`). The person typing the answer is the consent
(S-29 / Y-17); `overseer open` shows what a yes will register, and the ask's
own text must name the path and the mode. An agent relaying the answer from
its own shell registers only when its own session (`$CLAUDE_CODE_SESSION_ID`,
or `--session` where that is not set) shows the person's last typed row to be
a plain yes (`statements.latest_user_typed`); a yes it cannot prove records
nothing and leaves the question open.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from ruamel.yaml import YAML

from .. import cases, gitops, hosts, intents, sentinel, settings, statements, user_model
from ..primitives import chrono, fsops


class ConversationError(Exception):
    """The requested conversation operation could not be completed."""


class ConversationUsageError(ConversationError):
    """The caller supplied malformed conversation input."""


@dataclass(frozen=True)
class ResponseResult:
    statement_id: str | None
    observed_cases: tuple[str, ...] = ()
    #: S-NEXT-cures-b: one plain sentence on what the answer did about a
    #: host registration the ask carried (registered, already registered, not
    #: done and why); `None` when the question carried none.
    registration: str | None = None
    #: True when the registration was carried out (or already was in place).
    registered: bool = False


_PROPOSITION_RE = re.compile(r"^(um-[0-9a-f]{4})@r?(\d+)$")
_QUESTION_HEADING = "## Questions for you"
_OBS_LINE_RE = re.compile(
    r"^- (?P<id>obs-[0-9a-f]{8}) \S+ \S+ presented: (?P<text>.*)$",
    re.MULTILINE,
)


_INDEX_KEYS = frozenset({"id", "kind", "cases", "text", "why", "register"})

_REGISTER_KEYS = frozenset({"path", "mode", "kind"})


def normalize_register(raw: object, text: str) -> tuple[dict[str, str] | None, str | None]:
    """Check an ask's `register` field. Returns `(register, None)` with the
    kind defaulted to `project`, or `(None, problem)`.

    The user's "yes" carries out the registration, so what it registers must
    be what the question says: `path` must be an absolute path, `mode` and
    `kind` must be ones `host add` knows, and the ask's `text` must name the
    path exactly and the mode. A question that hid its path in a field the
    user was never shown would turn an unrelated "yes" into a registration."""
    if not isinstance(raw, dict) or not _REGISTER_KEYS >= set(raw) or not {"path", "mode"} <= set(raw):
        return None, "register must be a mapping with path and mode (and optionally kind)"
    path, mode, kind = raw.get("path"), raw.get("mode"), raw.get("kind", "project")
    if not isinstance(path, str) or not path.startswith("/") or path != path.strip() or any(
        ch in path for ch in "\n\r\x00"
    ):
        return None, "register.path must be one absolute path"
    if mode not in hosts.HOST_MODES:
        return None, f"register.mode must be one of {list(hosts.HOST_MODES)}"
    if kind not in hosts.HOST_KINDS:
        return None, f"register.kind must be one of {list(hosts.HOST_KINDS)}"
    if not _names_path(text, path) or not _names_mode(text, mode):
        return None, "the ask's text must name register.path exactly and its mode"
    return {"kind": kind, "path": path, "mode": mode}, None


def _names_path(text: str, path: str) -> bool:
    """True when *text* holds *path* as a whole path: not the front of a longer
    one (`/srv/app` inside `/srv/app-old` or `/srv/app/sub`), not the tail of
    one (`/home/x/srv/app`). A closing `?`, `,`, `.` or quote is fine."""
    return (
        re.search(rf"(?<![\w/.~-]){re.escape(path)}(?![\w/-])(?!\.\w)", text) is not None
    )


def _names_mode(text: str, mode: str) -> bool:
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


def _register_phrase(register: dict[str, str]) -> str:
    return f"{register['kind']} host {register['path']} in {register['mode']} mode"


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
            if "register" in row:
                raise ConversationError(
                    f"overseer open: indexed reading {row['id']} cannot carry a register"
                )
            rows.append({"id": row["id"], "kind": "reading", "cases": list(row["cases"])})
        elif kind == "ask" and all(
            isinstance(row.get(key), str) and row[key].strip() for key in ("text", "why")
        ):
            ask_row = {
                "id": row["id"], "kind": "ask", "cases": list(row["cases"]),
                "text": row["text"], "why": row["why"],
            }
            if "register" in row:
                register, problem = normalize_register(row["register"], row["text"])
                if register is None:
                    raise ConversationError(
                        f"overseer open: indexed question {row['id']} has a bad register: {problem}"
                    )
                ask_row["register"] = register
            rows.append(ask_row)
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
    lines = [f"- {row['id']}: {row['text']}", f"  why: {row['why']}"]
    if row.get("register"):
        lines.append(f"  a plain yes registers: {_register_phrase(row['register'])}")
    return lines


def _ask_recorded_text(row: dict) -> str:
    """The displayed ask as ONE line: a case observation is one line."""
    shown = f"- {row['id']}: {row['text']} (why: {row['why']})"
    if row.get("register"):
        shown += f" (a plain yes registers: {_register_phrase(row['register'])})"
    return " ".join(shown.split())


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
    block = _question_block(report_path.read_text(encoding="utf-8"))
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


_PLAIN_YES_RE = re.compile(r"\s*y(es)?\s*[.!]?\s*", re.IGNORECASE)


_OWN_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def _hand_command(register: dict[str, str]) -> str:
    """The `host add` line a person (or an agent they told to) can run, with
    the path quoted for a shell."""
    return (
        f"`self-learn host add {shlex.quote(register['path'])}"
        f"{' --skills-root' if register['kind'] == 'skills-root' else ''} "
        f"--mode {register['mode']}`"
    )


def _agent_shell_proof(
    home: Path, session: str | None, phrase: str, register: dict[str, str]
) -> tuple[str | None, str | None]:
    """From an agent's shell a yes registers only when the person's own typing
    is proved. Returns `(problem, proof_ref)`: `problem` is None when proved,
    else the sentence saying why; `proof_ref` is the transcript line that held
    the yes.

    The session is the agent's OWN: `$CLAUDE_CODE_SESSION_ID` when that is set
    (the agent need not know its id, and `--session` naming another session is
    refused, so an older session where the person said yes to something else
    cannot be borrowed); `--session` is for a shell that has no such variable.
    The LAST row the person typed in that session's transcript must be a plain
    yes. Nothing older counts (a yes to another question), nothing typed after
    it, and no tool result (an AskUserQuestion click is not typing)."""
    own = (os.environ.get(_OWN_SESSION_ENV) or "").strip()
    named = (session or "").strip()
    if own and named and named != own:
        return (
            f"`--session` names a session other than this shell's own, and a yes "
            f"is proved only in the session it was typed in ({phrase})",
            None,
        )
    chosen = named or own
    if not chosen:
        return (
            f"this is an agent's shell with no session to check the typing in "
            f"({phrase}); pass `--session <the session id the person typed the yes in>`",
            None,
        )
    try:
        ref, typed = statements.latest_user_typed(home, chosen)
    except statements.StatementError as exc:
        return f"the typing could not be checked ({exc}) ({phrase})", None
    if _PLAIN_YES_RE.fullmatch(typed) is None:
        return (
            f"the last thing the person typed in session {chosen} is not a plain "
            f"yes ({phrase})",
            None,
        )
    return None, ref


def _carry_out_registration(
    home: Path, row: dict, text: str, session: str | None = None
) -> tuple[str, bool]:
    """S-NEXT-cures-b: what the answer *text* does about the registration an
    ask carries. Returns `(sentence, registered)`.

    Only a bare yes registers: "yes, but use git mode" or "not yet" is an
    answer the overseer reads, not a consent to what the question named.
    From an agent's shell (the detection that keeps tier-C settings the
    person's) the registration also needs proof that the person typed the yes
    (see :func:`_agent_shell_proof`), because the agent relaying the answer is
    how it normally reaches the ledger. A bare yes the agent's shell cannot
    prove, like a registration `host add` refuses (a path that is gone, a
    path already registered in the other mode, a path that is not a git repo
    for `git` mode), raises, so the answer is NOT recorded and the question
    stays open: an answered question whose registration never happened would
    read as done. A registration already in place needs no proof (nothing is
    being done), so "register it by hand, then answer" works."""
    register = row["register"]
    phrase = _register_phrase(register)
    if _PLAIN_YES_RE.fullmatch(text) is None:
        return f"nothing registered: the answer was not a plain yes ({phrase})", False
    proof_ref: str | None = None
    try:
        before = hosts.load_hosts(home)
        target = Path(register["path"]).expanduser().resolve()
        already = (
            hosts.is_project_host(before, target)
            if register["kind"] == "project"
            else before.skills_root is not None
            and Path(before.skills_root).expanduser().resolve() == target
        )
        if (
            register["kind"] == "skills-root"
            and before.skills_root is not None
            and Path(before.skills_root).expanduser().resolve() != target
        ):
            # `host add` would silently replace the registered root, and the
            # question never said so: that is a person's decision, made by hand.
            raise ConversationError(
                f"overseer respond: your yes would register {phrase}, but "
                f"{before.skills_root} is already the skills root and registering "
                "this one would replace it. Nothing was recorded and the question "
                f"stays open; if you want the swap, run {_hand_command(register)} yourself"
            )
        if not already and settings.agent_caller():
            # A registration already in place needs no proof (nothing is
            # being done); one still to be done does.
            problem, proof_ref = _agent_shell_proof(home, session, phrase, register)
            if problem is not None:
                raise ConversationError(
                    f"overseer respond: NOT registered, {problem}. Nothing was recorded and "
                    "the question stays open. Have the person type a plain yes in this "
                    "session and answer again straight away, have them answer in their "
                    f"own terminal, or run {_hand_command(register)} (only if they told "
                    "you to) and answer again: a registration already done is left as it is"
                )
        hosts.host_add(home, register["path"], register["kind"], mode=register["mode"])
    except hosts.HostsError as exc:
        raise ConversationError(
            f"overseer respond: your yes would register {phrase}, and that was refused: {exc}. "
            "Nothing was recorded and the question stays open; fix that and answer again, "
            "or answer in words that say what you want instead"
        ) from exc
    except gitops.HalfWrittenError as exc:
        raise ConversationError(
            f"overseer respond: registering {phrase} was written but NOT committed ({exc}). "
            f"Repair: {exc.repair}. The answer was not recorded."
        ) from exc
    except (gitops.GitOpsError, intents.LedgerStoppedError) as exc:
        raise ConversationError(
            f"overseer respond: registering {phrase} failed ({exc}); the answer was not recorded"
        ) from exc
    proved = f" (the yes is at {proof_ref})" if proof_ref else ""
    return (
        f"already registered, left as it was: {phrase}{proved}" if already else f"registered {phrase}{proved}"
    ), True


def respond(
    home: Path | str,
    *,
    proposition: str,
    scope: str,
    text: str,
    as_asked: str | None = None,
    session: str | None = None,
) -> ResponseResult:
    resolved = Path(home)
    parsed_scope = _scope(scope)
    if not text or not text.strip():
        raise ConversationUsageError("overseer respond: --text is required")
    row = _indexed_row(resolved, proposition)
    presentations = _presentations(resolved, row)
    _case_id, observation_id, displayed = presentations[-1]
    answer_text = as_asked if as_asked and as_asked.strip() else displayed
    registration: str | None = None
    registered = False
    if row["kind"] == "ask" and row.get("register"):
        # The consent carries the action: do it BEFORE the answer is
        # recorded, so a registration that is refused leaves the question
        # open (nothing recorded) instead of an answered question whose
        # promised registration never happened.
        registration, registered = _carry_out_registration(resolved, row, text, session)
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
        return ResponseResult(
            statement_id, tuple(row["cases"]), registration=registration, registered=registered
        )
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
