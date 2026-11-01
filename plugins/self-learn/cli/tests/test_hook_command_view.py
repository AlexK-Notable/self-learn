"""S-133: a warning hook on Bash matches the command's words, not the text
inside the quotes and heredoc bodies it fully understands.

The live defect (notice ntc-71c2eb83, lesson lrn-042c8179): the heredoc
warning hook of lrn-c71f0a40 grepped the raw command, so a commit message
or a heredoc that only MENTIONED ``python3 - <<EOF </dev/null`` fired the
warning. Gate r2's rule (the orchestrator's): the view hides only spans it
fully understands -- a single-quoted string, a double-quoted string with no
``$``, backtick or escaped quote, a heredoc body whose terminator line is
found (an unquoted one only without ``$(`` or a backtick) -- and shows
everything else as written. The worst case is an extra warning, never a
missed one.

Every test runs the GENERATED script (or its embedded awk program) against
sample commands -- the suite's mock-free convention. The corpus below is
the builder's own cases plus every input gate r1 and gate r2 probed with.
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

#: name -> (command, expectation). ``warn``: a plain invocation (or text the
#: conservative rule shows) must warn. ``silent``: a mention inside a span
#: the rule fully understands must not warn, and the raw matcher must (the
#: control). ``none``: nothing to warn on, raw or viewed. ``syntax``: bash
#: rejects the input, so nothing runs; no claim.
CORPUS: dict[str, tuple[str, str]] = {
    # --- the builder's own: understood mentions
    "own: double-quoted commit message": (f'git commit -m "docs: {BAD}"', "silent"),
    "own: single-quoted argument": (f"echo '{BAD}'", "silent"),
    "own: heredoc body, quoted delimiter": (f"cat > notes.md <<'MD'\nnever run {BAD}\nMD", "silent"),
    "own: heredoc body, bare delimiter": (f"cat > notes.md <<MD\nnever run {BAD}\nMD", "silent"),
    "own: heredoc body with an apostrophe": (f"cat <<EOF\ndon't {BAD}\nEOF", "silent"),
    "own: two heredocs on one line": (f"cat <<A <<B\nx\nA\n{BAD}\nB", "silent"),
    "own: tab-stripped heredoc": (f"cat <<-EOF\n\t{BAD}\n\tEOF", "silent"),
    "own: python -c double-quoted, no $": (f"python3 -c \"print('{BAD}')\"", "silent"),
    "own: pkill in a commit message": ('git commit -m "never pkill -f a pattern"', "silent"),
    "own: pgrep in a quoted heredoc": ("cat <<'EOF' > NOTES.md\npgrep -f x matches itself\nEOF", "silent"),
    "own: $( ) in a quoted heredoc body": ("cat <<'EOF'\nrun $(pkill -f foo) danger\nEOF", "silent"),
    "own: quoted heredoc inside $( )": ("x=$(cat <<'EOF'\npkill -f foo\nEOF\n)", "silent"),
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
    "own: sudo sh -c": ('sudo sh -c "pgrep -f worker"', "warn"),
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
    "r1: python-c": ('python3 -c \'import os; os.system("pkill -f foo")\'', "silent"),
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
    "r1 fold: here-string to a shell, then quoted text": ("bash <<< x; echo 'pkill -f foo'", "silent"),
    "r1 fold: quoted here-string, then quoted text": ("bash <<< 'true'; echo 'pkill -f foo'", "silent"),
    "r1 fold: a trap's signal list": ("trap 'echo hi' 'pkill -f foo'", "silent"),
    "r1 fold: arithmetic leaves later quotes alone": ('x=$((1<<2)); echo "pkill -f foo"', "silent"),
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
    "r2: herestring-sh-unquoted-then-quote": ("bash <<< x 'pkill -f foo'", "silent"),
    "r2: herestring-forced-leak": ('bash <<< "$x"; git commit -m "pkill -f foo"', "silent"),
    "r2: herestring-sh-then-squote-later": ("sh <<< 'true' && echo 'pkill -f foo'", "silent"),
    "r2: herestring-sudo-bash": ("sudo bash <<< 'pkill -f foo'", "warn"),
    "r2: herestring-python": ('python3 <<< \'import os; os.system("pkill -f foo")\'', "warn"),
    "r2: trap-dash": ("trap -- 'pkill -f foo' EXIT", "warn"),
    "r2: trap-p": ("trap -p 'pkill -f foo'", "silent"),
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
    "r2 fold: a # after a substitution's ) is a word": ("echo $(date)#x 'pkill -f foo'", "silent"),
    "r2 fold: the here-string flag ends with its word":
        ("bash <<< 'a'; git commit -m 'pkill -f foo'", "silent"),
    "r2 fold: an inner quote in $( ) in double quotes":
        ('echo "$(echo "a" \'pkill -f foo\')"', "warn"),
    "r2 fold: an inner quote in backticks in double quotes":
        ('echo "`echo "a" \'pkill -f foo\'`"', "warn"),
    "r2 fold: a heredoc delimiter holding $ keeps its body":
        ("cat <<$X >f\npkill -f foo\n$X\nls", "warn"),
    "r2 fold: a heredoc after closed arithmetic":
        ("echo $((1<<2)); cat <<'E' >f\npkill -f foo\nE", "silent"),
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
}


@pytest.fixture(scope="module")
def corpus_hooks(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("corpus")
    return _guard(tmp, CORPUS_REGEX), _guard(tmp, CORPUS_REGEX, mode="deny")


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_the_corpus(corpus_hooks, name):
    """Every plain invocation warns; every mention inside a span the rule
    understands does not; and the view never hides what the raw matcher
    sees unless the case is such a mention."""
    warn_hook, raw_hook = corpus_hooks
    command, expected = CORPUS[name]
    raw = _run(raw_hook, command).returncode == 2  # the deny twin matches the raw text
    viewed = _warns(warn_hook, command)
    if expected == "warn":
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
    ('git commit -m "x y" && ls', 'git commit -m "" && ls'),
    ("echo 'a' \"c\"", "echo '' \"\""),
    ("cat <<'EOF'\nbody\nEOF\nls", "cat <<'EOF'\nEOF\nls"),
    ("cat <<EOF\nbody\nEOF\nls", "cat <<EOF\nEOF\nls"),
    ("cat <<-EOF\n\tbody\n\tEOF\nls", "cat <<-EOF\n\tEOF\nls"),
    ("python3 -c 'x'", "python3 -c ''"),
    # shown as written
    ("echo $'b'", "echo $'b'"),
    ('echo "$HOME" "a\\"b"', 'echo "$HOME" "a\\"b"'),
    ("ls # a 'comment'", "ls # a 'comment'"),
    ("echo a#b 'c'", "echo a#b ''"),
    ("echo \\'x 'y'", "echo \\'x ''"),
    ("x=$((1 << 2)) && (( n <<= 1 ))\nls", "x=$((1 << 2)) && (( n <<= 1 ))\nls"),
    ("cat <<EOF\n$(date)\nEOF", "cat <<EOF\n$(date)\nEOF"),
    ("cat <<EOF\nnever closed 'x'", "cat <<EOF\nnever closed 'x'"),
    # payloads, without their quote marks
    ("bash -c 'echo \"hi\"; ls'", 'bash -c echo "hi"; ls'),
    ('sh -c "echo hi; ls"', "sh -c echo hi; ls"),
    ("eval 'a' \"b\"", "eval a b"),
    ("'pkill' -f x", "pkill -f x"),
    ("sudo 'pkill' -f x", "sudo pkill -f x"),
    ("cat <<< 'a b'", "cat <<< a b"),
    ("trap 'a' EXIT", "trap a EXIT"),
    # the rest, as written, from the first construct the scan cannot follow
    ('echo "a $(ls "x") b" \'y\'', 'echo "a $(ls "x") b" \'y\''),
    ('echo "${x:-"a"}" \'y\'', 'echo "${x:-"a"}" \'y\''),
    ("echo 'unclosed \"x\"", "echo 'unclosed \"x\""),
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
    assert not _warns(mixed, "echo 'x'")


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
    shows everything from the quote on, so the hook warns as before S-133."""
    guard = _guard(tmp_path)
    for command in (f'echo "{BAD}', f"echo '{BAD}", f"echo $'{BAD}",
                    f'echo "$(true {BAD}"', f"cat <<'E\n{BAD}"):
        assert _viewed(command) == command, command  # shown as written
        assert _warns(guard, command), command
    assert not _warns(guard, f'echo "{BAD}"')  # control: balanced, silent


def test_a_command_over_the_size_bound_is_matched_raw(tmp_path):
    guard = _guard(tmp_path)
    filler = "x" * 80 + "\n"
    small = f"cat <<'EOF' > f\n{BAD}\n" + filler * 10 + "EOF"
    assert not _warns(guard, small)  # control: under the bound, the view runs
    big = f"cat <<'EOF' > f\n{BAD}\n" + filler * (COMMAND_VIEW_MAX_BYTES // len(filler) + 1) + "EOF"
    assert len(big.encode()) > COMMAND_VIEW_MAX_BYTES
    assert _warns(guard, big)


def _at_cap(unit: str, prefix: str = "") -> str:
    return prefix + unit * ((COMMAND_VIEW_MAX_BYTES - len(prefix) - 8) // len(unit))


#: Gate r2 G3 and r1 F9: inputs that made the old view quadratic (46 s and
#: >120 s at the cap). The view is one linear pass: each stays well inside
#: the bound below, at the size cap.
AT_CAP = {
    "unclosed $((": _at_cap("$(( ", "echo "),
    "unclosed ((": _at_cap("(("),
    "quoted words": _at_cap("'a' "),
    "double-quoted words": _at_cap('"a" '),
    "eval arguments": _at_cap("'a' ", "eval "),
    "bash -c payloads": _at_cap("bash -c 'a'; "),
    "heredoc operators on one line": _at_cap("<<A "),
    "heredocs": _at_cap("cat <<A\nx\nA\n"),
    "here-strings": _at_cap("bash <<< 'a'; "),
    "comments with apostrophes": _at_cap("# don't\n"),
    "open parentheses": _at_cap("("),
    "commit idioms": _at_cap("x \"$(cat <<'E'\ny\nE\n)\" "),
    "commit idioms on one line each": _at_cap("x \"$(cat <<'E'\ny\nE\n)\"\n"),
    "an idiom that never ends": _at_cap("y\n", "x \"$(cat <<'E'\n"),
    "idiom openers": _at_cap("x \"$(cat <<'E'\n"),
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
    _warns(guard, AT_CAP["unclosed $(("])
    assert time.monotonic() - start < 10.0


def test_random_shell_text_never_breaks_the_hook(tmp_path):
    """Fuzz: arbitrary mixes of quotes, escapes, heredoc operators and
    separators either warn with the exact line or stay silent -- never
    another exit code, never stderr -- and the awk view always ends."""
    guard = _guard(tmp_path)
    atoms = ["'", '"', "\\", "$'", "$(", "$((", "((", ")", "`", "<<", "<<-", "<<<", "EOF",
             "\n", "\t", " ", "#", ";", "&", "|", "bash -c ", "eval ", "trap ", BAD, "x",
             "</dev/null"]
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
