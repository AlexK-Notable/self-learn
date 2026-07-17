"""The pane permission surface (09 §4.3 / 09 §11 Y-2; 10 §1's pane-engine
construction row): builds the ``can_use_tool`` callback the sdk engine
hands to ``ClaudeAgentOptions``.

**Deny-by-default.** Every branch below either explicitly ALLOWs or falls
through to a DENY with a reason string; there is no code path that grants
access by omission.

**Reads** (``Read``/``Grep``/``Glob``) are allowed under exactly three
roots, each resolved and realpath-canonicalized once at callback-build
time (09 §11 Y-2):

1. the resolved ``SELF_LEARN_HOME`` tree (the ledger),
2. each registered host's **canon surfaces only** — enumerated by the
   CLI-owned ``self_learn.hosts.canon_read_roots()`` helper, imported
   through a thin indirection (:func:`default_canon_read_roots`) so
   tests can inject a fake. The real helper lands on the ``g3-u0``
   branch, not this one — until that branch merges, the indirection's
   import fails and the charter **fails closed** (raises
   :class:`CanonReadRootsUnavailable`), never widening scope to
   compensate,
3. the plugin ``references/`` dir, resolved relative to the ui
   package's own installed location (:func:`self_learn_ui.doctrine.
   plugin_references_dir`) — never via ``SELF_LEARN_HOME``.

Reads inside ``cwd`` (the bucket root) never reach this callback at all —
probe 2's empirical finding, carried in 09 §4.3: the SDK auto-approves
them before the callback runs. Every read that DOES reach this callback
is therefore, by construction, a read the caller wants OUTSIDE the item's
own bucket subtree.

**Writes** are exact-file, id-siblings-only (09 §4.3, P3-7): ``Edit``
(never ``Write`` — the resurrection vector) on the item's own
``pending/lrn-<id>.md``, and ``Write``/``Edit`` on its own
``proposals/lrn-<id>.yaml`` / ``proposals/lrn-<id>.diff``. No wildcards
beyond the id's own siblings; a proposal for a DIFFERENT id in the same
bucket is denied exactly like a file in a different bucket.

Every path — read or write — is canonicalized via ``Path.resolve()``
(which resolves symlinks) BEFORE matching, closing the symlink-escape
vector: a symlink planted at an allowed-looking path but pointing outside
every permitted root resolves to its real target and is judged on that.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    CanUseTool,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ..doctrine import plugin_references_dir

__all__ = [
    "CanonReadRootsUnavailable",
    "CharterPaths",
    "build_can_use_tool",
    "default_canon_read_roots",
]

#: Tools whose permission decision is a READ-scope decision (09 §4.3).
_READ_TOOLS = frozenset({"Read", "Grep", "Glob"})

#: tool_input keys that may carry the target path, checked in this order
#: (Read/NotebookRead use file_path; Grep/Glob use path when the caller
#: names one explicitly — and only an explicitly-named path ever reaches
#: this callback at all, since a cwd-relative/absent path auto-approves
#: before the callback runs — probe 2).
_PATH_KEYS = ("file_path", "path", "notebook_path")


class CanonReadRootsUnavailable(RuntimeError):
    """``self_learn.hosts.canon_read_roots()`` could not be imported.

    Raised instead of falling back to a wider (or empty-but-silent) read
    scope — 09 §11 Y-2's fail-closed rule. This is the EXPECTED state on
    this branch (``g3-u5``) until ``g3-u0`` lands ``canon_read_roots()``
    in ``self_learn.hosts``; it resolves automatically once the branches
    merge, with no code change required here.
    """


def default_canon_read_roots() -> list[Path]:
    """Thin indirection over ``self_learn.hosts.canon_read_roots()`` (09
    §11 Y-2 root 2) — imported lazily, at call time, so a worktree that
    hasn't merged ``g3-u0`` yet doesn't fail at *module import* time, only
    when a pane session actually needs the root list. Tests never call
    this — they inject a fake root-list callable into
    :func:`build_can_use_tool` instead.
    """
    try:
        from self_learn.hosts import canon_read_roots  # type: ignore[attr-defined]
    except ImportError as exc:
        raise CanonReadRootsUnavailable(
            "self_learn.hosts.canon_read_roots() is not available on this "
            "branch yet (lands with g3-u0) — the pane charter fails CLOSED "
            "rather than widen its read scope to compensate. Once g3-u0 "
            "merges, this resolves with no code change here."
        ) from exc
    return [Path(root).resolve() for root in canon_read_roots()]


@dataclass(frozen=True)
class CharterPaths:
    """The three canonicalized read roots plus the item's own write
    targets — computed once per session start (09 §11 Y-2: "each
    resolved and realpath-canonicalized at session start")."""

    read_roots: tuple[Path, ...]
    record_path: Path
    proposal_yaml_path: Path
    proposal_diff_path: Path


def _resolve_charter_paths(
    *,
    self_learn_home: Path,
    bucket_root: Path,
    record_id: str,
    canon_read_roots_fn: Callable[[], Iterable[Path | str]],
    plugin_references_dir_fn: Callable[[], Path],
) -> CharterPaths:
    home_root = Path(self_learn_home).resolve()
    canon_roots = tuple(Path(root).resolve() for root in canon_read_roots_fn())
    refs_root = plugin_references_dir_fn().resolve()
    bucket = Path(bucket_root).resolve()

    # Deliberately NOT ``.resolve()``d past the (trusted) bucket root: the
    # write-target paths below are the CANONICAL reference point a
    # request is judged against, and resolving them would follow any
    # symlink an attacker planted AT that exact filename, silently
    # rebasing the "expected" path onto wherever the symlink points —
    # defeating the check for the one case it exists to catch. Only the
    # REQUESTED path (the model-supplied, untrusted ``tool_input``) gets
    # the full symlink-following ``.resolve()``, in the callback below.
    read_roots = (home_root, *canon_roots, refs_root)
    return CharterPaths(
        read_roots=read_roots,
        record_path=bucket / "pending" / f"lrn-{record_id}.md",
        proposal_yaml_path=bucket / "proposals" / f"lrn-{record_id}.yaml",
        proposal_diff_path=bucket / "proposals" / f"lrn-{record_id}.diff",
    )


def _under_any(target: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        if target == root or target.is_relative_to(root):
            return True
    return False


def _extract_target_path(tool_input: dict[str, Any]) -> str | None:
    for key in _PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def build_can_use_tool(
    *,
    self_learn_home: Path,
    bucket_root: Path,
    record_id: str,
    canon_read_roots_fn: Callable[[], Iterable[Path | str]] = default_canon_read_roots,
    plugin_references_dir_fn: Callable[[], Path] = plugin_references_dir,
) -> CanUseTool:
    """Build the ``can_use_tool`` callback for one pane session.

    Resolves the three read roots and the item's own write-target paths
    ONCE (at build time — "session start" per Y-2), then returns a closure
    that judges every subsequent tool call against that frozen
    :class:`CharterPaths`. Raises :class:`CanonReadRootsUnavailable`
    immediately (before returning a callback) if the canon-surface helper
    can't be resolved — a session that can't establish its read scope
    must never start with a silently narrower (or wider) one.
    """
    paths = _resolve_charter_paths(
        self_learn_home=self_learn_home,
        bucket_root=bucket_root,
        record_id=record_id,
        canon_read_roots_fn=canon_read_roots_fn,
        plugin_references_dir_fn=plugin_references_dir_fn,
    )

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        if tool_name in _READ_TOOLS:
            raw_target = _extract_target_path(tool_input)
            if raw_target is None:
                return PermissionResultDeny(
                    message=(
                        "self-learn pane charter: could not determine a target "
                        f"path for this {tool_name} call — denied by default"
                    )
                )
            target = Path(raw_target).resolve()
            if _under_any(target, paths.read_roots):
                return PermissionResultAllow()
            return PermissionResultDeny(
                message=(
                    "self-learn pane charter: reads are limited to the ledger "
                    "tree, registered hosts' canon surfaces, and the plugin "
                    f"references dir — {target} is outside all three. Ask "
                    "the human if you need this file."
                )
            )

        if tool_name == "Edit" and Path(
            tool_input.get("file_path", "")
        ).resolve() == paths.record_path:
            return PermissionResultAllow()

        if tool_name in ("Write", "Edit"):
            candidate = Path(tool_input.get("file_path", "")).resolve()
            if candidate in (paths.proposal_yaml_path, paths.proposal_diff_path):
                return PermissionResultAllow()

        return PermissionResultDeny(
            message=(
                f"self-learn pane charter: {tool_name} is outside the pane's "
                "permitted surface — it may only edit this record's own "
                "pending record and proposal files. Denied by default."
            )
        )

    return can_use_tool
