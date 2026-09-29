"""always_loaded.py — the combined test for an always-loaded line (U3b,
2026-09-28).

An always-loaded line is one Claude Code reads into EVERY session of its
scope: a `claude-md` route with no `rules` variant (the user's or a
project's CLAUDE.md, or a project's CLAUDE.local.md) -- the ALWAYS load
class of the routing doctrine (`ledger_ops._RENDER_DESTINATIONS`). A
path-scoped rule (`claude-md:rules:<topic>`) is not one: it loads only
when a matching file is read.

The user's words (2026-09-26 19:37): "add the three questions, but enmesh
them with the three tests we already have related to 'does it always have
to apply' 'does the cost of context bloat outweight the cost of missing
the lesson or failing' 'cheaper fixes aren't working'." The combined
wording below was the orchestrator's (2026-09-27 02:37, shown to the
user). **All three must hold** -- the orchestrator's decision under the
user's delegation of 2026-09-28 15:17 ("i trust you to deal with the
questions"), not a user ruling: the analyst-era check
(`ledger_ops._validate_derivation`'s R-ALWAYS-EV) accepts any ONE of its
three signals, and stays as it is until U5 retires the analyst.

The steward (and the overseer) state the evidence for each test in the
case, under ``decision.always_loaded``; the runner refuses THAT case when
a test is missing (:func:`route_problem`), never the packet.

This module imports nothing from the package at module level: `cases`
reads :data:`TESTS` to render the block, and this module reads `cases`
lazily, so neither import is circular.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

__all__ = [
    "DECISION_KEY",
    "TESTS",
    "TEST_KEYS",
    "is_always_loaded",
    "dest_is_always_loaded",
    "check_block_shape",
    "missing_tests",
    "route_problem",
    "proposal_resolver",
]

#: Where a case carries the evidence: ``decision.always_loaded``.
DECISION_KEY = "always_loaded"

#: The three tests, in order: (key the case writes, headline, what it asks).
#: The text is the combined wording; `steward-method.md` and
#: `routing-doctrine.md` carry it verbatim (checked by the suite).
TESTS: tuple[tuple[str, str, str], ...] = (
    (
        "always_applies",
        "It always has to apply.",
        "The moment can come up in any session, with nothing the agent is "
        "reading to warn it. If it only matters while a particular file is "
        "open, it is a path-tied rule or a project line, not a global one.",
    ),
    (
        "missing_costs_more",
        "Missing it costs more than carrying it.",
        "Would an agent actually act differently because of the line (if not, "
        "it is context bloat for nothing)? Could the agent cheaply find the "
        "fact on its own at that moment, from config, `--help`, or a loud "
        "error (if so, missing it costs little and it fails)? What passes is "
        "a silent failure, or one that costs real work.",
    ),
    (
        "cheaper_fixes_fail",
        "Cheaper fixes aren't working.",
        "Either it has already come back after a cheaper placement (a path "
        "rule, the shelf, a skill), or no cheaper placement can reach that "
        "moment.",
    ),
)
TEST_KEYS: tuple[str, ...] = tuple(key for key, _headline, _text in TESTS)


def is_always_loaded(destination: object, variant: object) -> bool:
    """The ALWAYS load class: `claude-md` with no variant, or `local`."""
    return destination == "claude-md" and variant in (None, "local")


def dest_is_always_loaded(dest: object) -> bool:
    """An explicit sheet ``dest`` naming an always-loaded line."""
    return dest in ("claude-md", "claude-md:local")


def check_block_shape(block: object) -> str | None:
    """What is wrong with the SHAPE of a ``decision.always_loaded`` block,
    or `None`. Completeness (all three present) is the runner's check
    (:func:`missing_tests`); the case writer checks only that what is there
    is well-formed, so every text in it is rendered and scanned."""
    if not isinstance(block, dict):
        return f"decision.{DECISION_KEY} must be a mapping of {list(TEST_KEYS)}"
    unknown = sorted(str(key) for key in block if key not in TEST_KEYS)
    if unknown:
        return f"decision.{DECISION_KEY} has unknown key(s) {unknown}; allowed: {list(TEST_KEYS)}"
    for key, entry in block.items():
        if not isinstance(entry, dict) or set(entry) - {"because", "refs"}:
            return f"decision.{DECISION_KEY}.{key} must be a mapping of because and refs"
        because = entry.get("because")
        if because is not None and not isinstance(because, str):
            return f"decision.{DECISION_KEY}.{key}.because must be text"
        refs = entry.get("refs")
        if refs is not None and (
            not isinstance(refs, list) or not all(isinstance(r, str) for r in refs)
        ):
            return f"decision.{DECISION_KEY}.{key}.refs must be a list of evidence refs"
    return None


def block_texts(block: object) -> list[str]:
    """Every free text of a block, for the case writer's secret scan and
    heading refusal."""
    if not isinstance(block, dict):
        return []
    out: list[str] = []
    for entry in block.values():
        if isinstance(entry, dict):
            if entry.get("because") is not None:
                out.append(str(entry["because"]))
            out += [str(ref) for ref in entry.get("refs") or []]
    return out


def missing_tests(case_data: dict) -> list[str]:
    """The tests *case_data* does not evidence: each needs a non-empty
    ``because`` and at least one ``refs`` entry, and every ref must be the
    ref of one of the case's own evidence items AS THE RUNNER WILL RECORD
    THEM (after `cases.split_runner_evidence` drops an item) -- a test
    resting on a dropped item has no evidence on record."""
    from . import cases

    recorded, _dropped = cases.split_runner_evidence(dict(case_data))
    available = {
        str(item.get("ref"))
        for item in recorded.get("evidence") or []
        if isinstance(item, dict)
    }
    decision = case_data.get("decision")
    block = decision.get(DECISION_KEY) if isinstance(decision, dict) else None
    if not isinstance(block, dict):
        return list(TEST_KEYS)
    missing: list[str] = []
    for key in TEST_KEYS:
        entry = block.get(key)
        if not isinstance(entry, dict):
            missing.append(key)
            continue
        because = entry.get("because")
        refs = entry.get("refs")
        if (
            not isinstance(because, str)
            or not because.strip()
            or not isinstance(refs, list)
            or not refs
            or any(str(ref) not in available for ref in refs)
        ):
            missing.append(key)
    return missing


def route_problem(
    case_data: dict,
    items: Iterable[dict],
    *,
    resolve: Callable[[str], Any] | None = None,
    label: str = "case",
) -> str | None:
    """Why the runner refuses this case, or `None`: a decided case whose
    sheet routes a lesson to an always-loaded line must evidence all three
    tests. A parked case is never applied, so it is never refused here.

    *items* are the sheet's item mappings. A ``route`` with no ``dest``
    takes the destination the lesson's proposal names; *resolve* (given
    the lesson id, returns ``(destination, variant)`` or `None`) lets the
    caller find it, so a dest-less route cannot slip past the test."""
    if case_data.get("kind") == "parked":
        return None
    routed: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("verb") != "route":
            continue
        dest = item.get("dest")
        if dest is not None:
            hit = dest_is_always_loaded(dest)
        elif resolve is not None:
            resolved = resolve(str(item.get("id")))
            hit = resolved is not None and is_always_loaded(*resolved)
        else:
            hit = False
        if hit:
            routed.append(str(item.get("id")))
    if not routed:
        return None
    missing = missing_tests(case_data)
    if not missing:
        return None
    return (
        f"{label}: routes {sorted(set(routed))} to an always-loaded line, which needs "
        f"all three tests evidenced in decision.{DECISION_KEY}; missing or without "
        f"evidence: {missing}. Each test needs `because` and `refs` naming this "
        "case's own evidence refs -- or choose a cheaper destination, or park the "
        "case (always-loaded-user-scope)"
    )


def proposal_resolver(home: Any) -> Callable[[str], tuple[object, object] | None]:
    """For a dest-less `route` item: the (destination, variant) the lesson's
    proposal sibling names -- the SAME resolver `route` itself falls back
    to (`verbs._resolve_destination`) -- or `None` when there is none."""
    from pathlib import Path

    from . import ledger_ops, verbs

    def resolve(record_id: str) -> tuple[object, object] | None:
        try:
            path = ledger_ops.find_record_path(Path(home), record_id)
            resolved = verbs._resolve_destination(path.parent.parent, record_id, None)
        except Exception:  # noqa: BLE001 -- no readable proposal: nothing to test
            return None
        return resolved.destination, resolved.variant

    return resolve
