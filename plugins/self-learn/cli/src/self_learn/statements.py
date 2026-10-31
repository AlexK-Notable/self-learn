"""User-statement store (U2, `02-schema.md` §3a.3, S-65).

``<ledger>/user-statements.jsonl`` — append-only JSON Lines; nothing is
ever rewritten in place. A correction is a new line naming (`amends`) the
line it corrects.

Public surface:

    add(home, *, verbatim, source, recorded_by, answers=None,
        scope=None, uncertainty=None, amends=None) -> str   # stmt id
    list_statements(home, **filters) -> list[dict]

Every write opens :func:`self_learn.intents.ledger_write` before its
first mutation and stages+commits inside that same span, mirroring
:mod:`self_learn.cases`."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from . import gitops, intents, provenance, refs, sentinel
from .primitives import chrono, fsops
from .scan import attach_hits, format_refusal
from .scan import scan as secret_scan

__all__ = [
    "ANSWER_KINDS",
    "RECORDED_BY_VALUES",
    "SCOPE_LEVELS",
    "STMT_ID_RE",
    "StatementError",
    "StatementUsageError",
    "add",
    "list_statements",
    "user_message_ref",
]

#: 02-schema.md §3a.3: "whoever captured the words records them, the
#: steward included" — the same 3-name universe as `cases.ACTORS`.
RECORDED_BY_VALUES = frozenset({"human", "steward", "overseer"})
ANSWER_KINDS = frozenset({"proposition", "question", "instruction"})
SCOPE_LEVELS = frozenset({"user", "project"})

STMT_ID_RE = re.compile(r"^stmt-[0-9a-f]{8}$")
#: `source.message_ref` — the miner's own transcript grammar, or the
#: `conversation:<obs-id>` form for words typed into the overseer's own
#: conversation (R-6a) where no transcript line exists yet. D-c: the
#: `conversation:` form means exactly `conversation:obs-<8 hex>` — an
#: observation id, not an arbitrary trailing string.
_MESSAGE_REF_RE = re.compile(r"^(transcript:.+#L\d+|conversation:obs-[0-9a-f]{8})$")


class StatementError(Exception):
    """A statement write refused before committing."""

    exit_code = 1


class StatementUsageError(StatementError):
    """Malformed invocation — sysexits EX_USAGE."""

    exit_code = 64


def _path(home: Path) -> Path:
    return home / "user-statements.jsonl"


def _read_lines(home: Path) -> list[dict]:
    path = _path(home)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _new_stmt_id(existing: list[dict]) -> str:
    seen = {row["id"] for row in existing}
    for _ in range(64):
        candidate = "stmt-" + uuid.uuid4().hex[:8]
        if candidate not in seen:
            return candidate
    raise StatementError("statement add: could not allocate a unique id")  # pragma: no cover


def _displayed_label(label: str) -> str:
    """The label as Claude Code shows and records it (2.1.310, `G9`): tabs
    become spaces, the text is cut at 2000 characters, line breaks become
    U+FFFD, whitespace runs collapse to one space, the ends are trimmed."""
    text = re.sub(r"[\n\r\u2028\u2029]", "\ufffd", label.replace("\t", " ")[:2000])
    return re.sub(r"\s+", " ", text).strip()


def _free_answer(answer: str, question: dict) -> str:
    """Remove clicked labels from CC's comma-separated multi-select answer.

    Single-select Other answers are stored directly; notes have their own
    field. For overlapping labels, keep only the suffix left by every
    possible parsing of the selected-label prefixes.
    """
    if question.get("kind") in ("text", "number") and not question.get("options"):
        return answer
    options = question.get("options")
    if not isinstance(options, list) or not options:
        return ""
    if any(not isinstance(o, dict) or not isinstance(o.get("label"), str) for o in options):
        return ""
    raw = [o["label"] for o in options if o["label"]]
    # The clicked value is written as displayed, so the displayed spelling
    # counts as clicked too (gate-stmt-r3 MINOR D).
    labels = list(dict.fromkeys(raw + [_displayed_label(label) for label in raw]))
    spellings = labels + [json.dumps(label, ensure_ascii=False) for label in labels]
    if answer in spellings:
        return ""
    if question.get("multiSelect") is True:
        pending, seen, suffixes = [0], set(), []
        while pending:
            offset = pending.pop()
            if offset in seen:
                continue
            seen.add(offset)
            rest = answer[offset:]
            if rest in spellings:
                return ""
            prefixes = [s for s in spellings if rest.startswith(s + ", ")]
            if prefixes:
                pending.extend(offset + len(s) + 2 for s in prefixes)
            else:
                suffixes.append(rest)
        leftover = min(suffixes, key=len, default="")
        if leftover.startswith('"'):
            try:
                decoded = json.loads(leftover)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(decoded, str):
                    return decoded
        return leftover
    # A single-select Other answer with a pasted image is recorded as
    # `<typed> (Image attached)` (2.1.310); the suffix is Claude Code's.
    return answer.removesuffix(" (Image attached)")


def _question_signature(questions: object) -> list[tuple[str, tuple[str, ...]]] | None:
    """Compare question text and labels; UI-only fields may be dropped/added."""
    if not isinstance(questions, list):
        return None
    out = []
    for question in questions:
        if not isinstance(question, dict) or not isinstance(question.get("question"), str):
            return None
        options = question.get("options", [])
        if not isinstance(options, list) or any(
            not isinstance(o, dict) or not isinstance(o.get("label"), str) for o in options
        ):
            return None
        out.append((question["question"], tuple(o["label"] for o in options)))
    return out


def _typed_answer_contains(
    evidence: refs.Ref, verbatim: str, roots: list[Path], *,
    lines: tuple[str, ...] | None = None, sent: provenance.SentIndex | None = None,
) -> bool:
    """Only human answers from a linked interactive question can be quoted.

    Use refs' reader, including its line splitting; strict decoding refuses
    damaged files instead of attributing replacement-decoded text to a person.
    """
    if lines is None:
        lines = refs._lines(refs.locate(evidence, roots=roots), strict=True)
    calls: dict[str, dict] = {}
    entry = None
    for number, raw in enumerate(lines, 1):
        row = refs._entry(raw)
        if row is None:
            continue
        if refs.is_sdk(row):
            return False  # a marker anywhere in this session makes it SDK-driven
        if number > evidence.line:
            continue
        if row.get("type") in ("assistant", "user") and not isinstance(row.get("message"), dict):
            raise StatementUsageError("statement add: malformed transcript message (expected object)")
        if number == evidence.line:
            entry = row
            continue
        if row.get("type") != "assistant":
            continue
        for block in refs._blocks(row):
            if (block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion"
                    and isinstance(block.get("id"), str) and isinstance(block.get("input"), dict)):
                calls[block["id"]] = block["input"]
    if entry is None:
        raise StatementUsageError("statement add: corrupt target row")
    if entry.get("promptSource") == "system":
        return False
    result = entry.get("toolUseResult")
    if not isinstance(result, dict) or "afkTimeoutMs" in result:
        return False
    answers = result.get("answers")
    answers = answers if isinstance(answers, dict) else {}
    quote = " ".join(verbatim.split())
    for block in refs._blocks(entry):
        if (block.get("type") != "tool_result" or block.get("is_error")
                or not isinstance(block.get("tool_use_id"), str)):
            continue
        call = calls.get(block["tool_use_id"])
        if call is None or any(key in call for key in ("answers", "annotations", "response", "followUp")):
            continue
        questions = call.get("questions")
        signature = _question_signature(questions)
        if (not isinstance(questions, list) or signature is None
                or _question_signature(result.get("questions")) != signature):
            continue
        typed = []
        if isinstance(result.get("response"), str):
            typed.append(result["response"])
        for question in questions:
            key = question["question"]
            answer = answers.get(key)
            if isinstance(answer, str):
                typed.append(_free_answer(answer, question))
            annotations = result.get("annotations")
            annotation = annotations.get(key) if isinstance(annotations, dict) else None
            if isinstance(annotation, dict) and isinstance(annotation.get("notes"), str):
                typed.append(annotation["notes"])
        sender_entry = {**entry, "sessionId": entry.get("sessionId") or evidence.session}
        for text in typed:
            if text in ("(notes only)", "(Image attached)", "__other__"):
                continue
            if quote and quote in " ".join(text.split()):
                if sent is None:
                    sent = refs.sent_index(roots)
                if not provenance.agent_written(sender_entry, text, sent):
                    return True
    return False


def _transcript_problem(error: Exception) -> StatementUsageError:
    if isinstance(error, UnicodeError):
        cause = "invalid UTF-8"
    elif isinstance(error, PermissionError):
        cause = "permission denied reading transcript"
    elif isinstance(error, (FileNotFoundError, refs.RefError)):
        cause = "transcript disappeared or became unavailable between reads"
    else:
        cause = f"transcript read failed ({type(error).__name__})"
    return StatementUsageError(f"statement add: {cause}")


def _check_evidence(
    home: Path, message_ref: str, verbatim: str, *, sent: provenance.SentIndex | None = None,
) -> None:
    """Stateless transcript validation, outside the ledger commit lock."""
    if not message_ref.startswith("transcript:"):
        return
    session, number = message_ref[len("transcript:"):].rsplit("#L", 1)
    roots = refs.transcript_roots(home)
    try:
        evidence = refs.resolve(session, line=int(number), roots=roots, sent=sent)
    except refs.CorruptRefError as error:
        raise StatementUsageError("statement add: corrupt target row") from error
    except refs.RefError:
        return  # absent session / line out of range remain compatible
    except (OSError, UnicodeError) as error:
        raise _transcript_problem(error) from error
    try:
        lines = refs._lines(refs.locate(evidence, roots=roots), strict=True)
        if not 1 <= evidence.line <= len(lines):
            raise StatementUsageError("statement add: transcript row disappeared between reads")
        target = refs._entry(lines[evidence.line - 1])
        if target is None:
            raise StatementUsageError("statement add: corrupt target row")
        if target.get("type") in ("user", "assistant") and not isinstance(target.get("message"), dict):
            raise StatementUsageError("statement add: malformed transcript message (expected object)")
        if evidence.role in ("user", "tool_result") and refs.role_of(target) != evidence.role:
            raise StatementUsageError("statement add: transcript row changed between reads")
        if evidence.role == "user":
            return
        if evidence.role == "tool_result" and _typed_answer_contains(
            evidence, verbatim, roots, lines=lines, sent=sent
        ):
            return
    except (refs.RefError, OSError, UnicodeError) as error:
        raise _transcript_problem(error) from error
    raise StatementUsageError(
        "statement add: transcript evidence role must be user, "
        f"found {evidence.role}"
        + ("; quoted words were not typed by the user in a matched AskUserQuestion answer"
           if evidence.role == "tool_result" else "")
    )


def user_message_ref(home: Path | str, session: str, verbatim: str) -> str:
    """``transcript:<session>#L<n>`` for the LATEST row of *session*'s
    transcript that the user typed and that holds *verbatim*
    (S-NEXT-cures-a: ``teach --statement`` is given the words and the
    session, not a line number, so it finds the line itself).

    Read-only. Only a row :func:`add`'s own evidence check accepts counts
    (role ``user`` after rule 10 and the S-94 markers), so words an agent, a
    skill text or a tool result happens to repeat never become a "user
    statement".
    Raises :class:`StatementUsageError` when the session has no transcript
    under the configured roots, or no user row holds the words."""
    roots = refs.transcript_roots(home)
    try:
        ref = refs.resolve(session, roots=roots)
        lines = refs._lines(refs.locate(ref, roots=roots))  # noqa: SLF001
    except refs.RefError as error:
        raise StatementUsageError(
            f"statement: no transcript found for session {session!r} under "
            "the configured transcript roots (refs.transcript_roots)"
        ) from error
    except (OSError, UnicodeError) as error:
        raise _transcript_problem(error) from error
    hits = refs._find_in(lines, verbatim, roles=("user",))  # noqa: SLF001
    # The raw role above is only a prefilter. `add` judges a row with
    # `refs.resolve` (rule 10, the S-94 markers), which can call a row the
    # raw role named `user` an agent's. So each candidate, latest first, goes
    # through the SAME check `add` runs at write time; the first that passes
    # is cited. A statement `add` would refuse is refused here, before the
    # lesson is written, and an earlier row that passes is not lost behind a
    # later one that does not.
    refusal: StatementUsageError | None = None
    sent = refs.sent_index(roots) if hits else None  # built once, not per candidate
    for number in reversed(hits):
        ref = f"transcript:{session}#L{number}"
        try:
            _check_evidence(Path(home), ref, verbatim, sent=sent)
        except StatementUsageError as error:
            refusal = refusal or error
            continue
        return ref
    if refusal is not None:
        raise refusal
    raise StatementUsageError(
        f"statement: no row the user typed in session {session!r} holds "
        "these words; pass the words exactly as the user said them"
    )


def add(
    home: Path | str,
    *,
    verbatim: str,
    source: dict,
    recorded_by: str,
    answers: dict | None = None,
    scope: dict | None = None,
    uncertainty: str | None = None,
    amends: str | None = None,
) -> str:
    """Append one statement line (§3a.3). Idempotent on the dedupe key
    `(source.message_ref, verbatim)`: a second call with the same pair
    returns the EXISTING statement's id and writes nothing new — the same
    "already-applied is a read, not a refusal" idiom `verbs.note`'s
    `--key` uses, not a raw duplicate refusal."""
    home = Path(home)
    if not verbatim or not verbatim.strip():
        raise StatementUsageError("statement add: --verbatim is required")
    if recorded_by not in RECORDED_BY_VALUES:
        raise StatementUsageError(
            f"statement add: recorded_by must be one of {sorted(RECORDED_BY_VALUES)}, "
            f"got {recorded_by!r}"
        )
    if not isinstance(source, dict) or not source.get("message_ref"):
        raise StatementUsageError("statement add: source.message_ref is required")
    message_ref = source["message_ref"]
    if not _MESSAGE_REF_RE.match(message_ref):
        raise StatementUsageError(
            f"statement add: source.message_ref must be transcript:<session>#L<n> "
            f"or conversation:<obs-id>, got {message_ref!r}"
        )

    answers = dict(answers) if answers else {"kind": "proposition", "ref": None, "text": None}
    answers.setdefault("kind", "proposition")
    if answers["kind"] not in ANSWER_KINDS:
        raise StatementUsageError(
            f"statement add: answers.kind must be one of {sorted(ANSWER_KINDS)}, "
            f"got {answers['kind']!r}"
        )
    answers.setdefault("ref", None)
    answers.setdefault("text", None)

    scope = dict(scope) if scope else {"level": "user", "host": None}
    scope.setdefault("host", None)
    if scope.get("level") not in SCOPE_LEVELS:
        raise StatementUsageError(
            f"statement add: scope.level must be one of {sorted(SCOPE_LEVELS)}, "
            f"got {scope.get('level')!r}"
        )
    if scope["level"] == "project" and not scope.get("host"):
        raise StatementUsageError("statement add: scope.level project needs scope.host")

    if amends is not None and not STMT_ID_RE.match(amends):
        raise StatementUsageError(f"statement add: amends malformed: {amends!r}")

    hits = secret_scan(verbatim)
    if hits:
        raise attach_hits(StatementError(format_refusal(hits)), hits)

    # A duplicate is a read: skip transcript I/O only after a locked recheck.
    # The optimistic lookup saves this extra lock span for ordinary new writes.
    if any(row.get("source", {}).get("message_ref") == message_ref
           and row.get("verbatim") == verbatim for row in _read_lines(home)):
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            for row in _read_lines(home):
                if (row.get("source", {}).get("message_ref") == message_ref
                        and row.get("verbatim") == verbatim):
                    return row["id"]
    evidence_error = None
    try:
        _check_evidence(home, message_ref, verbatim)
    except StatementUsageError as error:
        # A concurrent writer may have recorded the same pair; dedupe wins.
        evidence_error = error

    # Astra 4/10 (item 6): the dedupe check, the amends-existence check,
    # and id allocation are all state-dependent — they must read the
    # store AFTER the lock is held, not before, or a peer's write landing
    # in between "read" and "acquire" is invisible to this call and a
    # duplicate (or a false "unknown amends") results. Only pure-input
    # checks (above) run before the lock.
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            existing = _read_lines(home)
            for row in existing:
                if (
                    row.get("source", {}).get("message_ref") == message_ref
                    and row.get("verbatim") == verbatim
                ):
                    return row["id"]  # already recorded — idempotent, nothing written

            if amends is not None and not any(row["id"] == amends for row in existing):
                raise StatementUsageError(
                    f"statement add: amends references unknown statement {amends}"
                )

            # Only a new write enforces the precomputed evidence verdict.
            if evidence_error is not None:
                raise evidence_error

            stmt_id = _new_stmt_id(existing)
            row = {
                "id": stmt_id,
                "at": chrono.now_iso(),
                "verbatim": verbatim,
                "answers": answers,
                "source": dict(source),
                "scope": scope,
                "uncertainty": uncertainty,
                "recorded_by": recorded_by,
                "amends": amends,
            }
            line = json.dumps(row, sort_keys=True)

            path = _path(home)
            prior = path.read_text(encoding="utf-8") if path.exists() else ""
            if prior and not prior.endswith("\n"):
                prior += "\n"
            fsops.atomic_write(path, prior + line + "\n", fsync=True)
            message = f"self-learn: statement add {stmt_id}"
            sha = gitops.stage_and_commit(home, [path], message, None)
            if sha is None:  # pragma: no cover
                raise StatementError("statement add: internal — commit produced nothing")
    finally:
        hold.release()
    return stmt_id


def list_statements(
    home: Path | str,
    *,
    scope_level: str | None = None,
    recorded_by: str | None = None,
    since: str | None = None,
    answers_ref: str | None = None,
) -> list[dict]:
    """Read-only linear scan — the store is append-only JSONL, small by
    construction, and needs no separate cache index."""
    home = Path(home)
    rows = _read_lines(home)
    if scope_level is not None:
        rows = [r for r in rows if r.get("scope", {}).get("level") == scope_level]
    if recorded_by is not None:
        rows = [r for r in rows if r.get("recorded_by") == recorded_by]
    if since is not None:
        rows = [r for r in rows if (r.get("at") or "") >= since]
    if answers_ref is not None:
        rows = [r for r in rows if r.get("answers", {}).get("ref") == answers_ref]
    return rows
