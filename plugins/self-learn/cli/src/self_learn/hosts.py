"""Compile-host registry (doc 13 §3, T-H3): hosts.yaml in the ledger home.

The ledger home holds ONLY ledger data; canon is compiled into HOST repos
that must be registered here first (invariant H-3: compile targets come
from hosts.yaml only — capture is open, canon is registered; no autonomous
process ever writes to an unregistered repo). One file to read to know
where canon may land:

    skills_root: /home/user/repos/claude-skills   # plugins/*/skills/* live here
    projects:
      - path: /home/user/repos/claude-skills      # CLAUDE.md targets

Registration is a CLI verb (``self-learn host add <path> [--skills-root]
[--mode git|plain]``, ``host rebind <slug-or-old-path> <new-path>``,
``host remove <path>``), never a hand edit the compilers trust blindly —
:func:`host_add` validates the path (must exist; must be a git repo when
``mode == "git"``, the default), rewrites hosts.yaml, and commits it in
the ledger repo with the pinned subject
``self-learn: host add <kind> <path>``.

Validation is at the GATE, not only at registration (audit 2026-07-16:
``load_hosts`` trusted a hand-edited hosts.yaml blindly, so a typo'd
``skills_root: /home/user/repos`` would CREATE ``/home/user/repos/
CLAUDE.md`` — canon written outside any repo — and only then fail its
commit). :func:`validate_host_path` is the one gate predicate; every
canon-writing path runs it (``verbs._resolve_target``), while
:func:`load_hosts` stays lenient about MISSING/BROKEN entries (so
``host list`` can SHOW a broken entry marked broken instead of exploding)
while being STRICT about unknown shape — an unrecognized key in a project
entry or a ``skills_root`` mapping raises (U-hostmode MODE10): silently
dropping it is a rollback hazard (§4.13), not a crash.

Slugs: :func:`slug_for` keeps Claude Code's ``~/.claude/projects``
readable shape — ``str(resolved path).replace("/", "-")`` — and appends
``-<sha256(resolved)[:8]>`` (audit 2026-07-16 BLOCKER: the readable shape
ALONE is ambiguous — ``/w/a-b`` and ``/w/a/b`` both slug to ``-w-a-b``,
cross-homing one project's lessons into another project's canon). The
hash is taken over the resolved path string, so the slug is stable per
path and collision-free in practice; the readable prefix survives for
humans reading ``projects/``.

**U-hostmode (git-optional canon hosts, §4.1-§4.4).** A registered host
now carries a MODE — ``"git"`` (default; today's behaviour, byte-for-byte)
or ``"plain"`` (no repo required; nothing staged, committed, or pushed
there). :func:`host_mode` is the ONE place a posture is decided — no
other site may infer a posture from repo presence, and no site may infer
user scope from a missing path (MODE9). A plain host is gated by a
``.self-learn-host`` marker file (:data:`MARKER_FILENAME`) the registering
verb writes — the structural analogue of ``.git`` — never by being
writable.
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import config as _config
from . import gitops

__all__ = [
    "HOST_KINDS",
    "HOST_MODES",
    "INIT_COMMIT_SUBJECT",
    "MARKER_FILENAME",
    "Hosts",
    "HostsError",
    "ancestors_of",
    "canon_read_roots",
    "effective_default_mode",
    "host_add",
    "host_marker_path",
    "host_mode",
    "host_rebind",
    "host_remove",
    "host_path_problem",
    "host_slug",
    "hosts_path",
    "is_project_host",
    "is_repo_root",
    "load_hosts",
    "save_hosts",
    "skill_dir_for",
    "slug_for",
    "unregistered_ancestor_dirs",
    "validate_host_path",
]

#: 13 §7.3/D1: the guard-canon dir for project/user-scope hook records,
#: relative to the registered skills root.
HOOK_CANON_USER_DIR = "hooks/self-learn"

HOST_KINDS = ("skills-root", "project")

#: U-hostmode §4.1/§4.2: the two version-control postures a host may
#: carry. Absent in hosts.yaml == "git" (MODE1) — every entry written
#: before this unit means "git".
HOST_MODES = ("git", "plain")

#: U-hostmode §4.4: the H-3 replacement guard for a plain host — a marker
#: file at the EXACT registered path, written by ``host add --mode
#: plain``, the structural analogue of ``.git``. A hand edit of
#: hosts.yaml naming a plain path cannot conjure this file.
MARKER_FILENAME = ".self-learn-host"


class HostsError(Exception):
    """hosts.yaml is malformed, or a registration was refused."""


@dataclass(frozen=True)
class Hosts:
    """The parsed registry: one optional skills root + registered
    projects, each carrying a mode (U-hostmode MODE7: the SHAPE of
    ``skills_root``/``projects`` is unchanged — every existing consumer
    that reads them as ``Path | None`` / ``list[Path]`` keeps working
    unedited; the mode rides two NEW, parallel fields nobody pre-existing
    reads)."""

    skills_root: Path | None = None
    projects: list[Path] = field(default_factory=list)
    #: MODE1/MODE2: absent from hosts.yaml == "git".
    skills_root_mode: str = "git"
    #: Keyed by ``str(<resolved project path>)``. Only non-"git" entries
    #: are ever stored (MODE2's byte-identical round-trip for a mode-free
    #: registry falls out of that for free — nothing to look up, nothing
    #: to re-serialize).
    project_modes: dict[str, str] = field(default_factory=dict)


def slug_for(path: Path | str) -> str:
    """The project bucket's directory name: Claude Code's readable
    projects-dir shape (resolved path, ``/`` → ``-``; the leading ``-``
    from the root slash is deliberate) PLUS a short digest of the resolved
    path.

    The digest is not decoration (audit 2026-07-16 BLOCKER 1): the
    readable shape alone is many-to-one — ``/w/a-b`` and ``/w/a/b`` both
    render ``-w-a-b`` — so two different projects shared one bucket and
    project B's records compiled into project A's CLAUDE.md. Slug =
    ``<readable>-<sha256(resolved)[:8]>``: still greppable by eye, stable
    per path, and injective for any pair of paths that do not also
    collide on SHA-256."""
    resolved = str(Path(path).resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
    return f"{resolved.replace('/', '-')}-{digest}"


def host_slug(home: Path | str, path: Path | str, *, scope_kind: str | None = None) -> str:
    """U-hostmode §4.2: the compile record's key — :func:`slug_for` for a
    registered host, and the literal ``"user"`` for the user-scope host
    (``scope_kind == "user"``, which is never registered in hosts.yaml —
    §4.8, USER3). ``home`` is accepted for signature symmetry with
    :func:`host_mode` (a future keying scheme might need it); the current
    implementation does not read the registry."""
    del home
    if scope_kind == "user":
        return "user"
    return slug_for(path)


def hosts_path(home: Path | str) -> Path:
    return Path(home) / "hosts.yaml"


def host_marker_path(path: Path | str) -> Path:
    """U-hostmode §4.4: where the plain-host marker lives for *path*."""
    return Path(path).expanduser().resolve() / MARKER_FILENAME


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.default_flow_style = False
    return y


def _parse_mode(path: Path, where: str, raw: object) -> str:
    """Shared shape check for a ``mode:`` value found at *where* (a
    project entry or the ``skills_root`` mapping)."""
    if raw is None:
        return "git"
    if raw not in HOST_MODES:
        raise HostsError(
            f"{path}: {where} must be one of {list(HOST_MODES)}, got {raw!r}"
        )
    return raw


def load_hosts(home: Path | str) -> Hosts:
    """Parse ``<home>/hosts.yaml``. A missing file is an EMPTY registry
    (nothing registered — every compile gate refuses), never an error;
    a malformed file raises :class:`HostsError` with the exact complaint.

    U-hostmode MODE10: an unrecognized key in a project entry mapping or
    the ``skills_root`` mapping REFUSES — the shipped (pre-unit) parser
    silently dropped one, which is a rollback hazard (§4.13), not merely
    a courtesy here."""
    path = hosts_path(home)
    if not path.is_file():
        return Hosts()
    try:
        data = _yaml().load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        raise HostsError(f"unparseable hosts.yaml at {path}: {exc}") from exc
    if data is None:
        return Hosts()
    if not isinstance(data, dict):
        raise HostsError(f"{path} must be a YAML mapping, got {type(data).__name__}")

    raw_root = data.get("skills_root")
    skills_root: Path | None = None
    skills_root_mode = "git"
    if raw_root is not None:
        if isinstance(raw_root, str):
            skills_root = Path(raw_root).expanduser()
        elif isinstance(raw_root, dict):
            unknown = sorted(set(raw_root) - {"path", "mode"})
            if unknown:
                raise HostsError(
                    f"{path}: skills_root has unrecognized key(s) {unknown} "
                    "— only 'path' and 'mode' are known"
                )
            raw_path = raw_root.get("path")
            if not isinstance(raw_path, str):
                raise HostsError(
                    f"{path}: skills_root.path must be a path string, got {raw_path!r}"
                )
            skills_root = Path(raw_path).expanduser()
            skills_root_mode = _parse_mode(path, "skills_root.mode", raw_root.get("mode"))
        else:
            raise HostsError(
                f"{path}: skills_root must be a path string or a "
                f"{{path: <str>, mode?: <str>}} mapping, got {raw_root!r}"
            )

    projects: list[Path] = []
    project_modes: dict[str, str] = {}
    raw_projects = data.get("projects")
    if raw_projects is not None:
        if not isinstance(raw_projects, list):
            raise HostsError(f"{path}: projects must be a list, got {raw_projects!r}")
        for i, entry in enumerate(raw_projects):
            if isinstance(entry, str) and entry.strip():
                projects.append(Path(entry).expanduser())
            elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
                unknown = sorted(set(entry) - {"path", "mode"})
                if unknown:
                    raise HostsError(
                        f"{path}: projects[{i}] has unrecognized key(s) "
                        f"{unknown} — only 'path' and 'mode' are known"
                    )
                p = Path(entry["path"]).expanduser()
                projects.append(p)
                mode = _parse_mode(path, f"projects[{i}].mode", entry.get("mode"))
                if mode != "git":
                    project_modes[str(p.resolve())] = mode
            else:
                raise HostsError(
                    f"{path}: projects[{i}] must be a path string or a "
                    f"{{path: <str>, mode?: <str>}} mapping, got {entry!r}"
                )
    return Hosts(
        skills_root=skills_root,
        projects=projects,
        skills_root_mode=skills_root_mode,
        project_modes=project_modes,
    )


def save_hosts(home: Path | str, hosts: Hosts) -> Path:
    """Serialize the registry back to ``<home>/hosts.yaml`` (canonical
    shape: ``skills_root`` scalar + ``projects`` list of path mappings).

    U-hostmode MODE2: ``mode`` is emitted ONLY when it is not the default
    ("git") — so a registry with every host in git mode round-trips
    byte-identically to what this function produced before this unit."""
    path = hosts_path(home)
    if hosts.skills_root is None:
        root_value = None
    elif hosts.skills_root_mode != "git":
        root_value = {"path": str(hosts.skills_root), "mode": hosts.skills_root_mode}
    else:
        root_value = str(hosts.skills_root)
    projects_value = []
    for p in hosts.projects:
        mode = hosts.project_modes.get(str(Path(p).resolve()), "git")
        entry = {"path": str(p)}
        if mode != "git":
            entry["mode"] = mode
        projects_value.append(entry)
    data = {"skills_root": root_value, "projects": projects_value}
    buf = io.StringIO()
    _yaml().dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def is_project_host(hosts: Hosts, path: Path | str) -> bool:
    """True iff *path* (resolved) is a registered project host."""
    target = Path(path).resolve()
    return any(Path(p).resolve() == target for p in hosts.projects)


def host_mode(home: Path | str, path: Path | str) -> str:
    """U-hostmode §4.1: THE ONE resolver for a registered host's posture.
    Returns ``"git"`` for a registered git-mode host, an UNREGISTERED
    path (the pre-existing, safe default), or a path that fails to
    resolve; returns ``"plain"`` only for a path this registry names as
    plain (project entry or ``skills_root``, exact resolved-path match).

    No other site may decide a posture (MODE9) — a caller with a
    :class:`~self_learn.verbs.TargetSpec` reads ``spec.mode`` (computed
    HERE, once, at resolve time), never re-derives one from ``.git``
    presence."""
    hosts = load_hosts(home)
    try:
        target = Path(path).expanduser().resolve()
    except OSError:
        return "git"
    if hosts.skills_root is not None:
        try:
            if Path(hosts.skills_root).expanduser().resolve() == target:
                return hosts.skills_root_mode
        except OSError:
            pass
    for p in hosts.projects:
        try:
            resolved = Path(p).expanduser().resolve()
        except OSError:
            continue
        if resolved == target:
            return hosts.project_modes.get(str(resolved), "git")
    return "git"


def effective_default_mode(home: Path | str) -> str:
    """U-hostmode MODE3: the default mode for a NEWLY registered host —
    a thin re-export of :func:`config.effective_default_mode`, kept here
    too so a caller resolving hosts-registry concerns never needs a
    second import."""
    return _config.effective_default_mode(home)


def _is_git_repo(path: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=gitops.GIT_LOCAL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


#: 09 §11 Y-17 / 13 §3: the pinned subject of the ``--init`` leg's empty
#: root commit. Best-effort-ONCE (F7): a zero-commit repo already counts
#: as a root, so after a failed empty commit the retry skips the init leg
#: entirely and this subject may never exist for that host.
INIT_COMMIT_SUBJECT = "self-learn: init for host registration"


def is_repo_root(path: Path | str) -> bool:
    """The Y-17 predicate (09 §11 Y-17 decision 2 / 13 §3): is the EXACT
    resolved path itself a git repository ROOT — i.e. its own ``git -C
    <path> rev-parse --show-toplevel``? The existing is-inside-work-tree
    check cannot carry this decision: it answers TRUE for a path
    swallowed by a PARENT repo's work tree. A ZERO-COMMIT repo counts as
    a root (F7 — ``--show-toplevel`` resolves before the first commit).

    CLI-owned and IMPORTED by the ui server for its ``needs_init``
    derivation at arm and confirm (the ``canon_read_roots()`` posture —
    one implementation, both sides of the seam, never a second)."""
    target = Path(path).expanduser()
    if not target.is_dir():
        return False
    target = target.resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=gitops.GIT_LOCAL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False
    if proc.returncode != 0:
        return False
    toplevel = proc.stdout.strip()
    return bool(toplevel) and Path(toplevel).resolve() == target


def _init_for_registration(path: Path | str) -> None:
    """The ``--init`` leg (09 §11 Y-17 semantics matrix; 13 §3 mirror):
    make the exact path a committable repo BEFORE the standard
    validation runs. Callers run this AFTER the pure-argument refusals
    (kind validity, ledger-home existence, ``--mode plain --init`` —
    F6: an invalid invocation must never leave an initialized repo
    behind) and BEFORE :func:`validate_host_path`. ``--init`` is a
    GIT-mode-only convenience (U-hostmode §4.2) — callers refuse the
    combination ``--mode plain --init`` before this ever runs.

    Matrix rows realized here:

    - path IS already a repo root (zero-commit included — F7): no-op;
      preserves ``host add``'s idempotency and absorbs the arm→confirm
      becomes-repo race instead of failing the confirm;
    - path is a directory and NOT a root — including inside a parent
      repo's work tree (nested repos are acceptable and intended):
      ``git init`` at the exact path + an empty root commit with
      :data:`INIT_COMMIT_SUBJECT`;
    - path missing OR a regular file: clean refusal in this verb's own
      words, never a fall-through to raw git stderr (F8) — ``--init``
      initializes existing directories only, it creates nothing;
    - root-commit failure (unset git identity is the realistic case):
      raise with git's stderr and NO hosts.yaml mutation. Honesty pin:
      init is not transactional with the add — the path stays an
      initialized zero-commit repo (harmless), and the retry no-ops
      this leg entirely (best-effort-ONCE, F7)."""
    target = Path(path).expanduser()
    if is_repo_root(target):
        return
    if not target.is_dir():
        what = "is a regular file, not a directory" if target.exists() else "does not exist on disk"
        raise HostsError(
            f"--init initializes existing directories only — {target} "
            f"{what}; create the project directory first, then re-run"
        )
    target = target.resolve()
    init = subprocess.run(
        ["git", "init", str(target)], capture_output=True, text=True
    )
    if init.returncode != 0:
        raise HostsError(f"git init {target} failed: {init.stderr.strip()}")
    commit = subprocess.run(
        ["git", "-C", str(target), "commit", "--allow-empty", "-m", INIT_COMMIT_SUBJECT],
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        raise HostsError(
            f"{target} was initialized (git init) but the empty root "
            f"commit failed: {commit.stderr.strip()} — nothing was "
            "registered; the path stays a zero-commit repo and a retry "
            "skips the init step (fix your git identity or commit in "
            "the repo yourself, then re-run)"
        )


def host_path_problem(
    home: Path | str, path: Path | str, kind: str, *, mode: str | None = None
) -> str | None:
    """The ONE host-path predicate (audit 2026-07-16 MAJOR 6): a host path
    must exist on disk, be SOUND for its registered mode, and MUST NOT be
    the ledger home itself (the ledger holds ledger data; canon compiled
    into it would make the source of truth its own host — doc 13 §2's
    three layers). Returns a human sentence naming the offending entry and
    the verb that fixes it, or None when the entry is sound.

    U-hostmode §4.4: "sound for its mode" means a git work tree for a
    ``git``-mode entry (unchanged) or the :data:`MARKER_FILENAME` marker
    for a ``plain``-mode entry — the H-3 replacement guard: a hand-edited
    hosts.yaml naming a plain path with no marker is refused here, before
    any commit (GATE2), exactly as a typo'd git entry always was.

    Used at registration (:func:`host_add`, for GIT-mode entries only —
    see its own validation for plain, which cannot consult THIS registry
    for a mode not yet written) AND at every canon-writing gate
    (``verbs._resolve_target``) — hosts.yaml is data, and data that only
    gets checked when it is written is data nobody checks.

    ``mode`` (M-12, code gate r1 fold): the CARRIED mode, when a caller
    already knows it and ``path`` is not (yet, or ever going to be)
    registered under it — :func:`host_rebind`'s own case: the new path
    is unregistered by definition (rebind is what registers it), so the
    default ``host_mode`` lookup below reads "unregistered ⇒ git" no
    matter what the OLD entry's mode was, and a plain host could never
    be rebound to a repo-less directory. ``None`` (the default) keeps
    every other caller's behaviour byte-identical: look the mode up in
    the registry, exactly as before."""
    target = Path(path).expanduser()
    label = f"{kind} host {target}"
    if not target.is_dir():
        return (
            f"{label} does not exist on disk — the repo moved or was "
            f"removed; re-point it with `self-learn host rebind {target} "
            "<new-path>` (or `self-learn host remove` it)"
        )
    target = target.resolve()
    resolved_mode = mode if mode is not None else host_mode(home, target)
    if resolved_mode == "plain":
        if not (target / MARKER_FILENAME).is_file():
            return (
                f"{label} is registered plain but carries no "
                f"{MARKER_FILENAME} marker — a hand-edited hosts.yaml "
                "entry, or the marker was removed; re-register it with "
                "`self-learn host add --mode plain`"
            )
    elif not _is_git_repo(target):
        return (
            f"{label} is not a git repo — canon hosts must be committable "
            "in git mode (doc 13 §4 two-phase routing; or register it "
            "`--mode plain`); fix hosts.yaml via `self-learn host add` / "
            "`host rebind`"
        )
    if Path(home).expanduser().resolve() == target:
        return (
            f"{label} IS the ledger home — the ledger is the source of "
            "truth, never a canon host (doc 13 §2); re-point it with "
            "`self-learn host rebind` or remove the entry"
        )
    return None


def validate_host_path(
    home: Path | str, path: Path | str, kind: str, *, mode: str | None = None
) -> Path:
    """:func:`host_path_problem` as a gate: raise :class:`HostsError` on a
    bad entry, else return the resolved path. ``mode`` (M-12) threads
    straight through — see :func:`host_path_problem`'s own docstring."""
    problem = host_path_problem(home, path, kind, mode=mode)
    if problem is not None:
        raise HostsError(problem)
    return Path(path).expanduser().resolve()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_host_marker(home: Path, target: Path) -> Path:
    """U-hostmode §4.4: one line naming the registering ledger home and
    an ISO timestamp — the structural analogue of ``.git``. Written
    BEFORE the ledger commit (mirrors ``--init``'s own honesty caveat:
    not transactional with the hosts.yaml write; a failed commit leaves
    an orphan marker, which is harmless and idempotent to re-register
    over). Guarded by the SAME plain-host lock a route/recompile would
    take against this exact path (``test_lock_invariant``'s structural
    walker: every repo-truth write needs a recognised lock on its path,
    and a fresh registration is no exception)."""
    marker = host_marker_path(target)
    with gitops.host_lock(target, "plain"):
        marker.write_text(
            f"home={Path(home).expanduser().resolve()} at={_now_iso()}\n",
            encoding="utf-8",
        )
    return marker


def host_add(
    home: Path | str,
    path: Path | str,
    kind: str,
    *,
    init: bool = False,
    mode: str = "git",
) -> Hosts:
    """The ``host add`` verb's backing function (doc 13 §3): validate the
    path (must exist; must be a git repo when ``mode == "git"``), rewrite
    hosts.yaml, and commit it in the LEDGER repo — pinned subject
    ``self-learn: host add <kind> <path>``. Idempotent: re-adding an
    already-registered host with the SAME mode changes nothing and
    commits nothing; re-adding with a DIFFERENT mode REFUSES (MODE6,
    U-hostmode R-f — the ruled "set once" shape: change is
    ``host remove`` + ``host add --mode``).

    ``init`` (09 §11 Y-17, 2026-07-18): run the ``--init`` leg
    (:func:`_init_for_registration`) between the pure-argument refusals
    and the path validation — validation ordering is normative (F6): the
    read-only kind/ledger-home/mode refusals FIRST (an invalid kind or an
    incoherent ``--mode plain --init`` must never leave an initialized
    repo behind), then init, then the path validation + idempotency
    exactly as they run today. Without ``init``, behavior is
    byte-unchanged for ``mode == "git"``.

    ``mode`` (U-hostmode MODE4): ``"plain"`` skips the git-repo
    requirement entirely and writes :data:`MARKER_FILENAME` instead —
    :func:`host_path_problem` cannot be reused for this leg's OWN
    validation because hosts.yaml does not carry the entry yet (its
    ``host_mode`` lookup would read "unregistered ⇒ git", the wrong
    answer for a plain registration in progress).

    Lock discipline (audit 2026-07-16 round 7 BLOCKER 1): the lock opens
    BEFORE :func:`save_hosts`, not at the commit. hosts.yaml is TRACKED,
    so a rewrite of it is exactly what a racing ``pull --rebase
    --autostash`` stashes and then restores into a conflict — the same
    window round 3 closed in ``verbs.py`` and left open here."""
    home = Path(home)
    if kind not in HOST_KINDS:
        raise HostsError(f"kind must be one of {list(HOST_KINDS)}, got {kind!r}")
    if mode not in HOST_MODES:
        raise HostsError(f"mode must be one of {list(HOST_MODES)}, got {mode!r}")
    if mode == "plain" and init:
        raise HostsError(
            "--mode plain --init makes no sense — --init only initializes "
            "a GIT repo (a plain host needs no repo at all); drop one flag"
        )
    if not home.is_dir():
        raise HostsError(f"ledger home {home} does not exist")
    if init:
        _init_for_registration(path)

    target = Path(path).expanduser()
    if not target.is_dir():
        raise HostsError(
            f"{kind} host {target} does not exist on disk — the repo "
            f"moved or was removed; re-point it with `self-learn host "
            f"rebind {target} <new-path>` (or `self-learn host remove` it)"
        )
    target = target.resolve()

    # U-hostmode M-11 (code gate r1 fold): the mode-flip/already-
    # registered refusal (MODE6) must run BEFORE the git-repo-soundness
    # check, in BOTH directions. Pre-fold this ran AFTER it, so a
    # PLAIN-registered host re-added with `mode="git"` hit the git-repo
    # check first — it is not (and was never expected to be) a git
    # repo, so THAT refusal fired instead of MODE6's, masking the repair
    # it names (`host remove` + `host add --mode`). The git→plain
    # direction never showed this: the git-repo check only RUNS for
    # `mode == "git"`, so a plain re-add skipped straight past it to the
    # (correctly ordered, even before this fix) mode-flip check below —
    # which is exactly why only that one direction had a test.
    hosts = load_hosts(home)
    existing_mode: str | None = None
    if kind == "skills-root":
        if hosts.skills_root is not None and hosts.skills_root.resolve() == target:
            existing_mode = hosts.skills_root_mode
    else:
        if is_project_host(hosts, target):
            existing_mode = host_mode(home, target)

    if existing_mode is not None and existing_mode != mode:
        raise HostsError(
            f"{kind} host {target} is already registered as "
            f"{existing_mode!r} — `self-learn host remove {target}` "
            f"then `self-learn host add {target} --mode {mode}` to "
            "change it (MODE is set once; there is no in-place flip)"
        )

    if mode == "git" and not _is_git_repo(target):
        raise HostsError(
            f"{kind} host {target} is not a git repo — canon hosts must "
            "be committable in git mode (doc 13 §4 two-phase routing; or "
            "register it `--mode plain`); fix hosts.yaml via "
            "`self-learn host add` / `host rebind`"
        )
    if Path(home).expanduser().resolve() == target:
        raise HostsError(
            f"{kind} host {target} IS the ledger home — the ledger is the "
            "source of truth, never a canon host (doc 13 §2); re-point it "
            "with `self-learn host rebind` or remove the entry"
        )

    if existing_mode is not None:
        return hosts  # already registered, same mode — nothing to do

    if mode == "plain":
        _write_host_marker(home, target)

    if kind == "skills-root":
        hosts = Hosts(
            skills_root=target,
            projects=hosts.projects,
            skills_root_mode=mode,
            project_modes=hosts.project_modes,
        )
    else:
        new_modes = dict(hosts.project_modes)
        if mode != "git":
            new_modes[str(target)] = mode
        hosts = Hosts(
            skills_root=hosts.skills_root,
            projects=[*hosts.projects, target],
            skills_root_mode=hosts.skills_root_mode,
            project_modes=new_modes,
        )

    message = f"self-learn: host add {kind} {target}"
    # BLOCKER 4: scoped like every producer. Round 7 BLOCKER 1: and the
    # lock now opens before the FIRST mutation (save_hosts), not at stage.
    with gitops.commit_lock(home):
        yaml_path = save_hosts(home, hosts)
        _commit_or_half_written(home, [yaml_path], message)
    return hosts


def _commit_or_half_written(
    home: Path, touched: list[Path], message: str
) -> None:
    """stage → pinned commit, with the state fact attached to the failure.

    **Callers must already hold** ``gitops.commit_lock(home)``: everything
    here is post-mutation by construction, so a :class:`gitops.GitOpsError`
    from either call means the registry was rewritten and NOT committed —
    :class:`gitops.HalfWrittenError` is the type that says so, and it
    carries the repair (audit 2026-07-16 round 7 BLOCKER 2: the ``host``
    verbs raised the bare class, which dispatch would have rendered as
    "nothing was written")."""
    try:
        gitops.stage(home, touched)
        gitops.commit(home, message, paths=touched)
    except gitops.HalfWrittenError:
        raise
    except gitops.GitOpsError as exc:
        raise gitops.HalfWrittenError.for_commit(home, message, touched, exc) from exc


def _project_bucket_for(home: Path, ref: str) -> Path | None:
    """Locate a project bucket by slug OR by (old) project path — the two
    things a human can still name once the repo itself has moved."""
    projects = home / "projects"
    by_slug = projects / ref
    if by_slug.is_dir() and by_slug.parent == projects:
        return by_slug
    by_path = projects / slug_for(ref)
    return by_path if by_path.is_dir() else None


def host_rebind(home: Path | str, ref: str, new_path: Path | str) -> Path:
    """``host rebind <slug-or-old-path> <new-path>`` (audit 2026-07-16
    MAJOR 5): a moved/renamed project used to strand its bucket behind an
    impossible command — the route refused with ``host not registered —
    self-learn host add /old/path``, and ``host add`` then refused because
    /old/path no longer exists. Rebind is the repair: it rewrites the
    bucket's ``meta.yaml``, RENAMES the bucket to the new path's slug (so
    later captures land in the same bucket instead of forking a second
    one), and rewrites the matching hosts.yaml entries — all in ONE ledger
    commit, pinned subject ``self-learn: host rebind <old> → <new>``.

    The MODE carries over from the old entry unchanged — rebind is a path
    move, never a mode change (that is ``host remove`` + ``host add
    --mode``, R-f).

    Returns the bucket's new directory. The new path is gate-validated
    (:func:`validate_host_path`, mode-aware); the OLD path is deliberately
    not — it is gone, that is the whole point.

    Lock discipline (audit 2026-07-16 round 7 BLOCKER 1 — the worst of the
    three): this verb ``git mv``s an ENTIRE project bucket, rewrites the
    moved bucket's meta.yaml and rewrites hosts.yaml, and it used to do
    all three BEFORE taking the lock. Probed: against a merely-held lock
    it exited 1 with a traceback and left the ledger holding a staged
    bucket-wide rename plus a modified hosts.yaml, uncommitted — which no
    other producer ever commits (every one of them pathspec-commits only
    its own paths), so the first non-FF push's ``pull --rebase
    --autostash`` destroys it. The lock now spans [git mv → commit]:
    every mutation of this verb is inside it."""
    from . import gitops

    home = Path(home)
    if not home.is_dir():
        raise HostsError(f"ledger home {home} does not exist")
    bucket = _project_bucket_for(home, ref)
    hosts = load_hosts(home)
    old_path: Path | None = None
    if bucket is not None:
        from .ledger_ops import bucket_project_path

        old_path = bucket_project_path(bucket)
    if old_path is None and not str(ref).startswith("-"):
        old_path = Path(ref).expanduser()
    if bucket is None and old_path is None:
        raise HostsError(
            f"no project bucket for {ref!r} — name its slug (see "
            "`self-learn status`) or its old absolute path"
        )
    old_mode = host_mode(home, old_path) if old_path is not None else "git"
    # U-hostmode M-12 (code gate r1 fold): `new_path` is unregistered by
    # definition (rebind is what registers it), so without `mode=`,
    # `validate_host_path`'s default registry lookup would read
    # "unregistered ⇒ git" regardless of `old_mode` — a plain host could
    # never be rebound to a repo-less directory. Rebind is a path move,
    # never a mode change (this docstring's own claim), so the OLD
    # entry's mode is exactly what the NEW path must be validated as.
    target = validate_host_path(home, new_path, "project", mode=old_mode)
    if old_path is not None and old_path.resolve() == target:
        raise HostsError(f"{target} is already this bucket's path — nothing to rebind")

    # Everything above this line is READ-ONLY (validation + lookups); the
    # refusals above are therefore honest "nothing was written" refusals.
    # Everything below MUTATES, so the lock opens here (BLOCKER 1).
    new_bucket = bucket
    if bucket is not None:
        new_bucket = home / "projects" / slug_for(target)
        if new_bucket != bucket and new_bucket.exists():
            raise HostsError(
                f"a bucket for {target} already exists ({new_bucket}) — "
                "merge it by hand; rebind never fuses two histories"
            )
    message = f"self-learn: host rebind {old_path or ref} → {target}"
    with gitops.commit_lock(home):  # BLOCKER 4 + round 7 BLOCKER 1
        touched: list[Path] = []
        if bucket is not None:
            # `new_bucket` was reassigned to a real `Path` above, under
            # this SAME `bucket is not None` condition on the SAME
            # never-reassigned `bucket` — provably not None here, but
            # pyright cannot correlate two variables' narrowing across
            # the statements in between; the assert documents the
            # invariant instead of leaving a live false-positive.
            assert new_bucket is not None
            if new_bucket != bucket:
                proc = gitops._git(  # noqa: SLF001 — same module family
                    home, "mv", str(bucket), str(new_bucket)
                )
                if proc.returncode != 0:  # untracked bucket: a plain move is fine
                    bucket.rename(new_bucket)
            _dump_meta(new_bucket, target)
            touched += [new_bucket, bucket]

        projects = [
            target
            if (old_path is not None and Path(p).resolve() == old_path.resolve())
            else p
            for p in hosts.projects
        ]
        if target not in projects and old_path is not None:
            # the old path was never registered (the stranded case) —
            # rebinding a bucket means naming its host: register the new one.
            projects.append(target)
        skills_root = hosts.skills_root
        skills_root_mode = hosts.skills_root_mode
        new_modes = dict(hosts.project_modes)
        if (
            old_path is not None
            and str(old_path.resolve()) in new_modes
            and (skills_root is None or Path(skills_root).resolve() != old_path.resolve())
        ):
            del new_modes[str(old_path.resolve())]
        if (
            skills_root is not None
            and old_path is not None
            and Path(skills_root).resolve() == old_path.resolve()
        ):
            skills_root = target
        elif old_mode != "git":
            new_modes[str(target.resolve())] = old_mode
        touched.append(
            save_hosts(
                home,
                Hosts(
                    skills_root=skills_root,
                    projects=projects,
                    skills_root_mode=skills_root_mode,
                    project_modes=new_modes,
                ),
            )
        )
        _commit_or_half_written(home, touched, message)
    return new_bucket if new_bucket is not None else target


def host_remove(home: Path | str, path: Path | str) -> Hosts:
    """``host remove <path>``: drop a registered host from hosts.yaml (one
    ledger commit, pinned subject ``self-learn: host remove <path>``). The
    bucket and its records are NEVER touched — deregistering a host closes
    the compile gate (H-3), it does not delete truth. Unlike ``host add``,
    the path is not gate-validated: removing an entry whose repo is GONE
    is exactly the case this serves.

    U-hostmode GATE5: for a plain host, the :data:`MARKER_FILENAME`
    marker is deliberately LEFT IN PLACE — deleting it would silently
    invalidate a re-add (the marker is the H-3 replacement guard, and
    ``host remove`` documents that only the compile gate closes, never
    the truth on disk).

    Lock before the first mutation (audit 2026-07-16 round 7 BLOCKER 1),
    like the other two: hosts.yaml is tracked."""
    from . import gitops

    home = Path(home)
    if not home.is_dir():
        raise HostsError(f"ledger home {home} does not exist")
    target = Path(path).expanduser().resolve()
    hosts = load_hosts(home)
    projects = [p for p in hosts.projects if Path(p).expanduser().resolve() != target]
    root = hosts.skills_root
    root_hit = root is not None and Path(root).expanduser().resolve() == target
    if len(projects) == len(hosts.projects) and not root_hit:
        raise HostsError(f"{target} is not a registered host — nothing to remove")
    new_modes = {k: v for k, v in hosts.project_modes.items() if k != str(target)}
    hosts = Hosts(
        skills_root=None if root_hit else root,
        projects=projects,
        skills_root_mode="git" if root_hit else hosts.skills_root_mode,
        project_modes=new_modes,
    )
    message = f"self-learn: host remove {target}"
    with gitops.commit_lock(home):  # BLOCKER 4 + round 7 BLOCKER 1
        yaml_path = save_hosts(home, hosts)
        _commit_or_half_written(home, [yaml_path], message)
    return hosts


def _dump_meta(bucket_dir: Path, project_path: Path) -> Path:
    from .ledger_ops import _dump_yaml

    bucket_dir.mkdir(parents=True, exist_ok=True)
    meta = bucket_dir / "meta.yaml"
    _dump_yaml({"path": str(Path(project_path).expanduser().resolve())}, meta)
    return meta


def skill_dir_for(hosts: Hosts, name: str) -> Path:
    """The HOST-side skill directory for ``skill:<name>`` — resolved by
    globbing ``plugins/*/skills/<name>`` under the registered skills root.
    Raises :class:`HostsError` when no root is registered, the skill is
    missing, or the name is ambiguous across plugins."""
    if hosts.skills_root is None:
        raise HostsError(
            "no skills root registered — self-learn host add <path> --skills-root"
        )
    matches = sorted(
        p for p in hosts.skills_root.glob(f"plugins/*/skills/{name}") if p.is_dir()
    )
    if not matches:
        raise HostsError(
            f"no skill named {name!r} under skills root {hosts.skills_root}"
        )
    if len(matches) > 1:
        raise HostsError(
            f"skill name {name!r} is ambiguous across plugins: "
            + ", ".join(str(m) for m in matches)
        )
    return matches[0]


def canon_read_roots(hosts: Hosts) -> list[Path]:
    """The pane charter's read-scope helper (09 §11 Y-2, built at 10 U0):
    given the registered host set, the CANON-SURFACE read prefixes — never
    a whole host repo (H-3's ``host add`` consents to compilers WRITING
    managed sections, not a model session reading an entire tree,
    untracked files included). Every returned path is ``resolve()``d
    (realpath-canonicalized); the pane callback matches candidate reads as
    path prefixes against this list — existence on disk is NOT required
    (a freshly-registered host's ``hooks/self-learn/`` may not exist yet,
    and that is still an allowed prefix for the guard the analyst is about
    to write there).

    Three families, all under the registered hosts (never
    ``SELF_LEARN_HOME`` or the plugin's own ``references/`` dir — those
    are the OTHER two roots of the three-root scope; a caller composes all
    three, this function owns only the host-derived ones):

    - skill trees under ``skills_root`` — ``plugins/*/skills/*/`` (each
      resolved existing skill directory; SKILL.md + its references live
      inside it);
    - the hook-canon dirs (13 §7.3/D1): ``<skills_root>/hooks/self-learn/``
      (project/user-scope guards; included even if not yet created) and
      each existing ``plugins/*/hooks/`` (skill-scope guards, one per
      plugin that has any);
    - each registered PROJECT host's compile-target files — its
      ``CLAUDE.md`` (the literal target ``verbs._resolve_target`` writes
      via ``host / "CLAUDE.md"``) and its whole ``references/`` dir (the
      literal ``host / "references"`` root ``verbs._resolve_target``'s
      ``reference`` branch resolves against — covers ``LEARNINGS.md`` and
      any other named reference file inside it; the compiler's own
      ``"references"`` literal is reused here rather than re-listing
      individual filenames).

    User scope is deliberately absent: its ``~/.claude/CLAUDE.md`` target
    stays excerpt-only in the pane's first message (Y-2), never a read
    root.
    """
    roots: list[Path] = []
    if hosts.skills_root is not None:
        root = hosts.skills_root.resolve()
        roots.extend(
            sorted(p.resolve() for p in root.glob("plugins/*/skills/*") if p.is_dir())
        )
        roots.append((root / HOOK_CANON_USER_DIR).resolve())
        roots.extend(
            sorted(p.resolve() for p in root.glob("plugins/*/hooks") if p.is_dir())
        )
    for project in hosts.projects:
        host = Path(project).resolve()
        roots.append((host / "CLAUDE.md").resolve())
        roots.append((host / "references").resolve())
    return roots


def ancestors_of(hosts: Hosts, path: Path | str) -> list[Path]:
    """U-ancestry §6.1: the registered project hosts that are PROPER
    resolved-path prefixes of ``path`` — never the target itself, never a
    sibling, never a descendant — ordered NEAREST-first (longest prefix
    first).

    Pure path arithmetic over the registered host set: no filesystem
    consultation beyond ``resolve()`` (no ``is_dir``, no read), no VCS
    boundary (measured, U-ancestry §2.3: Claude Code's ancestor walk
    crosses git roots — a derivation that stopped at one would model a
    rule that does not exist), and **derived, never persisted** — nothing
    here writes a byte anywhere; the relation is recomputed from
    ``hosts.yaml`` on every call, so ``host add``/``host remove`` changes
    it immediately (LOAD6).

    Both sides are ``Path.resolve()``d, matching how the real ancestor
    walk operates on the live cwd it is given (U-ancestry §6.1 note): a
    host reached only through a symlink whose realpath sits elsewhere is
    out of scope — not live on any registered host today."""
    target = Path(path).resolve()
    target_str = str(target)
    candidates = []
    for project in hosts.projects:
        candidate = Path(project).resolve()
        prefix = str(candidate) + os.sep
        if target_str.startswith(prefix):
            candidates.append(candidate)
    # Nearest-first: the longest matching prefix is the closest ancestor.
    candidates.sort(key=lambda p: len(str(p)), reverse=True)
    return candidates


def unregistered_ancestor_dirs(hosts: Hosts, path: Path | str) -> list[Path]:
    """U-ancestry §6.1: the content-free probe for doctrine §3's "an
    unregistered ancestor is a fact you tell the human, never something
    you register yourself" — directories strictly between ``path`` and
    its nearest REGISTERED ancestor (or the filesystem root, when there
    is none) that carry a ``CLAUDE.md`` or ``.claude/CLAUDE.md``.

    Returns PATHS ONLY — no caller may read the bytes of anything this
    reports (U-ancestry ANC5); this function itself never opens the
    ``CLAUDE.md``/``.claude/CLAUDE.md`` it detects, only
    :meth:`Path.is_file`s it. Ordered nearest-first, matching
    :func:`ancestors_of`."""
    target = Path(path).resolve()
    nearest = ancestors_of(hosts, target)
    floor = nearest[0] if nearest else Path(target.anchor)

    hits: list[Path] = []
    cur = target.parent
    while cur != floor and cur != cur.parent:
        if (cur / "CLAUDE.md").is_file() or (cur / ".claude" / "CLAUDE.md").is_file():
            hits.append(cur)
        cur = cur.parent
    return hits
