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
import stat
import subprocess
import sys
from pathlib import Path

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

from shims import write_analyst_claude_shim
from support import git, make_behavior, make_env

from test_invocation import _clear_backend_env, _clear_config, _write_config
from test_invocation import miner_capture  # noqa: F401 -- fixture resolved by name
from test_invocation_sdk import sdk_absent  # noqa: F401 -- fixture resolved by name
from test_repair import _defect_script, _t4_missing_target, _t4_target_fixed
from test_worker import claude_cli_shim_worker, env, seed_pending  # noqa: F401 -- fixtures resolved by name (NOT the "claude_shim" legacy alias -- FX4 permits exactly one importer, test_invocation.py)

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
_BASE_SHA = "89f8ef7"

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"

#: the GENUINE, never-patched `subprocess.run`, captured at import time --
#: `_Leg.fail("os-error")`'s patch is layered via the shared per-test
#: `monkeypatch`, so a caller that wants a NORMAL route after an
#: `os-error` leg (`H-e`'s negative control) must restore this
#: explicitly, never via `monkeypatch.undo()` (would also revert `leg`'s
#: own env setup -- the BLOCKER-1 shape).
_REAL_SUBPROCESS_RUN = subprocess.run
LEGS = ("cli", "sdk")


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
_ARMOR_21_BY_FILE: dict[str, tuple[str, ...]] = {
    "test_invocation.py": (
        "test_cn2_call_site_containment_matches_the_call_site_table",
        "test_cn10_argv_is_the_third_witness_iff_both_directions",
        "test_av1_argv_equals_surfaces_own_builder_output_recomputed",
        "test_av4_prompt_membership_on_real_invocations",
        "test_lg7_analyst_invocation_never_grows_worker_or_miner_log",
        "test_wr5_analyst_error_carries_cause_for_not_found_and_timeout",
    ),
    "test_composer.py": (
        "test_a23_roster_sha_honesty_both_legs_both_paths",
        "test_a24_containment_and_derivation_at_owned_sites",
    ),
    "test_regime_fixes.py": ("test_analyst_timeout_captures_to_pending",),
    "test_route_cli.py": (
        "test_teach_route_analyst_routes_to_shim_destination",
        "test_teach_route_bare_analyst_path_records_by_analyst",
        "test_teach_route_analyst_failure_captures_to_pending",
        "test_analyst_analyze_round_trips_unknown_fields",
        "test_analyst_analyze_hook_round_trips",
        "test_analyst_analyze_cli_owned_fields_win",
        "test_analyst_analyze_strips_script_unconditionally",
        "test_analyst_analyze_runs_in_ledger_home",
    ),
}

#: `A-f` -- the eight `EDITED` functions, BY THEIR CURRENT (post-build)
#: names, so `SU4`'s disjointness leg and `AR3`'s own scan share one list.
_EDITED_CURRENT_NAMES = {
    "test_invocation.py": (
        "test_rg1_five_rung_precedence_resolves_in_isolation",
        "test_tr4_bare_os_error_is_caught_on_analyst_worker_and_miner",
        "test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_through_log_templates",
    ),
    "test_invocation_sdk.py": (
        "test_ou1_every_row_of_the_map_1_table",
        "test_ou5_bare_oserror_caught_on_worker_miner_and_analyst",
        "test_rs2_present_returns_sdkbackend_for_every_surface",
    ),
    "test_doctor_invocation.py": (
        "test_dc2_switches_names_all_surfaces_and_changes_with_rung",
        "test_dc3_rollout_four_states",
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


def test_fl1_default_rung_resolves_sdk_for_analyst_cli_for_the_rest(tmp_path, monkeypatch, sdk_absent):
    # `FL1` -- the PRODUCT default, env cleared entirely (no conftest pin
    # survives a nested delenv), no config.yaml.
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

    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for("analyst", home=home)
    for surface in ("worker", "worker-repair", "miner-reader"):
        assert isinstance(invocation.backend_for(surface, home=home), invocation.CliBackend)

    assert isinstance(invocation.backend_for("nope", home=home), invocation.CliBackend)


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


def test_fl2_each_rung_shadows_the_table_both_directions(tmp_path, monkeypatch, sdk_absent):
    home = tmp_path / "fl2-home"
    home.mkdir()

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "cli")
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)

    _clear_backend_env(monkeypatch)
    _write_config(home, {"backend_analyst": "cli"})
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)
    _clear_config(home)

    _write_config(home, {"backend": "cli"})
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)
    _clear_config(home)

    # the inverse, for the three cli-default surfaces: the table is not a
    # ceiling.
    for surface in ("worker", "worker-repair", "miner-reader"):
        selector = invocation.SELECTOR_FOR_SURFACE[surface]

        _clear_backend_env(monkeypatch)
        monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "sdk")
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)

        _clear_backend_env(monkeypatch)
        monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)

        _clear_backend_env(monkeypatch)
        _write_config(home, {f"backend_{surface}": "sdk"})
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)
        _clear_config(home)

        _write_config(home, {"backend": "sdk"})
        with pytest.raises(invocation.BackendUnavailable):
            invocation.backend_for(surface, home=home)
        _clear_config(home)


def test_fl3_fail_closed_survives_the_table(tmp_path, monkeypatch, capsys):
    home = tmp_path / "fl3-home"
    home.mkdir()

    # (i) an unknown value at each configurable rung, on the ANALYST --
    # the fallback is now a DOWNGRADE from the sdk default, not a no-op.
    _clear_backend_env(monkeypatch)
    _clear_config(home)
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "bogus")
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        "self-learn: unknown invocation backend 'bogus' in SELF_LEARN_BACKEND_ANALYST"
        ' — using "cli"\n'
    )

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "bogus")
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        "self-learn: unknown invocation backend 'bogus' in SELF_LEARN_BACKEND" ' — using "cli"\n'
    )

    _clear_backend_env(monkeypatch)
    _write_config(home, {"backend_analyst": "bogus"})
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        "self-learn: config.yaml ignored — invocation.backend_analyst must be "
        "one of cli, sdk; got 'bogus' — using \"cli\"\n"
    )
    _clear_config(home)

    _write_config(home, {"backend": "bogus"})
    assert isinstance(invocation.backend_for("analyst", home=home), invocation.CliBackend)
    assert capsys.readouterr().err == (
        "self-learn: config.yaml ignored — invocation.backend must be "
        "one of cli, sdk; got 'bogus' — using \"cli\"\n"
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
    assert "sdk" not in literals
    assert "analyst" not in literals

    final = backend_for_node.body[-1]
    assert isinstance(final, ast.Return)
    dumped = ast.dump(final)
    assert "DEFAULT_BACKEND_FOR_SURFACE" in dumped


def test_fl5_the_two_transcriptions_agree_over_the_full_matrix(tmp_path, monkeypatch, sdk_absent):
    from self_learn.invocation.cli import CliBackend

    def _expected(surface, home):
        try:
            backend = invocation.backend_for(surface, home=home)
        except invocation.BackendUnavailable:
            return "sdk"
        return "cli" if isinstance(backend, CliBackend) else "sdk"

    for surface in SURFACES:
        selector = invocation.SELECTOR_FOR_SURFACE[surface]
        home = tmp_path / f"fl5-{surface}"
        home.mkdir()

        for setup, teardown in (
            (lambda: monkeypatch.setenv(f"SELF_LEARN_BACKEND_{selector}", "sdk"),
             lambda: monkeypatch.delenv(f"SELF_LEARN_BACKEND_{selector}")),
            (lambda: monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk"),
             lambda: monkeypatch.delenv("SELF_LEARN_BACKEND")),
        ):
            _clear_backend_env(monkeypatch)
            setup()
            derived, _ = provider.resolve_backend_name(home, surface)
            assert derived == _expected(surface, home), (surface, "env")
            teardown()

        _clear_backend_env(monkeypatch)
        _write_config(home, {f"backend_{surface}": "sdk"})
        derived, _ = provider.resolve_backend_name(home, surface)
        assert derived == _expected(surface, home), (surface, "config-surface")
        _clear_config(home)

        _write_config(home, {"backend": "sdk"})
        derived, _ = provider.resolve_backend_name(home, surface)
        assert derived == _expected(surface, home), (surface, "config-general")
        _clear_config(home)

        # the default rung -- the cell `M1`/`M5` guard.
        derived, source = provider.resolve_backend_name(home, surface)
        assert derived == _expected(surface, home), (surface, "default")
        assert source == "default"

    # `test_provider.py::test_bk1_agrees_with_registry_over_matrix` passing
    # UNEDITED is verified at full-suite level (SU1), not re-imported here
    # -- importing it while `sdk_absent` is active would poison its own
    # module-level `from claude_agent_sdk import ...`.


def test_fl6_worker_untouched(env, claude_cli_shim_worker, monkeypatch):
    # A REAL worker.run() reaching the repair round (test_invocation.py's
    # `repair_run` fixture, rebuilt HERE rather than imported -- it
    # requires a fixture literally named `claude_shim`, and U-fake's `FX4`
    # legacy-alias guard permits exactly one importer of that name,
    # test_invocation.py) -- no backend env set at all.
    from self_learn import worker

    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid)))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid)))
    worker.run(env.home)
    assert claude_cli_shim_worker["count"]() == 2  # batch + repair round both spawned the shim
    for surface in ("worker", "worker-repair"):
        assert provider.resolve_backend_name(env.home, surface)[0] == "cli"


def test_fl6b_miner_untouched(miner_capture):
    # Kept in its OWN test (not combined with `test_fl6_worker_untouched`
    # above): both `env` and `miner_capture` independently overwrite
    # `SELF_LEARN_HOME` via `monkeypatch.setenv` -- composed in one test,
    # `miner_capture`'s fixture setup (which also runs the miner reader
    # invocation) races the worker/repair setup for that ambient var.
    assert miner_capture["argv"] != []
    assert provider.resolve_backend_name(miner_capture["home"], "miner-reader")[0] == "cli"


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
        cli_argv_builder=lambda _s: ["claude", "-p", "p"],
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


def _path_without_claude() -> str:
    """Every PATH directory that does NOT resolve an executable `claude`
    -- unlike nuking PATH wholesale, `git` (and everything else) stays
    reachable, so `teach --route`'s own git calls keep working."""
    parts = os.environ.get("PATH", "").split(os.pathsep)
    safe = [p for p in parts if not (Path(p) / "claude").is_file()]
    return os.pathsep.join(safe)


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

    def __init__(self, name, env, monkeypatch, tmp_path, *, out_path, argv_path, cwd_path=None, shim_dir=None):
        self.name = name
        self.env = env
        self.home = env.ledger
        self._mp = monkeypatch
        self._tmp_path = tmp_path
        self._out_path = out_path
        self._argv_path = argv_path
        self._cwd_path = cwd_path
        self._shim_dir = shim_dir
        self._base_path = os.environ["PATH"]  # pristine, pre-any-`.fail()` PATH

    def restore(self) -> None:
        """Undo every `.fail()`-installed sabotage, WITHOUT ever touching
        the shared `monkeypatch` fixture's OTHER patches
        (`monkeypatch.undo()` would also revert this handle's own
        SELF_LEARN_SDK_CLI_PATH/PATH setup -- the BLOCKER-1 shape)."""
        self._mp.setattr(subprocess, "run", _REAL_SUBPROCESS_RUN)
        self._mp.delenv("SELF_LEARN_ANALYST_TIMEOUT", raising=False)
        if self.name == "cli":
            self._mp.delenv("CLAUDE_SHIM_EXIT", raising=False)
            if self._shim_dir is not None:
                self._mp.setenv("PATH", f"{self._shim_dir}{os.pathsep}{self._base_path}")
        else:
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
        """`H-d`'s table, mechanized. `not-found` on the cli leg filters
        PATH to drop only directories that actually resolve a `claude`
        binary (never the whole PATH -- that breaks `git`, which
        `teach --route` also shells out to) -- the shipped decoy/tripwire
        sweep must never let this leg resolve a REAL `claude` sitting
        elsewhere on PATH. `os-error` patches `subprocess.run`
        SELECTIVELY (`claude` argv only) so the rest of `teach --route`'s
        own `git` calls are untouched."""
        mp = self._mp
        if self.name == "cli":
            if kind == "exit":
                mp.setenv("CLAUDE_SHIM_EXIT", "1")
            elif kind == "timeout":
                sleep_dir = self._tmp_path / "leg-cli-sleep-shim"
                sleep_dir.mkdir(exist_ok=True)
                shim = sleep_dir / "claude"
                shim.write_text("#!/usr/bin/env bash\nsleep 30\n", encoding="utf-8")
                shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
                mp.setenv("PATH", f"{sleep_dir}{os.pathsep}{os.environ['PATH']}")
                mp.setenv("SELF_LEARN_ANALYST_TIMEOUT", "0.3")
            elif kind == "not-found":
                mp.setenv("PATH", _path_without_claude())
            elif kind == "os-error":
                real_run = subprocess.run

                def _raise(argv, *a, **kw):
                    if argv and Path(str(argv[0])).name == "claude":
                        raise PermissionError("permission denied")
                    return real_run(argv, *a, **kw)

                mp.setattr(subprocess, "run", _raise)
            else:
                raise AssertionError(f"{kind!r}: not reachable on the cli leg (H-e)")
        else:
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


@pytest.fixture(params=LEGS)
def leg(request, tmp_path, monkeypatch):
    name = request.param
    sandbox_root = tmp_path / f"leg-{name}-sandbox"
    sandbox_root.mkdir()
    env = make_env(sandbox_root)
    _bootstrap_remotes(env)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))

    out = tmp_path / f"leg-{name}-out.txt"
    out.write_text("", encoding="utf-8")
    argv_log = tmp_path / f"leg-{name}-argv.log"

    if name == "cli":
        # `H-a` -- calls `write_analyst_claude_shim` directly (a plain
        # function, `U-fake` `D-8`/`SH4`): a `params=` fixture body
        # cannot itself request another fixture.
        monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
        shim_dir = tmp_path / "leg-cli-shim-bin"
        shim_dir.mkdir()
        write_analyst_claude_shim(shim_dir)
        cwd_log = tmp_path / "leg-cli-cwd.log"
        monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("CLAUDE_SHIM_LOG", str(argv_log))
        monkeypatch.setenv("CLAUDE_SHIM_CWD", str(cwd_log))
        monkeypatch.setenv("CLAUDE_SHIM_OUT", str(out))
        handle = _Leg(
            name, env, monkeypatch, tmp_path,
            out_path=out, argv_path=argv_log, cwd_path=cwd_log, shim_dir=shim_dir,
        )
    else:
        # `H-b`
        monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
        monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
        monkeypatch.setenv("FAKE_CLAUDE_OUT", str(out))
        monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "analyst_result")
        handle = _Leg(name, env, monkeypatch, tmp_path, out_path=out, argv_path=argv_log)
    return handle


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
        if leg.name == "cli":
            assert str(exc) == "analyst invocation failed (permission denied)"
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
    assert contract_mod.TRANSPORT["analyst"].catches_os_error is True
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
            cli_argv_builder=lambda _s: ["claude", "-p", "p"],
        )
        try:
            outcome = invocation.text_session(spec)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{kind}: raised {type(exc).__name__} instead of returning an Outcome: {exc}")
        assert outcome.failure == kind, kind


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
        cli_argv_builder=lambda _s: ["claude", "-p", "ok_write"],
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
        cli_argv_builder=lambda _s: ["claude", "-p", "p"],
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
        cli_argv_builder=lambda _s: analyst.build_argv(prompt, "DOCTRINE", "claude-sonnet-5"),
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
    assert not any(prompt in a for a in child_argv)

    # the negative control: on the cli leg the SAME assertion FAILS.
    shim_dir = tmp_path / "hd7-cli-shim"
    shim_dir.mkdir()
    write_analyst_claude_shim(shim_dir)
    cli_out = tmp_path / "hd7-cli-out.txt"
    cli_out.write_text("ok", encoding="utf-8")
    cli_argv_log = tmp_path / "hd7-cli-argv.log"
    cli_cwd_log = tmp_path / "hd7-cli-cwd.log"
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLAUDE_SHIM_LOG", str(cli_argv_log))
    monkeypatch.setenv("CLAUDE_SHIM_CWD", str(cli_cwd_log))
    monkeypatch.setenv("CLAUDE_SHIM_OUT", str(cli_out))
    from self_learn.invocation.cli import CliBackend

    CliBackend().text_session(spec)
    cli_child_argv = cli_argv_log.read_text(encoding="utf-8").split("\0")[:-1]
    assert any(prompt in a for a in cli_child_argv)  # AV4's shipped positive statement, restated


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
#: leg is fixed to compare base-vs-WORKING-TREE. These are the exact nine
#: `+` line bodies (leading `+` stripped) `Armor-1`'s pin is sanctioned
#: to add to `conftest.py` -- any interior tripwire edit adds a tenth `+`
#: line, or a `-` line, regardless of what text it contains.
_AR1_SANCTIONED_PIN_LINES = [
    "    # U-sdka `Armor-1`: the analyst's SHIPPED default backend is now",
    "    # `sdk` (invocation/contract.py `DEFAULT_BACKEND_FOR_SURFACE`). Every",
    "    # pre-existing analyst test drives a bash PATH shim or a patched",
    "    # `subprocess.run`, i.e. the cli transport, and names no backend --",
    "    # same convention as SELF_LEARN_WORKER_AUTOKICK and",
    "    # SELF_LEARN_NO_NOTIFY above: the suite opts OUT of real machinery by",
    "    # default and a test that wants it opts back IN. `test_u_sdka.py`'s",
    "    # FL1 asserts the PRODUCT default directly, with this var cleared.",
    '    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")',
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


def test_ar2_suite_wide_pin_is_a_default_not_the_thing_under_test():
    src = inspect.getsource(sys.modules["conftest"]._worker_test_defaults)
    assert 'monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")' in src

    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("SELF_LEARN_BACKEND_ANALYST", raising=False)
        backend = invocation.backend_for("analyst", home=Path("/nonexistent-ar2-home"))
        assert type(backend) is SdkBackend


_AR3_REASONS = {
    ("test_invocation.py", "test_rg1_five_rung_precedence_resolves_in_isolation"): "flip (A-c)",
    ("test_invocation.py", "test_tr4_bare_os_error_is_caught_on_analyst_worker_and_miner"): "FW-87 (E-f)",
    ("test_invocation.py", "test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_through_log_templates"): "pin casualty (A-d)",
    ("test_invocation_sdk.py", "test_ou1_every_row_of_the_map_1_table"): "FW-87 (E-f)",
    ("test_invocation_sdk.py", "test_ou5_bare_oserror_caught_on_worker_miner_and_analyst"): "FW-87 (E-f)",
    ("test_invocation_sdk.py", "test_rs2_present_returns_sdkbackend_for_every_surface"): "Pin-1 casualty (A-e)",
    ("test_doctor_invocation.py", "test_dc2_switches_names_all_surfaces_and_changes_with_rung"): "flip (A-c)",
    ("test_doctor_invocation.py", "test_dc3_rollout_four_states"): "flip (A-c)",
}

_AR3_RENAMED = {
    "test_invocation.py": {
        "test_tr4_bare_os_error_escapes_analyst_but_not_worker_or_miner": "test_tr4_bare_os_error_is_caught_on_analyst_worker_and_miner",
    },
    "test_invocation_sdk.py": {
        "test_ou5_bare_oserror_escapes_worker_miner_caught_analyst_reraised": "test_ou5_bare_oserror_caught_on_worker_miner_and_analyst",
    },
    "test_doctor_invocation.py": {},
}

_AR3_ONE_LINE_ONLY = {
    "test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_through_log_templates",
    "test_rs2_present_returns_sdkbackend_for_every_surface",
}


def test_ar3_edited_is_exactly_eight_functions_with_reasons():
    touched: set[tuple[str, str]] = set()
    for relpath in ("test_invocation.py", "test_invocation_sdk.py", "test_doctor_invocation.py"):
        full = f"plugins/self-learn/cli/tests/{relpath}"
        base_text = _source_at(_BASE_SHA, full)
        base_funcs = _top_level_funcs(base_text)
        now_text = (Path(__file__).parent / relpath).read_text(encoding="utf-8")
        now_funcs = _top_level_funcs(now_text)

        renamed = _AR3_RENAMED[relpath]
        base_only = set(base_funcs) - set(now_funcs)
        now_only = set(now_funcs) - set(base_funcs)
        assert base_only == set(renamed), (relpath, "removed", base_only)
        assert now_only == set(renamed.values()), (relpath, "added", now_only)

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
    every test setting `SELF_LEARN_BACKEND=sdk` (rung 2) that reaches the
    analyst surface or iterates `SURFACES`, without first clearing
    `SELF_LEARN_BACKEND_ANALYST` -- directly, or via an autouse fixture in
    its module. This census recognizes exactly the two SYSTEMIC
    protections Pin-1 itself names (`_clear_backend_env(`'s convention, or
    an autouse module fixture) -- a same-function, one-off inline
    `delenv` (`test_rs2`'s own `A-e` fix) is deliberately NOT credited: it
    is what makes `test_rs2` the census's stable, tracked member rather
    than a moving target that vanishes the moment it grows its own fix."""
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
            reaches_analyst = (
                '"analyst"' in src or "'analyst'" in src or "SURFACES" in src
            )
            if not reaches_analyst:
                continue
            if "_clear_backend_env(" in src:
                continue
            casualties.add(node.name)

    assert casualties == {"test_rs2_present_returns_sdkbackend_for_every_surface"}


def test_ar4_byte_identity_under_the_rollback(tmp_path, monkeypatch, sdk_absent):
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    env = make_env(tmp_path / "ar4-sandbox")
    shim_dir = tmp_path / "ar4-shim"
    shim_dir.mkdir()
    write_analyst_claude_shim(shim_dir)
    out = tmp_path / "ar4-out.txt"
    argv_log = tmp_path / "ar4-argv.log"
    cwd_log = tmp_path / "ar4-cwd.log"
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLAUDE_SHIM_LOG", str(argv_log))
    monkeypatch.setenv("CLAUDE_SHIM_CWD", str(cwd_log))
    monkeypatch.setenv("CLAUDE_SHIM_OUT", str(out))

    out.write_text(_skill_proposal_text(env.ledger), encoding="utf-8")
    analyst.analyze(env.ledger, make_behavior())
    argv = argv_log.read_text(encoding="utf-8").split("\0")[:-1]
    # `build_argv` RECOMPUTED here, element for element -- `doctrine_text`
    # read independently (not extracted from argv), the one non-trivial
    # value this check can actually falsify.
    prompt = argv[argv.index("-p") + 1]
    model = argv[argv.index("--model") + 1]
    doctrine_text = analyst.doctrine_path().read_text(encoding="utf-8")
    # `build_argv` returns the FULL argv (leading "claude"); the bash shim
    # only records "$@" -- its OWN positional args, i.e. everything AFTER
    # the program name -- so the recorded log starts at "-p".
    expected = analyst.build_argv(prompt, doctrine_text, model)
    assert argv == expected[1:]
    assert argv[argv.index("--append-system-prompt") + 1] == doctrine_text
    assert model == analyst.DEFAULT_ANALYST_MODEL
    assert cwd_log.read_text(encoding="utf-8").strip() == str(Path(env.ledger).resolve())
    assert analyst._timeout() == analyst.DEFAULT_ANALYST_TIMEOUT

    # `AnalystError` messages, byte-identical to base -- not-found /
    # timeout / exit / unavailable. `os-error` is EXCLUDED (FW-87 is
    # this unit's one sanctioned cli-leg behavior change).
    def _raise_notfound(*_a, **_kw):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", _raise_notfound)
    with pytest.raises(analyst.AnalystError) as e1:
        analyst.analyze(env.ledger, make_behavior())
    assert str(e1.value) == "claude CLI not found on PATH"

    def _raise_timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=120)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    with pytest.raises(analyst.AnalystError) as e2:
        analyst.analyze(env.ledger, make_behavior())
    assert str(e2.value) == "analyst timed out after 120s"

    class _ExitProc:
        returncode = 7
        stdout = "OUT"
        stderr = "  ERR TEXT  "

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: _ExitProc())
    with pytest.raises(analyst.AnalystError) as e3:
        analyst.analyze(env.ledger, make_behavior())
    assert str(e3.value) == "analyst exited 7: ERR TEXT"

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    with pytest.raises(analyst.AnalystError) as e4:
        analyst.analyze(env.ledger, make_behavior())
    assert str(e4.value) == (
        'invocation backend unavailable (the "sdk" invocation backend is not '
        "built yet — install it with:\n"
        "    pip install 'self-learn-cli[sdk]')"
    )


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
    assert "worker: backend=cli (default)" in switches.detail

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


def test_dr3_wholly_inert_state_is_constructed_by_the_pin(tmp_path, monkeypatch):
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

    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
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
#: to their base-commit bytes.
_HY3_SCENARIO_SHAS = {
    "_scenario_ok_text": "62c5de5ba8d4870df7ad9c657bb78e6aeb41215f2dfa67357b3654fa2399bd7c",
    "_scenario_ok_blocks_only": "55a2ab044a4892756072a85141c5eed59f59fedf0daae6ceeb2243a4f2cd1050",
    "_scenario_ok_write": "1adacd1464e3556f1e55ee735c06fc8b1bef8096843e377d70a239b7f3c3c6c2",
    "_scenario_error_result": "c4dba03081c5521d7d2dad8ec1c50c738a7831a78f9cf650815d080f74d9cddb",
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
    }
    assert set(fake_mod.SCENARIOS) == expected_keys

    for banned in ("subprocess", "socket", "urllib", "http"):
        assert f"import {banned}" not in text


def test_hy5_numstat_bounds_hold():
    bounds = {
        "plugins/self-learn/cli/src/self_learn/invocation/contract.py": (16, 3),
        "plugins/self-learn/cli/src/self_learn/invocation/registry.py": (8, 1),
        "plugins/self-learn/cli/src/self_learn/provider.py": (3, 2),
        "plugins/self-learn/cli/src/self_learn/analyst.py": (8, 0),
        "plugins/self-learn/cli/tests/conftest.py": (10, 0),
        "plugins/self-learn/cli/tests/fixtures/fake_claude.py": (40, 0),
        "plugins/self-learn/cli/tests/test_invocation.py": (22, 6),
        "plugins/self-learn/cli/tests/test_invocation_sdk.py": (22, 8),
        "plugins/self-learn/cli/tests/test_doctor_invocation.py": (10, 4),
    }
    for relpath, (max_ins, max_del) in bounds.items():
        out = subprocess.run(
            ["git", "diff", "--numstat", f"{_BASE_SHA}..HEAD", "--", relpath],
            cwd=_REPO_ROOT, capture_output=True, text=True,
        ).stdout.strip()
        if not out:
            out = subprocess.run(
                ["git", "diff", "--numstat", f"{_BASE_SHA}", "--", relpath],
                cwd=_REPO_ROOT, capture_output=True, text=True,
            ).stdout.strip()
        if not out:
            continue
        ins_s, del_s, _ = out.split("\t")
        ins, dele = int(ins_s), int(del_s)
        if relpath.endswith("fake_claude.py"):
            ins -= 2  # the two SCENARIOS dict lines are excluded from the cap
        assert ins <= max_ins, (relpath, "insertions", ins, max_ins)
        assert dele <= max_del, (relpath, "deletions", dele, max_del)
