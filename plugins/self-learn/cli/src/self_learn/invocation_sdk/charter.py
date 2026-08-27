"""U-sdk §3.6 `Charter-1` — the SDK's `can_use_tool` permission callback.

This is the security surface and the only genuinely new code in the
unit: CLI-shaped containment is write-glob shaped, not record-file
shaped (`D-11`, `C-2` -- no CLI surface scopes reads by path, so the
UI's read-root apparatus does not port). Ports the UI charter's
deny-by-default structure and its asymmetric resolve VERBATIM, including
the comment (`P-b`).

Import-bounded (§3.1's table): stdlib, `claude_agent_sdk` (permission
types only), `..invocation.contract` (`Containment`). This module never
imports `.events` -- denial RECORDING is `backend.py`'s job (it wraps
the callback this module returns); denial DECISIONS are this module's
job alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    CanUseTool,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ..invocation.contract import Containment
from ..sdksession.toolpaths import TARGET_PATH_KEYS as P
from ..sdksession.toolpaths import extract_target_path as _extract_target_path

__all__ = ["CharterPaths", "CharterPatternUnsupported", "build_can_use_tool"]

#: `C-1` -- the write family, defined once.
W = frozenset({"Write", "Edit", "NotebookEdit"})

_UNSUPPORTED_CHARS = ("[", "]", "{", "}")


class CharterPatternUnsupported(ValueError):
    """`C-7` -- a `write_glob`/`write_exact` pattern used a metacharacter
    this matcher does not implement. Raised BEFORE `build_can_use_tool`
    returns a callback -- guessing at an unimplemented character class
    risks widening the boundary; refusing to start is the only safe
    direction (mirrors `charter.py`'s `CanonReadRootsUnavailable`
    fail-closed discipline)."""


@dataclass(frozen=True)
class CharterPaths:
    """The precomputed write-scope matchers (`C-5`). Each pattern's
    trusted prefix is resolved exactly ONCE, at callback-build time; the
    wildcard tail (or, for an exact path, the final segment) is kept
    verbatim and is never resolved -- that leaf is exactly where a
    planted symlink would rebase the expectation (`P-b`)."""

    glob_patterns: tuple[re.Pattern[str], ...]
    exact_paths: tuple[Path, ...]


def _split_trusted_prefix(pattern: str) -> tuple[str, str]:
    """`C-5` -- the trusted prefix is the longest leading run of '/'
    segments containing NEITHER '*' nor '?'; the remaining segments are
    re-joined verbatim, unresolved."""
    segments = pattern.split("/")
    idx = 0
    while idx < len(segments) and "*" not in segments[idx] and "?" not in segments[idx]:
        idx += 1
    prefix = "/".join(segments[:idx])
    remainder = "/".join(segments[idx:])
    return prefix, remainder


def _check_supported(pattern: str) -> None:
    """`C-7` -- fail closed on a metacharacter this matcher does not
    implement."""
    if pattern.startswith("!") or any(ch in pattern for ch in _UNSUPPORTED_CHARS):
        raise CharterPatternUnsupported(
            f"self-learn invocation charter: unsupported pattern metacharacter in {pattern!r}"
        )


def _translate_remainder(remainder: str) -> str:
    """`C-6` -- the CLI's gitignore-flavored `**` translated to a regex,
    per this table:

    - `**` as a WHOLE segment, anywhere but the very end of the pattern:
      zero-or-more full segments (`(?:.*/)?`, and the following literal
      '/' is folded into the group rather than re-emitted).
    - `**` as a whole segment AND the last thing in the pattern (a
      pattern ending in `/**`): one-or-more characters (`.+`) -- matches
      paths INSIDE the directory, never the directory itself.
    - `**` embedded inside a larger segment: crosses separators (`.*`).
    - `*` -- `[^/]*` (within one segment). `?` -- `[^/]` (one character).

    Anchored at both ends by the caller."""
    if remainder == "":
        return ""
    n = len(remainder)
    out: list[str] = []
    i = 0
    while i < n:
        if remainder[i : i + 2] == "**":
            prev_boundary = i == 0 or remainder[i - 1] == "/"
            after = i + 2
            next_boundary = after == n or remainder[after] == "/"
            if prev_boundary and next_boundary:
                if after == n:  # trailing "**" -- the very end of the pattern
                    out.append(".+")
                    i = after
                else:  # mid-pattern whole segment -- zero or more segments
                    out.append("(?:.*/)?")
                    i = after + 1  # the group already accounts for its own "/"
            else:
                out.append(".*")  # embedded inside a larger segment
                i = after
            continue
        ch = remainder[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


# `P-b` (NORMATIVE) -- ported verbatim, comment included, from the UI's
# `charter.py`; the spec calls this "the single most important sentence
# in the port source":
#
#   Deliberately NOT `.resolve()`d past the (trusted) bucket root: the
#   write-target paths below are the CANONICAL reference point a request
#   is judged against, and resolving them would follow any symlink an
#   attacker planted AT that exact filename, silently rebasing the
#   "expected" path onto wherever the symlink points -- defeating the
#   check for the one case it exists to catch. Only the REQUESTED path
#   (the model-supplied, untrusted `tool_input`) gets the full
#   symlink-following `.resolve()`.
#
# `_compile_glob` and `_compile_exact` below are where that rule is
# implemented: each resolves only its TRUSTED prefix (`_split_trusted_prefix`
# / `.parent`), leaving the wildcard tail / final leaf segment verbatim.
def _compile_glob(pattern: str) -> re.Pattern[str]:
    _check_supported(pattern)
    prefix, remainder = _split_trusted_prefix(pattern)
    resolved_prefix = str(Path(prefix).resolve()) if prefix else str(Path("/").resolve())
    if remainder == "":
        return re.compile(f"^{re.escape(resolved_prefix)}$")
    return re.compile(
        f"^{re.escape(resolved_prefix.rstrip('/'))}/{_translate_remainder(remainder)}$"
    )


def _compile_exact(path: str) -> Path:
    _check_supported(path)
    p = Path(path)
    resolved_parent = p.parent.resolve()
    return resolved_parent / p.name  # C-5: the leaf is verbatim, never resolved


def _build_charter_paths(containment: Containment) -> CharterPaths:
    globs = tuple(_compile_glob(g) for g in containment.write_globs)
    exacts = tuple(_compile_exact(e) for e in containment.write_exact)
    return CharterPaths(glob_patterns=globs, exact_paths=exacts)


def _matches_write_scope(target: Path, paths: CharterPaths) -> bool:
    if target in paths.exact_paths:
        return True
    target_str = str(target)
    return any(pattern.match(target_str) is not None for pattern in paths.glob_patterns)


def build_can_use_tool(containment: Containment) -> CanUseTool:
    """Build the `can_use_tool` callback for one SDK session (`Charter-1`).

    Resolves every write-scope pattern ONCE, at callback-build time, then
    returns a closure that judges every subsequent tool call against that
    frozen `CharterPaths`. Raises `CharterPatternUnsupported` immediately
    -- before returning a callback -- if any pattern uses an
    unimplemented metacharacter (`C-7`).

    The decision order (`C-4`), first hit wins:
      1. `tool_name` is in the containment's `disallowed_tools` -> DENY
         (belt; `options.disallowed_tools` is the braces and normally
         fires first).
      2. the enforcement hatch (`C-10`) is open -> ALLOW.
      3. `tool_name` is in the write family -> a path decision (`C-5`).
      4. `tool_name` is in the containment's `allowed_tools` -> ALLOW
         (unscoped -- `C-2`: no CLI surface scopes reads by path).
      5. -> DENY, always, with a reason naming the tool.

    Denial RECORDING (`C-9`) is deliberately NOT done here -- this module
    may not import `.events` (§3.1's table); `backend.py` wraps the
    returned callback to append every `PermissionResultDeny` to the
    session's `EventLog` before it reaches the SDK.
    """
    paths = _build_charter_paths(containment)
    disallowed = frozenset(t for t in (containment.disallowed_tools or "").split(",") if t)
    allowed = frozenset(t for t in (containment.allowed_tools or "").split(",") if t)
    # `C-10` -- the hatch is a property of the containment DATA, never an
    # `os.environ` read in this module (`D-25`): open iff the settings
    # scope is unenforced AND there is a write scope to un-enforce (the
    # second conjunct is what keeps the analyst and
    # `DEGRADED_WORKER_CONTAINMENT` -- both empty write sets -- closed).
    hatch_open = containment.default_mode is None and bool(
        containment.write_globs or containment.write_exact
    )

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        del context
        if tool_name in disallowed:
            return PermissionResultDeny(
                message=f"self-learn invocation charter: {tool_name} is disallowed on this surface"
            )

        if hatch_open:
            return PermissionResultAllow()

        if tool_name in W:
            raw_target = _extract_target_path(tool_input)
            if raw_target is None:
                return PermissionResultDeny(
                    message=(
                        "self-learn invocation charter: could not determine a "
                        f"target path for this {tool_name} call — denied by default"
                    )
                )
            target = Path(raw_target).resolve()
            if _matches_write_scope(target, paths):
                return PermissionResultAllow()
            return PermissionResultDeny(
                message=(
                    f"self-learn invocation charter: {tool_name} write scope "
                    f"does not include {target}"
                )
            )

        if tool_name in allowed:
            return PermissionResultAllow()

        return PermissionResultDeny(
            message=(
                f"self-learn invocation charter: {tool_name} is outside the "
                "permitted surface — denied by default"
            )
        )

    return can_use_tool
