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

from . import gitops, intents, sentinel
from .primitives import chrono, fsops
from .scan import format_refusal
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
        raise StatementError(format_refusal(hits))

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
