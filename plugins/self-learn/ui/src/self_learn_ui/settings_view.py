"""The settings page's view model (w33-humane lane 4, S-NEXT-humane-l4).

``self-learn config get --json`` already says, per row, which ``group`` a
setting is in, its plain ``label`` and its one-sentence ``plain`` words
(``self_learn.settings_plain``). This module only arranges those rows for
the page: groups in the CLI's own order, a few presentation words (where a
value came from, "On"/"Off"), and the "Find a setting" filter. It computes
no numbers and holds no copy of the registry: a row it does not know how to
place goes in the last group rather than vanishing.
"""

from __future__ import annotations

import re
from typing import Any

from self_learn.settings import ATTENTION_CLASS_VALUES
from self_learn.settings_plain import GROUPS

#: The group a row with no (or an unknown) ``group`` falls into, so a
#: partial read or an older CLI never makes a setting disappear.
FALLBACK_GROUP = "advanced"

#: Rows of this family are shown as one table, "Where each kind of item goes".
CLASS_PREFIX = "attention.class."

#: What a person sees for each value ``attention.class.*`` accepts. Unknown
#: values (a newer CLI) show as the raw word.
_CLASS_WORDS = {
    "needs-you": "Waits for you",
    "decided": "Shows as decided",
    "silent": "Stays silent",
    "table": "Its kind's default",
}

#: Within a group, these settings come first, in this order; every other
#: row keeps the registry's order after them. Presentation only: the
#: switches a person reaches for before the safety valves.
_SHOWN_FIRST = (
    "miner.enabled",
    "overseer.enabled",
    "steward.enabled",
    "overseer.skill_writing",
    "overseer.hook_activation",
    "overseer.skill_discovery",
)

_GROUP_TITLES = {g.id: g.title for g in GROUPS}


def _source_kind(source: str) -> str:
    """``config:miner.engine`` -> ``config``; ``inactive (provider=x)`` ->
    ``inactive``. Safe to put in a CSS class name."""
    return re.split(r"[:\s(]", source, maxsplit=1)[0] or "default"


def source_words(source: str) -> str:
    """Where a value comes from, in words a person reads."""
    kind = _source_kind(source)
    return {
        "default": "Default",
        "config": "Set in config.yaml",
        "env": "Set in the environment",
        "override": "Set for this terminal only",
        "inactive": "Not in use right now",
    }.get(kind, source)


#: Words for the few enum values a read-only row would otherwise show as
#: machine words, keyed by (setting, value). Any other value shows as is.
_VALUE_WORDS = {
    ("miner.engine", "session"): "Each session on its own",
    ("miner.engine", "digest"): "All sessions as short digests",
    ("premises.rotation_per_night", "auto"): "Automatic",
}


def value_words(row: dict[str, Any]) -> str:
    """A read-only value as a person reads it."""
    value = row.get("value")
    if (row.get("name"), value) in _VALUE_WORDS:
        return _VALUE_WORDS[(str(row.get("name")), str(value))]
    if row.get("kind") == "bool":
        return "On" if value else "Off"
    if value is None or value == "":
        return "Not set"
    if value in ("on", "off"):
        return str(value).capitalize()
    return str(value)


def unit_words(name: str) -> str:
    """The unit a number is in, from the registry's own naming (``_usd``,
    ``_secs``, ``_s``); empty when the name says nothing."""
    if name.endswith("_usd"):
        return "dollars"
    if name.endswith("_secs") or name.endswith("_s"):
        return "seconds"
    return ""


def decorate(row: dict[str, Any]) -> dict[str, Any]:
    """One CLI row plus the words the page shows. The CLI's fields stay as
    they were; a row without ``label``/``plain`` (an older CLI, a test
    fixture) degrades to its key and no sentence."""
    out = dict(row)
    name = str(row.get("name", ""))
    source = str(row.get("source") or "default")
    cli_label = str(row.get("label") or name)
    label = cli_label
    plain = str(row.get("plain") or "")
    is_class = name.startswith(CLASS_PREFIX)
    if is_class and label.startswith("Inbox: "):
        label = label[len("Inbox: "):]
    out.update(
        label=label,
        plain=plain,
        dom_name=name.replace(".", "-"),
        is_class=is_class,
        # The attention kinds share one sentence, said once above their table.
        show_plain=bool(plain) and not is_class,
        source_kind=_source_kind(source),
        source_words=source_words(source),
        value_words=value_words(row),
        unit=unit_words(name),
        default_words=value_words({"kind": row.get("kind"), "value": row.get("default")}),
        class_words=_CLASS_WORDS.get(str(row.get("value")), str(row.get("value"))),
        group_title=_GROUP_TITLES.get(str(row.get("group")), ""),
    )
    # What the "Find a setting" box searches: name, plain name, the
    # sentence, the technical note and the group's heading. Lower-cased once
    # here; the page's script and the server filter below read the same string.
    out["find"] = " ".join(
        [name, cli_label, label, plain, str(row.get("description") or ""), out["group_title"]]
    ).lower()
    return out


def class_options() -> list[tuple[str, str]]:
    """The ``attention.class.*`` choices, in the registry's order, with words."""
    return [(v, _CLASS_WORDS.get(v, v)) for v in ATTENTION_CLASS_VALUES]


def _terms(query: str) -> list[str]:
    return [t for t in query.lower().split() if t]


def matches(row: dict[str, Any], terms: list[str]) -> bool:
    """Every typed word appears somewhere in the row's searchable text."""
    return all(t in row["find"] for t in terms)


def build_groups(rows: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    """The page's groups in the CLI's order. Every row is kept; with a query,
    the rows that do not match are marked ``hidden`` (so the page works the
    same with and without its script, and clearing the box in the page can
    bring them back), a group with no match is hidden, and a group with a
    match is opened."""
    terms = _terms(query)
    by_group: dict[str, list[dict[str, Any]]] = {g.id: [] for g in GROUPS}
    for row in rows:
        d = decorate(row)
        d["hidden"] = bool(terms) and not matches(d, terms)
        gid = str(d.get("group"))
        by_group.setdefault(gid if gid in by_group else FALLBACK_GROUP, []).append(d)
    groups: list[dict[str, Any]] = []
    for g in GROUPS:
        members = by_group[g.id]
        if not members:
            continue
        first = [r for n in _SHOWN_FIRST for r in members if r["name"] == n]
        rest = [r for r in members if r["name"] not in _SHOWN_FIRST]
        ordered = first + rest
        plain_rows = [r for r in ordered if not r["is_class"]]
        class_rows = [r for r in ordered if r["is_class"]]
        shown = sum(1 for r in ordered if not r["hidden"])
        groups.append(
            {
                "id": g.id,
                "title": g.title,
                "intro": g.intro,
                "folded": g.folded,
                "open": (not g.folded) or (bool(terms) and shown > 0),
                "hidden": shown == 0,
                "shown": shown,
                "count": len(ordered),
                "rows": plain_rows,
                "class_rows": class_rows,
                "classes_hidden": all(r["hidden"] for r in class_rows),
            }
        )
    return groups
