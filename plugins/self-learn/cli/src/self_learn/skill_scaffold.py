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
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
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
    "SKILL_FRONTMATTER_ALLOWED_KEYS",
    "SKILL_FRONTMATTER_REFUSED_KEYS",
    "SKILL_NAME_MAX_CHARS",
    "SKILL_NAME_RESERVED_WORDS",
    "SKILL_NOTE_IDS",
    "SKILL_REFERENCES_DIR",
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

#: ``name``: the directory name. Anthropic's skill best practices: "Maximum
#: 64 characters".
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

#: ``name`` and ``description`` may not contain an XML tag (Anthropic: "Cannot
#: contain XML tags"). A tag is ``<`` or ``</`` straight into a letter, up to
#: the next ``>``; a bare comparison such as ``a < 5 and b > 3`` is not one.
SKILL_XML_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")

#: The one file every skill has, and the one folder for supporting files.
SKILL_ENTRY_FILE = "SKILL.md"
SKILL_REFERENCES_DIR = "references"
#: Supporting files are markdown only. No scripts, no executables, no other
#: file type.
SKILL_SUPPORT_FILE_SUFFIX = ".md"

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
RULE_FRONTMATTER_UNPARSEABLE = "frontmatter-unparseable"
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
    RULE_FRONTMATTER_UNPARSEABLE,
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

#: A markdown inline link: ``[text](target)``, target optionally in angle
#: brackets and optionally followed by a quoted title.
_MD_LINK_RE = re.compile(
    r"\[[^\]]*\]\(\s*(?:<([^>]*)>|([^)\s]+))(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)


def _shown(value: object, limit: int = 80) -> str:
    """``repr`` of an offending value, cut so a long one stays readable."""
    shown = repr(value)
    return shown if len(shown) <= limit else shown[: limit - 3] + "..."


def _read_frontmatter(text: str) -> tuple[dict[Any, Any] | None, str, str | None]:
    """``(mapping, body, problem)``. ``problem`` is a plain reason, set (and
    ``mapping`` None) when the frontmatter is absent, unterminated, not
    YAML, or not a mapping. ``body`` is the text after the frontmatter
    (the whole text when there is no readable block). The same fence rules
    and the same safe YAML loader the compilers use for ``paths:``."""
    try:
        block = _find_leading_block(text)
    except CompileError:
        return (
            None,
            text,
            "the leading '---' frontmatter block is never closed by a '---' line",
        )
    if block is None:
        return (
            None,
            text,
            "there is no frontmatter block (the file must start with a '---' line)",
        )
    inner, end = block
    body = text[end:]
    try:
        loaded = YAML(typ="safe").load(inner)
    except Exception as exc:  # any loader failure is the same refusal
        detail = " ".join(
            ln.strip() for ln in str(exc).splitlines() if ln.strip()
        )[:200]
        return (
            None,
            body,
            f"the frontmatter is not valid YAML ({detail}); put any value "
            "that contains ': ' in double quotes",
        )
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return None, body, "the frontmatter is not a mapping of keys to values"
    return loaded, body, None


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
    if "metadata" not in mapping:
        return []
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
    absolute = [p for p in value if p.startswith(("/", "~"))]
    if absolute:
        out.append(
            SkillFinding(
                RULE_PATHS_ABSOLUTE,
                "paths entries must be relative globs, but these are "
                "absolute or home-relative: " + ", ".join(_shown(p) for p in absolute),
            )
        )
    parent = [p for p in value if ".." in re.split(r"[\\/]", p)]
    if parent:
        out.append(
            SkillFinding(
                RULE_PATHS_PARENT,
                "paths entries may not climb out with '..': "
                + ", ".join(_shown(p) for p in parent),
            )
        )
    # The glob translator the rules-glob checks use (``ledger_ops``), called
    # read-only; local import because ``ledger_ops`` imports this module.
    from .ledger_ops import ProposalError, _compile_glob_pattern

    for pattern in value:
        try:
            _compile_glob_pattern(pattern)
        except ProposalError as exc:
            out.append(SkillFinding(RULE_PATHS_SHAPE, f"paths: {exc}"))
    return out


def _check_managed_section(text: str) -> list[SkillFinding]:
    """Exactly one managed section, at the end, or none. Counted the way
    ``compilers.compile_managed_text`` counts (exact marker lines), plus the
    begin prefix so a damaged marker is not mistaken for no section."""
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


def _linked_targets(body: str) -> set[str]:
    """Relative paths SKILL.md links to with a markdown inline link,
    normalised: ``./`` prefix, ``#fragment`` and ``?query`` dropped, percent
    escapes decoded. A bare mention of a path in prose is NOT a link."""
    out: set[str] = set()
    for match in _MD_LINK_RE.finditer(body):
        target = unquote(match.group(1) or match.group(2) or "")
        target = re.split(r"[#?]", target, maxsplit=1)[0]
        while target.startswith("./"):
            target = target[2:]
        if target:
            out.add(target)
    return out


def _path_is_unsafe(path: str) -> bool:
    """Not a plain relative path: empty, absolute, a backslash, a NUL, or an
    empty / ``.`` / ``..`` segment."""
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return True
    return any(seg in ("", ".", "..") for seg in path.split("/"))


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
        in_references = parts[0] == SKILL_REFERENCES_DIR and len(parts) > 1
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
        if in_references and len(parts) > 2:
            out.append(
                SkillFinding(
                    RULE_FILE_NESTED,
                    f"file {_shown(path)} is nested below "
                    f"{SKILL_REFERENCES_DIR}/; references stay one level deep "
                    f"({SKILL_REFERENCES_DIR}/<name>{SKILL_SUPPORT_FILE_SUFFIX})",
                    path,
                )
            )
        if (
            linked is not None
            and in_references
            and len(parts) == 2
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

    Every problem is collected; a draft with two faults reports both. The
    secret scan the design also requires is the writer's job, not this
    function's."""
    loaded = frozenset(n.casefold() for n in loaded_names)
    vetoed = frozenset(n.casefold() for n in vetoed_names)
    problems: list[SkillFinding] = []
    notes: list[SkillFinding] = []

    entry = files.get(SKILL_ENTRY_FILE)
    link_source: set[str] | None = None
    if entry is None:
        problems.append(
            SkillFinding(
                RULE_SKILL_MD_MISSING,
                f"there is no {SKILL_ENTRY_FILE}; every skill has one",
            )
        )
    else:
        mapping, body, fm_problem = _read_frontmatter(entry)
        link_source = _linked_targets(body)
        if mapping is None:
            problems.append(
                SkillFinding(
                    RULE_FRONTMATTER_UNPARSEABLE,
                    f"{SKILL_ENTRY_FILE} cannot be read: {fm_problem}",
                )
            )
        else:
            problems += _check_name(
                mapping.get("name", _ABSENT),
                loaded_names=loaded,
                vetoed_names=vetoed,
                expected_name=expected_name,
            )
            problems += _check_description(mapping.get("description", _ABSENT))
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
