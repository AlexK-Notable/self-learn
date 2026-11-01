"""S-133: a warning hook on Bash hides only a commit or gh message and a
heredoc written to a file, in their exact shapes; every other command is
matched on its raw text, as before S-133.

The live defect (notice ntc-71c2eb83, lesson lrn-042c8179): the heredoc
warning hook of lrn-c71f0a40 grepped the raw command, so a commit message
or a heredoc that only MENTIONED ``python3 - <<EOF </dev/null`` fired the
warning. Gate r3's rule (the orchestrator's): an exact-shape allowlist.
A1, the message argument of ``git commit -m|-am|--message`` or of ``gh
pr|issue create|comment -t|-b|--title|--body`` given as a single-quoted
string, a plain double-quoted string or the commit idiom; A2, the body of
``cat >|>> FILE <<'D'`` or ``tee [-a] FILE <<'D'``. Anything else -- and
any construct the scan does not tokenize exactly -- is the raw command.

Every test runs the GENERATED script (or its embedded awk program) against
sample commands -- the suite's mock-free convention. The corpus below is
the builder's own cases plus every input gates r1, r2 and r3 probed with.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from self_learn.hook_compiler import (
    COMMAND_VIEW_AWK,
    COMMAND_VIEW_MAX_BYTES,
    generate_script,
    replay_examples,
    script_for_hook,
)

RID = "lrn-c71f0a40"
TRIGGER = "About to run a Bash tool command that feeds a script"

#: lrn-c71f0a40's own hook block and examples, copied from the live ledger
#: record (read only, 2026-11-01): the regex the false positive came from.
HEREDOC_REGEX = r"<<-?[[:space:]]*[^[:space:]<|;&]+([^|;&]|&[0-9])*<[[:space:]]*/dev/null"
HEREDOC_BLOCK = {
    "mode": "warn",
    "event": "PreToolUse",
    "tools": ["Bash"],
    "path_regex": HEREDOC_REGEX,
    "warn_message": "This command feeds stdin from a heredoc and also redirects stdin "
                    "from /dev/null on the same command. (lrn-c71f0a40)",
}
HEREDOC_EXAMPLES = {
    "allow": [
        {"tool_name": "Bash", "tool_input": {
            "command": "cat > /tmp/check.py <<'EOF'\nprint(1)\nEOF\n"
                       "python3 /tmp/check.py </dev/null 2>&1 | tail -8"}},
        {"tool_name": "Bash", "tool_input": {"command": "some-tool --dir ./in </dev/null"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 - <<'EOF'\nprint(1)\nEOF"}},
    ],
    "warn": [
        {"tool_name": "Bash", "tool_input": {
            "command": "python3 - <<'EOF' </dev/null\nprint(1)\nEOF"}},
        {"tool_name": "Bash", "tool_input": {
            "command": "uv run python - <<PY 2>&1 </dev/null\nimport sys\n"
                       "print(sys.version)\nPY"}},
    ],
}
#: lrn-19f82fc5's live regex: anchored on a word boundary.
PGREP_REGEX = r"(^|[;&|(`[:space:]])p(kill|grep)([[:space:]]+-[^[:space:]]+)*[[:space:]]+(-[a-zA-Z]*f[a-zA-Z]*|--full)([[:space:]]|$)"
#: The gate's word probe: matches after a quote mark too.
WORD_REGEX = r"(^|[^[:alnum:]_-])(pkill|danger)([^[:alnum:]_-]|$)"
#: One hook carrying all three, so a corpus case is one run.
CORPUS_REGEX = "|".join(f"({r})" for r in (HEREDOC_REGEX, PGREP_REGEX, WORD_REGEX))

BAD = "python3 - <<EOF </dev/null"  # the shape the heredoc hook warns on


def _guard(tmp_path: Path, regex: str = HEREDOC_REGEX, *, mode: str = "warn",
           tools: tuple[str, ...] = ("Bash",)) -> Path:
    text = generate_script(RID, TRIGGER, list(tools), regex,
                           "careful" if mode == "warn" else "stop", mode=mode)
    path = tmp_path / f"{mode}-{abs(hash((regex, tools))) % 10**8}.sh"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def _run(script: Path, command: str, env: dict | None = None) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run([str(script)], input=payload, capture_output=True, text=True,
                          env=env, timeout=60)


def _warns(script: Path, command: str, env: dict | None = None) -> bool:
    proc = _run(script, command, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    if proc.stdout == "":
        return False
    assert json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"] == (
        f"self-learn {RID}: careful")
    return True


def _view(command: str, awk: tuple[str, ...] = ("awk",)) -> subprocess.CompletedProcess:
    return subprocess.run([*awk, COMMAND_VIEW_AWK], input=command + "\n",
                          capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"},
                          timeout=60)


# ------------------------------------------------------------- the corpus

#: name -> (command, expectation). ``warn``: matched as the raw text is --
#: everything outside an A1/A2 hidden span. ``silent``: the pattern appears
#: only inside an A1 message or an A2 body, so the view does not warn while
#: the raw matcher does (the control). ``none``: nothing to warn on, raw or
#: viewed. ``syntax``: bash rejects the input, so nothing runs; no claim.
CORPUS: dict[str, tuple[str, str]] = {
    # --- the builder's own: understood mentions
    "own: double-quoted commit message": (f'git commit -m "docs: {BAD}"', "silent"),
    "own: single-quoted argument": (f"echo '{BAD}'", "warn"),
    "own: heredoc body, quoted delimiter": (f"cat > notes.md <<'MD'\nnever run {BAD}\nMD", "silent"),
    "own: heredoc body, bare delimiter": (f"cat > notes.md <<MD\nnever run {BAD}\nMD", "warn"),
    "own: heredoc body with an apostrophe": (f"cat <<EOF\ndon't {BAD}\nEOF", "warn"),
    "own: two heredocs on one line": (f"cat <<A <<B\nx\nA\n{BAD}\nB", "warn"),
    "own: tab-stripped heredoc": (f"cat <<-EOF\n\t{BAD}\n\tEOF", "warn"),
    "own: python -c double-quoted, no $": (f"python3 -c \"print('{BAD}')\"", "warn"),
    "own: pkill in a commit message": ('git commit -m "never pkill -f a pattern"', "silent"),
    "own: pgrep in a quoted heredoc": ("cat <<'EOF' > NOTES.md\npgrep -f x matches itself\nEOF", "warn"),
    "own: $( ) in a quoted heredoc body": ("cat <<'EOF'\nrun $(pkill -f foo) danger\nEOF", "warn"),
    "own: quoted heredoc inside $( )": ("x=$(cat <<'EOF'\npkill -f foo\nEOF\n)", "warn"),
    # --- the builder's own: real invocations
    "own: the lesson's own example": ("python3 - <<'EOF' </dev/null\nprint(1)\nEOF", "warn"),
    "own: after an escaped quote outside quotes": (f'echo \\"x\\"; {BAD}\nEOF', "warn"),
    "own: between escaped apostrophes": (f"echo \\' {BAD} \\'\nEOF", "warn"),
    "own: bash -c single-quoted payload": (f"bash -c '{BAD}\nprint(1)\nEOF'", "warn"),
    "own: sh -c double-quoted payload": ("sh -c \"uv run python - <<PY 2>&1 </dev/null\nPY\"", "warn"),
    "own: bash -lc after other options": (f"sudo bash -o pipefail -lc '{BAD}\nEOF'", "warn"),
    "own: eval payload": (f'eval "{BAD}"', "warn"),
    "own: ssh remote command": (f"ssh host '{BAD}\nEOF'", "warn"),
    "own: a heredoc fed to a shell": (f"bash <<'SH'\n{BAD}\nprint(1)\nEOF\nSH", "warn"),
    "own: a here-string": ("python3 <<<'print(1)' </dev/null", "warn"),
    "own: a real line after a tab-stripped heredoc": (f"cat <<-EOF\n\tx\n\tEOF\n{BAD}\nEOF", "warn"),
    "own: after a heredoc whose body has quotes": (f"cat <<EOF\nit's \"x\nEOF\n{BAD}\nEOF", "warn"),
    "own: quoted argument, real command": ("pkill -f 'node server'", "warn"),
    "own: $( ) in double quotes": ('echo "pids: $(pgrep -f worker)"', "warn"),
    "own: backticks": ("echo `pgrep -f worker`", "warn"),
    "own: backticks in double quotes": ('echo "`pgrep -f worker`"', "warn"),
    "own: bash -c, word-anchored": ("bash -c 'pkill -f node'", "warn"),
    "own: sudo sh -c": ('sudo sh -c "pgrep -f worker"', "none"),  # raw misses it too (a quote before pgrep), as on master
    "own: eval ANSI-C": ("eval $'pkill -f x'", "warn"),
    # --- shown by the conservative rule (not understood, so visible)
    "rule: the commit idiom ($( ) in double quotes)": (f"git commit -m \"$(cat <<'EOF'\nfix: {BAD}\nEOF\n)\"", "silent"),
    "rule: escaped quotes in double quotes": (f'echo "he said \\"{BAD}\\" twice"', "warn"),
    "rule: ANSI-C quoting": (f"printf $'it\\'s {BAD}'", "warn"),
    "rule: a comment": (f"ls  # {BAD}", "warn"),
    "rule: a heredoc with no terminator line": (f"cat <<EOF\n{BAD}", "warn"),
    "rule: a double-quoted payload's single quotes": (f"bash -c \"echo '{BAD}'\"", "warn"),
    "rule: an unquoted heredoc body holding $( )": ("cat <<EOF\n$(date) danger\nEOF", "warn"),
    "rule: a here-string to any command": ('cat <<< "pkill -f foo"', "warn"),
    "rule: a here-string holding $( )": ("bash <<< \"$(echo 'x')\"; echo 'pkill -f foo'", "warn"),
    "rule: a comment after a subshell": ("(echo a) # pkill -f foo", "warn"),
    "rule: a double-quoted string holding $": ('echo "$HOME danger"', "warn"),
    # --- gate r1, cases1 (the gate's inputs, verbatim)
    "r1: plain": ("pkill -f foo", "warn"),
    "r1: commitmsg": ('git commit -m "pkill -f foo danger"', "silent"),
    "r1: bashc": ("bash -c 'pkill -f foo; danger'", "warn"),
    "r1: arith-shift": ("x=$((1 << 2))\npkill -f foo\ndanger", "warn"),
    "r1: arith-shift2": ("echo $((a<<b)); danger", "warn"),
    "r1: ssh-heredoc": ("ssh host <<'EOF'\npkill -f foo\nEOF", "warn"),
    "r1: pipe-to-bash": ("cat <<'EOF' | bash\npkill -f foo\nEOF", "warn"),
    "r1: subst-hash": ("echo $(date)#tag; pkill -f foo", "warn"),
    "r1: paren-hash": ("(echo a)#x; danger", "warn"),
    "r1: watch": ("watch -n1 'pkill -f foo'", "warn"),
    "r1: bash-c--": ("bash -c -- 'pkill -f foo'", "warn"),
    "r1: quoted-cmd": ('"pkill" -f foo', "warn"),
    "r1: quoted-arg": ('rm -rf "$HOME/.self-learn" danger', "warn"),
    "r1: python-c": ('python3 -c \'import os; os.system("pkill -f foo")\'', "warn"),
    "r1: heredoc-commit": ("git commit -m \"$(cat <<'EOF'\nfix: pkill -f foo danger\nEOF\n)\"", "silent"),
    "r1: heredoc-sh": ("bash <<EOF\npkill -f foo\nEOF", "warn"),
    "r1: bash-s-arg": ("bash -s -- arg <<EOF\npkill -f foo\nEOF", "warn"),
    "r1: xargs": ("echo x | xargs -I{} sh -c 'pkill -f {}'", "warn"),
    "r1: eval": ('eval "pkill -f foo"', "warn"),
    "r1: dq-subst": ('echo "$(pkill -f foo)"', "warn"),
    "r1: bt": ('echo "`pkill -f foo`"', "warn"),
    "r1: herestring": ("bash <<< 'pkill -f foo'", "warn"),
    "r1: unbalanced": ("echo 'oops; pkill -f foo", "syntax"),
    "r1: crlf": ("cat <<EOF\r\nbody\r\nEOF\r\npkill -f foo\r\n", "warn"),
    "r1: multi-heredoc": ("cat <<A <<B\na pkill -f x\nA\nb danger\nB\npkill -f foo", "warn"),
    "r1: tab-heredoc": ("cat <<-EOF\n\tdanger\n\tEOF\npkill -f foo", "warn"),
    "r1: comment": ("ls # pkill -f foo\ndanger", "warn"),
    "r1: subshell-case": ('echo "$(case x in a) echo;; esac)"; pkill -f foo', "warn"),
    "r1: ansi": ("echo $'it\\'s'; pkill -f foo", "warn"),
    "r1: trap": ("trap 'pkill -f foo' EXIT", "warn"),
    "r1: sudo-bash": ('sudo bash -c "pkill -f foo"', "warn"),
    "r1: dollar-paren-unq": ("x=$(pkill -f foo)", "warn"),
    "r1: backslash-cont": ("pkill \\\n -f foo", "warn"),
    "r1: in-dq-nested": ('echo "$(echo "$(pkill -f foo)")"', "warn"),
    "r1: fn": ("f() { pkill -f foo; }; f", "warn"),
    "r1: heredoc-then-same-line": ("cat <<EOF; pkill -f foo\nbody\nEOF", "warn"),
    "r1: lt-lt-noword": ("cat <<\npkill -f foo", "syntax"),
    "r1: git-c": ("git -c 'core.sshCommand=ssh' push", "none"),
    # --- gate r1, cases2
    "r1: dq-arith": ('echo "$((1<<2))"\npkill -f foo', "warn"),
    "r1: arith-cmd": ("(( n <<= 1 ))\npkill -f foo", "warn"),
    "r1: dd-bs": ("dd if=/dev/zero of=f bs=$((1<<20)) count=1\npkill -f foo", "warn"),
    "r1: procsub-hash": ("diff <(ls)#x <(ls); pkill -f foo", "warn"),
    "r1: herestring-bash": ('bash <<< "pkill -f foo"', "warn"),
    "r1: dq-nested-param": ('echo "${x:-"a b"}"; pkill -f foo', "warn"),
    "r1: two-line-ok": ("true\npkill -f foo", "warn"),
    "r1: sq-in-comment": ("ls # don't\npkill -f foo", "warn"),
    "r1: apostrophe-heredoc-delim-line": ("cat <<EOF\nit's\nEOF\npkill -f foo", "warn"),
    "r1: heredoc-in-subst-unquoted": ("x=$(cat <<EOF\nbody\nEOF\n)\npkill -f foo", "warn"),
    "r1: heredoc-quoted-word-nl-in-dq": ('cat <<EOF; echo "a\nb"\nbody\nEOF\npkill -f foo', "warn"),
    # --- gate r1, the fold's own GATE inputs
    "r1 fold: F1 a $(( that is a subshell": ("x=$((cd /; pkill -f foo) | wc -l)", "warn"),
    "r1 fold: F4 here-string, ANSI-C": ("bash <<< $'pkill -f foo'", "warn"),
    "r1 fold: here-string to a shell, then quoted text": ("bash <<< x; echo 'pkill -f foo'", "warn"),
    "r1 fold: quoted here-string, then quoted text": ("bash <<< 'true'; echo 'pkill -f foo'", "warn"),
    "r1 fold: a trap's signal list": ("trap 'echo hi' 'pkill -f foo'", "warn"),
    "r1 fold: arithmetic leaves later quotes alone": ('x=$((1<<2)); echo "pkill -f foo"', "warn"),
    # --- gate r2, cases3
    "r2: arith-then-cmd": ("(( x )) && pkill -f foo", "warn"),
    "r2: arith-subst": ("echo $(( $(pkill -f foo) ))", "warn"),
    "r2: dq-arith-subst": ('echo "$(( $(pkill -f foo) ))"', "warn"),
    "r2: dq-arith-bt": ('echo "$(( `pkill -f foo` ))"', "warn"),
    "r2: cmd-arith-subst": ("(( $(pkill -f foo) ))", "warn"),
    "r2: unterminated-arith": ("(( x <<= 1\npkill -f foo", "warn"),
    "r2: unterminated-darith": ("echo $(( 1 << 2\npkill -f foo", "warn"),
    "r2: arith-with-quote-inside": ("(( x == $(echo ')') )); pkill -f foo", "warn"),
    "r2: arith-span-swallows-quote": ('(( a )) ; echo "x" ; (( b + \'1\' )) ; pkill -f foo', "warn"),
    "r2: arith-unbal-paren-in-str": ("echo $(( $(echo '(') )) ; pkill -f foo ; echo ')) '", "warn"),
    "r2: nested-subshell-not-arith": ("((cd /tmp; ls) && pkill -f foo)", "warn"),
    "r2: arith-heredoc-inside": ("(( $(cat <<EOF\n1\nEOF\n) ))\npkill -f foo", "warn"),
    "r2: herestring-sh-unquoted-then-quote": ("bash <<< x 'pkill -f foo'", "warn"),
    "r2: herestring-forced-leak": ('bash <<< "$x"; git commit -m "pkill -f foo"', "warn"),
    "r2: herestring-sh-then-squote-later": ("sh <<< 'true' && echo 'pkill -f foo'", "warn"),
    "r2: herestring-sudo-bash": ("sudo bash <<< 'pkill -f foo'", "warn"),
    "r2: herestring-python": ('python3 <<< \'import os; os.system("pkill -f foo")\'', "warn"),
    "r2: trap-dash": ("trap -- 'pkill -f foo' EXIT", "warn"),
    "r2: trap-p": ("trap -p 'pkill -f foo'", "warn"),
    "r2: commit-msg-trap-word": ('git commit -m "trap" -m "pkill -f foo"', "silent"),
    "r2: echo-trap (G5, an extra warning)": ("echo trap 'pkill -f foo'", "warn"),
    "r2: paren-hash-fp": ("(echo a)#x; pkill -f foo", "warn"),
    "r2: arith-dollar-paren-paren-cmdsub": ("x=$((echo a); pkill -f foo)", "warn"),
    "r2: arith-in-heredoc-body": ("cat <<EOF\n$((1<<2))\nEOF\npkill -f foo", "warn"),
    "r2: force-across-newline": ("bash <<<\n'pkill -f foo'", "syntax"),
    # --- gate r2, G1 (quoted arithmetic around a substitution)
    "r2 G1: count inside quoted arithmetic": ('x="$(( $(pgrep -f worker | wc -l) + 1 ))"', "warn"),
    "r2 G1: substitution in quoted arithmetic": ('echo "$(( $(pkill -f foo) ))"', "warn"),
    "r2 G1: backticks in quoted arithmetic": ('echo "$(( `pkill -f foo` ))"', "warn"),
    # --- the gate r2 fold's own controls (mutation-driven)
    "r2 fold: a comment after a subshell's )": ("(cd x)# don't\npkill -f foo 'y'", "warn"),
    "r2 fold: a # after a substitution's ) is a word": ("echo $(date)#x 'pkill -f foo'", "warn"),
    "r2 fold: the here-string flag ends with its word":
        ("bash <<< 'a'; git commit -m 'pkill -f foo'", "warn"),
    "r2 fold: an inner quote in $( ) in double quotes":
        ('echo "$(echo "a" \'pkill -f foo\')"', "warn"),
    "r2 fold: an inner quote in backticks in double quotes":
        ('echo "`echo "a" \'pkill -f foo\'`"', "warn"),
    "r2 fold: a heredoc delimiter holding $ keeps its body":
        ("cat <<$X >f\npkill -f foo\n$X\nls", "warn"),
    "r2 fold: a heredoc after closed arithmetic":
        ("echo $((1<<2)); cat <<'E' >f\npkill -f foo\nE", "warn"),
    "r2 fold: a shift in (( )), then a line equal to its operand":
        ("(( x = 1 << 2 ))\npkill -f foo\n2", "warn"),
    # --- the commit idiom, recognised exactly (coordinator, before gate r3)
    "idiom: this repo's commit": ("git commit -q -m \"$(cat <<'EOF'\nfix(hooks): a warning hook on Bash matches the command's words\n\nThe live hook fired on pkill -f text and on notify-send -A examples;\na heredoc fed </dev/null was only quoted here: python3 - <<EOF </dev/null\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nEOF\n)\"", "silent"),
    "idiom: double-quoted delimiter": ("git commit -m \"$(cat <<\"EOF\"\npkill -f foo\nEOF\n)\"", "silent"),
    "idiom: backslash delimiter": ("git commit -m \"$(cat <<\\EOF\npkill -f foo\nEOF\n)\"", "silent"),
    "idiom: <<- with a tab-indented terminator": ("git commit -m \"$(cat <<-'EOF'\n\tpkill -f foo\n\tEOF\n)\"", "silent"),
    "idiom: a command after it on the same line": ("git commit -m \"$(cat <<'E'\nmsg\nE\n)\" && pkill -f foo", "warn"),
    "idiom: a command after it on the next line": ("git commit -m \"$(cat <<'E'\nmsg\nE\n)\"\npkill -f foo", "warn"),
    "idiom near-miss: unquoted delimiter": ("git commit -m \"$(cat <<EOF\npkill -f foo\nEOF\n)\"", "warn"),
    "idiom near-miss: cat reads a file too": ("git commit -m \"$(cat file <<'E'\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: piped into sh inside": ("x=\"$(cat <<'E' | sh\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: bash, not cat": ("x=\"$(bash <<'E'\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: sh with two spaces, not cat": ("x=\"$(sh  <<'E'\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: a mismatched delimiter quote": ("x=\"$(cat <<'E\"\npkill -f foo\nE\n)\"", "warn"),
    "idiom: no blank between cat and <<": ("git commit -m \"$(cat<<'EOF'\npkill -f foo\nEOF\n)\"", "silent"),
    "idiom near-miss: catx, not cat": ("x=\"$(catx <<'E'\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: no terminator": ("git commit -m \"$(cat <<'E'\npkill -f foo\n)\"", "warn"),
    "idiom near-miss: terminator with a trailing space": ("git commit -m \"$(cat <<'E'\npkill -f foo\nE \n)\"", "warn"),
    "idiom near-miss: tab-indented terminator without <<-": ("git commit -m \"$(cat <<'E'\npkill -f foo\n\tE\n)\"", "warn"),
    "idiom near-miss: more text inside the $( )": ("x=\"$(cat <<'E'\npkill -f foo\nE\necho y)\"", "warn"),
    "idiom near-miss: text after the delimiter word": ("x=\"$(cat <<'E' >&2\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: a bash -c payload": ("bash -c \"$(cat <<'E'\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: an eval payload": ("eval \"$(cat <<'E'\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: the command word itself": ("\"$(cat <<'E'\npkill -f foo\nE\n)\"", "warn"),
    "idiom near-miss: printed into a shell": ("echo \"$(cat <<'E'\npkill -f foo\nE\n)\" | bash", "warn"),
    "idiom near-miss: a heredoc already pending": ("cat <<A >f; x=\"$(cat <<'E'\npkill -f foo\nE\n)\"\nA", "warn"),
    # --- gate r3, cases4 (the gate's inputs, verbatim; H1-H5)
    'r3: bash-2>&1-heredoc': ("bash 2>&1 <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: bash-&>-heredoc': ("bash &>/dev/null <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: pipe-continued-line': ("cat <<'EOF' |\npkill -f foo\nEOF\nbash", 'warn'),
    'r3: source-stdin': ("source /dev/stdin <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: dot-stdin': (". /dev/stdin <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: bash-procsub-heredoc': ("bash <(cat <<'EOF'\npkill -f foo\nEOF\n)", 'warn'),
    'r3: source-procsub-heredoc': ("source <(cat <<'EOF'\npkill -f foo\nEOF\n)", 'warn'),
    'r3: idiom-assign-eval': ('x="$(cat <<\'EOF\'\npkill -f foo\nEOF\n)"; eval "$x"', 'warn'),
    'r3: idiom-assign-bashc': ('x="$(cat <<\'EOF\'\npkill -f foo\nEOF\n)"\nbash -c "$x"', 'warn'),
    'r3: idiom-assign-unquoted-run': ('cmd="$(cat <<\'EOF\'\npkill -f foo\nEOF\n)"\n$cmd', 'warn'),
    'r3: idiom-then-pkill': ('git commit -m "$(cat <<\'EOF\'\nmsg\nEOF\n)"; pkill -f foo', 'warn'),
    'r3: idiom-then-andbash': ('git commit -m "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)" && bash', 'silent'),
    'r3: idiom-pipe-bash': ('echo "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)" | bash', 'warn'),
    'r3: idiom-pipe-sudo-sh': ('printf \'%s\' "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)" | sudo sh', 'warn'),
    'r3: idiom-delim-in-body-then-cmd': ('git commit -m "$(cat <<\'EOF\'\nmsg\nEOF\npkill -f foo\n)"', 'warn'),
    'r3: idiom-paren-quote-in-body': ('git commit -m "$(cat <<\'EOF\'\nfoo)"\nEOF\n)"; pkill -f foo', 'warn'),
    'r3: idiom-crlf': ('git commit -m "$(cat <<\'EOF\'\r\nmsg\r\nEOF\r\n)"\r\npkill -f foo', 'warn'),
    'r3: idiom-second-heredoc-same-line': ('cat <<A; git commit -m "$(cat <<\'EOF\'\nx\nEOF\n)"\npkill -f foo\nA', 'warn'),
    'r3: two-idioms': ('git commit -m "$(cat <<\'A\'\nx\nA\n)" -m "$(cat <<\'B\'\ny\nB\n)"; pkill -f foo', 'warn'),
    'r3: idiom-nested': ('git commit -m "$(cat <<\'EOF\'\n$(cat <<\'F\'\nx\nF\n)\nEOF\n)"; pkill -f foo', 'warn'),
    'r3: idiom-dash-tabs': ('git commit -m "$(cat <<-\'EOF\'\n\tmsg\n\tEOF\n)"; pkill -f foo', 'warn'),
    'r3: idiom-bashc': ('bash -c "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)"', 'warn'),
    'r3: idiom-cmdpos': ('"$(cat <<\'EOF\'\npkill\nEOF\n)" -f foo', 'warn'),
    'r3: idiom-env-cmd': ('env "$(cat <<\'EOF\'\npkill\nEOF\n)" -f foo', 'warn'),
    'r3: idiom-ssh': ('ssh h "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)"', 'warn'),
    'r3: idiom-tmux': ('tmux send-keys "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)" Enter', 'warn'),
    'r3: idiom-redirect-run': ('echo "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)" > /tmp/s.sh && bash /tmp/s.sh', 'warn'),
    'r3: heredoc-file-then-run': ("cat > /tmp/s.sh <<'EOF'\npkill -f foo\nEOF\nbash /tmp/s.sh", 'warn'),
    'r3: python-c': ('python3 -c \'import os; os.system("pkill -f foo")\'', 'warn'),
    'r3: flock-c': ("flock /tmp/l -c 'pkill -f foo'", 'warn'),
    'r3: fish-c': ("fish -c 'pkill -f foo'", 'warn'),
    'r3: tcsh-c': ("tcsh -c 'pkill -f foo'", 'warn'),
    'r3: ash-c': ("busybox ash -c 'pkill -f foo'", 'warn'),
    'r3: parallel': ("parallel 'pkill -f {}' ::: foo", 'warn'),
    'r3: tmux-sendkeys': ("tmux send-keys -t x 'pkill -f foo' Enter", 'warn'),
    'r3: sudo-i': ("sudo -i 'pkill -f foo'", 'warn'),
    'r3: sudo-u-quoted-cmd': ("sudo -u root 'pkill' -f foo", 'warn'),
    'r3: env-quoted-cmd': ("env 'pkill' -f foo", 'warn'),
    'r3: brace-quoted-cmd': ("{ 'pkill' -f foo; }", 'warn'),
    'r3: then-quoted-cmd': ("if true; then 'pkill' -f foo; fi", 'warn'),
    'r3: xargs-quoted': ("echo foo | xargs 'pkill' -f", 'warn'),
    'r3: nohup-quoted': ("nohup 'pkill' -f foo &", 'warn'),
    'r3: let-shift-term': ("let 'x<<=1'\npkill -f foo", 'warn'),
    'r3: oldarith': ('echo $[1<<2]\npkill -f foo\n2]', 'warn'),
    'r3: arith-unclosed-heredoc': ('(( x\ncat <<EOF\npkill -f foo\nEOF', 'warn'),
    'r3: dq-dollar-var-plain': ('echo "$HOME pkill -f foo"', 'warn'),
    'r3: sq-in-code-eval-concat': ("eval 'pk''ill -f foo'", 'none'),  # split word: raw misses it too, as on master
    'r3: heredoc-bad-delim': ('cat <<$X\npkill -f foo\n$X', 'warn'),
    'r3: herestring-python': ('python3 <<< \'import os; os.system("pkill -f foo")\'', 'warn'),
    'r3: ssh-heredoc': ("ssh host <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: bash-s-arg-heredoc': ("bash -s -- arg <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: sudo-tee-sh': ("cat <<'EOF' | sudo tee /x | sh\npkill -f foo\nEOF", 'warn'),
    'r3: dq-escaped-dollar': ('bash -c "\\$(pkill -f foo)"', 'warn'),
    'r3: comment-sq': ("ls # it's\npkill -f foo", 'warn'),
    'r3: paren-hash': ('echo $(date)#x; pkill -f foo', 'warn'),
    'r3: sq-then-dq-code': ('sh -c \'x\'"; pkill -f foo"', 'warn'),
    'r3: bash-c-concat': ('bash -c \'pk\'"ill -f foo"', 'none'),  # split word: raw misses it too, as on master
    'r3: bash-c-x-c': ("bash -x -c 'pkill -f foo'", 'warn'),
    'r3: exec-bash-heredoc': ("exec bash <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: heredoc-in-dollarparen-unquoted': ('x=$(cat <<\'EOF\'\npkill -f foo\nEOF\n); eval "$x"', 'warn'),
    'r3: heredoc-in-dollarparen-bash': ("x=$(bash <<'EOF'\npkill -f foo\nEOF\n)", 'warn'),
    'r3: subshell-bash-heredoc': ("(bash <<'EOF'\npkill -f foo\nEOF\n)", 'warn'),
    'r3: semi-bash-heredoc': ("true; bash <<'EOF'\npkill -f foo\nEOF", 'warn'),
    'r3: ssh-t-heredoc': ("ssh -t h 'bash -s' <<'EOF'\npkill -f foo\nEOF", 'warn'),
    # --- gate r3's allowlist: A1, the message argument (silent)
    'A1: -am': ("git commit -am 'pkill -f foo'", 'silent'),
    'A1: --message, double-quoted': ('git add x && git commit --message "pkill -f foo"', 'silent'),
    'A1: in a subshell': ("(git commit -m 'pkill -f foo')", 'silent'),
    'A1: a redirect after it': ("cd r; git commit -m 'pkill -f foo' 2>&1", 'silent'),
    'A1: then git push': ("git commit -m 'pkill -f foo' && git push", 'silent'),
    'A1: then || true': ("git commit -m 'pkill -f foo' || true", 'silent'),
    'A1: on a continued line': ("git commit -q \\\n  -m 'pkill -f foo'", 'silent'),
    'A1: gh pr create, title and idiom body': ('gh pr create --title \'pkill -f foo\' --body "$(cat <<\'EOF\'\npkill -f foo\nEOF\n)"', 'silent'),
    'A1: gh issue comment -b': ("gh issue comment 5 -b 'pkill -f foo'", 'silent'),
    'A1: gh pr comment --body': ('gh pr comment 12 --body "pkill -f foo"', 'silent'),
    'A1: gh issue create -t': ("gh issue create -t 'pkill -f foo' -b 'x'", 'silent'),
    # --- A1 near-misses (warn: raw)
    'A1 near-miss: sudo prefix': ("sudo git commit -m 'pkill -f foo'", 'warn'),
    'A1 near-miss: env prefix': ("env X=1 git commit -m 'pkill -f foo'", 'warn'),
    'A1 near-miss: an assignment prefix': ("A=1 git commit -m 'pkill -f foo'", 'warn'),
    'A1 near-miss: inside bash -c': ('bash -c "git commit -m \'pkill -f foo\'"', 'warn'),
    'A1 near-miss: git -C': ("git -C repo commit -m 'pkill -f foo'", 'warn'),
    'A1 near-miss: a backslashed git': ("\\git commit -m 'pkill -f foo'", 'warn'),
    'A1 near-miss: git log, not commit': ("git log -m 'pkill -f foo'", 'warn'),
    'A1 near-miss: $ in the double quote': ('git commit -m "$x pkill -f foo"', 'warn'),
    'A1 near-miss: a backslash in the double quote': ('git commit -m "a\\"b pkill -f foo"', 'warn'),
    'A1 near-miss: glued pieces': ("git commit -m 'a''pkill -f foo'", 'warn'),
    'A1 near-miss: glued -m': ("git commit -m'pkill -f foo'", 'warn'),
    'A1 near-miss: --message=': ("git commit --message='pkill -f foo'", 'warn'),
    'A1 near-miss: piped on': ("git commit -m 'pkill -f foo' | bash", 'warn'),
    'A1 near-miss: |& piped on': ("git commit -m 'pkill -f foo' |& cat", 'warn'),
    'A1 near-miss: -F - from a heredoc': ("git commit -F - <<'E'\npkill -f foo\nE", 'warn'),
    'A1 near-miss: a word glued after the idiom': ('git commit -m "$(cat <<\'E\'\npkill -f foo\nE\n)"x', 'warn'),
    'A1 near-miss: gh pr view': ("gh pr view --body 'pkill -f foo'", 'warn'),
    'A1 near-miss: gh --label': ("gh pr create --label 'pkill -f foo'", 'warn'),
    'A1 near-miss: gh repo': ("gh repo create -t 'pkill -f foo'", 'warn'),
    'A1 near-miss: git redefined as a function': ('git() { bash -c "$4"; }; git commit -m \'pkill -f foo\'', 'warn'),
    'A1 near-miss: git redefined, spaced': ('git () { eval "$4"; }; git commit -m \'pkill -f foo\'', 'warn'),
    'A1 near-miss: an alias for git': ("alias git='bash -c'\ngit commit -m 'pkill -f foo'", 'warn'),
    'A1 near-miss: function gh': ('function gh { eval "$5"; }; gh pr create -t \'pkill -f foo\'', 'warn'),
    'A1 near-miss: a substitution elsewhere': ("git commit -m 'x' $(echo y); pkill -f foo", 'warn'),
    'A1 near-miss: a real command after it': ("git commit -m 'x' && pkill -f foo", 'warn'),
    'A1 near-miss: the message is the flag value of another flag': ("git commit -C 'pkill -f foo'", 'warn'),
    # --- A2, a heredoc written to a file (silent)
    'A2: cat >': ("cat > notes.md <<'E'\npkill -f foo\nE", 'silent'),
    'A2: cat >> with a double-quoted delimiter': ('cat >> notes.md <<"E"\npkill -f foo\nE', 'silent'),
    'A2: tee with a backslash delimiter': ('tee notes.md <<\\E\npkill -f foo\nE', 'silent'),
    'A2: tee -a to a quoted name': ("tee -a 'my notes.md' <<'E'\npkill -f foo\nE", 'silent'),
    'A2: cat > a double-quoted name': ('cat >"notes.md" <<\'E\'\npkill -f foo\nE', 'silent'),
    'A2: then another command': ("cd x && cat > a.md <<'E'\npkill -f foo\nE\ngit add b.md", 'silent'),
    # --- A2 near-misses (warn: raw)
    'A2 near-miss: unquoted delimiter': ('cat > f.md <<E\npkill -f foo\nE', 'warn'),
    'A2 near-miss: the redirect after the heredoc': ("cat <<'E' > f.md\npkill -f foo\nE", 'warn'),
    'A2 near-miss: piped into sh': ("cat > f.md <<'E' | sh\npkill -f foo\nE", 'warn'),
    'A2 near-miss: tee piped into bash': ("tee f.md <<'E' | bash\npkill -f foo\nE", 'warn'),
    'A2 near-miss: ; after the delimiter': ("cat > f.md <<'E'; true\npkill -f foo\nE", 'warn'),
    'A2 near-miss: two files': ("tee -a f.md g.md <<'E'\npkill -f foo\nE", 'warn'),
    'A2 near-miss: no terminator': ("cat > f.md <<'E'\npkill -f foo\n", 'warn'),
    'A2 near-miss: a trailing space on the terminator': ("cat > f.md <<'E'\npkill -f foo\nE ", 'warn'),
    'A2 near-miss: <<-': ("cat > f.md <<-'E'\n\tpkill -f foo\n\tE", 'warn'),
    'A2 near-miss: sudo cat': ("sudo cat > f.md <<'E'\npkill -f foo\nE", 'warn'),
    'A2 near-miss: $ in the file name': ("cat > $f <<'E'\npkill -f foo\nE", 'warn'),
    'A2 near-miss: cat>f, no blank': ("cat>f.md <<'E'\npkill -f foo\nE", 'warn'),
    'A2 near-miss: a comment after the delimiter': ("cat > f.md <<'E' # x\npkill -f foo\nE", 'warn'),
    'A2 near-miss: the file is run after': ("cat > /tmp/s.sh <<'E'\npkill -f foo\nE\nbash /tmp/s.sh", 'warn'),
    'A2 near-miss: the file is run by base name': ("cat > /tmp/s.sh <<'E'\npkill -f foo\nE\ncd /tmp && sh s.sh", 'warn'),
    'A2 near-miss: the file is sourced': ('cat > f.sh <<\'E\'\ngit() { bash -c "$4"; }\nE\nsource f.sh; git commit -m \'pkill -f foo\'', 'warn'),
    'A2 near-miss: inside bash -c': ('bash -c "cat > f <<\'E\'\npkill -f foo\nE"', 'warn'),
    'A2: a real command after the body': ("cat > f.md <<'E'\nx\nE\npkill -f foo", 'warn'),
    # --- allowlist controls (mutation-driven)
    'A1: newline-separated segments': ("git add x\ngit commit -m 'pkill -f foo'", 'silent'),
    'A1: a line continuation between git and commit': ("git \\\n  commit -m 'pkill -f foo'", 'silent'),
    'A1: &> before -m': ("git commit &>/dev/null -m 'pkill -f foo'", 'silent'),
    'A1: 2>&1 before -m': ("git commit 2>&1 -m 'pkill -f foo'", 'silent'),
    'A1: a pipe in a later segment': ("git commit -m 'pkill -f foo'; ls | wc -l", 'silent'),
    'A1 near-miss: gh with a quoted noun': ("gh 'pr' create -t 'pkill -f foo'", 'warn'),
    'A1 near-miss: the word after the message': ("git commit -m x 'pkill -f foo'", 'warn'),
    'A1 near-miss: a piece glued after the message': ("git commit -m 'pkill -f foo''a'", 'warn'),
    'A1 near-miss: a word glued after a double quote': ('git commit -m "pkill -f foo"x', 'warn'),
    'idiom near-miss at -m: more text inside': ('git commit -m "$(cat <<\'E\'\npkill -f foo\nE\necho y)"', 'warn'),
    'idiom near-miss at -m: a mismatched delimiter quote': ('git commit -m "$(cat <<\'E"\npkill -f foo\nE\n)"', 'warn'),
    'idiom near-miss at -m: text after the delimiter word': ('git commit -m "$(cat <<\'E\' >&2\npkill -f foo\nE\n)"', 'warn'),
    'idiom near-miss at -m: tac, not cat': ('git commit -m "$(tac <<\'E\'\npkill -f foo\nE\n)"', 'warn'),
    'A2 near-miss: two heredocs on the A2 line': ("cat <<'X' | sh; cat > f.md <<'E'\npkill -f foo\nX\ny\nE", 'warn'),
    'A1 near-miss: a second git command after a commit': ("git commit -m 'x'; git log -m 'pkill -f foo'", 'warn'),
    'A2 near-miss: a continued delimiter line into a shell': ("tee f.md <<'E' \\\n| sh\npkill -f foo\nE", 'warn'),
}


@pytest.fixture(scope="module")
def corpus_hooks(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("corpus")
    return _guard(tmp, CORPUS_REGEX), _guard(tmp, CORPUS_REGEX, mode="deny")


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_the_corpus(corpus_hooks, name):
    """Everything outside an A1/A2 hidden span is matched as the raw text;
    a mention only inside one is silent; the view never hides what the raw
    matcher sees unless the case is such a mention."""
    warn_hook, raw_hook = corpus_hooks
    command, expected = CORPUS[name]
    raw = _run(raw_hook, command).returncode == 2  # the deny twin matches the raw text
    viewed = _warns(warn_hook, command)
    if expected == "warn":
        assert raw, f"control: the raw matcher must see {command!r}"
        assert viewed, command
    elif expected == "silent":
        assert raw, f"control: the raw matcher must see {command!r}"
        assert not viewed, command
    elif expected == "none":
        assert not raw and not viewed, command
    if expected != "silent" and expected != "syntax":
        assert viewed or not raw, f"the view hid what the raw text shows: {command!r}"


def test_the_corpus_controls(corpus_hooks):
    warn_hook, raw_hook = corpus_hooks
    assert _warns(warn_hook, "pkill -f foo") and not _warns(warn_hook, "ls -la")
    assert _run(raw_hook, "pkill -f foo").returncode == 2
    assert _run(raw_hook, "ls -la").returncode == 0


def test_the_lessons_own_examples_still_replay_clean(tmp_path):
    path = tmp_path / "c71f0a40.sh"
    path.write_text(script_for_hook(RID, TRIGGER, HEREDOC_BLOCK), encoding="utf-8")
    path.chmod(0o755)
    assert replay_examples(path, HEREDOC_EXAMPLES, HEREDOC_BLOCK, RID) == []
    # and the replay still sees a broken example (the replay is live)
    broken = {**HEREDOC_EXAMPLES, "allow": HEREDOC_EXAMPLES["warn"][:1]}
    assert len(replay_examples(path, broken, HEREDOC_BLOCK, RID)) == 1


# ------------------------------------------------- what the view writes


def _viewed(command: str) -> str:
    proc = _view(command)
    assert proc.returncode == 0 and proc.stderr == "", proc.stderr
    return proc.stdout.rstrip("\n")


@pytest.mark.parametrize("command,view", [
    # A1: the message argument
    ('git commit -m "x y" && ls', 'git commit -m "" && ls'),
    ("git commit -am 'x' -m \"y\"", "git commit -am '' -m \"\""),
    ("gh pr create --title 'a' --body 'b' --label c", "gh pr create --title '' --body '' --label c"),
    ("git commit -m \"$(cat <<'EOF'\nbody\nEOF\n)\"; ls", "git commit -m \"$(cat <<'EOF'\nEOF\n)\"; ls"),
    # A2: the body
    ("cat > f.md <<'EOF'\nbody\nEOF\nls", "cat > f.md <<'EOF'\nEOF\nls"),
    ("tee -a 'a b' <<\\E\nbody\nE", "tee -a 'a b' <<\\E\nE"),
    # everything else, raw
    ("echo 'a' \"c\"", "echo 'a' \"c\""),
    ("python3 -c 'x'", "python3 -c 'x'"),
    ("cat <<'EOF'\nbody\nEOF\nls", "cat <<'EOF'\nbody\nEOF\nls"),
    ("ls # a 'comment'", "ls # a 'comment'"),
    ("git commit -m 'x' $(ls)", "git commit -m 'x' $(ls)"),
    ("git commit -m 'x'; echo `ls`", "git commit -m 'x'; echo `ls`"),
    ("git commit -m 'x'; echo $'y'", "git commit -m 'x'; echo $'y'"),
    ("git commit -m 'x'; (( n++ ))", "git commit -m 'x'; (( n++ ))"),
    ("git commit -m 'x'; cat <<< y", "git commit -m 'x'; cat <<< y"),
    ("git commit -m 'x'; diff <(ls) f", "git commit -m 'x'; diff <(ls) f"),
    ("git commit -m 'x'; echo 'unclosed", "git commit -m 'x'; echo 'unclosed"),
    ("git commit -m 'x'; echo \"${y}\"", "git commit -m 'x'; echo \"${y}\""),
    # parts the scan follows, kept as written around a hidden span
    ("git commit -m 'x' 2>&1 >/dev/null &>log", "git commit -m '' 2>&1 >/dev/null &>log"),
    ("echo \"$HOME\" a\\ b # c 'd'\ngit commit -m 'x'", "echo \"$HOME\" a\\ b # c 'd'\ngit commit -m ''"),
    ("ls # don't\ngit commit -m 'x'", "ls # don't\ngit commit -m ''"),
    ("echo it\\'s; git commit -m 'x'", "echo it\\'s; git commit -m ''"),
    ("echo \"`ls`\"; git commit -m 'x'", "echo \"`ls`\"; git commit -m 'x'"),
    ("echo \"$(ls)\"; git commit -m 'x'", "echo \"$(ls)\"; git commit -m 'x'"),
])
def test_the_view_hides_only_what_it_understands(command, view):
    assert _viewed(command) == view


# ----------------------------------------------------- what stays the same


def test_a_deny_guard_still_matches_the_raw_command(tmp_path):
    """A deny guard keeps matching the raw text: quoting must never get a
    command past a guard (``"sudo" npm i -g``, ``python -c "os.system(...)"``,
    a heredoc into an interpreter), so its false positives stay too."""
    deny = _guard(tmp_path, PGREP_REGEX, mode="deny")
    for command in ('git commit -m "never pkill -f a pattern"',
                    "python3 - <<'EOF'\nimport os; os.system('x; pkill -f y')\nEOF",
                    "bash -c 'x; pkill -f y'"):
        assert _run(deny, command).returncode == 2, command
    assert _run(deny, "ls").returncode == 0  # control
    assert "awk" not in generate_script(RID, TRIGGER, ["Bash"], PGREP_REGEX, "stop")


def test_a_file_path_hook_never_runs_the_view(tmp_path):
    guard = _guard(tmp_path, r"'x'", tools=("Edit", "Write"))
    assert "awk" not in guard.read_text()
    edit = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "/a/'x'/b"}})
    proc = subprocess.run([str(guard)], input=edit, capture_output=True, text=True)
    assert proc.stdout != ""
    # a mixed hook views the Bash command only
    mixed = _guard(tmp_path, r"'x'", tools=("Bash", "Edit"))
    assert subprocess.run([str(mixed)], input=edit, capture_output=True,
                          text=True).stdout != ""
    assert not _warns(mixed, "git commit -m 'x'")
    assert _warns(mixed, "echo 'x'")  # outside the allowlist: raw


def test_the_warn_script_carries_its_regex_once_and_is_deterministic():
    a = generate_script(RID, TRIGGER, ["Bash"], "placeholder", "m", mode="warn")
    assert a.count("'placeholder'") == 1
    assert a == generate_script(RID, TRIGGER, ["Bash"], "placeholder", "m", mode="warn")


# ------------------------------------------------------- it fails open

QUOTED = f'git commit -m "docs: {BAD}"'  # silent through the view, loud raw


def _bin_dir(tmp_path: Path, name: str, *, omit: tuple[str, ...] = (),
             fake_awk: str | None = None) -> dict:
    """A PATH holding exactly the binaries a generated warn script invokes
    (bash, cat, jq, grep, printf, awk) minus *omit*; *fake_awk* replaces
    awk with a script body."""
    bindir = tmp_path / name
    bindir.mkdir()
    for tool in ("bash", "cat", "jq", "grep", "printf", "awk", "env"):
        if tool in omit:
            continue
        found = shutil.which(tool)
        assert found, f"{tool} not on PATH"
        (bindir / tool).symlink_to(found)
    if fake_awk is not None:
        fake = bindir / "awk"
        fake.unlink()
        fake.write_text("#!" + shutil.which("bash") + "\n" + fake_awk + "\n")
        fake.chmod(0o755)
    return {**os.environ, "PATH": str(bindir)}


def test_without_awk_the_hook_matches_the_raw_text(tmp_path):
    guard = _guard(tmp_path)
    full = _bin_dir(tmp_path, "full")
    assert not _warns(guard, QUOTED, full)  # control
    env = _bin_dir(tmp_path, "no-awk", omit=("awk",))
    assert _warns(guard, QUOTED, env)
    assert _warns(guard, "python3 - <<'EOF' </dev/null\nprint(1)\nEOF", env)
    assert not _warns(guard, "ls", env)


@pytest.mark.parametrize("body", ["exit 2", "cat >/dev/null; echo garbage >&2; exit 1",
                                  "kill -SEGV $$"])
def test_a_failing_awk_falls_back_to_the_raw_text_and_never_blocks(tmp_path, body):
    guard = _guard(tmp_path)
    env = _bin_dir(tmp_path, "broken-awk", fake_awk=body)
    assert _warns(guard, QUOTED, env)
    assert not _warns(guard, "ls", env)


def test_an_unbalanced_quote_shows_the_rest_as_written(tmp_path):
    """bash itself refuses an unbalanced quote, so nothing runs; the view
    is the raw command, so the hook warns as before S-133."""
    guard = _guard(tmp_path)
    for command in (f'git commit -m "{BAD}', f"git commit -m '{BAD}", f"echo $'{BAD}",
                    f'git commit -m "$(true {BAD}"', f"cat > f <<'E\n{BAD}"):
        assert _viewed(command) == command, command  # shown as written
        assert _warns(guard, command), command
    assert not _warns(guard, f'git commit -m "{BAD}"')  # control: balanced, silent


def test_a_command_over_the_size_bound_is_matched_raw(tmp_path):
    guard = _guard(tmp_path)
    filler = "x" * 80 + "\n"
    small = f"cat > f <<'EOF'\n{BAD}\n" + filler * 10 + "EOF"
    assert not _warns(guard, small)  # control: under the bound, the view runs
    big = f"cat > f <<'EOF'\n{BAD}\n" + filler * (COMMAND_VIEW_MAX_BYTES // len(filler) + 1) + "EOF"
    assert len(big.encode()) > COMMAND_VIEW_MAX_BYTES
    assert _warns(guard, big)


def _at_cap(unit: str, prefix: str = "") -> str:
    return prefix + unit * ((COMMAND_VIEW_MAX_BYTES - len(prefix) - 8) // len(unit))


#: Gate r2 G3 and r1 F9 (inputs that made earlier views quadratic) and the
#: allowlist's own repeated shapes. The view is one linear pass: each stays
#: well inside the bound below, at the size cap.
AT_CAP = {
    "unclosed $((": _at_cap("$(( ", "echo "),
    "unclosed ((": _at_cap("(("),
    "quoted words": _at_cap("'a' "),
    "double-quoted words": _at_cap('"a" '),
    "commit messages": _at_cap("git commit -m 'a'; "),
    "commit messages on one segment": _at_cap("-m 'a' ", "git commit "),
    "commit idioms": _at_cap("git commit -m \"$(cat <<'E'\ny\nE\n)\"; "),
    "an idiom that never ends": _at_cap("y\n", "git commit -m \"$(cat <<'E'\n"),
    "idiom openers": _at_cap("git commit -m \"$(cat <<'E'\n"),
    "A2 bodies": _at_cap("cat > f <<'E'\nx\nE\n"),
    "A2 bodies, distinct names": "".join(
        f"cat > f{i:06d} <<'E'\nx\nE\n" for i in range(COMMAND_VIEW_MAX_BYTES // 24)),
    "A2 openers on one line": _at_cap("cat > f ", "x; "),
    "A2 openers, a delimiter at the end": _at_cap("cat > f ", "x; ")[:-20] + " <<'E'",
    "segments starting with c": _at_cap("c;"),
    "tee words": _at_cap("tee "),
    "heredoc operators on one line": _at_cap("<<A "),
    "comments with apostrophes": _at_cap("# don't\n"),
    "open parentheses": _at_cap("("),
}


@pytest.mark.parametrize("name", sorted(AT_CAP))
def test_the_view_is_linear_at_the_size_cap(name):
    command = AT_CAP[name]
    assert len(command) <= COMMAND_VIEW_MAX_BYTES
    start = time.monotonic()
    proc = _view(command)
    took = time.monotonic() - start
    assert proc.returncode == 0 and proc.stderr == ""
    assert took < 5.0, f"{name}: {took:.1f}s"


def test_a_hook_run_at_the_cap_is_bounded(tmp_path):
    guard = _guard(tmp_path, PGREP_REGEX)
    start = time.monotonic()
    _warns(guard, AT_CAP["commit messages"])
    assert time.monotonic() - start < 10.0


def test_random_shell_text_never_breaks_the_hook(tmp_path):
    """Fuzz: arbitrary mixes of quotes, escapes, heredoc operators and
    separators either warn with the exact line or stay silent -- never
    another exit code, never stderr -- and the awk view always ends."""
    guard = _guard(tmp_path)
    atoms = ["'", '"', "\\", "$'", "$(", "$((", "((", ")", "`", "<<", "<<-", "<<<", "EOF",
             "\n", "\t", " ", "#", ";", "&", "|", "bash -c ", "eval ", "trap ", BAD, "x",
             "</dev/null", "git commit -m ", "gh pr create -t ", "cat > f ", "tee f ",
             "<<'EOF'", "\"$(cat <<'EOF'\n", ")\"", "2>&1"]
    rng = random.Random(133)
    for _ in range(60):
        command = "".join(rng.choice(atoms) for _ in range(rng.randint(1, 30)))
        view = _view(command)
        assert view.returncode == 0 and view.stderr == "", (command, view.stderr)
        _warns(guard, command)  # asserts exit 0, no stderr, exact line or nothing


@pytest.mark.skipif(shutil.which("gawk") is None, reason="gawk not installed")
def test_the_view_program_is_posix_awk():
    """No gawk extension: the program runs the same under ``gawk --posix``."""
    for command, _ in CORPUS.values():
        plain = _view(command)
        posix = _view(command, ("gawk", "--posix"))
        assert (posix.returncode, posix.stdout, posix.stderr) == (
            plain.returncode, plain.stdout, ""), command
