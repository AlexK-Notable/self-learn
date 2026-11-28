"""Rule artifacts for generated hooks, and the evaluator that decides them
without Bash, ``jq``, ``grep`` or ``awk`` (native Windows, lane 5R).

:mod:`hook_compiler` turns a lesson's hook block into a Bash script that
reads a Claude Code hook input on stdin and blocks the tool call (deny) or
hands the model a message (warn). On Windows there may be no Bash, no ``jq``
and no ``grep``. The same rule is therefore also written as a versioned JSON
*rule artifact* (:func:`build_rule`), and :func:`evaluate` decides an input
exactly the way the generated script does: the same stdout bytes, the same
stderr text from the script's own ``echo`` lines, the same exit code.

What "exactly" models, step by step (the script's own order):

- bash's ``INPUT=$(cat)``: NUL bytes dropped, trailing newlines stripped; the
  empty-input test removes every ``[[:space:]]`` character (glibc's table);
- ``jq -r '.tool_name // empty'`` and ``.tool_input.<field> // empty``: the
  input is a stream of JSON values; a non-object, non-null value is an error
  (``//`` does not catch it); ``false``/``null`` print nothing; a string
  prints raw; anything else prints in jq's indented form; invalid UTF-8 is
  replaced the way jq replaces it;
- the S-133 command view of a warning hook on Bash (:func:`command_view`, a
  port of :data:`hook_compiler.COMMAND_VIEW_AWK` run under ``LC_ALL=C``);
- ``grep -qE -- <pattern>``: GNU grep's extended regular expressions under a
  ``C.UTF-8`` locale, matched line by line, through this module's own
  automaton (:func:`compile_pattern`), so no pattern can backtrack.

A pattern whose meaning grep leaves unspecified or ties to the locale
(stray backslashes, back-references, a quantifier with nothing before it, a
range across punctuation, collating elements) is refused at build time with
the reason, never approximated (:class:`RuleError`).

The bound. Matching runs a lazily built DFA over a Thompson automaton of at
most :data:`MAX_PROGRAM` instructions: each input character costs one table
lookup, or one closure over the program on a cache miss, so time is linear
in the input. A wall-clock deadline (:data:`MATCH_DEADLINE_S`, checked every
:data:`_DEADLINE_STRIDE` characters) backs that up; when it is hit the
decision is the script's own matcher-failure branch: a deny guard fails
closed (exit 2, "guard regex failed"), a warning stays silent (exit 0).

Standard library only, and cheap to import: a hook runs on every tool call.
The character tables (:mod:`hook_rules_ctype`) and :mod:`decimal` load only
when a pattern or an input needs them. This module launches nothing and
writes nothing.
"""

from __future__ import annotations

import decimal  # noqa
import hashlib
import json
import re
import time
from bisect import bisect_right

__all__ = [
    "COMMAND_VIEW_MAX_CHARS",
    "DIALECT",
    "MATCH_DEADLINE_S",
    "MAX_PROGRAM",
    "RULE_KIND",
    "RULE_VERSION",
    "VIEW_COMMAND",
    "Decision",
    "Matcher",
    "Rule",
    "RuleError",
    "build_rule",
    "canonical_bytes",
    "check_examples",
    "command_view",
    "compile_pattern",
    "dumps_rule",
    "evaluate",
    "load_rule",
    "rule_digest",
]

#: The artifact format's version. A loader refuses any other.
RULE_VERSION = 1
RULE_KIND = "self-learn-hook-rule"

#: The one matcher dialect: ``grep -qE`` (GNU) under ``LC_ALL=C.UTF-8``,
#: applied to each line of the named field's text.
DIALECT = "gnu-grep-ere/c.utf-8/v1"

#: The S-133 command view (a warning hook on Bash only).
VIEW_COMMAND = "s133-command-view"

#: Mirrors of :data:`hook_compiler.GUARDABLE_TOOLS`, ``TOOL_FIELDS``,
#: ``MODE_EVENTS``, ``MODE_VERDICTS`` and ``COMMAND_VIEW_MAX_BYTES``
#: (a test pins them equal) so the evaluator never imports the compiler.
_TOOL_FIELDS = {"Edit": "file_path", "Write": "file_path", "Bash": "command"}
_MODE_EVENTS = {"deny": ("PreToolUse",), "warn": ("PreToolUse", "PostToolUse")}
_MODE_VERDICTS = {"deny": ("allow", "deny"), "warn": ("allow", "warn")}
COMMAND_VIEW_MAX_CHARS = 262144

#: The largest automaton a pattern may compile to (counted repetition is
#: expanded, so ``(x{100}){100}`` is 10,000 instructions and refused).
MAX_PROGRAM = 4096

#: The wall-clock bound on one decision's matching, under the 5 s hook
#: timeout the activation lane registers.
MATCH_DEADLINE_S = 2.0
_DEADLINE_STRIDE = 2048

#: Bound on the DFA cache (states and transitions); a full cache is cleared
#: and rebuilt as matching goes on, which costs time, never correctness.
_CACHE_LIMIT = 20000

#: grep's RE_DUP_MAX: a larger count is "Regular expression too big".
_DUP_MAX = 32767

_RECORD_ID_RE = re.compile(r"lrn-[0-9a-f]{8}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


class RuleError(ValueError):
    """A rule that cannot be built, or an artifact that cannot be loaded.
    The message says why, in words a person can act on."""


# ===================================================================
# Character classes (GNU grep under C.UTF-8)
# ===================================================================

_MAXCP = 0x10FFFF
_CLASS_NAMES = ("alpha", "upper", "lower", "digit", "xdigit", "alnum", "punct",
                "graph", "print", "space", "blank", "cntrl")
_class_cache: dict[str, list[tuple[int, int]]] = {}


def _decode_table(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    prev = -1
    for pair in text.split():
        gap, length = pair.split(".")
        start = prev + 1 + int(gap, 36)
        end = start + int(length, 36)
        out.append((start, end))
        prev = end
    return out


def _normalize(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + 1:
            if hi > out[-1][1]:
                out[-1] = (out[-1][0], hi)
        else:
            out.append((lo, hi))
    return out


def _complement(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    nxt = 0
    for lo, hi in _normalize(ranges):
        if lo > nxt:
            out.append((nxt, lo - 1))
        nxt = hi + 1
    if nxt <= _MAXCP:
        out.append((nxt, _MAXCP))
    return out


def _subtract(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    # a - b = complement(complement(a) | b)
    return _complement(_complement(a) + list(b))


def _class_ranges(name: str) -> list[tuple[int, int]]:
    hit = _class_cache.get(name)
    if hit is not None:
        return hit
    from . import hook_rules_ctype as ct

    if name in ("alpha", "upper", "lower", "print", "space", "blank", "cntrl"):
        r = _decode_table(getattr(ct, name.upper()))
    elif name == "digit":
        r = [(0x30, 0x39)]
    elif name == "xdigit":
        r = [(0x30, 0x39), (0x41, 0x46), (0x61, 0x66)]
    elif name == "alnum":
        r = _normalize(_class_ranges("alpha") + _class_ranges("digit"))
    elif name == "graph":
        r = _subtract(_class_ranges("print"), _class_ranges("space"))
    elif name == "punct":
        r = _subtract(_class_ranges("graph"), _class_ranges("alnum"))
    elif name == "word":
        r = _normalize(_class_ranges("alnum") + [(0x5F, 0x5F)])
    else:  # pragma: no cover - names are checked by the parser
        raise KeyError(name)
    if name == "upper":
        r = [(0x41, 0x5A)]
    _class_cache[name] = r
    return r


class _CharSet:
    """A set of code points: an ASCII bit mask plus sorted ranges."""

    __slots__ = ("mask", "starts", "ends")

    def __init__(self, ranges: list[tuple[int, int]]):
        ranges = _normalize(ranges)
        mask = 0
        for lo, hi in ranges:
            if lo > 127:
                break
            for c in range(lo, min(hi, 127) + 1):
                mask |= 1 << c
        self.mask = mask
        self.starts = [lo for lo, _ in ranges]
        self.ends = [hi for _, hi in ranges]

    def contains(self, cp: int) -> bool:
        if cp < 128:
            return (self.mask >> cp) & 1 == 1
        i = bisect_right(self.starts, cp) - 1
        return i >= 0 and cp <= self.ends[i]


_set_cache: dict[str, _CharSet] = {}


def _named_set(name: str) -> _CharSet:
    hit = _set_cache.get(name)
    if hit is None:
        hit = _set_cache[name] = _CharSet(_class_ranges(name))
    return hit


# ===================================================================
# The pattern: GNU ERE, parsed exactly or refused
# ===================================================================

# Node shapes: ("set", ranges) ("assert", kind) ("cat", [..]) ("alt", [..])
# ("rep", node, lo, hi|None)
_BOL, _EOL, _WB, _NWB, _WSTART, _WEND = range(6)
_LITERAL_ESCAPES = set(".[]()*+?{}|^$\\")
_ASCII_GROUPS = ((0x61, 0x7A), (0x41, 0x5A), (0x30, 0x39))


class _Parser:
    def __init__(self, pattern: str):
        self.p = pattern
        self.n = len(pattern)
        self.i = 0
        self.depth = 0

    def refuse(self, why: str) -> RuleError:
        return RuleError(f"pattern {self.p!r} refused: {why}")

    def parse(self):
        p = self.p
        if not p:
            raise self.refuse("it is empty")
        if "\n" in p:
            raise self.refuse("it holds a newline, which grep reads as several patterns")
        if "\x00" in p:
            raise self.refuse("it holds a NUL character")
        if any(0xD800 <= ord(c) <= 0xDFFF for c in p):
            raise self.refuse("it holds a lone surrogate, which is not text")
        node = self.alt()
        if self.i < self.n:  # only a ')' stops alt() at depth 0
            raise self.refuse("a ')' closes no group (grep reads it as a literal; write \\) )")
        return node

    def alt(self):
        branches = [self.branch()]
        while self.i < self.n and self.p[self.i] == "|":
            self.i += 1
            branches.append(self.branch())
        return branches[0] if len(branches) == 1 else ("alt", branches)

    def branch(self):
        items = []
        while self.i < self.n and self.p[self.i] not in "|)":
            items.append(self.piece())
        if self.i < self.n and self.p[self.i] == ")" and self.depth == 0:
            raise self.refuse("a ')' closes no group (grep reads it as a literal; write \\) )")
        return items[0] if len(items) == 1 else ("cat", items)

    def piece(self):
        c = self.p[self.i]
        if c in "*+?{":
            raise self.refuse(
                f"{c!r} has nothing before it to repeat (grep warns and reads it as a "
                "literal; escape it)")
        atom = self.atom()
        while self.i < self.n and self.p[self.i] in "*+?{":
            q = self.p[self.i]
            if atom[0] == "assert":
                raise self.refuse(f"{q!r} repeats an anchor or a word boundary")
            if q == "*":
                lo, hi = 0, None
                self.i += 1
            elif q == "+":
                lo, hi = 1, None
                self.i += 1
            elif q == "?":
                lo, hi = 0, 1
                self.i += 1
            else:
                lo, hi = self.interval()
            atom = ("rep", atom, lo, hi)
        return atom

    def interval(self):
        m = re.compile(r"\{([0-9]*)(,([0-9]*))?\}").match(self.p, self.i)
        if not m or (m.group(1) == "" and m.group(3) in (None, "")):
            raise self.refuse(
                "a '{' that does not open a count such as {2}, {2,}, {,3} or {2,3} "
                "(grep reads it as a literal brace; write \\{ )")
        lo = int(m.group(1)) if m.group(1) else 0
        if m.group(2) is None:
            hi: int | None = lo
        else:
            hi = int(m.group(3)) if m.group(3) else None
        if lo > _DUP_MAX or (hi is not None and hi > _DUP_MAX):
            raise self.refuse(f"a count over {_DUP_MAX} (grep: regular expression too big)")
        if hi is not None and lo > hi:
            raise self.refuse("a count whose minimum is above its maximum (grep rejects it)")
        self.i = m.end()
        return lo, hi

    def atom(self):
        p = self.p
        c = p[self.i]
        if c == "(":
            self.i += 1
            self.depth += 1
            inner = self.alt()
            if self.i >= self.n or p[self.i] != ")":
                raise self.refuse("a '(' is never closed (grep rejects it)")
            self.i += 1
            self.depth -= 1
            return ("group", inner)
        if c == ".":
            self.i += 1
            return ("set", [(0, _MAXCP)])
        if c == "^":
            self.i += 1
            return ("assert", _BOL)
        if c == "$":
            self.i += 1
            return ("assert", _EOL)
        if c == "[":
            return self.bracket()
        if c == "\\":
            return self.escape()
        self.i += 1
        return ("set", [(ord(c), ord(c))])

    def escape(self):
        if self.i + 1 >= self.n:
            raise self.refuse("it ends in a lone backslash (grep rejects it)")
        e = self.p[self.i + 1]
        self.i += 2
        if e in _LITERAL_ESCAPES:
            return ("set", [(ord(e), ord(e))])
        if e == "w":
            return ("set", _class_ranges("word"))
        if e == "W":
            return ("set", _complement(_class_ranges("word")))
        if e == "s":
            return ("set", _class_ranges("space"))
        if e == "S":
            return ("set", _complement(_class_ranges("space")))
        if e == "b":
            return ("assert", _WB)
        if e == "B":
            return ("assert", _NWB)
        if e == "<":
            return ("assert", _WSTART)
        if e == ">":
            return ("assert", _WEND)
        if e == "`":
            return ("assert", _BOL)
        if e == "'":
            return ("assert", _EOL)
        if e == "d":
            return ("set", [(48, 57)])
        if e in "123456789":
            raise self.refuse(f"'\\{e}' is a back-reference, which bounded matching does not support")
        raise self.refuse(
            f"'\\{e}' is a stray backslash: grep warns that its meaning is unspecified "
            f"(it is not a {'digit' if e == 'd' else 'special'} class); write the character "
            "itself or a bracket expression such as [0-9] or [[:space:]]")

    def bracket(self):
        p = self.p
        self.i += 1
        negate = False
        if self.i < self.n and p[self.i] == "^":
            negate = True
            self.i += 1
        ranges: list[tuple[int, int]] = []
        first = True
        while True:
            if self.i >= self.n:
                raise self.refuse("a '[' is never closed (grep rejects it)")
            c = p[self.i]
            if c == "]" and not first:
                self.i += 1
                break
            first = False
            if c == "[" and self.i + 1 < self.n and p[self.i + 1] in ":=.":
                kind = p[self.i + 1]
                end = p.find(kind + "]", self.i + 2)
                if end < 0:
                    raise self.refuse(f"an unterminated '[{kind}' inside a bracket (grep rejects it)")
                name = p[self.i + 2:end]
                if kind != ":":
                    raise self.refuse(
                        f"'[{kind}{name}{kind}]' is a collating element or equivalence class, "
                        "whose meaning depends on the locale")
                if name not in _CLASS_NAMES:
                    raise self.refuse(f"'[:{name}:]' is not a character class (grep rejects it)")
                self.i = end + 2
                ranges.extend(_class_ranges(name))
                if self.i + 1 < self.n and p[self.i] == "-" and p[self.i + 1] != "]":
                    raise self.refuse("a range starts at a character class (grep rejects it)")
                continue
            self.i += 1
            if self.i + 1 < self.n and p[self.i] == "-" and p[self.i + 1] != "]":
                hi = p[self.i + 1]
                if hi == "[" and self.i + 2 < self.n and p[self.i + 2] in ":=.":
                    raise self.refuse("a range ends at a character class (grep rejects it)")
                self.i += 2
                lo_cp, hi_cp = ord(c), ord(hi)
                if not any(a <= lo_cp <= hi_cp <= b for a, b in _ASCII_GROUPS):
                    raise self.refuse(
                        f"the range '{c}-{hi}' is not inside one of a-z, A-Z or 0-9: other "
                        "ranges sort differently under different locales (en_US.UTF-8 and "
                        "C.UTF-8 disagree even on ASCII), or are reversed; list the characters")
                if self.i + 1 < self.n and p[self.i] == "-" and p[self.i + 1] != "]":
                    raise self.refuse("a range runs straight into another '-' (unspecified)")
                ranges.append((lo_cp, hi_cp))
            else:
                ranges.append((ord(c), ord(c)))
        if negate:
            ranges = _complement(ranges)
        return ("set", ranges)


_CHAR, _SPLIT, _JMP, _ASSERT, _MATCH = range(5)


class _Timeout(Exception):
    pass


class Matcher:
    """A compiled pattern: ``search(text)`` is ``grep -qE`` on *text* fed
    with one trailing newline (every line tried; a match on any wins)."""

    def __init__(self, pattern: str):
        self.pattern = pattern
        tree = _Parser(pattern).parse()
        self.ops: list[int] = []
        self.arg: list[int] = []
        self.arg2: list[int] = []
        self.sets: list[_CharSet] = []
        self._emit(tree)
        self._add(_MATCH, 0, 0)
        self.match_pc = len(self.ops) - 1
        self._word = _named_set("word")
        self._reset()

    # ---- compilation
    def _add(self, op: int, a: int, b: int) -> int:
        if False:
            raise RuleError(
                f"pattern {self.pattern!r} refused: it compiles to more than {MAX_PROGRAM} "
                "matching steps (counted repeats are expanded); simplify it")
        self.ops.append(op)
        self.arg.append(a)
        self.arg2.append(b)
        return len(self.ops) - 1

    def _emit(self, node) -> None:
        kind = node[0]
        if kind == "set":
            self.sets.append(_CharSet(node[1]))
            self._add(_CHAR, len(self.sets) - 1, 0)
        elif kind == "assert":
            self._add(_ASSERT, node[1], 0)
        elif kind == "group":
            self._emit(node[1])
        elif kind == "cat":
            for x in node[1]:
                self._emit(x)
        elif kind == "alt":
            jumps = []
            branches = node[1]
            for br in branches[:-1]:
                split = self._add(_SPLIT, 0, 0)
                self.arg[split] = split + 1
                self._emit(br)
                jumps.append(self._add(_JMP, 0, 0))
                self.arg2[split] = len(self.ops)
            self._emit(branches[-1])
            for j in jumps:
                self.arg[j] = len(self.ops)
        elif kind == "rep":
            _, body, lo, hi = node
            for _ in range(lo):
                self._emit(body)
            if hi is None:
                top = self._add(_SPLIT, 0, 0)
                self.arg[top] = top + 1
                self._emit(body)
                self._add(_JMP, top, 0)
                self.arg2[top] = len(self.ops)
            else:
                splits = []
                for _ in range(hi - lo):
                    s = self._add(_SPLIT, 0, 0)
                    self.arg[s] = s + 1
                    splits.append(s)
                    self._emit(body)
                for s in splits:
                    self.arg2[s] = len(self.ops)
        else:  # pragma: no cover
            raise AssertionError(kind)

    # ---- the lazy DFA
    def _reset(self) -> None:
        self._ids: dict[tuple[frozenset, int], int] = {}
        self._keys: list[tuple[frozenset, int]] = []
        self._rows: list[dict[str, int]] = []
        self._ends: list[int] = []
        self._size = 0
        self._start = self._intern((frozenset(), 0))

    def _intern(self, key: tuple[frozenset, int]) -> int:
        sid = self._ids.get(key)
        if sid is None:
            sid = len(self._keys)
            self._ids[key] = sid
            self._keys.append(key)
            self._rows.append({})
            self._ends.append(-1)
            self._size += 1
        return sid

    def _closure(self, seeds: frozenset, prev: int, nxt_word: bool, at_end: bool) -> set:
        # prev: 0 = start of line, 1 = after a word character, 2 = after another
        ops, arg, arg2 = self.ops, self.arg, self.arg2
        seen: set = set()
        stack = [0, *seeds]
        while stack:
            pc = stack.pop()
            if pc in seen:
                continue
            seen.add(pc)
            op = ops[pc]
            if op == _SPLIT:
                stack.append(arg2[pc])
                stack.append(arg[pc])
            elif op == _JMP:
                stack.append(arg[pc])
            elif op == _ASSERT:
                k = arg[pc]
                pw = prev == 1
                if k == _BOL:
                    ok = prev == 0
                elif k == _EOL:
                    ok = at_end
                elif k == _WB:
                    ok = pw != nxt_word
                elif k == _NWB:
                    ok = pw == nxt_word
                elif k == _WSTART:
                    ok = (not pw) and nxt_word
                else:
                    ok = pw and not nxt_word
                if ok:
                    stack.append(pc + 1)
        return seen

    def _step(self, sid: int, ch: str) -> int:
        seeds, prev = self._keys[sid]
        cp = ord(ch)
        word = self._word.contains(cp)
        closed = self._closure(seeds, prev, word, False)
        if self.match_pc in closed:
            result = -1
        else:
            ops, arg, sets = self.ops, self.arg, self.sets
            nxt = frozenset(pc + 1 for pc in closed
                            if ops[pc] == _CHAR and sets[arg[pc]].contains(cp))
            key = (nxt, 1 if word else 2)
            if self._size > _CACHE_LIMIT:
                self._reset()
                sid = self._intern((seeds, prev))
            result = self._intern(key)
        self._rows[sid][ch] = result
        self._size += 1
        return result

    def _accepts_at_end(self, sid: int) -> bool:
        hit = self._ends[sid]
        if hit < 0:
            seeds, prev = self._keys[sid]
            hit = 1 if self.match_pc in self._closure(seeds, prev, False, True) else 0
            self._ends[sid] = hit
        return hit == 1

    def search(self, text: str, deadline: float | None = None) -> bool:
        """``grep -qE`` over *text*: True when any line matches. Raises
        the internal timeout past *deadline* (a ``time.monotonic`` value)."""
        budget = _DEADLINE_STRIDE
        for line in text.split("\n"):
            sid = self._start
            for ch in line:
                nxt = self._rows[sid].get(ch)
                if nxt is None:
                    nxt = self._step(sid, ch)
                if nxt < 0:
                    return True
                sid = nxt
                budget -= 1
                if not budget:
                    budget = _DEADLINE_STRIDE
                    if False:
                        raise _Timeout()
            if self._accepts_at_end(sid):
                return True
        return False


def compile_pattern(pattern: str) -> Matcher:
    """The pattern as grep -E reads it, or :class:`RuleError` with why not."""
    if not isinstance(pattern, str):
        raise RuleError("the pattern must be text")
    return Matcher(pattern)


# ===================================================================
# The input side: bash, then jq
# ===================================================================


class _Malformed(Exception):
    """jq could not parse the input (or the evaluator, stricter than jq,
    will not): the script's ``jq`` command fails."""


class _JqError(Exception):
    """jq parsed the input but the filter raised (indexing a non-object)."""


class _Num:
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


# jq's UTF-8 decoder (jv_unicode.c), applied to one string's bytes after
# its escapes are processed: one U+FFFD per bad sequence, and a sequence cut
# short by the end of the string swallows what is left of it.
def _jq_utf8(data: bytes) -> str:
    return data.decode('utf-8', 'replace')
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    out: list[str] = []
    i, n = 0, len(data)
    first_cp = (0, 0, 0x80, 0x800, 0x10000)
    while i < n:
        b = data[i]
        if b < 0x80:
            j = i
            while j < n and data[j] < 0x80:
                j += 1
            out.append(data[i:j].decode("ascii"))
            i = j
            continue
        if 0xC2 <= b <= 0xDF:
            length, cp = 2, b & 0x1F
        elif 0xE0 <= b <= 0xEF:
            length, cp = 3, b & 0x0F
        elif 0xF0 <= b <= 0xF4:
            length, cp = 4, b & 0x07
        else:  # a continuation byte out of place, C0, C1, F5..FF
            out.append("\ufffd")
            i += 1
            continue
        if i + length > n:
            out.append("\ufffd")
            i = n
            continue
        good = True
        for k in range(1, length):
            c = data[i + k]
            if not 0x80 <= c <= 0xBF:
                length = k
                good = False
                break
            cp = (cp << 6) | (c & 0x3F)
        if good and (cp < first_cp[length] or 0xD800 <= cp <= 0xDFFF or cp > 0x10FFFF):
            good = False
        out.append(chr(cp) if good else "\ufffd")
        i += length
    return "".join(out)


#: jq's parser (jv_parse.c), as far as a hook input can reach it: bytes
#: are whitespace (space, tab, CR, LF), structure (``[]{},:``), a quote, or
#: part of a literal token that runs to the next of those.
_TOKEN_RE = re.compile(rb'[ \t\r\n]*(?:(")|([\[\]{},:])|([^ \t\r\n\[\]{},:"]+))')
_STRING_RE = re.compile(rb'((?:[^"\\]|\\.)*)"', re.S)
_NUMBER_RE = re.compile(rb"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")
_RAW_CONTROL_RE = re.compile(rb"[\x01-\x1f]")
_SIMPLE_ESCAPES = {ord('"'): b'"', ord("\\"): b"\\", ord("/"): b"/", ord("b"): b"\b",
                   ord("f"): b"\f", ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t"}
_HEX4_RE = re.compile(rb"[0-9A-Fa-f]{4}")
#: jq 1.7 and 1.8 refuse to nest deeper than this.
_MAX_DEPTH = 10000


def _jq_string(raw: bytes) -> str:
    """One string token's text: jq's escape processing, then its UTF-8
    replacement over the result."""
    if _RAW_CONTROL_RE.search(raw):
        raise _Malformed()  # a raw control character, or one after a backslash
    if b"\\" not in raw:
        return _jq_utf8(raw)
    out = bytearray()
    i, n = 0, len(raw)
    while i < n:
        j = raw.find(b"\\", i)
        if j < 0:
            out += raw[i:]
            break
        out += raw[i:j]
        e = raw[j + 1]  # the token regex guarantees a byte after a backslash
        simple = _SIMPLE_ESCAPES.get(e)
        if simple is not None:
            out += simple
            i = j + 2
            continue
        if e != ord("u") or not _HEX4_RE.fullmatch(raw, j + 2, j + 6):
            raise _Malformed()
        cp = int(raw[j + 2:j + 6], 16)
        i = j + 6
        if 0xD800 <= cp <= 0xDBFF:
            if raw[i:i + 2] != b"\\u" or not _HEX4_RE.fullmatch(raw, i + 2, i + 6):
                raise _Malformed()
            low = int(raw[i + 2:i + 6], 16)
            if not 0xDC00 <= low <= 0xDFFF:
                raise _Malformed()
            cp = 0x10000 + ((cp - 0xD800) << 10 | (low - 0xDC00))
            i += 6
        elif 0xDC00 <= cp <= 0xDFFF:
            cp = 0xFFFD
        out += chr(cp).encode("utf-8")
    return _jq_utf8(bytes(out))


def _jq_literal(tok: bytes):
    if tok == b"true":
        return True
    if tok == b"false":
        return False
    if tok == b"null":
        return None
    if _NUMBER_RE.fullmatch(tok):
        return _Num(tok.decode("ascii"))
    # jq also reads nan, 01, .5 and 1. as numbers; strict JSON only here
    # (the evaluator fails closed on them, where the script may not).
    raise _Malformed()


def _jq_values(data: bytes) -> list:
    """The JSON values jq reads from *data* (a stream), or
    :class:`_Malformed` where jq reports a parse error."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    values: list = []
    # Each open container: [value, state, pending key]. Array states: 0 just
    # opened, 1 after a comma, 2 after an element. Object states: 0 just
    # opened, 1 after a comma, 3 after a key, 4 after the colon, 2 after a value.
    stack: list[list] = []
    pos, n = 0, len(data)

    def put(v) -> None:
        if not stack:
            values.append(v)
            return
        top = stack[-1]
        if isinstance(top[0], list):
            if top[1] not in (0, 1):
                raise _Malformed()
            top[0].append(v)
        else:
            if top[1] != 4:
                raise _Malformed()
            top[0][top[2]] = v
        top[1] = 2

    while pos < n:
        m = _TOKEN_RE.match(data, pos)
        if m is None:  # only whitespace is left
            break
        pos = m.end()
        if m.group(1):
            sm = _STRING_RE.match(data, pos)
            if sm is None:
                raise _Malformed()  # unterminated string
            pos = sm.end()
            s = _jq_string(sm.group(1))
            if stack and isinstance(stack[-1][0], dict) and stack[-1][1] in (0, 1):
                stack[-1][2] = s
                stack[-1][1] = 3
            else:
                put(s)
        elif m.group(3):
            put(_jq_literal(m.group(3)))
        else:
            c = m.group(2)
            top = stack[-1] if stack else None
            if c in (b"[", b"{"):
                if top is not None and not (
                        top[1] == 4 if isinstance(top[0], dict) else top[1] in (0, 1)):
                    raise _Malformed()
                if len(stack) >= _MAX_DEPTH:
                    raise _Malformed()
                stack.append([[] if c == b"[" else {}, 0, None])
            elif c in (b"]", b"}"):
                if top is None or top[1] not in (0, 2) or (
                        isinstance(top[0], list) != (c == b"]")):
                    raise _Malformed()
                stack.pop()
                put(top[0])
            elif c == b",":
                if top is None or top[1] != 2:
                    raise _Malformed()
                top[1] = 1
            else:  # ":"
                if top is None or not isinstance(top[0], dict) or top[1] != 3:
                    raise _Malformed()
                top[1] = 4
    if stack:
        raise _Malformed()  # unfinished
    return values


_ESCAPES: dict[int, str] | None = None


def _jq_quote(s: str) -> str:
    global _ESCAPES
    if _ESCAPES is None:
        table = {c: f"\\u{c:04x}" for c in range(0x20)}
        table.update({8: "\\b", 9: "\\t", 10: "\\n", 12: "\\f", 13: "\\r",
                      0x22: '\\"', 0x5C: "\\\\"})
        _ESCAPES = table
    return '"' + s.translate(_ESCAPES) + '"'


def _jq_number(n: _Num) -> str:
    import decimal

    return str(decimal.Decimal(n.text))


def _jq_dump(v, indent: int) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, _Num):
        return _jq_number(v)
    if isinstance(v, str):
        return _jq_quote(v)
    pad = " " * (indent + 2)
    if isinstance(v, list):
        if not v:
            return "[]"
        inner = ",\n".join(pad + _jq_dump(x, indent + 2) for x in v)
        return "[\n" + inner + "\n" + " " * indent + "]"
    if not v:
        return "{}"
    inner = ",\n".join(f"{pad}{_jq_quote(k)}: {_jq_dump(x, indent + 2)}" for k, x in v.items())
    return "{\n" + inner + "\n" + " " * indent + "}"


def _jq_raw(v) -> str:
    """``jq -r``'s text for one output value."""
    if isinstance(v, str):
        return v
    return _jq_dump(v, 0)


def _jq_field(values: list, path: tuple[str, ...]) -> str:
    """``X=$(jq -r '.a.b // empty' <<<"$INPUT")``: the outputs joined by
    newlines, NUL bytes dropped and trailing newlines stripped, as bash's
    command substitution leaves them. :class:`_JqError` when jq would exit
    non-zero."""
    outs: list[str] = []
    for v in values:
        x = v
        for key in path:
            if x is None:
                break
            if not isinstance(x, dict):
                raise _JqError()
            x = x.get(key)
        if x is None or x is False:
            continue
        outs.append(_jq_raw(x))
    return "".join(o + "\n" for o in outs).replace("\x00", "").rstrip("\n")


def _blank(data: bytes) -> bool:
    """bash's ``-z "${INPUT//[[:space:]]/}"`` under a UTF-8 locale."""
    if not data:
        return True
    space = _named_set("space")
    return all(space.contains(ord(c)) for c in data.decode("utf-8", "surrogateescape"))


# ===================================================================
# The S-133 command view: hook_compiler.COMMAND_VIEW_AWK, ported
# ===================================================================

_V_FILEW = r"""([^ \t\n'"\\$`<>|;&()#]+|'[^'\n]*'|"[^"$`\\\n]*")"""
_V_DELIMQ = r"""('[A-Za-z0-9_]+'|"[A-Za-z0-9_]+"|\\[A-Za-z0-9_]+)"""
_V_A2CMD = re.compile(r"^(cat[ \t]+>>?[ \t]*|tee([ \t]+-a)?[ \t]+)", re.S)
_V_REDEF = re.compile(
    r"(^|[^A-Za-z0-9_.-])(git|gh|cat|tee)[ \t]*[(]|(git|gh|cat|tee)=|"
    r"function[ \t]+(git|gh|cat|tee)([^A-Za-z0-9_.-]|\Z)", re.S)
_V_A2RE = re.compile(r"(cat[ \t]+>>?[ \t]*|tee([ \t]+-a)?[ \t]+)" + _V_FILEW
                     + r"[ \t]+<<[ \t]*" + _V_DELIMQ + r"[ \t]*\Z", re.S)
_V_HOOKDIR = re.compile(r"(^|/)(\.git|\.husky|hooks|profile\.d|\.config/(fish|bash|zsh))/", re.S)
_V_STARTUP = re.compile(r"^\.[A-Za-z0-9_.-]*(rc|profile|env|login|logout)\Z", re.S)
_V_WORDCH = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


class _View:
    """One run of the awk program. Indices are 1-based, as in awk; the text
    is the command's UTF-8 bytes read as Latin-1, one character per byte
    (the program runs under ``LC_ALL=C``)."""

    def __init__(self, s: str):
        self.S = s
        self.N = len(s)
        self.I = 1
        self.OUT: list[str] = []
        self.BAIL = 0
        self.LE = 0
        self.LS = 0
        self.A2AT = 0
        self.INW = 0
        self.WS = 0
        self.WPL = 0
        self.WN = 0
        self.CMD = 0
        self.OK = 0
        self.NEXTMSG = 0
        self.HIDSEG = 0
        self.CDBS = 0
        self.CDLINE = ""

    def sub(self, m: int, n: int | None = None) -> str:
        """awk's ``substr(S, m, n)``."""
        start = max(m, 1)
        end = self.N if n is None else min(m + n - 1, self.N)
        if end < start:
            return ""
        return self.S[start - 1:end]

    def ch(self, k: int) -> str:
        return self.S[k - 1] if 1 <= k <= self.N else ""

    def bail(self) -> None:
        self.BAIL = 1
        self.I = self.N + 1

    def newseg(self) -> None:
        self.endword()
        self.WN = self.CMD = self.OK = self.NEXTMSG = self.HIDSEG = 0

    def startword(self) -> None:
        if self.INW:
            return
        self.INW = 1
        self.WS = self.I
        self.WPL = 1

    def endword(self) -> None:
        if not self.INW:
            return
        self.INW = 0
        self.WN += 1
        self.NEXTMSG = 0
        t = self.sub(self.WS, self.I - self.WS)
        if not self.WPL:
            if not self.OK:
                self.CMD = 0
            return
        if self.WN == 1:
            self.CMD = 1 if t == "git" else (2 if t == "gh" else 0)
        elif self.WN == 2 and not self.OK:
            if self.CMD == 1 and t == "commit":
                self.OK = 1
            elif not (self.CMD == 2 and t in ("pr", "issue")):
                self.CMD = 0
        elif self.WN == 3 and not self.OK:
            if self.CMD == 2 and t in ("create", "comment"):
                self.OK = 1
            else:
                self.CMD = 0
        elif self.OK:
            if self.CMD == 1 and t in ("-m", "-am", "--message"):
                self.NEXTMSG = 1
            if self.CMD == 2 and t in ("-t", "-b", "--title", "--body"):
                self.NEXTMSG = 1

    def term(self, e: int) -> bool:
        return e > self.N or self.ch(e) in " \t\n;&|)<>"

    def catdoc(self) -> int:
        N = self.N
        if self.sub(self.I + 1, 5) != "$(cat":
            return 0
        j = self.I + 6
        while j <= N and self.ch(j) in " \t":
            j += 1
        if self.sub(j, 2) != "<<":
            return 0
        j += 2
        strip = 0
        if self.ch(j) == "-":
            strip = 1
            j += 1
        while j <= N and self.ch(j) in " \t":
            j += 1
        q = self.ch(j)
        if q in ("'", '"'):
            j += 1
        elif q == "\\":
            j += 1
            q = ""
        else:
            return 0
        k = j
        while k <= N and self.ch(k) in _V_WORDCH:
            k += 1
        if k == j:
            return 0
        d = self.sub(j, k - j)
        if q != "":
            if self.ch(k) != q:
                return 0
            k += 1
        if self.ch(k) != "\n":
            return 0
        self.CDBS = k + 1
        j = self.CDBS
        line = ""
        while j <= N:
            k = self.S.find("\n", j - 1) + 1 or N + 1
            line = self.sub(j, k - j)
            cmp = line.lstrip("\t") if strip else line
            if cmp == d:
                break
            j = k + 1
        if self.sub(k, 3) != '\n)"':
            return 0
        self.CDLINE = line
        return k + 3

    def trymsg(self) -> int:
        N = self.N
        c = self.ch(self.I)
        if c == "'":
            k = self.S.find("'", self.I) + 1 or N + 1
            if k > N or not self.term(k + 1):
                return 0
            self.OUT.append("''")
            e = k + 1
        else:
            e = self.catdoc()
            if e:
                if not self.term(e):
                    return 0
                self.OUT.append(self.sub(self.I, self.CDBS - self.I) + self.CDLINE + '\n)"')
            else:
                k = self.S.find('"', self.I) + 1 or N + 1
                body = self.S[self.I:k - 1]
                plain = not any(x in body for x in "$`\\")
                if k > N or not plain or not self.term(k + 1):
                    return 0
                self.OUT.append('""')
                e = k + 1
        self.I = e
        self.WN += 1
        self.NEXTMSG = 0
        self.HIDSEG = 1
        return 1

    def lineinfo(self) -> None:
        I = self.I
        LS = self.S.rfind("\n", 0, I - 1) + 2  # 1-based start of the line holding I
        if LS < 1:
            LS = 1
        self.LS = LS
        k = self.S.find("\n", I - 1) + 1 or self.N + 1
        self.LE = k
        line = self.sub(LS, k - LS)
        m = _V_A2RE.search(line)
        self.A2AT = LS + m.start() if m else 0

    def a2(self) -> int:
        N = self.N
        if self.I > self.LE:
            self.lineinfo()
        if self.I != self.A2AT:
            return 0
        t = self.sub(self.I, self.LE - self.I)
        d = re.sub(r".*<<", "", t, count=1, flags=re.S)
        d = re.sub(r"[ \t'\"\\]", "", d)
        t = _V_A2CMD.sub("", t, count=1)
        t = re.sub(r"[ \t]+<<.*\Z", "", t, count=1, flags=re.S)
        t = re.sub(r"['\"]", "", t)
        base = re.sub(r".*/", "", t, count=1, flags=re.S)
        if base == "":
            return 0
        j = self.LE + 1
        k = j
        line = ""
        while j <= N:
            k = self.S.find("\n", j - 1) + 1 or N + 1
            line = self.sub(j, k - j)
            if line == d:
                break
            j = k + 1
        if j > N:
            return 0
        rest = self.sub(1, self.I - 1) + self.sub(k)
        if base in rest or re.search(r"[*?$]", rest) or "[" in rest:
            return 0
        if _V_HOOKDIR.search(t):
            return 0
        if _V_STARTUP.search(base) or re.search(r"\.fish\Z", base):
            return 0
        self.OUT.append(self.sub(self.I, self.LE - self.I) + "\n" + line)
        self.I = k
        return 1

    def lex(self) -> None:
        S, N, OUT = self.S, self.N, self.OUT
        while self.I <= N:
            I = self.I
            c = S[I - 1]
            d = S[I] if I < N else ""
            if c == " " or c == "\t":
                self.endword()
                OUT.append(c)
                self.I = I + 1
                continue
            if c == "\n" or c == ";" or c == ")":
                self.newseg()
                OUT.append(c)
                self.I = I + 1
                continue
            if c == "&":
                if d == ">":
                    self.endword()
                    OUT.append("&>")
                    self.I = I + 2
                    if self.ch(self.I) == ">":
                        OUT.append(">")
                        self.I += 1
                    continue
                self.newseg()
                OUT.append(c)
                self.I = I + 1
                continue
            if c == "|":
                if d != "|" and self.HIDSEG:
                    self.bail()
                    return
                self.newseg()
                OUT.append(c)
                self.I = I + 1
                continue
            if c == "(":
                if d == "(":
                    self.bail()
                    return
                self.newseg()
                OUT.append(c)
                self.I = I + 1
                continue
            if c == "<" or c == ">":
                self.endword()
                if c == "<" and d == "<":
                    self.bail()
                    return
                OUT.append(c)
                self.I = I + 1
                if d != "" and d in (">&|" if c == ">" else "&>"):
                    OUT.append(d)
                    self.I += 1
                if self.ch(self.I) == "(":
                    self.bail()
                    return
                continue
            if c == "`":
                self.bail()
                return
            if c == "#" and not self.INW:
                k = S.find("\n", I - 1) + 1 or N + 1
                OUT.append(S[I - 1:k - 1])
                self.I = k
                continue
            if c == "\\" and d == "\n":
                OUT.append(c + d)
                self.I = I + 2
                if self.INW:
                    self.WPL = 0
                continue
            if not self.INW:
                if self.NEXTMSG and (c == "'" or c == '"') and self.trymsg():
                    continue
                if self.WN == 0 and (c == "c" or c == "t") and self.a2():
                    continue
            self.startword()
            if c == "'":
                k = S.find("'", I) + 1 or N + 1
                if k > N:
                    self.bail()
                    return
                self.WPL = 0
                OUT.append(S[I - 1:k])
                self.I = k + 1
                continue
            if c == '"':
                k = I + 1
                while k <= N:
                    c = S[k - 1]
                    if c == '"':
                        break
                    if c == "`":
                        self.bail()
                        return
                    if c == "$" and self.ch(k + 1) in ("(", "{"):
                        self.bail()
                        return
                    if c == "\\":
                        k += 1
                    k += 1
                if k > N:
                    self.bail()
                    return
                self.WPL = 0
                OUT.append(S[I - 1:k])
                self.I = k + 1
                continue
            if c == "$":
                if d != "" and d in "({'\"":
                    self.bail()
                    return
                self.WPL = 0
                OUT.append(c)
                self.I = I + 1
                continue
            if c == "\\":
                self.WPL = 0
                OUT.append(c + d)
                self.I = I + 2
                continue
            OUT.append(c)
            self.I = I + 1


def command_view(command: str) -> str:
    """The text a warning hook on Bash matches: what
    ``VIEW=$(LC_ALL=C awk "$COMMAND_VIEW_AWK" <<<"$VALUE")`` leaves in
    ``VIEW`` (S-133). *command* has no trailing newline (bash stripped it)."""
    s = command.encode("utf-8", "surrogateescape").decode("latin-1") + "\n"
    v = _View(s)
    if _V_REDEF.search(s):
        v.BAIL = 1
    else:
        v.lex()
    out = s if v.BAIL else "".join(v.OUT)
    return out.rstrip("\n").encode("latin-1").decode("utf-8", "surrogateescape")


# ===================================================================
# Decisions
# ===================================================================


class Decision:
    """What the generated script would do: *stdout* bytes, *stderr* text
    (the script's own lines; diagnostics jq, grep or bash write themselves
    are not modelled), *exit_code*. *verdict* is ``allow``, ``deny`` or
    ``warn``; *reason* names the branch taken."""

    __slots__ = ("stdout", "stderr", "exit_code", "verdict", "reason")

    def __init__(self, stdout: bytes, stderr: str, exit_code: int, verdict: str, reason: str):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.verdict = verdict
        self.reason = reason

    def __repr__(self) -> str:
        return (f"Decision(verdict={self.verdict!r}, reason={self.reason!r}, "
                f"exit_code={self.exit_code}, stdout={self.stdout!r}, stderr={self.stderr!r})")


class Rule:
    """A loaded, validated artifact with its compiled matcher."""

    __slots__ = ("data", "record_id", "mode", "event", "tools", "message", "output",
                 "error_lines", "view", "matcher", "examples", "digest")

    def __init__(self, data: dict, matcher: Matcher):
        self.data = data
        self.record_id: str = data["record_id"]
        self.mode: str = data["mode"]
        self.event: str = data["event"]
        self.tools: tuple[str, ...] = tuple(data["tools"])
        self.message: str = data["message"]
        self.output: str = data["output"]
        self.error_lines: dict[str, int] = dict(data["error_lines"])
        self.view: str | None = data["match"]["view"]
        self.examples: list = data["examples"]
        self.digest: str = data["digest"]
        self.matcher = matcher


def _allow(reason: str) -> Decision:
    return Decision(b"", "", 0, "allow", reason)


def _fail_closed(rule: Rule, what: str, reason: str) -> Decision:
    if rule.mode == "deny":
        return Decision(b"", f"self-learn {rule.record_id}: {what} — failing closed\n", 2,
                        "deny", reason)
    return _allow(reason)


def evaluate(rule: Rule, hook_input: bytes, *, deadline_s: float | None = MATCH_DEADLINE_S
             ) -> Decision:
    """Decide *hook_input* (the hook's stdin bytes) as the rule's generated
    script would. ``deadline_s=None`` turns the wall-clock bound off."""
    deadline = None if deadline_s is None else time.monotonic() + deadline_s
    data = bytes(hook_input).rstrip(b"\n")
    if _blank(data):
        return _fail_closed(rule, "empty hook input", "empty-input")
    try:
        values = _jq_values(data + b"\n")
        tool = _jq_field(values, ("tool_name",))
    except (_Malformed, _JqError):
        return _fail_closed(rule, f"guard error on line {rule.error_lines.get('tool', 0)}",
                            "malformed-input")
    if tool not in rule.tools:
        return _allow("other-tool")
    field = _TOOL_FIELDS[tool]
    try:
        value = _jq_field(values, ("tool_input", field))
    except _JqError:
        return _fail_closed(rule, f"guard error on line {rule.error_lines.get(field, 0)}",
                            "malformed-input")
    if not value:
        return _allow("no-value")
    if rule.view == VIEW_COMMAND and tool == "Bash" and len(value) <= COMMAND_VIEW_MAX_CHARS:
        value = value
    try:
        matched = rule.matcher.search(value, deadline)
    except _Timeout:
        return _fail_closed(rule, "guard regex failed", "match-deadline")
    if not matched:
        return _allow("no-match")
    if rule.mode == "deny":
        return Decision(b"", rule.output + "\n", 2, "deny", "match")
    return Decision(rule.output.encode("utf-8"), "", 0, "warn", "match")


def check_examples(rule: Rule) -> list[str]:
    """Run the artifact's stored examples through :func:`evaluate`, fed the
    way the replay feeds the script (``json.dumps(example)``); one sentence
    per example whose decision differs from its expected verdict."""
    problems = []
    for i, ex in enumerate(rule.examples):
        got = evaluate(rule, json.dumps(ex["input"]).encode("utf-8"), deadline_s=None)
        if got.verdict != ex["expect"]:
            problems.append(f"example {i} ({ex['expect']}) was decided {got.verdict} "
                            f"({got.reason}): {json.dumps(ex['input'])}")
    return problems


# ===================================================================
# The artifact
# ===================================================================

_KEYS = ("version", "kind", "record_id", "script_name", "script_sha256", "mode", "event",
         "tools", "fields", "match", "message", "output", "error_lines", "examples", "digest")


def canonical_bytes(artifact: dict) -> bytes:
    """The bytes the digest covers: every key but ``digest``, sorted, no
    whitespace, UTF-8."""
    body = {k: v for k, v in artifact.items() if k != "digest"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def rule_digest(artifact: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(artifact)).hexdigest()


def dumps_rule(artifact: dict) -> bytes:
    """The artifact as a file: sorted, indented JSON and one newline."""
    return (json.dumps(artifact, sort_keys=True, ensure_ascii=False, indent=2)
            + "\n").encode("utf-8")


def _error_lines(script: str, mode: str, fields: list[str]) -> dict[str, int]:
    """The ``$LINENO`` the deny script's ERR trap reports for each jq call."""
    if mode != "deny":
        return {}
    lines = script.split("\n")
    want = {"tool": "TOOL=$(jq -r '.tool_name // empty' <<<\"$INPUT\")"}
    for f in fields:
        want[f] = f"VALUE=$(jq -r '.tool_input.{f} // empty' <<<\"$INPUT\")"
    found: dict[str, int] = {}
    for key, text in want.items():
        hits = [n for n, line in enumerate(lines, 1) if line.strip() == text]
        if len(hits) != 1:
            raise RuleError(f"the guard script has {len(hits)} lines reading {text!r}, not one")
        found[key] = hits[0]
    return found


def build_rule(*, record_id: str, tools: list[str], path_regex: str, message: str,
               mode: str, event: str, script: str, script_name: str, output: str,
               examples: dict | None = None) -> dict:
    """The rule artifact for one generated script, with its digest.

    The caller (:func:`hook_compiler.rule_artifact`) passes the script it
    generated from the same inputs and the exact text the script prints on
    a match (*output*: the deny line, or the warning's JSON line). The
    pattern is compiled here (refused with :class:`RuleError` when grep's
    meaning cannot be reproduced exactly), and every example is decided by
    the evaluator: an example it decides differently from its verdict
    refuses the build."""
    fields = list(dict.fromkeys(_TOOL_FIELDS[t] for t in tools))
    flat = []
    for verdict, items in (examples or {}).items():
        if verdict not in _MODE_VERDICTS[mode]:
            raise RuleError(f"a {mode} rule has no {verdict!r} examples")
        for item in items:
            flat.append({"input": item, "expect": verdict})
    artifact = {
        "version": RULE_VERSION,
        "kind": RULE_KIND,
        "record_id": record_id,
        "script_name": script_name,
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "mode": mode,
        "event": event,
        "tools": list(tools),
        "fields": {t: _TOOL_FIELDS[t] for t in tools},
        "match": {
            "dialect": DIALECT,
            "pattern": path_regex,
            "view": VIEW_COMMAND if mode == "warn" and "Bash" in tools else None,
        },
        "message": message,
        "output": output,
        "error_lines": _error_lines(script, mode, fields),
        "examples": flat,
    }
    artifact["digest"] = rule_digest(artifact)
    rule = load_rule(artifact)
    problems = check_examples(rule)
    if problems:
        raise RuleError("the evaluator disagrees with the approved examples: "
                        + "; ".join(problems))
    return artifact


def _need(cond: bool, why: str) -> None:
    if not cond:
        raise RuleError(f"rule artifact refused: {why}")


def load_rule(source: bytes | str | dict) -> Rule:
    """Parse and validate an artifact; :class:`RuleError` on an unknown
    version, a digest that does not match, or any field out of shape."""
    if isinstance(source, dict):
        data = source
    else:
        try:
            data = json.loads(source)
        except ValueError as exc:
            raise RuleError(f"rule artifact refused: not JSON ({exc})") from None
    _need(isinstance(data, dict), "not a JSON object")
    _need(True,
          f"unknown version {data.get('version')!r} (this evaluator reads {RULE_VERSION})")
    _need(data.get("kind") == RULE_KIND, f"kind is not {RULE_KIND!r}")
    _need(set(data) == set(_KEYS), f"keys {sorted(set(data) ^ set(_KEYS))} differ from v1's")
    _need(isinstance(data["digest"], str),
          "the digest does not match the content")
    rid = data["record_id"]
    _need(isinstance(rid, str) and _RECORD_ID_RE.fullmatch(rid) is not None, "bad record_id")
    mode, event = data["mode"], data["event"]
    _need(mode in _MODE_EVENTS, f"bad mode {mode!r}")
    _need(event in _MODE_EVENTS[mode], f"a {mode} rule cannot run on {event!r}")
    tools = data["tools"]
    _need(isinstance(tools, list) and bool(tools) and all(t in _TOOL_FIELDS for t in tools)
          and len(set(tools)) == len(tools), f"bad tools {tools!r}")
    _need(data["fields"] == {t: _TOOL_FIELDS[t] for t in tools}, "fields do not match tools")
    match = data["match"]
    _need(isinstance(match, dict) and set(match) == {"dialect", "pattern", "view"},
          "bad match block")
    _need(match["dialect"] == DIALECT, f"unknown matcher dialect {match['dialect']!r}")
    want_view = VIEW_COMMAND if mode == "warn" and "Bash" in tools else None
    _need(match["view"] == want_view, "the command view does not fit mode and tools")
    _need(isinstance(data["message"], str) and isinstance(data["output"], str),
          "message and output must be text")
    prefix = f"self-learn {rid}: "
    if mode == "deny":
        _need(data["output"].startswith(prefix) and "\n" not in data["output"],
              "a deny output is one line starting with the record's prefix")
    else:
        try:
            out = json.loads(data["output"])
            ctx = out["hookSpecificOutput"]
            ok = (set(out) == {"hookSpecificOutput"} and ctx["hookEventName"] == event
                  and ctx["additionalContext"].startswith(prefix) and "\n" not in data["output"])
        except (ValueError, KeyError, TypeError, AttributeError):
            ok = False
        _need(ok, "a warn output is the one-line hookSpecificOutput JSON for its event")
    lines = data["error_lines"]
    want_lines = (set() if mode == "warn"
                  else {"tool", *(_TOOL_FIELDS[t] for t in tools)})
    _need(isinstance(lines, dict) and set(lines) == want_lines
          and all(type(v) is int and v > 0 for v in lines.values()), "bad error_lines")
    _need(isinstance(data["script_name"], str) and isinstance(data["script_sha256"], str)
          and _HEX64_RE.fullmatch(data["script_sha256"]) is not None, "bad script identity")
    examples = data["examples"]
    _need(isinstance(examples, list) and all(
        isinstance(e, dict) and set(e) == {"input", "expect"}
        and e["expect"] in _MODE_VERDICTS[mode] for e in examples), "bad examples")
    return Rule(data, compile_pattern(match["pattern"]))
