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

import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from self_learn import hook_compiler, hook_rules
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


@pytest.mark.parametrize("case", [c[0] for c in CASES])
def test_recorded_decision(case):
    _, rule_name, data = next(c for c in CASES if c[0] == case)
    got = hook_rules.evaluate(_rule(rule_name), data)
    assert (got.exit_code, got.stdout, got.stderr) == EXPECTED[case]


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
    # test_route_hook.py: three live guards, inline in their tests
    "test_route_hook.chezmoi_cd": ("lrn-98d42215", "About to run `chezmoi cd` in a non-interactive shell", {
        "tools": ["Bash"],
        "path_regex": r"(^|[;&|[:space:]])chezmoi[[:space:]]+cd([[:space:]]|$)",
        "deny_message": "chezmoi cd spawns an interactive child shell and blocks — use git -C \"$(chezmoi source-path)\" instead",
    }, {
        "allow": [_b("chezmoi diff"), _b('git -C "$(chezmoi source-path)" status'),
                  _b("chezmoi cd-what a-weird-arg")],
        "deny": [_b("chezmoi cd"), _b("cd /tmp && chezmoi cd")],
    }),
    "test_route_hook.sudo_npm_global": ("lrn-6883f824", "About to run sudo npm install -g on this Arch system", {
        "tools": ["Bash"],
        "path_regex": r"sudo([[:space:]]+[^[:space:]]+)*[[:space:]]+npm[[:space:]]+(install|i|add)([[:space:]]+[^[:space:]]+)*[[:space:]]+(-g|--global)",
        "deny_message": "never sudo npm install -g here — it splits pacman's npm ownership; use pacman/paru or a user prefix",
    }, {
        "allow": [_b("npm install -g yarn --prefix ~/.local"), _b("sudo npm --version"),
                  _b("npm install left-pad")],
        "deny": [_b("sudo npm install -g corepack"), _b("sudo npm install --global npm@latest"),
                 _b("sudo npm install -g npm")],
    }),
    "test_route_hook.uv_venv_copy": ("lrn-25968266", "About to sandbox-copy a uv Python project", {
        "tools": ["Bash"],
        "path_regex": r"(cp[[:space:]]+-[a-zA-Z]*r|rsync[[:space:]])(.*[[:space:]])?[^[:space:]]*\.venv",
        "deny_message": "a copied .venv still points at the ORIGINAL tree — rm -rf <copy>/.venv and re-sync in the copy first",
    }, {
        "allow": [_b("cp -r src/ /tmp/scratch/"), _b("rm -rf /tmp/copy/.venv"), _b("uv sync")],
        "deny": [_b("cp -r project/.venv /tmp/copy/.venv"), _b("rsync -a proj/.venv/ /tmp/copy/.venv/"),
                 _b("cp -r p/.venv /tmp/c/.venv")],
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


def _fixture_artifact(name: str) -> dict:
    rid, trigger, block, examples = FIXTURES[name]
    return hook_compiler.rule_artifact_for_hook(rid, trigger, block, examples)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_examples_decide_as_approved(name):
    """Each fixture's approved examples (replayed against the Bash script by
    the route verb, and by the differential below) get their verdicts from
    the evaluator alone; the build itself refuses on any disagreement."""
    rule = hook_rules.load_rule(hook_rules.dumps_rule(_fixture_artifact(name)))
    assert rule.examples, name  # positive control: there is something to check
    assert hook_rules.check_examples(rule) == []


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
    import hashlib

    assert a["version"] == 1 and a["kind"] == "self-learn-hook-rule"
    assert a["script_sha256"] == hashlib.sha256(script.encode("utf-8")).hexdigest()
    assert a["script_name"] == hook_compiler.script_name(rid, trigger)
    assert a["match"] == {"dialect": hook_rules.DIALECT, "pattern": r"\.storage/", "view": None}
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


@pytest.mark.parametrize("label,artifact,why", [
    ("unknown version", lambda: _mutated(version=2), "unknown version 2"),
    ("version as text", lambda: _mutated(version="1"), "unknown version"),
    ("wrong kind", lambda: _mutated(kind="other"), "kind"),
    ("an extra key", lambda: _mutated(extra=1), "keys"),
    ("bad dialect", lambda: _mutated(match={"dialect": "pcre", "pattern": "x", "view": None}),
     "unknown matcher dialect"),
    ("a view on a deny rule", lambda: _mutated(
        match={"dialect": hook_rules.DIALECT, "pattern": "x", "view": hook_rules.VIEW_COMMAND}),
     "command view"),
    ("a deny on PostToolUse", lambda: _mutated(event="PostToolUse"), "cannot run on"),
    ("an unguardable tool", lambda: _mutated(tools=["Read"]), "bad tools"),
    ("fields that do not fit", lambda: _mutated(fields={"Edit": "command", "Write": "file_path"}),
     "fields"),
    ("a refused pattern", lambda: _mutated(
        match={"dialect": hook_rules.DIALECT, "pattern": r"\d", "view": None}), "stray backslash"),
    ("an output without the prefix", lambda: _mutated(output="stop"), "deny output"),
    ("a bad example verdict", lambda: _mutated(examples=[{"input": {}, "expect": "warn"}]),
     "bad examples"),
    ("missing error line", lambda: _mutated(error_lines={"tool": 26}), "error_lines"),
])
def test_load_refuses(label, artifact, why):
    with pytest.raises(RuleError, match=re.escape(why)):
        hook_rules.load_rule(artifact())


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
    for junk in (b"", b"[]", b"{", b"null"):
        with pytest.raises(RuleError):
            hook_rules.load_rule(junk)


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

#: pattern -> (reason fragment, how grep itself treats it)
REFUSED = {
    r"\d": ("stray backslash", "warns"),
    r"\/": ("stray backslash", "warns"),
    r"a\-b": ("stray backslash", "warns"),
    r"\n": ("stray backslash", "warns"),
    r"(a)\1": ("back-reference", "unsupported"),
    r"*a": ("nothing before it", "warns"),
    r"a|*b": ("nothing before it", "warns"),
    r"(*a)": ("nothing before it", "warns"),
    r"(?i)a": ("nothing before it", "warns"),
    r"{1}a": ("nothing before it", "warns"),
    r"^*": ("repeats an anchor", "warns"),
    r"a\b*": ("repeats an anchor", "unsupported"),
    r"a{": ("does not open a count", "literal"),
    r"a{1": ("does not open a count", "literal"),
    r"a{x}": ("does not open a count", "literal"),
    r"a{,}": ("does not open a count", "unsupported"),
    r"a{2,1}": ("minimum is above", "rejects"),
    r"a{32768}": ("count over", "rejects"),
    r"[[=a=]]": ("collating element", "locale"),
    # one-character collating symbols mean the character itself, but named
    # ones ([[.hyphen.]]) and multi-character ones depend on the locale's
    # collation tables: the whole form is refused rather than half-supported
    r"[[.a.]]": ("collating element", "unsupported"),
    r"[[:foo:]]": ("not a character class", "rejects"),
    r"[z-a]": ("not inside one of", "rejects"),
    r"[!-~]": ("not inside one of", "locale"),
    r"[A-z]": ("not inside one of", "locale"),
    "[à-ü]": ("not inside one of", "locale"),
    r"[a-c-e]": ("another '-'", "unsupported"),
    r"[[:alpha:]-z]": ("starts at a character class", "rejects"),
    r"[a-[:alpha:]]": ("ends at a character class", "rejects"),
    r"(a": ("never closed", "rejects"),
    r"[a": ("never closed", "rejects"),
    r"a)": ("closes no group", "literal"),
    r")": ("closes no group", "literal"),
    "a\\": ("lone backslash", "rejects"),
    "a\nb": ("newline", "unsupported"),
    "": ("empty", "unsupported"),
    r"(a{100}){100}": ("matching steps", "unsupported"),
    r"x{4097}": ("matching steps", "unsupported"),
}

ACCEPTED = [
    r"\.storage/", r"a{,3}", r"a{0}", r"a{2}{3}", r"a**", r"a+?", r"()", r"a|", r"|a",
    r"x}y", r"x]y", r"[]a]", r"[^]a]", r"[a-]", r"[\d]", r"[[:alpha:][:digit:]_]",
    r"\<\>\b\B\w\W\s\S\`\'", r"\.\[\]\(\)\*\+\?\{\}\|\^\$\\", "日本+", r"x{4000}",
    r"(^)*a", r"a($)?",
]


@pytest.mark.parametrize("pattern", sorted(REFUSED))
def test_refused_patterns(pattern):
    why, _ = REFUSED[pattern]
    with pytest.raises(RuleError, match=re.escape(why)):
        hook_rules.compile_pattern(pattern)


@pytest.mark.parametrize("pattern", ACCEPTED)
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
    assert late.reason == "match-deadline"


def test_a_full_dfa_cache_is_rebuilt_without_changing_the_answer(monkeypatch):
    monkeypatch.setattr(hook_rules, "_CACHE_LIMIT", 8)
    matcher = hook_rules.compile_pattern(r"[[:alpha:]]{3}[0-9]")
    text = "".join(chr(0x4E00 + i) + "1" for i in range(500)) + "abc5"
    assert matcher.search(text) is True
    assert matcher.search(text[:-1]) is False
    assert matcher._size <= 8 + 4  # the cache stayed bounded


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


def _differ(scripts: _Scripts, work: list[tuple[str, str, dict, bytes]]) -> list[str]:
    """work: (label, script text, artifact, stdin). Every row's script and
    evaluator decisions, compared; one line per difference."""
    paths: dict[str, Path] = {}
    rules: dict[str, hook_rules.Rule] = {}
    for _, text, art, _ in work:
        if text not in paths:
            paths[text] = scripts.write(text)
            rules[text] = hook_rules.load_rule(art)

    def one(row):
        label, text, _, data = row
        want = scripts.run(paths[text], data)
        got = hook_rules.evaluate(rules[text], data)
        mine = (got.exit_code, got.stdout, got.stderr)
        if any(_DIAG.match(line) for line in got.stderr.splitlines(True)):
            return f"{label}: the evaluator wrote a tool diagnostic: {got.stderr!r}"
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

#: Where jq is more lenient than JSON and the evaluator is not: a number
#: jq accepts (``nan``, ``01``, ``.5``, ``1.``). The evaluator treats the
#: input as malformed: a deny guard fails closed, a warning stays silent;
#: the script may instead read the number and decide on it.
JQ_LENIENT = [
    b'{"tool_name":nan}', b'{"tool_name":"Bash","tool_input":{"command":01}}',
    b'{"tool_name":"Bash","tool_input":{"command":.5}}',
    b'{"tool_name":"Bash","tool_input":{"command":1.}}', b"NaN",
]


@pytest.mark.parametrize("data", JQ_LENIENT)
def test_jq_lenient_numbers_fail_closed(data):
    deny = hook_rules.evaluate(_rule("deny-push"), data)
    assert (deny.exit_code, deny.stdout, deny.reason) == (2, b"", "malformed-input")
    assert deny.stderr == f"self-learn {RID}: guard error on line 26 — failing closed\n"
    warn = hook_rules.evaluate(_rule("warn-bash"), data)
    assert (warn.exit_code, warn.stdout, warn.stderr) == (0, b"", "")

#: Field values, wrapped for each tool a rule names (and for one it does not).
VALUES = [
    "", "\n", " ", "x", "x\ny", "\nx\n", "a\r\nb", "éè€\U0001f600", " ",
    "\x01\x7f", "\u0000", "tab\there", "\\", "'quoted' \"double\"", "x" * 20000,
    5, 0, -0.5, True, False, None, [], [""], ["x", "y"], {}, {"k": "v", "n": [1, None, True]},
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
    assert _differ(scripts, work) == []
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
    art = hook_compiler.rule_artifact_for_hook(rid, trigger, block, examples)
    work = [(f"{verdict}[{i}]", text, art, json.dumps(ex).encode())
            for verdict, items in examples.items() for i, ex in enumerate(items)]
    work += [(f"adversarial[{i}]", text, art, data)
             for i, data in enumerate(_inputs_for(block["tools"]))]
    assert len(work) > 60
    assert _differ(scripts, work) == []


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
    r"(^)*a": ["a", "ba"],
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
        art = hook_compiler.rule_artifact(RID, TRIGGER, tools, pattern, "m", mode=mode)
        for i, probe in enumerate(DIALECT[pattern]):
            work.append((f"{mode} command[{i}]", text, art, _cmd(probe)))
            work.append((f"{mode} path[{i}]", text, art, _path(probe)))
    assert _differ(scripts, work) == []


@_DIFF
@_LINUX_ONLY
def test_differential_command_view_corpus(scripts):
    """The S-133 corpus, through the deny and the warning hook on Bash."""
    import test_hook_command_view as view_tests

    work = []
    for mode in ("deny", "warn"):
        text = hook_compiler.generate_script(view_tests.RID, TRIGGER, ["Bash"],
                                             view_tests.CORPUS_REGEX, "careful", mode=mode)
        art = hook_compiler.rule_artifact(view_tests.RID, TRIGGER, ["Bash"],
                                          view_tests.CORPUS_REGEX, "careful", mode=mode)
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
@pytest.mark.parametrize("pattern", sorted(REFUSED))
def test_refusals_are_grounded_in_what_grep_does(pattern, tool_env):
    """Each refusal names a real grep behaviour: grep rejects the pattern,
    warns about it, reads it as a literal POSIX leaves unspecified, or
    answers differently under another locale."""
    _, how = REFUSED[pattern]
    if "\n" in pattern or not pattern:
        return  # grep -E reads a newline as two patterns; the compiler refuses an empty one

    def grep(text: str, locale: str = "C.UTF-8"):
        return subprocess.run(["grep", "-E", "--", pattern], input=text.encode("utf-8") + b"\n",
                              capture_output=True, env={**tool_env, "LC_ALL": locale}, timeout=60)

    probe = grep("a{1 a) ) {1}a *a x")
    if how == "rejects":
        assert probe.returncode == 2, probe
    elif how == "warns":
        assert probe.returncode < 2 and b"warning" in probe.stderr, probe
    elif how == "literal":
        assert probe.returncode < 2 and probe.stderr == b"", probe
    elif how == "locale":
        probes = ["é", "B", "$", "a", "à"]
        here = [grep(p).returncode for p in probes]
        us = [grep(p, "en_US.UTF-8").returncode for p in probes]
        avail = subprocess.run(["locale", "-a"], capture_output=True, text=True)
        if "en_US.utf8" in avail.stdout or "en_US.UTF-8" in avail.stdout:
            assert here != us or 2 in here, (here, us)
