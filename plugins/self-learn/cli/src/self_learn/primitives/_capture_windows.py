"""Native integration between the capture ledger, NTFS and Git for Windows."""

from __future__ import annotations

import os
from pathlib import Path

from . import names, procs

if os.name != "nt":
    raise NotImplementedError("native Windows capture requires Windows")


def checked_path(root: Path, candidate: Path) -> Path:
    """Validate every component starting at the caller's selected root, before I/O."""
    relative = candidate.relative_to(root)
    if not relative.parts:
        raise ValueError(f"expected a child of {root}")
    current = root
    for component in relative.parts:
        current = names.component_path(current, component)
    return current


def git_bytes(repo: Path, *args: str, timeout: float) -> bytes:
    from ..gitops import GitOpsError

    proc = procs.run_bounded(["git.exe", "-C", str(repo), *args], binary=True, timeout=timeout)
    if proc.returncode:
        raise GitOpsError(proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout


def git_argv(repo: Path, args: tuple[str, ...]) -> list[str]:
    """The capture callers pass file operands after --. check-ignore uses plain names."""
    argv = ["git.exe", "-C", str(repo)]
    if "--" not in args:
        return [*argv, *args]
    split = args.index("--")
    if "check-ignore" in args[:split]:
        return [*argv, *args[:split + 1], *(names.git_arg(repo, p, literal=False) for p in args[split + 1:])]
    if "--literal-pathspecs" not in args[:split]:
        argv.append("--literal-pathspecs")
    return [*argv, *args[:split + 1], *(names.git_arg(repo, path) for path in args[split + 1:])]


def status_paths(repo: Path, *, timeout: float):
    from ._names_windows import porcelain_paths

    return porcelain_paths(repo, git_bytes(repo, "status", "--porcelain=v1", "-z", "-uall", timeout=timeout))
