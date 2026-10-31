"""``skill write`` and ``skill retire``: self-learn deploys and removes the
skills it owns (SK1, S-NEXT-sk1-writer; skill-writing plan §2 steps 5 and 8,
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
   never change after the skill is made -- plus exactly one managed
   section at the end: the deployed file's own section carried over byte
   for byte, or an empty one for a new skill), ``references/*.md`` (the
   draft's set replaces the deployed set), ``.claude-plugin/plugin.json``,
   and the marketplace entry, each written only when its bytes change --
   one skills-root commit, or none;
3. the link ``~/.claude/skills/<name>`` -> ``plugins/<name>/skills/<name>``
   (:func:`link_skill`), made only once the folder exists.

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

Every ledger write goes through :func:`skill_registry.with_update`; every
skills-root write happens inside ``gitops.host_lock`` in a named function
called from the locked block (``tests/test_lock_invariant.py``).
"""

from __future__ import annotations

import io
import json
import os
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
from .compilers import BEGIN_MARKER, END_MARKER, CompileError, _find_leading_block
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
    _read_frontmatter,
    check_skill,
    plugin_manifest_text,
)

__all__ = [
    "BY_VALUES",
    "KIND_BAD_LINE",
    "KIND_DESTINATION_UNAVAILABLE",
    "KIND_GIT",
    "KIND_NEEDS_PERSON",
    "KIND_TARGET_BUSY",
    "MAX_DRAFT_FILE_BYTES",
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


def deployed_authored_sha256(home: Path | str, name: str) -> str | None:
    """The authored sha256 of the deployed files (what ``expect_sha`` is
    compared with), or ``None`` when none are deployed."""
    files = deployed_files(home, name)
    return None if files is None else _authored_sha(files)


def draft_view(files: Mapping[str, str]) -> dict[str, str]:
    """A deployed skill's files as a draft the overseer can edit and hand
    back: SKILL.md without the runner's stamp and without the managed
    section, plus the ``references/*.md`` files. Other files are left out
    (a draft may not carry them; :func:`write` leaves them where they are)."""
    out: dict[str, str] = {}
    for key, value in files.items():
        if key == SKILL_ENTRY_FILE:
            text = _unstamped(value)
            out[key] = _without_section(text).rstrip() + "\n"
        elif _is_managed_reference(key):
            out[key] = value
    return out


def _is_managed_reference(key: str) -> bool:
    """``references/<file>.md``, one level deep: the support files a write
    replaces. Anything else in the folder is left alone."""
    parts = key.split("/")
    return (
        len(parts) == 2
        and parts[0] == SKILL_REFERENCES_DIR
        and parts[1].endswith(SKILL_SUPPORT_FILE_SUFFIX)
    )


# --------------------------------------------------------- routed lessons


def routed_lessons(home: Path | str, name: str) -> list[str]:
    """The ids of every ROUTED lesson whose compiled line lands in the
    skill's folder: a ``new-skill`` or ``skill-md`` route whose target is
    the skill's SKILL.md (the compiler's own resolution,
    ``verbs.managed_target_for``), and a ``reference`` route filed in the
    ``skills/<name>`` bucket. A retire is refused while this is not empty."""
    return sorted({record_id for record_id, _destination in _routed(Path(home), name)})


def _routed(home: Path, name: str) -> list[tuple[str, str]]:
    """``(lesson id, destination)`` for every lesson :func:`routed_lessons`
    counts."""
    from . import ledger_ops, verbs  # local: verbs imports a great deal
    from .ledger import discover_buckets
    from .records import Record

    root = _skills_root_or_none(home)
    if root is None or not _valid_name(name):
        return []
    target = (skill_dir(root, name) / SKILL_ENTRY_FILE).resolve()
    found: list[tuple[str, str]] = []
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
            destination = (record.routing or {}).get("destination")
            if destination in ("skill-md", "new-skill"):
                hit = verbs.managed_target_for(home, bucket, record) == target
            else:
                hit = destination == "reference" and bucket.scope == "skill" and bucket.name == name
            if hit:
                seen.add(record.id)
                found.append((record.id, str(destination)))
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


def _without_section(text: str) -> str:
    """*text* with its managed section and everything after it taken out
    (the template check already refused text after the section)."""
    for marker in (BEGIN_MARKER, SKILL_MANAGED_BEGIN_PREFIX):
        if marker in text:
            return text[: text.index(marker)].rstrip()
    return text.rstrip()


def _with_section(authored: str, section: str | None) -> str:
    """The deployed SKILL.md: the authored text, one blank line, the
    section (an empty marker pair when *section* is ``None``) last."""
    if section is None:
        section = f"{BEGIN_MARKER}\n{END_MARKER}"
    return f"{authored.rstrip()}\n\n{section}\n"


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


def _loaded_names(home: Path, *, leaving_out: str | None) -> tuple[set[str], list[str]]:
    """Every name a skill or command is loaded under on this machine, both
    as listed (``plugin:skill``) and as its last part (``skill``), all
    case-folded; with *leaving_out*'s own entries left out when updating.
    Also returns the catalogue's problems, as notes."""
    from .overseer import catalogue  # local: the catalogue imports report, hosts, ...

    machine = catalogue.skills_on_machine(
        home,
        placed=catalogue.PlacedLessons(surfaces={}, unlisted=(), unreadable=()),
    )
    names: set[str] = set()
    for entry in machine.skills:
        full = entry.name.casefold()
        bare = full.rsplit(":", 1)[-1]
        if leaving_out is not None and bare == leaving_out.casefold():
            continue
        names.update((full, bare))
    for entry in machine.not_loaded:
        bare = entry["name"].casefold().rsplit(":", 1)[-1]
        if leaving_out is None or bare != leaving_out.casefold():
            names.add(bare)
    return names, list(machine.problems)


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
    loaded, catalogue_problems = _loaded_names(home, leaving_out=name if updating else None)
    plan.notes += [f"skills on this machine: {p}" for p in catalogue_problems]
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
        plan.current_sha = _authored_sha(deployed)
    section = _section_of(deployed_md) if deployed_md is not None else None
    authored = _stamped(_without_section(draft[SKILL_ENTRY_FILE]) + "\n", plan.stamp)
    new_md = _with_section(authored, section)
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
    plan.new_sha = _authored_sha(after)

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

    # -- lessons filed as references in the skill's own bucket: their
    # blocks live in references/*.md, which a write replaces
    touches_references = bool(plan.removals) or any(
        p.is_relative_to(folder) and _is_managed_reference(p.relative_to(folder).as_posix())
        for p in plan.changed_writes()
    )
    if touches_references:
        reference_lessons = [
            rid for rid, destination in _routed(home, name) if destination == "reference"
        ]
        if reference_lessons:
            raise _Refused(
                KIND_NEEDS_PERSON,
                [
                    f"{name}'s references hold lessons routed there as references "
                    f"({', '.join(reference_lessons)}); a write would change those files, so "
                    "a person must move the lessons first"
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
    files: Mapping[str, str],
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
    files: Mapping[str, str],
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
    files: Mapping[str, str],
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
    snapshot = _snapshot([*plan.removals, plan.root / _MARKETPLACE_REL])
    unlinked = _drop_link(link_path(name), skill_dir(plan.root, name))
    try:
        host_sha = _remove_plugin(plan, subject, f"By: {by}")
    except (gitops.GitOpsError, OSError) as exc:
        undone = _undo_remove(plan, snapshot, unlinked)
        return RetireResult(
            name=name, ok=False, kind=KIND_GIT,
            problems=(f"the skills-root removal failed ({exc}); {undone}",),
        )
    ledger_sha = skill_registry.with_update(
        home, partial(_registry_after_retire, name=name, case=case, by=by, now=now), subject=subject
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

