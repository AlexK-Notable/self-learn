"""S-160: a conservative refusal filter, never a safety proof or approval."""
from __future__ import annotations

import ast
import re
import shlex
import string
from dataclasses import dataclass

CREDENTIAL = re.compile(r"(?i)(?:\.env\b|\.ssh\b|credentials|token|hosts\.yml|\.aws\b|\.gnupg\b|\.netrc\b|/proc/(?:self|thread-self|[0-9]+)/environ\b|rclone\.conf|\.docker/config\.json|\.npmrc\b|\.pgpass\b|\.git-credentials\b|\.kube/config|\.password-store\b|(?:^|/)age(?:/|\b)|\.config/gh\b|id_[a-z0-9_*?-]+|shadow\b|\.(?:pem|key)\b)")
DANGEROUS = frozenset[str]("remove unlink rmdir removedirs rename renames replace truncate rmtree move write_text write_bytes touch mkdir makedirs chmod chown symlink link system exec execv execve execl execlp execvp execvpe spawn fork forkpty popen FileIO start_server open_connection create_connection connect bind listen send recv run Popen sleep decode fromhex loads load read_pickle extract extractall dump dumps".split()) - frozenset({"loads", "load", "dump", "dumps", "decode", "replace"})
# F1-F3: module members are positive lists, including from-import spellings.
MEMBERS = {
    "sys": "argv stdin stdout stderr exit",
    "json": "load loads dump dumps JSONDecodeError",
    "re": "compile search match fullmatch findall finditer split sub subn escape IGNORECASE MULTILINE DOTALL ASCII VERBOSE",
    "csv": "reader writer DictReader DictWriter Sniffer QUOTE_ALL QUOTE_MINIMAL QUOTE_NONE QUOTE_NONNUMERIC",
    "collections": "Counter defaultdict deque namedtuple OrderedDict ChainMap",
    "itertools": "chain combinations combinations_with_replacement permutations product accumulate islice takewhile dropwhile filterfalse groupby starmap zip_longest pairwise batched compress tee",
    "pathlib": "Path PurePath PurePosixPath PureWindowsPath",
    "os": "path listdir scandir walk stat lstat sep getcwd fspath",
    "os.path": "abspath basename commonpath commonprefix dirname exists isabs isdir isfile islink join normcase normpath realpath relpath split splitdrive splitext getsize getmtime getctime getatime",
    "datetime": "date datetime time timedelta timezone MINYEAR MAXYEAR",
    "math": "ceil floor trunc fabs factorial gcd lcm isclose isfinite isinf isnan sqrt isqrt pow exp log log2 log10 sin cos tan asin acos atan atan2 degrees radians hypot dist fsum prod comb perm pi e tau inf nan",
    "statistics": "mean fmean geometric_mean harmonic_mean median median_low median_high median_grouped mode multimode quantiles pstdev pvariance stdev variance covariance correlation linear_regression",
    "hashlib": "sha256 sha512 sha384 sha224 sha1 md5 blake2b blake2s shake_128 shake_256 file_digest",
    "difflib": "SequenceMatcher unified_diff context_diff ndiff get_close_matches Differ HtmlDiff",
    "fnmatch": "fnmatch fnmatchcase filter translate",
    "glob": "glob iglob escape",
    "textwrap": "wrap fill dedent indent shorten TextWrapper",
    "string": "ascii_letters ascii_lowercase ascii_uppercase digits hexdigits octdigits punctuation whitespace printable Template capwords",
    "typing": "Any Iterable Iterator Mapping Sequence Optional Union Literal NamedTuple TypedDict Callable TypeVar Generic",
    "dataclasses": "dataclass field fields asdict astuple replace is_dataclass",
    "enum": "Enum IntEnum StrEnum Flag IntFlag auto unique",
    "tomllib": "load loads TOMLDecodeError",
    "shlex": "split",
    "argparse": "ArgumentParser Namespace ArgumentError SUPPRESS",
    "io": "StringIO BytesIO open",
    "decimal": "Decimal Context localcontext getcontext",
    "fractions": "Fraction",
    "functools": "reduce partial cache lru_cache cmp_to_key",
    "pprint": "pprint pformat pp",
    "unicodedata": "normalize category name lookup combining decimal digit numeric",
    "calendar": "monthrange isleap leapdays monthcalendar day_name day_abbr month_name month_abbr",
}
MODULES = frozenset(MEMBERS)
# Methods of values (never module objects). No reflective/destructive methods.
VALUE_MEMBERS = frozenset("path name suffix suffixes stem parent parents parts anchor drive root is_absolute is_relative_to relative_to with_name with_suffix with_stem as_posix resolve absolute exists is_file is_dir is_symlink stat lstat iterdir glob rglob read_text read_bytes open match joinpath read readline readlines write writelines flush close closed seek tell encoding getvalue keys values items get setdefault update copy clear pop popitem append extend insert remove sort reverse count index add discard union intersection difference most_common elements total strip lstrip rstrip split rsplit splitlines join lower upper casefold title capitalize startswith endswith replace find rfind index rindex format format_map encode decode isdigit isalpha isalnum isspace islower isupper zfill center ljust rjust partition rpartition rematch groups group groupdict start end span search fullmatch findall finditer sub subn hexdigest digest update copy isoformat strftime strptime fromisoformat today now utcnow date time timestamp total_seconds weekday isoweekday year month day hour minute second microsecond tzinfo days seconds writerow writerows writeheader fieldnames line_num dialect add_argument parse_args parse_known_args print_help format_help add_subparsers add_parser set_defaults setdefault get_opcodes get_matching_blocks ratio quick_ratio real_quick_ratio get_close_matches st_mode st_size st_mtime st_ctime st_atime st_ino".split())

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



FILE_METHODS = frozenset("read_text read_bytes iterdir glob rglob stat lstat exists is_file is_dir is_symlink resolve absolute readlink open".split())
FILE_CALLS = frozenset("os.listdir os.scandir os.walk os.stat os.lstat glob.glob glob.iglob os.path.exists os.path.isdir os.path.isfile os.path.islink os.path.getsize os.path.getmtime os.path.getctime os.path.getatime os.path.realpath os.path.abspath".split())


def _fold(node: ast.AST, assignments: dict[str, list[ast.AST]], seen: frozenset[str] = frozenset()) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id not in seen and len(assignments.get(node.id, [])) == 1:
        return _fold(assignments[node.id][0], assignments, seen | {node.id})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _fold(node.left, assignments, seen), _fold(node.right, assignments, seen)
        return a + b if a is not None and b is not None else None
    if isinstance(node, ast.JoinedStr):
        pieces = [_fold(n.value if isinstance(n, ast.FormattedValue) else n, assignments, seen) for n in node.values]
        return "".join(v for v in pieces if isinstance(v, str)) if all(isinstance(v, str) for v in pieces) else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        sep = _fold(node.func.value, assignments, seen)
        if sep is not None and len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
            parts = [_fold(n, assignments, seen) for n in node.args[0].elts]
            return sep.join(v for v in parts if isinstance(v, str)) if all(isinstance(v, str) for v in parts) else None
    return None


def _relative(text: str) -> bool:
    return not (text.startswith(("/", "~", "\\")) or re.match(r"[A-Za-z]:", text) or
        ".." in text.replace("\\", "/").split("/") or CREDENTIAL.search(text))


def _input_path(node: ast.AST, paths: set[str], assignments: dict[str, list[ast.AST]], seen: frozenset[str] = frozenset()) -> bool:
    value = _fold(node, assignments)
    if value is not None:
        return _relative(value)
    if isinstance(node, ast.Name):
        if node.id in paths:
            return True
        if node.id not in seen and len(assignments.get(node.id, [])) == 1:
            return _input_path(assignments[node.id][0], paths, assignments, seen | {node.id})
        return False
    if _caller_path(node, paths):
        return True
    if isinstance(node, ast.Call):
        name = ast.unparse(node.func)
        if name in {"sys.stdin.readline", "sys.stdin.read"}:
            return True
        if name in {"Path", "pathlib.Path", "PurePath", "pathlib.PurePath", "os.path.join"}:
            return all(_input_path(n, paths, assignments, seen) for n in node.args) and not node.keywords
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"joinpath", "with_name", "with_suffix", "with_stem", "strip", "rstrip", "resolve", "absolute"}:
            return _input_path(node.func.value, paths, assignments, seen) and all(_input_path(n, paths, assignments, seen) for n in node.args)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _input_path(node.left, paths, assignments, seen) and _input_path(node.right, paths, assignments, seen)
    if isinstance(node, ast.Attribute) and node.attr in {"parent", "path"}:
        # parent can escape an allowed relative directory.
        return node.attr == "path" and _input_path(node.value, paths, assignments, seen)
    return False


def _path_rules(tree: ast.AST, paths: set[str], assignments: dict[str, list[ast.AST]], imported: dict[str, str]) -> list[str]:
    rules = []
    derived = set(paths)
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name) and isinstance(node.iter, ast.Call):
            call = node.iter
            name = imported.get(ast.unparse(call.func), ast.unparse(call.func))
            if name in FILE_CALLS and call.args and _input_path(call.args[0], derived, assignments):
                derived.add(node.target.id)
            elif isinstance(call.func, ast.Attribute) and call.func.attr in {"iterdir", "glob", "rglob"} and _input_path(call.func.value, derived, assignments):
                derived.add(node.target.id)
        folded = _fold(node, assignments)
        if folded is not None and CREDENTIAL.search(folded):
            rules.append("credentials: constant-folded value names a credential")
        if isinstance(node, ast.Call):
            name = imported.get(ast.unparse(node.func), ast.unparse(node.func))
            targets = []
            if name in FILE_CALLS or name in {"Path", "pathlib.Path", "PurePath", "pathlib.PurePath"}:
                targets = list(node.args) or [ast.Constant(".")]
                targets += [k.value for k in node.keywords if k.arg in {"path", "pathname", "root_dir"}]
                if any(k.arg not in {"path", "pathname", "root_dir", "recursive", "include_hidden", "follow_symlinks", "topdown", "onerror"} for k in node.keywords):
                    rules.append("input-path: unsupported filesystem keyword")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in FILE_METHODS and name != "io.open":
                targets = [node.func.value]
                if node.func.attr in {"glob", "rglob"}:
                    targets += list(node.args)
            if any(not _input_path(n, derived, assignments) for n in targets):
                rules.append("input-path: file access requires caller/stdin input or a relative path without parent traversal")
            if name == "range" and any(isinstance(n, ast.Pow) or isinstance(n, ast.Constant) and isinstance(n.value, int) and abs(n.value) > 1_000_000 for arg in node.args for n in ast.walk(arg)):
                rules.append("bounded: oversized constant ranges are refused")
        if isinstance(node, ast.For):
            iterable = ast.unparse(node.iter)
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and ast.unparse(n.func.value) == iterable and n.func.attr in {"append", "extend", "insert", "add", "update"} for stmt in node.body for n in ast.walk(stmt)):
                rules.append("bounded: mutating the collection being iterated is refused")
    return rules

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
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[alias.name.split(".")[0]] = alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported[alias.name] = (node.module or "") + "." + alias.name
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    local_calls = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    builtins = set("abs all any ascii bin bool bytearray bytes chr complex dict divmod enumerate filter float format frozenset hash hex int isinstance issubclass iter len list map max min next oct open ord pow print range repr reversed round set slice sorted str sum tuple type zip object super Exception ValueError TypeError RuntimeError KeyError IndexError StopIteration OSError FileNotFoundError".split())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            dotted = ast.unparse(node)
            head = dotted.split(".")[0]
            canonical = imported.get(head, head) + dotted[len(head):]
            parent = parents.get(node)
            if canonical in FILE_CALLS and not (isinstance(parent, ast.Call) and parent.func is node):
                rules.append("indirection: filesystem functions must be called directly")
            if canonical in MODULES and not (isinstance(parent, ast.Attribute) and parent.value is node):
                rules.append("indirection: module objects cannot be used as values or rebound")
        if (isinstance(node, ast.Name) and node.id == "open" or isinstance(node, ast.Attribute) and node.attr in FILE_METHODS | {"format", "format_map"}):
            parent = parents.get(node)
            if not isinstance(parent, ast.Call) or parent.func is not node:
                rules.append("indirection: checked open/format methods must be called directly")
        if isinstance(node, ast.Name) and imported.get(node.id) in FILE_CALLS:
            parent = parents.get(node)
            if not isinstance(parent, ast.Call) or parent.func is not node:
                rules.append("indirection: filesystem functions must be called directly")
        if isinstance(node, ast.Name) and node.id.startswith("__") and node.id != "__name__":
            rules.append("indirection: hidden namespace access is refused")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and CREDENTIAL.search(node.value):
            rules.append("credentials: normalized string names a credential")
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            value = getattr(node, "value", None)
            values = ast.walk(value) if isinstance(value, (ast.List, ast.Tuple, ast.Set, ast.Dict)) else [value]
            if any(v is not None and imported.get(ast.unparse(v), ast.unparse(v)) in MODULES for v in values):
                rules.append("indirection: module objects cannot be rebound")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(m not in MODULES for m in modules) or (isinstance(node, ast.ImportFrom) and node.level):
                rules.append("imports: only the read/report standard-library allow-list is permitted")
            if isinstance(node, ast.ImportFrom) and any(a.name not in MEMBERS.get(node.module or "", "").split() for a in node.names):
                rules.append("imports: member is not on this module's allow-list")
            if isinstance(node, ast.ImportFrom) and any(a.name in DANGEROUS or a.name == "replace" for a in node.names):
                rules.append("effects: destructive or process imports are forbidden")
            if any(a.asname or a.name == "*" for a in node.names):
                rules.append("indirection: aliased and wildcard imports are refused")
        if isinstance(node, (ast.While, ast.AsyncFor, ast.AsyncWith, ast.Await)):
            rules.append("bounded: while loops and asynchronous work are refused")
        if isinstance(node, ast.Attribute):
            dotted = ast.unparse(node)
            head = dotted.split(".")[0]
            canonical = imported.get(head, head) + dotted[len(head):]
            parent, _, member = canonical.rpartition(".")
            if parent in MODULES:
                if member not in MEMBERS[parent].split():
                    rules.append("module-member: attribute is not on this module's allow-list")
            elif node.attr not in VALUE_MEMBERS:
                rules.append("value-member: method or attribute is not on the read/report allow-list")
            if node.attr.startswith("_") or node.attr in DANGEROUS or (node.attr == "replace" and not isinstance(node.value, ast.Constant)):
                rules.append("effects: mutation, process, or hidden attribute is forbidden")
        if isinstance(node, ast.Name) and node.id in {"eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "input"}:
            rules.append("indirection: dynamic execution or introspection is forbidden")
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if isinstance(node.func, ast.Name) and name not in builtins | local_calls | set(imported):
                rules.append("call-target: only declared functions and allowed builtins/imports may be called")
            if not isinstance(node.func, (ast.Name, ast.Attribute)):
                rules.append("call-target: indirect call expressions are refused")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"format", "format_map"}:
                fmt = node.func.value
                valid = False
                if isinstance(fmt, ast.Constant) and isinstance(fmt.value, str):
                    try:
                        valid = all(field is None or (
                            re.fullmatch(r"[A-Za-z0-9_]*", field) is not None
                            and "{" not in (spec or "") and "}" not in (spec or "")
                            and conversion in {None, "r", "s", "a"})
                            for _literal, field, spec, conversion in string.Formatter().parse(fmt.value))
                    except ValueError:
                        pass
                if not valid:
                    rules.append("format: require literal fields without attribute/index lookup")
            if name == "iter" and len(node.args) != 1:
                rules.append("bounded: sentinel iterators are refused")
            if name in {"open", "io.open"} or isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                method = isinstance(node.func, ast.Attribute) and name != "io.open"
                index = 0 if method else 1
                mode = node.args[index] if len(node.args) > index else ast.Constant("r")
                mode = next((k.value for k in node.keywords if k.arg == "mode"), mode)
                if not isinstance(mode, ast.Constant) or mode.value not in ("r", "rb", "rt", "x", "xb", "xt") or any(k.arg in ("opener", None) for k in node.keywords):
                    rules.append("open-mode: only read or exclusive create is permitted")
                else:
                    target = node.func.value if method and isinstance(node.func, ast.Attribute) else (node.args[0] if node.args else ast.Constant(None))
                    if not (_caller_path(target, paths) if str(mode.value).startswith("x") else _input_path(target, paths, assignments)):
                        rules.append("output-path: file access must derive from caller/stdin or a relative read path")
            if name.startswith("os.") and name not in {"os.stat", "os.lstat", "os.listdir", "os.scandir", "os.walk", "os.getcwd", "os.fspath"} and not name.startswith("os.path."):
                rules.append("os-effects: only local read operations are permitted")
            if name.startswith("itertools.") and name.split(".")[-1] in {"count", "cycle", "repeat"}:
                rules.append("bounded: potentially infinite iterators are refused")
    rules.extend(_path_rules(tree, paths, assignments, imported))
    return rules



def _unquoted_glob(text: str) -> bool:
    quote = None
    for line in text.splitlines()[1:]:
        if line.lstrip().startswith("#"):
            continue
        for char in line:
            if quote:
                if char == quote:
                    quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char in "*?[":
                return True
    return False


def _bash(text: str) -> list[str]:
    rules: list[str] = []
    lines = text.splitlines()[1:]
    if _unquoted_glob(text):
        rules.append("input-path: unquoted glob operands are refused")
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
        lex.whitespace_split = True
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
    assigned: set[str] = set()
    assigned_values: dict[str, str] = {}
    for command in commands:
        if not command:
            continue
        normalized = " ".join(command)
        if CREDENTIAL.search(normalized):
            rules.append("credentials: normalized shell word names a credential")
        if any(w.startswith("~") or w.startswith("/") and w != "/dev/null" for w in command):
            rules.append("input-path: local file operands must come from caller arguments")
        for i, word in enumerate(command[1:], 1):
            output = i > 0 and command[i - 1] == ">"
            if not output and "$" in word and not re.fullmatch(r"\$(?:[1-9][0-9]*|[A-Za-z_][A-Za-z_0-9]*)", word):
                rules.append("input-path: composed variable operands are refused")
            if ".." in word.split("/") or word.startswith("~"):
                rules.append("input-path: parent traversal and home expansion are refused")
            if re.search(r"(?:^|/)dev/+", word) and word != "/dev/null":
                rules.append("input-path: device files other than /dev/null are refused")
            if command[0] in {"cat", "grep", "sort", "uniq", "head", "tail", "wc", "stat", "sha256sum", "diff", "comm", "realpath", "dirname", "basename", "find"} and re.search(r"[?*\[]", word):
                # Literal quoted patterns are useful for grep/find; shell expansion
                # is refused, including a glob appended after a quoted parameter.
                if not any(q + word + q in text for q in ("'", '"')):
                    rules.append("input-path: unquoted glob operands are refused")
            if word.startswith("$") and word[1:] in assigned_values and not _relative(assigned_values[word[1:]]):
                rules.append("input-path: assigned path is absolute, traversing or credential-shaped")
        variables = re.findall(r"\$([A-Za-z_][A-Za-z_0-9]*)", normalized)
        if any(v not in assigned for v in variables):
            rules.append("variables: only positional or script-assigned variables may expand")
        if len(command) == 1 and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*=[^;]*", command[0]):
            name = command[0].split("=", 1)[0]
            if name in {"PATH", "IFS", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "CDPATH", "GLOBIGNORE", "LD_PRELOAD", "LD_LIBRARY_PATH"}:
                rules.append("variables: shell control variables cannot be assigned")
            value = command[0].split("=", 1)[1]
            if not _relative(value) or "$" in value and not re.fullmatch(r"\$[1-9][0-9]*", value):
                rules.append("input-path: assigned values must be relative literals or a positional parameter")
            assigned_values[name] = value
            assigned.add(name)
            continue
        if command == ["set", "-o", "noclobber"]:
            continue
        if command[0] not in COMMANDS:
            rules.append("command: not on the local read/report allow-list: " + command[0])
            continue
        rules.extend(_command_options(command))
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

# F2: exact options only. No getopt abbreviation; every short cluster is parsed.
# (short flags, short flags taking a value, long flags, long value flags, min/max operands)
OPTIONS = {
    "cat": ("AbenstuvET", "", "show-all number-nonblank number squeeze-blank show-ends show-tabs show-nonprinting", "", 0, None),
    "grep": ("EFGPivwxyzcLlnHhoqs", "efmABCD", "extended-regexp fixed-strings perl-regexp ignore-case invert-match word-regexp line-regexp count files-without-match files-with-matches line-number with-filename no-filename only-matching quiet silent", "regexp max-count after-context before-context context directories", 1, None),
    "sort": ("bdfgimnhrRsuVz", "kSt", "ignore-leading-blanks dictionary-order ignore-case general-numeric-sort ignore-nonprinting month-sort numeric-sort human-numeric-sort reverse random-sort stable unique zero-terminated check", "key buffer-size field-separator parallel", 0, None),
    "uniq": ("cduiz", "fsw", "count repeated unique ignore-case zero-terminated", "skip-fields skip-chars check-chars", 0, 1),
    "wc": ("clmwL", "", "bytes chars lines words max-line-length", "", 0, None),
    "cut": ("nsz", "bcdf", "complement only-delimited zero-terminated", "bytes characters fields delimiter output-delimiter", 0, None),
    "tr": ("cdsCt", "", "complement delete squeeze-repeats truncate-set", "", 1, 2),
    "head": ("qvz", "nc", "quiet silent verbose zero-terminated", "lines bytes", 0, None),
    "tail": ("qvz", "nc", "quiet silent verbose zero-terminated", "lines bytes", 0, None),
    "jq": ("nrcsCeajMSR", "", "null-input raw-output compact-output slurp color-output monochrome-output exit-status ascii-output join-output sort-keys raw-input", "indent", 1, None),
    "date": ("uR", "d", "utc universal rfc-email", "date iso-8601 rfc-3339", 0, 1),
    "stat": ("Lf", "ct", "dereference file-system", "format printf", 1, None),
    "sha256sum": ("btcz", "", "binary text check zero tag ignore-missing quiet status strict warn", "", 0, None),
    "printf": ("", "", "", "", 1, None),
    "echo": ("nE", "", "", "", 0, None),
    "test": ("", "", "", "", 1, 3),
    "basename": ("az", "s", "multiple zero", "suffix", 1, 2),
    "dirname": ("z", "", "zero", "", 1, None),
    "realpath": ("eLmPqsz", "", "canonicalize-existing canonicalize-missing logical physical quiet strip no-symlinks zero", "relative-to relative-base", 1, None),
    "comm": ("123z", "", "check-order nocheck-order zero-terminated total", "output-delimiter", 2, 2),
    "diff": ("abBiEwZyqrsuN", "UC", "text ignore-space-change ignore-blank-lines ignore-case ignore-tab-expansion ignore-all-space ignore-trailing-space side-by-side brief recursive report-identical-files new-file", "unified context width", 2, 2),
}


def _options(command: str, args: list[str]) -> tuple[list[str], bool]:
    flags, values, longs, longvalues, minimum, maximum = OPTIONS[command]
    operands: list[str] = []
    i, options = 0, True
    while i < len(args):
        word = args[i]
        i += 1
        if word == "--" and options:
            options = False
        elif options and word.startswith("--"):
            key, equal, _ = word[2:].partition("=")
            if key in longvalues.split():
                if not equal:
                    if i == len(args): return operands, False
                    i += 1
            elif key not in longs.split() or equal:
                return operands, False
        elif options and word.startswith("-") and word != "-":
            cluster = word[1:]
            for at, char in enumerate(cluster):
                if char in values:
                    if command in {"tail", "head"} and at < len(cluster) - 1 and not re.fullmatch(r"[+-]?[0-9]+[bBkKmMgG]?", cluster[at + 1:]):
                        return operands, False
                    if at == len(cluster) - 1:
                        if i == len(args): return operands, False
                        i += 1
                    break
                if char not in flags:
                    return operands, False
        else:
            operands.append(word)
    return operands, len(operands) >= minimum and (maximum is None or len(operands) <= maximum)


def _command_arguments(command: list[str]) -> list[str]:
    args: list[str] = []
    i = 1
    while i < len(command):
        if command[i] in {"<", ">"}:
            i += 2
        else:
            args.append(command[i]); i += 1
    return args


def _command_options(command: list[str]) -> list[str]:
    name, args = command[0], _command_arguments(command)
    if name == "test":
        unary = {"-e", "-f", "-d", "-r", "-w", "-x", "-s", "-L", "-z", "-n"}
        binary = {"=", "!=", "-eq", "-ne", "-lt", "-le", "-gt", "-ge", "-nt", "-ot", "-ef"}
        if len(args) == 1 or len(args) == 2 and args[0] in unary or len(args) == 3 and args[1] in binary:
            return []
        return ["options: unsupported test expression"]
    if name in OPTIONS:
        operands, valid = _options(name, args)
        if not valid:
            return ["options: unsupported option, option bundle, or operand count for " + name]
        if name == "printf" and not re.fullmatch(r"(?:[^%$]|%%|%[-+ #0]*[0-9]*(?:\.[0-9]+)?[diouxXfFeEgGaAcspbq])*", operands[0]):
            return ["printf-format: require a literal read/report format; no variable assignments"]
        if name == "jq":
            # Small data-expression language: no file programs, environment, input
            # streams, recursion, loops or user-defined filters.
            words = set(re.findall(r"(?<![.\w])[A-Za-z_][A-Za-z_0-9]*", operands[0]))
            if not words <= {"length", "keys", "values", "sort", "unique", "reverse", "flatten", "map", "select", "true", "false", "null", "type", "tostring", "tonumber", "add", "min", "max", "has"}:
                return ["jq: unsupported data expression"]
            if re.search(r"\.\.|\b(?:env|input|inputs|repeat|recurse|while|until|def)\b|\$", operands[0]):
                return ["jq: persistent, environment or indirect program access"]
    elif name == "find":
        allowed = {"-H", "-L", "-P", "-name", "-iname", "-path", "-ipath", "-type", "-size", "-mtime", "-maxdepth", "-mindepth", "-print", "-print0", "-empty", "-readable", "-writable", "-executable", "-a", "-o", "-not", "!"}
        if not args or any(w.startswith("-") and w not in allowed and not re.fullmatch(r"-[0-9]+", w) for w in args):
            return ["options: unsupported find option"]
    elif name == "git":
        # Globals are vetted separately; subcommand options have no abbreviations.
        sub = next((i for i, w in enumerate(args) if w in GIT_READ), None)
        allowed = {"--no-ext-diff", "--no-textconv", "--oneline", "--stat", "--name-only", "--name-status", "--short", "--porcelain", "--branch", "--cached", "--staged", "--numstat", "--check", "--abbrev-ref", "--show-toplevel", "--show-prefix", "--verify", "--is-inside-work-tree", "--pretty", "--format", "--max-count", "--since", "--until", "--author", "--grep", "--all", "--reverse", "--no-renames", "--follow", "--", "-n", "-p", "-s", "-z", "-b", "-l", "-e", "-t"}
        if sub is None or any(w.startswith("-") and w.split("=", 1)[0] not in allowed for w in args[sub + 1:]):
            return ["options: unsupported git option"]
    return []
