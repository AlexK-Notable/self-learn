"""Compile-host registry (doc 13 §3, T-H3): hosts.yaml in the ledger home.

The ledger home holds ONLY ledger data; canon is compiled into HOST repos
that must be registered here first (invariant H-3: compile targets come
from hosts.yaml only — capture is open, canon is registered; no autonomous
process ever writes to an unregistered repo). One file to read to know
where canon may land:

    skills_root: /home/user/repos/claude-skills   # plugins/*/skills/* live here
    projects:
      - path: /home/user/repos/claude-skills      # CLAUDE.md targets

Registration is a CLI verb (``self-learn host add <path> [--skills-root]``,
``host rebind <slug-or-old-path> <new-path>``, ``host remove <path>``),
never a hand edit the compilers trust blindly — :func:`host_add` validates
the path (must exist, must be a git repo), rewrites hosts.yaml, and commits
it in the ledger repo with the pinned subject
``self-learn: host add <kind> <path>``.

Validation is at the GATE, not only at registration (audit 2026-07-16:
``load_hosts`` trusted a hand-edited hosts.yaml blindly, so a typo'd
``skills_root: /home/user/repos`` would CREATE ``/home/user/repos/
CLAUDE.md`` — canon written outside any repo — and only then fail its
commit). :func:`validate_host_path` is the one gate predicate; every
canon-writing path runs it (``verbs._resolve_target``), while
:func:`load_hosts` stays lenient so ``host list`` can SHOW a broken entry
marked broken instead of exploding.

Slugs: :func:`slug_for` keeps Claude Code's ``~/.claude/projects``
readable shape — ``str(resolved path).replace("/", "-")`` — and appends
``-<sha256(resolved)[:8]>`` (audit 2026-07-16 BLOCKER: the readable shape
ALONE is ambiguous — ``/w/a-b`` and ``/w/a/b`` both slug to ``-w-a-b``,
cross-homing one project's lessons into another project's canon). The
hash is taken over the resolved path string, so the slug is stable per
path and collision-free in practice; the readable prefix survives for
humans reading ``projects/``.
"""

from __future__ import annotations

import hashlib
import io
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import gitops

__all__ = [
    "HOST_KINDS",
    "INIT_COMMIT_SUBJECT",
    "Hosts",
    "HostsError",
    "canon_read_roots",
    "host_add",
    "host_rebind",
    "host_remove",
    "host_path_problem",
    "hosts_path",
    "is_project_host",
    "is_repo_root",
    "load_hosts",
    "save_hosts",
    "skill_dir_for",
    "slug_for",
    "validate_host_path",
]

#: 13 §7.3/D1: the guard-canon dir for project/user-scope hook records,
#: relative to the registered skills root.
HOOK_CANON_USER_DIR = "hooks/self-learn"

HOST_KINDS = ("skills-root", "project")


class HostsError(Exception):
    """hosts.yaml is malformed, or a registration was refused."""


@dataclass(frozen=True)
class Hosts:
    """The parsed registry: one optional skills root + registered projects."""

    skills_root: Path | None = None
    projects: list[Path] = field(default_factory=list)


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


def hosts_path(home: Path | str) -> Path:
    return Path(home) / "hosts.yaml"


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.default_flow_style = False
    return y


def load_hosts(home: Path | str) -> Hosts:
    """Parse ``<home>/hosts.yaml``. A missing file is an EMPTY registry
    (nothing registered — every compile gate refuses), never an error;
    a malformed file raises :class:`HostsError` with the exact complaint."""
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
    if raw_root is not None and not isinstance(raw_root, str):
        raise HostsError(f"{path}: skills_root must be a path string, got {raw_root!r}")
    skills_root = Path(raw_root).expanduser() if raw_root else None

    projects: list[Path] = []
    raw_projects = data.get("projects")
    if raw_projects is not None:
        if not isinstance(raw_projects, list):
            raise HostsError(f"{path}: projects must be a list, got {raw_projects!r}")
        for i, entry in enumerate(raw_projects):
            if isinstance(entry, str) and entry.strip():
                projects.append(Path(entry).expanduser())
            elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
                projects.append(Path(entry["path"]).expanduser())
            else:
                raise HostsError(
                    f"{path}: projects[{i}] must be a path string or a "
                    f"{{path: <str>}} mapping, got {entry!r}"
                )
    return Hosts(skills_root=skills_root, projects=projects)


def save_hosts(home: Path | str, hosts: Hosts) -> Path:
    """Serialize the registry back to ``<home>/hosts.yaml`` (canonical
    shape: ``skills_root`` scalar + ``projects`` list of path mappings)."""
    path = hosts_path(home)
    data = {
        "skills_root": str(hosts.skills_root) if hosts.skills_root else None,
        "projects": [{"path": str(p)} for p in hosts.projects],
    }
    buf = io.StringIO()
    _yaml().dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def is_project_host(hosts: Hosts, path: Path | str) -> bool:
    """True iff *path* (resolved) is a registered project host."""
    target = Path(path).resolve()
    return any(Path(p).resolve() == target for p in hosts.projects)


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
    (kind validity, ledger-home existence — F6: an invalid invocation
    must never leave an initialized repo behind) and BEFORE
    :func:`validate_host_path`.

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


def host_path_problem(home: Path | str, path: Path | str, kind: str) -> str | None:
    """The ONE host-path predicate (audit 2026-07-16 MAJOR 6): a host path
    must exist on disk, be a git repo, and MUST NOT be the ledger home
    itself (the ledger holds ledger data; canon compiled into it would
    make the source of truth its own host — doc 13 §2's three layers).
    Returns a human sentence naming the offending entry and the verb that
    fixes it, or None when the entry is sound.

    Used at registration (:func:`host_add`) AND at every canon-writing
    gate (``verbs._resolve_target``) — hosts.yaml is data, and data that
    only gets checked when it is written is data nobody checks."""
    target = Path(path).expanduser()
    label = f"{kind} host {target}"
    if not target.is_dir():
        return (
            f"{label} does not exist on disk — the repo moved or was "
            f"removed; re-point it with `self-learn host rebind {target} "
            "<new-path>` (or `self-learn host remove` it)"
        )
    target = target.resolve()
    if not _is_git_repo(target):
        return (
            f"{label} is not a git repo — canon hosts must be committable "
            "(doc 13 §4 two-phase routing); fix hosts.yaml via "
            "`self-learn host add` / `host rebind`"
        )
    if Path(home).expanduser().resolve() == target:
        return (
            f"{label} IS the ledger home — the ledger is the source of "
            "truth, never a canon host (doc 13 §2); re-point it with "
            "`self-learn host rebind` or remove the entry"
        )
    return None


def validate_host_path(home: Path | str, path: Path | str, kind: str) -> Path:
    """:func:`host_path_problem` as a gate: raise :class:`HostsError` on a
    bad entry, else return the resolved path."""
    problem = host_path_problem(home, path, kind)
    if problem is not None:
        raise HostsError(problem)
    return Path(path).expanduser().resolve()


def host_add(
    home: Path | str, path: Path | str, kind: str, *, init: bool = False
) -> Hosts:
    """The ``host add`` verb's backing function (doc 13 §3): validate the
    path (must exist, must be a git repo), rewrite hosts.yaml, and commit
    it in the LEDGER repo — pinned subject
    ``self-learn: host add <kind> <path>``. Idempotent: re-adding an
    already-registered host changes nothing and commits nothing.

    ``init`` (09 §11 Y-17, 2026-07-18): run the ``--init`` leg
    (:func:`_init_for_registration`) between the pure-argument refusals
    and the path validation — validation ordering is normative (F6): the
    read-only kind/ledger-home refusals FIRST (an invalid kind must
    never leave an initialized repo behind), then init, then the path
    validation + idempotency exactly as they run today. Without
    ``init``, behavior is byte-unchanged.

    Lock discipline (audit 2026-07-16 round 7 BLOCKER 1): the lock opens
    BEFORE :func:`save_hosts`, not at the commit. hosts.yaml is TRACKED,
    so a rewrite of it is exactly what a racing ``pull --rebase
    --autostash`` stashes and then restores into a conflict — the same
    window round 3 closed in ``verbs.py`` and left open here."""
    home = Path(home)
    if kind not in HOST_KINDS:
        raise HostsError(f"kind must be one of {list(HOST_KINDS)}, got {kind!r}")
    if not home.is_dir():
        raise HostsError(f"ledger home {home} does not exist")
    if init:
        _init_for_registration(path)
    target = validate_host_path(home, path, kind)

    hosts = load_hosts(home)
    if kind == "skills-root":
        if hosts.skills_root is not None and hosts.skills_root.resolve() == target:
            return hosts  # already registered — nothing to do
        hosts = Hosts(skills_root=target, projects=hosts.projects)
    else:
        if is_project_host(hosts, target):
            return hosts  # already registered — nothing to do
        hosts = Hosts(
            skills_root=hosts.skills_root, projects=[*hosts.projects, target]
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

    Returns the bucket's new directory. The new path is gate-validated
    (:func:`validate_host_path`); the OLD path is deliberately not — it is
    gone, that is the whole point.

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
    target = validate_host_path(home, new_path, "project")
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
        if (
            skills_root is not None
            and old_path is not None
            and Path(skills_root).resolve() == old_path.resolve()
        ):
            skills_root = target
        touched.append(
            save_hosts(home, Hosts(skills_root=skills_root, projects=projects))
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
    hosts = Hosts(skills_root=None if root_hit else root, projects=projects)
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
