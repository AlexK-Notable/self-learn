"""Native integration between the capture ledger, NTFS and Git for Windows."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import names, procs


class CapturePathError(ValueError):
    """Cannot establish a safe, unambiguous local capture path."""


def checked_path(root: Path, candidate: Path) -> Path:
    """Validate every component starting at the caller's selected root, before I/O."""
    try:
        relative = candidate.relative_to(root)
        if not relative.parts:
            raise ValueError(f"expected a child of {root}")
        current = root
        for component in relative.parts:
            current = names.component_path(current, component)
    except ValueError as exc:
        raise CapturePathError(str(exc)) from exc
    return current


def verify_project(home: Path, project: Path) -> None:
    """Before a write or plain-host lock, check any existing bucket's claim."""
    from ..ledger_ops import bucket_project_path

    bucket = home / "projects" / names.project_slug(project)
    checked_path(home, bucket / "meta.yaml")
    if (bucket / "meta.yaml").exists():
        recorded = bucket_project_path(bucket)
        if recorded is None or names.registration_key(recorded) != names.registration_key(project):
            raise CapturePathError(f"cannot verify the registered project in {bucket}")


def local_registry(data: dict, *, for_write: bool) -> dict:
    """A foreign absolute path must never become relative to the current drive."""
    def foreign(entry):
        value = entry.get("path") if isinstance(entry, dict) else entry
        return isinstance(value, str) and value and not Path(value).is_absolute()

    projects = data.get("projects")
    local_projects = [entry for entry in projects if not foreign(entry)] if isinstance(projects, list) else projects
    foreign_root = foreign(data.get("skills_root"))
    if not foreign_root and local_projects == projects:
        return data
    if for_write:
        raise CapturePathError("hosts.yaml contains paths without a local Windows drive or share")
    local = dict(data)
    if foreign_root:
        local["skills_root"] = None
    if isinstance(projects, list):
        local["projects"] = local_projects
    return local


def git_bytes(repo: Path, *args: str, timeout: float, data: bytes | None = None) -> bytes:
    from ..gitops import GitOpsError

    try:
        proc = procs.run_bounded(["git.exe", "-C", str(repo), *args], binary=True, timeout=timeout, input=data)
    except subprocess.TimeoutExpired as exc:
        raise GitOpsError(f"git {args[0]} in {repo} exceeded {timeout:g}s and was killed") from exc
    except OSError as exc:
        raise GitOpsError(f"git {args[0]} in {repo}: {exc}") from exc
    if proc.returncode:
        raise GitOpsError(proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout


def git_operand(repo: Path, path: Path | str) -> str:
    from ..gitops import GitOpsError

    try:
        return names.git_arg(repo, path)
    except (ValueError, OSError) as exc:
        raise GitOpsError(f"invalid Git path {str(path)!r} in {repo}: {exc}") from exc


def git_argv(repo: Path, args: tuple[str, ...]) -> list[str]:
    """The capture callers pass file operands after --. check-ignore uses plain names."""
    argv = ["git.exe", "-C", str(repo)]
    # Skip the global switches and option arguments used by capture. A
    # commit subject/body can literally be "--" or "check-ignore".
    index = 0
    while index < len(args) and args[index] in ("-c", "--literal-pathspecs"):
        index += 2 if args[index] == "-c" else 1
    command = args[index] if index < len(args) else None
    split = index + 1
    while split < len(args) and args[split] != "--":
        split += 2 if args[split] in ("-m", "--message") else 1
    if split >= len(args):
        return [*argv, *args]
    if command == "check-ignore":
        # The excludes probe can ask about a synthetic name ending in a
        # space. Validate its local path first, then restore those spaces.
        plain = []
        for operand in args[split + 1:]:
            name = operand.rstrip(" ")
            plain.append(git_operand(repo, name) + operand[len(name):])
        return [*argv, *args[:split + 1], *plain]
    if False:  # MUTANT M1
        argv.append("--literal-pathspecs")
    return [*argv, *args[:split + 1], *(git_operand(repo, path) for path in args[split + 1:])]


def status_paths(repo: Path, *, timeout: float):
    if os.name != "nt":
        raise NotImplementedError("native Windows capture requires Windows")
    from ._names_windows import porcelain_paths

    return porcelain_paths(repo, git_bytes(repo, "status", "--porcelain=v1", "-z", "-uall", timeout=timeout))
