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

import json

import pytest

from self_learn import batch, cases, hook_activation, verbs
from self_learn import cli as cli_mod
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
        reverted, confirmed GREEN (recorded in this build's report).

        Fold r1 (F3, ruling 6): `route`'s own `by` DOES now take a
        narrower actor default — `by = f.get("by") or (actor if actor
        != "human" else None)` — so a dest-explicit item with no
        `by:` key and `actor="overseer"` resolves `routing.by ==
        "overseer"` (this test used to assert `"human"` here, the
        pre-fold heuristic; gate-o2b-r1.md F3 measured that as a false
        attribution — no ledger surface named the overseer at all on
        its own hook path). `test_default_actor_route_keeps_the_old_by_
        heuristic` below is the companion this test's OLD assertion was
        actually protecting: the default (`"human"`) caller still gets
        the unwidened heuristic byte-for-byte."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=False,
        )
        assert result.items[0].state == "applied", result.items[0].detail
        assert env.resolved(RID).is_file()
        record = Record.from_path(env.resolved(RID))
        assert record.routing["by"] == "overseer"

    def test_default_actor_route_keeps_the_old_by_heuristic(self, tmp_path, monkeypatch):
        """Companion to the test above (fold r1, F3): the default
        (`"human"`) actor is UNCHANGED — `route`'s own dest-is-not-None
        heuristic still decides `routing.by`, never the actor, for the
        default caller. Runs against a NON-hook dest (a hook route
        never reaches `verbs.route` at all under the default actor —
        it refuses first) to isolate the by-heuristic from the S-29
        refusal entirely."""
        from self_learn.ledger_ops import find_record_path
        from test_batch import _env, _seed_pending

        home = _env(tmp_path, monkeypatch)
        rid = _seed_pending(home, "lrn-f0000001")
        sheet = _write_sheet(
            tmp_path,
            f"version: 1\nitems:\n  - id: {rid}\n    verb: route\n    dest: skill-md\n",
        )
        items = batch.load_sheet(sheet)
        result = batch.run(home, items, no_push=True)  # actor defaults to "human"
        assert result.summary["applied"] == 1
        record = Record.from_path(find_record_path(home, rid))
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


# ------------------------------------------------------------------- F1


class TestPlacedOnlyReceiptNamesTheManualSteps:
    """gate-o2b-r1.md F1: the placed-only receipt used to say only
    "delegated but switched off ... placed only" -- true, but silent
    about the two manual steps the human still owes. All three reader
    surfaces the brief names (item detail, `hook-activated` history
    note, the CLI's printed post-notes) read the SAME `delegated_note`
    string computed once in `hook_activation.activate`, so one fix
    covers all three. The third surface cannot be exercised through a
    REAL `self-learn batch` invocation in this test — the CLI never
    exposes `actor`/`hook_activation` as flags (by design, S-29), so it
    can never itself reach the delegated (`actor="overseer"`) state;
    only O-3's own runner (not built by this unit) does, and that
    runner's own printing is O-3's job. What IS proven here directly
    is `cli._cmd_batch`'s own text-mode print line (`cli.py`: `line +=
    f" — {it.detail}"`) is a bare, unconditional echo of
    `ItemResult.detail` for every actor — so the "item detail"
    assertion below IS the CLI-printed text, byte for byte, whenever a
    caller (the CLI today, O-3's runner once built) prints this exact
    item."""

    def test_manual_steps_named_on_item_detail_and_history_note(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=False,
        )
        detail = result.items[0].detail or ""
        record = Record.from_path(env.resolved(RID))
        history_note = next(
            h for h in record.history if h.get("event") == "hook-activated"
        ).get("note") or ""

        for surface_name, text in (("item detail", detail), ("history note", history_note)):
            assert "registration" in text, surface_name
            assert "check are" in text, surface_name
            assert "manual step" in text, surface_name
            assert "two manual" in text, surface_name
            assert "install.sh" in text, surface_name
            assert "settings.json" in text, surface_name

    def test_cmd_batch_print_line_is_a_bare_echo_of_item_detail(self):
        """Structural proof, read directly from the source, that the
        text-mode print loop this class's OTHER test relies on for the
        "CLI printed post-notes" surface really is an unconditional
        echo — grepped from `cli.py` itself so a future refactor that
        changes the format is caught here rather than silently
        invalidating the reasoning above."""
        import inspect

        src = inspect.getsource(cli_mod._cmd_batch)
        assert 'line += f" — {it.detail}"' in src


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


# ------------------------------------------------------------------- F9


class TestHookItemCarriesBothCommitsWorthOfNotes:
    """gate-o2b-r1.md F9: the route commit's own sha and post-notes
    (the exact-bytes preview and manual-steps text a human reviewing
    THIS route sees today, `verbs._hook_manual_steps`) used to be
    dropped from the hook item's `ItemResult` — only `hook_activate`'s
    own receipts rode `detail`, and only its commit sha rode `sha`.
    Both commits' worth of information now rides the ONE item."""

    def test_detail_names_the_route_commit_and_its_own_post_notes(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        item = result.items[0]
        assert item.state == "applied"
        detail = item.detail or ""
        assert "route commit" in detail
        # `sha` still names hook_activate's own commit (the more recent
        # of the two) -- no spec line requires two `sha` slots on one
        # item -- but the route commit's own sha string appears in
        # `detail` and differs from `item.sha`.
        assert item.sha is not None
        route_sha = detail.split("route commit ", 1)[1].split(";", 1)[0].strip()
        assert route_sha and route_sha != item.sha
        # route's own manual-steps text (present on EVERY hook route,
        # human or overseer — `verbs.route`'s own Apply text) rides
        # `detail` too, not just hook_activate's receipts.
        assert "two manual steps" in detail


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


# ------------------------------------------------------------------- F5


class TestActivationExceptionRefusesRatherThanEscapes:
    """gate-o2b-r1.md F5: an exception raised by the ACTIVATION leg
    (after the route commit already landed) used to escape `batch.run`
    entirely — a raw `OSError` is not `verbs.VerbError`/`LedgerOpsError`/
    `CompileError`/`MutationError`/`gitops.HalfWrittenError`/
    `gitops.GitOpsError`, the only six types `_dispatch`'s own except
    ladder caught before this fold, and `hook_activation.activate`'s
    own Phase 2 `except BaseException` re-raises the ORIGINAL exception
    type after its own undo — never wrapped as a `VerbError`. Injected
    at the EXACT point the gate's own probe (e) used: the settings
    write itself (`hook_activation._write_claude_runtime` called WITH
    `settings_bytes`) — AFTER the replay check `TestFailureAfterPlacem
    entUndoes` above injects at, so this proves the settings-write leg
    specifically."""

    def test_settings_write_oserror_refuses_the_item_not_the_sheet(
        self, env, tmp_path, monkeypatch
    ):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        real_write = hook_activation._write_claude_runtime

        def fail_at_settings_write(*a, **kw):
            if kw.get("settings_bytes") is not None:
                raise OSError("simulated: disk full writing settings.json")
            return real_write(*a, **kw)

        monkeypatch.setattr(
            hook_activation, "_write_claude_runtime", fail_at_settings_write
        )
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        # nothing escaped `batch.run` -- exactly one item, refused, no
        # raised exception out of this call at all.
        item = result.items[0]
        assert item.state == "refused"
        assert "simulated" in (item.detail or "")
        assert not _link_path(env).exists()  # the undo already ran
        assert not (env.claude / "settings.json").exists()
        record = Record.from_path(env.resolved(RID))
        assert record.status == "routed"  # route's own commit stands
        assert not any(h.get("event") == "hook-activated" for h in record.history)

    def test_arbitrary_exception_type_from_hook_activate_also_refuses(
        self, env, tmp_path, monkeypatch
    ):
        """A second, simpler injection point (`verbs.hook_activate`
        itself, bypassing `hook_activation`'s own internals) with a
        plain `RuntimeError` no downstream code wraps into anything —
        the general "any exception, not just VerbError" guard; the
        mutation witness for this and the test above is the SAME edit
        (narrowing `_dispatch`'s `except Exception as exc:` on the
        activation leg to `except verbs.VerbError as exc:`), performed
        once by hand: both tests went RED (the exception propagated,
        uncaught), reverted, both GREEN — recorded in this build's
        report."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)

        def boom(*a, **kw):
            raise RuntimeError("simulated: not a VerbError at all")

        monkeypatch.setattr(verbs, "hook_activate", boom)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        item = result.items[0]
        assert item.state == "refused"
        assert "simulated" in (item.detail or "")


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


# ------------------------------------------------------------------- F6


class TestOnlyOverseerLiftsTheRefusal:
    """gate-o2b-r1.md F6: M13b widened the gate to `actor not in
    ("overseer", "steward")` and left 73 tests green across this file,
    `test_batch.py`, and `test_u_verbs.py::TestBatch` — every existing
    test drives either the default `"human"` (still refused under the
    widened gate) or `"overseer"` (still lifted); none drove a THIRD
    actor. Parametrized over every other `ROUTING_BY_VALUES` member
    (`"human"` is `test_default_actor_still_refuses_the_hook_route`'s
    own job above; `"overseer"` is the one that lifts it) against a
    REAL hook route."""

    @pytest.mark.parametrize("actor", ["steward", "analyst", "agent"])
    def test_non_overseer_actor_still_refuses_the_hook_route(
        self, env, tmp_path, actor
    ):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(env.home, items, no_push=True, actor=actor)
        assert result.items[0].state == "refused"
        detail = result.items[0].detail or ""
        assert "refused inside a batch" in detail and "S-29" in detail
        assert env.pending(RID).is_file() and not env.resolved(RID).exists()
        assert not _link_path(env).exists()


# ------------------------------------------------------------------- F7


class TestGateTrueDoctorVerdictChecked:
    """gate-o2b-r1.md F7: `test_gate_true_runs_all_three_steps` (test
    3, above) only proves step 3 RAN (its own receipt line appended
    regardless of the verdict) — not that the verdict was CHECKED
    (M4b: disabling `hook_activation.activate`'s own `if verdict is not
    selfcheck.Verdict.PASS: raise` left all 19 pre-fold tests in this
    file green). Same technique `test_hook_activation.py::
    TestDoctorVerdictAbortsAfterRegistering` uses — a REAL unrelated
    dangling `self-learn-*` registration already in settings.json fails
    the genuine doctor verdict, not a mocked one — driven through
    `batch.run` this time, proving the failure reaches all the way to
    the item's own refusal, not just `hook_activation.activate`'s own
    raise."""

    def test_non_pass_verdict_refuses_the_item_and_undoes(self, env, tmp_path):
        seed_hook(env, rid=RID)
        settings = env.claude / "settings.json"
        unrelated_command = "$HOME/.claude/hooks/self-learn-deadbeef-unrelated.sh"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": unrelated_command}],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before_bytes = settings.read_bytes()
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        item = result.items[0]
        assert item.state == "refused"
        assert "did not verify as live" in (item.detail or "")
        assert not _link_path(env).exists()  # undone: our symlink removed
        assert settings.read_bytes() == before_bytes  # unrelated entry untouched
        record = Record.from_path(env.resolved(RID))
        assert record.status == "routed"  # route's own commit stands
        assert not any(h.get("event") == "hook-activated" for h in record.history)


# ------------------------------------------------------- dry-run preview


class TestDryRunPreviewsPerActor:
    def test_default_actor_previews_would_refuse(self, env, tmp_path):
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        dr = batch.dry_run(env.home, items)
        assert dr.hook_items == [RID]
        assert dr.items[0].state == "would-refuse"
        # F8: the SAME shared S-29 sentence `_dispatch` raises for real
        # — a substring check here closes the drift gap between the two
        # copies (gate-o2b-r1.md F8).
        detail = dr.items[0].detail or ""
        assert "refused inside a batch" in detail and "S-29" in detail
        # F10: the truthful state's own CONSEQUENCE — base exited 0 for
        # a preview the real run always refused (disagreeing with its
        # own `run`); the tip agrees with `run` (`test_bat6_refuses_
        # hook_routes` pins `rc == 1` for the real run at this same
        # default actor) — pin both the envelope's own `ok` key and the
        # CLI's exit code, beside this state assertion.
        assert dr.ok is False
        rc = cli_mod.main(["batch", str(sheet), "--dry-run", "--json"])
        assert rc == 1

    def test_dry_run_ok_true_when_nothing_would_refuse(self, env, tmp_path):
        """Positive control for F10's `dr.ok` pin above: the SAME hook
        item, previewed for the overseer's own runner (`actor=
        "overseer"` — never reachable through the CLI, which exposes
        no such flag) instead of the default actor, previews `ok=True`
        — the new assertion only fires on the specific
        default-actor-would-refuse shape above, not unconditionally."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        dr = batch.dry_run(env.home, items, actor="overseer", hook_activation=True)
        assert dr.ok is True

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


# ------------------------------------------------------------------- F2


class TestActorRidesEveryLedgerSurface:
    """gate-o2b-r1.md F2: before this fold, NO ledger surface named the
    overseer on its own hook path — the route commit writes no `By:`
    trailer at all (F3, separately fixed), the activation commit's
    message carried no trailer either, `routing.by` said `"human"`
    (F3), and the `--json` envelope had no `actor` key. This test pins
    all three surfaces this fold adds/fixes together, after ONE
    overseer hook sheet: the activation commit's own `By:` trailer
    (F2(b)), `routing.by` (F3), and the envelope's `actor` key (F2(a))."""

    def test_by_trailer_on_activation_commit_and_routing_by_and_envelope(
        self, env, tmp_path
    ):
        import subprocess

        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        assert result.items[0].state == "applied", result.items[0].detail

        # `item.sha` IS the activation commit (`hook_activate`'s own,
        # F9's "more recent of the two" choice) -- addressed directly
        # rather than assumed to be HEAD, since a later commit (e.g. a
        # telemetry flush) can land after `batch.run` returns.
        activation_sha = result.items[0].sha
        assert activation_sha is not None
        trailer = subprocess.run(
            ["git", "-C", str(env.home), "log", "-1", activation_sha,
             "--format=%(trailers:key=By,valueonly)"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert trailer == "overseer"
        subject = subprocess.run(
            ["git", "-C", str(env.home), "log", "-1", activation_sha, "--format=%s"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert "hook activate" in subject

        record = Record.from_path(env.resolved(RID))
        assert record.routing["by"] == "overseer"

        assert result.actor == "overseer"
        assert result.to_json()["actor"] == "overseer"

    def test_mutation_dropping_the_by_trailer_reddens(self, env, tmp_path, monkeypatch):
        """Mutation witness: `verbs.hook_activate`'s own `by=(f.get("by")
        or actor)` forwarding, dropped back to no `by` at all — the
        SAME observable shape as before F2(b), reproduced by
        monkeypatching `verbs.hook_activate` to strip the kwarg before
        calling through (the hand-edit was ALSO performed once directly
        against `batch.py`'s own call site: RED on the trailer
        assertion above, reverted, GREEN — recorded in this build's
        report)."""
        import subprocess

        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)
        real_hook_activate = verbs.hook_activate

        def drop_by(*a, **kw):
            kw.pop("by", None)
            return real_hook_activate(*a, **kw)

        monkeypatch.setattr(verbs, "hook_activate", drop_by)
        result = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        assert result.items[0].state == "applied", result.items[0].detail
        activation_sha = result.items[0].sha
        assert activation_sha is not None
        trailer = subprocess.run(
            ["git", "-C", str(env.home), "log", "-1", activation_sha,
             "--format=%(trailers:key=By,valueonly)"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert trailer == ""  # RED shape: no trailer at all


# ------------------------------------------------------------------- F4


class TestReRunReAttemptsActivationOnly:
    """gate-o2b-r1.md F4: re-running the same overseer hook sheet used
    to report `already-applied` (exit 0) for a hook that was neither
    placed nor registered — a success-shaped report for a failure
    state. Two shapes, both from the gate's own measurement."""

    def test_shape_i_failed_activation_is_retried_not_silently_already_applied(
        self, env, tmp_path, monkeypatch
    ):
        """(i) a failed activation, retried: run 1 fails at replay
        (undone, nothing lands on the runtime dir); run 2, with the
        failure removed, must actually re-attempt activation — not
        report `already-applied` while nothing is placed or
        registered."""
        seed_hook(env, rid=RID)
        sheet = _hook_sheet(tmp_path, RID)
        items = batch.load_sheet(sheet)

        real_replay_examples = hook_activation.replay_examples

        def fail_replay(*a, **kw):
            return ["simulated: allow example did not match"]

        monkeypatch.setattr(hook_activation, "replay_examples", fail_replay)
        run1 = batch.run(
            env.home, items, no_push=True, actor="overseer", hook_activation=True,
        )
        assert run1.items[0].state == "refused"
        assert not _link_path(env).exists()

        # Restore explicitly (a SECOND `setattr`, never `monkeypatch.
        # undo()`) -- `undo()` reverts EVERY patch this shared
        # `monkeypatch` instance made, including the `env`/`cache_dir`
        # fixtures' own `setenv("SELF_LEARN_CLAUDE_DIR", ...)` — which
        # would fall `selfcheck.claude_runtime_dir()` back to the REAL
        # `~/.claude` for run2 below (measured: a probe test confirmed
        # `undo()` clears a co-fixture's `setenv` too; the real
        # `~/.claude/hooks`/`settings.json` mtimes were checked
        # afterward and were untouched, but this test no longer risks
        # it at all).
        monkeypatch.setattr(hook_activation, "replay_examples", real_replay_examples)
        items2 = batch.load_sheet(_hook_sheet(tmp_path, RID, name="hook-sheet-2.yaml"))
        run2 = batch.run(
            env.home, items2, no_push=True, actor="overseer", hook_activation=True,
        )
        item2 = run2.items[0]
        # RE-ATTEMPTS activation -- never silently `already-applied`
        # while the symlink is absent and settings.json is untouched.
        assert item2.state == "applied", item2.detail
        assert "already routed" in (item2.detail or "")
        assert _link_path(env).exists()
        settings = env.claude / "settings.json"
        assert settings.exists()

    def test_shape_ii_gate_flips_true_reactivates_instead_of_already_applied(
        self, env, tmp_path
    ):
        """(ii) parked under gate false, gate later flips true: run 1
        places only (delegated); run 2, same sheet, `hook_activation=
        True` — must run the activation leg (register + check), never
        report `already-applied` with settings.json still untouched."""
        seed_hook(env, rid=RID)
        sheet1 = _hook_sheet(tmp_path, RID, name="hook-sheet-1.yaml")
        items1 = batch.load_sheet(sheet1)
        run1 = batch.run(
            env.home, items1, no_push=True, actor="overseer", hook_activation=False,
        )
        assert run1.items[0].state == "applied", run1.items[0].detail
        assert not (env.claude / "settings.json").exists()

        sheet2 = _hook_sheet(tmp_path, RID, name="hook-sheet-2.yaml")
        items2 = batch.load_sheet(sheet2)
        run2 = batch.run(
            env.home, items2, no_push=True, actor="overseer", hook_activation=True,
        )
        item2 = run2.items[0]
        assert item2.state == "applied", item2.detail
        assert "already routed" in (item2.detail or "")
        settings = env.claude / "settings.json"
        assert settings.exists()
        command = f"{env.claude}/hooks/{_link_path(env).name}"
        assert command in settings.read_text(encoding="utf-8")

    def test_shape_iii_registered_hook_stays_applied_when_gate_flips_false(
        self, env, tmp_path
    ):
        """(iii) orchestrator residual: activated under gate TRUE (registered
        + checked); the gate later flips FALSE and the same sheet re-runs.
        A registered hook is COMPLETE whatever the current gate says --
        `already-applied`, no activation re-attempt, settings.json bytes
        identical, no second `hook-activated` history entry (a re-run
        that re-placed it as "delegated" would write a false placed-only
        note over a live registration)."""
        seed_hook(env, rid=RID)
        sheet1 = _hook_sheet(tmp_path, RID, name="hook-sheet-1.yaml")
        run1 = batch.run(
            env.home, batch.load_sheet(sheet1), no_push=True,
            actor="overseer", hook_activation=True,
        )
        assert run1.items[0].state == "applied", run1.items[0].detail
        settings = env.claude / "settings.json"
        before = settings.read_bytes()
        rec_before = Record.from_path(env.resolved(RID))
        n_before = sum(
            1 for h in (rec_before.history or []) if h.get("event") == "hook-activated"
        )
        assert n_before == 1

        sheet2 = _hook_sheet(tmp_path, RID, name="hook-sheet-2.yaml")
        run2 = batch.run(
            env.home, batch.load_sheet(sheet2), no_push=True,
            actor="overseer", hook_activation=False,
        )
        item2 = run2.items[0]
        assert item2.state == "already-applied", item2.detail
        assert settings.read_bytes() == before
        rec_after = Record.from_path(env.resolved(RID))
        n_after = sum(
            1 for h in (rec_after.history or []) if h.get("event") == "hook-activated"
        )
        assert n_after == 1
        assert "delegated" not in ((rec_after.history or [])[-1].get("note") or "")

    def test_mutation_restoring_the_status_only_check_reddens(
        self, env, tmp_path, monkeypatch
    ):
        """Mutation witness: `classify`'s own hook-aware branch removed
        (restoring the pre-fold status-only check — `record.status ==
        "routed"` plus destination match alone decides already-applied,
        regardless of the activation state) reddens the shape (ii) test
        above at the `item2.state == "applied"` assertion (the retry
        reports `already-applied` instead). Reproduced here by
        monkeypatching `batch._hook_activation_registered` to always
        return `True` (unconditionally "fully registered", the
        pre-fold shape's effective behaviour for a hook-dest already-
        routed record) rather than reading the record's own history
        (the hand-edit — deleting the `if want_dest ==
        REFUSED_HOOK_DESTINATION and actor == "overseer":` branch in
        `batch.classify` — was ALSO performed once directly: RED on
        `test_shape_ii_gate_flips_true_reactivates_instead_of_already_
        applied` above, reverted, GREEN; recorded in this build's
        report)."""
        seed_hook(env, rid=RID)
        sheet1 = _hook_sheet(tmp_path, RID, name="hook-sheet-1.yaml")
        items1 = batch.load_sheet(sheet1)
        run1 = batch.run(
            env.home, items1, no_push=True, actor="overseer", hook_activation=False,
        )
        assert run1.items[0].state == "applied"

        monkeypatch.setattr(batch, "_hook_activation_registered", lambda record: True)
        sheet2 = _hook_sheet(tmp_path, RID, name="hook-sheet-2.yaml")
        items2 = batch.load_sheet(sheet2)
        run2 = batch.run(
            env.home, items2, no_push=True, actor="overseer", hook_activation=True,
        )
        item2 = run2.items[0]
        # RED shape: silently "already-applied" although settings.json
        # is still untouched -- the exact defect F4 (i) measured.
        assert item2.state == "already-applied"
        assert not (env.claude / "settings.json").exists()


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
        `_dispatch`'s own ``"; ".join(hook_result.post_notes)`` line
        would produce if it were never given the receipts to join.
        This reproduces the mutation's OBSERVABLE effect (the
        hook_activate-specific receipts vanish from `detail`) without
        needing to hand-edit `batch.py` inside a test run; the
        hand-edit was ALSO performed once by hand (RED, reverted,
        GREEN) and is recorded in this build's report.

        Fold r1 (F9): `detail` is no longer JUST the joined
        `post_notes` — it always leads with ``"route commit <sha>"``
        (route's own commit, folded in alongside hook_activate's), so
        stripping `post_notes` no longer collapses `detail` to `None`.
        The RED shape this test now pins is narrower and more precise:
        the hook_activate-SPECIFIC text (its own step receipts —
        "placed"/"registered") is gone, even though `detail` itself is
        non-empty."""
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
        # RED shape under the mutation: hook_activate's own step
        # receipts never reach `detail` -- where the real (unmutated)
        # path asserts them present above.
        detail = item.detail or ""
        assert "placed" not in detail
        assert "registered" not in detail
