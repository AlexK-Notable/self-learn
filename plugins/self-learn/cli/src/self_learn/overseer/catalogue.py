"""The catalogue the overseer's skill-discovery step reads (K3a).

Two read-only views of what self-learn has placed and what Claude Code loads
on this machine. Each is data first, then a renderer over the data:

1. **Placed lessons, by delivery surface** (:func:`placed_lessons`,
   :func:`render_surface`). For each surface a lesson is loaded from -- the
   user ``CLAUDE.md``, each project's ``CLAUDE.md`` / ``CLAUDE.local.md``, each
   rules file, each skill's ``SKILL.md``, each reference shelf -- every ROUTED
   lesson placed there, with the line exactly as the compiler writes it, its
   word count, its fires in the window, who placed it, and its age. One
   markdown text per surface, under a stable, filesystem-safe key.
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
on the resolved ``SKILL.md`` path, and adds the two kinds of skill that row
cannot see: enabled plugins' skills and registered hosts' ``.claude/skills``.
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
from ..compilers import _iso, _reference_block, entry_line, reference_target_path
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

#: Where a skill lives (the ``where`` field).
WHERE_PERSONAL = "personal"  # ~/.claude/skills/<name>, a folder or a symlink
WHERE_PLUGIN = "plugin"  # <enabled plugin>/skills/<name>
WHERE_HOST = "host"  # <registered host>/.claude/skills/<name>

# ============================================================ end of knobs ==

#: Surface kinds (:attr:`Surface.kind`).
KIND_CLAUDE_MD = "claude-md"
KIND_CLAUDE_LOCAL = "claude-local"
KIND_RULES = "rules"
KIND_SKILL = "skill"
KIND_REFERENCE = "reference"

#: Longest surface key kept whole; a longer one is cut and given a digest.
_KEY_MAX = 120
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
    """A place lessons are loaded from, and the lessons placed there."""

    key: str  # filesystem-safe and stable: the file name under catalogue/
    kind: str  # one of the KIND_* values
    title: str
    loaded: str  # how it reaches a session, in a sentence
    target: Path  # the file the compiler writes (resolved)
    window_days: int  # the fire window the counts were taken over
    lessons: tuple[PlacedLesson, ...]


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
    name: str  # as Claude Code names it; a plugin's skill is ``plugin:skill``
    description: str | None  # None when no description could be read
    where: str  # WHERE_*
    path: str  # the skill folder, as Claude Code finds it
    resolves_to: str | None = None  # the real folder, when ``path`` is a symlink
    repo: str | None = None  # the registered skills root it lives in, by name
    plugin: str | None = None  # ``plugin@marketplace``, for a plugin skill
    host: str | None = None  # the registered host, for a host skill
    lessons: int = 0  # routed lessons compiled into its SKILL.md
    also: tuple[str, ...] = ()  # other folders that reach the same SKILL.md


@dataclass(frozen=True)
class SkillsOnMachine:
    skills: tuple[SkillEntry, ...]
    #: Skills switched off by ``skillOverrides`` in settings.json: ``name`` and
    #: ``path``. Present on the machine, not loaded.
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
    """Where one lesson goes, before the keys are made filesystem-safe."""

    raw_key: str
    kind: str
    title: str
    loaded: str
    target: Path


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
    keys = {place.raw_key: _safe_key(place.raw_key) for place, _ in walk.placed}

    grouped: dict[str, list[tuple[_Place, Record]]] = {}
    for place, record in walk.placed:
        grouped.setdefault(keys[place.raw_key], []).append((place, record))

    surfaces: dict[str, Surface] = {}
    for key in sorted(grouped):
        members = grouped[key]
        first = members[0][0]
        members.sort(key=lambda m: (_iso((m[1].routing or {}).get("routed_at") or ""), m[1].id))
        surfaces[key] = Surface(
            key=key,
            kind=first.kind,
            title=first.title,
            loaded=first.loaded,
            target=first.target,
            window_days=window,
            lessons=tuple(
                _lesson_row(place, record, fires, moment) for place, record in members
            ),
        )
    return PlacedLessons(
        surfaces=surfaces,
        unlisted=tuple(sorted(walk.unlisted)),
        unreadable=tuple(sorted(walk.unreadable)),
    )


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
    """The surface *record* is loaded from, or ``(None, why)``.

    The target file comes from the compiler's own resolution
    (:func:`self_learn.verbs.managed_target_for`) so the catalogue and the
    compile can never disagree about where a lesson lands. The user
    ``CLAUDE.md`` is always passed in: left to default, that resolution reads
    the real ``~/.claude``.
    """
    from .. import verbs

    routing = record.routing or {}
    destination = routing.get("destination")
    variant = routing.get("variant")

    if destination == "hook":
        return None, "routed to a hook (a script, not a loaded line)"
    if destination == "reference":
        return _place_reference(home, bucket, record)
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
        name = bucket.name if destination == "skill-md" else str(routing.get("new_skill"))
        return (
            _Place(
                f"skill-{name}",
                KIND_SKILL,
                f"Skill {name}: SKILL.md",
                "when Claude invokes the skill (only its description is in every session)",
                target,
            ),
            "",
        )

    if variant == "rules":
        topic = str(routing.get("rules_topic"))
        owner, prefix = _owner(bucket, record)
        return (
            _Place(
                f"{prefix}-rules-{topic}",
                KIND_RULES,
                f"{owner} rule file {topic}",
                "when a file matching the rule file's paths is read "
                "(a rule file with no paths loads every session)",
                target,
            ),
            "",
        )
    if variant == "local":
        owner, prefix = _owner(bucket, record)
        return (
            _Place(
                f"{prefix}-claude-local-md",
                KIND_CLAUDE_LOCAL,
                f"{owner} CLAUDE.local.md",
                "every session in that project",
                target,
            ),
            "",
        )
    owner, prefix = _owner(bucket, record)
    if record.scope == "user":
        loaded = "every session, in every project"
    else:
        loaded = "every session in that project"
    return (
        _Place(f"{prefix}-claude-md", KIND_CLAUDE_MD, f"{owner} CLAUDE.md", loaded, target),
        "",
    )


def _owner(bucket: Bucket, record: Record) -> tuple[str, str]:
    """``(display name, key prefix)`` of the scope that owns a CLAUDE.md or
    rules surface."""
    if record.scope == "user":
        return "User", "user"
    if record.scope == "project":
        label = _project_label(bucket)
        return f"Project {label}", f"project-{label}"
    return "Skills root", "skills-root"


def _project_label(bucket: Bucket) -> str:
    """A project bucket's short name: the project folder's name and the
    bucket's own digest (the last eight characters of its slug, which keeps
    two projects with the same folder name apart)."""
    path = bucket_project_path(bucket.path)
    if path is None or not path.name:
        return bucket.name
    return f"{path.name}-{bucket.name[-8:]}"


def _place_reference(
    home: Path, bucket: Bucket, record: Record
) -> tuple[_Place | None, str]:
    """A reference lesson's shelf. ``managed_target_for`` has no answer for a
    reference (it has no managed section), so this follows the route-time
    resolution in ``verbs._resolve_target``: a skill's ``references/`` or a
    project's ``references/``; user scope has no shelf."""
    routing = record.routing or {}
    if bucket.scope == "skill":
        try:
            skill_dir = hosts_mod.skill_dir_for(hosts_mod.load_hosts(home), bucket.name)
        except hosts_mod.HostsError as exc:
            return None, f"the reference shelf cannot be resolved ({exc})"
        refs_dir = skill_dir / "references"
        owner, prefix = f"skill {bucket.name}", f"skill-{bucket.name}"
    elif bucket.scope == "project":
        host = bucket_project_path(bucket.path)
        if host is None:
            return None, "the reference shelf cannot be resolved (project host unknown)"
        label = _project_label(bucket)
        refs_dir = host / "references"
        owner, prefix = f"project {label}", f"project-{label}"
    else:
        return None, "the reference shelf cannot be resolved (user scope has no shelf)"
    target = reference_target_path(refs_dir, routing.get("reference_file"))
    shelf = target.stem if target.suffix == ".md" else target.name
    return (
        _Place(
            f"{prefix}-reference-{shelf}",
            KIND_REFERENCE,
            f"Reference shelf {target.name} of {owner}",
            "only when read; the SKILL.md or CLAUDE.md carries a pointer to it",
            target.resolve(),
        ),
        "",
    )


# ---------------------------------------------------------- surface keys ---


def _safe_key(raw: str) -> str:
    """A filesystem-safe, stable key for a raw key. A raw key made only of
    ``A-Za-z0-9._-`` is its own key. Any other becomes the same text with each
    run of other characters turned into ``-``, plus a short digest of the raw
    key, so two raw keys that differ never share a key. The key depends on the
    raw key alone: it does not change when another surface appears."""
    key = _UNSAFE_KEY_CHARS.sub("-", raw).strip("-.")
    if key == raw and 0 < len(key) <= _KEY_MAX:
        return key
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{(key or 'surface')[: _KEY_MAX - 9]}-{digest}"


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
    """Every skill Claude Code loads on this machine.

    Three places, in this order: ``<claude_dir>/skills/*`` (folders and
    symlinks), the ``skills/*`` of each enabled plugin, and
    ``.claude/skills/*`` of each registered host. A skill reached by more than
    one folder is listed once, under the first, with the others in ``also``
    (de-duplicated on the resolved ``SKILL.md``, as report.py does). A skill
    switched off in settings.json is listed in ``not_loaded`` instead.
    *placed* is the result of :func:`placed_lessons`, used for the lesson
    counts; it is computed when not given.
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

    def add(folder: Path, name: str, where: str, **extra: str | None) -> None:
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            return
        real = _resolved(skill_md)
        if real in found:
            known = found[real]
            if str(folder) != known.path and str(folder) not in known.also:
                found[real] = replace(known, also=known.also + (str(folder),))
            return
        if instrument.skill_overrides.get(name) == "off":
            not_loaded.append({"name": name, "path": str(folder)})
            return
        try:
            description, _tier = _extract_skill_description(skill_md.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            description = None
        real_folder = real.parent
        in_root = skills_root is not None and (
            real_folder == skills_root or skills_root in real_folder.parents
        )
        repo = skills_root.name if in_root and skills_root is not None else None
        found[real] = SkillEntry(
            name=name,
            description=description.strip() if isinstance(description, str) else None,
            where=where,
            path=str(folder),
            resolves_to=str(real_folder) if folder.is_symlink() else None,
            repo=repo,
            plugin=extra.get("plugin"),
            host=extra.get("host"),
            lessons=lesson_counts.get(real, 0),
        )

    # 1. personal: <claude_dir>/skills/*
    personal = claude / "skills"
    if personal.is_dir():
        try:
            folders = sorted(personal.iterdir())
        except OSError as exc:
            folders = []
            problems.append(f"{personal} could not be listed: {exc}")
        for folder in folders:
            add(folder, folder.name, WHERE_PERSONAL)

    # 2. enabled plugins
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
            skills_dir = root / "skills"
            if not skills_dir.is_dir():
                continue
            for folder in sorted(skills_dir.iterdir()):
                add(folder, f"{plugin_name}:{folder.name}", WHERE_PLUGIN, plugin=key)

    # 3. registered hosts' .claude/skills
    if registry is not None:
        # A repo registered as both a project and the skills root is one host.
        hosts: dict[Path, Path] = {}
        for host in [*registry.projects, *([registry.skills_root] if registry.skills_root else [])]:
            hosts.setdefault(_resolved(host), host)
        for host in hosts.values():
            skills_dir = host / ".claude" / "skills"
            if not skills_dir.is_dir():
                continue
            for folder in sorted(skills_dir.iterdir()):
                add(folder, folder.name, WHERE_HOST, host=str(host))

    skills = tuple(sorted(found.values(), key=lambda s: (s.name, s.path)))
    return SkillsOnMachine(
        skills=skills,
        not_loaded=tuple(sorted(not_loaded, key=lambda n: (n["name"], n["path"]))),
        problems=tuple(problems),
    )


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
    return {
        "skills": rows,
        "counts": {"total": len(rows), **dict(sorted(where_counts.items()))},
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
