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
import shlex
from pathlib import Path

from .primitives import procs

__all__ = [
    "GUARDABLE_TOOLS",
    "HOOK_EVENTS",
    "HOOK_MODES",
    "MODE_EVENTS",
    "MODE_MESSAGE_KEY",
    "MODE_VERDICTS",
    "TOOL_FIELDS",
    "WARN_MESSAGE_MAX",
    "WARN_OUTPUT_CAP",
    "COMMAND_VIEW_AWK",
    "COMMAND_VIEW_MAX_BYTES",
    "hook_event",
    "hook_message",
    "hook_mode",
    "HookCompileError",
    "command_for",
    "command_root",
    "generate_script",
    "replay_examples",
    "script_for_hook",
    "script_name",
    "settings_snippet",
    "trigger_slug",
    "validate_ere",
    "warn_context",
    "warn_output",
]

#: The tool-name set a guard may decide on — exactly the tools whose
#: ``tool_input`` field is pinned (M3-8). Anything else is refused at
#: validation: a guard without a named field would have to regex the raw
#: JSON blob, which the pin forbids.
GUARDABLE_TOOLS = ("Edit", "Write", "Bash")

#: tool_name → the ``tool_input`` key the path regex applies to (M3-8).
TOOL_FIELDS = {"Edit": "file_path", "Write": "file_path", "Bash": "command"}

#: S-73 (FW-161 items 1 and 2): what a hook does when its regex matches.
#: ``deny`` (the default, byte-unchanged) blocks the call: exit 2, a
#: one-line stderr message. ``warn`` lets the call through and hands the
#: model a message instead: exit 0 with one JSON line carrying
#: ``hookSpecificOutput.additionalContext``.
HOOK_MODES = ("deny", "warn")

#: The Claude Code hook events a generated script may register under.
HOOK_EVENTS = ("PreToolUse", "PostToolUse")

#: The events each mode may use. A deny after the call has run means
#: nothing, so ``PostToolUse`` is for ``warn`` only.
MODE_EVENTS = {"deny": ("PreToolUse",), "warn": ("PreToolUse", "PostToolUse")}

#: The hook-block key that carries each mode's message.
MODE_MESSAGE_KEY = {"deny": "deny_message", "warn": "warn_message"}

#: The two example verdicts each mode's replay checks.
MODE_VERDICTS = {"deny": ("allow", "deny"), "warn": ("allow", "warn")}

#: A warn message's own bound (newlines allowed).
WARN_MESSAGE_MAX = 2000

#: The bound on the JSON line a warn script prints, under Claude Code's own
#: cap on hook output (the hand-written precedent, git-stage-status.sh,
#: keeps the same 7,500).
WARN_OUTPUT_CAP = 7500

#: S-133: a Bash command longer than this many characters is matched raw, as
#: before S-133 -- the view below is linear, but a hook runs on every call.
COMMAND_VIEW_MAX_BYTES = 262144

#: S-133: the command view a WARNING hook on Bash matches instead of the
#: raw command, so text that only mentions a pattern (a commit message, a
#: heredoc writing a file, a comment) no longer fires the warning. POSIX
#: awk, run under ``LC_ALL=C``, reading the command on stdin. The view is
#: the command with:
#:
#: - every quoted span's content dropped, its quote marks kept (``"x y"``
#:   -> ``""``, ``'x'`` -> ``''``, ``$'x'`` -> ``$''``), so the words around
#:   it stay where they were;
#: - every heredoc body dropped (the operator, its delimiter word and the
#:   terminator line stay), ``<<-`` tab stripping included; a body with no
#:   terminator runs to the end, as bash reads it;
#: - every ``#`` comment dropped, to the end of its line (a ``#`` right
#:   after a ``)`` is part of the word, as after ``$(date)#tag``);
#: - an arithmetic ``$(( ))`` or command-position ``(( ))`` kept as it is,
#:   so its ``<<`` shift is never read as a heredoc;
#:
#: and with these kept, because they ARE commands: a ``$( )`` or backtick
#: substitution inside double quotes; the quoted payload of
#: ``sh|bash|dash|ksh|zsh|su|script ... -c`` (any option word holding a
#: ``c``, ``--`` allowed after it), of ``eval``, of ``ssh``, the first
#: argument of ``trap``, and a quoted here-string fed to a shell
#: (``bash <<< '...'``), viewed by the same rules and
#: written WITHOUT its quote marks (``bash -c 'pkill -f x'`` ->
#: ``bash -c pkill -f x``, so a regex anchored on a word boundary sees
#: the payload's first word), nested to depth 32; and the body of a heredoc fed straight to a shell
#: (``bash <<EOF``, ``ssh host sh -s <<EOF``). An unbalanced quote, an
#: unclosed ``$(`` or backtick exits 3 and prints nothing, and the hook
#: then matches the raw text. No single quote appears in the program, so
#: the generator embeds it as one bash single-quoted word.
COMMAND_VIEW_AWK = r"""
function view(str,    sS, sN, sI, sHH, sHN, r) {
    sS = S; sN = N; sI = I; sHH = HH; sHN = HN
    S = str; N = length(str); I = 1; HH = HN + 1
    DEPTH++
    if (DEPTH > 32) r = str
    else r = scan("")
    DEPTH--
    S = sS; N = sN; I = sI; HH = sHH; HN = sHN
    return r
}
function tailof(out, segs,    t) {
    t = substr(out, segs)
    if (length(t) > 256) t = substr(t, length(t) - 255)
    return t
}
function codectx(out, segs,    t) {
    t = tailof(out, segs)
    return t ~ SHELL_C || t ~ EVAL_ARGS || t ~ SSH_ARGS || t ~ TRAP_ARGS
}
function arith(st,    k, c, d) {
    d = 0; k = st
    while (k <= N) {
        c = substr(S, k, 1)
        if (c == "(") d++
        else if (c == ")") {
            if (d == 0) return (substr(S, k + 1, 1) == ")") ? k + 2 : 0
            d--
        }
        k++
    }
    return 0
}
function wordstart(    p) {
    if (I == 1) return 1
    p = substr(S, I - 1, 1)
    return index(" \t\n;&|(<>", p) > 0
}
function squote(out, segs,    k, content, force) {
    force = FORCE; FORCE = 0
    k = I + 1
    while (k <= N && substr(S, k, 1) != "\047") k++
    if (k > N) { ERR = 1; return "" }
    content = substr(S, I + 1, k - I - 1)
    I = k + 1
    if (force || codectx(out, segs)) return view(content)
    return "\047\047"
}
function ansiq(out, segs,    k, c, content, force) {
    force = FORCE; FORCE = 0
    k = I + 2
    while (k <= N) {
        c = substr(S, k, 1)
        if (c == "\\") { k += 2; continue }
        if (c == "\047") break
        k++
    }
    if (k > N) { ERR = 1; return "" }
    content = substr(S, I + 2, k - I - 2)
    I = k + 1
    if (force || codectx(out, segs)) return view(content)
    return "$\047\047"
}
function dqunescape(raw,    r, k, c, d) {
    r = ""
    for (k = 1; k <= length(raw); k++) {
        c = substr(raw, k, 1)
        if (c == "\\" && k < length(raw)) {
            d = substr(raw, k + 1, 1)
            if (index("$`\"\\", d) > 0) { r = r d; k++; continue }
            if (d == "\n") { k++; continue }
        }
        r = r c
    }
    return r
}
function dquote(out, segs,    st, c, k, subs, v, raw, force) {
    force = FORCE; FORCE = 0
    I++
    st = I; subs = ""
    while (I <= N) {
        c = substr(S, I, 1)
        if (c == "\\") { I += 2; continue }
        if (c == "\"") break
        if (c == "$" && substr(S, I + 1, 2) == "((") {
            k = arith(I + 3)
            if (k) { I = k; continue }
        }
        if (c == "$" && substr(S, I + 1, 1) == "(") {
            I += 2
            v = scan(")")
            if (ERR) return ""
            subs = subs "$(" v ")"
            continue
        }
        if (c == "`") {
            k = I + 1
            while (k <= N && substr(S, k, 1) != "`") {
                if (substr(S, k, 1) == "\\") k++
                k++
            }
            if (k > N) { ERR = 1; return "" }
            subs = subs "`" view(substr(S, I + 1, k - I - 1)) "`"
            I = k + 1
            continue
        }
        I++
    }
    if (I > N) { ERR = 1; return "" }
    raw = substr(S, st, I - st)
    I++
    if (force || codectx(out, segs)) return view(dqunescape(raw))
    return "\"" subs "\""
}
function heredoc(out, segs,    op, strip, st, delim, c, k) {
    op = "<<"; I += 2; strip = 0
    if (substr(S, I, 1) == "-") { op = op "-"; strip = 1; I++ }
    while (I <= N && index(" \t", substr(S, I, 1)) > 0) { op = op substr(S, I, 1); I++ }
    st = I; delim = ""
    while (I <= N) {
        c = substr(S, I, 1)
        if (index(" \t\n;&|()<>", c) > 0) break
        if (c == "\\") { delim = delim substr(S, I + 1, 1); I += 2; continue }
        if (c == "\047" || c == "\"") {
            k = I + 1
            while (k <= N && substr(S, k, 1) != c) {
                if (c == "\"" && substr(S, k, 1) == "\\") k++
                k++
            }
            if (k > N) { ERR = 1; return "" }
            delim = delim substr(S, I + 1, k - I - 1)
            I = k + 1
            continue
        }
        delim = delim c; I++
    }
    if (delim == "") return op substr(S, st, I - st)
    HN++
    HD[HN] = delim; HS[HN] = strip
    HC[HN] = (tailof(out, segs) ~ SHELL_STDIN)
    return op substr(S, st, I - st)
}
function bodies(    res, d, strip, code, bst, k, line, cmp, found) {
    res = ""
    while (HH <= HN) {
        d = HD[HH]; strip = HS[HH]; code = HC[HH]; HH++
        bst = I; found = 0
        while (I <= N) {
            k = I
            while (k <= N && substr(S, k, 1) != "\n") k++
            line = substr(S, I, k - I)
            cmp = line
            if (strip) sub(/^\t+/, "", cmp)
            if (cmp == d) { found = 1; break }
            I = k + 1
        }
        if (I > N + 1) I = N + 1
        if (code) res = res view(substr(S, bst, I - bst))
        if (found) {
            res = res line
            if (k <= N) res = res "\n"
            I = k + 1
        }
    }
    return res
}
function scan(stop,    out, c, depth, segs, k) {
    out = ""; depth = 0; segs = 1
    while (I <= N) {
        c = substr(S, I, 1)
        if (c == "\\") { out = out substr(S, I, 2); I += 2; continue }
        if (c == "\047") { out = out squote(out, segs); if (ERR) return out; continue }
        if (c == "\"") { out = out dquote(out, segs); if (ERR) return out; continue }
        if (c == "$" && substr(S, I + 1, 1) == "\047") {
            out = out ansiq(out, segs); if (ERR) return out; continue
        }
        if (c == "$" && substr(S, I + 1, 2) == "((") {
            k = arith(I + 3)
            if (k) { out = out substr(S, I, k - I); I = k; continue }
        }
        if (c == "(" && substr(S, I + 1, 1) == "(" && wordstart()) {
            k = arith(I + 2)
            if (k) { out = out substr(S, I, k - I); I = k; segs = length(out) + 1; continue }
        }
        if (c == "#" && wordstart()) {
            while (I <= N && substr(S, I, 1) != "\n") I++
            continue
        }
        if (c == "<" && substr(S, I + 1, 1) == "<") {
            if (substr(S, I + 2, 1) == "<") {
                k = (tailof(out, segs) ~ SHELL_STDIN)
                out = out "<<<"; I += 3
                while (I <= N && index(" \t", substr(S, I, 1)) > 0) { out = out substr(S, I, 1); I++ }
                c = substr(S, I, 1)
                FORCE = k && (c == "\047" || c == "\"" || (c == "$" && substr(S, I + 1, 1) == "\047"))
                continue
            }
            out = out heredoc(out, segs); if (ERR) return out; continue
        }
        if (c == "\n") {
            out = out c; I++
            if (HH <= HN) out = out bodies()
            segs = length(out) + 1
            continue
        }
        if (stop == ")" && c == "(") depth++
        if (stop == ")" && c == ")") {
            if (depth == 0) { I++; return out }
            depth--
        }
        out = out c; I++
        if (index(";&|()`", c) > 0) segs = length(out) + 1
    }
    if (stop != "") ERR = 1
    return out
}
BEGIN {
    RS = "\001"
    SHELL_C = "(^|[ \t/])((ba|da|k|z)?sh|su|script)([ \t]+[^ \t]+)*[ \t]+-[A-Za-z]*c[A-Za-z]*([ \t]+--)?[ \t]+$"
    EVAL_ARGS = "(^|[ \t])eval([ \t]+[^ \t]+)*[ \t]+$"
    SSH_ARGS = "(^|[ \t/])ssh([ \t]+[^ \t]+)*[ \t]+$"
    TRAP_ARGS = "(^|[ \t])trap([ \t]+--)?[ \t]+$"
    SHELL_STDIN = "(^|[ \t/])(ba|da|k|z)?sh([ \t]+-[^ \t]*)*[ \t]*$"
}
{ BUF = (NR == 1) ? $0 : BUF RS $0 }
END {
    ERR = 0; DEPTH = 0; HN = 0; HH = 1; FORCE = 0
    R = view(BUF)
    if (ERR) exit 3
    printf "%s\n", R
}
"""


def hook_mode(hook: dict) -> str:
    """The block's mode; a block (or an old placed hook's routing.hook)
    that records none is ``deny``."""
    return hook.get("mode") or "deny"


def hook_event(hook: dict) -> str:
    """The block's event; one that records none is ``PreToolUse``."""
    return hook.get("event") or "PreToolUse"


def hook_message(hook: dict) -> str:
    """The block's message, read from its mode's key."""
    return str(hook.get(MODE_MESSAGE_KEY.get(hook_mode(hook), "deny_message")) or "")

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


def command_root(claude_dir: Path | None) -> str:
    """13 §7.4 fold r1, D-d (Astra 7 — a registered command must name
    the directory the symlink actually went into): the portable
    ``$HOME/.claude`` form when ``claude_dir`` is ``None`` or the
    default runtime directory (no ``SELF_LEARN_CLAUDE_DIR`` override —
    matches the spec snippet and the doctor's own basename-only
    detection either way); the literal ``claude_dir`` path otherwise,
    so an OVERRIDE runtime directory's own registered command names
    where the symlink really lives rather than a ``$HOME`` form that
    resolves somewhere else entirely on that machine. Compares against
    ``Path("~/.claude").expanduser()`` freshly on every call (never
    cached at import time) so a test that points ``$HOME`` itself at a
    scratch directory can exercise the default branch without ever
    reading or writing the real ``~/.claude``."""
    if claude_dir is None:
        return "$HOME/.claude"
    default = Path("~/.claude").expanduser()
    if claude_dir == default:
        return "$HOME/.claude"
    return str(claude_dir)


def _absolute(p: Path) -> Path:
    """*p*, anchored to an absolute path WITHOUT resolving symlinks
    (fold r2, item E / Astra 13's relative-override half): a plain
    ``Path.cwd() / p`` join for a relative path, never
    ``Path.resolve()`` — resolving would chase a symlink component and
    could name a REAL path different from the one
    :func:`hook_activation.activate`/``.deactivate`` actually placed
    the guard symlink under (those functions anchor ``claude_dir`` the
    SAME way, once, at their own entry point — see their docstrings),
    which would make the registered command point somewhere the
    symlink itself does not live."""
    p = p.expanduser()
    return p if p.is_absolute() else Path.cwd() / p


def command_for(name: str, claude_dir: Path | None) -> str:
    """The exact command string a registration for hook ``name`` under
    ``claude_dir`` names — :func:`command_root`'s D-d root selection,
    plus fold r2, item E (Astra 13): the portable default
    (``$HOME/.claude/...``) is NEVER shell-quoted — a shell must still
    expand ``$HOME``; single-quoting it would break that expansion
    outright — emitted byte-identical to before this fold. An OVERRIDE
    directory is anchored to an absolute path (:func:`_absolute` — a
    relative ``SELF_LEARN_CLAUDE_DIR`` must still name where the
    symlink really is, regardless of the current process's cwd at
    doctor-check time) and the WHOLE command (root + ``/hooks/`` +
    name) is emitted as ONE shell argument via ``shlex.quote`` — a
    directory containing a space or any other shell metacharacter
    still names exactly the placed symlink when Claude Code's own
    shell invokes it. ``shlex.quote`` is a no-op (returns the string
    unchanged, no quotes added) for any path built only from the
    "safe" charset (letters, digits, ``@%+=:,./-``), so every existing
    override path used in this tree's own tests is unaffected."""
    root = command_root(claude_dir)
    if claude_dir is None or root == "$HOME/.claude":
        return f"{root}/hooks/{name}"
    resolved_root = str(_absolute(Path(claude_dir)))
    return shlex.quote(f"{resolved_root}/hooks/{name}")


def settings_snippet(
    tools: list[str],
    name: str,
    claude_dir: Path | None = None,
    event: str = "PreToolUse",
) -> str:
    """The M3-1 literal registration snippet. The matcher is the tool-name
    set ONLY (M3-14) — ``hook.tools`` joined with ``|``; the path regex
    lives exclusively in-script. ``event`` (S-73) is the hook event the
    entry registers under — ``PreToolUse`` unless a warning hook names
    ``PostToolUse``; the default keeps every deny snippet byte-identical.
    ``claude_dir`` (D-d, default ``None``)
    selects the command's root via :func:`command_for` — every route-
    time caller leaves it ``None`` (the printed two-step snippet stays
    the portable ``$HOME`` form, unchanged from before this amendment);
    only :mod:`hook_activation` ever passes a resolved directory, at
    the moment it actually writes the command into ``settings.json``."""
    matcher = "|".join(tools)
    command = command_for(name, claude_dir)
    if event not in HOOK_EVENTS:
        raise HookCompileError(f"event must be one of {list(HOOK_EVENTS)}, got {event!r}")
    hooks = json.dumps([{"type": "command", "command": command}])
    return f'{json.dumps(event)}: [{{"matcher": {json.dumps(matcher)}, "hooks": {hooks}}}]'


#: M-G: `grep -qE` against an empty stdin is a pattern-syntax check only
#: — no data to scan — so it is effectively instant; 5s (matches
#: `gitops._git_nolock`'s convention for "should be instant" diagnostics)
#: catches a genuine hang without pressuring routine work.
VALIDATE_ERE_TIMEOUT_S = 5.0


def validate_ere(pattern: str) -> str | None:
    """Validate ``pattern`` against the ENGINE that will run it — grep -E
    on this machine, not Python's ``re`` approximation. Returns the error
    text, or None when the pattern is usable. (grep exits 1 for
    "no match", ≥2 for a broken pattern; a `grep -qE` that somehow wedges
    on a pathological pattern — M-G's ``VALIDATE_ERE_TIMEOUT_S`` bound —
    is reported the same way, as a rejected pattern, rather than
    propagating a bounded-child exception through a validator whose whole
    contract is "return the problem, or None.")"""
    try:
        proc = procs.run_bounded(
            ["grep", "-qE", "--", pattern],
            input="",
            timeout=VALIDATE_ERE_TIMEOUT_S,
        )
    except procs.BoundedTimeout:
        return f"grep -E did not finish within {VALIDATE_ERE_TIMEOUT_S:g}s — pattern rejected"
    if proc.returncode >= 2:
        return (proc.stderr.strip() or "grep -E rejected the pattern").splitlines()[0]
    return None


def _sq(text: str) -> str:
    """Embed ``text`` in a bash single-quoted string."""
    return "'" + text.replace("'", "'\\''") + "'"


def _validate_inputs(
    record_id: str,
    tools: list[str],
    path_regex: str,
    deny_message: str,
    *,
    mode: str = "deny",
    event: str = "PreToolUse",
) -> None:
    if mode not in HOOK_MODES:
        raise HookCompileError(f"hook.mode must be one of {list(HOOK_MODES)}, got {mode!r}")
    if event not in MODE_EVENTS[mode]:
        raise HookCompileError(
            f"a {mode} hook runs on {' or '.join(MODE_EVENTS[mode])} only, got {event!r}"
        )
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
    if mode == "warn":
        if not deny_message.strip() or len(deny_message) > WARN_MESSAGE_MAX:
            raise HookCompileError(
                f"hook.warn_message must be non-empty text of at most "
                f"{WARN_MESSAGE_MAX} characters (S-73)"
            )
    elif "\n" in deny_message or not deny_message.strip():
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
    *,
    mode: str = "deny",
    event: str = "PreToolUse",
) -> str:
    """The deterministic guard script (08 §8.1 Generated-guard-shape pin).

    Byte-stable for identical inputs: no timestamps, no environment reads.

    S-73: *deny_message* is the block's message whatever its mode (the
    parameter keeps its name so every deny caller is unchanged). ``mode:
    deny`` (the default) produces exactly the bytes it always has —
    placed guards are re-derived and byte-compared (verbs m-5); ``mode:
    warn`` produces :func:`_warn_script`.
    """
    _validate_inputs(record_id, tools, path_regex, deny_message, mode=mode, event=event)
    if mode == "warn":
        return _warn_script(record_id, trigger, tools, path_regex, deny_message, event)
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
    deny_line = _sq(prefixed_message(record_id, deny_message))

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


def prefixed_message(record_id: str, message: str) -> str:
    """*message* behind ONE ``self-learn <record_id>: `` prefix, so the model
    can name the lesson a guard or warning came from.

    Congruence n5 (attention round): a stored message that already begins
    with that exact prefix (the deciding agent wrote it in) is stripped of
    it once before the prefix is added, so the guard never says
    ``self-learn lrn-…: self-learn lrn-…: …``. Only one leading copy is
    stripped, and only this record's own id."""
    prefix = f"self-learn {record_id}: "
    if message.startswith(prefix):
        message = message[len(prefix):]
    return f"{prefix}{message}"


def warn_context(record_id: str, message: str) -> str:
    """The text a warning hands the model: the block's message behind the
    same ``self-learn lrn-…:`` prefix a deny message carries
    (:func:`prefixed_message`), so the model can name the lesson it came
    from."""
    return prefixed_message(record_id, message)


def warn_output(event: str, record_id: str, message: str) -> str:
    """The one JSON line a warn script prints on a match: Claude Code
    hands ``additionalContext`` (:func:`warn_context`) to the model
    (verified live on 2.1.284 for both events, misc probe 2026-09-28).
    ``ensure_ascii=False`` keeps a multibyte message near its own size
    rather than six bytes a character. The generator and the replay both
    build it here."""
    context = warn_context(record_id, message)
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _warn_script(
    record_id: str,
    trigger: str,
    tools: list[str],
    path_regex: str,
    message: str,
    event: str,
) -> str:
    """S-73: the warning script. The same input handling as the deny
    guard — the tool name, the NAMED ``tool_input`` field (M3-8), the ERE
    through ``grep -E`` — but it FAILS OPEN: a missing jq, empty or
    malformed stdin, a regex error, or any other error exits 0 and prints
    nothing. A warning must never block a call. On a match it prints
    :func:`warn_output` and exits 0; on no match it exits 0, silent.

    The JSON line is built here, at generation, and embedded as one
    single-quoted literal (the deny guard's quoting), so the script needs
    no jq to print it and its bytes stay deterministic.

    S-133: when ``tools`` names Bash, the command is matched through
    :data:`COMMAND_VIEW_AWK` (its words, not quoted text, comments or
    heredoc bodies); any trouble there matches the raw text, as before.
    A deny guard never gets the view: quoting must not get a command past
    a guard, so a deny guard keeps matching the raw command, false
    positives included."""
    output = warn_output(event, record_id, message)
    if len(output.encode("utf-8")) > WARN_OUTPUT_CAP:
        raise HookCompileError(
            f"the warning's JSON line is {len(output.encode('utf-8'))} bytes — "
            f"over the {WARN_OUTPUT_CAP}-byte hook output cap; shorten warn_message"
        )
    name = script_name(record_id, trigger)
    matcher = "|".join(tools)
    arms = []
    seen_fields: dict[str, list[str]] = {}
    for tool in tools:
        seen_fields.setdefault(TOOL_FIELDS[tool], []).append(tool)
    for fld, fld_tools in seen_fields.items():
        arms.append(
            f"    {'|'.join(fld_tools)})\n"
            f"        VALUE=$(jq -r '.tool_input.{fld} // empty' <<<\"$INPUT\" 2>/dev/null) || exit 0\n"
            f"        ;;"
        )
    case_arms = "\n".join(arms)
    regex_sq = _sq(path_regex)
    output_sq = _sq(output)
    # S-133: a Bash command is matched through the command view, never a
    # file path; a hook guarding only Edit/Write keeps its old bytes.
    view_block = ""
    if "Bash" in tools:
        view_block = f"""
# S-133: match the command's words, not quoted text, comments or heredoc
# bodies (COMMAND_VIEW_AWK). No awk, a command over {COMMAND_VIEW_MAX_BYTES} characters, an
# unbalanced quote or any awk failure: match the raw text instead.
if [[ "$TOOL" == Bash ]] && (( ${{#VALUE}} <= {COMMAND_VIEW_MAX_BYTES} )) && command -v awk &>/dev/null; then
    VIEW=$(LC_ALL=C awk {_sq(COMMAND_VIEW_AWK)} <<<"$VALUE" 2>/dev/null) || VIEW=$VALUE
    VALUE=$VIEW
fi
"""

    return f"""#!/usr/bin/env bash
# {name} — {event} warning hook, generated by self-learn from {record_id}.
# Register manually in ~/.claude/settings.json under {event} (matcher: "{matcher}");
# the symlink into ~/.claude/hooks/ materializes via ./install.sh.
# NEVER hand-edit this file — supersede the record instead (08 §8.1
# rollback pin); a hand edit silently drifts from its record.
# WARN = exit 0 + one JSON line on stdout (additionalContext) · NO MATCH =
# exit 0, silent · any error FAILS OPEN (exit 0, silent): a warning must
# never block a call (S-73).

set -uo pipefail
trap 'exit 0' ERR

command -v jq &>/dev/null || exit 0

INPUT=$(cat) || exit 0
[[ -n "${{INPUT//[[:space:]]/}}" ]] || exit 0
TOOL=$(jq -r '.tool_name // empty' <<<"$INPUT" 2>/dev/null) || exit 0

case "$TOOL" in
{case_arms}
    *)
        exit 0
        ;;
esac

[[ -n "$VALUE" ]] || exit 0
{view_block}
# grep -E: 0 = match, 1 = no match, >= 2 = a broken regex -- only a match warns.
MATCH_RC=0
grep -qE -- {regex_sq} <<<"$VALUE" 2>/dev/null || MATCH_RC=$?
[[ "$MATCH_RC" -eq 0 ]] || exit 0

printf '%s\\n' {output_sq} || exit 0
exit 0
"""


def script_for_hook(record_id: str, trigger: str, hook: dict) -> str:
    """:func:`generate_script` for a hook block (or a routing.hook
    payload): mode, event and message read the way an old placed hook
    reads (no ``mode`` = deny, no ``event`` = PreToolUse)."""
    return generate_script(
        record_id,
        trigger,
        list(hook.get("tools") or []),
        str(hook.get("path_regex") or ""),
        hook_message(hook),
        mode=hook_mode(hook),
        event=hook_event(hook),
    )


#: M-G: the guard script is a compiled bash script of fixed, small size —
#: string comparisons and `grep -qE` against ONE value, nothing that
#: scales with repo/ledger size. 10s catches a genuine hang (a
#: pathological regex, a wedged shell) without pressuring the replay of
#: several examples in a row.
REPLAY_EXAMPLE_TIMEOUT_S = 10.0


def replay_examples(
    script_path: Path,
    examples: dict,
    hook: dict | None = None,
    record_id: str | None = None,
) -> list[str]:
    """M3-12: run the analyst's allow/deny example inputs against the
    generated script. Returns one human sentence per MISMATCH (empty =
    replay clean); the route verb aborts on any. An unexpected exit code
    (neither 0 nor 2) is always a mismatch — a guard may only allow or
    deny. A guard that does not finish within
    ``REPLAY_EXAMPLE_TIMEOUT_S`` (M-G) counts as a mismatch too — a
    wedged guard is exactly the kind of guard the replay must abort a
    route over, not one hung request that hangs the whole verb.

    S-73: *hook* is the block (or routing.hook) the script came from; a
    ``mode: warn`` block replays through :func:`_replay_warn`. ``None``,
    or a block that records no mode, replays as deny, unchanged. A warn
    replay needs *record_id*: the expected text carries the lesson's id."""
    if hook is not None and hook_mode(hook) == "warn":
        if record_id is None:
            raise HookCompileError("a warning hook's replay needs its record id")
        return _replay_warn(
            script_path, examples, hook_event(hook), record_id, hook_message(hook)
        )
    mismatches: list[str] = []
    for verdict, expected_rc in (("allow", 0), ("deny", 2)):
        for i, example in enumerate(examples.get(verdict, [])):
            try:
                proc = procs.run_bounded(
                    [str(script_path)],
                    input=json.dumps(example),
                    timeout=REPLAY_EXAMPLE_TIMEOUT_S,
                )
            except procs.BoundedTimeout:
                mismatches.append(
                    f"{verdict}[{i}] the guard did not finish within "
                    f"{REPLAY_EXAMPLE_TIMEOUT_S:g}s: {json.dumps(example)}"
                )
                continue
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


def _replay_warn(
    script_path: Path, examples: dict, event: str, record_id: str, message: str
) -> list[str]:
    """S-73: a warning hook's replay. Both verdicts exit 0, so the exit
    code alone proves nothing: an ``allow`` example must print nothing,
    and a ``warn`` example must print exactly :func:`warn_output`'s line
    for this event and message — anything else (another exit code, stray
    output, a different event or text, a timeout) is a mismatch, named
    per example."""
    mismatches: list[str] = []
    expected = json.loads(warn_output(event, record_id, message))
    for verdict in ("allow", "warn"):
        for i, example in enumerate(examples.get(verdict, [])):
            where = f"{verdict}[{i}]"
            try:
                proc = procs.run_bounded(
                    [str(script_path)],
                    input=json.dumps(example),
                    timeout=REPLAY_EXAMPLE_TIMEOUT_S,
                )
            except procs.BoundedTimeout:
                mismatches.append(
                    f"{where} the hook did not finish within "
                    f"{REPLAY_EXAMPLE_TIMEOUT_S:g}s: {json.dumps(example)}"
                )
                continue
            if proc.returncode != 0:
                mismatches.append(
                    f"{where} expected exit 0 but the warning hook exited "
                    f"{proc.returncode}: {json.dumps(example)}"
                )
                continue
            out = proc.stdout.strip()
            if verdict == "allow":
                if out:
                    mismatches.append(
                        f"{where} expected no warning but the hook warned: "
                        f"{json.dumps(example)}"
                    )
                continue
            if not out:
                mismatches.append(
                    f"{where} expected a warning but the hook printed nothing: "
                    f"{json.dumps(example)}"
                )
                continue
            try:
                got = json.loads(out)
            except ValueError:
                got = None
            if got != expected:
                mismatches.append(
                    f"{where} expected the {event} warning with the block's "
                    f"message but the hook printed {out[:200]!r}: {json.dumps(example)}"
                )
    return mismatches
