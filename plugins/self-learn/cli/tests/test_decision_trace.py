"""U-schema — the decision trace, its validator, quote containment, and the
closed flag set (docs/specs/self-learn/drafts/u-schema-decision-trace-spec.md
r3). Fixtures are LOCAL to this module (§6-D1): `tests/support.py` is in
reach of four other Wave-1 units editing `ledger_ops.py`'s callers right
now, so this file does not touch it — `proposal_dict`/`hook_proposal_fields`
are imported from it read-only.

Section letters (A-G) mirror the spec's §4 acceptance-criteria lettering;
each test's docstring/comment names its criterion id."""

from __future__ import annotations

import glob as glob_mod
import inspect
import os
import time
from pathlib import Path

import pytest

from self_learn.ledger import discover_buckets
from self_learn.ledger_ops import (
    ROSTER_UNAVAILABLE,
    TRACE_FLAGS,
    TRACE_FS_VERDICTS,
    TRACE_GATE_KEYS,
    TRACE_OUTCOMES,
    TRACE_RECOMMENDATIONS,
    ProposalError,
    _QUOTE_MIN_CHARS,
    _compile_glob_pattern,
    _compile_glob_pattern_cached,
    _dump_yaml,
    _flatten_quote,
    _glob_match,
    _load_yaml_map,
    _proposal_path,
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
from self_learn.normalize import sha_anchor

from support import hook_proposal_fields, make_behavior, make_home, proposal_dict

#: The default `make_behavior()` trigger (support.py) — a genuine RECORD
#: quote source for every test below that does not need a custom body.
TRUE_QUOTE = "About to edit .storage while HA is running."


def _bucket(home, name="s"):
    (b,) = [b for b in discover_buckets(home) if b.name == name]
    return b


def _base_gates(quote: str = TRUE_QUOTE) -> dict:
    """A fully Schema-1-valid trace (§3.6's illustrative shape) — every
    leg answered "no", `t3a` null (t3 said no), `t4` populated (t2/t3 both
    "no", tn not "yes" forces it). Fresh dict every call — no aliasing
    between tests that mutate their own copy."""
    return {
        "g0": {
            "reject": {"answer": "no", "evidence": None},
            "defer": {"answer": "no", "evidence": None},
            "canon": {"answer": "no", "evidence": None, "target": None},
        },
        "t1": {
            "attempted": True,
            "field_shaped": {"answer": "no", "evidence": quote},
            "separable": {"answer": None, "evidence": None},
            "cost_bearing": {"answer": None, "evidence": None},
        },
        "t2": {
            "answer": "no",
            "evidence": quote,
            "match_path": None,
        },
        "t3": {
            "answer": "no",
            "owner": None,
            "scan_terms": ["guard", "invariant"],
            "roster_sha": "sha256:0a1b2c3d4e5f",
        },
        "t3a": None,
        "t4": {
            "depth_behind_rule": {"answer": "no", "evidence": None, "target": None},
            "conduct_mode": {"answer": "no", "evidence": quote},
            "fs": {"verdict": "INDETERMINATE", "evidence": None},
        },
        "tn": {
            "answer": "no",
            "terms": [],
            "members": [],
            "proposed_name": None,
        },
        "e1": {
            "sightings": 1,
            "post_demand_recurrence": False,
        },
        "outcome": "DEMAND",
    }


def _gates_with_t3_yes(
    quote: str = TRUE_QUOTE,
    fs_verdict: str = "INDETERMINATE",
    fs_evidence: str | None = None,
    owner: str = "the-owner",
) -> dict:
    """A valid trace with `t3.answer: yes` — forces `t3a` non-null (D6) and
    frees `t4` (§6-D5's scope-free residual; set null here for simplicity)."""
    g = _base_gates(quote=quote)
    g["t3"] = {
        "answer": "yes",
        "owner": owner,
        "scan_terms": None,
        "roster_sha": "sha256:0a1b2c3d4e5f",
    }
    g["t3a"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None, "target": None},
        "fs": {"verdict": fs_verdict, "evidence": fs_evidence},
    }
    g["t4"] = None
    return g


# =========================================================================
# A. Absent-is-valid — the seam (S1)
# =========================================================================


def test_traceless_proposal_validates_unchanged():
    """A1: a trace-less proposal validates, identically with record_text=
    supplied and omitted — the mandated third positive control."""
    data = proposal_dict()
    validate_proposal(data)
    validate_proposal(data, record_text="irrelevant — gates is absent")


def test_traceless_proposal_stays_fresh_and_analyzed(tmp_path):
    """A2: a real record + trace-less proposal, written + stamped, stays
    fresh and analyzed — S1 exercised through the real call sites."""
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    write_proposal(home, "lrn-aa000001", proposal_dict())
    stamp_proposal(home, "lrn-aa000001")
    (entry,) = queue(_bucket(home))
    assert proposal_info(entry)["proposal_fresh"] is True
    assert is_unanalyzed(entry) is False


def test_traceless_hook_and_rules_proposals_unchanged():
    """A3: the hook-destination and variant:rules proposal shapes still
    validate — _validate_gates did not disturb their validators."""
    validate_proposal(proposal_dict(destination="hook", **hook_proposal_fields()))
    validate_proposal(
        proposal_dict(
            destination="claude-md",
            variant="rules",
            rules_topic="ts-rules",
            rules_paths=["src/**/*.ts"],
        )
    )


def test_validate_proposal_signature_is_backward_compatible():
    """A4: `record_text` is keyword-only with a None default — the
    machine-checkable form of S2."""
    sig = inspect.signature(validate_proposal)
    params = sig.parameters
    assert params["data"].kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_ONLY,
    )
    rt = params["record_text"]
    assert rt.kind is inspect.Parameter.KEYWORD_ONLY
    assert rt.default is None
    validate_proposal(proposal_dict())  # the old one-positional-arg call


def test_flags_and_recommendation_absent_are_valid():
    """A5: gates/flags/recommendation absent independently and together."""
    validate_proposal(proposal_dict())  # all three absent
    validate_proposal(proposal_dict(flags=["evidence-gap"], recommendation="route"))
    validate_proposal(proposal_dict(gates=_base_gates(), recommendation="route"))
    validate_proposal(proposal_dict(gates=_base_gates(), flags=[]))


def test_yes_no_scalars_round_trip_as_strings(tmp_path):
    """A6: unquoted yes/no round-trips as the STRING "no", never a bool
    (ruamel YAML 1.2) — pins §3.6's verified loader behaviour."""
    data = proposal_dict(gates=_base_gates())
    path = tmp_path / "trace.yaml"
    _dump_yaml(data, path)
    reloaded = _load_yaml_map(path)
    answer = reloaded["gates"]["g0"]["reject"]["answer"]
    assert answer == "no"
    assert isinstance(answer, str)
    validate_proposal(reloaded)


_MALFORMED_TRACE_CASES = [
    ("gates_not_a_mapping", proposal_dict(gates="oops")),
    ("gates_partial_with_bad_g0", proposal_dict(gates={"g0": "oops"})),
    ("gates_is_a_list", proposal_dict(gates=[])),
    (
        "t1_null_where_mapping_required",
        proposal_dict(gates={**_base_gates(), "t1": None}),
    ),
    ("flags_bare_string", proposal_dict(flags="near-cluster")),
    ("recommendation_is_a_list", proposal_dict(recommendation=[])),
    (
        "evidence_is_an_int",
        proposal_dict(
            gates={
                **_base_gates(),
                "t1": {
                    **_base_gates()["t1"],
                    "field_shaped": {"answer": "no", "evidence": 5},
                },
            }
        ),
    ),
    (
        "t3_scan_terms_bare_string",
        proposal_dict(
            gates={**_base_gates(), "t3": {**_base_gates()["t3"], "scan_terms": "guard"}}
        ),
    ),
    (
        "tn_members_bare_string",
        proposal_dict(
            gates={**_base_gates(), "tn": {**_base_gates()["tn"], "members": "lrn-aa000001"}}
        ),
    ),
]


@pytest.mark.parametrize(
    "data", [c[1] for c in _MALFORMED_TRACE_CASES], ids=[c[0] for c in _MALFORMED_TRACE_CASES]
)
def test_malformed_trace_shapes_raise_only_proposal_error(data):
    """A7: the S6 test. Every malformed shape raises ProposalError and
    ONLY ProposalError — never TypeError/KeyError (S6) — because
    `proposal_info` catches only ProposalError and `queue()` catches
    nothing at all."""
    with pytest.raises(ProposalError):
        validate_proposal(data)


def test_validate_proposal_performs_no_filesystem_io(monkeypatch):
    """A8: the S4 test. With Path.read_text / Path.open / builtins.open all
    raising, a full valid trace with record_text= supplied still passes —
    and, monkeypatched the SAME way, a fabricated quote still raises
    ProposalError (paired in the same test — otherwise a build where
    containment never runs would also pass the I/O half)."""
    record_text = make_behavior(record_id="lrn-aa000001").to_text()
    valid = proposal_dict(gates=_base_gates(quote=TRUE_QUOTE), flags=[], recommendation="route")
    fabricated = proposal_dict(
        gates=_base_gates(quote="the compiler writes uppercase markers")
    )

    def _boom(*_a, **_k):
        raise AssertionError("validate_proposal must not touch the filesystem")

    monkeypatch.setattr(Path, "read_text", _boom)
    monkeypatch.setattr(Path, "open", _boom)
    monkeypatch.setattr("builtins.open", _boom)

    validate_proposal(valid, record_text=record_text)
    with pytest.raises(ProposalError):
        validate_proposal(fabricated, record_text=record_text)


def test_stamp_proposal_does_not_validate_the_trace(tmp_path):
    """A9: the S5 test. A proposal carrying a fabricated quote, written
    straight to disk (bypassing write_proposal), still gets stamped —
    guards the deliberate choice not to run the trace validator from
    stamp_proposal (whose escape would surface as rc=64 EXIT_USAGE)."""
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    record_path = find_record_path(home, "lrn-aa000001")
    proposal_path = _proposal_path(record_path.parent.parent, "lrn-aa000001")
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    data = proposal_dict(
        gates=_base_gates(quote="the compiler writes uppercase markers")
    )
    _dump_yaml(data, proposal_path)

    stamp_proposal(home, "lrn-aa000001")  # must NOT raise

    reloaded = read_proposal(proposal_path)
    record = make_behavior(record_id="lrn-aa000001")
    assert reloaded["record_sha"] == sha_anchor(record.body)


def _swap(base_builder, key_path):
    """A gates dict from base_builder() with the dotted key_path's value
    replaced by a non-mapping scalar — every level type-checked before
    it is indexed (S6), exercised at every Schema-1 mapping node."""
    g = base_builder()
    node = g
    parts = key_path.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = "oops"
    return g


_MAPPING_LEVEL_CASES = [
    ("g0", lambda: _swap(_base_gates, "g0")),
    ("g0.reject", lambda: _swap(_base_gates, "g0.reject")),
    ("g0.canon", lambda: _swap(_base_gates, "g0.canon")),
    ("t1.field_shaped", lambda: _swap(_base_gates, "t1.field_shaped")),
    ("t1.separable", lambda: _swap(_base_gates, "t1.separable")),
    ("t1.cost_bearing", lambda: _swap(_base_gates, "t1.cost_bearing")),
    ("t2", lambda: _swap(_base_gates, "t2")),
    ("t3", lambda: _swap(_base_gates, "t3")),
    ("tn", lambda: _swap(_base_gates, "tn")),
    ("e1", lambda: _swap(_base_gates, "e1")),
    # Code gate F6 (MINOR), r3 delta: the S6 sweep covered every t3a/t4
    # SUB-leg but not the t3a/t4 top level itself.
    ("t3a", lambda: _swap(_gates_with_t3_yes, "t3a")),
    ("t4", lambda: _swap(_base_gates, "t4")),
    ("t3a.depth_behind_rule", lambda: _swap(_gates_with_t3_yes, "t3a.depth_behind_rule")),
    ("t3a.fs", lambda: _swap(_gates_with_t3_yes, "t3a.fs")),
    ("t4.depth_behind_rule", lambda: _swap(_base_gates, "t4.depth_behind_rule")),
    ("t4.conduct_mode", lambda: _swap(_base_gates, "t4.conduct_mode")),
    ("t4.fs", lambda: _swap(_base_gates, "t4.fs")),
]


@pytest.mark.parametrize(
    "gates_builder",
    [c[1] for c in _MAPPING_LEVEL_CASES],
    ids=[c[0] for c in _MAPPING_LEVEL_CASES],
)
def test_every_mapping_node_type_checked_before_indexed(gates_builder):
    """S6, exercised at every Schema-1 mapping level (M22): swapping any
    nested mapping node for a scalar must raise ProposalError, never a
    bare TypeError/AttributeError/KeyError. A7 pins the top-level shapes;
    this pins the S6 discipline at every deeper node the mutation catalog
    names."""
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=gates_builder()))


# =========================================================================
# B. The closed flag set (Set-F)
# =========================================================================


def test_flag_outside_closed_set_refused():
    """B1: mandated positive control 2 — a value outside the set REJECTED."""
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(flags=["invented"]))


def test_every_flag_in_the_closed_set_is_accepted():
    """B2: the twin, in three required parts (FOLD-1)."""
    for flag in TRACE_FLAGS:  # (a) never a hardcoded copy
        validate_proposal(proposal_dict(flags=[flag]))
    assert len(TRACE_FLAGS) == 8  # (b) the count guard
    assert "pathed-unbuilt" in TRACE_FLAGS  # (c) C1's resolution, by exception


def test_flags_shape():
    """B3. The non-iterable case (`flags=5`) is the one that actually
    discriminates the `isinstance(flags, list)` guard (M27): TRACE_FLAGS
    has no single-character members, so a bare STRING non-list value
    would still raise via character-by-character iteration even with the
    guard removed — only a non-iterable value proves the guard runs
    before the loop, never letting a bare TypeError escape (S6)."""
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(flags="near-cluster"))  # non-list
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(flags=5))  # non-list, non-iterable
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(flags=[5]))  # non-string member
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(flags=[""]))  # empty-string member
    with pytest.raises(ProposalError):
        validate_proposal(
            proposal_dict(flags=["evidence-gap", "evidence-gap"])
        )  # duplicate
    validate_proposal(proposal_dict(flags=[]))  # [] accepted


# =========================================================================
# C. recommendation (Set-R)
# =========================================================================


def test_recommendation_outside_enum_refused():
    """C1."""
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(recommendation="maybe"))


def test_each_recommendation_value_accepted():
    """C2: the twin, iterating TRACE_RECOMMENDATIONS. Code gate F5
    (MINOR), r3 delta: the count guard — an iterating test alone stays
    green under a shrunken enum (B2/FOLD-1's lesson, unapplied to Set-R
    until now)."""
    for rec in TRACE_RECOMMENDATIONS:
        validate_proposal(proposal_dict(recommendation=rec))
    assert len(TRACE_RECOMMENDATIONS) == 4


def test_recommendation_absent_is_not_defaulted():
    """C3: validators do not write."""
    data = proposal_dict()
    assert "recommendation" not in data
    validate_proposal(data)
    assert "recommendation" not in data


# =========================================================================
# D. Trace shape, enums, required-ness (Schema-1)
# =========================================================================


def test_unknown_gate_key_refused():
    """D1."""
    g = _base_gates()
    g["bogus"] = {}
    with pytest.raises(ProposalError, match="bogus"):
        validate_proposal(proposal_dict(gates=g))


def test_unknown_gate_keys_of_incomparable_types_do_not_raise_typeerror():
    """FW-63, the S6 test for this specific defect. YAML permits
    non-string mapping keys — a `gates:` mapping with 2+ unknown keys of
    MUTUALLY INCOMPARABLE TYPES (`{1: x, zzz: y}`) used to make the
    unknown-key `sorted()` raise a bare `TypeError` ("'<' not supported
    between instances of 'str' and 'int'"), verified end to end via
    `cli.main(["list"])`. `TypeError` is neither `ProposalError` nor
    `LedgerOpsError`, so it escaped every caller's `except ProposalError`
    (`proposal_info`, `queue`, `list_items`) and tracebacked `self-learn
    list` for EVERY record, not just the malformed one — the exact
    failure S6 (this module's docstring, `_validate_gates`) commits to
    never happening.

    A single unknown key would not discriminate this: `sorted()` on a
    1-element set never calls the comparator, so a same-type-only
    regression (e.g. a `key=` typo that still handles all-`str` sets)
    would slip past a weaker test."""
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates={1: "x", "zzz": "y"}))


def test_missing_gate_key_refused():
    """D1: TRACE_GATE_KEYS closed in the missing direction — iterated,
    never a hardcoded copy.

    FW-59: `match=key` alone is VACUOUS here — every message this check
    can ever raise echoes the FULL `list(TRACE_GATE_KEYS)` in its
    "required:" clause, so `key` is a substring of every message
    regardless of which key the `missing` computation actually names.
    Mutation-verified: hardcoding the reported `missing` list to always
    read `["g0"]` (i.e. reporting the wrong key for 8 of the 9 iterations)
    left the OLD bare `match=key` form green for every key. Pinned
    instead to the "missing key(s) [...]" clause specifically, split off
    from the "required:" clause before the exact key list is compared —
    so a `missing` computation that names the wrong key is caught."""
    for key in TRACE_GATE_KEYS:
        g = _base_gates()
        del g[key]
        with pytest.raises(ProposalError) as excinfo:
            validate_proposal(proposal_dict(gates=g))
        reported, _, _required_clause = str(excinfo.value).partition(" — required:")
        assert reported == f"gates is missing key(s) {[key]}"


def test_outcome_outside_enum_refused():
    """D2."""
    g = _base_gates()
    g["outcome"] = "BOGUS"
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))


def test_each_outcome_value_accepted():
    """D2: the twin, iterating TRACE_OUTCOMES. Code gate F5 (MINOR), r3
    delta: the count guard — §8-O1 has `U-table` import this tuple, so a
    silently shrunken TRACE_OUTCOMES would make a legitimate outcome
    (e.g. GRADUATE) schema-invalid and propagate into permanent
    re-analysis (proposal_fresh: False forever)."""
    for outcome in TRACE_OUTCOMES:
        g = _base_gates()
        g["outcome"] = outcome
        validate_proposal(proposal_dict(gates=g))
    assert len(TRACE_OUTCOMES) == 9


def test_fs_verdict_enum_and_evidence_rule():
    """D3: covers both t3a.fs and t4.fs. Iterates TRACE_FS_VERDICTS and
    subtracts the one exception (INDETERMINATE) — never a partial
    re-enumeration of Set-V (FOLD-15).

    Code gate F3 (MODERATE), r3 delta: the BOGUS-verdict fixtures must
    carry a TRUE quote, not `evidence: None` — otherwise deleting the
    enum-membership check still raises, for the evidence-missing reason,
    and Set-V's closure is unpinned by this test."""
    g = _base_gates()
    g["t4"]["fs"] = {"verdict": "BOGUS", "evidence": TRUE_QUOTE}
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _gates_with_t3_yes(fs_verdict="BOGUS", fs_evidence=TRUE_QUOTE)
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    for verdict in TRACE_FS_VERDICTS:
        required = verdict != "INDETERMINATE"

        g_null = _base_gates()
        g_null["t4"]["fs"] = {"verdict": verdict, "evidence": None}
        g_quote = _base_gates()
        g_quote["t4"]["fs"] = {"verdict": verdict, "evidence": TRUE_QUOTE}
        if required:
            with pytest.raises(ProposalError):
                validate_proposal(proposal_dict(gates=g_null))
        else:
            validate_proposal(proposal_dict(gates=g_null))
        validate_proposal(proposal_dict(gates=g_quote))

        g2_null = _gates_with_t3_yes(fs_verdict=verdict, fs_evidence=None)
        g2_quote = _gates_with_t3_yes(fs_verdict=verdict, fs_evidence=TRUE_QUOTE)
        if required:
            with pytest.raises(ProposalError):
                validate_proposal(proposal_dict(gates=g2_null))
        else:
            validate_proposal(proposal_dict(gates=g2_null))
        validate_proposal(proposal_dict(gates=g2_quote))

    assert len(TRACE_FS_VERDICTS) == 4  # code gate F5: the count guard


def test_field_shaped_requires_evidence_both_ways():
    """D4: the leg r2 singles out as required in BOTH directions."""
    for answer in ("no", "yes"):
        g = _base_gates()
        g["t1"]["field_shaped"] = {"answer": answer, "evidence": None}
        with pytest.raises(ProposalError):
            validate_proposal(proposal_dict(gates=g))
        g2 = _base_gates()
        g2["t1"]["field_shaped"] = {"answer": answer, "evidence": TRUE_QUOTE}
        validate_proposal(proposal_dict(gates=g2))


def test_canon_yes_requires_target_and_evidence():
    """D5: g0.canon, t3a.depth_behind_rule, t4.depth_behind_rule."""
    g = _base_gates()
    g["g0"]["canon"] = {"answer": "yes", "evidence": TRUE_QUOTE, "target": None}
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))
    g = _base_gates()
    g["g0"]["canon"] = {"answer": "yes", "evidence": None, "target": "canon/anchor.md"}
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))
    g = _base_gates()
    g["g0"]["canon"] = {
        "answer": "yes",
        "evidence": TRUE_QUOTE,
        "target": "canon/anchor.md",
    }
    validate_proposal(proposal_dict(gates=g))

    g = _gates_with_t3_yes()
    g["t3a"]["depth_behind_rule"] = {
        "answer": "yes",
        "evidence": TRUE_QUOTE,
        "target": None,
    }
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))
    g = _gates_with_t3_yes()
    g["t3a"]["depth_behind_rule"] = {
        "answer": "yes",
        "evidence": None,
        "target": "docs/rule.md",
    }
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))
    g = _gates_with_t3_yes()
    g["t3a"]["depth_behind_rule"] = {
        "answer": "yes",
        "evidence": TRUE_QUOTE,
        "target": "docs/rule.md",
    }
    validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["t4"]["depth_behind_rule"] = {
        "answer": "yes",
        "evidence": TRUE_QUOTE,
        "target": None,
    }
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))
    g = _base_gates()
    g["t4"]["depth_behind_rule"] = {
        "answer": "yes",
        "evidence": None,
        "target": "docs/rule.md",
    }
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))
    g = _base_gates()
    g["t4"]["depth_behind_rule"] = {
        "answer": "yes",
        "evidence": TRUE_QUOTE,
        "target": "docs/rule.md",
    }
    validate_proposal(proposal_dict(gates=g))


def test_t3a_presence_follows_t3_answer():
    """D6."""
    g = _gates_with_t3_yes()
    g["t3a"] = None
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()  # t3.answer == "no", t3a already null
    g["t3a"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None, "target": None},
        "fs": {"verdict": "INDETERMINATE", "evidence": None},
    }
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    validate_proposal(proposal_dict(gates=_gates_with_t3_yes()))
    validate_proposal(proposal_dict(gates=_base_gates()))


def test_t4_presence_rules():
    """D7."""
    g = _base_gates()
    g["t2"] = {"answer": "yes", "evidence": TRUE_QUOTE, "match_path": "src/app.py"}
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g, rules_paths=["src/**/*.py"]))

    g = _base_gates()
    g["tn"] = {
        "answer": "yes",
        "terms": [],
        "members": ["lrn-aa000001", "lrn-bb000002"],
        "proposed_name": "link-checker",
    }
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["t4"] = None
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _gates_with_t3_yes()
    g["t4"] = None
    validate_proposal(proposal_dict(gates=g))

    g = _gates_with_t3_yes()
    g["t4"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None, "target": None},
        "conduct_mode": {"answer": "no", "evidence": TRUE_QUOTE},
        "fs": {"verdict": "INDETERMINATE", "evidence": None},
    }
    validate_proposal(proposal_dict(gates=g))


def test_tn_member_and_name_rules():
    """D8."""

    def _tn(**overrides):
        base = {"answer": "no", "terms": [], "members": [], "proposed_name": None}
        base.update(overrides)
        return base

    g = _base_gates()
    g["tn"] = _tn(answer="yes", members=["lrn-aa000001"], proposed_name="link-checker")
    g["t4"] = None
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(
        answer="yes",
        members=["lrn-aa000001", "lrn-bb000002"],
        proposed_name="link-checker",
    )
    g["t4"] = None
    validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(answer="no", members=["lrn-aa000001", "lrn-bb000002"])
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(answer="no", members=["lrn-aa000001"])
    validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(answer="no", members=[])
    validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(
        answer="indeterminate",
        members=["lrn-aa000001", "lrn-bb000002", "lrn-cc000003"],
    )
    validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(answer="indeterminate", members=["not-a-record-id"])
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(
        answer="yes", members=["lrn-aa000001", "lrn-bb000002"], proposed_name=None
    )
    g["t4"] = None
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(
        answer="yes",
        members=["lrn-aa000001", "lrn-bb000002"],
        proposed_name="Not Kebab",
    )
    g["t4"] = None
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["tn"] = _tn(answer="no", proposed_name="link-checker")
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))


def test_e1_shape():
    """D9: the bool/int type-confusion runs both ways (FOLD-14)."""
    g = _base_gates()
    g["e1"]["sightings"] = "1"
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["e1"]["sightings"] = 0
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["e1"]["sightings"] = 1
    validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["e1"]["sightings"] = True
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["e1"]["post_demand_recurrence"] = "no"
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["e1"]["post_demand_recurrence"] = 1
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))


def test_t1_attempted_must_be_bool():
    """D10."""
    g = _base_gates()
    g["t1"]["attempted"] = "true"
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))
    g = _base_gates()
    g["t1"]["attempted"] = True
    validate_proposal(proposal_dict(gates=g))


# =========================================================================
# E. Quote containment — the discriminator
# =========================================================================


def test_true_record_quote_accepted():
    """E1: E2's discriminating twin."""
    record_text = make_behavior(record_id="lrn-aa000001").to_text()
    validate_proposal(proposal_dict(gates=_base_gates(quote=TRUE_QUOTE)), record_text=record_text)


def test_fabricated_record_quote_refused():
    """E2: mandated positive control 1."""
    record_text = make_behavior(record_id="lrn-aa000001").to_text()
    fabricated = "the compiler writes uppercase markers"
    with pytest.raises(ProposalError) as excinfo:
        validate_proposal(
            proposal_dict(gates=_base_gates(quote=fabricated)), record_text=record_text
        )
    msg = str(excinfo.value)
    assert "gates.t1.field_shaped" in msg  # names the gate leg
    assert fabricated in msg  # echoes the quote


def test_quote_matches_across_a_line_wrap():
    """E3: proves _flatten_quote collapses, not merely trims."""
    rec = make_behavior(record_id="lrn-aa000001")
    rec.set_body(
        "\n## Trigger\nThe quote spans\na line wrap in the body.\n\n"
        "## Instruction\nStop the container first.\n"
    )
    record_text = rec.to_text()
    quote = "The quote spans a line wrap in the body."
    validate_proposal(proposal_dict(gates=_base_gates(quote=quote)), record_text=record_text)


def test_flatten_quote_strips_and_collapses():
    """Code gate F6 (MINOR), r3 delta: `_flatten_quote`'s `.strip()` half,
    unit-tested directly — E3 pins the collapse half but a leading/
    trailing-only whitespace case can coincidentally survive against a
    real record body (the record's own surrounding context often
    supplies matching boundary spaces after collapse), so it does not
    reliably discriminate `.strip()` on its own."""
    assert _flatten_quote("  a   b  \n c  ") == "a b c"
    assert _flatten_quote("no whitespace change needed") == "no whitespace change needed"


def test_fabricated_quote_on_optional_record_leg_refused():
    """Code gate F6 (MINOR), r3 delta: containment must not be gated on
    `required` — `t1.separable`'s evidence is optional (never required),
    but a FABRICATED quote there, once present, must still be refused."""
    record_text = make_behavior(record_id="lrn-aa000001").to_text()
    g = _base_gates()
    g["t1"]["separable"] = {
        "answer": "no",
        "evidence": "the compiler writes uppercase markers",
    }
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g), record_text=record_text)

    g2 = _base_gates()
    g2["t1"]["separable"] = {"answer": "no", "evidence": TRUE_QUOTE}
    validate_proposal(proposal_dict(gates=g2), record_text=record_text)


def test_quote_from_frontmatter_accepted(tmp_path):
    """E4: proves the source is to_text(), not body — exercised through
    write_proposal's real record_text wiring (§3.5) so a "source from
    record.body instead" regression at the CALL SITE is caught, not just
    a hypothetical inside _validate_gates (M6)."""
    home = make_home(tmp_path)
    rec = make_behavior(record_id="lrn-aa000001")
    rec.set_incident_cost("an evening of debugging session")
    create_record(home, rec)
    g = _base_gates()
    g["t4"]["fs"] = {
        "verdict": "COSTLY",
        "evidence": "an evening of debugging session",
    }
    g["outcome"] = "ALWAYS"  # u-table §3.2: t4.fs COSTLY -> L6 -> ALWAYS
    write_proposal(
        home, "lrn-aa000001", proposal_dict(gates=g, destination="claude-md")
    )


def test_quote_from_frontmatter_accepted_via_proposal_info(tmp_path):
    """Code gate F6 (MINOR), r3 delta — "the one with teeth": E4 covered
    only `write_proposal`'s record_text wiring, never `proposal_info`'s.
    If `proposal_info` ever sourced `.body` instead of `.to_text()`, a
    proposal quoting the frontmatter would validate at write time and
    then be judged schema-invalid FOREVER on the eligibility path — the
    re-analysis storm §3.7 calls "a worse failure than the one being
    prevented." Exercised through the real queue()/proposal_info() path,
    not a direct validate_proposal call."""
    home = make_home(tmp_path)
    rec = make_behavior(record_id="lrn-aa000001")
    rec.set_incident_cost("an evening of debugging session")
    create_record(home, rec)
    g = _base_gates()
    g["t4"]["fs"] = {
        "verdict": "COSTLY",
        "evidence": "an evening of debugging session",
    }
    g["outcome"] = "ALWAYS"  # u-table §3.2: t4.fs COSTLY -> L6 -> ALWAYS
    write_proposal(
        home, "lrn-aa000001", proposal_dict(gates=g, destination="claude-md")
    )
    stamp_proposal(home, "lrn-aa000001")
    (entry,) = queue(_bucket(home))
    assert proposal_info(entry)["proposal_fresh"] is True
    assert is_unanalyzed(entry) is False


def test_quote_below_minimum_length_refused():
    """E5: (a) a too-short substring refused; (b) the whitespace twin —
    raw len 9, flattened len 3 — also refused (FOLD-7, floor is measured
    on the FLATTENED quote); a legitimate >=8-char quote accepted."""
    assert _QUOTE_MIN_CHARS == 8
    record_text = make_behavior(record_id="lrn-aa000001").to_text()

    with pytest.raises(ProposalError, match="_QUOTE_MIN_CHARS"):
        validate_proposal(
            proposal_dict(gates=_base_gates(quote="dit")), record_text=record_text
        )
    with pytest.raises(ProposalError, match="_QUOTE_MIN_CHARS"):
        validate_proposal(
            proposal_dict(gates=_base_gates(quote="   the   ")), record_text=record_text
        )
    validate_proposal(
        proposal_dict(gates=_base_gates(quote="the container")), record_text=record_text
    )


def test_write_proposal_supplies_record_text(tmp_path):
    """E6: the caller-wiring test on the producer path."""
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    with pytest.raises(ProposalError):
        write_proposal(
            home,
            "lrn-aa000001",
            proposal_dict(
                gates=_base_gates(quote="the compiler writes uppercase markers"),
                destination="reference",  # u-table: _base_gates() derives DEMAND
            ),
        )
    write_proposal(
        home,
        "lrn-aa000001",
        proposal_dict(gates=_base_gates(quote=TRUE_QUOTE), destination="reference"),
    )


def test_fabricated_quote_makes_proposal_unfresh(tmp_path):
    """E7: the caller-wiring test on the eligibility path, with its
    mandated in-test twin (a true-quote rewrite stays fresh) and the
    has_proposal assertion distinguishing "refused for containment" from
    "the file vanished"."""
    home = make_home(tmp_path)
    create_record(home, make_behavior(record_id="lrn-aa000001"))
    write_proposal(
        home,
        "lrn-aa000001",
        proposal_dict(gates=_base_gates(quote=TRUE_QUOTE), destination="reference"),
    )
    stamp_proposal(home, "lrn-aa000001")
    bucket = _bucket(home)
    (entry,) = queue(bucket)
    assert is_unanalyzed(entry) is False

    record_path = find_record_path(home, "lrn-aa000001")
    proposal_path = _proposal_path(record_path.parent.parent, "lrn-aa000001")
    data = read_proposal(proposal_path)

    data["gates"] = _base_gates(quote="the compiler writes uppercase markers")
    _dump_yaml(data, proposal_path)
    (entry,) = queue(bucket)
    assert is_unanalyzed(entry) is True
    assert proposal_info(entry)["has_proposal"] is True

    data["gates"] = _base_gates(quote=TRUE_QUOTE)  # the mandated twin
    _dump_yaml(data, proposal_path)
    (entry,) = queue(bucket)
    assert is_unanalyzed(entry) is False


# =========================================================================
# F. Intra-trace cross-checks
# =========================================================================


def test_t2_match_path_must_match_a_proposed_glob():
    """F1."""
    record_text = make_behavior(record_id="lrn-aa000001").to_text()

    def _t2_yes_gates():
        g = _base_gates()
        g["t2"] = {"answer": "yes", "evidence": TRUE_QUOTE, "match_path": "src/app.py"}
        g["t4"] = None
        return g

    with pytest.raises(ProposalError):
        validate_proposal(
            proposal_dict(gates=_t2_yes_gates(), rules_paths=["docs/**/*.md"]),
            record_text=record_text,
        )
    validate_proposal(
        proposal_dict(gates=_t2_yes_gates(), rules_paths=["src/**/*.py"]),
        record_text=record_text,
    )
    validate_proposal(
        proposal_dict(
            gates=_t2_yes_gates(), rules_paths=["docs/**/*.md", "src/**/*.py"]
        ),
        record_text=record_text,
    )


def test_double_star_matches_zero_directory_levels():
    """F1a: the case the blocker turns on."""
    assert _glob_match("src/app.py", "src/**/*.py") is True
    assert _glob_match("src/a/b/deep.py", "src/**/*.py") is True
    assert _glob_match("docs/x.md", "src/**/*.py") is False

    record_text = make_behavior(record_id="lrn-aa000001").to_text()
    for match_path in ("src/app.py", "src/a/b/deep.py"):
        g = _base_gates()
        g["t2"] = {"answer": "yes", "evidence": TRUE_QUOTE, "match_path": match_path}
        g["t4"] = None
        validate_proposal(
            proposal_dict(gates=g, rules_paths=["src/**/*.py"]), record_text=record_text
        )


def test_malformed_glob_class_body_raises_proposal_error_not_re_error():
    """Code gate F1 (MAJOR), r3 delta — the class-BODY corner §3.4a never
    named. A *balanced* class whose body ends in a backslash —
    `src/[a\\].py` — used to emit an unterminated `re` class (`\\]`
    escapes the closing bracket) and `re.compile` raised `re.error`, not
    `ProposalError` — a traceback out of `self-learn list` on a malformed
    trace on somebody else's record, verbatim the symptom S6 exists to
    prevent. Exercised end-to-end through X1/`validate_proposal`, the
    actual reachable path, not just `_glob_match` directly."""
    assert _glob_match("src/a.py", "src/[a\\].py") is True  # the discriminating twin

    g = _base_gates()
    g["t2"] = {"answer": "yes", "evidence": TRUE_QUOTE, "match_path": "src/x.py"}
    g["t4"] = None
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g, rules_paths=["src/[a\\].py"]))


def test_untranslatable_glob_raises_proposal_error():
    """Code gate N-1, r3 delta — `_compile_glob_pattern`'s `re.error`
    backstop is LOAD-BEARING TODAY, not merely future-proofing, and had
    no test: removing it left the whole suite green.

    The F1 sanitizer escapes the class BODY but does not touch RANGES, so
    a reversed range reopens the exact S6 escape F1 was about — measured
    on `[z-a]`, `[d-*]` and `[a-\\]`. Without the backstop this raises
    `re.PatternError: bad character range z-a`, which is neither a
    `ProposalError` nor a `LedgerOpsError`, so it surfaces as a traceback
    out of `self-learn list`.

    Keep this pinned to the RANGE family specifically: the body-escaping
    tests above cannot reach it, and a future translator change that
    re-broke ranges would otherwise ship silently."""
    with pytest.raises(ProposalError):
        _glob_match("src/app.py", "src/[z-a]*.py")


def test_consecutive_double_star_segments_collapse_before_translation():
    """FW-57. §3.4a emits a separate `(?:[^/]+/)*` group per `**`
    segment; left uncollapsed, adjacent groups are semantically redundant
    (Kleene-star idempotence: `(?:X)*(?:X)*` matches exactly what `(?:X)*`
    matches) but NOT backtracking-cost-redundant — `re` explores every
    way of splitting a span across N adjacent groups before concluding a
    non-match, exponential in N. The oracle the module's own docstring
    names, `glob.translate`, collapses consecutive `**` into a single
    `(?:.+/)?` before translating; this pins the same collapse here.

    Asserting the TRANSLATED SHAPE, not timing, is the primary oracle: a
    timing assertion is flaky under CI/host load, but the shape is the
    actual mechanism of the blowup, so pinning it is strictly stronger
    and can't flake. (See the bounded-time test below for a second,
    coarser regression guard.)"""
    single = _compile_glob_pattern("a/**/b")
    doubled = _compile_glob_pattern("a/**/**/b")
    tripled = _compile_glob_pattern("a/**/**/**/b")
    assert single.pattern == doubled.pattern == tripled.pattern
    # a trailing run of `**` collapses too — the final segment still gets
    # `.*` (zero-or-more directory levels *or* nothing at all), not the
    # non-final `(?:[^/]+/)*` form.
    trailing_single = _compile_glob_pattern("a/**")
    trailing_tripled = _compile_glob_pattern("a/**/**/**")
    assert trailing_single.pattern == trailing_tripled.pattern


def test_many_consecutive_double_stars_do_not_hang():
    """FW-57: a bounded-time backstop against reintroducing the
    exponential blowup, paired with (not a replacement for) the shape
    test above — the shape test proves the mechanism is gone; this proves
    it stays gone even if some future change reaches the same regex via a
    different code path the shape assertion does not cover.

    Pre-fix on this machine: 12 consecutive `**` segments against this
    24-segment non-matching path measured ~40s (8 -> 0.35s, 10 -> 4.2s —
    each +2 roughly 12x'd the runtime). Post-fix it is microseconds. 5s
    is generous enough not to flake under host load while still failing
    hard on any regression — the blowup is multiplicative per additional
    `**`, so a partial reintroduction would still blow well past it."""
    path = "/".join(f"seg{i}" for i in range(24)) + "/x.txt"
    pattern = "/".join(["**"] * 12) + "/x.py"
    t0 = time.perf_counter()
    result = _glob_match(path, pattern)
    dt = time.perf_counter() - t0
    assert result is False
    assert dt < 5.0


def test_untranslatable_glob_pattern_error_is_memoized():
    """Adjacent to the FW-57 fix, code gate N-1 territory: `lru_cache`
    never caches an exception — a bare `raise` inside an `lru_cache`d
    function reruns the function body on every call. Measured pre-fix:
    `cache_info()` after 5 identical failing calls read `hits=0,
    misses=5, currsize=0` — a broken `rules_paths` pattern on one record
    was re-translated on every `list`, for every record, every time.
    Fixed by caching `(compiled, error)` tuples inside
    `_compile_glob_pattern_cached` instead of raising there — the raise
    now lives only in the thin, un-memoized `_compile_glob_pattern`
    wrapper."""
    _compile_glob_pattern_cached.cache_clear()
    for _ in range(5):
        with pytest.raises(ProposalError):
            _glob_match("src/app.py", "src/[z-a]*.py")
    info = _compile_glob_pattern_cached.cache_info()
    assert info.misses == 1
    assert info.hits == 4


def test_glob_matcher_treats_backslash_as_literal_not_regex_escape():
    """Code gate F2 (MODERATE), r3 delta — the un-sanitized class body
    diverges from the oracle in the FALSE-REFUSAL direction (§3.4a states
    the divergence is "false accept, never false refusal"). `re` reads
    `\\d` as a digit class; `glob`/`fnmatch` read `\\` and `d` as two
    literal members — `_glob_match` must agree with the oracle, not with
    bare `re` semantics."""
    assert _glob_match("src/d.py", "src/[\\d].py") is True
    assert _glob_match("src/9.py", "src/[\\d].py") is False  # not a digit class


def test_glob_matcher_agrees_with_stdlib_glob(tmp_path):
    """F1b: the equivalence control — both oracle preconditions
    (include_hidden=True, files not directories) are required; under the
    default oracle 7 of 13 patterns mismatch. Extended past r3's 13
    patterns (code gate F1/F2): `src/[\\d].py` and `src/[a\\].py` pin the
    class-BODY sanitizing — a backslash-ending balanced class must not
    raise `re.error` (F1), and `\\d` must stay two literal members, never
    a digit class (F2, the false-refusal direction)."""
    tree = tmp_path / "scratch"
    files = [
        "src/app.py",
        "src/a/b/deep.py",
        "src/.secret.py",
        "src/a.b.py",
        "src/^caret.py",
        "src/unbal[.py",
        "src/weird.py",
        "docs/x.md",
        "docs/sub/y.md",
        ".claude/rules.md",
        "src/ab.py",
        "src/aXb.py",
        "src/a.py",
        "src/d.py",
        "src/\\.py",  # a literal-backslash filename — the `[a\].py` member
    ]
    for rel in files:
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")

    patterns = [
        "src/**/*.py",
        "**/*.py",
        "src/*.py",
        "docs/**/*.md",
        "*.py",
        "src/**",
        "**",
        "src/a?b.py",
        "src/[ab]*.py",
        "src/[!a]*.py",
        "src/[^a]*.py",  # a literal `^` class member, not a negation
        "src/[weird].py",
        "src/unbal[.py",
        "src/[\\d].py",  # `\d` must stay two literal members (F2)
        "src/[a\\].py",  # a balanced class whose body ends in `\` (F1)
    ]
    assert len(patterns) == 15

    all_files = []
    for root, _dirs, fnames in os.walk(tree):
        for fn in fnames:
            all_files.append(str((Path(root) / fn).relative_to(tree)))

    mismatches = []
    for pat in patterns:
        oracle = {
            p
            for p in glob_mod.glob(
                pat, root_dir=tree, recursive=True, include_hidden=True
            )
            if (tree / p).is_file()
        }
        for rel in all_files:
            ours = _glob_match(rel, pat)
            theirs = rel in oracle
            if ours != theirs:
                mismatches.append((pat, rel, ours, theirs))

    assert mismatches == []


def test_t2_yes_requires_rules_paths():
    """F2: the check must never be vacuous.

    FW-59: a bare `pytest.raises(ProposalError)` on the `rules_paths=[]`
    leg was vacuous — `_glob_match`'s downstream "match_path matches none
    of rules_paths" check ALSO raises `ProposalError` whenever
    `rules_paths` is empty (`any()` over an empty iterable is always
    `False`), so deleting this check's own `or not rules_paths` clause
    left that leg green too, just via the OTHER check silently
    backstopping it (mutation-verified). Pinned to this check's own
    message ("...rules_paths is missing/empty...") on BOTH legs — the
    fallback's message ("...matches none of rules_paths...") does not
    contain that text, so the fallback firing instead is now visible."""
    g = _base_gates()
    g["t2"] = {"answer": "yes", "evidence": TRUE_QUOTE, "match_path": "src/app.py"}
    g["t4"] = None
    with pytest.raises(ProposalError, match="rules_paths is missing/empty"):
        validate_proposal(proposal_dict(gates=g))  # rules_paths absent
    with pytest.raises(ProposalError, match="rules_paths is missing/empty"):
        validate_proposal(proposal_dict(gates=g, rules_paths=[]))  # empty


def test_roster_unavailable_forces_t3_no_and_evidence_gap():
    """F3: (c) and (d) are distinct failures (FOLD-8).

    Code gate F4 (MODERATE), r3 delta: case (a) must supply
    `flags=["evidence-gap"]` — without it, removing X3's answer-coupling
    check (`t3.answer != "no"`) just lets the NEXT check (flags missing
    "evidence-gap") raise instead, since `_gates_with_t3_yes` carries no
    flags at all, and the test can no longer tell which check refused."""
    g = _gates_with_t3_yes(owner="me")
    g["t3"]["roster_sha"] = ROSTER_UNAVAILABLE
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g, flags=["evidence-gap"]))

    g = _base_gates()
    g["t3"]["roster_sha"] = ROSTER_UNAVAILABLE
    validate_proposal(proposal_dict(gates=g, flags=["evidence-gap"]))

    g = _base_gates()
    g["t3"]["roster_sha"] = ROSTER_UNAVAILABLE
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g, flags=["near-cluster"]))

    g = _base_gates()
    g["t3"]["roster_sha"] = ROSTER_UNAVAILABLE
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))


def test_roster_sha_form():
    """F4."""
    g = _base_gates()
    g["t3"]["roster_sha"] = "not-a-sha-and-not-unavailable"
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["t3"]["roster_sha"] = "sha256:0a1b2c3d4e5f"
    validate_proposal(proposal_dict(gates=g))

    g = _base_gates()
    g["t3"]["roster_sha"] = ROSTER_UNAVAILABLE
    validate_proposal(proposal_dict(gates=g, flags=["evidence-gap"]))


# =========================================================================
# Supplementary — code gate F6 (MINOR), r3 delta: eight production checks
# no test could see. Not tied to a numbered spec criterion; each closes
# one of the eight named gaps.
# =========================================================================


def test_t3_owner_and_scan_terms_null_constraints():
    """`t3.owner` must be null when answer is "no"; `t3.scan_terms` must
    be null when answer is "yes" — the mirror halves of D-series' "owner
    iff yes"/"scan_terms iff no", previously untested."""
    g = _base_gates()  # t3.answer == "no"
    g["t3"]["owner"] = "someone"
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g = _gates_with_t3_yes()  # t3.answer == "yes"
    g["t3"]["scan_terms"] = ["x"]
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))


def test_t2_match_path_required_when_answer_is_yes():
    """`t2.match_path` — non-empty str, required iff yes (Schema-1a) —
    previously exercised only implicitly through X1's own rules_paths
    fixtures, never isolated as its own required-ness rule."""
    g = _base_gates()
    g["t2"] = {"answer": "yes", "evidence": TRUE_QUOTE, "match_path": None}
    g["t4"] = None
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g, rules_paths=["src/**/*.py"]))


# =========================================================================
# Supplementary — FW-58: a follow-up audit found five of the "eight
# production checks no test could see" (the F6 sweep above) were still
# uncovered after that merge. Each test below was mutation-verified
# uncovered on this file's HEAD (full suite: 1354 passed, 5 skipped, 0
# failed, byte-identical with and without the check) before being
# written, including the one below whose surrounding function FW-57/
# FW-63 rewrote the same day — that rewrite never reached this specific
# line.
# =========================================================================


def test_g0_reject_defer_answer_enum():
    """FW-58: `gates.g0.reject`/`gates.g0.defer`.answer's yes/no enum
    check had no test — no fixture in this module ever set either leg's
    answer outside {"yes", "no"} (`_base_gates` ships both at "no"; the
    only other touch, the YAML round-trip test, reads the value back
    without ever writing something else). Mutation-verified: neutering
    the check (`if False:` in place of the enum test) left the full suite
    green — with it gone, `answer="bogus"` reaches `_check_evidence` with
    `required=False` (`"bogus" != "yes"`), and nothing downstream
    objects."""
    for leg in ("reject", "defer"):
        g = _base_gates()
        g["g0"][leg] = {"answer": "bogus", "evidence": None}
        with pytest.raises(ProposalError):
            validate_proposal(proposal_dict(gates=g))


def test_g0_reject_defer_evidence_required_when_yes():
    """FW-58: `gates.g0.reject`/`gates.g0.defer`.evidence — required iff
    the leg's own answer is "yes". No fixture in this module ever set
    either leg's answer to "yes" (`_base_gates` ships both at "no", and
    that's the only value this evidence leaf is ever exercised at).
    Mutation-verified: forcing `required=False` at this call site left
    the full suite green."""
    for leg in ("reject", "defer"):
        g = _base_gates()
        g["g0"][leg] = {"answer": "yes", "evidence": None}
        with pytest.raises(ProposalError):
            validate_proposal(proposal_dict(gates=g))

        g2 = _base_gates()
        g2["g0"][leg] = {"answer": "yes", "evidence": TRUE_QUOTE}
        validate_proposal(proposal_dict(gates=g2))


def test_cost_bearing_evidence_required_when_yes():
    """FW-58: `gates.t1.cost_bearing`.evidence — required iff answer is
    "yes". `_base_gates` ships `cost_bearing.answer: None`, and the only
    other place this leg is touched
    (`test_every_mapping_node_type_checked_before_indexed`'s
    "t1.cost_bearing" case) swaps the whole node for a scalar, which
    raises inside `_mapping` before this line is ever reached —
    `answer == "yes"` was never exercised. Mutation-verified: forcing
    `required=False` at this call site left the full suite green."""
    g = _base_gates()
    g["t1"]["cost_bearing"] = {"answer": "yes", "evidence": None}
    with pytest.raises(ProposalError):
        validate_proposal(proposal_dict(gates=g))

    g2 = _base_gates()
    g2["t1"]["cost_bearing"] = {"answer": "yes", "evidence": TRUE_QUOTE}
    validate_proposal(proposal_dict(gates=g2))


def test_t2_evidence_required_both_ways():
    """FW-58: `gates.t2`.evidence — required BOTH ways (Schema-1a), the
    same rule `t1.field_shaped` gets (D4). Every fixture in this module
    that reaches `_validate_gates` supplies a non-null `t2.evidence`
    (`_base_gates`'s default `quote` parameter on the "no" leg, or an
    explicit `TRUE_QUOTE` on every "yes" fixture elsewhere in this file)
    — `evidence: None` on EITHER answer was never exercised. Mutation-
    verified: forcing `required=False` at this call site left the full
    suite green."""
    for answer in ("no", "yes"):
        g = _base_gates()
        g["t2"] = {"answer": answer, "evidence": None, "match_path": None}
        with pytest.raises(ProposalError):
            validate_proposal(proposal_dict(gates=g))

        g2 = _base_gates()
        if answer == "yes":
            g2["t2"] = {
                "answer": "yes",
                "evidence": TRUE_QUOTE,
                "match_path": "src/app.py",
            }
            g2["t4"] = None
            validate_proposal(proposal_dict(gates=g2, rules_paths=["src/**/*.py"]))
        else:
            g2["t2"] = {"answer": "no", "evidence": TRUE_QUOTE, "match_path": None}
            validate_proposal(proposal_dict(gates=g2))


def test_glob_class_body_escapes_ampersand_tilde_pipe():
    """FW-58: the class-BODY sanitizer escapes `&`/`~`/`|` (§3.4a) because
    `re` has signalled those will gain set-operation meaning inside a
    class — plain literal members to `glob`/`fnmatch` today, so leaving
    them unescaped would be the false-refusal direction (F2) this
    sanitizer exists to avoid. No test pinned the escaping: under CURRENT
    `re` semantics `[&~|]` and `[\\&\\~\\|]` compile and match
    identically (measured — no warning is raised either, on this
    interpreter), so a behavioural assertion through `_glob_match` alone
    cannot discriminate the substitution; only the translated pattern
    SHAPE can — the same strategy
    `test_consecutive_double_star_segments_collapse_before_translation`
    uses for its own forward-looking mechanism. Mutation-verified:
    dropping the substitution left the full suite green — including
    today, in the very function (`_compile_glob_pattern`) FW-57/FW-63
    rewrote, because that rewrite never touched this specific line."""
    pattern = _compile_glob_pattern("src/[&~|]x.py")
    assert "\\&" in pattern.pattern
    assert "\\~" in pattern.pattern
    assert "\\|" in pattern.pattern
    # And the escaping doesn't change what the class matches (F2: still
    # plain literal members to the oracle) — the behavioural control.
    assert _glob_match("src/&x.py", "src/[&~|]x.py") is True
    assert _glob_match("src/zx.py", "src/[&~|]x.py") is False
