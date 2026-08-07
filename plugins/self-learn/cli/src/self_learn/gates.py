"""U-table — Table-1, the decision table
(`docs/specs/self-learn/drafts/u-table-decision-table-spec.md` §3.1).

Pure: no filesystem, no network, no clock, no mutation of its argument.
`trace` is a proposal's `gates:` mapping, already validated by
`ledger_ops._validate_gates` (Schema-1: nine required keys, closed enums,
quote containment) — this module trusts that shape and never re-checks
it. `scope` is the record's own `scope` string (`records.py`'s `project`
/ `user` / `skill:<name>`, `_validate_scope` `:806-811`).

Its only import is `TRACE_OUTCOMES` (Set-O) from `ledger_ops` (§8-O1) —
at MODULE level, because the import cycle this creates only closes one
way (measured, §3.6/§9-X2): `ledger_ops` must import from this module
from *inside* the function that needs it, never at its own module level,
or `self-learn` fails to start in both import orders.

Rows are evaluated top-down; the first match wins (§3.1). Row ids are
normative and are referenced by the acceptance criteria and the mutation
plan — each `if`/`return` below is commented with the row id it
implements, so a one-line edit to any row is a one-line edit here too.
"""

from __future__ import annotations

from .ledger_ops import TRACE_OUTCOMES  # noqa: F401 — §3.1/§8-O1's pinned import

__all__ = [
    "e1_promote",
    "expected_outcome",
    "hook_ok",
    "load_class",
    "t3_route_taken",
]

#: §3.1's `*.fs.verdict` values that promote a load class the same way an
#: `e1` recurrence does (L2b, L6) — SILENT and COSTLY only, never
#: LOUD_CHEAP or INDETERMINATE.
_PROMOTING_FS_VERDICTS = ("SILENT", "COSTLY")


def hook_ok(trace: dict) -> bool:
    """Table-1 row H: true iff all three of `t1.field_shaped.answer`,
    `t1.separable.answer`, `t1.cost_bearing.answer` equal "yes".
    `t1.attempted` is NOT read (§6-BD2 — it records whether T1 was
    attempted, not its verdict)."""
    t1 = trace["t1"]
    return (
        t1["field_shaped"]["answer"] == "yes"
        and t1["separable"]["answer"] == "yes"
        and t1["cost_bearing"]["answer"] == "yes"
    )


def t3_route_taken(trace: dict, scope) -> bool:
    """True iff `t3.answer == "yes"` AND `scope == "skill:" + t3.owner`.
    Used both by `load_class`'s L2 branch entry and by
    `ledger_ops._validate_gates`'s scope-conditional `t4` presence rule
    (§3.2) — the one other place this predicate is load-bearing.

    `scope` is typed loosely on purpose: C2 requires a non-string scope
    (an int, a list) to degrade gracefully rather than crash, and a bare
    `==` comparison against a string is safe for any operand type."""
    t3 = trace["t3"]
    return t3["answer"] == "yes" and scope == "skill:" + t3["owner"]


def e1_promote(trace: dict) -> bool:
    """True iff `e1.sightings >= 2` AND `e1.post_demand_recurrence` is
    true."""
    e1 = trace["e1"]
    return e1["sightings"] >= 2 and bool(e1["post_demand_recurrence"])


def load_class(trace: dict, scope) -> str:
    """Table-1's `load_class(trace, scope)`: L1..L6, first match wins.

    Called directly by R-HOOK and R-FALL (`ledger_ops._validate_derivation`)
    even when a `g0` leg or `H` already decided the outcome (§3.1 note 1)
    — so this function must be total on every trace `_validate_gates`
    accepts, at every legal scope (A3b's own floor, separate from
    `expected_outcome`'s)."""
    t2 = trace["t2"]
    if t2["answer"] == "yes":
        return "PATHED"  # L1

    if t3_route_taken(trace, scope):  # L2 branch entry
        t3a = trace["t3a"]
        if t3a["depth_behind_rule"]["answer"] == "yes":
            return "DEMAND"  # L2a
        if t3a["fs"]["verdict"] in _PROMOTING_FS_VERDICTS or e1_promote(trace):
            return "SKILL"  # L2b
        return "DEMAND"  # L2c

    if trace["tn"]["answer"] == "yes":
        return "NEW_SKILL"  # L3 — deletion reddens BY EXCEPTION (§3.1 note 3):
        # falling through reads `t4`, which `_validate_gates` forces null
        # whenever `tn.answer == "yes"`.

    t4 = trace["t4"]
    if t4["depth_behind_rule"]["answer"] == "yes":
        return "DEMAND"  # L4
    if t4["conduct_mode"]["answer"] == "yes":
        return "ALWAYS"  # L5
    if t4["fs"]["verdict"] in _PROMOTING_FS_VERDICTS or e1_promote(trace):
        return "ALWAYS"  # L6
    return "DEMAND"  # otherwise


def expected_outcome(trace: dict, scope) -> str:
    """Table-1's top-level table: G1, G2, G3, H, then `load_class`. First
    match wins."""
    g0 = trace["g0"]
    if g0["reject"]["answer"] == "yes":
        return "REJECT"  # G1
    if g0["defer"]["answer"] == "yes":
        return "DEFER"  # G2
    if g0["canon"]["answer"] == "yes":
        return "GRADUATE"  # G3
    if hook_ok(trace):
        return "HOOK"  # H
    return load_class(trace, scope)
