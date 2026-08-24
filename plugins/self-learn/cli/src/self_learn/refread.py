"""refread.py — U-readref §4.1.2: the ONE helper that owns the
reference-target key mapping. Both the emit side (this module's
:func:`emit_reference_read`, driven by the PostToolUse hook via
``telemetry read-observed``) and the aggregate side (``report.py``, via
``selfcheck._reference_target_for``) import :func:`resolve_ref_target` —
neither re-derives the key shape, and neither re-splits ``RefTarget.key``
to recover ``scope``/``bucket`` (§10.1's discharge; T9.2 is the source-level
test for the no-re-split rule).

Path normalization is MANDATORY (§4.1.1): ``.resolve()`` is applied to BOTH
the given absolute path and every candidate references directory before
any comparison — a build that compares unresolved strings is rejected
regardless of which tests pass (a symlinked ``~/.claude/skills/<name>`` is
the live case on this host; §7-T8 is the test).

The project-scope ``bucket`` component is the resolved path's 8-hex sha256
digest ALONE, never the readable slug (§5.2.1 — RULED). The digest is
computed independently here, the same way ``hosts.py::slug_for`` computes
its own digest suffix, rather than parsed back out of ``slug_for``'s
formatted string.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NamedTuple

from .hosts import HostsError, load_hosts
from .telemetry import spool_quiet

__all__ = ["RefTarget", "emit_reference_read", "resolve_ref_target"]


class RefTarget(NamedTuple):
    """The composite the mapping owns — §4.1.2's discharge of §10.1: the
    emit side reads ``scope``/``bucket`` off this tuple directly, it never
    re-splits ``key`` to recover them."""

    key: str  # "<scope>:<bucket>/references/<relpath>" — the `ref_target` field
    scope: str  # "skill" | "project"
    bucket: str  # skill name, or the project's 8-hex digest (§5.2.1)


def _project_digest(project_path: Path | str) -> str:
    """§5.2.1's RULING, verbatim construction: ``sha256(resolved path)``,
    first 8 hex chars — the same digest ``hosts.py::slug_for`` appends to
    its readable prefix, computed directly rather than parsed back out of
    that formatted string."""
    resolved = str(Path(project_path).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]


def _relative_key(resolved_path: Path, resolved_refs_dir: Path) -> str | None:
    """``resolved_path``'s POSIX-style path relative to ``resolved_refs_dir``,
    or None when it is not under that directory (or IS that directory —
    a references dir itself is never a read target)."""
    try:
        relpath = resolved_path.relative_to(resolved_refs_dir)
    except ValueError:
        return None
    rel = relpath.as_posix()
    if rel in ("", "."):
        return None
    return rel


def resolve_ref_target(home: Path | str, abs_path: Path | str) -> RefTarget | None:
    """Absolute path -> its :class:`RefTarget`, or None when the path is
    not under any registered references dir (§4.1.2).

    Applies ``.resolve()`` to BOTH ``abs_path`` and every candidate
    references directory before comparing (§4.1.1 — MANDATORY; a naive
    prefix comparison emits zero events forever through a symlinked skill
    dir, which is the live shape on this host). Skill candidates come from
    ``hosts.skills_root`` (every ``plugins/*/skills/<name>`` directory);
    project candidates come from ``hosts.projects`` (§2.4 — user scope has
    no references dir by design and is never a candidate here, S-23 (2)).

    Read-only: a missing/unreadable hosts.yaml, an unreadable candidate
    directory, or any OS-level resolution failure yields None rather than
    raising — this runs on the critical path of every reference-shaped
    Read (via the hook -> ``telemetry read-observed``), and must never
    break the call that reaches it (§5.2's ``spool_quiet`` rule, extended
    to resolution itself)."""
    home = Path(home)
    try:
        hosts = load_hosts(home)
    except HostsError:
        return None

    try:
        resolved_path = Path(abs_path).resolve()
    except OSError:
        return None

    if hosts.skills_root is not None:
        try:
            skill_dirs = sorted(
                p
                for p in hosts.skills_root.glob("plugins/*/skills/*")
                if p.is_dir()
            )
        except OSError:
            skill_dirs = []
        for skill_dir in skill_dirs:
            try:
                resolved_refs = (skill_dir / "references").resolve()
            except OSError:
                continue
            rel = _relative_key(resolved_path, resolved_refs)
            if rel is None:
                continue
            key = f"skill:{skill_dir.name}/references/{rel}"
            return RefTarget(key=key, scope="skill", bucket=skill_dir.name)

    for project_path in hosts.projects:
        try:
            resolved_refs = (Path(project_path) / "references").resolve()
        except OSError:
            continue
        rel = _relative_key(resolved_path, resolved_refs)
        if rel is None:
            continue
        digest = _project_digest(project_path)
        key = f"project:{digest}/references/{rel}"
        return RefTarget(key=key, scope="project", bucket=digest)

    return None


def emit_reference_read(
    home: Path | str,
    *,
    abs_path: str,
    session: str,
    subagent: bool,
) -> RefTarget | None:
    """Resolve ``abs_path`` and, iff it names a registered references
    target, spool one ``reference-read`` event (§5.2). Returns the
    resolved target (for callers that want it), or None when nothing was
    emitted — an unresolvable path emits nothing and is not an error
    (§4.1, T2.6).

    Emitted through ``telemetry.spool_quiet`` only, per §5.2 — never
    ``spool_event`` — so a spool failure never breaks this call, which
    sits on the critical path of every reference-shaped Read."""
    target = resolve_ref_target(home, abs_path)
    if target is None:
        return None
    spool_quiet(
        "reference-read",
        ref_target=target.key,
        scope=target.scope,
        bucket=target.bucket,
        subagent=bool(subagent),
        session=session,
    )
    return target
