"""U-reach Parts B + C: the `route` telemetry kind, and `routing.by`.

Part B (11 §4.3, U-reach §2.2): the resolution plane was previously
unobserved — nothing recorded that a routing happened, where it went, or
who chose it. `route` joins `EVENT_KINDS` as a code-emitted-only kind
(never `telemetry note`-able); `SCHEMA_VERSION` bumps 1 → 2 (11 §4.3: "v1
closed set; extending = version bump"). Both ROUTE-SITES (`route`,
`route_direct`) spool exactly one event each, immediately after their
ledger commit closes — the ledger commit IS the routing (doc 13 §4.1), so
a host-phase failure must not undercount exactly the interesting case.

Part C (U-reach §2.3): `routing.by` stops being a hardcoded "human" and
starts naming the actor that CHOSE THE DESTINATION — "human" when an
explicit `--dest` carried the choice, "analyst" when the proposal (a
bare `route <id>`) did.

Both AST guards (criteria 20, 25) live here too — one file keeps this
unit's footprint off the shared modules while five siblings build (§6).

**FW-64 correction (below, "Part D"):** the line above about "the review
UI's approve-as-proposed argv" was this spec's own premise, and it was
FALSE — driven end to end, the review UI always sends an explicit
`--dest` (the analyst's own scope-corrected proposal), even when the
human never touched it, so `verbs.route`'s dest-is-not-None heuristic
alone read "human" on every UI approval. FW-64 gave `verbs.route` and
`verbs.route_direct` an explicit, caller-supplied `by` override
(`ROUTING_BY_VALUES = {"human", "analyst", "agent"}`) so a caller that
knows better than the heuristic — the review UI's own CLI subprocess
call, via a new `--by` flag — never has to be guessed at. `route_direct`
gained the SAME plumbing already anticipated by this spec's own §6/§7
follow-up note: `teach.py`'s bare-analyst path now threads `by="analyst"`
explicitly. The UI-level tests (approve-as-proposed vs. a human
`o`-cycle override vs. the SDK pane's own `propose_verb` choice) live in
the `self_learn_ui` package's own test suite, not here — this file pins
only the CLI/verb-layer half of the fix.
"""

from __future__ import annotations

import ast
import inspect
import json

import pytest

from self_learn import cli, ledger_ops, report as report_mod, telemetry, verbs
from self_learn.ledger_ops import create_record, write_proposal
from self_learn.records import Record

from support import make_behavior, make_env, proposal_dict

TEACH_ARGS = [
    "teach",
    "--skill",
    "s",
    "--type",
    "behavior",
    "--kind",
    "anti-pattern",
    "--trigger",
    "About to edit .storage while HA is running.",
    "--instruction",
    "Stop the container first.",
]


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def seed_pending(env, record_id="lrn-0000aaaa", **overrides):
    """A pending record + its skill-md-destination proposal sibling —
    everything `route(id)` (no `--dest`) needs."""
    record = make_behavior(record_id=record_id)
    create_record(env.ledger, record)
    write_proposal(env.ledger, record_id, proposal_dict(**overrides))
    return record


def resolved_path(env, record_id, bucket="s"):
    return env.ledger / "skills" / bucket / "resolved" / f"{record_id}.md"


def _spooled_events(kind: str | None = None) -> list[dict]:
    """Every event currently sitting in the (unflushed) spool — the raw
    surface `spool_quiet` writes to, independent of the CLI's own
    end-of-verb flush."""
    events = []
    for path in telemetry.spool_dir().glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    if kind is not None:
        events = [e for e in events if e.get("kind") == kind]
    return events


# ------------------------------------------------------------- Part B: kind


def test_route_is_a_code_emitted_event_kind():
    """Criterion 14: `route` is code-emitted only — it never joins
    NOTE_KINDS (11 §4.3: this is a verb-flow event, never model-emitted
    via `telemetry note`)."""
    assert "route" in telemetry.EVENT_KINDS
    assert "route" not in telemetry.NOTE_KINDS


def test_schema_version_is_3():
    """Criterion 15: extending the closed set is a version bump. v2 -> v3
    (U-readref §5.1): `reference-read` joined `EVENT_KINDS`."""
    assert telemetry.SCHEMA_VERSION == 3


def test_route_emits_via_the_verb_directly(env):
    """Criterion 16: a proposal-driven `route(id)` (no `--dest`) leaves
    EXACTLY one spooled `route` line, carrying record/destination/scope/
    by. Calling the verb directly (not `cli.main`) keeps the assertion on
    the spool itself — never on the verb's exit code (the §2.2 trap:
    `spool_quiet` swallows a refusal, so "the verb returned 0" proves
    nothing about the event)."""
    record = seed_pending(env)

    verbs.route(env.ledger, record.id)

    route_events = _spooled_events("route")
    assert len(route_events) == 1
    ev = route_events[0]
    assert ev["record"] == record.id
    assert ev["destination"] == "skill-md"
    assert ev["scope"] == "skill:s"
    assert ev["by"] == "analyst"  # no --dest: the proposal chose it


def test_route_direct_emits_via_the_verb_directly(env):
    """Criterion 17 (verb-level half): `route_direct()` spools the same
    shape."""
    record = make_behavior(record_id="lrn-0000bbbb")

    verbs.route_direct(env.ledger, record, dest="skill-md")

    route_events = _spooled_events("route")
    assert len(route_events) == 1
    ev = route_events[0]
    assert ev["record"] == record.id
    assert ev["destination"] == "skill-md"
    assert ev["scope"] == "skill:s"
    assert ev["by"] == "human"


def test_route_direct_emits_via_teach_route_dest(env):
    """Criterion 17 (CLI-level half, as pinned): the SAME shape via
    `teach --route --dest`, the one-motion writer's own front door."""
    rc = cli.main(TEACH_ARGS + ["--route", "--dest", "skill-md"])
    assert rc == 0

    events = telemetry.read_events(env.ledger)
    route_events = [e for e in events if e["kind"] == "route"]
    assert len(route_events) == 1
    ev = route_events[0]
    assert ev["destination"] == "skill-md"
    assert ev["scope"] == "skill:s"
    assert ev["by"] == "human"
    assert "record" in ev


def test_route_event_survives_flush(env):
    """Criterion 18: after the verb, `read_events` returns it and
    `report.gather` counts it — the event outlives the spool it was
    written into."""
    record = seed_pending(env)

    rc = cli.main(["route", record.id])
    assert rc == 0

    events = telemetry.read_events(env.ledger)
    assert any(e["kind"] == "route" and e["record"] == record.id for e in events)

    facts = report_mod.gather(env.ledger)
    assert facts["telemetry"]["events_by_kind"].get("route") == 1


def test_host_phase_failure_still_spools_the_route_event(env, monkeypatch):
    """Criterion 19: a host-phase failure must not undercount the
    interesting case — the record is routed on disk (the ledger commit IS
    the routing, doc 13 §4.1) and the event is spooled DESPITE the raise,
    because the spool call sits immediately after the ledger-write block
    closes, not at the end of the function."""
    record = seed_pending(env)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated host-phase failure")

    monkeypatch.setattr(verbs, "_host_phase", boom)

    with pytest.raises(RuntimeError):
        verbs.route(env.ledger, record.id)

    routed = Record.from_path(resolved_path(env, record.id))
    assert routed.status == "routed"

    route_events = _spooled_events("route")
    assert any(e["record"] == record.id for e in route_events)


def test_route_sites_are_derived_and_all_spool():
    """Criterion 20: ROUTE-SITES is derived by AST walk (a function
    containing `set_routing(` or a `resolve_record(..., "routed", ...)`
    call), not hand-listed — and the collector carries its OWN positive
    control: non-empty, and containing at least `_execute_route`/
    `route_direct`. "Every collected function spools" is vacuously true
    against an empty set (F3 / M22 — hoisting the "routed" literal into a
    module constant would silently empty the derived set while this
    guard stayed green)."""
    # M-1 (U-verbs Phase 2 code gate r1): walk BOTH files -- `route`/
    # `route_direct` call `set_routing` directly inside verbs.py, but
    # `reroute` calls `ledger_ops.reroute_record`, whose OWN
    # `set_routing` call the old verbs.py-only walk could never see.
    sites = _route_sites(_verbs_ast())
    sites.update(_route_sites(_ledger_ops_ast()))

    # `reroute_record` in the floor control too: proves the ledger_ops.py
    # walk actually ran and found a real set_routing() site there, not
    # just an empty pass-through (M-1's own failure shape, one file over).
    #
    # M-R (2026-09-04): `route` itself dropped out of this floor control.
    # Its own body no longer calls `set_routing`/`resolve_record` at all
    # — that responsibility moved into the shared `_execute_route` core
    # it now delegates to (route's own adapter body only builds a
    # `TargetSpec` and hands off). `_execute_route` is the correct stand-
    # in: it is independently found by the SAME walk below (it contains
    # the `resolve_record(..., "routed", ...)` / `record.write` calls
    # for both adapters) and spools its own `route` event. `route_direct`
    # keeps its place unchanged — its adapter body still calls
    # `record.set_routing(...)` directly, pre-delegation.
    assert {"_execute_route", "route_direct", "reroute_record"} <= set(sites)

    for name, node in sites.items():
        if name in _CALLEE_SPOOLS_EXEMPT:
            # minor-5 (gate r1): a bare-name exemption proves nothing on
            # its own -- check the call chain it claims, the same way
            # `f1abafb`'s test_hostmode.py `_MERGE_FOR` fix does.
            assert _calls_a_spooling_site(node, sites), (
                f"{name} is in _CALLEE_SPOOLS_EXEMPT (exempt because it "
                "calls a spooling callee), but its own body no longer "
                "calls anything collected as a spooling site -- this "
                "exemption would otherwise hide a genuine regression"
            )
            continue
        assert _spools_route(node) or name in _CALLER_SPOOLS_EXEMPT, (
            f"{name} routes without spooling a `route` event"
        )


def test_reroute_spools_a_route_event(env):
    """M-1 (U-verbs Phase 2 code gate r1): the runtime half of the fix
    above -- `reroute` spools a `route` event for real, not just a
    shape the AST guard is satisfied by. Two `route` events end up in
    the spool for this record: the original `route`, and `reroute`'s
    own, carrying the NEW destination and the caller's `by`."""
    record = seed_pending(env)
    verbs.route(env.ledger, record.id, dest="skill-md")

    verbs.reroute(env.ledger, record.id, dest="claude-md", by="human")

    route_events = _spooled_events("route")
    assert len(route_events) == 2
    reroute_events = [e for e in route_events if e["destination"] == "claude-md"]
    assert len(reroute_events) == 1
    event = reroute_events[0]
    assert event["record"] == record.id
    assert event["by"] == "human"


def test_reroute_host_phase_failure_still_spools_the_route_event(env, monkeypatch):
    """gate r2 m-5: `reroute`'s own eight-line comment claims the SAME
    spool-survives-host-failure placement pin criterion 19 gives
    `route` (`test_host_phase_failure_still_spools_the_route_event`
    above) -- but until this test, nothing proved it for `reroute`;
    `test_reroute_spools_a_route_event` only exercises the happy path.
    Moving `reroute`'s spool call to the end of the function -- exactly
    the defect the comment exists to prevent -- would leave the rest of
    the suite green without this test."""
    record = seed_pending(env)
    verbs.route(env.ledger, record.id, dest="skill-md")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated host-phase failure")

    monkeypatch.setattr(verbs, "_host_phase", boom)

    with pytest.raises(RuntimeError):
        verbs.reroute(env.ledger, record.id, dest="claude-md", by="human")

    # the ledger commit IS the routing (doc 13 §4.1) -- it happened
    # despite the host-phase raise.
    rerouted = Record.from_path(resolved_path(env, record.id))
    assert rerouted.routing["destination"] == "claude-md"

    route_events = _spooled_events("route")
    reroute_events = [e for e in route_events if e["destination"] == "claude-md"]
    assert len(reroute_events) == 1
    assert reroute_events[0]["record"] == record.id


# --------------------------------------------------------- Part C: `by`


def test_route_by_is_analyst_when_dest_omitted(env):
    """Criterion 21: the proposal (analyst-written) chose the
    destination, so `by` reads "analyst"."""
    record = seed_pending(env)

    verbs.route(env.ledger, record.id)

    routed = Record.from_path(resolved_path(env, record.id))
    assert routed.routing["by"] == "analyst"


def test_route_by_is_human_when_dest_given(env):
    """Criterion 22: an explicit `--dest` is always the human's flag."""
    record = seed_pending(env)

    verbs.route(env.ledger, record.id, dest="skill-md")

    routed = Record.from_path(resolved_path(env, record.id))
    assert routed.routing["by"] == "human"


def test_route_direct_by_default_and_explicit(env):
    """Criterion 23: `route_direct` defaults `by="human"` (the `teach
    --route --dest X` shape) and threads an explicit `by="analyst"` (the
    plumbing the bare-analyst `teach --route` follow-up, §6/§7, needs —
    that call site is `teach.py:698`, outside this unit's files)."""
    default_record = make_behavior(record_id="lrn-0000cccc")
    verbs.route_direct(env.ledger, default_record, dest="skill-md")
    assert (
        Record.from_path(resolved_path(env, default_record.id)).routing["by"]
        == "human"
    )

    analyst_record = make_behavior(record_id="lrn-0000dddd")
    verbs.route_direct(env.ledger, analyst_record, dest="skill-md", by="analyst")
    assert (
        Record.from_path(resolved_path(env, analyst_record.id)).routing["by"]
        == "analyst"
    )


def test_route_event_by_matches_record_routing_by_both_directions(env):
    """Criterion 24, one assertion, both directions: the route event's
    `by` equals the record's `routing['by']`, whether the destination came
    from the proposal (analyst) or from an explicit --dest (human)."""
    proposal_record = seed_pending(env, record_id="lrn-0000eeee")
    verbs.route(env.ledger, proposal_record.id)

    dest_record = seed_pending(env, record_id="lrn-0000ffff")
    verbs.route(env.ledger, dest_record.id, dest="skill-md")

    events = {e["record"]: e for e in _spooled_events("route")}
    for record_id in (proposal_record.id, dest_record.id):
        routed = Record.from_path(resolved_path(env, record_id))
        assert events[record_id]["by"] == routed.routing["by"]
    assert events[proposal_record.id]["by"] == "analyst"
    assert events[dest_record.id]["by"] == "human"


# ------------------------------------------ Part D (FW-64): the `by` override


def test_route_by_override_wins_over_the_dest_given_heuristic(env):
    """FW-64's core fix: an explicit `by=` beats the dest-is-not-None
    heuristic entirely — this is what lets the review UI's subprocess
    call say "analyst" for an unmodified approve-as-proposed even though
    its argv always carries an explicit `--dest`. Before the fix,
    `verbs.route` had no `by` parameter at all and this call would have
    been impossible to make truthfully."""
    record = seed_pending(env)

    verbs.route(env.ledger, record.id, dest="skill-md", by="analyst")

    routed = Record.from_path(resolved_path(env, record.id))
    assert routed.routing["by"] == "analyst"
    route_events = _spooled_events("route")
    assert route_events[0]["by"] == "analyst"


def test_route_by_agent_value_persists(env):
    """FW-64: the third chooser (the SDK pane's own `propose_verb` route
    proposals) is a real, spoolable/persistable value — not silently
    coerced into "human" or "analyst" by anything downstream."""
    record = seed_pending(env)

    verbs.route(env.ledger, record.id, dest="skill-md", by="agent")

    routed = Record.from_path(resolved_path(env, record.id))
    assert routed.routing["by"] == "agent"
    route_events = _spooled_events("route")
    assert route_events[0]["by"] == "agent"


def test_route_none_by_keeps_the_unchanged_heuristic(env):
    """Regression guard: `by=None` (the default — every existing terminal
    caller) must reproduce criteria 21/22 byte-for-byte. This is the
    "don't break the CLI's own correct behaviour while fixing the UI's"
    half of FW-64's design."""
    proposal_record = seed_pending(env, record_id="lrn-0000a1a1")
    verbs.route(env.ledger, proposal_record.id)
    assert (
        Record.from_path(resolved_path(env, proposal_record.id)).routing["by"]
        == "analyst"
    )

    dest_record = seed_pending(env, record_id="lrn-0000b2b2")
    verbs.route(env.ledger, dest_record.id, dest="skill-md")
    assert (
        Record.from_path(resolved_path(env, dest_record.id)).routing["by"]
        == "human"
    )


def test_route_invalid_by_refuses(env):
    """FW-64: `ROUTING_BY_VALUES` is a real closed enum, not decoration —
    a programmer mistake at a call site (a typo'd `by=`) must refuse
    loudly rather than silently writing garbage into the ledger."""
    record = seed_pending(env)
    with pytest.raises(verbs.VerbError):
        verbs.route(env.ledger, record.id, dest="skill-md", by="bogus")
    # nothing written — the refusal is pre-flight
    assert resolved_path(env, record.id).exists() is False


def test_route_direct_invalid_by_refuses(env):
    record = make_behavior(record_id="lrn-0000c3c3")
    with pytest.raises(verbs.VerbError):
        verbs.route_direct(env.ledger, record, dest="skill-md", by="bogus")


def test_cli_route_by_flag_threads_through(env):
    """The review UI's own subprocess call, reproduced exactly: `self-learn
    route <id> --dest X --by analyst` — the CLI's `--by` flag (cli.py) must
    reach `verbs.route` and land in the record, not just exist as inert
    argparse decoration."""
    record = seed_pending(env)

    rc = cli.main(["route", record.id, "--dest", "skill-md", "--by", "analyst"])

    assert rc == 0
    routed = Record.from_path(resolved_path(env, record.id))
    assert routed.routing["by"] == "analyst"


def test_cli_route_by_flag_rejects_unknown_value(env):
    """argparse's own `choices=` refusal (test_status.py's own pin:
    argparse-level failures come back as 2, never an escaping
    SystemExit) — proves the CLI surface cannot silently accept a typo'd
    `--by` value that `verbs.route`'s own VerbError guard would also
    catch, but earlier and with a clearer message."""
    record = seed_pending(env)
    rc = cli.main(["route", record.id, "--dest", "skill-md", "--by", "robot"])
    assert rc == 2
    assert not resolved_path(env, record.id).exists()


def test_no_by_string_literal_at_a_call_site():
    """Criterion 25: no `ast.keyword` named `by`, and no `"by"` dict key,
    may carry an `ast.Constant` string value anywhere in verbs.py — the
    guard the mutation table's M17/M19/M20 all trip.

    Two must-stay-green controls against UNMUTATED code, in this same
    test (§ criterion 25's own pin):

    - `superseded_by="canon"` (graduate()'s call to resolve_record) is a
      REAL keyword-arg-with-string-constant in this file today — a
      guard written as `arg.endswith("by")` would flag it (reviewer's
      INV-4, "trains relax the guard"); matching the keyword name
      EXACTLY must leave it green. Asserted against the source, not a
      synthetic snippet, so a future edit that renames the guard's match
      predicate is caught here too.
    - A docstring containing `by="human"` (this file has one — the
      `route_direct` docstring explaining the exemption below) must not
      turn the guard red — AST-not-regex, `commit-drift-evidence-spec.md`
      §7.5's reason.
    """
    source = inspect.getsource(verbs)
    tree = ast.parse(source, filename=verbs.__file__)

    violations = _by_literal_violations(tree)
    assert violations == []

    # must-stay-green control 1: the real superseded_by="canon" call site
    # is present (so the guard had a real chance to false-positive on it).
    assert 'superseded_by="canon"' in source

    # must-stay-green control 2: a docstring mentions by="..." as prose
    # (route_direct's own docstring, added by this unit) and stays green.
    assert 'by="analyst"' in source or 'by="human"' in source

    # The route_direct SIGNATURE DEFAULT is the one exemption (§6: making
    # it required would break teach.py:698, outside this unit's files) —
    # a FunctionDef default is neither an ast.keyword nor a dict literal,
    # so the walk above never sees it; recorded here as a decision, not
    # an accident.
    assert inspect.signature(verbs.route_direct).parameters["by"].default == "human"


def test_by_guard_stays_green_on_a_synthetic_docstring_snippet():
    """The AST-not-regex control, isolated from the real file: a bare
    docstring containing `by="human"` must never trip the guard."""
    snippet = '''
def f():
    """some prose that happens to say by="human" as an example."""
    pass
'''
    tree = ast.parse(snippet)
    assert _by_literal_violations(tree) == []


def test_by_guard_matches_the_keyword_exactly_not_by_suffix():
    """The INV-4 control, isolated: `superseded_by="canon"` must not trip
    a guard that matches the keyword name EXACTLY."""
    snippet = 'f(home, record_id, "superseded", superseded_by="canon", note=note)'
    tree = ast.parse(snippet)
    assert _by_literal_violations(tree) == []


def test_by_guard_catches_a_real_literal():
    """Sanity: the guard DOES fire on the shape M17/M19/M20 introduce —
    proves the two must-stay-green controls above are not just a guard
    that never fires at all."""
    tree = ast.parse('f(home, record_id, "routed", by="human")')
    assert _by_literal_violations(tree) != []

    tree = ast.parse('routing = {"routed_at": now, "destination": d, "by": "human"}')
    assert _by_literal_violations(tree) != []


# ------------------------------------------------------------------- AST


def _verbs_ast() -> ast.Module:
    return ast.parse(inspect.getsource(verbs), filename=verbs.__file__)


def _ledger_ops_ast() -> ast.Module:
    """M-1 (U-verbs Phase 2 code gate r1): `reroute`'s `set_routing`
    call lives in `ledger_ops.reroute_record`, not in `verbs.py` --
    `route`/`route_direct` call `set_routing`/`resolve_record` DIRECTLY
    inside their own bodies, so criterion 20's single-file walk was
    sound for them, but it structurally could not see a `set_routing`
    call one file away. Walking `ledger_ops.py` too is what makes
    ROUTE-SITES complete rather than merely convenient."""
    return ast.parse(inspect.getsource(ledger_ops), filename=ledger_ops.__file__)


def _by_literal_violations(tree: ast.AST) -> list[tuple[str, int | None]]:
    """Every `by=<string constant>` keyword arg at a call site, and every
    `"by": <string constant>` dict-literal entry, in `tree`."""
    violations: list[tuple[str, int | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if (
                    kw.arg == "by"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    violations.append(("call", getattr(kw, "lineno", None)))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "by"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    violations.append(("dict", getattr(key, "lineno", None)))
    return violations


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


#: M-1 (U-verbs Phase 2 code gate r1): `reroute_record` (`ledger_ops.py`)
#: calls `set_routing` directly -- a REAL route site, not a dry-run one,
#: so unlike `_DRY_RUN_EXEMPT` it is NOT hidden from `_route_sites`'
#: discovery (that would just recreate the single-file blind spot this
#: fix exists to close, one exemption at a time). It IS exempted from
#: the "must spool ITSELF" check `test_route_sites_are_derived_and_
#: all_spool` runs, because it has exactly one caller in the whole
#: tree -- `verbs.reroute` (grep-verified: `grep -rn 'reroute_record('
#: cli/src` finds only its own `def` and that one call, inside
#: `reroute`'s own `_ledger_write` lock) -- and `reroute` is what
#: spools the `route` event, immediately after the SAME ledger commit
#: this helper's write closes (verbs.py, same placement pin as
#: route()/route_direct()'s own, criterion 19). The spool call cannot
#: live inside this helper without either duplicating it or moving
#: `_commit_ledger` into `ledger_ops.py`, neither of which this unit's
#: scope calls for.
#:
#: `resolve_record` (also `ledger_ops.py`) is the SAME shape, found the
#: same way -- widening the walk to `ledger_ops.py` surfaces it too, not
#: just `reroute_record`. It is the shared file-op helper EVERY
#: resolution verb calls (route, route_direct, reject, graduate,
#: supersede, confirm_recurrence, ...), and calls `set_routing()`
#: internally ONLY when `new_status == "routed"` -- it has always done
#: this, the guard simply never saw it before this widening. Its real
#: `new_status="routed"` caller is `_execute_route` (M-R, 2026-09-04:
#: previously `route`/`route_direct` each called it directly -- both
#: now delegate through the shared core), ALREADY, independently,
#: caught by this SAME criterion's OTHER detection leg -- a
#: `resolve_record(..., "routed", ...)` call site inside `verbs.py`
#: itself (see `_execute_route`'s own call, `verbs.py:4081`) -- and
#: already required to spool via that leg. Exempting the shared helper
#: here narrows nothing the criterion actually verifies; it only stops
#: re-flagging the one function whose job is to be called for EVERY
#: resolution status, "routed" among five others.
#:
#: `route_direct` is a DIFFERENT exemption SHAPE from the two above, not
#: a third instance of the same one (minor-5, gate r1): `reroute_record`/
#: `resolve_record` are exempt because their CALLER spools -- nothing in
#: their own body reaches a spooling callee, so that direction can only
#: ever be checked from the OUTSIDE (by testing `reroute`/the managed-
#: write verbs directly, which the rest of this suite already does).
#: `route_direct` is exempt because IT calls a callee that spools: its
#: own adapter body still calls `record.set_routing(...)` directly (it
#: stays a real SITE, found below), but the `spool_quiet("route", ...)`
#: call that used to sit in its own body moved into `_execute_route`,
#: which it now delegates to for the rest of the pinned sequence -- same
#: placement pin, same commit, just one call frame further in. `route`
#: itself needs no entry in EITHER set: its body no longer calls
#: `set_routing`/`resolve_record` at all, so it is not a site in the
#: first place (see the floor-control assertion's own comment above).
#: Kept in a SEPARATE set (`_CALLEE_SPOOLS_EXEMPT`) rather than folded
#: into `_CALLER_SPOOLS_EXEMPT` because only THIS shape can be checked
#: from the inside: the exempt function's own body must call a name
#: that is itself a collected site and itself spools (same call-chain-
#: guard shape as `f1abafb`'s test_hostmode.py `_MERGE_FOR` fix) --
#: applying that same check to `reroute_record`/`resolve_record` would
#: be checking the wrong direction and would always fail.
_CALLER_SPOOLS_EXEMPT = {"reroute_record", "resolve_record"}
_CALLEE_SPOOLS_EXEMPT = {"route_direct"}


def _route_sites(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function ANYWHERE in the module containing a `set_routing(` call, or a
    `resolve_record(...)` call whose third POSITIONAL argument is the
    string literal `"routed"` (criterion 20: AST, not regex — a docstring
    naming `set_routing()` must not turn this red; matching the literal,
    not the argument's runtime value, is exactly why `reject` (third arg
    `"rejected"`) and `graduate` (`"superseded"`) never match)."""
    sites: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    # ast.walk, NOT tree.body: a route site inside a class body (or any
    # nested def) is invisible to a module-level-only iteration, so
    # criterion 20 would stay VACUOUSLY green through a third site that
    # spools nothing — and the floor control cannot see it either, since
    # {route, route_direct} still holds. Measured at the code gate: a
    # `class _SneakyRouter` with a set_routing() call and no spool passed
    # the whole suite under `tree.body`. Same defect class as M22, one
    # scope level deeper.
    # U-verbs §4.3: `route_dry_run` calls `set_routing()` too, but on an
    # in-memory, NEVER-PERSISTED `Record` copy built purely to predict
    # canon bytes (DRY1/DRY2) — no ledger write, no host write, and
    # (deliberately, DRY3's "zero side effects" spirit) no telemetry
    # spool either. It is excluded BY NAME, not by weakening the
    # `set_routing`/`resolve_record` match this criterion is built on.
    _DRY_RUN_EXEMPT = {
        "route_dry_run",
        # M-1 fold (U-verbs Phase 2 code gate r1): `followup_add` was
        # exempted here for one gate round -- the gate proved that
        # avoidable (its sibling `followup_done` uses
        # `Record.complete_follow_up` and never touches `set_routing`
        # at all), so `followup_add` was rewritten to match rather
        # than kept as a second, weaker exemption. This set stays at
        # its original one entry.
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in _DRY_RUN_EXEMPT:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = _call_name(inner.func)
            if name == "set_routing":
                sites[node.name] = node
                break
            if name == "resolve_record" and len(inner.args) >= 3:
                third = inner.args[2]
                if isinstance(third, ast.Constant) and third.value == "routed":
                    sites[node.name] = node
                    break
    return sites


def _spools_route(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and _call_name(inner.func) == "spool_quiet":
            if (
                inner.args
                and isinstance(inner.args[0], ast.Constant)
                and inner.args[0].value == "route"
            ):
                return True
    return False


def _calls_a_spooling_site(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    sites: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> bool:
    """minor-5 (gate r1): the call-chain guard `_CALLEE_SPOOLS_EXEMPT`
    needs -- True when `node`'s own body calls (by bare name) some
    OTHER function that is itself a collected `sites` entry and itself
    spools. Without this, an exemption in `_CALLEE_SPOOLS_EXEMPT` is a
    bare name nobody re-checks: severing the exempt function's own call
    into its spooling callee would leave it silently unrouted-to-
    telemetry and this criterion still green."""
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        name = _call_name(inner.func)
        if name and name != node.name and name in sites and _spools_route(sites[name]):
            return True
    return False
