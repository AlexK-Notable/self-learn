"""What the user asks of a skill self-learn owns, kept on the skill's own
record (S-110; skills.md SK-B, decisions 1 and 6 of the
2026-10-31b round).

Nothing in self-learn shows the user a skill or asks them about one (the
user, 2026-10-31: *"skills should be created unattended. i don't want to be
asked about them."*). When the user does want to act on a skill they say so,
in their own terminal or to an agent in any session, and it is done or
queued:

* ``self-learn skill veto <name> [--rename-to <new>]`` bans a name for ever
  (:func:`veto`). Any kebab-case name may be vetoed: a live skill self-learn
  owns (the next overseer run that writes skills renames it, or
  ``--rename-to`` renames it at once), a name a draft or a ``build``
  disposition used, a retired skill's name, or a name nothing has used yet.
  The veto is an entry in the registry's ``vetoed`` list
  (:mod:`self_learn.skill_registry`), so every later ``skill write`` and
  ``skill rename`` refuses the name.
* ``self-learn skill retire <name>`` of a skill lessons still route into
  records ``retire_requested`` on the skill's registry row
  (:func:`request_retire`); the next overseer run that writes skills moves
  the lessons out and retires it. With no lesson left it retires at once
  (``skill_writer.retire``).

The proof is who ran the command, not a presentation and not a statement:
from a person's own terminal it is the person's (``by: human``); from an
agent's shell the command runs only under the user's standing grant with
``--note`` (``grants.authorize``, decision 6) and is recorded ``by: agent``
with the grant's statement id. No case is touched: the request lives on the
registry, which the overseer's runner stages from :func:`pending_renames`
and :func:`pending_retire_requests` (``vetoes.yaml``).

Every registry write goes through :func:`skill_registry.with_update` with a
named callback, so the lock invariant sees it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path

from ruamel.yaml import YAML

from . import skill_registry, skill_writer
from .primitives import chrono
from .skill_registry import STATUS_LIVE, STATUS_RETIRED, SkillRegistryError
from .skill_scaffold import SKILL_NAME_MAX_CHARS, SKILL_NAME_RE

# Called by its bare name, never as ``skill_writer.rename(...)``: the lock
# invariant's walker reads every ``<x>.rename(...)`` call as ``Path.rename``.
from .skill_writer import rename as rename_skill

__all__ = [
    "RequestResult",
    "VetoResult",
    "describe_name",
    "pending_renames",
    "pending_retire_requests",
    "request_retire",
    "veto",
]

#: Where the overseer keeps drafts and its weekly discovery files, under
#: the ledger home (``overseer.skills.LEDGER_DIR``; not imported, the
#: overseer package imports this module).
_OVERSEER_SKILLS_DIR = "overseer/skills"


@dataclass(frozen=True)
class VetoResult:
    name: str
    ok: bool
    #: What the name is (``describe_name``), for the person's output.
    what: str = ""
    #: Whether this call added the veto (``False``: it was already vetoed,
    #: or the call was refused).
    added: bool = False
    ledger_sha: str | None = None
    problems: tuple[str, ...] = ()
    #: The rename ``--rename-to`` asked for, when one was asked.
    rename: skill_writer.RenameResult | None = None


@dataclass(frozen=True)
class RequestResult:
    name: str
    ok: bool
    added: bool = False
    #: The lessons that still route into the skill.
    routed: tuple[str, ...] = ()
    ledger_sha: str | None = None
    problems: tuple[str, ...] = ()


def _valid_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and SKILL_NAME_RE.fullmatch(name) is not None
        and len(name) <= SKILL_NAME_MAX_CHARS
    )


def _drafted(home: Path, name: str) -> bool:
    """Whether any week's drafts held a skill of this name."""
    root = home / _OVERSEER_SKILLS_DIR
    try:
        return any((week / "drafts" / name).is_dir() for week in root.iterdir() if week.is_dir())
    except OSError:
        return False


def _decided_build(home: Path, name: str) -> bool:
    """Whether a ``build`` disposition of any week named this skill."""
    root = home / _OVERSEER_SKILLS_DIR
    try:
        files = sorted(root.glob("*.yaml"))
    except OSError:
        return False
    for path in files:
        try:
            data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- an unreadable week file names nothing
            continue
        runs = data.get("runs") if isinstance(data, dict) else None
        for run in runs if isinstance(runs, list) else []:
            entries = run.get("dispositions") if isinstance(run, dict) else None
            for entry in entries if isinstance(entries, list) else []:
                if (
                    isinstance(entry, dict)
                    and entry.get("disposition") == "build"
                    and entry.get("skill") == name
                ):
                    return True
    return False


def describe_name(home: Path | str, registry: skill_registry.Registry, name: str) -> str:
    """What *name* is, in the words ``skill veto`` prints."""
    home = Path(home)
    row = registry.row(name)
    if registry.is_registered(name):
        return f"{name} is user-owned and registered: the veto stops edits, but never renames it"
    if registry.is_owned(name):
        return (
            f"{name} is a live skill self-learn owns: the next overseer run that writes skills "
            "renames it"
        )
    if row is not None and row["status"] == STATUS_RETIRED:
        return f"{name} was a skill self-learn retired: no skill is written under the name again"
    if _drafted(home, name) or _decided_build(home, name):
        return (
            f"{name} is a name the overseer drafted or decided to build: no skill is written "
            "under it, and the overseer chooses another name"
        )
    if _loaded_here(home, name):
        # gate r1 NIT: a skill a person made and self-learn does not own
        return (
            f"{name} is a skill on this machine that self-learn does not own: it is left as it "
            "is, and self-learn never writes a skill under the name"
        )
    return f"{name} is not a name any skill uses: banned for any future skill"


def _loaded_here(home: Path, name: str) -> bool:
    """Whether a skill or command on this machine is loaded under *name*
    (the writer's own catalogue read); ``False`` when it cannot be read."""
    try:
        loaded, _problems, _notes = skill_writer._loaded_names(  # noqa: SLF001 -- one definition
            home, leaving_out=None
        )
    except Exception:  # noqa: BLE001 -- only the printed words depend on it
        return False
    return name.casefold() in loaded


# ------------------------------------------------------------------ writes


def _add_veto(
    registry: skill_registry.Registry, *, name: str, at: str, by: str, grant: str | None,
) -> None:
    registry.add_veto(name, at=at, by=by, grant=grant)


def _add_retire_request(
    registry: skill_registry.Registry, *, name: str, at: str, by: str, grant: str | None,
) -> None:
    """Mark the live row *name* ``retire_requested``, unless it already is
    (the first request's date stands) or the skill is no longer live."""
    row = registry.skills.get(name)
    if row is None or row.get("status") != STATUS_LIVE or "retire_requested" in row:
        return
    request: dict = {"at": at, "by": by}
    if grant is not None:
        request["grant"] = grant
    row["retire_requested"] = request


def _check_by(by: str, grant: str | None) -> None:
    if by not in skill_registry.REQUEST_BY_VALUES:
        raise ValueError(
            f"a request is made by {' or '.join(skill_registry.REQUEST_BY_VALUES)}, not {by!r}"
        )
    if grant is not None and by != "agent":
        raise ValueError("only an agent's request runs under the user's standing grant")


def veto(
    home: Path | str,
    name: str,
    *,
    by: str,
    grant: str | None = None,
    rename_to: str | None = None,
    no_push: bool = False,
) -> VetoResult:
    """Ban *name* for ever (module docstring). With *rename_to*, a live
    skill self-learn owns under *name* is then renamed at once (``case:
    null``, as *by*). The veto stays when that rename is refused: the next
    overseer run that writes skills renames the skill instead."""
    home = Path(home)
    _check_by(by, grant)
    if not _valid_name(name):
        return VetoResult(
            name=name, ok=False,
            problems=(f"{name!r} is not a skill name (kebab-case, at most "
                      f"{SKILL_NAME_MAX_CHARS} characters)",),
        )
    if rename_to is not None and not _valid_name(rename_to):
        return VetoResult(
            name=name, ok=False,
            problems=(f"--rename-to {rename_to!r} is not a skill name (kebab-case, at most "
                      f"{SKILL_NAME_MAX_CHARS} characters)",),
        )
    try:
        registry = skill_registry.load(home)
        what = describe_name(home, registry, name)
        sha = skill_registry.with_update(
            home,
            partial(_add_veto, name=name, at=chrono.now_iso(), by=by, grant=grant),
            subject=f"skill veto {name}",
            body=f"By: {by}",
        )
    except SkillRegistryError as exc:
        return VetoResult(name=name, ok=False, problems=(str(exc),))
    renamed = None
    if rename_to is not None:
        renamed = rename_skill(home, name, rename_to, case=None, by=by, no_push=no_push)
    return VetoResult(
        name=name, ok=True, what=what, added=sha is not None, ledger_sha=sha, rename=renamed,
    )


def request_retire(
    home: Path | str, name: str, *, by: str, grant: str | None = None,
) -> RequestResult:
    """Ask the overseer to retire the live skill *name* self-learn owns:
    ``retire_requested`` on its registry row. The next overseer run that
    writes skills moves its lessons out and retires it; the request goes
    when the row is retired."""
    home = Path(home)
    _check_by(by, grant)
    try:
        registry = skill_registry.load(home)
    except SkillRegistryError as exc:
        return RequestResult(name=name, ok=False, problems=(str(exc),))
    if not registry.is_owned(name):
        return RequestResult(
            name=name, ok=False,
            problems=(f"{name} is not a live skill self-learn owns",),
        )
    routed = tuple(skill_writer.routed_lessons(home, name))
    try:
        sha = skill_registry.with_update(
            home,
            partial(_add_retire_request, name=name, at=chrono.now_iso(), by=by, grant=grant),
            subject=f"skill retire requested {name}",
            body=f"By: {by}",
        )
    except SkillRegistryError as exc:
        return RequestResult(name=name, ok=False, routed=routed, problems=(str(exc),))
    return RequestResult(name=name, ok=True, added=sha is not None, routed=routed, ledger_sha=sha)


# ------------------------------------------------------------------- reads


def _request_fields(entry: dict) -> dict:
    out = {"at": entry["at"]}
    for key in ("by", "grant", "statement"):
        if key in entry:
            out[key] = entry[key]
    return out


def pending_renames(home: Path | str) -> list[dict]:
    """Live skills whose name is vetoed, by name: ``{name, at, by?, grant?,
    statement?}`` from the veto. The overseer's next run that writes skills
    renames each. A skill renamed since has a new key, so it drops out.
    Reads the registry only."""
    registry = skill_registry.load(home)
    out = []
    for name in registry.live():
        entry = registry.veto_of(name)
        if entry is not None:
            out.append({"name": name, **_request_fields(entry)})
    return out


def pending_retire_requests(home: Path | str) -> list[dict]:
    """Live skills the user asked to retire: ``{name, at, by, grant?}`` from
    each row's ``retire_requested``, by name. Reads the registry only."""
    registry = skill_registry.load(home)
    out = []
    for name in registry.live():
        row = registry.skills[name]
        request = row.get("retire_requested")
        if isinstance(request, dict):
            out.append({"name": name, **_request_fields(request)})
    return out


# S-157: build/change requests are available to agents WITHOUT a standing grant.
# Unlike retirement and veto, these request a decision, not a destructive act.
REQUESTS_FILE = "skill-requests.yaml"


def requests(home: Path | str, *, open_only: bool = False) -> list[dict]:
    path = Path(home) / REQUESTS_FILE
    if not path.exists():
        return []
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        rows = data["requests"]
        if data.get("version") != 1 or not isinstance(rows, list):
            raise ValueError("expected version 1 and requests list")
        ids = set()
        for row in rows:
            if (not isinstance(row, dict) or row.get("kind") not in ("build", "change")
                or row.get("state") not in ("open", "closed") or not _valid_name(row.get("name"))
                or not isinstance(row.get("id"), str) or row["id"] in ids
                or row.get("by") not in ("human", "agent")
                or not isinstance(row.get("note"), str) or not row["note"].strip()
                or chrono.to_dt(row.get("at")) is None or not isinstance(row.get("lessons"), list)):
                raise ValueError("invalid request row")
            ids.add(row["id"])
        return [row for row in rows if not open_only or row["state"] == "open"]
    except Exception as exc:
        raise ValueError(f"cannot read {REQUESTS_FILE}: {exc}") from exc


def _save_requests(home: Path, rows: list[dict], subject: str, by: str) -> str | None:
    import io
    from . import gitops, intents
    from .primitives import fsops
    path = home / REQUESTS_FILE
    stream = io.StringIO()
    YAML().dump({"version": 1, "requests": rows}, stream)
    intent = intents.begin(home, "skill-requests", [path], subject)
    fsops.atomic_write(path, stream.getvalue(), fsync=True)
    intents.complete(intent)
    sha = gitops.stage_and_commit(home, [path], subject, f"By: {by}")
    intents.finish(intent)
    return sha


def file_request(home: Path | str, kind: str, name: str, *, lessons: list[str], note: str, by: str) -> dict:
    import uuid
    from . import intents
    from .ledger_ops import find_record_path
    from .skill_registration import _note_by
    _note_by(note, by)
    if kind not in ("build", "change") or not _valid_name(name):
        raise ValueError("request needs build/change and a valid skill name")
    home = Path(home)
    notes: list[str] = []
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        registry = skill_registry.load(home)
        if kind == "change" and not registry.may_edit(name):
            raise ValueError(f"{name} is neither owned nor registered; register it first")
        if kind == "change" and registry.veto_of(name):
            raise ValueError(f"{name} is vetoed; upkeep is disabled for this skill")
        if kind == "build":
            from .skill_scaffold import _check_name
            if registry.is_registered(name):
                raise ValueError(f"{name} is already registered; file a change request instead")
            loaded, catalogue_problems, _ = skill_writer._loaded_names(home, leaving_out=None)
            notes += [f"skills on this machine: {p}" for p in catalogue_problems]
            problems = _check_name(name, loaded_names=frozenset(loaded),
                vetoed_names=frozenset(registry.vetoed_names()), expected_name=name)
            if problems:
                clashes = sorted(n for n in loaded if n.rsplit(":", 1)[-1] == name.casefold())
                detail = "; already loaded: " + ", ".join(clashes) if clashes else ""
                raise ValueError("; ".join(str(p) for p in problems) + detail)
            if not lessons or len(set(lessons)) != len(lessons):
                raise ValueError("build needs distinct existing lesson ids")
            for rid in lessons:
                try:
                    find_record_path(home, rid)
                except Exception as exc:
                    raise ValueError(f"lesson does not exist: {rid}") from exc
            if registry.veto_of(name):
                raise ValueError(f"{name} is vetoed")
        row = {"id": "sr-" + uuid.uuid4().hex[:12], "kind": kind, "name": name,
            "lessons": lessons, "note": note.strip(), "by": by, "at": chrono.now_iso(), "state": "open"}
        rows = requests(home)
        existing = next((r for r in rows if r["state"] == "open" and r["kind"] == kind
            and r["name"] == name and set(r["lessons"]) == set(lessons)), None)
        if existing is not None:
            existing.setdefault("followups", []).append({"note": note.strip(), "by": by, "at": row["at"]})
            row = existing
        else:
            rows.append(row)
        sha = _save_requests(home, rows, f"self-learn: skill request {kind} {name}", by)
        return {**row, "ledger_commit": sha, "notes": notes}


def close_request(home: Path | str, ident: str, *, answer: str, reason: str, run: str, actual_name: str | None = None) -> None:
    from . import intents
    if answer not in ("built", "changed", "declined") or not isinstance(reason, str) or not reason.strip():
        raise ValueError("request answer needs built/changed/declined and a reason")
    home = Path(home)
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        rows = requests(home)
        row = next((row for row in rows if row["id"] == ident), None)
        if row is None:
            raise ValueError(f"unknown request {ident}")
        if row["state"] == "closed":
            return
        row.update(state="closed", answer=answer, reason=reason.strip(), decided_at=chrono.now_iso(), run=run)
        if actual_name is not None:
            row["actual_name"] = actual_name
        _save_requests(home, rows, f"self-learn: skill request {ident} {answer}", "overseer")


def withdraw_request(home: Path | str, ident: str, *, note: str, by: str) -> dict:
    from . import intents
    from .skill_registration import _note_by
    _note_by(note, by)
    home = Path(home)
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        rows = requests(home)
        row = next((r for r in rows if r["id"] == ident), None)
        if row is None:
            raise ValueError(f"unknown request {ident}")
        if row["state"] == "closed":
            return row
        row.update(state="closed", answer="withdrawn", reason=note.strip(),
            decided_at=chrono.now_iso(), withdrawn_by=by)
        _save_requests(home, rows, f"self-learn: skill request {ident} withdrawn", by)
        return row
