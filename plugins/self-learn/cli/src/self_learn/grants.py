"""The user's standing grant (S-NEXT-attribution; 2026-10-31b decision 6).

One recorded grant replaces every "a person must run this": an agent's
shell may run a person-only command (``host add|remove|rebind|set-mode``,
tier-C ``config set|unset``, ``skill write|rename|retire``) when the ledger
holds the user's standing grant and the agent says why (``--note``). The
commit records ``By: agent``, ``Grant: <statement id>`` and the reason,
never ``human``: the act is the agent's, the grant is what allowed it.

``<ledger>/grants.jsonl`` is append-only, like ``user-statements.jsonl``:

* ``{"id": "grant-…", "op": "grant", "statement": "stmt-…", "verbatim":
  "<the user's words>", "message_ref": "transcript:<session>#L<n>", "at",
  "by": "human"|"agent", "note"}``
* ``{"id": "grant-…", "op": "revoke", "grant": "grant-…", "at", "by",
  "note"}``

A grant is made from a recorded user statement (:mod:`statements`), and
only one the user typed: its transcript line must still resolve, read as
the user's own typing (rule 10, the same reading ``statement add`` makes),
and hold the words. A person or an agent may record it; the agent needs a
reason. Anyone may revoke it; the newest grant not revoked is in force.

:func:`authorize` is the one function every agent-shell refusal of a
person-only command calls. Sudo is outside self-learn and never covered.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import attribution, gitops, intents, refs, sentinel, statements
from .primitives import chrono, fsops
from .scan import format_refusal
from .scan import scan as secret_scan

__all__ = [
    "GRANT_ID_RE",
    "GRANT_KINDS",
    "Grant",
    "GrantError",
    "GrantUsageError",
    "PersonOnlyRefusal",
    "active",
    "add",
    "authorize",
    "clean_note",
    "grants_path",
    "list_rows",
    "revoke",
]

GRANT_ID_RE = re.compile(r"^grant-[0-9a-f]{8}$")
#: The statement kinds (``answers.kind``) a grant may be made from.
GRANT_KINDS = frozenset({"proposition", "instruction"})


class GrantError(Exception):
    """A grant write refused before committing (exit 1)."""

    exit_code = 1


class GrantUsageError(GrantError):
    exit_code = 64


class PersonOnlyRefusal(GrantError):
    """An agent's shell called a person-only command without what lets it
    run there: a reason (exit 64, like any missing argument) or a recorded
    grant (exit 1)."""


def _needs_note(message: str) -> PersonOnlyRefusal:
    refusal = PersonOnlyRefusal(message)
    refusal.exit_code = 64
    return refusal


@dataclass(frozen=True)
class Grant:
    id: str
    statement: str
    verbatim: str
    message_ref: str
    at: str
    by: str
    note: str | None


def grants_path(home: Path | str) -> Path:
    return Path(home) / "grants.jsonl"


def list_rows(home: Path | str) -> list[dict]:
    path = grants_path(home)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _grant_of(row: dict) -> Grant:
    return Grant(
        id=row["id"], statement=row["statement"], verbatim=row["verbatim"],
        message_ref=row["message_ref"], at=row["at"], by=row["by"], note=row.get("note"),
    )


def active(home: Path | str) -> Grant | None:
    """The newest grant no later row revokes, or ``None``."""
    rows = list_rows(home)
    revoked = {row.get("grant") for row in rows if row.get("op") == "revoke"}
    for row in reversed(rows):
        if row.get("op") == "grant" and row.get("id") not in revoked:
            return _grant_of(row)
    return None


def _shell() -> str:
    from . import settings  # lazy: settings imports ledger, which imports hosts

    return "agent" if settings.agent_caller() else "human"


def clean_note(note: str | None, surface: str) -> str | None:
    """*note* stripped, ``None`` when empty; refused when the secret scan
    matches it (it becomes a commit body)."""
    if note is None or not note.strip():
        return None
    hits = secret_scan(note)
    if hits:
        raise GrantError(f"{surface}: --note: {format_refusal(hits)}")
    return note.strip()


def _typed_words(home: Path, message_ref: str, verbatim: str) -> None:
    """Refuse unless *message_ref* is a transcript line self-learn can read
    now, the user typed it, and it holds *verbatim*. Stricter than
    ``statement add``'s own check, which lets a transcript it cannot find
    pass: a grant is never made from words nobody can show were typed."""
    if not message_ref.startswith("transcript:"):
        raise GrantError(
            "grant add: the statement's words were not recorded from a transcript "
            f"line ({message_ref}); a grant needs the line the user typed them on"
        )
    session, _sep, number = message_ref[len("transcript:"):].rpartition("#L")
    roots = refs.transcript_roots(home)
    try:
        ref = refs.resolve(session, line=int(number), roots=roots)
        lines = refs._lines(refs.locate(ref, roots=roots))  # noqa: SLF001
    except (refs.RefError, ValueError) as exc:
        raise GrantError(
            f"grant add: the transcript line {message_ref} cannot be read ({exc}); "
            "a grant needs a line self-learn can show the user typed"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise GrantError(f"grant add: the transcript could not be read ({exc})") from exc
    if ref.role != "user":
        raise GrantError(
            f"grant add: {message_ref} is not a line the user typed (it reads as {ref.role})"
        )
    entry = refs._entry(lines[ref.line - 1])  # noqa: SLF001
    text = " ".join(refs._raw_text(entry).split()) if entry else ""  # noqa: SLF001
    if " ".join(verbatim.split()) not in text:
        raise GrantError(
            f"grant add: the line {message_ref} does not hold the statement's words"
        )


def _new_id(rows: list[dict]) -> str:
    seen = {row.get("id") for row in rows}
    for _ in range(64):
        candidate = "grant-" + uuid.uuid4().hex[:8]
        if candidate not in seen:
            return candidate
    raise GrantError("grant: could not allocate a unique id")  # pragma: no cover


def _append(home: Path, row: dict, subject: str, body: str | None) -> None:
    """Append *row* and commit it. Callers hold :func:`intents.ledger_write`."""
    path = grants_path(home)
    prior = path.read_text(encoding="utf-8") if path.exists() else ""
    if prior and not prior.endswith("\n"):
        prior += "\n"
    fsops.atomic_write(path, prior + json.dumps(row, sort_keys=True) + "\n", fsync=True)
    gitops.stage_and_commit(home, [path], subject, body)


def add(home: Path | str, *, statement: str, note: str | None = None) -> tuple[Grant, bool]:
    """Record the user's standing grant from *statement*. Returns ``(grant,
    created)``; a grant already in force from the same statement is returned
    with ``created=False`` and nothing is written.

    From an agent's shell *note* (why the agent records it) is required, and
    the commit says ``By: agent`` and ``Grant: <statement>``: the statement
    itself is the authority, so an agent can record the grant the user typed
    but never one the user did not."""
    home = Path(home)
    if not statements.STMT_ID_RE.match(statement):
        raise GrantUsageError(f"grant add: --statement must be a stmt- id, got {statement!r}")
    shell = _shell()
    reason = clean_note(note, "grant add")
    if shell == "agent" and reason is None:
        raise _needs_note(
            "grant add: from an agent's shell say why with --note TEXT; the ledger "
            "records it as By: agent"
        )
    row = next((r for r in statements.list_statements(home) if r.get("id") == statement), None)
    if row is None:
        raise GrantUsageError(f"grant add: no statement {statement} in this ledger")
    if (row.get("scope") or {}).get("level") != "user":
        raise GrantError(
            f"grant add: {statement} is scoped to a project; a standing grant is the "
            "user's own word for everything"
        )
    kind = (row.get("answers") or {}).get("kind")
    if kind not in GRANT_KINDS:
        # Gate r1 finding 6: a question the user asked grants nothing. Which
        # typed proposition or instruction is a grant is not something code
        # can read; the words are copied into the record, printed on every
        # command run under it and written into each commit it allows, so a
        # wrong choice is visible wherever it is used, and `grant revoke`
        # ends it (02 §3a.3a).
        raise GrantError(
            f"grant add: {statement} records a {kind or 'statement of no kind'}; a standing "
            "grant is made from something the user stated or instructed "
            f"({' or '.join(sorted(GRANT_KINDS))}), never from a question"
        )
    verbatim = row.get("verbatim") or ""
    message_ref = (row.get("source") or {}).get("message_ref") or ""
    _typed_words(home, message_ref, verbatim)
    granted = (
        attribution.Authority("grant", statement, reason, words=verbatim)
        if shell == "agent" and reason
        else None
    )
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            current = active(home)
            if current is not None and current.statement == statement:
                return current, False
            rows = list_rows(home)
            new = {
                "id": _new_id(rows),
                "op": "grant",
                "statement": statement,
                "verbatim": verbatim,
                "message_ref": message_ref,
                "at": chrono.now_iso(),
                "by": shell,
                "note": reason,
            }
            # The user's words ride the commit either way (gate r1 finding 6):
            # under the agent's authority as its paragraph, else as the body.
            words = f'The user\'s words ({message_ref}): "{" ".join(verbatim.split())}"'
            with attribution.acting(granted):
                _append(
                    home, new, f"self-learn: grant add {new['id']} ({statement})",
                    "\n\n".join(p for p in (reason, words) if p) if granted is None else None,
                )
    finally:
        hold.release()
    return _grant_of(new), True


def revoke(home: Path | str, grant_id: str, *, note: str | None = None) -> bool:
    """End *grant_id*. Anyone may (it only takes power away); from an
    agent's shell *note* is required. Returns False when it was already
    revoked (nothing written)."""
    home = Path(home)
    if not GRANT_ID_RE.match(grant_id):
        raise GrantUsageError(f"grant revoke: not a grant id: {grant_id!r}")
    shell = _shell()
    reason = clean_note(note, "grant revoke")
    if shell == "agent" and reason is None:
        raise _needs_note("grant revoke: from an agent's shell say why with --note TEXT")
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            rows = list_rows(home)
            if not any(r.get("op") == "grant" and r.get("id") == grant_id for r in rows):
                raise GrantUsageError(f"grant revoke: no grant {grant_id} in this ledger")
            if any(r.get("op") == "revoke" and r.get("grant") == grant_id for r in rows):
                return False
            new = {
                "id": _new_id(rows),
                "op": "revoke",
                "grant": grant_id,
                "at": chrono.now_iso(),
                "by": shell,
                "note": reason,
            }
            _append(home, new, f"self-learn: grant revoke {grant_id}", reason)
    finally:
        hold.release()
    return True


def authorize(home: Path | str, surface: str, *, note: str | None) -> attribution.Authority | None:
    """The gate every agent-shell refusal of a person-only command calls.

    A person's own terminal: ``None`` (nothing needed, the commit says
    ``By: human``). An agent's shell: the :class:`attribution.Authority`
    already in force (a typed yes the overseer proved), else the user's
    standing grant with *note* as the reason. Raises
    :class:`PersonOnlyRefusal` with no reason (exit 64) or no grant in force
    (exit 1). The caller puts the result in force with
    :func:`attribution.acting` around the command's own writes."""
    from . import settings  # lazy: settings imports ledger, which imports hosts

    if not settings.agent_caller():
        return None
    current = attribution.authority()
    if current is not None:
        return current
    markers = ", ".join(settings.agent_caller_markers())
    reason = clean_note(note, surface)
    granted = active(home)
    if reason is None:
        under = (
            f" ({granted.statement}: \"{_flat(granted.verbatim)}\")" if granted is not None else ""
        )
        raise _needs_note(
            f"{surface} is a person-only command; from an agent's shell it runs under "
            f"the user's standing grant{under} and needs --note TEXT saying why (the ledger "
            f"records By: agent, the grant and the reason) (agent shell detected: {markers})"
        )
    if granted is None:
        raise PersonOnlyRefusal(
            f"{surface} is a person-only command and this ledger holds no standing grant "
            "for an agent to run it under. Record the user's grant from the statement "
            "they typed it in: `self-learn grant add --statement <stmt-id> --note "
            f"\"<why>\"` (`self-learn statement list` finds it) (agent shell detected: {markers})"
        )
    # Gate r1 finding 6: every command run under the grant says, where it
    # runs, which words of the user's it runs under.
    print(
        f"{surface}: running under the user's standing grant {granted.statement} "
        f"(\"{_flat(granted.verbatim)}\"); the ledger records By: agent",
        file=sys.stderr,
    )
    return attribution.Authority("grant", granted.statement, reason, words=granted.verbatim)


def _flat(text: str) -> str:
    return " ".join(text.split())
