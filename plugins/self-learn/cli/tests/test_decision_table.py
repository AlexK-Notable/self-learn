"""U-table — the decision table as a pure module (`gates.py`) and the
recompute-and-refuse check
(`docs/specs/self-learn/drafts/u-table-decision-table-spec.md` r3).

Fixtures are LOCAL to this module (inherits U-schema's §6-D1 convention,
reiterated here): only `proposal_dict` / `hook_proposal_fields` /
`make_behavior` / `make_home` are imported from `tests/support.py`,
read-only.

Section letters (A-E) mirror the spec's §4 acceptance-criteria lettering;
each test's docstring/comment names its criterion id. The §9 enumeration
is computed ONCE, in a module-scoped fixture (`_kept_pairs`), and reused
by A3, A3b, A4 and A6 — the legality sweep alone takes several seconds;
running it four times would just slow the suite for no added coverage.
"""

from __future__ import annotations

import inspect
import itertools
import subprocess
import sys

import pytest

from self_learn import cli, gates
from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import (
    TRACE_FS_VERDICTS,
    TRACE_OUTCOMES,
    ProposalError,
    _RENDER_DESTINATIONS,
    _dump_yaml,
    _proposal_path,
    _validate_gates,
    create_record,
    find_record_path,
    is_unanalyzed,
    proposal_info,
    queue,
    read_proposal,
    stamp_proposal,
    validate_proposal,
    write_proposal,
)

from support import hook_proposal_fields, make_behavior, make_home, proposal_dict

# =========================================================================
# Fixture builders — local to this module (§6-D1). Two layers: the raw
# per-leg dict builders (_g0/_t1/_t2/...), and `_trace(**overrides)`,
# a single entry point covering both the exhaustive §9 enumeration and
# hand-crafted per-criterion fixtures.
# =========================================================================

_QUOTE = "a quote long enough to clear the eight char floor"
_ANCHOR = "sha256:0a1b2c3d4e5f"
_UNSET = object()


def _g0(reject="no", defer="no", canon="no", *, canon_target=None):
    if canon == "yes" and canon_target is None:
        canon_target = "the canon target"
    return {
        "reject": {"answer": reject, "evidence": _QUOTE if reject == "yes" else None},
        "defer": {"answer": defer, "evidence": _QUOTE if defer == "yes" else None},
        "canon": {
            "answer": canon,
            "evidence": _QUOTE if canon == "yes" else None,
            "target": canon_target,
        },
    }


def _t1(field_shaped="no", separable=None, cost_bearing=None):
    return {
        "attempted": True,
        "field_shaped": {"answer": field_shaped, "evidence": _QUOTE},
        "separable": {
            "answer": separable,
            "evidence": _QUOTE if separable is not None else None,
        },
        "cost_bearing": {
            "answer": cost_bearing,
            "evidence": _QUOTE if cost_bearing == "yes" else None,
        },
    }


def _t2(answer="no"):
    if answer == "yes":
        return {"answer": "yes", "evidence": _QUOTE, "match_path": "src/a.py"}
    return {"answer": "no", "evidence": _QUOTE, "match_path": None}


def _t3(answer="no", *, owner="alpha"):
    if answer == "yes":
        return {"answer": "yes", "owner": owner, "scan_terms": None, "roster_sha": _ANCHOR}
    return {
        "answer": "no",
        "owner": None,
        "scan_terms": ["guard", "invariant"],
        "roster_sha": _ANCHOR,
    }


def _t3a(depth_behind_rule="no", verdict="INDETERMINATE"):
    return {
        "depth_behind_rule": {
            "answer": depth_behind_rule,
            "evidence": _QUOTE if depth_behind_rule == "yes" else None,
            "target": "the t3a target" if depth_behind_rule == "yes" else None,
        },
        "fs": {"verdict": verdict, "evidence": None if verdict == "INDETERMINATE" else _QUOTE},
    }


def _tn(answer="no", *, members=None, proposed_name=None):
    if answer == "yes":
        return {
            "answer": "yes",
            "terms": [],
            "members": members if members is not None else ["lrn-aa000001", "lrn-aa000002"],
            "proposed_name": proposed_name if proposed_name is not None else "the-proposed-skill",
        }
    return {"answer": answer, "terms": [], "members": members or [], "proposed_name": proposed_name}


def _t4(depth_behind_rule="no", conduct_mode="no", verdict="INDETERMINATE"):
    return {
        "depth_behind_rule": {
            "answer": depth_behind_rule,
            "evidence": _QUOTE if depth_behind_rule == "yes" else None,
            "target": "the t4 target" if depth_behind_rule == "yes" else None,
        },
        "conduct_mode": {
            "answer": conduct_mode,
            "evidence": _QUOTE if conduct_mode == "yes" else None,
        },
        "fs": {"verdict": verdict, "evidence": None if verdict == "INDETERMINATE" else _QUOTE},
    }


def _e1(sightings=1, post_demand_recurrence=False):
    return {"sightings": sightings, "post_demand_recurrence": post_demand_recurrence}


def _trace(
    *,
    g0_reject="no",
    g0_defer="no",
    g0_canon="no",
    g0_canon_target=None,
    t1_field_shaped="no",
    t1_separable=None,
    t1_cost_bearing=None,
    t2_answer="no",
    t3_answer="no",
    t3_owner="alpha",
    t3a=_UNSET,
    tn_answer="no",
    tn_members=None,
    tn_proposed_name=None,
    t4=_UNSET,
    e1_sightings=1,
    e1_post_demand_recurrence=False,
    outcome="DEMAND",
):
    """One entry point for every hand-crafted trace in this module.
    Returns `(trace, rules_paths)` — `rules_paths` is the PROPOSAL-level
    glob list X1's positive control needs (gate N2 item 4), non-None iff
    `t2_answer == "yes"`.

    `t3a` and `t4` auto-compute their null-vs-populated shape from the
    OTHER answers wherever that shape is unambiguous without `scope`
    (mirroring `_validate_gates`'s own scope-free rule). The one case
    that IS ambiguous without `scope` — t2=no, t3=yes, tn!=yes, u-table
    §3.2's window — refuses with a clear message rather than silently
    guessing, so a test that forgets to pass `t4=` explicitly there fails
    loudly at construction, not with a confusing downstream refusal."""
    tn_is_yes = tn_answer == "yes"

    if t3a is _UNSET:
        t3a_val = _t3a("no", "INDETERMINATE") if t3_answer == "yes" else None
    elif t3a is None:
        t3a_val = None
    else:
        t3a_val = _t3a(*t3a)

    if t4 is _UNSET:
        if t2_answer == "yes" or tn_is_yes:
            t4_val = None
        elif t3_answer == "no":
            t4_val = _t4("no", "no", "INDETERMINATE")
        else:
            raise ValueError(
                "t4 is ambiguous in the t3-route free window (t2=no, "
                "t3=yes, tn!=yes) — pass t4= explicitly (None or a "
                "(depth_behind_rule, conduct_mode, verdict) tuple)"
            )
    elif t4 is None:
        t4_val = None
    else:
        t4_val = _t4(*t4)

    rules_paths = ["src/**/*.py"] if t2_answer == "yes" else None
    trace = {
        "g0": _g0(g0_reject, g0_defer, g0_canon, canon_target=g0_canon_target),
        "t1": _t1(t1_field_shaped, t1_separable, t1_cost_bearing),
        "t2": _t2(t2_answer),
        "t3": _t3(t3_answer, owner=t3_owner),
        "t3a": t3a_val,
        "t4": t4_val,
        "tn": _tn(tn_answer, members=tn_members, proposed_name=tn_proposed_name),
        "e1": _e1(e1_sightings, e1_post_demand_recurrence),
        "outcome": outcome,
    }
    return trace, rules_paths


def _legal(trace, rules_paths, scope):
    """A5's own requirement: each pinned trace must be one
    `_validate_gates` actually accepts."""
    _validate_gates({"gates": trace, "rules_paths": rules_paths}, scope=scope)


def _outcome_trace(outcome: str, scope: str):
    """A (trace, rules_paths) pair whose Table-1 derivation is exactly
    `outcome` at `scope` — used by the D-criteria, which pin Render-1's
    proposal-field checks, not the derivation itself."""
    if outcome == "HOOK":
        return _trace(
            t1_field_shaped="yes", t1_separable="yes", t1_cost_bearing="yes", outcome="HOOK"
        )
    if outcome == "ALWAYS":
        return _trace(t4=("no", "no", "COSTLY"), outcome="ALWAYS")
    if outcome == "PATHED":
        return _trace(t2_answer="yes", outcome="PATHED")
    if outcome == "SKILL":
        owner = scope.split(":", 1)[1] if scope.startswith("skill:") else "alpha"
        return _trace(
            t3_answer="yes", t3_owner=owner, t3a=("no", "COSTLY"), t4=None, outcome="SKILL"
        )
    if outcome == "DEMAND":
        return _trace(outcome="DEMAND")
    if outcome == "NEW_SKILL":
        return _trace(tn_answer="yes", outcome="NEW_SKILL")
    if outcome == "REJECT":
        return _trace(g0_reject="yes", outcome="REJECT")
    if outcome == "DEFER":
        return _trace(g0_defer="yes", outcome="DEFER")
    if outcome == "GRADUATE":
        return _trace(g0_canon="yes", outcome="GRADUATE")
    raise ValueError(outcome)


# =========================================================================
# §9's exhaustive enumeration — the oracle for legality is `_validate_gates`
# itself, called directly, never a re-implementation of the schema.
# =========================================================================

_G0_OPTIONS = list(itertools.product(("yes", "no"), repeat=3))
_T1_OPTIONS = list(itertools.product(("yes", "no"), (None, "yes", "no"), (None, "yes", "no")))
_TN_OPTIONS = ("yes", "no", "indeterminate")
_E1_OPTIONS = list(itertools.product((1, 2), (False, True)))
_SCOPES = ("user", "project", "skill:alpha", "skill:beta")


def _iter_trace_shapes():
    """§9's varied dimensions: all three g0 answers (A4 needs this —
    REJECT/DEFER/GRADUATE are unreachable without it), both t1 legs, t2,
    t3 (+ t3a conditionally on t3), tn, t4 (conditionally on t2/t3/tn,
    per the EXISTING presence rule — the scope-dependent narrowing inside
    the t3-route free window is left to `_validate_gates(scope=...)`,
    called once per scope by the caller). Fixed: `t1.attempted=True`,
    `t3.owner="alpha"`, quotes/targets/anchors, and gate N2's four
    additions (canon.target, both depth_behind_rule.targets, t2.match_path
    + a matching proposal-level rules_paths)."""
    for reject, defer, canon in _G0_OPTIONS:
        g0 = _g0(reject, defer, canon)
        for field_shaped, separable, cost_bearing in _T1_OPTIONS:
            t1 = _t1(field_shaped, separable, cost_bearing)
            for t2_answer in ("yes", "no"):
                t2 = _t2(t2_answer)
                rules_paths = ["src/**/*.py"] if t2_answer == "yes" else None
                for t3_answer in ("yes", "no"):
                    t3 = _t3(t3_answer)
                    if t3_answer == "no":
                        t3a_shapes = [None]
                    else:
                        t3a_shapes = [
                            (dbr, v) for dbr in ("yes", "no") for v in TRACE_FS_VERDICTS
                        ]
                    for t3a_shape in t3a_shapes:
                        t3a = _t3a(*t3a_shape) if t3a_shape is not None else None
                        for tn_answer in _TN_OPTIONS:
                            tn = _tn(tn_answer)
                            tn_is_yes = tn_answer == "yes"
                            if t2_answer == "yes" or tn_is_yes:
                                t4_shapes = [None]
                            elif t3_answer == "no":
                                t4_shapes = [
                                    (dbr, cm, v)
                                    for dbr in ("yes", "no")
                                    for cm in ("yes", "no")
                                    for v in TRACE_FS_VERDICTS
                                ]
                            else:  # t3=="yes", t2=="no", tn!="yes" — free window
                                t4_shapes = [None] + [
                                    (dbr, cm, v)
                                    for dbr in ("yes", "no")
                                    for cm in ("yes", "no")
                                    for v in TRACE_FS_VERDICTS
                                ]
                            for t4_shape in t4_shapes:
                                t4 = _t4(*t4_shape) if t4_shape is not None else None
                                for sightings, recurrence in _E1_OPTIONS:
                                    e1 = _e1(sightings, recurrence)
                                    yield {
                                        "g0": g0,
                                        "t1": t1,
                                        "t2": t2,
                                        "t3": t3,
                                        "t3a": t3a,
                                        "t4": t4,
                                        "tn": tn,
                                        "e1": e1,
                                        "outcome": "DEMAND",
                                    }, rules_paths


@pytest.fixture(scope="module")
def _kept_pairs():
    """Runs §9's full sweep exactly once, shared by A3/A3b/A4/A6.
    Measured on this tree: 195,840 trace shapes -> 608,256 kept /
    175,104 refused pairs, ~10s — matching the spec's own §9-X1b/§3.2
    figures to the digit."""
    pairs = []
    refused = 0
    for trace, rules_paths in _iter_trace_shapes():
        for scope in _SCOPES:
            data = {"gates": trace, "rules_paths": rules_paths}
            try:
                _validate_gates(data, scope=scope)
            except ProposalError:
                # every shape _iter_trace_shapes() yields is already
                # scope-FREE-legal by construction, so a scope-level
                # refusal can only be §3.2's window rule.
                refused += 1
                continue
            pairs.append((trace, scope))
    return pairs, refused


# =========================================================================
# A. The module
# =========================================================================


def test_a1_gates_imports_trace_outcomes_no_redeclaration():
    """A1: gates.py contains no literal outcome tuple/list/set — it
    imports TRACE_OUTCOMES from ledger_ops. Every value Table-1 can
    return is a member of ledger_ops.TRACE_OUTCOMES, checked by importing
    that name directly, not through gates. *Absent target:* if gates.py
    does not exist, this whole module fails at collection (the `from
    self_learn import ... gates` import at the top) — a loud,
    unmistakable failure, not a skip."""
    from self_learn.ledger_ops import TRACE_OUTCOMES as REAL_TRACE_OUTCOMES

    returnable = {
        "REJECT", "DEFER", "GRADUATE", "HOOK",
        "PATHED", "DEMAND", "SKILL", "NEW_SKILL", "ALWAYS",
    }
    assert returnable <= set(REAL_TRACE_OUTCOMES)

    import ast

    tree = ast.parse(inspect.getsource(gates))
    outcome_set = set(REAL_TRACE_OUTCOMES)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            literal_strs = {
                elt.value
                for elt in node.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
            assert not outcome_set <= literal_strs, (
                "gates.py re-declares Set-O as a literal collection "
                f"instead of importing TRACE_OUTCOMES: {literal_strs}"
            )


def test_a2_import_cycle_closes_both_orders():
    """A2: two subprocess runs of the project interpreter, each entering
    the ledger_ops<->gates cycle from a different side, rc asserted
    DIRECTLY from CompletedProcess.returncode, never through a pipe.
    *Broken:* a module-level `from .gates import ...` in ledger_ops.py
    makes BOTH runs exit non-zero with an ImportError naming a
    partially-initialized module (measured, §9-X2)."""
    python = sys.executable
    for module in ("self_learn.ledger_ops", "self_learn.gates"):
        result = subprocess.run(
            [python, "-c", f"import {module}"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"importing {module} first failed (rc={result.returncode}): "
            f"{result.stderr}"
        )


def test_a3_totality(_kept_pairs):
    """A3: over every (trace, scope) pair `_validate_gates` accepts,
    `expected_outcome` returns a member of TRACE_OUTCOMES and raises
    nothing. Two vacuity guards: (i) kept pairs >= 500,000 (measured
    608,256); (ii) pairs refused by §3.2's scoped rule > 100,000
    (measured 175,104) — proving the filter DISCRIMINATES rather than
    accepting everything."""
    pairs, refused = _kept_pairs
    assert len(pairs) >= 500_000, (
        f"vacuity guard (i): only {len(pairs)} kept pairs — the "
        "enumeration or legality filter may be broken"
    )
    assert refused > 100_000, (
        f"vacuity guard (ii): only {refused} refused by §3.2's scoped "
        "rule — the filter may not be discriminating at all"
    )

    crashes = []
    bad_outcomes = []
    for trace, scope in pairs:
        try:
            outcome = gates.expected_outcome(trace, scope)
        except Exception as exc:  # noqa: BLE001 — this IS the assertion
            crashes.append((scope, trace, exc))
            continue
        if outcome not in TRACE_OUTCOMES:
            bad_outcomes.append((scope, trace, outcome))

    assert not crashes, (
        f"expected_outcome raised on {len(crashes)} kept pairs; witness: "
        f"scope={crashes[0][0]!r} trace={crashes[0][1]!r} -> "
        f"{crashes[0][2]!r}"
    )
    assert not bad_outcomes, (
        f"expected_outcome returned a non-Set-O value on "
        f"{len(bad_outcomes)} pairs; witness: scope={bad_outcomes[0][0]!r} "
        f"-> {bad_outcomes[0][2]!r}"
    )


def test_a3b_load_class_totality(_kept_pairs):
    """A3b (r1 gate F5): `load_class` must be swept DIRECTLY too, with
    its own floor — sweeping `expected_outcome` alone understates the
    crash surface by 8.5x, because it returns early on G1/G2/G3/H and
    never reaches the table's fragile part, while R-FALL/R-HOOK call
    `load_class` even when a g0 leg or H fired (§3.1 note 1) — the
    production-reachable surface is `load_class`'s, not
    `expected_outcome`'s (measured, §9-X1e)."""
    pairs, refused = _kept_pairs
    assert len(pairs) >= 500_000
    assert refused > 100_000

    crashes = []
    bad_outcomes = []
    for trace, scope in pairs:
        try:
            outcome = gates.load_class(trace, scope)
        except Exception as exc:  # noqa: BLE001 — this IS the assertion
            crashes.append((scope, trace, exc))
            continue
        if outcome not in TRACE_OUTCOMES:
            bad_outcomes.append((scope, trace, outcome))

    assert not crashes, (
        f"load_class raised on {len(crashes)} kept pairs; witness: "
        f"scope={crashes[0][0]!r} trace={crashes[0][1]!r} -> "
        f"{crashes[0][2]!r}"
    )
    assert not bad_outcomes, (
        f"load_class returned a non-Set-O value on {len(bad_outcomes)} "
        f"pairs; witness: scope={bad_outcomes[0][0]!r} -> "
        f"{bad_outcomes[0][2]!r}"
    )


def test_a4_onto_every_outcome_reachable(_kept_pairs):
    """A4: SET EQUALITY (not containment) — a dead/shadowed row makes its
    outcome unreachable, and an outcome the table can emit but Set-O
    doesn't contain shows up on the other side. This is the positive
    control against a table row that can never fire; A4 is why A3's
    enumeration must vary g0 (REJECT/DEFER/GRADUATE are unreachable
    without it)."""
    pairs, _ = _kept_pairs
    reachable = {gates.expected_outcome(trace, scope) for trace, scope in pairs}
    assert reachable == set(TRACE_OUTCOMES), (
        f"symmetric difference: {reachable ^ set(TRACE_OUTCOMES)}"
    )


def test_a6_skill_is_scope_safe_by_construction(_kept_pairs):
    """A6: over the A3 enumeration, every (trace, scope) yielding SKILL
    has scope.startswith('skill:'). *Broken:* a mutation dropping the
    scope test from t3_route_taken produces SKILL at project/user scope,
    which verbs.py:930-935 refuses at route time.

    Vacuity guard: a mutation that makes SKILL UNREACHABLE (e.g.
    comparing scope against the bare owner instead of "skill:"+owner)
    would make the loop below iterate zero SKILL-producing pairs and
    pass trivially — this project's own signature defect, "a check that
    reports success when it cannot see its target at all." A4 also
    catches that shape (SKILL missing from the reachable set), but A6
    must not rely on A4 alone to avoid vacuity."""
    pairs, _ = _kept_pairs
    skill_pairs_seen = 0
    for trace, scope in pairs:
        if gates.expected_outcome(trace, scope) == "SKILL":
            skill_pairs_seen += 1
            assert scope.startswith("skill:"), (
                f"SKILL produced at non-skill scope {scope!r}: {trace!r}"
            )
    assert skill_pairs_seen > 0, (
        "vacuity guard: zero SKILL-producing pairs in the enumeration — "
        "this test cannot see its own target"
    )


# ---- A5: the golden rows, each drawn from its row's DIFFERS set -------
#
# `_ref_load_class`/`_ref_expected_outcome` are a DELIBERATE row-deleted
# re-implementation of gates.py's real functions, used ONLY to compute
# whether a candidate fixture survives deletion of its own row — never
# the system under test. `skip` names the ONE row id to treat as absent,
# falling through exactly the way deleting that row's check in gates.py
# would (§9-X1c's own measurement method, reproduced here per-fixture
# instead of over the full sweep).

_PROMOTING_FS_VERDICTS = ("SILENT", "COSTLY")


def _ref_load_class(trace, scope, *, skip=None):
    t2 = trace["t2"]
    if skip != "L1" and t2["answer"] == "yes":
        return "PATHED"
    if gates.t3_route_taken(trace, scope):
        t3a = trace["t3a"]
        if skip != "L2a" and t3a["depth_behind_rule"]["answer"] == "yes":
            return "DEMAND"
        if skip != "L2b" and (
            t3a["fs"]["verdict"] in _PROMOTING_FS_VERDICTS or gates.e1_promote(trace)
        ):
            return "SKILL"
        if skip != "L2c":
            return "DEMAND"
        # skip == "L2c": fall OUT of the L2 block entirely — §9-X1c: this
        # is exactly what deleting L2c does in gates.py (falls to L3/L4).
    if skip != "L3" and trace["tn"]["answer"] == "yes":
        return "NEW_SKILL"
    t4 = trace["t4"]
    if skip != "L4" and t4["depth_behind_rule"]["answer"] == "yes":
        return "DEMAND"
    if skip != "L5" and t4["conduct_mode"]["answer"] == "yes":
        return "ALWAYS"
    if skip != "L6" and (
        t4["fs"]["verdict"] in _PROMOTING_FS_VERDICTS or gates.e1_promote(trace)
    ):
        return "ALWAYS"
    return "DEMAND"


def _ref_expected_outcome(trace, scope, *, skip=None):
    g0 = trace["g0"]
    if skip != "G1" and g0["reject"]["answer"] == "yes":
        return "REJECT"
    if skip != "G2" and g0["defer"]["answer"] == "yes":
        return "DEFER"
    if skip != "G3" and g0["canon"]["answer"] == "yes":
        return "GRADUATE"
    if skip != "H" and gates.hook_ok(trace):
        return "HOOK"
    return _ref_load_class(trace, scope, skip=skip)


def _assert_row_pinned(row_id, real_fn, ref_fn, trace, scope):
    """A5's own requirement: a pinned fixture is only valid if deleting
    its own row changes what it produces — a DIFFERENT outcome, or an
    exception."""
    real = real_fn(trace, scope)
    try:
        mutated = ref_fn(trace, scope, skip=row_id)
    except Exception:
        return  # differs by exception (§3.1 note 3's L3/L2c shape)
    assert mutated != real, (
        f"{row_id}: fixture survives deletion of its own row — both "
        f"compute {real!r} for trace={trace!r} scope={scope!r}"
    )


def test_a5_g1_golden_row():
    # reject=yes PAIRED with defer=yes and canon=yes — G1 must win over
    # EVERY row below it, so an order mutation (M2: swap G1/G2) actually
    # changes the answer; a fixture with only reject=yes would survive
    # M2 unmodified (both orderings check "reject" and "defer" and the
    # single true flag returns the same result either way).
    trace, rp = _trace(g0_reject="yes", g0_defer="yes", g0_canon="yes", outcome="REJECT")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.expected_outcome(trace, scope)
    assert outcome == "REJECT", f"G1: {outcome!r}"
    _assert_row_pinned("G1", gates.expected_outcome, _ref_expected_outcome, trace, scope)


def test_a5_g2_golden_row():
    # defer=yes PAIRED with canon=yes (reject=no) — G2 must win over G3,
    # so M2's G1/G2 swap and any G2/G3 reordering both actually change
    # the answer for this fixture.
    trace, rp = _trace(g0_defer="yes", g0_canon="yes", outcome="DEFER")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.expected_outcome(trace, scope)
    assert outcome == "DEFER", f"G2: {outcome!r}"
    _assert_row_pinned("G2", gates.expected_outcome, _ref_expected_outcome, trace, scope)


def test_a5_g3_golden_row():
    trace, rp = _trace(g0_canon="yes", outcome="GRADUATE")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.expected_outcome(trace, scope)
    assert outcome == "GRADUATE", f"G3: {outcome!r}"
    _assert_row_pinned("G3", gates.expected_outcome, _ref_expected_outcome, trace, scope)


def test_a5_h_golden_row():
    trace, rp = _trace(
        t1_field_shaped="yes", t1_separable="yes", t1_cost_bearing="yes", outcome="HOOK"
    )
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.expected_outcome(trace, scope)
    assert outcome == "HOOK", f"H: {outcome!r}"
    _assert_row_pinned("H", gates.expected_outcome, _ref_expected_outcome, trace, scope)

    # M4's negative witness: field_shaped=yes ALONE must not fire H — all
    # three legs are required (hook_ok is an AND, not a single check).
    # The positive-only fixture above cannot detect a weakened `hook_ok`
    # that still returns True on all-yes; only a partial-yes trace can.
    partial_trace, partial_rp = _trace(
        t1_field_shaped="yes", t1_separable="no", t1_cost_bearing="no", outcome="DEMAND"
    )
    _legal(partial_trace, partial_rp, scope)
    partial_outcome = gates.expected_outcome(partial_trace, scope)
    assert partial_outcome != "HOOK", (
        f"H fired on field_shaped=yes alone (separable=no, cost_bearing=no): "
        f"{partial_outcome!r}"
    )


def test_a5_l1_golden_row():
    trace, rp = _trace(t2_answer="yes", outcome="PATHED")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "PATHED", f"L1: {outcome!r}"
    _assert_row_pinned("L1", gates.load_class, _ref_load_class, trace, scope)


def test_a5_l2a_golden_row():
    # depth_behind_rule=yes (fires L2a) PAIRED with a PROMOTING verdict,
    # so deleting L2a falls to L2b (SKILL) rather than L2c (DEMAND) — a
    # naive fixture without this pairing survives 37.5% of the time.
    trace, rp = _trace(
        t3_answer="yes", t3a=("yes", "COSTLY"), t4=None, outcome="DEMAND"
    )
    scope = "skill:alpha"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "DEMAND", f"L2a: {outcome!r}"
    _assert_row_pinned("L2a", gates.load_class, _ref_load_class, trace, scope)


def test_a5_l2b_golden_row():
    trace, rp = _trace(
        t3_answer="yes", t3a=("no", "COSTLY"), t4=None, outcome="SKILL"
    )
    scope = "skill:alpha"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "SKILL", f"L2b: {outcome!r}"
    _assert_row_pinned("L2b", gates.load_class, _ref_load_class, trace, scope)

    # M8's witness: L2b's promotion via e1_promote ALONE (fs.verdict
    # NON-promoting) — the COSTLY-driven fixture above fires L2b through
    # its first disjunct regardless of e1_promote's threshold, so it
    # cannot catch a weakened ">= 1" boundary. sightings=1 must NOT
    # promote (threshold is >= 2).
    e1_trace, e1_rp = _trace(
        t3_answer="yes", t3a=("no", "INDETERMINATE"), t4=None,
        e1_sightings=2, e1_post_demand_recurrence=True, outcome="SKILL",
    )
    _legal(e1_trace, e1_rp, scope)
    e1_outcome = gates.load_class(e1_trace, scope)
    assert e1_outcome == "SKILL", f"L2b (e1-driven): {e1_outcome!r}"

    boundary_trace, boundary_rp = _trace(
        t3_answer="yes", t3a=("no", "INDETERMINATE"), t4=None,
        e1_sightings=1, e1_post_demand_recurrence=True, outcome="DEMAND",
    )
    _legal(boundary_trace, boundary_rp, scope)
    boundary_outcome = gates.load_class(boundary_trace, scope)
    assert boundary_outcome == "DEMAND", (
        f"e1_promote fired below its >= 2 threshold: {boundary_outcome!r}"
    )


def test_a5_l2c_golden_row():
    trace, rp = _trace(
        t3_answer="yes", t3a=("no", "INDETERMINATE"), t4=None, outcome="DEMAND"
    )
    scope = "skill:alpha"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "DEMAND", f"L2c: {outcome!r}"
    _assert_row_pinned("L2c", gates.load_class, _ref_load_class, trace, scope)


def test_a5_l3_golden_row():
    trace, rp = _trace(tn_answer="yes", outcome="NEW_SKILL")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "NEW_SKILL", f"L3: {outcome!r}"
    _assert_row_pinned("L3", gates.load_class, _ref_load_class, trace, scope)


def test_a5_l4_golden_row():
    # depth_behind_rule=yes (fires L4) PAIRED with a PROMOTING verdict,
    # so deleting L4 falls to L6 (ALWAYS) rather than "otherwise"
    # (DEMAND) — a naive fixture survives 18.8% of the time.
    trace, rp = _trace(t4=("yes", "no", "COSTLY"), outcome="DEMAND")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "DEMAND", f"L4: {outcome!r}"
    _assert_row_pinned("L4", gates.load_class, _ref_load_class, trace, scope)


def test_a5_l5_golden_row():
    # A5's own worst case: 62.5% of naive fixtures survive. conduct_mode
    # =yes PAIRED with a NON-promoting verdict and no e1 promotion, so
    # deleting L5 falls all the way to "otherwise" (DEMAND), not L6
    # (ALWAYS).
    trace, rp = _trace(t4=("no", "yes", "INDETERMINATE"), outcome="ALWAYS")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "ALWAYS", f"L5: {outcome!r}"
    _assert_row_pinned("L5", gates.load_class, _ref_load_class, trace, scope)


def test_a5_l6_golden_row():
    trace, rp = _trace(t4=("no", "no", "COSTLY"), outcome="ALWAYS")
    scope = "user"
    _legal(trace, rp, scope)
    outcome = gates.load_class(trace, scope)
    assert outcome == "ALWAYS", f"L6: {outcome!r}"
    _assert_row_pinned("L6", gates.load_class, _ref_load_class, trace, scope)

    # M7/M8's witness: L6's promotion via e1_promote ALONE (fs.verdict
    # NON-promoting) — the COSTLY-driven fixture above fires L6 through
    # its first disjunct regardless of e1_promote, so it cannot catch
    # either a dropped e1_promote disjunct (M7) or a weakened ">= 1"
    # threshold (M8). sightings=1 must NOT promote (threshold is >= 2).
    e1_trace, e1_rp = _trace(
        t4=("no", "no", "INDETERMINATE"),
        e1_sightings=2, e1_post_demand_recurrence=True, outcome="ALWAYS",
    )
    _legal(e1_trace, e1_rp, scope)
    e1_outcome = gates.load_class(e1_trace, scope)
    assert e1_outcome == "ALWAYS", f"L6 (e1-driven): {e1_outcome!r}"

    boundary_trace, boundary_rp = _trace(
        t4=("no", "no", "INDETERMINATE"),
        e1_sightings=1, e1_post_demand_recurrence=True, outcome="DEMAND",
    )
    _legal(boundary_trace, boundary_rp, scope)
    boundary_outcome = gates.load_class(boundary_trace, scope)
    assert boundary_outcome == "DEMAND", (
        f"e1_promote fired below its >= 2 threshold: {boundary_outcome!r}"
    )


# =========================================================================
# B. The scope-conditional t4 rule
# =========================================================================


def _b_trace(t4_present: bool, owner="alpha"):
    """B1-B4's shared shape: t3.answer=yes owner=<owner>, t2=no, tn=no —
    the window §3.2 closes."""
    t4 = ("no", "no", "INDETERMINATE") if t4_present else None
    return _trace(t3_answer="yes", t3_owner=owner, t3a=("no", "INDETERMINATE"), t4=t4)


def test_b1_under_requirement_closes():
    """B1: t3.answer=yes owner=alpha, t2=no, tn=no, t4=null,
    scope=skill:beta -> ProposalError matching gates.t4 AND the scope
    string."""
    trace, rules_paths = _b_trace(t4_present=False, owner="alpha")
    data = {"gates": trace, "rules_paths": rules_paths}
    with pytest.raises(ProposalError, match=r"gates\.t4") as exc_info:
        _validate_gates(data, scope="skill:beta")
    assert "skill:beta" in str(exc_info.value)


def test_b2_under_requirement_positive_control():
    """B2: the same trace with t4 populated, same scope -> accepted.
    Without B2, M10/M27 pass on a build that refuses everything in the
    window."""
    trace, rules_paths = _b_trace(t4_present=True, owner="alpha")
    data = {"gates": trace, "rules_paths": rules_paths}
    _validate_gates(data, scope="skill:beta")  # must not raise


def test_b3_over_permission_closes():
    """B3: t4 populated at scope skill:alpha (the owner) -> ProposalError
    naming gates.t4; t4=null at that scope -> accepted."""
    trace, rules_paths = _b_trace(t4_present=True, owner="alpha")
    data = {"gates": trace, "rules_paths": rules_paths}
    with pytest.raises(ProposalError, match=r"gates\.t4"):
        _validate_gates(data, scope="skill:alpha")

    trace2, rules_paths2 = _b_trace(t4_present=False, owner="alpha")
    data2 = {"gates": trace2, "rules_paths": rules_paths2}
    _validate_gates(data2, scope="skill:alpha")  # must not raise


def test_b4_scope_free_behaviour_unchanged():
    """B4: all four traces of B1-B3 validate UNCHANGED when scope is
    omitted (two accepted, two accepted) — asserted against
    validate_proposal(data) called EXACTLY as it is at analyst.py:244
    (positional, no scope kwarg). *Broken:* if the scoped rules were made
    unconditional, this fails."""
    for t4_present in (False, True):
        trace, rules_paths = _b_trace(t4_present=t4_present, owner="alpha")
        data = proposal_dict(gates=trace, rules_paths=rules_paths, destination="reference")
        validate_proposal(data)  # exactly as analyst.py:244 calls it


# =========================================================================
# C. Recompute-and-refuse
# =========================================================================


def test_c1_mismatch_refused_and_twin_accepted():
    """C1: a trace whose outcome disagrees with Table-1 -> ProposalError
    whose message contains BOTH the stated and the derived outcome. The
    identical trace with the derived outcome -> accepted."""
    scope = "user"
    trace, rules_paths = _trace(outcome="ALWAYS")  # true derivation: DEMAND
    data = proposal_dict(
        gates=trace,
        rules_paths=rules_paths,
        destination="reference",
        recommendation="defer",
        flags=["no-cheap-surface"],
    )
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(data, scope=scope)
    msg = str(exc_info.value)
    assert "ALWAYS" in msg and "DEMAND" in msg

    trace2, rules_paths2 = _trace(outcome="DEMAND")
    data2 = proposal_dict(
        gates=trace2,
        rules_paths=rules_paths2,
        destination="reference",
        recommendation="defer",
        flags=["no-cheap-surface"],
    )
    validate_proposal(data2, scope=scope)  # accepted


def test_c2_malformed_inputs_never_escape_as_non_proposal_error():
    """C2 (r1 gate BLOCKER, restated): outcome absent; outcome a
    non-string; scope not a string at all (123, ["skill:s"]); scope the
    empty string; scope the empty-name form "skill:" — for each, the call
    either returns normally or raises ProposalError, asserted by catching
    Exception and requiring isinstance(exc, ProposalError). PLUS the
    mandatory counter-leg: a LEGAL scope value never refuses on shape
    alone — a coherent trace validates cleanly at all three of "project",
    "user" and "skill:s"."""

    def _try(data, scope):
        try:
            validate_proposal(data, scope=scope)
        except Exception as exc:  # noqa: BLE001 — this IS the assertion
            assert isinstance(exc, ProposalError), (
                f"non-ProposalError escaped: {type(exc).__name__}: {exc}"
            )

    trace, rules_paths = _trace(outcome="DEMAND")
    base_data = proposal_dict(
        gates=trace,
        rules_paths=rules_paths,
        destination="reference",
        recommendation="defer",
        flags=["no-cheap-surface"],
    )

    # leg 1: outcome absent
    t = dict(trace)
    t.pop("outcome")
    _try({**base_data, "gates": t}, "user")

    # leg 2: outcome a non-string
    t2 = dict(trace)
    t2["outcome"] = 123
    _try({**base_data, "gates": t2}, "user")

    # leg 3: scope not a string at all
    _try(base_data, 123)
    _try(base_data, ["skill:s"])

    # leg 4: scope the empty string
    _try(base_data, "")

    # leg 5: scope the empty-name form "skill:"
    _try(base_data, "skill:")

    # leg 6: the §9-X1 crash SHAPE itself (t2=no, t3=yes, tn!=yes,
    # t4=null, scope != owner) — this is exactly what M27 (deleting
    # §3.2's scoped t4 rule) turns into an unguarded TypeError. Under
    # correct code the rule refuses this cleanly with ProposalError;
    # _try's isinstance check is what catches a TypeError escaping in
    # its place (the exact S6 breach that tracebacks `self-learn list`).
    window_trace, window_paths = _trace(
        t3_answer="yes", t3_owner="alpha", t3a=("no", "INDETERMINATE"),
        t4=None, outcome="DEMAND",
    )
    window_data = proposal_dict(
        gates=window_trace, rules_paths=window_paths, destination="reference"
    )
    _try(window_data, "skill:beta")  # non-owner scope — route not taken, t4 required

    # the mandatory counter-leg: a coherent trace whose rendering
    # (ALWAYS, via L6) is routable at EVERY scope, so the same proposal
    # fields validate cleanly at all three legal scopes — only the
    # trace's own content may refuse it.
    coherent_trace, coherent_paths = _trace(t4=("no", "no", "COSTLY"), outcome="ALWAYS")
    coherent_data = proposal_dict(
        gates=coherent_trace, rules_paths=coherent_paths, destination="claude-md"
    )
    for scope in ("project", "user", "skill:s"):
        validate_proposal(coherent_data, scope=scope)  # must not raise


def test_c3_eligibility_path_wired(tmp_path):
    """C3: through the REAL queue() -> proposal_info() path (not a direct
    validate_proposal call): a mismatched trace gives proposal_fresh:
    False AND has_proposal: True; rewriting the outcome to the derived
    value gives proposal_fresh: True."""
    home = make_home(tmp_path)
    create_record(
        home, make_behavior(record_id="lrn-aa000001", scope="skill:s", trigger=_QUOTE)
    )
    trace, rules_paths = _trace(t4=("no", "no", "COSTLY"), outcome="ALWAYS")  # correct
    write_proposal(
        home,
        "lrn-aa000001",
        proposal_dict(gates=trace, rules_paths=rules_paths, destination="claude-md"),
    )
    stamp_proposal(home, "lrn-aa000001")
    (bucket,) = [b for b in discover_buckets(home) if b.name == "s"]
    (entry,) = queue(bucket)
    assert proposal_info(entry)["proposal_fresh"] is True

    record_path = find_record_path(home, "lrn-aa000001")
    proposal_path = _proposal_path(record_path.parent.parent, "lrn-aa000001")
    data = read_proposal(proposal_path)
    data["gates"]["outcome"] = "DEMAND"  # now mismatched — true derivation is ALWAYS
    _dump_yaml(data, proposal_path)
    (entry,) = queue(bucket)
    info = proposal_info(entry)
    assert info["proposal_fresh"] is False
    assert info["has_proposal"] is True

    data["gates"]["outcome"] = "ALWAYS"  # the mandated twin — restore
    _dump_yaml(data, proposal_path)
    (entry,) = queue(bucket)
    assert proposal_info(entry)["proposal_fresh"] is True


def test_c4_producer_path_wired(tmp_path):
    """C4: write_proposal with a mismatched trace raises ProposalError
    AND the proposal file does not exist afterwards; the twin with the
    derived outcome writes it."""
    home = make_home(tmp_path)
    create_record(
        home, make_behavior(record_id="lrn-aa000001", scope="skill:s", trigger=_QUOTE)
    )
    trace, rules_paths = _trace(t4=("no", "no", "COSTLY"), outcome="DEMAND")  # wrong
    data = proposal_dict(gates=trace, rules_paths=rules_paths, destination="claude-md")
    with pytest.raises(ProposalError):
        write_proposal(home, "lrn-aa000001", data)
    record_path = find_record_path(home, "lrn-aa000001")
    proposal_path = _proposal_path(record_path.parent.parent, "lrn-aa000001")
    assert not proposal_path.is_file()

    trace2, rules_paths2 = _trace(t4=("no", "no", "COSTLY"), outcome="ALWAYS")
    data2 = proposal_dict(gates=trace2, rules_paths=rules_paths2, destination="claude-md")
    write_proposal(home, "lrn-aa000001", data2)
    assert proposal_path.is_file()


def test_c5_human_path_wired_by_exit_code(tmp_path, monkeypatch):
    """C5: cli.main(["proposal","validate",rid]) returns 1
    (EXIT_SCHEMA_INVALID) on a mismatched trace, 0 on the twin — rc taken
    from the return value, never read downstream of a pipe."""
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    create_record(
        home, make_behavior(record_id="lrn-aa000001", scope="skill:s", trigger=_QUOTE)
    )
    trace, rules_paths = _trace(t4=("no", "no", "COSTLY"), outcome="ALWAYS")
    write_proposal(
        home,
        "lrn-aa000001",
        proposal_dict(gates=trace, rules_paths=rules_paths, destination="claude-md"),
    )

    record_path = find_record_path(home, "lrn-aa000001")
    proposal_path = _proposal_path(record_path.parent.parent, "lrn-aa000001")
    data = read_proposal(proposal_path)
    data["gates"]["outcome"] = "DEMAND"  # mismatched
    _dump_yaml(data, proposal_path)

    rc = cli.main(["proposal", "validate", "lrn-aa000001"])
    assert rc == 1

    data["gates"]["outcome"] = "ALWAYS"  # the twin
    _dump_yaml(data, proposal_path)
    rc2 = cli.main(["proposal", "validate", "lrn-aa000001"])
    assert rc2 == 0


# =========================================================================
# D. Render-1
# =========================================================================


def test_d1_r_demand():
    """D1 — R-DEMAND: DEMAND + destination: claude-md refused; +
    reference accepted."""
    scope = "project"
    trace, rp = _outcome_trace("DEMAND", scope)
    bad = proposal_dict(gates=trace, rules_paths=rp, destination="claude-md")
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)
    good = proposal_dict(gates=trace, rules_paths=rp, destination="reference")
    validate_proposal(good, scope=scope)


def test_d2_r_pathed():
    """D2 — R-PATHED: PATHED + variant: null refused; PATHED +
    variant: rules + non-empty rules_paths + rules_topic accepted."""
    scope = "project"  # PATHED routable at project/user, not skill:*
    trace, rp = _outcome_trace("PATHED", scope)
    bad = proposal_dict(gates=trace, rules_paths=rp, destination="claude-md")
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)
    good = proposal_dict(
        gates=trace, rules_paths=rp, destination="claude-md",
        variant="rules", rules_topic="ts-rules",
    )
    validate_proposal(good, scope=scope)


def test_d3_r_always():
    """D3 — R-ALWAYS: ALWAYS + variant: rules + non-empty rules_paths
    refused; variant: null accepted; AND variant: local accepted, AND
    variant: rules with NO rules_paths accepted (the §6-BD7 admissions —
    without these two legs a build that refuses every variant on ALWAYS
    passes D3)."""
    scope = "project"
    trace, rp = _outcome_trace("ALWAYS", scope)

    bad = proposal_dict(
        gates=trace, rules_paths=["src/**/*.py"], destination="claude-md",
        variant="rules", rules_topic="ts-rules",
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)

    good_null = proposal_dict(gates=trace, destination="claude-md")
    validate_proposal(good_null, scope=scope)

    good_local = proposal_dict(gates=trace, destination="claude-md", variant="local")
    validate_proposal(good_local, scope=scope)

    good_rules_no_paths = proposal_dict(
        gates=trace, destination="claude-md", variant="rules", rules_topic="ts-rules"
    )
    validate_proposal(good_rules_no_paths, scope=scope)


def test_d4_r_skill():
    """D4 — R-SKILL: SKILL + destination: claude-md refused; + skill-md
    accepted."""
    scope = "skill:alpha"
    trace, rp = _outcome_trace("SKILL", scope)
    bad = proposal_dict(gates=trace, rules_paths=rp, destination="claude-md")
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)
    good = proposal_dict(gates=trace, rules_paths=rp, destination="skill-md")
    validate_proposal(good, scope=scope)


def test_d5_r_hook():
    """D5 — R-HOOK: HOOK + destination: hook but alternates missing the
    load-class destination refused; with it present accepted. The
    expected alternate is DERIVED from load_class, never hardcoded."""
    scope = "user"
    trace, rp = _outcome_trace("HOOK", scope)
    expected_alt_class = gates.load_class(trace, scope)
    expected_alt_dest = _RENDER_DESTINATIONS[expected_alt_class]

    bad = proposal_dict(
        gates=trace, rules_paths=rp, destination="hook",
        **hook_proposal_fields(), alternates=[],
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)

    good = proposal_dict(
        gates=trace, rules_paths=rp, destination="hook",
        **hook_proposal_fields(), alternates=[expected_alt_dest],
    )
    validate_proposal(good, scope=scope)

    # M4's negative witness at the proposal-validation level: a trace
    # with field_shaped=yes ALONE (separable=no, cost_bearing=no) truly
    # derives DEMAND, never HOOK — so a proposal STATING outcome: HOOK
    # for it is refused (a weakened hook_ok would derive HOOK too and
    # accept this proposal instead of refusing it).
    partial_trace, partial_rp = _trace(
        t1_field_shaped="yes", t1_separable="no", t1_cost_bearing="no", outcome="HOOK"
    )
    partial_bad = proposal_dict(
        gates=partial_trace, rules_paths=partial_rp, destination="hook",
        **hook_proposal_fields(), alternates=["reference"],
    )
    with pytest.raises(ProposalError):
        validate_proposal(partial_bad, scope=scope)


def test_d6_r_new():
    """D6 — R-NEW: NEW_SKILL with new_skill != gates.tn.proposed_name
    refused; equal accepted."""
    scope = "project"
    trace, rp = _outcome_trace("NEW_SKILL", scope)
    proposed_name = trace["tn"]["proposed_name"]
    bad = proposal_dict(
        gates=trace, rules_paths=rp, destination="new-skill",
        new_skill=proposed_name + "-wrong",
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)
    good = proposal_dict(
        gates=trace, rules_paths=rp, destination="new-skill", new_skill=proposed_name
    )
    validate_proposal(good, scope=scope)


def test_d7_r_fall():
    """D7 — R-FALL: for each of REJECT/DEFER/GRADUATE, a wrong
    recommendation refused and the right one accepted; a GRADUATE
    proposal with already_canon: false refused, true accepted. AND: the
    destination is asserted to equal the LOAD CLASS's destination, with a
    second fixture whose load class DIFFERS from the first — otherwise
    the rule passes for a build that hardcodes one destination."""
    scope = "project"
    for outcome, correct_rec in (
        ("REJECT", "reject"), ("DEFER", "defer"), ("GRADUATE", "graduate"),
    ):
        trace, rp = _outcome_trace(outcome, scope)
        dest = _RENDER_DESTINATIONS[gates.load_class(trace, scope)]
        extra = {"already_canon": True} if outcome == "GRADUATE" else {}
        bad = proposal_dict(
            gates=trace, rules_paths=rp, destination=dest, recommendation="route", **extra
        )
        with pytest.raises(ProposalError):
            validate_proposal(bad, scope=scope)
        good = proposal_dict(
            gates=trace, rules_paths=rp, destination=dest, recommendation=correct_rec, **extra
        )
        validate_proposal(good, scope=scope)

    # already_canon leg, isolated
    trace, rp = _outcome_trace("GRADUATE", scope)
    dest = _RENDER_DESTINATIONS[gates.load_class(trace, scope)]
    bad = proposal_dict(
        gates=trace, rules_paths=rp, destination=dest,
        recommendation="graduate", already_canon=False,
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)
    good = proposal_dict(
        gates=trace, rules_paths=rp, destination=dest,
        recommendation="graduate", already_canon=True,
    )
    validate_proposal(good, scope=scope)

    # destination == the LOAD CLASS's, proven with two fixtures whose
    # load classes DIFFER — else a hardcoded single destination passes.
    trace_a, rp_a = _trace(g0_reject="yes", t4=("no", "no", "COSTLY"), outcome="REJECT")
    trace_b, rp_b = _trace(g0_reject="yes", tn_answer="yes", outcome="REJECT")
    lc_a = gates.load_class(trace_a, scope)
    lc_b = gates.load_class(trace_b, scope)
    assert lc_a != lc_b, "test fixtures must have DIFFERING load classes"
    for trace_x, rp_x, lc_x in ((trace_a, rp_a, lc_a), (trace_b, rp_b, lc_b)):
        dest_x = _RENDER_DESTINATIONS[lc_x]
        good_x = proposal_dict(
            gates=trace_x, rules_paths=rp_x, destination=dest_x, recommendation="reject"
        )
        validate_proposal(good_x, scope=scope)
        wrong_dest = next(d for d in _RENDER_DESTINATIONS.values() if d != dest_x)
        wrong_x = proposal_dict(
            gates=trace_x, rules_paths=rp_x, destination=wrong_dest, recommendation="reject"
        )
        with pytest.raises(ProposalError):
            validate_proposal(wrong_x, scope=scope)


def test_d7a_r_fall_beats_r_scope():
    """D7a (r1 gate F3): a REJECT outcome at scope="user" whose load
    class is DEMAND (an unroutable rendering under an outcome that is NOT
    a routing) keeps recommendation: reject, carries NO no-cheap-surface
    flag, and is accepted; the same proposal with recommendation: defer
    is refused. The only criterion exercising a fallback outcome at an
    unroutable scope."""
    scope = "user"
    trace, rp = _trace(g0_reject="yes", outcome="REJECT")  # load class: DEMAND
    lc = gates.load_class(trace, scope)
    assert lc == "DEMAND"
    dest = _RENDER_DESTINATIONS[lc]

    good = proposal_dict(gates=trace, rules_paths=rp, destination=dest, recommendation="reject")
    validate_proposal(good, scope=scope)  # no no-cheap-surface flag needed

    bad = proposal_dict(gates=trace, rules_paths=rp, destination=dest, recommendation="defer")
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)


def test_d8_r_scope_at_user_scope():
    """D8: DEMAND at scope="user" with recommendation: route refused;
    with recommendation: defer AND flags: [no-cheap-surface] accepted;
    with defer but NO flag refused."""
    scope = "user"
    trace, rp = _outcome_trace("DEMAND", scope)

    bad_route = proposal_dict(
        gates=trace, rules_paths=rp, destination="reference", recommendation="route"
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad_route, scope=scope)

    good = proposal_dict(
        gates=trace, rules_paths=rp, destination="reference",
        recommendation="defer", flags=["no-cheap-surface"],
    )
    validate_proposal(good, scope=scope)

    bad_no_flag = proposal_dict(
        gates=trace, rules_paths=rp, destination="reference", recommendation="defer"
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad_no_flag, scope=scope)


def test_d9_r_scope_at_skill_scope():
    """D9: the same three legs for PATHED at scope="skill:s" — the hole
    r2 does not name; without D9 a build that special-cases user scope
    alone passes everything else."""
    scope = "skill:s"
    trace, rp = _outcome_trace("PATHED", scope)

    bad_route = proposal_dict(
        gates=trace, rules_paths=rp, destination="claude-md",
        variant="rules", rules_topic="ts-rules", recommendation="route",
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad_route, scope=scope)

    good = proposal_dict(
        gates=trace, rules_paths=rp, destination="claude-md",
        variant="rules", rules_topic="ts-rules",
        recommendation="defer", flags=["no-cheap-surface"],
    )
    validate_proposal(good, scope=scope)

    bad_no_flag = proposal_dict(
        gates=trace, rules_paths=rp, destination="claude-md",
        variant="rules", rules_topic="ts-rules", recommendation="defer",
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad_no_flag, scope=scope)


def test_d10_recommendation_absent_reads_as_route():
    """D10: a DEMAND proposal at project scope with no recommendation key
    is accepted; the same with recommendation: defer is refused.
    *Broken:* if absent were read as "skip the check" instead of "route",
    BOTH legs above would still pass unchanged (the first because its
    destination already happens to be right, the second because
    recommendation is explicitly present, never absent) — the twin that
    actually separates the two readings needs recommendation ABSENT
    together with a WRONG destination: "skip the check" would let it
    through, "route" would still catch the destination mismatch."""
    scope = "project"
    trace, rp = _outcome_trace("DEMAND", scope)

    good = proposal_dict(gates=trace, rules_paths=rp, destination="reference")
    assert "recommendation" not in good
    validate_proposal(good, scope=scope)

    bad = proposal_dict(
        gates=trace, rules_paths=rp, destination="reference", recommendation="defer"
    )
    with pytest.raises(ProposalError):
        validate_proposal(bad, scope=scope)

    bad_absent_wrong_dest = proposal_dict(gates=trace, rules_paths=rp, destination="claude-md")
    assert "recommendation" not in bad_absent_wrong_dest
    with pytest.raises(ProposalError):
        validate_proposal(bad_absent_wrong_dest, scope=scope)


# =========================================================================
# E. The seam
# =========================================================================


def test_e1_absent_is_valid_survives(tmp_path):
    """E1: a proposal with no gates:, no flags:, no recommendation:
    validates identically with scope= supplied, with record_text=
    supplied, with both, and with neither; and its proposal_info dict and
    is_unanalyzed result are unchanged. *Broken:* any derivation that
    RUNS on a trace-less proposal fails here, loudly, and would otherwise
    have wedged all 20 live proposals (§9-X6)."""
    data = proposal_dict()
    validate_proposal(data)
    validate_proposal(data, scope="user")
    validate_proposal(data, record_text="irrelevant — gates is absent")
    validate_proposal(data, scope="user", record_text="irrelevant — gates is absent")

    home = make_home(tmp_path)
    create_record(
        home, make_behavior(record_id="lrn-aa000001", scope="skill:s", trigger=_QUOTE)
    )
    write_proposal(home, "lrn-aa000001", proposal_dict())
    stamp_proposal(home, "lrn-aa000001")
    (bucket,) = [b for b in discover_buckets(home) if b.name == "s"]
    (entry,) = queue(bucket)
    # proposal_info ALWAYS threads scope=entry.record.scope (§3.5) — this
    # is the real production path exercising the "gates absent, scope
    # non-None" combination, not just a direct call in this test.
    info = proposal_info(entry)
    assert info["proposal_fresh"] is True
    assert is_unanalyzed(entry) is False


def test_e2_scope_is_keyword_only_with_default_none():
    """E2: by inspect.signature, scope on both validate_proposal and
    _validate_gates is KEYWORD_ONLY with default None. *Broken:* a
    positional parameter would silently change meaning at analyst.py:244,
    worker.py:927/:1282, verbs.py:551/:1193/:1247 — six sites this unit
    may not edit."""
    for fn in (validate_proposal, _validate_gates):
        sig = inspect.signature(fn)
        scope_param = sig.parameters["scope"]
        assert scope_param.kind is inspect.Parameter.KEYWORD_ONLY
        assert scope_param.default is None
