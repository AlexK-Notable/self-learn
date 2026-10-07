"""U-seam §3.1/3.2/3.3/3.4/3.5/3.6/3.7.4 — the invocation seam's data
contracts: the seven surfaces, containment-as-data, the session/outcome
shapes, a session's own tools as plain data, the ``Backend`` protocol,
the log-template table and the transport table.

Stdlib-only (``I-a``): this module -- and every module in this package --
may not import ``worker``, ``miner``, ``analyst``, ``verbs``, ``teach``
or ``ledger_ops``. Everything surface-specific arrives as data or as a
caller-supplied closure.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

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
    "ToolReply",
    "McpTool",
    "McpToolset",
    "SessionSpec",
    "NO_AUTO_MEMORY_ENV",
    "FAILURE_KINDS",
    "Outcome",
    "Backend",
    "BackendUnavailable",
    "LogTemplates",
    "LOG_TEMPLATES",
    "TRANSPORT",
]

# --------------------------------------------------------- Surf-1 (Sec 3.2)

Surface = Literal[
    "worker",
    "worker-repair",
    "miner-reader",
    "analyst",
    "steward",
    "overseer",
    "miner-session",
]

#: 2026-10-06 (U4-seam, `17-invocation-runbook.md` §1a): `miner-session`,
#: the session miner (one transcript per call, run beside the old miner
#: during its shadow period), is LAST so every existing row keeps its
#: position (`provider.py` reads `SURFACES[0]` as its representative).
SURFACES: tuple[Surface, ...] = (
    "worker",
    "worker-repair",
    "miner-reader",
    "analyst",
    "steward",
    "overseer",
    "miner-session",
)

#: Five environment selectors for seven surfaces (Sec 3.2) -- the repair
#: round is the worker's second invocation and is never independently
#: configurable. `steward`/`overseer` (17-invocation-runbook.md §1,
#: 2026-09-13 note; S-18 as amended) join with their own, independent
#: selectors -- neither shares a round with another surface the way
#: worker-repair does. `miner-session` (2026-10-06) shares `MINER` with
#: `miner-reader`, so `models.miner`, `sdk.max_turns.miner` and the
#: `MINER` backend environment selector apply to both miners alike.
SELECTOR_FOR_SURFACE: dict[str, str] = {
    "worker": "WORKER",
    "worker-repair": "WORKER",
    "miner-reader": "MINER",
    "analyst": "ANALYST",
    "steward": "STEWARD",
    "overseer": "OVERSEER",
    "miner-session": "MINER",
}

#: `Flip-1` (U-sdka, U-flip) -- rung 5 of the backend precedence chain,
#: per surface. The analyst flipped first (attended, lowest volume, and
#: the flip IS the F3 containment fix); worker/worker-repair/miner-reader
#: flip together in this wave (user ruling 2026-08-23: burn-in cancelled,
#: Lane B full steam). Every value must be a member of
#: `registry.KNOWN_BACKENDS`. `steward`/`overseer` (2026-09-13, S-18 as
#: amended) ship directly on `sdk` -- there is no `cli` backend left to
#: default away from (S-49), so unlike the four above there was never a
#: burn-in period for these two to flip through.
DEFAULT_BACKEND_FOR_SURFACE: dict[str, str] = {
    "worker": "sdk",
    "worker-repair": "sdk",
    "miner-reader": "sdk",
    "analyst": "sdk",
    "steward": "sdk",
    "overseer": "sdk",
    "miner-session": "sdk",
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
    #: 2026-09-28: absolute DIRECTORY paths the read tools (Read, Grep,
    #: Glob) are fenced to; empty = reads unscoped, as every surface but
    #: the overseer has always been (`charter.py` `C-2`). The overseer's
    #: one root is its own workspace, the session's cwd.
    read_roots: tuple[str, ...] = ()
    #: 2026-09-28 (follow-up 5): absolute DIRECTORY paths the read tools may
    #: never read inside, whatever `read_roots` says -- the steward's is the
    #: cache's kept session transcripts (`session_copies.sessions_dir`).
    #: Empty = no deny root.
    read_denied: tuple[str, ...] = ()


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
    sessions_dir: Path | str | None = None,
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
    if surface == "steward":
        # 2026-09-28 (follow-up 5): the steward reads transcripts under
        # Claude Code's own `projects/` as evidence, unfenced; it may never
        # read self-learn's kept COPIES of model sessions (`sessions_dir`,
        # the cache's `sessions/`), which hold other runs' sessions.
        return Containment(
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            write_globs=(f"{stage_dir}/steward/**",),
            write_exact=(),
            strict_mcp=True,
            default_mode="default",
            read_denied=(f"{sessions_dir}",) if sessions_dir is not None else (),
        )
    if surface == "overseer":
        # 2026-09-28 (the user's words: "it should have a 'sandbox' ... it
        # can use as a workspace"): `{stage_dir}/overseer` is the overseer's
        # OWN workspace (`overseer.run.workspace_dir`, whose parent the
        # runner passes here), never under the worker's stage. It is both
        # the only place the session may write and the only place it may
        # read.
        return Containment(
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            write_globs=(f"{stage_dir}/overseer/**",),
            write_exact=(),
            strict_mcp=True,
            default_mode="default",
            read_roots=(f"{stage_dir}/overseer",),
        )
    if surface == "miner-session":
        # 2026-10-06 (U4-seam): the session miner's only tools are its own
        # (`SessionSpec.mcp_toolset`); the caller's `allowed_tools` names
        # exactly those, and the charter allows a tool only when its name
        # is listed here. No write scope, so the hatch stays shut; no read
        # roots, because with the session's built-in tools switched off
        # no read tool exists.
        return Containment(
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            write_globs=(),
            write_exact=(),
            strict_mcp=True,
            default_mode="default",
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


# ------------------------------------------------- a session's own tools


#: A tool or server name as the model sees it, `mcp__<server>__<name>`:
#: lower-case, starting with a letter, at most 32 characters.
_MCP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

#: `SessionSpec.sidecar_key` becomes part of a file name in the cache.
_SIDECAR_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class ToolReply:
    """What one of a session's own tools answers (2026-10-06, U4-seam):
    the text the model reads, and whether it is an error the model may
    retry after."""

    text: str
    is_error: bool = False


@dataclass(frozen=True)
class McpTool:
    """One of a session's own tools, as plain data (2026-10-06, U4-seam):
    nothing here imports the SDK, so a producer can define its tools
    without it. `input_schema` is a JSON Schema object (it must carry
    `type` and `properties`); `handler` receives the model's arguments
    and answers with a `ToolReply`. `read_only` tools may run in
    parallel. The seam (`invocation_sdk/backend.py`) builds the SDK's
    in-process server from these."""

    name: str
    description: str
    input_schema: Mapping[str, object]
    handler: Callable[[dict[str, Any]], Awaitable[ToolReply]]
    read_only: bool = True


@dataclass(frozen=True)
class McpToolset:
    """A session's own tools, served by one in-process MCP server named
    `server` (2026-10-06, U4-seam). The model sees each tool as
    `mcp__<server>__<name>`; the session's containment must allow
    exactly those names and nothing else."""

    server: str
    tools: tuple[McpTool, ...]

    def __post_init__(self) -> None:
        if not _MCP_NAME_RE.match(self.server):
            raise ValueError(f"McpToolset: bad server name {self.server!r}")
        seen: set[str] = set()
        for tool in self.tools:
            if not _MCP_NAME_RE.match(tool.name):
                raise ValueError(f"McpToolset: bad tool name {tool.name!r}")
            if tool.name in seen:
                raise ValueError(f"McpToolset: duplicate tool name {tool.name!r}")
            seen.add(tool.name)

    @property
    def qualified_names(self) -> tuple[str, ...]:
        return tuple(f"mcp__{self.server}__{tool.name}" for tool in self.tools)


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
    #: The LEDGER this session's settings come from -- the directory that
    #: holds `config.yaml`. Distinct from `cwd`, which is where the
    #: session RUNS. They coincide on the worker, the miner-reader and
    #: the analyst (all three pass `cwd=home`), which is why this field
    #: defaults to `None` and the seam then falls back to `cwd`: those
    #: three producers need no change and behave exactly as before.
    #: They do NOT coincide on the steward or the overseer, whose
    #: sessions run inside a cache stage directory that has no
    #: `config.yaml` at all -- before this field existed, every ledger
    #: setting the seam reads (the Claude Code binary, the model, the
    #: turn bound, the spend bound, the provider resolution and the
    #: backend choice) silently resolved to its default for those two
    #: surfaces. Keyword, defaulted and LAST so every existing
    #: construction stays valid.
    ledger_home: Path | str | None = None
    #: The turn limit THIS session asks for, when its producer can size
    #: it better than a per-surface constant can -- the steward sets it
    #: to `steward.turns_per_lesson` x the lessons in the batch
    #: (2026-09-20). `None` (every other producer) keeps the seam's own
    #: `sdk.max_turns.<surface>` lookup. What it limits is what Claude
    #: Code's `--max-turns` limits: model responses, not tool calls
    #: (measured 2026-09-19; `docs/specs/self-learn/README.md` revision
    #: log). Keyword, defaulted and LAST, like `ledger_home`.
    max_turns: int | None = None
    #: Environment variables THIS producer adds to its session, as
    #: `(name, value)` pairs (2026-09-24). Empty -- every producer but the
    #: steward and the overseer -- leaves the session environment exactly
    #: what `provider_env` returns. A provider variable wins over one of
    #: these on a clash (`invocation_sdk/backend.py`,
    #: `CliSessionPolicy.env`). Keyword, defaulted and LAST, like the two
    #: fields above.
    extra_env: tuple[tuple[str, str], ...] = ()
    #: A FILE whose text is appended to Claude Code's system prompt
    #: (`--append-system-prompt-file`, 2026-09-26). The steward puts the
    #: part of its brief shared by every call of a run here, so a later
    #: call reads it from the prompt cache; passed as a file because a
    #: command-line argument fails at 131,072 bytes (measured 2026-09-20).
    #: `None` -- every other producer -- sends no such flag. Exclusive
    #: with `doctrine`. Keyword, defaulted and LAST, like the fields above.
    append_system_prompt_file: Path | None = None
    #: Claude Code's `--exclude-dynamic-system-prompt-sections`, through
    #: the SDK's `exclude_dynamic_sections` preset key (2026-09-26): the
    #: working directory and the auto-memory path move out of the system
    #: prompt into the first user message, so the system prompt is the
    #: same bytes from one session to the next. `False` -- every producer
    #: but the steward -- leaves the preset exactly as it was.
    exclude_dynamic_sections: bool = False
    #: The folder name this session's transcript copy lands under,
    #: `<cache>/sessions/<surface>/<transcript_group>/` (2026-09-28,
    #: `session_copies.py`): the steward and the overseer pass their run
    #: id, so every session of one run sits together. `None` -- every
    #: other producer -- falls back to the seam's own per-session run id. Keyword, defaulted and LAST, like the fields
    #: above.
    transcript_group: str | None = None
    #: The session's OWN tools (2026-10-06, U4-seam): one in-process MCP
    #: server the seam builds, with Claude Code's built-in tools switched
    #: off. The containment must allow exactly `mcp_toolset.
    #: qualified_names`, or the seam refuses the session. `None` -- every
    #: producer but the session miner -- sends exactly the options it sent
    #: before. Keyword, defaulted and LAST, like the fields above.
    mcp_toolset: McpToolset | None = None
    #: Keys this session's pid sidecar to it alone,
    #: `<surface>.sdk-child.<sidecar_key>.pid` (2026-10-06, U4-seam), so
    #: several sessions on one surface can run at once without sharing
    #: one sidecar. `None` keeps the one unkeyed sidecar per surface.
    sidecar_key: str | None = None
    #: `True` skips the orphan sweep before this session starts
    #: (2026-10-06, U4-seam): a batch of parallel sessions sweeps once, on
    #: its first call, because a sweep judges every sidecar of the surface
    #: and would clear a live sibling's. `False` -- every producer but the
    #: session miner's fan-out -- sweeps exactly as before.
    skip_orphan_sweep: bool = False

    def __post_init__(self) -> None:
        if self.sidecar_key is not None and not _SIDECAR_KEY_RE.match(self.sidecar_key):
            raise ValueError(f"SessionSpec: bad sidecar_key {self.sidecar_key!r}")

    @property
    def settings_home(self) -> Path | str:
        """The ONE answer to "which ledger do this session's settings come
        from": `ledger_home` when the producer named one, else `cwd`.
        Every settings/provider/backend lookup in the seam
        (`invocation_sdk/backend.py`, `invocation_sdk/provider_env.py`,
        `invocation/registry.py`) reads THIS, never `spec.cwd` -- so a
        surface cannot launch one binary while reporting another."""
        return self.cwd if self.ledger_home is None else self.ledger_home


#: 2026-09-24: Claude Code's auto-memory OFF for a session. Claude Code
#: keys its memory folder to the session's working directory; the
#: overseer's stage path never changes, so a note one overseer session
#: wrote there (run 02227dc1's phase B wrote three, one a "User-demand
#: policy ruling") was loaded into every later overseer session, the blind
#: phase A included, and would have made the journal readable across runs.
#: The installed Claude Code reads this variable (a truthy value turns
#: auto-memory off). The steward and the overseer pass it as `extra_env`.
NO_AUTO_MEMORY_ENV: tuple[tuple[str, str], ...] = (
    ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1"),
)

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

#: U8 (17-invocation-runbook.md §1, 2026-09-13 note) -- steward and
#: overseer both run through `write_session`, like the miner, and
#: neither carries a worker-style repair-round label; each mirrors
#: `_MINER_TEMPLATES`'s shape, naming itself only in `os_error` the same
#: way the miner's own row names itself "reader".
_STEWARD_TEMPLATES = LogTemplates(
    exited="run: claude exited {rc}: {detail}",
    timed_out="run: claude timed out after {timeout}s",
    not_found="run: claude CLI not found on PATH",
    os_error="run: steward invocation failed ({exc})",
    unavailable="run: invocation backend unavailable ({exc})",
    detail_cap=400,
    detail_strip=False,
)

_OVERSEER_TEMPLATES = LogTemplates(
    exited="run: claude exited {rc}: {detail}",
    timed_out="run: claude timed out after {timeout}s",
    not_found="run: claude CLI not found on PATH",
    os_error="run: overseer invocation failed ({exc})",
    unavailable="run: invocation backend unavailable ({exc})",
    detail_cap=400,
    detail_strip=False,
)

_MINER_SESSION_TEMPLATES = LogTemplates(
    exited="run: claude exited {rc}: {detail}",
    timed_out="run: claude timed out after {timeout}s",
    not_found="run: claude CLI not found on PATH",
    os_error="run: session miner invocation failed ({exc})",
    unavailable="run: invocation backend unavailable ({exc})",
    detail_cap=400,
    detail_strip=False,
)

#: ``L-a`` -- the templates are NOT uniform across surfaces, and that is
#: the shipped truth (worker and worker-repair share one table; the
#: miner carries no label and different wording; the analyst has no
#: `run: ` prefix, no truncation, strips, and has no `os_error` leg).
#: steward/overseer (U8) and miner-session (U4-seam) each carry their
#: own row, miner-shaped.
LOG_TEMPLATES: dict[str, LogTemplates] = {
    "worker": _WORKER_TEMPLATES,
    "worker-repair": _WORKER_TEMPLATES,
    "miner-reader": _MINER_TEMPLATES,
    "analyst": _ANALYST_TEMPLATES,
    "steward": _STEWARD_TEMPLATES,
    "overseer": _OVERSEER_TEMPLATES,
    "miner-session": _MINER_SESSION_TEMPLATES,
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
    "steward": True,  # U8 -- same split as every other surface
    "overseer": True,
    "miner-session": True,
}
