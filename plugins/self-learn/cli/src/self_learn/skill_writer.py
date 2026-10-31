"""``skill write`` and ``skill retire``: self-learn deploys and removes the
skills it owns (SK1, S-107; skill-writing plan §2 steps 5 and 8,
decisions D4 and D7, interfaces §4.0).

A skill self-learn owns lives in the skills root (claude-skills) as an
ordinary plugin, ``plugins/<name>/skills/<name>/``, linked into
``~/.claude/skills/<name>``, with a live row in the ledger's
``owned-skills.yaml`` (:mod:`self_learn.skill_registry`). This module is
the only code that creates, rewrites or removes one. The overseer's runner
calls :func:`write` and :func:`retire` in-process; a person calls them
through ``self-learn skill write|retire`` (:mod:`self_learn.skill_cli`).

Public surface::

    check(home, name, files, *, expect_sha=None, updating=None) -> SkillWriteCheck
    write(home, name, files, *, case, by, expect_sha=None, updating=None,
          no_push=False) -> WriteResult
    retire(home, name, *, case, by, no_push=False) -> RetireResult
    rename(home, old, new, *, case, by, veto_statement=None, expect_sha=None,
           no_push=False) -> RenameResult      # SK8; see the rename section
    link_skill(skills_root, name) -> str
    routed_lessons(home, name) -> list[str]
    deployed_files(home, name) -> dict[str, str] | None
    deployed_authored_sha256(home, name) -> str | None
    draft_view(files) -> dict[str, str]
    read_draft_dir(path) -> dict[str, str | bytes]

**What ``write`` checks** (all of it before anything is written, and again
under the locks): the skill template (``skill_scaffold.check_skill``, K1a);
the name against every skill Claude Code loads on this machine
(``overseer.catalogue.skills_on_machine``, its own name left out when
updating) and against the vetoed names; that nothing in the skills root
already uses the name (a plugin folder, a ``plugins/*/skills/<name>``
folder, a marketplace entry, a ``~/.claude/skills/<name>`` entry); a secret
scan of every file; and the compare-and-swap (D4): the sha256 of the skill's
authored files as they are now must equal ``expect_sha`` when one is given.
With no ``expect_sha``, an update is refused when the files changed since
self-learn last wrote them (the registry row's ``authored_sha256``), unless
they already are what this write would leave, or no SKILL.md is there at
all and this write is exactly the one the row records (the two states a
rerun of an interrupted write finds). Any uncommitted change in the
skill's plugin folder or in ``marketplace.json`` that is not this write's
own bytes refuses the write as ``target-busy``.

**What ``write`` does**, holding the autosync-pause sentinel, the ledger
lock and the skills root's lock, in this order:

1. the registry row (created, or ``last_write`` with the new authored
   sha256) -- one ledger commit, or none when the row already says so;
2. the skill's files: ``SKILL.md`` (the draft, stamped with
   ``metadata.self-learn`` -- ``authored_by``, ``case``, ``created``, which
   never change after the skill is made -- then exactly one managed
   section: the deployed file's own section carried over byte for byte,
   or an empty one for a new skill -- then, when the deployed file has
   one, the pointer block a skill-scoped ``reference`` route added, also
   carried over byte for byte, last), ``references/*.md`` (the draft's
   set replaces the deployed set, except the reference shelf
   ``references/LEARNINGS.md``, which a write never writes or removes),
   ``.claude-plugin/plugin.json``, and the marketplace entry, each written
   only when its bytes change -- one skills-root commit, or none;
3. the link ``~/.claude/skills/<name>`` -> ``plugins/<name>/skills/<name>``
   (:func:`link_skill`), made only once the folder exists.

**What the compilers own.** The managed section, the pointer block and the
reference shelf are the compilers', not the author's: a draft may not
carry the shelf or a pointer marker (``bad-line``), :func:`draft_view`
leaves all three out, and a write keeps the deployed ones. Everything else
in the deployed SKILL.md is the author's, wherever it stands, including
text a person added after the managed section: :func:`draft_view` hands
it back at the end of the prose, and a write replaces it with the draft,
which is why changing it needs ``expect_sha`` (the authored hash covers
it). A ``reference`` lesson routed with ``--dest`` into one of the
author's ``references/*.md`` files has its entry in that file, so a write
that would change or remove that file is refused (``needs-person``) until
the lesson is moved.

Both commits carry a ``By: <actor>`` trailer: the skills-root commit and
the registry commit (:func:`skill_registry.with_update`'s ``body``).

**Interrupted writes.** The registry row is the write's intent: it is
committed first, and everything after it is idempotent, so running the
same ``write`` again finishes the job (the row already matches, the files
already written are this write's own bytes, the link is made last). A
crash can therefore leave a live row whose folder is missing (the selftest
names it) but never a link to a missing folder. A host step that FAILS
(a refused commit, a full disk) is undone on the host side and the row is
put back as it was, in a second ledger commit.

**What ``retire`` does**: refuses while any routed lesson still compiles
into the skill (:func:`routed_lessons`); otherwise, under the same locks,
removes the link, then the plugin folder and the marketplace entry in one
skills-root commit, then marks the registry row ``retired`` in one ledger
commit. Rerunning a retire that was interrupted finishes it.

Refusals carry an S-71 refusal kind: ``bad-line`` (the draft or the name is
wrong and will fail the same way every time), ``target-busy`` (uncommitted
edits or a stale ``expect_sha``: retry later), ``needs-person`` (only a
person can settle it), ``destination-unavailable`` (no git-mode skills root
with a marketplace on this machine) and ``git`` (a git step failed).

Every registry write goes through :func:`skill_registry.with_update`; a
rename also rewrites each moved lesson's ``routing.new_skill`` and commits
it under the same ledger lock (:func:`_reroute_lesson`). Every skills-root
write happens inside ``gitops.host_lock`` in a named function called from
the locked block (``tests/test_lock_invariant.py``).
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from . import gitops, intents, sentinel, skill_registry
from .cases import CASE_ID_RE
from .compilers import (
    BEGIN_MARKER,
    DEFAULT_REFERENCE_BASENAME,
    END_MARKER,
    POINTER_BEGIN_MARKER,
    POINTER_END_MARKER,
    CompileError,
    _find_leading_block,
    compile_managed_file,
    reference_target_path,
)
from .hosts import HostsError, host_mode, load_hosts, validate_host_path
from .primitives import chrono, fsops, yamlio
from .scan import scan as secret_scan
from .skill_registry import STATUS_LIVE, STATUS_RETIRED, SkillRegistryError
from .skill_scaffold import (
    SCAFFOLD_VERSION,
    SKILL_ENTRY_FILE,
    SKILL_MANAGED_BEGIN_PREFIX,
    SKILL_NAME_MAX_CHARS,
    SKILL_NAME_RE,
    SKILL_REFERENCES_DIR,
    SKILL_RUNNER_METADATA_KEY,
    SKILL_SUPPORT_FILE_SUFFIX,
    _check_name,
    _read_frontmatter,
    check_skill,
    plugin_manifest_text,
)
from .statements import STMT_ID_RE

__all__ = [
    "BY_VALUES",
    "KIND_BAD_LINE",
    "KIND_DESTINATION_UNAVAILABLE",
    "KIND_GIT",
    "KIND_NEEDS_PERSON",
    "KIND_TARGET_BUSY",
    "MAX_DRAFT_FILE_BYTES",
    "RenameResult",
    "RetireResult",
    "SkillCheck",
    "SkillLinkError",
    "SkillWriteCheck",
    "WriteResult",
    "check",
    "deployed_authored_sha256",
    "deployed_files",
    "draft_view",
    "link_path",
    "link_skill",
    "read_draft_dir",
    "rename",
    "retire",
    "routed_lessons",
    "skill_dir",
    "unlink_skill",
    "write",
]

BY_VALUES = skill_registry.BY_VALUES

#: S-71 refusal kinds this module gives (``batch.REFUSAL_KINDS`` is the
#: closed set they come from).
KIND_BAD_LINE = "bad-line"
KIND_TARGET_BUSY = "target-busy"
KIND_NEEDS_PERSON = "needs-person"
KIND_DESTINATION_UNAVAILABLE = "destination-unavailable"
KIND_GIT = "git"

#: A draft file larger than this is refused by :func:`read_draft_dir`
#: (a skill's SKILL.md and references are prose, not data).
MAX_DRAFT_FILE_BYTES = 1024 * 1024

#: ``check`` runs before the case and author are known; the stamp it
#: checks is built with these and never written.
_PLACEHOLDER_CASE = "case-00000000"

#: The reference shelf, ``references/LEARNINGS.md``: a skill-scoped
#: ``reference`` route creates it and appends to it (``compilers.
#: compile_reference``), so the compilers own it, like the managed section.
#: A draft may not carry it, ``draft_view`` leaves it out, and a write
#: never writes or removes it (``skill_registry.authored_sha256`` leaves it
#: out of the hash for the same reason).
_SHELF_KEY = f"{SKILL_REFERENCES_DIR}/{DEFAULT_REFERENCE_BASENAME}"

#: What both pointer-block markers start with
#: (``compilers.POINTER_BEGIN_MARKER`` / ``POINTER_END_MARKER``): a draft
#: carrying either one, whole or damaged, is refused.
_POINTER_MARK = "<!-- self-learn:pointers:"

_MARKETPLACE_REL = ".claude-plugin/marketplace.json"
_MANIFEST_REL = ".claude-plugin/plugin.json"
_STAMP_KEYS = ("authored_by", "case", "created")


# ------------------------------------------------------------------ results


@dataclass(frozen=True)
class SkillWriteCheck:
    """What :func:`check` found. ``problems`` are plain sentences; ``kind``
    is the S-71 refusal kind when ``ok`` is false."""

    name: str
    ok: bool
    kind: str | None = None
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    #: Whether the write updates a skill self-learn already owns.
    updating: bool = False
    #: The authored sha256 of the skill's files as deployed now; ``None``
    #: when no SKILL.md is deployed (or the check stopped before reading it).
    current_sha: str | None = None
    #: The registry row's ``last_write.authored_sha256``, when there is a row.
    recorded_sha: str | None = None


#: The plan's §4.0 name for the result of :func:`check`.
SkillCheck = SkillWriteCheck


@dataclass(frozen=True)
class WriteResult:
    name: str
    ok: bool
    kind: str | None = None
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    updating: bool = False
    #: The registry commit this write made (``None``: the row already said so).
    ledger_sha: str | None = None
    #: The skills-root commit this write made (``None``: nothing changed there).
    host_sha: str | None = None
    #: What :func:`link_skill` did: ``created``, ``replaced`` or ``unchanged``.
    link: str | None = None
    #: The authored sha256 of the files as deployed after this write.
    authored_sha256: str | None = None
    warnings: tuple[str, ...] = ()
    ledger_push: gitops.PushResult | None = None
    host_push: gitops.PushResult | None = None

    @property
    def changed(self) -> bool:
        return bool(self.ledger_sha or self.host_sha or self.link in ("created", "replaced"))


@dataclass(frozen=True)
class RetireResult:
    name: str
    ok: bool
    kind: str | None = None
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    #: The routed lessons that still compile into the skill (a refusal).
    routed: tuple[str, ...] = ()
    ledger_sha: str | None = None
    host_sha: str | None = None
    #: Whether the ``~/.claude/skills/<name>`` link was removed.
    unlinked: bool = False
    warnings: tuple[str, ...] = ()
    ledger_push: gitops.PushResult | None = None
    host_push: gitops.PushResult | None = None

    @property
    def changed(self) -> bool:
        return bool(self.ledger_sha or self.host_sha or self.unlinked)


class _Refused(Exception):
    """Flow control inside this module: a refusal with its kind."""

    def __init__(
        self, kind: str, problems: list[str] | tuple[str, ...], *, notes=(), routed=()
    ) -> None:
        super().__init__("; ".join(problems))
        self.kind = kind
        self.problems = tuple(problems)
        self.notes = tuple(notes)
        self.routed = tuple(routed)


class SkillLinkError(Exception):
    """:func:`link_skill` refused: the link path holds something that is not
    a link self-learn may replace, or the folder to link to is missing."""


# ----------------------------------------------------------------- paths


def skill_dir(skills_root: Path | str, name: str) -> Path:
    """``<skills_root>/plugins/<name>/skills/<name>`` -- the folder a
    ``new-skill:<name>`` route compiles into and the link points at."""
    return Path(skills_root) / "plugins" / name / "skills" / name


def link_path(name: str) -> Path:
    """``<claude dir>/skills/<name>`` (``SELF_LEARN_CLAUDE_DIR`` in tests)."""
    from .selfcheck import claude_runtime_dir  # local: selfcheck imports a lot

    return claude_runtime_dir() / "skills" / name


def _valid_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and SKILL_NAME_RE.fullmatch(name) is not None
        and len(name) <= SKILL_NAME_MAX_CHARS
    )


def _root_mode_for_lock(root: Path) -> str:
    """The mode to key ``gitops.host_lock`` on for *root*: ``git`` inside a
    git work tree (the same lock file as a git-mode registration), else
    ``plain``."""
    return "git" if gitops.work_tree_of(root) is not None else "plain"


# ------------------------------------------------------------------- links


def link_skill(skills_root: Path | str, name: str) -> str:
    """Make ``~/.claude/skills/<name>`` a link to the skill's folder in the
    skills root (D7: what ``claude-skills/install.sh`` does for a skill, so
    nobody has to run it). Returns ``created``, ``replaced`` (a dangling
    link was replaced) or ``unchanged``.

    Refuses (:class:`SkillLinkError`) when the folder has no SKILL.md (a link
    to a missing folder is never made), or when the link path holds a real
    file or folder, or a link that works and points somewhere else. Runs
    under the skills root's lock (re-entrant for a caller that holds it)."""
    if not _valid_name(name):
        raise SkillLinkError(f"{name!r} is not a skill name")
    root = Path(skills_root)
    with gitops.host_lock(root, _root_mode_for_lock(root)):
        return _place_link(link_path(name), skill_dir(root, name))


def _place_link(link: Path, target: Path) -> str:
    """The locked half of :func:`link_skill`."""
    if not (target / SKILL_ENTRY_FILE).is_file():
        raise SkillLinkError(
            f"{target} has no {SKILL_ENTRY_FILE}; refusing to link {link} to a missing folder"
        )
    outcome = "created"
    if link.is_symlink():
        if os.readlink(link) == str(target) or (
            link.exists() and link.resolve() == target.resolve()
        ):
            return "unchanged"
        if link.exists():
            raise SkillLinkError(
                f"{link} already links to {link.resolve()}; a working link to another "
                "folder is not replaced"
            )
        outcome = "replaced"  # a dangling link
    elif link.exists():
        raise SkillLinkError(
            f"{link} is a real file or folder, not a link; it is not replaced"
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.parent / f".{link.name}.self-learn-{uuid.uuid4().hex[:8]}"
    os.symlink(str(target), temporary)
    try:
        os.replace(temporary, link)
    finally:
        if temporary.is_symlink():
            temporary.unlink()
    return outcome


def unlink_skill(skills_root: Path | str, name: str) -> bool:
    """Remove ``~/.claude/skills/<name>`` when it is a link to the skill's
    folder (working or dangling). Anything else at that path is left alone
    and ``False`` returned. Runs under the skills root's lock."""
    if not _valid_name(name):
        return False
    root = Path(skills_root)
    with gitops.host_lock(root, _root_mode_for_lock(root)):
        return _drop_link(link_path(name), skill_dir(root, name))


def _drop_link(link: Path, target: Path) -> bool:
    """The locked half of :func:`unlink_skill`."""
    if not link.is_symlink():
        return False
    points_here = os.readlink(link) == str(target)
    if not points_here and link.exists():
        points_here = link.resolve() == target.resolve()
    if not points_here:
        return False
    link.unlink()
    return True


# ------------------------------------------------------------ reading files


def read_draft_dir(path: Path | str) -> dict[str, str | bytes]:
    """Every regular file under *path* as ``{relative posix path: text}``.
    A file that is not UTF-8 comes back as ``bytes`` (the template check
    then names it). A symlink, or a file over :data:`MAX_DRAFT_FILE_BYTES`,
    raises ``ValueError``: a draft is plain files."""
    base = Path(path)
    if not base.is_dir():
        raise ValueError(f"{base} is not a folder")
    files: dict[str, str | bytes] = {}
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        here = Path(current)
        for dirname in list(dirnames):
            if (here / dirname).is_symlink():
                raise ValueError(f"{here / dirname} is a symlink; a draft holds plain files")
        for filename in sorted(filenames):
            file_path = here / filename
            if file_path.is_symlink():
                raise ValueError(f"{file_path} is a symlink; a draft holds plain files")
            if file_path.stat().st_size > MAX_DRAFT_FILE_BYTES:
                raise ValueError(
                    f"{file_path} is larger than {MAX_DRAFT_FILE_BYTES} bytes"
                )
            data = file_path.read_bytes()
            key = file_path.relative_to(base).as_posix()
            try:
                files[key] = data.decode("utf-8")
            except UnicodeDecodeError:
                files[key] = data
    return files


def _read_tree(directory: Path) -> dict[str, str]:
    """Every regular file under *directory* (no symlinks followed), as
    text; bytes that are not UTF-8 are kept as backslash escapes so the
    hash stays defined."""
    files: dict[str, str] = {}
    if not directory.is_dir():
        return files
    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        here = Path(current)
        dirnames[:] = sorted(d for d in dirnames if not (here / d).is_symlink())
        for filename in sorted(filenames):
            file_path = here / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            key = file_path.relative_to(directory).as_posix()
            files[key] = file_path.read_bytes().decode("utf-8", errors="backslashreplace")
    return files


def _skills_root_or_none(home: Path) -> Path | None:
    try:
        hosts = load_hosts(home)
    except HostsError:
        return None
    return hosts.skills_root


def deployed_files(home: Path | str, name: str) -> dict[str, str] | None:
    """The skill's files as they are in the skills root now (every file in
    its folder, keyed like a draft), or ``None`` when no SKILL.md is there."""
    root = _skills_root_or_none(Path(home))
    if root is None or not _valid_name(name):
        return None
    files = _read_tree(skill_dir(root, name))
    return files if SKILL_ENTRY_FILE in files else None


def _authored_sha(files: Mapping[str, str]) -> str:
    others = {key: value for key, value in files.items() if key != SKILL_ENTRY_FILE}
    return skill_registry.authored_sha256(files[SKILL_ENTRY_FILE], others)


def _authored_sha_or_refuse(files: Mapping[str, str], what: str) -> str:
    """:func:`_authored_sha` for the checks: a file the hash cannot take (a
    deployed file name with a backslash in it, say) is a refusal with its
    reason, never a traceback."""
    try:
        return _authored_sha(files)
    except SkillRegistryError as exc:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"the authored sha256 of {what} cannot be taken: {exc}; a person must look at the folder"],
        ) from exc


def deployed_authored_sha256(home: Path | str, name: str) -> str | None:
    """The authored sha256 of the deployed files (what ``expect_sha`` is
    compared with), or ``None`` when none are deployed."""
    files = deployed_files(home, name)
    return None if files is None else _authored_sha(files)


def draft_view(files: Mapping[str, str]) -> dict[str, str]:
    """A deployed skill's files as a draft the overseer can edit and hand
    back: SKILL.md without the runner's stamp and without the two blocks
    the compilers own (the managed section and the pointer block), plus the
    ``references/*.md`` files except the reference shelf
    ``references/LEARNINGS.md``. Other files are left out (a draft may not
    carry them; :func:`write` leaves them where they are).

    Every other line of SKILL.md is in the view, wherever it stood: text a
    person added after the managed section or after the pointer block
    comes back at the end of the prose (one blank line between pieces), so
    whoever edits the view sees it and a write from the view keeps it,
    moved above the managed section. Nothing a person wrote is dropped
    unseen (D4)."""
    out: dict[str, str] = {}
    for key, value in files.items():
        if key == SKILL_ENTRY_FILE:
            out[key] = _authored_part(_unstamped(value)) + "\n"
        elif _is_managed_reference(key):
            out[key] = value
    return out


def _is_managed_reference(key: str) -> bool:
    """``references/<file>.md``, one level deep, other than the reference
    shelf: the support files a write replaces. Anything else in the folder
    (the shelf included) is left alone."""
    parts = key.split("/")
    return (
        len(parts) == 2
        and parts[0] == SKILL_REFERENCES_DIR
        and parts[1].endswith(SKILL_SUPPORT_FILE_SUFFIX)
        and key != _SHELF_KEY
    )


# --------------------------------------------------------- routed lessons


def routed_lessons(home: Path | str, name: str) -> list[str]:
    """The ids of every ROUTED lesson whose compiled line lands in the
    skill's folder: a ``new-skill`` or ``skill-md`` route whose target is
    the skill's SKILL.md (the compiler's own resolution,
    ``verbs.managed_target_for``), and a ``reference`` route filed in the
    ``skills/<name>`` bucket. A retire is refused while this is not empty."""
    return sorted({record_id for record_id, _destination, _file in _routed(Path(home), name)})


def _routed(home: Path, name: str) -> list[tuple[str, str, Path | None]]:
    """``(lesson id, destination, file)`` for every lesson
    :func:`routed_lessons` counts. *file* is the references file a
    ``reference`` lesson's entry lives in (the shelf, or the file its
    ``--dest`` named: ``compilers.reference_target_path``, the one place
    that mapping lives), ``None`` for the other destinations."""
    from . import ledger_ops, verbs  # local: verbs imports a great deal
    from .ledger import discover_buckets
    from .records import Record

    root = _skills_root_or_none(home)
    if root is None or not _valid_name(name):
        return []
    target = (skill_dir(root, name) / SKILL_ENTRY_FILE).resolve()
    references = skill_dir(root, name) / SKILL_REFERENCES_DIR
    found: list[tuple[str, str, Path | None]] = []
    seen: set[str] = set()
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except ledger_ops.UNREADABLE_RECORD_ERRORS:
                continue
            if record.status != "routed" or record.id in seen:
                continue
            routing = record.routing or {}
            destination = routing.get("destination")
            file: Path | None = None
            if destination in ("skill-md", "new-skill"):
                hit = verbs.managed_target_for(home, bucket, record) == target
            else:
                hit = destination == "reference" and bucket.scope == "skill" and bucket.name == name
                if hit:
                    reference_file = routing.get("reference_file")
                    file = reference_target_path(
                        references, reference_file if isinstance(reference_file, str) else None
                    )
            if hit:
                seen.add(record.id)
                found.append((record.id, str(destination), file))
    return found


# ------------------------------------------------------- frontmatter stamp


def _split_frontmatter(text: str) -> tuple[str, str, str, str]:
    """``(opening fence line, inner text, closing fence line, body)``; the
    four join back to *text*. Call only on a SKILL.md whose frontmatter
    ``_read_frontmatter`` accepted."""
    block = _find_leading_block(text)
    if block is None:  # pragma: no cover -- the caller checked
        raise CompileError("no frontmatter block")
    inner, end = block
    opening = text[: text.index("\n") + 1]
    closing = text[len(opening) + len(inner) : end]
    return opening, inner, closing, text[end:]


def _stamp_block(stamp: Mapping[str, Any]) -> str:
    return (
        "metadata:\n"
        f"  {SKILL_RUNNER_METADATA_KEY}:\n"
        f"    authored_by: {stamp['authored_by']}\n"
        f"    case: {stamp['case']}\n"
        f"    created: {json.dumps(stamp['created'])}\n"
    )


def _rt_dump(data: Any) -> str:
    buf = io.StringIO()
    yamlio.rt_yaml(preserve_quotes=True, width=4096).dump(data, buf)
    return buf.getvalue()


def _stamped(text: str, stamp: Mapping[str, str]) -> str:
    """SKILL.md *text* with ``metadata.self-learn`` set to *stamp*. A
    frontmatter with no ``metadata`` key gets a block appended at its end,
    every other byte unchanged; one with a ``metadata`` mapping is edited
    through the round-trip YAML loader. Either way the result is read back
    and must hold exactly the old keys plus the stamp, or this refuses."""
    read = _read_frontmatter(text)
    if read.mapping is None:
        raise _Refused(KIND_BAD_LINE, [f"{SKILL_ENTRY_FILE}: the frontmatter cannot be read"])
    opening, inner, closing, body = _split_frontmatter(text)
    if "metadata" not in read.mapping:
        if inner and not inner.endswith("\n"):
            inner += "\n"
        new_inner = inner + _stamp_block(stamp)
    else:
        data = yamlio.rt_yaml(preserve_quotes=True, width=4096).load(inner)
        if data.get("metadata") is None:
            data["metadata"] = CommentedMap()
        stamp_map = CommentedMap()
        stamp_map["authored_by"] = stamp["authored_by"]
        stamp_map["case"] = stamp["case"]
        stamp_map["created"] = DoubleQuotedScalarString(stamp["created"])
        data["metadata"][SKILL_RUNNER_METADATA_KEY] = stamp_map
        new_inner = _rt_dump(data)
    new_text = opening + new_inner + closing + body
    expected = dict(read.mapping)
    expected["metadata"] = {
        **dict(read.mapping.get("metadata") or {}),
        SKILL_RUNNER_METADATA_KEY: dict(stamp),
    }
    after = _read_frontmatter(new_text)
    if after.mapping != expected or after.body != body:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [
                f"{SKILL_ENTRY_FILE}: the metadata.{SKILL_RUNNER_METADATA_KEY} stamp could not "
                "be added without changing the rest of the frontmatter"
            ],
        )
    return new_text


def _unstamped(text: str) -> str:
    """*text* without ``metadata.self-learn`` (the inverse of
    :func:`_stamped`); unchanged when there is no stamp or no readable
    frontmatter."""
    read = _read_frontmatter(text)
    if read.mapping is None:
        return text
    meta = read.mapping.get("metadata")
    if not isinstance(meta, dict) or SKILL_RUNNER_METADATA_KEY not in meta:
        return text
    opening, inner, closing, body = _split_frontmatter(text)
    stamp = meta[SKILL_RUNNER_METADATA_KEY]
    if (
        list(meta) == [SKILL_RUNNER_METADATA_KEY]
        and isinstance(stamp, dict)
        and set(stamp) == set(_STAMP_KEYS)
        and all(isinstance(stamp[k], str) for k in _STAMP_KEYS)
        and inner.endswith(_stamp_block(stamp))
    ):
        return opening + inner[: -len(_stamp_block(stamp))] + closing + body
    data = yamlio.rt_yaml(preserve_quotes=True, width=4096).load(inner)
    del data["metadata"][SKILL_RUNNER_METADATA_KEY]
    if not data["metadata"]:
        del data["metadata"]
    return opening + (_rt_dump(data) if data else "") + closing + body


# ------------------------------------------------------- managed section


def _section_of(text: str) -> str | None:
    """The managed section (begin marker through end marker) of *text*,
    ``None`` when there is none; refuses a broken one."""
    prefix_begins = text.count(SKILL_MANAGED_BEGIN_PREFIX)
    ends = text.count(END_MARKER)
    if prefix_begins == 0 and ends == 0:
        return None
    if prefix_begins == 1 and text.count(BEGIN_MARKER) == 1 and ends == 1:
        begin_at = text.index(BEGIN_MARKER)
        end_at = text.index(END_MARKER)
        if begin_at < end_at:
            return text[begin_at : end_at + len(END_MARKER)]
    raise _Refused(
        KIND_NEEDS_PERSON,
        [
            f"the deployed {SKILL_ENTRY_FILE}'s managed section is broken (its markers are "
            "not one intact pair); a person must repair it before self-learn writes the skill"
        ],
    )


def _pointer_block_of(text: str) -> str | None:
    """The pointer block (pointer begin marker through pointer end marker)
    of a deployed SKILL.md, ``None`` when there is none; refuses a broken
    one. A skill-scoped ``reference`` route adds this block at the end of
    the file, after the managed section (``compilers.compile_pointer_text``),
    and owns it: a write carries it over byte for byte."""
    begins = text.count(POINTER_BEGIN_MARKER)
    ends = text.count(POINTER_END_MARKER)
    marks = text.count(_POINTER_MARK)
    if marks == 0:
        return None
    if begins == 1 and ends == 1 and marks == 2:
        begin_at = text.index(POINTER_BEGIN_MARKER)
        end_at = text.index(POINTER_END_MARKER)
        if begin_at < end_at:
            return text[begin_at : end_at + len(POINTER_END_MARKER)]
    raise _Refused(
        KIND_NEEDS_PERSON,
        [
            f"the deployed {SKILL_ENTRY_FILE}'s pointer block is broken (its markers are not "
            "one intact pair); a person must repair it before self-learn writes the skill"
        ],
    )


def _compiler_blocks(text: str) -> tuple[str | None, str | None]:
    """``(managed section, pointer block)`` of a deployed SKILL.md, each
    ``None`` when absent. Refuses (``needs-person``) when either is broken
    or when the two overlap."""
    section = _section_of(text)
    pointer = _pointer_block_of(text)
    if section is not None and pointer is not None:
        section_at, pointer_at = text.index(section), text.index(pointer)
        apart = (
            section_at + len(section) <= pointer_at or pointer_at + len(pointer) <= section_at
        )
        if not apart:
            raise _Refused(
                KIND_NEEDS_PERSON,
                [
                    f"the deployed {SKILL_ENTRY_FILE}'s managed section and pointer block "
                    "overlap; a person must repair the file before self-learn writes the skill"
                ],
            )
    return section, pointer


def _intact_span(text: str, begin: str, end: str) -> tuple[int, int] | None:
    """Where the *begin* .. *end* block is in *text*, when its markers are
    exactly one pair, in order."""
    if text.count(begin) == 1 and text.count(end) == 1:
        begin_at, end_at = text.index(begin), text.index(end)
        if begin_at < end_at:
            return begin_at, end_at + len(end)
    return None


def _authored_part(text: str) -> str:
    """*text* with the managed section and the pointer block taken out
    (each when it is one intact pair, in order) and every other line kept,
    wherever it stood: the pieces left are joined with one blank line, and
    trailing whitespace goes. A damaged managed section is cut off at its
    first marker, as before: a write refuses the deployed file by name
    (:func:`_section_of`) rather than the draft. Pure; never raises."""
    spans = sorted(
        span
        for span in (
            _intact_span(text, BEGIN_MARKER, END_MARKER),
            _intact_span(text, POINTER_BEGIN_MARKER, POINTER_END_MARKER),
        )
        if span is not None
    )
    if len(spans) == 2 and spans[0][1] > spans[1][0]:
        spans = spans[:1]  # overlapping blocks: a write refuses this file
    pieces: list[str] = []
    at = 0
    for start, stop in spans:
        pieces.append(text[at:start])
        at = stop
    pieces.append(text[at:])
    kept = [pieces[0].rstrip()]
    kept += [piece.strip("\n").rstrip() for piece in pieces[1:] if piece.strip()]
    joined = "\n\n".join(kept)
    if SKILL_MANAGED_BEGIN_PREFIX in joined:
        joined = joined[: joined.index(SKILL_MANAGED_BEGIN_PREFIX)].rstrip()
    return joined


def _without_section(text: str) -> str:
    """A DRAFT's SKILL.md with its managed section and everything after it
    taken out (the template check already refused text after the section,
    and a pointer marker in a draft)."""
    for marker in (BEGIN_MARKER, SKILL_MANAGED_BEGIN_PREFIX):
        if marker in text:
            return text[: text.index(marker)].rstrip()
    return text.rstrip()


def _with_section(authored: str, section: str | None, pointer: str | None = None) -> str:
    """The deployed SKILL.md: the authored text, one blank line, the
    section (an empty marker pair when *section* is ``None``), and then,
    when the deployed file had one, one blank line and the pointer block,
    last: the layout ``compilers.compile_pointer_text`` leaves when it adds
    the block to a file that ends with the section, so a write from
    :func:`draft_view` changes no byte of it."""
    if section is None:
        section = f"{BEGIN_MARKER}\n{END_MARKER}"
    out = f"{authored.rstrip()}\n\n{section}\n"
    if pointer is not None:
        out += f"\n{pointer}\n"
    return out


# ----------------------------------------------------------- JSON files


def _json_layout(raw: str, data: Any) -> bool | None:
    """Which of the two layouts self-learn writes *raw* is in: the value of
    ``ensure_ascii`` that reproduces it byte for byte with a two-space
    indent and a final newline, or ``None`` for neither."""
    for ensure_ascii in (True, False):
        if json.dumps(data, indent=2, ensure_ascii=ensure_ascii) + "\n" == raw:
            return ensure_ascii
    return None


def _dump_json(data: Any, ensure_ascii: bool) -> str:
    return json.dumps(data, indent=2, ensure_ascii=ensure_ascii) + "\n"


def _read_marketplace(raw: str) -> tuple[dict, bool]:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise _Refused(KIND_NEEDS_PERSON, [f"{_MARKETPLACE_REL} is not JSON: {exc}"]) from exc
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise _Refused(KIND_NEEDS_PERSON, [f"{_MARKETPLACE_REL} has no plugins list"])
    layout = _json_layout(raw, data)
    if layout is None:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [
                f"{_MARKETPLACE_REL} is not laid out as two-space JSON, so self-learn cannot add "
                "or remove one entry without touching other lines; a person must edit it"
            ],
        )
    return data, layout


def _entries_named(data: dict, name: str) -> list[dict]:
    return [p for p in data["plugins"] if isinstance(p, dict) and p.get("name") == name]


def _marketplace_with(raw: str, name: str, description: str) -> str:
    """*raw* with this skill's entry present and its description current;
    every other entry and key unchanged, in the file's own JSON layout."""
    data, layout = _read_marketplace(raw)
    source = f"./plugins/{name}"
    entries = _entries_named(data, name)
    if len(entries) > 1 or (entries and entries[0].get("source") != source):
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"{_MARKETPLACE_REL} has an entry named {name!r} that is not {source}"],
        )
    if entries:
        if entries[0].get("description") == description:
            return raw
        entries[0]["description"] = description
    else:
        data["plugins"].append(
            {"name": name, "source": source, "description": description, "version": SCAFFOLD_VERSION}
        )
    return _dump_json(data, layout)


def _marketplace_without(raw: str, name: str) -> str:
    data, layout = _read_marketplace(raw)
    if not _entries_named(data, name):
        return raw
    data["plugins"] = [
        p for p in data["plugins"] if not (isinstance(p, dict) and p.get("name") == name)
    ]
    return _dump_json(data, layout)


def _manifest_text(existing: str | None, name: str, description: str) -> tuple[str | None, str | None]:
    """``(new plugin.json text, note)``. A new skill gets the scaffold's
    three keys. An existing manifest gets only its ``name`` and
    ``description`` brought up to date, in its own layout; one self-learn
    cannot rewrite exactly is left alone with a note (``None`` text)."""
    if existing is None:
        return plugin_manifest_text(name, description), None
    try:
        data = json.loads(existing)
    except ValueError:
        data = None
    layout = _json_layout(existing, data) if isinstance(data, dict) else None
    if not isinstance(data, dict) or layout is None:
        return None, f"{_MANIFEST_REL} was left as it is (self-learn cannot rewrite its layout)"
    if data.get("name") == name and data.get("description") == description:
        return existing, None
    data["name"] = name
    data["description"] = description
    return _dump_json(data, layout), None


# ------------------------------------------------------------- the plan


@dataclass
class _Plan:
    """Everything a write (or a check) decided, computed from the state on
    disk. ``writes`` holds every path the write manages with its intended
    bytes; ``removals`` the tracked files it takes out."""

    name: str
    root: Path
    updating: bool
    row_before: dict | None
    writes: dict[Path, str] = field(default_factory=dict)
    removals: list[Path] = field(default_factory=list)
    new_sha: str = ""
    current_sha: str | None = None
    recorded_sha: str | None = None
    stamp: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def plugin_dir(self) -> Path:
        return self.root / "plugins" / self.name

    @property
    def folder(self) -> Path:
        return skill_dir(self.root, self.name)

    def changed_writes(self) -> dict[Path, str]:
        """The writes whose bytes differ from what is on disk."""
        out: dict[Path, str] = {}
        for path, text in self.writes.items():
            try:
                same = path.is_file() and path.read_text(encoding="utf-8") == text
            except (OSError, UnicodeDecodeError):
                same = False
            if not same:
                out[path] = text
        return out


def _skills_root(home: Path) -> Path:
    """The registered skills root, checked: registered, sound, git mode,
    with a marketplace."""
    try:
        hosts = load_hosts(home)
    except HostsError as exc:
        raise _Refused(KIND_NEEDS_PERSON, [f"hosts.yaml cannot be read: {exc}"]) from exc
    if hosts.skills_root is None:
        raise _Refused(
            KIND_DESTINATION_UNAVAILABLE,
            ["no skills root is registered (self-learn host add <path> --skills-root)"],
        )
    try:
        root = validate_host_path(home, hosts.skills_root, "skills-root")
    except HostsError as exc:
        raise _Refused(KIND_NEEDS_PERSON, [str(exc)]) from exc
    if host_mode(home, hosts.skills_root, registration="skills-root") != "git":
        raise _Refused(
            KIND_DESTINATION_UNAVAILABLE,
            [
                f"the skills root {root} is registered in plain mode; self-learn writes the "
                "skills it owns only into a git-mode skills root"
            ],
        )
    if not (root / _MARKETPLACE_REL).is_file():
        raise _Refused(
            KIND_DESTINATION_UNAVAILABLE,
            [f"the skills root {root} has no {_MARKETPLACE_REL}"],
        )
    return root


def _load_registry(home: Path) -> skill_registry.Registry:
    try:
        return skill_registry.load(home)
    except SkillRegistryError as exc:
        raise _Refused(KIND_NEEDS_PERSON, [str(exc)]) from exc


def _resolves_to(path: object, folder: Path) -> bool:
    if not isinstance(path, str) or not path:
        return False
    try:
        return Path(path).resolve() == folder.resolve()
    except (OSError, RuntimeError):
        return False


def _is_own_entry(
    full: str, paths: tuple[object, ...], where: str, *, own: str, own_folder: Path | None
) -> bool:
    """Whether a catalogue entry (case-folded name *full*) is the skill
    being updated itself: it reaches *own_folder*, or it is the
    ``<name>:<name>`` skill of its own plugin."""
    from .overseer import catalogue  # local, as in _loaded_names

    if own_folder is not None and any(_resolves_to(p, own_folder) for p in paths):
        return True
    return full == f"{own}:{own}" and where in (catalogue.WHERE_PLUGIN, catalogue.WHERE_SYNCED_PLUGIN)


def _loaded_names(
    home: Path, *, leaving_out: str | None, own_folder: Path | None = None
) -> tuple[set[str], list[str], list[str]]:
    """Every name a skill or command is loaded under on this machine, both
    as listed (``plugin:skill``) and as its last part (``skill``), all
    case-folded. Returns ``(names, the catalogue's problems, collision
    notes)``.

    When updating (*leaving_out* is the skill's name), the skill's own
    entries are left out: the one that reaches *own_folder* (the
    ``~/.claude/skills/<name>`` link) and the ``<name>:<name>`` entry of
    its own plugin installed from the marketplace (Claude Code loads an
    installed plugin from its own copy, which does not resolve to the
    skills root). Any OTHER entry with the same last part (``other:<name>``,
    a synced ``anthropic-skills:<name>``) is left out of the names too, so
    an update is not refused for a name the skill already had, but each
    one is named in a note: the clash is reported, not hidden."""
    from .overseer import catalogue  # local: the catalogue imports report, hosts, ...

    machine = catalogue.skills_on_machine(
        home,
        placed=catalogue.PlacedLessons(surfaces={}, unlisted=(), unreadable=()),
    )
    own = leaving_out.casefold() if leaving_out is not None else None
    names: set[str] = set()
    clashes: list[str] = []
    for entry in machine.skills:
        full = entry.name.casefold()
        bare = full.rsplit(":", 1)[-1]
        if own is not None and bare == own:
            paths = (entry.path, entry.resolves_to)
            if not _is_own_entry(full, paths, entry.where, own=own, own_folder=own_folder):
                clashes.append(entry.name)
            continue
        names.update((full, bare))
    for item in machine.not_loaded:
        full = item["name"].casefold()
        bare = full.rsplit(":", 1)[-1]
        if own is not None and bare == own:
            paths = (item.get("path"),)
            if not _is_own_entry(full, paths, item.get("where", ""), own=own, own_folder=own_folder):
                clashes.append(item["name"])
            continue
        names.add(bare)
    notes = [
        f"name-collision (not refused on an update): {clash} also uses the name {leaving_out}"
        for clash in sorted(set(clashes))
    ]
    return names, list(machine.problems), notes


def _compiler_owned_in_draft(files: Mapping[Any, Any]) -> list[str]:
    """What a draft may not carry because the compilers own it: the
    reference shelf, and the pointer block's markers (whole or damaged).
    :func:`draft_view` leaves both out; a write keeps the deployed ones."""
    problems: list[str] = []
    if _SHELF_KEY in files:
        problems.append(
            f"reference-shelf: {_SHELF_KEY} is the reference shelf self-learn's compilers "
            "own (lessons routed as references land there); a draft may not carry it, and "
            "a write leaves the deployed one as it is"
        )
    skill_md = files.get(SKILL_ENTRY_FILE)
    if isinstance(skill_md, str) and _POINTER_MARK in skill_md:
        problems.append(
            f"pointer-block: {SKILL_ENTRY_FILE} carries a self-learn pointer-block marker; the "
            "pointer block is the compilers' (a reference route adds it), so leave it out of "
            "the draft, and a write keeps the deployed one"
        )
    return problems


def _secret_problems(files: Mapping[Any, Any]) -> list[str]:
    """One sentence per secret-scan hit in any file or file name. The
    matched text is never repeated (it would be published by the refusal)."""
    problems: list[str] = []
    for key, value in files.items():
        for label, text in ((f"the file name {key!r}", key), (str(key), value)):
            if not isinstance(text, str):
                continue
            for hit in secret_scan(text):
                problems.append(
                    f"secret scan: {label} holds a likely secret ({hit.rule}, characters "
                    f"{hit.start}..{hit.end}); remove it from the draft"
                )
    return problems


def _dirty_under(root: Path, paths: list[Path]) -> set[str]:
    """Repo-relative paths ``git status`` reports changed or untracked under
    *paths* (every untracked file listed, not just its folder)."""
    rels = [os.path.relpath(p, root) for p in paths]
    proc = gitops._git_ok(  # noqa: SLF001 -- the porcelain read this needs has no public wrapper
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *rels
    )
    dirty: set[str] = set()
    entries = proc.stdout.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        dirty.add(entry[3:])
        if entry[0] in "RC":  # a rename or copy: the source path follows
            if index < len(entries):
                dirty.add(entries[index])
            index += 1
    return dirty


def _head_text(root: Path, path: Path) -> str | None:
    """*path*'s text as committed at the skills root's HEAD, or ``None``
    when HEAD has no such file."""
    rel = Path(os.path.relpath(path, root)).as_posix()
    proc = gitops._git(root, "show", f"HEAD:{rel}")  # noqa: SLF001 -- a read
    return proc.stdout if proc.returncode == 0 else None


def _tracked_under(root: Path, directory: Path) -> list[Path]:
    rel = os.path.relpath(directory, root)
    proc = gitops._git_ok(root, "ls-files", "-z", "--", rel)  # noqa: SLF001
    return [root / item for item in proc.stdout.split("\0") if item]


def _preflight(
    home: Path,
    name: str,
    files: object,
    *,
    expect_sha: str | None,
    updating: bool | None,
    case: str,
    by: str,
    now: str,
) -> _Plan:
    """Decide the write from the state on disk; raises :class:`_Refused`.
    Writes nothing."""
    if not _valid_name(name):
        raise _Refused(
            KIND_BAD_LINE,
            [f"{name!r} is not a skill name (kebab-case, at most {SKILL_NAME_MAX_CHARS} characters)"],
        )
    if not isinstance(files, Mapping):
        raise _Refused(KIND_BAD_LINE, ["the draft must map file paths to their text"])
    registry = _load_registry(home)
    root = _skills_root(home)
    owned = registry.is_owned(name)
    if updating is None:
        updating = owned
    if updating and not owned:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"{name} is not a skill self-learn owns, so there is nothing to update"],
        )
    row = registry.row(name)
    plan = _Plan(name=name, root=root, updating=updating, row_before=row)
    expected_plugin = f"plugins/{name}"
    if updating and row is not None and row["plugin"] != expected_plugin:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"the registry row for {name} names {row['plugin']}, not {expected_plugin}"],
        )

    # -- names
    problems: list[str] = []
    loaded, catalogue_problems, clash_notes = _loaded_names(
        home, leaving_out=name if updating else None, own_folder=plan.folder
    )
    plan.notes += [f"skills on this machine: {p}" for p in catalogue_problems]
    plan.notes += clash_notes
    if not updating:
        taken: list[str] = []
        if plan.plugin_dir.exists():
            taken.append(f"the skills root already has a folder plugins/{name}")
        others = sorted(p for p in root.glob(f"plugins/*/skills/{name}") if p.is_dir())
        if others:
            taken.append(
                f"the skills root already has a skill folder named {name} "
                f"({os.path.relpath(others[0], root)})"
            )
        market_raw = (root / _MARKETPLACE_REL).read_text(encoding="utf-8")
        market_data, _layout = _read_marketplace(market_raw)
        if _entries_named(market_data, name):
            taken.append(f"{_MARKETPLACE_REL} already has an entry named {name}")
        link = link_path(name)
        if link.is_symlink() or link.exists():
            taken.append(f"{link} already exists")
        problems += [f"name-collision: {t}" for t in taken]

    # -- the template and the secret scan
    result = check_skill(
        files,
        loaded_names=sorted(loaded),
        vetoed_names=registry.vetoed_names(),
        expected_name=name,
    )
    problems += [str(p) if p.path == SKILL_ENTRY_FILE else f"{p} ({p.path})" for p in result.problems]
    plan.notes += [str(n) for n in result.notes]
    problems += _compiler_owned_in_draft(files)
    problems += _secret_problems(files)
    if problems:
        raise _Refused(KIND_BAD_LINE, problems, notes=plan.notes)
    draft: dict[str, str] = dict(files)  # every value is text: check_skill passed

    # -- the files as they would be deployed
    if updating and row is not None:
        created = row["created"]
        plan.stamp = {"authored_by": created["by"], "case": created["case"], "created": created["at"]}
        plan.recorded_sha = row["last_write"]["authored_sha256"]
    else:
        plan.stamp = {"authored_by": by, "case": case, "created": now}
    folder = plan.folder
    deployed = _read_tree(folder)
    deployed_md = deployed.get(SKILL_ENTRY_FILE)
    if deployed_md is not None:
        plan.current_sha = _authored_sha_or_refuse(deployed, "the deployed files")
    section, pointer = (
        _compiler_blocks(deployed_md) if deployed_md is not None else (None, None)
    )
    authored = _stamped(_without_section(draft[SKILL_ENTRY_FILE]) + "\n", plan.stamp)
    # Both compiler blocks are carried over byte for byte; everything else
    # in the deployed SKILL.md (a person's text after the section included)
    # is replaced by the draft, which is why an update with that text in
    # place needs --expect (the hash covers it) and why draft_view hands it
    # back to whoever edits the skill.
    new_md = _with_section(authored, section, pointer)
    plan.writes[folder / SKILL_ENTRY_FILE] = new_md
    for key, text in draft.items():
        if key != SKILL_ENTRY_FILE:
            plan.writes[folder / key] = text
    tracked = set(_tracked_under(root, folder)) if folder.is_dir() else set()
    for key in deployed:
        if _is_managed_reference(key) and key not in draft:
            path = folder / key
            if path in tracked:
                plan.removals.append(path)
    description = _read_frontmatter(draft[SKILL_ENTRY_FILE]).mapping["description"]  # type: ignore[index]
    # plugin.json and marketplace.json are edited from their COMMITTED text,
    # so a person's uncommitted edit there never reads as this write's own.
    manifest = plan.plugin_dir / _MANIFEST_REL
    manifest_text, manifest_note = _manifest_text(_head_text(root, manifest), name, description)
    if manifest_text is not None:
        plan.writes[manifest] = manifest_text
    if manifest_note:
        plan.notes.append(manifest_note)
    marketplace = root / _MARKETPLACE_REL
    market_base = _head_text(root, marketplace)
    if market_base is None:
        market_base = marketplace.read_text(encoding="utf-8")
    plan.writes[marketplace] = _marketplace_with(market_base, name, description)

    # The authored state after the write: SKILL.md and the draft's
    # references, plus every other deployed file, which the write leaves.
    after = {k: v for k, v in deployed.items() if not _is_managed_reference(k)}
    after.update({k: v for k, v in draft.items() if k != SKILL_ENTRY_FILE})
    after[SKILL_ENTRY_FILE] = new_md
    plan.new_sha = _authored_sha_or_refuse(after, "the files this write would leave")

    # -- the compare-and-swap (D4)
    if expect_sha is not None:
        if plan.current_sha != expect_sha:
            raise _Refused(
                KIND_TARGET_BUSY,
                [
                    f"the skill's files changed since they were read: expected authored sha256 "
                    f"{expect_sha}, found {plan.current_sha or 'no deployed SKILL.md'}"
                ],
                notes=plan.notes,
            )
    elif updating and plan.current_sha not in (plan.recorded_sha, plan.new_sha):
        # The files differ from what self-learn last wrote AND from what
        # this write would leave. The one case let through: no SKILL.md
        # at all while this write is exactly the one the row records (a
        # create interrupted before its files landed). An interrupted run
        # that DID write its files reads as current == new above.
        if plan.current_sha is not None:
            raise _Refused(
                KIND_TARGET_BUSY,
                [
                    f"{name} was changed since self-learn last wrote it (authored sha256 "
                    f"{plan.current_sha}, last written {plan.recorded_sha}); read the change "
                    f"and write again with --expect {plan.current_sha}"
                ],
                notes=plan.notes,
            )
        if plan.new_sha != plan.recorded_sha:
            raise _Refused(
                KIND_NEEDS_PERSON,
                [f"{name}'s folder or SKILL.md is missing from the skills root"],
                notes=plan.notes,
            )

    # -- lessons filed as references in the skill's own bucket: an entry
    # routed with --dest into an authored references file lives in that
    # file, which a write replaces or removes. (The shelf is never written
    # or removed by a write, so the lessons in it never stop one.)
    touched = {
        p.resolve()
        for p in [*plan.changed_writes(), *plan.removals]
        if p.is_relative_to(folder) and _is_managed_reference(p.relative_to(folder).as_posix())
    }
    if touched:
        reference_lessons = [
            rid
            for rid, destination, file in _routed(home, name)
            if destination == "reference" and file is not None and file.resolve() in touched
        ]
        if reference_lessons:
            raise _Refused(
                KIND_NEEDS_PERSON,
                [
                    f"{name}'s references hold lessons routed there as references "
                    f"({', '.join(reference_lessons)}); this write would change or remove the "
                    "files they live in, so a person must move the lessons first"
                ],
                notes=plan.notes,
            )

    # -- uncommitted changes that are not this write's own bytes
    dirty = _dirty_under(root, [plan.plugin_dir, marketplace])
    ours = {os.path.relpath(p, root): text for p, text in plan.writes.items()}
    busy: list[str] = []
    for rel in sorted(dirty):
        intended = ours.get(rel)
        try:
            disk = (root / rel).read_text(encoding="utf-8") if (root / rel).is_file() else None
        except (OSError, UnicodeDecodeError):
            disk = None
        if intended is None or disk != intended:
            busy.append(rel)
    if busy:
        raise _Refused(
            KIND_TARGET_BUSY,
            [f"uncommitted changes in the skills root: {', '.join(busy)}; retry once they are committed"],
            notes=plan.notes,
        )
    return plan


# ------------------------------------------------------------------ check


def _check_case_by(case: object, by: object) -> None:
    problems = []
    if not isinstance(case, str) or CASE_ID_RE.fullmatch(case) is None:
        problems.append(f"{case!r} is not a case id (case-xxxxxxxx)")
    if by not in BY_VALUES:
        problems.append(f"by must be one of {', '.join(BY_VALUES)}, got {by!r}")
    if problems:
        raise _Refused(KIND_BAD_LINE, problems)


def check(
    home: Path | str,
    name: str,
    files: Mapping[str, str | bytes],
    *,
    expect_sha: str | None = None,
    updating: bool | None = None,
) -> SkillWriteCheck:
    """Everything :func:`write` checks, writing nothing. *updating* is
    worked out from the registry when not given (a live row means update);
    ``True`` for a skill that is not owned is refused, ``False`` for one
    that is reads as a name collision."""
    home = Path(home)
    try:
        plan = _preflight(
            home, name, files, expect_sha=expect_sha, updating=updating,
            case=_PLACEHOLDER_CASE, by="overseer", now=chrono.now_iso(),
        )
    except _Refused as refused:
        return SkillWriteCheck(
            name=name, ok=False, kind=refused.kind, problems=refused.problems,
            notes=refused.notes,
        )
    return SkillWriteCheck(
        name=name, ok=True, notes=tuple(plan.notes),
        updating=plan.updating, current_sha=plan.current_sha, recorded_sha=plan.recorded_sha,
    )


# ------------------------------------------------------------------ write


def _registry_after_write(
    registry: skill_registry.Registry, *, name: str, sha: str, case: str, by: str, now: str
) -> None:
    """The row a write leaves: unchanged when it already records *sha* for a
    live skill; else ``last_write`` updated, or a new row."""
    row = registry.skills.get(name)
    if row is not None and row.get("status") == STATUS_LIVE:
        if row["last_write"]["authored_sha256"] == sha:
            return
        row["last_write"] = {"at": now, "case": case, "by": by, "authored_sha256": sha}
        return
    fresh: dict[str, Any] = {
        "status": STATUS_LIVE,
        "plugin": f"plugins/{name}",
        "created": {"at": now, "case": case, "by": by},
        "last_write": {"at": now, "case": case, "by": by, "authored_sha256": sha},
    }
    if row is not None and row.get("renamed_from"):
        fresh["renamed_from"] = list(row["renamed_from"])
    registry.skills[name] = fresh


def _registry_restore(registry: skill_registry.Registry, *, name: str, row: dict | None) -> None:
    if row is None:
        registry.skills.pop(name, None)
    else:
        registry.skills[name] = row


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {p: (p.read_bytes() if p.is_file() else None) for p in paths}


def _missing_dirs(paths: list[Path], stop: Path) -> list[Path]:
    """Folders above *paths* (up to *stop*) that do not exist yet, deepest
    first: a failed write takes them out again."""
    missing: set[Path] = set()
    for path in paths:
        for parent in path.parents:
            if parent == stop or stop not in parent.parents:
                break
            if not parent.exists():
                missing.add(parent)
    return sorted(missing, key=lambda p: len(p.parts), reverse=True)


def _deploy(plan: _Plan, subject: str, body: str) -> str | None:
    """Write the plan's changed files, take out its removals, and commit
    them (plus any of this write's own bytes left uncommitted by an
    interrupted run) in one skills-root commit. The caller holds the
    skills root's lock."""
    root = plan.root
    changed = plan.changed_writes()
    for path, text in changed.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(path, text, preserve_mode=True, fsync=True, follow_symlinks=True)
    for path in plan.removals:
        gitops.remove(root, path)
    # Changed files, plus this write's own bytes an interrupted run left
    # uncommitted (the preflight let only those through).
    dirty = _dirty_under(root, list(plan.writes))
    leftovers = {p for p in plan.writes if os.path.relpath(p, root) in dirty}
    paths = sorted(set(changed) | leftovers)
    if not paths and not plan.removals:
        return None
    gitops.stage(root, paths)
    return gitops.commit(root, subject, body=body, paths=[*paths, *plan.removals])


def _undo_deploy(
    plan: _Plan, snapshot: dict[Path, bytes | None], new_dirs: list[Path]
) -> str:
    """Put every file the failed write touched back as it was, unstaged,
    and take out the folders it made. The caller holds the skills root's
    lock. Returns a sentence for the report."""
    root = plan.root
    for path, data in snapshot.items():
        if data is None:
            if path.is_file() or path.is_symlink():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(path, data, preserve_mode=True, fsync=True, follow_symlinks=True)
    try:
        gitops.unstage(root, [p for p in snapshot if p.exists() or gitops.known_paths(root, [p])])
    except gitops.GitOpsError as exc:
        return f"the files were put back but could not be unstaged ({exc})"
    for directory in new_dirs:
        try:
            directory.rmdir()
        except OSError:
            pass
    return "the skills root was put back as it was"


def _subject(verb: str, name: str, case: str) -> str:
    return f"self-learn: skill {verb} {name} ({case})"


def _apply_write(home: Path, plan: _Plan, *, case: str, by: str, now: str) -> WriteResult:
    """The locked half of :func:`write`: registry row, files, link. The
    caller holds the ledger lock and the skills root's lock."""
    name = plan.name
    subject = _subject("write", name, case)
    body = f"By: {by}"
    ledger_sha = skill_registry.with_update(
        home,
        partial(_registry_after_write, name=name, sha=plan.new_sha, case=case, by=by, now=now),
        subject=subject,
        body=body,
    )
    touched = [*plan.writes, *plan.removals]
    snapshot = _snapshot(touched)
    new_dirs = _missing_dirs(list(plan.writes), plan.root)
    try:
        host_sha = _deploy(plan, subject, body)
    except (gitops.GitOpsError, OSError) as exc:
        undone = _undo_deploy(plan, snapshot, new_dirs)
        restored = None
        if ledger_sha is not None:
            try:
                restored = skill_registry.with_update(
                    home,
                    partial(_registry_restore, name=name, row=plan.row_before),
                    subject=_subject("write", name, case) + " undone: the skills-root write failed",
                    body=body,
                )
            except (SkillRegistryError, gitops.GitOpsError) as undo_exc:
                undone += f"; the registry row could not be put back ({undo_exc}): run the same write again to finish it"
        return WriteResult(
            name=name, ok=False, kind=KIND_GIT,
            problems=(f"the skills-root write failed ({exc}); {undone}",),
            notes=tuple(plan.notes), updating=plan.updating,
            ledger_sha=restored or ledger_sha,
        )
    try:
        link = link_skill(plan.root, name)
    except (SkillLinkError, OSError) as exc:
        return WriteResult(
            name=name, ok=False, kind=KIND_NEEDS_PERSON,
            problems=(
                f"the skill was written but could not be linked: {exc}; fix that path and run "
                "the same write again to finish",
            ),
            notes=tuple(plan.notes), updating=plan.updating, ledger_sha=ledger_sha,
            host_sha=host_sha, authored_sha256=plan.new_sha,
        )
    return WriteResult(
        name=name, ok=True, notes=tuple(plan.notes), updating=plan.updating,
        ledger_sha=ledger_sha, host_sha=host_sha, link=link, authored_sha256=plan.new_sha,
    )


def _write_locked(
    home: Path,
    name: str,
    files: Mapping[str, str | bytes],
    root: Path,
    *,
    case: str,
    by: str,
    expect_sha: str | None,
    updating: bool | None,
    now: str,
) -> WriteResult:
    """Take the ledger lock, then the skills root's lock (the one order),
    decide again from the state now, and apply."""
    with intents.ledger_write(home) as recovered, gitops.host_lock(root, "git"):
        intents.announce_recovered(recovered)
        try:
            plan = _preflight(
                home, name, files, expect_sha=expect_sha, updating=updating,
                case=case, by=by, now=now,
            )
        except _Refused as refused:
            return _refused_write(name, refused)
        return _apply_write(home, plan, case=case, by=by, now=now)


def _refused_write(name: str, refused: _Refused) -> WriteResult:
    return WriteResult(
        name=name, ok=False, kind=refused.kind, problems=refused.problems,
        notes=refused.notes,
    )


def _push(home: Path, root: Path, ledger_sha: str | None, host_sha: str | None):
    ledger_push = gitops.push_if_remote(home, is_ledger=True) if ledger_sha else None
    host_push = gitops.push_if_remote(root) if host_sha else None
    return ledger_push, host_push


def write(
    home: Path | str,
    name: str,
    files: Mapping[str, str | bytes],
    *,
    case: str,
    by: str,
    expect_sha: str | None = None,
    updating: bool | None = None,
    no_push: bool = False,
) -> WriteResult:
    """Check, then deploy the skill (module docstring). Idempotent by
    content: a second identical write makes no commit. *files* maps
    ``SKILL.md`` and ``references/<file>.md`` to their text; *case* is the
    case the write belongs to; *by* is ``overseer`` or ``human``."""
    home = Path(home)
    now = chrono.now_iso()
    try:
        _check_case_by(case, by)
        plan = _preflight(
            home, name, files, expect_sha=expect_sha, updating=updating,
            case=case, by=by, now=now,
        )
    except _Refused as refused:
        return _refused_write(name, refused)
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        result = _write_locked(
            home, name, files, plan.root, case=case, by=by,
            expect_sha=expect_sha, updating=updating, now=now,
        )
    except (gitops.GitOpsError, SkillRegistryError) as exc:
        return WriteResult(name=name, ok=False, kind=KIND_GIT, problems=(str(exc),))
    finally:
        hold.release()
    if no_push or not (result.ledger_sha or result.host_sha):
        return result
    ledger_push, host_push = _push(home, plan.root, result.ledger_sha, result.host_sha)
    return _with_pushes(result, ledger_push, host_push)


def _with_pushes(result, ledger_push, host_push):
    return replace(result, ledger_push=ledger_push, host_push=host_push)


# ----------------------------------------------------------------- retire


@dataclass
class _RetirePlan:
    name: str
    root: Path
    row: dict
    removals: list[Path]
    marketplace_text: str


def _retire_preflight(home: Path, name: str) -> _RetirePlan | None:
    """``None`` when the skill is already retired (nothing to do)."""
    if not _valid_name(name):
        raise _Refused(KIND_BAD_LINE, [f"{name!r} is not a skill name"])
    registry = _load_registry(home)
    row = registry.row(name)
    if row is not None and row["status"] == STATUS_RETIRED:
        return None
    if not registry.is_owned(name):
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"{name} is not a skill self-learn owns; self-learn retires only its own skills"],
        )
    assert row is not None
    root = _skills_root(home)
    routed = routed_lessons(home, name)
    if routed:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [
                f"{len(routed)} routed lesson(s) still compile into {name}: {', '.join(routed)}; "
                "move them out first (reroute each to its earlier place)"
            ],
            routed=routed,
        )
    plugin_dir = root / "plugins" / name
    marketplace = root / _MARKETPLACE_REL
    dirty = _dirty_under(root, [plugin_dir, marketplace])
    if dirty:
        raise _Refused(
            KIND_TARGET_BUSY,
            [f"uncommitted changes in the skills root: {', '.join(sorted(dirty))}; retry once they are committed"],
        )
    removals = _tracked_under(root, plugin_dir) if plugin_dir.is_dir() else []
    return _RetirePlan(
        name=name, root=root, row=row, removals=removals,
        marketplace_text=_marketplace_without(marketplace.read_text(encoding="utf-8"), name),
    )


def _registry_after_retire(
    registry: skill_registry.Registry, *, name: str, case: str, by: str, now: str
) -> None:
    row = registry.skills.get(name)
    if row is None or row.get("status") != STATUS_LIVE:
        return
    row["status"] = STATUS_RETIRED
    row["retired"] = {"at": now, "case": case, "by": by}


def _remove_plugin(plan: _RetirePlan, subject: str, body: str) -> str | None:
    """Take the plugin folder and the marketplace entry out in one
    skills-root commit. The caller holds the skills root's lock."""
    root = plan.root
    marketplace = root / _MARKETPLACE_REL
    paths: list[Path] = []
    if marketplace.read_text(encoding="utf-8") != plan.marketplace_text:
        fsops.atomic_write(
            marketplace, plan.marketplace_text, preserve_mode=True, fsync=True, follow_symlinks=True
        )
        gitops.stage(root, [marketplace])
        paths.append(marketplace)
    for path in plan.removals:
        gitops.remove(root, path)
        paths.append(path)
    _prune_empty_dirs(root / "plugins" / plan.name)
    if not paths:
        return None
    return gitops.commit(root, subject, body=body, paths=paths)


def _prune_empty_dirs(top: Path) -> None:
    """Remove *top* and every folder under it that is empty (deepest
    first); a folder that still holds anything stays."""
    if not top.is_dir():
        return
    folders = [d for d in top.rglob("*") if d.is_dir() and not d.is_symlink()]
    for directory in sorted(folders, key=lambda d: len(d.parts), reverse=True) + [top]:
        try:
            directory.rmdir()
        except OSError:
            pass


def _undo_remove(plan: _RetirePlan, snapshot: dict[Path, bytes | None], relink: bool) -> str:
    """Put the plugin folder, the marketplace and the link back after a
    failed retire. The caller holds the skills root's lock."""
    for path, data in snapshot.items():
        if data is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(path, data, preserve_mode=True, fsync=True, follow_symlinks=True)
    try:
        gitops.unstage(plan.root, list(snapshot))
    except gitops.GitOpsError as exc:
        return f"the files were put back but could not be unstaged ({exc})"
    if relink:
        try:
            _place_link(link_path(plan.name), skill_dir(plan.root, plan.name))
        except (SkillLinkError, OSError) as exc:
            return f"the files were put back, but the link could not be ({exc})"
    return "the skills root and the link were put back as they were"


def _apply_retire(home: Path, plan: _RetirePlan, *, case: str, by: str, now: str) -> RetireResult:
    """The locked half of :func:`retire`: link, then files, then the row.
    The caller holds the ledger lock and the skills root's lock."""
    name = plan.name
    subject = _subject("retire", name, case)
    body = f"By: {by}"
    snapshot = _snapshot([*plan.removals, plan.root / _MARKETPLACE_REL])
    unlinked = _drop_link(link_path(name), skill_dir(plan.root, name))
    try:
        host_sha = _remove_plugin(plan, subject, body)
    except (gitops.GitOpsError, OSError) as exc:
        undone = _undo_remove(plan, snapshot, unlinked)
        return RetireResult(
            name=name, ok=False, kind=KIND_GIT,
            problems=(f"the skills-root removal failed ({exc}); {undone}",),
        )
    try:
        ledger_sha = skill_registry.with_update(
            home,
            partial(_registry_after_retire, name=name, case=case, by=by, now=now),
            subject=subject,
            body=body,
        )
    except (gitops.GitOpsError, SkillRegistryError) as exc:
        # The skill is already gone from the skills root; only the row is
        # left. The removal commit is returned so retire() still pushes it,
        # and running the same retire again marks the row.
        return RetireResult(
            name=name, ok=False, kind=KIND_GIT,
            problems=(
                f"the skill was removed from the skills root, but the registry row could not be "
                f"marked retired ({exc}); run the same retire again to finish it",
            ),
            host_sha=host_sha, unlinked=unlinked,
        )
    return RetireResult(
        name=name, ok=True, ledger_sha=ledger_sha, host_sha=host_sha, unlinked=unlinked
    )


def _retire_locked(home: Path, name: str, root: Path, *, case: str, by: str, now: str) -> RetireResult:
    with intents.ledger_write(home) as recovered, gitops.host_lock(root, "git"):
        intents.announce_recovered(recovered)
        try:
            plan = _retire_preflight(home, name)
        except _Refused as refused:
            return RetireResult(
                name=name, ok=False, kind=refused.kind, problems=refused.problems,
                routed=refused.routed,
            )
        if plan is None:
            return RetireResult(name=name, ok=True, notes=(f"{name} is already retired",))
        return _apply_retire(home, plan, case=case, by=by, now=now)


def retire(
    home: Path | str, name: str, *, case: str, by: str, no_push: bool = False
) -> RetireResult:
    """Retire a skill self-learn owns (module docstring). Refused while any
    routed lesson still compiles into it; a skill already retired is a
    no-op success."""
    home = Path(home)
    now = chrono.now_iso()
    try:
        _check_case_by(case, by)
        plan = _retire_preflight(home, name)
    except _Refused as refused:
        return RetireResult(
            name=name, ok=False, kind=refused.kind, problems=refused.problems,
            routed=refused.routed,
        )
    if plan is None:
        return RetireResult(name=name, ok=True, notes=(f"{name} is already retired",))
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        result = _retire_locked(home, name, plan.root, case=case, by=by, now=now)
    except (gitops.GitOpsError, SkillRegistryError) as exc:
        return RetireResult(name=name, ok=False, kind=KIND_GIT, problems=(str(exc),))
    finally:
        hold.release()
    if no_push or not (result.ledger_sha or result.host_sha):
        return result
    ledger_push, host_push = _push(home, plan.root, result.ledger_sha, result.host_sha)
    return _with_pushes(result, ledger_push, host_push)


# ----------------------------------------------------------------- rename
#
# SK8 (S-107; skill-writing plan D15, §4.1 row SK8). A skill
# self-learn owns gets a new name. ``rename`` MOVES the skill, every byte
# kept except its name:
#
# 1. the registry row moves to the new name (one ledger commit): the same
#    ``created`` stamp, ``plugin: plugins/<new>``, a ``last_write`` for
#    this rename (the authored sha256 changes with the name line), and the
#    old name added to ``renamed_from``. The old row stays live until step
#    6, so nothing can scaffold a fresh skill under the old name meanwhile.
#    A rename that comes from the user's veto (``veto_statement``) bans the
#    old name for ever in the same commit;
# 2. the plugin folder moves in ONE skills-root commit:
#    ``plugins/<old>/skills/<old>/`` becomes ``plugins/<new>/skills/<new>/``;
#    SKILL.md's frontmatter ``name`` and plugin.json's ``name`` change; the
#    marketplace entry is renamed where it stands, every other byte of
#    ``marketplace.json`` unchanged. Every other file moves as it is, the
#    managed section and its lessons' lines included;
# 3. the links: ``~/.claude/skills/<old>`` goes, ``~/.claude/skills/<new>``
#    is made;
# 4. every lesson routed ``new-skill:<old>`` is re-routed to
#    ``new-skill:<new>``, one ledger commit each. Its routing block stays
#    whole except ``new_skill`` (``routed_at`` keeps the compiler's line
#    order; ``by`` still names who placed the lesson), and the old block
#    is displaced into the lesson's ``history`` (``event: routing``), as
#    ``reroute`` does. A ``new-skill`` target has no compile record
#    (U-hostmode §8 OUT-7), so nothing else in the ledger names the path;
# 5. the managed section is compared with what the compiler writes for
#    the lessons now routed to the new name, and recompiled (one more
#    skills-root commit) only when they differ, which only an interrupted
#    rename can cause;
# 6. the old row goes (one ledger commit), once no lesson routes to it.
#
# Refused: a new name that is not a skill name, is the old name, is vetoed,
# is loaded on this machine, or is already used in the skills root or in
# ``~/.claude/skills`` (``bad-line``); a skill self-learn does not own, or
# whose own ledger bucket ``skills/<old>/`` -- or the new name's bucket --
# holds records (``needs-person``: D15, "the overseer asks instead"); a
# skill changed since self-learn last wrote it, unless ``expect_sha`` names
# its files as they are now, and uncommitted changes in either plugin
# folder or in ``marketplace.json`` (``target-busy``); a plugin folder that
# holds a symlink, a file that is not UTF-8 text, or another skill's folder
# (``needs-person``).
#
# Interrupted renames: every step is computed from the skills root's HEAD
# and the ledger as they are, so running the same rename again finishes
# it. An uncommitted half-move is taken up only when every changed file
# holds this rename's own bytes. A rerun of a finished rename changes
# nothing beyond making sure of the link and the veto. A skills-root commit
# that FAILS puts the skills root back as HEAD has it and, on a first run,
# the registry row too.
#
# Every write runs under the ledger lock and the skills root's lock, taken
# in :func:`_rename_locked` (the one order: ledger first), in the named
# functions it calls -- no nested closures (``tests/test_lock_invariant.py``).

#: The registry stages of a rename (see :func:`_rename_preflight`).
_STAGE_FRESH = "fresh"
_STAGE_RESUME = "resume"
_STAGE_DONE = "done"


@dataclass(frozen=True)
class RenameResult:
    old: str
    new: str
    ok: bool
    kind: str | None = None
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    #: The lessons this run moved from ``new-skill:<old>`` to ``new-skill:<new>``.
    rerouted: tuple[str, ...] = ()
    #: Every ledger commit this run made, in order.
    ledger_shas: tuple[str, ...] = ()
    #: The skills-root commit that moved the plugin (``None``: not this run).
    host_sha: str | None = None
    #: The skills-root commit that recompiled the managed section (step 5).
    settle_sha: str | None = None
    #: What making ``~/.claude/skills/<new>`` did: ``created``, ``replaced``
    #: or ``unchanged``.
    link: str | None = None
    #: Whether ``~/.claude/skills/<old>`` was removed.
    unlinked: bool = False
    #: Whether this run added the old name to the vetoed names.
    vetoed: bool = False
    #: The authored sha256 of the skill's files under the new name.
    authored_sha256: str | None = None
    warnings: tuple[str, ...] = ()
    ledger_push: gitops.PushResult | None = None
    host_push: gitops.PushResult | None = None

    @property
    def changed(self) -> bool:
        return bool(
            self.ledger_shas or self.host_sha or self.settle_sha or self.unlinked
            or self.link in ("created", "replaced")
        )


@dataclass
class _RenamePlan:
    """Everything a rename decided from the state on disk."""

    old: str
    new: str
    root: Path
    #: ``fresh`` (nothing done yet), ``resume`` (step 1 is committed and
    #: the old row is still live) or ``done`` (only the link and the veto
    #: are made sure of).
    stage: str
    #: The row step 1 writes under the new name (``None``: it is there).
    new_row: dict | None = None
    #: The new name's registry row before step 1, put back when a first
    #: run's skills-root move fails.
    new_row_before: dict | None = None
    #: ``{at, statement}`` of the user's veto of the old name, if any.
    veto: dict | None = None
    adds_veto: bool = False
    #: Whether HEAD already has the plugin under its new name.
    host_moved: bool = False
    #: Each file under its new path, with its text after the rename.
    writes: dict[Path, str] = field(default_factory=dict)
    #: Each old tracked file, with its text at HEAD (step 2's undo).
    removals: dict[Path, str] = field(default_factory=dict)
    #: Paths (old and new) whose git mode is 100755.
    executable: set[Path] = field(default_factory=set)
    marketplace_head: str = ""
    marketplace_text: str = ""
    current_sha: str | None = None
    new_sha: str | None = None
    #: ``(id, path)`` of every lesson routed ``new-skill:<old>``.
    lessons: list[tuple[str, Path]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _rename_subject(old: str, new: str, case: str) -> str:
    return f"self-learn: skill rename {old} → {new} ({case})"


def _head_entries(root: Path, rel_dir: str) -> list[tuple[str, str]]:
    """``(git mode, repo-relative path)`` of every file the skills root's
    HEAD has under *rel_dir*. The whole tree is listed and filtered here,
    so no path argument's matching rules decide what counts."""
    proc = gitops._git_ok(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")  # noqa: SLF001 -- a read
    prefix = rel_dir.rstrip("/") + "/"
    entries: list[tuple[str, str]] = []
    for item in proc.stdout.split("\0"):
        meta, tab, path = item.partition("\t")
        if tab and path.startswith(prefix):
            entries.append((meta.split(" ", 1)[0], path))
    return entries


def _head_file_text(root: Path, rel: str) -> str | None:
    """*rel*'s exact text at the skills root's HEAD (bytes decoded as
    UTF-8, no newline translation); ``None`` when HEAD has no such file.
    A file that is not UTF-8 is refused."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{rel}"],
            capture_output=True,
            timeout=gitops.GIT_LOCAL_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise gitops.GitOpsError(f"git show HEAD:{rel} in {root} timed out") from exc
    if proc.returncode != 0:
        return None
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"{rel} is not a UTF-8 text file; a person must rename this plugin"],
        ) from exc


def _holds(path: Path, text: str) -> bool:
    """Whether *path* is a plain file holding exactly *text*'s bytes."""
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.read_bytes() == text.encode("utf-8")
        )
    except OSError:
        return False


def _make_executable(path: Path) -> None:
    os.chmod(path, path.stat().st_mode | 0o111)


def _lessons_routed_to(home: Path, name: str) -> list[tuple[str, Path]]:
    """``(id, path)`` of every ROUTED lesson whose routing names
    ``new-skill:<name>``, by id."""
    from . import ledger_ops  # local: as in _routed
    from .ledger import discover_buckets
    from .records import Record

    found: dict[str, Path] = {}
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except ledger_ops.UNREADABLE_RECORD_ERRORS:
                continue
            routing = record.routing or {}
            if (
                record.status == "routed"
                and routing.get("destination") == "new-skill"
                and routing.get("new_skill") == name
                and record.id not in found
            ):
                found[record.id] = path
    return sorted(found.items())


def _bucket_records(home: Path, name: str) -> list[str]:
    """The ids of every record filed anywhere in the ledger bucket
    ``skills/<name>/`` (pending, resolved, or any other folder in it)."""
    bucket = home / "skills" / name
    if not bucket.is_dir():
        return []
    return sorted({p.stem for p in bucket.rglob("lrn-*.md") if p.is_file()})


# -- the three name edits (pure)


def _renamed_skill_md(text: str, old: str, new: str) -> str:
    """SKILL.md *text* with its frontmatter ``name`` changed from *old* to
    *new*: the one ``name:`` line rewritten, every other byte unchanged,
    read back to prove it. Anything else is a person's to do."""
    read = _read_frontmatter(text)
    if read.mapping is None or read.mapping.get("name") != old:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [
                f"{SKILL_ENTRY_FILE}: its frontmatter does not name the skill {old}; a person "
                "must repair it before it is renamed"
            ],
        )
    opening, inner, closing, body = _split_frontmatter(text)
    pattern = re.compile(rf"name:[ \t]*(?P<q>[\"']?){re.escape(old)}(?P=q)[ \t]*")
    lines = inner.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if pattern.fullmatch(line.rstrip("\r\n"))]
    if len(hits) == 1:
        index = hits[0]
        ending = lines[index][len(lines[index].rstrip("\r\n")) :]
        lines[index] = f"name: {new}{ending}"
        new_text = opening + "".join(lines) + closing + body
        after = _read_frontmatter(new_text)
        if after.mapping == {**read.mapping, "name": new} and after.body == body:
            return new_text
    raise _Refused(
        KIND_NEEDS_PERSON,
        [
            f"{SKILL_ENTRY_FILE}: its name line could not be changed to {new} without touching "
            "the rest of the frontmatter; a person must rename the skill"
        ],
    )


def _renamed_manifest(raw: str, old: str, new: str) -> str:
    """plugin.json *raw* with ``name`` changed from *old* to *new*, in the
    file's own layout."""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    layout = _json_layout(raw, data) if isinstance(data, dict) else None
    if not isinstance(data, dict) or layout is None or data.get("name") != old:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [
                f"plugins/{old}/{_MANIFEST_REL} is not two-space JSON naming {old}, so "
                "self-learn cannot change only its name; a person must rename the plugin"
            ],
        )
    data["name"] = new
    return _dump_json(data, layout)


def _marketplace_renamed(raw: str, old: str, new: str) -> str:
    """marketplace.json *raw* with the entry for *old* renamed to *new*
    (``name`` and ``source``) where it stands; every other entry and key,
    and the file's own JSON layout, unchanged."""
    data, layout = _read_marketplace(raw)
    if _entries_named(data, new):
        raise _Refused(
            KIND_BAD_LINE,
            [f"name-collision: {_MARKETPLACE_REL} already has an entry named {new}"],
        )
    entries = _entries_named(data, old)
    if len(entries) != 1 or entries[0].get("source") != f"./plugins/{old}":
        raise _Refused(
            KIND_NEEDS_PERSON,
            [
                f"{_MARKETPLACE_REL} has no single entry named {old} with source "
                f"./plugins/{old}; a person must repair it before the skill is renamed"
            ],
        )
    entries[0]["name"] = new
    entries[0]["source"] = f"./plugins/{new}"
    return _dump_json(data, layout)


# -- the preflight (writes nothing)


def _rename_bucket_check(home: Path, plan: _RenamePlan) -> None:
    """D15: a skill whose own ledger bucket (``skills/<old>/`` or
    ``skills/<new>/``) holds records is not renamed. Run on a first run AND
    on every resumed run that is not done (integration 2026-10-31, the sk8
    gate's MINOR): a record filed there between a crash and the rerun would
    otherwise be stranded on a folder that no longer exists, or start
    compiling into the renamed skill."""
    held = [(name, ids) for name in (plan.old, plan.new) if (ids := _bucket_records(home, name))]
    if held:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [
                f"the ledger bucket skills/{name}/ holds record(s) {', '.join(ids)}; a skill "
                "whose own bucket holds records is not renamed, so a person must decide"
                for name, ids in held
            ],
        )


def _rename_name_check(home: Path, plan: _RenamePlan, vetoed: set[str]) -> None:
    """A first run's checks on the names: the new name as ``skill write``
    would check it, then what already uses it (the buckets are
    :func:`_rename_bucket_check`'s, on every run that is not done)."""
    root, old, new = plan.root, plan.old, plan.new
    loaded, catalogue_problems, _clashes = _loaded_names(home, leaving_out=None)
    plan.notes += [f"skills on this machine: {p}" for p in catalogue_problems]
    problems = [
        str(finding)
        for finding in _check_name(
            new,
            loaded_names=frozenset(loaded),
            vetoed_names=frozenset(vetoed),
            expected_name=None,
        )
    ]
    taken: list[str] = []
    if (root / "plugins" / new).exists():
        taken.append(f"the skills root already has a folder plugins/{new}")
    others = sorted(p for p in root.glob(f"plugins/*/skills/{new}") if p.is_dir())
    if others:
        taken.append(
            f"the skills root already has a skill folder named {new} "
            f"({os.path.relpath(others[0], root)})"
        )
    link = link_path(new)
    if link.is_symlink() or link.exists():
        taken.append(f"{link} already exists")
    problems += [f"name-collision: {t}" for t in taken]
    if problems:
        raise _Refused(KIND_BAD_LINE, problems, notes=plan.notes)


def _rename_host_plan(plan: _RenamePlan) -> None:
    """Fill in step 2 from the skills root's HEAD (writes nothing), or mark
    it done when HEAD already has the plugin under its new name."""
    root, old, new = plan.root, plan.old, plan.new
    old_rel, new_rel = f"plugins/{old}", f"plugins/{new}"
    head_old = _head_entries(root, old_rel)
    head_new = _head_entries(root, new_rel)
    if head_old and head_new:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"the skills root has both {old_rel} and {new_rel} committed; a person must decide"],
        )
    if not head_old:
        moved_md = f"{new_rel}/skills/{new}/{SKILL_ENTRY_FILE}"
        if plan.stage == _STAGE_RESUME and any(path == moved_md for _mode, path in head_new):
            plan.host_moved = True
            return
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"the skills root has no committed {old_rel}/skills/{old}/{SKILL_ENTRY_FILE} to rename"],
        )
    skill_prefix = f"skills/{old}/"
    old_skill: dict[str, str] = {}
    new_skill: dict[str, str] = {}
    for mode, path in head_old:
        rest = path[len(old_rel) + 1 :]
        if mode not in ("100644", "100755"):
            raise _Refused(
                KIND_NEEDS_PERSON,
                [f"{path} is not a plain file (git mode {mode}); a person must rename this plugin"],
            )
        if rest.startswith("skills/") and not rest.startswith(skill_prefix):
            raise _Refused(
                KIND_NEEDS_PERSON,
                [f"{old_rel} holds another skill's folder ({path}); a person must rename this plugin"],
            )
        text = _head_file_text(root, path)
        if text is None:  # pragma: no cover -- ls-tree just listed it
            raise _Refused(KIND_NEEDS_PERSON, [f"{path} cannot be read from HEAD"])
        if rest == f"{skill_prefix}{SKILL_ENTRY_FILE}":
            new_text = _renamed_skill_md(text, old, new)
        elif rest == _MANIFEST_REL:
            new_text = _renamed_manifest(text, old, new)
        else:
            new_text = text
        in_skill = rest.startswith(skill_prefix)
        new_rest = f"skills/{new}/{rest[len(skill_prefix):]}" if in_skill else rest
        if in_skill:
            old_skill[rest[len(skill_prefix) :]] = text
            new_skill[rest[len(skill_prefix) :]] = new_text
        target = root / new_rel / new_rest
        plan.writes[target] = new_text
        plan.removals[root / path] = text
        if mode == "100755":
            plan.executable.update({target, root / path})
    if SKILL_ENTRY_FILE not in old_skill:
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"the skills root has no committed {old_rel}/skills/{old}/{SKILL_ENTRY_FILE} to rename"],
        )
    market = _head_file_text(root, _MARKETPLACE_REL)
    if market is None:
        raise _Refused(
            KIND_DESTINATION_UNAVAILABLE,
            [f"the skills root has no committed {_MARKETPLACE_REL}"],
        )
    plan.marketplace_head = market
    plan.marketplace_text = _marketplace_renamed(market, old, new)
    try:
        plan.current_sha = _authored_sha(old_skill)
        plan.new_sha = _authored_sha(new_skill)
    except SkillRegistryError as exc:
        raise _Refused(KIND_NEEDS_PERSON, [f"the skill's files cannot be hashed: {exc}"]) from exc


def _rename_dirty_check(plan: _RenamePlan) -> None:
    """Uncommitted changes in either plugin folder or the marketplace
    refuse the rename (``target-busy``); on a rerun, the changes an
    interrupted step 2 left (its own new files, its own removals, its own
    marketplace) are let through."""
    root = plan.root
    marketplace = root / _MARKETPLACE_REL
    dirty = _dirty_under(
        root, [root / "plugins" / plan.old, root / "plugins" / plan.new, marketplace]
    )
    ours = {os.path.relpath(p, root): text for p, text in plan.writes.items()}
    ours[_MARKETPLACE_REL] = plan.marketplace_text
    gone = {os.path.relpath(p, root) for p in plan.removals}
    busy: list[str] = []
    for rel in sorted(dirty):
        path = root / rel
        if plan.stage == _STAGE_RESUME:
            if rel in gone and not path.exists() and not path.is_symlink():
                continue
            if rel in ours and _holds(path, ours[rel]):
                continue
        busy.append(rel)
    if busy:
        raise _Refused(
            KIND_TARGET_BUSY,
            [f"uncommitted changes in the skills root: {', '.join(busy)}; retry once they are committed"],
            notes=plan.notes,
        )


def _rename_preflight(
    home: Path,
    old: str,
    new: str,
    *,
    case: str,
    by: str,
    now: str,
    expect_sha: str | None,
    veto_statement: str | None,
) -> _RenamePlan:
    """Decide the rename from the state on disk; raises :class:`_Refused`.
    Writes nothing.

    The registry says how far an earlier run got: no row under the new
    name naming the old one in ``renamed_from`` is a FIRST run; such a row
    with the old row still live and carrying the same ``created`` stamp
    (step 1 copies it) is a RERUN of an interrupted one; such a row with
    no live old row is a FINISHED rename. A live old row with another
    ``created`` stamp is a skill made under the old name since, and is
    renamed only as a first run would be (refused: the new name is taken)."""
    for value in (old, new):
        if not _valid_name(value):
            raise _Refused(
                KIND_BAD_LINE,
                [f"{value!r} is not a skill name (kebab-case, at most {SKILL_NAME_MAX_CHARS} characters)"],
            )
    if old == new:
        raise _Refused(KIND_BAD_LINE, [f"{old} already has that name"])
    registry = _load_registry(home)
    root = _skills_root(home)
    old_row, new_row = registry.row(old), registry.row(new)
    renamed = (
        new_row is not None
        and new_row["status"] == STATUS_LIVE
        and old in (new_row.get("renamed_from") or [])
    )
    if renamed and not registry.is_owned(old):
        stage = _STAGE_DONE
    elif (
        renamed
        and old_row is not None
        and new_row is not None
        and old_row["created"] == new_row["created"]
    ):
        stage = _STAGE_RESUME
    elif not registry.is_owned(old):
        raise _Refused(
            KIND_NEEDS_PERSON,
            [f"{old} is not a skill self-learn owns; self-learn renames only its own skills"],
        )
    elif registry.is_owned(new):
        raise _Refused(KIND_BAD_LINE, [f"name-collision: {new} is already a skill self-learn owns"])
    else:
        stage = _STAGE_FRESH
    plan = _RenamePlan(old=old, new=new, root=root, stage=stage, new_row_before=new_row)
    vetoed = {name.casefold() for name in registry.vetoed_names()}
    if veto_statement is not None:
        plan.veto = {"at": now, "statement": veto_statement}
        plan.adds_veto = old.casefold() not in vetoed

    if stage == _STAGE_DONE:
        assert new_row is not None
        if _head_entries(root, f"plugins/{old}") or not (
            skill_dir(root, new) / SKILL_ENTRY_FILE
        ).is_file():
            raise _Refused(
                KIND_NEEDS_PERSON,
                [
                    f"the registry says {old} was renamed to {new}, but the skills root does not "
                    f"hold the skill under plugins/{new} alone; a person must repair it"
                ],
            )
        plan.host_moved = True
        plan.new_sha = new_row["last_write"]["authored_sha256"]
        plan.notes.append(f"{old} was already renamed to {new}")
        return plan

    _rename_bucket_check(home, plan)
    if stage == _STAGE_FRESH:
        _rename_name_check(home, plan, vetoed)
    _rename_host_plan(plan)
    if not plan.host_moved:
        _rename_dirty_check(plan)
    if stage == _STAGE_FRESH:
        assert old_row is not None
        recorded = old_row["last_write"]["authored_sha256"]
        if expect_sha is not None and plan.current_sha != expect_sha:
            raise _Refused(
                KIND_TARGET_BUSY,
                [
                    f"the skill's files changed since they were read: expected authored sha256 "
                    f"{expect_sha}, found {plan.current_sha}"
                ],
                notes=plan.notes,
            )
        if expect_sha is None and plan.current_sha != recorded:
            raise _Refused(
                KIND_TARGET_BUSY,
                [
                    f"{old} was changed since self-learn last wrote it (authored sha256 "
                    f"{plan.current_sha}, last written {recorded}); read the change and rename "
                    f"again with --expect {plan.current_sha}"
                ],
                notes=plan.notes,
            )
        renamed_from = [name for name in (old_row.get("renamed_from") or []) if name != new]
        if old not in renamed_from:
            renamed_from.append(old)
        assert plan.new_sha is not None
        plan.new_row = {
            "status": STATUS_LIVE,
            "plugin": f"plugins/{new}",
            "created": dict(old_row["created"]),
            "last_write": {"at": now, "case": case, "by": by, "authored_sha256": plan.new_sha},
            "renamed_from": renamed_from,
        }
    else:
        assert new_row is not None
        recorded_new = new_row["last_write"]["authored_sha256"]
        if not plan.host_moved and plan.new_sha != recorded_new:
            raise _Refused(
                KIND_NEEDS_PERSON,
                [
                    f"plugins/{old} changed since the interrupted rename to {new} began (its "
                    f"files would hash {plan.new_sha}, the registry row records {recorded_new}); "
                    "a person must decide"
                ],
            )
        plan.new_sha = recorded_new
    plan.lessons = _lessons_routed_to(home, old)
    return plan


# -- the registry steps


def _registry_rename_begin(
    registry: skill_registry.Registry,
    *,
    old: str,
    new: str,
    row: dict | None,
    veto: dict | None,
) -> None:
    """Step 1: the row under the new name, unless a live one is there
    already, and the user's veto of the old name, unless it is banned."""
    if row is not None:
        current = registry.skills.get(new)
        if current is None or current.get("status") != STATUS_LIVE:
            registry.skills[new] = copy.deepcopy(row)
    if veto is not None:
        registry.add_veto(old, at=veto["at"], statement=veto["statement"])


def _registry_rename_finish(registry: skill_registry.Registry, *, old: str, new: str) -> None:
    """Step 6: the old row goes, when it is live, the new row names it in
    ``renamed_from``, and both carry the same ``created`` stamp (the row
    step 1 moved, not a skill made under the old name since)."""
    row = registry.skills.get(old)
    moved = registry.skills.get(new)
    if row is None or row.get("status") != STATUS_LIVE:
        return
    if moved is None or moved.get("status") != STATUS_LIVE:
        return
    if old not in (moved.get("renamed_from") or []) or row.get("created") != moved.get("created"):
        return
    del registry.skills[old]


# -- the skills-root and ledger steps (the caller holds both locks)


def _move_plugin(plan: _RenamePlan, subject: str, body: str) -> str:
    """Step 2: write the plugin under its new name, take the old files out,
    and commit both halves with the marketplace in one skills-root commit.
    Files an interrupted run already wrote are left as they are."""
    root = plan.root
    marketplace = root / _MARKETPLACE_REL
    writes = {**plan.writes, marketplace: plan.marketplace_text}
    for path, text in writes.items():
        if not _holds(path, text):
            path.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(path, text, preserve_mode=True, fsync=True, follow_symlinks=True)
        if path in plan.executable:
            _make_executable(path)
    for path in plan.removals:
        if gitops.is_tracked(root, path):
            gitops.remove(root, path)
    _prune_empty_dirs(root / "plugins" / plan.old)
    gitops.stage(root, list(writes))
    return gitops.commit(root, subject, body=body, paths=[*writes, *plan.removals])


def _undo_move(plan: _RenamePlan) -> str:
    """Put the skills root back as HEAD has it after a failed step 2: the
    new files gone, the old ones back, the marketplace as committed, all
    of it unstaged. Returns a sentence for the report."""
    root = plan.root
    marketplace = root / _MARKETPLACE_REL
    for path in plan.writes:
        if path.is_file() or path.is_symlink():
            path.unlink()
    for path, text in plan.removals.items():
        if not _holds(path, text):
            path.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(path, text, preserve_mode=True, fsync=True, follow_symlinks=True)
        if path in plan.executable:
            _make_executable(path)
    if not _holds(marketplace, plan.marketplace_head):
        fsops.atomic_write(
            marketplace, plan.marketplace_head, preserve_mode=True, fsync=True, follow_symlinks=True
        )
    touched = [*plan.writes, *plan.removals, marketplace]
    try:
        gitops.unstage(root, [p for p in touched if p.exists() or gitops.known_paths(root, [p])])
    except gitops.GitOpsError as exc:
        return f"the files were put back but could not be unstaged ({exc})"
    _prune_empty_dirs(root / "plugins" / plan.new)
    return "the skills root was put back as it was"


def _reroute_lesson(
    home: Path, path: Path, *, old: str, new: str, subject: str, body: str
) -> str | None:
    """Step 4 for one lesson: ``new_skill`` changed from *old* to *new*,
    the rest of its routing block as it was, the old block displaced into
    its history; one ledger commit. ``None`` when the lesson no longer
    routes to *old*. The caller holds the ledger lock."""
    from .records import Record  # local: as in _routed

    record = Record.from_path(path)
    routing = record.routing or {}
    if (
        record.status != "routed"
        or routing.get("destination") != "new-skill"
        or routing.get("new_skill") != old
    ):
        return None
    intent = intents.begin(home, "skill-rename", [path], subject)
    record.append_history("routing", {"routing": copy.deepcopy(routing)})
    moved = copy.deepcopy(routing)
    moved["new_skill"] = new
    record.set_routing(moved)
    record.write(path)
    intents.complete(intent)
    sha = gitops.stage_and_commit(home, [path], subject, body)
    intents.finish(intent)
    return sha


def _settle_section(
    home: Path, plan: _RenamePlan, body: str
) -> tuple[str | None, str | None]:
    """Step 5: recompile the managed section under the new name when it is
    not what the compiler writes for the lessons routed there now (only an
    interrupted rename leaves it so). Returns ``(skills-root commit,
    warning)``; a failure is a warning naming ``self-learn recompile``,
    never a failed rename: the lessons are routed either way."""
    from . import verbs  # local: verbs imports a great deal

    root = plan.root
    target = skill_dir(root, plan.new) / SKILL_ENTRY_FILE
    records = verbs._target_matched_records(  # noqa: SLF001 -- the compiler's own set
        home, target.resolve(), ("skill-md", "new-skill"), user_claude_md=None
    )
    if not records:
        return None, None
    before = target.read_bytes()
    try:
        section = compile_managed_file(target, records)
    except (CompileError, OSError) as exc:
        return None, (
            f"the managed section of {plan.new} was not checked ({exc}); run "
            "`self-learn recompile` to repair it"
        )
    if not section.changed:
        return None, None
    rel = os.path.relpath(target, root)
    try:
        gitops.stage(root, [target])
        sha = gitops.commit(
            root,
            f"self-learn: recompile {rel} (skill rename {plan.old} → {plan.new})",
            body=body,
            paths=[target],
        )
    except gitops.GitOpsError as exc:
        fsops.atomic_write(target, before, preserve_mode=True, fsync=True, follow_symlinks=True)
        try:
            gitops.unstage(root, [target])
        except gitops.GitOpsError:
            pass
        return None, (
            f"the managed section of {plan.new} is stale and its recompile could not be "
            f"committed ({exc}); run `self-learn recompile` to repair it"
        )
    return sha, None


def _rename_outcome(plan: _RenamePlan, **fields: Any) -> RenameResult:
    fields.setdefault("notes", tuple(plan.notes))
    fields.setdefault("authored_sha256", plan.new_sha)
    for key in ("problems", "rerouted", "ledger_shas", "warnings"):
        if key in fields:
            fields[key] = tuple(fields[key])
    return RenameResult(old=plan.old, new=plan.new, **fields)


def _apply_rename(home: Path, plan: _RenamePlan, *, case: str, by: str) -> RenameResult:
    """The locked half of :func:`rename`: steps 1 to 6 of the section
    comment, each skipped when an earlier run finished it. The caller
    holds the ledger lock and the skills root's lock."""
    from . import ledger_ops  # local: as in _routed

    old, new, root = plan.old, plan.new, plan.root
    subject = _rename_subject(old, new, case)
    body = f"By: {by}"
    shas: list[str] = []

    begun = skill_registry.with_update(
        home,
        partial(_registry_rename_begin, old=old, new=new, row=plan.new_row, veto=plan.veto),
        subject=subject,
    )
    if begun is not None:
        shas.append(begun)
    vetoed = plan.adds_veto and begun is not None

    host_sha = None
    if not plan.host_moved:
        try:
            host_sha = _move_plugin(plan, subject, body)
        except (gitops.GitOpsError, OSError) as exc:
            undone = _undo_move(plan)
            if plan.stage == _STAGE_FRESH and begun is not None:
                try:
                    restored = skill_registry.with_update(
                        home,
                        partial(_registry_restore, name=new, row=plan.new_row_before),
                        subject=f"{subject} undone: the skills-root move failed",
                    )
                except (SkillRegistryError, gitops.GitOpsError) as undo_exc:
                    undone += (
                        f"; the registry row for {new} could not be put back ({undo_exc}): run "
                        "the same rename again to finish it"
                    )
                else:
                    if restored is not None:
                        shas.append(restored)
            return _rename_outcome(
                plan, ok=False, kind=KIND_GIT, ledger_shas=shas, vetoed=vetoed,
                problems=[f"the skills-root move failed ({exc}); {undone}"],
            )

    try:
        unlinked = _drop_link(link_path(old), skill_dir(root, old))
        link = _place_link(link_path(new), skill_dir(root, new))
    except (SkillLinkError, OSError) as exc:
        return _rename_outcome(
            plan, ok=False, kind=KIND_NEEDS_PERSON, ledger_shas=shas, host_sha=host_sha,
            vetoed=vetoed,
            problems=[
                f"{old} was moved to {new} but could not be linked: {exc}; fix that path and "
                "run the same rename again to finish"
            ],
        )

    rerouted: list[str] = []
    try:
        for record_id, path in plan.lessons:
            sha = _reroute_lesson(
                home, path, old=old, new=new, body=body,
                subject=f"self-learn: reroute {record_id} → new-skill:{new} (skill rename {old}, {case})",
            )
            if sha is not None:
                shas.append(sha)
                rerouted.append(record_id)
    except (gitops.GitOpsError, *ledger_ops.UNREADABLE_RECORD_ERRORS) as exc:
        return _rename_outcome(
            plan, ok=False,
            kind=KIND_GIT if isinstance(exc, gitops.GitOpsError) else KIND_NEEDS_PERSON,
            ledger_shas=shas, host_sha=host_sha, link=link, unlinked=unlinked,
            rerouted=rerouted, vetoed=vetoed,
            problems=[
                f"re-routing the lessons of {old} stopped ({exc}); run the same rename again "
                "to finish"
            ],
        )

    warnings: list[str] = []
    settle_sha = None
    if plan.stage != _STAGE_DONE:
        settle_sha, warning = _settle_section(home, plan, body)
        if warning:
            warnings.append(warning)
        remaining = [record_id for record_id, _path in _lessons_routed_to(home, old)]
        if remaining:
            return _rename_outcome(
                plan, ok=False, kind=KIND_NEEDS_PERSON, ledger_shas=shas, host_sha=host_sha,
                settle_sha=settle_sha, link=link, unlinked=unlinked, rerouted=rerouted,
                vetoed=vetoed, warnings=warnings,
                problems=[
                    f"lesson(s) {', '.join(remaining)} still route to new-skill:{old}, so its "
                    "registry row stays; run the same rename again to finish"
                ],
            )
        finished = skill_registry.with_update(
            home, partial(_registry_rename_finish, old=old, new=new), subject=subject
        )
        if finished is not None:
            shas.append(finished)
    return _rename_outcome(
        plan, ok=True, ledger_shas=shas, host_sha=host_sha, settle_sha=settle_sha, link=link,
        unlinked=unlinked, rerouted=rerouted, vetoed=vetoed, warnings=warnings,
    )


def _refused_rename(old: str, new: str, refused: _Refused) -> RenameResult:
    return RenameResult(
        old=old, new=new, ok=False, kind=refused.kind, problems=refused.problems,
        notes=refused.notes,
    )


def _rename_locked(
    home: Path,
    old: str,
    new: str,
    root: Path,
    *,
    case: str,
    by: str,
    now: str,
    expect_sha: str | None,
    veto_statement: str | None,
) -> RenameResult:
    """Take the ledger lock, then the skills root's lock (the one order),
    decide again from the state now, and apply."""
    with intents.ledger_write(home) as recovered, gitops.host_lock(root, "git"):
        intents.announce_recovered(recovered)
        try:
            plan = _rename_preflight(
                home, old, new, case=case, by=by, now=now,
                expect_sha=expect_sha, veto_statement=veto_statement,
            )
        except _Refused as refused:
            return _refused_rename(old, new, refused)
        return _apply_rename(home, plan, case=case, by=by)


def rename(
    home: Path | str,
    old: str,
    new: str,
    *,
    case: str,
    by: str,
    veto_statement: str | None = None,
    expect_sha: str | None = None,
    no_push: bool = False,
) -> RenameResult:
    """Rename a skill self-learn owns from *old* to *new* (the rename
    section above). *veto_statement* is the statement id of the user's
    veto when the rename comes from one: the old name is then banned for
    ever. *expect_sha* is the authored sha256 of the skill's files as the
    caller read them, needed when they changed since self-learn last wrote
    them. Running the same rename again finishes an interrupted one and
    changes nothing after a finished one."""
    home = Path(home)
    now = chrono.now_iso()
    try:
        _check_case_by(case, by)
        if veto_statement is not None and (
            not isinstance(veto_statement, str) or STMT_ID_RE.fullmatch(veto_statement) is None
        ):
            raise _Refused(
                KIND_BAD_LINE, [f"{veto_statement!r} is not a statement id (stmt-xxxxxxxx)"]
            )
        plan = _rename_preflight(
            home, old, new, case=case, by=by, now=now,
            expect_sha=expect_sha, veto_statement=veto_statement,
        )
    except _Refused as refused:
        return _refused_rename(old, new, refused)
    except gitops.GitOpsError as exc:
        return RenameResult(old=old, new=new, ok=False, kind=KIND_GIT, problems=(str(exc),))
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        result = _rename_locked(
            home, old, new, plan.root, case=case, by=by, now=now,
            expect_sha=expect_sha, veto_statement=veto_statement,
        )
    except (gitops.GitOpsError, SkillRegistryError) as exc:
        return RenameResult(old=old, new=new, ok=False, kind=KIND_GIT, problems=(str(exc),))
    finally:
        hold.release()
    host_sha = result.settle_sha or result.host_sha
    ledger_sha = result.ledger_shas[-1] if result.ledger_shas else None
    if no_push or not (ledger_sha or host_sha):
        return result
    ledger_push, host_push = _push(home, plan.root, ledger_sha, host_sha)
    return _with_pushes(result, ledger_push, host_push)

