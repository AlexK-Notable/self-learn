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

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .ledger_ops import ProposalError, validate_proposal
from .normalize import sha_anchor
from .records import Record

__all__ = [
    "ANALYST_ALLOWED_TOOLS",
    "DEFAULT_ANALYST_MODEL",
    "DEFAULT_ANALYST_TIMEOUT",
    "DOCTRINE_BASENAME",
    "AnalystError",
    "analyze",
    "build_argv",
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

_PROMPT_TEMPLATE = """\
Choose the routing destination for the lesson record below, following the
routing doctrine in your system prompt (narrowest-surface bias).

Reply with ONLY a YAML mapping — no prose, no explanation outside it:

destination: <one of skill-md | claude-md | reference | new-skill | hook>
alternates: [<zero or more others from the same list>]
rationale: <one sentence>
# claude-md only, optional (A2 §3): a rules topic file, or a personal
# per-project file — omit all three for plain claude-md.
variant: <rules | local, omit for plain claude-md>
rules_topic: <kebab-slug topic — required iff variant is rules>
rules_paths: [<glob>, ...]  # optional; omit for an unpathed rule

Record:

{record_text}"""


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


def _timeout() -> float:
    raw = os.environ.get("SELF_LEARN_ANALYST_TIMEOUT")
    if not raw:
        return DEFAULT_ANALYST_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_ANALYST_TIMEOUT


def build_argv(prompt: str, doctrine_text: str, model: str) -> list[str]:
    """The literal ``claude -p`` invocation (see the module docstring)."""
    return [
        "claude",
        "-p",
        prompt,
        "--append-system-prompt",
        doctrine_text,
        "--model",
        model,
        "--allowedTools",
        ANALYST_ALLOWED_TOOLS,
    ]


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


def analyze(home: Path | str, record: Record) -> dict:
    """Run the one-shot analyst for ``record``; return a validated proposal
    dict (destination/alternates/rationale + CLI-stamped ``record_sha``,
    model, analyzed_at). Raises :class:`AnalystError` on ANY failure —
    exactly one parse attempt, no reprompt."""
    doctrine = doctrine_path()
    if not doctrine.is_file():
        # Callers check first for the pinned exit-2 message; this guard is
        # defense in depth for library use.
        raise AnalystError(f"routing doctrine not installed — T10 ({doctrine})")
    doctrine_text = doctrine.read_text(encoding="utf-8")
    model = _model()
    prompt = _PROMPT_TEMPLATE.format(record_text=record.to_text())

    argv = build_argv(prompt, doctrine_text, model)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_timeout()
        )
    except FileNotFoundError as exc:
        raise AnalystError("claude CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise AnalystError(
            f"analyst timed out after {_timeout():g}s"
        ) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise AnalystError(f"analyst exited {proc.returncode}: {detail}")

    parsed = _parse_yaml_map(proc.stdout)
    proposal = {
        "destination": parsed.get("destination"),
        "alternates": parsed.get("alternates"),
        "rationale": parsed.get("rationale"),
        "model": model,
        "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # CLI-stamped — never the model's (shared normalization fn, 08 §7.1).
        "record_sha": sha_anchor(record.body),
    }
    # A2 §4.2 sync obligation (site 2): pass the analyst's variant fields
    # through only when present, so a plain-claude-md (or non-claude-md)
    # analysis stays byte-identical (P-A6) — validate_proposal enforces
    # the §4.3 schema either way.
    for key in ("variant", "rules_topic", "rules_paths"):
        if parsed.get(key) is not None:
            proposal[key] = parsed[key]
    try:
        validate_proposal(proposal)
    except ProposalError as exc:
        raise AnalystError(f"analyst proposal invalid: {exc}") from exc
    return proposal
