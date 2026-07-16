"""T17 — the hook compiler's pure half (08 §8.1 pins; 02 §1 hook extension).

Deterministic generation of PreToolUse guard scripts from a hook
proposal's structured compile input — ``hook: {tools, path_regex,
deny_message}`` — plus the pinned settings.json snippet and the M3-12
replay machinery. No git, no ledger I/O: the route verb (verbs.py) owns
placement, approval flow, and commits.

Pins implemented here, by row:

- **Filename (M3-6):** ``self-learn-<8hex-id>-<slug>.sh`` — id WITHOUT
  the ``lrn-`` prefix; slug = kebab-case of the first ≤4 Trigger words,
  ``[a-z0-9-]``, ≤32 chars.
- **Snippet template (M3-1/M3-14, literal):** ``"PreToolUse":
  [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command":
  "$HOME/.claude/hooks/<name>"}]}]`` — the matcher is the TOOL-NAME set
  only (``hook.tools`` joined with ``|``); the path regex lives
  exclusively in-script (a path regex in the matcher field never fires).
- **Generated guard shape (ground-truthed against organizer-guard.sh):**
  read the hook JSON from stdin; decide on ``tool_name`` ∈ the pinned
  set plus a path regex applied to the NAMED ``tool_input`` field —
  ``Edit``/``Write`` → ``.tool_input.file_path``, ``Bash`` →
  ``.tool_input.command`` (M3-8; never regex the raw JSON blob); deny =
  exit 2 with a one-line stderr message citing the rule and the record
  id (``self-learn lrn-…: <message>``); allow = exit 0; malformed stdin
  fails closed (ERR trap, the precedent's pattern). One hardening beyond
  the precedent: ``grep -E`` returning ≥2 (regex error) is caught
  explicitly and FAILS CLOSED — inside an ``if`` condition it would
  otherwise fall through to allow.
- **Replay (M3-12):** analyst-authored allow/deny example inputs are run
  against the generated script; the route verb aborts on any mismatch
  BEFORE committing. :func:`replay_examples` is that machinery; the
  per-guard cases ride each proposal.

Determinism is load-bearing: the script text carries no timestamps and
reads no environment, so the bytes the human approved in the proposal
are reproducible from the structured input alone (recompile re-applies
the APPROVED bytes stored on the routing block — never a regeneration
from changed inputs; 08 §8.1 hook-apply pin).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

__all__ = [
    "GUARDABLE_TOOLS",
    "TOOL_FIELDS",
    "HookCompileError",
    "generate_script",
    "replay_examples",
    "script_name",
    "settings_snippet",
    "trigger_slug",
    "validate_ere",
]

#: The tool-name set a guard may decide on — exactly the tools whose
#: ``tool_input`` field is pinned (M3-8). Anything else is refused at
#: validation: a guard without a named field would have to regex the raw
#: JSON blob, which the pin forbids.
GUARDABLE_TOOLS = ("Edit", "Write", "Bash")

#: tool_name → the ``tool_input`` key the path regex applies to (M3-8).
TOOL_FIELDS = {"Edit": "file_path", "Write": "file_path", "Bash": "command"}

_SLUG_WORD_RE = re.compile(r"[a-z0-9]+")


class HookCompileError(Exception):
    """The structured compile input violates a §8.1 pin."""


def trigger_slug(trigger: str) -> str:
    """M3-6 slug: kebab-case of the first ≤4 Trigger words, charset
    ``[a-z0-9-]``, ≤32 chars. Refuses a trigger with no sluggable words —
    a Trigger that yields none is not a firing condition (doctrine §6)."""
    words = _SLUG_WORD_RE.findall(trigger.lower())[:4]
    slug = "-".join(words)[:32].strip("-")
    if not slug:
        raise HookCompileError(
            f"cannot derive a slug from trigger {trigger!r} — no [a-z0-9] words"
        )
    return slug


def _id8(record_id: str) -> str:
    """The 8-hex id without the ``lrn-`` prefix (M3-6)."""
    return record_id.removeprefix("lrn-")


def script_name(record_id: str, trigger: str) -> str:
    return f"self-learn-{_id8(record_id)}-{trigger_slug(trigger)}.sh"


def settings_snippet(tools: list[str], name: str) -> str:
    """The M3-1 literal registration snippet. The matcher is the tool-name
    set ONLY (M3-14) — ``hook.tools`` joined with ``|``; the path regex
    lives exclusively in-script."""
    matcher = "|".join(tools)
    hooks = json.dumps(
        [{"type": "command", "command": f"$HOME/.claude/hooks/{name}"}]
    )
    return f'"PreToolUse": [{{"matcher": {json.dumps(matcher)}, "hooks": {hooks}}}]'


def validate_ere(pattern: str) -> str | None:
    """Validate ``pattern`` against the ENGINE that will run it — grep -E
    on this machine, not Python's ``re`` approximation. Returns the error
    text, or None when the pattern is usable. (grep exits 1 for
    "no match", ≥2 for a broken pattern.)"""
    proc = subprocess.run(
        ["grep", "-qE", "--", pattern],
        input="",
        capture_output=True,
        text=True,
    )
    if proc.returncode >= 2:
        return (proc.stderr.strip() or "grep -E rejected the pattern").splitlines()[0]
    return None


def _sq(text: str) -> str:
    """Embed ``text`` in a bash single-quoted string."""
    return "'" + text.replace("'", "'\\''") + "'"


def _validate_inputs(
    record_id: str, tools: list[str], path_regex: str, deny_message: str
) -> None:
    if not tools:
        raise HookCompileError("hook.tools must name at least one tool")
    bad = [t for t in tools if t not in GUARDABLE_TOOLS]
    if bad:
        raise HookCompileError(
            f"hook.tools may only name {list(GUARDABLE_TOOLS)} — the tools "
            f"with a pinned tool_input field (M3-8); got {bad}"
        )
    if len(set(tools)) != len(tools):
        raise HookCompileError(f"hook.tools has duplicates: {tools}")
    if not path_regex or not path_regex.strip():
        raise HookCompileError("hook.path_regex must be non-empty")
    if "\n" in deny_message or not deny_message.strip():
        raise HookCompileError(
            "hook.deny_message must be non-empty and one line — the pinned "
            "deny is a ONE-line stderr message (08 §8.1)"
        )
    if not re.fullmatch(r"lrn-[0-9a-f]{8}", record_id):
        raise HookCompileError(f"not a record id: {record_id!r}")


def generate_script(
    record_id: str,
    trigger: str,
    tools: list[str],
    path_regex: str,
    deny_message: str,
) -> str:
    """The deterministic guard script (08 §8.1 Generated-guard-shape pin).

    Byte-stable for identical inputs: no timestamps, no environment reads.
    """
    _validate_inputs(record_id, tools, path_regex, deny_message)
    name = script_name(record_id, trigger)
    matcher = "|".join(tools)

    # One case arm per distinct tool_input field, tools grouped (M3-8).
    arms = []
    seen_fields: dict[str, list[str]] = {}
    for tool in tools:
        seen_fields.setdefault(TOOL_FIELDS[tool], []).append(tool)
    for fld, fld_tools in seen_fields.items():
        arms.append(
            f"    {'|'.join(fld_tools)})\n"
            f"        VALUE=$(jq -r '.tool_input.{fld} // empty' <<<\"$INPUT\")\n"
            f"        ;;"
        )
    case_arms = "\n".join(arms)

    regex_sq = _sq(path_regex)
    deny_line = _sq(f"self-learn {record_id}: {deny_message}")

    return f"""#!/usr/bin/env bash
# {name} — PreToolUse guard, generated by self-learn from {record_id}.
# Register manually in ~/.claude/settings.json (matcher: "{matcher}");
# the symlink into ~/.claude/hooks/ materializes via ./install.sh.
# NEVER hand-edit this file — supersede the record instead (08 §8.1
# rollback pin); a hand edit silently drifts from its record.
# DENY = exit 2 (stderr shown) · ALLOW = exit 0 · malformed input FAILS
# CLOSED (precedent: universal-directory-organizer/organizer-guard.sh).

set -uo pipefail
trap 'echo "self-learn {record_id}: guard error on line $LINENO — failing closed" >&2; exit 2' ERR

if ! command -v jq &>/dev/null; then
    echo "self-learn {record_id}: jq required but not found — failing closed" >&2
    exit 2
fi

INPUT=$(cat)
# Empty stdin is malformed input, not "no tool" — fail closed. (jq exits 0
# with no output on empty input, which would otherwise fall through to
# the allow arm below.)
if [[ -z "${{INPUT//[[:space:]]/}}" ]]; then
    echo "self-learn {record_id}: empty hook input — failing closed" >&2
    exit 2
fi
TOOL=$(jq -r '.tool_name // empty' <<<"$INPUT")

case "$TOOL" in
{case_arms}
    *)
        # Not a guarded tool — the matcher should prevent this; allow.
        trap - ERR
        exit 0
        ;;
esac

# Named field absent/empty: nothing to match against — allow (precedent).
if [[ -z "$VALUE" ]]; then
    trap - ERR
    exit 0
fi

# Pre-flight the pattern itself: grep -E rc ≥ 2 = broken regex. Inside an
# `if` a grep error would fall through to ALLOW — catch it and fail closed.
PROBE_RC=0
grep -qE -- {regex_sq} <<<"" || PROBE_RC=$?
if [[ "$PROBE_RC" -ge 2 ]]; then
    echo "self-learn {record_id}: guard regex is invalid — failing closed" >&2
    exit 2
fi

MATCH_RC=0
grep -qE -- {regex_sq} <<<"$VALUE" || MATCH_RC=$?
if [[ "$MATCH_RC" -eq 0 ]]; then
    echo {deny_line} >&2
    exit 2
fi
if [[ "$MATCH_RC" -ge 2 ]]; then
    echo "self-learn {record_id}: guard regex failed — failing closed" >&2
    exit 2
fi

trap - ERR
exit 0
"""


def replay_examples(script_path: Path, examples: dict) -> list[str]:
    """M3-12: run the analyst's allow/deny example inputs against the
    generated script. Returns one human sentence per MISMATCH (empty =
    replay clean); the route verb aborts on any. An unexpected exit code
    (neither 0 nor 2) is always a mismatch — a guard may only allow or
    deny."""
    mismatches: list[str] = []
    for verdict, expected_rc in (("allow", 0), ("deny", 2)):
        for i, example in enumerate(examples.get(verdict, [])):
            proc = subprocess.run(
                [str(script_path)],
                input=json.dumps(example),
                capture_output=True,
                text=True,
            )
            if proc.returncode != expected_rc:
                got = {0: "allowed", 2: "denied"}.get(
                    proc.returncode, f"exit {proc.returncode}"
                )
                mismatches.append(
                    f"{verdict}[{i}] expected {verdict} but the guard "
                    f"{got}: {json.dumps(example)}"
                    + (f" (stderr: {proc.stderr.strip()})" if proc.stderr.strip() else "")
                )
    return mismatches
