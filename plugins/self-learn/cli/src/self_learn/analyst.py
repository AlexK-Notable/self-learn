"""One-shot routing analyst for bare-terminal ``teach --route`` (T8).

08 §1 `teach --route` pin: in-session callers pass structured fields plus
``--dest``; a bare ``--route`` with no destination spawns a ONE-SHOT
``claude -p`` analyst against the routing doctrine file and applies its
destination. 01 §3.2: invocation is the approval — the analyst produces the
destination, never a confirmation prompt.

Invocation (the shipped flag set — documented here per the T8 brief; like
T13's worker pin, the *property* is the contract and the literal syntax is
re-verified against the live CLI when the analyst first runs for real):

    claude -p <prompt>
        --append-system-prompt <full text of routing-doctrine.md>
        --model ${SELF_LEARN_ANALYST_MODEL:-claude-sonnet-5}
        --allowedTools Read,Grep,Glob

Properties pinned by that construction:

- **System prompt = the doctrine file** at
  ``plugins/self-learn/skills/self-learn/references/routing-doctrine.md``,
  resolved under ``SELF_LEARN_HOME``'s plugin tree (08 §1 Routing-doctrine
  pin: one file, three loaders — never fork it). Missing file → the caller
  exits 2 pre-spawn ("routing doctrine not installed — T10").
- **Restricted tools**: Read/Grep/Glob only — NO Bash, NO Edit, NO Write,
  ever (mirror of the T13 worker pin: with shell access any restriction is
  void). The analyst returns YAML on stdout; the record content rides in
  the prompt, so it needs no write path at all.
- **Model**: ``SELF_LEARN_ANALYST_MODEL``, default ``claude-sonnet-5``
  (routing is human-approved by invocation — cost beats brilliance).
- **Timeout**: ``SELF_LEARN_ANALYST_TIMEOUT`` seconds, default 120.

Output contract: a YAML mapping ``destination`` (02 §1 enum) /
``alternates`` (optional) / ``rationale`` — fenced output tolerated. ONE
parse attempt, no reprompt (T8 brief): any failure (spawn error, non-zero
exit, timeout, unparseable or invalid YAML) raises :class:`AnalystError`
and the caller captures the record to ``pending/`` as a normal teach —
the lesson is never lost.

The CLI stamps ``record_sha`` itself with the shared normalization hash
(the model's value — if it emitted one — is never trusted; same rule as
08 §7.1's worker step 4), then validates the assembled proposal through
``ledger_ops.validate_proposal`` — one schema, both producers.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import invocation, settings
from .ledger_ops import (
    ROSTER_UNAVAILABLE,
    LedgerOpsError,
    ProposalError,
    bucket_dir_for_scope,
    find_record_path,
    validate_proposal,
)
from .normalize import sha_anchor
from .records import Record

__all__ = [
    "ANALYST_ALLOWED_TOOLS",
    "DEFAULT_ANALYST_MODEL",
    "DEFAULT_ANALYST_TIMEOUT",
    "DOCTRINE_BASENAME",
    "AnalystError",
    "analyze",
    "doctrine_path",
]

#: 08 §1 Routing-doctrine pin — the single source. Doc 13 T-H3 moved its
#: resolution to the CLI PACKAGE (the doctrine ships with the product
#: beside the skill — never via any ledger home).
DOCTRINE_BASENAME = "routing-doctrine.md"

#: Read-only tool set — NO Bash/Edit/Write, ever (see module docstring).
ANALYST_ALLOWED_TOOLS = "Read,Grep,Glob"

DEFAULT_ANALYST_MODEL = "claude-sonnet-5"
DEFAULT_ANALYST_TIMEOUT = 120  # seconds

_FENCE_RE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)\n\s*```", re.DOTALL)

class AnalystError(Exception):
    """The one-shot analyst failed — the caller falls back to a normal
    pending capture (the record is never lost)."""


def doctrine_path() -> Path:
    """The routing doctrine file, PACKAGE-relative (doc 13 T-H3: one
    file, three loaders — worker, analyst, skill — all off the product
    tree, never any home)."""
    from .worker import package_skill_refs

    return package_skill_refs() / DOCTRINE_BASENAME


def _model() -> str:
    return os.environ.get("SELF_LEARN_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL


def _timeout(home: Path | str) -> float:
    """U-settings Phase 1: resolves through the registry's `analyst.
    timeout_secs` entry (config.yaml `analyst.timeout_secs` > env
    `SELF_LEARN_ANALYST_TIMEOUT` > :data:`DEFAULT_ANALYST_TIMEOUT` --
    U-flip 2026-09-01, S-58: config wins). No
    positivity clamp (unlike the worker/miner timeouts) — this function
    never validated a <=0 value pre-Phase-1 either; preserved rather than
    tightened as a side effect."""
    value, _source = settings.resolve_setting(home, settings.by_name("analyst.timeout_secs"))
    return cast(float, value)


def _strip_fences(text: str) -> str:
    """Tolerate fenced output: prefer the first fenced block, else as-is."""
    match = _FENCE_RE.search(text)
    return match.group(1) if match else text.strip()


def _parse_yaml_map(text: str) -> dict:
    try:
        data = YAML(typ="safe").load(_strip_fences(text))
    except YAMLError as exc:
        raise AnalystError(f"analyst output is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise AnalystError(
            f"analyst output is not a YAML mapping (got {type(data).__name__})"
        )
    return data


def analyze(
    home: Path | str, record: Record, *, project_path: Path | None = None,
    charter_denials: list[dict[str, Any]] | None = None,
) -> dict:
    """Run the one-shot analyst for ``record``; return a validated proposal
    dict: **every field the model emitted**, plus the CLI-stamped
    ``record_sha``, ``model`` and ``analyzed_at``. Raises
    :class:`AnalystError` on ANY failure — exactly one parse attempt, no
    reprompt.

    This docstring used to enumerate a fixed key set
    (destination/alternates/rationale), which was the shipped defect
    (FW-41): the function rebuilt the proposal from that enumeration and
    silently dropped anything not on it, so a `hook` proposal could never
    survive its own validator. The fix copies the parsed mapping wholesale,
    so **do not re-introduce an enumeration here** — a list of fields in
    this docstring is what a future reader would restore the bug from.

    ``project_path`` (gate FOLD 5, keyword-only, default ``None`` for
    backward compatibility with any caller re-analyzing a record already
    on disk — see the WOULD-BE-path comment below, where it's only ever
    consulted on the not-yet-persisted branch): the COMMON case for
    ``teach --route`` at project scope is a record that is NOT yet on
    disk, so :func:`bucket_dir_for_scope` needs the project's path to
    resolve a real bucket at all (doc 13 §3: project buckets are
    per-project, keyed by the path). Before this parameter existed, every
    project-scope one-shot call degraded straight to the
    ``_unresolved-scope`` sentinel — never the record's REAL bucket —
    which made ALWAYS/PATHED/DEMAND all render "(unresolvable — project
    bucket has no meta.yaml)" in the prompt, a FALSE reason (there was no
    bucket to check for a meta.yaml at all; the caller simply never
    supplied the path it had in hand). ``teach.py``'s own call site
    (``_route_now``, ~:683) now threads its own ``project_path`` through;
    a caller that still omits it gets `worker.path_roster`'s newer,
    honest sentinel instead of the old misleading one (see that
    function's own docstring).

    U-corrob (``DEN3``, 2026-08-28): ``charter_denials``, when given, is a
    caller-owned list this call EXTENDS with this invocation's
    charter-sourced denials (``outcome.denials`` entries with
    ``source == "charter"``) — the same caller-owned-accumulator shape
    ``worker._invoke_claude`` uses for `FW-107`, and for the same reason:
    the extend happens BEFORE any of the ``AnalystError`` legs below, so a
    caller sees this run's denials whether ``analyze`` returns or raises.
    Every existing call site that omits the new keyword-only parameter is
    unaffected."""
    doctrine = doctrine_path()
    if not doctrine.is_file():
        # Callers check first for the pinned exit-2 message; this guard is
        # defense in depth for library use.
        raise AnalystError(f"routing doctrine not installed — T10 ({doctrine})")
    home = Path(home)
    # Pre-spawn guard, same posture as the doctrine check above: without
    # it, subprocess.run(cwd=...) raises FileNotFoundError (mislabeled
    # "claude CLI not found on PATH" by the handler below) for a missing
    # home, and NotADirectoryError / PermissionError — caught by
    # nothing — for a file or an unenterable directory, escaping this
    # function's AnalystError-only contract. `is_dir()` alone is not
    # enough: a directory without the search bit still raises
    # PermissionError on chdir, so the guard requires one the process can
    # actually enter.
    if not (home.is_dir() and os.access(home, os.X_OK)):
        raise AnalystError(
            f"analyst home is not a directory this process can enter ({home})"
        )
    doctrine_text = doctrine.read_text(encoding="utf-8")
    model = _model()
    # U-composer §3.5: the analyst's prompt is composed by the SAME
    # function the worker uses for its per-record block (A11). The
    # QueueEntry's path is derived via find_record_path when the record
    # is ALREADY on disk (a re-analysis of a real pending record) — but
    # the bare-terminal `teach --route` path (teach.py:683) calls
    # analyze() on an in-memory record that is not yet persisted (it
    # writes to pending/ only on the AnalystError fallback), so
    # find_record_path would raise for the common case. Degrade to the
    # WOULD-BE path (the same arithmetic create_record uses) rather than
    # fail: this is purely informational (the "record file:" line and the
    # bucket-derived path-roster rows), never a file this function reads
    # or writes. `project_path` (above) is what makes that WOULD-BE path
    # a REAL bucket at project scope instead of always the
    # `_unresolved-scope` sentinel (gate FOLD 5) — `bucket_dir_for_scope`
    # only still raises here when project scope's `project_path` is
    # genuinely absent (a caller other than `teach.py` that didn't supply
    # it) or a skill scope names a skill no host registers.
    from .ledger_ops import QueueEntry
    from .worker import compose_single_prompt

    try:
        record_path = find_record_path(home, record.id)
    except LedgerOpsError:
        try:
            bucket_dir = bucket_dir_for_scope(
                home, record.scope, project_path=project_path
            )
        except LedgerOpsError:
            bucket_dir = home / "_unresolved-scope"
        record_path = bucket_dir / "pending" / f"{record.id}.md"
    entry = QueueEntry(path=record_path, record=record)
    prompt, roster = compose_single_prompt(home, entry)

    timeout = _timeout(home)
    spec = invocation.SessionSpec(
        surface="analyst",
        prompt=prompt,
        cwd=home,
        timeout=timeout,
        containment=invocation.containment_for(
            "analyst", allowed_tools=ANALYST_ALLOWED_TOOLS
        ),
        log=lambda _msg: None,
        doctrine=doctrine_text,
    )
    outcome = invocation.text_session(spec)
    if charter_denials is not None:
        charter_denials.extend(
            d for d in getattr(outcome, "denials", ()) if d.get("source") == "charter"
        )
    # W-h: every AnalystError message on this path is rendered through
    # LOG_TEMPLATES["analyst"] -- the analyst does not carry its own
    # copies of these f-strings (see that criterion's docstring, WR6).
    templates = invocation.LOG_TEMPLATES["analyst"]
    if outcome.failure == "not-found":
        assert templates.not_found is not None  # T-c: analyst never omits this leg
        raise AnalystError(templates.not_found) from outcome.exc
    if outcome.failure == "timeout":
        assert templates.timed_out is not None  # T-c: analyst never omits this leg
        raise AnalystError(
            templates.timed_out.format(timeout=timeout)
        ) from outcome.exc
    if outcome.failure == "exit":
        detail = outcome.detail
        if templates.detail_strip:
            detail = detail.strip()
        if templates.detail_cap is not None:
            detail = detail[: templates.detail_cap]
        assert templates.exited is not None  # T-c: analyst never omits this leg
        raise AnalystError(templates.exited.format(rc=outcome.rc, detail=detail))
    if outcome.failure == "unavailable":
        raise AnalystError(templates.unavailable.format(exc=outcome.detail))
    if outcome.failure == "os-error":
        assert templates.os_error is not None  # Err-1: the analyst now carries this leg
        raise AnalystError(templates.os_error.format(exc=outcome.detail)) from outcome.exc

    parsed = _parse_yaml_map(outcome.stdout)
    # Register R (U-analyst spec §2.1) — copy-then-stamp, not a rebuild
    # from an enumerated key set: any field the analyst doesn't know
    # about (a future doctrine addition, r2's `recommendation:`/`gates:`,
    # today's `hook`/`examples`) survives verbatim instead of silently
    # vanishing between the parse and validate_proposal below. That
    # schema has exactly one authority — validate_proposal itself —
    # restating it here would reintroduce the defect in a new location.
    proposal = dict(parsed)
    # `script` is CLI-owned and refused from the model on every other
    # path (stamp_proposal, _prepare_one_motion_hook) — strip it here
    # UNCONDITIONALLY and BEFORE validate_proposal. Conditioning the strip
    # on destination == "hook", or moving it below validate_proposal,
    # would let a non-hook proposal carrying `script` reach the
    # validator, which refuses `script` outright outside a hook
    # destination — turning an otherwise-routable proposal into an
    # AnalystError.
    proposal.pop("script", None)
    # CLI-stamped fields — assigned after the copy, unconditionally
    # overwriting whatever the model emitted (Register R). Kept literal
    # rather than setdefault, which would silently invert this row.
    proposal["model"] = model
    proposal["analyzed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # CLI-stamped — never the model's (shared normalization fn, 08 §7.1).
    proposal["record_sha"] = sha_anchor(record.body)

    # U-composer §3.6 — roster-sha honesty, both legs, BEFORE
    # validate_proposal: a well-shaped-but-wrong sha or a false
    # "unavailable" claim would otherwise reach the validator looking
    # legitimate (X3 only proves shape, never the value).
    gates = proposal.get("gates")
    if isinstance(gates, dict):
        t3 = gates.get("t3")
        if isinstance(t3, dict):
            claimed = t3.get("roster_sha")
            if claimed == ROSTER_UNAVAILABLE:
                if roster.sha != ROSTER_UNAVAILABLE:
                    raise AnalystError(
                        f"analyst proposal claims gates.t3.roster_sha "
                        f"{ROSTER_UNAVAILABLE!r} but this run's roster WAS "
                        f"composed (real sha {roster.sha!r}) — X3 Leg B"
                    )
            elif isinstance(claimed, str) and claimed != roster.sha:
                raise AnalystError(
                    f"analyst proposal's gates.t3.roster_sha {claimed!r} "
                    f"does not match this run's composed roster sha "
                    f"{roster.sha!r} — X3 Leg A"
                )

    # U-composer §3.7/F1 — analyst.analyze is the PRODUCER: "where a
    # fabricated quote first arrives from the model, before any other
    # site ever sees it." record_text= closes containment here; scope=
    # closes Table-1/Render-1 derivation (u-table §3.5) on the same call.
    try:
        validate_proposal(proposal, record_text=record.to_text(), scope=record.scope)
    except ProposalError as exc:
        raise AnalystError(f"analyst proposal invalid: {exc}") from exc
    return proposal
