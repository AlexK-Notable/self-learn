"""notices.py -- one-line project notices at session start (hand-maintenance
cures, lane D: M7 and M6 part 3; decision row S-106, assigned at
landing).

The problem. Two kinds of fact end up outside the ledger with nobody to read
them: an overseer finding about a project's own code ("the shutdown watchdog
predates the daemon, no defect", 2026-10-25, which sat five days until a
person opened the report), and the uncommitted change self-learn leaves in a
tracked file of a plain host when it takes a lesson out of it (S-89 -- "a
person commits it", with nothing telling the person). Both are about ONE
project. The weekly report and the pending count are the wrong place for
them: a session working in that project needs the line, and a session
elsewhere does not.

What a notice is. One short line about one project, with:

- ``project``: the project's real path. A notice shows only in a session whose
  working directory is that path or somewhere inside it (a git worktree of the
  project included). It never shows anywhere else.
- ``source``: ``overseer`` (a finding the overseer wrote to its
  ``notices.yaml``, for a project the ledger knows) or ``code`` (the runner of
  a plain-host removal, for each tracked file it left changed).
- an end: it stops showing when a person runs ``self-learn notice done <id>``
  or when its condition clears (a ``code`` notice's file has no uncommitted
  change any more). A notice WITHOUT a condition also ends
  :data:`NOTICE_DAYS` (14) days after it was made. A notice WITH a condition
  has no age limit (S-106 as amended, hand-maintenance round b, lane CU-6): it
  is live while git still answers that the condition holds, because an
  uncommitted removal outlives 14 days and the note about it must too. Past
  14 days a condition that cannot be answered (git missing, a timeout, the
  budget spent) hides it; inside the 14 days it keeps the notice, as before.

Where it lives. In the CACHE, ``<cache>/notices/<id>.json``, one file per
notice, and never in the ledger: a notice carries a machine path, ends by
itself, and is a hint, not a record. A lost cache costs the hint and loses
nothing the ledger holds (the overseer's report still carries the finding and
the removal's warning still printed). One file per notice means two writers (a
verb in a shell and the overseer's run) never read-modify-write the same file.
Every write here is a ``NOT_REPO_TRUTH`` cache write for the lock invariant.

Identity. The id is ``ntc-`` plus eight hex digits of a hash of the project,
the source and a key (an overseer notice: ``case:<case id>`` when it names a
case, else its words; a code notice: the file). A notice a person marked done
keeps its key done for :data:`DONE_DAYS` (30) days, so the overseer cannot
bring it back in other words (:func:`is_done_key`).
The same finding written again by the next run is the same notice: it does not
start a new 14 days and does not come back after a person marked it done. A
code notice is different because it is only ever written right after a removal
changed the file: if the notice for that file is still live it stays as it is
(two removals before a commit are one notice, not two lines), and if it was
marked done or ran out its days the new change gets a fresh one.

What the reader costs. ``self-learn status --fast`` is the session-start
hook's one call, pinned git-free and cheap. Reading notices keeps that: a
notice outside the current project costs a path comparison. Only a ``code``
notice INSIDE the current project asks git one bounded question
(``git status --porcelain`` on its one file, no index lock, 1.5 s), all of a
call's questions together get :data:`GIT_TOTAL_BUDGET` seconds (the hook that
calls this gives up at 4 s and would lose every one of its lines), and an
answer that cannot be had -- git missing, a timeout, the budget spent --
keeps a notice inside its first 14 days and hides an older one. The hook prints at most
:data:`MAX_SHOWN` lines.

What this module does not do: decide anything, write the ledger, or touch a
host file. It never raises into a caller that is doing something else:
:func:`add`, :func:`add_uncommitted` and :func:`visible` answer ``None`` or an
empty list when something is wrong.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import cache_gc, scan
from .primitives import chrono, fsops

__all__ = [
    "GIT_CHECK_TIMEOUT",
    "DONE_DAYS",
    "GIT_TOTAL_BUDGET",
    "MAX_PER_RUN",
    "MAX_SHOWN",
    "MAX_TEXT",
    "NOTICE_DAYS",
    "Notice",
    "SOURCE_CODE",
    "SOURCE_OVERSEER",
    "add",
    "add_uncommitted",
    "all_notices",
    "condition_holds",
    "condition_state",
    "done_by_project",
    "is_done_key",
    "is_showing",
    "overseer_key",
    "uncommitted_removals",
    "format_line",
    "is_live",
    "known_projects",
    "mark_done",
    "notice_id",
    "notices_dir",
    "prune",
    "showing_by_project",
    "text_problem",
    "visible",
]

#: A notice stops showing this long after it was made (the user's 2026-10-30
#: agreement to design question Q3: "each ending when done, when its condition
#: clears, or after 14 days").
NOTICE_DAYS = 14
#: A notice file is deleted this long after it was made. Longer than the
#: expiry, so a finding the overseer repeats on the next run while the first
#: notice is still on file is the same notice and not a second one.
RETAIN_DAYS = 30
#: A notice marked done keeps its key done this long (the overseer is told
#: which notices were marked done, and one with the same key is not made again).
DONE_DAYS = 30
#: One line: the longest a notice's words may be.
MAX_TEXT = 200
#: The hook prints at most this many notices; the rest are counted.
MAX_SHOWN = 3
#: One overseer run writes at most this many notices (a run that wants more
#: has more to say than a session start should carry).
MAX_PER_RUN = 5
#: The most ``code`` notices one status call will ask git about.
MAX_CHECKS = 6
#: Seconds the one git question may take.
GIT_CHECK_TIMEOUT = 1.5
#: Seconds ALL the git questions of one :func:`visible` call may take together.
#: Six asks of 1.5 s each would be 9 s, past the 4 s the session-start hook
#: allows its one ``status --fast`` call, and a hook that times out prints none
#: of its lines. Once this is spent a notice is kept without asking.
GIT_TOTAL_BUDGET = 2.0

SOURCE_OVERSEER = "overseer"
SOURCE_CODE = "code"
SOURCES = (SOURCE_OVERSEER, SOURCE_CODE)

#: A ``code`` notice's condition: its file still has an uncommitted change.
COND_UNCOMMITTED = "uncommitted"

CACHE_SUBDIR = "notices"
_ID_PREFIX = "ntc-"
_VERSION = 1


@dataclass(frozen=True)
class Notice:
    """One notice, as stored."""

    id: str
    project: str
    text: str
    source: str
    created_at: str
    run: str | None = None
    #: ``{"kind": "uncommitted", "repo": <path>, "file": <path>}`` or ``None``.
    condition: dict[str, str] | None = None
    done_at: str | None = None
    #: The case an overseer notice comes from, when it named one.
    case: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": _VERSION,
            "id": self.id,
            "project": self.project,
            "text": self.text,
            "source": self.source,
            "created_at": self.created_at,
            "run": self.run,
            "condition": self.condition,
            "done_at": self.done_at,
            "case": self.case,
        }

    def expires_at(self) -> datetime | None:
        made = chrono.to_dt(self.created_at)
        return made + timedelta(days=NOTICE_DAYS) if made is not None else None


# ------------------------------------------------------------------ where


def notices_dir(home: Path | str) -> Path:
    """``<cache>/home-<digest>/notices``, with no side effects. The same
    per-home namespace :func:`worker.cache_dir` and :func:`serve.
    cache_dir_readonly` resolve; this module reads it by the formula so that
    importing it costs nothing and cannot cycle."""
    cache = cache_gc.cache_root() / f"home-{cache_gc.home_digest(home)}"
    return cache / CACHE_SUBDIR


def _path_for(home: Path | str, notice_id_: str) -> Path:
    return notices_dir(home) / f"{notice_id_}.json"


def _store(path: Path, notice: Notice, home: Path | str) -> None:
    """THE cache writer of this module (``NOT_REPO_TRUTH`` in the lock
    invariant: a file under the XDG cache, never a repo's truth). Atomic, so
    a reader never sees half a notice."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cache_gc.record_home(path.parent.parent, home)
    fsops.atomic_write(
        path, json.dumps(notice.as_dict(), sort_keys=True) + "\n", fsync=False, preserve_mode=False
    )


def _discard(path: Path) -> None:
    """Delete one notice file (``NOT_REPO_TRUTH``: a cache file). A file that
    is already gone is fine."""
    try:
        path.unlink()
    except OSError:
        pass


# ------------------------------------------------------------------- text


def text_problem(text: object) -> str | None:
    """Why *text* cannot be a notice's words, or ``None``. A notice is printed
    into a session's context, so it is one line of printable characters, at
    most :data:`MAX_TEXT` long, and secret-scanned."""
    if not isinstance(text, str) or not text.strip():
        return "a notice needs words"
    if text != text.strip():
        return "a notice has no leading or trailing space"
    if len(text) > MAX_TEXT:
        return f"a notice is at most {MAX_TEXT} characters (this one has {len(text)})"
    if not text.isprintable():
        return "a notice is one line of printable characters"
    if scan.scan(text):
        return "the secret scan matched the notice's words"
    return None


def notice_id(project: str, source: str, key: str) -> str:
    """``ntc-`` and eight hex digits of a hash of the three. Stable: the same
    finding written twice is the same notice."""
    digest = hashlib.sha256("\0".join((project, source, key)).encode("utf-8")).hexdigest()
    return f"{_ID_PREFIX}{digest[:8]}"


def _real(path: Path | str) -> str:
    return os.path.realpath(Path(path).expanduser())


# ------------------------------------------------------------------ reads


def _load(path: Path) -> Notice | None:
    """One notice file, or ``None`` when it is not a notice. Never raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    nid, project, text = data.get("id"), data.get("project"), data.get("text")
    source, made = data.get("source"), data.get("created_at")
    if not (
        isinstance(nid, str) and nid.startswith(_ID_PREFIX) and path.stem == nid
        and isinstance(project, str) and project
        and isinstance(text, str) and source in SOURCES and isinstance(made, str)
    ):
        return None
    if text_problem(text) is not None:
        return None  # a hand-edited file: its words are printed into a session
    condition = data.get("condition")
    if condition is not None and not (
        isinstance(condition, dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in condition.items())
    ):
        return None
    run, done, case = data.get("run"), data.get("done_at"), data.get("case")
    return Notice(
        id=nid, project=project, text=text, source=str(source), created_at=made,
        run=run if isinstance(run, str) else None,
        condition=dict(condition) if condition else None,
        done_at=done if isinstance(done, str) else None,
        case=case if isinstance(case, str) else None,
    )


def all_notices(home: Path | str) -> list[Notice]:
    """Every notice on file for *home*, done and expired ones included,
    newest first. A file that is not a notice is skipped."""
    folder = notices_dir(home)
    try:
        files = sorted(folder.glob(f"{_ID_PREFIX}*.json"))
    except OSError:
        return []
    found = [n for n in (_load(path) for path in files) if n is not None]
    found.sort(key=lambda n: (n.created_at, n.id), reverse=True)
    return found


def _inside(project: str, cwd: str) -> bool:
    """Whether *cwd* is *project* or somewhere below it. Both are real paths."""
    if cwd == project:
        return True
    root = project if project.endswith(os.sep) else project + os.sep
    return cwd.startswith(root)


def is_live(notice: Notice, now: datetime) -> bool:
    """Not done and not past its 14 days. (The condition is asked separately,
    :func:`condition_state`, because it may cost a git call; a notice with a
    condition is also current past its days while the condition holds, see
    :func:`is_showing`.)"""
    if notice.done_at is not None:
        return False
    expires = notice.expires_at()
    return expires is not None and now < expires


def _asks_git(notice: Notice) -> bool:
    """Whether the notice has a condition git can answer."""
    cond = notice.condition
    return bool(
        cond and cond.get("kind") == COND_UNCOMMITTED and cond.get("repo") and cond.get("file")
    )


def condition_state(notice: Notice, *, timeout: float = GIT_CHECK_TIMEOUT) -> str:
    """The notice's condition, asked once: ``"holds"``, ``"clear"`` or
    ``"unknown"`` (git missing, a timeout, a git error). No condition git can
    answer: it holds. An ``uncommitted`` condition: its file still shows in
    ``git status``; a repo that is gone clears it. *timeout* is the most
    seconds the one git question may take. Reads only: git runs with
    ``GIT_OPTIONAL_LOCKS=0`` so it takes no index lock."""
    if not _asks_git(notice):
        return "holds"
    cond = notice.condition or {}
    repo, file = str(cond["repo"]), str(cond["file"])
    if not Path(repo).is_dir():
        return "clear"
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain", "--", file],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return "holds" if proc.stdout.strip() else "clear"


def condition_holds(notice: Notice, *, timeout: float = GIT_CHECK_TIMEOUT) -> bool:
    """Whether the notice's condition still holds, counting an answer that
    cannot be had as "holds" (inside its first 14 days that keeps the notice).
    See :func:`condition_state` for the three-way answer."""
    return condition_state(notice, timeout=timeout) != "clear"


def is_showing(notice: Notice, now: datetime, *, timeout: float = GIT_CHECK_TIMEOUT) -> bool:
    """Whether the notice is current: not done, and either inside its 14 days
    or (a notice with a condition) its condition answers that it still holds.
    May ask git once."""
    if notice.done_at is not None:
        return False
    if is_live(notice, now):
        return True
    return _asks_git(notice) and condition_state(notice, timeout=timeout) == "holds"


def visible(
    home: Path | str, cwd: Path | str | None = None, *, now: datetime | None = None
) -> list[Notice]:
    """The notices a session started in *cwd* (default: the working
    directory) should be shown: live, for a project that holds *cwd*, with
    its condition still true. Newest first. Reads only; never raises."""
    try:
        here = _real(cwd if cwd is not None else os.getcwd())
        moment = now if now is not None else datetime.now(timezone.utc)
        out: list[Notice] = []
        checks = 0
        deadline = time.monotonic() + GIT_TOTAL_BUDGET
        for notice in all_notices(home):
            if not _inside(notice.project, here) or notice.done_at is not None:
                continue
            young = is_live(notice, moment)
            if not young and not _asks_git(notice):
                continue  # past its days and nothing to keep it
            if notice.condition:
                checks += 1
                if checks > MAX_CHECKS:
                    continue  # no more git questions this call; unconditioned notices still count
                left = deadline - time.monotonic()
                # The budget is spent: an answer cannot be had, so a notice
                # inside its first days is kept without asking (the same as a
                # git that timed out) and an older one is hidden.
                state = (
                    condition_state(notice, timeout=min(GIT_CHECK_TIMEOUT, left))
                    if left > 0 else "unknown"
                )
                if state == "clear" or (state == "unknown" and not young):
                    continue
            out.append(notice)
        return out
    except Exception:  # noqa: BLE001 -- a session start must never fail on a hint
        return []


# ----------------------------------------------------------------- writes


def add(
    home: Path | str,
    *,
    project: Path | str,
    text: str,
    source: str,
    key: str | None = None,
    run: str | None = None,
    condition: dict[str, str] | None = None,
    renew: bool = False,
    case: str | None = None,
    now: datetime | None = None,
) -> Notice | None:
    """Make one notice, or find the one that is already there. Answers the
    notice (new or existing), or ``None`` when *text* is not acceptable
    (:func:`text_problem`), *source* is unknown, or the cache cannot be
    written. Never raises.

    An existing notice with the same id is left exactly as it is: it keeps its
    first ``created_at`` (the 14 days run from the first sighting) and a done
    notice stays done. With *renew* (a ``code`` notice, written right after a
    new change) an existing notice that is done or past its days is replaced
    by a fresh one; a live one is still left alone. *case* is the case an
    overseer notice comes from, stored with it (the key, :func:`overseer_key`,
    is the caller's)."""
    try:
        if source not in SOURCES or text_problem(text) is not None:
            return None
        real_project = _real(project)
        nid = notice_id(real_project, source, key if key is not None else text)
        path = _path_for(home, nid)
        existing = _load(path)
        moment = now if now is not None else datetime.now(timezone.utc)
        if existing is not None and not (renew and not is_showing(existing, moment)):
            return existing
        notice = Notice(
            id=nid, project=real_project, text=text, source=source,
            created_at=chrono.now_iso(now), run=run, condition=condition,
            case=case if isinstance(case, str) and case else None,
        )
        _store(path, notice, home)
        prune(home, now=now)
        return notice
    except Exception:  # noqa: BLE001 -- a hint must never fail the verb that made it
        return None


def uncommitted_text(rel: str, commit_path: str | None = None) -> str:
    """The words of a ``code`` notice for a tracked file left changed. They
    name the step, so whoever reads the line (usually the agent working in the
    project) can do it: the exact ``git commit`` for the one file. *rel* is the
    file's path in the project, *commit_path* the pathspec for the command
    (default *rel*; the caller passes a repo-root one, ``:/<path>``, so it works
    from any directory). The command is never clipped: a path too long for the
    line makes the words fall back to naming the file and saying to commit it."""
    # No "self-learn" in the words: the printed line already starts with it
    # (:func:`format_line`).
    spec = shlex.quote(commit_path if commit_path is not None else rel)
    command = f'git commit -m "remove retired lesson lines" -- {spec}'
    text = (
        f"a retired lesson's lines were taken out of {rel}; nothing else changed. "
        f"Commit it: {command}"
    )
    if len(text) > MAX_TEXT and "/" in rel:
        text = (
            f"a retired lesson's lines were taken out of {rel.rsplit('/', 1)[1]}; "
            f"nothing else changed. Commit it: {command}"
        )
    if len(text) > MAX_TEXT:
        text = f"a retired lesson's lines were taken out of {rel}; the change is uncommitted: commit that file."
    if len(text) > MAX_TEXT:
        text = text[: MAX_TEXT - 3].rstrip() + "..."
    return text


def add_uncommitted(
    home: Path | str, *, project: Path | str, file: Path | str, now: datetime | None = None
) -> Notice | None:
    """The ``code`` notice for one tracked file of a plain host that a
    removal left changed (S-89). *project* is the host's path; the notice
    shows in sessions inside it. Its condition is that git still reports the
    file changed. Its key is the file: while a notice for it is live a further
    removal leaves it as it is, and one that was marked done or ran out its
    days is replaced by a fresh one (``renew``). Never raises; ``None`` when
    nothing could be made."""
    try:
        real_file = Path(_real(file))
        real_project = _real(project)
        try:
            rel = real_file.relative_to(real_project).as_posix()
        except ValueError:
            rel = real_file.name
        from . import gitops  # late: gitops is heavier than a status call needs

        repo = gitops.work_tree_of(real_file)
        if repo is None:
            return None
        try:
            commit_path = ":/" + real_file.relative_to(Path(_real(repo))).as_posix()
        except ValueError:
            commit_path = None
        return add(
            home, project=real_project, text=uncommitted_text(rel, commit_path), source=SOURCE_CODE,
            key=str(real_file), renew=True,
            condition={"kind": COND_UNCOMMITTED, "repo": str(repo), "file": str(real_file)},
            now=now,
        )
    except Exception:  # noqa: BLE001
        return None


def mark_done(home: Path | str, notice_id_: str, *, now: datetime | None = None) -> Notice | None:
    """A person (or an agent) says a notice is dealt with. Answers the notice
    as stored, or ``None`` when no such notice is on file. A notice already
    done is answered as it is. Raises ``OSError`` when the cache cannot be
    written (the verb that calls this says so)."""
    path = _path_for(home, notice_id_)
    existing = _load(path)
    if existing is None:
        return None
    if existing.done_at is not None:
        return existing
    done = Notice(
        id=existing.id, project=existing.project, text=existing.text,
        source=existing.source, created_at=existing.created_at, run=existing.run,
        condition=existing.condition, done_at=chrono.now_iso(now), case=existing.case,
    )
    _store(path, done, home)
    return done


def prune(home: Path | str, *, now: datetime | None = None) -> int:
    """Delete notice files made more than :data:`RETAIN_DAYS` ago -- except a
    notice with a condition that is not done, whose repo and file still exist
    and whose condition git has not answered "clear" (it outlives the age
    limit, :func:`is_showing`). Answers how many were deleted. Never raises."""
    try:
        moment = now if now is not None else datetime.now(timezone.utc)
        cutoff = moment - timedelta(days=RETAIN_DAYS)
        removed = 0
        for notice in all_notices(home):
            made = chrono.to_dt(notice.created_at)
            if made is None or made >= cutoff:
                continue
            if notice.done_at is None and _asks_git(notice):
                cond = notice.condition or {}
                if (
                    Path(str(cond["repo"])).is_dir()
                    and Path(str(cond["file"])).exists()
                    and condition_state(notice) != "clear"
                ):
                    continue
            _discard(_path_for(home, notice.id))
            removed += 1
        return removed
    except Exception:  # noqa: BLE001
        return 0


# --------------------------------------------------------------- projects


def showing_by_project(
    home: Path | str, *, now: datetime | None = None
) -> dict[str, list[str]]:
    """The words of every overseer notice still showing, by project (its real
    path): live, not done, not past its days. Phase B is shown this so it does
    not write a finding again that is still up -- a reworded one is a new
    notice (a new id, a fresh 14 days) and would come back after a person
    marked the first one done. Reads only; never raises."""
    out: dict[str, list[str]] = {}
    try:
        moment = now if now is not None else datetime.now(timezone.utc)
        for notice in all_notices(home):
            if notice.source == SOURCE_OVERSEER and is_live(notice, moment):
                out.setdefault(notice.project, []).append(notice.text)
    except Exception:  # noqa: BLE001
        return {}
    return out


def overseer_key(text: str, case: str | None) -> str:
    """The key an overseer notice is identified by: ``case:<id>`` when it
    names a case (the same case a week later is the same notice however it is
    worded), else its words."""
    return f"case:{case}" if case else text


def is_done_key(
    home: Path | str, project: Path | str, key: str, *,
    source: str = SOURCE_OVERSEER, now: datetime | None = None,
) -> bool:
    """Whether the notice with this (project, source, key) was marked done in
    the last :data:`DONE_DAYS` days. Reads only; never raises."""
    try:
        moment = now if now is not None else datetime.now(timezone.utc)
        existing = _load(_path_for(home, notice_id(_real(project), source, key)))
        if existing is None or existing.done_at is None:
            return False
        done = chrono.to_dt(existing.done_at)
        return done is not None and moment - done < timedelta(days=DONE_DAYS)
    except Exception:  # noqa: BLE001
        return False


def done_by_project(
    home: Path | str, *, now: datetime | None = None
) -> dict[str, list[str]]:
    """The words of every overseer notice marked done in the last
    :data:`DONE_DAYS` days, by project (its real path), so phase B can see why
    a finding it wants to repeat will not be shown. Reads only; never raises."""
    out: dict[str, list[str]] = {}
    try:
        moment = now if now is not None else datetime.now(timezone.utc)
        for notice in all_notices(home):
            if notice.source != SOURCE_OVERSEER or notice.done_at is None:
                continue
            done = chrono.to_dt(notice.done_at)
            if done is not None and moment - done < timedelta(days=DONE_DAYS):
                out.setdefault(notice.project, []).append(notice.text)
    except Exception:  # noqa: BLE001
        return {}
    return out


def uncommitted_removals(
    home: Path | str, *, timeout: float = GIT_CHECK_TIMEOUT
) -> list[dict[str, str]]:
    """Every not-done ``code`` notice whose condition git answers "holds":
    ``{project, file, since}`` -- a plain host's tracked file that a lesson
    removal left changed and nobody has committed. Asked by the overseer's
    run (no session-start budget). Oldest first. Never raises."""
    try:
        found: list[dict[str, str]] = []
        for notice in reversed(all_notices(home)):
            if notice.source != SOURCE_CODE or notice.done_at is not None:
                continue
            if not _asks_git(notice) or condition_state(notice, timeout=timeout) != "holds":
                continue
            found.append({
                "project": notice.project,
                "file": str((notice.condition or {}).get("file", "")),
                "since": notice.created_at,
            })
        return found
    except Exception:  # noqa: BLE001
        return []


def known_projects(home: Path | str) -> list[dict[str, str]]:
    """The projects the ledger knows, for the overseer's ``projects.yaml`` and
    for validating a notice's ``project``: every project bucket's recorded
    path (``projects/<slug>/meta.yaml``) and every registered host path, as
    ``{"name", "path"}`` with the real path, de-duplicated, stable order. A
    path that no longer exists is left out. Never raises."""
    found: dict[str, str] = {}
    try:
        from ruamel.yaml import YAML

        from .ledger import discover_buckets

        for bucket in discover_buckets(Path(home)):
            if bucket.scope != "project":
                continue
            try:
                meta = YAML(typ="safe").load((bucket.path / "meta.yaml").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            raw = meta.get("path") if isinstance(meta, dict) else None
            if isinstance(raw, str) and raw:
                found.setdefault(_real(raw), bucket.name)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .hosts import load_hosts

        hosts = load_hosts(home)
        for path in [*hosts.projects, *([hosts.skills_root] if hosts.skills_root else [])]:
            real = _real(path)
            found.setdefault(real, Path(real).name)
    except Exception:  # noqa: BLE001
        pass
    return [
        {"name": name, "path": path}
        for path, name in sorted(found.items())
        if Path(path).is_dir()
    ]


def format_line(notice: Notice) -> str:
    """The one line the hook prints for a notice."""
    return f"self-learn: {notice.text} (done with it: self-learn notice done {notice.id})"
