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
    mark_seen(home, entry_id) -> Path                  # standalone: own
                                                         # lock span, own commit
    show(home) -> dict

`_mark_seen_locked(home, entry_ids)` is the internal counterpart:
validates every id, flips, and `_save`s — but does NOT commit. It
assumes the CALLER already holds the ledger lock (its own, or a nested
pass-through). `mark_seen` is a thin wrapper that opens its own lock and
commits alone; `cases.observe(kind="presented")` calls the locked helper
directly, inside its OWN already-open span, so the case file's write and
every named entry's flip land in ONE commit (fold-u2-r1 item 1 / B1: a
refused observation must never leave a flipped entry with no
presentation record — see `_mark_seen_locked`'s own docstring for how it
guarantees that).

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

#: Gate r2 B1 / Astra 12: `title`, `because`, the lapse cause/contrary
#: text, and `ref` are interpolated straight into this module's
#: line-structured document (`_render_entry`) and reparsed by two bare
#: regexes (`_CONTAINER_HEADING_RE`, `_ENTRY_HEADING_RE`) plus a
#: `- key: value` line scanner (`_parse_entry_fields`) that has no
#: notion of "this line belongs to a different field" — an EMBEDDED
#: NEWLINE in any of these fields therefore becomes structure on the
#: next read (a forged container/entry heading, or a `- key: value`
#: line that silently overwrites a real field on re-parse). D-i's own
#: fix on the CASE side used `^## ` (exactly two hashes) because case
#: headings are always spelled that way; this module's own headings are
#: NOT uniform (`## A.`/`## B.` for containers, `### um-… — …` for
#: entries), so `^## ` alone would miss a forged THREE-hash entry
#: heading — the gate's own probe forged one. Refused here the same
#: secret-scan-style way `cases._refuse_headings` refuses a case's free
#: text: never escaped, never silently accepted.
_STRUCTURAL_RE = re.compile(r"\n|^#+", re.MULTILINE)


def _refuse_structural(*texts: str | None) -> None:
    for text in texts:
        if text and _STRUCTURAL_RE.search(text):
            raise UserModelError(
                "user-model: a free-text field contains an embedded newline "
                "or a leading '#' heading-shaped line — refused (structural "
                "refusal, gate r2 B1)"
            )


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
) -> str:
    """Add one entry to *container* (§3a.4 table). Refuses a container/
    source mismatch, a container B add (nobody adds there directly — see
    :func:`mark_seen`), a container E system-reading add (S10: E holds
    only own-words entries — human unconditionally, steward/overseer
    only with an own-words reference), an actor not permitted for that
    container, a B/C system-reading with no statement id (R-6c),
    forbidden vocabulary, or a secret-scan hit on `title`/`because`.

    D-f: there is no `provisional` parameter — a system-reading entry is
    ALWAYS created `provisional: true` (an own-words entry never carries
    the field at all); no caller, CLI or Python, can create an
    already-seen reading."""
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
    if container == "E" and source != "own-words":
        raise UserModelError(
            "user-model add: container E holds only own-words entries (S10, §3a.4 E row)"
        )
    if not title or not title.strip():
        raise UserModelUsageError("user-model add: title is required")
    if not because or not because.strip():
        raise UserModelUsageError("user-model add: because is required")

    _check_vocabulary(title, because)
    hits = secret_scan(title) + secret_scan(because)
    if hits:
        raise UserModelError(format_refusal(hits))
    # Gate r2 B1 / Astra 12: refuse before any write, same as the secret
    # scan just above — `ref` is included because it too is rendered as
    # a raw line (`_render_entry`'s `- ref: …`).
    _refuse_structural(title, because, ref)
    # Fold r2 residual (builder's own post-commit find): the list-shaped
    # fields render through `_fmt_list` as raw text on one line each, so
    # every ITEM is a free-text field too — refuse per item.
    _refuse_structural(*(conditions or []), *(statements or []), *(basis or []))

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

    # Astra 4/10 (item 6): id allocation is state-dependent (it must see
    # every currently-live id to avoid a collision) — load and allocate
    # INSIDE the lock, not before it. Every check above is pure input,
    # unaffected by a concurrent writer, and stays outside.
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
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
                entry["provisional"] = True
            else:
                if recorded_by is not None:
                    entry["recorded_by"] = recorded_by
            if basis:
                entry["basis"] = list(basis)

            containers_map = dict(containers_map)
            containers_map[container] = containers_map[container] + [entry]

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

    if consolidated_into is not None:
        changed_text = f"consolidated-into:{consolidated_into}"
    else:
        changed_text = changed_condition or contrary
    # `named` above already guarantees exactly one of the three is
    # truthy, so this is never None here — asserted, not re-validated,
    # purely so the type checker sees a plain `str` from here on.
    assert changed_text is not None
    _check_vocabulary(changed_text)
    # B2 (item 2): the changed-condition/contrary text is free text like
    # any other — scan it before it can ever reach the committed file.
    hits = secret_scan(changed_text)
    if hits:
        raise UserModelError(format_refusal(hits))
    # Gate r2 B1 / Astra 12: same structural refusal as `add_entry` — the
    # lapse cause is rendered as `- changed_condition: …`, one more line
    # a newline could turn into forged structure.
    _refuse_structural(changed_text)

    # Astra 4/10 (item 6): `_load`/`_find` (and the checks that depend on
    # what they find — permission-by-container, already-LAPSED) are
    # state-dependent and move inside the lock; only the pure-input
    # checks above (actor shape, exactly-one-cause, id shape, vocabulary,
    # secret scan) run before it.
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            fm, containers_map = _load(home)
            letter, found = _find(containers_map, entry_id)
            if found is None or letter is None:
                raise UserModelUsageError(f"user-model lapse: unknown entry {entry_id}")
            if by not in _WHO_MAY_LAPSE[letter]:
                raise UserModelError(f"user-model lapse: container {letter} may not be lapsed by {by!r}")
            if found.get("status") == "LAPSED":
                raise UserModelError(f"user-model lapse: {entry_id} is already LAPSED")

            new_entry = dict(found)
            new_entry["r"] = int(found["r"]) + 1
            new_entry["status"] = "LAPSED"
            new_entry["lapsed_at"] = at or chrono.now_iso()[:10]
            new_entry["changed_condition"] = changed_text

            containers_map = dict(containers_map)
            containers_map[letter] = [
                new_entry if e["id"] == entry_id else e for e in containers_map[letter]
            ]

            path, _new_fm = _save(home, fm, containers_map, by=by)
            message = f"self-learn: user-model lapse {entry_id}"
            sha = gitops.stage_and_commit(home, [path], message, changed_text)
            if sha is None:  # pragma: no cover
                raise UserModelError("user-model lapse: internal — commit produced nothing")
    finally:
        hold.release()
    return entry_id


# ------------------------------------------------------------- mark_seen


def _validate_seen(
    home: Path | str, entry_ids: list[str]
) -> tuple[dict, dict[str, list[dict]], dict[str, tuple[str, dict]]]:
    """Load (under the caller's already-open lock) and validate every id
    in *entry_ids* — well-formed, known, `source == system-reading` (has
    a `provisional` field) — performing NO writes. Raises on the FIRST
    invalid id. Split out of the old single `_mark_seen_locked` (gate r2
    S2) so a caller with its OWN file to write first (`cases.observe`)
    can validate here — before ANYTHING is written anywhere (B1) — then
    write its own file, then call :func:`_apply_seen` for the flip,
    bracketing the two writes with an intent for crash recovery. Returns
    `(fm, containers_map, targets)` — `targets` maps each entry id to its
    `(container_letter, entry_dict)`, ready for :func:`_apply_seen`."""
    home = Path(home)
    fm, containers_map = _load(home)
    targets: dict[str, tuple[str, dict]] = {}
    for entry_id in entry_ids:
        if UM_ID_RE.match(entry_id) is None:
            raise UserModelUsageError(f"user-model: malformed entry id {entry_id!r}")
        letter, found = _find(containers_map, entry_id)
        if found is None or letter is None:
            raise UserModelUsageError(f"user-model: unknown entry {entry_id}")
        if found.get("source") != "system-reading" or "provisional" not in found:
            raise UserModelError(
                f"user-model: {entry_id} has no provisional field — own-words "
                "entries are never marked seen"
            )
        targets[entry_id] = (letter, found)
    return fm, containers_map, targets


def _apply_seen(
    home: Path | str,
    fm: dict,
    containers_map: dict[str, list[dict]],
    targets: dict[str, tuple[str, dict]],
) -> Path:
    """Apply the flip for already-:func:`_validate_seen`-d *targets* and
    `_save` — but does NOT commit (gate r2 S2, split out of the old
    `_mark_seen_locked`). The CALLER must already hold the ledger lock
    and is responsible for the commit.

    D-a: only a container-C entry moves into B when flipped (B's ≥1
    statement invariant is never violated — nothing moves into B without
    one). A container-D entry (which `add_entry` may create with zero
    statements, §3a.4 D row) flips `provisional` IN PLACE and stays in D
    — moving it into B would manufacture a B entry `add_entry` itself
    would have refused to create directly (S5).

    Changes NOTHING else about any entry — never bumps `r` (a
    presentation is not a dependency move; bumping `r` here would make
    every case citing `um-…@rN` read as "the dependency moved" merely
    because the user was shown it, which is exactly the confusion the
    revision counter exists to avoid — D-b amends the spec sentence that
    otherwise reads as requiring this). A no-op (per id) on an entry
    already `provisional: false` — still written/committed by the
    caller, idempotent, not an error."""
    home = Path(home)
    containers_map = dict(containers_map)
    for entry_id, (letter, found) in targets.items():
        if found["provisional"] is False:
            continue  # no-op: already seen
        new_entry = dict(found)
        new_entry["provisional"] = False
        if letter == "C":
            containers_map[letter] = [e for e in containers_map[letter] if e["id"] != entry_id]
            containers_map["B"] = containers_map["B"] + [new_entry]
        else:  # D-a: D stays D; B (already there) or any other flips in place
            containers_map[letter] = [
                new_entry if e["id"] == entry_id else e for e in containers_map[letter]
            ]

    path, _new_fm = _save(home, fm, containers_map, by=None)
    return path


def _mark_seen_locked(home: Path | str, entry_ids: list[str]) -> Path:
    """Flip every id in *entry_ids* STORED `provisional` field `true` ->
    `false`, in one write — but does NOT commit. The CALLER must already
    hold the ledger lock (its own outermost acquisition, or a nested
    pass-through) and is responsible for the commit. A thin combinator
    of :func:`_validate_seen` + :func:`_apply_seen` (gate r2 S2 split
    those apart so `cases.observe` can interleave its own case-file
    write between them); kept as one call for `mark_seen`'s standalone
    use and any direct/test caller that wants validate-then-flip in one
    step, with the same "raises on the FIRST invalid id, nothing written
    yet" guarantee (fold-u2-r1 item 1 / B1) as before the split."""
    home = Path(home)
    fm, containers_map, targets = _validate_seen(home, entry_ids)
    return _apply_seen(home, fm, containers_map, targets)


def mark_seen(home: Path | str, entry_id: str) -> Path:
    """Standalone single-entry entry point: opens its own lock, flips
    *entry_id* via :func:`_mark_seen_locked`, and commits alone. Never a
    CLI verb (no `user-model mark-seen` in the parser) — the only
    production caller is `cases.observe(kind="presented")`, which calls
    `_mark_seen_locked` directly inside its OWN already-open lock span
    instead, so its write and this one land in a single commit; this
    wrapper exists for direct/test callers and any future standalone
    use."""
    home = Path(home)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            path = _mark_seen_locked(home, [entry_id])
            message = f"self-learn: user-model mark-seen {entry_id}"
            sha = gitops.stage_and_commit(home, [path], message, None)
            if sha is None:  # pragma: no cover
                raise UserModelError("user-model mark-seen: internal — commit produced nothing")
    finally:
        hold.release()
    return path


# ---------------------------------------------------------------- show


def show(home: Path | str) -> dict:
    """Read-only: the whole document as `{"frontmatter": {...},
    "containers": {"A": [...], ..., "E": [...]}}`."""
    home = Path(home)
    fm, containers_map = _load(home)
    return {"frontmatter": fm, "containers": containers_map}
