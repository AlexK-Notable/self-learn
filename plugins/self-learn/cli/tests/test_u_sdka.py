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

#: U-armor DELETE (build note): the general-purpose `_BASE_SHA` this
#: file used to carry for AR1/AR3/HY5's byte-identity checks against a
#: historical base commit is retired along with those mechanisms
#: (`test_armor.py`'s anchor-side node census now covers that ground).
#: `test_su4_armor_21_is_byte_identical_and_disjoint_from_edited` (below)
#: is a SEPARATE, un-retired pin -- not named in the armor spec's
#: section 13 list -- so it keeps its own narrowly-scoped constant,
#: same literal value (`442385d`, the merge train re-anchor point,
#: 2026-08-19), so its behaviour is byte-for-byte unchanged.
_SU4_ARMOR_21_BASE_SHA = "442385d"

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
        base_funcs = _top_level_funcs(_source_at(_SU4_ARMOR_21_BASE_SHA, full))
        now_text = (Path(__file__).parent / relpath).read_text(encoding="utf-8")
        now_funcs = _top_level_funcs(now_text)
        base_text = _source_at(_SU4_ARMOR_21_BASE_SHA, full)
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
    """FL4: "sdk" is a DATA VALUE reached through the shared cascade,
    never a surface-keyed branch. Fold r1 (MAJOR-1/MAJOR-4) MOVED the
    default-rung table lookup out of `backend_for` into
    `resolve_backend_raw`'s own default rung -- `backend_for` now ends
    `return _resolve(...)`, fed by that function's result. The pin
    follows the seam: it now checks both functions."""
    src = inspect.getsource(registry_mod)
    tree = ast.parse(src)

    def get_fn(name):
        return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)

    backend_for_node = get_fn("backend_for")
    raw_node = get_fn("resolve_backend_raw")

    def str_literals(node):
        return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    # (a) `backend_for`: no surface-name literal, no "sdk" literal
    # anywhere -- it now branches on SOURCE LABEL only, never on VALUE.
    bf_literals = str_literals(backend_for_node)
    assert not (bf_literals & set(SURFACES))
    assert "sdk" not in bf_literals

    # (c) its FINAL statement calls `_resolve`, fed by `resolve_backend_
    # raw`'s own `(raw_value, source)` result -- the data reaches it
    # through the cascade, never a branch computing a fresh value.
    final = backend_for_node.body[-1]
    assert isinstance(final, ast.Return) and isinstance(final.value, ast.Call)
    assert isinstance(final.value.func, ast.Name) and final.value.func.id == "_resolve"
    assert {a.id for a in final.value.args if isinstance(a, ast.Name)} == {"surface", "raw_value"}

    # (b) `resolve_backend_raw`: the table lookup is the FIRST of three
    # returns (nested in `if found is None:`), not the function's last
    # statement -- located structurally, by its own AST dump naming
    # `DEFAULT_BACKEND_FOR_SURFACE`, rather than by position. "sdk" (the
    # table's fallback default) lives ONLY there; no other literal in
    # the function is "sdk" or a surface name.
    default_returns = [
        n for n in ast.walk(raw_node) if isinstance(n, ast.Return) and "DEFAULT_BACKEND_FOR_SURFACE" in ast.dump(n)
    ]
    assert len(default_returns) == 1
    inside_ids = {id(n) for n in ast.walk(default_returns[0])}
    outside_literals = {
        n.value
        for n in ast.walk(raw_node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in inside_ids
    }
    assert "sdk" not in outside_literals
    assert not (outside_literals & set(SURFACES))


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
    immune_modules = {
        "test_doctor_invocation.py",  # autouse _clear_provider_env
        "test_provider.py",  # autouse _clear_provider_env
        "test_settings_fold_r1.py",  # autouse _clear_registry_env
    }
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


