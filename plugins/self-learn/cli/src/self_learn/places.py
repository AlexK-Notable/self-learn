"""Plain names for ledger buckets (w33-humane lane 0, S-135).

A bucket's directory name is a slug ("-home-user-repos-project-8c7fedb5")
that no person reads easily. :func:`bucket_places` gives every bucket a
``label`` a person recognises, the ``path`` it compiles into (written from
``~`` when under the home directory), and whether that path still exists,
so a page can fold away buckets of folders that are gone (old worktrees).

Read-only: it reads each project bucket's ``meta.yaml`` and stats the
recorded path; it writes nothing.
"""

from __future__ import annotations

from pathlib import Path

from .ledger import Bucket

__all__ = ["USER_LABEL", "bucket_places", "display_path"]

#: The user bucket's label: it compiles into the user's own instructions
#: (`~/.claude/CLAUDE.md`, rules and hooks).
USER_LABEL = "Your instructions"
_USER_PATH = "~/.claude"
_WORKTREE_PART = "/.claude/worktrees/"


def display_path(path: Path | str) -> str:
    """*path* as ``~/…`` when it is under the home directory, else as it is."""
    p = Path(path)
    try:
        rel = p.relative_to(Path.home())
    except ValueError:
        return str(p)
    return "~" if str(rel) == "." else "~/" + str(rel)


def _project_label(path: Path) -> str:
    text = str(path)
    if _WORKTREE_PART in text:
        repo, _, rest = text.partition(_WORKTREE_PART)
        name = rest.split("/", 1)[0]
        return f"{Path(repo).name} (worktree {name})"
    return path.name or text


def bucket_places(buckets: list[Bucket]) -> dict[tuple[str, str], dict]:
    """``{(scope, name): {"label", "path", "path_exists"}}`` for *buckets*.

    - user: ``label`` "Your instructions", ``path`` "~/.claude".
    - skill: ``label`` the skill's name, ``path`` None (a skill's folder
      is found through the skills root at compile time, not recorded on
      the bucket), ``path_exists`` None.
    - project: ``label`` the folder's name ("self-learn"); a worktree reads
      "<repo> (worktree <name>)"; when two projects would share a label,
      both use their ``~`` path instead. ``path`` is the recorded path in
      ``~`` form; ``path_exists`` whether it is a directory now. With no
      readable ``meta.yaml``: ``label`` is the slug, ``path`` None,
      ``path_exists`` False.
    """
    from .ledger_ops import bucket_project_path  # deferred: heavy module

    out: dict[tuple[str, str], dict] = {}
    project_rows: list[tuple[Bucket, Path | None]] = []
    for bucket in buckets:
        key = (bucket.scope, bucket.name)
        if bucket.scope == "user":
            out[key] = {"label": USER_LABEL, "path": _USER_PATH, "path_exists": True}
        elif bucket.scope == "skill":
            out[key] = {"label": bucket.name, "path": None, "path_exists": None}
        else:
            project_rows.append((bucket, bucket_project_path(bucket.path)))
    labels: dict[str, int] = {}
    for _bucket, recorded in project_rows:
        if recorded is not None:
            label = _project_label(recorded)
            labels[label] = labels.get(label, 0) + 1
    for bucket, recorded in project_rows:
        key = (bucket.scope, bucket.name)
        if recorded is None:
            out[key] = {"label": bucket.name, "path": None, "path_exists": False}
            continue
        label = _project_label(recorded)
        shown = display_path(recorded)
        out[key] = {
            "label": shown if labels.get(label, 0) > 1 else label,
            "path": shown,
            "path_exists": recorded.is_dir(),
        }
    return out
