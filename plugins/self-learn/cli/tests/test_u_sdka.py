"""U-sdka acceptance criteria (docs/specs/self-learn/drafts/
u-sdka-analyst-flip-spec.md §4): SU/FL/AC/HD/AR/DR/HY -- the analyst's
SDK contract, the FW-87 hardening on both backends, and the flip of the
analyst's default backend from `cli` to `sdk`.

`SU1`, `SU2`, `SU3`, `SU5`, `HY4`, `HY5` are INSTRUMENT criteria (a suite
delta, a diff, the shipped DS1 sha-guard, a UI-untouched diff, a pyright
delta, a numstat) satisfied by the build report, not by a function here
-- per spec §5.1. `AC3`/`AC4`/`AC5`/`AC6`/`HD8`/`DR3`/`AR4` have no
mutation row for the reasons §5.1 states; every OTHER criterion is a
named test below, `^test_ac\\d+_` for the `AC` group (`H-c`).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from self_learn import analyst, cli as cli_mod, provider
from self_learn import invocation
from self_learn.invocation import contract as contract_mod
from self_learn.invocation import registry as registry_mod
from self_learn.invocation.contract import DEFAULT_BACKEND_FOR_SURFACE, SURFACES
from self_learn.invocation_sdk import SdkBackend
from self_learn.invocation_sdk import backend as sdk_backend_mod
from self_learn.invocation_sdk import charter as charter_mod
from self_learn.ledger_ops import ROSTER_UNAVAILABLE
from self_learn.normalize import sha_anchor
from self_learn.records import Record

from support import git, make_behavior, make_env

from test_invocation import _clear_backend_env, _clear_config, _write_config
from test_invocation import miner_capture  # noqa: F401 -- fixture resolved by name
from test_invocation_sdk import sdk_absent  # noqa: F401 -- fixture resolved by name
from test_repair import _defect_script, _t4_missing_target, _t4_target_fixed
from test_worker import sdk_fake_worker, env, seed_pending  # noqa: F401 -- fixtures resolved by name (NOT the "claude_shim" legacy alias -- FX4 permits exactly one importer, test_invocation.py)

_REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
)

#: `U-sdka`'s own base commit (spec header) -- an immutable, already-
#: merged ancestor, never a moving ref (`HEAD` would equal the working
#: tree once this unit's own edits are committed, which would make every
#: byte-identity check below trivially, uselessly green).
# Re-anchored 89f8ef7 -> 442385d at the merge train (2026-08-19): the unit
# built against pre-U-docs/U-sdkr/U-sdkw master; every inter-base drift was
# verified as those units' gated landings (U-sdkr's CN2 strict_mcp witness +
# reader shim/scenario, U-sdkw's worker contract file + fake scenarios)
# before moving this ref. 442385d is the master this unit merged onto, so
# every diff-vs-base below is exactly this unit's own sanctioned delta.
_BASE_SHA = "442385d"

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"

#: the GENUINE, never-patched `subprocess.run`, captured at import time --
#: `_Leg.fail("os-error")`'s patch is layered via the shared per-test
#: `monkeypatch`, so a caller that wants a NORMAL route after an
#: `os-error` leg (`H-e`'s negative control) must restore this
#: explicitly, never via `monkeypatch.undo()` (would also revert `leg`'s
#: own env setup -- the BLOCKER-1 shape).
_REAL_SUBPROCESS_RUN = subprocess.run
# U-cleanup-B DELETE (§8.3): `LEGS = ("cli", "sdk")` had zero live
# readers -- U-cleanup-A already collapsed every `params=LEGS`
# parametrization to the sdk leg alone (see the `leg` fixture's own
# docstring); the two remaining mentions were a comment and this same
# docstring, both purely historical.


# ===================================================================== #
# Shared: base-commit source recovery (`SU4`/`AR1`/`AR3`/`HY3`'s one
# mechanism, never re-implemented per criterion)
# ===================================================================== #


def _source_at(base: str, relpath: str) -> str:
    return subprocess.run(
        ["git", "show", f"{base}:{relpath}"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _top_level_funcs(text: str) -> dict[str, ast.AST]:
    tree = ast.parse(text)
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _func_source(text: str, node: ast.AST) -> str:
    return ast.get_source_segment(text, node)


def _assert_dumps(node: ast.AST) -> list[str]:
    return [ast.dump(n) for n in ast.walk(node) if isinstance(n, ast.Assert)]


# ===================================================================== #
# SU -- the suite (only `SU4` gets a function; see module docstring)
# ===================================================================== #

#: `SHADOW_22` minus `test_wr6_...` (§3.3 `A-0`), re-derived at the base
#: commit by §9 `E3`'s command (measured for this build: 18 FAILED + 4
#: ERROR = 22, matching the spec's provenance exactly).
#:
#: U-cleanup-A reconciliation: `test_cn10_...`, `test_av1_...`, and
#: `test_av4_...` are removed from `test_invocation.py`'s tuple below --
#: `cn10`/`av1` were DELETED outright (CV2/CB-3's argv-witness machinery
#: is CLI-only, see the `_run_argv_pins`-class disposition), and `av4`'s
#: body was REWRITTEN (its "analyst prompt rides argv" leg is false
#: under sdk; see `test_invocation.py::test_av4_prompt_membership_on_
#: real_invocations`'s own docstring). `test_teach_route_analyst_routes_
#: to_shim_destination` is removed from `test_route_cli.py`'s tuple for
#: the same reason (`-p`/`--allowedTools` argv checks dropped, replaced
#: with a wire-level prompt check). All four are tracked as EDITED, not
#: armored, from here on -- see `_AR3_REASONS`/`_AR3_RENAMED` for the
#: `test_invocation.py`/`test_invocation_sdk.py` pair (AR3's scan
#: doesn't cover `test_route_cli.py`, so that one drops out of armor
#: coverage with no replacement bookkeeping -- nothing else pins it).
_ARMOR_21_BY_FILE: dict[str, tuple[str, ...]] = {
    "test_invocation.py": (
        "test_cn2_call_site_containment_matches_the_call_site_table",
        # `lg7`/`wr5` REMOVED (code gate r1 MAJOR-1 fold,
        # 8uvjHmdKaUd6PI3tSyB-F): both were left `@pytest.mark.skip`ped
        # with no A4/S10.1 disposition -- migrated onto sdk instead
        # (`_AR3_REASONS` carries their entries now).
    ),
    "test_composer.py": (
        "test_a23_roster_sha_honesty_both_legs_both_paths",
        "test_a24_containment_and_derivation_at_owned_sites",
    ),
    # `test_regime_fixes.py`'s `test_analyst_timeout_captures_to_pending`
    # is REMOVED from this tuple (U-cleanup-A): under `AG3` the analyst
    # resolves `sdk` by default with no `SELF_LEARN_SDK_CLI_PATH`
    # configured, so the test as originally written tripped the
    # PRE-EXISTING `_no_real_sdk_spawn_tripwire` (conftest.py) rather
    # than exercising its own real subject (a wedged session timing out
    # end to end through `teach --route`). Fixed with one added line --
    # pointing `SELF_LEARN_SDK_CLI_PATH` at the test's own existing
    # `sleep 30` PATH shim, so the SDK transport has a concrete,
    # non-`None` `cli_path` and never reaches `_find_cli()` at all. The
    # `asyncio.wait_for(..., timeout=spec.timeout)` wrapper in
    # `invocation_sdk/backend.py::_run_session` is what actually fires
    # (verified: source-read, not inferred) -- backend-agnostic, so this
    # stays a genuine end-to-end regression test, not a CliBackend
    # transport-mechanics test in the AG1-skip sense. `test_route_cli.py`
    # (below) is the precedent for a file AR3's scan doesn't cover
    # dropping out of armor with no replacement bookkeeping.
    # `test_route_cli.py`'s seven-function tuple REMOVED here (code gate r1
    # MAJOR-1 fold): all seven took `claude_cli_shim_analyst` as a
    # parameter (or referenced it in-body); the fold's CV7 rename to
    # `sdk_fake_analyst` touched every one of them, so none is
    # byte-identical to base any longer. Moved to `_EDITED_CURRENT_NAMES`
    # below with the rename as their stated reason -- SU4's disjointness
    # leg is what actually enforces "armor and edited never overlap", and
    # it stays green precisely because they moved together.
}

#: `A-f` -- the eight `EDITED` functions, BY THEIR CURRENT (post-build)
#: names, so `SU4`'s disjointness leg and `AR3`'s own scan share one list.
#: U-cleanup-A adds its own `test_invocation.py`/`test_invocation_sdk.py`
#: casualties (rebased onto sdk, or renamed off a CLI-comparison leg) so
#: the disjointness check stays a true statement about what SU4 no
#: longer treats as armored, not just a stale U-flip snapshot.
_EDITED_CURRENT_NAMES = {
    "test_invocation.py": (
        "test_rg1_five_rung_precedence_resolves_in_isolation",
        # U-cleanup-B: `test_tr4_bare_os_error_is_caught_on_analyst_
        # worker_and_miner` (this name) is DELETED outright, not edited
        # -- it drove `CliBackend()` directly, same as the rest of the
        # TR1-TR7 group (§8.1). No longer belongs in an "edited" list.
        "test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_through_log_templates",
        "test_av4_prompt_membership_on_real_invocations",
        "test_fk2_each_fakestep_matches_sdkbackend_for_the_same_failure",
        "test_lg1_twelve_byte_identical_log_lines",
        "test_lg2_repair_label_appears_only_in_repair_lines",
        "test_lg3a_worker_g_format",
        "test_lg3b_miner_no_g_format",
        "test_lg3c_timeout_display_is_actually_read",
        "test_lg5_detail_rendering_per_surface",
        "test_lg6_clean_invocation_logs_nothing",
    ),
    "test_invocation_sdk.py": (
        "test_ou1_every_row_of_the_map_1_table",
        "test_ou5_bare_oserror_caught_on_worker_miner_and_analyst",
        "test_rs2_present_returns_sdkbackend_for_every_surface",
        "test_ou3_sdk_not_found_wording_and_template_table_authority",
    ),
    "test_doctor_invocation.py": (
        "test_dc2_switches_names_all_surfaces_and_changes_with_rung",
        "test_dc3_rollout_four_states",
    ),
    # code gate r1 MAJOR-1 fold: `claude_cli_shim_analyst` -> `sdk_fake_
    # analyst`, CV7's rename, touched every one of these seven signatures
    # (and several bodies, e.g. `sdk_fake_analyst["out"].write_text(...)`
    # at :351). Pure rename, no behavioural edit -- but SU4's "byte-
    # identical to base" bar does not distinguish a rename from a logic
    # change, so these move out of `_ARMOR_21_BY_FILE` rather than fail
    # that bar dishonestly.
    "test_route_cli.py": (
        "test_teach_route_bare_analyst_path_records_by_analyst",
        "test_teach_route_analyst_failure_captures_to_pending",
        "test_analyst_analyze_round_trips_unknown_fields",
        "test_analyst_analyze_hook_round_trips",
        "test_analyst_analyze_cli_owned_fields_win",
        "test_analyst_analyze_strips_script_unconditionally",
        "test_analyst_analyze_runs_in_ledger_home",
    ),
}


def test_su4_armor_21_is_byte_identical_and_disjoint_from_edited():
    armor_names: set[str] = set()
    for relpath, names in _ARMOR_21_BY_FILE.items():
        full = f"plugins/self-learn/cli/tests/{relpath}"
        base_funcs = _top_level_funcs(_source_at(_BASE_SHA, full))
        now_text = (Path(__file__).parent / relpath).read_text(encoding="utf-8")
        now_funcs = _top_level_funcs(now_text)
        base_text = _source_at(_BASE_SHA, full)
        for name in names:
            armor_names.add(name)
            assert name in base_funcs, (relpath, name, "missing at base")
            assert name in now_funcs, (relpath, name, "missing now -- ARMOR_21 must be UNEDITED")
            base_src = _func_source(base_text, base_funcs[name])
            now_src = _func_source(now_text, now_funcs[name])
            assert now_src == base_src, (relpath, name)

    edited_names = {n for names in _EDITED_CURRENT_NAMES.values() for n in names}
    assert armor_names.isdisjoint(edited_names), armor_names & edited_names


# ===================================================================== #
# FL -- the flip
# ===================================================================== #


def test_fl1_default_rung_resolves_sdk_for_every_surface(tmp_path, monkeypatch, sdk_absent):
    # `FL1` -- the PRODUCT default, env cleared entirely (no conftest pin
    # survives a nested delenv), no config.yaml. U-flip: this criterion
    # used to be "...resolves_sdk_for_analyst_cli_for_the_rest" -- U-flip
    # flipped worker/worker-repair/miner-reader's default to sdk too, so
    # every named surface now takes the BackendUnavailable leg
    # (`sdk_absent` forces the import to fail). U-cleanup: `CliBackend`
    # is deleted and the unknown-surface fallback (`registry.py`'s
    # `.get(surface, "sdk")`) now also names "sdk" -- there is no
    # surface, named or not, left that resolves anything else. The
    # "only an unknown surface still resolves CliBackend" special case
    # this test used to carve out no longer exists; folded into the
    # same loop below (`"nope"` alongside the real surfaces).
    for var in (
        "SELF_LEARN_BACKEND",
        "SELF_LEARN_BACKEND_WORKER",
        "SELF_LEARN_BACKEND_MINER",
        "SELF_LEARN_BACKEND_ANALYST",
    ):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "fl1-home"
    home.mkdir()

    assert set(DEFAULT_BACKEND_FOR_SURFACE) == set(SURFACES)

    for surface in (*SURFACES, "nope"):
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)


def test_fl1b_default_rung_returns_a_real_sdkbackend_when_installed(tmp_path, monkeypatch):
    # Companion to `test_fl1...` above -- WITHOUT `sdk_absent`, the same
    # cleared-env resolution returns an actual `SdkBackend`, asserted by
    # identity (not `isinstance` against a name, `FL1`).
    for var in (
        "SELF_LEARN_BACKEND",
        "SELF_LEARN_BACKEND_WORKER",
        "SELF_LEARN_BACKEND_MINER",
        "SELF_LEARN_BACKEND_ANALYST",
    ):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "fl1b-home"
    home.mkdir()
    backend = invocation.backend_for("analyst", home=home)
    assert type(backend) is SdkBackend


def _assert_cli_refused(surface, home):
    """U-cleanup §5: a `cli` pin at any rung no longer resolves a
    `CliBackend` (deleted) -- it REFUSES, raising `BackendUnavailable`
    with the retirement message byte-for-byte. `FL2`'s property (this
    rung's value shadows the table's default) still holds: refusing is
    observably DIFFERENT from every surface's own (now sdk) default,
    which is what proves the shadowing happened."""
    with pytest.raises(invocation.BackendUnavailable) as exc_info:
        invocation.backend_for(surface, home=home)
    assert str(exc_info.value) == registry_mod._CLI_RETIRED_MESSAGE


def test_fl2_each_rung_shadows_the_table_both_directions(tmp_path, monkeypatch, sdk_absent):
    home = tmp_path / "fl2-home"
    home.mkdir()

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    _assert_cli_refused("analyst", home)

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
    _assert_cli_refused("analyst", home)

    _clear_backend_env(monkeypatch)
    _write_config(home, {"backend_analyst": "cli"})
    _assert_cli_refused("analyst", home)
    _clear_config(home)

    _write_config(home, {"backend": "cli"})
    _assert_cli_refused("analyst", home)
    _clear_config(home)

    # the inverse, for worker/worker-repair/miner-reader: since U-flip,
    # these three ALSO default to sdk (the table is not a ceiling in
    # either direction now -- every surface can be pinned to "cli", and
    # every such pin refuses, U-cleanup §5).
    for surface in ("worker", "worker-repair", "miner-reader"):
        selector = invocation.SELECTOR_FOR_SURFACE[surface]

        _clear_backend_env(monkeypatch)
        monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "cli")
        _assert_cli_refused(surface, home)

        _clear_backend_env(monkeypatch)
        monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
        _assert_cli_refused(surface, home)

        _clear_backend_env(monkeypatch)
        _write_config(home, {f"backend_{surface}": "cli"})
        _assert_cli_refused(surface, home)
        _clear_config(home)

        _write_config(home, {"backend": "cli"})
        _assert_cli_refused(surface, home)
        _clear_config(home)


def test_fl3_fail_closed_survives_the_table(tmp_path, monkeypatch, capsys):
    home = tmp_path / "fl3-home"
    home.mkdir()

    # (i) an unknown value at each configurable rung, on the ANALYST --
    # U-cleanup: the fallback is now "sdk" (was "cli"; SEL5's
    # discriminator -- an unknown value is NOT the retired "cli" name,
    # it folds to sdk silently, same as before the retirement just with
    # a different fold target).
    _clear_backend_env(monkeypatch)
    _clear_config(home)
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "bogus")
    assert isinstance(invocation.backend_for("analyst", home=home), SdkBackend)
    assert capsys.readouterr().err == (
        "self-learn: unknown invocation backend 'bogus' in SELF_LEARN_BACKEND_ANALYST"
        ' — using "sdk"\n'
    )

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "bogus")
    assert isinstance(invocation.backend_for("analyst", home=home), SdkBackend)
    assert capsys.readouterr().err == (
        "self-learn: unknown invocation backend 'bogus' in SELF_LEARN_BACKEND" ' — using "sdk"\n'
    )

    _clear_backend_env(monkeypatch)
    _write_config(home, {"backend_analyst": "bogus"})
    assert isinstance(invocation.backend_for("analyst", home=home), SdkBackend)
    assert capsys.readouterr().err == (
        "self-learn: config.yaml ignored — invocation.backend_analyst must be "
        "one of sdk; got 'bogus' — using \"sdk\"\n"
    )
    _clear_config(home)

    _write_config(home, {"backend": "bogus"})
    assert isinstance(invocation.backend_for("analyst", home=home), SdkBackend)
    assert capsys.readouterr().err == (
        "self-learn: config.yaml ignored — invocation.backend must be "
        "one of sdk; got 'bogus' — using \"sdk\"\n"
    )
    _clear_config(home)

    # (ii) default-rung resolution for all four surfaces writes NOTHING.
    _clear_backend_env(monkeypatch)
    for surface in SURFACES:
        try:
            invocation.backend_for(surface, home=home)
        except invocation.BackendUnavailable:
            pass
    assert capsys.readouterr().err == ""

    # (iii) every table value is a known backend.
    assert set(DEFAULT_BACKEND_FOR_SURFACE.values()) <= set(registry_mod.KNOWN_BACKENDS)


def test_fl4_the_flip_is_data_not_a_branch():
    src = inspect.getsource(registry_mod)
    tree = ast.parse(src)
    backend_for_node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "backend_for"
    )
    literals = {
        n.value
        for n in ast.walk(backend_for_node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "analyst" not in literals

    final = backend_for_node.body[-1]
    assert isinstance(final, ast.Return)
    dumped = ast.dump(final)
    assert "DEFAULT_BACKEND_FOR_SURFACE" in dumped

    # U-cleanup: `KNOWN_BACKENDS` has one member now, so the literal
    # "sdk" is unavoidable -- it is the two-arg fallback default of
    # `DEFAULT_BACKEND_FOR_SURFACE.get(surface, "sdk")` in the trailing
    # return, not evidence of a surface-keyed branch. `FL4`'s real
    # property survives as: "sdk" appears NOWHERE ELSE in the function
    # body (no `if surface == ...: return "sdk"`-shaped special case).
    non_final_literals = {
        n.value
        for node in backend_for_node.body[:-1]
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "sdk" not in non_final_literals
    final_literals = {
        n.value for n in ast.walk(final) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "sdk" in final_literals


def test_fl5_the_two_transcriptions_agree_over_the_full_matrix(tmp_path, monkeypatch, sdk_absent):
    # U-cleanup SEL7: extended, not weakened, to cover the refusal.
    # `CliBackend` is deleted -- `registry.backend_for` no longer ever
    # RETURNS a distinguishable "cli" object; a `cli` pin now RAISES
    # `BackendUnavailable` carrying the retirement message byte-for-
    # byte, distinguishable from the generic sdk-extra-missing message
    # `sdk_absent` produces for every other value. `provider.
    # resolve_backend_name`'s third element (`refused`) is the
    # INDEPENDENT transcription of that same fact -- `MAJOR-5` is
    # exactly a disagreement between the two, so this is the one test
    # that pins them agreeing on BOTH the folded name and the refusal.
    def _expected(surface, home):
        try:
            invocation.backend_for(surface, home=home)
        except invocation.BackendUnavailable as exc:
            return "sdk", str(exc) == registry_mod._CLI_RETIRED_MESSAGE
        return "sdk", False

    for surface in SURFACES:
        selector = invocation.SELECTOR_FOR_SURFACE[surface]
        home = tmp_path / f"fl5-{surface}"
        home.mkdir()

        # code-gate MAJOR-1: `_expected` calls `backend_for` itself, so a
        # "sdk" stimulus that happens to equal a surface's own default
        # (every surface, post U-flip) lets a rung-1..4 mutant in
        # `backend_for` move `derived` and `_expected` together --
        # `resolve_backend_name` is the INDEPENDENT transcription that
        # would actually diverge, but only if the stimulus differs from
        # the default. Inverted to "cli" so a real rung bug in either
        # transcription produces a genuine mismatch.
        for setup, teardown in (
            (lambda: monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "cli"),
             lambda: monkeypatch.delenv(f"SELF_LEARN_BACKEND_{selector}")),
            (lambda: monkeypatch.setenv("SELF_LEARN_BACKEND", "cli"),
             lambda: monkeypatch.delenv("SELF_LEARN_BACKEND")),
        ):
            _clear_backend_env(monkeypatch)
            setup()
            derived, _source, refused = provider.resolve_backend_name(home, surface)
            expected_name, expected_refused = _expected(surface, home)
            assert derived == expected_name, (surface, "env")
            assert (refused is not None) == expected_refused, (surface, "env", "refusal")
            teardown()

        _clear_backend_env(monkeypatch)
        _write_config(home, {f"backend_{surface}": "cli"})
        derived, _source, refused = provider.resolve_backend_name(home, surface)
        expected_name, expected_refused = _expected(surface, home)
        assert derived == expected_name, (surface, "config-surface")
        assert (refused is not None) == expected_refused, (surface, "config-surface", "refusal")
        _clear_config(home)

        _write_config(home, {"backend": "cli"})
        derived, _source, refused = provider.resolve_backend_name(home, surface)
        expected_name, expected_refused = _expected(surface, home)
        assert derived == expected_name, (surface, "config-general")
        assert (refused is not None) == expected_refused, (surface, "config-general", "refusal")
        _clear_config(home)

        # the default rung -- the cell `M1`/`M5` guard. Never refused:
        # the default value is always a real "sdk", never "cli".
        derived, source, refused = provider.resolve_backend_name(home, surface)
        expected_name, expected_refused = _expected(surface, home)
        assert derived == expected_name, (surface, "default")
        assert source == "default"
        assert refused is None and not expected_refused, (surface, "default", "refusal")

    # `test_provider.py::test_bk1_agrees_with_registry_over_matrix` passing
    # UNEDITED is verified at full-suite level (SU1), not re-imported here
    # -- importing it while `sdk_absent` is active would poison its own
    # module-level `from claude_agent_sdk import ...`.


def test_fl6_worker_untouched(env, sdk_fake_worker, monkeypatch):
    # A REAL worker.run() reaching the repair round (test_invocation.py's
    # `repair_run` fixture, rebuilt HERE rather than imported -- it
    # requires a fixture literally named `claude_shim`, and U-fake's `FX4`
    # legacy-alias guard permits exactly one importer of that name,
    # test_invocation.py) -- no backend env is set BY THIS TEST BODY.
    #
    # U-cleanup-A RE-BASELINE: originally "untouched" meant CLI, because
    # the bash shim ran unconditionally regardless of which backend
    # resolved (it just replaced whatever `claude` meant on PATH), so the
    # suite-wide conftest `cli` pin (AG3) was the only thing setting
    # `SELF_LEARN_BACKEND_WORKER`. The migrated `sdk_fake_worker`
    # fixture instead routes through `SdkBackend` -> `fake_claude.py`, so
    # IT is now the thing setting `SELF_LEARN_BACKEND_WORKER=sdk` for
    # both surfaces. The assertion still checks something real -- that a
    # worker.run() reaching BOTH the batch and repair rounds resolved the
    # SAME (fixture-configured) backend for `worker` and `worker-repair`
    # end to end -- just against the value the fixture now sets.
    from self_learn import worker

    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid)))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid)))
    worker.run(env.home)
    assert sdk_fake_worker["count"]() == 2  # batch + repair round both spawned the shim
    for surface in ("worker", "worker-repair"):
        assert provider.resolve_backend_name(env.home, surface)[0] == "sdk"


def test_fl6b_miner_untouched(miner_capture):
    # Kept in its OWN test (not combined with `test_fl6_worker_untouched`
    # above): both `env` and `miner_capture` independently overwrite
    # `SELF_LEARN_HOME` via `monkeypatch.setenv` -- composed in one test,
    # `miner_capture`'s fixture setup (which also runs the miner reader
    # invocation) races the worker/repair setup for that ambient var.
    # U-cleanup-A RE-BASELINE: see `test_fl6_worker_untouched` -- the
    # migrated `miner_capture` fixture sets `SELF_LEARN_BACKEND_MINER=sdk`
    # to route through `fake_claude.py`, so that is now the resolved value.
    assert miner_capture["argv"] != []
    assert provider.resolve_backend_name(miner_capture["home"], "miner-reader")[0] == "sdk"


def test_fl7_missing_extra_never_loses_a_lesson(tmp_path, monkeypatch, sdk_absent, capsys):
    _clear_backend_env(monkeypatch)
    home = tmp_path / "fl7-home"
    home.mkdir()

    with pytest.raises(invocation.BackendUnavailable) as exc_info:
        invocation.backend_for("analyst", home=home)
    assert str(exc_info.value) == registry_mod._SDK_UNAVAILABLE_MESSAGE

    from self_learn.invocation.contract import SessionSpec, containment_for

    spec = SessionSpec(
        surface="analyst",
        prompt="p",
        cwd=home,
        timeout=5.0,
        containment=containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS),
        log=lambda _msg: None,
        doctrine=None,
    )
    outcome = invocation.text_session(spec)
    assert outcome.ok is False
    assert outcome.failure == "unavailable"

    # `analyze` converts it to `AnalystError` carrying `W-i`'s literal.
    env = make_env(tmp_path / "fl7-sandbox")
    with pytest.raises(analyst.AnalystError) as ai:
        analyst.analyze(env.ledger, make_behavior())
    assert "pip install 'self-learn-cli[sdk]'" in str(ai.value)

    # `teach --route` end to end: exit 4, captured to pending/, the
    # refusal names the install command on stderr.
    _bootstrap_remotes(env)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    rc = cli_mod.main(_TEACH_ARGS + ["--route"])
    captured = capsys.readouterr()
    assert rc == 4
    assert "pip install" in captured.err
    pending = list((env.ledger / "skills" / "s" / "pending").glob("lrn-*.md"))
    assert len(pending) == 1
    assert list((env.ledger / "skills" / "s" / "resolved").glob("lrn-*.md")) == []


# ===================================================================== #
# T2-1 -- the contract-test harness (`leg`, params=LEGS)
# ===================================================================== #

_TEACH_ARGS = [
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

_TRIGGER_QUOTE = "About to edit .storage while HA is running."


# U-cleanup-B DELETE (§8.3): `_path_without_claude` -- PATH-filtering for
# the `_Leg.fail("not-found")` cli branch -- had zero callers left once
# that branch was deleted (`leg`'s single construction site always
# passes `name="sdk"`; the sdk `not-found` leg points
# `SELF_LEARN_SDK_CLI_PATH` at a nonexistent file instead of touching
# PATH at all).


def _bootstrap_remotes(env) -> None:
    """`Env`'s bare-remote pair (test_route_cli.py), rebuilt locally so
    `teach --route` can push on EITHER leg."""
    bare = env.ledger.parent / "u-sdka-remote.git"
    host_bare = env.ledger.parent / "u-sdka-host-remote.git"
    for bare_path, repo in ((bare, env.ledger), (host_bare, env.host)):
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare_path)], check=True)
        git(repo, "remote", "add", "origin", str(bare_path))
        git(repo, "push", "-q", "-u", "origin", "main")


def _roster_sha(home) -> str:
    from self_learn.worker import skill_roster

    return skill_roster(home).sha


def _skill_gates_yaml(home) -> str:
    return f"""gates:
  g0:
    reject: {{answer: "no"}}
    defer: {{answer: "no"}}
    canon: {{answer: "no"}}
  t1:
    attempted: false
    field_shaped:
      answer: "no"
      evidence: "{_TRIGGER_QUOTE}"
    separable: {{answer: null}}
    cost_bearing: {{answer: null}}
  t2:
    answer: "no"
    evidence: "{_TRIGGER_QUOTE}"
    match_path: null
  t3:
    answer: "yes"
    owner: "s"
    scan_terms: null
    roster_sha: "{_roster_sha(home)}"
  t3a:
    depth_behind_rule: {{answer: "no", evidence: null}}
    fs: {{verdict: "SILENT", evidence: "{_TRIGGER_QUOTE}"}}
  tn: {{answer: "no", terms: [], members: [], proposed_name: null}}
  t4: null
  e1: {{sightings: 1, post_demand_recurrence: false}}
  outcome: SKILL
flags: []
recommendation: route
"""


def _skill_proposal_text(home) -> str:
    return (
        "destination: skill-md\n"
        "alternates: [claude-md]\n"
        "rationale: deterministic guard beats advisory text\n" + _skill_gates_yaml(home)
    )


class _Leg:
    """`H-c` -- the handle IS the contract: `.name`, `.say(text)`,
    `.argv()`, `.fail(kind)`. `.home`/`.env` and the two lower-level
    readers (`.cwd()`, `pending_files()`/`resolved_files()`) are the
    plumbing the `HD`/`AR`/`DR` groups need to drive `teach --route` or
    inspect the raw transport."""

    def __init__(self, name, env, monkeypatch, tmp_path, *, out_path, argv_path, cwd_path=None):
        self.name = name
        self.env = env
        self.home = env.ledger
        self._mp = monkeypatch
        self._tmp_path = tmp_path
        self._out_path = out_path
        self._argv_path = argv_path
        self._cwd_path = cwd_path

    def restore(self) -> None:
        """Undo every `.fail()`-installed sabotage, WITHOUT ever touching
        the shared `monkeypatch` fixture's OTHER patches
        (`monkeypatch.undo()` would also revert this handle's own
        SELF_LEARN_SDK_CLI_PATH/PATH setup -- the BLOCKER-1 shape).

        U-cleanup-B DELETE (§8.3): the `if self.name == "cli":` branch
        (and the `shim_dir`/`_base_path` state it alone read) is
        unreachable dead code -- the `leg` fixture's single construction
        site always passes `name="sdk"` and never passes `shim_dir=`.
        Only the sdk branch's body remains, unconditional."""
        self._mp.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
        self._mp.delenv("SELF_LEARN_ANALYST_TIMEOUT", raising=False)
        self._mp.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
        self._mp.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")

    def say(self, text: str) -> None:
        self._out_path.write_text(text, encoding="utf-8")
        if self.name == "sdk":
            self._mp.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")

    def argv(self) -> list[str]:
        if not self._argv_path.exists():
            return []
        raw = self._argv_path.read_text(encoding="utf-8")
        return raw.split("\0")[:-1] if raw else []

    def cwd(self) -> str:
        return self._cwd_path.read_text(encoding="utf-8").strip()

    def pending_files(self):
        pending = self.home / "skills" / "s" / "pending"
        return sorted(pending.glob("lrn-*.md")) if pending.is_dir() else []

    def resolved_files(self):
        resolved = self.home / "skills" / "s" / "resolved"
        return sorted(resolved.glob("lrn-*.md")) if resolved.is_dir() else []

    def fail(self, kind: str) -> None:
        """`H-d`'s table, mechanized.

        U-cleanup-B DELETE (§8.3): the `if self.name == "cli":` branch
        (PATH-filtering sleep-shim/decoy sabotage for a `CliBackend`
        transport) is unreachable dead code -- the `leg` fixture's single
        construction site always passes `name="sdk"`. Only the sdk
        branch's body remains, unconditional."""
        mp = self._mp
        if kind == "exit":
            mp.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "error_result")
        elif kind == "timeout":
            mp.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")
            mp.setenv("SELF_LEARN_ANALYST_TIMEOUT", "0.5")
        elif kind == "not-found":
            mp.setenv("SELF_LEARN_SDK_CLI_PATH", "/nonexistent/claude-fake")
        elif kind == "os-error":
            bad = self._tmp_path / "leg-sdk-nonexec"
            bad.write_text("", encoding="utf-8")
            bad.chmod(0o644)
            mp.setenv("SELF_LEARN_SDK_CLI_PATH", str(bad))
        else:
            raise AssertionError(f"{kind!r}: installed by the caller directly (H-d/H-e)")


@pytest.fixture()
def leg(tmp_path, monkeypatch):
    """COLLAPSED (U-cleanup-A `CV2`/`CB-3`): formerly `params=LEGS`
    (`LEGS = ("cli", "sdk")`) -- every criterion parametrized over this
    fixture now runs the `sdk` leg ONLY, with no parametrization suffix
    on its node id. The `cli` branch (`H-a`) is UNUSED from here on
    (stays defined; U-cleanup-B deletes it, §8.3)."""
    name = "sdk"
    sandbox_root = tmp_path / f"leg-{name}-sandbox"
    sandbox_root.mkdir()
    env = make_env(sandbox_root)
    _bootstrap_remotes(env)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))

    out = tmp_path / f"leg-{name}-out.txt"
    out.write_text("", encoding="utf-8")
    argv_log = tmp_path / f"leg-{name}-argv.log"

    # `H-b`
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv("FAKE_CLAUDE_OUT", str(out))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")
    return _Leg(name, env, monkeypatch, tmp_path, out_path=out, argv_path=argv_log)


# ===================================================================== #
# AC -- the analyst output contract, on both backends (T2)
# ===================================================================== #


def test_ac1_same_yaml_same_proposal_on_both_legs(leg):
    leg.say(_skill_proposal_text(leg.home))
    proposal = analyst.analyze(leg.home, make_behavior())
    assert proposal["destination"] == "skill-md"
    assert proposal["alternates"] == ["claude-md"]
    assert proposal["rationale"] == "deterministic guard beats advisory text"
    record = make_behavior()
    proposal2 = analyst.analyze(leg.home, record)
    assert proposal2["record_sha"] == sha_anchor(record.body)
    # branch 1's sentinel must NOT leak into the proposal.
    assert "ANALYST-ASSISTANT-SENTINEL" not in str(proposal2)


def test_ac2_blocks_join_produces_the_same_proposal(leg):
    text = _skill_proposal_text(leg.home)
    leg._out_path.write_text(text, encoding="utf-8")
    # `H-c`'s ONE declared per-leg branch: the cli transport has a single
    # text channel (branch 1/2 are the same path there), so only the sdk
    # leg needs the `analyst_blocks` scenario switched in.
    if leg.name == "sdk":
        leg._mp.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_blocks")
    proposal = analyst.analyze(leg.home, make_behavior())
    assert proposal["destination"] == "skill-md"
    assert proposal["rationale"] == "deterministic guard beats advisory text"


def test_ac3_yaml_parsing_round_trips_and_refuses_identically(leg):
    body = "destination: skill-md\nrationale: r\n" + _skill_gates_yaml(leg.home)
    leg.say("```yaml\n" + body + "```\n")
    p1 = analyst.analyze(leg.home, make_behavior())
    leg.say("```\n" + body + "```\n")
    p2 = analyst.analyze(leg.home, make_behavior())
    leg.say(body)
    p3 = analyst.analyze(leg.home, make_behavior())
    assert p1["destination"] == p2["destination"] == p3["destination"] == "skill-md"

    leg.say("key: [1, 2\n  bad indent\n")
    with pytest.raises(analyst.AnalystError) as exc1:
        analyst.analyze(leg.home, make_behavior())
    assert "not valid YAML" in str(exc1.value)

    leg.say("just a string\n")
    with pytest.raises(analyst.AnalystError) as exc2:
        analyst.analyze(leg.home, make_behavior())
    assert str(exc2.value) == "analyst output is not a YAML mapping (got str)"


def test_ac4_cli_stamped_fields_win_on_both_legs(leg):
    leg.say(
        "destination: skill-md\n"
        "model: pwned-model\n"
        "analyzed_at: 1999-01-01T00:00:00Z\n"
        "record_sha: sha256:deadbeefdead\n"
        "rationale: r\n" + _skill_gates_yaml(leg.home)
    )
    record = make_behavior()
    proposal = analyst.analyze(leg.home, record)
    assert proposal["model"] == analyst.DEFAULT_ANALYST_MODEL
    assert proposal["record_sha"] == sha_anchor(record.body)
    assert proposal["analyzed_at"] != "1999-01-01T00:00:00Z"

    leg.say(
        'script: "#!/usr/bin/env bash\\necho pwned\\n"\n'
        "destination: skill-md\nrationale: r\n" + _skill_gates_yaml(leg.home)
    )
    proposal2 = analyst.analyze(leg.home, make_behavior())
    assert "script" not in proposal2


def test_ac5_unenumerated_fields_round_trip_verbatim(leg):
    import io

    from ruamel.yaml import YAML

    from support import hook_proposal_fields

    hook_fields = dict(hook_proposal_fields())
    hook_fields["probe_key"] = "probe-value"
    buf = io.StringIO()
    YAML(typ="safe").dump(hook_fields, buf)
    body = (
        "destination: hook\nalternates: [skill-md]\nrationale: r\n"
        + _hook_gates_yaml(leg.home)
        + buf.getvalue()
    )
    leg.say(body)
    proposal = analyst.analyze(leg.home, make_behavior())
    assert proposal["hook"] == hook_fields["hook"]
    assert proposal["examples"] == hook_fields["examples"]
    assert proposal["probe_key"] == "probe-value"


def _hook_gates_yaml(home) -> str:
    return f"""gates:
  g0:
    reject: {{answer: "no"}}
    defer: {{answer: "no"}}
    canon: {{answer: "no"}}
  t1:
    attempted: true
    field_shaped: {{answer: "yes", evidence: "{_TRIGGER_QUOTE}"}}
    separable: {{answer: "yes", evidence: "{_TRIGGER_QUOTE}"}}
    cost_bearing: {{answer: "yes", evidence: "{_TRIGGER_QUOTE}"}}
  t2:
    answer: "no"
    evidence: "{_TRIGGER_QUOTE}"
    match_path: null
  t3:
    answer: "yes"
    owner: "s"
    scan_terms: null
    roster_sha: "{_roster_sha(home)}"
  t3a:
    depth_behind_rule: {{answer: "no", evidence: null}}
    fs: {{verdict: "SILENT", evidence: "{_TRIGGER_QUOTE}"}}
  tn: {{answer: "no", terms: [], members: [], proposed_name: null}}
  t4: null
  e1: {{sightings: 1, post_demand_recurrence: false}}
  outcome: HOOK
flags: []
recommendation: route
"""


def test_ac6_roster_sha_honesty_on_both_legs(leg):
    body = (
        "destination: skill-md\nrationale: r\ngates:\n"
        "  g0: {reject: {answer: \"no\"}, defer: {answer: \"no\"}, canon: {answer: \"no\"}}\n"
        "  t1: {attempted: false, field_shaped: {answer: \"no\", evidence: \"x\"}, "
        "separable: {answer: null}, cost_bearing: {answer: null}}\n"
        "  t2: {answer: \"no\", evidence: \"x\", match_path: null}\n"
        "  t3: {answer: \"yes\", owner: \"s\", scan_terms: null, roster_sha: \"sha256:wrongwrong\"}\n"
        "  t3a: {depth_behind_rule: {answer: \"no\", evidence: null}, fs: {verdict: \"SILENT\", evidence: \"x\"}}\n"
        "  tn: {answer: \"no\", terms: [], members: [], proposed_name: null}\n"
        "  t4: null\n"
        "  e1: {sightings: 1, post_demand_recurrence: false}\n"
        "  outcome: SKILL\nflags: []\nrecommendation: route\n"
    )
    leg.say(body)
    with pytest.raises(analyst.AnalystError) as exc1:
        analyst.analyze(leg.home, make_behavior())
    assert "X3 Leg A" in str(exc1.value)

    body_b = body.replace(f'roster_sha: "sha256:wrongwrong"', f'roster_sha: "{ROSTER_UNAVAILABLE}"')
    leg.say(body_b)
    with pytest.raises(analyst.AnalystError) as exc2:
        analyst.analyze(leg.home, make_behavior())
    assert "X3 Leg B" in str(exc2.value)

    leg.say(_skill_proposal_text(leg.home))
    proposal = analyst.analyze(leg.home, make_behavior())
    assert proposal["gates"]["t3"]["roster_sha"] == _roster_sha(leg.home)


def _ac7_unavailable_and_refused_config(leg):
    """`H-e`'s two negative-control rows: a per-leg OUTCOME asymmetry
    (unlike `AC2`'s single declared branch), so it lives in a plain
    helper -- NOT a `^test_ac\\d+_`-named function -- and never touches
    the `AC` group's `leg.name ==` cap (`HY2`/`AC0`)."""
    # the loop above may have left `subprocess.run`/PATH sabotaged by a
    # `.fail()` call -- restore so the cli leg's negative-control route
    # can actually run.
    leg.restore()
    if leg.name == "sdk":
        # missing-extra: sdk_absent-style poisoning, applied via a NESTED
        # MonkeyPatch context -- NEVER `monkeypatch.undo()` on the shared
        # per-test fixture, which would also revert `leg`'s own
        # SELF_LEARN_SDK_CLI_PATH setenv (the exact BLOCKER-1 hazard
        # `conftest.py`'s tripwire docstring names).
        with pytest.MonkeyPatch.context() as local_mp:
            for name in list(sys.modules):
                if name == "self_learn.invocation_sdk" or name.startswith("self_learn.invocation_sdk."):
                    local_mp.delitem(sys.modules, name, raising=False)
            local_mp.setitem(sys.modules, "claude_agent_sdk", None)
            rc = cli_mod.main(_TEACH_ARGS + ["--route"])
            assert rc == 4
            pend = leg.pending_files()
            assert len(pend) == 1
            for p in pend:
                p.unlink()

    # refused-config, both legs -- `H-e`'s negative control lives on cli.
    (leg.home / "config.yaml").write_text(
        "provider:\n  name: bedrock\n  bedrock:\n    region: us-east-1\n", encoding="utf-8"
    )
    if leg.name == "sdk":
        rc = cli_mod.main(_TEACH_ARGS + ["--route"])
        assert rc == 4
        pend = leg.pending_files()
        assert len(pend) == 1
        record = Record.from_path(pend[0])
        assert record.routing is None
    else:
        leg.say(_skill_proposal_text(leg.home))
        rc = cli_mod.main(_TEACH_ARGS + ["--route"])
        assert rc == 0  # H-e: the same refusing config is INERT on cli
        assert leg.resolved_files() != []
    (leg.home / "config.yaml").unlink()


def test_ac7_never_lost_chain_per_failure_kind(leg, monkeypatch, capsys):
    for kind in ("exit", "timeout", "not-found", "os-error"):
        leg.fail(kind)
        rc = cli_mod.main(_TEACH_ARGS + ["--route"])
        captured = capsys.readouterr()
        assert rc == 4, kind
        assert "analysis failed" in captured.err, kind
        assert "captured to pending" in captured.err, kind
        assert leg.resolved_files() == [], kind
        pend = leg.pending_files()
        assert len(pend) == 1, kind
        record = Record.from_path(pend[0])
        assert record.status == "pending"
        assert record.routing is None
        for p in pend:
            p.unlink()

    _ac7_unavailable_and_refused_config(leg)


def test_ac8_happy_path_end_to_end_identical(leg, capsys):
    leg.say(_skill_proposal_text(leg.home))
    rc = cli_mod.main(_TEACH_ARGS + ["--route"])
    out = capsys.readouterr().out
    assert rc == 0
    assert leg.pending_files() == []
    resolved = leg.resolved_files()
    assert len(resolved) == 1
    record = Record.from_path(resolved[0])
    assert record.routing["by"] == "analyst"
    assert record.routing["destination"] == "skill-md"
    compiled = leg.env.skill_md.read_text(encoding="utf-8")
    assert ".storage" in compiled and "stop the container first" in compiled
    assert "analyst: destination skill-md" in out


# ===================================================================== #
# HD -- hardening (FW-87 and the containment the flip buys)
# ===================================================================== #


def test_hd1_fw87_both_backends_byte_exact_and_chained(leg):
    # Inverted guard (`HD1`): a re-raised OSError/ClaudeSDKError must fail
    # LOUDLY here, never be read as "a different error".
    leg.fail("os-error")
    try:
        analyst.analyze(leg.home, make_behavior())
    except analyst.AnalystError as exc:
        assert str(exc).startswith("analyst invocation failed (") and str(exc).endswith(")")
        # U-cleanup-B DELETE (§8.3): the `if leg.name == "cli":` branch
        # (byte-exact "permission denied" message) is unreachable dead
        # code -- the `leg` fixture's single construction site always
        # passes `name="sdk"`.
        assert exc.__cause__ is not None
    except Exception as exc:  # noqa: BLE001 -- any non-AnalystError escape (OSError included) is the failure
        pytest.fail(f"os-error escaped as {type(exc).__name__}, not AnalystError: {exc}")
    else:
        pytest.fail("os-error did not raise at all")

    # `M14` guard (mirrors wr6's indirection leg): the message must render
    # THROUGH `LOG_TEMPLATES["analyst"]`, not a hand-written local string.
    original = invocation.LOG_TEMPLATES["analyst"]
    mutated = invocation.LogTemplates(
        exited=original.exited, timed_out=original.timed_out,
        not_found=original.not_found, os_error="MUTATED OS ERROR ({exc})",
        unavailable=original.unavailable, detail_cap=original.detail_cap,
        detail_strip=original.detail_strip,
    )
    leg._mp.setitem(invocation.LOG_TEMPLATES, "analyst", mutated)
    with pytest.raises(analyst.AnalystError, match=r"^MUTATED OS ERROR \("):
        analyst.analyze(leg.home, make_behavior())


def test_hd2_sdk_leg_claudesdkerror_flavor_is_caught(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    bad = tmp_path / "hd2-nonexec"
    bad.write_text("", encoding="utf-8")
    bad.chmod(0o644)
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(bad))
    env = make_env(tmp_path / "hd2-sandbox")
    with pytest.raises(analyst.AnalystError) as exc_info:
        analyst.analyze(env.ledger, make_behavior())
    assert "Permission denied" in str(exc_info.value)


def test_hd3_fw87_chain_exits_4_both_legs(leg, capsys):
    leg.fail("os-error")
    rc = cli_mod.main(_TEACH_ARGS + ["--route"])
    err = capsys.readouterr().err
    assert rc == 4
    pend = leg.pending_files()
    assert len(pend) == 1


def test_hd4_seam_is_total_on_the_analyst_surface(leg):
    assert contract_mod.TRANSPORT["analyst"] is True
    assert contract_mod.LOG_TEMPLATES["analyst"].os_error is not None
    for kind in ("exit", "timeout", "not-found", "os-error"):
        leg.fail(kind)
        from self_learn.invocation.contract import SessionSpec, containment_for

        spec = SessionSpec(
            surface="analyst",
            prompt="p",
            cwd=leg.home,
            timeout=1.0 if kind == "timeout" else 5.0,
            containment=containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS),
            log=lambda _msg: None,
            doctrine=None,
        )
        try:
            outcome = invocation.text_session(spec)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{kind}: raised {type(exc).__name__} instead of returning an Outcome: {exc}")
        assert outcome.failure == kind, kind


def test_m16_transport_table_is_still_a_plain_mutable_dict(monkeypatch):
    """`M-16`/`CL5` (U-cleanup §11.1, `T-TRANSPORT-FLAG-STILL-MUTABLE`):
    `contract.TRANSPORT` was trimmed from a one-field dataclass carrier
    to a plain `dict[str, bool]` (`contract.py` ~:296, `BLOCKER-1`) so
    the table stays a mutable, table-level fact rather than something a
    maintainer must restructure a class to edit -- the property `S-48`'s
    `M11` evidence (the analyst-vs-worker/miner OSError/ClaudeSDKError
    split) depends on staying reproducible. `test_hd4_...` (above)
    already re-spells the ORIGINAL read half (`TRANSPORT["analyst"] is
    True`, was `.catches_os_error is True` pre-trim, `git show
    163a93e:plugins/self-learn/cli/tests/test_u_sdka.py` ~:1068); this
    covers the half a read alone cannot: that the table genuinely
    supports item assignment (not frozen, not a `MappingProxyType`, not
    a dataclass requiring a field-by-field rebuild to change one row),
    and that a mutation is PER-SURFACE, not an all-or-nothing table
    replacement."""
    assert isinstance(contract_mod.TRANSPORT, dict)
    assert not isinstance(contract_mod.TRANSPORT, MappingProxyType)
    monkeypatch.setitem(contract_mod.TRANSPORT, "analyst", False)
    assert contract_mod.TRANSPORT["analyst"] is False
    assert contract_mod.TRANSPORT["worker"] is True
    assert contract_mod.TRANSPORT["miner-reader"] is True


def _ctx():
    class _Ctx:
        pass

    return _Ctx()


def _call_charter(cb, tool_name, tool_input):
    return asyncio.run(cb(tool_name, tool_input, _ctx()))


def test_hd5_deny_all_writes_wired(tmp_path):
    containment = contract_mod.containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS)
    cb = charter_mod.build_can_use_tool(containment)
    for tool in ("Write", "Edit", "NotebookEdit", "Bash", "Task", "WebFetch"):
        result = _call_charter(cb, tool, {"file_path": str(tmp_path / "x")})
        assert isinstance(result, PermissionResultDeny), tool
    for tool in ("Read", "Grep", "Glob"):
        result = _call_charter(cb, tool, {})
        assert isinstance(result, PermissionResultAllow), tool
    hatch_open = containment.default_mode is None and bool(
        containment.write_globs or containment.write_exact
    )
    assert hatch_open is False

    # end to end: the callback is actually WIRED, not just unit-correct.
    home = tmp_path / "hd5-home"
    home.mkdir()
    target = home / "skills" / "s" / "pending" / "lrn-fake.md"
    from self_learn.invocation.contract import SessionSpec

    spec = SessionSpec(
        surface="analyst",
        prompt="ok_write",
        cwd=home,
        timeout=10.0,
        containment=containment,
        log=lambda _msg: None,
        doctrine=None,
    )
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
        mp.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
        mp.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
        mp.setenv("FAKE_CLAUDE_WRITE_TARGET", str(target))
        outcome = SdkBackend().text_session(spec)
    finally:
        mp.undo()
    tool_results = [e for e in outcome.tool_events if e["kind"] == "tool_result"]
    assert any(e["is_error"] for e in tool_results)
    assert any("write scope does not include" in str(e["content"]) for e in tool_results if e["is_error"])
    assert any("write scope does not include" in d.get("reason", "") for d in outcome.denials)


def test_hd6_isolation_and_strict_mcp(tmp_path):
    from self_learn.invocation.contract import SessionSpec

    home = tmp_path / "hd6-home"
    home.mkdir()
    spec = SessionSpec(
        surface="analyst",
        prompt="p",
        cwd=home,
        timeout=5.0,
        containment=contract_mod.containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS),
        log=lambda _msg: None,
        doctrine=None,
    )
    kwargs = sdk_backend_mod.options_kwargs(spec)
    assert kwargs["strict_mcp_config"] is True
    assert kwargs["mcp_servers"] == {}
    assert kwargs["setting_sources"] == []
    assert kwargs["settings"] is None
    assert kwargs["allowed_tools"] == []
    assert kwargs["permission_mode"] == "default"
    assert kwargs["include_partial_messages"] is False
    assert kwargs["max_turns"] == 30


def test_hd7_prompt_leaves_the_process_table(tmp_path, monkeypatch):
    # U-cleanup-A RE-BASE (spec §8.4b: "re-base onto the SDK process
    # table"): the ORIGINAL second half drove a REAL `CliBackend().
    # text_session(spec)` as a negative control -- "the same assertion
    # FAILS on the cli leg" -- to prove the sdk-side protection is real
    # by contrast. `AG1`'s tripwire makes that reach fatal by design,
    # and there is no longer a live cli leg to contrast against (every
    # surface resolves sdk by default post-`AG3`). Rebased onto the sdk
    # leg's OWN process table alone: `child_argv` below is not read from
    # a log file the fake CHOSE to write -- it is `sys.argv[1:]` as
    # `fake_claude.py`'s `main()` (RO-1's `_capture_argv_per_call`)
    # captured it from INSIDE the real, separately-`exec`'d child
    # process, i.e. byte-for-byte what `/proc/<pid>/cmdline` would have
    # shown for that live process. Never seeing the prompt there is the
    # process-table claim itself, checked directly and unconditionally,
    # not via contrast with a transport this build retires.
    from self_learn.invocation.contract import SessionSpec

    home = tmp_path / "hd7-home"
    home.mkdir()
    prompt = "UNIQUE-HD7-PROMPT-MARKER-98216"
    spec = SessionSpec(
        surface="analyst",
        prompt=prompt,
        cwd=home,
        timeout=5.0,
        containment=contract_mod.containment_for("analyst", allowed_tools=analyst.ANALYST_ALLOWED_TOOLS),
        log=lambda _msg: None,
        doctrine="DOCTRINE",
    )
    kwargs = sdk_backend_mod.options_kwargs(spec)
    for value in kwargs.values():
        assert prompt not in repr(value)

    argv_log = tmp_path / "hd7-argv.log"
    out = tmp_path / "hd7-out.txt"
    out.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv("FAKE_CLAUDE_OUT", str(out))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")
    SdkBackend().text_session(spec)
    child_argv = argv_log.read_text(encoding="utf-8").split("\0")[:-1]
    assert child_argv, "the real child never recorded its own argv"
    assert not any(prompt in a for a in child_argv)


def test_hd8_flip_does_not_change_the_model(tmp_path, monkeypatch):
    home = tmp_path / "hd8-home"
    home.mkdir()
    monkeypatch.setattr(analyst, "_model", lambda: "sentinel-model-hd8")
    assert provider.model_for("analyst", home=home) == "sentinel-model-hd8"


# ===================================================================== #
# AR -- the armor (byte-identity under `backend=cli`)
# ===================================================================== #

#: base-commit literal (`AR1`) -- `d800aeaad0d2...` measured at `89f8ef7`.
_AR1_TRIPWIRE_SHA256 = "1b012978efe34788697a854bd40f28d0c1c45125cbca9d56fea368907330b28f"


#: Region/whitelist form (gate MAJOR-2 redux): a name-based scan only
#: ever sees the tripwire's name on a `+`/`-` line, never in the `@@`
#: hunk-header context git derives around an INTERIOR edit -- so an
#: interior mutation (a body comment, or gutting `_tripped`'s raise so
#: `_find_cli` is never patched) evades a name scan even once the diff
#: leg is fixed to compare base-vs-WORKING-TREE. These are the exact
#: `+` line bodies (leading `+` stripped) sanctioned to add to
#: `conftest.py` -- any interior tripwire edit adds one more `+` line,
#: or a `-` line, regardless of what text it contains.
#:
#: U-cleanup-B RE-ANCHOR (second re-anchor of this test; see the prior
#: U-cleanup-A entry preserved in git history for the first). U-cleanup-A
#: added the `_cli_backend_unreached_tripwire` fixture (`AG1`) plus an
#: explanatory comment; U-cleanup-B DELETES that fixture outright (its
#: own docstring said it would be, §8.1: `CliBackend` no longer exists)
#: and replaces it with a short retirement comment. Because `_BASE_SHA`
#: (442385d) predates BOTH units, a base-vs-working-tree diff never sees
#: the fixture at all -- it was added and removed entirely between the
#: two endpoints this diff compares, so `removed` stays `[]` and `added`
#: is simply whatever text differs from base RIGHT NOW: the original
#: `AG3` comment (unchanged since U-cleanup-A, still present) plus this
#: unit's new retirement comment in place of the fixture.
#:
#: U-servehermetic (2026-08-27) adds one more sanctioned block: `_worker_
#: test_defaults` now sets `XDG_CONFIG_HOME` to a fresh `tmp_path` subdir
#: (the fix for `serve.unit_dir()` reading the real host's linked
#: `self-learn-host.service` unit during a test run), inserted between
#: the pre-existing `XDG_CACHE_HOME` line and the `AG3` paragraph -- so
#: its ten `+` lines land in `added` right where the diff places them,
#: between the two blank lines above and the `AG3` paragraph below.
_AR1_SANCTIONED_PIN_LINES = [
    '#: U-cleanup-B: `_cli_backend_unreached_tripwire` (U-cleanup-A `AG1`) is',
    '#: RETIRED here, exactly as its own docstring said it would be -- its',
    '#: subject, `CliBackend._run`, no longer exists (§8.1), so there is',
    "#: nothing left to guard being unreached. `AG2`'s negative control",
    '#: (`test_u_sdka.py::test_ag2_tripwire_fires_on_direct_clibackend_call`)',
    '#: is deleted alongside it, not retargeted -- it existed solely to prove',
    '#: THIS tripwire arms, and there is no tripwire left to prove.',
    '',
    '',
    '    # Config isolation for EVERY test (found 2026-08-27, U-servehermetic:',
    '    # `serve.unit_dir()` falls back to `XDG_CONFIG_HOME`, then to the',
    '    # real `~/.config/systemd/user`, exactly mirroring the cache-isolation',
    '    # reasoning above -- without this, a test session on a host that has',
    '    # ever linked the `self-learn-host.service` reference unit reads that',
    '    # REAL unit as "configured" and produces a live-host-dependent FAIL/',
    '    # SKIP split invisible to the U-engine Phase 2 gate, which ran before',
    '    # any host had linked the unit). Tests that redirect XDG themselves',
    '    # simply override this default, same convention as XDG_CACHE_HOME.',
    '    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-default"))',
    '    # U-cleanup-A `AG3`: the three suite-wide `cli` pins that used to sit',
    "    # here (U-sdka `Armor-1`'s analyst pin, U-flip's worker/miner pins)",
    '    # are REMOVED, not merely edited. Their premise was "every',
    '    # pre-existing test drives a bash PATH shim or a patched',
    '    # `subprocess.run`, i.e. the cli transport, and names no backend" --',
    "    # CV2/CB-3's migration has made that premise false: the ~109",
    '    # behaviour tests now drive `SdkBackend` -> `fake_claude.py`',
    '    # end to end (`sdk_fake_worker`/`sdk_fake_analyst`,',
    '    # `reader_leg`, `backend`). With no pin left here, EVERY surface now',
    '    # resolves through `DEFAULT_BACKEND_FOR_SURFACE` (all `sdk` since',
    '    # U-flip) unless a test overrides it.',
    '    # U-cleanup-B (code gate r1, NIT-5): this paragraph used to end by',
    '    # pointing at "the suite-wide default this unit\'s own `AG1`',
    '    # tripwire on `CliBackend._run` is meant to prove unreached in',
    '    # practice, not merely in theory" and "every remaining test that',
    '    # still needs `cli` for real names it explicitly via its own',
    '    # `monkeypatch.setenv`" -- both stale. `AG1`/`_cli_backend_',
    '    # unreached_tripwire` is RETIRED (see the docstring 30 lines above',
    '    # this fixture); `CliBackend._run` no longer exists to be reached',
    '    # or unreached. And no test "needs `cli` for real" any more --',
    '    # `cli` is a NAMED REFUSAL now (`registry._resolve`), never a',
    '    # second transport a test could drive; the handful of tests that',
    '    # still `monkeypatch.setenv(..., "cli")` (SEL1-6, the scoping-',
    '    # precedence tests) are asserting the refusal fires, not reaching',
    '    # a real subprocess.',
]


def test_ar1_tripwire_byte_unchanged():
    from conftest import _no_real_sdk_spawn_tripwire

    src = inspect.getsource(_no_real_sdk_spawn_tripwire)
    assert hashlib.sha256(src.encode()).hexdigest() == _AR1_TRIPWIRE_SHA256

    # Base vs WORKING TREE, not `..HEAD` -- in this uncommitted worktree
    # HEAD IS `_BASE_SHA`, so `..HEAD` is vacuous during the gating window
    # (gate MAJOR-2).
    diff = subprocess.run(
        ["git", "diff", _BASE_SHA, "--", "plugins/self-learn/cli/tests/conftest.py"],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    ).stdout
    removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    assert removed == []
    assert added == _AR1_SANCTIONED_PIN_LINES


# U-cleanup-A DELETE (`AG3`): `test_ar2_suite_wide_pin_is_a_default_not_
# the_thing_under_test`'s whole subject -- proving the suite-wide
# `SELF_LEARN_BACKEND_ANALYST=cli` pin in `_worker_test_defaults` was a
# mere DEFAULT rather than load-bearing test coverage (clearing it still
# resolved a real `SdkBackend`) -- ceases to exist the moment `AG3`
# removes that pin from `conftest.py` outright. There is no pin left to
# distinguish from "the thing under test"; the property it guarded
# (a clean env resolves `SdkBackend` for `analyst`) is already covered
# directly by `test_fl1b_default_rung_returns_a_real_sdkbackend_when_
# installed` above.


# U-cleanup-B DELETE: `test_ag2_tripwire_fires_on_direct_clibackend_call`
# (`AG2`) -- its whole subject was observing `_cli_backend_unreached_
# tripwire` (U-cleanup-A `AG1`) fire on a direct `CliBackend` call. Both
# the tripwire and `CliBackend` itself are deleted in this unit (§8.1,
# conftest.py); there is nothing left for a negative control to prove.


_AR3_REASONS = {
    ("test_invocation.py", "test_rg1_five_rung_precedence_resolves_in_isolation"): "flip (A-c)",
    ("test_invocation.py", "test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_through_log_templates"): "pin casualty (A-d); U-cleanup-A MAJOR-1 fold: un-skipped, sdk rebase",
    # U-cleanup-A MAJOR-1 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F): four
    # behaviour tests were left `@pytest.mark.skip`ped with no A4/§10.1
    # disposition -- migrated onto the sdk transport instead.
    ("test_invocation.py", "test_lg7_analyst_invocation_never_grows_worker_or_miner_log"): "U-cleanup-A (MAJOR-1 fold, sdk rebase)",
    ("test_invocation.py", "test_wr1_invoke_claude_signature_and_never_raises"): "U-cleanup-A (MAJOR-1 fold, sdk rebase)",
    ("test_invocation.py", "test_wr5_analyst_error_carries_cause_for_not_found_and_timeout"): "U-cleanup-A (MAJOR-1 fold, sdk rebase)",
    # Full-suite re-run (same fold round) surfaced a second-order casualty:
    # dropping `wr6` from `_SIM_2_NINE` (see that constant's own comment,
    # test_invocation_sdk.py) touched SU6's docstring (the "nine" -> "eight"
    # correction) -- an edit to an EXISTING function's body, not a rename/
    # add/remove, so it needs its own reason here rather than an
    # `_AR3_RENAMED`/`_AR3_REMOVED`/`_AR3_ADDED` entry. 22 tracked functions
    # now, not 21; the test's own name is historical, like `_SIM_2_NINE`'s.
    ("test_invocation_sdk.py", "test_su6_the_nine_request_the_fixture_and_it_is_singly_defined_and_scoped"): "U-cleanup-A (fold round, SU6 set edit)",
    ("test_invocation_sdk.py", "test_ou1_every_row_of_the_map_1_table"): "FW-87 (E-f)",
    ("test_invocation_sdk.py", "test_ou5_bare_oserror_caught_on_worker_miner_and_analyst"): "FW-87 (E-f)",
    ("test_invocation_sdk.py", "test_rs2_present_returns_sdkbackend_for_every_surface"): "Pin-1 casualty (A-e)",
    ("test_doctor_invocation.py", "test_dc2_switches_names_all_surfaces_and_changes_with_rung"): "flip (A-c)",
    ("test_doctor_invocation.py", "test_dc3_rollout_four_states"): "flip (A-c)",
    # U-flip: worker/worker-repair/miner-reader's default flipped to sdk
    # (same table rung the analyst flip, U-sdka, used) -- every entry
    # below is a rollout-state pin or a Pin-1-shaped rung-1-shadows-
    # rung-2 casualty caused by the matching conftest pins this unit
    # added (see `_AR1_SANCTIONED_PIN_LINES`'s U-flip extension).
    ("test_invocation.py", "test_wr2_miner_early_returns_precede_the_stray_sweep"): "flip (U-flip)",
    ("test_invocation.py", "test_rg2_each_rung_shadows_the_ones_below"): "flip (U-flip)",
    ("test_invocation.py", "test_rg6_empty_string_falls_through_silently"): "flip (U-flip)",
    ("test_invocation_sdk.py", "test_ch10_hatch_open_driven_end_to_end_from_the_real_variable"): "Pin-1 casualty (U-flip)",
    ("test_invocation_sdk.py", "test_ch13_silence_parity_on_both_hatch_paths"): "Pin-1 casualty (U-flip)",
    ("test_invocation_sdk.py", "test_rs2_present_resolves_absent_raises_byte_identical_unavailable"): "Pin-1 casualty (U-flip)",
    ("test_invocation_sdk.py", "test_rs4_non_import_error_from_claude_agent_sdk_propagates"): "Pin-1 casualty (U-flip)",
    ("test_invocation_sdk.py", "test_rs6_lazy_import_target_resolves_by_identity"): "Pin-1 casualty (U-flip)",
    ("test_doctor_invocation.py", "test_dc6_id_shapes_and_doc_i_gating"): "flip (U-flip)",
    ("test_doctor_invocation.py", "test_dc11_selftest_row"): "flip (U-flip)",
    ("test_doctor_invocation.py", "test_dc12_mixed_rollout_info_lines_per_surface"): "flip (U-flip)",
    ("test_doctor_invocation.py", "test_dc14_env_row_per_surface_and_catches_refusal"): "flip (U-flip)",
    ("test_doctor_invocation.py", "test_dc16_credentials_warn_not_fail_and_dc3_coupling"): "flip (U-flip)",
    # U-cleanup-A: sdk-only rebase of the twin-witness/log-line/argv-
    # membership tests (CV2/CB-3's 43-leg collapse fallout in
    # test_invocation.py; the CliBackend leg is gone, bodies rebased
    # onto `_run_sdk`/`SdkBackend` or a wire-level check).
    ("test_invocation.py", "test_av4_prompt_membership_on_real_invocations"): "U-cleanup-A (sdk rebase)",
    ("test_invocation.py", "test_fk2_each_fakestep_matches_sdkbackend_for_the_same_failure"): "U-cleanup-A (rename, sdk rebase)",
    ("test_invocation.py", "test_lg1_twelve_byte_identical_log_lines"): "U-cleanup-A (sdk rebase)",
    ("test_invocation.py", "test_lg2_repair_label_appears_only_in_repair_lines"): "U-cleanup-A (sdk rebase)",
    ("test_invocation.py", "test_lg3a_worker_g_format"): "U-cleanup-A (sdk rebase)",
    ("test_invocation.py", "test_lg3b_miner_no_g_format"): "U-cleanup-A (sdk rebase)",
    ("test_invocation.py", "test_lg3c_timeout_display_is_actually_read"): "U-cleanup-A (sdk rebase)",
    ("test_invocation.py", "test_lg5_detail_rendering_per_surface"): "U-cleanup-A (sdk rebase, dropped stdout/stderr-invert leg)",
    ("test_invocation.py", "test_lg6_clean_invocation_logs_nothing"): "U-cleanup-A (sdk rebase)",
    ("test_invocation.py", "analyst_capture"): "U-cleanup-A (fixture, adds prompt_wire key)",
    ("test_invocation.py", "analyst_shim"): "U-cleanup-A (fixture, sdk-backed + prompt log)",
    ("test_invocation.py", "miner_capture"): "U-cleanup-A (fixture, sdk-backed)",
    ("test_invocation_sdk.py", "test_ou3_sdk_not_found_wording_and_template_table_authority"): "U-cleanup-A (rename, RO-6)",
    # U-cleanup-B: `SessionSpec.cli_argv_builder`/`.cli_settings_writer`
    # -> `.doctrine` rebase (§8.1) touches every `_spec()` test helper
    # and every test that reads its own precedence/witness/pin machinery
    # against `TRANSPORT`'s new `dict[str, bool]` shape or `KNOWN_BACKENDS
    # = ("sdk",)`.
    ("test_invocation.py", "_spec"): "U-cleanup-B (doctrine rebase, §8.1)",
    # FW-117 (2026-08-28): `test_cn6_witnesses_a_and_b_agree_statically`'s
    # U-cleanup-B-era edit above is superseded -- the function is now
    # DELETED outright (its last leg, worker-repair, lost its witness
    # function too), so it moves to `_AR3_REMOVED` instead and drops out
    # of this reasons table entirely (a deleted function has no body left
    # to reason about an edit to).
    ("test_invocation.py", "test_fk3_fake_is_not_reachable_from_backend_for"): "U-cleanup-B (SdkBackend rebase)",
    ("test_invocation.py", "test_hy3_witness_b_is_sha_pinned"): "U-cleanup-B (_HY3_SHAS trimmed, §8.1); FW-117 (2026-08-28, trimmed again: three witnesses -> two)",
    ("test_invocation.py", "test_cn9_direction_guard_one_hop_local_taint"): "FW-117 (2026-08-28): docstring only -- named this file's own CN6/CN7 legs, both deleted",
    ("test_invocation.py", "test_rg3_unknown_value_falls_closed_with_byte_exact_warning"): "U-cleanup-B (SEL5, fold target cli->sdk)",
    ("test_invocation.py", "test_rg8_pyproject_sdk_extra_matches_ui_pin"): "U-cleanup-B (DEP3, pin moves to dependencies)",
    ("test_invocation.py", "test_fk1_fakebackend_records_specs_prompts_and_doctrines"): "U-cleanup-B (rename, argvs -> doctrines)",
    ("test_invocation_sdk.py", "_spec"): "U-cleanup-B (doctrine rebase, §8.1)",
    ("test_invocation_sdk.py", "test_op10_system_prompt_never_none_and_analyst_appends"): "U-cleanup-B (doctrine rebase, §8.1)",
    ("test_invocation_sdk.py", "test_op13_argv_read_set_is_closed"): "U-cleanup-B (re-baselined, BLOCKER-5/§8.4b)",
    ("test_invocation_sdk.py", "test_op11_model_from_provider_unconditionally"): "U-cleanup-B (rename, argv-edge leg dropped)",
    ("test_invocation_sdk.py", "test_op4_settings_always_none"): "U-cleanup-B (rename, settings-writer half dropped)",
    ("test_invocation_sdk.py", "test_rs7_project_dependencies_include_sdk_and_extra_is_empty_alias"): "U-cleanup-B (rename, DEP3 inverted)",
    # U-cleanup-B (§8.3, R-1): the `claude_shim = sdk_fake_worker`
    # compat alias is deleted from test_repair.py -- its one consumer,
    # test_invocation.py, now imports and requests `claude_cli_shim_
    # worker` directly (8 sites renamed).
    ("test_invocation.py", "repair_run"): "U-cleanup-B (§8.3, claude_shim -> sdk_fake_worker rename)",
    ("test_invocation.py", "test_rg5_shimmed_worker_run_completes_under_sdk_selection"): "U-cleanup-B (§8.3, claude_shim -> sdk_fake_worker rename)",
    # U-kl4 (2026-08-28): the pgrep-based liveness check was host-global
    # (matched ANY process on the machine, not just this run's own child
    # -- measured 2/2 parallel-suite runs false-red, solo green).
    # Rebuilt to identify the child by PID, read off a new
    # `SdkOutcome.child_pid` field (`backend.py`) instead of a name
    # pattern.
    ("test_invocation_sdk.py", "test_kl4_hang_sigterm_ignored_child_is_gone_after_run_sync_returns"): "U-kl4 (pid-keyed liveness check, root-cause fix for the host-global pgrep false-red)",
}

_AR3_RENAMED = {
    "test_invocation.py": {
        "test_fk2_each_fakestep_matches_clibackend_for_the_same_failure": "test_fk2_each_fakestep_matches_sdkbackend_for_the_same_failure",
        # U-cleanup-B: `FakeBackend.argvs` -> `.doctrines` rebase.
        "test_fk1_fakebackend_records_specs_prompts_and_argvs": "test_fk1_fakebackend_records_specs_prompts_and_doctrines",
    },
    "test_invocation_sdk.py": {
        "test_ou5_bare_oserror_escapes_worker_miner_caught_analyst_reraised": "test_ou5_bare_oserror_caught_on_worker_miner_and_analyst",
        "test_ou3_failure_legs_render_byte_identical_to_clibackend_and_respect_the_template_table": "test_ou3_sdk_not_found_wording_and_template_table_authority",
        # U-cleanup-B: OP11's argv-edge leg dropped (§8.1 deletes
        # `_read_argv_flag`), OP4 simplified to a plain settings=None
        # loop (§8.1 deletes the settings-writer half), DEP3 inverts
        # RS7 (the sdk pin moves from the `[sdk]` extra into main deps).
        "test_op11_model_from_provider_not_argv_and_append_system_prompt_last_element_edge": "test_op11_model_from_provider_unconditionally",
        "test_op4_settings_none_but_writer_still_called": "test_op4_settings_always_none",
        "test_rs7_project_dependencies_unchanged_and_sdk_in_dev_and_extra_only": "test_rs7_project_dependencies_include_sdk_and_extra_is_empty_alias",
    },
    "test_doctor_invocation.py": {},
}

#: U-cleanup-A: functions DELETED outright (CLI-only argv/transport
#: machinery with no sdk equivalent -- CV2's own §3.4 measurement and
#: replacement-coverage disposition) and functions ADDED outright (new
#: sdk-side helpers/tests with no base-commit counterpart). Neither
#: shape existed in this bookkeeping before U-cleanup-A; `_AR3_RENAMED`
#: only covers the old-name/new-name pairs, so a pure add or a pure
#: delete needs its own declared set or `base_only`/`now_only` would
#: silently stop matching and mask an unauthorized change instead of
#: catching one.
#: U-cleanup-B additions (§8.1/§8.4a): the CLI-only argv/transport/
#: settings-writer machinery those tests exercised is deleted outright,
#: with no sdk equivalent to rebase onto (15 in test_invocation.py --
#: the AV/TR/WR/CN7/LG4 group Phase A left `@pytest.mark.skip`ped with
#: its own "delete" disposition; 4 in test_invocation_sdk.py -- the argv
#: helper functions and OP12's settings-writer-ordering test). FW-117
#: (2026-08-28) fold: this count was pre-existing STALE at "12" --
#: enumerated from the current set, the AV/TR/WR/CN7/LG4 group is 15
#: (av x4, tr x7, wr x2, cn7_worker, lg4); `cn8`/`cn10` and
#: `_assert_argv_matches_containment_iff` are U-cleanup-A (see the
#: paragraph above), and `cn6`/`cn7_repair_leg` are FW-117's own -- none
#: counted in this group's tally.
_AR3_REMOVED: dict[str, frozenset[str]] = {
    "test_invocation.py": frozenset(
        {
            "_assert_argv_matches_containment_iff",
            "test_av1_argv_equals_surfaces_own_builder_output_recomputed",
            "test_av2_worker_argv_shape",
            "test_cn10_argv_is_the_third_witness_iff_both_directions",
            "test_cn8_twin_witnesses_agree_at_runtime_on_a_repair_producing_run",
            "test_av3_settings_writer_called_before_argv_builder",
            "test_av4_transport_kwargs_input_presence",
            "test_cn7_worker_leg_over_all_four_switch_combinations",
            "test_lg4_miner_timeout_read_at_call_time",
            # was Phase A's rename target (test_tr4_bare_os_error_is_
            # caught_on_analyst_worker_and_miner) -- that target is
            # ITSELF now deleted, folded into the TR1-TR7 group below,
            # so this is a pure removal (base name), not a rename.
            "test_tr4_bare_os_error_escapes_analyst_but_not_worker_or_miner",
            "test_tr1_surfaces_reach_the_right_transport",
            "test_tr2_miner_popen_kwargs",
            "test_tr3_miner_timeout_killpg_and_wait",
            "test_tr5_cwd_passed_for_every_surface",
            "test_tr6_argv_positional_timeout_keyword",
            "test_tr7_transport_reached_through_the_subprocess_module_attribute",
            "test_wr3_miner_rc_nonzero_does_not_short_circuit",
            "test_wr4_outcome_stdout_per_surface",
            # FW-117 (2026-08-28): `worker.write_repair_settings_file`
            # deleted (dead write, `A-2`) -- these two lost their sole
            # witness function to agree against, same reasoning as the
            # `test_cn8`/`test_cn7_worker_leg...` removals above.
            "test_cn6_witnesses_a_and_b_agree_statically",
            "test_cn7_repair_leg_over_both_enforce_values",
        }
    ),
    "test_invocation_sdk.py": frozenset(
        {
            "_analyst_argv",
            "_miner_argv",
            "_worker_argv",
            "test_op12_settings_writer_called_before_argv_builder",
        }
    ),
}

_AR3_ADDED: dict[str, frozenset[str]] = {
    "test_invocation.py": frozenset(
        {
            "_run_sdk",
            "_sdk_env",
            "_analyst_fail_sdk",
            # U-cleanup-B T-UNKNOWN-STILL-SDK (SEL5's discriminator, S11.1):
            "test_t_unknown_still_sdk_write_session_succeeds_not_refused",
            # U-cleanup-B T-CLI-REFUSED-ENV/ALL-SURFACES/COARSE/CONFIG
            # (SEL1-4, §11.1):
            "test_sel1_env_selector_cli_refused_through_text_session",
            "test_sel2_all_four_surfaces_refuse_through_their_own_templates",
            "test_sel3_coarse_rung_cli_refuses_identically",
            "test_sel4_config_backend_worker_cli_refuses_and_names_that_key",
            # U-cleanup-B T-DOCTRINE-REACHES-SDK (M-5, §11.1):
            "test_m5_doctrine_reaches_sdk_system_prompt_from_the_real_call_site",
        }
    ),
    "test_invocation_sdk.py": frozenset(
        {
            "test_fake_argv_per_call_ro1",
            "test_fake_multi_write_ro3",
            "test_fake_per_call_error_ro4",
            "test_fake_prompt_log_ro2",
            "test_templates_byte_pinned_ro6",
            # U-kl4 (2026-08-28): the pid-keyed liveness-check helpers
            # (module-level, shared by both `test_kl4_...` and its
            # positive control below) plus the positive control itself.
            "_proc_start_ticks",
            "_child_gone",
            "test_kl4a_pid_check_reddens_when_the_explicit_kill_is_disabled",
            # U-kl4 gate r1 fold (2026-08-28): B-1's reap helper (used by
            # `test_kl4a_...`'s finally, once it captures the pid FIRST)
            # and N/D-2's new committed test (child_pid is None on the
            # not-found path).
            "_reap_best_effort",
            "test_kl4b_child_pid_is_none_on_a_path_where_no_child_ever_spawned",
        }
    ),
    "test_doctor_invocation.py": frozenset(
        {
            # U-cleanup-B T-DOCTOR-SWITCHES (SEL6, §11.1): the `switches`
            # row's REFUSED rendering had no test asserting it directly.
            "test_dc17_switches_row_reports_cli_selection_as_refused",
            # U-papercuts P-2: bare `self-learn doctor` (no `<verb>`) now
            # defaults to `doctor invocation` instead of printing a usage
            # error — the positive test (byte-identical stdout/stderr/rc
            # against the explicit `doctor invocation` form) and its
            # negative control (`doctor bogus` stays an argparse usage
            # error, unaffected by the new default).
            "test_p2_bare_doctor_is_byte_identical_to_doctor_invocation",
            "test_p2_doctor_unknown_verb_still_a_usage_error",
        }
    ),
}

_AR3_ONE_LINE_ONLY = {
    "test_rs2_present_returns_sdkbackend_for_every_surface",
}
#: `test_wr6_...` LEFT `_AR3_ONE_LINE_ONLY` in the code gate r1 MAJOR-1
#: fold (8uvjHmdKaUd6PI3tSyB-F): it was a one-line pin casualty (`A-d`)
#: before this build un-skipped and fully rebased it onto sdk (new legs,
#: not a single added line) -- the narrower one-line-only shape no
#: longer describes it.


def test_ar3_edited_is_exactly_21_functions_with_reasons():
    # code-gate NIT: this criterion was
    # `..._is_exactly_eight_functions_with_reasons` -- U-flip's Pin-1/
    # rollout-state fallout in test_invocation.py, test_invocation_sdk.py,
    # and test_doctor_invocation.py added 13 more tracked functions to
    # `_AR3_REASONS` (8 U-sdka + 13 U-flip = 21). U-cleanup-A adds its
    # own casualties on top via `_AR3_REMOVED`/`_AR3_ADDED` (pure
    # deletes/adds, tracked but NOT counted in `_AR3_REASONS` -- a
    # function with no base-commit body to diff against has no "edit"
    # to reason about) plus 14 more `_AR3_REASONS` entries for bodies
    # that changed name-for-name or were rebased onto `SdkBackend`.
    touched: set[tuple[str, str]] = set()
    for relpath in ("test_invocation.py", "test_invocation_sdk.py", "test_doctor_invocation.py"):
        full = f"plugins/self-learn/cli/tests/{relpath}"
        base_text = _source_at(_BASE_SHA, full)
        base_funcs = _top_level_funcs(base_text)
        now_text = (Path(__file__).parent / relpath).read_text(encoding="utf-8")
        now_funcs = _top_level_funcs(now_text)

        renamed = _AR3_RENAMED[relpath]
        removed = _AR3_REMOVED.get(relpath, frozenset())
        added = _AR3_ADDED.get(relpath, frozenset())
        base_only = set(base_funcs) - set(now_funcs)
        now_only = set(now_funcs) - set(base_funcs)
        assert base_only == set(renamed) | removed, (relpath, "removed", base_only)
        assert now_only == set(renamed.values()) | added, (relpath, "added", now_only)

        shared = set(base_funcs) & set(now_funcs)
        for name in shared:
            base_src = _func_source(base_text, base_funcs[name])
            now_src = _func_source(now_text, now_funcs[name])
            if base_src != now_src:
                touched.add((relpath, name))
                assert (relpath, name) in _AR3_REASONS, (relpath, name, "unauthorized edit")
                if name in _AR3_ONE_LINE_ONLY:
                    assert _assert_dumps(base_funcs[name]) == _assert_dumps(now_funcs[name]), (
                        relpath, name, "an assert changed"
                    )
                    base_stmts = len(base_funcs[name].body)
                    now_stmts = len(now_funcs[name].body)
                    assert now_stmts == base_stmts + 1, (relpath, name, "not exactly one line added")
            else:
                assert (relpath, name) not in _AR3_REASONS, (relpath, name, "declared edited but byte-identical")
        for old_name, new_name in renamed.items():
            touched.add((relpath, new_name))
            assert (relpath, new_name) in _AR3_REASONS, (relpath, new_name)

    assert touched == set(_AR3_REASONS)


def test_ar5_pin1_class_is_closed_by_census():
    """`Pin-1`'s casualty class, re-run as a census over the WHOLE suite:
    every test setting `SELF_LEARN_BACKEND=sdk` (rung 2) that reaches a
    surface conftest pins at rung 1 -- `analyst` (U-sdka's own pin) or
    `worker`/`worker-repair`/`miner-reader` (U-flip's matching
    `SELF_LEARN_BACKEND_WORKER`/`_MINER` pins) -- or iterates `SURFACES`,
    without first clearing the relevant rung-1 var(s), directly or via an
    autouse fixture in its module. This census recognizes exactly the two
    SYSTEMIC protections Pin-1 itself names (`_clear_backend_env(`'s
    convention, or an autouse module fixture) -- a same-function, one-off
    inline `delenv` is deliberately NOT credited: it is what makes a test
    a census STABLE, TRACKED member rather than a moving target that
    vanishes the moment it grows its own fix. U-flip's generalization
    (WORKER/MINER, not just ANALYST) surfaces three more members of
    exactly this shape -- `test_rs2_present_resolves_absent_raises_
    byte_identical_unavailable`, `test_rs4_non_import_error_from_
    claude_agent_sdk_propagates`, `test_rs6_lazy_import_target_resolves_
    by_identity` -- each fixed with a same-function, one-off inline
    `delenv("SELF_LEARN_BACKEND_WORKER")` for the same reason `test_rs2`
    itself was."""
    tests_dir = Path(__file__).parent
    immune_modules = {"test_doctor_invocation.py", "test_provider.py"}  # autouse _clear_provider_env
    casualties: set[str] = set()

    for path in sorted(tests_dir.glob("test_*.py")):
        if path.name in immune_modules:
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            src = ast.get_source_segment(text, node)
            if 'setenv("SELF_LEARN_BACKEND", "sdk")' not in src:
                continue
            reaches_pinned_surface = any(
                literal in src
                for literal in (
                    '"analyst"', "'analyst'",
                    '"worker"', "'worker'",
                    '"worker-repair"', "'worker-repair'",
                    '"miner-reader"', "'miner-reader'",
                    "SURFACES",
                )
            )
            if not reaches_pinned_surface:
                continue
            if "_clear_backend_env(" in src:
                continue
            casualties.add(node.name)

    assert casualties == {
        "test_rs2_present_returns_sdkbackend_for_every_surface",
        "test_rs2_present_resolves_absent_raises_byte_identical_unavailable",
        "test_rs4_non_import_error_from_claude_agent_sdk_propagates",
        "test_rs6_lazy_import_target_resolves_by_identity",
    }


# U-cleanup-A DELETE (spec §8.4b's own disposition: "ar4 delete (its
# subject, the env-var rollback, ceases to exist -- §5)"): `test_ar4_
# byte_identity_under_the_rollback` explicitly set `SELF_LEARN_BACKEND_
# ANALYST=cli` and drove `analyst.analyze()` through a REAL bash-shimmed
# `CliBackend` -- exactly the "env-var rollback to cli" escape hatch §5
# retires. It also reaches `CliBackend._run` for real, which `AG1`'s
# tripwire now makes fatal by design. The `AnalystError` message-mapping
# coverage it carried (not-found/timeout/exit/unavailable, byte-exact)
# has its sdk-side counterpart in `test_ou1_every_row_of_the_map_1_
# table`/`test_ou5_bare_oserror_caught_on_worker_miner_and_analyst`
# (`test_invocation_sdk.py`).


# ===================================================================== #
# DR -- doctor and operator reporting
# ===================================================================== #


def test_dr1_switches_row_and_only_that_row_changes(tmp_path, monkeypatch):
    for var in (
        "SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER",
        "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST",
    ):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "dr1-home"
    home.mkdir()
    rows_default = provider.preflight(home)
    switches = next(r for r in rows_default if r.name == "switches")
    assert "analyst: backend=sdk (default)" in switches.detail
    # U-flip flipped worker's default to sdk too (same table).
    assert "worker: backend=sdk (default)" in switches.detail

    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    rows_pinned = provider.preflight(home)
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST")

    def _keyed(rows):
        return {(r.name, r.surface, r.verdict, r.detail) for r in rows}

    diff = _keyed(rows_default) ^ _keyed(rows_pinned)
    changed_names = {name for name, *_ in diff}
    assert changed_names == {"switches"}, changed_names


def test_dr2_bedrock_rollout_delta_full_row_set(tmp_path, monkeypatch):
    for var in (
        "SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER",
        "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST",
    ):
        monkeypatch.delenv(var, raising=False)
    # U-flip flipped worker/worker-repair/miner-reader's default to sdk
    # alongside the analyst's; pin them back to cli so this fixture keeps
    # its intended shape -- one surface (analyst) sdk, three cli -- which
    # is what the "mixed" (four INFO rollout rows) and per-surface
    # assertions below are about.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    home = tmp_path / "dr2-home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "provider:\n  name: bedrock\n  bedrock:\n    region: us-east-1\n", encoding="utf-8"
    )
    rows = provider.preflight(home)
    by_name = {}
    for r in rows:
        by_name.setdefault(r.name, []).append(r)

    consistency = [r for r in by_name.get("consistency", []) if r.surface == "analyst"]
    assert consistency and consistency[0].verdict == "FAIL"
    assert consistency[0].cause == "bedrock-model-is-alias"
    assert "refused-config: " in consistency[0].detail
    assert "Anthropic alias, not a Bedrock id" in consistency[0].detail

    credentials = by_name["credentials"][0]
    assert credentials.verdict == "WARN"
    assert "no mechanism found (IMDS not probed — see R-4)" == credentials.detail

    env_analyst = [r for r in by_name["env"] if r.surface == "analyst"][0]
    assert env_analyst.verdict == "FAIL"

    models_analyst = [r for r in by_name["models"] if r.surface == "analyst"][0]
    assert models_analyst.verdict == "FAIL"

    rollout_rows = by_name["rollout"]
    assert len(rollout_rows) == 4
    for r in rollout_rows:
        assert r.verdict == "INFO"

    switches = by_name["switches"][0]
    assert switches.verdict == "INFO"

    for cli_surface in ("worker", "worker-repair", "miner-reader"):
        env_row = [r for r in by_name["env"] if r.surface == cli_surface][0]
        assert env_row.verdict in ("SKIP",)


def test_dr3_wholly_inert_state_is_constructed_by_pinning_every_surface_to_cli(tmp_path, monkeypatch):
    # U-flip: this criterion used to construct the wholly-inert state by
    # pinning the analyst ALONE back to cli (worker/worker-repair/
    # miner-reader were already cli by default). U-flip flipped their
    # default to sdk too, so "the pin" is now the general rung, which
    # forces every surface without a more specific override to cli.
    home = tmp_path / "dr3-home"
    home.mkdir()
    (home / "config.yaml").write_text("provider:\n  name: bedrock\n", encoding="utf-8")

    for var in (
        "SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER",
        "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST",
    ):
        monkeypatch.delenv(var, raising=False)
    rows_unpinned = provider.preflight(home)
    rollout_unpinned = [r for r in rows_unpinned if r.name == "rollout"]
    assert not (len(rollout_unpinned) == 1 and rollout_unpinned[0].verdict == "FAIL")

    monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
    rows_pinned = provider.preflight(home)
    rollout_pinned = [r for r in rows_pinned if r.name == "rollout"]
    assert len(rollout_pinned) == 1
    assert rollout_pinned[0].verdict == "FAIL"


# ===================================================================== #
# HY -- hygiene
# ===================================================================== #


def test_hy1_this_file_contains_no_bare_claude_argv_literal():
    import re

    pattern = re.compile(r'\[\s*"claude"\s*\]')
    text = Path(__file__).read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            assert "worker._invoke_claude(" in line, (i, line)


def test_hy2_no_network_no_real_model_at_most_one_leg_name_branch():
    text = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)

    # every sdk-driving test sets SELF_LEARN_SDK_CLI_PATH somewhere in the
    # file (the `leg` fixture and the standalone sdk-leg tests both do).
    assert "SELF_LEARN_SDK_CLI_PATH" in text

    # production code never reads the fake's test-only knobs.
    src_dir = Path(__file__).parent.parent / "src" / "self_learn"
    for py in src_dir.rglob("*.py"):
        body = py.read_text(encoding="utf-8")
        for banned in ("FAKE_CLAUDE_FORCE_SCENARIO", "FAKE_CLAUDE_OUT", "FAKE_CLAUDE_ARGV_LOG"):
            assert banned not in body, (py, banned)

    # AC0/H-c's cap: at most one `leg.name ==` comparison in the AC group.
    ac_funcs = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_ac")
        and re.match(r"^test_ac\d+_", n.name)
    ]
    branch_count = 0
    for node in ac_funcs:
        src = ast.get_source_segment(text, node)
        branch_count += src.count("leg.name ==") + src.count('leg.name=="') + src.count("leg.name is ")
    assert branch_count <= 1, branch_count


#: `HY3` -- the ten pre-existing `fake_claude.py` scenarios, sha-pinned
#: to their base-commit bytes. U-cleanup-A repins `_scenario_error_result`
#: alone: its body gained an optional `FAKE_CLAUDE_ERROR_TEXT` override
#: (default `"boom"` unchanged, see the function's own comment) needed by
#: `test_lg5`'s sdk-rebased detail-rendering leg. Every other entry below
#: is still the literal base-commit byte pin.
_HY3_SCENARIO_SHAS = {
    "_scenario_ok_text": "62c5de5ba8d4870df7ad9c657bb78e6aeb41215f2dfa67357b3654fa2399bd7c",
    "_scenario_ok_blocks_only": "55a2ab044a4892756072a85141c5eed59f59fedf0daae6ceeb2243a4f2cd1050",
    "_scenario_ok_write": "1adacd1464e3556f1e55ee735c06fc8b1bef8096843e377d70a239b7f3c3c6c2",
    "_scenario_error_result": "43fee6fd00ec92a447e1e36edee8c6210cf6ce227badb8f2e8416434ad34e0d9",
    "_scenario_no_result": "102fd9240ce702f26bd8bbc0b906135bbe37405738d0615619a943516bccc6ac",
    "_scenario_hard_exit": "ddf6d99171ba9b50cfa07c24fa188692329c839a9c32a57b5308aea1a17fa84d",
    "_scenario_hang": "0750312cb7e5bd7b4abe4a7130809987b5717e02a13a7cb2dfd4c8f66b87da7f",
    "_scenario_hang_sigterm_ignored": "82a5149929ce24dd9e57c26e44c3c43f663a15db7f5a4a1607f976b4516b3a29",
    "_scenario_malformed_line": "3a5f4f3b67a40fc99cde1c228c7a68711975747b10f0fc9a23e04e3ec6cab691",
    "_scenario_unknown_message_type": "82579f9dec6827d60b6e940c1d62d8dccdfd14effab78a815059e6800afa2fcf",
}


def test_hy3_fake_claude_additions_are_additive():
    fake_path = Path(__file__).parent / "fixtures" / "fake_claude.py"
    text = fake_path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name, expected_sha in _HY3_SCENARIO_SHAS.items():
        assert name in funcs, name
        src = ast.get_source_segment(text, funcs[name])
        assert hashlib.sha256(src.encode()).hexdigest() == expected_sha, name

    import fixtures.fake_claude as fake_mod

    expected_keys = {name[len("_scenario_") :] for name in _HY3_SCENARIO_SHAS} | {
        "analyst_result", "analyst_blocks",
        # sibling units' gated additions, merged the same day (U-sdkr's
        # reader_write, U-sdkw's ok_write_real) -- sanctioned, not ours
        "reader_write", "ok_write_real",
        # U-cleanup-A's own addition: the bash-shim-script interpreter
        # (`_scenario_shim_script`) backing the migrated
        # `sdk_fake_worker`/`sdk_fake_analyst` fixtures --
        # not sha-pinned above since it has no base-commit body to pin.
        "shim_script",
    }
    assert set(fake_mod.SCENARIOS) == expected_keys

    for banned in ("subprocess", "socket", "urllib", "http"):
        assert f"import {banned}" not in text


def test_hy5_numstat_bounds_hold():
    # Bounds reconciled 2026-08-25 for U-cleanup-A's BLOCKER-1 fold (code
    # gate r1, 8uvjHmdKaUd6PI3tSyB-F): this test used to run the TWO-ref
    # form (`{_BASE_SHA}..HEAD`) FIRST and only fall back to the
    # single-ref (base-vs-WORKING-TREE) form when that output was empty
    # -- which it never was, for any file any unit had ever touched, so
    # the fallback never fired and the armor was blind to every
    # uncommitted build in this unit's own history, going red only once
    # a build committed. `test_ar1`'s sibling armor (`D-27`) already uses
    # the single-ref form EXCLUSIVELY for exactly this reason -- base vs
    # WORKING TREE, never `..HEAD` -- and it is strictly more correct: a
    # clean working tree measures identically to `..HEAD` (HEAD's blob
    # IS the working tree's blob), so there is no case the two-ref form
    # caught that the single-ref form misses. Reconciled to this unit's
    # OWN measured single-ref numstat for the four files it actually
    # touches (conftest.py, fake_claude.py, test_invocation.py,
    # test_invocation_sdk.py) -- tight on purpose (c0a49a9 precedent).
    # The other five rows are untouched by this unit; their existing
    # (looser) bounds still hold under the single-ref form and are left
    # as-is.
    # U-cleanup-B RECONCILE (2026-08-25): every row below widened to this
    # unit's own measured single-ref numstat -- §8.1's deletion inventory
    # (CliBackend, argv builders, settings writers, the CL9 SessionSpec
    # rebase) touches every one of these 9 files. `provider.py` and
    # `test_doctor_invocation.py` were untouched by U-sdka/U-flip/
    # U-cleanup-A but are now touched by MAJOR-5's fold-consistency fix
    # (`_rollout_rows`/`_credentials_row`/`_models_rows`/`session_env`/
    # `resolve`) plus the test-side `_read_argv_flag`/`SessionSpec`
    # rebase; `provider.py` gets its first-ever bounds row here.
    # U-cleanup-B follow-on re-measure (§8.3, R-1): `test_invocation.py`
    # widened again for the `_ANALYST_CLAUDE_SHIM` dead-constant deletion
    # plus the `claude_shim` -> `sdk_fake_worker` rename (8
    # sites, `test_repair.py`'s compat-alias deletion's one consumer).
    # Widened AGAIN (§11.1): four new tests -- `T-CLI-REFUSED-ENV/ALL-
    # SURFACES/COARSE/CONFIG` (SEL1-4) -- landed in `test_invocation.py`.
    # Widened a further time (§11.1, T-DOCTOR-SWITCHES/SEL6):
    # `test_dc17_switches_row_reports_cli_selection_as_refused` landed in
    # `test_doctor_invocation.py` (50, 6) -> (91, 6); registered in
    # `_AR3_ADDED["test_doctor_invocation.py"]` above.
    # Widened YET AGAIN (§11.1, T-DOCTRINE-REACHES-SDK/M-5):
    # `test_m5_doctrine_reaches_sdk_system_prompt_from_the_real_call_site`
    # (+ its `backend_mod` import) landed in `test_invocation.py`
    # (697, 700) -> (718, 700); registered in
    # `_AR3_ADDED["test_invocation.py"]` above.
    # `src/self_learn/provider.py` widened (82, 28) -> (108, 36): FIVE
    # detail strings across `_rollout_rows` (x2), `_models_rows`,
    # `_env_rows`, and the handoff-block `env-keys.<surface>` builder
    # still said "backend=cli" for a value that can no longer be
    # literally true post-collapse (`backends[s]`/`res.backend` are
    # unconditionally "sdk"); corrected to the SEL6 pattern ("REFUSED
    # (cli retired)") already used by the switches row -- extends the
    # same MAJOR-5 fix this unit's own exception already covers 6 other
    # `provider.py` call sites for (11 total now). `test_doctor_
    # invocation.py` widened alongside it (91, 6) -> (100, 9): test_dc6's
    # and test_dc12's assertions re-spelled to match.
    # U-engine Phase 2 (spec Sec 5.6/7.2, `SUP2`/`SUP4`): `provider.py`
    # widened (108, 36) -> (185, 36) -- the new `_serve_row` function
    # (the `doctor` row for the `self-learn serve` heartbeat/staleness
    # alarm) plus its `DOCTOR_ROWS`/`preflight` call-site additions,
    # measured single-ref against _BASE_SHA. Widened again (185, 36) ->
    # (196, 36) -- gate r2 N-6': the corrupt-vs-absent heartbeat
    # distinction added to `_serve_row`'s configured-no-heartbeat leg.
    # U-papercuts P-2 (2026-08-27): `test_doctor_invocation.py` widened
    # (100, 9) -> (156, 9) -- the two `test_p2_*` functions registered in
    # `_AR3_ADDED["test_doctor_invocation.py"]` above (bare `doctor`
    # defaults to `doctor invocation`; `doctor bogus` still a usage
    # error). `cli.py` itself (the actual fix, `_build_parser`'s doctor
    # block) is not a row in this table -- it was never touched by any
    # prior unit this armor tracks. Widened again, (156, 9) -> (165, 9)
    # -- code gate r1 N-2 fix: `doctor_sub`'s `metavar` changed
    # `"<verb>"` -> `"[<verb>]"` (cli.py, not tracked here either) plus
    # the provenance note this added to `test_p2_doctor_unknown_verb_
    # still_a_usage_error`'s docstring.
    # U-servehermetic (2026-08-27): `conftest.py` widened (34, 0) ->
    # (44, 0) -- the ten-line `XDG_CONFIG_HOME` hermetic-default addition
    # to `_worker_test_defaults` (see `_AR1_SANCTIONED_PIN_LINES` above,
    # same unit). No other row in this table is touched by this unit.
    # U-kl4 (2026-08-28): `test_invocation_sdk.py` widened (298, 149) ->
    # (414, 166) -- `test_kl4_...`'s pgrep-based liveness check (host-
    # global, measured false-red under concurrent suites) rebuilt to key
    # on the pid this run's own child actually got, plus its positive
    # control (`test_kl4a_...`) and the two shared identity-check
    # helpers (`_proc_start_ticks`/`_child_gone`). Measured single-ref
    # against `_BASE_SHA`, required (not a discretionary widening): the
    # unedited bound already sat at exactly 298/149, one insertion below
    # the true content this build needs.
    # U-kl4 gate r1 fold (2026-08-28): widened AGAIN, (414, 166) ->
    # (493, 166) -- B-1 (`test_kl4a_...`'s `try` rescoped to capture
    # `pid` FIRST so every assertion's cleanup runs, plus a new
    # `_reap_best_effort` waitpid helper), N/D-3 (re-check start-ticks
    # immediately before the `SIGKILL`, not just once at capture time),
    # N/D-1 (one sentence on `NOTE-14` about the PID-reuse guard's
    # failure mode), and N/D-2 (a new committed test, `test_kl4b_...`,
    # asserting `child_pid is None` on the `not-found` path). Measured
    # single-ref against `_BASE_SHA`, required: the prior bound (414,
    # 166) undercounted this fold's real insertions by 79.
    bounds = {
        "plugins/self-learn/cli/src/self_learn/invocation/contract.py": (31, 47),
        "plugins/self-learn/cli/src/self_learn/invocation/registry.py": (34, 20),
        "plugins/self-learn/cli/src/self_learn/provider.py": (196, 36),
        "plugins/self-learn/cli/src/self_learn/analyst.py": (4, 18),
        "plugins/self-learn/cli/tests/conftest.py": (44, 0),  # U-servehermetic: XDG_CONFIG_HOME hermetic default added
        "plugins/self-learn/cli/tests/fixtures/fake_claude.py": (388, 1),
        "plugins/self-learn/cli/tests/test_invocation.py": (737, 760),  # FW-117 (2026-08-28): HY3 trimmed to two witnesses, SETTINGS_WITNESS/test_cn6/test_cn7_repair_leg deleted, then gate r1 fold (test_cn9 docstring truth) -- widened (718, 700) -> (730, 757) -> (737, 760), EXACT measured value (not a margin), single-ref against _BASE_SHA
        "plugins/self-learn/cli/tests/test_invocation_sdk.py": (493, 166),  # U-kl4 gate r1 fold (2026-08-28): B-1 (try scoped to capture pid first + best-effort reap), N/D-2 (new test_kl4b), N/D-3 (re-check start-ticks immediately before the kill), N/D-1 (NOTE-14 sentence); was (298, 149) -> (414, 166) -> (493, 166), measured single-ref against _BASE_SHA
        "plugins/self-learn/cli/tests/test_doctor_invocation.py": (165, 9),
    }
    for relpath, (max_ins, max_del) in bounds.items():
        out = subprocess.run(
            ["git", "diff", "--numstat", f"{_BASE_SHA}", "--", relpath],
            cwd=_REPO_ROOT, capture_output=True, text=True,
        ).stdout.strip()
        # code gate r1 NIT-8: fail-open by construction -- a row whose
        # file turns out UNTOUCHED (empty numstat output) SKIPS its
        # bound check entirely rather than failing it. That is correct
        # for a file this build never claimed to touch, but it means a
        # row wrongly believed touched, that in fact reverted to base
        # (numstat empty), would silently pass here rather than flag
        # the missing change. All 9 rows in `bounds` measure nonzero in
        # this build (verified: every row fires, none skips) -- the gap
        # is theoretical today, recorded so it is not mistaken for
        # coverage it does not have.
        if not out:
            continue
        ins_s, del_s, _ = out.split("\t")
        ins, dele = int(ins_s), int(del_s)
        if relpath.endswith("fake_claude.py"):
            ins -= 2  # the two SCENARIOS dict lines are excluded from the cap
        assert ins <= max_ins, (relpath, "insertions", ins, max_ins)
        assert dele <= max_del, (relpath, "deletions", dele, max_del)
