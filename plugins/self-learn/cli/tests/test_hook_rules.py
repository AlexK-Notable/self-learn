"""Lane 5R: the rule artifact and its evaluator (``self_learn.hook_rules``).

Two halves.

- **Linux differential** (``_DIFF`` skip mark: Linux with bash, jq, grep,
  cat and awk). For every hook-bearing fixture record the other tests use,
  and for a table of rules covering every rule kind and every dialect
  construct the evaluator accepts, the REAL generated Bash script and the
  evaluator decide the same stdin, and must give the same exit code, the
  same stdout bytes and the same stderr text. The one stderr difference
  allowed: lines jq, grep or bash write about themselves (``jq: parse
  error ...``, bash's ``ignored null byte`` warning); the script's own
  lines must be identical, and the evaluator never writes such a line.
  The S-133 command view is compared against the awk program itself, under
  every awk on the machine, and the character classes against grep.
- **Everywhere, Windows included**: the evaluator alone on recorded
  decisions (literals the differential also checks against Bash on Linux),
  artifact load / validate / digest refusal, the refusal table, and the
  matching bound.

Scripts run with ``PATH`` holding only the five tools and ``LC_ALL=C.UTF-8``
(the dialect the artifact names). Nothing here reads or writes a ledger.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from self_learn import hook_compiler, hook_rules, hook_rules_ctype
from self_learn.hook_rules import RuleError

RID = "lrn-5a5e0001"
TRIGGER = "About to run a guarded thing"

_LINUX = sys.platform.startswith("linux")
LINUX_REASON = "Linux differential: compares against the generated Bash script"
_TOOLS = ("bash", "jq", "grep", "cat", "awk")
_MISSING = [t for t in _TOOLS if shutil.which(t) is None]
if not _LINUX:
    _SKIP: str | None = LINUX_REASON
elif _MISSING:
    _SKIP = f"needs {', '.join(_TOOLS)} on PATH; missing: {', '.join(_MISSING)}"
else:
    _SKIP = None
_DIFF = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")

#: The allowed stderr difference: diagnostics the tools write themselves.
_DIAG = re.compile(r"^(jq: |grep: |.*: warning: command substitution: ignored null byte in input$)")


def _payload(tool: str, field: str, value) -> bytes:
    return json.dumps({"tool_name": tool, "tool_input": {field: value}}).encode("utf-8")


def _cmd(value) -> bytes:
    return _payload("Bash", "command", value)


def _path(value, tool: str = "Edit") -> bytes:
    return _payload(tool, "file_path", value)


def _nest(kind: str, n: int, inner: str = "0") -> str:
    """*inner* inside *n* nested arrays (``kind="["``) or objects."""
    if kind == "[":
        return "[" * n + inner + "]" * n
    return '{"a":' * n + inner + "}" * n


def _deep(kind: str, n: int, command: str = "git status") -> bytes:
    """A Bash event with an unrelated field nested *n* deep inside it."""
    return ('{"tool_name":"Bash","tool_input":{"command":' + json.dumps(command)
            + '},"nest":' + _nest(kind, n) + "}").encode()


def _rule(name: str) -> hook_rules.Rule:
    tools, regex, message, mode, event = CASE_RULES[name]
    return hook_rules.load_rule(hook_compiler.rule_artifact(
        RID, TRIGGER, tools, regex, message, mode=mode, event=event))


# ===================================================================
# Recorded decisions (run everywhere; checked against Bash on Linux)
# ===================================================================

#: name -> (tools, regex, message, mode, event)
CASE_RULES = {
    "deny-bash": (["Bash"], r"(^|[;&|[:space:]])git[[:space:]]+push([[:space:]]|$)",
                  "no pushing from here", "deny", "PreToolUse"),
    "deny-file": (["Edit", "Write"], r"\.storage/", "stop HA first", "deny", "PreToolUse"),
    "deny-mixed": (["Edit", "Bash"], r"\bsecret\b", "no secrets", "deny", "PreToolUse"),
    "deny-push": (["Bash"], r"push", "no push", "deny", "PreToolUse"),
    "deny-number": (["Bash"], r"^1E\+2$|^-0$|^1\.50$", "numbers", "deny", "PreToolUse"),
    "deny-classes": (["Bash"], r"[[:upper:]][[:digit:]]{2,}\W", "classes", "deny", "PreToolUse"),
    "deny-word": (["Bash"], r"\<sudo\>", "no sudo", "deny", "PreToolUse"),
    "deny-three": (["Bash"], r"^.{3}$", "three", "deny", "PreToolUse"),
    "deny-fffd": (["Bash"], "^a�b$|^�$|^a��b$", "replacement", "deny",
                  "PreToolUse"),
    "deny-render": (["Bash"], r'u007f|u0001|\\[btnfr"\\]|"/"', "rendered", "deny", "PreToolUse"),
    "deny-huge": (["Bash"], r"^1[.]797|^1E\+1000000000$", "huge", "deny", "PreToolUse"),
    "deny-int": (["Bash"], r"^9007199254740992$|^-9007199254740992$|^0$|^42$|^900719925474099[34]$",
                 "integers", "deny", "PreToolUse"),
    "deny-nested": (["Bash"], r"git push|^\[$", "nested", "deny", "PreToolUse"),
    "warn-bash": (["Bash"], r"pkill[[:space:]]+-f", "careful with -f", "warn", "PreToolUse"),
    "warn-post": (["Bash", "Edit"], r"pkill[[:space:]]+-f",
                  "careful: é \"quoted\"\nsecond line", "warn", "PostToolUse"),
    "warn-file": (["Write"], r"db/migrations/", "run the check", "warn", "PostToolUse"),
}

#: (case id, rule name, stdin bytes)
CASES = [
    ("bash-match", "deny-bash", _cmd("git push origin x")),
    ("bash-no-match", "deny-bash", _cmd("git status")),
    ("bash-second-line", "deny-bash", _cmd("echo a\ngit push")),
    ("bash-empty-stdin", "deny-bash", b""),
    ("bash-blank-stdin", "deny-bash", b" \n\t\r\n"),
    ("bash-unicode-blank", "deny-bash", "　  \n".encode()),
    ("bash-nbsp-not-blank", "deny-bash", " ".encode()),
    ("bash-nul-only-stdin", "deny-bash", b"\x00\x00\n"),
    ("warn-nul-only-stdin", "warn-bash", b"\x00"),
    ("bash-malformed", "deny-bash", b'{"tool_name":'),
    ("bash-top-array", "deny-bash", b"[1]"),
    ("bash-top-null", "deny-bash", b"null"),
    ("bash-tool-input-string", "deny-bash", b'{"tool_name":"Bash","tool_input":"git push"}'),
    ("bash-no-tool-input", "deny-bash", b'{"tool_name":"Bash"}'),
    ("bash-command-null", "deny-bash", _cmd(None)),
    ("bash-command-false", "deny-bash", _cmd(False)),
    ("bash-command-empty", "deny-bash", _cmd("")),
    ("bash-command-newlines", "deny-bash", _cmd("\n\n")),
    ("bash-other-tool", "deny-bash", _path("git push", "Edit")),
    ("bash-nul-in-name", "deny-bash", b'{"tool_name":"Ba\x00sh","tool_input":{"command":"git push"}}'),
    ("bash-escaped-nul", "deny-bash", _cmd("git\u0000 push")),
    ("bash-stream", "deny-bash", b'{"tool_name":"Bash"} {"tool_input":{"command":"git push"}}'),
    ("bash-stream-two-names", "deny-bash",
     b'{"tool_name":"Bash","tool_input":{"command":"git push"}}{"tool_name":"Bash"}'),
    ("bash-bom", "deny-bash", b"\xef\xbb\xbf" + _cmd("git push")),
    ("bash-literal-run", "deny-bash", _cmd("git push") + b"null"),
    ("bash-trailing-junk", "deny-bash", _cmd("git push") + b" x"),
    ("bash-lone-high-surrogate", "deny-bash", b'{"tool_name":"Bash","tool_input":{"command":"\\ud800 git push"}}'),
    ("bash-high-then-not-low", "deny-bash",
     b'{"tool_name":"Bash","tool_input":{"command":"\\ud800\\u0041 git push"}}'),
    ("render-del", "deny-render", _cmd(["\x7f"])),
    ("render-control", "deny-render", _cmd(["\x01"])),
    ("render-backspace", "deny-render", _cmd({"k": "\b"})),
    ("render-quote-in-key", "deny-render", _cmd({'"': 1})),
    ("render-slash-raw", "deny-render", _cmd(["/"])),
    ("render-unicode-raw", "deny-render", _cmd(["é "])),
    ("render-raw-string", "deny-render", _cmd("\x7f\x01")),
    ("bash-raw-control", "deny-bash", b'{"tool_name":"Bash","tool_input":{"command":"git\tpush"}}'),
    ("bash-long", "deny-bash", _cmd("x" * 50000 + " git push")),
    ("file-edit-match", "deny-file", _path("/c/.storage/core")),
    ("file-write-no-match", "deny-file", _path("/c/storage/core", "Write")),
    ("file-bash-other", "deny-file", _cmd(".storage/")),
    ("mixed-edit", "deny-mixed", _path("/x/secret/y")),
    ("mixed-bash", "deny-mixed", _cmd("cat secret.txt")),
    ("mixed-bash-no", "deny-mixed", _cmd("cat secretive.txt")),
    ("mixed-edit-wrong-field", "deny-mixed", b'{"tool_name":"Edit","tool_input":{"command":"secret"}}'),
    ("mixed-write-other", "deny-mixed", _path("/x/secret", "Write")),
    ("push-array", "deny-push", _cmd(["git", "push"])),
    ("push-object", "deny-push", _cmd({"push": 1})),
    ("push-number", "deny-push", _cmd(5)),
    ("push-true", "deny-push", _cmd(True)),
    ("number-exponent", "deny-number", b'{"tool_name":"Bash","tool_input":{"command":1e2}}'),
    ("number-negative-zero", "deny-number", b'{"tool_name":"Bash","tool_input":{"command":-0}}'),
    ("number-trailing-zero", "deny-number", b'{"tool_name":"Bash","tool_input":{"command":1.50}}'),
    ("number-huge-exponent", "deny-huge", b'{"tool_name":"Bash","tool_input":{"command":1e1000000000}}'),
    ("number-giant-exponent", "deny-huge",
     b'{"tool_name":"Bash","tool_input":{"command":1e9999999999999999999999999}}'),
    ("number-max-safe", "deny-int", _cmd(9007199254740992)),
    ("number-min-safe", "deny-int", _cmd(-9007199254740992)),
    ("number-zero", "deny-int", _cmd(0)),
    ("number-in-array", "deny-int", _cmd([42])),
    ("number-past-safe", "deny-int", b'{"tool_name":"Bash","tool_input":{"command":9007199254740993}}'),
    ("number-past-safe-no-match", "deny-int",
     b'{"tool_name":"Bash","tool_input":{"command":9007199254740995}}'),
    ("number-tool-name", "deny-bash", b'{"tool_name":1.5,"tool_input":{"command":"git push"}}'),
    ("stream-number-then-event-warn", "warn-bash", b"3 " + _cmd("pkill -f x")),
    ("stream-true-then-empty", "deny-bash", b"true{}"),
    ("stream-event-then-number", "deny-bash", _cmd("git push") + b" 3"),
    ("lenient-unrelated-warn", "warn-bash",
     b'{"tool_name":"Bash","tool_input":{"command":"pkill -f x"},"n":01}'),
    ("lenient-unrelated-deny", "deny-bash",
     b'{"tool_name":"Bash","tool_input":{"command":"git push"},"n":01}'),
    ("lenient-nan-name", "deny-bash", b'{"tool_name":nan}'),
    ("depth-arrays-under-old-limit", "deny-bash", _deep("[", 254)),
    ("depth-arrays-at-old-limit", "deny-bash", _deep("[", 255)),
    ("depth-arrays-under-limit", "deny-bash", _deep("[", 9998)),
    ("depth-arrays-at-limit", "deny-bash", _deep("[", 9999)),
    ("depth-objects-under-limit", "deny-bash", _deep("{", 4999)),
    ("depth-objects-at-limit", "deny-bash", _deep("{", 5000)),
    ("depth-deep-then-junk", "deny-bash", _deep("[", 300) + b" x"),
    ("depth-selected-field", "deny-nested", _cmd(json.loads(_nest("[", 650, '"git push"')))),
    ("depth-selected-shallow", "deny-nested", _cmd(json.loads(_nest("[", 3, '"git push"')))),
    ("classes-upper-digits", "deny-classes", _cmd("A12;")),
    ("classes-lower", "deny-classes", _cmd("a12;")),
    ("classes-accented-upper", "deny-classes", _cmd("É12;")),
    ("classes-arabic-digits", "deny-classes", _cmd("A١٢;")),
    ("word-match", "deny-word", _cmd("sudo ls")),
    ("word-inside", "deny-word", _cmd("pseudo ls")),
    ("word-underscore", "deny-word", _cmd("sudo_x")),
    ("word-after-accent", "deny-word", _cmd("ésudo")),
    ("three-multibyte", "deny-three", _cmd("aé€")),
    ("three-short", "deny-three", _cmd("ab")),
    ("fffd-bad-byte", "deny-fffd", b'{"tool_name":"Bash","tool_input":{"command":"a\xffb"}}'),
    ("fffd-truncated-swallows", "deny-fffd", b'{"tool_name":"Bash","tool_input":{"command":"\xe2a"}}'),
    ("fffd-two-bytes", "deny-fffd", b'{"tool_name":"Bash","tool_input":{"command":"a\xc0\xafb"}}'),
    ("fffd-lone-low", "deny-fffd", b'{"tool_name":"Bash","tool_input":{"command":"\\udc00"}}'),
    ("warn-match", "warn-bash", _cmd("pkill -f node")),
    ("warn-no-match", "warn-bash", _cmd("pkill node")),
    ("warn-commit-message-hidden", "warn-bash", _cmd("git commit -m 'never pkill -f x'")),
    ("warn-single-quotes-raw", "warn-bash", _cmd("echo 'pkill -f x'")),
    ("warn-heredoc-file-hidden", "warn-bash", _cmd("cat > n.md <<'E'\npkill -f x\nE")),
    ("warn-malformed", "warn-bash", b"{"),
    ("warn-empty", "warn-bash", b""),
    ("warn-tool-input-string", "warn-bash", b'{"tool_name":"Bash","tool_input":"x"}'),
    ("post-match", "warn-post", _cmd("pkill -f x")),
    ("post-edit-raw", "warn-post", _path("git commit -m 'pkill -f x'")),
    ("post-edit-no", "warn-post", _path("/x/y")),
    ("file-warn-match", "warn-file", _path("/r/db/migrations/1.sql", "Write")),
    ("file-warn-other-tool", "warn-file", _path("/r/db/migrations/1.sql", "Edit")),
]

#: Recorded from the generated Bash scripts under LC_ALL=C.UTF-8 (jq 1.8.2,
#: GNU grep 3.12, gawk 5.4, bash 5.3); the differential below re-checks every
#: row against the real script on each Linux run.
EXPECTED: dict[str, tuple[int, bytes, str]] = {
    'bash-match': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'bash-no-match': (0, b'', ''),
    'bash-second-line': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'bash-empty-stdin': (2, b'', 'self-learn lrn-5a5e0001: empty hook input — failing closed\n'),
    'bash-blank-stdin': (2, b'', 'self-learn lrn-5a5e0001: empty hook input — failing closed\n'),
    'bash-unicode-blank': (2, b'', 'self-learn lrn-5a5e0001: empty hook input — failing closed\n'),
    'bash-nbsp-not-blank': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'bash-nul-only-stdin': (2, b'', 'self-learn lrn-5a5e0001: empty hook input — failing closed\n'),
    'warn-nul-only-stdin': (0, b'', ''),
    'bash-malformed': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'bash-top-array': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'bash-top-null': (0, b'', ''),
    'bash-tool-input-string': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 30 — failing closed\n'),
    'bash-no-tool-input': (0, b'', ''),
    'bash-command-null': (0, b'', ''),
    'bash-command-false': (0, b'', ''),
    'bash-command-empty': (0, b'', ''),
    'bash-command-newlines': (0, b'', ''),
    'bash-other-tool': (0, b'', ''),
    'bash-nul-in-name': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'bash-escaped-nul': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'bash-stream': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'bash-stream-two-names': (0, b'', ''),
    'bash-bom': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'bash-literal-run': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'bash-trailing-junk': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'bash-lone-high-surrogate': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'bash-high-then-not-low': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'render-del': (2, b'', 'self-learn lrn-5a5e0001: rendered\n'),
    'render-control': (2, b'', 'self-learn lrn-5a5e0001: rendered\n'),
    'render-backspace': (2, b'', 'self-learn lrn-5a5e0001: rendered\n'),
    'render-quote-in-key': (2, b'', 'self-learn lrn-5a5e0001: rendered\n'),
    'render-slash-raw': (2, b'', 'self-learn lrn-5a5e0001: rendered\n'),
    'render-unicode-raw': (0, b'', ''),
    'render-raw-string': (0, b'', ''),
    'bash-raw-control': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'bash-long': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'file-edit-match': (2, b'', 'self-learn lrn-5a5e0001: stop HA first\n'),
    'file-write-no-match': (0, b'', ''),
    'file-bash-other': (0, b'', ''),
    'mixed-edit': (2, b'', 'self-learn lrn-5a5e0001: no secrets\n'),
    'mixed-bash': (2, b'', 'self-learn lrn-5a5e0001: no secrets\n'),
    'mixed-bash-no': (0, b'', ''),
    'mixed-edit-wrong-field': (0, b'', ''),
    'mixed-write-other': (0, b'', ''),
    'push-array': (2, b'', 'self-learn lrn-5a5e0001: no push\n'),
    'push-object': (2, b'', 'self-learn lrn-5a5e0001: no push\n'),
    'push-number': (0, b'', ''),
    'push-true': (0, b'', ''),
    'number-exponent': (2, b'', 'self-learn lrn-5a5e0001: numbers\n'),
    'number-negative-zero': (2, b'', 'self-learn lrn-5a5e0001: numbers\n'),
    'number-trailing-zero': (2, b'', 'self-learn lrn-5a5e0001: numbers\n'),
    'number-huge-exponent': (2, b'', 'self-learn lrn-5a5e0001: huge\n'),
    'number-giant-exponent': (2, b'', 'self-learn lrn-5a5e0001: huge\n'),
    'number-max-safe': (2, b'', 'self-learn lrn-5a5e0001: integers\n'),
    'number-min-safe': (2, b'', 'self-learn lrn-5a5e0001: integers\n'),
    'number-zero': (2, b'', 'self-learn lrn-5a5e0001: integers\n'),
    'number-in-array': (0, b'', ''),
    'number-past-safe': (2, b'', 'self-learn lrn-5a5e0001: integers\n'),
    'number-past-safe-no-match': (0, b'', ''),
    'number-tool-name': (0, b'', ''),
    'stream-number-then-event-warn': (0, b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"self-learn lrn-5a5e0001: careful with -f"}}\n', ''),
    'stream-true-then-empty': (0, b'', ''),
    'stream-event-then-number': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'lenient-unrelated-warn': (0, b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"self-learn lrn-5a5e0001: careful with -f"}}\n', ''),
    'lenient-unrelated-deny': (2, b'', 'self-learn lrn-5a5e0001: no pushing from here\n'),
    'lenient-nan-name': (0, b'', ''),
    'depth-arrays-under-old-limit': (0, b'', ''),
    'depth-arrays-at-old-limit': (0, b'', ''),
    'depth-arrays-under-limit': (0, b'', ''),
    'depth-arrays-at-limit': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'depth-objects-under-limit': (0, b'', ''),
    'depth-objects-at-limit': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'depth-deep-then-junk': (2, b'', 'self-learn lrn-5a5e0001: guard error on line 26 — failing closed\n'),
    'depth-selected-field': (2, b'', 'self-learn lrn-5a5e0001: nested\n'),
    'depth-selected-shallow': (2, b'', 'self-learn lrn-5a5e0001: nested\n'),
    'classes-upper-digits': (2, b'', 'self-learn lrn-5a5e0001: classes\n'),
    'classes-lower': (0, b'', ''),
    'classes-accented-upper': (2, b'', 'self-learn lrn-5a5e0001: classes\n'),
    'classes-arabic-digits': (0, b'', ''),
    'word-match': (2, b'', 'self-learn lrn-5a5e0001: no sudo\n'),
    'word-inside': (0, b'', ''),
    'word-underscore': (0, b'', ''),
    'word-after-accent': (0, b'', ''),
    'three-multibyte': (2, b'', 'self-learn lrn-5a5e0001: three\n'),
    'three-short': (0, b'', ''),
    'fffd-bad-byte': (2, b'', 'self-learn lrn-5a5e0001: replacement\n'),
    'fffd-truncated-swallows': (2, b'', 'self-learn lrn-5a5e0001: replacement\n'),
    'fffd-two-bytes': (2, b'', 'self-learn lrn-5a5e0001: replacement\n'),
    'fffd-lone-low': (2, b'', 'self-learn lrn-5a5e0001: replacement\n'),
    'warn-match': (0, b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"self-learn lrn-5a5e0001: careful with -f"}}\n', ''),
    'warn-no-match': (0, b'', ''),
    'warn-commit-message-hidden': (0, b'', ''),
    'warn-single-quotes-raw': (0, b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"self-learn lrn-5a5e0001: careful with -f"}}\n', ''),
    'warn-heredoc-file-hidden': (0, b'', ''),
    'warn-malformed': (0, b'', ''),
    'warn-empty': (0, b'', ''),
    'warn-tool-input-string': (0, b'', ''),
    'post-match': (0, b'{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"self-learn lrn-5a5e0001: careful: \xc3\xa9 \\"quoted\\"\\nsecond line"}}\n', ''),
    'post-edit-raw': (0, b'{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"self-learn lrn-5a5e0001: careful: \xc3\xa9 \\"quoted\\"\\nsecond line"}}\n', ''),
    'post-edit-no': (0, b'', ''),
    'file-warn-match': (0, b'{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"self-learn lrn-5a5e0001: run the check"}}\n', ''),
    'file-warn-other-tool': (0, b'', ''),
}


#: Cases the evaluator cannot reproduce exactly, so it fails closed: a deny
#: rule blocks with its own labelled line, a warning stays silent. Each is a
#: number jq prints in a form not modelled (or that differs between jq
#: releases), a number only jq's lenient grammar reads, or nesting that jq
#: 1.6-1.7 refuse and 1.8 reads. EXPECTED keeps the script's own answer; the
#: Linux differential checks the evaluator never allows where it denies.
FAILS_CLOSED = {
    "number-exponent", "number-negative-zero", "number-trailing-zero", "number-huge-exponent",
    "number-giant-exponent", "number-past-safe", "number-past-safe-no-match",
    "number-tool-name", "lenient-unrelated-warn", "lenient-unrelated-deny", "lenient-nan-name",
    "depth-arrays-at-old-limit", "depth-arrays-under-limit", "depth-objects-under-limit",
    "depth-selected-field",
}


def _fail_closed(mode: str) -> tuple[int, bytes, str]:
    if mode == "deny":
        return (2, b"", f"self-learn {RID}: {hook_rules.EVALUATOR_INEXACT} — failing closed\n")
    return (0, b"", "")


@pytest.mark.parametrize("case", [c[0] for c in CASES])
def test_recorded_decision(case):
    _, rule_name, data = next(c for c in CASES if c[0] == case)
    got = hook_rules.evaluate(_rule(rule_name), data)
    if case in FAILS_CLOSED:
        assert (got.exit_code, got.stdout, got.stderr) == _fail_closed(CASE_RULES[rule_name][3])
        assert got.reason == "inexact"
    else:
        assert (got.exit_code, got.stdout, got.stderr) == EXPECTED[case]
        assert got.reason != "inexact"


# ===================================================================
# The fixture rules the other tests use (copies, pinned to their
# originals on Linux by test_fixture_copies_match_their_sources)
# ===================================================================

_PGREP_REGEX = r"(^|[;&|(`[:space:]])p(kill|grep)([[:space:]]+-[^[:space:]]+)*[[:space:]]+(-[a-zA-Z]*f[a-zA-Z]*|--full)([[:space:]]|$)"
_WORD_REGEX = r"(^|[^[:alnum:]_-])(pkill|danger)([^[:alnum:]_-]|$)"
_HEREDOC_REGEX = r"<<-?[[:space:]]*[^[:space:]<|;&]+([^|;&]|&[0-9])*<[[:space:]]*/dev/null"
_PKILL_F = r"(^|[;&|[:space:]])p(kill|grep)[[:space:]]+-[a-zA-Z]*f"


def _b(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _f(path: str, tool: str = "Edit") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path}}


#: name -> (record id, trigger, hook block, examples)
FIXTURES: dict[str, tuple[str, str, dict, dict]] = {
    "support.hook_proposal_fields": (RID, TRIGGER, {
        "tools": ["Edit", "Write"], "path_regex": r"\.storage/",
        "deny_message": "stop the HA container first",
    }, {
        "allow": [_f("/x/config.yaml"), _f("/x/notes.md", "Write")],
        "deny": [_f("/x/.storage/a"), _f("/y/.storage/b", "Write")],
    }),
    "overseer.formats.EXAMPLE_HOOK_INPUT": (RID, TRIGGER, {
        "mode": "warn", "event": "PreToolUse", "tools": ["Bash"], "path_regex": _PKILL_F,
        "warn_message": (
            "A -f pattern matches whole command lines, this shell's included, so it can "
            "find or kill the caller.\nAct on a PID you captured, or check the pattern "
            "cannot match this command."),
    }, {
        "allow": [_b("pkill -x myserver"), _b("pgrep -l node")],
        "warn": [_b("pkill -f 'app --reindex'"), _b("until ! pgrep -af worker; do sleep 1; done")],
    }),
    "overseer.formats.EXAMPLE_POST_HOOK_INPUT": (RID, TRIGGER, {
        "mode": "warn", "event": "PostToolUse", "tools": ["Write"],
        "path_regex": "db/migrations/",
        "warn_message": "A migration was written: run the migration check before the next step.",
    }, {
        "allow": [_f("/repo/db/seeds/users.sql", "Write"), _f("/repo/README.md", "Write")],
        "warn": [_f("/repo/db/migrations/0042_add.sql", "Write"),
                 _f("/repo/db/migrations/0043_idx.sql", "Write")],
    }),
    "overseer.formats.EXAMPLE_DENY_HOOK_INPUT": (RID, TRIGGER, {
        "tools": ["Edit", "Write"], "path_regex": "/data/app\\.db$",
        "deny_message": "stop the service before editing its database file",
    }, {
        "allow": [_f("/srv/app/config.yaml"), _f("/srv/app/data/app.db.bak", "Write")],
        "deny": [_f("/srv/app/data/app.db"), _f("/opt/x/data/app.db", "Write")],
    }),
    "test_hook_command_view.HEREDOC_BLOCK": ("lrn-c71f0a40", "About to run a Bash tool command that feeds a script", {
        "mode": "warn", "event": "PreToolUse", "tools": ["Bash"], "path_regex": _HEREDOC_REGEX,
        "warn_message": "This command feeds stdin from a heredoc and also redirects stdin "
                        "from /dev/null on the same command. (lrn-c71f0a40)",
    }, {
        "allow": [
            _b("cat > /tmp/check.py <<'EOF'\nprint(1)\nEOF\npython3 /tmp/check.py </dev/null 2>&1 | tail -8"),
            _b("some-tool --dir ./in </dev/null"),
            _b("python3 - <<'EOF'\nprint(1)\nEOF"),
        ],
        "warn": [
            _b("python3 - <<'EOF' </dev/null\nprint(1)\nEOF"),
            _b("uv run python - <<PY 2>&1 </dev/null\nimport sys\nprint(sys.version)\nPY"),
        ],
    }),
    "test_hook_command_view.PGREP_REGEX": ("lrn-19f82fc5", TRIGGER, {
        "tools": ["Bash"], "path_regex": _PGREP_REGEX, "deny_message": "stop",
    }, {"allow": [_b("ls")], "deny": [_b("pkill -f foo")]}),
    "test_hook_command_view.WORD_REGEX": ("lrn-c71f0a40", TRIGGER, {
        "mode": "warn", "tools": ["Bash"], "path_regex": _WORD_REGEX, "warn_message": "careful",
    }, {"allow": [_b("ls"), _b("unpkill")], "warn": [_b("'pkill' x"), _b("danger")]}),
    "test_hook_regenerate.BASH_WARN": (RID, TRIGGER, {
        "mode": "warn", "event": "PreToolUse", "tools": ["Bash"], "path_regex": _HEREDOC_REGEX,
        "warn_message": "a heredoc and </dev/null on one command: the script never arrives",
    }, {
        "allow": [_b("python3 - <<'EOF'\nprint(1)\nEOF"), _b("tool --dir x </dev/null")],
        "warn": [_b("python3 - <<EOF </dev/null\nprint(1)\nEOF"),
                 _b("uv run python - <<PY 2>&1 </dev/null\nPY")],
    }),
    "test_hook_regenerate.FILE_WARN": (RID, TRIGGER, {
        "mode": "warn", "event": "PostToolUse", "tools": ["Edit", "Write"],
        "path_regex": r"\.storage/", "warn_message": "HA rewrites .storage on shutdown",
    }, {
        "allow": [_f("/x/configuration.yaml"), _f("/x/notes.md", "Write")],
        "warn": [_f("/x/.storage/core.config"), _f("/y/.storage/auth", "Write")],
    }),
    "test_hook_compiler.DENY_ORACLE": ("lrn-0a1b2c3d", "About to run pkill -f with a pattern", {
        "tools": ["Bash"], "path_regex": _PKILL_F,
        "deny_message": "self-learn lrn-0a1b2c3d: don't use pkill -f; it's got 'quotes'",
    }, {"allow": [_b("ls -la"), _b("pkill -x node")], "deny": [_b("pkill -f 'node x'")]}),
    "test_hook_compiler.WARN_BLOCK": ("lrn-4c1e9a2f", "About to run pkill -f", {
        "mode": "warn", "event": "PostToolUse", "tools": ["Bash"], "path_regex": _PKILL_F,
        "warn_message": "don't use pkill -f; it's got 'quotes' and \"doubles\"\nkill by the PID you captured",
    }, {
        "allow": [_b("ls -la"), _b("pkill -x node")],
        "warn": [_b("pkill -f 'node x'"), _b("pgrep -af keys")],
    }),
}


_ROUTE_SOURCE = Path(__file__).with_name("test_route_hook.py")


def _route_guards() -> dict[str, tuple[str, str, dict, dict, dict]]:
    """The live guards ``test_route_hook.py`` routes, read from its source
    (parsed, never imported, so the fixtures are the originals on every
    platform): each test there that calls ``self.route_one(env, rid, trigger,
    hook, examples)`` and then checks ``run_guard(script, event).returncode``.

    name -> (record id, trigger, hook block, approved examples, runtime
    cases). The approved examples are what routing replayed; the runtime
    cases are the test's later ``run_guard`` checks, kept apart."""
    tree = ast.parse(_ROUTE_SOURCE.read_text(encoding="utf-8"))
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        call = None
        runtime: dict[str, list] = {"allow": [], "deny": []}
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "route_one" and len(node.args) == 5):
                call = node
            if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute)
                    and node.left.attr == "returncode" and isinstance(node.left.value, ast.Call)
                    and getattr(node.left.value.func, "id", None) == "run_guard"):
                code = ast.literal_eval(node.comparators[0])
                assert code in (0, 2), code
                runtime["deny" if code == 2 else "allow"].append(
                    ast.literal_eval(node.left.value.args[1]))
        if call is not None:
            rid, trigger, hook, examples = (ast.literal_eval(a) for a in call.args[1:])
            out[f"test_route_hook.{fn.name}"] = (rid, trigger, hook, examples, runtime)
    return out


_ROUTE_GUARDS = _route_guards()
FIXTURES.update({name: g[:4] for name, g in _ROUTE_GUARDS.items()})
#: The route tests' own later checks, apart from the approved examples.
RUNTIME_CASES: dict[str, dict] = {name: g[4] for name, g in _ROUTE_GUARDS.items()}

#: Deny fixtures whose pattern holds a letter range (``[a-zA-Z]``): GNU grep
#: reads a range through the caller's locale, so the artifact is refused
#: (``test_a_letter_range_is_locale_bound``). 3 of the 14 fixtures, 3 of 7
#: deny rules.
LETTER_RANGE_DENY = {
    "test_route_hook.test_uv_venv_copy_guard",
    "test_hook_command_view.PGREP_REGEX",
    "test_hook_compiler.DENY_ORACLE",
}


def _fixture_artifact(name: str) -> dict:
    rid, trigger, block, examples = FIXTURES[name]
    return hook_compiler.rule_artifact_for_hook(rid, trigger, block, examples)


def test_the_fixture_table_is_whole():
    """Positive controls: the three route guards were found in their
    source, each with runtime checks, and the letter-range count holds."""
    assert len(_ROUTE_GUARDS) == 3, sorted(_ROUTE_GUARDS)
    assert all(rt["allow"] and rt["deny"] for rt in RUNTIME_CASES.values()), RUNTIME_CASES
    assert len(FIXTURES) == 14
    deny = {n for n, f in FIXTURES.items() if f[2].get("mode", "deny") == "deny"}
    assert len(deny) == 7 and LETTER_RANGE_DENY <= deny


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_examples_decide_as_approved(name):
    """Each fixture's approved examples (replayed against the Bash script by
    the route verb, and by the differential below) get their verdicts from
    the evaluator alone; the build itself refuses on any disagreement. The
    route guards' later runtime checks get theirs too."""
    if name in LETTER_RANGE_DENY:
        with pytest.raises(RuleError, match="letter range"):
            _fixture_artifact(name)
        return
    rule = hook_rules.load_rule(hook_rules.dumps_rule(_fixture_artifact(name)))
    assert rule.examples, name  # positive control: there is something to check
    assert hook_rules.check_examples(rule) == []
    for verdict, events in RUNTIME_CASES.get(name, {}).items():
        for event in events:
            got = hook_rules.evaluate(rule, json.dumps(event).encode())
            assert got.verdict == verdict, (event, got)


# ===================================================================
# The artifact: format, digest, load refusals
# ===================================================================


def _deny_artifact() -> dict:
    return _fixture_artifact("support.hook_proposal_fields")


def test_artifact_shape_and_determinism():
    a, b = _deny_artifact(), _deny_artifact()
    assert hook_rules.dumps_rule(a) == hook_rules.dumps_rule(b)
    rid, trigger, block, _ = FIXTURES["support.hook_proposal_fields"]
    script = hook_compiler.script_for_hook(rid, trigger, block)

    assert a["version"] == 1 and a["kind"] == "self-learn-hook-rule"
    assert a["script_sha256"] == hashlib.sha256(script.encode("utf-8")).hexdigest()
    assert a["script_name"] == hook_compiler.script_name(rid, trigger)
    assert a["match"] == {"dialect": hook_rules.DIALECT, "pattern": r"\.storage/", "view": None,
                          "locale": "C.UTF-8", "ctype": hook_rules_ctype.DIGEST}
    assert a["fields"] == {"Edit": "file_path", "Write": "file_path"}
    assert a["output"] == f"self-learn {rid}: stop the HA container first"
    lines = script.split("\n")
    assert lines[a["error_lines"]["tool"] - 1].startswith("TOOL=$(jq")
    assert ".tool_input.file_path" in lines[a["error_lines"]["file_path"] - 1]
    assert a["digest"] == hook_rules.rule_digest(a)
    assert hook_compiler.rule_artifact_name(rid, trigger) == script_name_rule(rid, trigger)
    warn = _fixture_artifact("test_hook_regenerate.BASH_WARN")
    assert warn["match"]["view"] == hook_rules.VIEW_COMMAND and warn["error_lines"] == {}
    assert _fixture_artifact("test_hook_regenerate.FILE_WARN")["match"]["view"] is None


def script_name_rule(rid: str, trigger: str) -> str:
    return hook_compiler.script_name(rid, trigger)[:-3] + ".rule.json"


def _redigest(a: dict) -> dict:
    a = json.loads(json.dumps(a))
    a["digest"] = hook_rules.rule_digest(a)
    return a


def _mutated(**changes) -> dict:
    a = json.loads(json.dumps(_deny_artifact()))
    a.update(changes)
    return _redigest(a)


def _match(**changes) -> dict:
    return {**_deny_artifact()["match"], **changes}


def _warn_artifact() -> dict:
    return _fixture_artifact("test_hook_regenerate.FILE_WARN")


@pytest.mark.parametrize("label,artifact,why", [
    ("unknown version", lambda: _mutated(version=2), "unknown version 2"),
    ("version as text", lambda: _mutated(version="1"), "unknown version"),
    ("wrong kind", lambda: _mutated(kind="other"), "kind"),
    ("an extra key", lambda: _mutated(extra=1), "keys"),
    ("bad dialect", lambda: _mutated(match=_match(dialect="pcre")), "unknown matcher dialect"),
    ("a match block without the locale", lambda: _mutated(
        match={k: v for k, v in _match().items() if k != "locale"}), "bad match block"),
    ("another locale", lambda: _mutated(match=_match(locale="en_US.UTF-8")), "C.UTF-8 only"),
    ("other character tables", lambda: _mutated(match=_match(ctype="sha256:" + "0" * 64)),
     "other character tables"),
    ("a view on a deny rule", lambda: _mutated(match=_match(view=hook_rules.VIEW_COMMAND)),
     "command view"),
    ("a deny on PostToolUse", lambda: _mutated(event="PostToolUse"), "cannot run on"),
    ("an unguardable tool", lambda: _mutated(tools=["Read"]), "bad tools"),
    ("fields that do not fit", lambda: _mutated(fields={"Edit": "command", "Write": "file_path"}),
     "fields"),
    ("a refused pattern", lambda: _mutated(match=_match(pattern=r"\d")), "stray backslash"),
    ("a deny letter range", lambda: _mutated(match=_match(pattern="[a-z]")), "letter range"),
    ("an output without the prefix", lambda: _mutated(output="stop"), "deny output"),
    ("a deny output for another message", lambda: _mutated(
        output=f"self-learn {RID}: something else"), "deny output"),
    ("a warn output for another message", lambda: _redigest({**_warn_artifact(), "output": (
        _warn_artifact()["output"].replace("shutdown", "startup"))}), "warn output"),
    ("a deny message with a NUL", lambda: _mutated(
        message="one\x00two", output=f"self-learn {RID}: one\x00two"), "NUL"),
    ("a bad example verdict", lambda: _mutated(examples=[{"input": {}, "expect": "warn"}]),
     "bad examples"),
    ("an example verdict that is not text", lambda: _mutated(
        examples=[{"input": {}, "expect": ["allow"]}]), "bad examples"),
    ("missing error line", lambda: _mutated(error_lines={"tool": 26}), "error_lines"),
    ("a mode that is an object", lambda: _mutated(mode={}), "not text"),
    ("a tool that is a list", lambda: _mutated(tools=[[]]), "tools"),
    ("an empty script name", lambda: _mutated(script_name=""), "script name"),
    ("a script name for another record", lambda: _mutated(
        script_name="self-learn-00000000-about-to-run-a.sh"), "script name"),
    ("a script name of another shape", lambda: _mutated(script_name="../x.sh"), "script name"),
    ("a match block that is a list", lambda: _mutated(match=[]), "bad match block"),
    ("error lines that are a list", lambda: _mutated(error_lines=[]), "error_lines"),
    ("examples that are an object", lambda: _mutated(examples={}), "examples"),
    ("a digest that is a number", lambda: {**_deny_artifact(), "digest": 5}, "digest"),
])
def test_load_refuses(label, artifact, why):
    with pytest.raises(RuleError, match=re.escape(why)):
        hook_rules.load_rule(artifact())


def test_load_refuses_a_lone_surrogate_as_a_rule_error():
    """An escaped unpaired surrogate decodes to text that has no UTF-8 form:
    the digest check meets it first and the loader still says RuleError."""
    raw = hook_rules.dumps_rule(_deny_artifact()).decode()
    assert '"message": "stop the HA container first"' in raw  # positive control
    bad = raw.replace('"message": "stop the HA container first"', '"message": "\\ud800"')
    with pytest.raises(RuleError):
        hook_rules.load_rule(bad)
    with pytest.raises(RuleError):
        hook_rules.load_rule(bad.encode())


@pytest.mark.parametrize("junk", [b"", b"[]", b"{", b"null", b'"x"', b"5", b"\xff",
                                  b'{"version":1}', b'{"version":{}}', b'{"kind":[]}'],
                         ids=lambda j: repr(j))
def test_load_refuses_junk_with_a_rule_error(junk):
    with pytest.raises(RuleError):
        hook_rules.load_rule(junk)


def test_the_output_helpers_equal_the_compiler_ones():
    for rid, message in ((RID, "m"), (RID, f"self-learn {RID}: m"), (RID, "é \"q\"\nx")):
        assert hook_rules._prefixed(rid, message) == hook_compiler.prefixed_message(rid, message)
        for event in ("PreToolUse", "PostToolUse"):
            assert hook_rules._warn_line(event, rid, message) == hook_compiler.warn_output(
                event, rid, message)


def test_the_ctype_digest_covers_the_tables():
    body = "\n".join(f"{n}={getattr(hook_rules_ctype, n)}"
                     for n in ("ALPHA", "UPPER", "LOWER", "PRINT", "SPACE", "BLANK", "CNTRL"))
    assert hook_rules_ctype.DIGEST == "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def test_a_nul_in_a_deny_message_refuses_the_artifact_not_the_script():
    """Bash's echo drops the NUL (stderr ``onetwo``); the artifact would
    print it, so it is refused. A warning's JSON escapes it, so it builds."""
    hook_compiler.generate_script(RID, TRIGGER, ["Bash"], "x", "one\x00two")
    with pytest.raises(RuleError, match="NUL"):
        hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "x", "one\x00two")
    warn = hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "x", "one\x00two", mode="warn")
    assert "\\u0000" in warn["output"]


def test_a_placed_hook_carries_its_own_examples():
    """M5: without an examples argument the hook block's stored examples
    are replayed (a disagreeing one refuses the build); an explicit argument
    wins, as for a proposal block whose examples sit beside it."""
    rid, trigger, block, examples = FIXTURES["support.hook_proposal_fields"]
    wrong = {"allow": examples["deny"][:1], "deny": []}
    with pytest.raises(RuleError, match=r"example 0 \(allow\) was decided deny"):
        hook_compiler.rule_artifact_for_hook(rid, trigger, {**block, "examples": wrong})
    placed = hook_compiler.rule_artifact_for_hook(rid, trigger, {**block, "examples": examples})
    assert len(placed["examples"]) == 4  # carried
    explicit = hook_compiler.rule_artifact_for_hook(rid, trigger, {**block, "examples": wrong},
                                                    examples)
    assert len(explicit["examples"]) == 4
    with pytest.raises(RuleError, match=r"example 0 \(allow\) was decided deny"):
        hook_compiler.rule_artifact_for_hook(rid, trigger, block, wrong)


def test_load_refuses_a_failed_digest_and_accepts_the_untouched_file():
    raw = hook_rules.dumps_rule(_deny_artifact())
    assert hook_rules.load_rule(raw).record_id == RID  # positive control
    tampered = json.loads(raw)
    tampered["message"] = "something else"
    with pytest.raises(RuleError, match="digest does not match"):
        hook_rules.load_rule(json.dumps(tampered))
    tampered = json.loads(raw)
    tampered["match"]["pattern"] = "x"
    with pytest.raises(RuleError, match="digest does not match"):
        hook_rules.load_rule(json.dumps(tampered))


def test_the_build_refuses_examples_the_evaluator_decides_otherwise():
    rid, trigger, block, examples = FIXTURES["support.hook_proposal_fields"]
    wrong = {"allow": examples["deny"][:1], "deny": examples["deny"][1:]}
    with pytest.raises(RuleError, match=r"example 0 \(allow\) was decided deny"):
        hook_compiler.rule_artifact_for_hook(rid, trigger, block, wrong)
    with pytest.raises(RuleError, match="no 'warn' examples"):
        hook_compiler.rule_artifact_for_hook(rid, trigger, block, {"warn": []})


def test_the_compiler_refusals_still_come_first():
    with pytest.raises(hook_compiler.HookCompileError):
        hook_compiler.rule_artifact(RID, TRIGGER, ["Read"], "x", "m")
    with pytest.raises(hook_compiler.HookCompileError):
        hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "x", "a\nb")


def test_mirrors_equal_the_compiler_constants():
    assert hook_rules._TOOL_FIELDS == hook_compiler.TOOL_FIELDS
    assert tuple(hook_rules._TOOL_FIELDS) == hook_compiler.GUARDABLE_TOOLS
    assert hook_rules._MODE_EVENTS == hook_compiler.MODE_EVENTS
    assert hook_rules._MODE_VERDICTS == hook_compiler.MODE_VERDICTS
    assert hook_rules.COMMAND_VIEW_MAX_CHARS == hook_compiler.COMMAND_VIEW_MAX_BYTES


def test_import_is_cheap_and_standard_library_only():
    code = ("import sys; import self_learn.hook_rules; "
            "print(sorted(m for m in sys.modules if m.startswith('self_learn') or m in "
            "('decimal', '_decimal', 'yaml', 'ruamel', 'claude_agent_sdk')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, timeout=60).stdout.strip()
    assert out == "['self_learn', 'self_learn.hook_rules']"
    import ast

    tree = ast.parse(Path(hook_rules.__file__).read_text(encoding="utf-8"))
    top = {n.names[0].name.split(".")[0] for n in tree.body if isinstance(n, ast.Import)}
    top |= {n.module.split(".")[0] for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    assert top <= {"__future__", "hashlib", "json", "re", "time", "bisect"}


# ===================================================================
# The dialect: what is refused, what compiles
# ===================================================================

_NESTED_350 = "(" * 350 + "a" + ")" * 350
_LONG_COUNT = "a{" + "1" * 4000 + "}"

#: pattern -> (reason fragment, how grep itself treats it). Each "how" is
#: checked against grep (test_refusals_are_grounded_in_what_grep_does):
#: stray (a stray backslash, read as the character), warns, literal (read
#: as literal text without a word), rejects (exit 2), locale (answers
#: differently under en_US.UTF-8), quirk (GNU's answer is not the obvious
#: one: see QUIRKS), policy (grep accepts it silently; the evaluator refuses
#: what it does not model exactly, or what would cost too much), newline
#: (grep reads two patterns), compiler (the Bash emitter refuses it first).
REFUSED = {
    r"\d": ("stray backslash", "stray"),
    r"\/": ("stray backslash", "stray"),
    r"a\-b": ("stray backslash", "stray"),
    r"\n": ("stray backslash", "stray"),
    r"(a)\1": ("back-reference", "policy"),
    r"*a": ("nothing before it", "warns"),
    r"a|*b": ("nothing before it", "warns"),
    r"(*a)": ("nothing before it", "warns"),
    r"(?i)a": ("nothing before it", "warns"),
    r"{1}a": ("nothing before it", "warns"),
    r"^*": ("repeats an anchor", "warns"),
    r"a\b*": ("repeats an anchor", "policy"),
    r"a{": ("does not open a count", "literal"),
    r"a{1": ("does not open a count", "literal"),
    r"a{x}": ("does not open a count", "literal"),
    r"a{,}": ("does not open a count", "policy"),
    r"a{2,1}": ("minimum is above", "rejects"),
    r"a{32768}": ("count over", "rejects"),
    _LONG_COUNT: ("count over", "rejects"),
    r"[[=a=]]": ("collating element", "locale"),
    # one-character collating symbols mean the character itself, but named
    # ones ([[.hyphen.]]) and multi-character ones depend on the locale's
    # collation tables: the whole form is refused rather than half-supported
    r"[[.a.]]": ("collating element", "policy"),
    r"[[:foo:]]": ("not a character class", "rejects"),
    r"[:alpha:]": ("without its outer brackets", "rejects"),
    r"[:space:]x": ("without its outer brackets", "rejects"),
    r"[z-a]": ("not inside one of", "rejects"),
    r"[!-~]": ("not inside one of", "locale"),
    r"[A-z]": ("not inside one of", "locale"),
    "[à-ü]": ("not inside one of", "rejects"),
    r"[a-c-e]": ("another '-'", "rejects"),
    r"[[:alpha:]-z]": ("starts at a character class", "rejects"),
    r"[a-[:alpha:]]": ("ends at a character class", "rejects"),
    r"(a": ("never closed", "rejects"),
    r"[a": ("never closed", "rejects"),
    r"a)": ("closes no group", "literal"),
    r")": ("closes no group", "literal"),
    "a\\": ("lone backslash", "rejects"),
    "a\nb": ("newline", "newline"),
    "": ("empty", "compiler"),
    r"(a{100}){100}": ("matching steps", "policy"),
    r"x{4097}": ("matching steps", "policy"),
    r"((){1000}){1000}": ("more than 100000 steps", "rejects"),
    r"((){320}){320}": ("more than 100000 steps", "rejects"),
    _NESTED_350: ("nest deeper than 32", "policy"),
    "a+++++": ("more than 4 repeat operators", "policy"),
    "a" * 4097: ("longer than 4096", "policy"),
    # an anchor or word boundary inside a repeated group (B1)
    r"(\ba){2}": ("inside a repeated group", "quirk"),
    r"(^b($)?){,2}|(\>)+\W": ("inside a repeated group", "quirk"),
    r"(^)*a": ("inside a repeated group", "policy"),
    r"a($)?": ("inside a repeated group", "policy"),
    r"(\<a)+": ("inside a repeated group", "policy"),
    r"(a$)*": ("inside a repeated group", "policy"),
    r"(a|^b)+": ("inside a repeated group", "policy"),
    r"((x)(\B))*": ("inside a repeated group", "policy"),
}

#: pattern -> (text, grep's exit status on it, the exit status a naive
#: reading gives): where GNU grep's answer is not the obvious one.
QUIRKS = {
    r"(\ba){2}": ("aa", 0, 1),
    r"(^b($)?){,2}|(\>)+\W": ("bb", 1, 0),
}

#: pattern -> probe texts: each accepted construct, compared with grep on
#: texts that tell its readings apart (test_accepted_patterns_match_grep).
ACCEPTED = {
    r"\.storage/": [".storage/", "xstorage/", ".storage"],
    r"a{,3}b": ["b", "aaab", "c"],
    r"^a{0}b": ["b", "ab"],
    r"^a{2}{3}$": ["aaaaaa", "aaaa", "aaaaaaa"],
    r"^a**$": ["", "aaa", "ab"],
    r"^a+?$": ["", "a", "aa", "b"],
    r"^()$": ["", "x"],
    r"a|": ["", "b"],
    r"|a": ["", "b"],
    r"x}y": ["x}y", "xy"],
    r"x]y": ["x]y", "xy"],
    r"[]a]": ["]", "a", "b"],
    r"[^]a]": ["]", "a", "b"],
    r"[a-]": ["a", "-", "b"],
    r"[\d]": ["\\", "d", "1"],
    r"^[[:alpha:][:digit:]_]$": ["a", "1", "_", "-", "é"],
    r"\<a\>": ["a", "ab", "b a c"],
    r"\bb\B": ["bb", "b", "ab"],
    r"\w\W\s\S": ["a. x", "a.  ", "ab x"],
    r"\`a": ["a", "ba"],
    r"a\'": ["a", "ab"],
    r"\.\[\]\(\)\*\+\?\{\}\|\^\$\\": [".[]()*+?{}|^$\\", "x"],
    "日本+": ["日本本", "日"],
    r"^x{4000}$": ["x" * 4000, "x" * 3999, "x" * 4001],
    r"[:a]": [":", "a", "b"],
    r"^(a|b){2}$": ["ab", "ba", "a", "abc"],
    r"(\<a|b\>)c": ["ac", "x ac", "xac", "bc"],
    r"^(a|)$": ["", "a", "b"],
    r"(^a|b$)": ["ab", "ba", "a", "b"],
    r"^((){100}){100}a$": ["a", "b", ""],
    r"^a{000002}$": ["a", "aa", "aaa"],
}


@pytest.mark.parametrize("pattern", sorted(REFUSED), ids=lambda p: repr(p)[:60])
def test_refused_patterns(pattern):
    why, how = REFUSED[pattern]
    if how == "compiler":
        with pytest.raises(hook_compiler.HookCompileError):
            hook_compiler.generate_script(RID, TRIGGER, ["Bash"], pattern, "m")
        return
    with pytest.raises(RuleError, match=re.escape(why)):
        hook_rules.compile_pattern(pattern)


@pytest.mark.parametrize("pattern", sorted(ACCEPTED))
def test_accepted_patterns(pattern):
    assert hook_rules.compile_pattern(pattern).pattern == pattern


def test_a_refused_pattern_refuses_the_artifact_not_the_script():
    hook_compiler.generate_script(RID, TRIGGER, ["Bash"], r"\d+", "m")  # the script still builds
    with pytest.raises(RuleError, match="stray backslash"):
        hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], r"\d+", "m")


# ===================================================================
# The bound
# ===================================================================

#: Patterns that hang a backtracking engine (Python's ``re`` included) on
#: inputs like these; the automaton is linear in the input.
CATASTROPHIC = [
    (r"(a+)+$", "a" * 40000 + "!", False),
    (r"(a|aa)*c", "a" * 40000, False),
    (r"(.*a){12}", "a" * 20000, True),
    (r"(x+x+)+y", "x" * 40000, False),
    (r"([a-z]+[[:space:]]?)*;", "word " * 8000, False),
]


@pytest.mark.parametrize("pattern,text,expected", CATASTROPHIC,
                         ids=[c[0] for c in CATASTROPHIC])  # short ids: Windows caps env vars
def test_catastrophic_patterns_stay_linear(pattern, text, expected):
    matcher = hook_rules.compile_pattern(pattern)
    start = time.monotonic()
    assert matcher.search(text) is expected
    assert time.monotonic() - start < 3.0


@pytest.mark.parametrize("mode,expected", [
    ("deny", (2, b"", f"self-learn {RID}: guard regex failed — failing closed\n")),
    ("warn", (0, b"", "")),
])
def test_the_deadline_fails_the_way_the_script_fails(mode, expected):
    rule = hook_rules.load_rule(hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "zzz", "m",
                                                            mode=mode))
    data = _cmd("y" * (hook_rules._DEADLINE_STRIDE * 2))
    on_time = hook_rules.evaluate(rule, data)
    assert (on_time.exit_code, on_time.stdout, on_time.stderr) == (0, b"", "")  # control
    late = hook_rules.evaluate(rule, data, deadline_s=-1.0)
    assert (late.exit_code, late.stdout, late.stderr) == expected
    assert late.reason == "deadline"


class _Clock:
    """A clock for the deadline: *times* are returned in turn, the last one
    from then on; ``reads`` counts the calls."""

    def __init__(self, *times: float):
        self.times = list(times)
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return self.times.pop(0) if len(self.times) > 1 else self.times[0]


_GUARD_FAILED = (2, b"", f"self-learn {RID}: guard regex failed — failing closed\n")


@pytest.mark.parametrize("label,data", [
    ("an early match", _cmd("q")),
    ("a short miss", _cmd("x" * 2047)),
    ("empty lines before the text", _cmd("\n" * 5000 + "x")),
    ("an empty stdin", b""),
    ("a malformed stdin", b"{"),
    ("another tool", _path("q")),
    ("no value", _cmd("")),
])
def test_one_deadline_covers_the_whole_decision(label, data):
    """M2: with the deadline already past when the decision ends, every
    branch of a deny rule fails the way the script's failed grep does, and
    every branch of a warning stays silent; with the clock standing still
    the same inputs get their ordinary answers (the control)."""
    deny = hook_rules.load_rule(hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "q", "m"))
    warn = hook_rules.load_rule(hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "q", "m",
                                                            mode="warn"))
    still = hook_rules.evaluate(deny, data, deadline_s=1.0, clock=_Clock(0.0))
    assert still.reason != "deadline", still
    late = hook_rules.evaluate(deny, data, deadline_s=1.0, clock=_Clock(0.0, 5.0))
    assert ((late.exit_code, late.stdout, late.stderr), late.reason) == (_GUARD_FAILED, "deadline")
    quiet = hook_rules.evaluate(warn, data, deadline_s=1.0, clock=_Clock(0.0, 5.0))
    assert ((quiet.exit_code, quiet.stdout, quiet.stderr), quiet.reason) == (
        (0, b"", ""), "deadline")


def test_the_deadline_is_read_while_the_work_goes_on():
    """The clock is read during parsing, during the command view and during
    matching, not only at the end: a long step cannot run on unbounded."""
    stride = hook_rules._DEADLINE_STRIDE
    text = "git commit -m 'x'; " * (stride * 16 // 19)
    for label, run in [
        ("parse tokens", lambda b: hook_rules._jq_values(_cmd(list(range(stride * 4))), b)),
        ("parse a string", lambda b: hook_rules._jq_values(_cmd("x\\" * stride * 32), b)),
        ("view", lambda b: hook_rules.command_view(text, b)),
        ("match", lambda b: hook_rules.compile_pattern("zzz").search(text, b)),
        ("render", lambda b: hook_rules._jq_dump([["x", None]] * (stride * 2), b)),
    ]:
        clock = _Clock(0.0)
        run(hook_rules._Budget(10.0, clock))
        assert clock.reads >= 3, (label, clock.reads)


@pytest.mark.parametrize("mode,expected", [
    ("deny", (2, b"", f"self-learn {RID}: {hook_rules.EVALUATOR_ERROR} — failing closed\n")),
    ("warn", (0, b"", "")),
])
def test_an_unexpected_error_still_gets_a_decision(monkeypatch, mode, expected):
    """No input raises out of evaluate: an error the evaluator did not
    foresee fails a deny rule closed with its own line, and silences a
    warning."""
    rule = hook_rules.load_rule(hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "q", "m",
                                                            mode=mode))
    assert hook_rules.evaluate(rule, _cmd("x")).reason == "no-match"  # control

    def boom(*_a, **_k):
        raise ZeroDivisionError

    monkeypatch.setattr(hook_rules, "_blank", boom)
    got = hook_rules.evaluate(rule, _cmd("x"))
    assert ((got.exit_code, got.stdout, got.stderr), got.reason) == (expected, "evaluator-error")


def test_the_replay_keeps_the_deadline(monkeypatch):
    """M3: replaying a rule's examples at build time runs each under the
    ordinary deadline, never with it turned off."""
    seen = []
    real = hook_rules.evaluate

    def spy(rule, data, **kw):
        seen.append(kw.get("deadline_s", hook_rules.MATCH_DEADLINE_S))
        return real(rule, data, **kw)

    monkeypatch.setattr(hook_rules, "evaluate", spy)
    _fixture_artifact("support.hook_proposal_fields")
    assert len(seen) == 4 and all(s is not None and s > 0 for s in seen), seen


def test_a_full_dfa_cache_is_rebuilt_without_changing_the_answer(monkeypatch):
    monkeypatch.setattr(hook_rules, "_CACHE_LIMIT", 8)
    matcher = hook_rules.compile_pattern(r"[[:alpha:]]{3}[0-9]")
    text = "".join(chr(0x4E00 + i) + "1" for i in range(500)) + "abc5"
    for t, want in ((text, True), (text[:-1], False)):
        search = hook_rules._Search(matcher, hook_rules._Budget(None))
        assert search.run(t) is want
        assert search.size <= 8 + 4  # the cache stayed bounded
        assert sum(len(r) for r in search.rows) <= 8 + 4


def test_searching_leaves_the_matcher_unchanged():
    """B4: a search keeps its state to itself; the compiled matcher a rule
    holds is the same object, field for field, after thirty thousand
    searches with distinct first characters (accepting ones included)."""
    for pattern in ("a?", "^abc$", r"\bx"):
        matcher = hook_rules.compile_pattern(pattern)
        before = {k: (repr(v) if not isinstance(v, (list, dict)) else len(v))
                  for k, v in vars(matcher).items()}
        for i in range(30000):
            matcher.search(chr(0x4E00 + i) + "abc")
        after = {k: (repr(v) if not isinstance(v, (list, dict)) else len(v))
                 for k, v in vars(matcher).items()}
        assert after == before, pattern


def test_concurrent_evaluations_of_one_rule_agree(monkeypatch):
    """B4: one loaded rule, decided from several threads at once, while
    other threads churn its matcher through cache resets. Every decision
    must still be the script's (red on 37438b84, whose searches shared one
    cache: a reset under a live state lost the match)."""
    monkeypatch.setattr(hook_rules, "_CACHE_LIMIT", 16)
    rule = hook_rules.load_rule(hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "^abc$", "m"))
    hit, miss = _cmd("abc"), _cmd("abd")
    stop = threading.Event()
    wrong: list = []
    churned = [0]

    def churn():
        i = 0
        while not stop.is_set():
            hook_rules.evaluate(rule, _cmd(chr(0x4E00 + i % 20000)))
            i += 1
        churned[0] += i

    def check():
        for _ in range(1500):
            for data, want in ((hit, "deny"), (miss, "allow")):
                got = hook_rules.evaluate(rule, data)
                if got.verdict != want or got.reason not in ("match", "no-match"):
                    wrong.append((data, got))

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        churners = [threading.Thread(target=churn) for _ in range(2)]
        checkers = [threading.Thread(target=check) for _ in range(2)]
        for t in churners + checkers:
            t.start()
        for t in checkers:
            t.join()
        stop.set()
        for t in churners:
            t.join()
    finally:
        sys.setswitchinterval(old)
    assert churned[0] > 100  # control: the churn really ran alongside
    assert wrong[:5] == []


# ===================================================================
# The Linux differential
# ===================================================================

LINUX_ONLY_REASON = "Linux only: reads the Linux test modules the fixtures come from"
_LINUX_ONLY = pytest.mark.skipif(not _LINUX, reason=LINUX_ONLY_REASON)


@pytest.fixture(scope="module")
def tool_env(tmp_path_factory) -> dict:
    """A PATH holding exactly the tools a generated script runs, and the
    locale the dialect names. No inherited shell functions or variables."""
    bindir = tmp_path_factory.mktemp("bin")
    for tool in _TOOLS:
        (bindir / tool).symlink_to(shutil.which(tool))
    return {"PATH": str(bindir), "LC_ALL": "C.UTF-8"}


class _Scripts:
    def __init__(self, root: Path, env: dict):
        self.root, self.env, self.n = root, env, 0
        self.bash = str(Path(env["PATH"]) / "bash")

    def write(self, text: str) -> Path:
        self.n += 1
        path = self.root / f"guard-{self.n}.sh"
        path.write_text(text, encoding="utf-8")
        return path

    def run(self, script: Path, data: bytes) -> tuple[int, bytes, str]:
        proc = subprocess.run([self.bash, str(script)], input=data, capture_output=True,
                              env=self.env, timeout=120)
        err = proc.stderr.decode("utf-8", "replace")
        kept = "".join(line for line in err.splitlines(True) if not _DIAG.match(line))
        return proc.returncode, proc.stdout, kept


@pytest.fixture
def scripts(tmp_path, tool_env) -> _Scripts:
    return _Scripts(tmp_path, tool_env)


def _differ(scripts: _Scripts, work: list[tuple[str, str, dict, bytes]], *,
            inexact_ok: bool = False, inexact: list | None = None) -> list[str]:
    """work: (label, script text, artifact, stdin). Every row's script and
    evaluator decisions, compared; one line per difference.

    With *inexact_ok*, a row the evaluator declares it cannot reproduce
    (reason ``inexact``) may differ, but only in the safe direction: a deny
    rule blocks with the evaluator's labelled line, a warning stays silent.
    Such rows are appended to *inexact*."""
    paths: dict[str, Path] = {}
    rules: dict[str, hook_rules.Rule] = {}
    for _, text, art, _ in work:
        if text not in paths:
            paths[text] = scripts.write(text)
            rules[text] = hook_rules.load_rule(art)

    def one(row):
        label, text, _, data = row
        want = scripts.run(paths[text], data)
        rule = rules[text]
        got = hook_rules.evaluate(rule, data)
        mine = (got.exit_code, got.stdout, got.stderr)
        if any(_DIAG.match(line) for line in got.stderr.splitlines(True)):
            return f"{label}: the evaluator wrote a tool diagnostic: {got.stderr!r}"
        if got.reason == "inexact":
            if not inexact_ok:
                return f"{label}: inexact where exact was required on {data[:200]!r}"
            if inexact is not None:
                inexact.append(label)
            if mine != _fail_closed(rule.mode):
                return f"{label}: an inexact decision that is not the fail-closed one: {mine!r}"
            return None
        if mine != want:
            return f"{label}: bash {want!r} evaluator {mine!r} on {data[:200]!r}"
        return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [r for r in pool.map(one, work) if r]


#: Raw stdin, whatever the rule: the malformed, the empty, the odd.
RAW_INPUTS = [
    b"", b"\n", b"   \t\n", "　".encode(), b"\x00", b"{", b"}", b"[1]", b'"Bash"', b"5",
    b"null", b"true", b"{}", b"nullnull", b"{} junk", b"\xef\xbb\xbf{}", b'{"tool_name":null}',
    b'{"tool_name":false}', b'{"tool_name":["Bash"]}', b'{"tool_name":"Bash\\n"}',
    b'{"tool_name":"Bash","tool_input":[]}', b'{"tool_name":"Edit","tool_input":7}',
    b'{"tool_name":"Write","tool_input":null}', b'{"tool_name":"Bash"} [1]',
    b"\xff\xfe", b'{"a":1,}', b'{"a" 1}', b'[1 2]', b"{}:",
]

#: Where jq is more lenient than JSON: a number jq reads (``nan``, ``01``,
#: ``.5``, ``1.``) in any field, the guarded one or not. The evaluator
#: declares it cannot reproduce the input: a deny guard fails closed with its
#: own line, a warning stays silent; the script may instead read the number.
#: A bare word jq rejects too is a parse error in both.
JQ_LENIENT = [
    b'{"tool_name":nan}', b'{"tool_name":"Bash","tool_input":{"command":01}}',
    b'{"tool_name":"Bash","tool_input":{"command":.5}}',
    b'{"tool_name":"Bash","tool_input":{"command":1.}}', b"NaN",
    b'{"tool_name":"Bash","tool_input":{"command":"push"},"n":01}',
    b'{"tool_name":"Bash","tool_input":{"command":"pkill -f x"},"n":-.5e1}',
    b'{"tool_name":"Bash","tool_input":{"command":"push"},"n":infinite}',
    b'{"tool_name":"Bash","tool_input":{"command":"push"},"n":+1}',
]


@pytest.mark.parametrize("data", JQ_LENIENT, ids=lambda d: repr(d)[:60])
def test_jq_lenient_numbers_fail_closed(data):
    deny = hook_rules.evaluate(_rule("deny-push"), data)
    assert ((deny.exit_code, deny.stdout, deny.stderr), deny.reason) == (
        _fail_closed("deny"), "inexact")
    warn = hook_rules.evaluate(_rule("warn-bash"), data)
    assert (warn.exit_code, warn.stdout, warn.stderr, warn.reason) == (0, b"", "", "inexact")


@_DIFF
def test_jq_lenient_numbers_never_allow_what_the_script_denies(scripts):
    """The same inputs through the real scripts: wherever the evaluator's
    answer differs, it is the fail-closed one (and a parse error jq also
    reports, a bare word after a lenient number, stays exact)."""
    work = []
    for name in ("deny-push", "warn-bash"):
        tools, regex, message, mode, event = CASE_RULES[name]
        text = hook_compiler.generate_script(RID, TRIGGER, tools, regex, message, mode=mode,
                                             event=event)
        art = hook_compiler.rule_artifact(RID, TRIGGER, tools, regex, message, mode=mode,
                                          event=event)
        work += [(f"{name}[{i}]", text, art, d) for i, d in enumerate(JQ_LENIENT)]
        work.append((f"{name} then junk", text, art, JQ_LENIENT[1] + b" junk"))
    seen: list = []
    assert _differ(scripts, work, inexact_ok=True, inexact=seen) == []
    assert len(seen) == 2 * len(JQ_LENIENT)  # the junk rows stayed exact


#: Field values, wrapped for each tool a rule names (and for one it does not).
VALUES = [
    "", "\n", " ", "x", "x\ny", "\nx\n", "a\r\nb", "éè€\U0001f600", " ",
    "\x01\x7f", "\u0000", "tab\there", "\\", "'quoted' \"double\"", "x" * 20000,
    5, 0, 42, -7, True, False, None, [], [""], ["x", "y"], {}, {"k": "v", "n": [1, None, True]},
    ["\x01\x7fé\"\\\n\t /", {"": [[], {}]}],
]


def _inputs_for(tools: list[str]) -> list[bytes]:
    out = list(RAW_INPUTS)
    for tool in [*tools, "Read"]:
        field = hook_compiler.TOOL_FIELDS.get(tool, "file_path")
        out.extend(_payload(tool, field, v) for v in VALUES)
        out.append(json.dumps({"tool_name": tool, "tool_input": {"other": "x"}}).encode())
    return out


@_DIFF
def test_differential_recorded_cases(scripts):
    """Every literal the Windows run checks is what the real script does."""
    work = []
    for case, rule_name, data in CASES:
        tools, regex, message, mode, event = CASE_RULES[rule_name]
        text = hook_compiler.generate_script(RID, TRIGGER, tools, regex, message,
                                             mode=mode, event=event)
        art = hook_compiler.rule_artifact(RID, TRIGGER, tools, regex, message,
                                          mode=mode, event=event)
        work.append((case, text, art, data))
    seen: list = []
    assert _differ(scripts, work, inexact_ok=True, inexact=seen) == []
    assert sorted(seen) == sorted(FAILS_CLOSED)  # and every other case is exact
    # and each recorded literal is the script's own answer
    paths = {text: scripts.write(text) for _, text, _, _ in work}
    bad = [(case, got) for case, text, _, data in work
           if (got := scripts.run(paths[text], data)) != EXPECTED[case]]
    assert bad == []


@_DIFF
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_differential_fixture(scripts, name):
    rid, trigger, block, examples = FIXTURES[name]
    text = hook_compiler.script_for_hook(rid, trigger, block)
    if name in LETTER_RANGE_DENY:
        with pytest.raises(RuleError, match="letter range"):
            hook_compiler.rule_artifact_for_hook(rid, trigger, block, examples)
        return
    art = hook_compiler.rule_artifact_for_hook(rid, trigger, block, examples)
    work = [(f"{verdict}[{i}]", text, art, json.dumps(ex).encode())
            for verdict, items in examples.items() for i, ex in enumerate(items)]
    work += [(f"runtime {verdict}[{i}]", text, art, json.dumps(ex).encode())
             for verdict, items in RUNTIME_CASES.get(name, {}).items()
             for i, ex in enumerate(items)]
    work += [(f"adversarial[{i}]", text, art, data)
             for i, data in enumerate(_inputs_for(block["tools"]))]
    assert len(work) > 60
    assert _differ(scripts, work) == []


@_DIFF
def test_a_letter_range_is_locale_bound(scripts):
    """M1, side by side: the same deny script decides ``é`` differently
    under en_US.UTF-8 (``[a-z]`` collates it in) and C.UTF-8, so a deny
    rule with a letter range is refused; the class form builds, and agrees
    with the script under both locales."""
    avail = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout
    if "en_US.utf8" not in avail and "en_US.UTF-8" not in avail:
        pytest.skip("en_US.UTF-8 is not installed")  # only the side-by-side needs it
    data = _cmd("é")
    ranged = scripts.write(hook_compiler.generate_script(RID, TRIGGER, ["Bash"], "^[a-z]$", "m"))
    c_run = scripts.run(ranged, data)
    us = _Scripts(scripts.root, {**scripts.env, "LC_ALL": "en_US.UTF-8"})
    assert (c_run[0], us.run(ranged, data)[0]) == (0, 2)  # the script follows the locale
    with pytest.raises(RuleError, match="letter range"):
        hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], "^[a-z]$", "m")
    classed = hook_compiler.generate_script(RID, TRIGGER, ["Bash"], "^[[:lower:]]$", "m")
    rule = hook_rules.load_rule(hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"],
                                                            "^[[:lower:]]$", "m"))
    path = scripts.write(classed)
    got = hook_rules.evaluate(rule, data)
    assert scripts.run(path, data) == us.run(path, data) == (got.exit_code, got.stdout, got.stderr)
    assert got.verdict == "deny"  # é is lower case in both


@_DIFF
@pytest.mark.parametrize("pattern", sorted(QUIRKS))
def test_quirks_are_what_the_script_does(scripts, pattern):
    """B1, side by side: the script's answer on these is GNU grep's, not the
    obvious one, and the evaluator refuses to build the rule."""
    text, grep_rc, naive_rc = QUIRKS[pattern]
    script = scripts.write(hook_compiler.generate_script(RID, TRIGGER, ["Bash"], pattern, "m"))
    assert scripts.run(script, _cmd(text))[0] == (2 if grep_rc == 0 else 0)
    naive = re.search(pattern.replace(r"\>", r"\b"), text)  # Python re: the obvious reading
    assert (0 if naive else 1) == naive_rc != grep_rc
    with pytest.raises(RuleError, match="inside a repeated group"):
        hook_compiler.rule_artifact(RID, TRIGGER, ["Bash"], pattern, "m")


#: pattern -> probe texts. Run as a deny and as a warning hook on Bash and
#: Edit, each text as the command and as the file path.
DIALECT = {
    r"a.c": ["abc", "a\nc", "aéc", "ac", "a\tc"],
    r"^ab": ["ab", "xab", "x\nab"],
    r"ab$": ["ab", "abx", "ab\nx", "ab\r"],
    r"a^b|c": ["a^b", "c", "ab"],
    r"a$b": ["a$b", "ab"],
    r"(^|x)y": ["y", "xy", "zy"],
    r"a($|b)": ["a", "ab", "ac"],
    r"\bfoo\b": ["foo", "foobar", "a foo b", "_foo", "éfoo", "foo-", "x"],
    r"\Bfoo": ["afoo", "foo", " foo"],
    r"\B": ["", " ", "ab", "-"],
    r"\b": [" ", "a", "--"],
    r"\<foo": ["foo", "afoo", ".foo"],
    r"foo\>": ["foo", "foo_", "foo."],
    r"\`foo": ["foo", "xfoo"],
    r"foo\'": ["foo", "foox"],
    r"\w+@\w+": ["a@b", "@b", "é@ß", "ͅ@١"],
    r"\W": ["abc", "ab c", "é", "²"],
    r"\s": ["a b", "ab", "a　b", "a b", "a\x0bb", "a b", "a\x1cb"],
    r"\S{3}": ["a b", "abc"],
    r"[[:alpha:]]{2}": ["a1", "ab", "éß", "ͅͅ", "ⅠⅡ", "²²"],
    r"[[:digit:]]": ["a", "1", "١"],
    r"[[:alnum:]_-]+x": ["ab_-x", "!x"],
    r"[[:upper:]]": ["a", "A", "É", "ǅ"],
    r"[[:lower:]]": ["ǅ", "ʕ", "a", "A"],
    r"[[:punct:]]": ["a", "!", "§", "²", "½", " "],
    r"[[:space:]]x": [" x", " x", " x", "\x85x"],
    r"[[:blank:]]": ["\t", "　", "\x0b", "a"],
    r"[[:cntrl:]]": ["\x01", "\x7f", "\x85", " ", "a"],
    r"[[:print:]]": ["\x01", "a", "­"],
    r"[[:graph:]]": [" ", "a", "　"],
    r"[[:xdigit:]]+$": ["ff", "fg", "ＡＢ"],
    r"[]a]": ["]", "a", "b"],
    r"[^]a]": ["]", "b", "a]"],
    r"[a-]": ["-", "b"],
    r"[\d]": ["\\", "d", "1"],
    r"[a-cx-z0-2]": ["b", "y", "1", "d"],
    r"^[^a-z]+$": ["abc", "ABC", "é"],
    r"a{2}": ["a", "aa"],
    r"a{2,}b": ["ab", "aab"],
    r"^a{,2}b": ["b", "aaab", "ab"],
    r"^a{1,3}b$": ["ab", "aaab", "aaaab"],
    r"^(ab){0}c": ["c", "abc"],
    r"^a**b": ["b", "aab"],
    r"^a+?b": ["b", "ab"],
    r"^a{2}{3}$": ["aaaaaa", "aaaa"],
    r"(a|)b": ["b", "ab"],
    r"(|a)b": ["b"],
    r"^(a|)$": ["", "a", "b"],
    r"q|": ["anything"],
    r"()x": ["x", "y"],
    r"x}y": ["x}y", "xy"],
    r"x]y": ["x]y"],
    r"\.\*\+\?\(\)\[\]\{\}\|\^\$\\": [".*+?()[]{}|^$\\", "x"],
    "é+": ["éé", "e"],
    "日本": ["日本語", "日"],
    r"(a|b)*abb": ["babb", "abab"],
    r"(.*)(.*)(.*)x": ["y" * 3000 + "x", "y" * 3000],
    r"(^)a": ["a", "ba"],
    r"(\<a|b\>)c": ["ac", "xac", "bc", "x bc"],
    r"x*": ["", "y"],
    r"^$": ["", "x"],
    r"(a+)+$": ["a" * 30 + "!", "a" * 30],
}


@_DIFF
@pytest.mark.parametrize("pattern", sorted(DIALECT))
def test_differential_dialect(scripts, pattern):
    work = []
    for mode in ("deny", "warn"):
        tools = ["Bash", "Edit"]
        text = hook_compiler.generate_script(RID, TRIGGER, tools, pattern, "m", mode=mode)
        if mode == "deny" and hook_rules.compile_pattern(pattern).letter_range:
            with pytest.raises(RuleError, match="letter range"):
                hook_compiler.rule_artifact(RID, TRIGGER, tools, pattern, "m", mode=mode)
            continue
        art = hook_compiler.rule_artifact(RID, TRIGGER, tools, pattern, "m", mode=mode)
        for i, probe in enumerate(DIALECT[pattern]):
            work.append((f"{mode} command[{i}]", text, art, _cmd(probe)))
            work.append((f"{mode} path[{i}]", text, art, _path(probe)))
    assert _differ(scripts, work) == []


def _numbers() -> list[str]:
    """JSON number literals: the edges, then generated integers inside and
    past the exact range, decimals and exponents."""
    rng = random.Random(7)
    out = ["0", "-0", "1", "-1", "42", "100", "9007199254740991", "-9007199254740991",
           "9007199254740992", "-9007199254740992", "9007199254740993", "12345678901234567",
           "1.0", "1e2", "1E2", "0.1", "1.5e-7", "-0.0", "1e308", "1e309", "-1e1000000000",
           "5e-324", "1e-400", "123456789012345678901234567890", "1e9999999999999999999999999"]
    out += [str(rng.randint(-2 ** 53, 2 ** 53)) for _ in range(400)]
    out += [str(rng.randint(-9, 9) * 10 ** rng.randint(0, 15)) for _ in range(100)]
    out += [str(rng.randint(-10 ** 22, 10 ** 22)) for _ in range(100)]
    out += [repr(rng.uniform(-1e6, 1e6)) for _ in range(100)]
    out += [f"{rng.randint(1, 9)}e{rng.randint(-30, 30)}" for _ in range(100)]
    return out


@_DIFF
def test_differential_numbers(tool_env):
    """B2: every number, alone and inside an array and an object, printed by
    the evaluator exactly as ``jq -r`` prints it, or declared inexact (the
    decision then fails closed); never an exception. Every integer in the
    exact range is printed, none declared inexact."""
    sep = "@@sep@@"
    numbers = _numbers()
    docs, shapes = [], []
    for n in numbers:
        for shape in ("{n}", "[{n}]", '{{"k":[{n},{{"j":{n}}}]}}'):
            docs.append('{"v":' + shape.format(n=n) + '}{"v":"' + sep + '"}')
            shapes.append((n, shape))
    proc = subprocess.run(["jq", "-r", ".v"], input="\n".join(docs).encode(),
                          capture_output=True, env=tool_env, timeout=120)
    assert proc.returncode == 0, proc.stderr[:300]
    printed = proc.stdout.decode().split(sep + "\n")[:-1]
    assert len(printed) == len(docs)
    exact, bad = 0, []
    for (n, shape), want in zip(shapes, printed):
        values = hook_rules._jq_values(('{"v":' + shape.format(n=n) + "}").encode(),
                                       hook_rules._Budget(None))
        try:
            got = hook_rules._jq_field(values, ("v",), hook_rules._Budget(None)) + "\n"
        except hook_rules._Inexact:
            if re.fullmatch(r"0|-?[1-9][0-9]*", n) and abs(int(n)) <= 2 ** 53 and n != "-0":
                bad.append(f"{shape.format(n=n)}: a safe integer declared inexact")
            continue
        exact += 1
        if got != want:
            bad.append(f"{shape.format(n=n)}: jq {want!r} evaluator {got!r}")
    assert bad[:10] == []
    assert exact >= 3 * 400  # the generated safe integers, at least


def _grep_lines(env: dict, pattern: str, texts: list[str]) -> set[int] | None:
    """The indexes of *texts* (one per line) ``grep -E`` matches; None when
    grep rejects the pattern, warns, or takes too long."""
    data = "".join(t + "\n" for t in texts).encode()
    try:
        proc = subprocess.run(["grep", "-nE", "--", pattern], input=data, capture_output=True,
                              env=env, timeout=10)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode not in (0, 1) or proc.stderr:
        return None
    return {int(line.split(b":", 1)[0]) - 1 for line in proc.stdout.split(b"\n") if line}


_FUZZ_TEXTS = ["", "a", "b", "aa", "ab", "ba", "a b", " a", "a ", "bb", "aab", "-a-", "ab ba",
               "é", "aé", "  ", "a-b", "b a b", "]", "[", ":", "^", "\\", "1", "x", "A", "]a"]


def _assertion_patterns(rng: random.Random, n: int) -> list[str]:
    asserts = ["^", "$", r"\b", r"\B", r"\<", r"\>", r"\`", r"\'"]
    atoms = ["a", "b", ".", "[ab]", r"\w", r"\W", " ", "-"]
    quants = ["", "", "*", "+", "?", "{2}", "{,2}", "{1,2}", "{0}"]

    def gen(depth: int) -> str:
        r = rng.random()
        if depth > 2 or r < 0.35:
            x = rng.choice(asserts + atoms)
        elif r < 0.6:
            x = "".join(gen(depth + 1) for _ in range(rng.randint(1, 3)))
        elif r < 0.8:
            x = "(" + "|".join(gen(depth + 1) for _ in range(rng.randint(1, 3))) + ")"
        else:
            x = "(" + gen(depth + 1) + ")"
        return x + (rng.choice(quants) if rng.random() < 0.4 else "")

    out: dict[str, None] = {}
    while len(out) < n:
        out[gen(0)] = None
    return list(out)


def _bracket_patterns(rng: random.Random, n: int) -> list[str]:
    pieces = ["a", "b", "-", "]", "^", "[", ":", "=", ".", "[:alpha:]", "[:digit:]", "a-c", "\\",
              " ", "é", "[:", ":]", "[.", ".]", "[=", "=]", "0-9", "x"]
    out: dict[str, None] = {}
    while len(out) < n:
        body = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 4)))
        out[rng.choice(["", "^", "x"]) + "[" + rng.choice(["", "^"]) + body + "]"
            + rng.choice(["", "$", "+", "x"])] = None
    return list(out)


@_DIFF
@pytest.mark.parametrize("kind", ["assertions", "brackets"])
def test_fuzzed_patterns_match_grep_or_are_refused(kind, tool_env):
    """B1: seeded patterns that put the assertions (``^ $ \\b \\B \\< \\> \\`
    \\'``) inside groups, alternations and intervals, and bracket
    expressions with every special member. Each one the evaluator accepts,
    grep accepts too (a grep syntax error or warning is always refused) and
    matches on exactly the same texts."""
    rng = random.Random(11 if kind == "assertions" else 12)
    patterns = (_assertion_patterns if kind == "assertions" else _bracket_patterns)(rng, 1500)

    def one(pattern: str):
        try:
            matcher = hook_rules.compile_pattern(pattern)
        except RuleError:
            return "refused", None
        want = _grep_lines(tool_env, pattern, _FUZZ_TEXTS)
        if want is None:
            return "accepted", f"{pattern!r}: grep rejects, warns or hangs; the evaluator accepts"
        got = {i for i, t in enumerate(_FUZZ_TEXTS) if matcher.search(t)}
        if got != want:
            return "accepted", (f"{pattern!r}: grep-only {sorted(_FUZZ_TEXTS[i] for i in want - got)}"
                                f" evaluator-only {sorted(_FUZZ_TEXTS[i] for i in got - want)}")
        return "accepted", None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, patterns))
    accepted = sum(1 for k, _ in results if k == "accepted")
    assert accepted >= 300, accepted  # control: the fuzz exercised the engine
    assert [r for _, r in results if r][:10] == []


@_DIFF
@pytest.mark.parametrize("pattern", sorted(ACCEPTED))
def test_accepted_patterns_match_grep(pattern, tool_env):
    """m4: each accepted construct matches what grep matches on texts that
    tell its readings apart, not merely compiles."""
    texts = ACCEPTED[pattern]
    want = _grep_lines(tool_env, pattern, texts)
    assert want is not None, "grep rejects or warns"
    matcher = hook_rules.compile_pattern(pattern)
    assert {i for i, t in enumerate(texts) if matcher.search(t)} == want
    assert 0 < len(want) < len(texts) or pattern in ("a|", "|a", r"^a**$")  # the texts discriminate


@_DIFF
@_LINUX_ONLY
def test_differential_command_view_corpus(scripts):
    """The S-133 corpus, through the deny and the warning hook on Bash. The
    corpus pattern holds ``[a-zA-Z]``, which a deny artifact refuses (a
    letter range), so the deny run uses its class form ``[[:alpha:]]``."""
    import test_hook_command_view as view_tests

    with pytest.raises(RuleError, match="letter range"):
        hook_compiler.rule_artifact(view_tests.RID, TRIGGER, ["Bash"], view_tests.CORPUS_REGEX,
                                    "careful")
    classed = view_tests.CORPUS_REGEX.replace("[a-zA-Z]", "[[:alpha:]]")
    assert classed != view_tests.CORPUS_REGEX
    work = []
    for mode in ("deny", "warn"):
        regex = classed if mode == "deny" else view_tests.CORPUS_REGEX
        text = hook_compiler.generate_script(view_tests.RID, TRIGGER, ["Bash"], regex,
                                             "careful", mode=mode)
        art = hook_compiler.rule_artifact(view_tests.RID, TRIGGER, ["Bash"], regex,
                                          "careful", mode=mode)
        for name, (command, _) in sorted(view_tests.CORPUS.items()):
            work.append((f"{mode} {name}", text, art, _cmd(command)))
    assert len(work) > 300
    assert _differ(scripts, work) == []


@_LINUX_ONLY
def test_fixture_copies_match_their_sources():
    """The literal copies above are the blocks the other tests use."""
    import support
    import test_hook_command_view as view_tests
    import test_hook_compiler as compiler_tests
    import test_hook_regenerate as regenerate_tests

    from self_learn.overseer import formats

    def same(name, block, examples=None):
        _, _, mine, my_examples = FIXTURES[name]
        assert mine == block, name
        if examples is not None:
            assert my_examples == examples, name

    fields = support.hook_proposal_fields()
    same("support.hook_proposal_fields", fields["hook"], fields["examples"])
    for key in ("EXAMPLE_HOOK_INPUT", "EXAMPLE_POST_HOOK_INPUT", "EXAMPLE_DENY_HOOK_INPUT"):
        src = getattr(formats, key)
        same(f"overseer.formats.{key}", src["hook"], src["examples"])
    same("test_hook_command_view.HEREDOC_BLOCK", view_tests.HEREDOC_BLOCK,
         view_tests.HEREDOC_EXAMPLES)
    assert FIXTURES["test_hook_command_view.PGREP_REGEX"][2]["path_regex"] == view_tests.PGREP_REGEX
    assert FIXTURES["test_hook_command_view.WORD_REGEX"][2]["path_regex"] == view_tests.WORD_REGEX
    same("test_hook_regenerate.BASH_WARN", regenerate_tests.BASH_WARN)
    assert [e["tool_input"]["command"] for e in regenerate_tests.BASH_EXAMPLES["warn"]] == [
        e["tool_input"]["command"] for e in FIXTURES["test_hook_regenerate.BASH_WARN"][3]["warn"]]
    same("test_hook_regenerate.FILE_WARN", regenerate_tests.FILE_WARN,
         regenerate_tests.FILE_EXAMPLES)
    oracle = compiler_tests.DENY_ORACLE_ARGS
    rid, trigger, block, _ = FIXTURES["test_hook_compiler.DENY_ORACLE"]
    assert (rid, trigger, block["tools"], block["path_regex"], block["deny_message"]) == (
        oracle[0], oracle[1], oracle[2], oracle[3], oracle[4])
    same("test_hook_compiler.WARN_BLOCK", compiler_tests.WARN_BLOCK, compiler_tests.WARN_EXAMPLES)


def _awks() -> list[tuple[str, ...]]:
    found = []
    for cmd in (("awk",), ("gawk",), ("mawk",), ("gawk", "--posix"), ("busybox", "awk")):
        if shutil.which(cmd[0]) and (cmd[0] != "busybox" or subprocess.run(
                [cmd[0], "awk", "BEGIN{}"], capture_output=True).returncode == 0):
            found.append(cmd)
    return found


def _view_inputs() -> list[str]:
    import test_hook_command_view as view_tests

    out = [command for command, _ in view_tests.CORPUS.values()]
    out += list(view_tests.AT_CAP.values())
    atoms = ["'", '"', "\\", "$'", "$(", "$((", "((", ")", "`", "<<", "<<-", "<<<", "EOF",
             "\n", "\t", " ", "#", ";", "&", "|", "&>", ">>", "bash -c ", "git commit -m ",
             "gh pr create -t ", "gh issue comment --body ", "cat > f ", "cat >> 'a b' ",
             "tee -a f ", "<<'EOF'", "<<\\E", "\"$(cat <<'EOF'\n", ")\"", "2>&1", "E", "x",
             "é", "日", "\x01", "\r", "function git", "git=", "cat()", ".bashrc",
             "/tmp/", "*", "?", "[", "$"]
    rng = random.Random(5)
    for _ in range(1500):
        out.append("".join(rng.choice(atoms) for _ in range(rng.randint(1, 40))))
    return out


@_DIFF
@_LINUX_ONLY
def test_command_view_matches_the_awk_program():
    awks = _awks()
    assert awks, "no awk found"
    inputs = _view_inputs()

    def one(args):
        awk, command = args
        proc = subprocess.run([*awk, hook_compiler.COMMAND_VIEW_AWK],
                              input=command.encode("utf-8") + b"\n", capture_output=True,
                              env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"},
                              timeout=120)
        want = proc.stdout.rstrip(b"\n")
        got = hook_rules.command_view(command).encode("utf-8", "surrogateescape")
        if proc.returncode != 0 or want != got:
            return f"{' '.join(awk)}: {command[:120]!r}: awk {want[:200]!r} port {got[:200]!r}"
        return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        bad = [r for r in pool.map(one, [(a, c) for a in awks for c in inputs]) if r]
    assert bad == []


def test_command_view_is_linear_at_the_size_cap():
    cap = hook_rules.COMMAND_VIEW_MAX_CHARS
    for unit in ("git commit -m 'a'; ", "cat > f <<'E'\nx\nE\n", "'a' ", "(", "c;", "# don't\n"):
        command = unit * ((cap - 8) // len(unit))
        start = time.monotonic()
        hook_rules.command_view(command)
        assert time.monotonic() - start < 5.0, unit
    # M2: a file heredoc whose file name has no slash (one name scan, not one
    # per position): 128k characters took 2.8 s before rpartition
    for name_len in (32768, 131072, cap - 64):
        command = "cat > " + "a" * name_len + " <<'E'\nx\nE"
        start = time.monotonic()
        assert hook_rules.command_view(command) == command.replace("\nx\n", "\n")
        assert time.monotonic() - start < 1.0, name_len


def test_command_view_examples():
    """A few views by hand (the awk comparison above covers the corpus)."""
    v = hook_rules.command_view
    assert v('git commit -m "x y" && ls') == 'git commit -m "" && ls'
    assert v("cat > f.md <<'EOF'\nbody\nEOF\nls") == "cat > f.md <<'EOF'\nEOF\nls"
    assert v("echo 'a' \"c\"") == "echo 'a' \"c\""
    assert v("git commit -m 'x' $(ls)") == "git commit -m 'x' $(ls)"
    assert v("cat() { x; }; git commit -m 'x'") == "cat() { x; }; git commit -m 'x'"
    assert v("git commit -m 'é'") == "git commit -m ''"


#: Class patterns checked against grep, code point by code point, over
#: blocks whose assignments predate every Unicode version a supported glibc
#: ships (the tables were measured on one glibc; see hook_rules_ctype).
_CLASS_PATTERNS = [f"[[:{c}:]]" for c in hook_rules._CLASS_NAMES] + [
    r"\w", r"\W", r"\s", r"\S", ".", "[^a]", "[a-z]", "[A-Z0-9]"]
_SAMPLE_BLOCKS = [(0x01, 0x52F), (0x900, 0x97F), (0x1E00, 0x1FFF), (0x2000, 0x206F),
                  (0x2100, 0x218F), (0x3000, 0x303F), (0x4E00, 0x4E80), (0xFF00, 0xFF60),
                  (0x1F600, 0x1F64F)]


@_DIFF
@pytest.mark.parametrize("pattern", _CLASS_PATTERNS)
def test_classes_match_grep(pattern, tool_env):
    cps = [c for a, b in _SAMPLE_BLOCKS for c in range(a, b + 1) if c != 10]
    data = "".join(chr(c) + "\n" for c in cps).encode("utf-8")
    proc = subprocess.run(["grep", "-nE", "--", f"^{pattern}$"], input=data,
                          capture_output=True, env=tool_env, timeout=120)
    assert proc.returncode in (0, 1) and proc.stderr == b""
    want = {cps[int(line.split(b":", 1)[0]) - 1] for line in proc.stdout.split(b"\n") if line}
    matcher = hook_rules.compile_pattern(f"^{pattern}$")
    got = {c for c in cps if matcher.search(chr(c))}
    assert len(want) > 0 or pattern == r"[[:foo:]]"
    assert sorted(got ^ want)[:20] == []


@_DIFF
@pytest.mark.parametrize("pattern", sorted(REFUSED), ids=lambda p: repr(p)[:60])
def test_refusals_are_grounded_in_what_grep_does(pattern, tool_env):
    """Each refusal names a real grep behaviour, checked here: grep rejects
    the pattern, warns about it, reads it as literal text, answers
    differently under another locale, gives a non-obvious answer (QUIRKS),
    reads it as two patterns, or accepts it silently (a policy refusal: the
    evaluator does not model it exactly, or it would cost too much)."""
    _, how = REFUSED[pattern]
    assert how in ("rejects", "warns", "stray", "literal", "locale", "quirk", "policy",
                   "newline", "compiler"), how
    if how == "compiler":
        with pytest.raises(hook_compiler.HookCompileError):
            hook_compiler.generate_script(RID, TRIGGER, ["Bash"], pattern, "m")
        return

    def grep(text: str, locale: str = "C.UTF-8"):
        return subprocess.run(["grep", "-E", "--", pattern], input=text.encode("utf-8") + b"\n",
                              capture_output=True, env={**tool_env, "LC_ALL": locale}, timeout=60)

    probe = grep("a{1 a) ) {1}a *a x")
    locale_probes = ["é", "B", "$", "a", "à", "`", "_", "aa", "b"]

    def by_locale() -> tuple[list[int], list[int]]:
        avail = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout
        assert "en_US.utf8" in avail or "en_US.UTF-8" in avail, "en_US.UTF-8 is needed here"
        return ([grep(p).returncode for p in locale_probes],
                [grep(p, "en_US.UTF-8").returncode for p in locale_probes])

    if how == "rejects":
        assert probe.returncode == 2, probe
    elif how == "warns":
        assert probe.returncode < 2 and b"warning" in probe.stderr, probe
    elif how == "stray":
        # grep reads the character itself (3.8+ also warns; Ubuntu 26.04's
        # grep was measured silent): \d matches "d", never a digit
        literal = grep(pattern.replace("\\", ""))
        assert literal.returncode == 0, literal
        assert literal.stderr == b"" or b"stray" in literal.stderr, literal
        if pattern == r"\d":
            assert grep("1").returncode == 1
    elif how == "literal":
        own = grep(pattern)  # the pattern's own text is what it matches
        assert own.returncode == 0 and own.stderr == b"", own
    elif how == "locale":
        here, us = by_locale()
        assert 2 not in here and here != us, (here, us)
    elif how == "quirk":
        text, grep_rc, _ = QUIRKS[pattern]
        assert grep(text).returncode == grep_rc
    elif how == "newline":
        first, second = pattern.split("\n")
        assert grep(first).returncode == 0 and grep(second).returncode == 0  # two patterns
        assert probe.stderr == b""
    else:  # policy: accepted silently, and the same answers under either locale
        assert probe.returncode < 2 and probe.stderr == b"", probe
        here, us = by_locale()
        assert here == us, (here, us)
