"""The catalogue the overseer's skill-discovery step reads (K3a).

Two read-only views of what self-learn has placed and what Claude Code loads
on this machine. Each is data first, then a renderer over the data:

1. **Placed lessons, by delivery surface** (:func:`placed_lessons`,
   :func:`render_surface`). For each surface a lesson is loaded from -- the
   user ``CLAUDE.md``, each project's ``CLAUDE.md`` / ``CLAUDE.local.md``, each
   rules file, each skill's ``SKILL.md``, each reference shelf -- every ROUTED
   lesson placed there, with the line exactly as the compiler writes it, its
   word count, its fires in the window, who placed it, and its age. A
   surface is a FILE: lessons are grouped on the resolved file the compiler
   writes them into, whatever scope or route reached it. One markdown text
   per surface, under a stable, filesystem-safe key derived from the file.
2. **Skills on this machine** (:func:`skills_on_machine`,
   :func:`render_skills_index`): every skill Claude Code loads here, with its
   description, where it lives, and how many routed lessons are compiled into
   it. A dict ready to dump as ``skills-index.yaml``.

:func:`build_catalogue` runs both and returns what a later unit stages
(``catalogue/<surface key>.md`` and ``skills-index.yaml``).

Read-only, by construction: this module opens files for reading only, runs no
``git`` command, flushes no telemetry spool, and creates no directory and no
cache file. It calls no model.

Where it differs from the skills index ``report.py`` builds
(``_skill_description_row``): that row reads ``~/.claude/skills`` only, off an
environment variable rather than a parameter, and keeps word counts, not
description text or paths. This module reuses its description extractor
(:func:`self_learn.report._extract_skill_description`) and its de-duplication
on the resolved ``SKILL.md`` path, and adds the kinds of skill that row
cannot see: synced skills, enabled and synced plugins' skills and commands,
personal commands, registered hosts' ``.claude/skills``, and the skills built
into Claude Code (a hand-kept list, :data:`BUILT_IN_SKILLS`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import domain, hosts as hosts_mod, reachability, telemetry
from ..compilers import _iso, _reference_block, entry_line
from ..ledger import Bucket, discover_buckets
from ..ledger_ops import UNREADABLE_RECORD_ERRORS, bucket_project_path
from ..primitives import chrono
from ..records import Record
from .health import _replacement_successors, credit_replacement_chains

# ============================================================== THE KNOBS ==
# Everything the discovery step's view of the machine depends on is in this
# block. The overseer's skill-discovery step reads what these produce:
# change a value here and the next catalogue changes with it; nothing else in
# this module holds a copy. (Each is read when a function RUNS, never bound
# as a default argument, so a test or a later unit can override one.)

#: How far back a fire counts, in days. The overseer's health checks use 30
#: too (``health._FIRE_WINDOW_DAYS``); this copy is separate on purpose, so
#: discovery's window can change without moving the health row.
FIRE_WINDOW_DAYS = 30

#: Record statuses that count as "placed". A record is also left out when
#: ``superseded_by`` is set (``domain.is_canon_live`` is the compiler's own
#: test for "still the current canon"; this set is the knob for the status
#: half of it). Pending, deferred, rejected and superseded lessons are not
#: placed anywhere, so they are not listed.
PLACED_STATUSES: frozenset[str] = frozenset({"routed"})

#: The per-lesson numbers shown under each line, in order: ``(attribute of
#: PlacedLesson, label)``. The label may use ``{window}`` for the fire window.
#: Valid attributes: ``words``, ``fires``, ``placed_by``, ``age_days``. The
#: lesson's id and its line are always shown.
LESSON_COLUMNS: tuple[tuple[str, str], ...] = (
    ("words", "words"),
    ("fires", "fires in the last {window} days"),
    ("placed_by", "placed by"),
    ("age_days", "age in days"),
)

#: The fields of each skill in ``skills-index.yaml``, in order. A field whose
#: value is empty (``None``, or an empty list) is left out, except
#: ``description``, which is written as null when a skill has none that can
#: be read. Valid fields are the attributes of :class:`SkillEntry`.
SKILL_FIELDS: tuple[str, ...] = (
    "name",
    "kind",
    "description",
    "where",
    "path",
    "resolves_to",
    "repo",
    "plugin",
    "host",
    "lessons",
    "also",
)

#: What an entry is (the ``kind`` field). Claude Code lists all three as
#: skills in a session: a skill folder, a slash command file, and a skill
#: built into Claude Code itself.
KIND_ENTRY_SKILL = "skill"  # a folder holding SKILL.md
KIND_ENTRY_COMMAND = "command"  # a commands/<name>.md file
KIND_ENTRY_BUILT_IN = "built-in"  # in Claude Code, nothing on disk

#: Where an entry lives (the ``where`` field).
WHERE_PERSONAL = "personal"  # ~/.claude/skills/<name> (a folder or a symlink), ~/.claude/commands
WHERE_SYNCED = "synced"  # ~/.claude/skills/synced/<id>/<name>
WHERE_PLUGIN = "plugin"  # <enabled plugin>/skills/<name>, <enabled plugin>/commands/<name>.md
WHERE_SYNCED_PLUGIN = "synced-plugin"  # ~/.claude/plugins/synced/<id>/<plugin>/...
WHERE_HOST = "host"  # <registered host>/.claude/skills/<name>
WHERE_BUILT_IN = "claude-code"  # built into Claude Code

#: The name prefix of a synced skill (``~/.claude/skills/synced/<id>/<name>``).
#: Its ``manifest.json`` carries no namespace field (its entries name
#: ``skillId``, ``name``, ``description``, ``source``; two different
#: ``source`` values, ``anthropic`` and ``anthropic-example``, are listed under
#: the same prefix). The prefix is Claude Code's own constant: in the 2.1.293
#: binary, ``function $Te(n){return n.startsWith("anthropic-skills:")?n:
#: `anthropic-skills:${n}`}`` names every synced skill, and a warning there
#: says synced skills "answer only to anthropic-skills:<name>" when their bare
#: names cannot be checked. The session listing of 2026-10-08 names all 11
#: synced skills this way.
SYNCED_SKILL_NAMESPACE = "anthropic-skills"

#: Skills built into Claude Code: no file on this machine names them, so
#: they are kept here by hand. Source: the skills a Claude Code 2.1.293
#: session listed on 2026-10-08 (the gate's ``session_skills.txt``), minus
#: every name this module finds on disk. REFRESH BY HAND when Claude Code
#: changes; nothing checks this list against a newer version. (Claude Code
#: has a ``CLAUDE_CODE_DISABLE_BUNDLED_SKILLS`` switch; when it is set these
#: are not loaded, and this list does not know.)
BUILT_IN_SKILLS: tuple[str, ...] = (
    "artifact-capabilities",
    "artifact-design",
    "artifact-diagramming",
    "claude-api",
    "claude-in-chrome",
    "code-review",
    "dataviz",
    "fewer-permission-prompts",
    "init",
    "keybindings-help",
    "loop",
    "plugin-authoring",
    "run",
    "schedule",
    "security-review",
    "simplify",
    "update-config",
    "workflow-authoring",
)

#: Surface keys. A key is a readable label taken from the surface's file
#: plus a digest of that file's resolved path, so one file is one key and two
#: files never share one. ``KEY_MAX`` is the longest key; the label is cut to
#: fit. ``KEY_DIGEST_CHARS`` is how many hex digits of the digest are kept.
KEY_MAX = 120
KEY_DIGEST_CHARS = 8

# ============================================================ end of knobs ==

#: Surface kinds (:attr:`Surface.kind`), in the order a surface reached by
#: routes of more than one kind takes its kind from.
KIND_CLAUDE_MD = "claude-md"
KIND_CLAUDE_LOCAL = "claude-local"
KIND_RULES = "rules"
KIND_SKILL = "skill"
KIND_REFERENCE = "reference"
_KIND_ORDER = (KIND_CLAUDE_MD, KIND_CLAUDE_LOCAL, KIND_RULES, KIND_SKILL, KIND_REFERENCE)

_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


# ================================================================== data ====


@dataclass(frozen=True)
class PlacedLesson:
    """One routed lesson on one surface."""

    id: str
    line: str  # as the compiler writes it (the reference block, on a shelf)
    words: int  # len(line.split()), the count compile_managed_text uses
    fires: int  # fires in the window, credited along replacement chains
    placed_by: str  # routing.by
    age_days: int  # days since the lesson was created


@dataclass(frozen=True)
class Surface:
    """One file lessons are loaded from, and the lessons placed there.

    A surface IS a file: every lesson whose route resolves to the same file
    is on the same surface, whatever scope or destination routed it there
    (a repo registered as both a project and the skills root has ONE
    ``CLAUDE.md``, holding both scopes' lines)."""

    key: str  # filesystem-safe and stable: the file name under catalogue/
    kind: str  # one of the KIND_* values
    title: str  # names the file's kind and every owner that reaches it
    loaded: str  # how it reaches a session, in a sentence
    target: Path  # the file the compiler writes (resolved)
    window_days: int  # the fire window the counts were taken over
    lessons: tuple[PlacedLesson, ...]
    #: Every scope and route that reaches this file, one line each, e.g.
    #: ``project host-repo-1a2b3c4d (claude-md)``.
    owners: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlacedLessons:
    surfaces: dict[str, Surface]
    #: Routed lessons that are on no listed surface, each as ``"<id>: <why>"``:
    #: a hook's lessons (a script, not a loaded line), and any lesson whose
    #: target file cannot be resolved (host not registered, no skills root).
    unlisted: tuple[str, ...]
    #: Record files in a ``resolved/`` directory that did not read back.
    unreadable: tuple[str, ...]


@dataclass(frozen=True)
class SkillEntry:
    #: As Claude Code names it in a session: ``<name>`` for a personal or
    #: host skill, ``plugin:skill`` / ``plugin:command`` for a plugin's,
    #: ``dir:command`` for a personal command in a folder, and
    #: ``anthropic-skills:<name>`` for a synced skill.
    name: str
    description: str | None  # None when no description could be read
    where: str  # WHERE_*
    #: The skill folder or the command file, as Claude Code finds it; None for
    #: a built-in skill, which has no file here.
    path: str | None
    kind: str = KIND_ENTRY_SKILL  # KIND_ENTRY_*
    resolves_to: str | None = None  # the real folder or file, when ``path`` goes through a symlink
    repo: str | None = None  # the registered skills root it lives in, by name
    plugin: str | None = None  # ``plugin@marketplace``, for a plugin's skill or command
    host: str | None = None  # the registered host, for a host skill
    lessons: int = 0  # routed lessons compiled into its SKILL.md
    also: tuple[str, ...] = ()  # other folders or files that reach the same file


@dataclass(frozen=True)
class SkillsOnMachine:
    skills: tuple[SkillEntry, ...]
    #: Entries switched off by ``skillOverrides`` in settings.json: ``name``,
    #: ``where`` and (unless built in) ``path``. Present, not loaded.
    not_loaded: tuple[dict[str, str], ...] = ()
    #: Things that could not be read, one sentence each.
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalogue:
    surfaces: dict[str, str]  # surface key -> markdown, staged as <key>.md
    skills_index: dict[str, Any]  # dumped as skills-index.yaml
    unlisted: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Place:
    """Where one lesson goes: the resolved file the compiler writes it into,
    the kind of that file, and who routed it there."""

    target: Path
    kind: str
    owner: str


@dataclass
class _Walk:
    """Working state of one ledger walk."""

    placed: list[tuple[_Place, Record]] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)


# ====================================================== placed lessons =====


def placed_lessons(
    home: Path | str,
    *,
    claude_dir: Path | str | None = None,
    now: datetime | None = None,
    window_days: int | None = None,
) -> PlacedLessons:
    """Every placed lesson in the ledger *home*, grouped by delivery surface.

    *claude_dir* is the ``~/.claude`` directory (default: the one every other
    ``~/.claude`` reader here uses, ``SELF_LEARN_CLAUDE_DIR`` or the real
    one); it fixes where the user ``CLAUDE.md`` and the user rules live.
    *now* and *window_days* default to the present and
    :data:`FIRE_WINDOW_DAYS`. A surface with no placed lesson is not listed.
    """
    ledger = Path(home)
    claude = _claude_dir(claude_dir)
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    window = FIRE_WINDOW_DAYS if window_days is None else window_days

    walk = _walk_ledger(ledger, claude)
    fires = _fires_by_record(ledger, moment, window)

    # One surface per FILE: group on the resolved file the compiler writes.
    grouped: dict[Path, list[tuple[_Place, Record]]] = {}
    for place, record in walk.placed:
        grouped.setdefault(place.target, []).append((place, record))

    user_claude_md = _resolved(claude / "CLAUDE.md")
    surfaces: dict[str, Surface] = {}
    for target in sorted(grouped, key=str):
        # Sort first; everything below is chosen from the sorted group, so
        # nothing depends on the order the ledger walk met the lessons in.
        members = sorted(grouped[target], key=_placement_order)
        kind = min((place.kind for place, _ in members), key=_KIND_ORDER.index)
        owners = tuple(sorted({place.owner for place, _ in members}))
        label = _readable_label(kind, target, claude)
        key = _surface_key(label, target)
        if key in surfaces:  # a digest collision: the full digest keeps them apart
            key = _surface_key(label, target, digest_chars=64)
        surfaces[key] = Surface(
            key=key,
            kind=kind,
            title=f"{_file_label(kind, target)}, reached by {'; '.join(owners)}",
            loaded=_loaded(kind, target, user_claude_md),
            target=target,
            window_days=window,
            lessons=tuple(
                _lesson_row(place, record, fires, moment) for place, record in members
            ),
            owners=owners,
        )
    return PlacedLessons(
        surfaces=dict(sorted(surfaces.items())),
        unlisted=tuple(sorted(walk.unlisted)),
        unreadable=tuple(sorted(walk.unreadable)),
    )


def _placement_order(member: tuple[_Place, Record]) -> tuple[str, str]:
    """Oldest routing first, then id: the order the compiler writes a section
    in."""
    record = member[1]
    return (_iso((record.routing or {}).get("routed_at") or ""), record.id)


def _claude_dir(claude_dir: Path | str | None) -> Path:
    if claude_dir is not None:
        return Path(claude_dir)
    from ..selfcheck import claude_runtime_dir

    return claude_runtime_dir()


def _is_placed(record: Record) -> bool:
    return record.status in PLACED_STATUSES and record.superseded_by is None


def _walk_ledger(home: Path, claude_dir: Path) -> _Walk:
    """Read every ``resolved/`` record once; place the ones that are placed."""
    walk = _Walk()
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except UNREADABLE_RECORD_ERRORS:
                walk.unreadable.append(f"{bucket.scope}/{bucket.name}/{path.name}")
                continue
            if not _is_placed(record):
                continue
            place, why = _place(home, bucket, record, claude_dir)
            if place is None:
                walk.unlisted.append(f"{record.id}: {why}")
            else:
                walk.placed.append((place, record))
    return walk


def _lesson_row(
    place: _Place, record: Record, fires: Counter[str], now: datetime
) -> PlacedLesson:
    line = _reference_block(record) if place.kind == KIND_REFERENCE else entry_line(record)
    return PlacedLesson(
        id=record.id,
        line=line,
        words=len(line.split()),
        fires=fires[record.id],
        placed_by=str((record.routing or {}).get("by") or ""),
        age_days=domain.record_age_days(record, now),
    )


# -------------------------------------------------- where a lesson goes ----


def _place(
    home: Path, bucket: Bucket, record: Record, claude_dir: Path
) -> tuple[_Place | None, str]:
    """The file *record* is loaded from, or ``(None, why)``.

    The file is the compiler's own answer, never a second derivation: for a
    managed section (``claude-md``, ``skill-md``, ``new-skill``)
    :func:`self_learn.verbs.managed_target_for`, the resolution
    ``recompile`` groups its compile sets on; for a reference shelf
    :func:`self_learn.selfcheck._reference_target_for`, the same
    skill-``references/`` or project-``references/`` resolution the route
    and recompile use. The user ``CLAUDE.md`` is always passed in: left to
    default, that resolution reads the real ``~/.claude``.
    """
    from .. import verbs
    from ..selfcheck import _reference_target_for

    routing = record.routing or {}
    destination = routing.get("destination")

    if destination == "hook":
        return None, "routed to a hook (a script, not a loaded line)"
    if destination == "reference":
        target = _reference_target_for(home, bucket, record)
        if target is None:
            why = (
                "user scope has no shelf"
                if bucket.scope == "user"
                else "its host is not registered, or its skill is missing or ambiguous"
            )
            return None, f"the reference shelf cannot be resolved ({why})"
        return _Place(_resolved(target), KIND_REFERENCE, _owner(bucket, routing)), ""
    if destination not in ("claude-md", "skill-md", "new-skill"):
        return None, f"destination {destination!r} loads no text"

    try:
        target = verbs.managed_target_for(
            home, bucket, record, user_claude_md=claude_dir / "CLAUDE.md"
        )
    except hosts_mod.HostsError as exc:
        return None, f"the target file cannot be resolved ({exc})"
    if target is None:
        return None, f"the target file cannot be resolved (destination {destination})"
    if destination in ("skill-md", "new-skill"):
        kind = KIND_SKILL
    elif routing.get("variant") == "rules":
        kind = KIND_RULES
    elif routing.get("variant") == "local":
        kind = KIND_CLAUDE_LOCAL
    else:
        kind = KIND_CLAUDE_MD
    return _Place(_resolved(target), kind, _owner(bucket, routing)), ""


def _owner(bucket: Bucket, routing: dict[str, Any]) -> str:
    """Who reaches a file: the lesson's bucket and its route, e.g.
    ``project host-repo-1a2b3c4d (claude-md)`` or ``skill s (skill-md)``."""
    if bucket.scope == "user":
        scope = "user"
    elif bucket.scope == "project":
        scope = f"project {_project_label(bucket)}"
    else:
        scope = f"skill {bucket.name}"
    destination = str(routing.get("destination"))
    if destination == "new-skill":
        route = f"new-skill {routing.get('new_skill')}"
    elif destination == "claude-md" and routing.get("variant") == "rules":
        route = f"claude-md, rules topic {routing.get('rules_topic')}"
    elif destination == "claude-md" and routing.get("variant") == "local":
        route = "claude-md, local"
    else:
        route = destination
    return f"{scope} ({route})"


def _project_label(bucket: Bucket) -> str:
    """A project bucket's short name: the project folder's name and the
    bucket's own digest (the last eight characters of its slug, which keeps
    two projects with the same folder name apart)."""
    path = bucket_project_path(bucket.path)
    if path is None or not path.name:
        return bucket.name
    return f"{path.name}-{bucket.name[-8:]}"


# --------------------------------------------------- what a surface says ---


def _file_label(kind: str, target: Path) -> str:
    if kind == KIND_SKILL:
        return f"Skill {target.parent.name}: SKILL.md"
    if kind == KIND_REFERENCE:
        return f"Reference shelf {target.name}"
    if kind == KIND_RULES:
        return f"Rule file {target.stem}"
    return target.name  # CLAUDE.md or CLAUDE.local.md


def _loaded(kind: str, target: Path, user_claude_md: Path) -> str:
    """How a surface reaches a session, in a sentence."""
    if kind == KIND_SKILL:
        return "when Claude invokes the skill (only its description is in every session)"
    if kind == KIND_REFERENCE:
        return "only when read; the SKILL.md or CLAUDE.md carries a pointer to it"
    if kind == KIND_RULES:
        return (
            "when a file matching the rule file's paths is read "
            "(a rule file with no paths loads every session)"
        )
    if kind == KIND_CLAUDE_MD and target == user_claude_md:
        return "every session, in every project"
    return "every session started in that repository"


# ---------------------------------------------------------- surface keys ---


def _readable_label(kind: str, target: Path, claude_dir: Path) -> str:
    """The readable half of a surface key, taken from the FILE (its kind,
    its name and the folders around it) and never from the lessons on it, so
    it cannot change when the lessons do. It need not be unique: the key's
    digest is."""
    if kind == KIND_SKILL:
        return f"skill-{target.parent.name}"
    shelf_or_stem = target.stem if target.suffix == ".md" else target.name
    if kind == KIND_REFERENCE:
        refs_owner = target.parent.parent
        if refs_owner.parent.name == "skills":  # <...>/skills/<name>/references/<file>
            return f"skill-{refs_owner.name}-reference-{shelf_or_stem}"
        return f"{refs_owner.name}-reference-{shelf_or_stem}"
    if kind == KIND_RULES:
        # <claude dir>/rules/<topic>.md or <host>/.claude/rules/<topic>.md;
        # a topic may hold a "/", so the rules folder is looked for upward.
        user_rules = _resolved(claude_dir / "rules")
        if user_rules in target.parents:
            owner, topic = "user", target.relative_to(user_rules)
        else:
            rules_dir = next(
                (p for p in target.parents if p.name == "rules" and p.parent.name == ".claude"),
                target.parent,
            )
            owner, topic = rules_dir.parent.parent.name, target.relative_to(rules_dir)
        topic_text = str(topic.with_suffix("") if topic.suffix == ".md" else topic)
        return f"{owner}-rules-{topic_text}"
    user_file = _resolved(claude_dir / target.name) == target
    owner = "user" if user_file else target.parent.name
    return f"{owner}-claude-local-md" if kind == KIND_CLAUDE_LOCAL else f"{owner}-claude-md"


def _surface_key(label: str, target: Path, *, digest_chars: int | None = None) -> str:
    """A filesystem-safe, stable key for the surface whose file is *target*:
    the *label* with each run of characters outside ``A-Za-z0-9._-`` turned
    into ``-``, cut to fit :data:`KEY_MAX`, then ``-`` and a digest of the
    resolved file path. The key depends on the file alone, so it does not
    change when another surface appears, and two files never share one."""
    chars = KEY_DIGEST_CHARS if digest_chars is None else digest_chars
    digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:chars]
    text = _UNSAFE_KEY_CHARS.sub("-", label).strip("-.") or "surface"
    text = text[: max(1, KEY_MAX - len(digest) - 1)].rstrip("-.") or "surface"
    return f"{text}-{digest}"


# ----------------------------------------------------------------- fires ---


def _fires_by_record(home: Path, now: datetime, window_days: int) -> Counter[str]:
    """Fires per record id in the window, with chain credit.

    A fire on a lesson that was replaced counts toward every lesson after it
    in the replacement chain (:func:`health.credit_replacement_chains`, the
    overseer's own rule), so a rewrite keeps the fires of the lesson it
    replaced. That function answers with a set, so it is asked once for each
    fired id that has a successor; an id with none is its own chain.
    Each such question reads the ledger's resolved records again.
    """
    since = now - timedelta(days=window_days)
    own: Counter[str] = Counter()
    for event in telemetry.read_events(home):
        record_id = event.get("record")
        if event.get("kind") != "fire" or not isinstance(record_id, str):
            continue
        when = chrono.to_dt(event.get("ts"))
        if when is not None and when >= since:
            own[record_id] += 1

    credited: Counter[str] = Counter(own)
    successors = _replacement_successors(home) if own else {}
    for record_id, count in own.items():
        if record_id not in successors:
            continue
        for downstream in credit_replacement_chains(home, {record_id}) - {record_id}:
            credited[downstream] += count
    return credited


# =============================================================== render ====


def render_surface(surface: Surface) -> str:
    """One surface as markdown. Each lesson is its line exactly as compiled,
    with its numbers on the line beneath."""
    window = surface.window_days
    words = sum(lesson.words for lesson in surface.lessons)
    out = [
        f"# {surface.key}",
        "",
        surface.title,
        "",
        f"- Loaded: {surface.loaded}",
        f"- File: {surface.target}",
        f"- Lessons: {len(surface.lessons)} · words: {words} · fires counted over the last {window} days",
        "",
    ]
    for lesson in surface.lessons:
        if "\n" in lesson.line:
            out.extend(f"> {text}".rstrip() for text in lesson.line.split("\n"))
            out.append("")
        else:
            out.append(lesson.line)
        numbers = " · ".join(
            f"{label.format(window=window)}: {getattr(lesson, attribute)}"
            for attribute, label in LESSON_COLUMNS
        )
        out.append(f"  - {numbers}")
    return "\n".join(out) + "\n"


def render_surfaces(placed: PlacedLessons) -> dict[str, str]:
    """``{surface key: markdown}``, in key order."""
    return {key: render_surface(placed.surfaces[key]) for key in sorted(placed.surfaces)}


# ========================================================= skills index ====


def skills_on_machine(
    home: Path | str,
    *,
    claude_dir: Path | str | None = None,
    placed: PlacedLessons | None = None,
) -> SkillsOnMachine:
    """Every skill Claude Code loads on this machine, named as a session
    lists it.

    Seven places, in this order:

    1. personal skills, ``<claude_dir>/skills/*`` (folders and symlinks);
    2. synced skills, ``<claude_dir>/skills/synced/<id>/<name>``, named
       ``anthropic-skills:<name>`` (:data:`SYNCED_SKILL_NAMESPACE`);
    3. each enabled plugin's ``skills/*`` and ``commands/*.md``;
    4. each synced plugin's (``<claude_dir>/plugins/synced/<id>/<plugin>``)
       ``skills/*`` and ``commands/*.md``;
    5. personal commands, ``<claude_dir>/commands/<name>.md`` and
       ``<claude_dir>/commands/<dir>/<name>.md`` (named ``<dir>:<name>``);
    6. each registered host's ``.claude/skills/*``;
    7. the skills built into Claude Code (:data:`BUILT_IN_SKILLS`).

    A synced skill or plugin is read off its folder's ``manifest.json``: only
    the folder the manifest names is loaded, which for an entry with a
    ``generation`` above 1 is ``<name>~g<generation>`` (Claude Code 2.1.293,
    ``function Jno(e,n,i){...return n<=1?r:p(i,`${L(r)}~g${n}`)}``); an older
    generation's folder left beside it is not listed.

    A file reached from more than one place is listed once, under the first,
    with the others in ``also`` (de-duplicated on the resolved file, as
    report.py does for ``SKILL.md``). An entry switched off in settings.json
    is listed in ``not_loaded`` instead. *placed* is the result of
    :func:`placed_lessons`, used for the lesson counts; it is computed when
    not given.
    """
    from ..report import _extract_skill_description

    ledger = Path(home)
    claude = _claude_dir(claude_dir)
    if placed is None:
        placed = placed_lessons(ledger, claude_dir=claude)
    lesson_counts = _lessons_by_skill_file(placed)
    problems: list[str] = []
    instrument = reachability.read_instrument(claude)
    if instrument.problem:
        problems.append(instrument.problem)

    registry: hosts_mod.Hosts | None = None
    try:
        registry = hosts_mod.load_hosts(ledger)
    except hosts_mod.HostsError as exc:
        problems.append(f"hosts.yaml could not be read: {exc}")
    skills_root = _resolved(registry.skills_root) if registry and registry.skills_root else None

    found: dict[Path, SkillEntry] = {}
    not_loaded: list[dict[str, str]] = []

    def listing(directory: Path) -> list[Path]:
        if not directory.is_dir():
            return []
        try:
            return sorted(directory.iterdir())
        except OSError as exc:
            problems.append(f"{directory} could not be listed: {exc}")
            return []

    def add(entry_file: Path, listed: Path, name: str, where: str, kind: str, **extra: str | None) -> None:
        """*entry_file* is the SKILL.md or the command file; *listed* is the
        path the entry is listed under (the skill folder, or the command
        file)."""
        if not entry_file.is_file():
            return
        real = _resolved(entry_file)
        if real in found:
            known = found[real]
            if str(listed) != known.path and str(listed) not in known.also:
                found[real] = replace(known, also=known.also + (str(listed),))
            return
        if instrument.skill_overrides.get(name) == "off":
            not_loaded.append({"name": name, "where": where, "path": str(listed)})
            return
        try:
            description, _tier = _extract_skill_description(entry_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            description = None
        real_listed = real.parent if kind == KIND_ENTRY_SKILL else real
        in_root = skills_root is not None and (
            real_listed == skills_root or skills_root in real_listed.parents
        )
        found[real] = SkillEntry(
            name=name,
            description=description.strip() if isinstance(description, str) else None,
            where=where,
            path=str(listed),
            kind=kind,
            resolves_to=str(real_listed) if real_listed != listed.absolute() else None,
            repo=skills_root.name if in_root and skills_root is not None else None,
            plugin=extra.get("plugin"),
            host=extra.get("host"),
            lessons=lesson_counts.get(real, 0),
        )

    def add_plugin(root: Path, plugin_name: str, key: str, where: str) -> None:
        for folder in listing(root / "skills"):
            add(folder / "SKILL.md", folder, f"{plugin_name}:{folder.name}", where,
                KIND_ENTRY_SKILL, plugin=key)
        for file in listing(root / "commands"):
            if file.suffix == ".md":
                add(file, file, f"{plugin_name}:{file.stem}", where, KIND_ENTRY_COMMAND, plugin=key)

    # 1. personal skills: <claude_dir>/skills/*
    for folder in listing(claude / "skills"):
        add(folder / "SKILL.md", folder, folder.name, WHERE_PERSONAL, KIND_ENTRY_SKILL)

    # 2. synced skills: <claude_dir>/skills/synced/<id>/<name>
    for folder, item in _synced_entries(claude / "skills" / "synced", "skills", problems):
        if not (folder / "SKILL.md").is_file():
            problems.append(f"synced skill {item['name']}: no SKILL.md at {folder}")
            continue
        add(folder / "SKILL.md", folder, f"{SYNCED_SKILL_NAMESPACE}:{item['name']}",
            WHERE_SYNCED, KIND_ENTRY_SKILL)

    # 3. enabled plugins
    installed = _installed_plugin_roots(claude)
    for key, enabled in sorted(instrument.enabled_plugins.items()):
        if not enabled:
            continue
        plugin_name, _sep, marketplace = key.partition("@")
        roots = installed.get(key)
        if not roots:
            fallback = reachability._resolve_plugin_root(instrument, plugin_name, marketplace)
            roots = [fallback] if fallback is not None else []
        roots = [root for root in roots if root.is_dir()]
        if not roots:
            problems.append(f"enabled plugin {key}: its folder could not be found")
            continue
        for root in roots:
            add_plugin(root, plugin_name, key, WHERE_PLUGIN)

    # 4. synced plugins: <claude_dir>/plugins/synced/<id>/<plugin>
    for root, item in _synced_entries(claude / "plugins" / "synced", "plugins", problems):
        if not root.is_dir():
            problems.append(f"synced plugin {item['name']}: no folder at {root}")
            continue
        marketplace = item.get("marketplaceName")
        key = f"{item['name']}@{marketplace}" if isinstance(marketplace, str) and marketplace else item["name"]
        add_plugin(root, item["name"], key, WHERE_SYNCED_PLUGIN)

    # 5. personal commands: <claude_dir>/commands/<name>.md, .../<dir>/<name>.md
    for entry in listing(claude / "commands"):
        if entry.is_dir():
            for file in listing(entry):
                if file.suffix == ".md":
                    add(file, file, f"{entry.name}:{file.stem}", WHERE_PERSONAL, KIND_ENTRY_COMMAND)
        elif entry.suffix == ".md":
            add(entry, entry, entry.stem, WHERE_PERSONAL, KIND_ENTRY_COMMAND)

    # 6. registered hosts' .claude/skills
    if registry is not None:
        # A repo registered as both a project and the skills root is one host.
        hosts: dict[Path, Path] = {}
        for host in [*registry.projects, *([registry.skills_root] if registry.skills_root else [])]:
            hosts.setdefault(_resolved(host), host)
        for host in hosts.values():
            for folder in listing(host / ".claude" / "skills"):
                add(folder / "SKILL.md", folder, folder.name, WHERE_HOST, KIND_ENTRY_SKILL,
                    host=str(host))

    # 7. built into Claude Code: names only, kept by hand
    built_in: list[SkillEntry] = []
    for name in BUILT_IN_SKILLS:
        if instrument.skill_overrides.get(name) == "off":
            not_loaded.append({"name": name, "where": WHERE_BUILT_IN})
            continue
        built_in.append(SkillEntry(
            name=name, description=None, where=WHERE_BUILT_IN, path=None, kind=KIND_ENTRY_BUILT_IN,
        ))

    skills = tuple(sorted([*found.values(), *built_in], key=lambda s: (s.name, s.path or "")))
    return SkillsOnMachine(
        skills=skills,
        not_loaded=tuple(sorted(not_loaded, key=lambda n: (n["name"], n.get("path", "")))),
        problems=tuple(problems),
    )


def _synced_entries(
    base: Path, list_key: str, problems: list[str]
) -> list[tuple[Path, dict[str, Any]]]:
    """``(folder, manifest entry)`` for each skill or plugin a synced
    folder's ``manifest.json`` lists (*list_key* is ``skills`` or
    ``plugins``), ``base/<id>/manifest.json`` for every ``<id>``. The folder
    is the one Claude Code loads: ``<name>``, or ``<name>~g<generation>``
    when the entry's ``generation`` is above 1. A name that is not one plain
    folder name is skipped."""
    if not base.is_dir():
        return []
    try:
        buckets = sorted(path for path in base.iterdir() if path.is_dir())
    except OSError as exc:
        problems.append(f"{base} could not be listed: {exc}")
        return []
    entries: list[tuple[Path, dict[str, Any]]] = []
    for bucket in buckets:
        manifest = bucket / "manifest.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{manifest} could not be read ({exc}); its {list_key} are not listed")
            continue
        items = data.get(list_key) if isinstance(data, dict) else None
        if not isinstance(items, list):
            problems.append(f"{manifest} has no {list_key} list; none are listed")
            continue
        for item in items:
            name = item.get("name") if isinstance(item, dict) else None
            if not isinstance(name, str) or not name or "/" in name or name in (".", ".."):
                continue
            generation = item.get("generation")
            if isinstance(generation, int) and not isinstance(generation, bool) and generation > 1:
                folder = bucket / f"{name}~g{generation}"
            else:
                folder = bucket / name
            entries.append((folder, item))
    return entries


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _lessons_by_skill_file(placed: PlacedLessons) -> Counter[Path]:
    """Routed lessons compiled into each ``SKILL.md``, by resolved path."""
    counts: Counter[Path] = Counter()
    for surface in placed.surfaces.values():
        if surface.kind == KIND_SKILL:
            counts[_resolved(surface.target)] += len(surface.lessons)
    return counts


def _installed_plugin_roots(claude_dir: Path) -> dict[str, list[Path]]:
    """``{plugin@marketplace: [install folders]}`` from Claude Code's own
    ``plugins/installed_plugins.json``. Most marketplace entries name their
    source as a repository, not a folder, so the install folder is the
    reliable route to a plugin's files."""
    path = claude_dir / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return {}
    roots: dict[str, list[Path]] = {}
    for key, installs in plugins.items():
        if isinstance(installs, dict):
            installs = [installs]
        if not isinstance(key, str) or not isinstance(installs, list):
            continue
        for install in installs:
            location = install.get("installPath") if isinstance(install, dict) else None
            if isinstance(location, str) and location:
                roots.setdefault(key, []).append(Path(location))
    return roots


def render_skills_index(machine: SkillsOnMachine) -> dict[str, Any]:
    """The skills as a dict ready to dump as ``skills-index.yaml``: plain
    strings, numbers, lists and mappings only."""
    rows: list[dict[str, Any]] = []
    for skill in machine.skills:
        row: dict[str, Any] = {}
        for name in SKILL_FIELDS:
            value = getattr(skill, name)
            if isinstance(value, tuple):
                value = list(value)
            if name == "description" or value not in (None, [], ""):
                row[name] = value
        rows.append(row)
    where_counts = Counter(skill.where for skill in machine.skills)
    kind_counts = Counter(skill.kind for skill in machine.skills)
    return {
        "skills": rows,
        "counts": {
            "total": len(rows),
            "by_where": dict(sorted(where_counts.items())),
            "by_kind": dict(sorted(kind_counts.items())),
        },
        "not_loaded": [dict(item) for item in machine.not_loaded],
        "problems": list(machine.problems),
    }


# ============================================================== the whole ===


def build_catalogue(
    home: Path | str,
    *,
    claude_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Catalogue:
    """Both views, rendered. Writes nothing; the caller stages the result."""
    claude = _claude_dir(claude_dir)
    placed = placed_lessons(home, claude_dir=claude, now=now)
    machine = skills_on_machine(home, claude_dir=claude, placed=placed)
    return Catalogue(
        surfaces=render_surfaces(placed),
        skills_index=render_skills_index(machine),
        unlisted=placed.unlisted,
        unreadable=placed.unreadable,
    )
