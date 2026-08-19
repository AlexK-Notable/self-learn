"""U-repair acceptance criteria (docs/specs/self-learn/drafts/
u-repair-unattended-elicitation-spec.md §4): A1/A2/A4/A5 (the elicitation
contract; A3 lives in `test_composer.py::test_a19_worked_example_
validates_and_the_check_can_fail`, an in-place extension per spec),
B1-B13 (the repair round), G1-G8 (fabrication containment), D1-D9
(Rule-F attribution), E1-E8 (headroom/backoff), F2/F5/F6 (hygiene —
F1 extends `test_worker.py::test_run_argv_pins` in place, per spec),
H1-H5 (Obs-1, the observable surface).

Fixtures reused from test_worker.py (`env`, `claude_shim`, `seed_pending`,
`shim_writes`, `PROPOSAL_YAML_TEMPLATE`, `_proposal_yaml`) — imported by
NAME, not redefined: pytest resolves a fixture by the name bound in the
requesting module's namespace regardless of which module defines the
function, so `from test_worker import claude_shim, env` makes both
available here unchanged, including F5's multi-invocation shim.

Construction-1 (spec §4, D-group preamble): `snap0` is taken INSIDE
`worker.run()` at S1, and `_written_since` returns only paths whose
digest differs from that snapshot. A file written or stamped BEFORE
`worker.run()` starts is already in `snap0` and Rule-F never sees it —
every foreign-file fixture below therefore stages its file DURING the
model window, from the shim script itself, computing
`normalize.sha_anchor(record.body)` in Python and interpolating it into
the heredoc so the staged file already carries the correct
`record_sha:` line (byte-identical to what `stamp_proposal` would write,
without a nested CLI call or a lock).
"""

from __future__ import annotations

import copy
import inspect
import io
import json
import os
import re
import time
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cli, worker
from self_learn.ledger_ops import (
    ProposalError,
    TRACE_FS_VERDICTS,
    TRACE_OUTCOMES,
    _validate_derivation,
    _validate_gates,
    create_record,
    validate_proposal,
)
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import commit_all, git, make_behavior, proposal_dict

from test_worker import (  # noqa: F401 -- fixtures resolved by name
    PROPOSAL_YAML_TEMPLATE,
    Env,
    _path_without_real_notify_helper,
    claude_cli_shim_worker,
    env,
    seed_pending,
    shim_writes,
)

#: U-fake COMPAT — the ONLY surviving binding of the old fixture name.
#: test_invocation.py is U-seam's and frozen (B-4); it imports
#: `claude_shim` from this module. Delete this line and rename that
#: module's 19 occurrences in U-cleanup (R-1, V-1). Nothing else may
#: request this name — SU3's per-name census is what proves it.
claude_shim = claude_cli_shim_worker


# ===================================================================== #
# Shared fixture-building helpers
# ===================================================================== #

#: Verbatim in every `make_behavior()` record's frontmatter (structural,
#: independent of trigger/instruction text) — the same RECORD-sourced
#: quote convention `support.proposal_dict()` documents for itself.
RECORD_QUOTE = "status: pending"


def _dump(data: dict) -> str:
    """Serialize a proposal dict to YAML text the way a producer would
    emit it — a plain safe dumper, never this project's own
    comment-preserving round-trip loader (we are BUILDING analyst output
    here, not editing an existing file)."""
    y = YAML(typ="safe")
    y.default_flow_style = False
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def _write_script(path: Path, text: str) -> str:
    """A bash heredoc the shim can run to write `text` to `path` verbatim
    (mirrors `test_worker.shim_writes`'s own heredoc shape)."""
    return f"mkdir -p {path.parent} && cat > {path} <<'YAML'\n{text}YAML"


def _valid_trace(env, *, scope="skill:s", destination="claude-md", **overrides) -> dict:
    """A schema-valid, Table-1-derivation-consistent proposal dict for
    `env`'s REAL composed roster (`support.proposal_dict()`'s own dummy
    sha would fail worker's roster-sha honesty leg, which every test here
    exercises through the real worker). `record_sha` is dropped — a model
    never emits one; callers building a Rule-F/foreign fixture add it
    back explicitly via `sha_anchor(record.body)` (Construction-1)."""
    data = proposal_dict(scope=scope, destination=destination, **overrides)
    data.pop("record_sha", None)
    data["gates"]["t3"]["roster_sha"] = worker.skill_roster(env.home).sha
    return data


def _record_for(env, rid: str) -> Record:
    return Record.from_path(env.bucket / "pending" / f"{rid}.md")


def _stamp_sha(env, rid: str) -> str:
    return sha_anchor(_record_for(env, rid).body)


def _foreign_script(env, rid: str, data: dict, path: Path | None = None) -> tuple[str, str, Path]:
    """Construction-1: the shim stands in for a concurrent attended
    session — writes a proposal carrying the record's REAL current
    record_sha, during the model window, from the shim itself. Returns
    ``(script, exact_bytes_written, path)`` so a caller can assert on the
    EXACT text later without a second, independently-ordered `_dump`
    call."""
    data = dict(data)
    data["record_sha"] = _stamp_sha(env, rid)
    path = path or (env.proposals / f"{rid}.yaml")
    text = _dump(data)
    return _write_script(path, text), text, path


def _defect_script(env, rid: str, data: dict) -> str:
    """Round-1-shaped output: no record_sha at all (a model never emits
    one). U-attrib (Stage-1): this is the model's OWN output (round 1 AND
    round 2's edit-in-place repair both target it) — it lands in the
    EXCLUSIVE STAGE, at the SAME path both rounds see, matching GR-d's
    exact-path repair grant."""
    data = dict(data)
    data.pop("record_sha", None)
    path = worker.stage_dir() / f"{rid}.yaml"
    return _write_script(path, _dump(data))


def _t4_missing_target(env, rid: str) -> dict:
    """A genuinely `gates.`-refused, E-1..E-3-ELIGIBLE defect: `t4`'s
    `depth_behind_rule.answer: yes` with no `target` (TE1). Built on a
    DEMAND-outcome base (`destination="reference"`) where
    `depth_behind_rule.answer == "yes"` ALREADY drives the derived
    outcome (Table-1 L4) — nulling only `target` leaves the derivation
    untouched, so the ONLY defect is the missing target, never a second,
    unintended outcome mismatch (measured: an ALWAYS base's
    `depth_behind_rule.answer: no -> yes` flip silently moves the
    Table-1-derived outcome to DEMAND too, which would make the
    'repaired' form still invalid for an unrelated reason)."""
    data = _valid_trace(env, destination="reference")
    data["gates"]["t4"]["depth_behind_rule"]["target"] = None
    return data


def _t4_target_fixed(env, rid: str) -> dict:
    """`_t4_missing_target`'s repaired form — P1: add the absent
    conditionally-required field, change nothing else."""
    data = _t4_missing_target(env, rid)
    data["gates"]["t4"]["depth_behind_rule"]["target"] = "the candidate target"
    return data


def _gates_raises(data: dict, record: Record) -> str:
    with pytest.raises(ProposalError) as exc_info:
        _validate_gates(data, record_text=record.to_text())
    return str(exc_info.value)


def _derivation_raises(data: dict, scope: str) -> str:
    with pytest.raises(ProposalError) as exc_info:
        _validate_derivation(data, scope=scope)
    return str(exc_info.value)


def _validate_proposal_raises(data: dict, record: Record, scope: str | None = None) -> str:
    with pytest.raises(ProposalError) as exc_info:
        validate_proposal(data, record_text=record.to_text(), scope=scope)
    return str(exc_info.value)


def _next_run_scripts(claude_cli_shim_worker, monkeypatch, *scripts, exits=None, sleeps=None):
    """Bind `scripts[i]` (1-indexed) to `CLAUDE_SHIM_SCRIPT_<base+i>` for
    the NEXT `worker.run()` call, where `base` is the shim's CURRENT
    cumulative invocation count. The shim's counter is shared across
    EVERY `worker.run()` call within one test function — it never resets
    mid-test — so a multi-run test that hardcodes `CLAUDE_SHIM_SCRIPT_1`/
    `_2` for its SECOND (or later) `worker.run()` call is silently
    scripting invocations that already happened; this helper computes
    the right indices instead. Also clears the unnumbered
    `CLAUDE_SHIM_SCRIPT`/`CLAUDE_SHIM_EXIT` fallback so a PRIOR phase's
    script can never leak into an invocation THIS phase did not
    explicitly script. Returns `base` so a caller needing the absolute
    invocation index (e.g. for `claude_shim['call_prompt'](n)`) can
    compute `base + i`."""
    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    monkeypatch.delenv("CLAUDE_SHIM_EXIT", raising=False)
    base = claude_cli_shim_worker["count"]()
    for i, script in enumerate(scripts, start=1):
        if script is not None:
            monkeypatch.setenv(f"CLAUDE_SHIM_SCRIPT_{base + i}", script)
    for i, code in (exits or {}).items():
        monkeypatch.setenv(f"CLAUDE_SHIM_EXIT_{base + i}", str(code))
    for i, secs in (sleeps or {}).items():
        monkeypatch.setenv(f"CLAUDE_SHIM_SLEEP_{base + i}", str(secs))
    return base


# ===================================================================== #
# A. The elicitation contract
# ===================================================================== #


def test_a1_setc_tokens_pinned_both_legs(env, claude_cli_shim_worker):
    """A1 — for each member of Set-C and each token in its `token(s)`
    column, two legs: (i) the validator still raises, with the token
    verbatim in the message; (ii) `worker.TRACE_CONDITIONALS` still
    carries the token verbatim. Vacuity guard: >= 14 distinct tokens
    checked, every Set-C row (C1-C14) contributing at least one.
    Absent/broken: deleting a checklist line reddens leg (ii) for the
    member that names it; renaming a validator field reddens leg (i) for
    the same member — neither direction can pass silently."""
    rid = seed_pending(env)
    record = _record_for(env, rid)
    scope = "skill:s"
    base = _valid_trace(env)  # ALWAYS outcome: non-null t4, t3 == "no"

    cases: list[tuple[str, str, str]] = []  # (row_id, token, raised_message)

    # C1 — g0.reject.evidence required iff answer yes (RECORD-sourced).
    d = copy.deepcopy(base)
    d["gates"]["g0"]["reject"] = {"answer": "yes"}
    cases.append(("C1", "gates.g0.reject.evidence", _gates_raises(d, record)))

    # C2 — g0.canon.target non-empty iff answer yes (TARGET-sourced evidence).
    d = copy.deepcopy(base)
    d["gates"]["g0"]["canon"] = {
        "answer": "yes",
        "evidence": "a target-sourced quote long enough",
        "target": None,
    }
    cases.append(("C2", "gates.g0.canon.target", _gates_raises(d, record)))

    # C3 — t1.field_shaped.answer never null.
    d = copy.deepcopy(base)
    d["gates"]["t1"]["field_shaped"] = {"answer": None, "evidence": RECORD_QUOTE}
    cases.append(("C3", "gates.t1.field_shaped.answer", _gates_raises(d, record)))

    # C4 — t1.cost_bearing.answer in {yes,no,null} ONLY (the trap).
    d = copy.deepcopy(base)
    d["gates"]["t1"]["cost_bearing"] = {"answer": "banana"}
    cases.append(("C4", "gates.t1.cost_bearing.answer", _gates_raises(d, record)))

    # C5 — t2.match_path non-empty iff answer yes.
    d = copy.deepcopy(base)
    d["gates"]["t2"] = {"answer": "yes", "evidence": RECORD_QUOTE, "match_path": None}
    cases.append(("C5", "gates.t2.match_path", _gates_raises(d, record)))

    # C6 — t3.scan_terms null iff yes, non-empty list iff no.
    d = copy.deepcopy(base)
    d["gates"]["t3"]["scan_terms"] = None  # t3.answer stays "no"
    cases.append(("C6", "gates.t3.scan_terms", _gates_raises(d, record)))

    # C7 — t3a.depth_behind_rule.target non-empty iff answer yes.
    d = copy.deepcopy(base)
    d["gates"]["t3"] = {
        "answer": "yes",
        "owner": "s",
        "scan_terms": None,
        "roster_sha": worker.skill_roster(env.home).sha,
    }
    d["gates"]["t3a"] = {
        "depth_behind_rule": {
            "answer": "yes",
            "evidence": "a target-sourced quote long enough",
            "target": None,
        },
        "fs": {"verdict": "SILENT", "evidence": RECORD_QUOTE},
    }
    cases.append(("C7", "gates.t3a.depth_behind_rule.target", _gates_raises(d, record)))

    # C8a — t4.depth_behind_rule.target non-empty iff answer yes.
    d = copy.deepcopy(base)
    d["gates"]["t4"]["depth_behind_rule"] = {
        "answer": "yes",
        "evidence": "a target-sourced quote long enough",
        "target": None,
    }
    cases.append(("C8", "gates.t4.depth_behind_rule.target", _gates_raises(d, record)))

    # C8b — t4.conduct_mode.answer never null.
    d = copy.deepcopy(base)
    d["gates"]["t4"]["conduct_mode"] = {"answer": None, "evidence": RECORD_QUOTE}
    cases.append(("C8", "gates.t4.conduct_mode.answer", _gates_raises(d, record)))

    # C9 — fs.verdict in Set-V, never null (t4.fs, same rule as t3a.fs).
    d = copy.deepcopy(base)
    d["gates"]["t4"]["fs"] = {"verdict": None}
    cases.append(("C9", "gates.t4.fs.verdict", _gates_raises(d, record)))

    # C10a — tn.members >= 2 iff answer yes.
    d = copy.deepcopy(base)
    d["gates"]["tn"] = {
        "answer": "yes",
        "terms": [],
        "members": ["lrn-aaaaaaaa"],
        "proposed_name": "probe-skill",
    }
    d["gates"]["t4"] = None
    cases.append(("C10", "gates.tn.members", _gates_raises(d, record)))

    # C10b — tn.proposed_name required iff answer yes.
    d = copy.deepcopy(base)
    d["gates"]["tn"] = {
        "answer": "yes",
        "terms": [],
        "members": ["lrn-aaaaaaaa", "lrn-bbbbbbbb"],
        "proposed_name": None,
    }
    d["gates"]["t4"] = None
    cases.append(("C10", "gates.tn.proposed_name", _gates_raises(d, record)))

    # C11 — e1.sightings must be an int >= 1.
    d = copy.deepcopy(base)
    d["gates"]["e1"] = {"sightings": "one", "post_demand_recurrence": False}
    cases.append(("C11", "gates.e1.sightings", _gates_raises(d, record)))

    # C12 — the DERIVATION leg: outcome must equal what Table-1 derives.
    d = copy.deepcopy(base)
    d["gates"]["outcome"] = "SKILL"
    cases.append(("C12", "gates.outcome", _derivation_raises(d, scope)))

    # C13 — RECORD-sourced evidence must be verbatim-contained.
    d = copy.deepcopy(base)
    d["gates"]["t1"]["field_shaped"]["evidence"] = (
        "a paraphrase that is not verbatim but long enough to pass length"
    )
    cases.append(("C13", "contained in the record", _gates_raises(d, record)))

    # C14 — gates/flags/recommendation each REQUIRED (three tokens).
    d = copy.deepcopy(base)
    d["gates"] = None
    cases.append(("C14", "gates", _gates_raises(d, record)))
    d = copy.deepcopy(base)
    d["flags"] = None
    cases.append(("C14", "flags", _gates_raises(d, record)))
    d = copy.deepcopy(base)
    d["recommendation"] = None
    cases.append(("C14", "recommendation", _gates_raises(d, record)))

    seen_tokens: set[str] = set()
    seen_rows: set[str] = set()
    for row_id, token, message in cases:
        assert token in message, f"{row_id}: token {token!r} not in raised message {message!r}"
        assert token in worker.TRACE_CONDITIONALS, (
            f"{row_id}: token {token!r} not in worker.TRACE_CONDITIONALS"
        )
        seen_tokens.add(token)
        seen_rows.add(row_id)

    assert len(seen_tokens) >= 14, seen_tokens
    assert seen_rows == {f"C{i}" for i in range(1, 15)}, seen_rows


def test_a2_doctrine_examples_exercise_every_conditional_branch():
    """A2 — the doctrine's examples exercise every conditional branch, and
    Pair-1's pairing (§3.2 a) is total and injective (asserted inside
    `_pair_doctrine_examples`, imported from test_composer.py — the SAME
    extraction/pairing logic `A3`'s test relies on, not a second
    definition). Absent/broken: reverting §5.3 to the single all-`no`
    exemplar fails every leg below, naming which; zero extracted blocks
    fails collection loudly (the `assert pairs` guard), not silently."""
    from test_composer import _doctrine_text, _pair_doctrine_examples

    text = _doctrine_text()
    pairs = _pair_doctrine_examples(text)
    assert pairs, "no paired doctrine examples extracted"

    traces = [proposal for proposal, _record in pairs]

    def _find(pred):
        return [t for t in traces if pred(t)]

    # (a) a t3.answer: yes record: owner set, scan_terms null, t3a
    # populated, t4 null.
    t3_yes = _find(
        lambda t: t["gates"]["t3"]["answer"] == "yes"
        and t["gates"]["t3"].get("owner")
        and t["gates"]["t3"].get("scan_terms") is None
        and t["gates"].get("t3a") is not None
        and t["gates"].get("t4") is None
    )
    assert t3_yes, "no example exhibits t3.answer: yes on its full triggering shape"

    # (b) depth_behind_rule.answer: yes carrying BOTH target and evidence
    # (checked across both t3a and t4 nodes, either satisfies the union).
    def _dbr_yes_with_both(t):
        for node_name in ("t3a", "t4"):
            node = t["gates"].get(node_name)
            if not node:
                continue
            dbr = node.get("depth_behind_rule")
            if not dbr:
                continue
            if (
                dbr.get("answer") == "yes"
                and dbr.get("target")
                and dbr.get("evidence")
            ):
                return True
        return False

    assert any(_dbr_yes_with_both(t) for t in traces), (
        "no example exhibits depth_behind_rule.answer: yes with both target and evidence"
    )

    # (c) conduct_mode.answer: yes carrying evidence.
    conduct_yes = _find(
        lambda t: (t["gates"].get("t4") or {}).get("conduct_mode", {}).get("answer")
        == "yes"
        and (t["gates"].get("t4") or {}).get("conduct_mode", {}).get("evidence")
    )
    assert conduct_yes, "no example exhibits conduct_mode.answer: yes with evidence"

    # (d) an fs.verdict in TRACE_FS_VERDICTS other than INDETERMINATE,
    # carrying evidence (either t3a.fs or t4.fs).
    def _fs_non_indeterminate(t):
        for node_name in ("t3a", "t4"):
            node = t["gates"].get(node_name)
            if not node:
                continue
            fs = node.get("fs")
            if not fs:
                continue
            verdict = fs.get("verdict")
            if verdict in TRACE_FS_VERDICTS and verdict != "INDETERMINATE" and fs.get(
                "evidence"
            ):
                return True
        return False

    assert any(_fs_non_indeterminate(t) for t in traces), (
        "no example exhibits a non-INDETERMINATE fs.verdict with evidence"
    )


def test_a4_checklist_sits_where_attention_is(env):
    """A4 (spec §3.2 b3) — the checklist sits where attention is. In the
    composed BATCH prompt, `TRACE_CONDITIONALS` must appear exactly once,
    at an offset greater than the doctrine section's and less than
    `=== PENDING RECORDS ===`. Absent/broken: a builder who appends the
    constant to the preamble at the top of the prompt (the natural place)
    puts it ~200 KB from the records and fails the ordering leg (M4).
    Also assert it appears in the prompt `compose_single_prompt` returns
    (§3.2 b3)."""
    from self_learn.ledger import discover_buckets
    from self_learn.ledger_ops import queue as _queue

    rid = seed_pending(env)
    (bucket,) = [b for b in discover_buckets(env.home) if b.name == "s"]
    (entry,) = _queue(bucket)

    batch_prompt, _roster = worker.compose_batch_prompt(env.home, [entry])
    assert batch_prompt.count(worker.TRACE_CONDITIONALS) == 1

    doctrine_offset = batch_prompt.find("=== ROUTING DOCTRINE ===")
    trace_offset = batch_prompt.find(worker.TRACE_CONDITIONALS)
    pending_offset = batch_prompt.find("=== PENDING RECORDS ===")
    assert doctrine_offset != -1 and pending_offset != -1
    assert doctrine_offset < trace_offset < pending_offset, (
        doctrine_offset,
        trace_offset,
        pending_offset,
    )

    single_prompt, _roster2 = worker.compose_single_prompt(env.home, entry)
    assert worker.TRACE_CONDITIONALS in single_prompt


def test_a5_setE_classifier_pinned_to_table_e(env, claude_cli_shim_worker):
    """A5 — Set-E's classifier (`_repairable`) is pinned to Table-E
    (TE1-TE21), quantifying over Table-E and NOT over Set-C (r1 gate
    BLOCKER 2: `C14`'s refusals never begin with `gates.` and `C12` has
    one eligible leg and one ineligible one — Set-C is unsatisfiable as a
    quantifier here). Two legs per row: (i) the refusal is still
    producible with the row's stated prefix; (ii) `_repairable` returns
    the row's stated class. Vacuity guard: >= 10 ELIGIBLE, >= 8
    INELIGIBLE — a classifier stuck at True or False cannot pass either
    floor."""
    rid = seed_pending(env)
    record = _record_for(env, rid)
    scope = "skill:s"
    roster = worker.skill_roster(env.home)
    base = _valid_trace(env)

    rows: list[tuple[str, str, str, str]] = []  # (te_id, class, prefix, message)

    def add(te_id, cls, prefix, message):
        rows.append((te_id, cls, prefix, message))

    # TE1 (=C8a)
    d = copy.deepcopy(base)
    d["gates"]["t4"]["depth_behind_rule"] = {
        "answer": "yes", "evidence": "a target quote long enough", "target": None,
    }
    add("TE1", "ELIGIBLE", "gates.t4.depth_behind_rule.target must be non-empty text when answer is yes",
        _gates_raises(d, record))

    # TE2 (=C8b)
    d = copy.deepcopy(base)
    d["gates"]["t4"]["conduct_mode"] = {"answer": None, "evidence": RECORD_QUOTE}
    add("TE2", "ELIGIBLE", "gates.t4.conduct_mode.answer must be 'yes' or 'no', got",
        _gates_raises(d, record))

    # TE3 (=C9)
    d = copy.deepcopy(base)
    d["gates"]["t4"]["fs"] = {"verdict": None}
    add("TE3", "ELIGIBLE", "gates.t4.fs.verdict must be one of", _gates_raises(d, record))

    # TE4 — t3.scan_terms must be null when answer is yes.
    d = copy.deepcopy(base)
    d["gates"]["t3"] = {
        "answer": "yes", "owner": "s", "scan_terms": ["leftover", "terms"],
        "roster_sha": roster.sha,
    }
    add("TE4", "ELIGIBLE", "gates.t3.scan_terms must be null when answer is yes",
        _gates_raises(d, record))

    # TE5 (=C13, on field_shaped specifically)
    d = copy.deepcopy(base)
    d["gates"]["t1"]["field_shaped"]["evidence"] = (
        "a paraphrase that is not verbatim but long enough to pass length"
    )
    add(
        "TE5", "ELIGIBLE",
        "gates.t1.field_shaped.evidence is not contained in the record it claims to quote",
        _gates_raises(d, record),
    )

    # TE6 (=C3)
    d = copy.deepcopy(base)
    d["gates"]["t1"]["field_shaped"] = {"answer": None, "evidence": RECORD_QUOTE}
    add("TE6", "ELIGIBLE", "gates.t1.field_shaped.answer must be 'yes' or 'no', got",
        _gates_raises(d, record))

    # TE7 (=C11)
    d = copy.deepcopy(base)
    d["gates"]["e1"] = {"sightings": "one", "post_demand_recurrence": False}
    add("TE7", "ELIGIBLE", "gates.e1.sightings must be an int", _gates_raises(d, record))

    # TE8 (=C10a)
    d = copy.deepcopy(base)
    d["gates"]["tn"] = {
        "answer": "yes", "terms": [], "members": ["lrn-aaaaaaaa"], "proposed_name": "probe-skill",
    }
    d["gates"]["t4"] = None
    add("TE8", "ELIGIBLE", "gates.tn.members must have", _gates_raises(d, record))

    # TE9 — t2.match_path matches none of rules_paths.
    d = copy.deepcopy(base)
    d["gates"]["t2"] = {
        "answer": "yes", "evidence": RECORD_QUOTE, "match_path": "totally/different/path.txt",
    }
    d["gates"]["t4"] = None
    d["rules_paths"] = ["src/**/*.ts"]
    add("TE9", "ELIGIBLE", "matches none of rules_paths", _gates_raises(d, record))

    # TE10 (=C7)
    d = copy.deepcopy(base)
    d["gates"]["t3"] = {
        "answer": "yes", "owner": "s", "scan_terms": None, "roster_sha": roster.sha,
    }
    d["gates"]["t3a"] = {
        "depth_behind_rule": {
            "answer": "yes", "evidence": "a target quote long enough", "target": None,
        },
        "fs": {"verdict": "SILENT", "evidence": RECORD_QUOTE},
    }
    add("TE10", "ELIGIBLE", "gates.t3a.depth_behind_rule.target must be non-empty text when answer is yes",
        _gates_raises(d, record))

    # TE11 — the ENUM leg (schema-level, via _validate_gates).
    d = copy.deepcopy(base)
    d["gates"]["outcome"] = "BOGUS"
    add("TE11", "ELIGIBLE", "gates.outcome must be one of", _gates_raises(d, record))

    # TE12 — the DERIVATION leg (via _validate_derivation), INELIGIBLE.
    d = copy.deepcopy(base)
    d["gates"]["outcome"] = "SKILL"
    add("TE12", "INELIGIBLE", "but Table-1 derives", _derivation_raises(d, scope))

    # TE13 — roster_sha shape leg.
    d = copy.deepcopy(base)
    d["gates"]["t3"]["roster_sha"] = "not-a-sha"
    add("TE13", "INELIGIBLE", "gates.t3.roster_sha must match sha256:", _gates_raises(d, record))

    # TE14 — roster_sha 'unavailable' but answer is yes.
    d = copy.deepcopy(base)
    d["gates"]["t3"] = {
        "answer": "yes", "owner": "s", "scan_terms": None, "roster_sha": "unavailable",
    }
    d["gates"]["t3a"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None},
        "fs": {"verdict": "SILENT", "evidence": RECORD_QUOTE},
    }
    add("TE14", "INELIGIBLE", "gates.t3.roster_sha is 'unavailable' but answer is",
        _gates_raises(d, record))

    # TE15 — worker._roster_sha_dishonest Leg A (value dishonesty): a
    # well-shaped sha that is simply not THIS run's composed roster sha.
    d = copy.deepcopy(base)
    d["gates"]["t3"]["roster_sha"] = "sha256:0123456789ab"
    msg15 = worker._roster_sha_dishonest(d, roster)
    assert msg15 is not None
    add("TE15", "INELIGIBLE", "does not match this run's composed roster sha", msg15)

    # TE16 (=C14, the trace-less refusal — INELIGIBLE by principle, §3.4).
    d = copy.deepcopy(base)
    d["gates"] = None
    add("TE16", "INELIGIBLE", "proposal is missing the required decision-trace key",
        _gates_raises(d, record))

    # TE17 — flags must be a list.
    d = copy.deepcopy(base)
    d["flags"] = "not-a-list"
    add("TE17", "INELIGIBLE", "flags must be a list, got", _gates_raises(d, record))

    # TE18 — recommendation must be one of.
    d = copy.deepcopy(base)
    d["recommendation"] = "bogus"
    add("TE18", "INELIGIBLE", "recommendation must be one of", _gates_raises(d, record))

    # TE19 — destination must be one of (validate_proposal, not _validate_gates).
    d = copy.deepcopy(base)
    d["destination"] = "bogus"
    add("TE19", "INELIGIBLE", "destination must be one of",
        _validate_proposal_raises(d, record, scope))

    # TE20 — no pending record for <id> (raised by worker._check_proposal_file
    # itself, not by ledger_ops — a different code path than every row above).
    path = env.proposals / "lrn-ffffffff.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(copy.deepcopy(base)), encoding="utf-8")
    # dest=path: a self-referential (already-at-destination) check, so
    # the "no pending record" leg fires rather than ST-e's "no batch
    # record" litter check (a different code path this row is not about).
    verdict = worker._check_proposal_file(env.home, path, roster, {}, path)
    assert verdict.error is not None
    add("TE20", "INELIGIBLE", "no pending record for", verdict.error)

    # TE21 — a card: refusal (via validate_proposal, before _validate_gates
    # even runs).
    d = copy.deepcopy(base)
    d["card"] = {}
    add("TE21", "INELIGIBLE", "card must be a non-empty mapping of sections",
        _validate_proposal_raises(d, record, scope))

    eligible_count = 0
    ineligible_count = 0
    seen = set()
    for te_id, cls, prefix, message in rows:
        assert prefix in message, f"{te_id}: prefix {prefix!r} not in {message!r}"
        got = worker._repairable(message)
        assert got == cls, f"{te_id}: _repairable returned {got!r}, expected {cls!r} for {message!r}"
        seen.add(te_id)
        if cls == "ELIGIBLE":
            eligible_count += 1
        else:
            ineligible_count += 1

    assert seen == {f"TE{i}" for i in range(1, 22)}, seen
    assert eligible_count >= 10, eligible_count
    assert ineligible_count >= 8, ineligible_count


# ===================================================================== #
# B. The repair round
# ===================================================================== #


def test_b1_dry_check_and_real_check_are_one_function_source_read():
    """B1 (source-read leg) — the per-file validation body appears once:
    `_check_proposal_file` is the ONLY place `validate_proposal(` is
    called inside the S4/S8 per-path loop, and neither `_dry_check_batch`
    (S4) nor `_validate_written` (S8) calls it directly — both route
    through the one shared function. Absent/broken: a builder who copies
    the validation body into a second `_dry_check` passes the behavioural
    leg below (it still mutates nothing) but fails THIS leg, which is the
    point — the copy would drift silently."""
    src_check = inspect.getsource(worker._check_proposal_file)
    assert src_check.count("validate_proposal(") == 1

    src_dry = inspect.getsource(worker._dry_check_batch)
    assert "validate_proposal(" not in src_dry
    assert "_check_proposal_file(" in src_dry

    src_real = inspect.getsource(worker._validate_written)
    assert "validate_proposal(" not in src_real
    assert "_check_proposal_file(" in src_real


def test_b1_dry_check_mutates_nothing(env):
    """B1 (behavioural leg) — after S4 on a batch containing one valid and
    one invalid file, the on-disk bytes of BOTH files are unchanged, no
    `record_sha` has been stamped, and `git status --porcelain` in the
    ledger is what it was."""
    rid_valid = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    rid_invalid = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    valid_path = env.proposals / f"{rid_valid}.yaml"
    invalid_path = env.proposals / f"{rid_invalid}.yaml"
    valid_path.parent.mkdir(parents=True, exist_ok=True)
    valid_path.write_text(_dump(_valid_trace(env)), encoding="utf-8")
    bad = _valid_trace(env)
    bad["gates"]["t4"]["depth_behind_rule"] = {"answer": "yes", "evidence": "x" * 20, "target": None}
    invalid_path.write_text(_dump(bad), encoding="utf-8")
    commit_all(env.home, "seed proposals for B1")

    before_valid = valid_path.read_bytes()
    before_invalid = invalid_path.read_bytes()
    status_before = git(env.home, "status", "--porcelain").stdout

    roster = worker.skill_roster(env.home)
    dest_map = {valid_path: valid_path, invalid_path: invalid_path}
    verdicts = worker._dry_check_batch(env.home, [valid_path, invalid_path], roster, dest_map)

    assert valid_path.read_bytes() == before_valid
    assert invalid_path.read_bytes() == before_invalid
    assert "record_sha:" not in valid_path.read_text(encoding="utf-8")
    assert git(env.home, "status", "--porcelain").stdout == status_before
    assert verdicts[valid_path].error is None
    assert verdicts[invalid_path].error is not None


def test_b2_world_all_valid_output(env, claude_cli_shim_worker, monkeypatch):
    """B2 — world: all-valid output. `claude` invoked exactly once,
    `result.repair_attempted is False`, the log carries
    `repair round skipped`, every proposal landed stamped."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    result = worker.run(env.home)
    assert claude_cli_shim_worker["count"]() == 1
    assert result.repair_attempted is False
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "repair round skipped" in log_text
    assert result.proposed == [rid]
    text = (env.proposals / f"{rid}.yaml").read_text(encoding="utf-8")
    assert "record_sha: sha256:" in text


def test_b3_world_all_invalid_output_cleared(env, claude_cli_shim_worker, monkeypatch):
    """B3 — world: all-invalid output, cleared. Call #1 writes traces
    missing `t4.depth_behind_rule.target`; call #2 writes the same files
    with the target added. Two invocations; `repair round: N of N
    refusals cleared`; every proposal landed stamped; `result.status ==
    'ok'`. Absent/broken: a build that never re-reads the repaired files
    (S7 reusing `written1` instead of recomputing from `snap0`) lands
    nothing."""
    ra = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    rb = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    round1 = "\n".join(
        _defect_script(env, rid, _t4_missing_target(env, rid)) for rid in (ra, rb)
    )
    round2 = "\n".join(
        _defect_script(env, rid, _t4_target_fixed(env, rid)) for rid in (ra, rb)
    )
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", round2)
    result = worker.run(env.home)
    assert claude_cli_shim_worker["count"]() == 2
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "repair round: 2 of 2 refusals cleared" in log_text
    assert sorted(result.proposed) == [ra, rb]
    for rid in (ra, rb):
        text = (env.proposals / f"{rid}.yaml").read_text(encoding="utf-8")
        assert "record_sha: sha256:" in text
    assert result.status == "ok"


def test_b4_world_mixed_and_repair_prompt_scoped(env, claude_cli_shim_worker, monkeypatch):
    """B4 — world: mixed, and the repair prompt is scoped. One valid
    file, two invalid. The repair prompt contains the two invalid paths
    and their record texts, and does NOT contain the valid path; the
    valid file's bytes are unchanged after the run; both repaired files
    land. Absent/broken: a build that hands the model the whole batch
    fails the exclusion leg."""
    r_valid = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_bad1 = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    r_bad2 = seed_pending(env, "lrn-0000cccc", created_at="2026-07-03T00:00:00Z")
    round1 = "\n".join([
        shim_writes(env, r_valid),
        _defect_script(env, r_bad1, _t4_missing_target(env, r_bad1)),
        _defect_script(env, r_bad2, _t4_missing_target(env, r_bad2)),
    ])
    round2 = "\n".join([
        _defect_script(env, r_bad1, _t4_target_fixed(env, r_bad1)),
        _defect_script(env, r_bad2, _t4_target_fixed(env, r_bad2)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", round2)
    valid_path = env.proposals / f"{r_valid}.yaml"

    # The spec's "valid file's bytes are unchanged" leg is unsatisfiable
    # byte-for-byte: S8 re-stamps `record_sha` on every landed proposal,
    # valid ones included, so a raw before/after equality check would
    # fail on the stamp alone even on a correct build. Asserted instead,
    # honestly: the valid path never appears in the repair prompt (so
    # nothing in this run's control flow could have rewritten its BODY),
    # and it lands with a real stamp below.
    result = worker.run(env.home)
    assert claude_cli_shim_worker["count"]() == 2

    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    # U-attrib (GR-d): the repair round's exact-path grants — and this
    # prompt's per-file paths — now name STAGED files, not ledger ones.
    assert str(worker.stage_dir() / f"{r_bad1}.yaml") in prompt2
    assert str(worker.stage_dir() / f"{r_bad2}.yaml") in prompt2
    assert str(valid_path) not in prompt2
    record1 = _record_for(env, r_bad1)
    record2 = _record_for(env, r_bad2)
    assert record1.to_text() in prompt2
    assert record2.to_text() in prompt2

    assert sorted(result.proposed) == sorted([r_valid, r_bad1, r_bad2])
    text_valid = valid_path.read_text(encoding="utf-8")
    assert "record_sha: sha256:" in text_valid


def _long_containment_defect(env) -> dict:
    """A genuinely-eligible (`gates.` prefix, no roster_sha/Table-1-derives
    exclusion, §3.4 E-1..E-3) defect whose refusal message is >= 80 chars
    (gate NOTE fold, B5/M9): a RECORD-sourced containment failure on
    `t1.field_shaped.evidence`. Measured: 148 chars — the default
    `_t4_missing_target` shape's message is only 75, under M9's 80-char
    truncation cutoff, so it could never make that mutation bite."""
    data = _valid_trace(env)
    data["gates"]["t1"]["field_shaped"]["evidence"] = (
        "a paraphrase that is not verbatim but long enough to pass length"
    )
    return data


def test_b5_refusal_line_matches_delete_line(env, claude_cli_shim_worker, monkeypatch):
    """B5 — the refusal line handed to the model is the one the log would
    print. Run once with SELF_LEARN_REPAIR=0 and capture the
    `run: invalid worker output X deleted (<reason>)` line; run again
    with repairs enabled on an identical fixture and capture the refusal
    string embedded in the repair prompt. String equality. Uses
    `_long_containment_defect` (>= 80 chars) rather than
    `_t4_missing_target` (75 chars) so M9's 80-char truncation mutation
    actually reddens this leg."""
    rid_disabled = seed_pending(env, "lrn-0000aaaa")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT", _defect_script(env, rid_disabled, _long_containment_defect(env))
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    delete_line = next(
        ln for ln in log_text.splitlines() if f"invalid worker output {rid_disabled}.yaml deleted" in ln
    )
    reason = delete_line.split("deleted (", 1)[1].rsplit(")", 1)[0]
    assert len(reason) >= 80, f"fixture refusal is only {len(reason)} chars — too short to pin M9"

    monkeypatch.delenv("SELF_LEARN_REPAIR")
    rid_enabled = seed_pending(env, "lrn-0000bbbb")
    base = _next_run_scripts(
        claude_cli_shim_worker, monkeypatch,
        _defect_script(env, rid_enabled, _long_containment_defect(env)),
    )
    worker.run(env.home)
    prompt2 = claude_cli_shim_worker["call_prompt"](claude_cli_shim_worker["count"]())
    assert claude_cli_shim_worker["count"]() == base + 2  # batch, then repair
    assert f"refusal: {reason}" in prompt2


def test_b6_orphaned_record_mid_run(env, claude_cli_shim_worker, monkeypatch):
    """B6 — world: orphaned record mid-run. The shim writes a proposal and
    then resolves its record (moves pending/lrn-X.md away). The
    `no pending record` refusal is classified ineligible, does not appear
    in any repair prompt, and the file is deleted with the line the
    delete path actually prints. Does NOT assert `orphan proposal ...
    swept` — that line comes from `_still_pending`, which globs
    `proposals/` AFTER `_validate_written` has already unlinked this
    path, so it never fires for a path that WAS in `written` (r1 gate
    NOTE 10)."""
    rid = seed_pending(env)
    other = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    resolve_script = (
        f"mkdir -p {env.bucket / 'routed'} && "
        f"git -C {env.home} mv {env.bucket / 'pending' / f'{rid}.md'} "
        f"{env.bucket / 'routed' / f'{rid}.md'} 2>/dev/null || "
        f"mv {env.bucket / 'pending' / f'{rid}.md'} {env.bucket / 'routed' / f'{rid}.md'}"
    )
    round1 = "\n".join([
        _defect_script(env, rid, _t4_missing_target(env, rid)),
        resolve_script,
        _defect_script(env, other, _t4_missing_target(env, other)),
    ])
    round2 = _defect_script(env, other, _t4_target_fixed(env, other))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", round2)
    result = worker.run(env.home)

    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    assert str(env.proposals / f"{rid}.yaml") not in prompt2
    assert f"{rid}.yaml" in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert f"run: invalid worker output {rid}.yaml deleted (no pending record for {rid})" in log_text
    assert f"run: orphan proposal {rid}.yaml swept" not in log_text


def test_b7_repair_round_times_out(env, claude_cli_shim_worker, monkeypatch):
    """B7 — world: the repair round itself times out. Shim call #2 sleeps
    past `SELF_LEARN_REPAIR_TIMEOUT_SECS` (~1s). The run completes;
    round-1's valid files still land; still-invalid files are deleted
    with the ordinary line; `result.status` reflects what landed.
    Absent/broken: a build that lets TimeoutExpired escape kills the run
    and loses round-1's valid output too."""
    r_valid = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_bad = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    round1 = "\n".join([
        shim_writes(env, r_valid),
        _defect_script(env, r_bad, _t4_missing_target(env, r_bad)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv("CLAUDE_SHIM_SLEEP_2", "1")
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "0.2")
    result = worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair claude timed out after" in log_text
    assert result.proposed == [r_valid]
    assert f"{r_bad}.yaml" in result.invalid_deleted
    assert result.status == "ok"


def test_b8_world_repair_output_still_invalid(env, claude_cli_shim_worker, monkeypatch):
    """B8 — world: repair output is still invalid. Call #2 writes a
    DIFFERENT-BYTES defect back — same missing-target defect, different
    `rationale` — not a byte-identical resend (gate MAJOR 1: a
    byte-identical round 2 makes `touched2` empty for this file, which
    collapses "count the file changed" and "count landed valid" into the
    same result and hides a build that counts the former instead of the
    latter). `repair round: 0 of N refusals cleared`, the files are
    deleted, and (with nothing else landing) `result.status == 'failed'`
    and the failure counter increments."""
    rid = seed_pending(env)
    defect = _t4_missing_target(env, rid)
    defect2 = copy.deepcopy(defect)
    defect2["rationale"] = "a second, still-invalid attempt at fixing this"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, defect))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, defect2))
    result = worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "repair round: 0 of 1 refusals cleared" in log_text
    assert result.status == "failed"
    assert not (env.proposals / f"{rid}.yaml").exists()
    assert worker._read_failure_count() == 1


def test_b9_kill_switch_disables_composition(env, claude_cli_shim_worker, monkeypatch):
    """B9 — the kill switch is exact, and switches off COMPOSITION, not
    just the call. With SELF_LEARN_REPAIR=0 on an entirely-invalid
    fixture, all five: one invocation; the disabled log line and no
    `repair round —` line; the narrowed settings file does NOT exist;
    the repair-prompt composer was never called; the concrete RunResult
    shape, including `touched == [<every fixture PATH>]` — deletions ARE
    in `touched` by design."""
    rid = seed_pending(env)
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    composer_calls = []
    orig = worker._compose_repair_prompt
    monkeypatch.setattr(
        worker,
        "_compose_repair_prompt",
        lambda *a, **k: composer_calls.append(1) or orig(*a, **k),
    )
    result = worker.run(env.home)

    assert claude_cli_shim_worker["count"]() == 1
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair round disabled (SELF_LEARN_REPAIR=0)" in log_text
    assert "run: repair round —" not in log_text
    assert not worker._p("worker.repair.settings.json").exists()
    assert composer_calls == []

    assert result.status == "failed"
    assert result.proposed == []
    assert result.merge_proposed == []
    assert result.invalid_deleted == [f"{rid}.yaml"]
    # U-attrib (Obs-2/OB3's type leg): a discarded STAGED file was never
    # ledger truth — `_stage_discard` never appends to `touched` (unlike
    # `_git_rm_or_unlink`'s old ledger-delete shape this line used to
    # pin) — nothing landed, nothing to stage/commit.
    assert result.touched == []
    assert result.repair_attempted is False
    assert result.repair_eligible == 0
    assert result.repair_cleared == 0
    assert result.foreign_left == []


def test_b10_exactly_one_repair_round_never_recursive(env, claude_cli_shim_worker, monkeypatch):
    """B10 — exactly one round, never recursive. A fixture where call #2's
    output is invalid must produce exactly TWO invocations, never three."""
    rid = seed_pending(env)
    defect = _t4_missing_target(env, rid)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, defect))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, defect))
    worker.run(env.home)
    assert claude_cli_shim_worker["count"]() == 2


def test_b11_ineligible_refusals_never_reach_a_model(env, claude_cli_shim_worker, monkeypatch):
    """B11 — ineligible refusals never reach a model, end-to-end through
    `run` (A5 pins the classifier in isolation; this pins that the
    classification is actually consulted). One sub-case each for
    E-INELIGIBLE-1 (roster-sha), E-INELIGIBLE-2 (outcome-derivation
    mismatch), E-INELIGIBLE-3 (a card: refusal), E-INELIGIBLE-5 (a
    secret-scan hit), E-INELIGIBLE-7 (a merge refusal): the file's path
    does not appear in any repair prompt and is deleted with today's
    line. A genuinely-eligible sibling defect is included in each
    sub-case so a real repair round (and a real prompt) actually runs.
    Each sub-case seeds its OWN unique eligible record — the SAME `env`
    is reused across all five, so a repeated id would collide with an
    earlier sub-case's still-pending record; each sub-case's scripts are
    bound via `_next_run_scripts` since the shim's invocation counter is
    cumulative across all five `worker.run()` calls in this test."""

    def _run_subcase(label, eligible_rid, bad_script):
        round1 = "\n".join([
            _defect_script(env, eligible_rid, _t4_missing_target(env, eligible_rid)),
            bad_script,
        ])
        round2 = _defect_script(env, eligible_rid, _t4_target_fixed(env, eligible_rid))
        base = _next_run_scripts(claude_cli_shim_worker, monkeypatch, round1, round2)
        result = worker.run(env.home)
        assert claude_cli_shim_worker["count"]() == base + 2, label
        prompt2 = claude_cli_shim_worker["call_prompt"](base + 2)
        return result, prompt2

    # E-INELIGIBLE-1: roster-sha refusal.
    e1 = seed_pending(env, "lrn-0000e001", created_at="2026-07-01T00:00:00Z")
    r1 = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    d = _valid_trace(env)
    d["gates"]["t3"]["roster_sha"] = "sha256:0123456789ab"  # well-shaped, wrong
    script = _defect_script(env, r1, d)
    result, prompt2 = _run_subcase("roster-sha", e1, script)
    assert str(env.proposals / f"{r1}.yaml") not in prompt2
    assert f"{r1}.yaml" in result.invalid_deleted

    # E-INELIGIBLE-2: outcome-derivation mismatch.
    e2 = seed_pending(env, "lrn-0000e002", created_at="2026-07-08T00:00:00Z")
    r2 = seed_pending(env, "lrn-0000cccc", created_at="2026-07-09T00:00:00Z")
    d = _valid_trace(env)
    d["gates"]["outcome"] = "SKILL"
    script = _defect_script(env, r2, d)
    result, prompt2 = _run_subcase("derivation", e2, script)
    assert str(env.proposals / f"{r2}.yaml") not in prompt2
    assert f"{r2}.yaml" in result.invalid_deleted

    # E-INELIGIBLE-3: a card: refusal.
    e3 = seed_pending(env, "lrn-0000e003", created_at="2026-07-15T00:00:00Z")
    r3 = seed_pending(env, "lrn-0000dddd", created_at="2026-07-16T00:00:00Z")
    d = _valid_trace(env)
    d["card"] = {}
    script = _defect_script(env, r3, d)
    result, prompt2 = _run_subcase("card", e3, script)
    assert str(env.proposals / f"{r3}.yaml") not in prompt2
    assert f"{r3}.yaml" in result.invalid_deleted

    # E-INELIGIBLE-5: a secret-scan hit.
    e5 = seed_pending(env, "lrn-0000e005", created_at="2026-07-22T00:00:00Z")
    r5 = seed_pending(env, "lrn-0000eeee", created_at="2026-07-23T00:00:00Z")
    d = _valid_trace(env)
    d["rationale"] = "use password = hunter2secret9 for this"
    script = _defect_script(env, r5, d)
    result, prompt2 = _run_subcase("secret-scan", e5, script)
    assert str(env.proposals / f"{r5}.yaml") not in prompt2
    assert f"{r5}.yaml" in result.invalid_deleted

    # E-INELIGIBLE-7: a merge refusal.
    e7 = seed_pending(env, "lrn-0000e007", created_at="2026-07-29T00:00:00Z")
    r7a = seed_pending(env, "lrn-0000ffff", created_at="2026-07-30T00:00:00Z")
    r7b = seed_pending(env, "lrn-00007777", created_at="2026-07-31T00:00:00Z")
    merge_path = worker.stage_dir() / "merge-00000001.yaml"
    bad_merge = (
        f"cluster_id: merge-00000001\n"
        f"records: [{r7a}, {r7b}]\n"
        f"suggested_survivor: lrn-notinrecords\n"
        f"rationale: same lesson twice\n"
        f"model: claude-sonnet-5\n"
        f"analyzed_at: '2026-07-13T02:10:00Z'\n"
    )
    script = _write_script(merge_path, bad_merge)
    result, prompt2 = _run_subcase("merge", e7, script)
    assert str(merge_path) not in prompt2
    assert "merge-00000001.yaml" in result.invalid_deleted


def test_b12_repair_prompt_carries_checklist_and_rules(env, claude_cli_shim_worker, monkeypatch):
    """B12 (r1 gate BLOCKER 3) — the repair prompt carries the two things
    that make it work: `worker.TRACE_CONDITIONALS` appears verbatim and
    exactly once; the first-problem-only statement (`only the FIRST
    problem`); Set-P/Set-Q are stated (`do not change`, `only the files
    listed`). Absent/broken: a repair prompt that is "here is the file
    and the error, fix it" passes B3-B5 and fails all three legs here."""
    rid = seed_pending(env)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid))
    )
    worker.run(env.home)
    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    assert prompt2.count(worker.TRACE_CONDITIONALS) == 1
    # Leg 2 (gate MAJOR 3): TRACE_CONDITIONALS' OWN text independently
    # contains "only the FIRST problem" (its own first-problem-only
    # sentence), so checking the composed prompt AS A WHOLE cannot tell
    # the template's own copy of that sentence apart from the constant's.
    # Strip the interpolated constant's span first so this leg is pinned
    # to the TEMPLATE's own sentence, not smuggled in by the checklist —
    # then collapse whitespace, because the template's own sentence wraps
    # its line mid-phrase ("only the FIRST\nproblem"), the same class of
    # defect as the "only\nthe files listed" wrap fixed earlier this
    # build; this leg checks for the SENTENCE, not a literal newline-free
    # span, so a wrapped-but-present sentence still counts as present and
    # a genuinely DELETED sentence still reddens.
    prompt2_sans_checklist = " ".join(
        prompt2.replace(worker.TRACE_CONDITIONALS, "").split()
    )
    assert "only the FIRST problem" in prompt2_sans_checklist
    assert "do not change" in prompt2
    assert "only the files listed" in prompt2


def test_b13_repair_prompt_excludes_rejudgment_materials(env, claude_cli_shim_worker, monkeypatch):
    """B13 — the repair prompt EXCLUDES the re-judgment materials: none of
    the doctrine/roster/cluster-candidates/rejected-digest/card-registry/
    canon-excerpt markers appear on the captured round-2 stdin (each
    marker is a literal from the NAMED material's own emitter, not a
    neighbouring template line — delta gate NOTE 7). Also: the composed
    repair prompt is < 64 KiB on a full BATCH_CAP-sized all-invalid
    fixture."""
    rid = seed_pending(env)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid))
    )
    worker.run(env.home)
    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    forbidden = {
        "the routing doctrine": "## 2. The gate procedure",
        "the T3 skill roster": "=== SKILL ROSTER (T3) ===",
        "the per-record path roster": "--- path roster ---",
        "cluster candidates": "--- cluster candidates (T-N) ---",
        "the rejected-proposal digest": "Never re-propose the classes below",
        "the card-section registry": "=== CARD SECTION REGISTRY ===",
        "the canon excerpt": "--- candidate target canon excerpt ---",
    }
    for material, marker in forbidden.items():
        assert marker not in prompt2, f"{material} leaked into the repair prompt via {marker!r}"

    # Size alarm on a full BATCH_CAP-sized all-invalid fixture.
    rids = [
        seed_pending(env, f"lrn-000000{i:02x}", created_at=f"2026-08-{1 + i:02d}T00:00:00Z")
        for i in range(worker.batch_cap())
    ]
    round1 = "\n".join(
        _defect_script(env, r, _t4_missing_target(env, r)) for r in rids
    )
    _next_run_scripts(claude_cli_shim_worker, monkeypatch, round1)
    worker.run(env.home)
    prompt2_full = claude_cli_shim_worker["call_prompt"](claude_cli_shim_worker["count"]())
    assert len(prompt2_full.encode("utf-8")) < 64 * 1024


# ===================================================================== #
# G. Fabrication containment
# ===================================================================== #


def test_g1_setj_pin_refuses_flipped_answer(env, claude_cli_shim_worker, monkeypatch):
    """G1 — the Set-J pin refuses a flipped answer. Call #1 writes
    `t4.depth_behind_rule: {answer: yes, evidence: <verbatim>}` (no
    target); call #2 writes the same file with `answer: no` and no
    target — a document that PASSES `_validate_gates`. The file is
    deleted, with `repair changed a settled judgment` naming
    `gates.t4.depth_behind_rule.answer`, and its record is still
    pending. This is the highest-stakes criterion in the unit: without
    the pin this file LANDS and the ledger records a judgment the
    analyst never made."""
    rid = seed_pending(env)
    bad = _t4_missing_target(env, rid)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, bad))
    flipped = copy.deepcopy(bad)
    flipped["gates"]["t4"]["depth_behind_rule"] = {"answer": "no", "evidence": None, "target": None}
    # sanity: the flipped shape alone passes _validate_gates (the model
    # "escaped" the requirement rather than satisfying it).
    _validate_gates(flipped, record_text=_record_for(env, rid).to_text())
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, flipped))
    result = worker.run(env.home)

    assert not (env.proposals / f"{rid}.yaml").exists()
    assert f"{rid}.yaml" in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    line = next(ln for ln in log_text.splitlines() if f"invalid worker output {rid}.yaml deleted" in ln)
    assert "repair changed a settled judgment" in line
    assert "gates.t4.depth_behind_rule.answer" in line
    assert (env.bucket / "pending" / f"{rid}.md").exists()


def test_g2_setj_pins_positive_control(env, claude_cli_shim_worker, monkeypatch):
    """G2 — the pin's positive control: the same fixture where call #2
    ADDS the target and changes nothing else -> the file lands. Without
    G2, G1 would pass on a build that refuses every repaired file."""
    rid = seed_pending(env)
    bad = _t4_missing_target(env, rid)
    fixed = _t4_target_fixed(env, rid)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, bad))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, fixed))
    result = worker.run(env.home)
    assert result.proposed == [rid]
    assert "record_sha: sha256:" in (env.proposals / f"{rid}.yaml").read_text(encoding="utf-8")


def test_g3_supplied_field_is_not_a_changed_field(env, claude_cli_shim_worker, monkeypatch):
    """G3 — a supplied field is not a changed field. Call #1 writes
    `fs: {verdict: null}` (a C9 defect, on the doctrine's own
    depth_behind_rule=no/conduct_mode=no fallback shape — the ONLY shape
    where `fs.verdict` alone decides the outcome, per Table-1's L6); call
    #2 writes `fs: {verdict: COSTLY, evidence: <verbatim record span>}`,
    moving `gates.outcome` from the null-fs fallback (DEMAND) to ALWAYS
    (COSTLY is a PROMOTING verdict) with `destination` following
    Render-1. The file LANDS — a pin that treats `null -> COSTLY` as a
    judgment change, or that pins `gates.outcome`, refuses the very
    repair Set-P's P2 authorises."""
    rid = seed_pending(env)
    record = _record_for(env, rid)
    demand = _valid_trace(env, destination="reference")
    demand["gates"]["t4"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None, "target": None},
        "conduct_mode": {"answer": "no", "evidence": None},
        "fs": {"verdict": None},
    }
    demand["gates"]["outcome"] = "DEMAND"
    # sanity: null fs.verdict is exactly a C9 defect (ELIGIBLE) — the
    # trace as a WHOLE is invalid because of it, not despite it.
    with pytest.raises(ProposalError, match="gates.t4.fs.verdict"):
        _validate_gates(demand, record_text=record.to_text())

    fixed = copy.deepcopy(demand)
    fixed["gates"]["t4"]["fs"] = {"verdict": "COSTLY", "evidence": RECORD_QUOTE}
    fixed["gates"]["outcome"] = "ALWAYS"
    fixed["destination"] = "claude-md"
    fixed["alternates"] = ["reference"]
    # sanity: this repaired shape validates + derives cleanly at scope.
    validate_proposal(fixed, record_text=record.to_text(), scope="skill:s")

    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, demand))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, fixed))
    result = worker.run(env.home)
    assert result.proposed == [rid]


def test_g4_containment_still_runs_on_repaired_output(env, claude_cli_shim_worker, monkeypatch):
    """G4 — containment still runs on repaired output. Call #2 replaces a
    RECORD-sourced `evidence` with a plausible paraphrase. Deletion, with
    the containment refusal in the line."""
    rid = seed_pending(env)
    bad = _t4_missing_target(env, rid)
    paraphrased = copy.deepcopy(bad)
    paraphrased["gates"]["t4"]["depth_behind_rule"]["target"] = "the candidate target"
    paraphrased["gates"]["t1"]["field_shaped"]["evidence"] = (
        "a paraphrase that is not verbatim but long enough to pass length"
    )
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, bad))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, paraphrased))
    result = worker.run(env.home)
    assert f"{rid}.yaml" in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    line = next(ln for ln in log_text.splitlines() if f"invalid worker output {rid}.yaml deleted" in ln)
    assert "not contained in the record" in line


def test_g5_derivation_still_runs_on_repaired_output(env, claude_cli_shim_worker, monkeypatch):
    """G5 — the derivation still runs on repaired output. Call #2 writes a
    `gates.outcome` that does not follow from its own answers. Deletion
    with the `Table-1 derives` refusal."""
    rid = seed_pending(env)
    bad = _t4_missing_target(env, rid)
    wrong_outcome = copy.deepcopy(bad)
    wrong_outcome["gates"]["t4"]["depth_behind_rule"]["target"] = "the candidate target"
    wrong_outcome["gates"]["outcome"] = "SKILL"  # ALWAYS is what the answers derive
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, bad))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, wrong_outcome))
    result = worker.run(env.home)
    assert f"{rid}.yaml" in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    line = next(ln for ln in log_text.splitlines() if f"invalid worker output {rid}.yaml deleted" in ln)
    assert "Table-1 derives" in line


def test_g6_repair_may_not_rewrite_an_already_valid_proposal(env, claude_cli_shim_worker, monkeypatch):
    """G6 — the repair may not rewrite a proposal that already validated.
    Call #2 modifies a file that was VALID in the dry pass. Deleted with
    `repair rewrote a proposal that had already validated`, and its
    record is still pending. Without the V-set rule a repair round could
    silently re-author a passing analysis."""
    r_valid = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_bad = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    round1 = "\n".join([
        shim_writes(env, r_valid),
        _defect_script(env, r_bad, _t4_missing_target(env, r_bad)),
    ])
    # round 2 rewrites the ALREADY-VALID file at r_valid — not one of the
    # eligible files it was told about, but nothing stops the model's Edit
    # calls from touching a sibling proposal in the same narrowed grant
    # tree at the FILE level (the settings scope is what should stop it;
    # this fixture proves the S5 rule catches it even if that grant were
    # ever loosened).
    tampered = _valid_trace(env)
    tampered["rationale"] = "a rewritten rationale from the repair round"
    # U-attrib: `r_valid`'s round-1 output is still sitting in the STAGE
    # at repair time (Install-1 does not run until S8, after the repair
    # round) — the sibling this fixture tampers with is the staged copy,
    # not (yet) a ledger path.
    round2 = _write_script(worker.stage_dir() / f"{r_valid}.yaml", _dump(tampered))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", round2)
    result = worker.run(env.home)

    assert not (env.proposals / f"{r_valid}.yaml").exists()
    assert f"{r_valid}.yaml" in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    line = next(
        ln for ln in log_text.splitlines() if f"invalid worker output {r_valid}.yaml deleted" in ln
    )
    assert "repair rewrote a proposal that had already validated" in line
    assert (env.bucket / "pending" / f"{r_valid}.md").exists()


def test_g7_no_ledger_mutation_between_the_invocations(env, claude_cli_shim_worker, monkeypatch):
    """G7 — no ledger mutation between the invocations. Monkeypatch
    `worker._git_rm_or_unlink` and `worker.stamp_proposal` (the NAME
    `_validate_written` actually calls — `worker.py` imports
    `stamp_proposal` by name from `ledger_ops`, so patching
    `ledger_ops.stamp_proposal` would rebind a name `worker` never reads
    again; patching where the call is MADE is what actually intercepts
    it) to record the invocation index at which they fire. Zero calls
    before the final invocation returns; `test_lock_invariant.py` passes
    unchanged (asserted separately by the suite run, not here)."""
    rid = seed_pending(env)
    calls: list[tuple[str, int]] = []
    orig_unlink = worker._git_rm_or_unlink
    orig_stamp = worker.stamp_proposal

    def spy_unlink(home, path, result=None):
        calls.append(("unlink", claude_cli_shim_worker["count"]()))
        return orig_unlink(home, path, result)

    def spy_stamp(home, record_id):
        calls.append(("stamp", claude_cli_shim_worker["count"]()))
        return orig_stamp(home, record_id)

    monkeypatch.setattr(worker, "_git_rm_or_unlink", spy_unlink)
    monkeypatch.setattr(worker, "stamp_proposal", spy_stamp)

    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid))
    )
    worker.run(env.home)

    final_count = claude_cli_shim_worker["count"]()
    assert final_count == 2
    assert calls, "neither stamp nor unlink fired at all — fixture did not exercise S8"
    for kind, n in calls:
        assert n >= final_count, f"{kind} fired at invocation index {n}, before the final invocation ({final_count})"


def test_g8_sentinel_reasserted_after_the_last_invocation(env, claude_cli_shim_worker, monkeypatch):
    """G8 — the sentinel is re-asserted after the LAST invocation. At
    least one re-assertion occurs after invocation #2 and before the
    first mutation. Do NOT assert exactly one, and do NOT assert none
    occurs between #1 and #2 (r1 gate NOTE 8) — a build that
    re-asserts after BOTH invocations is strictly safer and must pass."""
    from self_learn import sentinel as sentinel_mod

    rid = seed_pending(env)
    reassert_calls: list[int] = []
    orig_hold = sentinel_mod.hold

    def spy_hold():
        reassert_calls.append(claude_cli_shim_worker["count"]())
        return orig_hold()

    monkeypatch.setattr(sentinel_mod, "hold", spy_hold)
    monkeypatch.setattr(worker.sentinel, "hold", spy_hold)

    # force a heartbeat miss after EVERY invocation, by deleting the
    # sentinel file the shim itself would find live (simplest reliable
    # forcing function: heartbeat() returns False on a missing file).
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1",
        _defect_script(env, rid, _t4_missing_target(env, rid))
        + f"\nrm -f {sentinel_mod.sentinel_path()}",
    )
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2",
        _defect_script(env, rid, _t4_target_fixed(env, rid))
        + f"\nrm -f {sentinel_mod.sentinel_path()}",
    )
    worker.run(env.home)

    final_count = claude_cli_shim_worker["count"]()
    assert final_count == 2
    assert any(n >= final_count for n in reassert_calls), reassert_calls


# ===================================================================== #
# D. Attribution (Rule-F)
# ===================================================================== #


def test_d1_foreign_validated_proposal_survives_the_landing(env, claude_cli_shim_worker, monkeypatch):
    """D1 — a foreign, validated proposal survives the landing. Per
    Construction-1, the shim (standing in for a concurrent attended
    session) writes, DURING the model window, a complete, schema-valid,
    correctly-stamped proposal for a batch record, and writes nothing
    else for it. After the run: the file exists, bytes unchanged, not in
    `result.proposed`, not in `result.invalid_deleted`, not in
    `result.touched`, and `result.foreign_left` names it; the Rule-F log
    line fires. This IS the FW-84 incident: without Rule-F the file is
    re-stamped (bytes change) or deleted."""
    rid = seed_pending(env)
    data = _valid_trace(env)
    script, text, path = _foreign_script(env, rid, data)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", script)
    result = worker.run(env.home)

    assert path.exists()
    assert path.read_text(encoding="utf-8") == text
    assert result.proposed == []
    assert result.invalid_deleted == []
    assert path not in result.touched
    assert rid in result.foreign_left
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert (
        f"run: proposal {rid}.yaml carries a matching record_sha — "
        "another producer wrote it; left untouched"
    ) in log_text


def test_d2_rule_f_positive_control(env, claude_cli_shim_worker, monkeypatch):
    """D2 — Rule-F's positive control: the same fixture where the shim
    writes a VALID but UNSTAMPED proposal -> it is validated, stamped
    and landed as today. Without D2, D1 would pass on a build that skips
    every file."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", shim_writes(env, rid))
    result = worker.run(env.home)
    assert result.proposed == [rid]
    assert result.foreign_left == []
    text = (env.proposals / f"{rid}.yaml").read_text(encoding="utf-8")
    assert "record_sha: sha256:" in text

    # Second leg (gate MAJOR 2): a shape-valid but WRONG record_sha —
    # present, but not matching the record — must ALSO land normally as
    # ordinary output, not be mistaken for Rule-F's foreign case. Without
    # this leg, D2 cannot distinguish "fires on any present sha" from
    # "fires on a MATCHING sha" (M23): every other fixture's record_sha
    # is either exactly correct (_foreign_script) or fully absent
    # (_defect_script always pops it) — never present-but-wrong.
    rid2 = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    junk = _valid_trace(env)
    junk["record_sha"] = "sha256:deadbeefdead"  # shape-valid (12 hex), wrong
    _next_run_scripts(
        claude_cli_shim_worker, monkeypatch,
        _write_script(worker.stage_dir() / f"{rid2}.yaml", _dump(junk)),
    )
    result2 = worker.run(env.home)
    assert result2.proposed == [rid2]
    assert result2.foreign_left == []
    text2 = (env.proposals / f"{rid2}.yaml").read_text(encoding="utf-8")
    assert "record_sha: sha256:" in text2
    assert "deadbeefdead" not in text2  # re-stamped with the REAL sha


def test_d3_rule_f_does_not_rescue_a_scan_hit(env, claude_cli_shim_worker, monkeypatch):
    """D3 — Rule-F does not rescue a scan hit: a file carrying a matching
    record_sha AND a secret-scan hit is deleted, with today's line."""
    rid = seed_pending(env)
    data = _valid_trace(env)
    data["rationale"] = "use password = hunter2secret9 for this"
    script, _text, path = _foreign_script(env, rid, data)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", script)
    result = worker.run(env.home)
    assert not path.exists()
    assert f"{rid}.yaml" in result.invalid_deleted
    assert result.foreign_left == []


def test_d4_repair_round_does_not_enlarge_the_blast_radius(env, claude_cli_shim_worker, monkeypatch):
    """D4 — the repair round does not enlarge the blast radius. During
    the repair window the shim writes a FOREIGN STAMPED proposal for a
    record that is IN the batch but NOT in the repair set (an O-set
    member). It is left untouched by Rule-F and NOT refused by any
    out-of-scope rule. A blanket 'anything touched outside the assigned
    set is deleted' rule would make the repair round a new destroyer of
    attended work."""
    r_bad = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_other = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    round1 = _defect_script(env, r_bad, _t4_missing_target(env, r_bad))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)

    other_data = _valid_trace(env)
    round2_o_set, o_text, o_path = _foreign_script(env, r_other, other_data)
    round2 = "\n".join([
        _defect_script(env, r_bad, _t4_target_fixed(env, r_bad)),
        round2_o_set,
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", round2)
    result = worker.run(env.home)

    assert o_path.exists()
    assert o_path.read_text(encoding="utf-8") == o_text
    assert r_other not in result.invalid_deleted and f"{r_other}.yaml" not in result.invalid_deleted
    # O-set: not refused, falls through to ordinary S8 handling — here
    # that means Rule-F applies FRESH and it is foreign (valid + stamped).
    assert r_other in result.foreign_left


def test_d5_the_narrowed_repair_scope_is_real(env, claude_cli_shim_worker, monkeypatch):
    """D5 — the narrowed repair scope is real: the repair settings file
    has exactly one entry per member of E, every entry an absolute
    Edit(/<path>) rule naming a member of E, no entry a glob (this
    unit's exact-path design, live-verified per §3.7 — see the build
    report; the OR-branch for `write_permission_rules` glob fallback
    does not apply here)."""
    ra = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    rb = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    round1 = "\n".join([
        _defect_script(env, ra, _t4_missing_target(env, ra)),
        _defect_script(env, rb, _t4_missing_target(env, rb)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2",
        "\n".join([
            _defect_script(env, ra, _t4_target_fixed(env, ra)),
            _defect_script(env, rb, _t4_target_fixed(env, rb)),
        ]),
    )
    worker.run(env.home)
    settings_path = worker._p("worker.repair.settings.json")
    assert settings_path.exists()
    settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
    rules = settings_data["permissions"]["allow"]
    # U-attrib (GR-d): E's members are now STAGED paths, not ledger ones.
    expected_paths = sorted(
        [str(worker.stage_dir() / f"{ra}.yaml"), str(worker.stage_dir() / f"{rb}.yaml")]
    )
    assert rules == [f"Edit(/{p})" for p in expected_paths]
    for rule in rules:
        assert rule.startswith("Edit(//")
        assert "*" not in rule
    # security hotfix: without an explicit defaultMode, the session
    # inherits the host's global permissions.defaultMode (which may be
    # "bypassPermissions"), voiding every allow-rule above.
    assert settings_data["permissions"]["defaultMode"] == "default"


def test_d6i_f_a_is_enforced(env, claude_cli_shim_worker, monkeypatch):
    """D6(i) — F-a is enforced: the shim writes, as the analyst's own
    output, a proposal that is SCHEMA-INVALID (a Set-C violation) AND
    carries a `record_sha` matching the record (the
    copy-the-line-you-found shape). Assert the file is NOT foreign: it
    is deleted, it appears in `result.invalid_deleted`, it is NOT in
    `result.foreign_left`, and its record is still pending. Under r1's
    sha-match-alone Rule-F it would have won total immunity."""
    rid = seed_pending(env)
    bad = _t4_missing_target(env, rid)
    bad["record_sha"] = _stamp_sha(env, rid)  # F-b holds; F-a does not
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1", _write_script(worker.stage_dir() / f"{rid}.yaml", _dump(bad))
    )
    result = worker.run(env.home)
    assert not (env.proposals / f"{rid}.yaml").exists()
    assert f"{rid}.yaml" in result.invalid_deleted
    assert rid not in result.foreign_left
    assert (env.bucket / "pending" / f"{rid}.md").exists()


def test_d6ii_phi_excluded_from_v(env, claude_cli_shim_worker, monkeypatch):
    """D6(ii) — Phi is excluded from V. Per Construction-1, round-1's shim
    writes a FOREIGN, VALID, STAMPED file (so it classifies Phi at S4 —
    under r1's three-way partition it would have been in V); round-2's
    shim edits it again during the repair window (the attended session
    still working). Not deleted, not in `result.invalid_deleted`, not
    refused with `repair rewrote a proposal that had already validated`.
    Under the bug this models, the V rule deletes it — the FW-84 incident
    reproduced by the machinery added to prevent it."""
    r_bad = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_phi = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    phi_script, _phi_text0, phi_path = _foreign_script(env, r_phi, _valid_trace(env))
    round1 = "\n".join([
        _defect_script(env, r_bad, _t4_missing_target(env, r_bad)),
        phi_script,
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)

    edited = _valid_trace(env)
    edited["rationale"] = "the attended session's own further edit"
    edit_script, edited_text, _ = _foreign_script(env, r_phi, edited, path=phi_path)
    round2 = "\n".join([
        _defect_script(env, r_bad, _t4_target_fixed(env, r_bad)),
        edit_script,
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", round2)
    result = worker.run(env.home)

    assert phi_path.exists()
    assert phi_path.read_text(encoding="utf-8") == edited_text
    assert f"{r_phi}.yaml" not in result.invalid_deleted
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "repair rewrote a proposal that had already validated" not in log_text or not any(
        r_phi in ln and "already validated" in ln for ln in log_text.splitlines()
    )
    assert r_phi in result.foreign_left


def test_d6iii_hook_takes_the_same_phi_branch_at_s5(env, claude_cli_shim_worker, monkeypatch):
    """D6(iii) — a `destination: hook` path takes the same Phi branch at
    S5. The identical fixture with a valid, stamped `destination: hook`
    proposal: it must not fall into V and be deleted on the repair-window
    edit — the hook carve-out governs S8's stamp-or-delete, not S5's
    partition (§3.5)."""
    from support import hook_proposal_fields

    r_bad = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_hook = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    hook_data = _valid_trace(env, destination="hook", alternates=["claude-md"])
    hook_data.update(hook_proposal_fields())
    hook_script, _hook_text0, hook_path = _foreign_script(env, r_hook, hook_data)
    round1 = "\n".join([
        _defect_script(env, r_bad, _t4_missing_target(env, r_bad)),
        hook_script,
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)

    edited_hook = dict(hook_data)
    edited_hook["rationale"] = "the attended session's own further edit"
    edit_script, edited_text, _ = _foreign_script(env, r_hook, edited_hook, path=hook_path)
    round2 = "\n".join([
        _defect_script(env, r_bad, _t4_target_fixed(env, r_bad)),
        edit_script,
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", round2)
    worker.run(env.home)

    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert not any(
        r_hook in ln and "already validated" in ln for ln in log_text.splitlines()
    )
    assert hook_path.exists()


def test_d7_a_foreign_file_counts_as_progress(env, claude_cli_shim_worker, monkeypatch):
    """D7 — a foreign file counts as progress, and does not fake a
    failure. The batch's ONLY outcome is one Phi file, staged per
    Construction-1, with the batch below BATCH_CAP (so `worker.dirty` is
    cleared). `result.status == 'ok'`; `worker.last-run` exists;
    `result.proposed == []`; `result.valid_landed == 0`;
    `result.foreign_left` names the file; `result.touched == []`; the
    failure counter file does not exist; no follow-on spawned."""
    rid = seed_pending(env)
    script, text, path = _foreign_script(env, rid, _valid_trace(env))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", script)
    spawned = []
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: spawned.append(1) or 4242
    )
    result = worker.run(env.home)

    assert result.status == "ok"
    assert (worker.cache_dir() / "worker.last-run").is_file()
    assert result.proposed == []
    assert result.valid_landed == 0
    assert rid in result.foreign_left
    assert result.touched == []
    assert not worker._p("worker.failures").exists()
    assert not worker._p("worker.dirty").exists()
    assert spawned == []
    assert result.followon is False


def test_d8i_e4_batch_membership(env, claude_cli_shim_worker, monkeypatch):
    """D8(i) — E-4: an invalid, `gates.`-refused proposal exists for a
    record NOT in this run's batch (16 pending records over BATCH_CAP=15
    puts the newest one in the leftover set). Its path appears in NO
    repair prompt and it is deleted with today's line.

    2026-08-09 hardening (T2, real-spawn-site audit): the leftover batch
    here ALSO keeps `worker.dirty` set, reaching the follow-on decision
    unmocked before this incident's fix — `_spawn_window` is guarded so a
    real spawn attempt fails the test loudly instead of leaking a
    process."""
    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "must not reach a real spawn — AUTOKICK=0 must gate the "
            "follow-on before this point"
        ),
    )
    for i in range(16):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-000000{i:02x}",
                created_at=f"2026-07-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "sixteen pending")
    leftover_rid = "lrn-0000000f"  # newest, i=15 -> excluded from the batch
    batch_rid = "lrn-00000000"  # oldest, definitely in the batch

    round1 = "\n".join([
        _defect_script(env, batch_rid, _t4_missing_target(env, batch_rid)),
        _defect_script(env, leftover_rid, _t4_missing_target(env, leftover_rid)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2",
        _defect_script(env, batch_rid, _t4_target_fixed(env, batch_rid)),
    )
    result = worker.run(env.home)

    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    # U-attrib (RT5/ST-e): E-4's litter rule is the destination resolver
    # now — the leftover id never resolves to a batch entry, so it never
    # even reaches the repair round's eligibility filter, and the
    # eligible sibling's path in the prompt is the STAGED one.
    assert str(worker.stage_dir() / f"{leftover_rid}.yaml") not in prompt2
    assert str(env.proposals / f"{leftover_rid}.yaml") not in prompt2
    assert str(worker.stage_dir() / f"{batch_rid}.yaml") in prompt2
    assert f"{leftover_rid}.yaml" in result.invalid_deleted
    assert not (env.proposals / f"{leftover_rid}.yaml").exists()
    assert not (worker.stage_dir() / f"{leftover_rid}.yaml").exists()


def test_d8ii_e5_retired_a_matching_sha_is_now_repair_eligible(env, claude_cli_shim_worker, monkeypatch):
    """D8(ii) — RETIRED, and INVERTED (U-attrib §3.5 bucket 3: replaced by
    `RT4`/`IN3` in test_attrib.py). U-repair's E-5 excluded a staged file
    carrying a MATCHING `record_sha` from repair eligibility, reading it
    as "somebody's unstamped draft" (the copy-the-sha-you-found shape).
    Under U-attrib no staged file can EVER be an attended draft — the
    stage is the model's exclusive namespace — so that exclusion is not a
    safety net here, it is a silent narrowing: a model that happens to
    echo a correct `record_sha` into its own INVALID output would lose
    its repair round for no reason (`RT4`). This test pins the INVERTED
    behaviour so the retirement is verified, not a silently-surviving
    no-op: the identical fixture is now repair-ELIGIBLE."""
    r_bad = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_matching_sha = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    matching_sha_invalid = _t4_missing_target(env, r_matching_sha)
    matching_sha_invalid["record_sha"] = _stamp_sha(env, r_matching_sha)
    round1 = "\n".join([
        _defect_script(env, r_bad, _t4_missing_target(env, r_bad)),
        _write_script(worker.stage_dir() / f"{r_matching_sha}.yaml", _dump(matching_sha_invalid)),
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    fixed = _t4_target_fixed(env, r_matching_sha)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2",
        "\n".join([
            _defect_script(env, r_bad, _t4_target_fixed(env, r_bad)),
            _defect_script(env, r_matching_sha, fixed),
        ]),
    )
    result = worker.run(env.home)

    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    assert str(worker.stage_dir() / f"{r_matching_sha}.yaml") in prompt2
    assert r_matching_sha in result.proposed


# D8(iii) — RETIRED and INVERTED (U-attrib §3.5 bucket 3). U-repair's
# pinned residual was "a never-validated ATTENDED proposal for a batch
# record is repair-eligible" — indistinguishable from model output at
# the shared-namespace seam, and a decision U-repair accepted rather than
# fixed. Under Stage-1 the seam is gone: an attended write lives in the
# LEDGER, never the stage, so it structurally cannot reach the repair
# round at all. The OLD positive control here (an ordinary staged defect
# IS repairable) is not a meaningful test of THIS retirement — it is now
# just RT5/ordinary repair-round coverage, already exercised by B3/B4/B8
# and friends. The retirement itself — the INVERTED claim, that a
# never-validated ATTENDED proposal is now NEVER repair-eligible — is
# `RT3` in test_attrib.py, with its own fixture (a concurrent-producer
# write, never a shim_writes/_defect_script one).


def test_d9_a_hook_proposal_is_never_foreign(env, claude_cli_shim_worker, monkeypatch):
    """D9 — a hook proposal is never foreign. A `destination: hook`
    proposal satisfying F-a and F-b is nonetheless STAMPED (its `script`
    equals `_generate_hook_script`'s output for the record — any
    model-written `script:` is overwritten) and counted in
    `result.proposed`, not `foreign_left`."""
    from support import hook_proposal_fields

    rid = seed_pending(env)
    record = _record_for(env, rid)
    hook_data = _valid_trace(env, destination="hook", alternates=["claude-md"])
    hook_data.update(hook_proposal_fields())
    hook_data["record_sha"] = _stamp_sha(env, rid)
    hook_data["script"] = "#!/bin/sh\necho model-authored-script\n"
    staged_path = worker.stage_dir() / f"{rid}.yaml"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _write_script(staged_path, _dump(hook_data)))
    result = worker.run(env.home)

    assert rid in result.proposed
    assert rid not in result.foreign_left
    # the STAGED copy is consumed by the install (Install-1) — read the
    # LANDED ledger copy (RT8(a): IN9's removal of the shipped `Φ` skip
    # means this — a valid staged file — is installed and stamped like
    # any other, hook or not).
    path = env.proposals / f"{rid}.yaml"
    landed = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    from self_learn import ledger_ops as _ledger_ops

    expected_script = _ledger_ops._generate_hook_script(record, landed)
    assert landed["script"] == expected_script
    assert landed["script"] != "#!/bin/sh\necho model-authored-script\n"


# ===================================================================== #
# E. Headroom, backoff and constants
# ===================================================================== #


def test_e1_timeouts_read_not_hardcoded(monkeypatch):
    """E1 — the timeouts are read, not hardcoded. Defaults 1800/600; each
    honours its env var; the value actually reaches `subprocess.run` by
    capturing the `timeout=` kwarg."""
    monkeypatch.delenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", raising=False)
    monkeypatch.delenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", raising=False)
    assert worker.invoke_timeout_secs() == 1800
    assert worker.repair_timeout_secs() == 600
    monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", "42")
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "99")
    assert worker.invoke_timeout_secs() == 42
    assert worker.repair_timeout_secs() == 99

    captured = {}

    def fake_run(argv, **kwargs):
        captured["timeout"] = kwargs.get("timeout")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    import subprocess as subprocess_mod

    monkeypatch.setattr(worker, "subprocess", subprocess_mod)
    monkeypatch.setattr(subprocess_mod, "run", fake_run)
    worker._invoke_claude(["claude"], "prompt", worker.invoke_timeout_secs(), Path("/tmp"), label="")
    assert captured["timeout"] == 42
    worker._invoke_claude(["claude"], "prompt", worker.repair_timeout_secs(), Path("/tmp"), label="repair ")
    assert captured["timeout"] == 99


def test_e2_batch_cap_unchanged():
    """E2 — BATCH_CAP is unchanged: `worker.batch_cap() == 15`."""
    assert worker.batch_cap() == 15


def test_e3_timeout_floor_defensible_against_the_measurement(monkeypatch):
    """E3 — the timeout floor is defensible against the measurement:
    `invoke_timeout_secs() >= 2 * 857` (the two measured figures — 745s
    replay, 857s live — named in the assertion message). An alarm, not a
    control, labelled as one."""
    monkeypatch.delenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", raising=False)
    measured_live = 857
    measured_replay = 745
    assert worker.invoke_timeout_secs() >= 2 * measured_live, (
        f"invoke_timeout_secs() has fallen back toward the coin flip — "
        f"measured maxima were {measured_live}s live / {measured_replay}s replayed"
    )


def test_e4_zero_or_garbage_timeout_falls_back(monkeypatch):
    """E4 — a zero or garbage timeout falls back: 0, -5, and 'banana' each
    yield the default (never clamped to 0 — a zero `subprocess.run(timeout=...)`
    would kill every run)."""
    for raw in ("0", "-5", "banana"):
        monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", raw)
        assert worker.invoke_timeout_secs() == worker.INVOKE_TIMEOUT_SECS, raw


def test_e5_the_backoff_suppresses_at_the_cap(env, claude_cli_shim_worker, monkeypatch):
    """E5 — the backoff suppresses at the cap. Two consecutive failed runs
    (shim writes nothing landable, leftovers > 0 so `worker.dirty` stays
    set). `_spawn_window` was called after run 1 and NOT after run 2, the
    suppression line logged, `result.followon is False`, `worker.dirty`
    still exists.

    AUTOKICK now gates the follow-on's non-suppressed branch too
    (2026-08-09) — opt back in (mirroring `kick` tests' own convention)
    so run 1's attempt reaches the mocked `_spawn_window`, never a real
    process; run 2's cap suppression fires independent of AUTOKICK
    either way."""
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)
    for i in range(16):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-000000{i:02x}",
                created_at=f"2026-07-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "sixteen pending")
    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)  # shim writes nothing
    spawned = []
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: spawned.append(1) or 4242
    )

    result1 = worker.run(env.home)
    assert result1.status == "failed"
    assert spawned == [1]

    spawned.clear()
    result2 = worker.run(env.home)
    assert result2.status == "failed"
    assert spawned == []
    assert result2.followon is False
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: follow-on suppressed after 2 consecutive failed runs" in log_text
    assert worker._p("worker.dirty").exists()


def test_e6_an_ok_run_resets_the_counter(env, claude_cli_shim_worker, monkeypatch):
    """E6 — an ok run resets the counter: fail -> ok -> fail. The THIRD
    run DOES spawn a follow-on (the cap did not accumulate across the
    intervening success). Seeds 17 (not 16) pending records: after the
    middle 'ok' run resolves exactly one, 16 remain — still > BATCH_CAP
    (15), so `worker.dirty` stays set for the third run too. With only
    16 seeded, the ok run's single resolution would drop the queue to
    exactly BATCH_CAP, clearing `worker.dirty` and making the third run's
    non-spawn a `worker.dirty` artifact rather than a counter one.

    AUTOKICK now gates the follow-on's non-suppressed branch too
    (2026-08-09) — opt back in (mirroring `kick` tests' own convention)
    so the third run's spawn attempt reaches the mocked `_spawn_window`,
    never a real process."""
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)
    for i in range(17):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-000000{i:02x}",
                created_at=f"2026-07-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "seventeen pending")
    spawned = []
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: spawned.append(1) or 4242
    )

    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    worker.run(env.home)  # fail
    assert worker._read_failure_count() == 1

    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, "lrn-00000000"))
    worker.run(env.home)  # ok
    assert worker._read_failure_count() == 0

    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    spawned.clear()
    worker.run(env.home)  # fail again, counter was reset -> spawns
    assert spawned == [1]


def test_e7_kick_resets_the_counter_and_is_never_suppressed(env, monkeypatch):
    """E7 — `kick` resets the counter and is never suppressed. With the
    counter AT the cap, `worker.kick(home)` returns 'spawned' and clears
    `worker.failures`.

    `_spawn_window` mocked (2026-08-09 hardening — matches
    `test_kick_spawns_one_window_and_second_is_absorbed`'s convention):
    this test asserts on `kick`'s decision outcome, not on a real spawned
    process, and previously left one real (if short-lived, no-pending-work)
    detached child behind."""
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK")
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: 4242
    )
    worker._write_failure_count(worker.FOLLOWON_FAILURE_CAP)
    assert worker._read_failure_count() == worker.FOLLOWON_FAILURE_CAP
    outcome = worker.kick(env.home)
    assert outcome == "spawned"
    assert not worker._p("worker.failures").exists()


def test_e8_a_corrupt_counter_is_read_as_zero(env, claude_cli_shim_worker, monkeypatch):
    """E8 — a corrupt counter is read as zero. Writing 'not-a-number'
    still lets the run proceed and spawn (an unguarded `int()` would
    wedge the worker on a corrupt cache file).

    AUTOKICK now gates the follow-on's non-suppressed branch too
    (2026-08-09) — opt back in (mirroring `kick` tests' own convention)
    so the spawn attempt reaches the mocked `_spawn_window`, never a
    real process."""
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)
    worker.cache_dir().mkdir(parents=True, exist_ok=True)
    worker._p("worker.failures").write_text("not-a-number", encoding="utf-8")
    assert worker._read_failure_count() == 0

    for i in range(16):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-000000{i:02x}",
                created_at=f"2026-07-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "sixteen pending")
    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    spawned = []
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: spawned.append(1) or 4242
    )
    worker.run(env.home)
    assert spawned == [1]


def test_d2_followon_requires_progress_on_the_eligible_set(env, claude_cli_shim_worker, monkeypatch):
    """D2 (incident 2026-08-09) — an "ok" status alone is not proof of
    progress: it only means a proposal FILE was written, never that a
    record actually left the eligible set. A batch that keeps reporting
    "ok" while landing NOTHING new (Rule-F: `_check_proposal_file` finds
    a proposal whose `record_sha` already matches — "another producer
    wrote it; left untouched" — `foreign_left`, not `valid_landed`) must
    not chain forever, invisible to the failure cap (which only counts
    `status == "failed"` runs).

    POSITIVE-CONTROL HAZARD (a check that passes when the feature is
    absent is worthless): this test observes the SPAWN DECISION itself
    via a mocked `_spawn_window` in BOTH directions on the SAME 18-record
    leftover batch — generation 1 (genuine landing, eligible 18 -> 17)
    attempts a spawn; generation 2 (Rule-F re-write of the ALREADY-fresh
    record, eligible stays 17) does not. If D2 were absent, or if it
    always suppressed regardless of progress, this pairing would fail to
    discriminate the two generations."""
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)
    for i in range(18):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-300000{i:02x}",
                created_at=f"2026-09-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "eighteen pending — 3 beyond BATCH_CAP=15")
    oldest_rid = "lrn-30000000"  # sort-key oldest -> definitely batch member

    spawned = []
    monkeypatch.setattr(
        worker, "_spawn_window", lambda home, *, no_push=False: spawned.append(1) or 4242
    )

    # Generation 1 — CONTROL: a genuine landing shrinks the eligible set
    # (18 -> 17). D2 must NOT suppress; the follow-on reaches the mocked
    # spawn.
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, oldest_rid))
    result1 = worker.run(env.home)
    assert result1.status == "ok"
    assert result1.valid_landed == 1
    assert result1.followon is True
    assert spawned == [1], "control run: the follow-on must reach the mocked spawn"

    # Generation 2 — the fixture under test: the SAME already-landed
    # record's proposal is re-written carrying its CURRENT (unchanged)
    # record_sha — Rule-F fires (`foreign_left`, not `valid_landed`),
    # `result.status` is still "ok", but NOTHING new left the eligible
    # set (still 17: the other 14 in-batch records and the 3 leftovers
    # never received proposals from this narrowly-targeted shim).
    spawned.clear()
    script, _text, _path = _foreign_script(env, oldest_rid, _valid_trace(env))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    result2 = worker.run(env.home)
    assert result2.status == "ok"
    assert result2.valid_landed == 0
    assert result2.foreign_left == [oldest_rid]
    assert result2.followon is False
    assert spawned == [], (
        "no-progress run: the follow-on must NOT reach the mocked spawn "
        "— D2 is the only gate that can catch this ('ok' status alone "
        "would have let it through)"
    )
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert (
        "run: follow-on suppressed — no progress on the eligible set "
        "(17 still eligible after an 'ok' run)"
    ) in log_text


# ===================================================================== #
# F. Hygiene and process (F1 extends test_worker.py::test_run_argv_pins
# in place, per spec — not duplicated here)
# ===================================================================== #


def test_f2_both_invocations_share_one_argv_builder(env, claude_cli_shim_worker, monkeypatch):
    """F2 — both invocations share one argv builder: the two captured
    argvs are equal except at the `--settings` value. A hand-rolled
    second argv for the repair round would drift from `build_argv` the
    first time either changes."""
    rid = seed_pending(env)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid))
    )
    worker.run(env.home)
    argv1 = claude_cli_shim_worker["argv"](1)
    argv2 = claude_cli_shim_worker["argv"](2)
    assert argv1 != argv2  # they DO differ (at --settings)
    diffs = [(a, b) for a, b in zip(argv1, argv2) if a != b]
    settings_idx = argv1.index("--settings")
    assert argv1[settings_idx + 1] != argv2[settings_idx + 1]
    stripped1 = list(argv1)
    stripped2 = list(argv2)
    stripped1[settings_idx + 1] = "SETTINGS"
    stripped2[settings_idx + 1] = "SETTINGS"
    assert stripped1 == stripped2
    assert len(argv1) == len(argv2)


def test_f5_shim_observes_and_drives_two_invocations(env, claude_cli_shim_worker, monkeypatch):
    """F5 — the shim fixture can observe AND drive two invocations: both
    argvs, both prompts, the counter reading 2, a differing per-call
    script effect, and a non-zero second exit code observed by the
    caller. The pre-U-repair shim truncated (`>`), so a two-invocation
    test would silently observe only the second call."""
    rid = seed_pending(env)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid))
    )
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid))
    )
    monkeypatch.setenv("CLAUDE_SHIM_EXIT_2", "7")
    worker.run(env.home)

    assert claude_cli_shim_worker["count"]() == 2
    argv1 = claude_cli_shim_worker["argv"](1)
    argv2 = claude_cli_shim_worker["argv"](2)
    assert argv1 and argv2
    prompt1 = claude_cli_shim_worker["call_prompt"](1)
    prompt2 = claude_cli_shim_worker["call_prompt"](2)
    assert prompt1 and prompt2 and prompt1 != prompt2
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair claude exited 7:" in log_text


def test_f6_no_test_invokes_a_real_claude():
    """F6 — no test invokes a real `claude`, by source read of THIS file:
    every occurrence of a `claude` argv[0] literal is passed to
    `worker._invoke_claude` (never straight to `subprocess.*`), and every
    such call site sits inside a test that monkeypatches `subprocess.run`
    itself BEFORE the call (so no real process is ever spawned); every
    OTHER `worker.run`/`cli.main(["worker","run"])` call in this file
    routes through the `claude_shim` fixture, whose PATH construction
    puts its own shim dir FIRST, ahead of the inherited PATH."""
    this_file = Path(__file__)
    src = this_file.read_text(encoding="utf-8")
    # search for the ARGV LITERAL SHAPE itself (a one-element list
    # containing the bare word claude) via a pattern that does not
    # itself CONTAIN that shape as a contiguous substring — so this
    # detection line can never match its own source.
    pattern = re.compile(r'\[\s*"claude"\s*\]')
    lines = src.splitlines()
    claude_argv_lines = [
        (i, ln) for i, ln in enumerate(lines, start=1) if pattern.search(ln)
    ]
    # the two legitimate sites (E1) call worker._invoke_claude, which
    # itself calls subprocess.run — and THAT is what E1 monkeypatches
    # first, so no real process ever spawns from either site.
    assert claude_argv_lines, "no claude-argv literal found — F6 has nothing to pin"
    for lineno, line in claude_argv_lines:
        assert "worker._invoke_claude(" in line, (
            f"{this_file}:{lineno}: a claude-argv literal NOT routed through "
            f"worker._invoke_claude — possible direct subprocess call: {line!r}"
        )
    assert "subprocess_mod.run" in src or "subprocess.run" in src
    assert 'monkeypatch.setattr(subprocess_mod, "run", fake_run)' in src, (
        "the direct-argv test no longer monkeypatches subprocess.run before calling "
        "worker._invoke_claude with a claude argv literal"
    )

    # every OTHER real invocation in this file goes through the shim: the
    # fixture itself must put its own shim dir FIRST in PATH.
    #
    # 2026-08-09 (T3, incident hardening): the fixture now ALSO strips
    # any REAL self-learn-notify from the rest of the inherited PATH
    # (`_path_without_real_notify_helper`) — belt-and-braces alongside
    # worker.py's own SELF_LEARN_NO_NOTIFY=1 kill switch — but `shims`
    # is still unconditionally the FIRST leading dir that helper builds,
    # so the invariant this assertion pins is unchanged, only its
    # literal source shape is.
    claude_shim_src = inspect.getsource(claude_cli_shim_worker)
    assert (
        'monkeypatch.setenv("PATH", _path_without_real_notify_helper(shims))'
        in claude_shim_src
    ), "the claude_shim fixture no longer prepends its own shim dir to PATH"
    helper_src = inspect.getsource(_path_without_real_notify_helper)
    assert "parts = [str(d) for d in leading_dirs]" in helper_src, (
        "_path_without_real_notify_helper no longer puts its leading_dirs "
        "argument first in the PATH it builds"
    )


# ===================================================================== #
# H. Obs-1 — the observable surface
# ===================================================================== #


def test_h1_the_exit_code_contract(env, claude_cli_shim_worker, monkeypatch, capsys):
    """H1 — the exit-code contract: `cli.main(["worker","run"])` returns 0
    on an ok run, 0 on an idle run, 1 on a failed run (`cli.py:761`)."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    assert cli.main(["worker", "run"]) == 0  # ok

    assert cli.main(["worker", "run"]) == 0  # idle — nothing eligible

    rid2 = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    bad2 = worker.stage_dir() / f"{rid2}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {bad2.parent} && printf 'destination: bogus\\n' > {bad2}",
    )
    assert cli.main(["worker", "run"]) == 1  # failed


def test_h2_the_stdout_summary_is_byte_stable(env, claude_cli_shim_worker, monkeypatch, capsys):
    """H2 — the stdout summary is byte-stable:
    `worker run: {status} — {n} proposal(s), {merge} merge, {eligible}
    eligible, {suspects} recurrence suspect(s)` with values substituted."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    cli.main(["worker", "run"])
    out = capsys.readouterr().out
    assert out.strip() == "worker run: ok — 1 proposal(s), 0 merge, 1 eligible, 0 recurrence suspect(s)"


def test_h3_the_five_existing_log_lines_are_byte_stable(env, claude_cli_shim_worker, monkeypatch):
    """H3 — the FIVE existing log lines are byte-stable, verbatim (format
    string, then values): the ok/FAILED summaries, the invalid-delete
    line, the orphan-swept line, the follow-on-window line."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: ok — 1 proposal(s), 0 merge, 0 invalid deleted" in log_text

    rid2 = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    bad2 = worker.stage_dir() / f"{rid2}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {bad2.parent} && printf 'destination: bogus\\n' > {bad2}",
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert (
        "run: FAILED — 1 eligible, 0 valid proposals (last-run not touched; "
        "staleness alarm is the detector)"
    ) in log_text
    assert f"run: invalid worker output {rid2}.yaml deleted (" in log_text

    orphan_path = env.proposals / "lrn-orphaned0.yaml"
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_text("destination: bogus\n", encoding="utf-8")
    commit_all(env.home, "seed an orphan proposal")
    rid3 = seed_pending(env, "lrn-0000cccc", created_at="2026-07-03T00:00:00Z")
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid3))
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: orphan proposal lrn-orphaned0.yaml swept" in log_text

    # 2026-08-09 hardening (T2, incident): this phase seeds a leftover
    # batch (16 > BATCH_CAP=15) and its shim keeps re-landing the SAME
    # record every generation — the EXACT shape that spawned a real,
    # self-respawning `worker run --coalesce` chain when this test ran
    # unmocked (AUTOKICK=0 ambient from conftest gates the follow-on now
    # — see `worker._autokick_disabled` — but `_spawn_window` is ALSO
    # mocked here, belt-and-braces, matching the sibling
    # `test_batch_cap_leftovers_keep_dirty_and_followon`-style tests: a
    # `pytest.fail` guard proves the gate refuses BEFORE ever reaching a
    # real spawn, not merely that a real spawn would have been harmless).
    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "must not reach a real spawn — AUTOKICK=0 must gate the "
            "follow-on before this point"
        ),
    )
    for i in range(16):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-100000{i:02x}",
                created_at=f"2026-08-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "sixteen more pending")
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, "lrn-10000000"))
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: follow-on window: " in log_text


def test_h4_every_new_line_in_obs1_is_produced_and_pinned(env, claude_cli_shim_worker, monkeypatch):
    """H4 — every NEW line in §3.12 is produced and pinned, including the
    two r1 left entirely unexercised: the repair-round summary line and
    `run: repair claude exited {rc}: {...}`. Also: skipped, disabled,
    timeout, cleared, Rule-F and suppression lines. Every phase below
    calls `worker.run()` on the SAME `env`/`claude_shim` — the shim's
    invocation counter is cumulative across the whole test function, so
    each phase's numbered `CLAUDE_SHIM_SCRIPT_<n>` vars are bound via
    `_next_run_scripts`, never hardcoded from 1.

    2026-08-09 hardening (T2, real-spawn-site audit): the suppression
    phase near the end seeds a leftover batch (16 > BATCH_CAP=15) and
    drives two consecutive failed runs — reaching the follow-on decision
    unmocked before this incident's fix. `_spawn_window` is guarded for
    the WHOLE function so a real spawn attempt from ANY phase (present or
    future) fails the test loudly instead of leaking a process."""
    monkeypatch.setattr(
        worker,
        "_spawn_window",
        lambda home, *, no_push=False: pytest.fail(
            "must not reach a real spawn — AUTOKICK=0 must gate the "
            "follow-on before this point"
        ),
    )
    # repair round — {n} refused, eligible, ineligible; and non-zero exit.
    rid = seed_pending(env)
    base = _next_run_scripts(
        claude_cli_shim_worker, monkeypatch,
        _defect_script(env, rid, _t4_missing_target(env, rid)),
        _defect_script(env, rid, _t4_target_fixed(env, rid)),
        exits={2: 9},
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair round — 1 refused, 1 eligible, 0 not repairable" in log_text
    assert "run: repair claude exited 9:" in log_text
    assert "run: repair round: 1 of 1 refusals cleared" in log_text

    # skipped — nothing eligible.
    rid2 = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid2))
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair round skipped (no eligible refusals)" in log_text

    # disabled.
    rid3 = seed_pending(env, "lrn-0000cccc", created_at="2026-07-03T00:00:00Z")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT", _defect_script(env, rid3, _t4_missing_target(env, rid3))
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair round disabled (SELF_LEARN_REPAIR=0)" in log_text
    monkeypatch.delenv("SELF_LEARN_REPAIR")

    # timed out. rid3's leftover invalid file was deleted above (repairs
    # were disabled), so its record is pending again — seed a NEW record
    # instead of reusing it, to keep this phase's batch single-file.
    rid4 = seed_pending(env, "lrn-0000dddd", created_at="2026-07-04T00:00:00Z")
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "0.2")
    _next_run_scripts(
        claude_cli_shim_worker, monkeypatch,
        _defect_script(env, rid4, _t4_missing_target(env, rid4)),
        sleeps={2: 1},
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: repair claude timed out after" in log_text
    monkeypatch.delenv("SELF_LEARN_REPAIR_TIMEOUT_SECS")

    # Rule-F.
    rid5 = seed_pending(env, "lrn-0000eeee", created_at="2026-07-05T00:00:00Z")
    script, _text, _path = _foreign_script(env, rid5, _valid_trace(env))
    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert (
        f"run: proposal {rid5}.yaml carries a matching record_sha — "
        "another producer wrote it; left untouched"
    ) in log_text

    # suppression (backoff fired) — reset the counter first: phases 3/4
    # above each independently ended "failed" (their invalid files were
    # deleted with nothing else landing), which would otherwise have
    # already reached FOLLOWON_FAILURE_CAP before this phase's own two
    # runs, measuring stale accumulation instead of THIS phase's pair.
    worker._reset_failure_count()
    for i in range(16):
        create_record(
            env.home,
            make_behavior(
                record_id=f"lrn-200000{i:02x}",
                created_at=f"2026-09-{1 + i:02d}T00:00:00Z",
            ),
        )
    commit_all(env.home, "sixteen pending for suppression")
    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    worker.run(env.home)  # fail #1
    worker.run(env.home)  # fail #2 -> suppressed
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
    assert "run: follow-on suppressed after 2 consecutive failed runs" in log_text


def test_h5_the_new_runresult_fields_are_asserted_as_fields(env, claude_cli_shim_worker, monkeypatch):
    """H5 — the new RunResult fields are asserted as fields (not by
    parsing log text): `repair_attempted`, `repair_eligible`,
    `repair_cleared`, `foreign_left` directly on the returned
    `RunResult`."""
    r_repaired = seed_pending(env, "lrn-0000aaaa", created_at="2026-07-01T00:00:00Z")
    r_foreign = seed_pending(env, "lrn-0000bbbb", created_at="2026-07-02T00:00:00Z")
    foreign_script, _text, _path = _foreign_script(env, r_foreign, _valid_trace(env))
    round1 = "\n".join([
        _defect_script(env, r_repaired, _t4_missing_target(env, r_repaired)),
        foreign_script,
    ])
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", round1)
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, r_repaired, _t4_target_fixed(env, r_repaired))
    )
    result = worker.run(env.home)

    assert result.repair_attempted is True
    assert result.repair_eligible == 1
    assert result.repair_cleared == 1
    assert result.foreign_left == [r_foreign]
