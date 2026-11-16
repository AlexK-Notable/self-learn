"""S-160: a conservative refusal filter, never a safety proof or approval."""
from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass

CREDENTIAL = re.compile(r"(?i)(?:\.env\b|\.ssh\b|credentials|token|hosts\.yml|\.aws\b|\.gnupg\b|id_rsa|id_ed25519|\.(?:pem|key)\b)")
MODULES = frozenset("sys pathlib os json csv re math statistics collections itertools functools operator string textwrap datetime calendar hashlib difflib argparse decimal fractions pprint unicodedata typing dataclasses enum io".split())
DANGEROUS = frozenset[str]("remove unlink rmdir removedirs rename renames replace truncate rmtree move write_text write_bytes touch mkdir makedirs chmod chown symlink link system exec execv execve execl execlp execvp execvpe spawn fork forkpty popen FileIO start_server open_connection create_connection connect bind listen send recv run Popen sleep decode fromhex loads load read_pickle extract extractall dump dumps".split()) - frozenset({"loads", "load", "dump", "dumps", "decode", "replace"})
COMMANDS = frozenset("cat grep sed awk find sort uniq wc cut tr head tail jq date stat sha256sum printf echo test basename dirname realpath comm diff git".split())
GIT_READ = frozenset("log show diff status rev-parse ls-files blame cat-file".split())

@dataclass(frozen=True)
class Screen:
    language: str
    rules: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.rules

    def record(self) -> dict:
        return {"language": self.language, "ok": self.ok, "rules": list(self.rules)}


def screen(text: str) -> Screen:
    rules: list[str] = []
    if len(text.encode()) > 64_000:
        rules.append("size: scripts must be at most 64000 bytes")
    if CREDENTIAL.search(text):
        rules.append("credentials: credential paths or names are forbidden")
    if re.search(r"base64|b64decode|fromhex|/dev/(?:tcp|udp)", text):
        rules.append("payload: encoded payloads and device networking are forbidden")
    first = text.splitlines()[0] if text else ""
    if first in ("#!/usr/bin/env python3", "#!/usr/bin/python3"):
        language = "python"
        rules.extend(_python(text))
    elif first in ("#!/usr/bin/env bash", "#!/bin/bash", "#!/usr/bin/bash"):
        language = "bash"
        rules.extend(_bash(text))
    else:
        language = "unknown"
        rules.append("language: use a python3 or bash shebang")
    return Screen(language, tuple(dict.fromkeys(rules)))


def _caller_path(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Subscript):
        return ast.unparse(node.value) == "sys.argv" and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int) and node.slice.value > 0
    if isinstance(node, ast.Call) and ast.unparse(node.func) in ("Path", "pathlib.Path") and len(node.args) == 1:
        return _caller_path(node.args[0], names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _caller_path(node.left, names) and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str) and bool(re.fullmatch(r"[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)?", node.right.value))
    return False


def _python(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ["syntax: invalid Python"]
    rules: list[str] = []
    paths: set[str] = set()
    # Only single, direct assignments qualify; reassignments fail closed.
    assignments: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
    for _ in range(len(assignments) + 1):
        for name, values in assignments.items():
            if len(values) == 1 and _caller_path(values[0], paths):
                paths.add(name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(m not in MODULES for m in modules) or (isinstance(node, ast.ImportFrom) and node.level):
                rules.append("imports: only the read/report standard-library allow-list is permitted")
            if isinstance(node, ast.ImportFrom) and any(a.name in DANGEROUS or a.name == "replace" for a in node.names):
                rules.append("effects: destructive or process imports are forbidden")
            if any(a.asname or a.name == "*" for a in node.names):
                rules.append("indirection: aliased and wildcard imports are refused")
        if isinstance(node, (ast.While, ast.AsyncFor, ast.AsyncWith, ast.Await)):
            rules.append("bounded: while loops and asynchronous work are refused")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in DANGEROUS or (node.attr == "replace" and not isinstance(node.value, ast.Constant)):
                rules.append("effects: mutation, process, or hidden attribute is forbidden")
        if isinstance(node, ast.Name) and node.id in {"eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "input"}:
            rules.append("indirection: dynamic execution or introspection is forbidden")
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name in {"open", "io.open"} or isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                method = isinstance(node.func, ast.Attribute) and name != "io.open"
                index = 0 if method else 1
                mode = node.args[index] if len(node.args) > index else ast.Constant("r")
                mode = next((k.value for k in node.keywords if k.arg == "mode"), mode)
                if not isinstance(mode, ast.Constant) or mode.value not in ("r", "rb", "rt", "x", "xb", "xt") or any(k.arg in ("opener", None) for k in node.keywords):
                    rules.append("open-mode: only read or exclusive create is permitted")
                elif str(mode.value).startswith("x"):
                    target = node.func.value if method and isinstance(node.func, ast.Attribute) else (node.args[0] if node.args else ast.Constant(None))
                    if not _caller_path(target, paths):
                        rules.append("output-path: exclusive output must derive from a caller argument")
            if name.startswith("os.") and name not in {"os.stat", "os.lstat", "os.listdir", "os.walk", "os.fspath"} and not name.startswith("os.path."):
                rules.append("os-effects: only local read operations are permitted")
            if name.startswith("itertools.") and name.split(".")[-1] in {"count", "cycle", "repeat"}:
                rules.append("bounded: potentially infinite iterators are refused")
    return rules


def _bash(text: str) -> list[str]:
    rules: list[str] = []
    lines = text.splitlines()[1:]
    effective = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not effective or effective[0] != "set -o noclobber":
        rules.append("noclobber: bash requires set -o noclobber")
    # No substitutions/functions/control flow: all commands can then be
    # checked, rather than mistaking embedded commands for quoted data.
    if re.search(r"`|\$\(|[(){}]|\\|\$'|\b(?:eval|exec|source|while|until|for|function|trap)\b", text):
        rules.append("shell-syntax: substitution, evaluation, functions and loops are refused")
    try:
        lex = shlex.shlex("\n".join(lines), posix=True, punctuation_chars=";&|<>\n")
        lex.whitespace = " \t\r"
        tokens = list(lex)
    except ValueError:
        return rules + ["syntax: invalid shell quoting"]
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token in (";", "\n", "|", "&&", "||") or token.isspace():
            commands.append([])
        elif "&" in token or token in (">>", ">|", "<>", "<<", "<<<"):
            rules.append("shell-effects: background work, append and unsafe redirects are refused")
        else:
            commands[-1].append(token)
    for command in commands:
        if not command:
            continue
        if command == ["set", "-o", "noclobber"]:
            continue
        if command[0] not in COMMANDS:
            rules.append("command: not on the local read/report allow-list: " + command[0])
            continue
        for i, token in enumerate(command):
            if token in (">", "<"):
                if i + 1 >= len(command) or not re.fullmatch(r"\$[1-9][0-9]*(?:/[a-zA-Z0-9_.-]+)?", command[i + 1]) or ".." in command[i + 1]:
                    rules.append("output-path: redirects must name a caller argument")
        if command[0] == "git" and not _git_read_only(command[1:]):
            rules.append("git: require --no-pager --no-optional-locks -c core.fsmonitor=false -c log.showSignature=false, a read-only subcommand, and disabled diff helpers")
        if command[0] == "sed" and not _sed_read_only(command[1:]):
            rules.append("sed-effects: only simple substitutions and print/delete/quit expressions are permitted")
        if command[0] == "tail" and any(t.startswith(("-f", "-F", "--follow", "--retry")) for t in command[1:]):
            rules.append("bounded: follow modes start persistent work")
        if command[0] == "awk":
            rules.append("awk-effects: awk programs require unsupported embedded-language analysis")
        if command[0] == "find" and any(t in {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"} for t in command):
            rules.append("find-effects: only traversal and printing are permitted")
        if command[0] == "date" and any(t.startswith(("-s", "--set")) for t in command[1:]):
            rules.append("command-effects: setting the clock is forbidden")
        if command[0] == "sort" and any(t.startswith("--compress-program") for t in command[1:]):
            rules.append("command-effects: external compression programs are forbidden")
        if command[0] in {"sort", "uniq", "tee"} and (any(t.startswith(("-o", "--output")) for t in command) or command[0] == "uniq" and len([t for t in command[1:] if not t.startswith("-")]) > 1):
            rules.append("command-output: output files must use checked exclusive redirects")
    return rules


def _sed_read_only(args: list[str]) -> bool:
    """Do not parse a second programming language optimistically.

    sed d deletes pattern space, not disk data. File scripts, extensions and
    unknown flags refuse. Every -e expression is checked independently.
    """
    expressions: list[str] = []
    need_expression = False
    for arg in args:
        if arg == "-e":
            if need_expression:
                return False
            need_expression = True
        elif arg in {"-n", "-E", "-r", "--quiet", "--silent", "--posix", "--sandbox", "--"}:
            continue
        elif arg.startswith("-"):
            return False
        elif need_expression or not expressions:
            expressions.append(arg)
            need_expression = False
    return bool(expressions) and not need_expression and all(
        re.fullmatch(r"s/[^/\n]*/[^/\n]*/[gIp0-9]*|(?:[0-9]+(?:,[0-9]+)?)?[pdq]", expr)
        for expr in expressions
    )


def _git_read_only(args: list[str]) -> bool:
    """Git's ostensibly read-only commands can refresh the index or run helpers."""
    flags: set[str] = set()
    at = 0
    while at < len(args):
        if args[at] in {"--no-pager", "--no-optional-locks"}:
            flags.add(args[at]); at += 1
        elif args[at] == "-c" and at + 1 < len(args) and args[at + 1] in {"core.fsmonitor=false", "log.showSignature=false"}:
            flags.add(args[at + 1]); at += 2
        else:
            break
    required = {"--no-pager", "--no-optional-locks", "core.fsmonitor=false", "log.showSignature=false"}
    if flags != required or at >= len(args) or args[at] not in GIT_READ:
        return False
    subcommand, rest = args[at], args[at + 1:]
    if any(t.startswith(("--output", "--ext-diff", "--textconv", "--filters", "--show-signature")) or "%G" in t for t in rest):
        return False
    if subcommand in {"diff", "show", "log"} and not {"--no-ext-diff", "--no-textconv"}.issubset(rest):
        return False
    if subcommand == "blame" and "--no-textconv" not in rest:
        return False
    return True
