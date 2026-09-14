"""O-2b — `batch.run(actor=, hook_activation=)`: the overseer's owned
hook-activation path through the ONE batch executor everyone uses
(`13-hosting-and-separation.md` §7.4 "The gate"/"The path";
`03-decisions.md` S-54 as amended, S-29 as amended;
`plan-overseer-2026-09-12.md` §O-2, test 8).

**Safety**: every test here resolves the Claude runtime directory through
`SELF_LEARN_CLAUDE_DIR` pointed at a `tmp_path` (the `env` fixture below,
the same pattern `test_hook_activation.py`'s own `env` fixture uses). The
module-scoped `_real_claude_dir_never_touched` fixture is IMPORTED from
`test_hook_activation` rather than re-implemented — it is the recursive
real-`~/.claude` snapshot control that module already carries (settings
.json, every settings.json.self-learn-bak.*, and everything under
hooks/, each as (relative path, size, mtime_ns), compared before/after
every test in this file — same positive control, same file, no drift
between the two build's copies of it).

Module-level tests against `batch.run`/`batch.dry_run`/`batch.
write_receipt` directly -- CLI-level (`--json`, "no flag exposes actor/
hook_activation") tests live in `test_batch_cli.py`. Tests 1-7 below are
`build-o2b.md`'s own numbering; "own mutation" is this build's extra,
named in the report.
"""

from __future__ import annotations

import pytest

from self_learn import batch, cases, hook_activation, verbs
from self_learn.hook_compiler import script_name
from self_learn.records import Record

from test_batch import _seed_case, _write_sheet
from test_hook_activation import _real_claude_dir_never_touched  # noqa: F401
from test_route_hook import TRIGGER
from test_route_hook import Env as RouteEnv
from test_route_hook import seed_hook

RID = "lrn-0000bbbb"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = RouteEnv(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    e.claude = claude
    return e


def _hook_sheet(tmp_path, rid, *, name="hook-sheet.yaml"):
    return _write_sheet(
        tmp_path,
        f"version: 1\nitems:\n  - id: {rid}\n    verb: route\n    dest: hook\n",
        name=name,
    )


def _link_path(env, rid=RID):
    name = script_name(rid, TRIGGER)
    return env.claude / "hooks" / name


# ---------------------------------------------------------------- test 1


class TestActorGatesTheHookRefusal:
    def test_default_actor_still_refuses_the_hook_route(self, env, tmp_path):
        """Unchanged S-29 behaviour (re-tested here in O-2b's own file,
        against a REAL hook proposal, per the brief's "re-test it"):
        `batch.run`'s default `actor="human"` still refuses a hook
        route with the existing message, and nothing lands."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(env.home, items, no_push=True)
        assert result.items[0].state == "refused"
        detail = result.items[0].detail or ""
        assert "refused inside a batch" in detail and "S-29" in detail
        assert env.pending(RID).is_file() and not env.resolved(RID).exists()
        assert not _link_path(env).exists()

    def test_actor_overseer_lifts_the_refusal(self, env, tmp_path):
        """Mutation witness (test 1, part 2): `actor="overseer"` is the
        ONE condition under which a hook route is not refused — proven
        by re-running the SAME sheet with `actor="overseer"` and seeing
        it actually reach `verbs.route`/`verbs.hook_activate` (item
        applied, record resolved) where the default just refused it.
        Mutation: comment out the `actor != "overseer"` branch of the
        `if is_hook_dest and actor != "overseer":` guard in `batch.
        _dispatch` (i.e. make EVERY actor refuse, human included) —
        reddens `result.items[0].state == "applied"` below; verified,
        reverted, confirmed GREEN (recorded in this build's report)."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=False,
        )
        assert result.items[0].state == "applied", result.items[0].detail
        assert env.resolved(RID).is_file()
        # `route`'s own `by` does NOT take the actor-default widening
        # (unlike the eight commit-trailer verbs `test_batch.py`'s
        # `test_by_default_actor_overseer_writes_by_overseer` pins):
        # `verbs.route`'s docstring names `by` as "the actor that chose
        # the destination" and resolves it via its own dest-is-not-None
        # heuristic into `Record.set_routing`'s `routing.by` SCHEMA
        # FIELD -- never a commit trailer -- and `batch._dispatch`
        # still passes the sheet item's own (absent) `by:` through
        # unwidened. With `dest: hook` explicit on the item and no
        # `by:` key, the heuristic reads `by="human"` regardless of
        # `actor="overseer"` -- unchanged from the pre-O-2b behaviour.
        record = Record.from_path(env.resolved(RID))
        assert record.routing["by"] == "human"

    def test_sheet_level_actor_key_refused_regardless_of_the_caller(
        self, env, tmp_path
    ):
        """The sheet-text vector stays closed even when the CALLER's own
        `actor="overseer"` would otherwise lift the hook refusal — a
        hand-written `actor:` top-level key is refused at `load_sheet`
        time, before `run` (and its own `actor=` parameter) are ever
        reached. Re-tests U3's own `_KNOWN_TOP_LEVEL_KEYS` rule
        (already pinned at `test_batch.py`'s
        `TestTopLevelCase::test_unknown_top_level_key_refused_before_
        item_1`) in combination with THIS build's own widening, so the
        two never silently interact."""
        seed_hook(env, rid=RID)
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nactor: overseer\nitems:\n  - id: {RID}\n"
            "    verb: route\n    dest: hook\n",
        )
        with pytest.raises(batch.BatchError, match="unknown top-level key"):
            batch.load_sheet(sheet)


# ---------------------------------------------------------------- test 2


class TestGateFalseParksDelegated:
    def test_gate_false_places_only_and_receipts_delegated(self, env, tmp_path):
        """`hook_activation=False` -> symlink placed, settings.json
        byte-identical (never touched — register=False never reaches
        step 2), the receipt says delegated/switched off, and the
        `hook-activated` history entry carries the SAME truthful note
        (not the pre-O-2b default of "no settings.json change (already
        registered)" — a false statement this build's own report names
        as a defect found and fixed alongside this test)."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=False,
        )
        assert result.items[0].state == "applied", result.items[0].detail
        link = _link_path(env)
        assert link.is_symlink()
        assert not (env.claude / "settings.json").exists()
        detail = result.items[0].detail or ""
        assert "delegated" in detail and "switched off" in detail

        record = Record.from_path(env.resolved(RID))
        assert record.status == "routed"
        entry = next(h for h in record.history if h.get("event") == "hook-activated")
        assert "switched off" in (entry.get("note") or "")
        assert "already registered" not in (entry.get("note") or "")


# ---------------------------------------------------------------- test 3


class TestGateTrueActivates:
    def test_gate_true_runs_all_three_steps(self, env, tmp_path):
        """`hook_activation=True` -> all three steps: placed,
        registered (settings.json actually gains the PreToolUse entry),
        activation-checked (the doctor verdict is consulted — proven by
        letting the real `selfcheck._check_hooks` run, not mocked)."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        assert result.items[0].state == "applied", result.items[0].detail
        link = _link_path(env)
        assert link.is_symlink()
        settings = env.claude / "settings.json"
        assert settings.exists()
        command = f"{env.claude}/hooks/{link.name}"
        assert command in settings.read_text(encoding="utf-8")
        detail = result.items[0].detail or ""
        assert "registered" in detail
        assert "activation-checked" in detail or "doctor-checked" in detail

        record = Record.from_path(env.resolved(RID))
        entry = next(h for h in record.history if h.get("event") == "hook-activated")
        assert "switched off" not in (entry.get("note") or "")


# ---------------------------------------------------------------- test 4


class TestFailureAfterPlacementUndoes:
    def test_replay_failure_undoes_placement_and_refuses_the_item(
        self, env, tmp_path, monkeypatch
    ):
        """A failure AFTER placement (the guard-replay check, reached
        only when `hook_activation=True`) undoes the symlink — O-2a's
        own `_undo` mechanism, reached THROUGH the batch call — and the
        item receipts refused, naming the reason. The route's own
        commit stands (the record is `routed`); no `hook-activated`
        history entry lands, since `_hook_commit_or_undo` is never
        reached."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)

        def fail_replay(*a, **kw):
            return ["simulated: allow example did not match"]

        monkeypatch.setattr(hook_activation, "replay_examples", fail_replay)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        item = result.items[0]
        assert item.state == "refused"
        assert "replay" in (item.detail or "").lower()
        assert not _link_path(env).exists()  # undone

        record = Record.from_path(env.resolved(RID))
        assert record.status == "routed"  # route's own commit stands
        assert not any(h.get("event") == "hook-activated" for h in record.history)


# ---------------------------------------------------------------- test 5


class TestActorValidated:
    def test_bogus_actor_refused_before_item_1(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        with pytest.raises(batch.BatchError, match="actor="):
            batch.run(env.home, items, no_push=True, actor="bogus")
        assert env.pending(RID).is_file()  # nothing ran

    def test_bogus_actor_refused_in_dry_run_too(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        with pytest.raises(batch.BatchError, match="actor="):
            batch.dry_run(env.home, items, actor="bogus")


# ------------------------------------------------------- dry-run preview


class TestDryRunPreviewsPerActor:
    def test_default_actor_previews_would_refuse(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        dr = batch.dry_run(env.home, items)
        assert dr.hook_items == [RID]
        assert dr.items[0].state == "would-refuse"

    def test_overseer_gate_false_previews_placed_only(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        dr = batch.dry_run(env.home, items, actor="overseer", hook_activation=False)
        assert dr.hook_items == [RID]
        assert dr.items[0].state == "would-apply"
        assert "placed only" in (dr.items[0].detail or "")

    def test_overseer_gate_true_previews_activated(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        dr = batch.dry_run(env.home, items, actor="overseer", hook_activation=True)
        assert dr.items[0].state == "would-apply"
        assert "activated" in (dr.items[0].detail or "")

    def test_dry_run_never_touches_the_runtime_directory(self, env, tmp_path):
        """Positive control named by the brief: the claude-dir tree is
        byte-identical (recursive: path, size, mtime_ns) after a dry
        run, for every actor/gate combination — BAT9 extended to the
        overseer's own preview."""
        from test_hook_activation import _snapshot_claude_dir

        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        before = _snapshot_claude_dir(env.claude)
        batch.dry_run(env.home, items, actor="overseer", hook_activation=True)
        batch.dry_run(env.home, items, actor="overseer", hook_activation=False)
        batch.dry_run(env.home, items)
        after = _snapshot_claude_dir(env.claude)
        assert after == before


# ---------------------------------------------------------------- test 7


class TestWriteReceiptParity:
    """Module-level (non-CLI) coverage of `batch.write_receipt` — CLI
    parity (the `--json` envelope / stderr byte-for-byte, applied /
    refused / failing-receipt) is `test_batch_cli.py`'s own extensive
    `TestF2ReceiptFailureNeverRewritesExitCode` et al., unchanged by
    this build (51 passed, `test_batch.py` + `test_batch_cli.py`
    together, before and after — recorded in this build's report)."""

    def test_no_case_returns_none(self, tmp_path, monkeypatch):
        from test_batch import _env, _seed_pending

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000001")
        sheet = _write_sheet(
            tmp_path, f"version: 1\nitems:\n  - id: {rid}\n    verb: reject\n"
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert batch.write_receipt(home, result, "sheet.yaml") is None

    def test_applied_sheet_writes_ok_and_the_application_section(
        self, tmp_path, monkeypatch
    ):
        from test_batch import _env, _seed_pending

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000002")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        # direct, non-CLI call — proves write_receipt has no CLI-only
        # behaviour left in it.
        receipt = batch.write_receipt(home, result, "sheet.yaml", no_push=True)
        assert receipt == {"state": "ok", "pushed": None}
        view = cases.show(home, case_id, evidence_only=False)
        assert f"item=1 {rid} reject" in view.sections["Application"]

    def test_refused_item_still_writes_ok_receipt(self, tmp_path, monkeypatch):
        from test_batch import _env, _seed_pending

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000003")
        verbs.route(home, rid, dest="skill-md", no_push=True)  # reject now refuses
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.items[0].state == "refused"
        receipt = batch.write_receipt(home, result, "sheet.yaml", no_push=True)
        assert receipt == {"state": "ok", "pushed": None}
        view = cases.show(home, case_id, evidence_only=False)
        assert "refused" in view.sections["Application"]

    def test_failing_receipt_returns_failed_state_and_prints_stderr(
        self, tmp_path, monkeypatch, capsys
    ):
        """A genuinely tampered case (frozen-section hash mismatch, the
        SAME `CaseError` `cases.receipt` raises for real — not a
        monkeypatch standing in for it) -- proves `write_receipt`
        catches it and reports `{"state": "failed", ...}` instead of
        raising, printing the SAME stderr line the original inline
        block did."""
        from test_batch import _env, _seed_pending

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000004")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        # Tamper a frozen section AFTER the case was recorded — its
        # `decided_sha256` no longer matches (`cases.py`'s own tamper
        # test does the same thing: replace one word in the frozen
        # body).
        path = next((home / "cases").glob(f"*/{case_id}.md"))
        text = path.read_text(encoding="utf-8")
        tampered = text.replace("u3 test", "TAMPERED")
        assert tampered != text
        path.write_text(tampered, encoding="utf-8")

        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)
        assert result.summary["applied"] == 1  # the sheet itself landed

        receipt = batch.write_receipt(home, result, "sheet.yaml", no_push=True)
        assert receipt is not None and receipt["state"] == "failed"
        assert "freeze-hash" in receipt["reason"]
        err = capsys.readouterr().err
        assert "self-learn batch: case receipt:" in err

    def test_mutation_dropping_the_except_reddens_the_failing_case(
        self, tmp_path, monkeypatch
    ):
        """Mutation witness (test 7): `write_receipt`'s own
        `except (cases.CaseError, gitops.GitOpsError):` clause is what
        turns a receipt failure into `{"state": "failed", ...}` instead
        of an uncaught raise — simulated here by monkeypatching
        `cases.receipt` itself to always raise, matching
        `test_batch_cli.py`'s own established pattern for this exact
        mutation (`TestF2ReceiptFailureNeverRewritesExitCode`), and
        additionally proving the real source removal reddens it
        (recorded in this build's report: the `except` clause was
        commented out in `batch.py`, this test's
        `pytest.raises(cases.CaseError)` block below went RED with an
        uncaught exception instead of a caught one, then reverted and
        confirmed GREEN)."""
        from test_batch import _env, _seed_pending

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-c0000005")
        case_id = _seed_case(home, tmp_path, records=[rid], outcome="reject")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\ncase: {case_id}\nitems:\n  - id: {rid}\n    verb: reject\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)

        def always_fail(*a, **kw):
            raise cases.CaseError("simulated")

        monkeypatch.setattr(cases, "receipt", always_fail)
        receipt = batch.write_receipt(home, result, "sheet.yaml", no_push=True)
        assert receipt == {"state": "failed", "reason": "simulated"}


# --------------------------------------------------------- own mutation


class TestItemResultCarriesActivationReceipts:
    """This build's own extra mutation (brief: "Plus one mutation of
    your own"), against the behaviour named least-protected by every
    OTHER test above — every test 1-4 above checks the item's `state`/
    the RECORD's history, but none pin that `ItemResult.detail` itself
    carries the hook_activate receipts (the brief's own line: "the
    item's result carries the activation receipts")."""

    def test_detail_carries_the_activation_receipts(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        item = result.items[0]
        assert item.state == "applied"
        assert item.detail is not None
        assert "placed" in item.detail
        assert "registered" in item.detail

    def test_mutation_dropping_detail_reddens_the_assertion(
        self, env, tmp_path, monkeypatch
    ):
        """Mutation witness (own), self-verifying: simulates dropping
        the ``detail=`` kwarg from the overseer-path `ItemResult`
        return in `batch._dispatch` by wrapping `verbs.hook_activate`
        so its result's `post_notes` reads empty — the SAME shape
        `_dispatch`'s own ``"; ".join(hook_result.post_notes) or None``
        line would produce if it were never given the receipts to join.
        This reproduces the mutation's OBSERVABLE effect (an empty
        detail) without needing to hand-edit `batch.py` inside a test
        run; the hand-edit was ALSO performed once by hand (RED,
        reverted, GREEN) and is recorded in this build's report."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        real_hook_activate = verbs.hook_activate

        def stripped_notes(*a, **kw):
            result = real_hook_activate(*a, **kw)
            result.post_notes.clear()
            return result

        monkeypatch.setattr(verbs, "hook_activate", stripped_notes)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        item = result.items[0]
        assert item.state == "applied"
        # RED shape under the mutation: no receipts to join -> None,
        # where the real (unmutated) path asserts non-None text above.
        assert item.detail is None
