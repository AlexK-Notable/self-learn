"""S-NEXT-hookmatch: a warning hook on Bash matches the command's words, not the text
inside quotes, comments or heredoc bodies.

The live defect (notice ntc-71c2eb83, lesson lrn-042c8179): the heredoc
warning hook of lrn-c71f0a40 grepped the raw command, so a commit message
or a heredoc that only MENTIONED ``python3 - <<EOF </dev/null`` fired the
warning. Every test here runs the GENERATED script (or its embedded awk
program) against sample commands -- the suite's mock-free convention.
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
#: A second live shape (lrn-19f82fc5's family): a word-anchored regex.
PGREP_REGEX = r"(^|[;&|(`[:space:]])p(kill|grep)([[:space:]]+-[^[:space:]]+)*[[:space:]]+(-[a-zA-Z]*f[a-zA-Z]*|--full)([[:space:]]|$)"

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
                          env=env, timeout=30)


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
                          timeout=30)


# ------------------------------------------------- the reproduction (red first)

#: Text that only MENTIONS the shape: none of these runs a heredoc into an
#: interpreter with stdin from /dev/null. Before S-NEXT-hookmatch every one warned.
SILENT = {
    "double-quoted commit message": f'git commit -m "docs: {BAD}"',
    "single-quoted argument": f"echo '{BAD}'",
    "heredoc body (quoted delimiter)": f"cat > notes.md <<'MD'\nnever run {BAD}\nMD",
    "heredoc body (bare delimiter)": f"cat > notes.md <<MD\nnever run {BAD}\nMD",
    "heredoc body with an apostrophe": f"cat <<EOF\ndon't {BAD}\nEOF",
    "the Claude Code commit idiom": f"git commit -m \"$(cat <<'EOF'\nfix: {BAD}\nEOF\n)\"",
    "escaped quotes inside double quotes": f'echo "he said \\"{BAD}\\" twice"',
    "ANSI-C quoting with an escaped quote": f"printf $'it\\'s {BAD}'",
    "a comment": f"ls  # {BAD}",
    "two heredocs on one line": f"cat <<A <<B\nx\nA\n{BAD}\nB",
    "tab-stripped heredoc": f"cat <<-EOF\n\t{BAD}\n\tEOF",
    "unterminated heredoc": f"cat <<EOF\n{BAD}",
    "data nested in a shell payload": f"bash -c \"echo '{BAD}'\"",
    "python -c is not a shell payload": f"python3 -c \"print('{BAD}')\"",
}

#: Real invocations: each still warns (the positive controls).
WARNS = {
    "the lesson's own example": "python3 - <<'EOF' </dev/null\nprint(1)\nEOF",
    "after an escaped quote outside quotes": f'echo \\"x\\"; {BAD}\nEOF',
    "between escaped apostrophes": f"echo \\' {BAD} \\'\nEOF",
    "bash -c single-quoted payload": f"bash -c '{BAD}\nprint(1)\nEOF'",
    "sh -c double-quoted payload": "sh -c \"uv run python - <<PY 2>&1 </dev/null\nPY\"",
    "bash -lc after other options": f"sudo bash -o pipefail -lc '{BAD}\nEOF'",
    "eval payload": f'eval "{BAD}"',
    "ssh remote command": f"ssh host '{BAD}\nEOF'",
    "a heredoc fed to a shell": f"bash <<'SH'\n{BAD}\nprint(1)\nEOF\nSH",
    "a here-string keeps its quote marks": "python3 <<<'print(1)' </dev/null",
    "a real line after a tab-stripped heredoc": f"cat <<-EOF\n\tx\n\tEOF\n{BAD}\nEOF",
    "after a heredoc whose body has quotes": f"cat <<EOF\nit's \"x\nEOF\n{BAD}\nEOF",
}


@pytest.mark.parametrize("name", sorted(SILENT))
def test_text_that_only_mentions_the_shape_does_not_warn(tmp_path, name):
    guard = _guard(tmp_path)
    assert _warns(guard, BAD + "\nEOF")  # positive control: the hook fires at all
    assert not _warns(guard, SILENT[name]), SILENT[name]


@pytest.mark.parametrize("name", sorted(WARNS))
def test_a_real_invocation_still_warns(tmp_path, name):
    guard = _guard(tmp_path)
    assert not _warns(guard, "ls -la")  # negative control
    assert _warns(guard, WARNS[name]), WARNS[name]


def test_the_lessons_own_examples_still_replay_clean(tmp_path):
    path = tmp_path / "c71f0a40.sh"
    path.write_text(script_for_hook(RID, TRIGGER, HEREDOC_BLOCK), encoding="utf-8")
    path.chmod(0o755)
    assert replay_examples(path, HEREDOC_EXAMPLES, HEREDOC_BLOCK, RID) == []
    # and the replay still sees a broken example (the replay is live)
    broken = {**HEREDOC_EXAMPLES, "allow": HEREDOC_EXAMPLES["warn"][:1]}
    assert len(replay_examples(path, broken, HEREDOC_BLOCK, RID)) == 1


def test_a_word_anchored_regex_sees_command_words_and_not_quoted_text(tmp_path):
    guard = _guard(tmp_path, PGREP_REGEX)
    assert _warns(guard, "pkill -f 'node server'")  # the argument may be quoted
    assert _warns(guard, 'echo "pids: $(pgrep -f worker)"')  # $( ) inside "..." runs
    assert _warns(guard, "echo `pgrep -f worker`")
    assert _warns(guard, 'echo "`pgrep -f worker`"')
    # a shell payload is written without its quote marks, so the word
    # boundary the regex anchors on is there (the raw text has a quote)
    assert _warns(guard, "bash -c 'pkill -f node'")
    assert _warns(guard, 'sudo sh -c "pgrep -f worker"')
    assert _warns(guard, "eval $'pkill -f x'")
    assert not _warns(guard, 'git commit -m "never pkill -f a pattern"')
    assert not _warns(guard, "cat <<'EOF' > NOTES.md\npgrep -f x matches itself\nEOF")


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
    assert not _warns(guard, SILENT["double-quoted commit message"], full)  # control
    env = _bin_dir(tmp_path, "no-awk", omit=("awk",))
    assert _warns(guard, SILENT["double-quoted commit message"], env)
    assert _warns(guard, WARNS["the lesson's own example"], env)
    assert not _warns(guard, "ls", env)


@pytest.mark.parametrize("body", ["exit 2", "cat >/dev/null; echo garbage >&2; exit 1",
                                  "kill -SEGV $$"])
def test_a_failing_awk_falls_back_to_the_raw_text_and_never_blocks(tmp_path, body):
    guard = _guard(tmp_path)
    env = _bin_dir(tmp_path, "broken-awk", fake_awk=body)
    assert _warns(guard, SILENT["double-quoted commit message"], env)
    assert not _warns(guard, "ls", env)


def test_an_unbalanced_quote_falls_back_to_the_raw_text(tmp_path):
    """bash itself refuses an unbalanced quote, so nothing runs; the hook
    matches the raw text, as it did before S-NEXT-hookmatch."""
    guard = _guard(tmp_path)
    for command in (f'echo "{BAD}', f"echo '{BAD}", f"echo $'{BAD}",
                    f'echo "$(true {BAD}"', f"cat <<'E\n{BAD}"):
        assert _view(command).returncode == 3, command
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


def test_a_large_heredoc_is_viewed_quickly(tmp_path):
    guard = _guard(tmp_path)
    body = "".join(f"line {i} with 'quotes' and \"more\" {BAD}\n" for i in range(2000))
    command = f"cat > big.md <<'EOF'\n{body}EOF\necho ok"
    assert len(command.encode()) < COMMAND_VIEW_MAX_BYTES
    start = time.monotonic()
    assert not _warns(guard, command)
    assert time.monotonic() - start < 5.0


def test_random_shell_text_never_breaks_the_hook(tmp_path):
    """Fuzz: arbitrary mixes of quotes, escapes, heredoc operators and
    separators either warn with the exact line or stay silent -- never
    another exit code, never stderr -- and the awk view always ends (exit 0
    or 3)."""
    guard = _guard(tmp_path)
    atoms = ["'", '"', "\\", "$'", "$(", ")", "`", "<<", "<<-", "<<<", "EOF", "\n", "\t",
             " ", "#", ";", "&", "|", "bash -c ", "eval ", BAD, "x", "</dev/null"]
    rng = random.Random(131)
    for _ in range(60):
        command = "".join(rng.choice(atoms) for _ in range(rng.randint(1, 30)))
        view = _view(command)
        assert view.returncode in (0, 3), (command, view.stderr)
        assert view.stderr == ""
        _warns(guard, command)  # asserts exit 0, no stderr, exact line or nothing


@pytest.mark.skipif(shutil.which("gawk") is None, reason="gawk not installed")
def test_the_view_program_is_posix_awk():
    """No gawk extension: the program runs the same under ``gawk --posix``."""
    for command in [*SILENT.values(), *WARNS.values()]:
        plain = _view(command)
        posix = _view(command, ("gawk", "--posix"))
        assert (posix.returncode, posix.stdout, posix.stderr) == (
            plain.returncode, plain.stdout, ""), command


def test_the_view_keeps_command_words_and_blanks_the_rest():
    def view(command: str) -> str:
        proc = _view(command)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.rstrip("\n")

    assert view('git commit -m "x y" && ls') == 'git commit -m "" && ls'
    assert view("echo 'a' $'b' \"c\"") == "echo '' $'' \"\""
    assert view("cat <<'EOF'\nbody\nEOF\nls") == "cat <<'EOF'\nEOF\nls"
    assert view("bash -c 'echo \"hi\"; ls'") == "bash -c echo \"\"; ls"
    assert view('sh -c "echo \\"hi\\"; ls"') == 'sh -c echo ""; ls'
    assert view("eval 'a' \"b\"") == "eval a b"
    assert view("python3 -c 'x'") == "python3 -c ''"
    assert view('echo "a $(ls "x") b"') == 'echo "$(ls "")"'
    assert view("ls # a 'comment'") == "ls "
    assert view("echo a#b") == "echo a#b"
    assert view("echo \\'x") == "echo \\'x"
