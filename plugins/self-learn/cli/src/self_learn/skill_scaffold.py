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

from .records import Record

__all__ = [
    "SKILL_NAME_RE",
    "SkillScaffoldError",
    "marketplace_with_entry",
    "plugin_manifest_text",
    "scaffold_description",
    "skill_md_seed",
    "validate_skill_name",
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
