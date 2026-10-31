"""The owned-skills registry (SK-R, S-NEXT-sk-r-registry; skill-writing plan §4.0).

A skill is **self-learn's own** when ``<ledger>/owned-skills.yaml`` has a
``live`` row for it. The ledger holds the registry row; the skill's files
live in the skills root (claude-skills), which stays the source of truth
for what the skill says. This module is the one place that reads and
writes that file. It knows nothing about the skills root, the template
checks or the overseer: ``skill_writer`` (SK1), ``verbs`` (SK2), the
overseer (SK3/SK4/SK7), the steward (SK6) and the selftest (SK9) all build
on the contract below.

The file::

    version: 1
    skills:
      <name>:
        status: live             # live | retired
        plugin: plugins/<name>   # relative to the skills root
        created:    {at: <iso>, case: case-xxxxxxxx, by: overseer|human}
        last_write: {at: <iso>, case: case-xxxxxxxx, by: overseer|human,
                     authored_sha256: <64 hex>}
        retired:    {at: <iso>, case: case-xxxxxxxx, by: overseer|human}
                                 # only when status is retired
        renamed_from: [<old name>, ...]                     # optional
    vetoed:
      - {name: <name>, at: <iso>, statement: stmt-xxxxxxxx}

Public surface:

    load(home) -> Registry                  # a missing file is an empty registry
    Registry.is_owned(name) -> bool         # a LIVE row only
    Registry.live() -> list[str]
    Registry.vetoed_names() -> list[str]
    Registry.row(name) -> dict | None       # any status; a copy
    Registry.add_veto(name, *, at, statement) -> bool
    with_update(home, fn, *, subject) -> str | None
    authored_sha256(skill_md_text, reference_files) -> str

Rules the file is held to (each refusal names the key and the skill):

- an unknown top-level key, row key or sub-key is refused, not ignored;
- ``status`` is ``live`` or ``retired``; a retired row carries ``retired``
  and a live row does not;
- every ``case`` is a case id, every ``statement`` a statement id, every
  ``by`` is ``overseer`` or ``human``, every ``authored_sha256`` is 64 lowercase
  hex digits, every ``at`` is a timestamp;
- ``plugin`` is exactly ``plugins/<the row's own name>``: a relative path
  that cannot climb out of the skills root and cannot name another skill's
  folder or one two rows share, because the retire and rename steps delete
  and move what it names.

A retired row stays in the file with its ``retired`` stamp. Rows are keyed by
name, so writing a row for a retired name replaces the retired row (git keeps
it); whether ``skill write`` may reuse a retired name is SK1's rule, not this
module's.

**Writing.** :func:`with_update` is the ONLY writer. It opens
:func:`self_learn.intents.ledger_write` (the same ledger lock
``verbs._ledger_write`` delegates to; used directly so this module does not
import ``verbs``, which will import it), re-reads the file INSIDE the lock,
hands the callback a private copy, validates the result, and only then
writes (under an intent, so a crash between the write and the commit is
finished by the next ledger write) and makes ONE commit. A callback that
changes nothing writes nothing and commits nothing. The write and the
commit stay in named helpers called from inside the lock's ``with`` block,
never in a nested closure, so ``tests/test_lock_invariant.py`` sees them
without any ``NOT_REPO_TRUTH`` entry.

**The authored hash.** :func:`authored_sha256` is what the compare-and-swap
in ``skill write`` (D4) uses to tell "the files are as self-learn last wrote
them" from "a person edited them since". It covers everything a person or
the overseer authors and nothing the compilers own, so the lessons moving in
and out of the skill never change it. The compilers own three things, and
all three are left out:

- the managed section of SKILL.md (``BEGIN_MARKER`` through ``END_MARKER``);
- the pointer block of SKILL.md that a skill-scoped ``reference`` route adds
  (``POINTER_BEGIN_MARKER`` through ``POINTER_END_MARKER``);
- the reference shelf, ``references/LEARNINGS.md``, which a ``reference``
  route creates and appends to (``compilers.compile_reference``). The shelf's
  own header says it is never hand-edited, and no authored file may use the
  name: pass it or leave it out, it is not hashed either way.

Every other reference file counts in full. A lesson routed with an explicit
``--dest`` into one of those files appends an entry to it, and that entry
counts as authored text; SK1 decides whether ``skill write`` accepts such a
route into an owned skill.
"""

from __future__ import annotations

import copy
import io
import posixpath
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import gitops, intents, sentinel
from .cases import CASE_ID_RE
from .compilers import (
    BEGIN_MARKER,
    DEFAULT_REFERENCE_BASENAME,
    END_MARKER,
    POINTER_BEGIN_MARKER,
    POINTER_END_MARKER,
)
from .compiled import sha256_hex
from .primitives import chrono, fsops, yamlio
from .skill_scaffold import SKILL_ENTRY_FILE, SKILL_NAME_MAX_CHARS, SKILL_NAME_RE
from .statements import STMT_ID_RE

__all__ = [
    "BY_VALUES",
    "REGISTRY_FILENAME",
    "REGISTRY_VERSION",
    "STATUSES",
    "STATUS_LIVE",
    "STATUS_RETIRED",
    "Registry",
    "SkillRegistryError",
    "authored_sha256",
    "load",
    "registry_path",
    "render",
    "with_update",
]

#: The registry's file name, directly under the ledger home.
REGISTRY_FILENAME = "owned-skills.yaml"
REGISTRY_VERSION = 1

STATUS_LIVE = "live"
STATUS_RETIRED = "retired"
STATUSES = (STATUS_LIVE, STATUS_RETIRED)

#: Who made a registry change: the overseer's runner, or a person through the CLI.
BY_VALUES = ("overseer", "human")

_TOP_KEYS = ("version", "skills", "vetoed")
_ROW_KEYS = ("status", "plugin", "created", "last_write", "retired", "renamed_from")
_STAMP_KEYS = ("at", "case", "by")
_WRITE_KEYS = ("at", "case", "by", "authored_sha256")
_VETO_KEYS = ("name", "at", "statement")

_PLUGIN_RE = re.compile(r"plugins/[a-z0-9][a-z0-9-]*")

#: The reference shelf the compilers own, as a key of ``authored_sha256``'s
#: file map (a path under the skill's directory).
_SHELF_KEY = f"references/{DEFAULT_REFERENCE_BASENAME}"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class SkillRegistryError(Exception):
    """The registry file is unreadable or invalid, or an update would make
    it so. Raised before anything is written."""


# ------------------------------------------------------------------ the file


def registry_path(home: Path | str) -> Path:
    return Path(home) / REGISTRY_FILENAME


def _where(*parts: str) -> str:
    return f"{REGISTRY_FILENAME}: " + ".".join(parts)


def _check_keys(mapping: object, allowed: tuple[str, ...], where: str) -> dict:
    if not isinstance(mapping, Mapping):
        raise SkillRegistryError(f"{where}: must be a mapping, got {type(mapping).__name__}")
    for key in mapping:
        if key not in allowed:
            raise SkillRegistryError(
                f"{where}: unknown key {key!r} (allowed: {', '.join(allowed)})"
            )
    return dict(mapping)


def _need(mapping: dict, key: str, where: str) -> object:
    if key not in mapping:
        raise SkillRegistryError(f"{where}: missing {key!r}")
    return mapping[key]


def _check_at(value: object, where: str) -> str:
    """A timestamp as the ledger writes it. ruamel hands back a ``datetime``
    for an unquoted ISO scalar, so a hand-written file still loads."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return chrono.now_iso(value)
    if isinstance(value, date) or not isinstance(value, str) or chrono.to_dt(value) is None:
        raise SkillRegistryError(f"{where}: {value!r} is not a timestamp")
    return value


def _check_case(value: object, where: str) -> str:
    if not isinstance(value, str) or CASE_ID_RE.fullmatch(value) is None:
        raise SkillRegistryError(f"{where}: {value!r} is not a case id (case-xxxxxxxx)")
    return value


def _check_statement(value: object, where: str) -> str:
    if not isinstance(value, str) or STMT_ID_RE.fullmatch(value) is None:
        raise SkillRegistryError(f"{where}: {value!r} is not a statement id (stmt-xxxxxxxx)")
    return value


def _check_by(value: object, where: str) -> str:
    if value not in BY_VALUES:
        raise SkillRegistryError(f"{where}: {value!r} must be one of {', '.join(BY_VALUES)}")
    return value  # type: ignore[return-value]


def _check_name(value: object, where: str) -> str:
    if (
        not isinstance(value, str)
        or SKILL_NAME_RE.fullmatch(value) is None
        or len(value) > SKILL_NAME_MAX_CHARS
    ):
        raise SkillRegistryError(
            f"{where}: {value!r} is not a skill name (kebab-case, at most "
            f"{SKILL_NAME_MAX_CHARS} characters)"
        )
    return value


def _check_stamp(value: object, where: str) -> dict:
    stamp = _check_keys(value, _STAMP_KEYS, where)
    return {
        "at": _check_at(_need(stamp, "at", where), f"{where}.at"),
        "case": _check_case(_need(stamp, "case", where), f"{where}.case"),
        "by": _check_by(_need(stamp, "by", where), f"{where}.by"),
    }


def _check_last_write(value: object, where: str) -> dict:
    stamp = _check_keys(value, _WRITE_KEYS, where)
    sha = _need(stamp, "authored_sha256", where)
    if not isinstance(sha, str) or _SHA256_RE.fullmatch(sha) is None:
        raise SkillRegistryError(
            f"{where}.authored_sha256: {sha!r} is not 64 lowercase hex digits"
        )
    return {
        "at": _check_at(_need(stamp, "at", where), f"{where}.at"),
        "case": _check_case(_need(stamp, "case", where), f"{where}.case"),
        "by": _check_by(_need(stamp, "by", where), f"{where}.by"),
        "authored_sha256": sha,
    }


def _check_row(name: str, value: object) -> dict:
    where = _where("skills", name)
    row = _check_keys(value, _ROW_KEYS, where)
    status = _need(row, "status", where)
    if status not in STATUSES:
        raise SkillRegistryError(
            f"{where}.status: unknown status {status!r} (expected one of {', '.join(STATUSES)})"
        )
    plugin = _need(row, "plugin", where)
    if not isinstance(plugin, str) or _PLUGIN_RE.fullmatch(plugin) is None:
        raise SkillRegistryError(
            f"{where}.plugin: {plugin!r} must be plugins/<kebab-case name>, relative to the "
            "skills root"
        )
    if plugin != f"plugins/{name}":
        # Retire and rename delete and move the folder this names, so a row
        # may only name its own skill's folder, never another's.
        raise SkillRegistryError(
            f"{where}.plugin: {plugin!r} must be plugins/{name}, the folder of the skill "
            "the row is for"
        )
    out: dict = {
        "status": status,
        "plugin": plugin,
        "created": _check_stamp(_need(row, "created", where), f"{where}.created"),
        "last_write": _check_last_write(_need(row, "last_write", where), f"{where}.last_write"),
    }
    if status == STATUS_RETIRED:
        out["retired"] = _check_stamp(_need(row, "retired", where), f"{where}.retired")
    elif "retired" in row:
        raise SkillRegistryError(f"{where}.retired: a live skill has no retirement")
    if "renamed_from" in row:
        old_names = row["renamed_from"]
        if not isinstance(old_names, list):
            raise SkillRegistryError(f"{where}.renamed_from: must be a list of skill names")
        seen: list[str] = []
        for index, old in enumerate(old_names):
            _check_name(old, f"{where}.renamed_from[{index}]")
            if old == name:
                raise SkillRegistryError(f"{where}.renamed_from[{index}]: {old!r} is its own name")
            if old in seen:
                raise SkillRegistryError(f"{where}.renamed_from[{index}]: {old!r} is listed twice")
            seen.append(old)
        out["renamed_from"] = seen
    return out


def _check_veto(index: int, value: object) -> dict:
    where = _where(f"vetoed[{index}]")
    veto = _check_keys(value, _VETO_KEYS, where)
    return {
        "name": _check_name(_need(veto, "name", where), f"{where}.name"),
        "at": _check_at(_need(veto, "at", where), f"{where}.at"),
        "statement": _check_statement(_need(veto, "statement", where), f"{where}.statement"),
    }


def _normalise(skills: object, vetoed: object) -> tuple[dict[str, dict], list[dict]]:
    """Validate and canonicalise the two collections; raises by name."""
    if skills is None:
        skills = {}
    if not isinstance(skills, Mapping):
        raise SkillRegistryError(_where("skills") + ": must be a mapping of name to row")
    rows: dict[str, dict] = {}
    for name in skills:
        _check_name(name, _where("skills", str(name)))
        rows[name] = _check_row(name, skills[name])
    if vetoed is None:
        vetoed = []
    if not isinstance(vetoed, list):
        raise SkillRegistryError(_where("vetoed") + ": must be a list")
    vetoes: list[dict] = []
    for index, entry in enumerate(vetoed):
        veto = _check_veto(index, entry)
        if veto["name"].casefold() in {v["name"].casefold() for v in vetoes}:
            raise SkillRegistryError(
                _where(f"vetoed[{index}]") + f": {veto['name']!r} is already vetoed"
            )
        vetoes.append(veto)
    return rows, vetoes


class Registry:
    """The registry as data. ``skills`` maps a name to its row and ``vetoed``
    is the list of banned names, both plain dicts and lists.

    Reading is by the methods below. A ``Registry`` from :func:`load` is a
    private copy: changing it changes nothing on disk. The only way to
    change the file is :func:`with_update`, whose callback gets a copy to
    edit; whatever the copy holds afterwards is validated before it is
    written."""

    def __init__(
        self, skills: dict[str, dict] | None = None, vetoed: list[dict] | None = None
    ) -> None:
        self.skills: dict[str, dict] = skills if skills is not None else {}
        self.vetoed: list[dict] = vetoed if vetoed is not None else []

    # -- reads

    def is_owned(self, name: str) -> bool:
        """True only for a LIVE row. A retired skill is not owned."""
        row = self.skills.get(name) if isinstance(name, str) else None
        return row is not None and row.get("status") == STATUS_LIVE

    def live(self) -> list[str]:
        return sorted(name for name, row in self.skills.items() if row.get("status") == STATUS_LIVE)

    def vetoed_names(self) -> list[str]:
        return [entry["name"] for entry in self.vetoed]

    def row(self, name: str) -> dict | None:
        """The row for *name*, whatever its status, as a copy; ``None`` when
        there is none."""
        row = self.skills.get(name) if isinstance(name, str) else None
        return copy.deepcopy(row) if row is not None else None

    # -- helpers for a callback

    def add_veto(self, name: str, *, at: str, statement: str) -> bool:
        """Ban *name* for ever. ``False`` (and no change) when it is already
        banned, compared without regard to case, which is how the template
        check compares names."""
        if name.casefold() in {n.casefold() for n in self.vetoed_names()}:
            return False
        self.vetoed.append({"name": name, "at": at, "statement": statement})
        return True

    def copy(self) -> "Registry":
        return Registry(copy.deepcopy(self.skills), copy.deepcopy(self.vetoed))

    # -- validation and shape

    def validated(self) -> "Registry":
        """A normalised copy, or :class:`SkillRegistryError` naming what is wrong."""
        rows, vetoes = _normalise(self.skills, self.vetoed)
        return Registry(rows, vetoes)

    def to_data(self) -> dict:
        """The file's content as plain data, in a fixed order: skills sorted
        by name, vetoes in the order they were added. Assumes the registry is
        valid; :func:`with_update` validates first."""
        skills: dict[str, dict] = {}
        for name in sorted(self.skills):
            row = self.skills[name]
            skills[name] = {key: copy.deepcopy(row[key]) for key in _ROW_KEYS if key in row}
        return {
            "version": REGISTRY_VERSION,
            "skills": skills,
            "vetoed": copy.deepcopy(self.vetoed),
        }

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Registry) and self.to_data() == other.to_data()

    __hash__ = None  # type: ignore[assignment]


def _parse(text: str, where: Path | str) -> Registry:
    try:
        data = YAML(typ="safe").load(text)
    except (YAMLError, ValueError) as exc:
        raise SkillRegistryError(f"unparseable {where}: {exc}") from exc
    top = _check_keys(data, _TOP_KEYS, f"{REGISTRY_FILENAME} (top level)") if data is not None else {}
    version = top.get("version")
    if type(version) is not int or version != REGISTRY_VERSION:
        raise SkillRegistryError(
            f"{REGISTRY_FILENAME}: version must be {REGISTRY_VERSION}, got {version!r}"
        )
    rows, vetoes = _normalise(top.get("skills"), top.get("vetoed"))
    return Registry(rows, vetoes)


def load(home: Path | str) -> Registry:
    """The registry for *home*. A missing file is an empty registry (nothing
    has been written yet). An unreadable or invalid file raises
    :class:`SkillRegistryError`; callers that ask "is this skill owned?"
    should let it stop them rather than guess."""
    path = registry_path(home)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Registry()
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillRegistryError(f"unreadable {path}: {exc}") from exc
    return _parse(text, path)


def render(registry: Registry) -> str:
    """The registry as the file's text: block style, fixed key order."""
    buf = io.StringIO()
    yamlio.rt_yaml(default_flow_style=False).dump(registry.validated().to_data(), buf)
    return buf.getvalue()


# ------------------------------------------------------------------- writing


def _commit_subject(subject: str) -> str:
    if not isinstance(subject, str) or not subject.strip() or "\n" in subject:
        raise SkillRegistryError("with_update: subject must be one non-empty line")
    subject = subject.strip()
    return subject if subject.startswith("self-learn:") else f"self-learn: {subject}"


def with_update(
    home: Path | str,
    fn: Callable[[Registry], Registry | None],
    *,
    subject: str,
    body: str | None = None,
) -> str | None:
    """Change the registry under the ledger lock and commit it once.

    *fn* gets a private copy of the registry as it is NOW (read again inside
    the lock) and edits it in place, or returns a replacement. The result is
    validated; an invalid one raises :class:`SkillRegistryError` and nothing
    is written. Returns the commit's sha, or ``None`` when *fn* left the data
    unchanged (no write, no commit; a missing file stays missing). The
    commit subject is *subject*, with ``self-learn: `` put in front when it
    is not already there; *body*, when given, is the commit body (``skill
    write`` and ``skill retire`` pass their ``By: <actor>`` trailer, so the
    overseer's weekly census of hand steps can tell its own commits from a
    person's)."""
    home = Path(home)
    message = _commit_subject(subject)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            return _update_locked(home, fn, message, body)
    finally:
        hold.release()


def _update_locked(
    home: Path,
    fn: Callable[[Registry], Registry | None],
    message: str,
    body: str | None = None,
) -> str | None:
    """The locked half of :func:`with_update`. The caller holds the ledger
    lock; this function writes and commits and must only be reached from
    inside it."""
    path = registry_path(home)
    current = load(home)
    working = current.copy()
    result = fn(working)
    if result is not None:
        if not isinstance(result, Registry):
            raise SkillRegistryError("with_update: the callback must return None or a Registry")
        working = result
    working = working.validated()
    if working.to_data() == current.to_data():
        return None
    text = render(working)
    intent = intents.begin(home, "skill-registry", [path], message)
    fsops.atomic_write(path, text, fsync=True)
    intents.complete(intent)
    sha = gitops.stage_and_commit(home, [path], message, body)
    if sha is None:  # pragma: no cover -- the data changed, so the file did
        raise SkillRegistryError("with_update: internal -- the commit produced nothing")
    intents.finish(intent)
    return sha


# --------------------------------------------------------------- authored hash


def _without_one_pair(text: str, begin: str, end: str) -> str:
    """*text* with the section from *begin* through *end* taken out, when the
    markers are exactly one intact pair, in order. Otherwise *text* as it is,
    so a damaged section counts as authored and can never match a hash taken
    from a healthy file."""
    if text.count(begin) == 1 and text.count(end) == 1:
        begin_at = text.index(begin)
        end_at = text.index(end)
        if begin_at < end_at:
            return text[:begin_at] + text[end_at + len(end) :]
    return text


def _outside_managed(text: str) -> str:
    """*text* with both compiler-owned sections taken out: the managed
    section and the pointer block, each when it is exactly one intact pair of
    markers, in order (see :func:`_without_one_pair`)."""
    text = _without_one_pair(text, BEGIN_MARKER, END_MARKER)
    text = _without_one_pair(text, POINTER_BEGIN_MARKER, POINTER_END_MARKER)
    # Trailing whitespace is not authored: the compiler puts one blank line
    # before each section it adds, and a draft hashed before the sections
    # existed must hash the same as the deployed file after they do.
    return text.rstrip()


def _reference_key(key: object) -> str:
    if not isinstance(key, str) or not key:
        raise SkillRegistryError(f"authored_sha256: file key {key!r} must be a non-empty string")
    normal = posixpath.normpath(key)
    if (
        normal != key
        or key.startswith("/")
        or "\\" in key
        or key == ".."
        or key.startswith("../")
        or key == SKILL_ENTRY_FILE
    ):
        raise SkillRegistryError(
            f"authored_sha256: file key {key!r} must be a clean relative path under the skill "
            f"directory and not {SKILL_ENTRY_FILE}"
        )
    return key


def authored_sha256(skill_md_text: str, reference_files: Mapping[str, str] | None = None) -> str:
    """The sha256 (hex) of everything the compilers do not own: SKILL.md
    with its managed section, its pointer block and trailing whitespace taken
    out, and every reference file in full except the shelf
    ``references/LEARNINGS.md``, in path order. *reference_files* maps a path
    relative to the skill's directory (``references/x.md``) to its text,
    the same keys ``skill_scaffold.check_skill`` uses, without ``SKILL.md``.

    Every part is length-framed, so moving text from one file into another,
    or renaming a file, changes the hash."""
    if not isinstance(skill_md_text, str):
        raise SkillRegistryError("authored_sha256: SKILL.md must be text")
    parts: list[tuple[str, str]] = [(SKILL_ENTRY_FILE, _outside_managed(skill_md_text))]
    files = reference_files or {}
    for key in sorted(_reference_key(k) for k in files):
        if key == _SHELF_KEY:
            continue  # the compilers' shelf: lessons moving in must not count
        content = files[key]
        if not isinstance(content, str):
            raise SkillRegistryError(f"authored_sha256: {key} must be text")
        parts.append((key, content))
    blob = bytearray(b"self-learn authored v1\n")
    for label, content in parts:
        label_bytes = label.encode("utf-8")
        content_bytes = content.encode("utf-8")
        blob += f"{len(label_bytes)}:".encode("ascii") + label_bytes
        blob += f"{len(content_bytes)}:".encode("ascii") + content_bytes + b"\n"
    return sha256_hex(bytes(blob))
