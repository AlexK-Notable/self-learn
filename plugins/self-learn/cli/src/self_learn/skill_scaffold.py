"""T18 — the new-skill compiler's pure half (08 §8.1 New-skill pin).

Deterministic, CLI-owned templates: ``plugins/<name>/.claude-plugin/
plugin.json`` (the three-key scaffold set pinned by 08 §8.1: name /
version / description), ``skills/<name>/SKILL.md`` (frontmatter + a
managed section the ordinary compilers own from then on), and the
marketplace entry (a ``name``/``source``-shaped entry, appended exactly
once). No dependency on the plugin-dev plugin — post-hoc enrichment is a
normal session activity where plugin-dev *may* be used.

The verbs own placement, collision policy (M3-9) and commits; this
module never touches git.
"""

from __future__ import annotations

import json
import posixpath
import re
import reprlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, NamedTuple
from urllib.parse import unquote

from ruamel.yaml import YAML

from .compilers import BEGIN_MARKER, END_MARKER, CompileError, _find_leading_block
from .records import Record

__all__ = [
    "SKILL_NAME_RE",
    "SkillScaffoldError",
    "marketplace_with_entry",
    "plugin_manifest_text",
    "scaffold_description",
    "skill_md_seed",
    "validate_skill_name",
    # The skill template's checks (K1a): rules, result types, entry point.
    "SKILL_BODY_SOFT_MAX_LINES",
    "SKILL_DESCRIPTION_MAX_CHARS",
    "SKILL_ENTRY_FILE",
    "SKILL_FILE_PATH_FORBIDDEN_CHARS",
    "SKILL_FILE_PATH_FORBIDDEN_SEGMENTS",
    "SKILL_FRONTMATTER_ALLOWED_KEYS",
    "SKILL_FRONTMATTER_FENCE",
    "SKILL_FRONTMATTER_FENCE_PADDING",
    "SKILL_FRONTMATTER_FORBIDDEN_CHARS",
    "SKILL_FRONTMATTER_MAX_CHARS",
    "SKILL_FRONTMATTER_MAX_FLOW_DEPTH",
    "SKILL_FRONTMATTER_REFUSED_CLOSER",
    "SKILL_FRONTMATTER_REFUSED_KEYS",
    "SKILL_LISTING_JOINER",
    "SKILL_LISTING_MAX_CHARS",
    "SKILL_NAME_MAX_CHARS",
    "SKILL_NAME_RESERVED_WORDS",
    "SKILL_NOTE_IDS",
    "SKILL_PATHS_ABSOLUTE_PREFIXES",
    "SKILL_PATHS_PARENT_SEGMENT",
    "SKILL_REFERENCES_DIR",
    "SKILL_REFERENCES_MAX_DEPTH",
    "SKILL_RULE_IDS",
    "SKILL_RUNNER_METADATA_KEY",
    "SKILL_SUPPORT_FILE_SUFFIX",
    "SKILL_XML_TAG_RE",
    "SkillCheck",
    "SkillFinding",
    "check_skill",
]

#: Kebab names, like every plugin in the repo's marketplace.
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

SCAFFOLD_VERSION = "0.1.0"


class SkillScaffoldError(Exception):
    """A scaffold input violates the §8.1 pin."""


def validate_skill_name(name: str) -> str:
    if not name or not SKILL_NAME_RE.match(name):
        raise SkillScaffoldError(
            f"new-skill name {name!r} must be kebab-case ([a-z0-9-], "
            "starting alphanumeric) — it names the plugin dir, the skill "
            "dir, and the marketplace entry"
        )
    return name


def scaffold_description(record: Record) -> str:
    """Deterministic description seeded from the FIRST routed lesson's
    firing condition — the trigger is the activation signal Claude's
    native skill loading keys on."""
    from .ledger_ops import record_title  # local: avoids a module cycle

    title = record_title(record).rstrip(".")
    lead = f"Use when: {title}." if title else ""
    return (
        f"{lead} Scaffolded by self-learn from routed lessons; enrich the "
        "prose post-hoc (plugin-dev optional)."
    ).strip()


def plugin_manifest_text(name: str, description: str) -> str:
    """``plugin.json`` — exactly the three-key scaffold set pinned by
    08 §8.1: name, version, description."""
    data = {
        "name": name,
        "version": SCAFFOLD_VERSION,
        "description": description,
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def skill_md_seed(name: str, description: str) -> str:
    """The SKILL.md scaffold: well-formed frontmatter + a heading. The
    managed section is NOT written here — the ordinary managed-section
    compiler bootstraps its marker pair on first compile (08 §1 pin), so
    from the first route on this file behaves exactly like every other
    compile target."""
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "---\n"
        "\n"
        f"# {name}\n"
        "\n"
        "Scaffolded by self-learn (`route --dest new-skill`). Routed\n"
        "lessons live in the managed section below; authored prose added\n"
        "here survives every recompile (text outside the markers is\n"
        "never touched).\n"
    )


def marketplace_with_entry(
    raw_text: str, name: str, description: str
) -> tuple[str, bool]:
    """Append the marketplace entry for ``name`` exactly once. Returns
    (new_text, changed). The file is rewritten in the repo's own format
    (2-space JSON + trailing newline); an existing entry makes this a
    no-op.

    Only ``.plugins[].name`` and the entry shape matter to install.sh —
    no other validation is performed (the pin: don't invent checks it
    doesn't perform)."""
    try:
        data = json.loads(raw_text)
    except ValueError as exc:
        raise SkillScaffoldError(f"marketplace.json is unparseable: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise SkillScaffoldError(
            "marketplace.json has no plugins list — not a marketplace file"
        )
    if any(
        isinstance(p, dict) and p.get("name") == name for p in data["plugins"]
    ):
        return raw_text, False
    data["plugins"].append(
        {
            "name": name,
            "source": f"./plugins/{name}",
            "description": description,
            "version": SCAFFOLD_VERSION,
        }
    )
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", True


# =============================================================================
# THE SKILL TEMPLATE'S RULES  (K1a; design: D-AUTHOR §3.2 "The template
# baseline" and §3.4 "Naming")
#
# Everything below, up to the "checks" heading, IS the skill template: every
# limit, every list, every rule id. The checks read ONLY these names, and a
# later unit generates the overseer's skill example and its rules page from
# them (``overseer/formats.py``'s own rule: "every closed set is read from
# the module that enforces it"). So changing a rule is a one-line edit in
# this block -- raise a limit, add a refused frontmatter key, allow another
# key, add a reserved word -- and the check, the generated example and the
# tests' completeness guard all follow. Rule ids are stable: a caller, a
# refusal message and a test may name them, so rename one only on purpose.
# =============================================================================

#: ``name``: the directory name, kebab-case. The kebab-case rule is
#: ``SKILL_NAME_RE`` (defined at the top of this module, where
#: ``validate_skill_name`` and the rules-topic checks already read it; it is
#: referenced here, not moved). ``check_skill`` also requires a ``fullmatch``
#: of it, because its ``$`` alone lets a trailing newline through.
#:
#: Anthropic's skill best practices: "Maximum 64 characters".
SKILL_NAME_MAX_CHARS = 64

#: ``name`` may not contain any of these, in any case. Anthropic's rule:
#: "Cannot contain reserved words: "anthropic", "claude"".
SKILL_NAME_RESERVED_WORDS: tuple[str, ...] = ("anthropic", "claude")

#: ``description``: Anthropic's rule, "Maximum 1,024 characters".
SKILL_DESCRIPTION_MAX_CHARS = 1024

#: Reported as a note, never refused: Anthropic's "Keep SKILL.md body under
#: 500 lines for optimal performance". The body is everything after the
#: frontmatter, managed section included.
SKILL_BODY_SOFT_MAX_LINES = 500

#: The soft DESCRIPTION word limit is not repeated here: it is
#: ``report.DESCRIPTION_SOFT_MAX_WORDS``, read at call time so the catalogue
#: report and this check always use the same number.

#: ``description`` and ``when_to_use`` together are what the skill listing
#: shows, and Claude Code truncates that combined text at 1,536 characters
#: (D-AUTHOR §3.1, line 556: "the combined `description` and `when_to_use`
#: text is truncated at 1,536 characters in the skill listing to reduce
#: context usage"). How it joins and counts them is in Claude Code 2.1.293's
#: bundled code, read from the binary by the 2026-10-08 gate:
#: ``whenToUse ? `${description} - ${whenToUse}` : description``, cut when
#: its ``length`` exceeds 1,536 (the ``skillListingMaxDescChars`` setting).
#: JavaScript's ``length`` counts UTF-16 code units, so a character outside
#: the Basic Multilingual Plane (most emoji) counts 2. The check builds
#: that same text and counts it the same way; an empty when_to_use adds no
#: joiner, as in JavaScript.
SKILL_LISTING_MAX_CHARS = 1536
SKILL_LISTING_JOINER = " - "

#: ``name``, ``description`` and ``when_to_use`` may not contain an XML tag
#: (Anthropic: "Cannot contain XML tags"; ``when_to_use`` is listed beside
#: ``description``, so the same reason applies). Matched: ``<`` or ``</``
#: straight into a letter or ``_`` (any script) up to the next ``>``; a
#: comment opener ``<!--``; ``<![CDATA[``; ``<!DOCTYPE ...>``; ``<?...>``. A
#: bare comparison such as ``a < 5 and b > 3`` is not one, and ``<b and c>``
#: is.
SKILL_XML_TAG_RE = re.compile(
    r"</?[^\W\d][^<>]*>|<!--|<!\[CDATA\[|<![A-Za-z][^<>]*>|<\?[^<>]*>"
)

#: The one file every skill has, and the one folder for supporting files.
SKILL_ENTRY_FILE = "SKILL.md"
SKILL_REFERENCES_DIR = "references"
#: Supporting files are markdown only. No scripts, no executables, no other
#: file type.
SKILL_SUPPORT_FILE_SUFFIX = ".md"
#: How many levels a supporting file may sit below ``references/`` (the file
#: itself counts as one): ``references/x.md`` is depth 1, so
#: ``references/a/b.md`` is refused. Anthropic: "Keep references one level
#: deep from SKILL.md".
SKILL_REFERENCES_MAX_DEPTH = 1

#: A supporting file's path (a key of ``files``) may not contain any of
#: these characters or have any of these segments (split on ``/``): that
#: would be an absolute path, a path that climbs out of the skill's folder,
#: or one that is not a plain file name.
SKILL_FILE_PATH_FORBIDDEN_CHARS: tuple[str, ...] = ("\\", "\x00")
SKILL_FILE_PATH_FORBIDDEN_SEGMENTS: tuple[str, ...] = ("", ".", "..")

#: The frontmatter is read the way Claude Code reads it, or refused.
#: Claude Code 2.1.293 finds the block with ``/^---\s*\n([\s\S]*?)---\s*\n?/``:
#: the FIRST ``---`` anywhere after the opening line ends it (even mid-line,
#: even inside a quoted value), and ``...`` never does. The compilers'
#: reader (which this check also uses) ends it at the first line that is
#: exactly ``---`` or ``...``. So the check is STRICTER than both: a
#: frontmatter whose inner text contains the fence anywhere, or that is
#: closed by the refused closer, is refused, and whatever passes reads
#: identically in all three.
SKILL_FRONTMATTER_FENCE = "---"
SKILL_FRONTMATTER_REFUSED_CLOSER = "..."

#: The fence LINES. Claude Code 2.1.293 needs a literal ``\n`` right after
#: the opening ``---`` and its whitespace (``\s`` there is JavaScript's:
#: tab, line feed, vertical tab, form feed, carriage return, the Unicode
#: spaces, U+2028, U+2029 and U+FEFF). The compilers' reader splits lines
#: with Python's ``splitlines()`` and compares ``rstrip()``, which also
#: split at a lone ``\r``, ``\x0b``, ``\x0c``, ``\x1c``-``\x1e``, U+0085,
#: U+2028 and U+2029, and also strip ``\x1c``-``\x1f`` and U+0085. The
#: 2026-10-08 gate found 14 opening lines (``---`` then one of those) that
#: this check accepted and Claude Code read as NO frontmatter. So, stricter
#: than both readers: a fence line must be exactly ``---``, then only these
#: padding characters, then ``\n`` or ``\r\n`` (the closing fence may end
#: the text instead). ``---`` itself is the readers' own literal (both
#: hard-code it); ``SKILL_FRONTMATTER_FENCE`` names it for the inside check
#: and the messages.
SKILL_FRONTMATTER_FENCE_PADDING = " \t"

#: Refused anywhere from the start of SKILL.md through the closing fence:
#: every character ``splitlines()`` breaks a line at other than ``\n`` and
#: ``\r\n``, and ``\x1f``, which ``rstrip()`` strips and JavaScript does
#: not. ``"\r"`` counts only when no ``\n`` follows it (``\r\n`` line
#: endings are fine). With these gone, the compilers' reader and Claude
#: Code split the frontmatter into the same lines, and a value cannot read
#: differently because of them (U+0085 inside a plain value is a line break
#: to ruamel and an ordinary character to Claude Code).
SKILL_FRONTMATTER_FORBIDDEN_CHARS: tuple[str, ...] = (
    "\r",
    "\x0b",
    "\x0c",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x1f",
    "\x85",
    " ",
    " ",
)

#: The two caps checked BEFORE any YAML parse. ruamel's pure-Python parser
#: costs time quadratic in how deeply ``[``/``{`` collections nest (the
#: 2026-10-08 gate: 4 KB of ``[`` took about 2 s, 30 KB about 30 s), so a
#: tiny hostile draft could stall the check; with both caps the worst draft
#: that reaches the parser takes tens of milliseconds.
#:
#: The size cap, in characters of the text between the fences. A skill's
#: frontmatter carries a name (at most 64 characters), a description (at
#: most 1,024) and a when_to_use that together with it fits the 1,536-
#: character listing limit, a few ``paths`` globs and a little metadata.
#: 4,096 is about 2.7 times the listing limit: room for that text quoted
#: or folded (which can roughly double it) plus the name, paths and
#: metadata lines. Anything larger is not a skill's frontmatter.
SKILL_FRONTMATTER_MAX_CHARS = 4096
#: The flow-nesting cap. The depth is measured by a linear scan of the raw
#: text, as an upper bound: every ``[`` and ``{`` counts as one level more
#: and no ``]`` or ``}`` ever counts one less, because a closer inside a
#: quoted value (``["]", ["]", ...``) cannot be told from a real one
#: without parsing, and a scan that subtracted it would read the hundreds
#: of real levels 4 KB can hold that way as 1. Brackets in quoted text and
#: comments count too. A skill's
#: frontmatter needs only a few (``paths: [...]``, ``metadata: {...}``, a
#: brace glob), so a false refusal costs nothing.
SKILL_FRONTMATTER_MAX_FLOW_DEPTH = 32

#: ``paths`` entries: a leading character that makes a glob absolute or
#: home-relative (never fires against a project tree), and the segment that
#: climbs out. Both refused.
SKILL_PATHS_ABSOLUTE_PREFIXES: tuple[str, ...] = ("/", "~")
SKILL_PATHS_PARENT_SEGMENT = ".."

#: Frontmatter keys a draft may carry. Anything else is refused by name.
SKILL_FRONTMATTER_ALLOWED_KEYS: tuple[str, ...] = (
    "name",
    "description",
    "when_to_use",
    "paths",
    "metadata",
)

#: Keys refused by name, each with the plain reason the refusal quotes.
#: (D-AUTHOR §3.2: the first two grant or remove permissions; ``hooks``
#: registers commands, which have their own path and safety design; the rest
#: change how sessions run; none is lesson content.) A key that is neither
#: allowed nor listed here is refused too, as an unknown key. To ALLOW one of
#: these, add it to the allow-list above; the allow-list wins.
SKILL_FRONTMATTER_REFUSED_KEYS: dict[str, str] = {
    "allowed-tools": "it grants tool permissions",
    "disallowed-tools": "it removes tool permissions",
    "hooks": "it registers commands, which have their own path and safety design",
    "model": "it changes how sessions run",
    "effort": "it changes how sessions run",
    "context": "it changes how sessions run",
    "agent": "it changes how sessions run",
    "shell": "it changes how sessions run",
    "arguments": "it changes how sessions run",
}

#: ``metadata.<this key>`` is written by the runner (``authored_by``,
#: ``case``, ``created``), never by the model: a draft that carries it is
#: refused.
SKILL_RUNNER_METADATA_KEY = "self-learn"

#: The managed section is the compilers' own marker pair
#: (``compilers.BEGIN_MARKER`` / ``END_MARKER``). The begin PREFIX is what a
#: mangled marker still starts with, so a damaged marker is caught instead
#: of being mistaken for "no section".
SKILL_MANAGED_BEGIN_PREFIX = BEGIN_MARKER.split(" (", 1)[0]

# ------------------------------------------------------------------- rule ids

RULE_SKILL_MD_MISSING = "skill-md-missing"
RULE_FILE_KEY_NOT_TEXT = "file-key-not-text"
RULE_FILE_NOT_TEXT = "file-not-text"
RULE_FRONTMATTER_UNPARSEABLE = "frontmatter-unparseable"
RULE_FRONTMATTER_FENCE_LINE = "frontmatter-fence-line"
RULE_FRONTMATTER_FORBIDDEN_CHAR = "frontmatter-forbidden-character"
RULE_FRONTMATTER_CLOSED_BY_DOTS = "frontmatter-closed-by-dots"
RULE_FRONTMATTER_CONTAINS_FENCE = "frontmatter-contains-fence"
RULE_FRONTMATTER_TOO_LONG = "frontmatter-too-long"
RULE_FRONTMATTER_FLOW_TOO_DEEP = "frontmatter-flow-too-deep"
RULE_FRONTMATTER_ANCHOR = "frontmatter-anchor-alias"
RULE_FRONTMATTER_KEY_REFUSED = "frontmatter-key-refused"
RULE_FRONTMATTER_KEY_UNKNOWN = "frontmatter-key-unknown"
RULE_NAME_MISSING = "name-missing"
RULE_NAME_NOT_KEBAB = "name-not-kebab"
RULE_NAME_TOO_LONG = "name-too-long"
RULE_NAME_RESERVED_WORD = "name-reserved-word"
RULE_NAME_XML_TAG = "name-xml-tag"
RULE_NAME_COLLISION = "name-collision"
RULE_NAME_VETOED = "name-vetoed"
RULE_NAME_DIR_MISMATCH = "name-dir-mismatch"
RULE_DESCRIPTION_EMPTY = "description-empty"
RULE_DESCRIPTION_TOO_LONG = "description-too-long"
RULE_DESCRIPTION_XML_TAG = "description-xml-tag"
RULE_WHEN_TO_USE_NOT_TEXT = "when-to-use-not-text"
RULE_WHEN_TO_USE_XML_TAG = "when-to-use-xml-tag"
RULE_LISTING_TOO_LONG = "listing-text-too-long"
RULE_METADATA_NOT_MAPPING = "metadata-not-mapping"
RULE_METADATA_SELF_LEARN = "metadata-self-learn"
RULE_PATHS_SHAPE = "paths-shape"
RULE_PATHS_ABSOLUTE = "paths-absolute"
RULE_PATHS_PARENT = "paths-parent"
RULE_MANAGED_MULTIPLE = "managed-section-multiple"
RULE_MANAGED_BROKEN = "managed-section-broken"
RULE_MANAGED_NOT_LAST = "managed-section-not-last"
RULE_FILE_PATH_UNSAFE = "file-path-unsafe"
RULE_FILE_OUTSIDE_REFERENCES = "file-outside-references"
RULE_FILE_NOT_MARKDOWN = "file-not-markdown"
RULE_FILE_NESTED = "file-nested"
RULE_REFERENCE_NOT_LINKED = "reference-not-linked"

#: Problems: each REFUSES the write. The order is the order the checks run.
SKILL_RULE_IDS: tuple[str, ...] = (
    RULE_SKILL_MD_MISSING,
    RULE_FILE_KEY_NOT_TEXT,
    RULE_FILE_NOT_TEXT,
    RULE_FRONTMATTER_UNPARSEABLE,
    RULE_FRONTMATTER_FENCE_LINE,
    RULE_FRONTMATTER_FORBIDDEN_CHAR,
    RULE_FRONTMATTER_CLOSED_BY_DOTS,
    RULE_FRONTMATTER_CONTAINS_FENCE,
    RULE_FRONTMATTER_TOO_LONG,
    RULE_FRONTMATTER_FLOW_TOO_DEEP,
    RULE_FRONTMATTER_ANCHOR,
    RULE_FRONTMATTER_KEY_REFUSED,
    RULE_FRONTMATTER_KEY_UNKNOWN,
    RULE_NAME_MISSING,
    RULE_NAME_NOT_KEBAB,
    RULE_NAME_TOO_LONG,
    RULE_NAME_RESERVED_WORD,
    RULE_NAME_XML_TAG,
    RULE_NAME_COLLISION,
    RULE_NAME_VETOED,
    RULE_NAME_DIR_MISMATCH,
    RULE_DESCRIPTION_EMPTY,
    RULE_DESCRIPTION_TOO_LONG,
    RULE_DESCRIPTION_XML_TAG,
    RULE_WHEN_TO_USE_NOT_TEXT,
    RULE_WHEN_TO_USE_XML_TAG,
    RULE_LISTING_TOO_LONG,
    RULE_METADATA_NOT_MAPPING,
    RULE_METADATA_SELF_LEARN,
    RULE_PATHS_SHAPE,
    RULE_PATHS_ABSOLUTE,
    RULE_PATHS_PARENT,
    RULE_MANAGED_MULTIPLE,
    RULE_MANAGED_BROKEN,
    RULE_MANAGED_NOT_LAST,
    RULE_FILE_PATH_UNSAFE,
    RULE_FILE_OUTSIDE_REFERENCES,
    RULE_FILE_NOT_MARKDOWN,
    RULE_FILE_NESTED,
    RULE_REFERENCE_NOT_LINKED,
)

NOTE_DESCRIPTION_LONG_WORDS = "description-long-words"
NOTE_BODY_LONG_LINES = "body-long-lines"

#: Notes: reported to catalogue health, never a refusal.
SKILL_NOTE_IDS: tuple[str, ...] = (
    NOTE_DESCRIPTION_LONG_WORDS,
    NOTE_BODY_LONG_LINES,
)

# =============================================================================
# The checks. Pure: text and lists in, findings out. Nothing here writes a
# file, reads the ledger or the machine, or raises on a bad draft -- a draft
# that cannot be read is a problem in the result, not an exception.
# =============================================================================


@dataclass(frozen=True)
class SkillFinding:
    """One problem (refuses the write) or one note (reported only)."""

    #: A stable rule id from :data:`SKILL_RULE_IDS` / :data:`SKILL_NOTE_IDS`.
    rule: str
    #: A plain sentence naming the rule and the offending value.
    message: str
    #: The file it concerns, as a key of ``files``.
    path: str = SKILL_ENTRY_FILE

    def __str__(self) -> str:
        return f"{self.rule}: {self.message}"


@dataclass(frozen=True)
class SkillCheck:
    """What :func:`check_skill` found. ``problems`` refuse the write;
    ``notes`` are reported and never refuse."""

    problems: tuple[SkillFinding, ...] = ()
    notes: tuple[SkillFinding, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def problem_rules(self) -> tuple[str, ...]:
        return tuple(p.rule for p in self.problems)

    @property
    def note_rules(self) -> tuple[str, ...]:
        return tuple(n.rule for n in self.notes)


#: "No such frontmatter key", told apart from a key that is present and null.
_ABSENT: Any = object()

#: The link patterns below bound every run (``{0,999}``, the CommonMark label
#: limit) so that text of many unclosed ``[`` or ``<`` cannot make a match
#: attempt rescan the rest of the file each time (an unbounded ``[^>]*`` took
#: seconds on 50 KB).
#:
#: A markdown inline link: ``[text](target)``, target optionally in angle
#: brackets and optionally followed by a quoted title.
_MD_LINK_RE = re.compile(
    r"\[[^\]]{0,999}\]\(\s*(?:<([^>\n]{0,999})>|([^)\s]{1,999}))"
    r"(?:\s+(?:\"[^\"]{0,999}\"|'[^']{0,999}'))?\s*\)"
)
#: A link reference definition line, ``[label]: target "optional title"``.
_MD_REF_DEF_RE = re.compile(
    r"^ {0,3}\[([^\]]{1,999})\]:[ \t]*(?:<([^>\n]{0,999})>|(\S{1,999}))"
    r"(?:[ \t]+(?:\"[^\"]{0,999}\"|'[^']{0,999}'|\([^)]{0,999}\)))?[ \t]*$",
    re.MULTILINE,
)
#: ``[text][label]`` (full) and ``[label][]`` (collapsed) reference links.
_MD_REF_USE_RE = re.compile(r"\[([^\]]{0,999})\]\[([^\]]{0,999})\]")
#: ``[label]`` on its own (shortcut), not followed by ``[``, ``(`` or ``:``.
_MD_SHORTCUT_RE = re.compile(r"\[([^\]]{1,999})\](?![\[(:])")
#: ``<references/x.md>``.
_MD_AUTOLINK_RE = re.compile(r"<([^<>\s]{1,999})>")

#: How much of an offending value a sentence shows. Every value that reaches
#: a message goes through :func:`_shown` / :func:`_clip`, so a hostile or
#: huge draft cannot make the check build a huge string.
_SHOWN_LIMIT = 80
_SHOWN_ITEMS = 5

_BOUNDED_REPR = reprlib.Repr()
_BOUNDED_REPR.maxstring = _BOUNDED_REPR.maxother = _BOUNDED_REPR.maxlong = _SHOWN_LIMIT
_BOUNDED_REPR.maxlist = _BOUNDED_REPR.maxtuple = _BOUNDED_REPR.maxdict = _SHOWN_ITEMS
_BOUNDED_REPR.maxset = _BOUNDED_REPR.maxfrozenset = _SHOWN_ITEMS
_BOUNDED_REPR.maxdeque = _BOUNDED_REPR.maxarray = _SHOWN_ITEMS
_BOUNDED_REPR.maxlevel = 3


def _shown(value: object) -> str:
    """A bounded ``repr`` of an offending value: ``reprlib`` slices a string
    before it builds the repr and stops at a fixed nesting depth and item
    count, so the cost does not grow with the value. Never raises (a repr
    that fails, such as an integer too long to print, shows its type)."""
    try:
        return _BOUNDED_REPR.repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def _shown_list(items: Iterable[object]) -> str:
    """The first few items, each bounded, then how many more there were."""
    listed: list[str] = []
    more = 0
    for item in items:
        if len(listed) < _SHOWN_ITEMS:
            listed.append(_shown(item))
        else:
            more += 1
    return ", ".join(listed) + (f" (and {more} more)" if more else "")


def _clip(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


class _Frontmatter(NamedTuple):
    """What :func:`_read_frontmatter` read: ``mapping`` and ``inner`` (the
    text between the fences) when it is acceptable, ``finding`` (the one
    problem that stops the frontmatter checks) when it is not, and the
    ``body`` after the frontmatter (the whole text when there is no readable
    block)."""

    mapping: dict[Any, Any] | None
    inner: str | None
    body: str
    finding: SkillFinding | None


def _fence_line_ok(line: str, *, closing: bool) -> bool:
    """``line`` (with its line break, if it has one) is exactly ``---``, then
    only :data:`SKILL_FRONTMATTER_FENCE_PADDING`, then ``\\n`` or ``\\r\\n``;
    the closing fence may also have no line break (it ends the text)."""
    if not line.startswith("---"):
        return False
    rest = line[3:]
    if rest.endswith("\r\n"):
        rest = rest[:-2]
    elif rest.endswith("\n"):
        rest = rest[:-1]
    elif not closing:
        return False
    return rest.strip(SKILL_FRONTMATTER_FENCE_PADDING) == ""


def _first_forbidden_char(region: str) -> tuple[int, str] | None:
    """The first :data:`SKILL_FRONTMATTER_FORBIDDEN_CHARS` character in
    ``region`` and its offset (a ``\\r`` only when no ``\\n`` follows)."""
    first: tuple[int, str] | None = None
    for char in SKILL_FRONTMATTER_FORBIDDEN_CHARS:
        if char == "\r":
            lone = re.search(r"\r(?!\n)", region)
            at = lone.start() if lone else -1
        else:
            at = region.find(char)
        if at >= 0 and (first is None or at < first[0]):
            first = (at, char)
    return first


def _char_name(char: str) -> str:
    code = f"U+{ord(char):04X}"
    if char == "\r":
        return f"a carriage return ({code}) with no line feed after it"
    return f"the character {code}"


def _read_frontmatter(text: str) -> _Frontmatter:
    """Read SKILL.md's frontmatter, strictly. A refusal here stops the
    frontmatter checks (they would be about a block Claude Code does not
    read). Refused: no block, an unclosed block, a fence line that is not
    exactly ``---`` plus spaces or tabs plus a line break, a character
    the two line readers treat differently, a block closed by the refused
    closer, a block with the fence inside it, a block over either cap,
    anchors and aliases, anything that is not YAML (an unquoted ``: `` in a
    value is one), and a block that is not a mapping. Same block reader and
    same safe YAML loader the compilers use for ``paths:``; the anchor test
    reads the parser's own events, never the text. What passes, Claude Code
    reads as the same block (the property test pins this)."""

    def refuse(rule: str, message: str, body: str) -> _Frontmatter:
        return _Frontmatter(None, None, body, SkillFinding(rule, message))

    def bad_fence_line(which: str, line: str, body: str) -> _Frontmatter:
        # Both callers pass a line that starts with '---'.
        rest = line[3:].lstrip(SKILL_FRONTMATTER_FENCE_PADDING)
        shown = _shown(rest[:1]) if rest else "nothing (the text ends there)"
        return refuse(
            RULE_FRONTMATTER_FENCE_LINE,
            f"the {which} '{SKILL_FRONTMATTER_FENCE}' line must be exactly "
            f"'{SKILL_FRONTMATTER_FENCE}', then only spaces or tabs, then a "
            "line break ('\\n' or '\\r\\n'), but after the "
            f"'{SKILL_FRONTMATTER_FENCE}' and any spaces or tabs it has "
            f"{shown}; Claude Code would read the block differently or not "
            "at all",
            body,
        )

    if not text.startswith("---"):
        return refuse(
            RULE_FRONTMATTER_UNPARSEABLE,
            f"{SKILL_ENTRY_FILE} cannot be read: there is no frontmatter block "
            f"(the file must start with a '{SKILL_FRONTMATTER_FENCE}' line)",
            text,
        )
    # The opening line as Claude Code sees it: up to the first '\n'.
    first_newline = text.find("\n")
    opening = text if first_newline < 0 else text[: first_newline + 1]
    if not _fence_line_ok(opening, closing=False):
        return bad_fence_line("opening", opening, text)
    try:
        block = _find_leading_block(text)
    except CompileError:
        return refuse(
            RULE_FRONTMATTER_UNPARSEABLE,
            f"{SKILL_ENTRY_FILE} cannot be read: the leading "
            f"'{SKILL_FRONTMATTER_FENCE}' frontmatter block is never closed "
            f"by a '{SKILL_FRONTMATTER_FENCE}' line",
            text,
        )
    if block is None:  # not reached: the opening line was checked above
        return refuse(
            RULE_FRONTMATTER_UNPARSEABLE,
            f"{SKILL_ENTRY_FILE} cannot be read: there is no frontmatter block "
            f"(the file must start with a '{SKILL_FRONTMATTER_FENCE}' line)",
            text,
        )
    inner, end = block
    body = text[end:]
    # From the start of the text through the closing fence.
    region = text[:end]
    forbidden = _first_forbidden_char(region)
    if forbidden is not None:
        at, char = forbidden
        return refuse(
            RULE_FRONTMATTER_FORBIDDEN_CHAR,
            f"the frontmatter has {_char_name(char)} on line "
            f"{region.count(chr(10), 0, at) + 1}; this check and Claude Code "
            "split lines differently there, so the skill could load with a "
            "different frontmatter or none. Before the closing "
            f"'{SKILL_FRONTMATTER_FENCE}', break lines only with '\\n' or "
            "'\\r\\n' and use no other control or separator character",
            body,
        )
    # No forbidden character: every line in the region ends in '\n'
    # (or '\r\n'), so the closing line starts after the last '\n' before
    # its own.
    closing = region[region.rfind("\n", 0, len(region) - 1) + 1 :]
    if closing.strip() == SKILL_FRONTMATTER_REFUSED_CLOSER:
        return refuse(
            RULE_FRONTMATTER_CLOSED_BY_DOTS,
            f"the frontmatter is closed by a '{SKILL_FRONTMATTER_REFUSED_CLOSER}' "
            f"line; Claude Code ends the frontmatter only at "
            f"'{SKILL_FRONTMATTER_FENCE}', so the skill would load with no "
            f"frontmatter. Close it with '{SKILL_FRONTMATTER_FENCE}'",
            body,
        )
    if not _fence_line_ok(closing, closing=True):
        return bad_fence_line("closing", closing, body)
    if SKILL_FRONTMATTER_FENCE in inner:
        # Line 1 is the opening fence; the inner text starts on line 2.
        line_no = next(
            n
            for n, ln in enumerate(inner.splitlines(), start=2)
            if SKILL_FRONTMATTER_FENCE in ln
        )
        return refuse(
            RULE_FRONTMATTER_CONTAINS_FENCE,
            f"the frontmatter contains '{SKILL_FRONTMATTER_FENCE}' on line "
            f"{line_no}; Claude Code ends the frontmatter at the first "
            f"'{SKILL_FRONTMATTER_FENCE}' anywhere, even inside a value, so "
            "the skill would load cut short. Reword it",
            body,
        )
    # The caps come before ANY YAML call: they are what bounds the parser's
    # work (see SKILL_FRONTMATTER_MAX_CHARS). Both are linear scans.
    if len(inner) > SKILL_FRONTMATTER_MAX_CHARS:
        return refuse(
            RULE_FRONTMATTER_TOO_LONG,
            f"the frontmatter is {len(inner)} characters; the limit is "
            f"{SKILL_FRONTMATTER_MAX_CHARS}. A skill's frontmatter holds a "
            "name, a description, an optional when_to_use, paths and a little "
            "metadata; move anything longer into the body or a reference file",
            body,
        )
    flow_depth = inner.count("[") + inner.count("{")
    if flow_depth > SKILL_FRONTMATTER_MAX_FLOW_DEPTH:
        return refuse(
            RULE_FRONTMATTER_FLOW_TOO_DEEP,
            f"the frontmatter has {flow_depth} '[' and '{{' characters; each "
            "counts as one more level of flow nesting (a ']' or '}' inside a "
            "quoted value cannot be told from a real one without parsing), "
            f"and the limit is {SKILL_FRONTMATTER_MAX_FLOW_DEPTH}. Use fewer "
            "brackets, or block lists ('- item' lines) instead of [ ... ]",
            body,
        )
    try:
        # The events pass is here to refuse anchors and aliases as a RULE:
        # a skill has no use for them, and the parser's own events find
        # them, so an '&' or '*' inside a quoted value is not one. It is not
        # what keeps an alias bomb cheap: ruamel loads an alias as a shared
        # reference, and the bomb's cost was in building its repr, which
        # ``_shown`` bounds (the 2026-10-08 gate's mutation K-M13 ran load()
        # first and stayed fast). Syntax errors surface in this pass too.
        # Its cost, like load()'s, is bounded by the two caps above.
        anchored = any(
            getattr(event, "anchor", None) is not None
            for event in YAML(typ="safe").parse(inner)
        )
        if anchored:
            return refuse(
                RULE_FRONTMATTER_ANCHOR,
                "the frontmatter uses a YAML anchor or alias (&name or "
                "*name); a skill has no use for them, so they are refused",
                body,
            )
        loaded = YAML(typ="safe").load(inner)
    except Exception as exc:  # any parser or loader failure is the same refusal
        detail = _clip(
            " ".join(ln.strip() for ln in str(exc).splitlines() if ln.strip())
        )
        return refuse(
            RULE_FRONTMATTER_UNPARSEABLE,
            f"{SKILL_ENTRY_FILE} cannot be read: the frontmatter is not valid "
            f"YAML ({detail}); put any value that contains ': ' in double quotes",
            body,
        )
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return refuse(
            RULE_FRONTMATTER_UNPARSEABLE,
            f"{SKILL_ENTRY_FILE} cannot be read: the frontmatter is not a "
            "mapping of keys to values",
            body,
        )
    return _Frontmatter(loaded, inner, body, None)


def _check_name(
    raw: object,
    *,
    loaded_names: frozenset[str],
    vetoed_names: frozenset[str],
    expected_name: str | None,
) -> list[SkillFinding]:
    out: list[SkillFinding] = []
    if raw is _ABSENT or raw is None or (isinstance(raw, str) and not raw.strip()):
        return [
            SkillFinding(
                RULE_NAME_MISSING,
                "name is missing or empty; the skill's name is its directory "
                "name and must be given in the frontmatter",
            )
        ]
    if not isinstance(raw, str):
        return [
            SkillFinding(
                RULE_NAME_MISSING,
                f"name must be text, got {_shown(raw)}",
            )
        ]
    name = raw
    kebab_ok = False
    try:
        validate_skill_name(name)
        # ``SKILL_NAME_RE`` ends in ``$``, which also matches before a
        # trailing newline; ``fullmatch`` does not.
        kebab_ok = SKILL_NAME_RE.fullmatch(name) is not None
    except SkillScaffoldError:
        kebab_ok = False
    if not kebab_ok:
        out.append(
            SkillFinding(
                RULE_NAME_NOT_KEBAB,
                f"name {_shown(name)} must be kebab-case: lowercase letters, "
                "digits and hyphens, starting with a letter or digit",
            )
        )
    if len(name) > SKILL_NAME_MAX_CHARS:
        out.append(
            SkillFinding(
                RULE_NAME_TOO_LONG,
                f"name {_shown(name)} is {len(name)} characters; the limit "
                f"is {SKILL_NAME_MAX_CHARS}",
            )
        )
    lowered = name.casefold()
    for word in SKILL_NAME_RESERVED_WORDS:
        if word in lowered:
            out.append(
                SkillFinding(
                    RULE_NAME_RESERVED_WORD,
                    f"name {_shown(name)} contains the reserved word "
                    f"{word!r} (any case is refused)",
                )
            )
    if SKILL_XML_TAG_RE.search(name):
        out.append(
            SkillFinding(
                RULE_NAME_XML_TAG,
                f"name {_shown(name)} contains an XML tag",
            )
        )
    if lowered in loaded_names:
        out.append(
            SkillFinding(
                RULE_NAME_COLLISION,
                f"name {_shown(name)} is already the name of a skill loaded "
                "on this machine; pick a different name",
            )
        )
    if lowered in vetoed_names:
        out.append(
            SkillFinding(
                RULE_NAME_VETOED,
                f"name {_shown(name)} is on the vetoed-names list; pick a "
                "different name",
            )
        )
    if expected_name is not None and name != expected_name:
        out.append(
            SkillFinding(
                RULE_NAME_DIR_MISMATCH,
                f"name {_shown(name)} does not match the skill's directory "
                f"name {_shown(expected_name)}",
            )
        )
    return out


def _check_description(raw: object) -> list[SkillFinding]:
    if raw is _ABSENT or raw is None or (isinstance(raw, str) and not raw.strip()):
        return [
            SkillFinding(
                RULE_DESCRIPTION_EMPTY,
                "description is missing or empty; it must say what the skill "
                "does and when to use it",
            )
        ]
    if not isinstance(raw, str):
        return [
            SkillFinding(
                RULE_DESCRIPTION_EMPTY,
                f"description must be text, got {_shown(raw)}",
            )
        ]
    out: list[SkillFinding] = []
    if len(raw) > SKILL_DESCRIPTION_MAX_CHARS:
        out.append(
            SkillFinding(
                RULE_DESCRIPTION_TOO_LONG,
                f"description is {len(raw)} characters; the limit is "
                f"{SKILL_DESCRIPTION_MAX_CHARS}",
            )
        )
    found = SKILL_XML_TAG_RE.search(raw)
    if found:
        out.append(
            SkillFinding(
                RULE_DESCRIPTION_XML_TAG,
                f"description contains an XML tag, {_shown(found.group(0))}",
            )
        )
    return out


def _check_when_to_use(mapping: dict[Any, Any]) -> list[SkillFinding]:
    """``when_to_use``, when present: text and no XML tag. (Its share of
    the skill listing is :func:`_check_listing`'s.)"""
    if "when_to_use" not in mapping:
        return []
    raw = mapping["when_to_use"]
    if not isinstance(raw, str):
        return [
            SkillFinding(
                RULE_WHEN_TO_USE_NOT_TEXT,
                f"when_to_use must be text, got {_shown(raw)}",
            )
        ]
    out: list[SkillFinding] = []
    found = SKILL_XML_TAG_RE.search(raw)
    if found:
        out.append(
            SkillFinding(
                RULE_WHEN_TO_USE_XML_TAG,
                f"when_to_use contains an XML tag, {_shown(found.group(0))}",
            )
        )
    return out


def _utf16_length(text: str) -> int:
    """``text.length`` in JavaScript: UTF-16 code units. ``surrogatepass``
    counts a lone surrogate (a YAML ``"\\ud800"`` escape) as the one unit
    JavaScript counts, instead of raising."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _check_listing(mapping: dict[Any, Any]) -> list[SkillFinding]:
    """The skill listing's text, built and measured as Claude Code builds and
    measures it (:data:`SKILL_LISTING_MAX_CHARS`), with or without a
    when_to_use. A description or when_to_use that is not text is refused by
    its own rule; this one then measures what is text."""
    description = mapping.get("description")
    if not isinstance(description, str):
        return []
    when_to_use = mapping.get("when_to_use")
    joined = isinstance(when_to_use, str) and bool(when_to_use)
    listing = (
        f"{description}{SKILL_LISTING_JOINER}{when_to_use}" if joined else description
    )
    units = _utf16_length(listing)
    if units <= SKILL_LISTING_MAX_CHARS:
        return []
    parts = (
        f"the description, then {SKILL_LISTING_JOINER!r}, then the when_to_use"
        if joined
        else "the description"
    )
    return [
        SkillFinding(
            RULE_LISTING_TOO_LONG,
            f"the skill listing text ({parts}) is {units} characters as "
            "Claude Code counts them (UTF-16 units, where most emoji count "
            f"2); Claude Code cuts it after {SKILL_LISTING_MAX_CHARS}",
        )
    ]


def _check_keys(mapping: dict[Any, Any]) -> list[SkillFinding]:
    out: list[SkillFinding] = []
    for key in mapping:
        if key in SKILL_FRONTMATTER_ALLOWED_KEYS:
            continue
        if key in SKILL_FRONTMATTER_REFUSED_KEYS:
            out.append(
                SkillFinding(
                    RULE_FRONTMATTER_KEY_REFUSED,
                    f"frontmatter key {_shown(key)} is refused: "
                    f"{SKILL_FRONTMATTER_REFUSED_KEYS[key]}",
                )
            )
        else:
            out.append(
                SkillFinding(
                    RULE_FRONTMATTER_KEY_UNKNOWN,
                    f"frontmatter key {_shown(key)} is not allowed; a skill "
                    "may carry only "
                    + ", ".join(SKILL_FRONTMATTER_ALLOWED_KEYS),
                )
            )
    return out


def _check_metadata(mapping: dict[Any, Any]) -> list[SkillFinding]:
    if mapping.get("metadata") is None:
        return []  # absent, or an empty ``metadata:``: no metadata
    meta = mapping["metadata"]
    if not isinstance(meta, dict):
        return [
            SkillFinding(
                RULE_METADATA_NOT_MAPPING,
                f"metadata must be a mapping of keys to values, got {_shown(meta)}",
            )
        ]
    if SKILL_RUNNER_METADATA_KEY in meta:
        return [
            SkillFinding(
                RULE_METADATA_SELF_LEARN,
                f"metadata.{SKILL_RUNNER_METADATA_KEY} is written by the "
                "runner, never by the author; remove it from the draft",
            )
        ]
    return []


def _check_paths(mapping: dict[Any, Any]) -> list[SkillFinding]:
    if "paths" not in mapping:
        return []
    value = mapping["paths"]
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(p, str) or not p.strip() for p in value)
    ):
        return [
            SkillFinding(
                RULE_PATHS_SHAPE,
                "paths must be a non-empty list of non-empty glob strings, "
                f"got {_shown(value)}",
            )
        ]
    out: list[SkillFinding] = []
    absolute = [p for p in value if p.startswith(SKILL_PATHS_ABSOLUTE_PREFIXES)]
    if absolute:
        out.append(
            SkillFinding(
                RULE_PATHS_ABSOLUTE,
                "paths entries must be relative globs, but these are "
                "absolute or home-relative: " + _shown_list(absolute),
            )
        )
    parent = [
        p for p in value if SKILL_PATHS_PARENT_SEGMENT in re.split(r"[\\/]", p)
    ]
    if parent:
        out.append(
            SkillFinding(
                RULE_PATHS_PARENT,
                f"paths entries may not climb out with "
                f"'{SKILL_PATHS_PARENT_SEGMENT}': " + _shown_list(parent),
            )
        )
    # The glob translator the rules-glob checks use (``ledger_ops``), called
    # read-only; local import because ``ledger_ops`` imports this module.
    from .ledger_ops import ProposalError, _compile_glob_pattern

    for pattern in value:
        try:
            _compile_glob_pattern(pattern)
        except ProposalError as exc:
            out.append(SkillFinding(RULE_PATHS_SHAPE, f"paths: {_clip(str(exc))}"))
    return out


def _check_managed_section(text: str) -> list[SkillFinding]:
    """Exactly one managed section, at the end, or none. Counted the way
    ``compilers.compile_managed_text`` counts: ``str.count`` of the marker
    TEXT anywhere in the file (a substring count, not a count of whole
    lines, so a marker quoted in prose counts too). On top of that, the begin
    PREFIX is counted so a damaged begin marker is not mistaken for no
    section."""
    prefix_begins = text.count(SKILL_MANAGED_BEGIN_PREFIX)
    begins = text.count(BEGIN_MARKER)
    ends = text.count(END_MARKER)
    if prefix_begins == 0 and ends == 0:
        return []
    if prefix_begins > 1 or ends > 1:
        return [
            SkillFinding(
                RULE_MANAGED_MULTIPLE,
                f"found {prefix_begins} managed-section begin markers and "
                f"{ends} end markers; a skill carries exactly one managed "
                "section or none",
            )
        ]
    broken = SkillFinding(
        RULE_MANAGED_BROKEN,
        f"the managed section is broken: found {prefix_begins} begin marker "
        f"({begins} exactly as the compiler writes it) and {ends} end "
        "marker; the pair must be intact and begin before end",
    )
    if not (prefix_begins == begins == ends == 1):
        return [broken]
    end_at = text.index(END_MARKER)
    if end_at < text.index(BEGIN_MARKER):
        return [broken]
    if text[end_at + len(END_MARKER) :].strip():
        return [
            SkillFinding(
                RULE_MANAGED_NOT_LAST,
                "text follows the managed section's end marker; the managed "
                "section must be the last thing in SKILL.md",
            )
        ]
    return []


def _normalise_link_target(raw: str) -> str | None:
    """A link target as the file path it lands on: percent escapes decoded,
    ``#fragment`` and ``?query`` dropped, then ``posixpath.normpath`` (so
    ``./references/x.md`` and ``references/../references/x.md`` both become
    ``references/x.md``). ``None`` when nothing is left."""
    target = unquote(raw.strip())
    target = re.split(r"[#?]", target, maxsplit=1)[0]
    if not target:
        return None
    normal = posixpath.normpath(target)
    return None if normal == "." else normal


def _label(raw: str) -> str:
    """A link label as markdown matches it: case-folded, whitespace folded."""
    return " ".join(raw.split()).casefold()


def _linked_targets(body: str) -> set[str]:
    """Relative paths SKILL.md links to, each normalised
    (:func:`_normalise_link_target`). A link is an inline link
    ``[text](path)``, a reference link (``[text][n]``, ``[n][]`` or ``[n]``
    with a ``[n]: path`` definition), or an autolink ``<path>``. A bare
    mention of a path in prose, and a definition nothing uses, are NOT
    links. A link lands on a file under ``references/`` only if its
    normalised path IS that file's path."""
    raw_targets: list[str] = []
    for match in _MD_LINK_RE.finditer(body):
        raw_targets.append(match.group(1) or match.group(2) or "")
    definitions = {
        _label(m.group(1)): (m.group(2) or m.group(3) or "")
        for m in _MD_REF_DEF_RE.finditer(body)
    }
    if definitions:
        prose = _MD_REF_DEF_RE.sub("", body)
        used = [_label(m.group(2) or m.group(1)) for m in _MD_REF_USE_RE.finditer(prose)]
        used += [_label(m.group(1)) for m in _MD_SHORTCUT_RE.finditer(prose)]
        raw_targets += [definitions[label] for label in used if label in definitions]
    raw_targets += [m.group(1) for m in _MD_AUTOLINK_RE.finditer(body)]
    out: set[str] = set()
    for raw in raw_targets:
        normal = _normalise_link_target(raw)
        if normal is not None:
            out.add(normal)
    return out


def _path_is_unsafe(path: str) -> bool:
    """Not a plain relative path: it holds a forbidden character
    (:data:`SKILL_FILE_PATH_FORBIDDEN_CHARS`) or a forbidden segment
    (:data:`SKILL_FILE_PATH_FORBIDDEN_SEGMENTS`: empty, ``.``, ``..``; an
    absolute path starts with an empty segment)."""
    if any(char in path for char in SKILL_FILE_PATH_FORBIDDEN_CHARS):
        return True
    return any(seg in SKILL_FILE_PATH_FORBIDDEN_SEGMENTS for seg in path.split("/"))


def _check_support_files(
    files: Mapping[str, str], linked: set[str] | None
) -> list[SkillFinding]:
    """Every file other than SKILL.md. ``linked`` is None when there is no
    SKILL.md to be linked from, so the link rule has nothing to say."""
    out: list[SkillFinding] = []
    for path in files:
        if path == SKILL_ENTRY_FILE:
            continue
        if _path_is_unsafe(path):
            out.append(
                SkillFinding(
                    RULE_FILE_PATH_UNSAFE,
                    f"file path {_shown(path)} is not a plain relative path",
                    path,
                )
            )
            continue
        parts = path.split("/")
        depth = len(parts) - 1  # levels below the first segment
        in_references = parts[0] == SKILL_REFERENCES_DIR and depth >= 1
        is_markdown = PurePosixPath(path).suffix == SKILL_SUPPORT_FILE_SUFFIX
        if not in_references:
            out.append(
                SkillFinding(
                    RULE_FILE_OUTSIDE_REFERENCES,
                    f"file {_shown(path)} is outside {SKILL_REFERENCES_DIR}/; "
                    f"supporting files live under {SKILL_REFERENCES_DIR}/ "
                    "and nowhere else",
                    path,
                )
            )
        if not is_markdown:
            out.append(
                SkillFinding(
                    RULE_FILE_NOT_MARKDOWN,
                    f"file {_shown(path)} is not a {SKILL_SUPPORT_FILE_SUFFIX} "
                    "file; supporting files are markdown only (no scripts, "
                    "executables or other file types)",
                    path,
                )
            )
        if in_references and depth > SKILL_REFERENCES_MAX_DEPTH:
            out.append(
                SkillFinding(
                    RULE_FILE_NESTED,
                    f"file {_shown(path)} is {depth} levels below "
                    f"{SKILL_REFERENCES_DIR}/; the limit is "
                    f"{SKILL_REFERENCES_MAX_DEPTH} "
                    f"({SKILL_REFERENCES_DIR}/<name>{SKILL_SUPPORT_FILE_SUFFIX})",
                    path,
                )
            )
        if (
            linked is not None
            and in_references
            and depth <= SKILL_REFERENCES_MAX_DEPTH
            and is_markdown
            and path not in linked
        ):
            out.append(
                SkillFinding(
                    RULE_REFERENCE_NOT_LINKED,
                    f"reference {_shown(path)} is not linked from SKILL.md; "
                    f"add a markdown link such as [text]({path})",
                    path,
                )
            )
    return out


def _text_files(
    files: Mapping[Any, Any],
) -> tuple[dict[str, str], list[SkillFinding]]:
    """Keep the files that are text under a text path. A key that is not
    text, or a value that is not text (bytes, None, a number), is a problem
    and the file is left out of every other check."""
    kept: dict[str, str] = {}
    problems: list[SkillFinding] = []
    for key, value in files.items():
        if not isinstance(key, str):
            problems.append(
                SkillFinding(
                    RULE_FILE_KEY_NOT_TEXT,
                    f"a file key must be a path as text, got {_shown(key)}",
                    _shown(key),
                )
            )
        elif not isinstance(value, str):
            problems.append(
                SkillFinding(
                    RULE_FILE_NOT_TEXT,
                    f"file {_shown(key)} must hold text, got a "
                    f"{type(value).__name__}",
                    key,
                )
            )
        else:
            kept[key] = value
    return kept, problems


def check_skill(
    files: Mapping[str, str],
    *,
    loaded_names: Iterable[str],
    vetoed_names: Iterable[str],
    expected_name: str | None = None,
) -> SkillCheck:
    """Check a skill draft against the template. Pure: text and lists in,
    findings out; it writes nothing, reads no live state, and never raises
    on a bad draft (an unreadable draft is a problem in the result).

    ``files`` maps a path relative to the skill's directory (``SKILL.md``,
    ``references/x.md``) to its text. ``loaded_names`` are the names of
    skills already loaded on this machine (a draft named like one collides;
    when UPDATING a skill the caller leaves that skill's own name out) and
    ``vetoed_names`` are names that may not be used; both are compared
    without regard to case, and both are required so a caller cannot skip
    them by accident. ``expected_name``, when the caller knows the skill's
    directory name, makes a different frontmatter ``name`` a problem.

    Every problem is collected; a draft with two faults reports both. A file
    key or value that is not text is a problem too, and every offending
    value in a sentence is bounded, so a hostile draft cannot make this
    raise or build a huge string. The secret scan the design also requires
    is the writer's job, not this function's."""
    loaded = frozenset(n.casefold() for n in loaded_names)
    vetoed = frozenset(n.casefold() for n in vetoed_names)
    notes: list[SkillFinding] = []
    entry_given = SKILL_ENTRY_FILE in files  # even a non-text one
    files, problems = _text_files(files)

    entry = files.get(SKILL_ENTRY_FILE)
    link_source: set[str] | None = None
    if entry is None:
        # A SKILL.md that was given but is not text is already a problem
        # (``file-not-text``); it is not also "missing".
        if not entry_given:
            problems.append(
                SkillFinding(
                    RULE_SKILL_MD_MISSING,
                    f"there is no {SKILL_ENTRY_FILE}; every skill has one",
                )
            )
    else:
        frontmatter = _read_frontmatter(entry)
        mapping, body = frontmatter.mapping, frontmatter.body
        link_source = _linked_targets(body)
        if mapping is None:
            assert frontmatter.finding is not None
            problems.append(frontmatter.finding)
        else:
            problems += _check_name(
                mapping.get("name", _ABSENT),
                loaded_names=loaded,
                vetoed_names=vetoed,
                expected_name=expected_name,
            )
            problems += _check_description(mapping.get("description", _ABSENT))
            problems += _check_when_to_use(mapping)
            problems += _check_listing(mapping)
            problems += _check_keys(mapping)
            problems += _check_metadata(mapping)
            problems += _check_paths(mapping)
            description = mapping.get("description")
            if isinstance(description, str):
                # Read at call time: report imports ledger_ops, which
                # imports this module.
                from .report import DESCRIPTION_SOFT_MAX_WORDS

                words = len(description.split())
                if words > DESCRIPTION_SOFT_MAX_WORDS:
                    notes.append(
                        SkillFinding(
                            NOTE_DESCRIPTION_LONG_WORDS,
                            f"description is {words} words; the soft limit "
                            f"is {DESCRIPTION_SOFT_MAX_WORDS}",
                        )
                    )
        problems += _check_managed_section(entry)
        body_lines = len(body.splitlines())
        if body_lines > SKILL_BODY_SOFT_MAX_LINES:
            notes.append(
                SkillFinding(
                    NOTE_BODY_LONG_LINES,
                    f"the {SKILL_ENTRY_FILE} body is {body_lines} lines; the "
                    f"soft limit is {SKILL_BODY_SOFT_MAX_LINES}",
                )
            )
    problems += _check_support_files(files, link_source)
    return SkillCheck(tuple(problems), tuple(notes))
