"""U-always — the ALWAYS tier becomes a validator refusal
(docs/specs/self-learn/drafts/u-always-gate-refusal-spec.md).

R-ALWAYS-EV (§4.2/§4.3) and R-ALWAYS-FLAG (§4.4), both inside
`_validate_derivation` (`ledger_ops.py`). Fixtures are LOCAL to this
module per §7's fixture note: `support.proposal_dict`'s auto-trace path
(`destination: claude-md`, no `gates=` override) runs `default_trace_for`
AFTER `overrides` and silently DISCARDS a `flags=`/`recommendation=`
override — `_flag_case` below sets the field on the dict AFTER
`proposal_dict` returns, never as an override on that path. `gates=`
callers (trap 1) must instead pass `flags=`/`recommendation=` explicitly,
since supplying `gates=` skips `default_trace_for` (and its own
`flags`/`recommendation`) entirely — every fixture in this module uses
one or the other, never the broken combination.
"""

from __future__ import annotations

import pytest

import support
from self_learn import gates as gates_mod
from self_learn import worker
from self_learn.ledger_ops import ProposalError, validate_proposal
from support import proposal_dict

#: §4.3's normative substrings for R-ALWAYS-EV's message — every one is
#: asserted by T1, verbatim, per the spec.
_R_ALWAYS_EV_SUBSTRINGS = (
    "gates.outcome",
    "ALWAYS",
    "gates.t4.fs.verdict",
    "gates.t4.conduct_mode.answer",
    "gates.e1",
    "Table-1 derives",
    "PATHED",
    "SKILL",
    "defer",
    "no-cheap-surface",
)


def _barren_always(**over) -> dict:
    """support._base_gate_answers() + a t4 whose three signals are all
    non-promoting; `outcome` defaults to ALWAYS."""
    g = support._base_gate_answers()
    g["t4"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None},
        "conduct_mode": {"answer": "no", "evidence": None},
        "fs": {"verdict": "INDETERMINATE", "evidence": None},
    }
    g["e1"] = {"sightings": 1, "post_demand_recurrence": False}
    g["outcome"] = "ALWAYS"
    g.update(over)
    return g


def _flag_case(flag: list) -> dict:
    """R-ALWAYS-FLAG's fixture recipe (§7 trap 2). `destination:
    claude-md` with no `gates=` override goes through the auto-trace
    path, whose `default_trace_for` OVERWRITES a `flags=` override with
    `_always_trace()`'s own `"flags": []` — so the flag is set on the
    dict AFTER `proposal_dict` returns, never passed as an override."""
    p = proposal_dict(scope="user", destination="claude-md")
    p["flags"] = flag
    return p


def test_t1_r_always_ev_fires_on_the_exact_triple():
    data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=_barren_always(),
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(data, scope="project")
    msg = str(exc_info.value)
    for substring in _R_ALWAYS_EV_SUBSTRINGS:
        assert substring in msg, f"{substring!r} missing from: {msg}"
    assert msg.startswith("gates."), msg


def test_t2_conduct_mode_promotes():
    trace = _barren_always()
    trace["t4"]["conduct_mode"] = {"answer": "yes", "evidence": support._RECORD_QUOTE}
    data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=trace,
        recommendation="route",
        flags=[],
    )
    validate_proposal(data, scope="project")  # accepted


@pytest.mark.parametrize("verdict", ["SILENT", "COSTLY"])
def test_t3_fs_verdict_promotes(verdict):
    trace = _barren_always()
    trace["t4"]["fs"] = {"verdict": verdict, "evidence": support._RECORD_QUOTE}
    data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=trace,
        recommendation="route",
        flags=[],
    )
    validate_proposal(data, scope="project")  # accepted


def test_t4_e1_promotes_with_both_boundaries():
    accepted = _barren_always()
    accepted["e1"] = {"sightings": 2, "post_demand_recurrence": True}
    data_accepted = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=accepted,
        recommendation="route",
        flags=[],
    )
    validate_proposal(data_accepted, scope="project")  # accepted

    refused_low_sightings = _barren_always()
    refused_low_sightings["e1"] = {"sightings": 1, "post_demand_recurrence": True}
    data_low = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=refused_low_sightings,
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_low:
        validate_proposal(data_low, scope="project")
    assert "has no promoting evidence" in str(exc_low.value)

    refused_no_recurrence = _barren_always()
    refused_no_recurrence["e1"] = {"sightings": 2, "post_demand_recurrence": False}
    data_no_recur = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=refused_no_recurrence,
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_no_recur:
        validate_proposal(data_no_recur, scope="project")
    assert "has no promoting evidence" in str(exc_no_recur.value)


def test_t5_independent_of_table_1(monkeypatch):
    """Independence from Table-1 (§1.1 item 2, §4.2): even under a
    monkeypatched `_PROMOTING_FS_VERDICTS` that makes Table-1 itself
    derive ALWAYS for the barren trace, R-ALWAYS-EV still refuses it —
    the refusal does not rely on the stated/derived MISMATCH alone.
    Positive control in the same test: under the same monkeypatch, a
    genuinely promoting trace (T3's leg) is still accepted."""
    monkeypatch.setattr(
        gates_mod, "_PROMOTING_FS_VERDICTS", ("SILENT", "COSTLY", "INDETERMINATE")
    )

    data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=_barren_always(),
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(data, scope="project")
    msg = str(exc_info.value)
    for substring in _R_ALWAYS_EV_SUBSTRINGS:
        assert substring in msg, f"{substring!r} missing from: {msg}"

    promoting = _barren_always()
    promoting["t4"]["fs"] = {"verdict": "COSTLY", "evidence": support._RECORD_QUOTE}
    promoting_data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=promoting,
        recommendation="route",
        flags=[],
    )
    validate_proposal(promoting_data, scope="project")  # positive control: accepted


def test_t5b_derived_only_path_independent_of_the_stated_outcome(monkeypatch):
    """Code-gate MAJOR-1 fix: the derived-only path IS reachable through
    `validate_proposal` — a stated non-ALWAYS proposal over a barren t4
    that a loosened Table-1 derives as ALWAYS still hits R-ALWAYS-EV (via
    the `derived_outcome` disjunct alone), because R-ALWAYS-EV sits
    BEFORE the stated-vs-derived mismatch raise. T5 alone could not catch
    this: it reuses T1's stated-ALWAYS fixture, so the `stated_outcome`
    disjunct always masks the `derived_outcome` one there."""
    monkeypatch.setattr(
        gates_mod, "_PROMOTING_FS_VERDICTS", ("SILENT", "COSTLY", "INDETERMINATE")
    )
    trace = _barren_always(outcome="DEMAND")  # STATED non-ALWAYS
    assert gates_mod.expected_outcome(trace, "project") == "ALWAYS"  # in-fixture control
    data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=trace,
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(data, scope="project")
    msg = str(exc_info.value)
    assert "has no promoting evidence" in msg, msg  # NOT the generic mismatch
    for substring in _R_ALWAYS_EV_SUBSTRINGS:
        assert substring in msg, f"{substring!r} missing from: {msg}"


def test_t6_null_t4_gets_the_generic_message_not_r_always_ev():
    base = support._pathed_trace("project", ["src/**/*.py"])
    trace = base["gates"]
    trace["outcome"] = "ALWAYS"  # stated ALWAYS over a null-t4 PATHED derivation
    data = proposal_dict(
        scope="project",
        gates=trace,
        rules_paths=["src/**/*.py"],
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(data, scope="project")
    msg = str(exc_info.value)
    assert "Table-1 derives" in msg
    assert "does not follow from the trace's own answers" in msg
    assert "has no promoting evidence" not in msg


def test_t7_malformed_shapes_refused_by_the_schema_layer_first():
    """Ordering, not totality (§4.1): each leg raises the SCHEMA message,
    never §4.3's evidence-naming one — R-ALWAYS-EV sits one line after
    `gates_mod.expected_outcome`, which is itself one line after
    `_validate_gates` already refused a malformed shape."""
    for t4_override, expected_substring in (
        (123, "gates.t4 must be a mapping"),
        ({}, "gates.t4.depth_behind_rule must be a mapping"),
    ):
        trace = _barren_always()
        trace["t4"] = t4_override
        data = proposal_dict(
            scope="project",
            destination="claude-md",
            gates=trace,
            recommendation="route",
            flags=[],
        )
        with pytest.raises(ProposalError) as exc_info:
            validate_proposal(data, scope="project")
        msg = str(exc_info.value)
        assert expected_substring in msg, msg
        assert "has no promoting evidence" not in msg

    trace = _barren_always()
    trace["e1"] = {"sightings": "two", "post_demand_recurrence": False}
    data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=trace,
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(data, scope="project")
    msg = str(exc_info.value)
    assert "gates.e1.sightings must be an int" in msg, msg
    assert "has no promoting evidence" not in msg


def test_t8_r_always_flag_refuses():
    p = _flag_case(["no-cheap-surface"])
    assert p["flags"] == ["no-cheap-surface"], p["flags"]  # in-fixture assertion (B1)
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(p, scope="user")
    msg = str(exc_info.value)
    assert "no-cheap-surface" in msg
    assert "ALWAYS" in msg
    assert "Table-1 derives" in msg
    assert msg.startswith("gates."), msg


def test_t9_r_always_flag_twin_accepted():
    """Positive control for T8, differing from it ONLY in the flag."""
    p8 = _flag_case(["no-cheap-surface"])
    p9 = _flag_case([])
    only_flags_differ = {k: v for k, v in p8.items() if k != "flags"} == {
        k: v for k, v in p9.items() if k != "flags"
    }
    assert only_flags_differ, (p8, p9)  # in-fixture assertion (B1)
    validate_proposal(p9, scope="user")  # accepted


def test_t10_r_always_flag_does_not_touch_the_legitimate_corner():
    trace = support._demand_trace("user")["gates"]
    data = proposal_dict(
        scope="user",
        destination="reference",
        gates=trace,
        recommendation="defer",
        flags=["no-cheap-surface"],
    )
    assert data["flags"] == ["no-cheap-surface"]  # in-fixture assertion
    validate_proposal(data, scope="user")  # accepted — DEMAND at user, not ALWAYS


def test_t11_repair_classification_unchanged():
    ev_data = proposal_dict(
        scope="project",
        destination="claude-md",
        gates=_barren_always(),
        recommendation="route",
        flags=[],
    )
    with pytest.raises(ProposalError) as exc_ev:
        validate_proposal(ev_data, scope="project")
    ev_message = str(exc_ev.value)

    flag_data = _flag_case(["no-cheap-surface"])
    with pytest.raises(ProposalError) as exc_flag:
        validate_proposal(flag_data, scope="user")
    flag_message = str(exc_flag.value)

    assert worker._repairable(ev_message) == "INELIGIBLE"
    assert worker._repairable(flag_message) == "INELIGIBLE"
