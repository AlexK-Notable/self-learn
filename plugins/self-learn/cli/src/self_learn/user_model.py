"""The model of the user (U2, `02-schema.md` §3a.4, S-65).

``<ledger>/user-model.md`` — one Markdown file, YAML frontmatter, five
containers (A-E) grouping entries by source. **No entry is ever deleted
or edited into a different claim** — a change is either a new
``LAPSED`` status (naming its date and cause) or a brand new entry.
**There is no time-based lapse anywhere in this module** — D6, seam
reconciliation addendum: "No retirement of a reading for silence. A
reading lapses only on changed conditions or contrary evidence." Grep
proof: this file contains no elapsed-time arithmetic and no clock-age
computation of any kind (nothing to grep for lands a hit here).

**Vocabulary (D2, binding).** The words "ratified", "ruled", "stated",
and "contradicted" are refused (whole-word, case-insensitive) in any
entry's ``title``/``because``/``changed_condition``.

Public surface:

    add_entry(home, *, container, title, because, source, by, ...) -> str
    lapse_entry(home, entry_id, *, changed_condition=None, contrary=None,
                consolidated_into=None, by, at=None) -> str
    mark_seen(home, entry_id) -> Path                  # called only from
                                                         # cases.observe
    bump_revision(home, *, by) -> int
    show(home) -> dict

Rendering note: the spec's own worked examples (§3a.4) pack several
sub-fields onto one bullet line (``- source: system-reading; ref: …;
statements: […]; provisional: true``). This module renders ONE field per
bullet line instead — the same field set and semantics, laid out so this
module's own reader never needs to disambiguate a ``;``-separated value
from a ``;``-separated field list (a `because` or `ref` free-text field
could legitimately contain a semicolon). This is a rendering choice, not
a content difference; see this unit's report for the note."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from . import gitops, intents, sentinel
from .primitives import chrono, fsops
from .primitives.yamlio import rt_yaml
from .scan import format_refusal
from .scan import scan as secret_scan

__all__ = [
    "CONTAINERS",
    "ACTORS",
    "SOURCES",
    "STATUSES",
    "UM_ID_RE",
    "UserModelError",
    "UserModelUsageError",
    "add_entry",
    "lapse_entry",
    "mark_seen",
    "bump_revision",
    "show",
]

CONTAINERS = ("A", "B", "C", "D", "E")
_CONTAINER_TITLES = {
    "A": "## A. From the user's own words",
    "B": "## B. System readings the user has seen",
    "C": "## C. System readings, provisional",
    "D": "## D. Observed regularities",
    "E": "## E. Declared conditions",
}
#: §3a.4 table — who may ADD directly to each container. B is empty on
#: purpose: "nobody writes here directly — an entry moves here when a
#: presentation record names it" (only :func:`mark_seen` populates it).
_WHO_MAY_ADD: dict[str, frozenset[str]] = {
    "A": frozenset({"human", "steward", "overseer"}),
    "B": frozenset(),
    "C": frozenset({"steward", "overseer"}),
    "D": frozenset({"overseer"}),
    "E": frozenset({"human", "steward", "overseer"}),
}
#: Who may mark an entry LAPSED, per container.
_WHO_MAY_LAPSE: dict[str, frozenset[str]] = {
    "A": frozenset({"human", "steward", "overseer"}),
    "B": frozenset({"human", "steward", "overseer"}),
    "C": frozenset({"human", "steward", "overseer"}),
    "D": frozenset({"human", "overseer"}),
    "E": frozenset({"human", "steward", "overseer"}),
}
#: Same 3-name universe as `cases.ACTORS` / `statements.RECORDED_BY_VALUES`
#: — kept as this module's own constant so this module never imports
#: `cases` (which imports THIS module, for `mark_seen`; a reverse import
#: would cycle).
ACTORS = frozenset({"human", "steward", "overseer"})
SOURCES = frozenset({"own-words", "system-reading"})
STATUSES = frozenset({"CURRENT", "LAPSED"})

UM_ID_RE = re.compile(r"^um-[0-9a-f]{4}$")

#: D2: never used, anywhere, for a user-model entry.
_FORBIDDEN_RE = re.compile(r"\b(ratified|ruled|stated|contradicted)\b", re.IGNORECASE)

_DELIM = "---"
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_CONTAINER_HEADING_RE = re.compile(r"^## ([A-E])\.[^\n]*$", re.MULTILINE)
_ENTRY_HEADING_RE = re.compile(
    r"^### (um-[0-9a-f]{4}) — (.*?)\s+\(r(\d+)\)\s*$", re.MULTILINE
)


class UserModelError(Exception):
    """A user-model write refused before committing."""

    exit_code = 1


class UserModelUsageError(UserModelError):
    """Malformed invocation / unknown entry id — sysexits EX_USAGE."""

    exit_code = 64


def _doc_path(home: Path) -> Path:
    return home / "user-model.md"


def _yaml():
    return rt_yaml(preserve_quotes=True, width=4096, default_flow_style=False)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise UserModelError("user-model: file is not frontmatter + body — malformed")
    fm = _yaml().load(m.group(1))
    return dict(fm or {}), m.group(2)


def _render_frontmatter(fm: dict) -> str:
    import io

    buf = io.StringIO()
    _yaml().dump(fm, buf)
    return f"{_DELIM}\n{buf.getvalue()}{_DELIM}\n"


def _check_vocabulary(*texts: str | None) -> None:
    for text in texts:
        if text and _FORBIDDEN_RE.search(text):
            raise UserModelError(
                "user-model: forbidden vocabulary — 'ratified'/'ruled'/'stated'/"
                "'contradicted' are never used for a user-model entry (D2)"
            )


def _fmt_list(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]"


def _parse_scalar(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [tok.strip() for tok in inner.split(",") if tok.strip()]
    return value


def _split_containers(body: str) -> dict[str, str]:
    matches = list(_CONTAINER_HEADING_RE.finditer(body))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[m.group(1)] = body[start:end]
    return out


def _split_entries(container_text: str) -> list[tuple[str, str, int, str]]:
    matches = list(_ENTRY_HEADING_RE.finditer(container_text))
    out = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(container_text)
        out.append((m.group(1), m.group(2), int(m.group(3)), container_text[start:end]))
    return out


def _parse_entry_fields(body: str) -> dict:
    fields: dict[str, Any] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        key, sep, value = line[2:].partition(": ")
        if not sep:
            continue
        fields[key.strip()] = _parse_scalar(value.strip())
    return fields


def _entry_from_block(entry_id: str, title: str, r: int, body: str) -> dict:
    fields = _parse_entry_fields(body)
    fields.update({"id": entry_id, "title": title, "r": r})
    return fields


def _load(home: Path) -> tuple[dict, dict[str, list[dict]]]:
    path = _doc_path(home)
    if not path.exists():
        return (
            {"revision": 0, "updated_at": None, "updated_by": None},
            {c: [] for c in CONTAINERS},
        )
    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)
    container_texts = _split_containers(body)
    containers: dict[str, list[dict]] = {}
    for letter in CONTAINERS:
        raw = container_texts.get(letter, "")
        containers[letter] = [_entry_from_block(*e) for e in _split_entries(raw)]
    return fm, containers


def _render_entry(e: dict) -> str:
    lines = [f"### {e['id']} — {e['title']}          (r{e['r']})"]
    lines.append(f"- held_since: {e['held_since']}")
    lines.append(f"- because: {e['because']}")
    lines.append(f"- conditions: {_fmt_list(e.get('conditions') or [])}")
    lines.append(f"- status: {e['status']}")
    if e["status"] == "LAPSED":
        lines.append(f"- lapsed_at: {e['lapsed_at']}")
        lines.append(f"- changed_condition: {e['changed_condition']}")
    lines.append(f"- source: {e['source']}")
    if e.get("ref") is not None:
        lines.append(f"- ref: {e['ref']}")
    if e.get("statements"):
        lines.append(f"- statements: {_fmt_list(e['statements'])}")
    if e.get("recorded_by") is not None:
        lines.append(f"- recorded_by: {e['recorded_by']}")
    if e.get("basis"):
        lines.append(f"- basis: {_fmt_list(e['basis'])}")
    if "provisional" in e and e["provisional"] is not None:
        lines.append(f"- provisional: {'true' if e['provisional'] else 'false'}")
    return "\n".join(lines) + "\n"


def _render_doc(fm: dict, containers: dict[str, list[dict]]) -> str:
    parts = [_render_frontmatter(fm)]
    for letter in CONTAINERS:
        parts.append(_CONTAINER_TITLES[letter])
        parts.append("")
        for e in containers[letter]:
            parts.append(_render_entry(e).rstrip("\n"))
            parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def _save(home: Path, fm: dict, containers: dict[str, list[dict]], *, by: str | None) -> tuple[Path, dict]:
    new_fm = dict(fm)
    new_fm["revision"] = int(fm.get("revision") or 0) + 1
    new_fm["updated_at"] = chrono.now_iso()
    if by is not None:
        new_fm["updated_by"] = by
    elif "updated_by" not in new_fm:
        new_fm["updated_by"] = None
    path = _doc_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, _render_doc(new_fm, containers), fsync=True)
    return path, new_fm


def _find(containers: dict[str, list[dict]], entry_id: str) -> tuple[str | None, dict | None]:
    for letter in CONTAINERS:
        for e in containers[letter]:
            if e["id"] == entry_id:
                return letter, e
    return None, None


def _new_um_id(containers: dict[str, list[dict]]) -> str:
    existing = {e["id"] for letter in CONTAINERS for e in containers[letter]}
    for _ in range(4096):
        candidate = "um-" + uuid.uuid4().hex[:4]
        if candidate not in existing:
            return candidate
    raise UserModelError("user-model: could not allocate a unique entry id")  # pragma: no cover


# ------------------------------------------------------------- add_entry


def add_entry(
    home: Path | str,
    *,
    container: str,
    title: str,
    because: str,
    source: str,
    by: str,
    held_since: str | None = None,
    conditions: list[str] | None = None,
    ref: str | None = None,
    statements: list[str] | None = None,
    recorded_by: str | None = None,
    basis: list[str] | None = None,
    provisional: bool | None = None,
) -> str:
    """Add one entry to *container* (§3a.4 table). Refuses a container/
    source mismatch, a container B add (nobody adds there directly — see
    :func:`mark_seen`), an actor not permitted for that container, a B/C
    system-reading with no statement id (R-6c), forbidden vocabulary, or
    a secret-scan hit on `title`/`because`."""
    home = Path(home)
    if container not in CONTAINERS:
        raise UserModelUsageError(f"user-model add: container must be one of {CONTAINERS}, got {container!r}")
    if by not in ACTORS:
        raise UserModelUsageError(f"user-model add: by must be one of {sorted(ACTORS)}, got {by!r}")
    if by not in _WHO_MAY_ADD[container]:
        raise UserModelError(
            f"user-model add: container {container} may not be added to by {by!r} (§3a.4)"
        )
    if source not in SOURCES:
        raise UserModelUsageError(f"user-model add: source must be one of {sorted(SOURCES)}, got {source!r}")
    if container == "A" and source != "own-words":
        raise UserModelError("user-model add: container A holds only own-words entries")
    if container in ("C", "D") and source != "system-reading":
        raise UserModelError(f"user-model add: container {container} holds only system-reading entries")
    if not title or not title.strip():
        raise UserModelUsageError("user-model add: title is required")
    if not because or not because.strip():
        raise UserModelUsageError("user-model add: because is required")

    _check_vocabulary(title, because)
    hits = secret_scan(title) + secret_scan(because)
    if hits:
        raise UserModelError(format_refusal(hits))

    statements = list(statements or [])
    if source == "system-reading":
        if container in ("B", "C") and not statements:
            raise UserModelError(
                f"user-model add: a {container} entry needs at least one statement id (R-6c)"
            )
        if not ref:
            raise UserModelUsageError("user-model add: system-reading entries need a ref")
    if source == "own-words" and not ref:
        raise UserModelUsageError("user-model add: own-words entries need a stmt-... ref")

    fm, containers_map = _load(home)
    entry_id = _new_um_id(containers_map)
    entry: dict[str, Any] = {
        "id": entry_id,
        "title": title,
        "r": 1,
        "held_since": held_since or chrono.now_iso()[:10],
        "because": because,
        "conditions": list(conditions or []),
        "status": "CURRENT",
        "source": source,
        "ref": ref,
    }
    if source == "system-reading":
        entry["statements"] = statements
        entry["provisional"] = True if provisional is None else bool(provisional)
    else:
        if recorded_by is not None:
            entry["recorded_by"] = recorded_by
    if basis:
        entry["basis"] = list(basis)

    containers_map = dict(containers_map)
    containers_map[container] = containers_map[container] + [entry]

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            path, _new_fm = _save(home, fm, containers_map, by=by)
            message = f"self-learn: user-model add {entry_id} ({container})"
            sha = gitops.stage_and_commit(home, [path], message, because)
            if sha is None:  # pragma: no cover
                raise UserModelError("user-model add: internal — commit produced nothing")
    finally:
        hold.release()
    return entry_id


# ----------------------------------------------------------- lapse_entry


def lapse_entry(
    home: Path | str,
    entry_id: str,
    *,
    changed_condition: str | None = None,
    contrary: str | None = None,
    consolidated_into: str | None = None,
    by: str,
    at: str | None = None,
) -> str:
    """Mark *entry_id* LAPSED. Refuses without EXACTLY one of
    `changed_condition`/`contrary`/`consolidated_into` — D6/S-65:
    "nothing lapses for lack of a reply", so every lapse names a cause;
    there is no code path here that lapses on elapsed clock time (see
    this module's own docstring for the grep proof)."""
    home = Path(home)
    if by not in ACTORS:
        raise UserModelUsageError(f"user-model lapse: by must be one of {sorted(ACTORS)}, got {by!r}")
    named = [x for x in (changed_condition, contrary, consolidated_into) if x]
    if len(named) != 1:
        raise UserModelUsageError(
            "user-model lapse: needs exactly one of --changed-condition / "
            "--contrary / --consolidated-into"
        )
    if UM_ID_RE.match(entry_id) is None:
        raise UserModelUsageError(f"user-model lapse: malformed entry id {entry_id!r}")

    fm, containers_map = _load(home)
    letter, found = _find(containers_map, entry_id)
    if found is None or letter is None:
        raise UserModelUsageError(f"user-model lapse: unknown entry {entry_id}")
    if by not in _WHO_MAY_LAPSE[letter]:
        raise UserModelError(f"user-model lapse: container {letter} may not be lapsed by {by!r}")
    if found.get("status") == "LAPSED":
        raise UserModelError(f"user-model lapse: {entry_id} is already LAPSED")

    if consolidated_into is not None:
        changed_text = f"consolidated-into:{consolidated_into}"
    else:
        changed_text = changed_condition or contrary
    _check_vocabulary(changed_text)

    new_entry = dict(found)
    new_entry["r"] = int(found["r"]) + 1
    new_entry["status"] = "LAPSED"
    new_entry["lapsed_at"] = at or chrono.now_iso()[:10]
    new_entry["changed_condition"] = changed_text

    containers_map = dict(containers_map)
    containers_map[letter] = [new_entry if e["id"] == entry_id else e for e in containers_map[letter]]

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            path, _new_fm = _save(home, fm, containers_map, by=by)
            message = f"self-learn: user-model lapse {entry_id}"
            sha = gitops.stage_and_commit(home, [path], message, changed_text)
            if sha is None:  # pragma: no cover
                raise UserModelError("user-model lapse: internal — commit produced nothing")
    finally:
        hold.release()
    return entry_id


# ------------------------------------------------------------- mark_seen


def mark_seen(home: Path | str, entry_id: str) -> Path:
    """Flip a system-reading entry's STORED `provisional` field
    `true` -> `false`; move it from container C or D into B (§3a.4 table
    B: "an entry moves here when a presentation record names it").
    Changes NOTHING else about the entry — never bumps its own `r`
    (a presentation is not a dependency move; bumping `r` here would make
    every case citing `um-…@rN` read as "the dependency moved" merely
    because the user was shown it, which is exactly the confusion the
    revision counter exists to avoid). Refuses on an own-words entry (no
    `provisional` field) or an unknown id. A no-op on an entry that is
    already `provisional: false` (still writes/commits — idempotent, not
    an error). Called only from `cases.observe` with `kind: presented`,
    per §3a.2/§3a.4 — never a standalone CLI verb (no `user-model
    mark-seen` in the CLI's parser)."""
    home = Path(home)
    if UM_ID_RE.match(entry_id) is None:
        raise UserModelUsageError(f"user-model: malformed entry id {entry_id!r}")

    fm, containers_map = _load(home)
    letter, found = _find(containers_map, entry_id)
    if found is None or letter is None:
        raise UserModelUsageError(f"user-model: unknown entry {entry_id}")
    if found.get("source") != "system-reading" or "provisional" not in found:
        raise UserModelError(
            f"user-model: {entry_id} has no provisional field — own-words "
            "entries are never marked seen"
        )

    containers_map = dict(containers_map)
    if found["provisional"] is False:
        new_containers = containers_map  # no-op: already seen
    else:
        new_entry = dict(found)
        new_entry["provisional"] = False
        if letter in ("C", "D"):
            containers_map[letter] = [e for e in containers_map[letter] if e["id"] != entry_id]
            containers_map["B"] = containers_map["B"] + [new_entry]
        else:  # letter == "B" already, or a future container — flip in place
            containers_map[letter] = [
                new_entry if e["id"] == entry_id else e for e in containers_map[letter]
            ]
        new_containers = containers_map

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            path, _new_fm = _save(home, fm, new_containers, by=None)
            message = f"self-learn: user-model mark-seen {entry_id}"
            sha = gitops.stage_and_commit(home, [path], message, None)
            if sha is None:  # pragma: no cover
                raise UserModelError("user-model mark-seen: internal — commit produced nothing")
    finally:
        hold.release()
    return path


# --------------------------------------------------------- bump_revision


def bump_revision(home: Path | str, *, by: str) -> int:
    """A bare "touch": bumps the document's `revision`/`updated_at`/
    `updated_by` without adding or lapsing any entry. Not in the spec's
    or the interface draft's verb table — this unit's OWN brief names it
    in the CLI wiring line; see this unit's report for the discrepancy
    against `commands/review.md`, which shows no `user-model bump`."""
    home = Path(home)
    if by not in ACTORS:
        raise UserModelUsageError(f"user-model bump: by must be one of {sorted(ACTORS)}, got {by!r}")
    fm, containers_map = _load(home)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            path, new_fm = _save(home, fm, containers_map, by=by)
            message = "self-learn: user-model bump"
            sha = gitops.stage_and_commit(home, [path], message, None)
            if sha is None:  # pragma: no cover
                raise UserModelError("user-model bump: internal — commit produced nothing")
    finally:
        hold.release()
    return int(new_fm["revision"])


# ---------------------------------------------------------------- show


def show(home: Path | str) -> dict:
    """Read-only: the whole document as `{"frontmatter": {...},
    "containers": {"A": [...], ..., "E": [...]}}`."""
    home = Path(home)
    fm, containers_map = _load(home)
    return {"frontmatter": fm, "containers": containers_map}
