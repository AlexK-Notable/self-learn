"""Compile-host registry (doc 13 §3, T-H3): hosts.yaml in the ledger home.

The ledger home holds ONLY ledger data; canon is compiled into HOST repos
that must be registered here first (invariant H-3: compile targets come
from hosts.yaml only — capture is open, canon is registered; no autonomous
process ever writes to an unregistered repo). One file to read to know
where canon may land:

    skills_root: /home/komi/repos/claude-skills   # plugins/*/skills/* live here
    projects:
      - path: /home/komi/repos/claude-skills      # CLAUDE.md targets

Registration is a CLI verb (``self-learn host add <path> [--skills-root]``),
never a hand edit the compilers trust blindly — :func:`host_add` validates
the path (must exist, must be a git repo), rewrites hosts.yaml, and commits
it in the ledger repo with the pinned subject
``self-learn: host add <kind> <path>``.

Slugs: :func:`slug_for` mirrors Claude Code's ``~/.claude/projects``
convention — ``str(resolved path).replace("/", "-")`` — so a leading ``-``
is correct, and the miner's transcript project dirs map onto ledger
project buckets by construction.
"""

from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import gitops

__all__ = [
    "HOST_KINDS",
    "Hosts",
    "HostsError",
    "host_add",
    "hosts_path",
    "is_project_host",
    "load_hosts",
    "save_hosts",
    "skill_dir_for",
    "slug_for",
]

HOST_KINDS = ("skills-root", "project")


class HostsError(Exception):
    """hosts.yaml is malformed, or a registration was refused."""


@dataclass(frozen=True)
class Hosts:
    """The parsed registry: one optional skills root + registered projects."""

    skills_root: Path | None = None
    projects: list[Path] = field(default_factory=list)


def slug_for(path: Path | str) -> str:
    """Claude Code's projects-dir slug: resolved path, ``/`` → ``-``.
    The leading ``-`` (from the root slash) is deliberate and correct."""
    return str(Path(path).resolve()).replace("/", "-")


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
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def host_add(home: Path | str, path: Path | str, kind: str) -> Hosts:
    """The ``host add`` verb's backing function (doc 13 §3): validate the
    path (must exist, must be a git repo), rewrite hosts.yaml, and commit
    it in the LEDGER repo — pinned subject
    ``self-learn: host add <kind> <path>``. Idempotent: re-adding an
    already-registered host changes nothing and commits nothing."""
    home = Path(home)
    if kind not in HOST_KINDS:
        raise HostsError(f"kind must be one of {list(HOST_KINDS)}, got {kind!r}")
    if not home.is_dir():
        raise HostsError(f"ledger home {home} does not exist")
    target = Path(path).expanduser()
    if not target.is_dir():
        raise HostsError(f"host path {target} does not exist (or is not a directory)")
    target = target.resolve()
    if not _is_git_repo(target):
        raise HostsError(
            f"host path {target} is not a git repo — canon hosts must be "
            "committable (doc 13 §4 two-phase routing)"
        )

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

    yaml_path = save_hosts(home, hosts)
    gitops.stage(home, [yaml_path])
    gitops.commit(home, f"self-learn: host add {kind} {target}")
    return hosts


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
