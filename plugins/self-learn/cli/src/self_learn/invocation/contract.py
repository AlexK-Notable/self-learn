"""U-seam §3.1/3.2/3.3/3.4/3.5/3.6/3.7.4 — the invocation seam's data
contracts: the four surfaces, containment-as-data, the session/outcome
shapes, the ``Backend`` protocol, the log-template table and the
transport table.

Stdlib-only (``I-a``): this module -- and every module in this package --
may not import ``worker``, ``miner``, ``analyst``, ``verbs``, ``teach``
or ``ledger_ops``. Everything surface-specific arrives as data or as a
caller-supplied closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

__all__ = [
    "SURFACES",
    "SELECTOR_FOR_SURFACE",
    "DEFAULT_BACKEND_FOR_SURFACE",
    "Surface",
    "Containment",
    "containment_rules",
    "containment_permissions",
    "containment_for",
    "DEGRADED_WORKER_CONTAINMENT",
    "SessionSpec",
    "FAILURE_KINDS",
    "Outcome",
    "Backend",
    "BackendUnavailable",
    "LogTemplates",
    "LOG_TEMPLATES",
    "TRANSPORT",
]

# --------------------------------------------------------- Surf-1 (Sec 3.2)

Surface = Literal["worker", "worker-repair", "miner-reader", "analyst"]

SURFACES: tuple[Surface, ...] = ("worker", "worker-repair", "miner-reader", "analyst")

#: Three environment selectors for four surfaces (Sec 3.2) -- the repair
#: round is the worker's second invocation and is never independently
#: configurable.
SELECTOR_FOR_SURFACE: dict[str, str] = {
    "worker": "WORKER",
    "worker-repair": "WORKER",
    "miner-reader": "MINER",
    "analyst": "ANALYST",
}

#: `Flip-1` (U-sdka, U-flip) -- rung 5 of the backend precedence chain,
#: per surface. The analyst flipped first (attended, lowest volume, and
#: the flip IS the F3 containment fix); worker/worker-repair/miner-reader
#: flip together in this wave (user ruling 2026-08-23: burn-in cancelled,
#: Lane B full steam). Every value must be a member of
#: `registry.KNOWN_BACKENDS`.
DEFAULT_BACKEND_FOR_SURFACE: dict[str, str] = {
    "worker": "sdk",
    "worker-repair": "sdk",
    "miner-reader": "sdk",
    "analyst": "sdk",
}


# ----------------------------------------------------------- Cont-1 (Sec 3.3)


@dataclass(frozen=True)
class Containment:
    allowed_tools: str | None  # the --allowedTools value, verbatim; None = flag absent
    disallowed_tools: str | None  # the --disallowedTools value, verbatim; None = flag absent
    write_globs: tuple[str, ...]  # absolute path PATTERNS, no rule syntax
    write_exact: tuple[str, ...]  # absolute FILE paths, no rule syntax
    strict_mcp: bool
    default_mode: str | None  # the settings file's permissions.defaultMode; None = key absent


def containment_rules(c: Containment) -> list[str]:
    """``C-b`` -- rule rendering lives in exactly one function. The double
    slash in ``Edit(//...)`` is the ``/`` here plus the leading ``/`` of
    an absolute pattern/path -- there is exactly one occurrence of that
    construction in the package. ``write_exact`` is sorted at render
    time; ``write_globs`` is not (the three fallback ledger globs ship in
    a hand-chosen order)."""
    return [f"Edit(/{p})" for p in (*c.write_globs, *sorted(c.write_exact))]


def containment_permissions(c: Containment) -> dict:
    """``defaultMode`` is omitted, not set to null, when absent."""
    perms: dict[str, object] = {"allow": containment_rules(c)}
    if c.default_mode is not None:
        perms["defaultMode"] = c.default_mode
    return perms


def containment_for(
    surface: str,
    *,
    allowed_tools: str | None = None,
    disallowed_tools: str | None = None,
    home: Path | str | None = None,
    stage_dir: Path | str | None = None,
    stage_on: bool = False,
    enforce: bool = True,
    write_exact: tuple[str, ...] = (),
    spool_dir: Path | str | None = None,
) -> Containment:
    """``C-c`` -- receives SCALARS ONLY and renders every glob PATTERN
    from string literals inside this module. It may not receive, call, or
    otherwise consult any rule list, rule string, settings path, or
    settings-file content (``CN9``). The "Scalar inputs" column of Sec
    3.3's table is exhaustive per surface -- fields not listed there for
    a given surface are fixed by this function, not taken from the
    caller."""
    if surface == "worker":
        if stage_on:
            write_globs: tuple[str, ...] = (f"{stage_dir}/**",)
        else:
            write_globs = (
                f"{home}/skills/**/proposals/**",
                f"{home}/projects/**/proposals/**",
                f"{home}/user/proposals/**",
            )
        return Containment(
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            write_globs=write_globs,
            write_exact=(),
            strict_mcp=True,
            default_mode="default" if enforce else None,
        )
    if surface == "worker-repair":
        return Containment(
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            write_globs=(),
            write_exact=tuple(write_exact),
            strict_mcp=True,
            default_mode="default" if enforce else None,
        )
    if surface == "miner-reader":
        return Containment(
            allowed_tools=None,
            disallowed_tools=disallowed_tools,
            write_globs=(f"{spool_dir}/**",),
            write_exact=(),
            strict_mcp=True,
            default_mode="default",
        )
    if surface == "analyst":
        return Containment(
            allowed_tools=allowed_tools,
            disallowed_tools=None,
            write_globs=(),
            write_exact=(),
            strict_mcp=False,
            default_mode=None,
        )
    raise ValueError(f"containment_for: unknown surface {surface!r}")


#: ``W-a`` -- describes NOTHING: empty write_globs, empty write_exact,
#: default_mode=None. Exists solely so `test_repair.py::test_e1`'s
#: five-argument call to `worker._invoke_claude` (no containment) stays
#: legal (`B-4`). Never reached from `run()` -- both of `run()`'s call
#: sites pass an explicit `containment=`.
DEGRADED_WORKER_CONTAINMENT = Containment(
    allowed_tools=None,
    disallowed_tools=None,
    write_globs=(),
    write_exact=(),
    strict_mcp=False,
    default_mode=None,
)


# ------------------------------------------------------------ Spec-1 (Sec 3.4)


@dataclass(frozen=True)
class SessionSpec:
    surface: str
    prompt: str
    cwd: Path
    timeout: float
    containment: Containment
    log: Callable[[str], None]
    label: str = ""
    timeout_display: object | None = None
    doctrine: str | None = None  # appended to the claude_code system-prompt preset (§7)


FAILURE_KINDS = ("exit", "timeout", "not-found", "os-error", "unavailable")


@dataclass(frozen=True)
class Outcome:
    ok: bool  # == (failure is None)
    rc: int | None  # None when the process never exited
    stdout: str  # "" unless the surface's transport captures it
    detail: str  # the surface's detail string, UNTRUNCATED, UNSTRIPPED
    failure: str | None  # None or a member of FAILURE_KINDS
    exc: BaseException | None = None

    def __post_init__(self) -> None:
        if self.ok != (self.failure is None):
            raise ValueError(
                f"Outcome invariant violated: ok={self.ok!r} but failure={self.failure!r}"
            )


class Backend(Protocol):
    """The two-operation seam every backend implements (Sec 3.2 `S-a`)."""

    def write_session(self, spec: SessionSpec) -> Outcome: ...

    def text_session(self, spec: SessionSpec) -> Outcome: ...


class BackendUnavailable(RuntimeError):
    """Raised by `backend_for` when the resolved backend is not built
    yet (Sec 3.7.4) -- the `sdk` selection, at any rung."""


# -------------------------------------------------------------- Log-1 (Sec 3.6)


@dataclass(frozen=True)
class LogTemplates:
    exited: str | None
    timed_out: str | None
    not_found: str | None
    os_error: str | None
    unavailable: str
    detail_cap: int | None  # [:N] before interpolation; None = no truncation
    detail_strip: bool  # .strip() before interpolation


_WORKER_TEMPLATES = LogTemplates(
    exited="run: {label}claude exited {rc}: {detail}",
    timed_out="run: {label}claude timed out after {timeout:g}s",
    not_found="run: {label}claude CLI not found on PATH",
    os_error="run: {label}claude invocation failed ({exc})",
    unavailable="run: {label}invocation backend unavailable ({exc})",
    detail_cap=400,
    detail_strip=False,
)

_MINER_TEMPLATES = LogTemplates(
    exited="run: claude exited {rc}: {detail}",
    timed_out="run: claude timed out after {timeout}s",
    not_found="run: claude CLI not found on PATH",
    os_error="run: reader invocation failed ({exc})",
    unavailable="run: invocation backend unavailable ({exc})",
    detail_cap=400,
    detail_strip=False,
)

_ANALYST_TEMPLATES = LogTemplates(
    exited="analyst exited {rc}: {detail}",
    timed_out="analyst timed out after {timeout:g}s",
    not_found="claude CLI not found on PATH",
    os_error="analyst invocation failed ({exc})",  # Err-1 (U-sdka): FW-87, R-1 closed
    unavailable="invocation backend unavailable ({exc})",
    detail_cap=None,
    detail_strip=True,
)

#: ``L-a`` -- the templates are NOT uniform across surfaces, and that is
#: the shipped truth (worker and worker-repair share one table; the
#: miner carries no label and different wording; the analyst has no
#: `run: ` prefix, no truncation, strips, and has no `os_error` leg).
LOG_TEMPLATES: dict[str, LogTemplates] = {
    "worker": _WORKER_TEMPLATES,
    "worker-repair": _WORKER_TEMPLATES,
    "miner-reader": _MINER_TEMPLATES,
    "analyst": _ANALYST_TEMPLATES,
}


# ------------------------------------------------------------ Trans-1 (Sec 3.5)

#: U-cleanup §8.2 (`BLOCKER-1`) -- the transport-table dataclass and the
#: CLI-only fields it described (`kind`, `kills_process_group`,
#: `prompt_via_argv`, `result_stdout`) are DELETED with the CLI backend,
#: the only reader that branched on them. `TRANSPORT` itself is NOT deleted:
#: `invocation_sdk/backend.py` folds it into `_CATCHES_OS_ERROR`, which is
#: the table-level mutation point `03-decisions.md`'s `S-48`/`M11`
#: evidence depends on -- the analyst-vs-worker/miner OSError/
#: ClaudeSDKError split. Trimmed to a plain `dict[str, bool]` rather than
#: a one-field dataclass, so the table stays a mutable, table-level fact
#: (`S-48` note, `03-decisions.md`).
TRANSPORT: dict[str, bool] = {
    "worker": True,
    "worker-repair": True,
    "miner-reader": True,
    "analyst": True,  # Err-1 (U-sdka): FW-87, R-1 closed
}
